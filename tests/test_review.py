import io
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from obsidian_agent_backend.config import Config, parse_config
from obsidian_agent_backend.daily_note import DailyNote, NoteError
from obsidian_agent_backend.review import (
    PromptInputs,
    ReviewError,
    ReviewOptions,
    WeeklyReview,
    build_prompt,
    changed_paths,
    claude_command,
    load_template,
    report_path,
    validate_report,
)
from obsidian_agent_backend.sources import run
from obsidian_agent_backend.week import IsoWeek

type Git = Callable[..., str]  # the `git` fixture from conftest.py

WEEK = IsoWeek(2026, 45)
TODAY = date(2026, 11, 9)
REPORT = PurePosixPath("Agents/Reports/2026-W45 Weekly review.md")
VALID = '---\ntype: agent\nweek: 2026-W45\nsummary: "busy week"\n---\n# Review\n'

type Agent = Callable[[Sequence[str], Path | None], str]


def make_config(vault: Path, **extra: Any) -> Config:
    return parse_config({"timezone": "America/Lima", **extra}, vault=vault)


# --- pure helpers ----------------------------------------------------------------


def test_report_path(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    assert report_path(config, WEEK, test=False) == REPORT
    assert report_path(config, WEEK, test=True).name == "2026-W45 Weekly review (test).md"


def test_default_template_has_every_placeholder(tmp_path: Path) -> None:
    template = load_template(make_config(tmp_path))
    inputs = PromptInputs(REPORT, WEEK, TODAY, None, "DATA")
    prompt = build_prompt(template, inputs)
    assert "`Agents/Reports/2026-W45 Weekly review.md`" in prompt
    assert "week: 2026-W45\nupdated: 2026-11-09" in prompt
    assert "(2026-11-02 → 2026-11-08)" in prompt
    assert prompt.rstrip().endswith("DATA")
    assert "$" not in prompt.replace("$$", "")
    assert "previous report" not in prompt


def test_prompt_mentions_the_previous_report() -> None:
    previous = PurePosixPath("Agents/Reports/2026-W44 Weekly review.md")
    prompt = build_prompt("$previous_report", PromptInputs(REPORT, WEEK, TODAY, previous, ""))
    assert prompt.startswith(
        "5. For continuity, read the previous report: `Agents/Reports/2026-W44"
    )


def test_custom_template_from_the_vault(tmp_path: Path) -> None:
    (tmp_path / "Agents").mkdir()
    (tmp_path / "Agents/prompt.md").write_text("Write $report_path for $week. $$5", "utf-8")
    config = make_config(tmp_path, review={"prompt": "Agents/prompt.md"})
    prompt = build_prompt(load_template(config), PromptInputs(REPORT, WEEK, TODAY, None, ""))
    assert prompt == "Write Agents/Reports/2026-W45 Weekly review.md for 2026-W45. $5"


def test_missing_custom_template(tmp_path: Path) -> None:
    config = make_config(tmp_path, review={"prompt": "Agents/prompt.md"})
    with pytest.raises(ReviewError, match=r"cannot read the prompt template Agents/prompt\.md"):
        load_template(config)


@pytest.mark.parametrize(
    ("template", "message"),
    [("$unknown", r"unknown placeholder \$unknown"), ("costs $ 5", r"write \$\$ for a literal")],
)
def test_broken_templates(template: str, message: str) -> None:
    with pytest.raises(ReviewError, match=message):
        build_prompt(template, PromptInputs(REPORT, WEEK, TODAY, None, ""))


def test_claude_command_is_least_privilege() -> None:
    cmd = claude_command("PROMPT", REPORT, "sonnet")
    assert cmd[:3] == ["claude", "-p", "PROMPT"]
    allowed = cmd[cmd.index("--allowedTools") + 1 : cmd.index("--disallowedTools")]
    assert allowed == [
        "Read",
        "Glob",
        "Grep",
        "Write(./Agents/Reports/2026-W45 Weekly review.md)",
        "Edit(./Agents/Reports/2026-W45 Weekly review.md)",
    ]
    denied = cmd[cmd.index("--disallowedTools") + 1 :]
    assert {"Bash", "WebFetch", "WebSearch"} <= set(denied)
    assert cmd[cmd.index("--model") + 1] == "sonnet"


def test_changed_paths_parses_porcelain_z() -> None:
    output = "\0".join(
        [" M a b.md", "?? new.md", "R  renamed.md", "old.md", "A  x\ny.md", "!!", ""]
    )

    def runner(cmd: Sequence[str], cwd: Path | None) -> str:
        assert cmd[:4] == ["git", "status", "--porcelain", "-z"]
        return output

    assert changed_paths(Path("/vault"), runner) == {"a b.md", "new.md", "renamed.md", "x\ny.md"}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("---\ntype: note\nweek: 2026-W45\nsummary: x\n---\n", "type: agent and the right week"),
        ("---\ntype: agent\nweek: 2026-W44\nsummary: x\n---\n", "type: agent and the right week"),
        ("---\ntype: agent\nweek: 2026-W45\nsummary: '  '\n---\n", "non-empty summary"),
        ("---\ntype: agent\nweek: 2026-W45\n---\n", "non-empty summary"),
        ("no frontmatter", "type: agent"),
    ],
)
def test_validate_report_rejects_bad_frontmatter(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "r.md"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ReviewError, match=message):
        validate_report(path, WEEK)


