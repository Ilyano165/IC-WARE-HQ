"""ADR-021 im echten Browser (Chromium/Playwright) gegen einen echten uvicorn-Prozess: Ersteinrichtung mit
Einrichtungscode, Anmeldung als Betreiber, Firma per Assistent anlegen, pausieren — und die Gegenprobe: ein Company
Admin ohne Betreiber-Eigenschaft sieht die Verwaltung nicht und der Server lehnt ab. Keine CSP-Verletzung, kein XSS."""
from __future__ import annotations

from typing import Any

from ichq.control import service as control
from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import platform_transaction
from tests.auth_helpers import PASSWORT, db, make_user
from tests.test_core_e2e import server  # noqa: F401  (Fixture: uvicorn-Prozess)
from tests.test_u1_browser import XSS, Seite, browser  # noqa: F401  (Fixtures)

STARK = "Regen-Lampe-Fenster-42"
NEU = "Wolke-Kiesel-Brunnen-77"


def _weiter(s: Seite, knopf: str = "Weiter") -> None:
    s.page.get_by_role("button", name=knopf, exact=True).click()


def _schritt(s: Seite, titel: str) -> None:
    s.page.get_by_role("heading", name=titel).wait_for()


def test_einrichtung_und_firma_anlegen(browser: Any, server: str, engines: Engines) -> None:  # noqa: F811
    with platform_transaction(engines.platform) as t:
        code = control.new_setup_code(t, actor="test")
    s = Seite(browser, server)
    p = s.page
    p.goto("/app/")
    p.get_by_text("noch nicht eingerichtet").wait_for()             # Anmeldeseite weist auf die Einrichtung hin
    p.goto(f"/app/#/einrichtung?code={code}")
    _schritt(s, "Schritt 1 von 4: Code")
    assert p.get_by_label("Einrichtungscode").input_value() == code
    _weiter(s)
    _schritt(s, "Schritt 2 von 4: Firma")
    p.get_by_label("Name der Firma").fill("Müller & Söhne GmbH")
    assert p.get_by_label("Kürzel").input_value() == "mueller-soehne-gmbh"   # Vorschlag wie auf dem Server
    _weiter(s)
    _schritt(s, "Schritt 3 von 4: Ihr Zugang")
    p.get_by_label("Ihr Name").fill("Chefin")
    p.get_by_label("E-Mail (Anmeldename)").fill("chefin@mueller.test")
    p.get_by_label("Passwort", exact=True).fill(STARK)
    p.get_by_label("Passwort wiederholen").fill(STARK + "x")
    _weiter(s)
    p.get_by_role("alert").filter(has_text="stimmen nicht überein").wait_for()
    p.get_by_label("Passwort wiederholen").fill(STARK)
    _weiter(s)
    _schritt(s, "Schritt 4 von 4: Prüfen")
    p.get_by_text("Chefin <chefin@mueller.test>").wait_for()
    _weiter(s, "Einrichten")
    p.get_by_text("Eingerichtet.").wait_for()
    assert db(engines, "SELECT slug, status FROM tenants") == [("mueller-soehne-gmbh", "active")]
    p.get_by_role("button", name="Zur Anmeldung").click()
    p.get_by_label("E-Mail oder Benutzername").fill("chefin@mueller.test")
    p.get_by_label("Passwort").fill(STARK)
    p.get_by_role("button", name="Anmelden").click()
    p.get_by_role("navigation", name="Hauptnavigation").wait_for()
    assert {"Firmen verwalten", "Betreiber", "Mitglieder"} <= set(s.nav())

    # Zweite Firma über den Assistenten, mit neuem Konto als Administrator
    s.gehe("Firmen verwalten")
    p.get_by_role("link", name="Firma anlegen").click()
    _schritt(s, "Schritt 1 von 4: Firma")
    p.get_by_label("Name der Firma").fill(f"Maler {XSS}")
    p.get_by_label("Kürzel").fill("maler-weiss")
    _weiter(s)
    _schritt(s, "Schritt 2 von 4: Einstellungen")
    p.get_by_label("Dienstreisen").uncheck()
    _weiter(s)
    _schritt(s, "Schritt 3 von 4: Administrator")
    p.get_by_label("Neues Konto").check()
    p.get_by_label("E-Mail").fill("chefin@mueller.test")              # gibt es schon → Hinweis, nichts angelegt
    p.get_by_label("Name", exact=True).fill("Inhaberin")
    p.get_by_role("textbox", name="Startpasswort").fill(NEU)
    _weiter(s)
    p.get_by_role("alert").filter(has_text="bereits ein Konto").wait_for()
    p.get_by_label("E-Mail").fill("inhaberin@maler.test")
    _weiter(s)
    _schritt(s, "Schritt 4 von 4: Prüfen")
    p.locator(".summary dd", has_text="Dienstreisen").wait_for()      # „Module aus“ nennt das abgewählte Modul
    _weiter(s, "Firma anlegen")
    p.locator("#inhalt h1", has_text="Maler").wait_for()
    assert p.evaluate("window.__xss") is None
    p.get_by_text("Inhaberin <inhaberin@maler.test>").wait_for()
    assert not p.get_by_label("Dienstreisen").is_checked()
    # Pausieren nur mit Begründung
    p.get_by_role("button", name="Pausieren").click()
    d = p.locator("dialog[open]")
    d.get_by_label("Begründung (steht im Plattform-Audit)").fill("Zahlung offen")
    d.get_by_role("button", name="Pausieren").click()
    p.locator(".pagehead .tag", has_text="pausiert").wait_for()
    assert db(engines, "SELECT status FROM tenants WHERE slug = 'maler-weiss'") == [("paused",)]
    s.sauber()

    # Gegenprobe: Company Admin ohne Betreiber-Eigenschaft
    m = Seite(browser, server)
    m.page.goto("/")
    m.page.get_by_label("E-Mail oder Benutzername").fill("inhaberin@maler.test")
    m.page.get_by_label("Passwort").fill(NEU)
    m.page.get_by_role("button", name="Anmelden").click()
    m.page.get_by_role("navigation", name="Hauptnavigation").wait_for()
    assert "Firmen verwalten" not in m.nav() and "Mitglieder" in m.nav()
    m.page.goto("/app/#/plattform/firmen")
    m.page.get_by_role("heading", name="Keine Berechtigung").wait_for()
    assert m.page.request.get("/api/v1/platform/companies").status == 403
    m.sauber()


