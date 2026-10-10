<#
IC WARE HQ Server entfernen (vom Deinstallationsprogramm aufgerufen, ADR-018).
Standard: Server anhalten, Autostart entfernen — DATEN BLEIBEN (WSL-Distribution „IC-WARE-HQ"; eine
Neuinstallation übernimmt sie). Nur mit -DatenLoeschen wird die Distribution samt Datenbank und Dokumenten gelöscht.
#>
[CmdletBinding(SupportsShouldProcess)]
param([switch]$DatenLoeschen)
$ErrorActionPreference = 'Continue'
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot 'IchqServer.psm1') -Force
$K = Get-IchqKonstante

if ((Get-IchqWslListe) -contains $K.Distro) {
    Write-Host 'Server anhalten …'
    $null = Invoke-IchqLinux 'deploy/hq stop'
}
Unregister-ScheduledTask -TaskName 'IC WARE HQ Server' -Confirm:$false -ErrorAction SilentlyContinue
Remove-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce' -Name 'IC-WARE-HQ-Einrichtung' -ErrorAction SilentlyContinue
if ($DatenLoeschen -and $PSCmdlet.ShouldProcess($K.Distro, 'Distribution mit ALLEN Daten löschen')) {
    & wsl.exe --unregister $K.Distro
    Remove-Item -LiteralPath $K.Basis -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -Path 'HKLM:\SOFTWARE\IC WARE HQ Server' -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host 'Alle Daten gelöscht.'
} else {
    Write-Host "Daten bleiben erhalten ($($K.Basis)\wsl). Neuinstallation übernimmt sie."
}
exit 0
