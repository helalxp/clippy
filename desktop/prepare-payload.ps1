$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$tauriRoot = Join-Path $PSScriptRoot "src-tauri"
$stageRoot = Join-Path $tauriRoot "resources\app-payload-stage"
$resourceRoot = Join-Path $tauriRoot "resources"
$archive = Join-Path $resourceRoot "app-payload.zip"
$renderDir = Join-Path $repoRoot "render-service"
$remotionDir = Join-Path $repoRoot "remotion"
$bgutilVersion = "1.3.2"
$bgutilSource = Join-Path $env:TEMP "clippy-bgutil-provider-$bgutilVersion"

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
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required to fetch the pinned bgutil YouTube token provider."
}

Write-Host "Preparing the renderer runtime payload..."
Invoke-Checked "npm" @("ci") $renderDir
Invoke-Checked "npm" @("run", "build") $renderDir
Invoke-Checked "npm" @("prune", "--omit=dev") $renderDir
Invoke-Checked "npm" @("ci", "--omit=dev") $remotionDir
$rendererVersion = (Get-Content (Join-Path $renderDir 'node_modules/@remotion/renderer/package.json') -Raw | ConvertFrom-Json).version
$contract = Get-Content (Join-Path $PSScriptRoot 'runtime-contract.json') -Raw | ConvertFrom-Json
$browserSource = Get-Content (Join-Path $renderDir 'node_modules/@remotion/renderer/dist/browser/get-chrome-download-url.js') -Raw
if ($browserSource -notmatch ("TESTED_VERSION\s*=\s*'" + [regex]::Escape($contract.browserVersion) + "'")) { throw 'Pinned browser contract differs from the renderer-tested browser; update and verify its hashes before release.' }
foreach ($name in @('remotion', '@remotion/media', '@remotion/player', '@remotion/cli', '@remotion/google-fonts', '@remotion/layout-utils')) {
    $version = (Get-Content (Join-Path $remotionDir "node_modules/$name/package.json") -Raw | ConvertFrom-Json).version
    if ($version -ne $rendererVersion) { throw "Remotion package $name ($version) differs from renderer $rendererVersion." }
}

if (-not (Test-Path (Join-Path $renderDir "dist\server.js"))) {
    throw "Renderer build did not produce render-service\dist\server.js."
}
if (-not (Test-Path (Join-Path $remotionDir "src\index.ts"))) {
    throw "Remotion entry point is missing."
}

if (Test-Path $stageRoot) { Remove-Item $stageRoot -Recurse -Force }
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null

# Build the same bgutil script provider used by the Docker image. The Python
# plugin is installed into the managed runtime from requirements.txt; this
# Node script and its production dependencies are shipped beside the app.
if (Test-Path $bgutilSource) { Remove-Item $bgutilSource -Recurse -Force }
Write-Host "Preparing pinned bgutil YouTube proof-of-origin token provider $bgutilVersion..."
& git clone --depth 1 --branch $bgutilVersion https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git $bgutilSource
if ($LASTEXITCODE -ne 0) { throw "Could not clone bgutil provider $bgutilVersion." }
$bgutilServer = Join-Path $bgutilSource "server"
Push-Location $bgutilServer
try {
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "bgutil provider npm ci failed (exit $LASTEXITCODE)." }
    npx tsc
    if ($LASTEXITCODE -ne 0) { throw "bgutil provider TypeScript build failed (exit $LASTEXITCODE)." }
    npm prune --omit=dev --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "bgutil provider production dependency pruning failed (exit $LASTEXITCODE)." }
} finally {
    Pop-Location
}
$bgutilPayload = Join-Path $stageRoot "bgutil-provider\server"
New-Item -ItemType Directory -Path $bgutilPayload -Force | Out-Null
Copy-Item (Join-Path $bgutilServer "build") -Destination $bgutilPayload -Recurse
Copy-Item (Join-Path $bgutilServer "node_modules") -Destination $bgutilPayload -Recurse
Copy-Item (Join-Path $bgutilServer "package.json") -Destination $bgutilPayload
if (-not (Test-Path (Join-Path $bgutilPayload "build\generate_once.js"))) {
    throw "bgutil provider payload is missing server/build/generate_once.js."
}
Remove-Item $bgutilSource -Recurse -Force

