# Clippy native Windows desktop

Clippy is the native Windows desktop distribution maintained in this repository. The desktop app is separate from the Docker Compose workflow documented in the repository root.

## Download and install

**Current stable release: [Clippy v0.2.3](https://github.com/helalxp/clippy/releases/tag/v0.2.3)**

Download and run the [x64 NSIS installer](https://github.com/helalxp/clippy/releases/download/v0.2.3/Clippy_0.2.3_x64-setup.exe). The installer is per-user and installs without requiring Docker Desktop, WSL2, system Python, or system Node.js.

The first launch requires an internet connection. Clippy extracts its application payload and runs the managed runtime setup. It selects the CPU Python package by default, or the CUDA 12.8 package when the NVIDIA driver and GPU compute capability meet the supported checks. It then provisions the remaining private components, verifies them, and writes the runtime manifest only after health checks pass.

Customers should download the installer only. The matching release contains the CPU and CUDA runtime archives/manifests/parts that setup retrieves automatically from the exact application version. Do not manually download, rename, recompress, or combine those runtime assets.

## What is installed and where

The managed root is:

```text
%LOCALAPPDATA%\Clippy\
  app\current\                 # replaceable application payload
  runtime\
    python\                       # managed Python and pinned packages
    node\                         # managed Node.js
    ffmpeg\                       # FFmpeg and FFprobe
  browser\headless-shell\       # persistent Remotion browser
  data\
    output\                       # generated outputs
    uploads\                      # uploaded source media
    models\whisper\             # separately managed Whisper models
    models\huggingface\         # Hugging Face cache
    reference_templates\
  settings.json
  runtime-manifest.json
  logs\
```

The app payload and runtime components are managed separately from user data. Settings, uploads, generated output, reference templates, caches, and model weights must survive normal application upgrades and runtime repair. Model weights are not bundled into the installer.

## Troubleshooting and diagnostics

The first place to look after a setup or launch failure is:

```text
%LOCALAPPDATA%\Clippy\logs\runtime-setup.log
```

The desktop shell also records native setup and supervisor diagnostics in the same Clippy logs directory. Preserve the complete log when reporting a problem; include the release version, Windows version, CPU/GPU model, NVIDIA driver version when relevant, and the exact step that failed. Do not delete the whole `%LOCALAPPDATA%\Clippy` directory as a first troubleshooting step: it contains user settings, generated media, downloads, and model weights.

The release smoke test intentionally launches Windows PowerShell 5.1 from a PowerShell 7 CI host. Both the application launcher and smoke-test launcher remove the inherited `PSModulePath` before creating that child process, allowing Windows PowerShell to initialize its own compatible module path. The smoke test has a preflight that checks the host edition/version and verifies that `Get-FileHash` and `ConvertFrom-Json` resolve before first-run setup begins. Keep this boundary covered if process-launch code changes.

## Build the Windows installer from source

Use a Windows x64 build machine with:

- Rust stable and the Tauri 2 Windows build prerequisites.
- WebView2 runtime/developer prerequisites.
- Node.js 22 and npm.
- Python 3.12.10 for runtime packaging.
- NSIS and PowerShell 7 (the CI workflow uses `pwsh`); Pester 5 for the PowerShell tests.

From the repository root:

```powershell
./desktop/validate-version.ps1
./desktop/build.ps1
```

The build script resolves paths relative to itself, builds the desktop dashboard, prepares the backend and renderer payload, and produces an NSIS installer under:

```text
desktop\src-tauri\target\release\bundle\nsis
```

To run the native desktop app during development, install the prerequisites above and run:

```powershell
cd desktop/src-tauri
cargo tauri dev
```

The packaged dashboard receives its backend URL and per-launch API token from the desktop supervisor. The regular web/Docker development build continues to use the Vite proxy.

## CI and release gates

Two GitHub Actions workflows protect this path:

- `.github/workflows/windows-desktop-validation.yml` validates version synchronization, builds the dashboard and payload, runs PowerShell contract tests, checks Python syntax, runs Rust checks/tests, and builds the complete NSIS installer.
- `.github/workflows/release-windows.yml` runs backend/frontend validation, builds CPU and CUDA runtime packages, checks manifests and reconstructed archives, builds the installer, runs the clean first-run/runtime/render smoke test, runs Rust tests, creates a draft release, verifies all expected asset names and sizes, and only then publishes.

The smoke test is deliberately stronger than a script syntax test. It extracts the exact packaged payload into an isolated `LOCALAPPDATA`, runs the real first-run setup using the CPU runtime, verifies the managed runtime manifest and backend imports, renders a fixture through the packaged Remotion browser, and reruns setup to verify that a healthy install is reused without downloads.

See [RELEASING.md](../RELEASING.md), the [first-run setup contract](FIRST_RUN_SETUP_CONTRACT.md), and the [Windows installer operations runbook](../docs/architecture/windows-installer-operations-runbook.md) before changing packaging or release logic.
