# Oberfläche (U1 / M5 UI-Shell)

Entscheidung und Begründung: [ADR-013](adr/013-oberflaeche-ohne-build-im-ic-ware-design.md). Code: `src/ichq/web/`
(statische Dateien), Auslieferung `src/ichq/api/ui.py`.

## Aufbau
```
web/index.html          einzige HTML-Datei, lädt css/ und js/app.js (Modul) — keine Inline-Skripte/-Styles
web/css/tokens.css      IC-Ware-Design-Tokens + Schriften (aus Ilyano165/ic-ware.v2)
web/css/app.css         Layout (Seitenleiste, Kopfzeile, Karten, Tabellen, Formulare, Dialog, Mobil)
web/fonts/              Inter / Inter Tight (WOFF2) + OFL.txt
web/js/dom.js           h() — baut DOM, Text NUR als Textknoten; Dialog, Meldungen, Formatierung
web/js/api.js           einziger Serverzugang (/api/v1, Cookie, RFC-9457-Fehler → ApiError)
web/js/router.js        Fragment-Routing (#/aufgaben/…)
web/js/state.js         Sitzung, Rechte (nur zur Anzeige)
web/js/app.js           Start, Shell, Navigation nach Rechten, Routen
web/js/views/*.js       anmeldung, uebersicht, aufgaben, kommentare, dokumente, inbox (Mitteilungen, Suche),
                        mitglieder (inkl. Rechte einer Person), rollen (Matrix-Editor), verwaltung (Firma,
                        Aktivität, Audit), konto (Passwort, 2FA, Sitzungen)
```

## Seiten
| Pfad | Inhalt | Recht (Anzeige; der Server prüft selbst) |
| --- | --- | --- |
| Anmeldung | Login, 2FA-Code/Recovery-Code, Passwort vergessen, Firmenwahl (bei einer Firma automatisch) | — |
| `/invite#token=…`, `/reset#token=…` | Einladung annehmen (neues oder bestehendes Konto), neues Passwort | Token |
| `#/` | Dashboard (D0, `docs/d0-dashboard.md`): Widgets nach effektiven Rechten, jede verlinkte Zahl = Liste | — |
| `#/aufgaben`, `#/aufgaben/:id` | Liste mit Filtern/Seiten, anlegen, bearbeiten, Status, Zuweisung, Anhänge (Dokumente), Kommentare | `tasks.read` |
| `#/dokumente`, `#/dokumente/:id` | Liste, Hochladen, Quarantäne-Hinweis, Download nach Prüfung, Freigeben/Ablehnen, Kommentare | `files.read` |
| `#/benachrichtigungen`, `#/suche` | Mitteilungen (gelesen markieren), globale Suche gruppiert | — |
| `#/mitglieder`, `#/mitglieder/:id` | Mitglieder, Einladungen; Person: Rollen vergeben/entziehen, **Rechte mit Quelle**, Einzelrechte, deaktivieren | `users.read` |
| `#/rollen`, `#/rollen/:id` | Rollen, anlegen, Matrix-Editor (gelb = kritisch, grau = selbst nicht vorhanden), duplizieren, archivieren | `roles.read` |
| `#/firma`, `#/aktivitaet`, `#/audit` | Firmenprofil, Verlauf, Audit (Filter, CSV-Export mit `audit.export`) | jeweils Modulrecht |
| `#/konto` | Passwort, 2FA einrichten/ausschalten, Recovery-Codes, überall abmelden, Firma verlassen | — |

## Regeln (Tests in `tests/test_u1_static.py`)
- Serverdaten nur als Text: `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, `new Function`,
  `on…=`-Zuweisungen sind im App-Code verboten.
- Keine externen Adressen in JS/CSS, keine `@import`, keine Inline-Skripte/-Styles (CSP `script-src 'self'; style-src 'self'`).
- Jede JS-Datei ≤ 400 Zeilen, Syntax wird mit `node --check` geprüft (wenn Node vorhanden).
- Auslieferung nur aus `ichq/web`, nur bekannte Dateitypen, kein `..`, Symlinks nach draußen → 404.
- Die API behält ihre eigene CSP (`default-src 'none'`); die Middleware setzt Standard-Header nur, wo eine Antwort
  keine eigenen hat.

## Tests im Browser (`tests/test_u1_browser.py`)
Chromium über Playwright gegen einen echten `ichq serve`-Prozess: Login (falsch/richtig), Navigation nach Rechten
(Admin vs. Mitarbeiter), Direktaufruf ohne Recht (Oberfläche **und** Server lehnen ab), Aufgabe anlegen/kommentieren/
erledigen mit XSS-Nutzlast im Titel, Einzelrecht über die Oberfläche setzen (Wirkung auf dem Server geprüft), gesperrte
Rolle nicht bearbeitbar, Mobil 360 px ohne Querscrollen, **jede CSP-Verletzung oder JS-Fehler lässt den Test scheitern**.

Lokal: `pip install playwright==1.56.0` (Browser: vorinstalliert oder `python -m playwright install chromium`).
Ohne Playwright werden die Browsertests übersprungen — in CI laufen sie immer.

## Bekannte Grenzen
- 2FA-Einrichtung zeigt Schlüssel und `otpauth://`-Link, **keinen QR-Code** (kein QR-Generator ohne Bibliothek).
- 2FA-Login im Browser ist nicht als Browsertest abgedeckt (TOTP-Zeitfenster); die API-Tests decken ihn ab.
- Keine Offline-Fähigkeit, keine Barrierefreiheits-Prüfung mit Werkzeug (nur semantische Rollen/Labels, die die Tests nutzen).
- Objekt-Freigaben/-Sperren und Verknüpfungen haben noch keine Oberfläche (API vorhanden).
- Kein Dashboard (D0), keine Fachmodule (S1–S8).
