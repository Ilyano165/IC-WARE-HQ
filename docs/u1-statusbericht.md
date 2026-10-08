# U1 · Oberfläche (M5 UI-Shell) — Statusbericht (08.10.2026)

Auftrag: „nutz die typische IC-Ware-UI und arbeite weiter". Entscheidung: [ADR-013](adr/013-oberflaeche-ohne-build-im-ic-ware-design.md)
(löst ADR-004). Beschreibung: [docs/ui.md](ui.md).

## Implemented
- **Technik:** build-freie Single-Page-App aus nativen ES-Modulen unter `/app/`, ausgeliefert von derselben App
  (Marke `public`), spricht nur `/api/v1`. Kein npm, kein Build, Docker-Image bleibt reines Python.
- **Design:** Tokens, Logo und Schriften der IC-Ware-Website (`Ilyano165/ic-ware.v2`): `#060708`, Spring Green
  `#19E56E` als einzige Akzentfarbe, Inter Tight / Inter selbst gehostet (OFL-Lizenz liegt bei), Pillen-Buttons,
  Glasflächen. Für ein Arbeitswerkzeug ruhiger (keine Zieranimationen, `prefers-reduced-motion`).
- **Seiten:** Anmeldung, 2FA, Passwort vergessen/neu, Firmenwahl, Einladung (neues/bestehendes Konto), Übersicht
  (eigene Aufgaben, Mitteilungen — kein Dashboard), Aufgaben, Kommentare (inkl. Löschen mit Grund), Dokumente
  (Hochladen, Quarantäne, Prüfen), Mitteilungen, Suche, Mitglieder + Einladungen, **Rechte einer Person mit Quelle**
  und Einzelrechten, Rollen-Matrix-Editor, Firma, Aktivität, Audit (+CSV), Konto & Sicherheit (Passwort, 2FA,
  Recovery-Codes, überall abmelden, Firma verlassen). Mobil nutzbar (Schubladen-Navigation unter 900 px).
- **Sicherheit:** CSP ohne Inline-Skripte/-Styles, kein Einbetten, `nosniff`, `no-referrer`; Auslieferung nur aus
  `ichq/web`, nur bekannte Typen, Pfad-Regex + Symlink-Prüfung; Serverdaten nur als Text (HTML-APIs verboten,
  per Test); Tokens aus Mail-Links bleiben im Fragment (Weiterleitung `/invite`, `/reset`).
- **Nebenbei behoben:** Die Middleware hätte eine zweite CSP (`default-src 'none'`) angehängt — beide gelten im
  Browser, die App wäre leer geblieben. Standard-Header jetzt nur, wo die Antwort keine eigenen setzt.

## Tested (lokal, PostgreSQL 16 + Chromium 141 über Playwright 1.56)
| Prüfung | Ergebnis |
| --- | --- |
| pytest gesamt | siehe Commit-Nachricht des Abschluss-Commits |
| `test_u1_static.py` | Weiterleitungen, Header, 12 Ausbruchspfade, Dateitypen, Symlink, Code-Regeln, JS-Syntax (`node --check`) |
| `test_u1_browser.py` | 5 Tests im echten Browser; 15 Wiederholungen der Datei ohne Fehlschlag (75 Läufe) |
| U1-Mutationen | 8 (Pfad-Regex, Symlink, Dateitypen, Header, zwei CSP, Text als HTML, Navigation ohne Rechtefilter, veraltete Ansicht) |

**Durch Tests gefundene Fehler:**
1. CI-Lauf 8 rot: Der Browsertest bediente nach einem Seitenwechsel noch ein Feld der alten Seite (Testfehler,
   behoben in `adf7c42`).
2. **Echter App-Fehler** bei der Suche nach einem seltenen Fehlschlag: Wer schnell die Seite wechselte, konnte
   eine verspätet ladende alte Seite über der neuen sehen. Behoben (eigener Container je Seitenwechsel), mit
   Regressionstest (verzögerte Antwort, rot ohne Fix, grün mit Fix) und Mutation.

## Not Tested
- 2FA-Anmeldung im Browser (TOTP-Zeitfenster) — über die API getestet.
- Barrierefreiheit mit Prüfwerkzeug (axe o. ä.); vorhanden sind semantische Rollen/Labels, die die Tests nutzen.
- Andere Browser als Chromium (Firefox, Safari).
- Hochladen über den Dateidialog im Browser (die Upload-API ist getestet).

## Known Issues / Grenzen
- Kein QR-Code bei der 2FA-Einrichtung (Schlüssel + `otpauth://`-Link).
- Freigaben/Sperren einzelner Objekte und Verknüpfungen haben noch keine Oberfläche (API vorhanden).
- Kein Dashboard (D0), keine Fachmodule (S1–S8) — nächste Schritte laut Reihenfolge.

## Security Review (eigene Durchsicht)
- Keine neue Datenroute; jede Entscheidung bleibt im Server. Ausblenden in der Navigation ist nur Komfort
  (Test: Direktaufruf ohne Recht → Oberfläche „Keine Berechtigung" **und** API 403).
- XSS: Nutzlast in Titel, Beschreibung, Kommentar wird als Text angezeigt; CSP blockiert zusätzlich Inline-Code.
- Offen: kein externer Pentest; CSP-Berichte (report-to) nicht eingerichtet.
