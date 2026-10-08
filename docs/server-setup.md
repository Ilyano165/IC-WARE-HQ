# Server-Betrieb (feste Domain)

Status: **lauffähig und Ende-zu-Ende getestet, aber nicht produktionsreif für Kundendaten** — Tor 2 (verschlüsselte
Sicherung an zweitem Standort, Restore-Test automatisiert) fehlt noch. Entscheidungen und Grenzen: ADR-005, ADR-015.

## Was man braucht

* Linux-Server (Debian 12 / Ubuntu 22.04+ empfohlen; andere Distributionen mit vorinstalliertem Docker), **≥ 4 GB RAM**
  (ClamAV ~1,5 GB), ~20 GB Platte, root-Zugang.
* Eine **feste Domain** mit DNS-A-Eintrag (und ggf. AAAA) auf die öffentliche IP des Servers, z. B. `hq.ic-ware.eu`.
* Ports **80 und 443** aus dem Internet erreichbar (Let's Encrypt prüft über Port 80/443).
* Eine E-Mail-Adresse für Let's Encrypt (Warnungen vor Zertifikatsablauf).

## Installation (einmal)

```bash
sudo git clone https://github.com/ilyano165/ic-ware-hq.git /opt/ic-ware-hq   # oder Archiv entpacken
cd /opt/ic-ware-hq
sudo deploy/install.sh --domain hq.ic-ware.eu --email admin@ic-ware.eu [--firewall]
sudo deploy/hq setup-admin          # erste Firma + Company Admin (fragt alles ab, Passwort verdeckt)
```

Danach: `https://hq.ic-ware.eu/app/` — anmelden mit dem eben angelegten Admin.

`install.sh` macht, in dieser Reihenfolge: Eingaben prüfen → Docker installieren (nur Debian/Ubuntu, falls fehlend) →
RAM, Ports 80/443 und DNS prüfen → `deploy/.env` schreiben (Domain, E-Mail; Modus 600) → Secrets erzeugen (**nur
wenn `secrets/` fehlt** — nie überschreiben) und Besitzer setzen → Image bauen → starten → auf App und HTTPS warten →
systemd: `ichq.service` (Start beim Booten) und `ichq-backup.timer` (täglich 03:15) → optional ufw (22/80/443).

Erneut ausführen ist sicher, z. B. um die Domain zu ändern. Optionen: `deploy/install.sh --help`
(`--skip-dns-check` hinter NAT, `--dockerhub-mirror mirror.gcr.io` oder `--no-build` bei Docker-Hub-Limit „429",
`--backup-dir`, `--no-systemd`, `--ca-file`).

**Slug der Firma:** Kleinbuchstaben, Ziffern, Bindestrich. Einige Kürzel sind reserviert (u. a. `ic-ware`, `admin`,
`api`, `app`) — z. B. `ic-ware-gbr` verwenden.

## Bedienung: `deploy/hq`

| Befehl | Wirkung |
| --- | --- |
| `sudo deploy/hq status` | Dienste, App-Bereitschaft, HTTPS von außen |
| `sudo deploy/hq logs [dienst]` | Logs folgen, z. B. `logs app`, `logs caddy`, `logs scanner` |
| `sudo deploy/hq start` / `stop` / `restart` | Stack starten/stoppen (Migration läuft vor jedem App-Start) |
| `sudo deploy/hq update` | **Sicherung** → `git pull --ff-only` → Image bauen → Neustart |
| `sudo deploy/hq backup [ordner]` | Sicherung (Standard `/var/backups/ichq`, die neuesten 14 bleiben; `HQ_BACKUP_KEEP`) |
| `sudo deploy/hq restore <datei> --yes` | vollständige Wiederherstellung — überschreibt Datenbank, Dateien, Secrets |
| `sudo deploy/hq setup-admin` | Firma + Company Admin anlegen |
| `sudo deploy/hq ichq <befehl>` | beliebiger CLI-Befehl im App-Container, z. B. `ichq tenant-show ic-ware-gbr` |

## Aufbau

| Dienst | Aufgabe | Neustart |
| --- | --- | --- |
| `caddy` | TLS (Let's Encrypt, automatisch erneuert), HTTP→HTTPS, HSTS, 25-MB-Grenze, geschwärzte Logs | immer |
| `app` | API + Oberfläche `/app` (uvicorn, 2 Prozesse, UID 10001) | immer |
| `worker` | Outbox-Worker | immer |
| `jobs` | stündlich `notifications-scan` und `auth-cleanup` (idempotent, Advisory-Lock) | immer |
| `scanner` | Virenprüfung der Uploads (`documents-scan --loop 10`) | immer |
| `clamav` | ClamAV-Daemon, aktualisiert Signaturen selbst | immer |
| `postgres` | PostgreSQL 16 | immer |
| `db-init`, `migrate` | einmalig je Start: Rollen/Passwörter angleichen, Migration | nein |

Nur Caddy veröffentlicht Ports (80, 443). Datenbank, App und ClamAV sind nur im internen Docker-Netz erreichbar.
Volumes: `pgdata`, `filedata` (Dokumente), `caddydata` (Zertifikate), `caddyconfig`, `clamdb` (Signaturen).

Startreihenfolge: `postgres` → `db-init` → `migrate` → `app` (gesund) → `caddy`; `worker`, `jobs`, `scanner` nach
`migrate`. Alle Dauerdienste haben `restart: unless-stopped`; `ichq.service` startet den Stack beim Booten auch dann,
wenn er vorher mit `hq stop` angehalten wurde.

## Virenprüfung

Jeder Upload ist zuerst `quarantined` („Virenprüfung läuft"), Download 409. Der Dienst `scanner` prüft mit ClamAV:
`clean` → ladbar; `infected` → dauerhaft gesperrt (die Datenbank verbietet jeden anderen Übergang). Ist ClamAV nicht
erreichbar oder antwortet unklar, bleibt das Dokument gesperrt und wird beim nächsten Lauf erneut geprüft — nie
ungeprüft freigegeben. Beim allerersten Start lädt ClamAV einige Minuten Signaturen.

## Sicherung und Wiederherstellung

Eine Sicherung ist **ein** Archiv `ichq-backup-<UTC-Zeit>.tar` (Modus 600) mit `db.dump` (pg_dump), `storage.tar.gz`
(alle Dokumente), `secrets.tar`, `env` und `manifest` (Git-Stand, Migration).

* **Sie enthält die Secrets** — wer die Datei hat, hat alle Daten. Sicher verwahren.
* **Sie liegt auf demselben Server.** Gegen Plattenausfall/Verlust des Servers hilft sie nur, wenn sie regelmäßig
  woanders hin kopiert wird — verschlüsselt, z. B.
  `gpg -c --cipher-algo AES256 ichq-backup-….tar` und dann `scp`/`rclone`. **Noch nicht automatisiert** (M22, vor Tor 2).
* Wiederherstellung auf einem **neuen** Server: Repository holen, `install.sh` wie oben (erzeugt neue Secrets),
  dann `sudo deploy/hq restore /pfad/ichq-backup-….tar --yes`. Die Secrets der Sicherung ersetzen die neuen
  (die alten liegen danach in `secrets.vor-restore-*`), Datenbank-Passwörter werden angeglichen.

## Was geprüft ist — und was nicht

Belege mit Zahlen: ADR-015, Abschnitt „Belege". Automatisch in CI (Job `betrieb`, frischer Ubuntu-24.04-Runner):
`install.sh` + `deploy/smoke-test.sh --wegwerf --docker-neustart`.

| Teil | Geprüft |
| --- | --- |
| Installer auf leerem Docker, zweiter Lauf idempotent | ja (Testumgebung + CI) |
| HTTPS über Caddy, HTTP→HTTPS, HSTS, CSP, kein `Server`-Header | ja (mit `localhost` und Caddys interner CA) |
| Anmeldung über HTTPS, Aufgabe, Upload, Virenprüfung mit echtem ClamAV (EICAR) | ja |
| App als UID 10001, App aus → 503, Client-IP in `auth_events`, Logs ohne Passwort/Token/Query | ja |
| Sicherung → Totalverlust (Volumes + Secrets gelöscht) → Neuinstallation → Wiederherstellung | ja |
| Neustart des Docker-Dienstes | ja (Testumgebung von Hand; CI mit `systemctl restart docker`) |
| `hq update`, Aufbewahrung der Sicherungen | ja (Testumgebung) |
| Eingabeprüfung Installer, Secrets-Rechte, Compose-Regeln, Passwort-Angleich, shellcheck | ja (`tests/test_deploy.py`, Mutationen) |
| **echtes Let's-Encrypt-Zertifikat mit echter Domain** | **nein** — Testumgebung ohne öffentliche Domain |
| DNS-Prüfung gegen echte Domain, Docker-Installation per apt, ufw | **nein** |
| systemd-Units im Betrieb, Neustart des ganzen Servers | **nein** — nur `systemd-analyze verify` |
| Zwei Scanner gleichzeitig (`SKIP LOCKED`) | **nein** |

## Bekannte Lücken für den Betrieb

- **Sicherung unverschlüsselt und am selben Ort**, täglich (bis zu 24 h Datenverlust), kein WAL-Archiv, kein
  automatischer Restore-Test → Tor 2 (M0) nicht erfüllt.
- **Kein Monitoring/Alarm.** `/readiness` (auch `HEAD`) eignet sich für einen externen Uptime-Dienst.
- **Kein E-Mail-Versand konfiguriert** (`ICHQ_SMTP_*`): Passwort-Reset und Einladungen antworten mit 503.
- **Betriebssystem-Updates** (unattended-upgrades) und SSH-Härtung sind Sache des Servers, nicht des Installers.
- **pgBouncer:** mit Statement-Pooling funktioniert `SET LOCAL` **nicht** — nicht einsetzen ohne Prüfung.
- **Client-IP:** Die App vertraut `X-Forwarded-For` von `ICHQ_TRUSTED_PROXIES` (`*` in Compose, weil nur Caddy die
  App erreicht). Wird die App anders erreichbar gemacht, auf Caddys Adresse einschränken.

## Ohne Compose: systemd-Timer

`deploy/systemd/ichq-{notifications-scan,auth-cleanup}.{service,timer}` sind die Alternative zum Dienst `jobs` für
Installationen, die die Jobs auf dem Host planen. **Nicht zusätzlich zum Dienst `jobs` aktivieren** (doppelt wäre
dank Advisory-Lock harmlos, aber unnötig). `WorkingDirectory` anpassen, prüfen mit `systemd-analyze verify`.
