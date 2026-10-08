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

# ---------- M3 Mandanten / Tor 1 und C0-Nachträge ----------
mutation "M3 Pause-Schreibschutz zentral aus" "api/security.py" "    if principal.tenant_status == \"paused\" and request.method in SCHREIBEND:|||    if False:" "tests/test_m3_tenancy.py"
mutation "M3 Selbst-Deaktivierung erlaubt" "members/service.py" "    if m.id == principal.membership_id:|||    if False:" "tests/test_m3_tenancy.py"
mutation "M3 Last-Admin-Schutz aus" "authz/guard.py" "    if vorher > 0 and not admins(session):|||    if False:" "tests/test_m3_tenancy.py"
mutation "M3 Archivierte Rolle zählt als Admin" "authz/effective.py" " AND r.archived_at IS NULL|||" "tests/test_m3_tenancy.py"
mutation "M3 Einladung mehrfach einlösbar" "members/accept.py" "WHERE id = :i AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now()|||WHERE id = :i" "tests/test_m3_tenancy.py"
mutation "M3 Vorprüfung ignoriert Gültigkeit" "members/accept.py" "    if r is None or not r.gueltig:|||    if r is None:" "tests/test_m3_tenancy.py"
mutation "M3 Fremdes Konto nimmt Einladung an" "members/accept.py" "    if email != inv.email:|||    if False:" "tests/test_m3_tenancy.py"
mutation "M3 Bestehendes Konto ohne Zustimmung" "members/accept.py" "        if s.execute(text(\"SELECT 1 FROM users WHERE lower(email) = :e\"), {\"e\": inv.email}).scalar():|||        if False:" "tests/test_m3_tenancy.py"
mutation "M3 Firmenprofil ohne Validierung" "tenancy/service.py" "    _pruefen(t.slug, name, str(neu[\"timezone\"]), str(neu[\"language\"]), str(neu[\"currency\"]))|||    pass" "tests/test_m3_tenancy.py"
mutation "M3 Route mandantenblind (RLS) → IDOR-Generator" "migrations/versions/0003_core.py" "                           USING (tenant_id = ichq_current_tenant())
                           WITH CHECK|||                           USING (true)
                           WITH CHECK" "tests/test_core_security.py"
mutation "3a Fahrt über finance.read lesbar" "objects/registry.py" "_T(\"trip\", \"Fahrt\", \"receipts\", \"vehicles.read\",|||_T(\"trip\", \"Fahrt\", \"receipts\", \"finance.read\"," "tests/test_core_followups.py"
mutation "3b Neuzuweisung behält automatische Freigabe" "tasks/service.py" "            drop_assignment_grant(session, principal, obj, alt_assignee)|||            pass" "tests/test_core_followups.py"
mutation "3b Neuzuweisung entzieht auch manuelle Freigabe" "relations/service.py" "        ObjectGrant.source == AUTO)).rowcount|||        True)).rowcount" "tests/test_core_followups.py"
mutation "3b API-Entzug entfernt automatische Freigabe" "relations/service.py" "                                                  ObjectGrant.source == MANUAL)).rowcount|||                                                  True)).rowcount" "tests/test_core_followups.py"
mutation "3c Historie-Trigger fehlt" "migrations/versions/0005_core_followups.py" "    CREATE TRIGGER trg_comments_history AFTER INSERT OR UPDATE ON comments
      FOR EACH ROW EXECUTE FUNCTION ichq_comment_history();|||    SELECT 1;" "tests/test_core_followups.py"
mutation "3c Gelöschter Kommentar änderbar" "migrations/versions/0005_core_followups.py" "      IF OLD.deleted_at IS NOT NULL THEN|||      IF false THEN" "tests/test_core_followups.py"
mutation "3d Scan ohne Sperre gegen Parallellauf" "db/locks.py" "        erworben = bool(conn.execute(text(\"SELECT pg_try_advisory_lock(:k)\"), {\"k\": key}).scalar())|||        erworben = True" "tests/test_notifications_job.py"
mutation "3d Fehler einer Firma bricht den Scan ab" "notifications/jobs.py" "            except Exception as e:   # eine Firma darf die anderen nicht aufhalten|||            except ZeroDivisionError as e:" "tests/test_notifications_job.py"
mutation "3d Doppelte Zustellung (kein dedup_key)" "notifications/service.py" "                     dedup_key=dedup_key)|||                     dedup_key=None)" "tests/test_notifications_job.py"

