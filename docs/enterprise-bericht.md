# Bericht: Enterprise-Module (Master-Prompt 1, ADR-020)

Stand 19.10.2026, Branch `claude/zen-babbage-l8n0be`, PR #2 (nicht gemergt). Alle Zahlen stammen aus tatsächlich
ausgeführten Läufen. „Nicht getestet“ steht ausdrücklich da, wo es zutrifft. **Nichts davon ist produktionsreif. Keine
Steuerfunktion geht vor Tor S an Kunden** (CLAUDE.md).

## 1. Was umgesetzt ist

| Phase | Ergebnis | Commit |
| --- | --- | --- |
| 1 Bestandsaufnahme | `docs/enterprise-bestandsaufnahme.md`, ADR-020 (15 Entscheidungen) | vor E1 |
| 2 Gemeinsame Architektur | Fachobjekte auf `objects`, dreifache Mandantentrennung, Geld in Cent, `kurz()` für lange Namen, Archiv-Wächter, `company_today/currency` | E1–E3 |
| 7 Kunden & Anfragen | Dublettenprüfung (409 statt still), Zusammenführen, Kontaktpersonen, Anfragen mit Wiedervorlage | E1 `78e6ca7` |
| 4 Projekte | Team = Freigabe (`project_team`), Budget, Projektzeiten, Aufgaben, Kanban | E2 `63097ff` |
| 3.2 Rechnungen | lückenloser Nummernkreis (8 parallele Ausstellungen getestet), DB-Unveränderbarkeit, Storno als Gegenrechnung, Zahlungen mit Rücknahme, Druckansicht | E3 `0ad72f4` |
| 3.3 Überfällig | Überfälligkeit in Firmenzeitzone, Kontaktversuche/Mahnstufen nur dokumentiert, **kein automatischer Versand** | E3 |
| 3.4 Fehlende Belege | Belegstatus aus Dokument + Virenprüfung (Quarantäne ≠ vorhanden), Stornieren statt Löschen (DB) | E4 `6f6deeb` |
| 3.1 Liquidität | nur manuelle Stände (anhängend), seither erfasst, erwartet, Herkunft jeder Zahl, Unschärfe sichtbar, keine Umrechnung | E5 `cd23a74` |
| 3.5 Steuerfristen | selbst angelegt, Quelle als Freitext, ohne Quelle „nicht amtlich bestätigt“, Wiederholung, Erinnerung | E6 `ce087ba` |
| 5 Verträge | Laufzeit, Kündigungsfrist, Verlängerung, Termin als Kalenderrechnung (keine Rechtsprüfung), Upload ≠ Prüfung | E6 |
| 3.6 Monatsabschluss | Prüfliste, Sperre in Service **und** DB-Triggern, Wiedereröffnen mit Grund, Historie | E7 `e5de0e7` |
| 3.7 Export | internes CSV `ichq-buchungen-v1` mit Prüfbericht, SHA-256, Historie, Wiederholung, CSV-Injection-Schutz. **Kein DATEV** | E7 |
| 6 Reisen/Fahrtenbuch | Fahrten nur als Versionen, Korrektur sichtbar in der Fahrt, Kilometer-Lücken, Periodensperre. Dienstreisen mit Genehmigung ohne Selbstgenehmigung | E8 `0ddf3f3` |
| 4 Profitabilität | Erlös/Ausgaben/Personal mit `gaps` und `complete` | E9 `67f9e7b` |
| 8 Dashboard | 11 Widgets mit echten Zahlen (Zahl = Liste), nur DATEV bleibt „geplant“ | E9 |
| 9 Benachrichtigungen/Audit | Scan-Regeln (Rechnung, Kündigung, Frist, Reise), Audit + Aktivität je Fachaktion | E3–E9 |

Details, Routen und Rechte je Modul stehen in `docs/fachmodule.md`, das Exportformat in `docs/export-format.md`.

## 2. Dateien (Auswahl)

* Pakete: `src/ichq/crm/`, `src/ichq/projects/`, `src/ichq/finance/` (Rechnungen, Zahlungen, Belege, Liquidität,
  Fristen, Abschluss, Sperre, Export, Profitabilität), `src/ichq/contracts/`, `src/ichq/travel/`,
  `src/ichq/core/kalender.py`, `src/ichq/dashboard/fach.py`, `src/ichq/notifications/fach.py`.
