$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$tauriRoot = Join-Path $PSScriptRoot "src-tauri"
$stageRoot = Join-Path $tauriRoot "resources\app-payload-stage"
$resourceRoot = Join-Path $tauriRoot "resources"
$archive = Join-Path $resourceRoot "app-payload.zip"
$renderDir = Join-Path $repoRoot "render-service"
$remotionDir = Join-Path $repoRoot "remotion"

function Invoke-Checked([string]$File, [string[]]$Arguments, [string]$WorkingDirectory) {
    Push-Location $WorkingDirectory
    try {
        & $File @Arguments
        if ($LASTEXITCODE -ne 0) { throw "$File failed with exit code $LASTEXITCODE." }
    } finally {
        Pop-Location
    }
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "Node.js/npm is required to prepare the renderer payload."
}

Write-Host "Preparing the renderer runtime payload..."
Invoke-Checked "npm" @("ci") $renderDir
Invoke-Checked "npm" @("run", "build") $renderDir
Invoke-Checked "npm" @("prune", "--omit=dev") $renderDir
Invoke-Checked "npm" @("install", "--omit=dev", "--no-package-lock") $remotionDir

if (-not (Test-Path (Join-Path $renderDir "dist\server.js"))) {
    throw "Renderer build did not produce render-service\dist\server.js."
}
if (-not (Test-Path (Join-Path $remotionDir "src\index.ts"))) {
    throw "Remotion entry point is missing."
}

if (Test-Path $stageRoot) { Remove-Item $stageRoot -Recurse -Force }
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null

# Include all top-level Python modules because app.py imports the pipeline as
# sibling modules and launches several of them as subprocesses.
Get-ChildItem $repoRoot -File -Filter "*.py" | Copy-Item -Destination $stageRoot
Copy-Item (Join-Path $repoRoot "requirements.txt") -Destination $stageRoot
Copy-Item (Join-Path $PSScriptRoot "setup-runtime.ps1") -Destination $stageRoot

$directories = @("assets", "fonts", "reference_templates", "render-service", "remotion", "bin")
foreach ($name in $directories) {
    $source = Join-Path $repoRoot $name
    if (Test-Path $source) {
        Copy-Item $source -Destination $stageRoot -Recurse
    }
}

# Remove development-only files while retaining package locks and production
# node_modules needed by the renderer and Remotion bundler.
Get-ChildItem $stageRoot -Directory -Recurse -Force |
    Where-Object { $_.Name -in @(".git", ".cache", "coverage", "test", "tests") } |
    Sort-Object FullName -Descending |
    ForEach-Object { if (Test-Path $_.FullName) { Remove-Item $_.FullName -Recurse -Force } }

if (Test-Path $archive) { Remove-Item $archive -Force }
Compress-Archive -Path (Join-Path $stageRoot "*") -DestinationPath $archive -CompressionLevel Optimal
Remove-Item $stageRoot -Recurse -Force

$hash = (Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant()
$size = (Get-Item $archive).Length
Write-Host "Application payload ready: $archive"
Set-Content -Path (Join-Path $resourceRoot "app-payload.sha256") -Value $hash -NoNewline
Write-Host "SHA256: $hash"
Write-Host "Size: $size bytes"
