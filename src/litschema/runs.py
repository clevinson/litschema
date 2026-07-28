"""Immutable extraction runs: layout, publish-activates, resolution.

  data/papers/<id>/extraction-runs/<run-id>/agent-extraction.json
  data/papers/<id>/extraction-runs/<run-id>/agent-reasoning.json
  data/papers/<id>/extraction-runs/<run-id>/run.json
  data/papers/<id>/active-run.json

A run directory is a complete, published extraction attempt; its extraction,
reasoning, and run.json never change after publication. The only activation is
the publisher's: publishing a complete non-error run atomically activates it
(`specs/article-store/spec.md`).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .articles import ArticleFiles
from .config import LitSchemaConfig
from .schema_resolution import schema_hash

logger = logging.getLogger(__name__)

RUN_JSON_VERSION = 1
ACTIVE_RUN_FILENAME = "active-run.json"
RUNS_DIRNAME = "extraction-runs"

# Crockford base32, per ULID: time-ordered on generation, but consumers must
# treat run IDs as opaque (the spec forbids deriving meaning from the text).
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class RunPublishError(Exception):
    """A run could not be published; nothing was written to the run layout."""


class BrokenActiveRunError(Exception):
    """active-run.json names a run that does not exist or is unreadable."""


def is_error_marker(data: object) -> bool:
    """True when an extraction payload is an error marker rather than data.

    Recognised by structure — ``error: true`` plus a nonempty ``reason`` — not
    by the truthiness of an ``error`` key. This is a scientific extraction
    tool, and `error` is an ordinary slot name in that domain (measurement
    error, standard error): a truthiness test would let a real extraction skip
    schema validation and publish inactive whenever that value was non-zero.

    A marker carries nothing but the marker: `article_id`, `error: true`, and a
    nonempty `reason`. Accepting any object that merely *contains* those would
    let real extraction data — which may legitimately have an `error` slot —
    skip schema validation and publish inactive, which is the same failure the
    truthiness test caused, only rarer and so harder to notice.

    Every consumer must share this predicate. Three independent copies of the
    test are how validation and publication came to disagree about what a
    marker is.
    """
    if not isinstance(data, dict):
        return False
    if data.get("error") is not True:
        return False
    if not isinstance(data.get("reason"), str) or not data["reason"].strip():
        return False
    # Exactly the marker keys, and an `article_id` that actually identifies
    # something: the contract's shape is
    # `{"article_id": ..., "error": true, "reason": ...}`, and a marker whose
    # id is null, empty, or not a string names no document, so nothing
    # downstream can say which one failed.
    if set(data) != {"article_id", "error", "reason"}:
        return False
    article_id = data["article_id"]
    return isinstance(article_id, str) and bool(article_id.strip())


def new_run_id() -> str:
    """A 26-char ULID: 48-bit ms timestamp + 80 bits of randomness."""
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


@dataclass(frozen=True)
class RunFiles:
    article: ArticleFiles
    run_id: str

    @property
    def run_dir(self) -> Path:
        return self.article.runs_dir / self.run_id

    @property
    def extraction(self) -> Path:
        return self.run_dir / "agent-extraction.json"

    @property
    def reasoning(self) -> Path:
        return self.run_dir / "agent-reasoning.json"

    @property
    def run_json(self) -> Path:
        return self.run_dir / "run.json"

    @property
    def review(self) -> Path:
        return self.run_dir / "review.json"

    def read_run_json(self) -> dict:
        return json.loads(self.run_json.read_text())


def run_files(files: ArticleFiles, run_id: str) -> RunFiles:
    # Same chokepoint rule as article ids: run ids arrive from pointers and
    # URL segments and must never traverse outside the runs directory.
    if not run_id or run_id in {".", ".."} or "/" in run_id or "\\" in run_id:
        raise BrokenActiveRunError(f"invalid run id: {run_id!r}")
    return RunFiles(article=files, run_id=run_id)


def iter_run_ids(files: ArticleFiles) -> list[str]:
    """Every published run id for this article. A run dir has a run.json."""
    if not files.runs_dir.is_dir():
        return []
    return sorted(
        entry.name
        for entry in files.runs_dir.iterdir()
        if entry.is_dir() and (entry / "run.json").is_file()
    )


def active_run_id(files: ArticleFiles) -> str | None:
    """The active run id, or None when the article has no active extraction."""
    pointer = files.active_run_file
    if not pointer.is_file():
        return None
    try:
        run_id = json.loads(pointer.read_text())["run_id"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise BrokenActiveRunError(f"{pointer} is unreadable") from exc
    if not isinstance(run_id, str) or not run_id:
        raise BrokenActiveRunError(f"{pointer} names no run")
    return run_id


def active_run(files: ArticleFiles) -> RunFiles | None:
    """Resolve the active run. None means unextracted; a broken pointer raises."""
    run_id = active_run_id(files)
    if run_id is None:
        return None
    run = run_files(files, run_id)
    if not run.run_json.is_file() or not run.extraction.is_file():
        raise BrokenActiveRunError(
            f"active-run.json for {files.article_id} names {run_id}, which is not a published run"
        )
    return run


def _write_active_pointer(files: ArticleFiles, run_id: str) -> None:
    # Unique temp name per write, in the same directory so the replace stays
    # atomic. A shared `.json.tmp` let two concurrent publishers overwrite each
    # other's staging file, after which the losing one could tear down a run the
    # pointer had already been moved to.
    tmp = files.active_run_file.with_suffix(f".json.tmp.{os.getpid()}.{run_id}")
    tmp.write_text(json.dumps({"run_id": run_id}) + "\n")
    try:
        os.replace(tmp, files.active_run_file)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


class RunActivationError(Exception):
    """A run could not be activated; the active pointer is unchanged."""


def is_error_run(run: RunFiles) -> bool:
    """True when the run's extraction is an error marker rather than data."""
    try:
        data = json.loads(run.extraction.read_text())
    except (OSError, ValueError):
        # ValueError covers both a JSON syntax error and undecodable bytes;
        # either way the payload is not usable data.
        return True
    return is_error_marker(data)


