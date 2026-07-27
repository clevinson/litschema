"""Helpers for resolving a project's configured extraction schema."""

from __future__ import annotations

from dataclasses import dataclass
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
    range_name = getattr(slot, "range", None)
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

    expected = _RANGE_PYTHON_TYPES.get(range_name)
    if expected is None:
        return  # a range we do not model; leave it to schema validation
    if isinstance(value, bool) and bool not in expected:
        raise ValueError(f"{value!r} is a boolean, but {slot.name} is {range_name}")
    if not isinstance(value, expected):
        raise ValueError(f"{value!r} is not a valid {range_name} for {slot.name}")
    if expected == (float, int) or range_name in ("float", "double", "decimal"):
        import math

        if not math.isfinite(value):
            raise ValueError(f"{value!r} is not a finite {range_name}")


def _check_class_value(view: SchemaView, class_name: str, value, label: str) -> None:
    """A class-range value must be an object whose properties the class defines."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} holds {class_name} objects, not {type(value).__name__}")
    slots = {s.name: s for s in view.class_induced_slots(class_name)}
    unknown = sorted(set(value) - set(slots))
    if unknown:
        raise ValueError(f"{class_name} does not define {', '.join(unknown)}")
    for key, item in value.items():
        slot = slots[key]
        if getattr(slot, "multivalued", False) and isinstance(item, list):
            for entry in item:
                _check_single_value(view, slot, entry)
        else:
            _check_single_value(view, slot, item)


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
    """Schema identity: the SHA-256 of the configured schema file's exact bytes.

    The digest alone identifies the schema (specs/project-config/spec.md);
    deterministic and independent of the working directory.
    """
    import hashlib

    return "sha256:" + hashlib.sha256(extraction_schema_path(cfg).read_bytes()).hexdigest()


def resolve_extraction_schema(cfg: LitSchemaConfig) -> ResolvedExtractionSchema:
    schema_path = extraction_schema_path(cfg)
    if not schema_path.exists():
        raise FileNotFoundError(
            f"extraction schema not found at {schema_path}. "
            "Set `extraction_schema_file` in litschema.yaml or place a file "
            "at the default location."
        )
    sv = SchemaView(str(schema_path))
    return ResolvedExtractionSchema(
        path=schema_path,
        view=sv,
        root_class=_find_tree_root_class(sv),
    )
