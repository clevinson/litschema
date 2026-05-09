"""Extraction verification webapp — FastAPI backend.

Usage:
    uv run litschema verify
    # or, directly:
    uv run python -m litschema.webapp.app
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from linkml_runtime.utils.schemaview import SchemaView

from ..articles import (
    article_files,
    iter_article_ids_with_extractions,
    read_article_metadata,
    read_review_events,
)
from ..config import LitSchemaConfig, load_config
from ..schema_resolution import resolve_extraction_schema
from .search import strip_references

_CFG = load_config()
PROJECT_ROOT = _CFG.project_root
PAPERS_DIR = _CFG.papers_dir
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="ERW Extraction Verifier")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_author_file_index: dict[str, dict] | None = None
_schema_fields_cache: dict | None = None
ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[0-9X]$")


def _load_author_index() -> dict[str, dict]:
    global _author_file_index
    if _author_file_index is not None:
        return _author_file_index
    authors_path = _CFG.data_dir / "authors.yaml"
    if not authors_path.exists():
        _author_file_index = {}
        return {}
    authors = yaml.safe_load(authors_path.read_text()) or []
    _author_file_index = {a.get("id"): a for a in authors if a.get("id")}
    return _author_file_index


def _article_meta(article_id: str) -> dict:
    """Return a compact bibliographic dict for an article id."""
    a = read_article_metadata(article_files(_CFG, article_id))
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
    """Look up PDF filename from per-article metadata."""
    a = read_article_metadata(article_files(_CFG, article_id))
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


def _leaf_paths(obj, base_path: str = "") -> list[str]:
    """Return reviewable extraction leaf paths in verifier path syntax."""
    if obj is None or not isinstance(obj, (dict, list)):
        return [base_path] if base_path else []
    if isinstance(obj, list):
        paths = []
        for idx, item in enumerate(obj):
            paths.extend(_leaf_paths(item, f"{base_path}[{idx}]"))
        return paths

    paths = []
    for key, value in obj.items():
        if not base_path and key in {"article_id", "confidence", "reasoning"}:
            continue
        child_path = f"{base_path}.{key}" if base_path else key
        paths.extend(_leaf_paths(value, child_path))
    return paths


def _normalize_review_path(path: str) -> str:
    path = path.lstrip(".")
    legacy_suffix = ".trial_type"
    if path.endswith(legacy_suffix):
        return path[: -len(legacy_suffix)] + ".experimental_scale"
    return path


def _review_progress(extraction: dict, annotations: list[dict]) -> dict:
    """Summarize field-level review progress for article queue filters."""
    leaf_paths = set(_leaf_paths(extraction))
    current: dict[str, dict] = {}
    for annotation in annotations:
        path = annotation.get("path")
        status = annotation.get("status")
        if not path:
            continue
        path = _normalize_review_path(path)
        if status == "cleared":
            current.pop(path, None)
        elif path in leaf_paths:
            current[path] = annotation

    n_verified = sum(1 for ann in current.values() if ann.get("status") == "verified")
    n_flagged = sum(1 for ann in current.values() if ann.get("status") == "flagged")
    n_fields = len(leaf_paths)
    n_reviewed = n_verified + n_flagged
    return {
        "n_fields": n_fields,
        "n_reviewed": n_reviewed,
        "n_verified": n_verified,
        "n_flagged": n_flagged,
        "is_complete": n_fields > 0 and n_reviewed >= n_fields,
        "has_flags": n_flagged > 0,
    }


def _enum_permissible_values(sv: SchemaView, enum_name: str) -> list[dict]:
    enum = sv.get_enum(enum_name)
    if not enum:
        return []
    values = []
    for value, pv in (enum.permissible_values or {}).items():
        values.append(
            {
                "value": value,
                "description": getattr(pv, "description", None) or "",
            }
        )
    return values


def _schema_field_metadata(cfg: LitSchemaConfig) -> dict:
    """Return enum metadata keyed by verifier path pattern.

    Multivalued path components use [] so the frontend can normalize
    concrete paths such as experiments[0].treatments[1].type.
    """
    extraction_schema = resolve_extraction_schema(cfg)
    sv = extraction_schema.view
    root_class = extraction_schema.root_class
    classes = set(sv.all_classes())
    enums = set(sv.all_enums())
    fields: dict[str, dict] = {}

    def walk(class_name: str, base_path: str = "", stack: tuple[str, ...] = ()) -> None:
        if class_name in stack:
            return
        for slot in sv.class_induced_slots(class_name):
            slot_path = f"{base_path}.{slot.name}" if base_path else slot.name
            path_pattern = f"{slot_path}[]" if slot.multivalued else slot_path
            slot_range = slot.range
            if slot_range in enums:
                fields[path_pattern] = {
                    "range": slot_range,
                    "multivalued": bool(slot.multivalued),
                    "permissible_values": _enum_permissible_values(sv, slot_range),
                }
            elif slot_range in classes:
                walk(
                    slot_range,
                    path_pattern if slot.multivalued else slot_path,
                    (*stack, class_name),
                )

    walk(root_class)
    return {"root_class": root_class, "fields": fields}


def _normalize_orcid_id(orcid_id: str) -> str:
    """Return a canonical ORCID iD or raise 400."""
    value = re.sub(r"^https?://orcid\.org/", "", orcid_id.strip(), flags=re.IGNORECASE).rstrip("/")
    value = value.upper()
    if not ORCID_RE.match(value):
        raise HTTPException(400, "Invalid ORCID iD")
    return value


def _orcid_display_name(person: dict) -> str | None:
    """Extract a readable public name from an ORCID person payload."""
    name = (person.get("name") or {}) if isinstance(person, dict) else {}
    credit = ((name.get("credit-name") or {}).get("value") or "").strip()
    given = ((name.get("given-names") or {}).get("value") or "").strip()
    family = ((name.get("family-name") or {}).get("value") or "").strip()
    if credit:
        return credit
    full = " ".join(part for part in [given, family] if part).strip()
    return full or None


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
        annotations = _current_annotations(article_id)
        progress = _review_progress(data, annotations)
        # Look up bibliographic fields from article metadata.
        bib = _article_meta(article_id)
        articles.append(
            {
                "article_id": article_id,
                "confidence": data.get("confidence"),
                "study_types": data.get("study_types", []),
                "focus_areas": data.get("focus_areas", []),
                "document_type": data.get("document_type"),
                "n_setups": len(setups),
                "n_annotated": progress["n_reviewed"],
                **progress,
                "doi": bib.get("doi"),
                "title": bib.get("title"),
                "year": bib.get("year"),
                "journal": bib.get("journal"),
                "authors": bib.get("authors", []),
            }
        )

    return {"articles": articles, "total": len(articles)}


@app.get("/api/schema/fields")
async def get_schema_fields():
    """Return schema-driven field editor metadata for the verifier."""
    global _schema_fields_cache
    if _schema_fields_cache is None:
        try:
            _schema_fields_cache = _schema_field_metadata(_CFG)
        except Exception as exc:
            raise HTTPException(404, "schema metadata unavailable") from exc
    return _schema_fields_cache


@app.get("/api/orcid/{orcid_id}")
async def get_orcid_profile(orcid_id: str):
    """Resolve an ORCID iD to a public profile name."""
    canonical_id = _normalize_orcid_id(orcid_id)
    request = urllib.request.Request(
        f"https://pub.orcid.org/v3.0/{canonical_id}/person",
        headers={
            "Accept": "application/json",
            "User-Agent": "litschema-verifier/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            person = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(404, "User not found") from exc
        raise HTTPException(502, "ORCID lookup failed") from exc
    except Exception as exc:
        raise HTTPException(502, "ORCID lookup failed") from exc

    name = _orcid_display_name(person)
    if not name:
        raise HTTPException(404, "User not found")
    return {"orcid": canonical_id, "name": name, "url": f"https://orcid.org/{canonical_id}"}


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
