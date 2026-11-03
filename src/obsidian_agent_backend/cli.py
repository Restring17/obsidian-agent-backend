"""Console entry points.

Exit codes: 0 success, 1 a source, the agent, a write or systemd failed, 2 invalid
arguments or config.
"""

import argparse
import shutil
import sys
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

from obsidian_agent_backend import __version__
from obsidian_agent_backend.collector import Collector
from obsidian_agent_backend.config import (
    DEFAULT_CONFIG_NAME,
    MODEL_NAME,
    Config,
    ConfigError,
    load_config,
)
from obsidian_agent_backend.daily_note import DailyNote
from obsidian_agent_backend.review import AGENT_TIMEOUT, ReviewOptions, WeeklyReview
from obsidian_agent_backend.sources import GitHubSource, Runner, VaultSource, run
from obsidian_agent_backend.timers import (
    DEFAULT_COLLECT_AT,
    DEFAULT_REVIEW_AT,
    TIMERS,
    Schedule,
    TimerError,
    Which,
    calendar,
    find_command,
    install,
    render,
    search_path,
    uninstall,
    unit_folder,
)
from obsidian_agent_backend.week import IsoWeek

EXIT_CONFIG_ERROR = 2
MAX_DAYS = 31


def _build_parser(prog: str, description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(DEFAULT_CONFIG_NAME),
        metavar="PATH",
        help=f"config file at the vault root (default: ./{DEFAULT_CONFIG_NAME})",
    )
    return parser


def _load(prog: str, path: Path) -> Config | None:
    try:
        return load_config(path)
    except ConfigError as exc:
        print(f"{prog}: error: {exc}", file=sys.stderr)
        return None


def iso_date(text: str) -> date:
    # Length check: fromisoformat also accepts compact forms such as 20261102.
    if len(text) == len("YYYY-MM-DD"):
        try:
            return date.fromisoformat(text)
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(f"invalid date (use YYYY-MM-DD): {text!r}")


def day_count(text: str) -> int:
    if not text.isascii() or not text.isdigit() or not 1 <= int(text) <= MAX_DAYS:
        raise argparse.ArgumentTypeError(f"must be an integer between 1 and {MAX_DAYS}")
    return int(text)


