from __future__ import annotations

import json
from pathlib import Path

import duckdb

from litschema.config import load_config
from litschema.explore.loader import build_store


def test_loader_reads_per_article_folder_and_review_json(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    paper_dir = project / "data" / "papers" / "smith-2024"
    schema_dir = project / "schema"
    paper_dir.mkdir(parents=True)
    schema_dir.mkdir(parents=True)

    template = (
        Path(__file__).parent.parent
        / "src"
        / "litschema"
        / "templates"
        / "agriculture"
        / "agriculture_extraction.yaml"
    )
    (schema_dir / "agriculture_extraction.yaml").write_text(template.read_text())
    (paper_dir / "agent-extraction.json").write_text(
        json.dumps(
            {
                "article_id": "smith-2024",
                "study_type": "field_trial",
                "crops": ["maize"],
                "sample_size": 12,
            }
        )
    )
    (paper_dir / "review.json").write_text(
        json.dumps(
            {
                "version": 1,
                "fields": {
                    "sample_size": [
                        {
                            "author": "0000-0002-1825-0097",
                            "signal": "flagged",
                            "timestamp": "2026-05-05T00:00:00+00:00",
                            "override_value": 18,
                        }
                    ]
                },
            }
        )
        + "\n"
    )
    (project / "litschema.yaml").write_text(
        'project_root: "."\n'
        'schema_dir: "schema"\n'
        'extraction_schema_file: "agriculture_extraction.yaml"\n'
        'data_dir: "data"\n'
        'article_store_dir: "data/papers"\n'
        'paper_inbox_dir: "papers-inbox"\n'
    )

    cfg = load_config(project / "litschema.yaml")
    db_path = tmp_path / "layout.duckdb"
    summary = build_store(cfg, db_path=db_path, force_rebuild=True)

    assert summary.extractions_loaded == 1
    assert summary.reviews_applied == 1
    assert summary.overrides_applied == 1

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute("SELECT article_id, sample_size FROM articles").fetchone()
    finally:
        con.close()

    assert row == ("smith-2024", 18)
