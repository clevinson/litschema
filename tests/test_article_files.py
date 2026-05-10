from __future__ import annotations

import json
from pathlib import Path

from litschema.articles import (
    article_files,
    iter_extraction_paths,
    iter_markdown_paths,
    iter_reasoning_paths,
    iter_review_paths,
    read_review_events,
)
from litschema.config import LitSchemaConfig


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


def test_article_files_prefers_per_article_paths_when_present(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    paper_dir = tmp_path / "data" / "papers" / "smith-2024"
    paper_dir.mkdir(parents=True)
    (paper_dir / "agent-extraction.json").write_text('{"article_id": "smith-2024"}')
    (paper_dir / "agent-reasoning.json").write_text('{"fields": []}')
    (paper_dir / "reviews.jsonl").write_text(
        json.dumps({"article_id": "smith-2024", "path": ".confidence"}) + "\n"
    )

    files = article_files(cfg, "smith-2024")

    assert files.extraction_path() == paper_dir / "agent-extraction.json"
    assert files.reasoning_path() == paper_dir / "agent-reasoning.json"
    assert files.reviews_path() == paper_dir / "reviews.jsonl"
    assert read_review_events(files) == [{"article_id": "smith-2024", "path": ".confidence"}]


def test_article_files_falls_back_to_legacy_paths(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    (tmp_path / "data" / "llm_extractions").mkdir(parents=True)
    (tmp_path / "data" / "extraction_reasoning").mkdir(parents=True)
    (tmp_path / "data" / "reviews").mkdir(parents=True)
    (tmp_path / "data" / "fulltext_md").mkdir(parents=True)
    (tmp_path / "data" / "llm_extractions" / "smith-2024.json").write_text("{}")
    (tmp_path / "data" / "extraction_reasoning" / "smith-2024.json").write_text("{}")
    (tmp_path / "data" / "reviews" / "smith-2024.json").write_text(
        json.dumps(
            {
                "article_id": "smith-2024",
                "annotations": [{"path": ".confidence", "status": "verified"}],
            }
        )
    )

    files = article_files(cfg, "smith-2024")

    assert files.extraction_path() == tmp_path / "data" / "llm_extractions" / "smith-2024.json"
    assert files.reasoning_path() == tmp_path / "data" / "extraction_reasoning" / "smith-2024.json"
    assert files.markdown_path() == tmp_path / "data" / "fulltext_md" / "smith-2024.md"
    assert read_review_events(files) == [
        {"path": ".confidence", "status": "verified", "article_id": "smith-2024"}
    ]


def test_iter_extraction_paths_merges_new_and_legacy_without_duplicates(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    (tmp_path / "data" / "papers" / "smith-2024").mkdir(parents=True)
    (tmp_path / "data" / "papers" / "smith-2024" / "agent-extraction.json").write_text("{}")
    (tmp_path / "data" / "llm_extractions").mkdir(parents=True)
    (tmp_path / "data" / "llm_extractions" / "smith-2024.json").write_text("{}")
    (tmp_path / "data" / "llm_extractions" / "jones-2025.json").write_text("{}")

    paths = list(iter_extraction_paths(cfg))

    assert paths == [
        tmp_path / "data" / "llm_extractions" / "jones-2025.json",
        tmp_path / "data" / "papers" / "smith-2024" / "agent-extraction.json",
    ]


def test_iter_artifact_paths_merge_new_and_legacy_without_duplicates(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    paper_dir = tmp_path / "data" / "papers" / "smith-2024"
    paper_dir.mkdir(parents=True)
    (paper_dir / "article.md").write_text("new markdown")
    (paper_dir / "agent-reasoning.json").write_text("{}")
    (paper_dir / "reviews.jsonl").write_text("{}\n")
    (tmp_path / "data" / "fulltext_md").mkdir(parents=True)
    (tmp_path / "data" / "extraction_reasoning").mkdir(parents=True)
    (tmp_path / "data" / "reviews").mkdir(parents=True)
    (tmp_path / "data" / "fulltext_md" / "smith-2024.md").write_text("old markdown")
    (tmp_path / "data" / "fulltext_md" / "jones-2025.md").write_text("legacy markdown")
    (tmp_path / "data" / "extraction_reasoning" / "smith-2024.json").write_text("{}")
    (tmp_path / "data" / "extraction_reasoning" / "jones-2025.json").write_text("{}")
    (tmp_path / "data" / "reviews" / "smith-2024.json").write_text('{"annotations": []}')
    (tmp_path / "data" / "reviews" / "jones-2025.json").write_text('{"annotations": []}')

    assert list(iter_markdown_paths(cfg)) == [
        tmp_path / "data" / "fulltext_md" / "jones-2025.md",
        paper_dir / "article.md",
    ]
    assert list(iter_reasoning_paths(cfg)) == [
        tmp_path / "data" / "extraction_reasoning" / "jones-2025.json",
        paper_dir / "agent-reasoning.json",
    ]
    assert list(iter_review_paths(cfg)) == [
        tmp_path / "data" / "reviews" / "jones-2025.json",
        paper_dir / "reviews.jsonl",
    ]
