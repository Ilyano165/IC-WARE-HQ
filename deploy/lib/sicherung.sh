# shellcheck shell=bash
# IC WARE HQ — Sicherung und Wiederherstellung mit restic (ADR-016). Wird von deploy/hq eingebunden.
#
# Konfiguration (deploy/.env, Standardwerte in Klammern):
#   HQ_BACKUP_REPOSITORY   Ziel. Extern, z. B. s3:https://s3.eu-central-1.amazonaws.com/<bucket>/ichq
#                          (ohne Angabe: /var/backups/ichq/restic — verschlüsselt, aber AUF DIESEM SERVER)
#   HQ_BACKUP_KEY_FILE     Schlüssel des Repositorys (/etc/ichq/backup.key) — liegt NIE in der Sicherung
#   HQ_BACKUP_S3_ENV       S3-Zugang als AWS_ACCESS_KEY_ID=…/AWS_SECRET_ACCESS_KEY=… (/etc/ichq/backup-s3.env)
#   HQ_BACKUP_KEEP_DAILY / _WEEKLY / _MONTHLY   Aufbewahrung (7 / 5 / 12)
#   HQ_BACKUP_MAX_AGE_HOURS   ab wann eine Sicherung als überfällig gilt (26)
# Inhalt jeder Sicherung: /sicherung/meta (db.dump, secrets.tar, env, manifest.json) + /sicherung/storage (Dateien).

BACKUP_IMAGE="ic-ware-hq-backup:local"
STATUS_DIR="${HQ_STATUS_DIR:-/var/lib/ichq}"
RESTIC_HOST="ichq-hq"

cfg() { local v="${!1:-}"; [ -n "$v" ] || v="$(env_wert "$1")"; printf '%s' "${v:-$2}"; }
repo() { cfg HQ_BACKUP_REPOSITORY /var/backups/ichq/restic; }
schluessel() { cfg HQ_BACKUP_KEY_FILE /etc/ichq/backup.key; }
s3_env() { cfg HQ_BACKUP_S3_ENV /etc/ichq/backup-s3.env; }
extern() { case "$(repo)" in s3:*|b2:*|azure:*|gs:*|sftp:*|rest:*) return 0 ;; *) return 1 ;; esac; }

