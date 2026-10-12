# ADR-019: Schnellstart ohne Cloudflare-Konto (zufällige Adresse)

**Status:** angenommen (12.10.2026) · ergänzt ADR-018 (Server auf Windows-PC mit Cloudflare Tunnel)

## Kontext

Der Betreiber möchte IC WARE HQ auch **ohne Cloudflare-Konto und ohne eigene Domain** starten können, mit einer
zufälligen Adresse.

## Entscheidung

1. **Cloudflare Quick Tunnel** (`cloudflared tunnel --url http://caddy:80`, Dienst `cloudflared-schnell`, Profil
   `schnell`): kein Konto, kein Token, Adresse `https://<wort-wort-…>.trycloudflare.com`. Selbe feste Netzadresse wie
   `cloudflared` ⇒ die fälschungssichere Besucher-IP aus ADR-018 gilt unverändert (`Caddyfile.tunnel`).
2. **Die Adresse wird nachgeführt:** `deploy/hq adresse` (systemd-Timer jede Minute, außerdem nach jedem Start und vor
   jeder Betriebsprüfung) liest die Adresse **nur aus Cloudflares Erfolgsmeldung** im Log („Your quick Tunnel has been
   created“ — die Zeile im Kasten), prüft sie streng und setzt sie als `ICHQ_DOMAIN`. Neu erzeugt werden nur App,
   Worker, Jobs, Scanner und Caddy (`--no-deps`) — **nie** `cloudflared-schnell`, sonst gäbe es sofort wieder eine neue
   Adresse. Bei einer neuen Adresse geht eine Mail an die Betreiber-Adresse.
3. Windows-Installer: erste Seite „Schnellstart ohne Konto“ oder „Eigene Domain“. Startmenü „Adresse anzeigen“
   (kopiert sie zum Weitergeben); „Domain ändern“ bietet im Schnellstart den Umstieg auf eigene Domain + Konto an.
4. `deploy/hq domain` lehnt im Schnellstart ab (die Adresse ist nicht wählbar) und nennt den Umstieg.

## Folgen (ehrlich)

* **Die Adresse ändert sich bei jedem Neustart des Tunnels** (PC-Neustart, Windows-Update, Docker-Neustart, Absturz).
  Alle Nutzer brauchen dann die neue Adresse; Anmeldungen gelten je Adresse (neu anmelden); früher verschickte
  Einladungs-/Reset-Links und gespeicherte Adressen (z. B. im Windows-Launcher anderer PCs) zeigen ins Leere.
* Laut Cloudflare (Stand 10/2026): **keine Verfügbarkeitsgarantie**, nur für Tests/Entwicklung gedacht, höchstens
  **200 gleichzeitige Anfragen** (danach HTTP 429), kein Server-Sent Events (nutzt die App nicht). Cloudflare kann die
  Nutzung im Rahmen seiner Nutzungsbedingungen prüfen.
* Wie bei ADR-018 beendet Cloudflare TLS und sieht den Verkehr im Klartext.
* **Für echte Firmendaten nicht empfohlen** — der Schnellstart ist zum Ausprobieren. Umstieg jederzeit ohne
  Datenverlust (`install.sh --domain … --tunnel` bzw. Startmenü „Domain ändern“).
* **Nicht live geprüft:** ein echter Quick Tunnel (die Testumgebung kann trycloudflare.com nicht erreichen). Geprüft:
  Erkennung der Adresse (auch der Fehlerfall `api.trycloudflare.com`, im Live-Test gefunden), Nachführen mit echtem
  Stack (App-Origin und Caddy umgestellt, Tunnel-Container unverändert, Anmeldung lokal 200), Ablehnung von
  `hq domain`, Moduswechsel.
