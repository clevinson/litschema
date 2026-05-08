"""Validate LLM extraction output against the configured extraction schema.

Usage:
    # Validate a single extraction
    uv run python -m litschema.ingest.validate_extraction data/llm_extractions/beerling-2024.json

    # Validate all extractions
    uv run python -m litschema.ingest.validate_extraction data/llm_extractions/

    # Generate the extraction schema (for inspection)
    uv run python -m litschema.ingest.validate_extraction --dump-schema
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from ..articles import iter_extraction_paths
from ..config import LitSchemaConfig
from ..config import load_config as _load_config
from ..schema_resolution import resolve_extraction_schema


def generate_extraction_schema(cfg: LitSchemaConfig | None = None) -> dict:
    """Generate JSON Schema from the configured LinkML extraction schema."""
    cfg = cfg or _load_config()
    schema_path, root_class = resolve_extraction_schema(cfg)
    result = subprocess.run(
        ["uv", "run", "gen-json-schema", "--top-class", root_class, str(schema_path)],
        capture_output=True,
        text=True,
        cwd=schema_path.parent,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gen-json-schema failed: {result.stderr}")
    return json.loads(result.stdout)


def validate_extraction(data: dict, schema: dict) -> list[str]:
    """Validate extraction data against schema. Returns list of error messages."""
    validator = Draft202012Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append(f"{path}: {error.message}")
    return errors


def validate_file(filepath: Path, schema: dict) -> tuple[bool, list[str]]:
    """Validate a single extraction JSON file. Returns (valid, errors)."""
    data = json.loads(filepath.read_text())

    # Skip error markers
    if data.get("error"):
        return True, []

    errors = validate_extraction(data, schema)
    return len(errors) == 0, errors


def main():
    args = sys.argv[1:]
    cfg = _load_config()

    if "--dump-schema" in args:
        schema = generate_extraction_schema(cfg)
        print(json.dumps(schema, indent=2))
        return

    if not args:
        files = list(iter_extraction_paths(cfg))
    else:
        target = Path(args[0])
        if not target.exists():
            print(f"Missing extraction target: {target}")
            sys.exit(1)
        if target.is_dir():
            files = sorted(target.glob("*.json"))
            if not files:
                files = list(iter_extraction_paths(cfg))
        else:
            files = [target]

    schema = generate_extraction_schema(cfg)

    total = 0
    valid_count = 0
    error_files = []

    for filepath in files:
        total += 1
        is_valid, errors = validate_file(filepath, schema)
        if is_valid:
            valid_count += 1
        else:
            error_files.append((filepath.name, errors))
            print(f"INVALID: {filepath.name}")
            for err in errors:
                print(f"  {err}")

    print(f"\n{valid_count}/{total} valid")
    if error_files:
        sys.exit(1)


if __name__ == "__main__":
    main()
