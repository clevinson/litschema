"""Shared test fixtures for the run-shaped article store."""

from __future__ import annotations

import json
from pathlib import Path

from litschema.runs import is_error_marker

TEST_RUN_ID = "01TESTRUN0000000000000000A"


def _try_json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None


def _project_schema_hash(article_dir: Path) -> str:
    """The real hash of the schema this article's project is configured with.

    Computed through the product's own `schema_hash`, not a local reimplementation
    — recording a placeholder (or a differently-derived digest) makes every
    fixture look like a run extracted against some other schema, which is
    exactly the state the verifier now refuses to interpret.
    """
    from litschema.config import load_config
    from litschema.schema_resolution import _schema_closure, schema_hash

    for candidate in [article_dir, *article_dir.parents]:
        config = candidate / "litschema.yaml"
        if config.is_file():
            try:
                return schema_hash(load_config(config, reload=True))
            except Exception:
                break
        # Many tests build LitSchemaConfig in memory and never write
        # litschema.yaml, but they do create the conventional layout.
        default = candidate / "schema" / "extraction.yaml"
        if default.is_file():
            import hashlib

            digest = hashlib.sha256()
            for path in _schema_closure(default):
                digest.update(path.name.encode())
                digest.update(b"\0")
                digest.update(path.read_bytes())
            return "sha256:" + digest.hexdigest()
    return "sha256:test"


def publish_test_run(
    article_dir: Path,
    extraction: dict | str,
    *,
    reasoning: dict | str | None = None,
    run_id: str = TEST_RUN_ID,
    schema_hash: str | None = None,
    activate: bool = True,
) -> Path:
    """Materialize a published run (and active pointer) for a test article.

    A non-error run gets a reasoning file by default, because `publish_run`
    refuses to publish one without it — a fixture that omits it builds a run
    shape the product cannot actually produce, and then tests pass against a
    state no user can reach.

    ``schema_hash`` defaults to the project's real schema hash for the same
    reason; pass one explicitly to model a run extracted against a schema that
    has since changed.
    """
    if schema_hash is None:
        schema_hash = _project_schema_hash(article_dir)
    run_dir = article_dir / "extraction-runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = extraction if isinstance(extraction, str) else json.dumps(extraction)
    (run_dir / "agent-extraction.json").write_text(payload)

    if reasoning is None:
        parsed = extraction if isinstance(extraction, dict) else _try_json(extraction)
        if not is_error_marker(parsed):
            reasoning = {"fields": []}
    if reasoning is not None:
        payload = reasoning if isinstance(reasoning, str) else json.dumps(reasoning)
        (run_dir / "agent-reasoning.json").write_text(payload)
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "version": 1,
                "run_id": run_id,
                "article_id": article_dir.name,
                "created_at": "2026-01-01T00:00:00+00:00",
                "schema_hash": schema_hash,
                "inputs": {
                    "prepared_text": "sha256:test",
                    "domain_context": "sha256:test",
                    "skill": "sha256:test",
                },
                "agent": {},
            }
        )
        + "\n"
    )
    if activate:
        (article_dir / "active-run.json").write_text(json.dumps({"run_id": run_id}) + "\n")
    return run_dir


def _png(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    import pymupdf

    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), False)
    pix.set_rect(pix.irect, color)
    for x in range(0, width, 7):
        pix.set_pixel(x, x % height, (0, 0, 0))
    return pix.tobytes("png")


def make_pdf(path: Path, *, title: str = "Soil carbon study") -> Path:
    """A three-page PDF: body text, a ruled table, a shaded (highlight-flagged)
    value, a logo on every page, one small icon, and one large figure."""
    import pymupdf

    logo = _png(300, 200, (200, 30, 30))
    icon = _png(40, 40, (30, 200, 30))
    figure = _png(600, 400, (30, 30, 200))
    body = "Soil samples were collected and analysed for inorganic carbon. " * 6
    doc = pymupdf.open()
    for number in range(1, 4):
        page = doc.new_page()
        page.insert_text((72, 72), f"{title}, page {number}", fontsize=11)
        page.insert_textbox(pymupdf.Rect(72, 100, 540, 250), body, fontsize=10)
        page.insert_image(pymupdf.Rect(400, 700, 550, 800), stream=logo)
        page.insert_text((280, 825), f"Running footer {number}", fontsize=8)
        if number == 1:
            page.insert_image(pymupdf.Rect(72, 300, 92, 320), stream=icon)
            page.insert_image(pymupdf.Rect(72, 400, 372, 600), stream=figure)
        if number == 2:
            rows = [("Site", "pH", "SIC"), ("A", "7.1", "0.4"), ("B", "6.8", "0.2")]
            for r, row in enumerate(rows):
                for c, cell in enumerate(row):
                    rect = pymupdf.Rect(72 + c * 100, 320 + r * 20, 172 + c * 100, 340 + r * 20)
                    page.draw_rect(rect, color=(0, 0, 0), width=0.5)
                    page.insert_text((rect.x0 + 4, rect.y0 + 14), cell, fontsize=10)
            page.insert_text((72, 273), "Shaded field value 42", fontsize=10)
            page.draw_rect(
                pymupdf.Rect(70, 262, 200, 276), color=None, fill=(1, 1, 0), fill_opacity=0.4
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path
