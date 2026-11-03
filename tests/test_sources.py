import json
import subprocess
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from obsidian_agent_backend import sources
from obsidian_agent_backend.config import Config, parse_config
from obsidian_agent_backend.domain import SourceError
from obsidian_agent_backend.sources import GitHubSource, VaultSource, day_bounds, run

DAY = date(2026, 11, 2)
LIMA = ZoneInfo("America/Lima")


class FakeRunner:
    """Returns queued outputs in order and records every command."""

    def __init__(self, *outputs: str) -> None:
        self.outputs = list(outputs)
        self.calls: list[tuple[list[str], Path | None]] = []

    def __call__(self, cmd: Sequence[str], cwd: Path | None) -> str:
        self.calls.append((list(cmd), cwd))
        return self.outputs.pop(0)


def page(total: int, items: list[Any]) -> str:
    return json.dumps({"total_count": total, "items": items})


def commit(repo: str) -> dict[str, Any]:
    return {"repository": {"full_name": repo}}


# --- run -------------------------------------------------------------------------


def test_run_returns_stdout(tmp_path: Path) -> None:
    assert run(["pwd"], tmp_path).strip() == str(tmp_path)


def test_run_reports_exit_code() -> None:
    with pytest.raises(SourceError, match="false exited with code 1"):
        run(["false"])


def test_run_reports_missing_command() -> None:
    with pytest.raises(SourceError, match="command not found: oab-no-such-binary"):
        run(["oab-no-such-binary"])


def test_run_reports_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired("gh", 60)

    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(SourceError, match="true failed: TimeoutExpired"):
        run(["true"])


def test_run_kills_a_command_that_exceeds_the_timeout() -> None:
    with pytest.raises(SourceError, match="failed: TimeoutExpired"):
        run([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.2)


def test_run_never_uses_a_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs, args=args)
        return subprocess.CompletedProcess(args, 0, stdout="ok")

    monkeypatch.setattr(subprocess, "run", fake)
    assert run(["git", "status; rm -rf /"]) == "ok"
    assert seen["args"][1] == "status; rm -rf /"
    assert seen["args"][0].endswith("/git")
    assert "shell" not in seen


# --- day bounds ------------------------------------------------------------------


def test_day_bounds_use_the_timezone_offset() -> None:
    assert day_bounds(DAY, LIMA) == ("2026-11-02T00:00:00-05:00", "2026-11-02T23:59:59-05:00")


def test_day_bounds_follow_daylight_saving_time() -> None:
    madrid = ZoneInfo("Europe/Madrid")
    assert day_bounds(date(2026, 7, 1), madrid)[0].endswith("+02:00")
    assert day_bounds(date(2026, 12, 1), madrid)[0].endswith("+01:00")


# --- GitHub ----------------------------------------------------------------------


def test_github_collects_and_builds_queries() -> None:
    runner = FakeRunner(
        "octo-cat\n",
        page(3, [commit("o/a"), commit("o/b"), commit("o/a")]),
        page(2, [{}, {}]),
    )
    metrics = GitHubSource(LIMA, runner).collect(DAY)

    assert dict(metrics.values) == {"github_commits": 3, "github_repos": 2, "github_prs": 2}
    span = "2026-11-02T00:00:00-05:00..2026-11-02T23:59:59-05:00"
    assert runner.calls[0] == (["gh", "api", "user", "--jq", ".login"], None)
    assert runner.calls[1][0] == [
        "gh", "api", "-X", "GET", "search/commits",
        "-f", f"q=author:octo-cat committer-date:{span}",
        "-f", "per_page=100", "-f", "page=1",
    ]  # fmt: skip
    assert f"q=author:octo-cat type:pr created:{span}" in runner.calls[2][0]


def test_github_login_is_fetched_once() -> None:
    runner = FakeRunner("me", page(0, []), page(0, []), page(0, []), page(0, []))
    source = GitHubSource(LIMA, runner)
    source.collect(DAY)
    source.collect(DAY)
    assert sum(call[0][2] == "user" for call in runner.calls) == 1


def test_github_paginates_until_the_total() -> None:
    runner = FakeRunner(page(150, [commit("o/a")] * 100), page(150, [commit("o/b")] * 50))
    total, items = GitHubSource(LIMA, runner, login="me")._search("search/commits", "q")
    assert (total, len(items)) == (150, 150)
    assert runner.calls[1][0][-1] == "page=2"


def test_github_stops_on_an_empty_page() -> None:
    runner = FakeRunner(page(500, [commit("o/a")]), page(500, []))
    total, items = GitHubSource(LIMA, runner, login="me")._search("search/commits", "q")
    assert (total, len(items), len(runner.calls)) == (500, 1, 2)


def test_github_respects_the_page_limit() -> None:
    runner = FakeRunner(*[page(5000, [commit("o/a")] * 100)] * sources.MAX_PAGES)
    _, items = GitHubSource(LIMA, runner, login="me")._search("search/commits", "q")
    assert len(items) == 1000
    assert len(runner.calls) == sources.MAX_PAGES


