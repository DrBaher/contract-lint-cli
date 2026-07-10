"""WordprocessingML automatic list numbering.

Word stores a numbered paragraph's visible number nowhere in its text: the paragraph
carries only a `w:numPr` pointer (ilvl + numId), and the number is computed at render
time from `word/numbering.xml`. A reader that pulls only `w:t` nodes therefore produces
a silently *unnumbered* document — so a contract whose clauses Word displays as 1-20
extracts with no numbers at all, `rule_broken_xref` finds no target for an in-body
"Section 7", and reports a drafting defect in a correctly-drafted document.

Fixtures are assembled in-test from raw XML rather than committed as binaries, so the
XML that drives each behaviour is visible in the diff.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

import contract_lint_cli as cl

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def para(text: str = "", num_id: object = None, ilvl: int = 0, style: str = "") -> str:
    ppr = ""
    if num_id is not None:
        ppr = (f'<w:pPr><w:numPr><w:ilvl w:val="{ilvl}"/>'
               f'<w:numId w:val="{num_id}"/></w:numPr></w:pPr>')
    elif style:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def level(ilvl: int, fmt: str, lvl_text: str, start: int = 1) -> str:
    return (f'<w:lvl w:ilvl="{ilvl}"><w:start w:val="{start}"/>'
            f'<w:numFmt w:val="{fmt}"/><w:lvlText w:val="{lvl_text}"/></w:lvl>')


def numbering_xml(abstracts: dict, nums: dict) -> str:
    """abstracts: {abstractId: [level_xml, ...]}; nums: {numId: abstractId | (abstractId, override_xml)}"""
    parts = [f'<w:abstractNum w:abstractNumId="{aid}">{"".join(lvls)}</w:abstractNum>'
             for aid, lvls in abstracts.items()]
    for nid, spec in nums.items():
        aid, override = spec if isinstance(spec, tuple) else (spec, "")
        parts.append(f'<w:num w:numId="{nid}"><w:abstractNumId w:val="{aid}"/>{override}</w:num>')
    return f'<?xml version="1.0"?><w:numbering {W}>{"".join(parts)}</w:numbering>'


def build(path: Path, body: str, numbering: str = "", styles: str = "") -> Path:
    document = f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", document)
        if numbering:
            z.writestr("word/numbering.xml", numbering)
        if styles:
            z.writestr("word/styles.xml", styles)
    return path


def read(tmp_path: Path, body: str, numbering: str = "", styles: str = "", name: str = "c.docx"):
    return cl.read_document(str(build(tmp_path / name, body, numbering, styles)))


# ---------------------------------------------------------------------------
# Number rendering
# ---------------------------------------------------------------------------


def test_decimal_and_decimal_zero() -> None:
    assert cl._render_number("decimal", 7) == "7"
    assert cl._render_number("decimalZero", 7) == "07"


def test_letters_use_words_repeating_sequence() -> None:
    # Word renders the 27th item as "aa", not "ab".
    assert cl._to_letter(1) == "a"
    assert cl._to_letter(26) == "z"
    assert cl._to_letter(27) == "aa"
    assert cl._to_letter(28) == "bb"
    assert cl._to_letter(53) == "aaa"
    assert cl._render_number("upperLetter", 2) == "B"


def test_roman() -> None:
    assert cl._to_roman(4) == "iv"
    assert cl._to_roman(9) == "ix"
    assert cl._to_roman(1987) == "mcmlxxxvii"
    assert cl._render_number("upperRoman", 6) == "VI"


def test_bullet_and_unknown_format_render_as_none() -> None:
    assert cl._render_number("bullet", 1) is None
    assert cl._render_number("ideographDigital", 1) is None


def test_none_format_renders_empty_not_none() -> None:
    # numFmt="none" is a real, supported format that contributes no visible number —
    # distinct from a bullet (skipped) and from an unsupported format (a failure).
    assert cl._render_number("none", 3) == ""


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_decimal_numbers_are_prepended(tmp_path: Path) -> None:
    nx = numbering_xml({0: [level(0, "decimal", "%1.")]}, {1: 0})
    body = "".join(para(t, num_id=1) for t in ("First clause", "Second clause", "Third clause"))
    text, fmt, numbering = read(tmp_path, body, nx)
    assert fmt == "docx"
    assert text.splitlines() == ["1. First clause", "2. Second clause", "3. Third clause"]
    assert numbering.resolved is True
    assert numbering.numbered_paragraphs == 3
    assert numbering.reason is None


def test_multilevel_numbering_resets_deeper_levels(tmp_path: Path) -> None:
    nx = numbering_xml({0: [level(0, "decimal", "%1."), level(1, "decimal", "%1.%2")]}, {1: 0})
    body = (para("Alpha", 1, 0) + para("Alpha one", 1, 1) + para("Alpha two", 1, 1)
            + para("Beta", 1, 0) + para("Beta one", 1, 1))
    text, _, _ = read(tmp_path, body, nx)
    assert text.splitlines() == [
        "1. Alpha", "1.1 Alpha one", "1.2 Alpha two", "2. Beta", "2.1 Beta one",
    ]


def test_separate_num_ids_count_independently(tmp_path: Path) -> None:
    """A nested (a)(b) exceptions list must not disturb the outer 1. 2. clause count."""
    nx = numbering_xml(
        {0: [level(0, "decimal", "%1.")], 1: [level(0, "lowerLetter", "(%1)")]},
        {1: 0, 2: 1},
    )
    body = (para("Exceptions:", 1, 0) + para("public knowledge", 2, 0)
            + para("already known", 2, 0) + para("Next clause", 1, 0))
    text, _, _ = read(tmp_path, body, nx)
    assert text.splitlines() == [
        "1. Exceptions:", "(a) public knowledge", "(b) already known", "2. Next clause",
    ]


def test_start_value_is_honoured(tmp_path: Path) -> None:
    nx = numbering_xml({0: [level(0, "decimal", "%1.", start=5)]}, {1: 0})
    text, _, _ = read(tmp_path, para("Clause", 1, 0), nx)
    assert text == "5. Clause"


def test_start_override_is_honoured(tmp_path: Path) -> None:
    nx = numbering_xml(
        {0: [level(0, "decimal", "%1.")]},
        {1: (0, '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="10"/></w:lvlOverride>')},
    )
    text, _, _ = read(tmp_path, para("Clause", 1, 0), nx)
    assert text == "10. Clause"


def test_lvl_override_replaces_format_and_text(tmp_path: Path) -> None:
    nx = numbering_xml(
        {0: [level(0, "decimal", "%1.")]},
        {1: (0, '<w:lvlOverride w:ilvl="0"><w:lvl w:ilvl="0">'
                '<w:numFmt w:val="upperRoman"/><w:lvlText w:val="Article %1"/>'
                '</w:lvl></w:lvlOverride>')},
    )
    text, _, _ = read(tmp_path, para("Confidentiality", 1, 0) + para("Term", 1, 0), nx)
    assert text.splitlines() == ["Article I Confidentiality", "Article II Term"]


def test_numbering_inherited_through_pstyle_and_basedon(tmp_path: Path) -> None:
    """Contract templates frequently number through a style, not on the paragraph."""
    nx = numbering_xml({0: [level(0, "upperRoman", "Article %1 -")]}, {3: 0})
    styles = (f'<?xml version="1.0"?><w:styles {W}>'
              '<w:style w:styleId="Base"><w:pPr><w:numPr><w:ilvl w:val="0"/>'
              '<w:numId w:val="3"/></w:numPr></w:pPr></w:style>'
              '<w:style w:styleId="Clause"><w:basedOn w:val="Base"/></w:style></w:styles>')
    body = para("Confidentiality", style="Clause") + para("Term", style="Clause")
    text, _, numbering = read(tmp_path, body, nx, styles)
    assert text.splitlines() == ["Article I - Confidentiality", "Article II - Term"]
    assert numbering.resolved is True


def test_cyclic_basedon_chain_does_not_hang(tmp_path: Path) -> None:
    nx = numbering_xml({0: [level(0, "decimal", "%1.")]}, {1: 0})
    styles = (f'<?xml version="1.0"?><w:styles {W}>'
              '<w:style w:styleId="A"><w:basedOn w:val="B"/></w:style>'
              '<w:style w:styleId="B"><w:basedOn w:val="A"/></w:style></w:styles>')
    text, _, _ = read(tmp_path, para("Body", style="A"), nx, styles)
    assert text == "Body"


def test_bullets_are_skipped_and_that_is_not_a_failure(tmp_path: Path) -> None:
    nx = numbering_xml({0: [level(0, "bullet", "-")]}, {1: 0})
    text, _, numbering = read(tmp_path, para("A bulleted item", 1, 0), nx)
    assert text == "A bulleted item"
    assert numbering.resolved is True


def test_paragraphs_in_tables_are_numbered_too(tmp_path: Path) -> None:
    nx = numbering_xml({0: [level(0, "decimal", "%1.")]}, {1: 0})
    body = (para("Intro", 1, 0)
            + f"<w:tbl><w:tr><w:tc>{para('In a cell', 1, 0)}</w:tc></w:tr></w:tbl>")
    text, _, _ = read(tmp_path, body, nx)
    assert text.splitlines() == ["1. Intro", "2. In a cell"]


def test_empty_paragraphs_keep_their_line(tmp_path: Path) -> None:
    """Line numbers are the finding's anchor; a dropped blank paragraph shifts them all."""
    text, _, _ = read(tmp_path, para("First") + para("") + para("Third"))
    assert text.splitlines() == ["First", "", "Third"]


