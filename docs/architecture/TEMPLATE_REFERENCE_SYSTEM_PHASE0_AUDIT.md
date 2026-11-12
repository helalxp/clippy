# Template Reference System — Phase 0 Repository Audit

**Repository:** `helalxp/clippy`  
**Audit baseline:** `main` at `0d8fe1fa4f9d8493adf2b8e6aff2bdaf6e64b4eb`  
**Feature branch:** `feature/template-reference-system`  
**Audit date:** 2026-11-12  
**Status:** Remote source audit in progress; local Windows checkout and runtime behavior not yet verified.

## Executive summary

The current repository contains substantial, useful video-editing capabilities, but the Template Reference System cannot safely be implemented as a thin layer over the current UI or Remotion props.

The highest-impact finding is that the project has **two separate Remotion composition trees**:
- Browser preview imports `dashboard/src/remotion/compositions/ShortVideo.tsx`.
- The render service bundles the root `remotion/` tree.

The trees have diverged. For example, the dashboard subtitle renderer includes configurable block grouping, word spacing, reveal behavior, dimming, uppercase, shadow, and highlight-text handling that the root renderer does not fully implement. This means a preview and a server-side Remotion render can interpret the same caption configuration differently.

There is a second rendering boundary: the primary clip-generation and editing pipeline renders through Python/FFmpeg, including `reframe_v2.py`, `subtitles.py`, `hooks.py`, and `recut.py`. The Remotion render service is a separate rendering route, not the single renderer used by the full clip-generation pipeline. A template must not be implemented against one path and assumed to control all output paths.

**Architecture direction:** establish a canonical, versioned editing recipe and capability contract; make each supported renderer an explicit adapter; then converge or retire duplicated implementations based on measured parity and quality. Do not begin with a large UI implementation.

## 1. Branch and integration baseline

At audit time:
- `main` head: `0d8fe1fa4f9d8493adf2b8e6aff2bdaf6e64b4eb`.
- `feature/template-reference-system` is one commit ahead of `main`, with only the specification added.
- `windows-native-migration` compares as 14 commits ahead and 140 commits behind `main`.
- The native migration branch contains Tauri/Rust desktop files, runtime manifest/bootstrap work, renderer path changes, local model settings, and the reference-template prototype.
- The `CLIPPY_MASTER.md` on `windows-native-migration` explicitly describes that branch as divergent and warns that its desktop scaffold is not proof of a production-ready installer.

This is a major integration constraint. The desired product is Windows-first, but the current feature branch is based on current `main`, which does not contain the Tauri desktop layer. The old migration branch cannot be merged wholesale into current `main` because it is 140 commits behind. The correct path is to reconcile the user's current local Windows-native worktree and selectively port/rebase the desktop integration onto the current source baseline. Do not make a speculative branch switch or destructive merge.

**Local checkout limitation:** this audit reads the GitHub repository. It cannot inspect unpushed local changes, the current local branch, working-tree modifications, locally generated installer artifacts, or execute Windows builds. Those must be checked in the user's active checkout before implementation commits.

## 2. Existing rendering architecture

### 2.1 Python/FFmpeg pipeline

Relevant source:
- `main.py`: clip render routing, final output processing, watermark application.
- `reframe_v2.py`: downscaled analysis and FFmpeg-native rendering, with scene-specific strategies and manual crop overrides.
- `recut.py`: edited segment concatenation, optional reframing, watermark/caption reapplication.
- `subtitles.py`: word collection, caption presets, ASS/SRT generation and subtitle style handling.
- `hooks.py`, `hook_placement.py`, `hook_grounding.py`: hook rendering, placement, and grounding.
- `layout_picker.py`, `layout_ranges.py`, `split_layout.py`, `screencast_layout.py`, `camera_inset.py`, `punch_in.py`: layout and motion/framing support.

Observed behavior:
- `main.render_clip` delegates vertical/square processing to `process_video_to_vertical`.
- `process_video_to_vertical` prefers `reframe_v2.render` unless `REFRAME_ENGINE=v1`, with a guarded fallback to the older frame loop.
- Forced framing or manual crop overrides do not silently fall back to v1 because that would discard explicit user corrections.
- The pipeline has a separate free-plan delivery watermark flow that preserves a clean copy.
- Caption burning uses the existing transcript and ASS for karaoke-style word highlighting; it also handles layout seam ranges for split layouts.
- Recutting preserves/remaps layout ranges and re-applies captions from the transcript where requested.

Assessment: the Python/FFmpeg path is the production-critical baseline for existing generated clips. It contains mature domain behavior and should not be replaced without corpus-based comparisons. It also has a number of visual capabilities not represented by the current Remotion composition contract.

