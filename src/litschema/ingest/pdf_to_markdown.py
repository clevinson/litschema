"""Phase 2b: Convert PDFs to markdown for LLM extraction.

Uses pymupdf4llm for fast, CPU-only PDF-to-markdown conversion.
Reads corpus.yaml for article_id -> filename mapping.

Usage:
    uv run python -m litschema.ingest.pdf_to_markdown [--force] [--papers-dir DIR]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import yaml

from ..config import load_config

logger = logging.getLogger(__name__)

_CFG = load_config()
PROJECT_ROOT = _CFG.project_root
CORPUS_PATH = _CFG.corpus_file
PAPERS_DIR = _CFG.papers_dir
FULLTEXT_DIR = _CFG.fulltext_md_dir

# Minimum character count to consider a conversion non-empty
# (scanned PDFs may produce very little text)
MIN_CHARS = 100


def convert_pdf(pdf_path: Path, out_path: Path) -> int:
    """Convert a single PDF to markdown. Returns character count."""
    import pymupdf4llm

    md_text = pymupdf4llm.to_markdown(str(pdf_path))
    out_path.write_text(md_text, encoding="utf-8")
    return len(md_text)


def run(
    corpus_path: Path = CORPUS_PATH,
    papers_dir: Path = PAPERS_DIR,
    output_dir: Path = FULLTEXT_DIR,
    force: bool = False,
) -> dict:
    """Convert all PDFs referenced in corpus.yaml to markdown."""
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(corpus_path) as f:
        corpus = yaml.safe_load(f)

    articles = corpus.get("articles", [])
    stats = {"total": 0, "converted": 0, "skipped": 0, "empty": 0, "missing": 0, "errors": 0}

    for article in articles:
        article_id = article.get("id")
        filename = article.get("filename")
        if not filename:
            continue

        stats["total"] += 1
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
    parser.add_argument("--papers-dir", type=Path, default=PAPERS_DIR)
    parser.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    parser.add_argument("--output-dir", type=Path, default=FULLTEXT_DIR)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stats = run(
        corpus_path=args.corpus,
        papers_dir=args.papers_dir,
        output_dir=args.output_dir,
        force=args.force,
    )
    import json

    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
