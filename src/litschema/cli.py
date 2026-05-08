"""litschema CLI - single entry point for the pipeline.

Verbs: harvest / convert / extract / validate / verify / mcp / status /
doctor / skills install / init. The pipeline verbs delegate to ingest-module
mains; status/doctor/skills/mcp have first-class implementations here.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

import typer

from .articles import (
    iter_extraction_paths,
    iter_markdown_paths,
    iter_metadata_paths,
    iter_reasoning_paths,
    iter_review_paths,
)
from .config import CONFIG_FILENAME, LitSchemaConfig, load_config
from .ingest import validate_extraction

app = typer.Typer(
    name="litschema",
    help="Schema-driven, agentic extraction of structured data from scientific PDFs.",
    no_args_is_help=True,
    add_completion=False,
)


# ── Helpers ────────────────────────────────────────────────────────────────

CHECK = "\033[32m✓\033[0m"
WARN = "\033[33m⚠\033[0m"
CROSS = "\033[31m✗\033[0m"
DIM = "\033[2m"
RESET = "\033[0m"


def _disable_color_if_needed():
    if os.environ.get("NO_COLOR"):
        global CHECK, WARN, CROSS, DIM, RESET
        CHECK = "[OK]"
        WARN = "[WARN]"
        CROSS = "[FAIL]"
        DIM = ""
        RESET = ""


_disable_color_if_needed()


def _delegate(module: str, args: list[str]) -> None:
    """Invoke `python -m litschema.<module>` with args. Exits with the child's code."""
    result = subprocess.run([sys.executable, "-m", module, *args])
    raise typer.Exit(code=result.returncode)


def _count_files(path: Path, pattern: str = "*") -> int:
    return len(list(path.glob(pattern))) if path.is_dir() else 0


def _require_config() -> LitSchemaConfig:
    """Load litschema.yaml or emit an actionable message and exit 2.

    Every command that needs filesystem paths goes through here, so running
    `litschema status` (etc.) outside a project never dumps a traceback.
    """
    try:
        return load_config()
    except FileNotFoundError as exc:
        typer.secho(
            f"{CROSS} No {CONFIG_FILENAME} found in this directory tree.",
            fg=typer.colors.RED,
        )
        typer.echo(
            "\nRun `litschema init <domain-name>` to scaffold a new project, "
            "or cd into an existing one."
        )
        raise typer.Exit(code=2) from exc


def _schema_root_path(cfg: LitSchemaConfig) -> Path:
    """Resolve the domain's root schema file from config (with sensible default)."""
    raw = cfg.raw.get("schema_root", "erw_articles.yaml")
    return cfg.schema_dir / raw


def _valid_skill_dirs(skills_dir: Path) -> list[Path]:
    if not skills_dir.is_dir():
        return []
    return sorted(
        path for path in skills_dir.iterdir() if path.is_dir() and (path / "SKILL.md").exists()
    )


def _bundled_skills_dir() -> Path:
    packaged = resources.files("litschema") / "_bundled_skills"
    if packaged.is_dir():
        return Path(str(packaged))
    return Path(__file__).resolve().parents[2] / "skills"


def _skill_sources(cfg: LitSchemaConfig) -> list[Path]:
    """Return installable skills, with project-local skills overriding bundled defaults."""
    by_name = {path.name: path for path in _valid_skill_dirs(_bundled_skills_dir())}
    by_name.update({path.name: path for path in _valid_skill_dirs(cfg.project_root / "skills")})
    return [by_name[name] for name in sorted(by_name)]


# ── Pipeline verbs (delegate to existing module mains) ─────────────────────


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    help="Run bibliographic harvest (OpenAlex + CrossRef by default).",
)
def harvest(
    ctx: typer.Context,
    source: str = typer.Option(
        "both", "--source", help="Which API to harvest from: openalex | crossref | both"
    ),
    resolve: bool = typer.Option(
        True, "--resolve/--no-resolve", help="Run entity resolution after harvest"
    ),
):
    _require_config()
    if source in ("openalex", "both"):
        typer.echo(f"{DIM}→ harvesting OpenAlex...{RESET}")
        subprocess.run(
            [sys.executable, "-m", "litschema.ingest.openalex_harvest", *ctx.args], check=True
        )
    if source in ("crossref", "both"):
        typer.echo(f"{DIM}→ harvesting CrossRef...{RESET}")
        subprocess.run(
            [sys.executable, "-m", "litschema.ingest.crossref_harvest", *ctx.args], check=True
        )
    if resolve:
        typer.echo(f"{DIM}→ resolving entities...{RESET}")
        subprocess.run([sys.executable, "-m", "litschema.ingest.resolve_entities"], check=True)


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    help="Convert PDFs to markdown via pymupdf4llm.",
)
def convert(ctx: typer.Context):
    _require_config()
    _delegate("litschema.ingest.pdf_to_markdown", ctx.args)


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    help="Extract structured article data. Currently run extraction via bundled agent skills.",
)
def extract(ctx: typer.Context):
    # Stub for future provider-native structured-output extraction.
    _ = ctx
    typer.secho("`litschema extract` is not yet supported.", fg=typer.colors.YELLOW)
    typer.echo(
        "\nFor now, install the bundled agent skills with "
        "`litschema skills install`, then run `/extract-article <article-id>` "
        "inside an agent CLI from your configured project directory."
    )
    raise typer.Exit(code=2)


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    help="Validate per-article extractions against the LinkML schema.",
)
def validate(ctx: typer.Context):
    _require_config()

    typer.echo(f"{DIM}→ validating extractions against extraction schema{RESET}")
    raise typer.Exit(code=validate_extraction.run(list(ctx.args)))


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    help="Launch the verification webapp.",
)
def verify(ctx: typer.Context):
    _require_config()
    _delegate("litschema.webapp.app", ctx.args)


