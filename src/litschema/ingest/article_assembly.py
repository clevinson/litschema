"""Deterministic article intake before schema building or extraction."""

from __future__ import annotations

import json
import logging
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from ..article_registry import (
    has_article_id,
    is_valid_doi,
    normalize_doi,
    normalize_registry_row,
    read_article_registry,
    registry_path,
    write_article_registry,
)
from ..articles import article_files
from ..config import LitSchemaConfig, require_config_or_exit
from . import harvest_cache_dir, openalex_harvest

logger = logging.getLogger(__name__)

AssembleReporter = Callable[[str, dict[str, object]], None]

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
DOI_SCAN_PAGES = 2
REGISTRY_OWNED_METADATA_KEYS = {
    "id",
    "doi",
    "title",
    "year",
    "publisher",
    "author_citation",
    "open_access",
}


class AssemblyInterrupted(Exception):
    """Raised when article assembly is cancelled by Ctrl-C."""

    def __init__(self, pdf_path: Path | None = None):
        self.pdf_path = pdf_path
        if pdf_path is None:
            message = "article assembly interrupted"
        else:
            message = f"article assembly interrupted while processing {pdf_path}"
        super().__init__(message)


def _report(reporter: AssembleReporter | None, event: str, **payload: object) -> None:
    if reporter is not None:
        reporter(event, payload)


def _is_wrapped_keyboard_interrupt(exc: BaseException) -> bool:
    return "KeyboardInterrupt" in f"{type(exc).__name__}: {exc}"


def _normalize_doi(doi: str) -> str:
    return normalize_doi(doi)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug or "article"


def _family_name(display_name: str | None) -> str:
    if not display_name:
        return ""
    return display_name.strip().split()[-1]


def _author_families(extracted: dict) -> list[str]:
    families = []
    for author in extracted.get("authors") or []:
        family = _family_name(author.get("display_name"))
        if family:
            families.append(family)
    return families


def _author_citation(extracted: dict) -> str:
    families = _author_families(extracted)
    if not families:
        return ""
    if len(families) == 1:
        return families[0]
    if len(families) == 2:
        return f"{families[0]} & {families[1]}"
    return f"{families[0]} et al."


def _article_id_from_metadata(row: dict[str, str], extracted: dict, doi: str) -> str:
    if row.get("article_id"):
        return row["article_id"]
    families = _author_families(extracted)
    year = extracted.get("publication_year") or row.get("year")
    if families and year:
        return _slugify(f"{families[0]}-{year}")
    return openalex_harvest.doi_to_slug(doi)


def _ensure_unique_article_id(article_id: str, existing_ids: set[str]) -> str:
    if article_id not in existing_ids:
        existing_ids.add(article_id)
        return article_id
    i = 2
    while f"{article_id}-{i}" in existing_ids:
        i += 1
    unique = f"{article_id}-{i}"
    existing_ids.add(unique)
    return unique


def _registry_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {_normalize_doi(row["doi"]).lower(): row for row in rows if row.get("doi")}


def _registry_article_id_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["article_id"]: row for row in rows if row.get("article_id")}


def _metadata_row(metadata_path: Path, metadata: dict) -> dict[str, str]:
    article_id = str(metadata.get("id") or metadata_path.parent.name)
    open_access = metadata.get("open_access")
    if isinstance(open_access, bool):
        open_access_value = "true" if open_access else "false"
    else:
        open_access_value = open_access
    return normalize_registry_row(
        doi=metadata.get("doi"),
        article_id=article_id,
        title=metadata.get("title"),
        author_citation=metadata.get("author_citation"),
        year=metadata.get("year"),
        publisher=metadata.get("publisher"),
        open_access=open_access_value,
    )


def _sync_registry_from_article_metadata(cfg: LitSchemaConfig, rows: list[dict[str, str]]) -> int:
    by_doi = _registry_index(rows)
    by_article_id = _registry_article_id_index(rows)
    added = 0
    for metadata_path in sorted(cfg.article_store_dir.glob("*/article-metadata.json")):
        try:
            metadata = json.loads(metadata_path.read_text())
        except (OSError, json.JSONDecodeError):
            logger.warning("Unable to read article metadata for registry sync: %s", metadata_path)
            continue
        row = _metadata_row(metadata_path, metadata)
        doi = row.get("doi")
        article_id = row.get("article_id")
        matched_by_doi = bool(doi and doi.lower() in by_doi)
        existing = by_doi.get(doi.lower()) if doi else None
        if existing is None and article_id:
            existing = by_article_id.get(article_id)
        if existing is not None:
            for key, value in row.items():
                if key == "doi" and not matched_by_doi:
                    continue
                if value and not existing.get(key):
                    existing[key] = value
            if existing.get("doi"):
                by_doi[existing["doi"].lower()] = existing
            if existing.get("article_id"):
                by_article_id[existing["article_id"]] = existing
            continue
        rows.append(row)
        if doi:
            by_doi[doi.lower()] = row
        if article_id:
            by_article_id[article_id] = row
        added += 1
    return added


