from __future__ import annotations

import json
from pathlib import Path

from litschema import analysis
from litschema.webapp import app as webapp
from litschema.config import LitSchemaConfig
from litschema.ingest import pdf_to_markdown


def _cfg(project: Path) -> LitSchemaConfig:
    return LitSchemaConfig(
        config_path=project / "litschema.yaml",
        project_root=project,
        data_dir=project / "data",
        schema_dir=project / "schema",
        references_dir=project / "references",
        tracking_xlsx=project / "paper_download_tracking.xlsx",
        fulltext_md_dir=project / "data" / "fulltext_md",
        llm_extractions_dir=project / "data" / "llm_extractions",
        extraction_reasoning_dir=project / "data" / "extraction_reasoning",
        annotations_dir=project / "data" / "reviews",
        papers_dir=project / "papers",
        static_site_dir=project / "static-site",
        article_store_dir=project / "data" / "papers",
        raw={},
    )


def test_pdf_conversion_defaults_to_article_folder(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    cfg.papers_dir.mkdir(parents=True)
    article_dir = cfg.article_store_dir / "smith-2024"
    article_dir.mkdir(parents=True)
    (article_dir / "article-metadata.json").write_text(
        json.dumps({"id": "smith-2024", "filename": "smith.pdf"})
    )
    (cfg.papers_dir / "smith.pdf").write_text("pdf placeholder")

    def fake_convert_pdf(pdf_path: Path, out_path: Path) -> int:
        out_path.write_text("# Smith\n")
        return 250

    monkeypatch.setattr(pdf_to_markdown, "convert_pdf", fake_convert_pdf)

    stats = pdf_to_markdown.run(
        cfg,
        papers_dir=cfg.papers_dir,
        output_dir=None,
    )

    assert stats["converted"] == 1
    assert (cfg.article_store_dir / "smith-2024" / "article.md").read_text() == "# Smith\n"
    assert not (cfg.fulltext_md_dir / "smith-2024.md").exists()


def test_analysis_loads_extractions_from_article_folders(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    article_dir = cfg.article_store_dir / "smith-2024"
    article_dir.mkdir(parents=True)
    (article_dir / "agent-extraction.json").write_text(
        json.dumps({"article_id": "smith-2024", "confidence": 0.8})
    )
    monkeypatch.setattr(analysis, "load_config", lambda: cfg)

    dfs = analysis.load_extractions()

    assert dfs["articles"]["article_id"].tolist() == ["smith-2024"]
    assert dfs["articles"]["confidence"].tolist() == [0.8]


def test_webapp_reads_bibliography_and_pdf_filename_from_article_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    article_dir = cfg.article_store_dir / "smith-2024"
    article_dir.mkdir(parents=True)
    (article_dir / "article-metadata.json").write_text(
        json.dumps(
            {
                "id": "smith-2024",
                "title": "Smith example",
                "year": 2024,
                "doi": "10.1234/example",
                "journal": "Example Journal",
                "publisher": "Example Publisher",
                "filename": "smith.pdf",
            }
        )
    )
    monkeypatch.setattr(webapp, "_author_index_by_path", {})

    assert webapp._article_meta(cfg, "smith-2024") == {
        "title": "Smith example",
        "year": 2024,
        "journal": "Example Journal",
        "doi": "10.1234/example",
        "publisher": "Example Publisher",
        "authors": [],
    }
    assert webapp._article_pdf_filename(cfg, "smith-2024") == "smith.pdf"


def test_webapp_computes_article_review_progress() -> None:
    extraction = {
        "article_id": "smith-2024",
        "confidence": 0.9,
        "document_type": "journal_article",
        "study_types": ["experimental", "modeling"],
        "experimental_setups": [
            {
                "experimental_scale": "field",
                "soil": {"texture_class": "silt"},
            }
        ],
    }
    annotations = [
        {"path": ".document_type", "status": "verified"},
        {"path": ".study_types[0]", "status": "flagged"},
        {"path": ".study_types[1]", "status": "cleared"},
        {"path": ".experimental_setups[0].trial_type", "status": "verified"},
    ]

    assert webapp._review_progress(extraction, annotations) == {
        "n_fields": 5,
        "n_reviewed": 3,
        "n_verified": 2,
        "n_flagged": 1,
        "is_complete": False,
        "has_flags": True,
    }
