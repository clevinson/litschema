"""Schema-shape tests for the explore loader across three usage patterns.

These tests pin down the three usage patterns documented in
`src/litschema/templates/agriculture/README.md`:

  1. Custom schema — a totally different domain (clinical trials).
  2. Demo schema usage — the bundled `templates/agriculture/` schema.
  3. Inheritance — a subclass via `is_a`, adding new slots, with its
     own `tree_root: true`. Inherits all base slots through
     `class_induced_slots`.

Each scenario points the litschema config loader at a fixture project
under `tests/fixtures/projects/<scenario>/` and asserts about the
DuckDB columns + insertable data the schema-driven loader produces.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from litschema.config import load_config
from litschema.explore.loader import build_store

FIXTURES = Path(__file__).parent / "fixtures" / "projects"


def _build_store_for(scenario: str, tmp_path: Path):
    """Load config for a fixture project and build its DuckDB into tmp."""
    project_root = FIXTURES / scenario
    cfg = load_config(project_root / "litschema.yaml")
    db_path = tmp_path / f"{scenario}.duckdb"
    summary = build_store(cfg, db_path=db_path, force_rebuild=True)
    return cfg, summary, db_path


def _column_map(article_columns: list[tuple[str, str]]) -> dict[str, str]:
    return dict(article_columns)


# ── Scenario 1: custom schema (clinical trials, no inheritance) ────────────


def test_custom_schema_clinical_trials(tmp_path: Path) -> None:
    """A user-defined schema in an unrelated domain produces a coherent
    `articles` table from schema introspection alone — no agriculture or
    ERW concepts present."""
    cfg, summary, db_path = _build_store_for("custom_clinical", tmp_path)

    cols = _column_map(summary.article_columns)

    # Slots from ClinicalTrialReport
    assert "article_id" in cols
    assert "registry_id" in cols
    assert "n_arms" in cols
    assert "total_participants" in cols
    assert "primary_endpoint" in cols
    assert "blinding" in cols
    assert "interventions" in cols
    assert "outcomes_reported" in cols

    # Type rules: scalar slots → typed; multivalued → JSON
    assert cols["registry_id"] == "VARCHAR"
    assert cols["n_arms"] == "BIGINT"
    assert cols["total_participants"] == "BIGINT"
    assert cols["blinding"] == "VARCHAR"  # single-valued enum
    assert cols["interventions"] == "JSON"
    assert cols["outcomes_reported"] == "JSON"

    # Make sure we did NOT bleed any agriculture/ERW slot names through
    for ag_only in ("crops", "study_type", "study_types", "treatments", "outcomes"):
        assert ag_only not in cols, f"{ag_only!r} should not appear in clinical schema"

    # Records loaded successfully
    assert summary.extractions_loaded == 2

    # Round-trip a query
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        n = con.execute("SELECT COUNT(*) FROM articles WHERE blinding = 'double_blind'").fetchone()[
            0
        ]
        assert n == 1
    finally:
        con.close()


# ── Scenario 2: use the bundled agriculture template as-is ─────────────────


def test_agriculture_template_as_is(tmp_path: Path) -> None:
    """A user who points their litschema project at the bundled
    `templates/agriculture/agriculture_extraction.yaml` gets exactly the
    template's column shape and can run scalar + JSON queries."""
    cfg, summary, db_path = _build_store_for("agriculture_demo", tmp_path)

    cols = _column_map(summary.article_columns)

    # All 7 top-level AgricultureExtraction slots are present
    expected = {
        "article_id",
        "confidence",
        "reasoning",
        "study_type",
        "crops",
        "experiments",
        "sample_size",
    }
    assert expected.issubset(cols.keys()), f"missing slots: {expected - cols.keys()}"

    # Type rules
    assert cols["article_id"] == "VARCHAR"
    assert cols["confidence"] == "DOUBLE"
    assert cols["sample_size"] == "BIGINT"
    assert cols["study_type"] == "VARCHAR"  # scalar enum
    assert cols["crops"] == "JSON"  # multivalued strings
    assert cols["experiments"] == "JSON"  # multivalued nested Experiment objects

    assert summary.extractions_loaded == 2

    # Scalar + JSON query patterns both work
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        n_field_trials = con.execute(
            "SELECT COUNT(*) FROM articles WHERE study_type = 'field_trial'"
        ).fetchone()[0]
        assert n_field_trials == 1

        # Drill into the Experiment bundle: site → country
        countries = con.execute(
            "SELECT json_extract_string(experiments, '$[0].site.country') "
            "FROM articles ORDER BY article_id"
        ).fetchall()
        assert sorted(c[0] for c in countries) == ["Nigeria", "USA"]

        # Drill into Experiment → soil → texture_class
        textures = con.execute(
            "SELECT json_extract_string(experiments, '$[0].soil.texture_class') "
            "FROM articles ORDER BY article_id"
        ).fetchall()
        assert sorted(t[0] for t in textures) == ["sandy_loam", "silty_clay_loam"]

        # Field-trial vs lab/greenhouse distinction via soil_source presence
        # inside the Experiment bundle. Greenhouse paper has a populated
        # soil_source.country; field trial leaves it null (site IS the source).
        soil_sources = con.execute(
            "SELECT article_id, "
            "json_extract_string(experiments, '$[0].soil_source.country') "
            "FROM articles ORDER BY article_id"
        ).fetchall()
        assert dict(soil_sources) == {
            "okeke-2025": "Nigeria",  # greenhouse: explicit source
            "smith-2024": None,  # field trial: site IS the source
        }

        # Per-treatment effect directions on the SAME measured variable —
        # the case the schema is explicitly designed to capture. Smith's
        # field trial had three treatments (cover crop / no-till / combo)
        # that all measured yield + soil_organic_carbon, with different
        # effect directions per treatment.
        smith_yield_effects = con.execute(
            """
            SELECT
              json_extract_string(t.value, '$.name') AS treatment,
              json_extract_string(o.value, '$.effect_direction') AS direction
            FROM articles AS a,
                 json_each(json_extract(a.experiments, '$[0].treatments')) AS t,
                 json_each(json_extract(t.value, '$.outcomes')) AS o
            WHERE a.article_id = 'smith-2024'
              AND json_extract_string(o.value, '$.variable') = 'yield'
            ORDER BY treatment
            """
        ).fetchall()
        assert dict(smith_yield_effects) == {
            "cover crop + no-till": "positive",
            "cover crop only": "neutral",
            "no-till only": "positive",
        }
    finally:
        con.close()


