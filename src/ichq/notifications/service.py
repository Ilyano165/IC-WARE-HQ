"""Zentrale Notification Engine.

* ``deliver`` ist der EINZIGE Weg, eine Benachrichtigung zu erzeugen. Er prüft beim Zustellen:
  Mitgliedschaft aktiv, Firma nutzbar, das Recht der Benachrichtigungsart und — bei Objektbezug — dass der
  Empfänger das Objekt JETZT sehen darf. Sonst wird nichts zugestellt (und nichts verraten).
* Beim Lesen wird erneut gefiltert: Verliert jemand später das Recht auf ein Objekt, verschwinden die
  Benachrichtigungen dazu aus seiner Liste.
* Kanäle: ``in_app`` ist umgesetzt. ``email``/``push`` sind vorgesehen (Schema, Registry), aber nicht aktiv.
* Inhalt: nur ein kurzer Titel + Objektbezug, keine Beträge (M0).
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from ichq.authz.service import Principal, decide
from ichq.core.errors import NotFound
from ichq.db.paging import SortKey, keyset
from ichq.db.session import current_tenant_id
from ichq.notifications.models import Notification
from ichq.objects.models import ObjectRow
from ichq.objects.service import check_public_id
from ichq.objects.visibility import can_see, principal_for_membership, visible_clause


@dataclass(frozen=True)
class Kind:
    code: str
    requires: str | None          # zusätzliches Recht des Empfängers (neben Objekt-Sichtbarkeit)
    channels: tuple[str, ...] = ("in_app",)


KINDS: dict[str, Kind] = {k.code: k for k in (
    Kind("document.review_pending", "files.update"),     # „Beleg wartet auf Prüfung."
    Kind("comment.mention", "comments.read"),
    Kind("comment.question", "comments.read"),           # „Steuerberater hat eine Rückfrage."
    Kind("task.assigned", "tasks.read"),
    Kind("task.overdue", "tasks.read"),
    Kind("invoice.overdue", "invoices.read"),            # reserviert: Regel kommt mit dem Rechnungsmodul
    Kind("contract.expiring", "contracts.read"),         # reserviert: Regel kommt mit dem Vertragsmodul
)}

Channel = Callable[[Session, Principal, Kind, ObjectRow | None, str, str | None], bool]


def _in_app(session: Session, recipient: Principal, kind: Kind, obj: ObjectRow | None, title: str,
            dedup_key: str | None) -> bool:
    n = Notification(tenant_id=current_tenant_id(session), recipient_membership_id=recipient.membership_id,
                     kind=kind.code, channel="in_app", object_id=obj.id if obj else None, title=title[:200],
                     dedup_key=dedup_key)
    try:
        with session.begin_nested():
            session.add(n)
            session.flush()
    except IntegrityError:
        return False      # schon zugestellt (dedup_key)
    return True


CHANNELS: dict[str, Channel] = {"in_app": _in_app}   # email/push: noch nicht umgesetzt (docs/core-activity-model.md)


def deliver(session: Session, recipient_membership_id: uuid.UUID, kind_code: str, *, title: str,
            obj: ObjectRow | None = None, dedup_key: str | None = None) -> bool:
    """Zustellen mit Rechteprüfung. ``True`` nur, wenn mindestens ein Kanal zugestellt hat."""
    kind = KINDS.get(kind_code)
    if kind is None:
        raise ValueError(f"Unbekannte Benachrichtigungsart: {kind_code}")
    empfaenger = principal_for_membership(session, recipient_membership_id)
    if empfaenger is None:
        return False
    if kind.requires is not None and not decide(empfaenger, kind.requires):
        return False
    if obj is not None and not can_see(session, empfaenger, obj.id):
        return False
    zugestellt = False
    for kanal in kind.channels:
        fn = CHANNELS.get(kanal)
        if fn is not None and fn(session, empfaenger, kind, obj, title, dedup_key):
            zugestellt = True
    return zugestellt


SORT = SortKey("created_at", Notification.created_at, "ts")


def _sichtbar_fuer(principal: Principal) -> Any:
    """Eigene Benachrichtigungen, deren Objekt (falls vorhanden) der Principal JETZT sehen darf."""
    o2 = aliased(ObjectRow)     # eigener Alias: Außenabfragen joinen ObjectRow evtl. schon (Korrelation)
    sichtbar = exists().where(o2.id == Notification.object_id, o2.tenant_id == Notification.tenant_id,
                              visible_clause(principal, o2))
    return and_(Notification.recipient_membership_id == principal.membership_id,
                or_(Notification.object_id.is_(None), sichtbar))


def list_for(session: Session, principal: Principal, *, unread_only: bool, cursor: str | None,
             limit: int | None) -> tuple[list[Any], str | None]:
    stmt = (select(Notification, ObjectRow.public_id, ObjectRow.type)
            .outerjoin(ObjectRow, (ObjectRow.id == Notification.object_id)
                       & (ObjectRow.tenant_id == Notification.tenant_id))
            .where(_sichtbar_fuer(principal)))
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    seite = keyset(session, stmt, SORT, Notification.id, desc=True, cursor=cursor, limit=limit)
    return list(seite.rows), seite.next_cursor


def unread_count(session: Session, principal: Principal) -> int:
    return int(session.scalar(select(func.count()).select_from(Notification).where(
        _sichtbar_fuer(principal), Notification.read_at.is_(None))) or 0)


def mark_read(session: Session, principal: Principal, ref: str) -> None:
    check_public_id(ref)
    n = session.execute(update(Notification).where(
        Notification.public_id == ref, Notification.recipient_membership_id == principal.membership_id,
    ).values(read_at=func.coalesce(Notification.read_at, func.now()))).rowcount  # type: ignore[attr-defined]
    if not n:
        raise NotFound()


def mark_all_read(session: Session, principal: Principal) -> int:
    return int(session.execute(update(Notification).where(
        Notification.recipient_membership_id == principal.membership_id, Notification.read_at.is_(None),
    ).values(read_at=func.now())).rowcount)  # type: ignore[attr-defined]
