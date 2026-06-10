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

import logging
import re

logger = logging.getLogger(__name__)

#: Fields the convention knows about, in display order.
SOURCE_FIELDS = ("title", "authors", "year", "journal", "doi", "publisher", "url", "abstract")

#: Valid ``metadata_source`` values. ``legacy`` is synthesized at read time
#: for manifests predating the convention; it is never written.
PROVENANCE_VALUES = ("openalex", "crossref", "doi", "filename", "manual", "legacy")

#: Provenance values the verify header renders as editable.
EDITABLE_SOURCES = frozenset({"filename", "manual", "legacy"})

#: Top-level manifest keys older projects wrote before source_metadata.
_LEGACY_KEYS = ("title", "year", "journal", "doi", "publisher", "abstract")


def title_from_filename(stem: str) -> str:
    """Derive a human-readable title from a PDF filename stem.

    Words that already contain capitals (acronyms, CamelCase) are preserved;
    all-lowercase words are capitalized. The result seeds an *editable*
    ``metadata_source: filename`` title — it does not need to be perfect.
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

    Falls back to legacy top-level bibliographic keys (tagged
    ``metadata_source: legacy``) so projects predating the convention keep a
    working verify header. Returns ``{}`` when neither exists.
    """
    block = manifest.get("source_metadata")
    if isinstance(block, dict) and block:
        out = {key: value for key, value in block.items() if value is not None}
        out.setdefault("metadata_source", "manual")
        return out
    legacy = {key: manifest[key] for key in _LEGACY_KEYS if manifest.get(key) is not None}
    if not legacy:
        return {}
    legacy["metadata_source"] = "legacy"
    return legacy
