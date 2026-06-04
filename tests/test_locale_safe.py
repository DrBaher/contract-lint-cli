"""Human output must not crash under a non-UTF-8 (C/POSIX) locale.

The human report carries a few non-ASCII glyphs (e.g. an em-dash). Under an
ASCII stdout codec, strict encoding would raise UnicodeEncodeError mid-write or
at shutdown-flush and surface as a non-zero crash (exit >= 2). `demo` may trip
its findings gate (exit 1), but it must never crash. Run as a subprocess so the
real stdout/stderr codecs are exercised, with UTF-8 mode forced off to emulate a
bare C locale.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "contract_lint_cli.py"


def _run_ascii(*args: str) -> subprocess.CompletedProcess:
    # Match the CI "Locale-safe" check exactly: bare C locale, nothing else.
    # (Setting PYTHONUTF8/PYTHONIOENCODING here would mask the very condition we
    # are guarding against, since it changes how the interpreter picks codecs.)
    env = dict(os.environ, LC_ALL="C", LANG="C")
    env.pop("PYTHONUTF8", None)
    env.pop("PYTHONIOENCODING", None)
    env.pop("PYTHONCOERCECLOCALE", None)
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_demo_human_does_not_crash_under_ascii_locale() -> None:
    # Mirror the CI check EXACTLY: inherit the full environment, set only
    # LC_ALL/LANG=C, send stdout to a real file (os.devnull). On failure, dump
    # the encoding-relevant env vars so the trigger is identifiable.
    env = dict(os.environ, LC_ALL="C", LANG="C")
    with open(os.devnull, "wb") as devnull:
        r = subprocess.run(
            [sys.executable, str(CLI), "demo"],
            stdout=devnull, stderr=subprocess.PIPE, text=True, env=env,
        )
    relevant = {k: os.environ.get(k) for k in (
        "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONCOERCECLOCALE",
        "PYTHONLEGACYWINDOWSSTDIO", "LC_ALL", "LANG")}
    assert r.returncode <= 1, (
        f"demo crashed under a C locale (exit {r.returncode}).\n"
        f"env: {relevant}\n"
        f"sys.stdout.encoding(parent)={sys.stdout.encoding}\n"
        f"--- stderr ---\n{r.stderr}"
    )
    assert "UnicodeEncodeError" not in r.stderr, r.stderr


def test_demo_json_is_ascii_clean_under_ascii_locale() -> None:
    r = _run_ascii("demo", "--json")
    assert r.returncode <= 1, f"demo --json crashed (exit {r.returncode}):\n{r.stderr}"


def test_version_under_ascii_locale() -> None:
    r = _run_ascii("--version")
    assert r.returncode == 0, f"--version exit {r.returncode}:\n{r.stderr}"
