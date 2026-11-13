"""Kunden und Kontaktpersonen.

* Ein Kunde ist ein Objekt vom Typ ``customer`` (Name = ``objects.title``) plus Zeile in ``customers``.
* Doppelte Profile: ``dedup_key`` (normalisierter Name ohne Rechtsform) und E-Mail. Anlegen mit einem möglichen
  Doppel braucht ``allow_duplicate`` — sonst 409 mit Hinweis.
* Zusammenführen verschiebt alle Verweise (jede Tabelle mit ``customer_id`` → ``customers``) auf den Zielkunden und
  archiviert die Dublette. Was die Datenbank schützt (z. B. ausgestellte Rechnungen), lässt das Zusammenführen
  scheitern — nichts wird still umgeschrieben.
"""
from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from ichq.activity.service import record as activity
from ichq.audit.service import record as audit
from ichq.authz.service import Principal, decide
from ichq.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from ichq.crm.models import CUSTOMER_KIND, CUSTOMER_STATUS, MAX_NOTES, Customer, CustomerContact
from ichq.db.base import Base
from ichq.db.paging import SortKey, keyset
from ichq.objects.models import ObjectRow
from ichq.objects.service import clean_title, create_object, member, resolve

SORTS: dict[str, SortKey] = {
    "name": SortKey("name", ObjectRow.title, "text"),
    "created_at": SortKey("created_at", ObjectRow.created_at, "ts"),
}
_RECHTSFORM = re.compile(r"\b(gmbh|mbh|ug|ag|kg|ohg|gbr|ek|e\s*k|e\s*v|ev|co|ltd|inc|llc|se|partg|"
                         r"haftungsbeschraenkt)\b")
FELDER = ("kind", "status", "legal_name", "email", "phone", "website", "street", "postal_code", "city", "country",
          "vat_id", "notes")


def dedup_key(name: str) -> str:
    """„Müller GmbH & Co. KG“ und „mueller“ → gleicher Schlüssel. Nur zum Finden, nie zum Entscheiden."""
    s = name.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _RECHTSFORM.sub(" ", s)
    return " ".join(s.split())[:300] or name.lower()[:300]


def _text(werte: dict[str, Any], feld: str) -> str | None:
    v = werte.get(feld)
    return (" ".join(str(v).split()) or None) if v is not None else None


def _pruefe(werte: dict[str, Any]) -> None:
    if "kind" in werte and werte["kind"] not in CUSTOMER_KIND:
        raise ValidationFailed("kind ist ungültig")
    if "status" in werte and werte["status"] not in CUSTOMER_STATUS:
        raise ValidationFailed("status ist ungültig")
    if len(werte.get("notes") or "") > MAX_NOTES:
        raise ValidationFailed(f"notes: höchstens {MAX_NOTES} Zeichen")
    land = werte.get("country")
    if land and not re.fullmatch(r"[A-Z]{2}", land):
        raise ValidationFailed("country: zweistelliger Ländercode, z. B. DE")


def _suchtext(c: Customer) -> str:
    return " ".join(x for x in (c.legal_name, c.email, c.phone, c.city, c.vat_id) if x)[:1000]


def duplicates(session: Session, visible: Any, *, name: str, email: str | None,
               ohne: uuid.UUID | None = None) -> list[tuple[Customer, ObjectRow]]:
    bedingung = [Customer.dedup_key == dedup_key(name)]
    if email:
        bedingung.append(func.lower(Customer.email) == email.strip().lower())
    stmt = (select(Customer, ObjectRow).join(ObjectRow, ObjectRow.id == Customer.id)
            .where(visible, ObjectRow.archived_at.is_(None), or_(*bedingung)).limit(5))
    if ohne is not None:
        stmt = stmt.where(Customer.id != ohne)
    return [(c, o) for c, o in session.execute(stmt).all()]


