"""Extraction verification webapp — FastAPI backend.

Usage:
    uv run litschema verify
    # or, directly:
    uv run python -m litschema.webapp.app
"""

from __future__ import annotations

import json
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..articles import (
    article_files,
    iter_article_ids_with_extractions,
    read_article_metadata,
    read_review_events,
)
from ..config import load_config
from .search import strip_references

_CFG = load_config()
PROJECT_ROOT = _CFG.project_root
CORPUS_PATH = _CFG.corpus_file
PAPERS_DIR = _CFG.papers_dir
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="ERW Extraction Verifier")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Cache corpus on startup
_corpus_cache: dict | None = None
_article_index: dict[str, dict] | None = None
_author_index: dict[str, dict] | None = None


def _load_corpus() -> dict:
    global _corpus_cache, _article_index, _author_index
    if _corpus_cache is None and CORPUS_PATH.exists():
        with open(CORPUS_PATH) as f:
            _corpus_cache = yaml.safe_load(f)
        _article_index = {
            a.get("id"): a for a in (_corpus_cache or {}).get("articles", []) if a.get("id")
        }
        _author_index = {
            a.get("id"): a for a in (_corpus_cache or {}).get("authors", []) if a.get("id")
        }
    return _corpus_cache or {}


def _load_author_index() -> dict[str, dict]:
    _load_corpus()
    if _author_index:
        return _author_index
    authors_path = _CFG.data_dir / "authors.yaml"
    if not authors_path.exists():
        return {}
    authors = yaml.safe_load(authors_path.read_text()) or []
    return {a.get("id"): a for a in authors if a.get("id")}


def _article_meta(article_id: str) -> dict:
    """Return a compact bibliographic dict for an article id."""
    _load_corpus()
    a = read_article_metadata(article_files(_CFG, article_id))
    if not a:
        a = (_article_index or {}).get(article_id)
    if not a:
        return {}
    authors = []
    author_index = _load_author_index()
    for aid in a.get("author_ids") or []:
        auth = author_index.get(aid)
        if auth:
            family = auth.get("family_name") or ""
            given = auth.get("given_name") or ""
            authors.append({"family": family, "given": given})
    return {
        "title": a.get("title"),
        "year": a.get("year"),
        "journal": a.get("journal"),
        "doi": a.get("doi"),
        "publisher": a.get("publisher"),
        "authors": authors,
    }


def _article_pdf_filename(article_id: str) -> str | None:
    """Look up PDF filename from per-article metadata or legacy corpus.yaml."""
    _load_corpus()
    a = read_article_metadata(article_files(_CFG, article_id))
    if not a:
        a = (_article_index or {}).get(article_id)
    if not a:
        return None
    return a.get("filename") or a.get("standard_filename")


def _current_annotations(article_id: str) -> list[dict]:
    """Return latest annotation state per path, hiding JSONL clear events."""
    current: dict[str, dict] = {}
    for event in read_review_events(article_files(_CFG, article_id)):
        path = event.get("path")
        if not path:
            continue
        if event.get("status") == "cleared":
            current.pop(path, None)
        else:
            current[path] = event
    return list(current.values())


@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text()


@app.get("/api/articles")
async def list_articles():
    """List articles that have both markdown and extraction JSON."""
    articles = []
    for article_id in iter_article_ids_with_extractions(_CFG):
        files = article_files(_CFG, article_id)
        ext_path = files.extraction_path()
        md_path = files.markdown_path()
        if not md_path.exists():
            continue

        data = json.loads(ext_path.read_text())
        if data.get("error"):
            continue

        setups = data.get("experimental_setups") or []
        # Annotation progress
        n_annotated = len(_current_annotations(article_id))
        # Look up bibliographic fields from corpus
        bib = _article_meta(article_id)
        articles.append(
            {
                "article_id": article_id,
                "confidence": data.get("confidence"),
                "study_types": data.get("study_types", []),
                "focus_areas": data.get("focus_areas", []),
                "document_type": data.get("document_type"),
                "n_setups": len(setups),
                "n_annotated": n_annotated,
                "doi": bib.get("doi"),
                "title": bib.get("title"),
                "year": bib.get("year"),
                "journal": bib.get("journal"),
                "authors": bib.get("authors", []),
            }
        )

    return {"articles": articles, "total": len(articles)}


