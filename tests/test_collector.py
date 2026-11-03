import io
from datetime import date
from pathlib import Path

from obsidian_agent_backend.collector import EXIT_OK, EXIT_PARTIAL_FAILURE, Collector
from obsidian_agent_backend.daily_note import NoteError
from obsidian_agent_backend.domain import Metrics, SourceError

TODAY = date(2026, 11, 3)
YESTERDAY = date(2026, 11, 2)
OLD = date(2026, 10, 20)
STAMP = "2026-11-03T06:00"


class FakeGitHub:
    def __init__(self, fail_on: set[date] | None = None, commits: int = 2) -> None:
        self.fail_on, self.commits, self.days = fail_on or set(), commits, list[date]()

    def collect(self, day: date) -> Metrics:
        self.days.append(day)
        if day in self.fail_on:
            raise SourceError("no network")
        return Metrics({"github_commits": self.commits})


class FakeVault:
    def __init__(self, fail: bool = False, commits: int = 1) -> None:
        self.fail, self.commits = fail, commits
        self.calls: list[tuple[date, bool]] = []

    def collect(self, day: date, snapshots: bool) -> Metrics:
        self.calls.append((day, snapshots))
        if self.fail:
            raise SourceError("git broken")
        values = {"vault_commits": self.commits}
        if snapshots:
            values["tasks_open"] = 5
        return Metrics(values)


class FakeNote:
    def __init__(
        self,
        existing: set[date] | None = None,
        fail_write: set[date] | None = None,
        fail_exists: bool = False,
    ) -> None:
        self.existing, self.fail_write = existing or set(), fail_write or set()
        self.fail_exists = fail_exists
        self.written: dict[date, tuple[dict[str, int], str]] = {}

    def exists(self, day: date) -> bool:
        if self.fail_exists:
            raise NoteError("resolves outside the vault")
        return day in self.existing

    def update(self, day: date, metrics: Metrics, collected_at: str) -> Path:
        if day in self.fail_write:
            raise OSError("read-only file system")
        self.written[day] = (dict(metrics.values), collected_at)
        return Path(f"/vault/Daily/{day}.md")


def make(
    github: FakeGitHub | None = None, vault: FakeVault | None = None, note: FakeNote | None = None
) -> tuple[Collector, FakeNote, io.StringIO, io.StringIO]:
    note = note or FakeNote()
    out, err = io.StringIO(), io.StringIO()
    collector = Collector(github, vault or FakeVault(), note, out, err)
    return collector, note, out, err


def test_writes_metrics_from_every_source() -> None:
    collector, note, out, err = make(FakeGitHub())
    assert collector.run([YESTERDAY], TODAY, STAMP, dry_run=False) == EXIT_OK
    assert note.written[YESTERDAY] == (
        {"github_commits": 2, "vault_commits": 1, "tasks_open": 5},
        STAMP,
    )
    assert out.getvalue() == (
        "2026-11-02: github_commits=2, vault_commits=1, tasks_open=5 -> 2026-11-02.md\n"
    )
    assert err.getvalue() == ""


def test_snapshots_only_for_today_and_yesterday() -> None:
    vault = FakeVault()
    collector, *_ = make(vault=vault)
    before_yesterday = date(2026, 11, 1)
    collector.run([TODAY, YESTERDAY, before_yesterday, OLD], TODAY, STAMP, dry_run=False)
    assert vault.calls == [
        (TODAY, True),
        (YESTERDAY, True),
        (before_yesterday, False),
        (OLD, False),
    ]


def test_failing_source_writes_no_fake_zeros_and_returns_1() -> None:
    collector, note, _, err = make(FakeGitHub(fail_on={YESTERDAY}))
    assert collector.run([YESTERDAY], TODAY, STAMP, dry_run=False) == EXIT_PARTIAL_FAILURE
    assert "github_commits" not in note.written[YESTERDAY][0]
    assert err.getvalue() == "2026-11-02 GitHub: no network (its metrics are not written)\n"


