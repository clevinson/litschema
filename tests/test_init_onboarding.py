from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from litschema.config import load_config


def test_init_scaffolds_standalone_project(tmp_path) -> None:
    from litschema import cli

    project = tmp_path / "my-review"

    result = CliRunner().invoke(cli.app, ["init", str(project)])

    assert result.exit_code == 0, result.output
    assert (project / "litschema.yaml").is_file()
    assert (project / "domain_context.md").is_file()
    assert (project / "schema" / "extraction.yaml").is_file()
    assert (project / "data" / "papers").is_dir()
    # Onboarding is local-PDF-first: no CSV registry is scaffolded.
    assert not (project / "data" / "sources" / "articles.csv").exists()
    assert (project / "papers-inbox").is_dir()
    assert (project / ".claude" / "skills" / "extract-article" / "SKILL.md").is_file()
    gitignore = (project / ".gitignore").read_text()
    assert "papers-inbox/*.pdf" in gitignore
    assert "papers-inbox/.processed/*.pdf" in gitignore
    assert "data/papers/*/*.pdf" in gitignore
    assert "data/papers/*/article.md" not in gitignore
    assert "agent-extraction.json" not in gitignore
    assert "agent-reasoning.json" not in gitignore
    assert "reviews.jsonl" not in gitignore

    cfg = load_config(project / "litschema.yaml", reload=True)
    assert cfg.paper_inbox_dir == project / "papers-inbox"
    assert "extraction_schema_file: \"extraction.yaml\"" in (project / "litschema.yaml").read_text()
    assert "paper_inbox_dir: \"papers-inbox\"" in (project / "litschema.yaml").read_text()
    assert "document_profile" not in (project / "litschema.yaml").read_text()
    schema = (project / "schema" / "extraction.yaml").read_text()
    assert "article_id:" in schema
    assert "confidence:" not in schema
    assert "reasoning:" not in schema
    assert "Next steps" in result.output
    assert f"cd {project}" in result.output
    assert "/litschema-onboard" in result.output
    assert "/litschema-assemble" not in result.output
    assert "litschema skills install --local" not in result.output
    assert "litschema convert" not in result.output
    assert "/litschema-builder" not in result.output
    assert "papers-inbox/" in result.output


def test_init_refuses_non_empty_directory_without_force(tmp_path) -> None:
    from litschema import cli

    project = tmp_path / "my-review"
    project.mkdir()
    project.joinpath("keep.txt").write_text("important\n")

    result = CliRunner().invoke(cli.app, ["init", str(project)])

    assert result.exit_code == 2
    assert "--force" in result.output  # the refusal names its remedy
    assert project.joinpath("keep.txt").read_text() == "important\n"


def test_init_refuses_existing_project_without_force(tmp_path) -> None:
    from litschema import cli

    project = tmp_path / "my-review"
    project.mkdir()
    project.joinpath("litschema.yaml").write_text("project_root: existing\n")

    result = CliRunner().invoke(cli.app, ["init", str(project)])

    assert result.exit_code == 2
    assert "litschema.yaml" in result.output
    assert project.joinpath("litschema.yaml").read_text() == "project_root: existing\n"


def test_init_refuses_dangling_config_symlink(tmp_path) -> None:
    # exists() follows symlinks, so a dangling litschema.yaml symlink must be
    # caught explicitly — otherwise init half-scaffolds and then crashes (or
    # writes the config through the link, outside the project).
    from litschema import cli

    project = tmp_path / "my-review"
    project.mkdir()
    project.joinpath("litschema.yaml").symlink_to(tmp_path / "gone" / "litschema.yaml")

    result = CliRunner().invoke(cli.app, ["init", str(project), "--force"])

    assert result.exit_code == 2
    assert "litschema.yaml" in result.output
    assert not (project / "papers-inbox").exists()  # nothing was scaffolded


