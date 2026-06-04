"""contract_lint_cli.__version__ must match the pyproject.toml version.

A hardcoded module version that drifts from the package version makes
`--version` and `--catalog json` under-report (this bit extract-cli once). Pin
them together so a release that bumps one but not the other fails CI.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import contract_lint_cli as cl  # noqa: E402


def test_version_matches_pyproject() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    assert m is not None, "could not find version in pyproject.toml"
    assert m.group(1) == cl.__version__, (
        f"pyproject version {m.group(1)!r} != contract_lint_cli.__version__ {cl.__version__!r}"
    )
