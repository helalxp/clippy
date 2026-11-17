$ErrorActionPreference = 'Stop'
$previousApiUrl = $env:VITE_API_URL
Push-Location $PSScriptRoot
try {
    # The supervisor supplies the allocated API address before mounting the UI.
    $env:VITE_API_URL = ''
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Desktop dashboard build failed (exit $LASTEXITCODE)." }
} finally {
    $env:VITE_API_URL = $previousApiUrl
    Pop-Location
}
