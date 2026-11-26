# Reference Analysis Workbench — Milestone 1

**Status:** First end-to-end implementation slice in development  
**Branch:** `feature/template-reference-workbench-current-main`  
**API namespace:** `/api/template-analysis`  
**Scope boundary:** Analyze an edited reference video and return an evidence-backed report. Do not modify normal clip generation or render a template onto generated clips in this milestone.

## 1. Product outcome

A user uploads an already-edited video in the Templates tab. Clippy stores it as a durable analysis job, runs deterministic media analysis, optionally sends bounded sample frames to Gemini after explicit consent, and presents a detailed report that can be checked against the original video.

The report is not yet a renderer recipe and is not automatically applied. It is a forensic description of what the analysis can substantiate.

## 2. Current workflow

1. The user uploads MP4, MOV, MKV, WebM, M4V or AVI.
2. The user confirms they own the reference or have permission to analyze it.
3. Gemini visual analysis is optional and requires a separate opt-in. If declined, local technical and pixel analysis still runs.
4. The API streams the upload to a bounded staging file. The job store moves it into its own durable job directory.
5. An analysis worker probes the source, detects cut candidates, extracts bounded frames, measures visual statistics and writes progress.
6. With consent, Gemini receives the sampled resized PNG frames and exact evidence identifiers/timestamps. It does not receive the full source video.
7. Clippy validates the structured response. Every finding, including global overview conclusions, must cite an exact frame/timestamp pair supplied to Gemini. Time-bounded text, effect, scene and transition findings are checked against their cited evidence window.
8. The workbench displays technical facts, evidence frames, measured visual properties and the AI breakdown. Clicking an evidence thumbnail seeks the original video player to that timestamp; estimated text/graphic boxes are overlaid on cited frames.
9. Jobs can be cancelled. Terminal jobs can be deleted along with their retained source and evidence files.

## 3. Data and report contracts

### 3.1 Deterministic analysis

The deterministic pass records:
- Source hash, file size, duration, dimensions, frame rate, codecs, rotation and audio stream metadata.
- FFmpeg scene-cut candidates.
- Representative sampled frames and their checksums.
- Dominant colors, luminance/saturation, edge density and inter-sample visual change.
- Coverage values and explicit analysis limitations.

The visual-difference metric is not optical flow and must not be presented as subject tracking or exact motion.

### 3.2 Gemini report

The provider returns a strict versioned `ReferenceStyleReport` containing:
- Overall visual identity, editorial style and pacing summary.
- Text regions: captions, hooks, titles, lower thirds and labels.
- Typography: ranked font candidates, estimated weight/style/size, fill/highlight/outline colors, stroke, shadow, backing, alignment and line count.
- Text placement: normalized top-left-origin bounding boxes and best-effort observed visibility intervals.
- Text animation/reveal behavior, only where sampled evidence supports it.
- Background treatment: original footage, blurred duplicate, solid fill, gradient, image/video background or unknown.
- Composition/framing: single subject, picture-in-picture, split/stacked layouts, screen-recording arrangements and estimated subject regions.
- Graphic overlays: logos, watermarks, badges, shapes and other visible elements.
- Effects and motion: zoom, pan, shake, speed changes, blur, color grade and related observations.
- Transitions: cuts, fades, dissolves, wipes, slides, whip pans, zooms and flashes.
- Scene/editorial observations: broad content type, mood/energy and the apparent editorial role of each sampled scene.
- Limitations and evidence references.

Confidence values are qualitative. Bounding boxes and timing inferred by the vision model are estimates.

### 3.3 Evidence validation

The provider cannot cite arbitrary frame names or timestamps. After structured parsing, Clippy verifies every finding against the supplied evidence set. A claim with invalid evidence is rejected rather than shown as supported.

The report contract describes observed treatment. It is deliberately separate from `TemplateRecipe`, which describes renderer-independent settings that Clippy can later apply.

## 4. Gemini and media boundaries

- Current visual interpreter default: `gemini-3.1-flash-lite`, overridden by `GEMINI_MODEL`.
- The full source file remains local.
- Only sampled, downscaled PNG frames are sent when consent is enabled.
- The interpretation stage is bounded by frame-count and total-byte limits.
- API keys are passed to the running worker but are not written into job manifests.
- If Gemini fails, deterministic results are retained and the job becomes partial rather than discarding the work.
- If consent is declined, the deterministic result remains available and AI status is `not_consented`.

## 5. Durable job lifecycle

Job data lives under `CLIPPY_DATA_DIR/template-analysis/jobs/<job-id>/`, outside `OUTPUT_DIR`. Each job contains:
- `job.json`: source identity, progress/state, consent flag and status.
- `source.*`: original uploaded reference.
- `evidence/`: extracted evidence frames.
- `report.json`: deterministic analysis and optional validated Gemini report.

