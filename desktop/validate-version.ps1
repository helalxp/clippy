param([string]$ExpectedVersion = "")
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
function Read-Text([string]$RelativePath) {
    $path = Join-Path $repoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Version metadata file is missing: $RelativePath" }
    return Get-Content -LiteralPath $path -Raw
}
$canonical = (Read-Text "VERSION").Trim()
if ($canonical -notmatch '^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$') { throw "VERSION must be valid SemVer. Found: '$canonical'" }
$tauri = (Read-Text "desktop/src-tauri/tauri.conf.json" | ConvertFrom-Json).version
$cargo = [regex]::Match((Read-Text "desktop/src-tauri/Cargo.toml"), '(?m)^version\s*=\s*"([^"]+)"').Groups[1].Value
$dashboard = (Read-Text "dashboard/package.json" | ConvertFrom-Json).version
$dashboardLock = (Read-Text "dashboard/package-lock.json" | ConvertFrom-Json).packages[""].version
$cargoLock = Read-Text "desktop/src-tauri/Cargo.lock"
$cargoMatch = [regex]::Match($cargoLock, '(?s)\[\[package\]\]\s*name\s*=\s*"clippy-desktop"\s*version\s*=\s*"([^"]+)"')
if (-not $cargoMatch.Success) { throw "Could not find clippy-desktop in Cargo.lock." }
$versions = [ordered]@{ "Tauri bundle"=$tauri; "Rust package"=$cargo; "Rust lockfile"=$cargoMatch.Groups[1].Value; "Dashboard package"=$dashboard; "Dashboard lockfile"=$dashboardLock }
$bad = @($versions.GetEnumerator() | Where-Object { $_.Value -ne $canonical })
if ($bad.Count -gt 0) {
    $details = ($bad | ForEach-Object { "$($_.Key): $($_.Value)" }) -join [Environment]::NewLine
    throw ("Clippy version mismatch. VERSION=" + $canonical + [Environment]::NewLine + $details)
}
if ($ExpectedVersion) {
    $expected = $ExpectedVersion.Trim().TrimStart('v')
    if ($expected -ne $canonical) { throw "Release tag '$expected' does not match VERSION '$canonical'." }
}
Write-Host "Clippy version $canonical is synchronized across all manifests." -ForegroundColor Green
