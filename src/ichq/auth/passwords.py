"""Passwörter: Argon2id-Hashes und eine Passwortregel nach NIST SP 800-63B.

Regel: 12–128 Zeichen, nicht unter den 10.000 häufigsten Passwörtern, enthält nicht
E-Mail-Namen oder Benutzernamen, nicht nur ein wiederholtes Zeichen. Bewusst KEINE
Pflicht zu Sonderzeichen/Ziffern — die erzeugt nachweislich schwächere Passwörter.
"""
from __future__ import annotations

import gzip
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ichq.core.config import Settings

MIN_LEN, MAX_LEN = 12, 128
_LISTE = Path(__file__).resolve().parent / "data" / "common-passwords.txt.gz"


@lru_cache(maxsize=1)
def _haeufige() -> frozenset[str]:
    with gzip.open(_LISTE, "rt", encoding="utf-8") as f:
        return frozenset(z.strip().lower() for z in f if z.strip())


@dataclass(frozen=True)
class PolicyViolation:
    code: str
    message: str


def check_policy(password: str, *, email: str | None = None, username: str | None = None) -> PolicyViolation | None:
    if len(password) < MIN_LEN:
        return PolicyViolation("too_short", f"Mindestens {MIN_LEN} Zeichen.")
    if len(password) > MAX_LEN:
        return PolicyViolation("too_long", f"Höchstens {MAX_LEN} Zeichen.")
    if len(set(password)) == 1:
        return PolicyViolation("repetitive", "Nicht nur ein wiederholtes Zeichen.")
    klein = password.lower()
    if klein in _haeufige() or klein.rstrip("0123456789!.") in _haeufige():
        return PolicyViolation("common", "Dieses Passwort ist zu verbreitet.")
    for teil in (email.split("@")[0] if email else None, username):
        if teil and len(teil) >= 3 and teil.lower() in klein:
            return PolicyViolation("contains_identity", "Das Passwort darf E-Mail oder Benutzernamen nicht enthalten.")
    return None


def hasher(settings: Settings) -> PasswordHasher:
    return PasswordHasher(time_cost=settings.argon2_time_cost, memory_cost=settings.argon2_memory_kib,
                          parallelism=settings.argon2_parallelism, hash_len=32, salt_len=16, type=Type.ID)


def hash_password(settings: Settings, password: str) -> str:
    return hasher(settings).hash(password)


@lru_cache(maxsize=4)
def _dummy(t: int, m: int, p: int) -> str:
    return PasswordHasher(time_cost=t, memory_cost=m, parallelism=p, type=Type.ID).hash("dummy-passwort-ohne-konto")


def verify_password(settings: Settings, stored: str | None, password: str) -> tuple[bool, bool]:
    """(stimmt, sollte_neu_gehasht_werden). Ohne gespeicherten Hash wird gegen einen Dummy geprüft,
    damit unbekannte Konten nicht schneller abgelehnt werden als bekannte."""
    h = hasher(settings)
    ziel = stored or _dummy(settings.argon2_time_cost, settings.argon2_memory_kib, settings.argon2_parallelism)
    try:
        h.verify(ziel, password[:MAX_LEN * 4])
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False, False
    if stored is None:
        return False, False
    return True, h.check_needs_rehash(stored)
