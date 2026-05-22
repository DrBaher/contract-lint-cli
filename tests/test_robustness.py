"""Regression tests for issues found by the stress harness (stress/): ReDoS, O(n^2)
blowups, and false positives on adversarial / real-world input. Time bounds are generous
to avoid CI flakiness while still catching a reintroduced superlinear path."""
from __future__ import annotations

import time

import contract_lint_cli as cl


def _lint_all(text: str):
    cfg = cl._default_config()
    for r in cl.RULES:
        cfg.rules[r.id].enabled = True
    return cl.lint(cl.analyze(text, "markdown"), cfg)


def test_number_seq_redos_bounded() -> None:
    # A long run of number-words with no closing "(digits)" used to backtrack quadratically.
    text = ("one " * 40000) + "!"
    t0 = time.perf_counter()
    findings = _lint_all(text)
    assert time.perf_counter() - t0 < 2.0  # was >>4s (timeout) before bounding the repeat
    assert not [f for f in findings if f.rule == "number-consistency"]


def test_huge_section_number_no_explosion() -> None:
    # An inline 8-digit amount/id parsed as a section number once produced an ~87M-element
    # "missing numbers" gap. It must be ignored as a section number entirely.
    text = "# T\n\n## 1. A\n\nbody\n\n78560181 Some line that starts with a big number\n"
    t0 = time.perf_counter()
    findings = _lint_all(text)
    assert time.perf_counter() - t0 < 1.0
    nums = [f for f in findings if f.rule == "numbering"]
    assert all("78560181" not in f.message for f in nums)


def test_numbering_large_gap_is_summarized() -> None:
    text = "# T\n\n## 2. A\n\nx\n\n## 90. B\n\ny\n"  # both < 499, real-ish, but a big gap
    findings = [f for f in _lint_all(text) if f.rule == "numbering"]
    assert findings and "missing" in findings[0].message
    assert "numbers missing" in findings[0].message  # summarized, not 87 enumerated ids


def test_broken_xref_rejects_word_like_ids() -> None:
    # "Exhibits AND Schedules" must not yield a broken ref to "Exhibit AND".
    text = "# T\n\n## Exhibit A\n\nstuff\n\nSee the Exhibits AND Schedules attached.\n"
    msgs = [f.message for f in _lint_all(text) if f.rule == "broken-xref"]
    assert not any("AND" in m for m in msgs)
    # "Section HEREOF" / "clause hereto" style are not references either
    text2 = "# T\n\n## 1. A\n\nas set forth in this Section hereof and that clause thereof.\n"
    assert not [f for f in _lint_all(text2) if f.rule == "broken-xref"]


def test_broken_xref_still_catches_real_dangling_refs() -> None:
    text = "# T\n\n## 1. One\n\n## 2. Two\n\nSee Section 9 and Exhibit A.\n\n## Exhibit B\n\nx\n"
    msgs = " ".join(f.message for f in _lint_all(text) if f.rule == "broken-xref")
    assert "Section 9" in msgs        # genuinely missing
    assert "Exhibit A" in msgs        # exhibits declared (B), A is missing


def test_broken_xref_linear_on_large_structured_doc() -> None:
    # Each heading line contains "Section N" (a self-reference); this used to be O(n^2).
    body = "# Master\n\n" + "".join(f"## {i}. Section {i}\n\nbody of section {i}.\n\n"
                                    for i in range(1, 3001))
    t0 = time.perf_counter()
    cl.lint(cl.analyze(body, "markdown"), cl._default_config())
    assert time.perf_counter() - t0 < 2.0  # ~quadratic before the prefix-index fix


def test_unused_definition_many_terms_fast() -> None:
    defs = "".join(f'"Term{i}" means definition {i}.\n' for i in range(3000))
    body = "# Defs\n\n" + defs + "\nThe Term0 appears once unquoted here.\n"
    t0 = time.perf_counter()
    findings = _lint_all(body)
    assert time.perf_counter() - t0 < 2.0  # was ~4.6s (regex compiled+scanned per term)
    # Term0 is used unquoted -> not unused; the rest are unused.
    unused = {f.message for f in findings if f.rule == "unused-definition"}
    assert not any("'Term0'" in m for m in unused)
    assert any("'Term1'" in m for m in unused)


def test_no_crash_on_adversarial_bytes() -> None:
    import random
    rng = random.Random(99)
    for _ in range(500):
        n = rng.randint(0, 2000)
        text = bytes(rng.randint(0, 255) for _ in range(n)).decode("utf-8", "replace")
        for fmt in ("markdown", "text", "html"):
            findings = _lint_all_fmt(text, fmt)
            cl.build_sarif([("f", findings)])  # serializers must not crash either


def _lint_all_fmt(text: str, fmt: str):
    cfg = cl._default_config()
    for r in cl.RULES:
        cfg.rules[r.id].enabled = True
    return cl.lint(cl.analyze(text, fmt), cfg)
