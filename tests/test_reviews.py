from __future__ import annotations

import hashlib
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


def test_canonical_review_path_strips_leading_dot_and_nothing_else() -> None:
    assert reviews.canonical_review_path(".title") == "title"
    assert reviews.canonical_review_path("title") == "title"
    assert reviews.canonical_review_path(".experiments[0].ph") == "experiments[0].ph"
    assert reviews.canonical_review_path("experiments[0].ph") == "experiments[0].ph"
    # Numeric dict keys are NOT list indices; they must survive untouched.
    assert reviews.canonical_review_path("yields.2023") == "yields.2023"


# ── read/write/upsert ────────────────────────────────────────────────────────


def test_read_reviews_empty_when_no_file(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    assert reviews.read_reviews(files) == {}


def test_upsert_review_writes_versioned_file(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    entry = {"author": "0000-0002-1825-0097", "signal": "verified", "timestamp": "t1"}

    reviews.upsert_review(files, ".experiments[0].ph", entry)

    on_disk = json.loads((files.article_dir / "review.json").read_text())
    assert on_disk["version"] == 1
    assert on_disk["fields"]["experiments[0].ph"] == entry  # single entry object, not a list


def test_upsert_review_replaces_regardless_of_author(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    reviews.upsert_review(files, "title", {"author": "A", "signal": "verified", "timestamp": "t1"})
    reviews.upsert_review(
        files, "title", {"author": "B", "signal": "flagged", "timestamp": "t2", "override_value": "X"}
    )

    entry = reviews.read_reviews(files)["title"]
    assert entry["author"] == "B"                       # B's save replaced A's entirely
    assert entry["signal"] == "flagged"
    assert entry["override_value"] == "X"


def test_delete_reviews_at_removes_path_and_empty_file(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    reviews.upsert_review(files, "title", {"author": "A", "signal": "verified", "timestamp": "t"})

    reviews.delete_reviews_at(files, ".title")

    assert reviews.read_reviews(files) == {}
    assert not (files.article_dir / "review.json").exists()  # no 0-entry litter


def test_read_reviews_ignores_non_dict_entry_values(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    files.article_dir.mkdir(parents=True, exist_ok=True)
    files.reviews.write_text(
        json.dumps(
            {
                "version": 1,
                "fields": {
                    "title": [{"author": "A", "signal": "verified", "timestamp": "t"}],  # old list shape
                    "year": {"author": "B", "signal": "verified", "timestamp": "t"},
                },
            }
        )
    )

    assert reviews.read_reviews(files) == {
        "year": {"author": "B", "signal": "verified", "timestamp": "t"}
    }


# ── base-extraction staleness stamp (per entry) ──────────────────────────────


def test_upsert_stamps_the_entry_with_the_base_extraction_hash(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    files.article_dir.mkdir(parents=True, exist_ok=True)
    files.extraction.write_text(json.dumps({"article_id": "a", "title": "T"}))

    reviews.upsert_review(files, "title", {"author": "A", "signal": "verified", "timestamp": "t"})

    on_disk = json.loads(files.reviews.read_text())
    assert on_disk["version"] == 1
    assert "base_extraction_sha256" not in on_disk  # the stamp lives on entries
    assert on_disk["fields"]["title"]["base_extraction_sha256"] == hashlib.sha256(
        files.extraction.read_bytes()
    ).hexdigest()


def test_upsert_omits_stamp_without_extraction_file(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")

    reviews.upsert_review(files, "title", {"author": "A", "signal": "verified", "timestamp": "t"})

    entry = json.loads(files.reviews.read_text())["fields"]["title"]
    assert "base_extraction_sha256" not in entry
    assert entry["author"] == "A"


def test_save_after_reextraction_does_not_disarm_staleness_for_other_entries(
    tmp_path: Path,
) -> None:
    files = article_files(_cfg(tmp_path), "a")
    files.article_dir.mkdir(parents=True, exist_ok=True)
    files.extraction.write_text(json.dumps({"article_id": "a", "title": "T", "ph": 7}))
    reviews.upsert_review(files, "title", {"author": "A", "signal": "verified", "timestamp": "t1"})

    files.extraction.write_text(json.dumps({"article_id": "a", "title": "T2", "ph": 7}))
    assert reviews.base_extraction_stale(files) is True

    # A fresh save against the NEW base must not clear the warning for the
    # old entry — only re-reviewing (or clearing) the stale entry may.
    reviews.upsert_review(files, "ph", {"author": "A", "signal": "verified", "timestamp": "t2"})
    assert reviews.base_extraction_stale(files) is True

    reviews.upsert_review(files, "title", {"author": "A", "signal": "verified", "timestamp": "t3"})
    assert reviews.base_extraction_stale(files) is False  # self-healed


def test_save_while_extraction_absent_preserves_older_stamps(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    files.article_dir.mkdir(parents=True, exist_ok=True)
    files.extraction.write_text(json.dumps({"article_id": "a", "title": "T"}))
    reviews.upsert_review(files, "title", {"author": "A", "signal": "verified", "timestamp": "t1"})

    files.extraction.unlink()
    reviews.upsert_review(files, "year", {"author": "A", "signal": "verified", "timestamp": "t2"})

    # The old entry's stamp survives, so recreating a DIFFERENT extraction
    # is still detectable as stale.
    files.extraction.write_text(json.dumps({"article_id": "a", "title": "CHANGED"}))
    assert reviews.base_extraction_stale(files) is True


# ── corrupt review.json protection ───────────────────────────────────────────


def test_writes_refuse_an_unreadable_review_file(tmp_path: Path) -> None:
    import pytest

    files = article_files(_cfg(tmp_path), "a")
    files.article_dir.mkdir(parents=True, exist_ok=True)
    files.reviews.write_text("{not json")

    with pytest.raises(reviews.ReviewFileUnreadableError):
        reviews.upsert_review(files, "title", {"author": "", "signal": "verified"})
    with pytest.raises(reviews.ReviewFileUnreadableError):
        reviews.delete_reviews_at(files, "title")

    assert files.reviews.read_text() == "{not json"  # evidence intact
    assert reviews.read_reviews(files) == {}  # lenient read still works


def test_read_reviews_canonicalizes_hand_edited_keys(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    files.article_dir.mkdir(parents=True, exist_ok=True)
    files.reviews.write_text(
        json.dumps(
            {
                "version": 1,
                "fields": {".title": {"author": "A", "signal": "verified", "timestamp": "t"}},
            }
        )
    )

    assert "title" in reviews.read_reviews(files)  # served canonically
    reviews.delete_reviews_at(files, ".title")  # ...and deletable
    assert not files.reviews.exists()


# ── no legacy awareness ──────────────────────────────────────────────────────


def test_stray_files_in_the_article_dir_are_ignored(tmp_path: Path) -> None:
    # The framework reads review.json and nothing else; unknown files (e.g. a
    # leftover reviews.jsonl from a pre-release checkout) are inert and
    # untouched — cleaning them up is the domain repo's business.
    files = article_files(_cfg(tmp_path), "a")
    files.article_dir.mkdir(parents=True, exist_ok=True)
    stray = files.article_dir / "reviews.jsonl"
    stray.write_text('{"path": ".title", "status": "verified"}\n')

    assert reviews.read_reviews(files) == {}

    assert stray.exists()
    assert stray.read_text() == '{"path": ".title", "status": "verified"}\n'
