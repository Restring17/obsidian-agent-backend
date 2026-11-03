"""Tell the tools' edits to the daily notes apart from the user's.

The tools only ever touch the daily notes in two ways: ``oab-collect`` sets the keys in
:data:`RESERVED_KEYS` and ``oab-review`` appends one log line to today's note. So the
version to commit is rebuilt as *before + those edits*, where *before* is the note at
HEAD (or the rendered template if git does not track it yet). Whatever else the working
copy holds is the user's and is left out.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath

from obsidian_agent_backend.config import Config
from obsidian_agent_backend.daily_note import (
    DailyNote,
    NoteError,
    append_log,
    frontmatter_lines,
    merge_frontmatter,
)
from obsidian_agent_backend.domain import RESERVED_KEYS
from obsidian_agent_backend.exact_commit import changed_paths, head_text
from obsidian_agent_backend.sources import Runner

NOTE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")

type Edit = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class Change:
    """One file to commit: its content before the tools ran, and how to redo their edits."""

    before: str
    redo: Edit

    @property
    def text(self) -> str:
        return self.redo(self.before)


@dataclass(frozen=True, slots=True)
class ToolChanges:
    changes: dict[str, Change]
    skipped: list[str]  # notes whose edits cannot be separated: they stay uncommitted


def _note_day(path: str, folder: PurePosixPath) -> date | None:
    posix = PurePosixPath(path)
    if posix.parent != folder or not NOTE_NAME.match(posix.name):
        return None
    try:
        return date.fromisoformat(posix.stem)
    except ValueError:
        return None


def _redo(values: dict[str, str], heading: str, log_line: str | None) -> Edit:
    def redo(text: str) -> str:
        if values:
            text = merge_frontmatter(text, values)
        return append_log(text, heading, log_line) if log_line is not None else text

    return redo


def daily_note_changes(config: Config, runner: Runner, today: date, log_line: str) -> ToolChanges:
    """The tools' edits to every changed daily note (today's carries ``log_line``)."""
    vault, folder = config.vault, config.daily_notes.folder
    today_note = (folder / f"{today.isoformat()}.md").as_posix()
    notes = DailyNote(config)
    changes: dict[str, Change] = {}
    skipped: list[str] = []
    for path in sorted(changed_paths(vault, runner) | {today_note}):
        day = _note_day(path, folder)
        file = Path(vault, path)
        if day is None or not file.is_file():
            continue
        log = log_line if path == today_note else None
        try:
            values = frontmatter_lines(file.read_text(encoding="utf-8"), sorted(RESERVED_KEYS))
            if not values and log is None:
                continue  # an edit of the user's only
            committed = head_text(vault, runner, path)
            before = committed if committed is not None else notes.from_template(day)
            change = Change(before, _redo(values, config.daily_notes.log_heading, log))
            if change.text != committed:
                changes[path] = change
        except (NoteError, UnicodeError):
            skipped.append(path)
    return ToolChanges(changes, skipped)