@app.get("/api/article/{article_id}")
async def get_article(article_id: str):
    """Return full extraction JSON for an article."""
    path = article_files(_CFG, article_id).extraction_path()
    if not path.exists():
        raise HTTPException(404, f"No extraction for {article_id}")
    return json.loads(path.read_text())


@app.get("/api/bibliography/{article_id}")
async def get_bibliography(article_id: str):
    """Return bibliographic metadata (title, year, journal, authors, doi)."""
    meta = _article_meta(article_id)
    if not meta:
        raise HTTPException(404, f"No bibliographic entry for {article_id}")
    return meta


@app.get("/api/markdown/{article_id}")
async def get_markdown(article_id: str):
    """Return raw markdown text for an article."""
    path = article_files(_CFG, article_id).markdown_path()
    if not path.exists():
        raise HTTPException(404, f"No markdown for {article_id}")
    text = path.read_text()
    return {"markdown": strip_references(text)}


@app.get("/api/pdf/{article_id}")
async def get_pdf(article_id: str):
    """Serve the PDF file for an article."""
    filename = _article_pdf_filename(article_id)
    if not filename:
        raise HTTPException(404, f"No PDF filename found for {article_id}")

    pdf_path = PAPERS_DIR / filename
    if not pdf_path.exists():
        raise HTTPException(404, f"PDF not found: {filename}")

    return FileResponse(pdf_path, media_type="application/pdf")


@app.get("/api/reasoning/{article_id}")
async def get_reasoning(article_id: str):
    """Return per-field extraction reasoning if it exists."""
    path = article_files(_CFG, article_id).reasoning_path()
    if not path.exists():
        raise HTTPException(404, f"No reasoning for {article_id}")
    return json.loads(path.read_text())


@app.get("/api/annotations/{article_id}")
async def get_annotations(article_id: str):
    """Return annotations for an article."""
    return {"article_id": article_id, "annotations": _current_annotations(article_id)}


@app.put("/api/annotations/{article_id}")
async def put_annotation(article_id: str, request: Request):
    """Add or update a field annotation."""
    body = await request.json()
    field_path = body.get("path")
    status = body.get("status")  # verified | flagged
    reviewer = body.get("reviewer", "")
    note = body.get("note")
    correct_value = body.get("correct_value")  # proposed correction or "__remove__" to delete field
    source = body.get("source")
    batch_id = body.get("batch_id")

    if not field_path or not status:
        raise HTTPException(400, "path and status are required")
    if status not in ("verified", "flagged"):
        raise HTTPException(400, "status must be verified or flagged")
    if status == "flagged" and not reviewer:
        raise HTTPException(400, "reviewer ORCID is required for flags")

    entry = {
        "article_id": article_id,
        "path": field_path,
        "status": status,
        "reviewer": reviewer,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if note:
        entry["note"] = note
    if correct_value is not None:
        entry["correct_value"] = correct_value
    if source:
        entry["source"] = source
    if batch_id:
        entry["batch_id"] = batch_id

    files = article_files(_CFG, article_id)
    ann_path = files.reviews_path(for_write=True)
    ann_path.parent.mkdir(parents=True, exist_ok=True)
    with ann_path.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


@app.delete("/api/annotations/{article_id}/{field_path:path}")
async def delete_annotation(article_id: str, field_path: str):
    """Remove an annotation for a specific field."""
    files = article_files(_CFG, article_id)
    ann_path = files.reviews_path(for_write=True)
    ann_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "article_id": article_id,
        "path": f".{field_path}",
        "status": "cleared",
        "reviewer": "",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    with ann_path.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
    return {"deleted": field_path}


def main():
    import uvicorn

    print(f"Article store: {_CFG.article_store_dir}")
    print(f"Legacy markdown dir: {_CFG.fulltext_md_dir}")
    print(f"Legacy extraction dir: {_CFG.llm_extractions_dir}")
    print(f"Papers dir: {PAPERS_DIR}")
    webbrowser.open("http://localhost:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
