from __future__ import annotations

import itertools
import json as _json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import litschema.webapp.app as webapp
from litschema.config import LitSchemaConfig, load_config


def _project_cfg(project: Path) -> LitSchemaConfig:
    cfg = LitSchemaConfig(
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
    # Every real project has a resolvable extraction schema — `doctor` reports
    # its absence as an error, and the verifier refuses to interpret a run it
    # cannot type. Write it up front, before any run is published, so fixture
    # runs record the project's real schema hash like published runs do.
    _write_default_schema(cfg)
    return cfg


def _write_default_schema(cfg: LitSchemaConfig) -> None:
    """A real schema, so typed-editor metadata resolves like it does live."""
    cfg.schema_dir.mkdir(parents=True, exist_ok=True)
    (cfg.schema_dir / "extraction.yaml").write_text(
        "id: https://example.org/t\nname: t\n"
        "prefixes:\n  linkml: https://w3id.org/linkml/\n"
        "imports: [linkml:types]\ndefault_range: string\n"
        "classes:\n  Article:\n    tree_root: true\n    attributes:\n"
        "      article_id:\n        identifier: true\n"
        "      title: {}\n      ph:\n        range: float\n"
    )
    cfg.raw["extraction_schema_file"] = "extraction.yaml"


def _write_manifest(cfg: LitSchemaConfig, article_id: str, manifest: dict) -> None:
    article_dir = cfg.article_store_dir / article_id
    article_dir.mkdir(parents=True, exist_ok=True)
    (article_dir / "article-metadata.json").write_text(_json.dumps(manifest))

_RUN_SEQ = itertools.count()


def _client(cfg) -> TestClient:
    webapp.app.dependency_overrides[webapp.get_config] = lambda: cfg
    return TestClient(webapp.app)


def teardown_function() -> None:
    webapp.app.dependency_overrides.clear()


def _write_extraction(cfg, article_id: str, extraction: dict, reasoning: dict | None = None) -> str:
    """Publish a fresh run for the article; repeat calls model re-extraction."""
    from .helpers import publish_test_run

    article_dir = cfg.article_store_dir / article_id
    article_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"01TESTRUN{next(_RUN_SEQ):015d}XX"
    publish_test_run(article_dir, extraction, reasoning=reasoning, run_id=run_id)
    return run_id




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
                "metadata_source": "doi",
            },
        },
    )
    meta = webapp._article_meta(cfg, "a")
    assert meta["title"] == "T"
    assert meta["authors"] == ["Jane Smith"]
    assert meta["metadata_source"] == "doi"
    assert meta["editable"] is False


