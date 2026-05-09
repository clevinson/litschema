"""Generate runtime JSON Schema context files for bundled agent skills."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import LitSchemaConfig, load_config
from ..schema_resolution import resolve_extraction_schema
from ..schema_validation import write_json_schema
from .reasoning_schema import reasoning_schema_source_path


@dataclass(frozen=True)
class SchemaContext:
    runtime_dir: Path
    extraction_schema_path: Path
    reasoning_schema_path: Path


def prepare_schema_context(cfg: LitSchemaConfig) -> SchemaContext:
    """Write runtime JSON Schemas derived from the configured LinkML schemas."""
    runtime_dir = cfg.project_root / ".litschema" / "runtime"

    extraction_schema, root_class = resolve_extraction_schema(cfg)
    extraction_output = runtime_dir / "extraction_schema.json"
    write_json_schema(extraction_schema, root_class, extraction_output)

    reasoning_schema = reasoning_schema_source_path()
    reasoning_output = runtime_dir / "reasoning_schema.json"
    write_json_schema(reasoning_schema, "ExtractionReasoning", reasoning_output)

    return SchemaContext(
        runtime_dir=runtime_dir,
        extraction_schema_path=extraction_output,
        reasoning_schema_path=reasoning_output,
    )


def main() -> None:
    context = prepare_schema_context(load_config())
    print(f"extraction_schema={context.extraction_schema_path}")
    print(f"reasoning_schema={context.reasoning_schema_path}")


if __name__ == "__main__":
    main()
