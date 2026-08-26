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


def findings_default(text: str) -> List[cl.Finding]:
    return cl.lint(cl.analyze(text, "markdown"), cl._default_config())


def test_placeholder_variants() -> None:
    text = (
        "Brackets [Party Name] and {{mustache}} and <ANGLE> and ____ blank "
        "and TBD and bullet [•]."
    )
    fs = [f for f in findings(text) if f.rule == "placeholder"]
    assert len(fs) >= 6
    assert all(f.severity == "error" for f in fs)


def test_placeholder_single_letter_words() -> None:
    # [Party A]/[Party B] is the suite's canonical placeholder style (draft-cli demo);
    # a single-letter word inside the brackets must not defeat the rule.
    text = "Between Acme GmbH and [Party B], organized in [Party B Jurisdiction].\n"
    fs = [f for f in findings(text) if f.rule == "placeholder"]
    assert len(fs) == 2
    # ...while markdown links and footnotes stay exempt.
    clean = "See [Section Two](#s2) and a footnote [1] and [see 2].\n"
    assert not [f for f in findings(clean) if f.rule == "placeholder"]


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


def test_parens_definition_variants_still_match() -> None:
    # The de-ReDoS'd _DEFN_PARENS_RE must keep matching the real constructs.
    assert cl.scan_definitions(['("Widget")']) == {"Widget": [1]}
    assert cl.scan_definitions(['(the "Widget")']) == {"Widget": [1]}
    assert cl.scan_definitions(['(collectively, "Parties")']) == {"Parties": [1]}
    assert cl.scan_definitions(['(  "Spaced")']) == {"Spaced": [1]}


def test_parens_definition_keyword_comma_is_optional_for_every_keyword() -> None:
    # The optional comma used to be attached to `collectively`/`together`/
    # `individually` only, so `(each, a "X")` -- the standard way to define a
    # singular alongside a collective -- was not recognised as a definition at all.
    for line, term in [
        ('Each of them is (each, a "Purchaser") hereunder.', "Purchaser"),
        ('Each of them is (each, the "Holder") hereunder.', "Holder"),
        ('They are (individually, a "Seller") hereunder.', "Seller"),
        ('They are (together, the "Group") hereunder.', "Group"),
        ('They are (collectively, the "Buyers") hereunder.', "Buyers"),
    ]:
        assert cl.scan_definitions([line]) == {term: [1]}, line

    # Without the comma every keyword must keep working exactly as before.
    for line, term in [
        ('They are (each a "Party") hereunder.', "Party"),
        ('They are (each an "Owner") hereunder.', "Owner"),
        ('It is (a "Notice") hereunder.', "Notice"),
        ('It is (the "Agreement") hereunder.', "Agreement"),
        ('It is (this "Deed") hereunder.', "Deed"),
    ]:
        assert cl.scan_definitions([line]) == {term: [1]}, line


def test_definition_scan_no_redos_on_pathological_line() -> None:
    # Regression for catastrophic backtracking in _DEFN_PARENS_RE: an open paren
    # followed by a long whitespace run and no closing quote used to take ~tens of
    # seconds. It must now complete near-instantly.
    import time

    pathological = "(" + " " * 5000
    start = time.perf_counter()
    cl.scan_definitions([pathological])
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"scan_definitions took {elapsed:.3f}s on a pathological line"


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


def test_date_sanity_checks_all_pairs_not_just_first() -> None:
    # Regression: the rule used to latch only the FIRST effective + FIRST expiry, so a
    # later out-of-order expiry slipped through. Here the first expiry is valid (after the
    # effective date) but a second termination date precedes it — that must still fire.
    text = (
        "Effective as of 2026-05-01.\n"
        "This expires on 2026-12-31.\n"
        "Termination date 2026-01-01.\n"
    )
    out_of_order = [
        f for f in findings(text)
        if f.rule == "date-sanity" and "precedes" in f.message
    ]
    assert len(out_of_order) == 1
    assert out_of_order[0].line == 3
    assert "2026-01-01" in out_of_order[0].message


def test_number_consistency() -> None:
    bad = "Payment is due within thirty (45) days of the invoice date.\n"
    fs = [f for f in findings(bad) if f.rule == "number-consistency"]
    assert len(fs) == 1 and "30" in fs[0].message and "45" in fs[0].message
    good = "Payment is due within thirty (30) days; warranty lasts one (1) year.\n"
    assert "number-consistency" not in {f.rule for f in findings(good)}


def test_duplicate_heading() -> None:
    text = "# T\n\n## 1. Quantity\nstuff\n\n## 3. Quantity\nmore\n"
    fs = [f for f in findings(text) if f.rule == "duplicate-heading"]
    assert len(fs) == 1 and "Quantity" in fs[0].message


def test_signature_block_opt_in() -> None:
    no_block = "# T\n\n## 1. A\nx\n\n## 2. B\ny\n\n## 3. C\nz\n"
    assert "signature-block" in fired(no_block)                       # fires when enabled
    assert "signature-block" not in {f.rule for f in findings_default(no_block)}  # off by default
    with_block = no_block + "\nIN WITNESS WHEREOF, the parties sign. By: Jane Doe\n"
    assert "signature-block" not in fired(with_block)
    short = "# T\n\n## 1. A\nonly one section\n"                       # <3 headings: never nags
    assert "signature-block" not in fired(short)


def test_clean_text_silent() -> None:
    text = (
        "# Agreement\n\n## 1. Term\nThis section is clean.\n\n"
        "## 2. Scope\nNothing to flag here at all.\n\n"
        "## 3. Signatures\nIN WITNESS WHEREOF, the parties have executed this. By: Jane Doe\n"
    )
    assert fired(text) == set()  # no findings even with every rule enabled


def test_every_rule_has_unique_id_and_valid_severity() -> None:
    ids = [r.id for r in cl.RULES]
    assert len(ids) == len(set(ids))
    assert all(r.severity in ("error", "warning") for r in cl.RULES)


def test_findings_sorted_by_position() -> None:
    text = "Late {{b}} here.\nEarly {{a}} there. Also [Party Name].\n"
    fs = findings(text)
    lines = [(f.line, f.column or 0) for f in fs]
    assert lines == sorted(lines)
