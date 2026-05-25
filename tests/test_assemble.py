from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from litschema import cli
from litschema.config import LitSchemaConfig
from litschema.ingest import article_assembly, openalex_harvest


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


def _fake_openalex_response(doi: str) -> dict:
    return {
        "id": "https://openalex.org/W1",
        "doi": f"https://doi.org/{doi}",
        "title": "OpenAlex title",
        "publication_year": 2024,
        "open_access": {"is_oa": True},
        "primary_location": {"source": {"host_organization_name": "Example Publisher"}},
        "authorships": [
            {"author": {"display_name": "Jane Smith"}},
            {"author": {"display_name": "Max Doe"}},
        ],
    }


def test_assemble_populates_metadata_for_doi_only_registry_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        "10.1234/example,,,,,,,,,,\n"
    )
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fake_openalex_response)

    stats = article_assembly.assemble(cfg)

    assert stats["harvested"] == 1
    assert source.read_text().splitlines()[1].startswith(
        "10.1234/example,smith-2024,OpenAlex title,Smith & Doe,2024,Example Publisher,true,"
    )
    metadata = json.loads(
        (cfg.article_store_dir / "smith-2024" / "article-metadata.json").read_text()
    )
    assert metadata["id"] == "smith-2024"
    assert metadata["doi"] == "10.1234/example"
    assert metadata["title"] == "OpenAlex title"
    assert metadata["open_access"] is True


def test_assemble_enriches_complete_registry_rows_without_existing_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        "10.1234/example,smith-2024,Registry title,Smith & Doe,2024,Example Publisher,true,"
        ",,,\n"
    )
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        openalex_harvest,
        "fetch_openalex",
        lambda doi: {
            **_fake_openalex_response(doi),
            "abstract_inverted_index": {"Harvested": [0], "abstract": [1]},
            "primary_location": {
                "source": {
                    "display_name": "Example Journal",
                    "host_organization_name": "Example Publisher",
                }
            },
        },
    )

    stats = article_assembly.assemble(cfg)

    assert stats["harvested"] == 1
    metadata = json.loads(
        (cfg.article_store_dir / "smith-2024" / "article-metadata.json").read_text()
    )
    assert metadata["title"] == "Registry title"
    assert metadata["abstract"] == "Harvested abstract"
    assert metadata["journal"] == "Example Journal"


def test_assemble_writes_complete_registry_metadata_when_openalex_not_found(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        "10.1234/example,smith-2024,Registry title,Smith & Doe,2024,Example Publisher,true,"
        ",,,\n"
    )
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", lambda doi: None)

    stats = article_assembly.assemble(cfg)

    assert stats["harvested"] == 0
    metadata = json.loads(
        (cfg.article_store_dir / "smith-2024" / "article-metadata.json").read_text()
    )
    assert metadata == {
        "id": "smith-2024",
        "doi": "10.1234/example",
        "title": "Registry title",
        "year": "2024",
        "publisher": "Example Publisher",
        "author_citation": "Smith & Doe",
        "open_access": True,
    }


def test_assemble_preserves_existing_metadata_for_complete_registry_rows(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        "10.1234/example,smith-2024,Registry title,Smith & Doe,2024,Example Publisher,true,"
        ",,,\n"
    )
    article_dir = cfg.article_store_dir / "smith-2024"
    article_dir.mkdir(parents=True)
    (article_dir / "article-metadata.json").write_text(
        json.dumps({"id": "smith-2024", "title": "Old title", "abstract": "Curated abstract"})
    )

    stats = article_assembly.assemble(cfg)

    assert stats["harvested"] == 0
    metadata = json.loads(
        (article_dir / "article-metadata.json").read_text()
    )
    assert metadata["id"] == "smith-2024"
    assert metadata["title"] == "Registry title"
    assert metadata["abstract"] == "Curated abstract"


def test_assemble_treats_cached_openalex_errors_as_missing_metadata(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        "10.1234/example,,,,,,,,,,\n"
    )
    cache_dir = cfg.data_dir / "harvest" / "openalex"
    cache_dir.mkdir(parents=True)
    (cache_dir / "10_1234_example.json").write_text(
        json.dumps({"doi": "10.1234/example", "error": "not_found"})
    )

    stats = article_assembly.assemble(cfg)

    assert stats["harvested"] == 0
    assert stats["missing_metadata_rows"] == 1
    assert not (cfg.article_store_dir / "10_1234_example" / "article-metadata.json").exists()


