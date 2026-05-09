"""Resolve the reasoning schema used by agent validation."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from ..config import LitSchemaConfig


def reasoning_schema_source_path(cfg: LitSchemaConfig) -> Path:
    """Return the project reasoning schema, or the bundled default."""
    project_schema = cfg.schema_dir / "reasoning.yaml"
    if project_schema.exists():
        return project_schema
    return Path(str(resources.files("litschema.agent") / "reasoning.yaml"))
