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
# Obsidian core Templates and Templater-style date placeholders.
DATE_PLACEHOLDERS = ("{{date:YYYY-MM-DD}}", "{{date}}", "{{title}}")
EMPTY_NOTE = "---\n---\n"
TEMP_PREFIX = ".oab-"


class NoteError(Exception):
    """The note or the template does not have the expected format."""


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

    def update(self, day: date, metrics: Metrics, collected_at: str) -> Path:
        """Write ``metrics`` and the collection timestamp; create the note if needed."""
        values = {key: str(value) for key, value in metrics.values.items()}
        values[COLLECTED_AT_KEY] = f'"{collected_at}"'
        path = self.path(day)
        atomic_write(path, merge_frontmatter(self._read(day), values))
        return path
