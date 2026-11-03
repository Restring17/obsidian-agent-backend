from datetime import date

import pytest

from obsidian_agent_backend.week import IsoWeek


def test_parse_and_properties() -> None:
    week = IsoWeek.parse("2026-W45")
    assert week == IsoWeek(2026, 45)
    assert (week.start, week.end) == (date(2026, 11, 2), date(2026, 11, 8))
    assert week.label == "2026-W45"
    assert week.days()[0] == week.start
    assert week.days()[-1] == week.end
    assert len(week.days()) == 7


@pytest.mark.parametrize("text", ["2026-45", "2026-W5", "26-W45", "2026-w45", "2026-W45 ", ""])
def test_parse_rejects_bad_labels(text: str) -> None:
    with pytest.raises(ValueError, match="invalid week"):
        IsoWeek.parse(text)


@pytest.mark.parametrize("text", ["2026-W00", "2026-W54", "2025-W53"])
def test_parse_rejects_weeks_that_do_not_exist(text: str) -> None:
    with pytest.raises(ValueError, match="no such ISO week"):
        IsoWeek.parse(text)


def test_week_53_exists_in_long_years() -> None:
    assert IsoWeek.parse("2026-W53").end == date(2027, 1, 3)


def test_before_and_previous_cross_years() -> None:
    assert IsoWeek.before(date(2026, 11, 3)) == IsoWeek(2026, 44)
    assert IsoWeek.before(date(2027, 1, 4)) == IsoWeek(2026, 53)
    assert IsoWeek(2027, 1).previous() == IsoWeek(2026, 53)


def test_weeks_are_ordered() -> None:
    assert IsoWeek(2026, 44) < IsoWeek(2026, 45) < IsoWeek(2027, 1)
