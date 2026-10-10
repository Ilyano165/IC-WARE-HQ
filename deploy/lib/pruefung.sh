# shellcheck shell=bash
# IC WARE HQ — Betriebsprüfung `deploy/hq check [--alert]` (ADR-016). Wird von deploy/hq eingebunden.
#
# Prüft Dienste und ihre Healthchecks, App, HTTPS + Restlaufzeit des Zertifikats, Outbox/Mail/Virenprüfung,
# Platte, Arbeitsspeicher, Sicherung und Wiederherstellungstest. Ausgabe je Zeile: OK|WARNUNG|FEHLER <name>: <text>.
# Exitcode 1 bei FEHLER. Mit --alert: Mail an ICHQ_ALERT_EMAIL bei neuem Problem (+ täglich Erinnerung) und bei
# Entwarnung; ohne FEHLER wird HQ_HEARTBEAT_URL angepingt (externer „Totmannschalter", z. B. healthchecks.io —
# fällt der ganze Server aus, meldet sich der externe Dienst).

DAUERDIENSTE="postgres app worker jobs scanner clamav caddy"
PRUEF_FEHLER=0

melde() {   # melde <OK|WARNUNG|FEHLER> <name> <text>
  printf '%-8s %s: %s\n' "$1" "$2" "$3"
  [ "$1" = OK ] || echo "$1|$2|$3" >> "$TMP/probleme"
  [ "$1" = FEHLER ] && PRUEF_FEHLER=1
  return 0
}

alter_s() { echo $(( $(date +%s) - $1 )); }

pruefe_dienste() {
  local d zustand st gesund neustarts dienste="$DAUERDIENSTE"
  tunnel_modus && dienste="$dienste cloudflared"
  for d in $dienste; do
    zustand="$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}} {{.RestartCount}}' \
      "$(compose ps -q "$d" 2>/dev/null | head -1)" 2>/dev/null || echo "fehlt - 0")"
    read -r st gesund neustarts <<< "$zustand"
    if [ "$st" != running ]; then melde FEHLER "dienst-$d" "Zustand $st"
    elif [ "$gesund" = unhealthy ]; then melde FEHLER "dienst-$d" "Healthcheck schlägt fehl"
    elif [ "${neustarts:-0}" -gt 5 ]; then melde WARNUNG "dienst-$d" "$neustarts Neustarts"
    else melde OK "dienst-$d" "läuft (${gesund/-/ohne Healthcheck})"; fi
  done
}

