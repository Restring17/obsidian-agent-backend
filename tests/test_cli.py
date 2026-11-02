from collections.abc import Callable

import pytest

from obsidian_agent_backend import __version__, cli

EntryPoint = Callable[[list[str] | None], int]

COMMANDS: list[tuple[str, EntryPoint]] = [
    ("oab-collect", cli.collect_main),
    ("oab-review", cli.review_main),
]


@pytest.mark.parametrize(("prog", "entry"), COMMANDS)
def test_stub_reports_not_implemented(
    prog: str, entry: EntryPoint, capsys: pytest.CaptureFixture[str]
) -> None:
    assert entry([]) == cli.EXIT_NOT_IMPLEMENTED
    assert capsys.readouterr().err == f"{prog}: not implemented yet\n"


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
