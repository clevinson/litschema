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
    raise ValueError(
        "could not determine the root extraction class. "
        "Mark exactly one locally-defined class with `tree_root: true`."
    )


def resolve_extraction_schema_view(cfg: LitSchemaConfig) -> tuple[SchemaView, str]:
    if "extraction_class" in cfg.raw:
        raise ValueError(
            "`extraction_class` is no longer supported. "
            "Mark the extraction root class with `tree_root: true` in the LinkML schema."
        )
    schema_path = extraction_schema_path(cfg)
    sv = SchemaView(str(schema_path))
    return sv, _find_tree_root_class(sv)


def resolve_extraction_schema(cfg: LitSchemaConfig) -> tuple[Path, str]:
    schema_path = extraction_schema_path(cfg)
    _, root_class = resolve_extraction_schema_view(cfg)
    return schema_path, root_class
