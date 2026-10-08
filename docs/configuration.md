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
| `ICHQ_S3_ENDPOINT_URL` | nein | z. B. `http://minio:9000`; leer = AWS |
| `ICHQ_S3_BUCKET` | bei `s3` | Bucket-Name (privat) |
| `ICHQ_S3_REGION` | nein (`eu-central-1`) | Region |
| `ICHQ_S3_ACCESS_KEY` / `ICHQ_S3_SECRET_KEY` | bei `s3` | Zugangsdaten |
| `ICHQ_SMTP_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `_FROM`, `_STARTTLS` | nein | E-Mail — in M1 validiert, aber ungenutzt |
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
