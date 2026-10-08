"""Aktivitäten schreiben und als Verlauf lesen. Für Audit siehe ``ichq.audit`` — bewusst getrennt."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ichq.activity.models import Activity
from ichq.authz.service import Principal
from ichq.core.errors import ValidationFailed
from ichq.db.paging import SortKey, keyset
from ichq.db.session import current_tenant_id
from ichq.objects.models import ObjectRow
from ichq.objects.visibility import visible_clause

# Verben, die die Plattform kennt. Reservierte Verben schreiben die künftigen Fachmodule.
VERBS: dict[str, str] = {
    "document.uploaded": "Beleg/Dokument hochgeladen",
    "document.reviewed": "Beleg/Dokument geprüft",
    "invoice.created": "Rechnung erstellt",
    "payment.received": "Zahlung eingegangen",
    "task.created": "Aufgabe erstellt",
    "task.updated": "Aufgabe geändert",
    "task.status_changed": "Aufgabenstatus geändert",
    "task.assigned": "Aufgabe zugewiesen",
    "comment.created": "Kommentar geschrieben",
    "comment.question_asked": "Rückfrage gestellt",
    "comment.edited": "Kommentar bearbeitet",
    "comment.deleted": "Kommentar gelöscht",
    "project.status_changed": "Projektstatus geändert",
    "object.linked": "Verknüpfung angelegt",
    "object.unlinked": "Verknüpfung entfernt",
    "object.shared": "Freigegeben",
    "object.unshared": "Freigabe entzogen",
}
SORT = SortKey("occurred_at", Activity.occurred_at, "ts")


def record(session: Session, object_id: uuid.UUID, verb: str, *, actor_membership_id: uuid.UUID | None,
           data: dict[str, Any] | None = None) -> None:
    """In derselben Transaktion wie die fachliche Änderung. ``data`` bleibt klein und ohne Beträge/Texte."""
    if verb not in VERBS:
        raise ValueError(f"Unbekanntes Aktivitätsverb: {verb}")
    session.add(Activity(tenant_id=current_tenant_id(session), object_id=object_id, verb=verb,
                         actor_membership_id=actor_membership_id, data=data or {}))


@dataclass(frozen=True)
class FeedFilter:
    object_id: uuid.UUID | None = None
    verb: str | None = None
    object_type: str | None = None
    actor_membership_id: uuid.UUID | None = None
    since: datetime | None = None
    until: datetime | None = None


def feed(session: Session, principal: Principal, f: FeedFilter, *, cursor: str | None, limit: int | None,
         ascending: bool = False) -> tuple[list[Any], str | None]:
    """Chronologischer Verlauf, nur über Objekte, die der Principal sehen darf. Neueste zuerst."""
    if f.verb is not None and f.verb not in VERBS:
        raise ValidationFailed("verb ist unbekannt")
    stmt = (select(Activity, ObjectRow.public_id, ObjectRow.type, ObjectRow.title)
            .join(ObjectRow, (ObjectRow.id == Activity.object_id) & (ObjectRow.tenant_id == Activity.tenant_id))
            .where(visible_clause(principal)))
    if f.object_id is not None:
        stmt = stmt.where(Activity.object_id == f.object_id)
    if f.verb is not None:
        stmt = stmt.where(Activity.verb == f.verb)
    if f.object_type is not None:
        stmt = stmt.where(ObjectRow.type == f.object_type)
    if f.actor_membership_id is not None:
        stmt = stmt.where(Activity.actor_membership_id == f.actor_membership_id)
    if f.since is not None:
        stmt = stmt.where(Activity.occurred_at >= f.since)
    if f.until is not None:
        stmt = stmt.where(Activity.occurred_at < f.until)
    seite = keyset(session, stmt, SORT, Activity.id, desc=not ascending, cursor=cursor, limit=limit)
    return list(seite.rows), seite.next_cursor
