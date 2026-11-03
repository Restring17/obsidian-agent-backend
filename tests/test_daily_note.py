from datetime import date
from pathlib import Path

import pytest

from obsidian_agent_backend.config import Config, parse_config
from obsidian_agent_backend.daily_note import DailyNote, NoteError, atomic_write, merge_frontmatter
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
