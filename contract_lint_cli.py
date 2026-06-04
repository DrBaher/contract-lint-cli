#!/usr/bin/env python3
"""contract-lint — a deterministic linter that checks a contract's INTERNAL
consistency and surfaces defects with CI-gateable exit codes. Single-file,
stdlib-only.

Point it at a contract (.md/.txt/.html natively; .docx/.pdf via optional extras)
and it reports leftover placeholders, broken cross-references, undefined or unused
defined terms, duplicate definitions, heading-number gaps, inconsistent party
spellings, and impossible dates — each as a finding with a stable rule id, a
severity, a line, and an excerpt. Every check is deterministic: no model, no
network, byte-stable output you can diff in CI.

Stands alone, and also composes with the contract-ops CLI suite: it is the
pre-signature quality gate (compare-cli gates *drift* between versions;
contract-lint gates *defects within one document*), shares the suite's agent
conventions (`--catalog json`, `--json`, exit codes), and can read a draft or
extract-cli's source text. See docs/INTEROP.md.

Exit codes: 0 clean · 1 findings at/above --fail-on · 2 bad usage / unreadable input.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import importlib.util
import io
import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

__version__ = "0.2.4"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLI_NAME = "contract-lint"

# Exit codes (the CI gate; documented in --catalog json and AGENTS.md):
EXIT_OK = 0       # clean — no findings at/above --fail-on
EXIT_FINDINGS = 1  # gate tripped — findings at/above --fail-on
EXIT_USAGE = 2     # bad usage / unreadable input

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
_SEVERITY_RANK = {SEVERITY_WARNING: 1, SEVERITY_ERROR: 2}

FAIL_ON_CHOICES = ("error", "warning", "none")
FORMAT_CHOICES = ("auto", "md", "markdown", "txt", "text", "html", "docx", "pdf")

# Suite-wide + project-local config locations. Project config wins over suite-wide;
# CLI flags win over both.
SUITE_CONFIG_DIR = "contract-ops"            # ~/.config/contract-ops/
SUITE_CONFIG_NAME = "contract-lint.json"
PROJECT_CONFIG_NAME = ".contract-lint.json"

# Guard against decompression bombs when reading .docx (a zip).
MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024

JSONObj = Dict[str, Any]

# Output state, configured once in main() from flags + environment.
_NO_COLOR = False
_QUIET = False


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LintError(Exception):
    """User-actionable error; printed to stderr, exits 2."""


class UsageError(LintError):
    """Bad invocation / unreadable input; exits 2."""


# ---------------------------------------------------------------------------
# Output helpers (color, json, stderr, --why)
# ---------------------------------------------------------------------------


def _configure_streams() -> None:
    """Make stdout/stderr crash-proof under any locale.

    Human output carries a few non-ASCII glyphs (e.g. an em-dash). Under a
    C/POSIX locale a stream can end up with an ASCII codec, and `errors="strict"`
    would then raise `UnicodeEncodeError` mid-write or at shutdown-flush — which
    the CLI surfaces as a non-zero crash. We force UTF-8 *and* `backslashreplace`
    so encoding can never raise: if UTF-8 sticks the glyphs render normally; if
    some environment keeps an ASCII codec, unencodable chars degrade instead of
    crashing. Falls back to rewrapping the raw binary buffer if `reconfigure`
    isn't available. JSON output stays `ensure_ascii` and is unaffected."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
                continue
            except (ValueError, OSError):
                pass
        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            try:
                setattr(sys, name, io.TextIOWrapper(
                    buffer, encoding="utf-8", errors="backslashreplace",
                    line_buffering=True))
            except (ValueError, OSError):
                pass


def _color_enabled(stream: Any = None) -> bool:
    if _NO_COLOR:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    s = stream if stream is not None else sys.stdout
    isatty = getattr(s, "isatty", None)
    return bool(isatty()) if callable(isatty) else False


def _c(text: str, code: str, stream: Any = None) -> str:
    if not _color_enabled(stream):
        return text
    return f"\033[{code}m{text}\033[0m"


def _red(s: str) -> str:
    return _c(s, "31")


def _yellow(s: str) -> str:
    return _c(s, "33")


def _green(s: str) -> str:
    return _c(s, "32")


def _cyan(s: str) -> str:
    return _c(s, "36")


def _dim(s: str) -> str:
    return _c(s, "2")


def _bold(s: str) -> str:
    return _c(s, "1")


def _eprint(*parts: str) -> None:
    print(*parts, file=sys.stderr)


def _out(*parts: str) -> None:
    if _QUIET:
        return
    print(*parts)


def _emit_json(obj: Any) -> None:
    # ensure_ascii=True keeps output byte-identical under any locale (Windows / LC_ALL=C);
    # no trailing timestamp -> the report is fully deterministic and diff-stable in CI.
    sys.stdout.write(json.dumps(obj, indent=2, ensure_ascii=True) + "\n")


def _why(args: argparse.Namespace, header: str, *lines: str) -> None:
    """Structured rationale on stderr, only when --why is set."""
    if not getattr(args, "why", False):
        return
    _eprint(f"[why] {header}")
    for line in lines:
        _eprint(f"  {line}")


# ---------------------------------------------------------------------------
# Document readers — lint operates on the document's TEXT (it needs original
# numbering, cross-references, and defined-term casing), never on normalized JSON.
# .md/.txt/.html read natively (stdlib); .docx/.pdf use a best-effort stdlib reader
# and prefer the higher-fidelity optional extra (python-docx / pypdf, pulled in by
# `contract-lint[docx]` / `[pdf]`, which install extract-cli's backends) when present.
# ---------------------------------------------------------------------------


