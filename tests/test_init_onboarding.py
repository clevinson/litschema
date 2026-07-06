from __future__ import annotations

from typer.testing import CliRunner

from litschema.config import load_config


def test_init_scaffolds_standalone_project(tmp_path) -> None:
    from litschema import cli

    project = tmp_path / "my-review"

    result = CliRunner().invoke(cli.app, ["init", str(project), "--profile", "generic"])

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


def test_init_refuses_to_overwrite_existing_project_without_force(tmp_path) -> None:
    from litschema import cli

    project = tmp_path / "my-review"
    project.mkdir()
    project.joinpath("keep.txt").write_text("important\n")

    result = CliRunner().invoke(cli.app, ["init", str(project), "--profile", "generic"])

    assert result.exit_code == 2
    assert project.joinpath("keep.txt").read_text() == "important\n"


def test_init_refuses_existing_project_even_with_force(tmp_path) -> None:
    # Re-init is disallowed outright: an existing litschema.yaml means the
    # project is managed by editing it (or `litschema skills install`), never
    # by running init again.
    from litschema import cli

    project = tmp_path / "my-review"
    project.mkdir()
    project.joinpath("litschema.yaml").write_text("project_root: existing\n")
    project.joinpath("domain_context.md").write_text("existing context\n")

    result = CliRunner().invoke(cli.app, ["init", str(project), "--profile", "generic", "--force"])

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

    result = CliRunner().invoke(cli.app, ["init", str(project), "--profile", "generic", "--force"])

    assert result.exit_code == 0, result.output
    assert project.joinpath("keep.txt").read_text() == "important\n"
    assert 'document_profile: "generic"' in project.joinpath("litschema.yaml").read_text()
    gitignore = project.joinpath(".gitignore").read_text()
    assert "custom-ignore\n" in gitignore
    assert "papers-inbox/.processed/*.pdf" in gitignore
    assert project.joinpath("papers-inbox").is_dir()


def test_init_no_longer_accepts_source_modes(tmp_path) -> None:
    from litschema import cli

    project = tmp_path / "review"

    result = CliRunner().invoke(cli.app, ["init", str(project), "--source", "bibliography"])

    assert result.exit_code == 2
    assert not project.exists()


def test_init_profile_flag_writes_document_profile(tmp_path) -> None:
    from litschema import cli

    runner = CliRunner()
    project = tmp_path / "myreview"

    result = runner.invoke(cli.app, ["init", str(project), "--profile", "journal_article"])

    assert result.exit_code == 0
    config = (project / "litschema.yaml").read_text()
    assert 'document_profile: "journal_article"' in config
    assert "litschema harvest" in result.output  # journal next-steps mention harvest


def test_init_prompts_for_profile_when_flag_absent(tmp_path, monkeypatch) -> None:
    from litschema import cli

    # CliRunner stdin is not a TTY; force the interactive path for this test.
    monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: True)
    runner = CliRunner()
    project = tmp_path / "myreview"

    result = runner.invoke(cli.app, ["init", str(project)], input="2\n")

    assert result.exit_code == 0
    assert "What kind of documents" in result.output
    assert 'document_profile: "generic"' in (project / "litschema.yaml").read_text()
    assert "litschema harvest" not in result.output  # generic next-steps don't


def test_init_without_profile_is_scriptable_when_not_a_tty(tmp_path) -> None:
    # CI, pipes, and agents call bare `init` with stdin at EOF: no prompt,
    # no abort — the default profile applies, same as pressing Enter.
    from litschema import cli

    runner = CliRunner()
    project = tmp_path / "myreview"

    result = runner.invoke(cli.app, ["init", str(project)])

    assert result.exit_code == 0, result.output
    assert "What kind of documents" not in result.output
    assert 'document_profile: "generic"' in (project / "litschema.yaml").read_text()


def test_init_rejects_unknown_profile(tmp_path) -> None:
    from litschema import cli

    runner = CliRunner()
    result = runner.invoke(cli.app, ["init", str(tmp_path / "x"), "--profile", "scrolls"])
    assert result.exit_code != 0


def test_init_installs_skills_project_locally(tmp_path) -> None:
    from litschema import cli

    runner = CliRunner()
    project = tmp_path / "myreview"

    result = runner.invoke(cli.app, ["init", str(project), "--profile", "generic"])

    assert result.exit_code == 0
    assert (project / ".claude" / "skills" / "extract-article" / "SKILL.md").is_file()
    assert (project / ".claude" / "skills" / "litschema-onboard" / "SKILL.md").is_file()


def test_init_no_skills_opts_out(tmp_path) -> None:
    from litschema import cli

    runner = CliRunner()
    project = tmp_path / "myreview"

    result = runner.invoke(cli.app, ["init", str(project), "--profile", "generic", "--no-skills"])

    assert result.exit_code == 0
    assert not (project / ".claude").exists()
