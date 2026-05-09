from __future__ import annotations

import tomllib
from pathlib import Path

from typer.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_config(project) -> None:
    (project / "schema").mkdir()
    (project / "litschema.yaml").write_text('project_root: "."\nschema_dir: "schema"\n')


def test_skills_install_uses_bundled_skills_without_project_skills(tmp_path, monkeypatch) -> None:
    from litschema import cli

    _write_config(tmp_path)
    monkeypatch.setenv("LITSCHEMA_CONFIG", str(tmp_path / "litschema.yaml"))

    result = CliRunner().invoke(cli.app, ["skills", "install", "--copy"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".claude" / "skills" / "extract-article" / "SKILL.md").is_file()
    assert "/extract-article" in result.output
    assert "/validate-articles" not in result.output


def test_skills_install_project_local_skill_overrides_bundled_skill(tmp_path, monkeypatch) -> None:
    from litschema import cli

    _write_config(tmp_path)
    project_skill = tmp_path / "skills" / "extract-article"
    project_skill.mkdir(parents=True)
    project_skill.joinpath("SKILL.md").write_text("project-local override\n")
    monkeypatch.setenv("LITSCHEMA_CONFIG", str(tmp_path / "litschema.yaml"))

    result = CliRunner().invoke(cli.app, ["skills", "install", "--copy"])

    assert result.exit_code == 0, result.output
    installed = tmp_path / ".claude" / "skills"
    assert (
        installed.joinpath("extract-article", "SKILL.md").read_text() == "project-local override\n"
    )
    assert not installed.joinpath("validate-articles", "SKILL.md").exists()


def test_bundled_skills_are_included_in_wheel() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())

    force_include = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]

    assert force_include["skills"] == "litschema/_bundled_skills"
