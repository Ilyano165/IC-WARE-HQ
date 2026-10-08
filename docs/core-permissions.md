# Core-Rechte (C0)

Grundlage: M0 „Rechte", CLAUDE.md Regeln 4 und 5, [ADR-009](adr/009-sichtbereich-und-objektfreigaben.md).

## Drei Schichten — jede prüft selbst

1. **Route** — genau eine Sicherheitsmarke (`require(...)` oder `authenticated()`); fehlt sie, startet die App nicht.
2. **Service** — Sichtbarkeit (`visible_clause`), Änderungsrecht am Objekttyp, Sonderregeln (Autor, Zuweisung).
3. **Datenbank** — RLS je Firma, zusammengesetzte Fremdschlüssel, Spaltenrechte, nur anhängende Tabellen.

Das Frontend ist nie Sicherheitsinstanz: Alle Tests laufen direkt gegen die API.

## Sichtbarkeit eines Objekts
```
sichtbar = Modulrecht des Typs (z. B. finance.read für receipt)
           UND ( objects.read_all  ODER  selbst angelegt  ODER  Freigabe in object_grants )
```
Unsichtbar ⇒ **404** (nie 403): Fremde Firma, nicht freigegeben, Typ ohne Modulrecht und „gibt es nicht"
sehen identisch aus. **403** gibt es nur, wenn das Objekt sichtbar ist bzw. die Route selbst ein Recht verlangt,
das fehlt (`permission_denied` mit Name des Rechts).

## Neue Rechte (Registry)

| Recht | Bedeutung |
| --- | --- |
| `objects.read_all` | Sichtbereich „alle Objekte der eigenen Module" (ohne: nur Eigenes + Freigegebenes) |
| `objects.share` | Objekte für Mitglieder freigeben/entziehen, Freigaben ansehen |
| `comments.read` / `comments.create` | Kommentare lesen / schreiben, eigene bearbeiten und löschen |
| `comments.moderate` | fremde Kommentare löschen (nicht bearbeiten) |
| `activity.read` | Aktivitätsverlauf (Firma und Objekt) |
| `audit.export` | Audit als CSV exportieren (`audit.read` reicht nicht) |
| `contracts.read` / `contracts.update` | Objekttyp Vertrag |
| `vehicles.read` / `vehicles.update` | Fahrten/Fahrzeuge (Objekttyp `trip`) |
| `travel.read` / `travel.update` | Reisen/Reisekosten (`travel`) |
| `hospitality.read` / `hospitality.update` | Bewirtung (`entertainment`) |
| `suppliers.read` / `suppliers.update` | Lieferanten (`supplier`) |

Benennung `.update` statt `.write`, weil die ganze Registry so aufgebaut ist (`customers.update`, `tasks.update` …).
`create`/`delete`/`export` je Fachrecht kommen erst mit dem Fachmodul — keine Rechte ohne Funktion.

Bestehende Rechte werden für Objekttypen wiederverwendet (Tabelle in `docs/core-object-model.md`).

## Sonderregeln im Service

| Regel | Ergebnis bei Verstoß |
| --- | --- |
| Zuweisen an andere braucht `tasks.assign` | 403 |
| Verantwortlicher muss `tasks.read` haben | 422 |
| Zuweisung an Mitglied ohne `objects.read_all` → automatische Freigabe der Aufgabe (`source = task_assignment`, nicht des Bezugsobjekts). Bei Neuzuweisung oder Entfernen der Zuweisung entfällt **nur** diese automatische Freigabe; eine manuelle (`source = manual`) bleibt. `DELETE …/grants/{member}` entzieht nur die manuelle. | — |
| Pausierte Firma: **jede** schreibende Route mit Principal (zentral, M3) | 403 `tenant_paused` |
| Verknüpfen/Entfernen braucht Änderungsrecht am Quellobjekt, beide Seiten sichtbar | 403 / 404 |
| Kommentar bearbeiten: nur Autor, nur 15 Minuten, nicht gelöscht | 403 / 409 |
| Kommentar löschen: Autor oder `comments.moderate` | 403 |
| Erwähnung/Zuweisung/Freigabe nur für aktive Mitglieder dieser Firma | 404 |
| Benachrichtigung: Empfänger aktiv, Recht der Art, Objekt sichtbar — beim Zustellen **und** beim Lesen | still nicht zugestellt / ausgeblendet |
| Download nur bei `scan_status = clean` | 409 `document_quarantined` |

## Routen und ihre Marke

