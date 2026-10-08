"""Sicherheit der Core-Plattform: IDOR/Cross-Tenant über ALLE Routen, Rechte-Matrix, Steuerberater, Pause."""
from __future__ import annotations

import re
from typing import Any

import pytest

from ichq.api.security import iter_api_routes
from ichq.app import create_app
from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import platform_transaction, tenant_transaction
from ichq.members.service import invite
from ichq.tenancy.service import set_status
from tests.auth_helpers import db
from tests.conftest import World
from tests.core_helpers import CoreWorld, ok, run_worker

PDF = {"content": b"%PDF-1.4 x", "headers": {"content-type": "application/pdf"}}


@pytest.fixture
def cw(world: World, engines: Engines, settings: Settings) -> CoreWorld:
    return CoreWorld(world, engines, settings)


def _bestand(cw: CoreWorld, mid: Any) -> dict[str, str]:
    """Je Firma: Aufgabe, Dokument, Kommentar, Verknüpfung, Benachrichtigung, Mitglied, Freigabe-Ziel."""
    c = cw.client(mid)
    t = ok(c.post("/api/v1/tasks", json={"title": f"Geheim {mid.hex[:6]}", "assignee": cw.public_id(mid)}), 201)
    d = ok(c.post("/api/v1/documents?filename=beleg.pdf", **PDF), 201)
    k = ok(c.post(f"/api/v1/objects/{t['id']}/comments", json={"body": "Interna"}), 201)
    link = ok(c.post(f"/api/v1/tasks/{t['id']}/attachments", json={"document": d["id"]}), 201)
    p = cw.principal(mid)
    with tenant_transaction(cw.engines.app, p.tenant_id) as s:   # Einladung ohne Mailversand anlegen
        inv, _roh = invite(s, p, email=f"neu-{mid.hex[:8]}@extern.test", title=None)
    return {"task": t["id"], "document": d["id"], "comment": k["id"], "link": link["id"],
            "member": cw.public_id(mid), "invitation": inv.public_id}


def _notification(cw: CoreWorld, engines: Engines, empfaenger: Any, tid: Any, absender: Any) -> str:
    c = cw.client(absender)
    t = ok(c.post("/api/v1/tasks", json={"title": "Benachrichtigung"}), 201)
    ok(c.post(f"/api/v1/objects/{t['id']}/comments", json={"body": "@", "mentions": [cw.public_id(empfaenger)]}), 201)
    run_worker(engines)
    return str(db(engines, "SELECT public_id FROM notifications WHERE tenant_id = %s ORDER BY created_at DESC "
                           "LIMIT 1", (tid,))[0][0])


# Eingaben, die die Validierung bestehen — sonst würde 422 ein fehlendes 404 verdecken.
BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("POST", "/api/v1/objects/{ref}/links"): {"link_type": "related"},          # target wird eingesetzt
    ("POST", "/api/v1/objects/{ref}/grants"): {},                                # member wird eingesetzt
    ("POST", "/api/v1/objects/{ref}/tasks"): {"title": "Eingeschleust"},
    ("POST", "/api/v1/objects/{ref}/comments"): {"body": "Eingeschleust"},
    ("PATCH", "/api/v1/tasks/{ref}"): {"title": "Übernommen", "status": "done"},
    ("POST", "/api/v1/tasks/{ref}/attachments"): {},                             # document wird eingesetzt
    ("PATCH", "/api/v1/comments/{ref}"): {"body": "Übernommen"},
    ("DELETE", "/api/v1/comments/{ref}"): {"reason": "Eingeschleust"},
    ("POST", "/api/v1/comments/{ref}/tasks"): {"title": "Eingeschleust"},
    ("POST", "/api/v1/documents/{ref}/review"): {"decision": "approved"},
    ("POST", "/api/v1/members/{member}/deactivate"): {},
}


def _ref_fuer(pfad: str, param: str, refs: dict[str, str]) -> str:
    if param == "member":
        return refs["member"]
    for praefix, art in (("/api/v1/invitations/", "invitation"), ("/api/v1/tasks/", "task"),
                         ("/api/v1/comments/", "comment"),
                         ("/api/v1/documents/", "document"), ("/api/v1/notifications/", "notification"),
                         ("/api/v1/links/", "link"), ("/api/v1/objects/", "task")):
        if pfad.startswith(praefix):
            return refs[art]
    raise AssertionError(f"Route {pfad} ist im IDOR-Test nicht abgedeckt — Zuordnung ergänzen")


