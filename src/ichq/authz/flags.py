"""Feature-Flags je Firma (M4 vorbereitet, Pläne folgen mit M19). Schreibt NUR die Control Plane
(Rolle ``ichq_platform``, heute per CLI) — es gibt keine Route dafür."""
from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from ichq.audit.service import record_platform
from ichq.authz.registry import CORE_MODULES, FLAGGABLE_MODULES
from ichq.core.errors import ValidationFailed


def set_flag(session: Session, tenant_id: uuid.UUID, module: str, enabled: bool, *, actor: str,
             reason: str) -> None:
    """Plattform-Transaktion. Kernmodule (Rechte, Mitglieder, Profil, Audit) lassen sich nicht abschalten."""
    if module not in FLAGGABLE_MODULES:
        art = "Kernmodul" if module in CORE_MODULES else "Unbekanntes Modul"
        raise ValidationFailed(f"{art} '{module}' kann nicht geschaltet werden")
    if not reason.strip():
        raise ValidationFailed("Begründung fehlt")
    session.execute(text("""
        INSERT INTO tenant_feature_flags(tenant_id, module, enabled, updated_by) VALUES (:t, :m, :e, :a)
        ON CONFLICT (tenant_id, module) DO UPDATE SET enabled = :e, updated_by = :a, updated_at = now()"""),
        {"t": tenant_id, "m": module, "e": enabled, "a": actor})
    record_platform(session, "tenant.feature_flag_set", actor=actor, tenant_id=tenant_id,
                    data={"module": module, "enabled": enabled, "reason": reason})
