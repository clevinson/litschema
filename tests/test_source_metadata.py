from __future__ import annotations

from pathlib import Path

import pytest

from litschema import source_metadata as sm
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


def test_read_source_metadata_ignores_legacy_top_level_keys() -> None:
    # No back-compat: bibliographic fields live only in the source_metadata block.
    manifest = {
        "id": "a",
        "filename": "a.pdf",
        "title": "Old Title",
        "year": 2020,
        "journal": "J",
        "doi": "10.1/x",
        "publisher": "P",
        "author_ids": ["x"],
    }
    assert sm.read_source_metadata(manifest) == {}


def test_read_source_metadata_empty_for_identity_only_manifest() -> None:
    assert sm.read_source_metadata({"id": "a", "filename": "a.pdf"}) == {}
    assert sm.read_source_metadata({}) == {}


def test_editable_sources_cover_human_provenance_only() -> None:
    assert frozenset({"filename", "manual"}) == sm.EDITABLE_SOURCES
    assert "legacy" not in sm.PROVENANCE_VALUES
    for value in ("openalex", "crossref", "doi"):
        assert value in sm.PROVENANCE_VALUES
        assert value not in sm.EDITABLE_SOURCES


def test_source_fields_include_corporate_author_after_authors() -> None:
    fields = list(sm.SOURCE_FIELDS)
    assert "corporate_author" in fields
    assert fields.index("corporate_author") == fields.index("authors") + 1


# ── update_source_metadata ───────────────────────────────────────────────────


def test_update_source_metadata_writes_block_and_provenance(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    block = sm.update_source_metadata(files, {"title": "T", "year": 2024}, source="filename")
    assert block == {"title": "T", "year": 2024, "metadata_source": "filename"}
    on_disk = files.read_metadata()
    assert on_disk["source_metadata"] == block
    assert on_disk["id"] == "a"


def test_update_source_metadata_merges_and_retags(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    sm.update_source_metadata(files, {"title": "T", "year": 2024}, source="filename")
    block = sm.update_source_metadata(files, {"title": "Better"}, source="manual")
    assert block["title"] == "Better"
    assert block["year"] == 2024              # untouched fields preserved
    assert block["metadata_source"] == "manual"


def test_update_source_metadata_accepts_corporate_author(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    block = sm.update_source_metadata(
        files, {"corporate_author": "Carbon Direct"}, source="manual"
    )
    assert block["corporate_author"] == "Carbon Direct"
    assert files.read_metadata()["source_metadata"]["corporate_author"] == "Carbon Direct"


def test_update_source_metadata_null_deletes_a_field(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    sm.update_source_metadata(files, {"title": "T", "doi": "10.1/x"}, source="manual")
    block = sm.update_source_metadata(files, {"doi": None}, source="manual")
    assert "doi" not in block


def test_update_source_metadata_does_not_promote_legacy_top_level_keys(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    files.article_dir.mkdir(parents=True)
    files.metadata.write_text('{"id": "a", "title": "Old", "year": 2020}\n')
    block = sm.update_source_metadata(files, {"journal": "J"}, source="manual")
    assert block == {"journal": "J", "metadata_source": "manual"}
    assert "title" not in block               # legacy top-level keys are not carried over


def test_update_source_metadata_ignores_unknown_fields_and_bad_source(tmp_path: Path) -> None:
    files = article_files(_cfg(tmp_path), "a")
    block = sm.update_source_metadata(files, {"title": "T", "hacker": "x"}, source="manual")
    assert "hacker" not in block
    with pytest.raises(ValueError):
        sm.update_source_metadata(files, {"title": "T"}, source="carrier-pigeon")


# ── meta.yaml sidecar ────────────────────────────────────────────────────────


def test_load_sidecar_metadata_reads_known_fields(tmp_path: Path) -> None:
    pdf = tmp_path / "report.pdf"
    pdf.write_text("pdf")
    (tmp_path / "report.meta.yaml").write_text(
        "title: Annual Report\nyear: 2024\nauthors:\n  - Jane Smith\nnonsense: ignored\n"
    )
    fields = sm.load_sidecar_metadata(pdf)
    assert fields == {"title": "Annual Report", "year": 2024, "authors": ["Jane Smith"]}


def test_load_sidecar_metadata_splits_comma_authors(tmp_path: Path) -> None:
    pdf = tmp_path / "r.pdf"
    pdf.write_text("pdf")
    (tmp_path / "r.meta.yaml").write_text("authors: Jane Smith, Mo Doe\n")
    assert sm.load_sidecar_metadata(pdf) == {"authors": ["Jane Smith", "Mo Doe"]}


def test_load_sidecar_metadata_none_when_missing_or_invalid(tmp_path: Path) -> None:
    pdf = tmp_path / "r.pdf"
    pdf.write_text("pdf")
    assert sm.load_sidecar_metadata(pdf) is None
    (tmp_path / "r.meta.yaml").write_text("just a string")
    assert sm.load_sidecar_metadata(pdf) is None
    (tmp_path / "r.meta.yaml").write_text(": not [ yaml")
    assert sm.load_sidecar_metadata(pdf) is None