# ---------- M2-Restpunkte ----------
mutation "M2 Aufräumen ignoriert Alter der Anmeldeversuche" "auth/cleanup.py" "\"DELETE FROM login_attempts WHERE occurred_at < now() - make_interval(days => :d)\"|||\"DELETE FROM login_attempts WHERE true\"" "tests/test_auth_cleanup.py"
mutation "M2 Aufräumen löscht frisch widerrufene Sitzungen" "auth/cleanup.py" "WHERE (revoked_at IS NOT NULL AND revoked_at < now() - make_interval(days => :d))|||WHERE (revoked_at IS NOT NULL)" "tests/test_auth_cleanup.py"
mutation "M2 Aufräumen löscht unbenutzte Recovery-Codes" "auth/cleanup.py" "\"DELETE FROM recovery_codes WHERE used_at < now() - make_interval(days => :d)\"|||\"DELETE FROM recovery_codes WHERE used_at IS NULL OR used_at < now()\"" "tests/test_auth_cleanup.py"
mutation "M2 Aufräumen ohne Sperre" "db/locks.py" "        erworben = bool(conn.execute(text(\"SELECT pg_try_advisory_lock(:k)\"), {\"k\": key}).scalar())|||        erworben = True" "tests/test_auth_cleanup.py"
mutation "Migration: Daten-Pflege unter FORCE RLS" "migrations/datenpflege.py" "op.execute(f\"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY\")|||op.execute(f\"ALTER TABLE {t} FORCE ROW LEVEL SECURITY\")" "tests/test_migrations.py"
# ---------- M4 Rollen & Rechte: jede Stufe der Entscheidungsreihenfolge, jede Delegationsregel ----------
M4D="tests/test_m4_decision.py"; M4G="tests/test_m4_delegation.py"; M4B="tests/test_m4_boundaries.py"
mutation "M4 1 Feature-Flag ignoriert" "authz/effective.py" "        if module_of(p) in aus:|||        if False:" "$M4D"
mutation "M4 1 Fehlercode feature_disabled fehlt" "api/security.py" "        if any(module_of(p) in principal.disabled_modules for p in fehlend):|||        if False:" "$M4D"
mutation "M4 1 Kernmodul per CLI abschaltbar" "authz/flags.py" "    if module not in FLAGGABLE_MODULES:|||    if False:" "$M4D"
mutation "M4 1 Kernmodul-Flag aus der DB wirkt" "authz/effective.py" "    return frozenset(rows) & FLAGGABLE_MODULES|||    return frozenset(rows)" "$M4D"
mutation "M4 2 Einzelrecht-DENY ignoriert" "authz/effective.py" "        elif einzel.get(p) == \"deny\":|||        elif False:" "$M4D"
mutation "M4 3 Ressourcen-DENY ignoriert" "objects/visibility.py" "and_(obj.type.in_(sorted(typen)), ~verboten)|||obj.type.in_(sorted(typen))" "$M4D"
mutation "M4 3 Gesperrte Person zuweisbar" "tasks/service.py" "    if task_obj is not None and session.get(ObjectDeny, (task_obj.id, m.id)) is not None:|||    if False:" "$M4D"
mutation "M4 4 Einzelrecht-ALLOW ignoriert" "authz/effective.py" "        elif einzel.get(p) == \"allow\":|||        elif False:" "$M4D"
mutation "M4 6 Company Admin hält nichts" "authz/effective.py" "for p in (PERMISSIONS if alle else|||for p in (set() if alle else" "$M4D"
mutation "M4 6 Archivierte Rolle wirkt" "authz/effective.py" " AND r.archived_at IS NULL|||" "$M4D"
mutation "M4 Obergrenze beim Anlegen aus" "authz/roles.py" "    fehlend = sorted(perms - a.permissions)|||    fehlend = []" "$M4G"
mutation "M4 Lücken-Löschung" "authz/roles.py" "            neu = (gewuenscht & a.permissions) | (alt - a.permissions)|||            neu = gewuenscht & a.permissions" "$M4G"
mutation "M4 Rang beim Anlegen ignoriert" "authz/roles.py" "    if not 1 <= rank < a.rank:|||    if not 1 <= rank:" "$M4G"
mutation "M4 Rang beim Verwalten ignoriert" "authz/roles.py" "    if r.priority >= a.rank:|||    if False:" "$M4G"
mutation "M4 Gesperrte Rolle verwaltbar" "authz/roles.py" "    if r.grants_all:
        raise RoleLocked|||    if False:
        raise RoleLocked" "$M4G"
