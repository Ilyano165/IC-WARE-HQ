"""Benachrichtigungen (Rechte beim Zustellen und Lesen), Suche, Aktivität ≠ Audit."""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import tenant_transaction
from ichq.notifications import handlers
from ichq.notifications.service import KINDS, deliver
from ichq.objects.service import by_id
from tests.auth_helpers import db
from tests.conftest import World
from tests.core_helpers import CoreWorld, ok, run_worker


@pytest.fixture
def cw(world: World, engines: Engines, settings: Settings) -> CoreWorld:
    return CoreWorld(world, engines, settings)


def _inbox(cw: CoreWorld, mid: object) -> list[dict]:  # type: ignore[type-arg]
    return list(ok(cw.client(mid).get("/api/v1/notifications"))["items"])  # type: ignore[arg-type]


# ---------- Benachrichtigungen ----------
def test_erwaehnung_benachrichtigt_nur_wer_das_objekt_sehen_darf(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.admin_a)
    t = ok(c.post("/api/v1/tasks", json={"title": "Jahresabschluss"}), 201)
    ok(c.post(f"/api/v1/objects/{t['id']}/comments",
              json={"body": "Bitte beide ansehen", "mentions": [cw.public_id(cw.leser), cw.public_id(cw.stb)]}), 201)
    assert _inbox(cw, cw.leser) == [] and _inbox(cw, cw.stb) == []          # erst der Worker stellt zu
    r = run_worker(engines)
    assert r.ok and r.claimed >= 1
    leser = _inbox(cw, cw.leser)
    assert [(n["kind"], n["object"]["id"]) for n in leser] == [("comment.mention", t["id"])]
    assert "Jahresabschluss" in leser[0]["title"]
    assert _inbox(cw, cw.stb) == []                                           # sieht die Aufgabe nicht → nichts
    assert db(engines, "SELECT count(*) FROM notifications WHERE recipient_membership_id = %s", (cw.stb,))[0][0] == 0
    run_worker(engines)                                                       # kein Doppel
    assert len(_inbox(cw, cw.leser)) == 1


def test_rueckfrage_des_steuerberaters_erreicht_den_ersteller(cw: CoreWorld, engines: Engines) -> None:
    beleg = cw.raw_object(cw.a, "receipt", "Bewirtung 12.09.", by=cw.admin_a)
    ok(cw.client(cw.admin_a).post(f"/api/v1/objects/{beleg}/grants", json={"member": cw.public_id(cw.stb)}), 201)
    ok(cw.client(cw.stb).post(f"/api/v1/objects/{beleg}/comments",
                              json={"body": "Teilnehmer fehlen", "kind": "question"}), 201)
    run_worker(engines)
    n = _inbox(cw, cw.admin_a)
    assert [(x["kind"], x["title"]) for x in n] == [("comment.question", "Rückfrage zu: Bewirtung 12.09.")]
    assert "Teilnehmer" not in str(n)                                          # kein Kommentartext in der Benachr.


def test_zuweisung_und_beleg_wartet_auf_pruefung(cw: CoreWorld, engines: Engines) -> None:
    ok(cw.client(cw.admin_a).post("/api/v1/tasks", json={"title": "Kasse zählen",
                                                          "assignee": cw.public_id(cw.mitarbeiter)}), 201)
    ok(cw.client(cw.mitarbeiter).post("/api/v1/documents?filename=q.pdf", content=b"%PDF",
                                      headers={"content-type": "application/pdf"}), 201)
    run_worker(engines)
    assert {n["kind"] for n in _inbox(cw, cw.mitarbeiter)} == {"task.assigned"}       # Uploader selbst nicht
    assert {n["kind"] for n in _inbox(cw, cw.admin_a)} == {"document.review_pending"}  # hat files.update
    assert _inbox(cw, cw.leser) == []                                                  # kein files.update


def test_rechteentzug_nach_zustellung_blendet_aus(cw: CoreWorld, engines: Engines) -> None:
    beleg = cw.raw_object(cw.a, "receipt", "Hotel Berlin", by=cw.admin_a)
    ok(cw.client(cw.admin_a).post(f"/api/v1/objects/{beleg}/grants", json={"member": cw.public_id(cw.stb)}), 201)
    with tenant_transaction(engines.app, cw.a) as s:
        assert deliver(s, cw.stb, "comment.question", title="Hotel Berlin", obj=by_id(s, _id(engines, beleg)))
    assert len(_inbox(cw, cw.stb)) == 1
    ok(cw.client(cw.admin_a).delete(f"/api/v1/objects/{beleg}/grants/{cw.public_id(cw.stb)}"), 204)
    assert _inbox(cw, cw.stb) == []
    r = ok(cw.client(cw.stb).get("/api/v1/notifications"))
    assert r["items"] == [] and r["unread_count"] == 0                     # auch der Zähler verrät nichts