def test_tabs_and_breaks_become_spaces(tmp_path: Path) -> None:
    body = "<w:p><w:r><w:t>A</w:t><w:tab/><w:t>B</w:t></w:r></w:p>"
    text, _, _ = read(tmp_path, body)
    assert text == "A B"


# ---------------------------------------------------------------------------
# Fail visible, not silent
# ---------------------------------------------------------------------------


def test_numpr_without_numbering_xml_is_unresolved(tmp_path: Path) -> None:
    text, _, numbering = read(tmp_path, para("Clause one", 1, 0))
    assert numbering.resolved is False
    assert "numbering.xml" in numbering.reason
    assert "Clause one" in text  # the text is still extracted


def test_unsupported_numfmt_is_unresolved(tmp_path: Path) -> None:
    nx = numbering_xml({0: [level(0, "ideographDigital", "%1.")]}, {1: 0})
    _, _, numbering = read(tmp_path, para("Clause", 1, 0), nx)
    assert numbering.resolved is False
    assert "ideographDigital" in numbering.reason


def test_malformed_numbering_xml_is_unresolved_not_unreadable(tmp_path: Path) -> None:
    _, _, numbering = read(tmp_path, para("Clause", 1, 0), "<w:numbering")
    assert numbering.resolved is False
    assert "numbering.xml" in numbering.reason


