"""Extraction verification webapp — FastAPI backend.

Usage:
    uv run litschema verify
"""

from __future__ import annotations

import contextlib
import json
import re
import urllib.error
import urllib.request
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from linkml_runtime.utils.schemaview import SchemaView

from ..articles import (
    article_files,
    iter_article_ids_with_extractions,
    read_article_metadata,
    read_review_events,
)
from ..config import LitSchemaConfig
from ..schema_resolution import resolve_extraction_schema
from ..source_metadata import (
    SOURCE_FIELDS,
    read_source_metadata,
    update_source_metadata,
)
from .search import strip_references

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="ERW Extraction Verifier")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[0-9X]$")


def get_config() -> LitSchemaConfig:
    """FastAPI dependency yielding the active litschema config.

    Tests override via ``app.dependency_overrides[get_config] = ...``
    (the documented FastAPI pattern). Production use must launch through
    ``litschema verify``, which sets ``app.state`` before uvicorn starts.
    """
    try:
        return app.state.litschema_config
    except AttributeError as exc:
        raise RuntimeError(
            "Verification app config is not initialized; launch with "
            "`litschema verify` or override get_config in tests."
        ) from exc


CfgDep = Annotated[LitSchemaConfig, Depends(get_config)]


def _article_meta(cfg: LitSchemaConfig, article_id: str) -> dict:
    """Return the provenance-tagged source metadata for an article id.

    ``editable`` tells the header which render mode to use — everything is
    editable except registry-locked (``doi``) records; an assembled article
    with no metadata yet comes back as an empty editable record.
    """
    manifest = read_article_metadata(article_files(cfg, article_id))
    if not manifest:
        return {}
    meta = read_source_metadata(manifest)
    if not meta:
        return {"metadata_source": "auto", "editable": True}
    meta["editable"] = meta.get("metadata_source") != "doi"
    return meta


def _article_pdf_filename(cfg: LitSchemaConfig, article_id: str) -> str | None:
    """Look up PDF filename from per-article metadata."""
    files = article_files(cfg, article_id)
    if files.pdf.exists():
        return files.pdf.name
    a = read_article_metadata(files)
    if not a:
        return None
    filename = a.get("filename") or a.get("standard_filename")
    if filename:
        return filename
    return None


def _article_pdf_path(cfg: LitSchemaConfig, article_id: str) -> Path | None:
    filename = _article_pdf_filename(cfg, article_id)
    if not filename:
        return None
    files = article_files(cfg, article_id)
    article_pdf = files.article_dir / filename
    if article_pdf.exists():
        return article_pdf
    inbox_pdf = cfg.paper_inbox_dir / filename
    if inbox_pdf.exists():
        return inbox_pdf
    return article_pdf


def _collapse_review_events(events: list[dict]) -> list[dict]:
    """Collapse an event stream to at most one entry per path.

    Legacy 'cleared' events drop their path; everything else is last-write-wins.
    Writes use this as the read-modify-write base so a file's persisted state
    is always already collapsed (one row per path, no clear markers).
    """
    current: dict[str, dict] = {}
    for event in events:
        path = event.get("path")
        if not path:
            continue
        if event.get("status") == "cleared":
            current.pop(path, None)
        else:
            current[path] = event
    return list(current.values())


def _current_annotations(cfg: LitSchemaConfig, article_id: str) -> list[dict]:
    """Return latest annotation state per path."""
    return _collapse_review_events(read_review_events(article_files(cfg, article_id)))


def _write_reviews_jsonl(path: Path, entries: list[dict]) -> None:
    """Atomically replace reviews.jsonl with ``entries``.

    Removes the file entirely when ``entries`` is empty so paper folders
    don't accumulate 0-byte review files.
    """
    if not entries:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")
    tmp.replace(path)


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
        if not base_path and key == "article_id":
            continue
        child_path = f"{base_path}.{key}" if base_path else key
        paths.extend(_leaf_paths(value, child_path))
    return paths


def _review_progress(extraction: dict, annotations: list[dict]) -> dict:
    """Summarize field-level review progress for article queue filters."""
    leaf_paths = set(_leaf_paths(extraction))
    current: dict[str, dict] = {}
    for annotation in annotations:
        path = annotation.get("path")
        status = annotation.get("status")
        if not path:
            continue
        path = path.lstrip(".")
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
async def list_articles(cfg: CfgDep):
    """List articles that have both markdown and extraction JSON."""
    articles = []
    for article_id in iter_article_ids_with_extractions(cfg):
        files = article_files(cfg, article_id)
        ext_path = files.extraction
        md_path = files.markdown
        if not md_path.exists():
            continue

        data = json.loads(ext_path.read_text())
        if data.get("error"):
            continue

        setups = data.get("experimental_setups") or []
        # Annotation progress
        annotations = _current_annotations(cfg, article_id)
        progress = _review_progress(data, annotations)
        # Look up bibliographic fields from article metadata.
        bib = _article_meta(cfg, article_id)
        articles.append(
            {
                "article_id": article_id,
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
                "corporate_author": bib.get("corporate_author"),
                "metadata_source": bib.get("metadata_source"),
            }
        )

    return {"articles": articles, "total": len(articles)}


