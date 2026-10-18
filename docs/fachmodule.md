# Fachmodule (ADR-020)

Kunden, Anfragen, Projekte, Finanzen, Verträge, Reisen und Fahrten — gebaut auf dem Objektmodell (ADR-008) mit
derselben Sichtbarkeit (ADR-009) und denselben Rechten (ADR-011) wie die Core-Plattform. Architektur:
[ADR-020](adr/020-fachmodule-auf-dem-objektmodell.md), Bestandsaufnahme: [enterprise-bestandsaufnahme.md](enterprise-bestandsaufnahme.md).

Allgemein gilt:

* Jede Route hat genau eine Sicherheitsmarke. Sichtbarkeit prüft der Service (`visible_clause`). Unsichtbar oder fremd ⇒ **404**.
* Archivieren statt Löschen: `POST /api/v1/objects/{ref}/archive` bzw. `/restore` (Änderungsrecht des Typs).
* Listen haben Filter, Sortierung und Cursor-Paginierung (höchstens 100 je Seite).

## Kunden und Anfragen (CRM)

| Methode | Pfad | Recht |
| --- | --- | --- |
| `GET` | `/api/v1/customers` | customers.read |
| `GET` | `/api/v1/customers/duplicates` | customers.read |
| `POST` | `/api/v1/customers` | customers.create |
| `GET` | `/api/v1/customers/{ref}` | customers.read |
| `PATCH` | `/api/v1/customers/{ref}` | customers.update |
| `POST` | `/api/v1/customers/{ref}/contacts` | customers.update |
| `PATCH` | `/api/v1/customers/{ref}/contacts/{contact}` | customers.update |
| `DELETE` | `/api/v1/customers/{ref}/contacts/{contact}` | customers.update |
| `POST` | `/api/v1/customers/{ref}/merge` | customers.delete |
| `GET` | `/api/v1/inquiries` | customers.read |
| `POST` | `/api/v1/inquiries` | customers.create |
| `GET` | `/api/v1/inquiries/{ref}` | customers.read |
| `PATCH` | `/api/v1/inquiries/{ref}` | customers.update |

**Dubletten:** Der Name wird normalisiert (Kleinschreibung, Umlaute, ohne Rechtsform wie GmbH/KG/AG), dazu wird die
E-Mail verglichen. Bei einem Treffer antwortet `POST /customers` mit 409. Bewusst trotzdem anlegen geht mit
`allow_duplicate: true` (im Audit vermerkt).
**Zusammenführen** (`customers.delete`): Alle Verweise wandern auf den bleibenden Kunden, die Dublette wird archiviert
und zeigt auf das Ziel. Schützt die Datenbank einen Verweis (z. B. eine ausgestellte Rechnung), scheitert der ganze
Vorgang mit 409 — nichts wird teilweise umgehängt.
**Anfragen:** Status `new → in_progress/waiting → won/lost/closed`. Abschluss setzt `closed_at`, Wiederöffnen leert es
(die Datenbank prüft, dass beides zusammenpasst). Wiedervorlage: `follow_up_before=<Datum>` liefert offene Anfragen mit
fälliger Wiedervorlage. Ein Kunde wird in der Antwort nur genannt, wenn der Aufrufer ihn sehen darf.

## Projekte

| Methode | Pfad | Recht |
| --- | --- | --- |
| `GET` | `/api/v1/projects` | projects.read |
| `POST` | `/api/v1/projects` | projects.create |
| `GET` | `/api/v1/projects/{ref}` | projects.read |
| `PATCH` | `/api/v1/projects/{ref}` | projects.update |
| `PUT` | `/api/v1/projects/{ref}/members/{member}` | projects.assign |
| `DELETE` | `/api/v1/projects/{ref}/members/{member}` | projects.assign |
| `GET` | `/api/v1/projects/{ref}/time-entries` | projects.read |
| `POST` | `/api/v1/projects/{ref}/time-entries` | projects.read |
| `DELETE` | `/api/v1/projects/{ref}/time-entries/{entry}` | projects.read |

* **Status** `planned → active ⇄ on_hold → completed | cancelled`. `completed` setzt `completed_at`, die Datenbank
  prüft, dass beides zusammenpasst. Zeitraum: Ende nicht vor Beginn (422, zusätzlich als DB-CHECK). Budget in Cent.
* **Team = Sichtbarkeit:** Wer ins Team kommt und kein `objects.read_all` hat, bekommt eine Freigabe mit der Quelle
  `project_team`, nur für das Projekt. Beim Entfernen endet genau diese Freigabe, eine manuelle bleibt bestehen. Die
  Projektleitung ist automatisch im Team und kann nicht entfernt werden, solange sie Leitung ist.
* **Kostensätze** (kalkulatorischer Stundensatz je Teammitglied): Setzen und Sehen nur mit `finance.read`.
* **Projektzeiten** sind Aufwand je Projekt, **keine Arbeitszeiterfassung** im arbeitsrechtlichen Sinn (nicht geprüft,
  Produktvision 7). Erfassen kann jedes Teammitglied für sich, für andere braucht es `projects.assign`. Löschen darf,
  wer den Eintrag erfasst hat, oder jemand mit `projects.update` (Audit).
