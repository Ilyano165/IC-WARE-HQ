"""Benachrichtigungen, globale Suche und Audit (C0)."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response

from ichq.api.security import TenantDB, authenticated, require, tenant_db
from ichq.api.v1.common import DEFAULT, Cursor, Limit, refs_for
from ichq.audit import query as audit_query
from ichq.audit.service import record
from ichq.authz.service import Principal
from ichq.notifications import service as notifications
from ichq.objects.registry import GROUPS
from ichq.objects.service import member_refs
from ichq.search import service as search

router = APIRouter(prefix="/api/v1", tags=["inbox"])


@router.get("/notifications")
def list_notifications(p: Principal = Depends(authenticated()), db: TenantDB = Depends(tenant_db),
                       unread: bool = False, cursor: Cursor = None, limit: Limit = DEFAULT) -> dict[str, Any]:
    """Nur eigene Benachrichtigungen — und nur zu Objekten, die man (noch) sehen darf."""
    with db() as s:
        rows, weiter = notifications.list_for(s, p, unread_only=unread, cursor=cursor, limit=limit)
        return {"items": [{"id": n.public_id, "kind": n.kind, "title": n.title, "created_at": n.created_at,
                           "read": n.read_at is not None,
                           "object": {"id": pid, "type": typ} if pid else None} for n, pid, typ, *_ in rows],
                "next_cursor": weiter, "unread_count": notifications.unread_count(s, p)}


@router.post("/notifications/{ref}/read", status_code=204)
def mark_read(ref: str, p: Principal = Depends(authenticated()), db: TenantDB = Depends(tenant_db)) -> Response:
    with db() as s:     # Lesestatus ist kein Fachinhalt: auch in pausierten Firmen erlaubt
        notifications.mark_read(s, p, ref)
    return Response(status_code=204)


@router.post("/notifications/read-all")
def mark_all_read(p: Principal = Depends(authenticated()), db: TenantDB = Depends(tenant_db)) -> dict[str, int]:
    with db() as s:
        return {"updated": notifications.mark_all_read(s, p)}


@router.get("/search")
def global_search(q: Annotated[str, Query(min_length=search.MIN_LEN, max_length=search.MAX_LEN)],
                  p: Principal = Depends(authenticated()), db: TenantDB = Depends(tenant_db),
                  group: Annotated[list[str] | None, Query(max_length=len(GROUPS))] = None,
                  per_group: Annotated[int, Query(ge=1, le=search.MAX_PER_GROUP)] = search.DEFAULT_PER_GROUP,
                  ) -> dict[str, Any]:
    """Suche über alle Objekte, die der Aufrufer sehen darf — gruppiert. Rechte wirken serverseitig."""
    with db() as s:
        return search.search(s, p, q, per_group=per_group, groups=tuple(group) if group else GROUPS)


def _filter(action: str | None, target_type: str | None, target_id: str | None, since: datetime | None,
            until: datetime | None) -> audit_query.AuditFilter:
    return audit_query.AuditFilter(action=action, target_type=target_type, target_id=target_id, since=since,
                                   until=until)


@router.get("/audit")
def list_audit(p: Principal = Depends(require("audit.read")), db: TenantDB = Depends(tenant_db),
               action: Annotated[str | None, Query(max_length=80)] = None,
               target_type: Annotated[str | None, Query(max_length=40)] = None,
               target_id: Annotated[str | None, Query(max_length=80)] = None,
               since: datetime | None = None, until: datetime | None = None,
               cursor: Cursor = None, limit: Limit = DEFAULT) -> dict[str, Any]:
    """Audit der Firma, neueste zuerst. Es gibt bewusst KEINE Route zum Ändern oder Löschen."""
    with db() as s:
        rows, weiter = audit_query.page(s, _filter(action, target_type, target_id, since, until),
                                        cursor=cursor, limit=limit)
        refs = refs_for(s, {r[0].actor_membership_id for r in rows})
        return {"items": [{"action": e.action, "occurred_at": e.occurred_at, "target_type": e.target_type,
                           "target_id": e.target_id, "request_id": e.request_id, "data": e.data,
                           "actor": refs.get(e.actor_membership_id) if e.actor_membership_id else None}
                          for e, *_ in rows], "next_cursor": weiter}


@router.get("/audit/export")
def export_audit(p: Principal = Depends(require("audit.export")), db: TenantDB = Depends(tenant_db),
                 action: Annotated[str | None, Query(max_length=80)] = None,
                 target_type: Annotated[str | None, Query(max_length=40)] = None,
                 since: datetime | None = None, until: datetime | None = None,
                 max_rows: Annotated[int, Query(ge=1, le=audit_query.MAX_EXPORT)] = 5_000) -> Response:
    """CSV-Export (älteste zuerst, begrenzt). Der Export selbst wird im Audit protokolliert."""
    with db() as s:     # Lesen ist auch in pausierten Firmen erlaubt; das Audit des Exports ist Systemsache
        cache: dict[Any, str] = {}

        def actor(mid: Any) -> str:
            if mid is None:
                return ""
            if mid not in cache:
                cache[mid] = member_refs(s, {mid}).get(mid, {}).get("id", "")
            return cache[mid]
        inhalt, n, abgeschnitten = audit_query.export_csv(s, _filter(action, target_type, None, since, until),
                                                          max_rows=max_rows, actor_ref=actor)
        record(s, "audit.exported", actor_membership_id=p.membership_id,
               data={"rows": n, "truncated": abgeschnitten, "action": action, "target_type": target_type})
    return Response(inhalt, media_type="text/csv; charset=utf-8", headers={
        "content-disposition": "attachment; filename=audit.csv", "x-ichq-truncated": str(abgeschnitten).lower()})
