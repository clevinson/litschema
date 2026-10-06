"""Independent grading of extraction runs against their cited evidence.

  data/papers/<id>/extraction-runs/<run-id>/grades/<grade-id>.json

A grader sees each reasoning entry's value, the extractor's basis and note, the
slot's description, and the cited lines, and returns per field the probability
that the value is correct and supported, plus a one-line issue when it is not
clearly so (`specs/grading/spec.md`). Grades sit beside the
immutable run like reviews do; each pass adds a file and none is overwritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .config import LitSchemaConfig
from .review_paths import InvalidReviewPathError, canonical_review_path, parse_path, resolve
from .runs import RunFiles, new_run_id
from .version import installed_version

GRADE_VERSION = 2
READABLE_VERSIONS = (1, 2)
GRADES_DIRNAME = "grades"
DEFAULT_MODEL = "claude-sonnet-5"
#: The agent CLIs litschema can grade through, and each one's default model.
HARNESSES = {"claude-code": DEFAULT_MODEL, "codex": None}
DEFAULT_HARNESS = "claude-code"

#: Lower bounds of the confidence bands; below `check` is `low`.
BANDS = {"high": 0.9, "check": 0.6}
BAND_NAMES = ("high", "check", "low", "cannot_verify")
FLAG_BANDS = ("check", "low", "cannot_verify")
#: Version-1 grades stored a verdict; this is how each one displays.
VERDICT_BANDS = {
    "supported": "high",
    "partial": "check",
    "unsupported": "low",
    "cannot_verify": "cannot_verify",
}
#: Variables that make `claude` bill the API instead of the logged-in account.
API_BILLING_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
CLAUDE_TIMEOUT_S = 1800

CONTEXT_LINES = 2
CONTEXT_CHARS = 300
MAX_EVIDENCE_LINES = 40

_CITE_RE = re.compile(r"L(\d+)(?:\s*-\s*L?(\d+))?", re.IGNORECASE)
_FIGURE_RE = re.compile(r"!\[[^\]]*\]\((figures/[^)\s]+)\)")

RUBRIC = """You are grading an extraction from a scientific paper. You did not write it.
For each field below you get: the field's path and meaning, the extracted value, how the
extractor says it got the value (its basis, and a note when the value is not stated
directly), and the cited lines of the paper (line-numbered; cited lines are marked with >
and shown whole, and up to two lines either side are included for context).

For each field give a confidence: the probability (0-1) that the extracted value is
correct as stated AND supported by its cited lines. It is not your confidence in a
verdict. The basis and note tell you what to check; they are claims, not evidence.
- A value stated plainly in the evidence: about 0.95 or higher.
- A routine conversion (units, degrees-minutes to decimal degrees) or a clear mapping
  onto a schema enum or list stays high if it is correct.
- An inference, a choice among alternatives, or knowledge that is not in the evidence
  lowers the confidence. If your reasoning relies on "implies", "suggests", or "likely",
  the value is not clearly supported.
- Evidence about a different site, setup, sample, or treatment than the field describes,
  or evidence that contradicts the value: low.
- Use null only when it cannot be judged: the deciding evidence is a figure you cannot
  read, or there is no citation.

Every grade has an issue: one short line saying what is weakest about the value,
naming what in the evidence decides it. When nothing is weak, say what supports it.

