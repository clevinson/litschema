"""Per-article human-review storage: ``data/papers/<id>/review.json``.

The current verification state IS the file (design doc §4, option B): a map of
canonical field path -> review entries, at most one entry per field per
author. Entries use ``{author, signal: verified|flagged, override_value?,
timestamp}`` (+ optional ``note``/``source``/``batch_id``). The webapp API
keeps its historical field names (status/reviewer/correct_value) and maps at
the endpoint boundary — see ``webapp/app.py``.

The append-only ``reviews.jsonl`` predecessor is set aside lazily and
one-time: first read renames the event log to ``reviews.jsonl.bak``
without converting it (pre-review.json logs are throwaway test data).
"""

from __future__ import annotations

import contextlib
import json
import logging
import re

from .articles import ArticleFiles

logger = logging.getLogger(__name__)

REVIEW_VERSION = 1

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


def read_reviews(files: ArticleFiles) -> dict[str, list[dict]]:
    """Return the ``fields`` map. Runs the lazy legacy migration first."""
    migrate_legacy_reviews(files)
    path = files.reviews
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
    path = files.reviews
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
    """Set aside a leftover append-only ``reviews.jsonl``.

    Pre-review.json logs are throwaway test data — they are renamed to
    ``reviews.jsonl.bak`` (not converted) so they can't be mistaken for
    live review state. Never runs once review.json exists.
    """
    legacy = files.reviews_legacy
    if files.reviews.exists() or not legacy.exists():
        return False
    legacy.rename(legacy.with_suffix(".jsonl.bak"))
    logger.info("Set aside legacy review log for %s", files.article_id)
    return True
