"""Console entry points.

Both commands load and validate the config, then stop: the collector (#4) and the
review agent (#5) are not implemented yet.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from obsidian_agent_backend import __version__
from obsidian_agent_backend.config import DEFAULT_CONFIG_NAME, ConfigError, load_config

EXIT_CONFIG_ERROR = 2
EXIT_NOT_IMPLEMENTED = 3


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


def _run_stub(prog: str, description: str, argv: Sequence[str] | None) -> int:
    args = _build_parser(prog, description).parse_args(argv)
    try:
        load_config(args.config)
    except ConfigError as exc:
        print(f"{prog}: error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    print(f"{prog}: not implemented yet", file=sys.stderr)
    return EXIT_NOT_IMPLEMENTED


def collect_main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``oab-collect``: write daily metrics to the daily note."""
    return _run_stub("oab-collect", "Collect daily metrics into the vault.", argv)


def review_main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``oab-review``: run the least-privilege weekly review."""
    return _run_stub("oab-review", "Write the weekly review with a least-privilege agent.", argv)
