"""Per-article file layout helpers.

  data/papers/<id>/article-metadata.json
  data/papers/<id>/article.md
  data/papers/<id>/agent-extraction.json
  data/papers/<id>/agent-reasoning.json
  data/papers/<id>/reviews.jsonl
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .config import LitSchemaConfig


@dataclass(frozen=True)
class ArticleFiles:
    cfg: LitSchemaConfig
    article_id: str

    @property
    def article_dir(self) -> Path:
        return self.cfg.article_store_dir / self.article_id

    @property
    def metadata(self) -> Path:
        return self.article_dir / "article-metadata.json"

    @property
    def markdown(self) -> Path:
        return self.article_dir / "article.md"

    @property
    def extraction(self) -> Path:
        return self.article_dir / "agent-extraction.json"

    @property
    def reasoning(self) -> Path:
        return self.article_dir / "agent-reasoning.json"

    @property
    def reviews(self) -> Path:
        return self.article_dir / "reviews.jsonl"

    def markdown_path(self, *, for_write: bool = False) -> Path:
        return self.markdown

    def extraction_path(self, *, for_write: bool = False) -> Path:
        return self.extraction

    def reasoning_path(self, *, for_write: bool = False) -> Path:
        return self.reasoning

    def reviews_path(self, *, for_write: bool = False) -> Path:
        return self.reviews


def article_files(cfg: LitSchemaConfig, article_id: str) -> ArticleFiles:
    return ArticleFiles(cfg=cfg, article_id=article_id)


def article_id_from_extraction_path(path: Path) -> str:
    return path.parent.name


def iter_extraction_paths(cfg: LitSchemaConfig) -> Iterator[Path]:
    yield from _iter_article_artifact_paths(cfg, "agent-extraction.json")


def iter_markdown_paths(cfg: LitSchemaConfig) -> Iterator[Path]:
    yield from _iter_article_artifact_paths(cfg, "article.md")


def iter_reasoning_paths(cfg: LitSchemaConfig) -> Iterator[Path]:
    yield from _iter_article_artifact_paths(cfg, "agent-reasoning.json")


def iter_review_paths(cfg: LitSchemaConfig) -> Iterator[Path]:
    yield from _iter_article_artifact_paths(cfg, "reviews.jsonl")


def iter_metadata_paths(cfg: LitSchemaConfig) -> Iterator[Path]:
    if not cfg.article_store_dir.is_dir():
        return
    yield from sorted(cfg.article_store_dir.glob("*/article-metadata.json"))


def _iter_article_artifact_paths(cfg: LitSchemaConfig, filename: str) -> Iterator[Path]:
    if not cfg.article_store_dir.is_dir():
        return
    yield from sorted(cfg.article_store_dir.glob(f"*/{filename}"))


def iter_article_ids_with_extractions(cfg: LitSchemaConfig) -> Iterator[str]:
    for path in iter_extraction_paths(cfg):
        yield article_id_from_extraction_path(path)


def read_article_metadata(files: ArticleFiles) -> dict:
    if not files.metadata.exists():
        return {}
    data = json.loads(files.metadata.read_text())
    data.setdefault("id", files.article_id)
    return data


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def read_review_events(files: ArticleFiles) -> list[dict]:
    if not files.reviews.exists():
        return []
    events = _read_jsonl(files.reviews)
    for event in events:
        event.setdefault("article_id", files.article_id)
    return events