def test_missing_level_definition_is_unresolved(tmp_path: Path) -> None:
    nx = numbering_xml({0: [level(0, "decimal", "%1.")]}, {1: 0})
    _, _, numbering = read(tmp_path, para("Clause", 1, 3), nx)  # ilvl=3 is undefined
    assert numbering.resolved is False
    assert "ilvl=3" in numbering.reason


def test_document_with_no_numbered_paragraphs_is_resolved(tmp_path: Path) -> None:
    """Nothing to resolve is not a failure to resolve."""
    _, _, numbering = read(tmp_path, para("Just prose."))
    assert numbering.resolved is True
    assert numbering.numbered_paragraphs == 0
    assert numbering.reason is None


def test_non_docx_reports_numbering_as_not_applicable(tmp_path: Path) -> None:
    f = tmp_path / "c.md"
    f.write_text("## 1 Scope\n", encoding="utf-8")
    _, _, numbering = cl.read_document(str(f))
    assert numbering is None


def test_python_docx_fallback_is_reported_as_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """python-docx cannot see list numbering, so anything it returns is unresolved."""
    nx = numbering_xml({0: [level(0, "decimal", "%1.")]}, {1: 0})
    path = build(tmp_path / "c.docx", para("Clause", 1, 0), nx)

    def boom(_raw: bytes) -> object:
        raise cl.UsageError("cannot read .docx: synthetic stdlib failure")

    monkeypatch.setattr(cl, "_read_docx_stdlib", boom)
    monkeypatch.setattr(cl, "_read_docx_python_docx", lambda _p: "Clause")
    text, _, numbering = cl.read_document(str(path))
    assert text == "Clause"  # no "1." — python-docx never saw the number
    assert numbering.resolved is False
    assert "python-docx" in numbering.reason


