# Clippy Template Reference System
## Product and Technical Specification (Draft v1)

**Status:** Proposed architecture, pending product-quiz confirmation  
**Target branch:** `feature/template-reference-system`  
**Baseline:** `main` at branch creation  
**Scope:** Reference-video analysis, reusable editing templates, template authoring, application, preview, rendering, and library lifecycle.

---

## 1. Product goal

Build a first-class Template Reference System that lets a user show Clippy an example video and ask it to reproduce the editing style across their own clips.

A template is not a color preset or a screenshot. It is a structured, editable, versioned editing recipe that can describe:

- Visual identity: typography, colors, outlines, shadows, backgrounds, overlays, logos, and safe areas.
- Caption language: font, size, placement, word/phrase grouping, highlighting, reveal behavior, animation, line limits, and language/direction handling.
- Composition: aspect ratio, subject placement, crop strategy, split-screen, picture-in-picture, screen/presenter arrangements, and background treatment.
- Motion: zooms, punch-ins, camera movement, transitions, animated text, and effect timing.
- Rhythm: shot duration distribution, cut density, pauses, emphasis, hook timing, and scene changes.
- Editorial structure: opening hook, recurring visual motifs, segment patterns, and optional end treatment.
- Technical constraints: supported output dimensions, frame rates, fonts, assets, renderer capabilities, and required dependencies.

The system must distinguish what was observed, what was inferred, what was manually corrected, and what Clippy can actually reproduce.

## 2. Product and engineering principles

### 2.1 Preserve outcomes, not legacy implementation

Existing functionality is not protected merely because it exists. Existing code may be retained, refactored, replaced, or rewritten when evidence shows the new approach is better.

A replacement must be evaluated against explicit criteria:
- Correctness and output quality.
- Reliability and failure behavior.
- Preview-to-render fidelity.
- Performance and resource use.
- Maintainability and testability.
- Accessibility and usability.
- Compatibility with existing jobs, saved settings, and user data.
- Security and licensing.

Do not perform a broad rewrite simply for novelty. Prefer the architecture that demonstrably serves the product best. A subsystem rewrite is acceptable when its design and migration plan are clear and measurable.

### 2.2 Honest analysis

Never label a property as detected when it was not measured. Never present an inference as fact. Every analyzed property should carry:
- Value or candidate values.
- Evidence/source.
- Confidence or uncertainty.
- Analysis coverage and sampling limitations.
- Support status: supported, partially supported, unsupported, or not analyzed.

A failure to analyze one dimension must not invalidate all other useful analysis.

### 2.3 User control

The user can inspect and edit extracted properties. AI recommendations are suggestions, not silent overrides of explicit user choices. Preserve original templates when making substantial edits; support duplicate/version workflows.

### 2.4 Reproducibility

Applying the same template version, source clip, and explicit settings should produce a reproducible render within the limits of encoder and platform determinism. Record the template version and effective settings used for each render.

### 2.5 Local-first with a future managed-storage boundary

The current reference-template code intentionally supports local/self-hosted storage and blocks managed mode until account-scoped storage exists. Retain that safety boundary. Do not expose a shared managed library until ownership, authorization, storage isolation, quotas, deletion, and media delivery are designed and tested.

---

## 3. Current-state audit

The existing reference-template prototype was inspected on `windows-native-migration`, and its branch diff was compared against `main`.

### 3.1 Existing prototype

Files on the prototype branch:
- `reference_templates.py`
- `dashboard/src/components/ReferenceTemplateLibrary.jsx`
- `tests/test_reference_templates.py`
- `reference_templates/<id>/manifest.json` and poster media
- API routes in `app.py`
- Navigation integration in `dashboard/src/App.jsx`
- A minimal integration touch in `layout_picker.py`

