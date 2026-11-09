# Clippy Repository Audit & Agent Handover

> **Inspection date:** 2026-11-09  
> **Repository:** https://github.com/helalxp/clippy  
> **Default branch:** `main`  
> **Purpose:** Shared technical orientation and audit ledger for Claude Code, Codex, Gemini CLI, Hermes, and other engineering agents.  
> **Status:** Initial repository-wide structural audit and targeted source inspection. This is **not yet a certified line-by-line audit of every source file**, nor a runtime certification. See the coverage ledger and verification limits below.

---

## 0. Mandatory instructions for agents

1. Read this file before engineering work, then read the branch's `CLIPPY_MASTER.md` and `AGENTS.md`/ `CLAUDE.md` if present.
2. Confirm the actual checkout: `git status --short`, `git branch --show-current`, `git branch -avv`, `git remote -v`, `git log --oneline --decorate -12`.
3. Never assume the current checkout is `main`. The native Windows migration is on `windows-native-migration`, not in main.
4. Source, tests, configuration, and Git history outrank this document. If this document conflicts with checked-out code, trust the code and update this document.
5. Preserve user work and data. Do not run destructive Git commands, force-push, reset, clean, delete, overwrite, or merge without explicit authorization.
6. Do not apply stored `.patch` files without first running `git apply --check` and examining the target files and local diffs.
7. Do not call a feature complete based only on a UI control, docstring, TODO, patch file, or test name. Trace UI -> API -> backend -> processing/rendering -> persistence/output.
8. Do not claim tests/builds passed unless actually run. Record command, branch, environment, result, and date.
9. Do not silently change product scope, provider choices, model selection, GPU behavior, ports, data locations, or entitlement rules.
10. Treat all user-supplied media, URLs, prompts, API keys, webhook URLs, and external model output as untrusted input.

## 1. Product identity and direction

Clippy is a Windows-first desktop product evolving from the OpenShorts codebase. Its core workflow is to turn long-form video into short-form clips, let users refine those clips, and prepare/publish them to social platforms. The codebase also contains AI UGC/video creation, YouTube Studio tooling, cloud account/billing features, and agent/MCP interfaces.

**Product direction from the project guide:** a normal Windows desktop app that launches its own local backend and renderer; end users should not need Docker Desktop, WSL2, Python, Node.js, Rust, Git, or a terminal. First-run setup should provision/verify runtimes. Model weights are managed separately. User settings, models, jobs, logs, and output must survive upgrades.

**Critical reality check:** this product direction is not the same thing as implementation status. The default `main` branch remains Docker-oriented. The separate `windows-native-migration` branch contains a Tauri/Rust desktop scaffold and Windows-native adaptations. The desktop installer must not be described as production-ready without build, install, upgrade, clean-machine, and runtime tests.

## 2. Repository snapshot and branches

Repository metadata observed through GitHub:
- Public repository: `helalxp/clippy`
- Repository ID: `1430643349`
- Default branch: `main`
- Main HEAD at inspection: `3b398f02b83fe99ec6b1ffd029c7bd0eff3e551d`
- Reported repository size: 79,360 KB (GitHub repository size metadata; not a local checkout measurement).
- Main recursive tree: 471 entries, 421 files, 50 directories, ~86.38 MB of tracked blob content. Tree response was not truncated.

### Branch inventory

| Branch | HEAD at inspection | GitHub comparison against main | Interpretation |
|---|---|---|---|
| `main` | `3b398f02b83f` | Default branch | Docker-oriented OpenShorts-derived application, workspace UI and existing feature patches. |
| `codex/new-ui` | `c260c6bf8319` | 0 ahead / 6 behind; status `behind` | Historical UI branch. No unique commits ahead of main in the comparison; do not treat it as a separate active feature line without rechecking. |
| `codex/reference-templates` | `ba2acc1e13f6` | 1 ahead / 5 behind; status `diverged` | Contains a unique reference-template feature commit. |
| `windows-native-migration` | `653e3bc380dc` | 14 ahead / 5 behind; status `diverged` | Native Windows migration plus reference-template work. This is the branch with desktop/Tauri scaffolding. |

