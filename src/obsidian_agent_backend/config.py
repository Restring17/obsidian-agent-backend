"""Load and validate ``oab.toml``.

Everything that depends on a particular vault (folders, timezone, metrics, model) comes
from this file, so the rest of the code never hardcodes one person's layout. The vault
root is the directory that contains the config file.

Validation is strict: unknown keys, wrong types, bad timezones and paths that could
escape the vault are rejected with a :class:`ConfigError` that names the offending key.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from obsidian_agent_backend.domain import METRIC_KEY, RESERVED_KEYS

DEFAULT_CONFIG_NAME = "oab.toml"

FIELD_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
# A Dataview inline value such as ``applied`` in ``[status:: applied]``.
# A Markdown heading text such as ``AI log`` (without the leading ``#``).
HEADING = re.compile(r"^[^#\s][^\n]{0,63}$")
FIELD_VALUE = re.compile(r"^[^\[\]\n]{1,64}$")
# Aliases (``sonnet``) and full ids (``claude-sonnet-5-5``, ``sonnet[1m]``). The value is
# passed as a single argv item, never through a shell; the pattern keeps it to a plain token.
MODEL_NAME = re.compile(r"^[a-z0-9][a-z0-9.\-\[\]]{0,63}$")
# Characters that would make a top-level folder pattern match across directories.
_PATTERN_FORBIDDEN = frozenset("/\\")

type Table = Mapping[str, Any]


class ConfigError(Exception):
    """The configuration file is missing, unreadable or invalid."""


@dataclass(frozen=True, slots=True)
class DailyNotesConfig:
    folder: PurePosixPath
    template: PurePosixPath | None
    log_heading: str


@dataclass(frozen=True, slots=True)
class HumanZoneConfig:
    folders: tuple[str, ...]
    exclude: tuple[str, ...]
    private_field: str


@dataclass(frozen=True, slots=True)
class AgentConfig:
    folder: PurePosixPath


@dataclass(frozen=True, slots=True)
class MetricsConfig:
    manual: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ApplicationsConfig:
    note: PurePosixPath
    field: str
    active: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProjectsConfig:
    folder: PurePosixPath
    status_field: str


@dataclass(frozen=True, slots=True)
class ReviewConfig:
    model: str
    prompt: PurePosixPath | None


@dataclass(frozen=True, slots=True)
class Config:
    vault: Path
    timezone: ZoneInfo
    daily_notes: DailyNotesConfig
    human_zone: HumanZoneConfig
    agent: AgentConfig
    metrics: MetricsConfig
    applications: ApplicationsConfig | None
    projects: ProjectsConfig | None
    review: ReviewConfig

    def in_human_zone(self, relative: PurePosixPath) -> bool:
        """Whether a vault-relative path belongs to the human zone.

        The human zone is every top-level folder matching one of ``human_zone.folders``,
        except the agent folder and hidden folders (``.obsidian``, ``.git``…).
        """
        parts = relative.parts
        if len(parts) < 2:  # noqa: PLR2004 (files at the vault root are in no folder)
            return False
        top = parts[0]
        if top.startswith(".") or top == self.agent.folder.name:
            return False
        if any(
            fnmatchcase(part, pattern) for part in parts[:-1] for pattern in self.human_zone.exclude
        ):
            return False
        return any(fnmatchcase(top, pattern) for pattern in self.human_zone.folders)

    def resolve(self, relative: PurePosixPath) -> Path:
        """Absolute path of a vault-relative path, refusing symlinks that leave the vault."""
        root = self.vault.resolve()
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise ConfigError(f"{relative} resolves outside the vault")
        return target


def load_config(path: Path) -> Config:
    """Read, parse and validate a config file. The vault is the file's directory."""
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror or type(exc).__name__}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from None
    except UnicodeDecodeError:
        raise ConfigError(f"{path} is not valid UTF-8") from None
    try:
        return parse_config(data, vault=path.resolve().parent)
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from None


