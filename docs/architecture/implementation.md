# Template Reference System — Implementation Tracker

**Repository:** `helalxp/clippy`  
**Branch:** `feature/template-reference-system`  
**Status:** Stages 0–3 complete; Stage 4 interpretation/synthesis and Stage 5 Python/FFmpeg adapter plus local clip-application API are in progress.  
**Last implementation update:** 2026-11-12 (shared edit-lock code committed; CI validation pending)

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
- [x] Focused template CI: **69 passed, 0 failed** on 2026-11-12.

### Not yet implemented

- [x] Provider-neutral strict interpretation contract, evidence verification, attributable human review, resolver integration, optional consent-gated Gemini vision adapter, persistent interpretation claims, and renderer capability snapshots in draft templates.
- [ ] Live provider quality validation, token/cost telemetry, and broader visual claim coverage.
- [x] Python/FFmpeg adapter consumes validated recipes for canvas, cover/contain/manual framing, and original/blur/solid backgrounds; local `POST /api/template/apply` integrates the application service with clean canonical clips and provenance persistence.
- [x] Shared per-job edit locking covers background, watermark, effects generation, subtitle add/remove, hook, and translation routes; rerender, reframe, template apply, and general edit retain their explicit lock scopes. Concurrency and route-registration tests are committed, pending CI execution.
- [~] Remaining Python/FFmpeg features include template-driven captions, hooks/titles, overlays, and tracking; these must be implemented and capability-tested individually.
- [ ] Shared recipe contract and parity adapters for browser preview and Remotion final render.
- [~] Local clip-application API exists, but template library CRUD/import/upload APIs, durable analysis-job lifecycle, library UI, editor UI, and a complete user-facing end-to-end workflow remain outstanding.
- [ ] Migration of the legacy v1 reference-template manifest.
- [ ] Versioned import/export package and complete template lifecycle operations.
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
| Focused template tests | `tests/test_template_system_*.py` | 69 passed in GitHub Actions |
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
- **Total: 109 passed in the focused GitHub Actions job.**
- Frontend build job: passed.

### Full backend suite

The full backend job is not green. The latest full-suite run after adding the local apply API tests reported **1,317 passed, 50 skipped, 2 failed**. Both failures match the pre-existing baseline recorded in the Phase 0 audit:

1. `tests/test_generation_controls.py::TestClipDurationBounds::test_env_overrides_apply`: test expects `(20.0, 30.0)`, current result is `(20.0, 25.0)`.
2. `tests/test_recut.py::TestPerformRecut::test_source_path_reframes_and_watermarks`: injected watermark lambda does not accept the `backdrop_type` and `backdrop_color` keyword arguments now passed by `recut.perform_recut`.

These are not failures in the template-specific test job. They remain separate repository cleanup items and are not silently counted as green.

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

Only the bounded sampled PNG evidence and deterministic measurements are passed to the Gemini adapter; the original reference video is never uploaded by this adapter. Model-generated claims are forcibly reset to pending and cannot approve themselves. The latest completed focused suite passed 109 tests. The local apply API and managed-mode storage-gate tests also passed within the full backend run. Stage 4's remaining gates are a live opt-in Gemini smoke test, token/cost telemetry, and quality checks on representative references. Draft `TemplateDocument` assembly persists interpretation claims, reviewer provenance, frame evidence, recipe, and per-renderer capability snapshots. Stage 5 now has a real FFmpeg adapter plus a storage-backed application service. The service resolves overrides and locks, applies the supported subset, and returns recipe hash, template revision, source/output fingerprints, compatibility, and adaptation provenance. It is now wired through `POST /api/template/apply`: the route checks job ownership, serializes against rerender/reframe, starts from the clean canonical clip, atomically updates metadata, updates in-memory clip state, and archives the new delivery. End-to-end local API and managed-mode storage-gate tests passed in the full backend run. The library is rooted independently through `TEMPLATE_LIBRARY_DIR` and is rejected if configured inside ephemeral `OUTPUT_DIR`. Managed/cloud application is deliberately disabled until durable per-user storage, tenant isolation, backup, and deletion semantics are approved and implemented. Captions, hooks, overlays, and tracking remain unsupported.

## 8. Next vertical slice

1. Wire `PythonFFmpegAdapter` into the existing editor/render API using clean canonical source media.
2. Persist recipe hash, template revision, and output provenance.
3. Add golden-frame pixel assertions for crop anchors and background treatment.
4. Add caption and hook adapters with exact/approximate/unsupported capability reporting.
5. Add overlay support only after asset sizing/position semantics are validated.
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
