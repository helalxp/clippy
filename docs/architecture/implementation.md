# Template Reference System — Implementation Tracker

**Repository:** `helalxp/clippy`  
**Branch:** `feature/template-reference-system-clean`  
**Status:** Stages 0–3 complete; Stage 4 interpretation/synthesis is implemented with provider-quality gates pending; Stage 5 Python/FFmpeg application and local template-library API are in progress.  
**Last implementation update:** 2026-11-12 (owner-scoped template CRUD and verified image asset lifecycle validated in CI run `43310755521`)

This is the execution-level source of truth. Product intent and architecture rationale live in [TEMPLATE_REFERENCE_SYSTEM_SPEC.md](./TEMPLATE_REFERENCE_SYSTEM_SPEC.md); milestone exit criteria live in [stages.md](./stages.md).

## 1. Objective

Turn a creator-provided reference video into a reusable, editable, versioned Clippy template. Applying a template must produce a deterministic effective recipe, disclose unsupported or approximate behavior, preserve explicit user choices, and ultimately render consistently in preview and final output.

A template is a structured editing recipe, not a visual preset or an AI-generated description.

## 2. Current standing

### Completed

- [x] Phase 0 repository and architecture audit.
- [x] Canonical versioned template and recipe contracts.
- [x] Conservative renderer capability registry.
- [x] Deterministic recipe resolver with explicit locks, adaptation decisions, and canonical SHA-256 hashing.
- [x] Local template storage with atomic manifest replacement, thread and OS-backed cross-process locks, optimistic revision checks, and asset integrity validation.
- [x] Reference-video staging, deterministic FFprobe metadata collection, FFmpeg scene-cut detection, bounded frame sampling, pixel-level visual measurements, and partial-result reporting.
- [x] Conversion of measured results into canonical `TemplateAnalysis`, `TemplateAsset`, and evidence records.
- [x] Progress callbacks and cancellation checks at safe staging/analysis boundaries.
- [x] Real FFmpeg/FFprobe integration fixture verifies the full local path from staging through analysis and persistent template assets.
- [x] Focused template/API/edit-lock CI: **123 passed, 0 failed** in run `43310755521`.

### Not yet implemented

- [x] Provider-neutral strict interpretation contract, evidence verification, attributable human review, resolver integration, optional consent-gated Gemini vision adapter, persistent interpretation claims, and renderer capability snapshots in draft templates.
- [ ] Live provider quality validation, token/cost telemetry, and broader visual claim coverage.
- [x] Python/FFmpeg adapter consumes validated recipes for canvas, cover/contain/manual framing, and original/blur/solid backgrounds; local `POST /api/template/apply` integrates the application service with clean canonical clips and provenance persistence.
- [x] Shared per-job edit locking covers background, watermark, effects generation, subtitle add/remove, hook, and translation routes; rerender, reframe, template apply, and general edit retain their explicit lock scopes. Concurrency and route-registration tests passed in CI run `43309965692`.
- [x] Canonical caption styling and template-driven hook/title rendering are implemented and capability-tested in Python/FFmpeg.
- [x] Image/watermark overlays and deterministic Python/FFmpeg motion/color-effect slices are implemented with real-render fixtures and conservative capability checks.
- [ ] Text overlays, subject tracking, transitions, and browser/Remotion parity remain outstanding.
- [ ] Shared recipe contract and parity adapters for browser preview and Remotion final render.
- [x] Local template-library list/create/read/update/delete APIs with owner-scoped storage and optimistic revision checks.
- [x] Raster image asset upload/read/delete APIs for PNG, JPEG, and WebP, with server-generated IDs/paths, 20 MB cap, MIME/signature/decoder checks, dimension and pixel limits, SHA-256 verification, and revision-safe lifecycle.
- [x] Local font asset upload supports bounded TrueType/OpenType SFNT validation, server-generated paths, checksum verification, revision-safe storage, and owner-scoped retrieval. Caption and hook adapters resolve referenced font assets and stage them for rendering.
- [x] Versioned .clippy-template package import/export validates archive paths, entry counts, compression methods/ratios, expanded sizes, symlinks, manifest schema/version, asset inventory, media signatures/structure, and SHA-256 checksums. Imports receive a fresh local template ID and revision.
- [ ] Durable analysis-job lifecycle, library UI, editor UI, and a complete user-facing end-to-end workflow remain outstanding.
- [ ] Migration of the legacy v1 reference-template manifest.
- [x] Versioned import/export package with bounded, integrity-checked asset round-trip.
- [ ] Complete template lifecycle operations, including migration of the legacy v1 reference-template manifest.
- [ ] Managed/cloud storage. This remains out of scope until tenant isolation and authorization are designed.

