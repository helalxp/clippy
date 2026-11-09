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

### F-03 — Renderer bypasses backend media authorization — high, confirmed exposure surface

Evidence:
- `render-service/src/server.ts:50`: `express.static(OUTPUT_DIR)` exposes the shared output tree under `/output`.
- `render-service/src/server.ts:58`: `POST /render` has no authentication middleware.
- `render-service/src/server.ts:124`: render status lookup has no authentication or ownership check.
- `docker-compose.yml:32-33`: host port `13100` is published to container port `3100` without a loopback-only bind.
- `render-service/src/server.ts`: server calls `app.listen(PORT)` without a host argument on main.

Impact: direct renderer access can expose output files outside FastAPI's `media_auth.py` checks and can submit resource-intensive render requests without a user identity or ownership boundary. Docker's port publication is normally reachable on host interfaces, subject to host firewall/network policy.

Required fix direction: make renderer an internal-only service in cloud/container deployments, or add strong service authentication and per-job ownership authorization. Bind local desktop renderer to loopback. Do not serve the whole output directory publicly; use scoped, authorized media delivery. Add tests proving anonymous clients cannot read private outputs or submit/poll another user's renders.

### F-04 — SSRF validation is vulnerable to DNS time-of-check/time-of-use changes — medium, needs exploit verification

Evidence:
- `security_utils.py:89-105`
- `main.py:933` also sets yt-dlp's `nocheckcertificate=True`.

The guard resolves a hostname, checks the returned addresses, then returns the original URL. The downstream HTTP client/yt-dlp performs its own resolution and follows redirects. The validation result is therefore not cryptographically or transport-bound to the address that is ultimately contacted. DNS rebinding and redirect behavior need explicit tests. Disabling certificate verification further weakens transport protection.

Fix direction: enforce safe destination validation at every redirect and connection, or use a fetch layer that pins the validated address while preserving the correct TLS hostname/certificate verification. Review every caller, not just the initial URL parser. Do not mark this finding fixed based only on another preflight DNS lookup.

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
