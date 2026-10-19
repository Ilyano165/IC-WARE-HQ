# Windows-Installer und Desktop-Launcher (ADR-017)

**Was er ist:** ein Zugang zur **zentralen** IC-WARE-HQ-Instanz der Firma, mit Startmenü-Eintrag,
Desktop-Verknüpfung und einem eigenen Fenster (Microsoft Edge im App-Modus).
**Was er nicht ist:** kein Server, keine Datenbank, keine Kopie von Firmendaten. Auf dem PC liegt nur die Adresse der
Instanz (`%APPDATA%\IC WARE HQ\launcher.json`). Alle Nutzer arbeiten mit denselben Daten auf dem Server.

## Installieren

1. `IC-WARE-HQ-Setup-<version>.exe` ausführen (keine Administratorrechte nötig — installiert ins Benutzerprofil;
   Administratoren können „für alle Benutzer" wählen).
2. Adresse der Firma eingeben (z. B. `hq.ihre-firma.de`) oder leer lassen — dann fragt der Launcher beim ersten Start.
3. Startmenü → **IC WARE HQ** → Anmeldeseite der Firma. Adresse später ändern: Startmenü → „IC WARE HQ – Adresse ändern".

**Verteilung an viele PCs** (stille Installation mit vorgegebener Adresse):

```
IC-WARE-HQ-Setup-<version>.exe /VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER /URL=https://hq.ihre-firma.de
```

Prüfsumme: Neben jedem Installer liegt `…exe.sha256` (`Get-FileHash … -Algorithm SHA256`).

## Was der Launcher prüft (vor dem Öffnen)

| Lage | Meldung / Verhalten |
| --- | --- |
| Adresse ohne `https://`, mit Pfad, mit Zugangsdaten, `http://` (außer localhost) | abgelehnt mit Erklärung |
| Domain existiert nicht | „Die Adresse wurde nicht gefunden …" — Angebot, eine andere Adresse einzugeben |
| Server antwortet nicht | „Der Server antwortet nicht …" |
| **Zertifikat ungültig** | Abbruch, **kein** „trotzdem öffnen" (Schutz vor Abhören) |
| andere Webseite / Weiterleitung woandershin | „Unter dieser Adresse läuft kein IC WARE HQ" |
| Server meldet Störung | Hinweis, App öffnet trotzdem |
| Server wurde aktualisiert | einmaliger Hinweis „auf Version X aktualisiert" |

Updates der Anwendung kommen **zentral** mit dem Server-Update (`deploy/hq update`) — für alle Nutzer sofort, ohne
etwas auf den PCs zu installieren. Der Launcher selbst ändert sich selten; eine neue Version installiert man über die
alte (Einstellungen bleiben).

Kommandozeile (für Administratoren; Exitcodes, keine Fenster): `ichq-launcher.exe --check URL` (0 = IC WARE HQ
erreichbar, 1 = nicht, 2 = Adresse ungültig), `--set-url URL`, `--adresse`, `--vergessen`, `--version`.

## Bauen

Automatisch: GitHub Actions, Workflow `Windows-Installer` (bei jedem PR über CI; bei Tag `v<version>` zusätzlich
GitHub-Release mit Installer + SHA-256). Ergebnis als Artefakt `IC-WARE-HQ-Windows-Installer` des Laufs.
Von Hand auf einem Windows-PC mit Python 3.12: `powershell -ExecutionPolicy Bypass -File windows\build.ps1`.

Bausteine: `windows/launcher/` (Python, nur Standardbibliothek), PyInstaller (gepinnt mit Hashes,
`windows/requirements-build.lock`), Inno Setup 6 (`windows/installer/ichq.iss`). Version = `src/ichq/__init__.py`;
weicht der Launcher ab, bricht der Bau ab.

## Geprüft

* `tests/test_windows_launcher.py` (Linux, bei jedem CI-Lauf): Erkennung des **echten** Servers (uvicorn-Prozess) und
  echte Gegenproben — fremde Webseite, `/health` eines anderen Dienstes, Weiterleitung auf eine nachgemachte Antwort,
  selbstsigniertes Zertifikat, kein Dienst, unbekannte Domain; Adressregeln; Einstellungen. Mutationen in
  `scripts/mutation-check.sh` (`mutation_windows`).
* `windows/test-installer.ps1` (CI-Job `windows`, echter Windows-Runner): stille Installation mit `/URL=`, Dateien,
  Startmenü, Desktop, keine Datenbank, Launcher-Kommandozeile (Ablehnungen, fremde Seite, ungültiges Zertifikat),
  Deinstallation.

## Grenzen (ehrlich)

* **Nicht signiert.** Windows SmartScreen zeigt „Unbekannter Herausgeber" → „Weitere Informationen" → „Trotzdem
  ausführen". Abhilfe: Code-Signing-Zertifikat (OV/EV) kaufen und im Bau signieren — braucht Ihre Entscheidung.
* PyInstaller-Programme werden von manchen Virenscannern fälschlich gemeldet; der Ordner-Modus (statt Einzeldatei)
  verringert das, schließt es nicht aus.
* Der Launcher öffnet Edge im App-Modus mit dem normalen Edge-Profil (Anmeldung bleibt wie im Browser erhalten).
  Ohne Edge/Chrome öffnet der Standardbrowser.
* Mit einem echten Nutzer auf einem echten Windows-PC gegen eine echte Instanz ist der Launcher **noch nicht**
  geprüft (es gibt noch keinen Produktionsserver); die Dialoge (tkinter) sind nur im CI-Bau enthalten, nicht
  automatisch durchgeklickt.
