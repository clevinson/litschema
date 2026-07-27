from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from litschema import cli
from litschema.config import LitSchemaConfig
from litschema.ingest import article_assembly


def _cfg(project: Path) -> LitSchemaConfig:
    return LitSchemaConfig(
        config_path=project / "litschema.yaml",
        project_root=project,
        data_dir=project / "data",
        schema_dir=project / "schema",
        references_dir=project / "references",
        tracking_xlsx=project / "paper_download_tracking.xlsx",
        paper_inbox_dir=project / "papers-inbox",
        static_site_dir=project / "static-site",
        article_store_dir=project / "data" / "papers",
        raw={},
    )


def _drop_pdf(cfg: LitSchemaConfig, name: str, content: str) -> Path:
    cfg.paper_inbox_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.paper_inbox_dir / name
    path.write_text(content)
    return path


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


# ── Article id derivation ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Smith et al. 2024 enhanced weathering", "smith-et-al-2024-enhanced-weathering"),
        ("Carbon Credit Issuance 0421", "carbon-credit-issuance-0421"),
        ("policy_final_v3", "policy-final-v3"),
        ("report", "report"),
        ("../../etc/passwd", "etc-passwd"),
        ("/abs/path", "abs-path"),
        ("..", "article"),
        ("", "article"),
    ],
)
def test_slugify_produces_safe_single_component(raw: str, expected: str) -> None:
    slug = article_assembly._slugify(raw)
    assert "/" not in slug
    assert ".." not in slug
    assert slug == expected


# ── Local-first intake ───────────────────────────────────────────────────────


