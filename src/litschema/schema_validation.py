"""LinkML-backed schema generation and validation helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from linkml.generators.jsonschemagen import JsonSchemaGenerator
from linkml.validator import Validator
from linkml.validator.plugins import JsonschemaValidationPlugin


def generate_json_schema(schema_path: Path, top_class: str) -> dict:
    """Generate JSON Schema from LinkML using the Python API."""
    serialized = JsonSchemaGenerator(str(schema_path), top_class=top_class).serialize()
    return json.loads(serialized)


def _write_text_atomic(output_path: Path, text: str) -> None:
    """Replace a text file atomically so concurrent readers never see partial JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
    try:
        temp_path.write_text(text)
        temp_path.replace(output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def write_json_file(output_path: Path, data: Any) -> None:
    """Write a JSON file atomically."""
    _write_text_atomic(output_path, json.dumps(data, indent=2) + "\n")


def write_json_schema(schema_path: Path, top_class: str, output_path: Path) -> None:
    """Write a runtime JSON Schema artifact for agents or external consumers."""
    write_json_file(output_path, generate_json_schema(schema_path, top_class))


class LinkMLDataValidator:
    """Reusable LinkML validator for one schema/class pair."""

    def __init__(self, schema_path: Path, target_class: str) -> None:
        self.target_class = target_class
        self._validator = Validator(
            schema=str(schema_path),
            validation_plugins=[JsonschemaValidationPlugin(closed=True)],
        )

    def validate(self, data: dict[str, Any]) -> list[str]:
        report = self._validator.validate(data, target_class=self.target_class)
        return [result.message for result in report.results]


def create_linkml_validator(schema_path: Path, target_class: str) -> LinkMLDataValidator:
    """Create a reusable validator for repeated records from the same schema."""
    return LinkMLDataValidator(schema_path, target_class)


def validate_linkml_data(data: dict[str, Any], schema_path: Path, target_class: str) -> list[str]:
    """Validate one JSON-compatible object against a LinkML class."""
    return create_linkml_validator(schema_path, target_class).validate(data)
