"""Validate LLM extraction output against the configured extraction schema.

Usage:
    # Validate a single extraction
    uv run python -m litschema.ingest.validate_extraction data/llm_extractions/beerling-2024.json

    # Validate all extractions
    uv run python -m litschema.ingest.validate_extraction data/llm_extractions/
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..articles import iter_extraction_paths
from ..config import LitSchemaConfig, require_config_or_exit
from ..schema_resolution import resolve_extraction_schema
from ..schema_validation import LinkMLDataValidator, create_linkml_validator


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
    errors = validator.validate(data)
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

    try:
        files = _files_for_args(args, cfg)
    except FileNotFoundError as exc:
        print(exc)
        return 1

    extraction_schema = resolve_extraction_schema(cfg)
    validator = create_linkml_validator(extraction_schema.path, extraction_schema.root_class)

    total = 0
    valid_count = 0
    error_files = []

    for filepath in files:
        total += 1
        is_valid, errors = validate_file(
            filepath,
            extraction_schema.path,
            extraction_schema.root_class,
            validator=validator,
        )
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
    sys.exit(run(sys.argv[1:], require_config_or_exit()))


if __name__ == "__main__":
    main()
