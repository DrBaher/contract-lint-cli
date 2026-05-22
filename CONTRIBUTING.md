# Contributing to contract-lint

contract-lint is part of the **contract-ops** CLI suite and follows its
[build-a-CLI playbook](https://cli.drbaher.com/build-a-cli). Read that first — it is the
binding spec for "fits the suite" (the `--catalog json` discovery contract, AGENTS/README
section order, output/exit-code rules, packaging, interop). This file is the project-local
quickstart.

## Setup

```bash
make install      # editable install with dev extras (pytest, coverage, mypy, build)
```

## The gate (must be green before any push)

```bash
make test         # full test suite (pytest)
make typecheck    # mypy --strict contract_lint_cli.py
make spec-check   # validate --json/SARIF/rules output against docs/spec schemas (offline)
make smoke        # build the wheel, install it in a clean venv, run it
```

CI runs the same gate on every push across Python 3.9–3.12 on Linux/macOS/Windows. **Never
`--no-verify` or skip hooks.** Verify any command you put in a README/AGENTS/recipe against
the live binary (`contract-lint --help` / `--catalog json` / `rules --json`) before shipping.

## Adding or changing a rule

A rule is a pure `Callable[[Analysis], List[Finding]]`:

1. Write `rule_<id>(a: Analysis) -> List[Finding]` near the other rules.
2. Register it in the `RULES` tuple with `Rule(id, severity, default_enabled, description, fn)`.
3. Add a seeded-defect fixture under `tests/fixtures/corpus/` and regenerate goldens:
   `python tests/_make_goldens.py`.
4. Run the gate. The rule appears automatically in `rules --json`, the SARIF metadata, config
   validation, and completion — no other edits.

Keep error-severity rules **high-precision** (near-zero false positives); make anything
noisy a warning, and ship genuinely noisy rules **disabled by default**.

## Output is a contract

`--json`/SARIF/`rules --json` outputs are schema'd in `docs/spec/` and validated by
`make spec-check`. Changing them is semver-meaningful (major for breaking, minor for new
optional fields). Keep the `--json` report **deterministic and timestamp-free** so goldens
stay byte-stable.

## Dev conventions (suite-wide)

- Commits: **author AND committer are `DrBaher <Drbaher@gmail.com>`** (capital D), no
  "Claude"/co-author trailer. Set repo-local `git config user.name "DrBaher"` /
  `user.email "Drbaher@gmail.com"`.
- Direct-to-`main` is fine for this work; **`git fetch` before every push**; never force-push
  `main`.
- Publishing to PyPI happens only when a `v*` tag is pushed (Trusted Publishing via
  `publish.yml`) — a deliberate, human-gated step. Use `make release VERSION=X.Y.Z` to bump,
  gate, and tag locally.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the module layout.
