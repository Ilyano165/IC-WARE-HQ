# IC WARE HQ — Windows-Installer bauen (ADR-017). Läuft auf windows-latest (CI) oder einem Windows-PC mit Python 3.12.
#   powershell -ExecutionPolicy Bypass -File windows\build.ps1
# Ergebnis: dist\IC-WARE-HQ-Setup-<version>.exe + .sha256
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Eine Versionsnummer: Server (src/ichq/__init__.py) == Launcher — sonst Abbruch
$ServerVersion = (Select-String -Path 'src\ichq\__init__.py' -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
$LauncherVersion = (Select-String -Path 'windows\launcher\ichq_launcher.py' -Pattern '^VERSION = "([^"]+)"').Matches[0].Groups[1].Value
if ($ServerVersion -ne $LauncherVersion) { throw "Version verschieden: Server $ServerVersion, Launcher $LauncherVersion" }
if ($env:GITHUB_REF_TYPE -eq 'tag' -and $env:GITHUB_REF_NAME -ne "v$ServerVersion") {
  throw "Tag $($env:GITHUB_REF_NAME) passt nicht zu Version $ServerVersion"
}
Write-Host "==> Version $ServerVersion"

Write-Host '==> Build-Abhängigkeiten (gepinnt, mit Hashes)'
python -m pip install --disable-pip-version-check --require-hashes -r windows\requirements-build.lock
if ($LASTEXITCODE) { throw 'pip install fehlgeschlagen' }

Write-Host '==> Launcher bauen (PyInstaller, Ordner statt Einzeldatei — weniger Fehlalarme von Virenscannern)'
python -m PyInstaller --noconfirm --clean --onedir --windowed --name ichq-launcher `
  --icon "$Root\windows\installer\ichq.ico" --distpath dist --workpath build\pyi --specpath build `
  --paths windows\launcher windows\launcher\ichq_launcher.py
if ($LASTEXITCODE) { throw 'PyInstaller fehlgeschlagen' }

$Iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $Iscc) { $Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $Iscc)) {
  Write-Host '==> Inno Setup installieren (Chocolatey)'
  choco install innosetup -y --no-progress
  if ($LASTEXITCODE) { throw 'Inno Setup nicht installierbar' }
  $Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
}
Write-Host "==> Installer bauen ($Iscc)"
& $Iscc "/DAppVersion=$ServerVersion" "/DQuelle=$Root\dist\ichq-launcher" windows\installer\ichq.iss
if ($LASTEXITCODE) { throw 'Inno Setup fehlgeschlagen' }

$Setup = "dist\IC-WARE-HQ-Setup-$ServerVersion.exe"
$Hash = (Get-FileHash $Setup -Algorithm SHA256).Hash.ToLower()
"$Hash  IC-WARE-HQ-Setup-$ServerVersion.exe" | Out-File -Encoding ascii "$Setup.sha256"
Write-Host "==> Fertig: $Setup (SHA-256 $Hash)"
