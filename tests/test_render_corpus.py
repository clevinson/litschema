"""Render every bake-off output and every active run in a project; report per source.

Opt-in: LITSCHEMA_RENDER_CORPUS=<dir>[:<dir>...] where each dir is either a
directory of *.md files or a litschema project root. Run with -s to see the
report, e.g.

  LITSCHEMA_RENDER_CORPUS=../spikes/2026-09-27-converter-bakeoff/outputs/p4l-nohf:../erw-lit \
    uv run pytest tests/test_render_corpus.py -s
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from litschema.webapp.render import render_blocks
from litschema.webapp.search import strip_references

DIRS = [Path(p) for p in os.environ.get("LITSCHEMA_RENDER_CORPUS", "").split(":") if p]
pytestmark = pytest.mark.skipif(not DIRS, reason="set LITSCHEMA_RENDER_CORPUS to run")

_SEPARATOR = re.compile(r"^\|[\s:|-]*\|$")
_CITE = re.compile(r"L(\d+)(?:\s*-\s*L?(\d+))?")


def _sources(root: Path):
    """(label, text, citations) per document; citations only for projects."""
    if (root / "litschema.yaml").is_file():
        for article in sorted((root / "data" / "papers").iterdir()):
            md = article / "article.md"
            pointer = article / "active-run.json"
            if not md.is_file():
                continue
            cites = []
            if pointer.is_file():
                run = json.loads(pointer.read_text())["run_id"]
                reasoning = article / "extraction-runs" / run / "agent-reasoning.json"
                if reasoning.is_file():
                    for entry in json.loads(reasoning.read_text()).get("fields", []):
                        for m in _CITE.finditer(str(entry.get("source_lines") or "")):
                            cites.append((int(m.group(1)), int(m.group(2) or m.group(1))))
            yield article.name, md.read_text(), cites
    else:
        for md in sorted(root.glob("*.md")):
            yield md.stem, md.read_text(), []


def _covered(blocks) -> set[int]:
    out: set[int] = set()
    for b in blocks:
        out.update(range(b["lines"][0], b["lines"][1] + 1))
        if "caption_lines" in b:
            out.update(range(b["caption_lines"][0], b["caption_lines"][1] + 1))
    return out


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "n/a"


@pytest.mark.parametrize("root", DIRS, ids=[d.name for d in DIRS])
def test_corpus(root) -> None:
    lines_total = lines_hit = rows_total = rows_hit = fences = 0
    cites_total = cites_hit = 0
    misses: list[str] = []
    for label, raw, cites in _sources(root):
        text = strip_references(raw)
        lines = text.split("\n")
        blocks = render_blocks(text)["blocks"]
        covered = _covered(blocks)
        html = "".join(b.get("html", "") for b in blocks)

        for i, line in enumerate(lines, start=1):
            s = line.strip()
            if not s or s.startswith("<!--"):
                continue
            lines_total += 1
            lines_hit += i in covered
            if s.startswith("|") and not _SEPARATOR.match(s):
                rows_total += 1
                rows_hit += f'<tr data-line="{i}">' in html
        fences += sum(
            1
            for b in blocks
            if b["kind"] == "paragraph" and b["html"].removeprefix("<p>").lstrip().startswith("|")
        )
        for start, end in cites:
            visible = [n for n in range(start, end + 1) if n <= len(lines) and lines[n - 1].strip()]
            if not visible:
                continue  # blank or stripped lines: not highlightable in Raw lines either
            cites_total += 1
            if any(n in covered for n in visible):
                cites_hit += 1
            else:
                misses.append(f"{label} L{start}-L{end}")

    print(
        f"\n{root.name}: lines {_pct(lines_hit, lines_total)} | "
        f"table rows {rows_hit}/{rows_total} ({_pct(rows_hit, rows_total)}) | "
        f"literal-pipe paragraphs {fences} | "
        f"citation parity {cites_hit}/{cites_total} ({_pct(cites_hit, cites_total)})"
    )
    for miss in misses[:20]:
        print("  miss:", miss)
    assert lines_hit == lines_total
    assert cites_hit == cites_total, f"{len(misses)} citations not highlightable"
