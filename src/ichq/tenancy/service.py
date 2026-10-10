"""Firmen anlegen und nachschlagen.

* Anlegen und Statuswechsel nur über die Plattform-Transaktion (Control Plane).
* ``current_tenant`` liest über die Mandanten-Transaktion — RLS liefert nur die eigene Firma.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ichq.audit.service import record, record_platform
from ichq.core.errors import Conflict, NotFound, ValidationFailed
from ichq.db.session import current_tenant_id
from ichq.tenancy.models import Tenant

SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,46})[a-z0-9]$")
RESERVIERT = frozenset({"admin", "api", "app", "www", "platform", "control", "support", "status",
                        "mail", "static", "assets", "auth", "login", "onboard", "ic-ware", "ichq"})
SPRACHEN = frozenset({"de", "en"})
UEBERGAENGE: dict[str, frozenset[str]] = {
    "pending": frozenset({"active", "deactivated"}),
    "active": frozenset({"paused", "suspended", "deactivated"}),
    "paused": frozenset({"active", "suspended", "deactivated"}),
    "suspended": frozenset({"active", "deactivated"}),
    "deactivated": frozenset(),
}


@dataclass(frozen=True)
class TenantInfo:
    id: uuid.UUID
    slug: str
    name: str
    legal_name: str | None
    status: str
    timezone: str
    language: str
    currency: str
    created_at: datetime

    @classmethod
    def of(cls, t: Tenant) -> TenantInfo:
        return cls(t.id, t.slug, t.name, t.legal_name, t.status, t.timezone, t.language, t.currency,
                   t.created_at)


def _pruefen(slug: str, name: str, timezone: str, language: str, currency: str) -> None:
    if not SLUG.match(slug):
        raise ValidationFailed("slug: 3–48 Zeichen, a–z, 0–9 und Bindestrich, nicht am Rand")
    if slug in RESERVIERT:
        raise ValidationFailed("slug ist reserviert")
    if not name.strip() or len(name) > 120:
        raise ValidationFailed("name: 1–120 Zeichen")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationFailed("Zeitzone unbekannt (z. B. Europe/Berlin)") from None
    if language not in SPRACHEN:
        raise ValidationFailed(f"language muss eine von {sorted(SPRACHEN)} sein")
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValidationFailed("Währung: dreistelliger ISO-Code in Großbuchstaben, z. B. EUR")


def create_tenant(session: Session, *, name: str, slug: str, actor: str, legal_name: str | None = None,
                  timezone: str = "Europe/Berlin", language: str = "de", currency: str = "EUR") -> TenantInfo:
    slug = slug.strip().lower()
    _pruefen(slug, name, timezone, language, currency)
    tenant = Tenant(slug=slug, name=name.strip(), legal_name=legal_name, timezone=timezone,
                    language=language, currency=currency, status="pending")
    session.add(tenant)
    try:
        session.flush()
    except IntegrityError:
        raise Conflict("slug ist bereits vergeben") from None
    session.refresh(tenant)
    record_platform(session, "tenant.created", actor=actor, tenant_id=tenant.id,
                    data={"slug": slug, "name": tenant.name})
    return TenantInfo.of(tenant)


def get_tenant(session: Session, tenant_id: uuid.UUID) -> TenantInfo:
    t = session.get(Tenant, tenant_id)
    if t is None:
        raise NotFound("Firma nicht gefunden")
    return TenantInfo.of(t)


def get_tenant_by_slug(session: Session, slug: str) -> TenantInfo:
    t = session.scalars(select(Tenant).where(Tenant.slug == slug.strip().lower())).one_or_none()
    if t is None:
        raise NotFound("Firma nicht gefunden")
    return TenantInfo.of(t)


def set_status(session: Session, tenant_id: uuid.UUID, new_status: str, *, actor: str, reason: str) -> TenantInfo:
    t = session.get(Tenant, tenant_id, with_for_update=True)
    if t is None:
        raise NotFound("Firma nicht gefunden")
    if new_status not in UEBERGAENGE.get(t.status, frozenset()):
        raise Conflict(f"Statuswechsel {t.status} → {new_status} ist nicht erlaubt")
    if not reason.strip():
        raise ValidationFailed("reason ist Pflicht")
    alt, t.status = t.status, new_status
    session.flush()
    record_platform(session, "tenant.status_changed", actor=actor, tenant_id=t.id,
                    data={"from": alt, "to": new_status, "reason": reason})
    return TenantInfo.of(t)


def current_tenant(session: Session) -> TenantInfo:
    """Firma des aktuellen Mandantenkontexts — über RLS, nicht über einen Filter im Code."""
    tid = current_tenant_id(session)
    t = session.scalars(select(Tenant)).one_or_none()
    if t is None or t.id != tid:
        raise NotFound("Firma nicht gefunden")
    return TenantInfo.of(t)


PROFILFELDER = ("name", "legal_name", "timezone", "language", "currency")


def update_profile(session: Session, changes: dict[str, str | None], *,
                   actor_membership_id: uuid.UUID) -> TenantInfo:
    """M3: Firma ändert ihr eigenes Profil (Mandanten-Transaktion, RLS + Spaltenrechte).
    Gleiche Regeln wie beim Anlegen; Slug, Status und Plan sind hier nicht änderbar."""
    unbekannt = set(changes) - set(PROFILFELDER)
    if unbekannt:
        raise ValidationFailed(f"Nicht änderbar: {sorted(unbekannt)}")
    tid = current_tenant_id(session)
    t = session.scalars(select(Tenant).where(Tenant.id == tid).with_for_update()).one_or_none()
    if t is None:
        raise NotFound("Firma nicht gefunden")
    neu = {f: getattr(t, f) for f in PROFILFELDER}
    neu.update(changes)
    name = (neu["name"] or "").strip()
    legal = (neu["legal_name"] or "").strip() or None
    if legal is not None and len(legal) > 200:
        raise ValidationFailed("legal_name: höchstens 200 Zeichen")
    _pruefen(t.slug, name, str(neu["timezone"]), str(neu["language"]), str(neu["currency"]))
    alt = {f: getattr(t, f) for f in PROFILFELDER}
    t.name, t.legal_name = name, legal
    t.timezone, t.language, t.currency = str(neu["timezone"]), str(neu["language"]), str(neu["currency"])
    session.flush()
    diff = {f: {"from": alt[f], "to": getattr(t, f)} for f in PROFILFELDER if alt[f] != getattr(t, f)}
    if diff:
        record(session, "company.updated", actor_membership_id=actor_membership_id, target_type="company",
               data={"changes": diff})
    return TenantInfo.of(t)
