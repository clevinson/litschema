from __future__ import annotations

import tomllib
from pathlib import Path

from typer.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_skills_install_uses_bundled_skills_without_project_config(tmp_path, monkeypatch) -> None:
    from litschema import cli

    monkeypatch.delenv("LITSCHEMA_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir()

    result = CliRunner().invoke(cli.app, ["skills", "install"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".claude" / "skills" / "extract-article" / "SKILL.md").is_file()
    assert (tmp_path / ".claude" / "skills" / "litschema-onboard" / "SKILL.md").is_file()
    assert not (tmp_path / ".claude" / "skills" / "litschema-assemble" / "SKILL.md").exists()
    assert not (tmp_path / ".claude" / "skills" / "litschema-builder" / "SKILL.md").exists()
    assert "/extract-article" in result.output
    assert "/litschema-onboard" in result.output
    assert "/litschema-assemble" not in result.output
    assert "/litschema-builder" not in result.output
    assert "/validate-articles" not in result.output


def test_skills_install_ignores_project_local_skills(tmp_path, monkeypatch) -> None:
    from litschema import cli

    monkeypatch.delenv("LITSCHEMA_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".claude").mkdir()
    project_skill = tmp_path / "skills" / "extract-article"
    project_skill.mkdir(parents=True)
    project_skill.joinpath("SKILL.md").write_text("project-local override\n")

    result = CliRunner().invoke(cli.app, ["skills", "install"])

    assert result.exit_code == 0, result.output
    installed = tmp_path / ".claude" / "skills"
    installed_skill = installed.joinpath("extract-article", "SKILL.md").read_text()
    assert installed_skill != "project-local override\n"
    assert "# Extract Article Metadata" in installed_skill
    assert not installed.joinpath("validate-articles", "SKILL.md").exists()


def test_skills_install_agent_both_creates_global_destinations(tmp_path, monkeypatch) -> None:
    from litschema import cli

    monkeypatch.delenv("LITSCHEMA_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    result = CliRunner().invoke(cli.app, ["skills", "install", "--agent", "both"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".claude" / "skills" / "extract-article" / "SKILL.md").is_file()
    assert (tmp_path / ".codex" / "skills" / "extract-article" / "SKILL.md").is_file()


def test_skills_install_local_uses_project_claude_skills_dir(tmp_path, monkeypatch) -> None:
    from litschema import cli

    monkeypatch.delenv("LITSCHEMA_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    project = tmp_path / "review"
    project.mkdir()
    monkeypatch.chdir(project)

    result = CliRunner().invoke(cli.app, ["skills", "install", "--local"])

    assert result.exit_code == 0, result.output
    assert (project / ".claude" / "skills" / "extract-article" / "SKILL.md").is_file()
    assert (project / ".claude" / "skills" / "litschema-onboard" / "SKILL.md").is_file()
    assert not (project / ".claude" / "skills" / "litschema-assemble" / "SKILL.md").exists()
    assert not (project / ".claude" / "skills" / "litschema-builder" / "SKILL.md").exists()
    assert not (tmp_path / "home" / ".claude" / "skills").exists()
    assert "/litschema-builder" not in result.output


def test_skills_install_experimental_does_not_include_deferred_builder(
    tmp_path,
    monkeypatch,
) -> None:
    from litschema import cli

    monkeypatch.delenv("LITSCHEMA_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir()

    result = CliRunner().invoke(cli.app, ["skills", "install", "--experimental"])

    assert result.exit_code == 0, result.output
    assert not (tmp_path / ".claude" / "skills" / "litschema-builder" / "SKILL.md").exists()
    assert "/litschema-builder" not in result.output


def test_skills_install_auto_requires_existing_agent_config(tmp_path, monkeypatch) -> None:
    from litschema import cli

    monkeypatch.delenv("LITSCHEMA_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    result = CliRunner().invoke(cli.app, ["skills", "install"])

    assert result.exit_code == 2, result.output
    assert "no Claude Code or Codex config directory found" in result.output
    assert "--agent claude" in result.output


def test_bundled_skills_are_included_in_wheel() -> None:
    from litschema import cli

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    force_include = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]

    assert force_include["skills"] == "litschema/skills"

    bundled = cli._packaged_skills_dir()
    assert bundled.joinpath("extract-article", "SKILL.md").is_file()
    assert bundled.joinpath("litschema-onboard", "SKILL.md").is_file()
    assert not bundled.joinpath("litschema-assemble", "SKILL.md").exists()


def test_onboard_and_extract_skills_delegate_deterministic_pipeline_steps() -> None:
    onboard = (REPO_ROOT / "skills" / "litschema-onboard" / "SKILL.md").read_text()
    extract = (REPO_ROOT / "skills" / "extract-article" / "SKILL.md").read_text()

    assert "$LITSCHEMA assemble" in onboard
    assert "$LITSCHEMA prepare-text --all" in onboard
    assert onboard.index("$LITSCHEMA assemble") < onboard.index("$LITSCHEMA prepare-text --all")
    assert "$LITSCHEMA convert" not in onboard
    assert "extract-article" in onboard  # defers extraction mechanics to that skill
    assert "LITSCHEMA prepare-text {article_id}" in extract
    assert "agent record-extraction" in extract


def test_skill_setup_gates_resolve_cli_with_dev_override() -> None:
    onboard = (REPO_ROOT / "skills" / "litschema-onboard" / "SKILL.md").read_text()
    extract = (REPO_ROOT / "skills" / "extract-article" / "SKILL.md").read_text()

    for skill in (onboard, extract):
        # Resolution order: .litschema/cli dev override, then uv run, then bare CLI.
        assert "`.litschema/cli`" in skill
        assert skill.index("`.litschema/cli`") < skill.index("`uv run litschema`")
        assert "development override" in skill
        assert "never required for normal use" in skill
        # The gate must confirm the resolved command actually works.
        assert "$LITSCHEMA --help" in skill
