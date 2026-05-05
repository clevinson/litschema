"""Per-article file layout helpers.

The current workspace still has legacy stage folders:

  data/llm_extractions/<id>.json
  data/extraction_reasoning/<id>.json
  data/reviews/<id>.json
  data/fulltext_md/<id>.md

The public-facing layout is one folder per article:

  data/papers/<id>/article-metadata.json
  data/papers/<id>/article.md
  data/papers/<id>/agent-extraction.json
  data/papers/<id>/agent-reasoning.json
  data/papers/<id>/reviews.jsonl

This module centralizes compatibility reads while consumers migrate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

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

    @property
    def legacy_markdown(self) -> Path:
        return self.cfg.fulltext_md_dir / f"{self.article_id}.md"

    @property
    def legacy_extraction(self) -> Path:
        return self.cfg.llm_extractions_dir / f"{self.article_id}.json"

    @property
    def legacy_reasoning(self) -> Path:
        return self.cfg.extraction_reasoning_dir / f"{self.article_id}.json"

    @property
    def legacy_reviews(self) -> Path:
        return self.cfg.annotations_dir / f"{self.article_id}.json"

    def markdown_path(self, *, for_write: bool = False) -> Path:
        if self.markdown.exists() or for_write:
            return self.markdown
        return self.legacy_markdown

    def extraction_path(self, *, for_write: bool = False) -> Path:
        if self.extraction.exists() or for_write:
            return self.extraction
        return self.legacy_extraction

    def reasoning_path(self, *, for_write: bool = False) -> Path:
        if self.reasoning.exists() or for_write:
            return self.reasoning
        return self.legacy_reasoning

    def reviews_path(self, *, for_write: bool = False) -> Path:
        if self.reviews.exists() or for_write:
            return self.reviews
        return self.legacy_reviews


def article_files(cfg: LitSchemaConfig, article_id: str) -> ArticleFiles:
    return ArticleFiles(cfg=cfg, article_id=article_id)


def article_id_from_extraction_path(path: Path) -> str:
    if path.name == "agent-extraction.json":
        return path.parent.name
    return path.stem


def iter_extraction_paths(cfg: LitSchemaConfig) -> Iterator[Path]:
    """Yield extraction files, preferring per-article folders over legacy files."""
    yield from _iter_artifact_paths(
        cfg,
        new_name="agent-extraction.json",
        legacy_dir=cfg.llm_extractions_dir,
        legacy_pattern="*.json",
    )


def iter_markdown_paths(cfg: LitSchemaConfig) -> Iterator[Path]:
    yield from _iter_artifact_paths(
        cfg,
        new_name="article.md",
        legacy_dir=cfg.fulltext_md_dir,
        legacy_pattern="*.md",
    )


def iter_reasoning_paths(cfg: LitSchemaConfig) -> Iterator[Path]:
    yield from _iter_artifact_paths(
        cfg,
        new_name="agent-reasoning.json",
        legacy_dir=cfg.extraction_reasoning_dir,
        legacy_pattern="*.json",
    )


def iter_review_paths(cfg: LitSchemaConfig) -> Iterator[Path]:
    yield from _iter_artifact_paths(
        cfg,
        new_name="reviews.jsonl",
        legacy_dir=cfg.annotations_dir,
        legacy_pattern="*.json",
    )


def _iter_artifact_paths(
    cfg: LitSchemaConfig,
    *,
    new_name: str,
    legacy_dir: Path,
    legacy_pattern: str,
) -> Iterator[Path]:
    """Yield artifact paths sorted by article id, preferring the new layout."""
    by_id: dict[str, Path] = {}
    if cfg.article_store_dir.is_dir():
        for path in sorted(cfg.article_store_dir.glob(f"*/{new_name}")):
            by_id[path.parent.name] = path
    if legacy_dir.is_dir():
        for path in sorted(legacy_dir.glob(legacy_pattern)):
            by_id.setdefault(path.stem, path)
    for article_id in sorted(by_id):
        yield by_id[article_id]


def iter_article_ids_with_extractions(cfg: LitSchemaConfig) -> Iterator[str]:
    for path in iter_extraction_paths(cfg):
        yield article_id_from_extraction_path(path)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def read_review_events(files: ArticleFiles) -> list[dict]:
    """Read review events from new JSONL or legacy per-article JSON."""
    if files.reviews.exists():
        events = _read_jsonl(files.reviews)
        for event in events:
            event.setdefault("article_id", files.article_id)
        return events

    if not files.legacy_reviews.exists():
        return []

    data = json.loads(files.legacy_reviews.read_text())
    events = data.get("annotations") or []
    article_id = data.get("article_id") or files.article_id
    for event in events:
        event.setdefault("article_id", article_id)
    return events