def _aufrufe(settings: Settings, engines: Engines, refs: dict[str, str], ziel: dict[str, str]) -> list[Any]:
    app = create_app(settings, engines=engines)
    faelle = []
    for pfad, methoden, _ in iter_api_routes(app):
        params = re.findall(r"{(\w+)}", pfad)
        if not params or not pfad.startswith("/api/v1/"):
            continue
        for m in sorted(methoden - {"HEAD"}):
            url = pfad
            for name in params:
                url = url.replace("{" + name + "}", _ref_fuer(pfad, name, refs))
            body = dict(BODIES.get((m, pfad), {}))
            if m in ("POST", "PATCH", "PUT") and (m, pfad) not in BODIES and not pfad.endswith("/read"):
                raise AssertionError(f"{m} {pfad}: gültiger Body für den IDOR-Test fehlt")
            body.update({k: ziel[v] for k, v in (("target", "task"), ("member", "member"), ("document", "document"))
                         if (m, pfad) in BODIES and k in _felder(m, pfad)})
            faelle.append((m, pfad, url, body))
    return faelle


def _felder(m: str, pfad: str) -> set[str]:
    return {("POST", "/api/v1/objects/{ref}/links"): {"target"}, ("POST", "/api/v1/objects/{ref}/grants"): {"member"},
            ("POST", "/api/v1/tasks/{ref}/attachments"): {"document"}}.get((m, pfad), set())


def test_idor_jede_route_mit_id_liefert_404_fuer_fremde_firma(cw: CoreWorld, settings: Settings,
                                                               engines: Engines) -> None:
    """Tor 1 — Generator: ALLE /api/v1-Routen mit Pfadparametern (Core + M3). Admin aus A (alle Rechte) greift
    mit IDs aus B zu → 404. Neue Routen ohne Zuordnung lassen den Test scheitern.
    Gegenprobe im selben Test: mit eigenen IDs ist keine dieser Antworten 404 (sonst prüfte der Test nichts)."""
    eigene, fremde = _bestand(cw, cw.admin_a), _bestand(cw, cw.admin_b)
    eigene["notification"] = _notification(cw, engines, cw.admin_a, cw.a, cw.mitarbeiter)
    fremde["notification"] = _notification(cw, engines, cw.admin_b, cw.b, cw.mitarbeiter_b)
    vorher = db(engines, "SELECT count(*), max(updated_at) FROM objects WHERE tenant_id = %s", (cw.b,))
    c = cw.client(cw.admin_a)
    geprueft = 0
    for m, pfad, url, body in _aufrufe(settings, engines, fremde, fremde):
        r = c.request(m, url, json=body or None)
        assert r.status_code == 404, f"{m} {pfad} mit ID aus Firma B: {r.status_code} {r.text[:200]}"
        assert fremde["task"] not in r.text.replace(url, "") and "Geheim" not in r.text
        geprueft += 1
    assert geprueft >= 20, geprueft
    # B unverändert, nichts aus A ist in B gelandet
    assert db(engines, "SELECT count(*), max(updated_at) FROM objects WHERE tenant_id = %s", (cw.b,)) == vorher
    assert db(engines, "SELECT body FROM comments WHERE public_id = %s", (fremde["comment"],))[0][0] == "Interna"
    assert db(engines, "SELECT count(*) FROM object_links WHERE public_id = %s", (fremde["link"],))[0][0] == 1
    # Gemischt: eigenes Objekt, fremdes Ziel/Mitglied → ebenfalls 404
    for m, pfad, url, body in _aufrufe(settings, engines, eigene, fremde):
        if body and _felder(m, pfad):
            r = c.request(m, url, json=body)
            assert r.status_code == 404, f"{m} {pfad} mit fremdem Ziel: {r.status_code}"
    # Gegenprobe: eigene IDs → nie 404 (Reihenfolge: Löschungen zuletzt)
    gegen = sorted(_aufrufe(settings, engines, eigene, eigene), key=lambda f: f[0] == "DELETE")
    for m, pfad, url, body in gegen:
        r = c.request(m, url, json=body or None)
        assert r.status_code != 404, f"Gegenprobe {m} {pfad}: {r.status_code} {r.text[:200]}"


