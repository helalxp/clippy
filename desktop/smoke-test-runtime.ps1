param(
    [string]$PayloadArchive = (Join-Path $PSScriptRoot "src-tauri\resources\app-payload.zip"),
    [string]$PayloadChecksum = (Join-Path $PSScriptRoot "src-tauri\resources\app-payload.sha256"),
    [string]$CpuRuntimeArchive = (Join-Path $PSScriptRoot "runtime-dist\clippy-python-cpu.zip"),
    [string]$CpuRuntimeChecksum = (Join-Path $PSScriptRoot "runtime-dist\clippy-python-cpu.zip.sha256")
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
. (Join-Path $PSScriptRoot "runtime-archive.ps1")

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
    $actual = Get-ClippyFileSha256 -Path $Path
    if ($actual -ne $expected) {
        throw "$Label SHA-256 mismatch. Expected $expected, got $actual."
    }
}

$originalLocalAppData = $env:LOCALAPPDATA
$originalRuntimeArchive = $env:CLIPPY_PYTHON_RUNTIME_ARCHIVE
$originalRuntimeChecksum = $env:CLIPPY_PYTHON_RUNTIME_CHECKSUM
$originalForceCpuRuntime = $env:CLIPPY_FORCE_CPU_RUNTIME
$originalModulePath = $env:PSModulePath
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
$diagnosticsSuffix = if ($env:GITHUB_RUN_ID) {
    "$($env:GITHUB_RUN_ID)-$($env:GITHUB_RUN_ATTEMPT)"
} else {
    [guid]::NewGuid().ToString("N")
}
$diagnosticsRoot = Join-Path $tempBase "clippy-first-run-smoke-diagnostics-$diagnosticsSuffix"
$diagnosticsLog = Join-Path $diagnosticsRoot "smoke-test-diagnostics.log"
$childContextLog = Join-Path $smokeRoot "child-context.log"
$originalRuntimeSetupTestMode = $env:CLIPPY_RUNTIME_SETUP_TEST_MODE
$originalRuntimeSetupManifestBaseUrl = $env:CLIPPY_RUNTIME_SETUP_TEST_MANIFEST_BASE_URL
$originalRuntimeSetupReleaseBaseUrl = $env:CLIPPY_RUNTIME_SETUP_TEST_RELEASE_BASE_URL
$originalClippyTempDir = $env:CLIPPY_TEMP_DIR
$script:smokeRoot = $smokeRoot
$script:smokeLocalAppData = $smokeLocalAppData
$script:diagnosticsRoot = $diagnosticsRoot
$script:diagnosticsLog = $diagnosticsLog
$script:childContextLog = $childContextLog
$script:setupLog = $setupLog
$script:setupStdout = $setupStdout
$script:setupStderr = $setupStderr
$script:setupProcess = $null
$originalSmokeDiagnosticsPath = $env:CLIPPY_SMOKE_DIAGNOSTICS_PATH
New-Item -ItemType Directory -Path $diagnosticsRoot -Force | Out-Null

function Write-SmokeDiagnostic([string]$Message) {
    $line = "[{0}] {1}" -f ([DateTime]::Now.ToString("yyyy-MM-dd HH:mm:ss")), $Message
    [IO.File]::AppendAllText($diagnosticsLog, $line + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    Write-Host $line
}

function Save-SmokeDiagnostics([string]$FailureMessage = "") {
    $root = Join-Path $script:smokeLocalAppData "Clippy"
    $paths = @(
        @{ Path = $script:childContextLog; Name = "child-context.log" },
        @{ Path = $script:setupLog; Name = "runtime-setup.log" },
        @{ Path = $script:setupStdout; Name = "setup.stdout.log" },
        @{ Path = $script:setupStderr; Name = "setup.stderr.log" }
    )
    $lines = @("Child exit code: $(if ($script:setupProcess) { $script:setupProcess.ExitCode } else { 'not-started' })")
    if ($FailureMessage) { $lines += "SMOKE TEST FAILURE: $FailureMessage" }
    foreach ($source in $paths) {
        $sourcePath = [string]$source.Path
        if (Test-Path -LiteralPath $sourcePath -PathType Leaf) {
            $target = Join-Path $script:diagnosticsRoot ([string]$source.Name)
            $lines += ""
            $lines += "===== $sourcePath ====="
            try {
                $sourceFull = [IO.Path]::GetFullPath($sourcePath)
                $targetFull = [IO.Path]::GetFullPath($target)
                if (-not [string]::Equals($sourceFull, $targetFull, [StringComparison]::OrdinalIgnoreCase)) {
                    Copy-Item -LiteralPath $sourcePath -Destination $target -Force -ErrorAction Stop
                }
                $lines += Get-Content -LiteralPath $sourcePath -Tail 300 -ErrorAction Stop
            } catch {
                $lines += "Diagnostic copy/read failed: $($_.Exception.Message)"
            }
        } else {
            $lines += "MISSING LOG: $sourcePath"
        }
    }

    foreach ($path in @(
        (Join-Path $root "runtime\python\python.exe"),
        (Join-Path $root "runtime\node\node.exe"),
        (Join-Path $root "runtime\ffmpeg\bin\ffmpeg.exe"),
        (Join-Path $root "browser\headless-shell\chrome-headless-shell.exe"),
        (Join-Path $root "runtime-manifest.json")
    )) {
        $lines += ("EXISTS [{0}]: {1}" -f (Test-Path -LiteralPath $path), $path)
    }
    if (Test-Path -LiteralPath $root -PathType Container) {
        $lines += "===== Isolated Clippy file inventory ====="
        $lines += Get-ChildItem -LiteralPath $root -Force -Recurse -File -ErrorAction SilentlyContinue |
            Select-Object -First 300 |
            ForEach-Object { "{0} ({1:N0} bytes)" -f $_.FullName, $_.Length }
    }
    $manifestPath = Join-Path $root "runtime-manifest.json"
    if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
        $lines += "===== Installed runtime manifest ====="
        $lines += Get-Content -LiteralPath $manifestPath -Raw
    }

    [IO.File]::WriteAllLines($script:diagnosticsLog, $lines, [Text.UTF8Encoding]::new($false))
    Write-Host ""
    Write-Host "========== FIRST-RUN SETUP DIAGNOSTICS =========="
    Get-Content -LiteralPath $script:diagnosticsLog
    Write-Host "========== END FIRST-RUN SETUP DIAGNOSTICS ======"
    Write-Host "Diagnostics retained at: $script:diagnosticsRoot"
}

