"""Console entry points.

Both commands are stubs until the collector (#4) and the review agent (#5) land.
"""

import argparse
import sys
from collections.abc import Sequence

from obsidian_agent_backend import __version__

EXIT_NOT_IMPLEMENTED = 2


def _build_parser(prog: str, description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _run_stub(prog: str, description: str, argv: Sequence[str] | None) -> int:
    _build_parser(prog, description).parse_args(argv)
    print(f"{prog}: not implemented yet", file=sys.stderr)
    return EXIT_NOT_IMPLEMENTED


def collect_main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``oab-collect``: write daily metrics to the daily note."""
    return _run_stub("oab-collect", "Collect daily metrics into the vault.", argv)


def review_main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``oab-review``: run the least-privilege weekly review."""
    return _run_stub("oab-review", "Write the weekly review with a least-privilege agent.", argv)
