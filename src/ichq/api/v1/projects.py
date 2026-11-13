"""Projekte (ADR-020): Liste/Detail, Team (mit automatischer Freigabe), Projektzeiten."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field

from ichq.api.security import TenantDB, require, tenant_db
from ichq.api.v1.common import DEFAULT, Cursor, Limit, Strict, object_out, object_ref, refs_for, writing
from ichq.authz.service import Principal, decide
from ichq.core.errors import ValidationFailed
from ichq.db.session import TenantSession
from ichq.finance.profitability import profitability
from ichq.objects import service as objects
from ichq.objects.models import ObjectRow
from ichq.objects.visibility import can_see, visible_clause
from ichq.projects import service as projects
from ichq.projects.models import PROJECT_STATUS, Project, ProjectMember, TimeEntry
from ichq.tenancy.service import company_currency

router = APIRouter(prefix="/api/v1", tags=["projects"])
Status = Annotated[str, Field(pattern="^(" + "|".join(PROJECT_STATUS) + ")$")]
Priority = Annotated[str, Field(pattern="^(low|normal|high|urgent)$")]
Ref = Annotated[str | None, Field(default=None, max_length=64)]
Cent = Annotated[int, Field(ge=0, le=10**13)]


class ProjectFields(Strict):
    description: str | None = Field(default=None, max_length=20_000)
    status: Status | None = None
    priority: Priority | None = None
    customer: Ref = None
    owner: Ref = None
    start_date: date | None = None
    end_date: date | None = None
    budget_minor: Cent | None = None
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")


class ProjectIn(ProjectFields):
    name: str = Field(min_length=1, max_length=300)


class ProjectPatch(ProjectFields):
    name: str | None = Field(default=None, min_length=1, max_length=300)


class MemberIn(Strict):
    role: str | None = Field(default=None, max_length=100)
    hourly_cost_minor: Cent | None = None


class TimeIn(Strict):
    work_date: date
    minutes: int = Field(ge=1, le=1440)
    billable: bool = True
    description: str = Field(default="", max_length=500)
    member: Ref = None


def _team_out(s: TenantSession, p: Principal, liste: list[ProjectMember]) -> list[dict[str, Any]]:
    refs = refs_for(s, {x.membership_id for x in liste})
    kosten = decide(p, "finance.read")      # kalkulatorische Kostensätze nur für Finanzrechte
    return [{"member": refs.get(x.membership_id), "role": x.role,
             **({"hourly_cost_minor": x.hourly_cost_minor} if kosten else {})} for x in liste]


def project_out(s: TenantSession, p: Principal, pr: Project, o: ObjectRow, *, detail: bool = False) -> dict[str, Any]:
    refs = refs_for(s, {pr.owner_membership_id})
    kunde = object_ref(objects.by_id(s, pr.customer_id)) if pr.customer_id and can_see(s, p, pr.customer_id) else None
    aus = {**object_out(s, o), "name": o.title, "status": pr.status, "priority": pr.priority, "customer": kunde,
           "owner": refs.get(pr.owner_membership_id) if pr.owner_membership_id else None,
           "start_date": pr.start_date, "end_date": pr.end_date, "budget_minor": pr.budget_minor,
           "currency": pr.currency, "completed_at": pr.completed_at}
    if detail:
        aus |= {"description": pr.description, "team": _team_out(s, p, projects.team(s, pr.id)),
                "summary": projects.summary(s, pr.id)}
    return aus


def _wer(s: TenantSession, p: Principal, wert: str | None) -> uuid.UUID | None:
    if wert == "me":
        return p.membership_id
    return objects.member(s, wert, active_only=False).id if wert else None


@router.get("/projects")
def list_projects(p: Principal = Depends(require("projects.read")), db: TenantDB = Depends(tenant_db),
                  q: Annotated[str | None, Query(max_length=100)] = None,
                  status: Annotated[list[str] | None, Query(max_length=5)] = None,
                  customer: Annotated[str | None, Query(max_length=64)] = None,
                  owner: Annotated[str | None, Query(max_length=64, description="ID oder 'me'")] = None,
                  member: Annotated[str | None, Query(max_length=64, description="Teammitglied: ID oder 'me'")] = None,
                  archived: bool = False,
                  sort: Annotated[str, Query(pattern="^(name|created_at|start_date|end_date|priority)$")] = "name",
                  order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
                  cursor: Cursor = None, limit: Limit = DEFAULT) -> dict[str, Any]:
    if status and not set(status) <= set(PROJECT_STATUS):
        raise ValidationFailed(f"status muss aus {list(PROJECT_STATUS)} sein")
    with db() as s:
        kunde = objects.resolve(s, p, customer, type_="customer").id if customer else None
        f = projects.ProjectFilter(q=q, status=tuple(status or ()), customer_id=kunde,
                                   owner_membership_id=_wer(s, p, owner), team_membership_id=_wer(s, p, member),
                                   archived=archived)
        rows, weiter = projects.list_projects(s, visible_clause(p), f, sort=sort, desc=order == "desc",
                                              cursor=cursor, limit=limit)
        return {"items": [project_out(s, p, pr, o) for pr, o, *_ in rows], "next_cursor": weiter}


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, p: Principal = Depends(require("projects.create")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        pr, o = projects.create(s, p, name=body.name, werte=body.model_dump(exclude={"name"}, exclude_none=True),
                                currency=company_currency(s))
        return project_out(s, p, pr, o, detail=True)


@router.get("/projects/{ref}")
def get_project(ref: str, p: Principal = Depends(require("projects.read")),
                db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        pr, o = projects.get(s, p, ref)
        return project_out(s, p, pr, o, detail=True)


@router.get("/projects/{ref}/profitability")
def project_profitability(ref: str, p: Principal = Depends(require("projects.read", "finance.read")),
                          db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Erlös, Ausgaben, Personalkosten, Marge — mit ``gaps``, wo die Zahl unvollständig ist (``complete``)."""
    with db() as s:
        pr, _o = projects.get(s, p, ref)
        return profitability(s, visible_clause(p), pr)


