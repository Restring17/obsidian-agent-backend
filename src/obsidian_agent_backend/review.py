"""Weekly review under least privilege: data, agent, verification, log and commit.

The model only writes prose. It runs through ``claude -p`` with read-only tools plus
Write/Edit on one path, and no shell or web access. Afterwards git is the source of
truth: if anything other than the report changed, the run is rejected and nothing is
committed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from importlib.resources import files
from pathlib import Path, PurePosixPath
from string import Template
from typing import TextIO

from obsidian_agent_backend.config import Config, ConfigError
from obsidian_agent_backend.daily_note import DailyNote, NoteError, read_frontmatter
from obsidian_agent_backend.domain import SourceError
from obsidian_agent_backend.sources import Runner
from obsidian_agent_backend.week import IsoWeek
from obsidian_agent_backend.weekly_context import WeeklyContext

AGENT_TIMEOUT = 15 * 60  # seconds
MAX_TURNS = 40
REPORTS_FOLDER = "Reports"
READ_ONLY_TOOLS = ("Read", "Glob", "Grep")
DISALLOWED_TOOLS = ("Bash", "WebFetch", "WebSearch", "NotebookEdit", "Task", "Agent")
DEFAULT_TEMPLATE = files("obsidian_agent_backend").joinpath("prompts/weekly_review.md")

EXIT_OK = 0
EXIT_FAILED = 1

type Snapshot = dict[str, str | None]


class ReviewError(Exception):
    """The agent did not produce a valid report or touched something it should not."""


def report_path(config: Config, week: IsoWeek, test: bool) -> PurePosixPath:
    suffix = " (test)" if test else ""
    return config.agent.folder / REPORTS_FOLDER / f"{week.label} Weekly review{suffix}.md"


def load_template(config: Config) -> str:
    custom = config.review.prompt
    try:
        if custom is None:
            return DEFAULT_TEMPLATE.read_text(encoding="utf-8")
        return config.resolve(custom).read_text(encoding="utf-8")
    except (ConfigError, OSError, UnicodeError):
        raise ReviewError(f"cannot read the prompt template {custom}") from None


@dataclass(frozen=True, slots=True)
class PromptInputs:
    report: PurePosixPath
    week: IsoWeek
    today: date
    previous: PurePosixPath | None
    data: str


def build_prompt(template: str, inputs: PromptInputs) -> str:
    previous = inputs.previous
    hint = (
        f"5. For continuity, read the previous report: `{previous.as_posix()}` "
        "(were its open items addressed?)."
        if previous
        else ""
    )
    try:
        return Template(template).substitute(
            report_path=inputs.report.as_posix(),
            week=inputs.week.label,
            start=inputs.week.start.isoformat(),
            end=inputs.week.end.isoformat(),
            today=inputs.today.isoformat(),
            previous_report=hint,
            data=inputs.data,
        )
    except KeyError as exc:
        raise ReviewError(f"prompt template: unknown placeholder ${exc.args[0]}") from None
    except ValueError as exc:
        raise ReviewError(f"prompt template: {exc} (write $$ for a literal $)") from None


def claude_command(prompt: str, report: PurePosixPath, model: str) -> list[str]:
    """``claude -p`` that can read the vault and write exactly one file."""
    target = f"./{report.as_posix()}"
    return [
        "claude", "-p", prompt,
        "--model", model,
        "--max-turns", str(MAX_TURNS),
        "--allowedTools", *READ_ONLY_TOOLS, f"Write({target})", f"Edit({target})",
        "--disallowedTools", *DISALLOWED_TOOLS,
    ]  # fmt: skip


def changed_paths(vault: Path, runner: Runner) -> set[str]:
    """Paths with changes, untracked included. ``-z`` avoids any quoting ambiguity."""
    output = runner(["git", "status", "--porcelain", "-z", "--untracked-files=all"], vault)
    tokens = output.split("\0")
    paths, index = set(), 0
    while index < len(tokens):
        entry = tokens[index]
        index += 1
        if len(entry) < 4:  # noqa: PLR2004 ("XY " plus at least one character)
            continue
        paths.add(entry[3:])
        if entry[0] in "RC":
            index += 1  # the next token is the source path of a rename or copy
    return paths


def _digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (FileNotFoundError, IsADirectoryError):
        return None


def snapshot(vault: Path, runner: Runner) -> Snapshot:
    """Content hash of every changed path, so later edits to dirty files are visible too."""
    return {path: _digest(vault / path) for path in changed_paths(vault, runner)}


def touched_since(vault: Path, runner: Runner, before: Snapshot) -> set[str]:
    """Paths whose content differs from ``before`` (new changes or edits to dirty files)."""
    candidates = changed_paths(vault, runner) | set(before)
    return {
        path for path in candidates if path not in before or _digest(vault / path) != before[path]
    }


def validate_report(path: Path, week: IsoWeek) -> None:
    if not path.is_file():
        raise ReviewError(f"the agent did not create {path.name}")
    try:
        data = read_frontmatter(path.read_text(encoding="utf-8"))
    except UnicodeError:
        raise ReviewError(f"{path.name} is not valid UTF-8") from None
    summary = data.get("summary")
    if data.get("type") != "agent" or str(data.get("week")) != week.label:
        raise ReviewError("the report frontmatter must have type: agent and the right week")
    if not isinstance(summary, str) or not summary.strip():
        raise ReviewError("the report frontmatter must have a non-empty summary")


@dataclass(frozen=True, slots=True)
class ReviewOptions:
    model: str
    test: bool = False
    force: bool = False
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class WeeklyReview:
    config: Config
    runner: Runner
    agent_runner: Runner
    out: TextIO
    err: TextIO

    def _previous(self, week: IsoWeek) -> PurePosixPath | None:
        previous = report_path(self.config, week.previous(), test=False)
        return previous if (self.config.vault / previous).is_file() else None

    def prompt(self, week: IsoWeek, today: date, report: PurePosixPath) -> str:
        inputs = PromptInputs(
            report=report,
            week=week,
            today=today,
            previous=self._previous(week),
            data=WeeklyContext(self.config, self.runner).build(week),
        )
        return build_prompt(load_template(self.config), inputs)

    def _run_agent(self, prompt: str, report: PurePosixPath, model: str, week: IsoWeek) -> None:
        vault = self.config.vault
        target = self.config.resolve(report)
        target.parent.mkdir(parents=True, exist_ok=True)
        before = snapshot(vault, self.runner)
        self.agent_runner(claude_command(prompt, report, model), vault)
        outside = touched_since(vault, self.runner, before) - {report.as_posix()}
        if outside:
            raise ReviewError(
                "the agent changed files outside its report: " + ", ".join(sorted(outside))
            )
        validate_report(target, week)

    def _publish(self, report: PurePosixPath, week: IsoWeek) -> bool:
        """Commit only the report and the daily notes, then sync if there is an upstream."""
        vault, run = self.config.vault, self.runner
        paths = [report.as_posix(), self.config.daily_notes.folder.as_posix()]
        run(["git", "add", "--", *paths], vault)
        if not run(["git", "diff", "--cached", "--name-only", "--", *paths], vault).strip():
            return True
        message = f"docs: weekly review {week.label}\n\nWritten by oab-review (claude -p)."
        run(["git", "commit", "-q", "-m", message, "--", *paths], vault)
        try:
            run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], vault)
        except SourceError:
            print("no upstream branch: the commit stays local", file=self.out)
            return True
        try:
            run(["git", "pull", "-q", "--rebase", "--autostash"], vault)
            run(["git", "push", "-q"], vault)
        except SourceError as exc:
            print(f"committed locally, but could not sync: {exc}", file=self.err)
            return False
        return True

    def run(self, week: IsoWeek, today: date, options: ReviewOptions) -> int:
        report = report_path(self.config, week, options.test)
        try:
            if (self.config.vault / report).exists() and not (options.force or options.dry_run):
                print(f"{report.name} already exists (use --force to redo it)", file=self.out)
                return EXIT_OK
            prompt = self.prompt(week, today, report)
            if options.dry_run:
                print(prompt, file=self.out)
                return EXIT_OK
            self._run_agent(prompt, report, options.model, week)
        except (ReviewError, SourceError, ConfigError) as exc:
            print(f"review {week.label}: {exc}", file=self.err)
            return EXIT_FAILED
        print(f"report written: {report}", file=self.out)
        if options.test:
            return EXIT_OK
        try:
            DailyNote(self.config).log(today, f"- [oab-review] {week.label} → [[{report.stem}]]")
            return EXIT_OK if self._publish(report, week) else EXIT_FAILED
        except (NoteError, OSError, SourceError) as exc:
            print(f"report written, but logging or committing failed: {exc}", file=self.err)
            return EXIT_FAILED
