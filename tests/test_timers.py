import shutil
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from obsidian_agent_backend import cli, timers
from obsidian_agent_backend.domain import SourceError
from obsidian_agent_backend.sources import run
from obsidian_agent_backend.timers import (
    MARKER,
    UNITS,
    Schedule,
    TimerError,
    calendar,
    find_command,
    install,
    quote,
    render,
    search_path,
    uninstall,
    unit_folder,
    verify,
)

BIN = Path("/opt/oab/bin")
SCHEDULE = Schedule(
    config=Path("/home/me/My Vault/oab.toml"),
    collect=BIN / "oab-collect",
    review=BIN / "oab-review",
    path=("/opt/oab/bin", "/usr/bin"),
    collect_at="*-*-* 09:00 America/Lima",
    review_at="Mon *-*-* 09:30 America/Lima",
)
CONFIG = 'timezone = "America/Lima"\n'


class FakeRunner:
    """Records commands; fails those whose first words match ``fail``."""

    def __init__(self, *fail: str) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    def __call__(self, cmd: Sequence[str], cwd: Path | None) -> str:
        self.calls.append(list(cmd))
        if any(" ".join(cmd).startswith(prefix) for prefix in self.fail):
            raise SourceError(f"{cmd[0]} exited with code 1")
        return ""


def which_in(folder: Path) -> timers.Which:
    def which(name: str) -> str | None:
        return str(folder / name) if name in {"oab-collect", "oab-review", "git"} else None

    return which


# --- validation and quoting ------------------------------------------------------


@pytest.mark.parametrize("text", ["*-*-* 09:00", "Mon *-*-* 09:30", "Mon..Fri 08:00", "daily"])
def test_calendar_accepts_systemd_expressions(text: str) -> None:
    assert calendar(text) == text


@pytest.mark.parametrize("text", ["", "09:00\nExecStart=/bin/sh", "a;b", "$HOME", "x" * 65])
def test_calendar_rejects_anything_that_could_inject_settings(text: str) -> None:
    with pytest.raises(ValueError, match=r"^invalid calendar expression: "):
        calendar(text)


def test_quote_escapes_specifiers_and_quotes() -> None:
    assert quote('/a b/100%/$HOME/"x"\\') == '"/a b/100%%/$HOME/\\"x\\"\\\\"'


def test_quote_escapes_variables_where_systemd_expands_them() -> None:
    assert quote("/a/$HOME/%n", expands_variables=True) == '"/a/$$HOME/%%n"'


@pytest.mark.parametrize("text", ["a\nb", "a\rb", "a\0b"])
def test_quote_rejects_line_breaks(text: str) -> None:
    with pytest.raises(TimerError, match=r"^cannot use a line break in a unit file: "):
        quote(text)


def test_quote_accepts_ordinary_text() -> None:
    assert quote("XX0rn") == '"XX0rn"'


# --- finding the executables -----------------------------------------------------


def test_find_command_uses_path_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert find_command("oab-collect", lambda name: f"bin/{name}") == tmp_path / "bin/oab-collect"


def test_find_command_falls_back_to_the_python_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "oab-collect"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    assert find_command("oab-collect", lambda name: None) == exe


def test_find_command_ignores_a_non_executable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "oab-collect").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    with pytest.raises(TimerError) as exc:
        find_command("oab-collect", lambda name: None)
    assert str(exc.value) == "oab-collect not found: install the package first (uv tool install .)"


def test_search_path_puts_our_folders_first_without_duplicates() -> None:
    tools = {"git": "/usr/bin/git", "gh": "/opt/gh/bin/gh", "claude": "/bad:dir/claude"}
    path = search_path([BIN / "oab-collect", BIN / "oab-review"], tools.get)
    assert path == ("/opt/oab/bin", "/usr/bin", "/opt/gh/bin", "/usr/local/bin", "/bin")


# --- rendering -------------------------------------------------------------------


