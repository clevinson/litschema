"""Spike: locate a reasoning citation's markdown line inside the source PDF.

Not wired into the app. This measures whether the `source_lines` an extraction
agent records against `article.md` can be mapped back to rectangles on the PDF
page, which is the load-bearing question for rendering the PDF with highlights
instead of the markdown (kata b85y).

Strategy, in order of preference per line:

1. Exact phrase search. Fast and unambiguous when the markdown line survived
   conversion intact — most body prose.
2. Token-set match against the page's words, then take the rectangles of the
   matched words. Handles reflow, hyphenation, and table rows, where the
   markdown carries `|` and `<br>` structure that exists nowhere in the PDF.

Both produce (page, [rect]) which a renderer can overlay directly.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pymupdf

# Markdown decorations that never appear as PDF text.
_MARKUP = re.compile(r"<br\s*/?>|[*_`#>|]")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-+/%]*")

# Words that carry no locating power. Matching them highlights half the page:
# a citation is identified by its rare words, not by "the" appearing somewhere.
_STOPWORDS = frozenset("""
a an and are as at be by for from had has have in into is it its of on or that
the to was were with which this these those we our their they not but than
""".split())


@dataclass
class Located:
    line: int
    page: int | None
    rects: list[tuple[float, float, float, float]]
    method: str
    score: float

    @property
    def ok(self) -> bool:
        return self.page is not None and self.score >= 0.8


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", _MARKUP.sub(" ", text)).strip()


def tokens(text: str) -> set[str]:
    return {
        t for t in _TOKEN.findall(clean(text))
        if len(t) > 1 and t.lower() not in _STOPWORDS
    }


def densest_band(words, want: set[str], slack: float = 26.0):
    """The tightest vertical run of matching words, plus everything inside it.

    Highlighting each matching word wherever it lands scatters marks across the
    page and reads as noise. A citation occupies one contiguous passage, so
    take the densest vertical run of matches and highlight that region whole —
    including the words between matches, which is what a marker pen does.
    """
    hits = sorted((w for w in words if w[4] in want), key=lambda w: (w[1], w[0]))
    if not hits:
        return []
    # Split matches wherever a vertical gap exceeds a couple of line heights.
    groups, current = [], [hits[0]]
    for prev, nxt in zip(hits, hits[1:], strict=False):
        if nxt[1] - prev[1] > slack:
            groups.append(current)
            current = []
        current.append(nxt)
    groups.append(current)
    best = max(groups, key=len)
    top, bottom = min(w[1] for w in best), max(w[3] for w in best)
    # Everything on those lines, so the highlight is a passage not a stipple.
    inside = [w for w in words if w[1] >= top - 1 and w[3] <= bottom + 1]
    by_line = {}
    for w in inside:
        key = round(w[1] / 3)
        r = by_line.get(key)
        by_line[key] = (
            (min(r[0], w[0]), min(r[1], w[1]), max(r[2], w[2]), max(r[3], w[3]))
            if r else (w[0], w[1], w[2], w[3])
        )
    return list(by_line.values())


def locate(doc, words_by_page, line_no: int, text: str) -> Located:
    """Find where a markdown line's content sits in the PDF."""
    phrase = clean(text)
    if len(phrase) < 12:
        # Too short to identify anything: a separator row, a stray number, or
        # the blank lines that reasoning artifacts cite surprisingly often.
        return Located(line_no, None, [], "too-short", 0.0)

    # 1. Exact phrase, longest prefix that lands on exactly one page.
    for length in (120, 80, 50, 30):
        probe = phrase[:length]
        if len(probe) < 12:
            break
        pages = {p: doc[p].search_for(probe) for p in range(doc.page_count)}
        pages = {p: r for p, r in pages.items() if r}
        if len(pages) == 1:
            page, rects = next(iter(pages.items()))
            return Located(line_no, page, [tuple(r) for r in rects], "phrase", 1.0)

    # 2. Token overlap, then the rectangles of the words that matched.
    want = tokens(text)
    if not want:
        return Located(line_no, None, [], "no-tokens", 0.0)
    best_page, best_score = None, 0.0
    for page, words in words_by_page.items():
        score = len(want & {w[4] for w in words}) / len(want)
        if score > best_score:
            best_page, best_score = page, score
    if best_page is None:
        return Located(line_no, None, [], "tokens", 0.0)
    rects = densest_band(words_by_page[best_page], want)
    return Located(line_no, best_page, rects, "tokens", round(best_score, 2))


def cited_lines(reasoning: dict, max_line: int) -> dict[int, list[str]]:
    """Markdown line -> the field paths citing it."""
    out: dict[int, list[str]] = {}
    for entry in reasoning.get("fields", []):
        for lo, hi in re.findall(r"L(\d+)(?:-L?(\d+))?", entry.get("source_lines", "")):
            start, end = int(lo), int(hi) if hi else int(lo)
            for n in range(start, min(end, max_line) + 1):
                out.setdefault(n, []).append(entry.get("path", "?"))
    return out


def run(project: Path, article_id: str) -> dict:
    base = project / "data" / "papers" / article_id
    md = (base / "article.md").read_text().splitlines()
    doc = pymupdf.open(base / f"{article_id}.pdf")
    words_by_page = {p: doc[p].get_text("words") for p in range(doc.page_count)}
    run_id = json.loads((base / "active-run.json").read_text())["run_id"]
    reasoning = json.loads(
        (base / "extraction-runs" / run_id / "agent-reasoning.json").read_text()
    )

    results = [
        locate(doc, words_by_page, n, md[n - 1] if n - 1 < len(md) else "")
        for n in sorted(cited_lines(reasoning, len(md)))
    ]
    by_method: dict[str, int] = {}
    for r in results:
        by_method[r.method] = by_method.get(r.method, 0) + 1
    return {
        "article_id": article_id,
        "pages": doc.page_count,
        "cited_lines": len(results),
        "located": sum(1 for r in results if r.ok),
        "by_method": by_method,
        "highlights": [
            {"line": r.line, "page": r.page, "rects": r.rects, "method": r.method}
            for r in results
            if r.ok
        ],
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    out = run(Path(sys.argv[1]), sys.argv[2])
    hl = out.pop("highlights")
    print(json.dumps(out, indent=2))
    print(f"\nfirst highlights ({len(hl)} total):")
    for h in hl[:5]:
        print(f"  L{h['line']:<4} page {h['page']}  {len(h['rects'])} rect(s)  via {h['method']}")
