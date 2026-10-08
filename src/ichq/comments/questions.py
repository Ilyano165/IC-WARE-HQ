"""Rückfragen über alle sichtbaren Objekte (D0, ADR-014).

Eine Rückfrage ist ein Kommentar ``kind = 'question'``. **Offen** heißt (abgeleitet, keine eigene Spalte):
nicht gelöscht UND am selben Objekt gibt es danach keinen (nicht gelöschten) Kommentar einer ANDEREN Person.
Antwortet nur der Fragesteller selbst (Nachtrag), bleibt sie offen. Sichtbar ist nur, was der Principal über
``visible_clause`` sehen darf — dieselbe Regel wie überall.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import and_, exists, select
from sqlalchemy.orm import Session, aliased

from ichq.authz.service import Principal
from ichq.comments.models import Comment
from ichq.db.paging import SortKey, keyset
from ichq.objects.models import ObjectRow
from ichq.objects.visibility import visible_clause

SORT = SortKey("created_at", Comment.created_at, "ts")


def open_clause() -> Any:
    antwort = aliased(Comment)
    beantwortet = exists().where(antwort.object_id == Comment.object_id, antwort.tenant_id == Comment.tenant_id,
                                 antwort.created_at > Comment.created_at, antwort.deleted_at.is_(None),
                                 antwort.author_membership_id != Comment.author_membership_id)
    return and_(Comment.deleted_at.is_(None), ~beantwortet)


def base(principal: Principal, *, open_only: bool) -> Any:
    """``select(Comment, ObjectRow)`` über sichtbare Objekte — für Liste und Dashboard-Zahl."""
    stmt = (select(Comment, ObjectRow)
            .join(ObjectRow, (ObjectRow.id == Comment.object_id) & (ObjectRow.tenant_id == Comment.tenant_id))
            .where(Comment.kind == "question", visible_clause(principal)))
    return stmt.where(open_clause()) if open_only else stmt


def list_questions(session: Session, principal: Principal, *, open_only: bool, cursor: str | None,
                   limit: int | None) -> tuple[list[Any], str | None]:
    seite = keyset(session, base(principal, open_only=open_only), SORT, Comment.id, desc=True, cursor=cursor,
                   limit=limit)
    return list(seite.rows), seite.next_cursor