def test_render_writes_the_four_units() -> None:
    units = render(SCHEDULE)
    assert list(units) == list(UNITS)
    assert all(text.startswith(MARKER + "\n") for text in units.values())
    collect = '"/opt/oab/bin/oab-collect" "--config" "/home/me/My Vault/oab.toml"'
    assert f"\nExecStart={collect} --days 3\n" in units["oab-collect.service"]
    assert f"\nExecStartPre=-{collect} --days 8\n" in units["oab-review.service"]
    assert (
        '\nExecStart="/opt/oab/bin/oab-review" "--config" "/home/me/My Vault/oab.toml"\n'
        in units["oab-review.service"]
    )
    for name in ("oab-collect.service", "oab-review.service"):
        assert '\nEnvironment="PATH=/opt/oab/bin:/usr/bin"\n' in units[name]
        assert "\nType=oneshot\n" in units[name]
    assert "\nOnCalendar=*-*-* 09:00 America/Lima\n" in units["oab-collect.timer"]
    assert "\nOnCalendar=Mon *-*-* 09:30 America/Lima\n" in units["oab-review.timer"]
    for name in ("oab-collect.timer", "oab-review.timer"):
        assert "\nPersistent=true\n" in units[name]
        assert "\nWantedBy=timers.target\n" in units[name]
    assert "--no-github" not in "".join(units.values())


def test_render_without_github() -> None:
    units = render(replace(SCHEDULE, github=False))
    assert '"/home/me/My Vault/oab.toml" "--no-github" --days 3\n' in units["oab-collect.service"]
    assert '"/home/me/My Vault/oab.toml" "--no-github" --days 8\n' in units["oab-review.service"]


def test_render_escapes_dollars_only_in_arguments() -> None:
    odd = Path("/home/me/$vault")
    units = render(replace(SCHEDULE, config=odd / "oab.toml", collect=odd / "oab-collect"))
    service = units["oab-collect.service"]
    assert '\nExecStart="/home/me/$vault/oab-collect" "--config" "/home/me/$$vault/oab.toml"' in (
        service
    )


requires_systemd = pytest.mark.skipif(
    shutil.which("systemd-analyze") is None, reason="systemd-analyze is not installed"
)


@requires_systemd
def test_rendered_units_pass_systemd_analyze_verify(tmp_path: Path) -> None:
    # Real executables and a config path with a space, '%' and '$' in it.
    folder = tmp_path / "100% $weird vault"
    folder.mkdir()
    for name in ("oab-collect", "oab-review"):
        (folder / name).write_text("#!/bin/sh\n", encoding="utf-8")
        (folder / name).chmod(0o755)
    schedule = replace(
        SCHEDULE,
        config=folder / "oab.toml",
        collect=folder / "oab-collect",
        review=folder / "oab-review",
    )
    verify(render(schedule), run, user=False)  # system scope: CI has no user session


@requires_systemd
def test_verify_rejects_an_invalid_calendar() -> None:
    broken = replace(SCHEDULE, collect_at="Mon 25:99")
    with pytest.raises(TimerError, match="do not pass systemd-analyze verify"):
        verify(render(broken), run, user=False)


# --- unit folder -----------------------------------------------------------------


def test_unit_folder_follows_xdg_config_home(tmp_path: Path) -> None:
    assert unit_folder({"XDG_CONFIG_HOME": str(tmp_path)}) == tmp_path / "systemd/user"


@pytest.mark.parametrize("environ", [{}, {"XDG_CONFIG_HOME": ""}, {"XDG_CONFIG_HOME": "rel"}])
def test_unit_folder_defaults_to_dot_config(environ: dict[str, str]) -> None:
    assert unit_folder(environ) == Path.home() / ".config/systemd/user"


# --- install and uninstall -------------------------------------------------------


def test_install_verifies_writes_and_enables(tmp_path: Path) -> None:
    runner = FakeRunner()
    folder = tmp_path / "systemd/user"
    written = install(render(SCHEDULE), folder, runner)
    assert written == [folder / name for name in UNITS]
    assert (folder / "oab-review.timer").read_text(encoding="utf-8") == render(SCHEDULE)[
        "oab-review.timer"
    ]
    verify_call, *rest = runner.calls
    assert verify_call[:3] == ["systemd-analyze", "--user", "verify"]
    assert [Path(arg).name for arg in verify_call[3:]] == list(UNITS)
    assert all(Path(arg).parent.name.startswith("oab-units-") for arg in verify_call[3:])
    assert rest == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", "--now", "oab-collect.timer", "oab-review.timer"],
    ]


def test_install_replaces_its_own_units(tmp_path: Path) -> None:
    (tmp_path / "oab-collect.timer").write_text(MARKER + "\nold\n", encoding="utf-8")
    install(render(SCHEDULE), tmp_path, FakeRunner())
    assert "old" not in (tmp_path / "oab-collect.timer").read_text(encoding="utf-8")


