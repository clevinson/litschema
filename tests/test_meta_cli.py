from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from litschema import cli
from litschema.config import LitSchemaConfig
from litschema.ingest import openalex_harvest


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


def _project(tmp_path: Path, monkeypatch) -> LitSchemaConfig:
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(cli, "_require_project", lambda ctx=None: SimpleNamespace(config=cfg))
    return cfg


def _write_manifest(cfg: LitSchemaConfig, article_id: str, manifest: dict) -> Path:
    article_dir = cfg.article_store_dir / article_id
    article_dir.mkdir(parents=True, exist_ok=True)
    path = article_dir / "article-metadata.json"
    path.write_text(json.dumps(manifest))
    return path


def _block(cfg: LitSchemaConfig, article_id: str) -> dict:
    path = cfg.article_store_dir / article_id / "article-metadata.json"
    return json.loads(path.read_text()).get("source_metadata", {})


runner = CliRunner()


# ── meta set / show ──────────────────────────────────────────────────────────


def test_meta_set_and_show_round_trip(tmp_path: Path, monkeypatch) -> None:
    cfg = _project(tmp_path, monkeypatch)
    _write_manifest(cfg, "a", {"id": "a"})

    result = runner.invoke(
        cli.app,
        [
            "meta", "set", "a", "--source", "manual",
            "--title", "Real Title",
            "--authors", "Jane Smith, Mo Doe",
            "--year", "2023",
        ],
    )

    assert result.exit_code == 0, result.output
    block = _block(cfg, "a")
    assert block["title"] == "Real Title"
    assert block["authors"] == ["Jane Smith", "Mo Doe"]  # comma string split
    assert block["year"] == 2023                          # typer coerced to int
    assert block["metadata_source"] == "manual"

    shown = runner.invoke(cli.app, ["meta", "show", "a"])
    assert shown.exit_code == 0
    assert json.loads(shown.output) == block


def test_meta_set_requires_valid_source(tmp_path: Path, monkeypatch) -> None:
    cfg = _project(tmp_path, monkeypatch)
    _write_manifest(cfg, "a", {"id": "a"})

    # doi cannot be asserted — it is earned via sync.
    result = runner.invoke(cli.app, ["meta", "set", "a", "--source", "doi", "--title", "T"])
    assert result.exit_code == 2

    # --source is required.
    result = runner.invoke(cli.app, ["meta", "set", "a", "--title", "T"])
    assert result.exit_code != 0


def test_meta_set_auto_refuses_to_overwrite_manual_without_force(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = _project(tmp_path, monkeypatch)
    _write_manifest(
        cfg, "a", {"id": "a", "source_metadata": {"title": "Hand Fixed", "metadata_source": "manual"}}
    )

    refused = runner.invoke(cli.app, ["meta", "set", "a", "--source", "auto", "--title", "Guess"])
    assert refused.exit_code == 1
    assert _block(cfg, "a")["title"] == "Hand Fixed"  # untouched

    forced = runner.invoke(
        cli.app, ["meta", "set", "a", "--source", "auto", "--title", "Guess", "--force"]
    )
    assert forced.exit_code == 0, forced.output
    assert _block(cfg, "a")["title"] == "Guess"


def test_meta_set_auto_refuses_locked_but_manual_always_wins(tmp_path: Path, monkeypatch) -> None:
    cfg = _project(tmp_path, monkeypatch)
    _write_manifest(
        cfg, "a", {"id": "a", "source_metadata": {"title": "Registry", "metadata_source": "doi"}}
    )

    assert runner.invoke(
        cli.app, ["meta", "set", "a", "--source", "auto", "--title", "Guess"]
    ).exit_code == 1

    result = runner.invoke(cli.app, ["meta", "set", "a", "--source", "manual", "--title", "Fixed"])
    assert result.exit_code == 0, result.output
    block = _block(cfg, "a")
    assert block["title"] == "Fixed"
    assert block["metadata_source"] == "manual"  # unlocked by the human edit


def test_meta_set_auto_over_auto_is_allowed(tmp_path: Path, monkeypatch) -> None:
    cfg = _project(tmp_path, monkeypatch)
    _write_manifest(
        cfg, "a", {"id": "a", "source_metadata": {"title": "Seed", "metadata_source": "auto"}}
    )
    result = runner.invoke(cli.app, ["meta", "set", "a", "--source", "auto", "--title", "Better"])
    assert result.exit_code == 0, result.output
    assert _block(cfg, "a")["title"] == "Better"


def test_meta_set_clear_removes_fields_and_rejects_unknown(tmp_path: Path, monkeypatch) -> None:
    cfg = _project(tmp_path, monkeypatch)
    _write_manifest(
        cfg,
        "a",
        {"id": "a", "source_metadata": {"title": "T", "url": "http://x", "metadata_source": "manual"}},
    )

    result = runner.invoke(cli.app, ["meta", "set", "a", "--source", "manual", "--clear", "url"])
    assert result.exit_code == 0, result.output
    assert "url" not in _block(cfg, "a")

    assert runner.invoke(
        cli.app, ["meta", "set", "a", "--source", "manual", "--clear", "hacker"]
    ).exit_code == 2


def test_meta_set_requires_some_change_and_known_article(tmp_path: Path, monkeypatch) -> None:
    cfg = _project(tmp_path, monkeypatch)
    _write_manifest(cfg, "a", {"id": "a"})

    assert runner.invoke(cli.app, ["meta", "set", "a", "--source", "manual"]).exit_code == 2
    assert runner.invoke(
        cli.app, ["meta", "set", "ghost", "--source", "manual", "--title", "T"]
    ).exit_code == 2
    assert runner.invoke(cli.app, ["meta", "show", "ghost"]).exit_code == 2


# ── meta sync ────────────────────────────────────────────────────────────────


def _fake_fetch(doi: str, email: str | None = None) -> dict:
    return {
        "id": "https://openalex.org/W1",
        "doi": f"https://doi.org/{doi}",
        "title": "Registry Title",
        "publication_year": 2024,
    }


def test_meta_sync_locks_from_recorded_doi(tmp_path: Path, monkeypatch) -> None:
    cfg = _project(tmp_path, monkeypatch)
    _write_manifest(
        cfg,
        "a",
        {
            "id": "a",
            "source_metadata": {
                "title": "Hand Fixed",
                "doi": "10.1234/x",
                "metadata_source": "manual",
            },
        },
    )
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fake_fetch)

    result = runner.invoke(cli.app, ["meta", "sync", "a"])

    assert result.exit_code == 0, result.output
    block = _block(cfg, "a")
    assert block["title"] == "Registry Title"  # explicit consent overwrote manual
    assert block["metadata_source"] == "doi"


