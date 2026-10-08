"""M2-Restpunkt: Aufräum-Job löscht nur Altes, nie auth_events; Sperre gegen Parallellauf; CLI; systemd-Units."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from ichq.auth.cleanup import run_cleanup
from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.locks import AUTH_CLEANUP
from tests.auth_helpers import db, make_user

SYSTEMD = Path(__file__).resolve().parent.parent / "deploy" / "systemd"


def _bytes() -> bytes:
    return os.urandom(32)


@pytest.fixture
def bestand(engines: Engines, settings: Settings) -> dict[str, uuid.UUID]:
    u = make_user(engines, settings, "aufraeumen@firma.test")
    ids: dict[str, uuid.UUID] = {}
    for name, alter, erfolg in (("versuch_alt", 40, False), ("versuch_neu", 1, False)):
        ids[name] = uuid.uuid4()
        db(engines, "INSERT INTO login_attempts(id, kind, subject_hash, ip, success, occurred_at) "
                    "VALUES (%s, 'login', %s, '1.2.3.4', %s, now() - make_interval(days => %s))",
           (ids[name], _bytes(), erfolg, alter))
    sitzungen = {  # name: (expires_at-Versatz in Tagen, revoked vor Tagen oder None)
        "sitzung_widerrufen_alt": (5, 40), "sitzung_widerrufen_neu": (5, 1), "sitzung_aktiv": (1, None),
        "sitzung_abgelaufen_alt": (-40, None), "sitzung_abgelaufen_neu": (-2, None)}
    for name, (ablauf, widerruf) in sitzungen.items():
        ids[name] = uuid.uuid4()
        db(engines, "INSERT INTO auth_sessions(id, token_hash, user_id, stage, expires_at, revoked_at) "
                    "VALUES (%s, %s, %s, 'full', now() + make_interval(days => %s), "
                    "CASE WHEN %s::int IS NULL THEN NULL ELSE now() - make_interval(days => %s::int) END)",
           (ids[name], _bytes(), u, ablauf, widerruf, widerruf))
    tokens = {  # name: (expires Versatz, used vor Tagen oder None)
        "reset_benutzt_alt": (-39, 40), "reset_benutzt_neu": (1, 1), "reset_offen": (1, None),
        "reset_abgelaufen_alt": (-40, None), "reset_abgelaufen_neu": (-1, None)}
    for name, (ablauf, benutzt) in tokens.items():
        ids[name] = uuid.uuid4()
        db(engines, "INSERT INTO password_reset_tokens(id, token_hash, user_id, created_at, expires_at, used_at) "
                    "VALUES (%s, %s, %s, now() - interval '60 days', now() + make_interval(days => %s), "
                    "CASE WHEN %s::int IS NULL THEN NULL ELSE now() - make_interval(days => %s::int) END)",
           (ids[name], _bytes(), u, ablauf, benutzt, benutzt))
    for name, benutzt in (("code_benutzt_alt", 40), ("code_benutzt_neu", 1), ("code_offen", None)):
        ids[name] = uuid.uuid4()
        db(engines, "INSERT INTO recovery_codes(id, user_id, code_hash, used_at) VALUES (%s, %s, %s, "
                    "CASE WHEN %s::int IS NULL THEN NULL ELSE now() - make_interval(days => %s::int) END)",
           (ids[name], u, _bytes(), benutzt, benutzt))
    return ids


def _da(engines: Engines, ids: dict[str, uuid.UUID]) -> set[str]:
    vorhanden = set()
    for tab in ("login_attempts", "auth_sessions", "password_reset_tokens", "recovery_codes"):
        vorhanden |= {r[0] for r in db(engines, f"SELECT id FROM {tab}")}
    return {n for n, i in ids.items() if i in vorhanden}


def test_loescht_nur_altes(bestand: dict[str, uuid.UUID], engines: Engines) -> None:
    events_vorher = db(engines, "SELECT count(*) FROM auth_events")[0][0]
    r = run_cleanup(engines, 30)
    assert not r.skipped
    assert _da(engines, bestand) == {"versuch_neu", "sitzung_widerrufen_neu", "sitzung_aktiv",
                                     "sitzung_abgelaufen_neu", "reset_benutzt_neu", "reset_offen",
                                     "reset_abgelaufen_neu", "code_benutzt_neu", "code_offen"}
    assert r.deleted == {"login_attempts": 1, "auth_sessions": 2, "password_reset_tokens": 2, "recovery_codes": 1}
    assert db(engines, "SELECT count(*) FROM auth_events")[0][0] == events_vorher > 0   # nie gelöscht
    assert run_cleanup(engines, 30).deleted == dict.fromkeys(r.deleted, 0)               # idempotent


def test_frist_ist_einstellbar_und_begrenzt(bestand: dict[str, uuid.UUID], engines: Engines) -> None:
    run_cleanup(engines, 3)        # Grenzfall 2 Tage wäre sekundengenau — bewusst Abstand
    assert "sitzung_abgelaufen_neu" in _da(engines, bestand) and "versuch_neu" in _da(engines, bestand)
    with pytest.raises(ValueError):
        run_cleanup(engines, 0)


def test_kein_parallellauf(bestand: dict[str, uuid.UUID], engines: Engines) -> None:
    with engines.auth.connect() as andere:
        assert andere.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": AUTH_CLEANUP}).scalar()
        assert run_cleanup(engines, 30).skipped
        assert "versuch_alt" in _da(engines, bestand)
        andere.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": AUTH_CLEANUP})
        andere.commit()


def test_cli(bestand: dict[str, uuid.UUID], engines: Engines, settings: Settings) -> None:
    from tests.test_entrypoints import _umgebung
    r = subprocess.run([sys.executable, "-m", "ichq.cli", "auth-cleanup", "--days", "30"], env=_umgebung(settings),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-500:]
    assert "login_attempts 1 · auth_sessions 2 · password_reset_tokens 2 · recovery_codes 1" in r.stdout


def test_systemd_units() -> None:
    dienst = (SYSTEMD / "ichq-auth-cleanup.service").read_text()
    assert "Type=oneshot" in dienst and "ichq auth-cleanup" in dienst
    assert "Persistent=true" in (SYSTEMD / "ichq-auth-cleanup.timer").read_text()
    if shutil.which("systemd-analyze"):
        r = subprocess.run(["systemd-analyze", "verify", str(SYSTEMD / "ichq-auth-cleanup.timer"),
                            str(SYSTEMD / "ichq-auth-cleanup.service")], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
