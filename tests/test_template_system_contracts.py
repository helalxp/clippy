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


def test_text_overlay_contract_requires_explicit_line_break_budget():
    with pytest.raises(ValidationError, match="max_lines"):
        TemplateRecipe.model_validate({
            "overlays": [{
                "id": "two-lines",
                "kind": "text",
                "text": "first\nsecond",
                "max_lines": 1,
            }],
        })


def test_text_overlay_box_must_fit_inside_canvas():
    with pytest.raises(ValidationError, match="outside the canvas"):
        TemplateRecipe.model_validate({
            "overlays": [{
                "id": "edge-copy",
                "kind": "text",
                "text": "brand",
                "text_anchor_x": 0.95,
            }],
        })


def test_text_overlay_font_asset_must_be_a_font():
    with pytest.raises(ValidationError, match="font reference"):
        TemplateDocument.model_validate({
            "id": "tpl_12345678",
            "name": "Wrong text font",
            "assets": [{
                "id": "logo",
                "path": "assets/logo.png",
                "media_type": "image/png",
                "size_bytes": 100,
                "sha256": "c" * 64,
                "width": 10,
                "height": 10,
            }],
            "recipe": {
                "overlays": [{
                    "id": "title",
                    "kind": "text",
                    "text": "Hello",
                    "font_asset_id": "logo",
                }],
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
    assert resolved.adaptation_decisions[0].accepted is False
    assert "clip override" in resolved.adaptation_decisions[0].reason
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


def test_font_reference_must_point_to_a_font_asset():
    with pytest.raises(ValidationError):
        TemplateDocument.model_validate({
            "id": "tpl_12345678",
            "name": "Wrong font asset",
            "assets": [{
                "id": "logo",
                "path": "assets/logo.png",
                "media_type": "image/png",
                "size_bytes": 100,
                "sha256": "b" * 64,
            }],
            "recipe": {
                "captions": {"font_asset_id": "logo"}
            },
        })


def test_empty_clip_override_does_not_block_adaptation():
    resolved = resolve_recipe(
        adaptations=[{
            "path": "captions.font_color",
            "value": "#123456",
            "reason": "Adapt to source palette",
        }],
        clip_overrides={"captions": {}},
    )

    assert resolved.recipe.captions.font_color == "#123456"
    assert resolved.adaptation_decisions[0].accepted is True
