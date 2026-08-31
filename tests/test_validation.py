from __future__ import annotations

from pathlib import Path

from zhanlu_worker.validation import validate_vault

from .test_vault import SOURCE_DOCUMENT, SUPPORTING_DOCUMENT, TARGET_DOCUMENT, _write_basic_vault


def _codes(root: Path) -> set[str]:
    return {issue.code for issue in validate_vault(root).issues}


def test_valid_vault_has_no_issues(tmp_path: Path) -> None:
    _write_basic_vault(tmp_path)

    report = validate_vault(tmp_path)

    assert report.ok is True
    assert report.issues == []


def test_duplicate_stable_id_is_reported(tmp_path: Path) -> None:
    _write_basic_vault(tmp_path)
    duplicate = tmp_path / "knowledge" / "topics" / "duplicate.md"
    duplicate.write_text(TARGET_DOCUMENT, encoding="utf-8")

    assert "DUPLICATE_KNOWLEDGE_ID" in _codes(tmp_path)


def test_missing_source_and_relation_targets_are_reported(tmp_path: Path) -> None:
    _write_basic_vault(tmp_path)
    source_path = tmp_path / "sources" / "files" / "source" / "source.md"
    source_path.unlink()
    supporting_path = tmp_path / "knowledge" / "methods" / "hybrid-search.md"
    supporting_path.write_text(
        SUPPORTING_DOCUMENT.replace("topic:retrieval", "topic:missing"), encoding="utf-8"
    )

    codes = _codes(tmp_path)

    assert "BROKEN_SOURCE_REFERENCE" in codes
    assert "BROKEN_RELATION_TARGET" in codes
    assert "BROKEN_RELATION_EVIDENCE" in codes


def test_unknown_types_and_malformed_yaml_are_reported(tmp_path: Path) -> None:
    _write_basic_vault(tmp_path)
    target = tmp_path / "knowledge" / "topics" / "retrieval.md"
    target.write_text(TARGET_DOCUMENT.replace("type: topic", "type: mystery"), encoding="utf-8")
    malformed = tmp_path / "knowledge" / "methods" / "broken.md"
    malformed.write_text("---\nid: [broken\n---\n", encoding="utf-8")

    codes = _codes(tmp_path)

    assert "INVALID_KNOWLEDGE_RECORD" in codes
    assert "INVALID_FRONTMATTER" in codes


def test_relation_display_mismatch_is_reported(tmp_path: Path) -> None:
    _write_basic_vault(tmp_path)
    supporting = tmp_path / "knowledge" / "methods" / "hybrid-search.md"
    supporting.write_text(
        SUPPORTING_DOCUMENT.replace(
            "- 支持：[[knowledge/topics/retrieval|知识检索]]", "- 支持：[[错误目标]]"
        ),
        encoding="utf-8",
    )

    assert "RELATION_BLOCK_MISMATCH" in _codes(tmp_path)


def test_invalid_source_fingerprint_is_reported(tmp_path: Path) -> None:
    _write_basic_vault(tmp_path)
    source = tmp_path / "sources" / "files" / "source" / "source.md"
    source.write_text(
        SOURCE_DOCUMENT.replace("content_sha256: " + "a" * 64, "content_sha256: short"),
        encoding="utf-8",
    )

    assert "INVALID_SOURCE_RECORD" in _codes(tmp_path)
