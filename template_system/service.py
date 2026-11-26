"""Application service joining persisted templates, resolver, and render adapters."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .adapters.python_ffmpeg import PythonFFmpegAdapter, RenderResult
from .models import TemplateDocument, TemplateRecipe
from .resolver import AdaptationDecision, resolve_recipe
from .storage import LocalTemplateStorage


@dataclass(frozen=True)
class TemplateApplicationResult:
    template_id: str
    template_name: str
    template_revision: int
    recipe_hash: str
    applied_at: datetime
    render: RenderResult
    resolved_recipe: TemplateRecipe
    adaptation_decisions: tuple[AdaptationDecision, ...]
    locked_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "template_name": self.template_name,
            "template_revision": self.template_revision,
            "recipe_hash": self.recipe_hash,
            "applied_at": self.applied_at.isoformat(),
            "output_filename": self.render.output_path.name,
            "resolved_recipe": self.resolved_recipe.model_dump(mode="json", by_alias=True),
            "source_fingerprint": self.render.source_fingerprint,
            "output_fingerprint": self.render.output_fingerprint,
            "duration_seconds": self.render.duration_seconds,
            "width": self.render.width,
            "height": self.render.height,
            "frame_rate": self.render.frame_rate,
            "has_audio": self.render.has_audio,
            "compatibility": self.render.compatibility.as_dict(),
            "adaptation_decisions": [asdict(item) for item in self.adaptation_decisions],
            "locked_paths": list(self.locked_paths),
        }


class TemplateApplicationService:
    """Resolve and apply a stored template without modifying its clean source."""

    def __init__(
        self,
        storage: LocalTemplateStorage,
        adapter: PythonFFmpegAdapter | None = None,
    ):
        self.storage = storage
        self.adapter = adapter or PythonFFmpegAdapter()

    def apply(
        self,
        template_id: str,
        source_path: str | Path,
        output_path: str | Path,
        *,
        job_overrides: Mapping[str, Any] | None = None,
        clip_overrides: Mapping[str, Any] | None = None,
        locks: Mapping[str, Any] | None = None,
        allow_approximate: bool = False,
        progress_callback: Callable[[str, float], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        caption_transcript: dict[str, Any] | None = None,
        caption_split_ranges: list[tuple[float, float]] | None = None,
    ) -> TemplateApplicationResult:
        template: TemplateDocument = self.storage.get(template_id)
        resolved = resolve_recipe(
            template=template.recipe,
            job_overrides=job_overrides,
            clip_overrides=clip_overrides,
            locks=locks,
        )
        font_path = None
        font_asset_id = resolved.recipe.captions.font_asset_id if resolved.recipe.captions.enabled else None
        if font_asset_id:
            font_asset, font_path = self.storage.get_asset(template_id, font_asset_id)
            if not font_asset.media_type.startswith("font/"):
                raise ValueError("caption font_asset_id must reference a stored font asset")

        overlay_asset_paths: dict[str, Path] = {}
        overlay_font_paths: dict[str, Path] = {}
        for overlay in resolved.recipe.overlays:
            if overlay.asset_id:
                overlay_asset, overlay_asset_path = self.storage.get_asset(template_id, overlay.asset_id)
                if not overlay_asset.media_type.startswith("image/"):
                    raise ValueError("overlay asset_id must reference a stored image asset")
                overlay_asset_paths[overlay.asset_id] = overlay_asset_path
            if overlay.font_asset_id:
                overlay_font, overlay_font_path = self.storage.get_asset(template_id, overlay.font_asset_id)
                if not overlay_font.media_type.startswith("font/"):
                    raise ValueError("text overlay font_asset_id must reference a stored font asset")
                overlay_font_paths[overlay.font_asset_id] = overlay_font_path

        hook_font_path = None
        hook_font_asset_id = resolved.recipe.hook.font_asset_id if resolved.recipe.hook.enabled else None
        if hook_font_asset_id:
            hook_font_asset, hook_font_path = self.storage.get_asset(template_id, hook_font_asset_id)
            if not hook_font_asset.media_type.startswith("font/"):
                raise ValueError("hook font_asset_id must reference a stored font asset")

        rendered = self.adapter.render(
            source_path,
            output_path,
            resolved.recipe,
            allow_approximate=allow_approximate,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
            caption_transcript=caption_transcript,
            caption_split_ranges=caption_split_ranges,
            font_path=font_path,
            hook_font_path=hook_font_path,
            overlay_asset_paths=overlay_asset_paths,
            overlay_font_paths=overlay_font_paths,
        )
        return TemplateApplicationResult(
            template_id=template.id,
            template_name=template.name,
            template_revision=template.revision,
            recipe_hash=resolved.recipe_hash,
            applied_at=datetime.now(timezone.utc),
            render=rendered,
            resolved_recipe=resolved.recipe,
            adaptation_decisions=resolved.adaptation_decisions,
            locked_paths=resolved.locked_paths,
        )
