"""Schema conformance (the `make spec-check` target): every machine output validates
against the committed schemas in docs/spec/, fully offline."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import contract_lint_cli as cl
from _report import default_report
from conftest import (
    GOLDEN,
    SPEC_DIR,
    all_corpus_files,
    assert_valid,
    load_json,
    schema_errors,
)


@pytest.mark.parametrize("md", all_corpus_files(), ids=lambda p: p.stem)
def test_live_report_conforms(md: Path, output_schema: dict) -> None:
    assert_valid(default_report(md), output_schema)


@pytest.mark.parametrize("golden", sorted(GOLDEN.glob("*.json")), ids=lambda p: p.stem)
def test_golden_conforms(golden: Path, output_schema: dict) -> None:
    assert_valid(load_json(golden), output_schema)


def test_report_with_all_rules_conforms(output_schema: dict) -> None:
    cfg = cl._default_config()
    for r in cl.RULES:
        cfg.rules[r.id].enabled = True
    findings = cl.lint(cl.analyze(cl.DEMO_CONTRACT, "markdown"), cfg)
    report = cl.build_json("demo.md", "markdown", findings, "error", False)
    assert_valid(report, output_schema)


def test_rules_json_conforms(rules_schema: dict, capsys: pytest.CaptureFixture[str]) -> None:
    cl.main(["rules", "--json"])
    assert_valid(json.loads(capsys.readouterr().out), rules_schema)


def test_demo_json_conforms(output_schema: dict, capsys: pytest.CaptureFixture[str]) -> None:
    cl.main(["demo", "--json"])
    assert_valid(json.loads(capsys.readouterr().out), output_schema)


def test_sarif_conforms(sarif_schema: dict, capsys: pytest.CaptureFixture[str]) -> None:
    cl.main(["demo", "--sarif"])
    assert_valid(json.loads(capsys.readouterr().out), sarif_schema)


@pytest.mark.parametrize("name", ["lint-output.schema.json", "rules.schema.json", "lint-sarif.schema.json"])
def test_spec_schemas_are_2020_12(name: str) -> None:
    schema = load_json(SPEC_DIR / name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert "$id" in schema and name in schema["$id"]
    assert "contract-lint-cli" in schema["$id"]


def test_validator_rejects_bad_report(output_schema: dict) -> None:
    """Sanity-check the embedded validator actually catches violations."""
    bad = {"tool": "contract-lint"}  # missing nearly everything
    assert schema_errors(bad, output_schema)
    good = default_report(GOLDEN.parent / "corpus" / "flawed_msa.md")
    mutated = json.loads(json.dumps(good))
    mutated["findings"][0]["severity"] = "critical"  # not in the severity enum
    assert schema_errors(mutated, output_schema)
