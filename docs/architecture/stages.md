# Template Reference System — Stages and Acceptance Gates

**Branch:** `feature/template-reference-system`  
**Planning status:** Active staged implementation  
**Rule:** A stage is complete only when its exit criteria are evidenced. Committed code or a passing unit test subset alone does not prove an end-to-end feature.

## Stage 0 — Repository and architecture audit

**Status: COMPLETE for GitHub-source inspection; local-only checks intentionally excluded from this workstream.**

Scope:
- Audit the legacy reference-template prototype and branch divergence.
- Trace Python/FFmpeg generation and editing paths.
- Trace browser preview and Remotion final-render paths.
- Identify schema/composition drift, capability gaps, and persistence risks.
- Record current CI baseline failures.

Evidence:
- [Phase 0 audit](./TEMPLATE_REFERENCE_SYSTEM_PHASE0_AUDIT.md)
- [System specification](./TEMPLATE_REFERENCE_SYSTEM_SPEC.md)

Exit:
- [x] Existing prototype audited; not merged wholesale.
- [x] Separate render paths documented.
- [x] Remotion preview/render drift confirmed.
- [x] Baseline CI failures recorded.
- [x] Target architecture and critical risks documented.

## Stage 1 — Canonical domain foundation

**Status: IMPLEMENTED; focused contract suite PASS.**

Deliverables:
- Strict, versioned template and recipe models.
- Asset and evidence contracts.
- Renderer capability registry.
- Deterministic resolver with adaptation decisions, clip overrides, locks, and stable recipe hash.
- Focused contract tests.

Evidence:
- `template_system/models.py`
- `template_system/capabilities.py`
- `template_system/resolver.py`
- `tests/test_template_system_contracts.py`
- [Phase 1 foundation notes](./TEMPLATE_REFERENCE_SYSTEM_PHASE1_FOUNDATION.md)

Verification:
- [x] User executed focused test module under Python 3.11.16.
- [x] **18 passed, 0 failed, 0.35s (2026-11-12).**
- [ ] Full backend suite and CI regression signal verified.
- [ ] Schema contract reviewed against the first real adapter.

Stage 1 is complete as a domain-contract milestone, not as a usable product feature.

## Stage 2 — Local persistence and asset integrity

**Status: COMPLETE; focused CI PASS.**

Objective: persist templates safely and reproducibly before adding public API or UI.

Deliverables:
- Local storage adapter with configurable root.
- Atomic manifest writes and per-template synchronization.
- Strict read/write validation through the canonical models.
- Asset inventory verification (path containment, size, SHA-256, media type).
- CRUD primitives and deterministic listing.
- Failure-safe behavior that preserves the last valid manifest.
- Automated storage tests.

Acceptance:
- [x] Local storage methods for create, load, update, list, and delete are implemented.
- [x] CRUD behavior passes the new automated storage test module.
- [x] Invalid manifests are rejected on read; atomic replacement preserves the prior manifest if writing fails.
- [x] Failure-preservation tests pass in CI.
- [x] Template ID/path containment and symlink checks are implemented.
- [x] Path/symlink adversarial tests pass in CI.
- [x] Asset byte length and SHA-256 are verified on create and read.
- [x] Asset-integrity tests pass in CI.
- [x] Manifest writes use same-directory temp files, fsync, and atomic replace.
- [x] Simulated write-failure test passes.
- [x] Thread locks, OS-backed file locks, and expected-revision compare-and-swap are implemented.
- [x] Concurrent thread and cross-process create/update tests pass.
- [x] Storage is explicitly rooted by caller and does not reference upload/output directories.

## Stage 3 — Reference ingest and deterministic analysis

**Status: IN PROGRESS — deterministic probe/sampling foundation implemented; ingest orchestration and visual measurements remain.**

Objective: turn a local reference video into a traceable analysis record without pretending unmeasured properties were detected.

Deliverables:
- Safe staged ingest and media validation.
- FFprobe metadata collection.
- Scene-aware bounded frame sampling.
- Deterministic shot/cut, color, layout, and motion measurements where reliable.
- Evidence assets with timestamps and provenance.
- Resumable staged analysis state and cancellation boundaries.
- Coverage and limitation reporting.

Acceptance:
- [ ] Invalid or unsupported media fails with actionable errors.
- [x] Sampling count (max 64), frame dimensions, frame bytes, source size, source duration, scene-cut count, and subprocess timeouts are bounded.
- [x] Sampled frames carry source timestamps, relative paths, dimensions, byte sizes, and checksums.
- [x] Probe/sample records convert into canonical `TemplateAnalysis` evidence and `TemplateAsset` records.
- [x] Scene-detection or individual frame-sampling failures produce partial results and preserve successful evidence.
- [ ] Unmeasured properties remain unknown, not fabricated.
- [x] This deterministic stage makes no model calls and uploads no media.

## Stage 4 — Structured interpretation and template synthesis

**Status: PLANNED.**

Objective: convert measurements and optional vision interpretation into a reviewable draft template.

Deliverables:
- Strict structured output contract for semantic interpretation.
- Evidence-linked claims, confidence/uncertainty, and limitations.
- Deterministic synthesis from measurements and model suggestions.
- Conflict handling and human correction provenance.
- Capability report for each target renderer.

