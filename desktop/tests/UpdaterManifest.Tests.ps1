Describe "Clippy Tauri updater manifest" {
    BeforeAll {
        $scriptPath = Join-Path $PSScriptRoot "..\create-updater-manifest.ps1"
        $fixtureRoot = Join-Path $TestDrive "updater-manifest"
        New-Item -ItemType Directory -Path $fixtureRoot -Force | Out-Null

        $script:installerPath = Join-Path $fixtureRoot "Clippy_1.2.3_x64-setup.exe"
        $script:signaturePath = "$script:installerPath.sig"
        $script:notesPath = Join-Path $fixtureRoot "release-notes.md"
        $script:manifestPath = Join-Path $fixtureRoot "latest.json"

        [System.IO.File]::WriteAllBytes($script:installerPath, [byte[]](1, 2, 3))
        [System.IO.File]::WriteAllText($script:signaturePath, "signature-line-one`nsignature-line-two`n")
        [System.IO.File]::WriteAllText($script:notesPath, "# Clippy 1.2.3`n`nRelease notes.")
    }

    It "writes the final installer URL, signature, release notes, and SemVer version" {
        & $scriptPath -ReleaseTag "v1.2.3" -Repository "helalxp/clippy" -InstallerPath $script:installerPath -SignaturePath $script:signaturePath -ReleaseNotesPath $script:notesPath -OutputPath $script:manifestPath

        $manifest = Get-Content -LiteralPath $script:manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $manifest.version | Should -Be "1.2.3"
        $manifest.platforms.'windows-x86_64'.url | Should -Be "https://github.com/helalxp/clippy/releases/download/v1.2.3/Clippy_1.2.3_x64-setup.exe"
        $manifest.platforms.'windows-x86_64'.signature | Should -Be "signature-line-one`nsignature-line-two"
        $manifest.notes | Should -Be "# Clippy 1.2.3`n`nRelease notes."
        { [DateTimeOffset]::Parse($manifest.pub_date) } | Should -Not -Throw
    }

    It "rejects a release tag that is not SemVer" {
        {
            & $scriptPath -ReleaseTag "v1.2" -Repository "helalxp/clippy" -InstallerPath $script:installerPath -SignaturePath $script:signaturePath -ReleaseNotesPath $script:notesPath -OutputPath $script:manifestPath
        } | Should -Throw "*valid SemVer*"
    }

    It "rejects an empty Tauri signature" {
        $emptySignaturePath = Join-Path $TestDrive "empty.sig"
        [System.IO.File]::WriteAllText($emptySignaturePath, "")

        {
            & $scriptPath -ReleaseTag "v1.2.3" -Repository "helalxp/clippy" -InstallerPath $script:installerPath -SignaturePath $emptySignaturePath -ReleaseNotesPath $script:notesPath -OutputPath $script:manifestPath
        } | Should -Throw "*signature is empty*"
    }
}