class _HTMLTextExtractor(HTMLParser):
    """Collapse HTML to plain text, inserting newlines at block boundaries so line
    numbers and heading structure survive."""

    _BLOCK = {
        "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "header", "footer", "table", "ul", "ol", "blockquote",
    }
    _SKIP = {"script", "style", "head"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        # Collapse runs of blank lines but keep line structure.
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip("\n")


def _read_html(raw_text: str) -> str:
    parser = _HTMLTextExtractor()
    try:
        parser.feed(raw_text)
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", raw_text)
    return parser.get_text()


def _docx_xml_guard(raw: bytes) -> Optional[str]:
    """Return a reason string if word/document.xml is unsafe to parse (zip bomb or a
    declared DTD/entities — the 'billion laughs' vector), else None. A legitimate
    OOXML document.xml never declares a DTD, so refusing is safe."""
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > MAX_DECOMPRESSED_BYTES:
                return f"word/document.xml decompresses to {info.file_size} bytes (over cap)"
            with z.open("word/document.xml") as f:
                head = f.read(65536)
    except Exception:
        return None  # not a valid zip / no document.xml -> let the reader report it
    if re.search(rb"<!DOCTYPE|<!ENTITY", head, re.IGNORECASE):
        return "document.xml declares a DTD/entities (XML-bomb guard)"
    return None


def _read_docx_stdlib(raw: bytes) -> str:
    import xml.etree.ElementTree as ET
    import zipfile

    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    # _docx_xml_guard returns None for a bad zip / missing document.xml ("let the reader
    # report it"), so the reader must turn those — plus malformed XML — into a clean
    # UsageError (exit 2) rather than letting a raw traceback escape (exit 1).
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            xml = z.read("word/document.xml")  # size/XML-bomb already vetted by _docx_xml_guard
        root = ET.fromstring(xml)
    except Exception as exc:
        # The enumerated catch list (BadZipFile/KeyError/ET.ParseError/OSError) is not
        # exhaustive: a valid zip whose word/document.xml exists but has a corrupt DEFLATE
        # payload makes z.read() raise zlib.error (not an OSError subclass). Catch broadly
        # and report a clean UsageError (exit 2), matching _docx_xml_guard's posture.
        raise UsageError(f"cannot read .docx: {exc}")
    paras: List[str] = []
    for p in root.iter(w + "p"):
        text = "".join(t.text or "" for t in p.iter(w + "t")).strip()
        paras.append(text)
    return "\n".join(paras)


def _read_docx(path: Optional[Path], raw: bytes) -> str:
    """Text from a .docx. Prefers python-docx (the [docx] extra) for fidelity;
    otherwise a stdlib zipfile/XML reader (always available)."""
    unsafe = _docx_xml_guard(raw)
    if unsafe is not None:
        raise UsageError(f"cannot read .docx: {unsafe}")
    if path is not None and importlib.util.find_spec("docx") is not None:
        try:
            mod = importlib.import_module("docx")
            document_cls = getattr(mod, "Document")
            doc = document_cls(str(path))
            return "\n".join((para.text or "").strip() for para in doc.paragraphs)
        except Exception:
            pass  # fall back to the stdlib reader
    return _read_docx_stdlib(raw)


def _read_pdf(raw: bytes) -> str:
    """Text from a .pdf via pypdf (the [pdf] extra). Stdlib has no reliable PDF text
    extractor, so this rule is honestly extra-gated rather than silently best-effort."""
    if importlib.util.find_spec("pypdf") is None:
        raise UsageError(
            "reading .pdf needs the optional extra: pip install \"contract-lint[pdf]\" "
            "(or convert to text first, e.g. `extract file.pdf` from extract-cli)"
        )
    try:
        mod = importlib.import_module("pypdf")
        reader_cls = getattr(mod, "PdfReader")
        reader = reader_cls(io.BytesIO(raw))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except UsageError:
        raise
    except Exception as exc:  # pragma: no cover - fidelity path
        raise UsageError(f"could not parse .pdf: {exc}")


def _resolve_format(path: Optional[Path], override: str) -> str:
    if override and override != "auto":
        return {"md": "markdown", "txt": "text"}.get(override, override)
    if path is None:
        return "text"  # stdin without --format: treat as plain text
    suffix = path.suffix.lower()
    return {
        ".md": "markdown", ".markdown": "markdown",
        ".txt": "text", ".text": "text",
        ".html": "html", ".htm": "html",
        ".docx": "docx", ".pdf": "pdf",
    }.get(suffix, "text")


def read_document(target: str, override: str = "auto") -> Tuple[str, str]:
    """Return (raw_text, format) for a path or '-' (stdin). Raises UsageError on
    unreadable input."""
    if target == "-":
        raw = sys.stdin.buffer.read()
        fmt = _resolve_format(None, override)
        path: Optional[Path] = None
    else:
        path = Path(target)
        if not path.exists():
            raise UsageError(f"no such file: {target}")
        if path.is_dir():
            raise UsageError(f"is a directory, not a contract: {target}")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise UsageError(f"cannot read {target}: {exc}")
        fmt = _resolve_format(path, override)

    if fmt == "docx":
        return _read_docx(path, raw), fmt
    if fmt == "pdf":
        return _read_pdf(raw), fmt
    text = raw.decode("utf-8", errors="replace")
    if fmt == "html":
        return _read_html(text), fmt
    return text, fmt


# ---------------------------------------------------------------------------
# Findings + document analysis
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Finding:
    rule: str
    severity: str
    message: str
    line: int
    excerpt: str
    column: Optional[int] = None

    def to_json(self) -> JSONObj:
        obj: JSONObj = {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "line": self.line,
        }
        if self.column is not None:
            obj["column"] = self.column
        obj["excerpt"] = self.excerpt
        return obj


@dataclasses.dataclass
class Heading:
    line: int
    kind: str        # section | article | exhibit | schedule | annex | appendix | plain
    number: str      # "7.2", roman "IV", letter "B", or "" for unnumbered
    title: str


# Word -> namespace used by both heading classification and cross-reference scanning.
_REF_KEYWORDS = {
    "section": "section", "sections": "section", "§": "section",
    "clause": "section", "clauses": "section",
    "article": "article", "articles": "article",
    "exhibit": "exhibit", "exhibits": "exhibit",
    "schedule": "schedule", "schedules": "schedule",
    "annex": "annex", "annexe": "annex", "annexes": "annex",
    "appendix": "appendix", "appendices": "appendix",
}

_HEADING_KEYWORD_RE = re.compile(
    r"^(Section|Article|Exhibit|Schedule|Annex|Annexe|Appendix)\s+([A-Za-z0-9][A-Za-z0-9.\-]*)",
    re.IGNORECASE,
)
_NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def _classify_heading_text(content: str) -> Optional[Heading]:
    """Parse the heading text of a heading-like line into (kind, number, title)."""
    content = content.strip()
    m = _HEADING_KEYWORD_RE.match(content)
    if m:
        kind = _REF_KEYWORDS.get(m.group(1).lower(), "section")
        number = m.group(2).rstrip(".")
        title = content[m.end():].lstrip(" .:-—–\t")
        return Heading(0, kind, number, title)
    m = _NUMBERED_RE.match(content)
    if m:
        return Heading(0, "section", m.group(1), m.group(2).strip())
    return None


def scan_headings(lines: Sequence[str]) -> List[Heading]:
    headings: List[Heading] = []
    for i, raw in enumerate(lines, 1):
        line = raw.rstrip()
        md = _MD_HEADING_RE.match(line)
        body = md.group(2) if md else line
        # An ALL-CAPS standalone keyword line ("EXHIBIT B", "ARTICLE IV") is a heading too.
        is_caps_heading = bool(re.match(r"^(SECTION|ARTICLE|EXHIBIT|SCHEDULE|ANNEX|APPENDIX)\b", body))
        if not md and not is_caps_heading and not _NUMBERED_RE.match(body):
            continue
        parsed = _classify_heading_text(body)
        if parsed is None:
            if md:
                headings.append(Heading(i, "plain", "", body.strip()))
            continue
        parsed.line = i
        headings.append(parsed)
    return headings


# Definition constructs: (the "X") / ("X") / "X" means / "X" shall mean / "X" refers to.
_DEFN_PARENS_RE = re.compile(
    r"""\(\s*(?:(?:the|this|each|an?|collectively,?|together,?|individually,?)\s+)*
        ["“]([A-Z][\w&.,'’\-/ ]{1,60}?)["”]\s*\)""",
    re.VERBOSE,
)
_DEFN_MEANS_RE = re.compile(
    r"""["“]([A-Z][\w&.,'’\-/ ]{1,60}?)["”]\s+
        (?:means|shall\s+mean|shall\s+have\s+the\s+meaning|refers?\s+to|has\s+the\s+meaning)\b""",
    re.VERBOSE,
)


def _norm_term(term: str) -> str:
    return re.sub(r"\s+", " ", term).strip()


def scan_definitions(lines: Sequence[str]) -> Dict[str, List[int]]:
    """Map each defined term to the line numbers where it is defined."""
    defs: Dict[str, List[int]] = {}
    for i, line in enumerate(lines, 1):
        for rx in (_DEFN_PARENS_RE, _DEFN_MEANS_RE):
            for m in rx.finditer(line):
                term = _norm_term(m.group(1))
                if term:
                    defs.setdefault(term, []).append(i)
    return defs


@dataclasses.dataclass
class Analysis:
    text: str
    lines: List[str]
    fmt: str
    headings: List[Heading]
    definitions: Dict[str, List[int]]

    def excerpt(self, line: int, max_len: int = 140) -> str:
        if 1 <= line <= len(self.lines):
            snippet = self.lines[line - 1].strip()
        else:
            snippet = ""
        return snippet if len(snippet) <= max_len else snippet[: max_len - 3] + "..."


def analyze(text: str, fmt: str) -> Analysis:
    lines = text.split("\n")
    return Analysis(
        text=text,
        lines=lines,
        fmt=fmt,
        headings=scan_headings(lines),
        definitions=scan_definitions(lines),
    )


# ---------------------------------------------------------------------------
# Rules — each is a pure function (Analysis) -> List[Finding] with a stable id.
# ---------------------------------------------------------------------------

_PLACEHOLDER_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("mustache", re.compile(r"\{\{[^}]{1,80}\}\}")),
    ("angle-caps", re.compile(r"<[A-Z][A-Z0-9 _\-]{1,40}>")),
    ("underscore-blank", re.compile(r"_{4,}")),
    ("token", re.compile(r"\b(?:TBD|TBA|FIXME|TKTK|\[?TODO\]?)\b")),
    ("empty-bracket", re.compile(r"\[\s*(?:[•·*xX]|\s)\s*\]")),
)
# Bracketed fill-ins like [Party Name], [Effective Date], [INSERT DATE] — but not
# markdown links [text](url), footnotes [1]/[a], or section refs [see 2].
_BRACKET_FILL_RE = re.compile(r"\[([A-Z][A-Za-z][^\]\n]{0,58})\](?!\()")
_BRACKET_FILL_OK = re.compile(r"^(?:[A-Z][A-Za-z]+ ?)+$|INSERT|TODO|NAME|DATE|PARTY|AMOUNT|ADDRESS")


