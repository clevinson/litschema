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
import sys
from pathlib import Path

from ..articles import iter_extraction_paths
from ..config import LitSchemaConfig
from ..config import load_config as _load_config
from ..schema_resolution import resolve_extraction_schema
from ..schema_validation import LinkMLDataValidator, create_linkml_validator, generate_json_schema


def generate_extraction_schema(cfg: LitSchemaConfig) -> dict:
    """Generate JSON Schema from the configured LinkML extraction schema."""
    schema_path, root_class = resolve_extraction_schema(cfg)
    return generate_json_schema(schema_path, root_class)


def validate_extraction(data: dict, validator: LinkMLDataValidator) -> list[str]:
    """Validate extraction data against schema. Returns list of error messages."""
    return validator.validate(data)


def validate_file(
    filepath: Path,
    schema_path: Path,
    root_class: str,
    validator: LinkMLDataValidator | None = None,
) -> tuple[bool, list[str]]:
    """Validate a single extraction JSON file. Returns (valid, errors)."""
    data = json.loads(filepath.read_text())

    # Skip error markers
    if data.get("error"):
        return True, []

    validator = validator or create_linkml_validator(schema_path, root_class)
    errors = validate_extraction(data, validator)
    return len(errors) == 0, errors


def _files_for_args(args: list[str], cfg: LitSchemaConfig) -> list[Path]:
    if not args:
        return list(iter_extraction_paths(cfg))

    target = Path(args[0])
    if not target.exists():
        raise FileNotFoundError(f"Missing extraction target: {target}")
    if target.is_dir():
        files = sorted(target.glob("*.json"))
        if not files:
            files = list(iter_extraction_paths(cfg))
        return files
    return [target]


def run(args: list[str] | None, cfg: LitSchemaConfig) -> int:
    args = list(args or [])

    if "--dump-schema" in args:
        schema = generate_extraction_schema(cfg)
        print(json.dumps(schema, indent=2))
        return 0

    try:
        files = _files_for_args(args, cfg)
    except FileNotFoundError as exc:
        print(exc)
        return 1

    schema_path, root_class = resolve_extraction_schema(cfg)
    validator = create_linkml_validator(schema_path, root_class)

    total = 0
    valid_count = 0
    error_files = []

    for filepath in files:
        total += 1
        is_valid, errors = validate_file(filepath, schema_path, root_class, validator=validator)
        if is_valid:
            valid_count += 1
        else:
            error_files.append((filepath.name, errors))
            print(f"INVALID: {filepath.name}")
            for err in errors:
                print(f"  {err}")

    print(f"\n{valid_count}/{total} valid")
    if error_files:
        return 1
    return 0


def main():
    sys.exit(run(sys.argv[1:], _load_config()))


if __name__ == "__main__":
    main()
