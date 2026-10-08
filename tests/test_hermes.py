from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pytest

from zhanlu_worker.hermes import (
    HermesAdapter,
    HermesConfig,
    HermesError,
    KnowledgeContext,
    select_context,
)
from zhanlu_worker.sources import NormalizedSource
from zhanlu_worker.vault import KnowledgeRecord, VaultDocument


FIXTURES = Path(__file__).parent / "fixtures"
SOURCE_ID = "source:sha256:" + "a" * 64


def _source() -> NormalizedSource:
    return NormalizedSource(
        source_id=SOURCE_ID,
        kind="file",
        title="混合检索资料",
        normalized_text="# 混合检索\n\n混合检索结合关键词和语义召回。\n",
        content_sha256="a" * 64,
        original_name="source.md",
        source_url=None,
        final_url=None,
        canonical_url=None,
        retrieved_at=datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
        extractor="markdown-v1",
        extraction_quality="high",
    )


def _adapter(tmp_path: Path, mode: str = "valid", timeout: float = 2) -> HermesAdapter:
    environment = {
        "FAKE_HERMES_MODE": mode,
        "FAKE_HERMES_RESPONSE": str(FIXTURES / "hermes" / "create.json"),
    }
    return HermesAdapter(
        HermesConfig(
            executable=sys.executable,
            launcher_args=(str(FIXTURES / "bin" / "fake-hermes.py"),),
            profile="personal-test",
            timeout_seconds=timeout,
            environment=environment,
        )
    )


def test_invokes_one_shot_hermes_in_job_directory_with_bounded_prompt(
    tmp_path: Path,
) -> None:
    context = [
        KnowledgeContext(
            knowledge_id="topic:retrieval",
            title="知识检索",
            status="confirmed",
            source_ids=[SOURCE_ID],
            relations=[],
            body_excerpt="检索用于找到相关资料。",
        )
    ]

    proposal = _adapter(tmp_path).compile(_source(), context, tmp_path)

    assert proposal.actions[0].action == "create"
    invocation = json.loads((tmp_path / "invocation.json").read_text(encoding="utf-8"))
    assert invocation["cwd"] == str(tmp_path)
    assert invocation["argv"][:-1] == [
        "--profile",
        "personal-test",
        "--ignore-rules",
        "-z",
    ]
    assert "UNTRUSTED SOURCE" in invocation["prompt"]
    assert "混合检索结合关键词和语义召回" in invocation["prompt"]
    assert "topic:retrieval" in invocation["prompt"]
    assert str(tmp_path) not in invocation["prompt"]


def test_prompt_embeds_machine_readable_schema_for_every_action(tmp_path: Path) -> None:
    _adapter(tmp_path).compile(_source(), [], tmp_path)

    prompt = json.loads((tmp_path / "invocation.json").read_text(encoding="utf-8"))[
        "prompt"
    ]
    schema_text = prompt.split("BEGIN TRUSTED OUTPUT JSON SCHEMA\n", 1)[1].split(
        "\nEND TRUSTED OUTPUT JSON SCHEMA", 1
    )[0]
    schema = json.loads(schema_text)

    assert set(schema["$defs"]["CreateAction"]["required"]) == {
        "action",
        "knowledge_id",
        "title",
        "knowledge_type",
        "status",
        "confidence",
        "content",
        "citations",
    }
    assert set(schema["$defs"]["ExistingAction"]["required"]) == {
        "action",
        "target_id",
        "confidence",
        "content",
        "citations",
    }
    assert set(schema["$defs"]["SupersedeAction"]["required"]) == {
        "action",
        "target_id",
        "replacement_id",
        "title",
        "knowledge_type",
        "status",
        "confidence",
        "content",
        "citations",
    }
    assert set(schema["$defs"]["NoChangeAction"]["required"]) == {
        "action",
        "reason",
    }
    action_items = schema["properties"]["actions"]["items"]
    assert {item["$ref"] for item in action_items["oneOf"]} == {
        "#/$defs/CreateAction",
        "#/$defs/ExistingAction",
        "#/$defs/SupersedeAction",
        "#/$defs/NoChangeAction",
    }
    assert action_items["discriminator"] == {
        "propertyName": "action",
        "mapping": {
            "create": "#/$defs/CreateAction",
            "supplement": "#/$defs/ExistingAction",
            "support": "#/$defs/ExistingAction",
            "contradict": "#/$defs/ExistingAction",
            "cite-only": "#/$defs/ExistingAction",
            "supersede": "#/$defs/SupersedeAction",
            "no-change": "#/$defs/NoChangeAction",
        },
    }


@pytest.mark.parametrize(
    ("mode", "code", "retryable", "timeout"),
    (
        ("invalid-json", "HERMES_INVALID_JSON", False, 2.0),
        ("invalid-proposal", "HERMES_INVALID_PROPOSAL", False, 2.0),
        ("exit", "HERMES_FAILED", True, 2.0),
        ("agent-failed", "HERMES_FAILED", True, 2.0),
        ("sleep", "HERMES_TIMEOUT", True, 0.05),
    ),
)
def test_rejects_failed_or_invalid_hermes_results(
    tmp_path: Path, mode: str, code: str, retryable: bool, timeout: float
) -> None:
    with pytest.raises(HermesError) as caught:
        _adapter(tmp_path, mode=mode, timeout=timeout).compile(_source(), [], tmp_path)

    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert "sk-secret-value" not in str(caught.value)


def _document(index: int, title: str, body: str) -> VaultDocument:
    record = KnowledgeRecord(
        id=f"topic:item-{index}",
        type="topic",
        status="confirmed",
        confidence=0.8,
        sources=[SOURCE_ID],
        relations=[],
        created="2026-08-03",
        updated="2026-08-03",
    )
    return VaultDocument(
        record=record,
        relative_path=PurePosixPath(f"knowledge/topics/item-{index}.md"),
        raw_text=body,
        body=body,
        title=title,
    )


def test_context_selection_is_relevant_bounded_and_deterministic() -> None:
    documents = [
        _document(index, f"无关条目 {index}", "天气与旅行") for index in range(24)
    ]
    documents.extend(
        [
            _document(30, "混合检索", "关键词 语义 召回"),
            _document(29, "语义检索", "向量 语义 召回"),
        ]
    )

    selected = select_context("混合检索使用语义召回", documents)

    assert len(selected) <= 20
    assert [item.knowledge_id for item in selected[:2]] == [
        "topic:item-30",
        "topic:item-29",
    ]
    assert len(json.dumps([item.to_prompt_dict() for item in selected]).encode("utf-8")) <= 60_000
