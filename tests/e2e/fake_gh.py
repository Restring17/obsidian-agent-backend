"""Stand-in for the ``gh`` CLI in end-to-end tests.

It answers the three calls the collector makes (login, commit search, PR search) with
canned data, appends every call to ``$OAB_FAKE_LOG`` and fails when ``$OAB_FAKE_GH=fail``.
"""

import json
import os
import sys
from pathlib import Path

LOGIN = "example-user"
COMMITS = [
    {"repository": {"full_name": "example-user/weather-api"}},
    {"repository": {"full_name": "example-user/weather-api"}},
    {"repository": {"full_name": "example-user/portfolio"}},
]


def main(argv: list[str]) -> int:
    with Path(os.environ["OAB_FAKE_LOG"]).open("a", encoding="utf-8") as log:
        log.write(json.dumps(["gh", *argv]) + "\n")
    if os.environ.get("OAB_FAKE_GH") == "fail":
        print("gh: authentication required", file=sys.stderr)
        return 4
    if argv[:2] == ["api", "user"]:
        print(LOGIN)
        return 0
    if "search/commits" in argv:
        print(json.dumps({"total_count": len(COMMITS), "items": COMMITS}))
        return 0
    if "search/issues" in argv:
        print(json.dumps({"total_count": 1, "items": [{"number": 7}]}))
        return 0
    print(f"fake gh: unexpected call {argv}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
