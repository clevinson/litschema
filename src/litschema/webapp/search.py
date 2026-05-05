"""Utility functions for the verification webapp."""

from __future__ import annotations

import re

# Section names that indicate primary content vs. references
_PRIMARY_SECTIONS = re.compile(
    r"^(?:#+\s*|\*\*)(?:method|material|result|experiment|setup|site|field|design|treatment)",
    re.IGNORECASE | re.MULTILINE,
)
_REFERENCE_SECTIONS = re.compile(
    r"^(?:#+\s*|\*\*)?\s*(?:references?|bibliography|acknowledg|supplementa|appendix)\s*\**\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def strip_references(text: str) -> str:
    """Remove References/Bibliography/Acknowledgements sections from markdown.

    Finds the first references-like heading and truncates everything after it,
    unless a primary content section (Methods, Results, etc.) appears later.
    """
    lines = text.split("\n")
    cut_from = None
    for i, line in enumerate(lines):
        if _REFERENCE_SECTIONS.match(line):
            cut_from = i
        elif cut_from is not None and _PRIMARY_SECTIONS.match(line):
            cut_from = None

    if cut_from is not None:
        return "\n".join(lines[:cut_from])
    return text
