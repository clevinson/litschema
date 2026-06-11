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


def test_article_meta_marks_filename_editable_and_ignores_legacy_keys(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_manifest(
        cfg, "f", {"id": "f", "source_metadata": {"title": "T", "metadata_source": "filename"}}
    )
    _write_manifest(cfg, "l", {"id": "l", "title": "Old", "year": 2019})

    assert webapp._article_meta(cfg, "f")["editable"] is True
    # Legacy top-level bib keys are dead: the manifest reads as an empty
    # editable record, same as any article with no source metadata yet.
    assert webapp._article_meta(cfg, "l") == {"metadata_source": "filename", "editable": True}


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
    assert metadata["fields"]["blinding"]["kind"] == "enum"
    assert metadata["fields"]["primary_endpoint"]["kind"] == "string"


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


def test_annotation_from_entry_maps_spec_names_to_api_names() -> None:
    entry = {
        "author": "0000-0002-1825-0097",
        "signal": "flagged",
        "timestamp": "t1",
        "override_value": "6.5",
        "note": "n",
    }

    ann = webapp._annotation_from_entry("experiments[0].ph", entry)

    assert ann == {
        "path": "experiments[0].ph",
        "status": "flagged",
        "reviewer": "0000-0002-1825-0097",
        "timestamp": "t1",
        "correct_value": "6.5",
        "note": "n",
    }


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
        json={
            "title": "Fixed Title",
            "year": "2023",
            "authors": "Jane Smith, Mo Doe",
            "corporate_author": "Carbon Direct",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Fixed Title"
    assert body["year"] == 2023                      # coerced to int
    assert body["authors"] == ["Jane Smith", "Mo Doe"]  # comma string split
    assert body["corporate_author"] == "Carbon Direct"  # accepted verbatim, never split
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


def _write_extraction(cfg, article_id: str, extraction: dict) -> None:
    article_dir = cfg.article_store_dir / article_id
    article_dir.mkdir(parents=True, exist_ok=True)
    (article_dir / "agent-extraction.json").write_text(_json.dumps(extraction))


def test_put_annotation_round_trip_via_review_json(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_extraction(cfg, "a", {"article_id": "a", "title": "T"})
    client = _client(cfg)

    resp = client.put(
        "/api/annotations/a",
        json={"path": ".title", "status": "flagged",
              "reviewer": "0000-0002-1825-0097", "correct_value": "Better"},
    )
    assert resp.status_code == 200

    # storage uses the spec shape...
    on_disk = _json.loads((cfg.article_store_dir / "a" / "review.json").read_text())
    (entry,) = on_disk["fields"]["title"]
    assert entry["signal"] == "flagged"
    assert entry["author"] == "0000-0002-1825-0097"
    assert entry["override_value"] == "Better"
    assert "status" not in entry and "correct_value" not in entry

    # ...while the API keeps its historical shape
    anns = client.get("/api/annotations/a").json()["annotations"]
    (ann,) = anns
    assert ann["path"] == "title"
    assert ann["status"] == "flagged"
    assert ann["reviewer"] == "0000-0002-1825-0097"
    assert ann["correct_value"] == "Better"


def test_delete_annotation_clears_review_json(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_extraction(cfg, "a", {"article_id": "a", "title": "T"})
    client = _client(cfg)
    client.put("/api/annotations/a", json={"path": ".title", "status": "verified", "reviewer": ""})

    assert client.delete("/api/annotations/a/title").status_code == 200
    assert client.get("/api/annotations/a").json()["annotations"] == []
    assert not (cfg.article_store_dir / "a" / "review.json").exists()


def test_get_annotations_sets_aside_legacy_jsonl(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_extraction(cfg, "a", {"article_id": "a", "title": "T"})
    article_dir = cfg.article_store_dir / "a"
    (article_dir / "reviews.jsonl").write_text(
        _json.dumps({"path": ".title", "status": "verified", "reviewer": "A", "timestamp": "t"}) + "\n"
    )
    client = _client(cfg)

    anns = client.get("/api/annotations/a").json()["annotations"]

    assert anns == []                                   # throwaway data, not converted
    assert not (article_dir / "reviews.jsonl").exists()
    assert (article_dir / "reviews.jsonl.bak").exists()


def _write_schema(cfg, text: str) -> None:
    cfg.schema_dir.mkdir(parents=True, exist_ok=True)
    (cfg.schema_dir / "extraction.yaml").write_text(text)
    (cfg.config_path).write_text(
        'schema_dir: "schema"\nextraction_schema_file: "extraction.yaml"\n'
        'data_dir: "data"\narticle_store_dir: "data/papers"\npaper_inbox_dir: "papers-inbox"\n'
    )


_TYPED_SCHEMA = """
id: https://example.org/t
name: t
prefixes: {t: "https://example.org/t/", linkml: "https://w3id.org/linkml/"}
default_prefix: t
default_range: string
imports: [linkml:types]
enums:
  Mood: {permissible_values: {happy: {}, sad: {}}}
classes:
  Root:
    tree_root: true
    attributes:
      article_id: {identifier: true}
      mood: {range: Mood}
      score: {range: float}
      n_samples: {range: integer}
      replicated: {range: boolean}
      label: {range: string}
"""


def test_schema_fields_reports_kind_for_every_scalar_slot(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_schema(cfg, _TYPED_SCHEMA)
    client = _client(cfg)

    fields = client.get("/api/schema/fields").json()["fields"]

    assert fields["mood"]["kind"] == "enum"
    assert [v["value"] for v in fields["mood"]["permissible_values"]] == ["happy", "sad"]
    assert fields["score"]["kind"] == "float"
    assert fields["n_samples"]["kind"] == "integer"
    assert fields["replicated"]["kind"] == "boolean"
    assert fields["label"]["kind"] == "string"
