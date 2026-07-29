"""Smoke tests for litschema.

Thin floor under the package: verify the import graph works, the CLI's
--help exits cleanly, config loads in the repo, and the LinkML schema
parses as YAML. These catch the kind of bug where a rename lands
everything except one import and nobody noticed.

Run:  uv run pytest tests/
"""

from __future__ import annotations

import json
import os
import re
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


def test_project_open_wraps_resolved_config() -> None:
    from litschema.project import Project

    config_path = (
        REPO_ROOT / "tests" / "fixtures" / "projects" / "agriculture_demo" / "litschema.yaml"
    )

    project = Project.open(config_path)

    assert project.config.config_path == config_path
    assert project.article_dir("smith-2024") == project.config.article_store_dir / "smith-2024"


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


def test_verify_command_accepts_port_option(monkeypatch) -> None:
    from litschema import cli
    from litschema.project import Project
    from litschema.webapp import app as webapp

    calls = []
    project = Project.open(
        REPO_ROOT / "tests" / "fixtures" / "projects" / "agriculture_demo" / "litschema.yaml"
    )
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: project)
    monkeypatch.setattr(webapp, "run_app", lambda cfg, *, port: calls.append((cfg, port)))

    result = CliRunner().invoke(cli.app, ["verify", "--port", "8017"])

    assert result.exit_code == 0, result.output
    assert calls == [(project.config, 8017)]


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
    assert "`.litschema/dev-cli`" in extract_skill
    assert "development override" in extract_skill
    assert "never required for normal use" in extract_skill
    assert "set `LITSCHEMA` to `uv run litschema`" in extract_skill
    assert "set `LITSCHEMA` to `litschema`" in extract_skill
    assert "$LITSCHEMA --help" in extract_skill
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


