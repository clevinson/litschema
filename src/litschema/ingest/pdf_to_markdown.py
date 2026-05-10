"""Phase 2b: Convert PDFs to markdown for LLM extraction.

Uses pymupdf4llm for fast, CPU-only PDF-to-markdown conversion.
Reads data/papers/<article_id>/article-metadata.json for filename mapping.

Usage:
    uv run python -m litschema.ingest.pdf_to_markdown [--force] [--papers-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from ..articles import article_files, iter_metadata_paths
from ..config import LitSchemaConfig, require_config

logger = logging.getLogger(__name__)

# Minimum character count to consider a conversion non-empty
# (scanned PDFs may produce very little text)
MIN_CHARS = 100


def convert_pdf(pdf_path: Path, out_path: Path) -> int:
    """Convert a single PDF to markdown. Returns character count."""
    import pymupdf4llm

    md_text = pymupdf4llm.to_markdown(str(pdf_path))
    out_path.write_text(md_text, encoding="utf-8")
    return len(md_text)


def _load_articles(cfg: LitSchemaConfig) -> list[dict]:
    articles = []
    for path in iter_metadata_paths(cfg):
        data = json.loads(path.read_text())
        data.setdefault("id", path.parent.name)
        articles.append(data)
    return sorted(articles, key=lambda article: article.get("id", ""))


def run(
    cfg: LitSchemaConfig,
    *,
    papers_dir: Path | None = None,
    output_dir: Path | None = None,
    force: bool = False,
) -> dict:
    """Convert all PDFs referenced by per-article metadata to markdown."""
    papers_dir = papers_dir or cfg.papers_dir
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    articles = _load_articles(cfg)
    stats = {"total": 0, "converted": 0, "skipped": 0, "empty": 0, "missing": 0, "errors": 0}

    for article in articles:
        article_id = article.get("id")
        filename = article.get("filename")
        if not filename:
            continue

        stats["total"] += 1
        if output_dir is None:
            out_path = article_files(cfg, article_id).markdown_path(for_write=True)
        else:
            # Explicit output-dir keeps the historical flat-folder behavior.
            out_path = output_dir / f"{article_id}.md"

        if out_path.exists() and not force:
            stats["skipped"] += 1
            continue

        pdf_path = papers_dir / filename
        if not pdf_path.exists():
            logger.warning("PDF not found: %s (article %s)", filename, article_id)
            stats["missing"] += 1
            continue

        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            char_count = convert_pdf(pdf_path, out_path)
            if char_count < MIN_CHARS:
                logger.warning("Empty/scanned PDF: %s (%d chars)", article_id, char_count)
                stats["empty"] += 1
            else:
                stats["converted"] += 1
        except Exception as e:
            logger.error("Failed to convert %s: %s", article_id, e)
            stats["errors"] += 1

        done = (
            stats["converted"]
            + stats["skipped"]
            + stats["empty"]
            + stats["missing"]
            + stats["errors"]
        )
        if done % 50 == 0:
            logger.info("Progress: %d/%d", done, stats["total"])

    logger.info("PDF conversion complete: %s", stats)
    return stats


def main():
    parser = argparse.ArgumentParser(description="Convert PDFs to markdown for LLM extraction")
    parser.add_argument("--force", action="store_true", help="Re-convert existing files")
    parser.add_argument("--papers-dir", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Write flat {article_id}.md files to DIR instead of data/papers/<id>/article.md",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = require_config()
    stats = run(
        cfg,
        papers_dir=args.papers_dir,
        output_dir=args.output_dir,
        force=args.force,
    )
    import json

    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
