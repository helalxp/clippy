$ErrorActionPreference = "Stop"

# Set Rust toolchain in PATH
$env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"

# Build dashboard first
Write-Host "Building dashboard..."
cd D:\openshorts\dashboard
npm run build
if ($LASTEXITCODE -ne 0) {
    Write-Host "Dashboard build failed with exit code $LASTEXITCODE"
    exit 1
}

# Now build Tauri desktop
Write-Host "`nBuilding Tauri desktop..."
cd D:\openshorts\desktop\src-tauri
cargo build
if ($LASTEXITCODE -ne 0) {
    Write-Host "Tauri build failed with exit code $LASTEXITCODE"
    exit 1
}

Write-Host "`n✓ Build complete!"
