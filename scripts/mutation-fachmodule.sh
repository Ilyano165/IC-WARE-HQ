#!/bin/bash
# Mutationen der Fachmodule (ADR-020) — wird von scripts/mutation-check.sh eingebunden (nutzt dessen mutation()).
# shellcheck disable=SC2154
CRM="tests/test_e1_crm.py"
mutation "CRM: Kundenliste ohne Sichtbarkeit" "api/v1/crm.py" "customers.list_customers(s, visible_clause(p), f,|||customers.list_customers(s, __import__('sqlalchemy').true(), f," "$CRM"
mutation "CRM: Anfrage nennt unsichtbaren Kunden" "api/v1/crm.py" "if i.customer_id is not None and can_see(s, p, i.customer_id):|||if i.customer_id is not None:" "$CRM"
mutation "CRM: RLS auf Kunden liest alles" "migrations/versions/0009_crm.py" "                       USING (tenant_id = ichq_current_tenant())|||                       USING (true)" "$CRM"
mutation "CRM: Dublettenprüfung aus" "crm/customers.py" "    if doppelt and not allow_duplicate:|||    if False:" "$CRM"
mutation "CRM: Archivieren ohne Änderungsrecht" "objects/service.py" "    if not can_update(principal, obj):|||    if False:" "$CRM"
mutation "CRM: Zusammenführen prüft fremde ID zu spät" "crm/customers.py" "    alt, alt_o = get(session, principal, ref)             # erst auflösen: fremde IDs ⇒ 404, nie 422|||    if ref == into_ref:
        raise ValidationFailed(\"selbst\")
    alt, alt_o = get(session, principal, ref)" "tests/test_core_security.py"

PRJ="tests/test_e2_projects.py"
mutation "Projekt: Teamfreigabe bleibt nach Entfernen" "projects/service.py" "    drop_assignment_grant(session, principal, o, m.id, TEAM)|||    pass" "$PRJ"
mutation "Projekt: Kostensatz ohne Finanzrecht sichtbar" "api/v1/projects.py" "    kosten = decide(p, \"finance.read\")|||    kosten = True" "$PRJ"
mutation "Projekt: Kostensatz ohne Finanzrecht setzbar" "projects/service.py" "    if cost_given and not decide(principal, \"finance.read\"):|||    if False:" "$PRJ"
mutation "Projekt: Zeit für andere ohne projects.assign" "projects/service.py" "    if mid != principal.membership_id and not decide(principal, \"projects.assign\"):|||    if False:" "$PRJ"
mutation "Projekt: Zeit ohne Teammitgliedschaft" "projects/service.py" "    if session.get(ProjectMember, (o.id, mid)) is None:|||    if False:" "$PRJ"
mutation "Projekt: fremde Zeiten löschbar" "projects/service.py" "    if e.created_by_membership_id != principal.membership_id and not decide(principal, \"projects.update\"):|||    if False:" "$PRJ"
mutation "Projekt: RLS liest alles" "migrations/versions/0010_projects.py" "                       USING (tenant_id = ichq_current_tenant())|||                       USING (true)" "$PRJ"

RE="tests/test_e3_invoices.py"
M11="migrations/versions/0011_invoices.py"
mutation "Rechnung: ausgestellt änderbar (Trigger)" "$M11" "          RAISE EXCEPTION 'ichq: ausgestellte Rechnung ist unveränderlich — Korrektur nur per Storno';|||          NULL;" "$RE"
mutation "Rechnung: ausgestellt löschbar (Trigger)" "$M11" "          RAISE EXCEPTION 'ichq: ausgestellte Rechnung kann nicht gelöscht werden';|||          NULL;" "$RE"
mutation "Rechnung: zurück in den Entwurf (Trigger)" "$M11" "          RAISE EXCEPTION 'ichq: ausgestellte Rechnung kann kein Entwurf mehr werden';|||          NULL;" "$RE"
mutation "Rechnung: Positionen nach Ausstellen änderbar (Trigger)" "$M11" "      IF st IS DISTINCT FROM 'draft' THEN|||      IF false THEN" "$RE"
mutation "Rechnung: Zahlung auf Entwurf (Trigger)" "$M11" "      IF r.status IS NULL OR r.status IN ('draft', 'cancelled') OR r.kind <> 'invoice' THEN|||      IF false THEN" "$RE"
mutation "Rechnung: Nummernkreis zählt nicht hoch" "finance/invoices.py" "ON CONFLICT (tenant_id, year) DO UPDATE SET next_value = invoice_number_counters.next_value + 1|||ON CONFLICT (tenant_id, year) DO UPDATE SET next_value = invoice_number_counters.next_value" "$RE"
mutation "Rechnung: Überzahlung erlaubt" "finance/payments.py" "    if amount_minor > offen:|||    if False:" "$RE"
mutation "Rechnung: Storno trotz Zahlungen" "finance/invoices.py" "    if paid(session, inv.id) != 0:|||    if False:" "$RE"
mutation "Rechnung: ausgestellte archivierbar" "finance/invoices.py" "    if inv is not None and inv.status != \"draft\":|||    if False:" "$RE"
mutation "Rechnung: Überfällig ohne Fälligkeitsprüfung" "finance/invoices.py" "        teile.append(Invoice.due_date < f.overdue_on)|||        pass" "$RE"
mutation "Rechnung: Zahlungen ohne Finanzrecht sichtbar" "api/v1/invoices.py" "        if decide(p, \"finance.read\"):|||        if True:" "$RE"
mutation "Rechnung: Storno zeigt offenen Betrag" "api/v1/invoices.py" "if inv.kind == \"invoice\" and inv.status not in (\"draft\", \"cancelled\") else 0|||if inv.kind == \"invoice\" and inv.status != \"draft\" else 0" "$RE"

BEL="tests/test_e4_receipts.py"
mutation "Beleg: Quarantäne zählt als vorhanden" "finance/receipts.py" "(_SCAN == \"clean\", \"complete\"),|||(_SCAN != \"infected\", \"complete\")," "$BEL"
mutation "Beleg: Einzelstatus Quarantäne als vorhanden" "finance/receipts.py" "    return {\"clean\": \"complete\", \"infected\": \"rejected\"}.get(scan or \"\", \"unchecked\")|||    return \"complete\"" "$BEL"
mutation "Beleg: storniert änderbar (Service)" "finance/receipts.py" "    if r.voided_at is not None:|||    if False:" "$BEL"
mutation "Beleg: storniert änderbar (Trigger)" "migrations/versions/0012_receipts.py" "        RAISE EXCEPTION 'ichq: stornierte Ausgabe ist unveränderlich';|||        NULL;" "$BEL"
mutation "Beleg: löschbar (Trigger)" "migrations/versions/0012_receipts.py" "        RAISE EXCEPTION 'ichq: Ausgaben werden nicht gelöscht — stornieren';|||        RETURN OLD;" "$BEL"
mutation "Beleg: archivierbar" "finance/receipts.py" "ARCHIVE_GUARDS[\"receipt\"] = lambda _s, _o: \"Ausgaben werden nicht archiviert — Fehlerfassung bitte stornieren\"|||" "$BEL"
mutation "Beleg: Storno zählt weiter mit" "finance/receipts.py" "    teile: list[Any] = [Receipt.voided_at.is_not(None) if f.voided else Receipt.voided_at.is_(None)]|||    teile: list[Any] = []" "$BEL"

LIQ="tests/test_e5_liquidity.py"
mutation "Liquidität: Stand änderbar (Trigger)" "migrations/versions/0013_liquidity.py" "      RAISE EXCEPTION 'ichq: erfasster Kontostand ist unveränderlich — neuen Stand erfassen';|||      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW;" "$LIQ"
mutation "Liquidität: App darf Stände ändern" "migrations/versions/0013_liquidity.py" "    GRANT SELECT, INSERT ON liquidity_accounts, liquidity_balances, liquidity_forecasts TO ichq_app;|||    GRANT SELECT, INSERT, UPDATE ON liquidity_accounts, liquidity_balances, liquidity_forecasts TO ichq_app;" "$LIQ"
mutation "Liquidität: Stand in der Zukunft" "finance/liquidity.py" "    if as_of > today:|||    if False:" "$LIQ"
mutation "Liquidität: älterer Stand gilt" "finance/liquidity.py" "                           .order_by(LiquidityBalance.as_of.desc(), LiquidityBalance.created_at.desc())|||                           .order_by(LiquidityBalance.as_of.desc(), LiquidityBalance.created_at.asc())" "$LIQ"
mutation "Liquidität: archivierte Konten zählen" "finance/liquidity.py" "    for a in accounts(session):|||    for a in session.scalars(select(LiquidityAccount)):" "$LIQ"
mutation "Liquidität: fremde Währung mitgerechnet" "finance/liquidity.py" "        if a.currency != currency:
            continue|||        pass" "$LIQ"
mutation "Liquidität: unsichtbare Zahlungen zählen" "finance/liquidity.py" "                visible, Payment.currency == currency,|||                Payment.currency == currency," "$LIQ"
mutation "Liquidität: unsichtbare Ausgaben erwartet" "finance/liquidity.py" "            visible, Receipt.voided_at.is_(None), Receipt.payment_status == \"unpaid\", Receipt.currency == currency,|||            Receipt.voided_at.is_(None), Receipt.payment_status == \"unpaid\", Receipt.currency == currency," "$LIQ"
mutation "Liquidität: abgesagte Planposten zählen" "finance/liquidity.py" "            for f in forecasts(session) if|||            for f in forecasts(session, status=(\"open\", \"cancelled\")) if" "$LIQ"
mutation "Liquidität: verborgene Posten verschwiegen" "finance/liquidity.py" "    return int(n)|||    return 0" "$LIQ"
mutation "Liquidität: Überfälliges in der Vergangenheit" "finance/liquidity.py" "    plan = [_posten(\"forecast\", f.public_id, f.label, max(f.expected_on, today), f.amount_minor,|||    plan = [_posten(\"forecast\", f.public_id, f.label, f.expected_on, f.amount_minor," "$LIQ"


FV="tests/test_e6_deadlines_contracts.py"
mutation "Kalender: Monatsende nicht gekappt" "core/kalender.py" "    return date(jahr, monat, min(d.day, calendar.monthrange(jahr, monat)[1]))|||    return date(jahr, monat, min(d.day, 28))" "$FV"
mutation "Frist: ohne Quelle als bestätigt" "api/v1/deadlines.py" "\"user_reference\" if d.source_reference else \"unconfirmed\"|||\"user_reference\"" "$FV"
mutation "Frist: abgeschlossene änderbar" "finance/deadlines.py" "    if d.status != \"open\":|||    if False:" "$FV"
mutation "Frist: keine Folgefrist" "finance/deadlines.py" "    faellig = next_due(d)|||    faellig = None" "$FV"
mutation "Frist: Folgefrist mehrfach (DB)" "migrations/versions/0014_deadlines_contracts.py" "        sa.UniqueConstraint(\"tenant_id\", \"follows_deadline_id\", name=kurz(\"uq_deadlines_tenant_id_follows_deadline_id\")),|||" "$FV"
mutation "Frist: Erinnerung ignoriert Vorlauf" "finance/deadlines.py" "        teile += [Deadline.status == \"open\", Deadline.due_on - Deadline.remind_days_before <= f.remind_by]|||        teile += [Deadline.status == \"open\", Deadline.due_on <= f.remind_by]" "$FV"
mutation "Frist: Absagen ohne Grund" "finance/deadlines.py" "    if len(\" \".join(note.split())) < 3:|||    if False:" "$FV"
mutation "Vertrag: keine Verlängerung" "contracts/service.py" "    if c.auto_renew and c.renewal_months:
        while|||    if False:
        while" "$FV"
mutation "Vertrag: Kündigungsfrist nicht abgezogen" "contracts/service.py" "    kuendigung = verschiebe(ende, -frist[0], frist[1]) if frist else None|||    kuendigung = ende if frist else None" "$FV"
mutation "Vertrag: Kündigung in der Zukunft" "contracts/service.py" "    if terminated_on > today:|||    if False:" "$FV"
mutation "Vertrag: gekündigt änderbar" "contracts/service.py" "    if c.status == \"terminated\":
        raise Conflict(\"Gekündigter Vertrag|||    if False:
        raise Conflict(\"Gekündigter Vertrag" "$FV"
mutation "Vertrag: Status über PATCH kündbar" "contracts/service.py" "    if w.get(\"status\") == \"terminated\":|||    if False:" "$FV"
mutation "Vertrag: verpasster Termin in Kündigungsliste" "contracts/service.py" "if t.notice_deadline is not None and 0 <= (t.notice_deadline - today).days <= days:|||if t.notice_deadline is not None and (t.notice_deadline - today).days <= days:" "$FV"

AB="tests/test_e7_closing_export.py"
mutation "Abschluss: Sperre Ausgaben (Trigger)" "migrations/versions/0015_month_close_export.py" "          RAISE EXCEPTION 'ichq: Monat % ist abgeschlossen', to_char(OLD.expense_date, 'YYYY-MM');|||          NULL;" "$AB"
mutation "Abschluss: Sperre Rechnungsdatum (Trigger)" "migrations/versions/0015_month_close_export.py" "        RAISE EXCEPTION 'ichq: Monat % ist abgeschlossen', to_char(NEW.issue_date, 'YYYY-MM');|||        NULL;" "$AB"
mutation "Abschluss: Sperre Zahlungen (Trigger)" "migrations/versions/0015_month_close_export.py" "        RAISE EXCEPTION 'ichq: Monat der Zahlung ist abgeschlossen';
      END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;|||        NULL;
      END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;" "$AB"
mutation "Abschluss: Sperre auch andere Firma" "migrations/versions/0015_month_close_export.py" "      SELECT d IS NOT NULL AND EXISTS (SELECT 1 FROM month_closes m WHERE m.tenant_id = t|||      SELECT d IS NOT NULL AND EXISTS (SELECT 1 FROM month_closes m WHERE true" "$AB"
mutation "Abschluss: wiedereröffnet sperrt weiter" "migrations/versions/0015_month_close_export.py" "        AND m.period = date_trunc('month', d)::date AND m.reopened_at IS NULL)|||        AND m.period = date_trunc('month', d)::date)" "$AB"
mutation "Abschluss: löschbar (Trigger)" "migrations/versions/0015_month_close_export.py" "        RAISE EXCEPTION 'ichq: Monatsabschlüsse werden nicht gelöscht';|||        RETURN OLD;" "$AB"
mutation "Abschluss: Beleg nachreichen gesperrt (Service)" "finance/receipts.py" "    if BUCHUNG & changes.keys():|||    if True:" "$AB"
mutation "Abschluss: Service prüft Sperre nicht" "finance/sperre.py" "        if geschlossen(session, d):|||        if False:" "$AB"
mutation "Abschluss: Warnungen ohne Bestätigung" "finance/closing.py" "    if pruefung[\"warnings\"] and not confirm_warnings:|||    if False:" "$AB"
mutation "Abschluss: laufender Monat abschließbar" "finance/closing.py" "    if p >= today.replace(day=1):|||    if False:" "$AB"
mutation "Abschluss: Wiedereröffnen ohne Grund" "finance/closing.py" "    if len(grund) < 10:|||    if False:" "$AB"
mutation "Export: CSV-Injection" "finance/export.py" "    return \"'\" + t if t.startswith(_GEFAEHRLICH) else t|||    return t" "$AB"
mutation "Export: veränderbar (Trigger)" "migrations/versions/0015_month_close_export.py" "      RAISE EXCEPTION 'ichq: Exporte sind Historie und unveränderlich';|||      RETURN NEW;" "$AB"
mutation "Export: Download ohne Protokoll" "api/v1/closing.py" "        audit(s, \"export.downloaded\"|||        (lambda *a, **k: None)(s, \"export.downloaded\"" "$AB"
mutation "Export: Storno als fehlender Beleg" "finance/export.py" "        if not r.voided_at and beleg != \"complete\":|||        if beleg != \"complete\":" "$AB"
