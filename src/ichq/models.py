"""Registriert alle Tabellen in ``Base.metadata``.

Warum es dieses Modul gibt: Tabellen verweisen schichtübergreifend aufeinander
(``audit_events`` → ``memberships``). SQLAlchemy löst solche Fremdschlüssel erst
beim Schreiben auf — fehlt das Modul mit der Zieltabelle im Prozess, scheitert
der Schreibvorgang zur Laufzeit. Jeder Einstiegspunkt (App, CLI, ASGI, Migrationen)
lädt deshalb dieses Modul. ``assert_complete()`` prüft das beim Start.
"""
from __future__ import annotations

from ichq.audit import models as audit_models
from ichq.auth import models as auth_models
from ichq.authz import models as authz_models
from ichq.db.base import Base
from ichq.identity import models as identity_models
from ichq.jobs import models as jobs_models
from ichq.tenancy import models as tenancy_models

MODULES = (tenancy_models, identity_models, authz_models, audit_models, jobs_models, auth_models)


def assert_complete() -> int:
    """Wirft, wenn ein Fremdschlüssel auf eine nicht registrierte Tabelle zeigt. Gibt die Tabellenzahl zurück."""
    fehlend = sorted({
        f"{t.name} → {fk.target_fullname.split('.')[0]}"
        for t in Base.metadata.tables.values()
        for fk in t.foreign_keys
        if fk.target_fullname.split(".")[0] not in Base.metadata.tables
    })
    if fehlend:
        raise RuntimeError("Modelle unvollständig registriert: " + ", ".join(fehlend))
    return len(Base.metadata.tables)
