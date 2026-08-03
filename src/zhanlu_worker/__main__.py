"""Strict JSONL command entry point for the local knowledge Worker."""

from __future__ import annotations

import os
import sys
from typing import TextIO
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from .hermes import HermesAdapter, HermesConfig
from .jobs import JobRunner
from .protocol import ErrorEvent, Event, Request


_FALLBACK_JOB_ID = UUID("00000000-0000-4000-8000-000000000000")


def run_cli(stdin: TextIO, stdout: TextIO, stderr: TextIO, runner) -> int:
    raw = stdin.read()
    lines = [line for line in raw.splitlines() if line.strip()]
    if len(lines) != 1:
        return _write_malformed(stdout, "expected exactly one JSON request line")
    try:
        request = TypeAdapter(Request).validate_json(lines[0])
    except ValidationError as error:
        print(f"invalid request: {error}", file=stderr)
        return _write_malformed(stdout, "request does not satisfy protocol version 1")

    adapter = TypeAdapter(Event)

    def emit(event: Event) -> None:
        stdout.write(adapter.dump_json(event).decode("utf-8") + "\n")
        stdout.flush()

    try:
        terminal = runner.handle(request, emit)
    except Exception as error:
        print(f"worker failed: {error}", file=stderr)
        terminal = ErrorEvent(
            version=1,
            type="error",
            job_id=request.job_id,
            code="INTERNAL_ERROR",
            message="worker terminated unexpectedly",
            retryable=False,
        )
    emit(terminal)
    return 0 if terminal.type == "completed" else 1


def _write_malformed(stdout: TextIO, message: str) -> int:
    event = ErrorEvent(
        version=1,
        type="error",
        job_id=_FALLBACK_JOB_ID,
        code="MALFORMED_REQUEST",
        message=message,
        retryable=False,
    )
    stdout.write(TypeAdapter(Event).dump_json(event).decode("utf-8") + "\n")
    stdout.flush()
    return 1


def build_runner() -> JobRunner:
    executable = os.environ.get("ZHANLU_HERMES_EXECUTABLE", "hermes")
    profile = os.environ.get("ZHANLU_HERMES_PROFILE") or None
    timeout = float(os.environ.get("ZHANLU_HERMES_TIMEOUT_SECONDS", "120"))
    adapter = HermesAdapter(
        HermesConfig(
            executable=executable,
            profile=profile,
            timeout_seconds=timeout,
        )
    )
    return JobRunner(
        adapter,
        hermes_version=os.environ.get("ZHANLU_HERMES_VERSION", "unknown"),
        hermes_profile=profile,
    )


def main() -> None:
    raise SystemExit(run_cli(sys.stdin, sys.stdout, sys.stderr, build_runner()))


if __name__ == "__main__":
    main()
