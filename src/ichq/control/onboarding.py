"""Firma mit Administrator in einem Zug anlegen (ADR-021) — ersetzt die sieben CLI-Schritte von
``deploy/hq setup-admin`` (Firma anlegen, aktivieren, Konto, Passwort, Konto aktivieren, Mitgliedschaft, Admin-Rolle).

Die Schritte laufen in drei Transaktionen, weil drei Datenbankrollen beteiligt sind (Plattform, Anmeldung, Mandant).
Deshalb wird ALLES, was scheitern kann, vorher geprüft (Kürzel, E-Mail, Passwortregel); Firma, Konto, Betreiber und
ein eingelöster Einrichtungscode entstehen gemeinsam in der ersten Transaktion.
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from ichq.auth import account
from ichq.auth.passwords import check_policy
from ichq.authz.flags import set_flag
from ichq.authz.registry import FLAGGABLE_MODULES
from ichq.authz.templates import make_company_admin
from ichq.control import service as control
from ichq.core.config import Settings
from ichq.core.errors import AppError, Conflict, NotFound, ValidationFailed
from ichq.db.engine import Engines
from ichq.db.session import auth_transaction, platform_transaction, tenant_transaction
from ichq.identity.service import add_membership, create_user
from ichq.tenancy import service as tenancy
from ichq.tenancy.service import TenantInfo

_UMLAUT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def slug_vorschlag(name: str) -> str:
    """„Müller & Söhne GmbH“ → ``mueller-soehne-gmbh`` (3–48 Zeichen, a–z, 0–9, Bindestrich)."""
    roh = unicodedata.normalize("NFKD", name.strip().lower().translate(_UMLAUT))
    slug = re.sub(r"[^a-z0-9]+", "-", roh.encode("ascii", "ignore").decode()).strip("-")[:48].strip("-")
    return slug if len(slug) >= 3 else (slug + "-firma").strip("-")


@dataclass(frozen=True)
class Firma:
    name: str
    slug: str
    legal_name: str | None = None
    timezone: str = "Europe/Berlin"
    language: str = "de"
    currency: str = "EUR"
    modules_off: tuple[str, ...] = ()


@dataclass(frozen=True)
class Admin:
    """``user_id`` gesetzt = bestehendes Konto; sonst entsteht ein neues Konto mit ``password``."""

    user_id: uuid.UUID | None = None
    email: str = ""
    name: str = ""
    password: str = field(default="", repr=False)


def _pruefe_admin(admin: Admin) -> None:
    if admin.user_id is not None:
        return
    verstoss = check_policy(admin.password, email=admin.email)
    if verstoss:
        raise ValidationFailed(f"Passwort: {verstoss.message}")


def create_company(engines: Engines, settings: Settings, firma: Firma, admin: Admin, *, actor: str,
                   in_platform_tx: Callable[[Session, uuid.UUID], None] | None = None) -> TenantInfo:
    """Legt die Firma an, aktiviert sie und macht ``admin`` zum Company Admin. ``in_platform_tx`` läuft in der
    ersten Transaktion (Ersteinrichtung: Code einlösen, Betreiber eintragen)."""
    unbekannt = sorted(set(firma.modules_off) - FLAGGABLE_MODULES)
    if unbekannt:
        raise ValidationFailed(f"Module nicht schaltbar: {unbekannt}")
    _pruefe_admin(admin)
    with platform_transaction(engines.platform) as s:
        if admin.user_id is None:
            if control.user_by_email(s, admin.email) is not None:
                raise Conflict("Für diese E-Mail gibt es bereits ein Konto — „bestehendes Konto“ wählen")
            uid = create_user(s, email=admin.email, display_name=admin.name)
        else:
            uid = admin.user_id
            if s.execute(text("SELECT 1 FROM users WHERE id = :u AND status = 'active'"), {"u": uid}).scalar() is None:
                raise NotFound("Konto nicht gefunden oder nicht aktiv")
        if in_platform_tx is not None:
            in_platform_tx(s, uid)
        t = tenancy.create_tenant(s, name=firma.name, slug=firma.slug, legal_name=firma.legal_name or None,
                                  timezone=firma.timezone, language=firma.language, currency=firma.currency,
                                  actor=actor)
        t = tenancy.set_status(s, t.id, "active", actor=actor, reason="Anlage in der Unternehmensverwaltung")
        for modul in firma.modules_off:
            set_flag(s, t.id, modul, False, actor=actor, reason="bei der Anlage abgewählt")
    if admin.user_id is None:
        with auth_transaction(engines.auth) as s:
            for o in (account.set_initial_password(s, settings, uid, admin.password, actor=actor),
                      account.set_status(s, uid, "active", actor=actor, reason="Anlage in der Unternehmensverwaltung")):
                if not o.ok:   # nach der Vorprüfung nicht zu erwarten; Firma existiert dann ohne Admin
                    raise AppError(f"Konto konnte nicht aktiviert werden ({o.error}) — Firma „{t.slug}“ ist angelegt, "
                                   "Administrator bitte in der Unternehmensverwaltung zuweisen")
    assign_admin(engines, t.id, uid)
    return t


def assign_admin(engines: Engines, tenant_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Konto zur Firma hinzufügen (falls nötig) und zum Company Admin machen. Gibt False zurück, wenn schon Admin."""
    with tenant_transaction(engines.app, tenant_id) as s:
        mid = s.execute(text("SELECT id FROM memberships WHERE user_id = :u"), {"u": user_id}).scalar()
        if mid is None:
            mid = add_membership(s, user_id=user_id)
        else:
            s.execute(text("UPDATE memberships SET status = 'active' WHERE id = :m AND status <> 'active'"),
                      {"m": mid})
        return make_company_admin(s, mid)


def first_setup(engines: Engines, settings: Settings, *, code: str, firma: Firma, admin: Admin) -> TenantInfo:
    """Ersteinrichtung: Code einlösen, erstes Konto wird Betreiber UND Company Admin der ersten Firma."""
    actor = f"setup:{admin.email.strip().lower()}"[:120]

    def einloesen(s: Session, uid: uuid.UUID) -> None:
        control.redeem_setup_code(s, code)
        control.add_operator(s, uid, actor=actor)
    return create_company(engines, settings, firma, Admin(email=admin.email, name=admin.name, password=admin.password),
                          actor=actor, in_platform_tx=einloesen)
