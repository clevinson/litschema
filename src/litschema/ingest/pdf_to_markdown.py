"""Phase 2b: Prepare article markdown from PDFs for LLM extraction.

Uses pymupdf4llm for fast, CPU-only PDF-to-markdown conversion.
Reads data/papers/<article_id>/article-metadata.json for filename mapping.
Writes article.md, the figures/ it references, and prepared-text.json.

Usage:
    uv run python -m litschema.ingest.pdf_to_markdown [--force] [--inbox-dir DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ..articles import article_files, iter_metadata_paths
from ..config import LitSchemaConfig, require_config_or_exit

logger = logging.getLogger(__name__)

# Minimum character count to consider a conversion non-empty
# (scanned PDFs may produce very little text)
MIN_CHARS = 100

PREPARED_TEXT_RECORD_VERSION = 1

# Keyword arguments for pymupdf4llm.to_markdown, minus image_path (a local path).
CONVERSION_OPTIONS = {
    "use_ocr": False,
    "header": False,
    "footer": False,
    "write_images": True,
    "image_format": "png",
    "dpi": 150,
}

# Images repeated this often are logos or page furniture; smaller ones are icons.
FIGURE_FILTER = {
    "drop_figure_repeats_at": 3,
    "min_figure_width_px": 150,
    "min_figure_height_px": 100,
}

# pymupdf4llm writes each image on its own line.
_IMAGE_LINE = re.compile(r"^!\[[^\]]*\]\((?P<ref>.+)\)[ \t]*$", re.MULTILINE)


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def figures_sha256(figures: list[dict]) -> str:
    """Hash over the sorted ``name:sha256`` lines of a figure list."""
    lines = "".join(f"{f['name']}:{f['sha256']}\n" for f in sorted(figures, key=lambda f: f["name"]))
    return _sha256_bytes(lines.encode())


def select_figures(figures_dir: Path) -> tuple[set[str], set[str]]:
    """Split the images in ``figures_dir`` into (kept, dropped) names."""
    import pymupdf

    if not figures_dir.is_dir():
        return set(), set()
    paths = sorted(p for p in figures_dir.iterdir() if p.is_file())
    digests = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    counts = Counter(digests.values())
    kept, dropped = set(), set()
    for path in paths:
        pix = pymupdf.Pixmap(str(path))
        repeated = counts[digests[path.name]] >= FIGURE_FILTER["drop_figure_repeats_at"]
        small = (
            pix.width < FIGURE_FILTER["min_figure_width_px"]
            or pix.height < FIGURE_FILTER["min_figure_height_px"]
        )
        (dropped if repeated or small else kept).add(path.name)
    return kept, dropped


def postprocess_markdown(
    md_text: str, *, kept: set[str], dropped: set[str], figures_ref: str
) -> str:
    """Rewrite kept image refs to ``figures_ref/<name>``, blank dropped ones, strip <mark>.

    Dropped image lines stay as empty lines. Refs to files this conversion did
    not write are left alone.
    """

    def rewrite(match: re.Match) -> str:
        name = match.group("ref").rsplit("/", 1)[-1]
        if name in dropped:
            return ""
        if name in kept:
            return f"![]({figures_ref}/{name})"
        return match.group(0)

    md_text = _IMAGE_LINE.sub(rewrite, md_text)
    return md_text.replace("<mark>", "").replace("</mark>", "")


def convert_pdf(pdf_path: Path, out_path: Path, figures_dir: Path, record_path: Path) -> int:
    """Convert one PDF to markdown, figures, and a conversion record.

    ``figures_dir`` must sit beside ``out_path``; refs in the markdown are
    relative to it. An existing ``figures_dir`` is replaced. Returns the
    markdown's character count.
    """
    import pymupdf
    import pymupdf4llm

    from ..schema_validation import write_json_file
    from ..version import installed_version

    if figures_dir.parent != out_path.parent:
        raise ValueError(f"{figures_dir} must be beside {out_path}")
    staging = figures_dir.with_name(f".{figures_dir.name}.{uuid4().hex}.tmp")
    try:
        md_text = pymupdf4llm.to_markdown(
            str(pdf_path), image_path=str(staging), **CONVERSION_OPTIONS
        )
        kept, dropped = select_figures(staging)
        for name in dropped:
            (staging / name).unlink()
        md_text = postprocess_markdown(
            md_text, kept=kept, dropped=dropped, figures_ref=figures_dir.name
        )
        if figures_dir.exists():
            shutil.rmtree(figures_dir)
        if kept:
            staging.rename(figures_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    out_path.write_text(md_text, encoding="utf-8")
    figures = [
        {"name": name, "sha256": _sha256_bytes((figures_dir / name).read_bytes())}
        for name in sorted(kept)
    ]
    write_json_file(
        record_path,
        {
            "version": PREPARED_TEXT_RECORD_VERSION,
            "tool": "pymupdf4llm",
            "tool_version": pymupdf4llm.__version__,
            "pymupdf_version": pymupdf.VersionBind,
            "options": {**CONVERSION_OPTIONS, **FIGURE_FILTER},
            "pdf_sha256": _sha256_bytes(pdf_path.read_bytes()),
            "text_sha256": _sha256_bytes(out_path.read_bytes()),
            "figures": figures,
            "litschema_version": installed_version(),
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    )
    return len(md_text)


def _resolve_pdf(*candidates: Path) -> Path | None:
    """First existing PDF: manifest filename, canonical <id>.pdf, then inbox."""
    return next((path for path in candidates if path.is_file()), None)


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
        if output_dir is None:
            out_path = files.markdown
            figures_dir = files.figures_dir
            record_path = files.prepared_text_record
        else:
            out_path = output_dir / f"{article_id}.md"
            figures_dir = output_dir / f"{article_id}-figures"
            record_path = output_dir / f"{article_id}.prepared-text.json"

        if out_path.exists() and not force:
            stats["skipped"] += 1
            continue

        pdf_path = _resolve_pdf(files.article_dir / filename, files.pdf, inbox_dir / filename)
        if pdf_path is None:
            logger.warning("PDF not found: %s (article %s)", filename, article_id)
            stats["missing"] += 1
            continue

        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path = files.metadata
            if not metadata_path.exists():
                metadata_path.parent.mkdir(parents=True, exist_ok=True)
                metadata_path.write_text(json.dumps(article, indent=2) + "\n")
            char_count = convert_pdf(pdf_path, out_path, figures_dir, record_path)
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
