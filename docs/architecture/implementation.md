# Template Reference System — Implementation Tracker

**Repository:** `helalxp/clippy`  
**Branch:** `feature/template-reference-system`  
**Status:** Phases 1 and 2 complete; Stage 3 deterministic reference-analysis foundation implemented and under verification.  
**Last verified update:** 2026-11-12

This file is the execution-level source of truth. Product intent and architecture rationale live in [TEMPLATE_REFERENCE_SYSTEM_SPEC.md](./TEMPLATE_REFERENCE_SYSTEM_SPEC.md); milestone gates live in [stages.md](./stages.md).

## 1. Objective

Let a creator provide a reference video and turn its editing language into a reusable, editable, versioned Clippy template. Applying a template must produce a deterministic effective recipe, disclose unsupported or approximate behavior, preserve explicit user choices, and eventually render consistently in preview and final output.

A template is a structured editing recipe, not a visual preset or an AI-generated description.

## 2. Current standing

### Completed

- [x] Phase 0 source audit: legacy reference-template prototype, Python/FFmpeg pipeline, Remotion preview/render trees, editing endpoints, and baseline CI were inspected.
- [x] Confirmed two Remotion composition trees have behavior/schema drift.
- [x] Confirmed Python/FFmpeg is a separate production-critical render path and cannot be bypassed by implementing templates only in Remotion.
- [x] Defined canonical versioned template and recipe contracts in `template_system/models.py`.
- [x] Defined conservative per-renderer capability reporting in `template_system/capabilities.py`.
- [x] Defined deterministic recipe resolution, adaptation rejection, explicit locks, and canonical SHA-256 hashing in `template_system/resolver.py`.
- [x] Added focused contract tests in `tests/test_template_system_contracts.py`.
- [x] Declared Pydantic v2 explicitly in `requirements.txt`.
- [x] Focused tests executed by the user in an isolated Python 3.11.16 environment: **18 passed, 0 failed (0.35s)** on 2026-11-12.

### Not yet implemented

- [x] Local template storage, atomic writes, per-template thread and OS-backed file locks, revision compare-and-swap, and asset integrity verification implemented and focused-test verified.
- [ ] Migration of the legacy v1 reference-template manifest.
- [~] Deterministic media probing, scene-boundary candidates, bounded sample selection, timestamped PNG evidence, SHA-256 fingerprints, and partial-result reporting implemented. Staged ingest/jobs, cancellation, and broader visual measurements remain.
- [ ] Deterministic visual measurements and optional structured vision interpretation.
- [ ] A production Python/FFmpeg adapter consuming the resolved recipe.
- [ ] A shared recipe contract consumed by browser preview and Remotion final render.
- [ ] Preview/final visual parity fixtures and automated image/timing comparisons.
- [ ] Template API, library UI, editor UI, and end-to-end apply workflow.
- [ ] Import/export package format and complete lifecycle operations.
- [ ] Managed/cloud storage. This remains explicitly out of scope until tenant isolation and authorization are designed.

## 3. Implementation inventory

| Area | Current implementation | Status |
|---|---|---|
| Domain contracts | `template_system/models.py` | Implemented; focused tests pass |
| Capability registry | `template_system/capabilities.py` | Implemented as conservative assessment |
| Recipe resolver | `template_system/resolver.py` | Implemented; focused tests pass |
| Public exports | `template_system/__init__.py` | Implemented |
| Contract tests | `tests/test_template_system_contracts.py` | 18/18 passed in user-run focused test |
| Storage | `template_system/storage.py` | Implemented; 18 tests added, execution pending |
| Analysis | `template_system/analysis.py` | Deterministic probe/sampling slice implemented; broader Stage 3 work pending |
| Python/FFmpeg adapter | Not implemented | Pending |
| Remotion adapters/parity | Not implemented | Pending |
| API and UI | Not implemented | Pending |
| Migration/import/export | Not implemented | Pending |

## 4. Technical decisions already established

1. **Canonical intent is renderer-independent.** Domain models describe normalized editing intent; FFmpeg and Remotion details belong in adapters.
2. **Units are explicit.** Positions and dimensions expressed as ratios are canvas-relative; timeline values are seconds; colors are six-digit sRGB hex; font sizes are ratios of canvas height.
3. **Compatibility is honest.** Exact, approximate, and unsupported are distinct. An unsupported requested feature makes a renderer incompatible; it must never be silently dropped.
4. **Resolution is deterministic.** Defaults → template → revision → job overrides → AI adaptation proposals → clip overrides → explicit locks. Lists replace, never append.
5. **AI is advisory.** Adaptations are recorded with accept/reject reasons. Clip overrides and locks cannot be silently overwritten.
6. **Local-first storage only.** Do not enable shared/managed storage before ownership, authorization, isolation, quotas, deletion, and media delivery are implemented and tested.
7. **No premature UI or renderer rewrite.** First prove a persisted recipe and one real renderer vertical slice. Then prove preview/render parity.
8. **Existing generation behavior must remain stable.** The template system must be opt-in and must not alter the current clip-generation path until adapter behavior has regression evidence.

