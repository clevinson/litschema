from __future__ import annotations

from pathlib import Path

from litschema import schema_resolution
from litschema.config import load_config


def test_resolve_extraction_schema_uses_tree_root_only(tmp_path) -> None:
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (schema_dir / "extraction.yaml").write_text(
        "id: https://example.org/test\n"
        "name: test\n"
        "classes:\n"
        "  ActualRoot:\n"
        "    tree_root: true\n"
        "    attributes:\n"
        "      article_id:\n"
        "        range: string\n"
        "  SecondaryClass:\n"
        "    attributes:\n"
        "      article_id:\n"
        "        range: string\n"
    )
    config_path = tmp_path / "litschema.yaml"
    config_path.write_text('project_root: "."\nschema_dir: "schema"\n')
    cfg = load_config(config_path, reload=True)

    resolved = schema_resolution.resolve_extraction_schema(cfg)

    assert resolved.path == schema_dir / "extraction.yaml"
    assert resolved.root_class == "ActualRoot"


def test_resolve_extraction_schema_returns_view_and_root() -> None:
    cfg = load_config("tests/fixtures/projects/custom_clinical/litschema.yaml", reload=True)

    resolved = schema_resolution.resolve_extraction_schema(cfg)

    assert resolved.root_class == "ClinicalTrialReport"
    assert "primary_endpoint" in [
        slot.name for slot in resolved.view.class_induced_slots(resolved.root_class)
    ]


# ── silent identifier-reference detection ────────────────────────────────────


def _schema_view(tmp_path, body: str):
    from linkml_runtime.utils.schemaview import SchemaView

    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "s.yaml"
    path.write_text(
        "id: https://example.org/t\nname: t\nprefixes:\n  linkml: https://w3id.org/linkml/\n"
        "imports: [linkml:types]\ndefault_range: string\nclasses:\n" + body
    )
    return SchemaView(str(path))


def test_identifier_reference_slot_is_reported_when_detail_would_be_lost(tmp_path) -> None:
    from litschema.schema_resolution import identifier_reference_slots

    view = _schema_view(
        tmp_path,
        """  Study:
    tree_root: true
    attributes:
      article_id:
        identifier: true
      arms:
        range: Arm
        multivalued: true
  Arm:
    attributes:
      arm_id:
        identifier: true
      practice: {}
      is_control:
        range: boolean
""",
    )

    findings = identifier_reference_slots(view, "Study")

    assert len(findings) == 1
    assert findings[0]["slot"] == "arms"
    assert findings[0]["range"] == "Arm"
    assert findings[0]["identifier"] == "arm_id"
    assert findings[0]["lost"] == ["is_control", "practice"]


def test_identifier_reference_slot_is_silent_when_nothing_is_lost(tmp_path) -> None:
    """An id-only range class loses nothing, and inlining opts out entirely."""
    from litschema.schema_resolution import identifier_reference_slots

    id_only = _schema_view(
        tmp_path / "a",
        """  Study:
    tree_root: true
    attributes:
      article_id:
        identifier: true
      arms:
        range: Arm
        multivalued: true
  Arm:
    attributes:
      arm_id:
        identifier: true
""",
    )
    assert identifier_reference_slots(id_only, "Study") == []

    inlined = _schema_view(
        tmp_path / "b",
        """  Study:
    tree_root: true
    attributes:
      article_id:
        identifier: true
      arms:
        range: Arm
        multivalued: true
        inlined_as_list: true
  Arm:
    attributes:
      arm_id:
        identifier: true
      practice: {}
""",
    )
    assert identifier_reference_slots(inlined, "Study") == []


def test_identifier_reference_detection_skips_classes_without_identifiers(tmp_path) -> None:
    """A range class with no identifier inlines by default — nothing to warn about."""
    from litschema.schema_resolution import identifier_reference_slots

    view = _schema_view(
        tmp_path,
        """  Study:
    tree_root: true
    attributes:
      article_id:
        identifier: true
      readings:
        range: Reading
        multivalued: true
  Reading:
    attributes:
      value:
        range: float
      unit: {}
""",
    )
    assert identifier_reference_slots(view, "Study") == []


