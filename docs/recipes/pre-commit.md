# Recipe: pre-commit

contract-lint is a [pre-commit](https://pre-commit.com) hook — it lints any staged
contract file and blocks the commit when the gate trips.

## Setup

Add to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/DrBaher/contract-lint-cli
    rev: v0.2.0
    hooks:
      - id: contract-lint
```

Then:

```bash
pre-commit install
pre-commit run --all-files     # lint everything once
```

The hook runs `contract-lint --check` on staged `.md/.markdown/.txt/.html/.docx` files and
fails the commit on any `error`-level finding (exit `1`) or unreadable input (exit `2`).

## Customising

Override the args to change the gate or enable opt-in rules:

```yaml
      - id: contract-lint
        args: ["--check", "--fail-on", "warning", "--enable", "signature-block"]
```

Or limit which files it sees:

```yaml
      - id: contract-lint
        files: '^contracts/.*\.md$'
```

(The hook passes the staged filenames to a single `contract-lint` invocation, which lints
each and exits non-zero if any trips the gate.)
