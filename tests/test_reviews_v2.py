"""Reviews v2: stored model, effective state, hierarchy, add, subtree unreview."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from litschema.articles import article_files
from litschema.config import LitSchemaConfig
from litschema.review_paths import InvalidReviewPathError, leaf_paths, parse_path
from litschema.reviews import (
    OVERRIDDEN,
    UNREVIEWED,
    VERIFIED,
    ReviewContractError,
    ReviewCorruptError,
    effective_extraction,
    effective_state,
    read_reviews,
    review_progress,
    unreview_subtree,
    upsert_review,
    write_reviews,
)
from litschema.runs import run_files

from .helpers import TEST_RUN_ID, publish_test_run


def _cfg(project: Path) -> LitSchemaConfig:
    return LitSchemaConfig(
        config_path=project / "litschema.yaml",
        project_root=project,
        data_dir=project / "data",
        schema_dir=project / "schema",
        references_dir=project / "references",
        tracking_xlsx=project / "t.xlsx",
        paper_inbox_dir=project / "papers-inbox",
        static_site_dir=project / "static-site",
        article_store_dir=project / "data" / "papers",
        raw={},
    )


def _run(tmp_path: Path, extraction: dict):
    cfg = _cfg(tmp_path)
    files = article_files(cfg, "a")
    files.article_dir.mkdir(parents=True, exist_ok=True)
    (files.metadata).write_text(json.dumps({"id": "a"}))
    publish_test_run(files.article_dir, extraction)
    return run_files(files, TEST_RUN_ID)


NESTED = {
    "article_id": "a",
    "title": "T",
    "experiments": [
        {"id": "E1", "ph": 6.1, "yield": 3.2},
        {"id": "E2", "ph": 7.0},
    ],
}


# ── path algebra ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "parts"),
    [
        ("title", ("title",)),
        ("experiments[0]", ("experiments", 0)),
        ("experiments[0].ph", ("experiments", 0, "ph")),
        (".experiments[10].a.b", ("experiments", 10, "a", "b")),
    ],
)
def test_parse_path_accepts_canonical_forms(path, parts) -> None:
    assert parse_path(path) == parts


@pytest.mark.parametrize("bad", ["", ".", "a..b", "a.", "[0]x", "a[b]", "a[]", "[0"])
def test_parse_path_rejects_malformed(bad) -> None:
    with pytest.raises(InvalidReviewPathError):
        parse_path(bad)


def test_leaf_paths_skips_containers(tmp_path: Path) -> None:
    assert leaf_paths(NESTED) == [
        "article_id",
        "title",
        "experiments[0].id",
        "experiments[0].ph",
        "experiments[0].yield",
        "experiments[1].id",
        "experiments[1].ph",
    ]


# ── stored model ─────────────────────────────────────────────────────────────


def test_empty_entry_is_verified_and_override_is_overridden(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)

    upsert_review(run, "title", {})
    fields = upsert_review(run, "experiments[0].ph", {"override": {"op": "replace", "value": 6.5}})

    assert effective_state("title", fields) == VERIFIED
    assert effective_state("experiments[0].ph", fields) == OVERRIDDEN
    assert effective_state("experiments[1].ph", fields) == UNREVIEWED
    on_disk = json.loads(run.review.read_text())
    assert on_disk["version"] == 2
    assert on_disk["fields"]["title"] == {}


def test_version_1_entries_are_corrupt_not_migrated(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)
    run.review.write_text(
        json.dumps(
            {"version": 1, "fields": {"title": {"author": "A", "signal": "verified"}}}
        )
    )

    with pytest.raises(ReviewCorruptError):
        read_reviews(run)


def test_corrupt_review_blocks_writes_without_destroying_the_file(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)
    run.review.write_text("{not json")

    with pytest.raises(ReviewCorruptError):
        read_reviews(run)
    with pytest.raises(ReviewCorruptError):
        upsert_review(run, "title", {})
    assert run.review.read_text() == "{not json"  # left for a human to inspect


def test_empty_field_map_removes_the_file(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)
    upsert_review(run, "title", {})
    assert run.review.is_file()

    write_reviews(run, {})

    assert not run.review.exists()


# ── ancestry and canonicalization ────────────────────────────────────────────


def test_parent_verification_covers_descendants(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)

    fields = upsert_review(run, "experiments[0]", {})

    assert effective_state("experiments[0].ph", fields) == VERIFIED
    assert effective_state("experiments[1].ph", fields) == UNREVIEWED


def test_redundant_descendant_verification_is_dropped_but_notes_survive(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)
    upsert_review(run, "experiments[0].ph", {})
    upsert_review(run, "experiments[0].yield", {"note": "checked against supplement"})

    fields = upsert_review(run, "experiments[0]", {})

    assert "experiments[0].ph" not in fields  # redundant under bare verification
    assert fields["experiments[0].yield"] == {"note": "checked against supplement"}
    assert fields["experiments[0]"] == {}


def test_parent_save_never_synthesized_from_siblings(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)

    upsert_review(run, "experiments[0].id", {})
    upsert_review(run, "experiments[0].ph", {})
    fields = upsert_review(run, "experiments[0].yield", {})

    assert "experiments[0]" not in fields  # complete leaf coverage != parent intent
    assert len(fields) == 3


def test_container_override_is_terminal(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)
    upsert_review(run, "experiments[0].ph", {"override": {"op": "replace", "value": 6.5}})

    fields = upsert_review(
        run, "experiments[0]", {"override": {"op": "replace", "value": {"id": "E1", "ph": 9.9}}}
    )

    assert "experiments[0].ph" not in fields  # descendants beneath it are invalid
    with pytest.raises(ReviewContractError, match="container override"):
        upsert_review(run, "experiments[0].yield", {})


# ── overrides applied ────────────────────────────────────────────────────────


def test_remove_of_array_element_writes_a_tombstone_not_a_splice(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)
    upsert_review(run, "experiments[0]", {"override": {"op": "remove"}})

    effective = effective_extraction(run)

    assert effective["experiments"][0] is None
    assert effective["experiments"][1]["id"] == "E2"  # index basis preserved


def test_remove_of_property_deletes_it(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)
    upsert_review(run, "experiments[0].yield", {"override": {"op": "remove"}})

    effective = effective_extraction(run)

    assert "yield" not in effective["experiments"][0]
    assert effective["experiments"][0]["ph"] == 6.1


def test_replace_sets_the_value_at_the_same_index(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)
    upsert_review(run, "experiments[1].ph", {"override": {"op": "replace", "value": 7.4}})

    assert effective_extraction(run)["experiments"][1]["ph"] == 7.4


def test_raw_run_artifact_is_never_mutated_by_review(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)
    before = run.extraction.read_bytes()

    upsert_review(run, "experiments[0].ph", {"override": {"op": "replace", "value": 6.5}})
    effective_extraction(run)

    assert run.extraction.read_bytes() == before


# ── add ──────────────────────────────────────────────────────────────────────


def test_add_appends_one_past_the_array_basis(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)

    upsert_review(
        run, "experiments[2]", {"override": {"op": "add", "value": {"id": "E3", "ph": 5.5}}}
    )

    effective = effective_extraction(run)
    assert len(effective["experiments"]) == 3
    assert effective["experiments"][2] == {"id": "E3", "ph": 5.5}


def test_add_fills_an_absent_property(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)

    upsert_review(run, "experiments[1].yield", {"override": {"op": "add", "value": 2.8}})

    assert effective_extraction(run)["experiments"][1]["yield"] == 2.8


def test_add_is_refused_where_the_path_already_resolves(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)

    with pytest.raises(ReviewContractError, match="use replace, not add"):
        upsert_review(run, "experiments[0].ph", {"override": {"op": "add", "value": 9.9}})


def test_add_is_refused_when_it_would_leave_a_gap(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)

    with pytest.raises(ReviewContractError, match="append one past"):
        upsert_review(run, "experiments[5]", {"override": {"op": "add", "value": {"id": "X"}}})


def test_replace_and_add_reject_null_values(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)

    for op in ("replace", "add"):
        with pytest.raises(ReviewCorruptError, match="non-null"):
            upsert_review(run, "experiments[1].yield", {"override": {"op": op, "value": None}})


def test_review_at_a_path_that_does_not_resolve_is_refused(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)

    with pytest.raises(ReviewContractError, match="does not resolve"):
        upsert_review(run, "experiments[0].nonexistent", {})


# ── subtree unreview ─────────────────────────────────────────────────────────


def test_unreview_expands_covering_ancestor_to_the_minimal_frontier(tmp_path: Path) -> None:
    """The spec's worked example: groups verified, unreview groups[0].x."""
    run = _run(tmp_path, {"groups": [{"x": 1, "y": 2}, {"x": 3}]})
    upsert_review(run, "groups", {})

    fields = unreview_subtree(run, "groups[0].x")

    assert set(fields) == {"groups[0].y", "groups[1]"}
    assert effective_state("groups[0].x", fields) == UNREVIEWED
    assert effective_state("groups[1].x", fields) == VERIFIED  # covered by the parent


