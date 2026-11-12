# Windows Installer and Update Architecture

Status: migration design for `windows-installer-release`
Scope: Windows desktop packaging, runtime delivery, installation, repair, and updates.
Out of scope for this migration: accounts, billing, cloud authorization, and brand workspaces.

## Goals

1. A customer downloads one signed Windows setup executable.
2. The first installation does not need to download Python, Node, FFmpeg, PyTorch, Python packages, renderer packages, or the Remotion browser.
3. Clippy uses only its own managed runtimes. System Python, the Python launcher, system Node, and user PATH entries must not affect it.
4. Normal application updates do not redownload large, unchanged AI runtimes.
5. User data, generated videos, settings, logs, and model weights survive application updates and repairs.
6. Installation and update operations are staged, verified, recoverable, and observable.
7. The existing video pipeline and exported media behavior remain unchanged.

## Current implementation (verified on windows-installer-release)

- Tauri 2 builds an NSIS installer.
- `prepare-payload.ps1` stages Python source, requirements, assets, renderer output, Remotion source, and production Node dependencies into `app-payload.zip`.
- The Tauri installer embeds that application payload and its SHA-256 file.
- On first launch, `setup-runtime.ps1` downloads and installs Python 3.12.10, Node 22.23.3, FFmpeg essentials, PyTorch, the remaining Python requirements, and the Remotion browser.
- The runtime is installed under `%LOCALAPPDATA%\Clippy\runtime`; application payload is extracted under `%LOCALAPPDATA%\Clippy\app\current`.
- The current release notes describe a manual installer update. There is no configured Tauri updater in the inspected Tauri configuration.
- The current installer payload hash detects accidental corruption, but it is not a publisher signature or a complete software-update trust chain.
- The setup script chooses CUDA 12.6 PyTorch if `nvidia-smi` succeeds and otherwise chooses CPU PyTorch. Thus the installed runtime is not currently a fully prebuilt, hardware-independent package.

## Target installation layout

Keep the install root private to Clippy and keep mutable user data outside versioned application files.

```text
%LOCALAPPDATA%\Clippy\
  app\
    versions\
      <app-version>\
        desktop web assets, backend source, renderer, app metadata
    current.json
  runtime\
    python\<runtime-version>\
    node\<runtime-version>\
    ffmpeg\<runtime-version>\
    python-packages\<dependency-set-id>\
    remotion-browser\<browser-version>\
    gpu\<gpu-runtime-set-id>\
  data\
    uploads\
    output\
    models\
  settings.json
  logs\
  cache\
  update-staging\
  runtime-manifest.json
```

The precise directory names may be adjusted during implementation, but immutable versioned components must not be overwritten in place. A small active-version pointer selects the currently active application/runtime set.

## Initial installer

Build the complete, tested Windows payload in CI or on a controlled release build machine. The customer installer must not run pip, npm, or download dependency installers on first launch.

Package and validate:
- Python 3.12 runtime and all pinned Python dependencies, including the selected PyTorch build.
- Node runtime and production renderer/Remotion dependencies.
- FFmpeg and FFprobe.
- The exact Remotion browser binary.
- Backend source and dashboard assets.
- Required native redistributables or a documented signed prerequisite flow.

Do not bundle user-selected Whisper/model weights in the core installer. They are large, user-specific, and have their own download/update lifecycle.

GPU packaging decision:
- Produce a CPU build and an NVIDIA/CUDA build if one universal payload would unnecessarily ship both PyTorch variants.
- The NVIDIA build must be validated against the supported driver floor and the CUDA runtime it bundles.
- Do not silently fall back from CUDA to CPU after a CUDA package or GPU initialization failure. Surface a clear diagnostic and make any fallback an explicit supported recovery path.
- Do not bundle NVIDIA display drivers. The customer must have a compatible vendor driver.

The build must pin all dependency versions and record the source URL, version, architecture, SHA-256, and license for each redistributable component. Generate an SBOM and retain build provenance with each release.

## Update architecture

Do not embed every large runtime component inside the object that the application updater replaces.

Use two coordinated update layers:

### Layer A: desktop shell update

Use the Tauri updater for the relatively small signed desktop shell update. Configure a stable update endpoint, platform target, version, and public verification key. Keep the private signing key outside the repository and CI logs.

