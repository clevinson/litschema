"""Runtime configuration for litschema projects.

Each project is configured by a ``litschema.yaml`` file. The loader resolves
project-relative paths once and returns an immutable ``LitSchemaConfig`` whose
path fields are absolute.

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
    article_store = cfg.article_store_dir   # -> Path

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
    project_root: Path = field(metadata={"default_path": "."})
    data_dir: Path = field(metadata={"default_path": "data"})
    schema_dir: Path = field(metadata={"default_path": "schema"})
    references_dir: Path = field(metadata={"default_path": "references"})

    # Files.
    tracking_xlsx: Path = field(metadata={"default_path": "paper_download_tracking.xlsx"})

    article_store_dir: Path = field(metadata={"default_path": "data/papers"})

    # External (typically sibling to project_root).
    papers_dir: Path = field(metadata={"default_path": "papers"})

    # Build output.
    static_site_dir: Path = field(metadata={"default_path": "static-site"})

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


def _build_config(config_path: Path, raw: dict) -> LitSchemaConfig:
    base = config_path.parent
    # If user overrode project_root, subsequent relative paths should still be
    # resolved against the CONFIG FILE's directory, which is the documented
    # contract. This keeps behaviour predictable.
    kwargs: dict = {"config_path": config_path, "raw": raw}
    for config_field in fields(LitSchemaConfig):
        default_path = config_field.metadata.get("default_path")
        if default_path is None:
            continue
        value = raw.get(config_field.name, default_path)
        kwargs[config_field.name] = _resolve_path(value, base)

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


class ConfigNotFoundError(FileNotFoundError):
    """Raised when no ``litschema.yaml`` can be located.

    Subclass of ``FileNotFoundError`` so existing ``except FileNotFoundError``
    handlers keep working. Carries an actionable hint in ``str(exc)``.
    """


_MISSING_CONFIG_HINT = (
    "Run `litschema init <domain-name>` to scaffold a new project, "
    "or cd into an existing one."
)


def require_config(path: Path | str | None = None) -> LitSchemaConfig:
    """Load the config or raise ``ConfigNotFoundError`` with an actionable hint.

    Use this from CLI / ``main()`` entry points so the user gets a single,
    consistent error message instead of either a raw traceback or
    command-specific phrasing.

    The "no config found in this directory tree" hint only applies to the
    auto-discovery case (no explicit path, no env var). For explicit paths
    and ``LITSCHEMA_CONFIG`` mismatches the original ``FileNotFoundError``
    message — which already names the missing file — is preserved.
    """
    try:
        return load_config(path)
    except FileNotFoundError as exc:
        if path is not None or os.environ.get(ENV_VAR):
            raise ConfigNotFoundError(str(exc)) from exc
        raise ConfigNotFoundError(
            f"No {CONFIG_FILENAME} found in this directory tree.\n\n{_MISSING_CONFIG_HINT}"
        ) from exc


def require_config_or_exit(
    path: Path | str | None = None,
    *,
    exit_code: int = 2,
) -> LitSchemaConfig:
    """``require_config`` for plain ``main()`` entry points.

    On missing config, prints the actionable hint to stderr and exits with
    ``exit_code`` (default 2) instead of raising. The CLI uses
    :func:`require_config` directly so it can render the error with typer's
    colored output; module mains use this helper to avoid duplicating the
    same try/except.
    """
    import sys

    try:
        return require_config(path)
    except ConfigNotFoundError as exc:
        print(exc, file=sys.stderr)
        sys.exit(exit_code)


__all__ = [
    "LitSchemaConfig",
    "load_config",
    "require_config",
    "require_config_or_exit",
    "ConfigNotFoundError",
    "CONFIG_FILENAME",
    "ENV_VAR",
]
