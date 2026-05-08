"""Validate agent reasoning files against the runtime reasoning JSON Schema."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from ..articles import iter_reasoning_paths
from ..config import LitSchemaConfig, load_config
from .prepare_schema_context import prepare_schema_context


def validate_file(filepath: Path, schema: dict) -> tuple[bool, list[str]]:
    data = json.loads(filepath.read_text())
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.absolute_path))
    messages = []
    for error in errors:
        path = ".".join(str(part) for part in error.absolute_path) or "<root>"
        messages.append(f"{path}: {error.message}")
    return len(messages) == 0, messages


def _reasoning_files_for_target(cfg: LitSchemaConfig, target: Path) -> list[Path]:
    if not target.exists():
        return list(iter_reasoning_paths(cfg))
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
    target = Path(args[0]) if args else cfg.article_store_dir

    context = prepare_schema_context(cfg)
    if context.reasoning_schema_path is None:
        print(f"No reasoning schema found at {cfg.schema_dir / 'reasoning.yaml'}; skipping")
        return

    schema = json.loads(context.reasoning_schema_path.read_text())
    files = _reasoning_files_for_target(cfg, target)
    if not files:
        print("No reasoning files found")
        sys.exit(1)

    valid_count = 0
    invalid_count = 0
    for filepath in files:
        ok, errors = validate_file(filepath, schema)
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
