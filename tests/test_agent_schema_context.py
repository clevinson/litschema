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
        'project_root: "."\n'
        'schema_dir: "schema"\n'
        'extraction_schema_file: "clinical_trial.yaml"\n'
    )
    cfg = load_config(config_path, reload=True)

    def fail_subprocess(*args, **kwargs):
        raise AssertionError("prepare_schema_context should use LinkML Python APIs")

    generated = tmp_path / ".litschema" / "runtime" / "extraction_schema.json"
    monkeypatch.setattr(subprocess, "run", fail_subprocess)

    context = prepare_schema_context.prepare_schema_context(cfg)

    assert context.extraction_schema_path == generated
    assert context.extraction_root_class == "ClinicalTrialReport"
    generated_schema = json.loads(generated.read_text())
    assert "article_id" in generated_schema["$defs"]["ClinicalTrialReport"]["properties"]
    manifest = json.loads(context.manifest_path.read_text())
    assert manifest == {
        "extraction_schema": ".litschema/runtime/extraction_schema.json",
        "extraction_root_class": "ClinicalTrialReport",
        "reasoning_schema": None,
    }


def test_prepare_schema_context_writes_optional_reasoning_schema(tmp_path, monkeypatch) -> None:
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
    (schema_dir / "reasoning.yaml").write_text(
        "id: https://example.org/reasoning\n"
        "name: reasoning\n"
        "classes:\n"
        "  ExtractionReasoning:\n"
        "    tree_root: true\n"
        "    attributes:\n"
        "      fields:\n"
        "        range: string\n"
        "        multivalued: true\n"
    )
    config_path = project / "litschema.yaml"
    config_path.write_text('project_root: "."\nschema_dir: "schema"\n')
    cfg = load_config(config_path, reload=True)

    def fail_subprocess(*args, **kwargs):
        raise AssertionError("prepare_schema_context should use LinkML Python APIs")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)

    context = prepare_schema_context.prepare_schema_context(cfg)

    assert context.reasoning_schema_path == project / ".litschema" / "runtime" / "reasoning_schema.json"
    reasoning_schema = json.loads(context.reasoning_schema_path.read_text())
    assert "ExtractionReasoning" in reasoning_schema["$defs"]
    manifest = json.loads((project / ".litschema" / "runtime" / "schema_context.json").read_text())
    assert manifest["extraction_root_class"] == "TestExtraction"
    assert manifest["reasoning_schema"] == ".litschema/runtime/reasoning_schema.json"


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


def test_validate_reasoning_skips_when_no_reasoning_schema(
    tmp_path, monkeypatch, capsys
) -> None:
    from litschema.agent import validate_reasoning

    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (tmp_path / "litschema.yaml").write_text('project_root: "."\nschema_dir: "schema"\n')
    monkeypatch.setenv("LITSCHEMA_CONFIG", str(tmp_path / "litschema.yaml"))
    monkeypatch.setattr(sys, "argv", ["validate_reasoning"])

    validate_reasoning.main()

    assert "No reasoning schema found" in capsys.readouterr().out


def test_validate_reasoning_fails_missing_explicit_target(
    tmp_path, monkeypatch, capsys
) -> None:
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