Figure lines appear as [figure image: PATH]. When one is cited, open the image at PATH
and judge from it.
Do not use outside knowledge of the paper. Return one grade per field id."""

RUBRIC_SHA256 = "sha256:" + hashlib.sha256(RUBRIC.encode()).hexdigest()

GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "grades": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
                    "issue": {"type": "string", "minLength": 1},
                },
                "required": ["id", "confidence", "issue"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["grades"],
    "additionalProperties": False,
}


class GradeError(Exception):
    """A run could not be graded; nothing was written."""


class HarnessNotFoundError(GradeError):
    """The grading CLI is not on PATH."""


class ClaudeNotFoundError(HarnessNotFoundError):
    """The `claude` CLI is not on PATH."""


class GraderConfigError(ValueError):
    """`models.grade` names an unknown harness or no model."""


@dataclass(frozen=True)
class GraderSettings:
    harness: str
    model: str


def grader_settings(
    cfg: LitSchemaConfig, *, harness: str | None = None, model: str | None = None
) -> GraderSettings:
    """Command-line options, then `models.grade` in litschema.yaml, then the defaults."""
    models = cfg.raw.get("models") or {}
    block = models.get("grade") if isinstance(models, dict) else None
    block = block or {}
    if not isinstance(models, dict) or not isinstance(block, dict):
        raise GraderConfigError("`models.grade` in litschema.yaml must be a mapping")
    harness = harness or block.get("harness") or DEFAULT_HARNESS
    if harness not in HARNESSES:
        raise GraderConfigError(
            f"unknown grading harness {harness!r}; expected one of: {', '.join(HARNESSES)}"
        )
    # A model set for another harness would be passed to the wrong CLI.
    configured = block.get("model") if (block.get("harness") or DEFAULT_HARNESS) == harness else None
    model = model or configured or HARNESSES[harness]
    if not model:
        raise GraderConfigError(
            f"grading with {harness} needs a model: set `models.grade.model` in "
            "litschema.yaml or pass --model"
        )
    return GraderSettings(harness=harness, model=str(model))


class GradeCorruptError(Exception):
    """A stored grade file is unreadable or not a grade."""


def band_for(confidence: float | None, bands: dict | None = None) -> str:
    """The display band for a grader confidence; null is `cannot_verify`."""
    if confidence is None:
        return "cannot_verify"
    bands = bands or BANDS
    if confidence >= bands["high"]:
        return "high"
    if confidence >= bands["check"]:
        return "check"
    return "low"


def field_band(field: dict, bands: dict | None = None) -> str | None:
    """A stored grade field's band, mapping version-1 verdicts."""
    if "verdict" in field:
        return VERDICT_BANDS.get(field["verdict"])
    confidence = field.get("confidence")
    if confidence is not None and not isinstance(confidence, (int, float)):
        return None
    return band_for(confidence, bands)


def grade_bands(grade: dict) -> dict:
    """The thresholds a grade was stored with, else the current ones."""
    bands = (grade.get("grader") or {}).get("bands")
    if isinstance(bands, dict) and all(isinstance(bands.get(k), (int, float)) for k in BANDS):
        return bands
    return BANDS


def with_bands(grade: dict) -> dict:
    """A copy of the grade with each field's derived `band` added."""
    bands = grade_bands(grade)
    fields = [
        {**f, "band": field_band(f, bands)} if isinstance(f, dict) else f
        for f in grade.get("fields") or []
    ]
    return {**grade, "fields": fields}


def band_counts(grade: dict) -> dict[str, int]:
    bands = grade_bands(grade)
    found = [field_band(f, bands) for f in grade.get("fields") or [] if isinstance(f, dict)]
    return {name: found.count(name) for name in BAND_NAMES}


# ── evidence ────────────────────────────────────────────────────────────────


def cited_lines(source_lines: str | None) -> list[int]:
    """Line numbers named by a `source_lines` string such as `L3-L5,L9`."""
    cited: set[int] = set()
    for match in _CITE_RE.finditer(source_lines or ""):
        start = int(match.group(1))
        end = int(match.group(2) or start)
        cited.update(range(min(start, end), max(start, end) + 1))
    return sorted(cited)


def _figure_refs(text: str, article_dir: Path) -> str:
    def swap(match: re.Match) -> str:
        path = article_dir / match.group(1)
        if path.is_file():
            return f"[figure image: {path}]"
        return f"[figure image missing: {match.group(1)}]"

    return _FIGURE_RE.sub(swap, text)


