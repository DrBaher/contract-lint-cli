"""CLI surface: version, dispatch, exit codes, stdin, output streams."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

import contract_lint_cli as cl


def run(argv, capsys):
    code = cl.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(["--version"], capsys)
    assert code == 0
    assert out.strip() == f"contract-lint {cl.__version__}"


def test_no_args_prints_help_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run([], capsys)
    assert code == cl.EXIT_USAGE


def test_catalog_intercept(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(["--catalog", "json"], capsys)
    assert code == 0
    cat = json.loads(out)
    assert cat["name"] == "contract-lint" and cat["bin"] == "contract-lint"
    assert {c["name"] for c in cat["commands"]} == {"lint", "rules", "demo", "completion"}


def test_catalog_bad_format(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(["--catalog", "yaml"], capsys)
    assert code == cl.EXIT_USAGE
    assert "json" in err


def test_default_command_is_lint(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "c.md"
    f.write_text("# Clean\n\n## 1. Term\nAll good here.\n", encoding="utf-8")
    # `contract-lint <file>` and a leading flag both route to lint.
    code, out, err = run([str(f)], capsys)
    assert code == 0
    code, out, err = run(["--json", str(f)], capsys)
    assert code == 0
    assert json.loads(out)["tool"] == "contract-lint"


def test_global_flag_before_subcommand_not_misrouted(capsys: pytest.CaptureFixture[str]) -> None:
    # `--no-color demo` must run the demo subcommand, not lint a file named "demo".
    # (The demo sample is deliberately flawed, so the gate trips -> EXIT_FINDINGS.)
    code, out, err = run(["--no-color", "demo"], capsys)
    assert code == cl.EXIT_FINDINGS
    assert "demo-contract.md" in out


def test_missing_file_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run([str(tmp_path / "nope.md")], capsys)
    assert code == cl.EXIT_USAGE
    assert "no such file" in err


def test_directory_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run([str(tmp_path)], capsys)
    assert code == cl.EXIT_USAGE


def test_json_and_sarif_mutually_exclusive(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "c.md"
    f.write_text("# X\nok\n", encoding="utf-8")
    code, out, err = run([str(f), "--json", "--sarif"], capsys)
    assert code == cl.EXIT_USAGE
    assert "mutually exclusive" in err


def test_check_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clean = tmp_path / "clean.md"
    clean.write_text("# A\n\n## 1. T\nFine.\n", encoding="utf-8")
    dirty = tmp_path / "dirty.md"
    dirty.write_text("# A\nFee is {{x}}.\n", encoding="utf-8")  # placeholder = error
    assert run([str(clean), "--check"], capsys)[0] == 0
    assert run([str(dirty), "--check"], capsys)[0] == 1
    # --check prints nothing on stdout
    code, out, err = run([str(dirty), "--check"], capsys)
    assert out == ""


def test_fail_on_thresholds(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # numbering gap = warning only
    f = tmp_path / "w.md"
    f.write_text("# A\n\n## 1 a\n\n## 3 b\n", encoding="utf-8")
    assert run([str(f), "--check"], capsys)[0] == 0                      # default fail-on=error
    assert run([str(f), "--check", "--fail-on", "warning"], capsys)[0] == 1
    assert run([str(f), "--check", "--fail-on", "none"], capsys)[0] == 0


def test_stdin(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cl.sys, "stdin", io.TextIOWrapper(io.BytesIO(b"Fee is {{x}} dollars.\n")))
    code, out, err = run(["-", "--format", "md", "--json"], capsys)
    assert code == 1
    report = json.loads(out)
    assert report["path"] == "-"
    assert report["summary"]["by_rule"].get("placeholder") == 1


def test_no_color_strips_ansi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    f = tmp_path / "c.md"
    f.write_text("# A\nFee is {{x}}.\n", encoding="utf-8")
    code, out, err = run([str(f), "--no-color"], capsys)
    assert "\033[" not in out


def test_multi_file_json_is_array(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = tmp_path / "a.md"; a.write_text("# A\nFee is {{x}}.\n", encoding="utf-8")
    b = tmp_path / "b.md"; b.write_text("# B\n\n## 1. T\nClean.\n", encoding="utf-8")
    code, out, err = run([str(a), str(b), "--json"], capsys)
    data = json.loads(out)
    assert isinstance(data, list) and len(data) == 2
    assert data[0]["path"] == str(a) and data[0]["ok"] is False
    assert data[1]["path"] == str(b) and data[1]["ok"] is True
    assert code == 1  # worst across files


def test_multi_file_sarif_one_run_many_uris(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = tmp_path / "a.md"; a.write_text("Fee is {{x}}.\n", encoding="utf-8")
    b = tmp_path / "b.md"; b.write_text("Fee is {{y}}.\n", encoding="utf-8")
    code, out, err = run([str(a), str(b), "--sarif"], capsys)
    sarif = json.loads(out)
    runs = sarif["runs"]
    assert len(runs) == 1
    uris = {r["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] for r in runs[0]["results"]}
    assert len(uris) == 2  # one result per file, each with its own uri


def test_multi_file_check_worst_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clean = tmp_path / "c.md"; clean.write_text("# A\n\n## 1. T\nfine\n", encoding="utf-8")
    dirty = tmp_path / "d.md"; dirty.write_text("Fee {{x}}.\n", encoding="utf-8")
    assert run([str(clean), "--check"], capsys)[0] == 0
    assert run([str(clean), str(dirty), "--check"], capsys)[0] == 1


def test_unknown_flag_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "c.md"
    f.write_text("# A\nok\n", encoding="utf-8")
    code, out, err = run([str(f), "--bogus"], capsys)
    assert code == cl.EXIT_USAGE
