# Server-Betrieb

Status: **nicht produktionsreif.** Die Dateien sind vorbereitet; `docker compose` selbst wurde in M1
nicht ausgeführt (siehe „Was geprüft ist").

## Aufbau

Docker Compose auf einem Server (M0, Abschnitt 29):

| Dienst | Aufgabe |
| --- | --- |
| `caddy` | TLS mit automatischen Zertifikaten, HSTS, 25-MB-Grenze, geschwärzte Logs |
| `app` | API (uvicorn, 2 Prozesse, Nutzer ohne Root-Rechte) |
| `worker` | Outbox-Worker |
| `postgres` | PostgreSQL 16 |
| `minio` | S3-kompatibler Speicher, privater Bucket |
| `db-init`, `migrate`, `minio-init` | einmalige Startaufgaben |

Startreihenfolge: `postgres` → `db-init` → `migrate` → `app` (gesund) → `caddy`.

## Einrichtung

```bash
# 1. Geheimnisse erzeugen (bricht ab, wenn ./secrets schon existiert)
deploy/generate-secrets.sh
# 2. Domain setzen und DNS-A-Eintrag auf den Server zeigen lassen
export ICHQ_DOMAIN=app.ic-ware.eu
# 3. Starten
docker compose -f deploy/docker-compose.yml up -d --build
# 4. Erste Firma
docker compose -f deploy/docker-compose.yml exec app ichq tenant-create --name "IC Ware" --slug ic-ware
```

Firewall: nur 80 und 443 öffnen. PostgreSQL und MinIO bleiben im internen Netz.

## Geheimnisse

Alle Geheimnisse liegen als Dateien in `./secrets` (Rechte 600) und kommen per Docker-Secret als
`ICHQ_*_FILE` in die Container. Nichts davon steht im Image, in der Compose-Datei oder im Repository.
`./secrets` sichern — ohne diese Dateien sind Datenbank und Speicher nicht mehr erreichbar.

## Was geprüft ist — und was nicht

| Teil | Geprüft |
| --- | --- |
| `init-roles.sql` | ja, gegen PostgreSQL 16 |
| `generate-secrets.sh` | ja, inkl. „überschreibt nichts" und Start der App mit den erzeugten Dateien |
| Lockfile im Image-Build-Verfahren | ja, Installation mit `--require-hashes` in sauberer Umgebung |
| Migration aus dem installierten Paket | ja |
| Caddyfile | ja, mit Caddy 2.10.2 vor der echten App: TLS, HSTS, `Server`-Header entfernt, Query/Cookie/Authorization aus allen Logs gefiltert, 503 bei App-Ausfall |
| Dockerfile, docker-compose.yml | **nein** — in der Bauumgebung gab es kein Docker |
| MinIO | **nein** — S3-Code nur gegen moto getestet |
| 25-MB-Grenze | **nein** — es gibt noch keinen Endpunkt, der einen Body liest |

## Bekannte Lücken für den Betrieb

- **Kein Backup.** Kommt in M22, muss aber vor echten Kundendaten stehen (M0, Tor 2).
- **Kein Monitoring/Alarm.** `/readiness` ist vorbereitet, ein Alarmierungssystem fehlt.
- **pgBouncer:** Mit Transaction-Pooling funktioniert `SET LOCAL` korrekt, mit Statement-Pooling
  **nicht**. Nicht getestet. Vor dem Einsatz prüfen.
- **Client-IP hinter Caddy:** uvicorn vertraut `X-Forwarded-For` standardmäßig nur von 127.0.0.1. In
  Compose kommt Caddy aus einem anderen Container — für Rate-Limits (M2) `FORWARDED_ALLOW_IPS` auf das
  Caddy-Netz setzen.


## Geplante Jobs (systemd)

Erste Betriebsvariante für zeitgesteuerte Jobs: systemd-Timer auf dem Host, der Job selbst läuft im App-Container.

```bash
sudo cp deploy/systemd/ichq-notifications-scan.{service,timer} /etc/systemd/system/
# WorkingDirectory in der .service-Datei auf den Pfad des Compose-Projekts anpassen
sudo systemd-analyze verify /etc/systemd/system/ichq-notifications-scan.{timer,service}
sudo systemctl daemon-reload && sudo systemctl enable --now ichq-notifications-scan.timer
systemctl list-timers ichq-notifications-scan.timer
journalctl -u ichq-notifications-scan.service      # Ergebnis: "firmen N · zugestellt M · fehlgeschlagen K"
```

Exitcode 1 = mindestens eine Firma ist gescheitert (Details im JSON-Log des Containers). Ein zweiter Lauf während
eines laufenden endet sofort („übersprungen"). **Nicht auf einem echten Server getestet** — geprüft sind die Units
mit `systemd-analyze verify` und der Job selbst in der Testsuite.


## Anmeldung hinter Caddy (M2)

- Fünfte Datenbankrolle **`ichq_auth`** anlegen (`deploy/postgres/init-roles.sql`, Variable `auth_pw`) und
  `ICHQ_AUTH_DATABASE_URL` setzen; Migration `0002` bricht ab, wenn die Rolle fehlt oder Superuser/BYPASSRLS ist.
- `ICHQ_PUBLIC_ORIGIN=https://<domain>` setzen — sonst fehlen Reset-/Einladungslinks und die CSRF-Prüfung nutzt den
  Host-Header.
- Cookies: In Produktion `Secure` + Name `__Host-ichq_session` (setzt HTTPS voraus — Caddy terminiert TLS).
- Client-IP: Caddy setzt `X-Forwarded-For`; die App vertraut ihm nur von `ICHQ_TRUSTED_PROXIES`. In Compose `*`,
  weil der App-Port nicht veröffentlicht ist und nur Caddy im internen Netz die App erreicht. Wird die App anders
  erreichbar gemacht, unbedingt auf die Caddy-Adresse einschränken — sonst kann jeder seine IP fälschen und die
  IP-Drosselung umgehen.
- Aufräumen: `deploy/systemd/ichq-auth-cleanup.{service,timer}` wie im Abschnitt „Geplante Jobs" installieren.
