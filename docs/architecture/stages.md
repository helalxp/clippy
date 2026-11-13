# Template Reference System — Stages and Acceptance Gates

**Branch:** `feature/template-reference-system-clean`  
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

**Status: IN PROGRESS — deterministic adapter, storage-backed application service, and local/self-hosted `POST /api/template/apply` integration implemented and CI-tested; remaining renderer capabilities and concurrency hardening are in progress.**

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
- Capability preflight supports canonical captions and hooks/titles; it rejects unsupported overlays, effects, motion, transitions, subject tracking, subtitle/other stream types, and conflicting crop/background combinations.
- `TemplateApplicationService` loads a persisted template, resolves job/clip overrides and explicit locks, applies the FFmpeg adapter, and returns template revision, resolved recipe, recipe hash, source/output fingerprints, compatibility, adaptation decisions, and lock provenance.
- `POST /api/template/apply` is connected to local/self-hosted Clippy jobs. It checks job ownership, serializes against rerender/reframe, renders from the clean canonical clip rather than the currently served derivative, atomically replaces metadata, updates in-memory job state, and archives the new delivery.
- Template manifests and assets use a dedicated `TEMPLATE_LIBRARY_DIR`, explicitly rejected if configured inside `OUTPUT_DIR`, so job cleanup and archival cannot erase the library. Managed/cloud template application is deliberately blocked until durable per-user storage, tenant isolation, backup, and deletion semantics are implemented.

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
- [x] Focused template CI: **109 passed, 0 failed**.
- [x] Full-backend API integration tests verify clean-source selection, metadata and in-memory updates, provenance persistence, managed-mode storage gate, and cleanup after simulated metadata-write failure.

Implemented in this update:
- Shared per-job edit serialization now covers background, watermark, effects-generation, subtitle-add, subtitle-remove, hook, and translation routes in addition to the existing rerender, reframe, and template-apply lock scopes.
- Added focused concurrency tests proving same-job edits serialize, different jobs proceed independently, form-style endpoints resolve their job ID, and all seven decorated routes remain registered with the lock wrapper.

Remaining:
- [ ] Audit any other metadata-mutating routes and add lock coverage where required.
- [x] Confirm concurrency tests and full backend CI are green.
- [x] Failure-injection test verifies metadata replacement failure preserves the last valid manifest/render and removes only the uncommitted output.
- [x] Canonical caption styling is translated through the existing ASS subtitle generator, including transcript remapping for recut clips and optional uploaded font assets.
- [x] Implement template-driven hook/title rendering as a separate capability, with exact compatibility reporting and real FFmpeg timing/placement tests.
- [x] Implement image/watermark overlays with preserved aspect ratio, normalized center anchors, opacity, rotation, and deterministic back-to-front order.
- [x] Add styled text overlays with explicit line breaks, owner-scoped fonts, typography, outline/backing, opacity, normalized layout boxes, and literal text-file input.
- [x] Implement deterministic punch-in, slow-zoom, and pan motion plus time-bounded brightness/contrast/saturation with real FFmpeg fixtures and capability rejection for unsupported values.
- [ ] Implement subject tracking only with a measurable, fixture-tested contract.
- [ ] Prove repeated template application is deterministic and never stacks burned-in derivatives.
- [x] Run the full backend suite green: 1,371 passed, 63 skipped.
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

**Status: PARTIAL.** Local owner-scoped CRUD, raster image and font asset lifecycle endpoints, and versioned package import/export are implemented; library UI and editor workflow remain outstanding.

Objective: expose template management and application through a cohesive user workflow.

Deliverables:
- Authenticated/local-safe template API. List/create/read/update/delete and PNG/JPEG/WebP asset upload/read/delete endpoints are implemented.
- Library browse/search/filter and template details.
- Reference upload and analysis progress/cancellation UI.
- Editor controls mapped directly to canonical schema properties.
- Compatibility panel and preview.
- Apply to one clip or batch, adaptation review, clip overrides, and explicit locks.

