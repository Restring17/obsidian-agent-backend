"""End-to-end: both commands against a copy of ``examples/vault``.

Git runs for real. ``gh`` and ``claude`` are small scripts placed first on ``PATH``, so the
code goes through its real command runner (``shutil.which`` and ``subprocess``).
"""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from obsidian_agent_backend import cli
from obsidian_agent_backend.daily_note import read_frontmatter

pytestmark = pytest.mark.e2e

type Git = Callable[..., str]  # the `git` fixture from conftest.py

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "vault"
FAKES = Path(__file__).resolve().parent
MADRID = ZoneInfo("Europe/Madrid")
# Commits per batch, dated inside ISO week 2026-W44 (after the switch to +01:00 on Oct 25).
BATCHES = [
    ("2026-10-26T09:00:00+01:00", None),  # everything else
    ("2026-10-27T21:00:00+01:00", ["Notes/Learning Rust.md", "Daily/2026-10-27.md"]),
    ("2026-10-29T22:30:00+01:00", ["Daily/2026-10-29.md", "Career/Applications.md"]),
    ("2026-10-31T23:45:00+01:00", ["Daily/2026-10-31.md"]),  # 22:45 UTC, still Oct 31
]


@pytest.fixture
def fake_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put fake ``gh`` and ``claude`` first on PATH; return the file they log calls to."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("gh", "claude"):
        wrapper = bin_dir / name
        script = FAKES / f"fake_{name}.py"
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', "utf-8")
        wrapper.chmod(0o755)
    log = tmp_path / "calls.jsonl"
    log.touch()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("OAB_FAKE_LOG", str(log))
    return log


def calls(log: Path, program: str) -> list[list[str]]:
    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return [entry[1:] for entry in entries if entry[0] == program]


@pytest.fixture
def vault(tmp_path: Path, git: Git, fake_log: Path) -> Path:
    root = tmp_path / "vault"
    shutil.copytree(EXAMPLE, root)
    git(root, "init", "-q", "-b", "main")
    later = [path for _, paths in BATCHES[1:] for path in paths or []]
    for when, paths in BATCHES:
        if paths is None:
            git(root, "add", "--all", "--", ".", *(f":!{path}" for path in later))
        else:
            git(root, "add", "--", *paths)
        git(root, "commit", "-qm", f"notes {when[:10]}", when=when)
    return root


def config_arg(vault: Path) -> list[str]:
    return ["--config", str(vault / "oab.toml")]


def head(git: Git, vault: Path) -> str:
    return git(vault, "rev-parse", "HEAD").strip()


# --- oab-collect -----------------------------------------------------------------


