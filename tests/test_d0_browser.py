"""D0 — Dashboard im echten Browser (Chromium) gegen echten uvicorn: Laden, Kennzahl → gefilterte Liste,
Widgets nach Rechten, Suche, Rückfragen, Mobil. Jede CSP-Verletzung/JS-Fehler lässt einen Test scheitern."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from tests.auth_helpers import PASSWORT, join, make_user
from tests.core_helpers import ok
from tests.test_core_e2e import server  # noqa: F401  (Fixture)
from tests.test_u1_browser import Seite, browser  # noqa: F401  (Fixture)

pytest.importorskip("playwright.sync_api", reason="Playwright fehlt (pip install playwright)")


@pytest.fixture
def team(rw: Any, engines: Any, settings: Any) -> dict[str, Any]:
    ids = {}
    for name, rolle in (("chefin", "Company Admin"), ("max", "Mitarbeiter"), ("kanzlei", "Steuerberater")):
        uid = make_user(engines, settings, f"{name}@alpha.test", password=PASSWORT)
        mid = join(engines, rw.a, uid)
        rw._tenant[mid] = rw.a
        rw.gib(mid, rolle)
        ids[name] = mid
    c = rw.client(ids["chefin"])
    vorgestern = (date.today() - timedelta(days=2)).isoformat()
    for titel, extra in (("USt-VA September", {"due_date": vorgestern, "priority": "urgent"}),
                         ("Belege sortieren", {"priority": "normal"})):
        ok(c.post("/api/v1/tasks", json={"title": titel, "assignee": rw.pid(ids["chefin"]), **extra}), 201)
    t = ok(c.post("/api/v1/tasks", json={"title": "Jahresabschluss 2025"}), 201)
    ok(c.post(f"/api/v1/objects/{t['id']}/grants", json={"member": rw.pid(ids["kanzlei"])}), 201)
    ok(rw.client(ids["kanzlei"]).post(f"/api/v1/objects/{t['id']}/comments",
                                      json={"body": "Fehlt die Inventurliste?", "kind": "question"}), 201)
    ok(c.post("/api/v1/tasks", json={"title": "Max: Fahrtenbuch", "assignee": rw.pid(ids["max"])}), 201)
    ids["frage"] = t["id"]
    return ids


def _widget(s: Seite, titel: str) -> Any:
    return s.page.locator("section.widget", has=s.page.get_by_role("heading", name=titel, exact=True))


def test_dashboard_kennzahl_fuehrt_zur_liste(browser: Any, server: str, team: dict[str, Any]) -> None:  # noqa: F811
    s = Seite(browser, server)
    s.anmelden("chefin@alpha.test")
    p = s.page
    meine = _widget(s, "Meine Aufgaben")
    meine.wait_for()
    for titel in ("Mitteilungen", "Offene Rückfragen", "Aufgaben der Firma", "Firma & Team", "Aktivität"):
        _widget(s, titel).wait_for()
    assert meine.get_by_role("link", name="Offen: 2").is_visible()
    meine.get_by_role("link", name="Überfällig: 1").click()             # Wert → Liste
    p.wait_for_url("**due_before=**")
    p.get_by_text("Fällig vor").wait_for()
    zeilen = p.locator("#inhalt tbody tr")
    zeilen.first.wait_for()
    assert zeilen.count() == 1 and "USt-VA September" in zeilen.first.inner_text()
    zeilen.first.get_by_role("link").click()                             # Liste → Objekt
    p.get_by_role("heading", name="USt-VA September").wait_for()
    p.goto("/app/#/")
    _widget(s, "Offene Rückfragen").get_by_role("link", name="Jahresabschluss 2025").click()
    p.get_by_text("Fehlt die Inventurliste?").wait_for()
    s.sauber()


def test_widgets_nach_rechten_im_browser(browser: Any, server: str, team: dict[str, Any]) -> None:  # noqa: F811
    m = Seite(browser, server)
    m.anmelden("max@alpha.test")
    _widget(m, "Meine Aufgaben").wait_for()
    assert _widget(m, "Meine Aufgaben").get_by_text("Max: Fahrtenbuch").is_visible()
    for verboten in ("Aufgaben der Firma", "Firma & Team"):
        assert _widget(m, verboten).count() == 0, verboten
    text = m.page.locator("#inhalt").inner_text()
    assert "USt-VA" not in text and "Liquidität" not in text and "Offene Rechnungen" not in text
    assert m.page.get_by_label("Geplante Module").get_by_text("Fahrten").is_visible()
    k = Seite(browser, server)
    k.anmelden("kanzlei@alpha.test")
    frage = _widget(k, "Offene Rückfragen")
    frage.wait_for()
    assert frage.get_by_role("link", name="Offen: 1").is_visible()
    assert k.page.get_by_label("Geplante Module").get_by_text("Liquidität").is_visible()
    assert _widget(k, "Firma & Team").count() == 0 and _widget(k, "Aktivität").count() == 0
    frage.get_by_role("link", name="Offen: 1").click()
    k.page.get_by_role("heading", name="Rückfragen").wait_for()
    k.page.get_by_text("Fehlt die Inventurliste?").wait_for()
    m.sauber()
    k.sauber()


def test_suche_aus_der_kopfzeile(browser: Any, server: str, team: dict[str, Any]) -> None:  # noqa: F811
    s = Seite(browser, server)
    s.anmelden("chefin@alpha.test")
    s.page.get_by_role("searchbox", name="Suchen").fill("Jahresab")
    s.page.get_by_role("searchbox", name="Suchen").press("Enter")
    s.page.get_by_role("heading", name="Suche").wait_for()
    s.page.get_by_role("link", name="Jahresabschluss 2025").wait_for()
    s.sauber()


def test_dashboard_mobil(browser: Any, server: str, team: dict[str, Any]) -> None:  # noqa: F811
    s = Seite(browser, server, viewport={"width": 360, "height": 740}, is_mobile=True, has_touch=True)
    s.anmelden("chefin@alpha.test")
    _widget(s, "Meine Aufgaben").wait_for()
    breite = s.page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    assert breite[0] <= breite[1], breite
    links = s.page.locator("section.widget").first.bounding_box()
    zweite = s.page.locator("section.widget").nth(1).bounding_box()
    assert links and zweite and zweite["y"] > links["y"] + links["height"] - 1     # eine Spalte, untereinander
    s.page.get_by_role("button", name="Menü", exact=True).click()
    s.gehe("Rückfragen")
    s.page.get_by_text("Fehlt die Inventurliste?").wait_for()
    s.sauber()
