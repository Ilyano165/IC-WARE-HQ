"""Audit lesen und exportieren — nur lesend. Schreiben geht ausschließlich über ``ichq.audit.service.record``;
Ändern und Löschen verhindert die Datenbank (Trigger + fehlende Rechte), nicht nur dieser Code."""
from __future__ import annotations

import csv
import io
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ichq.audit.models import AuditEvent
from ichq.db.paging import SortKey, keyset

SORT = SortKey("occurred_at", AuditEvent.occurred_at, "ts")
MAX_EXPORT = 10_000


@dataclass(frozen=True)
class AuditFilter:
    action: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None


def _gefiltert(f: AuditFilter) -> Any:
    stmt = select(AuditEvent)
    if f.action:
        stmt = stmt.where(AuditEvent.action == f.action)
    if f.target_type:
        stmt = stmt.where(AuditEvent.target_type == f.target_type)
    if f.target_id:
        stmt = stmt.where(AuditEvent.target_id == f.target_id)
    if f.since:
        stmt = stmt.where(AuditEvent.occurred_at >= f.since)
    if f.until:
        stmt = stmt.where(AuditEvent.occurred_at < f.until)
    return stmt


def page(session: Session, f: AuditFilter, *, cursor: str | None, limit: int | None) -> tuple[list[Any], str | None]:
    seite = keyset(session, _gefiltert(f), SORT, AuditEvent.id, desc=True, cursor=cursor, limit=limit)
    return list(seite.rows), seite.next_cursor


def export_csv(session: Session, f: AuditFilter, *, max_rows: int,
               actor_ref: Callable[[uuid.UUID | None], str]) -> tuple[str, int, bool]:
    """CSV, älteste zuerst, höchstens ``max_rows`` (≤ MAX_EXPORT). Gibt (csv, Zeilen, abgeschnitten) zurück."""
    n = max(1, min(max_rows, MAX_EXPORT))
    rows = session.scalars(_gefiltert(f).order_by(AuditEvent.occurred_at, AuditEvent.id).limit(n + 1)).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["occurred_at", "action", "actor", "target_type", "target_id", "request_id", "data"])
    for e in rows[:n]:
        w.writerow([e.occurred_at.isoformat(), e.action, actor_ref(e.actor_membership_id), e.target_type or "",
                    e.target_id or "", e.request_id or "", json.dumps(e.data, ensure_ascii=False, sort_keys=True)])
    return buf.getvalue(), min(len(rows), n), len(rows) > n
