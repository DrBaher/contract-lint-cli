"""Config files (project + suite-wide), severity overrides, ignore, flags, suppression."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import contract_lint_cli as cl


def report(argv, capsys) -> dict:
    code = cl.main(argv)
    out = capsys.readouterr().out
    return json.loads(out)


def test_project_config_disables_rule(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".contract-lint.json").write_text(
        json.dumps({"rules": {"placeholder": False}}), encoding="utf-8")
    f = tmp_path / "c.md"
    f.write_text("# A\nFee is {{x}}.\n", encoding="utf-8")
    rep = report([str(f), "--json"], capsys)
    assert "placeholder" not in rep["summary"]["by_rule"]


def test_project_config_severity_override_changes_gate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # numbering is a warning by default; promote it to error so --check (fail-on=error) trips.
    (tmp_path / ".contract-lint.json").write_text(
        json.dumps({"rules": {"numbering": {"severity": "error"}}}), encoding="utf-8")
    f = tmp_path / "c.md"
    f.write_text("# A\n\n## 1 a\n\n## 3 b\n", encoding="utf-8")
    assert cl.main([str(f), "--check"]) == 1
    rep = report([str(f), "--json"], capsys)
    assert any(x["rule"] == "numbering" and x["severity"] == "error" for x in rep["findings"])


def test_config_discovered_by_walking_up(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".contract-lint.json").write_text(
        json.dumps({"rules": {"placeholder": False}}), encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    f = nested / "c.md"
    f.write_text("# A\nFee is {{x}}.\n", encoding="utf-8")
    rep = report([str(f), "--json"], capsys)
    assert "placeholder" not in rep["summary"]["by_rule"]


def test_suite_wide_config_via_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    xdg = tmp_path / "xdg"
    (xdg / "contract-ops").mkdir(parents=True)
    (xdg / "contract-ops" / "contract-lint.json").write_text(
        json.dumps({"rules": {"placeholder": False}}), encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    f = tmp_path / "c.md"
    f.write_text("# A\nFee is {{x}}.\n", encoding="utf-8")
    rep = report([str(f), "--json"], capsys)
    assert "placeholder" not in rep["summary"]["by_rule"]


def test_ignore_regex(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".contract-lint.json").write_text(
        json.dumps({"ignore": ["payment_terms"]}), encoding="utf-8")
    f = tmp_path / "c.md"
    f.write_text("# A\nFee is {{payment_terms}}. Also {{rate}}.\n", encoding="utf-8")
    rep = report([str(f), "--json"], capsys)
    # the payment_terms placeholder is dropped (its message matches); the rate one remains
    placeholders = [x for x in rep["findings"] if x["rule"] == "placeholder"]
    assert len(placeholders) == 1
    assert "rate" in placeholders[0]["message"] and "payment_terms" not in placeholders[0]["message"]


def test_invalid_ignore_pattern_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Regression: a malformed regex in the config `ignore` list must be reported as a
    # clean usage error (exit 2) at config-load time, not escape as a raw re.error
    # traceback (exit 1) when lint() compiles the pattern.
    (tmp_path / ".contract-lint.json").write_text(
        json.dumps({"ignore": ["payment[", "rate"]}), encoding="utf-8")
    f = tmp_path / "c.md"
    f.write_text("# A\nFee is {{rate}}.\n", encoding="utf-8")
    assert cl.main([str(f)]) == cl.EXIT_USAGE
    err = capsys.readouterr().err
    assert "ignore pattern" in err


def test_enable_disable_flags(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "c.md"
    f.write_text("# A\nThe Disclosing Party tells the Disclosing Party.\n", encoding="utf-8")
    base = report([str(f), "--json"], capsys)
    assert "undefined-term" not in base["summary"]["by_rule"]
    enabled = report([str(f), "--json", "--enable", "undefined-term"], capsys)
    assert "undefined-term" in enabled["summary"]["by_rule"]


def test_flags_override_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".contract-lint.json").write_text(
        json.dumps({"rules": {"numbering": True}}), encoding="utf-8")
    f = tmp_path / "c.md"
    f.write_text("# A\n\n## 1 a\n\n## 3 b\n", encoding="utf-8")
    rep = report([str(f), "--json", "--disable", "numbering"], capsys)
    assert "numbering" not in rep["summary"]["by_rule"]


def test_unknown_rule_in_config_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".contract-lint.json").write_text(
        json.dumps({"rules": {"made-up-rule": False}}), encoding="utf-8")
    f = tmp_path / "c.md"
    f.write_text("# A\nok\n", encoding="utf-8")
    assert cl.main([str(f)]) == cl.EXIT_USAGE
    assert "made-up-rule" in capsys.readouterr().err


def test_unknown_enable_rule_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "c.md"
    f.write_text("# A\nok\n", encoding="utf-8")
    assert cl.main([str(f), "--enable", "nope"]) == cl.EXIT_USAGE


def test_comment_keys_allowed_in_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".contract-lint.json").write_text(
        json.dumps({"//note": "a comment", "rules": {"//x": "ignored", "placeholder": False}}),
        encoding="utf-8")
    f = tmp_path / "c.md"
    f.write_text("# A\nFee is {{x}}.\n", encoding="utf-8")
    rep = report([str(f), "--json"], capsys)
    assert "placeholder" not in rep["summary"]["by_rule"]


def test_explicit_config_highest_precedence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".contract-lint.json").write_text(
        json.dumps({"rules": {"placeholder": False}}), encoding="utf-8")
    explicit = tmp_path / "strict.json"
    explicit.write_text(json.dumps({"rules": {"placeholder": True}}), encoding="utf-8")
    f = tmp_path / "c.md"
    f.write_text("# A\nFee is {{x}}.\n", encoding="utf-8")
    rep = report([str(f), "--json", "--config", str(explicit)], capsys)
    assert rep["summary"]["by_rule"].get("placeholder") == 1


def test_missing_explicit_config_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    f = tmp_path / "c.md"
    f.write_text("# A\nok\n", encoding="utf-8")
    assert cl.main([str(f), "--config", str(tmp_path / "nope.json")]) == cl.EXIT_USAGE


# --- inline suppression ---------------------------------------------------- #


def _fired_lines(text: str):
    cfg = cl._default_config()
    for r in cl.RULES:
        cfg.rules[r.id].enabled = True
    return [(f.line, f.rule) for f in cl.lint(cl.analyze(text, "markdown"), cfg)]


def test_inline_disable_line() -> None:
    text = "Fee {{x}}.  <!-- contract-lint: disable-line placeholder -->\nFee {{y}}.\n"
    lines = _fired_lines(text)
    assert (1, "placeholder") not in lines
    assert (2, "placeholder") in lines


def test_inline_disable_next_line() -> None:
    text = "<!-- contract-lint: disable-next-line placeholder -->\nFee {{x}}.\nFee {{y}}.\n"
    lines = _fired_lines(text)
    assert (2, "placeholder") not in lines
    assert (3, "placeholder") in lines


def test_inline_disable_file() -> None:
    text = "<!-- contract-lint: disable-file placeholder -->\nFee {{x}}.\nFee {{y}}.\n"
    assert not any(r == "placeholder" for _, r in _fired_lines(text))


def test_inline_bare_disable_suppresses_all() -> None:
    text = "## 1 a\n## 3 b  <!-- contract-lint: disable -->\n"
    assert (2, "numbering") not in _fired_lines(text)


def test_inline_trailing_comment_syntax_ignored() -> None:
    # the `-->` must not corrupt the rule token
    text = "Fee {{x}}.  <!-- contract-lint: disable-line placeholder -->\n"
    assert (1, "placeholder") not in _fired_lines(text)