def test_unreview_on_an_object_replaces_the_ancestor_with_its_siblings(tmp_path: Path) -> None:
    run = _run(tmp_path, {"a": {"x": 1, "y": 2}, "b": 3})
    upsert_review(run, "a", {})

    fields = unreview_subtree(run, "a.x")

    assert set(fields) == {"a.y"}


def test_unreview_removes_descendant_overrides_and_notes(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)
    upsert_review(run, "experiments[0].ph", {"override": {"op": "replace", "value": 6.5}})
    upsert_review(run, "experiments[0].yield", {"note": "n"})

    fields = unreview_subtree(run, "experiments[0]")

    assert fields == {}


def test_unreview_requires_confirmation_to_discard_an_ancestor_note(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)
    upsert_review(run, "experiments[0]", {"note": "whole experiment checked"})

    with pytest.raises(ReviewContractError, match="confirm explicitly"):
        unreview_subtree(run, "experiments[0].ph")

    fields = unreview_subtree(run, "experiments[0].ph", discard_note=True)
    assert "experiments[0]" not in fields


def test_unreview_is_rejected_beneath_a_container_override(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)
    upsert_review(
        run, "experiments[0]", {"override": {"op": "replace", "value": {"id": "E1", "ph": 1.0}}}
    )

    with pytest.raises(ReviewContractError, match="edit or clear it"):
        unreview_subtree(run, "experiments[0].ph")


