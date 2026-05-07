from __future__ import annotations

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
    assert generated.read_text() == "{}"
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
    assert calls[1][0][4] == "ExtractionReasoning"
    assert calls[1][0][5] == str(schema_dir / "reasoning.yaml")
