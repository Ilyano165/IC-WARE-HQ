"""M4 — Szenarien aus dem Prototyp-Bericht (Abschnitt 6): Rechteausweitung, Rollenmanipulation,
Einzelrechte-Missbrauch, Admin-Eskalation, Bypass, Rollenlöschung. Letzter Admin und Mandantengrenzen:
test_m4_boundaries.py."""
from __future__ import annotations

from tests.core_helpers import ok
from tests.m4_helpers import RbacWorld

VERWALTER = {"roles.read", "roles.create", "roles.update", "roles.delete", "roles.assign", "users.read",
             "users.override", "tasks.read", "tasks.create"}


def _verwalter(rw: RbacWorld, rang: int = 50) -> tuple[object, object]:
    rw.rolle("Verwalter", rang, VERWALTER)
    v = rw.mitglied("verwalter@alpha.test", "Verwalter")
    return v, rw.client(v)


# ---------- Rechteausweitung ----------
def test_ohne_rollenrecht_keine_rollenverwaltung(rw: RbacWorld) -> None:
    gf = rw.client(rw.gf)                                     # Geschäftsführung: alles außer Rechteverwaltung
    assert gf.get("/api/v1/roles").status_code == 200
    for m, pfad, body in (("POST", "/api/v1/roles", {"name": "X", "rank": 10, "permissions": []}),
                          ("PATCH", f"/api/v1/roles/{rw.role_id('Mitarbeiter')}", {"description": "x"}),
                          ("PUT", f"/api/v1/members/{rw.pid(rw.ma)}/roles/{rw.role_id('Mitarbeiter')}", None),
                          ("PUT", f"/api/v1/members/{rw.pid(rw.ma)}/overrides/tasks.read", {"effect": "allow"})):
        r = gf.request(m, pfad, json=body)
        assert r.status_code == 403 and r.json()["code"] == "permission_denied", (m, pfad, r.text)


def test_obergrenze_beim_anlegen(rw: RbacWorld) -> None:
    _, v = _verwalter(rw)
    r = v.post("/api/v1/roles", json={"name": "Finanzen", "rank": 10, "permissions": ["tasks.read", "finance.read"]})
    assert r.status_code == 403 and "finance.read" in r.text
    neu = ok(v.post("/api/v1/roles", json={"name": "Aufgaben", "rank": 10, "permissions": ["tasks.read"]}), 201)
    assert neu["permissions"] == ["tasks.read"] and neu["rank"] == 10 and not neu["locked"]


def test_rang_beim_anlegen_nur_unter_dem_eigenen(rw: RbacWorld) -> None:
    _, v = _verwalter(rw, 50)
    for rang in (50, 51, 999):
        assert v.post("/api/v1/roles", json={"name": f"R{rang}", "rank": rang, "permissions": []}).status_code == 403
    assert v.post("/api/v1/roles", json={"name": "R49", "rank": 49, "permissions": []}).status_code == 201


def test_keine_luecken_loeschung(rw: RbacWorld) -> None:
    rid = rw.rolle("Gemischt", 10, {"tasks.read", "finance.read", "finance.export"})
    _, v = _verwalter(rw)
    r = ok(v.patch(f"/api/v1/roles/{rid}", json={"permissions": ["tasks.create"]}))
    # tasks.read (eigenes Recht) entfernt, tasks.create hinzu; finance.* (fremd) bleibt unverändert
    assert r["permissions"] == ["finance.export", "finance.read", "tasks.create"]
    assert v.patch(f"/api/v1/roles/{rid}", json={"permissions": ["finance.read", "audit.read"]}).status_code == 403
    a = rw.audit("role.updated")[-1][1]
    assert a["added"] == ["tasks.create"] and a["removed"] == ["tasks.read"]


def test_duplizieren_kopiert_nur_eigene_rechte(rw: RbacWorld) -> None:
    rid = rw.rolle("Vorlage", 20, {"tasks.read", "finance.read"})
    _, v = _verwalter(rw)
    kopie = ok(v.post(f"/api/v1/roles/{rid}/duplicate", json={"name": "Kopie"}), 201)
    assert kopie["permissions"] == ["tasks.read"] and kopie["rank"] == 20
    assert rw.audit("role.duplicated")[-1][1]["not_copied"] == ["finance.read"]
    ca = ok(v.post(f"/api/v1/roles/{rw.role_id('Company Admin')}/duplicate", json={"name": "Admin-Kopie"}), 201)
    assert set(ca["permissions"]) == VERWALTER and ca["rank"] == 49 and not ca["locked"]


