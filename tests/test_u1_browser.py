"""U1 — echte Oberfläche im echten Browser (Chromium/Playwright) gegen einen echten uvicorn-Prozess.

Geprüft wird, was ein Mensch tut: anmelden, Firma, Navigation nach Rechten, Aufgabe anlegen und kommentieren,
Rechte einer Person ändern — und dabei: keine CSP-Verletzung, kein Skript aus Daten (XSS), mobil ohne Querscrollen.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from ichq.core.config import Settings
from ichq.db.engine import Engines
from tests.auth_helpers import PASSWORT, join, make_user
from tests.test_core_e2e import server  # noqa: F401  (Fixture: uvicorn-Prozess)

sync_api = pytest.importorskip("playwright.sync_api", reason="Playwright fehlt (pip install playwright)")
XSS = "<img src=x onerror=\"window.__xss=1\"><script>window.__xss=2</script>"


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


class Seite:
    """Eine Browserseite, die jede CSP-Verletzung und jeden Skriptfehler mitschreibt."""

    def __init__(self, browser: Any, basis: str, **kontext: Any) -> None:
        self.ctx = browser.new_context(base_url=basis, **kontext)
        self.page = self.ctx.new_page()
        self.fehler: list[str] = []
        self.page.on("console", lambda m: self.fehler.append(m.text) if m.type == "error" else None)
        self.page.on("pageerror", lambda e: self.fehler.append(str(e)))
        self.page.set_default_timeout(8000)

    def anmelden(self, email: str) -> None:
        p = self.page
        p.goto("/")
        p.get_by_label("E-Mail oder Benutzername").fill(email)
        p.get_by_label("Passwort").fill(PASSWORT)
        p.get_by_role("button", name="Anmelden").click()
        p.get_by_role("navigation", name="Hauptnavigation").wait_for()

    def gehe(self, name: str) -> None:
        self.page.get_by_role("navigation", name="Hauptnavigation").get_by_role("link", name=name, exact=True).click()
        self.page.locator("#inhalt h1").first.wait_for()

    def nav(self) -> list[str]:
        return self.page.get_by_role("navigation", name="Hauptnavigation").get_by_role("link").all_inner_texts()

    def sauber(self) -> None:
        csp = [f for f in self.fehler if "Content Security Policy" in f or "Refused" in f]
        assert not csp, csp
        assert not [f for f in self.fehler if "Error" in f and "401" not in f and "403" not in f], self.fehler


@pytest.fixture
def leute(rw: Any, engines: Engines, settings: Settings) -> dict[str, Any]:
    ids = {}
    for name, rolle in (("chefin", "Company Admin"), ("max", "Mitarbeiter"), ("leitung", "Geschäftsführung")):
        uid = make_user(engines, settings, f"{name}@alpha.test", password=PASSWORT)
        mid = join(engines, rw.a, uid)
        rw._tenant[mid] = rw.a
        rw.gib(mid, rolle)
        ids[name] = mid
    return ids


def test_anmelden_navigation_nach_rechten(browser: Any, server: str, leute: dict[str, Any]) -> None:  # noqa: F811
    s = Seite(browser, server)
    s.page.goto("/")
    assert s.page.url.endswith("/app/")
    s.page.get_by_label("E-Mail oder Benutzername").fill("chefin@alpha.test")
    s.page.get_by_label("Passwort").fill("falsch-falsch-falsch")
    s.page.get_by_role("button", name="Anmelden").click()
    assert "falsch" in s.page.get_by_role("alert").inner_text()
    s.anmelden("chefin@alpha.test")
    assert {"Aufgaben", "Mitglieder", "Rollen & Rechte", "Audit", "Konto & Sicherheit"} <= set(s.nav())
    s.page.get_by_role("heading", name="Hallo chefin").wait_for()
    m = Seite(browser, server)
    m.anmelden("max@alpha.test")
    nav = set(m.nav())
    assert "Aufgaben" in nav and not {"Rollen & Rechte", "Audit", "Mitglieder"} & nav
    m.page.goto("/app/#/rollen")                                    # Direktaufruf: Oberfläche sagt nein …
    m.page.get_by_role("heading", name="Keine Berechtigung").wait_for()
    r = m.page.request.get("/api/v1/roles")                         # … und der Server sowieso
    assert r.status == 403
    s.sauber()
    m.sauber()


def test_aufgabe_anlegen_kommentieren_ohne_xss(browser: Any, server: str, leute: dict[str, Any]) -> None:  # noqa: F811
    s = Seite(browser, server)
    s.anmelden("chefin@alpha.test")
    p = s.page
    s.gehe("Aufgaben")
    p.get_by_role("button", name="Neue Aufgabe").click()
    p.get_by_label("Titel").fill(XSS)
    p.get_by_label("Beschreibung").fill("Zeile 1\n<b>fett?</b>")
    p.get_by_role("button", name="Anlegen").click()
    p.get_by_role("heading", name=XSS).wait_for()                  # als Text angezeigt
    p.get_by_label("Kommentar").fill(f"Bitte prüfen {XSS}")
    p.get_by_role("button", name="Senden").click()
    p.get_by_text(f"Bitte prüfen {XSS}").wait_for()
    p.get_by_label("Status").select_option("done")
    p.get_by_role("button", name="Speichern").click()
    p.get_by_text("Gespeichert.").first.wait_for()
    assert p.evaluate("window.__xss") is None
    assert p.locator("img[src=x]").count() == 0 and p.locator("#inhalt script").count() == 0
    p.get_by_role("link", name="← Aufgaben").click()
    p.get_by_role("combobox").first.select_option("done")
    p.get_by_role("link", name=XSS).wait_for()
    s.sauber()


def test_rechte_einer_person_aendern(browser: Any, server: str, leute: dict[str, Any], rw: Any) -> None:  # noqa: F811
    s = Seite(browser, server)
    s.anmelden("chefin@alpha.test")
    p = s.page
    s.gehe("Mitglieder")
    p.get_by_role("link", name="max", exact=True).click()
    p.get_by_role("heading", name="Was diese Person darf").wait_for()
    zeile = p.locator("tr", has=p.get_by_text("tasks.create", exact=True))
    assert "darf\t" in zeile.inner_text().lower() and "Mitarbeiter" in zeile.inner_text()
    zeile.get_by_role("combobox").select_option("deny")
    p.get_by_text("Gespeichert.").first.wait_for()
    zeile = p.locator("tr", has=p.get_by_text("tasks.create", exact=True))
    zeile.get_by_text("Einzelrecht: verboten").wait_for()
    assert "tasks.create" not in rw.rechte(leute["max"])           # wirklich auf dem Server
    # Eigenes Konto: Hinweis statt Bedienelemente
    p.get_by_role("link", name="← Mitglieder").click()
    p.get_by_role("link", name="chefin", exact=True).click()
    p.get_by_text("eigenes Konto").wait_for()
    assert p.get_by_role("combobox", name="Einzelrecht tasks.read").count() == 0
    # Rollen-Editor: gesperrte Rolle ist nicht bearbeitbar
    s.gehe("Rollen & Rechte")
    p.get_by_role("link", name="Company Admin").click()
    p.get_by_text("ist gesperrt").wait_for()
    assert p.get_by_role("button", name="Speichern").count() == 0
    s.sauber()


def test_mobil_ohne_querscrollen(browser: Any, server: str, leute: dict[str, Any]) -> None:  # noqa: F811
    s = Seite(browser, server, viewport={"width": 360, "height": 740}, is_mobile=True, has_touch=True)
    s.anmelden("chefin@alpha.test")
    p = s.page
    for ziel in ("#/", "#/aufgaben", "#/mitglieder", "#/rollen", "#/konto"):
        p.goto(f"/app/{ziel}")
        p.locator("#inhalt h1").first.wait_for()
        breite = p.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        assert breite[0] <= breite[1], (ziel, breite)
    assert not p.get_by_role("navigation", name="Hauptnavigation").get_by_role("link", name="Aufgaben").is_visible() \
        or p.evaluate("getComputedStyle(document.querySelector('.side')).transform") != "none"
    p.get_by_role("button", name="Menü").click()
    s.gehe("Aufgaben")
    p.get_by_role("heading", name="Aufgaben").wait_for()
    s.sauber()
