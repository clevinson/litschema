"""Phase 1a: Harvest structured metadata from OpenAlex API.

Queries OpenAlex for each DOI in data/sources/articles.csv. Extracts authors,
affiliations, ORCIDs, ROR IDs, abstracts, keywords. Saves raw JSON per article.

Usage:
    uv run python -m litschema.ingest.openalex_harvest [--email EMAIL]
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import time
from pathlib import Path

import requests

from ..article_registry import has_article_id, is_valid_doi, normalize_doi
from ..articles import article_files, write_article_metadata
from ..config import LitSchemaConfig, require_config_or_exit
from ..source_metadata import read_source_metadata, update_source_metadata
from . import harvest_cache_dir

logger = logging.getLogger(__name__)

OPENALEX_API = "https://api.openalex.org/works"
# Rate limit: 10 req/s without polite pool, 100 req/s with mailto
RATE_LIMIT_DELAY = 0.1  # 100 req/s with polite pool


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


def _has_metadata_only_fields(row: dict[str, str]) -> bool:
    if not has_article_id(row):
        return False
    if not str(row.get("title") or "").strip():
        return False
    return any(str(row.get(key) or "").strip() for key in ("author_citation", "year", "publisher"))


def doi_to_slug(doi: str) -> str:
    """Convert a DOI to a filesystem-safe slug."""
    return re.sub(r"[^a-zA-Z0-9]", "_", doi).strip("_").lower()


def reconstruct_abstract(inverted_index: dict | None) -> str | None:
    """Reconstruct abstract from OpenAlex inverted index format."""
    if not inverted_index:
        return None
    # inverted_index: {"word": [pos1, pos2, ...], ...}
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort(key=lambda x: x[0])
    return " ".join(word for _, word in word_positions)


def load_dois_from_csv(csv_path: Path) -> list[dict]:
    """Load DOIs and metadata from data/sources/articles.csv."""
    rows = []
    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fieldnames = set(reader.fieldnames or [])
        if "id" in fieldnames and "article_id" not in fieldnames:
            raise ValueError(
                f"{csv_path} uses legacy `id`; rename that column to `article_id`."
            )
        for record in reader:
            doi = record.get("doi")
            record["doi"] = normalize_doi(doi.lstrip("\ufeff")) if doi and doi.strip() else ""
            if any(value not in (None, "") for value in record.values()):
                rows.append(record)
    return rows


def _default_source_path(cfg: LitSchemaConfig) -> Path:
    return cfg.data_dir / "sources" / "articles.csv"


def _article_id_for_row(row: dict, doi: str | None = None) -> str | None:
    explicit = row.get("article_id")
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    if doi and is_valid_doi(doi):
        return doi_to_slug(doi)
    return None


def _write_article_metadata(cfg: LitSchemaConfig, row: dict, extracted: dict) -> bool:
    doi = row.get("doi") or extracted.get("doi")
    article_id = _article_id_for_row(row, str(doi) if doi else None)
    if not article_id:
        return False
    files = article_files(cfg, article_id)
    if read_source_metadata(files.read_metadata()).get("metadata_source") == "manual":
        logger.info("Keeping manual metadata for %s; harvest skipped", article_id)
        return False

    authors = [
        a.get("display_name") for a in extracted.get("authors") or [] if a.get("display_name")
    ]
    fields = {
        "doi": str(doi) if doi and is_valid_doi(str(doi)) else None,
        "title": row.get("title") or extracted.get("title"),
        "abstract": row.get("abstract") or extracted.get("abstract"),
        "year": row.get("year") or extracted.get("publication_year"),
        "journal": row.get("journal") or extracted.get("journal"),
        "publisher": row.get("publisher") or extracted.get("publisher_from_source"),
        "authors": authors or None,
    }
    fields = {key: value for key, value in fields.items() if value not in (None, "")}
    if not fields:
        return False
    source = "openalex" if extracted.get("openalex_id") else "manual"

    identity = {"id": article_id, "doi": fields.get("doi")}
    if row.get("author_citation"):
        identity["author_citation"] = row.get("author_citation")
    open_access = _metadata_open_access(row.get("open_access") or extracted.get("open_access"))
    if open_access is not None:
        identity["open_access"] = open_access
    write_article_metadata(files, identity)
    update_source_metadata(files, fields, source=source)
    return True


def fetch_openalex(doi: str, email: str | None = None) -> dict | None:
    """Fetch a single work from OpenAlex by DOI."""
    params = {}
    if email:
        params["mailto"] = email

    url = f"{OPENALEX_API}/doi:{doi}"
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 404:
            logger.warning("Not found in OpenAlex: %s", doi)
            return None
        else:
            logger.error("OpenAlex error %d for %s: %s", resp.status_code, doi, resp.text[:200])
            return None
    except requests.RequestException as e:
        logger.error("Request failed for %s: %s", doi, e)
        return None


def extract_metadata(raw: dict) -> dict:
    """Extract structured metadata from OpenAlex response."""
    result = {
        "openalex_id": raw.get("id"),
        "doi": raw.get("doi", "").replace("https://doi.org/", ""),
        "title": raw.get("title"),
        "publication_year": raw.get("publication_year"),
        "publication_date": raw.get("publication_date"),
        "type": raw.get("type"),
        "open_access": raw.get("open_access", {}),
    }

    # Abstract
    result["abstract"] = reconstruct_abstract(raw.get("abstract_inverted_index"))

    # Primary location (journal info)
    primary = raw.get("primary_location") or {}
    source = primary.get("source") or {}
    result["journal"] = source.get("display_name")
    result["journal_issn"] = source.get("issn_l")
    result["publisher_from_source"] = source.get("host_organization_name")

    # Authors with affiliations
    authors = []
    for authorship in raw.get("authorships", []):
        author_data = authorship.get("author", {})
        institutions = []
        for inst in authorship.get("institutions", []):
            institutions.append(
                {
                    "name": inst.get("display_name"),
                    "ror": inst.get("ror"),
                    "country_code": inst.get("country_code"),
                    "type": inst.get("type"),
                }
            )
        # Also check raw_affiliation_strings for cases where institution wasn't matched
        raw_affiliations = authorship.get("raw_affiliation_strings", [])

        orcid = author_data.get("orcid")
        if orcid:
            orcid = orcid.replace("https://orcid.org/", "")

        authors.append(
            {
                "openalex_author_id": author_data.get("id"),
                "display_name": author_data.get("display_name"),
                "orcid": orcid,
                "author_position": authorship.get("author_position"),
                "is_corresponding": authorship.get("is_corresponding"),
                "institutions": institutions,
                "raw_affiliation_strings": raw_affiliations,
            }
        )
    result["authors"] = authors

    # Keywords and topics
    result["keywords"] = [kw.get("keyword") for kw in raw.get("keywords", []) if kw.get("keyword")]
    result["topics"] = [
        {"name": t.get("display_name"), "subfield": t.get("subfield", {}).get("display_name")}
        for t in raw.get("topics", [])
    ]

    # Citation info
    result["cited_by_count"] = raw.get("cited_by_count")
    result["referenced_works_count"] = raw.get("referenced_works_count")

    return result


def harvest(
    cfg: LitSchemaConfig,
    *,
    source_path: Path | None = None,
    email: str | None = None,
    skip_existing: bool = True,
) -> dict:
    """Run the full OpenAlex harvest.

    Returns summary stats dict.
    """
    data_dir = harvest_cache_dir(cfg, "openalex")
    data_dir.mkdir(parents=True, exist_ok=True)

    source_path = source_path or _default_source_path(cfg)
    rows = load_dois_from_csv(source_path)
    logger.info("Loaded %d source rows from %s", len(rows), source_path.name)

    stats = {
        "total": len(rows),
        "fetched": 0,
        "skipped": 0,
        "not_found": 0,
        "missing_doi": 0,
        "invalid_doi": 0,
        "missing_metadata": 0,
        "errors": 0,
    }

    for i, row in enumerate(rows):
        doi = row.get("doi") or ""
        if not doi:
            stats["missing_doi"] += 1
            if _has_metadata_only_fields(row):
                _write_article_metadata(cfg, row, {})
            else:
                stats["missing_metadata"] += 1
            logger.info("Skipping OpenAlex harvest for DOI-less row: %s", row.get("article_id"))
            continue
        if not is_valid_doi(doi):
            stats["invalid_doi"] += 1
            if _has_metadata_only_fields(row):
                _write_article_metadata(cfg, row, {})
            else:
                stats["missing_metadata"] += 1
            logger.info("Skipping OpenAlex harvest for invalid DOI row: %s", row.get("article_id"))
            continue

        slug = doi_to_slug(doi)
        out_path = data_dir / f"{slug}.json"

        if skip_existing and out_path.exists():
            existing = json.loads(out_path.read_text())
            if not existing.get("error"):
                _write_article_metadata(cfg, row, existing)
            stats["skipped"] += 1
            continue

        raw = fetch_openalex(doi, email=email)
        if raw is None:
            stats["not_found"] += 1
            # Save a marker so we don't re-query
            out_path.write_text(json.dumps({"doi": doi, "error": "not_found"}))
            _write_article_metadata(cfg, row, {"doi": doi})
        else:
            extracted = extract_metadata(raw)
            extracted["_source_doi"] = doi
            out_path.write_text(json.dumps(extracted, indent=2, ensure_ascii=False))
            _write_article_metadata(cfg, row, extracted)
            stats["fetched"] += 1

        # Progress
        done = stats["fetched"] + stats["not_found"] + stats["skipped"]
        if (done % 50 == 0) or (i == len(rows) - 1):
            logger.info(
                "Progress: %d/%d (fetched=%d, skipped=%d, not_found=%d)",
                done,
                stats["total"],
                stats["fetched"],
                stats["skipped"],
                stats["not_found"],
            )

        time.sleep(RATE_LIMIT_DELAY)

    logger.info("Harvest complete: %s", stats)
    return stats


def main():
    parser = argparse.ArgumentParser(description="Harvest article metadata from OpenAlex")
    parser.add_argument("--email", help="Email for OpenAlex polite pool (recommended)")
    parser.add_argument(
        "--source-file",
        type=Path,
        default=None,
        help="CSV source file with DOI rows (defaults to data/sources/articles.csv)",
    )
    parser.add_argument("--no-skip", action="store_true", help="Re-fetch existing files")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg = require_config_or_exit()
    stats = harvest(
        cfg,
        source_path=args.source_file,
        email=args.email,
        skip_existing=not args.no_skip,
    )
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
