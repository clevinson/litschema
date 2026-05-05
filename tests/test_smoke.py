"""Smoke tests for litschema.

Thin floor under the package: verify the import graph works, the CLI's
--help exits cleanly, config loads in the repo, and the LinkML schema
parses as YAML. These catch the kind of bug where a rename lands
everything except one import and nobody noticed.

Run:  uv run pytest tests/
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_top_level_import() -> None:
    """The package imports cleanly."""
    import litschema  # noqa: F401


def test_config_module_import() -> None:
    """Config module exposes the canonical entry points."""
    from litschema.config import (
        CONFIG_FILENAME,
        ENV_VAR,
        LitSchemaConfig,
        load_config,
    )

    assert CONFIG_FILENAME == "litschema.yaml"
    assert ENV_VAR == "LITSCHEMA_CONFIG"
    assert LitSchemaConfig is not None
    assert callable(load_config)


def test_cli_import() -> None:
    """The typer app is constructed at import time without errors."""
    from litschema.cli import app

    assert app.info.name == "litschema"


def test_cli_help_exits_zero() -> None:
    """`python -m litschema.cli --help` returns 0 and mentions the tagline."""
    result = subprocess.run(
        [sys.executable, "-m", "litschema.cli", "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    # Help text includes at least a couple of the verbs we expect.
    assert "status" in result.stdout
    assert "validate" in result.stdout


def test_load_config_from_repo_root() -> None:
    """load_config() walks up to the repo's litschema.yaml."""
    from litschema.config import load_config

    cfg = load_config()
    assert cfg.config_path.name == "litschema.yaml"
    assert cfg.project_root.is_dir()
    assert cfg.schema_dir.is_dir()


def test_schema_root_is_valid_yaml() -> None:
    """The referenced schema_root file parses as YAML."""
    from litschema.config import load_config

    cfg = load_config()
    schema_root_name = cfg.raw.get("schema_root", "erw_articles.yaml")
    schema_path = cfg.schema_dir / schema_root_name

    assert schema_path.is_file(), f"schema_root not found at {schema_path}"
    with schema_path.open() as fh:
        parsed = yaml.safe_load(fh)
    assert isinstance(parsed, dict)
    assert "name" in parsed
    assert "classes" in parsed


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_cli_status_exits_zero() -> None:
    """`litschema status` runs end-to-end from the repo root."""
    result = subprocess.run(
        ["uv", "run", "litschema", "status"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "papers:" in result.stdout
    assert "extracted:" in result.stdout
