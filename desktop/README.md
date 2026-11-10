# Clippy native desktop (Windows installer work)

The native desktop target is separate from the Docker developer workflow.
Docker Compose is not used by the installed application.

## Build the Windows installer

On a Windows build machine, install the Rust stable toolchain, Node.js LTS,
Tauri 2 Windows prerequisites (including WebView2), and NSIS prerequisites.
Then run this from the repository root:

    git fetch origin
    git switch windows-installer-release
    git pull --ff-only origin windows-installer-release
    powershell -ExecutionPolicy Bypass -File .\desktop\build.ps1

The script resolves paths relative to itself, builds the dashboard, compiles
the renderer, stages the backend and Remotion source with their production
Node dependencies, and asks Tauri to create an NSIS installer. On first launch,
the app extracts that payload to the per-user Clippy directory. Output is
expected under desktop\src-tauri\target\release\bundle\nsis.

IMPORTANT: this is still an engineering preview, not yet a production release.
The first-run script now provisions private Python, Node.js, FFmpeg, Python
packages, PyTorch (CUDA 12.6 on detected NVIDIA systems, CPU otherwise), and
Remotion's browser runtime. It verifies upstream signatures/checksums and
records the installed runtime state. The complete flow still needs clean-
machine testing, including dependency compatibility, UAC behavior, interrupted
downloads, GPU variants, and repair before distribution.

## Expected managed service layout

    %LOCALAPPDATA%\Clippy\
      app\current\
        app.py
        render-service\dist\server.js
        remotion\src\index.ts
      runtime\
        python\python.exe
        node\node.exe
      data\output\
      logs\

User output, projects, settings, caches, and downloaded model weights must
remain outside the application install directory. AI model weights are not
core runtime dependencies and must not be bundled into the installer.

## Developer prerequisites

For desktop development, install Rust stable, Tauri 2 Windows prerequisites,
WebView2, Node.js LTS, and npm. From desktop/src-tauri:

    cargo tauri dev

The packaged dashboard build sets VITE_API_URL to
http://127.0.0.1:8000. The normal web development build retains its Vite
proxy-based relative API behavior.
