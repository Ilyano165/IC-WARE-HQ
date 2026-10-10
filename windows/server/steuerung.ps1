<#
IC WARE HQ Server bedienen (Startmenü „IC WARE HQ Server – …", ADR-018). Jede Aktion ruft deploy/hq in der
Linux-Umgebung „IC-WARE-HQ" auf — derselbe, geprüfte Weg wie auf einem Linux-Server.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('Oeffnen', 'Status', 'Diagnose', 'Domain', 'Token', 'ErsteFirma', 'Sicherung', 'Pruefung', 'Logs',
                 'Starten', 'Stoppen', 'Einrichten', 'SicherungExtern', 'EMail')]
    [string]$Aktion
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'IchqServer.psm1') -Force
$K = Get-IchqKonstante
$Host.UI.RawUI.WindowTitle = "IC WARE HQ Server – $Aktion"

function Klartext([Security.SecureString]$S) {
    [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($S))
}
function B64([string]$S) { [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($S)) }
function Pruefe([string]$Wert, [string]$Muster, [string]$Name) {
    if ($Wert -cnotmatch $Muster) { Write-Host "Ungültig: $Name"; Ende 2 }
}
# Wiederholt deploy/install.sh mit den gespeicherten Werten (Domain, E-Mail, Tunnel bleiben) plus Zusatzoptionen
function NeuEinrichten([string]$Zusatz, [string]$Vorher = '') {
    $d = Get-IchqDomain; $e = Get-IchqEnvWert ICHQ_ACME_EMAIL
    return Invoke-IchqLinux "$Vorher`ndeploy/install.sh --domain '$d' --email '$e' --no-build $Zusatz </dev/null"
}

function Ende([int]$Code) {
    Write-Host ''
    if ($Code -eq 0) { Write-Host 'Fertig.' -ForegroundColor Green } else { Write-Host "Beendet mit Fehler ($Code)." -ForegroundColor Red }
    Read-Host 'Fenster schließen mit Eingabetaste' | Out-Null
    exit $Code
}

if ((Get-IchqWslListe) -notcontains $K.Distro) {
    Write-Host 'IC WARE HQ Server ist auf diesem Benutzerkonto nicht eingerichtet (WSL-Distribution „IC-WARE-HQ" fehlt).'
    Write-Host 'Startmenü → „IC WARE HQ Server – Einrichtung wiederholen" — mit dem Konto, das installiert hat.'
    Ende 1
}

