from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from obsidian_agent_backend.config import (
    ApplicationsConfig,
    Config,
    ConfigError,
    ProjectsConfig,
    load_config,
    parse_config,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
VAULT = Path("/vault")

FULL = """
timezone = "America/Lima"

[daily_notes]
folder = "00 Inicio/Diario"
template = "00 Inicio/Plantillas/Plantilla - Diario.md"

[human_zone]
folders = ["[0-7]0 *"]
exclude = ["Plantillas"]

[agent]
folder = "90 Agentes"

[metrics]
manual = ["tutoria_horas", "muay_thai_min"]

[applications]
note = "40 Carrera/Postulaciones.md"
field = "estado"
active = ["Enviada", "entrevista"]

[review]
model = "claude-sonnet-5-5"
"""


def write(tmp_path: Path, text: str, name: str = "oab.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def parse(data: dict[str, Any]) -> Config:
    return parse_config(data, vault=VAULT)


def error_of(data: dict[str, Any]) -> str:
    with pytest.raises(ConfigError) as exc:
        parse(data)
    return str(exc.value)


# --- loading ---------------------------------------------------------------------


def test_full_config_is_loaded(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, FULL))

    assert config.vault == tmp_path.resolve()
    assert config.timezone.key == "America/Lima"
    assert config.daily_notes.folder == PurePosixPath("00 Inicio/Diario")
    assert config.daily_notes.template == PurePosixPath(
        "00 Inicio/Plantillas/Plantilla - Diario.md"
    )
    assert config.human_zone.folders == ("[0-7]0 *",)
    assert config.human_zone.exclude == ("Plantillas",)
    assert config.agent.folder == PurePosixPath("90 Agentes")
    assert config.metrics.manual == ("tutoria_horas", "muay_thai_min")
    assert config.applications == ApplicationsConfig(
        note=PurePosixPath("40 Carrera/Postulaciones.md"),
        field="estado",
        active=("enviada", "entrevista"),
    )
    assert config.review.model == "claude-sonnet-5-5"


def test_empty_config_uses_defaults(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, ""))

    assert config.timezone.key == "UTC"
    assert config.daily_notes.folder == PurePosixPath("Daily")
    assert config.daily_notes.template is None
    assert config.human_zone.folders == ("*",)
    assert config.human_zone.exclude == ()
    assert config.agent.folder == PurePosixPath("Agents")
    assert config.metrics.manual == ()
    assert config.applications is None
    assert config.review.model == "sonnet"


def test_example_file_is_valid() -> None:
    config = load_config(REPO_ROOT / "oab.example.toml")
    assert config.review.model == "sonnet"


def test_example_file_with_optional_sections_enabled(tmp_path: Path) -> None:
    text = (REPO_ROOT / "oab.example.toml").read_text(encoding="utf-8")
    lines = [
        line.removeprefix("# ")
        for line in text.splitlines()
        if line.startswith(("# [applications]", "# note =", "# field =", "# template ="))
    ]
    enabled = text.replace("[review]", "\n".join(lines[1:]) + "\n\n[review]", 1)
    enabled = enabled.replace('folder = "Daily"', f'folder = "Daily"\n{lines[0]}', 1)
    config = load_config(write(tmp_path, enabled))
    assert config.daily_notes.template == PurePosixPath("Templates/Daily.md")
    assert config.applications is not None


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="config file not found"):
        load_config(tmp_path / "oab.toml")


def test_directory_is_reported_as_unreadable(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path)
    assert str(exc.value) == f"cannot read {tmp_path}: Is a directory"


def test_read_error_without_description_names_the_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise PermissionError

    monkeypatch.setattr(Path, "open", fail)
    with pytest.raises(ConfigError) as exc:
        load_config(tmp_path / "oab.toml")
    assert str(exc.value) == f"cannot read {tmp_path / 'oab.toml'}: PermissionError"


def test_invalid_toml_reports_location(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"not valid TOML: .*line 1"):
        load_config(write(tmp_path, "timezone = \n"))


def test_invalid_utf8_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "oab.toml"
    path.write_bytes(b'timezone = "\xff"\n')
    with pytest.raises(ConfigError, match="not valid UTF-8"):
        load_config(path)


def test_validation_errors_name_the_file(tmp_path: Path) -> None:
    path = write(tmp_path, "colour = 1\n")
    with pytest.raises(ConfigError, match=f"^{path}: unknown key"):
        load_config(path)


