import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/mutation_summary.py"
STATS = {
    "killed": 90,
    "survived": 8,
    "total": 100,
    "no_tests": 0,
    "skipped": 0,
    "suspicious": 0,
    "timeout": 2,
}
RESULTS = (
    "    pkg.a__mutmut_1: survived\n    pkg.b__mutmut_2: survived\n    pkg.c__mutmut_3: timeout\n"
)


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mutation_summary", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_summary_scores_and_lists_unreviewed_survivors() -> None:
    text = load().summary(STATS, RESULTS, "- `pkg.a__mutmut_1`: equivalent")
    assert "| 100 | 90 | 2 | 8 | 0 | 0 | **92.0%** |" in text
    assert "2 survivors, **1 not reviewed yet**" in text
    assert "```\npkg.b__mutmut_2\n```" in text
    assert "pkg.c__mutmut_3" not in text


def test_summary_without_unreviewed_survivors_has_no_details() -> None:
    text = load().summary(STATS, RESULTS, "pkg.a__mutmut_1 pkg.b__mutmut_2")
    assert "**0 not reviewed yet**" in text
    assert "<details>" not in text


def test_summary_when_no_mutant_was_tested() -> None:
    empty = dict.fromkeys(STATS, 0)
    assert load().summary(empty, "", "") == load().NOT_FINISHED


def test_main_reads_the_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stats, results, doc = tmp_path / "s.json", tmp_path / "r.txt", tmp_path / "d.md"
    stats.write_text(json.dumps(STATS), encoding="utf-8")
    results.write_text(RESULTS, encoding="utf-8")
    doc.write_text("", encoding="utf-8")
    assert load().main([str(stats), str(results), str(doc)]) == 0
    assert "**2 not reviewed yet**" in capsys.readouterr().out


def test_main_without_results_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stats, doc = tmp_path / "s.json", tmp_path / "d.md"
    stats.write_text(json.dumps(STATS), encoding="utf-8")
    doc.write_text("", encoding="utf-8")
    assert load().main([str(stats), str(tmp_path / "missing.txt"), str(doc)]) == 0
    assert "0 survivors" in capsys.readouterr().out


def test_main_when_mutmut_did_not_finish(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = str(tmp_path / "missing")
    assert load().main([missing, missing, missing]) == 0
    assert "mutmut did not finish" in capsys.readouterr().out
