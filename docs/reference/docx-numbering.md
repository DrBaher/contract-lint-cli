# `.docx` automatic list numbering

What `contract-lint contract.docx` reads, why a naive reader silently drops the clause
numbers, and what the linter does when it can't recover them.

## Word does not store list numbers

A paragraph numbered `7.` in Word contains no `7` anywhere in its text. It carries only a
pointer:

```xml
<w:p>
  <w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="3"/></w:numPr></w:pPr>
  <w:r><w:t>Each party acknowledges …</w:t></w:r>
</w:p>
```

The visible number is computed at render time by walking `word/numbering.xml`:

```
numId → abstractNumId → per-level { numFmt, lvlText, start }
```

A reader that pulls only `w:t` nodes therefore produces a **silently unnumbered document**.
A contract whose operative clauses are numbered 1–20 in Word arrives as prose with no
numbers, and an in-body cross-reference to "Section 7" has nothing to point at. Nothing
errors — the numbers simply never existed in the text being linted.

python-docx does not save you: its `paragraph.text` excludes list numbering for the same
reason, and its `doc.paragraphs` additionally skips paragraphs nested in tables. That is why
the stdlib zip/XML reader is the preferred `.docx` path and the `[docx]` extra is only a
fallback.

## What we resolve

`_read_docx_stdlib` walks `w:body` paragraphs in document order and prepends each one's
computed number.

| Supported | Notes |
|---|---|
| `numFmt` | `decimal`, `decimalZero`, `lowerLetter`, `upperLetter`, `lowerRoman`, `upperRoman`, `none` |
| `lvlText` | `%1`–`%9` substitution, so a multi-level `"%1.%2"` renders as `2.1` |
| `start` / `w:startOverride` | Honoured per level |
| `w:lvlOverride` | Per-level `numFmt` / `lvlText` overrides |
| Level resets | A new item at level *N* restarts every deeper level |
| Style-inherited numbering | `w:pStyle` → `w:basedOn` chain in `styles.xml`; contract templates frequently number through a style rather than on the paragraph. The chain is cycle-guarded. |
| `bullet` | Skipped — a bullet has no number, and that is **not** a resolution failure |

Counters are keyed by `(numId, ilvl)`, so two lists in the same document count
independently: a nested `(a) (b)` exceptions list under its own `numId` does not disturb the
outer `1. 2. 3.` clause numbering.

Word's alphabetic sequence repeats the letter — `a … z, aa, bb, cc` — rather than counting in
base 26 (`ab`).

Every paragraph produces exactly one line, blank ones included: a finding's `line` is its
anchor, and dropping an empty paragraph would shift every line beneath it.

## Fail visible, not silent

Every `.docx` read reports whether numbering resolved. `--json` surfaces it as
`numbering_resolved`, and `--why` prints the reason.

| Value | Meaning |
|---|---|
| `true` | Every numbered paragraph resolved to its visible number. **A document with no numbered paragraphs is also `true`** — nothing to resolve is not a failure to resolve. |
| `false` | `numbering.xml` is absent or unparseable, a `numFmt` isn't supported, a level definition is missing, or the python-docx fallback reader was used. **The numbers you see in Word are not in this text.** |
| `null` | Numbering isn't a concept for this input (`.md`, `.txt`, `.html`, `.pdf`, stdin). |

Internally `read_document()` returns a `Numbering` record with `resolved`,
`numbered_paragraphs`, and a human-readable `reason` — a bare boolean is hard to debug.

## Rules degrade, they do not assert

Two rules reason about numbers. When `numbering_resolved` is `false`, both still report —
a real defect may be visible in the text that survived — but as a **warning** whose message
names the blind spot, never as an error:

- **`broken-xref`** → warning: *"… (document uses automatic numbering that was not resolved;
  cross-reference targets could not be verified)"*
- **`numbering`** → warning: *"… (document uses automatic numbering that was not resolved;
  the numbering it would check is not in the extracted text)"*

A rule may not claim a numbering gap it could not see. Because the default gate is
`--fail-on error`, an unresolved document no longer trips CI on a cross-reference the linter
never had the numbers to check.

Config may lower a degraded finding further, but it may **not** promote it back to `error`:
`lint()` takes the lower of the configured severity and the degraded one.

## Security

`numbering.xml` and `styles.xml` are parsed, so they are attack surface alongside
`document.xml`. All three are vetted by `_docx_xml_guard` before parsing: any part declaring
a `<!DOCTYPE>` or `<!ENTITY>` is refused (internal-entity expansion — the "billion laughs"
denial of service), as is any part that decompresses past `MAX_DECOMPRESSED_BYTES`.

## History

Through v0.2.4 the reader dropped list numbering entirely. A correctly-drafted contract whose
clauses were auto-numbered 1–20 in Word, containing an ordinary in-body reference to
"Section 7", was reported as a `broken-xref` **error** — a drafting defect that existed only
in the extraction. See [CHANGELOG.md](../../CHANGELOG.md).
