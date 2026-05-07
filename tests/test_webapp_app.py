from __future__ import annotations

from types import SimpleNamespace

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
    monkeypatch.setattr(webapp, "CORPUS_PATH", tmp_path / "missing-corpus.yaml")
    monkeypatch.setattr(webapp, "_corpus_cache", None)
    monkeypatch.setattr(webapp, "_author_index", None)
    monkeypatch.setattr(webapp, "_author_file_index", None)
    monkeypatch.setattr(webapp.yaml, "safe_load", counted_safe_load)

    assert webapp._load_author_index()["author_a"]["family_name"] == "Author"
    assert webapp._load_author_index()["author_a"]["family_name"] == "Author"
    assert calls["count"] == 1
