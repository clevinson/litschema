"""Helpers for resolving a project's configured extraction schema."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from linkml_runtime.utils.schemaview import SchemaView

from .config import LitSchemaConfig

DEFAULT_EXTRACTION_SCHEMA = "extraction.yaml"


@dataclass(frozen=True)
class ResolvedExtractionSchema:
    path: Path
    view: SchemaView
    root_class: str


def extraction_schema_path(cfg: LitSchemaConfig) -> Path:
    """Resolve the extraction schema file path from config.

    Lenient: returns the path even if the file does not exist; callers
    that need the file to exist (e.g. :func:`resolve_extraction_schema`)
    check separately, while informational consumers (status, MCP) decide
    how to render a missing file.
    """
    schema_file = cfg.raw.get("extraction_schema_file", DEFAULT_EXTRACTION_SCHEMA)
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


def schema_hash(cfg: LitSchemaConfig) -> str:
    """Schema identity: the SHA-256 of the configured schema file's exact bytes.

    The digest alone identifies the schema (specs/project-config/spec.md);
    deterministic and independent of the working directory.
    """
    import hashlib

    return "sha256:" + hashlib.sha256(extraction_schema_path(cfg).read_bytes()).hexdigest()


def resolve_extraction_schema(cfg: LitSchemaConfig) -> ResolvedExtractionSchema:
    schema_path = extraction_schema_path(cfg)
    if not schema_path.exists():
        raise FileNotFoundError(
            f"extraction schema not found at {schema_path}. "
            "Set `extraction_schema_file` in litschema.yaml or place a file "
            "at the default location."
        )
    sv = SchemaView(str(schema_path))
    return ResolvedExtractionSchema(
        path=schema_path,
        view=sv,
        root_class=_find_tree_root_class(sv),
    )
