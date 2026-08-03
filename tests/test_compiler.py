from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from zhanlu_worker.compiler import ChangeCompiler, CompileMetadata, FileChange
from zhanlu_worker.proposals import CompilationProposal
from zhanlu_worker.sources import acquire_file
from zhanlu_worker.validation import validate_vault

from .test_vault import _write_basic_vault


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
INGEST_ID = "44444444-4444-4444-8444-444444444444"


def _source(tmp_path: Path):
    path = tmp_path / "incoming.md"
    path.write_text("# 混合检索\n\n新来源说明关键词与语义召回互补。\n", encoding="utf-8")
    return path, acquire_file(path, now=lambda: NOW)


def _proposal(source_id: str, action: dict[str, object]) -> CompilationProposal:
    return CompilationProposal.model_validate(
        {"schema_version": 1, "source_id": source_id, "actions": [action]}
    )


def _metadata() -> CompileMetadata:
    return CompileMetadata(
        ingest_id=INGEST_ID,
        submitted_by="local-user",
        hermes_version="0.19.1",
        hermes_profile="personal-test",
        compiler_version="0.1.0",
        schema_version=1,
        created_at=NOW,
    )


def _apply(root: Path, changes: tuple[FileChange, ...]) -> None:
    for change in changes:
        path = root / Path(change.path.as_posix())
        path.parent.mkdir(parents=True, exist_ok=True)
        if change.operation in {"create", "update"}:
            path.write_bytes(change.content)


def test_create_derives_paths_and_traceable_markdown(tmp_path: Path) -> None:
    _write_basic_vault(tmp_path)
    source_path, source = _source(tmp_path)
    proposal = _proposal(
        source.source_id,
        {
            "action": "create",
            "knowledge_id": "method:hybrid-search-v2",
            "title": "混合检索 V2",
            "knowledge_type": "method",
            "status": "draft",
            "confidence": 0.82,
            "content": "混合检索组合两类召回。",
            "citations": [source.source_id],
            "relations": [
                {
                    "type": "supports",
                    "target": "topic:retrieval",
                    "evidence": source.source_id,
                    "confidence": 0.82,
                }
            ],
        },
    )

    change_set = ChangeCompiler(tmp_path).compile(
        source, proposal, _metadata(), original_path=source_path
    )

    paths = {change.path.as_posix() for change in change_set.changes}
    digest = source.content_sha256
    assert f"sources/files/{digest}/source.md" in paths
    assert f"sources/files/{digest}/original.md" in paths
    assert "knowledge/methods/hybrid-search-v2.md" in paths
    assert f"_meta/ingests/{INGEST_ID}.md" in paths
    knowledge = next(
        change.content.decode("utf-8")
        for change in change_set.changes
        if change.path.as_posix() == "knowledge/methods/hybrid-search-v2.md"
    )
    assert f"[来源：`{source.source_id}`]" in knowledge
    assert "target: topic:retrieval" in knowledge
    assert "[[knowledge/topics/retrieval|知识检索]]" in knowledge


def test_existing_document_is_located_by_id_and_supplemented_without_replacement(
    tmp_path: Path,
) -> None:
    _write_basic_vault(tmp_path)
    target = tmp_path / "knowledge" / "topics" / "retrieval.md"
    renamed = target.with_name("custom-name.md")
    target.rename(renamed)
    source_path, source = _source(tmp_path)
    proposal = _proposal(
        source.source_id,
        {
            "action": "supplement",
            "target_id": "topic:retrieval",
            "confidence": 0.76,
            "content": "补充混合召回的实现条件。",
            "citations": [source.source_id],
            "relations": [],
        },
    )

    change_set = ChangeCompiler(tmp_path).compile(
        source, proposal, _metadata(), original_path=source_path
    )

    update = next(
        change
        for change in change_set.changes
        if change.path.as_posix() == "knowledge/topics/custom-name.md"
    )
    rendered = update.content.decode("utf-8")
    assert "知识检索用于找到相关资料" in rendered
    assert "补充混合召回的实现条件" in rendered
    assert rendered.count(source.source_id) >= 2
    assert update.before_sha256 is not None


