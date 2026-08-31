from __future__ import annotations

import io
import json

from zhanlu_worker.__main__ import run_cli
from zhanlu_worker.protocol import CompletedEvent, ErrorEvent, StateEvent


VALID_REQUEST = {
    "version": 1,
    "type": "start",
    "job_id": "11111111-1111-4111-8111-111111111111",
    "vault_path": "C:\\Vault",
    "input": {"kind": "file", "value": "C:\\Inbox\\note.md"},
}


class SuccessfulRunner:
    def handle(self, request, emit):
        emit(
            StateEvent(
                version=1,
                type="state",
                job_id=request.job_id,
                state="queued",
                message="任务已排队",
            )
        )
        return CompletedEvent.model_validate(
            {
                "version": 1,
                "type": "completed",
                "job_id": str(request.job_id),
                "result": {
                    "outcome": "ready",
                    "risk": "high",
                    "branch": "knowledge/20260803-confirm",
                    "head": "0" * 40,
                    "changed_files": ["knowledge/topics/example.md"],
                    "ingest_manifest": "_meta/ingests/example.md",
                    "risk_reasons": ["MANUAL"],
                },
            }
        )


class ErrorRunner:
    def handle(self, request, emit):
        return ErrorEvent(
            version=1,
            type="error",
            job_id=request.job_id,
            code="TEST_FAILURE",
            message="controlled failure",
            retryable=False,
        )


def test_cli_writes_ordered_jsonl_and_returns_zero_for_completed() -> None:
    stdin = io.StringIO(json.dumps(VALID_REQUEST) + "\n")
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = run_cli(stdin, stdout, stderr, SuccessfulRunner())

    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [line["type"] for line in lines] == ["state", "completed"]
    assert exit_code == 0
    assert stderr.getvalue() == ""


def test_cli_returns_one_for_runner_error() -> None:
    stdin = io.StringIO(json.dumps(VALID_REQUEST) + "\n")
    stdout = io.StringIO()

    exit_code = run_cli(stdin, stdout, io.StringIO(), ErrorRunner())

    assert json.loads(stdout.getvalue())["code"] == "TEST_FAILURE"
    assert exit_code == 1


def test_cli_rejects_empty_or_multiple_requests() -> None:
    for raw in ("", json.dumps(VALID_REQUEST) + "\n" + json.dumps(VALID_REQUEST) + "\n"):
        stdout = io.StringIO()

        exit_code = run_cli(io.StringIO(raw), stdout, io.StringIO(), SuccessfulRunner())

        event = json.loads(stdout.getvalue())
        assert event["type"] == "error"
        assert event["code"] == "MALFORMED_REQUEST"
        assert exit_code == 1


def test_cli_rejects_malformed_json_without_traceback_on_stdout() -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = run_cli(io.StringIO("{broken}\n"), stdout, stderr, SuccessfulRunner())

    event = json.loads(stdout.getvalue())
    assert event["type"] == "error"
    assert event["code"] == "MALFORMED_REQUEST"
    assert "Traceback" not in stdout.getvalue()
    assert exit_code == 1
