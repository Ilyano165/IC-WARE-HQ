# Pester 5 — Windows-Server-Skripte (ADR-018). Läuft im CI-Job „windows" (windows-latest) und lokal unter pwsh.
# Die echte WSL2-Einrichtung ist auf GitHub-Runnern nicht möglich (keine verschachtelte Virtualisierung) — geprüft
# werden hier Eingaben, Prüfsumme, Pfade, die Skript-Übergabe an Linux (über STDIN, CRLF-fest) und -NurPruefen.
BeforeAll {
    $script:Ordner = Split-Path -Parent $PSScriptRoot
    Import-Module (Join-Path $script:Ordner 'IchqServer.psm1') -Force
    $script:Echt = 'eyJhIjoiMTIzNDU2Nzg5MGFiY2RlZjEyMzQ1Njc4OTBhYmNkZWYiLCJ0IjoiYWJjZGVmMDEtMjM0NS02Nzg5LWFiY2QtZWYwMTIz' +
                   'NDU2Nzg5IiwicyI6Ik1qQXlOaTB4TUMweE1GUXhNam93TURvd01Gb3RaWGhoYlhCc1pRPT0ifQ=='
}

Describe 'Eingaben (gleiche Regeln wie deploy/lib/tunnel.sh)' {
    It 'Domain <D> → <Ok>' -ForEach @(
        @{ D = 'hq.firma.de'; Ok = $true }, @{ D = 'a-b.c.example.com'; Ok = $true },
        @{ D = 'https://hq.firma.de'; Ok = $false }, @{ D = 'hq.firma.de/app'; Ok = $false }, @{ D = 'hq firma.de'; Ok = $false },
        @{ D = 'hq.firma.de}{$X}'; Ok = $false }, @{ D = "hq.firma.de`nimport x"; Ok = $false }, @{ D = '-hq.firma.de'; Ok = $false },
        @{ D = 'HQ.FIRMA.DE'; Ok = $false }, @{ D = ''; Ok = $false }, @{ D = "hq.firma.de'; rm -rf /"; Ok = $false }
    ) { Test-IchqDomain $D | Should -Be $Ok }

    It 'E-Mail' {
        Test-IchqEmail 'it@firma.de' | Should -BeTrue
        Test-IchqEmail "it@firma.de' --x" | Should -BeFalse
        Test-IchqEmail 'keine-mail' | Should -BeFalse
    }

    It 'Token: nur das Token, nie Leerzeichen/Anführungszeichen/Zeilen' {
        Test-IchqToken $script:Echt | Should -BeTrue
        Test-IchqToken 'zu-kurz' | Should -BeFalse
        Test-IchqToken ($script:Echt + "'; rm -rf /") | Should -BeFalse
        Test-IchqToken ($script:Echt + "`nx") | Should -BeFalse
        Test-IchqToken '' | Should -BeFalse
    }

    It 'Token aus dem ganzen Cloudflare-Befehl herauslösen' {
        ConvertTo-IchqToken "  cloudflared.exe service install $($script:Echt)  " | Should -Be $script:Echt
        ConvertTo-IchqToken "sudo cloudflared service install $($script:Echt)`r`n" | Should -Be $script:Echt
        ConvertTo-IchqToken '   ' | Should -Be ''
    }
}

Describe 'Download-Prüfung' {
    It 'richtige Prüfsumme bleibt, falsche wird verworfen' {
        $f = Join-Path ([IO.Path]::GetTempPath()) "ichq-test-$([guid]::NewGuid()).bin"
        [IO.File]::WriteAllText($f, 'IC WARE HQ')
        $hash = (Get-FileHash $f -Algorithm SHA256).Hash
        { Assert-IchqPruefsumme -Pfad $f -Sha256 $hash.ToLowerInvariant() } | Should -Not -Throw
        Test-Path $f | Should -BeTrue
        { Assert-IchqPruefsumme -Pfad $f -Sha256 ('0' * 64) } | Should -Throw '*Prüfsumme falsch*'
        Test-Path $f | Should -BeFalse                      # nie eine veränderte Datei liegen lassen
    }

    It 'Ubuntu-Quelle fest mit Prüfsumme (https, ubuntu.com)' {
        $k = Get-IchqKonstante
        $k.UbuntuUrl | Should -Match '^https://releases\.ubuntu\.com/'
        $k.UbuntuSha256 | Should -Match '^[0-9a-f]{64}$'
        $k.Distro | Should -Be 'IC-WARE-HQ'
    }
}

Describe 'Download' {
    It 'scheitert mit verständlicher Meldung und lässt keine halbe Datei liegen' {
        $ziel = Join-Path ([IO.Path]::GetTempPath()) "ichq-dl-$([guid]::NewGuid()).bin"
        { Save-IchqDownload -Url 'http://127.0.0.1:9/gibt-es-nicht' -Ziel $ziel } | Should -Throw '*Download von*gescheitert*'
        Test-Path $ziel | Should -BeFalse
    }
}