def test_assemble_writes_metadata_for_doi_less_registry_rows(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        ",carbon-direct-2024,Buyer guide,Carbon Direct,2024,Carbon Direct,true,,,,\n"
    )
    monkeypatch.setattr(
        openalex_harvest,
        "fetch_openalex",
        lambda doi: (_ for _ in ()).throw(AssertionError("should not fetch")),
    )

    stats = article_assembly.assemble(cfg)

    assert stats["metadata_only"] == 1
    metadata = json.loads(
        (cfg.article_store_dir / "carbon-direct-2024" / "article-metadata.json").read_text()
    )
    assert metadata == {
        "id": "carbon-direct-2024",
        "title": "Buyer guide",
        "year": "2024",
        "publisher": "Carbon Direct",
        "author_citation": "Carbon Direct",
        "open_access": True,
    }


def test_assemble_reports_incomplete_doi_less_rows_without_writing_metadata(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        ",carbon-direct-2024,,,,,,,,,\n"
    )

    stats = article_assembly.assemble(cfg)

    assert stats["metadata_only"] == 0
    assert stats["missing_metadata_rows"] == 1
    assert not (cfg.article_store_dir / "carbon-direct-2024" / "article-metadata.json").exists()


def test_assemble_requires_title_and_citation_anchor_for_doi_less_metadata(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        ",year-only-2024,,,2024,,,,,,\n"
        ",open-access-only,,,,,true,,,,\n"
    )

    stats = article_assembly.assemble(cfg)

    assert stats["metadata_only"] == 0
    assert stats["missing_metadata_rows"] == 2
    assert not (cfg.article_store_dir / "year-only-2024" / "article-metadata.json").exists()
    assert not (cfg.article_store_dir / "open-access-only" / "article-metadata.json").exists()


def test_assemble_omits_invalid_doi_from_metadata_only_rows(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        "ISSN: 2278-4632,singh-bano-2024,Geoengineering,Singh & Bano,2024,Other,false,,,,\n"
    )

    stats = article_assembly.assemble(cfg)

    assert stats["metadata_only"] == 1
    assert stats["invalid_doi_rows"] == 1
    metadata = json.loads(
        (cfg.article_store_dir / "singh-bano-2024" / "article-metadata.json").read_text()
    )
    assert "doi" not in metadata


def test_assemble_removes_stale_doi_for_doi_less_metadata_only_rows(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        ",carbon-direct-2024,Buyer guide,Carbon Direct,2024,Carbon Direct,true,,,,\n"
    )
    article_dir = cfg.article_store_dir / "carbon-direct-2024"
    article_dir.mkdir(parents=True)
    (article_dir / "article-metadata.json").write_text(
        json.dumps({"id": "carbon-direct-2024", "doi": "10.1234/stale"})
    )

    article_assembly.assemble(cfg)

    metadata = json.loads((article_dir / "article-metadata.json").read_text())
    assert "doi" not in metadata


def test_assemble_normalizes_doi_urls_when_upserting_inbox_pdfs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        "https://doi.org/10.1234/example,,,,,,,,,,\n"
    )
    cfg.paper_inbox_dir.mkdir(parents=True)
    (cfg.paper_inbox_dir / "Downloaded Article.pdf").write_text("pdf placeholder")

    monkeypatch.setattr(
        article_assembly,
        "_doi_from_pdf_text",
        lambda pdf_path: ("10.1234/example", "found"),
    )
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fake_openalex_response)

    article_assembly.assemble(cfg)

    rows = source.read_text().splitlines()
    assert len(rows) == 2
    assert rows[1].startswith("10.1234/example,smith-2024,")


def test_assemble_does_not_use_reference_doi_far_from_pdf_start(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    (cfg.data_dir / "sources").mkdir(parents=True)
    (cfg.data_dir / "sources" / "articles.csv").write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
    )
    cfg.paper_inbox_dir.mkdir(parents=True)
    inbox_pdf = cfg.paper_inbox_dir / "Report.pdf"
    inbox_pdf.write_text("pdf placeholder")

    monkeypatch.setattr(article_assembly, "_doi_from_pdf_text", lambda pdf_path: (None, "missing_doi"))
    monkeypatch.setattr(
        openalex_harvest,
        "fetch_openalex",
        lambda doi: (_ for _ in ()).throw(AssertionError("should not fetch")),
    )

    stats = article_assembly.assemble(cfg)

    assert stats["missing_doi_pdfs"] == 1
    assert inbox_pdf.exists()
    assert not any(cfg.article_store_dir.iterdir())


