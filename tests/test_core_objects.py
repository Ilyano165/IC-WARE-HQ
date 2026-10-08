"""Globales Objektmodell: Registry = Datenbank, typisierte Fremdschlüssel, Mandantengrenzen in der DB,
öffentliche IDs, Cursor-Paginierung (Unit + Integration gegen echtes PostgreSQL)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import column, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from ichq.core.errors import NotFound, ValidationFailed
from ichq.db.engine import Engines
from ichq.db.paging import MAX_LIMIT, SortKey, clamp_limit, decode_cursor, encode_cursor
from ichq.db.session import tenant_transaction
from ichq.objects.models import ObjectRow
from ichq.objects.registry import LINK_TYPES, OBJECT_TYPES
from ichq.objects.service import check_public_id, create_object
from tests.conftest import World, _admin

CORE = ["objects", "object_links", "object_grants", "activities", "comments", "comment_mentions", "tasks",
        "documents", "notifications"]


def _obj(engines: Engines, tid: uuid.UUID, typ: str, titel: str = "X") -> ObjectRow:
    with tenant_transaction(engines.app, tid) as s:
        return create_object(s, type_=typ, title=titel, actor_membership_id=None)


# ---------- Registry und Datenbank stimmen überein ----------
def test_registry_und_datenbank_stimmen_ueberein(world: World, engines: Engines) -> None:
    """Jeder Registry-Typ ist in der DB erlaubt, ein erfundener nicht. Eingefrorene Migration = Code."""
    for typ in OBJECT_TYPES:
        _obj(engines, world.a.id, typ)
    with pytest.raises(IntegrityError, match="ck_objects_type_known"), \
            tenant_transaction(engines.app, world.a.id) as s:
        s.execute(text("INSERT INTO objects(id, tenant_id, type, public_id, title) "
                       "VALUES (:i, :t, 'kaffeemaschine', :p, 'x')"),
                  {"i": uuid.uuid4(), "t": world.a.id, "p": uuid.uuid4().hex})


def test_verknuepfungsregeln_gelten_in_der_datenbank(world: World, engines: Engines) -> None:
    """Jede erlaubte Kombination geht, eine verbotene scheitert auch OHNE Service (CHECK)."""
    objekte = {t: _obj(engines, world.a.id, t) for t in OBJECT_TYPES}
    erlaubt = verboten = 0
    with tenant_transaction(engines.app, world.a.id) as s:
        for lt in LINK_TYPES.values():
            for q in OBJECT_TYPES:
                for z in OBJECT_TYPES:
                    if q == z:
                        continue
                    sql = text("INSERT INTO object_links(id, tenant_id, public_id, link_type, source_id, source_type, "
                               "target_id, target_type) VALUES (:i, :t, :p, :l, :q, :qt, :z, :zt)")
                    werte = {"i": uuid.uuid4(), "t": world.a.id, "p": uuid.uuid4().hex, "l": lt.code,
                             "q": objekte[q].id, "qt": q, "z": objekte[z].id, "zt": z}
                    if lt.allows(q, z):
                        s.execute(sql, werte)
                        erlaubt += 1
                    elif verboten < 40:
                        with pytest.raises(IntegrityError, match="ck_object_links_rule"), s.begin_nested():
                            s.execute(sql, werte)
                        verboten += 1
    assert erlaubt > 50 and verboten == 40


def test_fachtabelle_erzwingt_objekttyp(world: World, engines: Engines) -> None:
    """Eine Aufgabe kann nicht an einem Dokument-Objekt hängen: (tenant_id, id, object_type) → objects."""
    doc = _obj(engines, world.a.id, "document")
    with pytest.raises(IntegrityError), tenant_transaction(engines.app, world.a.id) as s:
        s.execute(text("INSERT INTO tasks(id, tenant_id) VALUES (:i, :t)"), {"i": doc.id, "t": world.a.id})
    with pytest.raises(IntegrityError), tenant_transaction(engines.app, world.a.id) as s:
        s.execute(text("INSERT INTO tasks(id, tenant_id, object_type) VALUES (:i, :t, 'document')"),
                  {"i": doc.id, "t": world.a.id})


def test_verweis_auf_fremde_firma_scheitert_in_der_datenbank(world: World, engines: Engines) -> None:
    """Zusammengesetzte Fremdschlüssel: Kommentar/Verknüpfung/Freigabe auf Objekt oder Mitglied von B geht nicht."""
    oa, ob = _obj(engines, world.a.id, "task"), _obj(engines, world.b.id, "task")
    faelle = [
        ("INSERT INTO comments(id, tenant_id, public_id, object_id, author_membership_id, body) "
         "VALUES (:i, :t, :p, :ob, :ma, 'x')"),
        ("INSERT INTO object_links(id, tenant_id, public_id, link_type, source_id, source_type, target_id, "
         "target_type) VALUES (:i, :t, :p, 'related', :oa, 'task', :ob, 'task')"),
        "INSERT INTO object_grants(tenant_id, object_id, membership_id) VALUES (:t, :oa, :mb)",
        "INSERT INTO activities(id, tenant_id, object_id, verb) VALUES (:i, :t, :ob, 'task.created')",
        ("INSERT INTO notifications(id, tenant_id, public_id, recipient_membership_id, kind, title) "
         "VALUES (:i, :t, :p, :mb, 'task.assigned', 'x')"),
    ]
    for sql in faelle:
        with pytest.raises(IntegrityError), tenant_transaction(engines.app, world.a.id) as s:
            s.execute(text(sql), {"i": uuid.uuid4(), "t": world.a.id, "p": uuid.uuid4().hex, "oa": oa.id,
                                  "ob": ob.id, "ma": world.mem_a, "mb": world.mem_b})


@pytest.mark.parametrize("tabelle", CORE)
def test_rls_erzwungen_und_ohne_kontext_leer(tabelle: str, world: World, engines: Engines) -> None:
    _obj(engines, world.a.id, "task")
    with engines.app.connect() as c:
        assert c.execute(text(f"SELECT count(*) FROM {tabelle}")).scalar() == 0
    with _admin(engines.app.url.database) as c:
        zeile = c.execute("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
                          (tabelle,)).fetchone()
    assert zeile == (True, True)


def test_schreiben_in_fremde_firma_per_rls_verboten(world: World, engines: Engines) -> None:
    with pytest.raises(ProgrammingError, match="row-level security"), \
            tenant_transaction(engines.app, world.a.id) as s:
        s.execute(text("INSERT INTO objects(id, tenant_id, type, public_id, title) VALUES (:i, :b, 'task', :p, 'x')"),
                  {"i": uuid.uuid4(), "b": world.b.id, "p": uuid.uuid4().hex})


def test_aktivitaeten_nur_anhaengend(world: World, engines: Engines) -> None:
    o = _obj(engines, world.a.id, "task")
    with tenant_transaction(engines.app, world.a.id) as s:
        s.execute(text("INSERT INTO activities(id, tenant_id, object_id, verb) VALUES (:i, :t, :o, 'task.created')"),
                  {"i": uuid.uuid4(), "t": world.a.id, "o": o.id})
    for sql in ("UPDATE activities SET verb = 'task.updated'", "DELETE FROM activities"):
        with pytest.raises(ProgrammingError, match="permission denied"), \
                tenant_transaction(engines.app, world.a.id) as s:
            s.execute(text(sql))


def test_spaltenrechte_verhindern_manipulation(world: World, engines: Engines) -> None:
    """App-Rolle darf Typ, Ersteller, Autor, Prüfstatus der Virenprüfung nicht ändern."""
    o = _obj(engines, world.a.id, "task")
    for sql in ("UPDATE objects SET type = 'document'", "UPDATE objects SET created_by_membership_id = NULL",
                "UPDATE objects SET public_id = 'ffffffffffffffffffffffffffffffff'",
                "UPDATE comments SET author_membership_id = NULL", "UPDATE documents SET scan_status = 'clean'",
                "UPDATE notifications SET recipient_membership_id = NULL", "DELETE FROM objects",
                "DELETE FROM comments"):
        with pytest.raises(ProgrammingError, match="permission denied"), \
                tenant_transaction(engines.app, world.a.id) as s:
            s.execute(text(sql))
    assert o.public_id


# ---------- Öffentliche IDs ----------
def test_oeffentliche_id_ist_zufaellig_und_nicht_der_schluessel(world: World, engines: Engines) -> None:
    ids = [_obj(engines, world.a.id, "task") for _ in range(20)]
    for o in ids:
        assert len(o.public_id) == 32 and o.public_id != o.id.hex
        assert o.id.hex[:12] not in o.public_id          # kein Zeitanteil der UUIDv7
    assert len({o.public_id for o in ids}) == 20
    with tenant_transaction(engines.app, world.a.id) as s:
        pids = s.execute(text("SELECT public_id FROM memberships")).scalars().all()
    assert all(len(p) == 32 for p in pids)


@pytest.mark.parametrize("ref", ["", "1", "../etc", "' OR 1=1 --", "A" * 32, "0" * 31, "0" * 33,
                                 str(uuid.uuid4())])
def test_ungueltige_referenz_ist_not_found(ref: str) -> None:
    with pytest.raises(NotFound):
        check_public_id(ref)


# ---------- Paginierung (Unit) ----------
SORT = SortKey("created_at", column("x"), "ts")


def test_cursor_rundreise_und_bindung_an_sortierung() -> None:
    jetzt, rid = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), uuid.uuid4()
    c = encode_cursor(SORT, True, jetzt, rid)
    assert decode_cursor(c, SORT, True) == (jetzt, rid)
    with pytest.raises(ValidationFailed):
        decode_cursor(c, SORT, False)                                   # andere Richtung
    with pytest.raises(ValidationFailed):
        decode_cursor(c, SortKey("title", column("t"), "text"), True)   # andere Sortierung


@pytest.mark.parametrize("kaputt", ["", "!!!", "eyJ9", "e30", "eyJzIjoiY3JlYXRlZF9hdCIsImQiOnRydWUsInYiOjEsImkiOiJ4In0"])
def test_kaputter_cursor_ist_validierungsfehler(kaputt: str) -> None:
    with pytest.raises(ValidationFailed):
        decode_cursor(kaputt, SORT, True)


def test_limit_wird_immer_begrenzt() -> None:
    assert clamp_limit(None) == 25 and clamp_limit(0) == 1 and clamp_limit(10_000) == MAX_LIMIT


def test_objekttitel_validierung(world: World, engines: Engines) -> None:
    with pytest.raises(ValidationFailed), tenant_transaction(engines.app, world.a.id) as s:
        create_object(s, type_="task", title="   ", actor_membership_id=None)
    with pytest.raises(ValidationFailed), tenant_transaction(engines.app, world.a.id) as s:
        create_object(s, type_="erfunden", title="x", actor_membership_id=None)
    with pytest.raises(DBAPIError), tenant_transaction(engines.app, world.a.id) as s:
        s.execute(text("INSERT INTO objects(id, tenant_id, type, public_id, title) VALUES (:i, :t, 'task', 'kurz', 'x')"),
                  {"i": uuid.uuid4(), "t": world.a.id})
