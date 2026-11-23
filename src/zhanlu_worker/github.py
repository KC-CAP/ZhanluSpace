"""GitHub Pull Request operations through the user's authenticated `gh` CLI."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .compiler import ChangeSet


class GitHubError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class GitHubPullRequests:
    def __init__(self, vault_root: Path, *, timeout_seconds: float = 30) -> None:
        self.vault_root = vault_root.resolve(strict=True)
        self.timeout_seconds = timeout_seconds

    def create_or_update_pr(self, branch: str, change_set: ChangeSet) -> str:
        title = f"knowledge: ingest {change_set.ingest_id}"
        body = render_pr_body(change_set)
        existing = self._run("pr", "view", branch, "--json", "url", "--jq", ".url", check=False)
        if existing.returncode == 0 and existing.stdout.strip():
            url = existing.stdout.strip()
            self._require(
                self._run("pr", "edit", branch, "--title", title, "--body", body),
                "GITHUB_PR_UPDATE_FAILED",
            )
            return url
        result = self._run(
            "pr", "create", "--head", branch, "--base", "main",
            "--title", title, "--body", body, check=False,
        )
        self._require(result, "GITHUB_PR_CREATE_FAILED")
        url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        if not url.startswith("https://github.com/"):
            raise GitHubError("GITHUB_PR_URL_MISSING", "gh did not return a GitHub PR URL")
        return url

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["gh", *args], cwd=self.vault_root, text=True, encoding="utf-8",
                errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                check=False, shell=False, timeout=self.timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError as error:
            raise GitHubError("GITHUB_CLI_MISSING", "install GitHub CLI (gh) and sign in") from error
        except subprocess.TimeoutExpired as error:
            raise GitHubError("GITHUB_CLI_TIMEOUT", "GitHub CLI timed out; local branch is preserved") from error
        if check and result.returncode != 0:
            self._require(result, "GITHUB_CLI_FAILED")
        return result

    @staticmethod
    def _require(result: subprocess.CompletedProcess[str], code: str) -> None:
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "GitHub CLI command failed").strip()
            raise GitHubError(code, detail[:1000])


def render_pr_body(change_set: ChangeSet) -> str:
    lines = [
        "## Zhanlu Knowledge change",
        "",
        f"- Ingest ID: `{change_set.ingest_id}`",
        f"- Source ID: `{change_set.source_id}`",
        f"- Semantic actions: {', '.join(change_set.semantic_actions)}",
        "",
        "### Changed files",
    ]
    lines.extend(f"- `{change.operation}` `{change.path.as_posix()}`" for change in change_set.changes)
    lines.extend(["", "### Risk notes"])
    lines.extend(f"- {warning}" for warning in change_set.warnings)
    lines.extend(["", "Generated from the validated manifest and Git change set; review the Files changed tab before approval."])
    return "\n".join(lines)
