function New-ClippyRuntimeState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$PythonVersion,
        [Parameter(Mandatory = $true)][ValidateSet("cpu", "cuda")][string]$PythonVariant,
        [Parameter(Mandatory = $true)][string]$NodeVersion,
        [Parameter(Mandatory = $true)][string]$FfmpegVersion,
        [Parameter(Mandatory = $true)][string]$BrowserVersion,
        [Parameter(Mandatory = $true)][ValidatePattern("^[a-fA-F0-9]{64}$")][string]$RequirementsSha256
    )
    foreach ($value in @($PythonVersion, $NodeVersion, $FfmpegVersion, $BrowserVersion)) {
        if ([string]::IsNullOrWhiteSpace($value) -or $value.Contains(";") -or $value.Contains("=")) {
            throw "Runtime manifest component versions must be non-empty scalar values."
        }
    }
    return "python=$PythonVersion;pythonVariant=$PythonVariant;node=$NodeVersion;ffmpeg=$FfmpegVersion;browser=$BrowserVersion;requirements=$($RequirementsSha256.ToLowerInvariant())"
}

function Assert-ClippyPythonRuntimeVersion {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Actual,
        [Parameter(Mandatory = $true)][string]$Expected
    )
    $expectedText = "Python $Expected"
    if ($Actual.Trim() -ne $expectedText) {
        throw "Packaged Python version mismatch. Expected $expectedText, found $($Actual.Trim())."
    }
}


# Managed runtime directories are staged and verified before activation. These
# helpers preserve the previous directory across process termination and
# recover an interrupted rename transaction on the next setup attempt.
function Repair-ClippyManagedDirectoryInstall {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$Staging,
        [Parameter(Mandatory = $true)][string]$Backup,
        [Parameter(Mandatory = $true)][string]$ExpectedMarkerValue
    )

    $destinationPath = [IO.Path]::GetFullPath($Destination)
    $stagingPath = [IO.Path]::GetFullPath($Staging)
    $backupPath = [IO.Path]::GetFullPath($Backup)
    $parentPaths = @(
        [IO.Path]::GetDirectoryName($destinationPath),
        [IO.Path]::GetDirectoryName($stagingPath),
        [IO.Path]::GetDirectoryName($backupPath)
    )
    if ($parentPaths | Where-Object { -not [string]::Equals($_, $parentPaths[0], [StringComparison]::OrdinalIgnoreCase) }) {
        throw "Managed runtime install paths must be sibling directories on the same volume."
    }

    $markerPath = Join-Path $destinationPath ".clippy-install-state"
    if (Test-Path -LiteralPath $backupPath -PathType Container) {
        $destinationCommitted = $false
        if (Test-Path -LiteralPath $destinationPath -PathType Container -and
            Test-Path -LiteralPath $markerPath -PathType Leaf) {
            $markerValue = (Get-Content -LiteralPath $markerPath -Raw).Trim()
            $destinationCommitted = [string]::Equals($markerValue, $ExpectedMarkerValue, [StringComparison]::Ordinal)
        }

        if ($destinationCommitted) {
            # The new directory was completely staged and validated before its
            # activation marker was written. Keep it and remove the stale backup.
            Remove-Item -LiteralPath $backupPath -Recurse -Force -ErrorAction Stop
        } else {
            # A backup with no matching activation marker means the last swap
            # was interrupted. Restore the previous installation.
            if (Test-Path -LiteralPath $destinationPath) {
                Remove-Item -LiteralPath $destinationPath -Recurse -Force -ErrorAction Stop
            }
            Move-Item -LiteralPath $backupPath -Destination $destinationPath -ErrorAction Stop
        }
    }

    # Staging is never active. A leftover staging directory is an interrupted
    # extraction or a transaction that did not reach the activation rename.
    if (Test-Path -LiteralPath $stagingPath) {
        Remove-Item -LiteralPath $stagingPath -Recurse -Force -ErrorAction Stop
    }
}

function Publish-ClippyManagedDirectoryInstall {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$Staging,
        [Parameter(Mandatory = $true)][string]$Backup,
        [Parameter(Mandatory = $true)][string]$MarkerValue
    )

    if ([string]::IsNullOrWhiteSpace($MarkerValue)) {
        throw "Managed runtime activation requires a non-empty validation marker."
    }
    $destinationPath = [IO.Path]::GetFullPath($Destination)
    $stagingPath = [IO.Path]::GetFullPath($Staging)
    $backupPath = [IO.Path]::GetFullPath($Backup)
    $parentPaths = @(
        [IO.Path]::GetDirectoryName($destinationPath),
        [IO.Path]::GetDirectoryName($stagingPath),
        [IO.Path]::GetDirectoryName($backupPath)
    )
    if ($parentPaths | Where-Object { -not [string]::Equals($_, $parentPaths[0], [StringComparison]::OrdinalIgnoreCase) }) {
        throw "Managed runtime install paths must be sibling directories on the same volume."
    }
    if (-not (Test-Path -LiteralPath $stagingPath -PathType Container)) {
        throw "Verified managed runtime staging directory is missing: $stagingPath"
    }
    if (Test-Path -LiteralPath $backupPath) {
        throw "Managed runtime backup still exists. Run transaction recovery before publishing: $backupPath"
    }

    $markerPath = Join-Path $stagingPath ".clippy-install-state"
    [IO.File]::WriteAllText($markerPath, $MarkerValue, [Text.UTF8Encoding]::new($false))
    if (Test-Path -LiteralPath $destinationPath) {
        Move-Item -LiteralPath $destinationPath -Destination $backupPath -ErrorAction Stop
    }
    try {
        Move-Item -LiteralPath $stagingPath -Destination $destinationPath -ErrorAction Stop
    } catch {
        if (Test-Path -LiteralPath $destinationPath) {
            Remove-Item -LiteralPath $destinationPath -Recurse -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $backupPath -PathType Container) {
            Move-Item -LiteralPath $backupPath -Destination $destinationPath -ErrorAction SilentlyContinue
        }
        throw
    }
}

function Complete-ClippyManagedDirectoryInstall {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Backup)

    if (Test-Path -LiteralPath $Backup -PathType Container) {
        Remove-Item -LiteralPath $Backup -Recurse -Force -ErrorAction Stop
    }
}

function Rollback-ClippyManagedDirectoryInstall {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$Backup
    )

    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force -ErrorAction Stop
    }
    if (Test-Path -LiteralPath $Backup -PathType Container) {
        Move-Item -LiteralPath $Backup -Destination $Destination -ErrorAction Stop
    }
}