def _id(engines: Engines, public_id: str) -> object:
    return db(engines, "SELECT id FROM objects WHERE public_id = %s", (public_id,))[0][0]


def test_zustellung_prueft_mitgliedschaft_und_art(cw: CoreWorld, engines: Engines) -> None:
    t = cw.raw_object(cw.a, "task", "x", by=cw.admin_a)
    leo = cw._mitglied(cw.a, "leo@alpha.test", "Leo Leser", ["tasks.read", "objects.read_all", "comments.read"])
    db(engines, "UPDATE memberships SET status = 'suspended' WHERE id = %s", (cw.leser,))
    with tenant_transaction(engines.app, cw.a) as s:
        obj = by_id(s, _id(engines, t))
        assert deliver(s, cw.leser, "task.assigned", title="x", obj=obj) is False        # gesperrt
        assert deliver(s, cw.ohne, "task.assigned", title="x", obj=obj) is False         # kein tasks.read
        # Leser SIEHT das Objekt (tasks.read + read_all), hat aber nicht das Recht der Art (files.update)
        assert deliver(s, leo, "document.review_pending", title="x", obj=obj) is False
        assert deliver(s, cw.ohne, "comment.mention", title="ohne Objekt") is False      # kein comments.read
        assert deliver(s, cw.admin_b, "task.assigned", title="x", obj=obj) is False      # fremde Firma
        assert deliver(s, cw.admin_a, "task.assigned", title="x", obj=obj, dedup_key="k") is True
        assert deliver(s, cw.admin_a, "task.assigned", title="x", obj=obj, dedup_key="k") is False
        with pytest.raises(ValueError):
            deliver(s, cw.admin_a, "erfunden.art", title="x")
    assert set(KINDS) >= {"document.review_pending", "invoice.overdue", "comment.question", "contract.expiring"}


def test_lesen_nur_eigene_benachrichtigungen(cw: CoreWorld, engines: Engines) -> None:
    t = cw.raw_object(cw.a, "task", "x", by=cw.admin_a)
    with tenant_transaction(engines.app, cw.a) as s:
        deliver(s, cw.admin_a, "task.assigned", title="für admin", obj=by_id(s, _id(engines, t)))
    n = _inbox(cw, cw.admin_a)[0]
    assert cw.client(cw.mitarbeiter).post(f"/api/v1/notifications/{n['id']}/read").status_code == 404
    assert _inbox(cw, cw.admin_a)[0]["read"] is False
    ok(cw.client(cw.admin_a).post(f"/api/v1/notifications/{n['id']}/read"), 204)
    r = ok(cw.client(cw.admin_a).get("/api/v1/notifications?unread=true"))
    assert r["items"] == [] and r["unread_count"] == 0


def test_ueberfaellige_aufgaben_regel(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.admin_a)
    ok(c.post("/api/v1/tasks", json={"title": "Alt", "due_date": "2026-01-01", "assignee": cw.public_id(cw.leser)}), 201)
    ok(c.post("/api/v1/tasks", json={"title": "Neu", "due_date": "2027-01-01", "assignee": cw.public_id(cw.leser)}), 201)
    with tenant_transaction(engines.app, cw.a) as s:
        assert handlers.scan(s, date(2026, 10, 8)) == {"task.overdue": 1}
        assert handlers.scan(s, date(2026, 10, 8)) == {"task.overdue": 0}          # dedup je Fälligkeit
    assert [n["title"] for n in _inbox(cw, cw.leser) if n["kind"] == "task.overdue"] == ["Überfällig: Alt"]


# ---------- Suche ----------
def test_suche_gruppiert_praefix_und_rechte(cw: CoreWorld) -> None:
    for typ, titel in (("customer", "Müller Bau GmbH"), ("supplier", "Müllerei Nord"), ("project", "Website Müller"),
                       ("receipt", "Tankbeleg Müller"), ("invoice", "Rechnung Müller 2026-17"),
                       ("contract", "Wartungsvertrag Müller"), ("employee", "Jens Müller")):
        cw.raw_object(cw.a, typ, titel, by=cw.admin_a)
    ok(cw.client(cw.admin_a).post("/api/v1/tasks", json={"title": "Müller anrufen"}), 201)
    g = ok(cw.client(cw.admin_a).get("/api/v1/search?q=müll"))["groups"]
    assert set(g) == {"persons", "companies", "projects", "receipts", "invoices", "tasks", "documents"}
    assert {i["title"] for i in g["companies"]["items"]} == {"Müller Bau GmbH", "Müllerei Nord"}
    assert [i["title"] for i in g["documents"]["items"]] == ["Wartungsvertrag Müller"]
    assert [i["title"] for i in g["tasks"]["items"]] == ["Müller anrufen"]
    assert [i["title"] for i in g["persons"]["items"]] == ["Jens Müller"]
    m = ok(cw.client(cw.mitarbeiter).get("/api/v1/search?q=müll"))["groups"]
    assert m["documents"]["items"] == []                                  # kein contracts.read
    assert len(ok(cw.client(cw.admin_a).get("/api/v1/search?q=Müller&per_group=1"))["groups"]["companies"]
               ["items"]) == 1
    assert ok(cw.client(cw.admin_a).get("/api/v1/search?q=Müller&per_group=1"))["groups"]["companies"]["has_more"]
    personen = ok(cw.client(cw.admin_a).get("/api/v1/search?q=Steuerberaterin"))["groups"]["persons"]["items"]
    assert [(p["type"], p["title"]) for p in personen] == [("member", "Sabine Steuerberaterin")]


