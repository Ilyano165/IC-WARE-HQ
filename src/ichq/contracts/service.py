"""Verträge: anlegen, ändern, kündigen (erfassen, nicht versenden), Laufzeit-/Kündigungstermine, Liste.

Termine sind reine Kalenderrechnung aus den eingegebenen Werten (``ichq.core.kalender``) — keine Rechtsprüfung.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ichq.activity.service import record as activity
from ichq.audit.service import record as audit
from ichq.authz.service import Principal
from ichq.contracts.models import BILLING, CONTRACT_STATUS, MAX_NOTES, UNITS, Contract
from ichq.core.errors import Conflict, NotFound, ValidationFailed
from ichq.core.kalender import plus_monate, verschiebe
from ichq.db.paging import SortKey, keyset
from ichq.objects.models import ObjectRow
from ichq.objects.service import clean_title, create_object, member, resolve

SORTS: dict[str, SortKey] = {
    "end_date": SortKey("end_date", func.coalesce(Contract.end_date, func.to_date("9999-12-31", "YYYY-MM-DD")),
                        "date"),
    "created_at": SortKey("created_at", ObjectRow.created_at, "ts"),
    "title": SortKey("title", ObjectRow.title, "text"),
}
MAX_RUNDEN = 1200                       # Schutz gegen Endlosschleifen bei sehr alten Verträgen (100 Jahre monatlich)
FREI = ("counterparty_name", "contract_type", "reference")


@dataclass(frozen=True)
class Termine:
    state: str                          # draft | active | terminated | ended
    term_end: date | None               # Ende der laufenden Laufzeit (nach automatischen Verlängerungen)
    notice_deadline: date | None        # letzter Tag, an dem die Kündigung zugehen muss (aus den Angaben)
    renewals: int                       # wie oft seit end_date automatisch verlängert


def termine(c: Contract, heute: date) -> Termine:
    if c.status == "draft":
        return Termine("draft", c.end_date, None, 0)
    if c.status == "terminated":
        ende = c.termination_effective_on
        return Termine("ended" if ende and ende < heute else "terminated", ende, None, 0)
    frist = (c.notice_value, c.notice_unit) if c.notice_value is not None and c.notice_unit else None
    if c.end_date is None:                                    # unbefristet: frühestes Ende ab heute
        return Termine("active", verschiebe(heute, frist[0], frist[1]) if frist else None, None, 0)
    ende, runden = c.end_date, 0
    if c.auto_renew and c.renewal_months:
        while runden < MAX_RUNDEN and (verschiebe(ende, -frist[0], frist[1]) if frist else ende) < heute:
            ende, runden = plus_monate(c.end_date, c.renewal_months * (runden + 1)), runden + 1
    kuendigung = verschiebe(ende, -frist[0], frist[1]) if frist else None
    if ende < heute:
        return Termine("ended", ende, None, runden)
    return Termine("active", ende, kuendigung, runden)


def _pruefe(w: dict[str, Any]) -> None:
    for f, erlaubt in (("notice_unit", UNITS), ("billing", BILLING), ("status", CONTRACT_STATUS)):
        if w.get(f) is not None and w[f] not in erlaubt:
            raise ValidationFailed(f"{f} ist ungültig")
    if w.get("status") == "terminated":
        raise ValidationFailed("Kündigen nur über POST /contracts/{ref}/terminate")
    if len(w.get("notes") or "") > MAX_NOTES:
        raise ValidationFailed(f"notes: höchstens {MAX_NOTES} Zeichen")


def _setze(session: Session, principal: Principal, c: Contract, w: dict[str, Any]) -> None:
    for f in FREI:
        if f in w:
            setattr(c, f, " ".join((w[f] or "").split()) or None)
    for f in ("start_date", "end_date", "renewal_months", "amount_minor"):
        if f in w:
            setattr(c, f, w[f])
    for f in ("auto_renew", "billing", "status", "currency"):
        if w.get(f) is not None:
            setattr(c, f, w[f])
    if "notice_value" in w or "notice_unit" in w:
        c.notice_value, c.notice_unit = w.get("notice_value"), w.get("notice_unit")
        if (c.notice_value is None) != (c.notice_unit is None):
            raise ValidationFailed("Kündigungsfrist: Wert und Einheit gemeinsam angeben")
    if "notes" in w:
        c.notes = (w["notes"] or "").strip()
    if "customer" in w:
        c.customer_id = resolve(session, principal, w["customer"], type_="customer").id if w["customer"] else None
    if "responsible" in w:
        c.responsible_membership_id = member(session, w["responsible"]).id if w["responsible"] else None
    if c.auto_renew and not c.renewal_months:
        raise ValidationFailed("Automatische Verlängerung braucht renewal_months")
    if c.start_date and c.end_date and c.end_date < c.start_date:
        raise ValidationFailed("end_date liegt vor start_date")


def create(session: Session, principal: Principal, *, title: str, werte: dict[str, Any], currency: str) -> tuple[
        Contract, ObjectRow]:
    _pruefe(werte)
    o = create_object(session, type_="contract", title=title, actor_membership_id=principal.membership_id,
                      search_text=" ".join(filter(None, (werte.get("counterparty_name"), werte.get("reference"),
                                                         werte.get("contract_type")))) or None)
    c = Contract(id=o.id, tenant_id=o.tenant_id, currency=currency, auto_renew=False, billing="none", status="active")
    _setze(session, principal, c, werte)
    session.add(c)
    session.flush()
    activity(session, o.id, "contract.created", actor_membership_id=principal.membership_id)
    audit(session, "contract.created", actor_membership_id=principal.membership_id, target_type="contract",
          target_id=o.public_id)
    return c, o


def get(session: Session, principal: Principal, ref: str) -> tuple[Contract, ObjectRow]:
    o = resolve(session, principal, ref, type_="contract")
    c = session.get(Contract, o.id)
    if c is None:
        raise NotFound()
    return c, o


def update(session: Session, principal: Principal, ref: str, changes: dict[str, Any]) -> tuple[Contract, ObjectRow]:
    c, o = get(session, principal, ref)
    if c.status == "terminated":
        raise Conflict("Gekündigter Vertrag — Änderungen nur an laufenden Verträgen")
    _pruefe(changes)
    if "title" in changes:
        o.title = clean_title(changes["title"])
    _setze(session, principal, c, changes)
    session.flush()
    activity(session, o.id, "contract.updated", actor_membership_id=principal.membership_id,
             data={"fields": sorted(changes)})
    audit(session, "contract.updated", actor_membership_id=principal.membership_id, target_type="contract",
          target_id=o.public_id, data={"fields": sorted(changes)})
    return c, o


def terminate(session: Session, principal: Principal, ref: str, *, terminated_on: date, effective_on: date,
              note: str, today: date) -> tuple[Contract, ObjectRow]:
    """Kündigung ERFASSEN (wann zugegangen, wann wirksam). HQ verschickt nichts und prüft keine Wirksamkeit."""
    c, o = get(session, principal, ref)
    if c.status == "terminated":
        raise Conflict("Vertrag ist bereits gekündigt")
    if terminated_on > today:
        raise ValidationFailed("terminated_on darf nicht in der Zukunft liegen")
    if effective_on < terminated_on:
        raise ValidationFailed("effective_on liegt vor terminated_on")
    t = termine(c, terminated_on)
    c.status, c.terminated_on, c.termination_effective_on = "terminated", terminated_on, effective_on
    c.termination_note = " ".join(note.split())[:500] or None
    session.flush()
    data = {"late": bool(t.notice_deadline and terminated_on > t.notice_deadline)}
    activity(session, o.id, "contract.terminated", actor_membership_id=principal.membership_id, data=data)
    audit(session, "contract.terminated", actor_membership_id=principal.membership_id, target_type="contract",
          target_id=o.public_id, data=data)
    return c, o


@dataclass(frozen=True)
class ContractFilter:
    status: tuple[str, ...] = ()
    customer_id: uuid.UUID | None = None
    responsible_membership_id: uuid.UUID | None = None
    ending_before: date | None = None
    archived: bool = False
    q: str | None = None


def filter_clauses(f: ContractFilter) -> list[Any]:
    teile: list[Any] = [ObjectRow.archived_at.is_not(None) if f.archived else ObjectRow.archived_at.is_(None)]
    if f.status:
        teile.append(Contract.status.in_(f.status))
    if f.customer_id is not None:
        teile.append(Contract.customer_id == f.customer_id)
    if f.responsible_membership_id is not None:
        teile.append(Contract.responsible_membership_id == f.responsible_membership_id)
    if f.ending_before is not None:
        teile.append(func.coalesce(Contract.termination_effective_on, Contract.end_date) <= f.ending_before)
    if f.q:
        muster = f"%{f.q.lower()}%"
        teile.append(or_(func.lower(ObjectRow.title).like(muster), func.lower(Contract.counterparty_name).like(muster),
                         func.lower(Contract.reference).like(muster), func.lower(Contract.contract_type).like(muster)))
    return teile


def list_contracts(session: Session, visible: Any, f: ContractFilter, *, sort: str, desc: bool, cursor: str | None,
                   limit: int | None) -> tuple[list[Any], str | None]:
    key = SORTS.get(sort)
    if key is None:
        raise ValidationFailed(f"sort muss eine von {sorted(SORTS)} sein")
    stmt = select(Contract, ObjectRow).join(ObjectRow, ObjectRow.id == Contract.id).where(visible, *filter_clauses(f))
    seite = keyset(session, stmt, key, ObjectRow.id, desc=desc, cursor=cursor, limit=limit)
    return list(seite.rows), seite.next_cursor


def notice_due(session: Session, visible: Any, *, today: date, days: int, cap: int = 1000) -> tuple[
        list[tuple[Contract, ObjectRow, Termine]], bool]:
    """Laufende Verträge, deren Kündigungstermin in ``days`` Tagen oder früher liegt (nicht überschritten).
    Gerechnet in Python (Verlängerungen); höchstens ``cap`` Verträge — ``truncated`` sagt, ob mehr existieren."""
    rows = session.execute(select(Contract, ObjectRow).join(ObjectRow, ObjectRow.id == Contract.id).where(
        visible, ObjectRow.archived_at.is_(None), Contract.status == "active", Contract.notice_value.is_not(None),
        Contract.end_date.is_not(None)).limit(cap + 1)).all()
    treffer = []
    for c, o in rows[:cap]:
        t = termine(c, today)
        if t.notice_deadline is not None and 0 <= (t.notice_deadline - today).days <= days:
            treffer.append((c, o, t))
    treffer.sort(key=lambda x: x[2].notice_deadline or today)
    return treffer, len(rows) > cap
