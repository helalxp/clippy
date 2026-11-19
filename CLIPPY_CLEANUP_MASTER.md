# Clippy v1 Master Cleanup Plan

> **Purpose:** This is the single working ledger for the Clippy v1 extraction, repository cleanup, architecture hardening, and UI preparation. It must be updated at the end of every phase before that phase is called complete.
>
> **Repository:** https://github.com/helalxp/clippy  
> **Default branch:** `main`  
> **Cleanup branch:** `chore/master-cleanup-phase-0`  
> **Baseline commit:** `61edcd5027e3f4e05c8019896e25af0e1cfa19f3`  
> **Baseline date:** 2026-11-19  
> **Application version at baseline:** `0.3.1`  
> **Current status:** Phase 0 COMPLETE. Local checkout confirmed on `chore/master-cleanup-phase-0`; Phase 1 is IN PROGRESS.
>
> **Change policy:** This document is the cleanup process record, not blanket permission to delete or rewrite code. Each phase must be completed and verified before the next phase starts. Source, tests, configuration, Git history, and current CI outrank historical audit claims.

---

## 1. How this document must be maintained

This file is the durable handover for the entire cleanup.

At the beginning of each phase:
- Confirm the cleanup branch and working tree state.
- Read this file and the relevant architecture, runtime, security, and feature documents.
- Confirm the phase scope and dependencies.
- Record the starting commit and the exact checks planned.

During each phase:
- Keep this file's task status current when a decision materially changes.
- Record discoveries that alter scope, dependencies, risk, or order of work.
- Do not mark a task complete because a file was edited or a UI control exists.
- Keep deferred-feature handoff documents synchronized with implementation discoveries.

At the end of each phase, before advancing:
1. Update the phase checklist.
2. Record changed files and commits.
3. Record tests/checks run, exact outcomes, and environment.
4. Record any tests not run and why.
5. Record regressions, unresolved risks, and follow-up work.
6. Update the overall milestone and next-phase entry criteria.
7. Verify the document is committed on the cleanup branch.

A phase is **complete** only when its exit criteria are met and the evidence is recorded here. If a required check is blocked, mark the phase **blocked** or **partially complete**, not complete.

### Validation-efficiency policy

The product owner requests that CI and Windows validation be kept to the minimum necessary without weakening release safety.

- Prefer focused tests, static checks, and narrow builds for the specific files/contracts changed.
- Do not run full CI for documentation-only changes or unrelated low-risk edits.
- Run the full Linux CI suite at meaningful integration/phase gates or when a change spans enough surfaces that focused tests are not sufficient.
- Run Windows desktop validation when a change affects Tauri/Rust, PowerShell setup, managed runtimes, installer/updater behavior, Windows path/process behavior, or a phase/release gate that depends on the packaged desktop.
- Do not repeatedly run the same Windows workflow for unchanged code.
- When Windows validation is needed, start it and provide the Actions URL to the product owner. Do not continuously poll or wait for completion; the owner will report the result. Record the run and its result in this file when supplied.
- A running workflow is not a passed workflow. Do not advance past a gate that requires its result until the owner reports it.
- Do not reduce or skip tests that directly cover changed behavior, data safety, security boundaries, or release contracts merely to save CI time.

### Status vocabulary

- `NOT STARTED`: no work has begun.
- `IN PROGRESS`: work is actively underway.
- `BLOCKED`: work cannot proceed without a dependency or decision.
- `PARTIALLY COMPLETE`: some deliverables are done, but at least one exit criterion remains.
- `COMPLETE`: all phase exit criteria are met and evidence is recorded.
- `DEFERRED`: deliberately retained for a later phase or roadmap item.
- `REMOVED`: deliberately removed after dependency, test, and data-safety checks.

---

## 2. Product decisions: Clippy v1 scope

These decisions were explicitly supplied by the product owner on 2026-11-19. They are the scope authority for this cleanup unless the owner changes them.

| Area | Decision | v1 treatment |
|---|---|---|
| Core video clipping and editing | Keep | In scope |
| Local Library and persistent projects | Keep | In scope |
| Reference templates | Keep | In scope |
| Social publishing and scheduling | Later | Deferred; UI label and handoff documentation required |
| Thumbnail Studio | Defer | Deferred; UI label and handoff documentation required |
| AI UGC / SaaS Shorts | Defer | Deferred; UI label and handoff documentation required |
| MCP / AI-agent integration | Future | Deferred/future; label as Under investigation wherever surfaced and document restart path |
| Product analytics / telemetry | None | No analytics or telemetry in v1 |
| Docker | Remove | Remove Docker development/self-hosting infrastructure and its dependencies from this repository |
| Clippy website | Separate | Build as a separate project/repository; no website implementation is part of this desktop cleanup |

### Deferred-feature UI rule

Every deferred/future feature that remains visible in the product UI must be explicitly labeled **Under investigation**. It must not look available or imply that an incomplete flow works. The UI should explain briefly that the feature is not part of the current v1 workflow and direct users to an appropriate roadmap/help surface where practical.

Every deferred feature must have a complete technical handoff document under:

```text
docs/roadmap/deferred/
  social-publishing.md
  thumbnail-studio.md
  ai-ugc.md
  mcp-ai-agents.md
```

Each handoff must cover:
- Product intent and intended user workflow.
- Current implementation status and what is genuinely working.
- Relevant source files, components, routes, tests, assets, and configuration.
- Data model, persistence, and API contracts.
- External services, provider accounts, credentials, and dependencies.
- What is retained, isolated, or removed during v1 extraction.
- Known defects, incomplete work, and technical debt.
- Licensing, security, privacy, and data-retention concerns.
- Architectural prerequisites and a restart sequence.
- Acceptance criteria and tests required for completion.
- Decisions still awaiting product-owner input.

