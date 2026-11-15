$ErrorActionPreference = "Stop"
# The desktop runtime setup is intentionally hosted by Windows PowerShell 5.1.
# When Clippy is launched from PowerShell 7, the inherited PSModulePath can
# point only at PowerShell 7 modules. Windows PowerShell then cannot auto-load
# its own built-in modules (for example Get-FileHash and Expand-Archive).
# Prepend this host's system module directory while preserving any other
# module directories already configured by the user.
$WindowsPowerShellModulePath = [System.IO.Path]::Combine($PSHOME, "Modules")
if ([System.IO.Directory]::Exists($WindowsPowerShellModulePath)) {
    $CurrentModulePath = [string]$env:PSModulePath
    $HasWindowsPowerShellModules = $false
    foreach ($ModulePathEntry in $CurrentModulePath.Split(';')) {
        if ([string]::Equals($ModulePathEntry.Trim(), $WindowsPowerShellModulePath, [System.StringComparison]::OrdinalIgnoreCase)) {
            $HasWindowsPowerShellModules = $true
            break
        }
    }
    if (-not $HasWindowsPowerShellModules) {
        if ([string]::IsNullOrWhiteSpace($CurrentModulePath)) {
            $env:PSModulePath = $WindowsPowerShellModulePath
        } else {
            $env:PSModulePath = $WindowsPowerShellModulePath + ';' + $CurrentModulePath
        }
    }
}

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
    [System.Environment]::SetEnvironmentVariable($Name, $null, [System.EnvironmentVariableTarget]::Process)
}
$env:PYTHONNOUSERSITE = "1"
$env:PYTHONUTF8 = "1"

$Root = [System.IO.Path]::Combine($env:LOCALAPPDATA, "Clippy")
$App = [System.IO.Path]::Combine($Root, "app", "current")
$Runtime = [System.IO.Path]::Combine($Root, "runtime")
$Downloads = [System.IO.Path]::Combine($Root, "downloads")
$PythonDir = [System.IO.Path]::Combine($Runtime, "python")
$NodeDir = [System.IO.Path]::Combine($Runtime, "node")
$FfmpegDir = [System.IO.Path]::Combine($Runtime, "ffmpeg", "bin")
$ManifestPath = [System.IO.Path]::Combine($Root, "runtime-manifest.json")
# Browser binaries are durable user data, not part of app\current. Updating the
# application payload must not force a multi-hundred-MB browser download.
$BrowserRoot = [System.IO.Path]::Combine($Root, "browser")
$BrowserDir = [System.IO.Path]::Combine($BrowserRoot, "headless-shell")
$BrowserExecutable = [System.IO.Path]::Combine($BrowserDir, "chrome-headless-shell.exe")
$BrowserVersionFile = [System.IO.Path]::Combine($BrowserRoot, "remotion-version.txt")
$LogDir = [System.IO.Path]::Combine($Root, "logs")
$SetupLogPath = [System.IO.Path]::Combine($LogDir, "runtime-setup.log")
$script:ScratchRoot = $null