@pytest.mark.parametrize("content", [b"[Timer]\nOnCalendar=daily\n", b"\xff"])
def test_install_refuses_foreign_units_unless_forced(tmp_path: Path, content: bytes) -> None:
    foreign = tmp_path / "oab-review.timer"
    foreign.write_bytes(content)
    runner = FakeRunner()
    with pytest.raises(TimerError) as exc:
        install(render(SCHEDULE), tmp_path, runner)
    assert str(exc.value) == f"not written by oab-timers, use --force to replace: {foreign}"
    assert runner.calls == []
    assert foreign.read_bytes() == content
    install(render(SCHEDULE), tmp_path, runner, force=True)
    assert foreign.read_text(encoding="utf-8").startswith(MARKER)


def test_install_lists_every_foreign_unit(tmp_path: Path) -> None:
    for name in ("oab-collect.timer", "oab-review.timer"):
        (tmp_path / name).write_text("[Timer]\n", encoding="utf-8")
    with pytest.raises(TimerError) as exc:
        install(render(SCHEDULE), tmp_path, FakeRunner())
    assert str(exc.value).endswith(
        f": {tmp_path / 'oab-collect.timer'}, {tmp_path / 'oab-review.timer'}"
    )


def test_verify_in_system_scope_has_no_user_flag() -> None:
    runner = FakeRunner()
    verify(render(SCHEDULE), runner, user=False)
    assert runner.calls[0][:2] == ["systemd-analyze", "verify"]


def test_install_writes_nothing_when_verify_fails(tmp_path: Path) -> None:
    runner = FakeRunner("systemd-analyze")
    with pytest.raises(TimerError) as exc:
        install(render(SCHEDULE), tmp_path, runner)
    assert str(exc.value) == (
        "the units do not pass systemd-analyze verify: systemd-analyze exited with code 1"
    )
    assert list(tmp_path.iterdir()) == []
    assert len(runner.calls) == 1


def test_install_reports_a_systemctl_failure(tmp_path: Path) -> None:
    runner = FakeRunner("systemctl --user enable")
    with pytest.raises(TimerError) as exc:
        install(render(SCHEDULE), tmp_path, runner)
    assert str(exc.value) == (
        f"units written to {tmp_path}, but systemctl failed: systemctl exited with code 1"
    )
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(UNITS)


def test_uninstall_removes_only_its_units(tmp_path: Path) -> None:
    install(render(SCHEDULE), tmp_path, FakeRunner())
    (tmp_path / "oab-review.timer").write_text("[Timer]\n", encoding="utf-8")  # user's own
    (tmp_path / "oab-collect.timer").unlink()  # already gone
    runner = FakeRunner()
    removed, kept = uninstall(tmp_path, runner)
    assert removed == [tmp_path / "oab-collect.service", tmp_path / "oab-review.service"]
    assert kept == [tmp_path / "oab-review.timer"]
    assert runner.calls == [
        ["systemctl", "--user", "disable", "--now", "oab-collect.timer", "oab-review.timer"],
        ["systemctl", "--user", "daemon-reload"],
    ]


def test_uninstall_cleans_up_even_if_the_timers_are_not_loaded(tmp_path: Path) -> None:
    install(render(SCHEDULE), tmp_path, FakeRunner())
    removed, kept = uninstall(tmp_path, FakeRunner("systemctl --user disable"))
    assert len(removed) == len(UNITS)
    assert kept == []
    assert list(tmp_path.iterdir()) == []


def test_uninstall_reports_a_reload_failure(tmp_path: Path) -> None:
    with pytest.raises(TimerError) as exc:
        uninstall(tmp_path, FakeRunner("systemctl --user daemon-reload"))
    assert str(exc.value) == "units removed, but systemctl failed: systemctl exited with code 1"


# --- command line ----------------------------------------------------------------


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A vault with oab.toml and XDG_CONFIG_HOME inside tmp_path."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "oab.toml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return vault


