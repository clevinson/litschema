"""Run-bound human review: ``extraction-runs/<run-id>/review.json`` (version 2).

A review is a compact overlay on one immutable run (`specs/reviews/spec.md`).
At most one entry per exact path; an entry carries an optional ``override``
(``replace``/``remove``/``add``) and an optional ``note``. An empty object
means verified. Git supplies author and time history, so the stored model
carries neither.

The file is the state: there is no staleness mode, because a review binds to a
run whose payload can never change.
"""

from __future__ import annotations

import contextlib
import json
import logging

from .review_paths import (
    InvalidReviewPathError,
    canonical_review_path,
    format_path,
    is_ancestor,
    leaf_paths,
    nearest_stored_ancestor,
    parse_path,
    path_resolves,
    resolve,
)
from .runs import RunFiles

logger = logging.getLogger(__name__)

REVIEW_VERSION = 2
OVERRIDE_OPS = ("replace", "remove", "add")

VERIFIED = "verified"
OVERRIDDEN = "overridden"
UNREVIEWED = "unreviewed"

LEGACY_KEYS = frozenset(
    {"signal", "author", "base_extraction_sha256", "override_value", "__remove__"}
)


class ReviewCorruptError(Exception):
    """review.json is unreadable, malformed, or names paths that cannot exist.

    Corrupt is never treated as empty: reads surface it, writes refuse rather
    than overwriting a file a human still needs to inspect.
    """


class ReviewContractError(Exception):
    """A proposed review entry violates the review contract."""


def read_reviews(run: RunFiles) -> dict[str, dict]:
    """Return the stored ``fields`` map for this run, or ``{}`` when absent.

    Raises :class:`ReviewCorruptError` for an unreadable file, a bad shape, a
    malformed path, or a legacy version-1 entry. Callers that need to render
    an error rather than fail should catch it.
    """
    path = run.review
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_bytes())
    except ValueError as exc:
        raise ReviewCorruptError(f"{path} is unreadable — fix or remove it by hand") from exc
    if not isinstance(data, dict) or not isinstance(data.get("fields"), dict):
        raise ReviewCorruptError(f"{path} has no usable fields map")
    if data.get("version") != REVIEW_VERSION:
        raise ReviewCorruptError(
            f"{path} is version {data.get('version')!r}, not {REVIEW_VERSION}"
        )

    fields: dict[str, dict] = {}
    for raw_path, entry in data["fields"].items():
        if not isinstance(entry, dict):
            raise ReviewCorruptError(f"{path}: entry at {raw_path!r} is not an object")
        if LEGACY_KEYS & set(entry):
            raise ReviewCorruptError(
                f"{path}: entry at {raw_path!r} uses version-1 keys, invalid in version 2"
            )
        try:
            key = canonical_review_path(raw_path)
        except InvalidReviewPathError as exc:
            raise ReviewCorruptError(f"{path}: {exc}") from exc
        if key in fields:
            raise ReviewCorruptError(f"{path}: duplicate entry for {key!r}")
        _validate_entry_shape(key, entry, source=str(path))
        fields[key] = entry
    return fields


def _validate_entry_shape(key: str, entry: dict, *, source: str) -> None:
    unknown = set(entry) - {"override", "note"}
    if unknown:
        raise ReviewCorruptError(f"{source}: entry at {key!r} has unknown keys {sorted(unknown)}")
    override = entry.get("override")
    if override is None:
        return
    if not isinstance(override, dict) or override.get("op") not in OVERRIDE_OPS:
        raise ReviewCorruptError(f"{source}: entry at {key!r} has an invalid override")
    if override["op"] == "remove":
        if "value" in override:
            raise ReviewCorruptError(f"{source}: remove override at {key!r} carries a value")
    elif "value" not in override or override["value"] is None:
        raise ReviewCorruptError(
            f"{source}: {override['op']} override at {key!r} needs a non-null value"
        )


def write_reviews(run: RunFiles, fields: dict[str, dict]) -> None:
    """Atomically replace review.json, removing it when no entries remain."""
    path = run.review
    if not fields:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": REVIEW_VERSION, "fields": {k: fields[k] for k in sorted(fields)}}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n")
    tmp.replace(path)


# ── effective state ──────────────────────────────────────────────────────────


def controlling_entry(path: str, fields: dict[str, dict]) -> tuple[str | None, dict | None]:
    """The entry governing ``path``: the exact one, else the nearest ancestor."""
    if path in fields:
        return path, fields[path]
    ancestor = nearest_stored_ancestor(path, fields)
    if ancestor is None:
        return None, None
    return ancestor, fields[ancestor]


def effective_state(path: str, fields: dict[str, dict]) -> str:
    """verified / overridden / unreviewed for ``path``."""
    _, entry = controlling_entry(path, fields)
    if entry is None:
        return UNREVIEWED
    return OVERRIDDEN if entry.get("override") else VERIFIED