* API: `src/ichq/api/v1/{crm,projects,invoices,receipts,liquidity,deadlines,contracts,closing,travel}.py`.
* Oberfläche: `src/ichq/web/js/views/{kunden,anfragen,projekte,rechnungen,belege,liquiditaet,fristen,vertraege,
  abschluss,fahrtenbuch,reisen}.js`.
* Tests: `tests/test_e1_crm.py` … `tests/test_e9_profit_dashboard.py`, `tests/test_e_browser.py`. Erweitert wurden
  `tests/test_core_security.py` (IDOR-Generator, Listen ohne fremde IDs) und die D0-Tests.
* Mutationen: `scripts/mutation-fachmodule.sh` (wird von `scripts/mutation-check.sh` eingebunden).

## 3. Migrationen

`0009_crm` · `0010_projects` · `0011_invoices` · `0012_receipts` · `0013_liquidity` · `0014_deadlines_contracts` ·
`0015_month_close_export` · `0016_travel_logbook`.

Jede neue Tabelle hat `FORCE ROW LEVEL SECURITY`, eine Mandanten-Policy für `ichq_app`, zusammengesetzte
Fremdschlüssel `(tenant_id, x_id)` und Spaltenrechte nur für änderbare Felder. Unveränderbarkeit erzwingen Trigger, die
auch den Superuser sperren: ausgestellte Rechnungen, Ausgaben (Löschen), Kontostände, Abschlüsse, Exporte und
Fahrtversionen. Hoch/Runter/Hoch und der Abgleich Modell ↔ Migration laufen in `tests/test_migrations.py`.

## 4. Testergebnisse (echt ausgeführt)

| Lauf | Ergebnis |
| --- | --- |
| Ausgangsstand vor E1 | 619 passed |
| Gesamtsuite nach E4 / E5 / E6 / E7 / E8 / E9 | 656 / 661 / 667 + 1 Doku-Fehler, behoben / 673 / 678 / **681 passed** |
| ruff, mypy (196 Dateien), lint-imports | grün |
| Mutationen Fachmodule, Teilläufe je Modul | CRM 6, Projekte 7, Rechnungen 12, Belege 7, Liquidität 11, Fristen/Verträge 13, Abschluss/Export 15, Fahrtenbuch/Reisen 14, E9 12. **Alle erkannt.** 14 davon waren zunächst unbemerkt und haben zu geschärften Tests geführt |
| Gesamter Mutationslauf `scripts/mutation-check.sh` | 313 erkannt · 0 unbemerkt · 1 ungültig (Muster angepasst, erkannt), siehe 4a |
| CI (GitHub) | E7 (`e5de0e7`) und E8 (`0ddf3f3`) vollständig grün inkl. `mutation`. Auf `0d8ed0f` alle vier Jobs grün (Mutation 314 · 0 · 0). Dazwischen war E9 rot wegen eines veralteten Musters, das behoben ist |

Geprüft wird, was CLAUDE.md verlangt:
* CRUD und Statusübergänge,
* Rechte: 403 ohne Recht, 404 ohne Sichtbarkeit,
* Mandantenisolation: API, RLS und zusammengesetzte Fremdschlüssel,
* Berechnungen (Rundung, Netto/Steuer, Kalender, Kündigungstermine, Liquidität),
* Nebenläufigkeit beim Nummernkreis,
* Migrationen,
* Browsertests je neuer Seite mit CSP-Prüfung und XSS-Probe.

### 4a. Gesamter Mutationslauf

* **Lokal** (`scripts/mutation-check.sh`, 19.10.2026): Der Lauf lief in mein Zeitlimit von 7000 s, nachdem 304
  Mutationen erkannt waren. Die restlichen 9 (4 aus E9, 5 Windows-Launcher) liefen einzeln: 9 erkannt.
  **Summe: 313 erkannt · 0 unbemerkt · 1 ungültig.**
