from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from obsidian_agent_backend.domain import SourceError
from obsidian_agent_backend.exact_commit import (
    commit_exact,
    has_staged_changes,
    head_text,
    index_text,
    stage,
    write_blob,
)
from obsidian_agent_backend.sources import run

type Git = Callable[..., str]  # the `git` fixture from conftest.py


@pytest.fixture
def repo(tmp_path: Path, git: Git) -> Path:
    root = tmp_path / "repo"
    (root / "Daily").mkdir(parents=True)
    (root / "Daily/n.md").write_text("one\n", encoding="utf-8")
    (root / "other.md").write_text("other\n", encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-qm", "init")
    return root


def test_head_and_index_text(repo: Path, git: Git) -> None:
    assert head_text(repo, run, "Daily/n.md") == "one\n"
    assert head_text(repo, run, "Daily/new.md") is None
    (repo / "Daily/new.md").write_text("staged\n", encoding="utf-8")
    git(repo, "add", "Daily/new.md")
    assert index_text(repo, run, "Daily/new.md") == "staged\n"
    assert index_text(repo, run, "Daily/missing.md") is None
    assert has_staged_changes(repo, run, "Daily/new.md")
    assert not has_staged_changes(repo, run, "Daily/n.md")


def test_paths_starting_with_a_dash_are_not_options(repo: Path, git: Git) -> None:
    (repo / "-dash.md").write_text("dash\n", encoding="utf-8")
    git(repo, "add", "--", "-dash.md")
    assert index_text(repo, run, "-dash.md") == "dash\n"
    git(repo, "commit", "-qm", "dash")
    assert head_text(repo, run, "-dash.md") == "dash\n"


def test_write_blob_keeps_the_text_byte_for_byte(repo: Path, git: Git) -> None:
    blob = write_blob(repo, run, "Daily/n.md", "a\r\nb  \n\n")
    assert git(repo, "cat-file", "-p", blob) == "a\nb  \n\n"  # text=True reads CRLF as LF
    raw = git(repo, "cat-file", "-s", blob)
    assert raw == "8\n"  # the CR is stored


def test_commit_exact_commits_only_the_blobs(repo: Path, git: Git) -> None:
    (repo / "Daily/n.md").write_text("one\nuser edit\n", encoding="utf-8")
    (repo / "other.md").write_text("staged by the user\n", encoding="utf-8")
    git(repo, "add", "other.md")
    blob = write_blob(repo, run, "Daily/n.md", "one\ntool\n")
    before = git(repo, "rev-parse", "HEAD")

    assert commit_exact(repo, run, {"Daily/n.md": blob}, "docs: subject\n\nbody")

    assert git(repo, "rev-parse", "HEAD~1") == before
    assert git(repo, "log", "-1", "--format=%B") == "docs: subject\n\nbody\n\n"
    assert git(repo, "show", "--name-only", "--format=", "HEAD") == "Daily/n.md\n"
    assert git(repo, "show", "HEAD:Daily/n.md") == "one\ntool\n"
    assert (repo / "Daily/n.md").read_text(encoding="utf-8") == "one\nuser edit\n"
    assert git(repo, "show", ":Daily/n.md") == "one\n"  # the index is the caller's job
    assert git(repo, "show", ":other.md") == "staged by the user\n"
    assert "commit: docs: subject" in git(repo, "reflog", "-1")
    stage(repo, run, "Daily/n.md", blob)
    assert git(repo, "status", "--porcelain") == " M Daily/n.md\nM  other.md\n"


def test_commit_exact_adds_new_files(repo: Path, git: Git) -> None:
    blob = write_blob(repo, run, "Daily/new.md", "new\n")
    assert commit_exact(repo, run, {"Daily/new.md": blob}, "docs: new")
    assert git(repo, "show", "HEAD:Daily/new.md") == "new\n"
    assert not (repo / "Daily/new.md").exists()


def test_commit_exact_without_changes_does_nothing(repo: Path, git: Git) -> None:
    before = git(repo, "rev-parse", "HEAD")
    blob = write_blob(repo, run, "Daily/n.md", "one\n")
    assert not commit_exact(repo, run, {"Daily/n.md": blob}, "docs: same")
    assert git(repo, "rev-parse", "HEAD") == before


def test_commit_exact_never_overwrites_a_concurrent_commit(repo: Path, git: Git) -> None:
    blob = write_blob(repo, run, "Daily/n.md", "tool\n")

    def racing(cmd: Sequence[str], cwd: Path | None) -> str:
        if cmd[:2] == ["git", "update-ref"]:  # someone commits in between
            git(repo, "commit", "-q", "--allow-empty", "-m", "user commit")
        return run(cmd, cwd)

    with pytest.raises(SourceError, match="git exited with code"):
        commit_exact(repo, racing, {"Daily/n.md": blob}, "docs: race")
    assert git(repo, "log", "-1", "--format=%s") == "user commit\n"