@app.command(
    help="Start the explore MCP server (DuckDB-backed SQL query tools).",
)
def mcp(
    rebuild: bool = typer.Option(
        False, "--rebuild", help="Force DuckDB rebuild even if sources haven't changed"
    ),
    db_path: Path | None = typer.Option(
        None, "--db-path", help="Override DuckDB location (default: .litschema/explore.duckdb)"
    ),
    transport: str = typer.Option("stdio", "--transport", help="MCP transport: stdio | http"),
    port: int = typer.Option(8765, "--port", help="HTTP port (ignored when --transport stdio)"),
    max_rows: int = typer.Option(
        200, "--max-rows", help="Cap on rows returned by run_sql per query"
    ),
):
    cfg = _require_config()
    from .explore.loader import build_store
    from .explore.server import build_server

    resolved_db = (db_path or (cfg.project_root / ".litschema" / "explore.duckdb")).resolve()

    # On stdio transport: log to stderr to keep stdout clean for MCP framing.
    err = transport == "stdio"
    typer.echo(f"{DIM}→ building explore store at {resolved_db}{RESET}", err=err)

    summary = build_store(cfg, db_path=resolved_db, force_rebuild=rebuild)

    msg = (
        f"{CHECK} {summary.extractions_loaded} extractions loaded"
        f" · {summary.reviews_applied} review-override set(s) applied"
        f" ({summary.overrides_applied} field overrides)"
        f" · articles table: {len(summary.article_columns)} columns"
        f" · {summary.authors_loaded} authors · {summary.institutions_loaded} institutions"
    )
    typer.echo(msg, err=err)

    server = build_server(cfg, resolved_db, max_rows=max_rows)
    if transport == "stdio":
        typer.echo(
            f"{DIM}→ MCP listening on stdio "
            f"(connect via `claude mcp add litschema -- uv run litschema mcp`){RESET}",
            err=True,
        )
        server.run()
    elif transport == "http":
        typer.echo(f"{DIM}→ MCP listening on http://127.0.0.1:{port}{RESET}")
        server.settings.port = port
        server.run(transport="streamable-http")
    else:
        typer.secho(
            f"{CROSS} unknown transport: {transport!r} (expected 'stdio' or 'http')",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)


# Docs serving is intentionally *not* a `litschema` CLI command — it's a
# repo-contributor concern, not a pipeline step. Run `make docs` for that.


# ── Skills subcommands ─────────────────────────────────────────────────────

skills_app = typer.Typer(help="Agentic skill management (.claude/skills/).", no_args_is_help=True)
app.add_typer(skills_app, name="skills")


