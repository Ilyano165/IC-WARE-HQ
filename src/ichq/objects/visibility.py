"""Sichtbarkeit von Fachobjekten — die EINE Stelle, an der entschieden wird, wer ein Objekt sieht (ADR-009).

Ein Objekt ist für einen Principal sichtbar, wenn

1. er das Modulrecht zum Lesen des Objekttyps hat (``OBJECT_TYPES[typ].read``) — sonst nie, und
2. für ihn KEIN Ressourcen-DENY auf dem Objekt liegt (``object_denies``, M4) — schlägt alles Folgende, und
3. er ``objects.read_all`` hat (normaler Sichtbereich: alle Objekte des Moduls) ODER
   das Objekt selbst angelegt hat ODER es ihm ausdrücklich freigegeben wurde (``object_grants``).

Ohne ``objects.read_all`` (z. B. Rolle „Steuerberater") sieht man also nur, was man angelegt hat oder was
freigegeben wurde. Mandantengrenzen setzt zusätzlich und unabhängig davon die Row-Level Security.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ColumnElement, and_, exists, false, or_, select, text
from sqlalchemy.orm import Session

from ichq.authz.service import Principal, decide, principal_for
from ichq.objects.models import ObjectDeny, ObjectGrant, ObjectRow
from ichq.objects.registry import OBJECT_TYPES, readable_types

READ_ALL = "objects.read_all"


def types_for(principal: Principal) -> frozenset[str]:
    return readable_types(frozenset(p for p in principal.permissions if decide(principal, p)))


def visible_clause(principal: Principal, obj: Any = ObjectRow) -> ColumnElement[bool]:
    """SQL-Bedingung über eine ``objects``-Tabelle (oder deren Alias)."""
    typen = types_for(principal)
    if not typen:
        return false()
    verboten = exists().where(ObjectDeny.object_id == obj.id, ObjectDeny.tenant_id == obj.tenant_id,
                              ObjectDeny.membership_id == principal.membership_id)
    typ_ok: ColumnElement[bool] = and_(obj.type.in_(sorted(typen)), ~verboten)
    if decide(principal, READ_ALL):
        return typ_ok
    freigabe = exists().where(ObjectGrant.object_id == obj.id, ObjectGrant.tenant_id == obj.tenant_id,
                              ObjectGrant.membership_id == principal.membership_id)
    return and_(typ_ok, or_(obj.created_by_membership_id == principal.membership_id, freigabe))


def can_see(session: Session, principal: Principal, object_id: uuid.UUID) -> bool:
    return bool(session.scalar(select(ObjectRow.id).where(ObjectRow.id == object_id,
                                                          visible_clause(principal))))


def can_update(principal: Principal, obj: ObjectRow) -> bool:
    typ = OBJECT_TYPES.get(obj.type)
    return typ is not None and decide(principal, typ.update)


def principal_for_membership(session: Session, membership_id: uuid.UUID) -> Principal | None:
    """Principal einer anderen Mitgliedschaft — für Rechteprüfungen beim Zustellen (Benachrichtigungen).

    ``None``, wenn die Mitgliedschaft nicht aktiv ist oder die Firma nicht nutzbar ist.
    """
    zeile = session.execute(text("""
        SELECT m.user_id, m.tenant_id FROM memberships m JOIN tenants t ON t.id = m.tenant_id
        WHERE m.id = :m AND m.status = 'active' AND t.status IN ('active', 'paused')"""),
        {"m": membership_id}).one_or_none()
    if zeile is None:
        return None
    return principal_for(session, user_id=zeile.user_id, tenant_id=zeile.tenant_id, membership_id=membership_id)
