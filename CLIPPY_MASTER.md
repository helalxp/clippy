# CLIPPY_MASTER.md
> **Canonical engineering and agent guide for Clippy**
>
> Repository: https://github.com/helalxp/clippy  
> Default branch: `main`  
> Last repository inspection: 2026-11-09  
> Status: living document. Verify the checked-out source before relying on any implementation claim.

This document is the primary onboarding and operating guide for Hermes and other coding agents. It consolidates the product direction, repository/branch map, architecture, development workflow, migration plan, and preservation rules. **The checked-out code, tests, configuration, and Git history remain the final source of truth.** This guide is not permission to overwrite user work, merge branches, remove files, or change product scope.

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

**Important distinction:** the repository's default `main` branch still contains the Docker-oriented OpenShorts application architecture. The separate `windows-native-migration` branch contains the active native-Windows migration work. Do not describe the native installer as finished or assume that migration branch is merged into main.

### Product principles
1. Preserve working functionality before redesigning internals.
2. Prefer explicit, testable interfaces between the desktop shell, backend, dashboard, and renderer.
3. Keep local user data outside the install directory.
4. Make CPU/GPU capability and fallback behavior truthful and observable.
5. Avoid silent model substitution, destructive upgrades, hidden background processes, and unexplained port assumptions.
6. Separate confirmed implementation from plans, prototypes, and historical reports.

## 2. Repository identity and Git state

- GitHub repository: `helalxp/clippy`
- Public repository.
- Default branch: `main`
- Main is based on customized OpenShorts.
- The inspected repository reports these branches:

| Branch | Relationship to main at inspection | Purpose / known contents |
|---|---|---|
| `main` | Default branch | Current committed OpenShorts-derived application and feature work. Docker Compose is still the documented full-stack workflow. |
| `codex/new-ui` | Behind main by 1 commit; no unique commits ahead in the comparison | Earlier workspace UI work. The UI merge is already represented in main history. Treat this as a historical/possibly stale branch, not a separate active feature line. |
| `codex/reference-templates` | 1 commit ahead of main | Reference-template library feature and related cleanup. Adds `reference_templates.py`, `dashboard/src/components/ReferenceTemplateLibrary.jsx`, a template asset/manifest, and tests; modifies `app.py`, `layout_picker.py`, and `dashboard/src/App.jsx`; removes several temporary patch files. |
| `windows-native-migration` | 9 commits ahead of main | Native Windows compatibility and desktop migration line. Adds Tauri/Rust desktop scaffold, bootstrap/downloader/supervisor, local model settings, platform compatibility, renderer path/server changes, runtime manifest, tests, and `AGENTS.md`. Also includes reference-template work. |

Branch relationships above are based on GitHub branch search and branch comparisons against `main` on 2026-11-09. Re-run comparisons before any merge or release; branch tips move.

### Mainline history observed
Recent main commits included:
- `97981a2` — Merge Clippy workspace UI
- `c260c6b` — feat: introduce clippy workspace UI
- `414973c` — Apply Clippy feature updates
- `e81d1f7` — Save current OpenShorts modifications
- `0789262` — Initial commit of customized OpenShorts

These messages are orientation only. Inspect commit diffs for the exact behavior of any change.

### Branch handling rules
- Never assume a branch is merged because its feature appears in another branch.
- Before starting work, run `git status --short`, `git branch --show-current`, `git branch -avv`, `git remote -v`, and inspect recent commits.
- Compare feature branches with main before cherry-picking or merging.
- Do not force-push, reset, clean, or discard local changes without explicit approval.
- Do not apply an old patch blindly. Run `git apply --check` first and reconcile local diffs.
- When a feature branch is not merged, clearly identify it as branch-only in reports and docs.

---

## 3. Architecture overview

The application has four major logical layers. Their exact deployment differs by branch.

### A. React/Vite dashboard
Location: `dashboard/`

Responsibilities:
- Main user interface and navigation.
- Clip generation forms and job progress/results.
- Clip result cards and editing workflows.
- Settings and user-provided API keys.
- Local model settings UI on the Windows migration branch.
- Reference-template library UI on the reference-template branch and Windows migration branch.
- Calls backend APIs through a configurable API base URL or Vite development proxy.
- Uses Remotion-related browser/player packages for preview-related UI where implemented.

