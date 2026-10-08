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
    "users.read", "users.create", "users.update", "users.deactivate",
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
    "comments.read", "comments.create", "comments.moderate",
    "activity.read",
    "objects.read_all", "objects.share",
})

assert all(_FORMAT.match(p) for p in PERMISSIONS), "Rechte-Format verletzt"


def is_known(permission: str) -> bool:
    return permission in PERMISSIONS
