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
        "framing": FeatureCapability("framing", "exact", "The canonical FFmpeg adapter implements deterministic cover, contain, and anchored crop modes; subject tracking is explicitly unsupported."),
        "safe_area": FeatureCapability("safe_area", "unsupported", "The first FFmpeg adapter does not place captions or overlays against canonical safe-area margins."),
        "captions": FeatureCapability("captions", "unsupported", "The first FFmpeg adapter does not yet translate canonical caption recipes into ASS subtitle styling."),
        "hook": FeatureCapability("hook", "unsupported", "The first FFmpeg adapter does not yet translate canonical hook typography and animation."),
        "background": FeatureCapability("background", "exact", "The FFmpeg adapter implements black/original matte, blurred duplicate, and solid-color contain backgrounds; background fill is incompatible with cover crop."),
        "overlays": FeatureCapability("overlays", "unsupported", "The first FFmpeg adapter does not implement the generic overlay collection."),
        "effects": FeatureCapability("effects", "unsupported", "The first FFmpeg adapter does not implement canonical effect segments."),
        "motion": FeatureCapability("motion", "unsupported", "The first FFmpeg adapter does not implement canonical motion recipes."),
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



def _capability_for_recipe(
    recipe: TemplateRecipe,
    backend: RendererBackend,
    feature: str,
    registered: FeatureCapability,
) -> FeatureCapability:
    """Refine broad feature support when a specific recipe combination conflicts."""
    if backend != "python_ffmpeg":
        return registered
    if feature == "framing":
        if recipe.framing.subject_tracking:
            return FeatureCapability(
                "framing", "unsupported",
                "The first adapter does not implement subject tracking.",
            )
        contain_mode = (
            recipe.framing.mode == "contain"
            or (recipe.framing.mode == "auto" and recipe.background.mode != "original")
        )
        if contain_mode and (
            recipe.framing.anchor_x != 0.5 or recipe.framing.anchor_y != 0.5
        ):
            return FeatureCapability(
                "framing", "unsupported",
                "Contain framing is centered; custom anchors are supported only for cover/manual crop.",
            )
        return registered
    if feature == "background":
        if recipe.framing.mode in {"cover", "manual"}:
            return FeatureCapability(
                "background", "unsupported",
                "Cover/manual crop fills the canvas, so a separate background treatment would be invisible.",
            )
        return registered
    return registered


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
        capability = _capability_for_recipe(recipe, backend, feature, registry[feature])
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
