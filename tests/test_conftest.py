import shutil
import subprocess
from pathlib import Path


def test_claude_on_path_is_the_blocker(no_real_agent: Path) -> None:
    assert shutil.which("claude") == str(no_real_agent)
    cmd = [str(no_real_agent), "-p", "hi"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    assert result.returncode == 97  # BLOCKED_AGENT_EXIT in conftest.py
    assert "blocked in the test suite" in result.stderr
