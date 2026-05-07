"""Helpers for resolving a project's configured extraction schema."""

from __future__ import annotations

from pathlib import Path

from linkml_runtime.utils.schemaview import SchemaView

from .config import LitSchemaConfig

DEFAULT_EXTRACTION_SCHEMA = "extraction.yaml"


def extraction_schema_path(cfg: LitSchemaConfig) -> Path:
    schema_file = cfg.raw.get("extraction_schema_file", DEFAULT_EXTRACTION_SCHEMA)
    path = cfg.schema_dir / schema_file
    if path.exists():
        return path
    raise FileNotFoundError(
        f"extraction schema not found at {path}. "
        "Set `extraction_schema_file` in litschema.yaml or place a file at the default location."
    )


def _find_tree_root_class(sv: SchemaView) -> str:
    local_classes = sv.schema.classes or {}
    roots = [name for name, cls in local_classes.items() if getattr(cls, "tree_root", False)]
    if len(roots) == 1:
        return roots[0]
    if len(roots) > 1:
        raise ValueError(f"multiple locally-defined classes marked `tree_root: true`: {roots}")
    raise ValueError("no tree_root class found in extraction schema")


def resolve_extraction_schema(cfg: LitSchemaConfig) -> tuple[Path, str]:
    schema_path = extraction_schema_path(cfg)
    sv = SchemaView(str(schema_path))

    explicit = cfg.raw.get("extraction_class")
    if explicit:
        if explicit not in sv.all_classes():
            raise ValueError(
                f"`extraction_class: {explicit}` not found in {schema_path}. "
                f"Available classes: {sorted(sv.all_classes().keys())}"
            )
        return schema_path, explicit

    return schema_path, _find_tree_root_class(sv)