switch ($Aktion) {
    'Oeffnen' {
        $d = Get-IchqDomain
        if (-not (Test-IchqDomain $d)) { Write-Host "Keine gültige Domain eingerichtet ($d)."; Ende 1 }
        Start-Process "https://$d/app/"
        exit 0
    }
    'Status'     { Ende (Invoke-IchqLinux 'deploy/hq status') }
    'Diagnose'   { Ende (Invoke-IchqLinux 'deploy/hq diagnose') }
    'Pruefung'   { Ende (Invoke-IchqLinux 'deploy/hq check') }
    'Sicherung'  { Ende (Invoke-IchqLinux 'deploy/hq backup && deploy/hq backup-verify') }
    'Logs'       { Write-Host 'Logs (laufend; beenden mit Strg+C) …'; Ende (Invoke-IchqLinux 'deploy/hq logs </dev/null') }
    'Starten'    { Start-ScheduledTask -TaskName 'IC WARE HQ Server' -ErrorAction SilentlyContinue; Ende (Invoke-IchqLinux 'deploy/hq start') }
    'Stoppen'    { Ende (Invoke-IchqLinux 'deploy/hq stop') }
    'Domain' {
        $alt = Get-IchqDomain
        Write-Host "Aktuelle Domain: $alt"
        $neu = (Read-Host 'Neue Domain (z. B. hq.meine-firma.de)').Trim().ToLowerInvariant()
        if (-not (Test-IchqDomain $neu)) { Write-Host 'Ungültig — nur der Hostname, ohne https:// und ohne Pfad.'; Ende 2 }
        Write-Host @"

Zuerst in Cloudflare (dash.cloudflare.com → Zero Trust → Networks → Tunnels → Ihr Tunnel → Public Hostname):
  Hostname: $neu        Dienst: HTTP   caddy:80
Die Domain muss in Cloudflare verwaltet sein.
"@
        $ok = Read-Host 'In Cloudflare erledigt? Domain jetzt umstellen [j/N]'
        if ($ok -notmatch '^[jJyY]$') { Write-Host 'Abgebrochen — nichts geändert.'; Ende 1 }
        Ende (Invoke-IchqLinux "deploy/hq domain '$neu' </dev/null")
    }
    'Token' {
        $t = ConvertTo-IchqToken (Read-Host 'Neues Cloudflare-Tunnel-Token (oder ganzer Befehl aus Cloudflare)')
        if (-not (Test-IchqToken $t)) { Write-Host 'Das ist kein Tunnel-Token.'; Ende 2 }
        Ende (Invoke-IchqLinux "export HQ_TUNNEL_TOKEN='$t'`ndeploy/hq tunnel-token </dev/null")
    }
    'ErsteFirma' {
        Write-Host 'Erste Firma und ihr Administrator (Kürzel: Kleinbuchstaben/Ziffern/Bindestrich).'
        $firma = Read-Host 'Firmenname'; $slug = Read-Host 'Kürzel (z. B. meine-firma)'
        $mail = Read-Host 'E-Mail des Admins'; $name = Read-Host 'Name des Admins'
        $pw = Read-Host 'Passwort (mind. 12 Zeichen)' -AsSecureString
        $klar = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw))
        foreach ($w in @($firma, $slug, $mail, $name, $klar)) {
            if ([string]::IsNullOrWhiteSpace($w) -or $w -match "[`r`n]") { Write-Host 'Leere oder mehrzeilige Eingabe.'; Ende 2 }
        }
        $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($firma, $slug, $mail, $name, $klar) -join "`n"))
        $klar = $null
        # Eingaben per Base64 über STDIN-Skript an setup-admin — Passwort nie in einer Kommandozeile
        Ende (Invoke-IchqLinux "printf '%s\n' '$b64' | base64 -d | deploy/hq setup-admin")
    }
    'SicherungExtern' {
        Write-Host 'Externe, verschlüsselte Sicherung (S3-kompatibel, z. B. Hetzner Object Storage, Backblaze B2, AWS).'
        Write-Host 'Ohne externes Ziel liegt die Sicherung auf DIESEM PC — ein Festplattenschaden nähme sie mit.'
        $repo = (Read-Host 'Ziel (s3:https://<endpunkt>/<bucket>/ichq)').Trim()
        $id = (Read-Host 'Access Key ID').Trim()
        $geheim = Klartext (Read-Host 'Secret Access Key' -AsSecureString)
        $region = (Read-Host 'Region (z. B. eu-central-1; leer = us-east-1)').Trim(); if (-not $region) { $region = 'us-east-1' }
        Pruefe $repo '^s3:https://[A-Za-z0-9.-]+(:[0-9]+)?/[A-Za-z0-9._/-]+$' 'Ziel'
        Pruefe $id '^[A-Za-z0-9]{8,128}$' 'Access Key ID'
        Pruefe $geheim '^[A-Za-z0-9/+=_-]{8,256}$' 'Secret Access Key'
        Pruefe $region '^[a-z0-9-]{2,40}$' 'Region'
        $inhalt = "AWS_ACCESS_KEY_ID=$id`nAWS_SECRET_ACCESS_KEY=$geheim`nAWS_DEFAULT_REGION=$region`n"
        $vorher = "install -d -m 700 /etc/ichq && (umask 077; printf '%s' '$(B64 $inhalt)' | base64 -d > /etc/ichq/backup-s3.env)"
        $geheim = $null; $inhalt = $null
        $rc = NeuEinrichten "--backup-repository '$repo'" $vorher
        if ($rc -eq 0) { $rc = Invoke-IchqLinux 'deploy/hq backup && deploy/hq backup-verify' }
        Ende $rc
    }
    'EMail' {
        Write-Host 'E-Mail-Versand (Einladungen, Passwort vergessen, Warnungen) über den SMTP-Zugang Ihres Mail-Anbieters.'
        $h = (Read-Host 'SMTP-Server (z. B. smtp.ionos.de)').Trim(); $port = (Read-Host 'Port (587 = STARTTLS)').Trim()
        $u = (Read-Host 'Benutzer').Trim(); $von = (Read-Host 'Absender-Adresse').Trim()
        $pw = Klartext (Read-Host 'Passwort' -AsSecureString)
        Pruefe $h '^[A-Za-z0-9.-]+$' 'SMTP-Server'; Pruefe $port '^[0-9]{1,5}$' 'Port'
        Pruefe $u '^[A-Za-z0-9._%+@-]+$' 'Benutzer'
        if (-not (Test-IchqEmail $von)) { Write-Host 'Ungültig: Absender'; Ende 2 }
        if (-not $pw) { Write-Host 'Passwort fehlt.'; Ende 2 }
        $ssl = if ($port -eq '465') { '--smtp-ssl' } else { '' }
        $vorher = "export HQ_SMTP_PASSWORD=`"`$(printf '%s' '$(B64 $pw)' | base64 -d)`""
        $pw = $null
        Ende (NeuEinrichten "--smtp-host '$h' --smtp-port '$port' --smtp-user '$u' --smtp-from '$von' $ssl --alert-email '$von'" $vorher)
    }
    'Einrichten' {
        $quelle = Join-Path $PSScriptRoot 'quelle.tar'
        $d = Get-IchqDomain
        $e = Get-IchqEnvWert ICHQ_ACME_EMAIL
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'einrichten.ps1') `
            -Domain $d -Email $e -Quelle $quelle
        Ende $LASTEXITCODE
    }
}
