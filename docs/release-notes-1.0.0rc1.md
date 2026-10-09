# IC WARE HQ 1.0.0rc1 — Release Candidate (09.10.2026)

**Release Candidate, kein freigegebenes Release.** Der Code ist implementiert und automatisiert getestet; produktiv
verifiziert ist noch nichts (es gibt noch keinen Produktionsserver). Was vor dem ersten Kunden fehlt, steht unten.

## Neu seit 0.1.0 (Stand `main` nach PR #1)

**Betrieb (ADR-015, ADR-016)**
* `deploy/install.sh`: Einrichtung auf einem Linux-Server mit fester Domain — HTTPS (Let's Encrypt), SMTP,
  Warn-Adresse, externes Sicherungsziel, systemd-Timer, optional Firewall; wiederholbar ohne Datenverlust.
* `deploy/hq`: status, check, start/stop, update (sichert vorher), backup, backup-verify, restore, setup-admin.
* Virenprüfung mit ClamAV: Uploads bleiben in Quarantäne, bis ein eindeutig sauberes Ergebnis vorliegt.
* Verschlüsselte Sicherung (restic) alle 6 h nach S3, Schlüssel getrennt, wöchentlicher automatischer
  Wiederherstellungstest in einer Wegwerf-Datenbank.
* Betriebsprüfung alle 5 min mit Alarm-Mail und externem Totmannschalter.

**E-Mail (ADR-016)**
* Einladungen, Passwort-Reset, Sicherheitshinweise (Passwort/2FA geändert, Sperre), Betreiberwarnungen — über eine
  Outbox mit Wiederholung, Ablauf, Dedup und Ratenlimit; Token-Mails nur verschlüsselt gespeichert.

**Sicherheit (docs/security-review.md)**
* 2FA gegen Durchprobieren über viele Logins gesichert; Passwort-Reset hebt keine Betreiber-Sperre auf;
  Passwortabfragen hinter einer Sitzung gedrosselt; Wiedereintritt ohne alte Rechte; Beleg-Freigabe erst nach
  Virenprüfung; Upload-Kontingente; verschlüsselte Paging-Cursor.

## Upgrade von 0.1.0
Migrationen 0007 (Virenprüfung) und 0008 (Mail-Outbox) laufen automatisch vor dem App-Start; Bestandsdokumente
bleiben in Quarantäne, bis der Scanner sie prüft. Getestet: Upgrade von 0006 mit Bestand und Rückweg
(`tests/test_migrations.py::test_update_von_main_0006_mit_bestand`).

## Vor dem ersten Kunden nötig (Betreiber)
Domain/DNS, SMTP-Zugang, externer S3-Speicher + verwahrter Sicherungsschlüssel, Warn-Adresse, optional
Totmannschalter — Schritte in `docs/server-setup.md`. Danach `deploy/hq check` ohne FEHLER und ein erfolgreicher
`deploy/hq backup-verify`.

## Bekannte Grenzen
Bis zu 6 h Datenverlust (kein WAL/PITR); ein Server ohne Hochverfügbarkeit; keine externe Sicherheitsprüfung;
nicht real geprüft: Let's-Encrypt mit echter Domain, echter S3- und SMTP-Anbieter, systemd-Timer im Betrieb.
Steuerfunktionen sind nicht enthalten (Tor S).
