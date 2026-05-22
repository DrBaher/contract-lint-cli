"""The fixture corpus → golden --json reports (regression + determinism)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from _report import default_report
from conftest import GOLDEN, all_corpus_files


@pytest.mark.parametrize("md", all_corpus_files(), ids=lambda p: p.stem)
def test_corpus_matches_golden(md: Path) -> None:
    golden_path = GOLDEN / f"{md.stem}.json"
    assert golden_path.is_file(), f"missing golden for {md.name}; run tests/_make_goldens.py"
    expected = json.loads(golden_path.read_text(encoding="utf-8"))
    actual = default_report(md)
    assert actual == expected, (
        f"{md.name} drifted from its golden. If intended, run tests/_make_goldens.py."
    )


@pytest.mark.parametrize("md", all_corpus_files(), ids=lambda p: p.stem)
def test_report_is_deterministic(md: Path) -> None:
    assert default_report(md) == default_report(md)


def test_clean_contract_has_no_findings() -> None:
    report = default_report(GOLDEN.parent / "corpus" / "clean_nda.md")
    assert report["summary"]["total"] == 0
    assert report["ok"] is True
    assert report["exit_code"] == 0


def test_flawed_contract_covers_every_default_rule() -> None:
    report = default_report(GOLDEN.parent / "corpus" / "flawed_msa.md")
    fired = set(report["summary"]["by_rule"])
    import contract_lint_cli as cl
    default_on = {r.id for r in cl.RULES if r.default_enabled}
    assert default_on <= fired, f"flawed_msa should seed every default-on rule; missing {default_on - fired}"