def test_init_refuses_existing_project_even_with_force(tmp_path) -> None:
    # Re-init is disallowed outright: an existing litschema.yaml means the
    # project is managed by editing it (or `litschema skills install`), never
    # by running init again.
    from litschema import cli

    project = tmp_path / "my-review"
    project.mkdir()
    project.joinpath("litschema.yaml").write_text("project_root: existing\n")
    project.joinpath("domain_context.md").write_text("existing context\n")

    result = CliRunner().invoke(cli.app, ["init", str(project), "--force"])

    assert result.exit_code == 2
    assert "litschema.yaml" in result.output
    assert project.joinpath("litschema.yaml").read_text() == "project_root: existing\n"
    assert project.joinpath("domain_context.md").read_text() == "existing context\n"
    assert not project.joinpath("papers-inbox").exists()


def test_init_force_initializes_non_empty_non_project_dir(tmp_path) -> None:
    # The legitimate --force case: a directory that already has files (a
    # README, .git, ...) but is not yet a litschema project.
    from litschema import cli

    project = tmp_path / "my-review"
    project.mkdir()
    project.joinpath("keep.txt").write_text("important\n")
    project.joinpath(".gitignore").write_text("custom-ignore\n")

    result = CliRunner().invoke(cli.app, ["init", str(project), "--force"])

    assert result.exit_code == 0, result.output
    assert project.joinpath("keep.txt").read_text() == "important\n"
    assert 'paper_inbox_dir: "papers-inbox"' in project.joinpath("litschema.yaml").read_text()
    gitignore = project.joinpath(".gitignore").read_text()
    assert "custom-ignore\n" in gitignore
    assert "papers-inbox/.processed/*.pdf" in gitignore
    assert project.joinpath("papers-inbox").is_dir()


def test_init_refuses_symlinked_scaffold_targets(tmp_path) -> None:
    # init must never write through a symlink to somewhere outside the
    # project (dotfiles-style .gitignore links, dangling links).
    from litschema import cli

    outside = tmp_path / "dotfiles" / "gitignore"
    outside.parent.mkdir()
    outside.write_text("custom\n")
    project = tmp_path / "my-review"
    project.mkdir()
    project.joinpath(".gitignore").symlink_to(outside)

    result = CliRunner().invoke(cli.app, ["init", str(project), "--force"])

    assert result.exit_code == 2
    assert "symlink" in result.output
    assert outside.read_text() == "custom\n"  # untouched

    project2 = tmp_path / "review-2"
    project2.mkdir()
    project2.joinpath("schema").symlink_to(tmp_path / "nowhere")

    result = CliRunner().invoke(cli.app, ["init", str(project2), "--force"])

    assert result.exit_code == 2
    assert "symlink" in result.output
    assert not (project2 / "litschema.yaml").exists()  # nothing scaffolded


def test_doctor_ignores_unrelated_skills(tmp_path, monkeypatch) -> None:
    # Someone else's skills in .claude/skills (or globally) are not a green
    # light: doctor counts only litschema's bundled skills.
    from litschema import cli

    runner = CliRunner()
    project = tmp_path / "myreview"
    result = runner.invoke(cli.app, ["init", str(project), "--no-skills"])
    assert result.exit_code == 0, result.output

    unrelated = project / ".claude" / "skills" / "totally-unrelated"
    unrelated.mkdir(parents=True)
    unrelated.joinpath("SKILL.md").write_text("something else\n")
    monkeypatch.setattr(cli, "_agent_skill_destinations", lambda agent: [])
    monkeypatch.chdir(project)

    result = runner.invoke(cli.app, ["--config", str(project / "litschema.yaml"), "doctor"])

    assert "skills not installed" in result.output
    assert "totally-unrelated" not in result.output


def test_doctor_reports_dev_cli_override(tmp_path, monkeypatch) -> None:
    # A .litschema/dev-cli file is the skills' first CLI resolution choice;
    # doctor surfaces its content so a stale override is visible.
    from litschema import cli

    runner = CliRunner()
    project = tmp_path / "myreview"
    result = runner.invoke(cli.app, ["init", str(project), "--no-skills"])
    assert result.exit_code == 0, result.output

    dev_cli = project / ".litschema" / "dev-cli"
    dev_cli.parent.mkdir(exist_ok=True)
    dev_cli.write_text("uv run --project ../litschema litschema\n")
    monkeypatch.chdir(project)

    result = runner.invoke(cli.app, ["--config", str(project / "litschema.yaml"), "doctor"])

    assert "CLI dev override (.litschema/dev-cli)" in result.output
    assert "uv run --project ../litschema litschema" in result.output