### 2.2 Browser preview and Remotion render service

Relevant source:
- `dashboard/src/components/RemotionPreview.jsx`
- `dashboard/src/remotion/compositions/ShortVideo.tsx`
- `dashboard/src/remotion/compositions/Subtitles.tsx`
- `dashboard/src/remotion/compositions/VideoEffects.tsx`
- `dashboard/src/remotion/lib/types.ts`
- `remotion/src/Root.tsx`
- `remotion/src/compositions/ShortVideo.tsx`
- `remotion/src/compositions/Subtitles.tsx`
- `remotion/src/compositions/VideoEffects.tsx`
- `remotion/src/lib/types.ts`
- `render-service/src/server.ts`
- `render-service/src/render-worker.ts`
- `render-service/src/bundle.ts`

Observed:
- `RemotionPreview.jsx` imports the dashboard-local composition and constructs 1080x1920, 30fps props.
- `render-service/src/bundle.ts` bundles the root `remotion/` project.
- The render service uses `selectComposition` and `renderMedia` with the root composition.
- `ShortVideo` layers base video, effects, subtitles, and hook.
- The render request schema uses `z.any()` for subtitle, hook, and effect payloads, so nested config validation is permissive at the HTTP boundary.
- The renderer stores render jobs in an in-memory Map and starts work fire-and-forget. This service has no durable render-job store in the inspected implementation.
- The renderer's own status API exposes progress, output URL, and error, but the inspected server contract does not expose cancellation or durable recovery.

### 2.3 Confirmed composition drift

The two `Subtitles.tsx` implementations are not equivalent:
- Dashboard version passes `maxChars` and `maxDurationMs` into caption grouping; root version uses default grouping.
- Dashboard version joins words with measured spaces in a shared text container; root version uses flex gaps.
- Dashboard version implements `reveal`, `baseOpacity`, `uppercase`, `shadow`, and `highlightTextColor`; root version lacks some or all of those controls.
- Dashboard's `SubtitleStyle` and `SubtitleConfig` contain additional fields that are not represented in the root renderer's TypeScript interface/schema.
- Dashboard's Zod schema itself also does not include every optional interface field, so even that tree has type/schema drift.

This is a concrete preview/render parity defect, not merely a theoretical concern. Before a full template editor is built, the project needs one authoritative recipe and shared rendering semantics. Either share a single composition package or generate/build both targets from the same source. Any unavoidable renderer differences must be explicit capabilities with visual regression coverage.

## 3. Current editing APIs and persistence behavior

Relevant endpoints in `app.py`:
- `POST /api/clip/rerender`
- `POST /api/clip/background`
- `POST /api/clip/watermark`
- `POST /api/clip/reframe`
- `POST /api/subtitle`
- `POST /api/subtitle/remove`
- `POST /api/hook`
- `POST /api/render` and `GET /api/render/{render_id}`

Observed:
- The clip editor has a recipe/EDL contract and chooses a fast recut path or a source-based reframing path.
- `/api/clip/rerender` serializes rerenders per job and persists clip recipe metadata.
- `/api/clip/reframe` stores manual scene crop overrides and invokes the source-based recut path.
- Background and custom watermark endpoints each create a new derivative file and update the current clip's metadata.
- The background endpoint tracks a source filename to avoid repeatedly applying a background effect to a previous background output.
- The custom watermark endpoint burns an uploaded PNG/WebP onto the current delivered clip and stores normalized position/size metadata.
- Subtitle and hook endpoints strip prior burned overlays where possible, render the new overlay, and reapply captions where needed.
- Multiple endpoints independently update the same metadata JSON and in-memory clip records. The rerender path has a per-job lock, but a unified edit transaction/recipe layer is not evident across all edit endpoints.
- Some editing operations are derivative-file based rather than a unified non-destructive recipe rendered from a stable clean base.

Assessment: preserve the user-visible editing capabilities, but the template system should not simply chain the existing endpoints. A template should resolve into one effective recipe, render from a known clean source/base where possible, and commit output + metadata atomically. That avoids overlay stacking, order-dependent results, and lost concurrent metadata updates.

## 4. Existing template prototype

The reference-template implementation is not present on current `main`. It is present on the old reference/migration branch.

Prototype files:
- `reference_templates.py`
- `dashboard/src/components/ReferenceTemplateLibrary.jsx`
- `tests/test_reference_templates.py`
- `reference_templates/<template-id>/manifest.json`
- API routes in `app.py`

