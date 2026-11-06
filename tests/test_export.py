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
    from .helpers import publish_test_run

    paper_dir = project / "data" / "papers" / article_id
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "article-metadata.json").write_text(json.dumps({"id": article_id}))
    publish_test_run(paper_dir, extraction)
    return paper_dir


def test_export_jsonl_is_the_reviewed_truth(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _write_article(
        project,
        "smith-2024",
        {"article_id": "smith-2024", "study_type": "field_trial", "sample_size": 12},
    )
    from .helpers import TEST_RUN_ID

    run_dir = project / "data" / "papers" / "smith-2024" / "extraction-runs" / TEST_RUN_ID
    (run_dir / "review.json").write_text(
        json.dumps(
            {
                "version": 2,
                "fields": {"sample_size": {"override": {"op": "replace", "value": 18}}},
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


def _review(run_dir: Path, fields: dict) -> None:
    (run_dir / "review.json").write_text(json.dumps({"version": 2, "fields": fields}))


def _audit(project: Path, tmp_path: Path, *extra: str) -> tuple[dict, str]:
    audit_file = tmp_path / "audit.jsonl"
    result = runner.invoke(
        cli.app,
        [
            "--config", str(project / "litschema.yaml"),
            "export", "--format", "csv", "--output", str(tmp_path / "out.csv"),
            "--audit-output", str(audit_file), *extra,
        ],
    )
    assert result.exit_code == 0, result.output
    records = {
        r["article_id"]: r for r in map(json.loads, audit_file.read_text().splitlines())
    }
    return records, result.output


def test_export_audit_reports_review_status_per_article(tmp_path: Path) -> None:
    project = _project(tmp_path)
    record = {"article_id": "x", "study_type": "field_trial", "sample_size": 12}
    done = _write_article(project, "done", {**record, "article_id": "done"})
    part = _write_article(project, "part", {**record, "article_id": "part"})
    _write_article(project, "none", {**record, "article_id": "none"})
    from .helpers import TEST_RUN_ID

    _review(done / "extraction-runs" / TEST_RUN_ID, {
        "study_type": {},
        "sample_size": {"override": {"op": "replace", "value": 18}},
    })
    _review(part / "extraction-runs" / TEST_RUN_ID, {"study_type": {}})

    audit, output = _audit(project, tmp_path)

    # The identifier slot is identity, not review work.
    assert audit["done"]["review"] == {
        "status": "complete", "n_fields": 2, "n_reviewed": 2,
        "n_verified": 1, "n_overridden": 1,
    }
    assert audit["part"]["review"]["status"] == "partial"
    assert audit["none"]["review"]["status"] == "unreviewed"
    assert audit["part"]["fields"] == {"study_type": {}}
    assert "1 complete, 1 partial, 1 unreviewed; 1 with corrections" in output
    rows = {r["article_id"]: r for r in csv.DictReader(io.StringIO((tmp_path / "out.csv").read_text()))}
    assert rows["done"]["sample_size"] == "18"
    assert "status" not in rows["done"]  # data rows keep the schema's shape


def test_export_audit_provenance_comes_from_the_active_run(tmp_path: Path) -> None:
    from .helpers import publish_test_run

    project = _project(tmp_path)
    paper = _write_article(project, "smith-2024", {"article_id": "smith-2024", "sample_size": 1})
    newer = publish_test_run(
        paper, {"article_id": "smith-2024", "sample_size": 2}, run_id="01TESTRUN0000000000000000B"
    )
    run_json = json.loads((newer / "run.json").read_text())
    run_json["agent"] = {"provider": "anthropic", "model": "claude-x"}
    run_json["litschema"] = {"version": "0.1.2"}
    (newer / "run.json").write_text(json.dumps(run_json))
    (paper / "article-metadata.json").write_text(
        json.dumps({"id": "smith-2024", "bib_metadata": {"doi": "10.1/abc", "bib_source": "openalex"}})
    )
    _write_article(project, "no-doi", {"article_id": "no-doi"})

    audit, _ = _audit(project, tmp_path)

    smith = audit["smith-2024"]
    assert smith["run_id"] == "01TESTRUN0000000000000000B"
    assert smith["doi"] == "10.1/abc"
    assert smith["extraction"]["model"] == "claude-x"
    assert smith["extraction"]["litschema_version"] == "0.1.2"
    assert smith["schema_hash"].startswith("sha256:")
    # Missing provenance is null, not a default.
    assert audit["no-doi"]["doi"] is None
    assert audit["no-doi"]["extraction"]["model"] is None
    assert audit["no-doi"]["grade"] is None


def test_export_audit_counts_grade_flags(tmp_path: Path) -> None:
    from litschema.articles import article_files
    from litschema.grading import BANDS, GRADE_VERSION, input_hashes, write_grade
    from litschema.runs import active_run

    project = _project(tmp_path)
    paper = project / "data" / "papers" / "smith-2024"
    paper.mkdir(parents=True)
    (paper / "article.md").write_text("text\n")  # before the run, so the run cites it
    _write_article(project, "smith-2024", {"article_id": "smith-2024", "sample_size": 1})
    cfg = load_config(project / "litschema.yaml", reload=True)
    run = active_run(article_files(cfg, "smith-2024"))
    write_grade(run, {
        "version": GRADE_VERSION, "grade_id": "01G", "article_id": "smith-2024",
        "run_id": run.run_id, "created_at": "2026-10-01T00:00:00+00:00",
        "grader": {"model": "m", "requested_model": "m", "bands": dict(BANDS)},
        "inputs": input_hashes(run),
        "fields": [
            {"path": "sample_size", "confidence": 0.95, "issue": "ok"},
            {"path": "study_type", "confidence": 0.7, "issue": "maybe"},
            {"path": "crops", "confidence": None, "issue": "figure only"},
        ],
        "ungraded": [], "usage": {},
    })

    audit, _ = _audit(project, tmp_path)

    assert audit["smith-2024"]["grade"] == {
        "grade_id": "01G", "model": "m", "flagged": 2,
        "high": 1, "check": 1, "low": 0, "cannot_verify": 1,
    }


def test_export_is_deterministic_and_hints_at_audit(tmp_path: Path) -> None:
    project = _project(tmp_path)
    _write_article(project, "smith-2024", {"article_id": "smith-2024", "sample_size": 1})
    args = ["--config", str(project / "litschema.yaml"), "export"]

    first = runner.invoke(cli.app, args)
    second = runner.invoke(cli.app, args)

    assert first.output == second.output
    assert "--audit-output" in first.output


# ── stale runs: an older schema or a changed article.md ──────────────────────


def _export(project: Path, tmp_path: Path, *extra: str):
    return runner.invoke(
        cli.app,
        [
            "--config", str(project / "litschema.yaml"),
            "export", "--format", "csv", "--output", str(tmp_path / "out.csv"),
            "--audit-output", str(tmp_path / "audit.jsonl"), *extra,
        ],
    )


def test_export_refuses_a_run_extracted_against_an_older_schema(tmp_path: Path) -> None:
    """A CSV shaped by today's schema has no column for yesterday's slot.

    Renaming `country` to `study_country` made export exit 0 with an empty
    `study_country` column and no `country` column: the value and a reviewer's
    correction were gone and nothing said so. Refusing is the default; the
    flag is the user saying they know.
    """
    from .helpers import publish_test_run

    project = _project(tmp_path)
    paper = project / "data" / "papers" / "old"
    paper.mkdir(parents=True)
    (paper / "article-metadata.json").write_text(json.dumps({"id": "old"}))
    publish_test_run(
        paper,
        {"article_id": "old", "study_type": "field_trial", "country": "Kenya"},
        schema_hash="sha256:the-schema-before-the-rename",
    )
    _write_article(project, "fresh", {"article_id": "fresh", "study_type": "field_trial"})

    refused = _export(project, tmp_path)

    assert refused.exit_code == 2, refused.output
    assert "1 extracted against an older schema" in refused.output
    assert "old" in refused.output
    assert "--allow-stale" in refused.output
    # Nothing half-written: a refused export leaves no files behind.
    assert not (tmp_path / "out.csv").exists()
    assert not (tmp_path / "audit.jsonl").exists()

    allowed = _export(project, tmp_path, "--allow-stale")

    assert allowed.exit_code == 0, allowed.output
    assert "stale: 1 article(s) exported anyway" in allowed.output
    audit = {r["article_id"]: r for r in map(json.loads, (tmp_path / "audit.jsonl").read_text().splitlines())}
    assert "different schema" in audit["old"]["drift"]["schema"]
    assert audit["old"]["drift"]["source"] is None
    assert audit["fresh"]["drift"] == {"schema": None, "source": None}


def test_export_refuses_a_run_whose_article_text_changed(tmp_path: Path) -> None:
    """Line citations index into the text the run was extracted from.

    Re-converting or editing article.md after the run leaves every `L<n>`
    pointing somewhere else. The run records the hash of the text it saw, so
    the mismatch is checkable; before this nothing checked it.
    """
    from .helpers import publish_test_run

    project = _project(tmp_path)
    paper = project / "data" / "papers" / "moved"
    paper.mkdir(parents=True)
    (paper / "article-metadata.json").write_text(json.dumps({"id": "moved"}))
    (paper / "article.md").write_text("# Moved\n\nThe text the run cited.\n")
    publish_test_run(paper, {"article_id": "moved", "study_type": "field_trial"})

    assert _export(project, tmp_path).exit_code == 0

    (paper / "article.md").write_text("# Moved\n\nA fresh conversion with other line numbers.\n")

    refused = _export(project, tmp_path)

    assert refused.exit_code == 2, refused.output
    assert "1 whose article.md changed since extraction" in refused.output

    allowed = _export(project, tmp_path, "--allow-stale")

    assert allowed.exit_code == 0, allowed.output
    (record,) = map(json.loads, (tmp_path / "audit.jsonl").read_text().splitlines())
    assert "article.md changed after run" in record["drift"]["source"]
    assert record["drift"]["schema"] is None


def test_export_summary_counts_stale_runs_only_when_allowed(tmp_path: Path) -> None:
    from litschema.config import load_config as _load
    from litschema.export import ExportSummary, StaleRunsError, export_records

    project = _project(tmp_path)
    paper = _write_article(project, "a", {"article_id": "a", "study_type": "field_trial"})
    (paper / "article.md").write_text("new text\n")
    cfg = _load(project / "litschema.yaml", reload=True)

    try:
        export_records(cfg, "jsonl", io.StringIO())
    except StaleRunsError as exc:
        summary: ExportSummary = exc.summary
    else:  # pragma: no cover - the assertion below reports it
        raise AssertionError("export did not refuse a run whose text changed")

    assert summary.stale_articles == ["a"]
    assert (summary.schema_drift, summary.source_drift) == (0, 1)
    out = io.StringIO()
    assert export_records(cfg, "jsonl", out, allow_stale=True).stale_articles == ["a"]
    assert json.loads(out.getvalue())["article_id"] == "a"
