"""Conservative renderer capability registry for template compatibility checks.

A capability is marked exact only when the current renderer contract is known to
implement the requested behavior. "Approximate" is intentionally not treated as
full support, and unsupported properties are never silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import TemplateRecipe

RendererBackend = Literal["python_ffmpeg", "remotion_preview", "remotion_render"]
SupportLevel = Literal["exact", "approximate", "unsupported"]


@dataclass(frozen=True)
class FeatureCapability:
    feature: str
    level: SupportLevel
    explanation: str


@dataclass(frozen=True)
class CompatibilityFinding:
    feature: str
    level: SupportLevel
    explanation: str


@dataclass(frozen=True)
class CompatibilityReport:
    backend: RendererBackend
    status: Literal["compatible", "partial", "incompatible"]
    exact: tuple[CompatibilityFinding, ...]
    approximate: tuple[CompatibilityFinding, ...]
    unsupported: tuple[CompatibilityFinding, ...]

    def as_dict(self) -> dict:
        return {
            "backend": self.backend,
            "status": self.status,
            "exact": [item.__dict__ for item in self.exact],
            "approximate": [item.__dict__ for item in self.approximate],
            "unsupported": [item.__dict__ for item in self.unsupported],
        }


# These are deliberately conservative. They describe the audited implementation,
# not the theoretical abilities of FFmpeg or Remotion.
_REGISTRY: dict[RendererBackend, dict[str, FeatureCapability]] = {
    "python_ffmpeg": {
        "canvas": FeatureCapability("canvas", "exact", "Output dimensions and frame rate are explicit pipeline inputs."),
        "framing": FeatureCapability("framing", "approximate", "Automatic scene framing and manual crop overrides exist, but normalized template anchors do not yet have a canonical adapter."),
        "safe_area": FeatureCapability("safe_area", "approximate", "Some existing overlay placement uses margins, but the canonical safe-area contract is not wired through the pipeline."),
        "captions": FeatureCapability("captions", "approximate", "ASS subtitle burning supports rich timing and styling, but the template caption contract is not yet translated."),
        "hook": FeatureCapability("hook", "approximate", "Hook rendering and placement exist, but template typography and animation semantics are not yet mapped."),
        "background": FeatureCapability("background", "approximate", "Blur and solid-background editing exists through a separate derivative endpoint."),
        "overlays": FeatureCapability("overlays", "approximate", "Watermark rendering exists, but the generic overlay layer is not implemented."),
        "effects": FeatureCapability("effects", "approximate", "Punch-in and selected image adjustments exist; the canonical effect timeline is not mapped."),
        "motion": FeatureCapability("motion", "approximate", "Punch-in motion exists, but generic motion recipes are not mapped."),
        "transitions": FeatureCapability("transitions", "unsupported", "No canonical transition adapter is present in the audited pipeline."),
        "rhythm": FeatureCapability("rhythm", "unsupported", "Rhythm is analysis metadata only; it is not applied as an edit recipe."),
    },
    "remotion_preview": {
        "canvas": FeatureCapability("canvas", "exact", "The browser Player receives explicit composition dimensions and frame rate."),
        "framing": FeatureCapability("framing", "unsupported", "The preview composition does not consume the canonical framing recipe."),
        "safe_area": FeatureCapability("safe_area", "unsupported", "The preview composition does not consume canonical safe-area margins."),
        "captions": FeatureCapability("captions", "approximate", "The dashboard composition supports captions, but its config schema and renderer semantics have drifted."),
        "hook": FeatureCapability("hook", "approximate", "The preview supports a narrower hook contract than the canonical template recipe."),
        "background": FeatureCapability("background", "unsupported", "The preview composition has no canonical background recipe input."),
        "overlays": FeatureCapability("overlays", "unsupported", "The preview composition has no generic overlay collection."),
        "effects": FeatureCapability("effects", "approximate", "The preview supports a limited effects segment contract."),
        "motion": FeatureCapability("motion", "unsupported", "Generic motion recipes are not consumed by the preview composition."),
        "transitions": FeatureCapability("transitions", "unsupported", "Transitions are not represented in the preview composition contract."),
        "rhythm": FeatureCapability("rhythm", "unsupported", "Rhythm is not consumed by the preview composition."),
    },
    "remotion_render": {
        "canvas": FeatureCapability("canvas", "exact", "The render service selects a composition with explicit dimensions and frame rate."),
        "framing": FeatureCapability("framing", "unsupported", "The render composition does not consume the canonical framing recipe."),
        "safe_area": FeatureCapability("safe_area", "unsupported", "The render composition does not consume canonical safe-area margins."),
        "captions": FeatureCapability("captions", "approximate", "The root composition supports a narrower caption contract than the dashboard preview."),
        "hook": FeatureCapability("hook", "approximate", "The root composition supports a narrower hook contract than the canonical template recipe."),
        "background": FeatureCapability("background", "unsupported", "The render composition has no canonical background recipe input."),
        "overlays": FeatureCapability("overlays", "unsupported", "The render composition has no generic overlay collection."),
        "effects": FeatureCapability("effects", "approximate", "The render service supports a limited effects segment contract."),
        "motion": FeatureCapability("motion", "unsupported", "Generic motion recipes are not consumed by the render composition."),
        "transitions": FeatureCapability("transitions", "unsupported", "Transitions are not represented in the render composition contract."),
        "rhythm": FeatureCapability("rhythm", "unsupported", "Rhythm is not consumed by the render composition."),
    },
}


def registered_capabilities(backend: RendererBackend) -> tuple[FeatureCapability, ...]:
    """Return the immutable capability description for one renderer."""
    return tuple(_REGISTRY[backend].values())


def _requested_features(recipe: TemplateRecipe) -> set[str]:
    requested = {"canvas"}
    # The renderer default is not a template override. Report framing only when
    # the template asks for behavior beyond the existing centered/automatic path.
    if (
        recipe.framing.mode != "auto"
        or recipe.framing.subject_tracking
        or recipe.framing.anchor_x != 0.5
        or recipe.framing.anchor_y != 0.5
    ):
        requested.add("framing")
    if (
        recipe.canvas.safe_top != 0.05
        or recipe.canvas.safe_right != 0.05
        or recipe.canvas.safe_bottom != 0.08
        or recipe.canvas.safe_left != 0.05
    ):
        requested.add("safe_area")
    if recipe.captions.enabled:
        requested.add("captions")
    if recipe.hook.enabled:
        requested.add("hook")
    if recipe.background.mode != "original":
        requested.add("background")
    if recipe.overlays:
        requested.add("overlays")
    if recipe.effects:
        requested.add("effects")
    if recipe.motion:
        requested.add("motion")
    if recipe.transitions:
        requested.add("transitions")
    if recipe.rhythm.pace != "balanced" or recipe.rhythm.target_shot_seconds is not None or recipe.rhythm.target_cuts_per_minute is not None:
        requested.add("rhythm")
    return requested


def check_compatibility(
    recipe: TemplateRecipe,
    backend: RendererBackend,
) -> CompatibilityReport:
    """Report only features the recipe actually requests.

    An approximate or unsupported feature is surfaced explicitly; callers must
    not interpret this report as permission to silently drop that feature.
    """
    registry = _REGISTRY[backend]
    exact: list[CompatibilityFinding] = []
    approximate: list[CompatibilityFinding] = []
    unsupported: list[CompatibilityFinding] = []

    for feature in sorted(_requested_features(recipe)):
        capability = registry[feature]
        finding = CompatibilityFinding(
            feature=capability.feature,
            level=capability.level,
            explanation=capability.explanation,
        )
        if capability.level == "exact":
            exact.append(finding)
        elif capability.level == "approximate":
            approximate.append(finding)
        else:
            unsupported.append(finding)

    status: Literal["compatible", "partial", "incompatible"]
    if unsupported:
        status = "incompatible"
    elif approximate:
        status = "partial"
    else:
        status = "compatible"

    return CompatibilityReport(
        backend=backend,
        status=status,
        exact=tuple(exact),
        approximate=tuple(approximate),
        unsupported=tuple(unsupported),
    )
