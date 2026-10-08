from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from ichq.audit.models import AuditEvent, PlatformAuditEvent
from ichq.core.logging import redact_value, request_id_var
from ichq.db.session import current_tenant_id


def _bereinigt(data: dict[str, Any] | None) -> dict[str, Any]:
    return {str(k): redact_value(str(k), v) for k, v in (data or {}).items()}


def record(session: Session, action: str, *, actor_membership_id: uuid.UUID | None = None,
           target_type: str | None = None, target_id: str | None = None,
           data: dict[str, Any] | None = None) -> None:
    """Audit in der laufenden Mandanten-Transaktion — wird nur geschrieben, wenn sie gelingt."""
    session.add(AuditEvent(
        tenant_id=current_tenant_id(session), action=action, actor_membership_id=actor_membership_id,
        target_type=target_type, target_id=target_id, request_id=request_id_var.get(),
        data=_bereinigt(data)))


def record_platform(session: Session, action: str, *, actor: str, tenant_id: uuid.UUID | None = None,
                    data: dict[str, Any] | None = None) -> None:
    session.add(PlatformAuditEvent(action=action, actor=actor, tenant_id=tenant_id,
                                   request_id=request_id_var.get(), data=_bereinigt(data)))
