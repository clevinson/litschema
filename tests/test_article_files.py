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
        paper_inbox_dir=project / "papers-inbox",
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
        json.dumps({"article_id": "smith-2024", "path": ".study_type"}) + "\n"
    )

    files = article_files(cfg, "smith-2024")

    assert files.extraction == paper_dir / "agent-extraction.json"
    assert files.reasoning == paper_dir / "agent-reasoning.json"
    assert files.reviews == paper_dir / "reviews.jsonl"
    assert read_review_events(files) == [{"article_id": "smith-2024", "path": ".study_type"}]


def test_article_files_exposes_only_property_paths(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "smith-2024")

    assert not hasattr(files, "markdown_path")
    assert not hasattr(files, "extraction_path")
    assert not hasattr(files, "reasoning_path")
    assert not hasattr(files, "reviews_path")


def test_iter_extraction_paths_reads_per_article_store(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    (tmp_path / "data" / "papers" / "smith-2024").mkdir(parents=True)
    (tmp_path / "data" / "papers" / "smith-2024" / "agent-extraction.json").write_text("{}")

    paths = list(iter_extraction_paths(cfg))

    assert paths == [
        tmp_path / "data" / "papers" / "smith-2024" / "agent-extraction.json",
    ]


def test_iter_artifact_paths_read_per_article_store(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    paper_dir = tmp_path / "data" / "papers" / "smith-2024"
    paper_dir.mkdir(parents=True)
    (paper_dir / "article.md").write_text("new markdown")
    (paper_dir / "agent-reasoning.json").write_text("{}")
    (paper_dir / "reviews.jsonl").write_text("{}\n")

    assert list(iter_markdown_paths(cfg)) == [paper_dir / "article.md"]
    assert list(iter_reasoning_paths(cfg)) == [paper_dir / "agent-reasoning.json"]
    assert list(iter_review_paths(cfg)) == [paper_dir / "reviews.jsonl"]
