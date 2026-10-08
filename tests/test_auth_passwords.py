"""Passwortregel und Argon2id."""
from __future__ import annotations

import pytest

from ichq.auth.passwords import check_policy, hash_password, verify_password
from ichq.core.config import Settings
from ichq.db.engine import Engines
from tests.auth_helpers import PASSWORT, alle_textwerte, db, make_user


@pytest.mark.parametrize("pw,code", [
    ("kurz", "too_short"), ("x" * 129, "too_long"), ("aaaaaaaaaaaaaaaa", "repetitive"),
    ("password1234", "common"), ("qwertyuiop123", "common"), ("unbelievable", "common"),
    ("anna.mueller-2026", "contains_identity"),
])
def test_passwortregel_lehnt_ab(pw: str, code: str) -> None:
    v = check_policy(pw, email="anna.mueller@firma.test")
    assert v is not None and v.code == code


@pytest.mark.parametrize("pw", [PASSWORT, "korrekt pferd batterie heftklammer", "Zwölf Zeichen ä"])
def test_passwortregel_erlaubt_lange_passphrasen(pw: str) -> None:
    assert check_policy(pw, email="x@y.test") is None


def test_keine_kompositionsregeln() -> None:
    """NIST 800-63B: keine Pflicht zu Ziffern/Sonderzeichen — lange Passphrasen sind besser."""
    assert check_policy("ganz ohne ziffern oder zeichen", email="x@y.test") is None


def test_argon2id_hash(settings: Settings) -> None:
    h = hash_password(settings, PASSWORT)
    assert h.startswith("$argon2id$v=19$") and PASSWORT not in h
    assert hash_password(settings, PASSWORT) != h               # eigenes Salz je Hash
    assert verify_password(settings, h, PASSWORT) == (True, False)
    assert verify_password(settings, h, PASSWORT + "x")[0] is False
    assert verify_password(settings, None, PASSWORT) == (False, False)   # Dummy-Prüfung ohne Konto
    assert verify_password(settings, "kein-hash", PASSWORT) == (False, False)


def test_rehash_bei_staerkeren_parametern(settings: Settings) -> None:
    alt = hash_password(settings, PASSWORT)
    staerker = settings.model_copy(update={"argon2_time_cost": settings.argon2_time_cost + 1})
    assert verify_password(staerker, alt, PASSWORT) == (True, True)


def test_datenbank_erzwingt_argon2id(world, engines: Engines) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(Exception, match="ck_users_password_argon2id"):
        db(engines, "UPDATE users SET password_hash = 'klartext' WHERE id = %s", (world.user_a,))
    with pytest.raises(Exception, match="ck_users_active_needs_password"):
        db(engines, "UPDATE users SET status = 'active', password_hash = NULL WHERE id = %s", (world.user_a,))


def test_nirgends_klartext(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "klar@test.de")
    assert PASSWORT not in alle_textwerte(engines)
