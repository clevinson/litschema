"""Independent grading of extraction runs against their cited evidence.

  data/papers/<id>/extraction-runs/<run-id>/grades/<grade-id>.json

A grader sees each reasoning entry's value, the extractor's note, the slot's
description, and the cited lines, and returns a verdict, a confidence, and one
line of reasoning per field (`specs/grading/spec.md`). Grades sit beside the
immutable run like reviews do; each pass adds a file and none is overwritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .config import LitSchemaConfig
from .review_paths import InvalidReviewPathError, canonical_review_path, parse_path, resolve
from .runs import RunFiles, new_run_id
from .version import installed_version

GRADE_VERSION = 1
GRADES_DIRNAME = "grades"
DEFAULT_MODEL = "claude-sonnet-5"
VERDICTS = ("supported", "partial", "unsupported", "cannot_verify")
FLAG_VERDICTS = ("unsupported", "partial")
STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")
CLAUDE_TIMEOUT_S = 1800

CONTEXT_LINES = 2
CONTEXT_CHARS = 300
MAX_EVIDENCE_LINES = 40

_CITE_RE = re.compile(r"L(\d+)(?:\s*-\s*L?(\d+))?", re.IGNORECASE)
_FIGURE_RE = re.compile(r"!\[[^\]]*\]\((figures/[^)\s]+)\)")

RUBRIC = """You are grading an extraction from a scientific paper. You did not write it.
For each field below you get: the field's path and meaning, the extracted value, the
extractor's note on how it got the value, and the cited lines of the paper
(line-numbered; cited lines are marked with > and shown whole, and up to two lines either
side are included for context).

Judge only whether the cited evidence supports the value:
- "supported": the evidence states the value, or it follows directly. Routine unit
  conversions (degrees-minutes to decimal degrees, cm to m) count as supported.
- "partial": the value is plausible but needs an inference, a combination, or outside
  knowledge; or only part of the value is supported. If your reasoning relies on
  "implies", "suggests", "likely", or knowledge that is not in the evidence, the verdict
  is "partial", not "supported".
- "unsupported": the evidence does not back the value, contradicts it, or is about a
  different site, setup, sample, or treatment than the field describes.
- "cannot_verify": the deciding evidence is a figure you cannot read, or there is no
  citation.

Figure lines appear as [figure image: PATH]. When one is cited, open the image at PATH
with the Read tool and judge from it.
Do not use outside knowledge of the paper. Give a confidence (0-1) that your verdict is
right, and one short sentence of reasoning that names what in the evidence decides it.
Return one grade per field id."""

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
                    "verdict": {"enum": list(VERDICTS)},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reasoning": {"type": "string"},
                },
                "required": ["id", "verdict", "confidence", "reasoning"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["grades"],
    "additionalProperties": False,
}


class GradeError(Exception):
    """A run could not be graded; nothing was written."""


class ClaudeNotFoundError(GradeError):
    """The `claude` CLI is not on PATH."""


class GradeCorruptError(Exception):
    """A stored grade file is unreadable or not a grade."""


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
                note=entry.get("reasoning"),
                source_lines=entry.get("source_lines"),
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
            f"Extractor's note: {target.note or '(none)'}",
            "Evidence:",
            build_evidence(lines, target.source_lines, article_dir),
            "",
        ]
    return "\n".join(parts)


# ── the claude CLI ──────────────────────────────────────────────────────────


def grader_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    """The environment without API credentials, so claude uses the logged-in account."""
    source = os.environ if environ is None else environ
    return {k: v for k, v in source.items() if k not in STRIPPED_ENV}


def claude_executable() -> str:
    path = shutil.which("claude")
    if path is None:
        raise ClaudeNotFoundError(
            "claude is not on PATH; install Claude Code "
            "(https://docs.claude.com/en/docs/claude-code) and run `claude` once to log in"
        )
    return path


def claude_version(executable: str) -> str | None:
    proc = subprocess.run(
        [executable, "--version"], capture_output=True, text=True, env=grader_env(), timeout=60
    )
    words = proc.stdout.split()
    return words[0] if proc.returncode == 0 and words else None


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
            env=grader_env(),
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


def parse_grades(result: dict, targets: list[GradeTarget]) -> tuple[list[dict], list[str]]:
    """Graded fields in target order, and the paths the grader skipped.

    Unknown ids and repeats of an id are ignored; the first grade per id wins.
    """
    structured = result.get("structured_output")
    grades = structured.get("grades") if isinstance(structured, dict) else None
    if not isinstance(grades, list):
        raise GradeError("claude returned no structured grades")
    by_id: dict[int, dict] = {}
    for grade in grades:
        if not isinstance(grade, dict):
            continue
        index = grade.get("id")
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(targets):
            continue
        if index in by_id or grade.get("verdict") not in VERDICTS:
            continue
        confidence = grade.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            continue
        by_id[index] = grade
    fields, ungraded = [], []
    for index, target in enumerate(targets):
        grade = by_id.get(index)
        if grade is None:
            ungraded.append(target.path)
            continue
        fields.append(
            {
                "path": target.path,
                "verdict": grade["verdict"],
                "confidence": max(0.0, min(1.0, float(grade["confidence"]))),
                "reasoning": str(grade.get("reasoning") or ""),
            }
        )
    if not fields:
        raise GradeError("claude graded none of the fields")
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
        or record.get("version") != GRADE_VERSION
        or not isinstance(record.get("fields"), list)
        or not isinstance(record.get("inputs"), dict)
    ):
        raise GradeCorruptError(f"{path} is not a version-{GRADE_VERSION} grade")
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
    hashes = input_hashes(run)
    stale = []
    for record in list_grades(run):
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
    return sum(
        1 for f in grade["fields"] if isinstance(f, dict) and f.get("verdict") in FLAG_VERDICTS
    )


# ── grading ─────────────────────────────────────────────────────────────────


@dataclass
class GradeOutcome:
    run: RunFiles
    record: dict
    path: Path
    seconds: float

    @property
    def counts(self) -> dict[str, int]:
        verdicts = [f["verdict"] for f in self.record["fields"]]
        return {v: verdicts.count(v) for v in VERDICTS}


def grade_run(
    cfg: LitSchemaConfig,
    run: RunFiles,
    *,
    model: str,
    executable: str,
    harness_version: str | None,
    descriptions: dict[str, str] | None = None,
) -> GradeOutcome:
    """Grade one run with `claude -p` and store the result beside it."""
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

    result = run_claude(executable, model, prompt, article_dir)
    fields, ungraded = parse_grades(result, targets)
    record = {
        "version": GRADE_VERSION,
        "grade_id": new_run_id(),
        "article_id": run.article.article_id,
        "run_id": run.run_id,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "grader": {
            "harness": "claude-code",
            "harness_version": harness_version,
            "requested_model": model,
            "model": reported_model(result),
            "rubric_sha256": RUBRIC_SHA256,
            "litschema_version": installed_version(),
        },
        "inputs": hashes,
        "fields": fields,
        "ungraded": ungraded,
        "usage": _usage(result),
    }
    path = write_grade(run, record)
    return GradeOutcome(run=run, record=record, path=path, seconds=time.monotonic() - started)
