from __future__ import annotations

import shutil
import subprocess
from types import SimpleNamespace

from typer.testing import CliRunner

from litschema.config import load_config

FIXTURES = "tests/fixtures/projects"


def test_validate_generation_uses_configured_schema_and_tree_root(monkeypatch) -> None:
    from litschema.ingest import validate_extraction

    cfg = load_config("tests/fixtures/projects/custom_clinical/litschema.yaml", reload=True)
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"type": "object"}', stderr="")

    monkeypatch.setattr(validate_extraction.subprocess, "run", fake_run)

    schema = validate_extraction.generate_extraction_schema(cfg)

    assert schema == {"type": "object"}
    args, kwargs = calls[0]
    assert args[:4] == ["uv", "run", "gen-json-schema", "--top-class"]
    assert args[4] == "ClinicalTrialReport"
    assert args[5] == str(cfg.schema_dir / "clinical_trial.yaml")
    assert kwargs["cwd"] == cfg.schema_dir


def test_schema_command_is_not_part_of_public_cli() -> None:
    from litschema import cli

    result = CliRunner().invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    assert " schema " not in result.output


def test_validate_cli_runs_against_configured_fixture_projects() -> None:
    if shutil.which("uv") is None:
        return

    for fixture in ("agriculture_demo", "custom_clinical"):
        result = subprocess.run(
            ["uv", "run", "litschema", "validate"],
            cwd=f"{FIXTURES}/{fixture}",
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, result.stderr
