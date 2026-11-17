# Clippy native first-run setup contract

This document defines the production behavior for the native Windows installer
and launcher. Docker Compose is developer-only and is not part of the installed
application, runtime checks, or end-user instructions.

## Two separate installation tracks

### Core application dependencies

The desktop bootstrapper owns these dependencies. On first launch it must:

1. Check the installed runtime manifest and detect missing or mismatched files.
2. Show a first-run setup screen before starting the backend or renderer.
3. Explain that this is a one-time setup and show each component's status,
   download progress, and errors.
4. Install the required application runtimes and libraries into Clippy-managed
   directories under `%LOCALAPPDATA%\Clippy\runtime` (or a versioned app
   runtime directory), not into the user's global PATH.
5. Verify checksums/signatures where the upstream distribution provides them,
   then verify each installed component can start.
6. Write a completed runtime manifest only after verification succeeds.
7. On later launches, validate the manifest and start immediately. Do not
   redownload healthy components. Download only for a version change, missing
   files, or an explicit repair action.

The runtime manifest is versioned with Clippy. Updates should reuse compatible
components and download only changed components. The setup must be resumable
after interruption and must not delete user data or model files.

Expected managed components include the embedded Python runtime and required
Python packages, Node runtime and renderer packages, FFmpeg/FFprobe, the
Remotion browser runtime, and compatible GPU runtime libraries when needed.
The Windows implementation stages the application payload, persistent Remotion browser version/hash metadata, and pinned bgutil YouTube PO-token provider into the managed install layout. It extracts the app payload to `%LOCALAPPDATA%\\Clippy\\app\\current` on first launch.
Python 3.12.10 and the complete pinned Python dependency set are built on
Windows CI into separate CPU and NVIDIA/CUDA 12.8 runtime packages. Each package
has a versioned manifest containing the complete archive size/hash and the
ordered part list. The CPU package is currently a single ZIP; the larger CUDA
package is published as binary parts. Setup downloads the manifest and every
listed part from the exact matching release, validates each part's size and
SHA-256, reconstructs the original ZIP with streaming I/O, verifies the complete
archive, extracts to a staging directory, checks the interpreter and critical
imports, and only then activates it. Customer machines do not run pip or
bootstrap Python packages. Node.js 22.23.3 and FFmpeg essentials are provisioned
as private runtimes and verified against publisher SHA-256 sidecars. The
version-matched Remotion headless browser is installed and hash-checked during
first-run setup. The runtime state manifest is written only after all required
components pass verification.

A Microsoft Visual C++ x64 redistributable may require a one-time UAC approval
on machines where that runtime is missing. The v0.2.3 release workflow now
passes the clean first-run setup and packaged-render smoke test, in addition to
the runtime package and contract checks. A real Windows installation was also
manually exercised through the editing workflow. This evidence establishes the
v0.2.3 baseline; it does not replace future testing of new versions, additional
hardware/driver combinations, interrupted setup, or repair behavior.

The native launcher deliberately starts Windows PowerShell 5.1 with an isolated
module search path: the Rust process builder removes an inherited
`PSModulePath` before spawning `powershell.exe`. This prevents module paths
from a parent PowerShell 7 process from contaminating the Windows PowerShell
child. The CI smoke test probes this exact child host before performing setup.

### AI model weights

Model weights are not core application dependencies. They live in a separate,
persistent model directory and are configured per feature.

Whisper specifically supports:
- selecting one of Clippy's supported faster-whisper model sizes and
  downloading it from the in-app model manager;
- selecting an already-downloaded faster-whisper model directory, or its
  `model.bin` file, from another location;
- validating the model layout before saving the selection;
- remembering the selected model across application updates;
- warning if a previously selected external folder is no longer available.

A missing selected local model must produce an actionable error. Clippy must
not silently switch to a different model.

## Data and packaging boundaries

- Installer contains the desktop shell and bootstrapper, not Docker images.
- No Docker Desktop, WSL2, container engine, system Python, or system Node
  installation is required from the end user.
- Runtime dependencies are installed once by the bootstrapper and retained
  across normal launches and app updates when compatible.
- User projects, generated videos, settings, caches, and downloaded models
  remain outside the application install directory.
- Model downloads and runtime dependency downloads must be reported separately
  in the UI because they have different lifecycles.