Branch tips are moving references. Re-run comparisons before cherry-picks, merges, or release decisions.

### Main tree composition

Main contains 421 tracked files across these extensions:

| Extension | Count |
|---|---:|
| Python | 173 |
| JSX | 50 |
| JavaScript | 25 |
| Markdown | 31 |
| TSX | 9 |
| TypeScript | 11 |
| JSON | 15 |
| YAML | 6 |
| WebP | 24 |
| PNG | 10 |
| WOFF2 | 14 |
| TTF | 6 |
| GIF | 3 |
| CSS | 5 |
| TXT | 10 |
| Other/config/patch/assets | Remaining |

The Windows migration branch has 451 files, including six Rust source files, PowerShell launch/build scripts, Tauri configuration, native renderer path code, local model settings, and additional tests. It is not equivalent to main.

### Important branch-only feature map

**`codex/reference-templates`**
- Adds `reference_templates.py`.
- Adds `dashboard/src/components/ReferenceTemplateLibrary.jsx`.
- Adds `reference_templates/<template-id>/manifest.json` and poster asset.
- Adds `tests/test_reference_templates.py`.
- Modifies `app.py`, `layout_picker.py`, and `dashboard/src/App.jsx`.
- Removes several old patch artifacts.
- It is not simply a clean forward-only branch: it diverges from main. Review its unique commit and base before integrating.

**`windows-native-migration`**
- Adds `desktop/src-tauri/` Tauri/Rust shell: `bootstrap.rs`, `downloader.rs`, `supervisor.rs`, `lib.rs`, `main.rs`, Cargo files, capabilities, and Tauri config.
- Adds `desktop/README.md`, `desktop/FIRST_RUN_SETUP_CONTRACT.md`, build scripts.
- Adds `platform_compat.py`, `clippy_local_models.py`, `runtime-manifest.json`.
- Adds dashboard local-model settings and reference-template UI.
- Adds renderer native-Windows path handling/tests and PowerShell/batch launch helpers.
- Modifies backend, dashboard, renderer, subtitles, transcription, compose, and quality-probe code.
- Adds `AGENTS.md`.
- This branch has the most direct relevance to the intended Windows desktop product, but remains a migration branch and must be validated independently.

## 3. System architecture map

### 3.1 Main branch deployment topology

Main's `docker-compose.yml` defines three services:

| Service | Container | Port mapping | Responsibility |
|---|---|---|---|
| backend | `openshorts-backend` | `8000:8000` | FastAPI application, API routes, job orchestration, cloud routers, media endpoints. |
| frontend | `openshorts-frontend` | `5175:5173` | React/Vite dashboard in development mode. |
| renderer | `openshorts-renderer` | `13100:3100` | Express/Remotion rendering service. |

Compose mounts the project into the backend, dashboard into frontend, and `./output:/output` into backend and renderer. The renderer's internal port remains 3100; host port 13100 is mapped to it. Vite proxy defaults in main are Docker service hostnames, not necessarily host-native values.

Main's backend dependencies in `requirements.txt` include FastAPI/Uvicorn, PyTorch/TorchVision, Ultralytics, MediaPipe, faster-whisper, PySceneDetect, Google GenAI, boto3, Pillow, HTTPX, and related processing libraries. This is a heavy ML/media runtime, not a small API-only service.

### 3.2 Frontend

Location: `dashboard/`

- React 18 + Vite + Tailwind.
- Main shell: `src/App.jsx`.
- Authentication/session context: `src/contexts/AuthContext.jsx`.
- API client: `src/lib/api.js`; centralizes bearer-token attachment, 402 quota errors, and JSON request handling.
- API URL/proxy config: `src/config.js`, `vite.config.js`.
- Feature UI: `src/components/` (clip results, editing, subtitles, hooks, translation, watermark, autopilot, SaaS Shorts, analytics, account, billing, etc.).
- Browser Remotion compositions: `src/remotion/`.
- SEO generation: `seo/`, `tools/`, and `vite-plugin-seo.js`.

Observed ResultCard responsibilities include clip display, preview, editing controls, background editing state, watermark/logo editor state, subtitles/hooks/translation, and browser rendering integration. This component is a high-coupling change surface; isolate new behavior and test it instead of adding more unrelated state to the card.

