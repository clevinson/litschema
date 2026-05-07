"""Runtime configuration for the ERW meta-analysis pipeline.

Replaces hardcoded ``PROJECT_ROOT = Path(__file__).resolve().parents[N]`` with
a small YAML config loaded at runtime. Foundational prep for open-sourcing:
keeps the package name (``litschema``) intact while making every filesystem
path a single source of truth (``litschema.yaml``).

Lookup order for ``litschema.yaml``:

1. The explicit path passed to :func:`load_config`.
2. The ``LITSCHEMA_CONFIG`` environment variable.
3. A walk upward from the current working directory.
4. A walk upward from this module's file location (fallback for scripts that
   ``cd`` elsewhere before calling us).

All relative paths in the YAML are resolved against the config file's own
directory, so ``data_dir: "data"`` means ``<dir-containing-litschema.yaml>/data``.

Typical usage::

    from litschema.config import load_config
    cfg = load_config()
    md_dir = cfg.fulltext_md_dir   # -> Path

The loader result is cached per resolved path; pass ``reload=True`` to bust.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_FILENAME = "litschema.yaml"
ENV_VAR = "LITSCHEMA_CONFIG"


@dataclass(frozen=True)
class LitSchemaConfig:
    """Resolved path configuration. All ``Path`` fields are absolute."""

    # Where the config file itself lives (useful for sanity checks).
    config_path: Path

    # Core roots.
    project_root: Path
    data_dir: Path
    schema_dir: Path
    references_dir: Path

    # Files.
    tracking_xlsx: Path

    # Stage-numbered subdirectories.
    openalex_dir: Path
    crossref_dir: Path
    fulltext_md_dir: Path
    llm_extractions_dir: Path
    extraction_reasoning_dir: Path
    annotations_dir: Path
    article_store_dir: Path

    # External (typically sibling to project_root).
    papers_dir: Path

    # Build output.
    static_site_dir: Path

    # Raw config dict (in case callers need exotic / future-added fields).
    raw: dict = field(default_factory=dict, repr=False)


def _find_config(start: Path) -> Path | None:
    """Walk upward from ``start`` looking for a litschema.yaml."""
    start = start.resolve()
    for candidate in [start, *start.parents]:
        p = candidate / CONFIG_FILENAME
        if p.is_file():
            return p
    return None


def _resolve_config_path(explicit: Path | str | None) -> Path:
    if explicit is not None:
        p = Path(explicit).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"litschema config not found: {p}")
        return p

    env = os.environ.get(ENV_VAR)
    if env:
        p = Path(env).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"{ENV_VAR} points to missing file: {p}")
        return p

    # Walk up from cwd first (typical invocation case).
    found = _find_config(Path.cwd())
    if found is not None:
        return found

    # Fallback: walk up from this module (for unusual cwd).
    found = _find_config(Path(__file__).parent)
    if found is not None:
        return found

    raise FileNotFoundError(
        f"Could not locate {CONFIG_FILENAME}. Searched upward from cwd "
        f"({Path.cwd()}) and from {Path(__file__).parent}. "
        f"Set {ENV_VAR} or pass an explicit path."
    )


def _resolve_path(value: str, base: Path) -> Path:
    """Resolve ``value`` relative to ``base`` if not absolute."""
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = base / p
    return p.resolve()


# Mapping of config-field name -> (yaml key, default relative path)
_PATH_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("project_root", "project_root", "."),
    ("data_dir", "data_dir", "data"),
    ("schema_dir", "schema_dir", "schema"),
    ("references_dir", "references_dir", "references"),
    ("tracking_xlsx", "tracking_xlsx", "paper_download_tracking.xlsx"),
    ("openalex_dir", "openalex_dir", "data/openalex_raw"),
    ("crossref_dir", "crossref_dir", "data/crossref_raw"),
    ("fulltext_md_dir", "fulltext_md_dir", "data/fulltext_md"),
    ("llm_extractions_dir", "llm_extractions_dir", "data/llm_extractions"),
    (
        "extraction_reasoning_dir",
        "extraction_reasoning_dir",
        "data/extraction_reasoning",
    ),
    ("annotations_dir", "annotations_dir", "data/reviews"),
    ("article_store_dir", "article_store_dir", "data/papers"),
    ("papers_dir", "papers_dir", "papers"),
    ("static_site_dir", "static_site_dir", "static-site"),
)


def _build_config(config_path: Path, raw: dict) -> LitSchemaConfig:
    base = config_path.parent
    # If user overrode project_root, subsequent relative paths should still be
    # resolved against the CONFIG FILE's directory, which is the documented
    # contract. This keeps behaviour predictable.
    kwargs: dict = {"config_path": config_path, "raw": raw}
    for attr, key, default in _PATH_FIELDS:
        value = raw.get(key, default)
        kwargs[attr] = _resolve_path(value, base)

    # Sanity: every dataclass Path field is covered.
    expected = {f.name for f in fields(LitSchemaConfig)} - {"config_path", "raw"}
    missing = expected - set(kwargs.keys())
    if missing:  # pragma: no cover - developer error guard
        raise RuntimeError(f"config loader missing fields: {missing}")

    return LitSchemaConfig(**kwargs)


@lru_cache(maxsize=8)
def _load_cached(config_path: Path) -> LitSchemaConfig:
    with open(config_path) as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{config_path} must be a YAML mapping at top level")
    return _build_config(config_path, raw)


def load_config(
    path: Path | str | None = None,
    *,
    reload: bool = False,
) -> LitSchemaConfig:
    """Load (and cache) the litschema config.

    Parameters
    ----------
    path
        Explicit path to a ``litschema.yaml``. If ``None``, uses the
        ``LITSCHEMA_CONFIG`` env var, else walks upward from cwd, else from
        this module.
    reload
        If True, bypass the cache and re-read the file.
    """
    resolved = _resolve_config_path(path)
    if reload:
        _load_cached.cache_clear()
    return _load_cached(resolved)


__all__ = ["LitSchemaConfig", "load_config", "CONFIG_FILENAME", "ENV_VAR"]
