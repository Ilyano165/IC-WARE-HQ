# ADR-018: Server auf einem Windows-PC, öffentlich über Cloudflare Tunnel, Domain änderbar

**Status:** angenommen (10.10.2026) · ergänzt ADR-015/016/017 · **ändert ADR-017, Punkt 5** („keine Tunnel“) für
diesen Betriebsweg, auf ausdrücklichen Wunsch des Betreibers.

## Kontext

Der Betreiber will keinen gemieteten Server, sondern seinen **privaten Windows-PC** als zentrale Instanz nutzen —
erreichbar für alle Nutzer über eine feste HTTPS-Adresse, ohne Portfreigabe am Router (Heimanschlüsse haben oft
CGNAT/DS-Lite, dann geht Portfreigabe gar nicht). Die Domain soll später änderbar sein.

## Entscheidung

1. **Kein zweiter, Windows-eigener Server-Stack.** Der Windows-Installer legt eine eigene WSL2-Distribution
   „IC-WARE-HQ“ an (Ubuntu 24.04.5 von ubuntu.com, SHA-256 fest im Installer, Prüfsummenliste mit dem
   Ubuntu-Archivschlüssel verifiziert) und führt darin den **geprüften Linux-Weg** aus (`deploy/install.sh`, Docker,
   systemd-Timer für Sicherung und Prüfung). Docker Desktop wird nicht benötigt (Lizenzfrage, zweite Konfiguration).
2. **Cloudflare Tunnel** (`cloudflared` als Container, Version fest, Token als Secret-Datei mit UID 65532): ausgehende
   Verbindung, kein offener Port. `cloudflared` liegt in einem eigenen Netz und sieht **nur Caddy**, nie App oder
   Datenbank. Caddy veröffentlicht im Tunnelbetrieb nur auf 127.0.0.1.
3. **Client-IP bleibt fälschungssicher:** Caddy übernimmt `Cf-Connecting-Ip` nur von der festen Adresse von
   `cloudflared` (`trusted_proxies static 172.31.250.10/32`) und reicht der App genau **eine** Adresse weiter
   (`header_up X-Forwarded-For {client_ip}`). Ohne das teilten sich alle Besucher eine IP (Drosselung gegen
   Passwort-Raten wirkte global) oder sie wäre über `X-Forwarded-For` fälschbar.
4. **Domain ändern:** `deploy/hq domain <neu>` (Windows: Startmenü „Domain ändern“) — prüft die Eingabe streng (sie
   landet im Caddyfile), führt durch den einen Schritt in Cloudflare und startet App (Origin, Mail-Links) und Caddy mit
   der neuen Domain. Gleiches Muster für das Token (`deploy/hq tunnel-token`).
5. **Daten bleiben bei Deinstallation**, außer der Betreiber wählt ausdrücklich „alle Daten löschen“
   (Standard-Knopf: Nein; stille Deinstallation löscht nie).
6. Autostart: geplante Aufgabe hält die WSL-Distribution am Leben (beim Start ohne Anmeldung per S4U und bei der
   Anmeldung); systemd in WSL startet Docker und den Stack (`restart: unless-stopped`).

## Folgen (ehrlich)

* **Cloudflare beendet TLS und sieht den Verkehr im Klartext** (Passwörter bei der Anmeldung, Dokumente). Das ist
  der Preis dafür, ohne offenen Port erreichbar zu sein. Für Firmendaten: Cloudflare-Auftragsverarbeitung (DPA)
  prüfen und dokumentieren. Wer das nicht will, nimmt den Direktbetrieb (ADR-015) mit eigenem Server.
* **Verfügbarkeit = der PC.** Ausgeschaltet, im Ruhezustand, Windows-Update-Neustart, Stromausfall, Internetausfall ⇒
  IC WARE HQ ist für alle weg. Der Installer kann den Energiesparmodus im Netzbetrieb abschalten.
* **Sicherung:** ohne „Externe Sicherung (S3) einrichten“ liegt sie auf demselben PC — ein Plattenschaden nimmt sie mit.
  `hq check` warnt dauerhaft, bis ein externes Ziel eingerichtet ist.
* Upload-Bandbreite des Heimanschlusses begrenzt Downloads für entfernte Nutzer.
* **Nicht in CI prüfbar:** WSL2 läuft auf GitHub-Windows-Runnern nicht (keine verschachtelte Virtualisierung).
  Geprüft sind: Linux-Teil (Tunnelmodus, Client-IP-Kette live, Moduswechsel, Domainwechsel), PowerShell-Logik
  (Pester), Lesbarkeit für Windows PowerShell 5.1, Installer-Bau. Eine Installation auf einem echten Windows-PC fehlt.
