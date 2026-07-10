# contract-lint

**Lint a contract for internal-consistency defects — before anyone signs it.** Point
it at a draft and it flags leftover placeholders, cross-references that go nowhere,
defined terms that are never defined (or never used), duplicate definitions, gaps in
section numbering, party names spelled three different ways, and impossible dates —
each as a finding with a stable rule id, a severity, and a line. It exits non-zero when
something is wrong, so a CI pipeline or an agent can gate on it.

Deterministic and offline: no model, no network, no telemetry. The same input always
produces the same byte-for-byte report, so you can diff it in CI.

- **Stdlib only.** Zero runtime dependencies; the core is fully functional with nothing installed.
- **Single file.** `contract_lint_cli.py` — no DB, no daemon, no SaaS.
- **CI-gateable.** `--check` (exit-code only), `--fail-on error|warning|none`, `--json`, and `--sarif` for code-scanning.
- **Reads the text.** `.md` / `.txt` / `.html` / `.docx` natively; `.pdf` via an optional extra. It lints the *original* numbering, cross-references, and defined-term casing — not a normalized model, and for `.docx` including the list numbers Word computes at render time rather than stores.

> **Part of the contract-ops suite — optional.** contract-lint stands on its own, but it
> also composes with the [contract-ops CLI suite](https://github.com/DrBaher): it is the
> pre-signature **quality gate** the suite was missing — where
> [`compare-cli`](https://github.com/DrBaher/compare-cli) gates *drift between versions*,
> contract-lint gates *defects within one document*. It shares the suite's agent
> conventions (`--catalog json`, `--json`, exit codes) and can lint a draft or
> extract-cli's source text. See [`docs/INTEROP.md`](docs/INTEROP.md).

---

## Run this

```bash
pipx run contract-lint demo     # zero-config: lint a deliberately-flawed sample contract
# or, installed:  pip install contract-lint && contract-lint demo
```

That lints a bundled, deliberately-broken contract (no file, no network, no model) and
prints every kind of finding. Then point it at your own draft:

```bash
contract-lint your-contract.md
contract-lint your-contract.md --check && echo "ready to sign"   # exit-code gate
```

## Where to go next

- **New here?** Keep reading — [Quick start](#quick-start) and [The rules](#the-rules).
- **Driving it from an agent?** See [`AGENTS.md`](AGENTS.md). Call `contract-lint --catalog json`
  at startup to discover commands/flags, and `contract-lint rules --json` to discover rule ids
  (don't hardcode them). The `--json` report follows [`docs/spec/lint-output.schema.json`](docs/spec/lint-output.schema.json).
  There's also an [MCP server](mcp/) (`lint_contract` / `list_rules` / `lint_demo` tools).
- **Wiring it into CI?** [`docs/recipes/`](docs/recipes/) — a [GitHub Action](docs/recipes/github-actions.md)
  (with code-scanning), a [pre-commit hook](docs/recipes/pre-commit.md), and [gating any CI/shell](docs/recipes/ci-gate.md).
- **Wiring it into the pipeline?** [`docs/INTEROP.md`](docs/INTEROP.md) — it sits as a
  pre-signature gate (after draft-cli, alongside compare-cli, before sign-cli) and emits SARIF.
- **Contributing?** [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## Install

```bash
pip install contract-lint                  # zero dependencies, fully functional on .md/.txt/.html/.docx
pip install "contract-lint[pdf]"           # + .pdf reading (pulls in extract-cli's PDF backend)
```

Requires Python 3.9+. `.md` / `.txt` / `.html` / `.docx` (and text piped on stdin) read with
no dependencies at all — the `.docx` reader resolves Word's automatic list numbering, which
python-docx cannot see. Only `.pdf` reading is delegated to
[`extract-cli`](https://github.com/DrBaher/extract-cli)'s document backend. You can also
convert first: `extract contract.pdf | contract-lint -`.

---

## Quick start

```bash
contract-lint demo                         # lint the bundled flawed sample
contract-lint draft.md                     # human table report
contract-lint draft.md --json | jq .summary
contract-lint draft.md --sarif > lint.sarif
cat draft.md | contract-lint - --format md # read from stdin

# Lint several at once (merged report, worst exit code wins):
contract-lint contracts/*.md --check

# CI gate: fail the build only on errors (default), or on warnings too:
contract-lint draft.md --check                  # exit 0 clean / 1 if errors / 2 unreadable
contract-lint draft.md --check --fail-on warning
```

---

## The rules

Each finding is `{ rule, severity, message, line, column?, excerpt }`. Discover them
live with `contract-lint rules --json`.

| Rule | Severity | Default | What it catches |
|---|---|---|---|
| `placeholder` | error | on | Leftover unfilled placeholders: `[Bracketed]`, `{{mustache}}`, `<ANGLE>`, `____` blanks, `TBD`, `[•]`. |
| `broken-xref` | error | on | A cross-reference (`Section 7.2`, `Article IV`, `Exhibit B`, `Schedule 2.1`, `clause 9.3`, `Annex 1`) that points to something not present in the document. |
| `undefined-term` | warning | **off** | A capitalized defined-style term used but never defined. Off by default (proper-noun-prone); enable it for documents with a formal definitions section. |
| `unused-definition` | warning | on | A term defined but never used afterward. |
| `double-definition` | warning | on | A term defined more than once. |
| `numbering` | warning | on | Gaps or duplicates in a heading-number sequence. |
| `duplicate-heading` | warning | on | Two headings with the same title (often a copy-paste left unedited). |
| `party-consistency` | warning | on | Defined party names used with variant spellings (`Acme Corporation` vs `Acme Corp.` vs `ACME Corporation`). |
| `date-sanity` | warning | on | Impossible or inconsistent dates (malformed, or an expiration before the effective date). |
| `number-consistency` | warning | on | A written-out amount that disagrees with its parenthetical figure, e.g. `thirty (45) days`. |
| `signature-block` | warning | **off** | A complete-looking contract with no signature/execution block. Off by default (most useful as a final pre-signature check). |

`undefined-term` and `signature-block` ship **off** — the former is the most
false-positive-prone, the latter is opinionated and noisy on fragments. Enable either per
run (`--enable undefined-term`) or in config.

---

## Output & exit codes

- **Default**: a human-readable table on **stdout**. Errors/warnings about the *run* (unreadable
  file, bad usage), `--why` rationale, and the demo banner go to **stderr**.
- **`--json`**: the locked, schema'd report on stdout ([`docs/spec/lint-output.schema.json`](docs/spec/lint-output.schema.json)).
  No timestamp — the report is byte-stable and diffable.
- **`--sarif`**: SARIF 2.1.0 on stdout for GitHub code-scanning / CI annotations
  ([`docs/spec/lint-sarif.schema.json`](docs/spec/lint-sarif.schema.json)). Mutually exclusive with `--json`.
- **`--check`**: print nothing; communicate purely via the exit code.

| Code | Meaning |
|------|---------|
| `0` | Clean — no findings at or above `--fail-on`. |
| `1` | Gate tripped — findings at or above `--fail-on` (default: `error`). |
| `2` | Bad usage / unreadable input (no such file, bad flag, `--json` + `--sarif`, a `.pdf` without the extra). |

`--fail-on error` (default) trips on errors only; `--fail-on warning` trips on any
finding; `--fail-on none` never trips (report-only). **Branch on the exit code, not on the
human-readable message.**

---

## Configuration

Optional, in precedence order (later wins): suite-wide
`~/.config/contract-ops/contract-lint.json` → project `.contract-lint.json` (found by
walking up from the linted file, like git) → `--config PATH` → `--enable`/`--disable`
flags. See [`config/contract-lint.json.example`](config/contract-lint.json.example):

```jsonc
{
  "rules": {
    "undefined-term": { "enabled": true },          // turn the opt-in rule on
    "placeholder":    { "enabled": true, "severity": "error" },
    "party-consistency": false                       // disable a rule
  },
  "ignore": ["Force Majeure", "Annex [0-9]"]         // drop findings whose message matches these regexes
}
```

```bash
contract-lint draft.md --enable undefined-term --disable numbering
```

### Inline suppression

A comment on (or above) a line suppresses findings there — eslint-style:

```markdown
Fee is {{rate}} per hour.  <!-- contract-lint: disable-line placeholder -->
<!-- contract-lint: disable-next-line broken-xref -->
See Schedule 9 for details.
<!-- contract-lint: disable-file undefined-term -->
```

`disable` / `disable-line` (this line), `disable-next-line` (the next line),
`disable-file` (the whole document). Name one or more rule ids, or omit them to suppress
all rules. Only known rule ids are honored, so trailing comment syntax (`-->`, `*/`) is ignored.

---

## Composability

```bash
# Lint a draft straight out of draft-cli, before rendering/signing:
draft fill nda --vars vars.json | contract-lint - --format md --check

# Lint the source text of any document extract-cli can read:
extract counterparty.pdf | contract-lint - --format md

# Gate a whole folder of drafts in CI (fail on the first defective one):
for f in contracts/*.md; do contract-lint "$f" --check || exit 1; done

# Emit SARIF for GitHub code-scanning:
contract-lint draft.md --sarif > contract-lint.sarif
```

In a GitHub workflow, the bundled action lints, uploads SARIF to code-scanning, and gates:

```yaml
- uses: DrBaher/contract-lint-cli@v0.2.0
  with: { paths: contracts/, fail-on: error }   # needs permissions: security-events: write
```

It's also a pre-commit hook (`id: contract-lint`). See [`docs/recipes/`](docs/recipes/).

---

## Shell completion

```bash
eval "$(contract-lint completion bash)"   # bash
eval "$(contract-lint completion zsh)"    # zsh
```

(There is also a hidden `contract-lint __complete …` helper that the scripts call.)

---

## Interop

The cross-CLI contracts live under [`docs/spec/`](docs/spec/) as JSON Schema 2020-12 and
are registered in [`docs/INTEROP.md`](docs/INTEROP.md):

- **`--json` report:** [`lint-output.schema.json`](docs/spec/lint-output.schema.json)
- **rule catalog:** [`rules.schema.json`](docs/spec/rules.schema.json) (`rules --json`)
- **SARIF:** [`lint-sarif.schema.json`](docs/spec/lint-sarif.schema.json) (`--sarif`)

contract-lint never calls a model. A future opt-in LLM rule (off by default, never on a hot
path) would reuse the suite's shared `~/.config/contract-ops/llm.json`.

---

## Development

```bash
make install      # editable install with dev extras
make test         # full test suite
make typecheck    # mypy --strict
make coverage     # tests under coverage + report
make build        # wheel + sdist
make smoke        # build, install the wheel in a clean venv, run it
make spec-check   # validate --json/SARIF/rules output against docs/spec schemas (offline)
```

See [`ARCHITECTURE.md`](ARCHITECTURE.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

[MIT](LICENSE) © DrBaher
