"""Strict semantic output accepted from Hermes."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .vault import KNOWLEDGE_ID_PATTERN, SOURCE_ID_PATTERN, KnowledgeStatus, KnowledgeType, RelationType


class ProposalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProposedRelation(ProposalModel):
    type: RelationType
    target: str = Field(pattern=KNOWLEDGE_ID_PATTERN.pattern)
    evidence: str = Field(pattern=SOURCE_ID_PATTERN.pattern)
    confidence: float = Field(ge=0, le=1)


class CreateAction(ProposalModel):
    action: Literal["create"]
    knowledge_id: str = Field(pattern=KNOWLEDGE_ID_PATTERN.pattern)
    title: str = Field(min_length=1, max_length=200)
    knowledge_type: KnowledgeType
    status: KnowledgeStatus
    confidence: float = Field(ge=0, le=1)
    content: str = Field(min_length=1)
    citations: list[str] = Field(min_length=1)
    relations: list[ProposedRelation] = Field(default_factory=list)


class ExistingAction(ProposalModel):
    action: Literal["supplement", "support", "contradict", "cite-only"]
    target_id: str = Field(pattern=KNOWLEDGE_ID_PATTERN.pattern)
    confidence: float = Field(ge=0, le=1)
    content: str = Field(min_length=1)
    citations: list[str] = Field(min_length=1)
    relations: list[ProposedRelation] = Field(default_factory=list)


class SupersedeAction(ProposalModel):
    action: Literal["supersede"]
    target_id: str = Field(pattern=KNOWLEDGE_ID_PATTERN.pattern)
    replacement_id: str = Field(pattern=KNOWLEDGE_ID_PATTERN.pattern)
    title: str = Field(min_length=1, max_length=200)
    knowledge_type: KnowledgeType
    status: KnowledgeStatus
    confidence: float = Field(ge=0, le=1)
    content: str = Field(min_length=1)
    citations: list[str] = Field(min_length=1)
    relations: list[ProposedRelation] = Field(default_factory=list)


class NoChangeAction(ProposalModel):
    action: Literal["no-change"]
    reason: str = Field(min_length=1)


ProposalAction: TypeAlias = Annotated[
    CreateAction | ExistingAction | SupersedeAction | NoChangeAction,
    Field(discriminator="action"),
]


class CompilationProposal(ProposalModel):
    schema_version: Literal[1]
    source_id: str = Field(pattern=SOURCE_ID_PATTERN.pattern)
    actions: list[ProposalAction] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_internal_references(self) -> "CompilationProposal":
        if any(isinstance(action, NoChangeAction) for action in self.actions):
            if len(self.actions) != 1 or not isinstance(self.actions[0], NoChangeAction):
                raise ValueError("no-change must be the only proposal action")

        action_targets: set[str] = set()
        for action in self.actions:
            if isinstance(action, NoChangeAction):
                continue
            if any(citation != self.source_id for citation in action.citations):
                raise ValueError("all citations must reference the current source")
            relation_targets: set[str] = set()
            for relation in action.relations:
                if relation.evidence != self.source_id:
                    raise ValueError("relation evidence must reference the current source")
                if relation.target in relation_targets:
                    raise ValueError("duplicate relation target in one action")
                relation_targets.add(relation.target)

            target = (
                action.knowledge_id
                if isinstance(action, CreateAction)
                else action.replacement_id
                if isinstance(action, SupersedeAction)
                else action.target_id
            )
            if target in action_targets:
                raise ValueError("duplicate action target")
            action_targets.add(target)
        return self
