"""D0 — Dashboard-API: Widgets nach EFFEKTIVEN Rechten, jede Zahl = Größe der verlinkten Liste, Mandantengrenzen,
Zeitzone der Firma, Fehlerisolierung. Erwartungen stehen hier ausgeschrieben (nicht aus dem Code gelesen)."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from ichq.authz.flags import set_flag
from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import platform_transaction
from tests.api_helpers import make_client
from tests.auth_helpers import client as auth_client
from tests.auth_helpers import db, login, make_user
from tests.core_helpers import ok
from tests.m4_helpers import RbacWorld

ALLE = {"warnings", "my_tasks", "questions", "notifications", "documents", "team_tasks", "company", "activity"}
PDF = {"content": b"%PDF-1.4 x", "headers": {"content-type": "application/pdf"}}


def _dash(c: Any, **params: str) -> dict[str, Any]:
    return ok(c.get("/api/v1/dashboard", params=params))  # type: ignore[no-any-return]


def _w(d: dict[str, Any], key: str) -> dict[str, Any]:
    return next(w for w in d["widgets"] if w["key"] == key)


def _m(w: dict[str, Any], key: str) -> dict[str, Any]:
    return next(m for m in w["metrics"] if m["key"] == key)


@pytest.fixture
def stb(rw: RbacWorld) -> Any:
    return rw.mitglied("stb@kanzlei.test", "Steuerberater")


def test_ohne_anmeldung_401_ohne_firma_403(settings: Settings, engines: Engines) -> None:
    c, _ = make_client(settings, engines)
    r = c.get("/api/v1/dashboard")
    assert r.status_code == 401 and r.json()["code"] == "authentication_required"
    make_user(engines, settings, "solo@nirgends.test")
    a, _ = auth_client(settings, engines)
    ok(login(a, "solo@nirgends.test"))
    r = a.get("/api/v1/dashboard")
    assert r.status_code == 403 and r.json()["code"] == "tenant_required"


def test_widgets_nach_effektiven_rechten(rw: RbacWorld, stb: Any) -> None:
    sicht = {name: {w["key"] for w in _dash(rw.client(mid))["widgets"]}
             for name, mid in (("admin", rw.admin), ("gf", rw.gf), ("ma", rw.ma), ("stb", stb))}
    assert sicht["admin"] == ALLE and sicht["gf"] == ALLE
    assert sicht["ma"] == {"warnings", "my_tasks", "questions", "notifications", "documents", "activity"}
    assert sicht["stb"] == {"warnings", "my_tasks", "questions", "notifications", "documents"}
    r = rw.client(rw.ohne).get("/api/v1/dashboard")                    # ohne dashboard.read
    assert r.status_code == 403 and r.json()["code"] == "permission_denied"


def test_mitarbeiter_sieht_keine_finanz_oder_firmendaten(rw: RbacWorld) -> None:
    gf = rw.client(rw.gf)
    geheim = ok(gf.post("/api/v1/tasks", json={"title": "Gehaltsrunde vorbereiten", "due_date": "2020-01-01"}), 201)
    d = _dash(rw.client(rw.ma))
    geplant = {p["key"] for p in d["planned"]}
    assert not geplant & {"liquidity", "open_invoices", "overdue_payments", "missing_receipts", "tax_deadlines",
                          "month_close", "datev_export", "crm", "project_profitability"}
    assert geplant == {"projects", "travel", "trips"}
    assert "Gehalt" not in str(d) and geheim["id"] not in str(d)
    # Zugewiesen, aber für ihn gesperrt (Ressourcen-DENY): zählt nicht und erscheint nicht
    gesperrt = ok(gf.post("/api/v1/tasks", json={"title": "Personalakte prüfen", "assignee": rw.pid(rw.ma)}), 201)
    sichtbar = ok(gf.post("/api/v1/tasks", json={"title": "Werkzeug bestellen", "assignee": rw.pid(rw.ma)}), 201)
    ok(rw.client(rw.admin).put(f"/api/v1/objects/{gesperrt['id']}/denies/{rw.pid(rw.ma)}"))
    ok(gf.post("/api/v1/documents?filename=lohn.pdf", **PDF), 201)
    d = _dash(rw.client(rw.ma))
    assert _m(_w(d, "my_tasks"), "open")["value"] == 1 and sichtbar["id"] in str(d)
    assert "Personalakte" not in str(d) and gesperrt["id"] not in str(d)
    assert _m(_w(d, "documents"), "pending")["value"] == 0 and "lohn.pdf" not in str(d)
    assert ok(rw.client(rw.ma).get("/api/v1/dashboard", params={"widget": "team_tasks"}), 404)


def test_steuerberater_und_geschaeftsfuehrung_geplante_module(rw: RbacWorld, stb: Any) -> None:
    stb_plan = {p["key"] for p in _dash(rw.client(stb))["planned"]}
    assert {"liquidity", "missing_receipts", "tax_deadlines", "month_close", "datev_export"} <= stb_plan
    assert "crm" not in stb_plan and "projects" not in stb_plan
    gf_plan = _dash(rw.client(rw.gf))["planned"]
    assert {p["key"] for p in gf_plan} >= {"liquidity", "open_invoices", "crm", "projects"}
    assert all(set(p) == {"key", "title", "module"} for p in gf_plan)       # geplant = keine Werte


def rw_heute(rw: RbacWorld) -> str:
    """„Heute" der Firma — unabhängig vom Code des Dashboards aus der Zeitzone im Profil berechnet."""
    zone = ok(rw.client(rw.admin).get("/api/v1/company"))["timezone"]
    return datetime.now(UTC).astimezone(ZoneInfo(zone)).date().isoformat()


