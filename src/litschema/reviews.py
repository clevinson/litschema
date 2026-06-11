"""Per-article human-review storage: ``data/papers/<id>/review.json``.

The current verification state IS the file (design doc §4, option B): a map of
canonical field path -> review entries, at most one entry per field per
author. Entries use ``{author, signal: verified|flagged, override_value?,
timestamp}`` (+ optional ``note``/``source``/``batch_id``). The webapp API
keeps its historical field names (status/reviewer/correct_value) and maps at
the endpoint boundary — see ``webapp/app.py``.

The append-only ``reviews.jsonl`` predecessor migrates lazily and one-time:
first read collapses the event log and renames it to ``reviews.jsonl.bak``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from pathlib import Path

from .articles import ArticleFiles

logger = logging.getLogger(__name__)

REVIEW_VERSION = 1
_LEGACY_NAME = "reviews.jsonl"

#: Optional entry keys carried verbatim from the API payload.
OPTIONAL_ENTRY_KEYS = ("override_value", "note", "source", "batch_id")


def canonical_review_path(path: str) -> str:
    """Normalize a review path to ``_leaf_paths`` bracket syntax.

    Legacy event paths look like ``.experiments.0.ph``; canonical form is
    ``experiments[0].ph`` (no leading dot, numeric segments bracketed).
    Already-canonical paths pass through unchanged.
    """
    path = path.lstrip(".")
    return re.sub(r"\.(\d+)(?=\.|\[|$)", r"[\1]", path)


def _review_path(files: ArticleFiles) -> Path:
    return files.article_dir / "review.json"


def read_reviews(files: ArticleFiles) -> dict[str, list[dict]]:
    """Return the ``fields`` map. Runs the lazy legacy migration first."""
    migrate_legacy_reviews(files)
    path = _review_path(files)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        logger.warning("Unreadable review.json (leaving in place): %s", path)
        return {}
    fields = data.get("fields") if isinstance(data, dict) else None
    return fields if isinstance(fields, dict) else {}


def write_reviews(files: ArticleFiles, fields: dict[str, list[dict]]) -> None:
    """Atomically replace review.json; remove it entirely when empty."""
    path = _review_path(files)
    fields = {p: entries for p, entries in fields.items() if entries}
    if not fields:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": REVIEW_VERSION, "fields": {p: fields[p] for p in sorted(fields)}}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def upsert_review(files: ArticleFiles, path: str, entry: dict) -> dict:
    """Insert/replace the entry for ``(path, entry['author'])``."""
    key = canonical_review_path(path)
    fields = read_reviews(files)
    entries = [e for e in fields.get(key, []) if e.get("author") != entry.get("author")]
    entries.append(entry)
    fields[key] = entries
    write_reviews(files, fields)
    return entry


def delete_reviews_at(files: ArticleFiles, path: str) -> None:
    """Remove every author's review at ``path`` (clearing is not attributable)."""
    fields = read_reviews(files)
    fields.pop(canonical_review_path(path), None)
    write_reviews(files, fields)


def migrate_legacy_reviews(files: ArticleFiles) -> bool:
    """One-time reviews.jsonl -> review.json migration. See Task 2."""
    return False
