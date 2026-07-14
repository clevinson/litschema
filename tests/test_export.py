from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from typer.testing import CliRunner

from litschema import cli
from litschema.config import load_config

runner = CliRunner()


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    schema_dir = project / "schema"
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
    (project / "litschema.yaml").write_text(
        'project_root: "."\n'
        'schema_dir: "schema"\n'
        'extraction_schema_file: "agriculture_extraction.yaml"\n'
        'article_store_dir: "data/papers"\n'
        'paper_inbox_dir: "papers-inbox"\n'
    )
    return project


def _write_article(project: Path, article_id: str, extraction: dict) -> Path:
    paper_dir = project / "data" / "papers" / article_id
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "agent-extraction.json").write_text(json.dumps(extraction))
    return paper_dir


def test_export_jsonl_is_the_reviewed_truth(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _write_article(
        project,
        "smith-2024",
        {"article_id": "smith-2024", "study_type": "field_trial", "sample_size": 12},
    )
    (project / "data" / "papers" / "smith-2024" / "review.json").write_text(
        json.dumps(
            {
                "version": 1,
                "fields": {
                    "sample_size": {"author": "", "signal": "flagged", "override_value": 18}
                },
            }
        )
    )
    # Error markers never export.
    _write_article(project, "broken", {"article_id": "broken", "error": True, "reason": "x"})
    # A record missing its identifier gets it backfilled from the dir name.
    _write_article(project, "jones-2023", {"study_type": "meta_analysis"})

    result = runner.invoke(
        cli.app, ["--config", str(project / "litschema.yaml"), "export"]
    )

    assert result.exit_code == 0, result.output
    records = {
        r["article_id"]: r
        for r in (json.loads(line) for line in result.output.splitlines() if line.startswith("{"))
    }
    assert set(records) == {"smith-2024", "jones-2023"}
    assert records["smith-2024"]["sample_size"] == 18  # override applied
    assert records["jones-2023"]["study_type"] == "meta_analysis"


def test_export_csv_shapes_columns_like_the_explore_store(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _write_article(
        project,
        "smith-2024",
        {
            "article_id": "smith-2024",
            "study_type": "field_trial",
            "crops": ["maize", "wheat"],
            "sample_size": 12,
        },
    )
    out_file = tmp_path / "out.csv"

    result = runner.invoke(
        cli.app,
        [
            "--config", str(project / "litschema.yaml"),
            "export", "--format", "csv", "--output", str(out_file),
        ],
    )

    assert result.exit_code == 0, result.output
    rows = list(csv.DictReader(io.StringIO(out_file.read_text())))
    (row,) = rows
    assert row["article_id"] == "smith-2024"
    assert row["sample_size"] == "12"
    assert json.loads(row["crops"]) == ["maize", "wheat"]  # multivalued -> JSON cell
    assert row["experiments"] == ""  # absent slot -> empty cell


def test_export_rejects_unknown_format_and_missing_schema(tmp_path: Path) -> None:
    project = _project(tmp_path)

    bad_fmt = runner.invoke(
        cli.app,
        ["--config", str(project / "litschema.yaml"), "export", "--format", "parquet"],
    )
    assert bad_fmt.exit_code == 2

    (project / "schema" / "agriculture_extraction.yaml").unlink()
    load_config(project / "litschema.yaml", reload=True)
    no_schema = runner.invoke(
        cli.app, ["--config", str(project / "litschema.yaml"), "export"]
    )
    assert no_schema.exit_code == 2
    assert "Traceback" not in no_schema.output