restic_lauf() {   # restic_lauf [docker-run-optionen…] -- <restic-argumente…>
  local opts=() r k
  while [ "$1" != "--" ]; do opts+=("$1"); shift; done; shift
  r="$(repo)"; k="$(schluessel)"
  [ -s "$k" ] || fehler "Sicherungsschlüssel fehlt ($k) — deploy/hq backup-init"
  case "$r" in /*) mkdir -p "$r" && chmod 700 "$r"; opts+=(-v "$r:$r") ;; esac
  [ -f "$(s3_env)" ] && opts+=(--env-file "$(s3_env)")
  docker run --rm -i --network host -e "RESTIC_REPOSITORY=$r" -e RESTIC_PASSWORD_FILE=/run/backup.key \
    -e RESTIC_CACHE_DIR=/cache -v ichq_restic_cache:/cache -v "$k:/run/backup.key:ro" "${opts[@]}" \
    "$BACKUP_IMAGE" restic "$@"
}

status_schreiben() {   # status_schreiben <art> <ok|fehler> <text>
  mkdir -p "$STATUS_DIR" && chmod 755 "$STATUS_DIR"
  printf '{"zeit":"%s","epoch":%s,"ergebnis":"%s","info":"%s"}\n' "$(date -u +%FT%TZ)" "$(date +%s)" "$2" \
    "$(printf '%s' "$3" | tr -d '"\\\n' | cut -c1-300)" > "$STATUS_DIR/$1.json.neu"
  mv "$STATUS_DIR/$1.json.neu" "$STATUS_DIR/$1.json"
}

warnen() {   # warnen <betreff> <nachricht> <dedup> — per E-Mail an ICHQ_ALERT_EMAIL (Outbox, sonst direkt SMTP)
  echo "WARNUNG: $1 — $2" >&2
  compose exec -T app ichq alert --subject "$1" --message "$2" --dedup "$3" >/dev/null 2>&1 \
    || compose run --rm --no-deps -T app ichq alert --subject "$1" --message "$2" --dedup "$3" >/dev/null 2>&1 \
    || echo "WARNUNG: Alarm-Mail nicht zustellbar (ICHQ_ALERT_EMAIL/SMTP prüfen)" >&2
}

backup_init() {
  local k s; k="$(schluessel)"; s="$(s3_env)"
  install -d -m 700 "$(dirname "$k")"
  if [ -s "$k" ]; then info "Sicherungsschlüssel vorhanden: $k (bleibt unverändert)"
  else
    (umask 077; head -c 48 /dev/urandom | base64 | tr -d '\n=' > "$k")
    cat <<EOF
==> NEUER SICHERUNGSSCHLÜSSEL ($k):

    $(cat "$k")

    JETZT getrennt vom Server aufbewahren (Passwortmanager/Tresor). Ohne diesen Schlüssel ist KEINE
    Sicherung lesbar — auch nicht durch IC Ware. Er liegt absichtlich nicht in der Sicherung selbst.
EOF
  fi
  if extern && [ ! -f "$s" ]; then
    (umask 077; printf 'AWS_ACCESS_KEY_ID=\nAWS_SECRET_ACCESS_KEY=\nAWS_DEFAULT_REGION=eu-central-1\n' > "$s")
    info "S3-Zugang eintragen: $s (Modus 600)"
  fi
  extern || echo "WARNUNG: HQ_BACKUP_REPOSITORY nicht gesetzt — Sicherungen liegen verschlüsselt auf DIESEM Server." >&2
}

repo_bereit() {   # anlegen NUR, wenn es das Repository nachweislich nicht gibt — nie bei falschem Schlüssel/Netzfehler
  local aus
  aus="$(restic_lauf -- cat config 2>&1 >/dev/null)" && return 0
  case "$aus" in
    *"does not exist"*|*"is there a repository"*) info "Repository anlegen: $(repo)"; restic_lauf -- init ;;
    *"wrong password"*) fehler "Sicherungsschlüssel passt nicht zum Repository $(repo) — richtigen Schlüssel nach $(schluessel)" ;;
    *) fehler "Repository nicht erreichbar: $(echo "$aus" | tail -1)" ;;
  esac
}

manifest() {   # manifest <meta-ordner>
  local m="$1" migration dateien
  migration="$(compose exec -T postgres psql -U postgres -d ichq -tAc 'SELECT version_num FROM alembic_version')"
  dateien="$(compose run --rm --no-deps -T -u 0 --entrypoint sh app -c \
    'find /var/lib/ichq/storage -type f ! -path "*/_health/*" | wc -l; find /var/lib/ichq/storage -type f ! -path "*/_health/*" -exec cat {} + | wc -c' \
    2>/dev/null | tr '\n' ' ')"
  printf '{"erstellt":"%s","git":"%s","migration":"%s","db_sha256":"%s","secrets_sha256":"%s","dateien":%s,"bytes":%s}\n' \
    "$(date -u +%FT%TZ)" "$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unbekannt)" "$migration" \
    "$(sha256sum "$m/db.dump" | cut -d' ' -f1)" "$(sha256sum "$m/secrets.tar" | cut -d' ' -f1)" \
    "$(echo "$dateien" | awk '{print $1}')" "$(echo "$dateien" | awk '{print $2}')" > "$m/manifest.json"
}

backup_kern() {
  local m="$TMP/meta"; umask 077; mkdir -m 700 "$m"
  repo_bereit
  info "Datenbank sichern (pg_dump) und lesbar prüfen"
  compose exec -T postgres pg_dump -U postgres -Fc ichq > "$m/db.dump"
  compose exec -T postgres pg_restore --list < "$m/db.dump" > /dev/null
  tar -C "$ROOT" -cf "$m/secrets.tar" secrets
  cp "$ENVFILE" "$m/env"
  manifest "$m"
  # Dateien NACH der Datenbank: Speicherschlüssel sind versioniert, nie überschrieben — jede referenzierte Datei ist dabei
  info "Verschlüsselt sichern nach $(repo)"
  restic_lauf -v "$m:/sicherung/meta:ro" -v ichq_filedata:/sicherung/storage:ro -- \
    backup /sicherung --host "$RESTIC_HOST" --tag ichq --exclude /sicherung/storage/_health --quiet
  info "Aufbewahrung anwenden"
  restic_lauf -- forget --host "$RESTIC_HOST" --tag ichq --prune --quiet \
    --keep-daily "$(cfg HQ_BACKUP_KEEP_DAILY 7)" --keep-weekly "$(cfg HQ_BACKUP_KEEP_WEEKLY 5)" \
    --keep-monthly "$(cfg HQ_BACKUP_KEEP_MONTHLY 12)"
  info "Repository prüfen (Struktur)"
  restic_lauf -- check --quiet
}

streng() {   # streng <funktion>: in einem EIGENEN hq-Prozess ausführen. Bash ignoriert set -e in Funktionen, die
  # in if/&&/||-Zusammenhang laufen — auch in Subshells. Nur ein neuer Prozess bricht beim ersten Fehler sicher ab.
  local rc=0
  AUSGABE="$("$HQ_SELF" "__$1" 2>&1)" || rc=$?
  return "$rc"
}

backup() {
  local snap
  if streng backup_kern; then
    local ausgabe="$AUSGABE"
    echo "$ausgabe"
    snap="$(restic_lauf -- snapshots latest --host "$RESTIC_HOST" --compact 2>/dev/null | awk 'NR==3{print $1}')"
    status_schreiben backup ok "Snapshot $snap in $(repo)"
    info "Sicherung ok (Snapshot $snap)$(extern || echo ' — ACHTUNG: nicht extern')"
  else
    local ausgabe="$AUSGABE"
    echo "$ausgabe" >&2
    status_schreiben backup fehler "$(echo "$ausgabe" | tail -1)"
    warnen "Sicherung fehlgeschlagen" "$(echo "$ausgabe" | tail -3 | tr '\n' ' ')" "backup-$(date +%F)"
    fehler "Sicherung fehlgeschlagen"
  fi
}

secrets_pruefen() {   # nur secrets/ und reguläre Dateien secrets/<name> — kein Pfad nach draußen, keine Links
  tar -tvf "$1" | awk '{print substr($1,1,1), $NF}' | while read -r typ pfad; do
    case "$typ:$pfad" in d:secrets/|d:secrets) ;; -:secrets/*)
      [[ "${pfad#secrets/}" =~ ^[a-z_]+$ ]] || fehler "unerwarteter Eintrag in secrets.tar: $pfad" ;;
      *) fehler "unerwarteter Eintrag in secrets.tar: $typ $pfad" ;; esac
  done
}

meta_holen() {   # meta_holen <snapshot> <ziel> — holt und prüft die Metadaten (Prüfsummen)
  local snap="$1" z="$2"
  mkdir -p "$z" && chmod 700 "$z"
  restic_lauf -v "$z:/ziel" -- restore "$snap" --host "$RESTIC_HOST" --target /ziel --include /sicherung/meta --quiet
  local m="$z/sicherung/meta"
  for f in db.dump secrets.tar manifest.json; do [ -s "$m/$f" ] || fehler "Sicherung unvollständig: $f fehlt"; done
  [ "$(sha256sum "$m/db.dump" | cut -d' ' -f1)" = "$(json_wert "$m/manifest.json" db_sha256)" ] \
    || fehler "Prüfsumme db.dump stimmt nicht"
  [ "$(sha256sum "$m/secrets.tar" | cut -d' ' -f1)" = "$(json_wert "$m/manifest.json" secrets_sha256)" ] \
    || fehler "Prüfsumme secrets.tar stimmt nicht"
  secrets_pruefen "$m/secrets.tar"
}

json_wert() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"; }

restore() {
  local snap="${1:-latest}" ja="${2:-}" m
  [ "$snap" = "--yes" ] && { ja="--yes"; snap=latest; }
  [ "$ja" = "--yes" ] || fehler "Überschreibt Datenbank, Dateien und Geheimnisse. Zum Bestätigen: deploy/hq restore [snapshot] --yes"
  meta_holen "$snap" "$TMP/r"; m="$TMP/r/sicherung/meta"
  info "Sicherung: $(cat "$m/manifest.json")"
  info "Dienste anhalten"
  compose stop caddy app worker jobs scanner >/dev/null 2>&1 || true
  info "Geheimnisse aus der Sicherung übernehmen"
  if [ -d "$ROOT/secrets" ]; then mv "$ROOT/secrets" "$ROOT/secrets.vor-restore-$(date -u +%Y%m%d-%H%M%S)"; fi
  tar -C "$ROOT" --no-same-owner -xf "$m/secrets.tar"
  "$DEPLOY/fix-secret-permissions.sh"
  info "Datenbank neu anlegen und einspielen"
  compose up -d --force-recreate postgres   # neu erzeugen: bindet die wiederhergestellten Secret-Dateien ein
  for _ in $(seq 1 60); do compose exec -T postgres pg_isready -U postgres >/dev/null 2>&1 && break; sleep 2; done
  # Superuser-Passwort stammt von der Erstinstallation des Clusters — an das wiederhergestellte Secret angleichen.
  # Lokaler Socket (trust im Container); das Passwort liest psql im Container, es steht in keiner Befehlszeile.
  compose exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 -q <<'SQL'
\set pw `cat /run/secrets/pg_admin_password`
ALTER ROLE postgres PASSWORD :'pw';
DROP DATABASE IF EXISTS ichq WITH (FORCE);
SQL
  compose run --rm -T db-init >/dev/null   # Datenbank + Rollen, Passwörter aus den (wiederhergestellten) Secrets
  compose exec -T postgres pg_restore -U postgres -d ichq --exit-on-error < "$m/db.dump"
  info "Dateien einspielen"
  compose run --rm --no-deps -T -u 0 --entrypoint sh app -c 'find /var/lib/ichq/storage -mindepth 1 -delete'
  restic_lauf -v ichq_filedata:/sicherung/storage -- restore "$snap" --host "$RESTIC_HOST" --target / \
    --include /sicherung/storage --quiet
  starten
  info "Wiederherstellung abgeschlossen."
}

backup_verify() {   # Wiederherstellungstest in Wegwerf-Umgebung: Prüfsummen, Daten-Stichprobe, jede Datei vorhanden
  if streng verify_kern; then
    echo "$AUSGABE"; status_schreiben verify ok "$(echo "$AUSGABE" | tail -1)"
  else
    echo "$AUSGABE" >&2; status_schreiben verify fehler "$(echo "$AUSGABE" | tail -1)"
    warnen "Wiederherstellungstest fehlgeschlagen" "$(echo "$AUSGABE" | tail -3 | tr '\n' ' ')" "verify-$(date +%F)"
    fehler "Wiederherstellungstest fehlgeschlagen"
  fi
}

verify_kern() {
  local z="$TMP/v" m pg="ichq-restore-probe-$$" pw fehlt
  info "Daten-Stichprobe des Repositorys lesen (restic check --read-data-subset)"
  restic_lauf -- check --read-data-subset "$(cfg HQ_BACKUP_VERIFY_SUBSET 10%)" --quiet
  meta_holen latest "$z"; m="$z/sicherung/meta"
  restic_lauf -v "$z:/ziel" -- restore latest --host "$RESTIC_HOST" --target /ziel --include /sicherung/storage --quiet
  local n bytes
  n="$(find "$z/sicherung/storage" -type f 2>/dev/null | wc -l)"
  bytes="$(find "$z/sicherung/storage" -type f -exec cat {} + 2>/dev/null | wc -c)"
  [ "$n" = "$(json_wert "$m/manifest.json" dateien)" ] || fehler "Dateizahl $n ≠ Manifest"
  [ "$bytes" = "$(json_wert "$m/manifest.json" bytes)" ] || fehler "Dateigröße $bytes ≠ Manifest"
  info "Datenbank in Wegwerf-PostgreSQL einspielen (ohne Netz)"
  pw="$(head -c 24 /dev/urandom | base64 | tr -d '/+=')"
  docker run -d --rm --name "$pg" --network none -e POSTGRES_PASSWORD="$pw" -v "$m:/meta:ro" "$BACKUP_IMAGE" \
    docker-entrypoint.sh postgres >/dev/null
  trap 'docker rm -f "$pg" >/dev/null 2>&1 || true' RETURN
  for _ in $(seq 1 60); do docker exec "$pg" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
  sleep 2; docker exec "$pg" pg_isready -U postgres >/dev/null
  # Rollen wie in Produktion (ohne Anmeldung) — dann originalgetreu einspielen: Besitzer, Rechte, RLS-Policies
  docker exec "$pg" psql -U postgres -v ON_ERROR_STOP=1 -qc "CREATE ROLE ichq_owner NOLOGIN; CREATE ROLE ichq_app NOLOGIN;
    CREATE ROLE ichq_platform NOLOGIN; CREATE ROLE ichq_worker NOLOGIN; CREATE ROLE ichq_auth NOLOGIN;"
  docker exec "$pg" createdb -U postgres -O ichq_owner probe
  docker exec "$pg" pg_restore -U postgres -d probe --exit-on-error /meta/db.dump
  docker exec "$pg" psql -U postgres -d probe -tAc "SELECT storage_key FROM documents" > "$z/schluessel"
  fehlt=0
  while read -r k; do [ -z "$k" ] || [ -f "$z/sicherung/storage/$k" ] || { echo "fehlt: $k" >&2; fehlt=$((fehlt + 1)); }; done < "$z/schluessel"
  [ "$fehlt" -eq 0 ] || fehler "$fehlt Dokument-Dateien fehlen in der Sicherung"
  info "Wiederherstellungstest ok: $(docker exec "$pg" psql -U postgres -d probe -tAc \
    "SELECT format('%s Firmen, %s Konten, %s Dokumente', (SELECT count(*) FROM tenants), (SELECT count(*) FROM users), (SELECT count(*) FROM documents))"), $n Dateien geprüft"
}

backup_status() {
  local f
  for f in backup verify; do
    if [ -f "$STATUS_DIR/$f.json" ]; then echo "$f: $(cat "$STATUS_DIR/$f.json")"; else echo "$f: noch nie gelaufen"; fi
  done
  echo "Ziel: $(repo)$(extern || echo '  (ACHTUNG: nicht extern)')"
  restic_lauf -- snapshots --host "$RESTIC_HOST" --compact 2>/dev/null | tail -n 8 || echo "Repository nicht erreichbar"
}
