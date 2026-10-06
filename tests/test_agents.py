from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from litschema import cli
from litschema.agents import UnknownAgentError, parse_agents, project_agents


def _init(tmp_path: Path, *args: str, input: str | None = None):
    project = tmp_path / "review"
    result = CliRunner().invoke(cli.app, ["init", str(project), *args], input=input)
    return project, result


def _recorded(project: Path) -> list[str]:
    return yaml.safe_load((project / "litschema.yaml").read_text())["agents"]


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["codex"], ["codex"]),
        (["claude", "codex"], ["claude-code", "codex"]),
        (["codex,claude-code"], ["codex", "claude-code"]),
        (["all"], ["claude-code", "codex"]),
        (["codex", "all"], ["codex", "claude-code"]),
    ],
)
def test_parse_agents(values, expected) -> None:
    assert parse_agents(values) == expected


def test_parse_agents_refuses_unknown_names() -> None:
    with pytest.raises(UnknownAgentError, match="unknown agent 'gemini'"):
        parse_agents(["gemini"])


def test_projects_without_the_key_get_every_agent() -> None:
    assert project_agents({}) == ["claude-code", "codex"]
    assert project_agents({"agents": ["codex"]}) == ["codex"]


def test_init_for_codex_only(tmp_path) -> None:
    project, result = _init(tmp_path, "--agent", "codex")

    assert result.exit_code == 0, result.output
    assert _recorded(project) == ["codex"]
    assert (project / ".agents" / "skills" / "litschema-onboard" / "SKILL.md").is_file()
    assert not (project / ".claude").exists()
    config = (project / ".codex" / "config.toml").read_text()
    assert "network_access = true" in config
    assert "Open this folder in Codex" in result.output


def test_init_for_claude_code_only_writes_no_codex_config(tmp_path) -> None:
    project, result = _init(tmp_path, "--agent", "claude-code")

    assert result.exit_code == 0, result.output
    assert _recorded(project) == ["claude-code"]
    assert (project / ".claude" / "skills" / "extract-article" / "SKILL.md").is_file()
    assert not (project / ".agents").exists()
    assert not (project / ".codex").exists()


def test_init_without_a_terminal_uses_detected_agents(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "litschema.agents.Agent.detected", lambda self: self.name == "claude-code"
    )

    project, result = _init(tmp_path)

    assert result.exit_code == 0, result.output
    assert _recorded(project) == ["claude-code"]


def test_init_with_nothing_detected_sets_up_every_agent(tmp_path) -> None:
    project, result = _init(tmp_path)

    assert result.exit_code == 0, result.output
    assert _recorded(project) == ["claude-code", "codex"]


def test_init_asks_on_a_terminal(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "_interactive", lambda: True)

    project, result = _init(tmp_path, input="9\n2\n")

    assert result.exit_code == 0, result.output
    assert "Which coding agents will you use with this project?" in result.output
    assert "enter numbers from 1 to 2" in result.output
    assert _recorded(project) == ["codex"]


def test_init_refuses_an_unknown_agent(tmp_path) -> None:
    project, result = _init(tmp_path, "--agent", "gemini")

    assert result.exit_code == 2
    assert "unknown agent 'gemini'" in result.output
    assert not project.exists()


def test_skills_install_local_follows_the_recorded_agents(tmp_path, monkeypatch) -> None:
    project, result = _init(tmp_path, "--agent", "claude-code")
    assert result.exit_code == 0, result.output
    config = project / "litschema.yaml"
    config.write_text(config.read_text().replace("agents: [claude-code]", "agents: [codex]"))
    monkeypatch.chdir(project)

    installed = CliRunner().invoke(cli.app, ["skills", "install", "--local"])

    assert installed.exit_code == 0, installed.output
    assert (project / ".agents" / "skills" / "extract-article" / "SKILL.md").is_file()
    assert (project / ".codex" / "config.toml").is_file()
