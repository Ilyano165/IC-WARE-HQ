"""API der Core-Plattform: Aufgaben, Kommentare, Dokumente, Verknüpfungen, Paginierung, Fehlerformat."""
from __future__ import annotations

import hashlib

import pytest

from ichq.core.config import Settings
from ichq.db.engine import Engines
from tests.auth_helpers import db
from tests.conftest import World
from tests.core_helpers import CoreWorld, ok


@pytest.fixture
def cw(world: World, engines: Engines, settings: Settings) -> CoreWorld:
    return CoreWorld(world, engines, settings)


def _pdf(c, name: str = "beleg.pdf", inhalt: bytes = b"%PDF-1.4 test") -> dict:  # type: ignore[no-untyped-def,type-arg]
    return ok(c.post("/api/v1/documents", params={"filename": name}, content=inhalt,
                     headers={"content-type": "application/pdf"}), 201)


# ---------- Aufgaben ----------
def test_aufgabe_anlegen_lesen_aendern(cw: CoreWorld) -> None:
    c = cw.client(cw.mitarbeiter)
    t = ok(c.post("/api/v1/tasks", json={"title": "  USt-Voranmeldung  ", "description": "Q3", "priority": "high",
                                          "due_date": "2026-10-10", "assignee": cw.public_id(cw.mitarbeiter)}), 201)
    assert t["title"] == "USt-Voranmeldung" and t["status"] == "open" and t["priority"] == "high"
    assert t["assignee"]["display_name"] == "Max Mitarbeiter" and t["created_by"]["id"] == cw.public_id(cw.mitarbeiter)
    assert set(t) >= {"id", "type", "created_at", "due_date", "subject"} and t["type"] == "task"
    assert ok(c.get(f"/api/v1/tasks/{t['id']}"))["id"] == t["id"]
    t2 = ok(c.patch(f"/api/v1/tasks/{t['id']}", json={"status": "done"}))
    assert t2["status"] == "done" and t2["completed_at"]
    assert ok(c.patch(f"/api/v1/tasks/{t['id']}", json={"status": "open"}))["completed_at"] is None


