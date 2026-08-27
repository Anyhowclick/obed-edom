"""Lock the OBED_AS_GEOMETRY emitter (Option 1.5).

The batched AppleScript geometry block is built in pure Python so it can be
exercised without Keynote. These tests pin the address form (`<kind> N` where
``N`` == kindIndex + 1), the line/group special cases, the locked unlock/relock
scaffold, the timeout wrapper, and that the flag is off by default (so the plan
that reaches JXA is unchanged).
"""

from __future__ import annotations

from obed_edom.map_remap import ItemTransform
from obed_edom.remap_keynote import (
    _build_as_geometry,
    _build_slide_geometry_script,
    as_geometry_enabled,
)


def _spec(**over):
    base = {
        "slide": 3,
        "kind": "text",
        "kindIndex": 0,
        "x": 100,
        "y": 200,
        "w": 300,
        "h": 120,
        "role": "other",
    }
    base.update(over)
    return base


# --- flag ------------------------------------------------------------------


def test_flag_on_by_default(monkeypatch):
    monkeypatch.delenv("OBED_AS_GEOMETRY", raising=False)
    assert as_geometry_enabled() is True


def test_flag_forced_off_values(monkeypatch):
    # AS-geometry is the default; only an explicit off-value falls back to JXA.
    for value in ("0", "false", "FALSE", "no", "off"):
        monkeypatch.setenv("OBED_AS_GEOMETRY", value)
        assert as_geometry_enabled() is False
    for value in ("1", "true", "yes", "on", "", "anything"):
        monkeypatch.setenv("OBED_AS_GEOMETRY", value)
        assert as_geometry_enabled() is True


# --- addressing & geometry -------------------------------------------------


def test_addresses_kind_index_plus_one():
    script = _build_slide_geometry_script([_spec(kind="text", kindIndex=2)], 5)
    # JXA col[2] == AppleScript element 3.
    assert "set theObj to text item 3" in script
    assert "tell slide 5" in script


def test_sets_width_height_position_for_box():
    script = _build_slide_geometry_script([_spec(w=300, h=120, x=100, y=200)], 3)
    assert "set width of theObj to 300" in script
    assert "set height of theObj to 120" in script
    assert "set position of theObj to {100, 200}" in script
    # Position is written after size so the height re-anchor is corrected last.
    assert script.index("set width of theObj") < script.index("set position of theObj")
    assert script.index("set height of theObj") < script.index("set position of theObj")


def test_kind_names_mapped():
    for kind, name in [
        ("text", "text item"),
        ("image", "image"),
        ("shape", "shape"),
        ("movie", "movie"),
        ("group", "group"),
        ("line", "line"),
    ]:
        spec = _spec(kind=kind, kindIndex=0, start=[0, 0], end=[10, 10])
        script = _build_slide_geometry_script([spec], 1)
        assert f"set theObj to {name} 1" in script


def test_unknown_kind_skipped():
    assert _build_slide_geometry_script([_spec(kind="chart")], 1) == ""


# --- lines -----------------------------------------------------------------


def test_line_uses_endpoints_not_width():
    spec = _spec(kind="line", kindIndex=1, start=[10, 20], end=[10, 400], w=380, h=0)
    script = _build_slide_geometry_script([spec], 2)
    assert "set start point of theObj to {10, 20}" in script
    assert "set end point of theObj to {10, 400}" in script
    # A line is placed by its endpoints; width/height are never written for it.
    assert "set width of theObj" not in script
    assert "set height of theObj" not in script


# --- groups ----------------------------------------------------------------


def test_group_gets_full_geometry():
    # There is no child-resize pass on this branch: the JXA full pass this
    # replaces was the only writer of a group's (wall-sized) frame, so the AS block
    # must set width AND height AND position, exactly like any other object.
    spec = _spec(kind="group", kindIndex=0, x=50, y=60, w=400, h=300)
    script = _build_slide_geometry_script([spec], 4)
    assert "set theObj to group 1" in script
    assert "set width of theObj to 400" in script
    assert "set height of theObj to 300" in script
    assert "set position of theObj to {50, 60}" in script
    assert script.index("set width of theObj") < script.index("set position of theObj")


