# Server-Betrieb (feste Domain)

Entscheidungen und Grenzen: ADR-005, ADR-015, ADR-016. Was wirklich geprüft ist: Abschnitt „Prüfstand".

## 1. Was man braucht

| Was | Wofür |
| --- | --- |
| Linux-Server, Debian 12 / Ubuntu 22.04+ (andere Linux mit vorinstalliertem Docker gehen auch), **≥ 4 GB RAM**, ≥ 20 GB Platte, root | ClamAV braucht ~1,5 GB |
| **Feste Domain**, DNS-A-Eintrag (ggf. AAAA) auf die öffentliche IP des Servers, z. B. `hq.ic-ware.eu` | HTTPS-Zertifikat (Let's Encrypt) |
| Ports **80 und 443** aus dem Internet erreichbar | Let's Encrypt prüft über 80/443 |
| E-Mail-Adresse für Let's Encrypt | Ablaufwarnungen |
| **SMTP-Zugang** (Host, Port, Benutzer, Passwort, Absender) — z. B. vom Mail-Anbieter der Domain | Einladungen, Passwort-Reset, Sicherheitshinweise, Alarm-Mails |
| **S3-kompatibler Speicher an einem anderen Ort** (Bucket + Zugangsschlüssel; z. B. Hetzner Object Storage, AWS S3, Backblaze B2 über S3) | Sicherung, die den Verlust des Servers übersteht |
| Betreiber-Adresse für Warnungen | `deploy/hq check --alert` |
| optional: externer Ping-Dienst (z. B. healthchecks.io) | Alarm, wenn der ganze Server ausfällt |

## 2. Installation

```bash
sudo git clone https://github.com/ilyano165/ic-ware-hq.git /opt/ic-ware-hq && cd /opt/ic-ware-hq
sudo HQ_SMTP_PASSWORD='…' deploy/install.sh \
  --domain hq.example.de --email admin@example.de \
  --smtp-host smtp.example.de --smtp-port 587 --smtp-user hq@example.de --smtp-from hq@example.de \
  --alert-email betrieb@example.de \
  --backup-repository s3:https://<s3-endpunkt>/<bucket>/ichq \
  --firewall
```

1. Der Installer zeigt am Ende einen **SICHERUNGSSCHLÜSSEL** an. Sofort getrennt vom Server aufbewahren
   (Passwortmanager/Tresor). Ohne ihn ist keine Sicherung lesbar — auch nicht durch IC Ware.
2. S3-Zugang eintragen: `sudo nano /etc/ichq/backup-s3.env`
   (`AWS_ACCESS_KEY_ID=…`, `AWS_SECRET_ACCESS_KEY=…`, `AWS_DEFAULT_REGION=…`; Modus 600).
3. Erste Sicherung und Wiederherstellungstest: `sudo deploy/hq backup && sudo deploy/hq backup-verify`
4. Erste Firma + Company Admin: `sudo deploy/hq setup-admin` (Kürzel z. B. `ic-ware-gbr`; reserviert sind u. a.
   `ic-ware`, `admin`, `api`, `app`).
5. Prüfen: `sudo deploy/hq check` — alles `OK` (Warnungen erklären sich selbst).
6. Optional Totmannschalter: `HQ_HEARTBEAT_URL=https://hc-ping.com/<uuid>` in `deploy/.env` eintragen.

**Was der Installer tut:** Eingaben streng prüfen (sie landen im Caddyfile/.env) → Docker installieren (nur
Debian/Ubuntu, falls fehlend) → RAM, Ports 80/443, DNS gegen die eigenen Adressen → `deploy/.env` setzen (nur die
übergebenen Werte; alles andere bleibt) → Secrets erzeugen (**nur wenn `secrets/` fehlt**) → SMTP-Passwort als
Secret-Datei → Images bauen → starten, auf App und HTTPS warten → Sicherungsschlüssel → systemd: Autostart,
Sicherung alle 6 h, Wiederherstellungstest sonntags, Betriebsprüfung alle 5 min → optional ufw (22/80/443).
Erneut ausführen ist sicher (z. B. Domain oder SMTP ändern). Alle Optionen: `deploy/install.sh --help`.

SMTP-Varianten: Standard STARTTLS (Port 587); `--smtp-ssl` für Port 465; `--smtp-plain` nur für ein lokales Relay
ohne Anmeldung. Anmeldung ohne TLS lehnt die Konfiguration ab.

## 3. Bedienung: `deploy/hq`

| Befehl | Wirkung |
| --- | --- |
| `status` | Dienste, App-Bereitschaft, HTTPS |
| `check [--alert]` | Betriebsprüfung, Exitcode 1 bei FEHLER; `--alert` mailt (läuft per Timer alle 5 min) |
| `logs [dienst]` | Logs folgen (`app`, `worker`, `scanner`, `caddy`, …) |
| `start` / `stop` / `restart` | Stack (Migration läuft vor jedem App-Start) |
| `update` | **Sicherung** → `git pull --ff-only` → Fremd-Images aktualisieren → bauen → Neustart |
| `backup` / `backup-verify` / `backup-status` | Sicherung / Wiederherstellungstest / Übersicht |
| `restore [snapshot] --yes` | vollständige Wiederherstellung (Standard: neueste) |
| `backup-init` | Sicherungsschlüssel anlegen (einmal; macht der Installer) |
| `setup-admin` | Firma + Company Admin anlegen |
| `ichq <befehl>` | CLI im App-Container, z. B. `ichq mail-status`, `ichq mail-retry`, `ichq tenant-show <slug>` |

## 4. Aufbau

| Dienst | Aufgabe | Healthcheck |
| --- | --- | --- |
| `caddy` | TLS (Let's Encrypt, automatisch erneuert), HTTP→HTTPS, HSTS, 25-MB-Grenze, geschwärzte Logs | — (HTTPS-Prüfung in `check`) |
| `app` | API + Oberfläche `/app` (uvicorn, 2 Prozesse, UID 10001) | `/readiness` |
| `worker` | Outbox + **E-Mail-Versand** | Lebenszeichen ≤ 2 min |
| `jobs` | stündlich Benachrichtigungsregeln + Aufräumen | Lebenszeichen nur bei Erfolg, ≤ 2 h |
| `scanner` | Virenprüfung der Uploads | Lebenszeichen ≤ 2 min |
| `clamav` | ClamAV, aktualisiert Signaturen selbst | eigener |
| `postgres` | PostgreSQL 16 | `pg_isready` |

Nur Caddy veröffentlicht Ports. Alle Dauerdienste: `restart: unless-stopped`; `ichq.service` startet den Stack beim
Booten. Volumes: `pgdata`, `filedata`, `caddydata` (Zertifikate), `caddyconfig`, `clamdb`, `restic_cache`.

## 5. Sicherung und Wiederherstellung (ADR-016)

* **Was:** Datenbank (geprüft lesbar), alle Dokumente, `secrets/`, `.env`, Manifest mit Prüfsummen.
* **Wie:** restic, authentifiziert verschlüsselt, an `HQ_BACKUP_REPOSITORY`; alle 6 h; behält 7 tägliche,
  5 wöchentliche, 12 monatliche Stände (`HQ_BACKUP_KEEP_*`).
* **Schlüssel:** `/etc/ichq/backup.key` — liegt nie in der Sicherung. Kopie außerhalb des Servers ist Pflicht.
* **Prüfung:** sonntags `backup-verify` — Wegwerf-PostgreSQL ohne Netz, Prüfsummen, jede Dokument-Datei vorhanden.
  Fehler ⇒ Alarm-Mail; `check` meldet überfällige oder gescheiterte Läufe.

**Neuer Server nach Totalverlust:**
```bash
sudo git clone … /opt/ic-ware-hq && cd /opt/ic-ware-hq
sudo install -d -m 700 /etc/ichq
sudo sh -c 'umask 077; cat > /etc/ichq/backup.key'          # Schlüssel aus dem Tresor einfügen, Strg-D
sudo sh -c 'umask 077; cat > /etc/ichq/backup-s3.env'       # S3-Zugang
sudo deploy/install.sh --domain … --email … --backup-repository s3:https://…/<bucket>/ichq   # gleiche Werte
sudo deploy/hq restore latest --yes
```
Die Secrets der Sicherung ersetzen die neu erzeugten (alte liegen in `secrets.vor-restore-*`), die
Datenbank-Passwörter werden angeglichen. Danach `deploy/hq check`.

## 6. Updates und Rollback

`sudo deploy/hq update` sichert zuerst, holt den Code (`--ff-only`: lokale Änderungen brechen ab), aktualisiert
PostgreSQL-16-/Caddy-/ClamAV-Images, baut und startet; die Migration läuft vor der App.
* Scheitert der **Bau**, läuft die bisherige Version unverändert weiter.
* Scheitert der **Start** nach einer Migration: `git checkout <voriger-Tag>`, `deploy/hq build`,
  `deploy/hq restore latest --yes` (die Sicherung vom Update-Beginn). Migrationen haben `downgrade()`, aber der
  geprüfte Weg zurück ist die Wiederherstellung.

## 7. Monitoring und Fehlerbehebung

`sudo deploy/hq check` zeigt je Zeile `OK | WARNUNG | FEHLER`. Typische Meldungen:

| Meldung | Ursache / Abhilfe |
| --- | --- |
| `https: kein gültiges Zertifikat` | DNS zeigt nicht auf den Server, Port 80/443 zu → `deploy/hq logs caddy` |
| `dienst-X: Healthcheck schlägt fehl` | `deploy/hq logs X`; `deploy/hq restart` |
| `mail: N Mails gescheitert` | SMTP-Daten prüfen (`install.sh --smtp-…`), dann `deploy/hq ichq mail-retry` |
| `mail-smtp: kein SMTP` | `install.sh … --smtp-host … --smtp-from …` |
| `clamav: antwortet nicht` | beim ersten Start normal (Signaturen laden, einige Minuten) |
| `backup: überfällig / fehlgeschlagen` | `deploy/hq backup` von Hand, Meldung lesen; S3-Zugang, Schlüssel |
| `Sicherungsschlüssel passt nicht zum Repository` | falscher Inhalt in `/etc/ichq/backup.key` — Tresor-Kopie einspielen |
| `sicherungsziel: nicht extern` | `install.sh … --backup-repository s3:https://…` |
| `platte: nur N % frei` | alte Docker-Images: `docker image prune`; Sicherungsziel nicht auf dieser Platte |
| Docker-Hub „429" beim Bau | `install.sh … --dockerhub-mirror mirror.gcr.io` oder `docker login` |

Logs: `deploy/hq logs app` (JSON, ohne Passwörter, Tokens, Query-Strings — geprüft im Ende-zu-Ende-Test).

## 8. Umgebungsvariablen in `deploy/.env`

| Variable | Bedeutung |
| --- | --- |
| `ICHQ_DOMAIN`, `ICHQ_ACME_EMAIL` | Domain, Let's-Encrypt-Kontakt (Pflicht) |
| `ICHQ_SMTP_HOST`, `_PORT`, `_USER`, `_FROM`, `_STARTTLS`, `_SSL` | E-Mail; Passwort in `secrets/smtp_password` |
| `ICHQ_ALERT_EMAIL` | Betreiberwarnungen |
| `HQ_BACKUP_REPOSITORY` | Sicherungsziel (`s3:https://…` oder absoluter Pfad) |
| `HQ_BACKUP_KEY_FILE`, `HQ_BACKUP_S3_ENV` | Schlüssel, S3-Zugang (Standard `/etc/ichq/…`) |
| `HQ_BACKUP_KEEP_DAILY` / `_WEEKLY` / `_MONTHLY` | Aufbewahrung (7 / 5 / 12) |
| `HQ_BACKUP_MAX_AGE_HOURS` | ab wann „überfällig" (26) |
| `HQ_HEARTBEAT_URL` | externer Totmannschalter |
| `HQ_DOCKERHUB_MIRROR`, `HQ_BUILD_CA_FILE` | Bau: Spiegel gegen Docker-Hub-Limit, CA hinter TLS-Proxy |

Alle `ICHQ_*`-Variablen der Anwendung: `docs/configuration.md`.

## 9. Prüfstand

**Automatisch in CI** (Job `betrieb`, frischer Ubuntu-24.04-Runner, bei jedem PR): Installation mit S3-Ziel (Test-Server
moto), `deploy/smoke-test.sh --wegwerf --docker-neustart`: HTTPS/Header, Anmeldung, echtes ClamAV (EICAR), UID,
503 bei App-Ausfall, Client-IP, Logs ohne Geheimnisse, verschlüsselte Sicherung, Unlesbarkeit ohne Schlüssel,
Wiederherstellungstest, Betriebsprüfung ohne FEHLER, Totalverlust → Neuinstallation → Wiederherstellung, Neustart
des Docker-Dienstes.

**Von Hand in der Testumgebung** (09.10.2026): S3-Inhalt ohne Klartext (Dateiinhalt, DB-Passwort, E-Mail, Tabellen-
name, Dump-Kopf gesucht — nichts gefunden); negative Proben: fehlende Dokument-Datei, falscher Schlüssel,
manipuliertes S3-Objekt — jeweils rot mit Alarm-Mail; Alarm und Entwarnung kommen per SMTP an.

**Nicht geprüft:** echtes Let's-Encrypt-Zertifikat, echte Domain/DNS-Prüfung, echter S3-Anbieter, echter
SMTP-Anbieter, Docker-Installation per apt, ufw, systemd-Timer im Betrieb (nur `systemd-analyze verify`), Neustart
des ganzen Servers, zwei Scanner gleichzeitig.

## 10. Bekannte Grenzen

* Bis zu **6 h Datenverlust** (kein WAL/PITR, ADR-016).
* Ein Server, keine Hochverfügbarkeit; Update = kurze Unterbrechung.
* pgBouncer mit Statement-Pooling bricht `SET LOCAL` — nicht einsetzen.
* Client-IP: `ICHQ_TRUSTED_PROXIES=*` ist nur sicher, weil Caddy `X-Forwarded-For` überschreibt. Einen CDN/Proxy davor
  nur mit angepasster Konfiguration.
* Betriebssystem-Updates (unattended-upgrades) und SSH-Härtung sind Sache des Servers.
