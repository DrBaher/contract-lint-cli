"""`demo` must behave correctly under a non-UTF-8 (C/POSIX) locale.

Two regressions live here:
  * `demo` trips its findings gate and exits 1 (not 0), and must never crash
    (>= 2) under an ASCII locale — human output carries a few non-ASCII glyphs.
  * The CI "Locale-safe" check runs under `bash -e`, where `cmd; test $? -le 1`
    aborts at cmd's exit-1 before `test` runs. The check must use
    `cmd || test $? -le 1` so the gate trip is tolerated while a real crash
    (exit 2) still fails. This test exercises that exact idiom.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "contract_lint_cli.py"


def _run_c_locale(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, LC_ALL="C", LANG="C")
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True, text=True, env=env,
    )


def test_demo_exits_gate_not_crash_under_c_locale() -> None:
    r = _run_c_locale("demo")
    assert r.returncode == 1, f"expected gate trip (1), got {r.returncode}:\n{r.stderr}"
    assert "UnicodeEncodeError" not in r.stderr, r.stderr


def test_demo_json_under_c_locale() -> None:
    r = _run_c_locale("demo", "--json")
    assert r.returncode <= 1, f"demo --json exit {r.returncode}:\n{r.stderr}"


def test_version_under_c_locale() -> None:
    r = _run_c_locale("--version")
    assert r.returncode == 0, f"--version exit {r.returncode}:\n{r.stderr}"


def test_ci_locale_check_idiom_survives_bash_e() -> None:
    """The `|| test $? -le 1` guard must tolerate the demo's exit-1 gate trip
    under `bash -e` (a plain `; test ...` would abort first)."""
    if os.name == "nt":
        return
    cmd = (
        f'LC_ALL=C LANG=C "{sys.executable}" "{CLI}" demo > /dev/null '
        f'|| test $? -le 1'
    )
    r = subprocess.run(["bash", "-e", "-c", cmd], capture_output=True, text=True)
    assert r.returncode == 0, (
        f"bash -e check failed (rc={r.returncode}); the gate trip was not "
        f"tolerated.\n{r.stderr}"
    )
