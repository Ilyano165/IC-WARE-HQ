"""M4 — Entscheidungsreihenfolge (M0 „Rechte", ADR-011). Jede Stufe einzeln, jeweils so aufgebaut, dass die
spätere Stufe JA sagen würde: Nur wenn die frühere Stufe wirkt, ist das Ergebnis NEIN.
Die Erwartungen stehen hier ausgeschrieben, nicht aus dem Code gelesen."""
from __future__ import annotations

import pytest

from ichq.authz.flags import set_flag
from ichq.authz.registry import PERMISSIONS
from ichq.core.errors import ValidationFailed
from ichq.db.session import platform_transaction
from tests.auth_helpers import db
from tests.core_helpers import ok
from tests.m4_helpers import RbacWorld


def _flag(rw: RbacWorld, modul: str, an: bool) -> None:
    with platform_transaction(rw.engines.platform) as s:
        set_flag(s, rw.a, modul, an, actor="test", reason="Test")


def _entscheidung(rw: RbacWorld, mid: object, recht: str) -> dict[str, object]:
    eintraege = ok(rw.client(mid).get("/api/v1/me/permissions"))["permissions"]   # type: ignore[arg-type]
    return next(e for e in eintraege if e["permission"] == recht)


def test_1_feature_flag_schlaegt_company_admin_und_allow(rw: RbacWorld) -> None:
    c = rw.client(rw.admin)
    ok(c.put(f"/api/v1/members/{rw.pid(rw.ohne)}/overrides/tasks.read", json={"effect": "allow"}))
    _flag(rw, "tasks", False)
    r = c.get("/api/v1/tasks")
    assert r.status_code == 403 and r.json()["code"] == "feature_disabled"
    assert rw.client(rw.ohne).get("/api/v1/tasks").json()["code"] == "feature_disabled"      # ALLOW hilft nicht
    assert _entscheidung(rw, rw.admin, "tasks.read") == {
        "permission": "tasks.read", "granted": False, "decided_by": "feature_disabled",
        "roles": [{"id": rw.role_id("Company Admin"), "name": "Company Admin"}]}
    assert c.get("/api/v1/documents").status_code == 200                                 # nur das eine Modul
    _flag(rw, "tasks", True)
    assert c.get("/api/v1/tasks").status_code == 200


def test_1_kernmodule_und_unbekannte_module_nicht_abschaltbar(rw: RbacWorld) -> None:
    for modul in ("roles", "users", "company", "audit", "settings", "platform", "gibtsnicht"):
        with pytest.raises(ValidationFailed):
            _flag(rw, modul, False)
    assert db(rw.engines, "SELECT count(*) FROM tenant_feature_flags")[0][0] == 0
    # Zweite Sicherung: eine direkt geschriebene Flag-Zeile für ein Kernmodul wird ignoriert
    db(rw.engines, "INSERT INTO tenant_feature_flags(tenant_id, module, enabled, updated_by) "
                   "VALUES (%s, 'roles', false, 'direkt')", (rw.a,))
    assert "roles.assign" in rw.rechte(rw.admin) and rw.client(rw.admin).get("/api/v1/roles").status_code == 200


def test_1_flag_gilt_nur_fuer_die_eigene_firma(rw: RbacWorld) -> None:
    _flag(rw, "tasks", False)
    assert rw.client(rw.admin_b).get("/api/v1/tasks").status_code == 200


def test_2_einzelrecht_deny_schlaegt_rolle(rw: RbacWorld) -> None:
    assert rw.client(rw.ma).get("/api/v1/tasks").status_code == 200                       # Mitarbeiter-Rolle
    ok(rw.client(rw.admin).put(f"/api/v1/members/{rw.pid(rw.ma)}/overrides/tasks.read", json={"effect": "deny"}))
    assert rw.client(rw.ma).get("/api/v1/tasks").status_code == 403                       # sofort, ohne Login
    e = _entscheidung(rw, rw.ma, "tasks.read")
    assert e["decided_by"] == "deny" and e["granted"] is False and e["roles"]             # Rolle hätte es gegeben


def test_2_deny_schlaegt_auch_company_admin(rw: RbacWorld) -> None:
    zweit = rw.mitglied("zweit@alpha.test", "Company Admin")
    ok(rw.client(rw.admin).put(f"/api/v1/members/{rw.pid(zweit)}/overrides/audit.read", json={"effect": "deny"}))
    assert "audit.read" not in rw.rechte(zweit) and rw.rechte(zweit) == PERMISSIONS - {"audit.read"}
    assert rw.client(zweit).get("/api/v1/audit").status_code == 403


def test_4_allow_ohne_rolle(rw: RbacWorld) -> None:
    assert rw.client(rw.ohne).get("/api/v1/tasks").status_code == 403
    ok(rw.client(rw.admin).put(f"/api/v1/members/{rw.pid(rw.ohne)}/overrides/tasks.read", json={"effect": "allow"}))
    assert rw.client(rw.ohne).get("/api/v1/tasks").status_code == 200
    assert _entscheidung(rw, rw.ohne, "tasks.read") == {"permission": "tasks.read", "granted": True,
                                                        "decided_by": "allow", "roles": []}


