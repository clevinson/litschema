"""Per-article human-review storage: ``data/papers/<id>/review.json``.

The current verification state IS the file (design doc §4, option B): a map of
canonical field path -> a single review entry, at most ONE review per field.
Any save replaces whatever entry is at the path, regardless of author; the
``author`` key is recorded on the entry so git diffs show "A replacing B's
review" — multi-reviewer coordination happens in PR diffs of review.json
(decision 2026-06-11). Entries use ``{author, signal: verified|flagged,
override_value?, timestamp}`` (+ optional ``note``/``source``/``batch_id``).
The webapp API keeps its historical field names (status/reviewer/
correct_value) and maps at the endpoint boundary — see ``webapp/app.py``.
"""

from __future__ import annotations

import contextlib
import hashlib
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


def base_extraction_sha256(files: ArticleFiles) -> str | None:
    """SHA-256 of the article's agent-extraction.json bytes, or None if absent."""
    path = files.extraction
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def base_extraction_stale(files: ArticleFiles) -> bool:
    """True when review.json carries a base-extraction stamp that no longer matches.

    Staleness guard (kata 3698): reviews are written against a specific
    agent-extraction.json; if that base has changed since, field paths may
    silently misattach. No stamp, no review file, or no extraction file all
    mean "not stale" — there is nothing to misattach against.
    """
    path = files.reviews
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return False
    stamp = data.get("base_extraction_sha256") if isinstance(data, dict) else None
    if not stamp:
        return False
    current = base_extraction_sha256(files)
    return current is not None and current != stamp


def read_reviews(files: ArticleFiles) -> dict[str, dict]:
    """Return the ``fields`` map (path -> entry).

    Non-dict entry values (e.g. the pre-2026-06-11 list-of-entries shape) are
    ignored — old-shape files are throwaway alpha data, not migrated.
    """
    path = files.reviews
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        logger.warning("Unreadable review.json (leaving in place): %s", path)
        return {}
    fields = data.get("fields") if isinstance(data, dict) else None
    if not isinstance(fields, dict):
        return {}
    return {p: entry for p, entry in fields.items() if isinstance(entry, dict)}


def write_reviews(files: ArticleFiles, fields: dict[str, dict]) -> None:
    """Atomically replace review.json; remove it entirely when empty.

    Non-empty writes are stamped with ``base_extraction_sha256`` — the hash of
    the agent-extraction.json the reviews were written against — so readers can
    detect a re-extracted base (kata 3698). Omitted when no extraction exists.
    """
    path = files.reviews
    fields = {p: entry for p, entry in fields.items() if entry}
    if not fields:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {"version": REVIEW_VERSION}
    digest = base_extraction_sha256(files)
    if digest is not None:
        payload["base_extraction_sha256"] = digest
    payload["fields"] = {p: fields[p] for p in sorted(fields)}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def upsert_review(files: ArticleFiles, path: str, entry: dict) -> dict:
    """Set THE entry at ``path``, replacing any existing one regardless of author."""
    key = canonical_review_path(path)
    fields = read_reviews(files)
    fields[key] = entry
    write_reviews(files, fields)
    return entry


def delete_reviews_at(files: ArticleFiles, path: str) -> None:
    """Remove THE review at ``path``, whoever wrote it."""
    key = canonical_review_path(path)
    fields = read_reviews(files)
    fields.pop(key, None)
    write_reviews(files, fields)
