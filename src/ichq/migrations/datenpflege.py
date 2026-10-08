"""Hilfe für Daten-Änderungen in Migrationen.

Alle Tabellen haben ``FORCE ROW LEVEL SECURITY`` — das gilt auch für den Besitzer ``ichq_owner``, der die
Migrationen ausführt, und für ihn gibt es keine Policy. Ein ``UPDATE``/``INSERT … SELECT`` in einer Migration
sieht deshalb KEINE Zeile und tut still nichts (gefunden mit ``test_m1_altdaten_nach_0002``).

``ohne_force`` hebt ``FORCE`` für die Dauer der Daten-Änderung auf und setzt es danach wieder — innerhalb
derselben Migrations-Transaktion (transaction_per_migration). Scheitert etwas, rollt alles zurück, ``FORCE``
inklusive. Nur für Daten-Pflege in Migrationen benutzen, nie zur Laufzeit.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from alembic import op


@contextmanager
def ohne_force(*tabellen: str) -> Iterator[None]:
    for t in tabellen:
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
    yield
    for t in tabellen:
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
