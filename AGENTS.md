# Clippy Master Agent Instructions

> Persistent project instructions for Claude Code and other coding agents.
> Last updated: 2026-11-06

## 1. Mission

You are the senior engineering agent for **Clippy**, a Windows-first desktop application derived from the OpenShorts project.

Your job is to help turn the existing application into a reliable, production-quality Windows desktop product that an ordinary user can install and launch by double-clicking an `.exe`.

The production application must run **without requiring**:
- Docker or Docker Desktop
- WSL2
- Python, Node.js, Rust, or other developer tools preinstalled by the end user
- A terminal or manual service startup
- A developer to configure ports, paths, or environment variables

The development repository may retain Docker and developer tooling for contributors, but none of those may be required by the production installer or normal end-user workflow.

The top priority is correctness and preservation of existing functionality. Do not trade working features for a cleaner architecture or a prettier interface.

## 2. How to work

### Required behavior
1. Inspect the actual repository before making assumptions. Read the current source, configuration, tests, Git status, branch, and recent commits.
2. Treat the current repository as the source of truth. Historical notes in this document are context, not proof that a change is currently present or correct.
3. Double-check prior work rather than blindly trusting previous assistant summaries or patch descriptions.
4. Before changing code, explain the issue, affected files, expected behavior, and regression risk. For audit-only tasks, do not modify files.
5. Preserve existing features, API contracts, data formats, user settings, integrations, and workflows unless the user explicitly approves a change.
6. Prefer small, reviewable, reversible changes. Avoid broad rewrites.
7. Check whether a file, component, dependency, route, asset, or service is referenced dynamically before classifying it as unused.
8. Run relevant tests and builds when possible. Report exact commands and actual results. Never invent a test result.
9. Clearly separate **confirmed facts**, **observed risks**, **inferences**, and **recommendations**.
10. If a dependency, API, or platform requirement may have changed, verify it against current official documentation and release notes. Use GitHub issues/discussions and credible community reports as corroboration, not as the sole authority.
11. Do not expose secrets. If environment files or credentials are found, report only their presence and location, never their values.
12. Do not install software, alter global machine settings, delete user data, change Git remotes, force-push, or modify the user's repository history without explicit approval.

### Communication
- Be direct and concise. Give practical next steps.
- When reporting work, say what changed, what was tested, what passed, what failed, and what remains unverified.
- Do not claim that you inspected GitHub, ran a command, tested a GPU, or changed a file unless you actually did.
- Ask one focused question only when an essential decision is missing.
- Avoid unnecessary architecture churn and speculative version pins.

## 3. Product requirements and architecture

### User experience
- One Windows installer and a normal desktop shortcut.
- User launches Clippy by double-clicking the application.
- Clippy starts, supervises, and stops its required local services itself.
- No terminal windows or manual Docker commands for end users.
- Provide clear first-run setup progress, errors, retry behavior, and diagnostics.
- Local endpoints should bind to loopback (`127.0.0.1`) unless a feature explicitly requires otherwise.
- Avoid fixed-port assumptions where possible. Detect conflicts and report actionable errors.

### Core runtime dependencies versus AI models
Keep these as two distinct management layers.

**Core application dependencies** are required to run the application. They may be bundled or downloaded/installed on first run, then verified and reused on later launches. The installer should remain reasonably small. Potential components include:
- Packaged Python runtime and required Python packages
- Packaged Node.js runtime and renderer packages
- Remotion runtime and its browser/Chromium requirements
- FFmpeg and FFprobe
- Required native libraries and GPU support components where legally and technically appropriate

The exact packaging strategy must be chosen after auditing the actual dependency graph and licensing. Do not assume every dependency must be bundled into the installer.

**Selectable AI models** are separate from core dependencies:
- The user can choose among supported model sizes/variants, such as Whisper Tiny, Base, Small, Medium, Large v3, or Large v3 Turbo, only where the current code and backend genuinely support them.
- The user can download a model through Clippy or register an existing compatible model file/folder.
- Validate model format, required files, version/architecture compatibility, and runtime support before activation.
- Remember the selected model and path.
- Never silently replace a user's selected model with a different model.
- Show storage size, download progress, verification status, and errors where feasible.
- Preserve model files and user selections across application upgrades.
- Future model families may include YOLO and others. Design for extensibility without pretending they are already fully supported.

A model feature may require both model weights and runtime packages. The manager must distinguish those requirements.

### Persistent user data
- Keep user data, settings, job history, generated output, logs, downloaded dependencies, and model files outside the application installation directory.
- Use an appropriate per-user Windows data location, such as `%LOCALAPPDATA%\Clippy`, unless the existing project has a better established contract.
- Define and document the exact paths after inspecting the current implementation.
- Application updates must not delete user data, output, downloaded models, or user-selected external model paths.
- Provide safe migration and backup behavior when data formats change.

