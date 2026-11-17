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
