# IC WARE HQ Server auf dem eigenen Windows-PC (ADR-018)

Ihr PC wird der Server für alle Nutzer. Erreichbar ist IC WARE HQ unter Ihrer Domain (z. B. `https://hq.meine-firma.de`)
— von jedem Gerät, jedem Netz — über einen **Cloudflare Tunnel**: keine Portfreigabe am Router nötig, funktioniert auch
hinter CGNAT/DS-Lite.

> **Bitte vorher lesen:** Läuft der PC nicht (aus, Ruhezustand, Neustart, Internet weg), ist IC WARE HQ für alle weg.
> Cloudflare sieht den Verkehr unverschlüsselt (siehe ADR-018). Sicherung unbedingt extern einrichten (Schritt 6).

## Was Sie brauchen

| Was | Wofür |
| --- | --- |
| Windows 10 (2004+) oder 11, 64 Bit, **8 GB RAM** (besser 16), 30 GB frei, Virtualisierung im BIOS/UEFI an | Linux-Umgebung (WSL2), Datenbank, Virenscanner |
| Ein **Administratorkonto** auf dem PC (das Konto, mit dem Sie sich normalerweise anmelden) | Installation; die Server-Umgebung gehört diesem Konto |
| **Cloudflare-Konto** (kostenlos) und eine **Domain**, deren Nameserver bei Cloudflare liegen | öffentliche Adresse + Tunnel |
| optional: S3-Speicher (z. B. Hetzner Object Storage) | externe Sicherung |
| optional: SMTP-Zugang Ihres Mail-Anbieters | Einladungen, „Passwort vergessen“, Warnungen |

## Einrichtung

1. **Domain zu Cloudflare:** dash.cloudflare.com → „Add a domain“ → Nameserver beim Domain-Anbieter auf die
   angezeigten Cloudflare-Nameserver umstellen (dauert Minuten bis Stunden).
2. **Tunnel anlegen:** Zero Trust → Networks → Tunnels → „Create a tunnel“ → Cloudflared → Name z. B. `ic-ware-hq` →
   den angezeigten Befehl (`cloudflared.exe service install eyJ…`) **kopieren** (Sie brauchen nur das Token; den Befehl
   selbst nicht ausführen).
3. Im selben Tunnel → **Public Hostname** hinzufügen:
   Subdomain `hq`, Domain `meine-firma.de`, Service **Type `HTTP`**, **URL `caddy:80`** (genau so, nicht localhost).
   Empfohlen: SSL/TLS → Edge Certificates → „Always Use HTTPS“ an.
4. **`IC-WARE-HQ-Server-Setup-<version>.exe`** ausführen → Domain, Ihre E-Mail, den kopierten Befehl einfügen →
   Installieren. Ein Konsolenfenster zeigt den Fortschritt (10–20 Minuten: Ubuntu laden und prüfen, Docker,
   Datenbank, Virenscanner, Tunnel). Fehlt WSL noch, verlangt Windows **einen Neustart**; danach läuft es von selbst weiter.
   Den angezeigten **SICHERUNGSSCHLÜSSEL** sofort im Passwortmanager ablegen.
5. Startmenü → **IC WARE HQ Server → Erste Firma anlegen**, dann **Diagnose** — alles `OK`?
   Danach vom **Handy ohne WLAN** `https://hq.meine-firma.de` öffnen: Erst das beweist die Erreichbarkeit für alle.
6. Startmenü → **Externe Sicherung (S3) einrichten** (sonst liegt die Sicherung nur auf diesem PC) und
   **E-Mail-Versand einrichten**.

## Bedienung (Startmenü „IC WARE HQ Server“)

| Eintrag | Wirkung |
| --- | --- |
| IC WARE HQ öffnen | Browser mit Ihrer Domain |
| Status / Betriebsprüfung / Diagnose | Dienste · Prüfung mit Warnungen · Warum nicht erreichbar? (Tunnel, Token, Hostname) |
| **Domain ändern** | neue Domain: erst in Cloudflare den Public Hostname ändern, dann hier bestätigen — App, Mail-Links und Proxy ziehen mit |
| Cloudflare-Token ändern | nach „Refresh token“ in Cloudflare |
| Sicherung jetzt + Wiederherstellungstest | sofortige Sicherung, danach Probe-Wiederherstellung |
| Server starten / stoppen, Logs | |
| Einrichtung wiederholen | nach einem Fehler; Daten bleiben |

