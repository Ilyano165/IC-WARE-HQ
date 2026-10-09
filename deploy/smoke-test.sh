#!/usr/bin/env bash
# IC WARE HQ — Ende-zu-Ende-Test einer Installation (CI-Job „betrieb" und Test-Server). NUR AUF WEGWERF-INSTALLATIONEN:
# legt eine Firma an und ZERSTÖRT danach alle Daten (Totalverlust-Probe), um die Sicherung wiederherzustellen.
#
#   sudo deploy/smoke-test.sh --wegwerf [--docker-neustart]
#
# Voraussetzung: deploy/install.sh ist gelaufen. Prüft: HTTP→HTTPS, Sicherheits-Header, setup-admin, Anmeldung über
# HTTPS, Aufgabe, Upload, echte Virenprüfung (EICAR gesperrt, sauberes Dokument ladbar), verschlüsselte Sicherung,
# Wiederherstellungstest, Betriebsprüfung, Totalverlust
# (Volumes + Geheimnisse gelöscht), Neuinstallation, Wiederherstellung, Daten + Anmeldung danach, optional
# Neustart des Docker-Dienstes.
# shellcheck disable=SC2016,SC2034  # Prüfungen absichtlich einfach gequotet: pruefe wertet sie per eval aus
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
HQ="$ROOT/deploy/hq"
[ "${1:-}" = "--wegwerf" ] || { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
NEUSTART=0; [ "${2:-}" = "--docker-neustart" ] && NEUSTART=1
env_wert() { sed -n "s/^$1=//p" "$ROOT/deploy/.env" | tail -1; }
DOMAIN="$(env_wert ICHQ_DOMAIN)"; EMAIL="$(env_wert ICHQ_ACME_EMAIL)"; CA_BAU="$(env_wert HQ_BUILD_CA_FILE)"
B="https://$DOMAIN"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
OK=0
pruefe() { if eval "$2"; then OK=$((OK + 1)); echo "  ok   $1"; else echo "  FEHLT $1" >&2; exit 1; fi; }
schritt() { echo "== $*"; }

curl_opts() {
  CURL=(curl -sS --max-time 30 --resolve "$DOMAIN:443:127.0.0.1" --resolve "$DOMAIN:80:127.0.0.1" -b "$T/jar" -c "$T/jar"
        -H "Origin: $B")
  if [ "$DOMAIN" = localhost ]; then   # interne CA von Caddy (bei echter Domain: Let's Encrypt, normale Prüfung)
    docker compose -f "$ROOT/deploy/docker-compose.yml" --env-file "$ROOT/deploy/.env" exec -T caddy \
      cat /data/caddy/pki/authorities/local/root.crt > "$T/ca.crt"
    CURL+=(--cacert "$T/ca.crt")
  fi
}
api() { "${CURL[@]}" -o "$T/body" -w '%{http_code}' "$@" || true; }
json() { python3 -c "import json,sys; d=json.load(open('$T/body')); print($1)"; }

anmelden() {
  rm -f "$T/jar"
  [ "$(api -X POST -H 'content-type: application/json' --data "{\"login\":\"$MAIL\",\"password\":\"$PW\"}" \
        "$B/api/v1/auth/login")" = 200 ] || return 1
  api "$B/api/v1/auth/session" >/dev/null
  local tid; tid="$(json 'd["memberships"][0]["tenant_id"]')"
  [ "$(api -X POST -H 'content-type: application/json' --data "{\"tenant_id\":\"$tid\"}" "$B/api/v1/auth/tenant")" = 200 ]
}
hochladen() { api -X POST -H 'content-type: text/plain' --data-binary "@$2" "$B/api/v1/documents?filename=$1" >/dev/null
              json 'd["id"]'; }
scanstatus() { api "$B/api/v1/documents/$1" >/dev/null; json 'd["scan_status"]'; }

curl_opts
schritt "Erreichbarkeit"
for _ in $(seq 1 60); do [ "$(api "$B/readiness")" = 200 ] && break; sleep 2; done
pruefe "HTTP leitet auf HTTPS um" '[ "$(curl -s -o /dev/null -w "%{http_code}" --resolve "$DOMAIN:80:127.0.0.1" "http://$DOMAIN/app/")" = 308 ]'
pruefe "HTTPS /readiness 200" '[ "$(api "$B/readiness")" = 200 ]'
"${CURL[@]}" -D "$T/kopf" -o /dev/null "$B/app/"
pruefe "HSTS gesetzt" 'grep -qi "^strict-transport-security: max-age=31536000" "$T/kopf"'
pruefe "CSP gesetzt" 'grep -qi "^content-security-policy: default-src .self." "$T/kopf"'
pruefe "kein Server-Header" '! grep -qi "^server:" "$T/kopf"'

schritt "Einrichtung + Anmeldung über HTTPS"
SLUG="smoke-$(date +%s)"; MAIL="admin@$SLUG.test"; PW="Smoke-$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')"
printf '%s\n' "Smoke-Test GmbH" "$SLUG" "$MAIL" "Smoke Admin" "$PW" | "$HQ" setup-admin > "$T/setup.log" 2>&1 || { cat "$T/setup.log"; exit 1; }
pruefe "Anmeldung + Firmenwahl" anmelden
pruefe "Aufgabe angelegt" '[ "$(api -X POST -H "content-type: application/json" --data "{\"title\":\"Smoke-Aufgabe $SLUG\"}" "$B/api/v1/tasks")" = 201 ]'

schritt "Virenprüfung mit echtem ClamAV (wartet bis 15 min auf Signaturen)"
printf 'Rechnung %s\n' "$SLUG" > "$T/gut.txt"
printf '%s' 'X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*' > "$T/eicar.txt"
GUT="$(hochladen gut.txt "$T/gut.txt")"; BOESE="$(hochladen eicar.txt "$T/eicar.txt")"
pruefe "vor der Prüfung gesperrt (409)" '[ "$(api "$B/api/v1/documents/$GUT/content")" = 409 ]'
for _ in $(seq 1 180); do
  [ "$(scanstatus "$GUT")" != quarantined ] && [ "$(scanstatus "$BOESE")" != quarantined ] && break; sleep 5
done
pruefe "sauberes Dokument: clean" '[ "$(scanstatus "$GUT")" = clean ]'
pruefe "EICAR: infected" '[ "$(scanstatus "$BOESE")" = infected ]'
pruefe "sauberes Dokument ladbar, Inhalt gleich" '[ "$(api "$B/api/v1/documents/$GUT/content")" = 200 ] && cmp -s "$T/body" "$T/gut.txt"'
pruefe "EICAR gesperrt (409)" '[ "$(api "$B/api/v1/documents/$BOESE/content")" = 409 ]'

schritt "Betrieb"
C=(docker compose -f "$ROOT/deploy/docker-compose.yml" --env-file "$ROOT/deploy/.env")
sql() { "${C[@]}" exec -T postgres psql -U postgres -d ichq -tAc "$1"; }
pruefe "App läuft nicht als root (UID 10001)" '[ "$("${C[@]}" exec -T app id -u)" = 10001 ]'
for _ in $(seq 1 30); do [ "$(sql "SELECT count(*) FROM outbox_events WHERE status <> 'done'")" = 0 ] && break; sleep 2; done
pruefe "Worker hat alle Outbox-Ereignisse erledigt" '[ "$(sql "SELECT count(*) FROM outbox_events WHERE status <> '"'done'"'")" = 0 ] && [ "$(sql "SELECT count(*) FROM outbox_events")" -gt 0 ]'
CADDY_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$("${C[@]}" ps -q caddy)")"
LOGIN_IP="$(sql "SELECT ip FROM auth_events WHERE event = 'login_succeeded' ORDER BY occurred_at DESC LIMIT 1")"
pruefe "echte Client-IP in auth_events ($LOGIN_IP), nicht die von Caddy" '[ -n "$LOGIN_IP" ] && [ "$LOGIN_IP" != "$CADDY_IP" ]'
# Gefälschtes X-Forwarded-For darf die Drosselung nicht umgehen: Caddy ersetzt den Kopf durch die echte Adresse
api -X POST -H 'content-type: application/json' -H 'X-Forwarded-For: 203.0.113.66' \
  --data "{\"login\":\"$MAIL\",\"password\":\"falsch-falsch-falsch\"}" "$B/api/v1/auth/login" > /dev/null
FALSCH_IP="$(sql "SELECT ip FROM auth_events WHERE event = 'login_failed' ORDER BY occurred_at DESC LIMIT 1")"
pruefe "gefälschtes X-Forwarded-For wirkungslos ($FALSCH_IP)" '[ "$FALSCH_IP" = "$LOGIN_IP" ]'
"$HQ" diagnose > "$T/diagnose.log" 2>&1 || true
pruefe "Diagnose (DNS/Ports/Weiterleitung/Zertifikat/intern) ohne FEHLER" '! grep -q "^FEHLER" "$T/diagnose.log" && grep -q "^OK *intern" "$T/diagnose.log"'
"${C[@]}" stop app > /dev/null 2>&1
for _ in $(seq 1 10); do [ "$(api "$B/readiness")" = 503 ] && break; sleep 2; done   # erst 502, nach Health-Check 503
pruefe "App gestoppt → Caddy 503" '[ "$(api "$B/readiness")" = 503 ]'
"${C[@]}" start app > /dev/null 2>&1
for _ in $(seq 1 60); do [ "$(api "$B/readiness")" = 200 ] && break; sleep 2; done
pruefe "App gestartet → wieder 200" '[ "$(api "$B/readiness")" = 200 ]'
"${C[@]}" logs --no-color > "$T/logs" 2>&1
SITZUNG="$(awk '$6 == "__Host-ichq_session" {print $7}' "$T/jar" | tail -1)"
pruefe "Logs ohne Passwort" '! grep -qF "$PW" "$T/logs"'
pruefe "Logs ohne Sitzungs-Token" '[ -n "$SITZUNG" ] && ! grep -qF "$SITZUNG" "$T/logs"'
pruefe "Logs ohne Query-Strings" '! grep -q "filename=gut.txt" "$T/logs"'

schritt "Verschlüsselte Sicherung → Prüfung → Totalverlust → Neuinstallation → Wiederherstellung"
"$HQ" backup > "$T/backup.log" 2>&1 || { tail -30 "$T/backup.log"; exit 1; }
pruefe "Sicherung erfolgreich (Status ok)" 'grep -q "\"ergebnis\":\"ok\"" /var/lib/ichq/backup.json'
echo "falscher-schluessel" > "$T/falsch.key"
pruefe "ohne richtigen Schlüssel nicht lesbar" 'HQ_BACKUP_KEY_FILE="$T/falsch.key" "$HQ" backup-status 2>&1 | grep -q "nicht erreichbar"'
"$HQ" backup-verify > "$T/verify.log" 2>&1 || { tail -30 "$T/verify.log"; exit 1; }
pruefe "Wiederherstellungstest (Wegwerf-DB, Prüfsummen, jede Datei)" 'grep -q "Wiederherstellungstest ok" "$T/verify.log"'
"$HQ" check > "$T/check.log" 2>&1 || { cat "$T/check.log"; exit 1; }
pruefe "Betriebsprüfung ohne FEHLER" '! grep -q "^FEHLER" "$T/check.log"'
docker compose -f "$ROOT/deploy/docker-compose.yml" --env-file "$ROOT/deploy/.env" down -v > /dev/null 2>&1
rm -rf "$ROOT/secrets"   # Totalverlust: Daten UND Geheimnisse weg; nur der getrennt verwahrte Sicherungsschlüssel bleibt
"$ROOT/deploy/install.sh" --domain "$DOMAIN" --email "$EMAIL" --skip-dns-check --no-systemd \
  --no-build ${CA_BAU:+--ca-file "$CA_BAU"} > "$T/install.log" 2>&1 || { tail -30 "$T/install.log"; exit 1; }
curl_opts
pruefe "nach Totalverlust: Konto existiert nicht mehr" '! anmelden'
"$HQ" restore latest --yes > "$T/restore.log" 2>&1 || { tail -30 "$T/restore.log"; exit 1; }
curl_opts
pruefe "nach Wiederherstellung: Anmeldung mit altem Passwort" anmelden
pruefe "Aufgabe wieder da" '[ "$(api "$B/api/v1/tasks")" = 200 ] && grep -q "Smoke-Aufgabe $SLUG" "$T/body"'
pruefe "Dokument wieder da, Inhalt gleich" '[ "$(api "$B/api/v1/documents/$GUT/content")" = 200 ] && cmp -s "$T/body" "$T/gut.txt"'
pruefe "EICAR weiterhin gesperrt" '[ "$(api "$B/api/v1/documents/$BOESE/content")" = 409 ]'

if [ "$NEUSTART" -eq 1 ]; then
  schritt "Neustart des Docker-Dienstes"
  systemctl restart docker
  for _ in $(seq 1 60); do "$HQ" status 2>/dev/null | grep -q "HTTPS: ok" && break; sleep 5; done
  curl_opts
  pruefe "nach Docker-Neustart: alles wieder erreichbar" '"$HQ" status | grep -q "HTTPS: ok"'
  pruefe "nach Docker-Neustart: Anmeldung" anmelden
fi
echo "== Ergebnis: $OK Prüfungen bestanden, 0 fehlgeschlagen"