# Include all top-level Python modules and the Community Highlights package.
# app.py imports both at backend startup; omitting a package breaks first run.
Get-ChildItem $repoRoot -File -Filter "*.py" | Copy-Item -Destination $stageRoot
Copy-Item (Join-Path $repoRoot "requirements.txt") -Destination $stageRoot
Copy-Item (Join-Path $repoRoot "VERSION") -Destination $stageRoot
Copy-Item (Join-Path $PSScriptRoot "setup-runtime.ps1") -Destination $stageRoot
Copy-Item (Join-Path $PSScriptRoot "runtime-archive.ps1") -Destination $stageRoot
Copy-Item (Join-Path $PSScriptRoot "runtime-manifest-state.ps1") -Destination $stageRoot
Copy-Item (Join-Path $PSScriptRoot "runtime-health.ps1") -Destination $stageRoot
Copy-Item (Join-Path $PSScriptRoot "runtime-contract.json") -Destination $stageRoot

# The runtime bootstrap dot-sources these files before it can inspect or repair
# any installed component. Fail the build here rather than shipping a payload
# that cannot execute its first-run setup.
$requiredRuntimeFiles = @(
    "setup-runtime.ps1",
    "runtime-archive.ps1",
    "runtime-health.ps1",
    "runtime-contract.json",
    "runtime-manifest-state.ps1"
)
foreach ($relativePath in $requiredRuntimeFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $stageRoot $relativePath) -PathType Leaf)) {
        throw "Application payload is missing required runtime setup file: $relativePath"
    }
}

$directories = @("assets", "fonts", "render-service", "remotion", "bin", "community_highlights")
foreach ($name in $directories) {
    $source = Join-Path $repoRoot $name
    if (Test-Path $source) {
        Copy-Item $source -Destination $stageRoot -Recurse
    }
}

# Remove development-only files while retaining package locks and production
# node_modules needed by the renderer and Remotion bundler.
Get-ChildItem $stageRoot -Directory -Recurse -Force |
    Where-Object { $_.Name -in @(".git", ".cache", ".remotion", "coverage") } |
    Sort-Object FullName -Descending |
    ForEach-Object { if (Test-Path $_.FullName) { Remove-Item $_.FullName -Recurse -Force } }

# Verify the complete runtime and service contract after all files have been
# staged and development-only directories removed. These are the files that
# the native shell and first-run setup will require on a customer machine.
$requiredPayloadFiles = @(
    "app.py",
    "community_highlights\__init__.py",
    "community_highlights\api.py",
    "local_library.py",
    "requirements.txt",
    "VERSION",
    "setup-runtime.ps1",
    "runtime-archive.ps1",
    "runtime-health.ps1",
    "runtime-contract.json",
    "runtime-manifest-state.ps1",
    "render-service\dist\server.js",
    "render-service\node_modules\@remotion\renderer\package.json",
    "remotion\src\index.ts",
    "bgutil-provider\server\build\generate_once.js"
)
foreach ($relativePath in $requiredPayloadFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $stageRoot $relativePath) -PathType Leaf)) {
        throw "Application payload is incomplete. Required file is missing: $relativePath"
    }
}

if (Test-Path $archive) { Remove-Item $archive -Force }
$Tar = Get-Command "tar.exe" -ErrorAction SilentlyContinue
if (-not $Tar) { throw "Windows tar.exe is required to package the application payload." }
$PayloadItems = @(Get-ChildItem -LiteralPath $stageRoot -Force | ForEach-Object { $_.Name })
& $Tar.Path -a -c -f $archive -C $stageRoot @PayloadItems
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $archive)) {
    throw "Could not create the application payload archive (exit $LASTEXITCODE)."
}
Remove-Item $stageRoot -Recurse -Force

$hash = (Get-FileHash $archive -Algorithm SHA256).Hash.ToLowerInvariant()
$size = (Get-Item $archive).Length
Write-Host "Application payload ready: $archive"
Set-Content -Path (Join-Path $resourceRoot "app-payload.sha256") -Value $hash -NoNewline
Write-Host "SHA256: $hash"
Write-Host "Size: $size bytes"
