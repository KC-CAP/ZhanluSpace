"""Versioned JSONL messages exchanged with the Obsidian plugin."""

from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


JobState: TypeAlias = Literal[
    "queued",
    "acquiring",
    "extracting",
    "compiling",
    "validating",
    "ready",
    "committed",
    "merged",
    "paused",
]
RiskLevel: TypeAlias = Literal["low", "high"]
Outcome: TypeAlias = Literal["merged", "ready", "no_change"]

_BRANCH_PATTERN = re.compile(r"^knowledge/[0-9]{8}-[a-z0-9][a-z0-9-]{0,63}$")
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _require_absolute_path(value: str) -> str:
    if not value or not (
        PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute()
    ):
        raise ValueError("path must be absolute")
    return value


class ProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FileInput(ProtocolModel):
    kind: Literal["file"]
    value: str

    _absolute_file = field_validator("value")(_require_absolute_path)


class UrlInput(ProtocolModel):
    kind: Literal["url"]
    value: HttpUrl


JobInput: TypeAlias = Annotated[FileInput | UrlInput, Field(discriminator="kind")]


class RequestBase(ProtocolModel):
    version: Literal[1]
    job_id: UUID
    vault_path: str

    _absolute_vault = field_validator("vault_path")(_require_absolute_path)


class StartRequest(RequestBase):
    type: Literal["start"]
    input: JobInput


class ConfirmRequest(RequestBase):
    type: Literal["confirm"]
    branch: str
    expected_head: str

    @field_validator("branch")
    @classmethod
    def validate_branch(cls, value: str) -> str:
        if not _BRANCH_PATTERN.fullmatch(value):
            raise ValueError("branch must be a knowledge proposal branch")
        return value

    @field_validator("expected_head")
    @classmethod
    def validate_expected_head(cls, value: str) -> str:
        if not _COMMIT_PATTERN.fullmatch(value):
            raise ValueError("expected_head must be a lowercase 40-character commit hash")
        return value


Request: TypeAlias = Annotated[StartRequest | ConfirmRequest, Field(discriminator="type")]


class EventBase(ProtocolModel):
    version: Literal[1]
    job_id: UUID


class StateEvent(EventBase):
    type: Literal["state"]
    state: JobState
    message: str


class JobResult(ProtocolModel):
    outcome: Outcome
    risk: RiskLevel
    branch: str
    head: str
    changed_files: list[str]
    ingest_manifest: str
    risk_reasons: list[str]

    @field_validator("branch")
    @classmethod
    def validate_branch(cls, value: str) -> str:
        if not _BRANCH_PATTERN.fullmatch(value):
            raise ValueError("branch must be a knowledge proposal branch")
        return value

    @field_validator("head")
    @classmethod
    def validate_head(cls, value: str) -> str:
        if not _COMMIT_PATTERN.fullmatch(value):
            raise ValueError("head must be a lowercase 40-character commit hash")
        return value


class CompletedEvent(EventBase):
    type: Literal["completed"]
    result: JobResult


class ErrorEvent(EventBase):
    type: Literal["error"]
    code: str
    message: str
    retryable: bool


Event: TypeAlias = Annotated[
    StateEvent | CompletedEvent | ErrorEvent,
    Field(discriminator="type"),
]
