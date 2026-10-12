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
