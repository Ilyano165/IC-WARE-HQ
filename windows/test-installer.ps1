# IC WARE HQ — gebauten Installer ECHT prüfen (CI auf windows-latest): stille Installation mit Adresse, Dateien,
# Verknüpfungen, Launcher-Kommandozeile, Deinstallation. Nutzt keinen IC-WARE-HQ-Server (der läuft im Linux-Job);
# die Gegenprobe „fremde Webseite" geht gegen https://github.com.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
$Setup = Get-ChildItem "$Root\dist\IC-WARE-HQ-Setup-*.exe" | Select-Object -First 1
if (-not $Setup) { throw 'Installer fehlt (windows\build.ps1 zuerst)' }
$Ziel = "$env:LOCALAPPDATA\Programs\IC WARE HQ"
$Exe = "$Ziel\ichq-launcher.exe"
$script:Ok = 0
function Pruefe([string]$Name, [bool]$Bedingung) {
  if (-not $Bedingung) { throw "FEHLT: $Name" }
  $script:Ok++; Write-Host "  ok   $Name"
}
function Lauf([string[]]$Argumente) {   # Launcher ist eine Fenster-Anwendung: Exitcode über Start-Process
  (Start-Process -FilePath $Exe -ArgumentList $Argumente -Wait -PassThru -WindowStyle Hidden).ExitCode
}

Write-Host "== Stille Installation: $($Setup.Name)"
$p = Start-Process -FilePath $Setup.FullName -Wait -PassThru -ArgumentList @(
  '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', '/URL=https://hq.beispiel-firma.de',
  "/LOG=$Root\dist\install.log")
Pruefe 'Installer endet mit 0' ($p.ExitCode -eq 0)
Pruefe 'Launcher installiert (ohne Administratorrechte, Benutzerprofil)' (Test-Path $Exe)
Pruefe 'Adresse aus /URL= gespeichert' ((Get-Content "$Ziel\server.json" -Raw) -match '"url": "https://hq.beispiel-firma.de"')
$Menue = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\IC WARE HQ"
Pruefe 'Startmenü: IC WARE HQ' (Test-Path "$Menue\IC WARE HQ.lnk")
Pruefe 'Startmenü: Adresse ändern' (Test-Path "$Menue\IC WARE HQ – Adresse ändern.lnk")
Pruefe 'Desktop-Verknüpfung' (Test-Path "$([Environment]::GetFolderPath('Desktop'))\IC WARE HQ.lnk")
Pruefe 'keine Datenbank/kein Server installiert' (-not (Get-ChildItem $Ziel -Recurse -Include *.sql, postgres*, *.db -ErrorAction SilentlyContinue))

Write-Host '== Launcher (installiert)'
Pruefe '--version' ((Lauf @('--version')) -eq 0)
Pruefe 'Adresse aus der Installer-Vorgabe gelesen' ((Lauf @('--adresse')) -eq 0)
Pruefe 'http:// zu fremdem Host abgelehnt (Exit 2)' ((Lauf @('--check', 'http://hq.beispiel-firma.de')) -eq 2)
Pruefe 'fremde Webseite ist kein IC WARE HQ (Exit 1)' ((Lauf @('--check', 'https://github.com')) -eq 1)
Pruefe 'unbekannte Domain (Exit 1)' ((Lauf @('--check', 'https://gibt-es-nicht.invalid')) -eq 1)
Pruefe 'ungültiges Zertifikat abgelehnt (Exit 1)' ((Lauf @('--check', 'https://self-signed.badssl.com')) -eq 1)

Write-Host '== Deinstallation'
$p = Start-Process -FilePath "$Ziel\unins000.exe" -Wait -PassThru -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
Start-Sleep -Seconds 3   # der Deinstaller löscht sich selbst nach dem Ende
Pruefe 'Deinstallation endet mit 0' ($p.ExitCode -eq 0)
Pruefe 'Launcher entfernt' (-not (Test-Path $Exe))
Pruefe 'Startmenü entfernt' (-not (Test-Path "$Menue\IC WARE HQ.lnk"))
Write-Host "== Ergebnis: $script:Ok Prüfungen bestanden, 0 fehlgeschlagen"
