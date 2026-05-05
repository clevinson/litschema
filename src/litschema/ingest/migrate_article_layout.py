"""Migrate legacy stage folders into per-article folders."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import typer
import yaml

from ..articles import article_files
from ..config import LitSchemaConfig, load_config


def _load_article_metadata(corpus_file: Path) -> dict[str, dict]:
    if not corpus_file.exists():
        return {}
    corpus = yaml.safe_load(corpus_file.read_text()) or {}
    articles = corpus.get("articles") or []
    return {article["id"]: article for article in articles if article.get("id")}


def _legacy_review_events(path: Path, article_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    events = data.get("annotations") or []
    for event in events:
        event.setdefault("article_id", data.get("article_id") or article_id)
    return events


def _copy_if_exists(src: Path, dest: Path, *, overwrite: bool) -> bool:
    if not src.exists():
        return False
    if dest.exists() and not overwrite:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True


def migrate_article_layout(
    cfg: LitSchemaConfig,
    *,
    overwrite: bool = False,
) -> dict[str, int]:
    """Copy legacy article artifacts into `data/papers/<id>/`.

    The migration is intentionally copy-first. Legacy folders remain in place
    until all consumers have moved to the new layout.
    """
    metadata_by_id = _load_article_metadata(cfg.corpus_file)
    article_ids = {
        *metadata_by_id.keys(),
        *(p.stem for p in cfg.llm_extractions_dir.glob("*.json")),
        *(p.stem for p in cfg.extraction_reasoning_dir.glob("*.json")),
        *(p.stem for p in cfg.fulltext_md_dir.glob("*.md")),
        *(p.stem for p in cfg.annotations_dir.glob("*.json")),
    }

    summary = {
        "articles": 0,
        "metadata": 0,
        "markdown": 0,
        "extractions": 0,
        "reasoning": 0,
        "reviews": 0,
    }
    for article_id in sorted(article_ids):
        files = article_files(cfg, article_id)
        files.article_dir.mkdir(parents=True, exist_ok=True)
        summary["articles"] += 1

        metadata = metadata_by_id.get(article_id)
        if metadata and (overwrite or not files.metadata.exists()):
            files.metadata.write_text(json.dumps(metadata, indent=2) + "\n")
            summary["metadata"] += 1

        if _copy_if_exists(files.legacy_markdown, files.markdown, overwrite=overwrite):
            summary["markdown"] += 1
        if _copy_if_exists(files.legacy_extraction, files.extraction, overwrite=overwrite):
            summary["extractions"] += 1
        if _copy_if_exists(files.legacy_reasoning, files.reasoning, overwrite=overwrite):
            summary["reasoning"] += 1

        events = _legacy_review_events(files.legacy_reviews, article_id)
        if events and (overwrite or not files.reviews.exists()):
            with files.reviews.open("w") as fh:
                for event in events:
                    fh.write(json.dumps(event) + "\n")
            summary["reviews"] += 1

    return summary


def main() -> None:
    cfg = load_config()
    summary = migrate_article_layout(cfg)
    typer.echo(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
