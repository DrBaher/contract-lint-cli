"""The bundled demo: zero-config, offline, several findings."""
from __future__ import annotations

import json

import pytest

import contract_lint_cli as cl


def test_demo_table_runs(capsys: pytest.CaptureFixture[str]) -> None:
    code = cl.main(["demo"])
    assert code == 0
    out = capsys.readouterr().out
    assert "demo-contract.md" in out


def test_demo_json_has_findings(capsys: pytest.CaptureFixture[str]) -> None:
    code = cl.main(["demo", "--json"])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["total"] > 5
    assert report["summary"]["error"] >= 1 and report["summary"]["warning"] >= 1


def test_demo_covers_many_rule_types(capsys: pytest.CaptureFixture[str]) -> None:
    cl.main(["demo", "--json"])
    report = json.loads(capsys.readouterr().out)
    fired = set(report["summary"]["by_rule"])
    # the demo deliberately triggers a broad spread, including the opt-in rules
    assert {"placeholder", "broken-xref", "numbering", "date-sanity",
            "number-consistency", "duplicate-heading", "signature-block"} <= fired
    assert len(fired) >= 7


def test_demo_sarif(capsys: pytest.CaptureFixture[str]) -> None:
    code = cl.main(["demo", "--sarif"])
    assert code == 0
    sarif = json.loads(capsys.readouterr().out)
    assert sarif["version"] == "2.1.0"
