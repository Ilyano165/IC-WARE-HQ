"""Entschiedene C0-Nachträge: eigene Rechte je Objekttyp, Freigabe an Zuweisung gebunden, Kommentar-Tombstones."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from ichq.authz.registry import PERMISSIONS
from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import tenant_transaction
from ichq.objects.registry import OBJECT_TYPES
from tests.auth_helpers import db
from tests.conftest import World, _admin
from tests.core_helpers import CoreWorld, ok


@pytest.fixture
def cw(world: World, engines: Engines, settings: Settings) -> CoreWorld:
    return CoreWorld(world, engines, settings)


# ---------- 3a: eigene Rechte ----------
@pytest.mark.parametrize(("typ", "lesen", "aendern"), [
    ("trip", "vehicles.read", "vehicles.update"), ("travel", "travel.read", "travel.update"),
    ("entertainment", "hospitality.read", "hospitality.update"), ("supplier", "suppliers.read", "suppliers.update")])
def test_eigene_rechte_je_objekttyp(typ: str, lesen: str, aendern: str) -> None:
    assert (OBJECT_TYPES[typ].read, OBJECT_TYPES[typ].update) == (lesen, aendern)
    assert {lesen, aendern} <= PERMISSIONS


@pytest.mark.parametrize(("typ", "recht"), [("trip", "vehicles.read"), ("travel", "travel.read"),
                                            ("entertainment", "hospitality.read"), ("supplier", "suppliers.read")])
def test_finance_oder_customers_reicht_nicht_mehr(cw: CoreWorld, typ: str, recht: str) -> None:
    ref = cw.raw_object(cw.a, typ, f"Objekt {typ}", by=cw.admin_a)
    # Mitarbeiter hat finance.read + customers.read + objects.read_all, aber nicht das neue Recht
    assert cw.client(cw.mitarbeiter).get(f"/api/v1/objects/{ref}").status_code == 404
    rolle = cw.w.role(cw.a, f"nur {recht}", [recht, "objects.read_all"])
    cw.w.assign(cw.a, cw.leser, rolle)
    assert ok(cw.client(cw.leser).get(f"/api/v1/objects/{ref}"))["type"] == typ


# ---------- 3b: Freigabe an aktuelle Zuweisung gebunden ----------
def _quellen(engines: Engines, task: str, mid: object) -> set[str]:
    return {r[0] for r in db(engines, "SELECT g.source FROM object_grants g JOIN objects o ON o.id = g.object_id "
                                      "WHERE o.public_id = %s AND g.membership_id = %s", (task, mid))}


def test_neuzuweisung_entzieht_nur_die_automatische_freigabe(cw: CoreWorld, engines: Engines) -> None:
    admin = cw.client(cw.admin_a)
    zweiter_stb = cw._mitglied(cw.a, "stb2@kanzlei.test", "Zweite Kanzlei", ["tasks.read", "comments.read"])
    t = ok(admin.post("/api/v1/tasks", json={"title": "Belege Q3", "assignee": cw.public_id(cw.stb)}), 201)
    assert _quellen(engines, t["id"], cw.stb) == {"task_assignment"}
    assert cw.client(cw.stb).get(f"/api/v1/tasks/{t['id']}").status_code == 200
    ok(admin.patch(f"/api/v1/tasks/{t['id']}", json={"assignee": cw.public_id(zweiter_stb)}))
    assert _quellen(engines, t["id"], cw.stb) == set()
    assert cw.client(cw.stb).get(f"/api/v1/tasks/{t['id']}").status_code == 404
    assert _quellen(engines, t["id"], zweiter_stb) == {"task_assignment"}
    # Zuweisung entfernen → auch die neue automatische Freigabe ist weg
    ok(admin.patch(f"/api/v1/tasks/{t['id']}", json={"assignee": None}))
    assert _quellen(engines, t["id"], zweiter_stb) == set()


def test_manuelle_freigabe_ueberlebt_neuzuweisung(cw: CoreWorld, engines: Engines) -> None:
    admin = cw.client(cw.admin_a)
    t = ok(admin.post("/api/v1/tasks", json={"title": "Belege Q4", "assignee": cw.public_id(cw.stb)}), 201)
    ok(admin.post(f"/api/v1/objects/{t['id']}/grants", json={"member": cw.public_id(cw.stb)}), 201)
    assert _quellen(engines, t["id"], cw.stb) == {"task_assignment", "manual"}
    freigaben = ok(admin.get(f"/api/v1/objects/{t['id']}/grants"))["items"]
    assert {(f["display_name"], f["source"]) for f in freigaben} == {
        ("Sabine Steuerberaterin", "task_assignment"), ("Sabine Steuerberaterin", "manual")}
    ok(admin.patch(f"/api/v1/tasks/{t['id']}", json={"assignee": cw.public_id(cw.mitarbeiter)}))
    assert _quellen(engines, t["id"], cw.stb) == {"manual"}
    assert cw.client(cw.stb).get(f"/api/v1/tasks/{t['id']}").status_code == 200       # manuell bleibt
    # Manuellen Entzug gibt es; die automatische Freigabe lässt sich über die API nicht „wegrevoken"
    ok(admin.delete(f"/api/v1/objects/{t['id']}/grants/{cw.public_id(cw.stb)}"), 204)
    assert cw.client(cw.stb).get(f"/api/v1/tasks/{t['id']}").status_code == 404


def test_api_entzug_laesst_automatische_freigabe_stehen(cw: CoreWorld, engines: Engines) -> None:
    admin = cw.client(cw.admin_a)
    t = ok(admin.post("/api/v1/tasks", json={"title": "Zuweisung", "assignee": cw.public_id(cw.stb)}), 201)
    r = admin.delete(f"/api/v1/objects/{t['id']}/grants/{cw.public_id(cw.stb)}")
    assert r.status_code == 404                                   # keine manuelle Freigabe vorhanden
    assert cw.client(cw.stb).get(f"/api/v1/tasks/{t['id']}").status_code == 200


def test_zuweisung_an_read_all_erzeugt_keine_freigabe(cw: CoreWorld, engines: Engines) -> None:
    t = ok(cw.client(cw.admin_a).post("/api/v1/tasks", json={"title": "x", "assignee": cw.public_id(cw.leser)}),
           201)
    assert _quellen(engines, t["id"], cw.leser) == set()


# ---------- 3c: Kommentar-Tombstones ----------
def _kommentar(cw: CoreWorld) -> tuple[str, str]:
    c = cw.client(cw.mitarbeiter)
    t = ok(c.post("/api/v1/tasks", json={"title": "Rückfrage"}), 201)
    k = ok(c.post(f"/api/v1/objects/{t['id']}/comments", json={"body": "Erste Fassung"}), 201)
    ok(c.patch(f"/api/v1/comments/{k['id']}", json={"body": "Zweite Fassung"}))
    return t["id"], k["id"]


def test_loeschen_ist_tombstone_mit_wer_wann_grund(cw: CoreWorld, engines: Engines) -> None:
    t, k = _kommentar(cw)
    c = cw.client(cw.mitarbeiter)
    assert c.request("DELETE", f"/api/v1/comments/{k}").status_code == 422          # Grund fehlt
    assert c.request("DELETE", f"/api/v1/comments/{k}", json={"reason": "x"}).status_code == 422
    ok(c.request("DELETE", f"/api/v1/comments/{k}", json={"reason": "Versehentlich doppelt gepostet"}), 204)
    sicht = ok(c.get(f"/api/v1/objects/{t}/comments"))["items"][0]
    assert sicht["deleted"] is True and sicht["body"] is None
    assert sicht["deleted_by"]["display_name"] == "Max Mitarbeiter" and sicht["deleted_at"]
    assert sicht["delete_reason"] == "Versehentlich doppelt gepostet"
    assert db(engines, "SELECT count(*) FROM comments WHERE public_id = %s", (k,))[0][0] == 1   # nicht physisch


def test_historie_bleibt_und_ist_nur_fuer_pruefer(cw: CoreWorld) -> None:
    _t, k = _kommentar(cw)
    ok(cw.client(cw.mitarbeiter).request("DELETE", f"/api/v1/comments/{k}", json={"reason": "veraltet"}), 204)
    assert cw.client(cw.mitarbeiter).get(f"/api/v1/comments/{k}/revisions").status_code == 403  # kein audit.read
    h = ok(cw.client(cw.admin_a).get(f"/api/v1/comments/{k}/revisions"))["items"]
    assert [(r["kind"], r["body"], r["reason"]) for r in h] == [
        ("created", "Erste Fassung", None), ("edited", "Zweite Fassung", None), ("deleted", "Zweite Fassung", "veraltet")]
    assert all(r["actor"]["display_name"] == "Max Mitarbeiter" for r in h)


def test_historie_ist_unveraenderbar(cw: CoreWorld, engines: Engines) -> None:
    _, _k = _kommentar(cw)
    for sql in ("UPDATE comment_revisions SET body = 'gefälscht'", "DELETE FROM comment_revisions",
                "INSERT INTO comment_revisions(tenant_id, comment_id, kind, body) "
                "SELECT tenant_id, comment_id, 'edited', 'eingeschleust' FROM comment_revisions LIMIT 1"):
        with pytest.raises(ProgrammingError), tenant_transaction(engines.app, cw.a) as s:
            s.execute(text(sql))
    with _admin(engines.app.url.database) as conn, pytest.raises(Exception, match="nur anhängend"):
        conn.execute("UPDATE comment_revisions SET body = 'gefälscht'")


def test_geloeschter_kommentar_ist_eingefroren(cw: CoreWorld, engines: Engines) -> None:
    _, k = _kommentar(cw)
    ok(cw.client(cw.mitarbeiter).request("DELETE", f"/api/v1/comments/{k}", json={"reason": "weg damit"}), 204)
    for sql in ("UPDATE comments SET body = 'wieder da', deleted_at = NULL",
                "UPDATE comments SET delete_reason = 'anderer Grund'"):
        with pytest.raises(DBAPIError, match="unveränderlich"), tenant_transaction(engines.app, cw.a) as s:
            s.execute(text(sql))
    n = db(engines, "SELECT count(*) FROM comment_revisions r JOIN comments c ON c.id = r.comment_id "
                    "WHERE c.public_id = %s", (k,))[0][0]
    assert n == 3


def test_historie_entsteht_auch_ohne_service(cw: CoreWorld, engines: Engines) -> None:
    """Die Datenbank schreibt die Historie selbst — auch ein direktes UPDATE der App-Rolle hinterlässt eine Fassung."""
    _, k = _kommentar(cw)
    with tenant_transaction(engines.app, cw.a) as s:
        s.execute(text("UPDATE comments SET body = 'heimlich geändert' WHERE public_id = :k"), {"k": k})
    koerper = [r[0] for r in db(engines, "SELECT r.body FROM comment_revisions r JOIN comments c ON c.id = r.comment_id"
                                         " WHERE c.public_id = %s ORDER BY r.seq", (k,))]
    assert koerper == ["Erste Fassung", "Zweite Fassung", "heimlich geändert"]
