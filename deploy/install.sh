#!/usr/bin/env bash
# IC WARE HQ — Einrichtung auf einem eigenen Linux-Server mit fester Domain (ADR-015). Idempotent: erneut ausführen
# ändert Domain/E-Mail, legt fehlende Teile an und überschreibt NIE vorhandene Geheimnisse.
#
#   sudo deploy/install.sh --domain hq.example.de --email admin@example.de
#
# Voraussetzungen: Debian/Ubuntu (andere Linux mit bereits installiertem Docker gehen auch), ≥ 4 GB RAM (ClamAV
# braucht ~1,5 GB), DNS-A/AAAA-Eintrag der Domain zeigt auf diesen Server, Ports 80 und 443 aus dem Internet offen.
#
# Optionen:
#   --domain D          feste Domain (Pflicht), z. B. hq.ic-ware.eu
#   --email E           Kontakt für Let's Encrypt bzw. Betreiber (Pflicht; Ablaufwarnungen)
#   --skip-dns-check    DNS-Prüfung überspringen (z. B. Server hinter NAT, DNS noch nicht verteilt)
#   --tunnel            Tunnelbetrieb über Cloudflare (ADR-018): kein offener Port, z. B. privater PC im Heimnetz.
#                       Token: Umgebung HQ_TUNNEL_TOKEN oder verdeckte Abfrage. Zurück: --no-tunnel
#   --firewall          ufw einrichten: nur 22, 80, 443 eingehend
#   --no-systemd        keine systemd-Units (Autostart, Sicherung, Prüfung)
#   --backup-repository R  Sicherungsziel, extern: s3:https://<endpunkt>/<bucket>/<pfad> (ADR-016);
#                       S3-Zugang danach in /etc/ichq/backup-s3.env. Ohne: verschlüsselt auf diesem Server
#   --alert-email E     Betreiberwarnungen (Sicherung, Dienste, Speicher, Zertifikat) an diese Adresse
#   --smtp-host H  --smtp-port P  --smtp-user U  --smtp-from F  [--smtp-ssl | --smtp-plain]
#                       --smtp-plain nur für lokale Relays ohne Anmeldung (sonst ist TLS Pflicht)
#                       E-Mail-Versand (Einladungen, Passwort-Reset, Warnungen). Passwort: Umgebung
#                       HQ_SMTP_PASSWORD oder Abfrage. Ohne SMTP: Reset/Einladung antworten 503
#   --ca-file P         zusätzliche CA für den Image-Bau (nur hinter TLS-Proxy)
#   --no-build          vorhandenes Image ic-ware-hq:local nutzen (z. B. bei Docker-Hub-Limit „429")
#   --dockerhub-mirror M Basis-Image über Spiegel bauen (z. B. mirror.gcr.io) — gegen das Docker-Hub-Limit
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
DEPLOY="$ROOT/deploy"
ENVFILE="$DEPLOY/.env"
DOMAIN="" EMAIL="" DNS=1 TUNNEL="" FIREWALL=0 SYSTEMD=1 CAFILE="" BAUEN=1 SPIEGEL="" REPO="" ALERT=""
SMTP_HOST="" SMTP_PORT="" SMTP_USER="" SMTP_FROM="" SMTP_SSL=""

fehler() { echo "Fehler: $*" >&2; exit 1; }
info() { echo "==> $*"; }
hilfe() { sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --email) EMAIL="${2:-}"; shift 2 ;;
    --skip-dns-check) DNS=0; shift ;;
    --tunnel) TUNNEL=1; shift ;;
    --no-tunnel) TUNNEL=0; shift ;;
    --firewall) FIREWALL=1; shift ;;
    --no-systemd) SYSTEMD=0; shift ;;
    --no-build) BAUEN=0; shift ;;
    --dockerhub-mirror) SPIEGEL="${2:-}"; shift 2 ;;
    --backup-repository) REPO="${2:-}"; shift 2 ;;
    --alert-email) ALERT="${2:-}"; shift 2 ;;
    --smtp-host) SMTP_HOST="${2:-}"; shift 2 ;;
    --smtp-port) SMTP_PORT="${2:-}"; shift 2 ;;
    --smtp-user) SMTP_USER="${2:-}"; shift 2 ;;
    --smtp-from) SMTP_FROM="${2:-}"; shift 2 ;;
    --smtp-ssl) SMTP_SSL=1; shift ;;
    --smtp-plain) SMTP_SSL=plain; shift ;;
    --ca-file) CAFILE="$(readlink -f "${2:-}")"; shift 2 ;;
    -h|--help) hilfe ;;
    *) echo "unbekannte Option: $1" >&2; hilfe 1 ;;
  esac
