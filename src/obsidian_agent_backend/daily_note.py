"""Daily note access: create it from the template and merge metrics into its frontmatter.

Only the frontmatter lines of the written keys change; the body and every other key stay
byte for byte. Writes go to a temporary file next to the note and are renamed over it,
so a crash never leaves a half-written note.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Mapping
from datetime import date
from pathlib import Path

import yaml

from obsidian_agent_backend.config import Config, ConfigError
from obsidian_agent_backend.domain import COLLECTED_AT_KEY, Metrics

FRONTMATTER = re.compile(r"\A---\n(.*?\n)?---(?:\n|\Z)", re.DOTALL)
SECTION = re.compile(r"^#{1,2} ", re.MULTILINE)
# Obsidian core Templates and Templater-style date placeholders.
DATE_PLACEHOLDERS = ("{{date:YYYY-MM-DD}}", "{{date}}", "{{title}}")
EMPTY_NOTE = "---\n---\n"
TEMP_PREFIX = ".oab-"


class NoteError(Exception):
    """The note or the template does not have the expected format."""


def read_frontmatter(text: str) -> dict[str, object]:
    """The frontmatter as a mapping; empty when missing or invalid (never raises)."""
    match = FRONTMATTER.match(text)
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1) or "")
    except yaml.YAMLError:
        return {}
    return {str(key): value for key, value in data.items()} if isinstance(data, dict) else {}


def _log_section(text: str, heading: str) -> tuple[int, int] | None:
    """Start and end offsets of the body of ``## <heading>``, if present."""
    match = re.search(rf"^## {re.escape(heading)}[ \t]*\n", text, re.MULTILINE)
    if not match:
        return None
    following = SECTION.search(text, match.end())
    return match.end(), following.start() if following else len(text)


def log_lines(text: str, heading: str) -> list[str]:
    """List items (``- …``) of the ``## <heading>`` section."""
    bounds = _log_section(text, heading)
    if bounds is None:
        return []
    body = text[bounds[0] : bounds[1]]
    return [line.strip() for line in body.splitlines() if line.strip().startswith("- ")]


def append_log(text: str, heading: str, line: str) -> str:
    """Append ``line`` to the end of ``## <heading>``, creating the section if needed."""
    if not line.strip() or "\n" in line or "\r" in line:
        raise NoteError("a log entry must be a single non-empty line")
    if not text.endswith("\n"):
        text += "\n"
    bounds = _log_section(text, heading)
    if bounds is None:
        return text.rstrip("\n") + f"\n\n## {heading}\n{line}\n"
    start, end = bounds
    body = text[start:end].rstrip("\n")
    rest = text[end:]
    return (
        text[:start] + body + ("\n" if body else "") + line + "\n" + ("\n" + rest if rest else "")
    )


def merge_frontmatter(text: str, values: Mapping[str, str]) -> str:
    """Replace or append ``key: value`` lines in the frontmatter, leaving the rest as is.

    ``values`` are already serialised YAML scalars. The result is parsed back to make
    sure each key now holds exactly the written value (catches duplicate keys and
    multi-line values that a line-based edit could break).
    """
    match = FRONTMATTER.match(text)
    if not match:
        raise NoteError("the note has no frontmatter")
    block = match.group(1) or ""
    for key, value in values.items():
        line = f"{key}: {value}"
        pattern = re.compile(rf"^{re.escape(key)}:.*$", re.MULTILINE)
        block, found = pattern.subn(lambda _, line=line: line, block, count=1)
        if not found:
            block += line + "\n"
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise NoteError("the resulting frontmatter is not valid YAML") from exc
    if not isinstance(data, dict):
        raise NoteError("the resulting frontmatter is not a mapping")
    for key, value in values.items():
        if data.get(key) != yaml.safe_load(value):
            raise NoteError(f"frontmatter key {key!r} could not be updated safely")
    return f"---\n{block}---\n" + text[match.end() :]


def atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` through a temporary file in the same folder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=TEMP_PREFIX, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class DailyNote:
    def __init__(self, config: Config) -> None:
        self._config = config

    def path(self, day: date) -> Path:
        relative = self._config.daily_notes.folder / f"{day.isoformat()}.md"
        try:
            return self._config.resolve(relative)
        except ConfigError as exc:
            raise NoteError(str(exc)) from None

    def exists(self, day: date) -> bool:
        return self.path(day).is_file()

    def _from_template(self, day: date) -> str:
        template = self._config.daily_notes.template
        if template is None:
            return EMPTY_NOTE
        try:
            text = self._config.resolve(template).read_text(encoding="utf-8")
        except (ConfigError, OSError, UnicodeError):
            raise NoteError(f"cannot read the template {template}") from None
        for placeholder in DATE_PLACEHOLDERS:
            text = text.replace(placeholder, day.isoformat())
        return text

    def _read(self, day: date) -> str:
        path = self.path(day)
        if not path.is_file():
            return self._from_template(day)
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeError:
            raise NoteError(f"{path.name} is not valid UTF-8") from None

    def log(self, day: date, line: str) -> Path:
        """Append a line to the log section of the day's note (created if missing)."""
        path = self.path(day)
        atomic_write(path, append_log(self._read(day), self._config.daily_notes.log_heading, line))
        return path

    def update(self, day: date, metrics: Metrics, collected_at: str) -> Path:
        """Write ``metrics`` and the collection timestamp; create the note if needed."""
        values = {key: str(value) for key, value in metrics.values.items()}
        values[COLLECTED_AT_KEY] = f'"{collected_at}"'
        path = self.path(day)
        atomic_write(path, merge_frontmatter(self._read(day), values))
        return path
