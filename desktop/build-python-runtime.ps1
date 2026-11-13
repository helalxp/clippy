param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("cpu", "cuda")]
    [string]$Variant,
    [string]$OutputDirectory = (Join-Path $PSScriptRoot "runtime-dist")
)
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$PythonVersion = "3.12.10"
$PythonArchiveName = "python-$PythonVersion-embed-amd64.zip"
$PythonArchiveUrl = "https://www.python.org/ftp/python/$PythonVersion/$PythonArchiveName"
$PythonArchiveSha256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
$TorchIndex = if ($Variant -eq "cuda") { "https://download.pytorch.org/whl/cu128" } else { "https://download.pytorch.org/whl/cpu" }
$RepoRoot = Split-Path -Parent $PSScriptRoot
$WorkRoot = Join-Path $env:RUNNER_TEMP "clippy-python-runtime-$Variant"
$RuntimeRoot = Join-Path $WorkRoot "python"
$SitePackages = Join-Path $RuntimeRoot "Lib\site-packages"
$ArchiveName = "clippy-python-$Variant.zip"
$ArchivePath = Join-Path $OutputDirectory $ArchiveName

if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "A CI Python 3.12 interpreter is required." }
$BuildPython = (& python --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $BuildPython -notmatch "^Python 3\.12\.") { throw "Runtime packaging requires Python 3.12. Found: $BuildPython" }

if (Test-Path $WorkRoot) { Remove-Item $WorkRoot -Recurse -Force }
New-Item -ItemType Directory -Path $WorkRoot, $OutputDirectory -Force | Out-Null
$PythonArchive = Join-Path $WorkRoot $PythonArchiveName
Write-Host "Downloading official CPython $PythonVersion embeddable distribution..."
Invoke-WebRequest -Uri $PythonArchiveUrl -OutFile $PythonArchive -UseBasicParsing
$ActualPythonHash = (Get-FileHash -LiteralPath $PythonArchive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ActualPythonHash -ne $PythonArchiveSha256) { throw "Official CPython archive SHA-256 mismatch." }

Expand-Archive -LiteralPath $PythonArchive -DestinationPath $RuntimeRoot
$PythonPth = Join-Path $RuntimeRoot "python312._pth"
if (-not (Test-Path $PythonPth)) { throw "Official CPython archive is missing python312._pth." }
[System.IO.File]::WriteAllLines($PythonPth, @("python312.zip", ".", "Lib", "Lib\site-packages", "import site"), [System.Text.Encoding]::ASCII)
New-Item -ItemType Directory -Path $SitePackages -Force | Out-Null

# CI's Python/pip installs wheels directly into the final runtime. The shipped
# runtime contains no package-manager bootstrap and never runs pip for users.
Write-Host "Installing pinned $Variant Python dependencies..."
& python -m pip install --disable-pip-version-check --no-warn-script-location --prefer-binary --target $SitePackages --index-url "https://pypi.org/simple" --extra-index-url $TorchIndex -r (Join-Path $RepoRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Could not install pinned $Variant Python dependencies." }

$StagedPython = Join-Path $RuntimeRoot "python.exe"
$VersionCheck = (& $StagedPython --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $VersionCheck -ne "Python $PythonVersion") { throw "Packaged Python failed version check: $VersionCheck" }
$ImportCheck = "import torch, torchvision, fastapi, uvicorn, faster_whisper, scenedetect, ultralytics, mediapipe; print('torch=' + torch.__version__); print('cuda_build=' + str(torch.version.cuda)); print('cuda_available=' + str(torch.cuda.is_available()))"
& $StagedPython -c $ImportCheck
if ($LASTEXITCODE -ne 0) { throw "Packaged Python failed dependency import validation." }
if ($Variant -eq "cuda") {
    & $StagedPython -c "import torch; assert torch.version.cuda is not None and torch.version.cuda.startswith('12.8'), 'CUDA 12.8 PyTorch wheel was not selected'"
    if ($LASTEXITCODE -ne 0) { throw "CUDA package does not contain the required CUDA 12.8 PyTorch build." }
    # Windows PyTorch CUDA wheels bundle the CUDA runtime DLLs in torch\lib.
    # The Linux nvidia-* package directory layout does not apply to this wheel.
    $CudaDllDirectory = Join-Path $SitePackages "torch\lib"
    $RequiredCudaDlls = @(
        (Join-Path $CudaDllDirectory "cublas64_12.dll"),
        (Join-Path $CudaDllDirectory "cudnn64_9.dll"),
        (Join-Path $CudaDllDirectory "cudart64_12.dll")
    )
    foreach ($dll in $RequiredCudaDlls) {
        if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) {
            throw "CUDA runtime is missing a required DLL for faster-whisper/PyTorch: $dll"
        }
    }
} else {
    & $StagedPython -c "import torch; assert torch.version.cuda is None, 'CPU package unexpectedly contains a CUDA build'"
    if ($LASTEXITCODE -ne 0) { throw "CPU package unexpectedly resolved a CUDA-enabled PyTorch wheel." }
}

# Confirm the package remains functional after relocation.
$RelocatedRoot = Join-Path $WorkRoot "relocated"
Move-Item -LiteralPath $RuntimeRoot -Destination $RelocatedRoot
$RelocatedPython = Join-Path $RelocatedRoot "python.exe"
& $RelocatedPython -c "import sys, torch, fastapi; print(sys.executable); print(torch.__version__)"
if ($LASTEXITCODE -ne 0) { throw "Packaged Python failed its relocation test." }

if (Test-Path $ArchivePath) { Remove-Item $ArchivePath -Force }
$Tar = Get-Command "tar.exe" -ErrorAction SilentlyContinue
if (-not $Tar) { throw "Windows tar.exe is required to archive the Python runtime." }
$Items = @(Get-ChildItem -LiteralPath $RelocatedRoot -Force | ForEach-Object { $_.Name })
& $Tar.Path -a -c -f $ArchivePath -C $RelocatedRoot @Items
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $ArchivePath)) { throw "Could not create $ArchiveName (tar exit $LASTEXITCODE)." }

$ArchiveBytes = (Get-Item -LiteralPath $ArchivePath).Length
if ($ArchiveBytes -ge 2GB) { throw "Runtime archive exceeds the 2 GiB per-asset release limit: $ArchiveBytes bytes." }
$Hash = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$ArchivePath.sha256" -Value "$Hash  $ArchiveName" -Encoding ascii

# Validate the exact compressed artifact that will be attached to the release.
$ArchiveTestRoot = Join-Path $WorkRoot "archive-test"
Expand-Archive -LiteralPath $ArchivePath -DestinationPath $ArchiveTestRoot -Force
$ArchiveTestPython = Join-Path $ArchiveTestRoot "python.exe"
& $ArchiveTestPython -c "import torch, torchvision, fastapi, faster_whisper; print(torch.__version__)"
if ($LASTEXITCODE -ne 0) { throw "Compressed runtime archive failed its extraction/import test." }

Write-Host "Runtime archive: $ArchivePath"
Write-Host "SHA-256: $Hash"
Write-Host "Size: $([math]::Round((Get-Item $ArchivePath).Length / 1GB, 2)) GiB"
