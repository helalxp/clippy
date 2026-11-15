param(
    [string]$PayloadArchive = (Join-Path $PSScriptRoot "src-tauri\resources\app-payload.zip"),
    [string]$PayloadChecksum = (Join-Path $PSScriptRoot "src-tauri\resources\app-payload.sha256"),
    [string]$CpuRuntimeArchive = (Join-Path $PSScriptRoot "runtime-dist\clippy-python-cpu.zip"),
    [string]$CpuRuntimeChecksum = (Join-Path $PSScriptRoot "runtime-dist\clippy-python-cpu.zip.sha256")
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Assert-File([string]$Path, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw ("First-run smoke test is missing " + $Label + ": " + $Path)
    }
}

function Assert-Sha256([string]$Path, [string]$ChecksumPath, [string]$Label) {
    Assert-File $Path $Label
    Assert-File $ChecksumPath "$Label SHA-256 file"
    $checksumText = Get-Content -LiteralPath $ChecksumPath -Raw
    if ($checksumText -notmatch '(?i)\b([a-f0-9]{64})\b') {
        throw "$Label SHA-256 file does not contain a valid digest: $ChecksumPath"
    }
    $expected = $Matches[1].ToLowerInvariant()
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        throw "$Label SHA-256 mismatch. Expected $expected, got $actual."
    }
}

