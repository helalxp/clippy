# CLIPPY_MASTER.md
> **Canonical engineering and agent guide for Clippy**
>
> Repository: https://github.com/helalxp/clippy  
> Default branch: `main`  
> Last repository inspection: 2026-11-19  
> Status: living document. Verify the checked-out source before relying on any implementation claim.

This document is the canonical project-wide engineering and agent guide. The active task-specific cleanup plan is `CLIPPY_CLEANUP_MASTER.md`; the dated `CLIPPY_REPO_AUDIT.md` is a supporting technical audit record, not a competing startup guide. **The checked-out code, tests, configuration, Git history, and current CI remain the final source of truth.** This guide is not permission to overwrite user work, merge branches, remove files, or change product scope.

## Current mainline status — 2026-11-19

- `main` contains the native Tauri/Windows desktop application, managed runtime setup, payload updater, and Windows NSIS installer. Older statements below that describe the native installer as branch-only or a scaffold are historical and no longer describe current main.
- The latest published stable release is **Clippy v0.3.1**, tag `v0.3.1`, published 2026-11-19. Its source baseline is `61edcd5027e3f4e05c8019896e25af0e1cfa19f3`.
- Runtime contract at that release: CPython 3.12.10; Node.js 22.23.3; Gyan FFmpeg essentials build family; Remotion headless shell 144.0.7559.20. The exact FFmpeg release is not yet immutably pinned in `runtime-contract.json`.
- Tauri supervises FastAPI and the Node/Remotion renderer on dynamic loopback ports. Both services receive a per-launch API token. The native shell manages application payload updates, runtime validation/repair, rollback, and the persistent user-data location.
- Current v1 scope: keep core video generation/editing, local Library, reference templates, and custom user watermarking; defer social publishing, Thumbnail Studio, AI UGC/SaaS Shorts, and MCP/AI-agent integration; remove analytics/telemetry; remove Docker; keep the Clippy website separate.
- The cleanup work is tracked on `chore/master-cleanup-phase-0` in `CLIPPY_CLEANUP_MASTER.md`. Its changes so far are documentation-only and are not merged into main.
- The source tree still contains hosted SaaS and deferred feature code. The desktop payload excludes the `cloud/` package, but the shared `app.py` has not yet been fully extracted. Follow the local API extraction map and cleanup ledger before moving or deleting shared code.
- The confirmed local-mode S3 artifact-upload path and inherited hosted-environment risk are blockers to the intended local-only execution contract; see `CLIPPY_CLEANUP_MASTER.md` and `docs/architecture/clippy-local-api-extraction-map.md`.

Implementation and branch claims in the historical sections below must be read as historical unless explicitly revalidated against current source/tests or superseded by this current-status block.


---

## 1. Product mission

Clippy is a Windows-first desktop product being developed from the OpenShorts codebase. Its core job is to turn long-form video into polished short-form clips, then let users refine and prepare those clips for publishing.

The product direction is a normal Windows application:
- A user installs Clippy and launches it from a desktop shortcut.
- Clippy starts and supervises its own local backend and renderer.
- The user should not need Docker Desktop, WSL2, Python, Node.js, Rust, Git, a terminal, or developer tools installed.
- First-run setup provisions and verifies the required application runtimes.
- AI model weights are managed separately from core runtime dependencies.
- User settings, models, jobs, logs, and output survive application upgrades.

**Historical note (2026-11-09):** this branch-only migration statement was superseded when the native installer was merged into `main` and subsequently released as v0.3.1. Use the current mainline status at the top of this document and the Windows runtime contracts below.

### Product principles
1. Preserve working functionality before redesigning internals.
2. Prefer explicit, testable interfaces between the desktop shell, backend, dashboard, and renderer.
3. Keep local user data outside the install directory.
4. Make CPU/GPU capability and fallback behavior truthful and observable.
5. Avoid silent model substitution, destructive upgrades, hidden background processes, and unexplained port assumptions.
6. Separate confirmed implementation from plans, prototypes, and historical reports.

## 2. Repository identity and Git state

