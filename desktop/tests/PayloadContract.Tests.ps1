BeforeAll {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $payloadPath = Join-Path $PSScriptRoot "../src-tauri/resources/app-payload.zip"
    if (-not (Test-Path -LiteralPath $payloadPath -PathType Leaf)) {
        throw "The assembled application payload is missing. Build the installer payload before running PayloadContract.Tests.ps1."
    }
    $script:payloadZip = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $payloadPath).Path)

    # Pester 5 executes test blocks in its own scope. Define this helper in
    # BeforeAll so each It block can resolve it while inspecting the shared ZIP.
    function Get-PayloadZipEntry([string]$ExpectedPath) {
        return $script:payloadZip.Entries |
            Where-Object { (($_.FullName -replace '\\', '/') -replace '^(\./)+', '') -eq $ExpectedPath } |
            Select-Object -First 1
    }
}

AfterAll {
    if ($script:payloadZip) {
        $script:payloadZip.Dispose()
    }
}

Describe "Assembled Clippy application payload contract" {
    It "contains every PowerShell helper imported by the runtime setup engine" {
        foreach ($entry in @(
            "setup-runtime.ps1",
            "runtime-archive.ps1",
            "runtime-health.ps1",
            "storage-path.ps1",
            "runtime-ffmpeg.ps1",
            "runtime-contract.json",
            "runtime-manifest-state.ps1",
            "VERSION",
            "requirements.txt"
        )) {
            Get-PayloadZipEntry $entry | Should -Not -BeNullOrEmpty -Because "the first-run runtime setup requires $entry"
        }
    }

    It "repairs an older managed Python runtime without the HTTP-only bgutil patch" {
        $setupSource = Get-Content (Join-Path $PSScriptRoot "../setup-runtime.ps1") -Raw
        $setupSource | Should -Match "getpot_bgutil_script"
        $setupSource | Should -Match "BgUtilHTTPPTP"
        $setupSource | Should -Match "bgutil HTTP provider must require an explicit managed base URL"
    }

    It "requires the packaged bgutil HTTP server and Express dependency during setup" {
        $setupSource = Get-Content (Join-Path $PSScriptRoot "../setup-runtime.ps1") -Raw
        $setupSource | Should -Match 'bgutil-provider\\server\\build\\main\.js'
        $setupSource | Should -Match 'bgutil-provider\\server\\node_modules\\express\\package\.json'
        $setupSource | Should -Not -Match 'bgutil-provider\\server\\build\\generate_once\.js'
    }

    It "contains every native-shell and first-run service entry point" {
        foreach ($entry in @(
            "app.py",
            "community_highlights/__init__.py",
            "community_highlights/api.py",
            "local_library.py",
            "render-service/dist/server.js",
            "render-service/node_modules/@remotion/renderer/package.json",
            "remotion/src/index.ts",
            "bgutil-provider/server/build/main.js",
            "bgutil-provider/server/package.json",
            "bgutil-provider/server/node_modules/express/package.json"
        )) {
            Get-PayloadZipEntry $entry | Should -Not -BeNullOrEmpty -Because "the installed desktop shell requires $entry"
        }
    }

    It "binds the packaged bgutil HTTP server to loopback only" {
        $entry = Get-PayloadZipEntry "bgutil-provider/server/build/main.js"
        $entry | Should -Not -BeNullOrEmpty
        $stream = $entry.Open()
        try {
            $reader = [IO.StreamReader]::new($stream)
            try { $serverSource = $reader.ReadToEnd() } finally { $reader.Dispose() }
        } finally {
            $stream.Dispose()
        }

        $serverSource | Should -Match '127\.0\.0\.1'
        $serverSource | Should -Not -Match '0\.0\.0\.0'
        $serverSource | Should -Not -Match 'host:\s*"::"'
        Get-PayloadZipEntry "bgutil-provider/server/node_modules/express/package.json" | Should -Not -BeNullOrEmpty
    }

    It "contains the current setup contract and helpers, not a stale build" {
        foreach ($relative in @('setup-runtime.ps1','runtime-health.ps1','storage-path.ps1','runtime-contract.json','runtime-archive.ps1','runtime-manifest-state.ps1','runtime-ffmpeg.ps1')) {
            $stream = (Get-PayloadZipEntry $relative).Open()
            $reader = [IO.StreamReader]::new($stream)
            try { $packaged = $reader.ReadToEnd() } finally { $reader.Dispose() }
            $source = Get-Content (Join-Path $PSScriptRoot "../$relative") -Raw
            $packaged | Should -Be $source -Because "$relative must be the exact source tested for this installer"
        }
    }

    It "packages only public Community Highlights OAuth client IDs" {
        $entry = Get-PayloadZipEntry "community-highlights-oauth.json"
        $entry | Should -Not -BeNullOrEmpty
        $stream = $entry.Open()
        try {
            $reader = [IO.StreamReader]::new($stream)
            try { $config = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        } finally {
            $stream.Dispose()
        }

        $config.schemaVersion | Should -Be 1
        $config.twitchClientId | Should -Be ([string]$env:CLIPPY_TWITCH_CLIENT_ID).Trim()
        $config.googleOauthClientId | Should -Be ([string]$env:CLIPPY_GOOGLE_OAUTH_CLIENT_ID).Trim()
        @($config.PSObject.Properties.Name) | Should -Be @("schemaVersion", "twitchClientId", "googleOauthClientId")
    }

    It "uses the persisted data directory for all user-data components" {
        $setupSource = Get-Content (Join-Path $PSScriptRoot "../setup-runtime.ps1") -Raw
        $setupSource | Should -Match 'storage-location\.json'
        $setupSource | Should -Match 'ConvertTo-ClippyPowerShellPath'
        foreach ($component in @("output", "uploads", "models")) {
            $pattern = 'Join-Path \$DataRoot "' + [regex]::Escape($component) + '"'
            $setupSource | Should -Match $pattern
        }
        $setupSource | Should -Match 'Join-Path \$DataRoot ''reference_templates'''
        $setupSource | Should -Not -Match 'Join-Path \$Root "data\\(output|uploads|models|reference_templates)"'
    }

    It "smoke-tests runtime setup with a relocated data directory" {
        $smokeSource = Get-Content (Join-Path $PSScriptRoot "../smoke-test-runtime.ps1") -Raw
        $smokeSource | Should -Match 'external-clippy-data'
        $smokeSource | Should -Match '\$legacyExtendedDataRoot'
        $smokeSource | Should -Match 'storage-location\.json'
        $smokeSource | Should -Match '\$env:CLIPPY_DATA_DIR = \$dataRoot'
        $smokeSource | Should -Match 'unexpectedly created a default data folder'
        $smokeSource | Should -Match 'community_highlights\\__init__\.py'
        $smokeSource | Should -Match 'community_highlights\\api\.py'
    }

    It "packages the helper scripts next to setup-runtime.ps1" {
        $setupEntry = Get-PayloadZipEntry "setup-runtime.ps1"
        $stream = $setupEntry.Open()
        try {
            $reader = [System.IO.StreamReader]::new($stream)
            try { $setupSource = $reader.ReadToEnd() } finally { $reader.Dispose() }
        } finally {
            $stream.Dispose()
        }

        foreach ($helper in @("runtime-manifest-state.ps1", "runtime-archive.ps1", "runtime-ffmpeg.ps1", "storage-path.ps1")) {
            $setupSource | Should -Match ([regex]::Escape($helper))
            Get-PayloadZipEntry $helper | Should -Not -BeNullOrEmpty
        }
    }
}