* **Aufgaben** am Projekt sind normale Aufgaben mit `subject` = Projekt (`POST /api/v1/objects/{ref}/tasks`).
  **Dokumente** werden über Verknüpfungen angehängt (`part_of`/`attachment`).

## Rechnungen, Zahlungen, Überfälligkeit

| Methode | Pfad | Recht |
| --- | --- | --- |
| `GET` | `/api/v1/invoices` | invoices.read |
| `POST` | `/api/v1/invoices` | invoices.create |
| `GET` | `/api/v1/invoices/{ref}` | invoices.read |
| `PATCH` | `/api/v1/invoices/{ref}` | invoices.update |
| `POST` | `/api/v1/invoices/{ref}/lines` | invoices.update |
| `PATCH` | `/api/v1/invoices/{ref}/lines/{line}` | invoices.update |
| `DELETE` | `/api/v1/invoices/{ref}/lines/{line}` | invoices.update |
| `POST` | `/api/v1/invoices/{ref}/issue` | invoices.approve |
| `POST` | `/api/v1/invoices/{ref}/dispatches` | invoices.update |
| `POST` | `/api/v1/invoices/{ref}/cancel` | invoices.approve |
| `POST` | `/api/v1/invoices/{ref}/payments` | finance.create |
| `POST` | `/api/v1/invoices/{ref}/payments/{payment}/reverse` | finance.update |
| `POST` | `/api/v1/invoices/{ref}/followups` | invoices.update |

* **Ablauf:** Entwurf (frei änderbar, keine Nummer) → **Ausstellen** (`invoices.approve`). Dabei wird die Nummer
  `RE-<Jahr>-<laufend>` vergeben, Kunde (als Stand `customer_snapshot`), Beträge und Positionen werden eingefroren.
  Danach geht es weiter über Versandvermerk, Zahlungen (teilweise bezahlt/bezahlt) oder **Storno**.
* **Nummernkreis:** je Firma und Jahr, `INSERT … ON CONFLICT DO UPDATE … RETURNING`. Die Zeilensperre serialisiert
  parallele Ausstellungen, ein Abbruch rollt die Nummer zurück, dadurch bleibt die Folge lückenlos (Test mit 8 parallelen
  Ausstellungen). `UNIQUE (tenant_id, number)` gilt zusätzlich.
* **Unveränderbarkeit (Datenbank):** Trigger lassen nach dem Ausstellen nur Status-, Versand-, Mahn- und
  Zuständigkeitsfelder zu. Positionen sind gesperrt, Löschen ist verboten, ein Weg zurück in den Entwurf oder aus
  „storniert“ existiert nicht. Archivieren geht nur für Entwürfe.
* **Storno:** neue Rechnung `kind = cancellation` mit negierten Positionen, eigener Nummer und Verweis auf das
  Original (höchstens eine je Rechnung). Das geht nur ohne erfasste Zahlungen.
* **Beträge:** Menge in Tausendsteln, Preise in Cent, Steuersatz in Basispunkten **vom Nutzer erfasst**. Es gibt keinen
  Standardsatz und keine Prüfung auf steuerliche Richtigkeit. Gerundet wird kaufmännisch **je Position**
  (`ichq.finance.rechnen`). Ob das den Anforderungen genügt, ist **nicht geprüft**. Pflichtangaben einer Rechnung
  (§ 14 UStG) werden nicht behauptet.
* **Zahlungen:** manuell erfasst, ohne Bankanbindung. Überzahlung und Zahlungen mit Datum in der Zukunft werden
  abgelehnt. Falsche Zahlungen werden nie gelöscht, sondern durch eine **Gegenbuchung** aufgehoben (beide sichtbar).
  Die Datenbank prüft: nur auf ausgestellte, nicht stornierte Rechnungen, gleiche Währung, Rücknahme genau einmal und
  genau mit dem Gegenbetrag.
* **Überfällig:** ausgestellt/versendet/teilweise bezahlt, Restbetrag > 0, Fälligkeit vor „heute“ (Zeitzone der Firma).
  Liste: `GET /invoices?overdue=true&sort=due_date&order=asc`.
* **Mahnwesen:** Kontaktversuche, notierte Erinnerungen, Mahnstufen (0–9), Notizen und Wiedervorlage
  (`follow_up_due=true`) werden **nur dokumentiert**. HQ verschickt **keine** Mahnung und keine Rechnung. Der Versand
  wird lediglich vermerkt (`dispatches`). Für einen Versand an Kunden fehlen Konfiguration und Freigabe.
* **PDF:** eine serverseitige PDF-Erzeugung gibt es nicht. Die Oberfläche hat eine Druckansicht, die der Browser als PDF
  speichern kann.

## Ausgaben und Belege