# ── Scenario 3: inheritance via is_a, with subclass marked tree_root ───────


def test_inheritance_is_a_with_tree_root_override(tmp_path: Path) -> None:
    """Subclassing `AgricultureExtraction` via `is_a` should:

    - Inherit all 9 base slots (LinkML class_induced_slots)
    - Add the 2 new slots from the subclass
    - Make `OrganicAgricultureExtraction` the active root because IT is the
      class with `tree_root: true` in the entry-point file (the imported
      `AgricultureExtraction.tree_root` is filtered out by the loader).
    """
    cfg, summary, db_path = _build_store_for("organic_inherits", tmp_path)

    cols = _column_map(summary.article_columns)

    # Inherited slots
    inherited = {
        "article_id",
        "confidence",
        "reasoning",
        "study_type",
        "crops",
        "experiments",
        "sample_size",
    }
    # New slots added in the subclass
    added = {"certification_body", "organic_practices"}

    assert inherited.issubset(cols.keys()), f"inherited slots missing: {inherited - cols.keys()}"
    assert added.issubset(cols.keys()), f"new slots missing: {added - cols.keys()}"

    # Subclass slots typed correctly
    assert cols["certification_body"] == "VARCHAR"
    assert cols["organic_practices"] == "JSON"  # multivalued

    # Inherited slots keep their inherited types
    assert cols["sample_size"] == "BIGINT"
    assert cols["experiments"] == "JSON"

    assert summary.extractions_loaded == 1

    # Confirm we can query both inherited and new slots in one row
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute(
            "SELECT article_id, sample_size, certification_body, "
            "json_array_length(organic_practices) AS n_practices "
            "FROM articles"
        ).fetchone()
        assert row[0] == "lopez-2024"
        assert row[1] == 18
        assert row[2] == "EU Organic"
        assert row[3] == 3
    finally:
        con.close()


# ── A small failure-mode test, since we ship explicit error messages ──────


def test_imported_tree_root_is_filtered_out(tmp_path: Path) -> None:
    """Sanity: if the entry-point schema didn't declare its OWN tree_root
    and only imported one, the loader must error rather than silently use
    the imported tree_root. This is the bug the local-classes filter
    prevents — proves the filter is actually doing something."""
    project = tmp_path / "no_local_root"
    (project / "schema").mkdir(parents=True)

    # The agriculture schema has tree_root on AgricultureExtraction
    template = (
        Path(__file__).parent.parent
        / "src"
        / "litschema"
        / "templates"
        / "agriculture"
        / "agriculture_extraction.yaml"
    )
    (project / "schema" / "agriculture_extraction.yaml").write_text(template.read_text())

    # Entry-point schema imports it but defines no local tree_root class
    (project / "schema" / "shell.yaml").write_text(
        "id: https://example.org/no-local-root\n"
        "name: shell_only\n"
        "imports:\n"
        "  - linkml:types\n"
        "  - ./agriculture_extraction\n"
    )

    (project / "litschema.yaml").write_text(
        'project_root: "."\n'
        'schema_dir: "schema"\n'
        'extraction_schema_file: "shell.yaml"\n'
        'data_dir: "data"\n'
        'papers_dir: "papers"\n'
    )

    cfg = load_config(project / "litschema.yaml")
    with pytest.raises(ValueError, match="could not determine the root extraction class"):
        build_store(cfg, db_path=tmp_path / "no_root.duckdb", force_rebuild=True)
