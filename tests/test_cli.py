import argparse
from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from obsidian_agent_backend import __version__, cli
from obsidian_agent_backend.domain import Metrics

type Git = Callable[..., str]  # the `git` fixture from conftest.py

EntryPoint = Callable[[list[str] | None], int]

COMMANDS: list[tuple[str, EntryPoint]] = [
    ("oab-collect", cli.collect_main),
    ("oab-review", cli.review_main),
]
LIMA = ZoneInfo("America/Lima")
NOW = datetime(2026, 11, 3, 6, 30, tzinfo=LIMA)
CONFIG = """
timezone = "America/Lima"
[human_zone]
folders = ["[0-7]0 *"]
[agent]
folder = "90 Agents"
"""


# --- shared behaviour ------------------------------------------------------------


@pytest.mark.parametrize(("prog", "entry"), COMMANDS)
def test_default_config_is_read_from_working_directory(
    prog: str,
    entry: EntryPoint,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    assert entry([]) == cli.EXIT_CONFIG_ERROR
    assert capsys.readouterr().err == f"{prog}: error: config file not found: oab.toml\n"


@pytest.mark.parametrize(("prog", "entry"), COMMANDS)
def test_invalid_config_fails_fast_with_exit_code_2(
    prog: str, entry: EntryPoint, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "oab.toml"
    config.write_text('timezone = "Mars/Olympus"\n', encoding="utf-8")
    assert entry(["--config", str(config)]) == 2
    err = capsys.readouterr().err
    assert err == f"{prog}: error: {config}: timezone: unknown IANA timezone 'Mars/Olympus'\n"
    assert "Traceback" not in err


@pytest.mark.parametrize(("prog", "entry"), COMMANDS)
def test_version_flag_prints_version(
    prog: str, entry: EntryPoint, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        entry(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out == f"{prog} {__version__}\n"


@pytest.mark.parametrize(("prog", "entry"), COMMANDS)
def test_unknown_argument_is_rejected(
    prog: str, entry: EntryPoint, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        entry(["--bogus"])
    assert exc.value.code == 2
    assert prog in capsys.readouterr().err


def test_version_is_a_non_empty_string() -> None:
    assert isinstance(__version__, str)
    assert __version__


def test_review_dry_run_prints_the_prompt_for_last_week(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_agent(cmd: Sequence[str], cwd: Path | None) -> str:
        raise AssertionError("the model must not be called in a dry run")

    args = ["--config", str(vault / "oab.toml"), "--dry-run"]
    assert cli.review_main(args, now=NOW, agent_runner=no_agent) == 0
    out = capsys.readouterr().out
    assert "`90 Agents/Reports/2026-W44 Weekly review.md`" in out
    assert "# Data for week 2026-W44 (2026-10-26 to 2026-11-01)" in out


def test_review_with_week_and_model(vault: Path) -> None:
    seen: list[list[str]] = []

    def agent(cmd: Sequence[str], cwd: Path | None) -> str:
        seen.append(list(cmd))
        return ""

    args = ["--config", str(vault / "oab.toml"), "--week", "2026-W45", "--model", "opus"]
    assert cli.review_main(args, now=NOW, agent_runner=agent) == 1  # no report was written
    assert seen[0][seen[0].index("--model") + 1] == "opus"
    assert "`90 Agents/Reports/2026-W45 Weekly review.md`" in seen[0][2]


def test_review_rejects_future_weeks(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["--config", str(vault / "oab.toml"), "--week", "2026-W46"]
    assert cli.review_main(args, now=NOW) == cli.EXIT_CONFIG_ERROR
    assert "week 2026-W46 has not started yet" in capsys.readouterr().err


@pytest.mark.parametrize("args", [["--week", "2026-45"], ["--model", "a b"]])
def test_review_rejects_invalid_arguments(
    args: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.review_main(args)
    assert exc.value.code == 2
    assert "oab-review: error: argument" in capsys.readouterr().err


def test_agent_runner_uses_the_long_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(cmd: Sequence[str], cwd: Path | None = None, timeout: float = 0) -> str:
        seen.update(cmd=list(cmd), timeout=timeout)
        return "ok"

    monkeypatch.setattr(cli, "run", fake_run)
    assert cli._agent_runner(["claude"], None) == "ok"
    assert seen == {"cmd": ["claude"], "timeout": 15 * 60}


# --- argument validation ---------------------------------------------------------


@pytest.mark.parametrize("text", ["2026-11-02", "2024-02-29"])
def test_iso_date_accepts_calendar_dates(text: str) -> None:
    assert cli.iso_date(text) == date.fromisoformat(text)


@pytest.mark.parametrize("text", ["20261102", "2026-13-01", "2025-02-29", "yesterday", ""])
def test_iso_date_rejects_other_forms(text: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="use YYYY-MM-DD"):
        cli.iso_date(text)


@pytest.mark.parametrize(("text", "days"), [("1", 1), ("31", 31)])
def test_day_count_accepts_the_range(text: str, days: int) -> None:
    assert cli.day_count(text) == days


@pytest.mark.parametrize("text", ["0", "32", "-1", "+3", "1.5", "x", "", "٣"])
def test_day_count_rejects_values_outside_the_range(text: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="between 1 and 31"):
        cli.day_count(text)


@pytest.mark.parametrize("args", [["--date", "2026/11/02"], ["--days", "40"]])
def test_collect_rejects_invalid_arguments(
    args: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.collect_main(args)
    assert exc.value.code == 2
    assert "oab-collect: error: argument" in capsys.readouterr().err


def test_collect_rejects_future_dates(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "oab.toml"
    config.write_text(CONFIG, encoding="utf-8")
    code = cli.collect_main(["--config", str(config), "--date", "2026-11-04"], now=NOW)
    assert code == cli.EXIT_CONFIG_ERROR
    assert "cannot be in the future (2026-11-04 > 2026-11-03)" in capsys.readouterr().err


# --- end to end with a real git repository ---------------------------------------


@pytest.fixture
def vault(tmp_path: Path, git: Git) -> Path:
    (tmp_path / "oab.toml").write_text(CONFIG, encoding="utf-8")
    notes = tmp_path / "10 Notes"
    notes.mkdir()
    (notes / "a.md").write_text("- [ ] open\n- [x] done ✅ 2026-11-02\n", encoding="utf-8")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", ".")
    # 23:30 in Lima is already 2026-11-03 in UTC: the day must follow the vault timezone.
    git(tmp_path, "commit", "-qm", "notes", when="2026-11-02T23:30:00-05:00")
    return tmp_path


def test_collect_writes_the_daily_note(vault: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.collect_main(["--config", str(vault / "oab.toml"), "--no-github"], now=NOW)

    assert code == 0
    note = (vault / "Daily/2026-11-02.md").read_text(encoding="utf-8")
    assert note == (
        "---\nvault_commits: 1\nvault_notes_edited: 1\ntasks_completed: 1\ntasks_open: 1\n"
        'applications_active: 0\ncollected_at: "2026-11-03T06:30"\n---\n'
    )
    assert "2026-11-02: vault_commits=1" in capsys.readouterr().out


def test_collect_several_days_skips_days_without_activity(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["--config", str(vault / "oab.toml"), "--no-github", "--days", "3", "--dry-run"]
    assert cli.collect_main(args, now=NOW) == 0
    assert capsys.readouterr().out.splitlines() == [
        "2026-11-02 (dry run): vault_commits=1, vault_notes_edited=1, tasks_completed=1, "
        "tasks_open=1, applications_active=0",
        "2026-11-01: no activity, no note created",
        "2026-10-31: no activity, no note created",
    ]
    assert not (vault / "Daily").exists()


def test_collect_uses_github_unless_disabled(
    vault: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeGitHub:
        def __init__(self, tz: ZoneInfo) -> None:
            assert tz.key == "America/Lima"

        def collect(self, day: date) -> Metrics:
            return Metrics({"github_commits": 7})

    monkeypatch.setattr(cli, "GitHubSource", FakeGitHub)
    args = ["--config", str(vault / "oab.toml"), "--date", "2026-11-02", "--dry-run"]
    assert cli.collect_main(args, now=NOW) == 0
    assert "github_commits=7" in capsys.readouterr().out


def test_collect_outside_a_git_repository_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "oab.toml").write_text(CONFIG, encoding="utf-8")
    code = cli.collect_main(["--config", str(tmp_path / "oab.toml"), "--no-github"], now=NOW)
    assert code == 1
    assert "vault: git exited with code 128" in capsys.readouterr().err
    assert not (tmp_path / "Daily").exists()


def test_collect_defaults_to_the_current_time(
    vault: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["--config", str(vault / "oab.toml"), "--no-github", "--dry-run"]
    assert cli.collect_main(args) == 0
    yesterday = datetime.now(LIMA).date().toordinal() - 1
    [line] = capsys.readouterr().out.splitlines()
    assert line.startswith(date.fromordinal(yesterday).isoformat())
