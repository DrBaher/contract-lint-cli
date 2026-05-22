# Recipe: GitHub Actions

contract-lint ships a reusable composite action that lints your contracts, merges the
results into one SARIF report, uploads it to **code-scanning** (so findings show up inline
on the PR), and fails the build when the gate trips.

## Quick start

```yaml
# .github/workflows/contract-lint.yml
name: contract-lint
on: [push, pull_request]

permissions:
  contents: read
  security-events: write   # required to upload SARIF to code-scanning

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: DrBaher/contract-lint-cli@v0.2.0
        with:
          paths: contracts/        # files and/or directories
          fail-on: error           # error | warning | none
```

That installs `contract-lint` from PyPI, lints every `.md/.markdown/.txt/.html/.docx`
under `paths`, uploads `contract-lint.sarif` to code-scanning, and fails the job on any
`error`-level finding.

## Inputs

| Input | Default | Description |
|---|---|---|
| `paths` | `.` | Files and/or directories to lint (space/newline-separated). Directories are searched for contract files. |
| `fail-on` | `error` | Severity that fails the build: `error` \| `warning` \| `none`. |
| `version` | latest | Pin a `contract-lint` version, e.g. `0.2.0`. |
| `args` | — | Extra args passed through, e.g. `--enable signature-block --config .contract-lint.json`. |
| `sarif-file` | `contract-lint.sarif` | Where to write the merged SARIF. |
| `upload-sarif` | `true` | Upload to code-scanning (set `false` to skip). |

Outputs: `findings` (total count) and `exit-code` (`0` clean / `1` gate tripped).

## Without the action (plain pip)

```yaml
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install contract-lint
      - run: contract-lint contracts/*.md --check          # gate only (exit code)
      # or, with code-scanning:
      - run: contract-lint contracts/*.md --sarif > contract-lint.sarif || true
      - uses: github/codeql-action/upload-sarif@v3
        with: { sarif_file: contract-lint.sarif }
```

> `--sarif` still returns the gate exit code, so `|| true` keeps the upload step running;
> add a final `contract-lint contracts/*.md --check` step if you also want the job to fail.