def rule_placeholder(a: Analysis) -> List[Finding]:
    out: List[Finding] = []
    for i, line in enumerate(a.lines, 1):
        for _label, rx in _PLACEHOLDER_PATTERNS:
            for m in rx.finditer(line):
                out.append(Finding(
                    "placeholder", SEVERITY_ERROR,
                    f"leftover placeholder {m.group(0)!r} — unfilled before signing",
                    i, a.excerpt(i), m.start() + 1,
                ))
        for m in _BRACKET_FILL_RE.finditer(line):
            inner = m.group(1).strip()
            if _BRACKET_FILL_OK.search(inner):
                out.append(Finding(
                    "placeholder", SEVERITY_ERROR,
                    f"leftover placeholder {m.group(0)!r} — unfilled before signing",
                    i, a.excerpt(i), m.start() + 1,
                ))
    return out


def _roman_to_int(s: str) -> Optional[int]:
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    s = s.upper()
    if not s or any(ch not in vals for ch in s):
        return None
    total = 0
    prev = 0
    for ch in reversed(s):
        v = vals[ch]
        total += -v if v < prev else v
        prev = max(prev, v)
    return total


def _section_components(num: str) -> List[str]:
    return [p for p in num.split(".") if p]


def _section_prefix_index(declared: Set[str]) -> Tuple[Set[str], Set[str]]:
    """Precompute, once per document, the two membership sets that answer section
    satisfaction in O(depth) instead of O(declared) per reference (the latter is
    quadratic on big contracts). Returns (all dotted-prefixes of declared numbers,
    full declared numbers)."""
    prefixes: Set[str] = set()
    full: Set[str] = set()
    for d in declared:
        comps = _section_components(d)
        if not comps:
            continue
        full.add(".".join(comps))
        for k in range(1, len(comps) + 1):
            prefixes.add(".".join(comps[:k]))
    return prefixes, full


def _section_satisfied(ref: str, prefixes: Set[str], full: Set[str]) -> bool:
    """A section/clause id is present if a declared number has the ref as a dotted-
    component prefix (covers exact match and 'declared 7.2.1 satisfies ref 7.2'), or if
    a declared number is itself a prefix of the ref ('declared 7 satisfies ref 7.2')."""
    rc = _section_components(ref)
    if not rc:
        return True
    if ".".join(rc) in prefixes:
        return True
    return any(".".join(rc[:k]) in full for k in range(1, len(rc)))


def _plausible_ref_id(ns: str, ref: str) -> bool:
    """Reject 'references' whose id is really an English word swept up after the keyword,
    e.g. 'Exhibit AND' (from 'Exhibits AND Schedules') or 'Section HEREOF'. Sections/clauses
    must contain a digit; articles must be a number or roman; exhibits/schedules/annexes/
    appendices must be a number, a single letter, or a roman numeral."""
    if not ref:
        return False
    if ns in ("section",):
        return any(c.isdigit() for c in ref)
    if ns == "article":
        return ref.isdigit() or _roman_to_int(ref) is not None
    if any(c.isdigit() for c in ref):
        return True
    return len(ref) == 1 or _roman_to_int(ref) is not None


_XREF_RE = re.compile(
    r"\b(Sections?|Articles?|Exhibits?|Schedules?|Annexe?s?|Appendix|Appendices|[Cc]lauses?|§)\s+"
    r"([A-Za-z0-9][A-Za-z0-9.\-]*)"
)


def rule_broken_xref(a: Analysis) -> List[Finding]:
    declared: Dict[str, Set[str]] = {}
    for h in a.headings:
        if h.kind != "plain" and h.number:
            declared.setdefault(h.kind, set()).add(h.number.upper())
    # Namespaces we can check: sections/articles are structural and (almost) always
    # declared; exhibit/schedule/annex/appendix are only checked when the document
    # actually declares at least one (so we never flag an attached-but-unheaded exhibit).
    checkable = {"section", "article"} | {k for k in declared if declared[k]}
    sec_prefixes, sec_full = _section_prefix_index(declared.get("section", set()))

    out: List[Finding] = []
    for i, line in enumerate(a.lines, 1):
        for m in _XREF_RE.finditer(line):
            ns = _REF_KEYWORDS.get(m.group(1).lower(), "section")
            ref = m.group(2).rstrip(".").upper()
            if ns not in checkable or not _plausible_ref_id(ns, ref):
                continue
            present = declared.get(ns, set())
            if ns == "section":
                ok = _section_satisfied(ref, sec_prefixes, sec_full)
            elif ns == "article":
                ri = _roman_to_int(ref)
                # accept the literal id, or a declared roman whose value matches.
                ok = ref in present or (ri is not None and any(_roman_to_int(d) == ri for d in present))
            else:
                ok = ref in present
            if not ok:
                label = m.group(1).rstrip("s").title() if m.group(1) != "§" else "Section"
                out.append(Finding(
                    "broken-xref", SEVERITY_ERROR,
                    f"cross-reference to {label} {ref} which is not present in the document",
                    i, a.excerpt(i), m.start() + 1,
                ))
    return out


# Function/connector words that a greedy capitalized-run match can absorb at the FRONT of a
# term or party name ("Between Acme Corp", "The Disclosing Party"). Stripping them keeps
# variant spellings grouped and avoids treating a sentence-initial word as part of a name.
_LEADING_STOP = {
    "the", "a", "an", "this", "that", "these", "those", "each", "such", "any", "all",
    "between", "among", "by", "for", "in", "of", "to", "as", "at", "on", "and", "or",
    "with", "from", "then", "later", "now", "therefore", "whereas", "hereby", "herein",
    "both", "either", "neither", "if", "when", "upon", "per", "via", "is", "are", "be",
}
_ARTICLES = {"the", "a", "an", "this", "that", "these", "those", "each", "such", "any", "all"}


def _strip_leading(name: str, stop: Set[str]) -> str:
    words = name.split()
    while len(words) > 1 and words[0].lower() in stop:
        words = words[1:]
    return " ".join(words)


_TITLECASE_TERM_RE = re.compile(
    r"\b((?:[A-Z][a-z][A-Za-z]*)(?:\s+(?:of|and|the|to|in|for|[A-Z][a-z][A-Za-z]*)){1,3})\b"
)
_TERM_STOPWORDS = {
    "United States", "New York", "United Kingdom", "European Union",
}
_MONTHS = {
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
}


# A quoted span (straight or curly), bounded to a single line so a stray quote can't
# gobble the document. Used to strip definitions/quoted mentions when deciding "unused".
_QUOTED_SPAN_RE = re.compile(r'"[^"\n]*"|“[^”\n]*”')


def rule_undefined_term(a: Analysis) -> List[Finding]:
    """Capitalized, multi-word defined-style terms used like definitions but never
    defined. Off by default (proper-noun-prone); conservative: requires >=2 uses and a
    multi-word Title-Case phrase that ends on a defined-term-looking word."""
    defined = set(a.definitions)
    # candidate -> first-use line
    first_use: Dict[str, int] = {}
    counts: Dict[str, int] = {}
    for i, line in enumerate(a.lines, 1):
        for m in _TITLECASE_TERM_RE.finditer(line):
            term = _strip_leading(_norm_term(m.group(1)), _ARTICLES)
            words = term.split()
            if len(words) < 2 or term in _TERM_STOPWORDS:
                continue
            if any(w in _MONTHS for w in words):
                continue
            if {w.lower() for w in words} <= {"of", "and", "the", "to", "in", "for"}:
                continue
            counts[term] = counts.get(term, 0) + 1
            first_use.setdefault(term, i)
    out: List[Finding] = []
    for term, n in sorted(first_use.items()):
        if counts.get(term, 0) < 2:
            continue
        if term in defined:
            continue
        # If a longer defined term contains this candidate (or vice versa), treat as defined.
        if any(term in d or d in term for d in defined):
            continue
        at = first_use[term]
        out.append(Finding(
            "undefined-term", SEVERITY_WARNING,
            f"capitalized term {term!r} is used like a defined term (used {n} times) but is never defined",
            at, a.excerpt(at),
        ))
    return out


def rule_unused_definition(a: Analysis) -> List[Finding]:
    # Strip quoted spans once (definitions are quoted), then a term that never appears in
    # the remaining unquoted text was never *used* — only defined. One O(text) strip plus
    # an O(text) substring check per term, instead of compiling+scanning a regex per term
    # over the whole document (which was O(defs x text), quadratic on definition-heavy docs).
    unquoted = _QUOTED_SPAN_RE.sub(" ", a.text)
    out: List[Finding] = []
    for term, def_lines in sorted(a.definitions.items()):
        if term not in unquoted:
            line = def_lines[0]
            out.append(Finding(
                "unused-definition", SEVERITY_WARNING,
                f"defined term {term!r} is never used after its definition",
                line, a.excerpt(line),
            ))
    return out


