from __future__ import annotations

from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from litschema import cli
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


def _scaffold(tmp_path, profile: str) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli.app, ["init", str(tmp_path / "p"), "--profile", profile, "--no-skills"]
    )
    assert result.exit_code == 0


def test_status_mentions_harvest_only_for_journal_profile(tmp_path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.delenv("LITSCHEMA_CONFIG", raising=False)

    _scaffold(tmp_path, "journal_article")
    monkeypatch.chdir(tmp_path / "p")
    assert "litschema harvest" in runner.invoke(cli.app, ["status"]).output

    _scaffold(tmp_path / "g", "generic")
    monkeypatch.chdir(tmp_path / "g" / "p")
    assert "litschema harvest" not in runner.invoke(cli.app, ["status"]).output