# --- unknown keys and types ------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "key"),
    [
        ({"timezon": "UTC"}, "timezon"),
        ({"daily_notes": {"folders": "x"}}, "daily_notes.folders"),
        ({"human_zone": {"pattern": "*"}}, "human_zone.pattern"),
        ({"agent": {"model": "x"}}, "agent.model"),
        ({"metrics": {"auto": []}}, "metrics.auto"),
        ({"applications": {"note": "a.md", "x": 1}}, "applications.x"),
        ({"review": {"modle": "x"}}, "review.modle"),
    ],
)
def test_unknown_keys_are_rejected(data: dict[str, Any], key: str) -> None:
    assert error_of(data) == f"unknown key(s): {key}"


def test_all_unknown_keys_are_listed_sorted() -> None:
    assert error_of({"b": 1, "a": 2}) == "unknown key(s): a, b"


@pytest.mark.parametrize("section", ["daily_notes", "human_zone", "agent", "metrics", "review"])
def test_sections_must_be_tables(section: str) -> None:
    assert error_of({section: "x"}) == f"[{section}] must be a table"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"timezone": 5}, "timezone must be a string"),
        ({"daily_notes": {"folder": 1}}, "daily_notes.folder must be a string"),
        ({"daily_notes": {"template": True}}, "daily_notes.template must be a string"),
        ({"agent": {"folder": []}}, "agent.folder must be a string"),
        ({"review": {"model": 4}}, "review.model must be a string"),
        ({"applications": {"note": 1}}, "applications.note must be a string"),
        ({"applications": {"note": "a.md", "field": 1}}, "applications.field must be a string"),
        ({"daily_notes": {"log_heading": 1}}, "daily_notes.log_heading must be a string"),
        ({"human_zone": {"private_field": 1}}, "human_zone.private_field must be a string"),
        ({"review": {"prompt": 1}}, "review.prompt must be a string"),
        ({"projects": {"folder": 1}}, "projects.folder must be a string"),
        (
            {"projects": {"folder": "P", "status_field": 1}},
            "projects.status_field must be a string",
        ),
        # Path errors name the key too.
        ({"daily_notes": {"folder": " "}}, "daily_notes.folder must not be empty"),
        ({"projects": {"folder": ""}}, "projects.folder must not be empty"),
        ({"review": {"prompt": ""}}, "review.prompt must not be empty"),
        ({"projects": {}}, "projects.folder is required when [projects] is present"),
    ],
)
def test_wrong_types_are_rejected(data: dict[str, Any], message: str) -> None:
    assert error_of(data) == message


# --- timezone --------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Mars/Olympus", "../../etc/passwd", "", "UTC-5"])
def test_unknown_timezone_is_rejected(name: str) -> None:
    assert error_of({"timezone": name}) == f"timezone: unknown IANA timezone {name!r}"


# --- paths -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("/etc", "must be relative to the vault"),
        ("../outside", "must not contain '..'"),
        ("Daily/../../outside", "must not contain '..'"),
        ("a\\b", "must use '/' as separator"),
        ("a\0b", "must use '/' as separator"),
        ("   ", "must not be empty"),
        (".", "must not be the vault root"),
        (".obsidian", "must not be a hidden folder"),
    ],
)
def test_unsafe_daily_folder_is_rejected(raw: str, message: str) -> None:
    assert message in error_of({"daily_notes": {"folder": raw}})


def test_unsafe_template_is_rejected() -> None:
    assert "must not contain '..'" in error_of({"daily_notes": {"template": "../t.md"}})


def test_template_must_be_markdown() -> None:
    assert error_of({"daily_notes": {"template": "Templates/daily.txt"}}) == (
        "daily_notes.template must be a Markdown file (.md)"
    )


def test_agent_folder_must_be_top_level() -> None:
    assert error_of({"agent": {"folder": "Notes/Agents"}}) == (
        "agent.folder must be a top-level folder (no '/')"
    )


def test_agent_folder_must_not_be_hidden() -> None:
    assert error_of({"agent": {"folder": ".agents"}}) == "agent.folder must not be a hidden folder"


@pytest.mark.parametrize("folder", ["Agents", "Agents/Daily"])
def test_daily_notes_cannot_live_in_agent_folder(folder: str) -> None:
    assert error_of({"daily_notes": {"folder": folder}}) == (
        "daily_notes.folder must not be inside agent.folder"
    )


def test_trailing_slash_is_normalised() -> None:
    config = parse({"daily_notes": {"folder": "Journal/Daily/"}})
    assert config.daily_notes.folder == PurePosixPath("Journal/Daily")


# --- human zone ------------------------------------------------------------------