def test_assemble_reports_ambiguous_top_of_pdf_dois_without_fetching(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    (cfg.data_dir / "sources").mkdir(parents=True)
    (cfg.data_dir / "sources" / "articles.csv").write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
    )
    cfg.paper_inbox_dir.mkdir(parents=True)
    inbox_pdf = cfg.paper_inbox_dir / "Article.pdf"
    inbox_pdf.write_text("pdf placeholder")

    monkeypatch.setattr(article_assembly, "_doi_from_pdf_text", lambda pdf_path: (None, "ambiguous_doi"))
    monkeypatch.setattr(
        openalex_harvest,
        "fetch_openalex",
        lambda doi: (_ for _ in ()).throw(AssertionError("should not fetch")),
    )

    stats = article_assembly.assemble(cfg)

    assert stats["ambiguous_doi_pdfs"] == 1
    assert inbox_pdf.exists()
    assert not any(cfg.article_store_dir.iterdir())


def test_assemble_moves_detected_inbox_pdf_into_canonical_article_folder(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    (cfg.data_dir / "sources").mkdir(parents=True)
    (cfg.data_dir / "sources" / "articles.csv").write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
    )
    cfg.paper_inbox_dir.mkdir(parents=True)
    inbox_pdf = cfg.paper_inbox_dir / "Downloaded Article.pdf"
    inbox_pdf.write_text("pdf placeholder")

    monkeypatch.setattr(
        article_assembly,
        "_doi_from_pdf_text",
        lambda pdf_path: ("10.1234/example", "found"),
    )
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fake_openalex_response)

    stats = article_assembly.assemble(cfg)

    article_dir = cfg.article_store_dir / "smith-2024"
    assert stats["inbox_pdfs"] == 1
    assert stats["assembled_pdfs"] == 1
    assert stats["harvested"] == 1
    assert (article_dir / "smith-2024.pdf").read_text() == "pdf placeholder"
    assert not (article_dir / "article.md").exists()
    assert not inbox_pdf.exists()
    assert (cfg.paper_inbox_dir / ".processed" / "Downloaded Article.pdf").read_text() == (
        "pdf placeholder"
    )
    assert json.loads((article_dir / "article-metadata.json").read_text())["filename"] == (
        "smith-2024.pdf"
    )


def test_assemble_uses_pdf_text_doi_scan_for_inbox_pdfs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    (cfg.data_dir / "sources").mkdir(parents=True)
    (cfg.data_dir / "sources" / "articles.csv").write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
    )
    cfg.paper_inbox_dir.mkdir(parents=True)
    (cfg.paper_inbox_dir / "Downloaded Article.pdf").write_text("pdf placeholder")

    monkeypatch.setattr(
        article_assembly,
        "_doi_from_pdf_text",
        lambda pdf_path: ("10.1234/example", "found"),
    )
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fake_openalex_response)

    stats = article_assembly.assemble(cfg)

    assert stats["assembled_pdfs"] == 1
    assert "10.1234/example" in (cfg.data_dir / "sources" / "articles.csv").read_text()


def test_assemble_does_not_overwrite_already_assembled_article_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    (cfg.data_dir / "sources").mkdir(parents=True)
    (cfg.data_dir / "sources" / "articles.csv").write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
    )
    cfg.paper_inbox_dir.mkdir(parents=True)
    (cfg.paper_inbox_dir / "Downloaded Article.pdf").write_text("pdf placeholder")

    monkeypatch.setattr(
        article_assembly,
        "_doi_from_pdf_text",
        lambda pdf_path: ("10.1234/example", "found"),
    )
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fake_openalex_response)

    article_assembly.assemble(cfg)
    article_dir = cfg.article_store_dir / "smith-2024"
    (article_dir / "smith-2024.pdf").write_text("curated pdf")
    (cfg.paper_inbox_dir / "Downloaded Article.pdf").write_text("duplicate inbox pdf")

    stats = article_assembly.assemble(cfg)

    assert stats["assembled_pdfs"] == 0
    assert stats["already_assembled_pdfs"] == 1
    assert (article_dir / "smith-2024.pdf").read_text() == "curated pdf"
    assert not (cfg.paper_inbox_dir / "Downloaded Article.pdf").exists()
    assert (cfg.paper_inbox_dir / ".processed" / "Downloaded Article.pdf").exists()


