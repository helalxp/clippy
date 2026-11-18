# Reference Analysis Workbench — Milestone 1

**Status:** First end-to-end implementation slice in development  
**Branch:** \`feature/template-reference-workbench\`  
**API namespace:** \`/api/template-analysis\`  
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
7. Clippy validates the structured response. Every finding must cite an exact frame/timestamp pair supplied to Gemini.
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

The provider returns a strict versioned \`ReferenceStyleReport\` containing:
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

The report contract describes observed treatment. It is deliberately separate from \`TemplateRecipe\`, which describes renderer-independent settings that Clippy can later apply.

## 4. Gemini and media boundaries

- Current visual interpreter default: \`gemini-3.1-flash-lite\`, overridden by \`GEMINI_MODEL\`.
- The full source file remains local.
- Only sampled, downscaled PNG frames are sent when consent is enabled.
- The interpretation stage is bounded by frame-count and total-byte limits.
- API keys are passed to the running worker but are not written into job manifests.
- If Gemini fails, deterministic results are retained and the job becomes partial rather than discarding the work.
- If consent is declined, the deterministic result remains available and AI status is \`not_consented\`.

## 5. Durable job lifecycle

Job data lives under \`CLIPPY_DATA_DIR/template-analysis/jobs/<job-id>/\`, outside \`OUTPUT_DIR\`. Each job contains:
- \`job.json\`: source identity, progress/state, consent flag and status.
- \`source.*\`: original uploaded reference.
- \`evidence/\`: extracted evidence frames.
- \`report.json\`: deterministic analysis and optional validated Gemini report.

Manifests are written atomically. Job identifiers and evidence asset identifiers are strictly validated. Interrupted jobs can be re-queued after backend restart. Only one reference analysis is executed at a time by the current local worker semaphore.

### Job statuses

- \`queued\`: accepted and waiting for analysis.
- \`running\`: probing, sampling, measuring or interpreting.
- \`completed\`: deterministic and consented AI stages completed.
- \`partial\`: deterministic report is available, but AI was not consented or failed.
- \`failed\`: deterministic processing failed.
- \`cancelled\`: safely cancelled at a stage boundary.

Deletion is allowed only for terminal states. Active jobs must be cancelled and allowed to finish first.

## 6. API surface

| Method | Route | Purpose |
| --- | --- | --- |
| POST | \`/api/template-analysis/jobs\` | Upload a reference and queue analysis |
| GET | \`/api/template-analysis/jobs\` | List local analysis jobs |
| GET | \`/api/template-analysis/jobs/{job_id}\` | Read job and report |
| POST | \`/api/template-analysis/jobs/{job_id}/cancel\` | Request safe cancellation |
| DELETE | \`/api/template-analysis/jobs/{job_id}\` | Delete a terminal analysis and its source/evidence |
| GET | \`/api/template-analysis/jobs/{job_id}/source\` | Stream the original reference for inline playback |
| GET | \`/api/template-analysis/jobs/{job_id}/evidence/{asset_id}\` | Serve a sampled evidence frame |

The source/evidence query-token exception is restricted to exact read-only paths and GET/HEAD. It exists because native HTML media/image elements cannot attach Clippy's desktop API header. It does not allow query-token access to arbitrary API endpoints.

Managed/billing mode remains disabled for this local analysis store until owner-scoped durable storage and media delivery are implemented.

## 7. Sensitive integration areas intentionally untouched

- \`/api/process\` and its upload/generation contract.
- \`main.py\`, \`clip_selection.py\`, moment scoring/selection and clip boundaries.
- \`recut.py\`, reframe/caption/hook/watermark editing paths.
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
- The report is viewable but does not yet have the full claim-review/correction workflow or a save-reviewed-report-as-template action.
- There is no managed/cloud template library, template application, preview/final renderer parity or clip-generation integration.
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
