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


Describe "Managed runtime directory transaction contract" {
    BeforeEach {
        $script:transactionRoot = Join-Path ([IO.Path]::GetTempPath()) ("clippy-install-transaction-" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $script:transactionRoot -Force | Out-Null
        $script:transactionDestination = Join-Path $script:transactionRoot "runtime"
        $script:transactionStaging = Join-Path $script:transactionRoot "runtime.installing"
        $script:transactionBackup = Join-Path $script:transactionRoot "runtime.previous"
    }

    AfterEach {
        if (Test-Path -LiteralPath $script:transactionRoot) {
            Remove-Item -LiteralPath $script:transactionRoot -Recurse -Force
        }
    }

    It "activates a validated staged directory and retains the previous directory until commit" {
        New-Item -ItemType Directory -Path $script:transactionDestination -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $script:transactionDestination "version.txt") -Value "old"
        New-Item -ItemType Directory -Path $script:transactionStaging -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $script:transactionStaging "version.txt") -Value "new"

        Publish-ClippyManagedDirectoryInstall -Destination $script:transactionDestination -Staging $script:transactionStaging -Backup $script:transactionBackup -MarkerValue "version=2"

        (Get-Content -LiteralPath (Join-Path $script:transactionDestination "version.txt") -Raw).Trim() | Should -Be "new"
        (Test-Path -LiteralPath (Join-Path $script:transactionDestination ".clippy-install-state")) | Should -BeTrue
        (Get-Content -LiteralPath (Join-Path $script:transactionBackup "version.txt") -Raw).Trim() | Should -Be "old"

        Complete-ClippyManagedDirectoryInstall -Backup $script:transactionBackup
        (Test-Path -LiteralPath $script:transactionBackup) | Should -BeFalse
    }

    It "restores the previous directory when activation was interrupted before the marker move" {
        New-Item -ItemType Directory -Path $script:transactionBackup -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $script:transactionBackup "version.txt") -Value "previous"
        New-Item -ItemType Directory -Path $script:transactionDestination -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $script:transactionDestination "partial.txt") -Value "incomplete"
        New-Item -ItemType Directory -Path $script:transactionStaging -Force | Out-Null

        Repair-ClippyManagedDirectoryInstall -Destination $script:transactionDestination -Staging $script:transactionStaging -Backup $script:transactionBackup

        (Get-Content -LiteralPath (Join-Path $script:transactionDestination "version.txt") -Raw).Trim() | Should -Be "previous"
        (Test-Path -LiteralPath (Join-Path $script:transactionDestination "partial.txt")) | Should -BeFalse
        (Test-Path -LiteralPath $script:transactionStaging) | Should -BeFalse
        (Test-Path -LiteralPath $script:transactionBackup) | Should -BeFalse
    }

    It "keeps a committed new directory and removes a stale backup after a restart" {
        New-Item -ItemType Directory -Path $script:transactionDestination -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $script:transactionDestination ".clippy-install-state") -Value "version=2"
        Set-Content -LiteralPath (Join-Path $script:transactionDestination "version.txt") -Value "new"
        New-Item -ItemType Directory -Path $script:transactionBackup -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $script:transactionBackup "version.txt") -Value "old"

        Repair-ClippyManagedDirectoryInstall -Destination $script:transactionDestination -Staging $script:transactionStaging -Backup $script:transactionBackup

        (Get-Content -LiteralPath (Join-Path $script:transactionDestination "version.txt") -Raw).Trim() | Should -Be "new"
        (Test-Path -LiteralPath $script:transactionBackup) | Should -BeFalse
    }

    It "keeps a committed directory from an older version so normal health checks can upgrade it" {
        New-Item -ItemType Directory -Path $script:transactionDestination -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $script:transactionDestination ".clippy-install-state") -Value "version=1"
        Set-Content -LiteralPath (Join-Path $script:transactionDestination "version.txt") -Value "previously-validated"
        New-Item -ItemType Directory -Path $script:transactionBackup -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $script:transactionBackup "version.txt") -Value "older-backup"

        Repair-ClippyManagedDirectoryInstall -Destination $script:transactionDestination -Staging $script:transactionStaging -Backup $script:transactionBackup

        (Get-Content -LiteralPath (Join-Path $script:transactionDestination "version.txt") -Raw).Trim() | Should -Be "previously-validated"
        (Test-Path -LiteralPath $script:transactionBackup) | Should -BeFalse
    }

    It "rolls back a failed post-activation health check" {
        New-Item -ItemType Directory -Path $script:transactionDestination -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $script:transactionDestination "version.txt") -Value "old"
        New-Item -ItemType Directory -Path $script:transactionStaging -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $script:transactionStaging "version.txt") -Value "new"

        Publish-ClippyManagedDirectoryInstall -Destination $script:transactionDestination -Staging $script:transactionStaging -Backup $script:transactionBackup -MarkerValue "version=2"
        Rollback-ClippyManagedDirectoryInstall -Destination $script:transactionDestination -Backup $script:transactionBackup

        (Get-Content -LiteralPath (Join-Path $script:transactionDestination "version.txt") -Raw).Trim() | Should -Be "old"
        (Test-Path -LiteralPath $script:transactionBackup) | Should -BeFalse
    }

    It "rejects staging and destination paths that are not sibling directories" {
        $outsideStage = Join-Path ([IO.Path]::GetTempPath()) ("clippy-outside-stage-" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $script:transactionStaging -Force | Out-Null
        try {
            { Publish-ClippyManagedDirectoryInstall -Destination $script:transactionDestination -Staging $outsideStage -Backup $script:transactionBackup -MarkerValue "version=2" } | Should -Throw
        } finally {
            if (Test-Path $outsideStage) { Remove-Item $outsideStage -Recurse -Force }
        }
    }
}
