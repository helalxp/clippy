# Clippy v1 Local Runtime, Service, and Data Contract

> Status: Phase 1 architecture baseline, documented from source at cleanup baseline `61edcd5027e3f4e05c8019896e25af0e1cfa19f3`.  
> Last inspected: 2026-11-19.  
> This document describes observed contracts and records recommended changes. It is not authorization to modify runtime behavior.

## 1. Purpose and authority

This document captures the local Windows desktop architecture that the Clippy v1 extraction must preserve. It is deliberately based on the current `main` source and checked-in runtime contracts, not the older Docker-only architecture notes.

The authoritative implementation surfaces are:

- `desktop/src-tauri/src/lib.rs`, `supervisor.rs`, `bootstrap.rs`, `installation.rs`, and `data_storage.rs`.
- `dashboard/src/components/DesktopRuntimeGate.jsx`, `dashboard/src/config.js`, and `dashboard/src/lib/api.js`.
- `app.py`, `main.py`, `local_library.py`, `clippy_local_models.py`.
- `render-service/src/server.ts`, `auth.ts`, `paths.ts`.
- `desktop/FIRST_RUN_SETUP_CONTRACT.md`, `desktop/INSTALLER_UPDATE_ARCHITECTURE.md`, and `desktop/runtime-contract.json`.

When these notes conflict with source, tests, a runtime manifest, or a release workflow, inspect and trust the current implementation.

## 2. Runtime responsibility boundaries

| Boundary | Current owner | Contract |
|---|---|---|
| Native application lifecycle | Tauri/Rust | Creates the desktop window, owns runtime bootstrap, supervises local services, exposes narrowly scoped native commands, and coordinates updates and storage moves |
| Frontend | React/Vite in `dashboard/` | Renders workflows and calls the local backend; in desktop mode it receives the current API base URL and per-launch token from the Tauri runtime gate |
| Local API | FastAPI in `app.py` | Validates requests, manages uploads/jobs/queues, coordinates settings and Library, launches pipeline subprocesses, and brokers rendering |
| Processing | Python pipeline in `main.py` and focused Python modules | Runs a job as a child process; performs source ingest, transcription, analysis, selection, clipping, reframing, captions/hooks and associated media work |
| Rendering | Node/Express in `render-service/` plus Remotion in `remotion/` | Accepts render jobs, resolves media paths, performs Remotion rendering and exposes local output media |
| Durable projects | `local_library.py` | Owns the Library and project/clip metadata, separate from temporary job output |
| Runtime provisioning | `desktop/setup-runtime.ps1`, runtime helper scripts, Rust bootstrap | Installs and validates private Python/Node/FFmpeg/browser components and the CPU/CUDA Python runtime |
| Persistent user data | Tauri data-location contract and backend path environment | Keeps mutable user data outside the replaceable application payload and supports a verified data-folder move |

Do not collapse these boundaries during the cleanup simply to reduce file count. Changes to any cross-boundary behavior require contract-level tests.

## 3. Desktop startup and shutdown sequence

### 3.1 Observed startup sequence

The current `DesktopRuntimeGate` coordinates startup approximately as follows:

1. Invoke Tauri `install_app_payload`. The desktop shell verifies the installer-embedded application payload hash and prepares/activates the matching payload while retaining the prior payload for rollback.
2. Invoke `check_runtime` to inspect the managed runtime and manifest.
3. When the runtime reports an error, or a retry is in progress, invoke `setup_runtime` and validate again.
4. Invoke `start_services`. The Rust supervisor discovers the managed paths, validates required executables and directories, creates output/upload/Library/model/log directories, and starts the backend and renderer.
5. The supervisor allocates independent available loopback ports for the backend and renderer, creates a fresh per-launch API token, starts both child processes, and waits for their health endpoints.
6. Tauri returns the service URLs. The frontend obtains the per-launch token with `get_api_token`, stores it only in the current WebView process memory, and installs the local-fetch authorization wrapper for backend requests.
7. Once runtime and services are healthy, the frontend invokes `commit_app_payload`. This retires the previous payload. A cleanup failure is treated as recoverable rather than converting a healthy startup into a failed startup.

If the new payload cannot start, the frontend invokes the rollback path, validates/repares the previous runtime if needed, and starts services from the previous payload. The old application payload is not committed away until the new one is healthy.

### 3.2 Shutdown

The Rust supervisor stops the renderer and backend. On Windows, child processes are assigned to a Windows Job Object so that a forcibly terminated Clippy process does not leave its service descendants running. Preserve the Job Object, process assignment/cleanup, health checks, graceful shutdown, and startup rollback behavior.

### 3.3 Runtime update versus user data

The signed Tauri updater installs the full NSIS installer. The installer embeds the replaceable application payload; first-run/runtime setup separately manages the Python runtime and other dependencies. The runtime manifest and version contract govern the dependency versions and integrity checks.

