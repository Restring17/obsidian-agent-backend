"""Daily collection use case: ask every source for each day and write the daily note."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol, TextIO

from obsidian_agent_backend.daily_note import NoteError
from obsidian_agent_backend.domain import Metrics, SourceError

EXIT_OK = 0
EXIT_PARTIAL_FAILURE = 1


class DaySource(Protocol):
    def collect(self, day: date) -> Metrics: ...


class SnapshotSource(Protocol):
    def collect(self, day: date, snapshots: bool) -> Metrics: ...


class NoteWriter(Protocol):
    def exists(self, day: date) -> bool: ...

    def update(self, day: date, metrics: Metrics, collected_at: str) -> Path: ...


@dataclass(frozen=True, slots=True)
class Collector:
    github: DaySource | None
    vault: SnapshotSource
    note: NoteWriter
    out: TextIO
    err: TextIO

    def _gather(self, day: date, today: date) -> tuple[Metrics, bool]:
        """Merge every source that succeeds; a failing source contributes nothing."""
        snapshots = day >= today - timedelta(days=1)
        sources: list[tuple[str, Callable[[], Metrics]]] = []
        if self.github is not None:
            github = self.github
            sources.append(("GitHub", lambda: github.collect(day)))
        sources.append(("vault", lambda: self.vault.collect(day, snapshots)))
        metrics, failed = Metrics(), False
        for name, fetch in sources:
            try:
                metrics = metrics.merge(fetch())
            except SourceError as exc:
                failed = True
                print(f"{day} {name}: {exc} (its metrics are not written)", file=self.err)
        return metrics, failed

    def run(self, days: Sequence[date], today: date, collected_at: str, dry_run: bool) -> int:
        failed = False
        for day in days:
            metrics, source_failed = self._gather(day, today)
            failed |= source_failed
            if not metrics.values:
                continue
            try:
                exists = self.note.exists(day)
            except NoteError as exc:
                failed = True
                print(f"{day}: {exc}", file=self.err)
                continue
            if not (exists or metrics.has_activity()):
                print(f"{day}: no activity, no note created", file=self.out)
                continue
            if dry_run:
                print(f"{day} (dry run): {metrics.summary()}", file=self.out)
                continue
            try:
                path = self.note.update(day, metrics, collected_at)
            except (NoteError, OSError) as exc:
                failed = True
                print(f"{day}: cannot write the note: {exc}", file=self.err)
                continue
            print(f"{day}: {metrics.summary()} -> {path.name}", file=self.out)
        return EXIT_PARTIAL_FAILURE if failed else EXIT_OK