The inspected API accepts a local video upload, creates a manifest and poster, lists/gets templates, and allows limited metadata/override updates. It blocks managed mode pending account-scoped storage. The analysis is primarily technical metadata and hard-cut/pacing statistics; visual style, typography, captions, framing, transitions, motion, and editorial patterns are not yet analyzed into an applicable render recipe.

Decision: use the prototype only as a source of ideas and a migration fixture. Do not merge the branch wholesale or treat its v1 manifest as the target architecture.

## 5. Baseline CI findings

Latest inspected `main` workflow run:
- Run: `42857338133`
- Frontend build: passed.
- Backend tests: failed.
- Backend result: **1,226 passed, 30 skipped, 2 failed**.

Failures:
1. `tests/test_generation_controls.py::TestClipDurationBounds::test_env_overrides_apply`: expected environment override bounds `(20.0, 30.0)`, actual result `(20.0, 25.0)`.
2. `tests/test_recut.py::TestPerformRecut::test_source_path_reframes_and_watermarks`: injected test watermarker lambda does not accept the newly supplied `backdrop_type` keyword argument.

These failures are on the current `main` baseline and are not caused by the template specification commit. They should be tracked as baseline issues and fixed in their own scoped changes or explicitly documented as known failures before the template work uses CI as a regression signal. Do not silently change unrelated product behavior while implementing templates.

## 6. Key risks and architecture decisions

| Risk | Severity | Decision |
|---|---|---|
| Two diverged Remotion trees | Critical | Converge on one composition source or generated shared package |
| Python/FFmpeg and Remotion have separate semantics | Critical | Canonical recipe + explicit renderer adapters and capability report |
| Caption preset duplication across Python and React | High | Single schema/preset source with generated or contract-tested consumers |
| Per-endpoint derivative chains | High | Resolve non-destructive template recipe from clean base and commit atomically |
| Metadata writes across independent edit routes | High | Shared per-job edit transaction/locking and atomic persistence |
| Remotion renderer in-memory job state | Medium/High | Durable job lifecycle or explicitly constrain scope and recoverability |
| Weak nested render request validation | High | Strict typed schemas, bounds, and compatibility validation |
| Legacy template branch divergence | High | Selective port only; no wholesale merge |
| Windows-native branch divergence from main | Critical | Reconcile local desktop work and selectively integrate before implementation |
| Existing CI red baseline | High | Record baseline and isolate unrelated repairs |

## 7. Proposed target architecture

1. **Canonical template schema:** versioned typed schema for template identity, revisions, provenance, assets, analysis evidence, recipe, and compatibility.
2. **Canonical render recipe:** normalized time, coordinate, color, font, and layer semantics shared across editor and backend.
3. **Capability registry:** each renderer declares exact/approximate/unsupported capabilities; no silent degradation.
4. **Analysis pipeline:** deterministic media probing/sampling/measurements first; optional structured vision interpretation with evidence and confidence.
5. **Application resolver:** deterministic precedence for defaults, template revision, job settings, clip overrides, and explicit locks.
6. **Renderer adapters:** Python/FFmpeg and Remotion consume the same resolved recipe. The long-term choice to consolidate or retire one renderer is made only after visual and performance benchmarks.
7. **Edit transaction:** output artifacts and metadata are committed together with rollback/cleanup behavior.
8. **Local-first template storage:** safe per-user storage, atomic writes, schema migration, asset validation, and explicit export/import package format. Managed sharing remains disabled until tenant isolation is implemented.

## 8. Phase 0 exit criteria

Before Phase 1 implementation:
- [x] Inspect the existing template prototype.
- [x] Compare the prototype branch with current `main`.
- [x] Inspect core Python/FFmpeg render and recut paths.
- [x] Inspect both Remotion composition trees and confirm drift.
- [x] Inspect editing endpoints and associated regression tests.
- [x] Inspect latest main CI and capture exact failing tests.
- [ ] Inspect the user's current local branch, dirty/clean working tree, and unpushed Windows installer work.
- [ ] Reconcile Windows-native application/runtime changes with current main without discarding either side.
- [ ] Run the current baseline test/build commands in the actual target checkout.
- [ ] Create representative source clips and visual reference fixtures for preview/render parity.

The checked items are based on GitHub source inspection. The unchecked items require the actual local Windows checkout or executable environment.

## 9. Next implementation gate

Do not start a broad template editor or replace the renderer yet.

The next technical deliverable should be:
- a shared recipe/schema proof-of-concept;
- a parity test that renders the same small recipe through browser preview and the final renderer;
- one vertical slice covering one caption style, one hook/overlay, one background/framing behavior, and one motion effect;
- measured comparison of output frames, text bounds, timing, and render behavior.

Only after this vertical slice passes should the schema and renderer contract be expanded to the full feature set.
