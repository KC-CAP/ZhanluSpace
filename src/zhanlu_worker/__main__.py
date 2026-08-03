"""Strict JSONL command entry point for the local knowledge Worker."""

from __future__ import annotations

import json
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
    launcher_args = _hermes_launcher_args()
    profile = os.environ.get("ZHANLU_HERMES_PROFILE") or None
    timeout = float(os.environ.get("ZHANLU_HERMES_TIMEOUT_SECONDS", "120"))
    adapter = HermesAdapter(
        HermesConfig(
            executable=executable,
            launcher_args=launcher_args,
            profile=profile,
            timeout_seconds=timeout,
        )
    )
    return JobRunner(
        adapter,
        hermes_version=os.environ.get("ZHANLU_HERMES_VERSION", "unknown"),
        hermes_profile=profile,
    )


def _hermes_launcher_args() -> tuple[str, ...]:
    """Read an optional JSON argument array without invoking a command shell."""
    raw = os.environ.get("ZHANLU_HERMES_LAUNCHER_ARGS")
    if not raw:
        return ()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("ZHANLU_HERMES_LAUNCHER_ARGS must be a JSON array") from error
    if (
        not isinstance(value, list)
        or len(value) > 16
        or any(not isinstance(item, str) or not item or "\0" in item for item in value)
    ):
        raise ValueError(
            "ZHANLU_HERMES_LAUNCHER_ARGS must contain 1-16 non-empty strings"
        )
    return tuple(value)


def main() -> None:
    # The plugin protocol is UTF-8 on every platform, independent of the
    # Windows console code page inherited by a Python subprocess.
    sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    sys.stdout.reconfigure(encoding="utf-8", errors="strict", newline="\n")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    raise SystemExit(run_cli(sys.stdin, sys.stdout, sys.stderr, build_runner()))


if __name__ == "__main__":
    main()
