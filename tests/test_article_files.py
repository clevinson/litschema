from __future__ import annotations

import json
from pathlib import Path

from litschema.articles import (
    article_files,
    iter_extraction_paths,
    iter_markdown_paths,
    iter_reasoning_paths,
    iter_review_paths,
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

    files = article_files(cfg, "smith-2024")

    assert files.extraction == paper_dir / "agent-extraction.json"
    assert files.reasoning == paper_dir / "agent-reasoning.json"
    assert files.reviews == paper_dir / "review.json"
    assert not hasattr(files, "reviews_legacy")  # no legacy awareness
    assert files.pdf == paper_dir / "smith-2024.pdf"


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
    (paper_dir / "review.json").write_text('{"version": 1, "fields": {}}\n')

    assert list(iter_markdown_paths(cfg)) == [paper_dir / "article.md"]
    assert list(iter_reasoning_paths(cfg)) == [paper_dir / "agent-reasoning.json"]
    assert list(iter_review_paths(cfg)) == [paper_dir / "review.json"]


def test_write_article_metadata_is_atomic_and_leaves_no_tmp(tmp_path: Path) -> None:
    from litschema.articles import write_article_metadata

    cfg = _cfg(tmp_path)
    files = article_files(cfg, "smith-2024")

    merged = write_article_metadata(files, {"filename": "smith-2024.pdf"})
    write_article_metadata(files, {"doi": "10.1234/x"})

    assert merged["id"] == "smith-2024"
    on_disk = json.loads(files.metadata.read_text())
    assert on_disk["filename"] == "smith-2024.pdf"  # earlier keys preserved
    assert on_disk["doi"] == "10.1234/x"
    # Atomic write: the tmp file never survives.
    assert list(files.article_dir.glob("*.tmp")) == []


def test_article_files_rejects_ids_that_escape_the_store(tmp_path: Path) -> None:
    import pytest

    from litschema.articles import InvalidArticleIdError, article_files

    cfg = _cfg(tmp_path)
    for bad in ("../other", "a/b", "..\\x", "..", ".", ""):
        with pytest.raises(InvalidArticleIdError):
            article_files(cfg, bad)
