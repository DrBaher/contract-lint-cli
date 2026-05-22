# Changelog

All notable changes to **contract-lint** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Schema changes are
semver-meaningful: backward-incompatible `--json`/SARIF/rules output changes require a
major bump; new optional fields are minor additions.

## [0.2.1] - 2026-05-22

### Fixed — hardening from a stress test (fuzz + 510 real CUAD contracts + seeded precision/recall)
- **ReDoS in `number-consistency`.** A long run of number-words with no closing `(digits)`
  backtracked quadratically (16k tokens → multi-second hang). The phrase continuation is now
  bounded, making matching linear. (Found by adversarial fuzzing.)
- **`numbering` perf + false positives.** An inline 8-digit amount/id (e.g. an SEC EDGAR
  document number) was read as a section number, producing an ~87-million-element "missing
  numbers" gap (a ~10s hang on one real contract). Section numbers ≥ 4 digits or > 499 are now
  ignored, and large gaps are summarized ("N numbers missing") rather than enumerated.
- **`broken-xref` is now O(n) instead of O(n²).** Section satisfaction uses a precomputed
  dotted-prefix index instead of rescanning every declared section per reference (a large
  structured contract was ~quadratic). Real-corpus throughput improved ~3.6×.
- **`broken-xref` false positives** like `Exhibit AND` (from "Exhibits AND Schedules") are
  gone: a reference id must look like an identifier (a number, single letter, or roman numeral;
  sections must contain a digit), not an English word swept up after the keyword.
- **`unused-definition` is no longer O(defs²).** It strips quoted spans once and does a fast
  substring check per term instead of compiling+scanning a regex per term over the whole
  document (a 3000-definition doc went 4.6s → ~0.1s).

No rule, schema, or output-shape changes — purely robustness, performance, and precision.
Stress results: **0 crashes** across 20k fuzz inputs and 510 real contracts; **0% false
positives** and **100% recall** on seeded synthetic clean/defective drafts.

## [0.2.0] - 2026-05-22

### Added — three new rules
- **`number-consistency`** (warning, on): a written-out amount that disagrees with its
  parenthetical figure — the classic `thirty (45) days` drafting defect. High precision:
  only the tight `<words> (<digits>)` idiom is checked, with a stdlib English-number parser.
- **`duplicate-heading`** (warning, on): two headings with the same title (a copy-paste left
  unedited) — distinct from `numbering`, which flags repeated heading *numbers*.
- **`signature-block`** (warning, **off** by default): a complete-looking contract (≥3 titled
  headings) with no signature/execution block. Opt-in — most useful as a final pre-signature
  check; noisy on clauses/fragments.

Eleven rules total. The bundled `demo` now showcases all three (it enables the opt-in
`undefined-term` and `signature-block` rules).

### Added — multi-file + CI integration
- **Multiple paths in one run:** `contract-lint a.md b.md c.md`. One path still emits a single
  `--json` report object (the v1 schema is unchanged); multiple paths emit a JSON **array** of
  those objects, and `--sarif` merges everything into one document. `--check` returns the worst
  exit code. This makes contract-lint a clean pre-commit hook and folder linter.
- **GitHub Action** (`action.yml`): a composite action that lints files/dirs, merges SARIF,
  uploads to code-scanning, and gates the build. See [`docs/recipes/github-actions.md`](docs/recipes/github-actions.md).
- **pre-commit hook** (`.pre-commit-hooks.yaml`): `id: contract-lint`. See [`docs/recipes/pre-commit.md`](docs/recipes/pre-commit.md).
- **Recipes** under `docs/recipes/` for GitHub Actions, pre-commit, and gating any CI / shell.
- **MCP server** under `mcp/` (`contract-lint-mcp`): a Model Context Protocol stdio server
  exposing `lint_contract`, `list_rules`, and `lint_demo` tools, so agents can lint via MCP.
  Shells out to the `contract-lint` binary and returns its locked JSON.

`--json`/SARIF/rules schemas are unchanged (rule ids are data, not schema; the multi-file
`--json` array is just a list of v1 reports), so this is a backward-compatible minor release.

## [0.1.0] - 2026-05-22

### Added — first release

- **The linter.** `contract-lint <file|->` checks a contract's internal consistency and
  reports findings `{rule, severity, message, line, column?, excerpt}`. Eight deterministic
  rules: `placeholder` and `broken-xref` (errors); `unused-definition`, `double-definition`,
  `numbering`, `party-consistency`, `date-sanity` (warnings, on by default); and
  `undefined-term` (warning, **off** by default — proper-noun-prone, opt-in).
- **CI gate.** Exit codes `0` clean / `1` findings at-or-above `--fail-on` / `2` bad usage;
  `--fail-on error|warning|none`, and a `--check` exit-code-only mode.
- **Machine output.** `--json` (locked, byte-stable, timestamp-free; `docs/spec/lint-output.schema.json`)
  and `--sarif` (SARIF 2.1.0 for code-scanning; `docs/spec/lint-sarif.schema.json`).
- **Discovery.** `--catalog json` (suite discovery contract, generated by walking the parser
  so it can't drift) and `contract-lint rules --json` (the rule catalog; `docs/spec/rules.schema.json`).
- **Readers.** `.md` / `.txt` / `.html` natively (stdlib); `.docx` via a stdlib zip/XML reader
  (preferring the `[docx]` extra for fidelity); `.pdf` via the `[pdf]` extra. `-` reads stdin.
- **Config & suppression.** `.contract-lint.json` (discovered by walking up) and suite-wide
  `~/.config/contract-ops/contract-lint.json` enable/disable rules, set severities, and add
  `ignore` regexes; `--enable`/`--disable` flags; eslint-style inline
  `contract-lint: disable[-line|-next-line|-file] <rule>` comments.
- **Niceties.** `contract-lint demo` (zero-config flawed-contract run, no network),
  `completion bash|zsh`, `--why` rationale on stderr, `--version`, `--no-color`
  (honors `NO_COLOR`/`FORCE_COLOR`).
- **Quality gate for the suite.** Where `compare-cli` gates *drift between versions*,
  contract-lint gates *defects within one document* — a pre-signature step in
  `extract → draft → contract-lint / compare → convert → sign`. See `docs/INTEROP.md`.
- **Tests + CI.** Fixture corpus with seeded defects + golden `--json` outputs; rule, reader,
  config, catalog, SARIF, and schema-conformance tests; `mypy --strict`; CI matrix on
  Python 3.9–3.12 across Linux/macOS/Windows; PyPI Trusted Publishing on `v*` tags.
