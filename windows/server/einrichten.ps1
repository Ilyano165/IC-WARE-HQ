<#
IC WARE HQ Server auf diesem Windows-PC einrichten oder aktualisieren (ADR-018). Ruft der Installer auf; erneut
ausführen ist sicher (Startmenü „IC WARE HQ Server – Einrichtung wiederholen"): vorhandene Daten bleiben.

Ablauf: Prüfen → WSL2 (ggf. Neustart, danach automatisch weiter) → eigene Ubuntu-Distribution „IC-WARE-HQ"
(Download von ubuntu.com, SHA-256 geprüft) → systemd → Quelltext → deploy/install.sh --tunnel (Docker, Stack,
Sicherung, Zeitpläne) → Autostart → Energiesparmodus (optional). Protokoll: %ProgramData%\IC-WARE-HQ\einrichten.log
#>
[CmdletBinding()]
param(
    [string]$Domain,
    [string]$Email,
    [string]$TokenDatei,          # Datei mit dem Cloudflare-Tunnel-Token (wird nach dem Lesen gelöscht)
    [string]$Quelle,              # quelle.tar (Inhalt des Repositorys, vom Installer mitgeliefert)
    [switch]$EnergieAus,
    [switch]$Fortsetzen,          # nach Neustart (WSL-Installation) — Werte aus fortsetzen.json
    [switch]$NurPruefen           # nur Eingaben und Voraussetzungen prüfen, nichts ändern (Test/CI)
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'IchqServer.psm1') -Force
$K = Get-IchqKonstante
$null = New-Item -ItemType Directory -Force -Path $K.Basis
$tokenAblage = Join-Path $K.Basis 'token.tmp'
$fortsetzenDatei = Join-Path $K.Basis 'fortsetzen.json'

function Schritt([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Green }
function Abbruch([string]$Text) { Write-Host "`nFEHLER: $Text" -ForegroundColor Red; exit 1 }

if ($Fortsetzen) {
    if (-not (Test-Path $fortsetzenDatei)) { Abbruch 'Keine unterbrochene Einrichtung gefunden.' }
    $w = Get-Content $fortsetzenDatei -Raw | ConvertFrom-Json
    $Domain = $w.Domain; $Email = $w.Email; $Quelle = $w.Quelle; $EnergieAus = [bool]$w.EnergieAus
}
if (-not $NurPruefen) { Start-Transcript -Path (Join-Path $K.Basis 'einrichten.log') -Append | Out-Null }

# ---- 1. Eingaben und Voraussetzungen ------------------------------------------------------------------------------
Schritt 'Eingaben und Voraussetzungen prüfen'
$Domain = "$Domain".Trim().ToLowerInvariant()
if (-not (Test-IchqDomain $Domain)) { Abbruch "Ungültige Domain „$Domain“ (nur Hostname, z. B. hq.meine-firma.de)." }
if (-not (Test-IchqEmail $Email)) { Abbruch "Ungültige E-Mail-Adresse „$Email“." }
$token = ''
if ($TokenDatei) {
    $token = ConvertTo-IchqToken ((Get-Content -LiteralPath $TokenDatei -Raw -ErrorAction SilentlyContinue) + '')
    if (-not $NurPruefen) { Remove-Item -LiteralPath $TokenDatei -Force -ErrorAction SilentlyContinue }
} elseif (Test-Path $tokenAblage) {
    $token = (Get-Content -LiteralPath $tokenAblage -Raw).Trim()
}
if ($token -and -not (Test-IchqToken $token)) {
    Abbruch 'Das ist kein Cloudflare-Tunnel-Token (Zero Trust → Networks → Tunnels → Ihr Tunnel → Token kopieren).'
}
$distroDa = (Get-IchqWslListe) -contains $K.Distro
if (-not $token -and -not $distroDa) { Abbruch 'Für die Ersteinrichtung wird das Cloudflare-Tunnel-Token benötigt.' }
if ([Environment]::OSVersion.Version.Build -lt 19041) { Abbruch 'Windows 10 Version 2004 (Build 19041) oder neuer nötig.' }
if (-not [Environment]::Is64BitOperatingSystem) { Abbruch '64-Bit-Windows nötig.' }
$ramGb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
if ($ramGb -lt 8) { Write-Warning "Nur $ramGb GB RAM — empfohlen sind 8 GB (WSL nutzt bis zur Hälfte, ClamAV braucht ~1,5 GB)." }
if (-not $NurPruefen -and -not (Test-Path -LiteralPath "$Quelle")) { Abbruch "Quelltext fehlt: $Quelle" }
if ($NurPruefen) { Write-Host 'Prüfung bestanden (nichts geändert).'; exit 0 }

if ($token) {   # bis zur Übergabe an Linux nur für Administratoren lesbar (überlebt ggf. den Neustart)
    Set-Content -LiteralPath $tokenAblage -Value $token -NoNewline -Encoding ascii
    Set-IchqNurAdmins $tokenAblage
}

# ---- 2. WSL2 ------------------------------------------------------------------------------------------------------
Schritt 'WSL2 prüfen'
if (-not (Test-IchqWslBereit)) {
    Write-Host 'WSL wird installiert (Windows-Funktion + aktuelle WSL). Danach ist ein NEUSTART nötig.'
    & wsl.exe --install --no-distribution
    if ($LASTEXITCODE -ne 0) { Abbruch "wsl --install scheiterte ($LASTEXITCODE). Virtualisierung im BIOS/UEFI aktiv?" }
    @{ Domain = $Domain; Email = $Email; Quelle = $Quelle; EnergieAus = [bool]$EnergieAus } | ConvertTo-Json |
        Set-Content -LiteralPath $fortsetzenDatei -Encoding utf8
    $befehl = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Fortsetzen"
    Set-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce' -Name 'IC-WARE-HQ-Einrichtung' -Value $befehl
    Write-Host "`nBitte Windows NEU STARTEN. Nach der Anmeldung geht die Einrichtung automatisch weiter." -ForegroundColor Yellow
    exit 3010
}
& wsl.exe --update 2>&1 | Out-Host        # aktuelle WSL (Fehler hier sind nicht fatal, z. B. ohne Store)

# ---- 3. Eigene Ubuntu-Distribution --------------------------------------------------------------------------------
if (-not $distroDa) {
    Schritt "Ubuntu 24.04 für IC WARE HQ laden (≈ 390 MB, Prüfsumme $($K.UbuntuSha256.Substring(0, 12))…)"
    $download = Join-Path $K.Basis 'download'
    $null = New-Item -ItemType Directory -Force -Path $download
    $datei = Join-Path $download 'ubuntu-24.04-wsl.tar.gz'
    $ProgressPreference = 'SilentlyContinue'   # sonst ist Invoke-WebRequest in PowerShell 5.1 extrem langsam
    Invoke-WebRequest -Uri $K.UbuntuUrl -OutFile $datei -UseBasicParsing
    Assert-IchqPruefsumme -Pfad $datei -Sha256 $K.UbuntuSha256
    Schritt "Distribution „$($K.Distro)“ anlegen"
    & wsl.exe --import $K.Distro (Join-Path $K.Basis 'wsl') $datei --version 2
    if ($LASTEXITCODE -ne 0) { Abbruch "wsl --import scheiterte ($LASTEXITCODE)." }
    Remove-Item -LiteralPath $datei -Force
}

Schritt 'Linux-Umgebung einstellen (systemd, root, ohne Windows-PATH)'
$wslConf = "cat > /etc/wsl.conf <<'ENDE'`n[boot]`nsystemd=true`n[user]`ndefault=root`n[interop]`nappendWindowsPath=false`nENDE"
if ((Invoke-IchqLinux $wslConf) -ne 0) { Abbruch '/etc/wsl.conf nicht schreibbar.' }
& wsl.exe --terminate $K.Distro | Out-Null                 # Neustart der Distribution — jetzt mit systemd
$null = Invoke-IchqLinux 'systemctl is-system-running --wait >/dev/null 2>&1; true'
if ((Invoke-IchqLinux 'test "$(ps -p 1 -o comm=)" = systemd') -ne 0) { Abbruch 'systemd startet nicht (WSL zu alt? wsl --update).' }

# ---- 4. Quelltext + Server-Einrichtung (geprüfter Linux-Weg) -------------------------------------------------------
Schritt 'Programm in die Linux-Umgebung kopieren'
$tar = ConvertTo-IchqWslPfad (Resolve-Path -LiteralPath $Quelle).Path
if ((Invoke-IchqLinux "mkdir -p $($K.LinuxQuelle) && tar -xf '$tar' -C $($K.LinuxQuelle)") -ne 0) { Abbruch 'Entpacken scheiterte.' }
if ($distroDa) {
    Schritt 'Bestehende Installation: Sicherung vor dem Update'
    if ((Invoke-IchqLinux 'deploy/hq backup') -ne 0) { Write-Warning 'Sicherung vor dem Update scheiterte — Meldung oben lesen.' }
}
Schritt 'Pakete für die Einrichtung (python3, curl, git)'
if ((Invoke-IchqLinux 'apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -yq python3 curl ca-certificates git') -ne 0) {
    Abbruch 'apt-get scheiterte — Internetverbindung?'
}
Schritt 'IC WARE HQ einrichten: Docker, Datenbank, Virenscanner, Tunnel, Sicherung (dauert 10–20 Minuten)'
# Token nur über STDIN (Invoke-IchqLinux) — geprüft: nur [A-Za-z0-9+/_=-], also sicher in einfachen Anführungszeichen
$installieren = "deploy/install.sh --domain '$Domain' --email '$Email' --tunnel"
if ($token) { $installieren = "export HQ_TUNNEL_TOKEN='$token'`n$installieren" }
$rc = Invoke-IchqLinux $installieren
Remove-Item -LiteralPath $tokenAblage -Force -ErrorAction SilentlyContinue   # liegt jetzt nur noch als Secret in Linux
if ($rc -ne 0) { Abbruch "deploy/install.sh scheiterte ($rc) — Meldung oben; danach Startmenü → Einrichtung wiederholen." }

# ---- 5. Autostart, Energie ----------------------------------------------------------------------------------------
Schritt 'Autostart einrichten (Aufgabenplanung „IC WARE HQ Server")'
$aktion = New-ScheduledTaskAction -Execute 'wsl.exe' -Argument "-d $($K.Distro) -u root -- /bin/sh -c `"exec sleep infinity`""
$ausloeser = @((New-ScheduledTaskTrigger -AtStartup), (New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"))
$einst = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$wer = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest
Register-ScheduledTask -TaskName 'IC WARE HQ Server' -Action $aktion -Trigger $ausloeser -Settings $einst -Principal $wer -Force | Out-Null
Start-ScheduledTask -TaskName 'IC WARE HQ Server'
if ($EnergieAus) {
    Schritt 'Energiesparmodus im Netzbetrieb aus (der PC ist jetzt ein Server)'
    & powercfg.exe /change standby-timeout-ac 0; & powercfg.exe /change hibernate-timeout-ac 0
}
Remove-Item -LiteralPath $fortsetzenDatei -Force -ErrorAction SilentlyContinue
New-Item -Path 'HKLM:\SOFTWARE\IC WARE HQ Server' -Force | Out-Null
Set-ItemProperty 'HKLM:\SOFTWARE\IC WARE HQ Server' -Name Eingerichtet -Value 1

Schritt 'Fertig'
Write-Host "IC WARE HQ: https://$Domain/app/"
Write-Host 'Nächste Schritte (Startmenü „IC WARE HQ Server"): „Erste Firma anlegen", dann „Diagnose".'
Write-Host 'WICHTIG: Den angezeigten SICHERUNGSSCHLÜSSEL getrennt von diesem PC aufbewahren (Passwortmanager).'
exit 0
