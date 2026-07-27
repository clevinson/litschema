"""Extraction verification webapp — FastAPI backend.

Usage:
    uv run litschema verify
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from linkml_runtime.utils.schemaview import SchemaView

from ..article_registry import is_valid_doi, normalize_doi
from ..articles import (
    ArticleFiles,
    InvalidArticleIdError,
    article_files,
    iter_metadata_paths,
    read_article_metadata,
)
from ..config import LitSchemaConfig
from ..ingest.openalex_harvest import RegistryUnavailableError, sync_article
from ..review_paths import InvalidReviewPathError, canonical_review_path
from ..reviews import (
    ReviewContractError,
    ReviewCorruptError,
    effective_state,
    read_reviews,
    review_progress,
    unreview_subtree,
    upsert_review,
)
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


@app.exception_handler(InvalidArticleIdError)
async def _invalid_article_id_handler(request: Request, exc: InvalidArticleIdError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


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
    meta = read_source_metadata(manifest) or {"metadata_source": "auto"}
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


def _annotation(path: str, entry: dict) -> dict:
    """One stored review entry, in the vocabulary the spec defines.

    The wire shape IS the stored shape — there is no translation layer, so a
    reader of `specs/reviews/spec.md` sees the same names here.
    """
    annotation: dict = {"path": path, "state": "overridden" if entry.get("override") else "verified"}
    if entry.get("override") is not None:
        annotation["override"] = entry["override"]
    if entry.get("note") is not None:
        annotation["note"] = entry["note"]
    if entry.get("reviewer") is not None:
        annotation["reviewer"] = entry["reviewer"]
    return annotation


def _require_run(cfg: LitSchemaConfig, article_id: str, run_id: str):
    """Resolve an explicit run, 404ing rather than escaping the store."""
    from ..runs import BrokenActiveRunError, run_files

    files = article_files(cfg, article_id)
    try:
        run = run_files(files, run_id)
    except BrokenActiveRunError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not run.run_json.is_file() or not run.extraction.is_file():
        raise HTTPException(404, f"no published run {run_id} for {article_id}")
    return run


def _active_artifact(files: ArticleFiles, name: str):
    """Path of an artifact inside the active run, or None (broken pointer -> None
    here; list/read endpoints surface the article as unextracted rather than
    500ing the whole listing)."""
    from ..runs import BrokenActiveRunError, active_run

    try:
        run = active_run(files)
    except BrokenActiveRunError:
        return None
    if run is None:
        return None
    return getattr(run, name)


def _extraction_confidence(files: ArticleFiles) -> float | None:
    """The extractor's overall self-rated confidence from agent-reasoning.json."""
    reasoning_path = _active_artifact(files, "reasoning")
    if reasoning_path is None or not reasoning_path.exists():
        return None
    try:
        reasoning = json.loads(reasoning_path.read_bytes())
    except ValueError:
        return None
    value = reasoning.get("confidence") if isinstance(reasoning, dict) else None
    return value if isinstance(value, (int, float)) else None


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


def _active_run_id_or_none(files: ArticleFiles) -> str | None:
    """The active run id, or None when absent or the pointer is broken."""
    from ..runs import BrokenActiveRunError, active_run_id

    try:
        return active_run_id(files)
    except BrokenActiveRunError:
        return None


def _active_run_summary(files: ArticleFiles) -> dict | None:
    """What produced the active extraction, for display.

    The run id is opaque by contract, so it identifies but does not inform. A
    reviewer judging an extraction wants to know what produced it and when —
    the id is carried along only because run-level CLI commands take it.
    """
    from ..runs import BrokenActiveRunError, active_run

    try:
        run = active_run(files)
    except BrokenActiveRunError:
        return None
    if run is None:
        return None
    try:
        record = run.read_run_json()
    except (OSError, ValueError):
        return {"run_id": run.run_id}
    agent = record.get("agent") or {}
    return {
        "run_id": run.run_id,
        "created_at": record.get("created_at"),
        "provider": agent.get("provider"),
        "model": agent.get("model"),
        "effort": agent.get("effort"),
        "harness": agent.get("harness"),
    }


def _count_unattributed(cfg: LitSchemaConfig) -> int:
    """Review entries carrying no reviewer, across every published run."""
    from ..articles import iter_metadata_paths
    from ..reviews import ReviewCorruptError, read_reviews
    from ..runs import iter_run_ids, run_files

    total = 0
    for metadata_path in iter_metadata_paths(cfg):
        files = article_files(cfg, metadata_path.parent.name)
        for run_id in iter_run_ids(files):
            try:
                fields = read_reviews(run_files(files, run_id))
            except ReviewCorruptError:
                continue
            total += sum(1 for entry in fields.values() if not entry.get("reviewer"))
    return total


REQUIRE_REVIEWER_KEY = "require_reviewer"


