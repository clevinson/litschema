"""Canonical review paths: parsing, ancestry, and extraction-tree walking.

A path names one node in an extraction: property segments and bracket indices
with no leading dot, e.g. ``experiments[0].measurements[1].ph``. Every rule in
`specs/reviews/spec.md` — ancestry, redundancy, subtree unreview — is stated in
terms of these paths, so they get their own module rather than living inside
the storage layer.
"""

from __future__ import annotations

import re

_SEGMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")


class InvalidReviewPathError(ValueError):
    """A review path is malformed and names no possible node."""


def parse_path(path: str) -> tuple[str | int, ...]:
    """Split a canonical path into property names and integer indices.

    ``experiments[0].ph`` -> ``("experiments", 0, "ph")``. A leading dot is
    tolerated on input — the verifier historically prefixed one — but never
    produced.
    """
    text = path.strip()
    if text.startswith("."):
        text = text[1:]
    if not text:
        raise InvalidReviewPathError("empty review path")

    parts: list[str | int] = []
    position = 0
    expect_property = True
    while position < len(text):
        if text[position] == ".":
            if expect_property or position + 1 >= len(text):
                raise InvalidReviewPathError(f"malformed review path: {path!r}")
            position += 1
            expect_property = True
            continue
        match = _SEGMENT.match(text, position)
        if match is None:
            raise InvalidReviewPathError(f"malformed review path: {path!r}")
        name, index = match.group(1), match.group(2)
        if name is not None:
            if not expect_property:
                raise InvalidReviewPathError(f"malformed review path: {path!r}")
            parts.append(name)
        else:
            if expect_property:
                raise InvalidReviewPathError(f"malformed review path: {path!r}")
            parts.append(int(index))
        expect_property = False
        position = match.end()
    if expect_property:
        raise InvalidReviewPathError(f"malformed review path: {path!r}")
    return tuple(parts)


def format_path(parts: tuple[str | int, ...]) -> str:
    """Render parsed segments back to canonical form."""
    out = ""
    for part in parts:
        out += f"[{part}]" if isinstance(part, int) else (part if not out else f".{part}")
    return out


def canonical_review_path(path: str) -> str:
    """Normalize a path to canonical form, rejecting malformed input."""
    return format_path(parse_path(path))


def ancestors(path: str) -> list[str]:
    """Proper ancestors of ``path``, nearest last.

    ``experiments[0].ph`` -> ``["experiments", "experiments[0]"]``.
    """
    parts = parse_path(path)
    return [format_path(parts[:i]) for i in range(1, len(parts))]


def is_ancestor(candidate: str, path: str) -> bool:
    """True when ``candidate`` is a proper ancestor of ``path``."""
    a, b = parse_path(candidate), parse_path(path)
    return len(a) < len(b) and b[: len(a)] == a


def nearest_stored_ancestor(path: str, stored: dict) -> str | None:
    """The deepest entry in ``stored`` that is a proper ancestor of ``path``."""
    for candidate in reversed(ancestors(path)):
        if candidate in stored:
            return candidate
    return None


def resolve(data, path: str):
    """Return the value at ``path`` in ``data``.

    Raises :class:`KeyError` when the path does not resolve, which the review
    contract treats as "this path names nothing in this run".
    """
    current = data
    for part in parse_path(path):
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current) or part < 0:
                raise KeyError(path)
            current = current[part]
        else:
            if not isinstance(current, dict) or part not in current:
                raise KeyError(path)
            current = current[part]
    return current


def path_resolves(data, path: str) -> bool:
    try:
        resolve(data, path)
    except (KeyError, InvalidReviewPathError):
        return False
    return True


def child_paths(data, path: str | None) -> list[str]:
    """Immediate child paths of ``path`` (or of the root when None)."""
    node = data if path is None else resolve(data, path)
    prefix = "" if path is None else path
    if isinstance(node, dict):
        return [f"{prefix}.{key}" if prefix else key for key in node]
    if isinstance(node, list):
        return [f"{prefix}[{index}]" for index in range(len(node))]
    return []


def leaf_paths(data, path: str | None = None) -> list[str]:
    """Every scalar leaf path under ``path``, in document order.

    A container with no children is not a leaf: it contributes nothing to
    review coverage, so counting it would inflate progress denominators.
    """
    children = child_paths(data, path)
    if not children:
        return [] if path is None else [path]
    out: list[str] = []
    for child in children:
        out.extend(leaf_paths(data, child))
    return out
