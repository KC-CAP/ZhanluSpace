"""Restricted Git transactions for validated knowledge changes."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .compiler import ChangeSet, FileChange
from .risk import RiskAssessment
from .validation import validate_vault


class GitError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class GitResult:
    outcome: Literal["merged", "ready", "no_change"]
    branch: str
    head: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


class GitController:
    def __init__(
        self,
        vault_root: Path,
        *,
        clock: Callable[[], datetime] = _utc_now,
        timeout_seconds: float = 30,
    ) -> None:
        self.vault_root = vault_root.resolve(strict=True)
        self.clock = clock
        self.timeout_seconds = timeout_seconds

    def apply(self, change_set: ChangeSet, risk: RiskAssessment) -> GitResult:
        self._preflight()
        branch = self._branch_name(change_set.ingest_id)
        if not change_set.changes:
            return GitResult("no_change", branch, self._rev_parse("main"))
        if self._ref_exists(f"refs/heads/{branch}"):
            raise GitError("PROPOSAL_BRANCH_EXISTS", f"branch already exists: {branch}")
        self._verify_optimistic_hashes(change_set.changes)

        backup: dict[Path, bytes | None] = {}
        branch_created = False
        committed = False
        try:
            self._require(self._run("switch", "-c", branch, "main"), "BRANCH_CREATE_FAILED")
            branch_created = True
            backup = self._apply_files(change_set.changes)
            report = validate_vault(self.vault_root)
            if not report.ok:
                codes = ", ".join(issue.code for issue in report.issues[:10])
                raise GitError("VAULT_VALIDATION_FAILED", codes)
            paths = sorted(change.path.as_posix() for change in change_set.changes)
            self._require(self._run("add", "--", *paths), "GIT_STAGE_FAILED")
            staged = {
                item
                for item in self._run("diff", "--cached", "--name-only", "-z").stdout.split("\0")
                if item
            }
            if staged != set(paths):
                raise GitError(
                    "UNEXPECTED_STAGED_PATHS",
                    f"expected {paths}, staged {sorted(staged)}",
                )
            commit = self._run(
                "commit",
                "-m",
                f"knowledge: ingest {change_set.ingest_id}",
                "-m",
                f"Source: {change_set.source_id}",
            )
            if commit.returncode != 0:
                raise GitError("GIT_COMMIT_FAILED", _command_message(commit))
            committed = True
            head = self._rev_parse("HEAD")
            self._require(self._run("switch", "main"), "RETURN_TO_MAIN_FAILED")
            if risk.level == "high":
                return GitResult("ready", branch, head)
            merge = self._run("merge", "--ff-only", branch)
            if merge.returncode != 0:
                raise GitError("FAST_FORWARD_FAILED", _command_message(merge))
            self._require(self._run("branch", "-d", branch), "BRANCH_DELETE_FAILED")
            return GitResult("merged", branch, head)
        except Exception:
            if not committed:
                self._rollback_uncommitted(change_set.changes, backup)
                if self._current_branch() != "main":
                    self._run("switch", "main")
                if branch_created and self._ref_exists(f"refs/heads/{branch}"):
                    self._run("branch", "-d", branch)
            elif self._current_branch() != "main":
                self._run("switch", "main")
            raise

    def confirm(self, branch: str, expected_head: str) -> GitResult:
        self._preflight()
        if not re.fullmatch(r"knowledge/[0-9]{8}-[a-z0-9][a-z0-9-]{0,63}", branch):
            raise GitError("INVALID_PROPOSAL_BRANCH", branch)
        if not self._ref_exists(f"refs/heads/{branch}"):
            raise GitError("PROPOSAL_BRANCH_MISSING", branch)
        actual_head = self._rev_parse(branch)
        if actual_head != expected_head:
            raise GitError(
                "STALE_PROPOSAL_HEAD",
                f"expected {expected_head}, proposal is {actual_head}",
            )
        ancestor = self._run("merge-base", "--is-ancestor", "main", branch)
        if ancestor.returncode != 0:
            raise GitError("MAIN_DIVERGED", "main is not an ancestor of the proposal")

        self._require(self._run("switch", branch), "PROPOSAL_SWITCH_FAILED")
        try:
            report = validate_vault(self.vault_root)
            if not report.ok:
                codes = ", ".join(issue.code for issue in report.issues[:10])
                raise GitError("VAULT_VALIDATION_FAILED", codes)
        finally:
            self._require(self._run("switch", "main"), "RETURN_TO_MAIN_FAILED")
        merge = self._run("merge", "--ff-only", branch)
        if merge.returncode != 0:
            raise GitError("FAST_FORWARD_FAILED", _command_message(merge))
        self._require(self._run("branch", "-d", branch), "BRANCH_DELETE_FAILED")
        return GitResult("merged", branch, actual_head)

    def _preflight(self) -> None:
        top = self._run("rev-parse", "--show-toplevel")
        if top.returncode != 0:
            raise GitError("NOT_A_GIT_REPOSITORY", _command_message(top))
        repository_root = Path(top.stdout.strip()).resolve()
        if repository_root != self.vault_root:
            raise GitError(
                "REPOSITORY_ROOT_MISMATCH",
                f"Vault {self.vault_root} is inside repository {repository_root}",
            )
        if not self._ref_exists("refs/heads/main"):
            raise GitError("MAIN_BRANCH_MISSING", "local main branch is required")
        if self._current_branch() != "main":
            raise GitError("MAIN_NOT_CHECKED_OUT", "switch to main before importing")
        status = self._run("status", "--porcelain", "--untracked-files=all")
        self._require(status, "GIT_STATUS_FAILED")
        if status.stdout:
            raise GitError("DIRTY_WORKTREE", "commit, stash, or remove current changes first")

    def _branch_name(self, ingest_id: str) -> str:
        date = self.clock().astimezone(UTC).strftime("%Y%m%d")
        slug = re.sub(r"[^a-z0-9-]", "", ingest_id.lower())[:8] or "import"
        return f"knowledge/{date}-{slug}"

    def _verify_optimistic_hashes(self, changes: tuple[FileChange, ...]) -> None:
        for change in changes:
            if change.operation not in {"create", "update"}:
                raise GitError("UNSUPPORTED_FILE_OPERATION", change.operation)
            target = self._safe_target(change)
            if target.is_symlink():
                raise GitError("SYMLINK_NOT_ALLOWED", change.path.as_posix())
            if change.operation == "create":
                if target.exists() or change.before_sha256 is not None:
                    raise GitError("OPTIMISTIC_HASH_MISMATCH", change.path.as_posix())
            else:
                if not target.is_file() or change.before_sha256 is None:
                    raise GitError("OPTIMISTIC_HASH_MISMATCH", change.path.as_posix())
                current = hashlib.sha256(target.read_bytes()).hexdigest()
                if current != change.before_sha256:
                    raise GitError("OPTIMISTIC_HASH_MISMATCH", change.path.as_posix())
            after = hashlib.sha256(change.content).hexdigest()
            if change.after_sha256 != after:
                raise GitError("CHANGESET_HASH_MISMATCH", change.path.as_posix())

    def _safe_target(self, change: FileChange) -> Path:
        target = self.vault_root.joinpath(*change.path.parts)
        try:
            target.resolve(strict=False).relative_to(self.vault_root)
        except ValueError as error:
            raise GitError("PATH_OUTSIDE_VAULT", change.path.as_posix()) from error
        return target

    def _apply_files(self, changes: tuple[FileChange, ...]) -> dict[Path, bytes | None]:
        backup: dict[Path, bytes | None] = {}
        for change in changes:
            target = self._safe_target(change)
            backup[target] = target.read_bytes() if target.exists() else None
            target.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(target, change.content)
        return backup

    def _rollback_uncommitted(
        self,
        changes: tuple[FileChange, ...],
        backup: dict[Path, bytes | None],
    ) -> None:
        paths = [change.path.as_posix() for change in changes]
        if paths:
            self._run("restore", "--staged", "--", *paths)
        for target, previous in reversed(list(backup.items())):
            if previous is None:
                if target.exists():
                    target.unlink()
            else:
                _atomic_write(target, previous)

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        try:
            return subprocess.run(
                ["git", *args],
                cwd=self.vault_root,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                shell=False,
                timeout=self.timeout_seconds,
                env=environment,
            )
        except subprocess.TimeoutExpired as error:
            raise GitError("GIT_TIMEOUT", "git command timed out") from error

    def _require(
        self, result: subprocess.CompletedProcess[str], code: str
    ) -> subprocess.CompletedProcess[str]:
        if result.returncode != 0:
            raise GitError(code, _command_message(result))
        return result

    def _ref_exists(self, ref: str) -> bool:
        return self._run("show-ref", "--verify", "--quiet", ref).returncode == 0

    def _rev_parse(self, ref: str) -> str:
        result = self._run("rev-parse", "--verify", ref)
        self._require(result, "REV_PARSE_FAILED")
        return result.stdout.strip()

    def _current_branch(self) -> str:
        result = self._run("branch", "--show-current")
        self._require(result, "BRANCH_READ_FAILED")
        return result.stdout.strip()


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.zhanlu-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _command_message(result: subprocess.CompletedProcess[str]) -> str:
    message = (result.stderr or result.stdout or "git command failed").strip()
    return re.sub(r"\b(?:ghp|github_pat|sk)-[A-Za-z0-9_-]+", "[REDACTED]", message)
