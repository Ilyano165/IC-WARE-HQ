# Aktivität, Audit, Benachrichtigungen (C0)

## Aktivität ≠ Audit

| | Aktivität (`activities`) | Audit (`audit_events`) |
| --- | --- | --- |
| Frage | „Was ist mit diesem Beleg passiert?" | „Wer hat wann was getan — nachweisbar?" |
| Leser | jeder, der das Objekt sieht, mit `activity.read` | nur `audit.read`; Export nur `audit.export` |
| Inhalt | Verb, Objekt, Akteur, kleine Daten (z. B. Status alt/neu) | Aktion, Ziel, Akteur, Request-ID, geschwärzte Daten |
| Was nie drinsteht | Kommentartexte, Beträge, Beschreibungen, Refs auf evtl. unsichtbare Objekte | Kommentartexte, Beträge, Beschreibungen (nur Länge/Hash) |
| Ändern/Löschen | App-Rolle hat nur `SELECT, INSERT` | nur `SELECT, INSERT` **und** Trigger gegen UPDATE/DELETE/TRUNCATE (auch für den Besitzer) |
| API | `GET /api/v1/activities`, `GET /api/v1/objects/{ref}/activities` | `GET /api/v1/audit`, `GET /api/v1/audit/export` — keine schreibende Route |

Beide werden in **derselben Transaktion** wie die fachliche Änderung geschrieben: Scheitert die Änderung,
gibt es weder Aktivität noch Audit. Der Audit-Export protokolliert sich selbst (`audit.exported`).

### Verben (`ichq/activity/service.py::VERBS`)
`document.uploaded` (Beleg hochgeladen) · `document.reviewed` (Beleg geprüft) · `task.created` ·
`task.updated` · `task.status_changed` · `task.assigned` · `comment.created` · `comment.question_asked`
(Rückfrage, z. B. Steuerberater) · `comment.edited` · `comment.deleted` · `object.linked` · `object.unlinked` ·
`object.shared` · `object.unshared` — reserviert für Fachmodule: `invoice.created` (Rechnung erstellt),
`payment.received` (Zahlung eingegangen), `project.status_changed`.

Unbekannte Verben sind ein Programmierfehler (`ValueError`). Die Datenbank prüft das Format.

### Lesen
Neueste zuerst (oder `order=asc`), Cursor-Paginierung, Filter `verb`, `object_type`, `actor`, `since`, `until`.
Der Verlauf enthält nur Aktivitäten zu Objekten, die der Leser sehen darf — für einen Steuerberater also nur
die freigegebenen Belege.

## Benachrichtigungen

```
fachliche Änderung ──(gleiche Transaktion)──▶ outbox_events
                                                   │ Worker, Mandantenkontext der Firma
                                                   ▼
                       notifications.handlers  ──▶ deliver(empfänger, art, objekt)
                                                   ├─ Mitgliedschaft aktiv, Firma nutzbar?
                                                   ├─ Recht der Art (z. B. comments.read)?
                                                   ├─ Objekt für den Empfänger sichtbar?
                                                   └─ Kanäle: in_app ✔ · email ✗ · push ✗
```

| Art | Auslöser | Empfänger | Recht |
| --- | --- | --- | --- |
| `comment.mention` | Kommentar mit Erwähnung | Erwähnte (nicht der Autor) | comments.read |
| `comment.question` | Kommentar `kind=question` („Steuerberater hat eine Rückfrage") | Ersteller des Objekts | comments.read |
| `task.assigned` | Aufgabe an jemand anderen zugewiesen | Verantwortlicher | tasks.read |
| `document.review_pending` | Upload („Beleg wartet auf Prüfung") | Mitglieder mit files.update (max. 50, nicht Uploader) | files.update |
| `task.overdue` | Regel, `ichq notifications-scan` | Verantwortlicher | tasks.read |
| `invoice.overdue` | reserviert („Rechnung seit 14 Tagen überfällig") — Regel kommt mit Rechnungen | — | invoices.read |
| `contract.expiring` | reserviert („Vertrag läuft in 30 Tagen aus") — Regel kommt mit Verträgen | — | contracts.read |

- **Rechte beim Zustellen und beim Lesen.** Wird eine Freigabe entzogen, verschwinden zugehörige
  Benachrichtigungen aus der Liste.
- **Inhalt:** Titel des Objekts + Art, keine Beträge, keine Kommentartexte (M0).
- **Doppelt zustellen** verhindert `dedup_key` (eindeutig je Empfänger).
- **Geplante Regeln:** `ichq notifications-scan [--date JJJJ-MM-TT]` läuft je aktiver Firma in deren
  Mandantenkontext. Ein Zeitplan (Cron/Systemd-Timer) ist noch nicht eingerichtet.
- **Worker:** `ichq worker` lädt die Handler und bricht ab, wenn für ein Core-Ereignis keiner registriert ist
  (`assert_handlers`).
- **E-Mail/Push:** Schema (`channel`) und Registry (`CHANNELS`) sind vorbereitet; Versand gibt es noch nicht.
  Für E-Mail gilt dann: nur Titel + Link, Rechteprüfung unverändert über `deliver`.

## Aufgaben und Kommentare

- Aufgabe = Objekt `task` + Zeile in `tasks`: Titel, Beschreibung, Verantwortlicher, Fälligkeit, Status
  (`open → in_progress → blocked → done | cancelled`, frei wechselbar, `completed_at` bei `done`), Priorität,
  Ersteller, Bezug (`subject`), Herkunftskommentar, Kommentare (an das Aufgabenobjekt), Anhänge
  (Verknüpfung `attachment` → Dokument).
- Aus Fachobjekt: `POST /api/v1/objects/{ref}/tasks` (z. B. Beleg → „IBAN prüfen").
  Aus Kommentar: `POST /api/v1/comments/{ref}/tasks` — Bezug ist das Objekt des Kommentars,
  Beschreibung der Kommentartext.
- Kommentare: Autor, Zeitpunkt, `kind` (`note`/`question`), Erwähnungen, Bearbeiten 15 Minuten nur durch den
  Autor, Löschen weich (Text weg, Hülle bleibt). Keine Kommentare ohne Firmenbezug (FK + RLS).
