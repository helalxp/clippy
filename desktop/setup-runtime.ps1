$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue" # Avoid the extremely slow per-byte progress UI in Windows PowerShell 5.1.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# Clippy must not inherit another application's Python, Conda, or Node setup.
# This setup engine invokes its managed executables by absolute path; these
# variables can otherwise redirect imports, DLLs, packages, or child tools.
$ConflictingEnvironmentVariables = @(
    "PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE", "PYTHONSTARTUP",
    "PYTHONEXECUTABLE", "VIRTUAL_ENV", "CONDA_PREFIX",
    "CONDA_DEFAULT_ENV", "CONDA_EXE", "CONDA_PYTHON_EXE",
    "NODE_PATH", "NODE_OPTIONS", "NPM_CONFIG_PREFIX",
    "NPM_CONFIG_USERCONFIG"
)
foreach ($Name in $ConflictingEnvironmentVariables) {
    Remove-Item -LiteralPath ("Env:" + $Name) -ErrorAction SilentlyContinue
}
$env:PYTHONNOUSERSITE = "1"
$env:PYTHONUTF8 = "1"

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
$TorchVariant = "cpu"
$Nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($Nvidia) {
    & $Nvidia.Source *> $null
    if ($LASTEXITCODE -eq 0) { $TorchVariant = "cuda" }
}
$PythonArchiveName = "python-$PythonVersion-embed-amd64.zip"
$PythonArchiveUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$PythonArchiveSha256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
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
    try { [System.IO.File]::AppendAllText($SetupLogPath, $Line + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false)) } catch { }
}

trap {
    $Failure = $_
    try {
        Write-Stage ("SETUP FAILED: " + $Failure.Exception.Message)
        Write-Stage ("Failure location: " + $Failure.InvocationInfo.PositionMessage)
        Write-Stage ("Diagnostic log: " + $SetupLogPath)
    } catch { }
    exit 1
}

Write-Stage "Runtime setup engine started."
Write-Stage ("Selected prebuilt Python runtime variant: " + $TorchVariant)

