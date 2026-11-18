$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$dashboard = Join-Path $repoRoot 'dashboard'
$tauri = Join-Path $repoRoot 'desktop/src-tauri'

Push-Location $dashboard
try {
    npm install --package-lock-only
    if ($LASTEXITCODE -ne 0) { throw 'Could not refresh dashboard/package-lock.json.' }
} finally {
    Pop-Location
}

Push-Location $tauri
try {
    cargo check
    if ($LASTEXITCODE -ne 0) { throw 'Cargo dependency resolution or compilation failed.' }
    cargo check --locked
    if ($LASTEXITCODE -ne 0) { throw 'Cargo.lock is not reproducible after refresh.' }
} finally {
    Pop-Location
}

Write-Host 'Updater dependency lockfiles are refreshed and Cargo lockfile validation passed.'