The prototype currently:
- Accepts a local video upload.
- Uses FFprobe to read duration, dimensions, frame rate, and audio presence.
- Uses FFmpeg scene detection to estimate hard cuts and average shot duration.
- Creates a poster frame.
- Stores the source video and a version-1 JSON manifest.
- Lists templates in a basic React library.
- Supports basic name/category/override updates.
- Rejects managed/billing mode because account-scoped media storage is not implemented.

### 3.2 Important limitations and risks found

1. **It is a reference record, not yet a full editing template.** Framing, captions, background, and watermark are explicitly marked not analyzed.
2. **No reference URL workflow exists.** The API accepts an uploaded file only.
3. **No true style editor exists.** The UI displays metadata and has no detailed editing controls or preview application.
4. **No template application contract exists.** The current Remotion renderer does not accept a complete template configuration.
5. **No template-to-render integration exists.** Existing renderer props are limited to video, subtitles, hook, and effects.
6. **Analysis is narrow.** Current pacing is inferred from hard-cut timestamps only. It does not analyze typography, colors, visual hierarchy, transitions, motion, or editorial structure.
7. **The source upload is moved into the library during creation.** This is acceptable for the current staging flow but needs explicit transactional semantics, cancellation handling, and cleanup guarantees.
8. **Manifest validation is weak.** JSON compatibility is checked for overrides, but there is no strict schema versioning, deep field validation, asset inventory, migration system, or capability validation.
9. **No robust lifecycle exists.** Delete, duplicate, export, import, archive, restore, and asset cleanup are not fully implemented.
10. **Tests cover only three narrow behaviors.** They do not cover API authorization, malformed media, failed analysis, cancellation, large files, manifest migrations, renderer application, or actual rendered output.
11. **The UI's own copy correctly admits the analysis is incomplete.** Preserve that honesty and replace the current minimal experience with progressive, evidence-backed analysis.

### 3.3 Branch safety finding

At inspection, `codex/reference-templates` had one unique commit and was 140 commits behind `main`. It must not be merged wholesale. Treat it as a source of ideas and selectively port useful behavior after auditing it against current `main`.

The new feature branch is based on `main`; the old branch is not the implementation base.

---

## 4. User experience and primary workflows

The detailed product quiz is still pending. The following are recommended defaults for the first implementation specification, not silently confirmed user decisions.

### 4.1 Entry points

The Templates workspace should provide clear entry points:
1. Browse the template library.
2. Create a template manually.
3. Analyze a reference video upload.
4. Import a supported template package.
5. Duplicate or edit an existing template.

Reference URL ingestion can be added when a specific provider and safe ingestion contract are approved. Do not implement arbitrary URL fetching.

### 4.2 Reference analysis workflow

1. User selects or uploads a reference video and confirms they have the right to use it as a reference.
2. Clippy validates file type, size, duration, media streams, and decode support.
3. Clippy creates a safe staged copy and an analysis job with visible progress, cancellation, and logs.
4. A deterministic media pass gathers technical metadata, representative frames, scene boundaries, audio features, and measurable motion/cut statistics.
5. Optional vision/AI analysis interprets visual semantics from selected frames or short bounded segments. It must not upload the entire source video by default.
6. Clippy builds a draft template with evidence, confidence, coverage, and support labels for each property.
7. The user reviews the draft, sees unsupported or uncertain elements, and edits any property.
8. Clippy validates the template against the renderer capability registry.
9. The user saves the result as a new template. The original reference remains available as provenance unless the user explicitly removes it.

Analysis should be resumable where practical. If one analysis stage fails, keep completed stages and clearly mark the missing dimensions.

### 4.3 Template library workflow

The library should support:
- Search, filter, category, tags, sort, and favorites.
- Clear distinction between built-in, personal, imported, and shared templates.
- Poster/preview, description, compatibility indicators, and last-updated details.
- Duplicate, rename, categorize, archive, delete, export, and import.
- Version history or recoverable revisions.
- Broken/missing asset warnings and repair guidance.

### 4.4 Template editor workflow

