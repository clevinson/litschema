from __future__ import annotations

import json
from pathlib import Path

from litschema.articles import article_files
from litschema.config import LitSchemaConfig
from litschema.ingest import openalex_harvest
from litschema.source_metadata import update_source_metadata


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


def _write_manifest(cfg: LitSchemaConfig, article_id: str, manifest: dict) -> Path:
    article_dir = cfg.article_store_dir / article_id
    article_dir.mkdir(parents=True)
    path = article_dir / "article-metadata.json"
    path.write_text(json.dumps(manifest))
    return path


def _fake_fetch(doi: str, email: str | None = None) -> dict:
    return {
        "id": "https://openalex.org/W1",
        "doi": f"https://doi.org/{doi}",
        "title": "OpenAlex title",
        "publication_year": 2024,
        "primary_location": {"source": {"display_name": "Example Journal"}},
    }


def _no_fetch(doi: str, email: str | None = None) -> dict:
    raise AssertionError("should not fetch")


def test_harvest_enriches_assembled_article_with_block_doi(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = _cfg(tmp_path)
    _write_manifest(
        cfg,
        "smith-2024",
        {
            "id": "smith-2024",
            "filename": "s.pdf",
            "source_metadata": {"doi": "10.1234/example", "metadata_source": "auto"},
        },
    )
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fake_fetch)

    stats = openalex_harvest.harvest(cfg)

    assert stats == {
        "articles": 1,
        "fetched": 1,
        "cached": 0,
        "not_found": 0,
        "no_doi": 0,
        "manual": 0,
        "unusable": 0,
        "errors": 0,
    }
    manifest = json.loads(
        (cfg.article_store_dir / "smith-2024" / "article-metadata.json").read_text()
    )
    assert manifest["filename"] == "s.pdf"  # identity preserved
    assert manifest["source_metadata"] == {
        "doi": "10.1234/example",
        "title": "OpenAlex title",
        "year": 2024,
        "journal": "Example Journal",
        "metadata_source": "doi",
    }


def test_harvest_ignores_unmigrated_legacy_manifests(tmp_path: Path, monkeypatch) -> None:
    # Alpha policy (specs/README.md): litschema carries no legacy-format
    # awareness. Pre-block manifests are the domain repo's to migrate
    # (`meta set --source auto --doi ...`, then `meta sync --all`).
    cfg = _cfg(tmp_path)
    _write_manifest(
        cfg,
        "legacy-2023",
        {
            "id": "legacy-2023",
            "doi": "10.1234/legacy",
            "title": "Old top-level title",
            "author_ids": ["smith_j"],
        },
    )
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _no_fetch)

    stats = openalex_harvest.harvest(cfg)

    assert stats["no_doi"] == 1  # top-level doi is never read
    manifest = json.loads(
        (cfg.article_store_dir / "legacy-2023" / "article-metadata.json").read_text()
    )
    assert "source_metadata" not in manifest


def test_harvest_never_touches_manual_metadata(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    files = article_files(cfg, "smith-2024")
    files.article_dir.mkdir(parents=True)
    files.metadata.write_text(json.dumps({"id": "smith-2024"}))
    update_source_metadata(
        files, {"title": "Hand Fixed", "doi": "10.1234/example"}, source="manual"
    )
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _no_fetch)

    stats = openalex_harvest.harvest(cfg)

    assert stats["manual"] == 1
    assert stats["fetched"] == 0
    block = json.loads(files.metadata.read_text())["source_metadata"]
    assert block["title"] == "Hand Fixed"
    assert block["metadata_source"] == "manual"


def test_harvest_overwrites_filename_seed(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    files = article_files(cfg, "smith-2024")
    files.article_dir.mkdir(parents=True)
    files.metadata.write_text(json.dumps({"id": "smith-2024"}))
    update_source_metadata(
        files, {"title": "Smith 2024", "doi": "10.1234/example"}, source="auto"
    )
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fake_fetch)

    openalex_harvest.harvest(cfg)

    block = json.loads(files.metadata.read_text())["source_metadata"]
    assert block["title"] == "OpenAlex title"
    assert block["metadata_source"] == "doi"


def test_sync_replaces_the_block_wholesale(tmp_path: Path, monkeypatch) -> None:
    # A doi block asserts registry origin for every field it shows: leftover
    # manual/agent values the registry did not supply must not survive under
    # the verified pill.
    cfg = _cfg(tmp_path)
    files = article_files(cfg, "smith-2024")
    files.article_dir.mkdir(parents=True)
    files.metadata.write_text(json.dumps({"id": "smith-2024"}))
    update_source_metadata(
        files,
        {
            "title": "Hand Title",
            "doi": "10.1234/example",
            "corporate_author": "Acme Institute",
            "url": "https://example.org/x",
        },
        source="manual",
    )
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fake_fetch)

    block = openalex_harvest.sync_article(cfg, "smith-2024")

    assert block["title"] == "OpenAlex title"
    assert block["metadata_source"] == "doi"
    assert "corporate_author" not in block  # registry-absent fields cleared
    assert "url" not in block


def test_harvest_reads_doi_from_source_metadata_block(tmp_path: Path, monkeypatch) -> None:
    # The block is the DOI's single home; harvest resolves from it directly.
    cfg = _cfg(tmp_path)
    files = article_files(cfg, "report-2024")
    files.article_dir.mkdir(parents=True)
    files.metadata.write_text(json.dumps({"id": "report-2024"}))
    update_source_metadata(
        files, {"title": "Report", "doi": "10.1234/report"}, source="auto"
    )
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fake_fetch)

    stats = openalex_harvest.harvest(cfg)

    assert stats["fetched"] == 1
    manifest = json.loads(files.metadata.read_text())
    assert "doi" not in manifest  # nothing writes the legacy identity slot anymore
    assert manifest["source_metadata"]["metadata_source"] == "doi"


def test_harvest_does_not_resurrect_doi_cleared_from_block(
    tmp_path: Path, monkeypatch
) -> None:
    # A block without a DOI means the article HAS no DOI; top-level keys
    # are never read.
    cfg = _cfg(tmp_path)
    _write_manifest(
        cfg,
        "cleared",
        {
            "id": "cleared",
            "doi": "10.1234/wrong",
            "source_metadata": {"title": "Fixed", "metadata_source": "auto"},
        },
    )
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _no_fetch)

    stats = openalex_harvest.harvest(cfg)

    assert stats["no_doi"] == 1


def test_harvest_skips_articles_without_valid_doi(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    _write_manifest(cfg, "no-doi-2024", {"id": "no-doi-2024"})
    _write_manifest(cfg, "bad-doi-2024", {"id": "bad-doi-2024", "doi": "ISSN: 2278-4632"})
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _no_fetch)

    stats = openalex_harvest.harvest(cfg)

    assert stats["no_doi"] == 2
    assert stats["fetched"] == 0
    for article_id in ("no-doi-2024", "bad-doi-2024"):
        manifest = json.loads(
            (cfg.article_store_dir / article_id / "article-metadata.json").read_text()
        )
        assert "source_metadata" not in manifest


def test_harvest_not_found_writes_cache_marker_but_not_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    # No row-only fallback: an unresolvable DOI leaves the manifest alone, so
    # a later run (once OpenAlex knows the DOI) can still enrich it.
    cfg = _cfg(tmp_path)
    _write_manifest(
        cfg,
        "smith-2024",
        {
            "id": "smith-2024",
            "source_metadata": {"doi": "10.1234/example", "metadata_source": "auto"},
        },
    )
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", lambda doi, email=None: None)

    stats = openalex_harvest.harvest(cfg)

    assert stats["not_found"] == 1
    manifest = json.loads(
        (cfg.article_store_dir / "smith-2024" / "article-metadata.json").read_text()
    )
    # The block is exactly the pre-harvest seed: nothing was enriched.
    assert manifest["source_metadata"] == {
        "doi": "10.1234/example",
        "metadata_source": "auto",
    }
    marker = json.loads(
        next(Path(cfg.project_root / ".litschema" / "cache" / "openalex").glob("*.json")).read_text()
    )
    assert marker["error"] == "not_found"


def test_transient_registry_failure_leaves_no_marker(tmp_path: Path, monkeypatch) -> None:
    # A network blip must not be cached as not_found: the article stays
    # retryable on the next run.
    import requests

    cfg = _cfg(tmp_path)
    _write_manifest(
        cfg,
        "smith-2024",
        {
            "id": "smith-2024",
            "source_metadata": {"doi": "10.1234/example", "metadata_source": "auto"},
        },
    )

    def _blip(doi: str, email: str | None = None) -> dict:
        raise openalex_harvest.RegistryUnavailableError("boom")

    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _blip)

    stats = openalex_harvest.harvest(cfg)

    assert stats["errors"] == 1
    assert stats["not_found"] == 0
    cache_dir = cfg.project_root / ".litschema" / "cache" / "openalex"
    assert not list(cache_dir.glob("*.json"))  # no marker written

    # sync_article propagates the transient failure (retry later), and the
    # manifest is untouched either way.
    import pytest

    with pytest.raises(openalex_harvest.RegistryUnavailableError):
        openalex_harvest.sync_article(cfg, "smith-2024")
    manifest = json.loads(
        (cfg.article_store_dir / "smith-2024" / "article-metadata.json").read_text()
    )
    assert manifest["source_metadata"] == {
        "doi": "10.1234/example",
        "metadata_source": "auto",
    }


def test_unusable_registry_response_is_counted_not_hidden(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    _write_manifest(
        cfg,
        "smith-2024",
        {
            "id": "smith-2024",
            "source_metadata": {"doi": "10.1234/example", "metadata_source": "auto"},
        },
    )
    # 200 response with no openalex id: enrichment cannot use it.
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        openalex_harvest, "fetch_openalex", lambda doi, email=None: {"title": "T"}
    )

    stats = openalex_harvest.harvest(cfg)

    assert stats["unusable"] == 1
    assert stats["fetched"] == 0


def test_unusable_registry_response_is_not_cached(tmp_path: Path, monkeypatch) -> None:
    # An anomalous 200 must stay retryable: no cache entry, so the next
    # default run re-fetches instead of counting it unusable forever.
    cfg = _cfg(tmp_path)
    _write_manifest(
        cfg,
        "smith-2024",
        {
            "id": "smith-2024",
            "source_metadata": {"doi": "10.1234/example", "metadata_source": "auto"},
        },
    )
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        openalex_harvest, "fetch_openalex", lambda doi, email=None: {"title": "T"}
    )

    stats = openalex_harvest.harvest(cfg)

    assert stats["unusable"] == 1
    cache_dir = cfg.project_root / ".litschema" / "cache" / "openalex"
    assert not list(cache_dir.glob("*.json"))


def test_enrichment_falls_back_to_fetch_doi_when_record_doi_is_mangled(
    tmp_path: Path, monkeypatch
) -> None:
    # A locked block must never end up with LESS than the DOI it was synced
    # by, even when the registry record's own doi field is null or junk.
    cfg = _cfg(tmp_path)
    files = article_files(cfg, "smith-2024")
    files.article_dir.mkdir(parents=True)
    files.metadata.write_text(json.dumps({"id": "smith-2024"}))
    update_source_metadata(
        files, {"title": "Seed", "doi": "10.1234/example"}, source="auto"
    )
    monkeypatch.setattr(
        openalex_harvest,
        "fetch_openalex",
        lambda doi, email=None: {
            "id": "https://openalex.org/W1",
            "doi": "not-a-doi",
            "title": "Registry Title",
        },
    )

    block = openalex_harvest.sync_article(cfg, "smith-2024")

    assert block["doi"] == "10.1234/example"  # the fetch DOI, kept
    assert block["metadata_source"] == "doi"


def test_enrichment_normalizes_the_stored_doi(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    files = article_files(cfg, "smith-2024")
    files.article_dir.mkdir(parents=True)
    files.metadata.write_text(json.dumps({"id": "smith-2024"}))
    update_source_metadata(files, {"doi": "10.1234/example"}, source="auto")
    monkeypatch.setattr(
        openalex_harvest,
        "fetch_openalex",
        lambda doi, email=None: {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1234/UPPER.",
            "title": "Registry Title",
        },
    )

    block = openalex_harvest.sync_article(cfg, "smith-2024")

    assert block["doi"] == "10.1234/UPPER"  # prefix and trailing dot stripped


def test_extract_metadata_tolerates_null_doi() -> None:
    extracted = openalex_harvest.extract_metadata(
        {"id": "https://openalex.org/W1", "doi": None, "title": "T"}
    )
    assert extracted["doi"] == ""


def test_harvest_applies_cached_response_without_fetching(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    _write_manifest(
        cfg,
        "smith-2024",
        {
            "id": "smith-2024",
            "source_metadata": {"doi": "10.1234/example", "metadata_source": "auto"},
        },
    )
    from litschema.ingest import harvest_cache_dir

    cache_dir = harvest_cache_dir(cfg, "openalex")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = openalex_harvest.extract_metadata(_fake_fetch("10.1234/example"))
    (cache_dir / f"{openalex_harvest.doi_to_slug('10.1234/example')}.json").write_text(
        json.dumps(cached)
    )
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _no_fetch)

    stats = openalex_harvest.harvest(cfg)

    assert stats["cached"] == 1
    manifest = json.loads(
        (cfg.article_store_dir / "smith-2024" / "article-metadata.json").read_text()
    )
    assert manifest["source_metadata"]["title"] == "OpenAlex title"
    assert manifest["source_metadata"]["metadata_source"] == "doi"
