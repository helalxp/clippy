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

**Status: COMPLETE; real FFmpeg integration and focused CI PASS.**

Objective: turn a local reference video into a traceable analysis record without pretending unmeasured properties were detected.

Implemented deliverables:
- Local staging into unique, permission-restricted directories with bounded streaming copy, SHA-256, atomic file placement, progress callbacks, cancellation checks, and ownership-checked cleanup.
- FFprobe technical metadata: codec, duration, dimensions, frame rate, pixel aspect ratio, pixel format, audio presence/codec/channels/sample rate, rotation, file size, and source fingerprint.
- FFmpeg scene-cut candidates with a hard boundary cap and bounded subprocess timeout.
- Deterministic scene-midpoint and uniform fallback sampling, capped at 64 frames.
- PNG evidence frames with timestamp, dimensions, byte size, and SHA-256.
- Pixel-level measurements: dominant color palette, luminance mean/standard deviation, saturation, edge density, and adjacent-sample visual change.
- Conversion into canonical `TemplateAnalysis`, `TemplateAsset`, and evidence records.
- Coverage and limitations reporting, including partial results when scene detection, frame extraction, or visual measurement fails.
- Progress callbacks and cancellation checks between major stages and individual frame operations.

Verification:
- [x] Safe local staging, bounded copy, SHA-256 fingerprint, and ownership-checked cleanup.
- [x] FFprobe stream metadata validation without inventing missing values.
- [x] Bounded scene detection and sample selection.
- [x] Sampled frame evidence with timestamps, dimensions, and checksums.
- [x] Deterministic color, luminance, saturation, edge-density, and inter-sample pixel-change measurements.
- [x] Canonical template evidence and asset conversion.
- [x] Partial results and limitations retained when optional analysis steps fail.
- [x] Progress callbacks and safe-boundary cancellation hooks.
- [x] Real FFmpeg-generated two-scene fixture verifies the known cut within 200 ms, samples real PNG frames, measures them, converts the evidence, persists the template and its assets, and cleans up the staged source.
- [x] Focused CI: **69 passed, 0 failed**.
- [x] No model calls or media uploads occur in this deterministic stage.

Scope limits carried forward:
- Pixel difference is not optical flow or subject-motion detection.
- Edge density is not semantic subject/layout understanding.
- Scene-cut candidates are not yet a validated editorial-cut classifier.
- Durable API/UI job orchestration and resume-after-restart belong to the API/lifecycle stage.

## Stage 4 — Structured interpretation and template synthesis

**Status: IN PROGRESS — provider-neutral contract, consent-gated Gemini adapter, human review, deterministic synthesis, and persistent draft assembly implemented; live-provider quality validation remains.**

Objective: convert measurements and optional vision interpretation into a reviewable draft template.

Implemented deliverables:
- Strict provider-neutral response schema and persisted domain models with a closed allowlist of canonical recipe leaf paths and strict scalar types.
- Every claim requires qualitative confidence, observation/inference classification, rationale, and one or more exact sampled asset/timestamp references. The template document persists the interpretation and verifies each evidence timestamp against its frame asset.
- Evidence files are path-contained, size-bounded, and SHA-256 verified before they are passed to a provider.
- Frame count and total evidence bytes are bounded; only selected PNG frames are sent, never the source video.
- Optional Gemini vision adapter uses structured JSON output and the existing `GEMINI_API_KEY` / `GEMINI_MODEL` configuration. It is opt-in and makes no network call on import or construction with an injected client.
- Provider claims are forcibly marked pending; a model cannot self-approve, reject, or mark its own claim as a human correction.
- Deterministic draft synthesis applies only accepted/corrected claims; pending and rejected claims do not mutate the recipe.
- Reviewed claims convert into canonical resolver proposals, preserving clip-override and explicit-lock precedence.
- Draft assembly persists deterministic analysis, interpretation claims, reviewer provenance, timestamped frame assets, synthesized recipe, and all three renderer compatibility snapshots.

Remaining deliverables:
- Live opt-in Gemini smoke test and provider token/cost telemetry.
- Representative-reference quality evaluation and calibration of qualitative confidence.
- Representative-reference quality evaluation, confidence calibration, and expanded interpretation of transitions/overlays/text where evidence supports it.

