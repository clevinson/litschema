from __future__ import annotations

import json
from pathlib import Path

import yaml

from litschema import analysis
from litschema.config import LitSchemaConfig
from litschema.ingest import assemble_corpus, pdf_to_markdown


def _cfg(project: Path) -> LitSchemaConfig:
    return LitSchemaConfig(
        config_path=project / "litschema.yaml",
        project_root=project,
        data_dir=project / "data",
        schema_dir=project / "schema",
        references_dir=project / "references",
        corpus_file=project / "corpus.yaml",
        tracking_xlsx=project / "paper_download_tracking.xlsx",
        openalex_dir=project / "data" / "openalex_raw",
        crossref_dir=project / "data" / "crossref_raw",
        fulltext_md_dir=project / "data" / "fulltext_md",
        llm_extractions_dir=project / "data" / "llm_extractions",
        extraction_reasoning_dir=project / "data" / "extraction_reasoning",
        annotations_dir=project / "data" / "reviews",
        papers_dir=project / "papers",
        static_site_dir=project / "static-site",
        article_store_dir=project / "data" / "papers",
        raw={},
    )


def test_assemble_corpus_loads_extraction_from_article_folder(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    article_dir = cfg.article_store_dir / "smith-2024"
    article_dir.mkdir(parents=True)
    (article_dir / "agent-extraction.json").write_text(
        json.dumps({"article_id": "smith-2024", "confidence": 0.85})
    )
    legacy_dir = cfg.llm_extractions_dir
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "smith-2024.json").write_text(
        json.dumps({"article_id": "smith-2024", "confidence": 0.1})
    )
    monkeypatch.setattr(assemble_corpus, "_CFG", cfg)

    extraction = assemble_corpus.load_llm_extraction("smith-2024")

    assert extraction is not None
    assert extraction["confidence"] == 0.85


def test_pdf_conversion_defaults_to_article_folder(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    cfg.papers_dir.mkdir(parents=True)
    cfg.corpus_file.write_text(
        yaml.safe_dump({"articles": [{"id": "smith-2024", "filename": "smith.pdf"}]})
    )
    (cfg.papers_dir / "smith.pdf").write_text("pdf placeholder")
    monkeypatch.setattr(pdf_to_markdown, "_CFG", cfg)

    def fake_convert_pdf(pdf_path: Path, out_path: Path) -> int:
        out_path.write_text("# Smith\n")
        return 250

    monkeypatch.setattr(pdf_to_markdown, "convert_pdf", fake_convert_pdf)

    stats = pdf_to_markdown.run(
        corpus_path=cfg.corpus_file,
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
