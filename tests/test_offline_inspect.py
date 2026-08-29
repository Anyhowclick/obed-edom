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
    VOUCHED_NEEDS_KEYNOTE,
    _build_data_index,
    _canvas_size,
    _data_identifier,
    _guard_tripped,
    _item_from_record,
    _item_text_style,
    _line_endpoints,
    _locked,
    offline_wall_payload,
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
    """Records the open gap: the offline plan does NOT equal the JXA plan yet.

    Expected to xfail. When a font-metric text-layout model + a group-frame model
    land and close the divergence, this flips to xpass — the signal to revisit the
    guard's vouched set and the default flip.
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