### Explicitly not claimed

- Pixel difference between sampled frames is not optical flow and does not establish subject motion.
- Edge density is not semantic subject/layout detection.
- Color palette measurements do not identify brand intent or editing style by themselves.
- Scene-cut candidates are deterministic FFmpeg measurements, not yet a validated editorial-cut classifier.
- No AI-generated claim is accepted without strict schema validation and references to sampled evidence.

## 3. Implementation inventory

| Area | Source | Status |
|---|---|---|
| Domain contracts | `template_system/models.py` | Implemented; 18 contract tests pass |
| Capability registry | `template_system/capabilities.py` | Implemented; conservative exact/approximate/unsupported reporting |
| Recipe resolver | `template_system/resolver.py` | Implemented; deterministic precedence, locks, and hash |
| Local storage | `template_system/storage.py` | Implemented; 18 storage tests pass |
| Reference staging | `template_system/ingest.py` | Implemented; 7 tests pass |
| Media probe and scene sampling | `template_system/analysis.py` | Implemented; real FFmpeg fixture passes |
| Pixel measurements | `template_system/visuals.py` | Implemented; 6 tests pass |
| Focused template tests | `tests/test_template_system_*.py` | 123 passed in GitHub Actions run `43310755521` |
| Semantic interpretation | `template_system/interpretation.py`, `template_system/providers/gemini.py`, domain models | Contract, consent-gated Gemini adapter, human review, synthesis, and persistent draft assembly implemented; live call/quality verification pending |
| Python/FFmpeg recipe adapter | `template_system/adapters/python_ffmpeg.py` | First real-FFmpeg slice implemented; API integration and additional features pending |
| Remotion parity | Not implemented | Stage 6 |
| API and UI | Not implemented | Stage 7 |
| Migration/import/export | Not implemented | Stage 8 |

## 4. Technical decisions

1. **Canonical intent is renderer-independent.** Domain models describe normalized editing intent; FFmpeg and Remotion details belong in adapters.
2. **Units are explicit.** Positions and dimensions ending in `_ratio` are canvas-relative; timeline values are seconds; colors are six-digit sRGB hex; font sizes are ratios of canvas height.
3. **Compatibility is honest.** Exact, approximate, and unsupported are distinct. An unsupported requested feature makes a renderer incompatible; it must never be silently dropped.
4. **Resolution is deterministic.** Defaults → template → revision → job overrides → AI adaptation proposals → clip overrides → explicit locks. Lists replace, never append.
5. **AI is advisory.** Claims must be schema-validated, evidence-linked, and reviewable. User corrections, clip overrides, and locks remain authoritative.
6. **Local-first storage only.** Do not enable shared/managed storage before ownership, authorization, isolation, quotas, deletion, and media delivery are implemented and tested.
7. **No premature UI or renderer rewrite.** First synthesize a validated recipe, then prove a Python/FFmpeg vertical slice, then measure preview/final parity.
8. **Existing generation behavior remains stable.** Template application is opt-in and must not alter the current generation path without regression evidence.

## 5. Verification and known repository baseline

### Template-specific verification

- Contract tests: 18 passed.
- Storage tests: 18 passed, including cross-process locking and failure-preservation cases.
- Analysis tests: 20 passed, including a real FFmpeg-generated two-scene fixture and a cut-time assertion within 200 ms of the known transition.
- Ingest tests: 7 passed.
- Visual-measurement tests: 6 passed.
- Interpretation/review/synthesis tests: 17 passed.
- Gemini adapter tests: 4 passed with a fake client; no live external request was made.
- Python/FFmpeg adapter tests: 17 passed, including real cover/contain/background renders, audio preservation, subtitle-stream rejection, pixel-level crop/background checks, cancellation, and clean-source protection.
- **Total: 123 passed in the focused GitHub Actions job** in run `43310755521`.
- Frontend build job: passed.

### Full backend suite

GitHub Actions run `43310755521` validated the local-library CRUD and image-asset lifecycle: **1,331 passed, 50 skipped, 0 failed** in the full backend suite; **123 passed** in the focused template/API/edit-lock suite; frontend production build passed. All three jobs completed successfully.

