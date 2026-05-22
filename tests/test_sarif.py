"""SARIF 2.1.0 output: shape, schema conformance, level mapping."""
from __future__ import annotations

import json

import pytest

import contract_lint_cli as cl
from conftest import assert_valid


def _demo_findings():
    cfg = cl._default_config()
    cfg.rules["undefined-term"].enabled = True
    return cl.lint(cl.analyze(cl.DEMO_CONTRACT, "markdown"), cfg)


def test_sarif_validates_against_schema(sarif_schema: dict) -> None:
    sarif = cl.build_sarif("demo-contract.md", _demo_findings())
    assert_valid(sarif, sarif_schema)


def test_sarif_top_level() -> None:
    sarif = cl.build_sarif("c.md", _demo_findings())
    assert sarif["version"] == "2.1.0"
    assert "sarif" in sarif["$schema"]
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "contract-lint"
    assert len(run["tool"]["driver"]["rules"]) == len(cl.RULES)


def test_sarif_results_map_findings() -> None:
    findings = _demo_findings()
    run = cl.build_sarif("c.md", findings)["runs"][0]
    assert len(run["results"]) == len(findings)
    for f, r in zip(findings, run["results"]):
        assert r["ruleId"] == f"contract-lint/{f.rule}"
        assert r["level"] in ("error", "warning", "note")
        assert r["locations"][0]["physicalLocation"]["region"]["startLine"] == f.line


def test_sarif_rule_metadata_levels() -> None:
    run = cl.build_sarif("c.md", [])["runs"][0]
    by_id = {r["id"]: r for r in run["tool"]["driver"]["rules"]}
    for r in cl.RULES:
        meta = by_id[f"contract-lint/{r.id}"]
        assert meta["defaultConfiguration"]["level"] == r.severity
        assert meta["name"] == r.id


def test_cli_sarif_path(capsys: pytest.CaptureFixture[str], tmp_path) -> None:
    f = tmp_path / "c.md"
    f.write_text("# A\nFee is {{x}}.\n", encoding="utf-8")
    code = cl.main([str(f), "--sarif"])
    sarif = json.loads(capsys.readouterr().out)
    assert sarif["version"] == "2.1.0"
    assert sarif["runs"][0]["results"][0]["ruleId"] == "contract-lint/placeholder"


def test_sarif_uri_for_stdin() -> None:
    assert cl._path_to_uri("-") == "stdin"
