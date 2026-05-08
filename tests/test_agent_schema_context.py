from __future__ import annotations

import json
import sys
from types import SimpleNamespace

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
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        stdout = kwargs.get("stdout")
        if stdout is not None:
            stdout.write("{}")
        return SimpleNamespace(returncode=0)

    generated = tmp_path / ".litschema" / "runtime" / "extraction_schema.json"
    monkeypatch.setattr(prepare_schema_context.subprocess, "run", fake_run)

    context = prepare_schema_context.prepare_schema_context(cfg)

    assert context.extraction_schema_path == generated
    assert context.extraction_root_class == "ClinicalTrialReport"
    assert generated.read_text() == "{}"
    manifest = json.loads(context.manifest_path.read_text())
    assert manifest == {
        "extraction_schema": ".litschema/runtime/extraction_schema.json",
        "extraction_root_class": "ClinicalTrialReport",
        "reasoning_schema": None,
    }
    args, kwargs = calls[0]
    assert args[:4] == ["uv", "run", "gen-json-schema", "--top-class"]
    assert args[4] == "ClinicalTrialReport"
    assert args[5] == str(cfg.schema_dir / "clinical_trial.yaml")
    assert kwargs["cwd"] == cfg.schema_dir


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
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        stdout = kwargs.get("stdout")
        if stdout is not None:
            stdout.write("{}")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(prepare_schema_context.subprocess, "run", fake_run)

    context = prepare_schema_context.prepare_schema_context(cfg)

    assert context.reasoning_schema_path == project / ".litschema" / "runtime" / "reasoning_schema.json"
    assert context.reasoning_schema_path.read_text() == "{}"
    manifest = json.loads((project / ".litschema" / "runtime" / "schema_context.json").read_text())
    assert manifest["extraction_root_class"] == "TestExtraction"
    assert manifest["reasoning_schema"] == ".litschema/runtime/reasoning_schema.json"
    assert calls[1][0][4] == "ExtractionReasoning"
    assert calls[1][0][5] == str(schema_dir / "reasoning.yaml")


def test_validate_reasoning_file_reports_schema_errors(tmp_path) -> None:
    from litschema.agent.validate_reasoning import validate_file

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["fields"],
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["path", "source_lines"],
                    "properties": {
                        "path": {"type": "string"},
                        "source_lines": {"type": "string"},
                    },
                },
            }
        },
    }
    valid = tmp_path / "valid.json"
    valid.write_text('{"fields": [{"path": ".x", "source_lines": "L1"}]}')
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"fields": [{"path": ".x"}], "extra": true}')

    assert validate_file(valid, schema) == (True, [])
    ok, errors = validate_file(invalid, schema)

    assert ok is False
    assert any("'source_lines' is a required property" in error for error in errors)
    assert any("Additional properties are not allowed" in error for error in errors)


def test_validate_reasoning_skips_when_no_reasoning_schema(
    tmp_path, monkeypatch, capsys
) -> None:
    from litschema.agent import validate_reasoning

    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (tmp_path / "litschema.yaml").write_text('project_root: "."\nschema_dir: "schema"\n')
    monkeypatch.setenv("LITSCHEMA_CONFIG", str(tmp_path / "litschema.yaml"))
    monkeypatch.setattr(
        validate_reasoning,
        "prepare_schema_context",
        lambda cfg: SimpleNamespace(reasoning_schema_path=None),
    )
    monkeypatch.setattr(sys, "argv", ["validate_reasoning"])

    validate_reasoning.main()

    assert "No reasoning schema found" in capsys.readouterr().out
