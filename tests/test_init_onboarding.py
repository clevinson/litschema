from __future__ import annotations

import csv

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
    assert (project / "data" / "sources" / "articles.csv").is_file()
    assert (project / "papers-inbox").is_dir()
    assert not (project / ".claude" / "skills").exists()
    gitignore = (project / ".gitignore").read_text()
    assert "papers-inbox/*.pdf" in gitignore
    assert "papers-inbox/.processed/*.pdf" in gitignore
    assert "data/papers/*/*.pdf" in gitignore
    assert "data/papers/*/article.md" not in gitignore
    assert "agent-extraction.json" not in gitignore
    assert "agent-reasoning.json" not in gitignore
    assert "reviews.jsonl" not in gitignore

    with (project / "data" / "sources" / "articles.csv").open() as fh:
        assert next(csv.reader(fh)) == [
            "doi",
            "article_id",
            "title",
            "author_citation",
            "year",
            "publisher",
            "open_access",
            "extraction_provider",
            "extraction_model",
            "extraction_date",
            "schema_commit",
        ]
        fh.seek(0)
        rows = list(csv.DictReader(fh))
    assert rows == []
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
    assert "litschema skills install --local" in result.output
    assert "/litschema-assemble" in result.output
    assert "/extract-article <article-id>" in result.output
    assert "litschema convert" not in result.output
    assert "/litschema-builder" not in result.output
    assert "papers-inbox/" in result.output


def test_init_refuses_to_overwrite_existing_project_without_force(tmp_path) -> None:
    from litschema import cli

    project = tmp_path / "my-review"
    project.mkdir()
    project.joinpath("keep.txt").write_text("important\n")

    result = CliRunner().invoke(cli.app, ["init", str(project)])

    assert result.exit_code == 2
    assert project.joinpath("keep.txt").read_text() == "important\n"


def test_init_force_preserves_existing_project_files(tmp_path) -> None:
    from litschema import cli

    project = tmp_path / "my-review"
    project.joinpath("schema").mkdir(parents=True)
    project.joinpath("data", "sources").mkdir(parents=True)
    project.joinpath("litschema.yaml").write_text("project_root: existing\n")
    project.joinpath("domain_context.md").write_text("existing context\n")
    project.joinpath("schema", "extraction.yaml").write_text("existing schema\n")
    project.joinpath("data", "sources", "articles.csv").write_text(
        "doi,article_id,title\n10.1234/example,smith-2024,Existing\n"
    )
    project.joinpath(".gitignore").write_text("custom-ignore\n")

    result = CliRunner().invoke(cli.app, ["init", str(project), "--force"])

    assert result.exit_code == 0, result.output
    assert project.joinpath("litschema.yaml").read_text() == "project_root: existing\n"
    assert project.joinpath("domain_context.md").read_text() == "existing context\n"
    assert project.joinpath("schema", "extraction.yaml").read_text() == "existing schema\n"
    assert project.joinpath("data", "sources", "articles.csv").read_text().endswith(
        "10.1234/example,smith-2024,Existing\n"
    )
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
