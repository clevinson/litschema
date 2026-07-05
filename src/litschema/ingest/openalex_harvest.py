"""Phase 1a: Harvest structured metadata from OpenAlex API.

Manifest-driven: iterates assembled articles (``data/papers/*/
article-metadata.json``) and queries OpenAlex for every manifest that
carries a DOI. Extracts authors, affiliations, ORCIDs, ROR IDs, abstracts,
keywords. Saves raw JSON per article and writes the provenance-tagged
``source_metadata`` block. Articles whose metadata a human edited
(``metadata_source: manual``) are never touched.

Usage:
    uv run python -m litschema.ingest.openalex_harvest [--email EMAIL]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time

import requests

from ..article_registry import is_valid_doi, normalize_doi
from ..articles import article_files, iter_metadata_paths, write_article_metadata
from ..config import LitSchemaConfig, require_config_or_exit
from ..source_metadata import read_source_metadata, update_source_metadata
from . import harvest_cache_dir

logger = logging.getLogger(__name__)

OPENALEX_API = "https://api.openalex.org/works"
# Rate limit: 10 req/s without polite pool, 100 req/s with mailto
RATE_LIMIT_DELAY = 0.1  # 100 req/s with polite pool


def _metadata_open_access(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict) and "is_oa" in value:
        return bool(value["is_oa"])
    return None


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


def _manifest_doi(manifest: dict) -> str | None:
    """Return the article's DOI from the source_metadata block.

    The block is the single home for the DOI. A top-level ``doi`` is read
    only as a legacy fallback for pre-block manifests (nothing writes it
    anymore); it goes inert as soon as a block carries a DOI.
    """
    block = read_source_metadata(manifest)
    for candidate in (block.get("doi"), manifest.get("doi")):
        if candidate and is_valid_doi(str(candidate)):
            return normalize_doi(str(candidate))
    return None


def _enrich_article(cfg: LitSchemaConfig, article_id: str, extracted: dict) -> bool:
    """Write identity fields and a locked (``doi``) block from a fetch result."""
    if not extracted.get("openalex_id"):
        return False
    files = article_files(cfg, article_id)
    authors = [
        a.get("display_name") for a in extracted.get("authors") or [] if a.get("display_name")
    ]
    doi = extracted.get("doi")
    fields = {
        "doi": str(doi) if doi and is_valid_doi(str(doi)) else None,
        "title": extracted.get("title"),
        "abstract": extracted.get("abstract"),
        "year": extracted.get("publication_year"),
        "journal": extracted.get("journal"),
        "publisher": extracted.get("publisher_from_source"),
        "authors": authors or None,
    }
    fields = {key: value for key, value in fields.items() if value not in (None, "")}
    if not fields:
        return False

    identity = {"id": article_id}
    open_access = _metadata_open_access(extracted.get("open_access"))
    if open_access is not None:
        identity["open_access"] = open_access
    write_article_metadata(files, identity)
    update_source_metadata(files, fields, source="doi")
    return True


def sync_article(
    cfg: LitSchemaConfig,
    article_id: str,
    *,
    doi: str | None = None,
    email: str | None = None,
) -> dict | None:
    """Explicit per-article registry sync — the consent path.

    Fetches the DOI live and overwrites the block WHATEVER its provenance
    (unlike batch harvest, which never touches ``manual``): the caller — a
    verifier button press or CLI invocation — supplies the consent. The DOI
    comes from ``doi`` when given, else the manifest. Atomic with respect to
    the manifest: a failed lookup writes nothing there (only the fetch cache)
    and returns ``None``. Raises ``LookupError`` when no DOI is available.
    """
    files = article_files(cfg, article_id)
    doi = doi or _manifest_doi(files.read_metadata())
    if not doi:
        raise LookupError(f"{article_id} has no DOI to sync from")
    raw = fetch_openalex(doi, email=email)
    if raw is None:
        return None
    extracted = extract_metadata(raw)
    extracted["_source_doi"] = doi
    cache_dir = harvest_cache_dir(cfg, "openalex")
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{doi_to_slug(doi)}.json").write_text(
        json.dumps(extracted, indent=2, ensure_ascii=False)
    )
    if not _enrich_article(cfg, article_id, extracted):
        return None
    return read_source_metadata(files.read_metadata())


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
    email: str | None = None,
    skip_existing: bool = True,
) -> dict:
    """Enrich every assembled article whose manifest carries a DOI.

    The DOI is read from the manifest (identity level, with the
    ``source_metadata`` block as fallback) — there is no registry file to
    author. Raw responses are cached under ``.litschema/cache``; with
    ``skip_existing`` (the default) a cached response is applied to the
    manifest without re-fetching. Returns summary stats dict.
    """
    cache_dir = harvest_cache_dir(cfg, "openalex")
    cache_dir.mkdir(parents=True, exist_ok=True)

    manifests = sorted(iter_metadata_paths(cfg))
    logger.info("Scanning %d assembled article(s)", len(manifests))

    stats = {
        "articles": len(manifests),
        "fetched": 0,
        "cached": 0,
        "not_found": 0,
        "no_doi": 0,
        "manual": 0,
    }

    for metadata_path in manifests:
        article_id = metadata_path.parent.name
        manifest = article_files(cfg, article_id).read_metadata()

        if read_source_metadata(manifest).get("metadata_source") == "manual":
            stats["manual"] += 1
            logger.info("Keeping manual metadata for %s; harvest skipped", article_id)
            continue
        doi = _manifest_doi(manifest)
        if not doi:
            stats["no_doi"] += 1
            logger.info("No DOI for %s; harvest skipped", article_id)
            continue

        out_path = cache_dir / f"{doi_to_slug(doi)}.json"
        if skip_existing and out_path.exists():
            cached = json.loads(out_path.read_text())
            if cached.get("error"):
                stats["not_found"] += 1
            else:
                _enrich_article(cfg, article_id, cached)
                stats["cached"] += 1
            continue

        raw = fetch_openalex(doi, email=email)
        if raw is None:
            stats["not_found"] += 1
            # Save a marker so we don't re-query; the manifest is left alone.
            out_path.write_text(json.dumps({"doi": doi, "error": "not_found"}))
        else:
            extracted = extract_metadata(raw)
            extracted["_source_doi"] = doi
            out_path.write_text(json.dumps(extracted, indent=2, ensure_ascii=False))
            _enrich_article(cfg, article_id, extracted)
            stats["fetched"] += 1

        done = stats["fetched"] + stats["not_found"]
        if done and done % 50 == 0:
            logger.info(
                "Progress: %d/%d (fetched=%d, cached=%d, not_found=%d)",
                done,
                stats["articles"],
                stats["fetched"],
                stats["cached"],
                stats["not_found"],
            )

        time.sleep(RATE_LIMIT_DELAY)

    logger.info("Harvest complete: %s", stats)
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Harvest metadata from OpenAlex for assembled articles with DOIs"
    )
    parser.add_argument("--email", help="Email for OpenAlex polite pool (recommended)")
    parser.add_argument("--no-skip", action="store_true", help="Re-fetch existing files")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg = require_config_or_exit()
    stats = harvest(
        cfg,
        email=args.email,
        skip_existing=not args.no_skip,
    )
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
