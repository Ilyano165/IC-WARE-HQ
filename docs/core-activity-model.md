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
- **Geplante Regeln (Fälligkeits-Scan):** eigener Job `ichq.notifications.jobs.run_scan`, Einstieg
  `ichq notifications-scan [--date JJJJ-MM-TT]`, erste Betriebsvariante **systemd-Timer**
  (`deploy/systemd/ichq-notifications-scan.{service,timer}`, täglich 05:47 Europe/Berlin, `Persistent=true`).
  Läuft nie im Webprozess. Idempotent über `dedup_key` + Unique-Index (erneuter Lauf stellt nichts doppelt zu);
  Advisory-Lock gegen Parallelläufe (zweiter Lauf endet mit „übersprungen", Exitcode 0); je Firma eigene
  Transaktion, Fehler einer Firma werden geloggt (ohne Inhalte), die übrigen laufen weiter, Exitcode 1.
  Ein anderer Scheduler ruft dieselbe Funktion auf — die Regeln (`handlers.RULES`) bleiben unverändert.
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
  Autor. Keine Kommentare ohne Firmenbezug (FK + RLS).

## Gelöschte Kommentare (Tombstone)

Kommentare werden **nie physisch gelöscht**:

| Ebene | Was passiert |
| --- | --- |
| Kommentarzeile | `deleted_at`, `deleted_by_membership_id`, `delete_reason` (Pflicht, 3–500 Zeichen) gesetzt; Text in der Zeile geleert. Die normale Ansicht zeigt „gelöscht" mit wer/wann/Grund, ohne Text. |
| `comment_revisions` | **jede** Fassung: `created`, jede `edited`, und `deleted` mit dem Text zum Löschzeitpunkt, Akteur und Grund. Geschrieben von einem **Datenbank-Trigger** (`ichq_comment_history`, SECURITY DEFINER) — auch ein direktes SQL-UPDATE der App-Rolle hinterlässt eine Fassung. |
| Schutz | App-Rolle darf `comment_revisions` nur lesen; UPDATE/DELETE/TRUNCATE verhindert ein Trigger auch für den Besitzer. Nach dem Löschen ist die Kommentarzeile unveränderlich (Trigger `ichq_comment_frozen`). |
| Lesen der Historie | `GET /api/v1/comments/{ref}/revisions` — nur `audit.read` und nur, wenn das Objekt sichtbar ist. |

### Sind Kommentare GoBD-relevant? — **ungeklärt**

Keine rechtliche Bewertung, nur die sichtbaren Unsicherheiten:
- Nach § 147 Abs. 1 AO sind u. a. Buchungsbelege, empfangene und abgesandte **Handels- oder Geschäftsbriefe** und
  „sonstige Unterlagen, soweit sie für die Besteuerung von Bedeutung sind" aufzubewahren. Ob eine Rückfrage des
  Steuerberaters zu einem Beleg oder ein interner Kommentar dazu zählt, hängt vom Inhalt ab — das kann HQ nicht
  allgemein entscheiden.
- Die GoBD verlangen für aufbewahrungspflichtige Unterlagen Unveränderbarkeit bzw. protokollierte Änderungen
  (Rz. 58 ff., Fassung 2019 gelesen; Fassung 14.07.2025 nicht im Volltext geprüft). Das Tombstone-Modell erfüllt die
  *technische* Seite (nichts verschwindet, jede Änderung ist protokolliert) — ob es *rechtlich* genügt, ist nicht geprüft.
- **Gegenläufig: DSGVO.** Kommentare können personenbezogene Daten enthalten. Ein Anspruch auf Löschung (Art. 17 DSGVO)
  kann mit der Aufbewahrung kollidieren; Art. 17 Abs. 3 lit. b kennt Ausnahmen für gesetzliche Aufbewahrungspflichten.
  Eine Löschroutine für Historie nach Fristablauf gibt es noch nicht.
- **Offen, mit Steuerberater/Datenschutz zu klären:** Aufbewahrungsdauer der Historie, ob Kommentare in die
  Verfahrensdokumentation gehören, ob ein Export zur Betriebsprüfung Kommentare enthalten muss.
