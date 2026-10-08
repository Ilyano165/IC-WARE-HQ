# IC WARE HQ

Mandantenfähige Unternehmensplattform von IC Ware GbR.

**Stand:** M0 Architektur ✅ · M1 Foundation ✅ · M2 Authentication — Kern fertig und getestet,
Doku und Abschluss offen (siehe `CLAUDE.md`). Keine Oberfläche (M5), keine Geschäftsdaten.
**Nicht produktionsreif.**

Arbeiten mit Claude Code: `CLAUDE.md` (Regeln, wird automatisch gelesen) und
[docs/claude-code-prompts.md](docs/claude-code-prompts.md).

Grundlage ist der M0-Bericht (Bestandsanalyse und Zielarchitektur). Abweichungen davon stehen
in [docs/architecture.md](docs/architecture.md#abweichungen-vom-m0-bericht).

## Was bisher enthalten ist

- Firmen (Mandanten) mit Statusmaschine, Konten, Mitgliedschaften, Rollen-Schema
- PostgreSQL mit vier getrennten Rollen und erzwungener Row-Level Security
- Versionierte API unter `/api/v1` mit zentraler, fail-closed Rechteprüfung
- `/health` und `/readiness`, strukturiertes Logging mit Korrelations-ID und Schwärzung
- Fehlerformat nach RFC 9457, Speicher (lokal/S3), Hintergrundjobs über eine Outbox
- Anmeldung (M2): Argon2id, serverseitige Sitzungen mit Leerlauf- und absoluter Grenze, Sperre und
  Drosselung, Passwort-Reset, TOTP-2FA mit Recovery-Codes, Kontozustände, Auth-Audit, CSRF-Schutz
- 231 Tests gegen echtes PostgreSQL, 45 Mutationstests, Docker/Compose/Caddy, CI

## Schnellstart (Entwicklung)

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements.lock && pip install --no-deps -e ".[dev]"
# PostgreSQL 16 nötig — Rollen und Datenbank anlegen, siehe docs/development.md
cp .env.example .env   # Werte ersetzen, dann: set -a; . ./.env; set +a
ichq migrate
ichq check-config
ichq tenant-create --name "Meine Firma" --slug meine-firma
ichq serve --port 8000
```

## Befehle

| Befehl | Zweck |
| --- | --- |
| `ichq check-config` | Konfiguration prüfen, ohne Geheimnisse auszugeben |
| `ichq migrate [rev]` / `ichq downgrade <rev>` | Datenbankmigrationen |
| `ichq tenant-create --name … --slug …` | Firma anlegen (Status `pending`) |
| `ichq tenant-show <id oder slug>` | Firma nachschlagen |
| `ichq tenant-status <id> <status> --reason …` | Status wechseln (nur erlaubte Übergänge) |
| `ichq worker [--once]` | Outbox-Worker; `--once` endet mit Exit-Code 1 bei Fehlschlägen |
| `ichq user-create --email … --name … [--username …]` | Konto anlegen (Status `pending`) |
| `ichq user-set-password --email … [--password-stdin]` | Passwort setzen (wird abgefragt, nie als Argument) |
| `ichq user-status --email … <status> --reason …` | Kontostatus; beendet bei Sperre alle Sitzungen |
| `ichq membership-add --email … --tenant <slug>` | Konto einer Firma zuordnen (ohne Rechte) |
| `ichq serve` | API-Server (uvicorn, ohne Zugriffslog — die App loggt selbst) |

## Dokumentation

| Datei | Inhalt |
| --- | --- |
| [docs/m0-zielarchitektur.md](docs/m0-zielarchitektur.md) | Verbindliche Zielarchitektur, Roadmap, Tore |
| [docs/architecture.md](docs/architecture.md) | Schichten, Datenbankrollen, Mandantenisolation, Abweichungen von M0 |
| [docs/development.md](docs/development.md) | Lokale Einrichtung |
| [docs/server-setup.md](docs/server-setup.md) | Betrieb mit Docker Compose und Caddy |
| [docs/configuration.md](docs/configuration.md) | Alle Umgebungsvariablen |
| [docs/migrations.md](docs/migrations.md) | Migrationen schreiben und ausführen |
| [docs/testing.md](docs/testing.md) | Tests und Mutationstests |
| [docs/adr/](docs/adr/) | Architekturentscheidungen 001–005 |
| [docs/reference/](docs/reference/) | M4-Prototyp aus IC·HQ 2.x (Konzepte, nicht Code) |
| [docs/claude-code-prompts.md](docs/claude-code-prompts.md) | Prompts für die Weiterarbeit mit Claude Code |