# ── progress ─────────────────────────────────────────────────────────────────


def test_progress_counts_inherited_coverage(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)
    upsert_review(run, "experiments[0]", {})

    progress = review_progress(run)

    assert progress["n_fields"] == 7
    assert progress["n_verified"] == 3  # the three leaves under experiments[0]
    assert progress["is_complete"] is False


def test_added_leaves_enter_the_denominator(tmp_path: Path) -> None:
    run = _run(tmp_path, NESTED)
    before = review_progress(run)["n_fields"]

    upsert_review(run, "experiments[1].yield", {"override": {"op": "add", "value": 2.8}})

    after = review_progress(run)
    assert after["n_fields"] == before + 1
    assert after["n_overridden"] == 1


def test_progress_is_complete_only_when_every_leaf_is_covered(tmp_path: Path) -> None:
    run = _run(tmp_path, {"article_id": "a", "title": "T"})

    upsert_review(run, "article_id", {})
    assert review_progress(run)["is_complete"] is False

    upsert_review(run, "title", {})
    assert review_progress(run)["is_complete"] is True


def test_identifier_slots_are_excluded_from_the_denominator(tmp_path: Path) -> None:
    """Identifiers are structural identity, not review work (verifier spec)."""
    from linkml_runtime.utils.schemaview import SchemaView

    from litschema.schema_resolution import identifier_leaf_paths

    schema = tmp_path / "s.yaml"
    schema.write_text(
        "id: https://example.org/t\nname: t\n"
        "prefixes:\n  linkml: https://w3id.org/linkml/\n"
        "imports: [linkml:types]\ndefault_range: string\n"
        "classes:\n  Article:\n    tree_root: true\n    attributes:\n"
        "      article_id:\n        identifier: true\n"
        "      title: {}\n"
        "      experiments:\n        range: Experiment\n        multivalued: true\n"
        "        inlined_as_list: true\n"
        "  Experiment:\n    attributes:\n"
        "      id:\n        identifier: true\n      ph:\n        range: float\n"
    )
    view = SchemaView(str(schema))
    data = {"article_id": "a", "title": "T", "experiments": [{"id": "E1", "ph": 6.1}]}

    identifiers = identifier_leaf_paths(view, "Article", data)
    assert identifiers == {"article_id", "experiments[0].id"}

    run = _run(tmp_path / "proj", data)
    full = review_progress(run)["n_fields"]
    trimmed = review_progress(run, exclude=identifiers)["n_fields"]
    assert full == 4  # article_id, title, experiments[0].id, experiments[0].ph
    assert trimmed == 2  # only title and ph are review work
