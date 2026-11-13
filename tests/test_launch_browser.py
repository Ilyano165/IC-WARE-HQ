"""Regressionstests der UI-Prüfung vor dem Launch (09.10.2026) — echter Browser gegen echten uvicorn-Prozess.

Je Befund ein Test: falsches Passwort meldet nicht ab, Doppelklick legt nichts doppelt an, Anhänge in der
Oberfläche, mobiles Menü schließbar, Kommentar-Knöpfe nur für eigene, keine „undefined"-Texte.
"""
from __future__ import annotations

from typing import Any

import pytest

from tests.test_core_e2e import server  # noqa: F401  (Fixture: uvicorn-Prozess)
from tests.test_u1_browser import Seite, browser, leute  # noqa: F401  (Fixtures)

sync_api = pytest.importorskip("playwright.sync_api", reason="Playwright fehlt (pip install playwright)")


def _api(s: Seite, server: str, methode: str, pfad: str, **kw: Any) -> Any:  # noqa: F811
    r = s.page.request.fetch(f"{server}/api/v1{pfad}", method=methode, headers={"Origin": server, **kw.pop("headers", {})},
                             **kw)
    assert r.ok, (pfad, r.status, r.text())
    return r.json() if r.status != 204 else None


def test_falsches_passwort_im_konto_meldet_nicht_ab(browser: Any, server: str, leute: dict[str, Any]) -> None:  # noqa: F811
    s = Seite(browser, server)
    s.anmelden("max@alpha.test")
    s.gehe("Konto & Sicherheit")
    p = s.page
    form = p.locator("form").filter(has=p.get_by_label("Neues Passwort"))
    form.get_by_label("Aktuelles Passwort").fill("ganz-falsch-geraten")
    form.get_by_label("Neues Passwort").fill("Neues-Passwort-Wolke-77")
    form.get_by_role("button").first.click()
    p.get_by_text("Passwort ist falsch").first.wait_for()            # Meldung am Formular …
    assert p.get_by_role("navigation", name="Hauptnavigation").is_visible()   # … und weiter angemeldet
    assert p.get_by_text("Sitzung beendet").count() == 0
    s.sauber()


def test_doppelklick_legt_kommentar_nur_einmal_an(browser: Any, server: str, leute: dict[str, Any]) -> None:  # noqa: F811
    s = Seite(browser, server)
    s.anmelden("chefin@alpha.test")
    t = _api(s, server, "POST", "/tasks", data={"title": "Doppelklick-Probe"})
    s.page.goto(f"/app/#/aufgaben/{t['id']}")
    s.page.get_by_placeholder("Kommentar schreiben …").fill("Nur einmal bitte")
    s.page.get_by_role("button", name="Senden").dblclick()
    s.page.locator(".comment").first.wait_for()
    s.page.wait_for_timeout(800)
    assert len(_api(s, server, "GET", f"/objects/{t['id']}/comments")["items"]) == 1
    s.sauber()


def test_dokument_an_aufgabe_anhaengen(browser: Any, server: str, leute: dict[str, Any]) -> None:  # noqa: F811
    s = Seite(browser, server)
    s.anmelden("chefin@alpha.test")
    d = _api(s, server, "POST", "/documents?filename=Rechnung-Anhang.pdf", data=b"%PDF-1.4 x",
             headers={"Content-Type": "application/pdf"})
    t = _api(s, server, "POST", "/tasks", data={"title": "Mit Anhang"})
    p = s.page
    p.goto(f"/app/#/aufgaben/{t['id']}")
    p.get_by_text("Keine Anhänge.").wait_for()
    p.get_by_role("button", name="Dokument anhängen").click()
    p.locator("dialog select[name=document]").select_option(d["id"])
    p.locator("dialog").get_by_role("button", name="Anhängen").click()
    p.get_by_role("link", name="Rechnung-Anhang.pdf").wait_for()
    links = _api(s, server, "GET", f"/objects/{t['id']}/links")["items"]
    assert [x["object"]["id"] for x in links] == [d["id"]]
    s.sauber()


def test_mobiles_menue_schliesst(browser: Any, server: str, leute: dict[str, Any]) -> None:  # noqa: F811
    s = Seite(browser, server, viewport={"width": 390, "height": 844})
    s.anmelden("chefin@alpha.test")
    p = s.page
    shell = p.locator(".shell")
    for schliessen in ("escape", "hintergrund", "knopf"):
        p.get_by_role("button", name="Menü", exact=True).click()
        assert "nav-open" in (shell.get_attribute("class") or "")
        assert p.get_by_role("button", name="Menü", exact=True).get_attribute("aria-expanded") == "true"
        if schliessen == "escape":
            p.keyboard.press("Escape")
        elif schliessen == "hintergrund":
            p.mouse.click(380, 400)                                  # rechts neben der Seitenleiste
        else:
            p.get_by_role("button", name="Menü schließen").click()
        p.wait_for_function("!document.querySelector('.shell').classList.contains('nav-open')")
    s.sauber()


def test_kommentarknoepfe_nur_fuer_eigene_und_keine_undefined(
        browser: Any, server: str, leute: dict[str, Any], rw: Any) -> None:  # noqa: F811
    chefin = Seite(browser, server)
    chefin.anmelden("chefin@alpha.test")
    t = _api(chefin, server, "POST", "/tasks", data={"title": "Fremder Kommentar"})
    _api(chefin, server, "POST", f"/objects/{t['id']}/comments", data={"body": "von der Chefin", "kind": "note"})
    _api(chefin, server, "PATCH", f"/tasks/{t['id']}", data={"assignee": rw.pid(leute["max"])})
    from ichq.jobs.worker import run_once
    from ichq.notifications.handlers import assert_handlers
    assert_handlers()                                      # wie `ichq worker`: Handler laden
    assert run_once(rw.engines).done >= 1                  # Worker stellt die Zuweisungs-Benachrichtigung zu
    s = Seite(browser, server)
    s.anmelden("max@alpha.test")
    s.page.goto(f"/app/#/aufgaben/{t['id']}")
    s.page.get_by_text("von der Chefin").wait_for()
    assert s.page.locator(".comment").get_by_role("button", name="Bearbeiten").count() == 0
    s.gehe("Benachrichtigungen")
    s.page.goto("/app/#/benachrichtigungen?alle=1")
    s.page.locator("#inhalt h1").first.wait_for()
    s.page.get_by_text("Fremder Kommentar").first.wait_for()    # die Benachrichtigung ist wirklich da
    text = s.page.locator("#inhalt").inner_text()
    assert "undefined" not in text and "Aufgabe" in text, text
    s.sauber()