def _szenario(rw: RbacWorld) -> dict[str, Any]:
    a = rw.client(rw.admin)
    ich = rw.pid(rw.admin)
    gestern = (date.today() - timedelta(days=2)).isoformat()
    for titel, extra in (("Ü1", {"due_date": gestern, "assignee": ich}), ("Ü2", {"due_date": gestern, "assignee": ich,
                         "priority": "urgent"}), ("Offen", {"assignee": ich, "priority": "high"}),
                         ("Niemand", {}), ("Niemand überfällig", {"due_date": gestern}),
                         ("Heute fällig", {"due_date": rw_heute(rw), "assignee": ich})):
        ok(a.post("/api/v1/tasks", json={"title": titel, **extra}), 201)
    erledigt = ok(a.post("/api/v1/tasks", json={"title": "Fertig", "assignee": ich, "due_date": gestern}), 201)
    ok(a.patch(f"/api/v1/tasks/{erledigt['id']}", json={"status": "done"}))
    docs = [ok(a.post(f"/api/v1/documents?filename=b{i}.pdf", **PDF), 201) for i in range(3)]
    t = ok(a.post("/api/v1/tasks", json={"title": "Mit Anhang"}), 201)
    ok(a.post(f"/api/v1/tasks/{t['id']}/attachments", json={"document": docs[0]["id"]}), 201)
    db(rw.engines, "UPDATE documents SET scan_status = 'clean'")      # Freigabe erst nach Virenprüfung (ADR-015)
    ok(a.post(f"/api/v1/documents/{docs[1]['id']}/review", json={"decision": "approved"}))
    ok(rw.client(rw.gf).post(f"/api/v1/objects/{t['id']}/comments", json={"body": "Wozu?", "kind": "question"}), 201)
    return {"docs": docs, "task": t}


def _anzahl(c: Any, pfad: str, params: dict[str, Any]) -> int:
    n, cursor = 0, None
    while True:
        seite = ok(c.get(pfad, params={**params, "limit": 100, **({"cursor": cursor} if cursor else {})}))
        n += len(seite["items"])
        cursor = seite.get("next_cursor")
        if not cursor:
            return n


LISTEN = {"tasks": "/api/v1/tasks", "documents": "/api/v1/documents", "questions": "/api/v1/questions",
          "members": "/api/v1/members"}


def test_jede_zahl_entspricht_der_verlinkten_liste(rw: RbacWorld) -> None:
    _szenario(rw)
    a = rw.client(rw.admin)
    d = _dash(a)
    erwartet = {("my_tasks", "open"): 4, ("my_tasks", "overdue"): 2, ("my_tasks", "urgent"): 2,
                ("team_tasks", "open"): 7, ("team_tasks", "overdue"): 3, ("team_tasks", "unassigned"): 3,
                ("documents", "pending"): 2, ("documents", "unlinked"): 2, ("documents", "new"): 3,
                ("questions", "open"): 1}
    for (w, m), wert in erwartet.items():
        assert _m(_w(d, w), m)["value"] == wert, (w, m)
    geprueft = 0
    for w in d["widgets"]:
        if w.get("list") not in LISTEN:
            continue
        for m in w["metrics"]:
            if m["filter"] or w["list"] == "questions":
                assert _anzahl(a, LISTEN[w["list"]], m["filter"]) == m["value"], (w["key"], m["key"])
                geprueft += 1
    assert geprueft >= 10
    n = _w(d, "notifications")
    assert _m(n, "unread")["value"] == ok(a.get("/api/v1/notifications?unread=true"))["unread_count"]