Describe 'WSL2-Voraussetzungen (Fehler beim Tester: HCS_E_SERVICE_NOT_AVAILABLE)' {
    BeforeAll {
        # Unter Linux-pwsh gibt es die Windows-Befehle nicht — Platzhalter, damit Pester sie ersetzen kann.
        if (-not (Get-Command Get-WindowsOptionalFeature -ErrorAction SilentlyContinue)) {
            function global:Get-WindowsOptionalFeature { param([switch]$Online, [string]$FeatureName) $null = $Online, $FeatureName }
        }
        if (-not (Get-Command Get-CimInstance -ErrorAction SilentlyContinue)) {
            function global:Get-CimInstance { param([Parameter(Position = 0)][string]$ClassName) $null = $ClassName }
        }
    }

    It 'echte Meldung vom Tester-PC → Windows-Funktionen einschalten' {
        $aus = "Der Vorgang konnte nicht gestartet werden, da ein erforderliches Feature nicht installiert ist.`n" +
               'Fehlercode: Wsl/Service/RegisterDistro/CreateVm/HCS/HCS_E_SERVICE_NOT_AVAILABLE'
        $f = Resolve-IchqWslFehler $aus
        $f.Funktionen | Should -BeTrue
        $f.Text | Should -Match 'VM-Plattform'
        $f.Text | Should -Match 'BIOS'
    }
    It 'Hyper-V fehlt / 0x80370102 → ebenfalls' {
        (Resolve-IchqWslFehler 'Wsl/Service/CreateInstance/CreateVm/HCS/HCS_E_HYPERV_NOT_INSTALLED').Funktionen | Should -BeTrue
        (Resolve-IchqWslFehler 'Error: 0x80370102').Funktionen | Should -BeTrue
    }
    It 'andere Fehler → kein Neustart-Versprechen' {
        (Resolve-IchqWslFehler 'Wsl/Service/RegisterDistro/ERROR_PATH_NOT_FOUND').Funktionen | Should -BeFalse
        (Resolve-IchqWslFehler '').Funktionen | Should -BeFalse
    }

    It 'VM-Plattform aus → als fehlend erkannt' {
        Mock -ModuleName IchqServer Get-WindowsOptionalFeature {
            [pscustomobject]@{ State = $(if ($FeatureName -eq 'VirtualMachinePlatform') { 'Disabled' } else { 'Enabled' }) }
        }
        @(Get-IchqFehlendeWslFunktion) | Should -Be @('VirtualMachinePlatform')
    }
    It 'beide an → nichts fehlt' {
        Mock -ModuleName IchqServer Get-WindowsOptionalFeature { [pscustomobject]@{ State = 'Enabled' } }
        @(Get-IchqFehlendeWslFunktion).Count | Should -Be 0
    }
    It 'Abfrage unmöglich → nicht als fehlend raten' {
        Mock -ModuleName IchqServer Get-WindowsOptionalFeature { throw 'keine Rechte' }
        @(Get-IchqFehlendeWslFunktion).Count | Should -Be 0
    }

    It 'Virtualisierung: Hypervisor läuft → an (auch wenn die CPU-Abfrage false meldet)' {
        Mock -ModuleName IchqServer Get-CimInstance {
            if ($ClassName -match 'ComputerSystem') { [pscustomobject]@{ HypervisorPresent = $true } }
            else { [pscustomobject]@{ VirtualizationFirmwareEnabled = $false } }
        }
        Get-IchqVirtualisierung | Should -Be 'an'
    }
    It 'Virtualisierung im BIOS aus → aus' {
        Mock -ModuleName IchqServer Get-CimInstance {
            if ($ClassName -match 'ComputerSystem') { [pscustomobject]@{ HypervisorPresent = $false } }
            else { [pscustomobject]@{ VirtualizationFirmwareEnabled = $false } }
        }
        Get-IchqVirtualisierung | Should -Be 'aus'
    }
    It 'Virtualisierung: Abfrage scheitert → unbekannt (kein Abbruch)' {
        Mock -ModuleName IchqServer Get-CimInstance { throw 'WMI kaputt' }
        Get-IchqVirtualisierung | Should -Be 'unbekannt'
    }
}

Describe 'Pfade' {
    It '<W> → <L>' -ForEach @(
        @{ W = 'C:\Program Files\IC WARE HQ Server\quelle.tar'; L = '/mnt/c/Program Files/IC WARE HQ Server/quelle.tar' },
        @{ W = 'D:\x\y.tar'; L = '/mnt/d/x/y.tar' }
    ) { ConvertTo-IchqWslPfad $W | Should -Be $L }
    It 'ohne Laufwerk: Fehler' { { ConvertTo-IchqWslPfad '\\server\share\x' } | Should -Throw }
}

