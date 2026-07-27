from __future__ import annotations

import json
from pathlib import Path

from litschema.articles import (
    article_files,
    iter_active_extraction_paths,
    iter_live_run_extraction_paths,
    iter_markdown_paths,
)
from litschema.config import LitSchemaConfig

from .helpers import publish_test_run


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


def test_article_files_exposes_run_and_staging_paths(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    paper_dir = tmp_path / "data" / "papers" / "smith-2024"
    paper_dir.mkdir(parents=True)

    files = article_files(cfg, "smith-2024")

    assert files.staged_extraction == paper_dir / "agent-extraction.json"
    assert files.staged_reasoning == paper_dir / "agent-reasoning.json"
    assert files.runs_dir == paper_dir / "extraction-runs"
    assert files.active_run_file == paper_dir / "active-run.json"
    # Reviews are run-bound (RunFiles.review); the article root carries no
    # review path at all, so nothing can accidentally read or write the v1 one.
    assert not hasattr(files, "reviews")
    assert files.pdf == paper_dir / "smith-2024.pdf"


def test_article_files_exposes_only_property_paths(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "smith-2024")

    assert not hasattr(files, "markdown_path")
    assert not hasattr(files, "extraction_path")
    assert not hasattr(files, "reasoning_path")
    assert not hasattr(files, "reviews_path")


def test_iter_active_extraction_paths_resolves_the_active_run(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    paper_dir = tmp_path / "data" / "papers" / "smith-2024"
    paper_dir.mkdir(parents=True)
    (paper_dir / "article-metadata.json").write_text('{"id": "smith-2024"}')
    run_dir = publish_test_run(paper_dir, {"article_id": "smith-2024"})

    assert list(iter_active_extraction_paths(cfg)) == [run_dir / "agent-extraction.json"]
    assert list(iter_live_run_extraction_paths(cfg)) == [run_dir / "agent-extraction.json"]

    # A staged (article-root) extraction is never yielded.
    (paper_dir / "agent-extraction.json").write_text("{}")
    assert list(iter_active_extraction_paths(cfg)) == [run_dir / "agent-extraction.json"]


def test_iter_active_extraction_paths_skips_unextracted_and_raises_on_broken(
    tmp_path: Path,
) -> None:
    import pytest

    from litschema.runs import BrokenActiveRunError

    cfg = _cfg(tmp_path)
    paper_dir = tmp_path / "data" / "papers" / "smith-2024"
    paper_dir.mkdir(parents=True)
    (paper_dir / "article-metadata.json").write_text('{"id": "smith-2024"}')

    # No active pointer: skipped, not an error.
    assert list(iter_active_extraction_paths(cfg)) == []

    # A pointer at a nonexistent run is an integrity failure, never a skip.
    (paper_dir / "active-run.json").write_text('{"run_id": "GONE"}')
    with pytest.raises(BrokenActiveRunError):
        list(iter_active_extraction_paths(cfg))


def test_iter_artifact_paths_read_per_article_store(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    paper_dir = tmp_path / "data" / "papers" / "smith-2024"
    paper_dir.mkdir(parents=True)
    (paper_dir / "article.md").write_text("new markdown")

    assert list(iter_markdown_paths(cfg)) == [paper_dir / "article.md"]


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