Deferred does **not** mean blindly deleting the implementation. Preserve reusable work where it can be safely isolated from the v1 execution path. Remove inherited cloud dependencies only after the local/future boundary is explicit.

### Explicit v1 product boundary

Clippy v1 is a standalone, Windows-first desktop application. The intended customer workflow is local video ingestion, AI-assisted analysis and clip selection, editing/refinement, rendering, and local project/library management. The application manages its own backend and renderer and provisions its required runtime. User data, models, settings, and generated work must survive application updates.

The new website is independent of the desktop repository's runtime and UI. Its brand, claims, legal copy, downloads, and support content must be authored against the actual product.

---

## 3. Target architecture and preservation invariants

The cleanup should converge on these responsibility boundaries:

1. **Tauri desktop shell:** application window, native integration, runtime bootstrap, process supervision, secure local service startup, update/install lifecycle.
2. **React frontend:** navigation, user workflows, editing UI, local settings, Library, reference templates, and clear deferred-feature states.
3. **Local FastAPI application:** local API, job coordination, upload/file validation, settings, Library, media delivery, and editing orchestration.
4. **Processing engine:** transcription, scene analysis, moment selection, clip extraction, reframing/layout, captions, hooks, and supporting AI/local-model work.
5. **Rendering engine:** Remotion, FFmpeg integration, composition, preview/final render, and output management.
6. **Persistent local data:** projects, generated assets, uploads, settings, model weights/caches, logs, and credentials.
7. **Managed Windows runtime:** pinned Python/Node/FFmpeg/browser assets, CPU/CUDA selection, integrity checks, and repair/update behavior.

### Non-negotiable invariants

- Preserve the Tauri process supervisor and Windows Job Object behavior.
- Preserve loopback-only service binding and the per-launch Tauri API token.
- Preserve safe upload handling, path validation, media-serving controls, process cancellation, and useful errors.
- Preserve CPU operation and the supported NVIDIA/CUDA runtime path.
- Preserve the managed runtime contract, first-run setup, integrity checks, repair, upgrade, and rollback behavior.
- Preserve Remotion/FFmpeg rendering and the existing real editing behavior.
- Preserve local Library data and reference templates across restarts and upgrades.
- Preserve custom user watermarks. Do not confuse them with any inherited hosted/free-plan delivery watermark.
- Preserve legally required root MIT, upstream copyright, and third-party notices.
- Do not migrate cloud auth/session tokens into local preferences.
- Do not store provider secrets in frontend localStorage. Use a narrow native secure-storage boundary.
- Do not create a frontend-only mock of a feature that is expected to work.
- Do not remove tests to make a suite pass.
- Do not treat line-count reduction as architecture improvement.

---

## 4. Execution phases and exit gates

The sequence is intentional. Do not reorder destructive work ahead of the dependency and contract work that makes it safe.

### Phase 0 — Current-state baseline and repository map

**Status: COMPLETE.**

Objectives:
- Inspect the actual current default-branch commit, version, tree, recent history, and release/CI state.
- Read the existing project instructions, extraction audit, and architecture/runtime contracts.
- Inventory top-level subsystems, major entry points, frontend feature surfaces, tests, workflows, and build manifests.
- Identify documentation drift and findings that must be reverified before acting.
- Record the exact current baseline so later phases are measured against it.

Deliverables:
- Current repository and release baseline recorded below.
- High-level architecture and dependency map.
- Initial preservation list, risks, documentation conflicts, and unresolved inspection items.
- This master cleanup document committed on the cleanup branch.

Exit criteria:
- Current remote baseline identified by immutable commit SHA.
- Product scope decisions recorded.
- Major application boundaries and protected contracts identified.
- Current CI/Windows/release evidence recorded.
- Remaining limitations explicitly listed.

### Phase 1 — Architecture contract, licensing, provenance, and retirement preflight

**Status: PARTIALLY COMPLETE — architecture and retirement preflight are documented; owner licensing/service decisions and artifact-level compliance verification remain open.**

Objectives:
- Define and document the stable contracts between Tauri, frontend, FastAPI, processing, renderer, and persistent data.
- Reconcile the documentation hierarchy so there is one canonical project engineering guide and one cleanup ledger.
- Verify the required commercial/distribution rights for all code, dependencies, binaries, fonts, models, and media.
- Determine whether any externally operated cloud services, user accounts, subscriptions, stored user data, OAuth grants, buckets, or retention obligations still exist. Repository deletion must not be treated as service/customer-data retirement.
- Define user-data backup, migration, and rollback requirements before changing storage or settings.
- Distinguish repository-level licence identification from artifact-level SBOM/source/hash verification; a dependency name alone is not release clearance.

Required work:
- Review root `LICENSE` and `NOTICE`; preserve inherited notices.
- Resolve Ultralytics YOLO commercial distribution: obtain an appropriate licence or select and validate a compatible replacement. Do not remove the broader reframing capability.
- Obtain confirmation of the Remotion licence category for an embedded video-creation product.
- Generate an SBOM/licence inventory for Python, npm, Rust, FFmpeg, browser runtime, fonts, models, and assets.
- Verify FFmpeg build configuration and applicable redistribution obligations.
- Define the local credential-storage design using Windows Credential Manager/DPAPI through a narrow Tauri interface.
- Document local API and renderer token requirements.
- Establish a storage/data migration and rollback plan.
- Commit the current local runtime/service/data contract, preliminary licence/provenance inventory, and hosted-service retirement preflight.
- Record the product owner's licensing choices and hosted-service status before starting destructive extraction.
- Inventory the actual generated CPU/CUDA runtime artifacts, Chrome headless-shell archive, FFmpeg build, and all corresponding notices/source obligations before release clearance.

