# IC WARE HQ

Mandantenfähige Unternehmensplattform von IC Ware GbR.

**Stand:** M0 ✅ · M1 ✅ · M2 Authentication ✅ · M3 Mandanten ✅ · **Tor 1 erreicht** · C0 Core-Plattform (Objektmodell, Aufgaben, Kommentare,
Dokumente, Aktivität, Benachrichtigungen, Suche). Keine Oberfläche (M5), noch keine Fachmodule.
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
- Core-Plattform (C0): globales Objektmodell mit typisierten Verknüpfungen und Freigaben, Aufgaben,
  Kommentare mit Erwähnungen, Dokumente (Quarantäne), Aktivitätsverlauf getrennt vom Audit, Benachrichtigungen
  mit Rechteprüfung beim Zustellen, globale Suche, Audit-Export — siehe `docs/core-*.md`
- M3 Mandanten: Firmenprofil, Mitglieder, Einladungen, Last-Admin-Schutz, zentraler Schreibschutz bei Pause
- 487 Tests gegen echtes PostgreSQL (inkl. IDOR-Generator über alle Routen und E2E mit echtem Server), 159 Mutationstests,
  Docker/Compose/Caddy, CI

## Auf einem Server betreiben (feste Domain)

```bash
sudo git clone https://github.com/ilyano165/ic-ware-hq.git /opt/ic-ware-hq && cd /opt/ic-ware-hq
sudo deploy/install.sh --domain hq.example.de --email admin@example.de   # Docker, TLS, Autostart, tägliche Sicherung
sudo deploy/hq setup-admin                                               # erste Firma + Admin
sudo deploy/hq status | update | backup | restore <datei> --yes | logs
```

Details, Grenzen und was getestet ist: [docs/server-setup.md](docs/server-setup.md), ADR-015.

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
| `ichq tenant-admin --email … --tenant <slug>` | gesperrte Rolle „Company Admin" zuweisen (legt Rollenvorlagen an) |
| `ichq tenant-feature --tenant <slug> <modul> on\|off --reason …` | Fachmodul je Firma schalten (Kernmodule nicht) |
| `ichq routes-doc` | Tabelle der geschützten Endpunkte aus dem Code (für `docs/authorization.md`) |
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
| [docs/server-setup.md](docs/server-setup.md) | Server mit fester Domain: Installer, `deploy/hq`, Sicherung, Virenprüfung |
| [docs/configuration.md](docs/configuration.md) | Alle Umgebungsvariablen |
| [docs/migrations.md](docs/migrations.md) | Migrationen schreiben und ausführen |
| [docs/testing.md](docs/testing.md) | Tests und Mutationstests |
| [docs/adr/](docs/adr/) | Architekturentscheidungen 001–015 |
| [docs/reference/](docs/reference/) | M4-Prototyp aus IC·HQ 2.x (Konzepte, nicht Code) |
| [docs/claude-code-prompts.md](docs/claude-code-prompts.md) | Prompts für die Weiterarbeit mit Claude Code |
