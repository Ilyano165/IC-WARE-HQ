"""Kommentare an Fachobjekten.

Regeln (docs/core-permissions.md):
* Lesen: ``comments.read`` + Objekt sichtbar.  Schreiben: ``comments.create`` + Objekt sichtbar.
* Bearbeiten: nur der Autor, nur innerhalb von ``EDIT_WINDOW`` nach dem Erstellen, nie nach dem Löschen.
  Erwähnungen ändern sich beim Bearbeiten nicht (keine nachträglichen Benachrichtigungen).
* Löschen: der Autor jederzeit; andere nur mit ``comments.moderate``. Gelöscht wird weich: Der Text wird
  geleert, die Hülle (wer, wann, gelöscht von) bleibt — Audit und Aktivität bleiben unverändert.
* Erwähnungen: nur aktive Mitglieder dieser Firma, höchstens ``MAX_MENTIONS``. Benachrichtigt wird nur,
  wer das Objekt sehen darf (Prüfung beim Zustellen, ``ichq.notifications``).
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ichq.activity.service import record as activity
from ichq.audit.service import record as audit
from ichq.authz.service import Principal, decide
from ichq.comments.models import COMMENT_KINDS, MAX_BODY, Comment, CommentMention
from ichq.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from ichq.db.paging import SortKey, keyset
from ichq.db.session import current_tenant_id
from ichq.jobs.service import emit_event
from ichq.objects.models import ObjectRow
from ichq.objects.service import check_public_id, member
from ichq.objects.visibility import visible_clause

EDIT_WINDOW = timedelta(minutes=15)
MAX_MENTIONS = 20
SORT = SortKey("created_at", Comment.created_at, "ts")


def _text(body: str) -> str:
    body = body.strip()
    if not body or len(body) > MAX_BODY:
        raise ValidationFailed(f"body: 1–{MAX_BODY} Zeichen")
    return body


def create(session: Session, principal: Principal, obj: ObjectRow, *, body: str, kind: str = "note",
           mentions: list[str] | None = None) -> Comment:
    if kind not in COMMENT_KINDS:
        raise ValidationFailed("kind ist ungültig")
    refs = list(dict.fromkeys(mentions or []))
    if len(refs) > MAX_MENTIONS:
        raise ValidationFailed(f"Höchstens {MAX_MENTIONS} Erwähnungen")
    erwaehnt = [member(session, r) for r in refs]     # fremde/inaktive Mitglieder → 404
    c = Comment(tenant_id=current_tenant_id(session), object_id=obj.id, author_membership_id=principal.membership_id,
                kind=kind, body=_text(body))
    session.add(c)
    session.flush()
    for m in erwaehnt:
        session.add(CommentMention(tenant_id=c.tenant_id, comment_id=c.id, membership_id=m.id))
    verb = "comment.question_asked" if kind == "question" else "comment.created"
    activity(session, obj.id, verb, actor_membership_id=principal.membership_id, data={"comment": c.public_id})
    audit(session, "comment.created", actor_membership_id=principal.membership_id, target_type=obj.type,
          target_id=obj.public_id, data={"comment": c.public_id, "kind": kind, "length": len(c.body),
                                         "mentions": [m.public_id for m in erwaehnt]})
    emit_event(session, "comment.created", {"comment_id": str(c.id)})
    return c


def load(session: Session, principal: Principal, ref: str) -> tuple[Comment, ObjectRow]:
    """Kommentar, dessen Objekt der Principal sehen darf — sonst 404."""
    check_public_id(ref)
    zeile = session.execute(
        select(Comment, ObjectRow).join(ObjectRow, (ObjectRow.id == Comment.object_id)
                                        & (ObjectRow.tenant_id == Comment.tenant_id))
        .where(Comment.public_id == ref, visible_clause(principal))).one_or_none()
    if zeile is None:
        raise NotFound()
    return zeile[0], zeile[1]


def edit(session: Session, principal: Principal, ref: str, body: str) -> Comment:
    c, obj = load(session, principal, ref)
    if c.author_membership_id != principal.membership_id:
        raise PermissionDenied("Nur der Autor darf einen Kommentar bearbeiten")
    if c.deleted_at is not None:
        raise Conflict("Gelöschte Kommentare können nicht bearbeitet werden")
    jetzt = session.scalar(select(func.now()))
    if jetzt is None or jetzt - c.created_at > EDIT_WINDOW:
        raise Conflict(f"Kommentare können nur {int(EDIT_WINDOW.total_seconds() // 60)} Minuten lang "
                       "bearbeitet werden")
    alt = len(c.body)
    c.body, c.edited_at = _text(body), jetzt
    session.flush()
    activity(session, obj.id, "comment.edited", actor_membership_id=principal.membership_id,
             data={"comment": c.public_id})
    audit(session, "comment.edited", actor_membership_id=principal.membership_id, target_type=obj.type,
          target_id=obj.public_id, data={"comment": c.public_id, "length_before": alt, "length": len(c.body)})
    return c


def delete(session: Session, principal: Principal, ref: str) -> None:
    c, obj = load(session, principal, ref)
    eigener = c.author_membership_id == principal.membership_id
    if not eigener and not decide(principal, "comments.moderate"):
        raise PermissionDenied("Fremde Kommentare löschen nur Moderatoren")
    if c.deleted_at is not None:
        return
    laenge = len(c.body)
    c.body, c.deleted_at, c.deleted_by_membership_id = "", session.scalar(select(func.now())), principal.membership_id
    session.flush()
    activity(session, obj.id, "comment.deleted", actor_membership_id=principal.membership_id,
             data={"comment": c.public_id})
    audit(session, "comment.deleted", actor_membership_id=principal.membership_id, target_type=obj.type,
          target_id=obj.public_id, data={"comment": c.public_id, "by_author": eigener, "length": laenge})


def mentions_of(session: Session, comment_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    if not comment_ids:
        return {}
    out: dict[uuid.UUID, list[uuid.UUID]] = {}
    for cid, mid in session.execute(select(CommentMention.comment_id, CommentMention.membership_id)
                                    .where(CommentMention.comment_id.in_(comment_ids))).all():
        out.setdefault(cid, []).append(mid)
    return out


def list_for(session: Session, obj: ObjectRow, *, cursor: str | None,
             limit: int | None) -> tuple[list[Any], str | None]:
    """Kommentare eines (bereits als sichtbar aufgelösten) Objekts, älteste zuerst."""
    seite = keyset(session, select(Comment).where(Comment.object_id == obj.id), SORT, Comment.id,
                   desc=False, cursor=cursor, limit=limit)
    return list(seite.rows), seite.next_cursor
