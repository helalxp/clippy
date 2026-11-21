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
$originalForceCpuRuntime = $env:CLIPPY_FORCE_CPU_RUNTIME
$originalEnvironment = @{}
foreach ($key in @('PATH','OUTPUT_DIR','UPLOAD_DIR','REFERENCE_TEMPLATES_DIR','CLIPPY_SETTINGS_PATH','CLIPPY_DATA_DIR','CLIPPY_LIBRARY_DIR','CLIPPY_MODELS_DIR','HF_HOME','TORCH_HOME','PYTHONHOME','PYTHONPATH','NODE_OPTIONS','NODE_PATH')) { $originalEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, 'Process') }
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

    $runtimeManifestPath = Join-Path (Split-Path -Parent ([IO.Path]::GetFullPath($CpuRuntimeArchive))) 'clippy-python-cpu.manifest.json'
    Assert-File $runtimeManifestPath "CPU runtime release manifest"
    $runtimeManifest = Get-Content -LiteralPath $runtimeManifestPath -Raw | ConvertFrom-Json
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $appVersionPath = Join-Path $repoRoot "VERSION"
    Assert-File $appVersionPath "application VERSION"
    $appVersion = (Get-Content -LiteralPath $appVersionPath -Raw).Trim()
    if ([string]$runtimeManifest.applicationVersion -ne $appVersion -or [string]$runtimeManifest.runtimeVariant -ne "cpu") {
        throw "CPU runtime manifest does not match application version $appVersion."
    }
    $cpuArchiveInfo = Get-Item -LiteralPath $CpuRuntimeArchive
    $cpuArchiveHash = (Get-FileHash -LiteralPath $CpuRuntimeArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ([long]$runtimeManifest.archive.size -ne $cpuArchiveInfo.Length -or
        ([string]$runtimeManifest.archive.sha256).ToLowerInvariant() -ne $cpuArchiveHash) {
        throw "CPU runtime ZIP does not match the release manifest that will be published."
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    New-Item -ItemType Directory -Path $smokeLocalAppData -Force | Out-Null
    New-Item -ItemType Directory -Path $smokeRoot -Force | Out-Null

    $env:LOCALAPPDATA = $smokeLocalAppData
    $env:CLIPPY_PYTHON_RUNTIME_ARCHIVE = [IO.Path]::GetFullPath($CpuRuntimeArchive)
    $env:CLIPPY_PYTHON_RUNTIME_CHECKSUM = [IO.Path]::GetFullPath($CpuRuntimeChecksum)
    $env:CLIPPY_FORCE_CPU_RUNTIME = "1"

    $root = Join-Path $smokeLocalAppData "Clippy"
    $appDirectory = Join-Path $root "app\current"
    New-Item -ItemType Directory -Path $appDirectory -Force | Out-Null
    [IO.Compression.ZipFile]::ExtractToDirectory([IO.Path]::GetFullPath($PayloadArchive), $appDirectory)

    # Exercise the persisted external-data-root path without touching the
    # runner's real LOCALAPPDATA or creating data under the app installation.
    $dataRoot = Join-Path $smokeRoot "external-clippy-data"
    New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
    # Simulate the legacy Win32 verbatim path produced by Rust canonicalize().
    # The packaged setup must normalize it before the first Join-Path call.
    $legacyExtendedDataRoot = '\\?\' + [IO.Path]::GetFullPath($dataRoot)
    $storageLocation = @{
        schema_version = 1
        data_directory = $legacyExtendedDataRoot
    } | ConvertTo-Json -Compress
    [IO.File]::WriteAllText(
        (Join-Path $root "storage-location.json"),
        $storageLocation,
        [Text.UTF8Encoding]::new($false)
    )

    foreach ($required in @(
        "setup-runtime.ps1",
        "runtime-archive.ps1",
        "runtime-manifest-state.ps1",
        "runtime-health.ps1",
        "storage-path.ps1",
        "runtime-ffmpeg.ps1",
        "runtime-contract.json",
        "app.py",
        "community_highlights\__init__.py",
        "community_highlights\api.py",
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

    function Start-WindowsPowerShellProcess {
        param(
            [Parameter(Mandatory = $true)][string[]]$Arguments,
            [Parameter(Mandatory = $true)][string]$StandardOutputPath,
            [Parameter(Mandatory = $true)][string]$StandardErrorPath
        )

        # The smoke-test host is PowerShell 7, while the product intentionally
        # uses Windows PowerShell 5.1. Do not let PowerShell 7's module paths
        # leak into the legacy child process. With PSModulePath absent, Windows
        # PowerShell reconstructs its own compatible module search path.
        $hadModulePath = Test-Path Env:PSModulePath
        $savedModulePath = $env:PSModulePath
        try {
            Remove-Item Env:PSModulePath -ErrorAction SilentlyContinue
            $child = Start-Process -FilePath $powershell -ArgumentList $Arguments -Wait -PassThru -NoNewWindow -RedirectStandardOutput $StandardOutputPath -RedirectStandardError $StandardErrorPath
            return $child
        } finally {
            if ($hadModulePath) {
                $env:PSModulePath = $savedModulePath
            } else {
                Remove-Item Env:PSModulePath -ErrorAction SilentlyContinue
            }
        }
    }

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

    # Prove that the exact Windows PowerShell host used by Clippy starts with
    # its own standard modules and can resolve the hash command before setup.
    $moduleProbeScript = Join-Path $smokeRoot "verify-windows-powershell.ps1"
    $moduleProbeContent = @'
$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSEdition -ne "Desktop" -or $PSVersionTable.PSVersion.Major -ne 5) {
    throw "Expected Windows PowerShell 5.1; found $($PSVersionTable.PSEdition) $($PSVersionTable.PSVersion)."
}
$hashCommand = Get-Command Get-FileHash -ErrorAction Stop
$jsonCommand = Get-Command ConvertFrom-Json -ErrorAction Stop
Write-Output "PSEdition=$($PSVersionTable.PSEdition)"
Write-Output "PSVersion=$($PSVersionTable.PSVersion)"
Write-Output "PSModulePath=$env:PSModulePath"
Write-Output "Get-FileHashModule=$($hashCommand.Source)"
Write-Output "ConvertFromJsonModule=$($jsonCommand.Source)"
'@
    [IO.File]::WriteAllText($moduleProbeScript, $moduleProbeContent, [Text.UTF8Encoding]::new($false))
    $probeStdout = Join-Path $smokeRoot "windows-powershell-probe.stdout.log"
    $probeStderr = Join-Path $smokeRoot "windows-powershell-probe.stderr.log"
    $probeArguments = @("-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", ('"' + $moduleProbeScript + '"'))
    $probeProcess = Start-WindowsPowerShellProcess -Arguments $probeArguments -StandardOutputPath $probeStdout -StandardErrorPath $probeStderr
    if ($probeProcess.ExitCode -ne 0) {
        $probeDetails = @()
        foreach ($logPath in @($probeStdout, $probeStderr)) {
            if (Test-Path -LiteralPath $logPath -PathType Leaf) {
                $probeDetails += "===== $logPath ====="
                $probeDetails += Get-Content -LiteralPath $logPath -Tail 40
            }
        }
        throw ("Windows PowerShell 5.1 module preflight failed with exit code $($probeProcess.ExitCode)." + [Environment]::NewLine + ($probeDetails -join [Environment]::NewLine))
    }
    Write-Host "Windows PowerShell 5.1 module preflight passed:"
    Get-Content -LiteralPath $probeStdout | ForEach-Object { Write-Host $_ }

    Write-Host "Running the actual first-run runtime setup in an isolated LOCALAPPDATA root..."
    $process = Start-WindowsPowerShellProcess -Arguments $argumentList -StandardOutputPath $setupStdout -StandardErrorPath $setupStderr
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

    foreach ($key in @('PYTHONHOME','PYTHONPATH','NODE_OPTIONS','NODE_PATH')) { [Environment]::SetEnvironmentVariable($key, $null, 'Process') }
    $env:CLIPPY_DATA_DIR = $dataRoot
    $env:OUTPUT_DIR = Join-Path $dataRoot 'output'
    $env:UPLOAD_DIR = Join-Path $dataRoot 'uploads'
    $env:CLIPPY_LIBRARY_DIR = Join-Path $dataRoot 'library'
    $env:REFERENCE_TEMPLATES_DIR = Join-Path $dataRoot 'reference_templates'
    $env:CLIPPY_MODELS_DIR = Join-Path $dataRoot 'models'
    $env:HF_HOME = Join-Path $dataRoot 'models\huggingface'
    $env:TORCH_HOME = Join-Path $dataRoot 'models\torch'
    $env:CLIPPY_SETTINGS_PATH = Join-Path $root 'settings.json'
    & $pythonExe -c "import sys,pathlib,app,torch,fastapi,faster_whisper; assert pathlib.Path(app.__file__).resolve() == (pathlib.Path(sys.argv[1])/'app.py').resolve(); assert torch.version.cuda is None; print('Packaged backend imports and CPU runtime OK:', torch.__version__)" $appDirectory
    if ($LASTEXITCODE -ne 0) { throw "Managed Python backend import smoke test failed." }
    if (-not (Test-Path -LiteralPath (Join-Path $dataRoot 'output') -PathType Container)) {
        throw "The relocated output directory was not created under the configured data root."
    }
    if (Test-Path -LiteralPath (Join-Path $root 'data') -PathType Container) {
        throw "The runtime smoke test unexpectedly created a default data folder under the application root."
    }
    & $nodeExe --version
    if ($LASTEXITCODE -ne 0) { throw "Managed Node.js executable smoke test failed." }
    & $ffmpegExe -version *> $null
    if ($LASTEXITCODE -ne 0) { throw "Managed FFmpeg executable smoke test failed." }

    # Match the supervisor's private environment for the post-setup checks.
    $env:CLIPPY_DATA_DIR = $dataRoot
    $env:OUTPUT_DIR = Join-Path $dataRoot 'output'
    $env:UPLOAD_DIR = Join-Path $dataRoot 'uploads'
    $env:CLIPPY_LIBRARY_DIR = Join-Path $dataRoot 'library'
    $env:REFERENCE_TEMPLATES_DIR = Join-Path $dataRoot 'reference_templates'
    $env:CLIPPY_MODELS_DIR = Join-Path $dataRoot 'models'
    $env:HF_HOME = Join-Path $dataRoot 'models\huggingface'
    $env:TORCH_HOME = Join-Path $dataRoot 'models\torch'
    $env:CLIPPY_SETTINGS_PATH = Join-Path $root 'settings.json'
    $env:PATH = (Split-Path $nodeExe -Parent) + ';' + (Split-Path $ffmpegExe -Parent) + ';' + "$env:SystemRoot\System32"
    $fixture = Join-Path $smokeRoot 'fixture.mp4'
    & $ffmpegExe -hide_banner -loglevel error -f lavfi -i 'color=c=blue:s=180x320:r=12:d=1' -an -c:v libx264 -pix_fmt yuv420p $fixture
    if ($LASTEXITCODE -ne 0) { throw 'Could not create render smoke fixture.' }
    & $nodeExe (Join-Path $PSScriptRoot 'smoke-render.mjs') $appDirectory $browserExe $fixture (Join-Path $smokeRoot 'rendered.mp4')
    if ($LASTEXITCODE -ne 0) { throw 'Packaged render smoke test failed.' }
    # A healthy second setup must succeed without the local archive and without downloads.
    Remove-Item Env:CLIPPY_PYTHON_RUNTIME_ARCHIVE,Env:CLIPPY_PYTHON_RUNTIME_CHECKSUM -ErrorAction SilentlyContinue
    $rerunOut = Join-Path $smokeRoot 'rerun.stdout.log'
    $rerunErr = Join-Path $smokeRoot 'rerun.stderr.log'
    $rerun = Start-WindowsPowerShellProcess -Arguments $argumentList -StandardOutputPath $rerunOut -StandardErrorPath $rerunErr
    if ($rerun.ExitCode -ne 0 -or (Get-Content $rerunOut -Raw) -notmatch 'No downloads needed') { throw 'Healthy setup did not reuse the installed runtime.' }
    Write-Host "Clean first-run runtime and rendering smoke tests passed for Clippy $appVersion."
} finally {
    foreach ($key in $originalEnvironment.Keys) { [Environment]::SetEnvironmentVariable($key, $originalEnvironment[$key], 'Process') }
    if ($null -eq $originalLocalAppData) { Remove-Item Env:LOCALAPPDATA -ErrorAction SilentlyContinue } else { $env:LOCALAPPDATA = $originalLocalAppData }
    if ($null -eq $originalRuntimeArchive) { Remove-Item Env:CLIPPY_PYTHON_RUNTIME_ARCHIVE -ErrorAction SilentlyContinue } else { $env:CLIPPY_PYTHON_RUNTIME_ARCHIVE = $originalRuntimeArchive }
    if ($null -eq $originalRuntimeChecksum) { Remove-Item Env:CLIPPY_PYTHON_RUNTIME_CHECKSUM -ErrorAction SilentlyContinue } else { $env:CLIPPY_PYTHON_RUNTIME_CHECKSUM = $originalRuntimeChecksum }
    if ($null -eq $originalForceCpuRuntime) { Remove-Item Env:CLIPPY_FORCE_CPU_RUNTIME -ErrorAction SilentlyContinue } else { $env:CLIPPY_FORCE_CPU_RUNTIME = $originalForceCpuRuntime }
    if (Test-Path -LiteralPath $smokeLocalAppData -PathType Container) {
        Remove-Item -LiteralPath $smokeLocalAppData -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $smokeRoot -PathType Container) {
        Remove-Item -LiteralPath $smokeRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