| Methode | Pfad | Recht |
| --- | --- | --- |
| `GET` | `/api/v1/receipts` | finance.read |
| `POST` | `/api/v1/receipts` | finance.create |
| `GET` | `/api/v1/receipts/{ref}` | finance.read |
| `PATCH` | `/api/v1/receipts/{ref}` | finance.update |
| `PUT` | `/api/v1/receipts/{ref}/document` | finance.update |
| `POST` | `/api/v1/receipts/{ref}/void` | finance.update |

* **Belegprinzip:** Jede Ausgabe hat einen berechneten Belegstatus. `missing` heißt kein Dokument, `unchecked` heißt
  Dokument noch in Quarantäne, `rejected` heißt bei der Virenprüfung als gefährlich erkannt, `complete` heißt geprüft und
  sauber. Ein hochgeladenes Dokument zählt also erst nach bestandener Prüfung (ADR-015). Liste der fehlenden Belege:
  `GET /receipts?evidence=missing&evidence=unchecked&evidence=rejected`. Wiedervorlage: `follow_up_due=true`, nur
  solange der Beleg nicht vollständig ist. `missing_reason` dokumentiert, warum der Beleg (noch) fehlt, der Status
  bleibt dabei trotzdem „fehlt“.
* **Beträge:** brutto laut Beleg in Cent. Der Steuersatz ist optional und wird vom Nutzer erfasst. Ausgaben- und
  Zahlungsdatum dürfen nicht in der Zukunft liegen.
* **Stornieren statt Löschen:** Eine Fehlerfassung wird mit Grund storniert, bleibt sichtbar (`voided=true`), zählt
  nirgends mehr mit und ist danach unveränderlich. Die Datenbank verbietet das Löschen von Ausgaben ganz (Trigger, auch
  für den Superuser) und jede Änderung nach dem Stornieren. Archivieren ist für Ausgaben gesperrt.
* Belegdokumente sind normale Dokumente (Upload mit Virenprüfung, `files.*`). Verknüpfen kann man nur ein sichtbares
  Dokument der eigenen Firma, ein fremdes ergibt 404, die Datenbank prüft zusätzlich Firma und Typ.

## Liquidität

| Methode | Pfad | Recht |
| --- | --- | --- |
| `GET` | `/api/v1/liquidity` | finance.read |
| `GET` | `/api/v1/liquidity/accounts` | finance.read |
| `POST` | `/api/v1/liquidity/accounts` | finance.update |
| `GET` | `/api/v1/liquidity/accounts/{account}` | finance.read |
| `PATCH` | `/api/v1/liquidity/accounts/{account}` | finance.update |
| `POST` | `/api/v1/liquidity/accounts/{account}/balances` | finance.update |
| `GET` | `/api/v1/liquidity/forecasts` | finance.read |
| `POST` | `/api/v1/liquidity/forecasts` | finance.update |
| `PATCH` | `/api/v1/liquidity/forecasts/{item}` | finance.update |

* **Keine vorgetäuschten Kontostände.** HQ hat keine Bankanbindung. Ein Kontostand ist immer ein **manuell erfasster**
  Stand laut Auszug, mit Stichtag, Erfasser und Erfassungszeit (`source: manual`). Stände sind nur anhängend: Wer sich
  vertippt hat, erfasst einen neuen Stand, und der alte bleibt in der Historie. Die Datenbank verbietet Ändern und
  Löschen (Trigger, auch für den Superuser).
* **Drei Arten von Zahlen, getrennt ausgewiesen:**
  * `manual` ist der letzte Stand je aktivem Konto.
  * `recorded` sind die seit dem **ältesten** Stichtag in HQ erfassten Zahlungseingänge und bezahlten Ausgaben, jeweils
    mit Verweis auf den Posten.
  * `expected` sind offene Forderungen (Restbetrag nach Fälligkeit), unbezahlte Ausgaben (Fälligkeit, sonst
    Ausgabedatum) und offene Planposten.

  Überfällige erwartete Posten zählen ab heute und sind mit `overdue` markiert. `estimated_today_minor` ist
  `manual` plus `recorded`, die Zeitleiste addiert `expected` je Woche oder Monat.
* **Unschärfe wird angezeigt, nicht versteckt:** `dates_differ` heißt, dass die Konten unterschiedliche Stichtage
  haben. `accounts_without_balance` nennt Konten ohne Stand. `hidden_items` zählt Posten, die der Aufrufer nicht sehen
  darf; seine Übersicht ist dann unvollständig. Ohne Stand gibt es keine Schätzung (0 und `oldest_as_of: null`).
* **Eine Währung:** Gerechnet wird in der Firmenwährung, oder in `currency=` wenn angegeben. Posten anderer Währungen
  stehen nur gezählt in `other_currencies`, ohne Umrechnung.
* Konten und Planposten sind keine Fachobjekte (keine Freigaben): Lesen erfordert `finance.read`, Pflegen
  `finance.update`. Rechnungen, Zahlungen und Ausgaben zählen nur, soweit der Aufrufer sie sehen darf.