def test_stdlib_failure_without_a_fallback_still_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = build(tmp_path / "c.docx", para("Clause"))
    monkeypatch.setattr(cl, "_read_docx_python_docx", lambda _p: None)
    monkeypatch.setattr(cl, "_read_docx_stdlib", lambda _raw: (_ for _ in ()).throw(
        cl.UsageError("cannot read .docx: synthetic stdlib failure")))
    with pytest.raises(cl.UsageError, match="synthetic stdlib failure"):
        cl.read_document(str(path))


def test_non_numeric_ilvl_does_not_crash_the_read(tmp_path: Path) -> None:
    """A corrupt/hostile paragraph level must degrade to a clean read, not escape as an
    unguarded ValueError (which the CLI's contract would mis-report as exit 1)."""
    nx = numbering_xml({0: [level(0, "decimal", "%1.")]}, {1: 0})
    body = ('<w:p><w:pPr><w:numPr><w:numId w:val="1"/><w:ilvl w:val="x"/>'
            '</w:numPr></w:pPr><w:r><w:t>Clause</w:t></w:r></w:p>')
    # Must not raise; the paragraph text is still extracted.
    text, _, numbering = read(tmp_path, body, nx)
    assert "Clause" in text
    assert isinstance(numbering.resolved, bool)


def test_non_numeric_level_start_does_not_crash(tmp_path: Path) -> None:
    nx = (f'<?xml version="1.0"?><w:numbering {W}>'
          '<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0">'
          '<w:start w:val="oops"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/>'
          '</w:lvl></w:abstractNum>'
          '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>')
    text, _, _ = read(tmp_path, para("Clause", 1, 0), nx)
    assert text == "1. Clause"  # a bad start degrades to the default of 1


def test_numbering_xml_declaring_a_dtd_is_refused(tmp_path: Path) -> None:
    """The billion-laughs guard must cover every XML part we parse, not just document.xml."""
    path = build(tmp_path / "bomb.docx", para("Clause", 1, 0),
                 '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "boom">]><w:numbering/>')
    with pytest.raises(cl.UsageError, match="numbering.xml"):
        cl.read_document(str(path))


def test_dtd_after_a_large_prolog_comment_is_still_refused(tmp_path: Path) -> None:
    """A DTD hidden behind >64KB of prolog padding must not slip past the guard: the
    scan covers the whole part, not a fixed-size head window."""
    padding = "<!-- " + ("x" * (128 * 1024)) + " -->"
    bomb = f'<?xml version="1.0"?>{padding}<!DOCTYPE x [<!ENTITY a "boom">]><w:numbering/>'
    path = build(tmp_path / "bomb.docx", para("Clause", 1, 0), bomb)
    with pytest.raises(cl.UsageError, match="numbering.xml"):
        cl.read_document(str(path))


# ---------------------------------------------------------------------------
# The trigger case, and rules that degrade rather than assert
# ---------------------------------------------------------------------------


CLAUSES = [
    "Definitions. Confidential Information means anything disclosed.",
    "Purpose of the disclosure.",
    "Term of this Agreement.",
    "Return of materials.",
    "No license is granted.",
    "Remedies for breach.",
    "Company and Other Party each hereby acknowledge the obligations herein.",
    "Governing law of this Agreement.",
]
XREF = "Nothing in Section 7 limits the foregoing."


def _autonumbered_body() -> str:
    return "".join(para(c, num_id=1) for c in CLAUSES) + para(XREF)


def _findings(tmp_path: Path, numbering: str, rule: str = "broken-xref"):
    text, fmt, num = read(tmp_path, _autonumbered_body(), numbering)
    findings = cl.lint(cl.analyze(text, fmt, num), cl._default_config())
    return [f for f in findings if f.rule == rule]


