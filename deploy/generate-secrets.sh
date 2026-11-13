#!/bin/sh
# Erzeugt alle Geheimnisse für docker-compose in ./secrets/ (nicht im Repository!).
# Bricht ab, wenn der Ordner schon existiert — vorhandene Geheimnisse werden nie überschrieben.
set -eu
cd "$(dirname "$0")/.."
[ -e secrets ] && { echo "secrets/ existiert bereits — Abbruch, nichts überschrieben."; exit 1; }
umask 077
mkdir secrets
zufall() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }
for f in pg_admin_password pg_owner_password pg_app_password pg_platform_password pg_worker_password pg_auth_password; do
  zufall 32 > "secrets/$f"
done
url() { printf 'postgresql://%s:%s@postgres:5432/ichq' "$1" "$(cat "secrets/$2")" > "secrets/$3"; }
url ichq_app pg_app_password database_url
url ichq_platform pg_platform_password platform_database_url
url ichq_worker pg_worker_password worker_database_url
url ichq_auth pg_auth_password auth_database_url
url ichq_owner pg_owner_password migration_database_url
zufall 48 > secrets/secret_key
zufall 48 > secrets/session_secret
# Die App-Container laufen als UID 10001 (deploy/Dockerfile) und lesen ihre Secrets als Bind-Mount — die Dateien
# müssen deshalb dieser UID gehören (Compose ohne Swarm kann Besitzer/Modus von Secrets nicht setzen).
deploy/fix-secret-permissions.sh
echo "Geheimnisse erzeugt in ./secrets. Sichern (deploy/hq backup), aber nie einchecken."