### Scope boundary

The Windows Python 3.12 installer/runtime issue is tracked separately. It is not a blocker for remote implementation or GitHub Actions validation of this feature.

## 6. Completed stages

- **Stage 0:** architecture and source audit.
- **Stage 1:** canonical contracts, capability registry, resolver.
- **Stage 2:** local persistence and asset integrity.
- **Stage 3:** deterministic reference ingest, probe, scene sampling, visual measurements, evidence conversion, and real-media fixture validation.

See [stages.md](./stages.md) for acceptance evidence and remaining work.

## 7. Active work: Stages 4–5

The provider-neutral interpretation contract and optional Gemini vision adapter are now implemented. A provider may propose structured claims about caption style, hook placement, framing, background treatment, and rhythm, but every claim must:
- target a known canonical recipe property;
- cite one or more sampled evidence asset IDs and timestamps;
- include a calibrated qualitative confidence or an explicit uncertainty state;
- pass strict type/range validation;
- remain a proposal until accepted or corrected;
- never invent text content, fonts, logos, or unsupported renderer behavior from insufficient evidence.

Only the bounded sampled PNG evidence and deterministic measurements are passed to the Gemini adapter; the original reference video is never uploaded by this adapter. Model-generated claims are forcibly reset to pending and cannot approve themselves. The latest completed focused suite passed 115 tests before the CRUD API tests were added. The local apply API and managed-mode storage-gate tests also passed within the full backend run. Stage 4's remaining gates are a live opt-in Gemini smoke test, token/cost telemetry, and quality checks on representative references. Draft `TemplateDocument` assembly persists interpretation claims, reviewer provenance, frame evidence, recipe, and per-renderer capability snapshots. Stage 5 now has a real FFmpeg adapter plus a storage-backed application service. The service resolves overrides and locks, applies the supported subset, and returns recipe hash, template revision, source/output fingerprints, compatibility, and adaptation provenance. It is now wired through `POST /api/template/apply`: the route checks job ownership, serializes against rerender/reframe, starts from the clean canonical clip, atomically updates metadata, updates in-memory clip state, and archives the new delivery. End-to-end local API and managed-mode storage-gate tests passed in the full backend run. The library is rooted independently through `TEMPLATE_LIBRARY_DIR` and is rejected if configured inside ephemeral `OUTPUT_DIR`. Managed/cloud application and library management are deliberately disabled until durable per-user storage, tenant isolation, backup, and deletion semantics are approved and implemented. The local library now exposes list/create/read/update/delete endpoints under `/api/templates`, plus owner-scoped raster/font asset lifecycle and versioned package import/export. Python/FFmpeg supports canonical captions, hook/title layers, image/watermark overlays, frame-timed punch-in/slow-zoom/pan motion, and time-bounded brightness/contrast/saturation effects. Text overlays, subject tracking, transitions, and unimplemented recipe features remain explicitly unsupported.

## 8. Next vertical slice

1. Wire `PythonFFmpegAdapter` into the existing editor/render API using clean canonical source media.
2. Persist recipe hash, template revision, and output provenance.
3. Add golden-frame pixel assertions for crop anchors and background treatment.
4. Add text overlays only after the canonical contract defines typography, backing, and line layout.
5. Define measurable subject-tracking and transition contracts with explicit quality and compatibility gates.
6. Add Remotion preview/final adapters only after the Python slice is integrated and stable.

## 9. Change log

- **2026-11-12:** Restored this tracker and `stages.md` on the online feature branch. Stages 0–3 are evidenced; Stage 4 interpretation and Stage 5 FFmpeg application work are in progress. Focused CI reached 107 passing tests, including real FFmpeg ingest, pixel-level output checks, and stored-template application-service tests. Added source-overwrite regression tests, pending CI. Recorded the two known full-backend baseline failures separately.


## Latest implementation update: shared clip-edit serialization

Commit: `733bec520a7759a5dd92a0d6a194bca4078e8027`

