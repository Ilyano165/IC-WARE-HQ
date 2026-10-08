#!/bin/bash
# Mutationstests: baut gezielt Sicherheitslücken ein und prüft, ob die Tests sie finden.
# Ein grüner Test, der eine eingebaute Lücke nicht bemerkt, ist wertlos.
# Aufruf aus dem Projektordner, mit ICHQ_TEST_ADMIN_URL gesetzt:  scripts/mutation-check.sh
set -u
ERKANNT=0; UNBEMERKT=0; UNGUELTIG=0
mutation() {
  local name="$1" datei="$2" ersatz="$3" tests="$4"
  local tmp; tmp=$(mktemp -d)
  cp -r src "$tmp/src"
  if ! python3 - "$tmp/src/ichq/$datei" "$ersatz" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1]); alt, neu = sys.argv[2].split("|||")
t = p.read_text()
if alt not in t:
    sys.exit(3)
p.write_text(t.replace(alt, neu, 1))
PY
  then echo "UNGÜLTIG  | $name (Muster nicht gefunden — Mutation nicht angewendet)"; UNGUELTIG=$((UNGUELTIG+1)); rm -rf "$tmp"; return; fi
  local ergebnis; ergebnis=$(PYTHONPATH="$tmp/src" timeout 300 python3 -m pytest -q -p no:cacheprovider $tests 2>&1 | tail -1)
  if echo "$ergebnis" | grep -q "failed"; then echo "ERKANNT   | $name"; ERKANNT=$((ERKANNT+1))
  else echo "UNBEMERKT | $name | $ergebnis"; UNBEMERKT=$((UNBEMERKT+1)); fi
  rm -rf "$tmp"
}
mutation "RLS-Schreibschutz entfernt" "migrations/versions/0001_foundation.py" "                       WITH CHECK (tenant_id = ichq_current_tenant())\"\"\")|||                       WITH CHECK (true)\"\"\")" "tests/test_isolation.py"
mutation "Mandant per Sitzung statt Transaktion" "db/session.py" "set_config('app.tenant_id', :t, true)|||set_config('app.tenant_id', :t, false)" "tests/test_db.py"
mutation "Mandantenwächter abgeschaltet" "db/session.py" "    if not state.session.info.get(\"tenant_id\"):|||    if False:" "tests/test_db.py"
mutation "Entscheidung immer ja" "authz/service.py" "    return permission in principal.permissions|||    return True" "tests/test_authz.py"
mutation "Unbekannte Rechte erlaubt" "authz/service.py" "    if principal is None or not is_known(permission):|||    if principal is None:" "tests/test_authz.py"
mutation "Routencheck nur oberste Ebene" "api/security.py" "        elif hasattr(route, \"effective_route_contexts\"):|||        elif False:" "tests/test_authz.py"
mutation "Inaktive Firma zugelassen" "api/security.py" "    if info.status not in (\"active\", \"paused\"):|||    if False:" "tests/test_authz.py"
mutation "Stacktrace an Client" "api/middleware.py" "detail=\"Ein interner Fehler ist aufgetreten. Bitte die request_id angeben.\"|||detail=__import__('traceback').format_exc()" "tests/test_errors_logging.py"
mutation "Eingabewerte in 422" "api/errors.py" "for e in exc.errors()]|||for e in exc.errors()]; fehler.append({'input': str(exc.errors())})" "tests/test_errors_logging.py"
mutation "Onboarding-Token nicht geschwärzt" "core/logging.py" "    (re.compile(r\"(/onboard/)[A-Za-z0-9_-]{16,}\"), r\"\\1\" + GESCHWAERZT),|||" "tests/test_errors_logging.py"
mutation "Zugriffslog mit rohem Pfad" "api/middleware.py" "\"route\": getattr(route, \"path\", None) or \"unmatched\",|||\"route\": scope.get(\"path\"),\"q\": scope.get(\"query_string\", b\"\").decode()," "tests/test_errors_logging.py"
mutation "Pfad-Ausbruch im Speicher" "storage/local.py" "        pfad = (self.root / check_key(key)).resolve()|||        pfad = (self.root / key).resolve()" "tests/test_storage.py"
mutation "Outbox im falschen Mandanten" "jobs/worker.py" "            with tenant_transaction(engines.app, job.tenant_id) as s:|||            with tenant_transaction(engines.app, __import__('uuid').uuid4()) as s:" "tests/test_jobs.py"
mutation "Schwaches Secret erlaubt" "core/config.py" "        if len(roh) < MIN_SECRET_LEN:|||        if False:" "tests/test_config.py"
mutation "Leere _FILE-Variable als gesetzt" "core/config.py" " or not pfad.strip():|||:" "tests/test_config.py"
mutation "Readiness ignoriert Speicher" "api/health.py" "    bereit = all(c.ok for c in checks)|||    bereit = checks[0].ok" "tests/test_api_health.py"
mutation "Modellregistrierung fehlt in der CLI" "cli.py" "from ichq.models import assert_complete|||assert_complete = lambda: 0" "tests/test_entrypoints.py"
mutation "Worker meldet Fehlschlag als Erfolg" "cli.py" "                return 0 if r.ok else 1|||                return 0" "tests/test_entrypoints.py"
mutation "Modellprüfung prüft nichts" "models.py" "        if fk.target_fullname.split(\".\")[0] not in Base.metadata.tables|||        if False" "tests/test_entrypoints.py"

