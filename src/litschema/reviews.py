"""Per-article human-review storage: ``data/papers/<id>/review.json``.

The current verification state IS the file (specs/reviews/spec.md): a map of
canonical field path -> a single review entry, at most ONE review per field.
Any save replaces whatever entry is at the path, regardless of author; the
``author`` key is recorded on the entry so git diffs show "A replacing B's
review" — multi-reviewer coordination happens in PR diffs of review.json
(specs/reviews/decisions.md, 2026-06-11). Entries use ``{author, signal:
verified|flagged, timestamp, base_extraction_sha256?}`` (+ optional
``override_value``/``note``/``source``/``batch_id``).
The webapp API keeps its historical field names (status/reviewer/
correct_value) and maps at the endpoint boundary — see ``webapp/app.py``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging

from .articles import ArticleFiles

logger = logging.getLogger(__name__)

REVIEW_VERSION = 1


class ReviewFileUnreadableError(Exception):
    """review.json exists but cannot be parsed.

    Read paths treat the file as empty and leave it in place; write paths
    raise this instead of destroying what a human needs to inspect.
    """


def canonical_review_path(path: str) -> str:
    """Normalize a review path: strip the leading dot the frontend prefixes.

    Canonical form is ``experiments[0].ph`` — bracket indices, no leading
    dot — exactly what the extraction leaf-path walkers on both sides
    produce. Nothing else is rewritten.
    """
    return path.lstrip(".")


def base_extraction_sha256(files: ArticleFiles) -> str | None:
    """SHA-256 of the article's agent-extraction.json bytes, or None if absent."""
    path = files.extraction
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def base_extraction_stale(files: ArticleFiles) -> bool:
    """True when ANY entry was written against a different agent-extraction.json.

    Each entry stamps the extraction it reviewed (specs/reviews/spec.md
    § Staleness); if that base has changed since, field paths may silently
    misattach. Per-entry stamps mean a fresh save after re-extraction never
    disarms the warning for older entries — it clears only when every stale
    entry has been re-reviewed or removed. No stamp, no review file, or no
    extraction file all mean "not stale" — nothing to misattach against.
    """
    current = base_extraction_sha256(files)
    if current is None:
        return False
    try:
        fields = read_reviews(files)
    except ReviewFileUnreadableError:  # pragma: no cover - lenient read never raises
        return False
    return any(
        entry.get("base_extraction_sha256") not in (None, current) for entry in fields.values()
    )


def read_reviews(files: ArticleFiles, *, strict: bool = False) -> dict[str, dict]:
    """Return the ``fields`` map (canonical path -> entry).

    Keys are canonicalized on the way out, so hand-edited files with dotted
    paths still round-trip through upsert/delete. An unreadable file reads as
    empty and is left in place — unless ``strict``, which raises
    :class:`ReviewFileUnreadableError` so write paths never build on (and
    then destroy) a corrupt file.

    Non-dict entry values (e.g. the pre-2026-06-11 list-of-entries shape) are
    ignored — old-shape files are throwaway alpha data, not migrated.
    """
    path = files.reviews
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_bytes())
    except ValueError as exc:  # JSONDecodeError and UnicodeDecodeError
        if strict:
            raise ReviewFileUnreadableError(
                f"review.json for {files.article_id} is unreadable — "
                "fix or remove it by hand"
            ) from exc
        logger.warning("Unreadable review.json (leaving in place): %s", path)
        return {}
    fields = data.get("fields") if isinstance(data, dict) else None
    if not isinstance(fields, dict):
        if strict:
            raise ReviewFileUnreadableError(
                f"review.json for {files.article_id} has no usable fields map — "
                "fix or remove it by hand"
            )
        return {}
    return {
        canonical_review_path(p): entry for p, entry in fields.items() if isinstance(entry, dict)
    }


def write_reviews(files: ArticleFiles, fields: dict[str, dict]) -> None:
    """Atomically replace review.json; remove it entirely when empty."""
    path = files.reviews
    fields = {p: entry for p, entry in fields.items() if entry}
    if not fields:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {"version": REVIEW_VERSION}
    payload["fields"] = {p: fields[p] for p in sorted(fields)}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def upsert_review(files: ArticleFiles, path: str, entry: dict) -> dict:
    """Set THE entry at ``path``, replacing any existing one regardless of author.

    The entry is stamped with the hash of the agent-extraction.json it was
    written against (omitted when no extraction exists); older entries keep
    their own stamps, so a save never disarms staleness for the rest of the
    file. Raises :class:`ReviewFileUnreadableError` on a corrupt review.json.
    """
    key = canonical_review_path(path)
    fields = read_reviews(files, strict=True)
    digest = base_extraction_sha256(files)
    if digest is not None:
        entry = {**entry, "base_extraction_sha256": digest}
    fields[key] = entry
    write_reviews(files, fields)
    return entry


def delete_reviews_at(files: ArticleFiles, path: str) -> None:
    """Remove THE review at ``path``, whoever wrote it.

    Raises :class:`ReviewFileUnreadableError` on a corrupt review.json rather
    than deleting a file a human still needs to inspect.
    """
    key = canonical_review_path(path)
    fields = read_reviews(files, strict=True)
    fields.pop(key, None)
    write_reviews(files, fields)