function Download-File([string]$Url, [string]$Destination) {
    if (Test-Path -LiteralPath $Destination -PathType Leaf) {
        if ((Get-Item -LiteralPath $Destination).Length -gt 0) {
            Write-Stage "Reusing cached $([IO.Path]::GetFileName($Destination)); caller will verify it."
            return
        }
        Remove-Item -LiteralPath $Destination -Force
    }

    $Partial = "$Destination.partial"
    $Parent = Split-Path -Parent $Destination
    if ($Parent) { New-Item -ItemType Directory -Path $Parent -Force | Out-Null }
    for ($Attempt = 1; $Attempt -le 3; $Attempt++) {
        $Offset = if (Test-Path -LiteralPath $Partial) { (Get-Item -LiteralPath $Partial).Length } else { 0L }
        $Response = $null
        $InputStream = $null
        $OutputStream = $null
        try {
            $Request = [System.Net.HttpWebRequest]::Create($Url)
            $Request.Method = "GET"
            $Request.AllowAutoRedirect = $true
            $Request.Timeout = 60000
            $Request.ReadWriteTimeout = 60000
            $Request.UserAgent = "ClippyRuntimeSetup/1.0"
            if ($Offset -gt 0) { $Request.AddRange([long]$Offset) }
            Write-Stage ("Downloading {0}; resuming at {1:N0} bytes (attempt {2}/3)." -f [IO.Path]::GetFileName($Destination), $Offset, $Attempt)
            $Response = [System.Net.HttpWebResponse]$Request.GetResponse()
            $Status = [int]$Response.StatusCode
            if ($Offset -gt 0 -and $Status -eq 200) {
                # Server ignored Range. Restart cleanly rather than append a full
                # response to a partial file and silently corrupt the archive.
                $Offset = 0
            } elseif ($Status -ne 200 -and $Status -ne 206) {
                throw "Unexpected HTTP status $Status while downloading $Url"
            }
            if ($Status -eq 206) {
                $ContentRange = $Response.Headers["Content-Range"]
                if ($Offset -gt 0 -and $ContentRange -notmatch "^bytes\s+$Offset-") {
                    throw "Server returned an invalid Content-Range while resuming $Url"
                }
            }
            $TotalBytes = if ($Response.ContentLength -ge 0) { $Offset + $Response.ContentLength } else { 0L }
            $InputStream = $Response.GetResponseStream()
            $Mode = if ($Offset -gt 0 -and $Status -eq 206) { [IO.FileMode]::Append } else { [IO.FileMode]::Create }
            $OutputStream = [IO.File]::Open($Partial, $Mode, [IO.FileAccess]::Write, [IO.FileShare]::None)
            $Buffer = New-Object byte[] (1024 * 1024)
            $Downloaded = $Offset
            $LastReportedPercent = -1
            while (($Read = $InputStream.Read($Buffer, 0, $Buffer.Length)) -gt 0) {
                $OutputStream.Write($Buffer, 0, $Read)
                $Downloaded += $Read
                if ($TotalBytes -gt 0) {
                    $Percent = [int][math]::Floor(($Downloaded * 100.0) / $TotalBytes)
                    if ($Percent -ge $LastReportedPercent + 10) {
                        $LastReportedPercent = $Percent
                        Write-Stage ("{0}: {1}% ({2:N0}/{3:N0} bytes)." -f [IO.Path]::GetFileName($Destination), $Percent, $Downloaded, $TotalBytes)
                    }
                }
            }
            $OutputStream.Flush()
            $OutputStream.Dispose(); $OutputStream = $null
            $InputStream.Dispose(); $InputStream = $null
            $Response.Close(); $Response = $null
            if ((Get-Item -LiteralPath $Partial).Length -lt 1) {
                throw "Download returned an empty file: $Url"
            }
            Move-Item -LiteralPath $Partial -Destination $Destination -Force
            Write-Stage "Download complete: $([IO.Path]::GetFileName($Destination))."
            return
        } catch {
            $Message = $_.Exception.Message
            if ($OutputStream) { $OutputStream.Dispose(); $OutputStream = $null }
            if ($InputStream) { $InputStream.Dispose(); $InputStream = $null }
            if ($Response) { $Response.Close(); $Response = $null }
            if ($Attempt -eq 3) { throw "Download failed after 3 attempts: $Url. $Message" }
            Write-Stage "Download interrupted; preserving partial data for resume. $Message"
            Start-Sleep -Seconds ([math]::Min(2 * $Attempt, 6))
        }
    }
    throw "Download failed: $Url"
}

