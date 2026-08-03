"""Compile semantic proposals into deterministic, filesystem-safe changes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml

from .proposals import (
    CompilationProposal,
    CreateAction,
    ExistingAction,
    NoChangeAction,
    ProposedRelation,
    SupersedeAction,
)
from .sources import NormalizedSource
from .vault import (
    KnowledgeRecord,
    Relation,
    SourceRecord,
    VaultDocument,
    VaultIndex,
    build_vault_index,
    render_relation_block,
)


FileOperation = Literal["create", "update", "delete", "move"]
_TYPE_DIRECTORIES = {
    "topic": "topics",
    "entity": "entities",
    "method": "methods",
    "comparison": "comparisons",
    "note": "notes",
}
_ALLOWED_CHANGE_ROOTS = {"sources", "knowledge", "archive", "attachments", "_meta"}


class CompileError(Exception):
    pass


@dataclass(frozen=True)
class CompileMetadata:
    ingest_id: str
    submitted_by: str
    hermes_version: str
    hermes_profile: str | None
    compiler_version: str
    schema_version: int
    created_at: datetime


@dataclass(frozen=True)
class FileChange:
    operation: FileOperation
    path: PurePosixPath
    content: bytes
    before_sha256: str | None
    after_sha256: str | None

    def __post_init__(self) -> None:
        if self.path.is_absolute() or ".." in self.path.parts:
            raise ValueError("change path must be a safe relative path")
        if not self.path.parts or self.path.parts[0] not in _ALLOWED_CHANGE_ROOTS:
            raise ValueError("change path is outside an allowed root")


@dataclass(frozen=True)
class ChangeSet:
    ingest_id: str
    source_id: str
    changes: tuple[FileChange, ...]
    semantic_actions: tuple[str, ...]
    relation_changes: tuple[str, ...]
    warnings: tuple[str, ...]
    modified_existing_knowledge: int
    replaces_confirmed: bool


@dataclass
class _KnowledgeDraft:
    record: KnowledgeRecord
    path: PurePosixPath
    title: str
    body: str
    existing: VaultDocument | None


class ChangeCompiler:
    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root.resolve(strict=True)

    def compile(
        self,
        source: NormalizedSource,
        proposal: CompilationProposal,
        metadata: CompileMetadata,
        *,
        original_path: Path | None = None,
    ) -> ChangeSet:
        if proposal.source_id != source.source_id:
            raise CompileError("proposal source does not match normalized source")
        index = build_vault_index(self.vault_root)
        changes: list[FileChange] = []
        source_changes = self._source_changes(source, metadata, index, original_path)
        changes.extend(source_changes)

        drafts: dict[str, _KnowledgeDraft] = {}
        touched: set[str] = set()
        relation_changes: list[str] = []
        replaces_confirmed = False
        semantic_actions = tuple(action.action for action in proposal.actions)

        for action in proposal.actions:
            if isinstance(action, NoChangeAction):
                continue
            if isinstance(action, CreateAction):
                self._apply_create(action, source, metadata, index, drafts, touched)
                relation_changes.extend(_relation_descriptions(action.relations))
            elif isinstance(action, ExistingAction):
                target = self._draft_for_existing(action.target_id, index, drafts)
                if target.record.status == "confirmed" and action.action == "contradict":
                    replaces_confirmed = True
                self._apply_existing(action, source, metadata, target)
                touched.add(action.target_id)
                relation_changes.extend(_relation_descriptions(action.relations))
            elif isinstance(action, SupersedeAction):
                target = self._draft_for_existing(action.target_id, index, drafts)
                replaces_confirmed = replaces_confirmed or target.record.status == "confirmed"
                self._apply_supersede(action, source, metadata, target, index, drafts)
                touched.update({action.target_id, action.replacement_id})
                relation_changes.extend(_relation_descriptions(action.relations))
                relation_changes.append(f"supersedes:{action.target_id}")

        prospective_index = self._prospective_index(index, drafts)
        for knowledge_id in sorted(touched):
            draft = drafts[knowledge_id]
            content = _render_knowledge(draft, prospective_index)
            change = self._file_change(draft.path, content.encode("utf-8"))
            if change is not None:
                changes.append(change)

        index_content = _render_index(prospective_index).encode("utf-8")
        index_change = self._file_change(PurePosixPath("_meta/index.md"), index_content)
        if index_change is not None:
            changes.append(index_change)

        if not changes:
            return ChangeSet(
                ingest_id=metadata.ingest_id,
                source_id=source.source_id,
                changes=(),
                semantic_actions=semantic_actions,
                relation_changes=tuple(sorted(set(relation_changes))),
                warnings=(),
                modified_existing_knowledge=0,
                replaces_confirmed=replaces_confirmed,
            )

        manifest_path = PurePosixPath(f"_meta/ingests/{metadata.ingest_id}.md")
        changed_paths = sorted({change.path.as_posix() for change in changes} | {manifest_path.as_posix()})
        manifest = _render_manifest(
            metadata,
            source,
            changed_paths,
            semantic_actions,
            tuple(sorted(set(relation_changes))),
        ).encode("utf-8")
        manifest_change = self._file_change(manifest_path, manifest)
        if manifest_change is not None:
            changes.append(manifest_change)
        changes.sort(key=lambda item: item.path.as_posix())
        modified_existing = sum(
            change.operation == "update" and change.path.parts[0] == "knowledge"
            for change in changes
        )
        return ChangeSet(
            ingest_id=metadata.ingest_id,
            source_id=source.source_id,
            changes=tuple(changes),
            semantic_actions=semantic_actions,
            relation_changes=tuple(sorted(set(relation_changes))),
            warnings=(),
            modified_existing_knowledge=modified_existing,
            replaces_confirmed=replaces_confirmed,
        )

    def _source_changes(
        self,
        source: NormalizedSource,
        metadata: CompileMetadata,
        index: VaultIndex,
        original_path: Path | None,
    ) -> list[FileChange]:
        if source.source_id in index.sources:
            return []
        source_root = "files" if source.kind == "file" else "web"
        directory = PurePosixPath("sources") / source_root / source.content_sha256
        record = SourceRecord(
            id=source.source_id,
            kind=source.kind,
            title=source.title,
            original_name=source.original_name,
            source_url=source.source_url,
            content_sha256=source.content_sha256,
            ingested_at=source.retrieved_at,
            submitted_by=metadata.submitted_by,
            extractor=source.extractor,
            extraction_quality=source.extraction_quality,
            data_policy="personal",
        )
        source_document = _frontmatter(record.model_dump(mode="json", exclude_none=True))
        source_document += "\n" + source.normalized_text
        changes = [
            change
            for change in [
                self._file_change(directory / "source.md", source_document.encode("utf-8"))
            ]
            if change is not None
        ]
        if source.kind == "file" and original_path is not None:
            resolved = original_path.resolve(strict=True)
            original_change = self._file_change(
                directory / f"original{resolved.suffix.lower()}", resolved.read_bytes()
            )
            if original_change is not None:
                changes.append(original_change)
        return changes

    def _apply_create(
        self,
        action: CreateAction,
        source: NormalizedSource,
        metadata: CompileMetadata,
        index: VaultIndex,
        drafts: dict[str, _KnowledgeDraft],
        touched: set[str],
    ) -> None:
        existing = index.knowledge.get(action.knowledge_id)
        marker = _source_marker(source.source_id)
        if existing is not None:
            if marker in existing.raw_text:
                return
            raise CompileError(f"knowledge ID already exists: {action.knowledge_id}")
        relations = [_relation(item) for item in action.relations]
        record = KnowledgeRecord(
            id=action.knowledge_id,
            type=action.knowledge_type,
            status=action.status,
            confidence=action.confidence,
            sources=list(action.citations),
            relations=relations,
            created=metadata.created_at.date(),
            updated=metadata.created_at.date(),
        )
        path = PurePosixPath("knowledge") / _TYPE_DIRECTORIES[action.knowledge_type] / (
            action.knowledge_id.split(":", 1)[1] + ".md"
        )
        body = f"# {action.title}\n\n{_sourced_section(source.source_id, '', action.content)}"
        drafts[action.knowledge_id] = _KnowledgeDraft(
            record=record,
            path=path,
            title=action.title,
            body=body,
            existing=None,
        )
        touched.add(action.knowledge_id)

    def _draft_for_existing(
        self,
        knowledge_id: str,
        index: VaultIndex,
        drafts: dict[str, _KnowledgeDraft],
    ) -> _KnowledgeDraft:
        if knowledge_id in drafts:
            return drafts[knowledge_id]
        document = index.knowledge.get(knowledge_id)
        if document is None or not isinstance(document.record, KnowledgeRecord):
            raise CompileError(f"knowledge target does not exist: {knowledge_id}")
        draft = _KnowledgeDraft(
            record=document.record.model_copy(deep=True),
            path=document.relative_path,
            title=document.title,
            body=_without_relation_block(document.body),
            existing=document,
        )
        drafts[knowledge_id] = draft
        return draft

    def _apply_existing(
        self,
        action: ExistingAction,
        source: NormalizedSource,
        metadata: CompileMetadata,
        draft: _KnowledgeDraft,
    ) -> None:
        sources = list(dict.fromkeys([*draft.record.sources, *action.citations]))
        relations = _merge_relations(draft.record.relations, action.relations)
        status = "contested" if action.action == "contradict" else draft.record.status
        draft.record = draft.record.model_copy(
            update={
                "sources": sources,
                "relations": relations,
                "status": status,
                "updated": metadata.created_at.date(),
            }
        )
        marker = _source_marker(source.source_id)
        if marker not in draft.body:
            heading = {
                "supplement": "来源补充",
                "support": "支持证据",
                "contradict": "冲突观点",
                "cite-only": "新增引用",
            }[action.action]
            draft.body = draft.body.rstrip() + "\n\n" + _sourced_section(
                source.source_id, heading, action.content
            )

    def _apply_supersede(
        self,
        action: SupersedeAction,
        source: NormalizedSource,
        metadata: CompileMetadata,
        target: _KnowledgeDraft,
        index: VaultIndex,
        drafts: dict[str, _KnowledgeDraft],
    ) -> None:
        target.record = target.record.model_copy(
            update={
                "status": "superseded",
                "sources": list(dict.fromkeys([*target.record.sources, *action.citations])),
                "updated": metadata.created_at.date(),
            }
        )
        marker = _source_marker(source.source_id)
        if marker not in target.body:
            target.body = target.body.rstrip() + "\n\n" + _sourced_section(
                source.source_id,
                "已被取代",
                f"由 `{action.replacement_id}` 取代。",
            )
        if action.replacement_id in index.knowledge:
            replacement = self._draft_for_existing(action.replacement_id, index, drafts)
            if marker not in replacement.body:
                replacement.body = replacement.body.rstrip() + "\n\n" + _sourced_section(
                    source.source_id, "取代说明", action.content
                )
            return
        relations = [_relation(item) for item in action.relations]
        relations.append(
            Relation(
                type="supersedes",
                target=action.target_id,
                evidence=source.source_id,
                confidence=action.confidence,
            )
        )
        record = KnowledgeRecord(
            id=action.replacement_id,
            type=action.knowledge_type,
            status=action.status,
            confidence=action.confidence,
            sources=list(action.citations),
            relations=relations,
            created=metadata.created_at.date(),
            updated=metadata.created_at.date(),
        )
        path = PurePosixPath("knowledge") / _TYPE_DIRECTORIES[action.knowledge_type] / (
            action.replacement_id.split(":", 1)[1] + ".md"
        )
        drafts[action.replacement_id] = _KnowledgeDraft(
            record=record,
            path=path,
            title=action.title,
            body=f"# {action.title}\n\n{_sourced_section(source.source_id, '', action.content)}",
            existing=None,
        )

    def _prospective_index(
        self, index: VaultIndex, drafts: dict[str, _KnowledgeDraft]
    ) -> VaultIndex:
        knowledge = dict(index.knowledge)
        for knowledge_id, draft in drafts.items():
            knowledge[knowledge_id] = VaultDocument(
                record=draft.record,
                relative_path=draft.path,
                raw_text="",
                body=draft.body,
                title=draft.title,
            )
        return VaultIndex(sources=dict(index.sources), knowledge=knowledge)

    def _file_change(self, relative: PurePosixPath, content: bytes) -> FileChange | None:
        if relative.is_absolute() or ".." in relative.parts:
            raise CompileError("unsafe change path")
        path = self.vault_root.joinpath(*relative.parts)
        root = self.vault_root
        try:
            path.resolve().relative_to(root)
        except ValueError as error:
            raise CompileError("change path escaped Vault") from error
        after = hashlib.sha256(content).hexdigest()
        if path.exists():
            before_content = path.read_bytes()
            before = hashlib.sha256(before_content).hexdigest()
            if before == after:
                return None
            operation: FileOperation = "update"
        else:
            before = None
            operation = "create"
        return FileChange(
            operation=operation,
            path=relative,
            content=content,
            before_sha256=before,
            after_sha256=after,
        )


def _relation(proposed: ProposedRelation) -> Relation:
    return Relation.model_validate(proposed.model_dump())


def _merge_relations(
    current: list[Relation], proposed: list[ProposedRelation]
) -> list[Relation]:
    merged = {(item.type, item.target, item.evidence): item for item in current}
    for item in proposed:
        relation = _relation(item)
        merged[(relation.type, relation.target, relation.evidence)] = relation
    return [merged[key] for key in sorted(merged)]


def _relation_descriptions(relations: list[ProposedRelation]) -> list[str]:
    return [f"{relation.type}:{relation.target}" for relation in relations]


def _source_marker(source_id: str) -> str:
    return f"<!-- knowledge-source:{source_id}:start -->"


def _sourced_section(source_id: str, heading: str, content: str) -> str:
    title = f"## {heading}\n\n" if heading else ""
    return (
        f"{_source_marker(source_id)}\n"
        f"{title}{content.strip()}\n\n"
        f"[来源：`{source_id}`]\n"
        f"<!-- knowledge-source:{source_id}:end -->"
    )


def _without_relation_block(body: str) -> str:
    start_marker = "<!-- knowledge-relations:start -->"
    end_marker = "<!-- knowledge-relations:end -->"
    if start_marker not in body:
        return body.rstrip()
    start = body.index(start_marker)
    end = body.index(end_marker, start) + len(end_marker)
    return (body[:start] + body[end:]).rstrip()


def _frontmatter(payload: dict[str, object]) -> str:
    yaml_text = yaml.safe_dump(
        payload,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).rstrip()
    return f"---\n{yaml_text}\n---\n"


def _render_knowledge(draft: _KnowledgeDraft, index: VaultIndex) -> str:
    relation_block = render_relation_block(draft.record, index)
    return (
        _frontmatter(draft.record.model_dump(mode="json"))
        + "\n"
        + draft.body.rstrip()
        + "\n\n"
        + relation_block
        + "\n"
    )


def _render_index(index: VaultIndex) -> str:
    lines = ["# 知识索引", ""]
    grouped: dict[str, list[VaultDocument]] = {}
    for document in index.knowledge.values():
        assert isinstance(document.record, KnowledgeRecord)
        grouped.setdefault(document.record.type, []).append(document)
    for knowledge_type in sorted(grouped):
        lines.extend([f"## {knowledge_type}", ""])
        for document in sorted(
            grouped[knowledge_type], key=lambda item: (item.title, item.record.id)
        ):
            link = document.relative_path.with_suffix("").as_posix()
            lines.append(f"- [[{link}|{document.title}]] (`{document.record.id}`)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_manifest(
    metadata: CompileMetadata,
    source: NormalizedSource,
    changed_paths: list[str],
    actions: tuple[str, ...],
    relation_changes: tuple[str, ...],
) -> str:
    profile = metadata.hermes_profile or "default"
    lines = [
        f"# 导入 {metadata.ingest_id}",
        "",
        f"- 来源：`{source.source_id}`",
        f"- 输入：`{source.original_name or source.source_url or source.title}`",
        f"- 内容 SHA-256：`{source.content_sha256}`",
        f"- 时间：`{metadata.created_at.isoformat()}`",
        f"- Hermes: `{metadata.hermes_version}` / `{profile}`",
        f"- Compiler / Schema: `{metadata.compiler_version}` / `{metadata.schema_version}`",
        "",
        "## 变更文件",
        "",
    ]
    lines.extend(f"- `{path}`" for path in changed_paths)
    lines.extend(["", "## 语义动作", ""])
    lines.extend(f"- `{action}`" for action in actions)
    lines.extend(["", "## 关系变化", ""])
    lines.extend(f"- `{change}`" for change in relation_changes)
    if not relation_changes:
        lines.append("- 无")
    return "\n".join(lines).rstrip() + "\n"
