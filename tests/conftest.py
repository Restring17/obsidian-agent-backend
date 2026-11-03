import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

type Git = Callable[..., str]


@pytest.fixture
def git() -> Git:
    """Run git in a repo with a fixed identity and no user or system config."""
    executable = shutil.which("git")
    assert executable

    def run(repo: Path, *args: str, when: str | None = None) -> str:
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
        if when:
            env |= {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        result = subprocess.run(  # noqa: S603
            [executable, "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
            cwd=repo,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    return run