def test_3_ressourcen_deny_schlaegt_read_all_freigabe_und_erstellerschaft(rw: RbacWorld) -> None:
    admin, gf, ma = rw.client(rw.admin), rw.client(rw.gf), rw.client(rw.ma)
    eigene = ok(ma.post("/api/v1/tasks", json={"title": "Von Max angelegt"}), 201)["id"]
    fremde = ok(admin.post("/api/v1/tasks", json={"title": "Für Max freigegeben"}), 201)["id"]
    ok(admin.post(f"/api/v1/objects/{fremde}/grants", json={"member": rw.pid(rw.ma)}), 201)
    vorher = ma.get("/api/v1/search?q=Max&per_group=20").text
    assert eigene in vorher and fremde in vorher                                        # Gegenprobe
    for ref in (eigene, fremde):
        assert ma.get(f"/api/v1/tasks/{ref}").status_code == 200
        ok(admin.put(f"/api/v1/objects/{ref}/denies/{rw.pid(rw.ma)}"))
        assert ma.get(f"/api/v1/tasks/{ref}").status_code == 404                        # Erstellerschaft/Freigabe
    assert ma.get("/api/v1/tasks?limit=100").json()["items"] == []
    treffer = ma.get("/api/v1/search?q=Max&per_group=20").text
    assert eigene not in treffer and fremde not in treffer
    assert gf.get(f"/api/v1/tasks/{fremde}").status_code == 200                        # GF: read_all
    ok(admin.put(f"/api/v1/objects/{fremde}/denies/{rw.pid(rw.gf)}"))
    assert gf.get(f"/api/v1/tasks/{fremde}").status_code == 404                        # read_all hilft nicht
    assert gf.get(f"/api/v1/objects/{fremde}").status_code == 404
    ok(admin.delete(f"/api/v1/objects/{fremde}/denies/{rw.pid(rw.gf)}"), 204)
    assert gf.get(f"/api/v1/tasks/{fremde}").status_code == 200
    gesperrt = ok(admin.get(f"/api/v1/objects/{eigene}/denies"))["items"]
    assert [m["id"] for m in gesperrt] == [rw.pid(rw.ma)]


def test_3_gesperrte_person_kann_nicht_zugewiesen_werden(rw: RbacWorld) -> None:
    admin = rw.client(rw.admin)
    t = ok(admin.post("/api/v1/tasks", json={"title": "Gesperrt"}), 201)["id"]
    ok(admin.put(f"/api/v1/objects/{t}/denies/{rw.pid(rw.ma)}"))
    r = admin.patch(f"/api/v1/tasks/{t}", json={"assignee": rw.pid(rw.ma)})
    assert r.status_code in (400, 422) and "gesperrt" in r.text
    assert rw.client(rw.ma).get(f"/api/v1/tasks/{t}").status_code == 404


def test_5_freigabe_ohne_read_all(rw: RbacWorld) -> None:
    admin, ma = rw.client(rw.admin), rw.client(rw.ma)
    t = ok(admin.post("/api/v1/tasks", json={"title": "Nur für Max"}), 201)["id"]
    assert ma.get(f"/api/v1/tasks/{t}").status_code == 404                             # Mitarbeiter: ohne read_all
    ok(admin.post(f"/api/v1/objects/{t}/grants", json={"member": rw.pid(rw.ma)}), 201)
    assert ma.get(f"/api/v1/tasks/{t}").status_code == 200


def test_6_rolle_und_company_admin_berechnet(rw: RbacWorld) -> None:
    assert rw.rechte(rw.admin) == PERMISSIONS
    assert db(rw.engines, "SELECT count(*) FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
                          "WHERE r.grants_all")[0][0] == 0                                 # nichts gespeichert
    assert "finance.read" in rw.rechte(rw.gf) and "roles.assign" not in rw.rechte(rw.gf)
    assert _entscheidung(rw, rw.gf, "finance.read")["decided_by"] == "role"


def test_6_archivierte_rolle_wirkt_nicht(rw: RbacWorld) -> None:
    ok(rw.client(rw.admin).post(f"/api/v1/roles/{rw.role_id('Mitarbeiter')}/archive"))
    assert rw.rechte(rw.ma) == frozenset()
    assert rw.client(rw.ma).get("/api/v1/tasks").status_code == 403


def test_7_sonst_nein(rw: RbacWorld) -> None:
    assert rw.rechte(rw.ohne) == frozenset()
    e = _entscheidung(rw, rw.ohne, "tasks.read")
    assert e == {"permission": "tasks.read", "granted": False, "decided_by": "none", "roles": []}
    assert len(ok(rw.client(rw.ohne).get("/api/v1/me/permissions"))["permissions"]) == len(PERMISSIONS)
