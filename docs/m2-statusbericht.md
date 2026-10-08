# M2 Authentication — Statusbericht (Abschluss, 08.10.2026)

## Implemented
Login mit E-Mail/Benutzername, Argon2id, Passwortregel (NIST), serverseitige Sitzungen (Leerlauf + absolut, Rotation
je Stufe), TOTP-2FA mit Recovery-Codes, Passwort ändern/zurücksetzen, Kontozustände, Drosselung und Kontosperre in
PostgreSQL (ADR-006), CSRF-Schutz, Auth-Ereignisse (nur anhängend), Firmenwahl, Rolle `ichq_auth`.
Abschluss-Punkte: `docs/authentication.md`, Konfiguration/Server-Setup, ADR-006, Migrationstest mit M1-Altdaten,
Aufräum-Job `ichq auth-cleanup` + systemd-Timer, bekannte Grenzen dokumentiert.

## Tested
Auth-Testdateien `test_auth_*.py`, `test_auth_cleanup.py`, `test_migrations.py::test_m1_altdaten_nach_0002`;
Zahlen der Gesamtsuite: siehe letzter Lauf in `docs/testing.md` und im CI. Mutationen M2: 26 + 4 (Aufräumen) +
1 (Migration).

## Gefunden beim Abschluss
**Daten-Pflege in Migrationen war wirkungslos:** `FORCE ROW LEVEL SECURITY` gilt auch für den Besitzer
`ichq_owner`; ohne Policy sahen `UPDATE`s in Migrationen keine Zeile. `0002` wäre mit M1-Altdaten gescheitert
(CHECK-Verletzung), `0005` hätte Bestands-Kommentare ohne Historie gelassen. Behoben mit
`ichq.migrations.datenpflege.ohne_force` (FORCE nur innerhalb der Migrations-Transaktion aufheben), belegt durch
zwei Migrationstests mit Bestandsdaten und eine Mutation. `0002` wurde dafür nachträglich geändert — vertretbar,
weil noch nichts produktiv läuft; in Produktion wäre das eine neue Migration gewesen.

## Not Tested
Echter SMTP-Versand (nur MemoryMailer); Betrieb hinter echtem Caddy mit echter Client-IP (Compose-Smoke-Test aus
`docs/claude-code-prompts.md` Abschnitt 2 steht aus); systemd-Timer auf echtem Server.

## Known Issues
Siehe Tabelle „Bekannte Grenzen" in `docs/authentication.md` (Sperr-DoS, Tastaturmuster, TRUSTED_PROXIES, Schlüsselrotation).

## Security Review Required
Sitzungs- und Reset-Abläufe, Schlüsselableitung für TOTP, Drosselungsgrenzen — vor Tor 3 durch externen Pentest.

## Production Readiness: NOT READY
