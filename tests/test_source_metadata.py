from __future__ import annotations

import pytest

from litschema import source_metadata as sm

# ── title_from_filename ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "stem,expected",
    [
        ("carbon-direct-2024", "Carbon Direct 2024"),
        ("Carbon Direct Buyer Guide 2024", "Carbon Direct Buyer Guide 2024"),
        ("policy_final_v3", "Policy Final V3"),
        ("smith-et-al-2024-enhanced-weathering", "Smith Et Al 2024 Enhanced Weathering"),
        ("", ""),
        ("---", ""),
    ],
)
def test_title_from_filename(stem: str, expected: str) -> None:
    assert sm.title_from_filename(stem) == expected


def test_title_from_filename_preserves_existing_capitalization() -> None:
    assert sm.title_from_filename("IPCC AR6 WG3 summary") == "IPCC AR6 WG3 Summary"


# ── read_source_metadata ─────────────────────────────────────────────────────


def test_read_source_metadata_returns_block_when_present() -> None:
    manifest = {
        "id": "a",
        "source_metadata": {"title": "T", "year": 2024, "metadata_source": "openalex"},
    }
    meta = sm.read_source_metadata(manifest)
    assert meta == {"title": "T", "year": 2024, "metadata_source": "openalex"}


def test_read_source_metadata_drops_null_values_and_defaults_source() -> None:
    manifest = {"source_metadata": {"title": "T", "doi": None}}
    meta = sm.read_source_metadata(manifest)
    assert meta == {"title": "T", "metadata_source": "manual"}


def test_read_source_metadata_falls_back_to_legacy_top_level_keys() -> None:
    manifest = {
        "id": "a",
        "filename": "a.pdf",
        "title": "Old Title",
        "year": 2020,
        "journal": "J",
        "doi": "10.1/x",
        "publisher": "P",
        "author_ids": ["x"],  # ignored: authors.yaml indirection is dead
    }
    meta = sm.read_source_metadata(manifest)
    assert meta["metadata_source"] == "legacy"
    assert meta["title"] == "Old Title"
    assert meta["year"] == 2020
    assert "author_ids" not in meta
    assert "filename" not in meta


def test_read_source_metadata_empty_for_identity_only_manifest() -> None:
    assert sm.read_source_metadata({"id": "a", "filename": "a.pdf"}) == {}
    assert sm.read_source_metadata({}) == {}


def test_editable_sources_cover_human_provenance_only() -> None:
    assert frozenset({"filename", "manual", "legacy"}) == sm.EDITABLE_SOURCES
    for value in ("openalex", "crossref", "doi"):
        assert value in sm.PROVENANCE_VALUES
        assert value not in sm.EDITABLE_SOURCES