Manifests are written atomically. Job identifiers and evidence asset identifiers are strictly validated. Interrupted jobs can be re-queued after backend restart. A retry starts deterministic analysis from the retained source and clears only the prior attempt's derived evidence directory first, preventing stale frame files from breaking recovery. Only one reference analysis is executed at a time by the current local worker semaphore. Analysis tasks are registered with the desktop maintenance tracker so data relocation and desktop updates wait for them to finish.

### Job statuses

- `queued`: accepted and waiting for analysis.
- `running`: probing, sampling, measuring or interpreting.
- `completed`: deterministic and consented AI stages completed.
- `partial`: deterministic report is available, but AI was not consented or failed.
- `failed`: deterministic processing failed.
- `cancelled`: safely cancelled at a stage boundary.

Deletion is allowed only for terminal states. Active jobs must be cancelled and allowed to finish first.

## 6. API surface

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/api/template-analysis/jobs` | Upload a reference and queue analysis |
| GET | `/api/template-analysis/jobs` | List local analysis jobs |
| GET | `/api/template-analysis/jobs/{job_id}` | Read job and report |
| POST | `/api/template-analysis/jobs/{job_id}/cancel` | Request safe cancellation |
| DELETE | `/api/template-analysis/jobs/{job_id}` | Delete a terminal analysis and its source/evidence |
| GET | `/api/template-analysis/jobs/{job_id}/source` | Stream the original reference for inline playback |
| GET | `/api/template-analysis/jobs/{job_id}/evidence/{asset_id}` | Serve a sampled evidence frame |

The source/evidence query-token exception is restricted to exact read-only paths and GET/HEAD. It exists because native HTML media/image elements cannot attach Clippy's desktop API header. It does not allow query-token access to arbitrary API endpoints.

Managed/billing mode remains disabled for this local analysis store until owner-scoped durable storage and media delivery are implemented.

## 7. Sensitive integration areas intentionally untouched

- `/api/process` and its upload/generation contract.
- `main.py`, `clip_selection.py`, moment scoring/selection and clip boundaries.
- `recut.py`, reframe/caption/hook/watermark editing paths.
- Normal job metadata, rerender locks and clean canonical clip handling.
- Browser Remotion preview composition and root Remotion final renderer.
- Windows runtime dependency manifests and installer bootstrap.

No template ID or recipe is passed into normal generation at this stage.

## 8. Known limitations and honesty requirements

- The current reference sampler is bounded. Very brief caption animations, fast transitions or overlays between sampled frames may be missed. The report must not claim to be an exhaustive frame-by-frame reconstruction.
- Font family names are ranked visual candidates, not recoverable source-font identity. The original font may be impossible to identify from a flattened video.
- Text and subject bounding boxes are visual estimates. They need human verification before being used as exact render coordinates.
- A vision model looking at still frames cannot prove motion paths, speed ramps or transition duration unless the evidence supports those claims.
- Audio content, music, sound effects, voice processing and audio ducking are **not analyzed** in this milestone. The visual report schema excludes audio claims; only audio stream metadata is measured.
- The report now has a separate human review/correction layer and a reviewed-draft save action. Draft synthesis intentionally maps only the currently supported subset of observations into the canonical recipe; it is not yet a complete visual editor.
- The saved local-template list now exposes a read-only compatibility preflight for Python/FFmpeg, Remotion preview and Remotion render. It still has no template detail/editor screen, recipe editing, revision-aware update/delete UI, or template-application UI. There is no managed/cloud template library, template application, preview/final renderer parity or clip-generation integration.
- Job data currently persists until the user deletes it. A configurable automatic retention policy is a follow-up.
- The UI has a technical/pixel analysis fallback without Gemini; this is not equivalent to the full visual interpretation.

## 9. Milestone acceptance plan

Before declaring reference analysis accurate enough to drive reusable templates:

1. Test a varied reference corpus: talking-head/podcast, gaming, educational/screencast, motivational, product, split-screen and picture-in-picture.
2. Include vertical and landscape source videos, low-light footage, heavy compression, multilingual captions, outlined text, animated captions, persistent watermarks, changing backgrounds and rapid cuts.
3. For each test video, manually label visible text regions, key typography attributes, bounding boxes, background/composition, important effects and transition times.
4. Compare model findings with those labels. Track missed findings, unsupported claims, bounding-box overlap/position error, timing error and top-k font-candidate accuracy.
5. Require 100% evidence-reference validity. Unsupported claims must be omitted or explicitly uncertain.
6. Have a human inspect the original player alongside report findings and correct the report before any future recipe conversion.
7. Repeat representative tests after changing the sample strategy, Gemini model or prompts.

Only after this milestone passes should the team connect approved analysis to template recipe synthesis and then redesign preview/final render parity.


## 10. Human review layer

The visual report remains the immutable provider result. Human decisions are stored separately in `review.json`, keyed by finding type and stable finding ID.

- Each supported finding can be accepted or rejected.
- The decision stores a UTC timestamp and an optional note.
- Repeated decisions update the same record rather than creating duplicate entries.
- A review can only target a finding present in the saved AI report, and its evidence is revalidated before the decision is stored.
- The selected-job detail API returns review decisions; the lightweight job-list API remains small.
- The review UI exposes Accept/Reject controls, notes, and typed corrections for supported finding categories. Corrections are validated against the report schema and evidence, then stored separately from the immutable provider report. The draft-template action converts accepted/corrected observations into the currently supported subset of canonical recipe properties and saves the report, review history, and evidence as local template assets.


## 11. Operational diagnostics and hardening

- Reference-analysis lifecycle events use the standard Python logger namespace `clippy.template_analysis`; logs include opaque job/template IDs, diagnostic IDs, stages, status, evidence counts and byte totals, but never source-video contents, API key values, desktop tokens, or review-note contents.
- Unexpected worker failures, API storage/list failures and invalid job manifests retain exception tracebacks in the desktop backend log. API responses expose a diagnostic ID rather than internal paths or exception details. Progress polling is not logged; stage transitions are.
- The Gemini key remains browser-local like the existing Settings implementation. It is sent in `X-Gemini-Key` only when the user explicitly enables Gemini visual analysis for a reference upload; only key presence/source is logged, never the value.
- The Windows backend payload explicitly includes `template_system`; the assembled-ZIP Pester contract checks its entry points, the clean-runtime smoke script imports the package, and the native supervisor checks required files before launching services.
- Analysis work is registered with the existing desktop maintenance background-task tracker, so data relocation and desktop update preparation cannot proceed while reference analysis is using the data directory.
- Restart recovery replays deterministic analysis from the retained source and removes only that job's stale derived evidence. It does not delete the source video or other jobs' data.
- This milestone remains local-only and does not apply templates to generated clips. Preview/final renderer parity and full template editing/application remain separate acceptance gates.

## 12. Remaining implementation sequence

The reference-analysis and human-review slice is now present in the branch. The following work remains deliberately staged:

1. Keep backend CI, frontend build and Windows installer validation green; fix regressions in the owning layer before expanding scope.
2. Validate analysis quality against a manually labeled reference corpus spanning the formats and visual cases in section 9. Treat this as the accuracy gate, not as an optional demo exercise.
3. Complete the remaining local template-library workflow: inspect a saved template, edit its metadata and supported recipe fields, save with expected-revision conflict handling, and delete safely. Extend the now-visible capability preflight only when actual adapter support changes; partial or unsupported behavior must never be silently dropped.
4. Establish one shared preview/final-render contract and close the currently reported capability gaps before claiming parity.
5. Add explicit, user-approved single-clip template application with a clear compatibility preflight and a reversible result. Do not couple it to automatic clip selection yet.
6. Only after single-clip behavior is reliable, consider batch application and normal generation-pipeline integration. Managed/cloud storage remains deferred until account-scoped storage and media delivery are designed.

A configurable local retention policy is also outstanding. It should be implemented with explicit user-visible policy and must never silently purge saved templates or active jobs.

## 13. Analysis-quality gate — required before template application

The first installed-app evaluation showed that a completed deterministic pass is not the same as a usable editing analysis. Template application remains deferred until this gate is met.

### 13.1 First evaluation findings (2026-11-26)

- The supplied gaming/streamer frame is a vertically stacked composition: a webcam/presenter region above a gameplay region. The visible split is approximately 30% webcam and 70% gameplay, not an assumed 50/50 split. This is an initial visual annotation from one still, not yet a source-video ground-truth measurement.
- The displayed luminance, saturation and edge-density values are low-level per-frame pixel diagnostics. They are not semantic detections, layout measurements, cut-quality scores or recipe instructions. Keep them available as advanced diagnostics, but do not present them as the main editing analysis.
- The deterministic sampler currently chooses at most 24 scene-midpoint/uniform timestamps. Frames are resized to a maximum dimension of 640 pixels before Gemini interpretation. This is too sparse/coarse to reliably reconstruct brief hooks, fast edits, small subtitle details or word-level caption animation.
- FFmpeg scene detection currently retains candidate timestamps from its scene filter, but not the scene score or a measured cut-strength/abruptness value. It therefore cannot yet explain how sharp a cut is.
- The current report has generic composition kinds and anonymous subject-region boxes. It does not identify independently addressable panes such as webcam and gameplay, nor store their ordered normalized rectangles, divider geometry or source-fit policy.
- The canonical `TemplateRecipe` currently has one `FramingRecipe` for the source frame. It cannot describe a multi-region canvas with separately assigned source panes. Even a better AI report could not yet express this layout as a renderer-ready recipe.
- The text report already has fields for text role, estimated box, font candidates, weight/style/size, fill/highlight/outline/shadow, alignment, animation and observed visibility interval. Those fields were not returned in the supplied run because Gemini interpretation failed before the request reached the model.
- The Gemini failure was a local SDK/schema-conversion error. `ReferenceStyleReport.schema_version` used integer `Literal[1]`; the pinned `google-genai==1.75.0` converter rejects non-string singleton Literal constants with `Literal values must be strings.` The field was changed to an integer constrained to version 1, and a regression test now exercises the SDK schema conversion without a network call. This fix is committed on the current workbench branch; CI still needs to validate it.

### 13.2 Required analysis capabilities

1. **Pane/layout reconstruction:** Represent the canvas layout and each region separately. A region needs a semantic role (for example webcam, gameplay, screen share, presenter, background or unknown), normalized x/y/width/height, order/layer, confidence, evidence timestamps, and an explicit fit policy such as contain, cover, crop or unknown. Record divider/gap/border details when visible. Report ratios from observed geometry rather than assuming equal halves.
2. **Temporal evidence:** Retain broad scene coverage, but add targeted samples around the opening hook, every deterministic cut candidate, text appearance/disappearance and other detected events. Use higher-resolution targeted evidence for small text where needed. Keep frame count, image dimensions and total upload bytes bounded; do not silently claim frame-accurate timing from sparse stills.
3. **Text/subtitle analysis:** Distinguish captions, hooks, titles, labels and watermarks. Report observed text, region geometry, line count, alignment, font characteristics, ranked font-family candidates, colors, outline/shadow/backing, and reveal/highlight behavior. Add temporal evidence where subtitles change. Font family remains a ranked visual estimate: a flattened video does not normally preserve the original font metadata, so exact identification must not be claimed.
4. **Hook placement:** Report visual/text hook type, content when readable, normalized placement, first/last observed times, entrance behavior and supporting frames. Spoken hooks and audio-driven timing require a separate transcript/audio-analysis stage; visual-only analysis must state that limitation.
5. **Cut and pacing analysis:** Preserve each cut candidate's timestamp and FFmpeg scene score. Measure shot durations and visual change around the boundary with before/after evidence. Detect gradual transitions with a multi-frame window rather than guessing from one still. Separate measurable cut abruptness from qualitative editorial effectiveness. Any effectiveness assessment must explain its visual/audio evidence and must not be presented as an objective numeric truth.
6. **Renderer-ready layout contract:** Extend the recipe only after its pane semantics are defined. A layout recipe must be able to place each source region in a normalized destination rectangle and specify whether source content is preserved, contained, covered or cropped. A separate source is required when webcam and gameplay are separate inputs; a single already-composited source can only be rearranged within the information present in that source. Unsupported source arrangements must fail compatibility preflight instead of silently cropping or dropping a pane.
7. **Workbench presentation:** Show a visual layout map with labelled panes and measured ratios, a cut/shot timeline, hook and caption timing, and typography details. Keep the low-level pixel measurements in an explicitly labelled advanced diagnostics section, with definitions.
8. **Human correction and evidence:** Keep all model findings evidence-linked and reviewable. A high-impact layout/caption finding must be correctable before recipe synthesis. Unknown or weakly supported properties should remain unknown instead of being filled with guesses.

### 13.3 Implementation order

1. Validate the Gemini schema compatibility fix and rerun the same reference.
2. Inspect the now-successful report against the same reference before changing prompts or adding more schema fields; this isolates model quality from the previous local failure.
3. Upgrade the sampler and deterministic cut evidence, then add the pane-region and text/hook report contracts and their UI.
4. Add the multi-region recipe and renderer compatibility support. Do not claim that analysis can recreate a layout until the recipe and renderer can represent it.
5. Validate against manually labelled gaming/streamer, podcast/talking-head, screencast, educational, split-screen and picture-in-picture references. Track pane-role correctness and geometry error, missed/false text regions, hook timing/placement error, cut-boundary/timing error, font-candidate ranking and evidence validity.
6. Only after the report and renderer pass this quality gate should single-clip template application begin. Batch and normal-generation integration remain later stages.

### 13.4 Boundaries and non-claims

- A reference still can establish visible composition and approximate geometry, but cannot establish cut timing, hook duration, subtitle animation, or whether an edit is effective over time. Those require the source video.
- Exact original-font recovery is not guaranteed from rendered pixels. Return ranked candidates and visual traits, then allow human correction or a supplied font asset.
- A visual-only pass cannot judge beat sync, spoken-hook timing, music edits, sound effects or audio ducking. Those belong to a separately validated audio-analysis milestone.
- “Preserve gameplay without cropping” is a renderer requirement, not something a vision prompt can guarantee. It must be represented explicitly in the layout recipe and verified by preview/final-render parity.
