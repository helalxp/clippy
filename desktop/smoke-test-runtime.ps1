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
$httpServerStdout = Join-Path $smokeRoot "runtime-http.stdout.log"
$httpServerStderr = Join-Path $smokeRoot "runtime-http.stderr.log"
$script:httpServerProcess = $null
$originalRuntimeSetupTestMode = $env:CLIPPY_RUNTIME_SETUP_TEST_MODE
$originalRuntimeSetupManifestBaseUrl = $env:CLIPPY_RUNTIME_SETUP_TEST_MANIFEST_BASE_URL
$originalRuntimeSetupReleaseBaseUrl = $env:CLIPPY_RUNTIME_SETUP_TEST_RELEASE_BASE_URL
$originalClippyTempDir = $env:CLIPPY_TEMP_DIR
$script:smokeRoot = $smokeRoot
$script:smokeLocalAppData = $smokeLocalAppData
$script:diagnosticsRoot = $diagnosticsRoot
$script:diagnosticsLog = $diagnosticsLog
$script:childContextLog = $childContextLog
$script:httpServerStdout = $httpServerStdout
$script:httpServerStderr = $httpServerStderr
$script:setupLog = $setupLog
$script:setupStdout = $setupStdout
$script:setupStderr = $setupStderr
$script:setupProcess = $null
$script:setupScript = $null
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
        @{ Path = $script:setupStderr; Name = "setup.stderr.log" },
        @{ Path = $script:httpServerStdout; Name = "runtime-http.stdout.log" },
        @{ Path = $script:httpServerStderr; Name = "runtime-http.stderr.log" }
    )
    if (-not [string]::IsNullOrWhiteSpace([string]$script:setupScript)) {
        $paths += @{ Path = $script:setupScript; Name = "setup-runtime.ps1" }
    }
    $lines = @()
    if (Test-Path -LiteralPath $script:diagnosticsLog -PathType Leaf) {
        $lines += "===== Smoke test startup context ====="
        $lines += Get-Content -LiteralPath $script:diagnosticsLog -Tail 100
    }
    $lines += "Child exit code: $(if ($script:setupProcess) { $script:setupProcess.ExitCode } else { 'not-started' })"
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
    Assert-ClippyRuntimeArchiveManifest -Manifest $runtimeManifest -ExpectedApplicationVersion $appVersion -ExpectedVariant cpu | Out-Null
    $cpuArchiveInfo = Get-Item -LiteralPath $CpuRuntimeArchive
    $cpuArchiveHash = Get-ClippyFileSha256 -Path $CpuRuntimeArchive
    $cpuArchiveExpandedSize = Get-ClippyZipUncompressedSize -Path $CpuRuntimeArchive
    if ([long]$runtimeManifest.archive.size -ne $cpuArchiveInfo.Length -or
        ([string]$runtimeManifest.archive.sha256).ToLowerInvariant() -ne $cpuArchiveHash -or
        [long]$runtimeManifest.archive.uncompressedSize -ne $cpuArchiveExpandedSize) {
        throw "CPU runtime ZIP does not match the release manifest that will be published."
    }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    New-Item -ItemType Directory -Path $smokeLocalAppData -Force | Out-Null
    New-Item -ItemType Directory -Path $smokeRoot -Force | Out-Null

    $runtimeDist = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "runtime-dist"))
    $httpPython = (Get-Command "python" -ErrorAction Stop).Source
    $portListener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $portListener.Start()
    $httpPort = [int]$portListener.LocalEndpoint.Port
    $portListener.Stop()
    $runtimeTestBaseUrl = "http://127.0.0.1:$httpPort"

    # Serve the exact runtime manifest and archive artifacts built by this run.
    # The setup script still executes the customer-facing manifest/download code.
    $script:httpServerProcess = Start-Process -FilePath $httpPython -ArgumentList @("-m", "http.server", [string]$httpPort, "--bind", "127.0.0.1") -WorkingDirectory $runtimeDist -PassThru -NoNewWindow -RedirectStandardOutput $httpServerStdout -RedirectStandardError $httpServerStderr
    $httpReady = $false
    for ($httpAttempt = 1; $httpAttempt -le 30; $httpAttempt++) {
        if ($script:httpServerProcess.HasExited) {
            throw "Local runtime asset server exited during startup with code $($script:httpServerProcess.ExitCode)."
        }
        try {
            $request = [System.Net.HttpWebRequest]::Create("$runtimeTestBaseUrl/clippy-python-cpu.manifest.json")
            $request.Method = "HEAD"
            $request.Timeout = 2000
            $response = $request.GetResponse()
            try { $httpReady = ([int]$response.StatusCode -eq 200) } finally { $response.Close() }
            if ($httpReady) { break }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $httpReady) {
        throw "Local runtime asset server did not serve the CPU release manifest: $runtimeTestBaseUrl"
    }
    Write-SmokeDiagnostic "Local runtime release assets are being served from $runtimeTestBaseUrl."

    $env:LOCALAPPDATA = $smokeLocalAppData
    # Deliberately remove the developer-only local archive override. This forces
    # setup-runtime.ps1 to download and validate the published release manifest.
    Remove-Item Env:CLIPPY_PYTHON_RUNTIME_ARCHIVE -ErrorAction SilentlyContinue
    Remove-Item Env:CLIPPY_PYTHON_RUNTIME_CHECKSUM -ErrorAction SilentlyContinue
    $env:CLIPPY_RUNTIME_SETUP_TEST_MODE = "1"
    $env:CLIPPY_RUNTIME_SETUP_TEST_MANIFEST_BASE_URL = $runtimeTestBaseUrl
    $env:CLIPPY_RUNTIME_SETUP_TEST_RELEASE_BASE_URL = $runtimeTestBaseUrl
    $env:CLIPPY_TEMP_DIR = $smokeRoot
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
    $script:setupScript = $setupScript

    # Verify that a script launched directly with -File returns its exit code
    # to Start-Process. The actual setup script is launched the same way.
    $exitProbeScript = Join-Path $smokeRoot "exit-code-probe.ps1"
    [IO.File]::WriteAllText($exitProbeScript, "exit 37", [Text.UTF8Encoding]::new($false))
    $exitProbeArguments = @(
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        ('"' + $exitProbeScript + '"')
    )
    $exitProbe = Start-Process -FilePath $powershell -ArgumentList $exitProbeArguments -Wait -PassThru -NoNewWindow
    if ($exitProbe.ExitCode -ne 37) {
        throw "Windows PowerShell direct -File invocation did not preserve child exit codes. Expected 37, got $($exitProbe.ExitCode)."
    }
    Write-SmokeDiagnostic "Direct Windows PowerShell -File invocation preserved the non-zero child exit code."

    $argumentList = @(
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        ('"' + $setupScript + '"')
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
    if ($null -ne $script:httpServerProcess -and -not $script:httpServerProcess.HasExited) {
        Stop-Process -Id $script:httpServerProcess.Id -Force -ErrorAction SilentlyContinue
    }
    $root = Join-Path $smokeLocalAppData "Clippy"
    $pythonExe = Join-Path $root "runtime\python\python.exe"
    $nodeExe = Join-Path $root "runtime\node\node.exe"
    $ffmpegExe = Join-Path $root "runtime\ffmpeg\bin\ffmpeg.exe"
    $ffprobeExe = Join-Path $root "runtime\ffmpeg\bin\ffprobe.exe"
    $browserExe = Join-Path $root "browser\headless-shell\chrome-headless-shell.exe"
    $manifestPath = Join-Path $root "runtime-manifest.json"
    Save-SmokeDiagnostics

    if ($process.ExitCode -ne 0) {
        throw "First-run runtime setup failed with exit code $($process.ExitCode). Full diagnostics were retained at $diagnosticsRoot."
    }

    if (-not (Test-Path -LiteralPath $childContextLog -PathType Leaf)) {
        throw "Runtime setup did not write its early child-context diagnostic."
    }
    $childContext = Get-Content -LiteralPath $childContextLog -Raw
    if (-not $childContext.Contains("PSModuleAutoLoadingPreference=None") -or
        -not $childContext.Contains($isolatedModulePath)) {
        throw "Runtime setup did not execute with module auto-loading disabled and the isolated module path."
    }

    $setupLogText = if (Test-Path -LiteralPath $setupLog -PathType Leaf) {
        Get-Content -LiteralPath $setupLog -Raw
    } else {
        ""
    }
    if ($setupLogText -notmatch 'PowerShell module auto-loading preference: None' -or
        $setupLogText -notmatch 'Windows PowerShell built-in modules were imported during bootstrap') {
        throw "Runtime setup log did not confirm explicit PowerShell module initialization."
    }

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
        @{ path = $ffprobeExe; label = "managed FFprobe" },
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
    if ([string]$installedManifest.gpuMode -ne "cpu") {
        throw "First-run CPU smoke test installed unexpected GPU mode '$($installedManifest.gpuMode)'."
    }

    & $pythonExe -c "import app, torch, fastapi, faster_whisper; assert torch.version.cuda is None; print('Backend imports and CPU runtime OK:', torch.__version__)"
    if ($LASTEXITCODE -ne 0) { throw "Managed Python backend import smoke test failed." }

    # Run outside the Clippy payload and checkout directories. With an embedded
    # python312._pth file, this import must succeed because the managed app path
    # is explicitly configured, not because the process happens to be in app\current.
    $expectedAppRootLiteral = ConvertTo-Json -InputObject ([IO.Path]::GetFullPath($appDirectory)) -Compress
    $appPathCheck = "import app, os; expected = os.path.normcase(os.path.join($expectedAppRootLiteral, 'app.py')); actual = os.path.normcase(os.path.abspath(app.__file__)); assert actual == expected, 'Imported app.py from an unexpected path: ' + actual; print('Clippy app import path OK:', actual)"
    Push-Location $smokeRoot
    try {
        & $pythonExe -c $appPathCheck
        if ($LASTEXITCODE -ne 0) { throw "Managed Python could not import app.py from the configured Clippy application path." }
    } finally {
        Pop-Location
    }
    & $nodeExe --version
    if ($LASTEXITCODE -ne 0) { throw "Managed Node.js executable smoke test failed." }
    & $ffmpegExe -version *> $null
    if ($LASTEXITCODE -ne 0) { throw "Managed FFmpeg executable smoke test failed." }
    & $ffprobeExe -version *> $null
    if ($LASTEXITCODE -ne 0) { throw "Managed FFprobe executable smoke test failed." }
    if ([string]$installedManifest.components.node.version -ne "22.23.5") {
        throw "Clean first-run setup installed an unexpected Node.js version: $($installedManifest.components.node.version)"
    }

    Write-Host "Clean first-run runtime smoke test passed for Clippy $appVersion."
} catch {
    $failureMessage = $_.Exception.Message
    try { Save-SmokeDiagnostics -FailureMessage $failureMessage } catch {
        Write-Host "Could not write complete diagnostics: $($_.Exception.Message)"
    }
    throw
} finally {
    if ($null -ne $script:httpServerProcess -and -not $script:httpServerProcess.HasExited) {
        Stop-Process -Id $script:httpServerProcess.Id -Force -ErrorAction SilentlyContinue
    }
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
