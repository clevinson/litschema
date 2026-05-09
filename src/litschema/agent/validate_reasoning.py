"""Validate an agent reasoning file against the bundled LinkML reasoning schema."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..schema_validation import validate_linkml_data
from .reasoning_schema import reasoning_schema_source_path


def validate_file(
    filepath: Path,
    schema_path: Path,
    root_class: str = "ExtractionReasoning",
) -> tuple[bool, list[str]]:
    data = json.loads(filepath.read_text())
    errors = validate_linkml_data(data, schema_path, root_class)
    return len(errors) == 0, errors


def _reasoning_file_for_target(target: Path) -> Path:
    if not target.exists():
        raise FileNotFoundError(f"Missing reasoning target: {target}")
    if target.is_dir():
        raise IsADirectoryError(f"Reasoning target must be a file: {target}")
    return target


def run(args: list[str] | None) -> int:
    args = list(args or [])
    if not args:
        print("Usage: litschema agent validate-reasoning <agent-reasoning.json>")
        return 1

    try:
        filepath = _reasoning_file_for_target(Path(args[0]))
    except (FileNotFoundError, IsADirectoryError) as exc:
        print(exc)
        return 1

    schema_path = reasoning_schema_source_path()

    ok, errors = validate_file(filepath, schema_path)
    if not ok:
        print(f"INVALID: {filepath}")
        for error in errors[:10]:
            print(f"  {error}")
        return 1

    print(f"Reasoning valid: {filepath}")
    return 0


def main() -> None:
    code = run(sys.argv[1:])
    if code:
        sys.exit(code)


if __name__ == "__main__":
    main()
