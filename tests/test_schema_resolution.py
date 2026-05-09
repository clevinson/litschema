from __future__ import annotations

from litschema.config import load_config
from litschema import schema_resolution


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
    config_path.write_text('project_root: "."\n' 'schema_dir: "schema"\n')
    cfg = load_config(config_path, reload=True)

    assert schema_resolution.resolve_extraction_schema(cfg) == (
        schema_dir / "extraction.yaml",
        "ActualRoot",
    )


def test_resolve_extraction_schema_view_returns_shared_view_and_root() -> None:
    cfg = load_config("tests/fixtures/projects/custom_clinical/litschema.yaml", reload=True)

    sv, root_class = schema_resolution.resolve_extraction_schema_view(cfg)

    assert root_class == "ClinicalTrialReport"
    assert "primary_endpoint" in [slot.name for slot in sv.class_induced_slots(root_class)]
