"""D0: Dashboard — EIN Aufruf liefert alle Widgets, die der Principal effektiv sehen darf (ADR-014)."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from ichq.api.security import TenantDB, require, tenant_db
from ichq.authz.service import Principal
from ichq.dashboard.service import build

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


@router.get("/dashboard")
def dashboard(p: Principal = Depends(require("dashboard.read")), db: TenantDB = Depends(tenant_db),
              widget: Annotated[str | None, Query(pattern="^[a-z_]{1,32}$")] = None) -> dict[str, Any]:
    """Widgets nach effektiven Rechten; ``widget`` lädt eines neu. Unbekannt oder ohne Recht → 404."""
    with db() as s:
        return build(s, p, only=widget)