def test_resolved_autonumbering_gives_section_7_a_target(tmp_path: Path) -> None:
    """The regression: "Section 7" is a real paragraph, not a broken cross-reference."""
    nx = numbering_xml({0: [level(0, "decimal", "%1.")]}, {1: 0})
    assert _findings(tmp_path, nx) == []


def test_resolved_autonumbering_still_catches_a_genuinely_missing_target(tmp_path: Path) -> None:
    nx = numbering_xml({0: [level(0, "decimal", "%1.")]}, {1: 0})
    body = "".join(para(c, num_id=1) for c in CLAUSES[:3]) + para("See Section 99.")
    text, fmt, num = read(tmp_path, body, nx)
    found = [f for f in cl.lint(cl.analyze(text, fmt, num), cl._default_config())
             if f.rule == "broken-xref"]
    assert len(found) == 1
    assert found[0].severity == cl.SEVERITY_ERROR
    assert "not resolved" not in found[0].message


def test_unresolved_numbering_downgrades_broken_xref_to_warning(tmp_path: Path) -> None:
    found = _findings(tmp_path, "")  # no numbering.xml -> unresolved
    assert len(found) == 1
    assert found[0].severity == cl.SEVERITY_WARNING
    assert "automatic numbering that was not resolved" in found[0].message


def test_unresolved_numbering_downgrades_numbering_rule_to_warning(tmp_path: Path) -> None:
    """rule_numbering must never assert a gap in numbers it could not see."""
    body = para("1. First", num_id=None) + para("3. Third") + para("Clause", num_id=1)
    text, fmt, num = read(tmp_path, body)  # numPr present, no numbering.xml
    found = [f for f in cl.lint(cl.analyze(text, fmt, num), cl._default_config())
             if f.rule == "numbering"]
    assert len(found) == 1
    assert found[0].severity == cl.SEVERITY_WARNING
    assert "automatic numbering that was not resolved" in found[0].message


def test_degraded_finding_is_not_repromoted_by_configured_severity(tmp_path: Path) -> None:
    """`lint()` overwrites severity from config; a degraded finding must not be raised
    back to error by the rule's configured default."""
    text, fmt, num = read(tmp_path, _autonumbered_body())  # unresolved
    cfg = cl._default_config()
    assert cfg.rules["broken-xref"].severity == cl.SEVERITY_ERROR
    found = [f for f in cl.lint(cl.analyze(text, fmt, num), cfg) if f.rule == "broken-xref"]
    assert [f.severity for f in found] == [cl.SEVERITY_WARNING]


def test_config_may_still_lower_a_degraded_finding(tmp_path: Path) -> None:
    text, fmt, num = read(tmp_path, _autonumbered_body())
    cfg = cl._default_config()
    cfg.rules["broken-xref"].severity = cl.SEVERITY_WARNING
    found = [f for f in cl.lint(cl.analyze(text, fmt, num), cfg) if f.rule == "broken-xref"]
    assert [f.severity for f in found] == [cl.SEVERITY_WARNING]


def test_unresolved_numbering_does_not_trip_the_default_error_gate(tmp_path: Path) -> None:
    text, fmt, num = read(tmp_path, _autonumbered_body())
    findings = cl.lint(cl.analyze(text, fmt, num), cl._default_config())
    assert cl.gate_tripped(findings, "error") is False


# ---------------------------------------------------------------------------
# --json surface
# ---------------------------------------------------------------------------


def test_json_report_carries_numbering_resolved_true(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    nx = numbering_xml({0: [level(0, "decimal", "%1.")]}, {1: 0})
    path = build(tmp_path / "c.docx", _autonumbered_body(), nx)
    cl.main([str(path), "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["numbering_resolved"] is True
    assert report["summary"]["by_rule"].get("broken-xref") is None


def test_json_report_carries_numbering_resolved_false(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = build(tmp_path / "c.docx", _autonumbered_body())
    cl.main([str(path), "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["numbering_resolved"] is False
    assert report["summary"]["by_rule"]["broken-xref"] == 1
    assert report["summary"]["error"] == 0


def test_json_report_numbering_resolved_is_null_for_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    f = tmp_path / "c.md"
    f.write_text("## 1 Scope\n\nSee Section 1.\n", encoding="utf-8")
    cl.main([str(f), "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["numbering_resolved"] is None
