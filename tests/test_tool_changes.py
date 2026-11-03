from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from obsidian_agent_backend.config import parse_config
from obsidian_agent_backend.sources import run
from obsidian_agent_backend.tool_changes import Change, daily_note_changes

type Git = Callable[..., str]  # the `git` fixture from conftest.py

TODAY = date(2026, 11, 9)
LINE = "- [oab-review] done"


@pytest.fixture
def vault(tmp_path: Path, git: Git) -> Path:
    root = tmp_path / "vault"
    (root / "Daily").mkdir(parents=True)
    (root / "Daily/2026-11-03.md").write_text("---\ngithub_commits: 2\n---\nBody\n", "utf-8")
    (root / "Templates").mkdir()
    (root / "Templates/Daily.md").write_text("---\ndate: {{date}}\n---\n", "utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-qm", "init")
    return root


def changes(vault: Path, **daily_notes: str) -> tuple[dict[str, str], list[str]]:
    config = parse_config(
        {"timezone": "America/Lima", "daily_notes": {"folder": "Daily", **daily_notes}},
        vault=vault,
    )
    found = daily_note_changes(config, run, TODAY, LINE)
    return {path: change.text for path, change in found.changes.items()}, found.skipped


def test_change_redoes_its_edit_on_any_version() -> None:
    change = Change("a", lambda text: text + "!")
    assert change.text == "a!"
    assert change.redo("b") == "b!"


def test_today_gets_the_log_line_on_top_of_the_template(vault: Path) -> None:
    (vault / "Daily/2026-11-09.md").write_text("user only\n", encoding="utf-8")
    found, skipped = changes(vault, template="Templates/Daily.md")
    assert found == {"Daily/2026-11-09.md": f"---\ndate: 2026-11-09\n---\n\n## AI log\n{LINE}\n"}
    assert skipped == []


def test_collector_keys_keep_their_order_and_the_rest_stays_out(vault: Path) -> None:
    (vault / "Daily/2026-11-03.md").write_text(
        "---\nmood: x\ngithub_commits: 4\ntasks_open: 1\n---\nBody\nMore\n", "utf-8"
    )
    found, _ = changes(vault)
    assert found["Daily/2026-11-03.md"] == "---\ngithub_commits: 4\ntasks_open: 1\n---\nBody\n"


@pytest.mark.parametrize(
    "path",
    [
        "Daily/notes.md",  # not a dated note
        "Daily/2026-13-40.md",  # not a date
        "Daily/sub/2026-11-04.md",  # not directly in the folder
        "Other/2026-11-04.md",
    ],
)
def test_only_dated_notes_in_the_folder_count(vault: Path, path: str) -> None:
    (vault / path).parent.mkdir(parents=True, exist_ok=True)
    (vault / path).write_text("---\ngithub_commits: 9\n---\n", encoding="utf-8")
    assert list(changes(vault)[0]) == []  # today's note does not exist: nothing at all


def test_user_only_edits_and_unchanged_keys_are_not_commits(vault: Path) -> None:
    (vault / "Daily/2026-11-03.md").write_text("---\ngithub_commits: 2\n---\nEdited\n", "utf-8")
    (vault / "Daily/2026-11-04.md").write_text("---\nworkout_min: 30\n---\n", "utf-8")
    assert changes(vault) == ({}, [])


def test_deleted_notes_are_ignored(vault: Path) -> None:
    (vault / "Daily/2026-11-03.md").unlink()
    assert changes(vault) == ({}, [])


def test_unreadable_notes_are_skipped(vault: Path) -> None:
    (vault / "Daily/2026-11-03.md").write_bytes(b"---\ngithub_commits: 3\n---\n\xff\n")
    (vault / "Daily/2026-11-04.md").write_text("---\ngithub_commits: 3\n---\n", "utf-8")
    found, skipped = changes(vault, template="Templates/Missing.md")
    assert found == {}
    assert skipped == ["Daily/2026-11-03.md", "Daily/2026-11-04.md"]
