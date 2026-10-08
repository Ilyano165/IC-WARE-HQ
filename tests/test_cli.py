"""Kommandozeile gegen die echte Testdatenbank."""
from __future__ import annotations

import pytest

from ichq import cli
from ichq.core.config import Settings, get_settings


@pytest.fixture
def cli_env(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("database_url", "platform_database_url", "worker_database_url", "auth_database_url",
                 "secret_key", "session_secret"):
        monkeypatch.setenv(f"ICHQ_{name.upper()}", getattr(settings, name).get_secret_value())
    monkeypatch.setenv("ICHQ_STORAGE_PATH", str(settings.storage_path))
    monkeypatch.setenv("ICHQ_LOG_FORMAT", "console")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_cli_firma_anlegen_und_status(cli_env: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["check-config"]) == 0
    assert cli.main(["tenant-create", "--name", "Kunde", "--slug", "kunde-eins"]) == 0
    tid = capsys.readouterr().out.strip().splitlines()[-1].split()[0]
    assert cli.main(["tenant-show", "kunde-eins"]) == 0
    assert cli.main(["tenant-status", tid, "active", "--reason", "ok"]) == 0
    assert "active" in capsys.readouterr().out


def test_cli_meldet_fachfehler_ohne_traceback(cli_env: None, capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["tenant-create", "--name", "Kunde", "--slug", "kunde-zwei"])
    tid = capsys.readouterr().out.strip().splitlines()[-1].split()[0]
    assert cli.main(["tenant-status", tid, "paused", "--reason", "x"]) == 1
    err = capsys.readouterr().err
    assert "Fehler (conflict)" in err and "Traceback" not in err
    assert cli.main(["tenant-create", "--name", "X", "--slug", "admin"]) == 1


def test_cli_ungueltige_konfiguration(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    for k in list(__import__("os").environ):
        if k.startswith("ICHQ_"):
            monkeypatch.delenv(k)
    get_settings.cache_clear()
    assert cli.main(["check-config"]) == 2
    assert "ICHQ_SECRET_KEY" in capsys.readouterr().err
    get_settings.cache_clear()
