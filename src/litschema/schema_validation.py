"""LinkML-backed schema generation and validation helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from linkml.generators.jsonschemagen import JsonSchemaGenerator
from linkml.validator import Validator
from linkml.validator.plugins import JsonschemaValidationPlugin


def generate_json_schema(schema_path: Path, top_class: str) -> dict:
    """Generate JSON Schema from LinkML using the Python API."""
    serialized = JsonSchemaGenerator(str(schema_path), top_class=top_class).serialize()
    return json.loads(serialized)


def write_json_schema(schema_path: Path, top_class: str, output_path: Path) -> None:
    """Write a runtime JSON Schema artifact for agents or external consumers."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(generate_json_schema(schema_path, top_class), indent=2) + "\n")


def validate_linkml_data(data: dict[str, Any], schema_path: Path, target_class: str) -> list[str]:
    """Validate one JSON-compatible object against a LinkML class."""
    validator = Validator(
        schema=str(schema_path),
        validation_plugins=[JsonschemaValidationPlugin(closed=True)],
    )
    report = validator.validate(data, target_class=target_class)
    return [result.message for result in report.results]
