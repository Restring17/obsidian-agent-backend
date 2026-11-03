from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from obsidian_agent_backend import weekly_context
from obsidian_agent_backend.config import Config, parse_config
from obsidian_agent_backend.domain import SourceError
from obsidian_agent_backend.week import IsoWeek
from obsidian_agent_backend.weekly_context import WeeklyContext, is_number

WEEK = IsoWeek(2026, 45)  # 2026-11-02 .. 2026-11-08


class FakeRunner:
    def __init__(self, output: str = "") -> None:
        self.output = output
        self.calls: list[tuple[list[str], Path | None]] = []

    def __call__(self, cmd: Sequence[str], cwd: Path | None) -> str:
        self.calls.append((list(cmd), cwd))
        return self.output


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_config(vault: Path, **extra: Any) -> Config:
    data: dict[str, Any] = {
        "timezone": "America/Lima",
        "human_zone": {"folders": ["[0-7]0 *"], "exclude": ["Templates"]},
        "agent": {"folder": "90 Agents"},
        "daily_notes": {"folder": "00 Home/Daily"},
        "metrics": {"manual": ["gym_min"]},
        **extra,
    }
    return parse_config(data, vault=vault)


def section(text: str, title: str) -> str:
    start = text.index(f"## {title}")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


@pytest.mark.parametrize(
    ("value", "expected"), [(1, True), (1.5, True), (True, False), ("1", False)]
)
def test_is_number(value: object, expected: bool) -> None:
    assert is_number(value) is expected


def test_daily_metrics_table_totals_and_log(tmp_path: Path) -> None:
    write(
        tmp_path / "00 Home/Daily/2026-11-02.md",
        "---\ngithub_commits: 3\ngym_min: 60\nvault_commits: x\ntasks_completed: true\n---\n"
        "## AI log\n- did A\n",
    )
    write(tmp_path / "00 Home/Daily/2026-11-04.md", "---\ngithub_commits: 2\ngym_min: 30.5\n---\n")
    write(tmp_path / "00 Home/Daily/2026-11-09.md", "---\ngithub_commits: 99\n---\n")  # next week

    text = WeeklyContext(make_config(tmp_path), FakeRunner()).build(WEEK)
    lines = section(text, "Metrics per day").splitlines()

    columns = 7  # 3 GitHub + 3 vault + 1 manual
    assert lines[1] == (
        "| Day | github_commits | github_repos | github_prs | vault_commits | "
        "vault_notes_edited | tasks_completed | gym_min |"
    )
    assert lines[2] == "|" + "---|" * (columns + 1)
    assert lines[3] == "| [[2026-11-02]] | 3 | — | — | — | — | — | 60 |"
    assert lines[4] == "| 2026-11-03 | — | — | — | — | — | — | — |"
    assert lines[5] == "| [[2026-11-04]] | 2 | — | — | — | — | — | 30.5 |"
    assert "| **Total** | 5 | — | — | — | — | — | 90.5 |" in lines
    assert section(text, "AI log of the week").splitlines()[1:] == ["- 2026-11-02: did A"]


def test_empty_week(tmp_path: Path) -> None:
    text = WeeklyContext(make_config(tmp_path), FakeRunner()).build(WEEK)
    assert text.startswith("# Data for week 2026-W45 (2026-11-02 to 2026-11-08)")
    assert "## AI log of the week\n(empty)" in text
    assert "## Vault commits (0)\n(none)" in text
    assert "## Open tasks (0)\n(none)" in text
    assert "## Applications" not in text
    assert "## Projects" not in text


def test_commits_use_the_week_bounds_and_are_capped(tmp_path: Path) -> None:
    output = "".join(f"abc{i} 2026-11-02 commit {i}\n" for i in range(105)) + "\n"
    runner = FakeRunner(output)
    text = WeeklyContext(make_config(tmp_path), runner).build(WEEK)

    cmd, cwd = runner.calls[0]
    assert cwd == tmp_path
    assert cmd[2:4] == ["--since=2026-11-02T00:00:00-05:00", "--until=2026-11-08T23:59:59-05:00"]
    commits = section(text, "Vault commits (105)")
    assert "- abc0 2026-11-02 commit 0" in commits
    assert "- abc99 " in commits
    assert "abc100" not in commits
    assert commits.rstrip().endswith("(+5 more)")


def test_open_tasks_skip_private_excluded_and_agent_notes(tmp_path: Path) -> None:
    write(tmp_path / "10 Notes/a.md", "- [ ] first\n- [x] done\n* [ ]  second  \n- [ ]nospace\n")
    write(tmp_path / "10 Notes/secret.md", "---\nprivate: true\n---\n- [ ] hidden\n")
    write(tmp_path / "10 Notes/quoted.md", '---\nprivate: "true"\n---\n- [ ] string is not true\n')
    write(tmp_path / "10 Notes/Templates/t.md", "- [ ] placeholder\n")
    write(tmp_path / "90 Agents/r.md", "- [ ] agent\n")
    text = WeeklyContext(make_config(tmp_path), FakeRunner()).build(WEEK)
    assert section(text, "Open tasks").splitlines() == [
        "## Open tasks (3)",
        "- first ([[a]])",
        "- second ([[a]])",
        "- string is not true ([[quoted]])",
    ]


