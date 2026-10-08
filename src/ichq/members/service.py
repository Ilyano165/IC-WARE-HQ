"""Mitglieder einer Firma (M3) — alles im Mandantenkontext (RLS).

Regeln (docs/m3-mandanten.md):
* Niemand deaktiviert sich selbst (dafür gibt es „Firma verlassen").
* Die letzte aktive Mitgliedschaft mit Admin-Recht (``ADMIN_RIGHT``) kann weder deaktiviert werden noch
  die Firma verlassen. Geprüft unter Sperre aller Mitgliedschaften der Firma — zwei gleichzeitige Anfragen
  können nicht beide „den anderen" entfernen.
* Einladungen: Token 256 Bit, nur SHA-256 gespeichert, 7 Tage, einmalig, widerrufbar; höchstens eine offene
  Einladung je E-Mail und Firma.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ichq.audit.service import record as audit
from ichq.auth.tokens import new_token
from ichq.authz.service import Principal
from ichq.core.errors import AppError, Conflict, NotFound, PermissionDenied, ValidationFailed
from ichq.db.paging import SortKey, keyset
from ichq.db.session import current_tenant_id
from ichq.identity.models import Membership, User
from ichq.members.models import Invitation

ADMIN_RIGHT = "users.deactivate"
INVITATION_DAYS = 7
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,}$")
_PUBLIC = re.compile(r"^[0-9a-f]{32}$")
STATUS = ("active", "suspended", "left", "invited")


class LastAdmin(AppError):
    status, code, title = 409, "last_admin", "Letzte Administration"


def _ref(ref: str) -> str:
    if not _PUBLIC.match(ref or ""):
        raise NotFound()
    return ref


def clean_email(email: str) -> str:
    email = email.strip().lower()
    if not _EMAIL.match(email):
        raise ValidationFailed("email ist ungültig")
    return email


# ---------- Mitglieder ----------
@dataclass(frozen=True)
class MemberRow:
    id: uuid.UUID
    public_id: str
    user_id: uuid.UUID
    status: str


def _member(session: Session, ref: str, *, lock: bool = False) -> MemberRow:
    stmt = select(Membership.id, Membership.public_id, Membership.user_id, Membership.status).where(
        Membership.public_id == _ref(ref))
    if lock:
        stmt = stmt.with_for_update()
    r = session.execute(stmt).one_or_none()
    if r is None:
        raise NotFound("Mitglied nicht gefunden")
    return MemberRow(r.id, r.public_id, r.user_id, r.status)


SORT = SortKey("display_name", User.display_name, "text")


def list_members(session: Session, *, status: str | None, q: str | None, cursor: str | None,
                 limit: int | None) -> tuple[list[Any], str | None]:
    stmt = (select(Membership.public_id, Membership.status, Membership.title, Membership.created_at,
                   User.display_name, User.email).join(User, User.id == Membership.user_id))
    if status is not None:
        if status not in STATUS:
            raise ValidationFailed("status ist ungültig")
        stmt = stmt.where(Membership.status == status)
    if q:
        muster = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(User.display_name.ilike(muster, escape="\\") | User.email.ilike(muster, escape="\\"))
    seite = keyset(session, stmt, SORT, Membership.id, desc=False, cursor=cursor, limit=limit)
    return list(seite.rows), seite.next_cursor


def _admins_ausser(session: Session, ausser: uuid.UUID) -> int:
    """Aktive Mitgliedschaften (ohne ``ausser``), die das Admin-Recht über eine nicht archivierte Rolle haben."""
    return int(session.execute(text("""
        SELECT count(DISTINCT m.id) FROM memberships m
        JOIN membership_roles mr ON mr.membership_id = m.id AND mr.tenant_id = m.tenant_id
        JOIN roles r ON r.id = mr.role_id AND r.tenant_id = mr.tenant_id AND r.archived_at IS NULL
        JOIN role_permissions rp ON rp.role_id = r.id AND rp.tenant_id = r.tenant_id
        WHERE m.status = 'active' AND m.id <> :x AND rp.permission = :p"""),
        {"x": ausser, "p": ADMIN_RIGHT}).scalar() or 0)


def _ist_admin(session: Session, membership_id: uuid.UUID) -> bool:
    return bool(session.execute(text("""
        SELECT 1 FROM membership_roles mr
        JOIN roles r ON r.id = mr.role_id AND r.tenant_id = mr.tenant_id AND r.archived_at IS NULL
        JOIN role_permissions rp ON rp.role_id = r.id AND rp.tenant_id = r.tenant_id
        WHERE mr.membership_id = :m AND rp.permission = :p LIMIT 1"""),
        {"m": membership_id, "p": ADMIN_RIGHT}).scalar())


def _last_admin_schutz(session: Session, membership_id: uuid.UUID) -> None:
    # Alle Mitgliedschaften der Firma sperren (RLS: nur diese Firma) — serialisiert konkurrierende Entfernungen
    session.execute(select(Membership.id).where(Membership.status == "active").with_for_update()).all()
    if _ist_admin(session, membership_id) and _admins_ausser(session, membership_id) == 0:
        raise LastAdmin("Die letzte aktive Mitgliedschaft mit Verwaltungsrecht kann nicht entfernt werden")


def deactivate(session: Session, principal: Principal, ref: str) -> MemberRow:
    m = _member(session, ref, lock=True)
    if m.id == principal.membership_id:
        raise PermissionDenied("Die eigene Mitgliedschaft kann nicht deaktiviert werden — „Firma verlassen“ nutzen")
    if m.status != "active":
        raise Conflict(f"Mitgliedschaft ist nicht aktiv ({m.status})")
    _last_admin_schutz(session, m.id)
    session.execute(update(Membership).where(Membership.id == m.id).values(status="suspended"))
    audit(session, "membership.deactivated", actor_membership_id=principal.membership_id, target_type="membership",
          target_id=m.public_id)
    return MemberRow(m.id, m.public_id, m.user_id, "suspended")


def leave(session: Session, principal: Principal) -> None:
    session.execute(select(Membership.id).where(Membership.id == principal.membership_id).with_for_update()).one()
    _last_admin_schutz(session, principal.membership_id)
    pid = session.scalar(select(Membership.public_id).where(Membership.id == principal.membership_id))
    session.execute(update(Membership).where(Membership.id == principal.membership_id).values(status="left"))
    audit(session, "membership.left", actor_membership_id=principal.membership_id, target_type="membership",
          target_id=pid)


# ---------- Einladungen ----------
def invite(session: Session, principal: Principal, *, email: str, title: str | None) -> tuple[Invitation, str]:
    """Gibt (Einladung, roher Token) zurück. Der rohe Token geht nur in die E-Mail, nie in Log/DB/Antwort."""
    email = clean_email(email)
    if title is not None and len(title.strip()) > 120:
        raise ValidationFailed("title: höchstens 120 Zeichen")
    schon = session.execute(text("""SELECT m.status FROM memberships m JOIN users u ON u.id = m.user_id
                                    WHERE lower(u.email) = :e"""), {"e": email}).scalar()
    if schon == "active":
        raise Conflict("Diese Person ist bereits Mitglied")
    roh, h = new_token()
    jetzt = session.scalar(select(func.now()))
    assert jetzt is not None
    inv = Invitation(tenant_id=current_tenant_id(session), email=email, title=(title or "").strip() or None,
                     token_hash=h, invited_by_membership_id=principal.membership_id,
                     created_at=jetzt, expires_at=jetzt + timedelta(days=INVITATION_DAYS))
    try:
        with session.begin_nested():
            session.add(inv)
            session.flush()
    except IntegrityError:
        raise Conflict("Für diese E-Mail gibt es bereits eine offene Einladung") from None
    audit(session, "invitation.created", actor_membership_id=principal.membership_id, target_type="invitation",
          target_id=inv.public_id, data={"email_domain": email.split("@", 1)[1]})
    return inv, roh


def revoke(session: Session, principal: Principal, ref: str) -> None:
    n = session.execute(update(Invitation).where(
        Invitation.public_id == _ref(ref), Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None),
    ).values(revoked_at=func.now(), revoked_by_membership_id=principal.membership_id)).rowcount  # type: ignore[attr-defined]
    if not n:
        raise NotFound("Keine offene Einladung")
    audit(session, "invitation.revoked", actor_membership_id=principal.membership_id, target_type="invitation",
          target_id=ref)


def list_invitations(session: Session, *, open_only: bool, cursor: str | None,
                     limit: int | None) -> tuple[list[Any], str | None]:
    stmt = select(Invitation, (Invitation.expires_at > func.now()).label("gueltig"))
    if open_only:
        stmt = stmt.where(Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None))
    seite = keyset(session, stmt, SortKey("created_at", Invitation.created_at, "ts"), Invitation.id, desc=True,
                   cursor=cursor, limit=limit)
    return list(seite.rows), seite.next_cursor