def create(session: Session, principal: Principal, visible: Any, *, name: str, werte: dict[str, Any],
           owner: str | None, allow_duplicate: bool) -> tuple[Customer, ObjectRow]:
    _pruefe(werte)
    titel = clean_title(name)
    doppelt = duplicates(session, visible, name=titel, email=_text(werte, "email"))
    if doppelt and not allow_duplicate:
        raise Conflict("Möglicher Doppeleintrag: " + ", ".join(o.title for _, o in doppelt)
                       + " — prüfen oder bewusst trotzdem anlegen")
    o = create_object(session, type_="customer", title=titel, actor_membership_id=principal.membership_id)
    c = Customer(id=o.id, tenant_id=o.tenant_id, dedup_key=dedup_key(titel),
                 owner_membership_id=member(session, owner).id if owner else None,
                 **{f: (werte.get(f) if f in ("kind", "status", "notes") else _text(werte, f))
                    for f in FELDER if werte.get(f) is not None})
    session.add(c)
    session.flush()
    o.search_text = _suchtext(c) or None
    activity(session, o.id, "customer.created", actor_membership_id=principal.membership_id)
    audit(session, "customer.created", actor_membership_id=principal.membership_id, target_type="customer",
          target_id=o.public_id, data={"duplicate_confirmed": bool(doppelt)})
    return c, o


def get(session: Session, principal: Principal, ref: str) -> tuple[Customer, ObjectRow]:
    o = resolve(session, principal, ref, type_="customer")
    c = session.get(Customer, o.id)
    if c is None:
        raise NotFound()
    return c, o


def update_customer(session: Session, principal: Principal, ref: str,
                    changes: dict[str, Any]) -> tuple[Customer, ObjectRow]:
    c, o = get(session, principal, ref)
    _pruefe(changes)
    if "name" in changes:
        o.title = clean_title(changes["name"])
        c.dedup_key = dedup_key(o.title)
    for f in FELDER:
        if f in changes:
            setattr(c, f, changes[f] if f in ("kind", "status") else (_text(changes, f) if f != "notes"
                                                                       else (changes[f] or "")))
    if "owner" in changes:
        c.owner_membership_id = member(session, changes["owner"]).id if changes["owner"] else None
    o.search_text = _suchtext(c) or None
    session.flush()
    activity(session, o.id, "customer.updated", actor_membership_id=principal.membership_id,
             data={"fields": sorted(changes)})
    audit(session, "customer.updated", actor_membership_id=principal.membership_id, target_type="customer",
          target_id=o.public_id, data={"fields": sorted(changes)})
    return c, o


@dataclass(frozen=True)
class CustomerFilter:
    q: str | None = None
    status: tuple[str, ...] = ()
    owner_membership_id: uuid.UUID | None = None
    archived: bool = False


def filter_clauses(f: CustomerFilter) -> list[Any]:
    teile: list[Any] = [ObjectRow.archived_at.is_not(None) if f.archived else ObjectRow.archived_at.is_(None)]
    if f.status:
        teile.append(Customer.status.in_(f.status))
    if f.owner_membership_id is not None:
        teile.append(Customer.owner_membership_id == f.owner_membership_id)
    if f.q:
        muster = f"%{f.q.lower()}%"
        teile.append(or_(func.lower(ObjectRow.title).like(muster), func.lower(Customer.email).like(muster),
                         func.lower(Customer.city).like(muster)))
    return teile


def list_customers(session: Session, visible: Any, f: CustomerFilter, *, sort: str, desc: bool,
                   cursor: str | None, limit: int | None) -> tuple[list[Any], str | None]:
    key = SORTS.get(sort)
    if key is None:
        raise ValidationFailed(f"sort muss eine von {sorted(SORTS)} sein")
    stmt = select(Customer, ObjectRow).join(ObjectRow, ObjectRow.id == Customer.id).where(visible, *filter_clauses(f))
    seite = keyset(session, stmt, key, ObjectRow.id, desc=desc, cursor=cursor, limit=limit)
    return list(seite.rows), seite.next_cursor


# ---- Kontaktpersonen ---------------------------------------------------------------------------------------------
def contacts(session: Session, customer_id: uuid.UUID) -> list[CustomerContact]:
    return list(session.scalars(select(CustomerContact).where(CustomerContact.customer_id == customer_id)
                                .order_by(CustomerContact.is_primary.desc(), CustomerContact.name)))