def test_validate_report_needs_the_file_and_utf8(tmp_path: Path) -> None:
    with pytest.raises(ReviewError, match=r"did not create r\.md"):
        validate_report(tmp_path / "r.md", WEEK)
    (tmp_path / "r.md").write_bytes(b"\xff")
    with pytest.raises(ReviewError, match="not valid UTF-8"):
        validate_report(tmp_path / "r.md", WEEK)


# --- end to end with a real git repository ---------------------------------------


@pytest.fixture
def vault(tmp_path: Path, git: Git) -> Path:
    root = tmp_path / "vault"
    (root / "Notes").mkdir(parents=True)
    (root / "Notes/a.md").write_text("- [ ] open task\n", encoding="utf-8")
    (root / "Notes/b.md").write_text("tracked\n", encoding="utf-8")
    (root / "Daily").mkdir()
    (root / "Daily/2026-11-03.md").write_text("---\ngithub_commits: 2\n---\n", "utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-qm", "init", when="2026-11-03T10:00:00-05:00")
    return root


def writer(text: str = VALID, extra: dict[str, str] | None = None) -> Agent:
    """A fake agent: writes the report path from the command plus optional extra files."""

    def agent(cmd: Sequence[str], cwd: Path | None) -> str:
        assert cwd is not None
        target = next(arg for arg in cmd if arg.startswith("Write(./"))[len("Write(./") : -1]
        (cwd / target).write_text(text, encoding="utf-8")
        for name, content in (extra or {}).items():
            (cwd / name).write_text(content, encoding="utf-8")
        return ""

    return agent


def make_review(
    vault: Path, agent: Agent, **extra: Any
) -> tuple[WeeklyReview, io.StringIO, io.StringIO]:
    out, err = io.StringIO(), io.StringIO()
    return WeeklyReview(make_config(vault, **extra), run, agent, out, err), out, err


def run_review(review_: WeeklyReview, **options: Any) -> int:
    return review_.run(WEEK, TODAY, ReviewOptions(model="sonnet", **options))


def test_review_writes_logs_and_commits_only_its_files(vault: Path, git: Git) -> None:
    (vault / "Notes/a.md").write_text("- [ ] user edit in progress\n", encoding="utf-8")
    (vault / "Notes/staged.md").write_text("staged by the user\n", encoding="utf-8")
    git(vault, "add", "Notes/staged.md")
    reviewer, out, err = make_review(vault, writer())

    assert run_review(reviewer) == 0

    assert out.getvalue() == (
        f"report written: {REPORT}\nno upstream branch: the commit stays local\n"
    )
    assert err.getvalue() == ""
    log = (vault / "Daily/2026-11-09.md").read_text(encoding="utf-8")
    assert log.endswith("## AI log\n- [oab-review] 2026-W45 → [[2026-W45 Weekly review]]\n")
    committed = git(vault, "show", "--name-only", "--format=%s", "HEAD").split("\n")
    assert committed[0] == "docs: weekly review 2026-W45"
    assert sorted(filter(None, committed[1:])) == [str(REPORT), "Daily/2026-11-09.md"]
    status = git(vault, "status", "--porcelain")
    assert " M Notes/a.md" in status  # user changes stay uncommitted
    assert "A  Notes/staged.md" in status  # and the user's staging is left alone


def test_agent_touching_another_file_is_rejected(vault: Path, git: Git) -> None:
    reviewer, out, err = make_review(vault, writer(extra={"Notes/a.md": "- [x] hijacked\n"}))
    assert run_review(reviewer) == 1
    assert err.getvalue() == (
        "review 2026-W45: the agent changed files outside its report: Notes/a.md\n"
    )
    assert out.getvalue() == ""
    assert git(vault, "log", "--oneline").count("\n") == 1  # nothing committed
    assert not (vault / "Daily/2026-11-09.md").exists()


def test_agent_editing_an_already_dirty_file_is_rejected(vault: Path) -> None:
    (vault / "Notes/a.md").write_text("- [ ] user draft\n", encoding="utf-8")
    reviewer, _, err = make_review(vault, writer(extra={"Notes/a.md": "- [ ] changed\n"}))
    assert run_review(reviewer) == 1
    assert "outside its report: Notes/a.md" in err.getvalue()


def test_agent_creating_an_untracked_file_is_rejected(vault: Path) -> None:
    reviewer, _, err = make_review(vault, writer(extra={"Notes/new.md": "x"}))
    assert run_review(reviewer) == 1
    assert "outside its report: Notes/new.md" in err.getvalue()