def test_assemble_moves_inbox_pdf_into_filename_derived_folder(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    inbox_pdf = _drop_pdf(cfg, "Smith 2024 enhanced weathering.pdf", "pdf placeholder")

    stats = article_assembly.assemble(cfg)

    article_dir = cfg.article_store_dir / "smith-2024-enhanced-weathering"
    assert stats == {"inbox_pdfs": 1, "assembled": 1, "already_assembled": 0, "errors": 0}
    assert (article_dir / "smith-2024-enhanced-weathering.pdf").read_text() == "pdf placeholder"
    assert not inbox_pdf.exists()
    assert not any(cfg.paper_inbox_dir.glob("*.pdf"))


def test_assemble_writes_minimal_manifest(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _drop_pdf(cfg, "Carbon Credit Issuance 0421.pdf", "carbon pdf bytes")

    article_assembly.assemble(cfg)

    metadata = json.loads(
        (cfg.article_store_dir / "carbon-credit-issuance-0421" / "article-metadata.json").read_text()
    )
    assert metadata["id"] == "carbon-credit-issuance-0421"
    assert metadata["filename"] == "carbon-credit-issuance-0421.pdf"
    assert metadata["original_filename"] == "Carbon Credit Issuance 0421.pdf"
    assert metadata["file_sha256"] == _sha256("carbon pdf bytes")
    assert "added_at" in metadata
    # Bibliographic fields are NOT written at assemble time.
    assert "title" not in metadata
    assert "doi" not in metadata


def test_assemble_needs_no_doi_or_network(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _drop_pdf(cfg, "report.pdf", "a report with no DOI anywhere")

    # The module must not carry any bibliographic-harvest machinery.
    assert "openalex_harvest" not in dir(article_assembly)
    assert not hasattr(article_assembly, "fetch_openalex")

    stats = article_assembly.assemble(cfg)

    assert stats["assembled"] == 1
    assert (cfg.article_store_dir / "report" / "report.pdf").exists()


def test_assemble_is_idempotent_on_same_content_redrop(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _drop_pdf(cfg, "paper.pdf", "same bytes")
    article_assembly.assemble(cfg)

    # Re-drop an identical file.
    _drop_pdf(cfg, "paper.pdf", "same bytes")
    stats = article_assembly.assemble(cfg)

    assert stats == {"inbox_pdfs": 1, "assembled": 0, "already_assembled": 1, "errors": 0}
    article_dirs = [p for p in cfg.article_store_dir.glob("*") if p.is_dir()]
    assert [p.name for p in article_dirs] == ["paper"]
    assert not (cfg.paper_inbox_dir / "paper.pdf").exists()
    assert (cfg.paper_inbox_dir / ".processed" / "paper.pdf").read_text() == "same bytes"


def test_assemble_disambiguates_colliding_slugs_by_content_hash(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _drop_pdf(cfg, "report.pdf", "content A")
    article_assembly.assemble(cfg)

    # A different file that slugifies to the same id.
    _drop_pdf(cfg, "report.pdf", "content B")
    stats = article_assembly.assemble(cfg)

    assert stats["assembled"] == 1
    suffixed_id = f"report-{_sha256('content B')[: article_assembly.SHORT_HASH_LEN]}"
    assert (cfg.article_store_dir / "report" / "report.pdf").read_text() == "content A"
    assert (cfg.article_store_dir / suffixed_id / f"{suffixed_id}.pdf").read_text() == "content B"


def test_assemble_is_concise_when_inbox_is_empty(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.paper_inbox_dir.mkdir(parents=True)

    stats = article_assembly.assemble(cfg)

    assert stats == {"inbox_pdfs": 0, "assembled": 0, "already_assembled": 0, "errors": 0}


def test_assemble_continues_after_pdf_intake_error(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    _drop_pdf(cfg, "Bad.pdf", "bad pdf")
    _drop_pdf(cfg, "Good.pdf", "good pdf")

    real_sha256 = article_assembly._sha256

    def fake_sha256(path: Path) -> str:
        if path.name == "Bad.pdf":
            raise RuntimeError("intake failed")
        return real_sha256(path)

    monkeypatch.setattr(article_assembly, "_sha256", fake_sha256)

    stats = article_assembly.assemble(cfg)

    assert stats["errors"] == 1
    assert stats["assembled"] == 1
    assert (cfg.article_store_dir / "good" / "good.pdf").exists()
    assert (cfg.paper_inbox_dir / "Bad.pdf").exists()  # failed PDFs stay in the inbox
    assert not (cfg.paper_inbox_dir / "Good.pdf").exists()


def test_assemble_raises_assembly_interrupted_on_keyboard_interrupt(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = _cfg(tmp_path)
    inbox_pdf = _drop_pdf(cfg, "Interrupted.pdf", "bytes")

    def fake_sha256(path: Path) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(article_assembly, "_sha256", fake_sha256)

    with pytest.raises(article_assembly.AssemblyInterrupted) as excinfo:
        article_assembly.assemble(cfg)

    assert excinfo.value.pdf_path == inbox_pdf


def test_assemble_treats_wrapped_keyboard_interrupt_as_cancellation(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    cfg = _cfg(tmp_path)
    inbox_pdf = _drop_pdf(cfg, "Interrupted.pdf", "bytes")

    def fake_sha256(path: Path) -> str:
        raise RuntimeError("Director error: <class 'KeyboardInterrupt'>")

    monkeypatch.setattr(article_assembly, "_sha256", fake_sha256)

    with pytest.raises(article_assembly.AssemblyInterrupted) as excinfo:
        article_assembly.assemble(cfg)

    assert excinfo.value.pdf_path == inbox_pdf
    assert "Failed to assemble inbox PDF" not in caplog.text


# ── CLI wiring ───────────────────────────────────────────────────────────────


def test_assemble_cli_runs_project_assembly(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.config_path.write_text('project_root: "."\n')
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))

    def fake_assemble(cfg, reporter=None):
        assert reporter is not None
        reporter("start", {"inbox_pdfs": 2})
        reporter("pdf", {"path": Path("papers-inbox/good.pdf"), "result": "assembled",
                         "article_id": "good"})
        reporter("pdf_error", {"path": Path("papers-inbox/bad.pdf"), "error": RuntimeError("bad")})
        return {"inbox_pdfs": 2, "assembled": 1, "already_assembled": 0, "errors": 1}

    monkeypatch.setattr(article_assembly, "assemble", fake_assemble)

    result = CliRunner().invoke(cli.app, ["assemble"])

    assert result.exit_code == 0
    assert "Assembling article inputs" in result.output
    assert "Inbox PDFs [##########----------] 1/2" in result.output
    assert "PDF assembled: good.pdf → good" in result.output
    assert "PDF failed: bad.pdf (bad)" in result.output
    assert "Summary" in result.output
    assert "assembled: 1" in result.output
    assert "errors: 1" in result.output


def test_assemble_cli_is_concise_when_there_is_no_work(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.config_path.write_text('project_root: "."\n')
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))

    def fake_assemble(cfg, reporter=None):
        assert reporter is not None
        reporter("start", {"inbox_pdfs": 0})
        return {"inbox_pdfs": 0, "assembled": 0, "already_assembled": 0, "errors": 0}

    monkeypatch.setattr(article_assembly, "assemble", fake_assemble)

    result = CliRunner().invoke(cli.app, ["assemble"])

    assert result.exit_code == 0
    assert "No inbox PDFs found." in result.output
    assert "Inbox PDFs [" not in result.output
    assert "Summary" in result.output


def test_assemble_cli_reports_keyboard_interrupt_without_traceback(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = _cfg(tmp_path)
    cfg.config_path.write_text('project_root: "."\n')
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))

    def fake_assemble(cfg, reporter=None):
        if reporter is not None:
            reporter("start", {"inbox_pdfs": 1})
        raise article_assembly.AssemblyInterrupted(Path("papers-inbox/Interrupted.pdf"))

    monkeypatch.setattr(article_assembly, "assemble", fake_assemble)

    result = CliRunner().invoke(cli.app, ["assemble"])

    assert result.exit_code == 130
    assert "Assembly interrupted" in result.output
    assert "Interrupted.pdf" in result.output
    assert "Traceback" not in result.output


# ── source_metadata seeding ──────────────────────────────────────────────────


def test_assemble_seeds_source_metadata_title_from_filename(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    _drop_pdf(cfg, "Carbon Direct Buyer Guide 2024.pdf", "pdf-bytes")

    article_assembly.assemble(cfg)

    manifest = json.loads(
        (cfg.article_store_dir / "carbon-direct-buyer-guide-2024" / "article-metadata.json").read_text()
    )
    assert manifest["source_metadata"] == {
        "title": "Carbon Direct Buyer Guide 2024",
        "metadata_source": "auto",
    }


# ── record-extraction publishes an immutable run and activates it ────────────


def _publishable_project(tmp_path: Path) -> tuple:
    """A minimal project where record-extraction can actually publish."""
    cfg = _cfg(tmp_path)
    (tmp_path / "schema").mkdir(parents=True, exist_ok=True)
    (tmp_path / "schema" / "extraction.yaml").write_text(
        """id: https://example.org/test
name: test
prefixes:
  linkml: https://w3id.org/linkml/
imports: [linkml:types]
default_range: string
classes:
  Article:
    tree_root: true
    attributes:
      article_id:
        identifier: true
      title: {}
"""
    )
    (tmp_path / "domain_context.md").write_text("# Test context\n")
    skill_dir = tmp_path / ".claude" / "skills" / "extract-article"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# extract-article\n")
    article_dir = cfg.article_store_dir / "smith-2024"
    article_dir.mkdir(parents=True)
    (article_dir / "article-metadata.json").write_text(json.dumps({"id": "smith-2024"}))
    (article_dir / "article.md").write_text("# Smith 2024\n\nA title.\n")
    (article_dir / "agent-extraction.json").write_text(
        json.dumps({"article_id": "smith-2024", "title": "A title"})
    )
    (article_dir / "agent-reasoning.json").write_text(
        json.dumps(
            {"fields": [{"path": ".title", "source_lines": "L3", "value": "A title"}]}
        )
    )
    return cfg, article_dir


def test_agent_record_extraction_publishes_and_activates(tmp_path: Path, monkeypatch) -> None:
    cfg, article_dir = _publishable_project(tmp_path)
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))

    result = CliRunner().invoke(
        cli.app,
        ["agent", "record-extraction", "smith-2024", "--provider", "codex", "--model", "gpt-5.5"],
    )

    assert result.exit_code == 0, result.output
    # The staged files were consumed into an immutable run.
    assert not (article_dir / "agent-extraction.json").exists()
    runs = list((article_dir / "extraction-runs").iterdir())
    assert len(runs) == 1
    record = json.loads((runs[0] / "run.json").read_text())
    assert record["schema_hash"].startswith("sha256:")
    assert set(record["inputs"]) == {"prepared_text", "domain_context", "skill"}
    assert all(v.startswith("sha256:") for v in record["inputs"].values())
    assert record["agent"]["provider"] == "codex"
    assert record["agent"]["model"] == "gpt-5.5"
    # Publish-activates.
    pointer = json.loads((article_dir / "active-run.json").read_text())
    assert pointer == {"run_id": record["run_id"]}
    # No extraction provenance in the manifest (the run owns it now).
    metadata = json.loads((article_dir / "article-metadata.json").read_text())
    assert "extraction" not in metadata


def test_agent_record_extraction_error_marker_publishes_inactive(
    tmp_path: Path, monkeypatch
) -> None:
    cfg, article_dir = _publishable_project(tmp_path)
    (article_dir / "agent-extraction.json").write_text(
        json.dumps({"article_id": "smith-2024", "error": True, "reason": "scan quality"})
    )
    (article_dir / "agent-reasoning.json").unlink()
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))

    result = CliRunner().invoke(cli.app, ["agent", "record-extraction", "smith-2024"])

    assert result.exit_code == 0, result.output
    assert "inactive" in result.output
    assert not (article_dir / "active-run.json").exists()
    assert len(list((article_dir / "extraction-runs").iterdir())) == 1


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"article_id": "a", "error": True, "reason": "no extractable text"}, True),
        # `error` is an ordinary slot name in a science schema. Truthiness let a
        # measurement error of 0.42 skip validation and publish inactive.
        ({"article_id": "a", "error": 0.42}, False),
        ({"article_id": "a", "error": 1}, False),
        ({"article_id": "a", "error": "extraction_failed"}, False),
        # A marker must say why; `error: true` alone is not a diagnosis.
        ({"article_id": "a", "error": True}, False),
        ({"article_id": "a", "error": True, "reason": "   "}, False),
        ({"article_id": "a", "error": False, "reason": "x"}, False),
        ([1, 2, 3], False),
        ("a string", False),
        (None, False),
    ],
)
def test_error_markers_are_recognised_by_structure_not_truthiness(payload, expected) -> None:
    from litschema.runs import is_error_marker

    assert is_error_marker(payload) is expected


