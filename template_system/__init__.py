"""Clippy's canonical template domain, storage, and recipe resolution primitives."""

from .capabilities import check_compatibility, registered_capabilities
from .models import TemplateDocument, TemplateRecipe
from .resolver import ResolvedRecipe, resolve_recipe
from .storage import (
    LocalTemplateStorage,
    TemplateAlreadyExists,
    TemplateIntegrityError,
    TemplateNotFound,
    TemplateRevisionConflict,
    TemplateStorageError,
)

__all__ = [
    "LocalTemplateStorage",
    "ResolvedRecipe",
    "TemplateAlreadyExists",
    "TemplateDocument",
    "TemplateIntegrityError",
    "TemplateNotFound",
    "TemplateRecipe",
    "TemplateRevisionConflict",
    "TemplateStorageError",
    "check_compatibility",
    "registered_capabilities",
    "resolve_recipe",
]
