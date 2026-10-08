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
#   --email E           Kontakt für Let's Encrypt (Pflicht; Ablaufwarnungen)
#   --skip-dns-check    DNS-Prüfung überspringen (z. B. Server hinter NAT, DNS noch nicht verteilt)
#   --firewall          ufw einrichten: nur 22, 80, 443 eingehend
#   --no-systemd        keine systemd-Units (Autostart, tägliche Sicherung)
#   --backup-dir P      Ziel der täglichen Sicherung (Standard /var/backups/ichq)
#   --ca-file P         zusätzliche CA für den Image-Bau (nur hinter TLS-Proxy)
#   --no-build          vorhandenes Image ic-ware-hq:local nutzen (z. B. bei Docker-Hub-Limit „429")
#   --dockerhub-mirror M Basis-Image über Spiegel bauen (z. B. mirror.gcr.io) — gegen das Docker-Hub-Limit
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
DEPLOY="$ROOT/deploy"
ENVFILE="$DEPLOY/.env"
DOMAIN="" EMAIL="" DNS=1 FIREWALL=0 SYSTEMD=1 BACKUPDIR="/var/backups/ichq" CAFILE="" BAUEN=1 SPIEGEL=""

fehler() { echo "Fehler: $*" >&2; exit 1; }
info() { echo "==> $*"; }
hilfe() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --email) EMAIL="${2:-}"; shift 2 ;;
    --skip-dns-check) DNS=0; shift ;;
    --firewall) FIREWALL=1; shift ;;
    --no-systemd) SYSTEMD=0; shift ;;
    --no-build) BAUEN=0; shift ;;
    --dockerhub-mirror) SPIEGEL="${2:-}"; shift 2 ;;
    --backup-dir) BACKUPDIR="${2:-}"; shift 2 ;;
    --ca-file) CAFILE="$(readlink -f "${2:-}")"; shift 2 ;;
    -h|--help) hilfe ;;
    *) echo "unbekannte Option: $1" >&2; hilfe 1 ;;
  esac
done

# --- 1. Eingaben prüfen --------------------------------------------------------------------------------------------
[ -n "$DOMAIN" ] && [ -n "$EMAIL" ] || hilfe 1
DOMAIN="${DOMAIN,,}"
[[ "$DOMAIN" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ || "$DOMAIN" == localhost ]] \
  || fehler "ungültige Domain: $DOMAIN (nur Hostname, ohne https:// und ohne Pfad)"
# Strenge Zeichenliste: Domain und E-Mail landen über .env im Caddyfile ({$…} wird VOR dem Parsen ersetzt)
[[ "$EMAIL" =~ ^[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,63}$ ]] || fehler "ungültige E-Mail: $EMAIL"
[ -z "$CAFILE" ] || [ -f "$CAFILE" ] || fehler "--ca-file nicht gefunden"
case "$BACKUPDIR" in /*) ;; *) fehler "--backup-dir muss ein absoluter Pfad sein" ;; esac
[ "$(id -u)" -eq 0 ] || fehler "als root ausführen (sudo) — Secrets müssen UID 10001 gehören, systemd braucht root."
command -v python3 >/dev/null || fehler "python3 fehlt (für das Erzeugen der Geheimnisse): apt-get install python3"

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
if ! eigener_stack && command -v ss >/dev/null; then
  belegt="$(ss -ltnH 2>/dev/null | awk '{print $4}' | grep -E ':(80|443)$' || true)"
  [ -z "$belegt" ] || fehler "Port 80/443 belegt ($(echo "$belegt" | tr '\n' ' ')) — anderen Webserver (nginx/apache) stoppen."
fi

if [ "$DNS" -eq 1 ] && [ "$DOMAIN" != localhost ]; then
  info "DNS prüfen: $DOMAIN"
  aufgeloest="$(getent ahosts "$DOMAIN" | awk '{print $1}' | sort -u || true)"
  [ -n "$aufgeloest" ] || fehler "$DOMAIN löst nicht auf. A-Eintrag auf diesen Server setzen (oder --skip-dns-check)."
  eigene="$( (ip -o addr show 2>/dev/null | awk '{sub(/\/.*/, "", $4); print $4}'
             curl -4 -fsS --max-time 5 https://api.ipify.org 2>/dev/null; echo
             curl -6 -fsS --max-time 5 https://api64.ipify.org 2>/dev/null; echo) | grep -v '^$' | sort -u)"
  treffer="$(comm -12 <(echo "$aufgeloest") <(echo "$eigene"))"
  [ -n "$treffer" ] || fehler "$DOMAIN zeigt auf $(echo "$aufgeloest" | tr '\n' ' '), dieser Server hat $(echo "$eigene" | tr '\n' ' ').
  Ohne passenden DNS-Eintrag scheitert das Let's-Encrypt-Zertifikat. DNS korrigieren oder --skip-dns-check."
  info "DNS ok ($treffer)"