def rule_double_definition(a: Analysis) -> List[Finding]:
    out: List[Finding] = []
    for term, def_lines in sorted(a.definitions.items()):
        if len(def_lines) >= 2:
            for line in def_lines[1:]:
                out.append(Finding(
                    "double-definition", SEVERITY_WARNING,
                    f"defined term {term!r} is defined {len(def_lines)}× "
                    f"(first at line {def_lines[0]})",
                    line, a.excerpt(line),
                ))
    return out


def rule_numbering(a: Analysis) -> List[Finding]:
    """Gaps or duplicates within a heading-number sequence (decimal sections at each
    level, and top-level Article romans)."""
    out: List[Finding] = []
    # group decimal-section numbers by parent prefix -> list of (last_component, line)
    groups: Dict[str, List[Tuple[int, int]]] = {}
    for h in a.headings:
        if h.kind != "section" or not h.number:
            continue
        comps = _section_components(h.number)
        if not comps or not all(c.isdigit() for c in comps):
            continue
        # A real section number is small. Skip years/amounts/ids (>=4 digits or >499) so
        # an inline "$78,560,181" or "2018" isn't read as a section — which also avoids a
        # giant phantom gap (and the cost of enumerating it).
        if any(len(c) >= 4 or int(c) > 499 for c in comps):
            continue
        parent = ".".join(comps[:-1])
        groups.setdefault(parent, []).append((int(comps[-1]), h.line))
    for parent, items in groups.items():
        out.extend(_sequence_findings(items, parent, "section"))
    # Article romans (top level only)
    art_items: List[Tuple[int, int]] = []
    for h in a.headings:
        if h.kind == "article" and h.number:
            ri = _roman_to_int(h.number)
            if ri is not None and ri <= 99:
                art_items.append((ri, h.line))
    out.extend(_sequence_findings(art_items, "", "article"))
    out.sort(key=lambda f: f.line)
    return out


def _sequence_findings(items: List[Tuple[int, int]], parent: str, kind: str) -> List[Finding]:
    if len(items) < 2:
        return []
    out: List[Finding] = []
    seen: Dict[int, int] = {}
    prefix = f"{parent}." if parent else ""
    for value, line in items:
        if value in seen:
            out.append(Finding(
                "numbering", SEVERITY_WARNING,
                f"duplicate {kind} number {prefix}{value} (also at line {seen[value]})",
                line, "",
            ))
        else:
            seen[value] = line
    ordered = sorted(seen)
    line_of = seen
    for idx in range(1, len(ordered)):
        prev, cur = ordered[idx - 1], ordered[idx]
        if cur - prev > 1:
            gap = cur - prev - 1
            # Summarize large gaps instead of enumerating every missing number (a defensive
            # cap; the section-number sanity filter already rules out astronomical gaps).
            if gap > 20:
                detail = f"{gap} numbers missing"
            else:
                detail = "missing " + ", ".join(f"{prefix}{n}" for n in range(prev + 1, cur))
            out.append(Finding(
                "numbering", SEVERITY_WARNING,
                f"{kind} numbering jumps from {prefix}{prev} to {prefix}{cur} ({detail})",
                line_of[cur], "",
            ))
    return out


# Longest-first so "Corporation" matches before "Corp", "Incorporated" before "Inc",
# etc. — otherwise "Corp" would match inside "Corporation" and invent a phantom variant.
_PARTY_SUFFIX = (
    r"(?:Incorporated|Corporation|Limited|Company|GmbH|L\.L\.C|L\.P|S\.A|N\.V|PLC|LLC|LLP|"
    r"Inc|Corp|Ltd|Co|LP|AG)"
)
# Words carry no '.' (that would let a name span a sentence boundary, e.g.
# "Exhibit B. ACME Corp"); internal periods live only in the suffix abbreviations.
_PARTY_RE = re.compile(
    r"\b([A-Z][\w&'’\-]*(?:\s+[A-Z][\w&'’\-]*){0,4}\s+" + _PARTY_SUFFIX + r")\b\.?"
)


def _party_key(name: str) -> str:
    stem = re.sub(r"\b" + _PARTY_SUFFIX + r"\b\.?", "", name, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]", "", stem.lower())


def rule_party_consistency(a: Analysis) -> List[Finding]:
    # key -> {surface_form: [lines]}
    groups: Dict[str, Dict[str, List[int]]] = {}
    for i, line in enumerate(a.lines, 1):
        for m in _PARTY_RE.finditer(line):
            surface = _strip_leading(_norm_term(m.group(1)), _LEADING_STOP)
            key = _party_key(surface)
            if len(key) < 3:
                continue
            groups.setdefault(key, {}).setdefault(surface, []).append(i)
    out: List[Finding] = []
    for _key, forms in groups.items():
        if len(forms) < 2:
            continue
        canonical = max(forms, key=lambda s: (len(forms[s]), len(s)))
        for surface, occ_lines in sorted(forms.items()):
            if surface == canonical:
                continue
            at = occ_lines[0]
            out.append(Finding(
                "party-consistency", SEVERITY_WARNING,
                f"party name {surface!r} is a variant spelling of {canonical!r}",
                at, a.excerpt(at),
            ))
    out.sort(key=lambda f: f.line)
    return out


_MONTH_INDEX = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}

_DATE_PATTERNS: Tuple["re.Pattern[str]", ...] = (
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),                               # ISO
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),                           # M/D/Y
    re.compile(r"\b([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\b"),                   # Month D, Y
    re.compile(r"\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b"),                     # D Month Y
)
_EFFECTIVE_RE = re.compile(r"effective(?:\s+(?:date|as\s+of))?|dated\s+(?:as\s+of\s+)?", re.IGNORECASE)
_EXPIRY_RE = re.compile(r"expir\w*|terminat\w*|end\s+date|through|until", re.IGNORECASE)


def _parse_date_match(rx: "re.Pattern[str]", m: "re.Match[str]") -> Tuple[Optional[dt.date], bool]:
    """Return (date, well_formed). well_formed=False means it looked like a date but the
    calendar values are impossible (e.g. month 13, day 30 of February)."""
    g = m.groups()
    try:
        if rx is _DATE_PATTERNS[0]:
            return dt.date(int(g[0]), int(g[1]), int(g[2])), True
        if rx is _DATE_PATTERNS[1]:
            return dt.date(int(g[2]), int(g[0]), int(g[1])), True
        if rx is _DATE_PATTERNS[2]:
            mi = _MONTH_INDEX.get(g[0].lower())
            if mi is None:
                return None, True  # not actually a month word ("April"); ignore non-dates
            return dt.date(int(g[2]), mi, int(g[1])), True
        mi = _MONTH_INDEX.get(g[1].lower())
        if mi is None:
            return None, True
        return dt.date(int(g[2]), mi, int(g[0])), True
    except ValueError:
        return None, False


def rule_date_sanity(a: Analysis) -> List[Finding]:
    out: List[Finding] = []
    effectives: List[Tuple[dt.date, int]] = []
    expiries: List[Tuple[dt.date, int]] = []
    for i, line in enumerate(a.lines, 1):
        for rx in _DATE_PATTERNS:
            for m in rx.finditer(line):
                date, well_formed = _parse_date_match(rx, m)
                if not well_formed:
                    out.append(Finding(
                        "date-sanity", SEVERITY_WARNING,
                        f"malformed or impossible date {m.group(0)!r}",
                        i, a.excerpt(i), m.start() + 1,
                    ))
                    continue
                if date is None:
                    continue
                before = line[: m.start()]
                # Classify by the nearest preceding keyword, not merely any match in
                # `before`: a single line can carry both an effective and an expiry date
                # (e.g. "Effective ... 2026-05-01. This expires on 2026-01-01."), so the
                # rightmost-matching keyword wins.
                eff = list(_EFFECTIVE_RE.finditer(before))
                exp = list(_EXPIRY_RE.finditer(before))
                eff_at = eff[-1].start() if eff else -1
                exp_at = exp[-1].start() if exp else -1
                if eff_at == -1 and exp_at == -1:
                    continue
                if eff_at >= exp_at:
                    effectives.append((date, i))
                else:
                    expiries.append((date, i))
    # Evaluate all matched pairs: an expiry that precedes the earliest effective date
    # is out of order. Comparing against the earliest effective date is the most
    # forgiving (a later effective date is never violated if the earliest isn't).
    if effectives:
        earliest_effective = min(effectives, key=lambda e: e[0])
        for exp_date, at in expiries:
            if exp_date < earliest_effective[0]:
                out.append(Finding(
                    "date-sanity", SEVERITY_WARNING,
                    f"expiration/termination date {exp_date.isoformat()} precedes the "
                    f"effective date {earliest_effective[0].isoformat()}",
                    at, a.excerpt(at),
                ))
    out.sort(key=lambda f: (f.line, f.column or 0))
    return out


