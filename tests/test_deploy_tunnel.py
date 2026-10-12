"""Tunnelbetrieb über Cloudflare (ADR-018): Compose, Caddyfile.tunnel, Eingabeprüfung, Domainwechsel, Diagnose-Deutung.

Ohne Docker. Live geprüft werden die Client-IP-Kette (deploy/tunnel-proxy-test.sh, CI-Job „betrieb") und
Einrichtung/Domainwechsel im Tunnelbetrieb (von Hand, docs/windows-server.md, Abschnitt „Geprüft")."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
DEPLOY = Path(os.environ.get("ICHQ_DEPLOY_DIR", REPO / "deploy"))
ECHT_AUSSEHEND = "eyJhIjoiMTIzNDU2Nzg5MGFiY2RlZjEyMzQ1Njc4OTBhYmNkZWYiLCJ0IjoiYWJjZGVmMDEtMjM0NS02Nzg5LWFiY2QtZWYwMTIz" \
                 "NDU2Nzg5IiwicyI6Ik1qQXlOaTB4TUMweE1GUXhNam93TURvd01Gb3RaWGhoYlhCc1pRPT0ifQ=="


def _compose() -> dict[str, Any]:
    return dict(yaml.safe_load((DEPLOY / "docker-compose.yml").read_text()))


def _lib(skript: str, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    kopf = ('set -euo pipefail; fehler() { echo "Fehler: $*" >&2; exit 1; }; info() { echo "$*"; }; '
            f'. "{DEPLOY}/lib/tunnel.sh"; ')
    return subprocess.run(["bash", "-c", kopf + skript, "_", *args], capture_output=True, text=True, timeout=30,
                          env={**os.environ, **env})


def test_cloudflared_nur_im_tunnelprofil_und_nur_neben_caddy() -> None:
    d = _compose()["services"]["cloudflared"]
    assert d["profiles"] == ["tunnel"]                                   # Direktbetrieb startet ihn nie
    assert re.fullmatch(r"cloudflare/cloudflared:\d{4}\.\d+\.\d+", d["image"])   # feste Version, kein „latest"
    assert "--no-autoupdate" in d["command"] and "--token-file" in d["command"]   # Token nie als Argument/Env
    assert d["secrets"] == ["cloudflare_tunnel_token"] and "environment" not in d
    assert list(d["networks"]) == ["tunnel"]                              # sieht weder App noch Datenbank
    assert "ports" not in d and d["restart"] == "unless-stopped" and "healthcheck" in d
    netz = _compose()["networks"]["tunnel"]["ipam"]["config"][0]["subnet"]
    assert netz == "172.31.250.0/28"
    assert set(_compose()["services"]["caddy"]["networks"]) == {"default", "tunnel"}


def test_caddy_vertraut_nur_cloudflared() -> None:
    ip = _compose()["services"]["cloudflared"]["networks"]["tunnel"]["ipv4_address"]
    cfg = (DEPLOY / "Caddyfile.tunnel").read_text()
    assert re.findall(r"trusted_proxies static (\S+)", cfg) == [f"{ip}/32"]   # genau eine Adresse, kein Bereich
    assert "client_ip_headers Cf-Connecting-Ip" in cfg
    assert "header_up X-Forwarded-For {client_ip}" in cfg                     # nur die geprüfte Adresse an die App
    assert "auto_https off" in cfg and "http://{$ICHQ_DOMAIN}" in cfg
    assert 'request>headers>Cookie delete' in cfg and '"\\?.*$" "?[REDACTED]"' in cfg


def test_caddy_ports_im_tunnelbetrieb_nur_lokal() -> None:
    ports = _compose()["services"]["caddy"]["ports"]
    assert ports and all(p.startswith("${ICHQ_BIND:-0.0.0.0}:") for p in ports)
    assert "./${ICHQ_CADDYFILE:-Caddyfile}:/etc/caddy/Caddyfile:ro" in _compose()["services"]["caddy"]["volumes"]
    fix = (DEPLOY / "fix-secret-permissions.sh").read_text()
    assert "chown 65532:65532 secrets/cloudflare_tunnel_token" in fix         # Benutzer im cloudflared-Image


def test_modus_setzen_schreibt_alle_drei_werte(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("ICHQ_DOMAIN=hq.firma.de\nANDERES=bleibt\n")
    assert _lib('ENVFILE="$1"; modus_setzen tunnel', str(env)).returncode == 0
    t = env.read_text()
    assert "HQ_ZUGANG=tunnel" in t and "ICHQ_CADDYFILE=Caddyfile.tunnel" in t and "ICHQ_BIND=127.0.0.1" in t
    assert "ANDERES=bleibt" in t and oct(env.stat().st_mode & 0o777) == "0o600"
    assert _lib('ENVFILE="$1"; modus_setzen direkt', str(env)).returncode == 0
    t = env.read_text()
    assert "HQ_ZUGANG=direkt" in t and "ICHQ_CADDYFILE=Caddyfile\n" in t and "ICHQ_BIND=0.0.0.0" in t
    assert t.count("ICHQ_BIND=") == 1


@pytest.mark.parametrize("domain,ok", [
    ("hq.firma.de", True), ("localhost", True), ("a-b.c.example.com", True),
    ("https://hq.firma.de", False), ("hq.firma.de/app", False), ("hq firma.de", False),
    ("hq.firma.de}{$X}", False), ("hq.firma.de\nimport x", False), ("-hq.firma.de", False), ("HQ.FIRMA.DE", False),
])
def test_domain_eingabe_streng(domain: str, ok: bool) -> None:
    assert (_lib('domain_gueltig "$1"', domain).returncode == 0) is ok


def test_domainwechsel_lehnt_ungueltiges_ab_ohne_aenderung(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("ICHQ_DOMAIN=hq.alt.de\n")
    r = _lib('ENVFILE="$1"; env_wert() { sed -n "s/^$1=//p" "$ENVFILE"; }; compose() { echo COMPOSE; }; '
             'domain_aendern "$2"', str(env), "neu.de}evil{")
    assert r.returncode != 0 and "ungültige Domain" in r.stderr and "COMPOSE" not in r.stdout
    assert env.read_text() == "ICHQ_DOMAIN=hq.alt.de\n"


def test_domainwechsel_im_tunnelbetrieb(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("ICHQ_DOMAIN=hq.alt.de\nHQ_ZUGANG=tunnel\n")
    r = _lib('ENVFILE="$1"; env_wert() { sed -n "s/^$1=//p" "$ENVFILE" | tail -1; }; compose() { echo "COMPOSE $*"; }; '
             'warten() { :; }; domain_aendern "$2"', str(env), "HQ.Neu.de")
    assert r.returncode == 0, r.stderr
    assert "Hostname:  hq.neu.de" in r.stdout and "HTTP   caddy:80" in r.stdout      # Anleitung für Cloudflare
    assert "COMPOSE up -d" in r.stdout and "ICHQ_DOMAIN=hq.neu.de" in env.read_text()


@pytest.mark.parametrize("token,ok", [
    (ECHT_AUSSEHEND, True), ("", False), ("zu-kurz", False), (ECHT_AUSSEHEND + " --x", False),
    (ECHT_AUSSEHEND + "\nevil", False), ("cloudflared service install " + ECHT_AUSSEHEND, False),
])
def test_token_eingabe_streng(token: str, ok: bool) -> None:
    assert (_lib('token_gueltig "$1"', token).returncode == 0) is ok


def test_installer_lehnt_ungueltiges_token_vor_jeder_aenderung_ab(tmp_path: Path) -> None:
    r = subprocess.run(["bash", str(DEPLOY / "install.sh"), "--domain", "hq.firma.de", "--email", "a@firma.de",
                        "--tunnel"], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "HQ_TUNNEL_TOKEN": "kein token; rm -rf /"})
    assert r.returncode != 0 and "kein Cloudflare-Tunnel-Token" in r.stderr, r.stderr


@pytest.mark.parametrize("log,erwartet", [
    ("ERR Provided Tunnel token is not valid.", "Token ab"),
    ('ERR Unable to establish connection error="failed to dial to edge with quic: timeout"', "Keine Verbindung"),
    ('ERR Unable to reach the origin service. dial tcp: lookup caddy on 127.0.0.11:53: no such host', "caddy:80"),
    ("INF Registered tunnel connection connIndex=0 location=fra08 protocol=quic", "OK: Tunnel"),
])
def test_cloudflared_log_verstaendlich(log: str, erwartet: str) -> None:
    r = subprocess.run(["bash", "-c", f'. "{DEPLOY}/lib/tunnel.sh"; cloudflared_deuten'], input=log + "\n",
                       capture_output=True, text=True, timeout=30)
    assert erwartet in r.stdout, r.stdout


@pytest.mark.parametrize("code,stufe,teil", [
    ("200", "OK", "öffentlich erreichbar"), ("530", "FEHLER", "nicht verbunden"),
    ("502", "FEHLER", "caddy:80"), ("000", "FEHLER", "nicht erreichbar"), ("404", "FEHLER", "Hostname"),
])
def test_oeffentliche_antwort_verstaendlich(code: str, stufe: str, teil: str) -> None:
    r = _lib('tunnel_antwort_deuten "$1" hq.firma.de', code)
    s, text = r.stdout.strip().split("|", 1)
    assert s == stufe and teil in text, r.stdout


def test_windows_server_prueft_wie_linux() -> None:
    """Die Windows-Einrichtung (ADR-018) prüft Domain und Token mit DENSELBEN Mustern wie deploy/lib/tunnel.sh —
    sonst nähme Windows etwas an, das Linux später ablehnt (oder umgekehrt)."""
    bash = (DEPLOY / "lib/tunnel.sh").read_text()
    ps = (REPO / "windows/server/IchqServer.psm1").read_text(encoding="utf-8-sig")
    for name_bash, name_ps in (("domain_gueltig", "Test-IchqDomain"), ("token_gueltig", "Test-IchqToken")):
        m_bash = re.search(name_bash + r'\(\) \{.*?=~ (\^\S+\$)', bash, re.S)
        m_ps = re.search(name_ps + r" \{.*?-cmatch '(\^[^']+\$)'", ps, re.S)
        assert m_bash and m_ps, name_bash
        assert m_bash.group(1) == m_ps.group(1), (name_bash, m_bash.group(1), m_ps.group(1))
    assert "UbuntuSha256 = 'bb415d824822c4b878125729af451a5d18fb13d1cf5cbed9a7393ad64ac6039e'" in ps


# ---- Schnellstart ohne Cloudflare-Konto (ADR-019) --------------------------------------------------------------------
def test_schnellstart_dienst_ohne_token_mit_gleicher_fester_adresse() -> None:
    d = _compose()["services"]["cloudflared-schnell"]
    konto = _compose()["services"]["cloudflared"]
    assert d["profiles"] == ["schnell"] and d["image"] == konto["image"]
    assert d["command"][-2:] == ["--url", "http://caddy:80"] and "--no-autoupdate" in d["command"]
    assert "secrets" not in d and "environment" not in d                      # kein Konto, kein Token
    assert d["networks"] == konto["networks"]                                   # dieselbe vertrauenswürdige Adresse
    assert "ports" not in d and d["restart"] == "unless-stopped" and "healthcheck" in d


KASTEN = "INF |  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |\n"


@pytest.mark.parametrize("log,erwartet", [
    (KASTEN + "INF |  https://able-river-tiger-moon.trycloudflare.com                    |",
     "able-river-tiger-moon.trycloudflare.com"),
    (KASTEN + "INF |  https://alt-eins.trycloudflare.com  |\n" + KASTEN + "INF |  https://neu-zwei.trycloudflare.com  |",
     "neu-zwei.trycloudflare.com"),
    # im Live-Test gefunden: die Fehlermeldung nennt die API-Adresse — das ist KEINE Tunnel-Adresse
    ('failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel": dial tcp: no such host', ""),
    ("INF |  https://api.trycloudflare.com  |", ""),
    ("INF |  https://evil.trycloudflare.com.angreifer.de  |", ""),
    ("INF |  https://x}{$Y-z.trycloudflare.com  |", ""),                       # nie Sonderzeichen ins Caddyfile
    ("INF |  https://UPPER-case.trycloudflare.com  |", ""), ("keine adresse", ""),
    ("https://frei-stehend.trycloudflare.com", ""),                            # nur aus dem Kasten
])
def test_schnellstart_adresse_aus_dem_log(log: str, erwartet: str) -> None:
    r = subprocess.run(["bash", "-c", f'. "{DEPLOY}/lib/tunnel.sh"; schnell_url_aus_log'], input=log + "\n",
                       capture_output=True, text=True, timeout=30)
    assert r.stdout.strip() == erwartet, r.stdout


def _schnell(tmp_path: Path, env: str, log: str) -> tuple[subprocess.CompletedProcess[str], str]:
    datei = tmp_path / ".env"
    datei.write_text(env)
    r = _lib('ENVFILE="$1"; env_wert() { sed -n "s/^$1=//p" "$ENVFILE" | tail -1; }; '
             'compose() { if [ "$1" = logs ]; then printf "%s\\n" "$LOG"; else echo "COMPOSE $*"; fi; }; '
             'if adresse_aktualisieren; then echo rc=0; else echo rc=1; fi', str(datei), LOG=log)
    return r, datei.read_text()


def test_schnellstart_neue_adresse_wird_uebernommen_ohne_tunnel_neustart(tmp_path: Path) -> None:
    r, env = _schnell(tmp_path, "HQ_ZUGANG=schnell\nICHQ_DOMAIN=alt-eins.trycloudflare.com\n",
                      KASTEN + "INF |  https://neu-zwei.trycloudflare.com  |")
    assert "rc=0" in r.stdout and "ICHQ_DOMAIN=neu-zwei.trycloudflare.com" in env, (r.stdout, r.stderr)
    aufrufe = [z for z in r.stdout.splitlines() if z.startswith("COMPOSE")]
    assert aufrufe and all("--no-deps" in z and "cloudflared" not in z for z in aufrufe), aufrufe
    assert "app" in aufrufe[0] and "caddy" in aufrufe[0]                    # Origin/Mail-Links + Proxy-Hostname


def test_schnellstart_ohne_adresse_aendert_nichts(tmp_path: Path) -> None:
    r, env = _schnell(tmp_path, "HQ_ZUGANG=schnell\nICHQ_DOMAIN=localhost\n", "INF Requesting new quick Tunnel")
    assert "rc=1" in r.stdout and "COMPOSE" not in r.stdout and "ICHQ_DOMAIN=localhost" in env


def test_ausserhalb_des_schnellstarts_wirkungslos(tmp_path: Path) -> None:
    r, env = _schnell(tmp_path, "HQ_ZUGANG=tunnel\nICHQ_DOMAIN=hq.firma.de\n", KASTEN + "INF |  https://x-y.trycloudflare.com |")
    assert "rc=0" in r.stdout and "COMPOSE" not in r.stdout and "ICHQ_DOMAIN=hq.firma.de" in env


def test_schnellstart_domain_nicht_waehlbar(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("HQ_ZUGANG=schnell\nICHQ_DOMAIN=a-b.trycloudflare.com\n")
    r = _lib('ENVFILE="$1"; env_wert() { sed -n "s/^$1=//p" "$ENVFILE" | tail -1; }; compose() { echo COMPOSE; }; '
             'domain_aendern hq.firma.de', str(env))
    assert r.returncode != 0 and "zufällig" in r.stderr and "--tunnel" in r.stderr and "COMPOSE" not in r.stdout


def test_modus_schnell_wie_tunnel_nur_lokal(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("")
    assert _lib('ENVFILE="$1"; modus_setzen schnell', str(env)).returncode == 0
    t = env.read_text()
    assert "HQ_ZUGANG=schnell" in t and "ICHQ_CADDYFILE=Caddyfile.tunnel" in t and "ICHQ_BIND=127.0.0.1" in t


def test_installer_schnellstart_braucht_keine_domain() -> None:
    hilfe = subprocess.run(["bash", str(DEPLOY / "install.sh"), "--help"], capture_output=True, text=True, timeout=30)
    assert "--schnell" in hilfe.stdout
    r = subprocess.run(["bash", str(DEPLOY / "install.sh"), "--email", "a@firma.de", "--schnell", "--firewall"],
                       capture_output=True, text=True, timeout=60, env={**os.environ, "HOME": "/nonexistent"})
    assert "--firewall ist im Tunnelbetrieb unnötig" in r.stderr or "als root" in r.stderr, r.stderr
    assert "Optionen:" not in r.stdout                                          # keine Hilfe ⇒ Domain nicht verlangt