### 3.3 Backend/API

Location: repository root, primarily `app.py`.

- FastAPI app and REST routes.
- Job submission/status, upload/download, clip editing, subtitles, hooks, translation, social publishing, thumbnail/UGC workflows, and other API features.
- Cloud routers are under `cloud/`.
- Processing pipeline is launched/orchestrated by app code and implemented primarily in `main.py` plus specialized modules.
- `app.py` is very large (~338 KB in the main tree); avoid treating it as a small route file. Before modifying, find the exact route/helper and its callers/tests. Prefer extracting cohesive services only when behavior can be preserved and tests added.

### 3.4 Video processing pipeline

Core pipeline: `main.py`, supported by:
- `frame_sampler.py`, `gpu_decode.py`, `scene_detection.py` (scene/frame analysis and GPU decode paths).
- `clip_selection.py` (transcript windows, clip-count targets, duration bounds, batching, overlap dedupe, word snapping, trimming).
- `transcribe_backends.py` (transcription providers/backends).
- `gemini_worker.py`, `llm_backend.py`, `layout_picker.py`, `hook_grounding.py`, `hook_placement.py`, `hooks.py` (AI selection, layout and hook logic).
- `ffmpeg_utils.py`, `editor.py`, `edit_builder.py`, `recut.py`, `reframe_v2.py`, `split_layout.py`, `screencast_layout.py`, `camera_inset.py`, `active_speaker.py`, `panel_layout.py`, `punch_in.py` (video editing, reframing, layout and composition).
- `subtitles.py`, `burned_subtitles.py`, `watermarked.py`, `thumbnail.py`, `translate.py` (delivery features).
- `quality_probe.py`, `restoring_static.py`, `security_utils.py`, `media_auth.py`, `file_hosts.py`, `s3_uploader.py` (validation, security, file delivery and storage).

The pipeline uses FFmpeg/ffprobe and multiple ML/AI dependencies. Hardware decode/encode must be treated as capability-dependent. A configured GPU path is not proof that the installed FFmpeg/PyTorch/driver stack actually uses the GPU. Validate real runtime logs and output, and preserve CPU fallback.

### 3.5 Renderer

Location: `render-service/`; Remotion compositions also exist under `remotion/` and frontend preview compositions under `dashboard/src/remotion/`.

- Express server validates render request shape with Zod.
- Remotion bundle setup in `src/bundle.ts`.
- Render execution in `src/render-worker.ts`.
- Main render state is held in an in-memory `Map` (`renderJobs`) in the server process.
- Composition code: ShortVideo, HookOverlay, Subtitles, VideoEffects; shared caption/font/type helpers.
- Output is written under the configured output directory.

**Architectural concern:** in-memory render job state is lost when the renderer process restarts. Confirm how backend callers handle renderer restart, polling, retries, and orphaned output before relying on this service for durable jobs. Also verify renderer access controls and network exposure: the main Compose file publishes host port 13100 and the inspected server excerpt shows a static output mount and render route; complete the full route/auth review before deployment.

### 3.6 Cloud/SaaS services

Location: `cloud/`

Modules include account, alerts, analytics, API keys, auth, autopilot, billing, cancellation, config, database, digest, email policy, emails, lifecycle, managed keys, marketing, MCP OAuth, metering, models, OAuth, onboarding, proxy ledger, social profiles, storage, and videos.

Key observed design points:
- `cloud/auth.py`: magic-link/JWT sessions; 30-day JWT and 15-minute magic-link TTL are declared. Optional auth supports anonymous/BYOK behavior.
- `cloud/metering.py`: reservation/commit/release ledger; plan minutes and FIFO top-ups; per-user database locking is described as the concurrency guard.
- `security_utils.py`: URL allowlist/SSRF guard uses HTTP(S), DNS resolution, and globally routable IP checks.
- `media_auth.py`: signed media capabilities and short-lived per-user media tokens; allowlisted deliverable extensions and path normalization.
- `docs/architecture/agent-access.md`: describes REST/MCP/API key/OAuth/webhook interfaces.
- `docs/architecture/autopilot.md`: describes cloud-only YouTube polling, standard processing pipeline, dedupe, guardrails and optional scheduled autopublishing.
- Billing/account erasure and quota flows have extensive architecture documentation and tests. Changes to user-owned tables must be reflected in account erasure logic and its tests.

