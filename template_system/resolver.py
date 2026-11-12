"""Deterministic template-to-clip recipe resolution."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .models import AdaptationProposal, TemplateRecipe


@dataclass(frozen=True)
class AdaptationDecision:
    path: str
    accepted: bool
    reason: str


@dataclass(frozen=True)
class ResolvedRecipe:
    recipe: TemplateRecipe
    recipe_hash: str
    adaptation_decisions: tuple[AdaptationDecision, ...]
    locked_paths: tuple[str, ...]


def _merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Deep-merge object layers; arrays and scalars are replaced, never appended."""
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _set_path(document: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    current: Any = document
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"unknown recipe property path: {dotted_path}")
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        raise ValueError(f"unknown recipe property path: {dotted_path}")
    current[parts[-1]] = deepcopy(value)


def _paths_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(right + ".") or right.startswith(left + ".")


def _canonical_hash(recipe: TemplateRecipe) -> str:
    payload = recipe.model_dump(mode="json")
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_recipe(
    *,
    defaults: TemplateRecipe | Mapping[str, Any] | None = None,
    template: TemplateRecipe | Mapping[str, Any] | None = None,
    revision: Mapping[str, Any] | None = None,
    job_overrides: Mapping[str, Any] | None = None,
    adaptations: Sequence[AdaptationProposal | Mapping[str, Any]] = (),
    clip_overrides: Mapping[str, Any] | None = None,
    locks: Mapping[str, Any] | None = None,
) -> ResolvedRecipe:
    """Resolve a validated effective recipe using documented precedence.

    Precedence, lowest to highest:
      defaults -> template -> revision -> job -> AI adaptation -> clip overrides
      -> explicit locks.

    Adaptation proposals are applied only when they do not overlap a locked
    property. Explicit clip overrides always win over AI adaptation. Locks carry
    their chosen values and are applied last.
    """
    def as_mapping(value: TemplateRecipe | Mapping[str, Any] | None) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, TemplateRecipe):
            return value.model_dump(mode="python")
        if not isinstance(value, Mapping):
            raise TypeError("recipe layers must be mappings or TemplateRecipe objects")
        return deepcopy(dict(value))

    locked_values = dict(locks or {})
    lock_paths = tuple(sorted(locked_values))
    for index, path in enumerate(lock_paths):
        if not path or any(_paths_overlap(path, other) for other in lock_paths[index + 1:]):
            raise ValueError("locked recipe paths must be non-empty and non-overlapping")

    merged = TemplateRecipe().model_dump(mode="python")
    for layer in (
        as_mapping(defaults),
        as_mapping(template),
        as_mapping(revision),
        as_mapping(job_overrides),
    ):
        merged = _merge(merged, layer)

    decisions: list[AdaptationDecision] = []
    for raw_proposal in adaptations:
        proposal = (
            raw_proposal
            if isinstance(raw_proposal, AdaptationProposal)
            else AdaptationProposal.model_validate(raw_proposal)
        )
        blocker = next(
            (locked for locked in lock_paths if _paths_overlap(proposal.path, locked)),
            None,
        )
        if blocker is not None:
            decisions.append(
                AdaptationDecision(
                    path=proposal.path,
                    accepted=False,
                    reason=f"blocked by explicit lock: {blocker}",
                )
            )
            continue
        _set_path(merged, proposal.path, proposal.value)
        decisions.append(
            AdaptationDecision(
                path=proposal.path,
                accepted=True,
                reason=proposal.reason,
            )
        )

    merged = _merge(merged, as_mapping(clip_overrides))
    for path, value in locked_values.items():
        _set_path(merged, path, value)

    recipe = TemplateRecipe.model_validate(merged)
    return ResolvedRecipe(
        recipe=recipe,
        recipe_hash=_canonical_hash(recipe),
        adaptation_decisions=tuple(decisions),
        locked_paths=lock_paths,
    )
