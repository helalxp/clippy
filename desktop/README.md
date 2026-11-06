# Clippy native desktop (Stage 3A)

This is the first native desktop shell and local-process supervisor. It is a
separate production target; Docker Compose remains a developer-only workflow
and is not invoked by this application.

## Current scope

- Tauri 2 Windows desktop shell using the existing dashboard build.
- Desktop dashboard build sets `VITE_API_URL` to the loopback FastAPI service.
- Rust commands expose start, stop, and status for the backend and renderer.
- Services bind to `127.0.0.1`; logs are written under `%LOCALAPPDATA%\Clippy\logs`.
- Runtime files, application payload, and user output are separated under
  `%LOCALAPPDATA%\Clippy`.
- Startup refuses to launch when the managed runtime or application payload is
  incomplete. It does not silently use a system Python or Node installation.

## Deliberate limitation in Stage 3A

The downloader, signed/checksummed runtime manifest, resumable installer UI,
application payload updater, and production NSIS packaging pipeline are not
implemented yet. `start_services` is therefore an integration scaffold and
will report that setup is required until Stage 3B installs the expected files.
No claim is made that this stage is already a usable end-user installer.

## Developer prerequisites

For desktop development only, install the Rust stable toolchain, the Tauri 2
Windows prerequisites (including WebView2), and the Node.js toolchain. These
are build-machine requirements, not end-user requirements.

From `desktop/src-tauri`:

```powershell
cargo install tauri-cli --version "^2"
cargo tauri dev
```

Build the Windows installer with:

```powershell
cargo tauri build
```

The Tauri build invokes `dashboard`'s `build:desktop` script. The dashboard
uses `http://127.0.0.1:8000` for API requests in the desktop build; the normal
Vite development build retains its proxy-based relative API behavior.

## Managed directory layout (target)

```text
%LOCALAPPDATA%\Clippy\
  app\current\                 # versioned Clippy application payload
    app.py
    render-service\dist\server.js
    remotion\src\index.ts
  runtime\
    python\python.exe
    node\node.exe
  data\output\                 # projects and generated media
  models\                      # independently managed AI model weights
  logs\
```

The Whisper model manager remains separate from core runtime setup. Model
weights are not part of the core dependency manifest.
