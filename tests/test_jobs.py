from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import pytest
from pydantic import TypeAdapter

from zhanlu_worker.hermes import HermesError
from zhanlu_worker.jobs import JobRunner, JobStateMachine, StateTransitionError
from zhanlu_worker.proposals import CompilationProposal
from zhanlu_worker.protocol import ConfirmRequest, Event, Request, StartRequest

from .test_git import _controller, _git, _repository


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


class ProposalHermes:
    def __init__(self, action_factory: Callable[[str], dict[str, object]]) -> None:
        self.action_factory = action_factory

    def compile(self, source, context, job_dir: Path) -> CompilationProposal:
        return CompilationProposal.model_validate(
            {
                "schema_version": 1,
                "source_id": source.source_id,
                "actions": [self.action_factory(source.source_id)],
            }
        )


class FailingHermes:
    def compile(self, source, context, job_dir: Path) -> CompilationProposal:
        raise HermesError("HERMES_TIMEOUT", "timeout", retryable=True)


class InterruptingHermes:
    def compile(self, source, context, job_dir: Path) -> CompilationProposal:
        raise KeyboardInterrupt()


def _start(root: Path, source_path: Path, job_id: str) -> StartRequest:
    return TypeAdapter(Request).validate_python(
        {
            "version": 1,
            "type": "start",
            "job_id": job_id,
            "vault_path": str(root),
            "input": {"kind": "file", "value": str(source_path)},
        }
    )


def _runner(root: Path, hermes) -> JobRunner:
    return JobRunner(
        hermes,
        clock=lambda: NOW,
        git_factory=lambda path: _controller(path),
        hermes_version="0.19.1",
        hermes_profile="test",
    )


def _input(tmp_path: Path) -> Path:
    path = tmp_path / "input.md"
    path.write_text("# 新知识\n\n关键词与语义召回互补。\n", encoding="utf-8")
    return path


def test_state_machine_accepts_only_declared_sequences() -> None:
    machine = JobStateMachine()
    for state in (
        "queued",
        "acquiring",
        "extracting",
        "compiling",
        "validating",
        "committed",
        "merged",
    ):
        machine.transition(state)

    with pytest.raises(StateTransitionError):
        machine.transition("paused")


@pytest.mark.parametrize(
    "sequence",
    (
        ("queued", "compiling"),
        ("queued", "queued"),
        ("queued", "acquiring", "ready", "merged"),
    ),
)
def test_state_machine_rejects_skipped_repeated_or_post_terminal_states(
    sequence: tuple[str, ...],
) -> None:
    machine = JobStateMachine()

    with pytest.raises(StateTransitionError):
        for state in sequence:
            machine.transition(state)


def test_low_risk_job_runs_real_compiler_validator_and_git_merge(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    source_path = _input(tmp_path)
    request = _start(
        root, source_path, "66666666-6666-4666-8666-666666666666"
    )
    hermes = ProposalHermes(
        lambda source_id: {
            "action": "create",
            "knowledge_id": "method:hybrid-retrieval-job",
            "title": "任务混合召回",
            "knowledge_type": "method",
            "status": "draft",
            "confidence": 0.8,
            "content": "任务创建混合召回知识。",
            "citations": [source_id],
            "relations": [],
        }
    )
    events: list[Event] = []

    terminal = _runner(root, hermes).handle(request, events.append)

    assert terminal.type == "completed"
    assert terminal.result.outcome == "merged"
    assert [event.state for event in events if event.type == "state"] == [
        "queued",
        "acquiring",
        "extracting",
        "compiling",
        "validating",
        "committed",
        "merged",
    ]
    assert (root / "knowledge" / "methods" / "hybrid-retrieval-job.md").exists()


def test_high_risk_job_returns_ready_and_confirm_merges_exact_head(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    request = _start(
        root, _input(tmp_path), "77777777-7777-4777-8777-777777777777"
    )
    hermes = ProposalHermes(
        lambda source_id: {
            "action": "contradict",
            "target_id": "topic:retrieval",
            "confidence": 0.7,
            "content": "新来源提出相反边界。",
            "citations": [source_id],
            "relations": [],
        }
    )
    runner = _runner(root, hermes)
    events: list[Event] = []

    ready = runner.handle(request, events.append)

    assert ready.type == "completed"
    assert ready.result.outcome == "ready"
    assert ready.result.risk == "high"
    assert "CONTRADICTS_OR_SUPERSEDES" in ready.result.risk_reasons
    assert [event.state for event in events if event.type == "state"][-1] == "ready"

    confirm = ConfirmRequest(
        version=1,
        type="confirm",
        job_id="88888888-8888-4888-8888-888888888888",
        vault_path=str(root),
        branch=ready.result.branch,
        expected_head=ready.result.head,
    )
    confirmation_events: list[Event] = []
    merged = runner.handle(confirm, confirmation_events.append)

    assert merged.type == "completed"
    assert merged.result.outcome == "merged"
    assert [event.state for event in confirmation_events if event.type == "state"] == [
        "queued",
        "validating",
        "merged",
    ]


def test_hermes_timeout_pauses_without_modifying_vault(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    request = _start(
        root, _input(tmp_path), "99999999-9999-4999-8999-999999999999"
    )
    baseline = _git(root, "rev-parse", "main").stdout.strip()
    events: list[Event] = []

    terminal = _runner(root, FailingHermes()).handle(request, events.append)

    assert terminal.type == "error"
    assert terminal.code == "HERMES_TIMEOUT"
    assert terminal.retryable is True
    assert [event.state for event in events if event.type == "state"][-1] == "paused"
    assert _git(root, "rev-parse", "main").stdout.strip() == baseline


def test_dirty_repository_fails_before_hermes_is_called(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "user-change.md").write_text("not committed", encoding="utf-8")
    request = _start(
        root, _input(tmp_path), "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    )

    terminal = _runner(root, FailingHermes()).handle(request, lambda event: None)

    assert terminal.type == "error"
    assert terminal.code == "DIRTY_WORKTREE"


def test_keyboard_interrupt_pauses_job_without_applying_changes(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    request = _start(
        root, _input(tmp_path), "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    )
    baseline = _git(root, "rev-parse", "main").stdout.strip()
    events: list[Event] = []

    terminal = _runner(root, InterruptingHermes()).handle(request, events.append)

    assert terminal.type == "error"
    assert terminal.code == "CANCELLED"
    assert [event.state for event in events if event.type == "state"][-1] == "paused"
    assert _git(root, "rev-parse", "main").stdout.strip() == baseline