Exit gate:
- No unidentified legal/provenance blocker is silently assumed acceptable.
- Data-retention and external-account obligations are known and separately assigned.
- Core API/runtime/data contracts are written and reviewed.
- No implementation deletion begins until the required dependency boundary is known.
- The owner has decided how the Ultralytics AGPL dependency will be licensed or replaced.
- Remotion eligibility for the entity operating Clippy is confirmed.
- The current live-service/data status is known and any shutdown/export/retention process is assigned.
- Artifact-level licence/source/hash checks are complete for every component distributed in the installer.

### Phase 2 — Local backend extraction and contract tests

**Status: NOT STARTED**

Objectives:
- Convert the current mixed backend into an explicitly local desktop API.
- Separate hosted account/billing/metering behavior from local process/job/library/edit/render behavior.
- Keep each backend responsibility testable and observable.

Required work:
- Inventory every cloud import, router, route, middleware, helper, configuration flag, and conditional path.
- Trace every `BILLING_ENABLED` branch and all cloud service call sites to determine the retained local behavior.
- Separate local routes/services before removing shared code.
- Remove cloud user resolution, cloud ownership/entitlement/quota assumptions from the local desktop execution path.
- Preserve local upload/path safety, job admission/lifecycle, cancellation, process supervision, media serving, rendering, Library, reference-template, and updater APIs.
- Replace hosted authentication UI/API semantics with a local application/settings/provider model.
- Keep the per-launch desktop token and loopback-only network boundary.
- Add regression tests for all retained local API contracts.

Exit gate:
- The packaged desktop workflow works without importing or invoking the inherited cloud subsystem.
- All retained API contracts have focused tests.
- No required local workflow depends on hosted authentication, billing, managed keys, or cloud storage.

### Phase 3 — Remove hosted SaaS and cloud-only infrastructure

**Status: NOT STARTED**

Objectives:
- Remove the inherited hosted SaaS product only after Phase 2 has disconnected it safely.

Candidate removals, subject to Phase 2 reference proof:
- The inherited `cloud/` package and its separate commercial licence code.
- Billing, Stripe, paid plans, hosted login/OAuth, account lifecycle emails, quotas, managed keys, metering, cloud analytics, cloud social profiles, hosted Autopilot, R2 archive/restore, and cloud-only routers.
- Cloud-only requirements, Alembic/Postgres migrations, cloud deployment files, and cloud configuration.
- SaaS-only dashboard screens and browser auth/session flows.
- Cloud-only environment variables and test fixtures.

Safety requirements:
- Do not delete external customer data, buckets, databases, subscriptions, OAuth grants, or accounts during Git cleanup.
- Preserve any legally required operational records and data-export/deletion obligations.
- Keep local Library and custom user editing features.
- Do not remove an entire shared module such as `s3_uploader.py` until its retained imports/callers are separated.

Exit gate:
- No runtime import, endpoint, frontend call, test, or shipped dependency relies on the removed hosted SaaS subsystem.
- Local generation, editing, render, Library, reference templates, and startup still work.
- External service retirement is handled separately by the service/account owner.

### Phase 4 — Remove Docker and Docker-dependent development paths

**Status: NOT STARTED**

Objectives:
- Remove Docker from the repository and supported developer workflow, per the explicit product decision.

Candidate removals, after source/workflow reference checks:
- Root and dashboard Dockerfiles.
- Renderer Dockerfile.
- All Compose files, including cloud and E2E overrides.
- `.dockerignore`, Docker-specific build assumptions, container-only scripts, and Docker-only service configuration.
- Docker instructions and port tables from README/developer documentation.
- Container-only environment variables, hostnames, volumes, and mount-path assumptions.

Required work:
- Confirm native Windows development, build, test, and packaging instructions are complete.
- Replace any CI/test task that still invokes Docker with an appropriate native or hosted runner path, or retire it deliberately.
- Make native service URLs, paths, startup, and shutdown explicit.
- Remove only Docker-specific code; do not remove processing or rendering capabilities merely because they were formerly run in a container.

Exit gate:
- No supported project workflow requires Docker, Compose, or WSL2.
- CI and Windows validation do not depend on Docker.
- Developer instructions describe the native workflow accurately.

### Phase 5 — Engineering untangling and architectural cleanup

**Status: NOT STARTED**

Objectives:
- Reduce accidental coupling and make responsibilities explicit without turning the cleanup into a broad rewrite.

Priority review areas:
- `app.py`: cohesive local route/service boundaries.
- `main.py`: explicit pipeline stages and stable stage contracts.
- `dashboard/src/App.jsx`: shell, workflow orchestration, local state, and feature components.
- `render-service/src/server.ts`: server setup, auth, routes, job lifecycle, media delivery.
- Frontend/backend layout decision authority.
- FFmpeg orchestration shared by captions/hooks/background/watermark paths.
- Transcript checkpoint duplication and source-of-truth behavior.
- Config/environment variable ownership and path resolution.
- Credential persistence and migration.
- Child-process environment secret isolation.
- Renderer job lifecycle and restart/recovery expectations.

Rules:
- Trace callers, imports, request/response shapes, persistence, and tests before extracting a module.
- Introduce abstractions only when they clarify a real boundary.
- Do not assume Redis is required; first specify render-job durability and recovery behavior.
- Do not assume a helper is dead merely because it is called in only one path.
- Do not use file age, one-time commit history, or names alone as dead-code proof.

