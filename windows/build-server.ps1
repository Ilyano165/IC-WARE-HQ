# IC WARE HQ SERVER — Windows-Installer bauen (ADR-018). Läuft auf windows-latest (CI) oder einem Windows-PC mit Git.
#   powershell -ExecutionPolicy Bypass -File windows\build-server.ps1
# Ergebnis: dist\IC-WARE-HQ-Server-Setup-<version>.exe + .sha256. Enthält den Quelltext des aktuellen Commits
# (git archive) — der Server wird daraus in der WSL-Umgebung gebaut, genau wie auf einem Linux-Server.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Version = (Select-String -Path 'src\ichq\__init__.py' -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
if ($env:GITHUB_REF_TYPE -eq 'tag' -and $env:GITHUB_REF_NAME -ne "v$Version") { throw "Tag $($env:GITHUB_REF_NAME) ≠ v$Version" }
Write-Host "==> Version $Version"
$null = New-Item -ItemType Directory -Force -Path dist
Write-Host '==> Quelltext des Commits (git archive, ohne .git und ohne lokale Geheimnisse)'
git archive --format=tar -o dist\quelle.tar HEAD
if ($LASTEXITCODE) { throw 'git archive fehlgeschlagen' }
$Iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $Iscc) { $Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $Iscc)) {
  choco install innosetup -y --no-progress
  if ($LASTEXITCODE) { throw 'Inno Setup nicht installierbar' }
  $Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
}
& $Iscc "/DAppVersion=$Version" windows\server\ichq-server.iss
if ($LASTEXITCODE) { throw 'Inno Setup fehlgeschlagen' }
$Setup = "dist\IC-WARE-HQ-Server-Setup-$Version.exe"
$Hash = (Get-FileHash $Setup -Algorithm SHA256).Hash.ToLower()
"$Hash  IC-WARE-HQ-Server-Setup-$Version.exe" | Out-File -Encoding ascii "$Setup.sha256"
Write-Host "==> Fertig: $Setup (SHA-256 $Hash)"
