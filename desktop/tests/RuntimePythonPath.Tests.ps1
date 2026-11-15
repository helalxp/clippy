BeforeAll {
    $runtimeBuilderSource = Get-Content -LiteralPath (Join-Path $PSScriptRoot "../build-python-runtime.ps1") -Raw
    $supervisorSource = Get-Content -LiteralPath (Join-Path $PSScriptRoot "../src-tauri/src/supervisor.rs") -Raw
}

Describe "Embedded Python application import path contract" {
    It "adds the managed application payload to the isolated python312._pth file" {
        $runtimeBuilderSource | Should -Match ([regex]::Escape('$ApplicationRootRelativeToRuntime = "..\..\app\current"'))
        $runtimeBuilderSource | Should -Match ([regex]::Escape('$ApplicationRootRelativeToRuntime,'))
        $runtimeBuilderSource | Should -Match ([regex]::Escape('$PythonPathEntries'))
        $runtimeBuilderSource | Should -Match ([regex]::Escape('$AppSearchPathCheck'))
    }

    It "validates the resolved application search path with the packaged interpreter" {
        $runtimeBuilderSource | Should -Match 'os\.path\.dirname\(sys\.executable\)'
        $runtimeBuilderSource | Should -Match 'sys\.path'
        $runtimeBuilderSource | Should -Match "does not expose Clippy's application payload"
    }

    It "does not rely on PYTHONPATH for the Rust-launched backend" {
        $supervisorSource | Should -Not -Match ([regex]::Escape('.env("PYTHONPATH", &paths.root)'))
        $supervisorSource | Should -Match 'python312\._pth'
    }
}
