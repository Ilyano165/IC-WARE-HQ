"""Gemeinsame Bausteine der Core-Routen: strikte Eingabemodelle, Paginierung, Schreibschutz, Ausgabeformen."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel, ConfigDict

from ichq.api.security import TenantDB, usable_tenant
from ichq.core.errors import AppError
from ichq.db.paging import DEFAULT_LIMIT, MAX_LIMIT
from ichq.db.session import TenantSession
from ichq.objects.models import ObjectRow
from ichq.objects.service import member_refs

Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT, description=f"Seitengröße, höchstens {MAX_LIMIT}")]
Cursor = Annotated[str | None, Query(max_length=512, description="next_cursor der vorigen Seite")]
DEFAULT = DEFAULT_LIMIT


class TenantPaused(AppError):
    status, code, title = 403, "tenant_paused", "Firma ist pausiert — nur Lesen möglich"


class Strict(BaseModel):
    """Eingaben: unbekannte Felder sind ein Fehler, Leerzeichen am Rand werden entfernt."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MemberRef(BaseModel):
    id: str
    display_name: str


class ObjectRef(BaseModel):
    id: str
    type: str
    title: str


class Page(BaseModel):
    items: list[Any]
    next_cursor: str | None


@contextmanager
def writing(db: TenantDB) -> Iterator[TenantSession]:
    """Schreibende Transaktion. Pausierte Firmen dürfen lesen, aber nicht schreiben — für alle Core-Routen hier."""
    with db() as s:
        if usable_tenant(s).status != "active":
            raise TenantPaused()
        yield s


def object_ref(o: ObjectRow) -> dict[str, Any]:
    return {"id": o.public_id, "type": o.type, "title": o.title}


def object_out(s: TenantSession, o: ObjectRow) -> dict[str, Any]:
    refs = member_refs(s, {o.created_by_membership_id} if o.created_by_membership_id else set())
    return {**object_ref(o), "created_at": o.created_at, "updated_at": o.updated_at,
            "created_by": refs.get(o.created_by_membership_id) if o.created_by_membership_id else None,
            "archived": o.archived_at is not None}


def refs_for(s: TenantSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, dict[str, str]]:
    return member_refs(s, {i for i in ids if i is not None})


def ts(v: datetime | None) -> str | None:
    return v.isoformat() if v else None
