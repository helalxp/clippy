Describe 'Runtime repair regressions' {
    It 'checks broken executables, timeouts, rollback and writable scratch' {
        & (Join-Path $PSScriptRoot '../test-runtime-contract.ps1')
    }
}
