from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from zhanlu_worker.compiler import ChangeSet, FileChange
from zhanlu_worker.risk import classify_risk


def _change(path: str, operation: str = "create") -> FileChange:
    return FileChange(
        operation=operation,
        path=PurePosixPath(path),
        content=b"content",
        before_sha256=None if operation == "create" else "a" * 64,
        after_sha256="ed7002b439e9ac845f22357d822bac14447392325dcb1d95bb9f08fd1c57a5b2",
    )


def _change_set(**overrides) -> ChangeSet:
    values = {
        "ingest_id": "44444444-4444-4444-8444-444444444444",
        "source_id": "source:sha256:" + "a" * 64,
        "changes": (_change("knowledge/topics/new.md"),),
        "semantic_actions": ("create",),
        "relation_changes": (),
        "warnings": (),
        "modified_existing_knowledge": 0,
        "replaces_confirmed": False,
    }
    values.update(overrides)
    return ChangeSet(**values)


def test_new_valid_knowledge_is_low_risk() -> None:
    assessment = classify_risk(
        _change_set(), extraction_quality="high", validation_ok=True
    )

    assert assessment.level == "low"
    assert assessment.reasons == ()


@pytest.mark.parametrize(
    ("change_set", "quality", "validation_ok", "reason"),
    (
        (_change_set(changes=(_change("knowledge/old.md", "delete"),)), "high", True, "DELETE_OR_MOVE"),
        (_change_set(changes=(_change("_meta/schema.md", "update"),)), "high", True, "GOVERNANCE_CHANGE"),
        (_change_set(semantic_actions=("contradict",)), "high", True, "CONTRADICTS_OR_SUPERSEDES"),
        (_change_set(semantic_actions=("supersede",)), "high", True, "CONTRADICTS_OR_SUPERSEDES"),
        (_change_set(replaces_confirmed=True), "high", True, "REPLACES_CONFIRMED"),
        (_change_set(modified_existing_knowledge=11), "high", True, "TOO_MANY_EXISTING_DOCUMENTS"),
        (_change_set(), "low", True, "LOW_EXTRACTION_QUALITY"),
        (_change_set(), "high", False, "VALIDATION_FAILED"),
        (_change_set(warnings=("SENSITIVE_CONTENT",)), "high", True, "SENSITIVE_CONTENT"),
    ),
)
def test_high_risk_conditions_have_stable_reason_codes(
    change_set: ChangeSet, quality: str, validation_ok: bool, reason: str
) -> None:
    assessment = classify_risk(
        change_set, extraction_quality=quality, validation_ok=validation_ok
    )

    assert assessment.level == "high"
    assert reason in assessment.reasons
