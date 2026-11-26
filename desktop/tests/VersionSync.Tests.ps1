Describe "Clippy application version synchronization" {
    BeforeAll {
        $scriptPath = Join-Path $PSScriptRoot "..\set-version.ps1"

        function New-FixtureText([string[]]$Lines) {
            return [string]::Join([Environment]::NewLine, $Lines) + [Environment]::NewLine
        }

        function New-VersionFixture([string]$Root) {
            foreach ($directory in @("desktop/src-tauri", "dashboard")) {
                New-Item -ItemType Directory -Path (Join-Path $Root $directory) -Force | Out-Null
            }

            $tauri = New-FixtureText @(
                '{',
                '  "version": "1.2.3",',
                '  "productName": "Clippy"',
                '}'
            )
            $cargoToml = New-FixtureText @(
                '[package]',
                'name = "clippy-desktop"',
                'version = "1.2.3"',
                'edition = "2021"',
                '',
                '[dependencies]',
                'serde = "1"'
            )
            $cargoLock = New-FixtureText @(
                '[[package]]',
                'name = "another-package"',
                'version = "8.8.8"',
                '',
                '[[package]]',
                'name = "clippy-desktop"',
                'version = "1.2.3"',
                'dependencies = ["serde"]'
            )
            $dashboard = New-FixtureText @(
                '{',
                '  "name": "openshorts-app",',
                '  "version": "1.2.3",',
                '  "private": true',
                '}'
            )
            $dashboardLock = New-FixtureText @(
                '{',
                '  "name": "openshorts-app",',
                '  "version": "1.2.3",',
                '  "lockfileVersion": 2,',
                '  "requires": true,',
                '  "packages": {',
                '    "": {',
                '      "name": "openshorts-app",',
                '      "version": "1.2.3"',
                '    },',
                '    "node_modules/example": {',
                '      "version": "8.8.8"',
                '    }',
                '  }',
                '}'
            )

            [System.IO.File]::WriteAllText((Join-Path $Root "VERSION"), "1.2.3" + [Environment]::NewLine)
            [System.IO.File]::WriteAllText((Join-Path $Root "desktop/src-tauri/tauri.conf.json"), $tauri)
            [System.IO.File]::WriteAllText((Join-Path $Root "desktop/src-tauri/Cargo.toml"), $cargoToml)
            [System.IO.File]::WriteAllText((Join-Path $Root "desktop/src-tauri/Cargo.lock"), $cargoLock)
            [System.IO.File]::WriteAllText((Join-Path $Root "dashboard/package.json"), $dashboard)
            [System.IO.File]::WriteAllText((Join-Path $Root "dashboard/package-lock.json"), $dashboardLock)
        }
    }

    It "updates the canonical version and every Clippy manifest field without changing dependency versions" {
        $fixture = Join-Path $TestDrive "set-version"
        New-VersionFixture $fixture

        & $scriptPath "2.4.6-rc.2" -RootPath $fixture

        (Get-Content (Join-Path $fixture "VERSION") -Raw).Trim() | Should -Be "2.4.6-rc.2"
        (Get-Content (Join-Path $fixture "desktop/src-tauri/tauri.conf.json") -Raw | ConvertFrom-Json).version | Should -Be "2.4.6-rc.2"
        (Get-Content (Join-Path $fixture "dashboard/package.json") -Raw | ConvertFrom-Json).version | Should -Be "2.4.6-rc.2"

        $cargoToml = Get-Content (Join-Path $fixture "desktop/src-tauri/Cargo.toml") -Raw
        $cargoToml | Should -Match 'version = "2\.4\.6-rc\.2"'
        $cargoToml | Should -Match 'serde = "1"'

        $cargoLock = Get-Content (Join-Path $fixture "desktop/src-tauri/Cargo.lock") -Raw
        $cargoLock | Should -Match '(?s)name = "clippy-desktop"\s+version = "2\.4\.6-rc\.2"'
        $cargoLock | Should -Match '(?s)name = "another-package"\s+version = "8\.8\.8"'

        $dashboardLock = Get-Content (Join-Path $fixture "dashboard/package-lock.json") -Raw | ConvertFrom-Json -AsHashtable
        $dashboardLock.version | Should -Be "2.4.6-rc.2"
        $dashboardLock.packages[""].version | Should -Be "2.4.6-rc.2"
        $dashboardLock.packages["node_modules/example"].version | Should -Be "8.8.8"

        & $scriptPath -Check -RootPath $fixture
    }

    It "reads VERSION and synchronizes the manifests when no version argument is supplied" {
        $fixture = Join-Path $TestDrive "sync-existing-version"
        New-VersionFixture $fixture
        [System.IO.File]::WriteAllText((Join-Path $fixture "VERSION"), "3.5.7" + [Environment]::NewLine)

        & $scriptPath -RootPath $fixture

        (Get-Content (Join-Path $fixture "desktop/src-tauri/tauri.conf.json") -Raw | ConvertFrom-Json).version | Should -Be "3.5.7"
        (Get-Content (Join-Path $fixture "dashboard/package-lock.json") -Raw | ConvertFrom-Json -AsHashtable).packages[""].version | Should -Be "3.5.7"
    }

    It "rejects invalid SemVer before changing any files" {
        $fixture = Join-Path $TestDrive "invalid-version"
        New-VersionFixture $fixture
        $tauriPath = Join-Path $fixture "desktop/src-tauri/tauri.conf.json"
        $before = Get-Content $tauriPath -Raw

        { & $scriptPath "1.2" -RootPath $fixture } | Should -Throw "*valid SemVer*"

        (Get-Content (Join-Path $fixture "VERSION") -Raw).Trim() | Should -Be "1.2.3"
        (Get-Content $tauriPath -Raw) | Should -Be $before
    }

    It "checks for drift without modifying files" {
        $fixture = Join-Path $TestDrive "check-drift"
        New-VersionFixture $fixture
        $tauriPath = Join-Path $fixture "desktop/src-tauri/tauri.conf.json"
        $before = Get-Content $tauriPath -Raw
        [System.IO.File]::WriteAllText($tauriPath, $before.Replace("1.2.3", "9.9.9"))

        { & $scriptPath -Check -RootPath $fixture } | Should -Throw "*out of sync*"
        (Get-Content $tauriPath -Raw) | Should -Match '"version": "9\.9\.9"'
    }

    It "does not partially update files when a manifest is malformed" {
        $fixture = Join-Path $TestDrive "malformed-manifest"
        New-VersionFixture $fixture
        $tauriPath = Join-Path $fixture "desktop/src-tauri/tauri.conf.json"
        $before = Get-Content $tauriPath -Raw
        $cargoLockPath = Join-Path $fixture "desktop/src-tauri/Cargo.lock"
        $badLock = New-FixtureText @(
            '[[package]]',
            'name = "not-clippy"',
            'version = "1.2.3"'
        )
        [System.IO.File]::WriteAllText($cargoLockPath, $badLock)

        { & $scriptPath "2.4.6" -RootPath $fixture } | Should -Throw "*clippy-desktop Cargo.lock package*"
        (Get-Content (Join-Path $fixture "VERSION") -Raw).Trim() | Should -Be "1.2.3"
        (Get-Content $tauriPath -Raw) | Should -Be $before
    }
}