Describe 'Skript-Übergabe an Linux (über STDIN, nicht als Argument)' -Skip:($IsWindows -or -not (Get-Command bash -ErrorAction SilentlyContinue)) {
    BeforeAll {
        # Ersatz für wsl.exe (nur unter Linux-pwsh): verwirft „-d … -u root --" und führt den Rest aus; merkt sich
        # die Kommandozeile, damit geprüft werden kann, dass das Token NICHT darin steht.
        $script:Bin = Join-Path ([IO.Path]::GetTempPath()) "ichq-wsl-$([guid]::NewGuid())"
        $null = New-Item -ItemType Directory $script:Bin
        $script:Protokoll = Join-Path $script:Bin 'argv.txt'
        Set-Content (Join-Path $script:Bin 'wsl.exe') -Value @"
#!/usr/bin/env bash
printf '%s\n' "`$*" >> '$($script:Protokoll)'
while [ `$# -gt 0 ] && [ "`$1" != -- ]; do shift; done; shift
exec "`$@"
"@
        & chmod +x (Join-Path $script:Bin 'wsl.exe')
        $script:AlterPfad = $env:PATH
        $env:PATH = "$($script:Bin):$env:PATH"
    }
    AfterAll { $env:PATH = $script:AlterPfad; Remove-Item -Recurse -Force $script:Bin }

    It 'Windows-Zeilenenden (CRLF) stören nicht; Exitcode kommt zurück' {
        $aus = Join-Path $script:Bin 'aus.txt'
        Invoke-IchqLinux "printf '%s' ok > '$aus'`r`nexit 7`r`n" | Should -Be 7
        Get-Content $aus -Raw | Should -Be 'ok'
    }

    It 'Token steht nie in der Kommandozeile' {
        $aus = Join-Path $script:Bin 'token.txt'
        Invoke-IchqLinux "printf '%s' '$($script:Echt)' > '$aus'" | Should -Be 0
        Get-Content $aus -Raw | Should -Be $script:Echt
        Get-Content $script:Protokoll -Raw | Should -Not -Match ([regex]::Escape($script:Echt.Substring(0, 20)))
    }
}

Describe 'einrichten.ps1 -NurPruefen (ändert nichts)' {
    BeforeAll {
        $script:Einrichten = Join-Path $script:Ordner 'einrichten.ps1'
        $script:Exe = if ($IsWindows -or $PSVersionTable.PSEdition -eq 'Desktop') { 'powershell.exe' } else { 'pwsh' }
        function script:Lauf([string[]]$Argumente) {
            & $script:Exe -NoProfile -ExecutionPolicy Bypass -File $script:Einrichten @Argumente -NurPruefen *> $null
            return $LASTEXITCODE
        }
        $script:TokenDatei = Join-Path ([IO.Path]::GetTempPath()) "ichq-token-$([guid]::NewGuid()).txt"
    }
    It 'ungültige Domain → Abbruch' { Lauf @('-Domain', 'https://x.de', '-Email', 'a@b.de') | Should -Be 1 }
    It 'ungültige E-Mail → Abbruch' { Lauf @('-Domain', 'hq.firma.de', '-Email', 'kaputt') | Should -Be 1 }
    It 'ungültiges Token → Abbruch' {
        Set-Content $script:TokenDatei 'kein token'
        Lauf @('-Domain', 'hq.firma.de', '-Email', 'a@b.de', '-TokenDatei', $script:TokenDatei) | Should -Be 1
    }
    It 'Ersteinrichtung ohne Token → Abbruch' { Lauf @('-Domain', 'hq.firma.de', '-Email', 'a@b.de') | Should -Be 1 }
    It 'Schnellstart: ungültige E-Mail → Abbruch' { Lauf @('-Schnell', '-Email', 'kaputt') | Should -Be 1 }
    It 'ohne Schnellstart ist die Domain Pflicht' { Lauf @('-Email', 'a@b.de') | Should -Be 1 }
    It 'Schnellstart: weder Domain noch Token nötig (ADR-019)' -Skip:(-not $IsWindows) {
        Lauf @('-Schnell', '-Email', 'a@b.de') | Should -Be 0
    }
    It 'Schnellstart ignoriert eine eingeschleuste Domain' -Skip:(-not $IsWindows) {
        Lauf @('-Schnell', '-Email', 'a@b.de', '-Domain', "x.de'; rm -rf /") | Should -Be 0
    }
    It 'gültige Eingaben → Prüfung bestanden, Token-Datei bleibt (nichts geändert)' -Skip:(-not $IsWindows) {
        Set-Content $script:TokenDatei "cloudflared.exe service install $($script:Echt)"
        Lauf @('-Domain', 'hq.firma.de', '-Email', 'a@b.de', '-TokenDatei', $script:TokenDatei) | Should -Be 0
        Test-Path $script:TokenDatei | Should -BeTrue
        Remove-Item $script:TokenDatei
    }
}
