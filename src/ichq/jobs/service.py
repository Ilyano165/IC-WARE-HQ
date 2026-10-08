from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ichq.core.logging import request_id_var
from ichq.db.session import current_tenant_id
from ichq.jobs.models import OutboxEvent


def emit_event(session: Session, event_type: str, payload: dict[str, Any] | None = None,
               max_attempts: int = 5) -> None:
    """Ereignis in DERSELBEN Transaktion wie die fachliche Änderung speichern.

    Rollt die Transaktion zurück, gibt es auch kein Ereignis — und umgekehrt.
    """
    session.add(OutboxEvent(tenant_id=current_tenant_id(session), type=event_type, payload=payload or {},
                            max_attempts=max_attempts, request_id=request_id_var.get()))
