"""Objekt-Referenzen, Verknüpfungen, Freigaben, Aktivitäten, Mitglieder (C0)."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field
from sqlalchemy import select

from ichq.activity import service as activities
from ichq.api.security import TenantDB, authenticated, require, tenant_db
from ichq.api.v1.common import DEFAULT, Cursor, Limit, Strict, object_out, refs_for, writing
from ichq.authz.service import Principal
from ichq.core.errors import ValidationFailed
from ichq.db.paging import SortKey, keyset
from ichq.identity.models import Membership, User
from ichq.objects import service as objects
from ichq.objects.registry import OBJECT_TYPES
from ichq.relations import service as relations

router = APIRouter(prefix="/api/v1", tags=["core"])


class LinkIn(Strict):
    target: str = Field(min_length=1, max_length=64)
    link_type: str = Field(min_length=1, max_length=24)


class GrantIn(Strict):
    member: str = Field(min_length=1, max_length=64)


@router.get("/objects/{ref}")
def get_object(ref: str, p: Principal = Depends(authenticated()), db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Jedes sichtbare Fachobjekt per öffentlicher ID. Unsichtbar/fremd/unbekannt → 404."""
    with db() as s:
        return object_out(s, objects.resolve(s, p, ref))


@router.get("/objects/{ref}/links")
def list_links(ref: str, p: Principal = Depends(authenticated()), db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        return {"items": relations.links_of(s, p, objects.resolve(s, p, ref))}


@router.post("/objects/{ref}/links", status_code=201)
def create_link(ref: str, body: LinkIn, p: Principal = Depends(authenticated()),
                db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        quelle = objects.resolve(s, p, ref)
        ziel = objects.resolve(s, p, body.target)
        link = relations.create_link(s, p, quelle, ziel, body.link_type)
        return {"id": link.public_id, "link_type": link.link_type, "source": quelle.public_id,
                "target": ziel.public_id}


@router.delete("/links/{ref}", status_code=204)
def delete_link(ref: str, p: Principal = Depends(authenticated()), db: TenantDB = Depends(tenant_db)) -> Response:
    with writing(db) as s:
        relations.delete_link(s, p, ref)
    return Response(status_code=204)


@router.get("/objects/{ref}/grants")
def list_grants(ref: str, p: Principal = Depends(require("objects.share")),
                db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        obj = objects.resolve(s, p, ref)
        ids = relations.grants_of(s, obj)
        refs = refs_for(s, set(ids))
        return {"items": [refs[i] for i in ids if i in refs]}


@router.post("/objects/{ref}/grants", status_code=201)
def create_grant(ref: str, body: GrantIn, p: Principal = Depends(require("objects.share")),
                 db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        obj = objects.resolve(s, p, ref)
        m = objects.member(s, body.member)
        neu = relations.grant(s, p, obj, m)
        return {"object": obj.public_id, "member": m.public_id, "created": neu}


@router.delete("/objects/{ref}/grants/{member}", status_code=204)
def delete_grant(ref: str, member: str, p: Principal = Depends(require("objects.share")),
                 db: TenantDB = Depends(tenant_db)) -> Response:
    with writing(db) as s:
        obj = objects.resolve(s, p, ref)
        relations.revoke(s, p, obj, objects.member(s, member, active_only=False))
    return Response(status_code=204)


def _feed(s: Any, p: Principal, f: activities.FeedFilter, cursor: str | None, limit: int,
          ascending: bool) -> dict[str, Any]:
    rows, weiter = activities.feed(s, p, f, cursor=cursor, limit=limit, ascending=ascending)
    refs = refs_for(s, {r[0].actor_membership_id for r in rows})
    return {"items": [{"verb": a.verb, "label": activities.VERBS[a.verb], "occurred_at": a.occurred_at,
                       "object": {"id": pid, "type": typ, "title": titel},
                       "actor": refs.get(a.actor_membership_id) if a.actor_membership_id else None,
                       "data": a.data} for a, pid, typ, titel, *_ in rows],
            "next_cursor": weiter}


@router.get("/activities")
def company_activities(p: Principal = Depends(require("activity.read")), db: TenantDB = Depends(tenant_db),
                       verb: Annotated[str | None, Query(max_length=48)] = None,
                       object_type: Annotated[str | None, Query(max_length=24)] = None,
                       actor: Annotated[str | None, Query(max_length=64)] = None,
                       since: datetime | None = None, until: datetime | None = None,
                       order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
                       cursor: Cursor = None, limit: Limit = DEFAULT) -> dict[str, Any]:
    """Chronologischer Verlauf der Firma — nur über Objekte, die der Aufrufer sehen darf."""
    with db() as s:
        if object_type is not None and object_type not in OBJECT_TYPES:
            raise ValidationFailed("object_type ist unbekannt")
        actor_id = objects.member(s, actor, active_only=False).id if actor else None
        f = activities.FeedFilter(verb=verb, object_type=object_type, actor_membership_id=actor_id,
                                  since=since, until=until)
        return _feed(s, p, f, cursor, limit, order == "asc")


@router.get("/objects/{ref}/activities")
def object_activities(ref: str, p: Principal = Depends(require("activity.read")), db: TenantDB = Depends(tenant_db),
                      order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
                      cursor: Cursor = None, limit: Limit = DEFAULT) -> dict[str, Any]:
    with db() as s:
        obj = objects.resolve(s, p, ref)
        return _feed(s, p, activities.FeedFilter(object_id=obj.id), cursor, limit, order == "asc")


_MITGLIED_SORT = SortKey("display_name", User.display_name, "text")


@router.get("/members")
def list_members(p: Principal = Depends(require("users.read")), db: TenantDB = Depends(tenant_db),
                 q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
                 cursor: Cursor = None, limit: Limit = DEFAULT) -> dict[str, Any]:
    """Aktive Mitglieder (für Zuweisung, Erwähnung, Freigabe). Nur öffentliche IDs und Anzeigename."""
    with db() as s:
        stmt = (select(Membership.public_id, User.display_name)
                .join(User, User.id == Membership.user_id).where(Membership.status == "active"))
        if q:
            muster = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            stmt = stmt.where(User.display_name.ilike(muster, escape="\\"))
        seite = keyset(s, stmt, _MITGLIED_SORT, Membership.id, desc=False, cursor=cursor, limit=limit)
        return {"items": [{"id": r.public_id, "display_name": r.display_name} for r in seite.rows],
                "next_cursor": seite.next_cursor}
