# Template System Foundation Port

**Target branch:** `feature/template-reference-workbench`  
**Base:** current `main` at `30e7686de84612446562799376e8e2c4649864ac` (after PR #19)  
**Source snapshot:** `feature/template-reference-system-clean` at `bc7f7b77444c6e57edfdddbdaad71ea17ec19f07` (PR #6)  
**Port date:** 2026-11-18

## Why this is a selective port

PR #6 is a stale, diverged development line. At the time of this port it was 127 commits ahead and 330 behind current main. It is not safe to merge or cherry-pick wholesale. This branch was created directly from the latest main commit and receives only the reusable template-domain foundation as a source snapshot.

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

The API and edit-locking tests from PR #6 are withheld for now because they test application routes/decorators that are intentionally not being ported. Two mixed domain/API test files were initially copied with those route tests still present; the first CI run exposed the coupling. The stale route-only cases have now been removed from the foundation suite and must be replaced by tests for the new analysis-job API when that API is implemented.

## Explicit non-claims

This commit does **not** provide a working Templates tab, a complete analysis job workflow, precise font identification, full visual reverse engineering, preview/render parity, generation integration, or managed/cloud template storage. The main-branch `ReferenceTemplateLibrary` remains a limited legacy reference-record UI and is not treated as the new template system.

## Next implementation sequence

1. Reconcile current Windows-native runtime and source checkout with this branch.
2. Audit the retained foundation against current main and repair regressions/dependency assumptions.
3. Build the Reference Analysis Workbench as the first major product milestone: upload, durable analysis job, deterministic evidence extraction, Gemini interpretation, detailed evidence-backed report, human correction and saving a draft template.
4. Validate analysis quality against a representative labeled reference-video corpus before starting generation integration.
5. Only after milestone acceptance, redesign and unify the preview/final rendering contracts, then plan clip-application and generation-pipeline integration.

Comparison mode C (independent normal-vs-template-directed selection) is explicitly deferred to a future update.