# ---------- Rollenmanipulation ----------
def test_company_admin_ist_gesperrt(rw: RbacWorld) -> None:
    admin, ca = rw.client(rw.admin), rw.role_id("Company Admin")
    for m, pfad, body in (("PATCH", f"/api/v1/roles/{ca}", {"description": "weniger"}),
                          ("PATCH", f"/api/v1/roles/{ca}", {"permissions": []}),
                          ("POST", f"/api/v1/roles/{ca}/archive", None),
                          ("DELETE", f"/api/v1/roles/{ca}", None)):
        r = admin.request(m, pfad, json=body)
        assert r.status_code == 409 and r.json()["code"] == "role_locked", (m, pfad, r.text)
    rolle = ok(admin.get(f"/api/v1/roles/{ca}"))
    assert rolle["locked"] and rolle["rank"] == 100 and len(rolle["permissions"]) == len(ok(
        admin.get("/api/v1/permissions"))["items"])


def test_rang_beim_bearbeiten_archivieren_loeschen(rw: RbacWorld) -> None:
    _, v = _verwalter(rw, 50)
    gleich, hoeher = rw.rolle("Gleich", 50, set()), rw.role_id("Geschäftsführung")
    for ref in (gleich, hoeher):
        for m, pfad, body in (("PATCH", f"/api/v1/roles/{ref}", {"description": "x"}),
                              ("POST", f"/api/v1/roles/{ref}/archive", None),
                              ("DELETE", f"/api/v1/roles/{ref}", None)):
            assert v.request(m, pfad, json=body).status_code == 403, (m, pfad)
    tiefer = rw.rolle("Tiefer", 49, set())
    assert v.patch(f"/api/v1/roles/{tiefer}", json={"rank": 50}).status_code == 403     # nicht hochstufen
    assert ok(v.patch(f"/api/v1/roles/{tiefer}", json={"rank": 30, "name": "Tiefer2"}))["rank"] == 30


# ---------- Einzelrechte-Missbrauch ----------
def test_einzelrechte_kein_selbstbedienen_obergrenze_rang(rw: RbacWorld) -> None:
    vid, v = _verwalter(rw)
    r = v.put(f"/api/v1/members/{rw.pid(vid)}/overrides/finance.read", json={"effect": "allow"})
    assert r.status_code == 403 and "selbst" in r.text
    assert v.put(f"/api/v1/members/{rw.pid(vid)}/overrides/tasks.read", json={"effect": "deny"}).status_code == 403
    assert v.put(f"/api/v1/members/{rw.pid(rw.ma)}/overrides/finance.read",
                 json={"effect": "allow"}).status_code == 403                  # hat finance.read selbst nicht
    assert v.put(f"/api/v1/members/{rw.pid(rw.gf)}/overrides/tasks.read",
                 json={"effect": "deny"}).status_code == 403                   # GF Rang 90 > 50
    assert v.put(f"/api/v1/members/{rw.pid(rw.ma)}/overrides/gibt.esnicht",
                 json={"effect": "allow"}).status_code in (400, 422)
    assert v.put(f"/api/v1/members/{rw.pid(rw.ma)}/overrides/tasks.read",
                 json={"effect": "maybe"}).status_code == 422
    ok(v.put(f"/api/v1/members/{rw.pid(rw.ma)}/overrides/tasks.create", json={"effect": "deny"}))
    assert "tasks.create" not in rw.rechte(rw.ma)
    ok(v.delete(f"/api/v1/members/{rw.pid(rw.ma)}/overrides/tasks.create"), 204)
    assert "tasks.create" in rw.rechte(rw.ma)
    assert [a[1]["effect"] for a in rw.audit("permission.override_set")] == ["deny"]
    assert len(rw.audit("permission.override_cleared")) == 1


# ---------- Admin-Eskalation ----------
def test_admin_eskalation_ueber_rollen(rw: RbacWorld) -> None:
    vid, v = _verwalter(rw, 80)
    ca, gf = rw.role_id("Company Admin"), rw.role_id("Geschäftsführung")
    assert v.put(f"/api/v1/members/{rw.pid(vid)}/roles/{ca}").status_code == 403        # sich selbst
    assert v.put(f"/api/v1/members/{rw.pid(rw.ma)}/roles/{ca}").status_code == 403      # Obergrenze + Rang
    assert v.put(f"/api/v1/members/{rw.pid(rw.ma)}/roles/{gf}").status_code == 403      # Rang 90 > 80
    # Jede Regel einzeln: Rang erlaubt, aber fremdes Recht → Obergrenze; Rechte erlaubt, aber Rang zu hoch → Rang
    fremd, hoch = rw.rolle("Finanzen40", 40, {"finance.read"}), rw.rolle("Hoch85", 85, {"tasks.read"})
    r = v.put(f"/api/v1/members/{rw.pid(rw.ma)}/roles/{fremd}")
    assert r.status_code == 403 and "finance.read" in r.text
    r = v.put(f"/api/v1/members/{rw.pid(rw.ma)}/roles/{hoch}")
    assert r.status_code == 403 and "Rang" in r.text
    helfer = rw.mitglied("helfer@alpha.test")
    assert v.put(f"/api/v1/members/{rw.pid(helfer)}/roles/{rw.role_id('Verwalter')}").json()["created"] is True
    # Helfer kann jetzt dasselbe wie der Verwalter — aber nicht mehr, und nicht den Verwalter selbst überholen
    h = rw.client(helfer)
    assert h.put(f"/api/v1/members/{rw.pid(helfer)}/overrides/finance.read", json={"effect": "allow"}).status_code \
        == 403
    assert rw.rechte(helfer) == VERWALTER


