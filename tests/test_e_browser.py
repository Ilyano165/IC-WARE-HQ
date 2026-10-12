"""Fachmodule im echten Browser (Chromium/Playwright) gegen einen echten uvicorn-Prozess: was ein Mensch tut —
anlegen, Dublette bestätigen, Kontakte, Anfrage, Status; dabei keine CSP-Verletzung und kein Skript aus Daten."""
from __future__ import annotations

from typing import Any

from tests.test_core_e2e import server  # noqa: F401  (Fixture: uvicorn-Prozess)
from tests.test_u1_browser import XSS, Seite, browser, leute  # noqa: F401  (Fixtures)


def _dialog(s: Seite) -> Any:
    d = s.page.locator("dialog[open]")
    d.wait_for()
    return d


def test_kunde_kontakt_dublette_anfrage(browser: Any, server: str, leute: dict[str, Any]) -> None:  # noqa: F811
    s = Seite(browser, server)
    s.anmelden("chefin@alpha.test")
    assert {"Kunden", "Anfragen"} <= set(s.nav())
    s.gehe("Kunden")
    s.page.get_by_text("Noch keine Kunden vorhanden").wait_for()
    s.page.get_by_role("button", name="Neuer Kunde").click()
    d = _dialog(s)
    d.get_by_label("Name", exact=True).fill(f"Müller GmbH {XSS}")
    d.get_by_label("E-Mail").fill("info@mueller.test")
    d.get_by_role("button", name="Weiter").click()
    s.page.locator("#inhalt h1", has_text="Müller GmbH").wait_for()
    assert s.page.evaluate("window.__xss") is None
    # Kontaktperson
    s.page.get_by_role("button", name="Kontakt hinzufügen").click()
    d = _dialog(s)
    d.get_by_label("Name", exact=True).fill("Anna Einkauf")
    d.get_by_label("Hauptkontakt").check()
    d.get_by_role("button", name="Speichern").click()
    s.page.get_by_text("Anna Einkauf").wait_for()
    # Anfrage zum Kunden
    s.page.get_by_role("link", name="Anfrage erfassen").click()
    d = _dialog(s)
    d.get_by_label("Titel").fill("Angebot Dachsanierung")
    d.get_by_label("Nächste Aktion").fill("Rückruf")
    d.get_by_role("button", name="Anlegen").click()
    s.page.locator("#inhalt h1", has_text="Angebot Dachsanierung").wait_for()
    s.page.get_by_label("Status").select_option("won")
    s.page.get_by_role("button", name="Speichern").click()
    s.page.locator(".pagehead .tag", has_text="Gewonnen").wait_for()
    # Dublette: gleicher Name ohne Rechtsform → Warnung, dann bewusst anlegen
    s.gehe("Kunden")
    s.page.get_by_role("button", name="Neuer Kunde").click()
    d = _dialog(s)
    d.get_by_label("Name", exact=True).fill(f"Mueller KG {XSS}")      # gleicher Name ohne Rechtsform/Umlaut
    d.get_by_role("button", name="Weiter").click()
    d = _dialog(s)
    d.get_by_text("Diese Kunden sehen gleich aus").wait_for()
    d.get_by_role("button", name="Trotzdem anlegen").click()
    s.page.locator("#inhalt h1", has_text="Mueller KG").wait_for()
    s.gehe("Kunden")
    assert s.page.locator("tbody tr").count() == 2
    assert s.page.evaluate("window.__xss") is None
    s.sauber()


def test_ohne_kundenrecht_kein_crm(browser: Any, server: str, leute: dict[str, Any]) -> None:  # noqa: F811
    s = Seite(browser, server)
    s.anmelden("max@alpha.test")                       # Vorlage „Mitarbeiter": keine customers.*-Rechte
    assert "Kunden" not in s.nav() and "Anfragen" not in s.nav()
    s.page.goto("/app/#/kunden")
    s.page.get_by_role("heading", name="Keine Berechtigung").wait_for()
    s.sauber()


def test_projekt_team_zeit_kanban(browser: Any, server: str, leute: dict[str, Any]) -> None:  # noqa: F811
    s = Seite(browser, server)
    s.anmelden("chefin@alpha.test")
    s.gehe("Projekte")
    s.page.get_by_text("Noch keine Projekte vorhanden").wait_for()
    s.page.get_by_role("button", name="Neues Projekt").click()
    d = _dialog(s)
    d.get_by_label("Name", exact=True).fill(f"Dach {XSS}")
    d.get_by_label("Budget (€)").fill("15.000,50")
    d.get_by_label("Status").select_option("active")
    d.get_by_role("button", name="Anlegen").click()
    s.page.locator("#inhalt h1", has_text="Dach").wait_for()
    s.page.locator(".metric", has_text="Budget").get_by_text("15.000,50").wait_for()
    # Max (Vorlage Mitarbeiter, ohne objects.read_all) ins Team, Zeit erfassen
    s.page.get_by_role("button", name="Person aufnehmen").click()
    d = _dialog(s)
    d.get_by_label("Person").select_option(label="max")
    d.get_by_label("Rolle im Projekt").fill("Montage")
    d.get_by_role("button", name="Aufnehmen").click()
    s.page.get_by_text("Montage").wait_for()
    s.page.get_by_role("button", name="Person aufnehmen").click()
    d = _dialog(s)
    d.get_by_label("Person").select_option(label="chefin")
    d.get_by_role("button", name="Aufnehmen").click()
    s.page.locator(".item", has_text="chefin").wait_for()
    s.page.get_by_role("button", name="Zeit erfassen").click()
    d = _dialog(s)
    d.get_by_label("Minuten").fill("90")
    d.get_by_label("Tätigkeit").fill("Aufmaß")
    d.get_by_role("button", name="Erfassen").click()
    s.page.locator(".metric", has_text="Projektzeit").get_by_text("1:30 h").wait_for()
    s.gehe("Projekte")
    s.page.get_by_label("Ansicht").select_option("kanban")
    s.page.get_by_role("region", name="Aktiv").get_by_role("link", name="Dach").wait_for()
    assert s.page.evaluate("window.__xss") is None
    s.sauber()
    m = Seite(browser, server)
    m.anmelden("max@alpha.test")
    m.gehe("Projekte")
    m.page.get_by_label("Team").select_option("me")
    m.page.get_by_role("link", name="Dach").first.wait_for()
    m.sauber()