- GitHub repository: `helalxp/clippy`.
- Public repository; `main` is the authoritative product branch.
- Current stable release at this inspection: `v0.3.1` (published 2026-11-19).
- Cleanup baseline: `61edcd5027e3f4e05c8019896e25af0e1cfa19f3`.
- Active task branch: `chore/master-cleanup-phase-0`, a short-lived documentation/planning branch created from that baseline. Its changes are not yet merged into main.

### Remote branch inventory

Remote refs observed on 2026-11-19 included main, the cleanup branch, release preparation/versioning branches, feature branches for Library/templates/updater, and release/Whisper signing/version fixes. They are not all necessarily active or merge-ready. Inspect each branch's tip and compare it with current main before using it; branch existence is not evidence of current ownership or readiness.

### Mainline release evidence

The v0.3.1 source baseline has successful recorded runs:
- General CI: [run 44463861746](https://github.com/helalxp/clippy/actions/runs/44463861746).
- Windows desktop validation: [run 44463861590](https://github.com/helalxp/clippy/actions/runs/44463861590).
- Windows release workflow: [run 44463950724](https://github.com/helalxp/clippy/actions/runs/44463950724).

These results apply to that immutable source baseline. They do not prove later commits pass, establish commercial licensing clearance, or prove every hardware/driver combination works.

### Branch handling rules

- Treat `main` as the authoritative product branch.
- Create short-lived feature/fix branches from current main and return through pull requests.
- The cleanup branch is a deliberate task-specific exception, not a permanent integration or release branch.
- Never assume a feature branch is merged because its implementation appears elsewhere.
- Inspect `git status --short`, branch, remotes, recent commits, and relevant diffs before local work.
- Do not force-push, reset, clean, or discard local changes without explicit approval.
- Do not apply old patch files blindly; inspect current source and run `git apply --check` first.

## 3. Architecture overview

The current mainline application has five cooperating boundaries: Tauri desktop shell, React WebView, local FastAPI/processing engine, Node/Remotion renderer, and persistent local data/managed runtime. The detailed service, token, data, and update contract is `docs/architecture/clippy-v1-local-runtime-contract.md`.

### A. React/Vite dashboard
Location: `dashboard/`.

Responsibilities:
- Main user interface, generation workflow, progress/results, clip cards and editing workflows.
- Local Library and project detail, reference-template UI, local model settings, runtime/setup status, and in-app updater UI.
- Calls the local backend using the API base URL supplied at runtime by Tauri.
- Uses the per-launch token supplied by Tauri for local backend requests.
- Includes several hosted/deferred feature components which are being isolated or deferred by the v1 cleanup; do not treat their presence in the source as approval to keep them in the v1 navigation.

Key files:
- `dashboard/src/App.jsx`: large current top-level workflow/state composition; a planned refactor target.
- `dashboard/src/components/DesktopRuntimeGate.jsx`: payload/runtime/service startup and local API token setup.
- `dashboard/src/config.js`, `dashboard/src/lib/api.js`: local API/media URL behavior.
- `dashboard/src/components/LocalLibraryTab.jsx`, `LocalModelSettings.jsx`, `ReferenceTemplateLibrary.jsx`: retained local v1 surfaces.
- `dashboard/vite.config.js`: development proxy; its web-development topology is not the Tauri production service-address contract.

### B. Python/FastAPI backend and processing engine
Main files:
- `app.py`: FastAPI API, request validation, job queue/admission, child-process startup, job state, media delivery, editing routes, Library routes, and still-mixed hosted/deferred routes.
- `main.py`: command-line processing pipeline executed as a child process per job.
- `local_library.py`: permanent local project/clip Library, deliberately separate from temporary job output.
- `clippy_local_models.py`: Whisper model selection, download, validation, and settings integration.
- `reference_templates.py`: retained local reference-template persistence/API.
- `llm_backend.py`, `platform_compat.py`, `media_auth.py`, `security_utils.py`: local LLM, platform, media-auth, and security support.
- `requirements.txt`: pinned direct Python runtime dependencies.

Backend lifecycle:
1. FastAPI validates an upload/URL request and creates a temporary job workspace.
2. Queue/admission code controls job execution and recovery.
3. A job runs `main.py` as a child process with a purpose-built environment.
4. The child performs transcription, scene analysis, moment selection, clip extraction, reframing, captions/hooks, and supporting processing.
5. The backend and renderer produce deliverable media; the local Library separately archives durable project/clip state.
6. The API exposes job status/logs, source/clip media, editing operations, and exports.

**Extraction caveat:** `app.py` still mixes local v1 endpoints with hosted SaaS and deferred social/thumbnail/UGC/MCP/website routes. A confirmed local-mode S3 artifact-upload path and inherited cloud-environment risk are blockers tracked in `CLIPPY_CLEANUP_MASTER.md`. Do not remove `s3_uploader.py` blindly: deferred gallery helpers share that module.

### C. Node.js / Remotion renderer
Location: `render-service/` and `remotion/`.

Responsibilities:
- Receives render jobs from the local backend via the supervisor-provided renderer URL.
- Validates composition settings and local media paths.
- Bundles/uses Remotion compositions and writes rendered output into the shared configured output root.
- Authenticates render/media calls using the per-launch token when configured.

Key files:
- `render-service/src/server.ts`: HTTP/render API and process-local render job state.
- `render-service/src/auth.ts`, `auth.test.ts`: local render token contract.
- `render-service/src/paths.ts`, `paths.test.ts`: output/media path mapping and validation.
- `render-service/src/bundle.ts`, `render-worker.ts`: Remotion bundle/render execution.
- `remotion/src/index.ts`: composition entrypoint.

Renderer job status is held in a process-local `Map` and is lost on renderer restart. Define the needed recovery semantics before adding persistence or a queue; Redis is not an automatic requirement.

### D. Tauri desktop shell
Location: `desktop/src-tauri/`; technology: Tauri 2 + Rust.

Responsibilities:
- Own the Windows application window and native integration.
- Install/validate/repair the managed runtime and application payload.
- Supervise local backend/renderer processes and their health/shutdown.
- Allocate dynamic loopback ports and mint/pass the per-launch API token.
- Manage logs, folder selection/reveal, streamed downloads, updater lifecycle, and safe data-folder relocation.

Current core Rust modules:
- `bootstrap.rs`: runtime validation/setup.
- `supervisor.rs`: managed paths, child process startup/health/shutdown.
- `data_storage.rs`: configured data root, staged copy, per-file SHA-256 verification and relocation.
- `installation.rs`: installation locks and legacy reference-template migration.
- `payload_update.rs`: application payload activation/commit/rollback.
- `lib.rs`, `main.rs`: Tauri commands and app shell.

### E. Persistent data and managed runtime

Installation root: `%LOCALAPPDATA%\\Clippy`. Default data root: `%LOCALAPPDATA%\\Clippy\\data`; the native data-move flow can relocate it to an external absolute directory.

Keep the replaceable app payload and runtime separate from persistent data. User projects, uploads, local Library deliverables, reference templates, model weights/caches, settings, and logs must survive application updates. The data relocation path is a verified staged copy/atomic-pointer/health-check operation; do not replace it with a simple folder copy.

## 4. End-to-end clip pipeline

The core clip-generation flow, as described in the existing project engineering notes and source structure:

1. **Ingest** — accept a local upload or fetch a permitted video URL (yt-dlp).
2. **Preflight** — inspect duration/quality and reject or warn about unusable inputs according to configuration.
3. **Transcribe** — faster-whisper or a supported transcription backend produces word-level timestamps.
4. **Scene analysis** — PySceneDetect/other configured scene tools identify boundaries.
5. **Moment selection** — Gemini or an OpenAI-compatible LLM scores transcript windows and selects candidate moments. Silent/low-speech footage may use a separate visual-analysis fallback.
6. **Clip extraction** — FFmpeg creates source segments.
7. **Reframing/layout** — choose crop/layout behavior and render a vertical composition.
8. **Enhancement** — subtitles, hooks, optional effects, dubbing, watermark/background operations where enabled.
9. **Final render** — backend and/or Remotion render service produces deliverable media.
10. **Persist and deliver** — temporary files use the configured job output root; durable projects/clip deliverables are archived in the local Library. The current implicit local-mode S3 artifact upload is a cleanup/security defect, not an intended v1 backup contract.
11. **Publish** — social publishing and scheduling are deferred for v1; do not present them as an active v1 workflow.

Do not assume every step runs for every job. Input type, settings, environment variables, feature flags, billing mode, and branch affect the actual path.

### Layout/reframing subsystem
Existing engineering notes describe these modes:
- **TRACK**: face/subject tracking and dynamic crop.
- **SPLIT**: two speakers stacked vertically, with captions positioned on the seam.
- **GENERAL**: blurred background treatment for content that does not suit a tight face crop.
- **SCREENCAST**: screen content combined with presenter view.

Related modules named in the existing project documentation include:
- `reframe_v2.py`
- `layout_picker.py`
- `layout_ranges.py`
- `split_layout.py`
- `screencast_layout.py`
- `camera_inset.py`
- `clip_selection.py`
- `active_speaker.py` (verify current path/name before use)

Preservation invariants from existing engineering notes:
- User-selected layout choices must not be silently overridden by an AI layout picker.
- Per-scene layout checks matter for videos that cut between close-ups and two-shots.
- SPLIT captions require positional ASS subtitle rendering; plain SRT cannot provide the same seam alignment.
- Preserve/remap layout ranges when recutting clips.
- Already-vertical sources may bypass normal reframing. Verify current source behavior before changing it.

### Transcription, captions, and hooks
Subsystems named in the current engineering notes:
- `transcribe_backends.py`: transcription backend selection and model lifecycle.
- `subtitles.py`: subtitle generation/formatting/burning.
- `burned_subtitles.py`: detect existing burned-in captions.
- `hooks.py`, `hook_grounding.py`, `hook_placement.py`: hook text generation, grounding against visible content, and placement.
- `translate.py`: voice dubbing/translation integration.

Preserve:
- Word-level timing where required by animated captions.
- Existing subtitle presets and font fallback behavior, including multilingual scripts.
- Positional ASS subtitle behavior for layouts that need it.
- Hook placement that avoids covering faces or important on-screen content.
- Existing caption/hook settings and metadata contracts.

### Watermark and background editing
The project has preserved custom user editing features and also has historical hosted-delivery functionality. The following concerns must remain separate:
- Watermark upload during advanced/raw-footage setup.
- Post-generation watermark editing: PNG/WebP upload, preview, draggable position, size/position controls, and final burned-in render.
- Background editing: blurred moving footage behind the clip or a selected solid color.
- Delivery watermark copies in cloud/free-plan behavior.

Do not conflate custom user watermarks with managed/free-plan delivery watermarks. They are separate concerns and may have different file/serving rules.

Earlier testing reported that background edits and custom watermark rendering did not reliably apply, and some clip previews appeared corrupted/empty. Those were historical reports, not confirmed current failures or fixes. Reproduce on the current branch, inspect API responses and backend/renderer logs, and test the actual rendered output file. A UI preview alone is not proof that the output was burned correctly.

### Reference templates
The `codex/reference-templates` branch adds:
- `reference_templates.py`
- `dashboard/src/components/ReferenceTemplateLibrary.jsx`
- `tests/test_reference_templates.py`
- `reference_templates/<template-id>/manifest.json` and poster assets
- API and layout-picker integration changes in `app.py` and `layout_picker.py`

Reference templates are present on current main and are explicitly retained in v1. Their files and user-created data must survive application-payload updates and data-folder relocation.

---

## 5. Windows-native migration roadmap (historical snapshot, superseded by v0.3.1)

The stage notes below were written for the pre-merge native migration branch. They are retained as history, not current readiness criteria. The native desktop application is now merged into main and ships as v0.3.1. Current runtime and release contracts supersede any statement below that says a downloader, installer, updater, or production NSIS package is still only a scaffold. The remaining product-hardening work is tracked in `CLIPPY_CLEANUP_MASTER.md`.

### Stage 1 — Windows compatibility
Areas explicitly addressed/identified on the migration branch:
- Linux-only process priority and subprocess hooks.
- POSIX `fcntl.flock` locking.
- Linux `resource` module assumptions.
- Shell-script FFmpeg placeholders.
- Signal/shutdown assumptions.
- Relative/container filesystem paths.
- Container-specific hostnames and mounts.

New/changed modules include `platform_compat.py` and related tests. Verify actual code and OS-specific behavior before claiming full compatibility.

### Stage 2 — Native local services and model settings
Known branch changes include:
- Local renderer/backend URL and path handling.
- Renderer path resolution and validation.
- Local model settings support in `clippy_local_models.py` and `dashboard/src/components/LocalModelSettings.jsx`.
- Runtime manifest.
- Tests for platform compatibility, local model settings, renderer paths.
- Docker networking retained for development where practical.

Model management must distinguish:
1. Core runtime packages required to run Clippy.
2. Model weights/files used by AI features.

Users should be able to choose supported models, download them, or register compatible existing files. Validate the format and required files; persist selections; never silently replace a selected model. A model may also require a particular runtime package/provider.

### Stage 3 — Desktop shell and bootstrap
Tauri scaffold exists on `windows-native-migration`. It is not yet equivalent to a finished installer.

Remaining work identified by the branch's own agent notes:
- Complete robust first-run dependency downloader.
- Verify runtime manifest checksums/signatures and source authenticity.
- Resumable downloads and safe extraction.
- Install/version core runtimes into application-managed paths.
- Provision Node/Remotion/browser and FFmpeg/FFprobe.
- Complete model manager and GPU capability detection.
- Production installer/NSIS packaging.
- Clean-machine installation, upgrade, recovery, and uninstall testing.

The intended persistent data root is under `%LOCALAPPDATA%\Clippy`, with logs and user data separate from the installed application. Treat exact path layout as a contract to verify in the current Rust source and setup documents.

### Stage 4 — Production hardening
- Local API and process security.
- Safe file/path handling and upload validation.
- Dependency/license review, especially for redistributing binaries/models.
- Signed installer/update artifacts where feasible.
- Crash recovery, logs, safe migrations, backup/recovery.
- CPU and supported GPU paths validated separately.

### Desktop definition of done
A clean Windows user can install and run Clippy without Docker/WSL2/developer toolchains; first-run setup verifies runtimes; subsequent starts reuse them; backend/renderer are supervised and shut down cleanly; user data/models survive upgrades; editing features work; installer, upgrade, uninstall, and clean-machine tests pass.

---

## 6. Project structure guide

This is a historical functional map from the November 9 snapshot; several paths and branch annotations below are stale. Use `git ls-files` and the current tree at the checked-out commit. The current desktop/native file map is in `docs/architecture/clippy-v1-local-runtime-contract.md` and `CLIPPY_CLEANUP_MASTER.md`.

```text
clippy/
├── app.py                         # FastAPI API, queue, jobs, delivery, editing routes
├── main.py                        # Child-process video pipeline entry point
├── requirements.txt               # Python dependencies
├── docker-compose.yml             # Docker development stack on main
├── Dockerfile                     # Backend image (verify current root file)
├── dashboard/                     # React + Vite frontend
│   ├── package.json
│   ├── vite.config.js
│   ├── build-desktop.ps1           # Native branch desktop build helper
│   └── src/
│       ├── App.jsx                 # Main dashboard composition
│       └── components/             # Result cards, editors, settings, modals, etc.
├── render-service/                # Node/Express + Remotion render service
│   ├── package.json
│   └── src/
│       ├── server.ts
│       ├── bundle.ts
│       ├── render-worker.ts
│       └── paths.ts                # Native branch path handling
├── desktop/                        # Native branch Tauri desktop shell
│   └── src-tauri/
│       └── src/
│           ├── bootstrap.rs
│           ├── downloader.rs
│           ├── supervisor.rs
│           ├── lib.rs
│           └── main.rs
├── cloud/                          # Optional hosted/billing functionality
├── tests/                          # Python tests; inspect actual inventory
├── reference_templates/            # Reference template data/assets on feature branches
├── output/                          # Generated job output at runtime; do not commit user media
├── uploads/                         # Runtime source uploads; do not commit user media
├── bin/                             # Bundled/helper binaries or scripts; inspect before changing
├── docs/                            # Architecture and subsystem docs where present
├── cli/                             # CLI client where present
├── skills/                          # Agent skill material where present
└── examples/                        # Integration/workflow examples where present
```

### How to map an unfamiliar file
- Search for imports/references before renaming or deleting.
- Search route registration and frontend API call sites before changing endpoint names.
- Check subprocess invocations and environment construction before moving Python modules.
- Check Vite proxy, desktop API base URL, renderer URL, and CORS together when changing service addresses.
- Check all output path consumers before changing directory layout.
- Check tests, CI workflows, scripts, docs, and packaging manifests for references.
- Dynamic imports, plugin registries, string-based route names, and runtime-loaded assets may not appear in ordinary static import searches.

### Key configuration and operational files
- `requirements.txt`: Python dependencies.
- `dashboard/package.json`: frontend dependencies and scripts.
- `render-service/package.json`: renderer dependencies and scripts.
- `desktop/runtime-contract.json`: source-controlled versions and immutable browser hashes for managed runtime components.
- `%LOCALAPPDATA%\\Clippy\\runtime-manifest.json`: per-user installed runtime state, written only after component validation.
- `docker-compose.yml` and related Docker files: legacy tracked infrastructure scheduled for removal in cleanup Phase 4; not the v1 workflow.
- `.env.example` / `.env`: legacy development/self-host configuration under review; do not treat it as a supported customer desktop configuration or expose secret values.
- `.gitignore`: generated files, secrets, caches, local outputs.
- GitHub Actions workflows: inspect `.github/workflows/` before changing CI assumptions.

---

## 7. Development and verification commands

Always inspect the checked-out branch and local modifications first. These are baseline commands; adjust for the current branch and installed tools.

### Legacy Docker development (not the v1 workflow)

Docker/Compose instructions below the historical snapshot have been deliberately removed from this guide. Docker remains in the current tree only as legacy material until cleanup Phase 4. Do not use Docker or WSL2 as the desktop product architecture, and do not add new Docker-dependent application paths. The supported product build and packaging path is the Windows-native Tauri workflow documented in `desktop/README.md`, `desktop/FIRST_RUN_SETUP_CONTRACT.md`, and `desktop/INSTALLER_UPDATE_ARCHITECTURE.md`.

### Windows native desktop build

From the repository root in PowerShell:

```powershell
./desktop/validate-version.ps1
./desktop/build.ps1
```

The build scripts resolve paths relative to the repository and produce a Windows NSIS installer. Development prerequisites include Rust/MSVC/Windows SDK, WebView2, Node.js/npm, Python 3.12.10, Git, NSIS, and the required PowerShell/Pester tooling. These are developer prerequisites, not end-user requirements.

To run the desktop app during development:

```powershell
cd desktop/src-tauri
cargo tauri dev
```

Use the following subsystem contracts for more detailed steps and runtime behavior:
- `desktop/FIRST_RUN_SETUP_CONTRACT.md`
- `desktop/INSTALLER_UPDATE_ARCHITECTURE.md`
- `desktop/runtime-contract.json`
- `docs/architecture/windows-installer-operations-runbook.md`
- `docs/architecture/clippy-v1-local-runtime-contract.md`

### Python
```powershell
python -m pip install -r requirements.txt
python -m pytest tests/ -v
python -m pytest tests/test_specific.py -v
uvicorn app:app --host 127.0.0.1 --port 8000
```

### Dashboard
```powershell
cd dashboard
npm install
npm run dev
npm run build
npm run lint
```

### Renderer
```powershell
cd render-service
npm install
npm run build
npm test
npm run dev
```
Check actual scripts in `render-service/package.json`; test script names may differ by branch.

### Tauri (current Windows desktop)
Developer prerequisites include Rust stable/MSVC, Visual Studio C++ Build Tools/Windows SDK, WebView2, and Node.js. These are development prerequisites, not intended end-user prerequisites.
```powershell
cd desktop/src-tauri
cargo tauri dev
cargo tauri build
```
Do not claim these pass unless actually run. The prior agent notes reported Rust tools were not on PATH at one point; re-check the current machine rather than relying on that historical status.

### Verification discipline
- Run focused tests for changed modules, then the full relevant test suite.
- Run frontend lint/build and renderer tests/build when their code changes.
- Run `git diff --check`.
- Test actual output media with a real player/ffprobe when changing rendering.
- Test both CPU and GPU paths when changing hardware acceleration.
- Report exact command, environment, result, and any skipped test.
- Never invent a passing test, successful GPU run, clean install, or CI status.

---

## 8. GPU, video, and performance

GPU inference and hardware video encoding are separate capabilities:
- CUDA/DirectML/etc. inference support does not automatically imply NVENC works.
- NVENC availability does not prove Whisper/YOLO/other inference uses the GPU.
- Check the installed driver, GPU architecture, framework wheel, CUDA/cuDNN runtime, ONNX Runtime provider, FFmpeg build, and VRAM requirements independently.
- GTX 1650 4 GB was the developer GPU discussed in earlier project work. Treat this as historical user hardware context, not proof that every current dependency or model supports it.
- Do not hardcode a GPU model or CUDA version as universally supported.
- Make CPU fallback explicit and log which backend/encoder was selected.
- Avoid loading multiple large inference models concurrently without understanding VRAM pressure.
- Preserve model release/cleanup behavior and concurrency limits.

Useful diagnostics when available:
```powershell
nvidia-smi
ffmpeg -hide_banner -encoders
ffmpeg -hide_banner -hwaccels
```
Inside Docker, also verify the container can see the GPU. On native Windows, test the packaged runtime rather than assuming the host's developer environment is representative.

---

## 9. Security, privacy, and data integrity

- Never print, paste, commit, or include API keys, tokens, passwords, cookies, signing secrets, database URLs, or private customer data.
- Do not broadly inherit database, Stripe, OAuth, cloud-storage, or other server secrets into pipeline child processes. Preserve the `child_env()` denylist/isolation design. The backend may pass a resolved provider key to the specific job that needs it, but must not place every provider secret into the global child environment.
- Validate uploaded files, MIME/type/extension, size, and paths. Do not trust user-supplied filenames.
- Never store provider API secrets in plaintext or reversible-obfuscation browser storage. Use the documented Windows Credential Manager contract and verified migration path.
- Desktop mode must be explicitly local-only and make no silent S3/R2/cloud upload. Keep remote storage opt-in and separately approved.
- Prevent path traversal and arbitrary local-file access.
- Keep local backend/renderer bound to loopback by default. Do not expose local services to the LAN without an explicit product requirement and security design.
- Validate remote webhook/download URLs against SSRF and private-network access.
- Preserve ownership checks for job and clip access.
- Do not weaken auth or entitlement checks to make a UI feature pass.
- Treat user-generated video, transcripts, metadata, and model files as untrusted input.
- Keep generated output and user data out of Git.
- Before bundling FFmpeg, Chromium, Python, Node, CUDA libraries, or model weights, check licensing and redistribution obligations.

---

## 10. Agent workflow and coding rules

Hermes must follow this workflow for every engineering task.

### Before editing
1. Read this file.
2. Inspect `git status --short`, branch, remotes, recent commits, and relevant diffs.
3. Confirm which branch contains the requested feature and whether it is merged.
4. Read the relevant source files and tests, not just documentation.
5. Trace the feature end-to-end: UI → API → backend → subprocess/renderer → output/delivery.
6. State the issue, affected files, expected behavior, and regression risks before broad changes.
7. If a requirement is ambiguous and materially affects architecture or data, ask one focused question.

### While editing
- Make small, reviewable changes.
- Preserve API contracts, metadata schemas, user settings, and backward compatibility.
- Avoid unnecessary rewrites or new dependencies.
- Add/update tests with behavior changes.
- Keep platform-specific behavior behind clear compatibility boundaries.
- Do not replace working code with stubs or TODOs.
- Do not claim a feature works based only on UI wiring.
- Never use patch files as a substitute for understanding current source and local diffs.

### Before reporting completion
1. Inspect the final diff.
2. Run `git diff --check`.
3. Run relevant tests/builds.
4. Inspect generated artifacts and actual media output if relevant.
5. Report changed files, behavior, tests run, exact outcomes, remaining risks, and unverified items.
6. Do not commit or push unless the user explicitly asked.
7. Never claim CI is green without checking the actual workflow for the commit.

### Public repository hygiene
This repository is public. Do not add:
- Private IPs, hostnames, server paths, customer data, internal metrics, or credentials.
- Local absolute paths tied to a developer machine.
- Secrets in examples, logs, screenshots, test fixtures, or commit messages.

---

## 11. Known historical context and open verification items

These notes are useful leads, not assertions about today's working tree.

- The project began as a fork/customization of `mutonby/openshorts`.
- Main includes an earlier Clippy workspace UI merge and feature-update commit.
- Feature work has included background editing, custom watermarking, caption/hook controls, and preview changes. Earlier reports found background/watermark output issues and corrupted/empty preview behavior. Reproduce before changing.
- The November 9 audit snapshot described the native migration as a branch-only scaffold. That statement was superseded by its merge into main and the published v0.3.1 installer on November 19.
- The reference-template feature is part of the current main baseline and is explicitly retained for v1; preserve its local data through upgrades and relocation.
- Older `codex/new-ui`, `codex/reference-templates`, and `windows-native-migration` branch comparisons in the November 9 snapshot are historical. Inspect current remote refs and commit relationships before using any of those branches.
- The current root README is Clippy-branded but still contains stale v0.2.3 release links and legacy Docker/self-host guidance. Those user-facing version/scope changes are tracked for the later documentation/identity cleanup phase.
- Main's former `CLAUDE.md` and the native branch's former `AGENTS.md` contained overlapping agent guidance. Their durable project-level instructions have been consolidated here; those files are now short pointers to this master guide. Subsystem/product documents remain separate where they serve a distinct purpose.

### Required next audits
1. Generate an exact tracked-file tree with `git ls-files` on each active branch.
2. Inventory every Markdown file and classify it as product documentation, subsystem architecture, agent instructions, or historical notes.
3. Inspect any remaining feature branches against current `main`; do not revive a historical branch as the release base without an explicit decision.
4. Audit current feature wiring and tests for watermark, background, captions, hooks, reference templates, and preview/rendering.
5. For every new runtime/installer release, validate clean-machine setup, CPU/CUDA selection, payload activation/rollback, and user-data preservation against that release candidate.
6. Update this file whenever architecture, branch status, build commands, runtime paths, or product decisions change.

---

## 12. Documentation hierarchy

This file is the canonical project-level guide for agents.

- `CLIPPY_MASTER.md`: canonical project-wide product, architecture, development, and agent guide.
- `CLIPPY_CLEANUP_MASTER.md`: active, task-specific Clippy v1 cleanup ledger, scope decisions, phase gates, findings, and validation record. It does not replace this guide.
- `README.md`: public-facing project introduction and user/developer quick start. Keep it accurate; it is not the internal engineering guide.
- `CLIPPY_REPO_AUDIT.md`: dated technical audit/findings ledger. Preserve its historical evidence, but do not treat its 2026-11-09/17 branch and release snapshots as current without revalidation.
- Subsystem architecture/runtime/compliance docs under `docs/`: authoritative focused contracts for their named subsystems; link them from this file and keep them synchronized.
- `AGENTS.md` and `CLAUDE.md`: short agent entry points that must both point to this master guide and the active cleanup ledger when the task is the v1 extraction.

**Do not remove any Markdown file until it has been inventoried and its unique information migrated.** The goal is one authoritative master guide, not loss of valuable technical documentation.
