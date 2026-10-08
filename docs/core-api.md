# Core-API (C0) — Referenz

Alle Pfade unter `/api/v1`. Anmeldung per Sitzungs-Cookie (siehe M2), Firma gewählt. Rechte je Route:
`docs/core-permissions.md`. Maschinenlesbar: OpenAPI unter `/openapi.json` (nur mit `ICHQ_EXPOSE_DOCS=true`).

## Konventionen

- **IDs:** nur `public_id` (32 Hex-Zeichen). Mitglieder ebenfalls per `public_id` (aus `GET /members`).
- **Eingaben:** JSON, unbekannte Felder → 422, Leerzeichen am Rand werden entfernt, Längen begrenzt.
- **Listen:** `limit` (1–100, Standard 25), `cursor` (aus `next_cursor`), Antwort `{"items": [...], "next_cursor": "…" | null}`.
  Sortierung/Richtung je Liste über `sort`/`order`; ein Cursor gilt nur für die Sortierung, mit der er entstand.
- **Fehler:** immer `application/problem+json` (RFC 9457):
  ```json
  {"type": "urn:ichq:problem:not_found", "title": "Nicht gefunden", "status": 404, "code": "not_found",
   "request_id": "01a1…", "detail": "…"}
  ```
  Validierungsfehler zusätzlich `errors: [{"loc": [...], "msg": "...", "type": "..."}]` — ohne Eingabewerte.

| Status | `code` | Wann |
| --- | --- | --- |
| 401 | `authentication_required` | keine Sitzung |
| 403 | `tenant_required` | angemeldet, keine Firma gewählt |
| 403 | `permission_denied` | Recht der Route oder Sonderregel fehlt |
| 403 | `tenant_paused` | schreibend in pausierter Firma |
| 404 | `not_found` | unbekannt, fremde Firma, nicht sichtbar, ungültiges ID-Format |
| 409 | `conflict` | doppelt verknüpft, Kommentar nicht mehr bearbeitbar, schon geprüft |
| 409 | `document_quarantined` | Download vor Virenprüfung |
| 413 / 415 | `payload_too_large` / `unsupported_media_type` | Upload > 20 MiB / Typ nicht erlaubt |
| 422 | `validation_failed` | Eingabe, Filter, Sortierung, Cursor ungültig |

## Objekte, Verknüpfungen, Freigaben

| Methode | Pfad | Eingabe | Antwort |
| --- | --- | --- | --- |
| GET | `/objects/{ref}` | — | `{id, type, title, created_at, updated_at, created_by, archived}` |
| GET | `/objects/{ref}/links` | — | `{items: [{id, link_type, direction: outgoing\|incoming, object: {id,type,title}, created_at}]}` (≤ 200) |
| POST | `/objects/{ref}/links` | `{target, link_type}` | 201 `{id, link_type, source, target}` |
| DELETE | `/links/{ref}` | — | 204 |
| GET | `/objects/{ref}/grants` | — | `{items: [{id, display_name}]}` (≤ 200) |
| POST | `/objects/{ref}/grants` | `{member}` | 201 `{object, member, created}` |
| DELETE | `/objects/{ref}/grants/{member}` | — | 204 |
| GET | `/members` | `q`, `cursor`, `limit` | aktive Mitglieder `{id, display_name}`, sortiert nach Name |

## Aktivitäten

| Methode | Pfad | Filter | Antwort-Element |
| --- | --- | --- | --- |
| GET | `/activities` | `verb`, `object_type`, `actor`, `since`, `until`, `order`, `cursor`, `limit` | `{verb, label, occurred_at, object: {id,type,title}, actor, data}` |
| GET | `/objects/{ref}/activities` | `order`, `cursor`, `limit` | wie oben |

## Aufgaben

| Methode | Pfad | Eingabe |
| --- | --- | --- |
| GET | `/tasks` | Filter `status` (mehrfach), `priority` (mehrfach), `assignee` (`me` oder ID), `subject`, `due_before`; `sort` = `created_at`\|`due_date`\|`priority`\|`title`; `order`; `cursor`; `limit` |
| POST | `/tasks` | `{title, description?, assignee?, due_date?, priority?, subject?}` |
| POST | `/objects/{ref}/tasks` | `{title, description?, assignee?, due_date?, priority?}` — Bezug = `{ref}` |
| GET | `/tasks/{ref}` | — |
| PATCH | `/tasks/{ref}` | beliebige Teilmenge von `{title, description, assignee, due_date, priority, status}`; `assignee: null` entfernt |
| POST | `/tasks/{ref}/attachments` | `{document}` → Verknüpfung `attachment` |

Aufgabe: `{id, type, title, created_at, updated_at, created_by, archived, description, status, priority,
assignee, due_date, completed_at, subject}` — `subject` nur, wenn der Aufrufer das Bezugsobjekt sehen darf.
`priority`: `low|normal|high|urgent`; `status`: `open|in_progress|blocked|done|cancelled`.

## Kommentare

| Methode | Pfad | Eingabe |
| --- | --- | --- |
| GET | `/objects/{ref}/comments` | `cursor`, `limit` (älteste zuerst) |
| POST | `/objects/{ref}/comments` | `{body (1–10 000), kind: note\|question, mentions: [member-ID] (≤ 20)}` |
| PATCH | `/comments/{ref}` | `{body}` |
| DELETE | `/comments/{ref}` | — (204) |
| POST | `/comments/{ref}/tasks` | `{title, assignee?, due_date?, priority?}` |

Kommentar: `{id, kind, body (null wenn gelöscht), author, created_at, edited_at, deleted, deleted_at, mentions}`.

## Dokumente

| Methode | Pfad | Eingabe |
| --- | --- | --- |
| POST | `/documents?filename=…` | Rohdaten im Body, `Content-Type`: pdf, png, jpeg, xml, txt, csv; ≤ 20 MiB |
| GET | `/documents` | `review_status`, `sort` = `created_at`\|`title`, `order`, `cursor`, `limit` |
| GET | `/documents/{ref}` | — |
| GET | `/documents/{ref}/content` | — (nur `scan_status = clean`, sonst 409) |
| POST | `/documents/{ref}/review` | `{decision: approved\|rejected}` — einmalig |

Dokument: Objektfelder + `{filename, content_type, size_bytes, sha256, scan_status, review_status, reviewed_by, reviewed_at}`.

## Benachrichtigungen, Suche, Audit

| Methode | Pfad | Eingabe | Antwort |
| --- | --- | --- | --- |
| GET | `/notifications` | `unread`, `cursor`, `limit` | `{items: [{id, kind, title, created_at, read, object}], next_cursor, unread_count}` |
| POST | `/notifications/{ref}/read` | — | 204 |
| POST | `/notifications/read-all` | — | `{updated}` |
| GET | `/search` | `q` (2–100), `group` (mehrfach), `per_group` (1–20, Std. 5) | `{query, groups: {persons, companies, projects, receipts, invoices, tasks, documents: {items: [{id,type,title}], has_more}}}` |
| GET | `/audit` | `action`, `target_type`, `target_id`, `since`, `until`, `cursor`, `limit` | `{items: [{action, occurred_at, target_type, target_id, request_id, data, actor}], next_cursor}` |
| GET | `/audit/export` | `action`, `target_type`, `since`, `until`, `max_rows` (≤ 10 000) | CSV; Kopfzeile `x-ichq-truncated` |

Suche: Präfixsuche je Wort (`tank bel` findet „Tankbeleg"), PostgreSQL-Konfiguration `simple` (keine
Stammformen), sortiert nach Relevanz. Personen = Mitglieder (`users.read`) + Objekte vom Typ `employee`.