def parse_config(data: Table, vault: Path) -> Config:
    """Build a :class:`Config` from already-parsed TOML data."""
    _check_keys(
        data,
        "",
        {
            "timezone",
            "daily_notes",
            "human_zone",
            "agent",
            "metrics",
            "applications",
            "projects",
            "review",
        },
    )
    daily = _table(data, "daily_notes")
    _check_keys(daily, "daily_notes", {"folder", "template", "log_heading"})
    zone = _table(data, "human_zone")
    _check_keys(zone, "human_zone", {"folders", "exclude", "private_field"})
    agent = _table(data, "agent")
    _check_keys(agent, "agent", {"folder"})
    metrics = _table(data, "metrics")
    _check_keys(metrics, "metrics", {"manual"})
    review = _table(data, "review")
    _check_keys(review, "review", {"model", "prompt"})

    template = daily.get("template")
    agent_folder = _folder(_string(agent, "folder", "Agents", prefix="agent"), "agent.folder")
    if len(agent_folder.parts) != 1:
        raise ConfigError("agent.folder must be a top-level folder (no '/')")
    daily_folder = _folder(
        _string(daily, "folder", "Daily", prefix="daily_notes"), "daily_notes.folder"
    )
    if daily_folder.parts[0] == agent_folder.name:
        raise ConfigError("daily_notes.folder must not be inside agent.folder")
    return Config(
        vault=vault,
        timezone=_timezone(_string(data, "timezone", "UTC")),
        daily_notes=DailyNotesConfig(
            folder=daily_folder,
            template=None
            if template is None
            else _note(_string(daily, "template", prefix="daily_notes"), "daily_notes.template"),
            log_heading=_heading(_string(daily, "log_heading", "AI log", prefix="daily_notes")),
        ),
        human_zone=HumanZoneConfig(
            folders=_patterns(zone, "folders", ["*"]),
            exclude=_patterns(zone, "exclude", [], allow_empty=True),
            private_field=_field(
                _string(zone, "private_field", "private", prefix="human_zone"),
                "human_zone.private_field",
            ),
        ),
        agent=AgentConfig(folder=agent_folder),
        metrics=MetricsConfig(manual=_metric_keys(metrics)),
        applications=_applications(data),
        projects=_projects(data),
        review=ReviewConfig(
            model=_model(_string(review, "model", "sonnet", prefix="review")),
            prompt=None
            if review.get("prompt") is None
            else _note(_string(review, "prompt", prefix="review"), "review.prompt"),
        ),
    )


# --- helpers -------------------------------------------------------------------


def _key(prefix: str, name: str) -> str:
    return f"{prefix}.{name}" if prefix else name


def _check_keys(table: Table, prefix: str, allowed: set[str]) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        names = ", ".join(_key(prefix, name) for name in unknown)
        raise ConfigError(f"unknown key(s): {names}")


def _table(data: Table, name: str) -> Table:
    value = data.get(name, {})
    if not isinstance(value, Mapping):
        raise ConfigError(f"[{name}] must be a table")
    return value


def _string(table: Table, key: str, default: str | None = None, *, prefix: str = "") -> str:
    value = table.get(key, default)
    if not isinstance(value, str):
        raise ConfigError(f"{_key(prefix, key)} must be a string")
    return value


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"timezone: unknown IANA timezone {name!r}") from None


def _relative(raw: str, key: str) -> PurePosixPath:
    """A vault-relative path that cannot escape the vault lexically."""
    if not raw.strip():
        raise ConfigError(f"{key} must not be empty")
    if "\\" in raw or "\0" in raw:
        raise ConfigError(f"{key} must use '/' as separator")
    path = PurePosixPath(raw)
    if path.is_absolute():
        raise ConfigError(f"{key} must be relative to the vault, got {raw!r}")
    if ".." in path.parts:
        raise ConfigError(f"{key} must not contain '..' (paths cannot leave the vault)")
    if path == PurePosixPath("."):
        raise ConfigError(f"{key} must not be the vault root")
    return path


