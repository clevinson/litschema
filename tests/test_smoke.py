"""Smoke tests for litschema.

Thin floor under the package: verify the import graph works, the CLI's
--help exits cleanly, config loads in the repo, and the LinkML schema
parses as YAML. These catch the kind of bug where a rename lands
everything except one import and nobody noticed.

Run:  uv run pytest tests/
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

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


def test_validate_extraction_import_does_not_load_project_config(tmp_path: Path) -> None:
    """Importing validation helpers should not require a discoverable litschema.yaml."""
    env = os.environ.copy()
    env.pop("LITSCHEMA_CONFIG", None)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")

    result = subprocess.run(
        [sys.executable, "-c", "import litschema.ingest.validate_extraction"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr


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
    assert "extract" in result.stdout


def test_extract_command_is_explicitly_unsupported() -> None:
    """`litschema extract` is discoverable but points users to agent skills for now."""
    from litschema import cli

    result = CliRunner().invoke(cli.app, ["extract"])

    assert result.exit_code == 2, result.output
    assert "not yet supported" in result.output
    assert "litschema skills install" in result.output
    assert "/extract-article <article-id>" in result.output


def test_no_old_aggregate_surface_remains() -> None:
    """Public litschema code should not carry the old aggregate workflow."""
    checked_roots = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "pyproject.toml",
        REPO_ROOT / "src",
        REPO_ROOT / "skills",
    ]
    forbidden = "co" + "rpus"
    offenders = []
    for root in checked_roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            if not path.is_file() or path.suffix in {".pyc", ".png", ".pdf"}:
                continue
            text = path.read_text(errors="ignore").lower()
            if forbidden in text:
                offenders.append(path.relative_to(REPO_ROOT))

    assert offenders == []


def test_bundled_skills_use_runtime_schemas() -> None:
    """Agent skills should use runtime JSON Schemas, not root-level artifacts."""
    extract_skill = (REPO_ROOT / "skills" / "extract-article" / "SKILL.md").read_text()

    assert "Before running extraction, verify you are in a litschema project" in extract_skill
    assert "Do not assume `uv` or `litschema` is available" in extract_skill
    assert "If `litschema.yaml` is missing" in extract_skill
    assert "set `LITSCHEMA` to `uv run litschema`" in extract_skill
    assert "set `LITSCHEMA` to `litschema`" in extract_skill
    assert "$LITSCHEMA agent prepare-schema-context" in extract_skill
    assert "$LITSCHEMA agent validate-reasoning" in extract_skill
    assert ".litschema/runtime/extraction_schema.json" in extract_skill
    assert "do not infer a different root from `$defs`" in extract_skill
    assert "Omit this key when the source lines are self-explanatory" in extract_skill
    assert "Set to `null`" not in extract_skill
    assert "A file is valid only if the corresponding command exits 0" in extract_skill
    assert "Do NOT finish until both validation commands exit 0" in extract_skill
    assert "`extraction_schema.json`" not in extract_skill
    assert "`reasoning_schema.json`" not in extract_skill


def test_load_config_from_repo_root() -> None:
    """load_config() walks up to the repo's litschema.yaml."""
    from litschema.config import load_config

    cfg = load_config()
    assert cfg.config_path.name == "litschema.yaml"
    assert cfg.project_root.is_dir()
    assert cfg.schema_dir.is_dir()


def test_load_config_resolves_default_paths_from_dataclass_metadata(tmp_path: Path) -> None:
    """Missing path keys should use the defaults declared on LitSchemaConfig."""
    from litschema.config import load_config

    config_path = tmp_path / "litschema.yaml"
    config_path.write_text("{}\n")

    cfg = load_config(config_path, reload=True)

    assert cfg.project_root == tmp_path
    assert cfg.data_dir == tmp_path / "data"
    assert cfg.schema_dir == tmp_path / "schema"
    assert cfg.references_dir == tmp_path / "references"
    assert cfg.tracking_xlsx == tmp_path / "paper_download_tracking.xlsx"
    assert cfg.article_store_dir == tmp_path / "data" / "papers"
    assert cfg.papers_dir == tmp_path / "papers"
    assert cfg.static_site_dir == tmp_path / "static-site"


def test_load_config_resolves_overrides_relative_to_config_file(tmp_path: Path) -> None:
    """Relative overrides should continue to resolve from litschema.yaml."""
    from litschema.config import load_config

    config_path = tmp_path / "nested" / "litschema.yaml"
    config_path.parent.mkdir()
    config_path.write_text('data_dir: "custom-data"\n')

    cfg = load_config(config_path, reload=True)

    assert cfg.project_root == config_path.parent
    assert cfg.data_dir == config_path.parent / "custom-data"


def test_extraction_schema_resolves_to_valid_yaml() -> None:
    """The configured extraction schema file parses as YAML."""
    from litschema.config import load_config
    from litschema.schema_resolution import extraction_schema_path

    schema_path = extraction_schema_path(load_config())

    assert schema_path.is_file(), f"extraction schema not found at {schema_path}"
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


def test_status_uses_per_article_store(tmp_path: Path, monkeypatch) -> None:
    """Per-article projects should not need any aggregate artifact."""
    (tmp_path / "schema").mkdir()
    (tmp_path / "schema" / "erw_articles.yaml").write_text("name: test\nclasses: {}\n")
    paper_dir = tmp_path / "data" / "papers" / "smith-2024"
    paper_dir.mkdir(parents=True)
    (paper_dir / "agent-extraction.json").write_text('{"article_id": "smith-2024"}')
    (tmp_path / "litschema.yaml").write_text(
        'project_root: "."\n'
        'schema_dir: "schema"\n'
        'extraction_schema_file: "erw_articles.yaml"\n'
        'article_store_dir: "data/papers"\n'
    )
    monkeypatch.setenv("LITSCHEMA_CONFIG", str(tmp_path / "litschema.yaml"))

    from litschema.cli import app

    result = CliRunner().invoke(app, ["status"])

    assert result.exit_code == 0, result.output
    assert "[FAIL]" not in result.output


def test_validate_defaults_to_article_store(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """`litschema validate` should target per-article extraction files."""
    (tmp_path / "schema").mkdir()
    (tmp_path / "schema" / "erw_articles.yaml").write_text("name: test\nclasses: {}\n")
    paper_dir = tmp_path / "data" / "papers" / "smith-2024"
    paper_dir.mkdir(parents=True)
    (paper_dir / "agent-extraction.json").write_text('{"article_id": "smith-2024"}')
    (tmp_path / "litschema.yaml").write_text(
        'project_root: "."\n'
        'schema_dir: "schema"\n'
        'extraction_schema_file: "erw_articles.yaml"\n'
        'article_store_dir: "data/papers"\n'
    )
    monkeypatch.setenv("LITSCHEMA_CONFIG", str(tmp_path / "litschema.yaml"))

    from litschema import cli
    from litschema.ingest import validate_extraction

    calls = []

    def fake_validate(args, cfg):
        calls.append((args, cfg.config_path))
        return 0

    def fail_subprocess(*args, **kwargs):
        raise AssertionError("litschema validate should call the Python validation function")

    monkeypatch.setattr(cli.subprocess, "run", fail_subprocess)
    monkeypatch.setattr(validate_extraction, "run", fake_validate)

    result = CliRunner().invoke(cli.app, ["validate"])

    assert result.exit_code == 0, result.output
    assert calls == [([], tmp_path / "litschema.yaml")]