Exit gate:
- Agreed boundaries are implemented and documented.
- Focused tests cover changed contracts.
- No observable core workflow regressions.
- The refactor demonstrably reduces coupling or risk.

### Phase 6 — Deferred-feature isolation, UI states, and handoff documentation

**Status: NOT STARTED**

Features:
- Social publishing/scheduling.
- Thumbnail Studio.
- AI UGC / SaaS Shorts.
- MCP / AI-agent integration.

Required work:
- Write the four handoff documents while current implementation context is still available.
- Identify source, route, data, dependency, credential, test, and external-service boundaries for each feature.
- Separate v1-safe reusable foundations from feature-specific paths.
- Keep incomplete feature flows out of the active v1 workflow.
- Add the exact UI state label **Under investigation** wherever a deferred feature remains visible.
- Add a central deferred-feature index with links to the four handoff documents.
- Make no claim that deferred features are usable in v1.

Exit gate:
- Every deferred/future feature has a complete restart document.
- All visible deferred entries are labeled consistently.
- Deferred implementation does not leave broken imports, dead UI navigation, or cloud-only runtime dependencies in v1.
- The v1 core works independently of deferred features.

### Phase 7 — Product identity, repository, docs, and configuration cleanup

**Status: NOT STARTED**

Objectives:
- Remove inherited OpenShorts product/website residue from the shipped desktop app and repository where safe.
- Make Clippy naming and documentation consistent.
- Keep the new Clippy website as a separate project.

Required work:
- Review all old brand/domain/package/asset/metadata references.
- Replace product-facing OpenShorts copy, icons, title, canonical/SEO/OG/Twitter metadata, host allowlists, old support links, and website-only routes.
- Remove the embedded legacy landing/legal/SEO build path from the desktop app.
- Reconcile README, `AGENTS.md`, `CLAUDE.md`, `CLIPPY_MASTER.md`, `CLIPPY_REPO_AUDIT.md`, and subsystem docs; preserve historical records only where they remain useful and are clearly marked historical.
- Rename package/internal metadata where meaningful and regenerate lockfiles using the package manager.
- Remove obsolete CLI, hosted marketplace, n8n, and OpenShorts agent-distribution metadata unless a separately approved local use is retained.
- Centralize retained preferences under a versioned Clippy namespace and migrate safe user preferences.
- Remove analytics/telemetry code and configuration from the v1 product. Do not add an opt-in analytics mode.
- Rewrite `.env.example` to include only supported settings.
- Keep root MIT and third-party notices accurate.
- Do not create the separate website in this repository as part of desktop cleanup.

Exit gate:
- No stale product claims or broken links in the desktop product docs/build metadata.
- User preferences/data migrations are tested.
- Package/lockfile metadata agrees.
- Required notices remain accurate.

### Phase 8 — Apply the approved Clippy UI

**Status: NOT STARTED**

Objectives:
- Apply the new UI only after the backend/runtime contracts are stable.

Implementation order:
1. Design tokens, typography, color, spacing, icons, and reusable primitives.
2. Desktop shell, navigation, responsive layouts, and page lifecycle.
3. Main input and clip-generation workflow.
4. Job progress, results, previews, and downloads.
5. Clip editing: reframing, captions, hooks, backgrounds, custom watermark, and render options.
6. Local Library, projects, and reference templates.
7. Settings, provider configuration, model/runtime controls, diagnostics, updater.
8. Deferred-feature entries with the exact Under investigation state.

Rules:
- Connect every v1 control to the real API/backend behavior.
- Preserve existing capabilities unless a separately approved scope decision removes them.
- Do not use mocked controls or placeholders for v1 functionality.
- Do not include analytics/telemetry.
- Test desktop window sizing, keyboard/accessibility basics, navigation, error/loading/empty states, and data persistence.

Exit gate:
- UI is integrated with real backend contracts.
- All v1 features work end to end.
- Deferred entries are visibly non-functional/investigative and have documentation.
- The UI does not regress desktop startup, runtime, or Library behavior.

### Phase 9 — Regression, security, migration, and Windows validation

**Status: NOT STARTED**

Required validation:
- Python unit/integration/security tests.
- Dashboard lint/build and relevant frontend tests.
- Renderer typecheck/build/unit/integration tests.
- Rust checks and tests.
- PowerShell/Pester runtime and payload contract tests.
- Backend/renderer startup, health, token, and process-shutdown behavior.
- Full video-to-clips workflow.
- Transcription, model selection, AI providers, scene analysis, reframing, captions, hooks.
- Background and custom watermark outputs verified in the actual rendered files.
- Remotion preview/final rendering and FFmpeg outputs.
- Local Library save/reopen/rename/delete/export and persistence.
- Reference template create/list/use/persist flows.
- CPU path and supported NVIDIA/CUDA path on real hardware.
- Clean Windows installation, first-run setup, repair, update, rollback, and uninstall.
- Existing-user data/settings/model preservation across upgrade.
- Secret storage, local API authorization, loopback binding, path traversal, upload limits, and child-process environment controls.

Do not infer GPU behavior from a configuration flag or build result. Verify real runtime logs and output on the target machine.

Exit gate:
- Critical checks pass on the exact release candidate commit.
- Windows installer and upgrade behavior are validated.
- Remaining failures/limitations are explicit and accepted.
- No critical data-loss, security, or legal blocker remains.

### Phase 10 — Release readiness and handover

**Status: NOT STARTED**