def test_article_meta_marks_auto_editable_and_ignores_legacy_keys(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_manifest(
        cfg, "f", {"id": "f", "source_metadata": {"title": "T", "metadata_source": "auto"}}
    )
    _write_manifest(cfg, "l", {"id": "l", "title": "Old", "year": 2019})

    assert webapp._article_meta(cfg, "f")["editable"] is True
    # Legacy top-level bib keys are dead: the manifest reads as an empty
    # editable record, same as any article with no source metadata yet.
    assert webapp._article_meta(cfg, "l") == {"metadata_source": "auto", "editable": True}


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


def test_list_articles_includes_assembled_but_unextracted(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_manifest(
        cfg,
        "noext",
        {"id": "noext", "source_metadata": {"title": "Unextracted Title", "metadata_source": "auto"}},
    )
    _write_manifest(
        cfg,
        "ext",
        {"id": "ext", "source_metadata": {"title": "Extracted Title", "metadata_source": "auto"}},
    )
    _write_extraction(cfg, "ext", {"article_id": "ext", "study_types": ["review"]})
    client = _client(cfg)

    body = client.get("/api/articles").json()

    by_id = {a["article_id"]: a for a in body["articles"]}
    assert set(by_id) == {"ext", "noext"}
    noext = by_id["noext"]
    assert noext["has_extraction"] is False
    assert noext["title"] == "Unextracted Title"
    assert noext["metadata_source"] == "auto"
    assert noext["n_setups"] == 0
    assert noext["n_fields"] == 0
    assert noext["n_reviewed"] == 0
    assert noext["n_verified"] == 0
    assert noext["n_overridden"] == 0
    assert noext["is_complete"] is False
    assert by_id["ext"]["has_extraction"] is True
    assert by_id["ext"]["title"] == "Extracted Title"


def test_list_articles_carries_overall_confidence_from_reasoning(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_manifest(cfg, "conf", {"id": "conf"})
    _write_extraction(
        cfg,
        "conf",
        {"article_id": "conf", "title": "T"},
        reasoning={"confidence": 0.55, "fields": []},
    )
    _write_manifest(cfg, "noconf", {"id": "noconf"})
    _write_extraction(cfg, "noconf", {"article_id": "noconf", "title": "T"})

    by_id = {
        a["article_id"]: a for a in _client(cfg).get("/api/articles").json()["articles"]
    }

    assert by_id["conf"]["confidence"] == 0.55  # the queue filter can see it
    assert by_id["noconf"]["confidence"] is None


def test_list_articles_treats_errored_extraction_as_unextracted(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_manifest(cfg, "bad", {"id": "bad", "source_metadata": {"title": "B", "metadata_source": "manual"}})
    # The marker shape the extraction contract defines, not a truthy `error`.
    _write_extraction(
        cfg, "bad", {"article_id": "bad", "error": True, "reason": "no extractable text"}
    )
    client = _client(cfg)

    (article,) = client.get("/api/articles").json()["articles"]

    assert article["article_id"] == "bad"
    assert article["has_extraction"] is False


def test_an_extraction_with_a_real_error_value_is_not_hidden(tmp_path) -> None:
    """`error` is an ordinary slot name in this domain.

    Treating any truthy `error` as a marker made a document with a measurement
    error of 0.42 read as unextracted — the verifier showed nothing to review
    and export dropped it, both silently.
    """
    cfg = _project_cfg(tmp_path)
    _write_schema(
        cfg,
        "id: https://example.org/t\nname: t\n"
        "prefixes:\n  linkml: https://w3id.org/linkml/\n"
        "imports: [linkml:types]\ndefault_range: string\n"
        "classes:\n  Article:\n    tree_root: true\n    attributes:\n"
        "      article_id:\n        identifier: true\n"
        "      error:\n        range: float\n",
    )
    _write_manifest(cfg, "sci", {"id": "sci"})
    _write_extraction(cfg, "sci", {"article_id": "sci", "error": 0.42})
    client = _client(cfg)

    (article,) = client.get("/api/articles").json()["articles"]

    assert article["has_extraction"] is True
    assert client.get("/api/article/sci").json()["error"] == 0.42


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


def test_put_bibliography_writes_manual_source_metadata(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_manifest(
        cfg, "a", {"id": "a", "source_metadata": {"title": "Seed", "metadata_source": "auto"}}
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


def test_put_bibliography_validates_doi_and_clears_on_empty_string(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_manifest(
        cfg, "a", {"id": "a", "source_metadata": {"title": "T", "metadata_source": "manual"}}
    )
    client = _client(cfg)

    # Junk can never enter the block, so the sync dead-end can't be created.
    assert client.put("/api/bibliography/a", json={"doi": "ISSN:1234-5678"}).status_code == 400

    # Valid but messy DOIs are normalized on the way in.
    ok = client.put("/api/bibliography/a", json={"doi": "https://doi.org/10.1234/x."})
    assert ok.status_code == 200
    assert ok.json()["doi"] == "10.1234/x"

    # Empty string clears (same convention as the CLI and the form).
    cleared = client.put("/api/bibliography/a", json={"title": ""})
    assert cleared.status_code == 200
    assert "title" not in cleared.json()


def test_invalid_article_ids_return_404_not_500(tmp_path) -> None:
    client = _client(_project_cfg(tmp_path))
    # backslash survives URL routing as a single path segment
    assert client.get("/api/bibliography/..%5Cx").status_code == 404


def test_cleared_doi_does_not_resurrect_from_legacy_identity(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    # Legacy-migrated article: stale top-level doi + a human-edited block.
    _write_manifest(
        cfg,
        "l",
        {
            "id": "l",
            "doi": "10.1234/wrong",
            "source_metadata": {
                "title": "Fixed",
                "doi": "10.1234/wrong",
                "metadata_source": "manual",
            },
        },
    )
    client = _client(cfg)

    resp = client.put("/api/bibliography/l", json={"doi": None})

    assert resp.status_code == 200
    assert "doi" not in resp.json()
    # GET must agree with PUT: once a block exists, its (absent) DOI is
    # authoritative — the legacy top-level copy must not resurrect.
    meta = client.get("/api/bibliography/l").json()
    assert "doi" not in meta


def test_sync_bibliography_overwrites_manual_and_locks(tmp_path, monkeypatch) -> None:
    from litschema.ingest import openalex_harvest

    cfg = _project_cfg(tmp_path)
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
    monkeypatch.setattr(
        openalex_harvest,
        "fetch_openalex",
        lambda doi, email=None: {
            "id": "https://openalex.org/W1",
            "doi": f"https://doi.org/{doi}",
            "title": "Registry Title",
            "publication_year": 2024,
        },
    )
    client = _client(cfg)

    resp = client.post("/api/bibliography/a/sync")

    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Registry Title"
    assert body["metadata_source"] == "doi"
    assert body["editable"] is False  # explicit consent overwrote manual and locked
    on_disk = _json.loads((cfg.article_store_dir / "a" / "article-metadata.json").read_text())
    assert on_disk["source_metadata"]["metadata_source"] == "doi"


def test_sync_bibliography_error_paths(tmp_path, monkeypatch) -> None:
    from litschema.ingest import openalex_harvest

    cfg = _project_cfg(tmp_path)
    _write_manifest(cfg, "no-doi", {"id": "no-doi"})
    _write_manifest(
        cfg,
        "gone",
        {"id": "gone", "source_metadata": {"doi": "10.1234/x", "metadata_source": "auto"}},
    )  # valid block doi: exercises the true registry-miss path
    monkeypatch.setattr(openalex_harvest, "fetch_openalex", lambda doi, email=None: None)
    client = _client(cfg)

    assert client.post("/api/bibliography/ghost/sync").status_code == 404
    assert client.post("/api/bibliography/no-doi/sync").status_code == 400
    assert client.post("/api/bibliography/gone/sync").status_code == 502


# ── run-explicit annotation API (v2) ─────────────────────────────────────────


def _article_with_run(cfg, article_id="a", extraction=None):
    _write_manifest(cfg, article_id, {"id": article_id})
    payload = extraction or {"article_id": article_id, "title": "T", "ph": 6.1}
    return _write_extraction(cfg, article_id, payload)


def test_annotation_round_trip_is_run_explicit(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    run_id = _article_with_run(cfg)
    client = _client(cfg)

    put = client.put(
        f"/api/annotations/a/{run_id}",
        json={"path": "ph", "override": {"op": "replace", "value": 6.5}, "note": "table 2"},
    )
    assert put.status_code == 200, put.text
    assert put.json()["state"] == "overridden"

    got = client.get(f"/api/annotations/a/{run_id}").json()
    assert got["run_id"] == run_id
    assert got["review_error"] is None
    assert got["annotations"] == [
        {"path": "ph", "state": "overridden", "override": {"op": "replace", "value": 6.5},
         "note": "table 2"}
    ]


def test_verify_is_an_empty_entry_not_a_status(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    run_id = _article_with_run(cfg)
    client = _client(cfg)

    client.put(f"/api/annotations/a/{run_id}", json={"path": "title"})

    annotation = client.get(f"/api/annotations/a/{run_id}").json()["annotations"][0]
    assert annotation == {"path": "title", "state": "verified"}


def test_annotation_writes_to_an_unknown_run_404(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _article_with_run(cfg)
    client = _client(cfg)

    assert client.get("/api/annotations/a/01NOSUCHRUN0000000000000X").status_code == 404
    assert client.put(
        "/api/annotations/a/01NOSUCHRUN0000000000000X", json={"path": "ph"}
    ).status_code == 404
    # Traversal-shaped run ids never reach the store: the guarded resolver
    # rejects a literal one, and an encoded one matches no route at all.
    assert client.get("/api/annotations/a/..").status_code >= 400
    assert client.get("/api/annotations/a/..%2F..%2Fetc").status_code >= 400


def test_annotation_rejects_contract_violations_with_400(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    run_id = _article_with_run(cfg)
    client = _client(cfg)

    missing = client.put(f"/api/annotations/a/{run_id}", json={"path": "nope"})
    assert missing.status_code == 400
    assert "does not resolve" in missing.text

    bad_op = client.put(
        f"/api/annotations/a/{run_id}", json={"path": "ph", "override": {"op": "bogus"}}
    )
    assert bad_op.status_code == 400

    malformed = client.put(f"/api/annotations/a/{run_id}", json={"path": "a..b"})
    assert malformed.status_code == 400


def test_corrupt_review_is_explicit_never_an_empty_list(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    run_id = _article_with_run(cfg)
    run_dir = cfg.article_store_dir / "a" / "extraction-runs" / run_id
    (run_dir / "review.json").write_text("{not json")
    client = _client(cfg)

    got = client.get(f"/api/annotations/a/{run_id}").json()
    assert got["annotations"] is None  # not [] — the caller must see the difference
    assert "unreadable" in got["review_error"]

    write = client.put(f"/api/annotations/a/{run_id}", json={"path": "ph"})
    assert write.status_code == 409
    assert (run_dir / "review.json").read_text() == "{not json"  # never destroyed


def test_delete_unreviews_the_subtree_and_gates_note_discard(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    run_id = _article_with_run(
        cfg, extraction={"article_id": "a", "exp": {"x": 1, "y": 2}}
    )
    client = _client(cfg)
    client.put(f"/api/annotations/a/{run_id}", json={"path": "exp", "note": "checked"})

    blocked = client.delete(f"/api/annotations/a/{run_id}/exp.x")
    assert blocked.status_code == 409
    assert "confirm" in blocked.text

    ok = client.delete(f"/api/annotations/a/{run_id}/exp.x?discard_note=true")
    assert ok.status_code == 200

    # exp.y keeps the coverage it had; exp.x is unreviewed.
    paths = {a["path"] for a in client.get(f"/api/annotations/a/{run_id}").json()["annotations"]}
    assert paths == {"exp.y"}


def test_articles_listing_reports_active_run_and_v2_counts(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    run_id = _article_with_run(cfg)
    client = _client(cfg)
    client.put(f"/api/annotations/a/{run_id}", json={"path": "ph"})

    entry = {a["article_id"]: a for a in client.get("/api/articles").json()["articles"]}["a"]

    assert entry["active_run_id"] == run_id
    assert entry["n_verified"] == 1
    assert entry["n_overridden"] == 0
    assert entry["review_error"] is None


# ── every read endpoint, exercised ───────────────────────────────────────────


def test_every_read_endpoint_answers_for_a_fully_populated_article(tmp_path) -> None:
    """Smoke-covers the whole read surface.

    The document view calls these together on load, so a single stale attribute
    on any of them breaks the page. Enumerating them here means a rename cannot
    pass tests while leaving an endpoint 500ing.
    """
    cfg = _project_cfg(tmp_path)
    _write_default_schema(cfg)
    _write_manifest(cfg, "a", {"id": "a", "filename": "a.pdf"})
    run_id = _write_extraction(
        cfg,
        "a",
        {"article_id": "a", "title": "T", "ph": 6.1},
        reasoning={"confidence": 0.7, "fields": [{"path": ".ph", "source_lines": "L3"}]},
    )
    (cfg.article_store_dir / "a" / "article.md").write_text("# A\n\nbody\n")
    client = _client(cfg)

    for path in (
        "/",
        "/api/articles",
        "/api/schema/fields",
        "/api/article/a",
        "/api/bibliography/a",
        "/api/markdown/a",
        "/api/reasoning/a",
        f"/api/annotations/a/{run_id}",
    ):
        response = client.get(path)
        assert response.status_code == 200, f"{path} -> {response.status_code} {response.text[:200]}"

    # The extraction endpoint serves the ACTIVE RUN's payload, not a stale
    # article-root file, and serves it raw so the client can show both values.
    assert client.get("/api/article/a").json() == {"article_id": "a", "title": "T", "ph": 6.1}


def test_read_endpoints_404_for_an_article_without_an_active_run(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_manifest(cfg, "bare", {"id": "bare"})
    client = _client(cfg)

    assert client.get("/api/article/bare").status_code == 404
    assert client.get("/api/reasoning/bare").status_code == 404
    # The article still lists — it is work to do, not an error.
    ids = {a["article_id"] for a in client.get("/api/articles").json()["articles"]}
    assert "bare" in ids


def test_articles_listing_describes_what_produced_the_active_run(tmp_path) -> None:
    """Provenance the reviewer can act on, not just an opaque identifier."""
    cfg = _project_cfg(tmp_path)
    _write_manifest(cfg, "a", {"id": "a"})
    run_id = _write_extraction(cfg, "a", {"article_id": "a", "title": "T"})
    run_json = cfg.article_store_dir / "a" / "extraction-runs" / run_id / "run.json"
    record = _json.loads(run_json.read_text())
    record["agent"] = {
        "harness": "claude-code",
        "provider": "anthropic",
        "model": "claude-sonnet-5",
        "effort": "high",
    }
    run_json.write_text(_json.dumps(record))

    entry = {a["article_id"]: a for a in _client(cfg).get("/api/articles").json()["articles"]}["a"]

    assert entry["active_run"]["model"] == "claude-sonnet-5"
    assert entry["active_run"]["effort"] == "high"
    assert entry["active_run"]["created_at"] == "2026-01-01T00:00:00+00:00"
    assert entry["active_run"]["run_id"] == run_id


def test_articles_listing_reports_no_run_metadata_when_unextracted(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_manifest(cfg, "bare", {"id": "bare"})

    entry = {
        a["article_id"]: a for a in _client(cfg).get("/api/articles").json()["articles"]
    }["bare"]

    assert entry["active_run"] is None
    assert entry["active_run_id"] is None


# ── project review policy and backfill ───────────────────────────────────────


def _config_project(tmp_path):
    cfg = _project_cfg(tmp_path)
    _write_default_schema(cfg)
    cfg.config_path.write_text(
        'project_root: "."\nschema_dir: "schema"\nextraction_schema_file: "extraction.yaml"\n'
        'article_store_dir: "data/papers"\n'
    )
    return cfg


def test_require_reviewer_binds_every_client_not_just_the_browser(tmp_path) -> None:
    """A policy the server does not enforce is advisory, and curl ignores it."""
    cfg = _config_project(tmp_path)
    _write_manifest(cfg, "a", {"id": "a"})
    run_id = _write_extraction(cfg, "a", {"article_id": "a", "title": "T", "ph": 6.1})
    client = _client(cfg)

    # Off by default: anonymous review is normal.
    assert client.put(f"/api/annotations/a/{run_id}", json={"path": "title"}).status_code == 200

    assert client.put("/api/settings", json={"require_reviewer": True}).json()["require_reviewer"]

    refused = client.put(f"/api/annotations/a/{run_id}", json={"path": "ph"})
    assert refused.status_code == 400
    assert "requires a reviewer" in refused.text

    ok = client.put(
        f"/api/annotations/a/{run_id}",
        json={"path": "ph", "reviewer": "0000-0002-1825-0097"},
    )
    assert ok.status_code == 200
    assert "require_reviewer: true" in cfg.config_path.read_text()


def test_settings_write_preserves_other_config_keys(tmp_path) -> None:
    """Unknown keys are preserved for domain repositories (project-config spec)."""
    cfg = _config_project(tmp_path)
    cfg.config_path.write_text(cfg.config_path.read_text() + 'custom_domain_key: keep-me\n')
    client = _client(cfg)

    client.put("/api/settings", json={"require_reviewer": True})
    client.put("/api/settings", json={"require_reviewer": False})

    text = cfg.config_path.read_text()
    assert "custom_domain_key: keep-me" in text
    assert "require_reviewer" not in text  # removed rather than left false


def test_backfill_attributes_only_anonymous_entries(tmp_path) -> None:
    """Never reassign someone else's review."""
    cfg = _config_project(tmp_path)
    _write_manifest(cfg, "a", {"id": "a"})
    run_id = _write_extraction(cfg, "a", {"article_id": "a", "title": "T", "ph": 6.1})
    run_dir = cfg.article_store_dir / "a" / "extraction-runs" / run_id
    (run_dir / "review.json").write_text(
        _json.dumps({
            "version": 2,
            "fields": {
                "title": {},
                "ph": {"reviewer": "0000-0001-5109-3700"},
            },
        })
    )
    client = _client(cfg)

    out = client.post(
        "/api/reviews/backfill-reviewer", json={"reviewer": "0000-0002-1825-0097"}
    ).json()

    assert out["updated"] == 1
    fields = _json.loads((run_dir / "review.json").read_text())["fields"]
    assert fields["title"]["reviewer"] == "0000-0002-1825-0097"
    assert fields["ph"]["reviewer"] == "0000-0001-5109-3700"  # untouched


def test_settings_reports_repo_context_for_the_backfill_warning(tmp_path) -> None:
    cfg = _config_project(tmp_path)
    client = _client(cfg)

    assert client.get("/api/settings").json()["in_git_repo"] is False
    (cfg.project_root / ".git").mkdir()
    assert client.get("/api/settings").json()["in_git_repo"] is True


# ── schema identity between a run and the schema used to interpret it ────────


def test_progress_is_null_with_a_schema_error_when_the_schema_moved(tmp_path) -> None:
    """A review is only meaningful against the schema the run was extracted with.

    Silently aggregating against today's schema reported confident numbers for
    a run it no longer describes. `specs/verifier/spec.md` requires the counts
    to be null and the reason to be named.
    """
    cfg = _project_cfg(tmp_path)
    _write_manifest(cfg, "a", {"id": "a"})
    from .helpers import publish_test_run

    publish_test_run(
        cfg.article_store_dir / "a",
        {"article_id": "a", "title": "T", "ph": 6.1},
        run_id="01OLDSCHEMA00000000000000",
        schema_hash="sha256:extracted-against-something-else",
    )
    client = _client(cfg)

    entry = {a["article_id"]: a for a in client.get("/api/articles").json()["articles"]}["a"]

    assert entry["schema_error"]
    assert "different schema" in entry["schema_error"]
    assert entry["n_fields"] is None
    assert entry["n_verified"] is None
    assert entry["is_complete"] is None


def test_overrides_are_refused_when_the_schema_moved_but_verification_is_not(
    tmp_path,
) -> None:
    """Only overrides need the schema.

    Verification asserts the agent was right about what is already there, so
    blocking it too would strand a reviewer mid-audit over a schema edit that
    never touched the field in front of them.
    """
    cfg = _project_cfg(tmp_path)
    _write_manifest(cfg, "a", {"id": "a"})
    from .helpers import publish_test_run

    run_id = "01OLDSCHEMA00000000000001"
    publish_test_run(
        cfg.article_store_dir / "a",
        {"article_id": "a", "title": "T", "ph": 6.1},
        run_id=run_id,
        schema_hash="sha256:extracted-against-something-else",
    )
    client = _client(cfg)

    edit = client.put(
        f"/api/annotations/a/{run_id}",
        json={"path": "ph", "override": {"op": "replace", "value": "7.2"}},
    )
    assert edit.status_code == 409
    assert "cannot judge this override" in edit.json()["detail"]

    # A removal is judged against the schema too — by whether the slot is an
    # identifier — so it is refused on the same grounds, not waved through.
    removal = client.put(
        f"/api/annotations/a/{run_id}",
        json={"path": "ph", "override": {"op": "remove"}},
    )
    assert removal.status_code == 409

    verify = client.put(f"/api/annotations/a/{run_id}", json={"path": "ph"})
    assert verify.status_code == 200, verify.text
    assert verify.json()["state"] == "verified"


def test_progress_names_an_unresolvable_schema_rather_than_reporting_zero(tmp_path) -> None:
    cfg = _project_cfg(tmp_path)
    _write_manifest(cfg, "a", {"id": "a"})
    _write_extraction(cfg, "a", {"article_id": "a", "title": "T", "ph": 6.1})
    (cfg.schema_dir / "extraction.yaml").write_text("this: is: not: linkml: [[[\n")
    client = _client(cfg)

    entry = {a["article_id"]: a for a in client.get("/api/articles").json()["articles"]}["a"]

    assert entry["schema_error"]
    assert entry["n_fields"] is None