def test_fremde_ids_in_listen_filtern_und_suche_unsichtbar(cw: CoreWorld) -> None:
    fremde = _bestand(cw, cw.admin_b)
    _bestand(cw, cw.admin_a)
    c = cw.client(cw.admin_a)
    for pfad in ("/api/v1/tasks?limit=100", "/api/v1/documents?limit=100", "/api/v1/activities?limit=100",
                 "/api/v1/audit?limit=100", "/api/v1/notifications", "/api/v1/members?limit=100",
                 "/api/v1/search?q=Geheim&per_group=20"):
        r = ok(c.get(pfad))
        text = str(r)
        for wert in fremde.values():
            assert wert not in text, (pfad, wert)
    assert c.get(f"/api/v1/tasks?subject={fremde['task']}").status_code == 404
    assert c.get(f"/api/v1/tasks?assignee={fremde['member']}").status_code == 404
    assert c.get(f"/api/v1/activities?actor={fremde['member']}").status_code == 404
    assert "Chef Beta" not in str(ok(c.get("/api/v1/search?q=Chef")))


# ---------- Rechte-Matrix ----------
def test_ohne_rechte_kein_zugriff(cw: CoreWorld) -> None:
    refs = _bestand(cw, cw.admin_a)
    c = cw.client(cw.ohne)
    for m, pfad in (("GET", "/api/v1/tasks"), ("POST", "/api/v1/tasks"), ("GET", "/api/v1/documents"),
                    ("GET", "/api/v1/activities"), ("GET", "/api/v1/audit"), ("GET", "/api/v1/audit/export"),
                    ("GET", "/api/v1/members"), ("GET", f"/api/v1/tasks/{refs['task']}"),
                    ("GET", f"/api/v1/objects/{refs['task']}/comments"),
                    ("POST", f"/api/v1/objects/{refs['task']}/grants")):
        r = c.request(m, pfad, json={"title": "x"} if m == "POST" else None)
        assert r.status_code == 403 and r.json()["code"] == "permission_denied", (m, pfad, r.status_code)
    # Routen ohne Modulrecht in der Marke: Objekt bleibt unsichtbar (404), Suche leer
    assert c.get(f"/api/v1/objects/{refs['task']}").status_code == 404
    assert all(not g["items"] for g in ok(c.get("/api/v1/search?q=Geheim"))["groups"].values())


def test_ohne_kommentarrecht_kein_kommentar(cw: CoreWorld) -> None:
    refs = _bestand(cw, cw.admin_a)
    r = cw.client(cw.leser).post(f"/api/v1/objects/{refs['task']}/comments", json={"body": "Darf ich?"})
    assert r.status_code == 403 and "comments.create" in r.json()["detail"]
    assert len(ok(cw.client(cw.leser).get(f"/api/v1/objects/{refs['task']}/comments"))["items"]) == 1


def test_ohne_exportrecht_kein_export(cw: CoreWorld) -> None:
    _bestand(cw, cw.admin_a)
    r = cw.client(cw.mitarbeiter).get("/api/v1/audit/export")
    assert r.status_code == 403 and "audit.export" in r.json()["detail"]
    r = cw.client(cw.admin_a).get("/api/v1/audit/export?max_rows=3")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    zeilen = r.text.strip().splitlines()
    assert zeilen[0].startswith("occurred_at,action,actor") and len(zeilen) == 4
    assert r.headers["x-ichq-truncated"] == "true"
    assert "Interna" not in r.text                                       # Kommentartexte nie im Audit
    actions = [e["action"] for e in ok(cw.client(cw.admin_a).get("/api/v1/audit?action=audit.exported"))["items"]]
    assert actions == ["audit.exported"]


def test_ohne_modulrecht_direktaufruf_api(cw: CoreWorld) -> None:
    refs = _bestand(cw, cw.admin_a)
    leser = cw.client(cw.leser)                           # hat weder files.upload noch tasks.create/update
    assert leser.post("/api/v1/documents?filename=x.pdf", **PDF).status_code == 403
    assert leser.post("/api/v1/tasks", json={"title": "x"}).status_code == 403
    assert leser.patch(f"/api/v1/tasks/{refs['task']}", json={"status": "done"}).status_code == 403
    assert leser.post(f"/api/v1/documents/{refs['document']}/review", json={"decision": "approved"}).status_code == 403
    vertrag = cw.raw_object(cw.a, "contract", "Mietvertrag Büro", by=cw.admin_a)
    assert cw.client(cw.mitarbeiter).get(f"/api/v1/objects/{vertrag}").status_code == 404   # kein contracts.read
    assert ok(cw.client(cw.admin_a).get(f"/api/v1/objects/{vertrag}"))["type"] == "contract"


