"""Helpers for resolving a project's configured extraction schema."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from linkml_runtime.utils.schemaview import SchemaView

from .config import LitSchemaConfig

DEFAULT_EXTRACTION_SCHEMA = "extraction.yaml"
DEFAULT_DOMAIN_SCHEMA = "erw_articles.yaml"


@dataclass(frozen=True)
class ResolvedExtractionSchema:
    path: Path
    view: SchemaView
    root_class: str


def _extraction_schema_path(cfg: LitSchemaConfig) -> Path:
    schema_file = cfg.raw.get("extraction_schema_file", DEFAULT_EXTRACTION_SCHEMA)
    path = cfg.schema_dir / schema_file
    if path.exists():
        return path
    raise FileNotFoundError(
        f"extraction schema not found at {path}. "
        "Set `extraction_schema_file` in litschema.yaml or place a file at the default location."
    )


def resolve_domain_schema_path(cfg: LitSchemaConfig) -> Path:
    """Resolve the domain's root LinkML schema file.

    The domain root is the schema that imports everything else
    (``schema_root`` in litschema.yaml, defaulting to ``erw_articles.yaml``).
    Lenient: returns the path even if the file does not exist; callers
    decide how to react (``status`` reports a missing file; the MCP tool
    returns an error string).
    """
    schema_file = cfg.raw.get("schema_root", DEFAULT_DOMAIN_SCHEMA)
    return cfg.schema_dir / schema_file


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


def resolve_extraction_schema(cfg: LitSchemaConfig) -> ResolvedExtractionSchema:
    schema_path = _extraction_schema_path(cfg)
    sv = SchemaView(str(schema_path))
    return ResolvedExtractionSchema(
        path=schema_path,
        view=sv,
        root_class=_find_tree_root_class(sv),
    )
