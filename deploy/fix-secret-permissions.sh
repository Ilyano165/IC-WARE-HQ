#!/bin/sh
# Setzt Besitzer und Rechte der Secret-Dateien passend zu den Containern (idempotent):
#   App-Secrets (Datenbank-URLs, Schlüssel) → UID 10001 (Benutzer „ichq" im Image), Modus 400
#   PostgreSQL-Passwörter → root, Modus 400 (der postgres-Entrypoint liest sie als root)
set -eu
cd "$(dirname "$0")/.."
[ -d secrets ] || { echo "secrets/ fehlt — zuerst deploy/generate-secrets.sh"; exit 1; }
APP="database_url platform_database_url worker_database_url auth_database_url migration_database_url secret_key session_secret smtp_password"
chmod 700 secrets
[ -e secrets/smtp_password ] || : > secrets/smtp_password   # ältere Installationen: leer = kein SMTP-Login
if [ "$(id -u)" -ne 0 ]; then
  echo "Hinweis: nicht als root — Besitzer nicht gesetzt. Die App (UID 10001) kann die Secrets so nicht lesen;"
  echo "         als root erneut ausführen: sudo deploy/fix-secret-permissions.sh"
  chmod 400 secrets/*
  exit 0
fi
for f in secrets/*; do chown 0:0 "$f"; chmod 400 "$f"; done
for f in $APP; do chown 10001:10001 "secrets/$f"; chmod 400 "secrets/$f"; done
