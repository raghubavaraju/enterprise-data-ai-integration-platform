#!/usr/bin/env python3
"""Validate the API specifications and enforce the governance rules.

Two jobs:

  1. structural validity - the OAS documents parse and satisfy the 3.0 schema,
     and every internal ``$ref`` resolves;
  2. governance - the rules in ``docs/api-governance.md`` are checked
     mechanically and not in review, because a naming convention nobody
     enforces is a naming convention nobody follows.

Run: ``python scripts/validate_api_specs.py``   (or ``make lint-spec``)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
OAS_DIR = REPO / "api-specs" / "oas"
RAML_DIR = REPO / "api-specs" / "raml"

VERB_IN_PATH = re.compile(r"/(get|post|put|delete|create|update|fetch|retrieve|list|do)[A-Z/]")
# Lower-case, hyphenated, or a numeric resource name such as "360". A numeric
# segment is legitimate ("/customers/{id}/360" is the customer's 360 view);
# what the rule forbids is camelCase and underscores.
CAMEL_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ERRORS: list[str] = []
WARNINGS: list[str] = []


def error(spec: str, message: str) -> None:
    ERRORS.append(f"{spec}: {message}")


def warn(spec: str, message: str) -> None:
    WARNINGS.append(f"{spec}: {message}")


def load(path: Path) -> dict:
    with path.open() as fh:
        return yaml.safe_load(fh)


def check_structure(name: str, doc: dict, path: Path) -> None:
    try:
        from openapi_spec_validator import validate
    except ImportError:                                        # pragma: no cover
        warn(name, "openapi-spec-validator is not installed; structural check skipped")
        return
    try:
        # base_uri lets the validator follow the cross-file $refs into
        # api-specs/fragments/, which is where the shared error and pagination
        # models live. Without it every reused fragment looks like a broken ref.
        validate(doc, base_uri=path.as_uri())
    except Exception as exc:                                   # noqa: BLE001
        error(name, f"OpenAPI structural validation failed: {str(exc).splitlines()[0][:200]}")


def check_refs(name: str, doc: dict, path: Path) -> None:
    """Every $ref must point at something that exists."""
    def walk(node, trail="$"):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref" and isinstance(value, str):
                    resolve(value, trail)
                else:
                    walk(value, f"{trail}.{key}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{trail}[{i}]")

    def resolve(ref: str, trail: str) -> None:
        file_part, _, pointer = ref.partition("#")
        target_doc = doc
        if file_part:
            target = (path.parent / file_part).resolve()
            if not target.exists():
                error(name, f"{trail}: $ref target file does not exist: {file_part}")
                return
            target_doc = load(target)
        node = target_doc
        for token in [t for t in pointer.split("/") if t]:
            token = token.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, dict) or token not in node:
                error(name, f"{trail}: $ref cannot be resolved: {ref}")
                return
            node = node[token]

    walk(doc)


def check_governance(name: str, doc: dict) -> None:
    info = doc.get("info", {})
    if not info.get("description"):
        error(name, "info.description is required - a contract without a rationale is a guess")
    if not re.match(r"^\d+\.\d+\.\d+$", str(info.get("version", ""))):
        error(name, f"info.version must be semantic, got {info.get('version')!r}")

    servers = doc.get("servers", [])
    if not servers:
        error(name, "at least one server must be declared")
    for server in servers:
        url = server.get("url", "")
        if not re.search(r"/v\d+", url):
            error(name, f"server URL must carry a major version: {url}")
        if url.startswith("http://") and "localhost" not in url and "127.0.0.1" not in url:
            error(name, f"non-local server must be HTTPS: {url}")

    for path, item in (doc.get("paths") or {}).items():
        if VERB_IN_PATH.search(path):
            error(name, f"path contains a verb (use HTTP methods instead): {path}")
        for segment in [s for s in path.split("/") if s and not s.startswith("{")]:
            if not CAMEL_SEGMENT.match(segment):
                error(name, f"path segment must be lower-case and hyphenated: {segment}")

        for method, operation in item.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            label = f"{method.upper()} {path}"
            if not operation.get("operationId"):
                error(name, f"{label}: operationId is required")
            if not operation.get("summary"):
                error(name, f"{label}: summary is required")
            if not operation.get("tags"):
                warn(name, f"{label}: no tags - the rendered documentation will be flat")

            responses = operation.get("responses", {})
            if not any(str(code).startswith("2") for code in responses):
                error(name, f"{label}: no success response declared")
            if path != "/health":
                missing = [c for c in ("401",) if c not in responses]
                if missing and operation.get("security") != []:
                    error(name, f"{label}: missing error response(s) {missing}")

            # Collection endpoints must be bounded.
            returns_collection = any(
                p.get("name") == "limit" or p.get("$ref", "").endswith("/Limit")
                for p in operation.get("parameters", []))
            if path.endswith(("/orders", "/cases", "/high-risk")) and not returns_collection:
                error(name, f"{label}: collection endpoint has no limit parameter")


def check_error_model_is_shared(name: str, doc: dict, path: Path) -> None:
    """Every non-2xx must use the canonical error object."""
    for p, item in (doc.get("paths") or {}).items():
        for method, operation in item.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            for code, response in (operation.get("responses") or {}).items():
                if str(code).startswith(("2", "3")):
                    continue
                blob = yaml.safe_dump(response)
                if "error.oas.yaml" not in blob and "Error" not in blob:
                    error(name, f"{method.upper()} {p} -> {code}: does not use the "
                                f"canonical error model")


def check_raml() -> None:
    """RAML is checked for structure and for the fragments being reused."""
    root = RAML_DIR / "customer-experience-api" / "customer-experience-api.raml"
    if not root.exists():
        error("raml", "the RAML root file is missing")
        return
    text = root.read_text()
    if not text.startswith("#%RAML 1.0"):
        error(root.name, "missing the RAML 1.0 header comment")
    for required in ["securitySchemes/oauth2.raml", "traits/correlated.raml",
                     "traits/standard-errors.raml", "dataTypes/error.raml"]:
        if required not in text:
            error(root.name, f"expected fragment is not referenced: {required}")
    # Every referenced include must exist.
    for include in re.findall(r"!include\s+(\S+)", text):
        if not (root.parent / include).exists():
            error(root.name, f"!include target does not exist: {include}")
    for fragment in RAML_DIR.rglob("*.raml"):
        if fragment == root:
            continue
        head = fragment.read_text().splitlines()[0]
        if not head.startswith("#%RAML 1.0"):
            error(str(fragment.relative_to(REPO)), f"missing RAML fragment header: {head!r}")


def main() -> int:
    specs = sorted(OAS_DIR.glob("*.yaml"))
    if not specs:
        print("no OpenAPI specifications found")
        return 1

    for path in specs:
        name = path.name
        try:
            doc = load(path)
        except yaml.YAMLError as exc:
            error(name, f"YAML is not parseable: {exc}")
            continue
        check_structure(name, doc, path)
        check_refs(name, doc, path)
        check_governance(name, doc)
        check_error_model_is_shared(name, doc, path)

    for path in sorted((REPO / "api-specs" / "fragments").glob("*.yaml")):
        try:
            load(path)
        except yaml.YAMLError as exc:
            error(path.name, f"YAML is not parseable: {exc}")

    check_raml()

    print(f"Validated {len(specs)} OpenAPI specifications and the RAML tree.")
    for w in WARNINGS:
        print(f"  WARN  {w}")
    for e in ERRORS:
        print(f"  ERROR {e}")
    if ERRORS:
        print(f"\n{len(ERRORS)} governance or structural error(s).")
        return 1
    print("All specifications conform to docs/api-governance.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