# ── doctor's behaviour when the schema cannot be resolved ────────────────────


def _doctor(project_root):
    """Run `doctor` against a project, returning (exit_code, output)."""
    from typer.testing import CliRunner

    from litschema import cli

    result = CliRunner().invoke(
        cli.app, ["--config", str(project_root / "litschema.yaml"), "doctor"]
    )
    return result.exit_code, result.output


def _minimal_project(tmp_path, schema_body: str):
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir(parents=True, exist_ok=True)
    (schema_dir / "extraction.yaml").write_text(schema_body)
    (tmp_path / "litschema.yaml").write_text('project_root: "."\nschema_dir: "schema"\n')
    return tmp_path


def test_doctor_reports_an_unparseable_schema_and_exits_nonzero(tmp_path) -> None:
    """The command whose job is diagnosis must not stay quiet about the schema.

    Every other verb reads the extraction schema, so swallowing a resolution
    failure here just moves the confusing error downstream into `extract`.
    """
    project = _minimal_project(tmp_path, "this: is: not: valid: linkml: [[[\n")

    code, output = _doctor(project)

    assert code == 1, output
    assert "cannot resolve the extraction schema" in output
    assert "Everything looks good" not in output
    assert "fix the extraction schema" in output


def test_doctor_reports_a_schema_with_no_tree_root(tmp_path) -> None:
    project = _minimal_project(
        tmp_path,
        "id: https://example.org/t\nname: t\nclasses:\n"
        "  NotARoot:\n    attributes:\n      article_id:\n        range: string\n",
    )

    code, output = _doctor(project)

    assert code == 1, output
    assert "cannot resolve the extraction schema" in output


def test_doctor_names_the_resolved_schema_when_it_is_healthy(tmp_path) -> None:
    project = _minimal_project(
        tmp_path,
        "id: https://example.org/t\nname: t\nclasses:\n"
        "  ActualRoot:\n    tree_root: true\n    attributes:\n"
        "      article_id:\n        range: string\n",
    )

    code, output = _doctor(project)

    assert "extraction schema:" in output
    assert "ActualRoot" in output
    assert "cannot resolve the extraction schema" not in output


def test_schema_identity_covers_imported_schema_files(tmp_path) -> None:
    """A split schema's identity must include what it imports.

    `organic_inherits` imports a base schema and subclasses it, so hashing only
    the configured file meant editing the base left the recorded hash
    unchanged: a run's provenance named bytes it was not extracted against, and
    the schema-mismatch check waved the difference through.
    """
    import shutil

    from litschema.schema_resolution import (
        _schema_closure,
        extraction_schema_path,
        schema_hash,
    )

    source = Path("tests/fixtures/projects/organic_inherits")
    project = tmp_path / "p"
    shutil.copytree(source, project)
    cfg = load_config(project / "litschema.yaml", reload=True)

    entry = extraction_schema_path(cfg)
    closure = _schema_closure(entry)
    assert len(closure) == 2, [p.name for p in closure]

    before = schema_hash(cfg)
    imported = next(p for p in closure if p != entry)
    imported.write_text(imported.read_text() + "\n# edited the imported base\n")

    assert schema_hash(cfg) != before


def test_schema_identity_ignores_linkml_library_imports(tmp_path) -> None:
    """`linkml:types` versions with the dependency, not with the project."""
    from litschema.schema_resolution import _schema_closure

    schema_dir = tmp_path / "schema"
    schema_dir.mkdir(parents=True)
    entry = schema_dir / "extraction.yaml"
    entry.write_text(
        "id: https://example.org/t\nname: t\n"
        "prefixes:\n  linkml: https://w3id.org/linkml/\n"
        "imports: [linkml:types]\nclasses:\n  A:\n    tree_root: true\n"
    )

    assert _schema_closure(entry) == [entry]
