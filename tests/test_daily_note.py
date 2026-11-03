from datetime import date
from pathlib import Path

import pytest

from obsidian_agent_backend.config import Config, parse_config
from obsidian_agent_backend.daily_note import (
    DailyNote,
    NoteError,
    append_log,
    atomic_write,
    log_lines,
    merge_frontmatter,
    read_frontmatter,
)
from obsidian_agent_backend.domain import Metrics

DAY = date(2026, 11, 2)


def make_config(vault: Path, template: str | None = "Templates/Daily.md") -> Config:
    daily: dict[str, str] = {"folder": "Journal"}
    if template:
        daily["template"] = template
    return parse_config({"daily_notes": daily}, vault=vault)


def test_creates_note_from_template(tmp_path: Path) -> None:
    (tmp_path / "Templates").mkdir()
    (tmp_path / "Templates/Daily.md").write_text(
        "---\ndate: {{date:YYYY-MM-DD}}\nmood:\n---\n# {{title}} ({{date}})\n", encoding="utf-8"
    )
    note = DailyNote(make_config(tmp_path))
    assert not note.exists(DAY)

    path = note.update(DAY, Metrics({"vault_commits": 3}), "2026-11-03T06:00")

    assert path == tmp_path / "Journal/2026-11-02.md"
    assert note.exists(DAY)
    assert path.read_text(encoding="utf-8") == (
        '---\ndate: 2026-11-02\nmood:\nvault_commits: 3\ncollected_at: "2026-11-03T06:00"\n'
        "---\n# 2026-11-02 (2026-11-02)\n"
    )


def test_creates_empty_note_without_template(tmp_path: Path) -> None:
    path = DailyNote(make_config(tmp_path, template=None)).update(DAY, Metrics({"a": 1}), "t")
    assert path.read_text(encoding="utf-8") == '---\na: 1\ncollected_at: "t"\n---\n'


def test_missing_template_is_a_note_error(tmp_path: Path) -> None:
    with pytest.raises(NoteError, match=r"cannot read the template Templates/Daily\.md"):
        DailyNote(make_config(tmp_path)).update(DAY, Metrics(), "t")


def test_updates_existing_note_without_touching_the_rest(tmp_path: Path) -> None:
    path = tmp_path / "Journal/2026-11-02.md"
    path.parent.mkdir()
    body = "\n# Day\n\n- [ ] task\nvault_commits: 0 in the body is not frontmatter\n"
    path.write_text(f"---\ntags: [daily]\nvault_commits: 1\nnotes: x\n---{body}", "utf-8")

    DailyNote(make_config(tmp_path)).update(DAY, Metrics({"vault_commits": 4}), "now")

    assert path.read_text(encoding="utf-8") == (
        f'---\ntags: [daily]\nvault_commits: 4\nnotes: x\ncollected_at: "now"\n---{body}'
    )


def test_existing_note_with_invalid_utf8(tmp_path: Path) -> None:
    path = tmp_path / "Journal/2026-11-02.md"
    path.parent.mkdir()
    path.write_bytes(b"---\na: \xff\n---\n")
    with pytest.raises(NoteError, match="not valid UTF-8"):
        DailyNote(make_config(tmp_path)).update(DAY, Metrics(), "t")


def test_symlinked_daily_folder_outside_the_vault_is_refused(tmp_path: Path) -> None:
    vault, outside = tmp_path / "vault", tmp_path / "outside"
    vault.mkdir()
    outside.mkdir()
    (vault / "Journal").symlink_to(outside)
    note = DailyNote(make_config(vault, template=None))
    with pytest.raises(NoteError, match="outside the vault"):
        note.exists(DAY)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("no frontmatter\n", "has no frontmatter"),
        ("---\nb: [\n---\n", "not valid YAML"),
        ("---\n- item\n---\n", "not valid YAML"),
        ("---\na: |\n  text\n---\n", "could not be updated safely"),  # becomes "1 text"
        ("---\na: 1\na: 2\n---\n", "could not be updated safely"),  # YAML keeps the last
    ],
)
def test_merge_rejects_unsafe_frontmatter(text: str, message: str) -> None:
    with pytest.raises(NoteError, match=message):
        merge_frontmatter(text, {"a": "1"})


