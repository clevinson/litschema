from __future__ import annotations

from pathlib import Path

import pytest

from litschema.article_registry import (
    ARTICLE_REGISTRY_COLUMNS,
    has_article_identity,
    read_article_registry,
    record_extraction_provenance,
    write_article_registry,
)


def test_article_registry_preserves_column_order_and_user_values(tmp_path: Path) -> None:
    path = tmp_path / "data" / "sources" / "articles.csv"

    write_article_registry(
        path,
        [
            {
                "doi": "10.1234/example",
                "title": "User title",
                "publisher": "Example Publisher",
                "unexpected": "ignored",
            }
        ],
    )

    assert path.read_text().splitlines()[0] == ",".join(ARTICLE_REGISTRY_COLUMNS)
    assert read_article_registry(path) == [
        {
            "doi": "10.1234/example",
            "article_id": "",
            "title": "User title",
            "author_citation": "",
            "year": "",
            "publisher": "Example Publisher",
            "open_access": "",
            "extraction_provider": "",
            "extraction_model": "",
            "extraction_date": "",
            "schema_commit": "",
        }
    ]


def test_article_identity_requires_nonblank_article_id() -> None:
    assert not has_article_identity(
        {
            "article_id": "   ",
            "title": "Buyer guide",
            "year": "2024",
            "publisher": "Carbon Direct",
        }
    )
    assert has_article_identity({"article_id": "buyer-guide"})


def test_article_registry_rejects_legacy_id_column(tmp_path: Path) -> None:
    path = tmp_path / "data" / "sources" / "articles.csv"
    path.parent.mkdir(parents=True)
    path.write_text("id,doi,title\nsmith-2024,10.1234/example,Example\n")

    with pytest.raises(ValueError, match="rename it to 'article_id'"):
        read_article_registry(path)


def test_record_extraction_provenance_updates_matching_article_id(tmp_path: Path) -> None:
    path = tmp_path / "data" / "sources" / "articles.csv"
    write_article_registry(
        path,
        [{"doi": "10.1234/example", "article_id": "smith-2024", "title": "User title"}],
    )

    record_extraction_provenance(
        path,
        "smith-2024",
        provider="codex",
        model="gpt-5.5",
        extraction_date="2026-05-10T12:00:00+00:00",
        schema_commit="abc1234",
    )

    assert read_article_registry(path)[0] == {
        "doi": "10.1234/example",
        "article_id": "smith-2024",
        "title": "User title",
        "author_citation": "",
        "year": "",
        "publisher": "",
        "open_access": "",
        "extraction_provider": "codex",
        "extraction_model": "gpt-5.5",
        "extraction_date": "2026-05-10T12:00:00+00:00",
        "schema_commit": "abc1234",
    }


def test_record_extraction_provenance_rejects_missing_article_id(tmp_path: Path) -> None:
    path = tmp_path / "data" / "sources" / "articles.csv"
    write_article_registry(
        path,
        [{"doi": "10.1234/example", "article_id": "smith-2024", "title": "User title"}],
    )

    with pytest.raises(ValueError, match="not found"):
        record_extraction_provenance(
            path,
            "missing-2024",
            provider="codex",
            model="gpt-5.5",
            extraction_date="2026-05-10T12:00:00+00:00",
            schema_commit="abc1234",
        )

    assert len(read_article_registry(path)) == 1