def terminal_override_ancestor(path: str, fields: dict[str, dict]) -> str | None:
    """An ancestor whose override makes entries beneath ``path`` invalid."""
    for candidate, entry in fields.items():
        if is_ancestor(candidate, path) and entry.get("override"):
            return candidate
    return None


# ── canonicalization ─────────────────────────────────────────────────────────


def _is_redundant(path: str, fields: dict[str, dict]) -> bool:
    """Exactly the spec's rule: bare verification under bare verification."""
    entry = fields[path]
    if entry.get("override") or entry.get("note"):
        return False
    ancestor = nearest_stored_ancestor(path, fields)
    if ancestor is None:
        return False
    return not fields[ancestor].get("override")


def canonicalize(fields: dict[str, dict]) -> dict[str, dict]:
    """Drop redundant empty verifications; never synthesize a parent."""
    kept = dict(fields)
    for path in sorted(fields, key=lambda p: len(parse_path(p))):
        if path in kept and _is_redundant(path, kept):
            del kept[path]
    return kept


# ── writes ───────────────────────────────────────────────────────────────────


def _typed_entry(entry: dict, key: str, schema) -> dict:
    """Coerce a replace/add value to its slot's declared type."""
    override = entry.get("override")
    if schema is None or not override or override.get("op") == "remove":
        return entry
    if "value" not in override:
        return entry
    from .schema_resolution import coerce_to_slot, slot_for_path

    slot = slot_for_path(schema.view, schema.root_class, parse_path(key))
    try:
        coerced = coerce_to_slot(schema.view, slot, override["value"])
    except ValueError as exc:
        raise ReviewContractError(f"{key}: {exc}") from None
    if coerced is override["value"]:
        return entry
    return {**entry, "override": {**override, "value": coerced}}


def _validate_against_run(run: RunFiles, path: str, entry: dict, extraction: dict) -> None:
    override = entry.get("override")
    op = override.get("op") if override else None
    resolves = path_resolves(extraction, path)

    if op == "add":
        if resolves:
            raise ReviewContractError(
                f"{path} already exists in this run — use replace, not add"
            )
        _validate_add_target(extraction, path)
    elif not resolves:
        raise ReviewContractError(f"{path} does not resolve against this run's extraction")

    if op == "remove":
        parts = parse_path(path)
        if not parts:
            raise ReviewContractError("the extraction root cannot be removed")


def _validate_add_target(extraction: dict, path: str) -> None:
    """An add appends one past an array's length, or fills an absent property."""
    parts = parse_path(path)
    if not parts:
        raise ReviewContractError("cannot add at the extraction root")
    parent_parts, last = parts[:-1], parts[-1]
    parent_path = format_path(parent_parts) if parent_parts else None
    try:
        parent = extraction if parent_path is None else resolve(extraction, parent_path)
    except KeyError:
        raise ReviewContractError(f"the parent of {path} does not resolve") from None

    if isinstance(last, int):
        if not isinstance(parent, list):
            raise ReviewContractError(f"{path} indexes something that is not an array")
        if last != len(parent):
            raise ReviewContractError(
                f"{path} must append one past the end of the array (index {len(parent)})"
            )
    else:
        if not isinstance(parent, dict):
            raise ReviewContractError(f"the parent of {path} is not an object")


def upsert_review(
    run: RunFiles,
    path: str,
    entry: dict,
    *,
    schema: object | None = None,
) -> dict[str, dict]:
    """Set the entry at ``path``, then canonicalize. Returns the stored fields.

    ``schema`` is a resolved extraction schema; when given, a replace/add value
    is coerced to the target slot's declared type and rejected if it cannot be.
    Without it the value is stored as supplied — callers that can resolve the
    schema should pass it, since a browser submits every edit as a string.
    """
    key = canonical_review_path(path)
    fields = read_reviews(run)
    entry = _typed_entry(entry, key, schema)
    _validate_entry_shape(key, entry, source=str(run.review))

    blocked = terminal_override_ancestor(key, fields)
    if blocked is not None:
        raise ReviewContractError(
            f"{blocked} carries a container override, so {key} cannot be reviewed separately"
        )

    extraction = json.loads(run.extraction.read_text())
    _validate_against_run(run, key, entry, extraction)

    fields[key] = entry
    if entry.get("override"):
        # A container override is terminal: anything beneath it is invalid.
        for existing in [p for p in fields if is_ancestor(key, p)]:
            del fields[existing]
    else:
        # Saving parent verification absorbs only redundant descendants.
        for existing in [p for p in fields if is_ancestor(key, p)]:
            if not (fields[existing].get("override") or fields[existing].get("note")):
                del fields[existing]

    fields = canonicalize(fields)
    write_reviews(run, fields)
    return fields


