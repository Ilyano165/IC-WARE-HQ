"""Dokumente (C0): Upload als Rohdaten (kein Multipart), Liste, Prüfung, Download nur nach Virenprüfung."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from ichq.api.security import TenantDB, require, tenant_db
from ichq.api.state import AppState, get_state
from ichq.api.v1.common import DEFAULT, Cursor, Limit, Strict, object_out, refs_for, writing
from ichq.authz.service import Principal
from ichq.db.session import TenantSession
from ichq.documents import service as documents
from ichq.documents.models import Document
from ichq.objects.models import ObjectRow
from ichq.objects.visibility import visible_clause

router = APIRouter(prefix="/api/v1", tags=["documents"])


class ReviewIn(Strict):
    decision: Annotated[str, Field(pattern="^(approved|rejected)$")]


def document_out(s: TenantSession, d: Document, o: ObjectRow) -> dict[str, Any]:
    refs = refs_for(s, {d.reviewed_by_membership_id})
    return {**object_out(s, o), "filename": d.filename, "content_type": d.content_type, "size_bytes": d.size_bytes,
            "sha256": d.sha256, "scan_status": d.scan_status, "review_status": d.review_status,
            "reviewed_by": refs.get(d.reviewed_by_membership_id) if d.reviewed_by_membership_id else None,
            "reviewed_at": d.reviewed_at}


async def _lesen(request: Request) -> bytes:
    """Body mit harter Grenze lesen — nie mehr als MAX_BYTES + 1 im Speicher."""
    teile, groesse = [], 0
    async for stueck in request.stream():
        groesse += len(stueck)
        if groesse > documents.MAX_BYTES:
            raise documents.PayloadTooLarge(f"Höchstens {documents.MAX_BYTES // (1024 * 1024)} MiB")
        teile.append(stueck)
    return b"".join(teile)


@router.post("/documents", status_code=201)
async def upload(request: Request, filename: Annotated[str, Query(min_length=1, max_length=255)],
                 p: Principal = Depends(require("files.upload")), db: TenantDB = Depends(tenant_db),
                 state: AppState = Depends(get_state)) -> dict[str, Any]:
    """Datei als Request-Body; Typ aus ``Content-Type``. Neue Dateien sind in Quarantäne."""
    content_type = request.headers.get("content-type", "")
    daten = await _lesen(request)

    def speichern() -> dict[str, Any]:
        with writing(db) as s:
            d, o = documents.upload(s, state.storage, p, filename=filename, content_type=content_type, data=daten)
            return document_out(s, d, o)
    return await run_in_threadpool(speichern)


@router.get("/documents")
def list_documents(p: Principal = Depends(require("files.read")), db: TenantDB = Depends(tenant_db),
                   review_status: Annotated[str | None, Query(pattern="^(pending|approved|rejected)$")] = None,
                   sort: Annotated[str, Query(pattern="^(created_at|title)$")] = "created_at",
                   order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
                   cursor: Cursor = None, limit: Limit = DEFAULT) -> dict[str, Any]:
    with db() as s:
        rows, weiter = documents.list_documents(s, visible_clause(p), review_status=review_status, sort=sort,
                                                desc=order == "desc", cursor=cursor, limit=limit)
        return {"items": [document_out(s, d, o) for d, o, *_ in rows], "next_cursor": weiter}


@router.get("/documents/{ref}")
def get_document(ref: str, p: Principal = Depends(require("files.read")),
                 db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        d, o = documents.get(s, p, ref)
        return document_out(s, d, o)


@router.get("/documents/{ref}/content")
def download(ref: str, p: Principal = Depends(require("files.read")), db: TenantDB = Depends(tenant_db),
             state: AppState = Depends(get_state)) -> Response:
    with db() as s:
        d, daten = documents.content(s, state.storage, p, ref)
    return Response(daten, media_type=d.content_type, headers={
        "content-disposition": "attachment", "x-content-type-options": "nosniff"})


@router.post("/documents/{ref}/review")
def review(ref: str, body: ReviewIn, p: Principal = Depends(require("files.update")),
           db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """„Beleg geprüft": einmalig freigeben oder ablehnen."""
    with writing(db) as s:
        d, o = documents.review(s, p, ref, body.decision)
        return document_out(s, d, o)
