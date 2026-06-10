from __future__ import annotations

from types import SimpleNamespace

import pytest

import litschema.webapp.app as webapp
from litschema.config import load_config


def test_load_author_index_returns_id_keyed_dict(tmp_path) -> None:
    authors_path = tmp_path / "authors.yaml"
    authors_path.write_text(
        """
- id: author_a
  family_name: Author
  given_name: A.
"""
    )
    cfg = SimpleNamespace(data_dir=tmp_path)

    index = webapp._load_author_index(cfg)

    assert index["author_a"]["family_name"] == "Author"
    assert index["author_a"]["given_name"] == "A."


def test_load_author_index_returns_empty_when_authors_yaml_missing(tmp_path) -> None:
    cfg = SimpleNamespace(data_dir=tmp_path)
    assert webapp._load_author_index(cfg) == {}


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