Required work:
- Align canonical version and all synchronized manifests.
- Validate the release workflow on the exact accepted commit/tag.
- Verify Tauri updater signature and installer integrity.
- Verify runtime manifests, part hashes, archive reconstruction, and expected release assets.
- Package third-party notices and SBOM.
- Verify published installer, updater manifest, and versioned runtime assets.
- Update install/build/troubleshooting/recovery documentation.
- Document rollback, data preservation, support diagnostics, uninstall behavior, and known limitations.
- Reconcile separate website download/release links against the actual published release.

Exit gate:
- The shipped artifact is the artifact that passed validation.
- Installer/updater/runtime assets match the canonical version and signatures.
- Documentation matches the release.
- Final handover records what shipped and all accepted limitations.

---

## 5. Milestones

| Milestone | Phases | Definition |
|---|---|---|
| A — Extraction foundation | 0–1 | Current baseline, architecture contracts, product scope, legal/provenance and retirement preflight |
| B — Standalone application | 2–4 | Local backend, hosted SaaS removed, Docker removed |
| C — Stable architecture | 5–7 | Refactoring complete, deferred features documented/isolated, identity/config/docs cleaned |
| D — New Clippy interface | 8 | Approved UI connected to the stable local application |
| E — Production readiness | 9–10 | Full regression, Windows validation, release and handover |

---

## 6. Phase 0 — recorded baseline (2026-11-19)

### 6.1 Git and release baseline

| Item | Verified value |
|---|---|
| Repository | `helalxp/clippy` |
| Visibility | Public |
| Default branch | `main` |
| Main baseline commit | `61edcd5027e3f4e05c8019896e25af0e1cfa19f3` |
| Baseline commit | Merge PR #26, stable v0.3.1 updater rollout |
| Merge date | 2026-11-19 05:15:04 UTC |
| Application version | `0.3.1` from root `VERSION` |
| Latest release | `v0.3.1`, published 2026-11-19 |
| Cleanup branch | `chore/master-cleanup-phase-0`, created from the baseline `main` commit |

The stable release workflow completed successfully on the baseline commit. The release includes the Windows NSIS installer and signature/checksum, CPU runtime package, CUDA manifest and ordered parts, and `latest.json`.

