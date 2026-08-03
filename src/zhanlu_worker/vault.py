"""Portable Markdown/YAML schema for a Zhanlu knowledge Vault."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Literal, TypeAlias

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
from yaml.tokens import AliasToken


SOURCE_ID_PATTERN = re.compile(r"^source:sha256:([0-9a-f]{64})$")
KNOWLEDGE_ID_PATTERN = re.compile(
    r"^[a-z][a-z0-9-]{2,79}:[a-z0-9][a-z0-9-]{1,119}$"
)
RELATION_START = "<!-- knowledge-relations:start -->"
RELATION_END = "<!-- knowledge-relations:end -->"
MAX_YAML_ALIASES = 20
ALLOWED_DOCUMENT_ROOTS = {"sources", "knowledge", "archive"}

KnowledgeType: TypeAlias = Literal["topic", "entity", "method", "comparison", "note"]
KnowledgeStatus: TypeAlias = Literal[
    "draft", "confirmed", "contested", "superseded", "archived"
]
RelationType: TypeAlias = Literal[
    "supports", "contradicts", "refines", "supersedes", "implements", "example_of"
]


class VaultFormatError(Exception):
    def __init__(self, code: str, message: str, *, path: Path | None = None) -> None:
        self.code = code
        self.path = path
        super().__init__(f"{code}: {message}")


class VaultModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRecord(VaultModel):
    id: str = Field(pattern=r"^source:sha256:[0-9a-f]{64}$")
    kind: Literal["web", "file", "image"]
    title: str = Field(min_length=1)
    original_name: str | None = None
    source_url: HttpUrl | None = None
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ingested_at: datetime
    submitted_by: str = Field(min_length=1)
    extractor: str = Field(min_length=1)
    extraction_quality: Literal["high", "medium", "low"]
    data_policy: Literal["personal", "team-approved"]

    @model_validator(mode="after")
    def source_id_matches_fingerprint(self) -> "SourceRecord":
        match = SOURCE_ID_PATTERN.fullmatch(self.id)
        if match is None or match.group(1) != self.content_sha256:
            raise ValueError("source ID digest must equal content_sha256")
        return self


class Relation(VaultModel):
    type: RelationType
    target: str = Field(pattern=KNOWLEDGE_ID_PATTERN.pattern)
    evidence: str = Field(pattern=SOURCE_ID_PATTERN.pattern)
    confidence: float = Field(ge=0, le=1)


class KnowledgeRecord(VaultModel):
    id: str = Field(pattern=KNOWLEDGE_ID_PATTERN.pattern)
    type: KnowledgeType
    status: KnowledgeStatus
    confidence: float = Field(ge=0, le=1)
    sources: list[str] = Field(min_length=1)
    relations: list[Relation] = Field(default_factory=list)
    created: date
    updated: date


VaultRecord: TypeAlias = SourceRecord | KnowledgeRecord


@dataclass(frozen=True)
class VaultDocument:
    record: VaultRecord
    relative_path: PurePosixPath
    raw_text: str
    body: str
    title: str


@dataclass
class VaultIndex:
    sources: dict[str, VaultDocument] = field(default_factory=dict)
    knowledge: dict[str, VaultDocument] = field(default_factory=dict)
    duplicate_source_ids: set[str] = field(default_factory=set)
    duplicate_knowledge_ids: set[str] = field(default_factory=set)


def parse_vault_markdown(path: Path, vault_root: Path) -> VaultDocument:
    try:
        root = vault_root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise VaultFormatError(
            "PATH_OUTSIDE_VAULT", "document must resolve inside the Vault", path=path
        ) from error
    relative_path = PurePosixPath(relative.as_posix())
    if not relative_path.parts or relative_path.parts[0] not in ALLOWED_DOCUMENT_ROOTS:
        raise VaultFormatError(
            "PATH_NOT_ALLOWED", "document is outside an allowed Vault root", path=path
        )

    raw_text = resolved.read_text(encoding="utf-8")
    frontmatter_text, body = _split_frontmatter(raw_text, path)
    try:
        alias_count = sum(
            isinstance(token, AliasToken) for token in yaml.scan(frontmatter_text)
        )
    except yaml.YAMLError as error:
        raise VaultFormatError("INVALID_FRONTMATTER", str(error), path=path) from error
    if alias_count > MAX_YAML_ALIASES:
        raise VaultFormatError(
            "TOO_MANY_YAML_ALIASES",
            f"frontmatter contains {alias_count} aliases; limit is {MAX_YAML_ALIASES}",
            path=path,
        )
    try:
        payload = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as error:
        raise VaultFormatError("INVALID_FRONTMATTER", str(error), path=path) from error
    if not isinstance(payload, dict):
        raise VaultFormatError(
            "INVALID_FRONTMATTER", "frontmatter must be a YAML mapping", path=path
        )

    is_source = relative_path.parts[0] == "sources"
    record_type = SourceRecord if is_source else KnowledgeRecord
    record_code = "INVALID_SOURCE_RECORD" if is_source else "INVALID_KNOWLEDGE_RECORD"
    try:
        record = record_type.model_validate(payload)
    except ValueError as error:
        raise VaultFormatError(record_code, str(error), path=path) from error
    title = record.title if isinstance(record, SourceRecord) else _body_title(body, record.id)
    return VaultDocument(
        record=record,
        relative_path=relative_path,
        raw_text=raw_text,
        body=body,
        title=title,
    )


def _split_frontmatter(raw_text: str, path: Path) -> tuple[str, str]:
    lines = raw_text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise VaultFormatError(
            "INVALID_FRONTMATTER", "document must start with YAML frontmatter", path=path
        )
    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing_index is None:
        raise VaultFormatError(
            "INVALID_FRONTMATTER", "frontmatter closing delimiter is missing", path=path
        )
    return "".join(lines[1:closing_index]), "".join(lines[closing_index + 1 :])


def _body_title(body: str, fallback: str) -> str:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", body)
    return match.group(1) if match else fallback


def index_documents(documents: list[VaultDocument]) -> VaultIndex:
    index = VaultIndex()
    for document in documents:
        if isinstance(document.record, SourceRecord):
            if document.record.id in index.sources:
                index.duplicate_source_ids.add(document.record.id)
            else:
                index.sources[document.record.id] = document
        else:
            if document.record.id in index.knowledge:
                index.duplicate_knowledge_ids.add(document.record.id)
            else:
                index.knowledge[document.record.id] = document
    return index


def build_vault_index(vault_root: Path) -> VaultIndex:
    documents = [
        parse_vault_markdown(path, vault_root)
        for path in iter_vault_markdown_paths(vault_root)
    ]
    return index_documents(documents)


def iter_vault_markdown_paths(vault_root: Path) -> list[Path]:
    paths: list[Path] = []
    sources = vault_root / "sources"
    if sources.exists():
        paths.extend(sources.rglob("source.md"))
    for root_name in ("archive", "knowledge"):
        root = vault_root / root_name
        if root.exists():
            paths.extend(root.rglob("*.md"))
    return sorted(paths)


_RELATION_LABELS: dict[RelationType, str] = {
    "supports": "支持",
    "contradicts": "反驳",
    "refines": "细化",
    "supersedes": "取代",
    "implements": "实现",
    "example_of": "示例",
}


def render_relation_block(record: KnowledgeRecord, index: VaultIndex) -> str:
    lines = [RELATION_START, "## 相关知识", ""]
    if not record.relations:
        lines.append("_暂无正式关系。_")
    else:
        for relation in sorted(record.relations, key=lambda item: (item.type, item.target)):
            target = index.knowledge.get(relation.target)
            if target is None:
                link = relation.target
            else:
                link_path = target.relative_path.with_suffix("").as_posix()
                link = f"[[{link_path}|{target.title}]]"
            lines.append(f"- {_RELATION_LABELS[relation.type]}：{link}")
    lines.append(RELATION_END)
    return "\n".join(lines)


def replace_relation_block(
    raw_text: str,
    record: KnowledgeRecord,
    index: VaultIndex,
) -> str:
    block = render_relation_block(record, index)
    start_count = raw_text.count(RELATION_START)
    end_count = raw_text.count(RELATION_END)
    if start_count == 0 and end_count == 0:
        return raw_text.rstrip() + "\n\n" + block + "\n"
    if start_count != 1 or end_count != 1:
        raise VaultFormatError(
            "INVALID_RELATION_BLOCK", "relation block markers must occur exactly once"
        )
    start = raw_text.index(RELATION_START)
    end = raw_text.index(RELATION_END, start) + len(RELATION_END)
    return raw_text[:start] + block + raw_text[end:]
