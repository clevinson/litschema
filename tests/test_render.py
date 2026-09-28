from __future__ import annotations

import pytest

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


@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>Text",
        '<img src="x" onerror="alert(1)">',
        '<p style="color:red">Text</p>',
        '[link](javascript:alert(1))',
        "<mark>shaded</mark>",
        '<iframe src="https://example.org"></iframe>',
    ],
)
def test_unsafe_markup_is_stripped(payload) -> None:
    html = "".join(b.get("html", "") for b in render_blocks(payload + "\n")["blocks"])

    for needle in ("<script", "onerror", "style=", 'href="javascript:', "<mark", "<iframe", "<img"):
        assert needle not in html


def test_scientific_inline_markup_survives() -> None:
    html = render_blocks("CO<sub>2</sub> at 10<sup>3</sup><br>next\n")["blocks"][0]["html"]

    assert "<sub>2</sub>" in html
    assert "<sup>3</sup>" in html
    assert "<br" in html


def test_links_keep_http_and_gain_noopener() -> None:
    html = render_blocks("[DOI](https://doi.org/10.1/x)\n")["blocks"][0]["html"]

    assert 'href="https://doi.org/10.1/x"' in html
    assert "noopener" in html


def test_image_only_paragraph_becomes_a_figure_with_its_caption() -> None:
    text = "_Table 3: Year 1 deltas._\n\n![](figures/paper.pdf-0026-03.png)\n\nAfter.\n"

    blocks = render_blocks(text)["blocks"]

    assert blocks[0] == {
        "kind": "figure",
        "lines": [3, 3],
        "src": "paper.pdf-0026-03.png",
        "caption_lines": [1, 1],
        "caption_html": "<p><em>Table 3: Year 1 deltas.</em></p>",
    }
    assert blocks[1]["kind"] == "paragraph"


def test_figure_without_caption_has_no_caption_fields() -> None:
    blocks = render_blocks("Plain text.\n\n![](figures/a.png)\n")["blocks"]

    assert blocks[1] == {"kind": "figure", "lines": [3, 3], "src": "a.png"}


def test_figure_src_drops_any_directory_part() -> None:
    blocks = render_blocks("![](../../etc/passwd.png)\n")["blocks"]

    assert blocks[0]["src"] == "passwd.png"
