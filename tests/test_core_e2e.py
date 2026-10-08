"""Ende-zu-Ende: echter API-Server (uvicorn, eigener Prozess), echte Logins mit Cookie und Firmenwahl,
Worker und Fälligkeits-Scan als eigene CLI-Prozesse. Kein dependency_override, kein TestClient.

Ablauf (Steuerberater-Szenario): Beleg hochladen → Aufgabe „IBAN prüfen" für Steuerberaterin → Beleg freigeben →
Steuerberaterin stellt Rückfrage mit Erwähnung → Worker stellt zu → Chefin sieht Benachrichtigungen, macht aus der
Rückfrage eine Aufgabe, findet alles in der Suche, sieht den Verlauf, exportiert das Audit.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from ichq.core.config import Settings
from ichq.db.engine import Engines
from tests.auth_helpers import PASSWORT, join, make_user
from tests.conftest import World
from tests.core_helpers import ALLES, STEUERBERATER
from tests.test_entrypoints import _umgebung


def _freier_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def server(settings: Settings, tmp_path: Path) -> Iterator[str]:
    port = _freier_port()
    log = (tmp_path / "server.log").open("w")
    proc = subprocess.Popen([sys.executable, "-m", "ichq.cli", "serve", "--port", str(port), "--workers", "1"],
                            env=_umgebung(settings), stdout=log, stderr=subprocess.STDOUT)
    basis = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{basis}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if proc.poll() is not None:
                raise AssertionError((tmp_path / "server.log").read_text()[-2000:])
            time.sleep(0.1)
        else:
            raise AssertionError("Server nicht gestartet")
        yield basis
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        log.close()


def _anmelden(basis: str, email: str, tenant_id: Any) -> httpx.Client:
    c = httpx.Client(base_url=basis, timeout=10)
    r = c.post("/api/v1/auth/login", json={"login": email, "password": PASSWORT})
    assert r.status_code == 200 and r.json()["status"] == "ok", r.text
    r = c.post("/api/v1/auth/tenant", json={"tenant_id": str(tenant_id)})
    assert r.status_code == 200, r.text
    return c


def _cli(settings: Settings, *args: str) -> str:
    r = subprocess.run([sys.executable, "-m", "ichq.cli", *args], env=_umgebung(settings), capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    return r.stdout


def _j(r: httpx.Response, status: int = 200) -> Any:
    assert r.status_code == status, f"{r.request.method} {r.request.url.path}: {r.status_code} {r.text[:300]}"
    return r.json()


def test_steuerberater_rueckfrage_end_to_end(world: World, engines: Engines, settings: Settings,
                                             server: str) -> None:
    chefin = make_user(engines, settings, "chefin@alpha.test")
    stb = make_user(engines, settings, "kanzlei@stb.test")
    m_chefin, m_stb = join(engines, world.a.id, chefin), join(engines, world.a.id, stb)
    world.assign(world.a.id, m_chefin, world.role(world.a.id, "Geschäftsführung", ALLES))
    world.assign(world.a.id, m_stb, world.role(world.a.id, "Steuerberater", STEUERBERATER))
    fremd = make_user(engines, settings, "chef@beta.test")
    m_fremd = join(engines, world.b.id, fremd)
    world.assign(world.b.id, m_fremd, world.role(world.b.id, "Admin", ALLES))

    a = _anmelden(server, "chefin@alpha.test", world.a.id)
    s = _anmelden(server, "kanzlei@stb.test", world.a.id)
    b = _anmelden(server, "chef@beta.test", world.b.id)
    mitglieder = {m["display_name"]: m["id"] for m in _j(a.get("/api/v1/members"))["items"]}
    assert set(mitglieder) == {"Anna", "chefin", "kanzlei"}                # Firma B („chef") taucht nicht auf

    beleg = _j(a.post("/api/v1/documents", params={"filename": "Tankbeleg Shell.pdf"}, content=b"%PDF-1.7 e2e",
                      headers={"content-type": "application/pdf"}), 201)
    aufgabe = _j(a.post(f"/api/v1/objects/{beleg['id']}/tasks",
                        json={"title": "IBAN prüfen", "assignee": mitglieder["kanzlei"], "due_date": "2026-01-15"}),
                 201)
    assert s.get(f"/api/v1/documents/{beleg['id']}").status_code == 404          # noch nicht freigegeben
    _j(a.post(f"/api/v1/objects/{beleg['id']}/grants", json={"member": mitglieder["kanzlei"]}), 201)
    assert _j(s.get(f"/api/v1/tasks/{aufgabe['id']}"))["subject"]["id"] == beleg["id"]
    frage = _j(s.post(f"/api/v1/objects/{beleg['id']}/comments",
                      json={"body": "Zu welchem Fahrzeug gehört der Beleg?", "kind": "question",
                            "mentions": [mitglieder["chefin"]]}), 201)
    assert b.get(f"/api/v1/comments/{frage['id']}").status_code in (404, 405)
    assert b.patch(f"/api/v1/comments/{frage['id']}", json={"body": "x"}).status_code == 404
    assert b.get(f"/api/v1/objects/{beleg['id']}").status_code == 404

    assert "endgültig gescheitert 0" in _cli(settings, "worker", "--once")
    kinds = sorted(n["kind"] for n in _j(a.get("/api/v1/notifications"))["items"])
    assert kinds == ["comment.mention", "comment.question"]    # Prüfhinweis nur an andere mit files.update: keiner
    assert [n["kind"] for n in _j(s.get("/api/v1/notifications"))["items"]] == ["task.assigned"]
    assert _j(b.get("/api/v1/notifications"))["items"] == []

    neu = _j(a.post(f"/api/v1/comments/{frage['id']}/tasks",
                    json={"title": "Fahrzeug zum Beleg nennen", "assignee": mitglieder["chefin"]}), 201)
    assert neu["description"] == "Zu welchem Fahrzeug gehört der Beleg?"
    treffer = _j(a.get("/api/v1/search", params={"q": "tankbel"}))["groups"]["documents"]["items"]
    assert [t["id"] for t in treffer] == [beleg["id"]]
    assert _j(b.get("/api/v1/search", params={"q": "tankbel"}))["groups"]["documents"]["items"] == []
    verlauf = [v["verb"] for v in _j(a.get(f"/api/v1/objects/{beleg['id']}/activities?order=asc"))["items"]]
    assert verlauf == ["document.uploaded", "task.created", "object.shared", "comment.question_asked",
                       "task.created"]

    assert s.get("/api/v1/audit/export").status_code == 403
    csv = a.get("/api/v1/audit/export")
    assert csv.status_code == 200 and "document.uploaded" in csv.text and "Fahrzeug" not in csv.text

    assert "zugestellt 1" in _cli(settings, "notifications-scan", "--date", "2026-10-08")
    assert "task.overdue" in [n["kind"] for n in _j(s.get("/api/v1/notifications"))["items"]]
    for c in (a, s, b):
        c.close()
