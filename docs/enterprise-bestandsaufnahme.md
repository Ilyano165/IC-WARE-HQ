# Bestandsaufnahme Fachmodule (12.10.2026, vor Master Prompt 1)

Geprüft wurden Code, Migrationen, Tests und Oberfläche — nicht nur, ob es eine Seite gibt, sondern ob sie mit API und
Datenbank verbunden ist. Ausgangsmessung: `pytest` gegen PostgreSQL 16 → **619 bestanden, 0 fehlgeschlagen**.

## 1. Vollständig implementiert und getestet

| Bereich | Nachweis |
| --- | --- |
| Mandanten, Firmenstatus, Pausieren | M3, `tests/test_m3_tenancy.py`, `test_isolation.py` |
| Anmeldung, Sitzungen, 2FA, Reset, Drosselung | M2, `tests/test_auth_*.py` |
| Rollen, Einzelrechte, DENY, Delegation, Last-Admin | M4, `tests/test_m4_*.py`, `test_authz.py` |
| Objektmodell, Verknüpfungen, Freigaben, Sichtbarkeit | C0, `test_core_objects.py`, `test_core_security.py` (IDOR-Generator) |
| Aufgaben (Liste, Detail, Zuweisung, Anhänge, Kommentare) | C0 + U1, `test_core_api.py`, `test_u1_browser.py` |
| Dokumente mit Virenprüfung und Quarantäne | `test_documents_scan.py` |
| Kommentare/Rückfragen, Aktivität, Audit, Benachrichtigungen, Suche | `test_core_*.py`, `test_notifications_job.py` |
| Mitglieder, Einladungen | `test_m3_tenancy.py`, `test_launch_browser.py` |
| Dashboard-Rahmen (Widgets mit Rechten, „Zahl = Liste") | D0, `test_d0_dashboard.py` |
| Mail-Outbox, Sicherung, Monitoring, Installer | ADR-015/016, `test_mail.py`, `test_deploy*.py` |

## 2. Vorhanden, aber unvollständig

| Bereich | Was fehlt |
| --- | --- |
| Objekttypen `customer`, `project`, `invoice`, `payment`, `receipt`, `contract`, `trip`, `travel` | nur reserviert (`implemented=False`), keine Fachtabelle, keine API |
| Rechte `contracts.*`, `vehicles.*`, `travel.*` | nur `.read`/`.update`; `create`/`approve` fehlen |
| Dashboard-Widgets Liquidität, Rechnungen, Belege, Fristen, Abschluss, Export, Projekte, Verträge, Reisen, Fahrten, CRM | `PLANNED` ohne Werte (ehrlich, aber ohne Funktion) |
| Archivieren von Objekten | Spalte `objects.archived_at` und Spaltenrecht vorhanden, keine Route |
| Geldtyp | `ichq.core.money.Money` (Cent) vorhanden, bisher ungenutzt |

## 3. Noch nicht implementiert

Kunden/Kontaktpersonen, Anfragen, Projekte mit Team/Budget, Rechnungen (Positionen, Nummernkreis, Storno),
Zahlungen, Überfälligkeit und Mahnhistorie, Ausgaben/Belege mit Status, Liquidität, Fristen, Verträge,
Monatsabschluss mit Periodensperre, Export mit Historie, Reiseanträge mit Genehmigung, Fahrtenbuch,
Projektprofitabilität, Zeiterfassung, Bankanbindung, DATEV, PDF-Erzeugung, Mahnversand an Kunden.

Umsetzung: ADR-020. Fortschritt und Ergebnisse stehen im Abschlussbericht `docs/enterprise-bericht.md`.
