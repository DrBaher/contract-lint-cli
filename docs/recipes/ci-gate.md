# Recipe: gating any CI (or a shell)

contract-lint communicates through its **exit code**, so it drops into any CI system or
shell with no integration. Branch on the code, not on the text.

| Code | Meaning |
|------|---------|
| `0` | Clean — no findings at or above `--fail-on`. |
| `1` | Gate tripped — findings at or above `--fail-on` (default `error`). |
| `2` | Bad usage / unreadable input. |

## The leanest gate

```bash
contract-lint contracts/*.md --check          # prints nothing; exit code is the result
```

```bash
# Fail a build step the moment a contract has a blocking defect:
contract-lint draft.md --check || exit 1
```

## Tune the threshold

```bash
contract-lint draft.md --check --fail-on warning   # warnings fail too
contract-lint draft.md --check --fail-on none      # report-only, never fails
```

## Lint a whole folder

```bash
# Multiple paths in one run: merged report, worst exit code wins.
contract-lint contracts/*.md --check
shopt -s globstar && contract-lint contracts/**/*.md --check   # recurse (bash)

# Stop on the first defective file:
for f in contracts/*.md; do contract-lint "$f" --check || { echo "FAIL: $f"; exit 1; }; done
```

## Machine-readable triage

```bash
# Single file -> one report object; multiple files -> an array of them.
contract-lint draft.md --json | jq '{ok, summary, findings: [.findings[] | {rule, line, message}]}'
contract-lint contracts/*.md --json | jq '[.[] | select(.ok|not) | .path]'   # which files failed

# Count findings by rule across a corpus:
contract-lint contracts/*.md --json | jq '[.[].findings[].rule] | group_by(.) | map({(.[0]): length}) | add'
```

## GitLab CI example

```yaml
contract-lint:
  image: python:3.12-slim
  script:
    - pip install contract-lint
    - contract-lint contracts/*.md --check
  artifacts:
    when: always
    paths: [contract-lint.sarif]
    reports: { sast: contract-lint.sarif }
  before_script:
    - pip install contract-lint && contract-lint contracts/*.md --sarif > contract-lint.sarif || true
```