## 5. Current verification and confidence

### Verified

- The user created and activated `D:\\openshorts\\.venv` with Python 3.11.16.
- `python -m pytest tests/test_template_system_contracts.py -v` collected 18 tests.
- Result: **18 passed in 0.35 seconds**.

### Not verified

- The complete backend suite has not been run successfully in a complete project environment.
- No GitHub Actions green run has been established for this feature branch.
- No FFmpeg recipe adapter or real template-driven render exists yet.
- No visual parity claim is justified.
- No Windows installer/runtime conclusion is part of this feature's verification.

The Python 3.12 installer/runtime issue is tracked separately and is not a blocker for continuing repository implementation.

## 6. Completed: Phase 2 local persistence

**Verification (2026-11-12):** GitHub Actions focused job passed for `tests/test_template_system_contracts.py` and `tests/test_template_system_storage.py` on commit `ee6a46f302cfecac935c400ab3697425f5e9f9ed`. The suite contains 18 contract tests and 18 storage tests. The focused job is green. The separate full backend job is red; its exact failures have not yet been extracted from the run log, and the audit already records two pre-existing main-branch failures. The frontend build job passed.



**Implementation update (2026-11-12):** `template_system/storage.py` now provides local-only create/get/list/update/delete operations, canonical manifest serialization, atomic replacement, per-template in-process locks, optimistic revision checks, and asset size/SHA-256 verification. `tests/test_template_system_storage.py` adds coverage for CRUD, malformed manifests, asset corruption, path/symlink escape, failed writes, and concurrent operations. These tests are committed but not yet verified. Stage 2 remains open until they execute successfully and edge cases are reviewed.



Implement a storage boundary that is safe and testable before exposing APIs.

Required behavior:
- Configurable local library root, defaulting to a dedicated template-library directory without changing existing upload/output folders.
- Strict template ID/path validation; all resolved paths must remain beneath the library root.
- One directory per template, with canonical manifest and an assets directory.
- Atomic manifest replacement using a temporary file in the same directory and `os.replace`.
- Per-template in-process synchronization to prevent lost updates in concurrent requests.
- Validate every manifest on read and write using `TemplateDocument`.
- Verify asset existence, declared size, and SHA-256 before accepting a stored document.
- Reject symlinks/path traversal that escape the template directory.
- Preserve the original manifest if a write or validation fails.
- Explicit local-only behavior; no implicit network access or cloud upload.
- Tests for create/get/list/update/delete, malformed manifests, path traversal, corrupt/missing assets, checksum mismatch, atomic-write failure, and concurrent updates.

Do not add API routes until storage behavior and its failure modes are covered.

## 7. Active work: Stage 3 deterministic reference analysis

**Implemented slice:** `template_system/analysis.py` probes local files with FFprobe, validates streams/duration/dimensions/size, records codec/FPS/pixel-aspect/audio/rotation metadata and a streaming SHA-256 fingerprint, detects bounded FFmpeg scene-cut candidates, chooses scene-midpoint plus uniform timestamps, extracts bounded PNG evidence frames, and reports coverage/limitations while retaining partial successes. `tests/test_template_system_analysis.py` covers probe parsing, invalid media, bounds, sampling, frame integrity, collisions, and partial analysis.

**Still required before Stage 3 closes:** staged ingest/copy and cleanup, explicit cancellation/progress integration, deterministic color/layout/motion measurements, attaching frame evidence to the canonical template asset inventory and `TemplateAnalysis`, and end-to-end fixture validation against real FFmpeg binaries.

## 8. Next vertical slice after Stage 3

1. Build a first Python/FFmpeg adapter for a deliberately small subset: canvas, caption styling, hook, and one background mode only where exact behavior can be proven.
2. Run deterministic fixture renders and inspect actual output frames and metadata.
3. Update the capability registry only when adapter behavior is implemented and tested.
4. Add preview/Remotion integration only after the Python slice is stable; parity must be measured, not assumed.

## 8. Change log

- **2026-11-12:** Phase 1 contract suite reported by the user as 18/18 passing under Python 3.11.16. Updated project standing; installer Python 3.12 issue explicitly kept outside this workstream.
