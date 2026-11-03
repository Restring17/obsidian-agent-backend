from types import MappingProxyType
from typing import Any

import pytest

from obsidian_agent_backend.domain import RESERVED_KEYS, SNAPSHOT_KEYS, Metrics


def test_merge_combines_and_other_wins() -> None:
    merged = Metrics({"a": 1, "b": 2}).merge(Metrics({"b": 5, "c": 0}))
    assert dict(merged.values) == {"a": 1, "b": 5, "c": 0}


def test_values_are_read_only_copies() -> None:
    source = {"a": 1}
    metrics = Metrics(source)
    source["a"] = 9
    assert metrics.values["a"] == 1
    assert isinstance(metrics.values, MappingProxyType)


@pytest.mark.parametrize(
    "values",
    [{"A": 1}, {"1a": 1}, {"a-b": 1}, {"": 1}, {"a": -1}, {"a": True}, {"a": 1.5}, {"a": "1"}],
)
def test_invalid_metrics_are_rejected(values: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="invalid"):
        Metrics(values)


def test_non_string_key_is_rejected() -> None:
    values: dict[Any, int] = {1: 1}
    with pytest.raises(ValueError, match="invalid metric key"):
        Metrics(values)


def test_has_activity_ignores_snapshots() -> None:
    assert not Metrics().has_activity()
    snapshot_only = Metrics({"vault_commits": 0, "tasks_open": 7, "applications_active": 2})
    assert not snapshot_only.has_activity()
    assert Metrics({"vault_commits": 1}).has_activity()


def test_summary() -> None:
    assert Metrics().summary() == "(none)"
    assert Metrics({"a": 1, "b": 0}).summary() == "a=1, b=0"


def test_reserved_keys_include_snapshots_and_timestamp() -> None:
    assert set(SNAPSHOT_KEYS) <= RESERVED_KEYS
    assert "collected_at" in RESERVED_KEYS
