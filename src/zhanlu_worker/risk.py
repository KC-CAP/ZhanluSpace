"""Deterministic personal-mode merge risk classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .compiler import ChangeSet


@dataclass(frozen=True)
class RiskAssessment:
    level: Literal["low", "high"]
    reasons: tuple[str, ...]


def classify_risk(
    change_set: ChangeSet,
    *,
    extraction_quality: str,
    validation_ok: bool,
) -> RiskAssessment:
    reasons: set[str] = set()
    if any(change.operation in {"delete", "move"} for change in change_set.changes):
        reasons.add("DELETE_OR_MOVE")
    if any(_is_governance_path(change.path.as_posix()) for change in change_set.changes):
        reasons.add("GOVERNANCE_CHANGE")
    if any(
        action in {"contradict", "supersede"}
        for action in change_set.semantic_actions
    ):
        reasons.add("CONTRADICTS_OR_SUPERSEDES")
    if change_set.replaces_confirmed:
        reasons.add("REPLACES_CONFIRMED")
    if change_set.modified_existing_knowledge > 10:
        reasons.add("TOO_MANY_EXISTING_DOCUMENTS")
    if extraction_quality == "low":
        reasons.add("LOW_EXTRACTION_QUALITY")
    if not validation_ok:
        reasons.add("VALIDATION_FAILED")
    reasons.update(change_set.warnings)
    ordered = tuple(sorted(reasons))
    return RiskAssessment(level="high" if ordered else "low", reasons=ordered)


def _is_governance_path(path: str) -> bool:
    return path in {"_meta/schema.md", "_meta/taxonomy.md"} or path.startswith(
        ".github/"
    )
