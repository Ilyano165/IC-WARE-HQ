# D0 · Dashboard

Entscheidungen: [ADR-014](adr/014-dashboard-architektur.md). Code: `src/ichq/dashboard/` (Registry, Loader,
Zusammenstellung), Route `src/ichq/api/v1/dashboard.py`, Oberfläche `src/ichq/web/js/views/dashboard.js`.

Frage, die es beantwortet: **„Was muss ich heute in meiner Firma wissen oder erledigen?"** — je Person nach
**effektiven Rechten**, jede Zahl führt zur Liste, aus der sie gezählt wurde, und von dort zum Objekt.

## Architektur
```
Browser ──GET /api/v1/dashboard──▶ require("dashboard.read")          (Anmeldung, Firma, Recht)
                                   context(): „heute" in Firmen-Zeitzone
                                   für jedes Widget der Registry:
                                     effektive Rechte vorhanden? (decide — Flags, DENY, Rollen)  nein → weglassen
                                     Savepoint → Loader → Zahlen + Einträge (visible_clause, LIMIT)
                                   geplante Module mit passenden Rechten (ohne Werte)
```
Kein Widget-Code im Browser entscheidet über Daten. Die Oberfläche rendert generisch: Kennzahlen (Link = Liste +
Filter), Einträge (Link = Objekt), leere Zustände.

## Widgets
| Schlüssel | Titel | Rechte (alle nötig) | Kennzahlen → Liste | Einträge |
| --- | --- | --- | --- | --- |
| `warnings` | Hinweise | — | — | Firma pausiert; eigene überfällige Aufgaben (`tasks.read`); Dokumente mit Schadsoftware (`files.read`); nur eine Person mit Verwaltungsrechten (`users.read`+`roles.read`) |
| `my_tasks` | Meine Aufgaben | `tasks.read` | Offen, Überfällig, Hoch/dringend → `/tasks?assignee=me&status=…` | 6 offene, nach Fälligkeit |
| `questions` | Offene Rückfragen | `comments.read` | Offen → `/questions?open_only=true` | 6 neueste, Link zum Objekt |
| `notifications` | Mitteilungen | — | Ungelesen | 6 ungelesene; Rückfrage/Überfällig/Prüfung hervorgehoben |
| `documents` | Dokumente & Belege | `files.read` | Ungeprüft, Neu (7 Tage), Nicht zugeordnet, In Virenprüfung → `/documents?…` | 6 ungeprüfte |
| `team_tasks` | Aufgaben der Firma | `tasks.read` + `objects.read_all` | Offen, Überfällig, Ohne Zuständige → `/tasks?…` | 6 überfällige |
| `company` | Firma & Team | `users.read` (+ `roles.read` für Admin-Zahl) | Aktive Mitglieder, Offene Einladungen, Mit Verwaltungsrechten | — |
| `activity` | Aktivität | `activity.read` | — | 8 neueste sichtbare |

**Geplant (ohne Werte, nur mit Rechten sichtbar):** Liquidität, Überfällige Zahlungen (S6, `finance.read`) · Offene
Rechnungen (S5, `invoices.read`) · Fehlende Belege (S1) · Steuerfristen (S8) · Monatsabschluss, DATEV-/Exportstatus
(S7, `finance.export`) · Projekte, Projektprofitabilität · Verträge · Reisen (S3) · Fahrten (S2) · Kunden & Anfragen
(CRM). **Arbeitszeiten** fehlen bewusst: dafür gibt es weder Modul noch Recht in der Registry.

## API
| Methode | Pfad | Regel |
| --- | --- | --- |
| `GET` | `/api/v1/dashboard` | dashboard.read (+ je Widget dessen Rechte; `?widget=` unbekannt/ohne Recht → 404) |
| `GET` | `/api/v1/questions` | comments.read (+ nur sichtbare Objekte) |

Antwort `/dashboard`: `{today, widgets: [{key, title, size, list, metrics: [{key, label, value, filter, tone}],
items: [{id, type, title, detail, date, tone, list, filter}], empty} | {key, title, size, error}], planned: [{key,
title, module}]}`. Erweiterte Listenfilter: `/tasks?assignee=none`, `/documents?scan_status=…&since=…&unlinked=true`.

## Rechte-Verhalten
- Ohne Anmeldung **401**, ohne gewählte Firma **403 tenant_required**, ohne `dashboard.read` **403**.
- Widgets fehlen, wenn ein Recht fehlt — auch durch Einzelrecht-DENY oder abgeschaltetes Modul (wirkt sofort).
- Zahlen und Einträge nur aus sichtbaren Objekten der eigenen Firma (RLS + `visible_clause`); Mitarbeiter ohne
  `objects.read_all` zählen nur Eigenes/Zugewiesenes/Freigegebenes.