# --- locked scaffold -------------------------------------------------------


def test_locked_unlock_relock_wraps_writes():
    script = _build_slide_geometry_script([_spec()], 3)
    assert "if locked of theObj then" in script
    assert "set locked of theObj to false" in script
    assert "if wasLocked then set locked of theObj to true" in script
    # Unlock happens before the geometry writes, relock after.
    assert script.index("set locked of theObj to false") < script.index("set width of theObj")
    assert script.index("set width of theObj") < script.index(
        "if wasLocked then set locked of theObj to true"
    )


# --- hide / empty ----------------------------------------------------------


def test_hide_role_skipped():
    hide = _spec(role="hide", kindIndex=7)
    keep = _spec(role="other", kindIndex=1)
    script = _build_slide_geometry_script([hide, keep], 3)
    assert "text item 8" not in script  # the hide (index 7) is never addressed
    assert "text item 2" in script  # the kept object (index 1) is


def test_empty_specs_yield_empty_string():
    assert _build_slide_geometry_script([], 3) == ""
    assert _build_slide_geometry_script([_spec(role="hide")], 3) == ""


# --- timeout wrapper -------------------------------------------------------


def test_timeout_wrapper_present():
    script = _build_slide_geometry_script([_spec()], 3)
    assert script.startswith("with timeout of 3600 seconds")
    assert script.rstrip().endswith("end timeout")


# --- per-slide grouping ----------------------------------------------------


def test_build_as_geometry_keys_by_slide():
    specs = [
        _spec(slide=3, kindIndex=0),
        _spec(slide=3, kindIndex=1),
        _spec(slide=5, kindIndex=0),
    ]
    out = _build_as_geometry(specs)
    assert set(out) == {"3", "5"}
    assert "text item 1" in out["3"] and "text item 2" in out["3"]
    assert "tell slide 3" in out["3"]
    assert "tell slide 5" in out["5"]


def test_build_as_geometry_drops_slideless_and_empty():
    specs = [_spec(slide=0), _spec(slide=4, role="hide")]
    assert _build_as_geometry(specs) == {}


# --- per-slide eligibility for unaddressable kinds -------------------------


def test_slide_with_unaddressable_kind_excluded():
    # "table" is not AppleScript-addressable here; a whole slide carrying a
    # geometry-bearing one falls back to the JXA full path (no key emitted),
    # while a sibling slide of only addressable kinds is still included.
    specs = [
        _spec(slide=3, kind="text", kindIndex=0),
        _spec(slide=3, kind="table", kindIndex=0),
        _spec(slide=6, kind="image", kindIndex=0),
    ]
    out = _build_as_geometry(specs)
    assert "3" not in out  # excluded: table has no AS address
    assert "6" in out  # included: all addressable


def test_generic_item_kind_excludes_slide():
    # map_remap emits `item.get("kind") or "item"`, so a bare "item" can appear.
    specs = [_spec(slide=2, kind="item", kindIndex=0)]
    assert _build_as_geometry(specs) == {}


def test_unaddressable_kind_without_geometry_does_not_exclude():
    # A non-hide, non-geometry transform of an unaddressable kind is harmless: JXA
    # would not move it either, so it must not force the whole slide off the path.
    specs = [
        _spec(slide=5, kind="text", kindIndex=0),
        {"slide": 5, "kind": "table", "kindIndex": 0, "role": "other"},  # no x/y/w/h
    ]
    out = _build_as_geometry(specs)
    assert "5" in out
    assert "set theObj to text item 1" in out["5"]


# --- integration with the real transform dict ------------------------------


def test_reads_itemtransform_as_dict():
    t = ItemTransform(
        slide_number=2,
        item_index=4,
        kind="image",
        x=12.34,
        y=56.78,
        w=200.0,
        h=100.0,
        kind_index=3,
        role="map",
    )
    script = _build_slide_geometry_script([t.as_dict()], t.slide_number)
    assert "set theObj to image 4" in script  # kind_index 3 -> element 4
    assert "set width of theObj to 200" in script
    assert "set position of theObj to {12.34, 56.78}" in script
