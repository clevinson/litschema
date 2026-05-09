"""Generate runtime JSON Schema context files for bundled agent skills."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..config import LitSchemaConfig, load_config
from ..schema_resolution import resolve_extraction_schema
from ..schema_validation import write_json_schema


@dataclass(frozen=True)
class SchemaContext:
    runtime_dir: Path
    manifest_path: Path
    extraction_schema_path: Path
    extraction_root_class: str
    reasoning_schema_path: Path | None


def _project_relative(path: Path | None, project_root: Path) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def prepare_schema_context(cfg: LitSchemaConfig | None = None) -> SchemaContext:
    """Write runtime JSON Schemas derived from the configured LinkML schemas."""
    cfg = cfg or load_config()
    runtime_dir = cfg.project_root / ".litschema" / "runtime"
    manifest_path = runtime_dir / "schema_context.json"

    extraction_schema, root_class = resolve_extraction_schema(cfg)
    extraction_output = runtime_dir / "extraction_schema.json"
    write_json_schema(extraction_schema, root_class, extraction_output)

    reasoning_schema = cfg.schema_dir / "reasoning.yaml"
    reasoning_output: Path | None = None
    if reasoning_schema.exists():
        reasoning_output = runtime_dir / "reasoning_schema.json"
        write_json_schema(reasoning_schema, "ExtractionReasoning", reasoning_output)

    manifest_path.write_text(
        json.dumps(
            {
                "extraction_schema": _project_relative(extraction_output, cfg.project_root),
                "extraction_root_class": root_class,
                "reasoning_schema": _project_relative(reasoning_output, cfg.project_root),
            },
            indent=2,
        )
        + "\n"
    )

    return SchemaContext(
        runtime_dir=runtime_dir,
        manifest_path=manifest_path,
        extraction_schema_path=extraction_output,
        extraction_root_class=root_class,
        reasoning_schema_path=reasoning_output,
    )


def main() -> None:
    context = prepare_schema_context()
    print(f"schema_context={context.manifest_path}")
    print(f"extraction_root_class={context.extraction_root_class}")
    print(f"extraction_schema={context.extraction_schema_path}")
    if context.reasoning_schema_path:
        print(f"reasoning_schema={context.reasoning_schema_path}")


if __name__ == "__main__":
    main()