Provide a visual preview beside structured controls. Organize settings into meaningful groups:
- Canvas and composition.
- Framing and subject layout.
- Captions and typography.
- Hook/title treatment.
- Colors, backgrounds, and overlays.
- Motion and transitions.
- Timing and editorial rhythm.
- Brand assets and watermark.
- Output and compatibility.

Provide simple controls by default and advanced controls for users who want precise values. Every control must map to a documented schema property and a renderer capability.

### 4.5 Apply and preview workflow

Users should be able to:
- Preview a representative sample before rendering a full set.
- Apply a template to one clip or a batch.
- Choose whether AI may adapt timing/layout to clip content.
- Lock properties that must remain exact.
- See which values were adapted and why.
- Override settings for an individual clip without mutating the source template.
- Save those overrides as a new template or revision.

Recommended default: content-aware adaptation is opt-in per application until quality has been validated. Explicitly locked properties always win.

---

## 5. Proposed architecture

Separate the system into independently testable domains.

### 5.1 Template domain

Owns template identity, schema, versions, validation, migration, assets, overrides, provenance, and lifecycle.

Suggested modules (names provisional):
- `template_domain/`: domain models and validation.
- `template_storage/`: local storage adapter and future managed adapter.
- `template_analysis/`: deterministic and AI-assisted analysis stages.
- `template_capabilities/`: renderer feature registry and validation.
- `template_application/`: resolve template + clip + user overrides into an effective render recipe.
- `template_api/`: API contracts and route handlers where separation from `app.py` is practical.

Do not create all modules mechanically. First map current project conventions and choose boundaries that reduce coupling.

### 5.2 Analysis pipeline

Use staged analysis rather than one giant AI prompt:

**Stage A: Media probe**
- Codec, duration, dimensions, pixel aspect ratio, frame rate, audio streams, rotation, and decode status.
- Validate timestamps and stream metadata.
- Record exact analysis coverage.

**Stage B: Temporal sampling**
- Detect scene boundaries and representative shots.
- Sample frames at scene-aware positions, not only uniform intervals.
- Bound frame count, resolution, and analysis duration.
- Preserve sample timestamps and source frame dimensions.

**Stage C: Deterministic visual measurements**
- Color palette candidates and distribution.
- Dominant/background colors where meaningful.
- Text/overlay region candidates.
- Motion magnitude and shot/cut statistics.
- Frame occupancy and safe-area measurements.
- Detectable transitions and repeated visual motifs where measurable.

**Stage D: Vision interpretation**
- Describe likely caption placement/style, text hierarchy, overlays, composition, scene roles, and recurring patterns.
- Return structured output against a strict schema.
- Require evidence frame timestamps for claims.
- Confidence must be calibrated or explicitly qualitative; do not invent numeric precision.
- Distinguish visually observed features from inferred editing intent.

**Stage E: Audio/editorial analysis (optional and bounded)**
- Audio energy, speech/music/noise segmentation, silence and beat candidates.
- Align visual changes to audio events where possible.
- Do not infer a specific soundtrack or copyrighted audio identity unless separately supported and legally appropriate.

**Stage F: Template synthesis**
- Convert measurements and interpretations into normalized schema properties.
- Attach provenance and confidence.
- Resolve conflicts and mark ambiguity for human review.
- Run capability validation before presenting the template as ready to apply.

### 5.3 Analysis strategy

Use deterministic tools for measurable facts and AI for semantic interpretation. AI should not be asked to estimate exact pixel positions or timestamps when code can measure them more reliably. Avoid sending long videos wholesale to a model. Prefer bounded frame/segment evidence, configurable model providers, cost estimates, and user consent for external analysis.

### 5.4 Capability registry

The template editor and renderer must share a capability registry describing:
- Supported property and value ranges.
- Required renderer implementation.
- Required fonts/assets.
- Preview support.
- Final-render support.
- Known platform restrictions.
- Whether support is exact, approximate, or unavailable.

