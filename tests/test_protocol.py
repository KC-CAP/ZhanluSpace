from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from zhanlu_worker.protocol import Event, Request


FIXTURES = Path(__file__).parents[1] / "protocol" / "fixtures"
REQUEST_FIXTURES = ("start-file.json", "start-url.json", "confirm.json")
EVENT_FIXTURES = ("state-event.json", "completed-event.json", "error-event.json")


@pytest.mark.parametrize("fixture_name", REQUEST_FIXTURES)
def test_request_fixture_round_trips_without_semantic_change(fixture_name: str) -> None:
    raw = (FIXTURES / fixture_name).read_text(encoding="utf-8")
    expected = json.loads(raw)
    adapter = TypeAdapter(Request)

    parsed = adapter.validate_json(raw)

    assert json.loads(adapter.dump_json(parsed)) == expected


@pytest.mark.parametrize("fixture_name", EVENT_FIXTURES)
def test_event_fixture_round_trips_without_semantic_change(fixture_name: str) -> None:
    raw = (FIXTURES / fixture_name).read_text(encoding="utf-8")
    expected = json.loads(raw)
    adapter = TypeAdapter(Event)

    parsed = adapter.validate_json(raw)

    assert json.loads(adapter.dump_json(parsed)) == expected


@pytest.mark.parametrize(
    "payload",
    (
        {
            "version": 2,
            "type": "start",
            "job_id": "11111111-1111-4111-8111-111111111111",
            "vault_path": "C:\\Vault",
            "input": {"kind": "file", "value": "C:\\Inbox\\note.md"},
        },
        {
            "version": 1,
            "type": "start",
            "job_id": "11111111-1111-4111-8111-111111111111",
            "vault_path": "relative-vault",
            "input": {"kind": "file", "value": "C:\\Inbox\\note.md"},
        },
        {
            "version": 1,
            "type": "start",
            "job_id": "11111111-1111-4111-8111-111111111111",
            "vault_path": "C:\\Vault",
            "input": {"kind": "url", "value": "file:///C:/private.txt"},
        },
        {
            "version": 1,
            "type": "confirm",
            "job_id": "33333333-3333-4333-8333-333333333333",
            "vault_path": "C:\\Vault",
            "branch": "main",
            "expected_head": "0123456789012345678901234567890123456789",
        },
        {
            "version": 1,
            "type": "confirm",
            "job_id": "33333333-3333-4333-8333-333333333333",
            "vault_path": "C:\\Vault",
            "branch": "knowledge/20260803-confirm",
            "expected_head": "not-a-commit",
        },
    ),
)
def test_request_rejects_invalid_boundary_values(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(Request).validate_python(payload)
