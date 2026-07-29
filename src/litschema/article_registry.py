"""DOI helpers: canonical normalization and syntax validation.

Historical note: this module once held the ``data/sources/articles.csv``
registry machinery, retired when harvest became manifest-driven (see
``specs/bib-metadata/decisions.md``). Only the DOI helpers survive.
"""

from __future__ import annotations

import re

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


def normalize_doi(doi: str) -> str:
    """Return the canonical DOI string used for comparisons and fetches."""
    doi = doi.strip().removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    return doi.rstrip(".,;)")


def is_valid_doi(doi: str) -> bool:
    return bool(DOI_RE.match(normalize_doi(doi)))
