# Architektur (Stand M1)

## Schichten

Höhere Schichten dürfen tiefere importieren, nie umgekehrt. Module in einer Zeile sind voneinander
unabhängig. Die Regel prüft `import-linter` in jedem CI-Lauf (`pyproject.toml`, Abschnitt
`tool.importlinter`).

```
ichq.cli | ichq.migrations            Einstiegspunkte
ichq.app                              Anwendungsfabrik
ichq.api                              HTTP: Routen, Sicherheitsabhängigkeiten, Fehler, Middleware
ichq.models                           registriert alle Tabellen (siehe unten)
ichq.search | ichq.notifications      C0: Suche, Benachrichtigungen (Konsumenten)
ichq.tasks                            C0: Aufgaben
ichq.comments | documents | relations C0: Kommentare, Dokumente, Verknüpfen/Freigeben
ichq.activity                         C0: Benutzerverlauf
ichq.objects                          C0: Objektmodell, Registry, Sichtbarkeit
ichq.health | jobs | tenancy | identity | authz | auth   Fachmodule
ichq.audit                            Audit — wird von Fachmodulen benutzt
ichq.db | ichq.storage                Datenbankzugriff, Dateispeicher
ichq.core                             Konfiguration, Logging, Fehler, IDs, Geld
```

Keine Datei überschreitet 400 Zeilen (Test `test_keine_riesendatei`).

### Warum es `ichq.models` gibt

Tabellen verweisen schichtübergreifend aufeinander: `audit_events` hat einen Fremdschlüssel auf
`memberships`, das Audit-Modul liegt aber unter dem Identitätsmodul und darf es nicht importieren.
SQLAlchemy löst solche Verweise erst beim Schreiben auf. Fehlt das Modul im Prozess, scheitert der
Schreibvorgang zur Laufzeit — genau das ist in M1 beim Worker passiert, während die Testsuite grün
war (dort waren zufällig alle Module geladen). Seitdem lädt jeder Einstiegspunkt `ichq.models`,
`assert_complete()` prüft beim Start, und `tests/test_entrypoints.py` startet jeden Einstiegspunkt in
einem frischen Prozess.

## Datenbankrollen

| Rolle | Wer nutzt sie | Darf |
| --- | --- | --- |
| `ichq_owner` | nur Migrationen | Tabellen besitzen und ändern |
| `ichq_app` | API, Worker-Handler | Mandantendaten — nur mit gesetztem Mandantenkontext |
| `ichq_platform` | Control Plane, CLI | Firmen, Konten, Plattform-Audit — **keine** Mandantendaten |
| `ichq_worker` | Worker, Scanner | Outbox abholen und markieren; Virenprüfung: Dokumente der gesetzten Firma lesen, nur `scan_status` ändern, Audit anhängen (ADR-015) |

Keine Rolle ist Superuser oder hat `BYPASSRLS`; die Migration bricht ab, wenn doch. Zur Laufzeit
existiert keine Verbindung mit Besitzerrechten.

## Mandantenisolation — dreifach

1. **Service-Kontext.** Mandantendaten gibt es nur über `tenant_transaction(engine, tenant_id)`.
   Eine `TenantSession` ohne Kontext wirft `TenantContextMissing`, statt still leere Ergebnisse zu
   liefern.
2. **Row-Level Security.** Jede Mandantentabelle hat `ENABLE` und `FORCE ROW LEVEL SECURITY`. Die
   Transaktion setzt `SET LOCAL app.tenant_id`; Policies vergleichen mit `ichq_current_tenant()`.
   Ohne Kontext liefert die Datenbank nichts — auch wenn der Python-Wächter umgangen wird (getestet).
3. **Zusammengesetzte Fremdschlüssel.** Verweise zwischen Mandantentabellen laufen über
   `(tenant_id, x_id) → (tenant_id, id)`. Eine Rolle von Firma B kann technisch nicht einem Mitglied
   von Firma A zugeordnet werden — selbst nicht durch einen Datenbank-Administrator.

`SET LOCAL` endet mit der Transaktion. Eine Verbindung aus dem Pool trägt den Mandanten nie in die
nächste Anfrage (Test mit Pool-Größe 1 und gleicher Backend-PID).

**Konten** (`users`) sind global. Eine Firma sieht per Policy nur Konten, die bei ihr Mitglied sind.

## Anfrageweg

