# Clippy native desktop (Windows installer work)

The native desktop target is separate from the Docker developer workflow.
Docker Compose is not used by the installed application.

## Build the Windows installer

On a Windows build machine, install the Rust stable toolchain, Node.js LTS,
Tauri 2 Windows prerequisites (including WebView2), and NSIS prerequisites.
Then run this from the repository root:

    git pull origin windows-installer-release
    powershell -ExecutionPolicy Bypass -File .\desktop\build.ps1

The script resolves paths relative to itself, installs locked dashboard
dependencies, and asks Tauri to create an NSIS installer. Output is expected
under desktop\src-tauri\target\release\bundle\nsis.

IMPORTANT: the current build produces the desktop shell and frontend bundle
only. It is NOT yet a complete end-user installer. The managed Python/Node/
FFmpeg runtime, Python packages, compiled renderer payload, Remotion browser
runtime, and first-run download/repair flow still need to be integrated and
tested before distributing it as a working Clippy application.

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
