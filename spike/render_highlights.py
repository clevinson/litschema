"""Spike: render a PDF page with source highlights drawn on it.

Proves the located rectangles land on the right text. In the real feature the
client would render the PDF (PDF.js) and overlay these rectangles as HTML; here
we burn them into a PNG so the result can be eyeballed without a browser.

Run: uv run python spike/render_highlights.py <project-dir> <article-id> [out.png]
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pymupdf

from locate_sources import cited_lines, locate  # noqa: E402
import json

HIGHLIGHT = (1.0, 0.85, 0.2)  # amber, like a marker pen


def render(project: Path, article_id: str, out: Path) -> None:
    base = project / "data" / "papers" / article_id
    md = (base / "article.md").read_text().splitlines()
    doc = pymupdf.open(base / f"{article_id}.pdf")
    words_by_page = {p: doc[p].get_text("words") for p in range(doc.page_count)}
    run_id = json.loads((base / "active-run.json").read_text())["run_id"]
    reasoning = json.loads(
        (base / "extraction-runs" / run_id / "agent-reasoning.json").read_text()
    )

    per_page = defaultdict(list)
    for n in sorted(cited_lines(reasoning, len(md))):
        found = locate(doc, words_by_page, n, md[n - 1] if n - 1 < len(md) else "")
        if found.ok:
            per_page[found.page].append(found)

    if not per_page:
        print("nothing located")
        return
    # The page carrying the most citations is the most informative to look at.
    page_no = max(per_page, key=lambda p: len(per_page[p]))
    page = doc[page_no]
    for found in per_page[page_no]:
        for rect in found.rects:
            annot = page.add_highlight_annot(pymupdf.Rect(rect))
            annot.set_colors(stroke=HIGHLIGHT)
            annot.update()

    page.get_pixmap(dpi=130).save(out)
    lines = sorted(f.line for f in per_page[page_no])
    print(f"page {page_no} of {doc.page_count}: {len(per_page[page_no])} cited lines highlighted")
    print(f"  lines: {lines}")
    print(f"  wrote {out}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("/tmp/highlights.png")
    render(Path(sys.argv[1]), sys.argv[2], out)