@pytest.mark.parametrize("q", ["a' & b", "x:*|y", "!(", "%_\\", "'); DROP TABLE objects; --", "ü" * 100])
def test_suche_mit_sonderzeichen_ist_sicher(cw: CoreWorld, q: str) -> None:
    r = cw.client(cw.admin_a).get("/api/v1/search", params={"q": q})
    assert r.status_code in (200, 422), r.text
    assert cw.client(cw.admin_a).get("/api/v1/search", params={"q": "x"}).status_code == 422


# ---------- Aktivität ≠ Audit ----------
def test_aktivitaet_und_audit_sind_getrennt(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.admin_a)
    t = ok(c.post("/api/v1/tasks", json={"title": "Gehaltsliste", "description": "vertraulich 4.200 EUR"}), 201)
    ok(c.patch(f"/api/v1/tasks/{t['id']}", json={"status": "in_progress"}), 200)
    ok(c.post(f"/api/v1/objects/{t['id']}/comments", json={"body": "Sehr geheimer Text"}), 201)
    feed = ok(c.get(f"/api/v1/objects/{t['id']}/activities?order=asc"))["items"]
    assert [a["verb"] for a in feed] == ["task.created", "task.status_changed", "comment.created"]
    assert feed[1]["data"] == {"from": "open", "to": "in_progress"} and feed[0]["actor"]["display_name"]
    audit = ok(c.get(f"/api/v1/audit?target_id={t['id']}"))["items"]
    assert {a["action"] for a in audit} == {"task.created", "task.updated", "comment.created"}
    gesamt = str(feed) + str(audit) + str(db(engines, "SELECT data FROM audit_events")) + \
        str(db(engines, "SELECT data FROM activities"))
    assert "geheimer" not in gesamt and "4.200" not in gesamt                # keine Inhalte/Beträge
    # Leser sieht Aktivität, aber nicht das Audit
    assert len(ok(cw.client(cw.leser).get("/api/v1/activities"))["items"]) == 3
    assert cw.client(cw.leser).get("/api/v1/audit").status_code == 403


def test_audit_ist_unveraenderbar(cw: CoreWorld, engines: Engines) -> None:
    ok(cw.client(cw.admin_a).post("/api/v1/tasks", json={"title": "x"}), 201)
    for sql in ("UPDATE audit_events SET action = 'harmlos'", "DELETE FROM audit_events", "TRUNCATE audit_events"):
        with pytest.raises(ProgrammingError), tenant_transaction(engines.app, cw.a) as s:
            s.execute(text(sql))
    # Auch der Tabellenbesitzer kann nicht ändern (Trigger)
    from tests.conftest import _admin
    with _admin(engines.app.url.database) as conn, pytest.raises(Exception, match="nur anhängend"):
        conn.execute("UPDATE audit_events SET action = 'harmlos'")
    # Es gibt keine Route, die Audit ändert oder löscht
    from ichq.api.security import iter_api_routes
    from ichq.app import create_app
    app = create_app(cw.settings, engines=engines)
    schreibend = [(p, m) for p, m, _ in iter_api_routes(app) if p.startswith("/api/v1/audit")
                  and m & {"POST", "PUT", "PATCH", "DELETE"}]
    assert schreibend == []


def test_aktivitaeten_feed_paginierung_und_filter(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    for i in range(30):
        ok(c.post("/api/v1/tasks", json={"title": f"T{i}"}), 201)
    erste = ok(c.get("/api/v1/activities?limit=20"))
    zweite = ok(c.get(f"/api/v1/activities?limit=20&cursor={erste['next_cursor']}"))
    assert len(erste["items"]) == 20 and len(zweite["items"]) == 10 and zweite["next_cursor"] is None
    zeiten = [a["occurred_at"] for a in erste["items"] + zweite["items"]]
    assert zeiten == sorted(zeiten, reverse=True)
    assert ok(c.get("/api/v1/activities?verb=comment.created"))["items"] == []
    assert c.get("/api/v1/activities?verb=erfunden.verb").status_code == 422
    assert c.get("/api/v1/activities?object_type=raumschiff").status_code == 422
    mich = ok(c.get(f"/api/v1/activities?actor={cw.public_id(cw.admin_a)}&limit=100"))["items"]
    assert len(mich) == 30