@pytest.mark.parametrize("login", ["", "-me", "a b", "me;rm", "x" * 40, "me\n--jq"])
def test_github_rejects_invalid_logins(login: str) -> None:
    with pytest.raises(SourceError, match=r"^invalid GitHub login$"):
        GitHubSource(LIMA, FakeRunner(), login=login).collect(DAY)


@pytest.mark.parametrize("output", ["not json", "{}", '{"total_count": "x", "items": []}', "[]"])
def test_github_unexpected_response(output: str) -> None:
    with pytest.raises(SourceError, match="unexpected response from search/commits"):
        GitHubSource(LIMA, FakeRunner(output), login="me").collect(DAY)


def test_github_commit_without_repository() -> None:
    runner = FakeRunner(page(1, [{}]), page(0, []))
    with pytest.raises(SourceError, match=r"^commit without repository in the response$"):
        GitHubSource(LIMA, runner, login="me").collect(DAY)


# --- vault -----------------------------------------------------------------------


def vault_config(vault: Path, **extra: Any) -> Config:
    data: dict[str, Any] = {
        "timezone": "America/Lima",
        "human_zone": {"folders": ["[0-7]0 *"], "exclude": ["Templates"]},
        "agent": {"folder": "90 Agents"},
        **extra,
    }
    return parse_config(data, vault=vault)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    write(
        tmp_path / "10 Notes/a.md",
        "- [ ] open\n* [ ] open too\n- [x] done ✅ 2026-11-02\n- [X] done ✅2026-11-02\n"
        "- [x] other day ✅ 2026-11-01\n  - [ ] nested open\n",
    )
    write(tmp_path / "20 Projects/deep/b.md", "+ [ ] open\n- [ ]missing space\n")
    write(tmp_path / "10 Notes/Templates/t.md", "- [ ] template placeholder\n")
    write(tmp_path / "80 Archive/old.md", "- [ ] outside the human zone\n")
    write(tmp_path / "90 Agents/report.md", "- [ ] agent task\n- [x] ✅ 2026-11-02\n")
    write(tmp_path / ".obsidian/x.md", "- [ ] hidden\n")
    write(tmp_path / "root.md", "- [ ] at the root\n")
    write(
        tmp_path / "40 Career/Applications.md",
        "- Acme [status:: applied]\n- Beta [status::Interview ]\n- Gamma [status:: rejected]\n"
        "- Delta [stage:: applied]\n",
    )
    return tmp_path


GIT_LOG = "@abc\n10 Notes/a.md\nimage.png\n\n@def\n10 Notes/a.md\n20 Projects/deep/b.md\n"


def test_vault_collects_with_snapshots(vault: Path) -> None:
    config = vault_config(
        vault, applications={"note": "40 Career/Applications.md", "field": "status"}
    )
    runner = FakeRunner(GIT_LOG)
    metrics = VaultSource(config, runner).collect(DAY, snapshots=True)

    assert dict(metrics.values) == {
        "vault_commits": 2,
        "vault_notes_edited": 2,
        "tasks_completed": 2,
        "tasks_open": 4,
        "applications_active": 2,
    }
    cmd, cwd = runner.calls[0]
    assert cwd == vault
    assert cmd[:4] == [
        "git", "log", "--since=2026-11-02T00:00:00-05:00", "--until=2026-11-02T23:59:59-05:00"
    ]  # fmt: skip


def test_vault_without_snapshots_and_without_commits(vault: Path) -> None:
    metrics = VaultSource(vault_config(vault), FakeRunner("")).collect(DAY, snapshots=False)
    assert dict(metrics.values) == {
        "vault_commits": 0,
        "vault_notes_edited": 0,
        "tasks_completed": 2,
    }


def test_vault_without_applications_section_counts_zero(vault: Path) -> None:
    metrics = VaultSource(vault_config(vault), FakeRunner("")).collect(DAY, snapshots=True)
    assert metrics.values["applications_active"] == 0


def test_vault_missing_applications_note_fails(vault: Path) -> None:
    config = vault_config(vault, applications={"note": "40 Career/Missing.md"})
    with pytest.raises(SourceError, match=r"cannot read applications note 40 Career/Missing\.md"):
        VaultSource(config, FakeRunner("")).collect(DAY, snapshots=True)


def test_vault_unreadable_note_fails(vault: Path) -> None:
    (vault / "10 Notes/bad.md").write_bytes(b"\xff")
    with pytest.raises(SourceError, match="cannot read the vault notes: UnicodeDecodeError"):
        VaultSource(vault_config(vault), FakeRunner("")).collect(DAY, snapshots=False)


def test_vault_ignores_folders_named_like_notes(vault: Path) -> None:
    (vault / "10 Notes/folder.md").mkdir()
    metrics = VaultSource(vault_config(vault), FakeRunner("")).collect(DAY, snapshots=True)
    assert metrics.values["tasks_open"] == 4


def test_vault_git_failure_propagates(vault: Path) -> None:
    def broken(cmd: Sequence[str], cwd: Path | None) -> str:
        raise SourceError("git exited with code 128")

    with pytest.raises(SourceError, match="128"):
        VaultSource(vault_config(vault), broken).collect(DAY, snapshots=False)
