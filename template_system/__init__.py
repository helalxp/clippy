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
from .interpretation import (
    DraftRecipeSynthesis,
    InterpretationClaim,
    InterpretationError,
    InterpretationEvidence,
    InterpretationSynthesisError,
    TemplateInterpretation,
    interpret_reference,
    interpretation_to_proposals,
    synthesize_draft_recipe,
)
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
    "DraftRecipeSynthesis",
    "InterpretationClaim",
    "InterpretationError",
    "InterpretationEvidence",
    "InterpretationSynthesisError",
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
    "TemplateInterpretation",
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
    "interpret_reference",
    "interpretation_to_proposals",
    "synthesize_draft_recipe",
    "probe_media",
    "registered_capabilities",
    "resolve_recipe",
    "stage_reference_video",
]