def test_a_truthy_error_field_does_not_bypass_schema_validation(tmp_path: Path) -> None:
    """A real extraction carrying an `error` value must still be validated."""
    from litschema.ingest.validate_extraction import validate_file

    cfg, article_dir = _publishable_project(tmp_path)
    schema = tmp_path / "schema" / "extraction.yaml"
    staged = tmp_path / "staged.json"
    staged.write_text(json.dumps({"article_id": "a", "error": 0.42, "bogus": "not in schema"}))

    valid, errors = validate_file(staged, schema, "Article")

    assert valid is False
    assert errors


def test_validate_file_reports_non_object_json_instead_of_crashing(tmp_path: Path) -> None:
    from litschema.ingest.validate_extraction import validate_file

    cfg, article_dir = _publishable_project(tmp_path)
    schema = tmp_path / "schema" / "extraction.yaml"
    staged = tmp_path / "staged.json"
    staged.write_text("[1, 2, 3]")

    valid, errors = validate_file(staged, schema, "Article")

    assert valid is False
    assert "must be a JSON object" in errors[0]


def test_record_extraction_rejects_a_marker_naming_another_article(
    tmp_path: Path, monkeypatch
) -> None:
    cfg, article_dir = _publishable_project(tmp_path)
    (article_dir / "agent-extraction.json").write_text(
        json.dumps({"article_id": "someone-else", "error": True, "reason": "bad scan"})
    )
    (article_dir / "agent-reasoning.json").unlink()
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))

    result = CliRunner().invoke(cli.app, ["agent", "record-extraction", "smith-2024"])

    assert result.exit_code == 1, result.output
    assert "names article" in result.output
    assert not (article_dir / "extraction-runs").exists()