def build_evidence(lines: list[str], source_lines: str | None, article_dir: Path) -> str:
    """Cited lines in full with trimmed context, capped at MAX_EVIDENCE_LINES."""
    cited = cited_lines(source_lines)
    if not cited:
        return "(no citation)"
    cited_set = set(cited)
    shown = sorted(
        {
            n
            for c in cited
            for n in range(c - CONTEXT_LINES, c + CONTEXT_LINES + 1)
            if 1 <= n <= len(lines)
        }
    )
    out: list[str] = []
    last = None
    for n in shown[:MAX_EVIDENCE_LINES]:
        if last is not None and n != last + 1:
            out.append("   ...")
        if n in cited_set:
            # Cited lines stay whole: a converted line is often a full paragraph.
            out.append(f">L{n}: {_figure_refs(lines[n - 1], article_dir)}")
        else:
            out.append(f" L{n}: {lines[n - 1][:CONTEXT_CHARS]}")
        last = n
    if len(shown) > MAX_EVIDENCE_LINES:
        out.append(f"   ... ({len(shown) - MAX_EVIDENCE_LINES} more lines not shown)")
    past_end = [n for n in cited if n > len(lines)]
    if past_end:
        out.append(f"   (cited L{past_end[0]} is past the end of the document, {len(lines)} lines)")
    return "\n".join(out)


def slot_descriptions(cfg: LitSchemaConfig) -> dict[str, str]:
    """Slot descriptions keyed by path with indices dropped (`a.b.c`)."""
    from .schema_resolution import resolve_extraction_schema

    resolved = resolve_extraction_schema(cfg)
    view = resolved.view
    classes = set(view.all_classes())
    out: dict[str, str] = {}

    def walk(class_name: str, prefix: str, stack: tuple[str, ...]) -> None:
        if class_name in stack:
            return
        for slot in view.class_induced_slots(class_name):
            path = f"{prefix}.{slot.name}" if prefix else slot.name
            if slot.description:
                out[path] = " ".join(slot.description.split())
            if slot.range in classes:
                walk(slot.range, path, (*stack, class_name))

    walk(resolved.root_class, "", ())
    return out


def _pattern(path: str) -> str:
    return ".".join(part for part in parse_path(path) if isinstance(part, str))


@dataclass(frozen=True)
class GradeTarget:
    """One reasoning entry to grade."""

    path: str
    value: object
    note: str | None
    source_lines: str | None
    basis: str | None = None


def grade_targets(run: RunFiles) -> list[GradeTarget]:
    """Every reasoning entry, with its value read from the extraction when it resolves."""
    extraction = json.loads(run.extraction.read_text())
    reasoning = json.loads(run.reasoning.read_text())
    targets = []
    for entry in reasoning.get("fields") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            continue
        try:
            path = canonical_review_path(entry["path"])
            value = resolve(extraction, path)
        except (InvalidReviewPathError, KeyError):
            path, value = entry["path"], entry.get("value")
        targets.append(
            GradeTarget(
                path=path,
                value=value,
                note=entry.get("note") or entry.get("reasoning"),
                source_lines=entry.get("source_lines"),
                basis=entry.get("basis"),
            )
        )
    return targets


def build_prompt(
    targets: list[GradeTarget], lines: list[str], descriptions: dict[str, str], article_dir: Path
) -> str:
    parts = [RUBRIC, ""]
    for index, target in enumerate(targets):
        try:
            meaning = descriptions.get(_pattern(target.path))
        except InvalidReviewPathError:
            meaning = None
        parts += [
            f"### Field {index}: {target.path}",
            f"Meaning: {meaning or '(no description)'}",
            f"Value: {json.dumps(target.value, ensure_ascii=False)}",
            f"Basis: {target.basis or '(not given)'}",
            f"Extractor's note: {target.note or '(none)'}",
            "Evidence:",
            build_evidence(lines, target.source_lines, article_dir),
            "",
        ]
    return "\n".join(parts)


# ── the claude CLI ──────────────────────────────────────────────────────────


def api_billing_notice(environ: dict[str, str] | None = None) -> str | None:
    """A note naming the shell variable that will bill the API, if one is set."""
    source = os.environ if environ is None else environ
    names = [name for name in API_BILLING_ENV if source.get(name)]
    if not names:
        return None
    return f"{' and '.join(names)} {'is' if len(names) == 1 else 'are'} set, so claude bills the API for grading"