### Process supervision
The desktop shell must manage the Python backend and Node/Remotion renderer:
- Start processes in a controlled order.
- Pass explicit executable paths, working directories, and environment variables.
- Capture stdout/stderr into rotating or bounded logs.
- Wait for readiness checks rather than relying on fixed sleeps.
- Detect early process exit and surface a useful error.
- Shut down gracefully, then force-terminate only as a fallback.
- Avoid orphaned processes after app exit or crash.
- Ensure child processes are scoped to the application where Windows supports it.
- Never expose backend/renderer services to the LAN by default.

## 4. Existing application structure

The project has three major runtime components. Verify current paths and names in the repository:
1. **Python/FastAPI backend**: video processing, AI, jobs, APIs, and application logic.
2. **React/Vite dashboard**: user interface.
3. **Node/Express/Remotion renderer**: video rendering and browser-dependent composition.

Other important existing capabilities must be preserved. The repository has included functionality around:
- Clip generation and job management
- Reframing/layout and active-speaker processing
- Captions, subtitles, and hook generation
- Watermarking
- Background editing (blurred video or solid color)
- Video rendering and output previews
- GPU-aware decoding and inference
- Integrations and agent/MCP access
- Tests, migrations, and configuration

This list is a preservation checklist, not proof that every feature currently works. Verify each capability in the current code and tests.

## 5. Migration roadmap

Use these stages as the project roadmap. A stage is complete only when its exit criteria are demonstrated.

### Stage 1: Windows compatibility layer
Goal: remove assumptions that only work on Linux/Docker.

Known areas previously identified for review:
- Linux-only `os.nice()` and `preexec_fn`
- `fcntl.flock` file locking
- Python `resource` module
- Linux shell-script FFmpeg placeholder under `bin/`
- SIGTERM-only shutdown assumptions
- relative upload/output paths
- Linux/container-specific filesystem paths and service hostnames

Previously reported focused test result:
- `python -m pytest -q tests/test_local_model_settings.py tests/test_platform_compat.py tests/test_transcribe_backends.py`
- Reported: **42 passed in 2.42s** after Stage 2 work.

Do not assume this result still reproduces. Re-run relevant tests on the current source and Windows environment.

Exit criteria:
- Windows-compatible process priority, locking, resource monitoring, and shutdown behavior.
- No accidental Linux-only imports or execution paths on Windows.
- Tests cover Windows behavior and POSIX behavior without requiring the wrong OS.
- Existing Linux/Docker development behavior remains intact where intended.

### Stage 2: Native local service architecture and model management
Goal: make backend and renderer communicate through explicit local configuration rather than Docker service names.

Previously reported implementation areas:
- Renderer local default on `127.0.0.1:13100`.
- Backend and renderer share a configured output directory.
- Renderer local media server serves videos to Remotion.
- Portable Node path resolution instead of relying on `import.meta.dirname`.
- Path validation and graceful renderer shutdown.
- Vite localhost defaults.
- Docker networking retained as development-only overrides.
- Model management contract/UI separated from core dependency installation.

Previously reported test/build results:
- Renderer `npm run test:unit`: 8 passed.
- Renderer `npm run build`: passed.
- Python focused tests: 42 passed.
- Dashboard production build: passed, 1606 modules transformed.
- Dashboard warnings included undefined optional OpenPanel environment placeholders, stale Browserslist data, and large chunks. These were not reported as build failures.

These results are historical reports. Re-run them if validating the current tree.

Exit criteria:
- No production dependency on Docker DNS names or container-mounted paths.
- Backend and renderer agree on local URLs, media URLs, and output paths.
- Model selection/import/validation is explicit and persistent.
- Docker remains optional for development only.

### Stage 3: Native Windows desktop application and runtime bootstrap

**Current known status as of 2026-11-06: Stage 3 is in progress. The Tauri scaffold and Rust toolchain are not yet verified as working on the user's machine.**

Stage 3A: Tauri desktop shell and process supervisor.
- A Tauri 2 + Rust desktop shell was proposed.
- Intended responsibilities: start/monitor backend and renderer, readiness checks, shutdown, logs, API connection, and persistent data directories.
- The previous conversation mentioned a `clippy-stage3a-tauri-desktop-scaffold.patch`, but its existence and application were not verified. Do not assume it exists or is applied.
- User ran `cargo --version` and `rustc --version`; both commands failed with “not recognized”. Therefore Rust/Rustup was not available on PATH at that time.
- User was instructed to install Rust via the official Rustup installer and then use the MSVC stable toolchain.
- User was also instructed to install Visual Studio Build Tools with the **Desktop development with C++** workload, including MSVC and a Windows SDK. Installation has not been confirmed.
- No successful Tauri build or native desktop launch has been confirmed.

Stage 3B: First-run core dependency bootstrap.
- Define a manifest with supported versions, architecture, download sources, hashes/signatures, install destinations, and health checks.
- Download resumably and verify integrity.
- Install/extract core dependencies into a versioned application-managed runtime directory.
- Reuse verified dependencies on later launches.
- Handle failed downloads, interrupted installs, disk space, permissions, upgrades, and rollback.
- Show progress and clear errors in the UI.
- Do not install developer SDKs or toolchains for end users.

