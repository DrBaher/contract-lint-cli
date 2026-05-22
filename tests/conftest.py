"""Shared test fixtures + a tiny stdlib JSON-Schema (2020-12 subset) validator.

The validator deliberately depends on nothing beyond the standard library, so the whole
suite (including schema-conformance / spec-check) runs offline with no third-party package
installed. It supports exactly the keywords used by the schemas in docs/spec/: type, enum,
const, required, properties, additionalProperties (bool|schema), items, $ref (#/$defs/...),
minimum, maximum, minItems, minLength, pattern, allOf/anyOf/oneOf.
"""
from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, List, Optional

import pytest

# Make the single-module CLI importable without an install.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import contract_lint_cli as cl  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CORPUS = FIXTURES / "corpus"
GOLDEN = FIXTURES / "golden"
SPEC_DIR = REPO_ROOT / "docs" / "spec"


# --------------------------------------------------------------------------- #
# Minimal JSON Schema validator
# --------------------------------------------------------------------------- #


def _is_type(value: Any, t: str) -> bool:
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "null":
        return value is None
    raise AssertionError(f"unsupported type keyword: {t}")


def _resolve(ref: str, root: dict) -> dict:
    assert ref.startswith("#"), f"only local refs supported: {ref}"
    if ref == "#":
        return root
    node: Any = root
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node


def schema_errors(instance: Any, schema: dict, root: Optional[dict] = None, path: str = "$") -> List[str]:
    root = root if root is not None else schema
    errors: List[str] = []

    if "$ref" in schema:
        return schema_errors(instance, _resolve(schema["$ref"], root), root, path)

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']}")
    if "type" in schema:
        types = schema["type"]
        types = [types] if isinstance(types, str) else types
        if not any(_is_type(instance, t) for t in types):
            errors.append(f"{path}: expected type {types}, got {type(instance).__name__} ({instance!r})")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} > maximum {schema['maximum']}")
    if isinstance(instance, str):
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append(f"{path}: {instance!r} does not match {schema['pattern']!r}")
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")

    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in instance:
                errors.append(f"{path}: missing required property {req!r}")
        ap = schema.get("additionalProperties", True)
        for key, val in instance.items():
            if key in props:
                errors += schema_errors(val, props[key], root, f"{path}.{key}")
            elif ap is False:
                errors.append(f"{path}: additional property {key!r} not allowed")
            elif isinstance(ap, dict):
                errors += schema_errors(val, ap, root, f"{path}.{key}")

    if isinstance(instance, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for i, el in enumerate(instance):
                errors += schema_errors(el, items, root, f"{path}[{i}]")
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: fewer than minItems {schema['minItems']}")

    for sub in schema.get("allOf", []):
        errors += schema_errors(instance, sub, root, path)
    if "anyOf" in schema and not any(not schema_errors(instance, s, root, path) for s in schema["anyOf"]):
        errors.append(f"{path}: matches none of anyOf")
    if "oneOf" in schema:
        matched = sum(1 for s in schema["oneOf"] if not schema_errors(instance, s, root, path))
        if matched != 1:
            errors.append(f"{path}: matched {matched} of oneOf (need exactly 1)")

    return errors


def assert_valid(instance: Any, schema: dict) -> None:
    errs = schema_errors(instance, schema)
    assert not errs, "schema validation failed:\n  " + "\n  ".join(errs)


# --------------------------------------------------------------------------- #
# Loaders / helpers
# --------------------------------------------------------------------------- #


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def all_corpus_files() -> List[Path]:
    return sorted(CORPUS.glob("*.md"))


def normalize_report(report: dict) -> dict:
    """Pin the volatile `version` field so goldens stay stable across version bumps."""
    out = json.loads(json.dumps(report))
    out["version"] = "X.Y.Z"
    return out


def lint_report(path: Path, argv_extra: Optional[List[str]] = None) -> dict:
    """Run the CLI on a path with --json and return the parsed report (raises on non-0/1)."""
    import subprocess
    cmd = [sys.executable, str(REPO_ROOT / "contract_lint_cli.py"), str(path), "--json", "--no-color"]
    cmd += argv_extra or []
    proc = subprocess.run(cmd, capture_output=True, text=True, env=_ascii_env())
    assert proc.returncode in (0, 1), f"unexpected exit {proc.returncode}: {proc.stderr}"
    return json.loads(proc.stdout)


def _ascii_env() -> dict:
    import os
    env = dict(os.environ)
    env["NO_COLOR"] = "1"
    env.pop("FORCE_COLOR", None)
    return env


def make_docx(path: Path, paragraphs: List[str]) -> Path:
    """Write a minimal real .docx (zip + word/document.xml) using only stdlib."""
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(
        f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs
    )
    doc = f'<?xml version="1.0"?><w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>'
    ct = ('<?xml version="1.0"?><Types '
          'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="xml" ContentType="application/xml"/></Types>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("word/document.xml", doc)
    return path


# --------------------------------------------------------------------------- #
# Schema fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def output_schema() -> dict:
    return load_json(SPEC_DIR / "lint-output.schema.json")


@pytest.fixture()
def rules_schema() -> dict:
    return load_json(SPEC_DIR / "rules.schema.json")


@pytest.fixture()
def sarif_schema() -> dict:
    return load_json(SPEC_DIR / "lint-sarif.schema.json")


# --------------------------------------------------------------------------- #
# Environment / state hygiene
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Deterministic, color-free environment; isolate config discovery from the host."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    # Point XDG at an empty temp dir so a real ~/.config/contract-ops/ never leaks in.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    cl._NO_COLOR = False
    cl._QUIET = False
