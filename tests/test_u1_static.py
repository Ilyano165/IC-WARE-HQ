"""U1 — Auslieferung der Oberfläche ohne Browser: Weiterleitungen, Sicherheits-Header, Pfad-Ausbruch, Dateitypen,
und die Code-Regeln aus ADR-013 (keine HTML-Einfüge-APIs, keine Inline-Skripte/-Styles, keine externen Quellen)."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ichq.api.ui import CSP, WEB
from ichq.core.config import Settings
from ichq.db.engine import Engines
from tests.api_helpers import make_client

JS = sorted((WEB / "js").rglob("*.js"))
VERBOTEN = re.compile(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\s*\(|new Function|"
                      r"\.on[a-z]+\s*=|setAttribute\(\s*[\"']on")


@pytest.fixture
def c(settings: Settings, engines: Engines):  # type: ignore[no-untyped-def]
    client, _ = make_client(settings, engines)
    return client


def test_weiterleitungen(c) -> None:  # type: ignore[no-untyped-def]
    for pfad, ziel in (("/", "/app/"), ("/app", "/app/"), ("/invite", "/app/?v=einladung"),
                       ("/reset", "/app/?v=passwort-neu")):
        r = c.get(pfad, follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == ziel, pfad


def test_index_mit_sicherheits_headern(c) -> None:  # type: ignore[no-untyped-def]
    r = c.get("/app/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"] == CSP
    assert "script-src 'self';" in CSP and "unsafe-inline" not in CSP and "frame-ancestors 'none'" in CSP
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer" and r.headers["cache-control"] == "no-store"
    assert '<script type="module" src="js/app.js">' in r.text
    js = c.get("/app/js/app.js")
    assert js.headers["content-type"].startswith("text/javascript") and js.headers["cache-control"] == "no-cache"
    assert c.get("/app/fonts/inter-latin-400-normal.woff2").headers["content-type"] == "font/woff2"


@pytest.mark.parametrize("pfad", ["/app/../pyproject.toml", "/app/%2e%2e/api/ui.py", "/app/js/../../api/ui.py",
                                  "/app/..%2f..%2fapi%2fui.py", "/app/js/%2e%2e/%2e%2e/models.py", "/app/nichtda.js",
                                  "/app/fonts/", "/app//etc/passwd", "/app/js/app.js%00.css", "/app/../../etc/passwd",
                                  "/app/.hidden", "/app/js/views/../../../cli.py"])
def test_kein_pfad_ausbruch(c, pfad: str) -> None:  # type: ignore[no-untyped-def]
    r = c.get(pfad)
    assert r.status_code == 404, (pfad, r.status_code)
    assert "def " not in r.text and "import" not in r.text


def test_nur_bekannte_dateitypen(c, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    assert c.get("/app/fonts/OFL.txt").status_code == 200
    py = WEB / "probe.py"
    py.write_text("geheim = 1\n")
    try:
        assert c.get("/app/probe.py").status_code == 404
    finally:
        py.unlink()


def test_app_code_regeln() -> None:
    assert len(JS) >= 10
    for datei in JS:
        text = datei.read_text()
        treffer = VERBOTEN.search(text.replace("innerHTML, outerHTML, insertAdjacentHTML, document.write, eval, new Function", ""))
        assert treffer is None, f"{datei.name}: verbotene API {treffer.group(0) if treffer else ''}"
        assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", text), f"{datei.name}: externe Adresse"
        assert len(text.splitlines()) <= 400, datei.name
    html = (WEB / "index.html").read_text()
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), "Inline-Skript in index.html"
    assert " style=" not in html and "<style" not in html and not re.search(r"\son[a-z]+=", html)
    for css in (WEB / "css").glob("*.css"):
        assert not re.search(r"url\(\s*[\"']?https?:", css.read_text()), f"{css.name}: externe Quelle"
        assert "@import" not in css.read_text()


@pytest.mark.skipif(shutil.which("node") is None, reason="node fehlt — Syntax prüft dann nur der Browsertest")
def test_js_syntax() -> None:
    for datei in JS:
        r = subprocess.run(["node", "--experimental-default-type=module", "--check", str(datei)], capture_output=True,
                           text=True, timeout=30)
        assert r.returncode == 0, f"{datei.name}: {r.stderr[-400:]}"


def test_symlink_aus_dem_app_ordner_wird_nicht_ausgeliefert(c, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """Zweite Linie hinter der Pfad-Regex: ein Symlink im App-Ordner, der hinauszeigt, liefert nichts."""
    geheim = tmp_path / "geheim.txt"
    geheim.write_text("GEHEIMNIS")
    link = WEB / "leck.txt"
    link.symlink_to(geheim)
    try:
        r = c.get("/app/leck.txt")
        assert r.status_code == 404 and "GEHEIMNIS" not in r.text
    finally:
        link.unlink()


def test_web_app_manifest_installierbar(c) -> None:  # type: ignore[no-untyped-def]
    """„App installieren" in Edge/Chrome, Startbildschirm auf Handy/Tablet (ADR-017): Manifest + Icons ausgeliefert."""
    import json
    assert '<link rel="manifest" href="manifest.webmanifest">' in c.get("/app/").text
    r = c.get("/app/manifest.webmanifest")
    assert r.status_code == 200 and r.headers["content-type"] == "application/manifest+json"
    m = json.loads(r.text)
    assert m["start_url"] == m["scope"] == "/app/" and m["display"] == "standalone" and m["name"] == "IC WARE HQ"
    groessen = set()
    for icon in m["icons"]:
        bild = c.get(f"/app/{icon['src']}")
        assert bild.status_code == 200 and bild.headers["content-type"] == "image/png", icon
        breite, hoehe = int.from_bytes(bild.content[16:20], "big"), int.from_bytes(bild.content[20:24], "big")
        assert icon["sizes"] == f"{breite}x{hoehe}", icon                  # Angabe = echte Bildgröße (PNG-Kopf)
        groessen.add(icon["sizes"])
    assert {"192x192", "512x512"} <= groessen