@skills_app.command(
    "install",
    help="Install bundled agentic skills into .claude/skills/ (Claude Code compatible).",
)
def skills_install(
    dest: Path = typer.Option(Path(".claude/skills"), "--dest", help="Destination for skill links"),
    copy: bool = typer.Option(False, "--copy", help="Copy instead of symlink"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing"),
):
    cfg = _require_config()
    skill_sources = _skill_sources(cfg)
    if not skill_sources:
        typer.secho("no bundled or project-local skills found", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    # If --dest is relative, anchor it to the project root so running from
    # a subdirectory still installs into `<project>/.claude/skills/`.
    if not dest.is_absolute():
        dest = cfg.project_root / dest
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    installed = 0
    for skill_dir in skill_sources:
        target = dest / skill_dir.name
        if target.exists() or target.is_symlink():
            if not force:
                typer.echo(f"{WARN} {target} already exists (use --force to overwrite)")
                continue
            if target.is_symlink() or target.is_file():
                target.unlink()
            else:
                shutil.rmtree(target)
        if copy:
            shutil.copytree(skill_dir, target)
            typer.echo(f"{CHECK} copied {skill_dir.name} → {target}")
        else:
            target.symlink_to(skill_dir.resolve(), target_is_directory=True)
            typer.echo(f"{CHECK} linked {skill_dir.name} → {target}")
        installed += 1

    if installed == 0:
        typer.echo("No skills installed.")
    else:
        typer.echo("\nAvailable as slash-commands in agents that read .claude/skills/:")
        for skill_dir in skill_sources:
            typer.echo(f"  /{skill_dir.name}")


# ── Status + doctor (new) ──────────────────────────────────────────────────


@app.command(help="Show pipeline state: what's done, what's pending.")
def status():
    cfg = _require_config()

    metadata = len(list(iter_metadata_paths(cfg)))
    converted = len(list(iter_markdown_paths(cfg)))
    extractions = len(list(iter_extraction_paths(cfg)))
    reasoning = len(list(iter_reasoning_paths(cfg)))
    annotations = len(list(iter_review_paths(cfg)))

    schema_yaml = _schema_root_path(cfg)
    papers = _count_files(cfg.papers_dir, "*.pdf")

    def _rel(path: Path) -> str:
        """Show as project-relative where possible; absolute otherwise."""
        try:
            return str(path.relative_to(cfg.project_root))
        except ValueError:
            return str(path)

    typer.echo(f"domain dir:  {cfg.project_root}")
    typer.echo(
        f"schema:      {_rel(schema_yaml)}"
        if schema_yaml.exists()
        else f"schema:      {CROSS} not found"
    )
    typer.echo(f"papers:      {papers} PDFs in {cfg.papers_dir.name}/")
    typer.echo(f"articles:    {metadata} metadata files")
    typer.echo(f"converted:   {converted} markdown files")
    typer.echo(f"extracted:   {extractions} extractions")
    typer.echo(f"reasoning:   {reasoning} reasoning files")
    typer.echo(f"annotations: {annotations}")


@app.command(help="Diagnose configuration and dependency issues.")
def doctor():
    cfg = _require_config()
    issues: list[str] = []

    py_version = sys.version_info
    if py_version >= (3, 13):
        typer.echo(f"{CHECK} Python {py_version.major}.{py_version.minor}.{py_version.micro}")
    else:
        typer.echo(
            f"{WARN} Python {py_version.major}.{py_version.minor}.{py_version.micro} "
            f"(litschema targets 3.13+)"
        )

    if shutil.which("uv"):
        typer.echo(f"{CHECK} uv on PATH")
    else:
        typer.echo(f"{CROSS} uv not on PATH")
        issues.append("uv not installed — see https://docs.astral.sh/uv/")

    typer.echo(f"{CHECK} litschema.yaml at {cfg.config_path}")

    if cfg.schema_dir.is_dir():
        typer.echo(f"{CHECK} schema dir: {cfg.schema_dir}")
    else:
        typer.echo(f"{CROSS} schema dir missing: {cfg.schema_dir}")
        issues.append(f"create {cfg.schema_dir}")

    # Skills check
    claude_skills = cfg.project_root / ".claude" / "skills"
    if claude_skills.is_dir():
        installed = [p.name for p in claude_skills.iterdir() if (p / "SKILL.md").exists()]
        if installed:
            typer.echo(f"{CHECK} Claude Code skills linked: {', '.join(installed)}")
        else:
            typer.echo(f"{WARN} .claude/skills/ exists but no SKILL.md files found")
            issues.append("run `litschema skills install`")
    else:
        typer.echo(f"{WARN} Claude Code skills not installed")
        issues.append("run `litschema skills install`")

    if shutil.which("claude"):
        typer.echo(f"{CHECK} agent CLI on PATH (claude)")
    else:
        typer.echo(f"{WARN} no agent CLI on PATH — bundled skills need one to run")
        issues.append(
            "install an agentic CLI that reads .claude/skills/ "
            "(e.g. Claude Code: npm install -g @anthropic-ai/claude-code)"
        )

    if issues:
        typer.echo("\nNext steps:")
        for issue in issues:
            typer.echo(f"  • {issue}")
        raise typer.Exit(code=1)
    typer.echo("\nEverything looks good.")


# ── Init (stub) ────────────────────────────────────────────────────────────


@app.command(help="Scaffold a new domain project. Not yet implemented.")
def init(
    domain: str | None = typer.Argument(None, help="Domain name (e.g. 'my-study')"),
):
    typer.secho(
        "`litschema init` is planned for a later release. "
        "For now, copy a template from src/litschema/templates/ "
        "(e.g. agriculture/) into your project's schema/ directory.",
        fg=typer.colors.YELLOW,
    )
    raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
