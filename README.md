# Clippy

Clippy is a Windows-first video repurposing application in development. It is built from the OpenShorts codebase and is intended to turn long-form video into short-form clips that users can refine and prepare for publishing.

> **Repository status:** the default `main` branch currently contains the Docker-oriented development stack. The Windows-native desktop implementation is on the separate `windows-native-migration` branch and is still a scaffold, not a production-ready installer.

## Current repository layout

- `app.py`, `main.py`: FastAPI backend and video-processing pipeline.
- `dashboard/`: React + Vite interface.
- `render-service/`, `remotion/`: Node.js rendering service and video compositions.
- `cloud/`: optional hosted accounts, billing, metering, storage, and agent services.
- `tests/`: backend regression and security tests.
- `docs/`: subsystem architecture, compliance, and operational documentation.
- `CLIPPY_REPO_AUDIT.md`: canonical engineering handover, architecture map, branch status, verified findings, and audit coverage ledger.

## Run the current main-branch development stack

Requirements: Docker Desktop with Docker Compose.

1. Copy `.env.example` to `.env` and configure the providers/features you intend to use.
2. From the repository root, run:

   ```powershell
   docker compose up --build
   ```

3. Open the dashboard at [http://localhost:5175](http://localhost:5175).

Main-branch service endpoints:

| Service | Address |
|---|---|
| Dashboard | `http://localhost:5175` |
| Backend API | `http://localhost:8000` |
| Backend readiness | `http://localhost:8000/health/ready` |
| Renderer | `http://localhost:13100` |

**Security note:** do not expose the renderer port or this development stack to an untrusted network. The current main-branch renderer needs an authorization and private-media exposure hardening pass. See the security findings in the audit document.

## Windows desktop direction

The `windows-native-migration` branch contains the Tauri shell, local process supervisor, Windows compatibility work, and first-run setup contracts. Its own documentation identifies it as an early scaffold. Runtime provisioning, signed/checksummed downloads, packaging, clean-machine installation, upgrades, and full end-to-end validation remain required before it can be treated as a normal end-user installer.

## Engineering reference

Start with [CLIPPY_REPO_AUDIT.md](./CLIPPY_REPO_AUDIT.md) before changing code. It records the current architecture, branch-specific implementation boundaries, security/reliability findings, CI status, and what has and has not been inspected. Source code, tests, configuration, and Git history remain authoritative when they disagree with the audit.

Focused subsystem documents under `docs/architecture/`, compliance documents, CLI documentation, skills, and operational runbooks are retained where they describe a specific active subsystem or workflow.

## License and attribution

See [LICENSE](./LICENSE) and [NOTICE](./NOTICE). This repository derives from the OpenShorts codebase; preserve applicable upstream notices and third-party asset attributions when modifying or redistributing it.
