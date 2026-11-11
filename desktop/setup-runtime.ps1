$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root = Join-Path $env:LOCALAPPDATA "Clippy"
$App = Join-Path $Root "app\current"
$Runtime = Join-Path $Root "runtime"
$Downloads = Join-Path $Root "downloads"
$PythonDir = Join-Path $Runtime "python"
$NodeDir = Join-Path $Runtime "node"
$FfmpegDir = Join-Path $Runtime "ffmpeg\bin"
$ManifestPath = Join-Path $Root "runtime-manifest.json"
$LogDir = Join-Path $Root "logs"
$SetupLogPath = Join-Path $LogDir "runtime-setup.log"

$PythonVersion = "3.12.10"
$PythonInstallerUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
$NodeVersion = "22.23.3"
$NodeArchiveName = "node-v$NodeVersion-win-x64.zip"
$NodeArchiveUrl = "https://nodejs.org/dist/v$NodeVersion/$NodeArchiveName"
$NodeChecksumsUrl = "https://nodejs.org/dist/v$NodeVersion/SHASUMS256.txt"
$FfmpegArchiveName = "ffmpeg-release-essentials.zip"
$FfmpegArchiveUrl = "https://www.gyan.dev/ffmpeg/builds/$FfmpegArchiveName"
$FfmpegChecksumUrl = "$FfmpegArchiveUrl.sha256"
$VcRedistUrl = "https://aka.ms/vs/17/release/vc_redist.x64.exe"

$null = New-Item -ItemType Directory -Path $LogDir -Force
function Write-Stage([string]$Message) {
    $Line = "[{0}] [Clippy setup] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Output $Line
    try { [System.IO.File]::AppendAllText($SetupLogPath, $Line + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($false))) } catch { }
}

trap {
    Write-Stage ("FATAL ERROR: " + $_.Exception.Message)
    break
}

function Download-File([string]$Url, [string]$Destination) {
    if (Test-Path $Destination) { Remove-Item $Destination -Force }
    Write-Stage "Downloading $([IO.Path]::GetFileName($Destination))..."
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
    if (-not (Test-Path $Destination) -or (Get-Item $Destination).Length -lt 1) {
        throw "Download did not produce a valid file: $Destination"
    }
}

function Assert-Sha256([string]$Path, [string]$Expected) {
    $Actual = (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne $Expected.ToLowerInvariant()) {
        throw "SHA-256 verification failed for $Path. Expected $Expected, got $Actual"
    }
}

New-Item -ItemType Directory -Path $Runtime, $Downloads -Force | Out-Null

# Put temporary extraction and package-install files on the roomiest fixed drive.
# The managed runtime remains under LOCALAPPDATA; only scratch data is redirected.
$ScratchDrive = [System.IO.DriveInfo]::GetDrives() |
    Where-Object { $_.IsReady -and $_.DriveType -eq [System.IO.DriveType]::Fixed } |
    Sort-Object AvailableFreeSpace -Descending |
    Select-Object -First 1
if (-not $ScratchDrive) { throw "No writable fixed drive is available for setup temporary files." }
$ScratchRoot = Join-Path $ScratchDrive.RootDirectory.FullName "ClippySetupTemp"
New-Item -ItemType Directory -Path $ScratchRoot -Force | Out-Null
$env:TEMP = $ScratchRoot
$env:TMP = $ScratchRoot
$env:PIP_CACHE_DIR = Join-Path $ScratchRoot "pip-cache"
Write-Stage ("Using " + $ScratchRoot + " for temporary setup files; managed runtimes remain in " + $Root)
foreach ($Required in @("app.py", "requirements.txt", "setup-runtime.ps1")) {
    if (-not (Test-Path (Join-Path $App $Required))) {
        throw "Application payload is incomplete. Missing $Required in $App"
    }
}

