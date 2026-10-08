"""Zentrale Rechte-Registry.

Übernommen aus dem M4-Prototyp (M0: REUSE als Konzept) und auf das M0-Zielbild
angepasst. Es gibt keine Platzhalter wie ``finance.*``. Ein Recht, das hier nicht
steht, existiert nicht — ``require()`` lehnt es schon beim Programmstart ab.
"""
from __future__ import annotations

import re

_FORMAT = re.compile(r"^[a-z][a-z_]*(\.[a-z][a-z_]*)+$")

PERMISSIONS: frozenset[str] = frozenset({
    "dashboard.read",
    "company.read", "company.update",
    "users.read", "users.create", "users.update", "users.deactivate", "users.override",
    "roles.read", "roles.create", "roles.update", "roles.delete", "roles.assign",
    "customers.read", "customers.create", "customers.update", "customers.delete", "customers.export",
    "projects.read", "projects.create", "projects.update", "projects.delete", "projects.assign",
    "tasks.read", "tasks.create", "tasks.update", "tasks.delete", "tasks.assign",
    "finance.read", "finance.create", "finance.update", "finance.approve", "finance.export",
    "invoices.read", "invoices.create", "invoices.update", "invoices.delete", "invoices.approve",
    "invoices.export",
    "files.read", "files.upload", "files.update", "files.delete", "files.share",
    "chat.read", "chat.create", "chat.moderate",
    "calendar.read", "calendar.create", "calendar.update", "calendar.delete",
    "audit.read", "audit.export",
    "settings.read", "settings.update",
    # C0 Core-Plattform (docs/core-permissions.md)
    "contracts.read", "contracts.update",
    # Fachrechte je Objekttyp (Entscheidung 3a): Fahrten/Fahrzeuge, Reisen, Bewirtung, Lieferanten.
    # Schema wie überall: .read/.update (nicht .write); create/delete/export erst mit dem jeweiligen Fachmodul.
    "vehicles.read", "vehicles.update",
    "travel.read", "travel.update",
    "hospitality.read", "hospitality.update",
    "suppliers.read", "suppliers.update",
    "comments.read", "comments.create", "comments.moderate",
    "activity.read",
    "objects.read_all", "objects.share",
})

assert all(_FORMAT.match(p) for p in PERMISSIONS), "Rechte-Format verletzt"


def is_known(permission: str) -> bool:
    return permission in PERMISSIONS


def module_of(permission: str) -> str:
    return permission.split(".", 1)[0]


MODULES: frozenset[str] = frozenset(module_of(p) for p in PERMISSIONS)

# Module, die ein Feature-Flag NIE abschalten kann: ohne sie ließe sich die Firma nicht mehr verwalten
# (Rechte, Mitglieder, Profil) oder nicht mehr prüfen (Audit). Feature-Flags sind für Fachmodule da.
CORE_MODULES: frozenset[str] = frozenset({"company", "users", "roles", "audit", "settings"})
FLAGGABLE_MODULES: frozenset[str] = MODULES - CORE_MODULES

# Rechte, mit denen man Rechte, Personen oder festgeschriebene Daten verändert — in Oberfläche und Doku
# hervorgehoben (Prototyp: „kritisch"). Keine Entscheidungslogik hängt daran.
CRITICAL: frozenset[str] = frozenset({
    "users.update", "users.deactivate", "users.override",
    "roles.create", "roles.update", "roles.delete", "roles.assign",
    "company.update", "settings.update", "invoices.approve", "finance.approve", "projects.assign",
    "objects.read_all", "objects.share", "audit.export",
})

# Verwaltungsrechte: wer alle drei effektiv hat, zählt als Admin (Last-Admin-Schutz, ADR-011)
ADMIN_PERMISSIONS: frozenset[str] = frozenset({"users.deactivate", "roles.update", "roles.assign"})

assert CRITICAL <= PERMISSIONS and ADMIN_PERMISSIONS <= PERMISSIONS and CORE_MODULES <= MODULES
