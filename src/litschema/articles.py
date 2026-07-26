"""Per-article file layout helpers.

  data/papers/<id>/article-metadata.json
  data/papers/<id>/article.md
  data/papers/<id>/active-run.json
  data/papers/<id>/extraction-runs/<run-id>/...
  data/papers/<id>/review.json          (v1 review model, article-bound)

Article-root agent-extraction.json / agent-reasoning.json are STAGING files:
an extraction attempt writes them, and publication consumes them into an
immutable run directory (see runs.py).
"""

from __future__ import annotations

import json
import os
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
    def pdf(self) -> Path:
        return self.article_dir / f"{self.article_id}.pdf"

    @property
    def runs_dir(self) -> Path:
        return self.article_dir / "extraction-runs"

    @property
    def active_run_file(self) -> Path:
        return self.article_dir / "active-run.json"

    @property
    def staged_extraction(self) -> Path:
        """Where an extraction attempt stages its output before publication."""
        return self.article_dir / "agent-extraction.json"

    @property
    def staged_reasoning(self) -> Path:
        return self.article_dir / "agent-reasoning.json"

    @property
    def reviews(self) -> Path:
        return self.article_dir / "review.json"

    def read_metadata(self) -> dict:
        if not self.metadata.exists():
            return {}
        try:
            return json.loads(self.metadata.read_text())
        except json.JSONDecodeError:
            return {}


class InvalidArticleIdError(ValueError):
    """Raised for article ids that would escape the article store."""


def article_files(cfg: LitSchemaConfig, article_id: str) -> ArticleFiles:
    # Single chokepoint for every article path join: ids minted by assemble
    # are safe slugs, but ids also arrive from CLI arguments and URL path
    # segments and must never traverse outside the store.
    if not article_id or article_id in {".", ".."} or "/" in article_id or "\\" in article_id:
        raise InvalidArticleIdError(f"invalid article id: {article_id!r}")
    return ArticleFiles(cfg=cfg, article_id=article_id)


def article_id_from_extraction_path(path: Path) -> str:
    """Article id for an extraction path in either run or staging position."""
    if path.parent.parent.name == "extraction-runs":
        return path.parent.parent.parent.name
    return path.parent.name


def iter_article_ids(cfg: LitSchemaConfig) -> Iterator[str]:
    for metadata_path in iter_metadata_paths(cfg):
        yield metadata_path.parent.name


def iter_active_extraction_paths(cfg: LitSchemaConfig) -> Iterator[Path]:
    """The active run's extraction per article; skips unextracted articles.

    A broken active pointer raises BrokenActiveRunError (integrity failure,
    never silently skipped).
    """
    from .runs import active_run  # local import: runs builds on articles

    for metadata_path in iter_metadata_paths(cfg):
        files = article_files(cfg, metadata_path.parent.name)
        run = active_run(files)
        if run is not None:
            yield run.extraction


def iter_live_run_extraction_paths(cfg: LitSchemaConfig) -> Iterator[Path]:
    """Every published run's extraction, active or not (validate discovery)."""
    if not cfg.article_store_dir.is_dir():
        return
    for run_json in sorted(cfg.article_store_dir.glob("*/extraction-runs/*/run.json")):
        extraction = run_json.parent / "agent-extraction.json"
        if extraction.is_file():
            yield extraction


def iter_markdown_paths(cfg: LitSchemaConfig) -> Iterator[Path]:
    yield from _iter_article_artifact_paths(cfg, "article.md")




def iter_review_paths(cfg: LitSchemaConfig) -> Iterator[Path]:
    yield from _iter_article_artifact_paths(cfg, "review.json")


def iter_metadata_paths(cfg: LitSchemaConfig) -> Iterator[Path]:
    if not cfg.article_store_dir.is_dir():
        return
    yield from sorted(cfg.article_store_dir.glob("*/article-metadata.json"))


def _iter_article_artifact_paths(cfg: LitSchemaConfig, filename: str) -> Iterator[Path]:
    if not cfg.article_store_dir.is_dir():
        return
    yield from sorted(cfg.article_store_dir.glob(f"*/{filename}"))


def read_article_metadata(files: ArticleFiles) -> dict:
    if not files.metadata.exists():
        return {}
    data = json.loads(files.metadata.read_text())
    data.setdefault("id", files.article_id)
    return data


def write_article_metadata(files: ArticleFiles, metadata: dict) -> dict:
    """Merge ``metadata`` into the article manifest, creating it if needed.

    The per-article ``article-metadata.json`` is the source of truth and is
    enriched in place across the pipeline (assemble writes identity, extraction
    and harvest add bibliographic and provenance fields). Existing keys are
    preserved; ``None`` values in ``metadata`` are ignored.

    The write is atomic (same-directory tmp + rename): the manifest carries
    human-authored metadata and the ``manual`` protection tag, and a torn
    write would read back as ``{}`` — silently rebuilding the manifest from
    scratch on the next write.
    """
    files.article_dir.mkdir(parents=True, exist_ok=True)
    merged = files.read_metadata()
    merged.update({key: value for key, value in metadata.items() if value is not None})
    merged.setdefault("id", files.article_id)
    tmp = files.metadata.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(merged, indent=2) + "\n")
    os.replace(tmp, files.metadata)
    return merged
