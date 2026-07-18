# Changelog

All notable changes to **contract-lint** are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Schema changes are
semver-meaningful: backward-incompatible `--json`/SARIF/rules output changes require a
major bump; new optional fields are minor additions.

## [Unreleased]

## [0.2.6] - 2026-07-18

### Fixed
- **`placeholder` missed `[Party B]`-style fill-ins.** The bracket-fill heuristic required
  every word inside the brackets to be at least two letters, so a single-letter word
  (`[Party B]`, `[Party B Jurisdiction]`, `[Exhibit A Reference]`) silently defeated the
  rule — despite `[Party A]`/`[Party B]` being the contract-ops suite's own canonical
  placeholder style (draft-cli's demo uses exactly that form). Words inside a bracketed
  fill-in may now be a single capital letter. Markdown links, footnotes (`[1]`), and
  lowercase section refs (`[see 2]`) remain exempt.

## [0.2.5] - 2026-07-18

### Fixed
- **`.docx` automatic list numbering is now resolved; `broken-xref` could previously
  report an error on a correctly-drafted document.** Word stores a numbered paragraph's
  visible number nowhere in its text — the paragraph carries only a `w:numPr` pointer
  (`ilvl` + `numId`) and the number is computed at render time from `word/numbering.xml`.
  Both readers dropped it: the stdlib reader walked `w:t` nodes, and python-docx's
  `paragraph.text` excludes list numbering just the same. A contract whose operative
  clauses Word displays as 1–20 was therefore linted as unnumbered prose, so an ordinary
  in-body cross-reference to "Section 7" had no target and was reported as a
  **`broken-xref` error — a drafting defect that existed only in our extraction**. (Such a
  false positive was nearly relayed to a counterparty as a defect in their template.)
  `rule_numbering` was blind in the same way: it could neither check an auto-numbered list
  nor report that it hadn't.

  The `.docx` reader now resolves numbering (stdlib-only): `numFmt` `decimal`,
  `decimalZero`, `lowerLetter`, `upperLetter`, `lowerRoman`, `upperRoman`, `none`; `%1`–`%9`
  substitution into `lvlText` (so `"%1.%2"` renders `2.1`); `start`, `w:startOverride` and
  per-level `w:lvlOverride`; `(numId, ilvl)` counters with deeper-level resets; numbering
  inherited through the `w:pStyle` → `w:basedOn` chain in `styles.xml` (cycle-guarded);
  Word's repeating letter sequence (`a…z, aa, bb`, not `ab`). Bullets are skipped, which is
  not a resolution failure. See [docs/reference/docx-numbering.md](docs/reference/docx-numbering.md).

### Added
- **`numbering_resolved` in the `--json` report** (`true` / `false` / `null`), and a `--why`
  line carrying the reason and the numbered-paragraph count. `true` means every numbered
  paragraph resolved — a document with no numbered paragraphs is also `true`, since nothing
  to resolve is not a failure to resolve. `false` means `numbering.xml` was absent or
  unparseable, a `numFmt` was unsupported, a level definition was missing, or the fallback
  reader was used. `null` means numbering isn't a concept for the input.
- **Rules degrade instead of asserting.** When `numbering_resolved` is `false`, `broken-xref`
  and `numbering` findings are emitted as **warnings** whose message names the blind spot
  ("document uses automatic numbering that was not resolved; …") rather than as errors. A
  configured severity may lower such a finding further but may not promote it back to
  `error`. Under the default `--fail-on error`, an unresolved document no longer trips CI on
  cross-references the linter never had the numbers to check.

### Changed
- **The stdlib zip/XML reader is now the preferred `.docx` path**; the `[docx]` extra
  (python-docx) is a fallback used only if the stdlib reader fails, and anything it returns
  is marked `numbering_resolved: false`. python-docx cannot see list numbering and its
  `doc.paragraphs` also skips paragraphs nested in tables, which the stdlib reader includes.
  `.docx` reading needs no optional extra and never did; the docs said otherwise.
- `_docx_xml_guard` now vets `word/numbering.xml` and `word/styles.xml` in addition to
  `word/document.xml` — resolving numbering means parsing them, so they are attack surface
  too (DTD/entity declarations refused; decompressed-size cap enforced).
- `w:tab` and `w:br` inside a paragraph now render as a space rather than being dropped.
- **Schema (`docs/spec/lint-output.schema.json`):** `numbering_resolved` is a new required
  property of the report object. The report is always emitted with it, so producers and
  consumers of the current version are unaffected; validating *older* output against the
  new schema will fail on the missing key.

## [0.2.4] - 2026-06-04

### Fixed
- **CI "Locale-safe" check fixed; defensive output hardening.** The check had
  been red since 0.2.3 — but `demo` was never crashing. The step runs under
  `bash -e`, where `demo > /dev/null; test $? -le 1` aborts at the demo's *exit-1
  gate trip* (correct behaviour on the flawed sample) before the `; test` can
  run; switched to `demo ... || test $? -le 1` so the gate trip is tolerated
  while a real crash (exit ≥ 2) still fails the check. Separately, as defensive
  hardening, `_configure_streams` now forces UTF-8 with
  `errors="backslashreplace"` so human output (which carries a few non-ASCII
  glyphs) can never raise `UnicodeEncodeError` under a C/POSIX locale; JSON
  output stays `ensure_ascii`. Adds regression tests for the gate exit and the
  `bash -e` check idiom.

## [0.2.3] - 2026-06-03

### Fixed — robustness/correctness from a follow-up source audit
- **Invalid regex in the config `ignore` list now exits 2 (usage), not 1 with a traceback.**
  `_apply_config_file` appended `ignore` entries as raw strings without validation; the only
  compile site was `lint()`, so a malformed pattern raised `re.error` mid-run and escaped as
  a traceback (exit 1) instead of the documented exit 2. Patterns are now compiled at
  config-load time and a bad one raises `UsageError("invalid ignore pattern in <path>: …")`.
- **Corrupt `.docx` DEFLATE payload now exits 2 (usage), not 1 with a traceback.** The 0.2.2
  fix caught an enumerated, non-exhaustive tuple. A valid zip whose `word/document.xml` exists
  (so `_docx_xml_guard` passes) but whose DEFLATE payload is corrupt makes `z.read()` raise
  `zlib.error`, which is not an `OSError` subclass, so it dumped a traceback and exited 1. The
  stdlib reader now catches broadly and raises `UsageError`, matching the guard's posture.
- **`date-sanity` now evaluates all effective/expiry pairs, not just the first.** The rule
  latched only the first matched effective and first matched expiry date, so a later
  out-of-order expiry slipped through. It now classifies each date by its nearest preceding
  keyword and flags every expiry that precedes the earliest effective date.
- **`demo` now exits 1 when the sample trips the gate.** `cmd_demo` computed `ok` but returned
  `EXIT_OK` unconditionally; it now returns `EXIT_FINDINGS` when error-severity findings fire.

## [0.2.2] - 2026-05-31

### Fixed — security/robustness hardening from a source audit
- **ReDoS in definition scanning (`_DEFN_PARENS_RE`).** The parenthetical-definition regex
  had an ambiguous overlap between a standalone `\s` alternative inside its repeatable
  keyword group and a trailing `\s*`, both followed by a required quote. A line with `(`
  plus a long whitespace run and no closing quote triggered catastrophic backtracking (a
  4,000-space line took ~79s; the regex runs per line in `scan_definitions` with no
  timeout). The leading group is now
  `(?:(?:the|this|each|an?|collectively,?|together,?|individually,?)\s+)*` — whitespace is
  only ever a separator after a keyword, never a standalone repeatable alternative — and
  the redundant trailing `\s*` is removed. Matching is now linear: a 5,000-space line lints
  in well under a second. All real constructs (`("X")`, `(the "X")`, `(collectively, "X")`)
  still match.
- **Malformed/invalid `.docx` now exits 2 (usage), not 1 with a traceback.** The stdlib
  `.docx` reader did not catch the failures `_docx_xml_guard` deliberately defers to it —
  `zipfile.BadZipFile` (non-zip), `KeyError` (zip missing `word/document.xml`), and
  `xml.etree.ElementTree.ParseError` (malformed `document.xml`) — so each dumped a raw
  traceback and exited 1 instead of the documented exit code 2. The reader now wraps the
  read/parse in `except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError)` and raises
  `UsageError("cannot read .docx: …")`.

No rule, schema, or output-shape changes — purely security and robustness.

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
