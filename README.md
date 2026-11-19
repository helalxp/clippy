# Clippy

Clippy is a Windows-first video repurposing application built from the OpenShorts codebase. It turns long-form video into short-form clips that users can edit and prepare for publishing.

## Windows desktop installer

**Clippy v0.2.3 is the published, verified Windows x64 installer baseline.**

- [Download the Windows installer](https://github.com/helalxp/clippy/releases/download/v0.2.3/Clippy_0.2.3_x64-setup.exe)
- [View the v0.2.3 release and runtime assets](https://github.com/helalxp/clippy/releases/tag/v0.2.3)
- [Desktop installation, build and troubleshooting guide](desktop/README.md)
- [Windows installer operations runbook](docs/architecture/windows-installer-operations-runbook.md)
- [Windows release procedure](RELEASING.md)
- [Runtime version and asset contract](docs/architecture/windows-release-versioning-and-runtime-asset-contract.md)

The installer is a per-user Tauri/NSIS application. It does not require Docker Desktop, WSL2, system Python, or system Node.js. First launch requires an internet connection and provisions Clippy-managed Python (CPU or supported NVIDIA/CUDA), Node.js, FFmpeg/FFprobe, renderer dependencies, and the Remotion headless browser. Runtime downloads come from the exact versioned GitHub Release and are checked before activation.

User settings, uploads, generated videos, caches, and downloaded AI model weights live outside the replaceable application payload. Whisper models are managed separately and are not bundled in the installer.

**Verified v0.2.3 baseline:** [Windows desktop validation](https://github.com/helalxp/clippy/actions/runs/44062955499) and [the full release workflow](https://github.com/helalxp/clippy/actions/runs/44066693854) passed. The release checks covered CPU and CUDA runtime packaging, manifests and multipart archive reconstruction, PowerShell contract tests, clean first-run setup, packaged rendering, Rust tests, and pre-publication asset verification. The installer was also manually installed and exercised through the editing workflow on Windows. A Whisper model-selection hiccup remains a separate follow-up and is not claimed as resolved.

## Docker development and self-hosted stack

The repository also retains the Docker-oriented development/self-hosted workflow. This is separate from the native Windows installer.

Requirements: Docker Desktop with Docker Compose, plus the API keys needed by the features being used.

1. Copy `.env.example` to `.env` and configure the providers/features you intend to use.
2. From the repository root, run:

   ```powershell
   docker compose up --build
   ```

3. Open the dashboard at [http://localhost:5175](http://localhost:5175).

| Service | Address |
|---|---|
| Dashboard | `http://localhost:5175` |
| Backend API | `http://localhost:8000` |
| Backend readiness | `http://localhost:8000/health/ready` |
| Renderer | `http://localhost:13100` |

**Security note:** do not expose the renderer port or this development stack to an untrusted network. The Docker-oriented renderer still has authorization and private-media exposure hardening work recorded in the repository audit.

## Repository layout

- `app.py`, `main.py`: FastAPI backend and video-processing pipeline.
- `dashboard/`: React + Vite interface.
- `desktop/`: Tauri shell, Windows installer, managed runtime setup and release tests.
- `render-service/`, `remotion/`: Node.js rendering service and video compositions.
- `cloud/`: optional hosted accounts, billing, metering, storage, and agent services.
- `tests/`: backend regression and security tests.
- `docs/`: architecture, platform contracts and operational runbooks.
- `CLIPPY_MASTER.md`: canonical internal engineering/agent guide.
- `CLIPPY_CLEANUP_MASTER.md`: active Clippy v1 extraction/cleanup phase ledger.
- `CLIPPY_REPO_AUDIT.md`: supporting dated technical audit and historical findings ledger.

## Engineering references

Start with [CLIPPY_MASTER.md](./CLIPPY_MASTER.md) before engineering work. For the active Clippy v1 cleanup, also read [CLIPPY_CLEANUP_MASTER.md](./CLIPPY_CLEANUP_MASTER.md). [CLIPPY_REPO_AUDIT.md](./CLIPPY_REPO_AUDIT.md) is a supporting historical audit; verify its findings against current source and CI before acting. For Windows installer changes, also read [the first-run setup contract](desktop/FIRST_RUN_SETUP_CONTRACT.md), [the operations runbook](docs/architecture/windows-installer-operations-runbook.md), and [RELEASING.md](RELEASING.md).

Source code, tests, configuration, Git history, and current CI results outrank older audit snapshots. Update the relevant docs whenever a verified product or release fact changes.

## License and attribution

See [LICENSE](./LICENSE) and [NOTICE](./NOTICE). This repository derives from the OpenShorts codebase; preserve applicable upstream notices and third-party asset attributions when modifying or redistributing it.