def test_already_dirty_files_left_alone_are_fine(vault: Path, git: Git) -> None:
    (vault / "Notes/a.md").write_text("- [ ] user draft\n", encoding="utf-8")
    (vault / "Notes/gone.md").write_text("x", encoding="utf-8")
    (vault / "Notes/b.md").unlink()  # deleted by the user before the run
    reviewer, _, _ = make_review(vault, writer())
    assert run_review(reviewer) == 0


def test_invalid_report_is_rejected(vault: Path) -> None:
    reviewer, _, err = make_review(vault, writer("no frontmatter"))
    assert run_review(reviewer) == 1
    assert "frontmatter must have type: agent" in err.getvalue()


def test_existing_report_is_kept_unless_forced(vault: Path) -> None:
    (vault / "Agents/Reports").mkdir(parents=True)
    (vault / REPORT).write_text(VALID, encoding="utf-8")
    calls: list[int] = []

    def agent(cmd: Sequence[str], cwd: Path | None) -> str:
        calls.append(1)
        return writer()(cmd, cwd)

    reviewer, out, _ = make_review(vault, agent)
    assert run_review(reviewer) == 0
    assert out.getvalue() == "2026-W45 Weekly review.md already exists (use --force to redo it)\n"
    assert calls == []
    assert run_review(reviewer, force=True) == 0
    assert calls == [1]


def test_dry_run_prints_the_prompt_even_if_the_report_exists(vault: Path) -> None:
    (vault / "Agents/Reports").mkdir(parents=True)
    (vault / REPORT).write_text(VALID, encoding="utf-8")
    (vault / "Agents/Reports/2026-W44 Weekly review.md").write_text(VALID, encoding="utf-8")

    def agent(cmd: Sequence[str], cwd: Path | None) -> str:
        raise AssertionError("no model call in a dry run")

    reviewer, out, _ = make_review(vault, agent)
    assert run_review(reviewer, dry_run=True) == 0
    prompt = out.getvalue()
    assert "read the previous report: `Agents/Reports/2026-W44 Weekly review.md`" in prompt
    assert "| [[2026-11-03]] | 2 |" in prompt
    assert "- open task ([[a]])" in prompt


def test_test_run_writes_no_log_and_no_commit(vault: Path, git: Git) -> None:
    reviewer, out, _ = make_review(vault, writer())
    assert run_review(reviewer, test=True) == 0
    assert "(test).md" in out.getvalue()
    assert not (vault / "Daily/2026-11-09.md").exists()
    assert git(vault, "log", "--oneline").count("\n") == 1


def test_nothing_to_commit_is_fine(vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reviewer, out, _ = make_review(vault, writer())
    monkeypatch.setattr(DailyNote, "log", lambda self, day, line: Path())
    calls: list[list[str]] = []

    def no_staged(cmd: Sequence[str], cwd: Path | None) -> str:
        calls.append(list(cmd))
        return "" if cmd[1] == "diff" else run(cmd, cwd)

    reviewer = WeeklyReview(reviewer.config, no_staged, writer(), out, io.StringIO())
    assert run_review(reviewer) == 0
    assert not any(cmd[1] == "commit" for cmd in calls)


def test_pushes_when_there_is_an_upstream(vault: Path, tmp_path: Path, git: Git) -> None:
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(vault, "remote", "add", "origin", str(remote))
    git(vault, "push", "-q", "-u", "origin", "main")
    reviewer, out, _ = make_review(vault, writer())

    assert run_review(reviewer) == 0
    assert out.getvalue() == f"report written: {REPORT}\n"
    assert git(remote, "log", "--format=%s", "-1", "main") == "docs: weekly review 2026-W45\n"


def test_sync_failure_keeps_the_local_commit(vault: Path, tmp_path: Path, git: Git) -> None:
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(vault, "remote", "add", "origin", str(remote))
    git(vault, "push", "-q", "-u", "origin", "main")
    git(vault, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    reviewer, _, err = make_review(vault, writer())

    assert run_review(reviewer) == 1
    assert "committed locally, but could not sync: git exited with code" in err.getvalue()
    assert git(vault, "log", "--format=%s", "-1") == "docs: weekly review 2026-W45\n"


def test_logging_failure_is_reported(
    vault: Path, git: Git, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_log(self: object, day: date, line: str) -> Path:
        raise NoteError("resolves outside the vault")

    monkeypatch.setattr(DailyNote, "log", broken_log)
    reviewer, out, err = make_review(vault, writer())
    assert run_review(reviewer) == 1
    assert out.getvalue() == f"report written: {REPORT}\n"
    assert err.getvalue() == (
        "report written, but logging or committing failed: resolves outside the vault\n"
    )
    assert git(vault, "log", "--oneline").count("\n") == 1


def test_missing_git_repository_is_reported(tmp_path: Path) -> None:
    reviewer, _, err = make_review(tmp_path, writer())
    assert run_review(reviewer) == 1
    assert err.getvalue().startswith("review 2026-W45: git exited with code")