def test_company_admin_vergeben_nur_mit_allen_rechten(rw: RbacWorld) -> None:
    ok(rw.client(rw.admin).put(f"/api/v1/members/{rw.pid(rw.gf)}/roles/{rw.role_id('Company Admin')}"))
    assert rw.rechte(rw.gf) == rw.rechte(rw.admin)
    assert rw.audit("role.assigned")[-1][1]["role_name"] == "Company Admin"


def test_archivierte_rolle_nicht_vergebbar_aber_entziehbar(rw: RbacWorld) -> None:
    _, v = _verwalter(rw, 50)
    alt = rw.rolle("Alt", 60, {"tasks.read"})
    rw.gib(rw.ma, "Alt")
    admin = rw.client(rw.admin)
    ok(admin.post(f"/api/v1/roles/{alt}/archive"))
    assert admin.put(f"/api/v1/members/{rw.pid(rw.ohne)}/roles/{alt}").status_code == 409
    ok(v.delete(f"/api/v1/members/{rw.pid(rw.ma)}/roles/{alt}"), 204)       # Rang 60 > 50, aber archiviert


# ---------- Bypass ----------
def test_keine_plattform_rechte_und_keine_flag_route(rw: RbacWorld) -> None:
    from ichq.api.security import iter_api_routes
    from ichq.app import create_app
    from ichq.authz.registry import PERMISSIONS
    assert not [p for p in PERMISSIONS if p.startswith(("platform.", "system."))]
    pfade = {p for p, _, _ in iter_api_routes(create_app(rw.settings, engines=rw.engines))}
    assert not [p for p in pfade if any(w in p for w in ("platform", "feature", "flag", "superuser"))]
    admin = rw.client(rw.admin)
    assert admin.put(f"/api/v1/members/{rw.pid(rw.ma)}/overrides/platform.admin",
                     json={"effect": "allow"}).status_code in (400, 422)
    r = admin.post("/api/v1/roles", json={"name": "X", "rank": 10, "permissions": ["platform.companies.manage"]})
    assert r.status_code in (400, 422)
    for feld in ({"grants_all": True}, {"is_system": True}, {"tenant_id": str(rw.b)}):
        r = admin.post("/api/v1/roles", json={"name": "X", "rank": 10, "permissions": [], **feld})
        assert r.status_code == 422, feld                                    # unbekannte Felder sind Fehler


# ---------- Rollenlöschung ----------
def test_loeschen_nur_archiviert_und_unbenutzt(rw: RbacWorld) -> None:
    admin, mit = rw.client(rw.admin), rw.role_id("Mitarbeiter")
    assert admin.delete(f"/api/v1/roles/{mit}").status_code == 409                       # nicht archiviert
    ok(admin.post(f"/api/v1/roles/{mit}/archive"))
    assert admin.delete(f"/api/v1/roles/{mit}").status_code == 409                       # noch zugewiesen
    ok(admin.delete(f"/api/v1/members/{rw.pid(rw.ma)}/roles/{mit}"), 204)
    ok(admin.delete(f"/api/v1/roles/{mit}"), 204)
    assert admin.get(f"/api/v1/roles/{mit}").status_code == 404
    assert [a[0] for a in rw.audit("role.deleted")] == [mit]


def test_wiederherstellen_mit_obergrenze(rw: RbacWorld) -> None:
    rid = rw.rolle("Finanzrolle", 10, {"finance.read"})
    _, v = _verwalter(rw)
    ok(rw.client(rw.admin).post(f"/api/v1/roles/{rid}/archive"))
    assert v.post(f"/api/v1/roles/{rid}/restore").status_code == 403                     # finance.read fehlt
    assert ok(rw.client(rw.admin).post(f"/api/v1/roles/{rid}/restore"))["archived"] is False
