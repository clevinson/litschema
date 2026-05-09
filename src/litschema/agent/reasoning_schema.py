"""Resolve the reasoning schema used by agent validation."""

from __future__ import annotations

from importlib import resources
from pathlib import Path


def reasoning_schema_source_path() -> Path:
    """Return the bundled litschema reasoning schema."""
    return Path(str(resources.files("litschema.agent") / "reasoning.yaml"))
