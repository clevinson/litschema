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
    def open(
        cls,
        config_path: Path | str | None = None,
        *,
        config: LitSchemaConfig | None = None,
    ) -> Project:
        cfg = config if config is not None else load_config(config_path)
        return cls(config=cfg)

    def article_dir(self, article_id: str) -> Path:
        return self.config.article_store_dir / article_id