def claude_executable() -> str:
    path = shutil.which("claude")
    if path is None:
        raise ClaudeNotFoundError(
            "claude is not on PATH; install Claude Code "
            "(https://docs.claude.com/en/docs/claude-code) and run `claude` once to log in"
        )
    return path


def claude_version(executable: str) -> str | None:
    return harness_version(executable)


def harness_executable(harness: str) -> str:
    if harness == "claude-code":
        return claude_executable()
    path = shutil.which("codex")
    if path is None:
        raise HarnessNotFoundError(
            "codex is not on PATH; install the Codex CLI "
            "(https://developers.openai.com/codex/cli) and run `codex login`"
        )
    return path


_VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)?\S*")


def harness_version(executable: str) -> str | None:
    """The first version number `<cli> --version` prints."""
    proc = subprocess.run(
        [executable, "--version"], capture_output=True, text=True, timeout=60
    )
    match = _VERSION_RE.search(proc.stdout) if proc.returncode == 0 else None
    return match.group(0) if match else None


def claude_command(executable: str, model: str, article_dir: Path) -> list[str]:
    return [
        executable,
        "-p",
        "Grade the fields described on stdin.",
        "--model",
        model,
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(GRADE_SCHEMA),
        "--setting-sources",
        "project",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--tools",
        "Read",
        "--allowedTools",
        "Read",
        "--add-dir",
        str(article_dir),
    ]


