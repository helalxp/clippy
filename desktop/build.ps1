$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$dashboardDir = Join-Path $repoRoot "dashboard"
$tauriDir = Join-Path $PSScriptRoot "src-tauri"

& (Join-Path $PSScriptRoot "validate-version.ps1")

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "Node.js/npm is required on the build machine."
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Rust/Cargo is required on the build machine."
}

if (-not (Get-Command cargo-tauri -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Tauri CLI 2..."
    cargo install tauri-cli --version "^2" --locked
    if ($LASTEXITCODE -ne 0) { throw "Tauri CLI installation failed (exit $LASTEXITCODE)." }
}

Write-Host "Installing dashboard dependencies..."
Push-Location $dashboardDir
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "Dashboard npm ci failed (exit $LASTEXITCODE)." }

    Write-Host "Building dashboard for the local Clippy API..."
    $previousApiUrl = $env:VITE_API_URL
    $env:VITE_API_URL = "http://127.0.0.1:8000"
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "Dashboard build failed (exit $LASTEXITCODE)." }
    } finally {
        $env:VITE_API_URL = $previousApiUrl
    }
} finally {
    Pop-Location
}

$dashboardDist = Join-Path $dashboardDir "dist"
if (-not (Test-Path (Join-Path $dashboardDist "index.html"))) {
    throw "Dashboard build did not produce dashboard\dist\index.html."
}

Write-Host "Staging the backend and renderer payload..."
& (Join-Path $PSScriptRoot "prepare-payload.ps1")
if ($LASTEXITCODE -ne 0) { throw "Application payload preparation failed (exit $LASTEXITCODE)." }

Write-Host "Building Windows NSIS installer..."
Push-Location $tauriDir
try {
    cargo tauri build --bundles nsis
    if ($LASTEXITCODE -ne 0) { throw "Tauri installer build failed (exit $LASTEXITCODE)." }
} finally {
    Pop-Location
}

$bundleDir = Join-Path $tauriDir "target\release\bundle\nsis"
if (-not (Test-Path $bundleDir)) {
    throw "Expected NSIS output directory was not created: $bundleDir"
}
Get-ChildItem $bundleDir -Filter "*.exe" | Select-Object -ExpandProperty FullName
