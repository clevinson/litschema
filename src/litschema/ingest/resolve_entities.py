"""Phase 4: Entity resolution and deduplication.

Builds canonical Author and Institution registries from harvested API data.
- Institutions: dedup by ROR ID (primary) + Jaro-Winkler similarity (fallback)
- Authors: dedup by OpenAlex author ID + ORCID matching

Usage:
    uv run python -m litschema.ingest.resolve_entities
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import unicodedata
from pathlib import Path

import jellyfish
import yaml

from ..config import LitSchemaConfig, require_config_or_exit
from . import harvest_cache_dir

logger = logging.getLogger(__name__)

JARO_WINKLER_THRESHOLD = 0.92  # High threshold to avoid false merges


def slugify(name: str) -> str:
    """Convert institution name to a slug ID."""
    # Normalize unicode
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    # Remove articles and common words
    name = name.lower()
    for word in ["the ", "of ", "and ", "for ", "at ", "in "]:
        name = name.replace(word, " ")
    # Keep only alphanumeric and spaces
    name = re.sub(r"[^a-z0-9\s]", "", name)
    # Collapse whitespace and join with underscore
    parts = name.split()
    return "_".join(parts)[:60]


def make_author_id(family_name: str, given_name: str | None, existing_ids: set[str]) -> str:
    """Generate author ID in lastname_f format with collision handling."""
    if not family_name:
        family_name = "unknown"
    family = unicodedata.normalize("NFKD", family_name.lower())
    family = family.encode("ascii", "ignore").decode("ascii")
    family = re.sub(r"[^a-z]", "", family)

    initial = ""
    if given_name:
        given = unicodedata.normalize("NFKD", given_name.lower())
        given = given.encode("ascii", "ignore").decode("ascii")
        given = re.sub(r"[^a-z]", "", given)
        if given:
            initial = f"_{given[0]}"

    base_id = f"{family}{initial}"
    if not base_id:
        base_id = "unknown"

    if base_id not in existing_ids:
        return base_id

    # Handle collisions with numeric suffix
    for i in range(2, 100):
        candidate = f"{base_id}{i}"
        if candidate not in existing_ids:
            return candidate
    return f"{base_id}_x"


def parse_author_name(display_name: str) -> tuple[str, str]:
    """Parse 'Given Family' display name into (family, given)."""
    if not display_name:
        return ("Unknown", "")
    parts = display_name.strip().split()
    if len(parts) == 1:
        return (parts[0], "")
    # Last part is family name (handles multi-word given names)
    return (parts[-1], " ".join(parts[:-1]))


def resolve_institutions(openalex_dir: Path) -> list[dict]:
    """Build canonical institution registry from OpenAlex harvest data."""
    # Collect all institution mentions
    raw_institutions: dict[str, dict] = {}  # ror -> best record
    no_ror: list[dict] = []

    for json_file in sorted(openalex_dir.glob("*.json")):
        data = json.loads(json_file.read_text())
        if data.get("error"):
            continue
        for author in data.get("authors", []):
            for inst in author.get("institutions", []):
                name = inst.get("name")
                ror = inst.get("ror")
                if not name:
                    continue
                if ror:
                    # ROR is canonical key
                    if ror not in raw_institutions:
                        raw_institutions[ror] = {
                            "name": name,
                            "ror_id": ror,
                            "country": inst.get("country_code"),
                        }
                else:
                    no_ror.append(
                        {
                            "name": name,
                            "country": inst.get("country_code"),
                        }
                    )

    # Dedup no-ROR institutions by Jaro-Winkler similarity
    # First, check if any match existing ROR institutions
    ror_names = {v["name"]: k for k, v in raw_institutions.items()}

    unmatched = []
    for inst in no_ror:
        name = inst["name"]
        matched = False
        for existing_name in ror_names:
            sim = jellyfish.jaro_winkler_similarity(name.lower(), existing_name.lower())
            if sim >= JARO_WINKLER_THRESHOLD:
                matched = True
                break
        if not matched:
            unmatched.append(inst)

    # Cluster unmatched institutions by similarity
    clusters: list[list[dict]] = []
    used = set()
    for i, inst in enumerate(unmatched):
        if i in used:
            continue
        cluster = [inst]
        used.add(i)
        for j in range(i + 1, len(unmatched)):
            if j in used:
                continue
            sim = jellyfish.jaro_winkler_similarity(
                inst["name"].lower(), unmatched[j]["name"].lower()
            )
            if sim >= JARO_WINKLER_THRESHOLD:
                cluster.append(unmatched[j])
                used.add(j)
        clusters.append(cluster)

    # Build final institution list
    institutions = []
    used_slugs: set[str] = set()

    # ROR institutions first
    for _ror, inst in sorted(raw_institutions.items(), key=lambda x: x[1]["name"]):
        slug = slugify(inst["name"])
        if slug in used_slugs:
            slug = f"{slug}_{len(used_slugs)}"
        used_slugs.add(slug)
        record = {"id": slug, "name": inst["name"]}
        if inst.get("ror_id"):
            record["ror_id"] = inst["ror_id"]
        if inst.get("country"):
            record["country"] = inst["country"]
        institutions.append(record)

    # Non-ROR clusters
    for cluster in clusters:
        # Use the longest name as canonical
        canonical = max(cluster, key=lambda x: len(x["name"]))
        slug = slugify(canonical["name"])
        if slug in used_slugs:
            slug = f"{slug}_{len(used_slugs)}"
        used_slugs.add(slug)
        record = {"id": slug, "name": canonical["name"]}
        if canonical.get("country"):
            record["country"] = canonical["country"]
        institutions.append(record)

    logger.info(
        "Resolved %d institutions (%d with ROR, %d without)",
        len(institutions),
        len(raw_institutions),
        len(clusters),
    )
    return institutions


def resolve_authors(openalex_dir: Path, institutions: list[dict]) -> list[dict]:
    """Build canonical author registry from OpenAlex data."""
    # Build institution lookup: ROR -> slug ID
    ror_to_id: dict[str, str] = {}
    name_to_id: dict[str, str] = {}
    for inst in institutions:
        if inst.get("ror_id"):
            ror_to_id[inst["ror_id"]] = inst["id"]
        name_to_id[inst["name"].lower()] = inst["id"]

    # Collect all author mentions, keyed by OpenAlex author ID
    raw_authors: dict[str, dict] = {}  # openalex_id -> merged record

    for json_file in sorted(openalex_dir.glob("*.json")):
        data = json.loads(json_file.read_text())
        if data.get("error"):
            continue
        for author in data.get("authors", []):
            oa_id = author.get("openalex_author_id")
            if not oa_id:
                continue
            display_name = author.get("display_name", "")

            if oa_id not in raw_authors:
                family, given = parse_author_name(display_name)
                raw_authors[oa_id] = {
                    "openalex_id": oa_id,
                    "display_name": display_name,
                    "family_name": family,
                    "given_name": given,
                    "orcid": author.get("orcid"),
                    "institution_rors": set(),
                    "institution_names": set(),
                }
            else:
                # Merge: prefer ORCID if we get one
                if author.get("orcid") and not raw_authors[oa_id]["orcid"]:
                    raw_authors[oa_id]["orcid"] = author["orcid"]

            # Collect affiliations
            for inst in author.get("institutions", []):
                if inst.get("ror"):
                    raw_authors[oa_id]["institution_rors"].add(inst["ror"])
                elif inst.get("name"):
                    raw_authors[oa_id]["institution_names"].add(inst["name"])

    # Build final author list
    authors = []
    used_ids: set[str] = set()

    for oa_id, raw in sorted(raw_authors.items(), key=lambda x: x[1]["family_name"].lower()):
        author_id = make_author_id(raw["family_name"], raw["given_name"], used_ids)
        used_ids.add(author_id)

        # Resolve affiliation IDs
        affiliation_ids = []
        for ror in raw["institution_rors"]:
            if ror in ror_to_id:
                affiliation_ids.append(ror_to_id[ror])
        for name in raw["institution_names"]:
            inst_id = name_to_id.get(name.lower())
            if inst_id and inst_id not in affiliation_ids:
                affiliation_ids.append(inst_id)

        record = {
            "id": author_id,
            "family_name": raw["family_name"],
            "given_name": raw["given_name"] or None,
        }
        if raw.get("orcid"):
            record["orcid"] = raw["orcid"]
        if affiliation_ids:
            record["affiliation_ids"] = affiliation_ids

        # Stash OpenAlex ID for article assembly cross-reference
        record["_openalex_id"] = oa_id
        authors.append(record)

    logger.info("Resolved %d unique authors from %d mentions", len(authors), len(raw_authors))
    return authors


def resolve(cfg: LitSchemaConfig) -> tuple[list[dict], list[dict]]:
    """Run full entity resolution. Returns (institutions, authors)."""
    openalex_dir = harvest_cache_dir(cfg, "openalex")
    data_dir = cfg.data_dir
    institutions = resolve_institutions(openalex_dir)
    authors = resolve_authors(openalex_dir, institutions)

    # Save registries
    inst_path = data_dir / "institutions.yaml"
    auth_path = data_dir / "authors.yaml"

    with open(inst_path, "w") as f:
        yaml.dump(institutions, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    with open(auth_path, "w") as f:
        yaml.dump(authors, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    logger.info("Saved %d institutions to %s", len(institutions), inst_path)
    logger.info("Saved %d authors to %s", len(authors), auth_path)

    return institutions, authors


def main():
    argparse.ArgumentParser(description="Resolve and deduplicate authors/institutions").parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = require_config_or_exit()
    resolve(cfg)


if __name__ == "__main__":
    main()
