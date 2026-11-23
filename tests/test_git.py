from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pytest

from zhanlu_worker.compiler import ChangeCompiler, ChangeSet, CompileMetadata, FileChange
from zhanlu_worker.git import GitController, GitError
from zhanlu_worker.git import _github_repository
from zhanlu_worker.git import _github_repository
from zhanlu_worker.github import GitHubPullRequests, render_pr_body
from zhanlu_worker.proposals import CompilationProposal
from zhanlu_worker.risk import RiskAssessment
from zhanlu_worker.sources import acquire_file

from .test_vault import _write_basic_vault


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
INGEST_ID = "55555555-5555-4555-8555-555555555555"


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=check,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    _write_basic_vault(root)
    (root / ".gitignore").write_text(".knowledge-runtime/\nteam-shared.md\n", encoding="utf-8")
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Zhanlu Test")
    _git(root, "config", "user.email", "zhanlu@example.invalid")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial vault")
    return root


def _change_set(tmp_path: Path, root: Path) -> ChangeSet:
    inbox = tmp_path / "inbox"
    inbox.mkdir(exist_ok=True)
    source_path = inbox / "incoming.md"
    source_path.write_text("# 新知识\n\n关键词与语义召回互补。\n", encoding="utf-8")
    source = acquire_file(source_path, now=lambda: NOW)
    proposal = CompilationProposal.model_validate(
        {
            "schema_version": 1,
            "source_id": source.source_id,
            "actions": [
                {
                    "action": "create",
                    "knowledge_id": "method:hybrid-retrieval",
                    "title": "混合召回",
                    "knowledge_type": "method",
                    "status": "draft",
                    "confidence": 0.8,
                    "content": "混合召回组合关键词与语义检索。",
                    "citations": [source.source_id],
                    "relations": [],
                }
            ],
        }
    )
    metadata = CompileMetadata(
        ingest_id=INGEST_ID,
        submitted_by="local-user",
        hermes_version="0.19.1",
        hermes_profile="test",
        compiler_version="0.1.0",
        schema_version=1,
        created_at=NOW,
    )
    return ChangeCompiler(root).compile(
        source, proposal, metadata, original_path=source_path
    )


def _controller(root: Path) -> GitController:
    return GitController(root, clock=lambda: NOW)


def test_rejects_vault_that_is_not_repository_root(tmp_path: Path) -> None:
    root = _repository(tmp_path)

    with pytest.raises(GitError, match="REPOSITORY_ROOT_MISMATCH"):
        GitController(root / "knowledge", clock=lambda: NOW).apply(
            _change_set(tmp_path, root), RiskAssessment("low", ())
        )


