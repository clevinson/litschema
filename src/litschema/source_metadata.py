"""The framework-owned source-metadata convention.

``article-metadata.json`` carries a ``source_metadata`` block describing what
the document *is* (title, authors, venue, ...) — distinct from identity fields
(written by assemble) and from the domain extraction (what the document
*says*). The block is provenance-tagged: ``metadata_source`` records where the
fields came from, and the verify header keys its render mode off that value
per-article. There is intentionally no LinkML schema here — this is a small,
fixed manifest convention (design doc §3.5, option B).
"""

from __future__ import annotations

import re

from .articles import ArticleFiles, write_article_metadata

#: Fields the convention knows about, in display order.
SOURCE_FIELDS = (
    "title",
    "authors",
    "corporate_author",
    "year",
    "journal",
    "doi",
    "publisher",
    "url",
    "abstract",
)

#: Valid ``metadata_source`` values — the 3-state lock model. ``doi``: fetched
#: from the DOI registries; the verify header renders it LOCKED (verified pill,
#: unlock affordance). ``auto``: machine-seeded (filename prettify, agent
#: title-page read) — editable, and batch harvest may enrich it. ``manual``: a
#: human touched it — editable, and machines never overwrite it without
#: explicit consent (per-article sync). Editable is derived: ``!= "doi"``.
PROVENANCE_VALUES = ("doi", "auto", "manual")


def title_from_filename(stem: str) -> str:
    """Derive a human-readable title from a PDF filename stem.

    Words that already contain capitals (acronyms, CamelCase) are preserved;
    all-lowercase words are capitalized. The result seeds an *editable*
    ``metadata_source: auto`` title — it does not need to be perfect.
    """
    text = re.sub(r"[-_]+", " ", stem)
    text = re.sub(r"\s+", " ", text).strip()
    words = [
        word if any(ch.isupper() for ch in word) else word.capitalize()
        for word in text.split(" ")
        if word
    ]
    return " ".join(words)


def read_source_metadata(manifest: dict) -> dict:
    """Return the provenance-tagged source-metadata block of a manifest.

    Bibliographic fields live only in the ``source_metadata`` block — top-level
    manifest keys are identity, never bibliography. Returns ``{}`` when the
    block is absent.
    """
    block = manifest.get("source_metadata")
    if not isinstance(block, dict) or not block:
        return {}
    out = {key: value for key, value in block.items() if value is not None}
    out.setdefault("metadata_source", "manual")
    return out


def update_source_metadata(files: ArticleFiles, fields: dict, *, source: str) -> dict:
    """Merge ``fields`` into the article's source_metadata block and persist.

    Only ``SOURCE_FIELDS`` keys are accepted; a ``None`` value deletes the
    field. Existing block keys not named in ``fields`` are preserved.
    ``metadata_source`` is set to ``source``. Returns the new block.
    """
    if source not in PROVENANCE_VALUES:
        raise ValueError(f"unknown metadata_source: {source!r}")
    block = read_source_metadata(files.read_metadata())
    for key, value in fields.items():
        if key not in SOURCE_FIELDS:
            continue
        if value is None:
            block.pop(key, None)
        else:
            block[key] = value
    block["metadata_source"] = source
    write_article_metadata(files, {"source_metadata": block})
    return block