_NUMBER_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_NUMBER_SCALES = {"thousand": 1000, "million": 1000000, "billion": 1000000000}
_NUMBER_WORDS = set(_NUMBER_ONES) | set(_NUMBER_SCALES) | {"hundred"}
# Longest-first alternation so "nineteen" wins over "nine", etc.
_NUMWORD_ALT = "|".join(sorted((re.escape(w) for w in _NUMBER_WORDS), key=len, reverse=True))
# The continuation is bounded ({0,12}) rather than unbounded (*): a real written number
# never runs longer than a handful of words, and an unbounded star backtracks
# quadratically on a long run of number-words with no closing "(digits)" (ReDoS).
_NUMBER_SEQ_RE = re.compile(
    r"\b((?:" + _NUMWORD_ALT + r")(?:[\s\-]+(?:and|" + _NUMWORD_ALT + r")){0,12})\s*\((\d{1,12})\)",
    re.IGNORECASE,
)


def _words_to_int(phrase: str) -> Optional[int]:
    """Parse an English number phrase (e.g. 'twenty-five', 'one hundred and fifty')
    to an int, or None if any token isn't a number word."""
    tokens = [t for t in re.split(r"[\s\-]+", phrase.lower().strip()) if t and t != "and"]
    if not tokens:
        return None
    total = 0
    current = 0
    for t in tokens:
        if t in _NUMBER_ONES:
            current += _NUMBER_ONES[t]
        elif t == "hundred":
            current = (current or 1) * 100
        elif t in _NUMBER_SCALES:
            total += (current or 1) * _NUMBER_SCALES[t]
            current = 0
        else:
            return None
    return total + current


def rule_number_consistency(a: Analysis) -> List[Finding]:
    """A number written out in words next to its figure in parentheses, where the two
    disagree — the classic 'thirty (45) days' drafting defect. High precision: only the
    tight `<words> (<digits>)` idiom is checked."""
    out: List[Finding] = []
    for i, line in enumerate(a.lines, 1):
        for m in _NUMBER_SEQ_RE.finditer(line):
            words, digits = m.group(1), int(m.group(2))
            value = _words_to_int(words)
            if value is not None and value != digits:
                out.append(Finding(
                    "number-consistency", SEVERITY_WARNING,
                    f"written amount '{words.strip()}' ({value}) does not match the figure ({digits})",
                    i, a.excerpt(i), m.start() + 1,
                ))
    return out


def rule_duplicate_heading(a: Analysis) -> List[Finding]:
    """Two headings with the same title — usually a copy-paste left unedited. (Distinct
    from `numbering`, which flags repeated heading *numbers*.)"""
    seen: Dict[str, Tuple[int, str]] = {}
    out: List[Finding] = []
    for h in a.headings:
        title = h.title.strip()
        key = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
        if len(key) < 3:
            continue
        if key in seen:
            out.append(Finding(
                "duplicate-heading", SEVERITY_WARNING,
                f"heading {title!r} duplicates an earlier heading (first at line {seen[key][0]})",
                h.line, a.excerpt(h.line),
            ))
        else:
            seen[key] = (h.line, title)
    return out


_SIGNATURE_RE = re.compile(
    r"in\s+witness\s+whereof|\bsignature\b|\bsigned\b|\bby:|name:|title:|/s/|"
    r"hereunto\s+set|duly\s+authoriz|executed\s+(?:this|as\s+of|by)",
    re.IGNORECASE,
)


def rule_signature_block(a: Analysis) -> List[Finding]:
    """A complete-looking contract with no signature/execution block. Off by default
    (most useful as a final pre-signature check; noisy on clauses/fragments). Only fires
    when the document has at least three titled headings."""
    if sum(1 for h in a.headings if h.title) < 3:
        return []
    if _SIGNATURE_RE.search(a.text):
        return []
    return [Finding(
        "signature-block", SEVERITY_WARNING,
        "no signature/execution block found (expected e.g. 'IN WITNESS WHEREOF', 'By:', 'Name:', 'Title:')",
        max(len(a.lines), 1), "",
    )]


# ---------------------------------------------------------------------------
# Rule registry
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    default_enabled: bool
    description: str
    check: Callable[[Analysis], List[Finding]]


RULES: Tuple[Rule, ...] = (
    Rule("placeholder", SEVERITY_ERROR, True,
         "Leftover unfilled placeholders: [Bracketed], {{mustache}}, <ANGLE>, ____ blanks, TBD, [•].",
         rule_placeholder),
    Rule("broken-xref", SEVERITY_ERROR, True,
         "A cross-reference (Section 7.2, Article IV, Exhibit B, Schedule 2.1, clause 9.3, Annex 1) "
         "that points to a section/exhibit/schedule not present in the document.",
         rule_broken_xref),
    Rule("undefined-term", SEVERITY_WARNING, False,
         "A capitalized defined-style term used but never defined. Off by default "
         "(proper-noun-prone); enable when a document uses a formal definitions section.",
         rule_undefined_term),
    Rule("unused-definition", SEVERITY_WARNING, True,
         "A term defined but never used afterward.",
         rule_unused_definition),
    Rule("double-definition", SEVERITY_WARNING, True,
         "A term defined more than once.",
         rule_double_definition),
    Rule("numbering", SEVERITY_WARNING, True,
         "Gaps or duplicates in a heading-number sequence.",
         rule_numbering),
    Rule("duplicate-heading", SEVERITY_WARNING, True,
         "Two headings with the same title (often a copy-paste left unedited).",
         rule_duplicate_heading),
    Rule("party-consistency", SEVERITY_WARNING, True,
         "Defined party names used with variant spellings.",
         rule_party_consistency),
    Rule("date-sanity", SEVERITY_WARNING, True,
         "Impossible or inconsistent dates (malformed, or expiration before effective).",
         rule_date_sanity),
    Rule("number-consistency", SEVERITY_WARNING, True,
         "A written-out amount that disagrees with its parenthetical figure, e.g. 'thirty (45) days'.",
         rule_number_consistency),
    Rule("signature-block", SEVERITY_WARNING, False,
         "A complete-looking contract with no signature/execution block. Off by default "
         "(most useful as a final pre-signature check; noisy on clauses/fragments).",
         rule_signature_block),
)
RULES_BY_ID = {r.id: r for r in RULES}


# ---------------------------------------------------------------------------
# Configuration (.contract-lint.json + ~/.config/contract-ops/) and suppression
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class RuleSetting:
    enabled: bool
    severity: str


@dataclasses.dataclass
class Config:
    rules: Dict[str, RuleSetting]
    ignore: List[str]          # regex patterns; a finding whose MESSAGE matches is dropped
    sources: List[str]         # config files actually loaded (for --why)

    def settings_for(self, rule_id: str) -> RuleSetting:
        return self.rules[rule_id]


def _default_config() -> Config:
    return Config(
        rules={r.id: RuleSetting(r.default_enabled, r.severity) for r in RULES},
        ignore=[],
        sources=[],
    )


def _config_search_paths(target: str, explicit: Optional[str]) -> List[Path]:
    """Suite-wide config first (lowest precedence), then project config discovered by
    walking up from the target's directory, then an explicit --config (highest)."""
    paths: List[Path] = []
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    suite = base / SUITE_CONFIG_DIR / SUITE_CONFIG_NAME
    if suite.is_file():
        paths.append(suite)
    start = Path.cwd() if target == "-" else Path(target).resolve().parent
    for d in [start, *start.parents]:
        candidate = d / PROJECT_CONFIG_NAME
        if candidate.is_file():
            paths.append(candidate)
            break
    if explicit:
        ep = Path(explicit)
        if not ep.is_file():
            raise UsageError(f"config file not found: {explicit}")
        paths.append(ep)
    return paths


