# Tests

Die Tests laufen gegen **echtes PostgreSQL** — nie gegen SQLite und nie als Superuser, denn
Superuser umgehen Row-Level Security und die Isolationstests bewiesen dann nichts.

```bash
export ICHQ_TEST_ADMIN_URL="postgresql://postgres:<passwort>@localhost:5432/postgres"
pytest -q
```

Die Testumgebung legt die vier `ichq_*`-Rollen mit **Testpasswörtern** an (bestehende Rollen bekommen
diese Passwörter!) und je Lauf eine frische Datenbank. Nur gegen einen eigenen Test-Server laufen lassen.

## Was getestet wird (Stand M2-Abschluss: 378 Tests, Zahl aus dem letzten Lauf)

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
| `test_core_docs.py` | Routentabellen in `docs/core-permissions.md` + `docs/m3-mandanten.md` + `docs/authorization.md` = jede `/api/v1`-Route (außer `/auth`) |
| `test_m3_tenancy.py` | M3 mit echten Logins: Firmenprofil, zentraler Pause-Schutz, Einladungen (Missbrauch, Zustimmung, Atomarität), Deaktivieren, Verlassen, Last-Admin, Company Admin per Control Plane |
| `test_core_followups.py` | eigene Rechte je Objekttyp, Freigabe an Zuweisung gebunden, Kommentar-Tombstones und unveränderbare Historie |
| `test_auth_cleanup.py` | M2: Aufräum-Job löscht nur Altes, nie `auth_events`; Sperre; CLI; systemd-Units |
| `test_m4_decision.py` | M4: jede Stufe der Entscheidungsreihenfolge einzeln (Flag, DENY, Ressourcen-DENY, ALLOW, Freigabe, Rolle, sonst) |
| `test_m4_delegation.py` | M4: Prototyp-Szenarien — Rechteausweitung, Lücken-Löschung, Duplizieren, gesperrte Rolle, Rang, Einzelrechte-Missbrauch, Admin-Eskalation, Bypass, Rollenlöschung |
| `test_m4_boundaries.py` | M4: letzter Admin auf jedem Weg, Mandantengrenzen, DB-Trigger der gesperrten Rolle, Flags nicht durch die App schreibbar, Wirkung in laufender Sitzung (echter Login) |
| `test_m4_setup.py` | M4: Migration 0006 mit Übergangsrolle im Bestand, Vorlagen idempotent, CLI `tenant-status`/`tenant-admin`/`tenant-feature` |
| `test_m4_docs.py` | Tabelle „Geschützte Endpunkte" in `docs/authorization.md` = `ichq routes-doc` |
| `test_documents_scan.py` | Virenprüfung gegen einen Test-clamd mit echtem Protokoll: sauber/infiziert, unklare Antworten, Ausfall mitten im Stapel, Firmen getrennt, CLI, DB lässt nur `quarantined → clean/infected` zu |
| `test_deploy.py` | Betrieb: shellcheck, Compose-Regeln (nur Caddy mit Ports, Neustart, gemeinsamer Speicher), Secrets (nie überschreiben, Rechte, UID 10001), Installer-Eingaben (Caddyfile-Injektion), Restore nur mit `--yes`, `init-roles.sql` gleicht Passwörter an (SCRAM-Prüfung) |
| `test_notifications_job.py` | Fälligkeits-Scan: idempotent, Advisory-Lock, Fehler je Firma isoliert, CLI, systemd-Units (`systemd-analyze verify`) |

## Mutationstests

```bash
scripts/mutation-check.sh
```

Baut 159 gezielte Sicherheitslücken ein (inkl. 7 Virenprüfung und 8 Betrieb in einer Kopie von `deploy/`, ADR-015) (z. B. RLS ohne Schreibschutz, Mandant pro Sitzung statt pro
Transaktion, Stacktrace an den Client, Routenprüfung nur auf oberster Ebene) und prüft, ob die Tests
rot werden. Meldet auch Mutationen, die gar nicht angewendet werden konnten — ein Prüfskript, das
nichts prüft, darf nicht grün sein.

Warum das wichtig ist: In M1 waren drei Prüfungen grün, die nichts geprüft haben — die Routenprüfung
(FastAPI-Hülle), der Worker (Modell nicht geladen) und eine Zeile im Mutationsskript selbst.

## Ende-zu-Ende auf einem Server (ADR-015)

```bash
sudo deploy/install.sh --domain localhost --email ci@example.org --skip-dns-check --no-systemd
sudo deploy/smoke-test.sh --wegwerf [--docker-neustart]     # NUR auf Wegwerf-Installationen — löscht alle Daten
```

26 Prüfungen: HTTPS, Header, Anmeldung, echtes ClamAV (EICAR), UID, 503 bei App-Ausfall, Client-IP, Logs ohne
Geheimnisse, Sicherung → Totalverlust → Neuinstallation → Wiederherstellung (+ 2 mit `--docker-neustart`).
Läuft in CI als Job `betrieb`.

Gefunden durch die Mutationen in dieser Runde: Der Test für den Passwort-Angleich war grün, obwohl der Angleich
fehlte — sein Aufräumen (`DROP DATABASE` mit weiteren Befehlen in einem `-c`, also in einer Transaktion) scheiterte
still, und Rollen aus früheren Läufen trugen schon das „richtige" Passwort. Aufräumen jetzt vorher und nachher, mit
geprüftem Exitcode.
Zweiter Fund: „Worker sieht fremde Firmen" blieb zunächst unbemerkt — die Isolationsprüfung joinete `documents` mit
`objects`, und die (intakte) `objects`-Policy verdeckte die offene `documents`-Policy. Jetzt wird jede Tabelle einzeln
geprüft.