Acceptance:
- [x] Local CRUD API is implemented with owner isolation and optimistic revision checks.
- [x] Raster image assets support bounded upload, verified retrieval, and reference-safe deletion; API/storage tests passed in CI run `43310755521`.
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
| 4. Structured interpretation and synthesis | In progress; strict claims, consent-gated Gemini adapter, human review, persistent draft assembly, and capability reports implemented |
| 5. Python/FFmpeg adapter | In progress; real FFmpeg adapter, application service, and local clip-application API implemented |
| 6. Remotion parity | Planned |
| 7. API and UI | Partial; local CRUD and image asset APIs implemented, UI planned |
| 8. Migration and lifecycle | Planned |
| 9. Release readiness | Planned |

**Immediate next action:** finish CI validation of styled text overlays, then move to measurable subject tracking and transitions. Image/watermark overlays, styled text overlays, canonical captions, hook/title rendering, frame-timed punch-in/slow-zoom/pan, and time-bounded brightness/contrast/saturation are implemented in the Python adapter. Keep live Gemini validation opt-in. Managed/cloud template application remains disabled until durable per-user storage and tenant lifecycle controls exist. Stage 5 is not a claim of full template support: tracking, transitions, and Remotion parity remain unfinished.


### Stage 5 update: shared edit locking

The background, watermark, effects-generation, subtitle-add, subtitle-remove, hook, and translation endpoints now acquire the same per-job lock used by rerender, reframe, and template application. The lock encloses the complete operation so metadata is read only after acquiring it and derivative generation cannot interleave with another edit to the same job. Different jobs remain concurrent. Focused tests cover same-job serialization, cross-job independence, form-style endpoint arguments, and route registration for all seven decorated endpoints. CI validation is pending for the code commits `733bec520a7759a5dd92a0d6a194bca4078e8027`.


## Implementation handoff — 2026-11-12

### Committed in this pass

- Added a shared async per-job edit-lock decorator.
- Applied it to background, watermark, effects-generation, subtitle-add, subtitle-remove, hook, and translation endpoints.
- Kept rerender, reframe, template application, and general edit on their existing explicit lock scopes to avoid nested-lock deadlocks.
- Added tests for same-job serialization, independent-job concurrency, form-style job ID extraction, and route registration coverage.
- Updated `implementation.md` and this stage tracker to distinguish implemented local application from the still-missing full template library workflow.

### Next work, in order

1. Run focused locking and template tests in CI, then run the full backend suite and record any baseline or newly introduced failures accurately.
2. Audit remaining lifecycle interactions, especially project restore versus active edit operations, and add a shared lock only if the ownership and concurrency model supports it.
3. Implement image/watermark overlays and measurable motion/effect capabilities with real FFmpeg fixtures, preflight reporting, and deterministic output tests.
4. Reconcile the existing asset lifecycle with overlay rendering, including alpha, sizing, and safe placement.
5. Reconcile browser-preview and final-render Remotion contracts before claiming preview/render parity.
6. Continue with editor UI, migration/import/export, lifecycle/security review, and release gates.

The branch is not release-ready. Managed/cloud template application remains blocked, the library/editor UI and full preview/final parity are not implemented, and text overlays, tracking, transitions, and release lifecycle checks remain outstanding.


## CI reliability review — 2026-11-12

The backend failures were reproduced on the pre-feature `main` workflow: the same two tests failed there (1,226 passed, 30 skipped). They were therefore baseline failures, not regressions introduced by the template system. The source audit found both had real causes, which are corrected in the isolated template branch:
- Duration fallback now consistently uses the five-second minimum range already required by the tests.
- Recut watermark application no longer passes unsupported background arguments to the watermark function.

The four shared edit-lock tests passed in the backend suite. The dedicated template workflow now also includes API and edit-lock tests, so these important integration checks do not rely solely on the broad backend job. Clean-branch Actions run `43309965692` passed: 119 focused template/API/locking tests, 1,327 backend tests passed with 50 skipped, and frontend build passed.


### Verified acceptance evidence

