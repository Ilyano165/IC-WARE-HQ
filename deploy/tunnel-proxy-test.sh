#!/usr/bin/env bash
# Prüft Caddyfile.tunnel ECHT (ADR-018): Caddy-Container + Echo-Upstream + Gegenstellen mit festen Adressen.
#   1. cloudflared-Adresse (172.31.250.10 bzw. im Prüfnetz .251.10) mit Cf-Connecting-Ip → App sieht genau diese Besucher-IP
#   2. jede andere Adresse mit gefälschtem Cf-Connecting-Ip/X-Forwarded-For → App sieht die echte Gegenstelle
#   3. Besucher kam per http:// bei Cloudflare an → 308 auf https://
#   4. fremder Host-Name → nichts wird weitergereicht
# Braucht Docker und die Images caddy:2-alpine + ic-ware-hq:local (nach deploy/install.sh vorhanden). Kein Netz nötig.
# Eigenes Prüfnetz 172.31.251.0/28 (das echte Netz „tunnel" kann schon bestehen): in einer Kopie des Caddyfile wird
# NUR das Präfix 172.31.250. → 172.31.251. ersetzt; die geprüfte Logik ist dieselbe.
set -euo pipefail
DEPLOY="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
N="ichq-tunneltest-$$"
T="$(mktemp -d)"
aufraeumen() { docker rm -f "$N-echo" "$N-caddy" >/dev/null 2>&1 || true; docker network rm "$N" >/dev/null 2>&1 || true
               rm -rf "$T"; }
trap aufraeumen EXIT
cat > "$T/echo.py" <<'PY'
import http.server, json
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        b = json.dumps({"xff": self.headers.get("X-Forwarded-For"), "proto": self.headers.get("X-Forwarded-Proto")}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
PY
sed 's/172\.31\.250\./172.31.251./g' "$DEPLOY/Caddyfile.tunnel" > "$T/Caddyfile"
chmod 644 "$T/echo.py" "$T/Caddyfile"
docker network create --subnet 172.31.251.0/28 "$N" >/dev/null
docker run -d --name "$N-echo" --network "$N" --ip 172.31.251.5 -v "$T/echo.py:/e.py:ro" --entrypoint python \
  ic-ware-hq:local /e.py >/dev/null
docker run -d --name "$N-caddy" --network "$N" --ip 172.31.251.2 -e ICHQ_DOMAIN=hq.beispiel.de \
  -e "ICHQ_UPSTREAM=$N-echo:8000" -v "$T/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2-alpine >/dev/null

anfrage() {   # anfrage <quell-ip> <host> <kopf|kopf…> → Antworttext oder „HTTP <code> <Location>"
  docker run --rm --network "$N" --ip "$1" --entrypoint python ic-ware-hq:local -c '
import sys, urllib.request as u
k = dict(h.split(": ", 1) for h in sys.argv[3].split("|") if h); k["Host"] = sys.argv[2]
class N(u.HTTPRedirectHandler):
    def redirect_request(s, *a, **kw): return None
try: print(u.build_opener(N).open(u.Request(sys.argv[1], headers=k), timeout=5).read().decode())
except Exception as e: print("HTTP", getattr(e, "code", e), getattr(e, "headers", {}).get("Location"))
' "http://$N-caddy/x" "$2" "$3"
}
OK=0
pruefe() { if [[ "$2" == *"$3"* ]]; then OK=$((OK + 1)); echo "  ok   $1"; else echo "  FEHLT $1: $2" >&2; exit 1; fi; }
for _ in $(seq 1 30); do
  [[ "$(anfrage 172.31.251.10 hq.beispiel.de 'Cf-Connecting-Ip: 203.0.113.7')" == *xff* ]] && break; sleep 1
done
pruefe "Tunnel: Besucher-IP aus Cf-Connecting-Ip, gefälschtes X-Forwarded-For verworfen" \
  "$(anfrage 172.31.251.10 hq.beispiel.de 'Cf-Connecting-Ip: 203.0.113.7|X-Forwarded-For: 6.6.6.6, 203.0.113.7|X-Forwarded-Proto: https')" \
  '"xff": "203.0.113.7", "proto": "https"'
pruefe "anderer Container: gefälschte Köpfe wirkungslos" \
  "$(anfrage 172.31.251.11 hq.beispiel.de 'Cf-Connecting-Ip: 6.6.6.6|X-Forwarded-For: 6.6.6.6')" '"xff": "172.31.251.11"'
pruefe "http:// bei Cloudflare → 308 auf https://" \
  "$(anfrage 172.31.251.10 hq.beispiel.de 'Cf-Connecting-Ip: 203.0.113.7|X-Forwarded-Proto: http')" "HTTP 308 https://hq.beispiel.de/x"
antwort="$(anfrage 172.31.251.10 andere.example 'Cf-Connecting-Ip: 203.0.113.7')"
pruefe "fremder Host-Name wird nicht weitergereicht" "[$antwort]" "[]"
echo "== Tunnel-Proxy: $OK Prüfungen bestanden"
