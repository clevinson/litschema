"""Deterministic, local-first article intake.

Moves PDFs out of the inbox into per-article folders under
``data/papers/<article_id>/``, deriving a stable ``article_id`` from each PDF's
filename. Intake is intentionally offline: no DOI lookup, no OpenAlex/CrossRef,
no registry. Bibliographic metadata (title, authors, year, ...) is filled in
later by extraction or by the optional ``litschema harvest`` enrichment flow.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ..articles import ArticleFiles, article_files, write_article_metadata
from ..config import LitSchemaConfig, require_config_or_exit

logger = logging.getLogger(__name__)

AssembleReporter = Callable[[str, dict[str, object]], None]

#: Length of the content-hash suffix used to disambiguate colliding slugs.
SHORT_HASH_LEN = 6
_HASH_CHUNK = 1 << 20


class AssemblyInterrupted(Exception):
    """Raised when article assembly is cancelled by Ctrl-C."""

    def __init__(self, pdf_path: Path | None = None):
        self.pdf_path = pdf_path
        if pdf_path is None:
            message = "article assembly interrupted"
        else:
            message = f"article assembly interrupted while processing {pdf_path}"
        super().__init__(message)


def _report(reporter: AssembleReporter | None, event: str, **payload: object) -> None:
    if reporter is not None:
        reporter(event, payload)


def _is_wrapped_keyboard_interrupt(exc: BaseException) -> bool:
    return "KeyboardInterrupt" in f"{type(exc).__name__}: {exc}"


def _slugify(value: str) -> str:
    """Collapse a filename stem into a safe, single-component article id.

    Only ``[a-z0-9-]`` survive, so the result can never contain a path
    separator or ``..`` and is always a single component under the article
    store.
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "article"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _existing_sha(files: ArticleFiles) -> str | None:
    metadata = files.read_metadata()
    sha = metadata.get("file_sha256")
    return str(sha) if sha else None


def _resolve_article_id(
    cfg: LitSchemaConfig, slug: str, sha: str, existing_ids: set[str]
) -> tuple[str, bool]:
    """Return ``(article_id, already_assembled)`` for a PDF.

    ``already_assembled`` is True when an article folder with the chosen id
    already holds a PDF with the same content hash (an idempotent re-drop).
    Slug collisions on *different* content are disambiguated with a short
    content-hash suffix.
    """
    if slug not in existing_ids:
        return slug, False
    if _existing_sha(article_files(cfg, slug)) == sha:
        return slug, True
    suffixed = f"{slug}-{sha[:SHORT_HASH_LEN]}"
    if suffixed in existing_ids and _existing_sha(article_files(cfg, suffixed)) == sha:
        return suffixed, True
    return suffixed, False


def _archive_processed_inbox_pdf(pdf_path: Path) -> None:
    """Move an already-assembled duplicate aside so the inbox stays clean."""
    processed_dir = pdf_path.parent / ".processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    target = processed_dir / pdf_path.name
    try:
        if target.exists():
            target.unlink()
        shutil.move(str(pdf_path), str(target))
        logger.info("Archived duplicate inbox PDF: %s -> %s", pdf_path, target)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Unable to archive duplicate inbox PDF: %s", pdf_path)


def _process_inbox_pdf(
    cfg: LitSchemaConfig, pdf_path: Path, existing_ids: set[str]
) -> tuple[str, str]:
    """Move one inbox PDF into its article folder. Returns ``(result, id)``."""
    sha = _sha256(pdf_path)
    slug = _slugify(pdf_path.stem)
    article_id, already_assembled = _resolve_article_id(cfg, slug, sha, existing_ids)
    files = article_files(cfg, article_id)

    if already_assembled:
        _archive_processed_inbox_pdf(pdf_path)
        return "already_assembled", article_id

    files.article_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pdf_path), str(files.pdf))
    write_article_metadata(
        files,
        {
            "id": article_id,
            "filename": files.pdf.name,
            "original_filename": pdf_path.name,
            "file_sha256": sha,
            "added_at": datetime.now(UTC).isoformat(),
        },
    )
    existing_ids.add(article_id)
    return "assembled", article_id


def assemble(cfg: LitSchemaConfig, reporter: AssembleReporter | None = None) -> dict[str, int]:
    """Move every inbox PDF into a per-article folder. Offline and idempotent."""
    cfg.article_store_dir.mkdir(parents=True, exist_ok=True)
    existing_ids = {path.name for path in cfg.article_store_dir.glob("*") if path.is_dir()}

    stats = {"inbox_pdfs": 0, "assembled": 0, "already_assembled": 0, "errors": 0}

    inbox_pdfs = sorted(cfg.paper_inbox_dir.glob("*.pdf")) if cfg.paper_inbox_dir.is_dir() else []
    _report(reporter, "start", inbox_pdfs=len(inbox_pdfs))

    for index, pdf_path in enumerate(inbox_pdfs, start=1):
        stats["inbox_pdfs"] += 1
        _report(reporter, "pdf_start", path=pdf_path, index=index, total=len(inbox_pdfs))
        try:
            result, article_id = _process_inbox_pdf(cfg, pdf_path, existing_ids)
        except KeyboardInterrupt as exc:
            raise AssemblyInterrupted(pdf_path) from exc
        except Exception as exc:
            if _is_wrapped_keyboard_interrupt(exc):
                raise AssemblyInterrupted(pdf_path) from exc
            logger.exception("Failed to assemble inbox PDF: %s", pdf_path)
            stats["errors"] += 1
            _report(reporter, "pdf_error", path=pdf_path, error=exc)
            continue
        if result == "assembled":
            stats["assembled"] += 1
        elif result == "already_assembled":
            stats["already_assembled"] += 1
        _report(reporter, "pdf", path=pdf_path, result=result, article_id=article_id)

    logger.info("Article assembly complete: %s", stats)
    return stats


def main() -> None:
    import argparse
    import json

    argparse.ArgumentParser(description="Move inbox PDFs into per-article folders").parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = require_config_or_exit()
    print(json.dumps(assemble(cfg), indent=2))


if __name__ == "__main__":
    main()
