param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("cpu", "cuda")]
    [string]$Variant,

    [string]$OutputDirectory = (Join-Path $PSScriptRoot "runtime-dist")
)

$ErrorActionPreference = "Stop"
$PythonVersion = "3.12.10"
$TorchVersion = "2.11.0"
$TorchVisionVersion = "0.26.0"
$TorchIndex = if ($Variant -eq "cuda") {
    "https://download.pytorch.org/whl/cu126"
} else {
    "https://download.pytorch.org/whl/cpu"
}

$PythonVersionOutput = (& python --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $PythonVersionOutput -ne "Python $PythonVersion") {
    throw "Runtime packaging requires CI Python $PythonVersion. Found: $PythonVersionOutput"
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
$WorkRoot = Join-Path $env:RUNNER_TEMP "clippy-python-runtime-$Variant"
$RuntimeRoot = Join-Path $WorkRoot "python"
$SitePackages = Join-Path $RuntimeRoot "Lib\site-packages"
$Requirements = Join-Path $WorkRoot "requirements-runtime.txt"
$ArchiveName = "clippy-python-$Variant.zip"
$ArchivePath = Join-Path $OutputDirectory $ArchiveName

if (Test-Path $WorkRoot) { Remove-Item $WorkRoot -Recurse -Force }
New-Item -ItemType Directory -Path $WorkRoot, $OutputDirectory -Force | Out-Null

$PythonPrefix = (& python -c "import sys; print(sys.prefix)" | Out-String).Trim()
if (-not (Test-Path (Join-Path $PythonPrefix "python.exe"))) {
    throw "Could not locate the CI Python installation at $PythonPrefix"
}

Write-Host "Installing $Variant PyTorch runtime into the isolated CI Python environment..."
& python -m pip install --disable-pip-version-check --no-warn-script-location "torch==$TorchVersion" "torchvision==$TorchVisionVersion" --index-url $TorchIndex
if ($LASTEXITCODE -ne 0) { throw "Could not install $Variant PyTorch wheels." }

Get-Content (Join-Path $RepoRoot "requirements.txt") |
    Where-Object { $_ -notmatch "^\s*(torch|torchvision)\s*==" } |
    Set-Content -LiteralPath $Requirements -Encoding utf8

& python -m pip install --disable-pip-version-check --no-warn-script-location -r $Requirements
if ($LASTEXITCODE -ne 0) { throw "Could not install Clippy's pinned Python requirements." }

# Copy the complete CPython installation, including its standard library and
# native extension dependencies. No pip operation is required on customer PCs.
Write-Host "Staging the complete Python $PythonVersion runtime..."
New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
& robocopy $PythonPrefix $RuntimeRoot /E /COPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { throw "Could not stage the Python runtime (robocopy exit $LASTEXITCODE)." }

$StagedPython = Join-Path $RuntimeRoot "python.exe"
$VersionCheck = (& $StagedPython --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $VersionCheck -ne "Python $PythonVersion") {
    throw "Staged Python failed its version check: $VersionCheck"
}

$ImportCheck = "import torch, torchvision, fastapi, uvicorn, faster_whisper, scenedetect, ultralytics, mediapipe; print('torch=' + torch.__version__); print('cuda_build=' + str(torch.version.cuda)); print('cuda_available=' + str(torch.cuda.is_available()))"
& $StagedPython -c $ImportCheck
if ($LASTEXITCODE -ne 0) { throw "Staged Python runtime failed dependency import validation." }

# Test relocation before packaging. This catches hard-coded CI installation paths.
$RelocatedRoot = Join-Path $WorkRoot "relocated"
Move-Item -LiteralPath $RuntimeRoot -Destination $RelocatedRoot
$RelocatedPython = Join-Path $RelocatedRoot "python.exe"
& $RelocatedPython -c "import sys, torch, fastapi; print(sys.executable); print(torch.__version__)"
if ($LASTEXITCODE -ne 0) { throw "Python runtime failed after relocation; package is not portable." }

if (Test-Path $ArchivePath) { Remove-Item $ArchivePath -Force }
Write-Host "Compressing the verified $Variant runtime..."
Compress-Archive -Path (Join-Path $RelocatedRoot "*") -DestinationPath $ArchivePath -CompressionLevel Optimal
if (-not (Test-Path $ArchivePath) -or (Get-Item $ArchivePath).Length -lt 1) {
    throw "Python runtime archive was not created."
}

$Hash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$ArchivePath.sha256" -Value "$Hash  $ArchiveName" -Encoding ascii
Write-Host "Runtime archive: $ArchivePath"
Write-Host "SHA-256: $Hash"
Write-Host "Size: $([math]::Round((Get-Item $ArchivePath).Length / 1GB, 2)) GiB"
