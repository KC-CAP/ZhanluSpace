from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from zhanlu_worker.proposals import CompilationProposal


FIXTURES = Path(__file__).parent / "fixtures" / "hermes"


@pytest.mark.parametrize(
    "fixture_name", ("create.json", "supplement.json", "contradict.json", "no-change.json")
)
def test_valid_compilation_proposals_round_trip(fixture_name: str) -> None:
    raw = (FIXTURES / fixture_name).read_text(encoding="utf-8")

    proposal = CompilationProposal.model_validate_json(raw)

    assert json.loads(proposal.model_dump_json(exclude_none=True)) == json.loads(raw)


def _create_payload() -> dict[str, object]:
    return json.loads((FIXTURES / "create.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "mutate",
    (
        lambda payload: payload["actions"][0].update(action="invent"),
        lambda payload: payload["actions"][0]["relations"][0].update(type="related_to"),
        lambda payload: payload["actions"][0].update(path="knowledge/owned-by-model.md"),
        lambda payload: payload["actions"][0].update(knowledge_id="Bad ID"),
        lambda payload: payload["actions"][0].update(confidence=1.1),
        lambda payload: payload["actions"][0].update(
            citations=["source:sha256:" + "b" * 64]
        ),
        lambda payload: payload["actions"][0]["relations"].append(
            copy.deepcopy(payload["actions"][0]["relations"][0])
        ),
    ),
)
def test_rejects_unsafe_or_inconsistent_proposals(mutate) -> None:
    payload = _create_payload()
    mutate(payload)

    with pytest.raises(ValidationError):
        CompilationProposal.model_validate(payload)


def test_no_change_must_be_the_only_action() -> None:
    payload = json.loads((FIXTURES / "no-change.json").read_text(encoding="utf-8"))
    payload["actions"].append(_create_payload()["actions"][0])

    with pytest.raises(ValidationError):
        CompilationProposal.model_validate(payload)
