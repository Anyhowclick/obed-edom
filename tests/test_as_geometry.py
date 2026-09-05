"""Lock the OBED_AS_GEOMETRY emitter (Option 1.5).

The batched AppleScript geometry block is built in pure Python so it can be
exercised without Keynote. These tests pin the address form (`<kind> N` where
``N`` == kindIndex + 1), the line/group special cases, the locked unlock/relock
scaffold, and the timeout wrapper.

Default ON: no JXA (0,0) yank, ~30% faster (drops setPos readback-verify and
the second position pass). OBED_AS_GEOMETRY=0 forces legacy JXA, also the
per-slide fallback for kinds AppleScript can't address.

Position MUST stay a separate LAST write. Setting height re-anchors ~18px about
the object centre; folding position into an atomic properties record loses that
ordering. Lines have no re-anchor, so endpoints stay one atomic set. A throw on
the combined size record loses both width and height — acceptable because both
are settable on every _AS_KIND_NAMES kind, and the write has its own try.

OBED_SUPPRESS_GEOMETRY: listed non-reuse slides get attrs only (no AS or JXA
geometry). Without it an empty-asGeom slide falls through to JXA full path.
Non-numeric tokens are ignored (typo = suppress nothing).
"""

from __future__ import annotations

from obed_edom.map_remap import ItemTransform
from obed_edom.remap_keynote import (
    GEOM_UNWRITABLE_MARKER,
    _build_as_geometry,
    _build_slide_geometry_script,
    as_geometry_enabled,
    geom_props_enabled,
    suppress_geometry_slides,
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


def test_geom_props_on_by_default(monkeypatch):
    monkeypatch.delenv("OBED_GEOM_PROPS", raising=False)
    assert geom_props_enabled() is True
    for value in ("0", "false", "FALSE", "no", "off"):
        monkeypatch.setenv("OBED_GEOM_PROPS", value)
        assert geom_props_enabled() is False
    for value in ("1", "yes", "on", "", "anything"):
        monkeypatch.setenv("OBED_GEOM_PROPS", value)
        assert geom_props_enabled() is True


# --- addressing & geometry -------------------------------------------------


def test_addresses_kind_index_plus_one():
    script = _build_slide_geometry_script([_spec(kind="text", kindIndex=2)], 5)
    # JXA col[2] == AppleScript element 3.
    assert "set theObj to text item 3" in script
    assert "tell slide 5" in script


def test_sets_size_via_properties_then_position(monkeypatch):
    # Default (OBED_GEOM_PROPS on): width+height fold into ONE `set properties`,
    # position stays a separate LAST write so the height re-anchor is still corrected.
    monkeypatch.delenv("OBED_GEOM_PROPS", raising=False)
    script = _build_slide_geometry_script([_spec(w=300, h=120, x=100, y=200)], 3)
    assert "set properties of theObj to {width:300, height:120}" in script
    assert "set position of theObj to {100, 200}" in script
    assert "set width of theObj to" not in script  # not written separately
    assert script.index("set properties of theObj") < script.index("set position of theObj")


def test_legacy_per_property_writes_when_opted_out(monkeypatch):
    monkeypatch.setenv("OBED_GEOM_PROPS", "0")
    script = _build_slide_geometry_script([_spec(w=300, h=120, x=100, y=200)], 3)
    assert "set width of theObj to 300" in script
    assert "set height of theObj to 120" in script
    assert "set position of theObj to {100, 200}" in script
    assert "set properties of theObj" not in script
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
    # A line has no re-anchor, so its endpoints fold into one atomic `set properties`.
    assert "start point:{10, 20}" in script
    assert "end point:{10, 400}" in script
    assert "set properties of theObj to {start point:{10, 20}, end point:{10, 400}}" in script
    # A line is placed by its endpoints; width/height are never written for it.
    assert "width:" not in script
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
    assert "set properties of theObj to {width:400, height:300}" in script
    assert "set position of theObj to {50, 60}" in script
    assert script.index("set properties of theObj") < script.index("set position of theObj")


# --- locked scaffold -------------------------------------------------------


def test_locked_unlock_relock_wraps_writes():
    script = _build_slide_geometry_script([_spec()], 3)
    assert "if locked of theObj then" in script
    assert "set locked of theObj to false" in script
    assert "if wasLocked then set locked of theObj to true" in script
    # Unlock happens before the geometry writes, relock after.
    assert script.index("set locked of theObj to false") < script.index("set properties of theObj")
    assert script.index("set properties of theObj") < script.index(
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


def test_unwritable_address_logged_instead_of_silently_swallowed():
    script = _build_slide_geometry_script([_spec(kind="image", kindIndex=8)], 96)
    assert "  on error" in script
    assert f'log "{GEOM_UNWRITABLE_MARKER} slide=96 kind=image kindIndex=8"' in script
    assert script.index("set theObj to image 9") < script.index("  on error")


def test_on_error_does_not_wrap_the_relock_tail():
    script = _build_slide_geometry_script([_spec()], 3)
    assert script.index("if wasLocked then set locked of theObj to true") < script.index("  on error")


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


# --- geometry suppression knob (OBED_SUPPRESS_GEOMETRY) --------------------


def test_suppress_geometry_empty_by_default(monkeypatch):
    monkeypatch.delenv("OBED_SUPPRESS_GEOMETRY", raising=False)
    assert suppress_geometry_slides() == set()


def test_suppress_geometry_parses_comma_and_space_lists(monkeypatch):
    monkeypatch.setenv("OBED_SUPPRESS_GEOMETRY", "9")
    assert suppress_geometry_slides() == {9}
    monkeypatch.setenv("OBED_SUPPRESS_GEOMETRY", "1, 9 12")
    assert suppress_geometry_slides() == {1, 9, 12}
    # A non-numeric token degrades to "suppress nothing extra" rather than raising.
    monkeypatch.setenv("OBED_SUPPRESS_GEOMETRY", "9, junk, 3")
    assert suppress_geometry_slides() == {9, 3}


def test_build_as_geometry_omits_suppressed_slide():
    # The plan-facing invariant behind OBED_SUPPRESS_GEOMETRY="9": slide 9 carries
    # NO asGeom body (so applyNonReuseSlide writes it attrs-only), while a sibling
    # non-suppressed slide keeps its body. This is the exact `plan["asGeom"]` map
    # `remap` attaches (remap itself needs Keynote, so the map builder is locked
    # here, mirroring the other _build_as_geometry tests above).
    specs = [
        _spec(slide=9, kind="text", kindIndex=0),
        _spec(slide=10, kind="image", kindIndex=0),
    ]
    out = _build_as_geometry(specs, suppress={9})
    assert "9" not in out  # suppressed: attrs-only, no geometry body
    assert "10" in out  # untouched


def test_build_as_geometry_no_suppress_keeps_all():
    specs = [_spec(slide=9, kind="text", kindIndex=0)]
    assert "9" in _build_as_geometry(specs)  # default suppress set is empty
    assert "9" in _build_as_geometry(specs, suppress=set())


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
    assert "set properties of theObj to {width:200, height:100}" in script
    assert "set position of theObj to {12.34, 56.78}" in script
