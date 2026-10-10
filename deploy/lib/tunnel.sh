# shellcheck shell=bash
# IC WARE HQ — Tunnelbetrieb über Cloudflare (ADR-018) und Domainwechsel. Eingebunden von deploy/hq und deploy/install.sh.
#
# Tunnelbetrieb: cloudflared baut eine AUSGEHENDE Verbindung zu Cloudflare auf; Besucher erreichen https://<domain>
# über Cloudflare. Kein offener Port am Router, funktioniert auch hinter CGNAT/DS-Lite (privater PC, Heimnetz).
# Preis: Cloudflare beendet TLS und sieht den Verkehr im Klartext (ADR-018).

domain_gueltig() {   # nur Hostname: landet über .env im Caddyfile ({$…} wird VOR dem Parsen ersetzt)
  [[ "$1" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ || "$1" == localhost ]]
}

token_gueltig() {    # Cloudflare-Tunnel-Token: Base64 (JSON mit Konto, Tunnel, Geheimnis), keine Leer-/Sonderzeichen
  [[ "$1" =~ ^[A-Za-z0-9+/_=-]{80,4096}$ ]]
}

tunnel_modus() { [ "$(env_wert HQ_ZUGANG 2>/dev/null || true)" = tunnel ]; }

env_aendern() {      # env_aendern KEY WERT — setzt einen Eintrag in deploy/.env, alle anderen bleiben
  (umask 077; touch "$ENVFILE")
  K="$1" V="$2" awk 'index($0, ENVIRON["K"] "=") == 1 { print ENVIRON["K"] "=" ENVIRON["V"]; ok = 1; next }
    { print } END { if (!ok) print ENVIRON["K"] "=" ENVIRON["V"] }' "$ENVFILE" > "$ENVFILE.neu"
  chmod 600 "$ENVFILE.neu" && mv "$ENVFILE.neu" "$ENVFILE"
}

token_pruefen() {
  token_gueltig "$1" || fehler "Das ist kein Cloudflare-Tunnel-Token (Zero Trust → Networks → Tunnels → Tunnel →
  'Install connector': die lange Zeichenkette nach '--token' bzw. 'service install')."
}

token_speichern() {  # token_speichern <token> — als Secret-Datei (nie in .env, nie als Argument an Container)
  token_pruefen "$1"
  (umask 077; printf '%s' "$1" > "$ROOT/secrets/cloudflare_tunnel_token")
  "$DEPLOY/fix-secret-permissions.sh" >/dev/null
}

token_abfragen() {   # Token aus HQ_TUNNEL_TOKEN oder verdeckter Eingabe (nie als Kommandozeilen-Argument: ps/Verlauf)
  local t="${HQ_TUNNEL_TOKEN:-}"
  if [ -z "$t" ] && [ -t 0 ]; then read -rsp "Cloudflare-Tunnel-Token (Eingabe unsichtbar): " t; echo >&2; fi
  [ -n "$t" ] || fehler "Tunnel-Token fehlt (HQ_TUNNEL_TOKEN setzen oder interaktiv ausführen)."
  printf '%s' "$t"
}

modus_setzen() {     # modus_setzen tunnel|direkt
  if [ "$1" = tunnel ]; then
    env_aendern HQ_ZUGANG tunnel; env_aendern ICHQ_CADDYFILE Caddyfile.tunnel; env_aendern ICHQ_BIND 127.0.0.1
  else
    env_aendern HQ_ZUGANG direkt; env_aendern ICHQ_CADDYFILE Caddyfile; env_aendern ICHQ_BIND 0.0.0.0
  fi
}

