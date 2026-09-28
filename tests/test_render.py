from __future__ import annotations

from litschema.webapp.render import render_blocks

DOC = """# Title

First paragraph.

Second paragraph
continues here.

| A | B |
|---|---|
| 1 | 2 |
| 3 | 4 |
"""


def _kinds(result):
    return [(b["kind"], b["lines"]) for b in result["blocks"]]


def test_blocks_carry_one_based_inclusive_line_ranges() -> None:
    result = render_blocks(DOC)

    assert _kinds(result) == [
        ("heading", [1, 1]),
        ("paragraph", [3, 3]),
        ("paragraph", [5, 6]),
        ("table", [8, 11]),
    ]


def test_every_table_row_carries_its_source_line() -> None:
    table = render_blocks(DOC)["blocks"][-1]

    assert '<tr data-line="8">' in table["html"]
    assert '<tr data-line="10">' in table["html"]
    assert '<tr data-line="11">' in table["html"]


def test_result_names_the_text_it_rendered() -> None:
    import hashlib

    result = render_blocks(DOC)

    assert result["text_sha256"] == hashlib.sha256(DOC.encode()).hexdigest()


def test_comment_only_blocks_are_dropped() -> None:
    result = render_blocks("<!-- Start of picture text -->\n\nText.\n")

    assert _kinds(result) == [("paragraph", [3, 3])]