def test_a_failure_does_not_stop_the_following_days() -> None:
    github = FakeGitHub(fail_on={YESTERDAY})
    collector, note, *_ = make(github)
    assert collector.run([YESTERDAY, OLD], TODAY, STAMP, dry_run=False) == EXIT_PARTIAL_FAILURE
    assert github.days == [YESTERDAY, OLD]
    assert note.written[OLD][0]["github_commits"] == 2


def test_every_source_failing_writes_nothing() -> None:
    note = FakeNote(existing={YESTERDAY})
    collector, _, out, err = make(FakeGitHub(fail_on={YESTERDAY}), FakeVault(fail=True), note)
    assert collector.run([YESTERDAY], TODAY, STAMP, dry_run=False) == EXIT_PARTIAL_FAILURE
    assert note.written == {}
    assert out.getvalue() == ""
    assert err.getvalue().count("\n") == 2


def test_no_activity_creates_no_note_and_continues() -> None:
    collector, note, out, _ = make(FakeGitHub(commits=0), FakeVault(commits=0))
    assert collector.run([YESTERDAY, OLD], TODAY, STAMP, dry_run=False) == EXIT_OK
    assert note.written == {}
    assert out.getvalue() == (
        "2026-11-02: no activity, no note created\n2026-10-20: no activity, no note created\n"
    )


def test_no_activity_but_existing_note_is_updated() -> None:
    note = FakeNote(existing={OLD})
    collector, *_ = make(vault=FakeVault(commits=0), note=note)
    assert collector.run([OLD], TODAY, STAMP, dry_run=False) == EXIT_OK
    assert note.written[OLD][0] == {"vault_commits": 0}


def test_dry_run_writes_nothing() -> None:
    collector, note, out, _ = make()
    assert collector.run([YESTERDAY], TODAY, STAMP, dry_run=True) == EXIT_OK
    assert note.written == {}
    assert out.getvalue() == "2026-11-02 (dry run): vault_commits=1, tasks_open=5\n"


def test_write_error_is_reported_and_next_day_still_written() -> None:
    note = FakeNote(fail_write={YESTERDAY})
    collector, _, _, err = make(note=note)
    assert collector.run([YESTERDAY, OLD], TODAY, STAMP, dry_run=False) == EXIT_PARTIAL_FAILURE
    assert err.getvalue() == "2026-11-02: cannot write the note: read-only file system\n"
    assert OLD in note.written


def test_unsafe_note_path_is_reported() -> None:
    collector, _, _, err = make(note=FakeNote(fail_exists=True))
    assert collector.run([YESTERDAY], TODAY, STAMP, dry_run=False) == EXIT_PARTIAL_FAILURE
    assert err.getvalue() == "2026-11-02: resolves outside the vault\n"


def test_unsafe_note_path_does_not_stop_the_following_days() -> None:
    collector, _, _, err = make(note=FakeNote(fail_exists=True))
    assert collector.run([YESTERDAY, OLD], TODAY, STAMP, dry_run=False) == EXIT_PARTIAL_FAILURE
    assert err.getvalue().splitlines() == [
        "2026-11-02: resolves outside the vault",
        "2026-10-20: resolves outside the vault",
    ]


def test_a_day_without_data_does_not_stop_the_following_days() -> None:
    github = FakeGitHub(fail_on={YESTERDAY})
    collector, note, *_ = make(github, FakeVault(fail=True))
    assert collector.run([YESTERDAY, OLD], TODAY, STAMP, dry_run=False) == EXIT_PARTIAL_FAILURE
    assert note.written == {OLD: ({"github_commits": 2}, STAMP)}


def test_github_can_be_disabled() -> None:
    collector, note, *_ = make(github=None)
    collector.run([YESTERDAY], TODAY, STAMP, dry_run=False)
    assert "github_commits" not in note.written[YESTERDAY][0]
