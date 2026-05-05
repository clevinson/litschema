from __future__ import annotations

import json
from pathlib import Path

import yaml

from litschema.config import LitSchemaConfig
from litschema.ingest.migrate_article_layout import migrate_article_layout


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


def test_migrate_article_layout_copies_legacy_artifacts_to_article_folder(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path)
    for path in (
        cfg.llm_extractions_dir,
        cfg.extraction_reasoning_dir,
        cfg.annotations_dir,
        cfg.fulltext_md_dir,
    ):
        path.mkdir(parents=True)

    (cfg.llm_extractions_dir / "smith-2024.json").write_text(
        json.dumps({"article_id": "smith-2024", "confidence": 0.8})
    )
    (cfg.extraction_reasoning_dir / "smith-2024.json").write_text(
        json.dumps({"fields": [{"path": ".confidence"}]})
    )
    (cfg.annotations_dir / "smith-2024.json").write_text(
        json.dumps(
            {
                "article_id": "smith-2024",
                "annotations": [{"path": ".confidence", "status": "verified"}],
            }
        )
    )
    (cfg.fulltext_md_dir / "smith-2024.md").write_text("# Smith\n")
    cfg.corpus_file.write_text(
        yaml.safe_dump(
            {
                "articles": [
                    {
                        "id": "smith-2024",
                        "doi": "10.1234/example",
                        "title": "Smith example",
                    }
                ]
            }
        )
    )

    summary = migrate_article_layout(cfg)

    article_dir = cfg.article_store_dir / "smith-2024"
    assert summary["articles"] == 1
    assert json.loads((article_dir / "agent-extraction.json").read_text())["confidence"] == 0.8
    assert json.loads((article_dir / "agent-reasoning.json").read_text())["fields"][0]["path"] == (
        ".confidence"
    )
    assert (article_dir / "article.md").read_text() == "# Smith\n"
    assert json.loads((article_dir / "article-metadata.json").read_text())["doi"] == (
        "10.1234/example"
    )
    assert (article_dir / "reviews.jsonl").read_text().splitlines() == [
        json.dumps(
            {
                "path": ".confidence",
                "status": "verified",
                "article_id": "smith-2024",
            }
        )
    ]