$originalLocalAppData = $env:LOCALAPPDATA
$originalRuntimeArchive = $env:CLIPPY_PYTHON_RUNTIME_ARCHIVE
$originalRuntimeChecksum = $env:CLIPPY_PYTHON_RUNTIME_CHECKSUM
if ([string]::IsNullOrWhiteSpace($originalLocalAppData)) {
    throw "The first-run smoke test requires the Windows LOCALAPPDATA environment variable."
}
$tempBase = if (-not [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$smokeRoot = Join-Path $tempBase ("clippy-first-run-smoke-" + [guid]::NewGuid().ToString("N"))
# Keep the managed runtime on the normal per-user app-data volume while the
# setup script independently selects the roomiest fixed volume for scratch.
$smokeLocalAppData = Join-Path $originalLocalAppData ("ClippySmoke-" + [guid]::NewGuid().ToString("N"))
$setupStdout = Join-Path $smokeRoot "setup.stdout.log"
$setupStderr = Join-Path $smokeRoot "setup.stderr.log"
$setupLog = Join-Path $smokeLocalAppData "Clippy\logs\runtime-setup.log"

try {
    Assert-Sha256 $PayloadArchive $PayloadChecksum "embedded application payload"
    Assert-Sha256 $CpuRuntimeArchive $CpuRuntimeChecksum "CPU Python runtime archive"

    $runtimeManifestPath = Join-Path $PSScriptRoot "runtime-dist\clippy-python-cpu.manifest.json"
    Assert-File $runtimeManifestPath "CPU runtime release manifest"
    $runtimeManifest = Get-Content -LiteralPath $runtimeManifestPath -Raw | ConvertFrom-Json
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $appVersionPath = Join-Path $repoRoot "VERSION"
    Assert-File $appVersionPath "application VERSION"
    $appVersion = (Get-Content -LiteralPath $appVersionPath -Raw).Trim()
    if ([string]$runtimeManifest.applicationVersion -ne $appVersion -or [string]$runtimeManifest.runtimeVariant -ne "cpu") {
        throw "CPU runtime manifest does not match application version $appVersion."
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    New-Item -ItemType Directory -Path $smokeLocalAppData -Force | Out-Null
    New-Item -ItemType Directory -Path $smokeRoot -Force | Out-Null

    $env:LOCALAPPDATA = $smokeLocalAppData
    $env:CLIPPY_PYTHON_RUNTIME_ARCHIVE = [IO.Path]::GetFullPath($CpuRuntimeArchive)
    $env:CLIPPY_PYTHON_RUNTIME_CHECKSUM = [IO.Path]::GetFullPath($CpuRuntimeChecksum)

    $appDirectory = Join-Path $smokeLocalAppData "Clippy\app\current"
    New-Item -ItemType Directory -Path $appDirectory -Force | Out-Null
    [IO.Compression.ZipFile]::ExtractToDirectory([IO.Path]::GetFullPath($PayloadArchive), $appDirectory)

    foreach ($required in @(
        "setup-runtime.ps1",
        "runtime-archive.ps1",
        "runtime-manifest-state.ps1",
        "app.py",
        "requirements.txt",
        "VERSION",
        "render-service\dist\server.js",
        "render-service\node_modules\@remotion\renderer\package.json",
        "remotion\src\index.ts",
        "bgutil-provider\server\build\generate_once.js"
    )) {
        Assert-File (Join-Path $appDirectory $required) "extracted payload file $required"
    }

    $powershell = (Get-Command "powershell.exe" -ErrorAction Stop).Source
    $setupScript = Join-Path $appDirectory "setup-runtime.ps1"
    $quotedSetupScript = '"' + $setupScript + '"'
    $argumentList = @(
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $quotedSetupScript
    )

    Write-Host "Running the actual first-run runtime setup in an isolated LOCALAPPDATA root..."
    $process = Start-Process -FilePath $powershell -ArgumentList $argumentList -Wait -PassThru -NoNewWindow -RedirectStandardOutput $setupStdout -RedirectStandardError $setupStderr
    if ($process.ExitCode -ne 0) {
        $details = @()
        foreach ($logPath in @($setupLog, $setupStdout, $setupStderr)) {
            if (Test-Path -LiteralPath $logPath -PathType Leaf) {
                $details += "===== $logPath ====="
                $details += Get-Content -LiteralPath $logPath -Tail 60
            }
        }
        throw ("First-run runtime setup failed with exit code $($process.ExitCode)." + [Environment]::NewLine + ($details -join [Environment]::NewLine))
    }

    $root = Join-Path $smokeLocalAppData "Clippy"
    $pythonExe = Join-Path $root "runtime\python\python.exe"
    $nodeExe = Join-Path $root "runtime\node\node.exe"
    $ffmpegExe = Join-Path $root "runtime\ffmpeg\bin\ffmpeg.exe"
    $browserExe = Join-Path $root "browser\headless-shell\chrome-headless-shell.exe"
    $manifestPath = Join-Path $root "runtime-manifest.json"

    foreach ($component in @(
        @{ path = $pythonExe; label = "managed Python" },
        @{ path = $nodeExe; label = "managed Node.js" },
        @{ path = $ffmpegExe; label = "managed FFmpeg" },
        @{ path = $browserExe; label = "persistent Remotion browser" },
        @{ path = $manifestPath; label = "runtime manifest" }
    )) {
        Assert-File $component.path $component.label
    }

    $installedManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    foreach ($name in @("python", "node", "ffmpeg", "browser")) {
        $component = $installedManifest.components.$name
        if (-not $component -or -not $component.installed -or [string]::IsNullOrWhiteSpace([string]$component.version)) {
            throw "Runtime manifest did not mark '$name' as installed."
        }
    }

    & $pythonExe -c "import app, torch, fastapi, faster_whisper; assert torch.version.cuda is None; print('Backend imports and CPU runtime OK:', torch.__version__)"
    if ($LASTEXITCODE -ne 0) { throw "Managed Python backend import smoke test failed." }
    & $nodeExe --version
    if ($LASTEXITCODE -ne 0) { throw "Managed Node.js executable smoke test failed." }
    & $ffmpegExe -version *> $null
    if ($LASTEXITCODE -ne 0) { throw "Managed FFmpeg executable smoke test failed." }

    Write-Host "Clean first-run runtime smoke test passed for Clippy $appVersion."
} finally {
    if ($null -eq $originalLocalAppData) { Remove-Item Env:LOCALAPPDATA -ErrorAction SilentlyContinue } else { $env:LOCALAPPDATA = $originalLocalAppData }
    if ($null -eq $originalRuntimeArchive) { Remove-Item Env:CLIPPY_PYTHON_RUNTIME_ARCHIVE -ErrorAction SilentlyContinue } else { $env:CLIPPY_PYTHON_RUNTIME_ARCHIVE = $originalRuntimeArchive }
    if ($null -eq $originalRuntimeChecksum) { Remove-Item Env:CLIPPY_PYTHON_RUNTIME_CHECKSUM -ErrorAction SilentlyContinue } else { $env:CLIPPY_PYTHON_RUNTIME_CHECKSUM = $originalRuntimeChecksum }
    if (Test-Path -LiteralPath $smokeRoot -PathType Container) {
        Remove-Item -LiteralPath $smokeRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
