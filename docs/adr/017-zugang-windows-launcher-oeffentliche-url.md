# ADR-017: Öffentliche Adresse, Windows-Launcher statt Desktop-Client, Diagnose der Erreichbarkeit

**Status:** angenommen (09.10.2026) · ergänzt ADR-013 (Oberfläche), ADR-015 (Einzelserver), ADR-016 (Launch)

## Kontext

IC WARE HQ soll unter einer festen HTTPS-Adresse von überall erreichbar sein; zusätzlich gewünscht: Start unter
Windows über Installer und Desktop-Verknüpfung. Alle Nutzer müssen dieselben zentralen Firmendaten sehen.

## Entscheidung

1. **Eine zentrale Instanz, eine Adresse.** Kein Windows-Server-Modus, keine lokale Datenbank auf Arbeitsplätzen —
   sonst entstehen getrennte Datenbestände („Insel"), Sicherung und Rechte wären nicht mehr zentral.
2. **Windows: Launcher + Inno-Setup-Installer** statt nativem Client oder Electron. Die Oberfläche ist bereits eine
   build-freie Web-App mit strenger CSP (ADR-013); ein zweiter Client verdoppelte Sicherheitsfläche und Pflege ohne
   Mehrwert. Der Launcher (Python-Standardbibliothek, mit PyInstaller gebaut) prüft vor dem Öffnen, dass unter der
   Adresse wirklich IC WARE HQ mit gültigem Zertifikat antwortet, und öffnet Edge im App-Modus. Ungültige Zertifikate
   sind ein harter Fehler. Gespeichert wird nur die Adresse.
3. **Web-App-Manifest** (`/app/manifest.webmanifest`): „App installieren" auf Desktop, Android, iOS ohne Installer.
4. **Erreichbarkeit erklärbar machen:** `deploy/hq diagnose` (und automatisch nach einem gescheiterten Start) prüft
   DNS **aller** A/AAAA-Einträge gegen die eigenen Adressen, Ports, ufw, versehentlich veröffentlichte interne Dienste,
   HTTP→HTTPS, Zertifikatsaussteller und deutet ACME-Fehlertypen (RFC 8555) aus dem Caddy-Log. Der Installer verlangt
   jetzt, dass **jeder** DNS-Eintrag auf den Server zeigt (vorher genügte einer — ein veralteter AAAA-Eintrag ließ
   Let's Encrypt scheitern).
5. **Keine Tunnel als Produktionslösung** (ngrok, Cloudflare Tunnel o. Ä.): zusätzliche Partei mit TLS-Endpunkt,
   Client-IP-Kette nicht mehr geprüft (Drosselung!). Ein CDN/Proxy davor braucht eine eigene Entscheidung.
6. **Releases:** Tag `v<version>` (= `ichq.__version__` = Launcher-Version) → CI inkl. Windows-Job → GitHub-Release
   mit Installer und SHA-256; `rc`-Versionen als Vorabversion.

## Folgen

* Client-IP: geprüft, dass gefälschtes `X-Forwarded-For` hinter Caddy wirkungslos ist (Ende-zu-Ende-Test) —
  `ICHQ_TRUSTED_PROXIES=*` bleibt nur mit Caddy direkt davor sicher.
* Installer unsigniert, bis ein Code-Signing-Zertifikat beschafft ist (SmartScreen-Hinweis).
* Ein echter Server mit echter Domain bleibt Voraussetzung; er lässt sich nicht im Repository „erzeugen".
