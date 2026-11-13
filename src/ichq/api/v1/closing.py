"""Monatsabschluss (ADR-020 Nr. 7) und Export (Nr. 11).

Abschließen/Wiedereröffnen: ``finance.approve`` (Wiedereröffnen nur mit Grund, im Audit). Export: ``finance.export``,
internes CSV-Format ``ichq-buchungen-v1`` — keine DATEV-Kompatibilität behauptet. Jeder Download wird protokolliert.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field

from ichq.api.security import TenantDB, require, tenant_db
from ichq.api.v1.common import Strict, refs_for, writing
from ichq.audit.service import record as audit
from ichq.authz.service import Principal
from ichq.db.session import TenantSession
from ichq.finance import closing, export
from ichq.finance.models_closing import Export, MonthClose
from ichq.tenancy.service import company_today

router = APIRouter(prefix="/api/v1", tags=["closing"])
Monat = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class CloseIn(Strict):
    month: Monat
    note: str = Field(default="", max_length=500)
    confirm_warnings: bool = False


class ReopenIn(Strict):
    month: Monat
    reason: str = Field(min_length=10, max_length=500)


class ExportIn(Strict):
    period_from: date
    period_to: date


def close_out(s: TenantSession, m: MonthClose) -> dict[str, Any]:
    refs = refs_for(s, {m.closed_by_membership_id, m.reopened_by_membership_id})
    return {"closed_at": m.closed_at,
            "closed_by": refs.get(m.closed_by_membership_id) if m.closed_by_membership_id else None,
            "note": m.close_note, "warnings_at_close": m.warnings, "reopened_at": m.reopened_at,
            "reopened_by": refs.get(m.reopened_by_membership_id) if m.reopened_by_membership_id else None,
            "reopen_reason": m.reopen_reason}


def period_out(s: TenantSession, p: date) -> dict[str, Any]:
    aktiv = closing.active(s, p)
    return {"period": p.strftime("%Y-%m"), "closed": aktiv is not None, **closing.checks(s, p),
            "history": [close_out(s, m) for m in closing.history(s, p)]}


def export_out(s: TenantSession, e: Export) -> dict[str, Any]:
    refs = refs_for(s, {e.created_by_membership_id})
    return {"id": e.public_id, "format": e.format, "period_from": e.period_from, "period_to": e.period_to,
            "row_count": e.row_count, "sha256": e.sha256, "report": e.report, "created_at": e.created_at,
            "created_by": refs.get(e.created_by_membership_id) if e.created_by_membership_id else None,
            "datev_compatible": False}


@router.get("/periods")
def list_periods(p: Principal = Depends(require("finance.read")), db: TenantDB = Depends(tenant_db),
                 year: Annotated[int | None, Query(ge=2000, le=2100)] = None) -> dict[str, Any]:
    with db() as s:
        jahr = year or company_today(s).year
        monate = closing.overview(s, jahr)
        return {"year": jahr, "items": [{**x, "period": x["period"].strftime("%Y-%m")} for x in monate]}


@router.get("/periods/check")
def get_period(month: Annotated[str, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")],
               p: Principal = Depends(require("finance.read")), db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Prüfliste und Historie eines Monats."""
    with db() as s:
        return period_out(s, closing.period_of(month))


@router.post("/periods/close")
def close_period(body: CloseIn, p: Principal = Depends(require("finance.approve")),
                 db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Monat abschließen. Offene Punkte (fehlende Belege, Entwürfe, ungeprüfte Dokumente) müssen bestätigt werden."""
    with writing(db) as s:
        monat = closing.period_of(body.month)
        closing.close(s, p, monat, today=company_today(s), note=body.note, confirm_warnings=body.confirm_warnings)
        return period_out(s, monat)


@router.post("/periods/reopen")
def reopen_period(body: ReopenIn, p: Principal = Depends(require("finance.approve")),
                  db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Wiedereröffnen — nur mit Grund; Abschluss und Wiedereröffnung bleiben in der Historie."""
    with writing(db) as s:
        monat = closing.period_of(body.month)
        closing.reopen(s, p, monat, body.reason)
        return period_out(s, monat)


@router.get("/exports")
def list_exports(p: Principal = Depends(require("finance.export")),
                 db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        return {"items": [export_out(s, e) for e in export.history(s)]}


@router.post("/exports", status_code=201)
def create_export(body: ExportIn, p: Principal = Depends(require("finance.export")),
                  db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        return export_out(s, export.create(s, p, von=body.period_from, bis=body.period_to))


@router.get("/exports/{ref}")
def get_export(ref: str, p: Principal = Depends(require("finance.export")),
               db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        return export_out(s, export.get(s, ref))


@router.post("/exports/{ref}/repeat", status_code=201)
def repeat_export(ref: str, p: Principal = Depends(require("finance.export")),
                  db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Gleichen Zeitraum neu exportieren; ``report.changed_since_original`` vergleicht die Prüfsummen."""
    with writing(db) as s:
        alt = export.get(s, ref)
        return export_out(s, export.create(s, p, von=alt.period_from, bis=alt.period_to, repeats=alt))


@router.get("/exports/{ref}/download")
def download_export(ref: str, p: Principal = Depends(require("finance.export")),
                    db: TenantDB = Depends(tenant_db)) -> Response:
    with db() as s:
        e = export.get(s, ref)
        audit(s, "export.downloaded", actor_membership_id=p.membership_id, target_type="export", target_id=e.public_id)
        name = f"ichq-buchungen_{e.period_from.isoformat()}_{e.period_to.isoformat()}.csv"
        return Response(content="﻿" + e.content, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-SHA256": e.sha256,
                                 "Cache-Control": "no-store"})
