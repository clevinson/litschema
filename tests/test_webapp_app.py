from __future__ import annotations

import json as _json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import litschema.webapp.app as webapp
from litschema.config import LitSchemaConfig, load_config


def _project_cfg(project: Path) -> LitSchemaConfig:
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


def _write_manifest(cfg: LitSchemaConfig, article_id: str, manifest: dict) -> None:
    article_dir = cfg.article_store_dir / article_id
    article_dir.mkdir(parents=True, exist_ok=True)
    (article_dir / "article-metadata.json").write_text(_json.dumps(manifest))


def test_article_meta_returns_provenance_and_editability(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_manifest(
        cfg,
        "a",
        {
            "id": "a",
            "source_metadata": {
                "title": "T",
                "authors": ["Jane Smith"],
                "year": 2024,
                "metadata_source": "openalex",
            },
        },
    )
    meta = webapp._article_meta(cfg, "a")
    assert meta["title"] == "T"
    assert meta["authors"] == ["Jane Smith"]
    assert meta["metadata_source"] == "openalex"
    assert meta["editable"] is False


def test_article_meta_marks_filename_and_legacy_editable(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_manifest(
        cfg, "f", {"id": "f", "source_metadata": {"title": "T", "metadata_source": "filename"}}
    )
    _write_manifest(cfg, "l", {"id": "l", "title": "Old", "year": 2019})

    assert webapp._article_meta(cfg, "f")["editable"] is True
    legacy = webapp._article_meta(cfg, "l")
    assert legacy["metadata_source"] == "legacy"
    assert legacy["editable"] is True


def test_article_meta_identity_only_manifest_is_editable_empty(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_manifest(cfg, "bare", {"id": "bare", "filename": "bare.pdf"})
    meta = webapp._article_meta(cfg, "bare")
    assert meta["editable"] is True
    assert meta.get("title") is None


def test_article_meta_empty_for_unknown_article(tmp_path) -> None:
    assert webapp._article_meta(_project_cfg(tmp_path), "ghost") == {}


def test_orcid_id_normalization_accepts_urls() -> None:
    assert webapp._normalize_orcid_id("https://orcid.org/0000-0002-1825-0097") == "0000-0002-1825-0097"
    assert webapp._normalize_orcid_id("HTTP://ORCID.ORG/0000-0002-1825-0097/") == "0000-0002-1825-0097"


def test_orcid_id_normalization_rejects_invalid_values() -> None:
    with pytest.raises(webapp.HTTPException):
        webapp._normalize_orcid_id("not-an-orcid")


def test_orcid_display_name_prefers_credit_name() -> None:
    person = {
        "name": {
            "credit-name": {"value": "Published Name"},
            "given-names": {"value": "Given"},
            "family-name": {"value": "Family"},
        }
    }

    assert webapp._orcid_display_name(person) == "Published Name"


def test_orcid_display_name_falls_back_to_given_and_family() -> None:
    person = {"name": {"given-names": {"value": "Given"}, "family-name": {"value": "Family"}}}

    assert webapp._orcid_display_name(person) == "Given Family"


def test_webapp_config_requires_cli_runner_or_dependency_override() -> None:
    webapp.app.state._state.pop("litschema_config", None)

    with pytest.raises(RuntimeError, match="litschema verify"):
        webapp.get_config()


def test_schema_field_metadata_exposes_top_level_enums() -> None:
    cfg = load_config("tests/fixtures/projects/custom_clinical/litschema.yaml", reload=True)

    metadata = webapp._schema_field_metadata(cfg)

    assert metadata["fields"]["blinding"]["range"] == "BlindingEnum"
    assert [v["value"] for v in metadata["fields"]["blinding"]["permissible_values"]] == [
        "open_label",
        "single_blind",
        "double_blind",
        "triple_blind",
    ]
    assert "primary_endpoint" not in metadata["fields"]


def test_schema_field_metadata_uses_array_path_patterns_for_nested_enums() -> None:
    cfg = load_config("tests/fixtures/projects/agriculture_demo/litschema.yaml", reload=True)

    metadata = webapp._schema_field_metadata(cfg)

    assert metadata["fields"]["study_type"]["range"] == "StudyTypeEnum"
    assert metadata["fields"]["experiments[].treatments[].type"]["range"] == "TreatmentTypeEnum"


def test_main_honors_port_argument(monkeypatch, tmp_path) -> None:
    import uvicorn

    cfg = SimpleNamespace(article_store_dir=tmp_path / "data" / "papers", paper_inbox_dir=tmp_path)
    opened = []
    runs = []

    monkeypatch.setattr(webapp.webbrowser, "open", opened.append)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: runs.append((args, kwargs)))

    webapp.run_app(cfg, port=8017)

    assert opened == ["http://localhost:8017"]
    assert runs == [((webapp.app,), {"host": "127.0.0.1", "port": 8017})]


def test_collapse_review_events_dedupes_by_path_last_write_wins() -> None:
    events = [
        {"path": ".a", "status": "verified", "timestamp": "t1"},
        {"path": ".a", "status": "flagged", "timestamp": "t2"},
        {"path": ".b", "status": "verified", "timestamp": "t3"},
    ]

    by_path = {e["path"]: e for e in webapp._collapse_review_events(events)}

    assert set(by_path) == {".a", ".b"}
    assert by_path[".a"]["status"] == "flagged"
    assert by_path[".a"]["timestamp"] == "t2"


def test_collapse_review_events_drops_path_after_cleared_event() -> None:
    events = [
        {"path": ".a", "status": "verified"},
        {"path": ".a", "status": "cleared"},
    ]

    assert webapp._collapse_review_events(events) == []


def test_collapse_review_events_drops_events_without_path() -> None:
    events = [
        {"status": "verified"},
        {"path": ".a", "status": "verified"},
        {"path": "", "status": "flagged"},
    ]

    out = webapp._collapse_review_events(events)
    assert [e["path"] for e in out] == [".a"]


def test_write_reviews_jsonl_writes_one_line_per_entry(tmp_path) -> None:
    p = tmp_path / "reviews.jsonl"

    webapp._write_reviews_jsonl(p, [
        {"path": ".a", "status": "verified"},
        {"path": ".b", "status": "flagged"},
    ])

    lines = p.read_text().splitlines()
    assert len(lines) == 2
    assert all(line.startswith("{") for line in lines)


def test_write_reviews_jsonl_removes_file_when_empty(tmp_path) -> None:
    p = tmp_path / "reviews.jsonl"
    p.write_text('{"path": ".x", "status": "verified"}\n')

    webapp._write_reviews_jsonl(p, [])

    assert not p.exists()


def test_write_reviews_jsonl_no_op_when_empty_and_missing(tmp_path) -> None:
    p = tmp_path / "reviews.jsonl"

    webapp._write_reviews_jsonl(p, [])

    assert not p.exists()


def _client(cfg: LitSchemaConfig) -> TestClient:
    webapp.app.dependency_overrides[webapp.get_config] = lambda: cfg
    return TestClient(webapp.app)


def teardown_function() -> None:
    webapp.app.dependency_overrides.clear()


def test_put_bibliography_writes_manual_source_metadata(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_manifest(
        cfg, "a", {"id": "a", "source_metadata": {"title": "Seed", "metadata_source": "filename"}}
    )
    client = _client(cfg)

    resp = client.put(
        "/api/bibliography/a",
        json={"title": "Fixed Title", "year": "2023", "authors": "Jane Smith, Mo Doe"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Fixed Title"
    assert body["year"] == 2023                      # coerced to int
    assert body["authors"] == ["Jane Smith", "Mo Doe"]  # comma string split
    assert body["metadata_source"] == "manual"
    assert body["editable"] is True
    on_disk = _json.loads((cfg.article_store_dir / "a" / "article-metadata.json").read_text())
    assert on_disk["source_metadata"]["metadata_source"] == "manual"


def test_put_bibliography_clears_a_field_with_null(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_manifest(
        cfg,
        "a",
        {"id": "a", "source_metadata": {"title": "T", "doi": "10.1/x", "metadata_source": "manual"}},
    )
    client = _client(cfg)
    resp = client.put("/api/bibliography/a", json={"doi": None})
    assert resp.status_code == 200
    assert "doi" not in resp.json()


def test_put_bibliography_rejects_garbage(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_manifest(cfg, "a", {"id": "a"})
    client = _client(cfg)
    assert client.put("/api/bibliography/a", json={"hacker": 1}).status_code == 400
    assert client.put("/api/bibliography/a", json={"year": "not-a-year"}).status_code == 400
    assert client.put("/api/bibliography/ghost", json={"title": "T"}).status_code == 404