Treat architecture docs as intended/recorded design, then verify current implementation and migrations.

### 3.7 Agent and automation interfaces

- `mcp_server.py`: Streamable HTTP MCP JSON-RPC endpoint at `/mcp`.
- `mcp_stdio.py`: stdio transport for clients that launch a subprocess.
- `mcp_ui.py`: MCP UI integration.
- `cloud/mcp_oauth.py`: cloud MCP OAuth metadata/registration/consent/token exchange.
- `cloud/api_keys.py`: API key lifecycle.
- `server.json`, `glama.json`, `integrations/chatgpt-app/`, `skills/openshorts/`: agent/app distribution metadata and skill assets.
- `cli/`: Python CLI package.
- `examples/n8n/`: workflow examples.

Do not create a second auth path or duplicate business logic for MCP. Existing architecture intends MCP tools to call into the same app behavior and preserve caller authentication.

## 4. Key files and change-surface map

| Path | Role / why agents should inspect it |
|---|---|
| `app.py` | Main FastAPI application, API endpoints, job orchestration, ownership, delivery, cloud integration. Large/high-risk file. |
| `main.py` | Core video analysis and clip generation pipeline. |
| `dashboard/src/App.jsx` | Main frontend shell and feature wiring. |
| `dashboard/src/components/ResultCard.jsx` | Clip result actions/edit controls; high UI coupling. |
| `dashboard/src/lib/api.js` | Central frontend API/auth/error handling. |
| `dashboard/src/config.js` | Frontend API base URL. |
| `dashboard/vite.config.js` | Dev proxy behavior; branch-specific for Docker/native. |
| `render-service/src/server.ts` | Render API, request validation, in-memory render-job state, output serving. |
| `render-service/src/render-worker.ts` | Remotion render execution and output naming. |
| `remotion/src/` | Render compositions and shared types/helpers. |
| `cloud/auth.py` | JWT, magic-link, current-user resolution. |
| `cloud/metering.py` | Quota reservation/commit/release and probing. |
| `cloud/account.py` | Account deletion/erasure and user-owned data cleanup. |
| `cloud/models.py` | SQLAlchemy schema/models. |
| `cloud/database.py`, `alembic/`, `alembic.ini` | Database setup and migrations. |
| `security_utils.py` | SSRF/public URL validation. |
| `media_auth.py` | Media URL capabilities, media token and path policy. |
| `s3_uploader.py` | Object storage/archive/gallery integration. |
| `docker-compose*.yml`, `Dockerfile` | Runtime topology and container build. |
| `.env.example` | Configuration contract; never commit real secrets. |
| `requirements*.txt` | Python dependency sets. |
| `tests/` | Python behavior/regression/security tests. |
| `docs/architecture/` | Subsystem design notes; verify against implementation. |
| `CLIPPY_MASTER.md`, `CLAUDE.md` | Existing project onboarding/agent rules. |
| Windows branch: `desktop/src-tauri/src/supervisor.rs` | Desktop process supervision. |
| Windows branch: `desktop/src-tauri/src/bootstrap.rs` | First-run bootstrap/provisioning. |
| Windows branch: `desktop/src-tauri/src/downloader.rs` | Runtime download/provisioning. |
| Windows branch: `platform_compat.py` | OS-specific compatibility layer. |
| Windows branch: `runtime-manifest.json` | Runtime asset/version contract. |
| Windows branch: `clippy_local_models.py` | Local model configuration/management. |
| Windows branch: `render-service/src/paths.ts` | Native renderer path handling. |

## 5. Existing docs and trust hierarchy