def unreview_subtree(run: RunFiles, path: str, *, discard_note: bool = False) -> dict[str, dict]:
    """Make the whole ``path`` subtree unreviewed, preserving sibling coverage.

    When a verifying ancestor covers ``path``, that ancestor is replaced by
    verification at the highest siblings that do not contain ``path``, so the
    rest of its subtree keeps exactly the coverage it had.
    """
    key = canonical_review_path(path)
    fields = read_reviews(run)

    covering = nearest_stored_ancestor(key, fields)
    if covering is not None:
        entry = fields[covering]
        if entry.get("override"):
            raise ReviewContractError(
                f"{covering} carries a container override; edit or clear it before "
                f"unreviewing {key}"
            )
        if entry.get("note") and not discard_note:
            raise ReviewContractError(
                f"{covering} carries a note that would be discarded — confirm explicitly"
            )

    for existing in [p for p in fields if p == key or is_ancestor(key, p)]:
        del fields[existing]

    if covering is not None:
        del fields[covering]
        extraction = json.loads(run.extraction.read_text())
        for sibling in _sibling_frontier(extraction, covering, key):
            if sibling not in fields and not any(
                is_ancestor(existing, sibling) or existing == sibling for existing in fields
            ):
                fields[sibling] = {}

    fields = canonicalize(fields)
    write_reviews(run, fields)
    return fields


def _sibling_frontier(extraction: dict, ancestor: str, target: str) -> list[str]:
    """Highest nodes under ``ancestor`` that do not contain ``target``.

    Walking down from the covering ancestor toward the target, every sibling
    branching off the way keeps its verification at the highest point that
    still excludes the target. That is the unique minimal frontier.
    """
    from .review_paths import child_paths

    frontier: list[str] = []
    current = ancestor
    target_parts = parse_path(target)
    while current != target:
        for child in child_paths(extraction, current):
            child_parts = parse_path(child)
            contains_target = target_parts[: len(child_parts)] == child_parts
            if not contains_target:
                frontier.append(child)
        # Descend one segment toward the target.
        depth = len(parse_path(current)) + 1
        current = format_path(target_parts[:depth])
    return frontier


# ── read helpers for consumers ───────────────────────────────────────────────


def effective_extraction(run: RunFiles, fields: dict[str, dict] | None = None) -> dict:
    """The run's extraction with review overrides applied.

    Removal of an array element writes a structural ``null`` tombstone rather
    than splicing, so every index a review refers to keeps meaning.
    """
    data = json.loads(run.extraction.read_text())
    fields = read_reviews(run) if fields is None else fields

    for path in sorted(fields, key=lambda p: len(parse_path(p))):
        override = fields[path].get("override")
        if not override:
            continue
        parts = parse_path(path)
        parent = data if len(parts) == 1 else _resolve_parts(data, parts[:-1])
        if parent is None:
            continue
        last = parts[-1]
        if override["op"] == "remove":
            if isinstance(last, int) and isinstance(parent, list) and last < len(parent):
                parent[last] = None
            elif isinstance(parent, dict):
                parent.pop(last, None)
        else:  # replace or add
            if isinstance(last, int) and isinstance(parent, list):
                if last < len(parent):
                    parent[last] = override["value"]
                elif last == len(parent):
                    parent.append(override["value"])
            elif isinstance(parent, dict):
                parent[last] = override["value"]
    return data


def _resolve_parts(data, parts: tuple[str | int, ...]):
    try:
        return resolve(data, format_path(parts))
    except KeyError:
        return None


def review_progress(
    run: RunFiles,
    fields: dict[str, dict] | None = None,
    *,
    exclude: set[str] | None = None,
) -> dict:
    """Counts over the run's leaves plus any leaves an ``add`` contributed.

    ``exclude`` drops paths from the denominator entirely — the verifier passes
    `identifier: true` slots, which are structural identity rather than
    extracted findings and so are not review work.
    """
    fields = read_reviews(run) if fields is None else fields
    extraction = json.loads(run.extraction.read_text())

    skip = exclude or set()
    paths = [p for p in leaf_paths(extraction) if p not in skip]
    for path, entry in fields.items():
        override = entry.get("override")
        if override and override["op"] == "add" and path not in paths and path not in skip:
            paths.append(path)

    verified = overridden = 0
    for path in paths:
        state = effective_state(path, fields)
        if state == VERIFIED:
            verified += 1
        elif state == OVERRIDDEN:
            overridden += 1
    reviewed = verified + overridden
    total = len(paths)
    return {
        "n_fields": total,
        "n_verified": verified,
        "n_overridden": overridden,
        "n_reviewed": reviewed,
        "n_unreviewed": total - reviewed,
        "review_progress": (reviewed / total) if total else 1.0,
        "is_complete": total == reviewed,
    }
