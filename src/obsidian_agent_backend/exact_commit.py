"""Commit exact file contents on top of HEAD without touching the user's files.

``git commit -- <paths>`` commits whatever the working tree holds, so a user's unfinished
edit to the same file would go in too. Here the commit is built from a temporary index
(``read-tree HEAD`` plus our blobs), so the working tree and the user's staged changes are
never used, and HEAD only moves if nobody moved it meanwhile (``update-ref`` with the old
value). Every command goes through the injected runner; ``env`` sets ``GIT_INDEX_FILE``
because the runner takes no environment.
"""

import tempfile
from collections.abc import Mapping
from pathlib import Path

from obsidian_agent_backend.sources import Runner

MODE = "100644"  # vault notes are regular files


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


def head_text(vault: Path, runner: Runner, path: str) -> str | None:
    """The text of ``path`` at HEAD, or None when HEAD does not track it."""
    if not runner(["git", "ls-tree", "--name-only", "HEAD", "--", path], vault).strip():
        return None
    return runner(["git", "show", f"HEAD:{path}"], vault)


def index_text(vault: Path, runner: Runner, path: str) -> str | None:
    """The text of ``path`` in the user's index, or None when it is not there."""
    if not runner(["git", "ls-files", "--", path], vault).strip():
        return None
    return runner(["git", "show", f":{path}"], vault)


def has_staged_changes(vault: Path, runner: Runner, path: str) -> bool:
    return bool(runner(["git", "diff", "--cached", "--name-only", "--", path], vault).strip())


def write_blob(vault: Path, runner: Runner, path: str, text: str) -> str:
    """Store ``text`` as the content of ``path`` (with its git filters) and return the id."""
    with tempfile.TemporaryDirectory(prefix="oab-blob-") as tmp:
        source = Path(tmp) / "blob"
        source.write_text(text, encoding="utf-8", newline="")
        command = ["git", "hash-object", "-w", "--path", path, str(source)]
        return runner(command, vault).strip()


def stage(vault: Path, runner: Runner, path: str, blob: str) -> None:
    """Point the user's index entry for ``path`` at ``blob``."""
    runner(["git", "update-index", "--add", "--cacheinfo", f"{MODE},{blob},{path}"], vault)


def commit_exact(vault: Path, runner: Runner, blobs: Mapping[str, str], message: str) -> bool:
    """Commit HEAD with ``blobs`` (path → blob id) replaced. False if nothing changed."""
    head = runner(["git", "rev-parse", "HEAD"], vault).strip()
    with tempfile.TemporaryDirectory(prefix="oab-index-") as tmp:
        index = ["env", f"GIT_INDEX_FILE={Path(tmp) / 'index'}"]
        runner([*index, "git", "read-tree", head], vault)
        for path, blob in blobs.items():
            cacheinfo = f"{MODE},{blob},{path}"
            runner([*index, "git", "update-index", "--add", "--cacheinfo", cacheinfo], vault)
        tree = runner([*index, "git", "write-tree"], vault).strip()
    if tree == runner(["git", "rev-parse", f"{head}^{{tree}}"], vault).strip():
        return False
    commit = runner(["git", "commit-tree", tree, "-p", head, "-m", message], vault).strip()
    subject = message.splitlines()[0]
    runner(["git", "update-ref", "-m", f"commit: {subject}", "HEAD", commit, head], vault)
    return True