Acceptance:
- [x] Model output is schema-validated and cannot introduce arbitrary recipe fields.
- [x] Claims without exact supplied evidence references are rejected.
- [x] Confidence is qualitative only; no numeric confidence is emitted.
- [x] Capability incompatibilities are attached to the synthesized draft for Python/FFmpeg, Remotion preview, and Remotion render.
- [x] Model claims remain pending; accepted/corrected claims are the only ones applied, and the resolver preserves clip overrides and locks.

## Stage 5 — Python/FFmpeg application vertical slice

**Status: IN PROGRESS — deterministic adapter, storage-backed application service, and `POST /api/template/apply` local/self-hosted integration implemented; end-to-end API verification and remaining capabilities are in progress.**

Objective: apply a validated recipe subset to a clean canonical clip, preserve source media, and reject unsupported properties instead of silently ignoring them.

Implemented:
- Exact canvas dimensions and frame rate.
- Deterministic cover crop, contain framing, and manually anchored crop.
- Original/black matte, blurred duplicate background, and solid-color contain background.
- H.264 MP4 output and AAC audio transcoding.
- FFprobe verification of dimensions, frame rate, duration, video stream count, and audio stream preservation.
- Atomic temporary-output replacement. Failed renders do not replace an existing output.
- Progress callbacks, cancellation before and during render, bounded runtime, and temporary-file cleanup.
- Refusal of source/output path aliases, including hard links, so a render cannot overwrite its clean source.
- Capability preflight rejects unsupported captions, hooks, overlays, effects, motion, transitions, subject tracking, subtitle/other stream types, and conflicting crop/background combinations.
- `TemplateApplicationService` loads a persisted template, resolves job/clip overrides and explicit locks, applies the FFmpeg adapter, and returns template revision, recipe hash, source/output fingerprints, compatibility, adaptation decisions, and lock provenance.

Verification:
- [x] Adapter consumes the canonical validated `TemplateRecipe`.
- [x] Supported canvas/framing/background combinations pass preflight.
- [x] Unsupported requested properties fail with a precise compatibility report.
- [x] Real FFmpeg fixtures render cover, blur, solid, and original-matte outputs.
- [x] Output dimensions, frame rate, duration, and audio stream preservation are verified.
- [x] Pixel-level frame assertions verify solid-background color, contain geometry, and manual crop-anchor behavior.
- [x] Subtitle streams are rejected rather than silently discarded.
- [x] Failed renders preserve existing destinations and clean temporary output.
- [x] Source path and hard-link aliases cannot be used as the destination.
- [x] Application-service tests verify stored-template lookup, resolver precedence/locks, recipe hash, and render provenance.
- [x] Focused CI previously passed **107 tests**; additional source-overwrite and provenance tests are queued with the latest commits.\n- [ ] End-to-end API integration and managed-mode storage-gate tests are added and await the full backend CI run.

Remaining:
- [ ] Integrate the application service into Clippy's existing job/editor API with job ownership checks, per-job serialization, and atomic metadata updates.
- [ ] Apply templates from the clean canonical clip, not from a previously styled delivery derivative.
- [ ] Persist recipe hash, template revision, source/output fingerprints, and applied settings with each clip output.
- [ ] Implement caption styling and hook/title adapters one capability at a time.
- [ ] Implement overlays only after asset sizing, alpha, and normalized-position semantics are validated.
- [ ] Implement subject tracking only with a measurable, fixture-tested contract.
- [ ] Prove repeated template application is deterministic and never stacks burned-in derivatives.
- [ ] Run the full backend suite green after the two pre-existing baseline failures are resolved.

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
| 3. Deterministic analysis | Complete; 69 focused tests pass, including real FFmpeg ingest-to-persisted-template fixture |
| 4. Structured interpretation and synthesis | In progress; strict claims, consent-gated Gemini adapter, human review, persistent draft assembly, and capability reports implemented |\n| 5. Python/FFmpeg adapter | In progress; real FFmpeg adapter and storage-backed application service implemented, existing API integration pending |
| 6. Remotion parity | Planned |
| 7. API and UI | Planned |
| 8. Migration and lifecycle | Planned |
| 9. Release readiness | Planned |

**Immediate next action:** integrate the isolated FFmpeg adapter into the existing Clippy render/editor API, add recipe provenance and golden-frame checks, while keeping the live Gemini quality test opt-in and consent-gated. The latest completed focused CI suite reports 107 passing tests; two additional regression tests are awaiting CI. The focused template CI job is green; the full backend job remains red only on the two baseline failures documented in `implementation.md`. Do not begin broad UI work or claim end-to-end template functionality until Stages 2–5 produce a real, reproducible Python/FFmpeg render.
