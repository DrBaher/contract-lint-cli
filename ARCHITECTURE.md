# Architecture

contract-lint is a **deterministic, single-file, stdlib-only** linter for a contract's
internal consistency. It stands alone; within the contract-ops suite it is the
**pre-signature quality gate** — where `compare-cli` gates *drift between versions*,
contract-lint gates *defects within one document*.

```
extract → draft → contract-lint / compare → convert → sign
                  (this tool: the quality gate)
```

## Principles

1. **Stdlib only, single file.** `contract_lint_cli.py` has zero runtime dependencies. The
   core (`.md`/`.txt`/`.html`, all rules, `--json`/`--sarif`) works with nothing
   installed. `.docx`/`.pdf` reading is delegated to extract-cli's backends via optional
   extras — never reimplemented as a hard dependency.
2. **Deterministic, offline.** No model, no network, no telemetry. Every rule is a pure
   function of the document text. The `--json` report carries **no timestamp**, so the same
   input yields byte-identical output that diffs cleanly in CI (golden-file friendly).
3. **Lint the text, not a model.** A linter needs the *original* numbering, cross-references,
   and defined-term casing — so it reads the document's text directly and never consumes
   extract-cli's normalized JSON. (It can lint extract-cli's *source text* on stdin.)
4. **The exit code is the contract.** Agents and CI branch on `0`/`1`/`2`, never on the
   human-readable message. `--fail-on` chooses the gate threshold; `--check` is exit-code-only.
5. **High precision over recall.** Error-severity rules (`placeholder`, `broken-xref`) use
   conservative heuristics to keep false positives near zero; noisier checks are warnings,
   and the noisiest (`undefined-term`) ships disabled.

## File layout (the module)

`contract_lint_cli.py` is organized into labelled sections:

| Section | Responsibility |
|---|---|
| Constants / Errors | exit codes, severities, config locations; `LintError`/`UsageError`. |
| Output helpers | color (`NO_COLOR`/`FORCE_COLOR`), `--json`/`_emit_json`, `--why`, UTF-8 stream config. |
| Document readers | `read_document` + `.html` / `.docx` (stdlib zip/XML, optional python-docx) / `.pdf` (pypdf extra). |
| Findings + analysis | `Finding`, `Heading`, `analyze()` → headings + defined terms shared across rules. |
| Rules | one `rule_*` per rule id, registered in `RULES` with id/severity/default/description. |
| Config + suppression | `.contract-lint.json` discovery/merge; inline `contract-lint: disable…` comments. |
| Lint engine | `lint()` runs enabled rules, applies severity overrides, suppression, and `ignore`. |
| Output renderers | `render_table`, `build_json`, `build_sarif`. |
| Commands | `cmd_lint`, `cmd_rules`, `cmd_demo`, `cmd_completion`, hidden `cmd_complete`. |
| Catalog | `build_parser` + `build_catalog` (walks the parser so the catalog can't drift). |
| Entry point | `main()` — dispatch, `lint` as the default command, `--catalog`/`__complete` intercepts. |

## How a rule works

Each rule is `Callable[[Analysis], List[Finding]]`. `Analysis` precomputes the shared
structures (`lines`, `headings`, `definitions`) once; a rule reads what it needs and emits
findings with a 1-indexed `line` (and a `column` where it has one). The engine then:

1. runs only enabled rules (config/flags decide),
2. applies any per-rule **severity override** from config,
3. drops findings suppressed by inline comments or matched by `ignore` regexes,
4. sorts by `(line, column, rule)` for stable output,
5. computes the gate decision from `--fail-on`.

Adding a rule = write one `rule_*` function and add a `Rule(...)` entry to `RULES`. It then
appears automatically in `rules --json`, the SARIF rule metadata, config validation, and
completion — no other edits.

## Testing

`tests/` carries a fixture corpus of contracts with **seeded defects** plus **golden**
`--json` reports (regenerated with `tests/_make_goldens.py`), per-rule unit tests, reader
tests, config/suppression tests, a catalog-vs-parser drift test, a SARIF test, and a
`mypy --strict`-clean module. `make spec-check` validates every machine output against the
committed schemas in `docs/spec/` with a tiny stdlib JSON-Schema validator (no third-party
dep), so conformance runs fully offline.
