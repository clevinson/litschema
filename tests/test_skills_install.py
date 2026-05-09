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
    assert "/extract-article" in result.output
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

    assert force_include["skills"] == "litschema/_bundled_skills"

    bundled = cli._bundled_skills_dir()
    assert bundled.joinpath("extract-article", "SKILL.md").is_file()
