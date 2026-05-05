"""Validate LLM extraction output against the ExtractionArtifact JSON Schema.

Uses gen-json-schema with --top-class ExtractionArtifact to generate the
validation schema directly from extraction.yaml.

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

from ..config import load_config as _load_config

EXTRACTION_SCHEMA_PATH = _load_config().schema_dir / "extraction.yaml"


def generate_extraction_schema(schema_path: Path = EXTRACTION_SCHEMA_PATH) -> dict:
    """Generate JSON Schema from extraction.yaml with ExtractionArtifact as root."""
    result = subprocess.run(
        ["uv", "run", "gen-json-schema", "--top-class", "ExtractionArtifact", str(schema_path)],
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

    if "--dump-schema" in args:
        schema = generate_extraction_schema()
        print(json.dumps(schema, indent=2))
        return

    if not args:
        print("Usage: validate_extraction.py [--dump-schema] <file_or_dir>")
        sys.exit(1)

    target = Path(args[0])
    schema = generate_extraction_schema()

    files = sorted(target.glob("*.json")) if target.is_dir() else [target]

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
