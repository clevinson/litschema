from __future__ import annotations

from litschema.explore.loader import REMOVE_SENTINEL, _apply_override


def test_apply_override_sets_scalar_values() -> None:
    record = {"title": "Old", "experiments": [{"ph": 6.8}]}

    assert _apply_override(record, "title", "New") is True
    assert _apply_override(record, "experiments[0].ph", 6.5) is True
    assert record == {"title": "New", "experiments": [{"ph": 6.5}]}


def test_apply_override_remove_sentinel_removes_the_field() -> None:
    # A reviewer's "this field should not exist" must never land in the
    # explore store as the literal string "__remove__".
    record = {"title": "T", "doi": "10.1/x", "experiments": [{"ph": 6.8, "n": 3}]}

    assert _apply_override(record, "doi", REMOVE_SENTINEL) is True
    assert _apply_override(record, "experiments[0].ph", REMOVE_SENTINEL) is True

    assert "doi" not in record
    assert "ph" not in record["experiments"][0]
    assert record["experiments"][0]["n"] == 3


def test_apply_override_remove_sentinel_nulls_list_items() -> None:
    record = {"tags": ["a", "b", "c"]}

    assert _apply_override(record, "tags[1]", REMOVE_SENTINEL) is True

    assert record["tags"] == ["a", None, "c"]  # positions preserved


def test_apply_override_reports_unresolvable_paths() -> None:
    record = {"experiments": [{"ph": 6.8}]}

    assert _apply_override(record, "experiments[9].ph", "x") is False
    assert _apply_override(record, "", "x") is False
    assert record == {"experiments": [{"ph": 6.8}]}