def _apply_config_file(cfg: Config, path: Path) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UsageError(f"invalid config {path}: {exc}")
    if not isinstance(data, dict):
        raise UsageError(f"invalid config {path}: top level must be an object")
    rules = data.get("rules", {})
    if isinstance(rules, dict):
        for rule_id, spec in rules.items():
            if rule_id.startswith("//"):  # JSON has no comments; allow `//`-prefixed notes
                continue
            if rule_id not in RULES_BY_ID:
                raise UsageError(f"unknown rule in {path}: {rule_id!r}")
            setting = cfg.rules[rule_id]
            if isinstance(spec, bool):
                setting.enabled = spec
            elif isinstance(spec, dict):
                if "enabled" in spec:
                    setting.enabled = bool(spec["enabled"])
                if "severity" in spec:
                    sev = str(spec["severity"])
                    if sev not in _SEVERITY_RANK:
                        raise UsageError(f"invalid severity {sev!r} for {rule_id} in {path}")
                    setting.severity = sev
    ignore = data.get("ignore", [])
    if isinstance(ignore, list):
        for p in ignore:
            pattern = str(p)
            try:
                re.compile(pattern)
            except re.error as exc:
                raise UsageError(f"invalid ignore pattern in {path}: {exc}")
            cfg.ignore.append(pattern)
    cfg.sources.append(str(path))


def load_config(target: str, args: argparse.Namespace) -> Config:
    cfg = _default_config()
    for path in _config_search_paths(target, getattr(args, "config", None)):
        _apply_config_file(cfg, path)
    # CLI flags win over config files.
    for rule_id in getattr(args, "enable", None) or []:
        if rule_id not in RULES_BY_ID:
            raise UsageError(f"unknown rule: {rule_id!r}")
        cfg.rules[rule_id].enabled = True
    for rule_id in getattr(args, "disable", None) or []:
        if rule_id not in RULES_BY_ID:
            raise UsageError(f"unknown rule: {rule_id!r}")
        cfg.rules[rule_id].enabled = False
    return cfg


# Inline suppression (eslint-style): a line carrying a comment
#   contract-lint: disable[-line] <rules>        suppress on THIS line
#   contract-lint: disable-next-line <rules>     suppress on the NEXT line
#   contract-lint: disable-file <rules>          suppress for the whole document
# Rules are comma/space-separated rule ids; omit them (or write `all`/`*`) to suppress
# every rule. Only known rule ids are honored, so trailing comment syntax (`-->`, `*/`)
# can never corrupt the token.
_SUPPRESS_RE = re.compile(r"contract-lint:\s*(disable-next-line|disable-file|disable-line|disable)\b([^\n]*)")
_RULE_TOKEN_RE = re.compile(r"[A-Za-z*][A-Za-z0-9*-]*")


def _suppression_marker(rules_raw: str) -> Set[str]:
    tokens = {t.lower() for t in _RULE_TOKEN_RE.findall(rules_raw)}
    if "*" in tokens or "all" in tokens:
        return {"*"}
    kept = {t for t in tokens if t in RULES_BY_ID}
    return kept or {"*"}  # bare `disable` (no rule named) = suppress everything


def _parse_suppressions(lines: Sequence[str]) -> Tuple[Dict[int, Set[str]], Set[str]]:
    """Return (per_line_suppressions, file_suppressions). A marker of {'*'} means 'all'."""
    per_line: Dict[int, Set[str]] = {}
    file_level: Set[str] = set()
    for i, line in enumerate(lines, 1):
        for m in _SUPPRESS_RE.finditer(line):
            scope, marker = m.group(1), _suppression_marker(m.group(2))
            if scope == "disable-file":
                file_level |= marker
            elif scope == "disable-next-line":
                per_line.setdefault(i + 1, set()).update(marker)
            else:  # disable / disable-line -> this line
                per_line.setdefault(i, set()).update(marker)
    return per_line, file_level


def _is_suppressed(f: Finding, per_line: Dict[int, Set[str]], file_level: Set[str]) -> bool:
    if "*" in file_level or f.rule in file_level:
        return True
    marker = per_line.get(f.line)
    if marker and ("*" in marker or f.rule in marker):
        return True
    return False


# ---------------------------------------------------------------------------
# Lint engine
# ---------------------------------------------------------------------------


def lint(analysis: Analysis, cfg: Config) -> List[Finding]:
    findings: List[Finding] = []
    for rule in RULES:
        setting = cfg.settings_for(rule.id)
        if not setting.enabled:
            continue
        for f in rule.check(analysis):
            f.severity = setting.severity  # config can override severity
            findings.append(f)

    per_line, file_level = _parse_suppressions(analysis.lines)
    ignore_res = [re.compile(p) for p in cfg.ignore]
    kept: List[Finding] = []
    for f in findings:
        if _is_suppressed(f, per_line, file_level):
            continue
        if any(rx.search(f.message) for rx in ignore_res):  # match the message (predictable)
            continue
        kept.append(f)
    kept.sort(key=lambda f: (f.line, f.column or 0, f.rule))
    return kept


def _fail_threshold(fail_on: str) -> int:
    if fail_on == "none":
        return 99  # nothing trips the gate
    return _SEVERITY_RANK[fail_on]


def gate_tripped(findings: Sequence[Finding], fail_on: str) -> bool:
    threshold = _fail_threshold(fail_on)
    return any(_SEVERITY_RANK[f.severity] >= threshold for f in findings)


# ---------------------------------------------------------------------------
# Output renderers
# ---------------------------------------------------------------------------


def _summary(findings: Sequence[Finding]) -> JSONObj:
    by_rule: Dict[str, int] = {}
    errors = warnings = 0
    for f in findings:
        by_rule[f.rule] = by_rule.get(f.rule, 0) + 1
        if f.severity == SEVERITY_ERROR:
            errors += 1
        else:
            warnings += 1
    return {"error": errors, "warning": warnings, "total": len(findings), "by_rule": by_rule}


def build_json(path: str, fmt: str, findings: Sequence[Finding], fail_on: str, ok: bool) -> JSONObj:
    return {
        "tool": CLI_NAME,
        "version": __version__,
        "path": path,
        "format": fmt,
        "fail_on": fail_on,
        "ok": ok,
        "exit_code": EXIT_OK if ok else EXIT_FINDINGS,
        "summary": _summary(findings),
        "findings": [f.to_json() for f in findings],
    }


_SARIF_LEVEL = {SEVERITY_ERROR: "error", SEVERITY_WARNING: "warning"}


def _path_to_uri(path: str) -> str:
    if path == "-":
        return "stdin"
    p = Path(path)
    if p.is_absolute():
        return p.as_uri()
    return str(path).replace("\\", "/")


def build_sarif(items: Sequence[Tuple[str, Sequence[Finding]]]) -> JSONObj:
    """One SARIF run aggregating findings across one or more linted files; each result
    carries its own file URI, so multi-file output uploads cleanly to code-scanning."""
    results: List[JSONObj] = []
    for path, findings in items:
        uri = _path_to_uri(path)
        for f in findings:
            region: JSONObj = {"startLine": max(f.line, 1)}
            if f.column is not None:
                region["startColumn"] = f.column
            result: JSONObj = {
                "ruleId": f"{CLI_NAME}/{f.rule}",
                "level": _SARIF_LEVEL[f.severity],
                "message": {"text": f.message},
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {"uri": uri},
                        "region": region,
                    }
                }],
            }
            if f.excerpt:
                result["locations"][0]["physicalLocation"]["region"]["snippet"] = {"text": f.excerpt}
            results.append(result)
    rules_meta = [{
        "id": f"{CLI_NAME}/{r.id}",
        "name": r.id,
        "shortDescription": {"text": r.description},
        "defaultConfiguration": {"level": _SARIF_LEVEL[r.severity]},
    } for r in RULES]
    return {
        "version": "2.1.0",
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json",
        "runs": [{
            "tool": {"driver": {
                "name": CLI_NAME,
                "version": __version__,
                "informationUri": "https://github.com/DrBaher/contract-lint-cli",
                "rules": rules_meta,
            }},
            "results": results,
        }],
    }


