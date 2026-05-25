"""Phase 2b: Prepare article markdown from PDFs for LLM extraction.

Uses pymupdf4llm for fast, CPU-only PDF-to-markdown conversion.
Reads data/papers/<article_id>/article-metadata.json for filename mapping.

Usage:
    uv run python -m litschema.ingest.pdf_to_markdown [--force] [--inbox-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

from ..articles import article_files, iter_metadata_paths
from ..config import LitSchemaConfig, require_config_or_exit

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


def _article_id_from_pdf(pdf_path: Path) -> str:
    article_id = re.sub(r"[^a-zA-Z0-9]+", "-", pdf_path.stem).strip("-").lower()
    return article_id or pdf_path.stem


def _load_article(cfg: LitSchemaConfig, inbox_dir: Path, article_id: str) -> dict:
    files = article_files(cfg, article_id)
    article = json.loads(files.metadata.read_text()) if files.metadata.exists() else {}
    article["id"] = article.get("id") or article_id
    if not article.get("filename"):
        canonical_pdfs = sorted(files.article_dir.glob("*.pdf"))
        if canonical_pdfs:
            article["filename"] = canonical_pdfs[0].name
        elif inbox_dir.joinpath(f"{article_id}.pdf").exists():
            article["filename"] = f"{article_id}.pdf"
    return article


def _load_articles(
    cfg: LitSchemaConfig,
    inbox_dir: Path,
    article_ids: list[str] | tuple[str, ...] | None = None,
) -> list[dict]:
    if article_ids is not None:
        seen = set()
        articles = []
        for article_id in article_ids:
            if article_id in seen:
                continue
            seen.add(article_id)
            articles.append(_load_article(cfg, inbox_dir, article_id))
        return articles

    articles = []
    seen_filenames = set()
    for path in iter_metadata_paths(cfg):
        data = json.loads(path.read_text())
        data.setdefault("id", path.parent.name)
        filename = data.get("filename")
        if filename:
            seen_filenames.add(filename)
        articles.append(data)
    if inbox_dir.is_dir():
        for pdf_path in sorted(inbox_dir.glob("*.pdf")):
            if pdf_path.name in seen_filenames:
                continue
            articles.append({"id": _article_id_from_pdf(pdf_path), "filename": pdf_path.name})
    return sorted(articles, key=lambda article: article.get("id", ""))


def run(
    cfg: LitSchemaConfig,
    *,
    article_ids: list[str] | tuple[str, ...] | None = None,
    inbox_dir: Path | None = None,
    output_dir: Path | None = None,
    force: bool = False,
) -> dict:
    """Convert all PDFs referenced by per-article metadata to markdown."""
    inbox_dir = inbox_dir or cfg.paper_inbox_dir
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    articles = _load_articles(cfg, inbox_dir, article_ids=article_ids)
    stats = {"total": 0, "converted": 0, "skipped": 0, "empty": 0, "missing": 0, "errors": 0}

    for article in articles:
        article_id = article.get("id")
        filename = article.get("filename")
        stats["total"] += 1
        if not filename:
            logger.warning("PDF filename not found for article %s", article_id)
            stats["missing"] += 1
            continue

        files = article_files(cfg, article_id)
        out_path = files.markdown if output_dir is None else output_dir / f"{article_id}.md"

        if out_path.exists() and not force:
            stats["skipped"] += 1
            continue

        canonical_pdf = files.article_dir / filename
        pdf_path = canonical_pdf if canonical_pdf.exists() else inbox_dir / filename
        if not pdf_path.exists():
            logger.warning("PDF not found: %s (article %s)", filename, article_id)
            stats["missing"] += 1
            continue

        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path = files.metadata
            if not metadata_path.exists():
                metadata_path.parent.mkdir(parents=True, exist_ok=True)
                metadata_path.write_text(json.dumps(article, indent=2) + "\n")
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

    logger.info("PDF text preparation complete: %s", stats)
    return stats


def main():
    parser = argparse.ArgumentParser(description="Prepare article markdown from PDFs")
    parser.add_argument("--force", action="store_true", help="Rebuild existing files")
    parser.add_argument("--inbox-dir", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Write flat {article_id}.md files to DIR instead of data/papers/<id>/article.md",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = require_config_or_exit()
    stats = run(
        cfg,
        inbox_dir=args.inbox_dir,
        output_dir=args.output_dir,
        force=args.force,
    )
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
