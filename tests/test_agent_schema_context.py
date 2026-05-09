from __future__ import annotations

import json
import subprocess
import sys

import pytest

from litschema.config import load_config


def test_prepare_schema_context_writes_runtime_extraction_schema(tmp_path, monkeypatch) -> None:
    from litschema.agent import prepare_schema_context

    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (schema_dir / "clinical_trial.yaml").write_text(
        "id: https://example.org/clinical\n"
        "name: clinical\n"
        "classes:\n"
        "  ClinicalTrialReport:\n"
        "    tree_root: true\n"
        "    attributes:\n"
        "      article_id:\n"
        "        range: string\n"
    )
    config_path = tmp_path / "litschema.yaml"
    config_path.write_text(
        'project_root: "."\nschema_dir: "schema"\nextraction_schema_file: "clinical_trial.yaml"\n'
    )
    cfg = load_config(config_path, reload=True)

    def fail_subprocess(*args, **kwargs):
        raise AssertionError("prepare_schema_context should use LinkML Python APIs")

    generated = tmp_path / ".litschema" / "runtime" / "extraction_schema.json"
    stale_manifest = tmp_path / ".litschema" / "runtime" / "schema_context.json"
    stale_manifest.parent.mkdir(parents=True)
    stale_manifest.write_text("{}")
    monkeypatch.setattr(subprocess, "run", fail_subprocess)

    context = prepare_schema_context.prepare_schema_context(cfg)

    assert context.extraction_schema_path == generated
    generated_schema = json.loads(generated.read_text())
    assert "article_id" in generated_schema["$defs"]["ClinicalTrialReport"]["properties"]
    assert not stale_manifest.exists()
    assert (tmp_path / ".litschema" / "runtime" / "reasoning_schema.json").is_file()


def test_prepare_schema_context_writes_bundled_reasoning_schema(tmp_path, monkeypatch) -> None:
    from litschema.agent import prepare_schema_context

    project = tmp_path
    schema_dir = project / "schema"
    schema_dir.mkdir()
    (schema_dir / "extraction.yaml").write_text(
        "id: https://example.org/test\n"
        "name: test\n"
        "classes:\n"
        "  TestExtraction:\n"
        "    tree_root: true\n"
        "    attributes:\n"
        "      article_id:\n"
        "        range: string\n"
    )
    config_path = project / "litschema.yaml"
    config_path.write_text('project_root: "."\nschema_dir: "schema"\n')
    cfg = load_config(config_path, reload=True)

    def fail_subprocess(*args, **kwargs):
        raise AssertionError("prepare_schema_context should use LinkML Python APIs")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)

    context = prepare_schema_context.prepare_schema_context(cfg)

    assert (
        context.reasoning_schema_path
        == project / ".litschema" / "runtime" / "reasoning_schema.json"
    )
    reasoning_schema = json.loads(context.reasoning_schema_path.read_text())
    assert "ExtractionReasoning" in reasoning_schema["$defs"]
    assert "ReasoningField" in reasoning_schema["$defs"]
    assert not (project / ".litschema" / "runtime" / "schema_context.json").exists()


def test_runtime_json_schema_writes_are_atomic(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from litschema import schema_validation

    monkeypatch.setattr(
        schema_validation,
        "generate_json_schema",
        lambda schema_path, top_class: {"title": top_class},
    )

    replacements = []
    original_replace = Path.replace

    def record_replace(self: Path, target: Path) -> Path:
        replacements.append((self, Path(target), self.exists()))
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", record_replace)
    output_path = tmp_path / "runtime" / "extraction_schema.json"

    schema_validation.write_json_schema(tmp_path / "schema.yaml", "RootClass", output_path)

    assert json.loads(output_path.read_text()) == {"title": "RootClass"}
    assert len(replacements) == 1
    temp_path, replaced_path, temp_existed = replacements[0]
    assert replaced_path == output_path
    assert temp_path.parent == output_path.parent
    assert temp_path.name.startswith(".extraction_schema.json.")
    assert temp_path.name.endswith(".tmp")
    assert temp_existed is True
    assert not list(output_path.parent.glob("*.tmp"))


def test_validate_reasoning_file_reports_schema_errors(tmp_path) -> None:
    from litschema.agent.validate_reasoning import validate_file

    schema_path = tmp_path / "reasoning.yaml"
    schema_path.write_text(
        "id: https://example.org/reasoning\n"
        "name: reasoning\n"
        "default_range: string\n"
        "classes:\n"
        "  ExtractionReasoning:\n"
        "    tree_root: true\n"
        "    attributes:\n"
        "      fields:\n"
        "        range: ReasoningField\n"
        "        multivalued: true\n"
        "  ReasoningField:\n"
        "    attributes:\n"
        "      path:\n"
        "        required: true\n"
        "      source_lines:\n"
        "        required: true\n"
    )
    valid = tmp_path / "valid.json"
    valid.write_text('{"fields": [{"path": ".x", "source_lines": "L1"}]}')
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"fields": [{"path": ".x"}], "extra": true}')

    assert validate_file(valid, schema_path) == (True, [])
    ok, errors = validate_file(invalid, schema_path)

    assert ok is False
    assert any("source_lines" in error for error in errors)
    assert any("extra" in error for error in errors)


