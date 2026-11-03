"""Deterministic context for the weekly review.

Everything the report needs is computed here, so the model never invents numbers and does
not spend tokens walking the vault. Notes whose frontmatter marks them as private are left
out of the task, application and project lists.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TypeGuard

from obsidian_agent_backend.config import Config, ConfigError
from obsidian_agent_backend.daily_note import log_lines, read_frontmatter
from obsidian_agent_backend.domain import GITHUB_KEYS, VAULT_KEYS, SourceError
from obsidian_agent_backend.sources import Runner, day_bounds, human_notes, run
from obsidian_agent_backend.week import IsoWeek

MAX_COMMITS = 100
MAX_TASKS = 40
OPEN_TASK = re.compile(r"^\s*[-*+] \[ \][ \t]+(.+)$", re.MULTILINE)
NO_DATA = "—"

type Number = int | float


def is_number(value: object) -> TypeGuard[Number]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _format(value: Number) -> str:
    return f"{value:g}"


@dataclass(frozen=True, slots=True)
class Note:
    path: Path
    relative: PurePosixPath
    text: str
    frontmatter: dict[str, object]

    @property
    def link(self) -> str:
        return f"[[{self.path.stem}]]"


class WeeklyContext:
    def __init__(self, config: Config, runner: Runner = run) -> None:
        self._config = config
        self._run = runner

    @property
    def metric_keys(self) -> tuple[str, ...]:
        return (*GITHUB_KEYS, *VAULT_KEYS, *self._config.metrics.manual)

    def _read(self, path: Path) -> Note:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SourceError(f"cannot read {path.name}: {type(exc).__name__}") from exc
        relative = PurePosixPath(path.relative_to(self._config.vault).as_posix())
        return Note(path, relative, text, read_frontmatter(text))

    def _public_notes(self) -> list[Note]:
        private = self._config.human_zone.private_field
        notes = (self._read(path) for path in human_notes(self._config))
        return [note for note in notes if note.frontmatter.get(private) is not True]

    def _daily(self, week: IsoWeek) -> str:
        keys = self.metric_keys
        heading = self._config.daily_notes.log_heading
        rows, log, totals = [], [], dict[str, Number]()
        for day in week.days():
            relative = self._config.daily_notes.folder / f"{day.isoformat()}.md"
            try:
                path = self._config.resolve(relative)
            except ConfigError as exc:
                raise SourceError(str(exc)) from None
            if not path.is_file():
                rows.append(f"| {day} | " + " | ".join(NO_DATA for _ in keys) + " |")
                continue
            note = self._read(path)
            cells = []
            for key in keys:
                value = note.frontmatter.get(key)
                if is_number(value):
                    totals[key] = totals.get(key, 0) + value
                    cells.append(_format(value))
                else:
                    cells.append(NO_DATA)
            rows.append(f"| [[{day}]] | " + " | ".join(cells) + " |")
            log += [f"- {day}: {line[2:]}" for line in log_lines(note.text, heading)]
        header = "| Day | " + " | ".join(keys) + " |\n|" + "---|" * (len(keys) + 1)
        total = (
            "| **Total** | "
            + " | ".join(_format(totals[key]) if key in totals else NO_DATA for key in keys)
            + " |"
        )
        return (
            f"## Metrics per day ({NO_DATA} = no data)\n"
            + header
            + "\n"
            + "\n".join(rows)
            + "\n"
            + total
            + f"\n\n## {heading} of the week\n"
            + ("\n".join(log) or "(empty)")
        )

    def _commits(self, week: IsoWeek) -> str:
        since, _ = day_bounds(week.start, self._config.timezone)
        _, until = day_bounds(week.end, self._config.timezone)
        output = self._run(
            [
                "git", "log", f"--since={since}", f"--until={until}",
                "--format=%h %ad %s", "--date=short",
            ],
            self._config.vault,
        )  # fmt: skip
        lines = [line for line in output.splitlines() if line.strip()]
        more = f"\n(+{len(lines) - MAX_COMMITS} more)" if len(lines) > MAX_COMMITS else ""
        body = "\n".join(f"- {line}" for line in lines[:MAX_COMMITS]) or "(none)"
        return f"## Vault commits ({len(lines)})\n{body}{more}"

    def _tasks(self, notes: Sequence[Note]) -> str:
        tasks = [
            f"- {task.strip()} ({note.link})"
            for note in notes
            for task in OPEN_TASK.findall(note.text)
        ]
        more = f"\n(+{len(tasks) - MAX_TASKS} more)" if len(tasks) > MAX_TASKS else ""
        body = "\n".join(tasks[:MAX_TASKS]) or "(none)"
        return f"## Open tasks ({len(tasks)})\n{body}{more}"

    def _applications(self, notes: Sequence[Note]) -> str | None:
        apps = self._config.applications
        if apps is None:
            return None
        field = re.compile(rf"^\s*[-*+] (.*\[{re.escape(apps.field)}::.*)$", re.MULTILINE)
        note = next((note for note in notes if note.relative == apps.note), None)
        lines = [f"- {item.strip()}" for item in field.findall(note.text)] if note else []
        return "## Applications\n" + ("\n".join(lines) or "(none)")

    def _projects(self, notes: Sequence[Note]) -> str | None:
        projects = self._config.projects
        if projects is None:
            return None
        lines = []
        for note in notes:
            status = note.frontmatter.get(projects.status_field)
            if note.relative.is_relative_to(projects.folder) and status:
                lines.append(f"- {note.link}: {status}")
        return "## Projects\n" + ("\n".join(lines) or "(none)")

    def build(self, week: IsoWeek) -> str:
        """The data block appended to the prompt."""
        notes = self._public_notes()
        sections = [
            f"# Data for week {week.label} ({week.start} to {week.end})",
            self._daily(week),
            self._commits(week),
            self._tasks(notes),
            self._applications(notes),
            self._projects(notes),
        ]
        return "\n\n".join(section for section in sections if section is not None)