done

# --- 1. Eingaben prüfen --------------------------------------------------------------------------------------------
# shellcheck source=deploy/lib/tunnel.sh
. "$DEPLOY/lib/tunnel.sh"
[ -n "$DOMAIN" ] && [ -n "$EMAIL" ] || hilfe 1
[ -z "${HQ_TUNNEL_TOKEN:-}" ] || token_pruefen "$HQ_TUNNEL_TOKEN"   # vor jeder Änderung, auch ohne root
DOMAIN="${DOMAIN,,}"
[[ "$DOMAIN" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ || "$DOMAIN" == localhost ]] \
  || fehler "ungültige Domain: $DOMAIN (nur Hostname, ohne https:// und ohne Pfad)"
# Strenge Zeichenliste: Domain und E-Mail landen über .env im Caddyfile ({$…} wird VOR dem Parsen ersetzt)
[[ "$EMAIL" =~ ^[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,63}$ ]] || fehler "ungültige E-Mail: $EMAIL"
[ -z "$CAFILE" ] || [ -f "$CAFILE" ] || fehler "--ca-file nicht gefunden"
MAILRE='^[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,63}$'
[[ -z "$REPO" || "$REPO" =~ ^(s3:https?://[A-Za-z0-9.-]+(:[0-9]+)?|/)[A-Za-z0-9._/-]*$ ]] \
  || fehler "ungültiges --backup-repository (s3:https://host/bucket/pfad oder absoluter Pfad)"
[[ -z "$ALERT" || "$ALERT" =~ $MAILRE ]] || fehler "ungültige --alert-email"
[[ -z "$SMTP_HOST" || "$SMTP_HOST" =~ ^[A-Za-z0-9.-]+$ ]] || fehler "ungültiger --smtp-host"
[[ -z "$SMTP_PORT" || "$SMTP_PORT" =~ ^[0-9]{1,5}$ ]] || fehler "ungültiger --smtp-port"
[[ -z "$SMTP_USER" || "$SMTP_USER" =~ ^[A-Za-z0-9._%+@-]+$ ]] || fehler "ungültiger --smtp-user"
[[ -z "$SMTP_FROM" || "$SMTP_FROM" =~ $MAILRE || "$SMTP_FROM" =~ ^[A-Za-z0-9\ .-]+\ \<[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\>$ ]] \
  || fehler "ungültiger --smtp-from (adresse@domain oder Name <adresse@domain>)"
[[ -z "$SMTP_HOST" || -n "$SMTP_FROM" ]] || fehler "--smtp-host braucht --smtp-from"
[ "$(id -u)" -eq 0 ] || fehler "als root ausführen (sudo) — Secrets müssen UID 10001 gehören, systemd braucht root."
command -v python3 >/dev/null || fehler "python3 fehlt (für das Erzeugen der Geheimnisse): apt-get install python3"
alt_wert() { [ -f "$ENVFILE" ] && sed -n "s/^$1=//p" "$ENVFILE" | tail -1 || true; }
env_wert() { alt_wert "$1"; }
[ -n "$TUNNEL" ] || { [ "$(alt_wert HQ_ZUGANG)" = tunnel ] && TUNNEL=1 || TUNNEL=0; }   # Wiederholung: Modus bleibt
[ "$TUNNEL" -eq 0 ] || [ "$FIREWALL" -eq 0 ] || fehler "--firewall ist im Tunnelbetrieb unnötig (keine eingehenden Ports)."
TOKEN=""
if [ "$TUNNEL" -eq 1 ] && { [ -n "${HQ_TUNNEL_TOKEN:-}" ] || [ ! -s "$ROOT/secrets/cloudflare_tunnel_token" ]; }; then
  TOKEN="$(token_abfragen)"; token_pruefen "$TOKEN"   # vor allen Änderungen: ungültig ⇒ Abbruch mit Erklärung
fi

# --- 2. Docker -----------------------------------------------------------------------------------------------------
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  . /etc/os-release
  case "${ID:-}" in debian|ubuntu) ;; *) fehler "Docker fehlt. Automatisch nur auf Debian/Ubuntu — bitte Docker Engine + Compose-Plugin selbst installieren." ;; esac
  info "Docker installieren (offizielles Repository download.docker.com)"
  apt-get update -q
  apt-get install -yq ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID ${VERSION_CODENAME:?} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
command -v systemctl >/dev/null && [ -d /run/systemd/system ] && systemctl enable --now docker >/dev/null 2>&1 || true
docker info >/dev/null 2>&1 || fehler "Docker-Dienst läuft nicht (systemctl start docker)."
command -v curl >/dev/null || fehler "curl fehlt: apt-get install curl"

# --- 3. Speicher, Ports, DNS ---------------------------------------------------------------------------------------
mem_mb=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
[ "$mem_mb" -ge 3500 ] || echo "WARNUNG: nur ${mem_mb} MB RAM — ClamAV braucht ~1,5 GB, empfohlen sind 4 GB." >&2

eigener_stack() { docker ps --filter label=com.docker.compose.project=ichq --filter label=com.docker.compose.service=caddy -q | grep -q .; }
if [ "$TUNNEL" -eq 0 ] && ! eigener_stack && command -v ss >/dev/null; then
  belegt="$(ss -ltnH 2>/dev/null | awk '{print $4}' | grep -E ':(80|443)$' || true)"
  [ -z "$belegt" ] || fehler "Port 80/443 belegt ($(echo "$belegt" | tr '\n' ' ')) — anderen Webserver (nginx/apache) stoppen."
fi

if [ "$TUNNEL" -eq 1 ]; then
  info "Tunnelbetrieb: keine DNS-/Port-Prüfung hier — die Domain zeigt auf Cloudflare (deploy/hq diagnose danach)"
elif [ "$DNS" -eq 1 ] && [ "$DOMAIN" != localhost ]; then
  info "DNS prüfen: $DOMAIN (A und AAAA — JEDER Eintrag muss auf diesen Server zeigen)"
  # shellcheck source=deploy/lib/diagnose.sh
  . "$DEPLOY/lib/diagnose.sh"
  dns_pruefen "$DOMAIN" || fehler "DNS passt nicht (siehe oben). Ohne passenden Eintrag scheitert das Let's-Encrypt-Zertifikat.
  Korrigieren und erneut ausführen — oder --skip-dns-check (z. B. DNS noch nicht verteilt)."
  info "DNS ok"
fi

# --- 4. Konfiguration + Geheimnisse ---------------------------------------------------------------------------------
info "Konfiguration schreiben: deploy/.env"
CAFILE="${CAFILE:-$(alt_wert HQ_BUILD_CA_FILE)}"; SPIEGEL="${SPIEGEL:-$(alt_wert HQ_DOCKERHUB_MIRROR)}"
[[ -z "$SPIEGEL" || "$SPIEGEL" =~ ^[a-z0-9.-]+(:[0-9]+)?(/[a-z0-9._-]+)*$ ]] || fehler "ungültiger Spiegel: $SPIEGEL"
[[ "$CAFILE" =~ ^[A-Za-z0-9._/-]*$ ]] || fehler "--ca-file: Pfad mit unerlaubten Zeichen"
env_setzen() {   # setzt KEY=WERT in deploy/.env, alle anderen Einträge bleiben (Wiederholbarkeit)
  [ -n "$2" ] || return 0
  (umask 077; touch "$ENVFILE")
  K="$1" V="$2" awk 'index($0, ENVIRON["K"] "=") == 1 { print ENVIRON["K"] "=" ENVIRON["V"]; ok = 1; next }
    { print } END { if (!ok) print ENVIRON["K"] "=" ENVIRON["V"] }' "$ENVFILE" > "$ENVFILE.neu"
  chmod 600 "$ENVFILE.neu" && mv "$ENVFILE.neu" "$ENVFILE"
}
[ -f "$ENVFILE" ] || (umask 077; echo "# deploy/install.sh — Werte per Option ändern, andere bleiben erhalten" > "$ENVFILE")
env_setzen ICHQ_DOMAIN "$DOMAIN"; env_setzen ICHQ_ACME_EMAIL "$EMAIL"
env_setzen HQ_BUILD_CA_FILE "$CAFILE"; env_setzen HQ_DOCKERHUB_MIRROR "$SPIEGEL"
env_setzen HQ_BACKUP_REPOSITORY "$REPO"; env_setzen ICHQ_ALERT_EMAIL "$ALERT"
env_setzen ICHQ_SMTP_HOST "$SMTP_HOST"; env_setzen ICHQ_SMTP_PORT "$SMTP_PORT"
env_setzen ICHQ_SMTP_USER "$SMTP_USER"; env_setzen ICHQ_SMTP_FROM "$SMTP_FROM"
[[ "$SMTP_SSL" != plain || -z "$SMTP_USER" ]] || fehler "--smtp-plain nur ohne --smtp-user (Passwort nie unverschlüsselt)"
case "$SMTP_SSL" in
  1) env_setzen ICHQ_SMTP_SSL true; env_setzen ICHQ_SMTP_STARTTLS false ;;
  plain) env_setzen ICHQ_SMTP_SSL false; env_setzen ICHQ_SMTP_STARTTLS false ;;
