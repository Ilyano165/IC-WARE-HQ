#!/bin/bash
# Mutationen der Unternehmensverwaltung (ADR-021). Wird von scripts/mutation-check.sh eingebunden (nutzt mutation()).
# shellcheck disable=SC2154
CTL="tests/test_control.py"
mutation "Betreiber: Marke prüft Betreiber nicht" "api/security.py" "            if not control.is_operator(s, info.user_id):|||            if False:" "$CTL"
mutation "Betreiber: halbe Anmeldung (2FA offen) reicht" "api/security.py" "        if info is None or info.stage != \"full\":
            raise AuthenticationRequired()
        with platform_transaction|||        if info is None:
            raise AuthenticationRequired()
        with platform_transaction" "$CTL"
mutation "Einrichtungscode läuft nie ab" "control/service.py" " AND expires_at > now() RETURNING id|||  RETURNING id" "$CTL"
mutation "Einrichtungscode mehrfach verwendbar" "control/service.py" "WHERE code_hash = :h AND used_at IS NULL AND|||WHERE code_hash = :h AND" "$CTL"
mutation "Einrichtungscode auch nach der Einrichtung" "control/service.py" "    if not setup_needed(s):
        raise Conflict(|||    if False:
        raise Conflict(" "$CTL"
mutation "Letzter Betreiber entfernbar" "control/service.py" "    if len(alle) == 1:|||    if False:" "$CTL"
mutation "Firma vor Passwortprüfung angelegt" "control/onboarding.py" "    _pruefe_admin(admin)
    with platform_transaction|||    with platform_transaction" "$CTL"
mutation "Betreibertabelle für Mandanten-Rolle lesbar" "migrations/versions/0017_control.py" "    GRANT SELECT, INSERT, DELETE ON platform_operators TO ichq_platform;|||    GRANT SELECT, INSERT, DELETE ON platform_operators TO ichq_platform, ichq_app;" "$CTL"
mutation_deploy "Einrichtungscode in deploy/hq ungeprüft" "hq" "  [[ \"\$code\" =~ ^[A-Za-z0-9_-]{20,64}\$ ]] || fehler|||  [[ \"\$code\" =~ .+ ]] || fehler" "tests/test_deploy_tunnel.py"