def _upsert_doi_row(rows: list[dict[str, str]], doi: str) -> dict[str, str]:
    doi = _normalize_doi(doi)
    by_doi = _registry_index(rows)
    existing = by_doi.get(doi.lower())
    if existing is not None:
        return existing
    row = normalize_registry_row(doi=doi)
    rows.append(row)
    return row


def _fill_blank(row: dict[str, str], key: str, value: object) -> None:
    if row.get(key) or value in (None, ""):
        return
    row[key] = str(value)


def _open_access_value(extracted: dict) -> str:
    open_access = extracted.get("open_access") or {}
    if isinstance(open_access, dict) and "is_oa" in open_access:
        return "true" if open_access["is_oa"] else "false"
    if isinstance(open_access, bool):
        return "true" if open_access else "false"
    return ""


def _metadata_open_access(value: object) -> bool | str | None:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
        return value if value.strip() else None
    if isinstance(value, bool):
        return value
    if isinstance(value, dict) and "is_oa" in value:
        return bool(value["is_oa"])
    return None


def _cache_openalex(cfg: LitSchemaConfig, doi: str, extracted: dict) -> None:
    cache_dir = harvest_cache_dir(cfg, "openalex")
    cache_dir.mkdir(parents=True, exist_ok=True)
    slug = openalex_harvest.doi_to_slug(doi)
    (cache_dir / f"{slug}.json").write_text(json.dumps(extracted, indent=2, ensure_ascii=False))


def _metadata_for_article(row: dict[str, str], extracted: dict, pdf_filename: str | None) -> dict:
    doi = row.get("doi")
    metadata = {
        "id": row.get("article_id"),
        "doi": doi if doi and is_valid_doi(doi) else None,
        "title": row.get("title") or extracted.get("title"),
        "abstract": extracted.get("abstract"),
        "year": row.get("year") or extracted.get("publication_year"),
        "journal": extracted.get("journal"),
        "publisher": row.get("publisher") or extracted.get("publisher_from_source"),
        "author_citation": row.get("author_citation"),
        "open_access": _metadata_open_access(row.get("open_access") or extracted.get("open_access")),
        "filename": pdf_filename,
    }
    return {key: value for key, value in metadata.items() if value not in (None, "")}


def _write_article_metadata(
    cfg: LitSchemaConfig,
    row: dict[str, str],
    extracted: dict,
    *,
    pdf_filename: str | None = None,
) -> None:
    article_id = row.get("article_id")
    if not article_id:
        return
    files = article_files(cfg, article_id)
    files.metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata = _metadata_for_article(row, extracted, pdf_filename)
    if files.metadata.exists():
        existing = json.loads(files.metadata.read_text())
        merged = metadata | existing
        for key in REGISTRY_OWNED_METADATA_KEYS:
            if key in metadata:
                merged[key] = metadata[key]
        if pdf_filename and "filename" in metadata:
            merged["filename"] = metadata["filename"]
        if not row.get("doi") or not is_valid_doi(row["doi"]):
            merged.pop("doi", None)
        metadata = merged
    files.metadata.write_text(json.dumps(metadata, indent=2) + "\n")


def _has_metadata_only_fields(row: dict[str, str]) -> bool:
    if not has_article_id(row):
        return False
    if not str(row.get("title") or "").strip():
        return False
    return any(str(row.get(key) or "").strip() for key in ("author_citation", "year", "publisher"))


def _write_metadata_only_row(cfg: LitSchemaConfig, row: dict[str, str]) -> bool:
    if not _has_metadata_only_fields(row):
        return False
    _write_article_metadata(cfg, row, {})
    return True