### Layer B: application component updater

Maintain a signed release manifest describing independently versioned components:
- desktop web assets and application source;
- Python application code;
- Python dependency set;
- Node runtime;
- renderer and Remotion dependencies;
- FFmpeg;
- Remotion browser;
- GPU runtime set.

Each manifest entry must include component ID, semantic version, compatible app/runtime ranges, archive URL, compressed size, SHA-256, and signature metadata.

The client compares installed component IDs and hashes to the manifest. It downloads only missing or changed components. Unchanged Python, PyTorch, Node, FFmpeg, and browser components are reused.

The update client must:
1. Verify the signed manifest before trusting its URLs or versions.
2. Download to a staging directory with resumable HTTP range support.
3. Verify the complete archive hash and signature before extraction.
4. Reject path traversal, unexpected files, oversized extraction, and unsupported component versions.
5. Extract into a new immutable version directory.
6. Run component health checks and an application startup/render smoke test.
7. Atomically switch the active-version pointer only after verification.
8. Keep the previous known-good version for rollback.
9. Preserve user data and model directories.
10. Recover safely after interruption, power loss, disk-full, or failed update.

Do not initially implement binary delta patches. Component-level archives are easier to validate and recover. If bandwidth measurements later justify it, add binary deltas only for large, stable components with a tested full-package fallback.

## Expected update sizes

There is no measured production installer size yet. The repository does not contain a built installer or a committed runtime payload. The latest inspected branch has no published GitHub Release assets. The current CI validation builds an installer but does not retain it as an artifact, so its exact size cannot be read from the repository.

The first complete installer will be materially larger than the current installer because the current first-run script downloads the Python and PyTorch environments and browser separately. The actual size must be measured from the finished CPU and NVIDIA installers, not guessed from repository size.

Distribution constraints also matter:
- GitHub Release assets must each be smaller than 2 GiB. A single 5 GB setup executable cannot be published as one GitHub Release asset.
- Tauri's Windows updater artifact is a ZIP containing the NSIS setup executable. It is not a binary-delta patch. If the NSIS installer embeds all multi-gigabyte runtimes, the updater download will also be multi-gigabyte.
- Therefore, the long-term design must keep large runtime components outside the frequently updated Tauri shell bundle. A single customer-facing bootstrapper can still orchestrate installation of signed, independently downloadable components with progress, retry, and verification. If a truly offline installer is offered, it should be a separate distribution assembled from component archives and tested against the distribution host's per-file limits.

After component separation:
- a UI/backend-only update should download only the changed application component archives;
- a renderer-only update should download the renderer component;
- a Python dependency update should download the dependency-set component;
- a PyTorch/CUDA update may still be large, but must not force redownloading the whole application;
- a shell-only update should download the signed Tauri updater package.

Publish compressed and installed sizes for every component in release metadata. Show the user the total download size before applying an update.

## Versioning and compatibility

Use independent versions/hashes for the desktop shell, app payload, Python dependency set, Node runtime, renderer, FFmpeg, browser, and GPU runtime. Do not tie all component updates to a single monolithic requirements hash.

An app release declares a compatibility range for each runtime component. Keep the currently active and previous known-good set until the new set passes health checks. Cleanup old versions only after successful activation and a retention window.

## Required validation gates

- Clean Windows 10/11 x64 install with no system Python or Node.
- Clean install with Python 3.14 already installed and registered in Windows.
- Upgrade from every supported previous release.
- Offline first launch after a complete installer install.
- Interrupted download and interrupted extraction recovery.
- Disk-full and permission-denied recovery.
- Corrupt archive, invalid signature, invalid manifest, and path traversal rejection.
- CPU-only hardware and supported NVIDIA driver/GPU combinations.
- CUDA availability and representative GPU inference test.
- Renderer browser launch and representative render test.
- Existing user settings, projects, downloads, outputs, and model paths survive update and rollback.
- Video output regression suite confirms clipping, crop, subtitles, audio, and render behavior are unchanged.

## Current release behavior versus target

Until the component updater is implemented and validated, releases remain manual full-installer upgrades. Do not advertise small/delta updates or automatic updates yet.