Observed documentation:
- `CLIPPY_MASTER.md`: canonical agent/project guide; explicitly says source/tests/config/history are final truth.
- `CLAUDE.md` (main) and `AGENTS.md` (Windows migration): short agent startup rules.
- `README.md`: public OpenShorts product README; still contains OpenShorts branding, upstream `mutonby/openshorts` badges/links, Docker-first setup and public product claims.
- `docs/architecture/*.md`: subsystem architecture notes.
- `STATUS.md`, `CHANGES_COMPLETE.md`, `FINAL_SUMMARY.md`, `IMPLEMENTATION_PLAN.md`, `QUALITY_ISSUES_ANALYSIS.md`: historical implementation/status/analysis notes. These are not automatically current.

**Observed documentation drift:** `STATUS.md` refers to local `D:\openshorts\...` paths and reports pending/fixed states that must be reconciled with current code. `QUALITY_ISSUES_ANALYSIS.md` records older values and recommendations that do not consistently match the later status narrative. Do not copy those claims into current issue lists without checking source and tests.

## 6. Preliminary findings and risks

These are evidence-based review observations, not a final security certification.

### R-01: Main README/product identity is stale — medium, confirmed
Main `README.md` still identifies the project as OpenShorts, links badges/commit history to `mutonby/openshorts`, and documents Docker as the expected self-host workflow. The internal product guide says Clippy is Windows-first and migration work is on a separate branch. This creates onboarding and product-truth confusion. Decide whether the public README should remain upstream-oriented or become Clippy-specific; do not silently rewrite upstream attribution/license notices.

### R-02: Windows-native implementation is branch-only — high, confirmed
Main does not contain `desktop/`, `platform_compat.py`, `runtime-manifest.json`, or the native local-model settings present in `windows-native-migration`. The migration branch diverges from main (14 ahead / 5 behind at inspection). Do not implement native-only fixes on main assuming they will be present in the desktop app. Establish an explicit integration strategy.

### R-03: Main includes a large tracked GIF — medium, confirmed
`churchil_queen_vertical.gif` is 65,384,963 bytes (~62.4 MiB), above GitHub's recommended 50 MB warning threshold. Consider Git LFS or an external asset if the file is needed, but first check references and preserve attribution/licensing. Do not remove it blindly.

### R-04: Patch artifacts are committed alongside source — medium, confirmed
Main contains multiple patch files, including `clippy-feature-updates.patch`, `clippy-watermark-preview-fix.patch`, `openshorts-background-watermark-fix.patch`, `openshorts-combined-watermark-background-fix.patch`, and `openshorts-final-fix.patch`. These can become stale and encourage unsafe reapplication. Determine whether they are historical records or active deliverables; if historical, label/archive them rather than applying them.

### R-05: Renderer durability and access need a focused review — high, needs verification
The main renderer stores render jobs in a process-local `Map`, so job status disappears on process restart. Compose publishes renderer host port 13100. The inspected Express source mounts the output directory as static content and accepts render requests. Complete a full route-level auth/network review, verify whether only the backend can reach it in production, and test renderer restart during queued and active renders. Consider persistent job state, authenticated internal access, and bounded/allowlisted output paths if not already enforced elsewhere.

### R-06: Large, tightly coupled modules raise regression risk — medium, confirmed
`app.py` is ~338 KB; `main.py` and `dashboard/src/App.jsx` are also central orchestration surfaces. Keep changes narrow, trace all callers, and add focused tests. Avoid unrelated refactors in feature-fix patches.

### R-07: Docker and Windows runtime contracts differ — high, confirmed
Main Compose uses Linux/Docker service names, bind mounts and shared output volume. Windows migration introduces native process supervision, runtime provisioning and native renderer paths. Treat these as separate deployment contracts until a deliberate abstraction/integration is completed. Validate paths, signals, process shutdown, port ownership, firewall behavior, GPU detection, and upgrade persistence on real Windows machines.

### R-08: Documentation is not a substitute for verification — medium, confirmed
The repo has substantial architecture and status documentation, but some docs are historical and contradictory. Add dates, source references, and verified/unverified labels. Update docs in the same change as behavior changes.

### R-09: No runtime test execution performed in this inspection — high, explicit limitation
GitHub source inspection does not execute pytest, npm lint/build, TypeScript tests, Docker builds, GPU tests, Tauri builds, or installer flows. CI status and test results must be fetched/re-run before a release decision. This document does not assert that the current tree passes tests.

## 7. Security and reliability review checklist

