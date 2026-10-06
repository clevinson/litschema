from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from litschema import cli
from litschema.agents import AGENTS, Agent, UnknownAgentError, parse_agents

# Captured at import, before the autouse fixture in conftest replaces it.
REAL_DETECTED = Agent.detected


def _init(tmp_path: Path, *args: str):
    project = tmp_path / "review"
    result = CliRunner().invoke(cli.app, ["init", str(project), *args])
    return project, result


@pytest.fixture
def config_dirs(tmp_path, monkeypatch):
    """Real detection, with both agents' config dirs under tmp_path; tests create them."""
    monkeypatch.setattr(Agent, "detected", REAL_DETECTED)
    claude, codex = tmp_path / "claude-config", tmp_path / "codex-home"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    monkeypatch.setenv("CODEX_HOME", str(codex))
    return claude, codex


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["codex"], ["codex"]),
        (["claude", "codex"], ["claude-code", "codex"]),
        (["codex,claude-code"], ["codex", "claude-code"]),
        (["all"], ["claude-code", "codex"]),
    ],
)
def test_parse_agents(values, expected) -> None:
    assert parse_agents(values) == expected


def test_parse_agents_refuses_unknown_names() -> None:
    with pytest.raises(UnknownAgentError, match="unknown agent 'gemini'"):
        parse_agents(["gemini"])


def test_an_agent_is_detected_by_its_config_dir(config_dirs) -> None:
    claude, _codex = config_dirs
    claude.mkdir()

    assert AGENTS["claude-code"].detected()
    assert not AGENTS["codex"].detected()


def test_a_shared_agents_dir_counts_for_codex(tmp_path, config_dirs) -> None:
    (tmp_path / "home" / ".agents").mkdir(parents=True)

    assert AGENTS["codex"].detected()
    assert not AGENTS["claude-code"].detected()


def test_init_sets_up_agents_whose_config_dir_exists(tmp_path, config_dirs) -> None:
    _claude, codex = config_dirs
    codex.mkdir()

    project, result = _init(tmp_path)

    assert result.exit_code == 0, result.output
    assert (project / ".agents" / "skills" / "litschema-onboard" / "SKILL.md").is_file()
    assert not (project / ".claude").exists()
    assert "network_access = true" in (project / ".codex" / "config.toml").read_text()
    assert "Open this folder in Codex" in result.output


def test_init_with_no_config_dirs_sets_up_every_agent(tmp_path) -> None:
    project, result = _init(tmp_path)

    assert result.exit_code == 0, result.output
    assert (project / ".claude" / "skills" / "extract-article" / "SKILL.md").is_file()
    assert (project / ".agents" / "skills" / "extract-article" / "SKILL.md").is_file()
    assert (project / ".codex" / "config.toml").is_file()


def test_init_agent_flag_overrides_detection(tmp_path, config_dirs) -> None:
    claude, codex = config_dirs
    claude.mkdir()
    codex.mkdir()

    project, result = _init(tmp_path, "--agent", "claude-code")

    assert result.exit_code == 0, result.output
    assert (project / ".claude" / "skills" / "extract-article" / "SKILL.md").is_file()
    assert not (project / ".agents").exists()
    assert not (project / ".codex").exists()


def test_init_refuses_an_unknown_agent(tmp_path) -> None:
    project, result = _init(tmp_path, "--agent", "gemini")

    assert result.exit_code == 2
    assert "unknown agent 'gemini'" in result.output
    assert not project.exists()


def test_skills_install_local_adds_the_agents_on_this_machine(
    tmp_path, config_dirs, monkeypatch
) -> None:
    claude, codex = config_dirs
    claude.mkdir()
    project, result = _init(tmp_path)
    assert result.exit_code == 0, result.output
    assert not (project / ".agents").exists()
    # A collaborator with Codex runs the install in the shared project.
    codex.mkdir()
    monkeypatch.chdir(project)

    installed = CliRunner().invoke(cli.app, ["skills", "install", "--local"])

    assert installed.exit_code == 0, installed.output
    assert (project / ".agents" / "skills" / "extract-article" / "SKILL.md").is_file()
    assert (project / ".codex" / "config.toml").is_file()
