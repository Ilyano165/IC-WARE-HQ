"""Bausteine für Fachtabellen auf dem Objektmodell (ADR-008, ADR-020).

Jede Fachtabelle verweist mit ``(tenant_id, id, object_type) → objects`` auf ihre Objektzeile; Verweise auf
Mitgliedschaften, Objekte und andere Fachtabellen sind immer zusammengesetzt ``(tenant_id, x_id)`` — so kann
keine Zeile auf Daten einer fremden Firma zeigen, auch nicht bei direktem Datenbankzugriff.
"""
from __future__ import annotations

from sqlalchemy import ForeignKeyConstraint


def typed_object_fk(ondelete: str = "CASCADE") -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["tenant_id", "id", "object_type"], ["objects.tenant_id", "objects.id", "objects.type"],
                                ondelete=ondelete)


def member_fk(spalte: str, ondelete: str = "RESTRICT") -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["tenant_id", spalte], ["memberships.tenant_id", "memberships.id"], ondelete=ondelete)


def object_fk(spalte: str, ondelete: str = "RESTRICT") -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["tenant_id", spalte], ["objects.tenant_id", "objects.id"], ondelete=ondelete)


def table_fk(spalte: str, tabelle: str, ondelete: str = "RESTRICT") -> ForeignKeyConstraint:
    """Verweis auf eine andere Fachtabelle (Ziel braucht ``UNIQUE (tenant_id, id)``)."""
    return ForeignKeyConstraint(["tenant_id", spalte], [f"{tabelle}.tenant_id", f"{tabelle}.id"], ondelete=ondelete)
