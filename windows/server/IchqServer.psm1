# IC WARE HQ Server auf Windows (ADR-018): gemeinsame Funktionen für Einrichtung, Steuerung, Deinstallation.
# Der Server läuft in einer EIGENEN WSL2-Distribution „IC-WARE-HQ" (Ubuntu 24.04) — getrennt von anderen
# Linux-Umgebungen des Benutzers. Darin: Docker, der geprüfte Linux-Stack (deploy/install.sh --tunnel), systemd-Timer.
Set-StrictMode -Version Latest

$script:Distro = 'IC-WARE-HQ'
$script:Basis = Join-Path $(if ($env:ProgramData) { $env:ProgramData } else { [IO.Path]::GetTempPath() }) 'IC-WARE-HQ'
$script:LinuxQuelle = '/opt/ic-ware-hq'
# Ubuntu 24.04.5 für WSL von ubuntu.com; Prüfsumme aus https://releases.ubuntu.com/noble/SHA256SUMS
# (Signatur mit dem Ubuntu-Archivschlüssel geprüft am 10.10.2026). Neue Version ⇒ URL UND Prüfsumme ändern.
$script:UbuntuUrl = 'https://releases.ubuntu.com/noble/ubuntu-24.04.5-wsl-amd64.wsl'
$script:UbuntuSha256 = 'bb415d824822c4b878125729af451a5d18fb13d1cf5cbed9a7393ad64ac6039e'

function Get-IchqKonstante {
    [CmdletBinding()]
    param()
    [pscustomobject]@{ Distro = $script:Distro; Basis = $script:Basis; LinuxQuelle = $script:LinuxQuelle
        UbuntuUrl = $script:UbuntuUrl; UbuntuSha256 = $script:UbuntuSha256 }
}

# ---- Eingaben (gleiche Regeln wie deploy/lib/tunnel.sh — sie landen im Caddyfile bzw. als Secret) ---------------------
function Test-IchqDomain {
    [CmdletBinding()]
    [OutputType([bool])]
    param([AllowEmptyString()][string]$Domain)
    return [bool]($Domain -cmatch '^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$')
}

function Test-IchqEmail {
    [CmdletBinding()]
    [OutputType([bool])]
    param([AllowEmptyString()][string]$Email)
    return [bool]($Email -cmatch '^[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,63}$')
}

function Test-IchqToken {
    [CmdletBinding()]
    [OutputType([bool])]
    param([AllowEmptyString()][string]$Token)
    return [bool]($Token -cmatch '^[A-Za-z0-9+/_=-]{80,4096}$')
}

function ConvertTo-IchqToken {
    <# Nimmt auch den ganzen Befehl aus Cloudflare („cloudflared.exe service install eyJ…") und liefert nur das Token. #>
    [CmdletBinding()]
    [OutputType([string])]
    param([AllowEmptyString()][string]$Eingabe)
    $teile = @($Eingabe.Trim() -split '\s+' | Where-Object { $_ -ne '' })
    if ($teile.Count -eq 0) { return '' }
    return $teile[-1]
}

# ---- Dateien ------------------------------------------------------------------------------------------------------
function Assert-IchqPruefsumme {
    <# Prüft SHA-256; bei Abweichung wird die Datei gelöscht und abgebrochen (nie eine veränderte Datei einspielen). #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Pfad, [Parameter(Mandatory)][string]$Sha256)
    $ist = (Get-FileHash -LiteralPath $Pfad -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ist -ne $Sha256.ToLowerInvariant()) {
        Remove-Item -LiteralPath $Pfad -Force -ErrorAction SilentlyContinue
        throw "Prüfsumme falsch für $Pfad (erwartet $Sha256, erhalten $ist) — Datei verworfen. Download wiederholen."
    }
}