## Rollenvorlagen (Default, je Firma anpassbar) — aus dem Code erzeugt
Quelle `ichq.authz.templates.TEMPLATES`, geprüft durch `tests/test_d0_docs.py`. Gilt für neu aktivierte Firmen;
bestehende Vorlagen-Rollen werden nie überschrieben (Firmen passen sie selbst an).

<!-- vorlagen:start -->
| Modul | Company Admin | Geschäftsführung | Mitarbeiter | Steuerberater |
| --- | --- | --- | --- | --- |
| `activity` | read | read | read | — |
| `audit` | export, read | export, read | — | — |
| `calendar` | create, delete, read, update | create, delete, read, update | create, read, update | — |
| `chat` | create, moderate, read | create, moderate, read | create, read | — |
| `comments` | create, moderate, read | create, moderate, read | create, read | create, read |
| `company` | read, update | read, update | read | read |
| `contracts` | read, update | read, update | — | read |
| `customers` | create, delete, export, read, update | create, delete, export, read, update | — | — |
| `dashboard` | read | read | read | read |
| `files` | delete, read, share, update, upload | delete, read, share, update, upload | read, upload | read |
| `finance` | approve, create, export, read, update | approve, create, export, read, update | — | export, read |
| `hospitality` | read, update | read, update | — | read |
| `invoices` | approve, create, delete, export, read, update | approve, create, delete, export, read, update | — | export, read |
| `objects` | read_all, share | read_all, share | — | — |
| `projects` | assign, create, delete, read, update | assign, create, delete, read, update | read | — |
| `roles` | assign, create, delete, read, update | read | — | — |
| `settings` | read, update | read, update | — | — |
| `suppliers` | read, update | read, update | — | read |
| `tasks` | assign, create, delete, read, update | assign, create, delete, read, update | create, read, update | create, read |
| `travel` | read, update | read, update | read, update | read |
| `users` | create, deactivate, override, read, update | create, read | — | — |
| `vehicles` | read, update | read, update | read, update | read |
<!-- vorlagen:end -->

Begründung je Vorlage (D0-Auftrag, Abschnitt 2):
- **Geschäftsführung:** alles Geschäftliche inkl. Finanzen, Rechnungen, Kunden, Projekte, Audit, `objects.read_all`;
  **keine** Rechteverwaltung (`roles.create/update/delete/assign`, `users.override/update/deactivate`) — die
  kommt nur über eine zusätzliche Admin-Rolle.
- **Mitarbeiter:** eigene Aufgaben, zugewiesene Projekte, eigene Dokumente, Reisen/Fahrten, Termine, Chat; **ohne**
  `objects.read_all`, Finanzen, Rechnungen, Kunden, Mitglieder, Bewirtung, Audit.
- **Steuerberater:** Finanzen/Rechnungen lesen und exportieren, Dokumente lesen, Rückfragen (Kommentare),
  Reisen/Fahrten/Bewirtung/Lieferanten/Verträge lesen; **ohne** `objects.read_all` (nur Freigegebenes), ohne
  Mitglieder/Rollen, ohne Prüfen/Freigeben von Dokumenten (`files.update`).

## Mobil
Unter 900 px eine Spalte, Kennzahlen zweispaltig, Navigation als Schublade, Suche in eigener Zeile. Gerüst-Karten in
Endgröße während des Ladens (kein Springen der Seite). Getestet bei 360 px ohne Querscrollen.

## Erweiterung um ein Widget
1. Loader mit `@register("key", "Titel", ("modul.read",))` — Zahlen per Aggregat mit den Filterbedingungen der Liste.
2. Schlüssel in `REIHENFOLGE`; Planeintrag aus `PLANNED` entfernen.
3. Listenfilter ergänzen, falls nötig; Test „jede Zahl = Liste" erweitern; Mutation für die Rechte/Filter.
4. Oberfläche: nur nötig, wenn ein neuer Listentyp verlinkt wird (`LISTE` in `dashboard.js`).

## Bekannte Grenzen
- „Offen" bei Rückfragen ist abgeleitet (Antwort einer anderen Person), nicht ausdrücklich markiert.
- Keine Echtzeit-Aktualisierung; neu laden per Seitenwechsel.
- Kennzahlen werden je Aufruf berechnet (wenige Aggregat-Abfragen); bei großen Firmen messen (M24).
