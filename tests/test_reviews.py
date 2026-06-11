from __future__ import annotations

import json
from pathlib import Path

from litschema import reviews
from litschema.articles import article_files
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


# ── canonical_review_path ────────────────────────────────────────────────────


def test_canonical_review_path_normalizes_legacy_dot_index_paths() -> None:
    assert reviews.canonical_review_path(".experiments.0.ph") == "experiments[0].ph"
    assert (
        reviews.canonical_review_path(".experiments.0.treatments.1.type")
        == "experiments[0].treatments[1].type"
    )
    assert reviews.canonical_review_path("title") == "title"
    assert reviews.canonical_review_path("experiments[0].ph") == "experiments[0].ph"
    assert reviews.canonical_review_path(".tags.2") == "tags[2]"


# ── read/write/upsert ────────────────────────────────────────────────────────


def test_read_reviews_empty_when_no_file(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    assert reviews.read_reviews(files) == {}


def test_upsert_review_writes_versioned_file(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    entry = {"author": "0000-0002-1825-0097", "signal": "verified", "timestamp": "t1"}

    reviews.upsert_review(files, ".experiments.0.ph", entry)

    on_disk = json.loads((files.article_dir / "review.json").read_text())
    assert on_disk["version"] == 1
    assert on_disk["fields"]["experiments[0].ph"] == [entry]


def test_upsert_review_replaces_same_author_keeps_others(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    reviews.upsert_review(files, "title", {"author": "A", "signal": "verified", "timestamp": "t1"})
    reviews.upsert_review(files, "title", {"author": "B", "signal": "flagged", "timestamp": "t2"})
    reviews.upsert_review(
        files, "title", {"author": "A", "signal": "flagged", "timestamp": "t3", "override_value": "X"}
    )

    entries = reviews.read_reviews(files)["title"]
    assert len(entries) == 2
    by_author = {e["author"]: e for e in entries}
    assert by_author["A"]["signal"] == "flagged"
    assert by_author["A"]["override_value"] == "X"
    assert by_author["B"]["timestamp"] == "t2"


def test_delete_reviews_at_removes_path_and_empty_file(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    reviews.upsert_review(files, "title", {"author": "A", "signal": "verified", "timestamp": "t"})

    reviews.delete_reviews_at(files, ".title")

    assert reviews.read_reviews(files) == {}
    assert not (files.article_dir / "review.json").exists()  # no 0-entry litter


# ── legacy reviews.jsonl set-aside ───────────────────────────────────────────


def test_leftover_legacy_log_is_renamed_aside_on_first_read(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    files.article_dir.mkdir(parents=True, exist_ok=True)
    legacy = files.article_dir / "reviews.jsonl"
    legacy.write_text('{"path": ".title", "status": "verified"}\n')

    assert reviews.read_reviews(files) == {}        # NOT converted — throwaway data

    assert not legacy.exists()
    assert (files.article_dir / "reviews.jsonl.bak").exists()


def test_legacy_log_left_alone_when_review_json_exists(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    reviews.upsert_review(files, "title", {"author": "A", "signal": "verified", "timestamp": "t9"})
    legacy = files.article_dir / "reviews.jsonl"
    legacy.write_text('{"path": ".title", "status": "flagged"}\n')

    fields = reviews.read_reviews(files)

    assert fields["title"][0]["timestamp"] == "t9"
    assert legacy.exists()                          # nothing touched


def test_migration_noop_without_legacy_file(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    assert reviews.migrate_legacy_reviews(files) is False