pruefe_https() {
  local domain tage ca="" ziel
  domain="$(env_wert ICHQ_DOMAIN)"
  if app_bereit; then melde OK app "bereit"; else melde FEHLER app "/readiness nicht 200"; fi
  [ "$domain" = localhost ] && compose exec -T caddy cat /data/caddy/pki/authorities/local/root.crt > "$TMP/ca.crt" \
    2>/dev/null && ca="$TMP/ca.crt"
  ziel=127.0.0.1; tunnel_modus && ziel="$domain"   # Tunnel: Zertifikat liefert Cloudflare (öffentlich prüfen)
  tage="$(python3 - "$domain" "$ca" "$ziel" <<'PY' 2>/dev/null
import socket, ssl, sys, time
domain, ca, ziel = sys.argv[1], sys.argv[2], sys.argv[3]
ctx = ssl.create_default_context(cafile=ca or None)
with socket.create_connection((ziel, 443), timeout=10) as roh, ctx.wrap_socket(roh, server_hostname=domain) as s:
    print(int((ssl.cert_time_to_seconds(s.getpeercert()["notAfter"]) - time.time()) // 3600))
PY
)"
  if [ -z "$tage" ]; then melde FEHLER https "kein gültiges Zertifikat für $domain (deploy/hq logs caddy)"
  elif [ "$domain" = localhost ]; then melde OK https "interne CA, noch $tage h gültig (erneuert Caddy laufend)"
  elif tunnel_modus && [ $(( tage / 24 )) -ge 7 ]; then melde OK https "Cloudflare-Zertifikat noch $(( tage / 24 )) Tage gültig"
  elif tage=$(( tage / 24 )) && [ "$tage" -lt 7 ]; then melde FEHLER https "Zertifikat läuft in $tage Tagen ab — Erneuerung scheitert?"
  elif [ "$tage" -lt 20 ]; then melde WARNUNG https "Zertifikat läuft in $tage Tagen ab"
  else melde OK https "Zertifikat noch $tage Tage gültig"; fi
  if https_pruefen; then melde OK https-erreichbar "https://$domain/readiness"
  else melde FEHLER https-erreichbar "https://$domain nicht erreichbar"; fi
}

pruefe_hintergrund() {
  local j
  j="$(compose exec -T scanner ichq ops-check 2>/dev/null | tail -1)"   # Scanner kennt auch ClamAV
  if [ -z "$j" ]; then melde FEHLER hintergrund "ichq ops-check nicht ausführbar (Datenbank?)"; return; fi
  python3 - "$j" <<'PY' >> "$TMP/hintergrund"
import json, sys
d = json.loads(sys.argv[1])
def m(stufe, name, text): print(f"{stufe}|{name}|{text}")
m("FEHLER" if d["outbox_failed"] else "OK", "outbox", f'{d["outbox_failed"]} endgültig gescheitert')
m("WARNUNG" if d["outbox_pending_age_s"] > 600 else "OK", "outbox-rueckstau", f'älteste wartet {d["outbox_pending_age_s"]} s')
m("FEHLER" if d["mail_failed"] else "OK", "mail", f'{d["mail_failed"]} Mails gescheitert (ichq mail-retry)')
m("WARNUNG" if d["mail_pending_age_s"] > 1800 else "OK", "mail-rueckstau", f'älteste wartet {d["mail_pending_age_s"]} s')
m("OK" if d["mail_configured"] else "WARNUNG", "mail-smtp", "eingerichtet" if d["mail_configured"] else "kein SMTP — Reset/Einladung/Warnungen gehen nicht raus")
m({True: "OK", False: "FEHLER", None: "WARNUNG"}[d["clamd_ok"]], "clamav",
  {True: "antwortet", False: "antwortet nicht", None: "nicht geprüft (ICHQ_CLAMD_HOST fehlt)"}[d["clamd_ok"]])
m("WARNUNG" if d["quarantine_oldest_s"] > 3600 else "OK", "virenpruefung", f'{d["quarantine"]} in Quarantäne, älteste {d["quarantine_oldest_s"]} s')
PY
  while IFS='|' read -r stufe name text; do melde "$stufe" "$name" "$text"; done < "$TMP/hintergrund"
}

pruefe_ressourcen() {
  local pfad frei ram
  for pfad in / "$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)"; do
    frei="$(df -P "$pfad" | awk 'NR==2 {print 100 - $5}')"
    if [ "$frei" -lt 10 ]; then melde FEHLER "platte:$pfad" "nur $frei % frei"
    elif [ "$frei" -lt 20 ]; then melde WARNUNG "platte:$pfad" "nur $frei % frei"
    else melde OK "platte:$pfad" "$frei % frei"; fi
  done
  ram="$(awk '/MemAvailable/ {a=$2} /MemTotal/ {t=$2} END {print int(a*100/t)}' /proc/meminfo)"
  if [ "$ram" -lt 5 ]; then melde FEHLER arbeitsspeicher "nur $ram % verfügbar"
  elif [ "$ram" -lt 10 ]; then melde WARNUNG arbeitsspeicher "nur $ram % verfügbar"
  else melde OK arbeitsspeicher "$ram % verfügbar"; fi
}

pruefe_sicherung() {   # pruefe_sicherung <art> <höchstalter in Stunden>
  local f="$STATUS_DIR/$1.json" epoch ergebnis
  if [ ! -f "$f" ]; then melde FEHLER "$1" "noch nie gelaufen (deploy/hq $([ "$1" = backup ] && echo backup || echo backup-verify))"; return; fi
  epoch="$(json_wert "$f" epoch)"; ergebnis="$(json_wert "$f" ergebnis)"
  if [ "$ergebnis" != ok ]; then melde FEHLER "$1" "letzter Lauf fehlgeschlagen: $(json_wert "$f" info)"
  elif [ "$(alter_s "$epoch")" -gt $(( $2 * 3600 )) ]; then melde FEHLER "$1" "überfällig — letzter Erfolg vor $(( $(alter_s "$epoch") / 3600 )) h"
  else melde OK "$1" "vor $(( $(alter_s "$epoch") / 60 )) min: $(json_wert "$f" info)"; fi
}

check() {
  local alarm="${1:-}" vorher="$STATUS_DIR/check.state" jetzt="$TMP/probleme" url
  : > "$jetzt"
  pruefe_dienste
  pruefe_https
  pruefe_hintergrund
  pruefe_ressourcen
  pruefe_sicherung backup "$(cfg HQ_BACKUP_MAX_AGE_HOURS 26)"
  pruefe_sicherung verify 200
  if extern; then melde OK sicherungsziel "extern: $(repo)"; else melde WARNUNG sicherungsziel "nicht extern ($(repo))"; fi
  if [ "$alarm" = --alert ]; then
    mkdir -p "$STATUS_DIR"; touch "$vorher"
    local neu behoben
    neu="$(cut -d'|' -f1,2 "$jetzt" | sort | comm -23 - <(cut -d'|' -f1,2 "$vorher" | sort))"
    behoben="$(cut -d'|' -f2 "$vorher" | sort -u | comm -23 - <(cut -d'|' -f2 "$jetzt" | sort -u))"
    if [ -s "$jetzt" ]; then   # neu ⇒ sofort; bestehend ⇒ einmal täglich (Dedup über das Datum)
      warnen "$(wc -l < "$jetzt") Problem(e) auf $(env_wert ICHQ_DOMAIN)" "$(tr '|' ' ' < "$jetzt" | tr '\n' ';')" \
        "check-$( [ -n "$neu" ] && echo "neu-$(echo "$neu" | md5sum | cut -c1-12)" || echo taeglich)-$(date +%F)"
    fi
    [ -z "$behoben" ] || warnen "Entwarnung auf $(env_wert ICHQ_DOMAIN)" "behoben: $(echo "$behoben" | tr '\n' ' ')" \
      "check-ok-$(echo "$behoben" | md5sum | cut -c1-12)-$(date +%F-%H)"
    cp "$jetzt" "$vorher"
  fi
  url="$(cfg HQ_HEARTBEAT_URL "")"
  if [ "$PRUEF_FEHLER" -eq 0 ] && [ -n "$url" ]; then
    curl -fsS -m 10 --retry 2 -o /dev/null "$url" || echo "WARNUNG: Totmannschalter $url nicht erreichbar" >&2
  fi
  return "$PRUEF_FEHLER"
}
