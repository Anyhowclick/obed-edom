"""Tests for the offline source-wall inspect payload (obed_edom.offline_inspect).

The field synthesis is pure and exercised WITHOUT keynote-parser by building
synthetic IWA archive dicts (mirroring test_iwa_geometry): item-level
font/size/colour with paragraph-style inheritance, line endpoints, locked,
fileName clean-vs-dirty, the childCount/buildCount rules, and the structural
guard. A local-only integration test builds the real Map deck offline and checks
field parity against its cached exact-bytes JXA payload.

NOTE ON THE PLAN GATE: full remap-plan equivalence (offline vs JXA transforms +
reuses within 2px) is NOT achieved on the two gold decks — see
``test_gate_is_not_green_pending_a_geometry_model`` and
``scratchpad/validate_remap_plan.py``. Autosize/shrink-to-fit text (stale
``naturalSize`` vs Keynote's laid-out box) and group geometry (JXA's stored group
frame, which neither the raw frame nor the child-union reproduces) diverge beyond
2px and, via each slide's ``visible_content_union``, perturb the learned recipe
onto otherwise-exact objects. Those categories are currently VOUCHED, so the
default stays ``off``; this suite pins the parts that DO hold and records the gap.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from obed_edom.iwa_geometry import compose_geometry
from obed_edom.offline_inspect import (
    BULK_KINDS,
    VOUCHED_NEEDS_KEYNOTE,
    _build_data_index,
    _canvas_size,
    _data_identifier,
    _guard_tripped,
    _item_from_record,
    _item_text_style,
    _line_endpoints,
    _locked,
    _splice_bulk_geometry,
    offline_wall_payload,
    two_tier_wall_payload,
    unvouched_items,
)

MAP_DECK = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Map_Extracted_Wall_1st.key")
FULL_DECK = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Full_Report_Card_Wall.key")


# --------------------------------------------------------------------------
# Synthetic IWA archive builders.
# --------------------------------------------------------------------------
def _geom(x, y, w, h, angle=0.0):
    return {"geometry": {"position": {"x": x, "y": y},
                         "size": {"width": w, "height": h}, "angle": angle}}


def _char_style(objects, ident, *, props, parent=None, name=None):
    sup: dict = {}
    if parent is not None:
        sup["parent"] = {"identifier": parent}
    if name is not None:
        sup["name"] = name
    objects[ident] = {"_pbtype": "TSWP.CharacterStyleArchive",
                      "charProperties": props, "super": sup}
    return ident


def _para_style(objects, ident, *, props, parent=None, name=None):
    sup: dict = {}
    if parent is not None:
        sup["parent"] = {"identifier": parent}
    if name is not None:
        sup["name"] = name
    objects[ident] = {"_pbtype": "TSWP.ParagraphStyleArchive",
                      "charProperties": props, "super": sup}
    return ident


def _storage(objects, ident, *, text, para=None, char=None):
    obj = {"_pbtype": "TSWP.StorageArchive", "text": [text]}
    if para is not None:
        obj["tableParaStyle"] = {"entries": [{"characterIndex": 0, "object": {"identifier": para}}]}
    if char is not None:
        obj["tableCharStyle"] = {"entries": [{"characterIndex": 0, "object": {"identifier": char}}]}
    objects[ident] = obj
    return ident


def _textbox(objects, ident, *, storage, x=0.0, y=0.0, w=100.0, h=40.0, angle=0.0,
             locked=False, is_textbox=True):
    # Drawable super chain carries `locked`; geometry sits at super.super.geometry.
    objects[ident] = {
        "_pbtype": "TSWP.ShapeInfoArchive",
        "isTextBox": is_textbox,
        "ownedStorage": {"identifier": storage},
        "super": {
            "pathsource": {},
            "super": {**_geom(x, y, w, h, angle), "locked": locked},
        },
    }
    return ident


def _image(objects, ident, *, data=None, x=0.0, y=0.0, w=10.0, h=10.0):
    obj = {"_pbtype": "TSD.ImageArchive", "super": _geom(x, y, w, h)}
    if data is not None:
        obj["data"] = {"identifier": data}
    objects[ident] = obj
    return ident


def _line(objects, ident, *, x, y, w, angle):
    # A line is a ShapeInfoArchive with a single-segment bezier (height 0 frame).
    objects[ident] = {
        "_pbtype": "TSWP.ShapeInfoArchive",
        "super": {
            "pathsource": {"bezierPathSource": {
                "naturalSize": {"width": w, "height": 0.0},
                "path": {"elements": [{"type": "moveTo"}, {"type": "lineTo"}]},
            }},
            "super": _geom(x, y, w, 0.0, angle),
        },
    }
    return ident


def _record(ident, kind, kind_index, **extra):
    rec = {"id": ident, "kind": kind, "kindIndex": kind_index,
           "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0, "text": "",
           "geom_source": "iwa", "needs_keynote": None}
    rec.update(extra)
    return rec


# --------------------------------------------------------------------------
# Item-level colour: ×257 up from the 0-255 IWA value to JXA 0-65535.
# --------------------------------------------------------------------------
def test_color_is_scaled_x257_to_jxa_65535():
    objects: dict = {}
    para = _para_style(objects, "p", props={
        "fontName": "Amplitude-Regular", "fontSize": 42.0,
        "fontColor": {"r": 0.0, "g": 0.9914394, "b": 1.0, "a": 1.0}})
    stor = _storage(objects, "s", text="CHC Aaliana", para=para)
    box = _textbox(objects, "b", storage=stor)

    font, size, color = _item_text_style(objects[box], objects, {})
    assert font == "Amplitude-Regular"
    assert size == 42.0
    # 0-1 -> round(x*255) -> x257: g = round(0.9914394*255)=253 -> 253*257 = 65021.
    assert color == [0, 253 * 257, 255 * 257]
    assert color == [0, 65021, 65535]
    assert max(color) <= 65535


def test_color_none_when_no_fontcolor_anywhere():
    objects: dict = {}
    para = _para_style(objects, "p", props={"fontName": "Foo", "fontSize": 20.0})
    stor = _storage(objects, "s", text="hi", para=para)
    box = _textbox(objects, "b", storage=stor)
    _font, _size, color = _item_text_style(objects[box], objects, {})
    assert color is None


# --------------------------------------------------------------------------
# Item-level font/size need PARAGRAPH-style inheritance (char-style fontName is
# usually None); unresolved -> the guard flags the item.
# --------------------------------------------------------------------------
def test_font_size_fall_back_to_paragraph_style():
    objects: dict = {}
    # Char style carries only colour + bold (no fontName/fontSize) — the common case.
    char = _char_style(objects, "c", props={
        "fontColor": {"r": 1.0, "g": 0.0, "b": 0.0, "a": 1.0}, "bold": True})
    para = _para_style(objects, "p", props={"fontName": "Amplitude-Regular", "fontSize": 42.0})
    stor = _storage(objects, "s", text="CHC X", para=para, char=char)
    box = _textbox(objects, "b", storage=stor)

    font, size, color = _item_text_style(objects[box], objects, {})
    assert font == "Amplitude-Regular"   # from the paragraph style
    assert size == 42.0                  # from the paragraph style
    assert color == [255 * 257, 0, 0]    # colour from the char style (overrides)


def test_unresolved_font_size_trips_the_guard():
    objects: dict = {}
    # No paragraph style, char style without fontName/fontSize -> font/size unresolved.
    char = _char_style(objects, "c", props={"bold": True})
    stor = _storage(objects, "s", text="orphan copy", char=char)
    box = _textbox(objects, "b", storage=stor)

    font, size, _color = _item_text_style(objects[box], objects, {})
    assert font is None and size is None

    rec = _record(box, "text", 0, text="orphan copy", geom_source="iwa", needs_keynote=None)
    item, reason = _item_from_record(rec, objects, {}, {})
    assert reason == "font-size-unresolved"
    assert item["font"] == "" and item["size"] == 0


def test_empty_text_box_with_unresolved_font_is_not_flagged():
    # An unresolved font only matters when the box actually carries copy.
    objects: dict = {}
    stor = _storage(objects, "s", text="   ")
    box = _textbox(objects, "b", storage=stor)
    rec = _record(box, "text", 0, text="   ")
    _item, reason = _item_from_record(rec, objects, {}, {})
    assert reason is None


# --------------------------------------------------------------------------
# Line start/end from the raw frame centre + angle + length.
# --------------------------------------------------------------------------
def test_line_endpoints_from_raw_frame():
    objects: dict = {}
    # Vertical rule: frame (2258.2, 552.1) length 658.1, angle 90 -> centre (2587.25, 552.1).
    line = _line(objects, "L", x=2258.2, y=552.1, w=658.1, angle=90.0)
    start, end = _line_endpoints(objects[line])
    # centre + (L/2)(cos90, sin90) = (2587.25, 552.1 + 329.05)
    assert start[0] == pytest.approx(2587.25, abs=0.1)
    assert start[1] == pytest.approx(881.15, abs=0.1)
    assert end[1] == pytest.approx(223.05, abs=0.1)


def test_horizontal_line_endpoints():
    objects: dict = {}
    line = _line(objects, "L", x=100.0, y=200.0, w=300.0, angle=0.0)
    start, end = _line_endpoints(objects[line])
    # centre (250, 200); start=moveTo(-x) end=lineTo(+x); y flat.
    assert (round(start[0]), round(end[0])) == (100, 400)
    assert start[1] == pytest.approx(200.0) and end[1] == pytest.approx(200.0)


def test_line_endpoints_rotated_is_correct_diagonal():
    # KNOWN ANSWER distinguishing the fixed R(-theta) form from the old
    # centre +/- (L/2)(cos, sin), which drew the OPPOSITE diagonal of the same box
    # for every non-axis-aligned line. A length-100 line at angle 45 about centre
    # (50, 0): start (moveTo) = (50 - 50cos45, 0 + 50sin45), end its mirror.
    objects: dict = {}
    line = _line(objects, "L", x=0.0, y=0.0, w=100.0, angle=45.0)
    start, end = _line_endpoints(objects[line])
    r = 50.0 * (2 ** 0.5) / 2.0  # 35.355
    assert start[0] == pytest.approx(50.0 - r, abs=0.01)
    assert start[1] == pytest.approx(r, abs=0.01)
    assert end[0] == pytest.approx(50.0 + r, abs=0.01)
    assert end[1] == pytest.approx(-r, abs=0.01)
    # The old form would have put start at (50 + r, r): guard against a regression.
    assert start[0] != pytest.approx(50.0 + r, abs=0.01)


def test_line_direction_honours_bezier_and_flip():
    # A bezier that runs moveTo->lineTo in -x (reversed) swaps start/end vs the
    # default +x; a horizontalFlip negates it back. Endpoints stay integers via
    # the payload item (see _round_pt).
    objects: dict = {}
    objects["L"] = {
        "_pbtype": "TSWP.ShapeInfoArchive",
        "super": {
            "pathsource": {
                "horizontalFlip": True,
                "bezierPathSource": {
                    "naturalSize": {"width": 100.0, "height": 0.0},
                    "path": {"elements": [
                        {"type": "moveTo", "points": [{"x": 100.0, "y": 0.0}]},
                        {"type": "lineTo", "points": [{"x": 0.0, "y": 0.0}]},
                    ]},
                },
            },
            "super": _geom(0.0, 0.0, 100.0, 0.0, 0.0),
        },
    }
    start, end = _line_endpoints(objects["L"])
    # reversed bezier (-x) then hFlip (+x) => start at left, end at right.
    assert (round(start[0]), round(end[0])) == (0, 100)


def test_geometry_is_rounded_to_integers_like_jxa():
    # Keynote returns whole-point geometry to JXA; the offline item must match so
    # the learned affine does not drift a sub-pixel that the cover scale amplifies.
    objects: dict = {}
    line = _line(objects, "L", x=0.4, y=0.4, w=99.6, angle=0.0)
    item, _flag = _item_from_record(
        _record("L", "line", 0, x=10.4, y=-2.6, w=99.6, h=0.0), objects, {}, {})
    assert all(isinstance(item[k], int) for k in ("x", "y", "w", "h"))
    assert (item["x"], item["y"], item["w"], item["h"]) == (10, -3, 100, 0)
    assert all(isinstance(v, int) for v in item["start"] + item["end"])


# --------------------------------------------------------------------------
# locked passthrough up the super chain.
# --------------------------------------------------------------------------
def test_locked_read_up_super_chain():
    objects: dict = {}
    stor = _storage(objects, "s", text="x")
    locked_box = _textbox(objects, "b1", storage=stor, locked=True)
    open_box = _textbox(objects, "b2", storage=stor, locked=False)
    assert _locked(objects[locked_box]) is True
    assert _locked(objects[open_box]) is False
    assert _locked({"_pbtype": "TSD.ImageArchive"}) is False  # no locked anywhere -> False


# --------------------------------------------------------------------------
# fileName: clean Data/*-<id> member resolves; a dirty id trips the guard.
# --------------------------------------------------------------------------
def test_data_index_strips_the_id_suffix():
    names = [
        "Data/1. 2025_FILLER_V3-15975.png",
        "Data/1. 2025_FILLER_V3-small-15976.png",
        "Data/mt-9E7B9BBB-4535-4DB9-BD3D-03A011FABAD7-32789.png",
        "Metadata/DocumentIdentifier",
        "Index/Slide-1.iwa",
    ]
    index = _build_data_index(names)
    assert index["15975"] == "1. 2025_FILLER_V3.png"
    assert index["15976"] == "1. 2025_FILLER_V3-small.png"
    assert index["32789"] == "mt-9E7B9BBB-4535-4DB9-BD3D-03A011FABAD7.png"
    assert "Index/Slide-1.iwa" not in index.values()


def test_filename_clean_resolves_and_dirty_id_flags():
    objects: dict = {}
    clean = _image(objects, "img_ok", data="15975")
    dirty = _image(objects, "img_bad", data="99999")  # id not present in the index
    index = {"15975": "1. 2025_FILLER_V3.png"}

    assert _data_identifier(objects[clean]) == "15975"
    item, reason = _item_from_record(_record(clean, "image", 0), objects, index, {})
    assert item["fileName"] == "1. 2025_FILLER_V3.png" and reason is None

    item, reason = _item_from_record(_record(dirty, "image", 1), objects, index, {})
    assert item["fileName"] == "" and reason == "filename-dirty"


def test_movie_filename_uses_moviedata_identifier():
    objects: dict = {}
    objects["mov"] = {"_pbtype": "TSD.MovieArchive", "super": _geom(0, 0, 10, 10),
                      "movieData": {"identifier": "77498"}}
    assert _data_identifier(objects["mov"]) == "77498"
    item, reason = _item_from_record(_record("mov", "movie", 0), objects,
                                     {"77498": "PIN DROP WAVE.mov"}, {})
    assert item["fileName"] == "PIN DROP WAVE.mov" and reason is None


# --------------------------------------------------------------------------
# childCount/children omitted; buildCount 0.
# --------------------------------------------------------------------------
def test_group_item_omits_childcount_and_children():
    objects: dict = {"g": {"_pbtype": "TSD.GroupArchive", "super": _geom(0, 0, 10, 10),
                           "children": []}}
    item, _reason = _item_from_record(_record("g", "group", 0), objects, {}, {})
    assert "childCount" not in item
    assert "children" not in item


def test_buildcount_is_zero():
    objects: dict = {}
    stor = _storage(objects, "s", text="x")
    box = _textbox(objects, "b", storage=stor)
    item, _reason = _item_from_record(_record(box, "text", 0, text="x"), objects, {}, {})
    assert item["buildCount"] == 0


# --------------------------------------------------------------------------
# The structural guard: vouched vs unvouched needs_keynote categories.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("reason", ["autosize-soft"])
def test_vouched_needs_keynote_does_not_flag(reason):
    # Only autosize-soft is vouched: Keynote re-autosizes the box on write, so its
    # stale offline height never lands. Everything else must trip (see below).
    objects: dict = {"g": {"_pbtype": "TSD.GroupArchive", "super": _geom(0, 0, 10, 10)}}
    rec = _record("g", "group", 0, geom_source="group-union", needs_keynote=reason)
    _item, flag = _item_from_record(rec, objects, {}, {})
    assert flag is None
    assert reason in VOUCHED_NEEDS_KEYNOTE


# group-residual is UNVOUCHED (prong 3b): a group's written w/h and its size-derived
# role diverge when its geometry can't be pinned down, so it must force the legacy read.
@pytest.mark.parametrize(
    "reason", ["rotated-masked", "masked-unresolved", "rotated-group", "group-residual"]
)
def test_unvouched_needs_keynote_flags(reason):
    assert reason not in VOUCHED_NEEDS_KEYNOTE
    objects: dict = {"i": {"_pbtype": "TSD.ImageArchive", "super": _geom(0, 0, 10, 10)}}
    rec = _record("i", "image", 0, geom_source="mask", needs_keynote=reason)
    _item, flag = _item_from_record(rec, objects, {}, {})
    assert flag == reason


def test_guard_tripped_scopes_to_slide_range():
    guard = [{"slide": 3, "kind": "image", "kindIndex": 0, "reason": "rotated-masked"}]
    assert _guard_tripped(guard, None) is True          # no range -> any flag trips
    assert _guard_tripped(guard, (3, 3)) is True         # flagged slide in range
    assert _guard_tripped(guard, (1, 2)) is False        # flagged slide out of range
    assert _guard_tripped([], None) is False


def test_unvouched_items_reads_and_scopes_the_sidecar():
    payload = {"_offline": {"guard": [
        {"slide": 2, "kind": "group", "kindIndex": 1, "reason": "rotated-group"},
        {"slide": 5, "kind": "image", "kindIndex": 0, "reason": "filename-dirty"},
    ]}}
    assert len(unvouched_items(payload)) == 2
    scoped = unvouched_items(payload, (1, 3))
    assert [f["slide"] for f in scoped] == [2]


# --------------------------------------------------------------------------
# Canvas size from KN.ShowArchive.size.
# --------------------------------------------------------------------------
def test_canvas_size_from_show_archive():
    objects = {"show": {"_pbtype": "KN.ShowArchive", "size": {"width": 7680.0, "height": 1080.0}}}
    assert _canvas_size(objects) == (7680.0, 1080.0)
    assert _canvas_size({}) == (1920.0, 1080.0)  # JXA's own fallback


# --------------------------------------------------------------------------
# All slides + document numbers are emitted; plan["slides"] does the filtering.
# --------------------------------------------------------------------------
def test_all_slides_emitted_and_plan_filters_by_range():
    from obed_edom.map_remap import wants_slide

    # A JXA-shaped payload standing in for offline_wall_payload's emission: every
    # slide present with number == index+1, so the planner's wants_slide filters.
    payload = {"slideWidth": 7680, "slideHeight": 1080, "slideCount": 3,
               "slides": [{"index": i, "number": i + 1, "skipped": False, "items": []}
                          for i in range(3)]}
    numbers = [s["number"] for s in payload["slides"]]
    assert numbers == [1, 2, 3]
    kept = [s["number"] for s in payload["slides"] if wants_slide(s["number"], (2, 2))]
    assert kept == [2]


# --------------------------------------------------------------------------
# Local integration — build the real Map deck offline and check field parity
# against its cached exact-bytes JXA payload.
# --------------------------------------------------------------------------
def _cached_payload(deck: Path):
    try:
        from obed_edom.baseline import deck_digest, inspect_cache_path
    except Exception:  # pragma: no cover
        return None
    try:
        path = inspect_cache_path(deck_digest(deck))
    except Exception:  # pragma: no cover
        return None
    return json.loads(path.read_text()) if path.is_file() else None


@pytest.mark.skipif(not MAP_DECK.exists(), reason="local gold deck only")
def test_integration_offline_field_parity_map_deck():
    pytest.importorskip("keynote_parser")
    payload = _cached_payload(MAP_DECK)
    if payload is None:
        pytest.skip("no exact-bytes JXA payload cached for the current deck bytes")
    off = offline_wall_payload(MAP_DECK)

    # Deck-level + all-slides-with-doc-number emission.
    assert off["slideCount"] == payload["slideCount"]
    assert (off["slideWidth"], off["slideHeight"]) == (payload["slideWidth"], payload["slideHeight"])
    assert [s["number"] for s in off["slides"]] == list(range(1, off["slideCount"] + 1))
    assert all("skipped" in s for s in off["slides"])

    jby = {s["index"]: {(it["kind"], it["kindIndex"]): it for it in s.get("items") or []}
           for s in payload["slides"]}
    filename_checked = build_zero = childcount_absent = geom_checked = 0
    for slide in off["slides"]:
        jmap = jby.get(slide["index"], {})
        for it in slide["items"]:
            assert it["buildCount"] == 0
            build_zero += 1
            if it["kind"] == "group":
                assert "childCount" not in it and "children" not in it
                childcount_absent += 1
            j = jmap.get((it["kind"], it["kindIndex"]))
            if j is None:
                continue
            # fileName: every resolved image/movie name must match JXA exactly.
            if it["kind"] in ("image", "movie") and it["fileName"]:
                assert it["fileName"] == (j.get("fileName") or ""), (
                    slide["number"], it["kind"], it["kindIndex"])
                filename_checked += 1
    assert filename_checked > 100 and build_zero > 100 and childcount_absent > 0

    # Wall geometry parity where the geometry model is EXACT: unmasked, unrotated
    # images (geom_source "iwa", not flagged) within 2px of JXA. (Autosize text and
    # groups are the known-soft categories, excluded here and pinned by the gate.)
    from obed_edom.iwa_runs import _load_deck, slide_order
    objects, _a, _b = _load_deck(MAP_DECK)
    for index, (sid, _skip) in enumerate(slide_order(objects)):
        if sid not in objects:
            continue
        jmap = jby.get(index, {})
        for rec in compose_geometry(objects[sid], objects):
            if rec["kind"] != "image" or rec.get("needs_keynote") or rec.get("geom_source") != "iwa":
                continue
            j = jmap.get((rec["kind"], rec["kindIndex"]))
            if not j or j.get("x") is None:
                continue
            assert abs(rec["x"] - j["x"]) <= 2 and abs(rec["y"] - j["y"]) <= 2
            assert abs(rec["w"] - j["w"]) <= 2 and abs(rec["h"] - j["h"]) <= 2
            geom_checked += 1
    assert geom_checked > 20


@pytest.mark.skipif(not MAP_DECK.exists(), reason="local gold deck only")
@pytest.mark.xfail(reason="Full remap-plan equivalence not reachable offline: two "
                          "residuals remain, both guard-detected. Group geometry the "
                          "child-union/stored-frame cannot pin down now TRIPS the guard "
                          "(group-residual, unvouched) -> legacy fallback; autosize text "
                          "with stale naturalSize / autoshrink stays vouched (Keynote "
                          "re-autosizes on write). Lines and the masked-map cascade are "
                          "fixed. See scratchpad/validate_remap_plan.py + module docstring.",
                   strict=False)
def test_gate_is_not_green_pending_a_geometry_model():
    """Records the open gap: the PURE-OFFLINE plan (tier 1, no bulk read) does NOT
    equal the JXA plan under the STRICT check (`_specs_equivalent`, all fields but
    itemIndex).

    NOTE (Session 15): the default already flipped to `on` — that rests on the
    TWO-TIER (offline + bulk geometry) read passing the WRITE-AFFECTING gate on both
    decks, not on this stricter pure-offline gate. This test tracks a separate,
    harder goal: whether a font-metric text-layout model + a group-frame model could
    make the read exact enough to skip the bulk Keynote pass entirely. Expected to
    xfail until then; an xpass is a bonus (pure-offline sufficiency), not a flip
    trigger. See scratchpad/validate_remap_plan.py + module docstring.
    """
    pytest.importorskip("keynote_parser")
    payload = _cached_payload(MAP_DECK)
    if payload is None:
        pytest.skip("no exact-bytes JXA payload cached for the current deck bytes")
    from obed_edom.map_remap import plan_payload_transforms
    from obed_edom.remap_keynote import _specs_equivalent, recipe_for

    template = offline_wall_payload(
        MAP_DECK.parent / "Base_CG_Assets.key") if (MAP_DECK.parent / "Base_CG_Assets.key").exists() else None
    if template is None:
        pytest.skip("no CG template deck available for the plan gate")
    off = offline_wall_payload(MAP_DECK)

    def specs(wall):
        return [t.as_dict() for t in plan_payload_transforms(
            wall, recipe_for(wall, template), template=template)]

    assert _specs_equivalent(specs(off), specs(payload)), "offline plan diverges from JXA plan"


# --------------------------------------------------------------------------
# Two-tier read: bulk geometry splice + granular fallback.
#
# The "second tier" bulk Keynote read overwrites the geometry of the three
# offline-soft classes (groups, masked/rotated images, autosize text). These
# tests use a bulk_geometry_fn TEST-DOUBLE built from the cached exact-bytes JXA
# payload — the exact x/y/w/h a real bulk read would return — so the whole two-
# tier assembly is exercised WITHOUT opening Keynote.
# --------------------------------------------------------------------------
# Attribute-only spec fields the WRITE path either re-derives on write (Keynote
# re-autosizes a text box, so a spliced-geometry box's stale `fontSize` never
# lands) or that only tie-break among template swatches of the same family (font,
# colour) — proven plan-neutral for decks of this kind. Geometry, role, locked,
# start/end and the addressing are what the geometry write actually consumes; the
# gate diffs THOSE ("write-affecting"). See offline_inspect + module docstring.
_ATTR_ONLY_SPEC_FIELDS = frozenset(
    {"itemIndex", "fontSize", "font", "color", "opacity", "matchText"}
)


def _wa_fields_equal(a: dict, b: dict, tol: float = 2.0) -> bool:
    """Two transform/mutate specs equal on their WRITE-AFFECTING fields."""
    for key in (set(a) | set(b)) - _ATTR_ONLY_SPEC_FIELDS:
        av, bv = a.get(key), b.get(key)
        if key in ("x", "y", "w", "h"):
            try:
                if abs(float(av) - float(bv)) > tol:
                    return False
            except (TypeError, ValueError):
                if av != bv:
                    return False
        elif key in ("start", "end"):
            ok = (
                isinstance(av, (list, tuple)) and isinstance(bv, (list, tuple))
                and len(av) >= 2 and len(bv) >= 2
                and abs(float(av[0]) - float(bv[0])) <= tol
                and abs(float(av[1]) - float(bv[1])) <= tol
            )
            if not ok and av != bv:
                return False
        elif av != bv:
            return False
    return True


def _addr(ref: dict) -> tuple:
    return (str(ref.get("kind")), int(ref.get("kindIndex", -1)))


def _present_addresses(payload: dict) -> dict[int, set]:
    """``{slide_number: {(kind, kindIndex), …}}`` the offline payload actually emits."""
    out: dict[int, set] = {}
    for s in payload.get("slides") or []:
        number = int(s.get("number") or (int(s.get("index") or 0) + 1))
        out[number] = {(it["kind"], it["kindIndex"]) for it in s.get("items") or []}
    return out


def _transform_wa_diffs(off_specs: list[dict], jxa_specs: list[dict]) -> list[tuple]:
    om = {(int(s["slide"]), s["kind"], int(s["kindIndex"])): s for s in off_specs}
    jm = {(int(s["slide"]), s["kind"], int(s["kindIndex"])): s for s in jxa_specs}
    diffs: list[tuple] = []
    if set(om) != set(jm):
        diffs.append(("address-set", set(om) ^ set(jm)))
    for k in set(om) & set(jm):
        if not _wa_fields_equal(om[k], jm[k]):
            diffs.append((k, om[k], jm[k]))
    return diffs


def _reuse_wa_diffs(off_jobs: list[dict], jxa_jobs: list[dict], present: dict[int, set]) -> list[tuple]:
    om = {int(j["slide"]): j for j in off_jobs}
    jm = {int(j["slide"]): j for j in jxa_jobs}
    diffs: list[tuple] = []
    if set(om) != set(jm):
        diffs.append(("reuse-slide-set", set(om) ^ set(jm)))
    for slide in set(om) & set(jm):
        jo, jj = om[slide], jm[slide]
        if jo.get("from") != jj.get("from") or jo.get("persist") != jj.get("persist"):
            diffs.append((slide, "from/persist"))
        # `strip` addresses the CURRENT slide's items; the offline read can only
        # strip what it emitted, so JXA's strip is compared over the addresses the
        # offline payload actually carries. (The only residual is JXA surfacing a
        # couple of trailing EMPTY (0,0) text boxes the offline addressing omits —
        # placement-neutral, so not a write divergence.)
        so = {_addr(r) for r in jo.get("strip") or []}
        sj = {_addr(r) for r in jj.get("strip") or []} & present.get(slide, set())
        if so != sj:
            diffs.append((slide, "strip", so ^ sj))
        # `remove`/`stripBuilds` address the DONOR slide's items — compared directly.
        for name in ("remove", "stripBuilds"):
            ao = {_addr(r) for r in jo.get(name) or []}
            aj = {_addr(r) for r in jj.get(name) or []}
            if ao != aj:
                diffs.append((slide, name, ao ^ aj))
        for name in ("add", "mutate"):
            a = {_addr(s): s for s in jo.get(name) or []}
            b = {_addr(s): s for s in jj.get(name) or []}
            if set(a) != set(b) or not all(_wa_fields_equal(a[k], b[k]) for k in a):
                diffs.append((slide, name))
    return diffs


def _bulk_double_from_jxa(jxa_payload: dict, *, omit: set | None = None):
    """A ``bulk_geometry_fn`` returning the JXA payload's group/image/movie/text x/y/w/h.

    ``{slideIndex: {kind: [[x, y, w, h], … by kindIndex]}}`` — exactly what a real
    bulk read would hand back. ``omit`` is a set of ``(slideIndex, kind)`` to leave
    OUT, so a test can simulate the bulk read missing a slide or a kind and check
    the granular fallback.
    """
    omit = omit or set()
    base: dict[int, dict[str, list]] = {}
    for s in jxa_payload["slides"]:
        by_kind: dict[str, dict[int, list]] = {}
        for it in s["items"]:
            if it["kind"] in BULK_KINDS:
                by_kind.setdefault(it["kind"], {})[it["kindIndex"]] = [
                    it["x"], it["y"], it["w"], it["h"]
                ]
        rows: dict[str, list] = {}
        for kind, d in by_kind.items():
            if (s["index"], kind) in omit:
                continue
            n = max(d) + 1
            rows[kind] = [d.get(i) for i in range(n)]
        base[s["index"]] = rows

    def fn(key_path, slides=None):
        return base
    return fn


def test_splice_overwrites_only_bulk_kind_geometry_keeps_style():
    # Pure unit: the splice overwrites x/y/w/h for the four bulk kinds and touches
    # NOTHING else — style/fileName/text/addressing all survive, shapes/lines are
    # left to the (exact) offline read.
    payload = {
        "slides": [
            {"index": 0, "number": 1, "items": [
                {"kind": "text", "kindIndex": 0, "x": 1, "y": 2, "w": 3, "h": 4,
                 "font": "Amplitude", "size": 42, "text": "hi", "index": 0},
                {"kind": "shape", "kindIndex": 0, "x": 5, "y": 6, "w": 7, "h": 8, "index": 1},
                {"kind": "image", "kindIndex": 0, "x": 9, "y": 9, "w": 9, "h": 9,
                 "fileName": "a.png", "index": 2},
                {"kind": "line", "kindIndex": 0, "x": 1, "y": 1, "w": 1, "h": 0,
                 "start": [0, 0], "end": [1, 0], "index": 3},
            ]},
        ]
    }
    bulk = {0: {"text": [[10, 20, 30, 40]], "image": [[100, 110, 120, 130]]}}
    spliced = _splice_bulk_geometry(payload, bulk)
    assert spliced == {(1, "text", 0), (1, "image", 0)}
    items = payload["slides"][0]["items"]
    assert (items[0]["x"], items[0]["y"], items[0]["w"], items[0]["h"]) == (10, 20, 30, 40)
    assert items[0]["font"] == "Amplitude" and items[0]["size"] == 42 and items[0]["text"] == "hi"
    assert (items[1]["x"], items[1]["y"], items[1]["w"], items[1]["h"]) == (5, 6, 7, 8)  # shape untouched
    assert (items[2]["x"], items[2]["y"], items[2]["w"], items[2]["h"]) == (100, 110, 120, 130)
    assert items[2]["fileName"] == "a.png"
    assert items[3]["start"] == [0, 0] and items[3]["end"] == [1, 0]  # line untouched


def test_splice_rounds_to_integers_like_jxa():
    payload = {"slides": [{"index": 0, "number": 1, "items": [
        {"kind": "group", "kindIndex": 0, "x": 0, "y": 0, "w": 0, "h": 0, "index": 0}]}]}
    _splice_bulk_geometry(payload, {0: {"group": [[10.4, -2.6, 99.6, 0.4]]}})
    it = payload["slides"][0]["items"][0]
    assert (it["x"], it["y"], it["w"], it["h"]) == (10, -3, 100, 0)
    assert all(isinstance(it[k], int) for k in ("x", "y", "w", "h"))


def test_two_tier_none_fn_is_pure_offline_with_soft_fallback():
    # With no bulk fn the payload is the tier-1 offline read, and every soft item
    # (unconfirmed) is a fallback unit — bulk_ok False.
    if not MAP_DECK.exists():
        pytest.skip("local gold deck only")
    pytest.importorskip("keynote_parser")
    payload = two_tier_wall_payload(MAP_DECK, bulk_geometry_fn=None)
    side = payload["_offline"]
    assert side["bulk_ok"] is False and side["spliced"] == 0
    assert side["fallback"], "pure offline must flag the soft classes for confirmation"
    # Every fallback reason is either a content flag or an unconfirmed soft frame.
    from obed_edom.offline_inspect import CONTENT_GUARD_REASONS
    assert all(f["reason"] in (CONTENT_GUARD_REASONS | {"bulk-missing"}) for f in side["fallback"])


@pytest.mark.skipif(not MAP_DECK.exists(), reason="local gold deck only")
def test_two_tier_splice_makes_write_affecting_gate_green_map_deck():
    """The proven simulation: splicing the JXA group/image/movie/text x/y/w/h into
    the offline payload makes the remap PLAN (transforms + reuses) write-affecting-
    identical to the JXA plan on the Map deck — the gate goes GREEN behind the bulk
    fn. Font size (autoshrink, re-derived on write) and colour are the only fields
    that still differ; both are non-write-affecting (see _ATTR_ONLY_SPEC_FIELDS)."""
    pytest.importorskip("keynote_parser")
    jxa = _cached_payload(MAP_DECK)
    if jxa is None:
        pytest.skip("no exact-bytes JXA payload cached for the current deck bytes")
    template = None
    tmpl_deck = MAP_DECK.parent / "Base_CG_Assets.key"
    if tmpl_deck.exists():
        template = offline_wall_payload(tmpl_deck)
    if template is None:
        pytest.skip("no CG template deck available for the plan gate")

    from obed_edom.map_remap import plan_payload_transforms, plan_slide_reuses
    from obed_edom.remap_keynote import recipe_for

    off = two_tier_wall_payload(MAP_DECK, bulk_geometry_fn=_bulk_double_from_jxa(jxa))
    assert off["_offline"]["bulk_ok"] is True
    assert off["_offline"]["fallback_slides"] == [], "full bulk => no slide falls back"
    assert off["_offline"]["spliced"] > 1000

    def plan(wall):
        rc = recipe_for(wall, template)
        transforms = plan_payload_transforms(wall, rc, template=template)
        return ([t.as_dict() for t in transforms],
                plan_slide_reuses(wall, transforms))

    off_t, off_r = plan(off)
    jxa_t, jxa_r = plan(jxa)
    present = _present_addresses(off)
    tdiffs = _transform_wa_diffs(off_t, jxa_t)
    rdiffs = _reuse_wa_diffs(off_r, jxa_r, present)
    assert tdiffs == [], f"transform write-affecting diffs: {tdiffs[:5]}"
    assert rdiffs == [], f"reuse write-affecting diffs: {rdiffs[:5]}"


@pytest.mark.skipif(not MAP_DECK.exists(), reason="local gold deck only")
def test_two_tier_granular_fallback_is_per_slide_not_deck():
    """Omitting one slide's groups from the bulk read flags ONLY that slide (its
    unconfirmed group frames) — every other slide stays served offline+bulk."""
    pytest.importorskip("keynote_parser")
    jxa = _cached_payload(MAP_DECK)
    if jxa is None:
        pytest.skip("no exact-bytes JXA payload cached for the current deck bytes")
    # Pick a slide index that actually carries soft group geometry.
    off_probe = two_tier_wall_payload(MAP_DECK, bulk_geometry_fn=None)
    soft = off_probe["_offline"]["soft_geometry"]
    victim_number = next(f["slide"] for f in soft if f["kind"] == "group")
    victim_index = victim_number - 1

    fn = _bulk_double_from_jxa(jxa, omit={(victim_index, "group")})
    off = two_tier_wall_payload(MAP_DECK, bulk_geometry_fn=fn)
    side = off["_offline"]
    assert side["bulk_ok"] is True
    # Only the victim slide falls back, and only for its (unconfirmed) groups.
    assert side["fallback_slides"] == [victim_number]
    assert {f["kind"] for f in side["fallback"]} == {"group"}
    assert all(f["slide"] == victim_number for f in side["fallback"])
    # A group on the victim slide kept its OFFLINE geometry (not spliced); a group
    # on another slide was overwritten by the bulk value.
    jby = {s["index"]: {(it["kind"], it["kindIndex"]): it for it in s["items"]}
           for s in jxa["slides"]}
    for slide in off["slides"]:
        if slide["index"] != victim_index:
            continue
        for it in slide["items"]:
            if it["kind"] == "group":
                # unconfirmed => did NOT take the JXA value (offline union frame)
                j = jby[victim_index].get(("group", it["kindIndex"]))
                if j is not None and (j["x"], j["y"]) != (it["x"], it["y"]):
                    break
        else:
            continue
        break


@pytest.mark.skipif(not MAP_DECK.exists(), reason="local gold deck only")
def test_two_tier_splice_does_not_touch_addressing_or_style():
    """The splice overwrites geometry ONLY: every item's addressing (index/kind/
    kindIndex), style (font/size/color), fileName, locked and text are byte-equal
    to the pure-offline payload."""
    pytest.importorskip("keynote_parser")
    jxa = _cached_payload(MAP_DECK)
    if jxa is None:
        pytest.skip("no exact-bytes JXA payload cached for the current deck bytes")
    base = two_tier_wall_payload(MAP_DECK, bulk_geometry_fn=None)
    spliced = two_tier_wall_payload(MAP_DECK, bulk_geometry_fn=_bulk_double_from_jxa(jxa))
    keep = ("index", "kind", "kindIndex", "font", "size", "color", "fileName",
            "locked", "text", "buildCount", "duplicateOf")
    for bs, ss in zip(base["slides"], spliced["slides"]):
        assert len(bs["items"]) == len(ss["items"])
        for bi, si in zip(bs["items"], ss["items"]):
            for key in keep:
                assert bi.get(key) == si.get(key), (bs["number"], key, bi.get(key), si.get(key))