The existing payload update process stages, hashes, activates, health-checks, commits, or rolls back application payloads. User data, model weights, logs, and the persistent Remotion browser are not supposed to be replaced as part of an application-payload update.

Do not remove or weaken:
- Payload SHA-256 verification.
- Previous-payload rollback.
- Runtime manifest validation.
- Version synchronization.
- Signed updater verification.
- CPU/CUDA runtime validation and repair.
- Browser archive/executable hash validation.
- Per-user installation and data-preservation behavior.

## 4. Local network and authentication contract

### 4.1 Binding and ports

The desktop supervisor binds both local services to `127.0.0.1`. It obtains ephemeral available ports at startup rather than relying on fixed ports. Backend and renderer URLs are returned to the WebView at runtime.

This dynamic-port behavior is a product contract. Do not reintroduce fixed ports, container hostnames, wildcard binds, or assumptions based on the Docker development topology.

### 4.2 Per-launch secret

The supervisor generates a fresh 32-byte API token at service startup and passes the same token to the backend and renderer as `CLIPPY_API_TOKEN`. The token is returned to the desktop WebView only through the Tauri `get_api_token` command.

The frontend:
- Keeps the token in process memory, not a persistent settings store.
- Adds `X-Clippy-Token` to requests sent to the backend origin.
- Adds a short-lived `token` query parameter only to local static-media URLs where browser media elements cannot attach a custom header.

The renderer:
- Requires the active token on render API requests and media URLs whenever `CLIPPY_API_TOKEN` is configured.
- Leaves `/health` open for process health checks.
- Uses constant-time token comparison in `render-service/src/auth.ts`.

The backend and renderer retain a legacy no-token self-host/container mode. The desktop supervisor always supplies a token. Do not mistake the optional self-host bypass for the desktop security policy.

### 4.3 Credential handling and job subprocesses

The local generation request currently accepts the user's Gemini key in an `X-Gemini-Key` request header. The backend resolves the request key (or the configured environment key) and passes the effective key into the specific `main.py` child process as `GEMINI_API_KEY`. If a local OpenAI-compatible LLM is active and no Gemini key is needed, the backend removes any stale `GEMINI_API_KEY` from that job's environment.

The backend constructs child environments through `child_env()`, which removes server-side secrets such as database, Stripe, OAuth, SMTP, managed provider keys and cloud storage credentials before pipeline execution. Keep this denylist policy and test it whenever new server secrets are introduced.

**Observed credential-storage defect to fix in a later implementation phase:** the frontend currently stores the Gemini API key in plaintext `localStorage`; Upload-Post, ElevenLabs and fal.ai keys use an XOR/Base64 transform with a static client-side secret. That is reversible obfuscation, not encryption. These values must not become the v1 credential-storage model.

The planned local credential boundary is a narrow Tauri command backed by Windows Credential Manager or DPAPI. It must:
- Store only provider secrets needed by active v1 features.
- Never persist the per-launch API token.
- Never migrate hosted cloud bearer/session tokens into local credentials.
- Provide explicit set, read/use, delete and provider-status operations without returning secret material to the frontend unless a real UI use requires it.
- Migrate existing user-saved keys safely: do not silently discard them; validate a successful secure-store write before clearing the legacy browser copy; support a recoverable migration error state.
- Keep secrets out of logs, URLs, telemetry, crash reports and child processes that do not need them.

The credential migration requires a dedicated backward-compatibility test plan before implementation.

## 5. Generation and render request contracts

### 5.1 Generation API

The primary local generation endpoint is `POST /api/process`.

Observed accepted inputs include:
- A local source file upload, or a validated source URL.
- An explicit user attestation that the caller owns the content or has rights to process it.
- Optional output format and layout choices.
- Optional clip-count and duration bounds.
- Optional automatic-hook controls.
- Optional caption and hook specifications.
- Optional custom watermark upload.
- Optional webhook callback configuration.
- Optional upload-slot or thumbnail-session handover identifiers, which are feature-specific and must be isolated during the deferred-feature work.

The route accepts multipart form data for uploads and can parse a JSON body for URL-based requests. The frontend currently sends the Gemini key as the `X-Gemini-Key` header. The server validates source URLs before retrieval, validates webhook targets, checks the content-rights attestation, creates a job workspace, and queues/launches the processing child.

Do not change these fields, defaults, ownership/validation checks, or response semantics during extraction without tracing all callers and adding contract tests.

### 5.2 Processing job lifecycle

The FastAPI service is responsible for job admission/queueing, job status, logs, cancellation/recovery, upload and source file serving, and delivery of results. It launches `main.py` as a separate child process with a per-job environment.