def _populate_row_from_openalex(
    cfg: LitSchemaConfig,
    row: dict[str, str],
    *,
    existing_ids: set[str],
) -> bool:
    doi = row.get("doi")
    if not doi:
        return False
    if not is_valid_doi(doi):
        return False
    if row.get("article_id") and row.get("title") and row.get("year") and row.get(
        "author_citation"
    ) and article_files(cfg, row["article_id"]).metadata.exists():
        _write_article_metadata(cfg, row, {})
        return False

    cache_path = harvest_cache_dir(cfg, "openalex") / f"{openalex_harvest.doi_to_slug(doi)}.json"
    if cache_path.exists():
        extracted = json.loads(cache_path.read_text())
        if extracted.get("error"):
            if _has_metadata_only_fields(row):
                _write_article_metadata(cfg, row, {})
            return False
    else:
        raw = openalex_harvest.fetch_openalex(doi)
        if raw is None:
            if _has_metadata_only_fields(row):
                _write_article_metadata(cfg, row, {})
            return False
        extracted = openalex_harvest.extract_metadata(raw)
        _cache_openalex(cfg, doi, extracted)

    if not row.get("article_id"):
        article_id = _article_id_from_metadata(row, extracted, doi)
        row["article_id"] = _ensure_unique_article_id(article_id, existing_ids)
    else:
        existing_ids.add(row["article_id"])
    _fill_blank(row, "title", extracted.get("title"))
    _fill_blank(row, "author_citation", _author_citation(extracted))
    _fill_blank(row, "year", extracted.get("publication_year"))
    _fill_blank(row, "publisher", extracted.get("publisher_from_source"))
    _fill_blank(row, "open_access", _open_access_value(extracted))
    _write_article_metadata(cfg, row, extracted)
    return True


def _doi_from_texts(texts: list[str], source: Path) -> tuple[str | None, str]:
    dois = []
    seen = set()
    for text in texts:
        for match in DOI_RE.finditer(text):
            doi = _normalize_doi(match.group(0))
            key = doi.lower()
            if key not in seen:
                seen.add(key)
                dois.append(doi)
    if not dois:
        return None, "missing_doi"
    if len(dois) > 1:
        logger.warning("Multiple DOI candidates found in %s: %s", source, ", ".join(dois))
        return None, "ambiguous_doi"
    return dois[0], "found"


def _doi_from_pdf_text(pdf_path: Path) -> tuple[str | None, str]:
    """Scan PDF metadata and first pages for DOI strings without OCR."""
    import pymupdf

    with pymupdf.open(pdf_path) as doc:
        texts = [str(value) for value in doc.metadata.values() if value]
        texts.extend(doc[index].get_text("text") for index in range(min(DOI_SCAN_PAGES, len(doc))))
    return _doi_from_texts(texts, pdf_path)


def _archive_processed_inbox_pdf(pdf_path: Path) -> None:
    processed_dir = pdf_path.parent / ".processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    target = processed_dir / pdf_path.name
    try:
        if target.exists():
            target.unlink()
        shutil.move(str(pdf_path), str(target))
        logger.info("Archived processed inbox PDF: %s -> %s", pdf_path, target)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("Unable to archive processed inbox PDF: %s", pdf_path)


def _process_inbox_pdf(
    cfg: LitSchemaConfig,
    pdf_path: Path,
    rows: list[dict[str, str]],
    existing_ids: set[str],
) -> tuple[str, str | None, bool]:
    doi, doi_status = _doi_from_pdf_text(pdf_path)
    if not doi:
        return doi_status, None, False

    row = _upsert_doi_row(rows, doi)
    harvested = _populate_row_from_openalex(cfg, row, existing_ids=existing_ids)
    article_id = row.get("article_id")
    if not article_id:
        return "missing_metadata", doi, harvested

    files = article_files(cfg, article_id)
    files.article_dir.mkdir(parents=True, exist_ok=True)
    canonical_pdf_name = f"{article_id}.pdf"
    canonical_pdf = files.pdf
    already_had_pdf = canonical_pdf.exists()

    cache_path = harvest_cache_dir(cfg, "openalex") / f"{openalex_harvest.doi_to_slug(doi)}.json"
    extracted = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    _write_article_metadata(cfg, row, extracted, pdf_filename=canonical_pdf_name)
    if already_had_pdf:
        _archive_processed_inbox_pdf(pdf_path)
        return "already_assembled", doi, harvested

    shutil.copy2(pdf_path, canonical_pdf)
    _archive_processed_inbox_pdf(pdf_path)
    return "assembled", doi, harvested