def test_rejects_repository_without_main_branch(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _git(root, "branch", "-m", "main", "trunk")

    with pytest.raises(GitError, match="MAIN_BRANCH_MISSING"):
        _controller(root).apply(_change_set(tmp_path, root), RiskAssessment("low", ()))


def test_dirty_worktree_rejects_before_branch_creation(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    (root / "scratch.txt").write_text("user work", encoding="utf-8")

    with pytest.raises(GitError, match="DIRTY_WORKTREE"):
        _controller(root).apply(_change_set(tmp_path, root), RiskAssessment("low", ()))

    assert "knowledge/20260803-55555555" not in _git(root, "branch", "--list").stdout


def test_low_risk_change_commits_and_fast_forwards_main(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    change_set = _change_set(tmp_path, root)
    baseline = _git(root, "rev-parse", "HEAD").stdout.strip()

    result = _controller(root).apply(change_set, RiskAssessment("low", ()))

    assert result.outcome == "merged"
    assert _git(root, "branch", "--show-current").stdout.strip() == "main"
    assert _git(root, "rev-parse", "HEAD").stdout.strip() == result.head
    assert result.head != baseline
    assert (root / "knowledge" / "methods" / "hybrid-retrieval.md").exists()
    assert _git(root, "status", "--porcelain").stdout == ""
    assert _git(root, "branch", "--list", result.branch).stdout == ""
    commit = _git(root, "show", "-s", "--format=%B", "HEAD").stdout
    assert INGEST_ID in commit
    assert change_set.source_id in commit
    assert "关键词与语义召回互补" not in commit


def test_team_change_stays_on_contribution_branch_even_when_low_risk(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    change_set = _change_set(tmp_path, root)
    baseline = _git(root, "rev-parse", "main").stdout.strip()

    result = _controller(root).apply(
        change_set, RiskAssessment("low", ()), auto_merge=False
    )

    assert result.outcome == "ready"
    assert _git(root, "branch", "--show-current").stdout.strip() == "main"
    assert _git(root, "rev-parse", "main").stdout.strip() == baseline
    assert _git(root, "rev-parse", result.branch).stdout.strip() == result.head
    assert not (root / "knowledge" / "methods" / "hybrid-retrieval.md").exists()
    assert _git(root, "status", "--porcelain").stdout == ""


def test_team_preflight_fast_forwards_clean_main_to_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repository(tmp_path)
    remote = tmp_path / "team.git"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(root, "remote", "add", "origin", str(remote))
    monkeypatch.setattr("zhanlu_worker.git._github_repository", lambda _: "team/vault")
    _git(root, "push", "--set-upstream", "origin", "main")
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(remote), str(peer))
    _git(peer, "fetch", "origin", "main")
    _git(peer, "switch", "-C", "main", "origin/main")
    _git(peer, "config", "user.name", "Team Peer")
    _git(peer, "config", "user.email", "peer@example.invalid")
    (peer / "team.md").write_text("approved team change\n", encoding="utf-8")
    _git(peer, "add", "team.md")
    _git(peer, "commit", "-m", "team change")
    _git(peer, "push", "origin", "main")

    _controller(root).team_preflight("team/vault")

    assert _git(root, "rev-parse", "main").stdout == _git(root, "rev-parse", "origin/main").stdout
    assert (root / "team.md").read_text(encoding="utf-8") == "approved team change\n"
    assert _git(root, "status", "--porcelain").stdout == ""


def test_team_preflight_refuses_to_overwrite_ignored_local_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repository(tmp_path)
    remote = tmp_path / "team.git"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(root, "remote", "add", "origin", str(remote))
    monkeypatch.setattr("zhanlu_worker.git._github_repository", lambda _: "team/vault")
    _git(root, "push", "--set-upstream", "origin", "main")
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(remote), str(peer))
    _git(peer, "fetch", "origin", "main")
    _git(peer, "switch", "-C", "main", "origin/main")
    _git(peer, "config", "user.name", "Team Peer")
    _git(peer, "config", "user.email", "peer@example.invalid")
    (peer / "team-shared.md").write_text("remote version\n", encoding="utf-8")
    _git(peer, "add", "-f", "team-shared.md")
    _git(peer, "commit", "-m", "tracked shared file")
    _git(peer, "push", "origin", "main")
    local_file = root / "team-shared.md"
    local_file.write_text("local ignored version\n", encoding="utf-8")
    baseline = _git(root, "rev-parse", "main").stdout

    with pytest.raises(GitError, match="TEAM_SYNC_FAILED"):
        _controller(root).team_preflight("team/vault")

    assert local_file.read_text(encoding="utf-8") == "local ignored version\n"
    assert _git(root, "rev-parse", "main").stdout == baseline


@pytest.mark.parametrize(
    ("remote", "expected"),
    (
        ("https://github.com/team/vault.git", "team/vault"),
        ("git@github.com:team/vault.git", "team/vault"),
        ("ssh://git@github.com/team/vault.git", "team/vault"),
        ("https://example.com/team/vault.git", None),
        ("https://user:token@github.com/team/vault.git", None),
    ),
)
def test_team_remote_must_be_unambiguous_github_url(remote: str, expected: str | None) -> None:
    assert _github_repository(remote) == expected


def test_team_preflight_rejects_different_fetch_and_push_repositories(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _git(root, "remote", "add", "origin", "https://github.com/team/vault.git")
    _git(root, "remote", "set-url", "--push", "origin", "https://github.com/other/vault.git")

    with pytest.raises(GitError, match="TEAM_REMOTE_MISMATCH"):
        _controller(root).team_preflight("other/vault")


@pytest.mark.parametrize(
    ("remote", "expected"),
    (
        ("https://github.com/team/vault.git", "team/vault"),
        ("git@github.com:team/vault.git", "team/vault"),
        ("ssh://git@github.com/team/vault.git", "team/vault"),
        ("https://example.com/team/vault.git", None),
        ("https://user:token@github.com/team/vault.git", None),
    ),
)
def test_team_remote_must_be_unambiguous_github_url(remote: str, expected: str | None) -> None:
    assert _github_repository(remote) == expected


def test_team_preflight_rejects_different_fetch_and_push_repositories(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    _git(root, "remote", "add", "origin", "https://github.com/team/vault.git")
    _git(root, "remote", "set-url", "--push", "origin", "https://github.com/other/vault.git")

    with pytest.raises(GitError, match="TEAM_REMOTE_MISMATCH"):
        _controller(root).team_preflight("team/vault")


def test_github_pr_body_is_derived_from_changes_without_source_text(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    change_set = _change_set(tmp_path, root)

    body = render_pr_body(change_set)

    assert change_set.ingest_id in body
    assert change_set.source_id in body
    assert "knowledge/methods/hybrid-retrieval.md" in body
    assert "关键词与语义召回互补" not in body


def test_github_client_creates_reviewable_pr_with_argument_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repository(tmp_path)
    change_set = _change_set(tmp_path, root)
    calls: list[tuple[list[str], dict[str, object]]] = []
    responses = [
        subprocess.CompletedProcess([], 0, "", ""),
        subprocess.CompletedProcess([], 0, "https://github.com/team/vault/pull/7\n", ""),
    ]

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        return responses.pop(0)

    monkeypatch.setattr("zhanlu_worker.github.subprocess.run", fake_run)

    url = GitHubPullRequests(root).create_or_update_pr(
        "knowledge/20260803-55555555", change_set, repo="team/vault"
    )

    assert url == "https://github.com/team/vault/pull/7"
    assert calls[0][0][:4] == ["gh", "pr", "list", "--repo"]
    create_args = calls[1][0]
    assert create_args[:3] == ["gh", "pr", "create"]
    assert "--draft" not in create_args
    assert "--title" in create_args and "--body" in create_args
    assert calls[1][1]["shell"] is False


def test_high_risk_change_stays_on_proposal_branch_until_confirmed(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    change_set = _change_set(tmp_path, root)
    baseline = _git(root, "rev-parse", "main").stdout.strip()

    ready = _controller(root).apply(
        change_set, RiskAssessment("high", ("CONTRADICTS_OR_SUPERSEDES",))
    )

    assert ready.outcome == "ready"
    assert _git(root, "branch", "--show-current").stdout.strip() == "main"
    assert _git(root, "rev-parse", "main").stdout.strip() == baseline
    assert _git(root, "rev-parse", ready.branch).stdout.strip() == ready.head
    assert not (root / "knowledge" / "methods" / "hybrid-retrieval.md").exists()

    merged = _controller(root).confirm(ready.branch, ready.head)

    assert merged.outcome == "merged"
    assert _git(root, "rev-parse", "main").stdout.strip() == ready.head
    assert (root / "knowledge" / "methods" / "hybrid-retrieval.md").exists()
    assert _git(root, "branch", "--list", ready.branch).stdout == ""


def test_confirm_rejects_stale_expected_head(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    ready = _controller(root).apply(
        _change_set(tmp_path, root), RiskAssessment("high", ("MANUAL",))
    )

    with pytest.raises(GitError, match="STALE_PROPOSAL_HEAD"):
        _controller(root).confirm(ready.branch, "0" * 40)

    assert _git(root, "branch", "--list", ready.branch).stdout.strip()


def test_confirm_rejects_main_that_diverged_after_proposal(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    ready = _controller(root).apply(
        _change_set(tmp_path, root), RiskAssessment("high", ("MANUAL",))
    )
    (root / "manual.md").write_text("manual main change", encoding="utf-8")
    _git(root, "add", "manual.md")
    _git(root, "commit", "-m", "manual main change")

    with pytest.raises(GitError, match="MAIN_DIVERGED"):
        _controller(root).confirm(ready.branch, ready.head)


def test_optimistic_hash_mismatch_leaves_main_unchanged(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    change_set = _change_set(tmp_path, root)
    first = change_set.changes[0]
    corrupted = FileChange(
        operation=first.operation,
        path=first.path,
        content=first.content,
        before_sha256="f" * 64 if first.operation == "update" else first.before_sha256,
        after_sha256=first.after_sha256,
    )
    changed = ChangeSet(
        **{**change_set.__dict__, "changes": (corrupted, *change_set.changes[1:])}
    )
    baseline = _git(root, "rev-parse", "HEAD").stdout.strip()

    if first.operation == "create":
        (root / Path(first.path.as_posix())).parent.mkdir(parents=True, exist_ok=True)
        (root / Path(first.path.as_posix())).write_text("unexpected", encoding="utf-8")
        _git(root, "add", first.path.as_posix())
        _git(root, "commit", "-m", "occupy create path")
        baseline = _git(root, "rev-parse", "HEAD").stdout.strip()

    with pytest.raises(GitError, match="OPTIMISTIC_HASH_MISMATCH"):
        _controller(root).apply(changed, RiskAssessment("low", ()))

    assert _git(root, "rev-parse", "HEAD").stdout.strip() == baseline
    assert _git(root, "status", "--porcelain").stdout == ""


def test_validation_failure_restores_owned_paths_and_main(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    content = b"not frontmatter\n"
    invalid = FileChange(
        operation="create",
        path=PurePosixPath("knowledge/topics/invalid.md"),
        content=content,
        before_sha256=None,
        after_sha256=hashlib.sha256(content).hexdigest(),
    )
    change_set = ChangeSet(
        ingest_id=INGEST_ID,
        source_id="source:sha256:" + "a" * 64,
        changes=(invalid,),
        semantic_actions=("create",),
        relation_changes=(),
        warnings=(),
        modified_existing_knowledge=0,
        replaces_confirmed=False,
    )
    baseline = _git(root, "rev-parse", "HEAD").stdout.strip()

    with pytest.raises(GitError, match="VAULT_VALIDATION_FAILED"):
        _controller(root).apply(change_set, RiskAssessment("low", ()))

    assert not (root / "knowledge" / "topics" / "invalid.md").exists()
    assert _git(root, "rev-parse", "HEAD").stdout.strip() == baseline
    assert _git(root, "status", "--porcelain").stdout == ""


def test_failed_commit_restores_transaction_without_staging_user_files(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    ignored = root / ".knowledge-runtime" / "local.log"
    ignored.parent.mkdir()
    ignored.write_text("local state", encoding="utf-8")
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8", newline="\n")
    baseline = _git(root, "rev-parse", "HEAD").stdout.strip()

    with pytest.raises(GitError, match="GIT_COMMIT_FAILED"):
        _controller(root).apply(
            _change_set(tmp_path, root), RiskAssessment("low", ())
        )

    assert ignored.read_text(encoding="utf-8") == "local state"
    assert _git(root, "rev-parse", "HEAD").stdout.strip() == baseline
    assert _git(root, "status", "--porcelain").stdout == ""