def activate_run(files: ArticleFiles, run_id: str) -> None:
    """Select a published, complete, non-error run as the article's active run.

    Activation changes only the pointer; neither run is mutated. Selecting the
    already-active run is a no-op rather than an error.
    """
    try:
        run = run_files(files, run_id)
    except BrokenActiveRunError as exc:
        raise RunActivationError(str(exc)) from None
    if not run.run_json.is_file() or not run.extraction.is_file():
        raise RunActivationError(f"{run_id} is not a published run of {files.article_id}")
    if is_error_run(run):
        raise RunActivationError(f"{run_id} is an error-marker run and cannot be activated")

    # Activation is what every consumer reads through, so check the run holds
    # what they need rather than trusting that publication left it complete —
    # a run directory can be edited by hand between the two.
    try:
        record = run.read_run_json()
    except (OSError, ValueError) as exc:
        raise RunActivationError(f"{run_id} has an unreadable run.json: {exc}") from None
    if not isinstance(record, dict):
        raise RunActivationError(f"{run_id} has a run.json that is not an object")
    if record.get("article_id") not in (None, files.article_id):
        raise RunActivationError(
            f"{run_id} records article {record['article_id']!r}, not {files.article_id!r}"
        )
    try:
        extraction = json.loads(run.extraction.read_text())
    except (OSError, ValueError) as exc:
        raise RunActivationError(f"{run_id} has an unreadable extraction: {exc}") from None
    if not isinstance(extraction, dict):
        raise RunActivationError(f"{run_id} has an extraction that is not an object")
    if not run.reasoning.is_file():
        raise RunActivationError(
            f"{run_id} has no agent-reasoning.json; the verifier needs it to show evidence"
        )
    try:
        reasoning = json.loads(run.reasoning.read_text())
    except (OSError, ValueError) as exc:
        raise RunActivationError(f"{run_id} has unreadable reasoning: {exc}") from None
    if not isinstance(reasoning, dict) or not isinstance(reasoning.get("fields"), list):
        raise RunActivationError(
            f"{run_id} has reasoning with no usable fields list; the verifier reads it "
            f"on every document load"
        )
    # Every entry must carry a string `path`: the verifier calls
    # `entry.path.startsWith(...)` on each one, so a single malformed entry
    # breaks every document load for this article.
    if not all(
        isinstance(entry, dict) and isinstance(entry.get("path"), str)
        for entry in reasoning["fields"]
    ):
        raise RunActivationError(
            f"{run_id} has reasoning entries without a string `path`"
        )

    _write_active_pointer(files, run.run_id)


def run_summary(run: RunFiles, *, active_run_id: str | None) -> dict:
    """Display fields for `runs list`, tolerant of an unreadable run.json.

    Tolerant means every damaged shape, not just the two that were obvious:
    `runs list` is the command you reach for to find out *which* run is broken,
    so one bad record must not take down the listing. `ValueError` covers both
    a JSON syntax error and undecodable bytes, and both the record and its
    `agent` are normalized to dicts — valid JSON that is not an object parses
    fine and then fails on `.get()`.
    """
    try:
        record = run.read_run_json()
    except (OSError, ValueError):
        record = {}
    if not isinstance(record, dict):
        record = {}
    agent = record.get("agent")
    if not isinstance(agent, dict):
        agent = {}

    def text(value):
        """Displayed fields are rendered and sliced, so they must be strings.

        Normalizing only the containers was not enough: a numeric non-empty
        `schema_hash` survived to `[:14]` in the CLI and raised TypeError,
        taking down the listing that exists to find the damaged run.
        """
        return value if isinstance(value, str) else None

    return {
        "run_id": run.run_id,
        "active": run.run_id == active_run_id,
        "error": is_error_run(run),
        "created_at": text(record.get("created_at")),
        "schema_hash": text(record.get("schema_hash")),
        "model": text(agent.get("model")),
        "reviewed": run.review.is_file(),
    }


def _hash_file(path: Path, what: str) -> str:
    import hashlib

    try:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise RunPublishError(f"cannot hash {what} ({path}): {exc}") from exc


