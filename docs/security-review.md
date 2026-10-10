# Sicherheitsprüfung vor dem Launch (09.10.2026)

Zwei unabhängige Prüfungen des Codes (Lesen + reproduzierende Wegwerf-Tests) und Erkenntnisse aus den Live-Tests.
**Keine externe Prüfung** — das ersetzt keinen Penetrationstest durch Dritte (CLAUDE.md: „Vorschlag, nicht Entscheidung").
Jeder behobene Befund hat einen Regressionstest (`tests/test_security_launch.py`, sonst angegeben) und eine Mutation
in `scripts/mutation-check.sh`, die ihn rot macht.

## Befunde und Stand

| # | Schwere | Befund | Stand |
| --- | --- | --- | --- |
| F1 | hoch | 2FA durchprobierbar: Grenze galt nur je Challenge; richtiges Passwort setzte Zähler zurück | **behoben** — Fehlversuche je Konto in `login_attempts` (`kind='mfa'`), vor der Prüfung gedrosselt |
| F2 | hoch | MFA-Zähler aus veralteter Sitzung, widerrufene Challenge nicht neu geprüft (parallele Anfragen) | **behoben** — atomares `mfa_attempts + 1 RETURNING`, Challenge nach der Sperre neu gelesen |
| F3 | mittel | Passwort-Reset hob eine Betreiber-Sperre auf | **behoben** — nur automatische Sperre (mit Ablauf) endet; zweite Linie in `_setze_passwort` |
| F4 | mittel | Passwort-Orakel hinter einer Sitzung (2FA-Einrichtung, Passwort ändern) ohne Drossel | **behoben** — gedrosselt je Konto, Missbrauch beendet die Sitzung |
| B1 | mittel | Wiedereintritt nach Austritt brachte alte Rollen (bis Company Admin) zurück — Einladen braucht nur `users.create` | **behoben** — Rollen, Einzelrechte, manuelle Freigaben werden beim Reaktivieren entfernt |
| F5 | niedrig | Kontosperre per bekanntem Login-Namen auslösbar (DoS) | **offen, bewusst** — Abwägung gegen Durchprobieren; Sperre endet nach 15 min, Betroffene bekommen eine Mail |
| F6 | niedrig | Einladung kürzte Leerzeichen am Passwortrand | **behoben** |
| F7 | niedrig | Wettlauf beim Annehmen hinterließ aktives Konto ohne Firma | **behoben** — Vorprüfung, Rücknahme, Rest wiederverwendbar |
| F8 | info | 2FA-Abschalten beendete andere Sitzungen nicht, keine Benachrichtigung | **behoben** — Sitzungen enden, Sicherheitshinweis per Mail |
| B2 | niedrig | Uploads unbegrenzt (Speicher, Scanner) | **behoben** — 20 GiB je Firma, 200 Uploads/h je Mitglied. Offen: Upload wird im Speicher gepuffert (max. 20 MiB) |
| B3 | niedrig | `/health`, `/readiness` öffentlich, schreiben bei jedem Aufruf in den Speicher | **behoben** — Speicherprüfung 5 s gecacht |
| B4 | niedrig | Paging-Cursor enthielt interne UUID | **behoben** — AES-GCM-verschlüsselt, Manipulation abgewiesen |
| B5 | niedrig | Beleg-Freigabe ohne Virenprüfung; Selbstprüfung unsichtbar | **behoben** — Freigabe erst nach `clean`; Selbstprüfung im Audit markiert (Ein-Personen-Firma: nicht verboten) |
| B6 | info | `ICHQ_TRUSTED_PROXIES=*` | **dokumentiert** — sicher, solange Caddy `X-Forwarded-For` überschreibt (Standard) |
| B7 | info | Wiederherstellung entpackte ungeprüftes Archiv als root | **behoben** — restic (authentifiziert verschlüsselt), Prüfsummen, Inhalt von `secrets.tar` vor dem Entpacken geprüft |
| B8 | info | Installer: einige Eingaben ungeprüft | **behoben** — strenge Zeichenlisten für alle Werte, die in `.env`/Caddyfile/Units landen |
| B9 | info | Keine DB-Prüfung, dass `storage_key` zur Firma passt | **offen** — App-Rolle kann `storage_key` nicht ändern; nur Server schreibt ihn |
| L1 | — | Live-Test: Mail-Outbox `ON CONFLICT (spalte)` verlangt SELECT-Recht | behoben (vor Auslieferung) |
| L2 | hoch | Live-Test: Prüf-/Sicherungsskript meldete „ok", obwohl `pg_restore` scheiterte (`set -e` im `if`) | **behoben** — eigener Prozess; Test + Mutation |
| L3 | mittel | Live-Test: falscher Sicherungsschlüssel ⇒ Versuch, das Repository neu anzulegen | **behoben** — Anlegen nur bei nachgewiesenem Fehlen |
| L4 | — | Live-Test: Web-App-Rolle durfte Scan-Ergebnis schreiben (Migration 0007, erster Entwurf) | behoben vor Merge — nur `ichq_worker` |

## Geprüft und in Ordnung (Auszug)
Sitzungs-Cookies (HttpOnly, SameSite=Lax, `__Host-`/Secure in Produktion), Rotation bei Login/MFA/Firmenwahl/
Passwortwechsel, Leerlauf- und absolute Grenze serverseitig, Kontostatus je Anfrage; Tokens 256 Bit, nur als Hash,
einmalig, befristet, im URL-Fragment; keine Konto-Enumeration; Argon2id; TOTP verschlüsselt mit
Wiederverwendungsschutz; CSRF über Origin-Prüfung + SameSite; keine CORS-Freigaben; CSP ohne `unsafe-inline`;
jede der 85 Routen mit genau einer Sicherheitsmarke; keine Route nimmt die Firma aus der Anfrage; IDOR über alle
Pfad-IDs (Generator-Test); SQL nur gebunden, Sortierungen per Whitelist; keine `innerHTML`-Nutzung; Upload-Typ-
Whitelist, Download als `attachment` + `nosniff`, Quarantäne auf dem einzigen Download-Weg; kein `subprocess`,
kein ausgehendes HTTP aus der App.
