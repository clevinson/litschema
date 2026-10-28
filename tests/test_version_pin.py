from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from litschema import cli
from litschema.version import (
    VERSION_MISMATCH_EXIT_CODE,
    installed_version,
    is_release,
    parse_direct_url,
    read_skill_stamp,
    stamp_skill,
    version_line,
)


def _init(tmp_path: Path, *extra: str) -> Path:
    project = tmp_path / "review"
    result = CliRunner().invoke(cli.app, ["init", str(project), *extra])
    assert result.exit_code == 0, result.output
    return project


def _run(project: Path, *args: str):
    return CliRunner(mix_stderr=False).invoke(
        cli.app, ["--config", str(project / "litschema.yaml"), *args]
    )


def _set_pin(project: Path, pin: str | None) -> None:
    config = project / "litschema.yaml"
    lines = [
        line for line in config.read_text().splitlines() if not line.startswith("litschema_version")
    ]
    if pin is not None:
        lines.append(f'litschema_version: "{pin}"')
    config.write_text("\n".join(lines) + "\n")


def test_version_flag_prints_version() -> None:
    result = CliRunner().invoke(cli.app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == version_line()
    assert installed_version() in result.output


def test_init_pins_the_running_version_and_stamps_skills(tmp_path) -> None:
    project = _init(tmp_path)

    assert f'litschema_version: "{installed_version()}"' in (
        project / "litschema.yaml"
    ).read_text()
    for skill in ("extract-article", "litschema-onboard"):
        skill_md = project / ".claude" / "skills" / skill / "SKILL.md"
        assert read_skill_stamp(skill_md) == installed_version()


def test_matching_pin_runs(tmp_path) -> None:
    project = _init(tmp_path)

    result = _run(project, "status")

    assert result.exit_code == 0, result.output
    assert result.stderr == ""


def test_mismatched_pin_stops_every_project_command(tmp_path) -> None:
    project = _init(tmp_path)
    _set_pin(project, "0.0.1")

    for command in (["status"], ["validate"], ["assemble"], ["runs", "list"]):
        result = _run(project, *command)
        assert result.exit_code == VERSION_MISMATCH_EXIT_CODE, (command, result.output)
        assert "pinned to litschema 0.0.1" in result.stderr
        assert installed_version() in result.stderr
        assert "uv tool install litschema==0.0.1" in result.stderr
        assert "skills install --project --force" in result.stderr


def test_dev_pin_does_not_suggest_pypi(tmp_path) -> None:
    project = _init(tmp_path)
    _set_pin(project, "0.1.2.dev36+g647a7f8f1")

    result = _run(project, "status")

    assert result.exit_code == VERSION_MISMATCH_EXIT_CODE
    assert "uv tool install" not in result.stderr
    assert "development build, not on PyPI" in result.stderr
    assert f'set litschema_version: "{installed_version()}"' in result.stderr


@pytest.mark.parametrize(
    ("version", "release"),
    [
        ("0.1.2", True),
        ("1.0.0rc1", True),
        ("0.1.2.post1", True),
        ("0.1.3.dev0", False),
        ("0.1.2.dev36+g647a7f8f1", False),
        ("0.1.2+local", False),
    ],
)
def test_is_release(version, release) -> None:
    assert is_release(version) is release


def test_unpinned_project_warns_and_runs(tmp_path) -> None:
    project = _init(tmp_path)
    _set_pin(project, None)

    result = _run(project, "status")

    assert result.exit_code == 0, result.output
    assert "has no litschema_version" in result.stderr


@pytest.mark.parametrize("skills_dir", [".claude", ".agents"])
def test_stale_project_skills_stop_until_reinstalled(tmp_path, monkeypatch, skills_dir) -> None:
    project = _init(tmp_path)
    skill_md = project / skills_dir / "skills" / "extract-article" / "SKILL.md"
    stamp_skill(skill_md, "0.0.1")

    result = _run(project, "status")
    assert result.exit_code == VERSION_MISMATCH_EXIT_CODE
    assert "extract-article" in result.stderr
    assert "skills install --project --force" in result.stderr

    monkeypatch.chdir(project)
    reinstall = CliRunner().invoke(cli.app, ["skills", "install", "--local", "--force"])
    assert reinstall.exit_code == 0, reinstall.output
    assert _run(project, "status").exit_code == 0


def test_doctor_reports_a_mismatch_instead_of_stopping(tmp_path) -> None:
    project = _init(tmp_path)
    _set_pin(project, "0.0.1")

    result = _run(project, "doctor")

    assert result.exit_code == 1
    assert "pinned to litschema 0.0.1" in result.stdout
    assert "resolve the version mismatch" in result.stdout


def test_doctor_reports_the_litschema_agents_will_run(tmp_path, monkeypatch) -> None:
    project = _init(tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/opt/bin/{name}")

    result = _run(project, "doctor")

    assert f"{version_line()} on PATH (/opt/bin/litschema)" in result.stdout


def test_doctor_tells_you_to_install_when_litschema_is_not_on_path(tmp_path, monkeypatch) -> None:
    project = _init(tmp_path)
    real_which = cli.shutil.which
    monkeypatch.setattr(
        cli.shutil, "which", lambda name: None if name == "litschema" else real_which(name)
    )

    result = _run(project, "doctor")

    assert result.exit_code == 1
    assert "litschema is not on PATH" in result.stdout
    assert "uv tool install litschema" in result.stdout


@pytest.mark.parametrize(
    ("raw", "kind", "path", "commit"),
    [
        (None, "release", None, None),
        (
            json.dumps({"url": "file:///home/me/litschema", "dir_info": {"editable": True}}),
            "local",
            "/home/me/litschema",
            None,
        ),
        (
            json.dumps({"url": "file:///tmp/litschema-0.1.1-py3-none-any.whl", "archive_info": {}}),
            "local",
            "/tmp/litschema-0.1.1-py3-none-any.whl",
            None,
        ),
        (
            json.dumps(
                {
                    "url": "https://github.com/clevinson/litschema",
                    "vcs_info": {"vcs": "git", "commit_id": "abc123", "requested_revision": "v0.1.1"},
                }
            ),
            "git",
            None,
            "abc123",
        ),
    ],
)
def test_install_source_from_direct_url(raw, kind, path, commit) -> None:
    source = parse_direct_url(raw)

    assert (source.kind, source.path, source.commit) == (kind, path, commit)


def test_stamp_skill_replaces_an_existing_stamp(tmp_path) -> None:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("---\nname: demo\ndescription: x\n---\n\n# Body\n")

    stamp_skill(skill_md, "0.1.1")
    stamp_skill(skill_md, "0.1.2")

    text = skill_md.read_text()
    assert read_skill_stamp(skill_md) == "0.1.2"
    assert text.count("litschema_version") == 1
    assert text.endswith("---\n\n# Body\n")
