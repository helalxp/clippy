$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue" # Avoid the extremely slow per-byte progress UI in Windows PowerShell 5.1.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# Wait before any mutation so the shell can assign our process to its cleanup job.
if ($env:CLIPPY_SETUP_WAIT_STDIN -eq '1' -and [Console]::ReadLine() -ne 'GO') { throw 'Setup launch was cancelled.' }
. (Join-Path $PSScriptRoot 'runtime-health.ps1')
$Root = Join-Path $env:LOCALAPPDATA 'Clippy'
$DesktopMutex = $null
if ($env:CLIPPY_SETUP_WAIT_STDIN -ne '1') { $DesktopMutex = Enter-ClippyMutex $Root 'Desktop' }
$InstallMutex = Enter-ClippyMutex $Root
try {
$Contract = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'runtime-contract.json') -Raw | ConvertFrom-Json
if ($Contract.schema -ne 1 -or $Contract.python -notmatch '^\d+\.\d+\.\d+
$PythonVersion = $Contract.python
$NodeVersion = $Contract.node
$FfmpegVersion = $Contract.ffmpeg
$TorchVariant = 'cpu'
if ($Contract.browserVersion -notmatch '^\d+\.\d+\.\d+\.\d+$' -or $Contract.browserArchiveSha256 -notmatch '^[a-f0-9]{64}$' -or $Contract.browserSha256 -notmatch '^[a-f0-9]{64}$') { throw 'Browser integrity contract is invalid.' }
$BrowserArchiveUrl = "https://storage.googleapis.com/chrome-for-testing-public/$($Contract.browserVersion)/win64/chrome-headless-shell-win64.zip"

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
$DataRoot = Join-Path $Root "data"
$StorageLocationPath = Join-Path $Root "storage-location.json"
if (Test-Path -LiteralPath $StorageLocationPath -PathType Leaf) {
    try {
        $StorageLocation = Get-Content -LiteralPath $StorageLocationPath -Raw | ConvertFrom-Json
        $ConfiguredDataRoot = [string]$StorageLocation.data_directory
        if ($StorageLocation.schema_version -ne 1 -or [string]::IsNullOrWhiteSpace($ConfiguredDataRoot)) {
            throw "Storage location configuration is incomplete or unsupported."
        }
        $DataRoot = [IO.Path]::GetFullPath($ConfiguredDataRoot)
        if ($DataRoot -notmatch '^[A-Za-z]:\\|^\\\\') {
            throw "Configured Clippy data directory must be an absolute Windows path."
        }
        if (-not (Test-Path -LiteralPath $DataRoot -PathType Container)) {
            throw "Configured Clippy data directory is unavailable: $DataRoot"
        }
    } catch {
        throw "Cannot load Clippy's configured data directory: $($_.Exception.Message)"
    }
}
$PythonDir = Join-Path $Runtime "python"
$NodeDir = Join-Path $Runtime "node"
$FfmpegDir = Join-Path $Runtime "ffmpeg\bin"
$ManifestPath = Join-Path $Root "runtime-manifest.json"
# Browser binaries are durable user data, not part of app\current. Updating the
# application payload must not force a multi-hundred-MB browser download.
$BrowserRoot = Join-Path $Root "browser"
$BrowserDir = Join-Path $BrowserRoot "headless-shell"
$BrowserExecutable = Join-Path $BrowserDir "chrome-headless-shell.exe"
$BrowserVersionFile = Join-Path $BrowserRoot "remotion-version.txt"
$LogDir = Join-Path $Root "logs"
$SetupLogPath = Join-Path $LogDir "runtime-setup.log"
$script:ScratchRoot = $null
$NvidiaDriverVersion = $null
$NvidiaGpuName = $null
$NvidiaComputeCapability = $null
$ForceCpuRuntime = $env:CLIPPY_FORCE_CPU_RUNTIME -eq "1"
if (-not $ForceCpuRuntime) {
    $Nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
$NvidiaSmiPath = if ($Nvidia) { $Nvidia.Source } else { $null }
if (-not $NvidiaSmiPath) {
    $NvidiaCandidates = @(
        (Join-Path $env:ProgramFiles "NVIDIA Corporation\NVSMI\nvidia-smi.exe"),
        (Join-Path $env:SystemRoot "System32\nvidia-smi.exe")
    )
    $NvidiaSmiPath = $NvidiaCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if ($NvidiaSmiPath) {
    $NvidiaInfo = & $NvidiaSmiPath --query-gpu=name,driver_version,compute_cap --format=csv,noheader 2>$null
    if ($LASTEXITCODE -eq 0 -and $NvidiaInfo) {
        $NvidiaLine = @($NvidiaInfo) | Select-Object -First 1
        $NvidiaFields = ([string]$NvidiaLine).Split(',')
        if ($NvidiaFields.Count -ge 3) {
            $NvidiaGpuName = $NvidiaFields[0].Trim()
            $DriverText = $NvidiaFields[1].Trim()
            try { $NvidiaDriverVersion = [Version]$DriverText } catch { $NvidiaDriverVersion = $null }
            $ParsedComputeCapability = 0.0
            if ([double]::TryParse($NvidiaFields[2].Trim(), [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$ParsedComputeCapability)) {
                $NvidiaComputeCapability = $ParsedComputeCapability
            }
            # CUDA 12.8 GA requires Windows driver 570.65. The packaged
            # PyTorch CUDA runtime targets Volta/Turing-era and newer devices;
            # Blackwell is supported by cu128. Unsupported/unknown devices use
            # the CPU runtime instead of failing during the first CUDA kernel.
            if ($NvidiaDriverVersion -and $NvidiaDriverVersion -ge [Version]"570.65" -and
                $null -ne $NvidiaComputeCapability -and $NvidiaComputeCapability -ge 7.0) {
                $TorchVariant = "cuda"
            }
        }
    }
}
}
$PythonArchiveName = "python-$PythonVersion-embed-amd64.zip"
$PythonArchiveUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$PythonArchiveSha256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
$NodeArchiveName = "node-v$NodeVersion-win-x64.zip"
$NodeArchiveUrl = "https://nodejs.org/dist/v$NodeVersion/$NodeArchiveName"
$NodeChecksumsUrl = "https://nodejs.org/dist/v$NodeVersion/SHASUMS256.txt"
$FfmpegArchiveName = [string]$Contract.ffmpegArchiveName
$FfmpegArchiveUrl = [string]$Contract.ffmpegPrimaryUrl
$FfmpegFallbackUrl = [string]$Contract.ffmpegFallbackUrl
$FfmpegArchiveSha256 = [string]$Contract.ffmpegArchiveSha256
$VcRedistUrl = "https://aka.ms/vs/17/release/vc_redist.x64.exe"

$null = New-Item -ItemType Directory -Path $LogDir -Force
function Write-Stage([string]$Message) {
    $Line = "[{0}] [Clippy setup] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Output $Line
    try { [System.IO.File]::AppendAllText($SetupLogPath, $Line + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false)) } catch { }
}

function Remove-ClippyScratchRoot {
    $scratch = $script:ScratchRoot
    if (-not [string]::IsNullOrWhiteSpace($scratch) -and (Test-Path -LiteralPath $scratch -PathType Container)) {
        Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }
    $script:ScratchRoot = $null
}

trap {
    $Failure = $_
    try {
        Write-Stage ("SETUP FAILED: " + $Failure.Exception.Message)
        Write-Stage ("Failure location: " + $Failure.InvocationInfo.PositionMessage)
        Write-Stage ("Diagnostic log: " + $SetupLogPath)
    } catch { }
    try { Remove-ClippyScratchRoot } catch { }
    exit 1
}

Write-Stage "Runtime setup engine started."
Write-Stage ("Selected prebuilt Python runtime variant: " + $TorchVariant)
if ($ForceCpuRuntime) {
    Write-Stage "CPU runtime selection was explicitly forced by CLIPPY_FORCE_CPU_RUNTIME=1."
}

# Load script dependencies only after logging and the failure trap are active.
# This turns missing packaged helpers into a useful diagnostic instead of an
# early PowerShell dot-source failure with no Clippy setup context.
foreach ($Helper in @("runtime-manifest-state.ps1", "runtime-archive.ps1", "runtime-health.ps1", "runtime-ffmpeg.ps1")) {
    $HelperPath = Join-Path $PSScriptRoot $Helper
    if (-not (Test-Path -LiteralPath $HelperPath -PathType Leaf)) {
        throw "Application payload is incomplete. Missing required runtime helper: $HelperPath"
    }
}
. (Join-Path $PSScriptRoot "runtime-manifest-state.ps1")
. (Join-Path $PSScriptRoot "runtime-archive.ps1")
. (Join-Path $PSScriptRoot "runtime-health.ps1")
. (Join-Path $PSScriptRoot "runtime-ffmpeg.ps1")
if ($NvidiaGpuName) {
    Write-Stage ("Detected NVIDIA GPU: " + $NvidiaGpuName + "; driver " + $NvidiaDriverVersion + "; compute capability " + $NvidiaComputeCapability)
    if ($TorchVariant -eq "cpu") {
        Write-Stage "NVIDIA driver or compute capability is not supported by the packaged CUDA 12.8 runtime; using the CPU runtime."
    }
}

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

            $ExpectedTotalBytes = $null
            if ($Status -eq 206) {
                $ContentRange = $Response.Headers["Content-Range"]
                if ($ContentRange -notmatch "^bytes\s+(\d+)-(\d+)/(\d+)$") {
                    throw "Server returned a missing or invalid Content-Range while resuming $Url"
                }
                $RangeStart = [long]$Matches[1]
                $RangeEnd = [long]$Matches[2]
                $ExpectedTotalBytes = [long]$Matches[3]
                if ($RangeStart -ne $Offset -or $RangeEnd -lt $RangeStart -or $ExpectedTotalBytes -le $RangeEnd) {
                    throw "Server returned an inconsistent Content-Range while resuming $Url"
                }
                $ExpectedResponseBytes = $RangeEnd - $RangeStart + 1
                if ($Response.ContentLength -ge 0 -and $Response.ContentLength -ne $ExpectedResponseBytes) {
                    throw "Server Content-Length does not match Content-Range while downloading $Url"
                }
            } elseif ($Response.ContentLength -ge 0) {
                $ExpectedTotalBytes = [long]$Response.ContentLength
            }

            $InputStream = $Response.GetResponseStream()
            $Mode = if ($Offset -gt 0 -and $Status -eq 206) { [IO.FileMode]::Append } else { [IO.FileMode]::Create }
            $OutputStream = [IO.File]::Open($Partial, $Mode, [IO.FileAccess]::Write, [IO.FileShare]::None)
            $Buffer = New-Object byte[] (1024 * 1024)
            $Downloaded = $Offset
            $LastReportedPercent = -1
            while (($Read = $InputStream.Read($Buffer, 0, $Buffer.Length)) -gt 0) {
                $OutputStream.Write($Buffer, 0, $Read)
                $Downloaded += $Read
                if ($ExpectedTotalBytes -gt 0) {
                    $Percent = [int][math]::Floor(($Downloaded * 100.0) / $ExpectedTotalBytes)
                    if ($Percent -ge $LastReportedPercent + 10) {
                        $LastReportedPercent = $Percent
                        Write-Stage ("{0}: {1}% ({2:N0}/{3:N0} bytes)." -f [IO.Path]::GetFileName($Destination), $Percent, $Downloaded, $ExpectedTotalBytes)
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
            if ($null -ne $ExpectedTotalBytes -and (Get-Item -LiteralPath $Partial).Length -ne $ExpectedTotalBytes) {
                throw "Download ended before the server-declared content length was received. Partial data has been preserved for resume."
            }
            Move-Item -LiteralPath $Partial -Destination $Destination -Force
            Write-Stage "Download complete: $([IO.Path]::GetFileName($Destination))."
            return
        } catch {
            $Message = $_.Exception.Message
            if ($OutputStream) { $OutputStream.Dispose(); $OutputStream = $null }
            if ($InputStream) { $InputStream.Dispose(); $InputStream = $null }
            if ($Response) { $Response.Close(); $Response = $null }

            # A missing release or asset is permanent until the publisher fixes
            # it. Do not waste time retrying an HTTP 404 three times.
            $ErrorResponse = $_.Exception.Response
            if ($ErrorResponse -is [System.Net.HttpWebResponse] -and [int]$ErrorResponse.StatusCode -eq 404) {
                $ErrorResponse.Close()
                throw "HTTP 404: required download asset was not found: $Url. Confirm that the matching Clippy release exists and contains this asset."
            }

            # A completed partial file can legitimately receive HTTP 416 when
            # the server is asked to resume exactly at EOF. Promote it and let
            # the caller's mandatory SHA-256 verification decide whether it is
            # usable. If it is longer than the server object, discard it and
            # retry from byte zero.
            $ErrorResponse = $_.Exception.Response
            if ($ErrorResponse -is [System.Net.HttpWebResponse]) {
                try {
                    if ([int]$ErrorResponse.StatusCode -eq 416) {
                        $RangeHeader = $ErrorResponse.Headers["Content-Range"]
                        if ($RangeHeader -match "^bytes\s+\*/(\d+)$") {
                            $ServerLength = [long]$Matches[1]
                            $PartialLength = if (Test-Path -LiteralPath $Partial) { (Get-Item -LiteralPath $Partial).Length } else { 0L }
                            if ($PartialLength -eq $ServerLength -and $ServerLength -gt 0) {
                                $ErrorResponse.Close()
                                Move-Item -LiteralPath $Partial -Destination $Destination -Force
                                Write-Stage "Resumed download was already complete; promoted the verified partial file."
                                return
                            }
                            if ($PartialLength -ne $ServerLength) {
                                Remove-Item -LiteralPath $Partial -Force -ErrorAction SilentlyContinue
                                Write-Stage "Discarded an inconsistent partial download after HTTP 416 and will restart from byte zero."
                            }
                        }
                    }
                } finally {
                    $ErrorResponse.Close()
                }
            }

            if ($Attempt -eq 3) { throw "Download failed after 3 attempts: $Url. $Message" }
            Write-Stage "Download interrupted; preserving valid partial data for resume. $Message"
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

# Prefer per-user temporary storage; inaccessible fixed volumes are skipped.
$ScratchCandidates = @([IO.Path]::GetTempPath()) + @([IO.DriveInfo]::GetDrives() |
    Where-Object { $_.IsReady -and $_.DriveType -eq [IO.DriveType]::Fixed } |
    Sort-Object AvailableFreeSpace -Descending | ForEach-Object { $_.RootDirectory.FullName })
foreach ($componentPath in @($PythonDir, $NodeDir, $FfmpegDir, $BrowserDir)) { Restore-ClippyComponent $componentPath }
foreach ($Required in @("app.py", "requirements.txt", "setup-runtime.ps1", "runtime-archive.ps1", "runtime-manifest-state.ps1", "VERSION", "bgutil-provider\server\build\generate_once.js")) {
    if (-not (Test-Path (Join-Path $App $Required))) {
        throw "Application payload is incomplete. Missing $Required in $App"
    }
}

$RequirementsHash = (Get-FileHash (Join-Path $App "requirements.txt") -Algorithm SHA256).Hash.ToLowerInvariant()
$RemotionPackagePath = Join-Path $App "render-service\node_modules\@remotion\renderer\package.json"
if (-not (Test-Path -LiteralPath $RemotionPackagePath -PathType Leaf)) {
    throw "Remotion renderer package is missing from the application payload: $RemotionPackagePath"
}
$RemotionVersion = (Get-Content -LiteralPath $RemotionPackagePath -Raw | ConvertFrom-Json).version
if ([string]::IsNullOrWhiteSpace($RemotionVersion)) { throw "Could not determine the bundled Remotion renderer version." }

# Build expected state from runtime contract
$ExpectedState = New-ClippyRuntimeState -PythonVersion $PythonVersion -PythonVariant $TorchVariant -NodeVersion $NodeVersion -FfmpegVersion $FfmpegVersion -BrowserVersion $RemotionVersion -RequirementsSha256 $RequirementsHash
if (Test-Path $ManifestPath) {
    try {
        $Existing = Get-Content $ManifestPath -Raw | ConvertFrom-Json
        $PythonExe = Join-Path $PythonDir "python.exe"
        $NodeExe = Join-Path $NodeDir "node.exe"
        $FfmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"
        $RuntimeFilesPresent =
            (Test-Path -LiteralPath $PythonExe -PathType Leaf) -and
            (Test-Path -LiteralPath $NodeExe -PathType Leaf) -and
            (Test-Path -LiteralPath $FfmpegExe -PathType Leaf) -and
            (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf) -and
            (Test-Path -LiteralPath $BrowserVersionFile -PathType Leaf) -and
            ((Get-Content -LiteralPath $BrowserVersionFile -Raw).Trim() -eq $RemotionVersion)
        $ManifestComponentsHealthy = $Existing.version -eq "1.0.0" -and $Existing.schema -eq 1
        foreach ($componentName in @("python", "node", "ffmpeg", "browser")) {
            $component = $Existing.components.$componentName
            if (-not $component -or -not $component.installed -or [string]::IsNullOrWhiteSpace([string]$component.version)) {
                $ManifestComponentsHealthy = $false
            }
        }
        $ManifestComponentsHealthy = $ManifestComponentsHealthy -and
            ($Existing.components.python.version -eq $PythonVersion) -and
            ($Existing.components.node.version -eq $NodeVersion) -and
            ($Existing.components.ffmpeg.version -eq $FfmpegVersion) -and
            ($Existing.components.browser.version -eq $RemotionVersion) -and
            ($Existing.requirementsSha256 -eq $RequirementsHash) -and
            ($Existing.browserSha256 -match "^[a-fA-F0-9]{64}$") -and
            ($Existing.browserSha256 -eq $Contract.browserSha256) -and
            ($Existing.browserSha256 -eq (Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant())
        if ($Existing.state -eq $ExpectedState -and $RuntimeFilesPresent -and $ManifestComponentsHealthy) {
            Write-Stage "Verifying installed Python, Node.js, FFmpeg, backend, and Remotion dependencies..."
            $PythonVersionHealthy = Test-ClippyExecutable $PythonExe '--version' "Python $PythonVersion"
            $NodeVersionHealthy = Test-ClippyExecutable $NodeExe '--version' "v$NodeVersion"
            $FfmpegHealthy = (Test-ClippyExecutable $FfmpegExe '-version') -and (Test-ClippyExecutable (Join-Path $FfmpegDir 'ffprobe.exe') '-version')
            $PythonHealthy = $false
            $NodeHealthy = $false
            $CudaDllDirectories = @()
            $CudaDllsHealthy = $true
            if ($TorchVariant -eq "cuda") {
                # Windows PyTorch CUDA wheels place their CUDA DLLs in torch\lib.
                $CudaDllDirectory = Join-Path $PythonDir "Lib\site-packages\torch\lib"
                $CudaDllDirectories = @($CudaDllDirectory)
                $RequiredCudaDlls = @(
                    (Join-Path $CudaDllDirectory "cublas64_12.dll"),
                    (Join-Path $CudaDllDirectory "cudnn64_9.dll"),
                    (Join-Path $CudaDllDirectory "cudart64_12.dll")
                )
                foreach ($dll in $RequiredCudaDlls) {
                    if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) { $CudaDllsHealthy = $false }
                }
                if ($CudaDllsHealthy) { $env:PATH = (($CudaDllDirectories -join ";") + ";" + $env:PATH) }
            }
            Push-Location $App
            try {
                $env:CLIPPY_DATA_DIR = $DataRoot
                $env:OUTPUT_DIR = Join-Path $DataRoot "output"
                $env:UPLOAD_DIR = Join-Path $DataRoot "uploads"
                $env:CLIPPY_SETTINGS_PATH = Join-Path $Root "settings.json"
                $env:CLIPPY_MODELS_DIR = Join-Path $DataRoot "models"
                $env:REFERENCE_TEMPLATES_DIR = Join-Path $DataRoot 'reference_templates'
                $PythonHealthScript = "import app, torch, faster_whisper"
                if ($TorchVariant -eq "cuda") {
                    $PythonHealthScript += "; import ctranslate2; assert torch.version.cuda and torch.version.cuda.startswith('12.8'); assert torch.cuda.is_available(); x=torch.ones((64,64),device='cuda'); y=x @ x; torch.cuda.synchronize(); assert float(y[0,0].item()) == 64.0; assert ctranslate2.get_cuda_device_count() > 0"
                } else {
                    $PythonHealthScript += "; assert torch.version.cuda is None"
                }
                $PythonHealthy = $PythonVersionHealthy -and $CudaDllsHealthy -and (Test-ClippyExecutable $PythonExe ('-c "' + $PythonHealthScript + '"') '' 120)
                $env:REMOTION_BROWSER_EXECUTABLE = $BrowserExecutable
                $BrowserCheck = "import('@remotion/renderer').then(async m => { await m.ensureBrowser({browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE}); }).catch(e => { console.error(e); process.exit(1); });"
                Push-Location (Join-Path $App "render-service")
                try {
                    $BrowserPackageHealthy = Test-ClippyExecutable $NodeExe ('-e "' + $BrowserCheck + '"')
                    $NodeHealthy = ($NodeVersionHealthy -and $BrowserPackageHealthy) -and (Test-ClippyExecutable $BrowserExecutable '--headless --disable-gpu --dump-dom about:blank')
                } finally {
                    Pop-Location
                }
            } finally {
                Pop-Location
            }
            if ($PythonHealthy -and $NodeHealthy -and $FfmpegHealthy) {
                Write-Stage "Managed runtimes and application dependencies are healthy. No downloads needed."
                Remove-ClippyScratchRoot
                exit 0
            }
            Write-Stage "A runtime health check failed; repairing dependencies."
        }
    } catch {
        Write-Stage "Previous runtime manifest is invalid; repairing managed runtimes."
    }
}

$script:ScratchRoot = New-ClippyScratch $ScratchCandidates -RuntimeRoot $Root
$ScratchDrive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($ScratchRoot))
$env:TEMP = $ScratchRoot
$env:TMP = $ScratchRoot
$env:PIP_CACHE_DIR = Join-Path $ScratchRoot 'pip-cache'
Write-Stage ("Using " + $ScratchRoot + " for temporary setup files; managed runtimes remain in " + $Root)
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
if ($AppVersion -notmatch "^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$") { throw "Application VERSION file is missing or invalid." }

$PythonRuntimeName = "clippy-python-$TorchVariant-$AppVersion.zip"
$PythonRuntimeArchive = Join-Path $Downloads $PythonRuntimeName
$PythonRuntimeManifestName = "clippy-python-$TorchVariant.manifest.json"
$PythonRuntimeManifestUrl = "https://github.com/helalxp/clippy/releases/download/v$AppVersion/$PythonRuntimeManifestName"
$PythonRuntimeReleaseBaseUrl = "https://github.com/helalxp/clippy/releases/download/v$AppVersion"
$LocalRuntimeArchive = $env:CLIPPY_PYTHON_RUNTIME_ARCHIVE
$LocalRuntimeChecksum = $env:CLIPPY_PYTHON_RUNTIME_CHECKSUM

# Local archive overrides remain available for developer diagnostics. Customer
# installs use only the manifest and assets from the exact matching release.
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
    $PythonRuntimeManifestPath = Join-Path $Downloads "$AppVersion-$PythonRuntimeManifestName"
    Download-File $PythonRuntimeManifestUrl $PythonRuntimeManifestPath
    $ManifestParsed = $false
    for ($ManifestAttempt = 1; $ManifestAttempt -le 2; $ManifestAttempt++) {
        try {
            $RuntimeManifest = Get-Content -LiteralPath $PythonRuntimeManifestPath -Raw | ConvertFrom-Json
            $ManifestParsed = $true
            break
        } catch {
            Remove-Item -LiteralPath $PythonRuntimeManifestPath -Force -ErrorAction SilentlyContinue
            if ($ManifestAttempt -eq 2) {
                throw "The runtime manifest downloaded from release v$AppVersion is not valid JSON: $PythonRuntimeManifestUrl"
            }
            Write-Stage "Cached runtime manifest was invalid; downloading it again."
            Download-File $PythonRuntimeManifestUrl $PythonRuntimeManifestPath
        }
    }
    if (-not $ManifestParsed) { throw "Could not read the runtime manifest for release v$AppVersion." }
    Assert-ClippyRuntimeArchiveManifest -Manifest $RuntimeManifest -ExpectedApplicationVersion $AppVersion -ExpectedVariant $TorchVariant | Out-Null

    foreach ($Part in @($RuntimeManifest.parts)) {
        $PartName = [string]$Part.name
        $PartUrl = "$PythonRuntimeReleaseBaseUrl/$PartName"
        $PartPath = Join-Path $Downloads $PartName
        $PartHealthy = $false
        if (Test-Path -LiteralPath $PartPath -PathType Leaf) {
            $PartInfo = Get-Item -LiteralPath $PartPath
            if ($PartInfo.Length -eq [long]$Part.size -and
                (Get-ClippyFileSha256 $PartPath) -eq ([string]$Part.sha256).ToLowerInvariant()) {
                $PartHealthy = $true
                Write-Stage "Reusing verified runtime part $PartName."
            } else {
                Write-Stage "Cached runtime part $PartName failed verification; downloading it again."
                Remove-Item -LiteralPath $PartPath -Force
            }
        }
        if (-not $PartHealthy) {
            Download-File $PartUrl $PartPath
            $PartInfo = Get-Item -LiteralPath $PartPath
            if ($PartInfo.Length -ne [long]$Part.size -or
                (Get-ClippyFileSha256 $PartPath) -ne ([string]$Part.sha256).ToLowerInvariant()) {
                Remove-Item -LiteralPath $PartPath -Force -ErrorAction SilentlyContinue
                throw "Downloaded runtime part failed size or SHA-256 verification: $PartName"
            }
        }
    }

    Write-Stage "Reconstructing the verified $TorchVariant Python runtime archive from $($RuntimeManifest.partCount) release asset(s)..."
    Join-ClippyRuntimeArchiveParts -Manifest $RuntimeManifest -PartsDirectory $Downloads -Destination $PythonRuntimeArchive | Out-Null
    $PythonRuntimeVerified = $true
}
if (-not $PythonRuntimeVerified) { throw "Could not verify the downloaded Python runtime." }

$PythonStage = Join-Path $Runtime "python.installing"
if (Test-Path $PythonStage) { Remove-Item $PythonStage -Recurse -Force }
Write-Stage "Extracting the verified $TorchVariant Python runtime..."
Expand-ArchiveFast $PythonRuntimeArchive $PythonStage
$StagedPython = Join-Path $PythonStage "python.exe"
if (-not (Test-Path -LiteralPath $StagedPython -PathType Leaf)) {
    throw "Verified Python runtime archive does not contain python.exe at its root."
}
$StagedVersion = (& $StagedPython --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Packaged Python executable failed its version check: $StagedVersion"
}
Assert-ClippyPythonRuntimeVersion -Actual $StagedVersion -Expected $PythonVersion
$StagedImportCheck = "import torch, torchvision, fastapi, uvicorn, faster_whisper; print('torch=' + torch.__version__); print('cuda_build=' + str(torch.version.cuda))"
& $StagedPython -c $StagedImportCheck
if ($LASTEXITCODE -ne 0) { throw "Packaged Python dependency verification failed." }
if ($TorchVariant -eq "cuda") {
    & $StagedPython -c "import torch; assert torch.version.cuda is not None, 'CUDA-enabled PyTorch is missing'"
    if ($LASTEXITCODE -ne 0) { throw "Selected CUDA runtime does not contain CUDA-enabled PyTorch." }
}

# Activate only after archive hash, Python version, and critical imports pass.
Install-ClippyComponent $PythonStage $PythonDir {
    param($dir)
    Test-ClippyExecutable (Join-Path $dir 'python.exe') '-c "import torch,fastapi,faster_whisper"' '' 120
}
$PythonExe = Join-Path $PythonDir 'python.exe'

# Node's archive is checked against the SHA-256 value published alongside the
# official Node.js release archive.
$NodeExe = Join-Path $NodeDir "node.exe"
$ExistingNodeHealthy = Test-ClippyExecutable $NodeExe '--version' "v$NodeVersion"
if (-not $ExistingNodeHealthy) {
    Write-Stage 'Managed Node.js runtime requires replacement.'
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
    $NodeStage = "$NodeDir.installing"
    if (Test-Path -LiteralPath $NodeStage) { Remove-Item -LiteralPath $NodeStage -Recurse -Force }
    Copy-Item -LiteralPath $ExtractedRoot -Destination $NodeStage -Recurse
    Install-ClippyComponent $NodeStage $NodeDir { param($dir) Test-ClippyExecutable (Join-Path $dir 'node.exe') '--version' "v$NodeVersion" }
    Remove-Item $Extract -Recurse -Force
}
$InstalledNodeVersion = (& $NodeExe --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $InstalledNodeVersion.TrimStart([char]"v") -ne $NodeVersion) {
    throw "Managed Node.js runtime version check failed. Expected $NodeVersion, found $InstalledNodeVersion."
}

# Both publisher endpoints must provide the exact pinned FFmpeg archive.
# The expected digest is part of the runtime contract, not fetched at install time.
$FfmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"
$FfmpegCheck = { param($dir) (Test-ClippyExecutable (Join-Path $dir 'ffmpeg.exe') '-version') -and (Test-ClippyExecutable (Join-Path $dir 'ffprobe.exe') '-version') }
$ExistingFfmpegHealthy = & $FfmpegCheck $FfmpegDir
if (-not $ExistingFfmpegHealthy) {
    Write-Stage 'Managed FFmpeg runtime requires replacement.'
    $FfmpegZip = Join-Path $Downloads $FfmpegArchiveName
    Get-ClippyFfmpegArchive -PrimaryUrl $FfmpegArchiveUrl -FallbackUrl $FfmpegFallbackUrl -ExpectedSha256 $FfmpegArchiveSha256 -ArchivePath $FfmpegZip | Out-Null
    $Extract = Join-Path $ScratchRoot "ffmpeg-extract"
    if (Test-Path $Extract) { Remove-Item $Extract -Recurse -Force }
    Expand-ArchiveFast $FfmpegZip $Extract
    $FfmpegBinary = Get-ChildItem $Extract -Filter "ffmpeg.exe" -Recurse | Select-Object -First 1
    if (-not $FfmpegBinary) { throw "FFmpeg archive did not contain ffmpeg.exe." }
    $SourceBin = $FfmpegBinary.Directory.FullName
    $FfmpegStage = "$FfmpegDir.installing"
    if (Test-Path -LiteralPath $FfmpegStage) { Remove-Item -LiteralPath $FfmpegStage -Recurse -Force }
    Copy-Item -LiteralPath $SourceBin -Destination $FfmpegStage -Recurse
    Install-ClippyComponent $FfmpegStage $FfmpegDir $FfmpegCheck
    Remove-Item $Extract -Recurse -Force
}
& $FfmpegExe -version
if ($LASTEXITCODE -ne 0) { throw "Managed FFmpeg runtime failed its version check." }

if ($TorchVariant -eq "cuda") {
    # Windows PyTorch CUDA wheels place their CUDA DLLs in torch\lib.
    $CudaDllDirectory = Join-Path $PythonDir "Lib\site-packages\torch\lib"
    $CudaDllDirectories = @($CudaDllDirectory)
    $RequiredCudaDlls = @(
        (Join-Path $CudaDllDirectory "cublas64_12.dll"),
        (Join-Path $CudaDllDirectory "cudnn64_9.dll"),
        (Join-Path $CudaDllDirectory "cudart64_12.dll")
    )
    foreach ($dll in $RequiredCudaDlls) {
        if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) {
            throw "CUDA runtime is missing a required DLL for PyTorch/CTranslate2: $dll"
        }
    }
    $env:PATH = (($CudaDllDirectories -join ";") + ";" + $env:PATH)
}

Write-Stage "Verifying backend imports..."
Push-Location $App
try {
    $env:CLIPPY_DATA_DIR = $DataRoot
    $env:OUTPUT_DIR = Join-Path $DataRoot "output"
    $env:UPLOAD_DIR = Join-Path $DataRoot "uploads"
    $env:CLIPPY_SETTINGS_PATH = Join-Path $Root "settings.json"
    $env:CLIPPY_MODELS_DIR = Join-Path $DataRoot "models"
    $env:REFERENCE_TEMPLATES_DIR = Join-Path $DataRoot 'reference_templates'
    & $PythonExe -c "import app; import torch; import faster_whisper; import ctranslate2; print('Backend imports OK; torch CUDA:', torch.cuda.is_available())"
    if ($LASTEXITCODE -ne 0) { throw "Backend import verification failed. Check the Python dependency log." }
    if ($TorchVariant -eq "cuda") {
        Write-Stage "Running a real CUDA kernel and faster-whisper device capability check..."
        & $PythonExe -c "import torch, ctranslate2; assert torch.version.cuda and torch.version.cuda.startswith('12.8'), f'Expected CUDA 12.8, got {torch.version.cuda}'; assert torch.cuda.is_available(), 'PyTorch cannot initialize the NVIDIA device'; x=torch.ones((64,64),device='cuda'); y=x @ x; torch.cuda.synchronize(); assert float(y[0,0].item()) == 64.0, 'CUDA kernel produced an unexpected result'; count=ctranslate2.get_cuda_device_count(); assert count > 0, 'CTranslate2/faster-whisper cannot see a CUDA device'; print('CUDA kernel OK:', torch.cuda.get_device_name(0), '| CTranslate2 devices:', count)"
        if ($LASTEXITCODE -ne 0) {
            throw "CUDA runtime verification failed. Clippy will not mark an unusable CUDA installation as healthy. Check the NVIDIA driver, CUDA DLL paths, and GPU compatibility in the setup log."
        }
    }
} finally {
    Pop-Location
}

Write-Stage "Verifying the persistent Remotion browser runtime..."
$InstalledBrowserVersion = if (Test-Path -LiteralPath $BrowserVersionFile) { (Get-Content -LiteralPath $BrowserVersionFile -Raw).Trim() } else { "" }
$BrowserNeedsInstall = -not (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf) -or $InstalledBrowserVersion -ne $RemotionVersion
if (-not $BrowserNeedsInstall) {
    $BrowserNeedsInstall = ((Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Contract.browserSha256) -or -not (Test-ClippyExecutable $BrowserExecutable '--headless --disable-gpu --dump-dom about:blank')
}
if ($BrowserNeedsInstall) {
    Write-Stage "Installing or repairing the Remotion browser for renderer version $RemotionVersion..."
    # Google's headless shell is unsigned. Trust the publisher's versioned HTTPS
    # archive only after matching the immutable hashes shipped in the payload.
    $BrowserArchive = Join-Path $Downloads "chrome-headless-shell-$($Contract.browserVersion)-win64.zip"
    Download-File $BrowserArchiveUrl $BrowserArchive
    try { Assert-Sha256 $BrowserArchive $Contract.browserArchiveSha256 } catch {
        Remove-Item -LiteralPath $BrowserArchive -Force
        Download-File $BrowserArchiveUrl $BrowserArchive
        Assert-Sha256 $BrowserArchive $Contract.browserArchiveSha256
    }
    $BrowserExtract = Join-Path $ScratchRoot 'browser-extract'
    Expand-ArchiveFast $BrowserArchive $BrowserExtract
    $DownloadedBrowserDir = Join-Path $BrowserExtract 'chrome-headless-shell-win64'
    Assert-Sha256 (Join-Path $DownloadedBrowserDir 'chrome-headless-shell.exe') $Contract.browserSha256
    $BrowserStage = "$BrowserDir.installing"
    if (Test-Path -LiteralPath $BrowserStage) { Remove-Item -LiteralPath $BrowserStage -Recurse -Force }
    Copy-Item -LiteralPath $DownloadedBrowserDir -Destination $BrowserStage -Recurse
    Install-ClippyComponent $BrowserStage $BrowserDir {
        param($dir)
        $exe = Join-Path $dir 'chrome-headless-shell.exe'
        ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Contract.browserSha256) -and (Test-ClippyExecutable $exe '--headless --disable-gpu --dump-dom about:blank')
    }
    Remove-Item -LiteralPath $BrowserExtract -Recurse -Force
    [System.IO.File]::WriteAllText($BrowserVersionFile, $RemotionVersion, [System.Text.UTF8Encoding]::new($false))
} else {
    Write-Stage "Reusing the browser already installed for Remotion $RemotionVersion."
}

if (-not (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf)) {
    throw "Persistent Remotion browser executable is missing: $BrowserExecutable"
}
Assert-Sha256 $BrowserExecutable $Contract.browserSha256
$BrowserSha256 = (Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
$env:REMOTION_BROWSER_EXECUTABLE = $BrowserExecutable
$BrowserValidation = "import('@remotion/renderer').then(async m => { await m.ensureBrowser({browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE}); console.log('Persistent Remotion browser ready'); }).catch(e => { console.error(e); process.exit(1); });"
Push-Location (Join-Path $App "render-service")
try {
    & $NodeExe -e $BrowserValidation
    if ($LASTEXITCODE -ne 0) { throw "Persistent Remotion browser validation failed." }
} finally {
    Pop-Location
}


New-Item -ItemType Directory -Path (Split-Path $ManifestPath -Parent) -Force | Out-NULL
$Manifest = @{
    version = "1.0.0"
    components = @{
        python = @{ version = $PythonVersion; installed = $true }
        node = @{ version = $NodeVersion; installed = $true }
        ffmpeg = @{ version = $FfmpegVersion; installed = $true }
        browser = @{ version = $RemotionVersion; installed = $true }
    }
    schema = 1
    state = $ExpectedState
    installedAt = (Get-Date).ToUniversalTime().ToString("o")
    requirementsSha256 = $RequirementsHash
    browserSha256 = $BrowserSha256
    gpuMode = if ($TorchVariant -eq "cuda") { "cuda128" } else { "cpu" }
}
$ManifestJson = $Manifest | ConvertTo-Json -Depth 5
# Windows PowerShell 5.1 writes a UTF-8 BOM with Set-Content -Encoding UTF8.
# serde_json expects plain JSON, so write UTF-8 explicitly without a BOM.
[System.IO.File]::WriteAllText($ManifestPath, $ManifestJson, [System.Text.UTF8Encoding]::new($false))
# Remove the multi-gigabyte Python archive and release parts only after the
# complete runtime setup has succeeded. If setup fails earlier, verified parts
# remain available for a retry without downloading them again.
if ([string]::IsNullOrWhiteSpace($LocalRuntimeArchive) -and $RuntimeManifest) {
    Remove-Item -LiteralPath $PythonRuntimeArchive, $PythonRuntimeManifestPath -Force -ErrorAction SilentlyContinue
    foreach ($Part in @($RuntimeManifest.parts)) {
        Remove-Item -LiteralPath (Join-Path $Downloads ([string]$Part.name)) -Force -ErrorAction SilentlyContinue
    }
}
Remove-ClippyScratchRoot
Write-Stage "Runtime setup completed successfully."
} finally {
    $InstallMutex.ReleaseMutex(); $InstallMutex.Dispose()
    if ($DesktopMutex) { $DesktopMutex.ReleaseMutex(); $DesktopMutex.Dispose() }
}
 -or $Contract.node -notmatch '^\d+\.\d+\.\d+
$PythonVersion = $Contract.python
$NodeVersion = $Contract.node
$FfmpegVersion = $Contract.ffmpeg
$TorchVariant = 'cpu'
if ($Contract.browserVersion -notmatch '^\d+\.\d+\.\d+\.\d+$' -or $Contract.browserArchiveSha256 -notmatch '^[a-f0-9]{64}$' -or $Contract.browserSha256 -notmatch '^[a-f0-9]{64}$') { throw 'Browser integrity contract is invalid.' }
$BrowserArchiveUrl = "https://storage.googleapis.com/chrome-for-testing-public/$($Contract.browserVersion)/win64/chrome-headless-shell-win64.zip"

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
$DataRoot = Join-Path $Root "data"
$StorageLocationPath = Join-Path $Root "storage-location.json"
if (Test-Path -LiteralPath $StorageLocationPath -PathType Leaf) {
    try {
        $StorageLocation = Get-Content -LiteralPath $StorageLocationPath -Raw | ConvertFrom-Json
        $ConfiguredDataRoot = [string]$StorageLocation.data_directory
        if ($StorageLocation.schema_version -ne 1 -or [string]::IsNullOrWhiteSpace($ConfiguredDataRoot)) {
            throw "Storage location configuration is incomplete or unsupported."
        }
        $DataRoot = [IO.Path]::GetFullPath($ConfiguredDataRoot)
        if ($DataRoot -notmatch '^[A-Za-z]:\\|^\\\\') {
            throw "Configured Clippy data directory must be an absolute Windows path."
        }
        if (-not (Test-Path -LiteralPath $DataRoot -PathType Container)) {
            throw "Configured Clippy data directory is unavailable: $DataRoot"
        }
    } catch {
        throw "Cannot load Clippy's configured data directory: $($_.Exception.Message)"
    }
}
$PythonDir = Join-Path $Runtime "python"
$NodeDir = Join-Path $Runtime "node"
$FfmpegDir = Join-Path $Runtime "ffmpeg\bin"
$ManifestPath = Join-Path $Root "runtime-manifest.json"
# Browser binaries are durable user data, not part of app\current. Updating the
# application payload must not force a multi-hundred-MB browser download.
$BrowserRoot = Join-Path $Root "browser"
$BrowserDir = Join-Path $BrowserRoot "headless-shell"
$BrowserExecutable = Join-Path $BrowserDir "chrome-headless-shell.exe"
$BrowserVersionFile = Join-Path $BrowserRoot "remotion-version.txt"
$LogDir = Join-Path $Root "logs"
$SetupLogPath = Join-Path $LogDir "runtime-setup.log"
$script:ScratchRoot = $null
$NvidiaDriverVersion = $null
$NvidiaGpuName = $null
$NvidiaComputeCapability = $null
$ForceCpuRuntime = $env:CLIPPY_FORCE_CPU_RUNTIME -eq "1"
if (-not $ForceCpuRuntime) {
    $Nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
$NvidiaSmiPath = if ($Nvidia) { $Nvidia.Source } else { $null }
if (-not $NvidiaSmiPath) {
    $NvidiaCandidates = @(
        (Join-Path $env:ProgramFiles "NVIDIA Corporation\NVSMI\nvidia-smi.exe"),
        (Join-Path $env:SystemRoot "System32\nvidia-smi.exe")
    )
    $NvidiaSmiPath = $NvidiaCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if ($NvidiaSmiPath) {
    $NvidiaInfo = & $NvidiaSmiPath --query-gpu=name,driver_version,compute_cap --format=csv,noheader 2>$null
    if ($LASTEXITCODE -eq 0 -and $NvidiaInfo) {
        $NvidiaLine = @($NvidiaInfo) | Select-Object -First 1
        $NvidiaFields = ([string]$NvidiaLine).Split(',')
        if ($NvidiaFields.Count -ge 3) {
            $NvidiaGpuName = $NvidiaFields[0].Trim()
            $DriverText = $NvidiaFields[1].Trim()
            try { $NvidiaDriverVersion = [Version]$DriverText } catch { $NvidiaDriverVersion = $null }
            $ParsedComputeCapability = 0.0
            if ([double]::TryParse($NvidiaFields[2].Trim(), [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$ParsedComputeCapability)) {
                $NvidiaComputeCapability = $ParsedComputeCapability
            }
            # CUDA 12.8 GA requires Windows driver 570.65. The packaged
            # PyTorch CUDA runtime targets Volta/Turing-era and newer devices;
            # Blackwell is supported by cu128. Unsupported/unknown devices use
            # the CPU runtime instead of failing during the first CUDA kernel.
            if ($NvidiaDriverVersion -and $NvidiaDriverVersion -ge [Version]"570.65" -and
                $null -ne $NvidiaComputeCapability -and $NvidiaComputeCapability -ge 7.0) {
                $TorchVariant = "cuda"
            }
        }
    }
}
}
$PythonArchiveName = "python-$PythonVersion-embed-amd64.zip"
$PythonArchiveUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$PythonArchiveSha256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
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

function Remove-ClippyScratchRoot {
    $scratch = $script:ScratchRoot
    if (-not [string]::IsNullOrWhiteSpace($scratch) -and (Test-Path -LiteralPath $scratch -PathType Container)) {
        Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }
    $script:ScratchRoot = $null
}

trap {
    $Failure = $_
    try {
        Write-Stage ("SETUP FAILED: " + $Failure.Exception.Message)
        Write-Stage ("Failure location: " + $Failure.InvocationInfo.PositionMessage)
        Write-Stage ("Diagnostic log: " + $SetupLogPath)
    } catch { }
    try { Remove-ClippyScratchRoot } catch { }
    exit 1
}

Write-Stage "Runtime setup engine started."
Write-Stage ("Selected prebuilt Python runtime variant: " + $TorchVariant)
if ($ForceCpuRuntime) {
    Write-Stage "CPU runtime selection was explicitly forced by CLIPPY_FORCE_CPU_RUNTIME=1."
}

# Load script dependencies only after logging and the failure trap are active.
# This turns missing packaged helpers into a useful diagnostic instead of an
# early PowerShell dot-source failure with no Clippy setup context.
foreach ($Helper in @("runtime-manifest-state.ps1", "runtime-archive.ps1", "runtime-health.ps1")) {
    $HelperPath = Join-Path $PSScriptRoot $Helper
    if (-not (Test-Path -LiteralPath $HelperPath -PathType Leaf)) {
        throw "Application payload is incomplete. Missing required runtime helper: $HelperPath"
    }
}
. (Join-Path $PSScriptRoot "runtime-manifest-state.ps1")
. (Join-Path $PSScriptRoot "runtime-archive.ps1")
. (Join-Path $PSScriptRoot "runtime-health.ps1")
if ($NvidiaGpuName) {
    Write-Stage ("Detected NVIDIA GPU: " + $NvidiaGpuName + "; driver " + $NvidiaDriverVersion + "; compute capability " + $NvidiaComputeCapability)
    if ($TorchVariant -eq "cpu") {
        Write-Stage "NVIDIA driver or compute capability is not supported by the packaged CUDA 12.8 runtime; using the CPU runtime."
    }
}

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

            $ExpectedTotalBytes = $null
            if ($Status -eq 206) {
                $ContentRange = $Response.Headers["Content-Range"]
                if ($ContentRange -notmatch "^bytes\s+(\d+)-(\d+)/(\d+)$") {
                    throw "Server returned a missing or invalid Content-Range while resuming $Url"
                }
                $RangeStart = [long]$Matches[1]
                $RangeEnd = [long]$Matches[2]
                $ExpectedTotalBytes = [long]$Matches[3]
                if ($RangeStart -ne $Offset -or $RangeEnd -lt $RangeStart -or $ExpectedTotalBytes -le $RangeEnd) {
                    throw "Server returned an inconsistent Content-Range while resuming $Url"
                }
                $ExpectedResponseBytes = $RangeEnd - $RangeStart + 1
                if ($Response.ContentLength -ge 0 -and $Response.ContentLength -ne $ExpectedResponseBytes) {
                    throw "Server Content-Length does not match Content-Range while downloading $Url"
                }
            } elseif ($Response.ContentLength -ge 0) {
                $ExpectedTotalBytes = [long]$Response.ContentLength
            }

            $InputStream = $Response.GetResponseStream()
            $Mode = if ($Offset -gt 0 -and $Status -eq 206) { [IO.FileMode]::Append } else { [IO.FileMode]::Create }
            $OutputStream = [IO.File]::Open($Partial, $Mode, [IO.FileAccess]::Write, [IO.FileShare]::None)
            $Buffer = New-Object byte[] (1024 * 1024)
            $Downloaded = $Offset
            $LastReportedPercent = -1
            while (($Read = $InputStream.Read($Buffer, 0, $Buffer.Length)) -gt 0) {
                $OutputStream.Write($Buffer, 0, $Read)
                $Downloaded += $Read
                if ($ExpectedTotalBytes -gt 0) {
                    $Percent = [int][math]::Floor(($Downloaded * 100.0) / $ExpectedTotalBytes)
                    if ($Percent -ge $LastReportedPercent + 10) {
                        $LastReportedPercent = $Percent
                        Write-Stage ("{0}: {1}% ({2:N0}/{3:N0} bytes)." -f [IO.Path]::GetFileName($Destination), $Percent, $Downloaded, $ExpectedTotalBytes)
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
            if ($null -ne $ExpectedTotalBytes -and (Get-Item -LiteralPath $Partial).Length -ne $ExpectedTotalBytes) {
                throw "Download ended before the server-declared content length was received. Partial data has been preserved for resume."
            }
            Move-Item -LiteralPath $Partial -Destination $Destination -Force
            Write-Stage "Download complete: $([IO.Path]::GetFileName($Destination))."
            return
        } catch {
            $Message = $_.Exception.Message
            if ($OutputStream) { $OutputStream.Dispose(); $OutputStream = $null }
            if ($InputStream) { $InputStream.Dispose(); $InputStream = $null }
            if ($Response) { $Response.Close(); $Response = $null }

            # A missing release or asset is permanent until the publisher fixes
            # it. Do not waste time retrying an HTTP 404 three times.
            $ErrorResponse = $_.Exception.Response
            if ($ErrorResponse -is [System.Net.HttpWebResponse] -and [int]$ErrorResponse.StatusCode -eq 404) {
                $ErrorResponse.Close()
                throw "HTTP 404: required download asset was not found: $Url. Confirm that the matching Clippy release exists and contains this asset."
            }

            # A completed partial file can legitimately receive HTTP 416 when
            # the server is asked to resume exactly at EOF. Promote it and let
            # the caller's mandatory SHA-256 verification decide whether it is
            # usable. If it is longer than the server object, discard it and
            # retry from byte zero.
            $ErrorResponse = $_.Exception.Response
            if ($ErrorResponse -is [System.Net.HttpWebResponse]) {
                try {
                    if ([int]$ErrorResponse.StatusCode -eq 416) {
                        $RangeHeader = $ErrorResponse.Headers["Content-Range"]
                        if ($RangeHeader -match "^bytes\s+\*/(\d+)$") {
                            $ServerLength = [long]$Matches[1]
                            $PartialLength = if (Test-Path -LiteralPath $Partial) { (Get-Item -LiteralPath $Partial).Length } else { 0L }
                            if ($PartialLength -eq $ServerLength -and $ServerLength -gt 0) {
                                $ErrorResponse.Close()
                                Move-Item -LiteralPath $Partial -Destination $Destination -Force
                                Write-Stage "Resumed download was already complete; promoted the verified partial file."
                                return
                            }
                            if ($PartialLength -ne $ServerLength) {
                                Remove-Item -LiteralPath $Partial -Force -ErrorAction SilentlyContinue
                                Write-Stage "Discarded an inconsistent partial download after HTTP 416 and will restart from byte zero."
                            }
                        }
                    }
                } finally {
                    $ErrorResponse.Close()
                }
            }

            if ($Attempt -eq 3) { throw "Download failed after 3 attempts: $Url. $Message" }
            Write-Stage "Download interrupted; preserving valid partial data for resume. $Message"
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

# Prefer per-user temporary storage; inaccessible fixed volumes are skipped.
$ScratchCandidates = @([IO.Path]::GetTempPath()) + @([IO.DriveInfo]::GetDrives() |
    Where-Object { $_.IsReady -and $_.DriveType -eq [IO.DriveType]::Fixed } |
    Sort-Object AvailableFreeSpace -Descending | ForEach-Object { $_.RootDirectory.FullName })
foreach ($componentPath in @($PythonDir, $NodeDir, $FfmpegDir, $BrowserDir)) { Restore-ClippyComponent $componentPath }
foreach ($Required in @("app.py", "requirements.txt", "setup-runtime.ps1", "runtime-archive.ps1", "runtime-manifest-state.ps1", "VERSION", "bgutil-provider\server\build\generate_once.js")) {
    if (-not (Test-Path (Join-Path $App $Required))) {
        throw "Application payload is incomplete. Missing $Required in $App"
    }
}

$RequirementsHash = (Get-FileHash (Join-Path $App "requirements.txt") -Algorithm SHA256).Hash.ToLowerInvariant()
$RemotionPackagePath = Join-Path $App "render-service\node_modules\@remotion\renderer\package.json"
if (-not (Test-Path -LiteralPath $RemotionPackagePath -PathType Leaf)) {
    throw "Remotion renderer package is missing from the application payload: $RemotionPackagePath"
}
$RemotionVersion = (Get-Content -LiteralPath $RemotionPackagePath -Raw | ConvertFrom-Json).version
if ([string]::IsNullOrWhiteSpace($RemotionVersion)) { throw "Could not determine the bundled Remotion renderer version." }

# Build expected state from runtime contract
$ExpectedState = New-ClippyRuntimeState -PythonVersion $PythonVersion -PythonVariant $TorchVariant -NodeVersion $NodeVersion -FfmpegVersion $FfmpegVersion -BrowserVersion $RemotionVersion -RequirementsSha256 $RequirementsHash
if (Test-Path $ManifestPath) {
    try {
        $Existing = Get-Content $ManifestPath -Raw | ConvertFrom-Json
        $PythonExe = Join-Path $PythonDir "python.exe"
        $NodeExe = Join-Path $NodeDir "node.exe"
        $FfmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"
        $RuntimeFilesPresent =
            (Test-Path -LiteralPath $PythonExe -PathType Leaf) -and
            (Test-Path -LiteralPath $NodeExe -PathType Leaf) -and
            (Test-Path -LiteralPath $FfmpegExe -PathType Leaf) -and
            (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf) -and
            (Test-Path -LiteralPath $BrowserVersionFile -PathType Leaf) -and
            ((Get-Content -LiteralPath $BrowserVersionFile -Raw).Trim() -eq $RemotionVersion)
        $ManifestComponentsHealthy = $Existing.version -eq "1.0.0" -and $Existing.schema -eq 1
        foreach ($componentName in @("python", "node", "ffmpeg", "browser")) {
            $component = $Existing.components.$componentName
            if (-not $component -or -not $component.installed -or [string]::IsNullOrWhiteSpace([string]$component.version)) {
                $ManifestComponentsHealthy = $false
            }
        }
        $ManifestComponentsHealthy = $ManifestComponentsHealthy -and
            ($Existing.components.python.version -eq $PythonVersion) -and
            ($Existing.components.node.version -eq $NodeVersion) -and
            ($Existing.components.ffmpeg.version -eq $FfmpegVersion) -and
            ($Existing.components.browser.version -eq $RemotionVersion) -and
            ($Existing.requirementsSha256 -eq $RequirementsHash) -and
            ($Existing.browserSha256 -match "^[a-fA-F0-9]{64}$") -and
            ($Existing.browserSha256 -eq $Contract.browserSha256) -and
            ($Existing.browserSha256 -eq (Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant())
        if ($Existing.state -eq $ExpectedState -and $RuntimeFilesPresent -and $ManifestComponentsHealthy) {
            Write-Stage "Verifying installed Python, Node.js, FFmpeg, backend, and Remotion dependencies..."
            $PythonVersionHealthy = Test-ClippyExecutable $PythonExe '--version' "Python $PythonVersion"
            $NodeVersionHealthy = Test-ClippyExecutable $NodeExe '--version' "v$NodeVersion"
            $FfmpegHealthy = (Test-ClippyExecutable $FfmpegExe '-version') -and (Test-ClippyExecutable (Join-Path $FfmpegDir 'ffprobe.exe') '-version')
            $PythonHealthy = $false
            $NodeHealthy = $false
            $CudaDllDirectories = @()
            $CudaDllsHealthy = $true
            if ($TorchVariant -eq "cuda") {
                # Windows PyTorch CUDA wheels place their CUDA DLLs in torch\lib.
                $CudaDllDirectory = Join-Path $PythonDir "Lib\site-packages\torch\lib"
                $CudaDllDirectories = @($CudaDllDirectory)
                $RequiredCudaDlls = @(
                    (Join-Path $CudaDllDirectory "cublas64_12.dll"),
                    (Join-Path $CudaDllDirectory "cudnn64_9.dll"),
                    (Join-Path $CudaDllDirectory "cudart64_12.dll")
                )
                foreach ($dll in $RequiredCudaDlls) {
                    if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) { $CudaDllsHealthy = $false }
                }
                if ($CudaDllsHealthy) { $env:PATH = (($CudaDllDirectories -join ";") + ";" + $env:PATH) }
            }
            Push-Location $App
            try {
                $env:CLIPPY_DATA_DIR = $DataRoot
                $env:OUTPUT_DIR = Join-Path $DataRoot "output"
                $env:UPLOAD_DIR = Join-Path $DataRoot "uploads"
                $env:CLIPPY_SETTINGS_PATH = Join-Path $Root "settings.json"
                $env:CLIPPY_MODELS_DIR = Join-Path $DataRoot "models"
                $env:REFERENCE_TEMPLATES_DIR = Join-Path $DataRoot 'reference_templates'
                $PythonHealthScript = "import app, torch, faster_whisper"
                if ($TorchVariant -eq "cuda") {
                    $PythonHealthScript += "; import ctranslate2; assert torch.version.cuda and torch.version.cuda.startswith('12.8'); assert torch.cuda.is_available(); x=torch.ones((64,64),device='cuda'); y=x @ x; torch.cuda.synchronize(); assert float(y[0,0].item()) == 64.0; assert ctranslate2.get_cuda_device_count() > 0"
                } else {
                    $PythonHealthScript += "; assert torch.version.cuda is None"
                }
                $PythonHealthy = $PythonVersionHealthy -and $CudaDllsHealthy -and (Test-ClippyExecutable $PythonExe ('-c "' + $PythonHealthScript + '"') '' 120)
                $env:REMOTION_BROWSER_EXECUTABLE = $BrowserExecutable
                $BrowserCheck = "import('@remotion/renderer').then(async m => { await m.ensureBrowser({browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE}); }).catch(e => { console.error(e); process.exit(1); });"
                Push-Location (Join-Path $App "render-service")
                try {
                    $BrowserPackageHealthy = Test-ClippyExecutable $NodeExe ('-e "' + $BrowserCheck + '"')
                    $NodeHealthy = ($NodeVersionHealthy -and $BrowserPackageHealthy) -and (Test-ClippyExecutable $BrowserExecutable '--headless --disable-gpu --dump-dom about:blank')
                } finally {
                    Pop-Location
                }
            } finally {
                Pop-Location
            }
            if ($PythonHealthy -and $NodeHealthy -and $FfmpegHealthy) {
                Write-Stage "Managed runtimes and application dependencies are healthy. No downloads needed."
                Remove-ClippyScratchRoot
                exit 0
            }
            Write-Stage "A runtime health check failed; repairing dependencies."
        }
    } catch {
        Write-Stage "Previous runtime manifest is invalid; repairing managed runtimes."
    }
}

$script:ScratchRoot = New-ClippyScratch $ScratchCandidates -RuntimeRoot $Root
$ScratchDrive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($ScratchRoot))
$env:TEMP = $ScratchRoot
$env:TMP = $ScratchRoot
$env:PIP_CACHE_DIR = Join-Path $ScratchRoot 'pip-cache'
Write-Stage ("Using " + $ScratchRoot + " for temporary setup files; managed runtimes remain in " + $Root)
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
if ($AppVersion -notmatch "^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$") { throw "Application VERSION file is missing or invalid." }

$PythonRuntimeName = "clippy-python-$TorchVariant-$AppVersion.zip"
$PythonRuntimeArchive = Join-Path $Downloads $PythonRuntimeName
$PythonRuntimeManifestName = "clippy-python-$TorchVariant.manifest.json"
$PythonRuntimeManifestUrl = "https://github.com/helalxp/clippy/releases/download/v$AppVersion/$PythonRuntimeManifestName"
$PythonRuntimeReleaseBaseUrl = "https://github.com/helalxp/clippy/releases/download/v$AppVersion"
$LocalRuntimeArchive = $env:CLIPPY_PYTHON_RUNTIME_ARCHIVE
$LocalRuntimeChecksum = $env:CLIPPY_PYTHON_RUNTIME_CHECKSUM

# Local archive overrides remain available for developer diagnostics. Customer
# installs use only the manifest and assets from the exact matching release.
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
    $PythonRuntimeManifestPath = Join-Path $Downloads "$AppVersion-$PythonRuntimeManifestName"
    Download-File $PythonRuntimeManifestUrl $PythonRuntimeManifestPath
    $ManifestParsed = $false
    for ($ManifestAttempt = 1; $ManifestAttempt -le 2; $ManifestAttempt++) {
        try {
            $RuntimeManifest = Get-Content -LiteralPath $PythonRuntimeManifestPath -Raw | ConvertFrom-Json
            $ManifestParsed = $true
            break
        } catch {
            Remove-Item -LiteralPath $PythonRuntimeManifestPath -Force -ErrorAction SilentlyContinue
            if ($ManifestAttempt -eq 2) {
                throw "The runtime manifest downloaded from release v$AppVersion is not valid JSON: $PythonRuntimeManifestUrl"
            }
            Write-Stage "Cached runtime manifest was invalid; downloading it again."
            Download-File $PythonRuntimeManifestUrl $PythonRuntimeManifestPath
        }
    }
    if (-not $ManifestParsed) { throw "Could not read the runtime manifest for release v$AppVersion." }
    Assert-ClippyRuntimeArchiveManifest -Manifest $RuntimeManifest -ExpectedApplicationVersion $AppVersion -ExpectedVariant $TorchVariant | Out-Null

    foreach ($Part in @($RuntimeManifest.parts)) {
        $PartName = [string]$Part.name
        $PartUrl = "$PythonRuntimeReleaseBaseUrl/$PartName"
        $PartPath = Join-Path $Downloads $PartName
        $PartHealthy = $false
        if (Test-Path -LiteralPath $PartPath -PathType Leaf) {
            $PartInfo = Get-Item -LiteralPath $PartPath
            if ($PartInfo.Length -eq [long]$Part.size -and
                (Get-ClippyFileSha256 $PartPath) -eq ([string]$Part.sha256).ToLowerInvariant()) {
                $PartHealthy = $true
                Write-Stage "Reusing verified runtime part $PartName."
            } else {
                Write-Stage "Cached runtime part $PartName failed verification; downloading it again."
                Remove-Item -LiteralPath $PartPath -Force
            }
        }
        if (-not $PartHealthy) {
            Download-File $PartUrl $PartPath
            $PartInfo = Get-Item -LiteralPath $PartPath
            if ($PartInfo.Length -ne [long]$Part.size -or
                (Get-ClippyFileSha256 $PartPath) -ne ([string]$Part.sha256).ToLowerInvariant()) {
                Remove-Item -LiteralPath $PartPath -Force -ErrorAction SilentlyContinue
                throw "Downloaded runtime part failed size or SHA-256 verification: $PartName"
            }
        }
    }

    Write-Stage "Reconstructing the verified $TorchVariant Python runtime archive from $($RuntimeManifest.partCount) release asset(s)..."
    Join-ClippyRuntimeArchiveParts -Manifest $RuntimeManifest -PartsDirectory $Downloads -Destination $PythonRuntimeArchive | Out-Null
    $PythonRuntimeVerified = $true
}
if (-not $PythonRuntimeVerified) { throw "Could not verify the downloaded Python runtime." }

$PythonStage = Join-Path $Runtime "python.installing"
if (Test-Path $PythonStage) { Remove-Item $PythonStage -Recurse -Force }
Write-Stage "Extracting the verified $TorchVariant Python runtime..."
Expand-ArchiveFast $PythonRuntimeArchive $PythonStage
$StagedPython = Join-Path $PythonStage "python.exe"
if (-not (Test-Path -LiteralPath $StagedPython -PathType Leaf)) {
    throw "Verified Python runtime archive does not contain python.exe at its root."
}
$StagedVersion = (& $StagedPython --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Packaged Python executable failed its version check: $StagedVersion"
}
Assert-ClippyPythonRuntimeVersion -Actual $StagedVersion -Expected $PythonVersion
$StagedImportCheck = "import torch, torchvision, fastapi, uvicorn, faster_whisper; print('torch=' + torch.__version__); print('cuda_build=' + str(torch.version.cuda))"
& $StagedPython -c $StagedImportCheck
if ($LASTEXITCODE -ne 0) { throw "Packaged Python dependency verification failed." }
if ($TorchVariant -eq "cuda") {
    & $StagedPython -c "import torch; assert torch.version.cuda is not None, 'CUDA-enabled PyTorch is missing'"
    if ($LASTEXITCODE -ne 0) { throw "Selected CUDA runtime does not contain CUDA-enabled PyTorch." }
}

# Activate only after archive hash, Python version, and critical imports pass.
Install-ClippyComponent $PythonStage $PythonDir {
    param($dir)
    Test-ClippyExecutable (Join-Path $dir 'python.exe') '-c "import torch,fastapi,faster_whisper"' '' 120
}
$PythonExe = Join-Path $PythonDir 'python.exe'

# Node's archive is checked against the SHA-256 value published alongside the
# official Node.js release archive.
$NodeExe = Join-Path $NodeDir "node.exe"
$ExistingNodeHealthy = Test-ClippyExecutable $NodeExe '--version' "v$NodeVersion"
if (-not $ExistingNodeHealthy) {
    Write-Stage 'Managed Node.js runtime requires replacement.'
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
    $NodeStage = "$NodeDir.installing"
    if (Test-Path -LiteralPath $NodeStage) { Remove-Item -LiteralPath $NodeStage -Recurse -Force }
    Copy-Item -LiteralPath $ExtractedRoot -Destination $NodeStage -Recurse
    Install-ClippyComponent $NodeStage $NodeDir { param($dir) Test-ClippyExecutable (Join-Path $dir 'node.exe') '--version' "v$NodeVersion" }
    Remove-Item $Extract -Recurse -Force
}
$InstalledNodeVersion = (& $NodeExe --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $InstalledNodeVersion.TrimStart([char]"v") -ne $NodeVersion) {
    throw "Managed Node.js runtime version check failed. Expected $NodeVersion, found $InstalledNodeVersion."
}

# FFmpeg is downloaded from the Windows builds publisher and verified against
# the publisher's SHA-256 sidecar before extraction.
$FfmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"
$FfmpegCheck = { param($dir) (Test-ClippyExecutable (Join-Path $dir 'ffmpeg.exe') '-version') -and (Test-ClippyExecutable (Join-Path $dir 'ffprobe.exe') '-version') }
$ExistingFfmpegHealthy = & $FfmpegCheck $FfmpegDir
if (-not $ExistingFfmpegHealthy) {
    Write-Stage 'Managed FFmpeg runtime requires replacement.'
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
    $FfmpegStage = "$FfmpegDir.installing"
    if (Test-Path -LiteralPath $FfmpegStage) { Remove-Item -LiteralPath $FfmpegStage -Recurse -Force }
    Copy-Item -LiteralPath $SourceBin -Destination $FfmpegStage -Recurse
    Install-ClippyComponent $FfmpegStage $FfmpegDir $FfmpegCheck
    Remove-Item $Extract -Recurse -Force
}
& $FfmpegExe -version
if ($LASTEXITCODE -ne 0) { throw "Managed FFmpeg runtime failed its version check." }

if ($TorchVariant -eq "cuda") {
    # Windows PyTorch CUDA wheels place their CUDA DLLs in torch\lib.
    $CudaDllDirectory = Join-Path $PythonDir "Lib\site-packages\torch\lib"
    $CudaDllDirectories = @($CudaDllDirectory)
    $RequiredCudaDlls = @(
        (Join-Path $CudaDllDirectory "cublas64_12.dll"),
        (Join-Path $CudaDllDirectory "cudnn64_9.dll"),
        (Join-Path $CudaDllDirectory "cudart64_12.dll")
    )
    foreach ($dll in $RequiredCudaDlls) {
        if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) {
            throw "CUDA runtime is missing a required DLL for PyTorch/CTranslate2: $dll"
        }
    }
    $env:PATH = (($CudaDllDirectories -join ";") + ";" + $env:PATH)
}

Write-Stage "Verifying backend imports..."
Push-Location $App
try {
    $env:CLIPPY_DATA_DIR = $DataRoot
    $env:OUTPUT_DIR = Join-Path $DataRoot "output"
    $env:UPLOAD_DIR = Join-Path $DataRoot "uploads"
    $env:CLIPPY_SETTINGS_PATH = Join-Path $Root "settings.json"
    $env:CLIPPY_MODELS_DIR = Join-Path $DataRoot "models"
    $env:REFERENCE_TEMPLATES_DIR = Join-Path $DataRoot 'reference_templates'
    & $PythonExe -c "import app; import torch; import faster_whisper; import ctranslate2; print('Backend imports OK; torch CUDA:', torch.cuda.is_available())"
    if ($LASTEXITCODE -ne 0) { throw "Backend import verification failed. Check the Python dependency log." }
    if ($TorchVariant -eq "cuda") {
        Write-Stage "Running a real CUDA kernel and faster-whisper device capability check..."
        & $PythonExe -c "import torch, ctranslate2; assert torch.version.cuda and torch.version.cuda.startswith('12.8'), f'Expected CUDA 12.8, got {torch.version.cuda}'; assert torch.cuda.is_available(), 'PyTorch cannot initialize the NVIDIA device'; x=torch.ones((64,64),device='cuda'); y=x @ x; torch.cuda.synchronize(); assert float(y[0,0].item()) == 64.0, 'CUDA kernel produced an unexpected result'; count=ctranslate2.get_cuda_device_count(); assert count > 0, 'CTranslate2/faster-whisper cannot see a CUDA device'; print('CUDA kernel OK:', torch.cuda.get_device_name(0), '| CTranslate2 devices:', count)"
        if ($LASTEXITCODE -ne 0) {
            throw "CUDA runtime verification failed. Clippy will not mark an unusable CUDA installation as healthy. Check the NVIDIA driver, CUDA DLL paths, and GPU compatibility in the setup log."
        }
    }
} finally {
    Pop-Location
}

Write-Stage "Verifying the persistent Remotion browser runtime..."
$InstalledBrowserVersion = if (Test-Path -LiteralPath $BrowserVersionFile) { (Get-Content -LiteralPath $BrowserVersionFile -Raw).Trim() } else { "" }
$BrowserNeedsInstall = -not (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf) -or $InstalledBrowserVersion -ne $RemotionVersion
if (-not $BrowserNeedsInstall) {
    $BrowserNeedsInstall = ((Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Contract.browserSha256) -or -not (Test-ClippyExecutable $BrowserExecutable '--headless --disable-gpu --dump-dom about:blank')
}
if ($BrowserNeedsInstall) {
    Write-Stage "Installing or repairing the Remotion browser for renderer version $RemotionVersion..."
    # Google's headless shell is unsigned. Trust the publisher's versioned HTTPS
    # archive only after matching the immutable hashes shipped in the payload.
    $BrowserArchive = Join-Path $Downloads "chrome-headless-shell-$($Contract.browserVersion)-win64.zip"
    Download-File $BrowserArchiveUrl $BrowserArchive
    try { Assert-Sha256 $BrowserArchive $Contract.browserArchiveSha256 } catch {
        Remove-Item -LiteralPath $BrowserArchive -Force
        Download-File $BrowserArchiveUrl $BrowserArchive
        Assert-Sha256 $BrowserArchive $Contract.browserArchiveSha256
    }
    $BrowserExtract = Join-Path $ScratchRoot 'browser-extract'
    Expand-ArchiveFast $BrowserArchive $BrowserExtract
    $DownloadedBrowserDir = Join-Path $BrowserExtract 'chrome-headless-shell-win64'
    Assert-Sha256 (Join-Path $DownloadedBrowserDir 'chrome-headless-shell.exe') $Contract.browserSha256
    $BrowserStage = "$BrowserDir.installing"
    if (Test-Path -LiteralPath $BrowserStage) { Remove-Item -LiteralPath $BrowserStage -Recurse -Force }
    Copy-Item -LiteralPath $DownloadedBrowserDir -Destination $BrowserStage -Recurse
    Install-ClippyComponent $BrowserStage $BrowserDir {
        param($dir)
        $exe = Join-Path $dir 'chrome-headless-shell.exe'
        ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Contract.browserSha256) -and (Test-ClippyExecutable $exe '--headless --disable-gpu --dump-dom about:blank')
    }
    Remove-Item -LiteralPath $BrowserExtract -Recurse -Force
    [System.IO.File]::WriteAllText($BrowserVersionFile, $RemotionVersion, [System.Text.UTF8Encoding]::new($false))
} else {
    Write-Stage "Reusing the browser already installed for Remotion $RemotionVersion."
}

if (-not (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf)) {
    throw "Persistent Remotion browser executable is missing: $BrowserExecutable"
}
Assert-Sha256 $BrowserExecutable $Contract.browserSha256
$BrowserSha256 = (Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
$env:REMOTION_BROWSER_EXECUTABLE = $BrowserExecutable
$BrowserValidation = "import('@remotion/renderer').then(async m => { await m.ensureBrowser({browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE}); console.log('Persistent Remotion browser ready'); }).catch(e => { console.error(e); process.exit(1); });"
Push-Location (Join-Path $App "render-service")
try {
    & $NodeExe -e $BrowserValidation
    if ($LASTEXITCODE -ne 0) { throw "Persistent Remotion browser validation failed." }
} finally {
    Pop-Location
}


New-Item -ItemType Directory -Path (Split-Path $ManifestPath -Parent) -Force | Out-NULL
$Manifest = @{
    version = "1.0.0"
    components = @{
        python = @{ version = $PythonVersion; installed = $true }
        node = @{ version = $NodeVersion; installed = $true }
        ffmpeg = @{ version = $FfmpegVersion; installed = $true }
        browser = @{ version = $RemotionVersion; installed = $true }
    }
    schema = 1
    state = $ExpectedState
    installedAt = (Get-Date).ToUniversalTime().ToString("o")
    requirementsSha256 = $RequirementsHash
    browserSha256 = $BrowserSha256
    gpuMode = if ($TorchVariant -eq "cuda") { "cuda128" } else { "cpu" }
}
$ManifestJson = $Manifest | ConvertTo-Json -Depth 5
# Windows PowerShell 5.1 writes a UTF-8 BOM with Set-Content -Encoding UTF8.
# serde_json expects plain JSON, so write UTF-8 explicitly without a BOM.
[System.IO.File]::WriteAllText($ManifestPath, $ManifestJson, [System.Text.UTF8Encoding]::new($false))
# Remove the multi-gigabyte Python archive and release parts only after the
# complete runtime setup has succeeded. If setup fails earlier, verified parts
# remain available for a retry without downloading them again.
if ([string]::IsNullOrWhiteSpace($LocalRuntimeArchive) -and $RuntimeManifest) {
    Remove-Item -LiteralPath $PythonRuntimeArchive, $PythonRuntimeManifestPath -Force -ErrorAction SilentlyContinue
    foreach ($Part in @($RuntimeManifest.parts)) {
        Remove-Item -LiteralPath (Join-Path $Downloads ([string]$Part.name)) -Force -ErrorAction SilentlyContinue
    }
}
Remove-ClippyScratchRoot
Write-Stage "Runtime setup completed successfully."
} finally {
    $InstallMutex.ReleaseMutex(); $InstallMutex.Dispose()
    if ($DesktopMutex) { $DesktopMutex.ReleaseMutex(); $DesktopMutex.Dispose() }
}
 -or $Contract.ffmpeg -notmatch '^\d+\.\d+(?:\.\d+)?
$PythonVersion = $Contract.python
$NodeVersion = $Contract.node
$FfmpegVersion = $Contract.ffmpeg
$TorchVariant = 'cpu'
if ($Contract.browserVersion -notmatch '^\d+\.\d+\.\d+\.\d+$' -or $Contract.browserArchiveSha256 -notmatch '^[a-f0-9]{64}$' -or $Contract.browserSha256 -notmatch '^[a-f0-9]{64}$') { throw 'Browser integrity contract is invalid.' }
$BrowserArchiveUrl = "https://storage.googleapis.com/chrome-for-testing-public/$($Contract.browserVersion)/win64/chrome-headless-shell-win64.zip"

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
$DataRoot = Join-Path $Root "data"
$StorageLocationPath = Join-Path $Root "storage-location.json"
if (Test-Path -LiteralPath $StorageLocationPath -PathType Leaf) {
    try {
        $StorageLocation = Get-Content -LiteralPath $StorageLocationPath -Raw | ConvertFrom-Json
        $ConfiguredDataRoot = [string]$StorageLocation.data_directory
        if ($StorageLocation.schema_version -ne 1 -or [string]::IsNullOrWhiteSpace($ConfiguredDataRoot)) {
            throw "Storage location configuration is incomplete or unsupported."
        }
        $DataRoot = [IO.Path]::GetFullPath($ConfiguredDataRoot)
        if ($DataRoot -notmatch '^[A-Za-z]:\\|^\\\\') {
            throw "Configured Clippy data directory must be an absolute Windows path."
        }
        if (-not (Test-Path -LiteralPath $DataRoot -PathType Container)) {
            throw "Configured Clippy data directory is unavailable: $DataRoot"
        }
    } catch {
        throw "Cannot load Clippy's configured data directory: $($_.Exception.Message)"
    }
}
$PythonDir = Join-Path $Runtime "python"
$NodeDir = Join-Path $Runtime "node"
$FfmpegDir = Join-Path $Runtime "ffmpeg\bin"
$ManifestPath = Join-Path $Root "runtime-manifest.json"
# Browser binaries are durable user data, not part of app\current. Updating the
# application payload must not force a multi-hundred-MB browser download.
$BrowserRoot = Join-Path $Root "browser"
$BrowserDir = Join-Path $BrowserRoot "headless-shell"
$BrowserExecutable = Join-Path $BrowserDir "chrome-headless-shell.exe"
$BrowserVersionFile = Join-Path $BrowserRoot "remotion-version.txt"
$LogDir = Join-Path $Root "logs"
$SetupLogPath = Join-Path $LogDir "runtime-setup.log"
$script:ScratchRoot = $null
$NvidiaDriverVersion = $null
$NvidiaGpuName = $null
$NvidiaComputeCapability = $null
$ForceCpuRuntime = $env:CLIPPY_FORCE_CPU_RUNTIME -eq "1"
if (-not $ForceCpuRuntime) {
    $Nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
$NvidiaSmiPath = if ($Nvidia) { $Nvidia.Source } else { $null }
if (-not $NvidiaSmiPath) {
    $NvidiaCandidates = @(
        (Join-Path $env:ProgramFiles "NVIDIA Corporation\NVSMI\nvidia-smi.exe"),
        (Join-Path $env:SystemRoot "System32\nvidia-smi.exe")
    )
    $NvidiaSmiPath = $NvidiaCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if ($NvidiaSmiPath) {
    $NvidiaInfo = & $NvidiaSmiPath --query-gpu=name,driver_version,compute_cap --format=csv,noheader 2>$null
    if ($LASTEXITCODE -eq 0 -and $NvidiaInfo) {
        $NvidiaLine = @($NvidiaInfo) | Select-Object -First 1
        $NvidiaFields = ([string]$NvidiaLine).Split(',')
        if ($NvidiaFields.Count -ge 3) {
            $NvidiaGpuName = $NvidiaFields[0].Trim()
            $DriverText = $NvidiaFields[1].Trim()
            try { $NvidiaDriverVersion = [Version]$DriverText } catch { $NvidiaDriverVersion = $null }
            $ParsedComputeCapability = 0.0
            if ([double]::TryParse($NvidiaFields[2].Trim(), [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$ParsedComputeCapability)) {
                $NvidiaComputeCapability = $ParsedComputeCapability
            }
            # CUDA 12.8 GA requires Windows driver 570.65. The packaged
            # PyTorch CUDA runtime targets Volta/Turing-era and newer devices;
            # Blackwell is supported by cu128. Unsupported/unknown devices use
            # the CPU runtime instead of failing during the first CUDA kernel.
            if ($NvidiaDriverVersion -and $NvidiaDriverVersion -ge [Version]"570.65" -and
                $null -ne $NvidiaComputeCapability -and $NvidiaComputeCapability -ge 7.0) {
                $TorchVariant = "cuda"
            }
        }
    }
}
}
$PythonArchiveName = "python-$PythonVersion-embed-amd64.zip"
$PythonArchiveUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$PythonArchiveSha256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
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

function Remove-ClippyScratchRoot {
    $scratch = $script:ScratchRoot
    if (-not [string]::IsNullOrWhiteSpace($scratch) -and (Test-Path -LiteralPath $scratch -PathType Container)) {
        Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }
    $script:ScratchRoot = $null
}

trap {
    $Failure = $_
    try {
        Write-Stage ("SETUP FAILED: " + $Failure.Exception.Message)
        Write-Stage ("Failure location: " + $Failure.InvocationInfo.PositionMessage)
        Write-Stage ("Diagnostic log: " + $SetupLogPath)
    } catch { }
    try { Remove-ClippyScratchRoot } catch { }
    exit 1
}

Write-Stage "Runtime setup engine started."
Write-Stage ("Selected prebuilt Python runtime variant: " + $TorchVariant)
if ($ForceCpuRuntime) {
    Write-Stage "CPU runtime selection was explicitly forced by CLIPPY_FORCE_CPU_RUNTIME=1."
}

# Load script dependencies only after logging and the failure trap are active.
# This turns missing packaged helpers into a useful diagnostic instead of an
# early PowerShell dot-source failure with no Clippy setup context.
foreach ($Helper in @("runtime-manifest-state.ps1", "runtime-archive.ps1", "runtime-health.ps1")) {
    $HelperPath = Join-Path $PSScriptRoot $Helper
    if (-not (Test-Path -LiteralPath $HelperPath -PathType Leaf)) {
        throw "Application payload is incomplete. Missing required runtime helper: $HelperPath"
    }
}
. (Join-Path $PSScriptRoot "runtime-manifest-state.ps1")
. (Join-Path $PSScriptRoot "runtime-archive.ps1")
. (Join-Path $PSScriptRoot "runtime-health.ps1")
if ($NvidiaGpuName) {
    Write-Stage ("Detected NVIDIA GPU: " + $NvidiaGpuName + "; driver " + $NvidiaDriverVersion + "; compute capability " + $NvidiaComputeCapability)
    if ($TorchVariant -eq "cpu") {
        Write-Stage "NVIDIA driver or compute capability is not supported by the packaged CUDA 12.8 runtime; using the CPU runtime."
    }
}

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

            $ExpectedTotalBytes = $null
            if ($Status -eq 206) {
                $ContentRange = $Response.Headers["Content-Range"]
                if ($ContentRange -notmatch "^bytes\s+(\d+)-(\d+)/(\d+)$") {
                    throw "Server returned a missing or invalid Content-Range while resuming $Url"
                }
                $RangeStart = [long]$Matches[1]
                $RangeEnd = [long]$Matches[2]
                $ExpectedTotalBytes = [long]$Matches[3]
                if ($RangeStart -ne $Offset -or $RangeEnd -lt $RangeStart -or $ExpectedTotalBytes -le $RangeEnd) {
                    throw "Server returned an inconsistent Content-Range while resuming $Url"
                }
                $ExpectedResponseBytes = $RangeEnd - $RangeStart + 1
                if ($Response.ContentLength -ge 0 -and $Response.ContentLength -ne $ExpectedResponseBytes) {
                    throw "Server Content-Length does not match Content-Range while downloading $Url"
                }
            } elseif ($Response.ContentLength -ge 0) {
                $ExpectedTotalBytes = [long]$Response.ContentLength
            }

            $InputStream = $Response.GetResponseStream()
            $Mode = if ($Offset -gt 0 -and $Status -eq 206) { [IO.FileMode]::Append } else { [IO.FileMode]::Create }
            $OutputStream = [IO.File]::Open($Partial, $Mode, [IO.FileAccess]::Write, [IO.FileShare]::None)
            $Buffer = New-Object byte[] (1024 * 1024)
            $Downloaded = $Offset
            $LastReportedPercent = -1
            while (($Read = $InputStream.Read($Buffer, 0, $Buffer.Length)) -gt 0) {
                $OutputStream.Write($Buffer, 0, $Read)
                $Downloaded += $Read
                if ($ExpectedTotalBytes -gt 0) {
                    $Percent = [int][math]::Floor(($Downloaded * 100.0) / $ExpectedTotalBytes)
                    if ($Percent -ge $LastReportedPercent + 10) {
                        $LastReportedPercent = $Percent
                        Write-Stage ("{0}: {1}% ({2:N0}/{3:N0} bytes)." -f [IO.Path]::GetFileName($Destination), $Percent, $Downloaded, $ExpectedTotalBytes)
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
            if ($null -ne $ExpectedTotalBytes -and (Get-Item -LiteralPath $Partial).Length -ne $ExpectedTotalBytes) {
                throw "Download ended before the server-declared content length was received. Partial data has been preserved for resume."
            }
            Move-Item -LiteralPath $Partial -Destination $Destination -Force
            Write-Stage "Download complete: $([IO.Path]::GetFileName($Destination))."
            return
        } catch {
            $Message = $_.Exception.Message
            if ($OutputStream) { $OutputStream.Dispose(); $OutputStream = $null }
            if ($InputStream) { $InputStream.Dispose(); $InputStream = $null }
            if ($Response) { $Response.Close(); $Response = $null }

            # A missing release or asset is permanent until the publisher fixes
            # it. Do not waste time retrying an HTTP 404 three times.
            $ErrorResponse = $_.Exception.Response
            if ($ErrorResponse -is [System.Net.HttpWebResponse] -and [int]$ErrorResponse.StatusCode -eq 404) {
                $ErrorResponse.Close()
                throw "HTTP 404: required download asset was not found: $Url. Confirm that the matching Clippy release exists and contains this asset."
            }

            # A completed partial file can legitimately receive HTTP 416 when
            # the server is asked to resume exactly at EOF. Promote it and let
            # the caller's mandatory SHA-256 verification decide whether it is
            # usable. If it is longer than the server object, discard it and
            # retry from byte zero.
            $ErrorResponse = $_.Exception.Response
            if ($ErrorResponse -is [System.Net.HttpWebResponse]) {
                try {
                    if ([int]$ErrorResponse.StatusCode -eq 416) {
                        $RangeHeader = $ErrorResponse.Headers["Content-Range"]
                        if ($RangeHeader -match "^bytes\s+\*/(\d+)$") {
                            $ServerLength = [long]$Matches[1]
                            $PartialLength = if (Test-Path -LiteralPath $Partial) { (Get-Item -LiteralPath $Partial).Length } else { 0L }
                            if ($PartialLength -eq $ServerLength -and $ServerLength -gt 0) {
                                $ErrorResponse.Close()
                                Move-Item -LiteralPath $Partial -Destination $Destination -Force
                                Write-Stage "Resumed download was already complete; promoted the verified partial file."
                                return
                            }
                            if ($PartialLength -ne $ServerLength) {
                                Remove-Item -LiteralPath $Partial -Force -ErrorAction SilentlyContinue
                                Write-Stage "Discarded an inconsistent partial download after HTTP 416 and will restart from byte zero."
                            }
                        }
                    }
                } finally {
                    $ErrorResponse.Close()
                }
            }

            if ($Attempt -eq 3) { throw "Download failed after 3 attempts: $Url. $Message" }
            Write-Stage "Download interrupted; preserving valid partial data for resume. $Message"
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

# Prefer per-user temporary storage; inaccessible fixed volumes are skipped.
$ScratchCandidates = @([IO.Path]::GetTempPath()) + @([IO.DriveInfo]::GetDrives() |
    Where-Object { $_.IsReady -and $_.DriveType -eq [IO.DriveType]::Fixed } |
    Sort-Object AvailableFreeSpace -Descending | ForEach-Object { $_.RootDirectory.FullName })
foreach ($componentPath in @($PythonDir, $NodeDir, $FfmpegDir, $BrowserDir)) { Restore-ClippyComponent $componentPath }
foreach ($Required in @("app.py", "requirements.txt", "setup-runtime.ps1", "runtime-archive.ps1", "runtime-manifest-state.ps1", "VERSION", "bgutil-provider\server\build\generate_once.js")) {
    if (-not (Test-Path (Join-Path $App $Required))) {
        throw "Application payload is incomplete. Missing $Required in $App"
    }
}

$RequirementsHash = (Get-FileHash (Join-Path $App "requirements.txt") -Algorithm SHA256).Hash.ToLowerInvariant()
$RemotionPackagePath = Join-Path $App "render-service\node_modules\@remotion\renderer\package.json"
if (-not (Test-Path -LiteralPath $RemotionPackagePath -PathType Leaf)) {
    throw "Remotion renderer package is missing from the application payload: $RemotionPackagePath"
}
$RemotionVersion = (Get-Content -LiteralPath $RemotionPackagePath -Raw | ConvertFrom-Json).version
if ([string]::IsNullOrWhiteSpace($RemotionVersion)) { throw "Could not determine the bundled Remotion renderer version." }

# Build expected state from runtime contract
$ExpectedState = New-ClippyRuntimeState -PythonVersion $PythonVersion -PythonVariant $TorchVariant -NodeVersion $NodeVersion -FfmpegVersion $FfmpegVersion -BrowserVersion $RemotionVersion -RequirementsSha256 $RequirementsHash
if (Test-Path $ManifestPath) {
    try {
        $Existing = Get-Content $ManifestPath -Raw | ConvertFrom-Json
        $PythonExe = Join-Path $PythonDir "python.exe"
        $NodeExe = Join-Path $NodeDir "node.exe"
        $FfmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"
        $RuntimeFilesPresent =
            (Test-Path -LiteralPath $PythonExe -PathType Leaf) -and
            (Test-Path -LiteralPath $NodeExe -PathType Leaf) -and
            (Test-Path -LiteralPath $FfmpegExe -PathType Leaf) -and
            (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf) -and
            (Test-Path -LiteralPath $BrowserVersionFile -PathType Leaf) -and
            ((Get-Content -LiteralPath $BrowserVersionFile -Raw).Trim() -eq $RemotionVersion)
        $ManifestComponentsHealthy = $Existing.version -eq "1.0.0" -and $Existing.schema -eq 1
        foreach ($componentName in @("python", "node", "ffmpeg", "browser")) {
            $component = $Existing.components.$componentName
            if (-not $component -or -not $component.installed -or [string]::IsNullOrWhiteSpace([string]$component.version)) {
                $ManifestComponentsHealthy = $false
            }
        }
        $ManifestComponentsHealthy = $ManifestComponentsHealthy -and
            ($Existing.components.python.version -eq $PythonVersion) -and
            ($Existing.components.node.version -eq $NodeVersion) -and
            ($Existing.components.ffmpeg.version -eq $FfmpegVersion) -and
            ($Existing.components.browser.version -eq $RemotionVersion) -and
            ($Existing.requirementsSha256 -eq $RequirementsHash) -and
            ($Existing.browserSha256 -match "^[a-fA-F0-9]{64}$") -and
            ($Existing.browserSha256 -eq $Contract.browserSha256) -and
            ($Existing.browserSha256 -eq (Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant())
        if ($Existing.state -eq $ExpectedState -and $RuntimeFilesPresent -and $ManifestComponentsHealthy) {
            Write-Stage "Verifying installed Python, Node.js, FFmpeg, backend, and Remotion dependencies..."
            $PythonVersionHealthy = Test-ClippyExecutable $PythonExe '--version' "Python $PythonVersion"
            $NodeVersionHealthy = Test-ClippyExecutable $NodeExe '--version' "v$NodeVersion"
            $FfmpegHealthy = (Test-ClippyExecutable $FfmpegExe '-version') -and (Test-ClippyExecutable (Join-Path $FfmpegDir 'ffprobe.exe') '-version')
            $PythonHealthy = $false
            $NodeHealthy = $false
            $CudaDllDirectories = @()
            $CudaDllsHealthy = $true
            if ($TorchVariant -eq "cuda") {
                # Windows PyTorch CUDA wheels place their CUDA DLLs in torch\lib.
                $CudaDllDirectory = Join-Path $PythonDir "Lib\site-packages\torch\lib"
                $CudaDllDirectories = @($CudaDllDirectory)
                $RequiredCudaDlls = @(
                    (Join-Path $CudaDllDirectory "cublas64_12.dll"),
                    (Join-Path $CudaDllDirectory "cudnn64_9.dll"),
                    (Join-Path $CudaDllDirectory "cudart64_12.dll")
                )
                foreach ($dll in $RequiredCudaDlls) {
                    if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) { $CudaDllsHealthy = $false }
                }
                if ($CudaDllsHealthy) { $env:PATH = (($CudaDllDirectories -join ";") + ";" + $env:PATH) }
            }
            Push-Location $App
            try {
                $env:CLIPPY_DATA_DIR = $DataRoot
                $env:OUTPUT_DIR = Join-Path $DataRoot "output"
                $env:UPLOAD_DIR = Join-Path $DataRoot "uploads"
                $env:CLIPPY_SETTINGS_PATH = Join-Path $Root "settings.json"
                $env:CLIPPY_MODELS_DIR = Join-Path $DataRoot "models"
                $env:REFERENCE_TEMPLATES_DIR = Join-Path $DataRoot 'reference_templates'
                $PythonHealthScript = "import app, torch, faster_whisper"
                if ($TorchVariant -eq "cuda") {
                    $PythonHealthScript += "; import ctranslate2; assert torch.version.cuda and torch.version.cuda.startswith('12.8'); assert torch.cuda.is_available(); x=torch.ones((64,64),device='cuda'); y=x @ x; torch.cuda.synchronize(); assert float(y[0,0].item()) == 64.0; assert ctranslate2.get_cuda_device_count() > 0"
                } else {
                    $PythonHealthScript += "; assert torch.version.cuda is None"
                }
                $PythonHealthy = $PythonVersionHealthy -and $CudaDllsHealthy -and (Test-ClippyExecutable $PythonExe ('-c "' + $PythonHealthScript + '"') '' 120)
                $env:REMOTION_BROWSER_EXECUTABLE = $BrowserExecutable
                $BrowserCheck = "import('@remotion/renderer').then(async m => { await m.ensureBrowser({browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE}); }).catch(e => { console.error(e); process.exit(1); });"
                Push-Location (Join-Path $App "render-service")
                try {
                    $BrowserPackageHealthy = Test-ClippyExecutable $NodeExe ('-e "' + $BrowserCheck + '"')
                    $NodeHealthy = ($NodeVersionHealthy -and $BrowserPackageHealthy) -and (Test-ClippyExecutable $BrowserExecutable '--headless --disable-gpu --dump-dom about:blank')
                } finally {
                    Pop-Location
                }
            } finally {
                Pop-Location
            }
            if ($PythonHealthy -and $NodeHealthy -and $FfmpegHealthy) {
                Write-Stage "Managed runtimes and application dependencies are healthy. No downloads needed."
                Remove-ClippyScratchRoot
                exit 0
            }
            Write-Stage "A runtime health check failed; repairing dependencies."
        }
    } catch {
        Write-Stage "Previous runtime manifest is invalid; repairing managed runtimes."
    }
}

$script:ScratchRoot = New-ClippyScratch $ScratchCandidates -RuntimeRoot $Root
$ScratchDrive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($ScratchRoot))
$env:TEMP = $ScratchRoot
$env:TMP = $ScratchRoot
$env:PIP_CACHE_DIR = Join-Path $ScratchRoot 'pip-cache'
Write-Stage ("Using " + $ScratchRoot + " for temporary setup files; managed runtimes remain in " + $Root)
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
if ($AppVersion -notmatch "^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$") { throw "Application VERSION file is missing or invalid." }

$PythonRuntimeName = "clippy-python-$TorchVariant-$AppVersion.zip"
$PythonRuntimeArchive = Join-Path $Downloads $PythonRuntimeName
$PythonRuntimeManifestName = "clippy-python-$TorchVariant.manifest.json"
$PythonRuntimeManifestUrl = "https://github.com/helalxp/clippy/releases/download/v$AppVersion/$PythonRuntimeManifestName"
$PythonRuntimeReleaseBaseUrl = "https://github.com/helalxp/clippy/releases/download/v$AppVersion"
$LocalRuntimeArchive = $env:CLIPPY_PYTHON_RUNTIME_ARCHIVE
$LocalRuntimeChecksum = $env:CLIPPY_PYTHON_RUNTIME_CHECKSUM

# Local archive overrides remain available for developer diagnostics. Customer
# installs use only the manifest and assets from the exact matching release.
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
    $PythonRuntimeManifestPath = Join-Path $Downloads "$AppVersion-$PythonRuntimeManifestName"
    Download-File $PythonRuntimeManifestUrl $PythonRuntimeManifestPath
    $ManifestParsed = $false
    for ($ManifestAttempt = 1; $ManifestAttempt -le 2; $ManifestAttempt++) {
        try {
            $RuntimeManifest = Get-Content -LiteralPath $PythonRuntimeManifestPath -Raw | ConvertFrom-Json
            $ManifestParsed = $true
            break
        } catch {
            Remove-Item -LiteralPath $PythonRuntimeManifestPath -Force -ErrorAction SilentlyContinue
            if ($ManifestAttempt -eq 2) {
                throw "The runtime manifest downloaded from release v$AppVersion is not valid JSON: $PythonRuntimeManifestUrl"
            }
            Write-Stage "Cached runtime manifest was invalid; downloading it again."
            Download-File $PythonRuntimeManifestUrl $PythonRuntimeManifestPath
        }
    }
    if (-not $ManifestParsed) { throw "Could not read the runtime manifest for release v$AppVersion." }
    Assert-ClippyRuntimeArchiveManifest -Manifest $RuntimeManifest -ExpectedApplicationVersion $AppVersion -ExpectedVariant $TorchVariant | Out-Null

    foreach ($Part in @($RuntimeManifest.parts)) {
        $PartName = [string]$Part.name
        $PartUrl = "$PythonRuntimeReleaseBaseUrl/$PartName"
        $PartPath = Join-Path $Downloads $PartName
        $PartHealthy = $false
        if (Test-Path -LiteralPath $PartPath -PathType Leaf) {
            $PartInfo = Get-Item -LiteralPath $PartPath
            if ($PartInfo.Length -eq [long]$Part.size -and
                (Get-ClippyFileSha256 $PartPath) -eq ([string]$Part.sha256).ToLowerInvariant()) {
                $PartHealthy = $true
                Write-Stage "Reusing verified runtime part $PartName."
            } else {
                Write-Stage "Cached runtime part $PartName failed verification; downloading it again."
                Remove-Item -LiteralPath $PartPath -Force
            }
        }
        if (-not $PartHealthy) {
            Download-File $PartUrl $PartPath
            $PartInfo = Get-Item -LiteralPath $PartPath
            if ($PartInfo.Length -ne [long]$Part.size -or
                (Get-ClippyFileSha256 $PartPath) -ne ([string]$Part.sha256).ToLowerInvariant()) {
                Remove-Item -LiteralPath $PartPath -Force -ErrorAction SilentlyContinue
                throw "Downloaded runtime part failed size or SHA-256 verification: $PartName"
            }
        }
    }

    Write-Stage "Reconstructing the verified $TorchVariant Python runtime archive from $($RuntimeManifest.partCount) release asset(s)..."
    Join-ClippyRuntimeArchiveParts -Manifest $RuntimeManifest -PartsDirectory $Downloads -Destination $PythonRuntimeArchive | Out-Null
    $PythonRuntimeVerified = $true
}
if (-not $PythonRuntimeVerified) { throw "Could not verify the downloaded Python runtime." }

$PythonStage = Join-Path $Runtime "python.installing"
if (Test-Path $PythonStage) { Remove-Item $PythonStage -Recurse -Force }
Write-Stage "Extracting the verified $TorchVariant Python runtime..."
Expand-ArchiveFast $PythonRuntimeArchive $PythonStage
$StagedPython = Join-Path $PythonStage "python.exe"
if (-not (Test-Path -LiteralPath $StagedPython -PathType Leaf)) {
    throw "Verified Python runtime archive does not contain python.exe at its root."
}
$StagedVersion = (& $StagedPython --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Packaged Python executable failed its version check: $StagedVersion"
}
Assert-ClippyPythonRuntimeVersion -Actual $StagedVersion -Expected $PythonVersion
$StagedImportCheck = "import torch, torchvision, fastapi, uvicorn, faster_whisper; print('torch=' + torch.__version__); print('cuda_build=' + str(torch.version.cuda))"
& $StagedPython -c $StagedImportCheck
if ($LASTEXITCODE -ne 0) { throw "Packaged Python dependency verification failed." }
if ($TorchVariant -eq "cuda") {
    & $StagedPython -c "import torch; assert torch.version.cuda is not None, 'CUDA-enabled PyTorch is missing'"
    if ($LASTEXITCODE -ne 0) { throw "Selected CUDA runtime does not contain CUDA-enabled PyTorch." }
}

# Activate only after archive hash, Python version, and critical imports pass.
Install-ClippyComponent $PythonStage $PythonDir {
    param($dir)
    Test-ClippyExecutable (Join-Path $dir 'python.exe') '-c "import torch,fastapi,faster_whisper"' '' 120
}
$PythonExe = Join-Path $PythonDir 'python.exe'

# Node's archive is checked against the SHA-256 value published alongside the
# official Node.js release archive.
$NodeExe = Join-Path $NodeDir "node.exe"
$ExistingNodeHealthy = Test-ClippyExecutable $NodeExe '--version' "v$NodeVersion"
if (-not $ExistingNodeHealthy) {
    Write-Stage 'Managed Node.js runtime requires replacement.'
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
    $NodeStage = "$NodeDir.installing"
    if (Test-Path -LiteralPath $NodeStage) { Remove-Item -LiteralPath $NodeStage -Recurse -Force }
    Copy-Item -LiteralPath $ExtractedRoot -Destination $NodeStage -Recurse
    Install-ClippyComponent $NodeStage $NodeDir { param($dir) Test-ClippyExecutable (Join-Path $dir 'node.exe') '--version' "v$NodeVersion" }
    Remove-Item $Extract -Recurse -Force
}
$InstalledNodeVersion = (& $NodeExe --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $InstalledNodeVersion.TrimStart([char]"v") -ne $NodeVersion) {
    throw "Managed Node.js runtime version check failed. Expected $NodeVersion, found $InstalledNodeVersion."
}

# FFmpeg is downloaded from the Windows builds publisher and verified against
# the publisher's SHA-256 sidecar before extraction.
$FfmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"
$FfmpegCheck = { param($dir) (Test-ClippyExecutable (Join-Path $dir 'ffmpeg.exe') '-version') -and (Test-ClippyExecutable (Join-Path $dir 'ffprobe.exe') '-version') }
$ExistingFfmpegHealthy = & $FfmpegCheck $FfmpegDir
if (-not $ExistingFfmpegHealthy) {
    Write-Stage 'Managed FFmpeg runtime requires replacement.'
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
    $FfmpegStage = "$FfmpegDir.installing"
    if (Test-Path -LiteralPath $FfmpegStage) { Remove-Item -LiteralPath $FfmpegStage -Recurse -Force }
    Copy-Item -LiteralPath $SourceBin -Destination $FfmpegStage -Recurse
    Install-ClippyComponent $FfmpegStage $FfmpegDir $FfmpegCheck
    Remove-Item $Extract -Recurse -Force
}
& $FfmpegExe -version
if ($LASTEXITCODE -ne 0) { throw "Managed FFmpeg runtime failed its version check." }

if ($TorchVariant -eq "cuda") {
    # Windows PyTorch CUDA wheels place their CUDA DLLs in torch\lib.
    $CudaDllDirectory = Join-Path $PythonDir "Lib\site-packages\torch\lib"
    $CudaDllDirectories = @($CudaDllDirectory)
    $RequiredCudaDlls = @(
        (Join-Path $CudaDllDirectory "cublas64_12.dll"),
        (Join-Path $CudaDllDirectory "cudnn64_9.dll"),
        (Join-Path $CudaDllDirectory "cudart64_12.dll")
    )
    foreach ($dll in $RequiredCudaDlls) {
        if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) {
            throw "CUDA runtime is missing a required DLL for PyTorch/CTranslate2: $dll"
        }
    }
    $env:PATH = (($CudaDllDirectories -join ";") + ";" + $env:PATH)
}

Write-Stage "Verifying backend imports..."
Push-Location $App
try {
    $env:CLIPPY_DATA_DIR = $DataRoot
    $env:OUTPUT_DIR = Join-Path $DataRoot "output"
    $env:UPLOAD_DIR = Join-Path $DataRoot "uploads"
    $env:CLIPPY_SETTINGS_PATH = Join-Path $Root "settings.json"
    $env:CLIPPY_MODELS_DIR = Join-Path $DataRoot "models"
    $env:REFERENCE_TEMPLATES_DIR = Join-Path $DataRoot 'reference_templates'
    & $PythonExe -c "import app; import torch; import faster_whisper; import ctranslate2; print('Backend imports OK; torch CUDA:', torch.cuda.is_available())"
    if ($LASTEXITCODE -ne 0) { throw "Backend import verification failed. Check the Python dependency log." }
    if ($TorchVariant -eq "cuda") {
        Write-Stage "Running a real CUDA kernel and faster-whisper device capability check..."
        & $PythonExe -c "import torch, ctranslate2; assert torch.version.cuda and torch.version.cuda.startswith('12.8'), f'Expected CUDA 12.8, got {torch.version.cuda}'; assert torch.cuda.is_available(), 'PyTorch cannot initialize the NVIDIA device'; x=torch.ones((64,64),device='cuda'); y=x @ x; torch.cuda.synchronize(); assert float(y[0,0].item()) == 64.0, 'CUDA kernel produced an unexpected result'; count=ctranslate2.get_cuda_device_count(); assert count > 0, 'CTranslate2/faster-whisper cannot see a CUDA device'; print('CUDA kernel OK:', torch.cuda.get_device_name(0), '| CTranslate2 devices:', count)"
        if ($LASTEXITCODE -ne 0) {
            throw "CUDA runtime verification failed. Clippy will not mark an unusable CUDA installation as healthy. Check the NVIDIA driver, CUDA DLL paths, and GPU compatibility in the setup log."
        }
    }
} finally {
    Pop-Location
}

Write-Stage "Verifying the persistent Remotion browser runtime..."
$InstalledBrowserVersion = if (Test-Path -LiteralPath $BrowserVersionFile) { (Get-Content -LiteralPath $BrowserVersionFile -Raw).Trim() } else { "" }
$BrowserNeedsInstall = -not (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf) -or $InstalledBrowserVersion -ne $RemotionVersion
if (-not $BrowserNeedsInstall) {
    $BrowserNeedsInstall = ((Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Contract.browserSha256) -or -not (Test-ClippyExecutable $BrowserExecutable '--headless --disable-gpu --dump-dom about:blank')
}
if ($BrowserNeedsInstall) {
    Write-Stage "Installing or repairing the Remotion browser for renderer version $RemotionVersion..."
    # Google's headless shell is unsigned. Trust the publisher's versioned HTTPS
    # archive only after matching the immutable hashes shipped in the payload.
    $BrowserArchive = Join-Path $Downloads "chrome-headless-shell-$($Contract.browserVersion)-win64.zip"
    Download-File $BrowserArchiveUrl $BrowserArchive
    try { Assert-Sha256 $BrowserArchive $Contract.browserArchiveSha256 } catch {
        Remove-Item -LiteralPath $BrowserArchive -Force
        Download-File $BrowserArchiveUrl $BrowserArchive
        Assert-Sha256 $BrowserArchive $Contract.browserArchiveSha256
    }
    $BrowserExtract = Join-Path $ScratchRoot 'browser-extract'
    Expand-ArchiveFast $BrowserArchive $BrowserExtract
    $DownloadedBrowserDir = Join-Path $BrowserExtract 'chrome-headless-shell-win64'
    Assert-Sha256 (Join-Path $DownloadedBrowserDir 'chrome-headless-shell.exe') $Contract.browserSha256
    $BrowserStage = "$BrowserDir.installing"
    if (Test-Path -LiteralPath $BrowserStage) { Remove-Item -LiteralPath $BrowserStage -Recurse -Force }
    Copy-Item -LiteralPath $DownloadedBrowserDir -Destination $BrowserStage -Recurse
    Install-ClippyComponent $BrowserStage $BrowserDir {
        param($dir)
        $exe = Join-Path $dir 'chrome-headless-shell.exe'
        ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Contract.browserSha256) -and (Test-ClippyExecutable $exe '--headless --disable-gpu --dump-dom about:blank')
    }
    Remove-Item -LiteralPath $BrowserExtract -Recurse -Force
    [System.IO.File]::WriteAllText($BrowserVersionFile, $RemotionVersion, [System.Text.UTF8Encoding]::new($false))
} else {
    Write-Stage "Reusing the browser already installed for Remotion $RemotionVersion."
}

if (-not (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf)) {
    throw "Persistent Remotion browser executable is missing: $BrowserExecutable"
}
Assert-Sha256 $BrowserExecutable $Contract.browserSha256
$BrowserSha256 = (Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
$env:REMOTION_BROWSER_EXECUTABLE = $BrowserExecutable
$BrowserValidation = "import('@remotion/renderer').then(async m => { await m.ensureBrowser({browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE}); console.log('Persistent Remotion browser ready'); }).catch(e => { console.error(e); process.exit(1); });"
Push-Location (Join-Path $App "render-service")
try {
    & $NodeExe -e $BrowserValidation
    if ($LASTEXITCODE -ne 0) { throw "Persistent Remotion browser validation failed." }
} finally {
    Pop-Location
}


New-Item -ItemType Directory -Path (Split-Path $ManifestPath -Parent) -Force | Out-NULL
$Manifest = @{
    version = "1.0.0"
    components = @{
        python = @{ version = $PythonVersion; installed = $true }
        node = @{ version = $NodeVersion; installed = $true }
        ffmpeg = @{ version = $FfmpegVersion; installed = $true }
        browser = @{ version = $RemotionVersion; installed = $true }
    }
    schema = 1
    state = $ExpectedState
    installedAt = (Get-Date).ToUniversalTime().ToString("o")
    requirementsSha256 = $RequirementsHash
    browserSha256 = $BrowserSha256
    gpuMode = if ($TorchVariant -eq "cuda") { "cuda128" } else { "cpu" }
}
$ManifestJson = $Manifest | ConvertTo-Json -Depth 5
# Windows PowerShell 5.1 writes a UTF-8 BOM with Set-Content -Encoding UTF8.
# serde_json expects plain JSON, so write UTF-8 explicitly without a BOM.
[System.IO.File]::WriteAllText($ManifestPath, $ManifestJson, [System.Text.UTF8Encoding]::new($false))
# Remove the multi-gigabyte Python archive and release parts only after the
# complete runtime setup has succeeded. If setup fails earlier, verified parts
# remain available for a retry without downloading them again.
if ([string]::IsNullOrWhiteSpace($LocalRuntimeArchive) -and $RuntimeManifest) {
    Remove-Item -LiteralPath $PythonRuntimeArchive, $PythonRuntimeManifestPath -Force -ErrorAction SilentlyContinue
    foreach ($Part in @($RuntimeManifest.parts)) {
        Remove-Item -LiteralPath (Join-Path $Downloads ([string]$Part.name)) -Force -ErrorAction SilentlyContinue
    }
}
Remove-ClippyScratchRoot
Write-Stage "Runtime setup completed successfully."
} finally {
    $InstallMutex.ReleaseMutex(); $InstallMutex.Dispose()
    if ($DesktopMutex) { $DesktopMutex.ReleaseMutex(); $DesktopMutex.Dispose() }
}
 -or $Contract.ffmpegArchiveName -notmatch '^ffmpeg-[0-9.]+-essentials_build\.zip
$PythonVersion = $Contract.python
$NodeVersion = $Contract.node
$FfmpegVersion = $Contract.ffmpeg
$TorchVariant = 'cpu'
if ($Contract.browserVersion -notmatch '^\d+\.\d+\.\d+\.\d+$' -or $Contract.browserArchiveSha256 -notmatch '^[a-f0-9]{64}$' -or $Contract.browserSha256 -notmatch '^[a-f0-9]{64}$') { throw 'Browser integrity contract is invalid.' }
$BrowserArchiveUrl = "https://storage.googleapis.com/chrome-for-testing-public/$($Contract.browserVersion)/win64/chrome-headless-shell-win64.zip"

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
$DataRoot = Join-Path $Root "data"
$StorageLocationPath = Join-Path $Root "storage-location.json"
if (Test-Path -LiteralPath $StorageLocationPath -PathType Leaf) {
    try {
        $StorageLocation = Get-Content -LiteralPath $StorageLocationPath -Raw | ConvertFrom-Json
        $ConfiguredDataRoot = [string]$StorageLocation.data_directory
        if ($StorageLocation.schema_version -ne 1 -or [string]::IsNullOrWhiteSpace($ConfiguredDataRoot)) {
            throw "Storage location configuration is incomplete or unsupported."
        }
        $DataRoot = [IO.Path]::GetFullPath($ConfiguredDataRoot)
        if ($DataRoot -notmatch '^[A-Za-z]:\\|^\\\\') {
            throw "Configured Clippy data directory must be an absolute Windows path."
        }
        if (-not (Test-Path -LiteralPath $DataRoot -PathType Container)) {
            throw "Configured Clippy data directory is unavailable: $DataRoot"
        }
    } catch {
        throw "Cannot load Clippy's configured data directory: $($_.Exception.Message)"
    }
}
$PythonDir = Join-Path $Runtime "python"
$NodeDir = Join-Path $Runtime "node"
$FfmpegDir = Join-Path $Runtime "ffmpeg\bin"
$ManifestPath = Join-Path $Root "runtime-manifest.json"
# Browser binaries are durable user data, not part of app\current. Updating the
# application payload must not force a multi-hundred-MB browser download.
$BrowserRoot = Join-Path $Root "browser"
$BrowserDir = Join-Path $BrowserRoot "headless-shell"
$BrowserExecutable = Join-Path $BrowserDir "chrome-headless-shell.exe"
$BrowserVersionFile = Join-Path $BrowserRoot "remotion-version.txt"
$LogDir = Join-Path $Root "logs"
$SetupLogPath = Join-Path $LogDir "runtime-setup.log"
$script:ScratchRoot = $null
$NvidiaDriverVersion = $null
$NvidiaGpuName = $null
$NvidiaComputeCapability = $null
$ForceCpuRuntime = $env:CLIPPY_FORCE_CPU_RUNTIME -eq "1"
if (-not $ForceCpuRuntime) {
    $Nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
$NvidiaSmiPath = if ($Nvidia) { $Nvidia.Source } else { $null }
if (-not $NvidiaSmiPath) {
    $NvidiaCandidates = @(
        (Join-Path $env:ProgramFiles "NVIDIA Corporation\NVSMI\nvidia-smi.exe"),
        (Join-Path $env:SystemRoot "System32\nvidia-smi.exe")
    )
    $NvidiaSmiPath = $NvidiaCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if ($NvidiaSmiPath) {
    $NvidiaInfo = & $NvidiaSmiPath --query-gpu=name,driver_version,compute_cap --format=csv,noheader 2>$null
    if ($LASTEXITCODE -eq 0 -and $NvidiaInfo) {
        $NvidiaLine = @($NvidiaInfo) | Select-Object -First 1
        $NvidiaFields = ([string]$NvidiaLine).Split(',')
        if ($NvidiaFields.Count -ge 3) {
            $NvidiaGpuName = $NvidiaFields[0].Trim()
            $DriverText = $NvidiaFields[1].Trim()
            try { $NvidiaDriverVersion = [Version]$DriverText } catch { $NvidiaDriverVersion = $null }
            $ParsedComputeCapability = 0.0
            if ([double]::TryParse($NvidiaFields[2].Trim(), [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$ParsedComputeCapability)) {
                $NvidiaComputeCapability = $ParsedComputeCapability
            }
            # CUDA 12.8 GA requires Windows driver 570.65. The packaged
            # PyTorch CUDA runtime targets Volta/Turing-era and newer devices;
            # Blackwell is supported by cu128. Unsupported/unknown devices use
            # the CPU runtime instead of failing during the first CUDA kernel.
            if ($NvidiaDriverVersion -and $NvidiaDriverVersion -ge [Version]"570.65" -and
                $null -ne $NvidiaComputeCapability -and $NvidiaComputeCapability -ge 7.0) {
                $TorchVariant = "cuda"
            }
        }
    }
}
}
$PythonArchiveName = "python-$PythonVersion-embed-amd64.zip"
$PythonArchiveUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$PythonArchiveSha256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
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

function Remove-ClippyScratchRoot {
    $scratch = $script:ScratchRoot
    if (-not [string]::IsNullOrWhiteSpace($scratch) -and (Test-Path -LiteralPath $scratch -PathType Container)) {
        Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }
    $script:ScratchRoot = $null
}

trap {
    $Failure = $_
    try {
        Write-Stage ("SETUP FAILED: " + $Failure.Exception.Message)
        Write-Stage ("Failure location: " + $Failure.InvocationInfo.PositionMessage)
        Write-Stage ("Diagnostic log: " + $SetupLogPath)
    } catch { }
    try { Remove-ClippyScratchRoot } catch { }
    exit 1
}

Write-Stage "Runtime setup engine started."
Write-Stage ("Selected prebuilt Python runtime variant: " + $TorchVariant)
if ($ForceCpuRuntime) {
    Write-Stage "CPU runtime selection was explicitly forced by CLIPPY_FORCE_CPU_RUNTIME=1."
}

# Load script dependencies only after logging and the failure trap are active.
# This turns missing packaged helpers into a useful diagnostic instead of an
# early PowerShell dot-source failure with no Clippy setup context.
foreach ($Helper in @("runtime-manifest-state.ps1", "runtime-archive.ps1", "runtime-health.ps1")) {
    $HelperPath = Join-Path $PSScriptRoot $Helper
    if (-not (Test-Path -LiteralPath $HelperPath -PathType Leaf)) {
        throw "Application payload is incomplete. Missing required runtime helper: $HelperPath"
    }
}
. (Join-Path $PSScriptRoot "runtime-manifest-state.ps1")
. (Join-Path $PSScriptRoot "runtime-archive.ps1")
. (Join-Path $PSScriptRoot "runtime-health.ps1")
if ($NvidiaGpuName) {
    Write-Stage ("Detected NVIDIA GPU: " + $NvidiaGpuName + "; driver " + $NvidiaDriverVersion + "; compute capability " + $NvidiaComputeCapability)
    if ($TorchVariant -eq "cpu") {
        Write-Stage "NVIDIA driver or compute capability is not supported by the packaged CUDA 12.8 runtime; using the CPU runtime."
    }
}

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

            $ExpectedTotalBytes = $null
            if ($Status -eq 206) {
                $ContentRange = $Response.Headers["Content-Range"]
                if ($ContentRange -notmatch "^bytes\s+(\d+)-(\d+)/(\d+)$") {
                    throw "Server returned a missing or invalid Content-Range while resuming $Url"
                }
                $RangeStart = [long]$Matches[1]
                $RangeEnd = [long]$Matches[2]
                $ExpectedTotalBytes = [long]$Matches[3]
                if ($RangeStart -ne $Offset -or $RangeEnd -lt $RangeStart -or $ExpectedTotalBytes -le $RangeEnd) {
                    throw "Server returned an inconsistent Content-Range while resuming $Url"
                }
                $ExpectedResponseBytes = $RangeEnd - $RangeStart + 1
                if ($Response.ContentLength -ge 0 -and $Response.ContentLength -ne $ExpectedResponseBytes) {
                    throw "Server Content-Length does not match Content-Range while downloading $Url"
                }
            } elseif ($Response.ContentLength -ge 0) {
                $ExpectedTotalBytes = [long]$Response.ContentLength
            }

            $InputStream = $Response.GetResponseStream()
            $Mode = if ($Offset -gt 0 -and $Status -eq 206) { [IO.FileMode]::Append } else { [IO.FileMode]::Create }
            $OutputStream = [IO.File]::Open($Partial, $Mode, [IO.FileAccess]::Write, [IO.FileShare]::None)
            $Buffer = New-Object byte[] (1024 * 1024)
            $Downloaded = $Offset
            $LastReportedPercent = -1
            while (($Read = $InputStream.Read($Buffer, 0, $Buffer.Length)) -gt 0) {
                $OutputStream.Write($Buffer, 0, $Read)
                $Downloaded += $Read
                if ($ExpectedTotalBytes -gt 0) {
                    $Percent = [int][math]::Floor(($Downloaded * 100.0) / $ExpectedTotalBytes)
                    if ($Percent -ge $LastReportedPercent + 10) {
                        $LastReportedPercent = $Percent
                        Write-Stage ("{0}: {1}% ({2:N0}/{3:N0} bytes)." -f [IO.Path]::GetFileName($Destination), $Percent, $Downloaded, $ExpectedTotalBytes)
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
            if ($null -ne $ExpectedTotalBytes -and (Get-Item -LiteralPath $Partial).Length -ne $ExpectedTotalBytes) {
                throw "Download ended before the server-declared content length was received. Partial data has been preserved for resume."
            }
            Move-Item -LiteralPath $Partial -Destination $Destination -Force
            Write-Stage "Download complete: $([IO.Path]::GetFileName($Destination))."
            return
        } catch {
            $Message = $_.Exception.Message
            if ($OutputStream) { $OutputStream.Dispose(); $OutputStream = $null }
            if ($InputStream) { $InputStream.Dispose(); $InputStream = $null }
            if ($Response) { $Response.Close(); $Response = $null }

            # A missing release or asset is permanent until the publisher fixes
            # it. Do not waste time retrying an HTTP 404 three times.
            $ErrorResponse = $_.Exception.Response
            if ($ErrorResponse -is [System.Net.HttpWebResponse] -and [int]$ErrorResponse.StatusCode -eq 404) {
                $ErrorResponse.Close()
                throw "HTTP 404: required download asset was not found: $Url. Confirm that the matching Clippy release exists and contains this asset."
            }

            # A completed partial file can legitimately receive HTTP 416 when
            # the server is asked to resume exactly at EOF. Promote it and let
            # the caller's mandatory SHA-256 verification decide whether it is
            # usable. If it is longer than the server object, discard it and
            # retry from byte zero.
            $ErrorResponse = $_.Exception.Response
            if ($ErrorResponse -is [System.Net.HttpWebResponse]) {
                try {
                    if ([int]$ErrorResponse.StatusCode -eq 416) {
                        $RangeHeader = $ErrorResponse.Headers["Content-Range"]
                        if ($RangeHeader -match "^bytes\s+\*/(\d+)$") {
                            $ServerLength = [long]$Matches[1]
                            $PartialLength = if (Test-Path -LiteralPath $Partial) { (Get-Item -LiteralPath $Partial).Length } else { 0L }
                            if ($PartialLength -eq $ServerLength -and $ServerLength -gt 0) {
                                $ErrorResponse.Close()
                                Move-Item -LiteralPath $Partial -Destination $Destination -Force
                                Write-Stage "Resumed download was already complete; promoted the verified partial file."
                                return
                            }
                            if ($PartialLength -ne $ServerLength) {
                                Remove-Item -LiteralPath $Partial -Force -ErrorAction SilentlyContinue
                                Write-Stage "Discarded an inconsistent partial download after HTTP 416 and will restart from byte zero."
                            }
                        }
                    }
                } finally {
                    $ErrorResponse.Close()
                }
            }

            if ($Attempt -eq 3) { throw "Download failed after 3 attempts: $Url. $Message" }
            Write-Stage "Download interrupted; preserving valid partial data for resume. $Message"
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

# Prefer per-user temporary storage; inaccessible fixed volumes are skipped.
$ScratchCandidates = @([IO.Path]::GetTempPath()) + @([IO.DriveInfo]::GetDrives() |
    Where-Object { $_.IsReady -and $_.DriveType -eq [IO.DriveType]::Fixed } |
    Sort-Object AvailableFreeSpace -Descending | ForEach-Object { $_.RootDirectory.FullName })
foreach ($componentPath in @($PythonDir, $NodeDir, $FfmpegDir, $BrowserDir)) { Restore-ClippyComponent $componentPath }
foreach ($Required in @("app.py", "requirements.txt", "setup-runtime.ps1", "runtime-archive.ps1", "runtime-manifest-state.ps1", "VERSION", "bgutil-provider\server\build\generate_once.js")) {
    if (-not (Test-Path (Join-Path $App $Required))) {
        throw "Application payload is incomplete. Missing $Required in $App"
    }
}

$RequirementsHash = (Get-FileHash (Join-Path $App "requirements.txt") -Algorithm SHA256).Hash.ToLowerInvariant()
$RemotionPackagePath = Join-Path $App "render-service\node_modules\@remotion\renderer\package.json"
if (-not (Test-Path -LiteralPath $RemotionPackagePath -PathType Leaf)) {
    throw "Remotion renderer package is missing from the application payload: $RemotionPackagePath"
}
$RemotionVersion = (Get-Content -LiteralPath $RemotionPackagePath -Raw | ConvertFrom-Json).version
if ([string]::IsNullOrWhiteSpace($RemotionVersion)) { throw "Could not determine the bundled Remotion renderer version." }

# Build expected state from runtime contract
$ExpectedState = New-ClippyRuntimeState -PythonVersion $PythonVersion -PythonVariant $TorchVariant -NodeVersion $NodeVersion -FfmpegVersion $FfmpegVersion -BrowserVersion $RemotionVersion -RequirementsSha256 $RequirementsHash
if (Test-Path $ManifestPath) {
    try {
        $Existing = Get-Content $ManifestPath -Raw | ConvertFrom-Json
        $PythonExe = Join-Path $PythonDir "python.exe"
        $NodeExe = Join-Path $NodeDir "node.exe"
        $FfmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"
        $RuntimeFilesPresent =
            (Test-Path -LiteralPath $PythonExe -PathType Leaf) -and
            (Test-Path -LiteralPath $NodeExe -PathType Leaf) -and
            (Test-Path -LiteralPath $FfmpegExe -PathType Leaf) -and
            (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf) -and
            (Test-Path -LiteralPath $BrowserVersionFile -PathType Leaf) -and
            ((Get-Content -LiteralPath $BrowserVersionFile -Raw).Trim() -eq $RemotionVersion)
        $ManifestComponentsHealthy = $Existing.version -eq "1.0.0" -and $Existing.schema -eq 1
        foreach ($componentName in @("python", "node", "ffmpeg", "browser")) {
            $component = $Existing.components.$componentName
            if (-not $component -or -not $component.installed -or [string]::IsNullOrWhiteSpace([string]$component.version)) {
                $ManifestComponentsHealthy = $false
            }
        }
        $ManifestComponentsHealthy = $ManifestComponentsHealthy -and
            ($Existing.components.python.version -eq $PythonVersion) -and
            ($Existing.components.node.version -eq $NodeVersion) -and
            ($Existing.components.ffmpeg.version -eq $FfmpegVersion) -and
            ($Existing.components.browser.version -eq $RemotionVersion) -and
            ($Existing.requirementsSha256 -eq $RequirementsHash) -and
            ($Existing.browserSha256 -match "^[a-fA-F0-9]{64}$") -and
            ($Existing.browserSha256 -eq $Contract.browserSha256) -and
            ($Existing.browserSha256 -eq (Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant())
        if ($Existing.state -eq $ExpectedState -and $RuntimeFilesPresent -and $ManifestComponentsHealthy) {
            Write-Stage "Verifying installed Python, Node.js, FFmpeg, backend, and Remotion dependencies..."
            $PythonVersionHealthy = Test-ClippyExecutable $PythonExe '--version' "Python $PythonVersion"
            $NodeVersionHealthy = Test-ClippyExecutable $NodeExe '--version' "v$NodeVersion"
            $FfmpegHealthy = (Test-ClippyExecutable $FfmpegExe '-version') -and (Test-ClippyExecutable (Join-Path $FfmpegDir 'ffprobe.exe') '-version')
            $PythonHealthy = $false
            $NodeHealthy = $false
            $CudaDllDirectories = @()
            $CudaDllsHealthy = $true
            if ($TorchVariant -eq "cuda") {
                # Windows PyTorch CUDA wheels place their CUDA DLLs in torch\lib.
                $CudaDllDirectory = Join-Path $PythonDir "Lib\site-packages\torch\lib"
                $CudaDllDirectories = @($CudaDllDirectory)
                $RequiredCudaDlls = @(
                    (Join-Path $CudaDllDirectory "cublas64_12.dll"),
                    (Join-Path $CudaDllDirectory "cudnn64_9.dll"),
                    (Join-Path $CudaDllDirectory "cudart64_12.dll")
                )
                foreach ($dll in $RequiredCudaDlls) {
                    if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) { $CudaDllsHealthy = $false }
                }
                if ($CudaDllsHealthy) { $env:PATH = (($CudaDllDirectories -join ";") + ";" + $env:PATH) }
            }
            Push-Location $App
            try {
                $env:CLIPPY_DATA_DIR = $DataRoot
                $env:OUTPUT_DIR = Join-Path $DataRoot "output"
                $env:UPLOAD_DIR = Join-Path $DataRoot "uploads"
                $env:CLIPPY_SETTINGS_PATH = Join-Path $Root "settings.json"
                $env:CLIPPY_MODELS_DIR = Join-Path $DataRoot "models"
                $env:REFERENCE_TEMPLATES_DIR = Join-Path $DataRoot 'reference_templates'
                $PythonHealthScript = "import app, torch, faster_whisper"
                if ($TorchVariant -eq "cuda") {
                    $PythonHealthScript += "; import ctranslate2; assert torch.version.cuda and torch.version.cuda.startswith('12.8'); assert torch.cuda.is_available(); x=torch.ones((64,64),device='cuda'); y=x @ x; torch.cuda.synchronize(); assert float(y[0,0].item()) == 64.0; assert ctranslate2.get_cuda_device_count() > 0"
                } else {
                    $PythonHealthScript += "; assert torch.version.cuda is None"
                }
                $PythonHealthy = $PythonVersionHealthy -and $CudaDllsHealthy -and (Test-ClippyExecutable $PythonExe ('-c "' + $PythonHealthScript + '"') '' 120)
                $env:REMOTION_BROWSER_EXECUTABLE = $BrowserExecutable
                $BrowserCheck = "import('@remotion/renderer').then(async m => { await m.ensureBrowser({browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE}); }).catch(e => { console.error(e); process.exit(1); });"
                Push-Location (Join-Path $App "render-service")
                try {
                    $BrowserPackageHealthy = Test-ClippyExecutable $NodeExe ('-e "' + $BrowserCheck + '"')
                    $NodeHealthy = ($NodeVersionHealthy -and $BrowserPackageHealthy) -and (Test-ClippyExecutable $BrowserExecutable '--headless --disable-gpu --dump-dom about:blank')
                } finally {
                    Pop-Location
                }
            } finally {
                Pop-Location
            }
            if ($PythonHealthy -and $NodeHealthy -and $FfmpegHealthy) {
                Write-Stage "Managed runtimes and application dependencies are healthy. No downloads needed."
                Remove-ClippyScratchRoot
                exit 0
            }
            Write-Stage "A runtime health check failed; repairing dependencies."
        }
    } catch {
        Write-Stage "Previous runtime manifest is invalid; repairing managed runtimes."
    }
}

$script:ScratchRoot = New-ClippyScratch $ScratchCandidates -RuntimeRoot $Root
$ScratchDrive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($ScratchRoot))
$env:TEMP = $ScratchRoot
$env:TMP = $ScratchRoot
$env:PIP_CACHE_DIR = Join-Path $ScratchRoot 'pip-cache'
Write-Stage ("Using " + $ScratchRoot + " for temporary setup files; managed runtimes remain in " + $Root)
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
if ($AppVersion -notmatch "^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$") { throw "Application VERSION file is missing or invalid." }

$PythonRuntimeName = "clippy-python-$TorchVariant-$AppVersion.zip"
$PythonRuntimeArchive = Join-Path $Downloads $PythonRuntimeName
$PythonRuntimeManifestName = "clippy-python-$TorchVariant.manifest.json"
$PythonRuntimeManifestUrl = "https://github.com/helalxp/clippy/releases/download/v$AppVersion/$PythonRuntimeManifestName"
$PythonRuntimeReleaseBaseUrl = "https://github.com/helalxp/clippy/releases/download/v$AppVersion"
$LocalRuntimeArchive = $env:CLIPPY_PYTHON_RUNTIME_ARCHIVE
$LocalRuntimeChecksum = $env:CLIPPY_PYTHON_RUNTIME_CHECKSUM

# Local archive overrides remain available for developer diagnostics. Customer
# installs use only the manifest and assets from the exact matching release.
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
    $PythonRuntimeManifestPath = Join-Path $Downloads "$AppVersion-$PythonRuntimeManifestName"
    Download-File $PythonRuntimeManifestUrl $PythonRuntimeManifestPath
    $ManifestParsed = $false
    for ($ManifestAttempt = 1; $ManifestAttempt -le 2; $ManifestAttempt++) {
        try {
            $RuntimeManifest = Get-Content -LiteralPath $PythonRuntimeManifestPath -Raw | ConvertFrom-Json
            $ManifestParsed = $true
            break
        } catch {
            Remove-Item -LiteralPath $PythonRuntimeManifestPath -Force -ErrorAction SilentlyContinue
            if ($ManifestAttempt -eq 2) {
                throw "The runtime manifest downloaded from release v$AppVersion is not valid JSON: $PythonRuntimeManifestUrl"
            }
            Write-Stage "Cached runtime manifest was invalid; downloading it again."
            Download-File $PythonRuntimeManifestUrl $PythonRuntimeManifestPath
        }
    }
    if (-not $ManifestParsed) { throw "Could not read the runtime manifest for release v$AppVersion." }
    Assert-ClippyRuntimeArchiveManifest -Manifest $RuntimeManifest -ExpectedApplicationVersion $AppVersion -ExpectedVariant $TorchVariant | Out-Null

    foreach ($Part in @($RuntimeManifest.parts)) {
        $PartName = [string]$Part.name
        $PartUrl = "$PythonRuntimeReleaseBaseUrl/$PartName"
        $PartPath = Join-Path $Downloads $PartName
        $PartHealthy = $false
        if (Test-Path -LiteralPath $PartPath -PathType Leaf) {
            $PartInfo = Get-Item -LiteralPath $PartPath
            if ($PartInfo.Length -eq [long]$Part.size -and
                (Get-ClippyFileSha256 $PartPath) -eq ([string]$Part.sha256).ToLowerInvariant()) {
                $PartHealthy = $true
                Write-Stage "Reusing verified runtime part $PartName."
            } else {
                Write-Stage "Cached runtime part $PartName failed verification; downloading it again."
                Remove-Item -LiteralPath $PartPath -Force
            }
        }
        if (-not $PartHealthy) {
            Download-File $PartUrl $PartPath
            $PartInfo = Get-Item -LiteralPath $PartPath
            if ($PartInfo.Length -ne [long]$Part.size -or
                (Get-ClippyFileSha256 $PartPath) -ne ([string]$Part.sha256).ToLowerInvariant()) {
                Remove-Item -LiteralPath $PartPath -Force -ErrorAction SilentlyContinue
                throw "Downloaded runtime part failed size or SHA-256 verification: $PartName"
            }
        }
    }

    Write-Stage "Reconstructing the verified $TorchVariant Python runtime archive from $($RuntimeManifest.partCount) release asset(s)..."
    Join-ClippyRuntimeArchiveParts -Manifest $RuntimeManifest -PartsDirectory $Downloads -Destination $PythonRuntimeArchive | Out-Null
    $PythonRuntimeVerified = $true
}
if (-not $PythonRuntimeVerified) { throw "Could not verify the downloaded Python runtime." }

$PythonStage = Join-Path $Runtime "python.installing"
if (Test-Path $PythonStage) { Remove-Item $PythonStage -Recurse -Force }
Write-Stage "Extracting the verified $TorchVariant Python runtime..."
Expand-ArchiveFast $PythonRuntimeArchive $PythonStage
$StagedPython = Join-Path $PythonStage "python.exe"
if (-not (Test-Path -LiteralPath $StagedPython -PathType Leaf)) {
    throw "Verified Python runtime archive does not contain python.exe at its root."
}
$StagedVersion = (& $StagedPython --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Packaged Python executable failed its version check: $StagedVersion"
}
Assert-ClippyPythonRuntimeVersion -Actual $StagedVersion -Expected $PythonVersion
$StagedImportCheck = "import torch, torchvision, fastapi, uvicorn, faster_whisper; print('torch=' + torch.__version__); print('cuda_build=' + str(torch.version.cuda))"
& $StagedPython -c $StagedImportCheck
if ($LASTEXITCODE -ne 0) { throw "Packaged Python dependency verification failed." }
if ($TorchVariant -eq "cuda") {
    & $StagedPython -c "import torch; assert torch.version.cuda is not None, 'CUDA-enabled PyTorch is missing'"
    if ($LASTEXITCODE -ne 0) { throw "Selected CUDA runtime does not contain CUDA-enabled PyTorch." }
}

# Activate only after archive hash, Python version, and critical imports pass.
Install-ClippyComponent $PythonStage $PythonDir {
    param($dir)
    Test-ClippyExecutable (Join-Path $dir 'python.exe') '-c "import torch,fastapi,faster_whisper"' '' 120
}
$PythonExe = Join-Path $PythonDir 'python.exe'

# Node's archive is checked against the SHA-256 value published alongside the
# official Node.js release archive.
$NodeExe = Join-Path $NodeDir "node.exe"
$ExistingNodeHealthy = Test-ClippyExecutable $NodeExe '--version' "v$NodeVersion"
if (-not $ExistingNodeHealthy) {
    Write-Stage 'Managed Node.js runtime requires replacement.'
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
    $NodeStage = "$NodeDir.installing"
    if (Test-Path -LiteralPath $NodeStage) { Remove-Item -LiteralPath $NodeStage -Recurse -Force }
    Copy-Item -LiteralPath $ExtractedRoot -Destination $NodeStage -Recurse
    Install-ClippyComponent $NodeStage $NodeDir { param($dir) Test-ClippyExecutable (Join-Path $dir 'node.exe') '--version' "v$NodeVersion" }
    Remove-Item $Extract -Recurse -Force
}
$InstalledNodeVersion = (& $NodeExe --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $InstalledNodeVersion.TrimStart([char]"v") -ne $NodeVersion) {
    throw "Managed Node.js runtime version check failed. Expected $NodeVersion, found $InstalledNodeVersion."
}

# FFmpeg is downloaded from the Windows builds publisher and verified against
# the publisher's SHA-256 sidecar before extraction.
$FfmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"
$FfmpegCheck = { param($dir) (Test-ClippyExecutable (Join-Path $dir 'ffmpeg.exe') '-version') -and (Test-ClippyExecutable (Join-Path $dir 'ffprobe.exe') '-version') }
$ExistingFfmpegHealthy = & $FfmpegCheck $FfmpegDir
if (-not $ExistingFfmpegHealthy) {
    Write-Stage 'Managed FFmpeg runtime requires replacement.'
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
    $FfmpegStage = "$FfmpegDir.installing"
    if (Test-Path -LiteralPath $FfmpegStage) { Remove-Item -LiteralPath $FfmpegStage -Recurse -Force }
    Copy-Item -LiteralPath $SourceBin -Destination $FfmpegStage -Recurse
    Install-ClippyComponent $FfmpegStage $FfmpegDir $FfmpegCheck
    Remove-Item $Extract -Recurse -Force
}
& $FfmpegExe -version
if ($LASTEXITCODE -ne 0) { throw "Managed FFmpeg runtime failed its version check." }

if ($TorchVariant -eq "cuda") {
    # Windows PyTorch CUDA wheels place their CUDA DLLs in torch\lib.
    $CudaDllDirectory = Join-Path $PythonDir "Lib\site-packages\torch\lib"
    $CudaDllDirectories = @($CudaDllDirectory)
    $RequiredCudaDlls = @(
        (Join-Path $CudaDllDirectory "cublas64_12.dll"),
        (Join-Path $CudaDllDirectory "cudnn64_9.dll"),
        (Join-Path $CudaDllDirectory "cudart64_12.dll")
    )
    foreach ($dll in $RequiredCudaDlls) {
        if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) {
            throw "CUDA runtime is missing a required DLL for PyTorch/CTranslate2: $dll"
        }
    }
    $env:PATH = (($CudaDllDirectories -join ";") + ";" + $env:PATH)
}

Write-Stage "Verifying backend imports..."
Push-Location $App
try {
    $env:CLIPPY_DATA_DIR = $DataRoot
    $env:OUTPUT_DIR = Join-Path $DataRoot "output"
    $env:UPLOAD_DIR = Join-Path $DataRoot "uploads"
    $env:CLIPPY_SETTINGS_PATH = Join-Path $Root "settings.json"
    $env:CLIPPY_MODELS_DIR = Join-Path $DataRoot "models"
    $env:REFERENCE_TEMPLATES_DIR = Join-Path $DataRoot 'reference_templates'
    & $PythonExe -c "import app; import torch; import faster_whisper; import ctranslate2; print('Backend imports OK; torch CUDA:', torch.cuda.is_available())"
    if ($LASTEXITCODE -ne 0) { throw "Backend import verification failed. Check the Python dependency log." }
    if ($TorchVariant -eq "cuda") {
        Write-Stage "Running a real CUDA kernel and faster-whisper device capability check..."
        & $PythonExe -c "import torch, ctranslate2; assert torch.version.cuda and torch.version.cuda.startswith('12.8'), f'Expected CUDA 12.8, got {torch.version.cuda}'; assert torch.cuda.is_available(), 'PyTorch cannot initialize the NVIDIA device'; x=torch.ones((64,64),device='cuda'); y=x @ x; torch.cuda.synchronize(); assert float(y[0,0].item()) == 64.0, 'CUDA kernel produced an unexpected result'; count=ctranslate2.get_cuda_device_count(); assert count > 0, 'CTranslate2/faster-whisper cannot see a CUDA device'; print('CUDA kernel OK:', torch.cuda.get_device_name(0), '| CTranslate2 devices:', count)"
        if ($LASTEXITCODE -ne 0) {
            throw "CUDA runtime verification failed. Clippy will not mark an unusable CUDA installation as healthy. Check the NVIDIA driver, CUDA DLL paths, and GPU compatibility in the setup log."
        }
    }
} finally {
    Pop-Location
}

Write-Stage "Verifying the persistent Remotion browser runtime..."
$InstalledBrowserVersion = if (Test-Path -LiteralPath $BrowserVersionFile) { (Get-Content -LiteralPath $BrowserVersionFile -Raw).Trim() } else { "" }
$BrowserNeedsInstall = -not (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf) -or $InstalledBrowserVersion -ne $RemotionVersion
if (-not $BrowserNeedsInstall) {
    $BrowserNeedsInstall = ((Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Contract.browserSha256) -or -not (Test-ClippyExecutable $BrowserExecutable '--headless --disable-gpu --dump-dom about:blank')
}
if ($BrowserNeedsInstall) {
    Write-Stage "Installing or repairing the Remotion browser for renderer version $RemotionVersion..."
    # Google's headless shell is unsigned. Trust the publisher's versioned HTTPS
    # archive only after matching the immutable hashes shipped in the payload.
    $BrowserArchive = Join-Path $Downloads "chrome-headless-shell-$($Contract.browserVersion)-win64.zip"
    Download-File $BrowserArchiveUrl $BrowserArchive
    try { Assert-Sha256 $BrowserArchive $Contract.browserArchiveSha256 } catch {
        Remove-Item -LiteralPath $BrowserArchive -Force
        Download-File $BrowserArchiveUrl $BrowserArchive
        Assert-Sha256 $BrowserArchive $Contract.browserArchiveSha256
    }
    $BrowserExtract = Join-Path $ScratchRoot 'browser-extract'
    Expand-ArchiveFast $BrowserArchive $BrowserExtract
    $DownloadedBrowserDir = Join-Path $BrowserExtract 'chrome-headless-shell-win64'
    Assert-Sha256 (Join-Path $DownloadedBrowserDir 'chrome-headless-shell.exe') $Contract.browserSha256
    $BrowserStage = "$BrowserDir.installing"
    if (Test-Path -LiteralPath $BrowserStage) { Remove-Item -LiteralPath $BrowserStage -Recurse -Force }
    Copy-Item -LiteralPath $DownloadedBrowserDir -Destination $BrowserStage -Recurse
    Install-ClippyComponent $BrowserStage $BrowserDir {
        param($dir)
        $exe = Join-Path $dir 'chrome-headless-shell.exe'
        ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Contract.browserSha256) -and (Test-ClippyExecutable $exe '--headless --disable-gpu --dump-dom about:blank')
    }
    Remove-Item -LiteralPath $BrowserExtract -Recurse -Force
    [System.IO.File]::WriteAllText($BrowserVersionFile, $RemotionVersion, [System.Text.UTF8Encoding]::new($false))
} else {
    Write-Stage "Reusing the browser already installed for Remotion $RemotionVersion."
}

if (-not (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf)) {
    throw "Persistent Remotion browser executable is missing: $BrowserExecutable"
}
Assert-Sha256 $BrowserExecutable $Contract.browserSha256
$BrowserSha256 = (Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
$env:REMOTION_BROWSER_EXECUTABLE = $BrowserExecutable
$BrowserValidation = "import('@remotion/renderer').then(async m => { await m.ensureBrowser({browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE}); console.log('Persistent Remotion browser ready'); }).catch(e => { console.error(e); process.exit(1); });"
Push-Location (Join-Path $App "render-service")
try {
    & $NodeExe -e $BrowserValidation
    if ($LASTEXITCODE -ne 0) { throw "Persistent Remotion browser validation failed." }
} finally {
    Pop-Location
}


New-Item -ItemType Directory -Path (Split-Path $ManifestPath -Parent) -Force | Out-NULL
$Manifest = @{
    version = "1.0.0"
    components = @{
        python = @{ version = $PythonVersion; installed = $true }
        node = @{ version = $NodeVersion; installed = $true }
        ffmpeg = @{ version = $FfmpegVersion; installed = $true }
        browser = @{ version = $RemotionVersion; installed = $true }
    }
    schema = 1
    state = $ExpectedState
    installedAt = (Get-Date).ToUniversalTime().ToString("o")
    requirementsSha256 = $RequirementsHash
    browserSha256 = $BrowserSha256
    gpuMode = if ($TorchVariant -eq "cuda") { "cuda128" } else { "cpu" }
}
$ManifestJson = $Manifest | ConvertTo-Json -Depth 5
# Windows PowerShell 5.1 writes a UTF-8 BOM with Set-Content -Encoding UTF8.
# serde_json expects plain JSON, so write UTF-8 explicitly without a BOM.
[System.IO.File]::WriteAllText($ManifestPath, $ManifestJson, [System.Text.UTF8Encoding]::new($false))
# Remove the multi-gigabyte Python archive and release parts only after the
# complete runtime setup has succeeded. If setup fails earlier, verified parts
# remain available for a retry without downloading them again.
if ([string]::IsNullOrWhiteSpace($LocalRuntimeArchive) -and $RuntimeManifest) {
    Remove-Item -LiteralPath $PythonRuntimeArchive, $PythonRuntimeManifestPath -Force -ErrorAction SilentlyContinue
    foreach ($Part in @($RuntimeManifest.parts)) {
        Remove-Item -LiteralPath (Join-Path $Downloads ([string]$Part.name)) -Force -ErrorAction SilentlyContinue
    }
}
Remove-ClippyScratchRoot
Write-Stage "Runtime setup completed successfully."
} finally {
    $InstallMutex.ReleaseMutex(); $InstallMutex.Dispose()
    if ($DesktopMutex) { $DesktopMutex.ReleaseMutex(); $DesktopMutex.Dispose() }
}
 -or $Contract.ffmpegArchiveSha256 -notmatch '^[a-f0-9]{64}
$PythonVersion = $Contract.python
$NodeVersion = $Contract.node
$FfmpegVersion = $Contract.ffmpeg
$TorchVariant = 'cpu'
if ($Contract.browserVersion -notmatch '^\d+\.\d+\.\d+\.\d+$' -or $Contract.browserArchiveSha256 -notmatch '^[a-f0-9]{64}$' -or $Contract.browserSha256 -notmatch '^[a-f0-9]{64}$') { throw 'Browser integrity contract is invalid.' }
$BrowserArchiveUrl = "https://storage.googleapis.com/chrome-for-testing-public/$($Contract.browserVersion)/win64/chrome-headless-shell-win64.zip"

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
$DataRoot = Join-Path $Root "data"
$StorageLocationPath = Join-Path $Root "storage-location.json"
if (Test-Path -LiteralPath $StorageLocationPath -PathType Leaf) {
    try {
        $StorageLocation = Get-Content -LiteralPath $StorageLocationPath -Raw | ConvertFrom-Json
        $ConfiguredDataRoot = [string]$StorageLocation.data_directory
        if ($StorageLocation.schema_version -ne 1 -or [string]::IsNullOrWhiteSpace($ConfiguredDataRoot)) {
            throw "Storage location configuration is incomplete or unsupported."
        }
        $DataRoot = [IO.Path]::GetFullPath($ConfiguredDataRoot)
        if ($DataRoot -notmatch '^[A-Za-z]:\\|^\\\\') {
            throw "Configured Clippy data directory must be an absolute Windows path."
        }
        if (-not (Test-Path -LiteralPath $DataRoot -PathType Container)) {
            throw "Configured Clippy data directory is unavailable: $DataRoot"
        }
    } catch {
        throw "Cannot load Clippy's configured data directory: $($_.Exception.Message)"
    }
}
$PythonDir = Join-Path $Runtime "python"
$NodeDir = Join-Path $Runtime "node"
$FfmpegDir = Join-Path $Runtime "ffmpeg\bin"
$ManifestPath = Join-Path $Root "runtime-manifest.json"
# Browser binaries are durable user data, not part of app\current. Updating the
# application payload must not force a multi-hundred-MB browser download.
$BrowserRoot = Join-Path $Root "browser"
$BrowserDir = Join-Path $BrowserRoot "headless-shell"
$BrowserExecutable = Join-Path $BrowserDir "chrome-headless-shell.exe"
$BrowserVersionFile = Join-Path $BrowserRoot "remotion-version.txt"
$LogDir = Join-Path $Root "logs"
$SetupLogPath = Join-Path $LogDir "runtime-setup.log"
$script:ScratchRoot = $null
$NvidiaDriverVersion = $null
$NvidiaGpuName = $null
$NvidiaComputeCapability = $null
$ForceCpuRuntime = $env:CLIPPY_FORCE_CPU_RUNTIME -eq "1"
if (-not $ForceCpuRuntime) {
    $Nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
$NvidiaSmiPath = if ($Nvidia) { $Nvidia.Source } else { $null }
if (-not $NvidiaSmiPath) {
    $NvidiaCandidates = @(
        (Join-Path $env:ProgramFiles "NVIDIA Corporation\NVSMI\nvidia-smi.exe"),
        (Join-Path $env:SystemRoot "System32\nvidia-smi.exe")
    )
    $NvidiaSmiPath = $NvidiaCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if ($NvidiaSmiPath) {
    $NvidiaInfo = & $NvidiaSmiPath --query-gpu=name,driver_version,compute_cap --format=csv,noheader 2>$null
    if ($LASTEXITCODE -eq 0 -and $NvidiaInfo) {
        $NvidiaLine = @($NvidiaInfo) | Select-Object -First 1
        $NvidiaFields = ([string]$NvidiaLine).Split(',')
        if ($NvidiaFields.Count -ge 3) {
            $NvidiaGpuName = $NvidiaFields[0].Trim()
            $DriverText = $NvidiaFields[1].Trim()
            try { $NvidiaDriverVersion = [Version]$DriverText } catch { $NvidiaDriverVersion = $null }
            $ParsedComputeCapability = 0.0
            if ([double]::TryParse($NvidiaFields[2].Trim(), [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$ParsedComputeCapability)) {
                $NvidiaComputeCapability = $ParsedComputeCapability
            }
            # CUDA 12.8 GA requires Windows driver 570.65. The packaged
            # PyTorch CUDA runtime targets Volta/Turing-era and newer devices;
            # Blackwell is supported by cu128. Unsupported/unknown devices use
            # the CPU runtime instead of failing during the first CUDA kernel.
            if ($NvidiaDriverVersion -and $NvidiaDriverVersion -ge [Version]"570.65" -and
                $null -ne $NvidiaComputeCapability -and $NvidiaComputeCapability -ge 7.0) {
                $TorchVariant = "cuda"
            }
        }
    }
}
}
$PythonArchiveName = "python-$PythonVersion-embed-amd64.zip"
$PythonArchiveUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$PythonArchiveSha256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
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

function Remove-ClippyScratchRoot {
    $scratch = $script:ScratchRoot
    if (-not [string]::IsNullOrWhiteSpace($scratch) -and (Test-Path -LiteralPath $scratch -PathType Container)) {
        Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }
    $script:ScratchRoot = $null
}

trap {
    $Failure = $_
    try {
        Write-Stage ("SETUP FAILED: " + $Failure.Exception.Message)
        Write-Stage ("Failure location: " + $Failure.InvocationInfo.PositionMessage)
        Write-Stage ("Diagnostic log: " + $SetupLogPath)
    } catch { }
    try { Remove-ClippyScratchRoot } catch { }
    exit 1
}

Write-Stage "Runtime setup engine started."
Write-Stage ("Selected prebuilt Python runtime variant: " + $TorchVariant)
if ($ForceCpuRuntime) {
    Write-Stage "CPU runtime selection was explicitly forced by CLIPPY_FORCE_CPU_RUNTIME=1."
}

# Load script dependencies only after logging and the failure trap are active.
# This turns missing packaged helpers into a useful diagnostic instead of an
# early PowerShell dot-source failure with no Clippy setup context.
foreach ($Helper in @("runtime-manifest-state.ps1", "runtime-archive.ps1", "runtime-health.ps1")) {
    $HelperPath = Join-Path $PSScriptRoot $Helper
    if (-not (Test-Path -LiteralPath $HelperPath -PathType Leaf)) {
        throw "Application payload is incomplete. Missing required runtime helper: $HelperPath"
    }
}
. (Join-Path $PSScriptRoot "runtime-manifest-state.ps1")
. (Join-Path $PSScriptRoot "runtime-archive.ps1")
. (Join-Path $PSScriptRoot "runtime-health.ps1")
if ($NvidiaGpuName) {
    Write-Stage ("Detected NVIDIA GPU: " + $NvidiaGpuName + "; driver " + $NvidiaDriverVersion + "; compute capability " + $NvidiaComputeCapability)
    if ($TorchVariant -eq "cpu") {
        Write-Stage "NVIDIA driver or compute capability is not supported by the packaged CUDA 12.8 runtime; using the CPU runtime."
    }
}

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

            $ExpectedTotalBytes = $null
            if ($Status -eq 206) {
                $ContentRange = $Response.Headers["Content-Range"]
                if ($ContentRange -notmatch "^bytes\s+(\d+)-(\d+)/(\d+)$") {
                    throw "Server returned a missing or invalid Content-Range while resuming $Url"
                }
                $RangeStart = [long]$Matches[1]
                $RangeEnd = [long]$Matches[2]
                $ExpectedTotalBytes = [long]$Matches[3]
                if ($RangeStart -ne $Offset -or $RangeEnd -lt $RangeStart -or $ExpectedTotalBytes -le $RangeEnd) {
                    throw "Server returned an inconsistent Content-Range while resuming $Url"
                }
                $ExpectedResponseBytes = $RangeEnd - $RangeStart + 1
                if ($Response.ContentLength -ge 0 -and $Response.ContentLength -ne $ExpectedResponseBytes) {
                    throw "Server Content-Length does not match Content-Range while downloading $Url"
                }
            } elseif ($Response.ContentLength -ge 0) {
                $ExpectedTotalBytes = [long]$Response.ContentLength
            }

            $InputStream = $Response.GetResponseStream()
            $Mode = if ($Offset -gt 0 -and $Status -eq 206) { [IO.FileMode]::Append } else { [IO.FileMode]::Create }
            $OutputStream = [IO.File]::Open($Partial, $Mode, [IO.FileAccess]::Write, [IO.FileShare]::None)
            $Buffer = New-Object byte[] (1024 * 1024)
            $Downloaded = $Offset
            $LastReportedPercent = -1
            while (($Read = $InputStream.Read($Buffer, 0, $Buffer.Length)) -gt 0) {
                $OutputStream.Write($Buffer, 0, $Read)
                $Downloaded += $Read
                if ($ExpectedTotalBytes -gt 0) {
                    $Percent = [int][math]::Floor(($Downloaded * 100.0) / $ExpectedTotalBytes)
                    if ($Percent -ge $LastReportedPercent + 10) {
                        $LastReportedPercent = $Percent
                        Write-Stage ("{0}: {1}% ({2:N0}/{3:N0} bytes)." -f [IO.Path]::GetFileName($Destination), $Percent, $Downloaded, $ExpectedTotalBytes)
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
            if ($null -ne $ExpectedTotalBytes -and (Get-Item -LiteralPath $Partial).Length -ne $ExpectedTotalBytes) {
                throw "Download ended before the server-declared content length was received. Partial data has been preserved for resume."
            }
            Move-Item -LiteralPath $Partial -Destination $Destination -Force
            Write-Stage "Download complete: $([IO.Path]::GetFileName($Destination))."
            return
        } catch {
            $Message = $_.Exception.Message
            if ($OutputStream) { $OutputStream.Dispose(); $OutputStream = $null }
            if ($InputStream) { $InputStream.Dispose(); $InputStream = $null }
            if ($Response) { $Response.Close(); $Response = $null }

            # A missing release or asset is permanent until the publisher fixes
            # it. Do not waste time retrying an HTTP 404 three times.
            $ErrorResponse = $_.Exception.Response
            if ($ErrorResponse -is [System.Net.HttpWebResponse] -and [int]$ErrorResponse.StatusCode -eq 404) {
                $ErrorResponse.Close()
                throw "HTTP 404: required download asset was not found: $Url. Confirm that the matching Clippy release exists and contains this asset."
            }

            # A completed partial file can legitimately receive HTTP 416 when
            # the server is asked to resume exactly at EOF. Promote it and let
            # the caller's mandatory SHA-256 verification decide whether it is
            # usable. If it is longer than the server object, discard it and
            # retry from byte zero.
            $ErrorResponse = $_.Exception.Response
            if ($ErrorResponse -is [System.Net.HttpWebResponse]) {
                try {
                    if ([int]$ErrorResponse.StatusCode -eq 416) {
                        $RangeHeader = $ErrorResponse.Headers["Content-Range"]
                        if ($RangeHeader -match "^bytes\s+\*/(\d+)$") {
                            $ServerLength = [long]$Matches[1]
                            $PartialLength = if (Test-Path -LiteralPath $Partial) { (Get-Item -LiteralPath $Partial).Length } else { 0L }
                            if ($PartialLength -eq $ServerLength -and $ServerLength -gt 0) {
                                $ErrorResponse.Close()
                                Move-Item -LiteralPath $Partial -Destination $Destination -Force
                                Write-Stage "Resumed download was already complete; promoted the verified partial file."
                                return
                            }
                            if ($PartialLength -ne $ServerLength) {
                                Remove-Item -LiteralPath $Partial -Force -ErrorAction SilentlyContinue
                                Write-Stage "Discarded an inconsistent partial download after HTTP 416 and will restart from byte zero."
                            }
                        }
                    }
                } finally {
                    $ErrorResponse.Close()
                }
            }

            if ($Attempt -eq 3) { throw "Download failed after 3 attempts: $Url. $Message" }
            Write-Stage "Download interrupted; preserving valid partial data for resume. $Message"
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

# Prefer per-user temporary storage; inaccessible fixed volumes are skipped.
$ScratchCandidates = @([IO.Path]::GetTempPath()) + @([IO.DriveInfo]::GetDrives() |
    Where-Object { $_.IsReady -and $_.DriveType -eq [IO.DriveType]::Fixed } |
    Sort-Object AvailableFreeSpace -Descending | ForEach-Object { $_.RootDirectory.FullName })
foreach ($componentPath in @($PythonDir, $NodeDir, $FfmpegDir, $BrowserDir)) { Restore-ClippyComponent $componentPath }
foreach ($Required in @("app.py", "requirements.txt", "setup-runtime.ps1", "runtime-archive.ps1", "runtime-manifest-state.ps1", "VERSION", "bgutil-provider\server\build\generate_once.js")) {
    if (-not (Test-Path (Join-Path $App $Required))) {
        throw "Application payload is incomplete. Missing $Required in $App"
    }
}

$RequirementsHash = (Get-FileHash (Join-Path $App "requirements.txt") -Algorithm SHA256).Hash.ToLowerInvariant()
$RemotionPackagePath = Join-Path $App "render-service\node_modules\@remotion\renderer\package.json"
if (-not (Test-Path -LiteralPath $RemotionPackagePath -PathType Leaf)) {
    throw "Remotion renderer package is missing from the application payload: $RemotionPackagePath"
}
$RemotionVersion = (Get-Content -LiteralPath $RemotionPackagePath -Raw | ConvertFrom-Json).version
if ([string]::IsNullOrWhiteSpace($RemotionVersion)) { throw "Could not determine the bundled Remotion renderer version." }

# Build expected state from runtime contract
$ExpectedState = New-ClippyRuntimeState -PythonVersion $PythonVersion -PythonVariant $TorchVariant -NodeVersion $NodeVersion -FfmpegVersion $FfmpegVersion -BrowserVersion $RemotionVersion -RequirementsSha256 $RequirementsHash
if (Test-Path $ManifestPath) {
    try {
        $Existing = Get-Content $ManifestPath -Raw | ConvertFrom-Json
        $PythonExe = Join-Path $PythonDir "python.exe"
        $NodeExe = Join-Path $NodeDir "node.exe"
        $FfmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"
        $RuntimeFilesPresent =
            (Test-Path -LiteralPath $PythonExe -PathType Leaf) -and
            (Test-Path -LiteralPath $NodeExe -PathType Leaf) -and
            (Test-Path -LiteralPath $FfmpegExe -PathType Leaf) -and
            (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf) -and
            (Test-Path -LiteralPath $BrowserVersionFile -PathType Leaf) -and
            ((Get-Content -LiteralPath $BrowserVersionFile -Raw).Trim() -eq $RemotionVersion)
        $ManifestComponentsHealthy = $Existing.version -eq "1.0.0" -and $Existing.schema -eq 1
        foreach ($componentName in @("python", "node", "ffmpeg", "browser")) {
            $component = $Existing.components.$componentName
            if (-not $component -or -not $component.installed -or [string]::IsNullOrWhiteSpace([string]$component.version)) {
                $ManifestComponentsHealthy = $false
            }
        }
        $ManifestComponentsHealthy = $ManifestComponentsHealthy -and
            ($Existing.components.python.version -eq $PythonVersion) -and
            ($Existing.components.node.version -eq $NodeVersion) -and
            ($Existing.components.ffmpeg.version -eq $FfmpegVersion) -and
            ($Existing.components.browser.version -eq $RemotionVersion) -and
            ($Existing.requirementsSha256 -eq $RequirementsHash) -and
            ($Existing.browserSha256 -match "^[a-fA-F0-9]{64}$") -and
            ($Existing.browserSha256 -eq $Contract.browserSha256) -and
            ($Existing.browserSha256 -eq (Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant())
        if ($Existing.state -eq $ExpectedState -and $RuntimeFilesPresent -and $ManifestComponentsHealthy) {
            Write-Stage "Verifying installed Python, Node.js, FFmpeg, backend, and Remotion dependencies..."
            $PythonVersionHealthy = Test-ClippyExecutable $PythonExe '--version' "Python $PythonVersion"
            $NodeVersionHealthy = Test-ClippyExecutable $NodeExe '--version' "v$NodeVersion"
            $FfmpegHealthy = (Test-ClippyExecutable $FfmpegExe '-version') -and (Test-ClippyExecutable (Join-Path $FfmpegDir 'ffprobe.exe') '-version')
            $PythonHealthy = $false
            $NodeHealthy = $false
            $CudaDllDirectories = @()
            $CudaDllsHealthy = $true
            if ($TorchVariant -eq "cuda") {
                # Windows PyTorch CUDA wheels place their CUDA DLLs in torch\lib.
                $CudaDllDirectory = Join-Path $PythonDir "Lib\site-packages\torch\lib"
                $CudaDllDirectories = @($CudaDllDirectory)
                $RequiredCudaDlls = @(
                    (Join-Path $CudaDllDirectory "cublas64_12.dll"),
                    (Join-Path $CudaDllDirectory "cudnn64_9.dll"),
                    (Join-Path $CudaDllDirectory "cudart64_12.dll")
                )
                foreach ($dll in $RequiredCudaDlls) {
                    if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) { $CudaDllsHealthy = $false }
                }
                if ($CudaDllsHealthy) { $env:PATH = (($CudaDllDirectories -join ";") + ";" + $env:PATH) }
            }
            Push-Location $App
            try {
                $env:CLIPPY_DATA_DIR = $DataRoot
                $env:OUTPUT_DIR = Join-Path $DataRoot "output"
                $env:UPLOAD_DIR = Join-Path $DataRoot "uploads"
                $env:CLIPPY_SETTINGS_PATH = Join-Path $Root "settings.json"
                $env:CLIPPY_MODELS_DIR = Join-Path $DataRoot "models"
                $env:REFERENCE_TEMPLATES_DIR = Join-Path $DataRoot 'reference_templates'
                $PythonHealthScript = "import app, torch, faster_whisper"
                if ($TorchVariant -eq "cuda") {
                    $PythonHealthScript += "; import ctranslate2; assert torch.version.cuda and torch.version.cuda.startswith('12.8'); assert torch.cuda.is_available(); x=torch.ones((64,64),device='cuda'); y=x @ x; torch.cuda.synchronize(); assert float(y[0,0].item()) == 64.0; assert ctranslate2.get_cuda_device_count() > 0"
                } else {
                    $PythonHealthScript += "; assert torch.version.cuda is None"
                }
                $PythonHealthy = $PythonVersionHealthy -and $CudaDllsHealthy -and (Test-ClippyExecutable $PythonExe ('-c "' + $PythonHealthScript + '"') '' 120)
                $env:REMOTION_BROWSER_EXECUTABLE = $BrowserExecutable
                $BrowserCheck = "import('@remotion/renderer').then(async m => { await m.ensureBrowser({browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE}); }).catch(e => { console.error(e); process.exit(1); });"
                Push-Location (Join-Path $App "render-service")
                try {
                    $BrowserPackageHealthy = Test-ClippyExecutable $NodeExe ('-e "' + $BrowserCheck + '"')
                    $NodeHealthy = ($NodeVersionHealthy -and $BrowserPackageHealthy) -and (Test-ClippyExecutable $BrowserExecutable '--headless --disable-gpu --dump-dom about:blank')
                } finally {
                    Pop-Location
                }
            } finally {
                Pop-Location
            }
            if ($PythonHealthy -and $NodeHealthy -and $FfmpegHealthy) {
                Write-Stage "Managed runtimes and application dependencies are healthy. No downloads needed."
                Remove-ClippyScratchRoot
                exit 0
            }
            Write-Stage "A runtime health check failed; repairing dependencies."
        }
    } catch {
        Write-Stage "Previous runtime manifest is invalid; repairing managed runtimes."
    }
}

$script:ScratchRoot = New-ClippyScratch $ScratchCandidates -RuntimeRoot $Root
$ScratchDrive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($ScratchRoot))
$env:TEMP = $ScratchRoot
$env:TMP = $ScratchRoot
$env:PIP_CACHE_DIR = Join-Path $ScratchRoot 'pip-cache'
Write-Stage ("Using " + $ScratchRoot + " for temporary setup files; managed runtimes remain in " + $Root)
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
if ($AppVersion -notmatch "^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$") { throw "Application VERSION file is missing or invalid." }

$PythonRuntimeName = "clippy-python-$TorchVariant-$AppVersion.zip"
$PythonRuntimeArchive = Join-Path $Downloads $PythonRuntimeName
$PythonRuntimeManifestName = "clippy-python-$TorchVariant.manifest.json"
$PythonRuntimeManifestUrl = "https://github.com/helalxp/clippy/releases/download/v$AppVersion/$PythonRuntimeManifestName"
$PythonRuntimeReleaseBaseUrl = "https://github.com/helalxp/clippy/releases/download/v$AppVersion"
$LocalRuntimeArchive = $env:CLIPPY_PYTHON_RUNTIME_ARCHIVE
$LocalRuntimeChecksum = $env:CLIPPY_PYTHON_RUNTIME_CHECKSUM

# Local archive overrides remain available for developer diagnostics. Customer
# installs use only the manifest and assets from the exact matching release.
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
    $PythonRuntimeManifestPath = Join-Path $Downloads "$AppVersion-$PythonRuntimeManifestName"
    Download-File $PythonRuntimeManifestUrl $PythonRuntimeManifestPath
    $ManifestParsed = $false
    for ($ManifestAttempt = 1; $ManifestAttempt -le 2; $ManifestAttempt++) {
        try {
            $RuntimeManifest = Get-Content -LiteralPath $PythonRuntimeManifestPath -Raw | ConvertFrom-Json
            $ManifestParsed = $true
            break
        } catch {
            Remove-Item -LiteralPath $PythonRuntimeManifestPath -Force -ErrorAction SilentlyContinue
            if ($ManifestAttempt -eq 2) {
                throw "The runtime manifest downloaded from release v$AppVersion is not valid JSON: $PythonRuntimeManifestUrl"
            }
            Write-Stage "Cached runtime manifest was invalid; downloading it again."
            Download-File $PythonRuntimeManifestUrl $PythonRuntimeManifestPath
        }
    }
    if (-not $ManifestParsed) { throw "Could not read the runtime manifest for release v$AppVersion." }
    Assert-ClippyRuntimeArchiveManifest -Manifest $RuntimeManifest -ExpectedApplicationVersion $AppVersion -ExpectedVariant $TorchVariant | Out-Null

    foreach ($Part in @($RuntimeManifest.parts)) {
        $PartName = [string]$Part.name
        $PartUrl = "$PythonRuntimeReleaseBaseUrl/$PartName"
        $PartPath = Join-Path $Downloads $PartName
        $PartHealthy = $false
        if (Test-Path -LiteralPath $PartPath -PathType Leaf) {
            $PartInfo = Get-Item -LiteralPath $PartPath
            if ($PartInfo.Length -eq [long]$Part.size -and
                (Get-ClippyFileSha256 $PartPath) -eq ([string]$Part.sha256).ToLowerInvariant()) {
                $PartHealthy = $true
                Write-Stage "Reusing verified runtime part $PartName."
            } else {
                Write-Stage "Cached runtime part $PartName failed verification; downloading it again."
                Remove-Item -LiteralPath $PartPath -Force
            }
        }
        if (-not $PartHealthy) {
            Download-File $PartUrl $PartPath
            $PartInfo = Get-Item -LiteralPath $PartPath
            if ($PartInfo.Length -ne [long]$Part.size -or
                (Get-ClippyFileSha256 $PartPath) -ne ([string]$Part.sha256).ToLowerInvariant()) {
                Remove-Item -LiteralPath $PartPath -Force -ErrorAction SilentlyContinue
                throw "Downloaded runtime part failed size or SHA-256 verification: $PartName"
            }
        }
    }

    Write-Stage "Reconstructing the verified $TorchVariant Python runtime archive from $($RuntimeManifest.partCount) release asset(s)..."
    Join-ClippyRuntimeArchiveParts -Manifest $RuntimeManifest -PartsDirectory $Downloads -Destination $PythonRuntimeArchive | Out-Null
    $PythonRuntimeVerified = $true
}
if (-not $PythonRuntimeVerified) { throw "Could not verify the downloaded Python runtime." }

$PythonStage = Join-Path $Runtime "python.installing"
if (Test-Path $PythonStage) { Remove-Item $PythonStage -Recurse -Force }
Write-Stage "Extracting the verified $TorchVariant Python runtime..."
Expand-ArchiveFast $PythonRuntimeArchive $PythonStage
$StagedPython = Join-Path $PythonStage "python.exe"
if (-not (Test-Path -LiteralPath $StagedPython -PathType Leaf)) {
    throw "Verified Python runtime archive does not contain python.exe at its root."
}
$StagedVersion = (& $StagedPython --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Packaged Python executable failed its version check: $StagedVersion"
}
Assert-ClippyPythonRuntimeVersion -Actual $StagedVersion -Expected $PythonVersion
$StagedImportCheck = "import torch, torchvision, fastapi, uvicorn, faster_whisper; print('torch=' + torch.__version__); print('cuda_build=' + str(torch.version.cuda))"
& $StagedPython -c $StagedImportCheck
if ($LASTEXITCODE -ne 0) { throw "Packaged Python dependency verification failed." }
if ($TorchVariant -eq "cuda") {
    & $StagedPython -c "import torch; assert torch.version.cuda is not None, 'CUDA-enabled PyTorch is missing'"
    if ($LASTEXITCODE -ne 0) { throw "Selected CUDA runtime does not contain CUDA-enabled PyTorch." }
}

# Activate only after archive hash, Python version, and critical imports pass.
Install-ClippyComponent $PythonStage $PythonDir {
    param($dir)
    Test-ClippyExecutable (Join-Path $dir 'python.exe') '-c "import torch,fastapi,faster_whisper"' '' 120
}
$PythonExe = Join-Path $PythonDir 'python.exe'

# Node's archive is checked against the SHA-256 value published alongside the
# official Node.js release archive.
$NodeExe = Join-Path $NodeDir "node.exe"
$ExistingNodeHealthy = Test-ClippyExecutable $NodeExe '--version' "v$NodeVersion"
if (-not $ExistingNodeHealthy) {
    Write-Stage 'Managed Node.js runtime requires replacement.'
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
    $NodeStage = "$NodeDir.installing"
    if (Test-Path -LiteralPath $NodeStage) { Remove-Item -LiteralPath $NodeStage -Recurse -Force }
    Copy-Item -LiteralPath $ExtractedRoot -Destination $NodeStage -Recurse
    Install-ClippyComponent $NodeStage $NodeDir { param($dir) Test-ClippyExecutable (Join-Path $dir 'node.exe') '--version' "v$NodeVersion" }
    Remove-Item $Extract -Recurse -Force
}
$InstalledNodeVersion = (& $NodeExe --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $InstalledNodeVersion.TrimStart([char]"v") -ne $NodeVersion) {
    throw "Managed Node.js runtime version check failed. Expected $NodeVersion, found $InstalledNodeVersion."
}

# FFmpeg is downloaded from the Windows builds publisher and verified against
# the publisher's SHA-256 sidecar before extraction.
$FfmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"
$FfmpegCheck = { param($dir) (Test-ClippyExecutable (Join-Path $dir 'ffmpeg.exe') '-version') -and (Test-ClippyExecutable (Join-Path $dir 'ffprobe.exe') '-version') }
$ExistingFfmpegHealthy = & $FfmpegCheck $FfmpegDir
if (-not $ExistingFfmpegHealthy) {
    Write-Stage 'Managed FFmpeg runtime requires replacement.'
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
    $FfmpegStage = "$FfmpegDir.installing"
    if (Test-Path -LiteralPath $FfmpegStage) { Remove-Item -LiteralPath $FfmpegStage -Recurse -Force }
    Copy-Item -LiteralPath $SourceBin -Destination $FfmpegStage -Recurse
    Install-ClippyComponent $FfmpegStage $FfmpegDir $FfmpegCheck
    Remove-Item $Extract -Recurse -Force
}
& $FfmpegExe -version
if ($LASTEXITCODE -ne 0) { throw "Managed FFmpeg runtime failed its version check." }

if ($TorchVariant -eq "cuda") {
    # Windows PyTorch CUDA wheels place their CUDA DLLs in torch\lib.
    $CudaDllDirectory = Join-Path $PythonDir "Lib\site-packages\torch\lib"
    $CudaDllDirectories = @($CudaDllDirectory)
    $RequiredCudaDlls = @(
        (Join-Path $CudaDllDirectory "cublas64_12.dll"),
        (Join-Path $CudaDllDirectory "cudnn64_9.dll"),
        (Join-Path $CudaDllDirectory "cudart64_12.dll")
    )
    foreach ($dll in $RequiredCudaDlls) {
        if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) {
            throw "CUDA runtime is missing a required DLL for PyTorch/CTranslate2: $dll"
        }
    }
    $env:PATH = (($CudaDllDirectories -join ";") + ";" + $env:PATH)
}

Write-Stage "Verifying backend imports..."
Push-Location $App
try {
    $env:CLIPPY_DATA_DIR = $DataRoot
    $env:OUTPUT_DIR = Join-Path $DataRoot "output"
    $env:UPLOAD_DIR = Join-Path $DataRoot "uploads"
    $env:CLIPPY_SETTINGS_PATH = Join-Path $Root "settings.json"
    $env:CLIPPY_MODELS_DIR = Join-Path $DataRoot "models"
    $env:REFERENCE_TEMPLATES_DIR = Join-Path $DataRoot 'reference_templates'
    & $PythonExe -c "import app; import torch; import faster_whisper; import ctranslate2; print('Backend imports OK; torch CUDA:', torch.cuda.is_available())"
    if ($LASTEXITCODE -ne 0) { throw "Backend import verification failed. Check the Python dependency log." }
    if ($TorchVariant -eq "cuda") {
        Write-Stage "Running a real CUDA kernel and faster-whisper device capability check..."
        & $PythonExe -c "import torch, ctranslate2; assert torch.version.cuda and torch.version.cuda.startswith('12.8'), f'Expected CUDA 12.8, got {torch.version.cuda}'; assert torch.cuda.is_available(), 'PyTorch cannot initialize the NVIDIA device'; x=torch.ones((64,64),device='cuda'); y=x @ x; torch.cuda.synchronize(); assert float(y[0,0].item()) == 64.0, 'CUDA kernel produced an unexpected result'; count=ctranslate2.get_cuda_device_count(); assert count > 0, 'CTranslate2/faster-whisper cannot see a CUDA device'; print('CUDA kernel OK:', torch.cuda.get_device_name(0), '| CTranslate2 devices:', count)"
        if ($LASTEXITCODE -ne 0) {
            throw "CUDA runtime verification failed. Clippy will not mark an unusable CUDA installation as healthy. Check the NVIDIA driver, CUDA DLL paths, and GPU compatibility in the setup log."
        }
    }
} finally {
    Pop-Location
}

Write-Stage "Verifying the persistent Remotion browser runtime..."
$InstalledBrowserVersion = if (Test-Path -LiteralPath $BrowserVersionFile) { (Get-Content -LiteralPath $BrowserVersionFile -Raw).Trim() } else { "" }
$BrowserNeedsInstall = -not (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf) -or $InstalledBrowserVersion -ne $RemotionVersion
if (-not $BrowserNeedsInstall) {
    $BrowserNeedsInstall = ((Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Contract.browserSha256) -or -not (Test-ClippyExecutable $BrowserExecutable '--headless --disable-gpu --dump-dom about:blank')
}
if ($BrowserNeedsInstall) {
    Write-Stage "Installing or repairing the Remotion browser for renderer version $RemotionVersion..."
    # Google's headless shell is unsigned. Trust the publisher's versioned HTTPS
    # archive only after matching the immutable hashes shipped in the payload.
    $BrowserArchive = Join-Path $Downloads "chrome-headless-shell-$($Contract.browserVersion)-win64.zip"
    Download-File $BrowserArchiveUrl $BrowserArchive
    try { Assert-Sha256 $BrowserArchive $Contract.browserArchiveSha256 } catch {
        Remove-Item -LiteralPath $BrowserArchive -Force
        Download-File $BrowserArchiveUrl $BrowserArchive
        Assert-Sha256 $BrowserArchive $Contract.browserArchiveSha256
    }
    $BrowserExtract = Join-Path $ScratchRoot 'browser-extract'
    Expand-ArchiveFast $BrowserArchive $BrowserExtract
    $DownloadedBrowserDir = Join-Path $BrowserExtract 'chrome-headless-shell-win64'
    Assert-Sha256 (Join-Path $DownloadedBrowserDir 'chrome-headless-shell.exe') $Contract.browserSha256
    $BrowserStage = "$BrowserDir.installing"
    if (Test-Path -LiteralPath $BrowserStage) { Remove-Item -LiteralPath $BrowserStage -Recurse -Force }
    Copy-Item -LiteralPath $DownloadedBrowserDir -Destination $BrowserStage -Recurse
    Install-ClippyComponent $BrowserStage $BrowserDir {
        param($dir)
        $exe = Join-Path $dir 'chrome-headless-shell.exe'
        ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Contract.browserSha256) -and (Test-ClippyExecutable $exe '--headless --disable-gpu --dump-dom about:blank')
    }
    Remove-Item -LiteralPath $BrowserExtract -Recurse -Force
    [System.IO.File]::WriteAllText($BrowserVersionFile, $RemotionVersion, [System.Text.UTF8Encoding]::new($false))
} else {
    Write-Stage "Reusing the browser already installed for Remotion $RemotionVersion."
}

if (-not (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf)) {
    throw "Persistent Remotion browser executable is missing: $BrowserExecutable"
}
Assert-Sha256 $BrowserExecutable $Contract.browserSha256
$BrowserSha256 = (Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
$env:REMOTION_BROWSER_EXECUTABLE = $BrowserExecutable
$BrowserValidation = "import('@remotion/renderer').then(async m => { await m.ensureBrowser({browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE}); console.log('Persistent Remotion browser ready'); }).catch(e => { console.error(e); process.exit(1); });"
Push-Location (Join-Path $App "render-service")
try {
    & $NodeExe -e $BrowserValidation
    if ($LASTEXITCODE -ne 0) { throw "Persistent Remotion browser validation failed." }
} finally {
    Pop-Location
}


New-Item -ItemType Directory -Path (Split-Path $ManifestPath -Parent) -Force | Out-NULL
$Manifest = @{
    version = "1.0.0"
    components = @{
        python = @{ version = $PythonVersion; installed = $true }
        node = @{ version = $NodeVersion; installed = $true }
        ffmpeg = @{ version = $FfmpegVersion; installed = $true }
        browser = @{ version = $RemotionVersion; installed = $true }
    }
    schema = 1
    state = $ExpectedState
    installedAt = (Get-Date).ToUniversalTime().ToString("o")
    requirementsSha256 = $RequirementsHash
    browserSha256 = $BrowserSha256
    gpuMode = if ($TorchVariant -eq "cuda") { "cuda128" } else { "cpu" }
}
$ManifestJson = $Manifest | ConvertTo-Json -Depth 5
# Windows PowerShell 5.1 writes a UTF-8 BOM with Set-Content -Encoding UTF8.
# serde_json expects plain JSON, so write UTF-8 explicitly without a BOM.
[System.IO.File]::WriteAllText($ManifestPath, $ManifestJson, [System.Text.UTF8Encoding]::new($false))
# Remove the multi-gigabyte Python archive and release parts only after the
# complete runtime setup has succeeded. If setup fails earlier, verified parts
# remain available for a retry without downloading them again.
if ([string]::IsNullOrWhiteSpace($LocalRuntimeArchive) -and $RuntimeManifest) {
    Remove-Item -LiteralPath $PythonRuntimeArchive, $PythonRuntimeManifestPath -Force -ErrorAction SilentlyContinue
    foreach ($Part in @($RuntimeManifest.parts)) {
        Remove-Item -LiteralPath (Join-Path $Downloads ([string]$Part.name)) -Force -ErrorAction SilentlyContinue
    }
}
Remove-ClippyScratchRoot
Write-Stage "Runtime setup completed successfully."
} finally {
    $InstallMutex.ReleaseMutex(); $InstallMutex.Dispose()
    if ($DesktopMutex) { $DesktopMutex.ReleaseMutex(); $DesktopMutex.Dispose() }
}
 -or $Contract.ffmpegPrimaryUrl -notmatch '^https://www\.gyan\.dev/ffmpeg/builds/' -or $Contract.ffmpegFallbackUrl -notmatch '^https://github\.com/GyanD/codexffmpeg/releases/download/') { throw 'Unsupported runtime contract.' }
$PythonVersion = $Contract.python
$NodeVersion = $Contract.node
$FfmpegVersion = $Contract.ffmpeg
$TorchVariant = 'cpu'
if ($Contract.browserVersion -notmatch '^\d+\.\d+\.\d+\.\d+$' -or $Contract.browserArchiveSha256 -notmatch '^[a-f0-9]{64}$' -or $Contract.browserSha256 -notmatch '^[a-f0-9]{64}$') { throw 'Browser integrity contract is invalid.' }
$BrowserArchiveUrl = "https://storage.googleapis.com/chrome-for-testing-public/$($Contract.browserVersion)/win64/chrome-headless-shell-win64.zip"

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
$DataRoot = Join-Path $Root "data"
$StorageLocationPath = Join-Path $Root "storage-location.json"
if (Test-Path -LiteralPath $StorageLocationPath -PathType Leaf) {
    try {
        $StorageLocation = Get-Content -LiteralPath $StorageLocationPath -Raw | ConvertFrom-Json
        $ConfiguredDataRoot = [string]$StorageLocation.data_directory
        if ($StorageLocation.schema_version -ne 1 -or [string]::IsNullOrWhiteSpace($ConfiguredDataRoot)) {
            throw "Storage location configuration is incomplete or unsupported."
        }
        $DataRoot = [IO.Path]::GetFullPath($ConfiguredDataRoot)
        if ($DataRoot -notmatch '^[A-Za-z]:\\|^\\\\') {
            throw "Configured Clippy data directory must be an absolute Windows path."
        }
        if (-not (Test-Path -LiteralPath $DataRoot -PathType Container)) {
            throw "Configured Clippy data directory is unavailable: $DataRoot"
        }
    } catch {
        throw "Cannot load Clippy's configured data directory: $($_.Exception.Message)"
    }
}
$PythonDir = Join-Path $Runtime "python"
$NodeDir = Join-Path $Runtime "node"
$FfmpegDir = Join-Path $Runtime "ffmpeg\bin"
$ManifestPath = Join-Path $Root "runtime-manifest.json"
# Browser binaries are durable user data, not part of app\current. Updating the
# application payload must not force a multi-hundred-MB browser download.
$BrowserRoot = Join-Path $Root "browser"
$BrowserDir = Join-Path $BrowserRoot "headless-shell"
$BrowserExecutable = Join-Path $BrowserDir "chrome-headless-shell.exe"
$BrowserVersionFile = Join-Path $BrowserRoot "remotion-version.txt"
$LogDir = Join-Path $Root "logs"
$SetupLogPath = Join-Path $LogDir "runtime-setup.log"
$script:ScratchRoot = $null
$NvidiaDriverVersion = $null
$NvidiaGpuName = $null
$NvidiaComputeCapability = $null
$ForceCpuRuntime = $env:CLIPPY_FORCE_CPU_RUNTIME -eq "1"
if (-not $ForceCpuRuntime) {
    $Nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
$NvidiaSmiPath = if ($Nvidia) { $Nvidia.Source } else { $null }
if (-not $NvidiaSmiPath) {
    $NvidiaCandidates = @(
        (Join-Path $env:ProgramFiles "NVIDIA Corporation\NVSMI\nvidia-smi.exe"),
        (Join-Path $env:SystemRoot "System32\nvidia-smi.exe")
    )
    $NvidiaSmiPath = $NvidiaCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
if ($NvidiaSmiPath) {
    $NvidiaInfo = & $NvidiaSmiPath --query-gpu=name,driver_version,compute_cap --format=csv,noheader 2>$null
    if ($LASTEXITCODE -eq 0 -and $NvidiaInfo) {
        $NvidiaLine = @($NvidiaInfo) | Select-Object -First 1
        $NvidiaFields = ([string]$NvidiaLine).Split(',')
        if ($NvidiaFields.Count -ge 3) {
            $NvidiaGpuName = $NvidiaFields[0].Trim()
            $DriverText = $NvidiaFields[1].Trim()
            try { $NvidiaDriverVersion = [Version]$DriverText } catch { $NvidiaDriverVersion = $null }
            $ParsedComputeCapability = 0.0
            if ([double]::TryParse($NvidiaFields[2].Trim(), [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$ParsedComputeCapability)) {
                $NvidiaComputeCapability = $ParsedComputeCapability
            }
            # CUDA 12.8 GA requires Windows driver 570.65. The packaged
            # PyTorch CUDA runtime targets Volta/Turing-era and newer devices;
            # Blackwell is supported by cu128. Unsupported/unknown devices use
            # the CPU runtime instead of failing during the first CUDA kernel.
            if ($NvidiaDriverVersion -and $NvidiaDriverVersion -ge [Version]"570.65" -and
                $null -ne $NvidiaComputeCapability -and $NvidiaComputeCapability -ge 7.0) {
                $TorchVariant = "cuda"
            }
        }
    }
}
}
$PythonArchiveName = "python-$PythonVersion-embed-amd64.zip"
$PythonArchiveUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$PythonArchiveSha256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
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

function Remove-ClippyScratchRoot {
    $scratch = $script:ScratchRoot
    if (-not [string]::IsNullOrWhiteSpace($scratch) -and (Test-Path -LiteralPath $scratch -PathType Container)) {
        Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
    }
    $script:ScratchRoot = $null
}

trap {
    $Failure = $_
    try {
        Write-Stage ("SETUP FAILED: " + $Failure.Exception.Message)
        Write-Stage ("Failure location: " + $Failure.InvocationInfo.PositionMessage)
        Write-Stage ("Diagnostic log: " + $SetupLogPath)
    } catch { }
    try { Remove-ClippyScratchRoot } catch { }
    exit 1
}

Write-Stage "Runtime setup engine started."
Write-Stage ("Selected prebuilt Python runtime variant: " + $TorchVariant)
if ($ForceCpuRuntime) {
    Write-Stage "CPU runtime selection was explicitly forced by CLIPPY_FORCE_CPU_RUNTIME=1."
}

# Load script dependencies only after logging and the failure trap are active.
# This turns missing packaged helpers into a useful diagnostic instead of an
# early PowerShell dot-source failure with no Clippy setup context.
foreach ($Helper in @("runtime-manifest-state.ps1", "runtime-archive.ps1", "runtime-health.ps1")) {
    $HelperPath = Join-Path $PSScriptRoot $Helper
    if (-not (Test-Path -LiteralPath $HelperPath -PathType Leaf)) {
        throw "Application payload is incomplete. Missing required runtime helper: $HelperPath"
    }
}
. (Join-Path $PSScriptRoot "runtime-manifest-state.ps1")
. (Join-Path $PSScriptRoot "runtime-archive.ps1")
. (Join-Path $PSScriptRoot "runtime-health.ps1")
if ($NvidiaGpuName) {
    Write-Stage ("Detected NVIDIA GPU: " + $NvidiaGpuName + "; driver " + $NvidiaDriverVersion + "; compute capability " + $NvidiaComputeCapability)
    if ($TorchVariant -eq "cpu") {
        Write-Stage "NVIDIA driver or compute capability is not supported by the packaged CUDA 12.8 runtime; using the CPU runtime."
    }
}

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

            $ExpectedTotalBytes = $null
            if ($Status -eq 206) {
                $ContentRange = $Response.Headers["Content-Range"]
                if ($ContentRange -notmatch "^bytes\s+(\d+)-(\d+)/(\d+)$") {
                    throw "Server returned a missing or invalid Content-Range while resuming $Url"
                }
                $RangeStart = [long]$Matches[1]
                $RangeEnd = [long]$Matches[2]
                $ExpectedTotalBytes = [long]$Matches[3]
                if ($RangeStart -ne $Offset -or $RangeEnd -lt $RangeStart -or $ExpectedTotalBytes -le $RangeEnd) {
                    throw "Server returned an inconsistent Content-Range while resuming $Url"
                }
                $ExpectedResponseBytes = $RangeEnd - $RangeStart + 1
                if ($Response.ContentLength -ge 0 -and $Response.ContentLength -ne $ExpectedResponseBytes) {
                    throw "Server Content-Length does not match Content-Range while downloading $Url"
                }
            } elseif ($Response.ContentLength -ge 0) {
                $ExpectedTotalBytes = [long]$Response.ContentLength
            }

            $InputStream = $Response.GetResponseStream()
            $Mode = if ($Offset -gt 0 -and $Status -eq 206) { [IO.FileMode]::Append } else { [IO.FileMode]::Create }
            $OutputStream = [IO.File]::Open($Partial, $Mode, [IO.FileAccess]::Write, [IO.FileShare]::None)
            $Buffer = New-Object byte[] (1024 * 1024)
            $Downloaded = $Offset
            $LastReportedPercent = -1
            while (($Read = $InputStream.Read($Buffer, 0, $Buffer.Length)) -gt 0) {
                $OutputStream.Write($Buffer, 0, $Read)
                $Downloaded += $Read
                if ($ExpectedTotalBytes -gt 0) {
                    $Percent = [int][math]::Floor(($Downloaded * 100.0) / $ExpectedTotalBytes)
                    if ($Percent -ge $LastReportedPercent + 10) {
                        $LastReportedPercent = $Percent
                        Write-Stage ("{0}: {1}% ({2:N0}/{3:N0} bytes)." -f [IO.Path]::GetFileName($Destination), $Percent, $Downloaded, $ExpectedTotalBytes)
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
            if ($null -ne $ExpectedTotalBytes -and (Get-Item -LiteralPath $Partial).Length -ne $ExpectedTotalBytes) {
                throw "Download ended before the server-declared content length was received. Partial data has been preserved for resume."
            }
            Move-Item -LiteralPath $Partial -Destination $Destination -Force
            Write-Stage "Download complete: $([IO.Path]::GetFileName($Destination))."
            return
        } catch {
            $Message = $_.Exception.Message
            if ($OutputStream) { $OutputStream.Dispose(); $OutputStream = $null }
            if ($InputStream) { $InputStream.Dispose(); $InputStream = $null }
            if ($Response) { $Response.Close(); $Response = $null }

            # A missing release or asset is permanent until the publisher fixes
            # it. Do not waste time retrying an HTTP 404 three times.
            $ErrorResponse = $_.Exception.Response
            if ($ErrorResponse -is [System.Net.HttpWebResponse] -and [int]$ErrorResponse.StatusCode -eq 404) {
                $ErrorResponse.Close()
                throw "HTTP 404: required download asset was not found: $Url. Confirm that the matching Clippy release exists and contains this asset."
            }

            # A completed partial file can legitimately receive HTTP 416 when
            # the server is asked to resume exactly at EOF. Promote it and let
            # the caller's mandatory SHA-256 verification decide whether it is
            # usable. If it is longer than the server object, discard it and
            # retry from byte zero.
            $ErrorResponse = $_.Exception.Response
            if ($ErrorResponse -is [System.Net.HttpWebResponse]) {
                try {
                    if ([int]$ErrorResponse.StatusCode -eq 416) {
                        $RangeHeader = $ErrorResponse.Headers["Content-Range"]
                        if ($RangeHeader -match "^bytes\s+\*/(\d+)$") {
                            $ServerLength = [long]$Matches[1]
                            $PartialLength = if (Test-Path -LiteralPath $Partial) { (Get-Item -LiteralPath $Partial).Length } else { 0L }
                            if ($PartialLength -eq $ServerLength -and $ServerLength -gt 0) {
                                $ErrorResponse.Close()
                                Move-Item -LiteralPath $Partial -Destination $Destination -Force
                                Write-Stage "Resumed download was already complete; promoted the verified partial file."
                                return
                            }
                            if ($PartialLength -ne $ServerLength) {
                                Remove-Item -LiteralPath $Partial -Force -ErrorAction SilentlyContinue
                                Write-Stage "Discarded an inconsistent partial download after HTTP 416 and will restart from byte zero."
                            }
                        }
                    }
                } finally {
                    $ErrorResponse.Close()
                }
            }

            if ($Attempt -eq 3) { throw "Download failed after 3 attempts: $Url. $Message" }
            Write-Stage "Download interrupted; preserving valid partial data for resume. $Message"
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

# Prefer per-user temporary storage; inaccessible fixed volumes are skipped.
$ScratchCandidates = @([IO.Path]::GetTempPath()) + @([IO.DriveInfo]::GetDrives() |
    Where-Object { $_.IsReady -and $_.DriveType -eq [IO.DriveType]::Fixed } |
    Sort-Object AvailableFreeSpace -Descending | ForEach-Object { $_.RootDirectory.FullName })
foreach ($componentPath in @($PythonDir, $NodeDir, $FfmpegDir, $BrowserDir)) { Restore-ClippyComponent $componentPath }
foreach ($Required in @("app.py", "requirements.txt", "setup-runtime.ps1", "runtime-archive.ps1", "runtime-manifest-state.ps1", "VERSION", "bgutil-provider\server\build\generate_once.js")) {
    if (-not (Test-Path (Join-Path $App $Required))) {
        throw "Application payload is incomplete. Missing $Required in $App"
    }
}

$RequirementsHash = (Get-FileHash (Join-Path $App "requirements.txt") -Algorithm SHA256).Hash.ToLowerInvariant()
$RemotionPackagePath = Join-Path $App "render-service\node_modules\@remotion\renderer\package.json"
if (-not (Test-Path -LiteralPath $RemotionPackagePath -PathType Leaf)) {
    throw "Remotion renderer package is missing from the application payload: $RemotionPackagePath"
}
$RemotionVersion = (Get-Content -LiteralPath $RemotionPackagePath -Raw | ConvertFrom-Json).version
if ([string]::IsNullOrWhiteSpace($RemotionVersion)) { throw "Could not determine the bundled Remotion renderer version." }

# Build expected state from runtime contract
$ExpectedState = New-ClippyRuntimeState -PythonVersion $PythonVersion -PythonVariant $TorchVariant -NodeVersion $NodeVersion -FfmpegVersion $FfmpegVersion -BrowserVersion $RemotionVersion -RequirementsSha256 $RequirementsHash
if (Test-Path $ManifestPath) {
    try {
        $Existing = Get-Content $ManifestPath -Raw | ConvertFrom-Json
        $PythonExe = Join-Path $PythonDir "python.exe"
        $NodeExe = Join-Path $NodeDir "node.exe"
        $FfmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"
        $RuntimeFilesPresent =
            (Test-Path -LiteralPath $PythonExe -PathType Leaf) -and
            (Test-Path -LiteralPath $NodeExe -PathType Leaf) -and
            (Test-Path -LiteralPath $FfmpegExe -PathType Leaf) -and
            (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf) -and
            (Test-Path -LiteralPath $BrowserVersionFile -PathType Leaf) -and
            ((Get-Content -LiteralPath $BrowserVersionFile -Raw).Trim() -eq $RemotionVersion)
        $ManifestComponentsHealthy = $Existing.version -eq "1.0.0" -and $Existing.schema -eq 1
        foreach ($componentName in @("python", "node", "ffmpeg", "browser")) {
            $component = $Existing.components.$componentName
            if (-not $component -or -not $component.installed -or [string]::IsNullOrWhiteSpace([string]$component.version)) {
                $ManifestComponentsHealthy = $false
            }
        }
        $ManifestComponentsHealthy = $ManifestComponentsHealthy -and
            ($Existing.components.python.version -eq $PythonVersion) -and
            ($Existing.components.node.version -eq $NodeVersion) -and
            ($Existing.components.ffmpeg.version -eq $FfmpegVersion) -and
            ($Existing.components.browser.version -eq $RemotionVersion) -and
            ($Existing.requirementsSha256 -eq $RequirementsHash) -and
            ($Existing.browserSha256 -match "^[a-fA-F0-9]{64}$") -and
            ($Existing.browserSha256 -eq $Contract.browserSha256) -and
            ($Existing.browserSha256 -eq (Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant())
        if ($Existing.state -eq $ExpectedState -and $RuntimeFilesPresent -and $ManifestComponentsHealthy) {
            Write-Stage "Verifying installed Python, Node.js, FFmpeg, backend, and Remotion dependencies..."
            $PythonVersionHealthy = Test-ClippyExecutable $PythonExe '--version' "Python $PythonVersion"
            $NodeVersionHealthy = Test-ClippyExecutable $NodeExe '--version' "v$NodeVersion"
            $FfmpegHealthy = (Test-ClippyExecutable $FfmpegExe '-version') -and (Test-ClippyExecutable (Join-Path $FfmpegDir 'ffprobe.exe') '-version')
            $PythonHealthy = $false
            $NodeHealthy = $false
            $CudaDllDirectories = @()
            $CudaDllsHealthy = $true
            if ($TorchVariant -eq "cuda") {
                # Windows PyTorch CUDA wheels place their CUDA DLLs in torch\lib.
                $CudaDllDirectory = Join-Path $PythonDir "Lib\site-packages\torch\lib"
                $CudaDllDirectories = @($CudaDllDirectory)
                $RequiredCudaDlls = @(
                    (Join-Path $CudaDllDirectory "cublas64_12.dll"),
                    (Join-Path $CudaDllDirectory "cudnn64_9.dll"),
                    (Join-Path $CudaDllDirectory "cudart64_12.dll")
                )
                foreach ($dll in $RequiredCudaDlls) {
                    if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) { $CudaDllsHealthy = $false }
                }
                if ($CudaDllsHealthy) { $env:PATH = (($CudaDllDirectories -join ";") + ";" + $env:PATH) }
            }
            Push-Location $App
            try {
                $env:CLIPPY_DATA_DIR = $DataRoot
                $env:OUTPUT_DIR = Join-Path $DataRoot "output"
                $env:UPLOAD_DIR = Join-Path $DataRoot "uploads"
                $env:CLIPPY_SETTINGS_PATH = Join-Path $Root "settings.json"
                $env:CLIPPY_MODELS_DIR = Join-Path $DataRoot "models"
                $env:REFERENCE_TEMPLATES_DIR = Join-Path $DataRoot 'reference_templates'
                $PythonHealthScript = "import app, torch, faster_whisper"
                if ($TorchVariant -eq "cuda") {
                    $PythonHealthScript += "; import ctranslate2; assert torch.version.cuda and torch.version.cuda.startswith('12.8'); assert torch.cuda.is_available(); x=torch.ones((64,64),device='cuda'); y=x @ x; torch.cuda.synchronize(); assert float(y[0,0].item()) == 64.0; assert ctranslate2.get_cuda_device_count() > 0"
                } else {
                    $PythonHealthScript += "; assert torch.version.cuda is None"
                }
                $PythonHealthy = $PythonVersionHealthy -and $CudaDllsHealthy -and (Test-ClippyExecutable $PythonExe ('-c "' + $PythonHealthScript + '"') '' 120)
                $env:REMOTION_BROWSER_EXECUTABLE = $BrowserExecutable
                $BrowserCheck = "import('@remotion/renderer').then(async m => { await m.ensureBrowser({browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE}); }).catch(e => { console.error(e); process.exit(1); });"
                Push-Location (Join-Path $App "render-service")
                try {
                    $BrowserPackageHealthy = Test-ClippyExecutable $NodeExe ('-e "' + $BrowserCheck + '"')
                    $NodeHealthy = ($NodeVersionHealthy -and $BrowserPackageHealthy) -and (Test-ClippyExecutable $BrowserExecutable '--headless --disable-gpu --dump-dom about:blank')
                } finally {
                    Pop-Location
                }
            } finally {
                Pop-Location
            }
            if ($PythonHealthy -and $NodeHealthy -and $FfmpegHealthy) {
                Write-Stage "Managed runtimes and application dependencies are healthy. No downloads needed."
                Remove-ClippyScratchRoot
                exit 0
            }
            Write-Stage "A runtime health check failed; repairing dependencies."
        }
    } catch {
        Write-Stage "Previous runtime manifest is invalid; repairing managed runtimes."
    }
}

$script:ScratchRoot = New-ClippyScratch $ScratchCandidates -RuntimeRoot $Root
$ScratchDrive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($ScratchRoot))
$env:TEMP = $ScratchRoot
$env:TMP = $ScratchRoot
$env:PIP_CACHE_DIR = Join-Path $ScratchRoot 'pip-cache'
Write-Stage ("Using " + $ScratchRoot + " for temporary setup files; managed runtimes remain in " + $Root)
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
if ($AppVersion -notmatch "^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$") { throw "Application VERSION file is missing or invalid." }

$PythonRuntimeName = "clippy-python-$TorchVariant-$AppVersion.zip"
$PythonRuntimeArchive = Join-Path $Downloads $PythonRuntimeName
$PythonRuntimeManifestName = "clippy-python-$TorchVariant.manifest.json"
$PythonRuntimeManifestUrl = "https://github.com/helalxp/clippy/releases/download/v$AppVersion/$PythonRuntimeManifestName"
$PythonRuntimeReleaseBaseUrl = "https://github.com/helalxp/clippy/releases/download/v$AppVersion"
$LocalRuntimeArchive = $env:CLIPPY_PYTHON_RUNTIME_ARCHIVE
$LocalRuntimeChecksum = $env:CLIPPY_PYTHON_RUNTIME_CHECKSUM

# Local archive overrides remain available for developer diagnostics. Customer
# installs use only the manifest and assets from the exact matching release.
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
    $PythonRuntimeManifestPath = Join-Path $Downloads "$AppVersion-$PythonRuntimeManifestName"
    Download-File $PythonRuntimeManifestUrl $PythonRuntimeManifestPath
    $ManifestParsed = $false
    for ($ManifestAttempt = 1; $ManifestAttempt -le 2; $ManifestAttempt++) {
        try {
            $RuntimeManifest = Get-Content -LiteralPath $PythonRuntimeManifestPath -Raw | ConvertFrom-Json
            $ManifestParsed = $true
            break
        } catch {
            Remove-Item -LiteralPath $PythonRuntimeManifestPath -Force -ErrorAction SilentlyContinue
            if ($ManifestAttempt -eq 2) {
                throw "The runtime manifest downloaded from release v$AppVersion is not valid JSON: $PythonRuntimeManifestUrl"
            }
            Write-Stage "Cached runtime manifest was invalid; downloading it again."
            Download-File $PythonRuntimeManifestUrl $PythonRuntimeManifestPath
        }
    }
    if (-not $ManifestParsed) { throw "Could not read the runtime manifest for release v$AppVersion." }
    Assert-ClippyRuntimeArchiveManifest -Manifest $RuntimeManifest -ExpectedApplicationVersion $AppVersion -ExpectedVariant $TorchVariant | Out-Null

    foreach ($Part in @($RuntimeManifest.parts)) {
        $PartName = [string]$Part.name
        $PartUrl = "$PythonRuntimeReleaseBaseUrl/$PartName"
        $PartPath = Join-Path $Downloads $PartName
        $PartHealthy = $false
        if (Test-Path -LiteralPath $PartPath -PathType Leaf) {
            $PartInfo = Get-Item -LiteralPath $PartPath
            if ($PartInfo.Length -eq [long]$Part.size -and
                (Get-ClippyFileSha256 $PartPath) -eq ([string]$Part.sha256).ToLowerInvariant()) {
                $PartHealthy = $true
                Write-Stage "Reusing verified runtime part $PartName."
            } else {
                Write-Stage "Cached runtime part $PartName failed verification; downloading it again."
                Remove-Item -LiteralPath $PartPath -Force
            }
        }
        if (-not $PartHealthy) {
            Download-File $PartUrl $PartPath
            $PartInfo = Get-Item -LiteralPath $PartPath
            if ($PartInfo.Length -ne [long]$Part.size -or
                (Get-ClippyFileSha256 $PartPath) -ne ([string]$Part.sha256).ToLowerInvariant()) {
                Remove-Item -LiteralPath $PartPath -Force -ErrorAction SilentlyContinue
                throw "Downloaded runtime part failed size or SHA-256 verification: $PartName"
            }
        }
    }

    Write-Stage "Reconstructing the verified $TorchVariant Python runtime archive from $($RuntimeManifest.partCount) release asset(s)..."
    Join-ClippyRuntimeArchiveParts -Manifest $RuntimeManifest -PartsDirectory $Downloads -Destination $PythonRuntimeArchive | Out-Null
    $PythonRuntimeVerified = $true
}
if (-not $PythonRuntimeVerified) { throw "Could not verify the downloaded Python runtime." }

$PythonStage = Join-Path $Runtime "python.installing"
if (Test-Path $PythonStage) { Remove-Item $PythonStage -Recurse -Force }
Write-Stage "Extracting the verified $TorchVariant Python runtime..."
Expand-ArchiveFast $PythonRuntimeArchive $PythonStage
$StagedPython = Join-Path $PythonStage "python.exe"
if (-not (Test-Path -LiteralPath $StagedPython -PathType Leaf)) {
    throw "Verified Python runtime archive does not contain python.exe at its root."
}
$StagedVersion = (& $StagedPython --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Packaged Python executable failed its version check: $StagedVersion"
}
Assert-ClippyPythonRuntimeVersion -Actual $StagedVersion -Expected $PythonVersion
$StagedImportCheck = "import torch, torchvision, fastapi, uvicorn, faster_whisper; print('torch=' + torch.__version__); print('cuda_build=' + str(torch.version.cuda))"
& $StagedPython -c $StagedImportCheck
if ($LASTEXITCODE -ne 0) { throw "Packaged Python dependency verification failed." }
if ($TorchVariant -eq "cuda") {
    & $StagedPython -c "import torch; assert torch.version.cuda is not None, 'CUDA-enabled PyTorch is missing'"
    if ($LASTEXITCODE -ne 0) { throw "Selected CUDA runtime does not contain CUDA-enabled PyTorch." }
}

# Activate only after archive hash, Python version, and critical imports pass.
Install-ClippyComponent $PythonStage $PythonDir {
    param($dir)
    Test-ClippyExecutable (Join-Path $dir 'python.exe') '-c "import torch,fastapi,faster_whisper"' '' 120
}
$PythonExe = Join-Path $PythonDir 'python.exe'

# Node's archive is checked against the SHA-256 value published alongside the
# official Node.js release archive.
$NodeExe = Join-Path $NodeDir "node.exe"
$ExistingNodeHealthy = Test-ClippyExecutable $NodeExe '--version' "v$NodeVersion"
if (-not $ExistingNodeHealthy) {
    Write-Stage 'Managed Node.js runtime requires replacement.'
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
    $NodeStage = "$NodeDir.installing"
    if (Test-Path -LiteralPath $NodeStage) { Remove-Item -LiteralPath $NodeStage -Recurse -Force }
    Copy-Item -LiteralPath $ExtractedRoot -Destination $NodeStage -Recurse
    Install-ClippyComponent $NodeStage $NodeDir { param($dir) Test-ClippyExecutable (Join-Path $dir 'node.exe') '--version' "v$NodeVersion" }
    Remove-Item $Extract -Recurse -Force
}
$InstalledNodeVersion = (& $NodeExe --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $InstalledNodeVersion.TrimStart([char]"v") -ne $NodeVersion) {
    throw "Managed Node.js runtime version check failed. Expected $NodeVersion, found $InstalledNodeVersion."
}

# FFmpeg is downloaded from the Windows builds publisher and verified against
# the publisher's SHA-256 sidecar before extraction.
$FfmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"
$FfmpegCheck = { param($dir) (Test-ClippyExecutable (Join-Path $dir 'ffmpeg.exe') '-version') -and (Test-ClippyExecutable (Join-Path $dir 'ffprobe.exe') '-version') }
$ExistingFfmpegHealthy = & $FfmpegCheck $FfmpegDir
if (-not $ExistingFfmpegHealthy) {
    Write-Stage 'Managed FFmpeg runtime requires replacement.'
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
    $FfmpegStage = "$FfmpegDir.installing"
    if (Test-Path -LiteralPath $FfmpegStage) { Remove-Item -LiteralPath $FfmpegStage -Recurse -Force }
    Copy-Item -LiteralPath $SourceBin -Destination $FfmpegStage -Recurse
    Install-ClippyComponent $FfmpegStage $FfmpegDir $FfmpegCheck
    Remove-Item $Extract -Recurse -Force
}
& $FfmpegExe -version
if ($LASTEXITCODE -ne 0) { throw "Managed FFmpeg runtime failed its version check." }

if ($TorchVariant -eq "cuda") {
    # Windows PyTorch CUDA wheels place their CUDA DLLs in torch\lib.
    $CudaDllDirectory = Join-Path $PythonDir "Lib\site-packages\torch\lib"
    $CudaDllDirectories = @($CudaDllDirectory)
    $RequiredCudaDlls = @(
        (Join-Path $CudaDllDirectory "cublas64_12.dll"),
        (Join-Path $CudaDllDirectory "cudnn64_9.dll"),
        (Join-Path $CudaDllDirectory "cudart64_12.dll")
    )
    foreach ($dll in $RequiredCudaDlls) {
        if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) {
            throw "CUDA runtime is missing a required DLL for PyTorch/CTranslate2: $dll"
        }
    }
    $env:PATH = (($CudaDllDirectories -join ";") + ";" + $env:PATH)
}

Write-Stage "Verifying backend imports..."
Push-Location $App
try {
    $env:CLIPPY_DATA_DIR = $DataRoot
    $env:OUTPUT_DIR = Join-Path $DataRoot "output"
    $env:UPLOAD_DIR = Join-Path $DataRoot "uploads"
    $env:CLIPPY_SETTINGS_PATH = Join-Path $Root "settings.json"
    $env:CLIPPY_MODELS_DIR = Join-Path $DataRoot "models"
    $env:REFERENCE_TEMPLATES_DIR = Join-Path $DataRoot 'reference_templates'
    & $PythonExe -c "import app; import torch; import faster_whisper; import ctranslate2; print('Backend imports OK; torch CUDA:', torch.cuda.is_available())"
    if ($LASTEXITCODE -ne 0) { throw "Backend import verification failed. Check the Python dependency log." }
    if ($TorchVariant -eq "cuda") {
        Write-Stage "Running a real CUDA kernel and faster-whisper device capability check..."
        & $PythonExe -c "import torch, ctranslate2; assert torch.version.cuda and torch.version.cuda.startswith('12.8'), f'Expected CUDA 12.8, got {torch.version.cuda}'; assert torch.cuda.is_available(), 'PyTorch cannot initialize the NVIDIA device'; x=torch.ones((64,64),device='cuda'); y=x @ x; torch.cuda.synchronize(); assert float(y[0,0].item()) == 64.0, 'CUDA kernel produced an unexpected result'; count=ctranslate2.get_cuda_device_count(); assert count > 0, 'CTranslate2/faster-whisper cannot see a CUDA device'; print('CUDA kernel OK:', torch.cuda.get_device_name(0), '| CTranslate2 devices:', count)"
        if ($LASTEXITCODE -ne 0) {
            throw "CUDA runtime verification failed. Clippy will not mark an unusable CUDA installation as healthy. Check the NVIDIA driver, CUDA DLL paths, and GPU compatibility in the setup log."
        }
    }
} finally {
    Pop-Location
}

Write-Stage "Verifying the persistent Remotion browser runtime..."
$InstalledBrowserVersion = if (Test-Path -LiteralPath $BrowserVersionFile) { (Get-Content -LiteralPath $BrowserVersionFile -Raw).Trim() } else { "" }
$BrowserNeedsInstall = -not (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf) -or $InstalledBrowserVersion -ne $RemotionVersion
if (-not $BrowserNeedsInstall) {
    $BrowserNeedsInstall = ((Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Contract.browserSha256) -or -not (Test-ClippyExecutable $BrowserExecutable '--headless --disable-gpu --dump-dom about:blank')
}
if ($BrowserNeedsInstall) {
    Write-Stage "Installing or repairing the Remotion browser for renderer version $RemotionVersion..."
    # Google's headless shell is unsigned. Trust the publisher's versioned HTTPS
    # archive only after matching the immutable hashes shipped in the payload.
    $BrowserArchive = Join-Path $Downloads "chrome-headless-shell-$($Contract.browserVersion)-win64.zip"
    Download-File $BrowserArchiveUrl $BrowserArchive
    try { Assert-Sha256 $BrowserArchive $Contract.browserArchiveSha256 } catch {
        Remove-Item -LiteralPath $BrowserArchive -Force
        Download-File $BrowserArchiveUrl $BrowserArchive
        Assert-Sha256 $BrowserArchive $Contract.browserArchiveSha256
    }
    $BrowserExtract = Join-Path $ScratchRoot 'browser-extract'
    Expand-ArchiveFast $BrowserArchive $BrowserExtract
    $DownloadedBrowserDir = Join-Path $BrowserExtract 'chrome-headless-shell-win64'
    Assert-Sha256 (Join-Path $DownloadedBrowserDir 'chrome-headless-shell.exe') $Contract.browserSha256
    $BrowserStage = "$BrowserDir.installing"
    if (Test-Path -LiteralPath $BrowserStage) { Remove-Item -LiteralPath $BrowserStage -Recurse -Force }
    Copy-Item -LiteralPath $DownloadedBrowserDir -Destination $BrowserStage -Recurse
    Install-ClippyComponent $BrowserStage $BrowserDir {
        param($dir)
        $exe = Join-Path $dir 'chrome-headless-shell.exe'
        ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Contract.browserSha256) -and (Test-ClippyExecutable $exe '--headless --disable-gpu --dump-dom about:blank')
    }
    Remove-Item -LiteralPath $BrowserExtract -Recurse -Force
    [System.IO.File]::WriteAllText($BrowserVersionFile, $RemotionVersion, [System.Text.UTF8Encoding]::new($false))
} else {
    Write-Stage "Reusing the browser already installed for Remotion $RemotionVersion."
}

if (-not (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf)) {
    throw "Persistent Remotion browser executable is missing: $BrowserExecutable"
}
Assert-Sha256 $BrowserExecutable $Contract.browserSha256
$BrowserSha256 = (Get-FileHash -LiteralPath $BrowserExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
$env:REMOTION_BROWSER_EXECUTABLE = $BrowserExecutable
$BrowserValidation = "import('@remotion/renderer').then(async m => { await m.ensureBrowser({browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE}); console.log('Persistent Remotion browser ready'); }).catch(e => { console.error(e); process.exit(1); });"
Push-Location (Join-Path $App "render-service")
try {
    & $NodeExe -e $BrowserValidation
    if ($LASTEXITCODE -ne 0) { throw "Persistent Remotion browser validation failed." }
} finally {
    Pop-Location
}


New-Item -ItemType Directory -Path (Split-Path $ManifestPath -Parent) -Force | Out-NULL
$Manifest = @{
    version = "1.0.0"
    components = @{
        python = @{ version = $PythonVersion; installed = $true }
        node = @{ version = $NodeVersion; installed = $true }
        ffmpeg = @{ version = $FfmpegVersion; installed = $true }
        browser = @{ version = $RemotionVersion; installed = $true }
    }
    schema = 1
    state = $ExpectedState
    installedAt = (Get-Date).ToUniversalTime().ToString("o")
    requirementsSha256 = $RequirementsHash
    browserSha256 = $BrowserSha256
    gpuMode = if ($TorchVariant -eq "cuda") { "cuda128" } else { "cpu" }
}
$ManifestJson = $Manifest | ConvertTo-Json -Depth 5
# Windows PowerShell 5.1 writes a UTF-8 BOM with Set-Content -Encoding UTF8.
# serde_json expects plain JSON, so write UTF-8 explicitly without a BOM.
[System.IO.File]::WriteAllText($ManifestPath, $ManifestJson, [System.Text.UTF8Encoding]::new($false))
# Remove the multi-gigabyte Python archive and release parts only after the
# complete runtime setup has succeeded. If setup fails earlier, verified parts
# remain available for a retry without downloading them again.
if ([string]::IsNullOrWhiteSpace($LocalRuntimeArchive) -and $RuntimeManifest) {
    Remove-Item -LiteralPath $PythonRuntimeArchive, $PythonRuntimeManifestPath -Force -ErrorAction SilentlyContinue
    foreach ($Part in @($RuntimeManifest.parts)) {
        Remove-Item -LiteralPath (Join-Path $Downloads ([string]$Part.name)) -Force -ErrorAction SilentlyContinue
    }
}
Remove-ClippyScratchRoot
Write-Stage "Runtime setup completed successfully."
} finally {
    $InstallMutex.ReleaseMutex(); $InstallMutex.Dispose()
    if ($DesktopMutex) { $DesktopMutex.ReleaseMutex(); $DesktopMutex.Dispose() }
}
