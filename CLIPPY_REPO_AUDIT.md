# Clippy Repository Audit & Agent Handover

> **Inspection date:** 2026-11-09  
> **Repository:** https://github.com/helalxp/clippy  
> **Default branch:** `main`  
> **Purpose:** Shared technical orientation and audit ledger for Claude Code, Codex, Gemini CLI, Hermes, and other engineering agents.  
> **Status:** Expanded repository audit in progress. This document is the canonical agent handover and audit ledger. It is **not yet a certified line-by-line audit of every tracked source file or every branch**, and no local runtime/build was executed in this inspection. Verified CI results and targeted findings are recorded below; the coverage ledger must remain explicit.

---

## 0. Mandatory instructions for agents

1. Read this file before engineering work, then read branch-specific `AGENTS.md` / `CLAUDE.md` and platform contracts if present.
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
- Main source snapshot: `ff879df772fc0051ffb3eb75f1e5e02987c95789`
- Reported repository size: 79,360 KB (GitHub repository size metadata; not a local checkout measurement).
- Main recursive tree: 460 entries, 410 files, 50 directories, ~86.38 MB of tracked blob content. Tree response was not truncated.

### Branch inventory

| Branch | HEAD at inspection | GitHub comparison against main | Interpretation |
|---|---|---|---|
| `main` | `ff879df772fc` | Default branch | Docker-oriented Clippy application, current dashboard and backend source. |
| `codex/new-ui` | `c260c6bf8319` | 0 ahead / 27 behind; status `behind` | Historical UI branch. No unique commits ahead of main in the comparison; do not treat it as a separate active feature line without rechecking. |
| `codex/reference-templates` | `ba2acc1e13f6` | 1 ahead / 26 behind; status `diverged` | Contains a unique reference-template feature commit. |
| `windows-native-migration` | `653e3bc380dc` | 14 ahead / 26 behind; status `diverged` | Native Windows migration plus reference-template work. This is the branch with desktop/Tauri scaffolding. |

Branch tips are moving references. Re-run comparisons before cherry-picks, merges, or release decisions.

### Main tree composition

Main contains 410 tracked files across these extensions:

| Extension | Count |
|---|---:|
| Python | 173 |
| JSX | 50 |
| JavaScript | 25 |
| Markdown | 25 |
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
| `CLIPPY_REPO_AUDIT.md`, `CLAUDE.md` | Canonical engineering handover and short agent entrypoint. |
| Windows branch: `desktop/src-tauri/src/supervisor.rs` | Desktop process supervision. |
| Windows branch: `desktop/src-tauri/src/bootstrap.rs` | First-run bootstrap/provisioning. |
| Windows branch: `desktop/src-tauri/src/downloader.rs` | Runtime download/provisioning. |
| Windows branch: `platform_compat.py` | OS-specific compatibility layer. |
| Windows branch: `runtime-manifest.json` | Runtime asset/version contract. |
| Windows branch: `clippy_local_models.py` | Local model configuration/management. |
| Windows branch: `render-service/src/paths.ts` | Native renderer path handling. |

## 5. Existing docs and trust hierarchy

Observed documentation:
- Root `CLIPPY_MASTER.md` was consolidated into this file and removed from main. The native migration branch still has its own branch-specific copy.
- `CLAUDE.md` (main) and `AGENTS.md` (Windows migration): short agent startup rules.
- `README.md`: current Clippy project overview. It distinguishes the Docker-oriented main development stack from the unfinished Windows-native migration branch.
- `docs/architecture/*.md`: subsystem architecture notes.
- Historical root reports (`STATUS.md`, `CHANGES_COMPLETE.md`, `FINAL_SUMMARY.md`, `IMPLEMENTATION_PLAN.md`, `QUALITY_ISSUES_ANALYSIS.md`) were read, superseded, and removed from main after their durable context was migrated into this audit.

**Historical documentation drift:** the removed status/quality reports contained local `D:\openshorts\...` paths and conflicting recommendations. Their claims were checked against current source and CI before removal; the verified current failures are recorded in F-01 and F-02.

## 6. Preliminary findings and risks

These are evidence-based review observations, not a final security certification.

### R-01: Main README/product identity was stale — resolved
The legacy OpenShorts README was replaced with a Clippy-specific overview in commit `1f4e2e02e95c2429f7e6a1364525d2126c6d0569`. The new README accurately states that main remains Docker-oriented and the Windows-native branch is still a scaffold. Upstream attribution and the repository's `LICENSE` / `NOTICE` were retained.

### R-02: Windows-native implementation is branch-only — high, confirmed
Main does not contain `desktop/`, `platform_compat.py`, `runtime-manifest.json`, or the native local-model settings present in `windows-native-migration`. The migration branch diverges from main (14 ahead / 26 behind at the `ff879df` source snapshot). Do not implement native-only fixes on main assuming they will be present in the desktop app. Establish an explicit integration strategy.

### R-03: Main includes a large tracked GIF — medium, confirmed
`churchil_queen_vertical.gif` is 65,384,963 bytes (~62.4 MiB), above GitHub's recommended 50 MB warning threshold. Consider Git LFS or an external asset if the file is needed, but first check references and preserve attribution/licensing. Do not remove it blindly.

### R-04: Temporary patch artifacts were committed alongside source — resolved by cleanup
The five temporary root patch artifacts were removed from main after confirming they are not runtime inputs. Do not recreate or reapply them as a substitute for source-level changes.

### R-05: Renderer durability and access require hardening — high, confirmed exposure surface
The main renderer stores job status in a process-local `Map`, losing status on restart. More importantly, `render-service/src/server.ts:50,58,124` serves the shared output directory and exposes render submission/status routes without authentication or ownership checks. `docker-compose.yml:32-33` publishes host port 13100 without a loopback-only bind. See F-03 for the verified exposure path and fix direction.

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
| Recursive tree main | Recursive Git tree; 410 files at the cleanup snapshot | Inventory inspected |
| Recursive trees other branches | Recursive Git trees | Inventory/counts inspected; not every blob read |
| Branch diffs | GitHub compare API | Inspected for all 3 non-main branches |
| Main README and agent docs | Clippy README, audit, CLAUDE | Targeted read |
| Historical status/quality docs | Read before removal; durable facts migrated into this audit |
| Architecture docs | agent access, autopilot, billing/jobs and other docs | Targeted partial read |
| Main API/backend | app.py:1-500 targeted; route families and call paths not exhaustively traced | Partial |
| Core processing | main.py:80-230 plus selected download/processing paths; full file not read | Partial |
| Cloud auth/metering | auth.py:1-240, metering.py:1-260, account.py:1-260; other cloud modules not read | Partial |
| Security/media | full security_utils.py and media_auth.py; callers/redirect behavior need deeper review | Partial |
| Frontend API/result card | api.js and AuthContext.jsx targeted; ResultCard.jsx and other components not fully read | Partial |
| Renderer | full main server.ts and render-worker.ts read; integration/auth tests not run | Targeted; integration remains |
| Windows desktop code | supervisor.rs, bootstrap.rs, downloader.rs, lib.rs, platform_compat.py, local model manager and manifest targeted | Partial; no Windows build/install test |
| Tests | tree inventory, two failing test sources, latest completed CI log | Partial; remaining test files not read individually |
| CI/workflows | CI definition, latest completed run for ec3092e and failure logs; later documentation runs pending | Verified for inspected run; latest pending |
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

**End of initial structural survey.** The expanded findings and coverage ledger below supersede this baseline where they differ.


---

# Deep audit update — 2026-11-09

## Current repository state (re-verified)

- Default branch: `main`
- Source snapshot HEAD: `ff879df772fc0051ffb3eb75f1e5e02987c95789`
- Recursive Git tree: 460 entries, 410 tracked files, 50 directories.
- Branch comparisons against source snapshot:
  - `codex/new-ui`: 0 ahead / 27 behind; no unique commits.
  - `codex/reference-templates`: 1 ahead / 26 behind; diverged.
  - `windows-native-migration`: 14 ahead / 26 behind; diverged.
- The prior audit's main SHA, branch behind counts, and file count are superseded by this snapshot.

## CI verification on current main HEAD

