# Template System Foundation Port

**Target branch:** `feature/template-reference-workbench-current-main`  
**Base:** current `main` at `c402e3adbe8205802c9d3786a660ca7285c1faef`  
**Workbench source:** `feature/template-reference-workbench` at `e7b8e3ac6d3da4f2023c7076f44c18f411513892` (PR #20)  
**Domain source snapshot:** `feature/template-reference-system-clean` at `bc7f7b77444c6e57edfdddbdaad71ea17ec19f07` (PR #6)  
**Port date:** 2026-11-26

## Why this is a selective port

PR #6 is a stale, diverged development line. The subsequent review found it 127 commits ahead and 424 behind current main; PR #20 was itself 51 commits ahead and 94 behind. Neither line was safe to merge wholesale. This fresh branch starts from current main and selectively ports the PR #20 workbench, its tests and docs, plus the reusable template-domain foundation originally developed on PR #6. It intentionally does not import the old PR histories.

## Retained foundation

- Canonical, versioned template contracts and claim/evidence models.
- Deterministic reference media probing, frame sampling, scene analysis and visual measurements.
- Provider-neutral interpretation and user-review/synthesis logic.
- Consent-gated Gemini structured-output adapter.
- Capability registry and compatibility preflight.
- Local template storage, revision checks, integrity validation and locking.
- Template resolver, application service and portable package import/export.
- Isolated Python/FFmpeg renderer and its caption, hook, motion/effect and text-overlay adapters.
- Domain-level tests for the above modules.

The current `main` requirements already include `google-genai==1.75.0`, Pillow, FastAPI and the existing media stack. This port therefore does not change dependency pins.

## Intentionally not ported

The following files and changes from PR #6 are withheld because they couple the old implementation to application and pipeline behavior that must be redesigned against current main:

- `app.py` template CRUD/apply route changes.
- `clip_selection.py` template influence.
- `recut.py` integration changes.
- The old branch's CI workflow changes.
- The old implementation tracker/spec/stage documents, which are superseded by the current product blueprint.

The API and edit-locking tests from PR #6 are also withheld for now because they test application routes/decorators that are intentionally not being ported. They must be rewritten against the current main API and the staged analysis-workbench design.

## Explicit non-claims

This port now includes the Templates workbench screen and its local reference-analysis workflow: durable jobs, deterministic media analysis, optional consent-gated Gemini interpretation, evidence review/correction, and saving an accepted subset as a local template draft. It does **not** provide precise original-font identification or exhaustive frame-by-frame reverse engineering. The saved-draft area is currently a read-only list, not a complete template detail/editor workflow; a read-only renderer-compatibility preflight is now surfaced for Python/FFmpeg, Remotion preview and Remotion render; the template detail/editor workflow is still missing. Preview/final parity and generation integration are not implemented. Managed/cloud template storage remains disabled until account-scoped storage and media delivery exist.

## Next implementation sequence

1. Keep the fresh-main port green across focused template tests, backend CI, frontend build and Windows installer validation; address failures before widening scope.
2. Validate analysis quality against a representative manually labeled reference-video corpus, including false claims, missed findings, geometry/timing error and top-k font-candidate accuracy.
3. Complete the local template library/editor workflow: detail inspection, supported metadata/recipe editing, revision-safe saves and safe deletion. Build on the now-visible compatibility reports for each renderer.
4. Unify preview/final rendering contracts and close unsupported or approximate capability gaps without silently dropping requested behavior.
5. Add explicit user-approved single-clip template application; only then consider batch or normal generation-pipeline integration. Keep managed/cloud storage deferred until ownership and media-delivery boundaries are designed.

Comparison mode C (independent normal-vs-template-directed selection) is explicitly deferred to a future update.


## Fresh-main port record — 2026-11-26

- After `main` advanced 136 commits beyond the earlier PR #39 base, this workbench was re-ported onto a fresh branch from current `main` at `c402e3adbe8205802c9d3786a660ca7285c1faef`. The previous PR #20 `app.py` was not copied over the current application file; the workbench routes, startup recovery, and media-token exceptions were selectively integrated, preserving newer Community Highlights lifecycle and diagnostics.
- Reference-analysis background workers use the existing `_create_data_background_task` helper, which participates in the current desktop maintenance handshake.
- The workbench domain package, UI, correction editor, media-token allowlist changes, architecture notes and focused test modules were selectively carried forward.
- Windows payload assembly, payload-contract tests, runtime smoke imports, and native-supervisor validation now require the `template_system` package.
- The Templates upload forwards the browser-local Gemini key through `X-Gemini-Key` only with explicit Gemini consent. API failure diagnostics include correlation IDs and tracebacks without logging key values.
- The previous PR #6/#7/#20 records are retained closed for history. Their remote branches are not deleted, so the source remains recoverable if a later audit identifies a needed implementation detail.