Acceptance:
- [ ] Model output is schema-validated and cannot introduce arbitrary recipe fields.
- [ ] Claims without evidence are rejected or marked as inference.
- [ ] Confidence is not presented with false numeric precision.
- [ ] Capability incompatibilities are visible before a template is marked ready.
- [ ] User edits remain authoritative and are preserved as corrections.

## Stage 5 — Python/FFmpeg application vertical slice

**Status: PLANNED; first production adapter target.**

Objective: apply a resolved template recipe to an existing clip through the production-critical Python/FFmpeg path.

Initial supported slice:
- Canvas/output dimensions.
- One caption styling path.
- Hook/title overlay.
- One explicitly implemented background treatment.
- Recipe hash and template provenance recorded with render output.

Acceptance:
- [ ] Adapter consumes only validated `TemplateRecipe` data.
- [ ] Unsupported requested properties fail preflight with a precise compatibility report.
- [ ] Rendering starts from a stable clean source/base rather than chaining already-burned derivatives.
- [ ] Output is playable and has expected dimensions, duration, and streams.
- [ ] Fixture frames verify placement, colors, typography, and timing.
- [ ] Existing non-template generation and editing tests remain unchanged/pass.
- [ ] Reapplying the same recipe does not stack overlays or compound effects.

## Stage 6 — Preview and Remotion parity

**Status: PLANNED.**

Objective: make browser preview and final Remotion rendering consume the same recipe semantics.

Deliverables:
- Shared/generated TypeScript contract from the canonical schema, or a rigorously contract-tested equivalent.
- Consolidated composition source or shared composition package.
- Explicit adapters for preview and Remotion final render.
- Deterministic fixture renders and visual comparison tooling.

Acceptance:
- [ ] Both paths accept the same versioned recipe shape.
- [ ] Caption grouping, font resolution, normalized coordinates, timing, and animation semantics are aligned.
- [ ] Unsupported differences are reported, never hidden.
- [ ] Golden-frame and timing tests pass within documented tolerances.
- [ ] No preview/final parity claim is made without measured evidence.

## Stage 7 — API, library, and visual editor

**Status: PLANNED.**

Objective: expose template management and application through a cohesive user workflow.

Deliverables:
- Authenticated/local-safe template API.
- Library browse/search/filter and template details.
- Reference upload and analysis progress/cancellation UI.
- Editor controls mapped directly to canonical schema properties.
- Compatibility panel and preview.
- Apply to one clip or batch, adaptation review, clip overrides, and explicit locks.

Acceptance:
- [ ] UI controls round-trip without losing schema fields.
- [ ] User can review analysis evidence and limitations.
- [ ] User can save, duplicate, rename, edit, and apply templates.
- [ ] Batch failures do not discard completed clips.
- [ ] Template application never silently mutates the source template.
- [ ] User-visible errors and progress reflect actual backend state.

## Stage 8 — Migration, import/export, and lifecycle hardening

**Status: PLANNED.**

Objective: make templates portable, recoverable, and maintainable.

Deliverables:
- Explicit migration from legacy v1 reference-template manifests.
- Versioned portable package format with checksums.
- Import validation and safe extraction.
- Duplicate, archive, restore, delete, asset cleanup, and revision history.
- Backup/recovery and corruption tests.

Acceptance:
- [ ] Legacy manifests migrate without losing source provenance.
- [ ] Failed migration leaves originals recoverable.
- [ ] Import rejects path traversal, archive bombs, invalid media, and checksum mismatches.
- [ ] Export/import round-trip preserves semantic recipe and assets.
- [ ] Deletion removes only owned template data.
- [ ] Revision history and restore behavior are deterministic.

## Stage 9 — Release readiness and managed-storage decision

**Status: PLANNED / OUT OF CURRENT IMPLEMENTATION SCOPE.**

Objective: verify product readiness and decide whether a managed library can be safely introduced.

Acceptance:
- [ ] End-to-end reference-to-template-to-render workflow passes on supported Windows hardware.
- [ ] Performance, memory, disk, and cancellation behavior are measured.
- [ ] Security review covers uploads, archives, paths, assets, and ownership.
- [ ] Documentation, diagnostics, and recovery guidance are complete.
- [ ] Managed storage remains disabled unless tenant isolation, authorization, quotas, deletion, and media delivery are independently approved and tested.

---

## Current milestone summary

| Stage | Status |
|---|---|
| 0. Audit | Complete |
| 1. Domain foundation | Implemented; 18/18 focused tests pass |
| 2. Local persistence | Complete; focused CI green |
| 3. Deterministic analysis | In progress; staging, probing, sampling, visual measurements, evidence conversion, progress/cancellation hooks implemented |
| 4. Python/FFmpeg adapter | Planned |
| 5. Remotion parity | Planned |
| 6. API and UI | Planned |
| 7. Migration and lifecycle | Planned |
| 8. Release readiness | Planned |

**Immediate next action:** validate the full ingest-to-evidence pipeline with representative real-media fixtures, measure scene-boundary and visual-metric quality, and wire the progress/cancellation hooks into an actual analysis job lifecycle. The focused template CI job now includes analysis tests; the separate full backend job remains red and must be triaged independently. Do not begin broad UI work or claim end-to-end template functionality until Stages 2–5 produce a real, reproducible Python/FFmpeg render.