def _agent_attribution(provider: str | None, model: str | None) -> dict:
    """Attribution is recorded as asserted; unavailable fields are omitted.

    harness/harness_version come from the AI_AGENT env var an agent CLI sets
    (e.g. ``claude-code_2-1-219_agent``); effort from CLAUDE_EFFORT. The
    publisher runs inside the agent's shell, so these are genuinely observed
    even though provider/model are only declared.
    """
    agent: dict = {}
    raw = os.environ.get("AI_AGENT", "")
    if raw:
        parts = raw.rsplit("_", 1)[0]  # drop trailing "_agent"
        harness, _, version = parts.partition("_")
        if harness:
            agent["harness"] = harness
        if version:
            agent["harness_version"] = version.replace("-", ".")
    if provider:
        agent["provider"] = provider
    if model:
        agent["model"] = model
    effort = os.environ.get("CLAUDE_EFFORT")
    if effort:
        agent["effort"] = effort
    return agent


def resolve_skill_file(cfg: LitSchemaConfig, override: Path | None = None) -> Path:
    """The SKILL.md that conducted the extraction: explicit, project, then global."""
    if override is not None:
        if not override.is_file():
            raise RunPublishError(f"skill file not found: {override}")
        return override
    candidates = [
        cfg.project_root / ".claude" / "skills" / "extract-article" / "SKILL.md",
        Path.home() / ".claude" / "skills" / "extract-article" / "SKILL.md",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RunPublishError(
        "cannot resolve the conducting skill file; pass --skill-file "
        "(looked for .claude/skills/extract-article/SKILL.md in the project and home)"
    )


def publish_run(
    cfg: LitSchemaConfig,
    files: ArticleFiles,
    *,
    provider: str | None = None,
    model: str | None = None,
    skill_file: Path | None = None,
    created_at: str,
) -> tuple[RunFiles, bool]:
    """Publish the staged article-root artifacts as an immutable run.

    Reads ``agent-extraction.json`` (and ``agent-reasoning.json`` when present)
    from the article root, computes the reproduction hashes, stages the run
    outside its final path, renames it into place atomically, and — for a
    complete non-error run — activates it. Staged article-root files are
    consumed (removed) on success.

    Returns ``(run, activated)``.
    """
    staged_extraction = files.staged_extraction
    if not staged_extraction.is_file():
        raise RunPublishError(f"no staged extraction at {staged_extraction}")
    try:
        extraction_data = json.loads(staged_extraction.read_text())
    except ValueError as exc:
        raise RunPublishError(f"staged extraction is not valid JSON: {exc}") from exc
    if not isinstance(extraction_data, dict):
        raise RunPublishError(
            f"staged extraction must be a JSON object, not "
            f"{type(extraction_data).__name__}: {staged_extraction}"
        )
    error_marker = is_error_marker(extraction_data)
    if error_marker and extraction_data.get("article_id") != files.article_id:
        raise RunPublishError(
            f"the staged error marker names article "
            f"{extraction_data['article_id']!r}, not {files.article_id!r}"
        )

    staged_reasoning = files.staged_reasoning
    if not error_marker and not staged_reasoning.is_file():
        raise RunPublishError(f"no staged reasoning at {staged_reasoning}")

    # Reproduction: the publisher hashes every input itself; failure to hash
    # any of them refuses publication. Attribution never blocks it.
    inputs = {
        "prepared_text": _hash_file(files.markdown, "prepared text"),
        "domain_context": _hash_file(cfg.project_root / "domain_context.md", "domain context"),
        "skill": _hash_file(resolve_skill_file(cfg, skill_file), "skill"),
    }
    record = {
        "version": RUN_JSON_VERSION,
        "run_id": new_run_id(),
        "article_id": files.article_id,
        "created_at": created_at,
        "schema_hash": schema_hash(cfg),
        "inputs": inputs,
        "agent": _agent_attribution(provider, model),
    }

    run = RunFiles(article=files, run_id=record["run_id"])
    staging = files.runs_dir / f".staging-{record['run_id']}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copy2(staged_extraction, staging / "agent-extraction.json")
        if staged_reasoning.is_file():
            shutil.copy2(staged_reasoning, staging / "agent-reasoning.json")
        (staging / "run.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        os.replace(staging, run.run_dir)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    activated = not error_marker
    if activated:
        # Roll the run directory back if activation fails. Leaving a complete
        # but inactive run behind reports failure while the store says an
        # extraction happened, and a retry would publish a second copy of it.
        try:
            _write_active_pointer(files, run.run_id)
        except OSError:
            shutil.rmtree(run.run_dir, ignore_errors=True)
            raise

    # Past this point the run is published and active: the command has already
    # succeeded. Clearing the staging files is tidying, so a failure here must
    # not turn a successful publication into a reported failure — which would
    # invite a retry that publishes the same extraction twice.
    for staged in (staged_extraction, staged_reasoning):
        try:
            staged.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("published run %s but could not remove %s: %s", run.run_id, staged, exc)
    return run, activated