@pytest.mark.parametrize("value", [[], "*", [1], [""], ["  "]])
def test_human_zone_needs_non_empty_strings(value: object) -> None:
    assert error_of({"human_zone": {"folders": value}}) == (
        "human_zone.folders must be a non-empty list of strings"
    )


@pytest.mark.parametrize("pattern", ["Notes/*", "a\\b", ".", ".."])
def test_human_zone_patterns_match_folder_names_only(pattern: str) -> None:
    assert "must match folder names only" in error_of({"human_zone": {"folders": [pattern]}})


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("10 Perfil/Sobre mí.md", True),
        ("70 Vida/sub/nota.md", True),
        ("80 Archivo/x.md", False),  # outside the pattern
        ("90 Agentes/Informes/r.md", False),  # agent folder
        ("CLAUDE.md", False),  # vault root
        (".obsidian/app.json", False),  # hidden
    ],
)
def test_in_human_zone(path: str, expected: bool) -> None:
    config = parse({"human_zone": {"folders": ["[0-7]0 *"]}, "agent": {"folder": "90 Agentes"}})
    assert config.in_human_zone(PurePosixPath(path)) is expected


def test_agent_folder_is_excluded_even_when_patterns_match_everything() -> None:
    config = parse({})
    assert config.in_human_zone(PurePosixPath("Notes/a.md"))
    assert not config.in_human_zone(PurePosixPath("Agents/report.md"))
    assert not config.in_human_zone(PurePosixPath(".git/HEAD"))


def test_patterns_are_case_sensitive() -> None:
    config = parse({"human_zone": {"folders": ["notes"]}})
    assert not config.in_human_zone(PurePosixPath("Notes/a.md"))


# --- metrics, applications, model ------------------------------------------------


@pytest.mark.parametrize("key", ["Workout", "1st", "a-b", "", "x" * 65, 3])
def test_invalid_metric_keys_are_rejected(key: object) -> None:
    assert "is not a valid key" in error_of({"metrics": {"manual": [key]}})


def test_metrics_manual_must_be_a_list() -> None:
    assert error_of({"metrics": {"manual": "a"}}) == "metrics.manual must be a list of strings"


def test_duplicate_metric_keys_are_rejected() -> None:
    assert error_of({"metrics": {"manual": ["a", "a"]}}) == "metrics.manual: duplicate key 'a'"


def test_applications_need_a_note() -> None:
    assert error_of({"applications": {"field": "status"}}) == (
        "applications.note is required when [applications] is present"
    )


def test_applications_field_defaults_to_status() -> None:
    config = parse({"applications": {"note": "Apps.md"}})
    assert config.applications == ApplicationsConfig(
        note=PurePosixPath("Apps.md"), field="status", active=("applied", "interview")
    )


def test_applications_section_must_be_a_table() -> None:
    assert error_of({"applications": []}) == "[applications] must be a table"


@pytest.mark.parametrize("field", ["", "1x", "a b", "a::b", "x" * 65])
def test_invalid_applications_field_is_rejected(field: str) -> None:
    message = error_of({"applications": {"note": "A.md", "field": field}})
    assert message == f"applications.field: {field!r} is not a valid Dataview field name"


def test_applications_note_must_be_markdown() -> None:
    assert error_of({"applications": {"note": "Apps"}}) == (
        "applications.note must be a Markdown file (.md)"
    )


@pytest.mark.parametrize("model", ["sonnet", "opus", "claude-opus-5-5", "sonnet[1m]"])
def test_valid_models(model: str) -> None:
    assert parse({"review": {"model": model}}).review.model == model


@pytest.mark.parametrize("model", ["", "Sonnet", "-x", "a b", "sonnet;rm", "x" * 65])
def test_invalid_models_are_rejected(model: str) -> None:
    assert error_of({"review": {"model": model}}) == f"review.model: invalid model name {model!r}"


# --- resolve ---------------------------------------------------------------------


def test_resolve_returns_absolute_path_inside_vault(tmp_path: Path) -> None:
    config = parse_config({}, vault=tmp_path)
    assert config.resolve(PurePosixPath("Daily/2026-11-02.md")) == (
        tmp_path.resolve() / "Daily" / "2026-11-02.md"
    )


def test_resolve_refuses_symlinks_leaving_the_vault(tmp_path: Path) -> None:
    vault, outside = tmp_path / "vault", tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    (vault / "Daily").symlink_to(outside)
    config = parse_config({}, vault=vault)
    with pytest.raises(ConfigError, match="resolves outside the vault"):
        config.resolve(PurePosixPath("Daily/x.md"))