def test_betreiber_ohne_eigene_firma(browser: Any, server: str, engines: Engines,  # noqa: F811
                                     settings: Settings) -> None:
    """Ein Betreiber, der in keiner Firma Mitglied ist, landet direkt in der Verwaltung — ohne leere Übersicht."""
    uid = make_user(engines, settings, "chef@x.test")
    db(engines, "UPDATE users SET status = 'active' WHERE id = %s", (uid,))
    with platform_transaction(engines.platform) as t:
        control.add_operator(t, uid, actor="test")
    s = Seite(browser, server, viewport={"width": 390, "height": 844})
    p = s.page
    p.goto("/")
    p.get_by_label("E-Mail oder Benutzername").fill("chef@x.test")
    p.get_by_label("Passwort").fill(PASSWORT)
    p.get_by_role("button", name="Anmelden").click()
    p.locator("#inhalt h1", has_text="Firmen verwalten").wait_for()
    assert "Übersicht" not in s.nav() and "Firmen verwalten" in s.nav()
    assert p.evaluate("document.documentElement.scrollWidth <= window.innerWidth")   # mobil ohne Querscrollen
    p.goto("/app/#/plattform/neue-firma")
    _schritt(s, "Schritt 1 von 4: Firma")
    assert p.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    s.sauber()
