"""CRM (ADR-020): Kunden mit Kontaktpersonen, Dublettenprüfung und Zusammenführen; Anfragen mit Wiedervorlage."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field

from ichq.api.security import TenantDB, require, tenant_db
from ichq.api.v1.common import DEFAULT, Cursor, Limit, Strict, object_out, object_ref, refs_for, writing
from ichq.authz.service import Principal
from ichq.core.errors import ValidationFailed
from ichq.crm import customers, inquiries
from ichq.crm.models import CUSTOMER_STATUS, INQUIRY_STATUS, Customer, CustomerContact, Inquiry
from ichq.db.session import TenantSession
from ichq.objects import service as objects
from ichq.objects.models import ObjectRow
from ichq.objects.visibility import can_see, visible_clause
from ichq.tenancy.service import company_today

router = APIRouter(prefix="/api/v1", tags=["crm"])
Kind = Annotated[str, Field(pattern="^(company|person)$")]
CStatus = Annotated[str, Field(pattern="^(lead|active|inactive)$")]
IStatus = Annotated[str, Field(pattern="^(" + "|".join(INQUIRY_STATUS) + ")$")]
Source = Annotated[str, Field(pattern="^(email|phone|website|referral|event|other)$")]
Priority = Annotated[str, Field(pattern="^(low|normal|high|urgent)$")]
Ref = Annotated[str | None, Field(default=None, max_length=64)]
# Einfache Formprüfung (keine Zustellbarkeitsprüfung) — gleiche Regel wie bei Einladungen
Email = Annotated[str, Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]


class CustomerFields(Strict):
    kind: Kind | None = None
    status: CStatus | None = None
    legal_name: str | None = Field(default=None, max_length=300)
    email: Email | None = None
    phone: str | None = Field(default=None, max_length=50)
    website: str | None = Field(default=None, max_length=300)
    street: str | None = Field(default=None, max_length=200)
    postal_code: str | None = Field(default=None, max_length=20)
    city: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, pattern="^[A-Z]{2}$")
    vat_id: str | None = Field(default=None, max_length=30)
    notes: str | None = Field(default=None, max_length=20_000)
    owner: Ref = None


class CustomerIn(CustomerFields):
    name: str = Field(min_length=1, max_length=300)
    allow_duplicate: bool = False


class CustomerPatch(CustomerFields):
    name: str | None = Field(default=None, min_length=1, max_length=300)


class ContactIn(Strict):
    name: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=100)
    email: Email | None = None
    phone: str | None = Field(default=None, max_length=50)
    is_primary: bool = False


class ContactPatch(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=100)
    email: Email | None = None
    phone: str | None = Field(default=None, max_length=50)
    is_primary: bool | None = None


class MergeIn(Strict):
    into: str = Field(min_length=1, max_length=64, description="öffentliche ID des Kunden, der bleibt")


class InquiryFields(Strict):
    description: str | None = Field(default=None, max_length=20_000)
    source: Source | None = None
    received_on: date | None = None
    priority: Priority | None = None
    owner: Ref = None
    customer: Ref = None
    next_action: str | None = Field(default=None, max_length=300)
    follow_up_on: date | None = None


class InquiryIn(InquiryFields):
    title: str = Field(min_length=1, max_length=300)


class InquiryPatch(InquiryFields):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: IStatus | None = None


def contact_out(k: CustomerContact) -> dict[str, Any]:
    return {"id": k.public_id, "name": k.name, "role": k.role, "email": k.email, "phone": k.phone,
            "is_primary": k.is_primary}


def customer_out(s: TenantSession, c: Customer, o: ObjectRow, *, detail: bool = False) -> dict[str, Any]:
    refs = refs_for(s, {c.owner_membership_id})
    aus = {**object_out(s, o), "name": o.title, "kind": c.kind, "status": c.status, "legal_name": c.legal_name,
           "email": c.email, "phone": c.phone, "website": c.website, "street": c.street, "postal_code": c.postal_code,
           "city": c.city, "country": c.country, "vat_id": c.vat_id,
           "owner": refs.get(c.owner_membership_id) if c.owner_membership_id else None}
    if detail:
        aus |= {"notes": c.notes, "contacts": [contact_out(k) for k in customers.contacts(s, c.id)],
                "merged_into": object_ref(objects.by_id(s, c.merged_into_id)) if c.merged_into_id else None}
    return aus


def _owner(s: TenantSession, p: Principal, wert: str | None) -> uuid.UUID | None:
    if wert == "me":
        return p.membership_id
    return objects.member(s, wert, active_only=False).id if wert else None


@router.get("/customers")
def list_customers(p: Principal = Depends(require("customers.read")), db: TenantDB = Depends(tenant_db),
                   q: Annotated[str | None, Query(max_length=100)] = None,
                   status: Annotated[list[str] | None, Query(max_length=3)] = None,
                   owner: Annotated[str | None, Query(max_length=64, description="ID oder 'me'")] = None,
                   archived: bool = False,
                   sort: Annotated[str, Query(pattern="^(name|created_at)$")] = "name",
                   order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
                   cursor: Cursor = None, limit: Limit = DEFAULT) -> dict[str, Any]:
    if status and not set(status) <= set(CUSTOMER_STATUS):
        raise ValidationFailed(f"status muss aus {list(CUSTOMER_STATUS)} sein")
    with db() as s:
        f = customers.CustomerFilter(q=q, status=tuple(status or ()), owner_membership_id=_owner(s, p, owner),
                                     archived=archived)
        rows, weiter = customers.list_customers(s, visible_clause(p), f, sort=sort, desc=order == "desc",
                                                cursor=cursor, limit=limit)
        return {"items": [customer_out(s, c, o) for c, o, *_ in rows], "next_cursor": weiter}


@router.get("/customers/duplicates")
def find_duplicates(name: Annotated[str, Query(min_length=1, max_length=300)],
                    email: Annotated[str | None, Query(max_length=320)] = None,
                    p: Principal = Depends(require("customers.read")),
                    db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Mögliche Doppeleinträge vor dem Anlegen (normalisierter Name ohne Rechtsform, gleiche E-Mail)."""
    with db() as s:
        return {"items": [customer_out(s, c, o) for c, o in
                          customers.duplicates(s, visible_clause(p), name=name, email=email)]}