def test_load_config_from_fixture_project() -> None:
    """load_config() can load a standalone litschema project explicitly."""
    from litschema.config import load_config

    cfg = load_config(
        REPO_ROOT / "tests" / "fixtures" / "projects" / "custom_clinical" / "litschema.yaml"
    )
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
    assert cfg.paper_inbox_dir == tmp_path / "papers-inbox"
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

    cfg = load_config(
        REPO_ROOT / "tests" / "fixtures" / "projects" / "custom_clinical" / "litschema.yaml"
    )
    schema_path = extraction_schema_path(cfg)

    assert schema_path.is_file(), f"extraction schema not found at {schema_path}"
    with schema_path.open() as fh:
        parsed = yaml.safe_load(fh)
    assert isinstance(parsed, dict)
    assert "name" in parsed
    assert "classes" in parsed


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_cli_status_exits_zero() -> None:
    """`litschema status` runs end-to-end from a standalone fixture project."""
    fixture = REPO_ROOT / "tests" / "fixtures" / "projects" / "custom_clinical"
    result = subprocess.run(
        ["uv", "run", "litschema", "status"],
        capture_output=True,
        text=True,
        cwd=fixture,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "inbox:" in result.stdout
    assert "runs:" in result.stdout
    assert "active:" in result.stdout


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


def test_status_uses_explicit_config_option(tmp_path: Path, monkeypatch) -> None:
    """Project commands should use the root --config option without chdir/env setup."""
    (tmp_path / "schema").mkdir()
    (tmp_path / "schema" / "erw_articles.yaml").write_text("name: test\nclasses: {}\n")
    (tmp_path / "litschema.yaml").write_text(
        'project_root: "."\n'
        'schema_dir: "schema"\n'
        'extraction_schema_file: "erw_articles.yaml"\n'
        'article_store_dir: "data/papers"\n'
    )
    monkeypatch.delenv("LITSCHEMA_CONFIG", raising=False)

    from litschema.cli import app

    result = CliRunner().invoke(app, ["--config", str(tmp_path / "litschema.yaml"), "status"])

    assert result.exit_code == 0, result.output
    assert f"domain dir:  {tmp_path}" in result.output


def test_prepare_text_calls_python_api_for_one_article(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """`litschema prepare-text <article_id>` should prepare one article."""
    (tmp_path / "litschema.yaml").write_text('project_root: "."\n')
    monkeypatch.delenv("LITSCHEMA_CONFIG", raising=False)

    from litschema import cli
    from litschema.ingest import pdf_to_markdown

    calls = []

    def fake_prepare_text(cfg, *, article_ids=None, inbox_dir=None, output_dir=None, force=False):
        calls.append(
            {
                "config_path": cfg.config_path,
                "article_ids": article_ids,
                "inbox_dir": inbox_dir,
                "output_dir": output_dir,
                "force": force,
            }
        )
        return {"total": 1, "converted": 1, "skipped": 0, "empty": 0, "missing": 0, "errors": 0}

    def fail_subprocess(*args, **kwargs):
        raise AssertionError("litschema prepare-text should call the Python conversion function")

    import subprocess

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    monkeypatch.setattr(pdf_to_markdown, "run", fake_prepare_text)

    result = CliRunner().invoke(
        cli.app,
        [
            "--config",
            str(tmp_path / "litschema.yaml"),
            "prepare-text",
            "smith-2024",
            "--inbox-dir",
            str(tmp_path / "pdfs"),
            "--output-dir",
            str(tmp_path / "markdown"),
            "--force",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        {
            "config_path": tmp_path / "litschema.yaml",
            "article_ids": ["smith-2024"],
            "inbox_dir": tmp_path / "pdfs",
            "output_dir": tmp_path / "markdown",
            "force": True,
        }
    ]
    assert json.loads(result.output) == {
        "total": 1,
        "converted": 1,
        "skipped": 0,
        "empty": 0,
        "missing": 0,
        "errors": 0,
    }


def test_prepare_text_all_calls_python_api_for_every_article(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """`litschema prepare-text --all` should prepare every known article."""
    (tmp_path / "litschema.yaml").write_text('project_root: "."\n')
    monkeypatch.delenv("LITSCHEMA_CONFIG", raising=False)

    from litschema import cli
    from litschema.ingest import pdf_to_markdown

    calls = []

    def fake_prepare_text(cfg, *, article_ids=None, inbox_dir=None, output_dir=None, force=False):
        calls.append(
            {
                "config_path": cfg.config_path,
                "article_ids": article_ids,
                "inbox_dir": inbox_dir,
                "output_dir": output_dir,
                "force": force,
            }
        )
        return {"total": 2, "converted": 2, "skipped": 0, "empty": 0, "missing": 0, "errors": 0}

    monkeypatch.setattr(pdf_to_markdown, "run", fake_prepare_text)

    result = CliRunner().invoke(
        cli.app,
        [
            "--config",
            str(tmp_path / "litschema.yaml"),
            "prepare-text",
            "--all",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        {
            "config_path": tmp_path / "litschema.yaml",
            "article_ids": None,
            "inbox_dir": None,
            "output_dir": None,
            "force": False,
        }
    ]


def test_prepare_text_requires_article_id_or_all(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "litschema.yaml").write_text('project_root: "."\n')
    monkeypatch.delenv("LITSCHEMA_CONFIG", raising=False)

    from litschema import cli

    result = CliRunner().invoke(
        cli.app,
        ["--config", str(tmp_path / "litschema.yaml"), "prepare-text"],
    )

    assert result.exit_code == 2
    assert "Specify an article_id or use --all" in result.output


def test_prepare_text_refuses_article_id_with_all(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "litschema.yaml").write_text('project_root: "."\n')
    monkeypatch.delenv("LITSCHEMA_CONFIG", raising=False)

    from litschema import cli

    result = CliRunner().invoke(
        cli.app,
        ["--config", str(tmp_path / "litschema.yaml"), "prepare-text", "smith-2024", "--all"],
    )

    assert result.exit_code == 2
    assert "Use either article_id or --all, not both" in result.output


def test_verify_calls_webapp_runner_with_explicit_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """`litschema verify` should launch the app in-process with the resolved config."""
    (tmp_path / "litschema.yaml").write_text('project_root: "."\n')
    monkeypatch.delenv("LITSCHEMA_CONFIG", raising=False)

    from litschema import cli
    from litschema.webapp import app as webapp

    calls = []

    def fake_run_app(cfg, *, port):
        calls.append((cfg.config_path, port))

    def fail_subprocess(*args, **kwargs):
        raise AssertionError("litschema verify should call the Python webapp function")

    import subprocess

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    monkeypatch.setattr(webapp, "run_app", fake_run_app)

    result = CliRunner().invoke(
        cli.app,
        ["--config", str(tmp_path / "litschema.yaml"), "verify", "--port", "8123"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [(tmp_path / "litschema.yaml", 8123)]


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

    import subprocess

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    monkeypatch.setattr(validate_extraction, "run", fake_validate)

    result = CliRunner().invoke(cli.app, ["validate"])

    assert result.exit_code == 0, result.output
    assert calls == [([], tmp_path / "litschema.yaml")]


def test_analysis_imports_without_pandas_at_module_scope() -> None:
    """The wheel must import with runtime deps only.

    `litschema.analysis` is a notebook helper and pandas is a development
    dependency, so importing pandas at module scope makes `import
    litschema.analysis` fail in a plain install. A `--help` smoke never reaches
    this module, which is why CI imports the public surface from the wheel.
    """
    source = (REPO_ROOT / "src" / "litschema" / "analysis" / "__init__.py").read_text()

    assert "\nimport pandas as pd" not in source
    assert "def _pandas():" in source
    assert "if TYPE_CHECKING:" in source


def test_ci_imports_the_public_surface_from_the_built_wheel() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "test.yml").read_text()

    assert "uv run pytest" in workflow
    assert "uv run ruff check ." in workflow
    assert "uv build" in workflow
    # --isolated --no-project is what makes the check meaningful: it proves the
    # wheel stands up without the dev group.
    assert "--isolated --no-project" in workflow
    assert "import litschema.analysis" in workflow
    assert "litschema-onboard" in workflow  # bundled skills ship


def test_package_metadata_is_complete_for_a_public_release() -> None:
    """PyPI shows what this declares, and a version cannot be re-uploaded."""
    import tomllib

    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        project = tomllib.load(fh)["project"]

    assert project["license"] == "Apache-2.0"
    assert project["readme"] == "README.md"
    assert project["authors"]
    assert project["classifiers"]
    assert project["urls"]["Repository"].startswith("https://")

    # The dependency rationale comment names the pipeline's steps as its
    # argument against extras, so every verb it cites must still be a real one.
    # Asserting the absence of specific dead names only catches the ones we
    # already thought of — `extract-skill` outlived a `harvest`-only check.
    from typer.main import get_command

    from litschema.cli import app

    verbs = set(get_command(app).commands)
    rationale = re.search(
        r"the pipeline's steps \(([^)]*)\)",
        (REPO_ROOT / "pyproject.toml").read_text(),
        re.DOTALL,
    )
    assert rationale, "the dependency rationale no longer names the pipeline's steps"
    cited = {step.strip() for step in rationale.group(1).replace("\n#", " ").split("/")}
    assert cited <= verbs, f"rationale cites verbs the CLI does not have: {sorted(cited - verbs)}"


def test_publish_workflow_gates_on_tests_and_a_matching_tag() -> None:
    """Parse the trigger; do not grep for it.

    A substring check for 'tags: [\"v*\"]' passed while the trigger was
    manual-only, because the sentence explaining why it is manual-only
    contains that string. Read the parsed `on:` block instead.
    """
    import yaml

    path = REPO_ROOT / ".github" / "workflows" / "publish.yml"
    workflow = path.read_text()
    # PyYAML reads a bare `on:` key as the boolean True (YAML 1.1 truthiness).
    parsed = yaml.safe_load(workflow)
    triggers = parsed.get("on", parsed.get(True))

    # 0.1.0 tags on GitHub without publishing, so a v* tag must NOT fire this.
    assert "workflow_dispatch" in triggers, triggers
    assert "push" not in triggers, f"a tag would fire an unconfigured publish: {triggers}"

    assert "uv run pytest -q" in workflow          # never publish an untested build
    assert "does not match project version" in workflow  # tag/version agreement
    assert "id-token: write" in workflow           # trusted publishing, no stored token
    assert "pypa/gh-action-pypi-publish" in workflow


def test_pdf_converter_is_pinned_to_one_minor() -> None:
    """Conversion output is hashed into run provenance, so it must not drift.

    pymupdf4llm 1.27 -> 1.28 changed the markdown it produces (proper <sup>
    markup, a real H1 title, more table rows). That is an improvement, but it
    means the same PDF converts to different bytes — and `inputs.prepared_text`
    in run.json hashes exactly those bytes. An unbounded requirement would let
    a resolver change every future run's provenance silently.
    """
    import tomllib

    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        deps = tomllib.load(fh)["project"]["dependencies"]

    pin = next(d for d in deps if d.startswith("pymupdf4llm"))
    assert ">=1.28" in pin
    assert "<1.29" in pin