def test_open_tasks_are_capped(tmp_path: Path) -> None:
    write(tmp_path / "10 Notes/a.md", "".join(f"- [ ] task {i}\n" for i in range(45)))
    tasks = section(WeeklyContext(make_config(tmp_path), FakeRunner()).build(WEEK), "Open tasks")
    assert tasks.splitlines()[0] == "## Open tasks (45)"
    assert "- task 39 ([[a]])" in tasks
    assert "task 40" not in tasks
    assert tasks.rstrip().endswith("(+5 more)")


def test_private_field_is_configurable(tmp_path: Path) -> None:
    write(tmp_path / "10 Notes/secret.md", "---\nprivado: true\n---\n- [ ] hidden\n")
    config = make_config(tmp_path, human_zone={"folders": ["*"], "private_field": "privado"})
    assert "## Open tasks (0)" in WeeklyContext(config, FakeRunner()).build(WEEK)


def test_applications_list_every_item_with_the_field(tmp_path: Path) -> None:
    write(
        tmp_path / "40 Career/Apps.md",
        "- Acme [status:: applied]\n* Beta [status:: rejected]\nGamma [status:: applied]\n"
        "- Delta [stage:: x]\n",
    )
    config = make_config(tmp_path, applications={"note": "40 Career/Apps.md"})
    text = WeeklyContext(config, FakeRunner()).build(WEEK)
    assert section(text, "Applications").splitlines() == [
        "## Applications",
        "- Acme [status:: applied]",
        "- Beta [status:: rejected]",
    ]


@pytest.mark.parametrize("frontmatter", ["", "---\nprivate: true\n---\n"])
def test_missing_or_private_applications_note(tmp_path: Path, frontmatter: str) -> None:
    if frontmatter:
        write(tmp_path / "40 Career/Apps.md", frontmatter + "- Acme [status:: applied]\n")
    config = make_config(tmp_path, applications={"note": "40 Career/Apps.md"})
    assert "## Applications\n(none)" in WeeklyContext(config, FakeRunner()).build(WEEK)


def test_projects_with_status(tmp_path: Path) -> None:
    write(tmp_path / "20 Projects/Alpha.md", "---\nstatus: active\n---\n")
    write(tmp_path / "20 Projects/sub/Beta.md", "---\nstatus: idea\n---\n")
    write(tmp_path / "20 Projects/Index.md", "# no status\n")
    write(tmp_path / "10 Notes/Other.md", "---\nstatus: active\n---\n")
    config = make_config(tmp_path, projects={"folder": "20 Projects"})
    text = WeeklyContext(config, FakeRunner()).build(WEEK)
    assert section(text, "Projects").splitlines() == [
        "## Projects",
        "- [[Alpha]]: active",
        "- [[Beta]]: idea",
    ]


def test_projects_section_without_projects(tmp_path: Path) -> None:
    config = make_config(tmp_path, projects={"folder": "20 Projects"})
    assert "## Projects\n(none)" in WeeklyContext(config, FakeRunner()).build(WEEK)


def test_unreadable_note_is_a_source_error(tmp_path: Path) -> None:
    (tmp_path / "10 Notes").mkdir()
    (tmp_path / "10 Notes/bad.md").write_bytes(b"\xff")
    with pytest.raises(SourceError, match=r"cannot read bad\.md: UnicodeDecodeError"):
        WeeklyContext(make_config(tmp_path), FakeRunner()).build(WEEK)


def test_symlinked_daily_folder_is_a_source_error(tmp_path: Path) -> None:
    vault, outside = tmp_path / "vault", tmp_path / "outside"
    (vault / "00 Home").mkdir(parents=True)
    outside.mkdir()
    (vault / "00 Home/Daily").symlink_to(outside)
    with pytest.raises(SourceError, match="outside the vault"):
        WeeklyContext(make_config(vault), FakeRunner()).build(WEEK)


def test_log_heading_is_configurable(tmp_path: Path) -> None:
    write(tmp_path / "00 Home/Daily/2026-11-03.md", "## Registro IA\n- hecho\n")
    config = make_config(
        tmp_path, daily_notes={"folder": "00 Home/Daily", "log_heading": "Registro IA"}
    )
    text = WeeklyContext(config, FakeRunner()).build(WEEK)
    assert "## Registro IA of the week\n- 2026-11-03: hecho" in text


def test_metric_keys_follow_the_config(tmp_path: Path) -> None:
    context = WeeklyContext(make_config(tmp_path, metrics={"manual": []}), FakeRunner())
    assert context.metric_keys[-1] == "tasks_completed"
    assert weekly_context.NO_DATA == "—"