* **CI** auf `208b6f2`: **erkannt 313 · unbemerkt 0 · ungültig 1**. Auf `e5de0e7` (E7) war der Job grün mit 288 · 0 · 0.
* Die eine ungültige Mutation („D0 Kennzahl-Link ohne Filter“) passte seit E9 nicht mehr, weil `dashboard.js` jetzt
  API-Filter in Ansichten übersetzt. Das Muster ist in `0d8ed0f` angepasst und wird lokal wieder erkannt. Damit sind es
  **314 von 314** Mutationen. **CI auf `0d8ed0f`: erkannt 314 · unbemerkt 0 · ungültig 0, alle Jobs grün.**
* Schon vorher war der CI-Job `mutation` von E2 bis E6 rot, ebenfalls wegen eines veralteten Musters („3b
  Neuzuweisung“, in E7 behoben). Muster veralten, wenn Code umgebaut wird. Der ungültige Zähler macht das sichtbar,
  bevor eine Schutzregel unbemerkt ungeprüft bleibt.

## 5. Fehlende Integrationen (nicht gebaut, nicht behauptet)

* **Bank:** keine Anbindung (kein FinTS/PSD2), deshalb gibt es keine Live-Kontostände.
* **DATEV:** kein DATEV-Format, keine Kompatibilitätsaussage. Der Export ist internes CSV.
* **E-Rechnung:** XRechnung/ZUGFeRD nicht gebaut.
* **PDF:** keine serverseitige PDF-Erzeugung, nur die Browser-Druckansicht.
* **Versand an Kunden:** keine Rechnungs- oder Mahnmails an Kunden. Benachrichtigungen gehen nur in die App.
* **OCR/Belegerkennung:** nicht gebaut. Beträge werden von Hand erfasst.
* **Steuerwerte:** keine Pauschalen (Verpflegung, Kilometer), kein Privatanteil Kfz, keine Standard-Steuersätze. Es
  gibt keine amtlich bestätigten Werte im System (Steuerregel 1).

## 6. Umgebungsvariablen

Keine neuen. Die Fachmodule nutzen die bestehende Konfiguration (`docs/configuration.md`). Der Scan der
Benachrichtigungen läuft wie bisher über `ichq notifications-scan` (systemd-Timer).

## 7. Offene Punkte und bekannte Grenzen (ehrlich)

* **Vorlagenrechte sind Annahmen.** Mitarbeiter bekommen `travel.create`. `travel.approve` ist kritisch. Beides mit
  echten Nutzern prüfen.
* Fahrten- und Reiselisten sind nicht seitenweise, sondern auf 200 Einträge begrenzt. Die Kennzahl „Fahrten diesen
  Monat“ zählt höchstens 200. Die Kündigungsliste rechnet höchstens 1000 Verträge (`truncated`).
* Die Periodensperre gilt für Rechnungsdatum, Zahlungen, Ausgaben und Fahrten. Dienstreisen und Planposten sind
  **nicht** gesperrt, weil sie keine Buchungen sind.
* Profitabilität ist eine Rechenhilfe: keine Gemeinkosten, keine Abschreibungen. Ausgaben ohne Steuersatz zählen brutto
  (mit Hinweis).
* Die Liquidität rechnet erfasste Bewegungen ab dem **ältesten** Stichtag. Bei unterschiedlichen Stichtagen ist das
  unscharf und wird angezeigt.
* Kündigungstermine und Fahrtenbuch werden ohne Aussage zur Rechtswirksamkeit bzw. Ordnungsmäßigkeit geführt.
* Kein Lasttest. Die Dashboard-Widgets fragen je Aufruf mehrere Tabellen ab. Mit großen Datenmengen ist das nicht
  gemessen.
* Die Oberflächen sind funktional getestet, aber nicht mit echten Nutzern erprobt.

## 8. Nächste Schritte (Vorschlag)

1. Review von PR #2 (CI grün auf `0d8ed0f`). **Kein Merge ohne
   Prüfung.**
2. Vorlagenrechte und Abläufe (Abschluss, Fahrtenbuch, Reisen) mit einem Pilotkunden durchgehen.
3. Steuerwerte nur mit Fundstelle als versionierte Daten (`docs/steuerwerte-pruefung.md`), danach Tor S.
4. DATEV-Export erst mit Formatbeschreibung, Kontenrahmen der Firma und echtem Importtest.
5. Seitenweise Listen für Fahrten und Reisen, Lastmessung des Dashboards.
