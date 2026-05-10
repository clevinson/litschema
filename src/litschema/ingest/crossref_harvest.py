"""Phase 1b: Supplement missing fields from CrossRef API.

Only queries papers where OpenAlex is missing key fields (abstract, type).
Extracts document type, subject categories, license info.

Usage:
    uv run python -m litschema.ingest.crossref_harvest [--email EMAIL]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from pathlib import Path

import requests

from ..config import LitSchemaConfig, require_config_or_exit
from . import harvest_cache_dir

logger = logging.getLogger(__name__)

CROSSREF_API = "https://api.crossref.org/works"
RATE_LIMIT_DELAY = 0.1  # Be polite


def doi_to_slug(doi: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "_", doi).strip("_").lower()


def needs_crossref(openalex_data: dict) -> bool:
    """Check if a paper needs CrossRef supplementation."""
    if openalex_data.get("error"):
        return True  # OpenAlex didn't find it at all
    if not openalex_data.get("abstract"):
        return True
    return not openalex_data.get("type")


def fetch_crossref(doi: str, email: str | None = None) -> dict | None:
    """Fetch metadata from CrossRef for a single DOI."""
    url = f"{CROSSREF_API}/{doi}"
    params = {}
    if email:
        params["mailto"] = email

    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            return resp.json().get("message", {})
        elif resp.status_code == 404:
            logger.warning("Not found in CrossRef: %s", doi)
            return None
        else:
            logger.error("CrossRef error %d for %s", resp.status_code, doi)
            return None
    except requests.RequestException as e:
        logger.error("Request failed for %s: %s", doi, e)
        return None


def extract_crossref_metadata(raw: dict) -> dict:
    """Extract useful fields from CrossRef response."""
    result = {
        "doi": raw.get("DOI"),
        "type": raw.get("type"),  # journal-article, book-chapter, posted-content, etc.
        "subject": raw.get("subject", []),
        "container_title": raw.get("container-title", [None])[0]
        if raw.get("container-title")
        else None,
        "publisher": raw.get("publisher"),
    }

    # Abstract (CrossRef sometimes has it when OpenAlex doesn't)
    abstract = raw.get("abstract")
    if abstract:
        # CrossRef abstracts often have JATS XML tags - strip them
        abstract = re.sub(r"<[^>]+>", "", abstract).strip()
        result["abstract"] = abstract

    # License info
    licenses = raw.get("license", [])
    if licenses:
        result["license"] = [
            {"url": lic.get("URL"), "content_version": lic.get("content-version")}
            for lic in licenses
        ]

    # Authors (as fallback)
    authors = []
    for author in raw.get("author", []):
        authors.append(
            {
                "given": author.get("given"),
                "family": author.get("family"),
                "orcid": author.get("ORCID", "")
                .replace("http://orcid.org/", "")
                .replace("https://orcid.org/", "")
                or None,
                "sequence": author.get("sequence"),
                "affiliation": [a.get("name") for a in author.get("affiliation", [])],
            }
        )
    if authors:
        result["authors"] = authors

    return result


def harvest(
    cfg: LitSchemaConfig,
    *,
    openalex_dir: Path | None = None,
    crossref_dir: Path | None = None,
    email: str | None = None,
    skip_existing: bool = True,
) -> dict:
    """Run CrossRef harvest for papers needing supplementation."""
    openalex_dir = openalex_dir or harvest_cache_dir(cfg, "openalex")
    crossref_dir = crossref_dir or harvest_cache_dir(cfg, "crossref")
    crossref_dir.mkdir(parents=True, exist_ok=True)

    stats = {"checked": 0, "needs_supplement": 0, "fetched": 0, "skipped": 0, "not_found": 0}

    for json_file in sorted(openalex_dir.glob("*.json")):
        data = json.loads(json_file.read_text())
        stats["checked"] += 1

        doi = data.get("_source_doi") or data.get("doi")
        if not doi:
            continue

        if not needs_crossref(data):
            continue
        stats["needs_supplement"] += 1

        slug = doi_to_slug(doi)
        out_path = crossref_dir / f"{slug}.json"

        if skip_existing and out_path.exists():
            stats["skipped"] += 1
            continue

        raw = fetch_crossref(doi, email=email)
        if raw is None:
            stats["not_found"] += 1
            out_path.write_text(json.dumps({"doi": doi, "error": "not_found"}))
        else:
            extracted = extract_crossref_metadata(raw)
            out_path.write_text(json.dumps(extracted, indent=2, ensure_ascii=False))
            stats["fetched"] += 1

        time.sleep(RATE_LIMIT_DELAY)

    logger.info("CrossRef harvest complete: %s", stats)
    return stats


def main():
    parser = argparse.ArgumentParser(description="Supplement missing metadata from CrossRef")
    parser.add_argument("--email", help="Email for CrossRef polite pool")
    parser.add_argument("--openalex-dir", type=Path, default=None)
    parser.add_argument("--crossref-dir", type=Path, default=None)
    parser.add_argument("--no-skip", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg = require_config_or_exit()
    stats = harvest(
        cfg,
        openalex_dir=args.openalex_dir,
        crossref_dir=args.crossref_dir,
        email=args.email,
        skip_existing=not args.no_skip,
    )
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
