"""Öffentliche Erreichbarkeit (ADR-017): DNS-Abgleich und ACME-Fehlerdeutung aus deploy/lib/diagnose.sh — ohne Netz.

Den Live-Lauf (`deploy/hq diagnose` gegen den Stack, Gegenprobe mit gestopptem Caddy) macht deploy/smoke-test.sh."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DEPLOY = Path(os.environ.get("ICHQ_DEPLOY_DIR", REPO / "deploy"))
EIGENE = "10.0.0.5\n203.0.113.10\n2001:db8::10"


def _vergleich(aufgeloest: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-c", f'. "{DEPLOY}/lib/diagnose.sh"; dns_vergleich hq.example.de "$1" "$2"', "_",
                           aufgeloest, EIGENE], capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize("aufgeloest,ok,erwartet", [
    ("203.0.113.10", True, "A-Eintrag 203.0.113.10 zeigt auf diesen Server"),
    ("203.0.113.10\n2001:db8::10", True, "AAAA-Eintrag 2001:db8::10 zeigt auf diesen Server"),
    # Der Fall, der Let's Encrypt scheitern lässt, obwohl der A-Eintrag stimmt: veralteter AAAA-Eintrag
    ("203.0.113.10\n2001:db8::99", False, "AAAA-Eintrag 2001:db8::99 gehört nicht zu diesem Server"),
    ("198.51.100.7", False, "A-Eintrag 198.51.100.7 gehört nicht zu diesem Server (dieser Server: 203.0.113.10)"),
    ("", False, "A-Eintrag anlegen: hq.example.de → 203.0.113.10"),
])
def test_dns_jeder_eintrag_muss_auf_den_server_zeigen(aufgeloest: str, ok: bool, erwartet: str) -> None:
    r = _vergleich(aufgeloest)
    assert (r.returncode == 0) is ok, r.stdout
    assert erwartet in r.stdout, r.stdout


@pytest.mark.parametrize("zeile,erwartet", [
    ('"problem":{"type":"urn:ietf:params:acme:error:dns","detail":"NXDOMAIN"}', "keinen DNS-Eintrag"),
    ('"type":"urn:ietf:params:acme:error:connection","detail":"Timeout during connect"', "Port 80/443"),
    ('"type":"urn:ietf:params:acme:error:unauthorized"', "ANDEREN Server"),
    ('"type":"urn:ietf:params:acme:error:caa"', "CAA"),
    ('"type":"urn:ietf:params:acme:error:rateLimited"', "Limit"),
    ('{"level":"info","msg":"certificate obtained successfully"}', ""),
])
def test_acme_fehler_verstaendlich(zeile: str, erwartet: str) -> None:
    r = subprocess.run(["bash", "-c", f'. "{DEPLOY}/lib/diagnose.sh"; acme_deuten'], input=zeile + "\n",
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0
    assert (erwartet in r.stdout) if erwartet else r.stdout == "", r.stdout