fi

# --- 4. Konfiguration + Geheimnisse ---------------------------------------------------------------------------------
info "Konfiguration schreiben: deploy/.env"
alt_wert() { [ -f "$ENVFILE" ] && sed -n "s/^$1=//p" "$ENVFILE" | tail -1 || true; }
CAFILE="${CAFILE:-$(alt_wert HQ_BUILD_CA_FILE)}"; SPIEGEL="${SPIEGEL:-$(alt_wert HQ_DOCKERHUB_MIRROR)}"
[[ -z "$SPIEGEL" || "$SPIEGEL" =~ ^[a-z0-9.-]+(:[0-9]+)?(/[a-z0-9._-]+)*$ ]] || fehler "ungültiger Spiegel: $SPIEGEL"
(umask 077; {
  echo "# von deploy/install.sh geschrieben — Änderungen: install.sh erneut ausführen"
  echo "ICHQ_DOMAIN=$DOMAIN"
  echo "ICHQ_ACME_EMAIL=$EMAIL"
  [ -z "$CAFILE" ] || echo "HQ_BUILD_CA_FILE=$CAFILE"
  [ -z "$SPIEGEL" ] || echo "HQ_DOCKERHUB_MIRROR=$SPIEGEL"
} > "$ENVFILE.neu" && mv "$ENVFILE.neu" "$ENVFILE")
if [ -d "$ROOT/secrets" ]; then
  info "Geheimnisse vorhanden — bleiben unverändert, Rechte werden geprüft"
  "$DEPLOY/fix-secret-permissions.sh"
else
  info "Geheimnisse erzeugen"
  "$DEPLOY/generate-secrets.sh"
fi

# --- 5. Bauen + Starten --------------------------------------------------------------------------------------------
if [ "$BAUEN" -eq 1 ] || ! docker image inspect ic-ware-hq:local >/dev/null 2>&1; then "$DEPLOY/hq" build; fi
"$DEPLOY/hq" start

# --- 6. Dauerbetrieb: Autostart + tägliche Sicherung -----------------------------------------------------------------
if [ "$SYSTEMD" -eq 1 ]; then
  if [ -d /run/systemd/system ]; then
    info "systemd: ichq.service (Start beim Booten) + ichq-backup.timer (täglich 03:15)"
    for f in ichq.service ichq-backup.service ichq-backup.timer; do
      sed -e "s#@ROOT@#$ROOT#g" -e "s#@BACKUPDIR@#$BACKUPDIR#g" "$DEPLOY/systemd/$f.in" > "/etc/systemd/system/$f"
    done
    systemctl daemon-reload
    systemctl enable ichq.service >/dev/null
    systemctl enable --now ichq-backup.timer >/dev/null
  else
    echo "WARNUNG: kein systemd — Autostart nur über Docker (restart: unless-stopped), keine tägliche Sicherung." >&2
  fi
fi

if [ "$FIREWALL" -eq 1 ]; then
  command -v ufw >/dev/null || apt-get install -yq ufw
  info "Firewall: 22, 80, 443 eingehend"
  ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw allow 443/udp >/dev/null
  ufw --force enable >/dev/null
fi

cat <<EOF

IC WARE HQ läuft: https://$DOMAIN/app/

Nächste Schritte:
  1. Erste Firma + Admin:   sudo deploy/hq setup-admin
  2. Zustand:               sudo deploy/hq status
  3. Sicherung testen:      sudo deploy/hq backup && ls -l $BACKUPDIR
     Sicherungen enthalten die Geheimnisse — regelmäßig verschlüsselt auf einen anderen Rechner kopieren.
  4. Updates:               sudo deploy/hq update   (sichert vorher automatisch)

Hinweis: ClamAV lädt beim ersten Start Virensignaturen (einige Minuten). Bis dahin bleiben hochgeladene Dokumente
in Quarantäne („Virenprüfung läuft") und werden danach automatisch geprüft.
EOF