function ConvertTo-IchqWslPfad {
    <# C:\Program Files\X\a.tar → /mnt/c/Program Files/X/a.tar (WSL-Standard-Einhängepunkt) #>
    [CmdletBinding()]
    [OutputType([string])]
    param([Parameter(Mandatory)][string]$Pfad)
    if ($Pfad -notmatch '^([A-Za-z]):\\(.*)$') { throw "Kein Windows-Pfad mit Laufwerk: $Pfad" }
    return '/mnt/' + $Matches[1].ToLowerInvariant() + '/' + ($Matches[2] -replace '\\', '/')
}

function Set-IchqAdminZugriff {
    <# Datei/Ordner nur für SYSTEM und Administratoren (z. B. Token bis zur Übergabe an Linux). #>
    [CmdletBinding(SupportsShouldProcess)]
    param([Parameter(Mandatory)][string]$Pfad)
    if ($PSCmdlet.ShouldProcess($Pfad, 'Zugriff auf SYSTEM und Administratoren beschränken')) {
        $null = & icacls.exe $Pfad /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F'
        if ($LASTEXITCODE -ne 0) { throw "Rechte für $Pfad nicht setzbar (icacls $LASTEXITCODE)" }
    }
}

# ---- WSL ----------------------------------------------------------------------------------------------------------
function Get-IchqWslListe {
    [CmdletBinding()]
    [OutputType([string[]])]
    param()
    $env:WSL_UTF8 = '1'                       # sonst liefert wsl.exe UTF-16
    try { $liste = & wsl.exe --list --quiet 2>$null } catch { return @() }   # WSL fehlt ganz
    if ($LASTEXITCODE -ne 0) { return @() }
    return @($liste | ForEach-Object { $_.Trim([char]0, ' ') } | Where-Object { $_ })
}

function Test-IchqWslBereit {
    [CmdletBinding()]
    [OutputType([bool])]
    param()
    $env:WSL_UTF8 = '1'
    try { $null = & wsl.exe --version 2>$null } catch { return $false }   # nur die aktuelle WSL kennt --version
    return ($LASTEXITCODE -eq 0)
}

function Invoke-IchqLinux {
    <# Skript in der IC-WARE-HQ-Distribution als root, im Programmordner. Das Skript geht über STDIN an bash — so
       stehen Token o. Ä. nie in einer Kommandozeile (Prozessliste) und Windows PowerShell 5.1 verdirbt keine
       Anführungszeichen in Argumenten. Ausgabe läuft durch. Rückgabe: Exitcode. #>
    [CmdletBinding()]
    [OutputType([int])]
    param([Parameter(Mandatory)][string]$Skript)
    $env:WSL_UTF8 = '1'
    $OutputEncoding = [Text.UTF8Encoding]::new($false)
    $voll = "cd $script:LinuxQuelle 2>/dev/null || true`n$Skript`n"
    $voll | & wsl.exe -d $script:Distro -u root -- bash -c "tr -d '\r' | bash -s" | Out-Host
    return $LASTEXITCODE
}

function Get-IchqEnvWert {
    <# Wert aus deploy/.env in der Linux-Umgebung (z. B. ICHQ_DOMAIN) #>
    [CmdletBinding()]
    [OutputType([string])]
    param([Parameter(Mandatory)][ValidatePattern('^[A-Z_]+$')][string]$Name)
    $env:WSL_UTF8 = '1'
    $w = & wsl.exe -d $script:Distro -u root -- sed -n "s/^$Name=//p" "$script:LinuxQuelle/deploy/.env" 2>$null
    return ((@($w) | Select-Object -Last 1) + '').Trim()
}

function Get-IchqDomain {
    [CmdletBinding()]
    [OutputType([string])]
    param()
    return Get-IchqEnvWert ICHQ_DOMAIN
}

Export-ModuleMember -Function Get-IchqKonstante, Test-IchqDomain, Test-IchqEmail, Test-IchqToken, ConvertTo-IchqToken,
    Assert-IchqPruefsumme, ConvertTo-IchqWslPfad, Set-IchqAdminZugriff, Get-IchqWslListe, Test-IchqWslBereit,
    Invoke-IchqLinux, Get-IchqEnvWert, Get-IchqDomain