$RequirementsHash = (Get-FileHash (Join-Path $App "requirements.txt") -Algorithm SHA256).Hash.ToLowerInvariant()
$ExpectedState = "python=$PythonVersion;node=$NodeVersion;ffmpeg=gyan-release-essentials;requirements=$RequirementsHash"
if (Test-Path $ManifestPath) {
    try {
        $Existing = Get-Content $ManifestPath -Raw | ConvertFrom-Json
        $RuntimeFilesPresent =
            (Test-Path (Join-Path $PythonDir "python.exe")) -and
            (Test-Path (Join-Path $NodeDir "node.exe")) -and
            (Test-Path (Join-Path $FfmpegDir "ffmpeg.exe"))
        if ($Existing.state -eq $ExpectedState -and $RuntimeFilesPresent) {
            Write-Stage "Verifying installed backend and Remotion dependencies..."
            $PythonHealthy = $false
            $NodeHealthy = $false
            Push-Location $App
            try {
                $env:OUTPUT_DIR = Join-Path $Root "data\output"
                $env:UPLOAD_DIR = Join-Path $Root "data\uploads"
                $env:CLIPPY_SETTINGS_PATH = Join-Path $Root "settings.json"
                $env:CLIPPY_MODELS_DIR = Join-Path $Root "data\models"
                & (Join-Path $PythonDir "python.exe") -c "import app; import torch; import faster_whisper" *> $null
                $PythonHealthy = ($LASTEXITCODE -eq 0)
                $BrowserCheck = "import('@remotion/renderer').then(async m => { await m.ensureBrowser(); }).catch(e => { console.error(e); process.exit(1); });"
                Push-Location (Join-Path $App "render-service")
                try {
                    & (Join-Path $NodeDir "node.exe") -e $BrowserCheck *> $null
                    $NodeHealthy = ($LASTEXITCODE -eq 0)
                } finally {
                    Pop-Location
                }
            } finally {
                Pop-Location
            }
            if ($PythonHealthy -and $NodeHealthy) {
                Write-Stage "Managed runtimes and application dependencies are healthy. No downloads needed."
                exit 0
            }
            Write-Stage "A runtime health check failed; repairing dependencies."
        }
    } catch {
        Write-Stage "Previous runtime manifest is invalid; repairing managed runtimes."
    }
}

$DriveLetter = [IO.Path]::GetPathRoot($Root).Substring(0, 1)
$RuntimeFreeBytes = (Get-PSDrive -Name $DriveLetter).Free
$ScratchFreeBytes = $ScratchDrive.AvailableFreeSpace
$MinimumRuntimeFreeBytes = 10GB
$MinimumScratchFreeBytes = 12GB
if ($RuntimeFreeBytes -lt $MinimumRuntimeFreeBytes) {
    throw "Clippy needs at least 10 GB free on the runtime drive ($DriveLetter) for installed components. Available: $([math]::Round($RuntimeFreeBytes / 1GB, 1)) GB."
}
if ($ScratchFreeBytes -lt $MinimumScratchFreeBytes) {
    throw "Clippy needs at least 12 GB free on scratch drive $($ScratchDrive.Name) for temporary CUDA/Python installation files. Available: $([math]::Round($ScratchFreeBytes / 1GB, 1)) GB."
}

# Python and native wheels require the Microsoft Visual C++ runtime.
# Install the signed Microsoft redistributable only when the x64 runtime is absent.
$VcRuntimeKey = "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
$VcRuntimeInstalled = $false
try {
    $VcRuntimeInstalled = (Get-ItemProperty -Path $VcRuntimeKey -Name Installed -ErrorAction Stop).Installed -eq 1
} catch {
    $VcRuntimeInstalled = $false
}
if (-not $VcRuntimeInstalled) {
    $VcRedist = Join-Path $Downloads "vc_redist.x64.exe"
    Download-File $VcRedistUrl $VcRedist
    $VcSignature = Get-AuthenticodeSignature -FilePath $VcRedist
    if ($VcSignature.Status -ne "Valid" -or $VcSignature.SignerCertificate.Subject -notmatch "Microsoft") {
        throw "Microsoft Visual C++ redistributable signature is not valid."
    }
    $VcProcess = Start-Process -FilePath $VcRedist -ArgumentList "/install /quiet /norestart" -Verb RunAs -Wait -PassThru
    if ($VcProcess.ExitCode -notin @(0, 3010)) {
        throw "Microsoft Visual C++ runtime installation failed with exit code $($VcProcess.ExitCode)."
    }
}

