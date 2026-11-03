"""Collector domain: the metrics of one day. No I/O and no third-party dependencies."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

METRIC_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

GITHUB_KEYS = ("github_commits", "github_repos", "github_prs")
VAULT_KEYS = ("vault_commits", "vault_notes_edited", "tasks_completed")
# Snapshot metrics describe the current state, not the day's activity: they do not count
# as activity and are only written for today and yesterday, never for past days.
SNAPSHOT_KEYS = ("tasks_open", "applications_active")
COLLECTED_AT_KEY = "collected_at"
# Every frontmatter key the collector writes. Manual metrics must not reuse them.
RESERVED_KEYS = frozenset((*GITHUB_KEYS, *VAULT_KEYS, *SNAPSHOT_KEYS, COLLECTED_AT_KEY))


class SourceError(Exception):
    """A source could not get its data (network, authentication, git…)."""


@dataclass(frozen=True, slots=True)
class Metrics:
    """Validated, immutable metric values: lowercase keys and non-negative integers."""

    values: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for key, value in self.values.items():
            if not isinstance(key, str) or not METRIC_KEY.match(key):
                raise ValueError(f"invalid metric key: {key!r}")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"invalid value for {key}: {value!r}")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    def merge(self, other: Metrics) -> Metrics:
        """A new instance with both sets of values; ``other`` wins on conflicts."""
        return Metrics({**self.values, **other.values})

    def has_activity(self) -> bool:
        """Whether any non-snapshot metric is above zero."""
        return any(value > 0 for key, value in self.values.items() if key not in SNAPSHOT_KEYS)

    def summary(self) -> str:
        return ", ".join(f"{key}={value}" for key, value in self.values.items()) or "(none)"
