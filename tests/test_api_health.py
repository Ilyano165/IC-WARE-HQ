"""/health und /readiness: echte Prüfungen, keine Details nach außen."""
from __future__ import annotations

from pathlib import Path

from ichq.core.config import Settings
from ichq.db.engine import Engines, make_engine
from ichq.storage.local import LocalStorage
from tests.api_helpers import make_client


class KaputterSpeicher(LocalStorage):
    def check(self) -> None:
        raise OSError("/geheimer/pfad nicht beschreibbar")


def test_health_ok(settings: Settings, engines: Engines) -> None:
    client, _ = make_client(settings, engines)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["application"]["status"] == "ok"
    assert body["checks"]["database"]["status"] == "ok" and body["checks"]["storage"]["status"] == "ok"


def test_readiness_ok(settings: Settings, engines: Engines) -> None:
    client, _ = make_client(settings, engines)
    r = client.get("/readiness")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert r.json()["checks"]["migrations"]["status"] == "ok"


def test_speicher_kaputt(settings: Settings, engines: Engines, tmp_path: Path) -> None:
    client, _ = make_client(settings, engines, storage=KaputterSpeicher(tmp_path))
    r = client.get("/readiness")
    speicher = r.json()["checks"]["storage"]
    assert r.status_code == 503 and speicher["status"] == "fail" and speicher["reason"] == "unavailable"
    h = client.get("/health")
    assert h.status_code == 200 and h.json()["status"] == "degraded"
    assert "geheimer" not in r.text and "geheimer" not in h.text


def test_datenbank_nicht_erreichbar(settings: Settings, engines: Engines) -> None:
    tot = make_engine("postgresql://ichq_app:falsch@127.0.0.1:1/nirgends", "tot")
    kaputt = Engines(app=tot, platform=engines.platform, worker=engines.worker, auth=engines.auth)
    client, _ = make_client(settings, kaputt)
    r = client.get("/readiness")
    assert r.status_code == 503 and r.json()["checks"]["database"]["status"] == "fail"
    assert "127.0.0.1" not in r.text and "falsch" not in r.text
    assert client.get("/health").json()["status"] == "degraded"


def test_migrationsstand_erkannt(settings: Settings, engines: Engines, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ichq.health import checks
    checks.expected_head.cache_clear()
    monkeypatch.setattr(checks, "expected_head", lambda: "9999_zukunft")
    client, _ = make_client(settings, engines)
    r = client.get("/readiness")
    assert r.status_code == 503 and r.json()["checks"]["migrations"]["reason"] == "not_at_head"


def test_methoden(settings: Settings, engines: Engines) -> None:
    client, _ = make_client(settings, engines)
    assert client.post("/health").status_code == 405
    assert client.head("/health").status_code == 200 and client.head("/readiness").status_code == 200
