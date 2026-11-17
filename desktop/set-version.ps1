[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version
)

$ErrorActionPreference = "Stop"
$Version = $Version.Trim() -replace '^v', ''
if ($Version -notmatch '^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$') {
    throw "Version must be valid SemVer (optionally prefixed with v). Found: '$Version'."
}

$repoRoot = Split-Path -Parent $PSScriptRoot

function Read-RepoText([string]$RelativePath) {
    $path = Join-Path $repoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required version metadata file is missing: $RelativePath"
    }
    return [System.IO.File]::ReadAllText($path)
}

function Write-RepoText([string]$RelativePath, [string]$Content) {
    $path = Join-Path $repoRoot $RelativePath
    [System.IO.File]::WriteAllText($path, $Content, [System.Text.UTF8Encoding]::new($false))
}

# Update the canonical source first, then every package/build manifest that
# embeds the application version. Dependency versions are intentionally untouched.
Write-RepoText "VERSION" ($Version + [Environment]::NewLine)

$tauri = Read-RepoText "desktop/src-tauri/tauri.conf.json"
$tauriObject = $tauri | ConvertFrom-Json
$tauriObject.version = $Version
Write-RepoText "desktop/src-tauri/tauri.conf.json" (($tauriObject | ConvertTo-Json -Depth 100) + [Environment]::NewLine)

$cargoToml = Read-RepoText "desktop/src-tauri/Cargo.toml"
$packageSection = [regex]::Match($cargoToml, '(?ms)^\[package\]\s*\r?\n(?<body>.*?)(?=^\[|\z)')
if (-not $packageSection.Success) { throw "Could not find the [package] section in desktop/src-tauri/Cargo.toml." }
$versionLine = [regex]::Matches($packageSection.Groups['body'].Value, '(?m)^version\s*=\s*"[^"]+"\s*$')
if ($versionLine.Count -ne 1) { throw "Expected exactly one package version in desktop/src-tauri/Cargo.toml." }
$updatedPackageBody = [regex]::Replace($packageSection.Groups['body'].Value, '(?m)^(version\s*=\s*")[^"]+(")', ('$1' + $Version + '$2'), 1)
$cargoToml = $cargoToml.Substring(0, $packageSection.Groups['body'].Index) + $updatedPackageBody + $cargoToml.Substring($packageSection.Groups['body'].Index + $packageSection.Groups['body'].Length)
Write-RepoText "desktop/src-tauri/Cargo.toml" $cargoToml

$cargoLock = Read-RepoText "desktop/src-tauri/Cargo.lock"
$cargoLockPattern = '(?m)(^\[\[package\]\]\r?\nname = "clippy-desktop"\r?\nversion = ")[^"]+(")'
if ([regex]::Matches($cargoLock, $cargoLockPattern).Count -ne 1) { throw "Expected exactly one clippy-desktop entry in Cargo.lock." }
$cargoLock = [regex]::Replace($cargoLock, $cargoLockPattern, ('$1' + $Version + '$2'), 1)
Write-RepoText "desktop/src-tauri/Cargo.lock" $cargoLock

$dashboard = Read-RepoText "dashboard/package.json" | ConvertFrom-Json
$dashboard.version = $Version
Write-RepoText "dashboard/package.json" (($dashboard | ConvertTo-Json -Depth 100) + [Environment]::NewLine)

$dashboardLock = Read-RepoText "dashboard/package-lock.json"
$dashboardLockPattern = '(?s)("packages"\s*:\s*\{\s*""\s*:\s*\{.*?"version"\s*:\s*")[^"]+(")'
if ([regex]::Matches($dashboardLock, $dashboardLockPattern).Count -ne 1) { throw "Expected exactly one root package version in dashboard/package-lock.json." }
$dashboardLock = [regex]::Replace($dashboardLock, $dashboardLockPattern, ('$1' + $Version + '$2'), 1)
Write-RepoText "dashboard/package-lock.json" $dashboardLock

& (Join-Path $PSScriptRoot "validate-version.ps1") -ExpectedVersion $Version
if ($LASTEXITCODE -ne 0) { throw "Version synchronization validation failed." }
Write-Host "Updated all Clippy application version metadata to $Version." -ForegroundColor Green