# Python is installed privately into Clippy's runtime folder. Its Authenticode
# signature is checked before the silent installer is allowed to run.
$PythonExe = Join-Path $PythonDir "python.exe"
if (-not (Test-Path $PythonExe)) {
    $Installer = Join-Path $Downloads "python-$PythonVersion-amd64.exe"
    Download-File $PythonInstallerUrl $Installer
    $Signature = Get-AuthenticodeSignature -FilePath $Installer
    if ($Signature.Status -ne "Valid" -or $Signature.SignerCertificate.Subject -notmatch "Python Software Foundation") {
        throw "Python installer signature is not valid or is not issued to the Python Software Foundation."
    }
    Write-Stage "Installing private Python $PythonVersion runtime..."
    New-Item -ItemType Directory -Path $PythonDir -Force | Out-Null
    $InstallerArgs = '/quiet InstallAllUsers=0 TargetDir="' + $PythonDir + '" Include_pip=1 Include_launcher=0 Include_test=0 Shortcuts=0 PrependPath=0'
    $Process = Start-Process -FilePath $Installer -ArgumentList $InstallerArgs -Wait -PassThru
    if ($Process.ExitCode -notin @(0, 3010) -or -not (Test-Path $PythonExe)) {
        throw "Private Python installation failed with exit code $($Process.ExitCode)."
    }
}
& $PythonExe --version
if ($LASTEXITCODE -ne 0) { throw "Managed Python runtime failed its version check." }

# Node's archive is checked against the SHA-256 value published alongside the
# official Node.js release archive.
$NodeExe = Join-Path $NodeDir "node.exe"
if (-not (Test-Path $NodeExe)) {
    $NodeZip = Join-Path $Downloads $NodeArchiveName
    $Checksums = Join-Path $Downloads "node-v$NodeVersion-SHASUMS256.txt"
    Download-File $NodeArchiveUrl $NodeZip
    Download-File $NodeChecksumsUrl $Checksums
    $Line = Get-Content $Checksums | Where-Object { $_ -match "\s$([regex]::Escape($NodeArchiveName))$" } | Select-Object -First 1
    if (-not $Line) { throw "Official Node.js checksum file does not contain $NodeArchiveName." }
    $Expected = ($Line -split "\s+")[0]
    Assert-Sha256 $NodeZip $Expected
    $Extract = Join-Path $Downloads "node-extract"
    if (Test-Path $Extract) { Remove-Item $Extract -Recurse -Force }
    Expand-Archive -Path $NodeZip -DestinationPath $Extract -Force
    $ExtractedRoot = Join-Path $Extract "node-v$NodeVersion-win-x64"
    if (-not (Test-Path (Join-Path $ExtractedRoot "node.exe"))) { throw "Node.js archive layout was unexpected." }
    New-Item -ItemType Directory -Path $NodeDir -Force | Out-Null
    Get-ChildItem $ExtractedRoot -Force | Move-Item -Destination $NodeDir
    Remove-Item $Extract -Recurse -Force
}
& $NodeExe --version
if ($LASTEXITCODE -ne 0) { throw "Managed Node.js runtime failed its version check." }

# FFmpeg is downloaded from the Windows builds publisher and verified against
# the publisher's SHA-256 sidecar before extraction.
$FfmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"
if (-not (Test-Path $FfmpegExe)) {
    $FfmpegZip = Join-Path $Downloads $FfmpegArchiveName
    $FfmpegHashFile = Join-Path $Downloads "$FfmpegArchiveName.sha256"
    Download-File $FfmpegArchiveUrl $FfmpegZip
    Download-File $FfmpegChecksumUrl $FfmpegHashFile
    $HashText = Get-Content $FfmpegHashFile -Raw
    if ($HashText -notmatch "(?i)\b([a-f0-9]{64})\b") { throw "FFmpeg checksum sidecar did not contain a SHA-256 hash." }
    Assert-Sha256 $FfmpegZip $Matches[1]
    $Extract = Join-Path $Downloads "ffmpeg-extract"
    if (Test-Path $Extract) { Remove-Item $Extract -Recurse -Force }
    Expand-Archive -Path $FfmpegZip -DestinationPath $Extract -Force
    $FfmpegBinary = Get-ChildItem $Extract -Filter "ffmpeg.exe" -Recurse | Select-Object -First 1
    if (-not $FfmpegBinary) { throw "FFmpeg archive did not contain ffmpeg.exe." }
    $SourceBin = $FfmpegBinary.Directory.FullName
    New-Item -ItemType Directory -Path $FfmpegDir -Force | Out-Null
    Copy-Item (Join-Path $SourceBin "*") -Destination $FfmpegDir -Recurse -Force
    Remove-Item $Extract -Recurse -Force
}
& $FfmpegExe -version
if ($LASTEXITCODE -ne 0) { throw "Managed FFmpeg runtime failed its version check." }