The UI currently polls `/api/status/{job_id}`. The job's working output is under the configured `OUTPUT_DIR`, keyed by job ID. The backend also uses a separate durable local Library; the job workspace is not the Library.

Core endpoints include:
- `/api/process`, `/api/status/{job_id}`
- Upload and source delivery routes.
- Local model settings/download/verification routes.
- Library storage/settings/project routes.
- Editing routes for clip reframe, background, custom watermark, subtitles, hooks, rerender and export.
- Reference-template list/create/update routes.

The full route inventory is not repeated here. Phase 2 must map every route to the local-v1, deferred, or retired classification before extraction.

### 5.3 Renderer contract

The FastAPI backend submits render requests to the renderer using the supervisor-provided `RENDER_SERVICE_URL`. Both processes use the same physical output directory. The renderer converts backend `/videos/` or `/output/` media paths into its own local `/output/` media endpoint for Remotion's browser.

Renderer requests include a job ID, clip index, and validated composition properties (video URL, frame duration, fps, width, height and optional composition layers). The renderer returns a render ID and exposes render status through `GET /render/{renderId}`.

The current renderer keeps job status in a process-local `Map`. A renderer restart loses this status map. This is a known durability limitation, not proof that Redis or another queue is automatically required. Phase 5 must define the expected restart/recovery semantics before selecting a persistence design.

## 6. Persistent storage contract

The desktop install root is anchored to `%LOCALAPPDATA%\Clippy`. The supervisor intentionally does not let an ambient `CLIPPY_HOME` environment variable redirect the application to another installation.

| Path | Ownership | Lifecycle |
|---|---|---|
| `app/current/` | Replaceable application payload | Replaced only through the verified payload update/rollback flow |
| `runtime/python/`, `runtime/node/`, `runtime/ffmpeg/` | Managed runtime components | Version/hash checked, repaired or reused according to runtime manifest |
| `browser/headless-shell/` | Persistent Remotion browser | Kept outside replaceable application payload; version/hash checked |
| `settings.json` | Clippy settings/model preferences | Persists across app upgrades |
| `runtime-manifest.json` | Verified runtime state | Updated only after successful validation |
| `storage-location.json` | Pointer to the configured data root | Atomically updated after a verified data-folder move |
| `logs/` | Setup, backend and renderer diagnostics | Persists for troubleshooting |
| `data/output/` (default) | Temporary job workspaces and generated output | Subject to the explicit output/job retention policy |
| `data/uploads/` (default) | User source uploads | Subject to explicit upload retention policy |
| `data/library/` | Durable project/clip Library | Must survive app upgrades and normal runtime repair |
| `data/models/` | Downloaded model weights and model caches | Separate from core runtime dependencies; must survive updates |
| `data/reference_templates/` | User-created reference-template files/manifests | Must survive app upgrades and storage moves |

The configured data root defaults to `%LOCALAPPDATA%\Clippy\data`. `storage-location.json` may point to an external absolute directory. The supervisor passes the resolved root through the explicit backend environment variables:
- `CLIPPY_DATA_DIR`, `OUTPUT_DIR`, `UPLOAD_DIR`, `CLIPPY_LIBRARY_DIR`
- `CLIPPY_MODELS_DIR`, `REFERENCE_TEMPLATES_DIR`
- `CLIPPY_SETTINGS_PATH` remains under the install root because it stores settings rather than bulk user data.
- `HF_HOME`, `HUGGINGFACE_HUB_CACHE`, and `TORCH_HOME` are pointed under the managed models directory.

### 6.1 Data-folder relocation algorithm

The existing Tauri data-move implementation is a preservation invariant and should be reused for future data migrations:

1. Resolve the current data directory from the schema-versioned `storage-location.json` (or the legacy default `data/` directory).
2. Require an existing, empty destination outside the install root and not overlapping the current data directory.
3. Reject unsafe symbolic links/junctions and links that escape the source tree.
4. Measure the source tree and check destination free space with a safety reserve.
5. Ask the backend to reject new mutations and confirm there are no active generation jobs or uploads.
6. Stop the backend and renderer.
7. Copy the full directory into a unique staging directory and SHA-256-verify each copied file.
8. Activate the staged directory by a directory rename.
9. Atomically write the new storage-location configuration.
10. Restart both services and verify health from the new location.
11. Only after successful restart, remove the original data directory. If cleanup fails, keep the duplicate rather than risk data loss.
12. If activation/configuration/startup fails, restore the old config and restart the old location; preserve a complete recovery copy if rollback cannot finish.

The data-move code also validates path overlap, rejects reparse points, verifies copied files, checks free space and uses an installation lock. These safety checks must not be simplified into a basic folder copy.

### 6.2 Existing upgrade migration for reference templates

The installer has a legacy migration step that moves reference-template files out of the replaceable application payload into the configured user data directory. It validates file hashes, avoids overwriting conflicting files, and leaves the previous copy when conflicts occur. Preserve this path until a verified migration test proves all supported existing user installations have completed it.