def test_aufgabe_aus_beleg_und_aus_kommentar(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    beleg = cw.raw_object(cw.a, "receipt", "Tankquittung 03.10.", by=cw.admin_a)
    t = ok(c.post(f"/api/v1/objects/{beleg}/tasks", json={"title": "IBAN prüfen"}), 201)
    assert t["subject"] == {"id": beleg, "type": "receipt", "title": "Tankquittung 03.10."}
    ok(c.post(f"/api/v1/objects/{beleg}/grants", json={"member": cw.public_id(cw.stb)}), 201)
    frage = ok(cw.client(cw.stb).post(f"/api/v1/objects/{beleg}/comments",
                                      json={"body": "Wo ist die Rechnung zum Tankbeleg?", "kind": "question"}), 201)
    t2 = ok(c.post(f"/api/v1/comments/{frage['id']}/tasks",
                   json={"title": "Rückfrage StB beantworten", "assignee": cw.public_id(cw.admin_a)}), 201)
    assert t2["description"] == "Wo ist die Rechnung zum Tankbeleg?" and t2["subject"]["id"] == beleg
    gefiltert = ok(c.get(f"/api/v1/tasks?subject={beleg}"))["items"]
    assert {x["id"] for x in gefiltert} == {t["id"], t2["id"]}
    verlauf = ok(c.get(f"/api/v1/objects/{beleg}/activities?order=asc"))["items"]
    assert [v["verb"] for v in verlauf] == ["task.created", "object.shared", "comment.question_asked", "task.created"]


def test_zuweisen_braucht_tasks_assign_und_empfaenger_mit_leserecht(cw: CoreWorld) -> None:
    c = cw.client(cw.mitarbeiter)     # hat kein tasks.assign
    r = c.post("/api/v1/tasks", json={"title": "x", "assignee": cw.public_id(cw.leser)})
    assert r.status_code == 403 and "tasks.assign" in r.json()["detail"]
    r = cw.client(cw.admin_a).post("/api/v1/tasks", json={"title": "x", "assignee": cw.public_id(cw.ohne)})
    assert r.status_code == 422 and "tasks.read" in r.json()["detail"]


def test_liste_filter_sortierung_paginierung(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    prio = ["low", "normal", "high", "urgent"]
    for i in range(53):
        ok(c.post("/api/v1/tasks", json={"title": f"Aufgabe {i:02d}", "priority": prio[i % 4],
                                          "due_date": f"2026-11-{(i % 28) + 1:02d}" if i % 5 else None}), 201)
    gesehen: list[str] = []
    cursor, seiten = None, 0
    while True:
        r = ok(c.get("/api/v1/tasks", params={"limit": 10, "sort": "title", "order": "asc",
                                              **({"cursor": cursor} if cursor else {})}))
        gesehen += [t["title"] for t in r["items"]]
        seiten += 1
        cursor = r["next_cursor"]
        if not cursor:
            break
    assert seiten == 6 and gesehen == [f"Aufgabe {i:02d}" for i in range(53)]       # lückenlos, ohne Dopplung
    faellig = [t["due_date"] for t in ok(c.get("/api/v1/tasks?sort=due_date&order=asc&limit=100"))["items"]]
    mit = [d for d in faellig if d]
    assert mit == sorted(mit) and faellig[-1] is None                                 # ohne Datum zuletzt
    p = [t["priority"] for t in ok(c.get("/api/v1/tasks?sort=priority&order=desc&limit=20"))["items"]]
    assert p[:13] == ["urgent"] * 13
    urgent = ok(c.get("/api/v1/tasks?priority=urgent&priority=high&limit=100"))["items"]
    assert len(urgent) == 26 and {t["priority"] for t in urgent} == {"urgent", "high"}
    assert len(ok(c.get("/api/v1/tasks?due_before=2026-11-03&limit=100"))["items"]) > 0


@pytest.mark.parametrize("abfrage", ["limit=0", "limit=101", "sort=geheim", "order=sideways", "status=fertig",
                                     "cursor=kaputt", "due_before=gestern"])
def test_listenparameter_werden_validiert(cw: CoreWorld, abfrage: str) -> None:
    r = cw.client(cw.admin_a).get(f"/api/v1/tasks?{abfrage}")
    assert r.status_code == 422 and r.headers["content-type"] == "application/problem+json"
    assert r.json()["code"] == "validation_failed" and r.json()["request_id"]


@pytest.mark.parametrize("body", [{"title": ""}, {"title": "x", "unbekannt": 1}, {"title": "x" * 301},
                                  {"title": "x", "priority": "sofort"}, {"title": "x", "due_date": "morgen"},
                                  {"title": "x", "description": "y" * 20_001}, {}])
def test_eingaben_werden_validiert(cw: CoreWorld, body: dict) -> None:  # type: ignore[type-arg]
    r = cw.client(cw.admin_a).post("/api/v1/tasks", json=body)
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert all("input" not in e for e in r.json()["errors"])     # Eingabewerte werden nicht zurückgespiegelt


# ---------- Kommentare ----------
def test_kommentar_erwaehnung_bearbeiten_loeschen(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.mitarbeiter)
    t = ok(c.post("/api/v1/tasks", json={"title": "Fahrtenbuch prüfen"}), 201)
    k = ok(c.post(f"/api/v1/objects/{t['id']}/comments",
                  json={"body": "Bitte ansehen", "mentions": [cw.public_id(cw.leser)]}), 201)
    assert k["author"]["display_name"] == "Max Mitarbeiter" and k["mentions"][0]["display_name"] == "Lena Leserin"
    k2 = ok(c.patch(f"/api/v1/comments/{k['id']}", json={"body": "Bitte bis Freitag ansehen"}))
    assert k2["edited_at"] and k2["body"] == "Bitte bis Freitag ansehen"
    # Bearbeitungsfenster abgelaufen (Zeitreise)
    db(engines, "UPDATE comments SET created_at = now() - interval '16 minutes' WHERE public_id = %s", (k["id"],))
    r = c.patch(f"/api/v1/comments/{k['id']}", json={"body": "später"})
    assert r.status_code == 409 and "15 Minuten" in r.json()["detail"]
    # Fremder darf nicht bearbeiten, ohne moderate nicht löschen
    assert cw.client(cw.admin_a).patch(f"/api/v1/comments/{k['id']}", json={"body": "x"}).status_code == 403
    k3 = ok(cw.client(cw.leser).get(f"/api/v1/objects/{t['id']}/comments"))["items"][0]
    assert k3["body"] == "Bitte bis Freitag ansehen"
    ok(c.request("DELETE", f"/api/v1/comments/{k['id']}", json={"reason": "Test: erledigt"}), 204)
    weg = ok(c.get(f"/api/v1/objects/{t['id']}/comments"))["items"][0]
    assert weg["deleted"] is True and weg["body"] is None
    assert c.patch(f"/api/v1/comments/{k['id']}", json={"body": "wieder da"}).status_code == 409


def test_loeschen_fremder_kommentare_nur_moderator(cw: CoreWorld) -> None:
    t = ok(cw.client(cw.mitarbeiter).post("/api/v1/tasks", json={"title": "x"}), 201)
    k = ok(cw.client(cw.mitarbeiter).post(f"/api/v1/objects/{t['id']}/comments", json={"body": "Hallo"}), 201)
    for mid in (cw.leser, cw.stb):       # leser: kein comments.create; stb: sieht die Aufgabe nicht
        assert cw.client(mid).request("DELETE", f"/api/v1/comments/{k['id']}", json={"reason": "Test: erledigt"}).status_code in (403, 404)
    # admin_a schreibt; mitarbeiter sieht das Objekt und hat comments.create, aber kein comments.moderate
    k2 = ok(cw.client(cw.admin_a).post(f"/api/v1/objects/{t['id']}/comments", json={"body": "Vom Chef"}), 201)
    r = cw.client(cw.mitarbeiter).request("DELETE", f"/api/v1/comments/{k2['id']}", json={"reason": "Test: erledigt"})
    assert r.status_code == 403 and "Moderatoren" in r.json()["detail"]
    assert ok(cw.client(cw.admin_a).get(f"/api/v1/objects/{t['id']}/comments"))["items"][1]["deleted"] is False
    ok(cw.client(cw.admin_a).request("DELETE", f"/api/v1/comments/{k['id']}", json={"reason": "Test: erledigt"}), 204)   # admin hat comments.moderate


def test_erwaehnung_fremder_oder_inaktiver_mitglieder_scheitert(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.admin_a)
    t = ok(c.post("/api/v1/tasks", json={"title": "x"}), 201)
    r = c.post(f"/api/v1/objects/{t['id']}/comments", json={"body": "x", "mentions": [cw.public_id(cw.admin_b)]})
    assert r.status_code == 404
    db(engines, "UPDATE memberships SET status = 'suspended' WHERE id = %s", (cw.ohne,))
    r = c.post(f"/api/v1/objects/{t['id']}/comments", json={"body": "x", "mentions": [cw.public_id(cw.ohne)]})
    assert r.status_code == 404
    assert c.post(f"/api/v1/objects/{t['id']}/comments", json={"body": "   "}).status_code == 422


# ---------- Dokumente ----------
def test_dokument_upload_quarantaene_pruefung(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.mitarbeiter)
    d = _pdf(c, "../../etc/Rechnung\x00 Okt.pdf")
    assert d["filename"] == "Rechnung Okt.pdf" and d["scan_status"] == "quarantined"
    assert d["sha256"] == hashlib.sha256(b"%PDF-1.4 test").hexdigest() and d["review_status"] == "pending"
    r = c.get(f"/api/v1/documents/{d['id']}/content")
    assert r.status_code == 409 and r.json()["code"] == "document_quarantined"
    r = c.post(f"/api/v1/documents/{d['id']}/review", json={"decision": "approved"})
    assert r.status_code == 409 and "Virenprüfung" in r.json()["detail"]     # Freigabe erst nach dem Scan
    db(engines, "UPDATE documents SET scan_status = 'clean'")                # Scanner (tests/test_documents_scan.py)
    g = ok(c.post(f"/api/v1/documents/{d['id']}/review", json={"decision": "approved"}))
    assert g["review_status"] == "approved" and g["reviewed_by"]["display_name"] == "Max Mitarbeiter"
    assert c.post(f"/api/v1/documents/{d['id']}/review", json={"decision": "rejected"}).status_code == 409
    assert [x["id"] for x in ok(c.get("/api/v1/documents?review_status=approved"))["items"]] == [d["id"]]
    verlauf = [v["verb"] for v in ok(c.get(f"/api/v1/objects/{d['id']}/activities?order=asc"))["items"]]
    assert verlauf == ["document.uploaded", "document.reviewed"]


def test_dokument_download_nach_freigabe(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.mitarbeiter)
    d = _pdf(c)
    db(engines, "UPDATE documents SET scan_status = 'clean'")      # Scanner: tests/test_documents_scan.py
    r = c.get(f"/api/v1/documents/{d['id']}/content")
    assert r.status_code == 200 and r.content == b"%PDF-1.4 test"
    assert r.headers["content-disposition"] == "attachment"


@pytest.mark.parametrize(("typ", "inhalt", "status"), [("text/html", b"<script>", 415),
                                                       ("application/pdf", b"", 422),
                                                       ("application/x-msdownload", b"MZ", 415)])
def test_upload_regeln(cw: CoreWorld, typ: str, inhalt: bytes, status: int) -> None:
    r = cw.client(cw.mitarbeiter).post("/api/v1/documents?filename=x", content=inhalt, headers={"content-type": typ})
    assert r.status_code == status


def test_upload_groessengrenze(cw: CoreWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    from ichq.documents import service
    monkeypatch.setattr(service, "MAX_BYTES", 1024)
    r = cw.client(cw.mitarbeiter).post("/api/v1/documents?filename=x.pdf", content=b"x" * 2000,
                                       headers={"content-type": "application/pdf"})
    assert r.status_code == 413


# ---------- Verknüpfungen & Anhänge ----------
def test_verknuepfungen_typisiert(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    t = ok(c.post("/api/v1/tasks", json={"title": "Reise Hamburg abrechnen"}), 201)
    d = _pdf(c)
    a = ok(c.post(f"/api/v1/tasks/{t['id']}/attachments", json={"document": d["id"]}), 201)
    assert c.post(f"/api/v1/tasks/{t['id']}/attachments", json={"document": d["id"]}).status_code == 409
    reise = cw.raw_object(cw.a, "travel", "Reise Hamburg", by=cw.admin_a)
    ok(c.post(f"/api/v1/objects/{d['id']}/links", json={"target": reise, "link_type": "evidence"}), 201)
    r = c.post(f"/api/v1/objects/{t['id']}/links", json={"target": reise, "link_type": "billed_to"})
    assert r.status_code == 422                                   # Aufgabe → Reise „berechnet an" gibt es nicht
    assert c.post(f"/api/v1/objects/{t['id']}/links", json={"target": t["id"], "link_type": "related"}
                  ).status_code == 422
    links = ok(c.get(f"/api/v1/objects/{d['id']}/links"))["items"]
    assert {(x["direction"], x["link_type"], x["object"]["id"]) for x in links} == {
        ("incoming", "attachment", t["id"]), ("outgoing", "evidence", reise)}
    ok(c.delete(f"/api/v1/links/{a['id']}"), 204)
    assert c.delete(f"/api/v1/links/{a['id']}").status_code == 404


def test_verknuepfen_braucht_aenderungsrecht_am_quellobjekt(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    t = ok(c.post("/api/v1/tasks", json={"title": "Quelle"}), 201)
    ziel = ok(c.post("/api/v1/tasks", json={"title": "Ziel"}), 201)
    leser = cw.client(cw.leser)                           # sieht beide, darf Aufgaben aber nicht ändern
    r = leser.post(f"/api/v1/objects/{t['id']}/links", json={"target": ziel["id"], "link_type": "related"})
    assert r.status_code == 403
    link = ok(c.post(f"/api/v1/objects/{t['id']}/links", json={"target": ziel["id"], "link_type": "related"}), 201)
    assert leser.delete(f"/api/v1/links/{link['id']}").status_code == 403
    assert len(ok(leser.get(f"/api/v1/objects/{t['id']}/links"))["items"]) == 1
