"""Fälligkeits-Scan als Job: idempotent, kein Parallellauf, Fehler je Firma isoliert, systemd-Units."""
from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.notifications import handlers
from ichq.notifications.jobs import LOCK_KEY, run_scan
from tests.auth_helpers import db
from tests.conftest import World
from tests.core_helpers import CoreWorld, ok

TAG = date(2026, 10, 8)
SYSTEMD = Path(__file__).resolve().parent.parent / "deploy" / "systemd"


@pytest.fixture
def cw(world: World, engines: Engines, settings: Settings) -> CoreWorld:
    cw = CoreWorld(world, engines, settings)
    for c, fremd in ((cw.client(cw.admin_a), cw.public_id(cw.leser)),
                     (cw.client(cw.admin_b), cw.public_id(cw.mitarbeiter_b))):
        ok(c.post("/api/v1/tasks", json={"title": "Alt", "due_date": "2026-01-01", "assignee": fremd}), 201)
        ok(c.post("/api/v1/tasks", json={"title": "Zukunft", "due_date": "2027-01-01", "assignee": fremd}), 201)
    return cw


def _anzahl(engines: Engines) -> int:
    return int(db(engines, "SELECT count(*) FROM notifications WHERE kind = 'task.overdue'")[0][0])


def test_idempotent_keine_doppelten_benachrichtigungen(cw: CoreWorld, engines: Engines) -> None:
    r1 = run_scan(engines, TAG)
    assert r1.ok and r1.tenants == 2 and r1.delivered == 2 and _anzahl(engines) == 2
    r2 = run_scan(engines, TAG)
    assert r2.ok and r2.delivered == 0 and _anzahl(engines) == 2
    # Fälligkeit verschoben und wieder überfällig → neue Fälligkeit, neue Benachrichtigung (anderer dedup_key)
    db(engines, "UPDATE tasks SET due_date = '2026-02-01' WHERE due_date = '2026-01-01'")
    assert run_scan(engines, TAG).delivered == 2


def test_kein_parallellauf(cw: CoreWorld, engines: Engines) -> None:
    with engines.platform.connect() as andere:
        assert andere.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar()
        r = run_scan(engines, TAG)
        assert r.skipped and r.delivered == 0 and _anzahl(engines) == 0
        andere.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
        andere.commit()
    assert run_scan(engines, TAG).delivered == 2


def test_fehler_einer_firma_stoppt_die_anderen_nicht(cw: CoreWorld, engines: Engines,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    echt = handlers.RULES["task.overdue"]

    def kaputt_in_a(session, heute):  # type: ignore[no-untyped-def]
        n = echt(session, heute)
        if session.info["tenant_id"] == cw.a:
            raise RuntimeError("Regel kaputt")
        return n
    monkeypatch.setitem(handlers.RULES, "task.overdue", kaputt_in_a)
    r = run_scan(engines, TAG)
    assert r.failed == [str(cw.a)] and r.tenants == 1 and not r.ok
    # A wurde zurückgerollt (nichts halb zugestellt), B ist zugestellt
    rows = db(engines, "SELECT tenant_id FROM notifications WHERE kind = 'task.overdue'")
    assert [x[0] for x in rows] == [cw.b]


def test_cli_einstiegspunkt(cw: CoreWorld, settings: Settings) -> None:
    import sys

    from tests.test_entrypoints import _umgebung
    r = subprocess.run([sys.executable, "-m", "ichq.cli", "notifications-scan", "--date", "2026-10-08"],
                       env=_umgebung(settings), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-500:]
    assert "firmen 2 · zugestellt 2 · fehlgeschlagen 0" in r.stdout
    assert "Alt" not in r.stdout + r.stderr                      # keine Inhalte im Log


def test_systemd_units() -> None:
    dienst = (SYSTEMD / "ichq-notifications-scan.service").read_text()
    timer = (SYSTEMD / "ichq-notifications-scan.timer").read_text()
    assert "Type=oneshot" in dienst and "ichq notifications-scan" in dienst and "Restart=" not in dienst
    assert "Persistent=true" in timer and "OnCalendar=" in timer and "Unit=ichq-notifications-scan.service" in timer
    if shutil.which("systemd-analyze"):
        r = subprocess.run(["systemd-analyze", "verify", str(SYSTEMD / "ichq-notifications-scan.timer"),
                            str(SYSTEMD / "ichq-notifications-scan.service")], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
