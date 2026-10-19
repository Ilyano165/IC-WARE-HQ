"""Windows-Launcher (ADR-017): Adresse prüfen, Instanz erkennen, Fehler verständlich — gegen den ECHTEN Server
(uvicorn-Prozess) und gegen echte Gegenproben (fremde Webseite, falsches Zertifikat, Weiterleitung, kein Dienst).

Den gebauten Installer (PyInstaller + Inno Setup) prüft der CI-Job „windows" auf einem Windows-Runner."""
from __future__ import annotations

import datetime
import http.server
import os
import socket
import ssl
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.test_core_e2e import server  # noqa: F401  (Fixture: uvicorn-Prozess)

# ICHQ_WINDOWS_DIR: veränderte Kopie für Mutationstests (scripts/mutation-check.sh)
sys.path.insert(0, str(Path(os.environ.get("ICHQ_WINDOWS_DIR", Path(__file__).resolve().parents[1] / "windows"))
                       / "launcher"))
import ichq_launcher as L


@pytest.fixture(autouse=True)
def _ohne_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gegenproben direkt (die Sandbox hat einen Proxy; unter Windows nutzt urllib den System-Proxy — gewollt)."""
    for v in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(v, raising=False)


@pytest.mark.parametrize("eingabe,erwartet", [
    ("hq.firma.de", "https://hq.firma.de"),
    ("  HTTPS://HQ.Firma.de/ ", "https://hq.firma.de"),
    ("https://hq.firma.de/app/", "https://hq.firma.de"),
    ("https://hq.firma.de:8443", "https://hq.firma.de:8443"),
    ("http://localhost:8000", "http://localhost:8000"),
])
def test_adresse_normalisiert(eingabe: str, erwartet: str) -> None:
    assert L.normalisiere(eingabe) == erwartet


@pytest.mark.parametrize("eingabe,teil", [
    ("", "eingeben"),
    ("http://hq.firma.de", "verschlüsselte"),                # Passwort nie unverschlüsselt übers Netz
    ("https://chef:geheim@hq.firma.de", "Zugangsdaten"),
    ("https://hq.firma.de/api/v1/x", "ohne Pfad"),
    ("https://hq.firma.de/?next=evil", "ohne Pfad"),
    ("ftp://hq.firma.de", "https://"),
    ("https://hq firma.de", "unerlaubte"),
    ("https://hq.firma.de:99999", "ungültig"),
])
def test_adresse_abgelehnt(eingabe: str, teil: str) -> None:
    with pytest.raises(L.Ungueltig, match=teil):
        L.normalisiere(eingabe)


def test_launcher_version_gleich_server_version() -> None:
    import ichq
    assert ichq.__version__ == L.VERSION


def test_echter_server_wird_erkannt(server: str) -> None:  # noqa: F811
    import ichq
    erg = L.pruefe(L.normalisiere(server))
    assert erg.oeffnen, erg
    assert erg.version == ichq.__version__


# ---- Gegenproben: echte Gegenstellen, die KEIN IC WARE HQ sind ----------------------------------------------------
def _starte(handler: type[http.server.BaseHTTPRequestHandler], ctx: ssl.SSLContext | None = None) -> Iterator[str]:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    if ctx:
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"{'https' if ctx else 'http'}://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


class _Webseite(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b"<html><body>Router-Login</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a: object) -> None:
        pass


class _Weiterleitung(_Webseite):
    """Leitet auf eine Seite um, die WIE IC WARE HQ antwortet — wer der Weiterleitung folgt, fiele darauf herein."""
    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(302)
            self.send_header("Location", "/nachgemacht")
            self.end_headers()
            return
        body = b'{"status":"ok","version":"9.9.9","application":{"status":"ok"}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _FalschesJson(_Webseite):
    def do_GET(self) -> None:
        body = b'{"status":"ok","version":"2.3.1"}'   # /health eines ANDEREN Dienstes
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.mark.parametrize("handler", [_Webseite, _Weiterleitung, _FalschesJson])
def test_fremde_webseite_ist_kein_hq(handler: type[http.server.BaseHTTPRequestHandler]) -> None:
    for basis in _starte(handler):
        erg = L.pruefe(basis)
        assert erg.befund is L.Befund.FREMD and not erg.oeffnen, erg


def _selbstsigniert(tmp: Path) -> ssl.SSLContext:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    jetzt = datetime.datetime.now(datetime.UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(jetzt)
            .not_valid_after(jetzt + datetime.timedelta(days=1)).sign(key, hashes.SHA256()))
    (tmp / "c.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp / "k.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                  serialization.NoEncryption()))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tmp / "c.pem", tmp / "k.pem")
    return ctx


def test_ungueltiges_zertifikat_wird_nie_geoeffnet(tmp_path: Path) -> None:
    for basis in _starte(_FalschesJson, _selbstsigniert(tmp_path)):
        erg = L.pruefe(basis)
        assert erg.befund is L.Befund.ZERTIFIKAT and not erg.oeffnen, erg
        assert "zertifikat" in erg.text.lower()


def test_kein_dienst_und_unbekannte_adresse() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        frei = s.getsockname()[1]
    assert L.pruefe(f"http://127.0.0.1:{frei}", timeout=3).befund is L.Befund.NICHT_ERREICHBAR
    assert L.pruefe("https://gibt-es-nicht.invalid", timeout=3).befund is L.Befund.DNS


# ---- Einstellungen ------------------------------------------------------------------------------------------------
def test_benutzer_vor_vorgabe_und_ungueltiges_ignoriert(tmp_path: Path) -> None:
    benutzer, vorgabe = tmp_path / "u" / "launcher.json", tmp_path / "server.json"
    assert L.adresse(benutzer, vorgabe) is None
    vorgabe.write_text('{"url": "hq.vorgabe.de"}', encoding="utf-8-sig")       # Inno Setup schreibt mit BOM
    assert L.adresse(benutzer, vorgabe) == "https://hq.vorgabe.de"
    L.speichere("hq.benutzer.de", datei=benutzer)
    assert L.adresse(benutzer, vorgabe) == "https://hq.benutzer.de"
    benutzer.write_text('{"url": "http://angreifer.de"}')                       # unverschlüsselt ⇒ nicht nutzen
    assert L.adresse(benutzer, vorgabe) == "https://hq.vorgabe.de"
    benutzer.write_text("kaputt{")
    assert L.adresse(benutzer, vorgabe) == "https://hq.vorgabe.de"


def test_update_hinweis_nur_bei_neuer_server_version(tmp_path: Path) -> None:
    datei = tmp_path / "launcher.json"
    erg = L.Ergebnis(L.Befund.OK, version="1.0.1")
    assert not L.neue_version(erg, datei)                    # erster Start: kein Hinweis
    L.speichere(version="1.0.0", datei=datei)
    assert L.neue_version(erg, datei)
    L.speichere(version="1.0.1", datei=datei)
    assert not L.neue_version(erg, datei)


def test_app_fenster_mit_edge_sonst_standardbrowser(tmp_path: Path) -> None:
    edge = tmp_path / "msedge.exe"
    assert L.browser_befehl("https://hq.firma.de", [edge]) is None
    edge.write_bytes(b"")
    assert L.browser_befehl("https://hq.firma.de", [edge]) == [str(edge), "--app=https://hq.firma.de/app/"]


def test_kommandozeile(server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
                       capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert L.main(["--version"]) == 0
    assert L.main(["--check", server]) == 0
    assert L.main(["--check", "http://hq.firma.de"]) == 2
    assert L.main(["--set-url", "hq.firma.de"]) == 0
    assert L.adresse(vorgabe=tmp_path / "keine.json") == "https://hq.firma.de"
    monkeypatch.setattr(L, "vorgabe_datei", lambda: tmp_path / "keine.json")
    assert L.main(["--adresse"]) == 0
    assert L.main(["--vergessen"]) == 0
    assert L.main(["--adresse"]) == 1
    assert L.adresse(vorgabe=tmp_path / "keine.json") is None
    assert L.main(["--unsinn"]) == 2
    capsys.readouterr()
