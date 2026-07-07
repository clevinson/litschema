from __future__ import annotations

from litschema.article_registry import is_valid_doi, normalize_doi


def test_normalize_doi_strips_url_prefixes_and_trailing_punctuation() -> None:
    assert normalize_doi("https://doi.org/10.1234/example") == "10.1234/example"
    assert normalize_doi("http://doi.org/10.1234/example") == "10.1234/example"
    assert normalize_doi("  10.1234/example.,;)") == "10.1234/example"


def test_is_valid_doi_accepts_canonical_and_url_forms() -> None:
    assert is_valid_doi("10.1234/example")
    assert is_valid_doi("https://doi.org/10.1016/j.jclepro.2023.138914")


def test_is_valid_doi_rejects_non_dois() -> None:
    assert not is_valid_doi("ISSN: 2278-4632")
    assert not is_valid_doi("")
    assert not is_valid_doi("not-a-doi")
    assert not is_valid_doi("10.12/too-short-prefix")
