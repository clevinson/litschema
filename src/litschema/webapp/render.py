"""Render prepared text as sanitized blocks that keep their source lines.

Citations in agent-reasoning.json name lines of article.md. Each block records
the lines it came from, and every table row its own line, so the app can
highlight exactly what a citation names while showing formatted text.
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import PurePosixPath

import nh3
from markdown_it import MarkdownIt
from markdown_it.token import Token

ALLOWED_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "hr",
    "table", "thead", "tbody", "tr", "th", "td",
    "br", "sub", "sup", "em", "strong", "code", "pre",
    "ul", "ol", "li", "blockquote", "a",
}
ALLOWED_ATTRIBUTES = {"tr": {"data-line"}, "a": {"href"}}

# "Table 3:", "_Table 3:", "**Figure 2.**", "Fig. 4" at the start of a paragraph.
_CAPTION = re.compile(r"^[\s_*]*(table|fig(?:ure)?\.?)\s*[A-Z]?\d", re.IGNORECASE)

_md = MarkdownIt("commonmark", {"html": True}).enable("table")


def sanitize(html: str) -> str:
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https"},
        link_rel="noopener noreferrer",
    )


def _top_level(tokens: list[Token]):
    """Group the token stream into top-level blocks (open..close, or one token)."""
    i = 0
    while i < len(tokens):
        if tokens[i].nesting == 1:
            depth, j = 0, i
            while True:
                depth += tokens[j].nesting
                if depth == 0:
                    break
                j += 1
            yield tokens[i : j + 1]
            i = j + 1
        else:
            yield tokens[i : i + 1]
            i += 1


def _figure_src(group: list[Token]) -> str | None:
    """The image file name when a paragraph holds exactly one image."""
    if [t.type for t in group] != ["paragraph_open", "inline", "paragraph_close"]:
        return None
    kids = [
        c for c in (group[1].children or [])
        if not (c.type in ("softbreak", "text") and not c.content.strip())
    ]
    if len(kids) == 1 and kids[0].type == "image":
        return PurePosixPath(str(kids[0].attrGet("src") or "")).name or None
    return None


def render_blocks(text: str) -> dict:
    """Blocks with 1-based inclusive line ranges; see specs/verifier/spec.md."""
    return _render(hashlib.sha256(text.encode()).hexdigest(), text)


@lru_cache(maxsize=64)
def _render(text_sha256: str, text: str) -> dict:
    blocks: list[dict] = []
    for group in _top_level(_md.parse(text)):
        head = group[0]
        if head.map is None:
            continue
        lines = [head.map[0] + 1, head.map[1]]

        src = _figure_src(group)
        if src:
            block = {"kind": "figure", "lines": lines, "src": src}
            prev = blocks[-1] if blocks else None
            if prev and prev["kind"] == "paragraph" and _CAPTION.match(prev.get("_text", "")):
                block["caption_lines"] = prev["lines"]
                block["caption_html"] = prev["html"]
                blocks.pop()
            blocks.append(block)
            continue

        for tok in group:
            if tok.type == "tr_open" and tok.map:
                tok.attrSet("data-line", str(tok.map[0] + 1))
        html = sanitize(_md.renderer.render(group, _md.options, {})).strip()
        if not html:
            continue
        kind = head.type.removesuffix("_open")
        block = {"kind": kind, "lines": lines, "html": html}
        if kind == "paragraph":
            block["_text"] = group[1].content
        blocks.append(block)

    for block in blocks:
        block.pop("_text", None)
    return {"text_sha256": text_sha256, "blocks": blocks}
