"""Canonical CSV registry for article-level metadata and extraction provenance."""

from __future__ import annotations

import csv
import re
from pathlib import Path

ARTICLE_REGISTRY_COLUMNS = (
    "doi",
    "article_id",
    "title",
    "author_citation",
    "year",
    "publisher",
    "open_access",
    "extraction_provider",
    "extraction_model",
    "extraction_date",
    "schema_commit",
)

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


def normalize_doi(doi: str) -> str:
    """Return the canonical DOI string used for registry comparisons."""
    doi = doi.strip().removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    return doi.rstrip(".,;)")


def is_valid_doi(doi: str) -> bool:
    return bool(DOI_RE.match(normalize_doi(doi)))


def has_article_id(row: dict[str, str]) -> bool:
    return bool(str(row.get("article_id") or "").strip())


def normalize_registry_row(**values: object) -> dict[str, str]:
    row = {column: "" for column in ARTICLE_REGISTRY_COLUMNS}
    for key, value in values.items():
        if key in row and value not in (None, ""):
            text = str(value)
            row[key] = normalize_doi(text) if key == "doi" else text
    return row


def read_article_registry(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        if "id" in fieldnames and "article_id" not in fieldnames:
            raise ValueError(
                f"{path} uses legacy column 'id'; rename it to 'article_id' before assembly"
            )
        return [normalize_registry_row(**record) for record in reader]


def write_article_registry(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=ARTICLE_REGISTRY_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(normalize_registry_row(**row))


def registry_path(data_dir: Path) -> Path:
    return data_dir / "sources" / "articles.csv"


def record_extraction_provenance(
    path: Path,
    article_id: str,
    *,
    provider: str | None,
    model: str | None,
    extraction_date: str,
    schema_commit: str | None,
) -> None:
    rows = read_article_registry(path)
    target = None
    for row in rows:
        if row.get("article_id") == article_id:
            target = row
            break
    if target is None:
        raise ValueError(f"article_id not found in registry: {article_id}")

    if provider:
        target["extraction_provider"] = provider
    if model:
        target["extraction_model"] = model
    target["extraction_date"] = extraction_date
    if schema_commit:
        target["schema_commit"] = schema_commit
    write_article_registry(path, rows)
