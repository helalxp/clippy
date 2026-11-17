Describe 'Runtime repair regressions' {
    It 'checks broken executables, timeouts, rollback and writable scratch' {
        & (Join-Path $PSScriptRoot '../test-runtime-contract.ps1')
    }
}


Describe 'Runtime SHA-256 helper' {
    BeforeAll {
        . (Join-Path $PSScriptRoot '../runtime-health.ps1')
    }

    It 'calculates the standard SHA-256 digest without PowerShell utility cmdlets' {
        $path = [System.IO.Path]::GetTempFileName()
        try {
            [System.IO.File]::WriteAllText($path, 'abc')
            (Get-ClippyFileSha256 -Path $path) | Should -Be 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
        } finally {
            Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
        }
    }

    It 'fails clearly when the target file is missing' {
        { Get-ClippyFileSha256 -Path (Join-Path $TestDrive 'missing-runtime-file.bin') } | Should -Throw '*does not exist*'
    }
}
