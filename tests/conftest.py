import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

type Git = Callable[..., str]


def pytest_configure(config: pytest.Config) -> None:
    """A run filtered by marker (``-m e2e``) checks behaviour, not coverage.

    The 90 % branch threshold applies to the full suite; a subset cannot meet it.
    """
    coverage = config.pluginmanager.getplugin("_cov")  # pytest-cov keeps its own options
    if config.option.markexpr and coverage is not None:
        coverage.options.cov_fail_under = 0


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every git process in the tests, the tool's included, ignores the user's config.

    CI runners have no git identity, so local runs must not depend on ~/.gitconfig either.

    mutmut runs the suite from ``mutants/`` inside this repository. A mutant that drops
    the vault ``cwd`` would then commit to the project's own branch, so git must not look
    above the folder that holds ``tests/`` (the ceiling is that folder's parent).
    """
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(Path(__file__).resolve().parents[2]))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "t")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "t@example.com")


BLOCKED_AGENT_EXIT = 97


@pytest.fixture(autouse=True)
def no_real_agent(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """A ``claude`` that always fails comes first on PATH, so no test can call the model.

    The tests never reach the real agent on purpose, but a mutant that disables a guard
    (``--dry-run``, the week check) would fall through to ``claude`` on the developer's
    PATH: a real agent spending tokens. The e2e fixture prepends its own fake later, so
    it still wins there.
    """
    bin_dir = tmp_path_factory.mktemp("blocked-agent")
    blocker = bin_dir / "claude"
    blocker.write_text(
        "#!/bin/sh\n"
        "echo 'the real claude CLI is blocked in the test suite' >&2\n"
        f"exit {BLOCKED_AGENT_EXIT}\n",
        encoding="utf-8",
    )
    blocker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return blocker


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