def test_assemble_continues_after_pdf_intake_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    (cfg.data_dir / "sources").mkdir(parents=True)
    (cfg.data_dir / "sources" / "articles.csv").write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
    )
    cfg.paper_inbox_dir.mkdir(parents=True)
    (cfg.paper_inbox_dir / "Bad.pdf").write_text("bad pdf")
    (cfg.paper_inbox_dir / "Good.pdf").write_text("good pdf")

    def fake_doi_from_pdf_text(pdf_path: Path) -> tuple[str | None, str]:
        if pdf_path.name == "Bad.pdf":
            raise RuntimeError("intake failed")
        return "10.1234/example", "found"

    monkeypatch.setattr(article_assembly, "_doi_from_pdf_text", fake_doi_from_pdf_text)
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fake_openalex_response)

    stats = article_assembly.assemble(cfg)

    assert stats["error_pdfs"] == 1
    assert stats["assembled_pdfs"] == 1
    assert (cfg.article_store_dir / "smith-2024" / "smith-2024.pdf").exists()
    assert (cfg.paper_inbox_dir / "Bad.pdf").exists()
    assert not (cfg.paper_inbox_dir / "Good.pdf").exists()


def test_assemble_persists_registry_after_each_successful_inbox_pdf(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    registry = cfg.data_dir / "sources" / "articles.csv"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
    )
    cfg.paper_inbox_dir.mkdir(parents=True)
    (cfg.paper_inbox_dir / "A Good.pdf").write_text("good pdf")
    (cfg.paper_inbox_dir / "B Interrupted.pdf").write_text("interrupted pdf")

    def fake_doi_from_pdf_text(pdf_path: Path) -> tuple[str | None, str]:
        if pdf_path.name == "B Interrupted.pdf":
            raise KeyboardInterrupt
        return "10.1234/example", "found"

    monkeypatch.setattr(article_assembly, "_doi_from_pdf_text", fake_doi_from_pdf_text)
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fake_openalex_response)

    with suppress(article_assembly.AssemblyInterrupted):
        article_assembly.assemble(cfg)

    assert "10.1234/example" in registry.read_text()
    assert "smith-2024" in registry.read_text()


def test_assemble_treats_wrapped_keyboard_interrupt_as_cancellation(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    cfg = _cfg(tmp_path)
    registry = cfg.data_dir / "sources" / "articles.csv"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
    )
    cfg.paper_inbox_dir.mkdir(parents=True)
    inbox_pdf = cfg.paper_inbox_dir / "Interrupted.pdf"
    inbox_pdf.write_text("interrupted pdf")

    def fake_doi_from_pdf_text(pdf_path: Path) -> tuple[str | None, str]:
        raise RuntimeError("Director error: <class 'KeyboardInterrupt'>")

    monkeypatch.setattr(article_assembly, "_doi_from_pdf_text", fake_doi_from_pdf_text)

    with pytest.raises(article_assembly.AssemblyInterrupted) as excinfo:
        article_assembly.assemble(cfg)

    assert excinfo.value.pdf_path == inbox_pdf
    assert "Failed to assemble inbox PDF" not in caplog.text


def test_assemble_recovers_registry_rows_from_existing_article_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    registry = cfg.data_dir / "sources" / "articles.csv"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
    )
    article_dir = cfg.article_store_dir / "smith-2024"
    article_dir.mkdir(parents=True)
    (article_dir / "article-metadata.json").write_text(
        json.dumps(
            {
                "id": "smith-2024",
                "doi": "10.1234/example",
                "title": "Recovered title",
                "author_citation": "Smith et al.",
                "year": "2024",
                "publisher": "Recovered Publisher",
                "open_access": True,
            }
        )
    )
    monkeypatch.setattr(
        openalex_harvest,
        "fetch_openalex",
        lambda doi: (_ for _ in ()).throw(AssertionError("should use existing metadata")),
    )

    article_assembly.assemble(cfg)

    text = registry.read_text()
    assert "10.1234/example" in text
    assert "smith-2024" in text
    assert "Recovered title" in text


def test_assemble_merges_existing_metadata_into_matching_registry_row(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    registry = cfg.data_dir / "sources" / "articles.csv"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        "10.1234/example,,,,,,,,,,\n"
    )
    article_dir = cfg.article_store_dir / "smith-2024"
    article_dir.mkdir(parents=True)
    (article_dir / "article-metadata.json").write_text(
        json.dumps(
            {
                "id": "smith-2024",
                "doi": "10.1234/example",
                "title": "Recovered title",
                "author_citation": "Smith et al.",
                "year": "2024",
                "publisher": "Recovered Publisher",
                "open_access": True,
            }
        )
    )
    monkeypatch.setattr(
        openalex_harvest,
        "fetch_openalex",
        lambda doi: (_ for _ in ()).throw(AssertionError("should use existing metadata")),
    )

    article_assembly.assemble(cfg)

    rows = registry.read_text().splitlines()
    assert len(rows) == 2
    assert rows[1].startswith(
        "10.1234/example,smith-2024,Recovered title,Smith et al.,2024,"
        "Recovered Publisher,true,"
    )
    assert not (cfg.article_store_dir / "smith-2024-2").exists()


