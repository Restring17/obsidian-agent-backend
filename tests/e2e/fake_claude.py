"""Stand-in for ``claude -p`` in end-to-end tests.

It writes the report to the only path the command allows (``Write(./<path>)``) and logs
its argv to ``$OAB_FAKE_LOG``. ``$OAB_FAKE_CLAUDE`` picks the behaviour:

- ``ok`` (default): a valid report;
- ``evil``: a valid report plus an edit to a human note, which must be rejected;
- ``invalid``: a report without the required frontmatter.
"""

import json
import os
import re
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    with Path(os.environ["OAB_FAKE_LOG"]).open("a", encoding="utf-8") as log:
        log.write(json.dumps(["claude", *argv]) + "\n")
    prompt = argv[argv.index("-p") + 1]
    target = next(arg for arg in argv if arg.startswith("Write(./"))[len("Write(./") : -1]
    week = re.search(r"^week: (\d{4}-W\d{2})$", prompt, re.MULTILINE)
    assert week, "the prompt must tell the agent which week to write"
    mode = os.environ.get("OAB_FAKE_CLAUDE", "ok")
    frontmatter = (
        f'---\ntype: agent\nweek: {week.group(1)}\nsummary: "Steady week."\n---\n'
        if mode != "invalid"
        else "---\ntype: draft\n---\n"
    )
    Path(target).write_text(frontmatter + f"# Weekly review {week.group(1)}\n", encoding="utf-8")
    if mode == "evil":
        with Path("Projects/Weather API.md").open("a", encoding="utf-8") as note:
            note.write("- [x] Done by the agent without asking\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
