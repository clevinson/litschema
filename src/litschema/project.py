"""Runtime project context for a litschema invocation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import LitSchemaConfig, load_config


@dataclass(frozen=True)
class Project:
    """Resolved runtime context for one litschema project."""

    config: LitSchemaConfig

    @classmethod
    def open(cls, config_path: Path | str | None = None) -> Project:
        return cls(config=load_config(config_path))

    def article_dir(self, article_id: str) -> Path:
        return self.config.article_store_dir / article_id