def test_runs_list_survives_every_damaged_run_json(tmp_path: Path, monkeypatch) -> None:
    """One unreadable record must not take down the listing that would find it."""
    cfg, article_dir = _publishable_project(tmp_path)
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))
    runner = CliRunner()
    assert runner.invoke(cli.app, ["agent", "record-extraction", "smith-2024"]).exit_code == 0

    runs = article_dir / "extraction-runs"
    for run_id, blob in [
        ("01DAMAGED000000000000000A", b'["a list, not an object"]'),
        ("01DAMAGED000000000000000B", b"\xff\xfe not utf-8 at all"),
        ("01DAMAGED000000000000000C", b'{"agent": "a string, not an object"}'),
        ("01DAMAGED000000000000000D", b"{not json"),
    ]:
        run_dir = runs / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_bytes(blob)
        (run_dir / "agent-extraction.json").write_text('{"article_id": "smith-2024"}')

    result = runner.invoke(cli.app, ["runs", "list", "smith-2024"])

    assert result.exit_code == 0, result.output
    for run_id in ("A", "B", "C", "D"):
        assert f"01DAMAGED000000000000000{run_id}" in result.output


def test_runs_list_reports_a_pointer_naming_a_run_that_is_gone(
    tmp_path: Path, monkeypatch
) -> None:
    cfg, article_dir = _publishable_project(tmp_path)
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))
    runner = CliRunner()
    assert runner.invoke(cli.app, ["agent", "record-extraction", "smith-2024"]).exit_code == 0
    (article_dir / "active-run.json").write_text(json.dumps({"run_id": "01GONE00000000000000000000"}))

    result = runner.invoke(cli.app, ["runs", "list", "smith-2024"])

    assert "not a published run" in result.output


