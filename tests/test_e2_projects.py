"""E2 Projekte (ADR-020): Stammdaten, Status, Team mit automatischer Freigabe, Kostensätze, Projektzeiten,
Aufgabenbezug, Filter, Rechte, Isolation."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import tenant_transaction
from ichq.objects.service import create_object
from tests.auth_helpers import db
from tests.conftest import World
from tests.core_helpers import CoreWorld, ok

TEAM = ["projects.read", "tasks.read", "tasks.create"]           # ohne objects.read_all


@pytest.fixture
def cw(world: World, engines: Engines, settings: Settings) -> CoreWorld:
    return CoreWorld(world, engines, settings)


def _projekt(c, name: str = "Dachsanierung", **extra):  # type: ignore[no-untyped-def]
    return ok(c.post("/api/v1/projects", json={"name": name, **extra}), 201)


def test_projekt_anlegen_status_zeitraum_budget(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    kunde = ok(c.post("/api/v1/customers", json={"name": "Bauherr GmbH"}), 201)
    p = _projekt(c, customer=kunde["id"], start_date="2026-10-01", end_date="2026-12-31", budget_minor=1_500_000,
                 priority="high", owner=cw.public_id(cw.admin_a), description="Ziegel tauschen")
    assert (p["status"], p["currency"], p["budget_minor"], p["customer"]["id"]) == ("planned", "EUR", 1_500_000,
                                                                                   kunde["id"])
    assert [t["member"]["id"] for t in p["team"]] == [cw.public_id(cw.admin_a)]      # Leitung ist im Team
    assert c.post("/api/v1/projects", json={"name": "X", "start_date": "2026-10-02",
                                            "end_date": "2026-10-01"}).status_code == 422
    assert c.patch(f"/api/v1/projects/{p['id']}", json={"end_date": "2026-09-01"}).status_code == 422
    assert c.post("/api/v1/projects", json={"name": "X", "budget_minor": -1}).status_code == 422
    fertig = ok(c.patch(f"/api/v1/projects/{p['id']}", json={"status": "completed"}))
    assert fertig["completed_at"] is not None
    assert ok(c.patch(f"/api/v1/projects/{p['id']}", json={"status": "active"}))["completed_at"] is None
    verben = [a["verb"] for a in ok(c.get(f"/api/v1/objects/{p['id']}/activities"))["items"]]
    assert verben.count("project.status_changed") == 2 and "project.member_added" in verben
    # Projekte erscheinen beim Kunden (Filter)
    assert [x["id"] for x in ok(c.get(f"/api/v1/projects?customer={kunde['id']}"))["items"]] == [p["id"]]


def test_filter_suche_sortierung(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    a = _projekt(c, "Alpha Website", end_date="2026-11-30", status="active")
    b = _projekt(c, "Beta Umzug", end_date="2026-10-15", status="on_hold")
    _projekt(c, "Gamma Abgeschlossen", status="cancelled")
    nach_ende = ok(c.get("/api/v1/projects?status=active&status=on_hold&sort=end_date"))["items"]
    assert [x["id"] for x in nach_ende] == [b["id"], a["id"]]
    assert [x["id"] for x in ok(c.get("/api/v1/projects?q=umzug"))["items"]] == [b["id"]]
    assert ok(c.get("/api/v1/projects?member=me"))["items"] == []
    ok(c.put(f"/api/v1/projects/{a['id']}/members/{cw.public_id(cw.admin_a)}", json={"role": "Technik"}))
    assert [x["id"] for x in ok(c.get("/api/v1/projects?member=me"))["items"]] == [a["id"]]
    assert c.get("/api/v1/projects?status=fertig").status_code == 422


def test_team_freigabe_kommt_und_geht(cw: CoreWorld) -> None:
    """Ohne objects.read_all sieht ein Teammitglied das Projekt nur, solange es im Team ist."""
    team = cw._mitglied(cw.a, "team@alpha.test", "Tim Team", TEAM)
    admin, t = cw.client(cw.admin_a), cw.client(team)
    p = _projekt(admin)
    assert t.get(f"/api/v1/projects/{p['id']}").status_code == 404
    ok(admin.put(f"/api/v1/projects/{p['id']}/members/{cw.public_id(team)}", json={"role": "Montage"}))
    assert ok(t.get(f"/api/v1/projects/{p['id']}"))["name"] == "Dachsanierung"
    assert [x["id"] for x in ok(t.get("/api/v1/projects?member=me"))["items"]] == [p["id"]]
    quelle = db(cw.engines, "SELECT source FROM object_grants g JOIN objects o ON o.id = g.object_id "
                            "WHERE o.public_id = %s", (p["id"],))
    assert quelle == [("project_team",)]
    assert admin.delete(f"/api/v1/projects/{p['id']}/members/{cw.public_id(team)}").status_code == 204
    assert t.get(f"/api/v1/projects/{p['id']}").status_code == 404
    # Ohne projects.read nicht ins Team; Leitung nicht entfernbar
    assert admin.put(f"/api/v1/projects/{p['id']}/members/{cw.public_id(cw.ohne)}", json={}).status_code == 422
    leitung = _projekt(admin, "Mit Leitung", owner=cw.public_id(cw.admin_a))
    assert admin.delete(f"/api/v1/projects/{leitung['id']}/members/{cw.public_id(cw.admin_a)}").status_code == 409
    # Manuelle Freigabe bleibt, wenn die Teamfreigabe endet
    ok(admin.put(f"/api/v1/projects/{p['id']}/members/{cw.public_id(team)}", json={}))
    ok(admin.post(f"/api/v1/objects/{p['id']}/grants", json={"member": cw.public_id(team)}), 201)
    assert admin.delete(f"/api/v1/projects/{p['id']}/members/{cw.public_id(team)}").status_code == 204
    assert t.get(f"/api/v1/projects/{p['id']}").status_code == 200


def test_kostensaetze_nur_mit_finanzrecht(cw: CoreWorld) -> None:
    pl = cw._mitglied(cw.a, "pl@alpha.test", "Paula Projektleitung",
                      ["projects.read", "projects.create", "projects.update", "projects.assign", "objects.read_all"])
    admin, c = cw.client(cw.admin_a), cw.client(pl)
    p = _projekt(c)
    assert c.put(f"/api/v1/projects/{p['id']}/members/{cw.public_id(pl)}",
                 json={"hourly_cost_minor": 6500}).status_code == 403
    ok(c.put(f"/api/v1/projects/{p['id']}/members/{cw.public_id(pl)}", json={"role": "Leitung"}))
    ok(admin.put(f"/api/v1/projects/{p['id']}/members/{cw.public_id(pl)}", json={"hourly_cost_minor": 6500}))
    assert "hourly_cost_minor" not in ok(c.get(f"/api/v1/projects/{p['id']}"))["team"][0]
    assert ok(admin.get(f"/api/v1/projects/{p['id']}"))["team"][0]["hourly_cost_minor"] == 6500
    assert ok(admin.get(f"/api/v1/projects/{p['id']}"))["team"][0]["role"] == "Leitung"   # Rolle bleibt


def test_projektzeiten_rechte_und_summen(cw: CoreWorld) -> None:
    team = cw._mitglied(cw.a, "team@alpha.test", "Tim Team", TEAM)
    admin, t = cw.client(cw.admin_a), cw.client(team)
    p = _projekt(admin)
    zeit = {"work_date": "2026-10-05", "minutes": 90, "description": "Aufmaß"}
    ok(admin.put(f"/api/v1/projects/{p['id']}/members/{cw.public_id(team)}", json={}))
    eigen = ok(t.post(f"/api/v1/projects/{p['id']}/time-entries", json=zeit), 201)
    assert eigen["member"]["display_name"] == "Tim Team"
    # für andere nur mit projects.assign; nur für Teammitglieder
    assert t.post(f"/api/v1/projects/{p['id']}/time-entries",
                  json={**zeit, "member": cw.public_id(cw.admin_a)}).status_code == 403
    assert admin.post(f"/api/v1/projects/{p['id']}/time-entries",
                      json={**zeit, "member": cw.public_id(cw.leser)}).status_code == 422
    ok(admin.put(f"/api/v1/projects/{p['id']}/members/{cw.public_id(cw.admin_a)}", json={}))
    fremd = ok(admin.post(f"/api/v1/projects/{p['id']}/time-entries", json={**zeit, "minutes": 30, "billable": False}),
               201)
    assert t.post(f"/api/v1/projects/{p['id']}/time-entries", json={**zeit, "minutes": 0}).status_code == 422
    s = ok(admin.get(f"/api/v1/projects/{p['id']}"))["summary"]
    assert (s["minutes_total"], s["minutes_billable"]) == (120, 90)
    assert t.delete(f"/api/v1/projects/{p['id']}/time-entries/{fremd['id']}").status_code == 403
    assert t.delete(f"/api/v1/projects/{p['id']}/time-entries/{eigen['id']}").status_code == 204
    assert len(ok(admin.get(f"/api/v1/projects/{p['id']}/time-entries"))["items"]) == 1


def test_aufgaben_am_projekt(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    p = _projekt(c)
    ok(c.post(f"/api/v1/objects/{p['id']}/tasks", json={"title": "Gerüst bestellen"}), 201)
    erledigt = ok(c.post("/api/v1/tasks", json={"title": "Angebot", "subject": p["id"]}), 201)
    ok(c.patch(f"/api/v1/tasks/{erledigt['id']}", json={"status": "done"}))
    assert ok(c.get(f"/api/v1/projects/{p['id']}"))["summary"]["open_tasks"] == 1
    assert len(ok(c.get(f"/api/v1/tasks?subject={p['id']}&status=open&status=done"))["items"]) == 2


def test_rechte_und_isolation(cw: CoreWorld, engines: Engines) -> None:
    ma = cw.client(cw.mitarbeiter)                                   # projects.read, kein create/update/assign
    assert ma.post("/api/v1/projects", json={"name": "X"}).status_code == 403
    p = _projekt(cw.client(cw.admin_a))
    assert ma.patch(f"/api/v1/projects/{p['id']}", json={"name": "X"}).status_code == 403
    assert ma.put(f"/api/v1/projects/{p['id']}/members/{cw.public_id(cw.mitarbeiter)}", json={}).status_code == 403
    assert cw.client(cw.stb).get("/api/v1/projects").status_code == 403
    kb = ok(cw.client(cw.admin_b).post("/api/v1/customers", json={"name": "Beta Kunde"}), 201)
    assert cw.client(cw.admin_a).post("/api/v1/projects", json={"name": "X", "customer": kb["id"]}).status_code == 404
    kb_id = db(engines, "SELECT id FROM objects WHERE public_id = %s", (kb["id"],))[0][0]
    with pytest.raises(IntegrityError), tenant_transaction(engines.app, cw.a) as s:
        o = create_object(s, type_="project", title="Fremdkunde", actor_membership_id=None)
        s.execute(text("INSERT INTO projects(id, tenant_id, customer_id) VALUES (:i, :t, :k)"),
                  {"i": o.id, "t": cw.a, "k": kb_id})
    with tenant_transaction(engines.app, cw.b) as s:
        assert s.execute(text("SELECT count(*) FROM projects")).scalar_one() == 0
