"""Each rule fires on a crafted positive case and stays silent on a clean one."""
from __future__ import annotations

from typing import List, Set

import pytest

import contract_lint_cli as cl


def fired(text: str) -> Set[str]:
    cfg = cl._default_config()
    for r in cl.RULES:               # enable every rule, including the opt-in one
        cfg.rules[r.id].enabled = True
    return {f.rule for f in cl.lint(cl.analyze(text, "markdown"), cfg)}


def findings(text: str) -> List[cl.Finding]:
    cfg = cl._default_config()
    for r in cl.RULES:
        cfg.rules[r.id].enabled = True
    return cl.lint(cl.analyze(text, "markdown"), cfg)


def test_placeholder_variants() -> None:
    text = (
        "Brackets [Party Name] and {{mustache}} and <ANGLE> and ____ blank "
        "and TBD and bullet [•]."
    )
    fs = [f for f in findings(text) if f.rule == "placeholder"]
    assert len(fs) >= 6
    assert all(f.severity == "error" for f in fs)


def test_broken_xref_detects_dangling_and_passes_valid() -> None:
    text = "# T\n\n## 1. One\n\n## 2. Two\nSee Section 2 and Section 9.\n"
    fs = [f for f in findings(text) if f.rule == "broken-xref"]
    msgs = " ".join(f.message for f in fs)
    assert "Section 9" in msgs and "Section 2" not in msgs


def test_broken_xref_exhibit_only_when_declared() -> None:
    # Exhibit A declared, Exhibit B referenced -> broken; a doc with no exhibits stays quiet.
    declared = "# T\n\n## Exhibit A\nstuff\n\nSee Exhibit B for details.\n"
    assert "broken-xref" in fired(declared)
    undeclared = "# T\n\n## 1. S\nSee Exhibit Q for details.\n"
    assert "broken-xref" not in {f.rule for f in findings(undeclared)}


def test_undefined_term_opt_in() -> None:
    text = "# T\nThe Disclosing Party shall notify the Disclosing Party promptly.\n"
    assert "undefined-term" in fired(text)
    # off by default
    assert "undefined-term" not in {f.rule for f in cl.lint(cl.analyze(text, "markdown"), cl._default_config())}


def test_unused_definition() -> None:
    text = '"Widget" means a small thing.\n\n## 1. Body\nNothing references it.\n'
    fs = [f for f in findings(text) if f.rule == "unused-definition"]
    assert len(fs) == 1 and "Widget" in fs[0].message


def test_used_definition_not_flagged() -> None:
    text = '"Widget" means a small thing.\n\n## 1. Body\nThe Widget is delivered. The Widget works.\n'
    assert "unused-definition" not in {f.rule for f in findings(text)}


def test_double_definition() -> None:
    text = '"Widget" means a thing. The Widget ships.\n"Widget" means another thing.\n'
    fs = [f for f in findings(text) if f.rule == "double-definition"]
    assert len(fs) == 1 and "2" in fs[0].message


def test_numbering_gap_and_duplicate() -> None:
    gap = "# T\n\n## 1 a\n\n## 3 b\n"
    assert any("missing" in f.message for f in findings(gap) if f.rule == "numbering")
    dup = "# T\n\n## 2 a\n\n## 2 b\n"
    assert any("duplicate" in f.message for f in findings(dup) if f.rule == "numbering")


def test_party_consistency() -> None:
    text = "Between Acme Corporation and a buyer.\nLater, Acme Corp. signs. Then ACME Corporation acts.\n"
    fs = [f for f in findings(text) if f.rule == "party-consistency"]
    assert fs and all("variant spelling" in f.message for f in fs)


def test_date_sanity_malformed_and_inconsistent() -> None:
    malformed = "Signed on 2026-02-30.\n"
    assert any("malformed" in f.message for f in findings(malformed) if f.rule == "date-sanity")
    inconsistent = "Effective as of 2026-05-01. This expires on 2026-01-01.\n"
    assert any("precedes" in f.message for f in findings(inconsistent) if f.rule == "date-sanity")


def test_clean_text_silent() -> None:
    text = (
        "# Agreement\n\n## 1. Term\nThis section is clean.\n\n"
        "## 2. Scope\nNothing to flag here at all.\n"
    )
    assert findings(text) == [] or fired(text) <= set()  # no findings


def test_every_rule_has_unique_id_and_valid_severity() -> None:
    ids = [r.id for r in cl.RULES]
    assert len(ids) == len(set(ids))
    assert all(r.severity in ("error", "warning") for r in cl.RULES)


def test_findings_sorted_by_position() -> None:
    text = "Late {{b}} here.\nEarly {{a}} there. Also [Party Name].\n"
    fs = findings(text)
    lines = [(f.line, f.column or 0) for f in fs]
    assert lines == sorted(lines)