def test_cli_print_shows_the_units_in_the_vault_timezone(
    setup: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["--config", str(setup / "oab.toml"), "print", "--collect-at", "*-*-* 07:15"]
    runner = FakeRunner()
    assert cli.timers_main(args, runner, which_in(BIN)) == 0
    out = capsys.readouterr().out
    folder = setup.parent / "config/systemd/user"
    assert out.startswith(f"# --- {folder / 'oab-collect.service'} ---\n{MARKER}\n")
    assert "\nOnCalendar=*-*-* 07:15 America/Lima\n" in out
    assert "\nOnCalendar=Mon *-*-* 09:30 America/Lima\n" in out
    assert f'"--config" "{setup / "oab.toml"}" --days 3\n' in out
    # Executables and PATH come from the injected lookup, not from the real PATH.
    assert '\nExecStart="/opt/oab/bin/oab-collect" "--config"' in out
    assert '\nExecStart="/opt/oab/bin/oab-review" "--config"' in out
    assert '\nEnvironment="PATH=/opt/oab/bin:/usr/local/bin:/usr/bin:/bin"\n' in out
    assert runner.calls == []
    assert not folder.exists()


def test_cli_force_replaces_foreign_units(setup: Path) -> None:
    folder = setup.parent / "config/systemd/user"
    folder.mkdir(parents=True)
    (folder / "oab-collect.timer").write_text("[Timer]\n", encoding="utf-8")
    args = ["--config", str(setup / "oab.toml"), "install"]
    assert cli.timers_main(args, FakeRunner(), which_in(BIN)) == 1
    assert cli.timers_main([*args, "--force"], FakeRunner(), which_in(BIN)) == 0
    timer = (folder / "oab-collect.timer").read_text(encoding="utf-8")
    assert "\nOnCalendar=*-*-* 09:00 America/Lima\n" in timer  # the default


def test_cli_install_and_uninstall(setup: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = setup.parent / "config/systemd/user"
    config = ["--config", str(setup / "oab.toml")]
    install_args = [*config, "install", "--review-at", "Sun *-*-* 20:00", "--no-github"]
    assert cli.timers_main(install_args, FakeRunner(), which_in(BIN)) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[:4] == [f"wrote {folder / name}" for name in UNITS]
    assert out[4] == (
        "enabled oab-collect.timer and oab-review.timer; "
        "next runs: systemctl --user list-timers 'oab-*'"
    )
    timer = (folder / "oab-review.timer").read_text(encoding="utf-8")
    assert "\nOnCalendar=Sun *-*-* 20:00 America/Lima\n" in timer
    assert "--no-github" in (folder / "oab-collect.service").read_text(encoding="utf-8")

    (folder / "oab-review.timer").write_text("[Timer]\n", encoding="utf-8")
    assert cli.timers_main(["uninstall"], FakeRunner()) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        f"removed {folder / name}" for name in UNITS if name != "oab-review.timer"
    ]
    assert captured.err == f"kept {folder / 'oab-review.timer'} (not written by oab-timers)\n"


def test_cli_uninstall_does_not_need_a_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert cli.timers_main(["uninstall"], FakeRunner()) == 0


def test_cli_errors_exit_with_1(
    setup: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "executable", str(setup / "python"))
    args = ["--config", str(setup / "oab.toml"), "install"]
    assert cli.timers_main(args, FakeRunner(), lambda name: None) == 1
    assert capsys.readouterr().err == (
        "oab-timers: error: oab-collect not found: install the package first (uv tool install .)\n"
    )


def test_cli_invalid_config_exits_with_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["--config", str(tmp_path / "missing.toml"), "print"]
    assert cli.timers_main(args, FakeRunner(), which_in(BIN)) == cli.EXIT_CONFIG_ERROR
    assert capsys.readouterr().err.startswith("oab-timers: error: config file not found")


@pytest.mark.parametrize(
    "args",
    [["print", "--collect-at", "09:00;x"], ["print", "--review-at", ""], ["start"], []],
)
def test_cli_rejects_invalid_arguments(args: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.timers_main(args)
    assert exc.value.code == cli.EXIT_CONFIG_ERROR
    assert "oab-timers: error: " in capsys.readouterr().err


def test_cli_invalid_calendar_message(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.timers_main(["print", "--collect-at", "a;b"])
    assert capsys.readouterr().err.endswith(
        "argument --collect-at: invalid calendar expression: 'a;b'\n"
    )


def test_cli_help(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("COLUMNS", "200")
    with pytest.raises(SystemExit):
        cli.timers_main(["--help"])
    lines = [line.strip() for line in capsys.readouterr().out.splitlines()]
    expected = [
        "Run the collector every day and the review every week with systemd user timers.",
        "print the units, install and enable them, or disable and remove them",
        "when to collect, in the vault timezone (default: '*-*-* 09:00')",
        "when to review, in the vault timezone (default: 'Mon *-*-* 09:30')",
        "the daily collector does not query GitHub",
        "replace unit files not written by oab-timers",
    ]
    assert "--collect-at CALENDAR" in "\n".join(lines)
    assert "--review-at CALENDAR" in "\n".join(lines)
    missing = [
        text
        for text in expected
        if not any(line == text or line.endswith(f" {text}") for line in lines)
    ]
    assert missing == []