def render_table(path: str, fmt: str, findings: Sequence[Finding]) -> str:
    lines: List[str] = []
    header = f"{_bold(path)} {_dim('(' + fmt + ')')}"
    lines.append(header)
    if not findings:
        lines.append(_green("  ✓ no findings"))
        return "\n".join(lines)
    for f in findings:
        loc = f"{f.line}:{f.column}" if f.column is not None else str(f.line)
        sev = _red(f.severity) if f.severity == SEVERITY_ERROR else _yellow(f.severity)
        lines.append(f"  {loc.ljust(8)} {sev.ljust(18)} {_cyan(f.rule)}  {f.message}")
        if f.excerpt:
            lines.append(f"           {_dim(f.excerpt)}")
    s = _summary(findings)
    lines.append("")
    lines.append(_dim(f"  {s['error']} error(s), {s['warning']} warning(s) in {path}"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_lint(args: argparse.Namespace) -> int:
    if getattr(args, "json", False) and getattr(args, "sarif", False):
        raise UsageError("--json and --sarif are mutually exclusive")
    targets: List[str] = list(args.path)
    fail_on = args.fail_on

    reports: List[JSONObj] = []
    sarif_items: List[Tuple[str, Sequence[Finding]]] = []
    tables: List[str] = []
    all_ok = True
    for target in targets:
        text, fmt = read_document(target, getattr(args, "format", "auto"))
        cfg = load_config(target, args)
        analysis = analyze(text, fmt)
        findings = lint(analysis, cfg)
        ok = not gate_tripped(findings, fail_on)
        all_ok = all_ok and ok
        enabled = [r.id for r in RULES if cfg.settings_for(r.id).enabled]
        _why(args, f"lint {target}",
             f"format={fmt}, {len(analysis.lines)} lines, {len(analysis.headings)} headings, "
             f"{len(analysis.definitions)} defined terms",
             f"rules enabled: {', '.join(enabled)}",
             f"config: {', '.join(cfg.sources) or '(defaults only)'}",
             f"fail-on={fail_on} -> {'clean' if ok else 'gate tripped'}")
        reports.append(build_json(target, fmt, findings, fail_on, ok))
        sarif_items.append((target, findings))
        tables.append(render_table(target, fmt, findings))

    if getattr(args, "check", False):
        return EXIT_OK if all_ok else EXIT_FINDINGS
    if getattr(args, "sarif", False):
        _emit_json(build_sarif(sarif_items))
    elif getattr(args, "json", False):
        # One path -> a single report object (stable v1 schema); many -> an array of them.
        _emit_json(reports[0] if len(reports) == 1 else reports)
    else:
        _out(("\n\n").join(tables))
        if len(tables) > 1:
            errors = sum(r["summary"]["error"] for r in reports)
            warnings = sum(r["summary"]["warning"] for r in reports)
            _out(_dim(f"\n  total: {errors} error(s), {warnings} warning(s) across {len(reports)} file(s)"))
    return EXIT_OK if all_ok else EXIT_FINDINGS


def cmd_rules(args: argparse.Namespace) -> int:
    """Machine-readable catalog of every rule — the source of truth agents read
    instead of hardcoding rule names (parallels extract-cli's `fields`)."""
    if getattr(args, "json", False):
        payload = {
            "tool": CLI_NAME,
            "version": __version__,
            "rules": [{
                "id": r.id,
                "severity": r.severity,
                "default_enabled": r.default_enabled,
                "description": r.description,
            } for r in RULES],
        }
        _emit_json(payload)
        return EXIT_OK
    _out(_bold("contract-lint rules") + _dim("  (severity · default)"))
    for r in RULES:
        sev = _red(r.severity) if r.severity == SEVERITY_ERROR else _yellow(r.severity)
        state = _green("on") if r.default_enabled else _dim("off")
        _out(f"  {_cyan(r.id.ljust(18))} {sev.ljust(18)} {state.ljust(12)} {_dim(r.description)}")
    return EXIT_OK


def cmd_demo(args: argparse.Namespace) -> int:
    """Zero-config run on a bundled, deliberately-flawed contract (no network)."""
    fmt = "markdown"
    if not getattr(args, "json", False) and not getattr(args, "sarif", False):
        _eprint(_bold("contract-lint demo") + " — linting a deliberately-flawed sample contract")
        _eprint(_dim(
            "  No file, no network, no model. Every finding below is deterministic.\n"
            "  Point it at your own draft with:  contract-lint your-contract.md\n"))
    cfg = _default_config()
    for opt_in in ("undefined-term", "signature-block"):
        cfg.rules[opt_in].enabled = True  # showcase the opt-in rules too
    analysis = analyze(DEMO_CONTRACT, fmt)
    findings = lint(analysis, cfg)
    ok = not gate_tripped(findings, "error")
    if getattr(args, "sarif", False):
        _emit_json(build_sarif([("demo-contract.md", findings)]))
    elif getattr(args, "json", False):
        _emit_json(build_json("demo-contract.md", fmt, findings, "error", ok))
    else:
        _out(render_table("demo-contract.md", fmt, findings))
        _eprint("")
        _eprint(_dim("  Try:  contract-lint demo --json | jq '.summary'"))
    return EXIT_OK if ok else EXIT_FINDINGS


# ---------------------------------------------------------------------------
# Shell completion (`contract-lint completion bash|zsh`)
# ---------------------------------------------------------------------------

_SUBCOMMANDS = ("lint", "rules", "demo", "completion")
_GLOBAL_FLAGS = (
    "--json", "--sarif", "--check", "--fail-on", "--format", "--config",
    "--enable", "--disable", "--why", "-q", "--quiet", "--no-color",
    "--catalog", "-V", "--version", "-h", "--help",
)

_BASH_COMPLETION = r"""# contract-lint bash completion
#   eval "$(contract-lint completion bash)"
_contract_lint_completions() {
    local cur cmds flags
    cur="${COMP_WORDS[COMP_CWORD]}"
    cmds="lint rules demo completion"
    flags="--json --sarif --check --fail-on --format --config --enable --disable --why -q --quiet --no-color --catalog -V --version -h --help"
    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "${cmds}" -- "${cur}") $(compgen -f -- "${cur}") )
        return 0
    fi
    if [[ "${cur}" == -* ]]; then
        COMPREPLY=( $(compgen -W "${flags}" -- "${cur}") )
        return 0
    fi
    COMPREPLY=( $(compgen -f -- "${cur}") )
}
complete -F _contract_lint_completions contract-lint
"""

_ZSH_COMPLETION = r"""# contract-lint zsh completion
#   eval "$(contract-lint completion zsh)"
_contract_lint() {
    local -a cmds flags
    cmds=(
        'lint:Lint a contract for internal-consistency defects'
        'rules:List every rule (id, severity, description); --json for machines'
        'demo:Lint a bundled, deliberately-flawed contract'
        'completion:Emit a shell completion script (bash or zsh)'
    )
    flags=(
        '--json' '--sarif' '--check' '--fail-on' '--format' '--config'
        '--enable' '--disable' '--why' '-q' '--quiet' '--no-color' '--catalog'
        '-V' '--version' '-h' '--help'
    )
    if (( CURRENT == 2 )); then
        _describe 'command' cmds
        _files
        return
    fi
    _files
    compadd -- ${flags}
}
compdef _contract_lint contract-lint
"""


def cmd_completion(args: argparse.Namespace) -> int:
    shell = (args.shell or "").lower()
    if shell == "bash":
        sys.stdout.write(_BASH_COMPLETION)
        return EXIT_OK
    if shell == "zsh":
        sys.stdout.write(_ZSH_COMPLETION)
        return EXIT_OK
    raise UsageError(f"unsupported shell: {args.shell!r}. Supported: bash, zsh.")


def cmd_complete(words: Sequence[str]) -> int:
    """Hidden completion helper (`contract-lint __complete <words...>`). Never raises."""
    try:
        words = list(words)
        current = words[-1] if words else ""
        if len(words) <= 1:
            candidates: List[str] = list(_SUBCOMMANDS)
        elif current.startswith("-"):
            candidates = list(_GLOBAL_FLAGS)
        elif words[0] == "completion":
            candidates = ["bash", "zsh"]
        elif words[0] in ("lint", "rules", "demo") and "--fail-on" in words[-2:]:
            candidates = list(FAIL_ON_CHOICES)
        else:
            candidates = [r.id for r in RULES]
        for c in candidates:
            if c.startswith(current):
                print(c)
        return EXIT_OK
    except Exception:  # completion must never break a shell session
        return EXIT_OK


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _add_output_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="machine-readable JSON report on stdout (locked schema)")
    p.add_argument("--sarif", action="store_true", help="SARIF 2.1.0 report on stdout (for code-scanning / CI annotations)")
    p.add_argument("--why", action="store_true", help="structured rationale on stderr")
    p.add_argument("--no-color", action="store_true", help="disable ANSI color (also honors NO_COLOR/FORCE_COLOR)")
    p.add_argument("-q", "--quiet", "--silent", dest="quiet", action="store_true", help="suppress non-error output")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=CLI_NAME,
        description=(
            "Lint a contract for internal-consistency defects — leftover placeholders, "
            "broken cross-references, undefined/unused defined terms, numbering gaps, "
            "inconsistent parties, and impossible dates — with CI-gateable exit codes. "
            "Deterministic, stdlib-only. Also composes with the contract-ops suite."
        ),
    )
    parser.add_argument("-V", "--version", action="version", version=f"{CLI_NAME} {__version__}")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI color")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_lint = sub.add_parser("lint", help="lint one or more contracts for internal-consistency defects")
    p_lint.add_argument("path", nargs="+",
                        help="contract file(s) (.md/.txt/.html; .docx/.pdf via extras), or '-' for stdin")
    p_lint.add_argument("--format", choices=list(FORMAT_CHOICES), default="auto",
                        help="input format (default: auto-detect by extension; '-' defaults to text)")
    p_lint.add_argument("--fail-on", choices=list(FAIL_ON_CHOICES), default="error",
                        help="severity that trips exit 1 (default: error)")
    p_lint.add_argument("--check", action="store_true",
                        help="exit-code-only gate: print nothing, communicate via exit code")
    p_lint.add_argument("--enable", action="append", metavar="RULE",
                        help="enable a rule (repeatable; e.g. --enable undefined-term)")
    p_lint.add_argument("--disable", action="append", metavar="RULE",
                        help="disable a rule (repeatable)")
    p_lint.add_argument("--config", metavar="PATH", help="explicit config file (highest precedence)")
    _add_output_flags(p_lint)
    p_lint.set_defaults(func=cmd_lint)

    p_rules = sub.add_parser("rules", help="list every rule (id, severity, description); --json for machines")
    p_rules.add_argument("--json", action="store_true", help="machine-readable rule catalog on stdout")
    p_rules.add_argument("--no-color", action="store_true", help="disable ANSI color")
    p_rules.set_defaults(func=cmd_rules)

    p_demo = sub.add_parser("demo", help="lint a bundled, deliberately-flawed contract (zero-config, no network)")
    p_demo.add_argument("--json", action="store_true", help="machine-readable JSON report on stdout")
    p_demo.add_argument("--sarif", action="store_true", help="SARIF 2.1.0 report on stdout")
    p_demo.add_argument("--no-color", action="store_true", help="disable ANSI color")
    p_demo.set_defaults(func=cmd_demo)

    p_comp = sub.add_parser("completion", help="emit a shell completion script (bash or zsh)")
    p_comp.add_argument("shell", choices=["bash", "zsh"], help="target shell")
    p_comp.set_defaults(func=cmd_completion)

    return parser


