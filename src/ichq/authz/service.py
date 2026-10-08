"""Principal und die Entscheidungsfunktion. Die Rechte selbst berechnet ``ichq.authz.effective`` (ADR-011)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ichq.authz.effective import effective
from ichq.authz.registry import is_known, module_of


@dataclass(frozen=True)
class Principal:
    """Wer handelt — immer im Kontext genau einer Firma."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    membership_id: uuid.UUID
    permissions: frozenset[str] = field(default_factory=frozenset)
    tenant_status: str = "active"     # 'paused' → nur lesende Anfragen (zentral in ichq.api.security)
    disabled_modules: frozenset[str] = field(default_factory=frozenset)   # Feature-Flags: zweite Sicherung + Fehlercode


def decide(principal: Principal | None, permission: str) -> bool:
    """Unbekanntes Recht/kein Principal → nein; abgeschaltetes Modul → nein; sonst die berechneten Rechte."""
    if principal is None or not is_known(permission):
        return False
    if module_of(permission) in principal.disabled_modules:
        return False
    return permission in principal.permissions


def permissions_for_membership(session: Session, membership_id: uuid.UUID) -> frozenset[str]:
    """Effektive Rechte (Feature-Flags, Einzelrechte, Rollen — ``ichq.authz.effective``). Mandanten-Transaktion."""
    return effective(session, membership_id).permissions


def principal_for(session: Session, *, user_id: uuid.UUID, tenant_id: uuid.UUID, membership_id: uuid.UUID,
                  tenant_status: str = "active") -> Principal:
    e = effective(session, membership_id)
    return Principal(user_id=user_id, tenant_id=tenant_id, membership_id=membership_id,
                     permissions=e.permissions, tenant_status=tenant_status, disabled_modules=e.disabled_modules)