Main entry/configuration files observed:
- `dashboard/package.json`: React 18, Vite, Tailwind, Remotion player/media packages, Mediabunny, Zod.
- `dashboard/src/App.jsx`: large top-level dashboard composition and workflow state.
- `dashboard/vite.config.js`: dev proxy configuration for backend and renderer.
- `dashboard/src/components/`: feature components; inspect actual directory for current inventory.
- `dashboard/build-desktop.ps1` on the native branch: desktop-specific build helper.

The dashboard's Vite dev proxy on main defaults to Docker service names:
- Backend: `http://backend:8000`
- Renderer: `http://renderer:3100`

The native migration changes this assumption for desktop builds and uses loopback URLs. Do not hard-code Docker hostnames into desktop production code.

### B. Python/FastAPI backend
Main files include:
- `app.py`: FastAPI application, HTTP endpoints, job queue/admission, subprocess creation, job status, file delivery, editing APIs, optional cloud integration.
- `main.py`: command-line processing pipeline executed as a child process per job.
- `requirements.txt`: Python runtime dependencies.
- `llm_backend.py`: OpenAI-compatible local/remote LLM routing.
- `s3_uploader.py`: S3-compatible artifact/gallery operations.
- `recut.py`, `layout_ranges.py`, `watermarked.py`, `media_auth.py`: editing/delivery support modules imported by `app.py`.
- Additional pipeline modules are described in the subsystem map below.

Backend architecture:
1. FastAPI accepts uploads/URLs and validates requests.
2. A queue/admission layer controls concurrency and job lifecycle.
3. Each processing job runs `main.py` as a separate subprocess.
4. The parent backend passes a sanitized child environment. In the inspected main `app.py`, `CHILD_ENV_DENYLIST` removes sensitive cloud/server credentials before the pipeline process is launched.
5. The child performs transcription, scene analysis, moment selection, clipping, reframing, and rendering-related work.
6. Job metadata and artifacts are written to the job output directory.
7. The API exposes job state, logs, clip URLs, and editing/publishing actions.

Do not move secrets into child-process environments. Do not weaken upload validation, path validation, ownership checks, or authentication to make a feature work.

### C. Node.js / Remotion render service
Location: `render-service/`

Responsibilities:
- Server-side video rendering and Remotion composition.
- Receives render requests from the backend.
- Bundles/uses Remotion compositions and renders output files.
- Serves a local render API and media paths.

Main files observed:
- `render-service/package.json`: Node ESM package with Express, Remotion bundler/renderer, TypeScript, tsx, Zod.
- `render-service/src/server.ts`: HTTP server and render endpoints.
- `render-service/src/bundle.ts`: Remotion bundle preparation.
- `render-service/src/render-worker.ts`: render execution worker.
- `render-service/src/paths.ts`: native-branch path resolution and validation.
- `render-service/src/paths.test.ts`: native-branch path tests.
- `render-service/run.ps1`, `start.ps1`, `start-renderer.bat`: Windows launch helpers on the migration branch.
- `render-service/NATIVE-WINDOWS.md`: native renderer notes on the migration branch.

On main, Docker Compose maps host port `13100` to renderer container port `3100`; the renderer's `PORT` is `3100`. The dashboard proxy defaults to the Docker service name and port `3100`. On the native migration branch, renderer communication is being adapted to local loopback paths and managed output directories. Always inspect the checked-out branch's configuration before assuming ports or paths.

### D. Tauri desktop shell (native migration branch only)
Location: `desktop/src-tauri/`

Technology: Tauri 2 + Rust.

Responsibilities intended/implemented in the scaffold:
- Native Windows application window using the existing dashboard.
- Start, stop, and report status for the local backend and renderer.
- Resolve managed runtime/application/data paths.
- Bootstrap/check local services and capture logs.
- Keep local services bound to loopback.
- Separate install payload from persistent per-user data.

Files observed on `windows-native-migration`:
- `desktop/src-tauri/Cargo.toml`, `Cargo.lock`: Rust dependencies.
- `desktop/src-tauri/tauri.conf.json`: Tauri app/build configuration.
- `desktop/src-tauri/src/main.rs`, `lib.rs`: shell entrypoints.
- `desktop/src-tauri/src/bootstrap.rs`: first-run/runtime bootstrap orchestration.
- `desktop/src-tauri/src/downloader.rs`: download support.
- `desktop/src-tauri/src/supervisor.rs`: local process supervision.
- `desktop/src-tauri/capabilities/default.json`: Tauri capabilities.
- `desktop/README.md`: scope and scaffold limitations.
- `desktop/FIRST_RUN_SETUP_CONTRACT.md`: first-run setup contract.
- `desktop/build.ps1`, `build-tauri.ps1`: Windows build helpers.