def _require_reviewer(cfg: LitSchemaConfig) -> bool:
    """Whether this project demands attribution on every review.

    Read from config on each request rather than cached: the file is the
    authority, and it may be edited by hand or arrive through a pull while the
    server is running.
    """
    import yaml

    try:
        raw = yaml.safe_load(cfg.config_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return False
    return bool(raw.get(REQUIRE_REVIEWER_KEY, False))


def _set_require_reviewer(cfg: LitSchemaConfig, value: bool) -> None:
    """Write the policy into the project config, preserving everything else.

    Rewritten key-by-key rather than dumped wholesale so unknown keys, which
    the config contract preserves for domain repositories, survive untouched.
    """
    import yaml

    raw = yaml.safe_load(cfg.config_path.read_text()) or {}
    if value:
        raw[REQUIRE_REVIEWER_KEY] = True
    else:
        raw.pop(REQUIRE_REVIEWER_KEY, None)
    tmp = cfg.config_path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(raw, sort_keys=False, default_flow_style=False))
    tmp.replace(cfg.config_path)


def _resolved_schema(cfg: LitSchemaConfig):
    """The project schema, or None when it cannot be resolved.

    Typed coercion is a guarantee the schema provides; without a schema the
    review still saves, storing the value exactly as supplied.
    """
    from ..schema_resolution import resolve_extraction_schema

    try:
        return resolve_extraction_schema(cfg)
    except Exception:
        return None


def _identifier_paths(files: ArticleFiles, run) -> set[str]:
    """`identifier: true` leaves, which are identity rather than review work.

    Falls back to excluding nothing when the schema cannot be resolved — an
    inflated denominator is a better failure than a crash on every listing.
    """
    from ..schema_resolution import identifier_leaf_paths, resolve_extraction_schema

    try:
        resolved = resolve_extraction_schema(files.cfg)
        data = json.loads(run.extraction.read_text())
    except Exception:
        return set()
    try:
        return identifier_leaf_paths(resolved.view, resolved.root_class, data)
    except Exception:
        return set()


def _article_progress(files: ArticleFiles) -> dict:
    """Review progress for an article's active run.

    `specs/reviews/spec.md` owns effective state; this only aggregates. A
    corrupt review file nulls the counts rather than reporting them as zero —
    zero would read as "nothing reviewed yet", which is a different and much
    more comfortable claim than "we cannot tell".
    """
    from ..runs import BrokenActiveRunError, active_run

    empty = {
        "n_fields": 0,
        "n_reviewed": 0,
        "n_verified": 0,
        "n_overridden": 0,
        "n_unreviewed": 0,
        "review_progress": 0.0,
        "is_complete": False,
        "review_error": None,
    }
    try:
        run = active_run(files)
    except BrokenActiveRunError as exc:
        return {**empty, "review_error": str(exc)}
    if run is None:
        return empty
    try:
        progress = review_progress(run, exclude=_identifier_paths(files, run))
    except ReviewCorruptError as exc:
        return {
            **{key: None for key in empty if key != "review_error"},
            "review_error": str(exc),
        }
    return {**progress, "review_error": None}


