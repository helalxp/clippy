$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$dashboardDir = Join-Path $repoRoot "dashboard"
$tauriDir = Join-Path $PSScriptRoot "src-tauri"

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
} finally {
    Pop-Location
}

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
