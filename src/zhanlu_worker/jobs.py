"""End-to-end orchestration for one short-lived knowledge job."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from . import __version__
from .compiler import ChangeCompiler, CompileError, CompileMetadata
from .git import GitController, GitError
from .hermes import HermesError, select_context
from .protocol import (
    CompletedEvent,
    ConfirmRequest,
    ErrorEvent,
    Event,
    JobState,
    Request,
    StartRequest,
    StateEvent,
)
from .risk import classify_risk
from .sources import (
    SourceAcquisitionError,
    acquire_file,
    acquire_url,
    write_staged_source,
)
from .vault import build_vault_index


class HermesCompiler(Protocol):
    def compile(self, source, context, job_dir: Path): ...


class StateTransitionError(Exception):
    pass


_TRANSITIONS: dict[JobState | None, set[JobState]] = {
    None: {"queued"},
    "queued": {"acquiring", "validating", "paused"},
    "acquiring": {"extracting", "paused"},
    "extracting": {"compiling", "paused"},
    "compiling": {"validating", "paused"},
    "validating": {"ready", "committed", "merged", "paused"},
    "committed": {"merged", "paused"},
    "ready": set(),
    "merged": set(),
    "paused": set(),
}


class JobStateMachine:
    def __init__(self) -> None:
        self.state: JobState | None = None

    def transition(self, state: JobState) -> None:
        if state not in _TRANSITIONS[self.state]:
            raise StateTransitionError(f"invalid transition: {self.state} -> {state}")
        self.state = state


def _utc_now() -> datetime:
    return datetime.now(UTC)


class JobRunner:
    def __init__(
        self,
        hermes: HermesCompiler,
        *,
        clock: Callable[[], datetime] = _utc_now,
        git_factory: Callable[[Path], GitController] = GitController,
        hermes_version: str = "unknown",
        hermes_profile: str | None = None,
    ) -> None:
        self.hermes = hermes
        self.clock = clock
        self.git_factory = git_factory
        self.hermes_version = hermes_version
        self.hermes_profile = hermes_profile

    def handle(
        self,
        request: Request,
        emit: Callable[[Event], None],
    ) -> CompletedEvent | ErrorEvent:
        machine = JobStateMachine()

        def state(value: JobState, message: str) -> None:
            machine.transition(value)
            emit(
                StateEvent(
                    version=1,
                    type="state",
                    job_id=request.job_id,
                    state=value,
                    message=message,
                )
            )

        state("queued", "任务已排队")
        try:
            if isinstance(request, StartRequest):
                return self._start(request, state)
            return self._confirm(request, state)
        except (Exception, KeyboardInterrupt) as error:
            if machine.state not in {"ready", "merged", "paused"}:
                state("paused", "任务已暂停")
            code, message, retryable = _error_details(error)
            return ErrorEvent(
                version=1,
                type="error",
                job_id=request.job_id,
                code=code,
                message=message,
                retryable=retryable,
            )

    def _start(
        self,
        request: StartRequest,
        state: Callable[[JobState, str], None],
    ) -> CompletedEvent:
        vault = Path(request.vault_path)
        git = self.git_factory(vault)
        git.preflight()
        state("acquiring", "正在获取素材")
        if request.input.kind == "file":
            source = acquire_file(request.input.value, now=self.clock)
            original_path: Path | None = Path(request.input.value)
        else:
            source = acquire_url(str(request.input.value), now=self.clock)
            original_path = None
        state("extracting", "正在规范化素材")
        jobs_root = vault / ".knowledge-runtime" / "jobs"
        jobs_root.mkdir(parents=True, exist_ok=True)
        job_dir = jobs_root / str(request.job_id)
        write_staged_source(job_dir, source, original_path=original_path)

        state("compiling", "正在调用 Hermes 编译知识提案")
        index = build_vault_index(vault)
        context = select_context(source.normalized_text, list(index.knowledge.values()))
        proposal = self.hermes.compile(source, context, job_dir)

        state("validating", "正在生成并校验确定性变更")
        metadata = CompileMetadata(
            ingest_id=str(request.job_id),
            submitted_by="local-user",
            hermes_version=self.hermes_version,
            hermes_profile=self.hermes_profile,
            compiler_version=__version__,
            schema_version=1,
            created_at=self.clock(),
        )
        change_set = ChangeCompiler(vault).compile(
            source, proposal, metadata, original_path=original_path
        )
        risk = classify_risk(
            change_set,
            extraction_quality=source.extraction_quality,
            validation_ok=True,
        )
        result = git.apply(change_set, risk)
        if result.outcome == "ready":
            state("ready", "高风险变更等待确认")
        elif result.outcome == "merged":
            state("committed", "变更已提交")
            state("merged", "低风险变更已合入 main")
        changed_files = [change.path.as_posix() for change in change_set.changes]
        return CompletedEvent.model_validate(
            {
                "version": 1,
                "type": "completed",
                "job_id": str(request.job_id),
                "result": {
                    "outcome": result.outcome,
                    "risk": risk.level,
                    "branch": result.branch,
                    "head": result.head,
                    "changed_files": changed_files,
                    "ingest_manifest": f"_meta/ingests/{request.job_id}.md",
                    "risk_reasons": list(risk.reasons),
                },
            }
        )

    def _confirm(
        self,
        request: ConfirmRequest,
        state: Callable[[JobState, str], None],
    ) -> CompletedEvent:
        state("validating", "正在重新校验提案分支")
        result = self.git_factory(Path(request.vault_path)).confirm(
            request.branch, request.expected_head
        )
        state("merged", "已确认并合入 main")
        return CompletedEvent.model_validate(
            {
                "version": 1,
                "type": "completed",
                "job_id": str(request.job_id),
                "result": {
                    "outcome": result.outcome,
                    "risk": "high",
                    "branch": result.branch,
                    "head": result.head,
                    "changed_files": [],
                    "ingest_manifest": "_meta/ingests/confirmed.md",
                    "risk_reasons": [],
                },
            }
        )


def _error_details(error: BaseException) -> tuple[str, str, bool]:
    if isinstance(error, KeyboardInterrupt):
        return "CANCELLED", "job cancelled by parent process", False
    if isinstance(error, (HermesError, SourceAcquisitionError)):
        return error.code, str(error), error.retryable
    if isinstance(error, GitError):
        return error.code, str(error), False
    if isinstance(error, CompileError):
        return "COMPILE_FAILED", str(error), False
    if isinstance(error, FileExistsError):
        return "JOB_ALREADY_EXISTS", str(error), False
    return "INTERNAL_ERROR", str(error), False
