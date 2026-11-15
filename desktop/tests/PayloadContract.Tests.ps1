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
            "runtime-manifest-state.ps1",
            "VERSION",
            "requirements.txt"
        )) {
            Get-PayloadZipEntry $entry | Should -Not -BeNullOrEmpty -Because "the first-run runtime setup requires $entry"
        }
    }

    It "contains every native-shell and first-run service entry point" {
        foreach ($entry in @(
            "app.py",
            "render-service/dist/server.js",
            "render-service/node_modules/@remotion/renderer/package.json",
            "remotion/src/index.ts",
            "bgutil-provider/server/build/generate_once.js"
        )) {
            Get-PayloadZipEntry $entry | Should -Not -BeNullOrEmpty -Because "the installed desktop shell requires $entry"
        }
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

        foreach ($helper in @("runtime-manifest-state.ps1", "runtime-archive.ps1")) {
            $setupSource | Should -Match ([regex]::Escape($helper))
            Get-PayloadZipEntry $helper | Should -Not -BeNullOrEmpty
        }
    }
}
