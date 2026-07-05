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
from ..source_metadata import SOURCE_FIELDS, read_source_metadata, update_source_metadata
from . import harvest_cache_dir

logger = logging.getLogger(__name__)

OPENALEX_API = "https://api.openalex.org/works"
# Rate limit: 10 req/s without polite pool, 100 req/s with mailto
RATE_LIMIT_DELAY = 0.1  # 100 req/s with polite pool


class RegistryUnavailableError(Exception):
    """Transient registry failure (network error, 5xx) — retryable.

    Distinct from a true 404: only a 404 may be cached as ``not_found``;
    transient failures must never leave a marker that would exclude the
    article from future runs.
    """


def _metadata_open_access(value: object) -> bool | None:
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

    The block is the DOI's only home — litschema carries no awareness of
    legacy manifest layouts (alpha policy, specs/README.md); unmigrated
    corpora update their manifests in their own repo.
    """
    candidate = read_source_metadata(manifest).get("doi")
    if candidate and is_valid_doi(str(candidate)):
        return normalize_doi(str(candidate))
    return None


def _enrich_article(cfg: LitSchemaConfig, article_id: str, extracted: dict) -> bool:
    """Replace the block with a locked (``doi``) one built from a fetch result.

    REPLACE, not merge: a ``doi`` block asserts registry origin for every
    field it shows, so registry-absent fields are explicitly cleared —
    leftover guesses or edits must not survive under the verified pill.
    """
    if not extracted.get("openalex_id"):
        return False
    files = article_files(cfg, article_id)
    authors = [
        a.get("display_name") for a in extracted.get("authors") or [] if a.get("display_name")
    ]
    # The record's own doi field can be null/mangled even on a 200; fall back
    # to the DOI the fetch was made with — a locked block must never end up
    # with LESS than the known-good DOI it was synced by.
    doi = extracted.get("doi")
    if not (doi and is_valid_doi(str(doi))):
        doi = extracted.get("_source_doi")
    fields = {
        "doi": normalize_doi(str(doi)) if doi and is_valid_doi(str(doi)) else None,
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
    replacement = {field: fields.get(field) for field in SOURCE_FIELDS}
    update_source_metadata(files, replacement, source="doi")
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
    comes from ``doi`` when given, else the manifest. Atomic: a failed or
    unusable lookup writes nothing at all — no manifest change, no cache
    marker — so sync stays retryable. Returns ``None`` when the registry has
    no usable record for the DOI (permanent until the registry changes);
    raises ``RegistryUnavailableError`` on transient failures (retry later)
    and ``LookupError`` when no DOI is available.
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
    if not _enrich_article(cfg, article_id, extracted):
        return None
    cache_dir = harvest_cache_dir(cfg, "openalex")
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{doi_to_slug(doi)}.json").write_text(
        json.dumps(extracted, indent=2, ensure_ascii=False)
    )
    return read_source_metadata(files.read_metadata())


def fetch_openalex(doi: str, email: str | None = None) -> dict | None:
    """Fetch a single work from OpenAlex by DOI.

    Returns the work on 200 and ``None`` on a true 404; raises
    :class:`RegistryUnavailableError` on network errors and other statuses
    so callers never mistake a transient failure for "not in the registry".
    """
    params = {}
    if email:
        params["mailto"] = email

    url = f"{OPENALEX_API}/doi:{doi}"
    try:
        resp = requests.get(url, params=params, timeout=30)
    except requests.RequestException as e:
        logger.error("Request failed for %s: %s", doi, e)
        raise RegistryUnavailableError(f"OpenAlex request failed for {doi}: {e}") from e
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code == 404:
        logger.warning("Not found in OpenAlex: %s", doi)
        return None
    logger.error("OpenAlex error %d for %s: %s", resp.status_code, doi, resp.text[:200])
    raise RegistryUnavailableError(f"OpenAlex returned {resp.status_code} for {doi}")


def extract_metadata(raw: dict) -> dict:
    """Extract structured metadata from OpenAlex response."""
    result = {
        "openalex_id": raw.get("id"),
        "doi": (raw.get("doi") or "").replace("https://doi.org/", ""),
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

    The DOI is read from the ``source_metadata`` block — there is no
    registry file to author. Raw responses are cached under
    ``.litschema/cache``; with ``skip_existing`` (the default) a cached
    response is applied to the manifest without re-fetching. Returns summary
    stats dict.
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
        "unusable": 0,
        "errors": 0,
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
            elif _enrich_article(cfg, article_id, cached):
                stats["cached"] += 1
            else:
                stats["unusable"] += 1
            continue

        try:
            raw = fetch_openalex(doi, email=email)
        except RegistryUnavailableError:
            # Transient failure: no marker, so the article stays retryable.
            # Keep the rate-limit pause — a 429/5xx burst must not turn into
            # zero-delay hammering for the remaining articles.
            stats["errors"] += 1
            time.sleep(RATE_LIMIT_DELAY)
            continue
        if raw is None:
            stats["not_found"] += 1
            # Save a marker so we don't re-query; the manifest is left alone.
            out_path.write_text(json.dumps({"doi": doi, "error": "not_found"}))
        else:
            extracted = extract_metadata(raw)
            extracted["_source_doi"] = doi
            if _enrich_article(cfg, article_id, extracted):
                # Cache only usable responses (mirrors sync_article): an
                # anomalous 200 is re-fetched next run instead of being
                # permanently counted as unusable from the cache.
                out_path.write_text(json.dumps(extracted, indent=2, ensure_ascii=False))
                stats["fetched"] += 1
            else:
                stats["unusable"] += 1

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
