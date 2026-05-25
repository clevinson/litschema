from __future__ import annotations

import json
from pathlib import Path

from litschema.config import LitSchemaConfig
from litschema.ingest import openalex_harvest


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


def test_openalex_harvest_reads_articles_csv_and_writes_article_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        "10.1234/example,smith-2024,CSV title,,,,,,,\n"
    )
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        openalex_harvest,
        "fetch_openalex",
        lambda doi, email=None: {
            "id": "https://openalex.org/W1",
            "doi": f"https://doi.org/{doi}",
            "title": "OpenAlex title",
            "publication_year": 2024,
            "primary_location": {"source": {"display_name": "Example Journal"}},
        },
    )

    stats = openalex_harvest.harvest(cfg, source_path=source)

    metadata = json.loads(
        (cfg.article_store_dir / "smith-2024" / "article-metadata.json").read_text()
    )
    assert stats["fetched"] == 1
    assert metadata == {
        "id": "smith-2024",
        "doi": "10.1234/example",
        "title": "CSV title",
        "year": 2024,
        "journal": "Example Journal",
    }


def test_openalex_harvest_preserves_existing_pdf_filename(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        "10.1234/example,smith-2024,CSV title,,,,,,,\n"
    )
    article_dir = cfg.article_store_dir / "smith-2024"
    article_dir.mkdir(parents=True)
    (article_dir / "article-metadata.json").write_text(
        json.dumps({"id": "smith-2024", "filename": "smith-2024.pdf", "notes": "curated"})
    )
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        openalex_harvest,
        "fetch_openalex",
        lambda doi, email=None: {
            "id": "https://openalex.org/W1",
            "doi": f"https://doi.org/{doi}",
            "title": "OpenAlex title",
            "publication_year": 2024,
        },
    )

    openalex_harvest.harvest(cfg, source_path=source)

    metadata = json.loads((article_dir / "article-metadata.json").read_text())
    assert metadata["filename"] == "smith-2024.pdf"
    assert metadata["notes"] == "curated"
    assert metadata["title"] == "CSV title"


def test_openalex_harvest_keeps_doi_less_rows_and_writes_curated_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        ",carbon-direct-2024,Buyer guide,Carbon Direct,2024,Carbon Direct,true,,,,\n"
        "10.1234/example,smith-2024,CSV title,,,,,,,,\n"
    )
    seen_dois = []

    def fake_fetch(doi: str, email: str | None = None) -> dict:
        seen_dois.append(doi)
        return {
            "id": "https://openalex.org/W1",
            "doi": f"https://doi.org/{doi}",
            "title": "OpenAlex title",
            "publication_year": 2024,
        }

    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", fake_fetch)

    stats = openalex_harvest.harvest(cfg, source_path=source)

    assert seen_dois == ["10.1234/example"]
    assert stats["total"] == 2
    assert stats["missing_doi"] == 1
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


def test_openalex_harvest_skips_malformed_doi_without_fetching(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        "ISSN: 2278-4632,singh-bano-2024,Geoengineering,Singh & Bano,2024,Other,false,,,,\n"
    )
    monkeypatch.setattr(
        openalex_harvest,
        "fetch_openalex",
        lambda doi, email=None: (_ for _ in ()).throw(AssertionError("should not fetch")),
    )

    stats = openalex_harvest.harvest(cfg, source_path=source)

    assert stats["invalid_doi"] == 1
    metadata = json.loads(
        (cfg.article_store_dir / "singh-bano-2024" / "article-metadata.json").read_text()
    )
    assert metadata["id"] == "singh-bano-2024"
    assert metadata["title"] == "Geoengineering"


def test_openalex_harvest_does_not_write_incomplete_doi_less_metadata(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        ",carbon-direct-2024,,,,,,,,,\n"
    )

    stats = openalex_harvest.harvest(cfg, source_path=source)

    assert stats["missing_doi"] == 1
    assert stats["missing_metadata"] == 1
    assert not (cfg.article_store_dir / "carbon-direct-2024" / "article-metadata.json").exists()


def test_openalex_harvest_requires_title_and_citation_anchor_for_doi_less_metadata(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text(
        "doi,article_id,title,author_citation,year,publisher,open_access,"
        "extraction_provider,extraction_model,extraction_date,schema_commit\n"
        ",year-only-2024,,,2024,,,,,,\n"
        ",open-access-only,,,,,,true,,,,\n"
    )

    stats = openalex_harvest.harvest(cfg, source_path=source)

    assert stats["missing_doi"] == 2
    assert stats["missing_metadata"] == 2
    assert not (cfg.article_store_dir / "year-only-2024" / "article-metadata.json").exists()
    assert not (cfg.article_store_dir / "open-access-only" / "article-metadata.json").exists()


def test_openalex_harvest_rejects_legacy_id_column(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    source = cfg.data_dir / "sources" / "articles.csv"
    source.parent.mkdir(parents=True)
    source.write_text("id,doi,title\nsmith-2024,10.1234/example,CSV title\n")

    try:
        openalex_harvest.harvest(cfg, source_path=source)
    except ValueError as exc:
        assert "article_id" in str(exc)
    else:
        raise AssertionError("legacy id column should be rejected")
