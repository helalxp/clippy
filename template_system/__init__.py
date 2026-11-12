"""Clippy's canonical template domain, analysis, storage, and resolution primitives."""

from .analysis import (
    FrameSample,
    MediaProbe,
    ReferenceAnalysisCancelled,
    ReferenceAnalysisError,
    ReferenceAnalysisResult,
    analyze_reference_video,
    choose_sample_timestamps,
    detect_scene_boundaries,
    extract_sample_frames,
    probe_media,
)
from .capabilities import check_compatibility, registered_capabilities
from .ingest import StagedReference, cleanup_staged_reference, stage_reference_video
from .models import TemplateDocument, TemplateRecipe
from .resolver import ResolvedRecipe, resolve_recipe
from .visuals import FrameVisualMeasurement, VisualMeasurementError, measure_visual_samples
from .storage import (
    LocalTemplateStorage,
    TemplateAlreadyExists,
    TemplateIntegrityError,
    TemplateNotFound,
    TemplateRevisionConflict,
    TemplateStorageError,
)

__all__ = [
    "FrameSample",
    "FrameVisualMeasurement",
    "LocalTemplateStorage",
    "MediaProbe",
    "ReferenceAnalysisCancelled",
    "ReferenceAnalysisError",
    "ReferenceAnalysisResult",
    "ResolvedRecipe",
    "StagedReference",
    "TemplateAlreadyExists",
    "TemplateDocument",
    "TemplateIntegrityError",
    "TemplateNotFound",
    "TemplateRecipe",
    "TemplateRevisionConflict",
    "TemplateStorageError",
    "VisualMeasurementError",
    "analyze_reference_video",
    "check_compatibility",
    "cleanup_staged_reference",
    "choose_sample_timestamps",
    "detect_scene_boundaries",
    "extract_sample_frames",
    "measure_visual_samples",
    "probe_media",
    "registered_capabilities",
    "resolve_recipe",
    "stage_reference_video",
]