A template must not silently degrade. The user sees a compatibility report before applying it.

### 5.5 Template application resolver

Resolve the final recipe in a deterministic order:

1. Renderer defaults.
2. Template base values.
3. User-selected template revision.
4. Per-job settings.
5. Per-clip overrides.
6. Explicit user locks and safety constraints.

AI adaptation may propose changes only to unlocked properties and must return a diff/reason for each change. The resolved recipe is immutable for a render job and stored with its provenance.

---

## 6. Canonical template data model

The exact schema must be validated against real renderer capabilities before implementation. The following is the proposed conceptual v2 shape:

```json
{
  "schema": "clippy.template",
  "schema_version": 2,
  "id": "tpl_<stable-id>",
  "revision": 1,
  "name": "Example style",
  "description": "",
  "category": "Podcast",
  "tags": [],
  "origin": {
    "kind": "reference_video",
    "source_name": "reference.mp4",
    "source_fingerprint": "sha256:...",
    "analyzed_at": "ISO-8601",
    "tool_versions": {}
  },
  "analysis": {
    "status": "complete",
    "coverage": {},
    "properties": {
      "canvas": {},
      "composition": {},
      "framing": {},
      "captions": {},
      "typography": {},
      "colors": {},
      "background": {},
      "overlays": [],
      "motion": [],
      "transitions": [],
      "rhythm": {},
      "audio": {}
    },
    "evidence": [],
    "limitations": []
  },
  "recipe": {
    "canvas": {},
    "composition": {},
    "framing": {},
    "captions": {},
    "hook": {},
    "typography": {},
    "colors": {},
    "background": {},
    "overlays": [],
    "motion": [],
    "transitions": [],
    "rhythm": {},
    "assets": []
  },
  "capabilities": {
    "status": "partially_supported",
    "supported": [],
    "approximated": [],
    "unsupported": []
  },
  "assets": [],
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601"
}
```

This is a design sketch, not a committed runtime schema. Use strict typed validation (Pydantic on the backend and Zod or generated contracts on the TypeScript side) and a single authoritative schema source or generated shared types to prevent drift.

### 6.1 Evidence record

Every analyzed property should be traceable to evidence such as:
- Source frame timestamp or time range.
- Thumbnail/evidence asset identifier.
- Measurement method or model/provider.
- Confidence/uncertainty.
- Analysis version.
- Human correction, if any.

### 6.2 Versioning and migration

- Separate schema version from user-visible template revision.
- Validate every read and write.
- Provide explicit migrations from the current version-1 manifest.
- Never mutate original reference assets during schema migration.
- Keep backups or atomic writes.
- Unknown fields should be handled by documented forward-compatibility rules, not silently discarded.
- Failed migration must leave the original file recoverable.

### 6.3 Asset management

Use relative, manifest-owned asset paths. Validate every path remains inside the template directory. Track content type, byte size, dimensions, and checksum. Never trust filenames or MIME headers alone. Enforce quotas and safe cleanup.

---

## 7. Rendering and preview architecture

This is a critical design area and must be audited before implementation.

### 7.1 Current rendering surfaces

The current repository has:
- Python/FFmpeg processing and subtitle burning.
- Remotion compositions for browser preview and Remotion rendering.
- A Remotion `ShortVideo` composition with subtitle, hook, and effects layers.
- Zod schemas for current Remotion props.
- Existing caption, hook, reframing, split, screencast, inset, and punch-in subsystems.
- A separate clip editor and rerender API.

The current reference prototype does not pass a complete template recipe into these render paths.

### 7.2 Required architecture

Establish one canonical render recipe and adapters for each rendering backend. Do not independently reimplement template semantics in multiple places.