GitHub Actions run: [CI run for ec3092e](https://github.com/helalxp/clippy/actions/runs/42646257926)

- Backend test job: **failed**.
- Frontend build job: **passed**.
- Backend result: **1,226 passed, 30 skipped, 2 failed**.
- Failed tests:
  1. `tests/test_generation_controls.py::TestClipDurationBounds::test_env_overrides_apply`
  2. `tests/test_recut.py::TestPerformRecut::test_source_path_reframes_and_watermarks`

### F-01 — Clip duration override is incorrectly narrowed — medium, confirmed

Evidence:
- `clip_selection.py:186-187`
- `tests/test_generation_controls.py:25-28`

The function widens any range narrower than 15 seconds, but the assignment uses `lo + 5.0`. For `CLIP_MIN_SECONDS=20` and `CLIP_MAX_SECONDS=30`, the condition is true and the result becomes `(20.0, 25.0)`, contradicting the test and the caller's explicit max. The existing logic also makes the comment and implementation disagree.

Fix direction: preserve a valid user-supplied range. Only repair an inverted/degenerate range according to a documented policy; do not silently narrow a valid 20–30 second request. Add boundary tests for 5, 10, 15, 20, 30, 60, 175, and 180 second limits.

### F-02 — Source-path recut watermark call is incompatible with the real watermark function — high, confirmed production-path defect

Evidence:
- `recut.py:326-328`
- `tests/test_recut.py:278-284`

The production call passes `backdrop_type` and `backdrop_color` keyword arguments. The test injects `watermarker=lambda path: ...`, which rejects those keywords. Follow-up inspection of the actual production target confirms `main.apply_watermark(video_path, output_path=None)` accepts neither keyword. Therefore the default source-path recut implementation also raises TypeError whenever watermark=True reaches this branch. The test double is stale, but it exposed a real production call-contract defect.

Fix direction: choose one stable watermarker contract. Either extend main.apply_watermark to support the requested backdrop options (if those options are genuinely part of the intended watermark feature) or remove the unsupported kwargs from recut. Update the fake to match the chosen protocol and add a test that uses the real function signature through a monkeypatched implementation. Then exercise a source-path recut with watermark=True using a real short media fixture.

## High-priority security findings

### F-03 — Renderer publicly serves the entire shared output directory and accepts unauthenticated render requests — high, confirmed exposure surface

Evidence:
- `render-service/src/server.ts`: `express.static(OUTPUT_DIR)` exposes the entire shared output tree under `/output`, with no authentication or media allowlist. This includes non-dotfile metadata JSON and other files beyond deliverable media.
- The same server accepts `POST /render` and `GET /render/:renderId` without authentication or ownership checks.
- `docker-compose.yml` publishes host port 13100 to container port 3100 without a loopback-only host bind; the main-branch renderer calls `app.listen(PORT)` without a host argument and therefore binds all interfaces.
- `RestoringStaticFiles` on the backend has an extension/path allowlist but no per-user or signed capability check; its own docstring explicitly says clips and source video remain public to anyone who has the job ID (see F-25).
- media_auth.py implements capability and user-token helpers, but app.py and mcp_server.py do not call sign_media_url, mint_user_token, or token-verification helpers; app.py only calls media_auth.is_servable. There is no /api/media-token route and dashboard/src/config.js does not append a media token.

Impact: anyone who can reach the renderer port can enumerate/fetch known output paths, including non-deliverable metadata, and can submit/poll render jobs without a user identity. The backend's /videos path is also bearer-by-job-ID rather than user-authenticated; the renderer is worse because it serves the full output directory, not just allowed media extensions. Docker's published port is normally reachable on host interfaces, subject to firewall/network policy.

Required fix direction: make renderer an internal-only service in cloud/container deployments, or add strong service authentication and per-job ownership authorization. Bind local desktop renderer to loopback. Do not serve the whole output directory publicly; use scoped, authorized media delivery. Wire media capability/user tokens through both backend media handlers and dashboard URLs before claiming media is private. Add tests proving anonymous clients cannot read private outputs or submit/poll another user's renders.

### F-04 — SSRF validation is vulnerable to DNS time-of-check/time-of-use changes — medium, needs exploit verification

Evidence:
- `security_utils.py:89-105`
- `main.py:933` also sets yt-dlp's `nocheckcertificate=True`.

The guard resolves a hostname, checks the returned addresses, then returns the original URL. The downstream HTTP client/yt-dlp performs its own resolution and follows redirects. The validation result is therefore not cryptographically or transport-bound to the address that is ultimately contacted. DNS rebinding and redirect behavior need explicit tests. Disabling certificate verification further weakens transport protection.

Caller review now narrows the scope: SaaSShorts scrape_website disables automatic redirects and validates every Location hop; webhook delivery disables redirects and re-resolves before every attempt; selected-actor HTTPX download uses the default no-auto-redirect behavior. The main YouTube/direct-file path validates the initial URL, then calls file_hosts.resolve and yt-dlp; file_hosts uses urllib.request.urlopen (which follows redirects) without a per-hop public-address check, and yt-dlp is configured with nocheckcertificate=True. This leaves the download path as the priority unresolved redirect/DNS-rebinding surface. Fix direction: enforce safe destination validation at every redirect and connection, or use a fetch layer that pins the validated address while preserving the correct TLS hostname/certificate verification. Review every caller, not just the initial URL parser. Do not mark this finding fixed based only on another preflight DNS lookup.

## Windows-native migration branch findings (branch-only)

These findings apply to `windows-native-migration`, not main.

### F-05 — Desktop runtime manifest path is hard-coded to a developer checkout — high functional blocker

Evidence:
- `desktop/src-tauri/src/lib.rs:34`

The `check_runtime` Tauri command constructs `manifest_path` as `D:\openshorts\runtime-manifest.json`. This will not resolve on a normal user's machine or an install path other than that developer directory. The current `Bootstrap` implementation also does not read the manifest when producing status; `get_status` checks executable presence and versions only.

Fix direction: resolve the manifest relative to the installed application payload or a documented managed app root, pass the path through the bootstrap configuration, and test paths containing spaces and non-default install roots on Windows.

### F-06 — Runtime manifest contains placeholder integrity values — high release blocker if used

Evidence:
- `runtime-manifest.json:10`, `:17`, `:24`, and `:37`

The checked-in manifest contains obviously placeholder-looking SHA-256 values and `manifest_hash_placeholder`. At least the FFmpeg release URL also appears to be a sample/non-release identifier. These values cannot establish artifact integrity. The branch's own desktop documentation explicitly says the signed/checksummed manifest flow is not implemented yet.

Fix direction: do not ship or execute this manifest. Populate verified upstream artifacts, real SHA-256 values, platform/architecture metadata, and a verifiable signed manifest before wiring downloads into first-run setup.

### F-07 — ZIP extraction helper constructs output paths from archive entry names — medium, reachability unverified

Evidence:
- `desktop/src-tauri/src/downloader.rs:132-145`

The helper joins `dest` with `entry.name()` and writes to that path without an explicit canonical containment check. If this helper is ever used with an untrusted archive, entries containing traversal components may write outside the destination. The separate `Bootstrap::install_from_archive` uses the ZIP library's `extract` helper, but the call graph for `Downloader::extract` was not fully established in this pass.

Fix direction: canonicalize/validate every entry path, reject absolute paths, drive prefixes, parent components, symlinks and other unsafe entry types, and add ZIP-slip regression tests before using this method.

### Native branch readiness

The branch's own `desktop/README.md` describes Stage 3A as a scaffold. The downloader, manifest verification, resumable setup UI, payload updater and production installer are not complete. Do not present this branch as an end-user-ready Windows installer.

## Documentation consolidation and deletion policy

This audit file is now the intended canonical project/architecture/branch/audit handover. The former root `CLIPPY_MASTER.md` material has been consolidated into this document's architecture map, branch notes, workflow, GPU guidance, security rules, and verification discipline. `CLAUDE.md` remains a short entrypoint to this file.

Historical root status/change reports and saved patch artifacts are not runtime dependencies. They are being removed after the verified findings and durable instructions are preserved here. Focused subsystem docs under `docs/architecture/`, compliance/legal docs, CLI docs, desktop migration contracts, agent skill files, and operational runbooks are retained because they serve active technical, legal, packaging, or user-workflow purposes.

The legacy root README is being replaced with a Clippy-specific, branch-accurate README. Demo media and screenshot assets are preserved until their full reference/use scan is complete; this pass did not establish that every such asset is unused.

## Coverage ledger — expanded but not complete

| Area | Inspection performed | Status |
|---|---|---|
| Repository tree | Current recursive main tree and branch heads | Complete for current snapshot |
| Branch divergence | GitHub compare for all four listed branches | Complete for current snapshot |
| Agent/project guides | Read root CLAUDE, root CLIPPY_MASTER, audit; read native branch AGENTS and desktop contracts | Targeted, migrated into this file |
| Root historical docs | Read all five historical reports before deletion | Complete for listed files |
| CI | Read current main workflow definition, latest run and failing job logs | Complete for latest run inspected |
| Core backend | Targeted sections of app.py, main.py, clip_selection.py, recut.py, security_utils.py, media_auth.py | Partial; full line-by-line review remains |
| Cloud services | Targeted sections of auth.py, metering.py, account.py, models.py | Partial; remaining modules and complete files remain |
| Renderer | Full server.ts and render-worker.ts inspected on main; native path module targeted | Targeted; full integration and auth review remains |
| Frontend | API client/AuthContext targeted; main shell and components not yet reviewed end-to-end | Partial |
| Native desktop | Supervisor, bootstrap, downloader, lib, platform compatibility, model manager and runtime manifest targeted | Partial; Windows build/install/runtime tests not run |
| Tests | Latest CI outcome and two failure sources inspected; test inventory/tree inspected | Partial; individual test coverage and untested paths remain |
| Assets | Tree and README asset references inspected | Not fully audited |
| Runtime verification | No local checkout, Docker, Windows machine, GPU, or media fixtures available to execute in this inspection | Not performed |

**Completion rule:** Do not relabel this audit as “full line-by-line complete” until every tracked text/source/config/test/script file on each in-scope branch has been read or explicitly classified as generated/vendor/opaque binary, references have been checked, and required builds/tests have been executed in a suitable environment. A source read is not a runtime certification.


## Repository cleanup record — 2026-11-09

The main-branch documentation cleanup was committed as individual GitHub contents commits. The legacy OpenShorts-branded root README was replaced with a Clippy-specific overview; the short `CLAUDE.md` entrypoint now points to this audit. Root `CLIPPY_MASTER.md` was consolidated into this audit and removed from main. The five historical root status/change/plan reports and five saved patch artifacts were removed after their relevant context was read and migrated. Focused architecture, compliance, CLI, skills, and operational documentation were retained.

Source snapshot and branch comparisons in this document refer to main HEAD `ff879df772fc0051ffb3eb75f1e5e02987c95789` before this audit-document refresh commit. The audit-document commit itself is documentation-only and will advance main after that snapshot. Branch comparisons at this snapshot: `codex/new-ui` 0 ahead / 27 behind; `codex/reference-templates` 1 ahead / 26 behind; `windows-native-migration` 14 ahead / 26 behind.


Additional documentation corrections in this cleanup:
- `docs/architecture/jobs-and-deploys.md` now distinguishes the 1-hour cloud default from the 24-hour self-host default for job retention.
- `docs/architecture/agent-access.md` no longer overstates the submit/delivery URL re-check as a complete DNS-rebinding defense.
- `design.md` is retained as the active dashboard/landing design system and now uses Clippy branding.
- The generic Vite-template `dashboard/README.md` was removed; it contained no Clippy-specific setup or operational instructions.


## Live audit checkpoint — 2026-11-09 15:52 UTC

This checkpoint supersedes older snapshot values above where they refer to a previous main HEAD. Historical snapshots are retained only as history.

### Re-verified repository state
- Current main HEAD: `1710a1d4e98cd5579d27e6c97c959557034799e0`.
- Current main tree: 460 entries, 410 files, 50 directories; GitHub tree response was not truncated.
- Tracked file extension counts: Python 173; JSX 50; JavaScript 25; Markdown 25; TSX 9; TypeScript 11; JSON 15; YAML 6; WebP 24; PNG 10; WOFF2 14; TTF 6; GIF 3; CSS 5; TXT 10; remaining files are other/config/asset formats.
- Branch tips: `main=1710a1d4e98c`, `codex/new-ui=c260c6bf8319`, `codex/reference-templates=ba2acc1e13f6`, `windows-native-migration=653e3bc380dc`.
- Current compare results against main: new-ui 0 ahead / 30 behind; reference-templates 1 ahead / 29 behind; windows-native-migration 14 ahead / 29 behind.
- Largest tracked blob remains `churchil_queen_vertical.gif` at 65,384,963 bytes. It is retained pending exhaustive reference and packaging checks.

### Latest CI run rechecked
- Run: [42648783960](https://github.com/helalxp/clippy/actions/runs/42648783960), commit `1710a1d4e98c`.
- Frontend build: passed.
- Backend tests: failed, 1,226 passed, 30 skipped, 2 failed (15.55 seconds).
- Failure 1: `tests/test_generation_controls.py::TestClipDurationBounds::test_env_overrides_apply`. With `CLIP_MIN_SECONDS=20` and `CLIP_MAX_SECONDS=30`, `clip_duration_bounds()` returns `(20.0, 25.0)`. This confirms F-01 remains present on current main.
- Failure 2: `tests/test_recut.py::TestPerformRecut::test_source_path_reframes_and_watermarks`. The injected test callback accepts only `path`, while `recut.perform_recut` calls it with `backdrop_type` and `backdrop_color`. This confirms the test-contract mismatch in F-02. Inspect the real `watermarked.apply_watermark` implementation and its other callers before changing production behavior.
- CI emitted a separate warning that the workflow's Node 20 action runtime is deprecated and actions are being forced onto Node 24. This is maintenance debt, not the cause of the backend test failures.

### Audit execution log
- Phase 0 (repository/branch/tree/CI baseline): rechecked at current HEAD; inventory and branch comparisons complete for this snapshot.
- Phase 1 (runtime/config/build/dependency contracts): started. Main Compose confirms the renderer is published as `13100:3100` on all host interfaces by default. This is a deployment exposure concern when used on an untrusted network; verify whether the backend/renderer is intended to be reachable only on a trusted local machine before release.
- Phases 2–8 remain open. The source, test, frontend, cloud, renderer, native Windows, and asset ledgers must be updated as each file group is read. No claim of full audit completion is made.

### Next verification targets
1. Complete Phase 1 by reading every root and service-level runtime/config/build/dependency file, comparing Docker and native Windows contracts, and checking workflow scripts.
2. Resolve F-01 with boundary tests and preserve explicit valid duration ranges.
3. Inspect the actual watermarker signature and adapt the test fake/protocol without weakening production behavior.
4. Trace renderer callers, authentication boundaries, network exposure, and media serving before assigning final exploitability/severity to F-03.
5. Trace every `assert_public_url` caller and downstream HTTP/yt-dlp redirect behavior before finalizing F-04.



## Phase 1 findings: runtime, build, dependency and configuration contracts

**Inspection completed in this batch (main @ 1710a1d4e98c):** .env.example, Dockerfile, .dockerignore, .gitignore, docker-compose.yml, docker-compose.override.yml, docker-compose.cloud.yml, docker-compose.e2e.local.yml, requirements.txt, requirements-billing.txt, .github/workflows/ci.yml, .github/workflows/publish-cli.yml, alembic.ini, render-service/Dockerfile, render-service/package.json, render-service/tsconfig.json, remotion/package.json, remotion/tsconfig.json, dashboard/package.json, dashboard/vite.config.js, dashboard/nginx.conf, dashboard/Dockerfile, cli/pyproject.toml, cli/README.md, and bin/ffmpeg. This is a configuration/build-contract review, not runtime validation.

### F-08: Uvicorn trusts forwarded client headers from every source: high, confirmed configuration defect

Evidence:
- Dockerfile: Uvicorn starts with --proxy-headers and --forwarded-allow-ips "*".
- .env.example: explicitly warns never to use "*", because callers could forge the client IP used by rate limiting and rights declarations; it documents narrowing trust to the reverse proxy.
- app.py around line 468: first-video-per-network enforcement fingerprints request.client.host.
- app.py around lines 3192-3194: rights attestation reads X-Forwarded-For directly and accepts its first value.
- Base Compose publishes backend port 8000:8000 on host interfaces.

The Dockerfile's wildcard overrides the documented trust boundary. With Uvicorn proxy headers enabled and every sender trusted, a direct caller can supply forwarding headers and influence the client address seen by request handlers. The attestation route independently trusts the header without checking whether the sender is a configured proxy. This undermines IP-based abuse controls and the reliability of recorded network attribution. It is not evidence that authentication or all quota controls can be bypassed.

Fix direction: make the trusted proxy set explicit and configurable; use the documented FORWARDED_ALLOW_IPS setting instead of a hard-coded wildcard; ensure the API port is not publicly exposed behind a reverse proxy; and derive attestation IP only from a trusted proxy chain or the direct peer. Add tests for direct forged headers, trusted-proxy chains, and untrusted proxy sources.

### F-09: Default Compose override forces NVIDIA GPU reservation: high setup compatibility risk, confirmed configuration

Evidence:
- docker-compose.override.yml sets build arg GPU=1 and reserves all NVIDIA GPU/video devices for the backend.
- The base docker-compose.yml has no GPU reservation.
- Dockerfile documents GPU=0 as the default CPU build and GPU-specific packages as optional.
- Docker Compose automatically merges the default override file for a standard compose up invocation when both default-named files are present.

A standard Compose startup therefore opts into the GPU build and NVIDIA device reservation even when the user intended to use the CPU-compatible default. Hosts without an NVIDIA GPU/container runtime can fail at build or startup. This conflicts with the Dockerfile's CPU-default design and makes the default setup non-portable.

Fix direction: keep the base Compose path CPU-compatible. Move GPU settings into an explicitly named opt-in file (for example docker-compose.gpu.yml) that users select with -f, or use a documented profile/override mechanism that does not activate by default. Test CPU-only and NVIDIA hosts separately. Do not remove GPU support.

### Configuration/build observations (not yet defects unless runtime evidence confirms)
- The backend image installs both base and cloud billing dependencies unconditionally, while cloud imports are gated by BILLING_ENABLED. This increases image size but is documented as intentional one-image deployment.
- The backend image installs a moving yt-dlp pre-release and clones the bgutil provider at the latest default-branch revision. These are not pinned to immutable versions/commits, so identical Dockerfile builds can change over time. Consider pinning or recording resolved versions for reproducible releases.
- Dashboard and renderer Dockerfiles use Node 18 base images; CI currently uses Node 20 for the frontend build. The workflow also reports Node 20 action-runtime deprecation. Align supported Node versions after checking Remotion/Vite compatibility and deployed runtime constraints.
- dashboard/Dockerfile production build uses npm install rather than npm ci, despite a committed lockfile. This weakens deterministic container builds.
- render-service/Dockerfile also uses npm install rather than npm ci and does not copy a package lockfile before installing. Dependency resolution is therefore not reproducible.
- .dockerignore excludes every *.gif from the backend build context. All three tracked root GIFs are consequently absent from the image unless mounted separately. Their runtime/UI references still need an exhaustive scan before any asset deletion decision.
- cli/pyproject.toml and cli/README.md still identify the package as OpenShorts and point to the upstream OpenShorts site/repository. This may be intentional compatibility/upstream attribution, but it is inconsistent with the Clippy-branded root product overview and should be decided explicitly before publishing the CLI under the Clippy product identity.
- alembic.ini states that cloud startup uses create_all and Alembic is for later controlled schema evolution. Verify that model changes and account-erasure tests remain synchronized; do not assume migrations are automatically applied at startup.
- bin/ffmpeg is a PATH wrapper that injects decoder/filter thread limits but deliberately leaves encoder thread options alone. Verify that all subprocesses resolve this wrapper and that FFMPEG_REAL_BIN points to the intended real binary on each platform.

### Phase 1 coverage update
- Read all listed root deployment/dependency/CI files and the dashboard, renderer, Remotion and CLI build metadata listed above.
- Not yet read: every nested platform-specific script/config, every workflow-adjacent release file, complete Docker build output, cloud production environment examples, native Windows branch equivalents, and all dependency lockfile metadata.
- No Docker build, compose config render, container startup, frontend lint, renderer build, Remotion typecheck, CLI wheel build, or Windows build was executed in this remote source inspection.
- Phase 1 remains **partial**, not complete.


## Phase 2 findings: backend/API route and ownership review

**Inventory performed on main @ 1710a1d4e98c:**
- app.py: 7,599 lines, 54 HTTP route decorators, 207 top-level functions/classes.
- main.py: 2,733 lines, 42 top-level functions/classes; no HTTP routes (processing/pipeline module).
- 47 root-level Python modules were enumerated. This phase has mapped the route surface and read selected high-risk route/helper sections; it has not yet completed a line-by-line review of all 173 Python files or every route body.

### Route/ownership observations
- Most core job routes visibly call _ensure_job_files and/or _assert_job_owner before reading or mutating job content: status, source, downloads, edit, transcript, EDL, rerender, scenes, background, watermark, reframe, subtitles, hooks, translation, thumbnail sessions, SaaS job status, and render polling.
- Social analytics and scheduled-post routes delegate to _social_analytics_auth, which resolves the caller's Upload-Post key and forces the managed profile in cloud mode. Scheduled-post cancellation checks the returned profile's scheduled-post list before deleting.
- Public gallery pages and public UGC/actor galleries are explicitly public by design in the current implementation. This is a product/privacy decision, not automatically a defect.
- Cloud account restore verifies the authenticated user against the Project row before restoring files. Standard video jobs use owner sidecars during disk recovery; SaaSShorts retry handling is a separate path and currently does not use that sidecar mechanism.
- Upload PUT route uses a UUID upload slot as a bearer capability and does not authenticate the PUT request itself. The subsequent process call checks the slot's user_id in _take_pending_upload. This may be intentional for agent upload flows, but the bearer capability and overwrite semantics need a dedicated threat-model/test review.

### F-10: SaaSShorts disk retry can reassign a persisted job to a different cloud user — high, confirmed source-level tenant-isolation defect

Evidence:
- app.py around lines 7389-7445.
- A retry for a job still present in saas_jobs calls _assert_job_owner.
- If the job is absent from memory, the code instead resolves output/saas_<retry_job_id> with _safe_under and accepts the directory if it exists.
- It then writes a new in-memory record with user_id set to the current caller.
- Unlike the standard job restore path, this SaaSShorts retry path does not read or validate a persisted .owner sidecar, and the creation path shown does not write one.

Impact: after a process restart (when saas_jobs is empty), a cloud user who knows another SaaSShorts job UUID can submit it as retry_job_id. If the old output directory remains, the endpoint can re-use and modify that directory and assign its in-memory owner to the new caller. This is a cross-tenant ownership gap conditional on knowing the job ID and the directory surviving. UUID unpredictability reduces discoverability but is not an authorization control.

Fix direction: persist an owner record at job creation and verify it before disk retry; fail closed when an existing directory has no owner record in cloud mode. Add a restart simulation test: create as user A, clear process memory, attempt retry as user B, expect 404; retry as user A should succeed.

### F-11: Thumbnail media directory is mounted publicly despite the media-auth contract — high privacy exposure, confirmed

Evidence:
- app.py mounts /videos through RestoringStaticFiles with _media_guard, but mounts /thumbnails directly with Starlette StaticFiles and no guard or auth handler.
- media_auth.py documents /videos and /thumbnails as protected prefixes and defines deliverable-extension/path checks and capability/user-token helpers.
- app.py comments say the old static mounts exposed actor photos and face crops, and describes both prefixes as needing real handlers; the actual thumbnail mount contradicts that stated design.
- thumbnail.py writes generated thumbnails and person_reference.jpg beneath output/thumbnails/<session_id>/ and returns public-style /thumbnails/<session_id>/<file> URLs.
- thumbnail.py extracts face frames/crops for use as person references. These are biometric-like close-up images and should not be assumed public.

Impact: anyone who obtains a thumbnail session's URL can request files from the thumbnail directory without a user token, path capability, or ownership check. Depending on generated files and URL leakage, this can expose generated thumbnails, face-reference crops and other session images. The media_auth allowlist is not applied to this mount.

Fix direction: replace the direct StaticFiles mount with an authenticated/capability-aware handler that applies media_auth path normalization and extension allowlisting, checks the session/job owner for user-token requests, and supports explicit signed URLs only where public sharing is intended. Add tests that anonymous requests to a private session's thumbnail/frame URLs return 404, owner-token requests succeed, expired tokens fail, and only intended public assets can be shared.

### Phase 2 review limits and next steps
- Read selected route/helper sections covering request identity, job ownership, uploads, process submission/attestation, project restoration, background/watermark edits, render proxy, social analytics/scheduling, thumbnail upload/generation/frames, SaaS analysis/generation/retry/status, media mounts, and media path helpers.
- The full implementations of all 54 routes, all cloud routers, MCP endpoints, free tools, and every root Python module still require review.
- Continue with the video pipeline and security-sensitive helpers, then finish the backend route matrix and test mapping. Do not infer that a route is safe merely because a helper name appears in the route.


## Phase 3 checkpoint: video pipeline and media processing

### F-02 production impact confirmed
The production watermark implementation was inspected at main.py around lines 1462-1528. Its actual callable is apply_watermark(video_path, output_path=None); it does not accept backdrop_type or backdrop_color. recut.py passes both keyword arguments to the default implementation. Therefore the current source-path recut watermark branch is broken in production, not merely a test-fixture mismatch. The CI test failure is a valid signal of a real integration defect.

### Additional pipeline inspection
- main.py was fetched in full for structural inventory (2,733 lines; 42 top-level definitions) and targeted review of YouTube download and watermark paths.
- recut.py was read in full (approximately 300 lines). It provides a standard-library-oriented EDL/recut engine, source and fast paths, word-timed transcript remapping, temporary-file cleanup, optional reframe, watermark and caption hooks.
- watermarked.py was read in full. It is a filename/marker helper for free-plan delivery copies; it does not implement the visual watermark rendering function.
- clip_selection.py duration bounds and tests/test_generation_controls.py were read. The test suite expects valid explicit 20–30 second bounds to remain unchanged; the implementation narrows this to 20–25 seconds.
- main.download_youtube_video validates the initial URL with assert_public_url, then passes it through file_hosts.resolve and yt-dlp. The yt-dlp options currently set nocheckcertificate=True. Redirect/host behavior across file_hosts and yt-dlp remains under review.
- SaaSShorts website scraping explicitly disables automatic redirects and revalidates each redirect hop. This narrows the earlier SSRF concern for that specific scraper, but does not establish safety for every other URL consumer.
- The visual watermark implementation probes dimensions and runs FFmpeg/GPU decode with a local watermark asset. The free-plan naming/marker layer is separate from that render function.

### New pipeline review questions
- Verify every caller of main.apply_watermark and recut.perform_recut against the actual signatures.
- Review user-uploaded logo read limits: the clip watermark route calls logo.read() before checking its 10 MB cap; this means the cap is checked after the entire upload has already been read into memory. Check other uploaded image paths for the same pattern and record a finding if the behavior is reachable.
- Trace file_hosts.resolve and yt-dlp redirect/download behavior against SSRF protections, including certificate verification and proxy paths.
- Review all FFmpeg command builders for shell invocation, path quoting, timeout, metadata scrubbing, codec fallback, and CPU/GPU parity.
- Review generated intermediate files, sidecars and media delivery rules together; the /thumbnails static-mount finding F-11 is especially relevant to generated face-reference images.

Phase 3 remains partial. No media fixture, FFmpeg render, GPU path, or Windows-native media execution was run in this remote source inspection.


### F-12: Image upload byte limits are checked after unbounded reads — medium, confirmed resource-control defect

Evidence:
- app.py around lines 4863-4900: clip watermark upload calls await logo.read() with no size argument, then checks whether the returned byte string exceeds 10 MB.
- app.py around lines 6534-6600: thumbnail generation reads optional face and background uploads fully with await face.read() / await background.read(), with no corresponding byte limit in the route.
- app.py SaaS actor upload uses the safer bounded pattern, reading MAX_BYTES + 1 and rejecting before storing more data.

Impact: the configured 10 MB watermark limit does not bound memory consumption because the entire upload is already loaded before the check. The thumbnail face/background upload paths have no visible size cap. A permitted caller can cause large memory allocations and potentially exhaust worker memory with oversized multipart uploads. Cloud entitlement gates reduce who can reach some paths but are not a resource limit.

Fix direction: read at most max_bytes + 1, reject immediately when the cap is exceeded, and validate actual image content/dimensions before expensive processing. Apply consistent limits to watermark, thumbnail face/background, actor image, and other upload paths. Add tests for exactly-at-limit and over-limit streams.

### F-13: Thumbnail generation accepts an unchecked session_id as a filesystem path — medium, confirmed path-validation defect

Evidence:
- app.py around lines 6534-6600: /api/thumbnail/generate accepts session_id from a multipart form. It only performs _assert_job_owner if that session_id happens to exist in thumbnail_sessions; a missing session is not rejected.
- The route computes a basename-safe thumb_upload_dir for uploaded references, but passes the original unsanitized session_id to generate_thumbnail.
- thumbnail.py around line 664 constructs output_dir with os.path.join("output", "thumbnails", session_id) and calls os.makedirs(output_dir, exist_ok=True). It later writes generated JPEGs into that directory.

Impact: a caller can supply traversal components or an absolute path as session_id when no in-memory session exists. The thumbnail generator then creates directories and writes generated image files outside the intended thumbnails/session directory. The generated file content is model-produced rather than attacker-controlled, and filenames include a random batch token, so this is not by itself arbitrary code execution; it is still an unintended filesystem write/path traversal surface and may enable disk/resource abuse.

Fix direction: require an existing, owner-verified session when session_id is supplied, or generate a server-owned session ID for sessionless/manual mode. Validate IDs against a strict UUID format at the API boundary and independently resolve/check the final output path under the configured thumbnail root in thumbnail.py. Add traversal, absolute-path, missing-session, and cross-user tests.

### Phase 2/3 follow-up: upload and thumbnail paths
The public thumbnail mount finding F-11 is compounded by the fact that the thumbnail generator writes generated thumbnails and person_reference.jpg under the same output tree. The upload-read limits and unchecked session path are separate defects and should be fixed independently.


### SSRF caller matrix update (F-04)
- Main YouTube/direct-file download: initial URL check exists, then file_hosts.resolve and yt-dlp; file_hosts uses urllib.request.urlopen with automatic redirects, and yt-dlp follows its own extractor/HTTP redirects. yt-dlp's shared options set nocheckcertificate=True. This is the priority path for deeper SSRF review.
- SaaS website scrape: explicit follow_redirects=False and up to five redirect hops, each Location revalidated with assert_public_url. The same pattern is used for same-host subpages.
- Webhook delivery: revalidates the URL on every attempt and sets follow_redirects=False.
- Selected actor URL download: validates the initial URL; HTTPX default is no automatic redirect following.
- This matrix reduces the scope of F-04 but does not close it. DNS rebinding between validation and connection remains possible for clients that resolve again; redirects in the main downloader need transport-level enforcement.

### Phase 3 coverage ledger update
| Component | Inspection | Status |
|---|---|---|
| main.py | Full file fetched for structural inventory; YouTube downloader and watermark implementation inspected | Partial |
| recut.py | Full file read; call contract and CI failure traced | Targeted complete for recut implementation, not end-to-end |
| watermarked.py | Full file read; delivery marker/name helpers | Complete for this small module |
| clip_selection.py | Duration bounds function inspected; remaining selection logic not reviewed | Partial |
| thumbnail.py | Output path and image-generation save flow inspected; remaining 789 lines not fully reviewed | Partial |
| file_hosts.py | Full small module read; redirecting urllib fetch identified | Complete for this small module |
| security_utils.py | Full small module read; DNS resolution and IP classification inspected | Complete for this small module |
| media_auth.py | Main helpers and intended token model inspected; full test/caller matrix remains | Partial |
| FFmpeg/GPU | Selected command construction and watermark GPU wrapper inspected | Partial; no real media/GPU execution |


## Phase 4 checkpoint: cloud identity, metering, account erasure and durable storage

### Modules reviewed in this batch
- cloud/auth.py: current-user resolution, JWT/API-key authentication, magic-link request and verification flow, reviewer login and attribution route inventory.
- cloud/api_keys.py: key generation/hash, last-used refresh, create/list/revoke endpoints and session-only key management.
- cloud/database.py: engine startup, create_all, additive schema statements and session helpers.
- cloud/models.py: model inventory and user-owned foreign-key/unique-constraint map.
- cloud/metering.py: reservation/commit/release and per-user row locking.
- cloud/account.py: account erasure flow and user-owned row deletion.
- cloud/storage.py: user/job R2 key layout, presigned links and prefix deletion.
- cloud/videos.py: archive, project restore, project-state persistence, history and retention entrypoints.
- app.py: managed process reservation path and request-to-ledger flow.

### Positive controls verified
- API keys are generated with cryptographic randomness; only SHA-256 hashes are stored; raw keys are returned once. Key management rejects API-key authentication and requires a session JWT.
- Magic-link verification locks the token row with SELECT FOR UPDATE, rejects used/expired tokens, and marks the token used in the same transaction as account lookup/creation.
- Metering serializes reservations with a per-user SELECT FOR UPDATE lock, reserves before work, commits after success, and refunds exact top-up allocations on release.
- Project restore checks the authenticated user's ownership against the Project row before downloading from the user's R2 prefix.
- History queries are scoped by authenticated user_id and return time-limited presigned URLs.
- Account erasure explicitly deletes user-owned rows, email-keyed magic-link tokens, storage prefixes and local working files, then writes a minimal deletion record.

### F-14: Account deletion has a check-then-act race with new job reservations — high, needs concurrency reproduction

Evidence:
- cloud/account.py around lines 251-334: delete_account reads the User row and counts reserved UsageLedger rows, then releases the DB session before Stripe cancellation, R2 deletion, local purge and _erase_rows.
- app.py around lines 368-500: reserve_process_minutes checks entitlement and later calls metering.reserve_minutes; it does not check an account-deletion state.
- cloud/metering.py around lines 597-648: reserve_minutes locks the User row, but account deletion's initial in-flight check does not take/hold that same lock or mark the user as deleting.
- _erase_rows deletes the User and user-owned rows only after the external side effects.

A new process request can begin after the in-flight count returns zero but before account erasure completes. Its reservation/job may be created while deletion is cancelling services or purging storage. Depending on timing, a job can write local files after local purge or archive output to R2 after the prefix deletion. The later User deletion may also race with the reservation transaction. This can violate the promised account-erasure result.

Fix direction: add an explicit account-deletion state/lock. Mark the user as deleting in a short committed transaction before checking in-flight work; make authentication/entitlement and reservation paths reject new work for deleting users; then wait/reject if existing reservations remain and perform the idempotent cleanup. Add a concurrency test that interleaves process reservation with account deletion and verifies no local/R2 object can be created after the final purge.

### F-15: Project-state request size cap trusts Content-Length only — medium, confirmed request-boundary weakness

Evidence:
- cloud/videos.py around lines 405-444: save_project_state rejects when the Content-Length header exceeds 262,144 bytes, then calls request.json() without a bounded stream read.
- If Content-Length is absent (for example, a chunked request) or is not a reliable representation of the body length, the JSON body is not bounded by this check.

Impact: an authenticated client can submit an arbitrarily large project-state JSON body and force it to be buffered/parsed. The normal dashboard is unlikely to do this, but the endpoint's advertised 256 KiB cap is not enforced for all request framing.

Fix direction: read a bounded request stream (limit + 1) or use a server-level body-size limit that applies regardless of Content-Length, then parse JSON. Add tests for oversized bodies with and without Content-Length.

### Cloud review notes requiring more inspection
- cloud/database.py catches and logs additive schema-step failures, then continues startup. Determine which columns/indexes are required by current queries and whether a partial schema can safely serve traffic. A missing required additive column should fail startup or be surfaced as a readiness failure rather than silently deferring the error to a later request.
- Cloud account deletion checks reserved work only once and allows unmetered post-processing routes (e.g. free subtitle operations) to continue racing with deletion; F-14 should cover all job/session writes, not just process reservations.
- cloud/videos.py persists metadata JSON (including transcript and rights attestation) in the user's private R2 prefix. This is intentional for project restoration but must be covered by deletion, retention and data-export tests.
- cloud/videos.py project-state size check needs a transport-independent cap; server-side validation of active_layers structure and maximum clip count should also be reviewed.
- Auth, API key and metering controls are promising but not a complete cloud audit. Billing, OAuth, MCP OAuth, social profile, autopilot, cancellation, lifecycle/email, proxy ledger, onboarding, alerts and digest modules remain to be reviewed.

Phase 4 remains partial; no PostgreSQL, Stripe, R2, OAuth, concurrency, or account-erasure integration test was executed during this remote source inspection.


## Phase 5 checkpoint: Remotion renderer and render API

### Files inspected
- render-service/src/server.ts (full file)
- render-service/src/render-worker.ts (full file)
- render-service/src/composition-metadata.test.ts (full file)
- remotion/src/compositions/ShortVideo.tsx (full file)
- app.py /api/render and /api/render/{render_id} proxy routes
- renderer package scripts and TypeScript configuration were inspected in Phase 1.

### F-16: Main-branch render job ID is used as an unchecked filesystem path — high, confirmed on main; fixed in the Windows migration branch

Evidence:
- render-service/src/server.ts accepts jobId as any non-empty string (Zod min(1)); it does not enforce a UUID or safe path segment.
- render-service/src/render-worker.ts computes jobOutputDir with path.join(outputDir, jobId), then creates it recursively and writes a generated MP4 inside it.
- app.py /api/render forwards the caller's JSON body to the renderer without validating jobId or checking that the caller owns the referenced job.

Impact: a caller who can reach the renderer can supply traversal components in jobId so the worker creates directories and writes generated media outside OUTPUT_DIR. The generated filename is timestamped and not an arbitrary overwrite primitive, but the directory escape can write files outside the intended media root and consume disk in other writable locations. The direct renderer route is unauthenticated (F-03); the backend proxy also lacks a job ownership/path check.

Branch comparison: windows-native-migration adds render-service/src/paths.ts::resolveJobOutputDirectory, which validates safe characters and confirms containment beneath OUTPUT_DIR; render-worker.ts uses that helper. This closes the specific worker path-escape in that branch, but the API still needs server-side ownership checks and tests. Main does not contain the helper and remains vulnerable. Fix direction: treat jobId as a strict UUID (or server-issued opaque identifier) at both API boundaries; derive output paths only from a validated server-side job record; resolve the final path and assert it remains beneath OUTPUT_DIR before mkdir/write. Add traversal, absolute-path, Windows drive-prefix and separator tests.

### F-17: Render proxy accepts untrusted video URL and unbounded render parameters — high, confirmed missing validation

Evidence:
- app.py /api/render checks managed entitlement but forwards the caller's entire JSON body without validating job ownership or the video URL.
- render-service/src/server.ts validates only that videoUrl is a string and that durationInFrames, fps, width and height are positive; there are no practical upper bounds.
- The renderer rewrites paths matching /videos/<job>/<file> to its own /output static server, but otherwise passes the supplied videoUrl through unchanged.
- remotion/src/compositions/ShortVideo.tsx passes videoUrl directly to the browser-side Video component, which is loaded by the server-side Remotion renderer.
- The renderer has no per-user concurrency/queue limit. Its HTTP server starts an executeRender task for each request.
- The backend commits the fixed render reservation as soon as the renderer accepts the job, not when the actual render completes.

Impact: the render service can make server-originated requests to arbitrary URLs during rendering, creating an SSRF/internal-resource fetch surface. The caller can also request a render of another job's media by supplying a foreign jobId/videoUrl because the proxy does not verify ownership of the referenced job. Positive-only duration/dimension validation allows pathological values that can consume excessive CPU, memory and disk. The fixed charge at enqueue does not bound actual work.

Fix direction: accept a job_id/clip_index only, load the caller-owned job and clip server-side, derive the source media URL internally, and reject arbitrary caller-provided videoUrl. Enforce strict maximum duration, fps, width, height, effects/subtitle payload size, render queue depth and per-user concurrency. Reserve/settle usage based on a bounded render policy, with failed/cancelled jobs handled consistently. Add SSRF, cross-tenant, huge-dimension, huge-duration and queue-flood tests.

### Renderer architecture and CI observations
- Render status is held in a process-local Map; restart loses queued/running/completed state. The backend's _render_owners map is also process-local, so cloud polling after a backend restart cannot recover ownership/status even if the renderer process still has the job.
- The renderer exposes the entire shared OUTPUT_DIR under /output. This bypasses the backend's /videos allowlist and owner/capability checks; see F-03.
- render-service/package.json defines a test script for composition metadata, but .github/workflows/ci.yml runs only Python tests and the dashboard build. The renderer test is not run by CI.
- remotion/package.json defines a TypeScript build/typecheck script, but CI does not run it.
- The renderer Dockerfile uses Node 18 and npm install, while the frontend CI uses Node 20. Lockfile/reproducibility and supported-runtime alignment remain open.
- The current renderer contract test checks dynamic composition metadata and fallback defaults, but no render integration, path containment, authorization, output retention or process-restart test is present in the inspected test file.

Phase 5 remains partial. No Remotion bundle build, renderer test, actual video render, network-isolation test, queue stress test or restart recovery test was run in this remote source inspection.


## Phase 7 checkpoint: Windows-native migration branch

**Branch inspected:** windows-native-migration @ 653e3bc380dc. Its recursive tree contains 508 entries / 451 files and is not truncated. The branch is 14 commits ahead and 29 behind the then-current main snapshot at the time of comparison; it is not merged and must be audited as a separate product line.

### Files read in this batch
- AGENTS.md, CLIPPY_MASTER.md, desktop/README.md, desktop/FIRST_RUN_SETUP_CONTRACT.md.
- All six Rust source/build files: build.rs, bootstrap.rs, downloader.rs, lib.rs, main.rs, supervisor.rs.
- Cargo.toml, Cargo.lock metadata, tauri.conf.json, capabilities/default.json, runtime-manifest.json.
- platform_compat.py, clippy_local_models.py.
- dashboard/package.json, dashboard/src/config.js, dashboard/src/lib/api.js, dashboard/vite.config.js, dashboard/build-desktop.ps1.
- desktop/build.ps1, desktop/build-tauri.ps1, render-service/run.ps1, render-service/start.ps1, render-service/start-renderer.bat.
- render-service/src/paths.ts, render-service/src/server.ts, render-service/src/render-worker.ts.

### F-05 refinement: runtime manifest path is hard-coded, and the manifest is not read at all — Stage 3B blocker

The native Tauri command check_runtime constructs manifest_path as D:\openshorts\runtime-manifest.json, which is not portable. More importantly, bootstrap.rs never reads config.manifest_path or parses RuntimeManifest. get_status only checks whether Python, Node and FFmpeg executables exist and can run their version commands. verify_installation only checks existence and is not used by get_status. There is no manifest version/hash validation in the current code path.

This is consistent with desktop/README.md saying the runtime-manifest/download/bootstrap flow is not implemented in Stage 3A. Treat it as a required Stage 3B implementation item, not as a functioning checksum-verification system. The fixed path is still a concrete bug in the scaffold's exposed check_runtime command.

### F-06 refinement: runtime-manifest.json contains placeholder values — Stage 3B release blocker

The Python, Node and FFmpeg SHA-256 fields are obvious non-hex placeholder strings; the FFmpeg release URL also contains a placeholder build identifier, and manifest_sha256 is the literal manifest_hash_placeholder. Because bootstrap currently does not consume the file and the downloader is not wired, these values are not currently being used to install code. They make the manifest unusable for a real installer and must be replaced by verified immutable artifact URLs and checksums before any Stage 3B release.

### F-07 refinement: unsafe custom ZIP extractor is currently dormant, not on the active install path

downloader.rs::Downloader::extract joins dest with entry.name() and writes files without canonical containment validation. This is a ZIP-slip hazard if that method is ever called with an untrusted archive. However, no call site for Downloader::extract or Downloader::new was found in the inspected native branch. bootstrap.rs::install_from_archive currently calls zip::ZipArchive::extract instead. Therefore F-07 is a latent unsafe helper, not a confirmed reachable exploit in the current Stage 3A flow. Remove the duplicate helper or harden it before wiring the downloader into bootstrap. The active zip crate extraction path still needs an explicit malicious-archive test before being relied upon.

### F-18: Native supervisor kills only service parent processes, not their descendants — high reliability defect

Evidence:
- desktop/src-tauri/src/supervisor.rs starts Uvicorn and the Node renderer as separate Child processes.
- The backend launches main.py job processes; the Remotion renderer launches browser/render worker processes.
- stop_child only calls Child::kill() and Child::wait() on the direct process. Startup rollback paths use the same direct-child kill pattern.
- No Windows Job Object, process group, descendant enumeration, or tree-kill mechanism is present in the inspected supervisor.

On Windows, terminating a process with TerminateProcess does not automatically terminate its child processes. A stop/restart can therefore leave Python pipeline jobs, Chromium/Remotion helpers or other descendants running after the UI reports the backend/renderer stopped. Orphans can continue consuming CPU/GPU/RAM/disk, keep files locked, or interfere with the next startup.

Fix direction: create each service tree inside a Windows Job Object configured with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, assign the process immediately after spawn, and close/terminate the job on stop and every startup-failure path. Ensure descendants cannot escape the job. Add a Windows integration test that starts a fake parent which spawns a child, stops the service, and verifies both PIDs exit.

### F-19: Packaged desktop frontend build does not set the required API base URL — high functional blocker

Evidence:
- dashboard/src/config.js sets API_BASE_URL to import.meta.env.VITE_API_URL or an empty string. Empty means relative /api paths.
- desktop/README.md says the packaged dashboard must use http://127.0.0.1:8000 because Tauri's packaged UI is not served by Vite's development proxy.
- dashboard/build-desktop.ps1 sets VITE_API_URL to http://127.0.0.1:8000 before running npm run build.
- However, tauri.conf.json beforeBuildCommand runs cd ../../dashboard && npm run build directly; it does not invoke build-desktop.ps1 or set VITE_API_URL.
- desktop/build.ps1 and desktop/build-tauri.ps1 also run npm run build without setting VITE_API_URL.
- dashboard/package.json has only dev, build, lint and preview scripts; there is no build:desktop script that injects the URL.

The normal Tauri build therefore embeds an empty API base URL unless the developer happened to export VITE_API_URL in the parent environment. The packaged WebView then sends relative /api requests to its Tauri origin rather than the local FastAPI server at 127.0.0.1:8000. This contradicts the documented desktop contract and is likely to make the packaged UI unable to reach its backend.

Fix direction: add an explicit build:desktop script or change beforeBuildCommand to invoke a checked-in script that sets VITE_API_URL and fails if it is absent; use the same path in every supported packaging command. Inspect the final built bundle for the literal loopback API base and test an installed NSIS build.

### F-20: Desktop build scripts compile the Rust binary but do not build the NSIS installer — medium packaging mismatch

Evidence:
- tauri.conf.json declares NSIS as the bundle target.
- desktop/README.md instructs developers to use cargo tauri build to produce the installer.
- desktop/build.ps1 and desktop/build-tauri.ps1 call cargo build, not cargo tauri build. They therefore compile the crate but do not invoke Tauri's bundler or produce the documented NSIS installer.
- Both scripts hard-code D:\openshorts paths, so they are not clone-location portable.

Fix direction: use cargo tauri build (or the supported tauri-cli invocation) in the packaging script, resolve the repository root from $PSScriptRoot, and verify the expected installer artifact exists before printing success. Keep a separate cargo build command if a fast compile-only workflow is desired.

### Native branch render-service comparison
- The Windows migration branch has already added render-service/src/paths.ts. Its resolveJobOutputDirectory validates jobId against a strict safe-character pattern and checks containment beneath OUTPUT_DIR; render-worker.ts uses it. This addresses the main-branch F-16 path traversal in this branch.
- The same paths.ts validates path segments when translating /videos or /output URLs, rejecting decoded dot segments, slashes and NUL bytes.
- F-17 is not closed by that helper: resolveRendererVideoUrl returns non-/videos and non-/output URLs unchanged, so the renderer can still fetch arbitrary caller-supplied URLs. server.ts still accepts unbounded positive duration/fps/dimensions and has no authentication or queue cap.
- The branch renderer defaults to binding 127.0.0.1, which is appropriate for the desktop shell. Verify that Docker deployment explicitly sets HOST=0.0.0.0 and that host port exposure is intentional; loopback-only desktop mode does not fix the main Docker deployment.
- render-service/run.ps1, start.ps1, start-renderer.bat and the desktop build scripts contain hard-coded D:\openshorts paths. These are developer convenience scripts but fail when the repository is cloned elsewhere.

### Native branch documentation and implementation alignment
- AGENTS.md directs agents to CLIPPY_MASTER.md rather than the new main-branch CLIPPY_REPO_AUDIT.md. The branch's CLIPPY_MASTER.md is a 556-line branch-local handover and should be reconciled before this branch is merged or used as the main development branch.
- The native README correctly labels Stage 3A as a scaffold and explicitly says runtime download, signed/checksummed manifest, resumable installer UI, payload updater and production NSIS packaging are not implemented. Preserve this status; do not describe the branch as an end-user-ready installer.
- BootstrapStatus reports GPU only via nvidia-smi. The AMD/Intel vendor branches are unreachable with nvidia-smi output; the current implementation is NVIDIA/CUDA detection only. Align the UI/documentation with the actual supported accelerator set or add vendor-specific detection.
- The first-run contract expects embedded Python packages, FFmpeg, Node, Remotion browser runtime and optional GPU components, but bootstrap currently only checks Python/Node/FFmpeg executables. The full dependency installation/health checks are still Stage 3B work.

Phase 7 remains partial. No Windows cargo build, Tauri dev run, NSIS packaging, Job Object test, clean-machine first-run install, or installed-app API smoke test was executed. Branch-specific test files and remaining scripts/configs still require review.


### F-21: OAuth authorization-code redemption is not serialized as single-use — medium, confirmed race

Evidence:
- cloud/mcp_oauth.py around lines 315-351: /oauth/token selects OAuthCode by code_hash, checks used_at, validates client/redirect/PKCE, then sets used_at and inserts a new ApiKey in the same session.
- The select does not use SELECT FOR UPDATE and there is no conditional UPDATE ... WHERE used_at IS NULL.
- cloud/models.py defines code_hash as the primary key and used_at as a nullable timestamp; no separate atomic-consumption constraint exists.
- tests/test_mcp_oauth.py covers PKCE and input rules but explicitly says the database-backed token exchange is exercised manually after deploy; there is no concurrent single-use redemption test.

Two concurrent token requests using the same valid code and verifier can both read used_at=NULL before either commits, then each mint a long-lived API key. This violates the documented single-use code contract and can create multiple persistent credentials from one consent grant. Both credentials belong to the same user/client, so this is primarily a credential proliferation and replay-control defect rather than a cross-user privilege escalation.

Fix direction: lock the OAuthCode row with SELECT FOR UPDATE inside an explicit transaction, or atomically update used_at with a WHERE used_at IS NULL and require rowcount == 1 before minting the API key. Add a concurrent redemption test proving exactly one request succeeds and exactly one ApiKey row is created.

### F-22: Account erasure cannot find thumbnail files after a backend restart — high privacy/erasure defect

Evidence:
- app.py around lines 2321-2385: _purge_local_jobs_for_user states that thumbnail session ownership is stored only in thumbnail_sessions memory. It skips the entire output/thumbnails directory while scanning .owner sidecars.
- The same function deletes a thumbnail directory only by iterating the in-memory thumbnail_sessions map.
- app.py cleanup task explicitly skips the thumbnails directory; its own comment says thumbnails are not removed by the normal one-hour cleanup sweep.
- thumbnail.py writes generated images and person_reference.jpg under output/thumbnails/<session_id>/ but no .owner sidecar is written there.
- app.py mounts /thumbnails as public StaticFiles, with no authentication guard (F-11).

After a backend restart, thumbnail_sessions is empty and there is no durable owner marker. Account deletion can no longer associate those generated images and face-reference crops with the deleted user, so it leaves them on disk. Because the directory is publicly served and excluded from normal cleanup, the files may remain accessible indefinitely unless an operator manually removes them. This is separate from the public-mount issue: fixing access control alone does not satisfy deletion/retention.

Fix direction: write an owner sidecar/metadata record for each thumbnail session and make startup recovery/cleanup enumerate it; account erasure must remove the session directory and its source upload using that durable owner record. Apply an explicit retention policy to orphaned thumbnail directories. Add a test that creates a session, simulates a restart by clearing memory, deletes the account, and verifies every thumbnail/frame/reference file is gone and no URL serves it.

### F-23: Stripe webhook event deduplication occurs after side effects — medium, confirmed concurrency/idempotency gap

Evidence:
- cloud/billing.py around lines 362-410: stripe_webhook checks whether StripeEvent exists, calls handle_event, and only afterward inserts the event row with ON CONFLICT DO NOTHING.
- The initial existence check and final insert are separate transactions; concurrent deliveries of the same event can both pass the check and execute handle_event.
- invoice.paid invokes _notify_invoice_paid and _track_invoice_revenue, which send an admin alert and an analytics revenue event without their own event/invoice deduplication in the inspected functions.
- charge.refunded also emits an analytics revenue event; duplicate delivery can mirror the same refund more than once.
- Some state handlers have their own guards (subscription last_event_at, top-up stripe_session_id check), so this does not mean every repeated event double-credits a balance.

Impact: duplicate or concurrent webhook delivery can produce duplicate payment alerts and duplicate revenue/refund analytics even when the subscription/top-up database state is protected. A failure after external side effects but before StripeEvent insertion can also cause the side effects to repeat on Stripe retry.

Fix direction: implement an inbox/event-processing state machine with a unique event claim before side effects, retryable processing state, and idempotency keys for outbound analytics/alerts. Keep state changes and event claim coordinated; do not simply mark processed before work and lose events on crashes. Add concurrent duplicate-delivery and failure-after-side-effect tests.

### Phase 4/6 cloud coverage update
- Authentication, API-key management, magic-link issuance/verification, core quota reservation, account erasure, R2 storage, project restore/history, Stripe checkout/webhook, MCP OAuth, social profiles and autopilot were inspected at the function/route level with selected implementation sections read.
- Billing webhook signatures, top-up duplicate checks, subscription event ordering, row locks in metering/subscription updates, PKCE S256, registered redirect URI checks and user-scoped history were verified as positive controls.
- Still open: detailed billing cancellation/retention paths, email deliverability and unsubscribe security, lifecycle scheduling/idempotency, alert/admin access, marketing/onboarding, proxy ledger accounting, autopilot crash/retry semantics, MCP protocol authorization on every tool, and database migration tests.
- No live Stripe, PostgreSQL, Upload-Post, OAuth-client, R2, or concurrency integration test was run.


### Cloud module coverage update (continued)
Additional full-module/selected-path reads:
- cloud/emails.py: transactional vs commercial email separation, SMTP delivery, unsubscribe footer/header, welcome/first-clip/winback/recovery templates.
- cloud/lifecycle.py: unique (user_id, kind) claim, candidate selection, periodic loop, checkout-expired recovery.
- cloud/alerts.py: Telegram/admin email delivery, job outcome aggregation, proxy health monitoring.
- cloud/proxy_ledger.py: proxy usage persistence, daily paid-byte budget, alert aggregation and probe queue.
- cloud/analytics.py: OpenPanel event/revenue transport and profile attribution.
- cloud/digest.py: daily digest queries, scheduled UTC delivery and retry loop.
- cloud/marketing.py: HMAC unsubscribe URL, GET confirmation and RFC 8058 one-click POST.
- cloud/onboarding.py: authenticated survey endpoint, answer validation and upsert.
- cloud/social_profiles.py: per-user managed Upload-Post profile creation and profile-scoped connection token generation.
- cloud/autopilot.py: per-user source discovery, unique video claims, normal pipeline submission, scheduled publish, completion settlement and user routes.
- cloud/cancellation.py: Stripe cancellation, retention coupon, resume, and user-scoped subscription lookup.

### Additional cloud reliability notes
- Lifecycle email claims are inserted before attempting SMTP. If the send raises, the claim remains and the candidate is excluded from future ticks. This is a deliberate at-most-once guard against duplicate sends across containers, but it also means a transient SMTP outage can permanently suppress a welcome/first-clip/winback message. Consider adding claim states (claimed/sent/failed), lease expiry and retry/backoff rather than treating any claim as proof of delivery.
- Autopilot uses a unique (user_id, video_id) claim to prevent duplicate processing. Its publish fan-out runs in an in-memory background task and updates posted_count after the full loop; a process crash mid-publish can leave the persisted run without per-clip delivery state. Review if this workflow is expected to resume or be reconciled after deployment/restart.
- The social tenant-isolation tests explicitly assert that cloud mode ignores a caller-supplied Upload-Post profile and filters scheduled posts by the server-resolved profile. These are useful regression controls.
- OAuth tests currently exercise helper and input-validation behavior; the code comment says DB-backed register/authorize/token tests are performed manually after deploy. Add local database-backed tests, especially for the single-use race in F-21.


### F-25: Backend video URLs are public bearer-by-job-ID, and media capability helpers are not wired — high privacy/design gap, explicitly documented in source

Evidence:
- restoring_static.py class documentation explicitly states that clips and the untouched source video remain public to anyone who has the job ID; closing this requires capability tokens, a /api/media-token endpoint and dashboard URL integration.
- app.py mounts /videos with RestoringStaticFiles and _media_guard. _media_guard only checks media_auth.is_servable (extension/path allowlist) and the free-plan clean-twin rule; it does not authenticate the requester or verify job ownership.
- media_auth.py implements path signatures and per-user media tokens, but a full app.py/mcp_server.py search finds no calls to sign_media_url, mint_user_token or verification helpers. app.py only calls is_servable.
- No /api/media-token endpoint exists, and dashboard/src/config.js getApiUrl simply prefixes API_BASE_URL; it does not append a user media token.
- /videos URLs are used directly as <video> sources and downloads, so the URL itself is the access capability.

Impact: anyone who obtains a /videos/<job_id>/<filename> URL can fetch that media until the local file expires or the URL is otherwise unavailable. The source video in the same job directory is also within the public media mount if its filename is known and its extension is allowlisted. This is not the same as the renderer's broader output-tree exposure in F-03: the backend mount does at least restrict paths/extensions, but it does not enforce user ownership.

Fix direction: implement the media-auth contract end-to-end: mint short-lived per-user media tokens from the authenticated API; validate tokens or signed path capabilities in the /videos and /thumbnails handlers; append tokens in the dashboard's media URL builder without exposing the 30-day session JWT; provide explicit signed links for webhooks/MCP/R2 consumers; and add tests for anonymous, wrong-user, expired-token, path-capability and source-file requests. Until then, product/privacy docs must describe video URLs as public to anyone who has them, not as private authenticated media.

### Phase 4 frontend checkpoint
- Main dashboard source inventory: 69 files (50 JSX, 7 JS, 4 TSX, 3 TS, 4 CSS and 1 SVG).
- Full-file structural/endpoint inventory performed for App.jsx, AuthContext.jsx, lib/api.js, ResultCard.jsx, ClipEditor.jsx, RemotionPreview.jsx, MediaInput.jsx, HistoryTab.jsx, ThumbnailStudio.jsx, and the remaining component batches listed in the audit notes. High-impact paths read include initial auth/hash handling, process submission/file-vs-URL/multipart branching, advanced watermark/hook/caption fields, clip background/watermark handlers, clip editor EDL/rerender, thumbnail upload/analyze/generate/frames/publish, account deletion, OAuth consent, API key management, billing/cancel, autopilot, and social analytics.
- Most managed dashboard API calls use apiFetch/apiJson, which attaches the bearer token. Static media URLs do not receive the short-lived media token described by media_auth.py because that integration is absent (F-25).
- ResultCard's watermark preview creates URL.createObjectURL(watermarkLogo) directly during JSX rendering without revoking the URL. ThumbnailStudio's DragDropZone similarly creates object URLs inline for image previews; repeated rerenders/file changes can leak blob URLs until the page is closed. This is a low-severity client memory leak; use a memoized URL and revoke it in effect cleanup.
- Further frontend work remains: read all 69 files in full, trace all props and event contracts into App.jsx/backend routes, review all polling/cleanup behavior, validate localStorage secret handling and consent, check accessibility/responsive states, and run ESLint plus production and desktop builds. Phase 4 remains partial.


### F-26: Third-party API keys are persisted in localStorage with reversible XOR obfuscation — medium, confirmed secret-storage weakness

Evidence:
- dashboard/src/App.jsx lines 40-64: encrypt/decrypt use XOR with VITE_ENCRYPTION_KEY or the compiled-in static fallback "OpenShorts-Static-Salt-Change-Me", then Base64. The source comments themselves call it client-side obfuscation, not secure encryption.
- dashboard/src/App.jsx lines 297-315 and 732-750: Upload-Post, ElevenLabs and fal.ai keys are read from and written to localStorage using that reversible transform.
- dashboard/src/App.jsx lines 291 and 732: the Gemini key is stored in plaintext under gemini_key.
- dashboard/src/lib/api.js stores the cloud session bearer token in localStorage as well.

Impact: any same-origin script execution (including a future XSS, compromised dependency or malicious browser extension) can read the cloud session token and all BYOK/provider keys. The XOR key is shipped in the JavaScript bundle and is recoverable by anyone with the application source/bundle, so the stored values are not encrypted at rest. This is not a remote exploit by itself; it is an inaccurate protection boundary and increases the impact of client-side compromise.

Fix direction: remove the "encrypted" claim and do not treat XOR/base64 as protection. For the native Windows app, move secrets into Windows Credential Manager/DPAPI through a narrow Tauri command and keep them out of WebView localStorage. For browser/self-host use, explain that persisted BYOK keys are accessible to same-origin scripts; offer session-only storage or require re-entry. Keep managed cloud credentials server-side. Add tests that ensure secrets are not written to localStorage in the desktop build once secure storage is wired.

### Frontend follow-up observations
- AuthContext scrubs the Google callback token from browser history immediately with replaceState and clears the auth hash in finally; magic-link tokens travel in the fragment and are exchanged through a POST body. This is a positive control.
- apiFetch attaches the cloud bearer token consistently for relative API calls and translates 402 responses into QuotaError. The inspected components generally use this wrapper for protected API routes.
- AccountPage checkout polling clears its interval on paid-plan activation, retry exhaustion or unmount. AutopilotTab polling also uses an effect cleanup.
- ThumbnailStudio publish polling has no overall timeout or abort controller in the inspected path; if the backend publish status remains "uploading" forever or the status endpoint never resolves, the modal can remain busy indefinitely. Add a bounded timeout and explicit cancel/retry state.


### F-27: Unsubscribe GET endpoint performs the state change immediately — medium, confirmed behavior

Evidence:
- cloud/marketing.py: GET /api/marketing/unsubscribe and POST /api/marketing/unsubscribe both call _opt_out.
- _opt_out immediately updates User.marketing_opt_out=True for either method.
- The email body footer uses an ordinary HTTPS link, which is fetched with GET by the user's browser and may also be prefetched/scanned by email security services.
- The POST route is explicitly intended for RFC 8058 one-click unsubscribe, which is the correct place for an automatic state-changing request.

Impact: link scanners and security gateways that prefetch the email's ordinary GET link can unsubscribe a user without the user choosing to do so. It also makes a GET request mutate account state, contrary to safe HTTP semantics.

Fix direction: make GET validate the token and render a confirmation page with a POST form/button, without changing the account. Keep the RFC 8058 POST endpoint as the one-click state-changing path. Add tests proving GET never changes the database and POST does.

### F-28: Cookie banner says analytics waits for consent, but analytics is always enabled and initialized on first load — high privacy/disclosure mismatch

Evidence:
- dashboard/src/components/CookieBanner.jsx says audience measurement "stays off until you say yes" and presents a Reject all button.
- The same component marks analytics as locked/always-on in the details view and describes it as exempt from prior consent.
- dashboard/src/lib/consent.js getConsent() returns analytics:true for both EEA and non-EEA visitors, including before a decision. setConsent() always writes analytics:true; rejectAll() therefore does not disable analytics.
- dashboard/src/main.jsx calls applyConsent() before React mounts and before the banner decision.
- dashboard/src/lib/consent.js applyConsent() unconditionally invokes window.__osAnalyticsInit when it exists.
- dashboard/index.html's initializer loads OpenPanel when the build credentials and hostname match. It is not gated on a user decision.
- dashboard/src/Legal.jsx says nothing non-essential loads until acceptance, which is also inconsistent with the actual first-load behavior.

Impact: on the hosted hostname with analytics credentials present, OpenPanel is initialized before a visitor acts on the banner. Reject all does not turn analytics off. The detail panel does disclose analytics as always-on/exempt, but the prominent copy, Reject all label and legal hub imply the opposite. Whether first-party audience measurement qualifies for an exemption is a legal determination; the implementation and disclosures must not contradict one another.

Fix direction: obtain a jurisdiction-specific legal review of the asserted first-party analytics exemption. If analytics requires consent, default analytics to false, gate applyConsent on allows('analytics'), and make Reject all actually disable it. If the operator is relying on an exemption, remove misleading opt-in/reject wording and clearly explain the always-on measurement and legal basis. Add tests for first visit, EEA/non-EEA behavior, Reject all, Accept all, and tracker initialization count.

### F-29: User-controlled video title is interpolated into transactional email HTML without escaping — medium, confirmed HTML injection surface

Evidence:
- cloud/emails.py send_clips_ready_email interpolates title directly into both the HTML body and the subject.
- The title comes from the processed video/job and can be derived from user-supplied filenames or remote video metadata.
- send_autopilot_clips_email correctly applies html.escape to its corresponding video_title, showing the safe pattern exists elsewhere in the same module.

Impact: a crafted video title can inject HTML into the clips-ready email. Most email clients block script execution, but markup injection can still alter the message, insert deceptive links or images, and make the service's transactional email a phishing surface.

Fix direction: html.escape the title before HTML interpolation, keep the subject as plain text with control characters stripped and a sensible length limit, and test titles containing tags, quotes, ampersands and CR/LF. Apply the same escaping rule to every user-controlled value inserted into HTML email templates.

### Privacy and branding reconciliation
- The hosted frontend, landing page, SEO metadata, static assets and legal hub remain OpenShorts-branded and reference openshorts.app, while the GitHub repository and engineering docs are Clippy-branded. This may be intentional because the repo is a fork or because the hosted service still uses the OpenShorts identity, but it is not a complete product rebrand. Do not bulk-replace legal/operator identity, domains, support addresses or license attribution without an explicit product/legal decision.
- dashboard/src/App.css is generic Vite starter CSS and is not imported by App.jsx or main.jsx in the inspected source. It appears to be an orphaned starter file; retain until the full import/build scan is complete.
- Landing.jsx demo video references are live page content, so those assets are not eligible for deletion merely because they are demo media.


## Phase 8 checkpoint: test inventory and regression coverage

### Test inventory
- Main tree contains 98 test files: 97 Python test/support files under tests/ plus one TypeScript renderer test.
- Latest completed CI result for the current code snapshot (1710a1d4e98c) remains 1,226 passed, 30 skipped, 2 failed. The subsequent commits in this audit sequence change only CLIPPY_REPO_AUDIT.md; no application code has been modified.
- CI workflow runs the Python pytest suite and dashboard production build. It does not run dashboard ESLint, renderer tests, Remotion TypeScript build/typecheck, a real renderer integration test, Docker Compose validation, or a Windows/Tauri build.
- No native Windows Rust tests or Windows integration tests are present in the inspected branch tree.

### Focused tests read and coverage conclusions
- tests/test_generation_controls.py explicitly expects CLIP_MIN_SECONDS=20 and CLIP_MAX_SECONDS=30 to return (20, 30); this is the direct regression test for F-01.
- tests/test_recut.py injects a one-argument watermarker fake; the actual main.apply_watermark signature mismatch proves the failure is not only a fake issue (F-02).
- tests/test_media_path_guard.py tests the extension/path allowlist and explicitly documents that media remains unauthenticated by job ID. It does not test path capabilities or per-user media tokens.
- tests/test_restoring_static.py tests static serving, restoration and job-ID shape. It does not test authentication or ownership for a valid job ID.
- tests/test_thumbnail_studio.py covers pure image/text/frame helpers; it does not exercise thumbnail API ownership, session path containment, upload size limits, static privacy or restart cleanup.
- tests/test_account_local_purge.py covers thumbnail cleanup only while thumbnail_sessions contains the owner in memory. It does not simulate a backend restart before account deletion, leaving the F-22 case uncovered.
- tests/test_ssrf_guard.py covers IP classification and initial DNS resolution, including one bad DNS answer. It does not test DNS changes between validation and connection, redirect hops in urllib/yt-dlp, or transport-level IP pinning.
- tests/test_mcp_oauth.py tests PKCE/input helpers but lacks database-backed concurrent code redemption; its own comments say the DB exchange is checked manually after deploy (F-21).
- tests/test_social_tenant_isolation.py provides useful cloud profile isolation and scheduled-post filtering coverage.
- tests/test_agent_uploads.py covers upload slot creation, PUT, process handoff and expiry, but does not test a leaked upload capability being overwritten by a different user.
- tests/test_email_policy.py covers commercial email/unsubscribe headers and opt-out filtering, but there is no dedicated test file for marketing GET vs POST semantics or HTML escaping of user-controlled email content (F-27/F-29).
- tests/test_billing_states.py, tests/test_invoice_subscription_status.py, tests/test_cancellation.py and tests/test_metering_free_plan.py cover important billing state transitions, but do not exercise duplicate concurrent Stripe webhook delivery or account deletion racing with a new reservation (F-14/F-23).
- render-service/src/composition-metadata.test.ts is the only renderer test file and is not run in CI. It does not cover server authorization, path traversal, SSRF, resource bounds or process restart.

### Test/CI remediation plan
1. Restore green backend CI by fixing F-01 and the real F-02 call contract, then rerun the complete suite.
2. Add the missing security regressions first: media privacy, thumbnail restart erasure, thumbnail session path traversal, SaaS retry tenant ownership, renderer path/url/limits, forwarded-header spoofing, and account-deletion concurrency.
3. Add database-backed OAuth and Stripe duplicate-delivery concurrency tests.
4. Add consent/marketing endpoint tests for first-load analytics behavior, Reject all, GET unsubscribe and POST one-click unsubscribe.
5. Add CI jobs for dashboard lint, renderer tests, Remotion typecheck/build, Compose config validation and a Windows Tauri compile/package smoke test.
6. Add media fixture integration tests for background, watermark, recut, subtitles, FFmpeg fallback and output metadata; current pipeline tests largely use injected fakes and do not prove real encoded outputs.

Phase 8 remains partial. The full test suite has not been rerun in this audit session, and no new application code has been committed.


### F-30: Post-generation watermark edits are not archived to durable cloud storage — high, confirmed persistence defect

Evidence:
- app.py /api/clip/background updates metadata and in-memory job result, then calls _archive_clip_edit_bg(job_id, clip_index, served_name).
- The immediately following /api/clip/watermark route performs the same local output/metadata/in-memory update but returns without calling _archive_clip_edit_bg.
- The shared _archive_clip_edit_bg helper invokes cloud.videos.archive_clip_edit for managed jobs and keeps the durable project/history copy in sync.
- dashboard/src/components/ResultCard.jsx clears durableSrc after a successful watermark and comments that the new archive is pending; however, the backend route does not schedule that archive.

Impact: in cloud mode, the watermarked MP4 exists only in the local working directory while the R2 project/history archive remains on the previous unwatermarked file. Once local job files are swept or the project is restored after a deploy, the user can receive the old unwatermarked clip, despite the dashboard having shown the watermark operation as successful. This is a direct persistence bug in the new post-generation watermark feature.

Fix direction: call _archive_clip_edit_bg(job_id, clip_index, served_name) after the metadata and in-memory state are successfully updated, matching the background/reframe/hook/subtitle/edit routes. Add a cloud test that mocks archive_clip_edit and asserts it receives the new watermarked filename; add a restore-after-local-cleanup test proving the watermarked bytes and metadata are restored.


### F-31: Watermark rendering runs synchronous FFmpeg/ffprobe inside an async API handler — high availability defect

Evidence:
- app.py /api/clip/watermark is declared async.
- It calls subprocess.run directly for ffprobe (up to 15 seconds) and again for FFmpeg (up to 600 seconds), without asyncio.to_thread, run_in_executor or an async subprocess API.
- The same file's /api/clip/background route correctly runs the FFmpeg subprocess in run_in_executor with a 600-second timeout.
- The backend Dockerfile starts a single Uvicorn worker; there is no multi-worker isolation to keep other requests responsive while this coroutine blocks.

Impact: while a watermark is being rendered, the only Uvicorn event loop is blocked. Health checks, status polling, authentication, uploads and unrelated users' API requests cannot be serviced until the synchronous FFmpeg process returns. A large or slow clip can make the entire backend appear hung for up to ten minutes. The endpoint also blocks during both ffprobe calls.

Fix direction: move all watermark ffprobe/FFmpeg work into asyncio.to_thread/run_in_executor or use asyncio.create_subprocess_exec with asynchronous waiting and cancellation. Apply the same pattern to every subprocess call reachable from async routes. Add an async responsiveness test that runs a deliberately slow fake renderer while /health/ready and an unrelated request continue to return promptly.


## Branch audit: codex/reference-templates (1 commit ahead of main)

This branch has one unique commit and is 46 commits behind the current main snapshot. Its only substantive feature addition is a local reference-template library; the remaining diff deletes historical patch files that have already been removed from main. The branch is not merged.

### Files inspected
- reference_templates.py (full)
- tests/test_reference_templates.py (full)
- dashboard/src/components/ReferenceTemplateLibrary.jsx (full)
- reference_templates/ref_10ed2bb978ca493f8fc2c9df44d65baf/manifest.json
- app.py route/mount additions and App.jsx nav integration
- layout_picker.py changed lines
- .dockerignore, Dockerfile and docker-compose.yml
- poster.jpg metadata; the referenced reference.mp4 file is absent from the branch tree.

### F-32: Reference template upload reads the same Fetch response body twice — medium functional bug, confirmed

Evidence:
- dashboard/src/components/ReferenceTemplateLibrary.jsx around lines 47-53 calls response.json() into payload, then on success calls response.json() a second time to obtain created.
- A Fetch Response body is a one-shot stream; the second read rejects with "body stream already read".
- The backend upload can therefore succeed and persist the template, but the UI's success path throws before adding it to local state and reports an error. The user may retry and create duplicate reference templates.

Fix direction: use the already-parsed payload as the created manifest after the response.ok check. Add a component/API integration test that uploads once and verifies the returned template is displayed without a second request.

### F-33: Reference-template library has no delete or total-storage limit — medium retention/resource gap in this branch

Evidence:
- reference_templates.create stores the uploaded source video permanently under reference_templates/<id>/reference.mp4.
- The upload route permits up to MAX_FILE_SIZE_MB (2,048 MB) per video and streams it safely, but there is no library-wide byte cap, item-count cap, retention sweep or delete endpoint.
- ReferenceTemplateLibrary exposes upload and refresh/list only; there is no delete action.
- OUTPUT_MAX_GB and UPLOADS_MAX_GB do not cover the separate REFERENCE_TEMPLATES_DIR.
- The sample manifest refers to reference.mp4, but the branch tree contains only manifest.json and poster.jpg for that template ID. The sample's reference_url therefore points to a missing file.

Impact: repeated uploads can fill the host disk outside the existing output/upload caps, and users cannot remove a stored reference through the UI/API. The sample template returns a broken reference-video URL. This branch is self-host-only by design (_reference_templates_local_only rejects managed/cloud mode), so it is an instance-level storage concern, not a cloud cross-tenant issue.

Fix direction: add delete with safe ID validation and directory containment; track total library bytes and enforce a configurable quota; document retention; add a consistency check that removes or reports manifests whose reference file is missing. Either include the sample reference.mp4 or remove the stale sample reference entry.

### Reference-template feature scope
- app.py explicitly disables the API in managed/cloud mode until account-scoped cloud storage exists. This is a positive tenant-boundary guard.
- Upload streaming enforces a per-file 2 GB cap, uses a random staging filename, and moves the staged file into a generated ref_<uuid> directory.
- reference_templates.manifest_path validates strict ref_<32 lowercase hex> IDs before reading/writing manifests.
- The new feature currently stores/analyzes a reference and exposes its poster/video URLs; it does not yet apply the stored overrides to the main clipping pipeline or connect them to layout_picker.pick_and_apply. Treat it as a local library/prototype, not a completed "apply template to generated clip" workflow.
- tests/test_reference_templates.py covers create/persist, ID traversal rejection and pacing detection, but not API upload failure cleanup, storage quota, delete, missing reference media, or frontend response handling.


### F-35: Metered whole-source duration cap fails open when OpenCV cannot read duration — medium quota-enforcement gap

Evidence:
- app.py sets SOURCE_CAP_MINUTES for URL jobs from the reserved/probed minutes.
- main.py around lines 750-790: cap_source_duration reads duration only through cv2.VideoCapture. When safety=True and OpenCV returns no usable duration, it returns the original input without applying the FFmpeg -t cut.
- main.py around lines 2433-2445: the whole-source metering path calls cap_source_duration(..., safety=True) before the rest of the pipeline reads the file.
- The earlier metering probe uses ffprobe, so there are media/container combinations where the server can determine a duration for reservation but OpenCV cannot determine the same duration for the safety cut.
- The YouTube downloader's ranged-download optimization is only applied to unknown or very long sources; it does not guarantee that every download is already limited to the exact reserved duration.

Impact: for a metered URL job whose duration is known to the reservation probe but unreadable to OpenCV, the safety cap silently skips the cut and the pipeline can process the entire downloaded source rather than the reserved minutes. This can exceed the user's plan allowance and increase compute/bandwidth cost. The partial-plan MAX_SOURCE_MINUTES path does not have the same fail-open because it still attempts the FFmpeg -t cut when duration is unknown.

Fix direction: use the same ffprobe-based duration probe as metering, or enforce the reserved -t cut regardless of whether OpenCV can report duration. Treat an unreadable duration as a reason to fail safely or perform the bounded cut, not as permission to process the entire source. Add tests where ffprobe returns a valid duration but cv2 reports zero, and assert the resulting media is capped.