- Added a reusable async endpoint decorator that resolves the job identifier from either a request model or form-style keyword argument and acquires the existing per-job edit lock.
- Applied it to background, watermark, effects-generation, subtitle-add, subtitle-remove, hook, and translation routes.
- Rerender, reframe, and template application retain their existing explicit lock scopes. They are not decorated, avoiding re-entrant deadlocks.
- The lock covers each decorated endpoint's complete operation, including metadata reads, derivative generation, and metadata writes. Edits to different jobs remain independent.
- Added concurrency tests for same-job serialization, cross-job independence, form-style job ID extraction, and route-registration coverage for all seven decorated endpoints in `tests/test_template_system_edit_locking.py`.

Verification status: implementation and tests are committed; CI validation is pending. Do not treat this as verified until the focused and full backend workflows complete.

Next: complete CI validation, finish auditing the remaining job-creation and restore lifecycle paths for lock interactions, then implement caption styling and hook/title template adapters with explicit capability reports and real FFmpeg fixtures. The existing hook endpoint is now race-serialized, but template-driven hook rendering is still unsupported.


### Lock coverage audit

The source audit identified seven additional editor routes that perform clip-level work against job metadata. All seven now use the shared lock decorator: background, watermark, effects generation, subtitle addition, subtitle removal, hook, and translation. The existing rerender, reframe, template-apply, and general edit routes retain their explicit lock scopes. New-job processing is a job-creation path rather than an edit to an existing clip; project restoration remains a separate storage lifecycle operation and is not folded into the local edit lock in this change.

The route-registration test guards against accidentally removing the decorator from any of the seven wrapped routes. This is code-level coverage only; CI must still execute the tests before this change is considered validated.


## CI reliability review — 2026-11-12

The red backend check was compared against the latest `main` workflow, not assumed to be template-related. Both failures were already present on `main` before this feature branch:
- `clip_selection.clip_duration_bounds` checked for a 15-second minimum span but widened an invalid range by only 5 seconds. The condition now consistently enforces a 5-second minimum span, matching the existing test contract.
- `recut.perform_recut` passed `backdrop_type` and `backdrop_color` to `main.apply_watermark`, whose actual signature accepts only the video path and optional output path. The unnecessary background arguments are removed.

The latest pre-fix template branch run had 1,321 passing, 50 skipped, and those same two baseline failures. The four new edit-lock tests passed in the backend run. The focused template workflow is being expanded to include the API and locking tests, with the lightweight backend dependencies needed to import the application.

Clean-branch validation passed in GitHub Actions run `43310755521` on 2026-11-12: focused template/API/locking suite **123 passed**, full backend suite **1,331 passed, 50 skipped**, and frontend production build **passed**. No backend failures remain in this run.


### Verified clean-branch CI