The preview and final output must share:
- Normalized units and coordinate system.
- Font resolution and asset loading.
- Caption grouping and timing.
- Animation curves and timing semantics.
- Layer order and compositing rules.
- Canvas and safe-area calculations.
- Crop/framing decisions, or an explicit statement of preview limitations.

Where exact parity is technically impossible, show a clear preview warning and test the difference.

### 7.3 Reuse versus rewrite

Audit each existing subsystem independently:
- Subtitle style and ASS burn path.
- Remotion subtitle preview/render path.
- Hook overlay and hook placement.
- Reframe/layout engines.
- Background and watermark overlays.
- Clip editor and rerender route.
- Renderer job contract and metadata persistence.

Keep or improve components with strong correctness and tests. Replace components whose duplicated semantics, hidden assumptions, or poor fidelity make the new system unreliable. Do not rewrite the entire media pipeline unless the audit demonstrates that it is necessary.

### 7.4 Render provenance

Every render should record:
- Template ID and revision.
- Schema version.
- Effective recipe hash.
- Per-clip overrides.
- Adaptation changes and rationale.
- Renderer/backend version.
- Unsupported/approximated properties.
- Output metadata and validation result.

---

## 8. API and lifecycle requirements

API names are provisional; fit them to existing route conventions after reviewing authentication and job handling.

Required operations:
- List/search templates.
- Get template and revision.
- Create a manual template.
- Start reference analysis.
- Poll analysis status and cancel analysis.
- Review/update extracted properties.
- Validate template against renderer capabilities.
- Preview template against a sample clip.
- Apply template to a clip or batch.
- Duplicate and create revision.
- Export and import a versioned package.
- Archive, restore, and delete with asset cleanup.
- Fetch poster/evidence assets through authorized media routes.

All operations require input validation, authorization, safe file handling, quotas, and structured errors. Long-running analysis and rendering must use job lifecycle patterns rather than blocking HTTP requests.

### URL ingestion

Do not fetch arbitrary user-provided URLs. First define supported providers and implement provider-specific resolution. Apply SSRF protections, redirect revalidation, DNS/IP checks, content-size and duration limits, safe temporary storage, and rights confirmation. Prefer official APIs or user-provided local files when a platform does not permit reliable ingestion.

---

## 9. Security, privacy, and licensing

- Treat source videos, metadata, manifests, and imported template packages as untrusted.
- Prevent path traversal, archive traversal, symlink escapes, decompression bombs, and unsafe media parser invocation.
- Limit upload size, duration, resolution, frame count, CPU/GPU time, disk use, and concurrent analysis jobs.
- Sanitize filenames and never expose raw filesystem paths.
- Keep private source references private and separate from generated posters/evidence.
- Use account-scoped storage and authorization before enabling managed mode.
- Define deletion semantics for source videos, derived evidence, exports, and backups.
- Obtain user consent before external AI analysis; disclose what media is sent and estimate cost where possible.
- Review fonts, stock assets, effects, and any bundled resources for redistribution licenses.
- Do not download or redistribute copyrighted reference media as part of template packages by default. A portable template should contain the recipe and only assets the user is authorized to export.

---

## 10. Performance and observability

- Analysis is asynchronous, cancellable, and progress-reporting.
- Reuse extracted media metadata and frame samples between compatible analysis stages.
- Cache analysis by source fingerprint and analysis version, subject to privacy and storage policy.
- Bound sampling and model context.
- Avoid loading multiple large AI models concurrently without understanding VRAM pressure.
- Support CPU fallback where appropriate and report which backend was used.
- Log stage durations, resource use, failures, model/provider, and cost without logging secrets or private media content.
- Provide actionable errors and a downloadable diagnostic report with user consent.

---

## 11. Testing and acceptance criteria

### 11.1 Domain and schema
- Valid templates round-trip without loss.
- Invalid types, ranges, assets, and paths are rejected.
- Version-1 manifests migrate to the new schema.
- Migration failure preserves original data.
- Revisions do not mutate previous revisions.
- Imported packages reject traversal and malformed archives.