Verified workflow evidence on the exact baseline:
- General CI: [run 44463861746](https://github.com/helalxp/clippy/actions/runs/44463861746) — success.
- Windows desktop validation: [run 44463861590](https://github.com/helalxp/clippy/actions/runs/44463861590) — success.
- Windows release: [run 44463950724](https://github.com/helalxp/clippy/actions/runs/44463950724) — success; published `v0.3.1`.

These are GitHub Actions results, not tests independently executed during this inspection.

### 6.2 Repository inventory

The recursive Git tree at the baseline contains **556 entries: 494 file blobs and 62 directory tree entries**. The root contains 75 tracked file blobs.

High-level tracked inventory:
- 51 root-level Python modules.
- 74 files under `dashboard/src/`.
- 42 files under `desktop/`.
- 24 files under `docs/`.
- 103 files under `tests/`.
- 4 GitHub workflow files: CI, CLI publishing, Windows release, and Windows desktop validation.

Major top-level areas include:
- `cloud/`, `alembic/`, and cloud billing/deployment files.
- `dashboard/` with React/Vite UI, legacy website/SEO, account, social, thumbnail, UGC, MCP, and local editing features.
- `desktop/` with Tauri/Rust shell, PowerShell setup/build, runtime contracts, updater and tests.
- `render-service/` and `remotion/`.
- `reference_templates/` plus root reference-template implementation.
- `tests/`, `docs/`, Docker/Compose files, CLI and external agent metadata.

These counts describe the tracked Git tree, not build output, ignored files, local user data, or the user's Windows working tree.

### 6.3 Major source entry points and coupling indicators

Static inspection of the current baseline source reported:

| File | Approx. lines | Observation |
|---|---:|---|
| `app.py` | 8,482 | 82 FastAPI route decorators; 91 occurrences of `BILLING_ENABLED`; 27 `cloud.` references; imports local Library, media auth, editor, reference templates, MCP/free tools, and S3/gallery helpers |
| `main.py` | 2,742 | Core pipeline orchestration; imports ML/media packages and many pipeline modules at module scope |
| `dashboard/src/App.jsx` | 2,725 | Imports local editing/runtime features alongside hosted auth/quota UI, social, thumbnail, UGC, MCP, Autopilot, and analytics helpers |
| `render-service/src/server.ts` | 219 | Express service, render request validation, token middleware, static output serving, and in-memory render job map |

The backend route inventory includes:
- Core local models, health, config, first-run, uploads, job processing/status, Library, projects, restore, edit, clip rerender, background, watermark, reframe, render, subtitles, hooks, and translation.
- Reference-template list/create/update APIs.
- Deferred social post/analytics/scheduling routes.
- Deferred thumbnail generation/publishing routes.
- Deferred AI UGC/SaaS Shorts routes.

Do not delete route groups from this list until their frontend, tests, background jobs, persistence, dependencies, and user-visible state are traced.

### 6.4 Native desktop and runtime contracts to protect

Current Tauri configuration reports:
- Product name: Clippy.
- Application version: `0.3.1`.
- Identifier: `com.helal.clippy`.
- NSIS per-user installer.
- Signed Tauri updater endpoint based on the stable GitHub latest-release manifest.

Current runtime contract:
- Python: `3.12.10`.
- Node.js: `22.23.3`.
- FFmpeg: Gyan essentials build family; the exact release version/source commit/archive hash is not currently pinned by the runtime contract.
- Remotion browser: `144.0.7559.20`, with archive/executable hashes in the runtime contract.

The current Rust supervisor source shows:
- Dynamic backend and renderer ports allocated on loopback.
- Backend and renderer hosts set to `127.0.0.1`.
- Per-launch API token generation.
- The same active token passed to backend and renderer.
- Backend/renderer process supervision and health checks.
- A Windows Job Object for supervised process lifetime.

The renderer token middleware rejects missing/wrong tokens when a desktop token is configured. If `CLIPPY_API_TOKEN` is empty, the middleware intentionally permits the self-host/Docker network-boundary mode. The desktop supervisor currently supplies the token and loopback hosts. Preserve this explicit desktop security contract; do not use the old Docker/self-host exception as the desktop security model.

### 6.5 Current feature implementation inventory

**Keep in v1**
- Video ingestion, processing, transcription, moment selection, reframing/layout, captions, hooks, rendering, clip editing, background editing, custom watermarking, local Library, reference templates, managed runtime, CPU/CUDA support, installer/updater.

**Reference templates are present on the current main baseline.** Confirmed implementation files include:
- `reference_templates.py`.
- `dashboard/src/components/ReferenceTemplateLibrary.jsx`.
- `tests/test_reference_templates.py`.
- The `reference_templates/` data/assets directory.
- API routes in `app.py`.

The template feature is local and should remain in v1. Its data persistence and migration behavior must be included in testing.

**Deferred/future features are already present in the codebase.** The UI imports social publishing components, `ThumbnailStudio`, `SaaShortsTab`, `UGCGallery`, MCP integration UI, and hosted Autopilot/account-related components. Their backend route groups, data, credentials, assets, tests, and cloud dependencies need feature-by-feature tracing before isolation.

**Analytics/telemetry:** `dashboard/src/lib/analytics.js` and OpenPanel configuration/commentary remain in the source. The environment example says analytics is optional/off by default, but the product decision is stricter: remove analytics/telemetry from v1, not merely leave it disabled.

### 6.6 Docker, website, and inherited identity residue

Docker-related tracked paths include root `Dockerfile`, `docker-compose.yml`, cloud/E2E/override Compose files, `dashboard/Dockerfile`, and `render-service/Dockerfile`. Root README still documents Docker development/self-hosting. Docker is not required by the native Windows installer and is explicitly out of scope for the future repository workflow.

The dashboard HTML still contains extensive OpenShorts website metadata: title, canonical URL, OpenGraph/Twitter content, structured data, old domain, old repository/download URL, and inherited marketing/pricing/feature claims. The dashboard tree also contains landing/legal/SEO content. These are not part of the new desktop app; the new Clippy website belongs in a separate project.

Product/internal package names still include:
- `openshorts-app` in `dashboard/package.json`.
- `openshorts-render-service` in `render-service/package.json`.
- `openshorts-remotion` in `remotion/package.json`.

The desktop Tauri product name and identifier are already Clippy-branded.

### 6.7 Confirmed documentation drift and contradictions

These are verified documentation inconsistencies, not cosmetic preferences:

1. Root `VERSION` and Tauri/dashboard app versions are `0.3.1`, and v0.3.1 is the latest published release, but root `README.md` and `desktop/README.md` still advertise v0.2.3 and its download path.
2. Root `AGENTS.md` identifies `CLIPPY_MASTER.md` as canonical. Root `CLAUDE.md` directs agents to `CLIPPY_REPO_AUDIT.md`. Root `README.md` also tells engineers to start with `CLIPPY_REPO_AUDIT.md`.
3. `CLIPPY_MASTER.md` records a last inspection date of 2026-11-09 and contains stale statements that main is Docker-oriented and the native migration is on a separate branch. The current main tree contains the merged Tauri desktop app and v0.3.1 release implementation.
4. `CLIPPY_REPO_AUDIT.md` contains a 2026-11-17 refresh and explicit historical caveats, but also has older sections that must be read as historical unless revalidated.
5. `CLIPPY_REPO_AUDIT.md` says `CLIPPY_MASTER.md` was consolidated into it and removed from main, but `CLIPPY_MASTER.md` is present in the current main tree.
6. README says the Docker self-host stack remains supported; that conflicts with the explicit v1 decision to remove Docker.

Do not silently delete historical engineering records to make the documentation look consistent. Phase 7 must establish a single current engineering guide, update agent instructions, and clearly label archived audit findings.

### 6.8 Build and validation surface

Current workflow definitions:
- `.github/workflows/ci.yml`: Python test suite and dashboard npm build.
- `.github/workflows/windows-desktop-validation.yml`: version validation, dashboard build, PowerShell script parsing, payload contract tests, Python compileall, Rust check/tests, and NSIS installer build; runtime packaging is conditional on relevant input changes.
- `.github/workflows/release-windows.yml`: backend tests, frontend build, CPU/CUDA runtime packaging, Pester contract tests, clean first-run setup/render smoke test, Rust tests, draft release asset verification, and publication.
- `.github/workflows/publish-cli.yml`: legacy CLI publication workflow; its continued presence is inconsistent with the current desktop-only v1 scope and must be evaluated with the CLI/agent metadata during a later removal phase.

Current dashboard package provides `build` and `lint` scripts. The inspected CI definition runs the build, not the lint script. Renderer package scripts include `build`, `test`, and `test:unit`; Phase 0 has not yet established that these renderer checks run in CI. Treat this as a validation-coverage question for the detailed test-matrix phase, not as a proven defect.

### 6.9 Baseline findings to carry forward

| ID | Finding | Priority | Planned handling |
|---|---|---|---|
| P0-01 | SaaS/cloud code is mixed into the large local backend | Critical | Trace and extract local contracts in Phase 2 before deletion in Phase 3 |
| P0-02 | Main UI mixes local and hosted/deferred feature state | High | Feature/state map, then controlled frontend refactor |
| P0-03 | Project engineering instructions contradict each other and are stale | High | Resolve documentation hierarchy in Phase 7; this cleanup file is the process ledger |
| P0-04 | README and desktop README advertise v0.2.3 while baseline is v0.3.1 | Medium | Correct during documentation/identity cleanup; no incidental docs edits during Phase 0 |
| P0-05 | Docker files and Docker/self-host documentation remain | High | Remove only after native build/test path references are confirmed |
| P0-06 | Deferred feature implementations have shared API/data/dependency paths | High | Four technical handoff documents and UI state in Phase 6 |
| P0-07 | Analytics helpers/configuration remain despite the no-analytics decision | Medium | Trace and remove in Phase 7 |
| P0-08 | Third-party commercial distribution rights for YOLO/Remotion and other assets require verification | Critical | Phase 1 release blocker |
| P0-09 | Renderer token behavior depends on desktop token being configured; no-token mode intentionally skips token checks | High | Preserve supervisor token injection; add/retain explicit security tests during Phase 2/5 |
| P0-10 | Renderer process-local job map loses status on process restart | Medium | Define expected lifecycle/recovery before deciding whether persistence is needed |
| P0-11 | Dashboard lint and renderer test/build coverage in CI is not yet established | Medium | Verify in detailed validation matrix; add coverage where needed |
| P0-12 | Local checkout contains two untracked items (`desktop/runtime-dist/` and `untangle-audit.md`) | High | Both are protected local working-tree content; do not stage, overwrite, delete, clean, or treat them as generated cleanup targets without an explicit owner decision |
| P0-13 | Current compliance/retention docs describe a hosted OpenShorts Cloud service, subprocessors, customer data, Stripe and R2/S3 retention | Critical | Verify live-service status and obtain an owner-approved export/retention/shutdown plan before hosted-source or external-infrastructure retirement |

### 6.10 Phase 0 completion checklist

- [x] Read the current repository agent instructions and the current engineering guide.
- [x] Read the current repository audit and the extraction/Untangle reference documents supplied for this cleanup.
- [x] Verify repository identity, default branch, and baseline commit.
- [x] Verify current application version and latest published release.
- [x] Inspect recursive tracked tree and identify top-level subsystem inventories.
- [x] Inspect major entry points, runtime manifests, package manifests, CI and release workflow definitions.
- [x] Verify general CI, Windows validation, and release workflow success on the baseline commit.
- [x] Record current scope decisions and deferred-feature requirements.
- [x] Create the cleanup branch from the exact main baseline.
- [x] Create this master cleanup ledger on the cleanup branch.
- [x] Owner confirmed the local checkout was on `chore/master-cleanup-phase-0` with HEAD `7e906b4` matching its then-current origin branch tip.
- [x] Owner reported only two untracked paths: `desktop/runtime-dist/` and `untangle-audit.md`; both are explicitly protected.
- [x] Owner confirmed there were no modified tracked files in the reported `git status --short` output.
- [ ] Owner to fast-forward the local checkout to the latest cleanup branch commits before local editing; do not disturb either protected untracked path.

**Phase 0 result:** remote source baseline and CI/release evidence are documented; the owner confirmed the local cleanup branch and then-current matching HEAD. The only Phase 0 repository change was the master cleanup document. The local untracked items `desktop/runtime-dist/` and `untangle-audit.md` remain untouched and must be preserved. No application source, tests, runtime scripts, workflows, or product behavior changed. Since the subsequent Phase 1 documentation commits were made remotely, the owner's local branch now needs a fast-forward pull before local work.

---

## 7. Current phase state and next action

| Phase | Status | Summary |
|---|---|---|
| 0 — Baseline and repository map | COMPLETE | Main `61edcd5`, v0.3.1, architecture/inventory, CI/release evidence, risks and drift recorded; local branch and protected untracked paths confirmed. The local branch now needs to pull the newer Phase 1 documentation commits. |
| 1 — Contracts, licensing, retirement preflight | PARTIALLY COMPLETE | Three Phase 1 documents are committed. Owner decisions on Ultralytics, Remotion eligibility and hosted-service status, plus artifact-level licence/hash/source verification, remain before Phase 1 can close. |
| 2 — Local backend extraction | NOT STARTED | Depends on Phase 1 contracts and safety review. |
| 3 — Remove hosted SaaS | NOT STARTED | Depends on Phase 2. |
| 4 — Remove Docker | NOT STARTED | Depends on verified native workflow and Phase 2/3 disconnection. |
| 5 — Engineering untangling | NOT STARTED | Focused refactoring with regression coverage. |
| 6 — Deferred features | NOT STARTED | Four handoff docs and Under investigation UI states. |
| 7 — Identity/docs/config cleanup | NOT STARTED | Reconcile guides and product identity. |
| 8 — New UI | NOT STARTED | Contract-driven implementation. |
| 9 — Full regression and Windows validation | NOT STARTED | Packaged behavior and upgrade/data preservation. |
| 10 — Release readiness | NOT STARTED | Signed, validated and documented release. |

### Local checkout confirmation and protected items

Owner-reported PowerShell state:
```text
PS D:\\openshorts> git status --short
?? desktop/runtime-dist/
?? untangle-audit.md

PS D:\\openshorts> git log -1 --oneline
7e906b4 (HEAD -> chore/master-cleanup-phase-0, origin/chore/master-cleanup-phase-0) docs(cleanup): establish Clippy v1 master cleanup plan
```

Interpretation:
- The checked-out branch and local HEAD match the cleanup branch commit.
- The working tree has two untracked paths. They are not dirty tracked files, but their content is user-owned local state and is protected.
- Do not add either path to a commit, overwrite it, delete it, clean it, or add an ignore rule without a separate explicit decision.
- The file `untangle-audit.md` remains a local reference source. Do not assume it is part of the tracked repository simply because it is present in the working directory.


### Phase 1 work log (2026-11-19)

**Phase 1 start commit:** `7e906b4abb1b89d6b5770a15c180ee2a485f9f74`  
**Current policy:** documentation and source-contract inspection only; no product source or workflow edits.

Documents added on the cleanup branch:
- [Local runtime, service and data contract](./docs/architecture/clippy-v1-local-runtime-contract.md) — commit `4d82e8dc7f`.
- [Third-party licence and provenance inventory](./docs/compliance/clippy-v1-third-party-license-and-provenance-inventory.md) — commit `172df8dd53`.
- [Hosted-service retirement preflight](./docs/compliance/clippy-hosted-service-retirement-preflight.md) — commit `edbd91db2d`.

### Phase 1 findings to carry forward

| ID | Finding | Priority | Required resolution |
|---|---|---|---|
| P1-01 | Ultralytics YOLO `8.4.46` and its default model are AGPLv3; the current MIT project licence is not proof of compliance with Ultralytics' commercial-use conditions | Critical | Owner selects Enterprise licence, full-project AGPL route after legal review, or a compatible replacement preserving person-detection behavior |
| P1-02 | Remotion is pinned to v4.0.447; exact tagged licence eligibility depends on the organisation/team operating Clippy | High | Owner confirms the applicable headcount/status and obtains written clarification if the embedded product arrangement is uncertain |
| P1-03 | Gyan's FFmpeg essentials static build is GPLv3, and setup downloads from a moving release URL with a separately fetched moving checksum | High | Pin exact build/version/source commit/hash and retain applicable GPL/source notices; obtain legal review of the distributed executable boundary |
| P1-04 | bgutil 1.3.2 plugin and Node provider are GPLv3; payload preparation does not explicitly include the Node source/licence bundle before deleting the clone | High | Pin immutable commit and prepare complete corresponding-source/licence notices for every distributed component |
| P1-05 | CUDA PyTorch runtime contains NVIDIA DLLs; CUDA Toolkit and cuDNN have separate EULAs and only specified components are distributable | High | Inventory actual runtime DLLs and map each package/version to the correct redistribution terms and notices |
| P1-06 | Chrome Headless Shell archive is separately downloaded; the Chrome for Testing metadata repository's Apache licence is not proof of the browser binary's complete notice set | High | Inspect the exact versioned archive and package its browser/Chromium third-party notices |
| P1-07 | Anton and Noto Serif fonts are OFL 1.1, but their licence texts are not present in the tracked fonts directory; Montserrat's OFL text is present | Medium | Add the identified font licence/copyright notices to the packaged third-party notice bundle |
| P1-08 | Gemini key is stored plaintext in localStorage; other provider keys use reversible XOR/Base64 obfuscation | High | Design secure native storage and lossless migration; do not migrate hosted auth/session tokens |
| P1-09 | Ultralytics' default Windows config/weights cache is outside Clippy's managed data root because the supervisor sets neither `YOLO_CONFIG_DIR` nor `YOLO_MODEL_PATH` | High | After the YOLO licensing decision, migrate cache/weights into managed model storage without losing existing files |
| P1-10 | Dated repository privacy/retention documents describe an OpenShorts Cloud service and customer/subprocessor data flows; current live status is not independently verified | Critical | Owner confirms live-service status and approves any customer export, retention, shutdown or data-deletion plan |
| P1-11 | Renderer job status is held in a process-local Map and is lost on renderer restart | Medium | Define required job recovery semantics before deciding on persistence in Phase 5 |

### Phase 1 validation record

- Documentation/source review only.
- No product source, test, workflow, runtime or installer files were changed.
- No CI run was started: changes are Markdown documentation only.
- No Windows validation was started: no Windows runtime/installer source was changed.
- Structural verification: all three new documents were fetched back from the cleanup branch and their headings/contents checked.
- Artifact-level SBOM, exact CUDA DLL inventory, Chrome archive licence inspection, FFmpeg immutable asset pinning and corresponding-source packaging remain open.

### Phase 1 owner decisions blocking closure

1. **Ultralytics:** obtain Enterprise licensing or replace the detector with a commercially compatible implementation. A full-project AGPL licence is another route, but requires an explicit project-wide decision.
2. **Remotion:** confirm whether Clippy is operated by an individual/non-profit or a for-profit organisation with three or fewer people, or by a larger organisation. Clarify the embedded product distribution with Remotion if needed.
3. **Hosted service:** confirm whether OpenShorts Cloud still has live customers/accounts/subscriptions/data or whether the cloud code is now only historical. Repository docs dated 2026-09-04 describe the service and its operational data/retention obligations.

### Phase 1 start record


**Started:** 2026-11-19  
**Starting cleanup commit:** `7e906b4abb1b89d6b5770a15c180ee2a485f9f74`  
**Scope:** Architecture/runtime/security contracts, licence/provenance inventory, data migration/rollback requirements, and external-service retirement preflight.  
**Code-change policy:** No product source or workflow edits during the initial Phase 1 investigation. Findings and contracts are documented first.  
**Validation policy:** Follow the minimum-CI policy above; focused checks first. Windows validation is launched only when required, and its link is handed to the owner without continuous polling.

**Next:** complete Phase 1 preflight. Do not start source deletion or broad refactoring before its contracts, licensing, provenance, and retirement requirements are resolved.