def test_contradiction_preserves_claim_and_marks_document_contested(tmp_path: Path) -> None:
    _write_basic_vault(tmp_path)
    source_path, source = _source(tmp_path)
    proposal = _proposal(
        source.source_id,
        {
            "action": "contradict",
            "target_id": "topic:retrieval",
            "confidence": 0.71,
            "content": "专有名词场景下纯语义召回可能退化。",
            "citations": [source.source_id],
            "relations": [],
        },
    )

    change_set = ChangeCompiler(tmp_path).compile(
        source, proposal, _metadata(), original_path=source_path
    )

    update = next(
        change.content.decode("utf-8")
        for change in change_set.changes
        if change.path.as_posix() == "knowledge/topics/retrieval.md"
    )
    assert "status: contested" in update
    assert "知识检索用于找到相关资料" in update
    assert "## 冲突观点" in update
    assert change_set.semantic_actions == ("contradict",)


def test_supersede_updates_old_status_and_creates_replacement(tmp_path: Path) -> None:
    _write_basic_vault(tmp_path)
    source_path, source = _source(tmp_path)
    proposal = _proposal(
        source.source_id,
        {
            "action": "supersede",
            "target_id": "topic:retrieval",
            "replacement_id": "topic:hybrid-retrieval",
            "title": "混合知识检索",
            "knowledge_type": "topic",
            "status": "draft",
            "confidence": 0.79,
            "content": "混合知识检索取代单一路径。",
            "citations": [source.source_id],
            "relations": [],
        },
    )

    change_set = ChangeCompiler(tmp_path).compile(
        source, proposal, _metadata(), original_path=source_path
    )

    by_path = {change.path.as_posix(): change.content.decode("utf-8") for change in change_set.changes}
    assert "status: superseded" in by_path["knowledge/topics/retrieval.md"]
    assert "knowledge/topics/hybrid-retrieval.md" in by_path
    assert "type: supersedes" in by_path["knowledge/topics/hybrid-retrieval.md"]
    assert "target: topic:retrieval" in by_path["knowledge/topics/hybrid-retrieval.md"]


def test_no_change_records_new_source_but_fully_recorded_duplicate_is_idempotent(
    tmp_path: Path,
) -> None:
    _write_basic_vault(tmp_path)
    source_path, source = _source(tmp_path)
    proposal = _proposal(
        source.source_id,
        {"action": "no-change", "reason": "内容已覆盖。"},
    )
    compiler = ChangeCompiler(tmp_path)

    first = compiler.compile(source, proposal, _metadata(), original_path=source_path)
    _apply(tmp_path, first.changes)
    second = compiler.compile(source, proposal, _metadata(), original_path=source_path)

    assert any(change.path.name == "source.md" for change in first.changes)
    assert second.changes == ()
    assert validate_vault(tmp_path).ok is True


def test_applying_same_create_change_set_twice_is_idempotent(tmp_path: Path) -> None:
    _write_basic_vault(tmp_path)
    source_path, source = _source(tmp_path)
    proposal = _proposal(
        source.source_id,
        {
            "action": "create",
            "knowledge_id": "method:hybrid-search-v2",
            "title": "混合检索 V2",
            "knowledge_type": "method",
            "status": "draft",
            "confidence": 0.82,
            "content": "混合检索组合两类召回。",
            "citations": [source.source_id],
            "relations": [],
        },
    )
    compiler = ChangeCompiler(tmp_path)

    first = compiler.compile(source, proposal, _metadata(), original_path=source_path)
    _apply(tmp_path, first.changes)
    second = compiler.compile(source, proposal, _metadata(), original_path=source_path)

    assert second.changes == ()
    assert validate_vault(tmp_path).ok is True


def test_index_and_manifest_are_deterministically_sorted(tmp_path: Path) -> None:
    _write_basic_vault(tmp_path)
    source_path, source = _source(tmp_path)
    proposal = _proposal(
        source.source_id,
        {
            "action": "create",
            "knowledge_id": "note:zeta",
            "title": "甲条目",
            "knowledge_type": "note",
            "status": "draft",
            "confidence": 0.7,
            "content": "新增条目。",
            "citations": [source.source_id],
            "relations": [],
        },
    )

    result = ChangeCompiler(tmp_path).compile(
        source, proposal, _metadata(), original_path=source_path
    )

    index = next(
        change.content.decode("utf-8")
        for change in result.changes
        if change.path.as_posix() == "_meta/index.md"
    )
    manifest = next(
        change.content.decode("utf-8")
        for change in result.changes
        if change.path.as_posix() == f"_meta/ingests/{INGEST_ID}.md"
    )
    assert index.index("## method") < index.index("## note") < index.index("## topic")
    assert "Hermes: `0.19.1` / `personal-test`" in manifest
    assert manifest.index("## 变更文件") < manifest.index("## 语义动作")