$PythonVersion = "3.12.10"
$TorchVariant = "cpu"
$NvidiaDriverVersion = $null
$NvidiaGpuName = $null
$NvidiaComputeCapability = $null
$ForceCpuRuntime = $env:CLIPPY_FORCE_CPU_RUNTIME -eq "1"
if (-not $ForceCpuRuntime) {
    $Nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
$NvidiaSmiPath = if ($Nvidia) { $Nvidia.Source } else { $null }
if (-not $NvidiaSmiPath) {
    $NvidiaCandidates = @(
        [System.IO.Path]::Combine($env:ProgramFiles, "NVIDIA Corporation\NVSMI\nvidia-smi.exe"),
        [System.IO.Path]::Combine($env:SystemRoot, "System32\nvidia-smi.exe")
    )
    foreach ($Candidate in $NvidiaCandidates) {
        if ([System.IO.File]::Exists($Candidate)) {
            $NvidiaSmiPath = $Candidate
            break
        }
    }
}
if ($NvidiaSmiPath) {
    $NvidiaInfo = & $NvidiaSmiPath --query-gpu=name,driver_version,compute_cap --format=csv,noheader 2>$null
    if ($LASTEXITCODE -eq 0 -and $NvidiaInfo) {
        $NvidiaLine = [string](@($NvidiaInfo)[0])
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
$NodeVersion = "22.23.3"
$NodeArchiveName = "node-v$NodeVersion-win-x64.zip"
$NodeArchiveUrl = "https://nodejs.org/dist/v$NodeVersion/$NodeArchiveName"
$NodeChecksumsUrl = "https://nodejs.org/dist/v$NodeVersion/SHASUMS256.txt"
$FfmpegArchiveName = "ffmpeg-release-essentials.zip"
$FfmpegArchiveUrl = "https://www.gyan.dev/ffmpeg/builds/$FfmpegArchiveName"
$FfmpegChecksumUrl = "$FfmpegArchiveUrl.sha256"
$VcRedistUrl = "https://aka.ms/vs/17/release/vc_redist.x64.exe"

[System.IO.Directory]::CreateDirectory($LogDir) | Out-Null
function Write-Stage([string]$Message) {
    $Timestamp = [DateTime]::Now.ToString("yyyy-MM-dd HH:mm:ss", [System.Globalization.CultureInfo]::InvariantCulture)
    $Line = "[{0}] [Clippy setup] {1}" -f $Timestamp, $Message
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
Write-Stage ("PowerShell host version: " + $PSVersionTable.PSVersion + "; PSHOME: " + $PSHOME)
Write-Stage ("Process LOCALAPPDATA: " + $env:LOCALAPPDATA)
Write-Stage ("Resolved Clippy root: " + $Root)
Write-Stage ("Resolved application payload: " + $App)
Write-Stage ("Resolved runtime directory: " + $Runtime)
Write-Stage ("Resolved Python executable: " + (Join-Path $PythonDir "python.exe"))
Write-Stage ("Resolved setup log: " + $SetupLogPath)
if (-not [string]::IsNullOrWhiteSpace($env:CLIPPY_SMOKE_DIAGNOSTICS_PATH)) {
    Write-Stage ("Smoke-test child context log: " + $env:CLIPPY_SMOKE_DIAGNOSTICS_PATH)
}
Write-Stage ("Selected prebuilt Python runtime variant: " + $TorchVariant)
if ($ForceCpuRuntime) {
    Write-Stage "CPU runtime selection was explicitly forced by CLIPPY_FORCE_CPU_RUNTIME=1."
}

# Load script dependencies only after logging and the failure trap are active.
# This turns missing packaged helpers into a useful diagnostic instead of an
# early PowerShell dot-source failure with no Clippy setup context.
foreach ($Helper in @("runtime-manifest-state.ps1", "runtime-archive.ps1")) {
    $HelperPath = [System.IO.Path]::Combine($PSScriptRoot, $Helper)
    if (-not [System.IO.File]::Exists($HelperPath)) {
        throw "Application payload is incomplete. Missing required runtime helper: $HelperPath"
    }
}
# Import built-in modules by absolute manifest path. The parent app may have been
# launched from PowerShell 7 or another host with a restricted PSModulePath, and
# -NoProfile deliberately prevents relying on a user's module-loading profile.
foreach ($ModuleName in @("Microsoft.PowerShell.Management", "Microsoft.PowerShell.Utility", "Microsoft.PowerShell.Security")) {
    $ModuleManifest = [System.IO.Path]::Combine($WindowsPowerShellModulePath, $ModuleName, ($ModuleName + ".psd1"))
    if (-not [System.IO.File]::Exists($ModuleManifest)) {
        throw "Required Windows PowerShell module is missing: $ModuleManifest"
    }
    Import-Module -Name $ModuleManifest -Force -ErrorAction Stop
}
Write-Stage ("Loaded built-in PowerShell utility and security modules from " + $WindowsPowerShellModulePath)

. (Join-Path $PSScriptRoot "runtime-manifest-state.ps1")
. (Join-Path $PSScriptRoot "runtime-archive.ps1")
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
    # Keep ZIP extraction independent from the optional PowerShell Archive module.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory([IO.Path]::GetFullPath($Archive), [IO.Path]::GetFullPath($Destination))
}

function Assert-Sha256([string]$Path, [string]$Expected) {
    $Actual = Get-ClippyFileSha256 -Path $Path
    if ($Actual -ne $Expected.ToLowerInvariant()) {
        throw "SHA-256 verification failed for $Path. Expected $Expected, got $Actual"
    }
}

function Get-ClippyAvailableFreeBytes([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "Cannot inspect free disk space without a path."
    }
    $fullPath = [IO.Path]::GetFullPath($Path)
    $volumeRoot = [IO.Path]::GetPathRoot($fullPath)
    if ([string]::IsNullOrWhiteSpace($volumeRoot)) {
        throw "Cannot determine the storage volume for $fullPath."
    }
    $drive = New-Object System.IO.DriveInfo($volumeRoot)
    if (-not $drive.IsReady) {
        throw "Storage volume $volumeRoot is not ready."
    }
    return [long]$drive.AvailableFreeSpace
}

New-Item -ItemType Directory -Path $Runtime, $Downloads -Force | Out-Null

# Use a user-writable temporary parent, never the root of a volume. Prefer
# CLIPPY_TEMP_DIR (an explicit administrator choice), then TEMP/TMP, then the
# platform temp and LOCALAPPDATA. Probe each candidate with a real write before
# selecting it, and prefer the candidate with the most free space.
$ScratchPrefix = "ClippySetupTemp-" + $env:USERNAME + "-"
$ScratchCandidates = New-Object System.Collections.Generic.List[object]
$SeenScratchParents = @{}
$ScratchProbeErrors = New-Object System.Collections.Generic.List[string]
foreach ($CandidatePath in @($env:CLIPPY_TEMP_DIR, $env:TEMP, $env:TMP, [IO.Path]::GetTempPath(), $env:LOCALAPPDATA)) {
    if ([string]::IsNullOrWhiteSpace([string]$CandidatePath)) { continue }
    try {
        $CandidateFullPath = [IO.Path]::GetFullPath([string]$CandidatePath)
        $CandidateVolumeRoot = [IO.Path]::GetPathRoot($CandidateFullPath)
        if ([string]::IsNullOrWhiteSpace($CandidateVolumeRoot) -or
            [string]::Equals($CandidateFullPath.TrimEnd([char[]]@('\', '/')), $CandidateVolumeRoot.TrimEnd([char[]]@('\', '/')), [System.StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        if ($SeenScratchParents.ContainsKey($CandidateFullPath)) { continue }
        $SeenScratchParents[$CandidateFullPath] = $true
        [System.IO.Directory]::CreateDirectory($CandidateFullPath) | Out-Null
        $ProbeDirectory = Join-Path $CandidateFullPath (".clippy-write-probe-" + $PID + "-" + [guid]::NewGuid().ToString("N"))
        [System.IO.Directory]::CreateDirectory($ProbeDirectory) | Out-Null
        $ProbeFile = Join-Path $ProbeDirectory "probe.txt"
        [System.IO.File]::WriteAllText($ProbeFile, "Clippy temporary storage probe")
        [System.IO.File]::Delete($ProbeFile)
        [System.IO.Directory]::Delete($ProbeDirectory)
        $CandidateDrive = New-Object System.IO.DriveInfo($CandidateVolumeRoot)
        if ($CandidateDrive.IsReady -and $CandidateDrive.DriveType -eq [System.IO.DriveType]::Fixed) {
            $ScratchCandidates.Add([pscustomobject]@{
                Path = $CandidateFullPath
                Drive = $CandidateDrive
                FreeBytes = [long]$CandidateDrive.AvailableFreeSpace
            })
        } else {
            $ScratchProbeErrors.Add("$CandidateFullPath is not on a ready local fixed drive.")
        }
    } catch {
        $ScratchProbeErrors.Add("$CandidatePath is not writable: $($_.Exception.Message)")
    }
}
$ScratchCandidate = $ScratchCandidates | Sort-Object -Property FreeBytes -Descending | Select-Object -First 1
if (-not $ScratchCandidate) {
    throw ("No writable temporary directory on a local fixed drive was found. Set TEMP/TMP or CLIPPY_TEMP_DIR to a writable location. " + ($ScratchProbeErrors -join " | "))
}
$ScratchParent = [string]$ScratchCandidate.Path
$ScratchDrive = $ScratchCandidate.Drive
# Remove only abandoned Clippy scratch folders inside the verified user-writable
# parent. Never enumerate or create installation temp folders at a drive root.
Get-ChildItem -LiteralPath $ScratchParent -Directory -Filter "$ScratchPrefix*" -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddHours(-24) } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
$script:ScratchRoot = Join-Path $ScratchParent ($ScratchPrefix + $PID + "-" + [guid]::NewGuid().ToString("N"))
[System.IO.Directory]::CreateDirectory($script:ScratchRoot) | Out-Null
$env:TEMP = $script:ScratchRoot
$env:TMP = $script:ScratchRoot
$env:PIP_CACHE_DIR = Join-Path $script:ScratchRoot "pip-cache"
Write-Stage ("Using writable temporary directory " + $script:ScratchRoot + " (" + $ScratchDrive.Name + ", " + [math]::Round($ScratchDrive.AvailableFreeSpace / 1GB, 1) + " GB free); managed runtimes remain in " + $Root)
foreach ($Required in @("app.py", "requirements.txt", "setup-runtime.ps1", "runtime-archive.ps1", "runtime-manifest-state.ps1", "VERSION", "bgutil-provider\server\build\generate_once.js")) {
    if (-not (Test-Path (Join-Path $App $Required))) {
        throw "Application payload is incomplete. Missing $Required in $App"
    }
}

$RequirementsHash = Get-ClippyFileSha256 -Path (Join-Path $App "requirements.txt")
$RemotionPackagePath = Join-Path $App "render-service\node_modules\@remotion\renderer\package.json"
if (-not (Test-Path -LiteralPath $RemotionPackagePath -PathType Leaf)) {
    throw "Remotion renderer package is missing from the application payload: $RemotionPackagePath"
}
$RemotionVersion = (Get-Content -LiteralPath $RemotionPackagePath -Raw | ConvertFrom-Json).version
if ([string]::IsNullOrWhiteSpace($RemotionVersion)) { throw "Could not determine the bundled Remotion renderer version." }
$ExpectedState = New-ClippyRuntimeState -PythonVersion $PythonVersion -PythonVariant $TorchVariant -NodeVersion $NodeVersion -FfmpegVersion "gyan-release-essentials" -BrowserVersion $RemotionVersion -RequirementsSha256 $RequirementsHash
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
            ($Existing.components.ffmpeg.version -eq "gyan-release-essentials") -and
            ($Existing.components.browser.version -eq $RemotionVersion) -and
            ($Existing.requirementsSha256 -eq $RequirementsHash) -and
            ($Existing.browserSha256 -match "^[a-fA-F0-9]{64}$") -and
            ($Existing.browserSha256 -eq (Get-ClippyFileSha256 -Path $BrowserExecutable))
        if ($Existing.state -eq $ExpectedState -and $RuntimeFilesPresent -and $ManifestComponentsHealthy) {
            Write-Stage "Verifying installed Python, Node.js, FFmpeg, backend, and Remotion dependencies..."
            $PythonVersionOutput = (& $PythonExe --version 2>&1 | Out-String).Trim()
            $PythonVersionHealthy = ($LASTEXITCODE -eq 0 -and $PythonVersionOutput -eq "Python $PythonVersion")
            $NodeVersionOutput = (& $NodeExe --version 2>&1 | Out-String).Trim()
            $NodeVersionHealthy = ($LASTEXITCODE -eq 0 -and $NodeVersionOutput.TrimStart('v') -eq $NodeVersion)
            & $FfmpegExe -version *> $null
            $FfmpegHealthy = ($LASTEXITCODE -eq 0)
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
                $env:OUTPUT_DIR = Join-Path $Root "data\output"
                $env:UPLOAD_DIR = Join-Path $Root "data\uploads"
                $env:CLIPPY_SETTINGS_PATH = Join-Path $Root "settings.json"
                $env:CLIPPY_MODELS_DIR = Join-Path $Root "data\models"
                $PythonHealthScript = "import app, torch, faster_whisper"
                if ($TorchVariant -eq "cuda") {
                    $PythonHealthScript += "; import ctranslate2; assert torch.version.cuda and torch.version.cuda.startswith('12.8'); assert torch.cuda.is_available(); x=torch.ones((64,64),device='cuda'); y=x @ x; torch.cuda.synchronize(); assert float(y[0,0].item()) == 64.0; assert ctranslate2.get_cuda_device_count() > 0"
                } else {
                    $PythonHealthScript += "; assert torch.version.cuda is None"
                }
                & $PythonExe -c $PythonHealthScript *> $null
                $PythonHealthy = ($PythonVersionHealthy -and $CudaDllsHealthy -and $LASTEXITCODE -eq 0)
                $env:REMOTION_BROWSER_EXECUTABLE = $BrowserExecutable
                $BrowserCheck = "import('@remotion/renderer').then(async m => { await m.ensureBrowser({browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE}); }).catch(e => { console.error(e); process.exit(1); });"
                Push-Location (Join-Path $App "render-service")
                try {
                    & $NodeExe -e $BrowserCheck *> $null
                    $BrowserSignature = Get-AuthenticodeSignature -FilePath $BrowserExecutable
                    $NodeHealthy = ($NodeVersionHealthy -and $LASTEXITCODE -eq 0) -and ($BrowserSignature.Status -eq "Valid") -and ($BrowserSignature.SignerCertificate.Subject -match "Google")
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

# Runtime storage requirements are calculated after the release manifest is
# validated, because compressed and uncompressed archive sizes vary by variant.
# Scratch storage is checked again at that point against the actual temp volume.


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
$RuntimeSetupTestMode = $env:CLIPPY_RUNTIME_SETUP_TEST_MODE -eq "1"
if ($RuntimeSetupTestMode) {
    $TestManifestBaseUrl = [string]$env:CLIPPY_RUNTIME_SETUP_TEST_MANIFEST_BASE_URL
    $TestReleaseBaseUrl = [string]$env:CLIPPY_RUNTIME_SETUP_TEST_RELEASE_BASE_URL
    foreach ($TestUrl in @(
        @{ Value = $TestManifestBaseUrl; Label = "manifest base URL" },
        @{ Value = $TestReleaseBaseUrl; Label = "release asset base URL" }
    )) {
        $ParsedTestUrl = $null
        if (-not [Uri]::TryCreate($TestUrl.Value, [UriKind]::Absolute, [ref]$ParsedTestUrl) -or
            $ParsedTestUrl.Scheme -ne "http" -or
            -not $ParsedTestUrl.IsLoopback -or
            -not [string]::IsNullOrEmpty($ParsedTestUrl.UserInfo) -or
            -not [string]::IsNullOrEmpty($ParsedTestUrl.Query) -or
            -not [string]::IsNullOrEmpty($ParsedTestUrl.Fragment)) {
            throw "Runtime setup test mode only accepts plain HTTP loopback URLs for the $($TestUrl.Label)."
        }
    }
    $PythonRuntimeManifestUrl = $TestManifestBaseUrl.TrimEnd('/') + "/" + $PythonRuntimeManifestName
    $PythonRuntimeReleaseBaseUrl = $TestReleaseBaseUrl.TrimEnd('/')
    Write-Stage ("Using loopback-only runtime test manifest URL: " + $PythonRuntimeManifestUrl)
    Write-Stage ("Using loopback-only runtime test asset base URL: " + $PythonRuntimeReleaseBaseUrl)
}
$LocalRuntimeArchive = $env:CLIPPY_PYTHON_RUNTIME_ARCHIVE
$LocalRuntimeChecksum = $env:CLIPPY_PYTHON_RUNTIME_CHECKSUM

# Local archive overrides remain available for developer diagnostics.
# Customer installs use only the verified manifest and assets from the exact app release.
$RuntimeManifest = $null
$VerifiedRuntimeParts = @{}
$MissingRuntimeParts = New-Object System.Collections.Generic.List[object]
$RuntimePartDownloadBytes = 0L
$RuntimeReconstructionBytes = 0L
$PythonRuntimeExpandedBytes = 0L
$PythonRuntimeVerified = $false

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
    $PythonRuntimeExpandedBytes = Get-ClippyZipUncompressedSize -Path $PythonRuntimeArchive
    $PythonRuntimeVerified = $true
} else {
    $PythonRuntimeManifestPath = Join-Path $Downloads "$AppVersion-$PythonRuntimeManifestName"
    $ManifestParsed = $false
    for ($ManifestAttempt = 1; $ManifestAttempt -le 2; $ManifestAttempt++) {
        try {
            Download-File $PythonRuntimeManifestUrl $PythonRuntimeManifestPath
            $RuntimeManifest = Get-Content -LiteralPath $PythonRuntimeManifestPath -Raw | ConvertFrom-Json
            Assert-ClippyRuntimeArchiveManifest -Manifest $RuntimeManifest -ExpectedApplicationVersion $AppVersion -ExpectedVariant $TorchVariant | Out-Null
            $ManifestParsed = $true
            break
        } catch {
            $ManifestError = $_.Exception.Message
            Remove-Item -LiteralPath $PythonRuntimeManifestPath -Force -ErrorAction SilentlyContinue
            if ($ManifestAttempt -eq 2) {
                throw "The runtime manifest for release v$AppVersion could not be downloaded or validated from $PythonRuntimeManifestUrl. $ManifestError"
            }
            Write-Stage ("Cached/downloaded runtime manifest failed validation; downloading it again. " + $ManifestError)
        }
    }
    if (-not $ManifestParsed) { throw "Could not read a valid runtime manifest for release v$AppVersion." }

    $PythonRuntimeExpandedBytes = [long]$RuntimeManifest.archive.uncompressedSize
    if ([int]$RuntimeManifest.partCount -eq 1) {
        # The single-part canonical asset is already the complete archive. Use
        # it directly rather than writing a second copy during reconstruction.
        $PythonRuntimeArchive = Join-Path $Downloads ([string]$RuntimeManifest.archive.name)
    } else {
        $PythonRuntimeArchive = Join-Path $Downloads "$AppVersion-$PythonRuntimeName"
        # Reconstruct-ClippyRuntimeArchiveParts writes a new archive. Remove an
        # abandoned previous output now so its bytes are not double-counted.
        if (Test-Path -LiteralPath $PythonRuntimeArchive -PathType Leaf) {
            Remove-Item -LiteralPath $PythonRuntimeArchive -Force
        }
        $RuntimeReconstructionBytes = [long]$RuntimeManifest.archive.size
    }

    foreach ($Part in @($RuntimeManifest.parts)) {
        $PartName = [string]$Part.name
        $PartPath = Join-Path $Downloads $PartName
        $PartHealthy = $false
        if (Test-Path -LiteralPath $PartPath -PathType Leaf) {
            $PartInfo = Get-Item -LiteralPath $PartPath
            if ($PartInfo.Length -eq [long]$Part.size -and
                (Get-ClippyFileSha256 $PartPath) -eq ([string]$Part.sha256).ToLowerInvariant()) {
                $PartHealthy = $true
                $VerifiedRuntimeParts[$PartName] = $true
                Write-Stage "Reusing verified runtime part $PartName."
            } else {
                Write-Stage "Cached runtime part $PartName failed verification; removing it before download."
                Remove-Item -LiteralPath $PartPath -Force
            }
        }
        if (-not $PartHealthy) {
            $MissingRuntimeParts.Add($Part)
            $RuntimePartDownloadBytes += [long]$Part.size
        }
    }
}

# Preflight the actual peak disk footprint before downloading or extracting the
# Python runtime. For multipart archives, both all downloaded parts and the
# reconstructed ZIP coexist until installation succeeds.
$RuntimeReserveBytes = 2GB
$ScratchReserveBytes = 3GB
$RuntimeStorageRequiredBytes = [long]$RuntimePartDownloadBytes + [long]$RuntimeReconstructionBytes + [long]$PythonRuntimeExpandedBytes + [long]$RuntimeReserveBytes
$ScratchStorageRequiredBytes = [long]$ScratchReserveBytes
$RuntimeFreeBytes = Get-ClippyAvailableFreeBytes -Path $Runtime
$ScratchFreeBytes = Get-ClippyAvailableFreeBytes -Path $script:ScratchRoot
$RuntimeVolumeRoot = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Runtime))
$ScratchVolumeRoot = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($script:ScratchRoot))
$SameStorageVolume = [string]::Equals($RuntimeVolumeRoot, $ScratchVolumeRoot, [System.StringComparison]::OrdinalIgnoreCase)
if ($SameStorageVolume) {
    $CombinedRequiredBytes = $RuntimeStorageRequiredBytes + $ScratchStorageRequiredBytes
    if ($RuntimeFreeBytes -lt $CombinedRequiredBytes) {
        throw ("Clippy needs {0:N1} GB free on {1} for this {2} Python runtime ({3:N1} GB download/reconstruction, {4:N1} GB extraction, {5:N1} GB temporary setup reserve). Available: {6:N1} GB." -f
            ($CombinedRequiredBytes / 1GB), $RuntimeVolumeRoot, $TorchVariant,
            (($RuntimePartDownloadBytes + $RuntimeReconstructionBytes) / 1GB),
            ($PythonRuntimeExpandedBytes / 1GB), ($RuntimeReserveBytes / 1GB + $ScratchReserveBytes / 1GB),
            ($RuntimeFreeBytes / 1GB))
    }
} else {
    if ($RuntimeFreeBytes -lt $RuntimeStorageRequiredBytes) {
        throw ("Clippy needs {0:N1} GB free on the runtime volume {1} for this {2} Python runtime. Available: {3:N1} GB." -f
            ($RuntimeStorageRequiredBytes / 1GB), $RuntimeVolumeRoot, $TorchVariant, ($RuntimeFreeBytes / 1GB))
    }
    if ($ScratchFreeBytes -lt $ScratchStorageRequiredBytes) {
        throw ("Clippy needs {0:N1} GB free in the selected temporary storage volume {1}. Available: {2:N1} GB. Set TEMP/TMP or CLIPPY_TEMP_DIR to a writable volume with more space." -f
            ($ScratchStorageRequiredBytes / 1GB), $ScratchVolumeRoot, ($ScratchFreeBytes / 1GB))
    }
}
Write-Stage ("Disk preflight passed. Runtime volume required: " + [math]::Round($RuntimeStorageRequiredBytes / 1GB, 1) + " GB; available: " + [math]::Round($RuntimeFreeBytes / 1GB, 1) + " GB. Temporary volume required: " + [math]::Round($ScratchStorageRequiredBytes / 1GB, 1) + " GB; available: " + [math]::Round($ScratchFreeBytes / 1GB, 1) + " GB.")

if (-not [string]::IsNullOrWhiteSpace($LocalRuntimeArchive)) {
    $ActualExpandedBytes = Get-ClippyZipUncompressedSize -Path $PythonRuntimeArchive
    if ($ActualExpandedBytes -ne $PythonRuntimeExpandedBytes) {
        throw "Locally supplied Python runtime ZIP expanded size changed during validation."
    }
} else {
    foreach ($Part in @($RuntimeManifest.parts)) {
        $PartName = [string]$Part.name
        if ($VerifiedRuntimeParts.ContainsKey($PartName)) { continue }
        $PartUrl = "$PythonRuntimeReleaseBaseUrl/$PartName"
        $PartPath = Join-Path $Downloads $PartName
        Download-File $PartUrl $PartPath
        $PartInfo = Get-Item -LiteralPath $PartPath
        if ($PartInfo.Length -ne [long]$Part.size -or
            (Get-ClippyFileSha256 $PartPath) -ne ([string]$Part.sha256).ToLowerInvariant()) {
            Remove-Item -LiteralPath $PartPath -Force -ErrorAction SilentlyContinue
            throw "Downloaded runtime part failed size or SHA-256 verification: $PartName"
        }
        $VerifiedRuntimeParts[$PartName] = $true
    }

    if ([int]$RuntimeManifest.partCount -gt 1) {
        Write-Stage "Reconstructing the verified $TorchVariant Python runtime archive from $($RuntimeManifest.partCount) release asset(s)..."
        Join-ClippyRuntimeArchiveParts -Manifest $RuntimeManifest -PartsDirectory $Downloads -Destination $PythonRuntimeArchive | Out-Null
    } else {
        Write-Stage "Using the verified single-part $TorchVariant Python runtime archive."
    }

    $PythonArchiveInfo = Get-Item -LiteralPath $PythonRuntimeArchive
    $PythonArchiveHash = Get-ClippyFileSha256 -Path $PythonRuntimeArchive
    if ($PythonArchiveInfo.Length -ne [long]$RuntimeManifest.archive.size -or
        $PythonArchiveHash -ne ([string]$RuntimeManifest.archive.sha256).ToLowerInvariant()) {
        throw "Verified Python runtime archive does not match its release manifest."
    }
    $ActualExpandedBytes = Get-ClippyZipUncompressedSize -Path $PythonRuntimeArchive
    if ($ActualExpandedBytes -ne $PythonRuntimeExpandedBytes) {
        throw "Python runtime archive uncompressed size does not match its release manifest. Expected $PythonRuntimeExpandedBytes, got $ActualExpandedBytes."
    }
    $PythonRuntimeVerified = $true
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
$ExistingNodeVersion = if (Test-Path -LiteralPath $NodeExe -PathType Leaf) { (& $NodeExe --version 2>&1 | Out-String).Trim() } else { "" }
$ExistingNodeHealthy = ($LASTEXITCODE -eq 0 -and $ExistingNodeVersion.TrimStart([char]"v") -eq $NodeVersion)
if (-not $ExistingNodeHealthy) {
    if (Test-Path -LiteralPath $NodeDir) {
        Write-Stage "Managed Node.js runtime is missing, corrupt, or the wrong version; replacing it."
        Remove-Item -LiteralPath $NodeDir -Recurse -Force
    }
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
$InstalledNodeVersion = (& $NodeExe --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $InstalledNodeVersion.TrimStart([char]"v") -ne $NodeVersion) {
    throw "Managed Node.js runtime version check failed. Expected $NodeVersion, found $InstalledNodeVersion."
}

# FFmpeg is downloaded from the Windows builds publisher and verified against
# the publisher's SHA-256 sidecar before extraction.
$FfmpegExe = Join-Path $FfmpegDir "ffmpeg.exe"
$ExistingFfmpegHealthy = $false
if (Test-Path -LiteralPath $FfmpegExe -PathType Leaf) {
    & $FfmpegExe -version *> $null
    $ExistingFfmpegHealthy = ($LASTEXITCODE -eq 0)
}
if (-not $ExistingFfmpegHealthy) {
    if (Test-Path -LiteralPath $FfmpegDir) {
        Write-Stage "Managed FFmpeg runtime is missing or unhealthy; replacing it."
        Remove-Item -LiteralPath $FfmpegDir -Recurse -Force
    }
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
    $env:OUTPUT_DIR = Join-Path $Root "data\output"
    $env:UPLOAD_DIR = Join-Path $Root "data\uploads"
    $env:CLIPPY_SETTINGS_PATH = Join-Path $Root "settings.json"
    $env:CLIPPY_MODELS_DIR = Join-Path $Root "data\models"
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
    $ExistingBrowserSignature = Get-AuthenticodeSignature -FilePath $BrowserExecutable
    $BrowserNeedsInstall = ($ExistingBrowserSignature.Status -ne "Valid" -or $ExistingBrowserSignature.SignerCertificate.Subject -notmatch "Google")
}
if ($BrowserNeedsInstall) {
    Write-Stage "Installing or repairing the Remotion browser for renderer version $RemotionVersion..."
    $BrowserCheck = "import('@remotion/renderer').then(async m => { const b = await m.ensureBrowser(); console.log('CLIPPY_BROWSER_PATH=' + b.path); }).catch(e => { console.error(e); process.exit(1); });"
    Push-Location (Join-Path $App "render-service")
    try {
        $BrowserOutput = & $NodeExe -e $BrowserCheck 2>&1
        foreach ($OutputLine in $BrowserOutput) { Write-Stage ([string]$OutputLine) }
        if ($LASTEXITCODE -ne 0) { throw "Remotion browser installation failed." }
    } finally {
        Pop-Location
    }
    $BrowserPathLine = @($BrowserOutput | Where-Object { ([string]$_).StartsWith("CLIPPY_BROWSER_PATH=") } | Select-Object -Last 1)
    if ($BrowserPathLine.Count -lt 1) { throw "Remotion did not report the installed browser executable path." }
    $DownloadedBrowserExe = ([string]$BrowserPathLine[0]).Substring("CLIPPY_BROWSER_PATH=".Length)
    if (-not (Test-Path -LiteralPath $DownloadedBrowserExe -PathType Leaf)) {
        throw "Remotion reported a browser executable that does not exist: $DownloadedBrowserExe"
    }
    $DownloadedBrowserDir = Split-Path -Parent $DownloadedBrowserExe
    if (Test-Path -LiteralPath $BrowserDir) { Remove-Item -LiteralPath $BrowserDir -Recurse -Force }
    New-Item -ItemType Directory -Path $BrowserDir -Force | Out-Null
    Copy-Item -Path (Join-Path $DownloadedBrowserDir "*") -Destination $BrowserDir -Recurse -Force
    $BrowserExecutable = Join-Path $BrowserDir (Split-Path -Leaf $DownloadedBrowserExe)
    [System.IO.File]::WriteAllText($BrowserVersionFile, $RemotionVersion, [System.Text.UTF8Encoding]::new($false))
} else {
    Write-Stage "Reusing the browser already installed for Remotion $RemotionVersion."
}

if (-not (Test-Path -LiteralPath $BrowserExecutable -PathType Leaf)) {
    throw "Persistent Remotion browser executable is missing: $BrowserExecutable"
}
$BrowserSignature = Get-AuthenticodeSignature -FilePath $BrowserExecutable
if ($BrowserSignature.Status -ne "Valid" -or $BrowserSignature.SignerCertificate.Subject -notmatch "Google") {
    throw "Remotion browser signature is invalid or not issued to Google. The downloaded browser will not be trusted."
}
$BrowserSha256 = Get-ClippyFileSha256 -Path $BrowserExecutable
$env:REMOTION_BROWSER_EXECUTABLE = $BrowserExecutable
$BrowserValidation = "import('@remotion/renderer').then(async m => { await m.ensureBrowser({browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE}); console.log('Persistent Remotion browser ready'); }).catch(e => { console.error(e); process.exit(1); });"
Push-Location (Join-Path $App "render-service")
try {
    & $NodeExe -e $BrowserValidation
    if ($LASTEXITCODE -ne 0) { throw "Persistent Remotion browser validation failed." }
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

# Do not emit a successful completion marker unless every managed executable
# and the installed manifest are present at their contractual locations.
foreach ($RequiredInstalledFile in @(
    (Join-Path $PythonDir "python.exe"),
    (Join-Path $NodeDir "node.exe"),
    (Join-Path $FfmpegDir "ffmpeg.exe"),
    $BrowserExecutable,
    $ManifestPath
)) {
    if (-not (Test-Path -LiteralPath $RequiredInstalledFile -PathType Leaf)) {
        throw "Runtime setup reached finalization but a required installed file is missing: $RequiredInstalledFile"
    }
}
Write-Stage ("Final runtime file validation passed for " + $Root)

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
