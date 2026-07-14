"""Data ingestion modules.

  article_assembly   - deterministic local-first PDF intake
  pdf_to_markdown    - prepare article markdown from PDFs (pymupdf4llm)
  openalex_harvest   - registry enrichment by DOI (`meta sync [--all]`)
  validate_extraction- validate per-article extraction JSON
"""

from __future__ import annotations

from pathlib import Path

from ..config import LitSchemaConfig


def harvest_cache_dir(cfg: LitSchemaConfig, source: str) -> Path:
    """Return the on-disk cache for a bibliographic source's raw API responses.

    Raw registry dumps are regeneratable from the upstream APIs and contain
    no information not also captured in per-article metadata. They live
    under ``.litschema/cache/`` (gitignored) rather than ``data/`` so the
    user's curated data stays distinct from tool-built cache.
    """
    return cfg.project_root / ".litschema" / "cache" / source
