# contract-lint interop

contract-lint is the **pre-signature quality gate** of the
[contract-ops CLI suite](https://github.com/DrBaher) — a set of composable,
local-first, agent-first CLIs for end-to-end contract operations. Where
[`compare-cli`](https://github.com/DrBaher/compare-cli) gates **drift between two
versions** of a contract, contract-lint gates **defects within a single document**. It runs
*after* a draft exists and *before* it is rendered and signed:

```
template-vault → draft → contract-lint / compare → docx2pdf → sign → contract-vault
                         (lint defects / compare drift)
```

This document registers the cross-CLI data contracts contract-lint participates in. All
contracts are **JSON Schema 2020-12** and live in [`docs/spec/`](spec/).

## Where it sits in the pipeline

- **After [`draft-cli`](https://github.com/DrBaher/draft-cli):** a freshly-filled draft is
  exactly what contract-lint should check — placeholders left unfilled, cross-references that
  the fill broke, defined terms that the chosen clauses never define. Lint the draft's text
  directly:
  ```bash
  draft fill nda --vars vars.json | contract-lint - --format md --check
  ```
- **Alongside [`compare-cli`](https://github.com/DrBaher/compare-cli):** complementary gates.
  compare answers "did this version drift from the agreed one?"; contract-lint answers "is
  this one document internally sound?" Run both before signing.
- **Before [`sign-cli`](https://github.com/DrBaher/sign-cli):** a clean `contract-lint --check`
  (exit `0`) is a sensible precondition for sealing — no unfilled blanks, no dangling refs.
- **On [`extract-cli`](https://github.com/DrBaher/extract-cli) source text:** contract-lint
  lints the document's **text**, not extract's normalized JSON (it needs the original
  numbering, cross-references, and defined-term casing). To lint a `.pdf`/`.docx` you can
  either install the extra (`pip install "contract-lint[pdf]"`, which pulls in extract-cli's
  backend) or convert first and pipe the text:
  ```bash
  extract counterparty.pdf | contract-lint - --format md
  ```

## Output contracts (produced)

| Schema | Produced by | Description |
|---|---|---|
| [`lint-output.schema.json`](spec/lint-output.schema.json) | `lint --json`, `demo --json` | The locked, timestamp-free lint report (`ok`, `exit_code`, `summary`, `findings[]`). |
| [`rules.schema.json`](spec/rules.schema.json) | `rules --json` | The rule catalog (`id`, `severity`, `default_enabled`, `description`) — discover rule ids here. |
| [`lint-sarif.schema.json`](spec/lint-sarif.schema.json) | `lint --sarif`, `demo --sarif` | SARIF 2.1.0 (one run, one result per finding) for GitHub code-scanning / CI annotators. |

Each finding is `{ rule, severity, message, line, column?, excerpt }`. Rule ids are stable
identifiers; the SARIF `ruleId` is `contract-lint/<rule>`.

## How to acquire the input

contract-lint reads the document's **text**:

| Invocation | Behavior |
|---|---|
| `contract-lint file.md` (`.md`/`.txt`/`.html`) | Read natively (stdlib), no extras needed. |
| `contract-lint file.docx` | Stdlib zip/XML reader, which resolves Word's automatic list numbering (see [reference/docx-numbering.md](reference/docx-numbering.md)). The `[docx]` extra is only a fallback — python-docx cannot see list numbers. |
| `contract-lint file.pdf` | Needs the `[pdf]` extra (extract-cli's PDF backend); else a clear error. |
| `… \| contract-lint - --format md` | Read text piped on stdin (draft-cli output, `extract` text, anything). |

## Shared conventions (suite-wide)

- **Streams:** `--json`/`--sarif` → stdout (opt-in; default output is human, never mixed with
  prose). `--why` → stderr as `[why] <header>` plus indented lines. Errors → stderr.
- **Flags:** `-V/--version` (`contract-lint X.Y.Z`), `-h/--help`, `-q/--quiet/--silent`,
  `--no-color` (honors `NO_COLOR`, then `FORCE_COLOR`, then TTY autodetect).
- **Exit codes:** `0` clean · `1` findings at/above `--fail-on` · `2` bad usage / unreadable
  input. **Branch on the exit code, not on the message.**
- **Discovery:** `--catalog json` (suite contract) + `rules --json` (tool-specific extra).
- **Config dir:** suite-wide config at `~/.config/contract-ops/contract-lint.json`; project
  config at `.contract-lint.json`. (Technical identifiers never change.)
- **LLM config lookup:** `~/.config/contract-ops/llm.json` — reserved for a *future* opt-in
  rule only. contract-lint's eight shipped rules are deterministic; it never calls a model on
  any default path.

## Versioning

Schema changes are semver-meaningful: a backward-incompatible change to the `--json`/SARIF/
rules output requires a major version bump; new optional fields are minor additions. The
current output schema version is `1` (the `v1` titles in `docs/spec/`).
