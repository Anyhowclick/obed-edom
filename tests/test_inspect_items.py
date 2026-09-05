"""L4 item-level checker fallback (Keynote-free).

Covers the four pieces of the item-scoped fallback added to ``inspect.py``:

* :func:`_partition_fallback` — item-addressable slides vs count-mismatch slides;
* :func:`_merge_legacy_items` — splices the JXA record's fields by (slide, kind,
  kindIndex), keeping the offline addressing and offline-only fields (runs);
* the count-drift / unreadable route to the slide-level merge;
* the caller partition in :func:`inspect_keynote_checker` (item-addressable ->
  item read; count-mismatch -> slide-level).

The item-scoped JXA read (:func:`inspect_items`) is mocked throughout, so no deck
is decoded and Keynote is never opened.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from obed_edom import inspect as inspect_mod
from obed_edom.baseline import CACHE_DIR_ENV, deck_digest, inspect_cache_path


# --------------------------------------------------------------------------
# _partition_fallback
# --------------------------------------------------------------------------
def test_partition_all_item_addressable_goes_item_scoped():
    fallback = [
        {"slide": 2, "kind": "image", "kindIndex": 0, "reason": "bulk-missing"},
        {"slide": 2, "kind": "text", "kindIndex": 1, "reason": "font-size-unresolved"},
        {"slide": 5, "kind": "movie", "kindIndex": 0, "reason": "filename-dirty"},
    ]
    item_entries, slide_numbers = inspect_mod._partition_fallback(fallback)
    assert slide_numbers == []
    assert {(e["slide"], e["kind"], e["kindIndex"]) for e in item_entries} == {
        (2, "image", 0),
        (2, "text", 1),
        (5, "movie", 0),
    }


def test_partition_count_mismatch_slide_goes_slide_level():
    fallback = [
        {"slide": 3, "kind": "image", "kindIndex": 0, "reason": "bulk-missing"},
        {"slide": 3, "kind": "image", "kindIndex": -1, "reason": "count-mismatch"},
    ]
    item_entries, slide_numbers = inspect_mod._partition_fallback(fallback)
    # A single count-mismatch entry taints the WHOLE slide -> slide-level, and its
    # sibling item-addressable entry does NOT leak into the item read.
    assert item_entries == []
    assert slide_numbers == [3]


def test_partition_negative_kindindex_forces_slide_level():
    fallback = [{"slide": 4, "kind": "group", "kindIndex": -1, "reason": "bulk-missing"}]
    item_entries, slide_numbers = inspect_mod._partition_fallback(fallback)
    assert item_entries == []
    assert slide_numbers == [4]


def test_partition_mixed_slides_split_independently():
    fallback = [
        {"slide": 1, "kind": "image", "kindIndex": 0, "reason": "bulk-missing"},
        {"slide": 2, "kind": "text", "kindIndex": 0, "reason": "count-mismatch"},
        {"slide": 7, "kind": "movie", "kindIndex": 2, "reason": "filename-dirty"},
    ]
    item_entries, slide_numbers = inspect_mod._partition_fallback(fallback)
    assert slide_numbers == [2]
    assert {e["slide"] for e in item_entries} == {1, 7}


# --------------------------------------------------------------------------
# _splice_item_record — field parity contract
# --------------------------------------------------------------------------
def test_splice_overwrites_jxa_fields_keeps_offline_addressing_and_runs():
    # Offline item carries stale geometry + a colour-managed offline colour + runs;
    # the JXA record is authoritative for everything describeItem emits.
    offline_item = {
        "index": 4,
        "kind": "text",
        "kindIndex": 1,
        "x": 10, "y": 20, "w": 30, "h": 40,
        "text": "Hello",
        "size": 0, "font": "", "color": [1, 2, 3],
        "fileName": "",
        "rotation": 0,
        "locked": False,
        "runs": [{"text": "Hello", "color": [1, 2, 3]}],
    }
    jxa_rec = {
        "index": 1,  # a describeItem index that must NOT clobber the offline order
        "kind": "text",
        "text": "Hello",
        "x": 111, "y": 222, "w": 333, "h": 120,
        "size": 24, "font": "Times", "color": [7, 8, 9],
        "fileName": "",
        "locked": False,
        "rotation": 0,
        "kindIndex": 1,
    }
    inspect_mod._splice_item_record(offline_item, jxa_rec)
    # JXA geometry/style won.
    assert (offline_item["x"], offline_item["y"], offline_item["w"], offline_item["h"]) == (111, 222, 333, 120)
    assert offline_item["size"] == 24 and offline_item["font"] == "Times"
    assert offline_item["color"] == [7, 8, 9]
    # Offline addressing preserved (index is the slide-list position, not describeItem's).
    assert offline_item["index"] == 4
    assert offline_item["kindIndex"] == 1
    # Offline-only field the JXA record never carries stays put.
    assert offline_item["runs"] == [{"text": "Hello", "color": [1, 2, 3]}]


def test_splice_adds_group_children_childcount():
    # A JXA group record carries children/childCount that the offline group item omits;
    # the splice must add them so a spliced group == the slide-level (full-JXA) group.
    offline_group = {"index": 0, "kind": "group", "kindIndex": 0,
                     "x": 0, "y": 0, "w": 0, "h": 0, "rotation": 0, "locked": False,
                     "runs": []}
    jxa_rec = {"index": 0, "kind": "group", "text": "", "x": 5, "y": 6, "w": 700, "h": 800,
               "size": 0, "font": "", "color": None, "fileName": "", "locked": False,
               "rotation": 0, "children": [], "childCount": 0, "kindIndex": 0}
    inspect_mod._splice_item_record(offline_group, jxa_rec)
    assert offline_group["children"] == []
    assert offline_group["childCount"] == 0
    assert (offline_group["w"], offline_group["h"]) == (700, 800)


# --------------------------------------------------------------------------
# _merge_legacy_items — orchestration
# --------------------------------------------------------------------------
def _payload_with(slides):
    return {"slideWidth": 7680, "slideHeight": 1080, "slides": slides}


def test_merge_splices_matching_items_and_computes_counts(monkeypatch):
    payload = _payload_with([
        {"index": 0, "number": 1, "items": [
            {"index": 0, "kind": "image", "kindIndex": 0, "x": 1, "y": 1, "w": 1, "h": 1, "fileName": ""},
            {"index": 1, "kind": "image", "kindIndex": 1, "x": 2, "y": 2, "w": 2, "h": 2, "fileName": ""},
            {"index": 2, "kind": "text", "kindIndex": 0, "x": 3, "y": 3, "w": 3, "h": 3, "text": "hi"},
        ]},
    ])
    captured = {}

    def fake_inspect_items(source, items, counts=None):
        captured["items"] = items
        captured["counts"] = counts
        return {
            0: {
                "unreadable": False,
                "records": {
                    ("image", 1): {"kind": "image", "kindIndex": 1, "x": 99, "y": 99,
                                   "w": 88, "h": 77, "fileName": "b.png"},
                },
            }
        }

    monkeypatch.setattr(inspect_mod, "inspect_items", fake_inspect_items)
    unreadable = inspect_mod._merge_legacy_items(
        payload, Path("/x.key"), [{"slide": 1, "kind": "image", "kindIndex": 1}]
    )
    assert unreadable == []
    # The count guard reference is computed from the offline payload's per-kind counts.
    assert captured["counts"] == {1: {"image": 2, "text": 1}}
    items = payload["slides"][0]["items"]
    # Only the referenced item was spliced.
    assert items[1]["x"] == 99 and items[1]["fileName"] == "b.png"
    assert items[0]["x"] == 1  # untouched
    assert items[2]["x"] == 3  # untouched


def test_merge_unreadable_slide_routes_to_slide_level(monkeypatch):
    payload = _payload_with([
        {"index": 0, "number": 1, "items": [
            {"index": 0, "kind": "image", "kindIndex": 0, "x": 1, "y": 1, "w": 1, "h": 1},
        ]},
    ])

    monkeypatch.setattr(
        inspect_mod, "inspect_items",
        lambda source, items, counts=None: {0: {"unreadable": True, "records": {}}},
    )

    slide_level_calls = {}

    def fake_merge_slides(payload_arg, source, slide_numbers):
        slide_level_calls["numbers"] = list(slide_numbers)

    # _merge_legacy_items imports _merge_legacy_slides from remap_keynote lazily.
    import obed_edom.remap_keynote as remap_mod
    monkeypatch.setattr(remap_mod, "_merge_legacy_slides", fake_merge_slides)

    unreadable = inspect_mod._merge_legacy_items(
        payload, Path("/x.key"), [{"slide": 1, "kind": "image", "kindIndex": 0}]
    )
    assert unreadable == [1]
    assert slide_level_calls["numbers"] == [1]
    # The unreadable slide's item was left untouched by the item splice.
    assert payload["slides"][0]["items"][0]["x"] == 1


def test_merge_empty_entries_is_a_noop(monkeypatch):
    def boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("inspect_items must not run with no entries")

    monkeypatch.setattr(inspect_mod, "inspect_items", boom)
    assert inspect_mod._merge_legacy_items(_payload_with([]), Path("/x.key"), []) == []


# --------------------------------------------------------------------------
# inspect_items — plan plumbing (osascript stubbed)
# --------------------------------------------------------------------------
def test_inspect_items_builds_plan_and_parses(tmp_path, monkeypatch):
    key = tmp_path / "deck.key"
    key.write_text("stub")
    captured = {}

    def fake_run(args, *a, **kw):
        plan_path = args[-1]
        captured["plan"] = json.loads(Path(plan_path).read_text(encoding="utf-8"))
        out = {"path": str(key), "itemsBySlide": {
            "0": {"unreadable": False, "items": [
                {"kind": "image", "kindIndex": 0, "x": 5, "y": 6, "w": 7, "h": 8},
            ]},
            "4": {"unreadable": True, "items": []},
        }}
        return SimpleNamespace(returncode=0, stdout=json.dumps(out), stderr="")

    monkeypatch.setattr(inspect_mod.subprocess, "run", fake_run)
    result = inspect_mod.inspect_items(
        key,
        [{"slide": 1, "kind": "image", "kindIndex": 0}],
        counts={1: {"image": 1}},
    )
    plan = captured["plan"]
    assert plan["items"] == [{"slide": 1, "kind": "image", "kindIndex": 0}]
    assert plan["counts"] == {"1": {"image": 1}}
    assert plan["textPlaceholderSlack"] == 2
    assert result[0]["unreadable"] is False
    assert result[0]["records"][("image", 0)]["x"] == 5
    assert result[4]["unreadable"] is True


def test_inspect_items_empty_returns_empty(tmp_path, monkeypatch):
    key = tmp_path / "deck.key"
    key.write_text("stub")

    def boom(*a, **k):  # pragma: no cover
        raise AssertionError("osascript must not run for an empty item list")

    monkeypatch.setattr(inspect_mod.subprocess, "run", boom)
    assert inspect_mod.inspect_items(key, []) == {}


# --------------------------------------------------------------------------
# inspect_keynote_checker caller partition
# --------------------------------------------------------------------------
@pytest.fixture()
def checker_deck(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv(CACHE_DIR_ENV, str(tmp_path / "cache"))
    path = tmp_path / "deck.key"
    path.write_bytes(b"checker deck bytes")
    return path


def _seed_offline_build(monkeypatch, fallback):
    """Stub _build_checker_offline to return a payload carrying `fallback`."""
    payload = {
        "slideCount": 2,
        "slides": [
            {"index": 0, "number": 1, "items": [
                {"index": 0, "kind": "image", "kindIndex": 0, "x": 0, "y": 0, "w": 0, "h": 0},
            ]},
            {"index": 1, "number": 2, "items": [
                {"index": 0, "kind": "image", "kindIndex": 0, "x": 0, "y": 0, "w": 0, "h": 0},
            ]},
        ],
        "_offline": {
            "bulk_ok": True,
            "fallback": fallback,
            "fallback_slides": sorted({int(f["slide"]) for f in fallback}),
        },
    }
    monkeypatch.setattr(inspect_mod, "_build_checker_offline", lambda k, fn, log=None: payload)
    return payload


def test_checker_routes_item_addressable_to_item_read(checker_deck, monkeypatch):
    _seed_offline_build(monkeypatch, [
        {"slide": 1, "kind": "image", "kindIndex": 0, "reason": "bulk-missing"},
    ])

    item_calls = {"n": 0}

    def fake_merge_items(payload, source, item_entries):
        item_calls["n"] += 1
        item_calls["entries"] = item_entries
        return []

    monkeypatch.setattr(inspect_mod, "_merge_legacy_items", fake_merge_items)

    import obed_edom.remap_keynote as remap_mod

    def no_slide_level(*a, **k):  # pragma: no cover
        raise AssertionError("a purely item-addressable fallback must not hit slide-level")

    monkeypatch.setattr(remap_mod, "_merge_legacy_slides", no_slide_level)

    out = inspect_mod.inspect_keynote_checker(checker_deck, use_cache=False)
    assert item_calls["n"] == 1
    assert item_calls["entries"] == [{"slide": 1, "kind": "image", "kindIndex": 0}]
    assert out["reader"] == "offline"


def test_checker_routes_count_mismatch_to_slide_level(checker_deck, monkeypatch):
    _seed_offline_build(monkeypatch, [
        {"slide": 2, "kind": "image", "kindIndex": -1, "reason": "count-mismatch"},
    ])

    def no_item_read(*a, **k):  # pragma: no cover
        raise AssertionError("a count-mismatch slide must not be read item-scoped")

    monkeypatch.setattr(inspect_mod, "_merge_legacy_items", no_item_read)

    slide_calls = {"n": 0}

    import obed_edom.remap_keynote as remap_mod

    def fake_slide_level(payload, source, slide_numbers):
        slide_calls["n"] += 1
        slide_calls["numbers"] = list(slide_numbers)

    monkeypatch.setattr(remap_mod, "_merge_legacy_slides", fake_slide_level)

    out = inspect_mod.inspect_keynote_checker(checker_deck, use_cache=False)
    assert slide_calls["n"] == 1
    assert slide_calls["numbers"] == [2]
    assert out["reader"] == "offline"


def test_checker_mixed_fallback_splits_both_paths(checker_deck, monkeypatch):
    _seed_offline_build(monkeypatch, [
        {"slide": 1, "kind": "image", "kindIndex": 0, "reason": "bulk-missing"},
        {"slide": 2, "kind": "image", "kindIndex": -1, "reason": "count-mismatch"},
    ])

    seen = {"items": None, "slides": None}
    monkeypatch.setattr(
        inspect_mod, "_merge_legacy_items",
        lambda payload, source, entries: seen.__setitem__("items", entries) or [],
    )
    import obed_edom.remap_keynote as remap_mod
    monkeypatch.setattr(
        remap_mod, "_merge_legacy_slides",
        lambda payload, source, numbers: seen.__setitem__("slides", list(numbers)),
    )

    inspect_mod.inspect_keynote_checker(checker_deck, use_cache=False)
    assert seen["items"] == [{"slide": 1, "kind": "image", "kindIndex": 0}]
    assert seen["slides"] == [2]


def test_checker_bulk_unavailable_still_falls_whole_deck(checker_deck, monkeypatch):
    # The pre-existing whole-deck path is unchanged: bulk_ok False + fallback_slides
    # -> a full inspect_keynote of the whole deck, never the item read.
    payload = {
        "slideCount": 1,
        "slides": [{"index": 0, "number": 1, "items": []}],
        "_offline": {
            "bulk_ok": False,
            "fallback": [{"slide": 1, "kind": "image", "kindIndex": 0, "reason": "bulk-missing"}],
            "fallback_slides": [1],
        },
    }
    monkeypatch.setattr(inspect_mod, "_build_checker_offline", lambda k, fn, log=None: payload)

    def no_item_read(*a, **k):  # pragma: no cover
        raise AssertionError("bulk-unavailable must go whole-deck, not item-scoped")

    monkeypatch.setattr(inspect_mod, "_merge_legacy_items", no_item_read)

    called = {"n": 0}

    def fake_full(key_path, export_dir=None, use_cache=None):
        called["n"] += 1
        return {"reader": "jxa", "slides": [], "sentinel": "WHOLE_DECK"}

    monkeypatch.setattr(inspect_mod, "inspect_keynote", fake_full)

    out = inspect_mod.inspect_keynote_checker(checker_deck, use_cache=False)
    assert called["n"] == 1
    assert out["sentinel"] == "WHOLE_DECK"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
