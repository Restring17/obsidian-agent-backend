"""ISO week (Monday to Sunday)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

WEEK_LABEL = re.compile(r"^(\d{4})-W(\d{2})$")
DAYS_PER_WEEK = 7


@dataclass(frozen=True, slots=True, order=True)
class IsoWeek:
    year: int
    number: int

    def __post_init__(self) -> None:
        try:
            date.fromisocalendar(self.year, self.number, 1)
        except ValueError:
            raise ValueError(f"no such ISO week: {self.year}-W{self.number:02d}") from None

    @classmethod
    def parse(cls, text: str) -> IsoWeek:
        match = WEEK_LABEL.match(text)
        if not match:
            raise ValueError(f"invalid week (use YYYY-Www): {text!r}")
        return cls(int(match.group(1)), int(match.group(2)))

    @classmethod
    def containing(cls, day: date) -> IsoWeek:
        year, number, _ = day.isocalendar()
        return cls(year, number)

    @classmethod
    def before(cls, day: date) -> IsoWeek:
        """The week before the one containing ``day``."""
        return cls.containing(day - timedelta(days=DAYS_PER_WEEK))

    @property
    def start(self) -> date:
        return date.fromisocalendar(self.year, self.number, 1)

    @property
    def end(self) -> date:
        return self.start + timedelta(days=DAYS_PER_WEEK - 1)

    @property
    def label(self) -> str:
        return f"{self.year}-W{self.number:02d}"

    def days(self) -> list[date]:
        return [self.start + timedelta(days=offset) for offset in range(DAYS_PER_WEEK)]

    def previous(self) -> IsoWeek:
        return IsoWeek.before(self.start)
