"""Typisierte Verknüpfungen zwischen Fachobjekten und Objektfreigaben.

Regeln (docs/core-object-model.md):
* Verknüpfungstyp muss in ``LINK_TYPES`` stehen und die Typkombination erlauben (zusätzlich CHECK in der DB).
* Anlegen/Entfernen: Änderungsrecht am Quellobjekt UND beide Objekte sichtbar.
* Lesen: nur Verknüpfungen, deren Gegenseite der Principal ebenfalls sehen darf.
* Freigaben: nur mit ``objects.share`` (Route) und nur für Objekte, die man selbst sieht.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from ichq.activity.service import record as activity
from ichq.audit.service import record as audit
from ichq.authz.service import Principal
from ichq.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from ichq.db.session import current_tenant_id
from ichq.objects.models import ObjectGrant, ObjectLink, ObjectRow
from ichq.objects.registry import LINK_TYPES
from ichq.objects.service import Member, check_public_id
from ichq.objects.visibility import can_update, visible_clause

MAX_LINKS = 200


def create_link(session: Session, principal: Principal, source: ObjectRow, target: ObjectRow,
                link_type: str) -> ObjectLink:
    lt = LINK_TYPES.get(link_type)
    if lt is None:
        raise ValidationFailed("link_type ist unbekannt")
    if not lt.allows(source.type, target.type):
        raise ValidationFailed(f"Verknüpfung '{link_type}' ist von {source.type} nach {target.type} nicht erlaubt")
    if source.id == target.id:
        raise ValidationFailed("Ein Objekt kann nicht mit sich selbst verknüpft werden")
    if not can_update(principal, source):
        raise PermissionDenied("Keine Berechtigung, dieses Objekt zu ändern")
    link = ObjectLink(tenant_id=current_tenant_id(session), link_type=link_type, source_id=source.id,
                      source_type=source.type, target_id=target.id, target_type=target.type,
                      created_by_membership_id=principal.membership_id)
    try:
        with session.begin_nested():
            session.add(link)
            session.flush()
    except IntegrityError:
        raise Conflict("Diese Verknüpfung besteht bereits") from None
    activity(session, source.id, "object.linked", actor_membership_id=principal.membership_id,
             data={"link_type": link_type})   # keine Ref auf das Ziel: es ist evtl. nicht für alle sichtbar
    audit(session, "object.linked", actor_membership_id=principal.membership_id, target_type=source.type,
          target_id=source.public_id, data={"link": link.public_id, "link_type": link_type,
                                            "target": target.public_id})
    return link


def delete_link(session: Session, principal: Principal, ref: str) -> None:
    check_public_id(ref)
    q, z = aliased(ObjectRow), aliased(ObjectRow)
    zeile = session.execute(
        select(ObjectLink, q).join(q, q.id == ObjectLink.source_id).join(z, z.id == ObjectLink.target_id)
        .where(ObjectLink.public_id == ref, visible_clause(principal, q), visible_clause(principal, z))
    ).one_or_none()
    if zeile is None:
        raise NotFound()
    link, quelle = zeile
    if not can_update(principal, quelle):
        raise PermissionDenied("Keine Berechtigung, dieses Objekt zu ändern")
    session.delete(link)
    activity(session, quelle.id, "object.unlinked", actor_membership_id=principal.membership_id,
             data={"link_type": link.link_type})
    audit(session, "object.unlinked", actor_membership_id=principal.membership_id, target_type=quelle.type,
          target_id=quelle.public_id, data={"link": ref, "link_type": link.link_type})


def links_of(session: Session, principal: Principal, obj: ObjectRow) -> list[dict[str, Any]]:
    """Ausgehende und eingehende Verknüpfungen — nur mit sichtbarer Gegenseite. Höchstens ``MAX_LINKS``."""
    andere = aliased(ObjectRow)
    ergebnis = []
    for richtung, eigene, fremde in (("outgoing", ObjectLink.source_id, ObjectLink.target_id),
                                     ("incoming", ObjectLink.target_id, ObjectLink.source_id)):
        rows = session.execute(
            select(ObjectLink, andere).join(andere, and_(andere.id == fremde, andere.tenant_id == ObjectLink.tenant_id))
            .where(eigene == obj.id, visible_clause(principal, andere))
            .order_by(ObjectLink.created_at, ObjectLink.id).limit(MAX_LINKS)).all()
        ergebnis += [{"id": link.public_id, "link_type": link.link_type, "direction": richtung,
                      "object": {"id": o.public_id, "type": o.type, "title": o.title},
                      "created_at": link.created_at} for link, o in rows]
    return ergebnis[:MAX_LINKS]


MANUAL, AUTO = "manual", "task_assignment"


def grant(session: Session, principal: Principal, obj: ObjectRow, m: Member) -> bool:
    """Manuelle Freigabe (API). ``False``, wenn schon manuell freigegeben."""
    if session.get(ObjectGrant, (obj.id, m.id, MANUAL)) is not None:
        return False
    session.add(ObjectGrant(tenant_id=current_tenant_id(session), object_id=obj.id, membership_id=m.id,
                            source=MANUAL, granted_by_membership_id=principal.membership_id))
    session.flush()
    activity(session, obj.id, "object.shared", actor_membership_id=principal.membership_id,
             data={"member": m.public_id})
    audit(session, "object.shared", actor_membership_id=principal.membership_id, target_type=obj.type,
          target_id=obj.public_id, data={"member": m.public_id, "source": MANUAL})
    return True


def grant_for_assignment(session: Session, principal: Principal, obj: ObjectRow, m: Member) -> None:
    """Automatische Freigabe, gebunden an die aktuelle Zuweisung. Unabhängig von manuellen Freigaben."""
    if session.get(ObjectGrant, (obj.id, m.id, AUTO)) is not None:
        return
    session.add(ObjectGrant(tenant_id=current_tenant_id(session), object_id=obj.id, membership_id=m.id,
                            source=AUTO, granted_by_membership_id=principal.membership_id))
    session.flush()
    audit(session, "object.shared", actor_membership_id=principal.membership_id, target_type=obj.type,
          target_id=obj.public_id, data={"member": m.public_id, "source": AUTO})


def drop_assignment_grant(session: Session, principal: Principal, obj: ObjectRow,
                          membership_id: uuid.UUID) -> bool:
    """Bei Neuzuweisung/Entzug: NUR die automatische Freigabe der bisherigen Person entfernen.
    Eine manuelle Freigabe derselben Person bleibt bestehen."""
    n = session.execute(delete(ObjectGrant).where(
        ObjectGrant.object_id == obj.id, ObjectGrant.membership_id == membership_id,
        ObjectGrant.source == AUTO)).rowcount  # type: ignore[attr-defined]
    if n:
        audit(session, "object.unshared", actor_membership_id=principal.membership_id, target_type=obj.type,
              target_id=obj.public_id, data={"source": AUTO, "reason": "reassigned"})
    return bool(n)


def revoke(session: Session, principal: Principal, obj: ObjectRow, m: Member) -> None:
    """Entzieht nur die MANUELLE Freigabe. Eine Freigabe aus Zuweisung endet mit der Zuweisung."""
    n = session.execute(delete(ObjectGrant).where(ObjectGrant.object_id == obj.id, ObjectGrant.membership_id == m.id,
                                                  ObjectGrant.source == MANUAL)).rowcount  # type: ignore[attr-defined]
    if not n:
        raise NotFound("Keine manuelle Freigabe für dieses Mitglied")
    activity(session, obj.id, "object.unshared", actor_membership_id=principal.membership_id,
             data={"member": m.public_id})
    audit(session, "object.unshared", actor_membership_id=principal.membership_id, target_type=obj.type,
          target_id=obj.public_id, data={"member": m.public_id, "source": MANUAL})


def grants_of(session: Session, obj: ObjectRow) -> list[tuple[uuid.UUID, str]]:
    return [(r.membership_id, r.source) for r in session.execute(
        select(ObjectGrant.membership_id, ObjectGrant.source).where(ObjectGrant.object_id == obj.id)
        .order_by(ObjectGrant.created_at, ObjectGrant.source).limit(MAX_LINKS)).all()]
