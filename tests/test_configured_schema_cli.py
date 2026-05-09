from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from litschema.config import load_config

FIXTURES = "tests/fixtures/projects"


def test_validate_generation_uses_configured_schema_and_tree_root(monkeypatch) -> None:
    from litschema.ingest import validate_extraction

    cfg = load_config("tests/fixtures/projects/custom_clinical/litschema.yaml", reload=True)

    def fail_subprocess(*args, **kwargs):
        raise AssertionError("schema generation should use LinkML Python APIs")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)

    schema = validate_extraction.generate_extraction_schema(cfg)

    assert "ClinicalTrialReport" in schema["$defs"]
    assert schema["$defs"]["ClinicalTrialReport"]["required"] == [
        "article_id",
        "primary_endpoint",
    ]


def test_validate_file_uses_linkml_schema_directly(tmp_path) -> None:
    from litschema.ingest.validate_extraction import validate_file

    cfg = load_config("tests/fixtures/projects/custom_clinical/litschema.yaml", reload=True)
    valid = cfg.llm_extractions_dir / "garcia-2024.json"
    invalid = tmp_path / "invalid-missing-required.json"
    invalid.write_text('{"article_id": "invalid"}')
    extra = tmp_path / "invalid-extra-property.json"
    extra.write_text('{"article_id": "extra", "primary_endpoint": "yield", "unexpected": true}')

    assert validate_file(valid, cfg.schema_dir / "clinical_trial.yaml", "ClinicalTrialReport") == (
        True,
        [],
    )
    ok, errors = validate_file(
        invalid, cfg.schema_dir / "clinical_trial.yaml", "ClinicalTrialReport"
    )

    assert ok is False
    assert any("primary_endpoint" in error for error in errors)

    ok, errors = validate_file(extra, cfg.schema_dir / "clinical_trial.yaml", "ClinicalTrialReport")
    assert ok is False
    assert any("unexpected" in error for error in errors)


def test_validate_run_reuses_linkml_validator(tmp_path, monkeypatch) -> None:
    from litschema.ingest import validate_extraction

    cfg = load_config("tests/fixtures/projects/custom_clinical/litschema.yaml", reload=True)
    files = []
    for index in range(2):
        path = tmp_path / f"valid-{index}.json"
        path.write_text(json.dumps({"article_id": f"valid-{index}", "primary_endpoint": "yield"}))
        files.append(path)

    class FakeValidator:
        def __init__(self) -> None:
            self.calls = 0

        def validate(self, data: dict) -> list[str]:
            self.calls += 1
            return []

    fake_validator = FakeValidator()
    created = []

    def create_validator(schema_path, target_class):
        created.append((schema_path, target_class))
        return fake_validator

    monkeypatch.setattr(validate_extraction, "_files_for_args", lambda args, cfg: files)
    monkeypatch.setattr(validate_extraction, "create_linkml_validator", create_validator)

    assert validate_extraction.run([], cfg) == 0
    assert created == [(cfg.schema_dir / "clinical_trial.yaml", "ClinicalTrialReport")]
    assert fake_validator.calls == 2


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


def test_validate_extraction_fails_missing_explicit_target(tmp_path, monkeypatch, capsys) -> None:
    from litschema.ingest import validate_extraction

    (tmp_path / "schema").mkdir()
    (tmp_path / "litschema.yaml").write_text('project_root: "."\nschema_dir: "schema"\n')
    missing = tmp_path / "data" / "papers" / "missing" / "agent-extraction.json"
    monkeypatch.setenv("LITSCHEMA_CONFIG", str(tmp_path / "litschema.yaml"))
    monkeypatch.setattr(sys, "argv", ["validate_extraction", str(missing)])

    with pytest.raises(SystemExit) as exc:
        validate_extraction.main()

    assert exc.value.code == 1
    assert f"Missing extraction target: {missing}" in capsys.readouterr().out
