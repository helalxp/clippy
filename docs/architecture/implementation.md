# Template Reference System — Implementation Tracker

**Repository:** `helalxp/clippy`  
**Branch:** `feature/template-reference-system`  
**Status:** Stages 0–3 complete; Stage 4 structured interpretation and template synthesis is next.  
**Last verified update:** 2026-11-12

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

- [ ] Structured semantic interpretation of reference frames.
- [ ] Evidence-backed synthesis of a reusable editing recipe from interpreted claims.
- [ ] Production Python/FFmpeg adapter consuming the resolved recipe.
- [ ] Shared recipe contract and parity adapters for browser preview and Remotion final render.
- [ ] Template API, durable analysis-job lifecycle, library UI, editor UI, and end-to-end apply workflow.
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
| Semantic interpretation | Not implemented | Stage 4 |
| Python/FFmpeg recipe adapter | Not implemented | Stage 5 |
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
- **Total: 69 passed in the focused GitHub Actions job.**
- Frontend build job: passed.

### Full backend suite

The full backend job is not green. On the audited branch run it reported **1,294 passed, 30 skipped, 2 failed**. Both failures match the pre-existing baseline recorded in the Phase 0 audit:

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

## 7. Next active work: Stage 4

Build a provider-agnostic interpretation boundary. A vision provider may propose structured claims about caption style, hook placement, framing, background treatment, overlays, transitions, and rhythm, but every claim must:
- target a known canonical recipe property;
- cite one or more sampled evidence asset IDs and timestamps;
- include a calibrated qualitative confidence or an explicit uncertainty state;
- pass strict type/range validation;
- remain a proposal until accepted or corrected;
- never invent text content, fonts, logos, or unsupported renderer behavior from insufficient evidence.

Then synthesize a draft `TemplateRecipe` deterministically from accepted claims and measured facts. Provider-specific Gemini wiring comes after the provider-neutral contract and fake-provider tests.

## 8. Next vertical slice after Stage 4

1. Implement a small Python/FFmpeg adapter for canvas, caption style, hook, and one background behavior.
2. Preflight renderer capability before rendering.
3. Render deterministic fixtures from clean source media.
4. Inspect output frames, timing, stream metadata, and recipe provenance.
5. Update capability claims only after adapter behavior is implemented and tested.
6. Add Remotion preview/final adapters only after the Python slice is stable.

## 9. Change log

- **2026-11-12:** Restored this tracker and `stages.md` on the online feature branch. Stages 0–3 are now evidenced; focused template CI reports 69 passing tests, including a real FFmpeg ingest-to-persisted-template fixture. Recorded the two known full-backend baseline failures separately.