def test_doctor_warns_when_skills_cannot_resolve_cli(tmp_path, monkeypatch) -> None:
    # A data-only project (no pyproject.toml) with no override and no bare
    # `litschema` on PATH leaves the agent skills nothing to resolve — the
    # exact trap a returning dev-mode user hits. Doctor must say so and
    # suggest the dev-cli line.
    from litschema import cli

    runner = CliRunner()
    project = tmp_path / "myreview"
    result = runner.invoke(cli.app, ["init", str(project), "--no-skills"])
    assert result.exit_code == 0, result.output

    real_which = cli.shutil.which
    monkeypatch.setattr(
        cli.shutil, "which", lambda name: None if name == "litschema" else real_which(name)
    )
    monkeypatch.chdir(project)

    result = runner.invoke(cli.app, ["--config", str(project / "litschema.yaml"), "doctor"])

    assert "agent skills cannot resolve the litschema CLI" in result.output
    assert ".litschema/dev-cli" in result.output
    assert result.exit_code == 1  # surfaced as an actionable issue


def test_doctor_distrusts_own_venv_litschema_on_path(tmp_path, monkeypatch) -> None:
    # Under `uv run --project <checkout>`, the checkout venv's bin dir is on
    # PATH — a fresh skill shell would not have it. Doctor must not report
    # that as a resolvable bare CLI.
    import sys

    from litschema import cli

    runner = CliRunner()
    project = tmp_path / "myreview"
    result = runner.invoke(cli.app, ["init", str(project), "--no-skills"])
    assert result.exit_code == 0, result.output

    venv_cli = Path(sys.prefix) / "bin" / "litschema"
    real_which = cli.shutil.which
    monkeypatch.setattr(
        cli.shutil, "which", lambda name: str(venv_cli) if name == "litschema" else real_which(name)
    )
    monkeypatch.chdir(project)

    result = runner.invoke(cli.app, ["--config", str(project / "litschema.yaml"), "doctor"])

    assert "agent skills cannot resolve the litschema CLI" in result.output


def test_doctor_flags_legacy_cli_override_name(tmp_path, monkeypatch) -> None:
    from litschema import cli

    runner = CliRunner()
    project = tmp_path / "myreview"
    result = runner.invoke(cli.app, ["init", str(project), "--no-skills"])
    assert result.exit_code == 0, result.output

    legacy = project / ".litschema" / "cli"
    legacy.parent.mkdir(exist_ok=True)
    legacy.write_text("uv run --project ../litschema litschema\n")
    monkeypatch.chdir(project)

    result = runner.invoke(cli.app, ["--config", str(project / "litschema.yaml"), "doctor"])

    assert "legacy .litschema/cli" in result.output
    assert "rename .litschema/cli to .litschema/dev-cli" in result.output


def test_init_no_longer_accepts_source_modes(tmp_path) -> None:
    from litschema import cli

    project = tmp_path / "review"

    result = CliRunner().invoke(cli.app, ["init", str(project), "--source", "bibliography"])

    assert result.exit_code == 2
    assert not project.exists()


def test_init_no_longer_accepts_profile(tmp_path) -> None:
    # document_profile is gone: DOI enrichment is decided per article from
    # data (meta sync), not declared per project at init time.
    from litschema import cli

    project = tmp_path / "review"

    result = CliRunner().invoke(cli.app, ["init", str(project), "--profile", "journal_article"])

    assert result.exit_code == 2
    assert not project.exists()


def test_init_installs_skills_project_locally(tmp_path) -> None:
    from litschema import cli

    runner = CliRunner()
    project = tmp_path / "myreview"

    result = runner.invoke(cli.app, ["init", str(project)])

    assert result.exit_code == 0
    assert (project / ".claude" / "skills" / "extract-article" / "SKILL.md").is_file()
    assert (project / ".claude" / "skills" / "litschema-onboard" / "SKILL.md").is_file()