### 11.2 Analysis
- Known sample videos produce correct technical metadata.
- Scene/cut detection is tested against labeled examples.
- Sampling timestamps and coverage are correct.
- Missing FFmpeg/FFprobe, decode failure, corrupt files, and AI provider failures produce clear partial/failure states.
- AI output is schema-validated and every visual claim has evidence.
- Analysis can be cancelled and does not leave orphaned files.

### 11.3 Application and renderer
- Template resolution order is deterministic.
- Explicit locks cannot be overwritten by AI adaptation.
- Unsupported features are reported before render.
- Existing job settings remain unchanged when no template is selected.
- Preview and final output are compared using representative frame snapshots and rendered videos.
- Subtitle timing, RTL text, font loading, animation, safe areas, and background layers are tested.
- Re-render preserves template provenance and per-clip overrides.

### 11.4 Lifecycle and security
- Create, list, get, update, duplicate, export, import, archive, restore, and delete are covered.
- Unauthorized access and cross-account access are rejected.
- File-size, duration, and resource limits are enforced.
- Failed operations clean up staging files safely.
- Local and managed storage boundaries are tested.

### 11.5 Product definition of done

The feature is not complete until a user can:
1. Supply a supported reference video.
2. See honest analysis progress and evidence.
3. Review and edit the resulting template.
4. Understand which features are exact, approximated, or unsupported.
5. Preview the template on their own clip.
6. Apply it to one or more clips.
7. Render a result whose visual behavior matches the preview within documented tolerances.
8. Save, duplicate, version, export, and re-import the template.
9. Reopen Clippy and find the saved template and its assets intact.
10. Complete the workflow without breaking existing clip generation or editing.

---

## 12. Implementation plan

Work in gated phases. Do not start by building the entire UI or wiring the current prototype directly into the renderer.

### Phase 0 — Repository and behavior audit
- Confirm the checked-out branch and clean/dirty working tree.
- Audit current `main` implementations and relevant tests.
- Audit the old reference-template commit as a prototype only.
- Trace subtitle, hook, framing, background, watermark, preview, render, rerender, and metadata paths.
- Identify duplicated semantics and establish baseline output fixtures.
- Produce a decision record: retain, refactor, replace, or rewrite each subsystem, with evidence.

**Gate:** reviewed architecture proposal and baseline tests/fixtures.

### Phase 1 — Domain model and storage
- Define and validate template schema v2.
- Build migrations from current v1 manifests.
- Implement safe storage, revisions, assets, and lifecycle operations.
- Add thorough domain/security tests.

**Gate:** schema and storage tests pass; existing sample manifests migrate.

### Phase 2 — Canonical recipe and renderer contract
- Define canonical units, layers, capability registry, and effective recipe resolver.
- Extend preview and final renderer contracts.
- Prove parity on a small vertical slice (e.g. one caption style + one overlay + one motion effect).

**Gate:** same recipe produces matching preview and final render for the vertical slice.

### Phase 3 — Reference analysis MVP
- Implement robust media probe and bounded scene-aware sampling.
- Add measurable visual and temporal features.
- Add optional structured vision interpretation with evidence and confidence.
- Add analysis jobs, progress, cancellation, and partial results.

**Gate:** labeled reference corpus demonstrates useful and repeatable analysis; failures are transparent.

### Phase 4 — Template editor and preview
- Build library, details, editor, evidence panel, compatibility report, and preview.
- Support simple and advanced editing modes.
- Support template revisions and duplication.

**Gate:** user can create/edit/save a template and preview it on a real clip.

### Phase 5 — Application and adaptation
- Apply templates to individual clips and batches.
- Add opt-in AI adaptation with locks and an inspectable diff.
- Persist per-clip overrides and render provenance.

**Gate:** real outputs meet quality and regression criteria.