def run_claude(executable: str, model: str, prompt: str, article_dir: Path) -> dict:
    """Run one grading call and return the parsed JSON result."""
    try:
        proc = subprocess.run(
            claude_command(executable, model, article_dir),
            input=prompt,
            cwd=article_dir,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise GradeError(f"claude did not finish within {CLAUDE_TIMEOUT_S}s") from exc
    try:
        result = json.loads(proc.stdout)
    except ValueError:
        detail = (proc.stderr or proc.stdout).strip()[-500:]
        raise GradeError(
            f"claude exited {proc.returncode} without a JSON result: {detail}"
        ) from None
    if not isinstance(result, dict):
        raise GradeError("claude returned JSON that is not an object")
    if proc.returncode != 0 or result.get("is_error"):
        detail = str(result.get("result") or result.get("subtype") or proc.stderr).strip()[-500:]
        raise GradeError(f"claude reported an error: {detail}")
    return result


@dataclass
class GraderReply:
    """What one grading call returned, the same for every harness."""

    structured: object
    model: str | None
    usage: dict


def codex_command(
    executable: str, model: str, article_dir: Path, schema: Path, out: Path, images: list[Path]
) -> list[str]:
    return [
        executable,
        "exec",
        "--model",
        model,
        "--sandbox",
        "read-only",
        "--cd",
        str(article_dir),
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--output-schema",
        str(schema),
        "--output-last-message",
        str(out),
        "--json",
        *(f"--image={path}" for path in images),
        "-",
    ]


def run_codex(
    executable: str, model: str, prompt: str, article_dir: Path, images: list[Path]
) -> GraderReply:
    """Run one grading call through `codex exec` and return its structured reply."""
    with tempfile.TemporaryDirectory(prefix="litschema-grade-") as tmp:
        schema = Path(tmp) / "schema.json"
        schema.write_text(json.dumps(GRADE_SCHEMA))
        out = Path(tmp) / "reply.json"
        try:
            proc = subprocess.run(
                codex_command(executable, model, article_dir, schema, out, images),
                input=prompt,
                cwd=article_dir,
                capture_output=True,
                text=True,
                timeout=CLAUDE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as exc:
            raise GradeError(f"codex did not finish within {CLAUDE_TIMEOUT_S}s") from exc
        usage: dict = {}
        error = None
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
                usage = event["usage"]
            elif event.get("type") in ("error", "turn.failed"):
                error = event.get("message") or (event.get("error") or {}).get("message")
        if proc.returncode != 0 or error:
            detail = str(error or proc.stderr or proc.stdout).strip()[-500:]
            raise GradeError(f"codex reported an error: {detail}")
        try:
            structured = json.loads(out.read_text())
        except (OSError, ValueError):
            raise GradeError("codex returned no JSON reply") from None
    return GraderReply(
        structured=structured,
        model=None,
        usage={
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "cache_read_input_tokens": int(usage.get("cached_input_tokens") or 0),
            "cache_creation_input_tokens": int(usage.get("cache_write_input_tokens") or 0),
            "cost_estimate_usd": None,
        },
    )


def cited_figures(targets: list[GradeTarget], lines: list[str], article_dir: Path) -> list[Path]:
    """Figure images on cited lines, for harnesses that take images as attachments."""
    found: list[Path] = []
    for target in targets:
        for n in cited_lines(target.source_lines):
            if not 1 <= n <= len(lines):
                continue
            for match in _FIGURE_RE.finditer(lines[n - 1]):
                path = article_dir / match.group(1)
                if path.is_file() and path not in found:
                    found.append(path)
    return found


def reported_model(result: dict) -> str | None:
    """The model that did the work: the modelUsage entry with the most output."""
    usage = result.get("modelUsage")
    if not isinstance(usage, dict) or not usage:
        return None
    name, stats = max(
        usage.items(),
        key=lambda item: (item[1] or {}).get("outputTokens", 0) if isinstance(item[1], dict) else 0,
    )
    if isinstance(stats, dict) and isinstance(stats.get("canonicalModel"), str):
        return stats["canonicalModel"]
    return name


def parse_grades(structured: object, targets: list[GradeTarget]) -> tuple[list[dict], list[str]]:
    """Graded fields in target order, and the paths the grader skipped.

    Unknown ids and repeats of an id are ignored; the first grade per id wins.
    """
    grades = structured.get("grades") if isinstance(structured, dict) else None
    if not isinstance(grades, list):
        raise GradeError("the grader returned no structured grades")
    by_id: dict[int, dict] = {}
    for grade in grades:
        if not isinstance(grade, dict):
            continue
        index = grade.get("id")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(targets):
            continue
        if index in by_id or "confidence" not in grade:
            continue
        confidence = grade["confidence"]
        if confidence is not None and (
            not isinstance(confidence, (int, float)) or isinstance(confidence, bool)
        ):
            continue
        by_id[index] = grade
    fields, ungraded = [], []
    for index, target in enumerate(targets):
        grade = by_id.get(index)
        if grade is None:
            ungraded.append(target.path)
            continue
        confidence = grade["confidence"]
        if confidence is not None:
            confidence = max(0.0, min(1.0, float(confidence)))
        entry = {"path": target.path, "confidence": confidence}
        issue = str(grade.get("issue") or "").strip()
        if issue and band_for(confidence) != "high":
            entry["issue"] = issue
        fields.append(entry)
    if not fields:
        raise GradeError("the grader graded none of the fields")
    return fields, ungraded


def _usage(result: dict) -> dict:
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    keys = (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    )
    out = {key: int(usage.get(key) or 0) for key in keys}
    cost = result.get("total_cost_usd")
    out["cost_estimate_usd"] = float(cost) if isinstance(cost, (int, float)) else None
    return out


# ── storage ─────────────────────────────────────────────────────────────────


def grades_dir(run: RunFiles) -> Path:
    return run.run_dir / GRADES_DIRNAME


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def input_hashes(run: RunFiles) -> dict[str, str]:
    return {
        "extraction": _sha256(run.extraction),
        "reasoning": _sha256(run.reasoning),
        "prepared_text": _sha256(run.article.markdown),
    }


def write_grade(run: RunFiles, record: dict) -> Path:
    directory = grades_dir(run)
    directory.mkdir(exist_ok=True)
    path = directory / f"{record['grade_id']}.json"
    tmp = directory / f".{record['grade_id']}.json.tmp"
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return path


def read_grade(path: Path) -> dict:
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise GradeCorruptError(f"{path} is unreadable: {exc}") from exc
    if (
        not isinstance(record, dict)
        or record.get("version") not in READABLE_VERSIONS
        or not isinstance(record.get("fields"), list)
        or not isinstance(record.get("inputs"), dict)
    ):
        raise GradeCorruptError(f"{path} is not a grade litschema can read")
    return record


def list_grades(run: RunFiles) -> list[dict]:
    """Every stored grade for the run, newest first."""
    directory = grades_dir(run)
    if not directory.is_dir():
        return []
    records = [read_grade(path) for path in directory.glob("*.json")]
    records.sort(
        key=lambda r: (str(r.get("created_at") or ""), str(r.get("grade_id") or "")), reverse=True
    )
    return records


@dataclass
class GradeStatus:
    """The run's current grade and the newer grades ignored as stale."""

    grade: dict | None
    stale: list[dict] = field(default_factory=list)


def current_grade(run: RunFiles) -> GradeStatus:
    """The newest grade whose input hashes match the run's files."""
    records = list_grades(run)
    if not records:
        return GradeStatus(grade=None)
    hashes = input_hashes(run)
    stale = []
    for record in records:
        if record["inputs"] == hashes:
            return GradeStatus(grade=record, stale=stale)
        stale.append(record)
    return GradeStatus(grade=None, stale=stale)


def has_current_grade(run: RunFiles, model: str) -> bool:
    """True when a complete, current grade exists from `model` under this rubric."""
    hashes = input_hashes(run)
    for record in list_grades(run):
        grader = record.get("grader") or {}
        if (
            record["inputs"] == hashes
            and grader.get("rubric_sha256") == RUBRIC_SHA256
            and model in (grader.get("requested_model"), grader.get("model"))
            and not record.get("ungraded")
        ):
            return True
    return False


def flag_count(grade: dict | None) -> int | None:
    if grade is None:
        return None
    counts = band_counts(grade)
    return sum(counts[name] for name in FLAG_BANDS)


# ── grading ─────────────────────────────────────────────────────────────────


@dataclass
class GradeOutcome:
    run: RunFiles
    record: dict
    path: Path
    seconds: float

    @property
    def counts(self) -> dict[str, int]:
        return band_counts(self.record)


def grade_run(
    cfg: LitSchemaConfig,
    run: RunFiles,
    *,
    grader: GraderSettings,
    executable: str,
    harness_version: str | None,
    descriptions: dict[str, str] | None = None,
) -> GradeOutcome:
    """Grade one run through the configured agent CLI and store the result beside it."""
    started = time.monotonic()
    if not run.reasoning.is_file():
        raise GradeError(f"{run.run_id} has no agent-reasoning.json")
    if not run.article.markdown.is_file():
        raise GradeError(f"{run.article.article_id} has no article.md to check citations against")
    targets = grade_targets(run)
    if not targets:
        raise GradeError(f"{run.run_id} has no reasoning entries to grade")
    hashes = input_hashes(run)
    article_dir = run.article.article_dir.resolve()
    lines = run.article.markdown.read_text().split("\n")
    if descriptions is None:
        descriptions = slot_descriptions(cfg)
    prompt = build_prompt(targets, lines, descriptions, article_dir)

    model = grader.model
    if grader.harness == "codex":
        reply = run_codex(
            executable, model, prompt, article_dir, cited_figures(targets, lines, article_dir)
        )
    else:
        result = run_claude(executable, model, prompt, article_dir)
        reply = GraderReply(
            structured=result.get("structured_output"),
            model=reported_model(result),
            usage=_usage(result),
        )
    fields, ungraded = parse_grades(reply.structured, targets)
    record = {
        "version": GRADE_VERSION,
        "grade_id": new_run_id(),
        "article_id": run.article.article_id,
        "run_id": run.run_id,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "grader": {
            "harness": grader.harness,
            "harness_version": harness_version,
            "requested_model": model,
            "model": reply.model,
            "rubric_sha256": RUBRIC_SHA256,
            "bands": dict(BANDS),
            "litschema_version": installed_version(),
        },
        "inputs": hashes,
        "fields": fields,
        "ungraded": ungraded,
        "usage": reply.usage,
    }
    path = write_grade(run, record)
    return GradeOutcome(run=run, record=record, path=path, seconds=time.monotonic() - started)
