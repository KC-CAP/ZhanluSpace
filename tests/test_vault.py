from __future__ import annotations

from pathlib import Path

import pytest

from zhanlu_worker.vault import (
    VaultFormatError,
    build_vault_index,
    parse_vault_markdown,
    replace_relation_block,
)


SOURCE_DOCUMENT = """---
id: source:sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
kind: file
title: 原始资料
original_name: source.md
content_sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
ingested_at: 2026-08-03T12:00:00Z
submitted_by: local-user
extractor: markdown-v1
extraction_quality: high
data_policy: personal
---

# 原始资料

可追溯的原文。
"""

TARGET_DOCUMENT = """---
id: topic:retrieval
type: topic
status: confirmed
confidence: 0.9
sources:
  - source:sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
relations: []
created: 2026-08-03
updated: 2026-08-03
---

# 知识检索

知识检索用于找到相关资料。[来源](source:sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)

<!-- knowledge-relations:start -->
## 相关知识

_暂无正式关系。_
<!-- knowledge-relations:end -->
"""

SUPPORTING_DOCUMENT = """---
id: method:hybrid-search
type: method
status: draft
confidence: 0.82
sources:
  - source:sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
relations:
  - type: supports
    target: topic:retrieval
    evidence: source:sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    confidence: 0.82
created: 2026-08-03
updated: 2026-08-03
---

# 混合检索

混合检索结合关键词和语义召回。[来源](source:sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)

<!-- knowledge-relations:start -->
## 相关知识

- 支持：[[knowledge/topics/retrieval|知识检索]]
<!-- knowledge-relations:end -->
"""


def _write_basic_vault(root: Path) -> None:
    (root / "sources" / "files" / "source").mkdir(parents=True)
    (root / "knowledge" / "topics").mkdir(parents=True)
    (root / "knowledge" / "methods").mkdir(parents=True)
    (root / "sources" / "files" / "source" / "source.md").write_text(
        SOURCE_DOCUMENT, encoding="utf-8"
    )
    (root / "knowledge" / "topics" / "retrieval.md").write_text(
        TARGET_DOCUMENT, encoding="utf-8"
    )
    (root / "knowledge" / "methods" / "hybrid-search.md").write_text(
        SUPPORTING_DOCUMENT, encoding="utf-8"
    )


def test_parses_source_and_knowledge_records(tmp_path: Path) -> None:
    _write_basic_vault(tmp_path)

    source = parse_vault_markdown(
        tmp_path / "sources" / "files" / "source" / "source.md", tmp_path
    )
    knowledge = parse_vault_markdown(
        tmp_path / "knowledge" / "methods" / "hybrid-search.md", tmp_path
    )

    assert source.record.id.startswith("source:sha256:")
    assert source.record.content_sha256 == "a" * 64
    assert knowledge.record.id == "method:hybrid-search"
    assert knowledge.record.relations[0].target == "topic:retrieval"


def test_builds_index_by_stable_id_independent_of_filename(tmp_path: Path) -> None:
    _write_basic_vault(tmp_path)
    moved = tmp_path / "knowledge" / "topics" / "renamed-file.md"
    (tmp_path / "knowledge" / "topics" / "retrieval.md").rename(moved)

    index = build_vault_index(tmp_path)

    assert index.knowledge["topic:retrieval"].relative_path.as_posix() == (
        "knowledge/topics/renamed-file.md"
    )


def test_relation_block_uses_index_path_and_preserves_other_bytes(tmp_path: Path) -> None:
    _write_basic_vault(tmp_path)
    index = build_vault_index(tmp_path)
    document = index.knowledge["method:hybrid-search"]
    original = document.raw_text.replace(
        "- 支持：[[knowledge/topics/retrieval|知识检索]]", "stale generated content"
    )

    rendered = replace_relation_block(original, document.record, index)

    expected_block = """<!-- knowledge-relations:start -->
## 相关知识

- 支持：[[knowledge/topics/retrieval|知识检索]]
<!-- knowledge-relations:end -->"""
    assert expected_block in rendered
    before_original, after_original = original.split(
        "<!-- knowledge-relations:start -->", maxsplit=1
    )
    before_rendered, after_rendered = rendered.split(
        "<!-- knowledge-relations:start -->", maxsplit=1
    )
    assert before_rendered == before_original
    assert after_rendered.split("<!-- knowledge-relations:end -->", maxsplit=1)[1] == (
        after_original.split("<!-- knowledge-relations:end -->", maxsplit=1)[1]
    )


def test_rejects_path_outside_vault(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.md"
    outside.write_text(SOURCE_DOCUMENT, encoding="utf-8")

    with pytest.raises(VaultFormatError, match="PATH_OUTSIDE_VAULT"):
        parse_vault_markdown(outside, tmp_path)


def test_rejects_unsafe_yaml_object_tag(tmp_path: Path) -> None:
    path = tmp_path / "knowledge" / "topics" / "unsafe.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        TARGET_DOCUMENT.replace("type: topic", "type: !!python/object:os.system topic"),
        encoding="utf-8",
    )

    with pytest.raises(VaultFormatError, match="INVALID_FRONTMATTER"):
        parse_vault_markdown(path, tmp_path)


def test_rejects_more_than_twenty_yaml_aliases(tmp_path: Path) -> None:
    aliases = "\n".join(f"  alias_{index}: *shared" for index in range(21))
    path = tmp_path / "knowledge" / "topics" / "aliases.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        TARGET_DOCUMENT.replace(
            "confidence: 0.9", f"confidence: &shared 0.9\nextra:\n{aliases}"
        ),
        encoding="utf-8",
    )

    with pytest.raises(VaultFormatError, match="TOO_MANY_YAML_ALIASES"):
        parse_vault_markdown(path, tmp_path)
