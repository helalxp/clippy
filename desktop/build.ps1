$ErrorActionPreference = "Continue"

# Set Rust toolchain in PATH
$env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"

# Build dashboard first
Write-Host "Building dashboard..."
cd D:\openshorts\dashboard
npm run build 2>&1 | Write-Host
$dashboardExit = $LASTEXITCODE
if ($dashboardExit -ne 0) {
    Write-Host "Dashboard build failed with exit code $dashboardExit"
    exit $dashboardExit
}

# Now build Tauri desktop
Write-Host "`nBuilding Tauri desktop..."
cd D:\openshorts\desktop\src-tauri
cargo build 2>&1 | Write-Host
$tauriExit = $LASTEXITCODE
if ($tauriExit -ne 0) {
    Write-Host "Tauri build failed with exit code $tauriExit"
    exit $tauriExit
}

Write-Host "`nBuild complete!"