def test_assemble_cli_runs_project_assembly(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.config_path.write_text('project_root: "."\n')
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))

    def fake_assemble(cfg, reporter=None):
        assert reporter is not None
        reporter("start", {"inbox_pdfs": 2})
        reporter(
            "pdf",
            {
                "path": Path("papers-inbox/good.pdf"),
                "result": "assembled",
                "doi": "10.1234/example",
                "harvested": True,
            },
        )
        reporter("pdf_error", {"path": Path("papers-inbox/bad.pdf"), "error": RuntimeError("bad")})
        reporter("stage", {"name": "registry", "total": 1})
        reporter(
            "row",
            {
                "row": {"doi": "10.1234/example", "article_id": "smith-2024"},
                "result": "ok",
                "harvested": False,
            },
        )
        return {
            "inbox_pdfs": 2,
            "assembled_pdfs": 1,
            "already_assembled_pdfs": 0,
            "missing_doi_pdfs": 0,
            "ambiguous_doi_pdfs": 0,
            "missing_metadata_pdfs": 0,
            "error_pdfs": 1,
            "metadata_only": 0,
            "invalid_doi_rows": 0,
            "missing_metadata_rows": 0,
            "harvested": 1,
        }

    monkeypatch.setattr(article_assembly, "assemble", fake_assemble)

    result = CliRunner().invoke(cli.app, ["assemble"])

    assert result.exit_code == 0
    assert "Assembling article inputs" in result.output
    assert "Inbox PDFs [##########----------] 1/2" in result.output
    assert "PDF assembled: good.pdf (10.1234/example)" in result.output
    assert "PDF failed: bad.pdf (bad)" in result.output
    assert "Registry rows [" not in result.output
    assert "Summary" in result.output
    assert "assembled_pdfs: 1" in result.output
    assert "error_pdfs: 1" in result.output


def test_assemble_cli_is_concise_when_there_is_no_work(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.config_path.write_text('project_root: "."\n')
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))

    def fake_assemble(cfg, reporter=None):
        assert reporter is not None
        reporter("start", {"inbox_pdfs": 0})
        reporter("stage", {"name": "registry", "total": 2})
        reporter(
            "row",
            {
                "row": {"doi": "10.1234/example", "article_id": "smith-2024"},
                "result": "ok",
                "harvested": False,
            },
        )
        reporter(
            "row",
            {
                "row": {"doi": "10.5678/example", "article_id": "jones-2025"},
                "result": "ok",
                "harvested": False,
            },
        )
        return {
            "inbox_pdfs": 0,
            "assembled_pdfs": 0,
            "already_assembled_pdfs": 0,
            "missing_doi_pdfs": 0,
            "ambiguous_doi_pdfs": 0,
            "missing_metadata_pdfs": 0,
            "error_pdfs": 0,
            "metadata_only": 0,
            "invalid_doi_rows": 0,
            "missing_metadata_rows": 0,
            "harvested": 0,
        }

    monkeypatch.setattr(article_assembly, "assemble", fake_assemble)

    result = CliRunner().invoke(cli.app, ["assemble"])

    assert result.exit_code == 0
    assert "No inbox PDFs found." in result.output
    assert "Inbox PDFs [" not in result.output
    assert "Registry rows [" not in result.output
    assert "Registry harvested" not in result.output
    assert "Summary" in result.output


def test_assemble_cli_reports_keyboard_interrupt_without_traceback(
    tmp_path: Path,
    monkeypatch,
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


def test_agent_record_extraction_updates_registry(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        "10.1234/example,smith-2024,Example,,,,,,,,\n"
    )
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))
    monkeypatch.setattr(cli, "_schema_commit", lambda cfg: "abc1234")

    result = CliRunner().invoke(
        cli.app,
        [
            "agent",
            "record-extraction",
            "smith-2024",
            "--provider",
            "codex",
            "--model",
            "gpt-5.5",
        ],
    )

    assert result.exit_code == 0, result.output
    row = source.read_text().splitlines()[1]
    assert row.startswith("10.1234/example,smith-2024,Example,,,,,codex,gpt-5.5,")
    assert row.endswith(",abc1234")