cloudflare_anleitung() {   # cloudflare_anleitung <domain>
  cat <<EOF

In Cloudflare (dash.cloudflare.com → Zero Trust → Networks → Tunnels → Ihr Tunnel → „Public Hostname"):
  Hostname:  $1
  Dienst:    HTTP   caddy:80          (genau so — NICHT localhost)
Die Domain muss in Cloudflare verwaltet sein (Nameserver bei Cloudflare). Den DNS-Eintrag legt Cloudflare dabei an.
Empfohlen: SSL/TLS → Edge-Zertifikate → „Always Use HTTPS" einschalten.
EOF
}

domain_aendern() {   # deploy/hq domain <neue-domain> [--skip-dns-check]
  local neu="${1:-}" alt
  neu="${neu,,}"
  [ -n "$neu" ] || fehler "Aufruf: deploy/hq domain <neue-domain>   (z. B. hq.meine-firma.de)"
  domain_gueltig "$neu" || fehler "ungültige Domain: $neu (nur Hostname, ohne https:// und ohne Pfad)"
  alt="$(env_wert ICHQ_DOMAIN)"
  [ "$neu" != "$alt" ] || { info "Domain ist bereits $neu."; return 0; }
  if tunnel_modus; then
    info "Tunnelbetrieb: zuerst in Cloudflare den Hostnamen ändern (bzw. zusätzlich anlegen):"
    cloudflare_anleitung "$neu"
    if [ -t 0 ]; then
      local ok; read -rp "In Cloudflare erledigt? Domain jetzt umstellen [j/N]: " ok
      [[ "$ok" =~ ^[jJyY]$ ]] || { info "Abgebrochen — nichts geändert."; return 1; }
    fi
  elif [ "${2:-}" != --skip-dns-check ] && [ "$neu" != localhost ]; then
    info "DNS prüfen: $neu"
    dns_pruefen "$neu" || fehler "DNS passt nicht — erst den A-Eintrag setzen (oder --skip-dns-check)."
  fi
  info "Domain $alt → $neu"
  env_aendern ICHQ_DOMAIN "$neu"
  compose up -d --remove-orphans   # App (Origin, Mail-Links) und Caddy (Site/Zertifikat) mit neuer Domain
  warten
  cat <<EOF

Neue Adresse: https://$neu/app/
Hinweise: Alle Nutzer melden sich unter der neuen Adresse neu an (Sitzungen gelten je Domain). Einladungs- und
Reset-Links, die vorher verschickt wurden, zeigen auf die alte Adresse — bei Bedarf neu senden.
Windows-Launcher: Startmenü → „IC WARE HQ – Adresse ändern".
EOF
}

tunnel_token_aendern() {   # deploy/hq tunnel-token — neues Token (z. B. nach „Refresh token" in Cloudflare)
  tunnel_modus || fehler "Kein Tunnelbetrieb (einrichten: deploy/install.sh … --tunnel)."
  token_speichern "$(token_abfragen)"
  compose up -d --force-recreate cloudflared
  info "Token ersetzt, cloudflared neu gestartet. Prüfen: deploy/hq diagnose"
}

# ---- Diagnose im Tunnelbetrieb --------------------------------------------------------------------------------------
cloudflared_deuten() {   # cloudflared-Log (stdin) → verständliche Ursachen
  local log; log="$(cat)"
  _ist() { grep -qiE "$1" <<< "$log"; }
  _ist 'token is not valid|Unauthorized|invalid tunnel secret|failed to unmarshal.*token' \
    && echo "Cloudflare lehnt das Tunnel-Token ab — neues Token eintragen: deploy/hq tunnel-token"
  _ist 'failed to dial|dial tcp.*7844|i/o timeout|no such host|context deadline exceeded' \
    && echo "Keine Verbindung zu Cloudflare — Internet? Ausgehend TCP/UDP 7844 und 443 dürfen nicht gesperrt sein."
  _ist 'Unable to reach the origin service|connection refused.*caddy|no such host.*caddy' \
    && echo "Cloudflare erreicht Caddy nicht — in Cloudflare als Dienst genau 'HTTP caddy:80' eintragen."
  _ist 'Registered tunnel connection' \
    && echo "OK: Tunnel mit Cloudflare verbunden."
  return 0
}

tunnel_antwort_deuten() {   # tunnel_antwort_deuten <http-code> <domain> → Stufe|Text
  case "$1" in
    200) echo "OK|https://$2 ist öffentlich erreichbar (über Cloudflare)" ;;
    530|1033) echo "FEHLER|Cloudflare kennt die Domain, der Tunnel ist aber nicht verbunden (cloudflared läuft? Token?)" ;;
    502|504) echo "FEHLER|Tunnel verbunden, aber Dienst falsch eingetragen — in Cloudflare 'HTTP caddy:80'" ;;
    000) echo "FEHLER|https://$2 nicht erreichbar — Domain nicht in Cloudflare oder Hostname im Tunnel fehlt" ;;
    *) echo "FEHLER|https://$2 antwortet mit HTTP $1 — stimmt der Hostname im Tunnel mit ICHQ_DOMAIN überein?" ;;
  esac
}

tunnel_diagnose() {
  local domain code zustand
  domain="$(env_wert ICHQ_DOMAIN)"
  zustand="$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' \
    "$(compose ps -q cloudflared 2>/dev/null | head -1)" 2>/dev/null || echo fehlt)"
  case "$zustand" in
    "running healthy") melde OK cloudflared "läuft, mit Cloudflare verbunden" ;;
    running*) melde FEHLER cloudflared "läuft, aber nicht verbunden ($zustand)" ;;
    *) melde FEHLER cloudflared "läuft nicht ($zustand) — deploy/hq start" ;;
  esac
  if [ -s "$ROOT/secrets/cloudflare_tunnel_token" ]; then melde OK token "vorhanden"
  else melde FEHLER token "fehlt — deploy/hq tunnel-token"; fi
  while IFS= read -r z; do
    case "$z" in OK:*) melde OK tunnel-log "${z#OK: }" ;; *) melde FEHLER tunnel-log "$z" ;; esac
  done < <(compose logs --no-color --tail 300 cloudflared 2>/dev/null | cloudflared_deuten)
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://$domain/readiness" || true)"
  IFS='|' read -r stufe text <<< "$(tunnel_antwort_deuten "${code:-000}" "$domain")"
  melde "$stufe" oeffentlich "$text"
  if docker ps --filter label=com.docker.compose.project=ichq --format '{{.Ports}}' | grep -qE '0\.0\.0\.0:|\[::\]:'; then
    melde FEHLER intern "ein Dienst ist im Tunnelbetrieb aus dem Netz erreichbar (ICHQ_BIND=127.0.0.1 erwartet)"
  else melde OK intern "keine offenen Ports nach außen (nur Tunnel)"; fi
}