# ---------------------------------------------------------------------------
# Machine-readable catalog (`contract-lint --catalog json`) — the suite discovery
# contract. Generated by walking the live parser so it can never drift from what the
# binary accepts (tests/test_catalog.py asserts this).
# ---------------------------------------------------------------------------


def _catalog_flags(p: argparse.ArgumentParser) -> List[JSONObj]:
    flags: List[JSONObj] = []
    for action in p._actions:
        if isinstance(action, argparse._SubParsersAction):
            continue
        if not action.option_strings:  # positional
            continue
        if action.help == argparse.SUPPRESS:
            continue
        default = None if action.default is argparse.SUPPRESS else action.default
        flags.append({
            "name": action.option_strings[-1],
            "aliases": list(action.option_strings[:-1]),
            "help": action.help or "",
            "required": bool(action.required),
            "default": default,
            "choices": list(action.choices) if action.choices else None,
        })
    return flags


def _subcommand_help(sub: "argparse._SubParsersAction[argparse.ArgumentParser]") -> Dict[str, str]:
    out: Dict[str, str] = {}
    getter = getattr(sub, "_get_subactions", None)
    if callable(getter):
        for pseudo in getter():
            out[str(getattr(pseudo, "dest", ""))] = str(getattr(pseudo, "help", "") or "")
    return out


def build_catalog() -> JSONObj:
    parser = build_parser()
    sub: Optional["argparse._SubParsersAction[argparse.ArgumentParser]"] = next(
        (a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)
    commands: List[JSONObj] = []
    if sub is not None:
        help_by_name = _subcommand_help(sub)
        for name, subparser in sub.choices.items():
            commands.append({
                "name": name,
                "summary": help_by_name.get(name, ""),
                "flags": _catalog_flags(subparser),
            })
    return {
        "name": CLI_NAME,
        "bin": CLI_NAME,
        "version": __version__,
        "description": (
            "Lint a contract for internal-consistency defects (leftover placeholders, "
            "broken cross-references, undefined/unused defined terms, numbering gaps, "
            "party-name and date inconsistencies) with CI-gateable exit codes. "
            "Deterministic, stdlib-only; also composes with the contract-ops suite."
        ),
        "commands": commands,
        "exitCodes": {
            "0": "clean — no findings at or above --fail-on",
            "1": "gate tripped — findings at or above --fail-on",
            "2": "bad usage / unreadable input",
        },
    }


def _set_output_flags(args: argparse.Namespace) -> None:
    global _NO_COLOR, _QUIET
    if getattr(args, "no_color", False):
        _NO_COLOR = True
    if getattr(args, "quiet", False):
        _QUIET = True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _route_argv(argv: List[str]) -> List[str]:
    """Insert the implicit `lint` command when the user passed a file (or a lint flag)
    instead of an explicit subcommand."""
    if not argv:
        return argv
    first = argv[0]
    if first in _SUBCOMMANDS or first in ("-h", "--help", "-V", "--version"):
        return argv
    # A top-level-only flag in front of a real subcommand: leave routing to the top parser.
    if first == "--no-color" and len(argv) > 1 and argv[1] in _SUBCOMMANDS:
        return argv
    return ["lint", *argv]


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _configure_streams()

    if argv and argv[0] == "__complete":
        return cmd_complete(argv[1:])

    if "--catalog" in argv:
        idx = argv.index("--catalog")
        fmt = argv[idx + 1] if idx + 1 < len(argv) else "json"
        if fmt != "json":
            _eprint(_red(f"error: unknown --catalog format {fmt!r}; supported: json"))
            return EXIT_USAGE
        print(json.dumps(build_catalog(), indent=2, ensure_ascii=True))
        return EXIT_OK

    # `lint` is the default command: `contract-lint file.md` == `contract-lint lint file.md`,
    # and a leading lint flag routes there too (`contract-lint --json file.md`). A top-level
    # flag in front of a real subcommand (`contract-lint --no-color demo`) is left alone.
    argv = _route_argv(argv)

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else (EXIT_OK if code is None else EXIT_USAGE)

    _set_output_flags(args)

    if not getattr(args, "command", None) or not hasattr(args, "func"):
        parser.print_help()
        return EXIT_USAGE

    try:
        return int(args.func(args))
    except UsageError as exc:
        _eprint(_red(f"error: {exc}"))
        return EXIT_USAGE
    except LintError as exc:
        _eprint(_red(f"error: {exc}"))
        return EXIT_USAGE
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass
        return EXIT_OK
    except KeyboardInterrupt:
        _eprint("interrupted")
        return 130


# ---------------------------------------------------------------------------
# Bundled demo contract — deliberately flawed, triggers several rules offline.
# ---------------------------------------------------------------------------

DEMO_CONTRACT = """# Master Services Agreement

This Master Services Agreement (the "Agreement") is entered into as of
March 15, 2026 (the "Effective Date") by and between Acme Corporation, Inc.
("Acme") and Initech LLC ("Initech").

## 1. Definitions

"Confidential Information" means any non-public information disclosed by a party.
"Services" means the services described in Exhibit A.
"Deliverables" means the work product described in [Schedule of Work].

## 2. Services

Acme Corp. shall provide the Services in accordance with Section 4.3 and the
timeline in Exhibit B. ACME Corporation may subcontract subject to Article IV.

## 4. Payment

Fees are due within {{payment_terms}} days at ten (15) percent interest. Late
amounts accrue per clause 9.3. See Schedule 2.1 for the fee schedule.

## 6. Term

This Agreement is effective as of March 15, 2026 and expires on January 1, 2026,
unless terminated earlier under Section 7.

## 7. Services

Either party may terminate for material breach. Notices go to the address in
__________ .

## Exhibit A

The Services consist of cloud migration and ongoing support. Dated 2026-02-30.
"""


if __name__ == "__main__":
    sys.exit(main())