mutation "M4 Duplizieren kopiert fremde Rechte" "authz/roles.py" "    perms = role_permissions(session, quelle) & a.permissions|||    perms = role_permissions(session, quelle)" "$M4G"
mutation "M4 Wiederherstellen ohne Obergrenze" "authz/roles.py" "    _obergrenze(a, role_permissions(session, r))      # wie Vergeben|||    pass  # wie Vergeben" "$M4G"
mutation "M4 Löschen trotz Zuweisung" "authz/roles.py" "    if session.scalar(select(func.count()).select_from(MembershipRole).where(MembershipRole.role_id == r.id)):|||    if False:" "$M4G"
mutation "M4 Selbstbedienen erlaubt" "authz/delegation.py" "    if t.id == p.membership_id:|||    if False:" "$M4G"
mutation "M4 Personen-Rang ignoriert" "authz/delegation.py" "    if effective(session, t.id).rank > a.rank:|||    if False:" "$M4G"
mutation "M4 Rollen-Obergrenze beim Vergeben aus" "authz/delegation.py" "    fehlend = sorted(role_permissions(session, r) - a.permissions)|||    fehlend = []" "$M4G"
mutation "M4 Rollen-Rang beim Vergeben aus" "authz/delegation.py" "    if r.priority > a.rank:
        raise PermissionDenied(\"Rollen über dem eigenen Rang können nicht vergeben werden\")|||    pass" "$M4G"
mutation "M4 Archivierte Rolle vergebbar" "authz/delegation.py" "    if r.archived_at is not None:
        raise Conflict|||    if False:
        raise Conflict" "$M4G"
mutation "M4 Einzelrecht-Obergrenze aus" "authz/delegation.py" "    if permission not in a.permissions:|||    if False:" "$M4G"
mutation "M4 Letzter Admin ungeschützt" "authz/guard.py" "    if vorher > 0 and not admins(session):|||    if False:" "$M4B"
mutation "M4 Last-Admin ohne Sperre (Nebenläufigkeit)" "authz/guard.py" "(\" FOR UPDATE\" if lock else \"\")|||(\"\")" "$M4B"
mutation "M4 Admin = nur ein Recht" "authz/registry.py" "frozenset({\"users.deactivate\", \"roles.update\", \"roles.assign\"})|||frozenset({\"users.deactivate\"})" "$M4B"
mutation "M4 Archivieren ohne Last-Admin-Schutz" "authz/roles.py" "        with admin_remains(session):
            session.execute(update(Role).where(Role.id == r.id).values(archived_at=func.now()))|||        if True:
            session.execute(update(Role).where(Role.id == r.id).values(archived_at=func.now()))" "$M4B"
mutation "M4 DB-Sperre der gesperrten Rolle aus" "migrations/versions/0006_m4_rbac.py" "      IF OLD.grants_all AND (NEW.name|||      IF false AND (NEW.name" "$M4B"
mutation "M4 App-Rolle schreibt Feature-Flags" "migrations/versions/0006_m4_rbac.py" "    GRANT SELECT ON tenant_feature_flags TO ichq_app;|||    GRANT SELECT, INSERT ON tenant_feature_flags TO ichq_app;" "$M4B"
mutation "M4 Migration lässt Rechteliste der Übergangsrolle stehen" "migrations/versions/0006_m4_rbac.py" "        op.execute(\"DELETE FROM role_permissions rp USING roles r WHERE r.id = rp.role_id AND r.grants_all\")|||        pass" "tests/test_m4_setup.py"
# ---------- U1 Oberfläche (ADR-013) ----------
U1S="tests/test_u1_static.py"; U1B="tests/test_u1_browser.py"
mutation "U1 Pfad-Regex aus" "api/ui.py" "    if not _PFAD.match(pfad) or any(teil in (\"\", \".\", \"..\") for teil in pfad.split(\"/\")[:-1]) or \"..\" in pfad:|||    if False:" "$U1S"
mutation "U1 Symlink-Ausbruch" "api/ui.py" "    if not datei.is_relative_to(WEB) or not datei.is_file() or datei.suffix not in TYPES:|||    if not datei.is_file() or datei.suffix not in TYPES:" "$U1S"
mutation "U1 Beliebige Dateitypen" "api/ui.py" " or datei.suffix not in TYPES:|||:" "$U1S"
mutation "U1 Sicherheits-Header fehlen" "api/ui.py" "    resp.headers.update(HEADERS)|||    pass" "$U1S"
mutation "U1 Zwei CSP (Middleware überschreibt nicht)" "api/middleware.py" "headers.extend(h for h in standard if h[0] not in gesetzt)|||headers.extend(standard)" "$U1S"
mutation "U1 Text als HTML eingefügt" "web/js/dom.js" "    el.append(k instanceof Node ? k : document.createTextNode(String(k)));|||    if (k instanceof Node) el.append(k); else el.insertAdjacentHTML(\"beforeend\", String(k));" "$U1S $U1B"
mutation "U1 Veraltete Ansicht überschreibt neue Seite" "web/js/app.js" "    await r.ansicht(ziel, r.params, query);|||    await r.ansicht(inhalt, r.params, query);" "$U1B"
mutation "U1 Navigation ohne Rechtefilter" "web/js/app.js" "NAV.filter((n) => !n.recht || darf(n.recht))|||NAV.filter(() => true)" "$U1B"
echo "---"; echo "erkannt $ERKANNT · unbemerkt $UNBEMERKT · ungültig $UNGUELTIG"
[ "$UNBEMERKT" -eq 0 ] && [ "$UNGUELTIG" -eq 0 ]