@router.post("/customers", status_code=201)
def create_customer(body: CustomerIn, p: Principal = Depends(require("customers.create")),
                    db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    werte = body.model_dump(exclude={"name", "owner", "allow_duplicate"}, exclude_none=True)
    with writing(db) as s:
        c, o = customers.create(s, p, visible_clause(p), name=body.name, werte=werte, owner=body.owner,
                                allow_duplicate=body.allow_duplicate)
        return customer_out(s, c, o, detail=True)


@router.get("/customers/{ref}")
def get_customer(ref: str, p: Principal = Depends(require("customers.read")),
                 db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        c, o = customers.get(s, p, ref)
        return customer_out(s, c, o, detail=True)


@router.patch("/customers/{ref}")
def update_customer(ref: str, body: CustomerPatch, p: Principal = Depends(require("customers.update")),
                    db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailed("Keine Änderung angegeben")
    for pflicht in ("name", "kind", "status"):
        if pflicht in changes and changes[pflicht] is None:
            raise ValidationFailed(f"{pflicht} darf nicht leer sein")
    with writing(db) as s:
        c, o = customers.update_customer(s, p, ref, changes)
        return customer_out(s, c, o, detail=True)


@router.post("/customers/{ref}/contacts", status_code=201)
def add_contact(ref: str, body: ContactIn, p: Principal = Depends(require("customers.update")),
                db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        return contact_out(customers.save_contact(s, p, ref, body.model_dump()))


@router.patch("/customers/{ref}/contacts/{contact}")
def update_contact(ref: str, contact: str, body: ContactPatch, p: Principal = Depends(require("customers.update")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if not changes or changes.get("name", "x") is None:
        raise ValidationFailed("Keine gültige Änderung angegeben")
    with writing(db) as s:
        return contact_out(customers.save_contact(s, p, ref, changes, contact))


@router.delete("/customers/{ref}/contacts/{contact}", status_code=204)
def delete_contact(ref: str, contact: str, p: Principal = Depends(require("customers.update")),
                   db: TenantDB = Depends(tenant_db)) -> Response:
    with writing(db) as s:
        customers.delete_contact(s, p, ref, contact)
    return Response(status_code=204)


@router.post("/customers/{ref}/merge")
def merge_customer(ref: str, body: MergeIn, p: Principal = Depends(require("customers.delete")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Dublette ``ref`` in ``into`` zusammenführen: Verweise wandern, die Dublette wird archiviert."""
    with writing(db) as s:
        c, o = customers.merge(s, p, ref, body.into)
        return customer_out(s, c, o, detail=True)


# ---- Anfragen ----------------------------------------------------------------------------------------------------
def inquiry_out(s: TenantSession, p: Principal, i: Inquiry, o: ObjectRow) -> dict[str, Any]:
    refs = refs_for(s, {i.owner_membership_id})
    kunde = None
    if i.customer_id is not None and can_see(s, p, i.customer_id):   # Kunde nur nennen, wenn sichtbar
        kunde = object_ref(objects.by_id(s, i.customer_id))
    return {**object_out(s, o), "description": i.description, "source": i.source, "received_on": i.received_on,
            "priority": i.priority, "status": i.status, "next_action": i.next_action,
            "follow_up_on": i.follow_up_on, "closed_at": i.closed_at, "customer": kunde,
            "owner": refs.get(i.owner_membership_id) if i.owner_membership_id else None}


@router.get("/inquiries")
def list_inquiries(p: Principal = Depends(require("customers.read")), db: TenantDB = Depends(tenant_db),
                   status: Annotated[list[str] | None, Query(max_length=6)] = None,
                   owner: Annotated[str | None, Query(max_length=64, description="ID oder 'me'")] = None,
                   customer: Annotated[str | None, Query(max_length=64)] = None,
                   follow_up_before: date | None = None, archived: bool = False,
                   sort: Annotated[str, Query(pattern="^(received_on|follow_up_on|priority|title)$")] = "received_on",
                   order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
                   cursor: Cursor = None, limit: Limit = DEFAULT) -> dict[str, Any]:
    if status and not set(status) <= set(INQUIRY_STATUS):
        raise ValidationFailed(f"status muss aus {list(INQUIRY_STATUS)} sein")
    with db() as s:
        kunde = objects.resolve(s, p, customer, type_="customer").id if customer else None
        f = inquiries.InquiryFilter(status=tuple(status or ()), owner_membership_id=_owner(s, p, owner),
                                    customer_id=kunde, follow_up_before=follow_up_before, archived=archived)
        rows, weiter = inquiries.list_inquiries(s, visible_clause(p), f, sort=sort, desc=order == "desc",
                                                cursor=cursor, limit=limit)
        return {"items": [inquiry_out(s, p, i, o) for i, o, *_ in rows], "next_cursor": weiter}


@router.post("/inquiries", status_code=201)
def create_inquiry(body: InquiryIn, p: Principal = Depends(require("customers.create")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        i, o = inquiries.create(s, p, title=body.title, werte=body.model_dump(exclude={"title"}, exclude_none=True),
                                today=company_today(s))
        return inquiry_out(s, p, i, o)


@router.get("/inquiries/{ref}")
def get_inquiry(ref: str, p: Principal = Depends(require("customers.read")),
                db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        i, o = inquiries.get(s, p, ref)
        return inquiry_out(s, p, i, o)


@router.patch("/inquiries/{ref}")
def update_inquiry(ref: str, body: InquiryPatch, p: Principal = Depends(require("customers.update")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailed("Keine Änderung angegeben")
    for pflicht in ("title", "status", "source", "priority", "received_on"):
        if pflicht in changes and changes[pflicht] is None:
            raise ValidationFailed(f"{pflicht} darf nicht leer sein")
    with writing(db) as s:
        i, o = inquiries.update(s, p, ref, changes)
        return inquiry_out(s, p, i, o)