def test_runs_activate_refuses_a_run_missing_reasoning(tmp_path: Path, monkeypatch) -> None:
    """Activation is what consumers read through, so the run must be complete."""
    cfg, article_dir = _publishable_project(tmp_path)
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))
    runner = CliRunner()
    assert runner.invoke(cli.app, ["agent", "record-extraction", "smith-2024"]).exit_code == 0
    first = json.loads((article_dir / "active-run.json").read_text())["run_id"]
    _publish_second_run(article_dir, "01SECONDRUN00000000000000")
    (article_dir / "extraction-runs" / "01SECONDRUN00000000000000" / "agent-reasoning.json").unlink()

    result = runner.invoke(
        cli.app, ["runs", "activate", "smith-2024", "01SECONDRUN00000000000000"]
    )

    assert result.exit_code == 1, result.output
    assert "agent-reasoning.json" in result.output
    # The pointer is unchanged: a refused activation must not disturb it.
    assert json.loads((article_dir / "active-run.json").read_text()) == {"run_id": first}


def test_agent_record_extraction_re_extraction_keeps_prior_run(
    tmp_path: Path, monkeypatch
) -> None:
    cfg, article_dir = _publishable_project(tmp_path)
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))
    runner = CliRunner()
    assert runner.invoke(cli.app, ["agent", "record-extraction", "smith-2024"]).exit_code == 0
    first_run = json.loads((article_dir / "active-run.json").read_text())["run_id"]
    first_bytes = (
        article_dir / "extraction-runs" / first_run / "agent-extraction.json"
    ).read_bytes()

    # Stage a second attempt and publish it.
    (article_dir / "agent-extraction.json").write_text(
        json.dumps({"article_id": "smith-2024", "title": "Better title"})
    )
    (article_dir / "agent-reasoning.json").write_text(
        json.dumps({"fields": [{"path": ".title", "source_lines": "L3"}]})
    )
    assert runner.invoke(cli.app, ["agent", "record-extraction", "smith-2024"]).exit_code == 0

    second_run = json.loads((article_dir / "active-run.json").read_text())["run_id"]
    assert second_run != first_run
    # The prior run is intact and unmodified.
    assert (
        article_dir / "extraction-runs" / first_run / "agent-extraction.json"
    ).read_bytes() == first_bytes


def test_agent_record_extraction_fails_without_hashable_inputs(
    tmp_path: Path, monkeypatch
) -> None:
    cfg, article_dir = _publishable_project(tmp_path)
    (tmp_path / "domain_context.md").unlink()
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))

    result = CliRunner().invoke(cli.app, ["agent", "record-extraction", "smith-2024"])

    assert result.exit_code == 1
    assert "domain context" in result.output
    # Refused publication writes nothing to the run layout.
    assert not (article_dir / "extraction-runs").exists() or not list(
        (article_dir / "extraction-runs").iterdir()
    )
    assert not (article_dir / "active-run.json").exists()


def test_agent_record_extraction_rejects_unknown_article(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.article_store_dir.mkdir(parents=True)
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))

    result = CliRunner().invoke(cli.app, ["agent", "record-extraction", "nope"])

    assert result.exit_code == 2
    assert "unknown article: nope" in result.output


