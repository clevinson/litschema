"""ERW Research data ingestion pipeline.

Pipeline phases:
  01_openalex_harvest    - Fetch structured metadata from OpenAlex API
  02_crossref_harvest    - Supplement missing fields from CrossRef
  04_pdf_to_markdown     - Convert PDFs to markdown (pymupdf4llm)
  06_resolve_entities    - Deduplicate authors and institutions
  09_llm_extraction      - Extract non-bibliographic fields (via agent skill)
"""

from __future__ import annotations

from pathlib import Path

from ..config import LitSchemaConfig


def harvest_cache_dir(cfg: LitSchemaConfig, source: str) -> Path:
    """Return the on-disk cache for a bibliographic source's raw API responses.

    Raw OpenAlex/CrossRef dumps are regeneratable from the upstream APIs and
    contain no information not also captured in per-article metadata or the
    canonical ``authors.yaml`` / ``institutions.yaml`` registries. They live
    under ``.litschema/cache/`` (gitignored) rather than ``data/`` so the
    user's curated data stays distinct from tool-built cache.
    """
    return cfg.project_root / ".litschema" / "cache" / source
