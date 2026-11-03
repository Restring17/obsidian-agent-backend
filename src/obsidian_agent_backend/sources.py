"""Data sources: GitHub (through the ``gh`` CLI) and the vault itself (git and Markdown).

Commands always run as an argument list, never through a shell, and every value that
ends up in a command (login, dates) is validated or generated here.
"""

from __future__ import annotations

import json
import re
import shutil

# Commands run as argument lists only, never through a shell.
import subprocess  # nosec B404
from collections.abc import Callable, Sequence
from datetime import date, datetime, time
from pathlib import Path, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo

from obsidian_agent_backend.config import Config, ConfigError
from obsidian_agent_backend.domain import Metrics, SourceError

type Runner = Callable[[Sequence[str], Path | None], str]

COMMAND_TIMEOUT = 60  # seconds
GITHUB_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
MAX_PAGES = 10  # the search API returns at most 1000 results
PER_PAGE = 100
OPEN_TASK = re.compile(r"^\s*[-*+] \[ \](?:[ \t]|$)", re.MULTILINE)


def run(cmd: Sequence[str], cwd: Path | None = None, timeout: float = COMMAND_TIMEOUT) -> str:
    """Run a command without a shell and return its standard output."""
    executable = shutil.which(cmd[0])
    if executable is None:
        raise SourceError(f"command not found: {cmd[0]}")
    try:
        # No shell; the executable is resolved with shutil.which and arguments are validated.
        result = subprocess.run(  # noqa: S603  # nosec B603
            [executable, *cmd[1:]],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise SourceError(f"{cmd[0]} exited with code {exc.returncode}") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise SourceError(f"{cmd[0]} failed: {type(exc).__name__}") from exc
    return result.stdout


def day_bounds(day: date, tz: ZoneInfo) -> tuple[str, str]:
    """First and last second of ``day`` in ``tz`` as ISO 8601 with the UTC offset."""
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day, time(23, 59, 59), tzinfo=tz)
    return start.isoformat(), end.isoformat()


def human_notes(config: Config) -> list[Path]:
    """Every Markdown file in the human zone, sorted."""
    root = config.vault
    in_zone = config.in_human_zone
    notes: list[Path] = []
    # Filter top-level folders first so .git and the agent folder are never walked.
    for top in sorted(root.iterdir()):
        if not top.is_dir() or not in_zone(PurePosixPath(top.name, "_.md")):
            continue
        notes += (
            path
            for path in top.rglob("*.md")
            if path.is_file() and in_zone(PurePosixPath(path.relative_to(root).as_posix()))
        )
    return sorted(notes)


class GitHubSource:
    """Commits, repositories and pull requests of the authenticated ``gh`` user."""

    def __init__(self, tz: ZoneInfo, runner: Runner = run, login: str | None = None) -> None:
        self._tz = tz
        self._run = runner
        self._login = login

    def login(self) -> str:
        if self._login is None:
            self._login = self._run(["gh", "api", "user", "--jq", ".login"], None).strip()
        if not GITHUB_LOGIN.match(self._login):
            raise SourceError("invalid GitHub login")
        return self._login

    def _search(self, endpoint: str, query: str) -> tuple[int, list[Any]]:
        items: list[Any] = []
        total = 0
        for page in range(1, MAX_PAGES + 1):
            output = self._run(
                [
                    "gh", "api", "-X", "GET", endpoint,
                    "-f", f"q={query}", "-f", f"per_page={PER_PAGE}", "-f", f"page={page}",
                ],
                None,
            )  # fmt: skip
            try:
                data = json.loads(output)
                total = int(data["total_count"])
                batch = list(data["items"])
            except (ValueError, KeyError, TypeError) as exc:
                raise SourceError(f"unexpected response from {endpoint}") from exc
            items.extend(batch)
            if not batch or len(items) >= total:
                break
        return total, items

    def collect(self, day: date) -> Metrics:
        login = self.login()
        start, end = day_bounds(day, self._tz)
        span = f"{start}..{end}"
        commits, items = self._search("search/commits", f"author:{login} committer-date:{span}")
        prs, _ = self._search("search/issues", f"author:{login} type:pr created:{span}")
        try:
            repos = {item["repository"]["full_name"] for item in items}
        except (KeyError, TypeError) as exc:
            raise SourceError("commit without repository in the response") from exc
        return Metrics({"github_commits": commits, "github_repos": len(repos), "github_prs": prs})


class VaultSource:
    """Vault commits and edited notes (git), plus tasks and applications (Markdown)."""

    def __init__(self, config: Config, runner: Runner = run) -> None:
        self._config = config
        self._run = runner

    def _git(self, day: date) -> tuple[int, int]:
        start, end = day_bounds(day, self._config.timezone)
        output = self._run(
            [
                "git", "log", f"--since={start}", f"--until={end}",
                "--format=@%H", "--name-only", "--no-renames",
            ],
            self._config.vault,
        )  # fmt: skip
        commits, notes = 0, set()
        for line in output.splitlines():
            if line.startswith("@"):
                commits += 1
            elif line.endswith(".md"):
                notes.add(line)
        return commits, len(notes)

    def _applications(self) -> int:
        apps = self._config.applications
        if apps is None:
            return 0
        try:
            path = self._config.resolve(apps.note)
            text = path.read_text(encoding="utf-8")
        except (ConfigError, OSError, UnicodeError) as exc:
            raise SourceError(f"cannot read applications note {apps.note}") from exc
        pattern = re.compile(rf"\[{re.escape(apps.field)}::\s*([^\]\n]*?)\s*\]")
        return sum(1 for value in pattern.findall(text) if value.casefold() in apps.active)

    def collect(self, day: date, snapshots: bool) -> Metrics:
        commits, notes = self._git(day)
        done = re.compile(
            rf"^\s*[-*+] \[[xX]\][ \t].*✅ ?{re.escape(day.isoformat())}", re.MULTILINE
        )
        try:
            texts = [path.read_text(encoding="utf-8") for path in human_notes(self._config)]
        except (OSError, UnicodeError) as exc:
            raise SourceError(f"cannot read the vault notes: {type(exc).__name__}") from exc
        values = {
            "vault_commits": commits,
            "vault_notes_edited": notes,
            "tasks_completed": sum(len(done.findall(text)) for text in texts),
        }
        if snapshots:
            values["tasks_open"] = sum(len(OPEN_TASK.findall(text)) for text in texts)
            values["applications_active"] = self._applications()
        return Metrics(values)
