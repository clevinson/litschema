"""Validate agent reasoning files against the configured LinkML reasoning schema."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..articles import iter_reasoning_paths
from ..config import LitSchemaConfig, load_config
from ..schema_validation import LinkMLDataValidator, create_linkml_validator
from .reasoning_schema import reasoning_schema_source_path


def validate_file(
    filepath: Path,
    schema_path: Path,
    root_class: str = "ExtractionReasoning",
    validator: LinkMLDataValidator | None = None,
) -> tuple[bool, list[str]]:
    data = json.loads(filepath.read_text())
    validator = validator or create_linkml_validator(schema_path, root_class)
    errors = validator.validate(data)
    return len(errors) == 0, errors


def _reasoning_files_for_target(cfg: LitSchemaConfig, target: Path | None) -> list[Path]:
    if target is None:
        return list(iter_reasoning_paths(cfg))
    if not target.exists():
        raise FileNotFoundError(f"Missing reasoning target: {target}")
    if target.is_dir():
        files = sorted(target.glob("*/agent-reasoning.json"))
        if not files:
            files = sorted(target.glob("*.json"))
        if not files:
            files = list(iter_reasoning_paths(cfg))
        return files
    return [target]


def run(args: list[str] | None, cfg: LitSchemaConfig) -> int:
    args = list(args or [])
    target = Path(args[0]) if args else None

    try:
        files = _reasoning_files_for_target(cfg, target)
    except FileNotFoundError as exc:
        print(exc)
        return 1

    schema_path = reasoning_schema_source_path()
    validator = create_linkml_validator(schema_path, "ExtractionReasoning")

    if not files:
        print("No reasoning files found")
        return 1

    valid_count = 0
    invalid_count = 0
    for filepath in files:
        ok, errors = validate_file(filepath, schema_path, validator=validator)
        if ok:
            valid_count += 1
            continue
        invalid_count += 1
        print(f"INVALID: {filepath}")
        for error in errors[:10]:
            print(f"  {error}")

    print(f"\nReasoning: {valid_count}/{valid_count + invalid_count} valid")
    if invalid_count:
        return 1
    return 0


def main() -> None:
    code = run(sys.argv[1:], load_config())
    if code:
        sys.exit(code)


if __name__ == "__main__":
    main()
