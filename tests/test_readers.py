"""Document readers: .md/.txt/.html natively, .docx via stdlib, .pdf gated on the extra."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import contract_lint_cli as cl
from conftest import make_docx


def test_markdown_and_text(tmp_path: Path) -> None:
    for ext, fmt in ((".md", "markdown"), (".txt", "text"), (".markdown", "markdown")):
        f = tmp_path / f"c{ext}"
        f.write_text("Fee is {{x}}.\n", encoding="utf-8")
        text, detected = cl.read_document(str(f))
        assert detected == fmt
        assert "{{x}}" in text


def test_html_strips_tags_and_keeps_structure(tmp_path: Path) -> None:
    f = tmp_path / "c.html"
    f.write_text(
        "<html><head><style>.x{}</style></head><body>"
        "<h1>NDA</h1><p>Fee is {{amt}}.</p><p>See <b>Section 5.5</b>.</p>"
        "</body></html>",
        encoding="utf-8",
    )
    text, fmt = cl.read_document(str(f))
    assert fmt == "html"
    assert "{{amt}}" in text and "Section 5.5" in text
    assert "<style>" not in text and ".x{}" not in text


def test_docx_stdlib_reader(tmp_path: Path) -> None:
    f = make_docx(tmp_path / "c.docx", [
        "Master Agreement effective March 1, 2026.",
        "Fee is {{rate}} per hour. See Section 9.9 for details.",
    ])
    text, fmt = cl.read_document(str(f))
    assert fmt == "docx"
    assert "{{rate}}" in text and "Section 9.9" in text


def test_docx_end_to_end_lint(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = make_docx(tmp_path / "c.docx", ["Fee is {{rate}}.", "## 1 A", "## 3 B"])
    code = cl.main([str(f), "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["format"] == "docx"
    assert report["summary"]["by_rule"].get("placeholder") == 1


def test_docx_zip_bomb_guard_is_safe(tmp_path: Path) -> None:
    # A .docx that declares a DTD must be refused, not parsed.
    import zipfile
    f = tmp_path / "bomb.docx"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("word/document.xml", '<?xml version="1.0"?><!DOCTYPE x><x/>')
    with pytest.raises(cl.UsageError):
        cl.read_document(str(f))


def test_docx_non_zip_errors_cleanly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # A .docx that is not a zip at all must exit 2 (usage), not dump a BadZipFile traceback.
    f = tmp_path / "junk.docx"
    f.write_bytes(b"this is plainly not a zip file")
    with pytest.raises(cl.UsageError):
        cl.read_document(str(f))
    code = cl.main([str(f)])
    err = capsys.readouterr().err
    assert code == cl.EXIT_USAGE
    assert "docx" in err.lower()


def test_docx_zip_missing_document_xml_errors_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A valid zip with no word/document.xml must exit 2 (usage), not a KeyError traceback.
    import zipfile

    f = tmp_path / "nodoc.docx"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("word/other.xml", "<x/>")
    with pytest.raises(cl.UsageError):
        cl.read_document(str(f))
    code = cl.main([str(f)])
    assert code == cl.EXIT_USAGE
    assert "docx" in capsys.readouterr().err.lower()


def test_docx_malformed_document_xml_errors_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A valid zip whose document.xml is not well-formed XML must exit 2 (usage),
    # not an ET.ParseError traceback.
    import zipfile

    f = tmp_path / "malformed.docx"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:body><unclosed></w:body>")
    with pytest.raises(cl.UsageError):
        cl.read_document(str(f))
    code = cl.main([str(f)])
    assert code == cl.EXIT_USAGE
    assert "docx" in capsys.readouterr().err.lower()


@pytest.mark.skipif(importlib.util.find_spec("pypdf") is not None, reason="pypdf installed")
def test_pdf_without_extra_errors_clearly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "c.pdf"
    f.write_bytes(b"%PDF-1.4\n%%EOF\n")
    code = cl.main([str(f)])
    err = capsys.readouterr().err
    assert code == cl.EXIT_USAGE
    assert "pdf" in err.lower() and "extra" in err.lower()


def test_format_override(tmp_path: Path) -> None:
    f = tmp_path / "weird.contract"
    f.write_text("<p>Fee is {{x}}.</p>", encoding="utf-8")
    text, fmt = cl.read_document(str(f), override="html")
    assert fmt == "html" and "<p>" not in text


def test_unknown_extension_treated_as_text(tmp_path: Path) -> None:
    f = tmp_path / "c.rtf"
    f.write_text("Plain {{x}} content.\n", encoding="utf-8")
    text, fmt = cl.read_document(str(f))
    assert fmt == "text"