- Branch: `feature/template-reference-system-clean`
- Base: current `main` at `0d8fe1fa4f9d8493adf2b8e6aff2bdaf6e64b4eb`
- CI run: [43304254324](https://github.com/helalxp/clippy/actions/runs/43304254324)
- Template, API and edit-lock tests: **123 passed**
- Full backend suite: **1,331 passed, 50 skipped**
- Frontend production build: **passed**
- Overall workflow: **passed**

The previous `feature/template-reference-system` branch was 205 commits ahead of main and its tree included desktop-installer files outside this feature. It was left untouched. The clean branch was created directly from main to isolate template work. It has since received implementation, validation-documentation, and local library API commits; compare the branch with main for its current ahead count.


## Latest implementation update: local template-library CRUD API

- Added owner-isolated local endpoints: `GET /api/templates`, `POST /api/templates`, `GET /api/templates/{template_id}`, `PUT /api/templates/{template_id}`, and `DELETE /api/templates/{template_id}`.
- Each request resolves the same hashed owner scope used by template application. Local installations without an account use a dedicated local-installation scope.
- Filesystem operations run in worker threads; the storage layer retains cross-process locks and atomic manifest writes.
- Updates require an explicit `expected_revision`; the server increments the revision and timestamp. Deletes also require the caller's observed `expected_revision`. Stale updates or deletes return HTTP 409.
- Managed mode returns HTTP 503 until durable per-user storage and lifecycle guarantees exist.
- Create currently accepts asset-free manifests only. Asset-bearing manifests return HTTP 422 rather than creating records whose referenced files do not exist.
- Added four API tests for CRUD, owner isolation, revision conflicts, asset gating, and managed-mode gating.
- Initial API implementation: `c208028afa3e453efa27eeed09c071dc42ba3b3a`.
- CRUD API tests: `ab80b3a82810fb50bc4dec397cc462a7beb39073`.
- Revision-safe update/delete hardening: `c620cb708fbca0502cd2fcd1448e9665fc97fb78`, `e80f0e3d06eb2b6c6f86c96906dcd868158a59db`, and `be791d4746e167a78ab8e7d463282ec26ce19be0`.
- Timestamp assertion hardening: `6e49046629eca2b41f4cd5a19aae668536c8758d`.
- CI validation: passed in run `43310755521`, including CRUD, revision-safe update/delete, and image asset upload/read/delete tests.

Next: add font asset support and versioned template package import/export. Then connect existing clip transcript and caption-style data to canonical template caption styling without duplicating the current subtitle engine.


## Latest implementation update: font assets and portable packages

- Added bounded TrueType/OpenType font upload to the owner-scoped template asset endpoint. The server derives the asset type and extension from the SFNT signature, validates the table directory and required structural tables, rejects out-of-bounds/overlapping tables, and applies a 25 MB limit.
- Existing PNG/JPEG/WebP upload behavior remains intact with its 20 MB, decoder, dimension, and pixel-count checks.
- Font assets use the existing revision-safe storage, checksum, opaque path, retrieval, and reference-safe deletion lifecycle. The canonical model already supports font asset references; this change does not claim that either renderer loads or applies uploaded fonts yet.
- Added versioned .clippy-template ZIP package import/export. Export verifies stored assets and writes deterministic archive entries. Import rejects traversal, symlinks, duplicate paths, encrypted or unsupported compression entries, excessive entry counts/sizes/ratios, unsupported package versions, unknown files, invalid media, and checksum mismatches. It assigns a new local template ID and revision 1.
- Added owner-scoped GET /api/templates/{template_id}/export and POST /api/templates/import endpoints.
- Added focused tests for SFNT validation, font API upload/retrieval, package round-trip, deterministic export, unsafe archive rejection, and package API behavior.
- GitHub Actions run 43420728540 passed on the current implementation: 149 focused template tests passed, 1,371 backend tests passed, 50 skipped, and the frontend production build passed.

Next: implement template-driven caption styling as the next isolated Python/FFmpeg adapter capability, with real font-file fixtures, deterministic rendered output, explicit compatibility reporting, and tests that prove existing subtitle behavior remains unchanged.


## Latest implementation update: template-driven captions

- The Python/FFmpeg adapter now consumes the canonical CaptionRecipe and writes ASS through the existing subtitle generator. It does not introduce a second caption-rendering engine.
- Caption rendering supports font family, normalized font size, text/highlight/outline colors, outline and shadow ratios, word highlighting, word reveal, uppercase, and top/middle/bottom placement. Canonical top/bottom safe-area margins are translated to ASS margins.
- When a template references a font asset, the application service resolves the owner-scoped asset and the adapter stages it in a temporary FFmpeg fonts directory. Temporary ASS/font files are cleaned after render.
- Template application receives the saved job transcript, remaps recut EDL segments onto the clip timeline, and prefers saved user-edited caption words when present. A template that enables captions without available words fails clearly instead of silently rendering without captions.
- Custom x/y caption anchors are explicitly unsupported. Non-default max_lines values are approximate because glyph wrapping varies by font and language. Text overlays and Remotion preview parity remain outstanding.
- GitHub Actions run 43421896913 passed on the current branch head: 154 focused template tests, 1,371 backend tests passed with 55 skipped, and frontend production build passed.

Implemented: the Python/FFmpeg adapter now renders canonical hook/title layers through a dedicated drawtext adapter. It supports uploaded hook fonts, UTF-8 text-file input with drawtext expansion disabled, optional solid backing, top/center/bottom/custom normalized placement, safe-area-aware top/bottom positions, timed visibility, and all declared entrance styles (none, fade, slide_up, spring, pop). Hooks are applied after captions. The application service resolves hook font assets independently from caption font assets. Real FFmpeg tests cover hook visibility and expiry on original, blurred, and solid background paths, plus text-injection safety and uploaded-font resolution.

- GitHub Actions run `43424728800` passed on commit `2e4d438348ae5813372bcf9fc0275c7f7a8659f7`: **157 focused template tests passed**, **1,371 backend tests passed with 58 skipped**, and the frontend production build passed.

Next: implement measurable motion/effect recipe support and subject-tracking only against explicit contracts and fixtures. Text overlays need an expanded typography schema. Do not claim full template fidelity until preview and final-render parity are separately proven.