# ── runs list / activate ─────────────────────────────────────────────────────


def _publish_second_run(article_dir: Path, run_id: str, *, error: bool = False) -> None:
    """Add a second published run beside whatever record-extraction wrote."""
    from tests.helpers import publish_test_run

    payload = (
        {"article_id": "smith-2024", "error": True, "reason": "bad scan"}
        if error
        else {"article_id": "smith-2024", "title": "Second"}
    )
    publish_test_run(article_dir, payload, run_id=run_id, activate=False)


def test_runs_activate_switches_the_active_pointer(tmp_path: Path, monkeypatch) -> None:
    cfg, article_dir = _publishable_project(tmp_path)
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))
    runner = CliRunner()
    assert runner.invoke(cli.app, ["agent", "record-extraction", "smith-2024"]).exit_code == 0
    first = json.loads((article_dir / "active-run.json").read_text())["run_id"]
    _publish_second_run(article_dir, "01SECONDRUN00000000000000")

    result = runner.invoke(
        cli.app, ["runs", "activate", "smith-2024", "01SECONDRUN00000000000000"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads((article_dir / "active-run.json").read_text()) == {
        "run_id": "01SECONDRUN00000000000000"
    }
    # Activation mutates neither run.
    assert (article_dir / "extraction-runs" / first / "run.json").is_file()


def test_runs_activate_rejects_unknown_and_error_runs(tmp_path: Path, monkeypatch) -> None:
    cfg, article_dir = _publishable_project(tmp_path)
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))
    runner = CliRunner()
    assert runner.invoke(cli.app, ["agent", "record-extraction", "smith-2024"]).exit_code == 0
    original = (article_dir / "active-run.json").read_text()
    _publish_second_run(article_dir, "01ERRORRUN000000000000000", error=True)

    missing = runner.invoke(cli.app, ["runs", "activate", "smith-2024", "01NOSUCHRUN00000000000000"])
    assert missing.exit_code == 1
    assert "not a published run" in missing.output

    errored = runner.invoke(cli.app, ["runs", "activate", "smith-2024", "01ERRORRUN000000000000000"])
    assert errored.exit_code == 1
    assert "error-marker" in errored.output

    traversal = runner.invoke(cli.app, ["runs", "activate", "smith-2024", "../escape"])
    assert traversal.exit_code == 1

    # Every refusal leaves the pointer untouched.
    assert (article_dir / "active-run.json").read_text() == original


def test_runs_list_marks_active_and_reports_model(tmp_path: Path, monkeypatch) -> None:
    cfg, article_dir = _publishable_project(tmp_path)
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))
    runner = CliRunner()
    assert (
        runner.invoke(
            cli.app,
            ["agent", "record-extraction", "smith-2024", "--model", "claude-sonnet-5"],
        ).exit_code
        == 0
    )
    _publish_second_run(article_dir, "01SECONDRUN00000000000000")

    result = runner.invoke(cli.app, ["runs", "list", "smith-2024"])

    assert result.exit_code == 0, result.output
    assert "claude-sonnet-5" in result.output
    assert result.output.count("01SECONDRUN00000000000000") == 1
    active_lines = [line for line in result.output.splitlines() if "active" in line]
    assert len(active_lines) == 1  # exactly one run is active


def test_status_counts_reviews_bound_to_the_active_run(tmp_path: Path, monkeypatch) -> None:
    """The counter must read where reviews actually live.

    It globbed the v1 article-root `review.json`, a path nothing writes any
    more, so it reported 0 unconditionally — which reads as "no review work
    yet" rather than "this number is broken".
    """
    from litschema.articles import article_files as _article_files
    from litschema.reviews import upsert_review
    from litschema.runs import active_run

    cfg, article_dir = _publishable_project(tmp_path)
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))
    runner = CliRunner()
    assert runner.invoke(cli.app, ["agent", "record-extraction", "smith-2024"]).exit_code == 0

    assert "0 articles with reviews" in runner.invoke(cli.app, ["status"]).output

    run = active_run(_article_files(cfg, "smith-2024"))
    upsert_review(run, "title", {})

    output = runner.invoke(cli.app, ["status"]).output
    assert "1 articles with reviews" in output
    assert "(1 entries on active runs)" in output
