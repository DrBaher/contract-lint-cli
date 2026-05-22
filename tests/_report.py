"""Shared helper: build the default-config --json report for a corpus file, in-process.

Used by both tests/_make_goldens.py (to write goldens) and test_golden.py (to compare),
so the two can never disagree. Config discovery is pinned to an empty XDG dir and the
path is stored as a basename, keeping goldens deterministic and machine-portable.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import contract_lint_cli as cl  # noqa: E402


def default_report(path: Path, enable: Optional[List[str]] = None,
                   fail_on: str = "error") -> Dict[str, Any]:
    os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="cl-xdg-")  # no suite-wide config leaks in
    text, fmt = cl.read_document(str(path))
    args = argparse.Namespace(config=None, enable=enable, disable=None)
    cfg = cl.load_config(str(path), args)
    analysis = cl.analyze(text, fmt)
    findings = cl.lint(analysis, cfg)
    ok = not cl.gate_tripped(findings, fail_on)
    report = cl.build_json(path.name, fmt, findings, fail_on, ok)
    report["version"] = "X.Y.Z"  # pin the volatile field so goldens survive version bumps
    return report
