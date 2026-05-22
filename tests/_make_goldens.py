#!/usr/bin/env python3
"""Regenerate the golden --json reports for the fixture corpus.

    python tests/_make_goldens.py

Writes tests/fixtures/golden/<name>.json for every tests/fixtures/corpus/<name>.md.
Run this whenever a rule's behavior intentionally changes, then review the diff.
"""
from __future__ import annotations

import json
from pathlib import Path

from _report import default_report

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "fixtures" / "corpus"
GOLDEN = HERE / "fixtures" / "golden"


def main() -> int:
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for md in sorted(CORPUS.glob("*.md")):
        report = default_report(md)
        out = GOLDEN / f"{md.stem}.json"
        out.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        print(f"wrote {out.relative_to(HERE.parent)}  ({report['summary']['total']} findings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