esac
if [ -d "$ROOT/secrets" ]; then
  info "Geheimnisse vorhanden — bleiben unverändert, Rechte werden geprüft"
  "$DEPLOY/fix-secret-permissions.sh"
else
  info "Geheimnisse erzeugen"
  "$DEPLOY/generate-secrets.sh"
fi
if [ "$TUNNEL" -eq 1 ]; then modus_setzen tunnel; [ -z "$TOKEN" ] || token_speichern "$TOKEN"
else
  modus_setzen direkt
  docker rm -f "$(docker ps -aq --filter label=com.docker.compose.project=ichq \
    --filter label=com.docker.compose.service=cloudflared)" >/dev/null 2>&1 || true   # Wechsel aus dem Tunnelbetrieb
fi
if [ -n "$SMTP_USER" ]; then   # SMTP-Passwort nie als Argument: Umgebung oder verdeckte Abfrage
  pw="${HQ_SMTP_PASSWORD:-}"
  if [ -z "$pw" ] && [ -t 0 ]; then read -rsp "SMTP-Passwort für $SMTP_USER: " pw; echo; fi
  [ -n "$pw" ] || fehler "SMTP-Passwort fehlt (HQ_SMTP_PASSWORD setzen oder interaktiv ausführen)"
  (umask 077; printf '%s' "$pw" > "$ROOT/secrets/smtp_password"); unset pw
  "$DEPLOY/fix-secret-permissions.sh"
