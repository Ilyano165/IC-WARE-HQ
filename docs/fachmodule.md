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
