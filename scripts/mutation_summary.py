"""Markdown summary of a mutmut run, for the GitHub job summary.

Usage: mutation_summary.py STATS_JSON RESULTS_TXT REVIEWED_MD

STATS_JSON is ``mutmut export-cicd-stats`` output, RESULTS_TXT is ``mutmut results`` output
and REVIEWED_MD documents the survivors already reviewed (docs/mutation-testing.md). A
survivor whose name is not in that document is listed as not reviewed yet.
"""

import json
import sys
from pathlib import Path

DOC = "docs/mutation-testing.md"
NOT_FINISHED = "## Mutation testing\n\nmutmut did not finish: no results to report.\n"


def survivors(results: str) -> list[str]:
    return sorted(
        line.split(":")[0].strip()
        for line in results.splitlines()
        if line.strip().endswith(": survived")
    )


def summary(stats: dict[str, int], results: str, reviewed: str) -> str:
    caught = stats["killed"] + stats["timeout"]
    judged = caught + stats["survived"] + stats["suspicious"]
    if not judged:  # e.g. the clean test run failed, so no mutant was tested
        return NOT_FINISHED
    score = f"{caught / judged:.1%}"
    names = survivors(results)
    new = [name for name in names if name not in reviewed]
    lines = [
        "## Mutation testing",
        "",
        "| Mutants | Killed | Timeout | Survived | Suspicious | No tests | Score |",
        "|---|---|---|---|---|---|---|",
        f"| {stats['total']} | {stats['killed']} | {stats['timeout']} | {stats['survived']} "
        f"| {stats['suspicious']} | {stats['no_tests']} | **{score}** |",
        "",
        f"{len(names)} survivors, **{len(new)} not reviewed yet** (reviewed ones: `{DOC}`).",
    ]
    if new:
        lines += ["", "<details><summary>Not reviewed yet</summary>", "", "```"]
        lines += [*new, "```", "", "</details>"]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    stats_path, results_path, reviewed_path = (Path(arg) for arg in argv)
    if not stats_path.is_file():
        print(NOT_FINISHED, end="")
        return 0
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    results = results_path.read_text(encoding="utf-8") if results_path.is_file() else ""
    print(summary(stats, results, reviewed_path.read_text(encoding="utf-8")), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