def test_meta_sync_doi_flag_is_passthrough_and_atomic(tmp_path: Path, monkeypatch) -> None:
    cfg = _project(tmp_path, monkeypatch)
    _write_manifest(cfg, "a", {"id": "a"})
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fake_fetch)

    result = runner.invoke(
        cli.app, ["meta", "sync", "a", "--doi", "https://doi.org/10.1234/found"]
    )

    assert result.exit_code == 0, result.output
    manifest = json.loads((cfg.article_store_dir / "a" / "article-metadata.json").read_text())
    assert "doi" not in manifest  # single home: the block, not the identity level
    assert manifest["source_metadata"]["metadata_source"] == "doi"
    assert manifest["source_metadata"]["doi"] == "10.1234/found"

    bad = runner.invoke(cli.app, ["meta", "sync", "a", "--doi", "not-a-doi"])
    assert bad.exit_code == 2


def test_meta_sync_doi_flag_records_nothing_on_registry_miss(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = _project(tmp_path, monkeypatch)
    _write_manifest(cfg, "a", {"id": "a"})
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", lambda doi, email=None: None)

    result = runner.invoke(cli.app, ["meta", "sync", "a", "--doi", "10.1234/miss"])

    assert result.exit_code == 1
    assert "meta set" in result.output  # points at the escape hatch
    manifest = json.loads((cfg.article_store_dir / "a" / "article-metadata.json").read_text())
    assert "doi" not in manifest
    assert "source_metadata" not in manifest  # atomic: the miss wrote nothing


def test_meta_sync_errors(tmp_path: Path, monkeypatch) -> None:
    cfg = _project(tmp_path, monkeypatch)
    _write_manifest(cfg, "no-doi", {"id": "no-doi"})
    _write_manifest(cfg, "gone", {"id": "gone", "doi": "10.1234/x"})
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", lambda doi, email=None: None)

    assert runner.invoke(cli.app, ["meta", "sync", "ghost"]).exit_code == 2
    assert runner.invoke(cli.app, ["meta", "sync", "no-doi"]).exit_code == 1  # no DOI
    assert runner.invoke(cli.app, ["meta", "sync", "gone"]).exit_code == 1  # registry miss
    assert runner.invoke(cli.app, ["meta", "sync"]).exit_code == 2  # id or --all required


def test_meta_sync_all_is_the_batch_harvest(tmp_path: Path, monkeypatch) -> None:
    cfg = _project(tmp_path, monkeypatch)
    _write_manifest(cfg, "smith-2024", {"id": "smith-2024", "doi": "10.1234/x"})
    _write_manifest(
        cfg,
        "fixed",
        {
            "id": "fixed",
            "source_metadata": {"title": "H", "doi": "10.1234/y", "metadata_source": "manual"},
        },
    )
    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fake_fetch)

    result = runner.invoke(cli.app, ["meta", "sync", "--all"])

    assert result.exit_code == 0, result.output
    stats = json.loads(result.output)
    assert stats["fetched"] == 1
    assert stats["manual"] == 1  # batch sweep never touches manual
    assert _block(cfg, "smith-2024")["metadata_source"] == "doi"
    assert _block(cfg, "fixed")["title"] == "H"

    assert runner.invoke(cli.app, ["meta", "sync", "a", "--all"]).exit_code == 2


def test_meta_sync_all_refresh_bypasses_cache(tmp_path: Path, monkeypatch) -> None:
    cfg = _project(tmp_path, monkeypatch)
    _write_manifest(cfg, "smith-2024", {"id": "smith-2024", "doi": "10.1234/x"})
    from litschema.ingest import harvest_cache_dir

    cache_dir = harvest_cache_dir(cfg, "openalex")
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / f"{openalex_harvest.doi_to_slug('10.1234/x')}.json").write_text(
        json.dumps({"doi": "10.1234/x", "error": "not_found"})
    )
    calls = []

    def _fetch(doi: str, email: str | None = None) -> dict:
        calls.append(doi)
        return _fake_fetch(doi)

    monkeypatch.setattr(openalex_harvest.time, "sleep", lambda _: None)
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", _fetch)

    stale = runner.invoke(cli.app, ["meta", "sync", "--all"])
    assert json.loads(stale.output)["not_found"] == 1  # marker honored by default
    assert calls == []

    fresh = runner.invoke(cli.app, ["meta", "sync", "--all", "--refresh"])
    assert json.loads(fresh.output)["fetched"] == 1  # --refresh re-queries
    assert calls == ["10.1234/x"]
