"""The framework-owned bib-metadata convention.

``article-metadata.json`` carries a ``bib_metadata`` block describing what
the document *is* (title, authors, venue, ...) — distinct from identity fields
(written by assemble) and from the domain extraction (what the document
*says*). The block is provenance-tagged: ``bib_source`` records where the
fields came from, and the verify header keys its render mode off that value
per-article. There is intentionally no LinkML schema here — this is a small,
fixed manifest convention (see specs/bib-metadata/spec.md).
"""

from __future__ import annotations

import re

from .articles import ArticleFiles, write_article_metadata

#: Fields the convention knows about, in display order.
BIB_FIELDS = (
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

#: Valid ``bib_source`` values — the 3-state lock model. ``doi``: fetched
#: from the DOI registries; the verify header renders it LOCKED (verified pill,
#: unlock affordance). ``auto``: machine-seeded (filename prettify, agent
#: title-page read) — editable, and batch harvest may enrich it. ``manual``: a
#: human touched it — editable, and machines never overwrite it without
#: explicit consent (per-article sync). Editable is derived: ``!= "doi"``.
PROVENANCE_VALUES = ("doi", "auto", "manual")


def can_overwrite(existing_source: str | None, new_source: str) -> bool:
    """The never-clobber rule, in one place.

    Machine-authored writes (``auto``) may only replace machine-authored or
    absent metadata; human-authored (``manual``) and registry-locked
    (``doi``) blocks require explicit consent (sync, ``--force``).
    ``manual`` writes always win — a human outranks every machine.
    """
    if new_source == "auto":
        return existing_source in (None, "auto")
    return True


def title_from_filename(stem: str) -> str:
    """Derive a human-readable title from a PDF filename stem.

    Words that already contain capitals (acronyms, CamelCase) are preserved;
    all-lowercase words are capitalized. The result seeds an *editable*
    ``bib_source: auto`` title — it does not need to be perfect.
    """
    text = re.sub(r"[-_]+", " ", stem)
    text = re.sub(r"\s+", " ", text).strip()
    words = [
        word if any(ch.isupper() for ch in word) else word.capitalize()
        for word in text.split(" ")
        if word
    ]
    return " ".join(words)


def read_bib_metadata(manifest: dict) -> dict:
    """Return the provenance-tagged bib-metadata block of a manifest.

    Bibliographic fields live only in the ``bib_metadata`` block — top-level
    manifest keys are identity, never bibliography. Returns ``{}`` when the
    block is absent.
    """
    block = manifest.get("bib_metadata")
    if not isinstance(block, dict) or not block:
        return {}
    out = {key: value for key, value in block.items() if value is not None}
    out.setdefault("bib_source", "manual")
    return out


def update_bib_metadata(files: ArticleFiles, fields: dict, *, source: str) -> dict:
    """Merge ``fields`` into the article's bib_metadata block and persist.

    Only ``BIB_FIELDS`` keys are accepted; a ``None`` value deletes the
    field. Existing block keys not named in ``fields`` are preserved.
    ``bib_source`` is set to ``source``. Returns the new block.
    """
    if source not in PROVENANCE_VALUES:
        raise ValueError(f"unknown bib_source: {source!r}")
    block = read_bib_metadata(files.read_metadata())
    for key, value in fields.items():
        if key not in BIB_FIELDS:
            continue
        if value is None:
            block.pop(key, None)
        else:
            block[key] = value
    block["bib_source"] = source
    write_article_metadata(files, {"bib_metadata": block})
    return block