Write-SmokeDiagnostic "Clean first-run smoke test started."
Write-SmokeDiagnostic "PowerShell host: $($PSVersionTable.PSVersion); PSHOME: $PSHOME"
Write-SmokeDiagnostic "Original LOCALAPPDATA: $originalLocalAppData"
Write-SmokeDiagnostic "Isolated LOCALAPPDATA: $smokeLocalAppData"
Write-SmokeDiagnostic "Diagnostic artifact directory: $diagnosticsRoot"

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
    $cpuArchiveInfo = Get-Item -LiteralPath $CpuRuntimeArchive
    $cpuArchiveHash = Get-ClippyFileSha256 -Path $CpuRuntimeArchive
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
    $env:CLIPPY_SMOKE_DIAGNOSTICS_PATH = $childContextLog

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

    # Use the known Windows PowerShell 5.1 executable, not whichever
    # powershell.exe happens to appear first on the hosted runner's PATH.
    $powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    Assert-File $powershell "Windows PowerShell 5.1 executable"
    $powerShellVersion = (& $powershell -NoLogo -NoProfile -NonInteractive -Command '$PSVersionTable.PSVersion.ToString()' | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $powerShellVersion -notmatch '^5\.1\.') {
        throw "First-run smoke test requires Windows PowerShell 5.1; found '$powerShellVersion' at $powershell."
    }
    Write-Host "Using Windows PowerShell $powerShellVersion at $powershell."

    $setupScript = Join-Path $appDirectory "setup-runtime.ps1"
    $setupLauncherScript = Join-Path $smokeRoot "invoke-runtime-setup.ps1"
    $escapedSetupScript = $setupScript.Replace("'", "''")
    $escapedChildContextLog = $childContextLog.Replace("'", "''")
    $launcherContent = @'
