"""M4 — letzter Admin (jeder Weg), Mandantengrenzen, Direktzugriff auf die Datenbank, Wirkung ohne neuen Login."""
from __future__ import annotations

import pytest
from psycopg import errors as pg_errors
from sqlalchemy import exc, text

from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import tenant_transaction
from tests.auth_helpers import PASSWORT, client, db, join, login, make_user
from tests.core_helpers import ok
from tests.m4_helpers import RbacWorld

ADMIN = {"users.deactivate", "roles.update", "roles.assign"}


@pytest.fixture
def ohne_ca(rw: RbacWorld) -> tuple[object, object, str]:
    """Firma, in der genau EIN Admin übrig ist (über eine normale Rolle), und ein Verwalter OHNE Admin-Status
    (users.deactivate fehlt), der trotzdem Rollen und Einzelrechte ändern darf."""
    ok(rw.client(rw.admin).delete(f"/api/v1/members/{rw.pid(rw.admin)}/roles/{rw.role_id('Company Admin')}"),
       403)                                                      # sich selbst: nie
    rid = rw.rolle("Admin90", 90, ADMIN | {"users.read", "roles.read"})
    einziger = rw.mitglied("einzig@alpha.test", "Admin90")
    rw.rolle("Verwalter", 95, {"roles.read", "roles.update", "roles.delete", "roles.assign", "users.read",
                                "users.override"})
    v = rw.mitglied("v@alpha.test", "Verwalter")
    with tenant_transaction(rw.engines.app, rw.a) as s:          # Company Admin aus dem Spiel nehmen (Testaufbau)
        s.execute(text("UPDATE memberships SET status = 'suspended' WHERE id = :m"), {"m": rw.admin})
    return einziger, v, rid


def test_letzter_admin_jeder_weg(rw: RbacWorld, ohne_ca: tuple[object, object, str]) -> None:
    einziger, vid, rid = ohne_ca
    v, e = rw.client(vid), rw.pid(einziger)
    versuche = [("PATCH", f"/api/v1/roles/{rid}", {"permissions": ["users.read", "roles.read", "users.deactivate"]}),
                ("POST", f"/api/v1/roles/{rid}/archive", None),
                ("DELETE", f"/api/v1/members/{e}/roles/{rid}", None),
                ("PUT", f"/api/v1/members/{e}/overrides/roles.update", {"effect": "deny"})]
    for m, pfad, body in versuche:
        r = v.request(m, pfad, json=body)
        assert r.status_code == 409 and r.json()["code"] == "last_admin", (m, pfad, r.text)
    assert rw.rechte(einziger) >= ADMIN                                       # nichts geschrieben
    assert rw.audit("role.updated") == [] and rw.audit("role.archived") == []
    # Ein zweiter Admin über DIESELBE Rolle hilft nicht: Rolle bearbeiten träfe beide → weiterhin abgelehnt
    gleich = rw.mitglied("gleich@alpha.test", "Admin90")
    assert v.request(*versuche[0][:2], json=versuche[0][2]).status_code == 409
    # Mit einem Admin über eine ANDERE Rolle geht jeder Weg durch
    rw.rolle("AdminZwei", 80, ADMIN)
    zweit = rw.mitglied("zweit@alpha.test", "AdminZwei")
    ok(v.request(*versuche[0][:2], json=versuche[0][2]))
    assert not rw.rechte(einziger) >= ADMIN and not rw.rechte(gleich) >= ADMIN and rw.rechte(zweit) >= ADMIN


def test_letzter_admin_deaktivieren_und_verlassen(rw: RbacWorld, ohne_ca: tuple[object, object, str]) -> None:
    einziger, _vid, _ = ohne_ca
    r = rw.client(einziger).post("/api/v1/membership/leave")
    assert r.status_code == 409 and r.json()["code"] == "last_admin"
    zweit = rw.mitglied("zweit@alpha.test", "Admin90")
    ok(rw.client(zweit).post(f"/api/v1/members/{rw.pid(einziger)}/deactivate"))
    r = rw.client(zweit).post("/api/v1/membership/leave")
    assert r.status_code == 409 and r.json()["code"] == "last_admin"


