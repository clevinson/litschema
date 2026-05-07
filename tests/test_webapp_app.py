from __future__ import annotations

from types import SimpleNamespace

import pytest

from litschema.config import load_config
import litschema.webapp.app as webapp


def test_author_index_fallback_is_cached(monkeypatch, tmp_path) -> None:
    authors_path = tmp_path / "authors.yaml"
    authors_path.write_text(
        """
- id: author_a
  family_name: Author
  given_name: A.
"""
    )

    calls = {"count": 0}
    original_safe_load = webapp.yaml.safe_load

    def counted_safe_load(*args, **kwargs):
        calls["count"] += 1
        return original_safe_load(*args, **kwargs)

    monkeypatch.setattr(webapp, "_CFG", SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(webapp, "_author_file_index", None)
    monkeypatch.setattr(webapp.yaml, "safe_load", counted_safe_load)

    assert webapp._load_author_index()["author_a"]["family_name"] == "Author"
    assert webapp._load_author_index()["author_a"]["family_name"] == "Author"
    assert calls["count"] == 1


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