def test_steuerberater_sieht_nur_freigegebene_objekte(cw: CoreWorld, engines: Engines) -> None:
    admin, stb = cw.client(cw.admin_a), cw.client(cw.stb)
    refs = _bestand(cw, cw.admin_a)
    beleg = cw.raw_object(cw.a, "receipt", "Bewirtung Kunde Müller", by=cw.admin_a, search_text="Restaurant")
    anderer = cw.raw_object(cw.a, "receipt", "Bewirtung Lieferant", by=cw.admin_a, search_text="Restaurant")
    # vor der Freigabe: nichts
    assert stb.get(f"/api/v1/objects/{beleg}").status_code == 404
    assert ok(stb.get("/api/v1/tasks"))["items"] == [] and ok(stb.get("/api/v1/documents"))["items"] == []
    assert stb.get(f"/api/v1/objects/{beleg}/comments").status_code == 404
    assert stb.post(f"/api/v1/objects/{beleg}/comments", json={"body": "?"}).status_code == 404
    assert ok(stb.get("/api/v1/search?q=Bewirtung"))["groups"]["receipts"]["items"] == []
    # Freigabe für genau einen Beleg
    ok(admin.post(f"/api/v1/objects/{beleg}/grants", json={"member": cw.public_id(cw.stb)}), 201)
    assert ok(stb.get(f"/api/v1/objects/{beleg}"))["id"] == beleg
    treffer = ok(stb.get("/api/v1/search?q=Bewirtung restaurant"))["groups"]["receipts"]["items"]
    assert [t["id"] for t in treffer] == [beleg]
    assert stb.get(f"/api/v1/objects/{anderer}").status_code == 404
    feed = ok(stb.get("/api/v1/activities?limit=100"))["items"]
    assert feed and {a["object"]["id"] for a in feed} == {beleg}
    ok(stb.post(f"/api/v1/objects/{beleg}/comments", json={"body": "Bewirtungsbeleg unvollständig",
                                                            "kind": "question"}), 201)
    # Steuerberater darf nicht weiter freigeben und keine Aufgaben zuweisen
    assert stb.post(f"/api/v1/objects/{beleg}/grants", json={"member": cw.public_id(cw.leser)}).status_code == 403
    assert stb.get(f"/api/v1/tasks/{refs['task']}").status_code == 404
    # Entzug wirkt sofort
    ok(admin.delete(f"/api/v1/objects/{beleg}/grants/{cw.public_id(cw.stb)}"), 204)
    assert stb.get(f"/api/v1/objects/{beleg}").status_code == 404
    assert ok(stb.get("/api/v1/activities"))["items"] == []


def test_zugewiesene_aufgabe_wird_fuer_eingeschraenkte_freigegeben(cw: CoreWorld) -> None:
    beleg = cw.raw_object(cw.a, "receipt", "Kassenbeleg", by=cw.admin_a)
    t = ok(cw.client(cw.admin_a).post(f"/api/v1/objects/{beleg}/tasks",
                                      json={"title": "Bitte prüfen", "assignee": cw.public_id(cw.stb)}), 201)
    sicht = ok(cw.client(cw.stb).get(f"/api/v1/tasks/{t['id']}"))
    assert sicht["subject"] is None                       # Bezugsobjekt nicht automatisch sichtbar
    assert cw.client(cw.stb).get(f"/api/v1/objects/{beleg}").status_code == 404


def test_pausierte_firma_liest_aber_schreibt_nicht(cw: CoreWorld, engines: Engines) -> None:
    refs = _bestand(cw, cw.admin_a)
    with platform_transaction(engines.platform) as s:
        set_status(s, cw.a, "paused", actor="test", reason="Zahlungsverzug")
    c = cw.client(cw.admin_a)
    assert ok(c.get(f"/api/v1/tasks/{refs['task']}"))["id"] == refs["task"]
    for m, pfad, body in (("POST", "/api/v1/tasks", {"title": "x"}),
                          ("PATCH", f"/api/v1/tasks/{refs['task']}", {"status": "done"}),
                          ("POST", f"/api/v1/objects/{refs['task']}/comments", {"body": "x"}),
                          ("DELETE", f"/api/v1/comments/{refs['comment']}", {"reason": "pausiert?"}),
                          ("DELETE", f"/api/v1/links/{refs['link']}", None)):
        r = c.request(m, pfad, json=body)
        assert r.status_code == 403 and r.json()["code"] == "tenant_paused", (m, pfad, r.status_code)
    assert c.post("/api/v1/documents?filename=x.pdf", **PDF).json()["code"] == "tenant_paused"
