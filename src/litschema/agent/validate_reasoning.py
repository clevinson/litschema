"""Validate an agent reasoning file: LinkML shape, then citations that resolve.

Shape validation alone accepted `source_lines: L9999` on a two-hundred-line
document, because nothing ever opened the prepared text. A citation that does
not resolve is not a formatting nit — line-cited evidence is the claim this
project makes about its output, so an unresolvable one is a false claim that
looked fine to every check in the pipeline.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from ..schema_validation import validate_linkml_data
from .reasoning_schema import reasoning_schema_source_path

#: `L12` or `L12-L20` (the trailing `L` is optional), comma-separated.
_CITATION = re.compile(r"L(\d+)(?:\s*-\s*L?(\d+))?$")


def prepared_text_for(reasoning_path: Path) -> Path:
    """The article.md a reasoning file's citations refer to.

    Reasoning lives either inside a run directory or, in older projects, at the
    article root; the prepared text sits at the article root either way.
    """
    if reasoning_path.parent.parent.name == "extraction-runs":
        return reasoning_path.parent.parent.parent / "article.md"
    return reasoning_path.parent / "article.md"


def check_citations(data: dict, prepared_text: Path) -> list[str]:
    """Every citation must name lines that exist and carry content.

    Deliberately NOT checked: whether the cited line *contains* the value. A
    large share of reasoning values are composed, inferred, or normalised — a
    country taken from author affiliations, a crop name spelled correctly where
    the paper has a typo, a description of a table cell — so a content check
    would reject correct citations. Resolution is the part that can be
    mechanically true or false.
    """
    if not prepared_text.is_file():
        return [f"cannot verify citations: no prepared text at {prepared_text}"]

    lines = prepared_text.read_text().splitlines()
    problems: list[str] = []

    for entry in data.get("fields") or []:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path", "<no path>")
        spec = entry.get("source_lines")
        if not spec:
            continue

        cited: list[int] = []
        malformed = False
        for part in str(spec).split(","):
            match = _CITATION.fullmatch(part.strip())
            if not match:
                problems.append(f"{path}: {spec!r} is not a line reference like L12 or L12-L20")
                malformed = True
                break
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else start
            if end < start:
                problems.append(f"{path}: {part.strip()} runs backwards")
                malformed = True
                break
            cited.extend(range(start, end + 1))
        if malformed or not cited:
            continue

        outside = [n for n in cited if not 1 <= n <= len(lines)]
        if outside:
            problems.append(
                f"{path}: {spec} names line {outside[0]} of a {len(lines)}-line document"
            )
        elif not any(lines[n - 1].strip() for n in cited):
            problems.append(f"{path}: {spec} cites only blank lines")

    return problems


def validate_file(
    filepath: Path,
    schema_path: Path,
    root_class: str = "ExtractionReasoning",
    *,
    check_source_lines: bool = True,
) -> tuple[bool, list[str]]:
    data = json.loads(filepath.read_text())
    errors = validate_linkml_data(data, schema_path, root_class)
    if not errors and check_source_lines:
        errors = check_citations(data, prepared_text_for(filepath))
    return len(errors) == 0, errors


def _reasoning_file_for_target(target: Path) -> Path:
    if not target.exists():
        raise FileNotFoundError(f"Missing reasoning target: {target}")
    if target.is_dir():
        raise IsADirectoryError(f"Reasoning target must be a file: {target}")
    return target


def run(args: list[str] | None) -> int:
    args = list(args or [])
    if not args:
        print("Usage: litschema agent validate-reasoning <agent-reasoning.json>")
        return 1

    try:
        filepath = _reasoning_file_for_target(Path(args[0]))
    except (FileNotFoundError, IsADirectoryError) as exc:
        print(exc)
        return 1

    schema_path = reasoning_schema_source_path()

    ok, errors = validate_file(filepath, schema_path)
    if not ok:
        print(f"INVALID: {filepath}")
        for error in errors[:10]:
            print(f"  {error}")
        return 1

    print(f"Reasoning valid: {filepath}")
    return 0


def main() -> None:
    code = run(sys.argv[1:])
    if code:
        sys.exit(code)


if __name__ == "__main__":
    main()
