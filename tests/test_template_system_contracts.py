import pytest
from pydantic import ValidationError

from template_system.capabilities import check_compatibility
from template_system.models import TemplateDocument, TemplateRecipe
from template_system.resolver import resolve_recipe


def test_template_document_accepts_schema_alias_and_defaults():
    document = TemplateDocument.model_validate({
        "schema": "clippy.template",
        "schema_version": 2,
        "id": "tpl_12345678",
        "name": "Podcast bold",
    })

    assert document.template_type == "clippy.template"
    assert document.schema_version == 2
    assert document.revision == 1
    assert document.recipe.canvas.width == 1080


def test_template_contract_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        TemplateRecipe.model_validate({"surprise": True})


def test_solid_background_requires_a_color():
    with pytest.raises(ValidationError):
        TemplateRecipe.model_validate({"background": {"mode": "solid"}})


def test_enabled_hook_requires_text():
    with pytest.raises(ValidationError):
        TemplateRecipe.model_validate({
            "hook": {"enabled": True, "text": ""}
        })


def test_overlay_asset_reference_must_resolve():
    with pytest.raises(ValidationError):
        TemplateDocument.model_validate({
            "id": "tpl_12345678",
            "name": "Missing logo",
            "recipe": {
                "overlays": [{
                    "id": "brand",
                    "kind": "watermark",
                    "asset_id": "logo-file",
                }]
            },
        })


def test_asset_paths_cannot_escape_template_directory():
    with pytest.raises(ValidationError):
        TemplateDocument.model_validate({
            "id": "tpl_12345678",
            "name": "Unsafe asset",
            "assets": [{
                "id": "logo",
                "path": "../outside.png",
                "media_type": "image/png",
                "size_bytes": 100,
                "sha256": "a" * 64,
            }],
        })


def test_recipe_resolution_obeys_documented_precedence():
    resolved = resolve_recipe(
        defaults={"captions": {"font_color": "#FFFFFF"}},
        template={"captions": {"enabled": True, "font_color": "#FF0000"}},
        revision={"captions": {"font_color": "#00FF00"}},
        job_overrides={"captions": {"font_size_ratio": 0.04}},
        adaptations=[{
            "path": "captions.font_color",
            "value": "#0000FF",
            "reason": "Match the source clip palette",
        }],
        clip_overrides={"captions": {"font_color": "#FFFF00"}},
    )

    assert resolved.recipe.captions.enabled is True
    assert resolved.recipe.captions.font_color == "#FFFF00"
    assert resolved.recipe.captions.font_size_ratio == 0.04
    assert resolved.adaptation_decisions[0].accepted is True
    assert len(resolved.recipe_hash) == 64


def test_explicit_lock_blocks_adaptation_and_wins_last():
    resolved = resolve_recipe(
        template={"captions": {"enabled": True, "font_color": "#FF0000"}},
        adaptations=[{
            "path": "captions.font_color",
            "value": "#00FF00",
            "reason": "AI palette match",
        }],
        clip_overrides={"captions": {"font_color": "#0000FF"}},
        locks={"captions.font_color": "#FFFFFF"},
    )

    assert resolved.recipe.captions.font_color == "#FFFFFF"
    assert resolved.adaptation_decisions[0].accepted is False
    assert "explicit lock" in resolved.adaptation_decisions[0].reason


def test_locks_must_not_overlap():
    with pytest.raises(ValueError, match="non-overlapping"):
        resolve_recipe(locks={
            "captions": {"enabled": True},
            "captions.font_color": "#FFFFFF",
        })


def test_recipe_hash_is_stable_for_equivalent_layers():
    first = resolve_recipe(template={
        "captions": {"enabled": True, "font_color": "#FF0000"},
        "hook": {"enabled": False},
    })
    second = resolve_recipe(template={
        "hook": {"enabled": False},
        "captions": {"font_color": "#FF0000", "enabled": True},
    })

    assert first.recipe_hash == second.recipe_hash


def test_renderer_capability_report_never_hides_unsupported_transition():
    recipe = TemplateRecipe.model_validate({
        "transitions": [{"kind": "dissolve", "at_seconds": 4.0}]
    })

    report = check_compatibility(recipe, "remotion_render")

    assert report.status == "incompatible"
    assert [item.feature for item in report.unsupported] == ["transitions"]


def test_default_recipe_does_not_claim_unrequested_features():
    report = check_compatibility(TemplateRecipe(), "remotion_render")

    assert report.status == "compatible"
    assert [item.feature for item in report.exact] == ["canvas"]
    assert report.approximate == ()
    assert report.unsupported == ()


def test_template_serialization_uses_public_schema_key():
    document = TemplateDocument.model_validate({
        "schema": "clippy.template",
        "id": "tpl_12345678",
        "name": "Portable",
    })

    payload = document.to_storage_dict()
    assert payload["schema"] == "clippy.template"
    assert "template_type" not in payload


def test_color_tokens_must_be_six_digit_hex():
    with pytest.raises(ValidationError):
        TemplateRecipe.model_validate({
            "captions": {"font_color": "not-a-color"}
        })


def test_safe_area_margins_cannot_consume_the_canvas():
    with pytest.raises(ValidationError):
        TemplateRecipe.model_validate({
            "canvas": {"safe_left": 0.6, "safe_right": 0.5}
        })


def test_requested_feature_is_reported_as_approximate_or_unsupported():
    recipe = TemplateRecipe.model_validate({
        "captions": {"enabled": True},
        "background": {"mode": "blur"},
    })

    report = check_compatibility(recipe, "remotion_render")

    assert report.status == "incompatible"
    assert {item.feature for item in report.approximate} == {"captions"}
    assert {item.feature for item in report.unsupported} == {"background"}
