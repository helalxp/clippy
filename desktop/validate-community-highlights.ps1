param(
    [string]$Python = "python",
    [switch]$BuildRuntime,
    [ValidateSet("cpu", "cuda")]
    [string]$Variant = "cuda"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

try {
    if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
        throw "Python command '$Python' was not found. Pass -Python with your Python executable."
    }

    Write-Host "=== Python environment ==="
    & $Python --version
    if ($LASTEXITCODE -ne 0) { throw "Python could not start." }

    Write-Host "=== Community Highlights focused tests ==="
    $TestFiles = @(Get-ChildItem -LiteralPath (Join-Path $RepoRoot "tests") -File -Filter "test_community_highlights*.py" |
        Sort-Object Name |
        ForEach-Object { $_.FullName })
    if ($TestFiles.Count -eq 0) { throw "No Community Highlights test files were found." }
    & $Python -m pytest -q @TestFiles
    if ($LASTEXITCODE -ne 0) { throw "Community Highlights tests failed." }

    Write-Host "=== Runtime dependency and Windows Credential Manager imports ==="
    & $Python -c "import fastapi, httpx, keyring, streamlink, websockets; from keyring.backends.Windows import WinVaultKeyring; print('FastAPI=' + fastapi.__version__); print('Streamlink=' + getattr(streamlink, '__version__', 'installed')); print('Windows credential backend=' + WinVaultKeyring.__name__)"
    if ($LASTEXITCODE -ne 0) { throw "A required dependency or Windows Credential Manager backend could not be imported." }

    Write-Host "=== FFmpeg availability ==="
    $Ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($Ffmpeg) {
        & $Ffmpeg.Source -version | Select-Object -First 1
        if ($LASTEXITCODE -ne 0) { throw "FFmpeg failed its version check." }
    } else {
        Write-Warning "FFmpeg was not found on PATH. Live capture validation cannot proceed until FFmpeg is installed or FFMPEG_PATH is configured."
    }

    if ($BuildRuntime) {
        Write-Host "=== Packaged Python runtime build: $Variant ==="
        & (Join-Path $PSScriptRoot "build-python-runtime.ps1") -Variant $Variant
        if ($LASTEXITCODE -ne 0) { throw "Packaged Python runtime build failed." }
    }

    Write-Host ""
    Write-Host "Focused Community Highlights preflight passed."
    Write-Host "Live Twitch/YouTube authorization, chat, capture timing, and candidate extraction still require the interactive smoke test in Clippy."
}
finally {
    Pop-Location
}