fi

# --- 5. Bauen + Starten --------------------------------------------------------------------------------------------
if [ "$BAUEN" -eq 1 ] || ! docker image inspect ic-ware-hq:local >/dev/null 2>&1; then "$DEPLOY/hq" build; fi
"$DEPLOY/hq" start

# --- 6. Dauerbetrieb: Autostart, Sicherung, Wiederherstellungstest, Betriebsprüfung -------------------------------
"$DEPLOY/hq" backup-init
if [ "$SYSTEMD" -eq 1 ]; then
  if [ -d /run/systemd/system ]; then
    info "systemd: Autostart, Sicherung alle 6 h, Wiederherstellungstest wöchentlich, Betriebsprüfung alle 5 min"
    for f in ichq.service ichq-backup.service ichq-backup.timer ichq-backup-verify.service ichq-backup-verify.timer \
             ichq-check.service ichq-check.timer; do
      sed -e "s#@ROOT@#$ROOT#g" "$DEPLOY/systemd/$f.in" > "/etc/systemd/system/$f"
    done
    systemctl daemon-reload
    systemctl enable ichq.service >/dev/null
    systemctl enable --now ichq-backup.timer ichq-backup-verify.timer ichq-check.timer >/dev/null
  else
    echo "WARNUNG: kein systemd — Autostart nur über Docker (restart: unless-stopped); Sicherung und Prüfung" \
         "müssen per cron laufen (deploy/hq backup · backup-verify · check --alert)." >&2
  fi
fi

if [ "$FIREWALL" -eq 1 ]; then
  command -v ufw >/dev/null || apt-get install -yq ufw
  info "Firewall: 22, 80, 443 eingehend"
  ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw allow 443/udp >/dev/null
  ufw --force enable >/dev/null
fi

[ "$TUNNEL" -eq 0 ] || cloudflare_anleitung "$DOMAIN"
cat <<EOF

IC WARE HQ läuft: https://$DOMAIN/app/

Nächste Schritte:
  1. Erste Firma + Admin:   sudo deploy/hq setup-admin
  2. Zustand:               sudo deploy/hq status
  3. Sicherung testen:      sudo deploy/hq backup && sudo deploy/hq backup-verify
     Den oben angezeigten SICHERUNGSSCHLÜSSEL getrennt vom Server aufbewahren (/etc/ichq/backup.key).
  4. Updates:               sudo deploy/hq update   (sichert vorher automatisch)

Hinweis: ClamAV lädt beim ersten Start Virensignaturen (einige Minuten). Bis dahin bleiben hochgeladene Dokumente
in Quarantäne („Virenprüfung läuft") und werden danach automatisch geprüft.
EOF