$contextPath = '__CLIPPY_CHILD_CONTEXT_PATH__'
$context = @(
    "ChildPID=$PID",
    "PowerShellVersion=$($PSVersionTable.PSVersion)",
    "PSHOME=$PSHOME",
    "LOCALAPPDATA=$env:LOCALAPPDATA",
    "PSModulePath=$env:PSModulePath",
    "SetupScript=__CLIPPY_SETUP_SCRIPT__"
)
[IO.File]::WriteAllLines($contextPath, $context, [Text.Encoding]::UTF8)
$PSModuleAutoLoadingPreference = 'None'
& '__CLIPPY_SETUP_SCRIPT__'
'@
    $launcherContent = $launcherContent.Replace("__CLIPPY_SETUP_SCRIPT__", $escapedSetupScript)
    $launcherContent = $launcherContent.Replace("__CLIPPY_CHILD_CONTEXT_PATH__", $escapedChildContextLog)
    [IO.File]::WriteAllText($setupLauncherScript, $launcherContent, [Text.UTF8Encoding]::new($false))
    $quotedSetupLauncherScript = '"' + $setupLauncherScript + '"'
    $argumentList = @(
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $quotedSetupLauncherScript
    )

    Write-Host "Running the actual first-run runtime setup in an isolated LOCALAPPDATA root..."
    # Deliberately remove inherited module search paths for this child. The
    # setup engine must import Windows PowerShell's built-in modules by the
    # absolute paths under its own PSHOME, not depend on the parent host.
    $isolatedModulePath = Join-Path $smokeRoot "empty-module-path"
    New-Item -ItemType Directory -Path $isolatedModulePath -Force | Out-Null
    try {
        $env:PSModulePath = $isolatedModulePath
        $process = Start-Process -FilePath $powershell -ArgumentList $argumentList -Wait -PassThru -NoNewWindow -RedirectStandardOutput $setupStdout -RedirectStandardError $setupStderr
    } finally {
        if ($null -eq $originalModulePath) { Remove-Item Env:PSModulePath -ErrorAction SilentlyContinue } else { $env:PSModulePath = $originalModulePath }
    }
    $script:setupProcess = $process
    Save-SmokeDiagnostics

    if ($process.ExitCode -ne 0) {
        throw "First-run runtime setup failed with exit code $($process.ExitCode). Full diagnostics were retained at $diagnosticsRoot."
    }

    $setupLogText = if (Test-Path -LiteralPath $setupLog -PathType Leaf) { Get-Content -LiteralPath $setupLog -Raw } else { "" }
    $hasCompletionMarker =
        $setupLogText.Contains("Runtime setup completed successfully.") -or
        $setupLogText.Contains("Managed runtimes and application dependencies are healthy. No downloads needed.")
    if (-not $hasCompletionMarker) {
        throw "Runtime setup returned exit code 0 without writing a recognized completion marker. This is a false-success condition. Full diagnostics were retained at $diagnosticsRoot."
    }

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
} catch {
    $failureMessage = $_.Exception.Message
    try { Save-SmokeDiagnostics -FailureMessage $failureMessage } catch {
        Write-Host "Could not write complete diagnostics: $($_.Exception.Message)"
    }
    throw
} finally {
    if ($null -eq $originalLocalAppData) { Remove-Item Env:LOCALAPPDATA -ErrorAction SilentlyContinue } else { $env:LOCALAPPDATA = $originalLocalAppData }
    if ($null -eq $originalRuntimeArchive) { Remove-Item Env:CLIPPY_PYTHON_RUNTIME_ARCHIVE -ErrorAction SilentlyContinue } else { $env:CLIPPY_PYTHON_RUNTIME_ARCHIVE = $originalRuntimeArchive }
    if ($null -eq $originalRuntimeChecksum) { Remove-Item Env:CLIPPY_PYTHON_RUNTIME_CHECKSUM -ErrorAction SilentlyContinue } else { $env:CLIPPY_PYTHON_RUNTIME_CHECKSUM = $originalRuntimeChecksum }
    if ($null -eq $originalForceCpuRuntime) { Remove-Item Env:CLIPPY_FORCE_CPU_RUNTIME -ErrorAction SilentlyContinue } else { $env:CLIPPY_FORCE_CPU_RUNTIME = $originalForceCpuRuntime }
    if ($null -eq $originalSmokeDiagnosticsPath) { Remove-Item Env:CLIPPY_SMOKE_DIAGNOSTICS_PATH -ErrorAction SilentlyContinue } else { $env:CLIPPY_SMOKE_DIAGNOSTICS_PATH = $originalSmokeDiagnosticsPath }
    if ($null -eq $originalRuntimeSetupTestMode) { Remove-Item Env:CLIPPY_RUNTIME_SETUP_TEST_MODE -ErrorAction SilentlyContinue } else { $env:CLIPPY_RUNTIME_SETUP_TEST_MODE = $originalRuntimeSetupTestMode }
    if ($null -eq $originalRuntimeSetupManifestBaseUrl) { Remove-Item Env:CLIPPY_RUNTIME_SETUP_TEST_MANIFEST_BASE_URL -ErrorAction SilentlyContinue } else { $env:CLIPPY_RUNTIME_SETUP_TEST_MANIFEST_BASE_URL = $originalRuntimeSetupManifestBaseUrl }
    if ($null -eq $originalRuntimeSetupReleaseBaseUrl) { Remove-Item Env:CLIPPY_RUNTIME_SETUP_TEST_RELEASE_BASE_URL -ErrorAction SilentlyContinue } else { $env:CLIPPY_RUNTIME_SETUP_TEST_RELEASE_BASE_URL = $originalRuntimeSetupReleaseBaseUrl }
    if ($null -eq $originalClippyTempDir) { Remove-Item Env:CLIPPY_TEMP_DIR -ErrorAction SilentlyContinue } else { $env:CLIPPY_TEMP_DIR = $originalClippyTempDir }
    if ($null -eq $originalModulePath) { Remove-Item Env:PSModulePath -ErrorAction SilentlyContinue } else { $env:PSModulePath = $originalModulePath }
    if (Test-Path -LiteralPath $smokeLocalAppData -PathType Container) {
        Remove-Item -LiteralPath $smokeLocalAppData -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $smokeRoot -PathType Container) {
        Remove-Item -LiteralPath $smokeRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    Write-Host "First-run diagnostics were retained at: $diagnosticsRoot"
}
