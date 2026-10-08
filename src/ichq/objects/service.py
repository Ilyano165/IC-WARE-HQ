"""Objekt-Referenzen anlegen und auflösen.

Die API kennt ausschließlich ``public_id``. Auflösen geschieht IMMER in der Mandanten-Transaktion und
IMMER über ``visible_clause`` — ein fremdes, unbekanntes oder nicht freigegebenes Objekt ist für den
Aufrufer nicht von „gibt es nicht" zu unterscheiden (404, docs/core-permissions.md).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ichq.authz.service import Principal
from ichq.core.errors import NotFound, ValidationFailed
from ichq.db.session import current_tenant_id
from ichq.objects.models import ObjectRow
from ichq.objects.registry import OBJECT_TYPES
from ichq.objects.visibility import visible_clause

PUBLIC_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_TITLE = 300


def check_public_id(ref: str) -> str:
    """Formfehler werden wie „nicht gefunden" behandelt — keine Unterscheidung nach außen."""
    if not isinstance(ref, str) or not PUBLIC_ID.match(ref):
        raise NotFound()
    return ref


def clean_title(title: str) -> str:
    t = " ".join(title.split())
    if not t or len(t) > MAX_TITLE:
        raise ValidationFailed(f"title: 1–{MAX_TITLE} Zeichen")
    return t


def create_object(session: Session, *, type_: str, title: str, actor_membership_id: uuid.UUID | None,
                  search_text: str | None = None) -> ObjectRow:
    typ = OBJECT_TYPES.get(type_)
    if typ is None:
        raise ValidationFailed("Unbekannter Objekttyp")
    obj = ObjectRow(tenant_id=current_tenant_id(session), type=type_, title=clean_title(title),
                    search_text=(search_text or None) and search_text[:4000],
                    created_by_membership_id=actor_membership_id)
    session.add(obj)
    session.flush()
    return obj


def resolve(session: Session, principal: Principal, ref: str, *, type_: str | None = None) -> ObjectRow:
    """Sichtbares Objekt per öffentlicher ID — oder ``NotFound``."""
    check_public_id(ref)
    stmt = select(ObjectRow).where(ObjectRow.public_id == ref, visible_clause(principal))
    if type_ is not None:
        stmt = stmt.where(ObjectRow.type == type_)
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        raise NotFound()
    return obj


def by_id(session: Session, object_id: uuid.UUID) -> ObjectRow:
    obj = session.get(ObjectRow, object_id)
    if obj is None:
        raise NotFound()
    return obj


@dataclass(frozen=True)
class Member:
    id: uuid.UUID
    public_id: str
    display_name: str
    status: str


def member(session: Session, ref: str, *, active_only: bool = True) -> Member:
    """Mitgliedschaft dieser Firma per öffentlicher ID. Fremde/inaktive → NotFound (RLS + Filter)."""
    check_public_id(ref)
    zeile = session.execute(text("""
        SELECT m.id, m.public_id, u.display_name, m.status FROM memberships m JOIN users u ON u.id = m.user_id
        WHERE m.public_id = :p"""), {"p": ref}).one_or_none()
    if zeile is None or (active_only and zeile.status != "active"):
        raise NotFound("Mitglied nicht gefunden")
    return Member(zeile.id, zeile.public_id, zeile.display_name, zeile.status)


def member_ref(session: Session, membership_id: uuid.UUID | None) -> dict[str, str] | None:
    if membership_id is None:
        return None
    zeile = session.execute(text("""
        SELECT m.public_id, u.display_name FROM memberships m JOIN users u ON u.id = m.user_id
        WHERE m.id = :m"""), {"m": membership_id}).one_or_none()
    return None if zeile is None else {"id": zeile.public_id, "display_name": zeile.display_name}


def member_refs(session: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, dict[str, str]]:
    """Öffentliche Referenzen für Mitgliedschaften (statt interner IDs in Antworten)."""
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    rows = session.execute(text("""
        SELECT m.id, m.public_id, u.display_name FROM memberships m JOIN users u ON u.id = m.user_id
        WHERE m.id = ANY(:ids)"""), {"ids": list(ids)}).all()
    return {r.id: {"id": r.public_id, "display_name": r.display_name} for r in rows}