function Expand-ArchiveFast([string]$Archive, [string]$Destination) {
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $Tar = Get-Command "tar.exe" -ErrorAction SilentlyContinue
    if ($Tar) {
        & $Tar.Path -xf $Archive -C $Destination
        if ($LASTEXITCODE -eq 0) { return }
        Write-Stage "Windows tar could not extract $([IO.Path]::GetFileName($Archive)); using the PowerShell ZIP fallback."
        Remove-Item -LiteralPath $Destination -Recurse -Force
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    }
    Expand-Archive -LiteralPath $Archive -DestinationPath $Destination -Force
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
$ScratchRoot = Join-Path $ScratchDrive.RootDirectory.FullName ("ClippySetupTemp-" + $env:USERNAME)
# Remove leftovers from an interrupted previous run before calculating free space.
if (Test-Path $ScratchRoot) {
    Remove-Item $ScratchRoot -Recurse -Force -ErrorAction Stop
}
New-Item -ItemType Directory -Path $ScratchRoot -Force | Out-Null
$env:TEMP = $ScratchRoot
$env:TMP = $ScratchRoot
$env:PIP_CACHE_DIR = Join-Path $ScratchRoot "pip-cache"
Write-Stage ("Using " + $ScratchRoot + " for temporary setup files; managed runtimes remain in " + $Root)
foreach ($Required in @("app.py", "requirements.txt", "setup-runtime.ps1", "VERSION")) {
    if (-not (Test-Path (Join-Path $App $Required))) {
        throw "Application payload is incomplete. Missing $Required in $App"
    }
}

$RequirementsHash = (Get-FileHash (Join-Path $App "requirements.txt") -Algorithm SHA256).Hash.ToLowerInvariant()
$ExpectedState = "python=$PythonVersion;pythonVariant=$TorchVariant;node=$NodeVersion;ffmpeg=gyan-release-essentials;requirements=$RequirementsHash"
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
$ScratchDriveLetter = $ScratchDrive.Name.Substring(0, 1)
if ($ScratchDriveLetter -eq $DriveLetter) {
    $CombinedMinimumBytes = $MinimumRuntimeFreeBytes + $MinimumScratchFreeBytes
    if ($RuntimeFreeBytes -lt $CombinedMinimumBytes) {
        throw "Clippy needs at least 22 GB free on drive $DriveLetter when runtime and temporary files share a drive. Available: $([math]::Round($RuntimeFreeBytes / 1GB, 1)) GB."
    }
} else {
    if ($RuntimeFreeBytes -lt $MinimumRuntimeFreeBytes) {
        throw "Clippy needs at least 10 GB free on the runtime drive ($DriveLetter) for installed components. Available: $([math]::Round($RuntimeFreeBytes / 1GB, 1)) GB."
    }
    if ($ScratchFreeBytes -lt $MinimumScratchFreeBytes) {
        throw "Clippy needs at least 12 GB free on scratch drive $($ScratchDrive.Name) for temporary CUDA/Python installation files. Available: $([math]::Round($ScratchFreeBytes / 1GB, 1)) GB."
    }
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
    if ($VcProcess.ExitCode -notin @(0, 3010, 1638)) {
        throw "Microsoft Visual C++ runtime installation failed with exit code $($VcProcess.ExitCode)."
    }
}

# Select a prebuilt, tested Python runtime. Customer machines never run pip.
$AppVersion = (Get-Content -LiteralPath (Join-Path $App "VERSION") -Raw).Trim()
if ($AppVersion -notmatch "^\d+\.\d+\.\d+$") { throw "Application VERSION file is missing or invalid." }

$PythonRuntimeAssetName = "clippy-python-$TorchVariant.zip"
$PythonRuntimeName = "clippy-python-$TorchVariant-$AppVersion.zip"
$PythonRuntimeUrl = "https://github.com/helalxp/clippy/releases/download/v$AppVersion/$PythonRuntimeAssetName"
$PythonRuntimeArchive = Join-Path $Downloads $PythonRuntimeName
$PythonRuntimeChecksum = "$PythonRuntimeArchive.sha256"
$LocalRuntimeArchive = $env:CLIPPY_PYTHON_RUNTIME_ARCHIVE
$LocalRuntimeChecksum = $env:CLIPPY_PYTHON_RUNTIME_CHECKSUM

# Local archive overrides make branch-built installers testable before a
# matching GitHub release exists. The same SHA-256 verification is mandatory.
if (-not [string]::IsNullOrWhiteSpace($LocalRuntimeArchive)) {
    $PythonRuntimeArchive = [System.IO.Path]::GetFullPath($LocalRuntimeArchive)
    if (-not (Test-Path -LiteralPath $PythonRuntimeArchive -PathType Leaf)) {
        throw "CLIPPY_PYTHON_RUNTIME_ARCHIVE does not exist: $PythonRuntimeArchive"
    }
    if (-not [string]::IsNullOrWhiteSpace($LocalRuntimeChecksum)) {
        $PythonRuntimeChecksum = [System.IO.Path]::GetFullPath($LocalRuntimeChecksum)
    } else {
        $PythonRuntimeChecksum = "$PythonRuntimeArchive.sha256"
    }
    if (-not (Test-Path -LiteralPath $PythonRuntimeChecksum -PathType Leaf)) {
        throw "Python runtime checksum file is missing: $PythonRuntimeChecksum"
    }
    Write-Stage "Using locally supplied Python runtime archive: $PythonRuntimeArchive"
    $ChecksumText = Get-Content -LiteralPath $PythonRuntimeChecksum -Raw
    if ($ChecksumText -notmatch "(?i)\b([a-f0-9]{64})\b") {
        throw "Local Python runtime checksum file is invalid: $PythonRuntimeChecksum"
    }
    Assert-Sha256 $PythonRuntimeArchive $Matches[1]
    $PythonRuntimeVerified = $true
} else {
    $PythonRuntimeVerified = $false
    for ($Attempt = 1; $Attempt -le 2; $Attempt++) {
        if ($Attempt -eq 2) {
            Write-Stage "Cached Python runtime failed verification; downloading a fresh copy."
            Remove-Item -LiteralPath $PythonRuntimeArchive, $PythonRuntimeChecksum -Force -ErrorAction SilentlyContinue
        }
        Download-File $PythonRuntimeUrl $PythonRuntimeArchive
        Download-File "$PythonRuntimeUrl.sha256" $PythonRuntimeChecksum
        $ChecksumText = Get-Content -LiteralPath $PythonRuntimeChecksum -Raw
        if ($ChecksumText -notmatch "(?i)\b([a-f0-9]{64})\b") {
            if ($Attempt -eq 2) { throw "Python runtime checksum asset is invalid." }
            continue
        }
        try {
            Assert-Sha256 $PythonRuntimeArchive $Matches[1]
            $PythonRuntimeVerified = $true
            break
        } catch {
            if ($Attempt -eq 2) { throw }
        }
    }
}
if (-not $PythonRuntimeVerified) { throw "Could not verify the downloaded Python runtime." }

$PythonStage = Join-Path $Runtime "python.installing"
$PythonBackup = Join-Path $Runtime "python.previous"
if (Test-Path $PythonStage) { Remove-Item $PythonStage -Recurse -Force }
Write-Stage "Extracting the verified $TorchVariant Python runtime..."
Expand-ArchiveFast $PythonRuntimeArchive $PythonStage
$StagedPython = Join-Path $PythonStage "python.exe"
if (-not (Test-Path -LiteralPath $StagedPython -PathType Leaf)) {
    throw "Verified Python runtime archive does not contain python.exe at its root."
}
$StagedVersion = (& $StagedPython --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $StagedVersion -ne "Python $PythonVersion") {
    throw "Packaged Python version check failed: $StagedVersion"
}
$StagedImportCheck = "import torch, torchvision, fastapi, uvicorn, faster_whisper; print('torch=' + torch.__version__); print('cuda_build=' + str(torch.version.cuda))"
& $StagedPython -c $StagedImportCheck
if ($LASTEXITCODE -ne 0) { throw "Packaged Python dependency verification failed." }
if ($TorchVariant -eq "cuda") {
    & $StagedPython -c "import torch; assert torch.version.cuda is not None, 'CUDA-enabled PyTorch is missing'"
    if ($LASTEXITCODE -ne 0) { throw "Selected CUDA runtime does not contain CUDA-enabled PyTorch." }
}

# Activate only after archive hash, Python version, and critical imports pass.
if (Test-Path $PythonDir) {
    if (Test-Path $PythonBackup) { Remove-Item $PythonBackup -Recurse -Force }
    Move-Item -LiteralPath $PythonDir -Destination $PythonBackup
}
try {
    Move-Item -LiteralPath $PythonStage -Destination $PythonDir
    $PythonExe = Join-Path $PythonDir "python.exe"
    & $PythonExe -c "import torch, fastapi, faster_whisper; print(torch.__version__)"
    if ($LASTEXITCODE -ne 0) { throw "Activated Python runtime failed its health check." }
    if (Test-Path $PythonBackup) { Remove-Item $PythonBackup -Recurse -Force }
} catch {
    if (Test-Path $PythonDir) { Remove-Item $PythonDir -Recurse -Force }
    if (Test-Path $PythonBackup) { Move-Item -LiteralPath $PythonBackup -Destination $PythonDir }
    throw
}

# Node's archive is checked against the SHA-256 value published alongside the
# official Node.js release archive.
$NodeExe = Join-Path $NodeDir "node.exe"
if (-not (Test-Path $NodeExe)) {
    $NodeZip = Join-Path $Downloads $NodeArchiveName
    $Checksums = Join-Path $Downloads "node-v$NodeVersion-SHASUMS256.txt"
    Download-File $NodeArchiveUrl $NodeZip
    Download-File $NodeChecksumsUrl $Checksums
    $Line = Get-Content $Checksums -ErrorAction SilentlyContinue | Where-Object { $_ -match "\s$([regex]::Escape($NodeArchiveName))$" } | Select-Object -First 1
    if (-not $Line) {
        Write-Stage "Cached Node.js checksum file is incomplete; downloading it again."
        Remove-Item $Checksums -Force -ErrorAction SilentlyContinue
        Download-File $NodeChecksumsUrl $Checksums
        $Line = Get-Content $Checksums | Where-Object { $_ -match "\s$([regex]::Escape($NodeArchiveName))$" } | Select-Object -First 1
        if (-not $Line) { throw "Official Node.js checksum file does not contain $NodeArchiveName." }
    }
    $Expected = ($Line -split "\s+")[0]
    try {
        Assert-Sha256 $NodeZip $Expected
    } catch {
        Write-Stage "Cached Node.js archive failed verification; downloading a fresh copy."
        Remove-Item $NodeZip -Force -ErrorAction SilentlyContinue
        Download-File $NodeArchiveUrl $NodeZip
        Assert-Sha256 $NodeZip $Expected
    }
    $Extract = Join-Path $ScratchRoot "node-extract"
    if (Test-Path $Extract) { Remove-Item $Extract -Recurse -Force }
    Expand-ArchiveFast $NodeZip $Extract
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
    $HashText = Get-Content $FfmpegHashFile -Raw -ErrorAction SilentlyContinue
    if ($HashText -notmatch "(?i)\b([a-f0-9]{64})\b") {
        Write-Stage "Cached FFmpeg checksum file is incomplete; downloading it again."
        Remove-Item $FfmpegHashFile -Force -ErrorAction SilentlyContinue
        Download-File $FfmpegChecksumUrl $FfmpegHashFile
        $HashText = Get-Content $FfmpegHashFile -Raw
        if ($HashText -notmatch "(?i)\b([a-f0-9]{64})\b") { throw "FFmpeg checksum sidecar did not contain a SHA-256 hash." }
    }
    $FfmpegExpectedHash = $Matches[1]
    try {
        Assert-Sha256 $FfmpegZip $FfmpegExpectedHash
    } catch {
        Write-Stage "Cached FFmpeg archive failed verification; downloading a fresh copy."
        Remove-Item $FfmpegZip -Force -ErrorAction SilentlyContinue
        Download-File $FfmpegArchiveUrl $FfmpegZip
        Assert-Sha256 $FfmpegZip $FfmpegExpectedHash
    }
    $Extract = Join-Path $ScratchRoot "ffmpeg-extract"
    if (Test-Path $Extract) { Remove-Item $Extract -Recurse -Force }
    Expand-ArchiveFast $FfmpegZip $Extract
    $FfmpegBinary = Get-ChildItem $Extract -Filter "ffmpeg.exe" -Recurse | Select-Object -First 1
    if (-not $FfmpegBinary) { throw "FFmpeg archive did not contain ffmpeg.exe." }
    $SourceBin = $FfmpegBinary.Directory.FullName
    New-Item -ItemType Directory -Path $FfmpegDir -Force | Out-Null
    Copy-Item (Join-Path $SourceBin "*") -Destination $FfmpegDir -Recurse -Force
    Remove-Item $Extract -Recurse -Force
}
& $FfmpegExe -version
if ($LASTEXITCODE -ne 0) { throw "Managed FFmpeg runtime failed its version check." }

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
$Manifest = @{
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
    gpuMode = if ($TorchVariant -eq "cuda") { "cuda126" } else { "cpu" }
}
$ManifestJson = $Manifest | ConvertTo-Json -Depth 5
# Windows PowerShell 5.1 writes a UTF-8 BOM with Set-Content -Encoding UTF8.
# serde_json expects plain JSON, so write UTF-8 explicitly without a BOM.
[System.IO.File]::WriteAllText($ManifestPath, $ManifestJson, [System.Text.UTF8Encoding]::new($false))
try { Remove-Item $ScratchRoot -Recurse -Force -ErrorAction SilentlyContinue } catch { }
Write-Stage "Runtime setup completed successfully."
