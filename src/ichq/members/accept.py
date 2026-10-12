"""Einladung annehmen (M3). Läuft über mehrere Datenbankrollen, jede mit nur ihrem Recht:

1. ``ichq_auth`` liest die Einladung per Token-Hash (die Firma ist vorher unbekannt).
2. Neues Konto: ``ichq_platform`` legt es an, ``ichq_auth`` setzt das Passwort.
3. ``ichq_app`` im Mandantenkontext der Einladung: Einladung **atomar** als angenommen markieren und
   Mitgliedschaft anlegen — in EINER Transaktion. Wer zweimal annimmt, verliert beim zweiten Mal.

Bestehende Konten werden NIE automatisch verknüpft: Annehmen geht nur angemeldet, mit genau dem Konto,
an dessen E-Mail die Einladung ging (Zustimmung durch die Handlung selbst).
Alle Fehler zum Token (unbekannt, abgelaufen, benutzt, widerrufen, Firma inaktiv) sehen gleich aus.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text

from ichq.audit.service import record as audit
from ichq.auth import account
from ichq.auth.passwords import check_policy
from ichq.auth.tokens import hash_token
from ichq.core.config import Settings
from ichq.core.errors import AppError, Conflict, PermissionDenied, ValidationFailed
from ichq.core.ids import uuid7
from ichq.db.engine import Engines
from ichq.db.session import auth_transaction, platform_transaction, tenant_transaction
from ichq.identity.service import create_user


class InvalidInvitation(AppError):
    status, code, title = 400, "invalid_token", "Einladung ungültig"


class AccountExists(AppError):
    status, code, title = 409, "account_exists", "Konto existiert bereits"


@dataclass(frozen=True)
class Found:
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str


def _finden(engines: Engines, token: str) -> Found:
    if not token or len(token) > 128:
        raise InvalidInvitation("Die Einladung ist ungültig oder abgelaufen.")
    with auth_transaction(engines.auth) as s:
        r = s.execute(text("""SELECT id, tenant_id, email,
                                     accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now() AS gueltig
                              FROM invitations WHERE token_hash = :h"""), {"h": hash_token(token)}).one_or_none()
    if r is None or not r.gueltig:
        raise InvalidInvitation("Die Einladung ist ungültig oder abgelaufen.")
    return Found(r.id, r.tenant_id, r.email)


def _einloesen(engines: Engines, inv: Found, user_id: uuid.UUID) -> str:
    """Mandanten-Transaktion: Einladung atomar verbrauchen, Mitgliedschaft anlegen/reaktivieren."""
    with tenant_transaction(engines.app, inv.tenant_id) as s:
        if s.execute(text("SELECT status FROM tenants")).scalar() != "active":
            raise InvalidInvitation("Die Einladung ist ungültig oder abgelaufen.")
        vorhanden = s.execute(text("SELECT id, status FROM memberships WHERE user_id = :u FOR UPDATE"),
                              {"u": user_id}).one_or_none()
        if vorhanden is not None and vorhanden.status in ("active", "suspended"):
            raise Conflict("Bereits Mitglied dieser Firma" if vorhanden.status == "active"
                           else "Mitgliedschaft ist gesperrt — bitte die Firma kontaktieren")
        titel = s.execute(text("""UPDATE invitations SET accepted_at = now()
                                  WHERE id = :i AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now()
                                  RETURNING title"""), {"i": inv.id}).one_or_none()
        if titel is None:
            raise InvalidInvitation("Die Einladung ist ungültig oder abgelaufen.")
        if vorhanden is None:
            mid = s.execute(text("""INSERT INTO memberships(id, tenant_id, user_id, status, title)
                                    VALUES (:id, :t, :u, 'active', :ti) RETURNING id"""),
                            {"id": uuid7(), "t": inv.tenant_id, "u": user_id, "ti": titel.title}).scalar_one()
        else:   # früher ausgetreten ('left' / 'invited'): wieder aktiv — aber OHNE alte Rechte (Audit B1)
            mid = vorhanden.id
            # Wer einlädt, braucht nur users.create; alte Rollen (bis Company Admin), Einzelrechte und manuelle
            # Freigaben dürfen so nicht zurückkommen. Rechte vergibt danach jemand mit roles.assign (Delegation).
            for sql in ("DELETE FROM membership_roles WHERE membership_id = :m",
                        "DELETE FROM permission_overrides WHERE membership_id = :m",
                        "DELETE FROM object_grants WHERE membership_id = :m AND source = 'manual'"):
                s.execute(text(sql), {"m": mid})
            s.execute(text("UPDATE memberships SET status = 'active' WHERE id = :m"), {"m": mid})
        s.execute(text("UPDATE invitations SET accepted_membership_id = :m WHERE id = :i"), {"m": mid, "i": inv.id})
        pid = str(s.execute(text("SELECT public_id FROM memberships WHERE id = :m"), {"m": mid}).scalar_one())
        ipid = s.execute(text("SELECT public_id FROM invitations WHERE id = :i"), {"i": inv.id}).scalar_one()
        audit(s, "invitation.accepted", actor_membership_id=mid, target_type="invitation", target_id=ipid,
              data={"member": pid, "rejoined": vorhanden is not None})
    return pid


def accept_new(engines: Engines, settings: Settings, token: str, *, display_name: str, password: str) -> str:
    """Neues Konto über die Einladung. Gibt die öffentliche ID der Mitgliedschaft zurück."""
    inv = _finden(engines, token)
    if not display_name.strip() or len(display_name) > 120:
        raise ValidationFailed("display_name: 1–120 Zeichen")
    verstoss = check_policy(password, email=inv.email)
    if verstoss:
        raise ValidationFailed(verstoss.message)
    _vorab_pruefen(engines, inv)   # Firma aktiv, Einladung offen — bevor ein Konto entsteht (Audit F7)
    with platform_transaction(engines.platform) as s:
        vorhanden = s.execute(text("SELECT id FROM users WHERE lower(email) = :e"), {"e": inv.email}).scalar()
        if vorhanden is not None and not _verwaist(engines, vorhanden):
            raise AccountExists("Für diese E-Mail gibt es schon ein Konto. Bitte anmelden und dort annehmen.")
        if vorhanden is None:
            uid = create_user(s, email=inv.email, display_name=display_name)
        else:   # Rest eines gescheiterten Annehmens (ohne Passwort, ohne Firma): weiterverwenden
            uid = vorhanden
            s.execute(text("UPDATE users SET display_name = :n WHERE id = :u"), {"n": display_name, "u": uid})
    with auth_transaction(engines.auth) as s:
        o = account.set_password_from_invitation(s, settings, uid, password)
    if not o.ok:
        raise ValidationFailed(str(o.data.get("message") or "Passwort erfüllt die Regeln nicht"))
    try:
        return _einloesen(engines, inv, uid)
    except Exception:   # Wettlauf (Widerruf, Pause): kein aktives Konto ohne Firma zurücklassen
        with auth_transaction(engines.auth) as s:
            s.execute(text("UPDATE users SET password_hash = NULL, status = 'pending' WHERE id = :u"), {"u": uid})
        raise


def _vorab_pruefen(engines: Engines, inv: Found) -> None:
    with tenant_transaction(engines.app, inv.tenant_id) as s:
        offen = s.execute(text("""SELECT 1 FROM invitations i, tenants t
                                  WHERE i.id = :i AND t.status = 'active' AND i.accepted_at IS NULL
                                    AND i.revoked_at IS NULL AND i.expires_at > now()"""), {"i": inv.id}).scalar()
    if not offen:
        raise InvalidInvitation("Die Einladung ist ungültig oder abgelaufen.")


def _verwaist(engines: Engines, uid: uuid.UUID) -> bool:
    """Konto ohne Passwort, im Status pending und ohne jede Mitgliedschaft."""
    with auth_transaction(engines.auth, user_id=uid) as s:
        return bool(s.execute(text("""SELECT u.status = 'pending' AND u.password_hash IS NULL
                                             AND NOT EXISTS (SELECT 1 FROM memberships m WHERE m.user_id = u.id)
                                      FROM users u WHERE u.id = :u"""), {"u": uid}).scalar())


def accept_existing(engines: Engines, token: str, *, user_id: uuid.UUID) -> str:
    """Angemeldetes Konto nimmt an — nur, wenn die Einladung an genau seine E-Mail ging."""
    inv = _finden(engines, token)
    with auth_transaction(engines.auth, user_id=user_id) as s:
        email = s.execute(text("SELECT lower(email) FROM users WHERE id = :u"), {"u": user_id}).scalar()
    if email != inv.email:
        raise PermissionDenied("Diese Einladung gilt für ein anderes Konto.")
    return _einloesen(engines, inv, user_id)
