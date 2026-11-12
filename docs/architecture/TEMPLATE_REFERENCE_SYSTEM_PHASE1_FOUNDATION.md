# Template Reference System — Phase 1 Foundation

**Branch:** \`feature/template-reference-system\`  
**Status:** Foundation implementation committed; local test execution and renderer integration are still required.

## Delivered

The first implementation slice adds a backend domain foundation without changing existing clip-generation or editing behavior.

### 1. Strict versioned contract

\`template_system/models.py\` defines Pydantic v2 contracts for:

- Template identity, schema version, revision, timestamps and origin.
- Normalized canvas and safe-area values.
- Framing intent.
- Caption and hook styling.
- Background treatment.
- Generic overlays and referenced assets.
- Timed effects, motion and transitions.
- Editorial rhythm.
- Analysis coverage, evidence and limitations.

The public serialized discriminator is \`schema: "clippy.template"\`; schema version and user-visible revision are separate. Unknown fields are rejected. Coordinates and dimensions expressed as ratios are normalized to the canvas; timeline values are seconds; colors are six-digit sRGB hex values; font sizes are ratios of canvas height.

Asset paths must be relative and cannot contain parent traversal. Referenced overlay and evidence assets must exist in the template's asset inventory. The model exposes \`to_storage_dict()\` to serialize the public \`schema\` key rather than its internal Python field name.

### 2. Renderer capability registry

\`template_system/capabilities.py\` records support separately for:

- \`python_ffmpeg\`
- \`remotion_preview\`
- \`remotion_render\`

The registry is intentionally conservative. It reports only features requested by the recipe. A requested approximate feature produces a partial report; a requested unsupported feature makes the report incompatible. This is an assessment of the currently audited integration, not a claim about the theoretical capabilities of FFmpeg or Remotion.

The Remotion caption and hook paths are marked approximate because the preview and render composition trees have drifted. Generic transitions, background recipes, overlays, motion recipes and framing overrides remain unsupported by the Remotion contracts until adapters exist.

### 3. Deterministic recipe resolver

\`template_system/resolver.py\` resolves layers in this order:

1. Renderer defaults.
2. Template base recipe.
3. Selected revision patch.
4. Per-job overrides.
5. AI adaptation proposals.
6. Per-clip overrides.
7. Explicit property locks.

AI proposals overlapping a locked path are rejected and recorded in the resolution result. Clip overrides take precedence over AI proposals. Locks carry their selected values and are applied last. Lists replace rather than concatenate, avoiding accidental duplicate overlays or effects.

The resolver validates the final recipe and calculates a SHA-256 hash from canonical, key-sorted JSON. The hash is intended to identify the effective recipe independently of dictionary insertion order.

### 4. Tests

\`tests/test_template_system_contracts.py\` covers strict validation, schema serialization, asset references and path safety, safe areas, resolver precedence, locks, stable hashing and capability reporting.

Pydantic v2 is now declared explicitly in \`requirements.txt\`.

## Deliberately not delivered yet

This foundation is not yet wired into the production pipeline. In particular:

- No template storage API or library UI is exposed.
- No v1 prototype-manifest migration is implemented.
- No reference-video analysis pipeline is connected.
- No Python/FFmpeg or Remotion adapter consumes \`TemplateRecipe\`.
- No preview/final visual parity claim is made.
- No render transaction or atomic metadata commit is introduced.
- No managed/cloud template library is enabled.

These are intentional gates. The contract and capability model must be exercised before application routes can persist or apply templates.

## Next implementation gate

1. Run the new focused test module and the existing backend suite on the user's Windows checkout.
2. Fix any compatibility failures before adding route integration.
3. Build a Python/FFmpeg adapter for one vertical slice: canvas + caption style + hook + background, with explicit capability findings for anything not implemented.
4. Capture deterministic fixture renders and compare expected frames, bounds, timing and output metadata.
5. Only after that, add preview and Remotion adapters, using a shared contract and parity tests to address the existing composition drift.

## Branch integration note

The current feature branch contains Tauri-generated schemas and packaging metadata, but the desktop commit does not contain the Tauri application source tree. The Windows-native source integration remains a separate prerequisite and must be reconciled from the user's local checkout before claiming that this feature branch is a complete desktop application branch.
