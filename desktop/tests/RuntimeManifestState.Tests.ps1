BeforeAll {
    . (Join-Path $PSScriptRoot "../runtime-manifest-state.ps1")
    $fixturePath = Join-Path $PSScriptRoot "fixtures/runtime-manifest-state.txt"
    $expectedState = (Get-Content -LiteralPath $fixturePath -Raw).Trim()
    $expectedCudaState = (Get-Content -LiteralPath (Join-Path $PSScriptRoot "fixtures/runtime-manifest-state-cuda.txt") -Raw).Trim()
}

Describe "PowerShell runtime manifest contract" {
    It "emits the exact state consumed by the Rust validator" {
        $state = New-ClippyRuntimeState -PythonVersion "3.12.10" -PythonVariant "cpu" -NodeVersion "22.23.3" -FfmpegVersion "gyan-release-essentials" -BrowserVersion "4.0.0" -RequirementsSha256 "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        $state | Should -Be $expectedState
    }

    It "emits the CUDA variant without changing the component schema" {
        $state = New-ClippyRuntimeState -PythonVersion "3.12.10" -PythonVariant "cuda" -NodeVersion "22.23.3" -FfmpegVersion "gyan-release-essentials" -BrowserVersion "4.0.0" -RequirementsSha256 "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        $state | Should -Be $expectedCudaState
    }

    It "rejects a Python runtime that does not match the pinned version" {
        { Assert-ClippyPythonRuntimeVersion -Actual "Python 3.11.9" -Expected "3.12.10" } | Should -Throw
    }

    It "accepts the pinned Python runtime version" {
        { Assert-ClippyPythonRuntimeVersion -Actual "Python 3.12.10" -Expected "3.12.10" } | Should -Not -Throw
    }
}