def test_merge_handles_empty_frontmatter_and_end_of_file() -> None:
    assert merge_frontmatter("---\n---", {"a": "1"}) == "---\na: 1\n---\n"
    assert merge_frontmatter("---\n---\nbody", {"a": "1"}) == "---\na: 1\n---\nbody"


def test_merge_does_not_confuse_prefixed_keys() -> None:
    text = "---\ngithub_commits_total: 9\n---\n"
    assert merge_frontmatter(text, {"github_commits": "1"}) == (
        "---\ngithub_commits_total: 9\ngithub_commits: 1\n---\n"
    )


def test_merge_with_no_values_on_empty_frontmatter_is_not_a_mapping() -> None:
    with pytest.raises(NoteError, match="not a mapping"):
        merge_frontmatter("---\n---\n", {})


def test_atomic_write_leaves_no_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "sub/note.md"
    atomic_write(path, "hello\r\n")
    assert path.read_bytes() == b"hello\r\n"
    assert [p.name for p in path.parent.iterdir()] == ["note.md"]


def test_atomic_write_cleans_up_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(self: Path, target: Path) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", boom)
    path = tmp_path / "note.md"
    path.write_text("old", encoding="utf-8")
    with pytest.raises(OSError, match="disk full"):
        atomic_write(path, "new")
    assert path.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["note.md"]


# --- log section and frontmatter reader (#5) ------------------------------------


def test_read_frontmatter() -> None:
    assert read_frontmatter("---\na: 1\nb: x\n---\nbody") == {"a": 1, "b": "x"}
    assert read_frontmatter("---\n1: one\n---\n") == {"1": "one"}


@pytest.mark.parametrize(
    "text", ["no frontmatter", "---\na: [\n---\n", "---\n- x\n---\n", "---\n---\n"]
)
def test_read_frontmatter_never_raises(text: str) -> None:
    assert read_frontmatter(text) == {}


def test_log_lines_reads_only_list_items_of_the_section() -> None:
    text = "# Day\n## AI log\n- one\ntext\n  - two\n## Notes\n- not log\n"
    assert log_lines(text, "AI log") == ["- one", "- two"]
    assert log_lines(text, "Missing") == []
    assert log_lines("## AI log\n- last\n", "AI log") == ["- last"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("# Day", "# Day\n\n## AI log\n- new\n"),
        ("# Day\n## AI log\n", "# Day\n## AI log\n- new\n"),
        ("## AI log\n- old\n\n\n", "## AI log\n- old\n- new\n"),
        ("## AI log\n- old\n\n## Notes\nx\n", "## AI log\n- old\n- new\n\n## Notes\nx\n"),
        ("## AI log  \n# Next\n", "## AI log  \n- new\n\n# Next\n"),
        ("### AI log\n- deeper\n", "### AI log\n- deeper\n\n## AI log\n- new\n"),
    ],
)
def test_append_log(text: str, expected: str) -> None:
    assert append_log(text, "AI log", "- new") == expected


@pytest.mark.parametrize("line", ["", "  ", "a\nb", "a\rb"])
def test_append_log_rejects_invalid_lines(line: str) -> None:
    with pytest.raises(NoteError, match="single non-empty line"):
        append_log("", "AI log", line)


def test_log_creates_the_note_and_keeps_metrics(tmp_path: Path) -> None:
    note = DailyNote(make_config(tmp_path, template=None))
    note.update(DAY, Metrics({"vault_commits": 2}), "t")
    path = note.log(DAY, "- [oab-review] done")
    assert path.read_text(encoding="utf-8") == (
        '---\nvault_commits: 2\ncollected_at: "t"\n---\n\n## AI log\n- [oab-review] done\n'
    )