# Install the CUDA-enabled PyTorch wheel when an NVIDIA driver is present;
# otherwise install the official CPU wheel. Other pinned application packages
# are installed from requirements.txt without replacing that selected wheel.
$TorchIndex = "https://download.pytorch.org/whl/cpu"
$Nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($Nvidia) {
    & nvidia-smi
    if ($LASTEXITCODE -eq 0) {
        $TorchIndex = "https://download.pytorch.org/whl/cu126"
        Write-Stage "NVIDIA GPU detected; selecting the CUDA 12.6 PyTorch wheels."
    }
}
Write-Stage "Installing pinned PyTorch and application Python dependencies. This can take several minutes."
& $PythonExe -m pip install --disable-pip-version-check --no-cache-dir --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Could not prepare pip in the managed Python runtime." }
& $PythonExe -m pip install --disable-pip-version-check --no-cache-dir "torch==2.11.0" "torchvision==0.26.0" --index-url $TorchIndex
if ($LASTEXITCODE -ne 0 -and $TorchIndex -match "cu126") {
    Write-Stage "CUDA wheel installation failed; falling back to the official CPU PyTorch wheels."
    $TorchIndex = "https://download.pytorch.org/whl/cpu"
    & $PythonExe -m pip install --disable-pip-version-check --no-cache-dir "torch==2.11.0" "torchvision==0.26.0" --index-url $TorchIndex
}
if ($LASTEXITCODE -ne 0) { throw "PyTorch installation failed from $TorchIndex." }

$FilteredRequirements = Join-Path $Downloads "requirements-runtime.txt"
Get-Content (Join-Path $App "requirements.txt") |
    Where-Object { $_ -notmatch "^\s*(torch|torchvision)\s*==" } |
    Set-Content -Path $FilteredRequirements -Encoding ASCII
& $PythonExe -m pip install --disable-pip-version-check --no-cache-dir -r $FilteredRequirements
if ($LASTEXITCODE -ne 0) { throw "Application Python dependency installation failed." }

Write-Stage "Verifying backend imports..."
Push-Location $App
try {
    $env:OUTPUT_DIR = Join-Path $Root "data\output"
    $env:UPLOAD_DIR = Join-Path $Root "data\uploads"
    $env:CLIPPY_SETTINGS_PATH = Join-Path $Root "settings.json"
    $env:CLIPPY_MODELS_DIR = Join-Path $Root "data\models"
    & $PythonExe -c "import app; import torch; print('Backend imports OK; torch CUDA:', torch.cuda.is_available())"
    if ($LASTEXITCODE -ne 0) { throw "Backend import verification failed. Check the Python dependency log." }
} finally {
    Pop-Location
}

Write-Stage "Installing Remotion's browser runtime..."
$BrowserCheck = "import('@remotion/renderer').then(async m => { await m.ensureBrowser(); console.log('Remotion browser ready'); }).catch(e => { console.error(e); process.exit(1); });"
Push-Location (Join-Path $App "render-service")
try {
    & $NodeExe -e $BrowserCheck
    if ($LASTEXITCODE -ne 0) { throw "Remotion browser installation failed." }
} finally {
    Pop-Location
}

New-Item -ItemType Directory -Path (Split-Path $ManifestPath -Parent) -Force | Out-Null
@$Manifest = @{
    version = "1.0.0"
    components = @{
        python = @{ version = $PythonVersion; installed = $true }
        node = @{ version = $NodeVersion; installed = $true }
        ffmpeg = @{ version = "gyan-release-essentials"; installed = $true }
    }
    schema = 1
    state = $ExpectedState
    installedAt = (Get-Date).ToUniversalTime().ToString("o")
    requirementsSha256 = $RequirementsHash
    gpuMode = if ($TorchIndex -match "cu126") { "cuda126" } else { "cpu" }
}
$ManifestJson = $Manifest | ConvertTo-Json -Depth 5
# Windows PowerShell 5.1 writes a UTF-8 BOM with Set-Content -Encoding UTF8.
# serde_json expects plain JSON, so write UTF-8 explicitly without a BOM.
[System.IO.File]::WriteAllText($ManifestPath, $ManifestJson, (New-Object System.Text.UTF8Encoding($false)))
Write-Stage "Runtime setup completed successfully."