def _kontakt(session: Session, customer_id: uuid.UUID, ref: str) -> CustomerContact:
    k = session.scalars(select(CustomerContact).where(CustomerContact.public_id == ref,
                                                      CustomerContact.customer_id == customer_id)).one_or_none()
    if k is None:
        raise NotFound()
    return k


def _nur_ein_hauptkontakt(session: Session, k: CustomerContact) -> None:
    if k.is_primary:
        session.execute(update(CustomerContact).where(CustomerContact.customer_id == k.customer_id,
                                                      CustomerContact.id != k.id).values(is_primary=False))


def save_contact(session: Session, principal: Principal, ref: str, werte: dict[str, Any],
                 contact_ref: str | None = None) -> CustomerContact:
    c, o = get(session, principal, ref)
    if contact_ref is None:
        k = CustomerContact(id=uuid.uuid4(), tenant_id=c.tenant_id, public_id=secrets.token_hex(16),
                            customer_id=c.id, name=" ".join(str(werte["name"]).split()))
        session.add(k)
    else:
        k = _kontakt(session, c.id, contact_ref)
        if "name" in werte:
            k.name = " ".join(str(werte["name"]).split())
    if not k.name:
        raise ValidationFailed("name darf nicht leer sein")
    for f in ("role", "email", "phone"):
        if f in werte:
            setattr(k, f, _text(werte, f))
    if "is_primary" in werte:
        k.is_primary = bool(werte["is_primary"])
    session.flush()
    _nur_ein_hauptkontakt(session, k)
    activity(session, o.id, "customer.contact_changed", actor_membership_id=principal.membership_id)
    return k


def delete_contact(session: Session, principal: Principal, ref: str, contact_ref: str) -> None:
    c, o = get(session, principal, ref)
    session.delete(_kontakt(session, c.id, contact_ref))
    session.flush()
    activity(session, o.id, "customer.contact_changed", actor_membership_id=principal.membership_id)


# ---- Zusammenführen -----------------------------------------------------------------------------------------------
def _verweise() -> list[str]:
    """Alle Tabellen, die per ``customer_id`` auf ``customers`` zeigen — auch künftige Fachmodule."""
    return sorted(t.name for t in Base.metadata.tables.values()
                  if "customer_id" in t.c and any(fk.column.table.name == "customers"
                                                   for fk in t.c.customer_id.foreign_keys))


def merge(session: Session, principal: Principal, ref: str, into_ref: str) -> tuple[Customer, ObjectRow]:
    if not decide(principal, "customers.delete"):
        raise PermissionDenied("Fehlendes Recht: customers.delete")
    alt, alt_o = get(session, principal, ref)             # erst auflösen: fremde IDs ⇒ 404, nie 422
    ziel, ziel_o = get(session, principal, into_ref)
    if alt.id == ziel.id:
        raise ValidationFailed("Ein Kunde kann nicht mit sich selbst zusammengeführt werden")
    if alt_o.archived_at is not None or ziel_o.archived_at is not None:
        raise Conflict("Archivierte Kunden können nicht zusammengeführt werden")
    verschoben: dict[str, int] = {}
    try:
        with session.begin_nested():
            for tabelle in _verweise():
                # Tabellenname aus den eigenen Modellen (nie aus Eingaben)
                n = session.execute(text(f"UPDATE {tabelle} SET customer_id = :z WHERE customer_id = :a"),  # noqa: S608
                                    {"z": ziel.id, "a": alt.id}).rowcount   # type: ignore[attr-defined]
                if n:
                    verschoben[tabelle] = n
    except DBAPIError as e:
        raise Conflict("Zusammenführen nicht möglich: Ein Datensatz der Dublette ist geschützt "
                       "(z. B. ausgestellte Rechnung oder abgeschlossener Monat).") from e
    alt.merged_into_id = ziel.id
    alt_o.archived_at = session.scalar(select(func.now()))
    session.flush()
    for oid in (alt_o.id, ziel_o.id):
        activity(session, oid, "customer.merged", actor_membership_id=principal.membership_id,
                 data={"from": alt_o.public_id, "into": ziel_o.public_id})
    audit(session, "customer.merged", actor_membership_id=principal.membership_id, target_type="customer",
          target_id=ziel_o.public_id, data={"from": alt_o.public_id, "moved": verschoben})
    return ziel, ziel_o
