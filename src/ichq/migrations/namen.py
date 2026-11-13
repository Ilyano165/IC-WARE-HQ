"""Constraint-Namen für Migrationen: PostgreSQL erlaubt höchstens 63 Zeichen. Längere Namen werden genauso gekürzt
wie die Namenskonvention der Modelle (SQLAlchemy: 55 Zeichen + ``_`` + letzte 4 Stellen des MD5) — so stimmen Modell
und Datenbank überein."""
from __future__ import annotations

import hashlib

MAX = 63


def kurz(name: str) -> str:
    if len(name) <= MAX:
        return name
    return name[: MAX - 8] + "_" + hashlib.md5(name.encode(), usedforsecurity=False).hexdigest()[-4:]
