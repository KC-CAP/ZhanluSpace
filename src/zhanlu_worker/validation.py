"""Deterministic validation for all formal Vault facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .vault import (
    ALLOWED_DOCUMENT_ROOTS,
    KnowledgeRecord,
    VaultDocument,
    VaultFormatError,
    index_documents,
    parse_vault_markdown,
    replace_relation_block,
)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    path: str | None = None


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


def validate_vault(vault_root: Path) -> ValidationReport:
    issues: list[ValidationIssue] = []
    documents: list[VaultDocument] = []
    for root_name in sorted(ALLOWED_DOCUMENT_ROOTS):
        root = vault_root / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.md")):
            try:
                documents.append(parse_vault_markdown(path, vault_root))
            except VaultFormatError as error:
                issues.append(
                    ValidationIssue(
                        code=error.code,
                        message=str(error),
                        path=_display_path(path, vault_root),
                    )
                )

    index = index_documents(documents)
    issues.extend(
        ValidationIssue("DUPLICATE_SOURCE_ID", source_id)
        for source_id in sorted(index.duplicate_source_ids)
    )
    issues.extend(
        ValidationIssue("DUPLICATE_KNOWLEDGE_ID", knowledge_id)
        for knowledge_id in sorted(index.duplicate_knowledge_ids)
    )

    for document in sorted(documents, key=lambda item: item.relative_path.as_posix()):
        if not isinstance(document.record, KnowledgeRecord):
            continue
        path = document.relative_path.as_posix()
        for source_id in document.record.sources:
            if source_id not in index.sources:
                issues.append(
                    ValidationIssue(
                        "BROKEN_SOURCE_REFERENCE",
                        f"knowledge source does not exist: {source_id}",
                        path,
                    )
                )
        has_broken_target = False
        for relation in document.record.relations:
            if relation.target not in index.knowledge:
                has_broken_target = True
                issues.append(
                    ValidationIssue(
                        "BROKEN_RELATION_TARGET",
                        f"relation target does not exist: {relation.target}",
                        path,
                    )
                )
            if relation.evidence not in index.sources:
                issues.append(
                    ValidationIssue(
                        "BROKEN_RELATION_EVIDENCE",
                        f"relation evidence does not exist: {relation.evidence}",
                        path,
                    )
                )
        if not has_broken_target:
            try:
                expected = replace_relation_block(document.raw_text, document.record, index)
            except VaultFormatError as error:
                issues.append(ValidationIssue(error.code, str(error), path))
            else:
                if expected != document.raw_text:
                    issues.append(
                        ValidationIssue(
                            "RELATION_BLOCK_MISMATCH",
                            "derived relation block does not match formal relations",
                            path,
                        )
                    )
    return ValidationReport(issues=issues)


def _display_path(path: Path, vault_root: Path) -> str:
    try:
        return path.resolve().relative_to(vault_root.resolve()).as_posix()
    except ValueError:
        return str(path)