def test_mandantengrenze(rw: RbacWorld) -> None:
    b = rw.client(rw.admin_b)
    ok(b.post("/api/v1/tasks", json={"title": "Beta geheim", "assignee": rw.pid(rw.admin_b), "due_date": "2020-01-01"}),
       201)
    ok(b.post("/api/v1/documents?filename=beta.pdf", **PDF), 201)
    d = _dash(rw.client(rw.admin))
    assert "Beta" not in str(d) and "beta.pdf" not in str(d)
    assert _m(_w(d, "my_tasks"), "open")["value"] == 0 and _m(_w(d, "documents"), "pending")["value"] == 0
    assert _m(_w(_dash(b), "my_tasks"), "overdue")["value"] == 1
    assert rw.client(rw.admin).get("/api/v1/dashboard", params={"widget": "gibtsnicht"}).status_code == 404


def test_rechteentzug_entfernt_widget_sofort(rw: RbacWorld) -> None:
    admin = rw.client(rw.admin)
    ok(admin.put(f"/api/v1/members/{rw.pid(rw.ma)}/overrides/files.read", json={"effect": "deny"}))
    assert "documents" not in {w["key"] for w in _dash(rw.client(rw.ma))["widgets"]}
    with platform_transaction(rw.engines.platform) as s:
        set_flag(s, rw.a, "tasks", False, actor="test", reason="Test")
    keys = {w["key"] for w in _dash(admin)["widgets"]}
    assert not keys & {"my_tasks", "team_tasks"} and "documents" in keys


def test_offene_rueckfrage_regel(rw: RbacWorld, stb: Any) -> None:
    a, s = rw.client(rw.admin), rw.client(stb)
    t = ok(a.post("/api/v1/tasks", json={"title": "Beleg März"}), 201)
    ok(a.post(f"/api/v1/objects/{t['id']}/grants", json={"member": rw.pid(stb)}), 201)
    ok(s.post(f"/api/v1/objects/{t['id']}/comments", json={"body": "Wo ist die Rechnung?", "kind": "question"}), 201)
    offen = lambda: _m(_w(_dash(a), "questions"), "open")["value"]  # noqa: E731
    assert offen() == 1 and _m(_w(_dash(s), "questions"), "open")["value"] == 1
    ok(s.post(f"/api/v1/objects/{t['id']}/comments", json={"body": "Nachtrag: März 2026"}), 201)
    assert offen() == 1                                                       # Fragesteller selbst: bleibt offen
    antwort = ok(a.post(f"/api/v1/objects/{t['id']}/comments", json={"body": "Liegt im Ordner."}), 201)
    assert offen() == 0
    ok(a.request("DELETE", f"/api/v1/comments/{antwort['id']}", json={"reason": "falsch beantwortet"}), 204)
    assert offen() == 1                                                       # gelöschte Antwort zählt nicht
    assert [q["object"]["id"] for q in ok(a.get("/api/v1/questions"))["items"]] == [t["id"]]
    assert ok(rw.client(rw.ma).get("/api/v1/questions"))["items"] == []       # nicht sichtbar → nicht gelistet


@pytest.mark.parametrize("zone", ["Pacific/Kiritimati", "Pacific/Pago_Pago"])
def test_heute_in_der_zeitzone_der_firma(rw: RbacWorld, zone: str) -> None:
    """+14 h und −11 h: zu jeder Uhrzeit weicht mindestens eine der beiden Zonen vom UTC-Datum ab."""
    ok(rw.client(rw.admin).patch("/api/v1/company", json={"timezone": zone}))
    d = _dash(rw.client(rw.admin))
    assert d["today"] == datetime.now(UTC).astimezone(ZoneInfo(zone)).date().isoformat()


def test_ein_defektes_widget_leert_das_dashboard_nicht(rw: RbacWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    import dataclasses

    from ichq.dashboard.registry import WIDGETS

    def kaputt(*_: Any) -> Any:
        db(rw.engines, "SELECT 1")
        raise RuntimeError("absichtlich")
    monkeypatch.setitem(WIDGETS, "documents", dataclasses.replace(WIDGETS["documents"], loader=kaputt))
    d = _dash(rw.client(rw.admin))
    assert _w(d, "documents") ["error"] == "unavailable"
    assert "metrics" in _w(d, "my_tasks") and "items" in _w(d, "activity")


def test_firma_widget_warnt_bei_nur_einem_admin(rw: RbacWorld) -> None:
    d = _dash(rw.client(rw.admin))
    assert _m(_w(d, "company"), "admins")["value"] == 1 and _m(_w(d, "company"), "admins")["tone"] == "warn"
    assert any("Verwaltungsrechte" in i["title"] for i in _w(d, "warnings")["items"])
    rw.gib(rw.gf, "Company Admin")
    d = _dash(rw.client(rw.admin))
    assert _m(_w(d, "company"), "admins")["value"] == 2
    assert not any("Verwaltungsrechte" in i["title"] for i in _w(d, "warnings")["items"])