### Phase 6 — Import/export and sharing
- Versioned package format.
- Asset validation and portability.
- Local sharing/import/export.
- Managed sharing only after account-scoped storage and permissions are complete.

**Gate:** round-trip and security tests pass.

### Phase 7 — Quality, performance, and release hardening
- Corpus-based visual regression.
- Performance and resource profiling.
- Upgrade/migration testing.
- Accessibility and usability pass.
- Documentation and clean-install verification.

**Gate:** product definition of done is satisfied.

---

## 13. Open product decisions

The user has not yet submitted the eight-question product quiz. Do not treat the defaults below as confirmed. Ask for confirmation at the next product review.

1. Reference input: upload only, supported URL providers, or both.
2. Analysis depth: visual basics, motion/layout, or full editorial analysis.
3. Unsupported features: automatic approximation, ask first, or show alternatives and let the user choose.
4. Application: exact application, content-aware adaptation, or AI recommendation with approval.
5. Editor: simple preset controls, advanced controls, or progressive simple/advanced modes.
6. Editing lifecycle: overwrite, duplicate/version, or user choice.
7. Preview: before generation, after generation, or both.
8. Ecosystem: personal library, import/export, or community/shared templates.

Recommended starting defaults:
- Support local uploads first; add URL providers individually after security and rights review.
- Analyze all dimensions in stages, while clearly labeling coverage and uncertainty.
- Never silently substitute unsupported features.
- Offer content-aware adaptation as an explicit opt-in.
- Provide simple and advanced editor modes.
- Preserve originals and create revisions/duplicates by default.
- Preview before and after generation.
- Support personal templates and import/export before community sharing.

---

## 14. Engineering execution rules

- Read `CLIPPY_MASTER.md` when available on the active migration/architecture branch and reconcile it with this document and current source.
- Inspect `git status`, current branch, remotes, recent commits, and diffs before editing.
- Do not merge the stale reference branch wholesale.
- Do not overwrite user work or force-push.
- Do not claim a feature works based only on UI wiring.
- Add regression tests with every behavior change.
- Inspect actual rendered media, not just metadata or browser preview.
- Run relevant Python tests, frontend lint/build, renderer tests, and `git diff --check`.
- Report changed files, tests, exact outcomes, risks, and unverified behavior.
- Do not commit or push implementation changes unless explicitly authorized.
- Update this specification when product decisions or architecture change.

---

## 15. Initial architecture decision

**Decision:** Treat the existing reference-template implementation as a prototype, not as the required foundation. Reuse only the parts that survive review. Build the new system around a versioned canonical template recipe, evidence-backed analysis, a shared capability model, and a deterministic application resolver. Rework or replace existing renderer/editor subsystems when parity, correctness, or maintainability evidence justifies it.

**Rationale:** The existing prototype stores a source video and a narrow technical/pacing record. The target product requires a full editing recipe and reliable application to actual renders. Extending the current manifest and UI without first establishing the domain and render contract would create a larger but still fragile prototype.


---

## Phase 0 audit addendum

The source-level Phase 0 audit is recorded separately in [TEMPLATE_REFERENCE_SYSTEM_PHASE0_AUDIT.md](./TEMPLATE_REFERENCE_SYSTEM_PHASE0_AUDIT.md).

The audit confirmed two critical architecture issues that must be addressed before broad implementation:
1. Browser preview and server-side Remotion rendering use two diverged composition trees.
2. The primary Python/FFmpeg clip-generation and editing pipeline is a separate rendering path with capabilities and semantics that are not represented by the Remotion contract.

It also recorded the current `main` CI baseline (frontend build passed; backend had 1,226 passed, 30 skipped, and 2 failed), and the branch integration risk between current `main` and the older Windows-native migration branch.

**Updated implementation gate:** do not expand the editor or commit to replacing either renderer until a canonical recipe has been proven through a small preview-to-final-render vertical slice. The user's current local Windows worktree must also be inspected before choosing the final implementation base.
