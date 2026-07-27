"""litschema CLI - single entry point for the pipeline.

Verbs: assemble / prepare-text / meta (show|set|sync) / validate / verify /
mcp / status / doctor / skills install / agent / init.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

import typer

from .articles import (
    article_files,
    iter_markdown_paths,
    iter_metadata_paths,
    iter_review_paths,
)
from .config import ConfigNotFoundError, LitSchemaConfig
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
    overwrite_hint: str = "use --force to overwrite",
) -> tuple[int, list[str]]:
    dest.mkdir(parents=True, exist_ok=True)
    installed = 0
    messages = []
    for skill_dir in skill_sources:
        target = dest / skill_dir.name
        if target.exists() or target.is_symlink():
            if not force:
                messages.append(f"{WARN} {target} already exists ({overwrite_hint})")
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
    if article_id is not None:
        from .articles import InvalidArticleIdError
        from .articles import article_files as _af

        try:
            _af(project.config, article_id)
        except InvalidArticleIdError:
            typer.secho(f"{CROSS} invalid article id: {article_id}", fg=typer.colors.RED)
            raise typer.Exit(code=2) from None
    from .ingest import pdf_to_markdown

    stats = pdf_to_markdown.run(
        project.config,
        article_ids=None if all_articles else [article_id],
        inbox_dir=inbox_dir,
        output_dir=output_dir,
        force=force,
    )
    typer.echo(json.dumps(stats, indent=2))


@app.command(help="Assemble article inputs from the PDF inbox.")
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


@app.command(
    help="Export the reviewed extractions — overrides applied, error markers "
    "skipped — as JSONL (default) or CSV, to stdout or --output."
)
def export(
    ctx: typer.Context,
    fmt: str = typer.Option("jsonl", "--format", "-f", help="jsonl | csv"),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Write to a file instead of stdout"
    ),
):
    from .export import FORMATS, export_records

    if fmt not in FORMATS:
        typer.secho(
            f"{CROSS} unknown format: {fmt!r} (expected {' | '.join(FORMATS)})",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)
    cfg = _require_project(ctx).config
    try:
        if output is not None:
            with output.open("w", newline="") as handle:
                count, with_overrides = export_records(cfg, fmt, handle)
        else:
            count, with_overrides = export_records(cfg, fmt, sys.stdout)
    except (FileNotFoundError, ValueError) as exc:
        typer.secho(f"{CROSS} {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=2) from exc
    typer.echo(
        f"{CHECK} exported {count} record(s) ({with_overrides} with review overrides)"
        + (f" → {output}" if output is not None else ""),
        err=True,
    )


# Docs serving is intentionally *not* a `litschema` CLI command — it's a
# repo-contributor concern, not a pipeline step. Run `make docs` for that.


# ── Skills subcommands ─────────────────────────────────────────────────────

skills_app = typer.Typer(help="Agentic skill management.", no_args_is_help=True)
app.add_typer(skills_app, name="skills")

agent_app = typer.Typer(
    help="Agent-facing helper commands used by bundled skills.", no_args_is_help=True
)
app.add_typer(agent_app, name="agent")

meta_app = typer.Typer(
    help="Read and write an article's source metadata (what the document IS).",
    no_args_is_help=True,
)
app.add_typer(meta_app, name="meta")

runs_app = typer.Typer(
    help="Inspect an article's extraction runs and choose the active one.",
    no_args_is_help=True,
)
app.add_typer(runs_app, name="runs")


def _require_article(cfg: LitSchemaConfig, article_id: str):
    from .articles import InvalidArticleIdError

    try:
        files = article_files(cfg, article_id)
    except InvalidArticleIdError:
        typer.secho(f"{CROSS} invalid article id: {article_id}", fg=typer.colors.RED)
        raise typer.Exit(code=2) from None
    if not files.metadata.exists():
        typer.secho(f"{CROSS} unknown article: {article_id}", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    return files


@runs_app.command("list", help="List an article's extraction runs, or every article's.")
def runs_list(
    ctx: typer.Context,
    article_id: str | None = typer.Argument(None, help="Article to list; omit for all"),
):
    project = _require_project(ctx)
    cfg = project.config
    from .articles import iter_metadata_paths
    from .runs import BrokenActiveRunError, active_run_id, iter_run_ids, run_files, run_summary

    if article_id is not None:
        article_ids = [_require_article(cfg, article_id).article_id]
    else:
        article_ids = [path.parent.name for path in iter_metadata_paths(cfg)]

    total = 0
    for current_id in article_ids:
        files = article_files(cfg, current_id)
        run_ids = iter_run_ids(files)
        if not run_ids:
            if article_id is not None:
                typer.echo(f"{current_id}: no published runs")
            continue
        try:
            selected = active_run_id(files)
        except BrokenActiveRunError:
            selected = None
            typer.secho(f"{CROSS} {current_id}: broken active-run pointer", fg=typer.colors.RED)
        typer.echo(current_id)
        for run_id in run_ids:
            total += 1
            info = run_summary(run_files(files, run_id), active_run_id=selected)
            marks = []
            if info["active"]:
                marks.append("active")
            if info["error"]:
                marks.append("error")
            if info["reviewed"]:
                marks.append("reviewed")
            flags = f"  [{', '.join(marks)}]" if marks else ""
            created = info["created_at"] or "?"
            model = info["model"] or "unknown model"
            schema = (info["schema_hash"] or "sha256:?")[:14]
            typer.echo(f"  {run_id}  {created}  {model}  {schema}…{flags}")
    if article_id is None and total == 0:
        typer.echo("no published runs")


@runs_app.command("activate", help="Select a published run as the article's active run.")
def runs_activate(
    ctx: typer.Context,
    article_id: str = typer.Argument(..., help="Article whose active run to change"),
    run_id: str = typer.Argument(..., help="Run to activate"),
):
    project = _require_project(ctx)
    files = _require_article(project.config, article_id)
    from .runs import RunActivationError, activate_run

    try:
        activate_run(files, run_id)
    except RunActivationError as exc:
        typer.secho(f"{CROSS} {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None
    typer.echo(f"{CHECK} {article_id} now active: {run_id}")


@meta_app.command("show", help="Print the article's source-metadata block as JSON.")
def meta_show(ctx: typer.Context, article_id: str):
    from .source_metadata import read_source_metadata

    cfg = _require_project(ctx).config
    files = _require_article(cfg, article_id)
    typer.echo(
        json.dumps(read_source_metadata(files.read_metadata()), indent=2, ensure_ascii=False)
    )


@meta_app.command(
    "set",
    help="Merge fields into the source-metadata block. Provenance is caller-asserted: "
    "--source auto for machine-inferred values (agents, scripts), --source manual for "
    "human-authored values. An explicit empty-string value clears a field. The doi "
    "state is earned via `meta sync` (or `meta set --doi ... --sync`), never asserted.",
)
def meta_set(
    ctx: typer.Context,
    article_id: str,
    source: str = typer.Option(
        ..., "--source", help="Who authored the VALUES: auto (machine) or manual (human)"
    ),
    title: str | None = typer.Option(None, "--title"),
    authors: str | None = typer.Option(
        None, "--authors", help='Comma-separated display names: "Jane Smith, Mo Doe"'
    ),
    corporate_author: str | None = typer.Option(None, "--corporate-author"),
    year: int | None = typer.Option(None, "--year"),
    journal: str | None = typer.Option(None, "--journal"),
    doi: str | None = typer.Option(None, "--doi"),
    publisher: str | None = typer.Option(None, "--publisher"),
    url: str | None = typer.Option(None, "--url"),
    abstract: str | None = typer.Option(None, "--abstract"),
    clear: list[str] = typer.Option(
        [], "--clear", help="Remove a field from the block (repeatable)"
    ),
    sync: bool = typer.Option(
        False,
        "--sync",
        help="After recording the DOI, fetch registry metadata and lock the block. "
        "Takes ONLY --doi — registry values replace the whole block, so fallback "
        "values belong in a separate `meta set`.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Let an auto write overwrite manual/doi metadata"
    ),
):
    from .source_metadata import (
        SOURCE_FIELDS,
        can_overwrite,
        read_source_metadata,
        update_source_metadata,
    )

    if source not in ("auto", "manual"):
        typer.secho(
            f"{CROSS} --source must be auto or manual "
            "(doi is earned via `meta sync` or `meta set --doi ... --sync`)",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)
    if sync:
        others = (title, authors, corporate_author, year, journal, publisher, url, abstract)
        if not doi or any(v is not None for v in others) or clear:
            typer.secho(
                f"{CROSS} --sync requires --doi with a value and takes no other field "
                "options — registry values replace the whole block, so fallback values "
                "belong in a separate `meta set`",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=2)
    cfg = _require_project(ctx).config
    files = _require_article(cfg, article_id)

    values = (title, authors, corporate_author, year, journal, doi, publisher, url, abstract)
    fields: dict = {}
    for key, value in zip(SOURCE_FIELDS, values, strict=True):
        if value is None:
            continue
        # An explicit empty string clears the field (the webapp's convention).
        fields[key] = None if value == "" else value
    if isinstance(fields.get("authors"), str):
        fields["authors"] = [
            n.strip() for n in fields["authors"].split(",") if n.strip()
        ] or None
    if fields.get("doi") is not None:
        from .article_registry import is_valid_doi, normalize_doi

        normalized_doi = normalize_doi(str(fields["doi"]))
        if not is_valid_doi(normalized_doi):
            typer.secho(f"{CROSS} not a valid DOI: {fields['doi']}", fg=typer.colors.RED)
            raise typer.Exit(code=2)
        fields["doi"] = normalized_doi
    for field in clear:
        if field not in SOURCE_FIELDS:
            typer.secho(f"{CROSS} unknown field: {field}", fg=typer.colors.RED)
            raise typer.Exit(code=2)
        if fields.get(field) is not None:
            typer.secho(
                f"{CROSS} --clear {field} conflicts with the value passed for it",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=2)
        fields[field] = None
    if not fields:
        typer.secho(f"{CROSS} nothing to change (pass field options or --clear)", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    existing = read_source_metadata(files.read_metadata()).get("metadata_source")
    if not force and not can_overwrite(existing, source):
        typer.secho(
            f"{CROSS} refusing: metadata is {existing!r} and auto writes never overwrite "
            "human or registry data — this is expected for machine callers; a human who "
            "wants to override can pass --force",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    block = update_source_metadata(files, fields, source=source)
    if not sync:
        typer.echo(json.dumps(block, indent=2, ensure_ascii=False))
        return

    # --sync: attempt the registry upgrade the write just made possible. The
    # guard above already ruled on consent — a refused write never gets here.
    from .ingest import openalex_harvest

    # The batch sweep never touches manual blocks, so only promise it for auto.
    retry_via = f"`meta sync {article_id}`" + (" or the --all sweep" if source == "auto" else "")
    retry_hint = f"the DOI is recorded ({source}) and stays retryable via {retry_via}"
    try:
        synced = openalex_harvest.sync_article(cfg, article_id)
    except LookupError as exc:
        # Unreachable unless the manifest changed under us mid-command.
        typer.secho(f"{CROSS} {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    except openalex_harvest.RegistryUnavailableError:
        typer.echo(json.dumps(block, indent=2, ensure_ascii=False))
        typer.secho(
            f"{WARN} NOT locked — DOI registry unavailable; {retry_hint}",
            fg=typer.colors.YELLOW,
        )
        return
    if synced is None:
        typer.echo(json.dumps(block, indent=2, ensure_ascii=False))
        typer.secho(
            f"{WARN} NOT locked — the registry has no usable record for this DOI; "
            f"{retry_hint}",
            fg=typer.colors.YELLOW,
        )
        return
    typer.echo(json.dumps(synced, indent=2, ensure_ascii=False))
    typer.echo(f"{CHECK} synced from registry — metadata locked (was {source})")


@meta_app.command(
    "sync",
    help="Fetch metadata from the DOI registry and lock the block (overwrites any state — "
    "invoking this IS the consent). Use --all for the batch sweep, which enriches "
    "machine-seeded records and never touches manual ones.",
)
def meta_sync(
    ctx: typer.Context,
    article_id: str | None = typer.Argument(None),
    doi: str | None = typer.Option(
        None, "--doi", help="Record this DOI on the article first, then sync from it"
    ),
    all_articles: bool = typer.Option(
        False, "--all", help="Enrich every assembled article that has a DOI"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="With --all: re-fetch even when a cached response exists"
    ),
    email: str | None = typer.Option(None, "--email", help="Email for the OpenAlex polite pool"),
):
    from .article_registry import is_valid_doi, normalize_doi
    from .ingest import openalex_harvest

    cfg = _require_project(ctx).config
    if all_articles:
        if article_id or doi:
            typer.secho(f"{CROSS} --all takes no article id or --doi", fg=typer.colors.RED)
            raise typer.Exit(code=2)
        stats = openalex_harvest.harvest(cfg, email=email, skip_existing=not refresh)
        typer.echo(json.dumps(stats, indent=2))
        return
    if refresh:
        typer.secho(f"{CROSS} --refresh requires --all", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    if not article_id:
        typer.secho(f"{CROSS} provide an article id, or --all", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    _require_article(cfg, article_id)
    normalized = None
    if doi:
        normalized = normalize_doi(doi)
        if not is_valid_doi(normalized):
            typer.secho(f"{CROSS} not a valid DOI: {doi}", fg=typer.colors.RED)
            raise typer.Exit(code=2)
    try:
        block = openalex_harvest.sync_article(cfg, article_id, doi=normalized, email=email)
    except LookupError as exc:
        typer.secho(f"{CROSS} {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    except openalex_harvest.RegistryUnavailableError:
        typer.secho(
            f"{CROSS} DOI registry unavailable — try again later; nothing was recorded",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1) from None
    if block is None:
        typer.secho(
            f"{CROSS} the registry has no usable record for this DOI; nothing was recorded"
            + (
                f" (use `litschema meta set {article_id} --source manual --doi {normalized}`"
                " to keep the DOI anyway)"
                if normalized
                else ""
            ),
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    typer.echo(json.dumps(block, indent=2, ensure_ascii=False))


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
    "record-extraction",
    help="Publish the staged extraction as an immutable run and activate it.",
)
def agent_record_extraction(
    ctx: typer.Context,
    article_id: str = typer.Argument(..., help="Article identifier that was extracted"),
    provider: str | None = typer.Option(None, "--provider", help="Extraction provider, if known"),
    model: str | None = typer.Option(None, "--model", help="Extraction model, if known"),
    skill_file: Path | None = typer.Option(
        None, "--skill-file", help="Override the conducting skill file to hash"
    ),
):
    project = _require_project(ctx)
    cfg = project.config
    from .articles import InvalidArticleIdError
    from .ingest import validate_extraction as _validate_extraction
    from .runs import RunPublishError, publish_run
    from .schema_resolution import resolve_extraction_schema as _resolve_schema

    try:
        files = article_files(cfg, article_id)
    except InvalidArticleIdError:
        typer.secho(f"{CROSS} invalid article id: {article_id}", fg=typer.colors.RED)
        raise typer.Exit(code=2) from None
    if not files.article_dir.is_dir():
        typer.secho(f"{CROSS} unknown article: {article_id}", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    if not files.staged_extraction.is_file():
        typer.secho(
            f"{CROSS} no staged extraction at {files.staged_extraction}", fg=typer.colors.RED
        )
        raise typer.Exit(code=1)

    # The deterministic publication gate: both artifacts must validate before
    # anything is written to the run layout (error markers are legal artifacts
    # but skip schema validation and never activate).
    resolved = _resolve_schema(cfg)
    valid, errors = _validate_extraction.validate_file(
        files.staged_extraction, resolved.path, resolved.root_class
    )
    if not valid:
        typer.secho(f"{CROSS} staged extraction is invalid:", fg=typer.colors.RED)
        for err in errors[:10]:
            typer.echo(f"  {err}")
        raise typer.Exit(code=1)
    if files.staged_reasoning.is_file():
        from .agent import validate_reasoning as _validate_reasoning

        if _validate_reasoning.run([str(files.staged_reasoning)]) != 0:
            typer.secho(f"{CROSS} staged reasoning is invalid", fg=typer.colors.RED)
            raise typer.Exit(code=1)

    try:
        run, activated = publish_run(
            cfg,
            files,
            provider=provider,
            model=model,
            skill_file=skill_file,
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
    except RunPublishError as exc:
        typer.secho(f"{CROSS} {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None
    state = "activated" if activated else "published inactive (error marker)"
    typer.echo(f"{CHECK} published run {run.run_id} for {article_id} — {state}")


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

    from .runs import BrokenActiveRunError, active_run, iter_run_ids
    from .schema_resolution import schema_hash as _schema_hash

    metadata = len(list(iter_metadata_paths(cfg)))
    converted = len(list(iter_markdown_paths(cfg)))
    annotations = len(list(iter_review_paths(cfg)))

    live_runs = 0
    active_runs = 0
    current_schema_active = 0
    broken_pointers = 0
    try:
        current_hash = _schema_hash(cfg)
    except OSError:
        current_hash = None
    for metadata_path in iter_metadata_paths(cfg):
        files = article_files(cfg, metadata_path.parent.name)
        live_runs += len(iter_run_ids(files))
        try:
            run = active_run(files)
        except BrokenActiveRunError:
            broken_pointers += 1
            continue
        if run is None:
            continue
        active_runs += 1
        try:
            if current_hash and run.read_run_json().get("schema_hash") == current_hash:
                current_schema_active += 1
        except (OSError, json.JSONDecodeError):
            pass

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
    typer.echo(f"runs:        {live_runs} published")
    typer.echo(f"active:      {active_runs} articles with an active run")
    typer.echo(f"current:     {current_schema_active} active runs on the current schema")
    if broken_pointers:
        typer.echo(f"{CROSS} broken:      {broken_pointers} broken active-run pointers")
    typer.echo(f"annotations: {annotations}")


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

    # CLI resolution — mirrors the agent skills' resolution order:
    # .litschema/dev-cli override, then `uv run litschema`, then bare `litschema`.
    dev_cli = cfg.project_root / ".litschema" / "dev-cli"
    legacy_dev_cli = cfg.project_root / ".litschema" / "cli"
    if dev_cli.is_file():
        override = dev_cli.read_text().strip()
        typer.echo(f"{CHECK} CLI dev override (.litschema/dev-cli): {override}")
        # Agents run this file, so it needs the user's approval, recorded as a
        # hash they can verify rather than a claim passed to them in a prompt.
        approved_file = cfg.project_root / ".litschema" / "dev-cli-approved"
        current = hashlib.sha256(dev_cli.read_bytes()).hexdigest()
        approved = approved_file.read_text().strip() if approved_file.is_file() else None
        if approved == current:
            typer.echo(f"{CHECK} dev override approved for agent use")
        else:
            detail = "changed since approval" if approved else "not yet approved"
            typer.echo(f"{WARN} dev override {detail} — agents will stop and ask before using it")
            issues.append(
                "approve the dev override so agents can use it without asking per run: "
                "`shasum -a 256 .litschema/dev-cli | cut -d' ' -f1 "
                "> .litschema/dev-cli-approved`"
            )
    elif legacy_dev_cli.is_file():
        typer.echo(f"{WARN} legacy .litschema/cli found — agent skills now read .litschema/dev-cli")
        issues.append("rename .litschema/cli to .litschema/dev-cli")
    elif (cfg.project_root / "pyproject.toml").is_file():
        typer.echo(f"{CHECK} agent skills will resolve the CLI via `uv run litschema`")
    elif _bare_cli_on_path():
        typer.echo(f"{CHECK} litschema on PATH — agent skills will use the bare CLI")
    else:
        checkout = _dev_checkout_root()
        hint = (
            f"uv run --project {checkout} litschema"
            if checkout
            else "uv run --project <path-to-litschema-checkout> litschema"
        )
        typer.echo(f"{WARN} agent skills cannot resolve the litschema CLI in this project")
        issues.append(
            "write the CLI command to .litschema/dev-cli, e.g. "
            f"`mkdir -p .litschema && echo '{hint}' > .litschema/dev-cli`"
        )

    typer.echo(f"{CHECK} litschema.yaml at {cfg.config_path}")

    if cfg.schema_dir.is_dir():
        typer.echo(f"{CHECK} schema dir: {cfg.schema_dir}")
    else:
        typer.echo(f"{CROSS} schema dir missing: {cfg.schema_dir}")
        issues.append(f"create {cfg.schema_dir}")

    # Skills check — project-local .claude/skills/ is the init default;
    # global installs are the alternative. Only litschema's bundled skills
    # count: unrelated skills living in the same directories are not a green
    # light for this project.
    bundled = {skill.name for skill in _skill_sources()}

    def _bundled_in(directory: Path) -> list[str]:
        if not directory.is_dir():
            return []
        return [
            p.name
            for p in directory.iterdir()
            if p.is_dir() and p.name in bundled and (p / "SKILL.md").exists()
        ]

    installed = _bundled_in(cfg.project_root / ".claude" / "skills")
    where = "project-local"
    if not installed:
        where = "global"
        for skills_dir in _agent_skill_destinations("auto"):
            installed.extend(_bundled_in(skills_dir))
    if installed:
        typer.echo(
            f"{CHECK} litschema agent skills installed ({where}): "
            f"{', '.join(sorted(set(installed)))}"
        )
    else:
        typer.echo(
            f"{WARN} litschema agent skills not installed "
            "(looked in ./.claude/skills and the global skill dirs)"
        )
        issues.append(
            "run `litschema skills install --local` from the project "
            "(or `litschema skills install` for a global install)"
        )

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


def _bare_cli_on_path() -> bool:
    """True when `litschema` on PATH would survive outside this process.

    Under `uv run --project <checkout>`, the checkout venv's bin dir is
    prepended to PATH, so which() finds a `litschema` that a fresh shell
    (the shell an agent skill runs in) would not. Ignore hits inside this
    process's own environment prefix.
    """
    found = shutil.which("litschema")
    if not found:
        return False
    try:
        return not Path(found).resolve().is_relative_to(Path(sys.prefix).resolve())
    except OSError:
        return True


def _dev_checkout_root() -> Path | None:
    """Best-effort root of the litschema source checkout this process runs from.

    Walks up from the installed package looking for a pyproject.toml that
    declares the litschema project. Returns None for site-packages installs,
    where no checkout exists to point at.
    """
    package_dir = Path(__file__).resolve().parent
    for candidate in package_dir.parents:
        pyproject = candidate / "pyproject.toml"
        if pyproject.is_file():
            try:
                if 'name = "litschema"' in pyproject.read_text():
                    return candidate
            except OSError:
                pass
    return None


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
    no_skills: bool = typer.Option(
        False, "--no-skills", help="Skip installing agent skills into the project"
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Initialize into a non-empty directory (refused if it is already a litschema project)",
    ),
):
    project = domain.expanduser().resolve()
    if project.exists() and not project.is_dir():
        typer.secho(f"{CROSS} {project} exists and is not a directory", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    config_path = project.joinpath("litschema.yaml")
    # is_symlink() catches dangling symlinks, which exists() follows and misses.
    if config_path.exists() or config_path.is_symlink():
        typer.secho(
            f"{CROSS} {project} is already a litschema project (litschema.yaml exists) — "
            "edit litschema.yaml directly, or run "
            "'litschema skills install --local --force' from inside the project "
            "to refresh skills",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)
    if project.exists() and any(project.iterdir()) and not force:
        typer.secho(
            f"{CROSS} {project} already exists and is not empty "
            "(pass --force to initialize here anyway; existing files are never overwritten)",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)
    # Scaffolding must never write through a symlink to somewhere outside the
    # project (a symlinked .gitignore in a dotfiles setup, a dangling link).
    for entry in (
        "domain_context.md",
        ".gitignore",
        "schema",
        "schema/extraction.yaml",
        "data",
        "data/papers",
        "papers-inbox",
    ):
        if project.joinpath(entry).is_symlink():
            typer.secho(
                f"{CROSS} {project / entry} is a symlink — init only writes real files "
                "and directories inside the project",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=2)

    project.mkdir(parents=True, exist_ok=True)
    project.joinpath("schema").mkdir(exist_ok=True)
    project.joinpath("data", "papers").mkdir(parents=True, exist_ok=True)
    project.joinpath("papers-inbox").mkdir(exist_ok=True)

    # The config cannot exist here — init refuses existing projects above.
    config_path.write_text(
        'project_root: "."\n'
        'schema_dir: "schema"\n'
        'extraction_schema_file: "extraction.yaml"\n'
        'data_dir: "data"\n'
        'article_store_dir: "data/papers"\n'
        'paper_inbox_dir: "papers-inbox"\n'
    )
    _write_draft_schema(project)
    _ensure_gitignore_entries(project)

    if not no_skills:
        count, messages = _install_skill_dirs(
            _skill_sources(),
            _project_skill_destination(project),
            copy=True,
            force=False,
            overwrite_hint="run 'litschema skills install --local --force' "
            "from inside the project to replace",
        )
        for message in messages:
            typer.echo(message)
        if count:
            typer.echo(f"{CHECK} installed {count} agent skill(s) into .claude/skills/")

    onboard_available = (
        _project_skill_destination(project).joinpath("litschema-onboard", "SKILL.md").exists()
    )
    typer.echo(f"{CHECK} initialized litschema project at {project}")
    typer.echo("\nNext steps:")
    typer.echo(f"  1. cd {project}")
    typer.echo("  2. Drop PDFs into papers-inbox/")
    typer.echo(
        "     (documents with DOIs get bibliographic metadata synced automatically"
        " during onboarding)"
    )
    if onboard_available:
        typer.echo(
            "  3. Open this project in your agent (e.g. `claude`) and run /litschema-onboard"
        )
        typer.echo("     — it drafts your schema with you, runs intake, and extracts your papers")
    else:
        typer.echo(
            "  3. Install agent skills (`litschema skills install --local` from the project),"
        )
        typer.echo("     then open the project in your agent and run /litschema-onboard")
    typer.echo("  4. `litschema verify` any time to review what's been extracted")


if __name__ == "__main__":
    app()