@router.patch("/projects/{ref}")
def update_project(ref: str, body: ProjectPatch, p: Principal = Depends(require("projects.update")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailed("Keine Änderung angegeben")
    for pflicht in ("name", "status", "priority", "currency"):
        if pflicht in changes and changes[pflicht] is None:
            raise ValidationFailed(f"{pflicht} darf nicht leer sein")
    with writing(db) as s:
        pr, o = projects.update(s, p, ref, changes)
        return project_out(s, p, pr, o, detail=True)


@router.put("/projects/{ref}/members/{member}")
def put_member(ref: str, member: str, body: MemberIn | None = None,
               p: Principal = Depends(require("projects.assign")), db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Ins Team aufnehmen oder Rolle/Kostensatz ändern. Ohne objects.read_all gibt es eine Projektfreigabe."""
    body = body or MemberIn()
    with writing(db) as s:
        projects.put_member(s, p, ref, member, role=body.role, hourly_cost_minor=body.hourly_cost_minor,
                            cost_given="hourly_cost_minor" in body.model_fields_set)
        pr, o = projects.get(s, p, ref)
        return project_out(s, p, pr, o, detail=True)


@router.delete("/projects/{ref}/members/{member}", status_code=204)
def remove_member(ref: str, member: str, p: Principal = Depends(require("projects.assign")),
                  db: TenantDB = Depends(tenant_db)) -> Response:
    with writing(db) as s:
        projects.remove_member(s, p, ref, member)
    return Response(status_code=204)


def time_out(s: TenantSession, e: TimeEntry) -> dict[str, Any]:
    refs = refs_for(s, {e.membership_id})
    return {"id": e.public_id, "member": refs.get(e.membership_id), "work_date": e.work_date, "minutes": e.minutes,
            "billable": e.billable, "description": e.description, "created_at": e.created_at}


@router.get("/projects/{ref}/time-entries")
def list_time(ref: str, p: Principal = Depends(require("projects.read")),
              db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        pr, _ = projects.get(s, p, ref)
        return {"items": [time_out(s, e) for e in projects.time_entries(s, pr.id)]}


@router.post("/projects/{ref}/time-entries", status_code=201)
def add_time(ref: str, body: TimeIn, p: Principal = Depends(require("projects.read")),
             db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Projektzeit (Aufwand) — eigene als Teammitglied, für andere mit projects.assign. Keine Arbeitszeiterfassung."""
    with writing(db) as s:
        return time_out(s, projects.add_time(s, p, ref, work_date=body.work_date, minutes=body.minutes,
                                             billable=body.billable, description=body.description,
                                             member_ref=body.member))


@router.delete("/projects/{ref}/time-entries/{entry}", status_code=204)
def delete_time(ref: str, entry: str, p: Principal = Depends(require("projects.read")),
                db: TenantDB = Depends(tenant_db)) -> Response:
    with writing(db) as s:
        projects.delete_time(s, p, ref, entry)
    return Response(status_code=204)
