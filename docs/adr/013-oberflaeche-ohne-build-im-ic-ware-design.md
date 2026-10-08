# ADR-013: Oberfläche (U1/M5) — build-freie App auf der JSON-API, IC-Ware-Design

**Status:** angenommen (U1) · **Löst:** ADR-004 („HTMX oder React") · **Auftrag:** „nutz die typische IC-Ware-UI
und arbeite weiter" (08.10.2026)

## Kontext
ADR-004 ließ offen: serverseitiges Rendering mit HTMX oder React-SPA. Seit M1 liegt die gesamte Sicherheit in der
API (`/api/v1`, eine Sicherheitsmarke je Route, Rechte in der Service-Schicht, IDOR-Generator, 121 Mutationen).
Das Team sind zwei Personen. Die „typische IC-Ware-UI" ist das Design der Website (`Ilyano165/ic-ware.v2`):
dunkel (`#060708`), **Spring Green `#19E56E` als einzige Farbe**, Inter Tight / Inter **selbst gehostet**
(DSGVO, keine externen Dienste), runde Pillen-Buttons, Glasflächen, das IC-Logo als SVG.

## Entscheidung
**Weder HTMX noch React**, sondern eine **build-freie Single-Page-App aus nativen ES-Modulen**:

- Ausgeliefert von derselben App unter `/app/` (eine Route mit Marke `public` — statische Dateien sind keine Daten),
  `/` leitet dorthin. Gleiche Herkunft → Sitzungs-Cookie (`HttpOnly`, `SameSite=Lax`) und Origin-Schutz wirken
  unverändert, keine CORS-Öffnung.
- Die App spricht **ausschließlich** mit `/api/v1`. Es gibt keine zweite, HTML-erzeugende Schicht, die eigene
  Sicherheitsregeln bräuchte. Was die Oberfläche ausblendet, prüft trotzdem der Server.
- **Kein Build, kein npm im Produkt:** keine Abhängigkeitskette aus dem npm-Ökosystem, nichts zu kompilieren;
  das Docker-Image bleibt reines Python. (Playwright dient nur den Tests.)
- **Strenge CSP:** `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self';
  frame-ancestors 'none'; base-uri 'none'; form-action 'self'` — keine Inline-Skripte, keine Inline-Styles.
- **XSS-Regel:** Serverdaten werden nur als Text in DOM-Knoten gesetzt (`textContent` über `h()`); `innerHTML`,
  `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, `new Function` sind im App-Code verboten
  (Test durchsucht alle Dateien).
- **Design-Tokens** der IC-Ware-Website (`tokens.css`), Schriften als WOFF2 im Paket (SIL OFL 1.1, Lizenz liegt bei).
  Die Website ist eine Marketingseite; für ein Arbeitswerkzeug gelten dieselben Tokens, aber ruhiger: keine
  Animationen ohne Funktion, `prefers-reduced-motion` wird beachtet, Kontrast mindestens WCAG AA.
- **Mobil nutzbar** (Vision: „mobil nutzbar"): Navigation als Leiste ab 900 px, darunter als Schublade; kein
  horizontales Scrollen bei 360 px (Test).
- Routing über das Fragment (`#/aufgaben`) — der Server muss keine App-Pfade kennen, Tokens (Reset, Einladung)
  bleiben im Fragment und damit aus Serverlogs (wie M2/M3).

## Verworfen
- **HTMX + Jinja:** zweite Ausgabeschicht neben der API; jede HTML-Route bräuchte Marke, Rechteprüfung und
  IDOR-Abdeckung zusätzlich — doppelte Angriffsfläche für zwei Personen.
- **React/Vite-SPA:** Build-Kette und npm-Abhängigkeiten (Lieferkettenrisiko, Updates, Audit) für Funktionen, die
  mit nativen Modulen auskommen. Kann später kommen, wenn die Oberfläche es wirklich verlangt — die API bleibt gleich.

## Folgen
- Mehr Handarbeit beim Rendern (kleiner `h()`-Baustein statt Framework). Dafür jede Zeile prüfbar.
- E2E-Tests mit echtem Chromium (Playwright) gegen echten uvicorn-Prozess; CI installiert Chromium.
- QR-Code für 2FA-Einrichtung: vorerst nur Schlüssel und `otpauth://`-Link (kein QR-Generator ohne Bibliothek).
- `docs/ui.md` beschreibt Aufbau, Regeln und Grenzen.
