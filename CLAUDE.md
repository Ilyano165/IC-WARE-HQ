# CLAUDE.md — IC WARE HQ

Diese Datei liest Claude Code automatisch. Sie ist verbindlich.

## Was das hier ist

Mandantenfähige B2B-Plattform („digitales Betriebssystem eines Unternehmens") von IC Ware GbR.
Entwicklung in Meilensteinen M0–M26 (Roadmap: `docs/architecture.md`, M0-Bericht separat).

**Stand:** M0 Architektur ✅ · M1 Foundation ✅ · M2 Authentication ✅ · **C0 Core-Plattform** (vor M3/M4 gebaut, ADR-010) · **M3 Mandanten** umgesetzt
(`docs/m3-mandanten.md`); **M4 Rollen & Rechte** umgesetzt (`docs/authorization.md`, ADR-011); **U1 Oberfläche** im IC-Ware-Design (`docs/ui.md`, ADR-013); **Tor 1 erreicht** (CI grün auf PR #1, Commit 737db04). Reihenfolge laut Vision:
Tor 1/M3 → C0 → U1 → D0 → S1… — **keine D0-/S-Arbeit vor Tor 1.** Produktvision v2 ist ein **unbestätigter
Entwurf** (`docs/produktvision-v2.md`). Nichts davon ist produktionsreif.

Kommunikation mit dem Team: **Deutsch, direkt, ehrlich.** Lieber „das ist nicht getestet" als
etwas schönreden.

## Nicht verhandelbare Regeln

1. **Keine erfundenen Testergebnisse.** Nur berichten, was wirklich ausgeführt wurde — mit Zahl.
   „Sollte funktionieren" ist kein Ergebnis.
2. **Ein Test, der nie rot werden kann, ist wertlos.** Für jede Sicherheitsregel eine Mutation in
   `scripts/mutation-check.sh` ergänzen. Erwartungen eines Tests nie aus dem Code lesen, den er prüft.
3. **Mandantenisolation ist dreifach**: Service-Kontext (`tenant_transaction`), Row-Level Security mit
   `FORCE`, zusammengesetzte Fremdschlüssel `(tenant_id, x_id)`. Keine neue Tabelle ohne alle drei —
   Checkliste in `docs/migrations.md`.
4. **Jede Route hat genau eine Sicherheitsmarke** (`public`, `mfa_challenge`, `any_session`,
   `signed_in`, `authenticated`, `require`). Fehlt sie, startet die App nicht — so soll es bleiben.
5. **Authentifizierung ≠ Autorisierung.** `ichq.auth` beantwortet „wer?", `ichq.authz` „was darf er?".
   Rechte kommen ausschließlich aus Rollen der Mitgliedschaft. Keine `if role == "..."`-Abfragen.
6. **Nie Geheimnisse loggen oder im Klartext speichern.** Tokens nur als Hash, Passwörter nur Argon2id,
   TOTP-Geheimnisse AES-GCM-verschlüsselt. Keine Secrets im Repository.
7. **Schichten einhalten** (`lint-imports`). Keine Datei über 400 Zeilen. Keine Riesendatei.
8. **Abweichungen vom M0-Bericht als ADR** in `docs/adr/` begründen, nicht stillschweigend.

## Befehle

```bash
# Einmalig: PostgreSQL 16 lokal (z. B. docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=dev postgres:16)
pip install --require-hashes -r requirements.lock && pip install --no-deps -e .
pip install "pytest>=8" "httpx>=0.27" "moto[s3]>=5" "ruff>=0.6" "mypy>=1.11" "import-linter>=2" pip-tools pip-audit

export ICHQ_TEST_ADMIN_URL="postgresql://postgres:dev@localhost:5432/postgres"
pytest -q                          # gegen echtes PostgreSQL — nie SQLite, nie als Superuser
ruff check src tests && mypy && lint-imports
scripts/mutation-check.sh          # dauert einige Minuten; muss "unbemerkt 0 · ungültig 0" melden

# Neue Abhängigkeit: in pyproject.toml eintragen, dann
pip-compile --generate-hashes --strip-extras --output-file requirements.lock pyproject.toml
pip-audit -r requirements.lock --require-hashes
```

**Achtung:** Die Testsuite setzt die Passwörter der `ichq_*`-Rollen auf Testwerte. Nur gegen einen
eigenen Test-PostgreSQL laufen lassen.

## Struktur

```
src/ichq/
  core/        Konfiguration, Logging (mit Schwärzung), Fehler, IDs (UUIDv7), Geld (Cent)
  db/          Engines je DB-Rolle, Transaktionen mit Kontext (tenant/platform/worker/auth)
  storage/     lokal + S3, Schlüssel nur t/<tenant>/f/<file>/v/<n>
  audit/       Mandanten- und Plattform-Audit (nur anhängend)
  tenancy/     Firmen, Statusmaschine
  identity/    Konten, Mitgliedschaften
  authz/       Registry, effektive Rechte (EINE Berechnung), Rollen, Delegation, Last-Admin, Vorlagen, Flags (M4)
  auth/        Login, Sitzungen, Passwörter, Reset, TOTP, Drosselung, Auth-Audit (M2)
  jobs/        Transactional Outbox + Worker
  objects/     C0: Typ-Registry, `objects` (Supertyp), Verknüpfungen/Freigaben (Tabellen), Sichtbarkeit (EINE Stelle)
  activity/    C0: Benutzerverlauf (≠ Audit)
  relations/   C0: Verknüpfen, Freigeben (Services)
  comments/ tasks/ documents/   C0: Fachbausteine auf dem Objektmodell
  members/     M3: Mitglieder, Einladungen (Annehmen über auth/platform/app-Rolle), Last-Admin-Schutz
  notifications/  C0: Engine (Rechte beim Zustellen), Outbox-Handler, Regeln (`ichq notifications-scan`)
  search/      C0: Volltext über `objects`, gruppiert, nur Sichtbares
  health/      Prüfungen für /health und /readiness
  api/         Routen, Sicherheitsabhängigkeiten, Fehler (RFC 9457), Middleware, ui.py (Auslieferung /app)
  web/         U1: build-freie Oberfläche (ES-Module, IC-Ware-Tokens, Schriften lokal) — spricht nur /api/v1
  models.py    registriert ALLE Tabellen — jeder Einstiegspunkt lädt es
  app.py, cli.py, asgi.py, migrations/
tests/         echte PostgreSQL-Tests, Unterprozess-Tests, Mutationsliste in scripts/
deploy/        Dockerfile, docker-compose.yml, Caddyfile, init-roles.sql, generate-secrets.sh
docs/          Architektur, Setup, Konfiguration, Migrationen, Tests, ADRs
```

## Datenbankrollen (keine ist Superuser oder BYPASSRLS)

| Rolle | Zweck |
| --- | --- |
| `ichq_owner` | nur Migrationen |
| `ichq_app` | Mandantendaten, nur mit `app.tenant_id`; sieht an `users` nur Stammdaten-Spalten |
| `ichq_platform` | Firmen, Konten anlegen, Plattform-Audit — keine Mandantendaten, keine Passwort-Spalten |
| `ichq_worker` | Outbox abholen |
| `ichq_auth` | Anmeldung: Passwort-Hashes, Sitzungen, Reset, 2FA; Mitgliedschaften nur des eigenen Kontos (`app.user_id`) |

## Fallstricke, die schon einmal passiert sind

- **FastAPI ≥ 0.14x** legt eingebundene Router als Hülle in `app.routes`. Routen nur über
  `iter_api_routes()` durchsuchen — sonst prüft man nichts und ist trotzdem grün.
- **Modelle schichtübergreifend:** Ein Prozess, der `ichq.models` nicht lädt, scheitert erst beim
  Schreiben. Neue Modelle in `ichq/models.py` eintragen; `tests/test_entrypoints.py` prüft in frischen
  Prozessen.
- **Fehlversuche nie per Ausnahme abbrechen:** Eine Ausnahme rollt die Transaktion zurück — dann ist der
  Fehlversuch nicht gespeichert und die Brute-Force-Sperre wirkungslos. Auth-Funktionen geben `Outcome`
  zurück; die API wirft erst nach dem Commit.
- **Spaltenrechte an `users`:** Die ORM-Insert/-Select-Variante schickt alle Spalten und scheitert für
  App- und Plattform-Rolle. Mit expliziten Spalten arbeiten (siehe `identity.service.create_user`).
- **Caddy `validate`** sagt auch bei wirkungslosen Log-Filtern „Valid". Logfilter nur durch echten Lauf
  prüfen. Query-Strings werden per Regex entfernt, auch im Fehlerlog (`log default`).
- **Hintergrundprozesse** in Testskripten: Start und Prüfung im selben Shell-Aufruf; `pkill -f` mit
  Mustern trifft leicht die eigene Shell — PID-Dateien benutzen.
- **Constraint-Namen doppelt:** Alembic wendet die Namenskonvention auf schon vollständige Namen erneut an —
  in der DB heißen CHECKs `ck_x_ck_x_…` (seit 0001). Funktional egal; in Tests mit `match=` auf den Teilnamen
  prüfen. Korrektur (`op.f()`) nur mit eigener Migration.
- **Autoflush:** `session.scalar(select(func.now()))` NACH dem Setzen eines Feldes schreibt einen Halbzustand
  und verletzt CHECKs. Erst Werte holen, dann Felder gemeinsam setzen.
- **Korrelation in `exists()`:** Joint die Außenabfrage `objects` schon, im Unterselect einen Alias nutzen
  (`visible_clause(p, aliased(ObjectRow))`) — sonst „returned no FROM clauses".
- **TOTP-Wiederverwendungsschutz:** Nach Einrichtung (Schritt t) und Login (t+1) gibt es im selben
  30-s-Fenster keinen weiteren gültigen Code. In Tests Zeit simulieren, nicht den Schutz abschwächen.

## Steuerfunktionen — nicht verhandelbar

Quelle: `docs/produktvision-v2.md`, Abschnitt 2 (Entwurf; diese Regeln verschärfen nur und gelten deshalb sofort).

1. **Kein Steuerwert ohne amtliche Quelle.** Beträge, Sätze, Grenzen, Fristen nur als versionierte Daten mit
   Gültigkeit von–bis, Fundstelle und Prüfdatum — nie als Konstante im Code. Ohne bestätigte Fundstelle:
   „nicht amtlich bestätigt" anzeigen, nicht rechnen. Stand der Prüfung: `docs/steuerwerte-pruefung.md`.
2. **Unveränderbarkeit mit sichtbarer Historie.** Steuerrelevantes nie überschreiben oder löschen; Korrektur =
   neue Version mit wer/wann/vorher/warum; nach Festschreibung nur Korrekturbuchungen (GoBD Rz. 58).
   **Fahrtenbuch:** Korrekturen sichtbar **in der Fahrt selbst**, kein separates Protokoll
   (FG Düsseldorf 24.11.2023, 3 K 1887/22 H(L)); Erfassungszeitpunkt neben Fahrtzeitpunkt zeigen.
3. **Vorschlag, nicht Entscheidung.** Keine Aussage „steuerlich korrekt"/„GoBD-konform" ohne externe Prüfung.
4. **Belegprinzip.** Kein steuerrelevanter Eintrag ohne Nachweis; fehlende Nachweise sind sichtbarer Zustand.
5. **Export statt Insel.** Vollständiger, protokollierter Export für den Steuerberater (Ziel DATEV).

Keine Steuerfunktion geht vor **Tor S** an Kunden (Vision Abschnitt 5).

## Regeln der Core-Plattform (C0)

- **Fachobjekte nur über `objects`** (ADR-008): erst `create_object`, dann Fachzeile mit
  `(tenant_id, id, object_type) → objects`. Nie `target_type + target_id`-Spalten ohne Fremdschlüssel.
- **Sichtbarkeit nur über `ichq.objects.visibility`** (`visible_clause`, `can_see`, `resolve`). Unsichtbar ⇒ 404.
- **Nach außen nur `public_id`** — keine internen UUIDs in neuen Antworten.
- **Jede neue Route mit Pfad-ID** muss im IDOR-Generator (`tests/test_core_security.py::_ref_fuer`) zugeordnet
  sein und in `docs/core-permissions.md` stehen (`tests/test_core_docs.py`) — sonst rot.
- **Benachrichtigungen nur über `deliver`**; neue Outbox-Ereignisse in `notifications.handlers.EMITTED`.
- **Aktivität ≠ Audit**; in beide nie Kommentartexte, Beträge, Beschreibungen.
- Schreibende Core-Routen öffnen die Transaktion mit `writing(db)` (zweite Linie hinter dem zentralen
  Pause-Schreibschutz in `ichq.api.security`).
- Freigaben haben eine Quelle (`manual` / `task_assignment`); Zuweisungs-Freigaben nur über
  `grant_for_assignment`/`drop_assignment_grant`.
- Kommentare nie physisch löschen; Historie schreibt der DB-Trigger, nicht der Code.
- Zeitgesteuerte Jobs nie im Webprozess: eigener CLI-Einstieg + `deploy/systemd/`, idempotent, mit Advisory-Lock.

## M2 abgeschlossen (08.10.2026)

Statusbericht `docs/m2-statusbericht.md`. Dabei gefunden: Daten-Pflege in Migrationen sah wegen FORCE RLS keine Zeile —
**Daten-Änderungen in Migrationen immer in `with ohne_force(...)`** (`ichq.migrations.datenpflege`).
Noch offen aus M2: Compose-Smoke-Test (Prompt-Abschnitt 2), echter SMTP-Versand.

## Regeln für Rechte (M4)

- **Effektive Rechte nur über `ichq.authz.effective`** — Reihenfolge Flag → DENY → (Ressourcen-DENY) → ALLOW →
  (Freigabe) → Rolle. Keine zweite Berechnung, keine Rechte in der Sitzung.
- **Alles, was Rechte kosten kann, in `admin_remains(session)`** (`ichq.authz.guard`) — sonst ist der
  Last-Admin-Schutz umgehbar.
- **Delegation:** Obergrenze, keine Lücken-Löschung, Rang, kein Selbstbedienen — neue Vergabewege über
  `ichq.authz.delegation.manageable` und die Obergrenzen-Prüfung, nie daran vorbei.
- **Company Admin** (`grants_all`) speichert keine Rechte; DB-Trigger sperren Änderungen. Plattform-Rechte gibt es nicht.
- **Neue Route ⇒** `ichq routes-doc` neu erzeugen (`docs/authorization.md`, `tests/test_m4_docs.py`).

## Regeln der Oberfläche (U1, ADR-013)

- **Nur `/api/v1`** — keine HTML erzeugenden Routen, keine zweite Sicherheitsschicht. Ausblenden ist keine Sicherung.
- **Serverdaten nur als Text** über `h()`; `innerHTML` & Co. sind verboten (`tests/test_u1_static.py`).
- **Keine Inline-Skripte/-Styles, keine externen Quellen** (CSP). Neue Datei-Typen nur über `ui.TYPES`.
- **IC-Ware-Design:** Tokens aus `web/css/tokens.css`, Spring Green `#19E56E` als einzige Akzentfarbe.
- **Neue Seite ⇒** Browsertest in `tests/test_u1_browser.py`; jede CSP-Verletzung lässt ihn scheitern.