def assemble(cfg: LitSchemaConfig, reporter: AssembleReporter | None = None) -> dict[str, int]:
    source = registry_path(cfg.data_dir)
    rows = read_article_registry(source)
    cfg.article_store_dir.mkdir(parents=True, exist_ok=True)
    _sync_registry_from_article_metadata(cfg, rows)
    existing_ids = {row["article_id"] for row in rows if row.get("article_id")}
    existing_ids.update(path.name for path in cfg.article_store_dir.glob("*") if path.is_dir())

    stats = {
        "inbox_pdfs": 0,
        "assembled_pdfs": 0,
        "already_assembled_pdfs": 0,
        "missing_doi_pdfs": 0,
        "ambiguous_doi_pdfs": 0,
        "missing_metadata_pdfs": 0,
        "error_pdfs": 0,
        "metadata_only": 0,
        "invalid_doi_rows": 0,
        "missing_metadata_rows": 0,
        "harvested": 0,
    }

    inbox_pdfs = sorted(cfg.paper_inbox_dir.glob("*.pdf")) if cfg.paper_inbox_dir.is_dir() else []
    _report(reporter, "start", inbox_pdfs=len(inbox_pdfs))

    if inbox_pdfs:
        for index, pdf_path in enumerate(inbox_pdfs, start=1):
            stats["inbox_pdfs"] += 1
            _report(reporter, "pdf_start", path=pdf_path, index=index, total=len(inbox_pdfs))
            try:
                result, _doi, harvested = _process_inbox_pdf(cfg, pdf_path, rows, existing_ids)
            except KeyboardInterrupt as exc:
                write_article_registry(source, rows)
                raise AssemblyInterrupted(pdf_path) from exc
            except Exception as exc:
                if _is_wrapped_keyboard_interrupt(exc):
                    write_article_registry(source, rows)
                    raise AssemblyInterrupted(pdf_path) from exc
                logger.exception("Failed to assemble inbox PDF: %s", pdf_path)
                stats["error_pdfs"] += 1
                _report(reporter, "pdf_error", path=pdf_path, error=exc)
                continue
            if harvested:
                stats["harvested"] += 1
            if result == "assembled":
                stats["assembled_pdfs"] += 1
            elif result == "already_assembled":
                stats["already_assembled_pdfs"] += 1
            elif result == "missing_doi":
                stats["missing_doi_pdfs"] += 1
            elif result == "ambiguous_doi":
                stats["ambiguous_doi_pdfs"] += 1
            elif result == "missing_metadata":
                stats["missing_metadata_pdfs"] += 1
            write_article_registry(source, rows)
            _report(reporter, "pdf", path=pdf_path, result=result, doi=_doi, harvested=harvested)

    _report(reporter, "stage", name="registry", total=len(rows))
    for row in rows:
        doi = row.get("doi")
        if not doi:
            if _write_metadata_only_row(cfg, row):
                stats["metadata_only"] += 1
                _report(reporter, "row", row=row, result="metadata_only", harvested=False)
            else:
                stats["missing_metadata_rows"] += 1
                _report(reporter, "row", row=row, result="missing_metadata", harvested=False)
            continue
        if not is_valid_doi(doi):
            if _write_metadata_only_row(cfg, row):
                stats["metadata_only"] += 1
                result = "metadata_only"
            else:
                stats["missing_metadata_rows"] += 1
                result = "invalid_doi"
            stats["invalid_doi_rows"] += 1
            _report(reporter, "row", row=row, result=result, harvested=False)
            continue
        harvested = _populate_row_from_openalex(cfg, row, existing_ids=existing_ids)
        if harvested:
            stats["harvested"] += 1
        article_id = row.get("article_id")
        metadata_exists = bool(article_id and article_files(cfg, article_id).metadata.exists())
        result = "harvested" if harvested else "ok"
        if not harvested and not metadata_exists:
            stats["missing_metadata_rows"] += 1
            result = "missing_metadata"
        _report(
            reporter,
            "row",
            row=row,
            result=result,
            harvested=harvested,
        )

    write_article_registry(source, rows)
    logger.info("Article assembly complete: %s", stats)
    return stats


def main() -> None:
    import argparse

    argparse.ArgumentParser(description="Assemble article inputs from DOI rows and PDF inbox").parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = require_config_or_exit()
    print(json.dumps(assemble(cfg), indent=2))


if __name__ == "__main__":
    main()