@app.get("/api/schema/fields")
async def get_schema_fields(cfg: CfgDep):
    """Return schema-driven field editor metadata for the verifier."""
    try:
        return _schema_field_metadata(cfg)
    except Exception as exc:
        raise HTTPException(404, "schema metadata unavailable") from exc


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
async def get_article(article_id: str, cfg: CfgDep):
    """Return full extraction JSON for an article."""
    path = article_files(cfg, article_id).extraction
    if not path.exists():
        raise HTTPException(404, f"No extraction for {article_id}")
    return json.loads(path.read_text())


@app.get("/api/bibliography/{article_id}")
async def get_bibliography(article_id: str, cfg: CfgDep):
    """Return provenance-tagged source metadata for the verify header."""
    meta = _article_meta(cfg, article_id)
    if not meta:
        raise HTTPException(404, f"Unknown article {article_id}")
    return meta


@app.put("/api/bibliography/{article_id}")
async def put_bibliography(article_id: str, request: Request, cfg: CfgDep):
    """Apply a human edit to the verify header; provenance becomes 'manual'.

    Accepts a partial record of SOURCE_FIELDS. ``null`` clears a field.
    Header metadata lives in the article manifest — review.json is never
    touched by header edits (distinct layers, design doc §3.6).
    """
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be a JSON object")
    unknown = set(body) - set(SOURCE_FIELDS)
    if unknown:
        raise HTTPException(400, f"unknown fields: {', '.join(sorted(unknown))}")
    if not body:
        raise HTTPException(400, "no fields to update")

    fields = dict(body)
    if isinstance(fields.get("authors"), str):
        fields["authors"] = [n.strip() for n in fields["authors"].split(",") if n.strip()]
    if fields.get("year") not in (None, ""):
        try:
            fields["year"] = int(fields["year"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "year must be an integer") from exc
    if fields.get("year") == "":
        fields["year"] = None

    files = article_files(cfg, article_id)
    if not files.metadata.exists():
        raise HTTPException(404, f"Unknown article {article_id}")
    block = update_source_metadata(files, fields, source="manual")
    block["editable"] = True
    return block


@app.get("/api/markdown/{article_id}")
async def get_markdown(article_id: str, cfg: CfgDep):
    """Return raw markdown text for an article."""
    path = article_files(cfg, article_id).markdown
    if not path.exists():
        raise HTTPException(404, f"No markdown for {article_id}")
    text = path.read_text()
    return {"markdown": strip_references(text)}


@app.get("/api/pdf/{article_id}")
async def get_pdf(article_id: str, cfg: CfgDep):
    """Serve the PDF file for an article."""
    pdf_path = _article_pdf_path(cfg, article_id)
    if not pdf_path:
        raise HTTPException(404, f"No PDF filename found for {article_id}")
    if not pdf_path.exists():
        raise HTTPException(404, f"PDF not found: {pdf_path.name}")

    return FileResponse(pdf_path, media_type="application/pdf")


@app.get("/api/reasoning/{article_id}")
async def get_reasoning(article_id: str, cfg: CfgDep):
    """Return per-field extraction reasoning if it exists."""
    path = article_files(cfg, article_id).reasoning
    if not path.exists():
        raise HTTPException(404, f"No reasoning for {article_id}")
    return json.loads(path.read_text())


@app.get("/api/annotations/{article_id}")
async def get_annotations(article_id: str, cfg: CfgDep):
    """Return annotations for an article."""
    return {"article_id": article_id, "annotations": _current_annotations(cfg, article_id)}


@app.put("/api/annotations/{article_id}")
async def put_annotation(article_id: str, request: Request, cfg: CfgDep):
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

    files = article_files(cfg, article_id)
    ann_path = files.reviews
    # Upsert: keep at most one entry per path. The existing log is collapsed
    # first so legacy duplicates and 'cleared' markers get cleaned up by the
    # same write that records this annotation.
    entries = [
        e for e in _collapse_review_events(read_review_events(files))
        if e.get("path") != entry["path"]
    ]
    entries.append(entry)
    _write_reviews_jsonl(ann_path, entries)
    return entry


@app.delete("/api/annotations/{article_id}/{field_path:path}")
async def delete_annotation(article_id: str, field_path: str, cfg: CfgDep):
    """Remove an annotation for a specific field.

    Drops the matching line from reviews.jsonl rather than appending a
    'cleared' marker — clearing is not an attributable action and the
    file is meant to hold at most one entry per path.
    """
    files = article_files(cfg, article_id)
    ann_path = files.reviews
    target_path = f".{field_path}"
    entries = [
        e for e in _collapse_review_events(read_review_events(files))
        if e.get("path") != target_path
    ]
    _write_reviews_jsonl(ann_path, entries)
    return {"deleted": field_path}


def run_app(cfg: LitSchemaConfig, *, port: int = 8000) -> None:
    import uvicorn

    app.state.litschema_config = cfg
    print(f"Article store: {cfg.article_store_dir}")
    print(f"Paper inbox: {cfg.paper_inbox_dir}")
    webbrowser.open(f"http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)