GitHub Actions run [43310755521](https://github.com/helalxp/clippy/actions/runs/43310755521) passed on `feature/template-reference-system-clean`:
- Template/API/edit-lock suite: 123 passed.
- Full backend suite: 1,331 passed, 50 skipped.
- Frontend production build: passed.

The clean branch was created directly from `main` to isolate template work. It has since received implementation, documentation, and local CRUD API commits. The previous feature branch remains untouched because its history contained 205 commits beyond main and included desktop-installer artifacts unrelated to this feature.


## Latest Stage 7 update — local template API

The local API slice now includes:
- `GET /api/templates` for deterministic library listing.
- `POST /api/templates` for asset-free template creation.
- `GET /api/templates/{template_id}` for owner-scoped retrieval.
- `PUT /api/templates/{template_id}` with `expected_revision` conflict protection.
- `DELETE /api/templates/{template_id}` for owned template removal.

The same hashed owner scope is used by template application and library CRUD. Updates, asset uploads, and deletions use revision checks, preventing stale clients from overwriting or removing newer work. Raster image upload accepts PNG, JPEG, and WebP up to 20 MB, checks file signatures and decoded formats, enforces dimension/pixel bounds, generates opaque IDs and safe paths, and stores size/SHA-256 metadata. Verified assets are served through an owner-scoped route. Removing an asset still referenced by a recipe or evidence is rejected. Font uploads and template package import/export are now implemented with bounded validation and integrity checks. Managed mode remains blocked.

Initial API commit: `c208028afa3e453efa27eeed09c071dc42ba3b3a`. CRUD test commit: `ab80b3a82810fb50bc4dec397cc462a7beb39073`. Revision-safety hardening: `c620cb708fbca0502cd2fcd1448e9665fc97fb78`, `e80f0e3d06eb2b6c6f86c96906dcd868158a59db`, `be791d4746e167a78ab8e7d463282ec26ce19be0`, and `6e49046629eca2b41f4cd5a19aae668536c8758d`. Image asset storage/API: `46f4c1b7ed231a084acdd5a8c865adb73f708845`, `9448c8d030549e7fb35d2b59758e92a99b0f1622`, `caf8e21ea26120519df36f5a700264c1098b042a`, `c689c65540aa245b5622ca8f5c64786a674c1eac`, `a5ef16f9b9e5cf5f83e1da5eb2acc1a1742bfed8`, `a6ba2ff34d924679ec7a52ba037881b0c6e1f1de`, `11a50ebd49be06c0249fe5d54aaebf3fc4346560`, and `f92a52ffcec39d5c65fe12dc22bb64c39650968c`. CI run `43310755521` passed the current image asset lifecycle code.


## Latest update — font assets and portable template packages (2026-11-13)

Implemented on feature/template-reference-system-clean:

- The template asset upload endpoint now accepts TrueType and OpenType SFNT fonts in addition to PNG/JPEG/WebP images. Font uploads are bounded to 25 MB and validated for supported signatures, table-directory bounds, duplicate tags, overlapping tables, required metadata tables, and supported outline tables.
- Font asset metadata, opaque storage paths, SHA-256 integrity, revision conflict protection, retrieval, and reference-safe deletion use the existing asset lifecycle. Caption and hook adapters resolve and stage referenced font assets for FFmpeg.
- Added versioned .clippy-template ZIP export/import. Packages carry the canonical template document and its assets. Import validates safe paths, archive entry types, compression, sizes, package version, exact asset inventory, decoded image/font structure, and checksums. Imported templates receive a new local ID and revision 1.
- Added owner-scoped export and import API endpoints.
- GitHub Actions run 43420728540 passed: 149 focused template tests, 1,371 backend tests passed with 50 skipped, and frontend production build passed.

Next vertical slice: validate deterministic motion/effect rendering, then define text-overlay typography and backing semantics. Subject tracking needs a separate measurable contract. Keep preview/Remotion parity as a later explicit gate.


## Latest update — template-driven captions (2026-11-13)

Implemented on feature/template-reference-system-clean:

- Python/FFmpeg now maps the canonical CaptionRecipe into the existing ASS generator. It supports font family, normalized font size, text/highlight/outline colors, outline/shadow, word highlighting, reveal, uppercase, and top/middle/bottom positioning.
- Top/bottom positions use canonical safe-area margins. Arbitrary x/y anchors are rejected. Non-default max_lines values are reported as approximate rather than silently claimed as exact.
- Template application passes the clip's saved transcript into the renderer. Recut EDL segments are remapped to clip-relative time, and saved user-edited caption words take precedence when present.
- Referenced font assets are resolved from owner-scoped template storage and staged for FFmpeg. Temporary ASS and font files are removed after render.
- Missing transcript/word data causes a clear application failure when captions are enabled; the adapter never silently drops requested captions.
- GitHub Actions run 43421896913 passed on the current branch head: 154 focused template tests, 1,371 backend tests passed with 55 skipped, and frontend build passed.

Implemented in this update:
- Canonical hook/title rendering is supported by the Python/FFmpeg adapter through a dedicated drawtext translator.
- Hook text is written to a temporary UTF-8 text file rather than interpolated into the FFmpeg filter graph, and drawtext expansion is disabled so percent-based filter expressions remain literal user copy. The adapter supports uploaded font assets, optional solid background backing, normalized top/center/bottom/custom placement, canonical top/bottom safe margins, timed visibility, and none/fade/slide_up/spring/pop entrance behavior.
- Hook font assets are resolved independently from caption font assets and staged only for the render. Temporary text/font files are cleaned on success and failure.
- Hook rendering is applied after captions so it remains a distinct top layer.
- Real FFmpeg fixtures verify visible and expired hook frames across original, blur, and solid background paths. Unit coverage verifies text-file isolation and uploaded-font pass-through.
- GitHub Actions run `43425496250` passed on commit `7a46f6d1d257ed3132a9b440d27a52bfe906d5df`: **162 focused template tests passed**, **1,371 backend tests passed with 63 skipped**, and the frontend production build passed.

Implemented in this update:
- The Python/FFmpeg adapter renders ordered PNG, JPEG, and WebP image/watermark overlays from owner-scoped template assets.
- Overlay anchors are normalized center points; width is relative to canvas width, source aspect ratio is preserved, opacity multiplies source alpha, and rotation is applied around the center.
- Recipe order is back-to-front. Overlays are composited before captions and hook/title layers and work with original, blur, and solid background paths.
- The application service resolves image assets from the template's own asset store. Missing, symbolic-link, non-image, or unsupported-extension assets fail safely.
- Text overlays remain explicitly unsupported because the current recipe has no font, size, color, backing, or line-layout fields.

Motion/effect implementation added after the image-overlay milestone and verified in CI:
- Added frame-timed `punch_in`, `slow_zoom`, and `pan` recipes. Punch-in ramps over the first 20% of its interval and holds; slow zoom ramps linearly; pan moves from center to a normalized target while zoomed.
- Added time-bounded brightness, contrast, and saturation effects using FFmpeg EQ.
- Motion and effects are applied before image overlays, captions, and hook/title layers. Recipe timeline values are translated to output-frame indices using the configured FPS.
- Capability checks reject unsupported effect zoom/crop-center values and EQ values outside the exact FFmpeg range. Motion/effect intervals starting after the clip ends fail clearly.
- Added preflight and real-render regression tests for timed motion, timed brightness, and unsupported effect values.
- GitHub Actions run [43427264281](https://github.com/helalxp/clippy/actions/runs/43427264281) passed: **166 focused template tests**, **1,371 backend tests with 67 skipped**, and frontend production build.

Remaining in Stage 5: subject tracking, transitions, render-provenance hardening, deterministic repeated-application checks, and CI verification of the styled text-overlay slice. Stage 6 Remotion preview/final parity remains a separate release gate.


## Latest Stage 5 update: styled text overlays

Implemented, with CI validation pending:
- Extended the canonical overlay schema for font family or uploaded font, font size, font/outline colors, outline width, optional backing, opacity, explicit line count, line spacing, alignment, and normalized text-box dimensions/center anchors.
- Text and image/watermark layers now composite in the same recipe order. Captions and hook/title remain above the overlay stack.
- User text is staged in UTF-8 files and passed to FFmpeg drawtext with expansion disabled. Uploaded overlay fonts are resolved from owner-scoped storage and protected from deletion while referenced.
- Explicit line breaks and max_lines are enforced. Text rotation is rejected. A conservative width estimate marks long lines approximate rather than silently shrinking or wrapping them.
- Added schema, asset-lifecycle, service, text-injection, and real-render tests.