def test_mandantengrenzen(rw: RbacWorld) -> None:
    admin = rw.client(rw.admin)
    rolle_b, mitglied_b = rw.role_id("Mitarbeiter", rw.b), rw.pid(rw.admin_b)
    assert rolle_b != rw.role_id("Mitarbeiter")
    for m, pfad in (("GET", f"/api/v1/roles/{rolle_b}"), ("PATCH", f"/api/v1/roles/{rolle_b}"),
                    ("PUT", f"/api/v1/members/{rw.pid(rw.ma)}/roles/{rolle_b}"),
                    ("PUT", f"/api/v1/members/{mitglied_b}/roles/{rw.role_id('Mitarbeiter')}"),
                    ("GET", f"/api/v1/members/{mitglied_b}/permissions"),
                    ("PUT", f"/api/v1/members/{mitglied_b}/overrides/tasks.read")):
        body = {"effect": "deny"} if "overrides" in pfad else ({"description": "x"} if m == "PATCH" else None)
        assert admin.request(m, pfad, json=body).status_code == 404, (m, pfad)
    namen = {r["id"] for r in ok(admin.get("/api/v1/roles?archived=true"))["items"]}
    assert rolle_b not in namen and len(namen) == 4
    # Zeile mit Rolle aus A für Mitglied aus B: zusammengesetzter Fremdschlüssel verhindert sie
    with pytest.raises(exc.IntegrityError), tenant_transaction(rw.engines.app, rw.b) as s:
        s.execute(text("INSERT INTO membership_roles(tenant_id, membership_id, role_id) VALUES (:t, :m, :r)"),
                  {"t": rw.b, "m": rw.admin_b, "r": _intern_role_id(rw, "Mitarbeiter", rw.a)})
    # Einzelrecht in A wirkt nicht in B
    ok(admin.put(f"/api/v1/members/{rw.pid(rw.ma)}/overrides/finance.read", json={"effect": "allow"}))
    assert db(rw.engines, "SELECT count(*) FROM permission_overrides WHERE tenant_id = %s", (rw.b,))[0][0] == 0


def _intern_role_id(rw: RbacWorld, name: str, tid: object) -> object:
    return db(rw.engines, "SELECT id FROM roles WHERE name = %s AND tenant_id = %s", (name, tid))[0][0]


def test_db_sperrt_company_admin_auch_ohne_service(rw: RbacWorld) -> None:
    for sql in ("UPDATE roles SET archived_at = now() WHERE grants_all",
                "UPDATE roles SET name = 'Weg' WHERE grants_all",
                "UPDATE roles SET priority = 1 WHERE grants_all",
                "DELETE FROM roles WHERE grants_all",
                "UPDATE roles SET grants_all = true, is_system = true WHERE name = 'Mitarbeiter'",
                "INSERT INTO role_permissions(tenant_id, role_id, permission) "
                "SELECT tenant_id, id, 'tasks.read' FROM roles WHERE grants_all"):
        with pytest.raises(exc.DBAPIError), tenant_transaction(rw.engines.app, rw.a) as s:
            s.execute(text(sql))
    with pytest.raises(exc.IntegrityError), tenant_transaction(rw.engines.app, rw.a) as s:   # zweite gesperrte Rolle
        s.execute(text("INSERT INTO roles(tenant_id, name, is_system, grants_all) "
                       "VALUES (:t, 'Zweiter Admin', true, true)"), {"t": rw.a})
    with tenant_transaction(rw.engines.app, rw.a) as s:                                      # Beschreibung geht
        s.execute(text("UPDATE roles SET description = 'ok' WHERE grants_all"))


