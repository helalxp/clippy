$ErrorActionPreference = "Stop"

# Compatibility entry point retained for existing developer instructions.
# Keep all path resolution and build behavior in the canonical build script.
$buildScript = Join-Path $PSScriptRoot "build.ps1"
if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
    throw "Canonical Windows build script is missing: $buildScript"
}
& $buildScript
if ($LASTEXITCODE -ne 0) {
    throw "Clippy Windows build failed (exit $LASTEXITCODE)."
}