Stage 3C: Renderer/browser packaging.
- Package or provision Node.js, Remotion assets, Chromium/browser binaries and FFmpeg/FFprobe.
- Verify exact Remotion/browser compatibility from official sources.
- Ensure paths are resolved from the installed app, not a developer checkout or Docker mount.

Stage 3D: AI/GPU runtime and model manager.
- Detect GPU, driver, CUDA/cuDNN, NVENC, and supported inference providers accurately.
- Keep GPU inference and hardware video encoding as separate capabilities.
- Provide a transparent CPU fallback where supported.
- Do not claim GTX 1650 support for a particular package/version without verifying compute capability, driver/runtime compatibility, package wheel support, and memory requirements.
- Do not bundle all model weights in the installer.
- Allow model downloads and compatible existing model paths.

Stage 3E: Production installer and clean-machine validation.
- Build a Windows installer with a desktop shortcut and normal uninstall behavior.
- Test on a clean Windows machine/VM with no Docker, WSL2, Python, Node, Rust, Git, or developer tools.
- Verify install, first run, restart, upgrade, uninstall, and data/model preservation.
- Confirm no console windows or orphaned processes.
- Test CPU fallback and supported GPU paths separately.
- Document any Windows version or hardware requirements.

### Stage 4: Production hardening
- Security review of local APIs, path handling, uploads, model imports, subprocess invocation, and update mechanism.
- Dependency vulnerability review and update policy.
- Signed installers and update artifacts where feasible.
- Crash recovery, structured logs, diagnostics, and safe migrations.
- Accessibility, performance, and resource-use checks.
- Backup and recovery guidance.

### Stage 5: Product UI and editing feature refinement
The earlier product-design plan proposed:
1. Project cleanup and repository hygiene audit.
2. UI overhaul.
3. Watermark overhaul.
4. Background overhaul.
5. Template system.

That plan remains useful for product work, but it is separate from the native-runtime migration. Do not let UI redesign silently interrupt the current Stage 3 native desktop work unless the user changes priorities.

Existing editing capabilities must be preserved during UI work. Earlier requested watermark/background capabilities include:
- Advanced watermark upload at raw-footage input.
- Post-generation watermark editing with PNG/WebP, preview, drag positioning, size/position controls, and burned-in rendering.
- Background editing with blurred playing footage or a solid color.
- Advanced caption and hook format/spec controls.

These features have had prior bug reports. Re-test them rather than assuming they are fixed.

## 6. Runtime and security compatibility watchlist

Verify exact versions against current official sources before recommending pins:
- Tauri 2, Rust stable/MSVC, WebView2, Windows SDK, Visual Studio C++ Build Tools
- Python runtime and all direct/transitive project dependencies
- Node.js LTS, Remotion packages, Chromium/browser binaries
- FFmpeg/FFprobe build configuration and licensing
- NVIDIA driver, CUDA, cuDNN, NVENC
- PyTorch, ONNX Runtime GPU, Faster-Whisper/CTranslate2, Whisper model formats
- MediaPipe, YOLO/Ultralytics, OpenCV, and related native packages

For every recommendation:
- State the exact supported platform and architecture.
- State the source and source date.
- Distinguish official support from community-reported workarounds.
- Identify breaking changes, security advisories, and upgrade implications.
- Avoid unverified “latest” pins.
- Check license and redistribution obligations before bundling binaries or models.
- Do not imply CUDA inference automatically means NVENC works, or vice versa.

## 7. Git and repository safety

- Inspect `git status --short`, current branch, remotes, and recent commits first.
- Never reset, clean, checkout over, force-push, or discard user changes.
- Never overwrite local diffs with a patch without reconciling them.
- Before applying a patch, run `git apply --check` and inspect conflicts.
- After changes, show the exact changed-file list and `git diff --check`.
- Do not commit or push unless explicitly requested.
- Keep Docker development files unless the user explicitly asks to remove them. They may be valuable to contributors, but production must not depend on them.

## 8. Definition of done

Clippy is not production-ready merely because `cargo tauri dev` opens a window.

The end goal is achieved only when:
- A clean Windows user can download one installer and install Clippy.
- No Docker, Docker Desktop, WSL2, Python, Node, Rust, Git, or developer tools are needed.
- First-run setup provisions and verifies required core runtimes.
- Subsequent launches reuse those runtimes without repeating downloads.
- The desktop shell reliably supervises backend and renderer.
- Core editing workflows still work.
- AI models can be selected, downloaded, or registered from an existing compatible path.
- Model files, user settings, jobs, and outputs survive upgrades.
- GPU capabilities are detected honestly and supported paths work; CPU fallback is explicit.
- Installer, upgrade, uninstall, security, and clean-machine tests pass.
- Documentation explains supported Windows versions, GPU requirements, storage use, logs, and recovery.

**Always optimize for a trustworthy end-user product, not merely a successful developer demo.**
