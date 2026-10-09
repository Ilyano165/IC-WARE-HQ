# shellcheck shell=bash
# IC WARE HQ — Diagnose der öffentlichen Erreichbarkeit `deploy/hq diagnose` (ADR-017). Eingebunden von deploy/hq
# (nutzt melde/compose/env_wert/https_pruefen) und von deploy/install.sh (nur dns_* — vor dem ersten Start).
#
# Beantwortet die Frage „Warum ist https://<domain> nicht erreichbar?" in verständlichen Sätzen: DNS (A und AAAA —
# ein veralteter AAAA-Eintrag lässt Let's Encrypt scheitern, obwohl der A-Eintrag stimmt), Ports, Firewall,
# Weiterleitung HTTP→HTTPS, Zertifikat (Aussteller, Laufzeit), ACME-Fehler aus dem Caddy-Log, versehentlich
# veröffentlichte interne Dienste. Von außen prüfen kann ein Server sich nicht selbst — dafür nennt sie den Befehl.

dns_aufloesen() {   # dns_aufloesen <domain> → je Zeile eine Adresse (A und AAAA, ohne IPv4-gemappte)
  getent ahosts "$1" 2>/dev/null | awk '{print $1}' | grep -vi '^::ffff:' | sort -u || true
}

dns_eigene() {      # Adressen dieses Servers: Schnittstellen + öffentliche Sicht (hinter 1:1-NAT bei Cloud-Anbietern)
  { ip -o addr show 2>/dev/null | awk '{sub(/\/.*/, "", $4); print $4}'
    curl -4 -fsS --max-time 5 https://api.ipify.org 2>/dev/null; echo
    curl -6 -fsS --max-time 5 https://api64.ipify.org 2>/dev/null; echo
  } | grep -v '^$' | sort -u
}

dns_vergleich() {   # dns_vergleich <domain> <aufgelöst> <eigene> → Zeilen „STUFE|dns|Text"; Rückgabe 1 bei Fehler
  local domain="$1" aufgeloest="$2" eigene="$3" a typ fremd=0 passend=0 v4
  v4="$(echo "$eigene" | grep -v ':' | grep -Ev '^(127\.|10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)' | head -1)"
  if [ -z "$aufgeloest" ]; then
    echo "FEHLER|dns|$domain löst nicht auf. Beim Domain-Anbieter einen A-Eintrag anlegen: $domain → ${v4:-<öffentliche IPv4 dieses Servers>}"
    return 1
  fi
  for a in $aufgeloest; do
    case "$a" in *:*) typ=AAAA ;; *) typ=A ;; esac
    if echo "$eigene" | grep -qxF "$a"; then
      passend=1; echo "OK|dns|$typ-Eintrag $a zeigt auf diesen Server"
    elif [ "$typ" = AAAA ]; then
      fremd=1; echo "FEHLER|dns|AAAA-Eintrag $a gehört nicht zu diesem Server. Let's Encrypt prüft bevorzugt über IPv6 — den AAAA-Eintrag löschen oder auf die IPv6 dieses Servers ändern"
    else
      fremd=1; echo "FEHLER|dns|A-Eintrag $a gehört nicht zu diesem Server${v4:+ (dieser Server: $v4)} — A-Eintrag ändern"
    fi
  done
  [ "$passend" -eq 1 ] && [ "$fremd" -eq 0 ]
}

dns_pruefen() {     # dns_pruefen <domain> — für install.sh: Fehler ausgeben, Rückgabe 1 bei Fehler
  local zeilen rc=0
  zeilen="$(dns_vergleich "$1" "$(dns_aufloesen "$1")" "$(dns_eigene)")" || rc=1
  echo "$zeilen" | while IFS='|' read -r stufe _ text; do printf '   %-7s %s\n' "$stufe" "$text"; done
  [ "$rc" -eq 0 ] || echo "   Hinweis: DNS-Änderungen brauchen je nach Anbieter Minuten bis Stunden (TTL)." >&2
  return "$rc"
}

acme_deuten() {     # Caddy-Log (stdin) → verständliche Ursache je bekanntem ACME-Fehlertyp (RFC 8555, Abschnitt 6.7)
  local log; log="$(cat)"
  _hat() { grep -q "$1" <<< "$log"; }
  _hat 'acme:error:dns' && echo "Let's Encrypt findet keinen DNS-Eintrag für die Domain (A/AAAA fehlt oder noch nicht verteilt)."
  _hat 'acme:error:connection' && echo "Let's Encrypt erreicht den Server nicht auf Port 80/443 — Firewall des Anbieters (Cloud-Firewall/Security Group), ufw oder falscher A/AAAA-Eintrag."
  _hat 'acme:error:unauthorized' && echo "Let's Encrypt erreicht einen ANDEREN Server unter der Domain (falscher A/AAAA-Eintrag, Proxy/CDN davor?)."
  _hat 'acme:error:caa' && echo "Ein CAA-Eintrag der Domain verbietet Let's Encrypt — CAA um letsencrypt.org ergänzen oder entfernen."
  _hat 'acme:error:rateLimited' && echo "Let's-Encrypt-Limit erreicht (zu viele Versuche) — Ursache beheben und später erneut (Caddy wiederholt selbst)."
  _hat 'acme:error:tls' && echo "TLS-Prüfung durch Let's Encrypt scheiterte — Port 443 nicht frei durchgereicht (Proxy/Load-Balancer davor?)."
  return 0
}