# ---------- M2 Authentication ----------
mutation "M2 Kontosperre aus" "auth/login.py" "            if fehler >= settings.login_max_failures:|||            if False:" "tests/test_auth_bruteforce.py"
mutation "M2 Drosselung aus" "auth/throttle.py" "    return bool(zeile.ip_fehler >= settings.ip_max_failures or zeile.name_fehler >= settings.identifier_max_failures)|||    return False" "tests/test_auth_bruteforce.py"
mutation "M2 Gesperrtes Konto kommt rein" "auth/login.py" "    elif u.gesperrt:|||    elif False:" "tests/test_auth_bruteforce.py"
mutation "M2 Fehlversuch nicht gespeichert" "auth/login.py" "        throttle.record_attempt(s, \"login\", subjekt, ip, False)|||        pass" "tests/test_auth_bruteforce.py"
mutation "M2 Deaktiviertes Konto kommt rein" "auth/login.py" "    elif u.status in (\"pending\", \"suspended\", \"deactivated\"):|||    elif False:" "tests/test_auth_login.py"
mutation "M2 Kein Dummy-Vergleich" "auth/passwords.py" "    ziel = stored or _dummy(settings.argon2_time_cost, settings.argon2_memory_kib, settings.argon2_parallelism)|||    if stored is None:
        return False, False
    ziel = stored" "tests/test_auth_login.py"
