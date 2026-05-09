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