def test_app_rolle_kann_feature_flags_nicht_schreiben(rw: RbacWorld) -> None:
    with pytest.raises(exc.ProgrammingError) as e, tenant_transaction(rw.engines.app, rw.a) as s:
        s.execute(text("INSERT INTO tenant_feature_flags(tenant_id, module, enabled, updated_by) "
                       "VALUES (:t, 'tasks', true, 'ich')"), {"t": rw.a})
    assert isinstance(e.value.orig, pg_errors.InsufficientPrivilege)
    db(rw.engines, "INSERT INTO tenant_feature_flags(tenant_id, module, enabled, updated_by) "
                   "VALUES (%s, 'tasks', false, 't')", (rw.b,))
    with tenant_transaction(rw.engines.app, rw.a) as s:                                      # B unsichtbar in A
        assert s.execute(text("SELECT count(*) FROM tenant_feature_flags")).scalar() == 0


def test_rechteaenderung_wirkt_in_laufender_sitzung(rw: RbacWorld, engines: Engines, settings: Settings) -> None:
    """Echter Login (kein Test-Principal): get_principal berechnet je Anfrage neu."""
    uid = make_user(engines, settings, "sitzung@alpha.test", password=PASSWORT)
    mid = join(engines, rw.a, uid)
    rw._tenant[mid] = rw.a
    c, _ = client(settings, engines)
    ok(login(c, "sitzung@alpha.test"))
    ok(c.post("/api/v1/auth/tenant", json={"tenant_id": str(rw.a)}))
    assert c.get("/api/v1/tasks").status_code == 403
    rw.gib(mid, "Mitarbeiter")
    assert c.get("/api/v1/tasks").status_code == 200
    ok(rw.client(rw.admin).put(f"/api/v1/members/{rw.pid(mid)}/overrides/tasks.read", json={"effect": "deny"}))
    assert c.get("/api/v1/tasks").status_code == 403
    assert "tasks.read" not in ok(c.get("/api/v1/me"))["permissions"]


def test_letzter_admin_bei_gleichzeitigen_aenderungen(rw: RbacWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    """Zwei Admins entziehen sich GLEICHZEITIG gegenseitig ein Admin-Recht. Ohne Sperre sähen beide vorher 2 Admins
    und nachher (nur eigene Änderung sichtbar) 1 → beide durch → 0 Admins. Die Verzögerung nach dem ZWEITEN Zählen
    (vor dem Commit) sorgt dafür, dass sich die Transaktionen sicher überlappen — Gegenprobe: Mutation
    „M4 Last-Admin ohne Sperre"."""
    import threading
    import time

    from ichq.authz import delegation, guard
    from ichq.authz.guard import LastAdmin
    zweit = rw.mitglied("zweit@alpha.test", "Company Admin")
    original, zaehler = guard.admins, threading.local()

    def langsam(session):  # type: ignore[no-untyped-def]
        ergebnis = original(session)
        zaehler.n = getattr(zaehler, "n", 0) + 1
        if zaehler.n == 2:                           # nach dem Zählen „nachher", vor dem Commit
            time.sleep(0.5)
        return ergebnis
    monkeypatch.setattr(guard, "admins", langsam)
    ergebnisse: list[str] = []

    def entziehe(handelnd: object, ziel: object) -> None:
        try:
            with tenant_transaction(rw.engines.app, rw.a) as s:
                delegation.set_override(s, rw.principal(handelnd), rw.pid(ziel), "roles.assign", "deny")
            ergebnisse.append("ok")
        except LastAdmin:
            ergebnisse.append("last_admin")
    t = [threading.Thread(target=entziehe, args=a) for a in ((rw.admin, zweit), (zweit, rw.admin))]
    for x in t:
        x.start()
    for x in t:
        x.join(30)
    assert sorted(ergebnisse) == ["last_admin", "ok"], ergebnisse
    assert sum(rw.rechte(m) >= ADMIN for m in (rw.admin, zweit)) == 1
