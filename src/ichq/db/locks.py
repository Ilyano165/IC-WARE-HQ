"""Advisory-Locks für Jobs: verhindern Parallelläufe über Prozesse und Server hinweg (eine Datenbank)."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, text

# Feste Schlüssel je Job — nie wiederverwenden
NOTIFICATIONS_SCAN = 0x1C4A_5C40
AUTH_CLEANUP = 0x1C4A_C1EA


@contextmanager
def job_lock(engine: Engine, key: int) -> Iterator[bool]:
    """Liefert ``True``, wenn die Sperre erworben wurde, sonst ``False`` (anderer Lauf aktiv). Gibt sie am Ende frei."""
    with engine.connect() as conn:
        erworben = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar())
        try:
            yield erworben
        finally:
            if erworben:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
                conn.commit()
