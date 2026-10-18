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

## Fristen

| Methode | Pfad | Recht |
| --- | --- | --- |
| `GET` | `/api/v1/deadlines` | finance.read |
| `POST` | `/api/v1/deadlines` | finance.create |
| `GET` | `/api/v1/deadlines/{ref}` | finance.read |
| `PATCH` | `/api/v1/deadlines/{ref}` | finance.update |
| `POST` | `/api/v1/deadlines/{ref}/complete` | finance.update |
| `POST` | `/api/v1/deadlines/{ref}/cancel` | finance.update |

* **HQ gibt keine Fristen vor.** Auch Steuerfristen legt die Firma selbst an, mit Datum, Wiederholung und optional einer
  Quelle als Freitext (`source_reference`). `source_status` ist `user_reference`, wenn eine Quelle eingetragen ist, sonst
  `unconfirmed`. Die Oberfläche zeigt dann „nicht amtlich bestätigt“. Geprüft wird die Quelle in keinem Fall.
* **Erinnerung:** `reminder_on` = Fälligkeit minus `remind_days_before`. `reminder_due=true` listet offene Fristen, deren
  Erinnerungsdatum erreicht ist, `overdue=true` die überfälligen. „Heute“ gilt in der Zeitzone der Firma.
* **Wiederholung** (monatlich, vierteljährlich, jährlich): Beim Erledigen entsteht genau eine Folgefrist mit denselben
  Angaben. Das Monatsende wird gekappt, aus dem 31.01. wird also der 28./29.02. Dass es nur eine Folgefrist gibt,
  erzwingt die Datenbank über `UNIQUE (tenant_id, follows_deadline_id)`.
* Erledigt oder abgesagt (mit Grund) ist endgültig. Wer, wann und der Vermerk bleiben sichtbar, Änderungen danach
  ergeben 409.

## Verträge

| Methode | Pfad | Recht |
| --- | --- | --- |
| `GET` | `/api/v1/contracts` | contracts.read |
| `GET` | `/api/v1/contracts/notice-due` | contracts.read |
| `POST` | `/api/v1/contracts` | contracts.create |
| `GET` | `/api/v1/contracts/{ref}` | contracts.read |
| `PATCH` | `/api/v1/contracts/{ref}` | contracts.update |
| `POST` | `/api/v1/contracts/{ref}/terminate` | contracts.update |

* **Verwaltungsakte, keine Rechtsprüfung.** Gespeichert werden Partei (Kunde oder Freitext), Art, Laufzeit,
  Kündigungsfrist (Wert und Einheit), automatische Verlängerung, Kosten und Zuständige. Vertragsdokumente hängen als
  Anhang am Vertrag (`POST /objects/{ref}/links`, Typ `attachment`). Ein Upload wird nicht ausgewertet.
* **Termine sind Kalenderrechnung aus den Angaben** (`computed_from`):
  * `term_end` ist das Ende der laufenden Laufzeit. Ist bei automatischer Verlängerung der Kündigungstermin verstrichen,
    wird um `renewal_months` fortgeschrieben (`renewals` zählt mit).
  * `notice_deadline` ist das Laufzeitende minus Kündigungsfrist.
  * Bei unbefristeten Verträgen ist `term_end` das frühestmögliche Ende ab heute.
  * `state` ist `draft`, `active`, `terminated` oder `ended`.
* `GET /contracts/notice-due?days=60` listet laufende Verträge mit Kündigungstermin in höchstens 60 Tagen. Gerechnet
  wird in Python, für höchstens 1000 Verträge. `truncated` sagt, ob es mehr gibt.
* **Kündigung erfassen**, nicht versenden: `terminate` speichert, wann sie zugegangen ist und wann sie wirkt, plus
  Vermerk. Ob sie nach dem berechneten Termin kam, steht in Audit und Aktivität (`late`). Eine Aussage zur Wirksamkeit
  gibt es nicht. Ein gekündigter Vertrag ist danach unveränderlich (409).
* Neues Recht `contracts.create` (ADR-020 Nr. 14). Lesen und Ändern laufen über `contracts.read` / `contracts.update`
  und die Objektsichtbarkeit.