#: LinkML scalar range -> editor "kind" reported by /api/schema/fields.
_SCALAR_KINDS = {
    "integer": "integer",
    "float": "float",
    "double": "float",
    "decimal": "float",
    "boolean": "boolean",
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
                    "kind": "enum",
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
            else:
                fields[path_pattern] = {
                    "kind": _SCALAR_KINDS.get(slot_range or "string", "string"),
                    "range": slot_range or "string",
                    "multivalued": bool(slot.multivalued),
                }

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


def _read_valid_extraction(files: ArticleFiles) -> dict | None:
    """Return the parsed extraction JSON, or None if absent, invalid, or errored."""
    extraction_path = _active_artifact(files, "extraction")
    if extraction_path is None or not extraction_path.exists():
        return None
    try:
        data = json.loads(extraction_path.read_text())
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("error"):
        return None
    return data


@app.get("/api/articles")
async def list_articles(cfg: CfgDep):
    """List all assembled articles; extracted ones carry review progress.

    Articles without a (valid) extraction still appear so the verifier can
    show their header and PDF with a "not yet extracted" placeholder.
    Missing markdown never excludes an article — the PDF tab still works.
    """
    articles = []
    for metadata_path in iter_metadata_paths(cfg):
        article_id = metadata_path.parent.name
        files = article_files(cfg, article_id)
        # Look up bibliographic fields from article metadata.
        bib = _article_meta(cfg, article_id)
        entry = {
            "article_id": article_id,
            "doi": bib.get("doi"),
            "title": bib.get("title"),
            "year": bib.get("year"),
            "journal": bib.get("journal"),
            "authors": bib.get("authors", []),
            "corporate_author": bib.get("corporate_author"),
            "metadata_source": bib.get("metadata_source"),
        }

        data = _read_valid_extraction(files)
        if data is None:
            entry.update(
                {
                    "has_extraction": False,
                    "confidence": None,
                    "n_setups": 0,
                    "active_run_id": None,
                    "active_run": None,
                    **_article_progress(files),
                }
            )
        else:
            setups = data.get("experimental_setups") or []
            progress = _article_progress(files)
            entry.update(
                {
                    "has_extraction": True,
                    "confidence": _extraction_confidence(files),
                    "study_types": data.get("study_types", []),
                    "focus_areas": data.get("focus_areas", []),
                    "document_type": data.get("document_type"),
                    "n_setups": len(setups),
                    "active_run_id": _active_run_id_or_none(files),
                    "active_run": _active_run_summary(files),
                    **progress,
                }
            )
        articles.append(entry)

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
    """Return the active run's raw extraction JSON for an article.

    Raw, not effective: the document view renders the review overlay itself so
    it can show what the agent said alongside what a human changed it to.
    """
    path = _active_artifact(article_files(cfg, article_id), "extraction")
    if path is None or not path.exists():
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
    touched by header edits (distinct layers; see specs/source-metadata/spec.md).
    """
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be a JSON object")
    unknown = set(body) - set(SOURCE_FIELDS)
    if unknown:
        raise HTTPException(400, f"unknown fields: {', '.join(sorted(unknown))}")
    if not body:
        raise HTTPException(400, "no fields to update")

    # An explicit empty string clears the field (same convention as the CLI).
    fields = {key: (None if value == "" else value) for key, value in body.items()}
    if isinstance(fields.get("authors"), str):
        fields["authors"] = [
            n.strip() for n in fields["authors"].split(",") if n.strip()
        ] or None
    if fields.get("year") is not None:
        try:
            fields["year"] = int(fields["year"])
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "year must be an integer") from exc
    if fields.get("doi") is not None:
        normalized = normalize_doi(str(fields["doi"]))
        if not is_valid_doi(normalized):
            raise HTTPException(400, f"not a valid DOI: {fields['doi']}")
        fields["doi"] = normalized

    files = article_files(cfg, article_id)
    if not files.metadata.exists():
        raise HTTPException(404, f"Unknown article {article_id}")
    block = update_source_metadata(files, fields, source="manual")
    block["editable"] = True
    return block


@app.post("/api/bibliography/{article_id}/sync")
async def sync_bibliography(article_id: str, cfg: CfgDep):
    """Re-fetch the header from the DOI registry and lock it.

    Overwrites ANY provenance, including ``manual`` — the explicit button
    press (or CLI call) is the consent that batch harvest never has.
    """
    files = article_files(cfg, article_id)
    if not files.metadata.exists():
        raise HTTPException(404, f"Unknown article {article_id}")
    try:
        block = sync_article(cfg, article_id)
    except LookupError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RegistryUnavailableError as exc:
        raise HTTPException(502, "DOI registry unavailable — try again") from exc
    if block is None:
        raise HTTPException(502, "the registry has no usable record for this DOI")
    block["editable"] = False
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
    path = _active_artifact(article_files(cfg, article_id), "reasoning")
    if path is None or not path.exists():
        raise HTTPException(404, f"No reasoning for {article_id}")
    return json.loads(path.read_text())


@app.get("/api/settings")
async def get_settings(cfg: CfgDep):
    """Project-level review settings and the context needed to explain them."""
    from ..cli import _in_git_repo

    shared = _in_git_repo(cfg.project_root)
    return {
        "require_reviewer": _require_reviewer(cfg),
        # A repository is the available signal that the work may be shared,
        # which is what makes attribution matter and backfill risky.
        "in_git_repo": shared,
        "unattributed_reviews": _count_unattributed(cfg),
    }


@app.put("/api/settings")
async def put_settings(request: Request, cfg: CfgDep):
    """Update project review policy. Writes litschema.yaml."""
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be a JSON object")
    if REQUIRE_REVIEWER_KEY in body:
        value = body[REQUIRE_REVIEWER_KEY]
        if not isinstance(value, bool):
            raise HTTPException(400, f"{REQUIRE_REVIEWER_KEY} must be true or false")
        try:
            _set_require_reviewer(cfg, value)
        except OSError as exc:
            raise HTTPException(500, f"could not write {cfg.config_path}: {exc}") from exc
    return await get_settings(cfg)


@app.post("/api/reviews/backfill-reviewer")
async def backfill_reviewer(request: Request, cfg: CfgDep):
    """Attribute previously anonymous reviews to a reviewer.

    Only entries with no reviewer are touched; an entry already attributed to
    someone is never reassigned. Corrupt review files are skipped rather than
    rewritten.
    """
    from ..articles import iter_metadata_paths
    from ..reviews import ReviewCorruptError, read_reviews, write_reviews
    from ..runs import iter_run_ids, run_files

    body = await request.json()
    reviewer = str((body or {}).get("reviewer") or "").strip()
    if not reviewer:
        raise HTTPException(400, "reviewer is required")
    reviewer = _normalize_orcid_id(reviewer)

    updated = 0
    skipped_corrupt = 0
    for metadata_path in iter_metadata_paths(cfg):
        files = article_files(cfg, metadata_path.parent.name)
        for run_id in iter_run_ids(files):
            run = run_files(files, run_id)
            try:
                fields = read_reviews(run)
            except ReviewCorruptError:
                skipped_corrupt += 1
                continue
            changed = False
            for entry in fields.values():
                if not entry.get("reviewer"):
                    entry["reviewer"] = reviewer
                    changed = True
                    updated += 1
            if changed:
                write_reviews(run, fields)
    return {"updated": updated, "skipped_corrupt": skipped_corrupt, "reviewer": reviewer}


@app.get("/api/annotations/{article_id}/{run_id}")
async def get_annotations(article_id: str, run_id: str, cfg: CfgDep):
    """Stored review entries and effective state for one explicit run.

    Every review read and write names its run, so switching the active run can
    never silently retarget an edit begun against a different extraction.
    """
    run = _require_run(cfg, article_id, run_id)
    try:
        fields = read_reviews(run)
    except ReviewCorruptError as exc:
        # Explicit, never a silent empty: the caller must be able to tell
        # "no reviews" apart from "reviews unreadable".
        return {
            "article_id": article_id,
            "run_id": run_id,
            "annotations": None,
            "review_error": str(exc),
        }
    return {
        "article_id": article_id,
        "run_id": run_id,
        "annotations": [_annotation(path, entry) for path, entry in sorted(fields.items())],
        "review_error": None,
    }


@app.put("/api/annotations/{article_id}/{run_id}")
async def put_annotation(article_id: str, run_id: str, request: Request, cfg: CfgDep):
    """Upsert one path. No override means verify; an override replaces/removes/adds."""
    run = _require_run(cfg, article_id, run_id)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "body must be a JSON object")

    field_path = body.get("path")
    if not isinstance(field_path, str) or not field_path.strip():
        raise HTTPException(400, "path is required")

    entry: dict = {}
    override = body.get("override")
    if override is not None:
        if not isinstance(override, dict) or override.get("op") not in ("replace", "remove", "add"):
            raise HTTPException(400, "override.op must be replace, remove, or add")
        entry["override"] = override
    note = body.get("note")
    if note:
        entry["note"] = str(note)
    # Attribution is optional: a lone reviewer gains nothing from asserting who
    # they are. When supplied it is normalized so the stored form is canonical.
    reviewer = body.get("reviewer")
    if reviewer and str(reviewer).strip():
        entry["reviewer"] = _normalize_orcid_id(str(reviewer).strip())
    # A policy only the browser respects is not a policy: enforce it here so it
    # binds every caller, including scripts and agents.
    if _require_reviewer(cfg) and "reviewer" not in entry:
        raise HTTPException(
            400,
            "this project requires a reviewer on every review "
            f"(set {REQUIRE_REVIEWER_KEY}: false in litschema.yaml to change that)",
        )

    try:
        fields = upsert_review(run, field_path, entry, schema=_resolved_schema(cfg))
        key = canonical_review_path(field_path)
    except InvalidReviewPathError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ReviewContractError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ReviewCorruptError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "annotation": _annotation(key, fields[key]) if key in fields else None,
        "state": effective_state(key, fields),
    }


@app.delete("/api/annotations/{article_id}/{run_id}/{field_path:path}")
async def delete_annotation(
    article_id: str,
    run_id: str,
    field_path: str,
    cfg: CfgDep,
    discard_note: bool = False,
):
    """Unreview the whole subtree at ``field_path``.

    Pass ``?discard_note=true`` to confirm discarding a note carried by a
    covering ancestor — the one case where unreviewing destroys prose a human
    wrote, so it is never implicit.
    """
    run = _require_run(cfg, article_id, run_id)
    if not field_path.strip("."):
        raise HTTPException(400, "field path is required")
    try:
        unreview_subtree(run, field_path, discard_note=discard_note)
    except InvalidReviewPathError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ReviewContractError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ReviewCorruptError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"unreviewed": canonical_review_path(field_path)}


def run_app(cfg: LitSchemaConfig, *, port: int = 8000) -> None:
    import uvicorn

    app.state.litschema_config = cfg
    print(f"Article store: {cfg.article_store_dir}")
    print(f"Paper inbox: {cfg.paper_inbox_dir}")
    webbrowser.open(f"http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)
