from __future__ import annotations

from types import SimpleNamespace

import pytest

from litschema.config import DOCUMENT_PROFILES, document_profile


def test_document_profile_defaults_to_generic() -> None:
    assert document_profile(SimpleNamespace(raw={})) == "generic"


def test_document_profile_reads_raw_config() -> None:
    cfg = SimpleNamespace(raw={"document_profile": "journal_article"})
    assert document_profile(cfg) == "journal_article"


def test_document_profile_rejects_unknown_values() -> None:
    cfg = SimpleNamespace(raw={"document_profile": "scrolls"})
    with pytest.raises(ValueError, match="document_profile"):
        document_profile(cfg)


def test_profiles_constant_is_the_contract() -> None:
    assert DOCUMENT_PROFILES == ("journal_article", "generic")
