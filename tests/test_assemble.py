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


# ── Extraction provenance lands in the manifest, not a CSV ───────────────────


def test_agent_record_extraction_updates_manifest(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    article_dir = cfg.article_store_dir / "smith-2024"
    article_dir.mkdir(parents=True)
    (article_dir / "article-metadata.json").write_text(json.dumps({"id": "smith-2024"}))
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))
    monkeypatch.setattr(cli, "_schema_commit", lambda cfg: "abc1234")

    result = CliRunner().invoke(
        cli.app,
        ["agent", "record-extraction", "smith-2024", "--provider", "codex", "--model", "gpt-5.5"],
    )

    assert result.exit_code == 0, result.output
    metadata = json.loads((article_dir / "article-metadata.json").read_text())
    assert metadata["extraction"]["provider"] == "codex"
    assert metadata["extraction"]["model"] == "gpt-5.5"
    assert metadata["extraction"]["schema_commit"] == "abc1234"
    assert "date" in metadata["extraction"]


def test_agent_record_extraction_rejects_unknown_article(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.article_store_dir.mkdir(parents=True)
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))

    result = CliRunner().invoke(cli.app, ["agent", "record-extraction", "nope"])

    assert result.exit_code == 2
    assert "unknown article: nope" in result.output