def test_validate_reasoning_uses_bundled_schema_when_project_schema_absent(
    tmp_path, capsys
) -> None:
    from litschema.agent import validate_reasoning

    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (tmp_path / "litschema.yaml").write_text('project_root: "."\nschema_dir: "schema"\n')
    cfg = load_config(tmp_path / "litschema.yaml", reload=True)
    reasoning = tmp_path / "agent-reasoning.json"
    reasoning.write_text(
        json.dumps(
            {
                "fields": [
                    {
                        "path": ".study_type",
                        "value": "field trial",
                        "source_lines": "L12-L14",
                        "reasoning": "The cited lines describe a field trial.",
                    }
                ]
            }
        )
    )

    assert validate_reasoning.run([str(reasoning)], cfg) == 0
    assert "Reasoning: 1/1 valid" in capsys.readouterr().out


def test_bundled_reasoning_schema_is_packaged() -> None:
    from litschema.agent.reasoning_schema import reasoning_schema_source_path

    schema_path = reasoning_schema_source_path()

    assert schema_path.name == "reasoning.yaml"
    assert schema_path.is_file()
    assert "ExtractionReasoning" in schema_path.read_text()


def test_validate_reasoning_fails_when_no_reasoning_files(tmp_path, monkeypatch, capsys) -> None:
    from litschema.agent import validate_reasoning

    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (tmp_path / "litschema.yaml").write_text('project_root: "."\nschema_dir: "schema"\n')
    monkeypatch.setenv("LITSCHEMA_CONFIG", str(tmp_path / "litschema.yaml"))
    monkeypatch.setattr(sys, "argv", ["validate_reasoning"])

    with pytest.raises(SystemExit) as exc:
        validate_reasoning.main()

    assert exc.value.code == 1
    assert "No reasoning files found" in capsys.readouterr().out


def test_validate_reasoning_fails_missing_explicit_target(tmp_path, monkeypatch, capsys) -> None:
    from litschema.agent import validate_reasoning

    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (tmp_path / "litschema.yaml").write_text('project_root: "."\nschema_dir: "schema"\n')
    missing = tmp_path / "data" / "papers" / "missing" / "agent-reasoning.json"
    monkeypatch.setenv("LITSCHEMA_CONFIG", str(tmp_path / "litschema.yaml"))
    monkeypatch.setattr(sys, "argv", ["validate_reasoning", str(missing)])

    with pytest.raises(SystemExit) as exc:
        validate_reasoning.main()

    assert exc.value.code == 1
    assert f"Missing reasoning target: {missing}" in capsys.readouterr().out


def test_agent_prepare_schema_context_cli_command(monkeypatch) -> None:
    from typer.testing import CliRunner

    from litschema import cli

    cfg_path = "tests/fixtures/projects/custom_clinical/litschema.yaml"
    monkeypatch.setenv("LITSCHEMA_CONFIG", cfg_path)

    result = CliRunner().invoke(cli.app, ["agent", "prepare-schema-context"])

    assert result.exit_code == 0, result.output
    assert "extraction_schema=" in result.output
    assert "reasoning_schema=" in result.output
    assert "schema_context=" not in result.output
    assert "extraction_root_class=" not in result.output


def test_agent_validate_reasoning_cli_command_without_reasoning_files(monkeypatch) -> None:
    from typer.testing import CliRunner

    from litschema import cli

    cfg_path = "tests/fixtures/projects/custom_clinical/litschema.yaml"
    monkeypatch.setenv("LITSCHEMA_CONFIG", cfg_path)

    result = CliRunner().invoke(cli.app, ["agent", "validate-reasoning"])

    assert result.exit_code == 1, result.output
    assert "No reasoning files found" in result.output
