param(
    [string]$RuntimeDirectory = (Join-Path $PSScriptRoot "runtime-dist"),
    [string]$ExpectedVersion = ""
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "runtime-archive.ps1")

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ExpectedVersion)) {
    $ExpectedVersion = (Get-Content -LiteralPath (Join-Path $repoRoot "VERSION") -Raw).Trim()
}
if ($ExpectedVersion -match '^v') { $ExpectedVersion = $ExpectedVersion.Substring(1) }
if ($ExpectedVersion -notmatch '^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$') {
    throw "Expected application version is invalid: $ExpectedVersion"
}
if (-not (Test-Path -LiteralPath $RuntimeDirectory -PathType Container)) {
    throw "Runtime release directory does not exist: $RuntimeDirectory"
}

foreach ($variant in @("cpu", "cuda")) {
    $manifestPath = Join-Path $RuntimeDirectory "clippy-python-$variant.manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "Missing $variant runtime manifest: $manifestPath"
    }
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    } catch {
        throw "Runtime manifest is invalid JSON: $manifestPath"
    }
    Assert-ClippyRuntimeArchiveManifest -Manifest $manifest -ExpectedApplicationVersion $ExpectedVersion -ExpectedVariant $variant | Out-Null
    foreach ($part in @($manifest.parts)) {
        $partPath = Join-Path $RuntimeDirectory ([string]$part.name)
        if (-not (Test-Path -LiteralPath $partPath -PathType Leaf)) {
            throw "Missing $variant runtime release asset: $($part.name)"
        }
        $info = Get-Item -LiteralPath $partPath
        if ($info.Length -ne [long]$part.size -or (Get-ClippyFileSha256 $partPath) -ne ([string]$part.sha256).ToLowerInvariant()) {
            throw "Runtime release asset failed size or SHA-256 verification: $($part.name)"
        }
    }
    $reconstructed = Join-Path $RuntimeDirectory "clippy-python-$variant.ci-verified.zip"
    Join-ClippyRuntimeArchiveParts -Manifest $manifest -PartsDirectory $RuntimeDirectory -Destination $reconstructed | Out-Null
    Remove-Item -LiteralPath $reconstructed -Force
    Write-Host "$variant runtime manifest and $($manifest.partCount) asset(s) verified for v$ExpectedVersion."
}