diagnose() {
  local domain origin code ort aus zert
  domain="$(env_wert ICHQ_DOMAIN)"
  echo "Diagnose für https://$domain"
  melde OK konfiguration "Domain $domain, Anmeldungen nur über https://$domain (Cookies Secure, Origin-Prüfung)"
  origin="$(compose exec -T app printenv ICHQ_PUBLIC_ORIGIN 2>/dev/null | tr -d '\r' || true)"
  if [ -z "$origin" ]; then melde WARNUNG origin "App läuft nicht — Origin nicht prüfbar (deploy/hq start)"
  elif [ "$origin" = "https://$domain" ]; then melde OK origin "App erwartet https://$domain"
  else melde FEHLER origin "App erwartet $origin statt https://$domain — deploy/hq restart"; fi

  if [ "$domain" = localhost ]; then melde OK dns "localhost — keine öffentliche Domain (Testbetrieb)"
  else
    while IFS='|' read -r stufe name text; do melde "$stufe" "$name" "$text"; done \
      < <(dns_vergleich "$domain" "$(dns_aufloesen "$domain")" "$(dns_eigene)" || true)
  fi

  if command -v ss >/dev/null; then
    for p in 80 443; do
      if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -qE ":$p\$"; then melde OK "port-$p" "lauscht"
      else melde FEHLER "port-$p" "niemand lauscht auf Port $p — läuft Caddy? (deploy/hq status)"; fi
    done
  fi
  if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q '^Status: active'; then
    for p in 80 443; do
      if ufw status 2>/dev/null | grep -qE "^$p(/tcp)?[[:space:]]+ALLOW"; then melde OK "firewall-$p" "ufw erlaubt $p"
      else melde FEHLER "firewall-$p" "ufw blockiert $p — sudo ufw allow $p/tcp"; fi
    done
  else melde OK firewall "keine aktive ufw — Cloud-Firewall des Anbieters muss 80/443 erlauben (hier nicht sichtbar)"; fi

  # Nur Caddy darf Ports veröffentlichen — PostgreSQL, App, ClamAV nie (auch nicht versehentlich per Override)
  aus="$(docker ps --filter label=com.docker.compose.project=ichq --format '{{.Label "com.docker.compose.service"}} {{.Ports}}' \
    | awk '$1 != "caddy" && $0 ~ /->/ {print $1}' | tr '\n' ' ')"
  if [ -n "$aus" ]; then melde FEHLER intern "von außen erreichbar, obwohl intern: $aus"
  else melde OK intern "nur Caddy veröffentlicht Ports (Datenbank, App, Virenscanner intern)"; fi

  code="$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' --max-time 10 --resolve "$domain:80:127.0.0.1" \
    "http://$domain/app/" || true)"
  case "$code" in
    30[178]\ https://*) melde OK weiterleitung "http:// → https:// ($code)" ;;
    *) melde FEHLER weiterleitung "http://$domain leitet nicht auf HTTPS weiter (Antwort: ${code:-keine})" ;;
  esac

  zert="$(echo | openssl s_client -connect 127.0.0.1:443 -servername "$domain" 2>/dev/null \
    | openssl x509 -noout -issuer -enddate 2>/dev/null | tr '\n' ' ' || true)"
  if [ -z "$zert" ]; then melde FEHLER zertifikat "kein Zertifikat für $domain ausgeliefert"
  elif [ "$domain" != localhost ] && grep -qi 'Caddy Local Authority' <<< "$zert"; then
    melde FEHLER zertifikat "nur ein internes Notzertifikat — Let's Encrypt hat (noch) nicht ausgestellt: $zert"
  else melde OK zertifikat "$zert"; fi
  ort="$(compose logs --no-color --tail 400 caddy 2>/dev/null | acme_deuten)"
  if [ -n "$ort" ]; then while IFS= read -r z; do melde FEHLER acme "$z"; done <<< "$ort"
  else melde OK acme "keine Zertifikatsfehler im Caddy-Log (letzte 400 Zeilen)"; fi

  if https_pruefen; then melde OK https "https://$domain/readiness antwortet (lokal geprüft)"
  else melde FEHLER https "https://$domain antwortet nicht"; fi
  echo
  echo "Von einem ANDEREN Netz prüfen (z. B. Handy ohne WLAN, oder: curl -sI https://$domain/health)."
  echo "Erst das beweist, dass die Adresse für alle Nutzer erreichbar ist."
  return "$PRUEF_FEHLER"
}