**Status caveat:** the desktop branch's own README describes Stage 3A as a scaffold and says the downloader, signed/checksummed runtime manifest flow, resumable setup UI, payload updater, and production NSIS packaging pipeline are not yet implemented. The scaffold is not proof of a usable end-user installer. A successful Tauri build/launch on the developer's machine was not verified during this repository inspection.

---

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
10. **Persist and deliver** — metadata and files are saved under the job output area; optional S3/R2/cloud behavior depends on configuration.
11. **Publish** — optional Upload-Post integrations distribute/schedule content.

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
The project has historical feature work and bug reports around:
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

This feature is branch-specific relative to main at the inspection date. The native migration branch also includes these changes. Before using it on main, inspect and merge deliberately; do not assume it is present on main.

---

## 5. Windows-native migration roadmap

The native migration branch is the forward path for the Windows desktop product. The stages below distinguish intent from verified completion.

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

This is a functional map, not a promise that every listed path exists on every branch. Run `git ls-files` to obtain the exact current tree.

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
- `docker-compose.yml`: main-branch Docker topology.
- `runtime-manifest.json`: native-branch runtime provisioning metadata; verify schema and signatures/checksums.
- `.env.example` / `.env`: configuration; never expose secret values.
- `.gitignore`: generated files, secrets, caches, local outputs.
- GitHub Actions workflows: inspect `.github/workflows/` before changing CI assumptions.

---

## 7. Development and verification commands

Always inspect the checked-out branch and local modifications first. These are baseline commands; adjust for the current branch and installed tools.

### Docker-oriented development (main)
```powershell
docker compose up --build
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f renderer
```
Typical main-branch endpoints:
- Dashboard: `http://localhost:5175`
- Backend: `http://localhost:8000`
- Backend readiness: `http://localhost:8000/health/ready`
- Renderer host mapping: `http://localhost:13100` to container port `3100`

Do not assume those endpoints are used by native desktop builds.

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

### Tauri (native migration branch)
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
- Do not place server secrets in child pipeline processes. Preserve the `child_env()` denylist/isolation design.
- Validate uploaded files, MIME/type/extension, size, and paths. Do not trust user-supplied filenames.
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
- The native migration branch has a Tauri scaffold, Windows compatibility work, local model settings, and renderer path changes. It is not yet a confirmed production installer.
- The reference-template feature is one commit ahead of main on `codex/reference-templates` and is also included in the native migration branch comparison.
- The `codex/new-ui` branch is behind main and has no unique commits ahead according to the comparison at inspection time.
- Main's README is still the upstream-style OpenShorts product/installation README and describes Docker as the self-host setup. It is not yet a complete Clippy native desktop user manual.
- Main's `CLAUDE.md` contains extensive upstream architecture notes and hard rules. The native branch's `AGENTS.md` contains Clippy's Windows-first mission, migration stages, and agent workflow. This master file consolidates the durable project-level guidance from both, but subsystem docs may still contain details not repeated here.

### Required next audits
1. Generate an exact tracked-file tree with `git ls-files` on each active branch.
2. Inventory every Markdown file and classify it as product documentation, subsystem architecture, agent instructions, or historical notes.
3. Reconcile `main`, `codex/reference-templates`, and `windows-native-migration` before deciding which branch becomes the release base.
4. Audit current feature wiring and tests for watermark, background, captions, hooks, reference templates, and preview/rendering.
5. Finish native runtime/bootstrap and clean-machine packaging validation.
6. Update this file whenever architecture, branch status, build commands, runtime paths, or product decisions change.

---

## 12. Documentation hierarchy

This file is the canonical project-level guide for agents.

- `CLIPPY_MASTER.md`: product mission, branch map, architecture overview, project map, engineering rules, roadmap, and agent workflow.
- `README.md`: public-facing project introduction and user/developer quick start. Keep it accurate; it is not replaced by this internal master guide.
- Subsystem architecture docs under `docs/`: retain focused implementation details where they exist. Link them from this file and keep them synchronized.
- Old agent instruction files such as `CLAUDE.md` and branch-specific `AGENTS.md`: migrate any unique, still-valid guidance into this master file before removing or redirecting them. Do not delete subsystem/product docs just because they are Markdown.

**Do not remove any Markdown file until it has been inventoried and its unique information migrated.** The goal is one authoritative master guide, not loss of valuable technical documentation.