def _folder(raw: str, key: str) -> PurePosixPath:
    path = _relative(raw, key)
    if path.parts[0].startswith("."):
        raise ConfigError(f"{key} must not be a hidden folder")
    return path


def _note(raw: str, key: str) -> PurePosixPath:
    path = _relative(raw, key)
    if path.suffix != ".md":
        raise ConfigError(f"{key} must be a Markdown file (.md)")
    return path


def _patterns(
    zone: Table, key: str, default: list[str], *, allow_empty: bool = False
) -> tuple[str, ...]:
    """Glob patterns over single folder names (never across '/')."""
    raw = zone.get(key, default)
    shape = "a list of strings" if allow_empty else "a non-empty list of strings"
    if not isinstance(raw, list) or not (raw or allow_empty):
        raise ConfigError(f"human_zone.{key} must be {shape}")
    patterns: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"human_zone.{key} must be {shape}")
        if _PATTERN_FORBIDDEN & set(item) or item in {".", ".."}:
            raise ConfigError(f"human_zone.{key}: {item!r} must match folder names only")
        patterns.append(item)
    return tuple(patterns)


def _metric_keys(metrics: Table) -> tuple[str, ...]:
    raw = metrics.get("manual", [])
    if not isinstance(raw, list):
        raise ConfigError("metrics.manual must be a list of strings")
    keys: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not METRIC_KEY.match(item):
            raise ConfigError(
                f"metrics.manual: {item!r} is not a valid key (lowercase, digits, '_')"
            )
        if item in RESERVED_KEYS:
            raise ConfigError(f"metrics.manual: {item!r} is written by the collector")
        if item in keys:
            raise ConfigError(f"metrics.manual: duplicate key {item!r}")
        keys.append(item)
    return tuple(keys)


def _applications(data: Table) -> ApplicationsConfig | None:
    if "applications" not in data:
        return None
    table = _table(data, "applications")
    _check_keys(table, "applications", {"note", "field", "active"})
    if "note" not in table:
        raise ConfigError("applications.note is required when [applications] is present")
    field = _field(_string(table, "field", "status", prefix="applications"), "applications.field")
    return ApplicationsConfig(
        note=_note(_string(table, "note", prefix="applications"), "applications.note"),
        field=field,
        active=_active_values(table),
    )


def _active_values(table: Table) -> tuple[str, ...]:
    raw = table.get("active", ["applied", "interview"])
    if not isinstance(raw, list) or not raw:
        raise ConfigError("applications.active must be a non-empty list of strings")
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not FIELD_VALUE.match(item) or not item.strip():
            raise ConfigError(f"applications.active: {item!r} is not a valid field value")
        values.append(item.strip().casefold())
    return tuple(values)


def _projects(data: Table) -> ProjectsConfig | None:
    if "projects" not in data:
        return None
    table = _table(data, "projects")
    _check_keys(table, "projects", {"folder", "status_field"})
    if "folder" not in table:
        raise ConfigError("projects.folder is required when [projects] is present")
    return ProjectsConfig(
        folder=_folder(_string(table, "folder", prefix="projects"), "projects.folder"),
        status_field=_field(
            _string(table, "status_field", "status", prefix="projects"), "projects.status_field"
        ),
    )


def _field(name: str, key: str) -> str:
    if not FIELD_NAME.match(name):
        raise ConfigError(f"{key}: {name!r} is not a valid Dataview field name")
    return name


def _heading(text: str) -> str:
    if not HEADING.match(text) or text != text.strip():
        raise ConfigError(
            f"daily_notes.log_heading: {text!r} must be one line of heading text without '#'"
        )
    return text


def _model(name: str) -> str:
    if not MODEL_NAME.match(name):
        raise ConfigError(f"review.model: invalid model name {name!r}")
    return name