### 6.3 Model-storage gap: Ultralytics YOLO

The backend supervisor currently points Whisper/Hugging Face/Torch caches into `CLIPPY_MODELS_DIR`, but it does not currently set `YOLO_CONFIG_DIR` or `YOLO_MODEL_PATH`.

The pinned Ultralytics package defaults its Windows configuration directory to `%USERPROFILE%\AppData\Roaming\Ultralytics` unless `YOLO_CONFIG_DIR` is supplied. `main.py` initializes `YOLO(os.environ.get("YOLO_MODEL_PATH", "yolov8n.pt"))`; the model may therefore be downloaded/cached outside the Clippy-managed, relocatable data tree.

This is a confirmed data-boundary gap. Before correcting it:
- Resolve the Ultralytics licensing decision recorded in the distribution inventory.
- Determine the exact installed weight/config paths on the current supported runtime.
- Design a safe one-time migration from the existing Ultralytics cache.
- Point future model/config/cache data into the managed `models/` directory.
- Do not silently download a second copy, discard a local model, or change person-detection behavior.

## 7. Local runtime component and version contract

The current checked-in `desktop/runtime-contract.json` records:
- CPython 3.12.10.
- Node.js 22.23.3.
- FFmpeg provider family `gyan-release-essentials`.
- Remotion headless shell 144.0.7559.20 with archive and executable SHA-256 values.

The runtime build uses separate CPU and NVIDIA/CUDA 12.8 Python packages. The Windows CUDA package is checked for a CUDA-enabled PyTorch build and selected CUDA DLLs. The installer downloads and verifies runtime archives by per-release manifests and hashes.

**Known reproducibility gap:** FFmpeg is currently downloaded from the moving `ffmpeg-release-essentials.zip` URL and its sidecar is fetched from the same moving publisher path. The runtime contract identifies the build family but not a fixed FFmpeg release version, archive hash, or source commit. Phase 1 compliance work records this as a distribution/provenance blocker; the eventual fix must pin the exact binary, hash, source and licence evidence.

The runtime contract is the source of truth for version/hash metadata. Do not duplicate runtime versions in unrelated scripts or docs without a validation mechanism.

## 8. Security and data-integrity invariants

The following are release-critical:
- Backend and renderer bind to loopback in desktop mode.
- The per-launch token is generated by Tauri and passed to both services.
- Browser media token query parameters are scoped to local static-media URLs and must not be logged.
- Source URLs are validated before fetching; uploads and media paths must remain bounded to approved roots.
- Job subprocesses receive only secrets they require; cloud/server secrets must not flow to processing children.
- The Windows supervisor owns service lifecycle and child-process cleanup.
- Data-folder moves use verified staging, atomic configuration updates and service health checks.
- Application payload updates preserve the previous known-good payload until health gates pass.
- User data, settings, model weights, reference templates and logs remain outside replaceable application payload files.
- No update or cleanup procedure may delete the entire `%LOCALAPPDATA%\Clippy` directory.

## 9. Phase 1 contract decisions and later work

The following are intentionally not implemented in this Phase 1 document-only work:

| Item | Classification | Planned phase |
|---|---|---|
| Split hosted auth/billing behavior from the local app API | Architecture extraction | Phase 2 |
| Migrate needed provider credentials into Windows Credential Manager/DPAPI | Security and user-settings migration | Phase 2/5, after API contract is defined |
| Move Ultralytics model/config cache into Clippy-managed model storage | Data-boundary correction | After Ultralytics licence decision |
| Pin FFmpeg version/hash/source and package GPL notices/source provenance | Runtime/release correction | Phase 1 decision, implemented in later runtime phase |
| Preserve corresponding source and notices for distributed GPL components | Compliance packaging | Phase 1 decision, implemented before release |
| Define renderer status recovery semantics | Reliability architecture | Phase 5 |
| Write the four deferred-feature handoff docs and add UI investigation labels | Product scope | Phase 6 |
| Remove Docker-only networking and development paths | Deployment cleanup | Phase 4 |
| Remove analytics/telemetry | Product scope | Phase 7 |

## 10. Phase 1 acceptance

- [x] Current Tauri/backend/renderer responsibilities inspected.
- [x] Startup, shutdown, per-launch token and loopback contracts recorded.
- [x] Generation request and job-child environment contract recorded.
- [x] Data layout, storage-location pointer, data relocation and upgrade preservation behavior recorded.
- [x] Secret-storage gap and YOLO model-cache gap recorded.
- [x] Runtime version/reproducibility gap recorded.
- [ ] Product-owner licensing choices and any written third-party licence confirmations recorded.
- [ ] Phase 1 compliance and hosted-service retirement preflight docs reviewed and committed.