```
Client → Caddy (TLS, HSTS, Größenlimit, geschwärzte Logs)
       → RequestContextMiddleware (Korrelations-ID, Sicherheits-Header, Notfall-500, Zugriffslog)
       → Route mit genau EINER Sicherheitsmarke: public(…) | authenticated() | require(…)
       → tenant_db() → tenant_transaction → Fachfunktion → Commit vor der Antwort
```

`assert_routes_secured` verweigert den Start, wenn eine Route keine oder mehrere Marken hat.
Wichtig: Ab FastAPI 0.14x stehen eingebundene Router als Hülle in `app.routes`. Die Prüfung läuft
deshalb über `effective_route_contexts()` und meldet einen Fehler, wenn sie **keine** Route findet —
sie war in M1 zunächst wirkungslos und trotzdem grün.

`get_principal` liefert in M1 immer `None`; alle geschützten Routen antworten mit 401. M2 ersetzt nur
diese Funktion.

## Fehler

Alle Fehler als `application/problem+json` (RFC 9457) mit `code` und `request_id`. Unbehandelte
Ausnahmen fängt die äußerste eigene Middleware: Antwort ohne Stacktrace und Ausnahmetext, Log mit
Stacktrace (geschwärzt) und derselben ID. Validierungsfehler geben keine Eingabewerte zurück.

## Logging

JSON auf stdout. Zwei Verteidigungslinien: Sensibles wird nicht geloggt, und ein Filter schwärzt
Schlüssel (`password`, `token`, `secret`, `session`, `authorization`, `cookie`, …) sowie Muster
(Bearer-Tokens, Passwörter in Datenbank-URLs, `token=`-Parameter, Onboarding-Pfade). Das Zugriffslog
schreibt die Routen-Vorlage (`/onboard/{token}`), nie den rohen Pfad oder die Query. Das
uvicorn-Zugriffslog ist abgeschaltet. Caddy filtert Query, Cookie und Authorization in allen Logs.

## Hintergrundjobs

Transactional Outbox: `emit_event` schreibt in derselben Transaktion wie die fachliche Änderung. Der
Worker holt per `FOR UPDATE SKIP LOCKED`, führt Handler in `tenant_transaction` der jeweiligen Firma
aus, wiederholt mit wachsendem Abstand und gibt hängengebliebene Einträge nach 5 Minuten frei.

## Speicher

Schlüssel nur in der Form `t/<tenant>/f/<file>/v/<version>` — Mandant im Pfad, nie ein Originalname,
nie eine Benutzereingabe. Lokal: atomares Schreiben, Rechte 600, kein Pfad außerhalb der Wurzel.
S3: privater Bucket, signierte Links 1–300 Sekunden.

## Core-Plattform (C0)

Objektmodell und Beziehungen: `docs/core-object-model.md` (ADR-008). Rechte und Sichtbarkeit:
`docs/core-permissions.md` (ADR-009). Aktivität, Audit, Benachrichtigungen: `docs/core-activity-model.md`.
API: `docs/core-api.md`. Paginierung liegt in `ichq.db.paging`, damit auch das Audit-Lesen sie nutzt.

## Abweichungen vom M0-Bericht

| M0 sagt | M1 macht | Begründung |
| --- | --- | --- |
| Backend Django **oder** FastAPI | FastAPI (ADR-003) | M0-Aufgabenliste verlangt SQLAlchemy + Alembic und zusammengesetzte Fremdschlüssel |
| Redis für Queue | Queue = Outbox in PostgreSQL | M1 braucht keine zweite Infrastruktur; Redis kommt mit Rate-Limits in M2 |
| `/ready` | `/readiness` | Vorgabe aus dem M1-Auftrag |
| Plattform-Konten getrennt | Plattform-Aktionen in M1 nur per CLI (`actor = cli:<user>`) | Control-Plane-Konten folgen in M17 |
| Dateien-Tabelle | noch keine | Metadaten entstehen mit dem Dateimodul (M10); M1 liefert nur die Speicherschicht |
| Login-Sperre in Redis | — | gehört zu M2 |
| Aufgaben/Kommunikation/Dateien/Suche ab M7–M14 | Querschnitts-Bausteine schon in C0 | ADR-010 |
| Ressourcen-Freigaben in M4 | `object_grants` + `objects.read_all` schon in C0 | ADR-009 |
