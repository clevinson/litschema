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

from ..config import load_config
from .search import strip_references

_CFG = load_config()
PROJECT_ROOT = _CFG.project_root
MARKDOWN_DIR = _CFG.fulltext_md_dir
EXTRACTION_DIR = _CFG.llm_extractions_dir
REASONING_DIR = _CFG.extraction_reasoning_dir
ANNOTATIONS_DIR = _CFG.annotations_dir
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


def _article_meta(article_id: str) -> dict:
    """Return a compact bibliographic dict for an article id."""
    _load_corpus()
    a = (_article_index or {}).get(article_id)
    if not a:
        return {}
    authors = []
    for aid in a.get("author_ids") or []:
        auth = (_author_index or {}).get(aid)
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
    """Look up PDF filename from corpus.yaml."""
    _load_corpus()
    a = (_article_index or {}).get(article_id)
    if not a:
        return None
    return a.get("filename") or a.get("standard_filename")


@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text()


@app.get("/api/articles")
async def list_articles():
    """List articles that have both markdown and extraction JSON."""
    articles = []
    for ext_path in sorted(EXTRACTION_DIR.glob("*.json")):
        article_id = ext_path.stem
        md_path = MARKDOWN_DIR / f"{article_id}.md"
        if not md_path.exists():
            continue

        data = json.loads(ext_path.read_text())
        if data.get("error"):
            continue

        setups = data.get("experimental_setups") or []
        # Annotation progress
        ann_path = ANNOTATIONS_DIR / f"{article_id}.json"
        n_annotated = 0
        if ann_path.exists():
            ann = json.loads(ann_path.read_text())
            n_annotated = len(ann.get("annotations") or [])
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
    path = EXTRACTION_DIR / f"{article_id}.json"
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
    path = MARKDOWN_DIR / f"{article_id}.md"
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
    path = REASONING_DIR / f"{article_id}.json"
    if not path.exists():
        raise HTTPException(404, f"No reasoning for {article_id}")
    return json.loads(path.read_text())


@app.get("/api/annotations/{article_id}")
async def get_annotations(article_id: str):
    """Return annotations for an article."""
    path = ANNOTATIONS_DIR / f"{article_id}.json"
    if not path.exists():
        return {"article_id": article_id, "annotations": []}
    return json.loads(path.read_text())


@app.put("/api/annotations/{article_id}")
async def put_annotation(article_id: str, request: Request):
    """Add or update a field annotation."""
    body = await request.json()
    field_path = body.get("path")
    status = body.get("status")  # verified | flagged
    reviewer = body.get("reviewer", "")
    note = body.get("note")
    correct_value = body.get("correct_value")  # proposed correction or "__remove__" to delete field

    if not field_path or not status:
        raise HTTPException(400, "path and status are required")
    if status not in ("verified", "flagged"):
        raise HTTPException(400, "status must be verified or flagged")
    if status == "flagged" and not reviewer:
        raise HTTPException(400, "reviewer ORCID is required for flags")

    ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)
    ann_path = ANNOTATIONS_DIR / f"{article_id}.json"

    if ann_path.exists():
        data = json.loads(ann_path.read_text())
    else:
        data = {"article_id": article_id, "annotations": []}

    # Upsert: replace existing annotation for this path, or append
    annotations = [a for a in data["annotations"] if a["path"] != field_path]
    entry = {
        "path": field_path,
        "status": status,
        "reviewer": reviewer,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if note:
        entry["note"] = note
    if correct_value is not None:
        entry["correct_value"] = correct_value
    annotations.append(entry)
    data["annotations"] = annotations

    ann_path.write_text(json.dumps(data, indent=2) + "\n")
    return entry


@app.delete("/api/annotations/{article_id}/{field_path:path}")
async def delete_annotation(article_id: str, field_path: str):
    """Remove an annotation for a specific field."""
    ann_path = ANNOTATIONS_DIR / f"{article_id}.json"
    if not ann_path.exists():
        raise HTTPException(404, "No annotations for this article")

    data = json.loads(ann_path.read_text())
    # field_path comes URL-encoded, with leading dot
    data["annotations"] = [a for a in data["annotations"] if a["path"] != f".{field_path}"]
    ann_path.write_text(json.dumps(data, indent=2) + "\n")
    return {"deleted": field_path}


def main():
    import uvicorn

    print(f"Markdown dir: {MARKDOWN_DIR}")
    print(f"Extraction dir: {EXTRACTION_DIR}")
    print(f"Papers dir: {PAPERS_DIR}")
    print(f"Corpus: {CORPUS_PATH}")
    webbrowser.open("http://localhost:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