| Methode | Pfad | Marke / Recht |
| --- | --- | --- |
| `GET` | `/api/v1/objects/{ref}` | authenticated (+ Sichtbarkeit) |
| `GET` | `/api/v1/objects/{ref}/links` | authenticated (+ Sichtbarkeit beider Seiten) |
| `POST` | `/api/v1/objects/{ref}/links` | authenticated (+ Änderungsrecht Quelle) |
| `DELETE` | `/api/v1/links/{ref}` | authenticated (+ Änderungsrecht Quelle) |
| `GET` | `/api/v1/objects/{ref}/grants` | objects.share |
| `POST` | `/api/v1/objects/{ref}/grants` | objects.share |
| `DELETE` | `/api/v1/objects/{ref}/grants/{member}` | objects.share |
| `GET` | `/api/v1/activities` | activity.read |
| `GET` | `/api/v1/objects/{ref}/activities` | activity.read |
| `GET` | `/api/v1/tasks` | tasks.read |
| `POST` | `/api/v1/tasks` | tasks.create |
| `POST` | `/api/v1/objects/{ref}/tasks` | tasks.create |
| `GET` | `/api/v1/tasks/{ref}` | tasks.read |
| `PATCH` | `/api/v1/tasks/{ref}` | tasks.update (+ tasks.assign für Zuweisung an andere) |
| `POST` | `/api/v1/tasks/{ref}/attachments` | tasks.update |
| `GET` | `/api/v1/objects/{ref}/comments` | comments.read |
| `POST` | `/api/v1/objects/{ref}/comments` | comments.create |
| `PATCH` | `/api/v1/comments/{ref}` | comments.create (+ Autor, 15 min) |
| `DELETE` | `/api/v1/comments/{ref}` | comments.create (+ Autor oder comments.moderate, Grund Pflicht) |
| `GET` | `/api/v1/comments/{ref}/revisions` | audit.read (+ Objekt sichtbar) |
| `POST` | `/api/v1/comments/{ref}/tasks` | tasks.create |
| `POST` | `/api/v1/documents` | files.upload |
| `GET` | `/api/v1/documents` | files.read |
| `GET` | `/api/v1/documents/{ref}` | files.read |
| `GET` | `/api/v1/documents/{ref}/content` | files.read (+ Virenprüfung) |
| `POST` | `/api/v1/documents/{ref}/review` | files.update |
| `GET` | `/api/v1/notifications` | authenticated (nur eigene) |
| `POST` | `/api/v1/notifications/{ref}/read` | authenticated (nur eigene) |
| `POST` | `/api/v1/notifications/read-all` | authenticated (nur eigene) |
| `GET` | `/api/v1/search` | authenticated (Ergebnis je Typ gefiltert) |
| `GET` | `/api/v1/audit` | audit.read |
| `GET` | `/api/v1/audit/export` | audit.export |

Mitglieder- und Firmenrouten: `docs/m3-mandanten.md`. `tests/test_core_docs.py` prüft, dass beide Tabellen zusammen
jede `/api/v1`-Route (außer `/auth`) mit ihrer tatsächlichen Marke enthalten.

## Getestete Angriffe (alle gegen die echte API und PostgreSQL)

| Szenario | Test |
| --- | --- |
| User Firma A → Objekt Firma B, **jede** Route mit Pfad-ID (Generator) | `test_core_security.py::test_idor_jede_route_mit_id_liefert_404_fuer_fremde_firma` |
| eigenes Objekt + fremdes Ziel/Mitglied/Dokument | ebd. („Gemischt") |
| fremde IDs in Listen, Filtern, Suche | `test_fremde_ids_in_listen_filtern_und_suche_unsichtbar` |
| ohne Rechte / ohne Kommentarrecht / ohne Exportrecht / ohne Modulrecht | `test_ohne_*` |
| Steuerberater nur Freigegebenes, Entzug wirkt sofort | `test_steuerberater_sieht_nur_freigegebene_objekte` |
| Verweis über Firmengrenzen direkt in SQL | `test_core_objects.py::test_verweis_auf_fremde_firma_scheitert_in_der_datenbank` |
| Spalten manipulieren (Typ, Autor, Scanstatus, Empfänger) | `test_spaltenrechte_verhindern_manipulation` |
| Audit/Aktivität ändern oder löschen | `test_audit_ist_unveraenderbar`, `test_aktivitaeten_nur_anhaengend` |
| Benachrichtigung über unsichtbares Objekt | `test_core_notify_search.py::test_erwaehnung_*`, `test_rechteentzug_*` |

Für jede Schutzregel gibt es eine Mutation in `scripts/mutation-check.sh` (Abschnitt „C0").
