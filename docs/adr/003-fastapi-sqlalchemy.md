# ADR-003: FastAPI mit SQLAlchemy 2 und Alembic

**Status:** angenommen (M1) · **Offen in M0:** „Django oder FastAPI"

## Kontext
M0 ließ die Wahl offen, empfahl im Gespräch Django. Die M1-Aufgabenliste im selben Bericht verlangt
aber ausdrücklich SQLAlchemy 2 + Alembic und zusammengesetzte Fremdschlüssel. Eine Rückfrage blieb
unbeantwortet.

## Entscheidung
FastAPI, SQLAlchemy 2, Alembic, psycopg 3, pydantic-settings.

## Abwägung
| | Django | FastAPI + SQLAlchemy |
| --- | --- | --- |
| Zusammengesetzte Fremdschlüssel | nur per RunSQL | nativ |
| RLS mit `SET LOCAL` je Transaktion | möglich, gegen das ORM-Modell | direkt |
| Auth, Admin, Formulare | fertig | Eigenbau (M2, M5) |
| OpenAPI für die API aus M0 | Zusatzpaket | eingebaut |

## Folgen
Anmeldung (M2) und Oberfläche (M5) müssen selbst gebaut werden — der größere Aufwand gegenüber Django.
Bei FastAPI-Updates auf interne Änderungen achten: Version 0.14x hat die Routenstruktur geändert, was
die Sicherheitsprüfung zunächst unbemerkt wirkungslos machte (jetzt durch Test abgesichert).