The following areas deserve explicit review before release. Some protections are already visible in source/docs; the checklist is not a claim that every edge case is covered.

- **Authentication/authorization:** REST, MCP HTTP, MCP stdio, API keys, OAuth consent/token, media links, webhook delivery, account routes.
- **Tenant isolation:** every job, clip, upload, thumbnail, social account, billing row, API key, OAuth code, and storage object must be scoped to the authenticated owner.
- **SSRF/DNS rebinding:** all URL fetchers (video download, website scrape, image fetch, webhook target, proxy target) must validate at submission and again at delivery/use.
- **Path traversal/symlinks:** upload names, media paths, output paths, archive extraction, renderer paths, cleanup jobs.
- **Secrets:** no credentials in child pipeline environments unless needed; no secrets in logs, query strings, public static mounts, manifests or patch files.
- **Media access:** signed link expiry, token scope, allowed extensions, ownership, referrer/log leakage, cache behavior.
- **Resource exhaustion:** upload size, duration, resolution, concurrent jobs, render concurrency, disk caps, subprocess timeouts, memory/GPU limits, queue backpressure.
- **Subprocess safety:** argument arrays (not shell interpolation), environment denylist, process-tree cleanup, cancellation, orphan handling.
- **Billing correctness:** reserve/commit/release idempotency, Stripe webhook replay, subscription period boundaries, top-up FIFO, concurrent requests, deletion during webhook processing.
- **Account erasure:** all user-owned tables, local files, object storage, OAuth/API credentials, thumbnails, and logs; preserve only documented legal-retention records.
- **Renderer:** authentication, network binding, static file exposure, job persistence, output path validation, queue limits, retry/idempotency.
- **Desktop:** signed downloads, checksum/signature verification, update rollback, least privilege, runtime pinning, path safety, process ownership, clean uninstall, user-data preservation.

## 8. Testing and validation map

### Python
- Test suite: `tests/` (main tree contains many focused tests for processing, layouts, GPU decode, security, metering, billing, account erasure, MCP, media paths, proxy routing and more).
- Run from repository root in a correctly provisioned environment: `pytest -q`.
- Use focused tests first, e.g. `pytest -q tests/test_media_path_guard.py`.
- The full dependency stack is heavy and may require FFmpeg, model assets, credentials, or GPU-specific setup. Record skips and environment constraints.

### Frontend
- `cd dashboard`
- `npm ci`
- `npm run lint`
- `npm run build`

### Renderer
- `cd render-service`
- `npm ci`
- `npm test`
- `npm run build`

### Docker main
- `docker compose config`
- `docker compose build`
- `docker compose up -d`
- Verify backend readiness, frontend proxy/API calls, renderer health, output volume sharing, and end-to-end render.

### Windows migration branch
- Follow `desktop/README.md` and `desktop/FIRST_RUN_SETUP_CONTRACT.md` on that branch.
- Build Rust/Tauri and renderer using the branch's documented PowerShell scripts.
- Test on a clean Windows account/VM without developer runtimes installed.
- Verify bootstrap download integrity, offline/retry behavior, process startup/shutdown, ports, logs, GPU/CPU fallback, data persistence across upgrade, uninstall behavior, and no orphaned processes.
- A successful developer build is not proof of a production installer.

## 9. Branch-specific agent startup

### If on main
- Assume Docker-oriented deployment unless proven otherwise.
- Do not refer to native desktop files; they are not in this branch.
- Inspect the existing patch files only as historical context, not as instructions.
- Check whether public-facing OpenShorts documentation should remain unchanged before making branding changes.

### If on codex/new-ui
- Confirm branch ancestry; GitHub comparison showed it 6 commits behind main and 0 ahead.
- Do not build new work on it without a reason to preserve that branch.

### If on codex/reference-templates
- Inspect the unique reference-template commit and compare its `app.py` changes with main.
- Feature files: `reference_templates.py`, `dashboard/src/components/ReferenceTemplateLibrary.jsx`, `reference_templates/`, `tests/test_reference_templates.py`.
- Verify ownership/access controls for template upload, storage, manifest validation, and asset serving.

