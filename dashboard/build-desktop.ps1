$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# Keep the public web build untouched. Only the Tauri desktop bundle receives
# the loopback API origin because the packaged UI is not served by Vite's proxy.
$env:VITE_API_URL = 'http://127.0.0.1:8000'
npm run build
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
