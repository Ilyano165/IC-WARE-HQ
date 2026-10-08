"""Ressourcen-DENY (M4, ADR-011): ein Objekt für eine bestimmte Mitgliedschaft sperren.

Ein DENY schlägt ``objects.read_all``, jede Freigabe und die Erstellerschaft (``ichq.objects.visibility``).
Setzen/Aufheben: Route ``objects.share`` UND das Objekt selbst sehen UND die Person verwalten dürfen
(nicht sich selbst, Rang höchstens der eigene — ``ichq.authz.delegation.manageable``). Nur Audit, keine
Aktivität (der Sperrvermerk ist keine Information für den Verlauf des Objekts).
"""
from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ichq.audit.service import record as audit
from ichq.authz.delegation import manageable
from ichq.authz.service import Principal
from ichq.db.session import current_tenant_id
from ichq.objects.models import ObjectDeny, ObjectRow


def _anzahl(res: object) -> int:
    return int(getattr(res, "rowcount", 0) or 0)


def denies_of(session: Session, obj: ObjectRow) -> list[uuid.UUID]:
    return list(session.scalars(select(ObjectDeny.membership_id).where(ObjectDeny.object_id == obj.id)
                                .order_by(ObjectDeny.created_at)))


def deny(session: Session, p: Principal, obj: ObjectRow, member_ref: str) -> bool:
    _, t = manageable(session, p, member_ref)
    neu = _anzahl(session.execute(pg_insert(ObjectDeny).values(
        tenant_id=current_tenant_id(session), object_id=obj.id, membership_id=t.id,
        created_by_membership_id=p.membership_id).on_conflict_do_nothing()))
    if neu:
        audit(session, "object.denied", actor_membership_id=p.membership_id, target_type=obj.type,
              target_id=obj.public_id, data={"member": t.public_id})
    return bool(neu)


def undeny(session: Session, p: Principal, obj: ObjectRow, member_ref: str) -> bool:
    _, t = manageable(session, p, member_ref)
    weg = _anzahl(session.execute(delete(ObjectDeny).where(ObjectDeny.object_id == obj.id,
                                                           ObjectDeny.membership_id == t.id)))
    if weg:
        audit(session, "object.deny_lifted", actor_membership_id=p.membership_id, target_type=obj.type,
              target_id=obj.public_id, data={"member": t.public_id})
    return bool(weg)