### If on windows-native-migration
- Read `AGENTS.md`, `CLIPPY_MASTER.md`, `desktop/README.md`, `desktop/FIRST_RUN_SETUP_CONTRACT.md`, and `render-service/NATIVE-WINDOWS.md`.
- Treat the desktop shell as a scaffold until all exit criteria are proven.
- Review `supervisor.rs`, `bootstrap.rs`, `downloader.rs`, `platform_compat.py`, `runtime-manifest.json`, `clippy_local_models.py`, and `render-service/src/paths.ts` before modifying startup or runtime provisioning.
- Do not merge this branch wholesale without reviewing the five commits on main it is behind and its 14 unique commits.

## 10. Configuration and secrets

- `.env.example` is the configuration reference; inspect it before changing environment variable names/defaults.
- Never commit `.env`, real API keys, JWT secrets, Stripe secrets, database credentials, OAuth client secrets, webhook secrets, or user data.
- Preserve the principle visible in `app.py`: pipeline subprocesses should not inherit cloud/billing/auth secrets they do not need.
- Do not paste secret values into this document, issue comments, logs, tests, screenshots, or agent prompts.
- When adding a setting, update the example env, config validation, deployment config, docs, and tests as appropriate.

## 11. Audit coverage ledger

This ledger prevents agents from mistaking a structural survey for a complete line-by-line review.

| Area | Evidence inspected in this pass | Coverage status |
|---|---|---|
| Repository metadata/default branch | GitHub repo metadata | Inspected |
| Branch list and branch heads | GitHub branches API | Inspected: all 4 reported branches |
| Recursive tree main | Recursive Git tree; 421 files | Inventory inspected |
| Recursive trees other branches | Recursive Git trees | Inventory/counts inspected; not every blob read |
| Branch diffs | GitHub compare API | Inspected for all 3 non-main branches |
| Main README and agent docs | README, CLIPPY_MASTER, CLAUDE | Targeted read |
| Historical status/quality docs | STATUS, QUALITY_ISSUES_ANALYSIS | Targeted read; drift noted |
| Architecture docs | agent access, autopilot, billing/jobs and other docs | Targeted partial read |
| Main API/backend | app.py first 90 lines; route/module structure not exhaustively traced | Partial |
| Core processing | main.py first 90 lines and module inventory | Partial |
| Cloud auth/metering | cloud/auth.py and cloud/metering.py first 90 lines | Partial |
| Security/media | security_utils.py and media_auth.py first 90 lines | Partial |
| Frontend API/result card | api.js and ResultCard.jsx first 90 lines | Partial |
| Renderer | server.ts and render-worker.ts first 90 lines | Partial |
| Windows desktop code | Branch tree and agent/master docs; Rust source not yet exhaustively reviewed | Inventory + docs only |
| Tests | Test file inventory; test source/results not exhaustively reviewed | Inventory only |
| CI/workflows | Workflow files inventoried, not executed | Not verified |
| Runtime/build/installer/GPU | Not executable through GitHub source inspection | Not tested |

**Definition of complete audit:** every tracked text/source/config/test file on each branch is read or deliberately excluded with reason; high-risk flows are traced end-to-end; findings include path + line references + severity + evidence; tests/builds are executed in declared environments; binary/media assets are inventoried and licensing/use checked; branch-specific conclusions are kept separate. This file is the shared starting point and audit ledger, not a false declaration that those steps are already complete.

## 12. Required format for future findings

When an agent discovers a bug or risk, add a finding using:

- **ID:** stable ID (e.g. `SEC-001`, `BUG-014`, `WIN-003`)
- **Severity:** critical / high / medium / low / informational
- **Branch + commit:** exact branch and HEAD SHA
- **Location:** file path and line range
- **Evidence:** observed code path, test, log, or reproduction
- **Impact:** user/security/data/reliability impact
- **Reproduction:** exact steps and environment
- **Fix direction:** smallest safe change
- **Regression test:** test added/updated and command/result
- **Status:** open / in progress / fixed-unverified / verified / accepted

Do not erase historical findings. Mark them superseded with the commit/test evidence that resolved them.

---

**End of initial audit baseline.** Update the inspection date, branch SHAs, tree counts, and coverage ledger whenever the repository changes materially.