# --- collector extensions (#4) ---------------------------------------------------


def test_exclude_skips_folders_at_any_depth() -> None:
    config = parse({"human_zone": {"exclude": ["Templates", "_*"]}})
    assert config.in_human_zone(PurePosixPath("Notes/a.md"))
    assert not config.in_human_zone(PurePosixPath("Notes/Templates/daily.md"))
    assert not config.in_human_zone(PurePosixPath("Templates/daily.md"))
    assert not config.in_human_zone(PurePosixPath("Notes/_drafts/x.md"))
    assert config.in_human_zone(PurePosixPath("Notes/Templates.md"))  # files are not folders


@pytest.mark.parametrize("value", ["Templates", [1], [""]])
def test_exclude_must_be_a_list_of_strings(value: object) -> None:
    assert error_of({"human_zone": {"exclude": value}}) == (
        "human_zone.exclude must be a list of strings"
    )


def test_exclude_patterns_match_folder_names_only() -> None:
    assert error_of({"human_zone": {"exclude": ["a/b"]}}) == (
        "human_zone.exclude: 'a/b' must match folder names only"
    )


@pytest.mark.parametrize("key", ["github_commits", "tasks_open", "collected_at"])
def test_manual_metrics_cannot_reuse_collected_keys(key: str) -> None:
    assert error_of({"metrics": {"manual": [key]}}) == (
        f"metrics.manual: {key!r} is written by the collector"
    )


@pytest.mark.parametrize("value", [[], "applied"])
def test_applications_active_must_be_a_non_empty_list(value: object) -> None:
    assert error_of({"applications": {"note": "A.md", "active": value}}) == (
        "applications.active must be a non-empty list of strings"
    )


@pytest.mark.parametrize("value", ["", "  ", "a]b", "[x", "a\nb", "x" * 65, 3])
def test_applications_active_values_are_validated(value: object) -> None:
    message = error_of({"applications": {"note": "A.md", "active": [value]}})
    assert message == f"applications.active: {value!r} is not a valid field value"


def test_applications_active_values_are_normalised() -> None:
    config = parse({"applications": {"note": "A.md", "active": [" Applied ", "INTERVIEW"]}})
    assert config.applications is not None
    assert config.applications.active == ("applied", "interview")


# --- review extensions (#5) ------------------------------------------------------


def test_review_defaults() -> None:
    config = parse({})
    assert config.daily_notes.log_heading == "AI log"
    assert config.human_zone.private_field == "private"
    assert config.projects is None
    assert config.review.prompt is None


def test_review_keys_are_loaded() -> None:
    config = parse(
        {
            "daily_notes": {"log_heading": "Registro IA"},
            "human_zone": {"private_field": "privado"},
            "projects": {"folder": "20 Proyectos", "status_field": "estado"},
            "review": {"prompt": "90 Agentes/prompt.md"},
        }
    )
    assert config.daily_notes.log_heading == "Registro IA"
    assert config.human_zone.private_field == "privado"
    assert config.projects == ProjectsConfig(
        folder=PurePosixPath("20 Proyectos"), status_field="estado"
    )
    assert config.review.prompt == PurePosixPath("90 Agentes/prompt.md")


def test_projects_status_field_defaults_to_status() -> None:
    config = parse({"projects": {"folder": "Projects"}})
    assert config.projects is not None
    assert config.projects.status_field == "status"


@pytest.mark.parametrize("heading", ["", " AI log", "AI log ", "## AI log", "a\nb", "x" * 65])
def test_invalid_log_heading(heading: str) -> None:
    assert "must be one line of heading text" in error_of({"daily_notes": {"log_heading": heading}})


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"human_zone": {"private_field": "a b"}}, "human_zone.private_field: 'a b' is not"),
        ({"projects": {"status_field": "status"}}, "projects.folder is required"),
        ({"projects": {"folder": "../x"}}, "must not contain '..'"),
        ({"projects": {"folder": "P", "status_field": ""}}, "projects.status_field: '' is not"),
        ({"projects": {"folder": "P", "owner": "me"}}, "unknown key(s): projects.owner"),
        ({"projects": "P"}, "[projects] must be a table"),
        ({"review": {"prompt": "prompt.txt"}}, "review.prompt must be a Markdown file"),
        ({"review": {"prompt": "/etc/prompt.md"}}, "must be relative to the vault"),
    ],
)
def test_invalid_review_keys(data: dict[str, Any], message: str) -> None:
    assert message in error_of(data)