def test_collect_merges_every_source_into_the_existing_note(
    vault: Path, fake_log: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    now = datetime(2026, 10, 28, 7, 0, tzinfo=MADRID)
    assert cli.collect_main([*config_arg(vault), "--date", "2026-10-27"], now=now) == 0

    text = (vault / "Daily/2026-10-27.md").read_text(encoding="utf-8")
    assert read_frontmatter(text) == {
        "type": "daily",
        "tags": ["daily"],
        "workout_min": None,  # manual habit left as the user wrote it
        "reading_min": 35,
        "github_commits": 3,
        "github_repos": 2,
        "github_prs": 1,
        "vault_commits": 1,
        "vault_notes_edited": 2,
        "tasks_completed": 1,
        "tasks_open": 6,
        "applications_active": 2,
        "collected_at": "2026-10-28T07:00",
    }
    assert text.endswith("## Notes\nRead two chapters of the Rust book. Rest day.\n\n## AI log\n")
    searches = calls(fake_log, "gh")[1:]
    span = "2026-10-27T00:00:00+01:00..2026-10-27T23:59:59+01:00"
    assert f"q=author:example-user committer-date:{span}" in searches[0]
    assert f"q=author:example-user type:pr created:{span}" in searches[1]
    assert "2026-10-27: github_commits=3" in capsys.readouterr().out


def test_collect_creates_a_missing_note_from_the_template(vault: Path) -> None:
    now = datetime(2026, 11, 3, 7, 0, tzinfo=MADRID)
    assert cli.collect_main([*config_arg(vault), "--date", "2026-10-28"], now=now) == 0

    text = (vault / "Daily/2026-10-28.md").read_text(encoding="utf-8")
    data = read_frontmatter(text)
    assert data["github_commits"] == 3
    assert data["vault_commits"] == 0
    assert "tasks_open" not in data  # snapshots are only written for today and yesterday
    assert text.endswith("# 2026-10-28\n\n## Notes\n\n\n## AI log\n")


def test_collect_writes_no_fake_zeros_when_github_fails(
    vault: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OAB_FAKE_GH", "fail")
    now = datetime(2026, 11, 1, 8, 0, tzinfo=MADRID)
    assert cli.collect_main([*config_arg(vault), "--date", "2026-10-31"], now=now) == 1

    data = read_frontmatter((vault / "Daily/2026-10-31.md").read_text(encoding="utf-8"))
    assert not any(key.startswith("github_") for key in data)
    assert data["vault_commits"] == 1  # 23:45 in Madrid is still Oct 31
    assert data["tasks_completed"] == 1
    assert "2026-10-31 GitHub: gh exited with code 4" in capsys.readouterr().err


# --- oab-review ------------------------------------------------------------------


def test_review_writes_logs_and_commits_the_report(
    vault: Path, git: Git, fake_log: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    now = datetime(2026, 11, 2, 9, 30, tzinfo=MADRID)
    assert cli.review_main(config_arg(vault), now=now) == 0

    report = vault / "Agents/Reports/2026-W44 Weekly review.md"
    assert read_frontmatter(report.read_text(encoding="utf-8"))["week"] == "2026-W44"
    log = (vault / "Daily/2026-11-02.md").read_text(encoding="utf-8")
    assert log.rstrip().endswith("- [oab-review] 2026-W44 → [[2026-W44 Weekly review]]")
    committed = git(vault, "show", "--name-only", "--format=%s", "HEAD").split("\n")
    assert committed[0] == "docs: weekly review 2026-W44"
    assert sorted(filter(None, committed[1:])) == [
        "Agents/Reports/2026-W44 Weekly review.md",
        "Daily/2026-11-02.md",
    ]
    assert git(vault, "status", "--porcelain") == ""
    assert "no upstream branch" in capsys.readouterr().out

    [argv] = calls(fake_log, "claude")
    allowed = argv[argv.index("--allowedTools") + 1 : argv.index("--disallowedTools")]
    assert allowed[-2:] == [
        "Write(./Agents/Reports/2026-W44 Weekly review.md)",
        "Edit(./Agents/Reports/2026-W44 Weekly review.md)",
    ]
    assert "Bash" in argv[argv.index("--disallowedTools") + 1 :]


def test_review_prompt_contains_the_week_data(vault: Path, fake_log: Path) -> None:
    now = datetime(2026, 11, 2, 9, 30, tzinfo=MADRID)
    assert cli.review_main(config_arg(vault), now=now) == 0
    prompt = calls(fake_log, "claude")[0][1]

    assert "| [[2026-10-26]] | — | — | — | — | — | — | 45 | 20 |" in prompt
    assert "| **Total** | — | — | — | — | — | — | 135 | 70 |" in prompt
    assert "- 2026-10-29: [Claude Code] Applications: updated Northwind" in prompt
    assert "## Vault commits (4)" in prompt
    assert "- Redis implementation of the cache ([[Weather API]])" in prompt
    assert "private task" not in prompt
    assert "[status:: interview]" in prompt
    assert "- [[Weather API]]: active" in prompt
    assert "read the previous report: `Agents/Reports/2026-W43 Weekly review.md`" in prompt


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("evil", "the agent changed files outside its report: Projects/Weather API.md"),
        ("invalid", "the report frontmatter must have type: agent"),
    ],
)
def test_review_rejects_a_misbehaving_agent(
    vault: Path,
    git: Git,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    message: str,
) -> None:
    monkeypatch.setenv("OAB_FAKE_CLAUDE", mode)
    before = head(git, vault)
    now = datetime(2026, 11, 2, 9, 30, tzinfo=MADRID)

    assert cli.review_main(config_arg(vault), now=now) == 1

    assert message in capsys.readouterr().err
    assert head(git, vault) == before  # nothing committed
    assert not (vault / "Daily/2026-11-02.md").exists()  # nothing logged


# --- installed console scripts -----------------------------------------------------


@pytest.mark.parametrize(
    ("command", "args", "expected"),
    [
        ("oab-collect", ["--no-github", "--date", "2026-10-27", "--dry-run"], "(dry run)"),
        ("oab-review", ["--week", "2026-W44", "--dry-run"], "# Data for week 2026-W44"),
    ],
)
def test_console_scripts(vault: Path, command: str, args: list[str], expected: str) -> None:
    script = Path(sys.executable).parent / command
    result = subprocess.run(  # noqa: S603
        [str(script), *config_arg(vault), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout
