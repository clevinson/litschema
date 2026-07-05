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


def test_harvest_enriches_assembled_article_with_identity_doi(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = _cfg(tmp_path)
    _write_manifest(
        cfg, "smith-2024", {"id": "smith-2024", "doi": "10.1234/example", "filename": "s.pdf"}
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
        "metadata_source": "openalex",
    }


def test_harvest_migrates_legacy_manifest_with_top_level_bibliography(
    tmp_path: Path, monkeypatch
) -> None:
    # Pre-source_metadata manifests (e.g. the erw-lit corpus) carry top-level
    # bibliographic keys and no block; one harvest run gives them a
    # provenance-tagged block without touching the legacy keys.
    cfg = _cfg(tmp_path)
    _write_manifest(
        cfg,
        "legacy-2023",
        {
            "id": "legacy-2023",
            "doi": "10.1234/legacy",
            "title": "Old top-level title",
            "journal": "Old Journal",
            "author_ids": ["smith_j"],
        },
    )
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fake_fetch)

    stats = openalex_harvest.harvest(cfg)

    assert stats["fetched"] == 1
    manifest = json.loads(
        (cfg.article_store_dir / "legacy-2023" / "article-metadata.json").read_text()
    )
    assert manifest["title"] == "Old top-level title"  # legacy keys untouched
    assert manifest["source_metadata"]["title"] == "OpenAlex title"
    assert manifest["source_metadata"]["metadata_source"] == "openalex"


def test_harvest_never_touches_manual_metadata(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    files = article_files(cfg, "smith-2024")
    files.article_dir.mkdir(parents=True)
    files.metadata.write_text(json.dumps({"id": "smith-2024", "doi": "10.1234/example"}))
    update_source_metadata(files, {"title": "Hand Fixed"}, source="manual")
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
    files.metadata.write_text(json.dumps({"id": "smith-2024", "doi": "10.1234/example"}))
    update_source_metadata(files, {"title": "Smith 2024"}, source="filename")
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fake_fetch)

    openalex_harvest.harvest(cfg)

    block = json.loads(files.metadata.read_text())["source_metadata"]
    assert block["title"] == "OpenAlex title"
    assert block["metadata_source"] == "openalex"


def test_harvest_reads_doi_from_source_metadata_block(tmp_path: Path, monkeypatch) -> None:
    # An agent backfill may record the DOI in the block before any identity
    # doi exists; harvest still finds it.
    cfg = _cfg(tmp_path)
    files = article_files(cfg, "report-2024")
    files.article_dir.mkdir(parents=True)
    files.metadata.write_text(json.dumps({"id": "report-2024"}))
    update_source_metadata(
        files, {"title": "Report", "doi": "10.1234/report"}, source="agent"
    )
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fake_fetch)

    stats = openalex_harvest.harvest(cfg)

    assert stats["fetched"] == 1
    manifest = json.loads(files.metadata.read_text())
    assert manifest["doi"] == "10.1234/report"  # identity doi backfilled
    assert manifest["source_metadata"]["metadata_source"] == "openalex"


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
    _write_manifest(cfg, "smith-2024", {"id": "smith-2024", "doi": "10.1234/example"})
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", lambda doi, email=None: None)

    stats = openalex_harvest.harvest(cfg)

    assert stats["not_found"] == 1
    manifest = json.loads(
        (cfg.article_store_dir / "smith-2024" / "article-metadata.json").read_text()
    )
    assert "source_metadata" not in manifest
    marker = json.loads(
        next(Path(cfg.project_root / ".litschema" / "cache" / "openalex").glob("*.json")).read_text()
    )
    assert marker["error"] == "not_found"


def test_harvest_applies_cached_response_without_fetching(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    _write_manifest(cfg, "smith-2024", {"id": "smith-2024", "doi": "10.1234/example"})
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
    assert manifest["source_metadata"]["metadata_source"] == "openalex"
