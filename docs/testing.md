# Tests

Die Tests laufen gegen **echtes PostgreSQL** — nie gegen SQLite und nie als Superuser, denn
Superuser umgehen Row-Level Security und die Isolationstests bewiesen dann nichts.

```bash
export ICHQ_TEST_ADMIN_URL="postgresql://postgres:<passwort>@localhost:5432/postgres"
pytest -q
```

Die Testumgebung legt die vier `ichq_*`-Rollen mit **Testpasswörtern** an (bestehende Rollen bekommen
diese Passwörter!) und je Lauf eine frische Datenbank. Nur gegen einen eigenen Test-Server laufen lassen.

## Was getestet wird (Stand C0: 321 Tests, Zahl aus dem letzten Lauf)

| Datei | Inhalt |
| --- | --- |
| `test_config.py` | Pflichtwerte, schwache Geheimnisse, Secret-Dateien, Produktionsregeln, keine Werte in Fehlern |
| `test_db.py` | Rollen ohne Superuser-Rechte, Timeout, Wächter, Rollback, kein Mandant über den Pool hinweg |
| `test_migrations.py` | hoch/runter/hoch, Modelle = Datenbank, RLS überall, zusammengesetzte Fremdschlüssel, BYPASSRLS-Sperre |
| `test_tenancy.py` | Anlegen, Slug-Regeln, Eindeutigkeit, Nachschlagen, Statusübergänge, Plattform-Audit |
| `test_isolation.py` | Firma sieht nur eigene Zeilen, ohne Kontext nichts, kein Schreiben in fremde Firma, Audit nur anhängend |
| `test_authz.py` | Registry, fail-closed-Startprüfung (inkl. Gegenprobe), 401/403, Rechte aus Rollen, inaktive Firma |
| `test_api_health.py` | `/health` und `/readiness` bei DB-, Speicher- und Migrationsproblemen |
| `test_errors_logging.py` | RFC 9457, kein Stacktrace, keine Eingabewerte, Korrelations-ID, Schwärzung, Zugriffslog |
| `test_storage.py` | Schlüsselschema, kein Pfad-Ausbruch, atomares Schreiben, S3 gegen moto |
| `test_jobs.py` | Ereignis nur bei Commit, richtiger Mandant, Wiederholung, Parallelität, hängende Einträge |
| `test_entrypoints.py` | App, CLI, ASGI und Worker in **frischen Prozessen** |
| `test_cli.py` | Kommandozeile gegen die Testdatenbank |
| `test_architecture.py` | Schichtregeln, Dateigröße, keine Geheimnisse und keine Rollennamen im Code |
| `test_core_objects.py` | C0: Registry = DB-CHECK, typisierte FKs, Verweise über Firmengrenzen scheitern in der DB, RLS aller Core-Tabellen, Spaltenrechte, öffentliche IDs, Cursor |
| `test_core_api.py` | C0: Aufgaben (Filter, Sortierung, 53er-Paginierung), Validierung, Kommentare (15-min-Regel, Löschen), Dokumente (Quarantäne, Prüfung), Verknüpfungen |
| `test_core_security.py` | C0: **IDOR-Generator über alle Routen mit Pfad-ID** + Gegenprobe, Listen/Suche ohne Fremddaten, Rechte-Matrix, Steuerberater, pausierte Firma |
| `test_core_notify_search.py` | C0: Rechte beim Zustellen/Lesen, Rückfrage, Fälligkeitsregel, Suche (Gruppen, Präfix, Sonderzeichen), Aktivität ≠ Audit, Audit unveränderbar |
| `test_core_e2e.py` | C0: echter uvicorn-Prozess, echte Logins, Worker und Scan als CLI-Prozesse — Steuerberater-Szenario |
| `test_core_docs.py` | C0: Routentabelle in `docs/core-permissions.md` = Code |

## Mutationstests

```bash
scripts/mutation-check.sh
```

Baut 19 gezielte Sicherheitslücken ein (z. B. RLS ohne Schreibschutz, Mandant pro Sitzung statt pro
Transaktion, Stacktrace an den Client, Routenprüfung nur auf oberster Ebene) und prüft, ob die Tests
rot werden. Meldet auch Mutationen, die gar nicht angewendet werden konnten — ein Prüfskript, das
nichts prüft, darf nicht grün sein.

Warum das wichtig ist: In M1 waren drei Prüfungen grün, die nichts geprüft haben — die Routenprüfung
(FastAPI-Hülle), der Worker (Modell nicht geladen) und eine Zeile im Mutationsskript selbst.
