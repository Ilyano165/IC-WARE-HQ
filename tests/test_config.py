"""Konfigurationsprüfung: keine Standardwerte für Geheimnisse, keine Werte in Fehlermeldungen."""
from __future__ import annotations

from pathlib import Path

import pytest

from ichq.core.config import ConfigError, load_settings, read_secret_env

GEHEIM = "geheim-wert-der-nie-auftauchen-darf-123"


def basis(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {
        "ICHQ_DATABASE_URL": "postgresql://ichq_app:a@db/ichq",
        "ICHQ_PLATFORM_DATABASE_URL": "postgresql://ichq_platform:b@db/ichq",
        "ICHQ_WORKER_DATABASE_URL": "postgresql://ichq_worker:c@db/ichq",
        "ICHQ_AUTH_DATABASE_URL": "postgresql://ichq_auth:d@db/ichq",
        "ICHQ_SECRET_KEY": GEHEIM,
        "ICHQ_SESSION_SECRET": "anderes-geheimnis-mit-genug-zeichen-xyz",
        "ICHQ_STORAGE_PATH": str(tmp_path),
    }
    env.update(extra)
    return env


def test_gueltige_konfiguration(tmp_path: Path) -> None:
    s = load_settings(basis(tmp_path))
    assert s.env == "development" and s.storage_backend == "local"


@pytest.mark.parametrize("fehlt", ["ICHQ_SECRET_KEY", "ICHQ_SESSION_SECRET", "ICHQ_DATABASE_URL",
                                   "ICHQ_PLATFORM_DATABASE_URL", "ICHQ_WORKER_DATABASE_URL",
                                   "ICHQ_AUTH_DATABASE_URL"])
def test_pflichtwerte_ohne_standard(tmp_path: Path, fehlt: str) -> None:
    env = basis(tmp_path)
    del env[fehlt]
    with pytest.raises(ConfigError) as e:
        load_settings(env)
    assert fehlt in str(e.value)


@pytest.mark.parametrize("wert", ["change-me", "kurz", "secret"])
def test_schwache_oder_platzhalter_geheimnisse(tmp_path: Path, wert: str) -> None:
    with pytest.raises(ConfigError, match="ICHQ_SECRET_KEY"):
        load_settings(basis(tmp_path, ICHQ_SECRET_KEY=wert))


def test_gleiche_geheimnisse_abgelehnt(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="verschieden"):
        load_settings(basis(tmp_path, ICHQ_SESSION_SECRET=GEHEIM))


def test_gleiche_datenbankrolle_abgelehnt(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="getrennte Datenbankrollen"):
        load_settings(basis(tmp_path, ICHQ_WORKER_DATABASE_URL="postgresql://ichq_app:a@db/ichq"))


def test_produktion_ohne_superuser_und_docs(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Superuser"):
        load_settings(basis(tmp_path, ICHQ_ENV="production", ICHQ_PUBLIC_ORIGIN="https://app.example.org",
                            ICHQ_DATABASE_URL="postgresql://postgres:x@db/ichq"))
    with pytest.raises(ConfigError, match="expose_docs"):
        load_settings(basis(tmp_path, ICHQ_ENV="production", ICHQ_EXPOSE_DOCS="true",
                            ICHQ_PUBLIC_ORIGIN="https://app.example.org"))
    with pytest.raises(ConfigError, match="log_format"):
        load_settings(basis(tmp_path, ICHQ_ENV="production", ICHQ_LOG_FORMAT="console",
                            ICHQ_PUBLIC_ORIGIN="https://app.example.org"))
    prod = basis(tmp_path, ICHQ_ENV="production", ICHQ_PUBLIC_ORIGIN="https://app.example.org")
    assert load_settings(prod).env == "production"
    with pytest.raises(ConfigError, match="public_origin"):
        load_settings(basis(tmp_path, ICHQ_ENV="production"))
    with pytest.raises(ConfigError, match="cookie_secure"):
        load_settings({**prod, "ICHQ_COOKIE_SECURE": "false"})
    with pytest.raises(ConfigError, match="argon2_memory_kib"):
        load_settings({**prod, "ICHQ_ARGON2_MEMORY_KIB": "8192"})


def test_s3_braucht_zugangsdaten(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="s3_bucket"):
        load_settings(basis(tmp_path, ICHQ_STORAGE_BACKEND="s3"))


def test_secret_dateien(tmp_path: Path) -> None:
    datei = tmp_path / "secret_key"
    datei.write_text("aus-der-datei-gelesen-mit-genug-laenge-42\n")
    env = basis(tmp_path)
    del env["ICHQ_SECRET_KEY"]
    env["ICHQ_SECRET_KEY_FILE"] = str(datei)
    s = load_settings(env)
    assert s.secret_key.get_secret_value() == "aus-der-datei-gelesen-mit-genug-laenge-42"
    assert read_secret_env("SECRET_KEY", env) == "aus-der-datei-gelesen-mit-genug-laenge-42"


def test_secret_doppelt_gesetzt(tmp_path: Path) -> None:
    datei = tmp_path / "s"
    datei.write_text("x" * 40)
    with pytest.raises(ConfigError, match="beide gesetzt"):
        load_settings(basis(tmp_path, ICHQ_SECRET_KEY_FILE=str(datei)))


def test_fehlende_secret_datei(tmp_path: Path) -> None:
    env = basis(tmp_path)
    del env["ICHQ_SECRET_KEY"]
    env["ICHQ_SECRET_KEY_FILE"] = str(tmp_path / "gibtsnicht")
    with pytest.raises(ConfigError, match="nicht lesbar"):
        load_settings(env)


def test_geheimnisse_erscheinen_nirgends(tmp_path: Path) -> None:
    s = load_settings(basis(tmp_path))
    assert GEHEIM not in repr(s) and GEHEIM not in str(s) and "ichq_app:a@" not in repr(s)
    with pytest.raises(ConfigError) as e:
        load_settings(basis(tmp_path, ICHQ_SESSION_SECRET=GEHEIM))
    assert GEHEIM not in str(e.value)


def test_leere_file_variable_gilt_als_nicht_gesetzt(tmp_path: Path) -> None:
    assert load_settings(basis(tmp_path, ICHQ_SECRET_KEY_FILE="")).secret_key.get_secret_value() == GEHEIM
