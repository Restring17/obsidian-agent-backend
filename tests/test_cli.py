from collections.abc import Callable
from pathlib import Path

import pytest

from obsidian_agent_backend import __version__, cli

EntryPoint = Callable[[list[str] | None], int]

COMMANDS: list[tuple[str, EntryPoint]] = [
    ("oab-collect", cli.collect_main),
    ("oab-review", cli.review_main),
]


@pytest.mark.parametrize(("prog", "entry"), COMMANDS)
def test_stub_reports_not_implemented(
    prog: str, entry: EntryPoint, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "oab.toml"
    config.write_text("", encoding="utf-8")
    assert entry(["--config", str(config)]) == cli.EXIT_NOT_IMPLEMENTED
    assert capsys.readouterr().err == f"{prog}: not implemented yet\n"


@pytest.mark.parametrize(("prog", "entry"), COMMANDS)
def test_default_config_is_read_from_working_directory(
    prog: str,
    entry: EntryPoint,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    assert entry([]) == cli.EXIT_CONFIG_ERROR
    assert capsys.readouterr().err == f"{prog}: error: config file not found: oab.toml\n"
    (tmp_path / "oab.toml").write_text("", encoding="utf-8")
    assert entry([]) == cli.EXIT_NOT_IMPLEMENTED


@pytest.mark.parametrize(("prog", "entry"), COMMANDS)
def test_invalid_config_fails_fast_with_exit_code_2(
    prog: str, entry: EntryPoint, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "oab.toml"
    config.write_text('timezone = "Mars/Olympus"\n', encoding="utf-8")
    assert entry(["--config", str(config)]) == 2
    err = capsys.readouterr().err
    assert err == f"{prog}: error: {config}: timezone: unknown IANA timezone 'Mars/Olympus'\n"
    assert "Traceback" not in err


@pytest.mark.parametrize(("prog", "entry"), COMMANDS)
def test_version_flag_prints_version(
    prog: str, entry: EntryPoint, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        entry(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out == f"{prog} {__version__}\n"


@pytest.mark.parametrize(("prog", "entry"), COMMANDS)
def test_unknown_argument_is_rejected(
    prog: str, entry: EntryPoint, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        entry(["--bogus"])
    assert exc.value.code == 2
    assert prog in capsys.readouterr().err


def test_version_is_a_non_empty_string() -> None:
    assert isinstance(__version__, str)
    assert __version__
