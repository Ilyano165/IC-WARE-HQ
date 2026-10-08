# Core-Objektmodell (C0)

Entscheidung und Alternativen: [ADR-008](adr/008-globales-objektmodell.md). Hier: wie es funktioniert und
wie ein neues Fachmodul es benutzt.

## Bausteine

```
                        objects  (eine Zeile je Fachobjekt, typisiert)
      tenant_id · id · type · public_id · title · search_text · search_vector · created_by · archived_at
          ▲ (tenant_id, id, type)                      ▲ (tenant_id, id)
          │                                            │
   tasks · documents · (später: invoices, trips …)    comments · activities · object_links
   Fachtabelle mit derselben id                        object_grants · notifications · tasks.subject
```

| Tabelle | Zweck | Schlüssel zu `objects` |
| --- | --- | --- |
| `objects` | Identität, Typ, Titel, Suchtext, Ersteller | — |
| `tasks`, `documents` | Fachdaten | `(tenant_id, id, object_type)` → `(tenant_id, id, type)`, `object_type` per CHECK fix |
| `object_links` | typisierte Verknüpfung A → B | Quelle und Ziel je `(tenant_id, id, type)`; CHECK `ck_object_links_rule` |
| `object_grants` | Freigabe eines Objekts für ein Mitglied, mit Quelle `manual` / `task_assignment` | `(tenant_id, object_id)` |
| `comments` (+ `comment_mentions`, `comment_revisions`) | Kommentare, Erwähnungen, jede Fassung (Trigger) | `(tenant_id, object_id)` |
| `activities` | Benutzerverlauf (nicht Audit) | `(tenant_id, object_id)` |
| `notifications` | zugestellte Benachrichtigungen | `(tenant_id, object_id)` optional |

Alle Tabellen: `tenant_id NOT NULL`, `ENABLE` + `FORCE ROW LEVEL SECURITY`, Policy mit `USING` und
`WITH CHECK`, nur die nötigen `GRANT`s (teils spaltengenau). Ein Verweis über Firmengrenzen ist durch die
zusammengesetzten Fremdschlüssel **in der Datenbank** unmöglich (`test_verweis_auf_fremde_firma_scheitert_in_der_datenbank`).

## Objekttypen (Registry `ichq/objects/registry.py`)

| Typ | Bezeichnung | Suchgruppe | Lesen | Ändern | Fachmodul |
| --- | --- | --- | --- | --- | --- |
| `company` | Firma (extern) | companies | customers.read | customers.update | reserviert |
| `customer` | Kunde | companies | customers.read | customers.update | reserviert |
| `supplier` | Lieferant | companies | suppliers.read | suppliers.update | reserviert |
| `employee` | Mitarbeiter | persons | users.read | users.update | reserviert |
| `project` | Projekt | projects | projects.read | projects.update | reserviert |
| `task` | Aufgabe | tasks | tasks.read | tasks.update | **C0** |
| `receipt` | Beleg | receipts | finance.read | finance.update | reserviert |
| `invoice` | Rechnung | invoices | invoices.read | invoices.update | reserviert |
| `payment` | Zahlung | invoices | finance.read | finance.update | reserviert |
| `trip` | Fahrt | receipts | vehicles.read | vehicles.update | reserviert |
| `travel` | Reise | receipts | travel.read | travel.update | reserviert |
| `entertainment` | Bewirtung | receipts | hospitality.read | hospitality.update | reserviert |
| `contract` | Vertrag | documents | contracts.read | contracts.update | reserviert |
| `asset` | Anlage | receipts | finance.read | finance.update | reserviert |
| `website` | Website | projects | projects.read | projects.update | reserviert |
| `document` | Dokument | documents | files.read | files.update | **C0** |

„Firma" ist hier ein **Geschäftspartner** (CRM), nicht der Mandant. Fahrten, Reisen, Bewirtung und Lieferanten
haben eigene Rechte (Entscheidung vom 08.10.2026); `finance.read`/`customers.read` reichen dafür nicht mehr.

## Verknüpfungstypen

| Code | Bedeutung | erlaubt von → nach |
| --- | --- | --- |
| `related` | verknüpft mit | alle → alle |
| `attachment` | Anhang | alle → document |
| `part_of` | gehört zu Projekt | task, document, receipt, invoice, contract, website → project |
| `billed_to` | berechnet an | invoice → customer, company |
| `pays` | bezahlt | payment → invoice, receipt |
| `evidence` | Nachweis für | receipt, document → trip, travel, entertainment, invoice, payment, asset, contract |
| `party` | Vertragspartei | contract → customer, supplier, company, employee |

Die Regel steht zweimal: im Code (`LinkType.allows`, ergibt 422) und als CHECK in der Datenbank (letzte
Verteidigungslinie). Selbstverknüpfung ist verboten, Doppelte ergeben 409.

## Öffentliche IDs
- `public_id`: 32 Hex-Zeichen aus `secrets.token_hex(16)` — 128 Bit Zufall, kein Zeitanteil, kein Bezug zum
  Primärschlüssel (UUIDv7). Global eindeutig.
- Mitgliedschaften haben seit `0003_core` ebenfalls eine `public_id` (für Zuweisung, Erwähnung, Freigabe).
- Interne UUIDs erscheinen in keiner Core-Antwort (Ausnahme bleibt `/api/v1/me` aus M1).
- Ungültiges Format, fremde Firma, unsichtbar, gelöscht → **immer 404** mit identischer Antwort.

## Ein neues Fachmodul anschließen (Beispiel Rechnung)
1. Typ ist in der Registry schon reserviert → `implemented=True` setzen.
2. Migration: Fachtabelle `invoices` mit `id`, `tenant_id`, `object_type` (Default + CHECK `= 'invoice'`),
   FK `(tenant_id, id, object_type) → objects(tenant_id, id, type)`, Mandanten-Checkliste aus `docs/migrations.md`.
3. Service: `create_object(type_="invoice", title=…, search_text=…)`, dann Fachzeile; `activity.record(...)`,
   `audit.record(...)`, ggf. `emit_event(...)` — alles in derselben Transaktion.
4. Lesen nur über `resolve(session, principal, ref, type_="invoice")` bzw. Listen mit `visible_clause(principal)`
   und `keyset(...)`.
5. Neue Benachrichtigungsregel (z. B. „seit 14 Tagen überfällig") in `ichq/notifications/handlers.py::RULES`.
6. Neue Route: Pfad unter einer Präfixzuordnung im IDOR-Test (`tests/test_core_security.py::_ref_fuer`) —
   sonst schlägt der Generator fehl.

## Paginierung
Alle Listen: Keyset-Cursor (`ichq/db/paging.py`), `limit` 1–100 (Standard 25), hart begrenzt auch im Service.
Der Cursor ist an Sortierung und Richtung gebunden; ein manipulierter Cursor ist 422 oder verschiebt nur den
Start — Mandant und Sichtbarkeit stecken in der Abfrage. Ohne Cursor, aber begrenzt: Verknüpfungen und
Freigaben eines Objekts (je höchstens 200).
