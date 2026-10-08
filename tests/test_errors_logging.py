"""Fehlerformat und Logging: keine Interna nach außen, keine Geheimnisse ins Log."""
from __future__ import annotations

import json
import logging

import pytest

from ichq.core.config import Settings
from ichq.core.logging import JsonFormatter, redact_text, redact_value, request_id_var
from ichq.db.engine import Engines
from tests.api_helpers import make_client


def _logs(out: str) -> list[dict]:  # type: ignore[type-arg]
    return [json.loads(z) for z in out.splitlines() if z.startswith("{")]


def test_unbehandelter_fehler(settings: Settings, engines: Engines, capsys: pytest.CaptureFixture[str]) -> None:
    client, _ = make_client(settings, engines)
    r = client.get("/test/boom")
    assert r.status_code == 500 and r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["code"] == "internal_error" and body["request_id"] == r.headers["x-request-id"]
    assert "geheimer" not in r.text and "Traceback" not in r.text and "hunter2" not in r.text
    logs = _logs(capsys.readouterr().out)
    fehler = [e for e in logs if e["msg"] == "unbehandelter_fehler"]
    assert fehler and fehler[0]["request_id"] == body["request_id"]
    assert "Traceback" in fehler[0]["exc"] and "hunter2" not in fehler[0]["exc"]


def test_fachfehler(settings: Settings, engines: Engines) -> None:
    client, _ = make_client(settings, engines)
    r = client.get("/test/conflict")
    assert r.status_code == 409 and r.json()["code"] == "conflict" and r.json()["detail"] == "Slug ist schon vergeben"


def test_404_und_405(settings: Settings, engines: Engines) -> None:
    client, _ = make_client(settings, engines)
    r = client.get("/api/v1/gibtsnicht")
    assert r.status_code == 404 and r.json()["code"] == "not_found" and r.json()["request_id"]
    assert client.delete("/api/v1/me").json()["code"] == "method_not_allowed"


def test_validierung_ohne_eingabewerte(settings: Settings, engines: Engines) -> None:
    client, _ = make_client(settings, engines)
    r = client.post("/test/echo", json={"password": "streng-geheim-123"})
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert "streng-geheim-123" not in r.text and r.json()["errors"]


def test_request_id(settings: Settings, engines: Engines) -> None:
    client, _ = make_client(settings, engines)
    eigene = client.get("/health", headers={"X-Request-ID": "eigene-id-12345"})
    assert eigene.headers["x-request-id"] == "eigene-id-12345"
    boese = client.get("/health", headers={"X-Request-ID": "<script>alert(1)</script>"})
    assert "<script>" not in boese.headers["x-request-id"] and len(boese.headers["x-request-id"]) == 32


def test_sicherheits_header(settings: Settings, engines: Engines) -> None:
    client, _ = make_client(settings, engines)
    h = client.get("/health").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert h["content-security-policy"].startswith("default-src 'none'") and h["cache-control"] == "no-store"


def test_docs_standardmaessig_aus(settings: Settings, engines: Engines) -> None:
    client, _ = make_client(settings, engines)
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404


def test_zugriffslog_ohne_token_im_pfad(settings: Settings, engines: Engines,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    client, _ = make_client(settings, engines)
    token = "AbCdEf0123456789AbCdEf0123456789"
    assert client.get(f"/onboard/{token}?password=x").status_code == 200
    out = capsys.readouterr().out
    assert token not in out and "password=x" not in out
    zugriffe = [e for e in _logs(out) if e["msg"] == "request"]
    assert zugriffe and zugriffe[-1]["route"] == "/onboard/{token}" and zugriffe[-1]["status"] == 200


@pytest.mark.parametrize("roh,verboten", [
    ("Authorization: Bearer eyJhbGciOi.abc.def", "eyJhbGciOi"),
    ("verbinde postgresql+psycopg://ichq_app:SuperGeheim@db/ichq", "SuperGeheim"),
    ("GET /reset?token=abcdef123456&x=1", "abcdef123456"),
    ("link https://app/onboard/Zx9_kL3mN8pQ2rS5tU7vW1yA4bC6dE", "Zx9_kL3mN8pQ2rS5tU7vW1yA4bC6dE"),
])
def test_schwaerzung_von_mustern(roh: str, verboten: str) -> None:
    assert verboten not in redact_text(roh)


def test_schwaerzung_von_schluesseln() -> None:
    daten = redact_value("ctx", {"password": "x", "session_token": "y", "nested": {"api_key": "z"}, "name": "ok"})
    assert daten == {"password": "[REDACTED]", "session_token": "[REDACTED]",
                     "nested": {"api_key": "[REDACTED]"}, "name": "ok"}


def test_json_formatter_mit_korrelations_id() -> None:
    token = request_id_var.set("rid-1234567890")
    try:
        rec = logging.LogRecord("t", logging.INFO, "", 0, "hallo %s", ("welt",), None)
        rec.password = "geheim"
        aus = json.loads(JsonFormatter().format(rec))
    finally:
        request_id_var.reset(token)
    assert aus["msg"] == "hallo welt" and aus["request_id"] == "rid-1234567890" and aus["password"] == "[REDACTED]"
