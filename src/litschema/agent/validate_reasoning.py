"""Validate agent reasoning files against the configured LinkML reasoning schema."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..articles import iter_reasoning_paths
from ..config import LitSchemaConfig, load_config
from ..schema_validation import validate_linkml_data


def validate_file(
    filepath: Path,
    schema_path: Path,
    root_class: str = "ExtractionReasoning",
) -> tuple[bool, list[str]]:
    data = json.loads(filepath.read_text())
    errors = validate_linkml_data(data, schema_path, root_class)
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


def main() -> None:
    cfg = load_config()
    args = sys.argv[1:]
    target = Path(args[0]) if args else None

    try:
        files = _reasoning_files_for_target(cfg, target)
    except FileNotFoundError as exc:
        print(exc)
        sys.exit(1)

    schema_path = cfg.schema_dir / "reasoning.yaml"
    if not schema_path.exists():
        print(f"No reasoning schema found at {schema_path}; skipping")
        return

    if not files:
        print("No reasoning files found")
        sys.exit(1)

    valid_count = 0
    invalid_count = 0
    for filepath in files:
        ok, errors = validate_file(filepath, schema_path)
        if ok:
            valid_count += 1
            continue
        invalid_count += 1
        print(f"INVALID: {filepath}")
        for error in errors[:10]:
            print(f"  {error}")

    print(f"\nReasoning: {valid_count}/{valid_count + invalid_count} valid")
    if invalid_count:
        sys.exit(1)


if __name__ == "__main__":
    main()
