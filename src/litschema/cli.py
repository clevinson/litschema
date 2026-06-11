"""litschema CLI - single entry point for the pipeline.

Verbs: harvest / prepare-text / extract / validate / verify / mcp / status /
doctor / skills install / init.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

import typer

from .articles import (
    article_files,
    iter_extraction_paths,
    iter_markdown_paths,
    iter_metadata_paths,
    iter_reasoning_paths,
    iter_review_paths,
    record_extraction_provenance,
)
from .config import DOCUMENT_PROFILES, ConfigNotFoundError, LitSchemaConfig, document_profile
from .ingest import article_assembly, validate_extraction
from .project import Project
from .schema_resolution import extraction_schema_path

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
EXPERIMENTAL_SKILLS = {"litschema-builder"}


def _disable_color_if_needed():
    if os.environ.get("NO_COLOR"):
        global CHECK, WARN, CROSS, DIM, RESET
        CHECK = "[OK]"
        WARN = "[WARN]"
        CROSS = "[FAIL]"
        DIM = ""
        RESET = ""


_disable_color_if_needed()


@app.callback()
def main(
    ctx: typer.Context,
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        envvar="LITSCHEMA_CONFIG",
        help="Path to litschema.yaml.",
    ),
) -> None:
    ctx.obj = config


def _count_files(path: Path, pattern: str = "*") -> int:
    return len(list(path.glob(pattern))) if path.is_dir() else 0


def _schema_commit(cfg: LitSchemaConfig) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cfg.project_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


class _AssembleCliReporter:
    def __init__(self) -> None:
        self.label = "Inbox PDFs"
        self.total = 0
        self.current = 0
        self.show_progress = True

    def __call__(self, event: str, payload: dict[str, object]) -> None:
        if event == "start":
            typer.echo("Assembling article inputs")
            inbox_pdfs = int(payload.get("inbox_pdfs") or 0)
            self.total = inbox_pdfs
            self.current = 0
            self.show_progress = inbox_pdfs > 0
            if inbox_pdfs == 0:
                typer.echo("No inbox PDFs found.")
        elif event == "pdf_start":
            path = Path(str(payload["path"]))
            typer.echo(f"Processing PDF {payload['index']}/{payload['total']}: {path.name}")
        elif event == "pdf":
            self._advance()
            self._report_pdf(payload)
        elif event == "pdf_error":
            self._advance()
            path = Path(str(payload["path"]))
            error = payload.get("error")
            typer.echo(f"{CROSS} PDF failed: {path.name} ({error})")

    def _advance(self) -> None:
        self.current += 1
        if self.show_progress:
            typer.echo(f"{self.label} {self._bar()} {self.current}/{self.total}")

    def _bar(self) -> str:
        filled = 0 if self.total <= 0 else round((self.current / self.total) * 20)
        filled = max(0, min(20, filled))
        return f"[{'#' * filled}{'-' * (20 - filled)}]"

    def _report_pdf(self, payload: dict[str, object]) -> None:
        path = Path(str(payload["path"]))
        article_id = payload.get("article_id")
        result = str(payload.get("result"))
        if result == "assembled":
            typer.echo(f"{CHECK} PDF assembled: {path.name} → {article_id}")
        elif result == "already_assembled":
            typer.echo(f"{CHECK} PDF already assembled: {path.name} → {article_id}")
        else:
            typer.echo(f"{WARN} PDF {result}: {path.name}")


def _require_project(ctx: typer.Context | None = None) -> Project:
    """Load litschema.yaml or emit a colored message and exit 2.

    Thin CLI wrapper around :meth:`litschema.project.Project.open` that
    translates the typer-free :class:`ConfigNotFoundError` into colored
    output and an exit code. The exception's ``str(exc)`` already carries
    either the generic auto-discovery hint or the specific missing-path
    message — render it verbatim instead of substituting our own.
    """
    config_path = ctx.obj if ctx is not None and isinstance(ctx.obj, Path) else None
    try:
        return Project.open(config_path)
    except ConfigNotFoundError as exc:
        typer.secho(f"{CROSS} {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=2) from exc


def _valid_skill_dirs(skills_dir: Path) -> list[Path]:
    if not skills_dir.is_dir():
        return []
    return sorted(
        path for path in skills_dir.iterdir() if path.is_dir() and (path / "SKILL.md").exists()
    )


def _packaged_skills_dir() -> Path:
    packaged = resources.files("litschema") / "skills"
    if packaged.is_dir():
        return Path(str(packaged))
    return Path(__file__).resolve().parents[2] / "skills"


def _skill_sources(*, experimental: bool = False) -> list[Path]:
    """Return installable bundled skills from the litschema package."""
    skills = _valid_skill_dirs(_packaged_skills_dir())
    if experimental:
        return skills
    return [skill for skill in skills if skill.name not in EXPERIMENTAL_SKILLS]


def _agent_skill_destinations(agent: str) -> list[Path]:
    home = Path.home()
    destinations = {
        "claude": home / ".claude" / "skills",
        "codex": home / ".codex" / "skills",
    }
    agent = agent.lower()
    if agent == "auto":
        return [path for name, path in destinations.items() if (home / f".{name}").exists()]
    if agent == "both":
        return [destinations["claude"], destinations["codex"]]
    if agent in destinations:
        return [destinations[agent]]
    raise typer.BadParameter("--agent must be one of: auto, claude, codex, both")


def _project_skill_destination(project: Path) -> Path:
    return project.expanduser().resolve() / ".claude" / "skills"


def _install_skill_dirs(
    skill_sources: list[Path],
    dest: Path,
    *,
    copy: bool,
    force: bool,
) -> tuple[int, list[str]]:
    dest.mkdir(parents=True, exist_ok=True)
    installed = 0
    messages = []
    for skill_dir in skill_sources:
        target = dest / skill_dir.name
        if target.exists() or target.is_symlink():
            if not force:
                messages.append(f"{WARN} {target} already exists (use --force to overwrite)")
                continue
            if target.is_symlink() or target.is_file():
                target.unlink()
            else:
                shutil.rmtree(target)
        if copy:
            shutil.copytree(skill_dir, target)
            messages.append(f"{CHECK} copied {skill_dir.name} → {target}")
        else:
            target.symlink_to(skill_dir.resolve(), target_is_directory=True)
            messages.append(f"{CHECK} linked {skill_dir.name} → {target}")
        installed += 1
    return installed, messages


# ── Pipeline verbs ─────────────────────────────────────────────────────────


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
    project = _require_project(ctx)
    env = os.environ.copy()
    env["LITSCHEMA_CONFIG"] = str(project.config.config_path)
    if source in ("openalex", "both"):
        typer.echo(f"{DIM}→ harvesting OpenAlex...{RESET}")
        subprocess.run(
            [sys.executable, "-m", "litschema.ingest.openalex_harvest", *ctx.args],
            check=True,
            env=env,
        )
    if source in ("crossref", "both"):
        typer.echo(f"{DIM}→ harvesting CrossRef...{RESET}")
        subprocess.run(
            [sys.executable, "-m", "litschema.ingest.crossref_harvest", *ctx.args],
            check=True,
            env=env,
        )
    if resolve:
        typer.echo(f"{DIM}→ resolving entities...{RESET}")
        subprocess.run(
            [sys.executable, "-m", "litschema.ingest.resolve_entities"],
            check=True,
            env=env,
        )


@app.command("prepare-text", help="Prepare article markdown text from PDFs.")
def prepare_text(
    ctx: typer.Context,
    article_id: str | None = typer.Argument(
        None,
        help="Article ID to prepare. Use --all to prepare every known article.",
    ),
    all_articles: bool = typer.Option(
        False,
        "--all",
        help="Prepare markdown for every known article.",
    ),
    inbox_dir: Path | None = typer.Option(
        None, "--inbox-dir", help="Directory containing source PDFs."
    ),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Write flat {article_id}.md files to DIR instead of per-article folders.",
    ),
    force: bool = typer.Option(False, "--force", help="Rebuild existing markdown files."),
):
    if article_id is None and not all_articles:
        typer.secho(f"{CROSS} Specify an article_id or use --all", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    if article_id is not None and all_articles:
        typer.secho(f"{CROSS} Use either article_id or --all, not both", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    project = _require_project(ctx)
    from .ingest import pdf_to_markdown

    stats = pdf_to_markdown.run(
        project.config,
        article_ids=None if all_articles else [article_id],
        inbox_dir=inbox_dir,
        output_dir=output_dir,
        force=force,
    )
    typer.echo(json.dumps(stats, indent=2))


@app.command(help="Assemble article inputs from DOI rows and the PDF inbox.")
def assemble(ctx: typer.Context):
    project = _require_project(ctx)
    cfg = project.config
    try:
        stats = article_assembly.assemble(cfg, reporter=_AssembleCliReporter())
    except article_assembly.AssemblyInterrupted as exc:
        path = exc.pdf_path
        suffix = f" while processing {path.name}" if path is not None else ""
        typer.echo(f"\n{WARN} Assembly interrupted{suffix}. Progress has been saved.")
        typer.echo("Rerun `litschema assemble` to continue.")
        raise typer.Exit(code=130) from exc
    typer.echo(f"\n{CHECK} assembled article inputs")
    typer.echo("Summary")
    for key, value in stats.items():
        typer.echo(f"{key}: {value}")


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
    project = _require_project(ctx)
    cfg = project.config

    typer.echo(f"{DIM}→ validating extractions against extraction schema{RESET}")
    raise typer.Exit(code=validate_extraction.run(list(ctx.args), cfg))


@app.command(help="Launch the verification webapp.")
def verify(
    ctx: typer.Context,
    port: int = typer.Option(8000, "--port", "-p", help="Port for the local web server."),
):
    project = _require_project(ctx)
    from .webapp import app as webapp_app

    webapp_app.run_app(project.config, port=port)


@app.command(
    help="Start the explore MCP server (DuckDB-backed SQL query tools).",
)
def mcp(
    ctx: typer.Context,
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
    project = _require_project(ctx)
    cfg = project.config
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

skills_app = typer.Typer(help="Agentic skill management.", no_args_is_help=True)
app.add_typer(skills_app, name="skills")

agent_app = typer.Typer(
    help="Agent-facing helper commands used by bundled skills.", no_args_is_help=True
)
app.add_typer(agent_app, name="agent")


@agent_app.command("prepare-schema-context", help="Write runtime schema context files.")
def agent_prepare_schema_context(ctx: typer.Context):
    project = _require_project(ctx)
    cfg = project.config
    from .agent.prepare_schema_context import prepare_schema_context

    context = prepare_schema_context(cfg)
    typer.echo(f"extraction_schema={context.extraction_schema_path}")
    typer.echo(f"reasoning_schema={context.reasoning_schema_path}")


@agent_app.command(
    "validate-reasoning",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    help="Validate an agent reasoning file against the bundled reasoning schema.",
)
def agent_validate_reasoning(ctx: typer.Context):
    from .agent import validate_reasoning

    raise typer.Exit(code=validate_reasoning.run(list(ctx.args)))


@agent_app.command(
    "record-extraction", help="Record extraction provenance in article-metadata.json."
)
def agent_record_extraction(
    ctx: typer.Context,
    article_id: str = typer.Argument(..., help="Article identifier that was extracted"),
    provider: str | None = typer.Option(None, "--provider", help="Extraction provider, if known"),
    model: str | None = typer.Option(None, "--model", help="Extraction model, if known"),
):
    project = _require_project(ctx)
    cfg = project.config
    files = article_files(cfg, article_id)
    if not files.article_dir.is_dir():
        typer.secho(f"{CROSS} unknown article: {article_id}", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    record_extraction_provenance(
        files,
        provider=provider,
        model=model,
        extraction_date=datetime.now(UTC).isoformat(),
        schema_commit=_schema_commit(cfg),
    )
    typer.echo(f"{CHECK} recorded extraction provenance for {article_id}")


@skills_app.command(
    "install",
    help="Install bundled agentic skills globally or into a project-local skills directory.",
)
def skills_install(
    agent: str = typer.Option(
        "auto", "--agent", help="Agent destination: auto, claude, codex, or both"
    ),
    local: bool = typer.Option(
        False, "--local", help="Install into the current directory's .claude/skills"
    ),
    experimental: bool = typer.Option(
        False, "--experimental", help="Also install experimental skills"
    ),
    copy: bool = typer.Option(True, "--copy/--symlink", help="Copy instead of symlink"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing"),
):
    skill_sources = _skill_sources(experimental=experimental)
    if not skill_sources:
        typer.secho("no bundled skills found", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    if local:
        destinations = [_project_skill_destination(Path.cwd())]
    else:
        destinations = _agent_skill_destinations(agent)
        if not destinations:
            typer.secho(
                "no Claude Code or Codex config directory found; use "
                "`--agent claude`, `--agent codex`, `--agent both`, or `--local`",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=2)

    installed = 0
    for destination in destinations:
        count, messages = _install_skill_dirs(skill_sources, destination, copy=copy, force=force)
        installed += count
        for message in messages:
            typer.echo(message)

    if installed == 0:
        typer.echo("No skills installed.")
    else:
        typer.echo("\nAvailable as slash-commands in agents that read installed skills:")
        for skill_dir in skill_sources:
            typer.echo(f"  /{skill_dir.name}")


# ── Status + doctor (new) ──────────────────────────────────────────────────


@app.command(help="Show pipeline state: what's done, what's pending.")
def status(ctx: typer.Context):
    project = _require_project(ctx)
    cfg = project.config

    metadata = len(list(iter_metadata_paths(cfg)))
    converted = len(list(iter_markdown_paths(cfg)))
    extractions = len(list(iter_extraction_paths(cfg)))
    reasoning = len(list(iter_reasoning_paths(cfg)))
    annotations = len(list(iter_review_paths(cfg)))

    schema_yaml = extraction_schema_path(cfg)
    papers = _count_files(cfg.paper_inbox_dir, "*.pdf")

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
    typer.echo(f"inbox:       {papers} PDFs in {cfg.paper_inbox_dir.name}/")
    typer.echo(f"articles:    {metadata} metadata files")
    typer.echo(f"converted:   {converted} markdown files")
    typer.echo(f"extracted:   {extractions} extractions")
    typer.echo(f"reasoning:   {reasoning} reasoning files")
    typer.echo(f"annotations: {annotations}")
    if document_profile(cfg) == "journal_article":
        typer.echo("harvest:     run `litschema harvest` to fill bibliographic metadata by DOI")


@app.command(help="Diagnose configuration and dependency issues.")
def doctor(ctx: typer.Context):
    project = _require_project(ctx)
    cfg = project.config
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
    skills_dirs = _agent_skill_destinations("auto")
    installed = []
    for skills_dir in skills_dirs:
        if skills_dir.is_dir():
            installed.extend(p.name for p in skills_dir.iterdir() if (p / "SKILL.md").exists())
    if installed:
        typer.echo(f"{CHECK} global agent skills installed: {', '.join(sorted(set(installed)))}")
    else:
        typer.echo(f"{WARN} global agent skills not installed")
        issues.append("run `litschema skills install --agent claude` or `--agent codex`")

    agent_cli = shutil.which("claude") or shutil.which("codex")
    if agent_cli:
        typer.echo(f"{CHECK} agent CLI on PATH ({Path(agent_cli).name})")
    else:
        typer.echo(f"{WARN} no agent CLI on PATH — bundled skills need one to run")
        issues.append(
            "install an agentic CLI that reads installed skills (e.g. Claude Code or Codex)"
        )

    if issues:
        typer.echo("\nNext steps:")
        for issue in issues:
            typer.echo(f"  • {issue}")
        raise typer.Exit(code=1)
    typer.echo("\nEverything looks good.")


def _write_draft_schema(project: Path) -> None:
    domain_context = project.joinpath("domain_context.md")
    if not domain_context.exists():
        domain_context.write_text(
            "# Domain Context\n\n"
            "Describe the review question, inclusion boundaries, key concepts, "
            "and extraction guidance for agents.\n"
        )
    schema_path = project.joinpath("schema", "extraction.yaml")
    if not schema_path.exists():
        schema_path.write_text(
            "id: https://example.org/litschema/project\n"
            "name: draft_extraction\n"
            "description: Draft extraction schema. Revise for your review before extraction.\n"
            "prefixes:\n"
            "  draft: https://example.org/litschema/project/\n"
            "  linkml: https://w3id.org/linkml/\n"
            "default_prefix: draft\n"
            "default_range: string\n"
            "imports:\n"
            "  - linkml:types\n"
            "classes:\n"
            "  DraftExtraction:\n"
            "    tree_root: true\n"
            "    description: Draft structured extraction for one article.\n"
            "    attributes:\n"
            "      article_id:\n"
            "        identifier: true\n"
            "        required: true\n"
            "        description: Stable article identifier.\n"
        )


def _ensure_gitignore_entries(project: Path) -> None:
    gitignore_path = project / ".gitignore"
    entries = [
        ".venv/",
        ".litschema/",
        "papers-inbox/*.pdf",
        "papers-inbox/.processed/*.pdf",
        "data/papers/*/*.pdf",
        "# For non-open-access articles, add article-specific ignores such as:",
        "# data/papers/<article-id>/article.md",
        ".DS_Store",
    ]
    if not gitignore_path.exists():
        gitignore_path.write_text("\n".join(entries) + "\n")
        return

    existing = gitignore_path.read_text()
    existing_lines = set(existing.splitlines())
    missing = [entry for entry in entries if entry not in existing_lines]
    if missing:
        separator = "" if existing.endswith("\n") else "\n"
        gitignore_path.write_text(existing + separator + "\n".join(missing) + "\n")


# ── Init ───────────────────────────────────────────────────────────────────


@app.command(help="Scaffold a new litschema project.")
def init(
    domain: Path = typer.Argument(..., help="Project directory to create"),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Document profile: journal_article or generic (prompted if omitted)",
    ),
    no_skills: bool = typer.Option(
        False, "--no-skills", help="Skip installing agent skills into the project"
    ),
    force: bool = typer.Option(False, "--force", help="Allow initializing an existing directory"),
):
    if profile is None:
        typer.echo("What kind of documents is this project about?")
        typer.echo("  [1] Journal articles with DOIs   (bibliographic metadata auto-fetched)")
        typer.echo("  [2] Other documents              (reports, theses, policy PDFs, ...)")
        choice = typer.prompt("Choose 1 or 2", default="2").strip()
        profile = {"1": "journal_article", "2": "generic"}.get(choice, choice)
    if profile not in DOCUMENT_PROFILES:
        typer.secho(
            f"{CROSS} unknown profile {profile!r}; expected journal_article or generic",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)

    project = domain.expanduser().resolve()
    if project.exists() and not project.is_dir():
        typer.secho(f"{CROSS} {project} exists and is not a directory", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    if project.exists() and any(project.iterdir()) and not force:
        typer.secho(f"{CROSS} {project} already exists and is not empty", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    project.mkdir(parents=True, exist_ok=True)
    project.joinpath("schema").mkdir(exist_ok=True)
    project.joinpath("data", "papers").mkdir(parents=True, exist_ok=True)
    project.joinpath("papers-inbox").mkdir(exist_ok=True)

    config_path = project.joinpath("litschema.yaml")
    if not config_path.exists():
        config_path.write_text(
            'project_root: "."\n'
            'schema_dir: "schema"\n'
            'schema_root: "extraction.yaml"\n'
            'extraction_schema_file: "extraction.yaml"\n'
            'data_dir: "data"\n'
            'article_store_dir: "data/papers"\n'
            'paper_inbox_dir: "papers-inbox"\n'
            f'document_profile: "{profile}"\n'
        )
    _write_draft_schema(project)
    _ensure_gitignore_entries(project)

    if not no_skills:
        count, messages = _install_skill_dirs(
            _skill_sources(), _project_skill_destination(project), copy=True, force=False
        )
        for message in messages:
            typer.echo(message)
        if count:
            typer.echo(f"{CHECK} installed {count} agent skill(s) into .claude/skills/")

    typer.echo(f"{CHECK} initialized litschema project at {project}")
    typer.echo("\nNext steps:")
    typer.echo(f"  1. cd {project}")
    typer.echo("  2. Drop PDFs into papers-inbox/")
    if profile == "journal_article":
        typer.echo(
            "     (after extraction, `litschema harvest` fills bibliographic metadata by DOI)"
        )
    typer.echo("  3. Open this project in your agent (e.g. `claude`) and run /litschema-onboard")
    typer.echo("     — it drafts your schema with you, runs intake, and extracts your papers")
    typer.echo("  4. `litschema verify` any time to review what's been extracted")


if __name__ == "__main__":
    app()
