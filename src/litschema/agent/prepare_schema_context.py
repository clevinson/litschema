"""Generate runtime JSON Schema context files for bundled agent skills."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..config import LitSchemaConfig, load_config
from ..schema_resolution import resolve_extraction_schema


@dataclass(frozen=True)
class SchemaContext:
    runtime_dir: Path
    extraction_schema_path: Path
    reasoning_schema_path: Path | None


def _generate_json_schema(schema_path: Path, top_class: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as fh:
        subprocess.run(
            ["uv", "run", "gen-json-schema", "--top-class", top_class, str(schema_path)],
            stdout=fh,
            check=True,
            cwd=schema_path.parent,
        )


def prepare_schema_context(cfg: LitSchemaConfig | None = None) -> SchemaContext:
    """Write runtime JSON Schemas derived from the configured LinkML schemas."""
    cfg = cfg or load_config()
    runtime_dir = cfg.project_root / ".litschema" / "runtime"

    extraction_schema, extraction_class = resolve_extraction_schema(cfg)
    extraction_output = runtime_dir / "extraction_schema.json"
    _generate_json_schema(extraction_schema, extraction_class, extraction_output)

    reasoning_schema = cfg.schema_dir / "reasoning.yaml"
    reasoning_output: Path | None = None
    if reasoning_schema.exists():
        reasoning_output = runtime_dir / "reasoning_schema.json"
        _generate_json_schema(reasoning_schema, "ExtractionReasoning", reasoning_output)

    return SchemaContext(
        runtime_dir=runtime_dir,
        extraction_schema_path=extraction_output,
        reasoning_schema_path=reasoning_output,
    )


def main() -> None:
    context = prepare_schema_context()
    print(f"extraction_schema={context.extraction_schema_path}")
    if context.reasoning_schema_path:
        print(f"reasoning_schema={context.reasoning_schema_path}")


if __name__ == "__main__":
    main()
