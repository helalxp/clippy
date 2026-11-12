"""Clippy's canonical template domain and recipe resolution primitives."""

from .capabilities import check_compatibility, registered_capabilities
from .models import TemplateDocument, TemplateRecipe
from .resolver import ResolvedRecipe, resolve_recipe

__all__ = [
    "ResolvedRecipe",
    "TemplateDocument",
    "TemplateRecipe",
    "check_compatibility",
    "registered_capabilities",
    "resolve_recipe",
]
