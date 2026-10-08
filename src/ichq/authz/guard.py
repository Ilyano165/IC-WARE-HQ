"""Last-Admin-Schutz (ADR-011) — für JEDE Änderung, die Verwaltungsrechte kosten kann.

„Admin" ist, wer als aktive Mitgliedschaft EFFEKTIV alle ``ADMIN_PERMISSIONS`` hat — berechnet mit derselben
Funktion wie jede Anfrage (``effective``), also inklusive Einzelrechte-DENY, archivierter Rollen und der
gesperrten Rolle „Company Admin". Ablauf in EINER Transaktion:

1. alle aktiven Mitgliedschaften der Firma sperren (``FOR UPDATE``; RLS: nur diese Firma) — zwei gleichzeitige
   Änderungen können nicht beide „den anderen" Admin entfernen,
2. Admins zählen, Änderung ausführen, erneut zählen,
3. fiele die Zahl von > 0 auf 0 → ``LastAdmin`` (die Transaktion wird zurückgerollt).
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

from ichq.authz.effective import effective
from ichq.authz.registry import ADMIN_PERMISSIONS
from ichq.core.errors import AppError


class LastAdmin(AppError):
    status, code, title = 409, "last_admin", "Letzte Administration"


def _aktive(session: Session, *, lock: bool) -> list[uuid.UUID]:
    sql = "SELECT id FROM memberships WHERE status = 'active' ORDER BY id"
    return list(session.execute(text(sql + (" FOR UPDATE" if lock else ""))).scalars())


def is_admin(session: Session, membership_id: uuid.UUID) -> bool:
    return effective(session, membership_id).permissions >= ADMIN_PERMISSIONS


def admins(session: Session) -> list[uuid.UUID]:
    return [m for m in _aktive(session, lock=False) if is_admin(session, m)]


@contextmanager
def admin_remains(session: Session) -> Iterator[None]:
    _aktive(session, lock=True)
    vorher = len(admins(session))
    yield
    session.flush()
    if vorher > 0 and not admins(session):
        raise LastAdmin("Danach gäbe es in dieser Firma niemanden mehr mit Verwaltungsrechten")
