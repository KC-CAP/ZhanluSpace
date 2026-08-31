from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from zhanlu_worker.validation import validate_vault


ROOT = Path(__file__).parents[2]
SOURCE = ROOT / "tests" / "fixtures" / "e2e" / "source.md"
FAKE_HERMES = ROOT / "tests" / "fixtures" / "bin" / "fake-hermes.py"


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        check=True,
        text=True,
        encoding="utf-8",
        capture_output=True,
        shell=False,
    )


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    shutil.copytree(ROOT / "vault-template", vault)
    _run("git", "init", "-b", "main", cwd=vault)
    _run("git", "config", "user.name", "Zhanlu E2E", cwd=vault)
    _run("git", "config", "user.email", "e2e@example.invalid", cwd=vault)
    _run("git", "add", ".", cwd=vault)
    _run("git", "commit", "-m", "Initialize knowledge vault", cwd=vault)
    return vault


def _import(vault: Path, job_id: str) -> list[dict[str, object]]:
    request = {
        "version": 1,
        "type": "start",
        "job_id": job_id,
        "vault_path": str(vault),
        "input": {"kind": "file", "value": str(SOURCE)},
    }
    environment = os.environ.copy()
    environment.update(
        {
            "ZHANLU_HERMES_EXECUTABLE": sys.executable,
            "ZHANLU_HERMES_LAUNCHER_ARGS": json.dumps([str(FAKE_HERMES)]),
            "ZHANLU_HERMES_VERSION": "fake-e2e",
            "ZHANLU_HERMES_PROFILE": "deterministic-e2e",
            "FAKE_HERMES_MODE": "dynamic-create",
        }
    )
    result = subprocess.run(
        [sys.executable, "-m", "zhanlu_worker"],
        input=json.dumps(request) + "\n",
        cwd=vault,
        env=environment,
        check=False,
        text=True,
        encoding="utf-8",
        capture_output=True,
        shell=False,
        timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    return [json.loads(line) for line in result.stdout.splitlines() if line]


def test_personal_file_import_is_merged_valid_and_idempotent(tmp_path: Path) -> None:
    vault = _vault(tmp_path)

    first = _import(vault, "11111111-1111-4111-8111-111111111111")

    assert [event["state"] for event in first if event["type"] == "state"] == [
        "queued",
        "acquiring",
        "extracting",
        "compiling",
        "validating",
        "committed",
        "merged",
    ]
    assert first[-1]["type"] == "completed"
    assert first[-1]["result"]["outcome"] == "merged"
    assert _run("git", "branch", "--show-current", cwd=vault).stdout.strip() == "main"
    assert not _run("git", "status", "--porcelain", cwd=vault).stdout
    assert validate_vault(vault).ok

    second = _import(vault, "22222222-2222-4222-8222-222222222222")

    assert second[-1]["type"] == "completed"
    assert second[-1]["result"]["outcome"] == "no_change"
    assert len(list((vault / "knowledge").rglob("*.md"))) == 1
    assert len(list((vault / "sources").rglob("source.md"))) == 1
    assert not _run("git", "status", "--porcelain", cwd=vault).stdout