def collect_main(argv: Sequence[str] | None = None, now: datetime | None = None) -> int:
    """Entry point for ``oab-collect``: write daily metrics to the daily note."""
    prog = "oab-collect"
    parser = _build_parser(prog, "Write exact daily metrics to the daily note frontmatter.")
    parser.add_argument("--date", type=iso_date, help="day to collect (default: yesterday)")
    parser.add_argument(
        "--days",
        type=day_count,
        default=1,
        metavar="N",
        help=f"also collect the N-1 previous days (1-{MAX_DAYS}, default 1)",
    )
    parser.add_argument("--no-github", action="store_true", help="do not query GitHub")
    parser.add_argument("--dry-run", action="store_true", help="print metrics, write nothing")
    args = parser.parse_args(argv)

    config = _load(prog, args.config)
    if config is None:
        return EXIT_CONFIG_ERROR
    current = (now or datetime.now(config.timezone)).astimezone(config.timezone)
    today = current.date()
    last: date = args.date or today - timedelta(days=1)
    if last > today:
        print(f"{prog}: error: --date cannot be in the future ({last} > {today})", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    collector = Collector(
        github=None if args.no_github else GitHubSource(config.timezone),
        vault=VaultSource(config),
        note=DailyNote(config),
        out=sys.stdout,
        err=sys.stderr,
    )
    days = [last - timedelta(days=offset) for offset in range(args.days)]
    return collector.run(days, today, current.strftime("%Y-%m-%dT%H:%M"), args.dry_run)


def iso_week(text: str) -> IsoWeek:
    try:
        return IsoWeek.parse(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def model_name(text: str) -> str:
    if not MODEL_NAME.match(text):
        raise argparse.ArgumentTypeError(f"invalid model name: {text!r}")
    return text


def _agent_runner(cmd: Sequence[str], cwd: Path | None) -> str:
    return run(cmd, cwd, timeout=AGENT_TIMEOUT)


def review_main(
    argv: Sequence[str] | None = None,
    now: datetime | None = None,
    agent_runner: Runner = _agent_runner,
    runner: Runner = run,
) -> int:
    """Entry point for ``oab-review``: run the least-privilege weekly review."""
    prog = "oab-review"
    parser = _build_parser(prog, "Write the weekly review with a least-privilege agent.")
    parser.add_argument("--week", type=iso_week, help="ISO week YYYY-Www (default: last week)")
    parser.add_argument("--model", type=model_name, help="override review.model")
    parser.add_argument(
        "--test", action="store_true", help="write a '(test)' report, no log or commit"
    )
    parser.add_argument("--force", action="store_true", help="redo the report if it exists")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the prompt without calling the model"
    )
    args = parser.parse_args(argv)

    config = _load(prog, args.config)
    if config is None:
        return EXIT_CONFIG_ERROR
    today = (now or datetime.now(config.timezone)).astimezone(config.timezone).date()
    week: IsoWeek = args.week or IsoWeek.before(today)
    if week.start > today:
        print(f"{prog}: error: week {week.label} has not started yet", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    review = WeeklyReview(config, runner, agent_runner, sys.stdout, sys.stderr)
    options = ReviewOptions(
        model=args.model or config.review.model,
        test=args.test,
        force=args.force,
        dry_run=args.dry_run,
    )
    return review.run(week, today, options)


def on_calendar(text: str) -> str:
    try:
        return calendar(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def timers_main(
    argv: Sequence[str] | None = None, runner: Runner = run, which: Which = shutil.which
) -> int:
    """Entry point for ``oab-timers``: schedule both commands with systemd user timers."""
    prog = "oab-timers"
    parser = _build_parser(
        prog, "Run the collector every day and the review every week with systemd user timers."
    )
    parser.add_argument(
        "action",
        choices=("print", "install", "uninstall"),
        help="print the units, install and enable them, or disable and remove them",
    )
    parser.add_argument(
        "--collect-at",
        type=on_calendar,
        default=DEFAULT_COLLECT_AT,
        metavar="CALENDAR",
        help=f"when to collect, in the vault timezone (default: {DEFAULT_COLLECT_AT!r})",
    )
    parser.add_argument(
        "--review-at",
        type=on_calendar,
        default=DEFAULT_REVIEW_AT,
        metavar="CALENDAR",
        help=f"when to review, in the vault timezone (default: {DEFAULT_REVIEW_AT!r})",
    )
    parser.add_argument(
        "--no-github", action="store_true", help="the daily collector does not query GitHub"
    )
    parser.add_argument(
        "--force", action="store_true", help="replace unit files not written by oab-timers"
    )
    args = parser.parse_args(argv)

    folder = unit_folder()
    try:
        if args.action == "uninstall":
            removed, kept = uninstall(folder, runner)
            for path in removed:
                print(f"removed {path}")
            for path in kept:
                print(f"kept {path} (not written by oab-timers)", file=sys.stderr)
            return 0
        config = _load(prog, args.config)
        if config is None:
            return EXIT_CONFIG_ERROR
        collect, review = find_command("oab-collect", which), find_command("oab-review", which)
        timezone = config.timezone.key
        schedule = Schedule(
            config=args.config.resolve(),
            collect=collect,
            review=review,
            path=search_path([collect, review], which),
            collect_at=f"{args.collect_at} {timezone}",
            review_at=f"{args.review_at} {timezone}",
            github=not args.no_github,
        )
        units = render(schedule)
        if args.action == "print":
            for name, text in units.items():
                print(f"# --- {folder / name} ---\n{text}")
            return 0
        for path in install(units, folder, runner, force=args.force):
            print(f"wrote {path}")
        print(f"enabled {' and '.join(TIMERS)}; next runs: systemctl --user list-timers 'oab-*'")
    except TimerError as exc:
        print(f"{prog}: error: {exc}", file=sys.stderr)
        return 1
    return 0
