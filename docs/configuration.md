# Konfiguration

Ausschließlich über Umgebungsvariablen mit Präfix `ICHQ_`. Jede Variable geht auch als
`ICHQ_<NAME>_FILE` (Pfad zu einer Datei mit dem Wert, z. B. Docker-Secret). Beides gleichzeitig ist
ein Fehler; eine leere `_FILE`-Variable gilt als nicht gesetzt. Für kein Geheimnis gibt es einen
Standardwert. Fehlermeldungen nennen nie einen Wert. Prüfen mit `ichq check-config`.

| Variable | Pflicht | Bedeutung |
| --- | --- | --- |
| `ICHQ_ENV` | nein (`development`) | `development`, `test` oder `production` |
| `ICHQ_DATABASE_URL` | ja | Rolle `ichq_app` |
| `ICHQ_PLATFORM_DATABASE_URL` | ja | Rolle `ichq_platform` |
| `ICHQ_WORKER_DATABASE_URL` | ja | Rolle `ichq_worker` |
| `ICHQ_MIGRATION_DATABASE_URL` | für `ichq migrate` | Rolle `ichq_owner` |
| `ICHQ_DB_POOL_SIZE` | nein (5) | Verbindungen je Rolle und Prozess |
| `ICHQ_DB_STATEMENT_TIMEOUT_MS` | nein (15000) | Abbruch langer Abfragen |
| `ICHQ_SECRET_KEY` | ja | Anwendungsgeheimnis, mindestens 32 Zeichen |
| `ICHQ_SESSION_SECRET` | ja | Sitzungsgeheimnis (ab M2), mindestens 32 Zeichen, anders als `SECRET_KEY` |
| `ICHQ_STORAGE_BACKEND` | nein (`local`) | `local` oder `s3` |
| `ICHQ_STORAGE_PATH` | bei `local` | Speicherordner |
| `ICHQ_S3_ENDPOINT_URL` | nein | S3-kompatibler Endpunkt; leer = AWS. Compose nutzt seit ADR-015 `local` (Volume) |
| `ICHQ_S3_BUCKET` | bei `s3` | Bucket-Name (privat) |
| `ICHQ_S3_REGION` | nein (`eu-central-1`) | Region |
| `ICHQ_S3_ACCESS_KEY` / `ICHQ_S3_SECRET_KEY` | bei `s3` | Zugangsdaten |
| `ICHQ_CLAMD_HOST` / `ICHQ_CLAMD_PORT` | für `ichq documents-scan` (– / 3310) | ClamAV (clamd, TCP). Ohne erreichbares ClamAV bleiben Uploads in Quarantäne (ADR-015) |
| `ICHQ_AUTH_DATABASE_URL` | ja | Rolle `ichq_auth` (Anmeldung, Sitzungen, Passwort-Hashes) |
| `ICHQ_SMTP_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `_FROM`, `_STARTTLS` | für Reset/Einladung | E-Mail-Versand; ohne `HOST`+`FROM` antworten Passwort-Reset und Einladungen mit 503 |
| `ICHQ_PUBLIC_ORIGIN` | in Produktion | z. B. `https://app.ic-ware.eu` — Basis für Links in Mails und Prüfung des `Origin`-Headers (CSRF) |
| `ICHQ_COOKIE_SECURE` | nein (in Produktion an) | `Secure`-Cookie mit Namen `__Host-ichq_session` |
| `ICHQ_TRUSTED_PROXIES` | nein (`127.0.0.1`) | IPs, deren `X-Forwarded-For` vertraut wird (Client-IP für Drosselung/Auth-Ereignisse) |
| `ICHQ_SESSION_IDLE_MINUTES` / `ICHQ_SESSION_ABSOLUTE_HOURS` | nein (30 / 12) | Leerlauf- und absolute Sitzungsgrenze |
| `ICHQ_MFA_CHALLENGE_MINUTES` | nein (5) | Gültigkeit des 2FA-Zwischenschritts |
| `ICHQ_LOGIN_MAX_FAILURES` / `ICHQ_LOCKOUT_MINUTES` | nein (5 / 15) | Kontosperre |
| `ICHQ_THROTTLE_WINDOW_MINUTES`, `ICHQ_IP_MAX_FAILURES`, `ICHQ_IDENTIFIER_MAX_FAILURES` | nein (15, 30, 10) | Drosselung |
| `ICHQ_PASSWORD_RESET_MINUTES` | nein (30) | Gültigkeit des Reset-Links |
| `ICHQ_ARGON2_TIME_COST`, `_MEMORY_KIB`, `_PARALLELISM` | nein (3, 65536, 4) | Argon2id-Parameter |
| `ICHQ_LOG_LEVEL` | nein (`INFO`) | `DEBUG` … `ERROR` |
| `ICHQ_LOG_FORMAT` | nein (`json`) | `json` oder `console` |
| `ICHQ_EXPOSE_DOCS` | nein (`false`) | `/docs` und `/openapi.json` |

## Zusätzliche Regeln in Produktion (`ICHQ_ENV=production`)

- kein Datenbankzugang als Benutzer `postgres`
- `ICHQ_EXPOSE_DOCS` muss aus sein
- `ICHQ_LOG_FORMAT` muss `json` sein

## Immer

- Geheimnisse mindestens 32 Zeichen, keine Platzhalter wie `change-me`
- `SECRET_KEY` und `SESSION_SECRET` verschieden
- App, Plattform und Worker mit verschiedenen Datenbank-URLs (= verschiedenen Rollen)