def test_init_no_skills_opts_out(tmp_path) -> None:
    from litschema import cli

    runner = CliRunner()
    project = tmp_path / "myreview"

    result = runner.invoke(cli.app, ["init", str(project), "--no-skills"])

    assert result.exit_code == 0
    assert not (project / ".claude").exists()
    # Next steps must not advertise a slash command that was not installed:
    # the install step comes first, the slash command only after it.
    assert "litschema skills install --local" in result.output
    assert result.output.index("skills install --local") < result.output.index(
        "/litschema-onboard"
    )


def test_doctor_recognizes_project_local_skills(tmp_path, monkeypatch) -> None:
    from litschema import cli

    runner = CliRunner()
    project = tmp_path / "myreview"
    result = runner.invoke(cli.app, ["init", str(project)])
    assert result.exit_code == 0, result.output

    # Doctor must not flag the init-default (project-local) install as missing.
    monkeypatch.chdir(project)
    result = runner.invoke(cli.app, ["--config", str(project / "litschema.yaml"), "doctor"])

    assert "agent skills installed (project-local)" in result.output
    assert "skills not installed" not in result.output


def test_doctor_reports_dev_cli_approval_state(tmp_path: Path, monkeypatch) -> None:
    """The override needs verifiable approval, not an agent's say-so."""
    import hashlib

    from typer.testing import CliRunner

    from litschema import cli

    project = tmp_path / "proj"
    (project / "schema").mkdir(parents=True)
    (project / "schema" / "extraction.yaml").write_text(
        "id: x\nname: x\nclasses:\n  A:\n    tree_root: true\n    attributes:\n"
        "      article_id:\n        identifier: true\n"
    )
    (project / "litschema.yaml").write_text(
        'project_root: "."\nschema_dir: "schema"\nextraction_schema_file: "extraction.yaml"\n'
    )
    dev_cli = project / ".litschema" / "dev-cli"
    dev_cli.parent.mkdir(parents=True)
    dev_cli.write_text("uv run --project ../litschema litschema\n")
    runner = CliRunner()
    args = ["--config", str(project / "litschema.yaml"), "doctor"]

    unapproved = runner.invoke(cli.app, args)
    assert "not yet approved" in unapproved.output
    assert "agents will stop and ask" in unapproved.output

    approved_file = project / ".litschema" / "dev-cli-approved"
    approved_file.write_text(hashlib.sha256(dev_cli.read_bytes()).hexdigest() + "\n")
    approved = runner.invoke(cli.app, args)
    assert "dev override approved for agent use" in approved.output

    # Editing the override invalidates the old approval automatically.
    dev_cli.write_text("uv run --project ../elsewhere litschema\n")
    changed = runner.invoke(cli.app, args)
    assert "changed since approval" in changed.output


def test_doctor_reports_unattributed_reviews_only_inside_a_repo(tmp_path: Path) -> None:
    """A repo implies the work may be shared; outside one, anonymous is normal."""
    import json as _json

    from typer.testing import CliRunner

    from litschema import cli
    from tests.helpers import TEST_RUN_ID, publish_test_run

    project = tmp_path / "proj"
    (project / "schema").mkdir(parents=True)
    (project / "schema" / "extraction.yaml").write_text(
        "id: x\nname: x\nclasses:\n  A:\n    tree_root: true\n    attributes:\n"
        "      article_id:\n        identifier: true\n"
    )
    (project / "litschema.yaml").write_text(
        'project_root: "."\nschema_dir: "schema"\nextraction_schema_file: "extraction.yaml"\n'
        'article_store_dir: "data/papers"\n'
    )
    article = project / "data" / "papers" / "a"
    article.mkdir(parents=True)
    (article / "article-metadata.json").write_text(_json.dumps({"id": "a"}))
    publish_test_run(article, {"article_id": "a", "title": "T"})
    run_dir = article / "extraction-runs" / TEST_RUN_ID
    (run_dir / "review.json").write_text(
        _json.dumps({"version": 2, "fields": {"title": {}}})
    )
    args = ["--config", str(project / "litschema.yaml"), "doctor"]
    runner = CliRunner()

    outside = runner.invoke(cli.app, args)
    assert "no reviewer" not in outside.output

    (project / ".git").mkdir()
    inside = runner.invoke(cli.app, args)
    assert "1 review entries have no reviewer" in inside.output
    assert "may be shared" in inside.output
