$ErrorActionPreference = "Stop"

# Build dashboard first
Write-Host "Building dashboard..."
cd D:\openshorts\dashboard
npm run build

# Now build Tauri desktop
Write-Host "Building Tauri desktop..."
cd D:\openshorts\desktop\src-tauri
cargo build

Write-Host "Build complete!"