Updates: neue `IC-WARE-HQ-Server-Setup-<version>.exe` ausführen (Token-Feld leer lassen) — sichert vorher automatisch.
Andere PCs der Firma brauchen nichts davon: Browser oder der kleine Zugangs-Installer (`docs/windows.md`).

**Domain ändern — was passiert:** Nutzer melden sich unter der neuen Adresse neu an (Sitzungen gelten je Domain);
vorher verschickte Einladungs-/Reset-Links zeigen auf die alte Adresse. Die alte Adresse in Cloudflare danach entfernen.

## Deinstallation

Systemsteuerung → Programme → „IC WARE HQ Server“. Frage „ALLE DATEN löschen?“ — **Nein** (Standard): Daten bleiben
in `C:\ProgramData\IC-WARE-HQ\wsl`, eine Neuinstallation übernimmt sie. **Ja:** endgültig gelöscht.

## Fehlerbehebung

| Meldung (Diagnose) | Abhilfe |
| --- | --- |
| `Cloudflare lehnt das Tunnel-Token ab` | Token neu kopieren → „Cloudflare-Token ändern“ |
| `Tunnel verbunden, aber Dienst falsch eingetragen` | Public Hostname: Type HTTP, URL `caddy:80` |
| `Cloudflare kennt die Domain, der Tunnel ist aber nicht verbunden` | PC/Internet an? „Server starten“ |
| `antwortet mit HTTP 404` | Hostname in Cloudflare ≠ Domain hier → „Domain ändern“ oder Hostname anpassen |
| Installer: „wsl --install scheiterte“ | Virtualisierung im BIOS/UEFI aktivieren (Intel VT-x / AMD-V) |
| Installer: „Prüfsumme falsch“ | Download beschädigt oder verändert — erneut versuchen; nie eine fremde Datei nehmen |
| Protokoll der Einrichtung | `C:\ProgramData\IC-WARE-HQ\einrichten.log` |

## Geprüft (ehrlich)

* **Automatisch (CI):** Bau des Server-Installers auf windows-latest; alle Server-Skripte von **Windows PowerShell 5.1**
  fehlerfrei lesbar; PSScriptAnalyzer; Pester (Eingaben, Prüfsumme, Pfade, Skript-Übergabe an Linux über STDIN mit
  CRLF, Token nie in einer Kommandozeile, `-NurPruefen`). Linux: Tunnel-Client-IP-Kette live (`deploy/tunnel-proxy-test.sh`).
* **Von Hand in der Testumgebung (10.10.2026):** `install.sh --tunnel` mit `cloudflared 2026.9.3` (Token aus Datei,
  ungültiges Token korrekt erkannt), Caddy nur auf 127.0.0.1, `hq domain` (App-Origin und Proxy umgestellt),
  Rückwechsel `--no-tunnel`; Ubuntu-Datei vollständig geladen, SHA-256 stimmt, Prüfsummenliste mit Ubuntu-Schlüssel
  verifiziert, enthält alle benötigten Werkzeuge.
* **Simulation des Linux-Teils (10.10.2026):** genau das Ubuntu-Abbild des Installers (24.04.5, Prüfsumme geprüft) als
  Container mit systemd; dieselben Befehle wie `einrichten.ps1`, mit Windows-Zeilenenden über STDIN: Docker per apt aus
  download.docker.com installiert, Image gebaut, alle 7 Dienste gesund, Caddy nur auf 127.0.0.1, systemd-Zeitpläne
  aktiv, „Erste Firma anlegen“ → Anmeldung 200, „Domain ändern“ → Anmeldung unter neuer Domain 200, Sicherung ok.
  Dabei gefunden und behoben: „Erste Firma anlegen“ brach still ab, wenn die letzte Eingabe keinen Zeilenumbruch hatte.
* **Nicht geprüft:** Installation auf einem echten Windows-PC (WSL2-Einrichtung, Neustart-Fortsetzung, Autostart
  ohne Anmeldung per S4U, Energieeinstellungen, Deinstallation), echter Cloudflare-Tunnel mit echter Domain.