mutation "M2 Passwortliste aus" "auth/passwords.py" "    if klein in _haeufige() or klein.rstrip(\"0123456789!.\") in _haeufige():|||    if False:" "tests/test_auth_passwords.py"
mutation "M2 Rotation widerruft alte Sitzung nicht" "auth/sessions.py" "    revoke(s, alt.id, reason)
    return create(|||    return create(" "tests/test_auth_sessions.py"
mutation "M2 Leerlauf ignoriert" "auth/sessions.py" "\"idle_timeout\" if zeile.idle_abgelaufen and zeile.stage == \"full\" else|||\"idle_timeout\" if False else" "tests/test_auth_sessions.py"
mutation "M2 Absolute Grenze ignoriert" "auth/sessions.py" "(\"absolute_timeout\" if zeile.absolut_abgelaufen else|||(\"absolute_timeout\" if False else" "tests/test_auth_sessions.py"
mutation "M2 Kontostatus nicht je Anfrage geprüft" "auth/sessions.py" "f\"account_{zeile.status}\" if zeile.status not in (\"active\", \"locked\") else None)|||None)" "tests/test_auth_sessions.py"
mutation "M2 Logout widerruft nicht" "auth/login.py" "    sessions.revoke(s, current.id, \"logout\")|||    pass" "tests/test_auth_sessions.py"
mutation "M2 Passwortwechsel lässt andere Sitzungen leben" "auth/account.py" "    n = sessions.revoke_all(s, current.user_id, \"password_changed\", except_id=current.id)|||    n = 0" "tests/test_auth_sessions.py"
mutation "M2 Betreibersperre beendet Sitzungen nicht" "auth/account.py" "        n = sessions.revoke_all(s, user_id, f\"account_{new_status}\")|||        n = 0" "tests/test_auth_sessions.py"
mutation "M2 Reset-Token läuft nie ab" "auth/account.py" " AND r.expires_at > now() AS gueltig|||AS gueltig" "tests/test_auth_reset.py"
mutation "M2 Reset beendet Sitzungen nicht" "auth/account.py" "    n = sessions.revoke_all(s, t.user_id, \"password_reset\")|||    n = 0" "tests/test_auth_reset.py"
mutation "M2 Neuer Reset entwertet alten nicht" "auth/account.py" "    s.execute(text(\"UPDATE password_reset_tokens SET invalidated_at = now() \"
                   \"WHERE user_id = :u AND used_at IS NULL AND invalidated_at IS NULL\"), {\"u\": u.id})
    roh, h = new_token()|||    roh, h = new_token()" "tests/test_auth_reset.py"
mutation "M2 TOTP-Wiederverwendung erlaubt" "auth/totp.py" "        if last_step is not None and step <= last_step:|||        if False:" "tests/test_auth_totp.py"
mutation "M2 2FA-Versuchslimit aus" "auth/login.py" "        if versuche >= MFA_MAX_ATTEMPTS:|||        if False:" "tests/test_auth_totp.py"
mutation "M2 Zwischenschritt gilt als angemeldet" "api/security.py" "    return _sitzung_marke(\"signed_in\", (\"full\",))|||    return _sitzung_marke(\"signed_in\", (\"full\", \"mfa_pending\"))" "tests/test_auth_totp.py"
mutation "M2 Recovery-Code mehrfach nutzbar" "auth/login.py" "WHERE user_id = :u AND code_hash = :h AND used_at IS NULL RETURNING id|||WHERE user_id = :u AND code_hash = :h RETURNING id" "tests/test_auth_totp.py"
mutation "M2 Principal ohne aktive Mitgliedschaft" "api/security.py" "WHERE m.id = :m AND m.user_id = :u AND m.status = 'active' AND t.status IN ('active','paused')|||WHERE m.id = :m AND m.user_id = :u" "tests/test_auth_boundaries.py"
mutation "M2 Gesperrte Firma wählbar" "auth/login.py" "AND m.status = 'active' AND t.status IN ('active','paused')\"\"\"),|||\"\"\")," "tests/test_auth_boundaries.py"
mutation "M2 CSRF-Schutz aus" "api/origin.py" "            if h.get(\"sec-fetch-site\") == \"cross-site\" or (origin and origin.rstrip(\"/\") != erlaubt):|||            if False:" "tests/test_auth_boundaries.py"
mutation "M2 Cookie ohne HttpOnly" "api/cookies.py" "    response.set_cookie(cookie_name(settings), token, max_age=max_age, httponly=True,|||    response.set_cookie(cookie_name(settings), token, max_age=max_age, httponly=False," "tests/test_auth_login.py"
mutation "M2 Cookie in Produktion ohne Secure" "api/cookies.py" "                        secure=secure_cookies(settings), samesite=\"lax\", path=\"/\")|||                        secure=False, samesite=\"lax\", path=\"/\")" "tests/test_auth_login.py"

# ---------- C0 Core-Plattform ----------
mutation "C0 Sichtbereich ignoriert (read_all für alle)" "objects/visibility.py" "    if decide(principal, READ_ALL):
        return typ_ok|||    if True:
        return typ_ok" "tests/test_core_security.py"
mutation "C0 Modulrecht des Objekttyps ignoriert" "objects/visibility.py" "obj.type.in_(sorted(typen))|||obj.type.in_(sorted(OBJECT_TYPES))" "tests/test_core_security.py"
mutation "C0 Auflösen per ID ohne Sichtbarkeit" "objects/service.py" "where(ObjectRow.public_id == ref, visible_clause(principal))|||where(ObjectRow.public_id == ref)" "tests/test_core_security.py"
mutation "C0 RLS der Core-Tabellen ohne Mandant" "migrations/versions/0003_core.py" "                           USING (tenant_id = ichq_current_tenant())
                           WITH CHECK|||                           USING (true)
                           WITH CHECK" "tests/test_core_objects.py"
mutation "C0 Typregel für Verknüpfungen fehlt in der DB" "migrations/versions/0003_core.py" "sa.CheckConstraint(LINK_RULE, name=\"ck_object_links_rule\"),|||" "tests/test_core_objects.py"
mutation "C0 Kommentar-Bearbeitungsfenster aus" "comments/service.py" "    if jetzt is None or jetzt - c.created_at > EDIT_WINDOW:|||    if jetzt is None:" "tests/test_core_api.py"
mutation "C0 Fremde bearbeiten Kommentare" "comments/service.py" "    if c.author_membership_id != principal.membership_id:
        raise PermissionDenied(\"Nur der Autor|||    if False:
        raise PermissionDenied(\"Nur der Autor" "tests/test_core_api.py"
mutation "C0 Fremde Kommentare löschen ohne Moderation" "comments/service.py" "    if not eigener and not decide(principal, \"comments.moderate\"):|||    if False:" "tests/test_core_api.py"
mutation "C0 Zuweisen ohne tasks.assign" "tasks/service.py" "    if m.id != principal.membership_id and not decide(principal, \"tasks.assign\"):|||    if False:" "tests/test_core_api.py"
mutation "C0 Verknüpfen ohne Änderungsrecht" "relations/service.py" "    if not can_update(principal, source):|||    if False:" "tests/test_core_api.py"
mutation "C0 Zustellung ohne Objektprüfung" "notifications/service.py" "    if obj is not None and not can_see(session, empfaenger, obj.id):|||    if False:" "tests/test_core_notify_search.py"
mutation "C0 Zustellung ohne Recht der Art" "notifications/service.py" "    if kind.requires is not None and not decide(empfaenger, kind.requires):|||    if False:" "tests/test_core_notify_search.py"
mutation "C0 Benachrichtigungsliste ohne Empfängerfilter" "notifications/service.py" "    return and_(Notification.recipient_membership_id == principal.membership_id,|||    return and_(Notification.recipient_membership_id.is_not(None)," "tests/test_core_notify_search.py"
mutation "C0 Fremde Benachrichtigung als gelesen markieren" "notifications/service.py" "        Notification.public_id == ref, Notification.recipient_membership_id == principal.membership_id,|||        Notification.public_id == ref," "tests/test_core_notify_search.py"
mutation "C0 Suche ohne Sichtbarkeit" "search/service.py" "ObjectRow.search_vector.op(\"@@\")(tsq), visible_clause(principal))|||ObjectRow.search_vector.op(\"@@\")(tsq))" "tests/test_core_security.py"
mutation "C0 Pausierte Firma darf schreiben" "api/v1/common.py" "        if usable_tenant(s).status != \"active\":|||        if False:" "tests/test_core_security.py"
mutation "C0 Export mit Leserecht" "api/v1/inbox.py" "Depends(require(\"audit.export\"))|||Depends(require(\"audit.read\"))" "tests/test_core_security.py"
mutation "C0 Bezugsobjekt ohne Sichtprüfung ausgegeben" "api/v1/tasks.py" "    if t.subject_object_id is not None and can_see(s, p, t.subject_object_id):|||    if t.subject_object_id is not None:" "tests/test_core_security.py"
mutation "C0 Paginierung unbegrenzt" "db/paging.py" "    return max(1, min(int(limit), MAX_LIMIT))|||    return max(1, int(limit))" "tests/test_core_objects.py"
mutation "C0 Worker lädt Core-Handler nicht" "cli.py" "            from ichq.notifications.handlers import assert_handlers
            assert_handlers()|||            pass" "tests/test_core_e2e.py"
mutation "C0 Quarantäne-Download erlaubt" "documents/service.py" "    if doc.scan_status != \"clean\":|||    if False:" "tests/test_core_api.py"
echo "---"; echo "erkannt $ERKANNT · unbemerkt $UNBEMERKT · ungültig $UNGUELTIG"
[ "$UNBEMERKT" -eq 0 ] && [ "$UNGUELTIG" -eq 0 ]
