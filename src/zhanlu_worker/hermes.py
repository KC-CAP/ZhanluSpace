"""Hermes one-shot adapter with a narrow, structured output boundary."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .proposals import CompilationProposal
from .sources import NormalizedSource
from .vault import KnowledgeRecord, VaultDocument


DEFAULT_TIMEOUT_SECONDS = 120.0
MAX_CONTEXT_DOCUMENTS = 20
MAX_CONTEXT_BYTES = 60_000
MAX_BODY_EXCERPT_CHARS = 4_000


class HermesError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        stderr: str = "",
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.stderr = _redact(stderr)
        detail = f"{code}: {message}"
        if self.stderr:
            detail += f"; stderr={self.stderr}"
        super().__init__(detail)


@dataclass(frozen=True)
class HermesConfig:
    executable: str = "hermes"
    launcher_args: tuple[str, ...] = ()
    profile: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    environment: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeContext:
    knowledge_id: str
    title: str
    status: str
    source_ids: list[str]
    relations: list[dict[str, Any]]
    body_excerpt: str

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "knowledge_id": self.knowledge_id,
            "title": self.title,
            "status": self.status,
            "source_ids": self.source_ids,
            "relations": self.relations,
            "body_excerpt": self.body_excerpt,
        }


def _tokens(value: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9]+|[\u3400-\u9fff]", value)
    }


def select_context(
    source_text: str,
    documents: list[VaultDocument],
) -> list[KnowledgeContext]:
    source_tokens = _tokens(source_text)
    ranked: list[tuple[int, str, VaultDocument]] = []
    for document in documents:
        if not isinstance(document.record, KnowledgeRecord):
            continue
        score = len(source_tokens & _tokens(f"{document.title}\n{document.body}"))
        if score:
            ranked.append((score, document.record.id, document))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    selected: list[KnowledgeContext] = []
    for _score, _knowledge_id, document in ranked[:MAX_CONTEXT_DOCUMENTS]:
        record = document.record
        assert isinstance(record, KnowledgeRecord)
        candidate = KnowledgeContext(
            knowledge_id=record.id,
            title=document.title,
            status=record.status,
            source_ids=list(record.sources),
            relations=[relation.model_dump(mode="json") for relation in record.relations],
            body_excerpt=document.body[:MAX_BODY_EXCERPT_CHARS],
        )
        proposed = selected + [candidate]
        encoded = json.dumps(
            [item.to_prompt_dict() for item in proposed],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > MAX_CONTEXT_BYTES:
            break
        selected.append(candidate)
    return selected


class HermesAdapter:
    def __init__(self, config: HermesConfig) -> None:
        self.config = config

    def compile(
        self,
        source: NormalizedSource,
        context: list[KnowledgeContext],
        job_dir: Path,
    ) -> CompilationProposal:
        working_directory = job_dir.resolve(strict=True)
        prompt = _build_prompt(source, context)
        arguments = [self.config.executable, *self.config.launcher_args]
        if self.config.profile:
            arguments.extend(["--profile", self.config.profile])
        arguments.extend(["--ignore-rules", "-z", prompt])
        environment = os.environ.copy()
        environment.update(self.config.environment)
        creation_flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        )
        process = subprocess.Popen(
            arguments,
            cwd=working_directory,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            env=environment,
            creationflags=creation_flags,
            start_new_session=os.name != "nt",
        )
        try:
            stdout, stderr = process.communicate(timeout=self.config.timeout_seconds)
        except subprocess.TimeoutExpired as error:
            _kill_process_tree(process)
            stdout, stderr = process.communicate()
            raise HermesError(
                "HERMES_TIMEOUT",
                "Hermes exceeded the configured timeout",
                retryable=True,
                stderr=stderr,
            ) from error
        if process.returncode != 0:
            raise HermesError(
                "HERMES_FAILED",
                f"Hermes exited with code {process.returncode}",
                retryable=True,
                stderr=stderr,
            )
        if stdout.lstrip().startswith("hermes -z: agent failed:"):
            raise HermesError(
                "HERMES_FAILED",
                "Hermes could not complete the inference request",
                retryable=True,
                stderr="\n".join(part for part in (stdout, stderr) if part),
            )

        try:
            payload = _parse_single_json_object(stdout)
        except (json.JSONDecodeError, ValueError) as error:
            raise HermesError(
                "HERMES_INVALID_JSON",
                "Hermes did not return exactly one JSON object",
                stderr=stderr,
            ) from error
        try:
            proposal = CompilationProposal.model_validate(payload)
        except ValidationError as error:
            raise HermesError(
                "HERMES_INVALID_PROPOSAL",
                "Hermes output does not satisfy the proposal schema",
                stderr=stderr,
            ) from error
        if proposal.source_id != source.source_id:
            raise HermesError(
                "HERMES_INVALID_PROPOSAL",
                "Hermes proposal references a different source",
            )
        return proposal


def _build_prompt(
    source: NormalizedSource,
    context: list[KnowledgeContext],
) -> str:
    rules_path = Path(__file__).with_name("prompts") / "knowledge_compiler.md"
    rules = rules_path.read_text(encoding="utf-8")
    output_schema_json = json.dumps(
        CompilationProposal.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    context_json = json.dumps(
        [item.to_prompt_dict() for item in context],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        f"{rules}\n\n"
        "BEGIN TRUSTED OUTPUT JSON SCHEMA\n"
        f"{output_schema_json}\n"
        "END TRUSTED OUTPUT JSON SCHEMA\n\n"
        f"CURRENT SOURCE ID: {source.source_id}\n\n"
        "BEGIN UNTRUSTED SOURCE\n"
        f"{source.normalized_text}"
        "END UNTRUSTED SOURCE\n\n"
        "BEGIN UNTRUSTED EXISTING KNOWLEDGE JSON\n"
        f"{context_json}\n"
        "END UNTRUSTED EXISTING KNOWLEDGE JSON\n"
    )


def _parse_single_json_object(output: str) -> dict[str, Any]:
    stripped = output.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) < 3 or lines[-1].strip() != "```":
            raise ValueError("unterminated JSON code fence")
        stripped = "\n".join(lines[1:-1]).strip()
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("Hermes output must be a JSON object")
    return payload


def _kill_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            shell=False,
        )
    else:
        os.killpg(process.pid, signal.SIGKILL)


def _redact(value: str) -> str:
    redacted = re.sub(
        r"(?i)(?:api[_-]?key|token|secret|password)\s*=\s*[^\s]+",
        "[REDACTED]",
        value,
    )
    return re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", redacted).strip()
