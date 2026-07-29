"""Helpers for resolving a project's configured extraction schema."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from linkml_runtime.utils.schemaview import SchemaView

from .config import LitSchemaConfig

DEFAULT_EXTRACTION_SCHEMA = "extraction.yaml"


@dataclass(frozen=True)
class ResolvedExtractionSchema:
    path: Path
    view: SchemaView
    root_class: str


def extraction_schema_path(cfg: LitSchemaConfig) -> Path:
    """Resolve the extraction schema file path from config.

    Lenient: returns the path even if the file does not exist; callers
    that need the file to exist (e.g. :func:`resolve_extraction_schema`)
    check separately, while informational consumers (status, MCP) decide
    how to render a missing file.
    """
    schema_file = cfg.raw.get("extraction_schema_file", DEFAULT_EXTRACTION_SCHEMA)
    return cfg.schema_dir / schema_file


def _find_tree_root_class(sv: SchemaView) -> str:
    local_classes = sv.schema.classes or {}
    roots = [name for name, cls in local_classes.items() if getattr(cls, "tree_root", False)]
    if len(roots) == 1:
        return roots[0]
    if len(roots) > 1:
        raise ValueError(f"multiple locally-defined classes marked `tree_root: true`: {roots}")
    raise ValueError(
        "could not determine the root extraction class. "
        "Mark exactly one locally-defined class with `tree_root: true`."
    )


_SCALAR_COERCIONS: dict[str, tuple[type, ...]] = {
    "integer": (int,),
    "float": (float, int),
    "double": (float, int),
    "decimal": (float, int),
    "boolean": (bool,),
}


@dataclass(frozen=True)
class SlotResolution:
    """Where a review path lands in the schema.

    ``kind`` distinguishes the two ways :func:`slot_for_path` used to return
    None. They call for opposite handling: an *untyped* path is one the schema
    says nothing about, so a value there is stored as supplied; an *unknown*
    path names a property the class does not define, and writing there invents
    data the schema cannot express.
    """

    kind: str  # "slot" | "untyped" | "unknown"
    slot: object | None = None
    owner_class: str | None = None
    segment: str | None = None


def resolve_slot(view: SchemaView, root_class: str, path_parts) -> SlotResolution:
    """Walk a canonical review path through the schema.

    Integer segments are array indices and do not advance the class, since a
    multivalued slot's items share its range.
    """
    current_class: str | None = root_class
    slot = None
    for part in path_parts:
        if isinstance(part, int):
            continue
        if current_class is None:
            return SlotResolution("untyped")
        slots = {s.name: s for s in view.class_induced_slots(current_class)}
        if part not in slots:
            return SlotResolution("unknown", owner_class=current_class, segment=part)
        slot = slots[part]
        range_name = slot.range
        current_class = range_name if range_name in (view.all_classes() or {}) else None
    if slot is None:
        return SlotResolution("untyped")
    return SlotResolution("slot", slot=slot)


def slot_for_path(view: SchemaView, root_class: str, path_parts) -> object | None:
    """The LinkML slot a canonical review path lands on, or None if untyped."""
    return resolve_slot(view, root_class, path_parts).slot


def coerce_to_slot(view: SchemaView, slot, value):
    """Coerce a client-supplied value to the slot's declared scalar type.

    HTML controls submit strings, so a numeric field edited in a browser
    arrives as `"23"`. Storing that would put a string where the schema
    promises a float and quietly produce an invalid export. Coercion is exact:
    a value that does not convert cleanly raises rather than being forced.
    """
    if slot is None or value is None:
        return value
    range_name, _ = _resolve_type(view, getattr(slot, "range", None))
    if range_name not in _SCALAR_COERCIONS or not isinstance(value, str):
        return value
    text = value.strip()
    if range_name == "boolean":
        lowered = text.lower()
        if lowered in ("true", "yes", "1"):
            return True
        if lowered in ("false", "no", "0"):
            return False
        raise ValueError(f"{value!r} is not a boolean")
    try:
        return int(text) if range_name == "integer" else float(text)
    except ValueError:
        raise ValueError(f"{value!r} is not a valid {range_name}") from None


# What each LinkML scalar range accepts once coercion has run. Booleans are
# excluded from the numeric ranges deliberately: `isinstance(True, int)` is
# True in Python, so `True` would otherwise pass as a valid integer.
_RANGE_PYTHON_TYPES: dict[str, tuple[type, ...]] = {
    "integer": (int,),
    "float": (float, int),
    "double": (float, int),
    "decimal": (float, int),
    "boolean": (bool,),
    "string": (str,),
    "uri": (str,),
    "uriorcurie": (str,),
    "date": (str,),
    "datetime": (str,),
    "time": (str,),
    "ncname": (str,),
}


def check_value_against_slot(view: SchemaView, root_class: str, path_parts, value) -> None:
    """Raise ``ValueError`` if ``value`` cannot legally sit at this path.

    Coercion alone only ever looked at strings, so anything else — a list for a
    float slot, `True` for an integer, an object where a number belongs — was
    written straight through and exported as the human-reviewed value. A
    browser cannot produce those, but the annotation API is a documented
    surface and any non-browser client can.
    """
    resolution = resolve_slot(view, root_class, path_parts)
    if resolution.kind == "unknown":
        raise ValueError(
            f"{resolution.segment!r} is not a property of {resolution.owner_class}"
        )
    if resolution.kind == "untyped" or resolution.slot is None:
        return  # the schema declares nothing here; store as supplied

    slot = resolution.slot
    indexed = bool(path_parts) and isinstance(path_parts[-1], int)
    if getattr(slot, "multivalued", False) and not indexed:
        if not isinstance(value, list):
            raise ValueError(
                f"{slot.name} is multivalued, so it needs a list, not "
                f"{type(value).__name__}"
            )
        for item in value:
            _check_single_value(view, slot, item)
        return
    _check_single_value(view, slot, value)


def _check_single_value(view: SchemaView, slot, value) -> None:
    range_name = getattr(slot, "range", None)
    if value is None:
        return  # absence is expressed by `remove`, not by a null replacement

    if range_name in (view.all_classes() or {}):
        _check_class_value(view, range_name, value, slot.name)
        return

    enums = view.all_enums() or {}
    if range_name in enums:
        permitted = set((enums[range_name].permissible_values or {}).keys())
        if value not in permitted:
            raise ValueError(
                f"{value!r} is not one of the {range_name} values: {sorted(permitted)}"
            )
        return

    # A custom type declares its own base and may carry a pattern; resolve to
    # the base so `range: PositiveFloat` is checked like the float it is.
    base, type_pattern = _resolve_type(view, range_name)
    expected = _RANGE_PYTHON_TYPES.get(base)
    if expected is None:
        return  # a range we do not model; leave it to schema validation
    if isinstance(value, bool) and bool not in expected:
        raise ValueError(f"{value!r} is a boolean, but {slot.name} is {range_name}")
    if not isinstance(value, expected):
        raise ValueError(f"{value!r} is not a valid {range_name} for {slot.name}")
    if base in ("float", "double", "decimal"):
        import math

        if not math.isfinite(value):
            raise ValueError(f"{value!r} is not a finite {range_name}")

    # The schema's own constraints, not just its Python type. Without these a
    # reviewer could store a value the schema forbids and export it as truth.
    _check_constraints(slot, base, value, type_pattern)


def _resolve_type(view: SchemaView, range_name) -> tuple[str | None, str | None]:
    """(base type, pattern) for a range, following custom type definitions."""
    types = view.all_types() or {}
    pattern = None
    seen: set[str] = set()
    current = range_name
    while current in types and current not in seen:
        seen.add(current)
        definition = types[current]
        pattern = pattern or getattr(definition, "pattern", None)
        base = getattr(definition, "typeof", None)
        if not base:
            return getattr(definition, "base", None) and current or current, pattern
        current = base
    return current, pattern


def _check_constraints(slot, base: str | None, value, type_pattern: str | None) -> None:
    import re

    # JSON Schema `pattern` semantics: matches anywhere unless the pattern
    # anchors itself. `fullmatch` here was stricter than the schema and refused
    # edits the schema permits.
    pattern = getattr(slot, "pattern", None) or type_pattern
    if pattern and isinstance(value, str) and not re.search(pattern, value):
        raise ValueError(f"{value!r} does not match the pattern for {slot.name} ({pattern})")

    if base in ("integer", "float", "double", "decimal"):
        minimum = getattr(slot, "minimum_value", None)
        maximum = getattr(slot, "maximum_value", None)
        if minimum is not None and value < minimum:
            raise ValueError(f"{value!r} is below the minimum for {slot.name} ({minimum})")
        if maximum is not None and value > maximum:
            raise ValueError(f"{value!r} is above the maximum for {slot.name} ({maximum})")

    if base in ("date", "datetime", "time") and isinstance(value, str):
        # These are xsd:date / xsd:dateTime / xsd:time. `fromisoformat` is more
        # permissive than that — it takes compact forms (20240101T103000), a
        # space separator, and date-only strings for a datetime — so check the
        # lexical form first, then confirm it is a real calendar instant.
        from datetime import date, datetime
        from datetime import time as _time

        lexical = {
            "date": r"-?\d{4}-\d{2}-\d{2}(?P<tz>Z|[+-]\d{2}:\d{2})?",
            "time": r"\d{2}:\d{2}:\d{2}(\.\d+)?(?P<tz>Z|[+-]\d{2}:\d{2})?",
            "datetime": (
                r"-?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
                r"(\.\d+)?(?P<tz>Z|[+-]\d{2}:\d{2})?"
            ),
        }[base]
        match = re.fullmatch(lexical, value)
        if not match:
            raise ValueError(f"{value!r} is not a valid {base} for {slot.name}")
        offset = match.group("tz")
        if offset and offset != "Z":
            # XSD bounds timezone offsets at ±14:00; the regex alone would take
            # +15:00, and Python's parser accepts it too.
            hours, minutes = (int(part) for part in offset[1:].split(":"))
            if hours * 60 + minutes > 14 * 60:
                raise ValueError(f"{offset} is not a valid timezone offset for {slot.name}")
        parser = {
            "date": date.fromisoformat,
            "datetime": datetime.fromisoformat,
            "time": _time.fromisoformat,
        }[base]
        # `date.fromisoformat` cannot parse a timezone, though xsd:date allows
        # one, so the calendar check runs on the bare date.
        parseable = value[: match.start("tz")] if (offset and base == "date") else value
        try:
            parser(parseable.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"{value!r} is not a valid {base} for {slot.name}") from None


@lru_cache(maxsize=32)
def _class_validator(schema_path: str, schema_digest: str, class_name: str):
    """A cached LinkML validator for one class of one exact schema.

    Keyed by digest as well as path so editing the schema builds a new one
    rather than validating against a stale copy. Bounded because a project has
    few classes; validators are expensive to construct and reviews are written
    one human click at a time.
    """
    from .schema_validation import create_linkml_validator

    return create_linkml_validator(Path(schema_path), class_name)


def _check_class_value(view: SchemaView, class_name: str, value, label: str) -> None:
    """A class-range value must be a complete, valid instance of that class.

    Validated by LinkML rather than by hand: checking only that the supplied
    properties are defined accepted an object missing its required slots, and
    a scalar where a nested multivalued slot needs a list. Both would export as
    reviewed truth that the schema rejects.
    """
    if not isinstance(value, dict):
        raise ValueError(f"{label} holds {class_name} objects, not {type(value).__name__}")

    source = getattr(view, "schema", None)
    schema_path = getattr(source, "source_file", None)
    if not schema_path:
        # No file to validate against (an in-memory view): fall back to the
        # structural check rather than silently accepting anything.
        slots = {s.name: s for s in view.class_induced_slots(class_name)}
        unknown = sorted(set(value) - set(slots))
        if unknown:
            raise ValueError(f"{class_name} does not define {', '.join(unknown)}")
        for key, item in value.items():
            _check_single_value(view, slots[key], item)
        return

    digest = hashlib.sha256(Path(schema_path).read_bytes()).hexdigest()
    errors = _class_validator(str(schema_path), digest, class_name).validate(value)
    if errors:
        raise ValueError(f"invalid {class_name}: {errors[0]}")


def identifier_leaf_paths(view: SchemaView, root_class: str, data) -> set[str]:
    """Leaf paths in ``data`` that are `identifier: true` slots.

    Identifiers are structural identity, not extracted findings, so they are
    excluded from review denominators (`specs/verifier/spec.md`). Resolved by
    walking the data alongside the schema rather than by slot name, so a
    non-identifier slot that happens to share a name elsewhere is unaffected.
    """
    found: set[str] = set()

    def slots_of(class_name: str) -> dict:
        return {s.name: s for s in view.class_induced_slots(class_name)}

    def walk(node, class_name: str | None, prefix: str) -> None:
        if class_name is None or not isinstance(node, dict):
            return
        slots = slots_of(class_name)
        for key, value in node.items():
            slot = slots.get(key)
            if slot is None:
                continue
            path = f"{prefix}.{key}" if prefix else key
            if slot.identifier:
                found.add(path)
                continue
            range_name = slot.range
            if not range_name or range_name not in (view.all_classes() or {}):
                continue
            if isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, range_name, f"{path}[{index}]")
            else:
                walk(value, range_name, path)

    walk(data, root_class, "")
    return found


def identifier_reference_slots(view: SchemaView, root_class: str) -> list[dict]:
    """Slots that will silently serialize as bare ID strings, losing detail.

    LinkML defaults a multivalued slot whose range class declares an
    `identifier` to reference-by-identifier, so the generated JSON Schema
    types it as an array of strings. When the range class defines nothing but
    its identifier that is exactly right. When it defines other attributes,
    the author almost certainly expected inlined objects, and every one of
    those attributes has nowhere to land — silently, with the extraction still
    validating. Reported so the author sees it before extracting every
    document against the schema, not after.

    Returns one entry per affected slot, walking the tree from the root.
    """
    findings: list[dict] = []
    seen: set[str] = set()

    def visit(class_name: str) -> None:
        if class_name in seen:
            return
        seen.add(class_name)
        for slot in view.class_induced_slots(class_name):
            range_name = slot.range
            if not range_name or range_name not in (view.all_classes() or {}):
                continue
            identifier = None
            others: list[str] = []
            for sub in view.class_induced_slots(range_name):
                if sub.identifier:
                    identifier = sub.name
                else:
                    others.append(sub.name)
            references_by_id = (
                identifier is not None and slot.multivalued and not slot.inlined_as_list
                and not slot.inlined
            )
            if references_by_id and others:
                findings.append(
                    {
                        "owner": class_name,
                        "slot": slot.name,
                        "range": range_name,
                        "identifier": identifier,
                        "lost": sorted(others),
                    }
                )
            visit(range_name)

    visit(root_class)
    return findings


def schema_hash(cfg: LitSchemaConfig) -> str:
    """Schema identity: a digest over the schema and every file it imports.

    Hashing only the configured file is wrong wherever a project splits its
    schema across files — `tests/fixtures/projects/organic_inherits` does
    exactly that, importing a base schema and subclassing it with `is_a`.
    Editing the imported file left the recorded hash unchanged, so a run's
    provenance named bytes it was not extracted against and the
    schema-mismatch check waved the difference through.

    LinkML's own libraries (`linkml:...`) version with the dependency rather
    than with the project, so they are not part of project schema identity.

    Deterministic and independent of the working directory.
    """
    import hashlib

    digest = hashlib.sha256()
    for path in _schema_closure(extraction_schema_path(cfg)):
        # File name as well as bytes: moving content between files is a change
        # of schema even when the concatenated bytes happen to match.
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def _schema_closure(entry: Path) -> list[Path]:
    """``entry`` plus every project schema file it transitively imports.

    Sorted by resolved path so the digest never depends on traversal order.
    Unreadable or missing imports are skipped: resolution reports those, and
    computing an identity must not raise.
    """
    import yaml

    seen: dict[str, Path] = {}
    queue = [entry]
    while queue:
        current = queue.pop()
        key = str(current.resolve())
        if key in seen or not current.is_file():
            continue
        seen[key] = current
        try:
            document = yaml.safe_load(current.read_text()) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(document, dict):
            continue
        for name in document.get("imports") or []:
            name = str(name)
            if name.startswith("linkml:") or ":" in name:
                continue  # a CURIE, not a project file
            queue.extend(_import_candidates(current.parent, name))
    return [seen[key] for key in sorted(seen)]


def _import_candidates(directory: Path, name: str) -> list[Path]:
    """Files a LinkML import name could refer to, most specific first.

    `with_suffix(".yaml")` was wrong: it *replaces* an existing suffix, so an
    explicit `imports: [base.yml]` resolved to a `base.yaml` that does not
    exist and dropped the real file out of the identity digest silently — the
    exact failure the closure hash was added to prevent.
    """
    target = directory / name
    if target.suffix in (".yaml", ".yml"):
        return [target]
    # Exactly one candidate: enqueueing both would fold an unused sibling into
    # the identity digest, so editing a file LinkML never reads would change
    # the schema hash. `.yaml` wins, matching LinkML's own preference order.
    for candidate in (Path(f"{target}.yaml"), Path(f"{target}.yml")):
        if candidate.is_file():
            return [candidate]
    return []


def resolve_extraction_schema(cfg: LitSchemaConfig) -> ResolvedExtractionSchema:
    schema_path = extraction_schema_path(cfg)
    if not schema_path.exists():
        raise FileNotFoundError(
            f"extraction schema not found at {schema_path}. "
            "Set `extraction_schema_file` in litschema.yaml or place a file "
            "at the default location."
        )
    sv = SchemaView(str(schema_path))
    root_class = _find_tree_root_class(sv)
    _require_root_identifier(sv, root_class, schema_path)
    return ResolvedExtractionSchema(
        path=schema_path,
        view=sv,
        root_class=root_class,
    )


def _require_root_identifier(sv: SchemaView, root_class: str, schema_path: Path) -> None:
    """The root class must address a document by `article_id`.

    Every consumer — the CLI, the verifier, export, the review path algebra —
    needs one agreed way to say which document a record is about. Leaving that
    to convention meant it held only because every template happened to do it;
    a project that named the slot something else would fail later, somewhere
    else, for reasons that pointed at the wrong thing.

    Checked against induced slots, so inheriting `article_id` from a parent
    class satisfies it just as declaring it directly does.
    """
    slots = {slot.name: slot for slot in sv.class_induced_slots(root_class)}
    article_id = slots.get("article_id")
    if article_id is None:
        raise ValueError(
            f"{schema_path}: the root class {root_class} must declare an `article_id` "
            f"slot — it is how every part of litschema addresses a document"
        )
    if not article_id.identifier:
        raise ValueError(
            f"{schema_path}: `article_id` on {root_class} must be `identifier: true`, "
            f"so it identifies the document rather than merely describing it"
        )
