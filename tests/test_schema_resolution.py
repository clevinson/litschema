from __future__ import annotations

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
