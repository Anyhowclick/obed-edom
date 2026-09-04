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
def test_deck_slide_digests_ignore_image_rotation():
    """Regression: the slide-IDENTITY digest (which decides pairing) must NOT depend on
    image rotation. A flipped/masked photo's offline angle can differ from JXA (a flipped
    DSK lower-third read 354 vs JXA 0); when rotation was in the digest that churn floated
    the slide out of order in the checker. Orientation discrepancies are caught by the
    paired-image comparison, not this ordering key."""
    from obed_edom.baseline import deck_slide_digests
    base = {"slides": [{"index": 0, "number": 1, "skipped": False, "items": [
        {"kind": "image", "kindIndex": 0, "fileName": "a.jpg",
         "x": 44, "y": 704, "w": 1832, "h": 350, "rotation": 0}]}]}
    rotated = {"slides": [{"index": 0, "number": 1, "skipped": False, "items": [
        {"kind": "image", "kindIndex": 0, "fileName": "a.jpg",
         "x": 44, "y": 704, "w": 1832, "h": 350, "rotation": 354}]}]}
    assert deck_slide_digests(base) == deck_slide_digests(rotated)


def test_deck_slide_digests_ignore_image_geometry():
    """Same class as rotation: offline-composed x/y/w/h can drift from JXA between
    runs, so the slide-IDENTITY digest must not depend on image position or size —
    otherwise an unedited image churns its digest and floats out of order."""
    from obed_edom.baseline import deck_slide_digests
    a = {"slides": [{"index": 0, "number": 1, "skipped": False, "items": [
        {"kind": "image", "kindIndex": 0, "fileName": "a.jpg",
         "x": 44, "y": 704, "w": 1832, "h": 350}]}]}
    b = {"slides": [{"index": 0, "number": 1, "skipped": False, "items": [
        {"kind": "image", "kindIndex": 0, "fileName": "a.jpg",
         "x": 45, "y": 700, "w": 1830, "h": 351}]}]}
    assert deck_slide_digests(a) == deck_slide_digests(b)


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


def _bulk_double_from_jxa(jxa_payload: dict, *, omit: set | None = None, honour_slides: bool = False):
    """A ``bulk_geometry_fn`` returning the JXA payload's group/image/movie/text x/y/w/h.

    ``{slideIndex: {kind: [[x, y, w, h], … by kindIndex]}}`` — exactly what a real
    bulk read would hand back. ``omit`` is a set of ``(slideIndex, kind)`` to leave
    OUT, so a test can simulate the bulk read missing a slide or a kind and check
    the granular fallback. ``honour_slides`` restricts the response to the caller's
    (1-based) ``slides`` list, like the real bulk read would.
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
        if not honour_slides or not slides:
            return base
        keep = {int(n) - 1 for n in slides}  # `slides` is 1-based; `base` keys are 0-based
        return {i: rows for i, rows in base.items() if i in keep}
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
    spliced, mismatch = _splice_bulk_geometry(payload, bulk)
    assert spliced == {(1, "text", 0), (1, "image", 0)}
    assert mismatch == set()
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


def test_count_guard_exact_kind_mismatch_is_unspliced_and_flagged():
    # An image count disagreement (bulk returns one fewer row than the offline read
    # has image items) desyncs kindIndex: the kind is left UNspliced and returned in
    # count_mismatch, while a matching kind on the same slide still splices.
    payload = {"slideWidth": 1920, "slideHeight": 1080, "slides": [
        {"index": 0, "number": 1, "items": [
            {"kind": "image", "kindIndex": 0, "x": 0, "y": 0, "w": 0, "h": 0, "index": 0},
            {"kind": "image", "kindIndex": 1, "x": 0, "y": 0, "w": 0, "h": 0, "index": 1},
            {"kind": "group", "kindIndex": 0, "x": 0, "y": 0, "w": 0, "h": 0, "index": 2},
        ]},
    ]}
    bulk = {0: {"image": [[10, 10, 10, 10]], "group": [[20, 20, 20, 20]]}}
    spliced, mismatch = _splice_bulk_geometry(payload, bulk)
    assert mismatch == {(1, "image")}
    assert spliced == {(1, "group", 0)}  # matching kind still spliced
    items = payload["slides"][0]["items"]
    assert (items[0]["x"], items[0]["y"]) == (0, 0)  # image left offline
    assert (items[2]["x"], items[2]["y"]) == (20, 20)  # group overwritten


def test_count_guard_text_slack_requires_placeholder_tail():
    # The text slack [0,2] must not mask a mid-list drop: when keynote-derived is in
    # {1,2} the extra TAIL rows must be placeholder-shaped (at ~0,0 / off-canvas),
    # else the (slide, text) is a real count mismatch (a dropped mid-list box pushed
    # a real object to the end).
    def deck():
        return {"slideWidth": 1920, "slideHeight": 1080, "slides": [
            {"index": 0, "number": 1, "items": [
                {"kind": "text", "kindIndex": 0, "x": 0, "y": 0, "w": 0, "h": 0, "index": 0},
                {"kind": "text", "kindIndex": 1, "x": 0, "y": 0, "w": 0, "h": 0, "index": 1},
            ]}]}
    # Tail row is a real on-canvas box, not a placeholder => flagged, text unspliced.
    real_tail = {0: {"text": [[10, 20, 30, 40], [50, 60, 70, 80], [500, 400, 200, 50]]}}
    spliced, mismatch = _splice_bulk_geometry(deck(), real_tail)
    assert mismatch == {(1, "text")}
    assert spliced == set()
    # A genuine placeholder tail (at 0,0) is allowed: text splices, no mismatch.
    ph_tail = {0: {"text": [[10, 20, 30, 40], [50, 60, 70, 80], [0, 0, 0, 0]]}}
    spliced2, mismatch2 = _splice_bulk_geometry(deck(), ph_tail)
    assert mismatch2 == set()
    assert spliced2 == {(1, "text", 0), (1, "text", 1)}


def test_count_mismatch_forces_fallback_even_with_zero_soft_items(monkeypatch):
    """A per-(slide, kind) bulk-vs-offline count disagreement forces the slide into
    fallback_slides EVEN when the slide carries no soft item — closes the soft-free
    mis-splice hole (r-count-guard). Today's soft-only fallback logic would keep the
    offline item list the mismatch just proved wrong. The tier-1 read is stubbed so
    the two_tier fallback wiring is exercised on a deliberately soft-free slide."""
    from obed_edom import offline_inspect

    def fake_offline(key_path, slide_range=None, *, deck=None):
        # A soft-free slide (empty soft_geometry/guard) with two image items.
        return {
            "slideWidth": 1920, "slideHeight": 1080,
            "slides": [{"index": 0, "number": 1, "items": [
                {"kind": "image", "kindIndex": 0, "x": 0, "y": 0, "w": 0, "h": 0, "index": 0},
                {"kind": "image", "kindIndex": 1, "x": 0, "y": 0, "w": 0, "h": 0, "index": 1},
            ]}],
            "_offline": {"guard": [], "soft_geometry": []},
        }
    monkeypatch.setattr(offline_inspect, "offline_wall_payload", fake_offline)

    # Bulk returns ONE image row for a slide the offline read has TWO images on.
    def fn(key_path, slides=None):
        return {0: {"image": [[10, 10, 10, 10]]}}

    off = two_tier_wall_payload("ignored.key", bulk_geometry_fn=fn)
    side = off["_offline"]
    assert side["bulk_ok"] is True
    assert side["fallback_slides"] == [1]
    assert any(
        f["slide"] == 1 and f["reason"] == "count-mismatch" and f["kind"] == "image"
        for f in side["fallback"]
    )
    # And the mismatched kind was left UNspliced (offline geometry stands).
    assert side["spliced"] == 0


def _fake_offline_deck(*, skipped=(), soft=(), guard=()):
    """Tier-1 double: 3 numbered slides, one image each; ``skipped`` is 1-based numbers."""
    skip = set(skipped)

    def fake(key_path, slide_range=None, *, deck=None):
        return {
            "slideWidth": 1920, "slideHeight": 1080, "slideCount": 3,
            "slides": [{"index": i, "number": i + 1, "skipped": (i + 1) in skip,
                        "items": [{"kind": "image", "kindIndex": 0,
                                   "x": 0, "y": 0, "w": 0, "h": 0, "index": 0}]}
                       for i in range(3)],
            "_offline": {"guard": list(guard), "soft_geometry": list(soft)},
        }
    return fake


def test_two_tier_bulk_reads_only_non_skipped_slides(monkeypatch):
    from obed_edom import offline_inspect

    monkeypatch.setattr(offline_inspect, "offline_wall_payload", _fake_offline_deck(skipped={2}))

    seen: dict = {}

    def fn(key_path, slides=None):
        seen["slides"] = slides
        return {}

    off = two_tier_wall_payload("ignored.key", bulk_geometry_fn=fn)
    side = off["_offline"]
    assert seen["slides"] == [1, 3]
    assert side["bulk_slides"] == 2
    assert side["skipped"] == 1
    assert side["fallback_slides"] == []


def test_skipped_slide_soft_items_are_not_fallback(monkeypatch):
    from obed_edom import offline_inspect

    soft = [
        {"slide": 2, "kind": "group", "kindIndex": 0},
        {"slide": 3, "kind": "group", "kindIndex": 0},
    ]
    monkeypatch.setattr(
        offline_inspect, "offline_wall_payload", _fake_offline_deck(skipped={2}, soft=soft)
    )

    off = two_tier_wall_payload("ignored.key", bulk_geometry_fn=lambda key_path, slides=None: {})
    side = off["_offline"]
    assert side["fallback_slides"] == [3]
    assert all(f["slide"] == 3 for f in side["fallback"])


def test_skipped_slide_font_flags_are_not_fallback_but_filename_dirty_is(monkeypatch):
    """``filename-dirty`` stays even on a skipped slide because ``deck_slide_digests``
    hashes fileName (``baseline.py:170-172``) and the legacy item re-read is what
    fills the real fileName."""
    from obed_edom import offline_inspect

    guard = [
        {"slide": 2, "kind": "text", "kindIndex": 0, "reason": "font-size-unresolved"},
        {"slide": 2, "kind": "image", "kindIndex": 0, "reason": "filename-dirty"},
        {"slide": 3, "kind": "text", "kindIndex": 0, "reason": "font-size-unresolved"},
    ]
    monkeypatch.setattr(
        offline_inspect, "offline_wall_payload", _fake_offline_deck(skipped={2}, guard=guard)
    )

    off = two_tier_wall_payload("ignored.key", bulk_geometry_fn=lambda key_path, slides=None: {})
    side = off["_offline"]
    assert {(f["slide"], f["reason"]) for f in side["fallback"]} == {
        (2, "filename-dirty"), (3, "font-size-unresolved"),
    }
    assert side["fallback_slides"] == [2, 3]


def _own_path(key_path):
    return str(Path(key_path).expanduser().resolve())


def test_two_tier_sidecar_carries_bulk_errors(monkeypatch):
    """bulk_geometry.js's own per-collection/item failures (invisible otherwise -- a
    "bulk-missing" fallback carries no reason why) ride on `inspect.LAST_BULK_ERRORS`,
    set by whatever `bulk_geometry_fn` the LAST call made; _finalize_two_tier copies
    them into the sidecar as `bulk_errors` even on an overall bulk_ok=True read (a
    silent partial). Each entry must carry the CALLER's own `path` to survive the
    snapshot's path filter (D-item 4)."""
    from obed_edom import inspect as inspect_mod
    from obed_edom import offline_inspect

    monkeypatch.setattr(offline_inspect, "offline_wall_payload", _fake_offline_deck())

    def fn(key_path, slides=None):
        sample = [{"slide": 1, "kind": "movie", "where": "collection", "error": "boom",
                  "path": _own_path(key_path)}]
        monkeypatch.setattr(inspect_mod, "LAST_BULK_ERRORS", sample, raising=False)
        return {}

    off = two_tier_wall_payload("ignored.key", bulk_geometry_fn=fn)
    assert off["_offline"]["bulk_errors"] == [
        {"slide": 1, "kind": "movie", "where": "collection", "error": "boom",
         "path": _own_path("ignored.key")}
    ]
    assert off["bulkErrors"] == off["_offline"]["bulk_errors"]  # promoted, non-underscore
    assert off["_offline"]["bulk_ok"] is True  # a silent partial, not a hard failure


def test_two_tier_sidecar_bulk_errors_empty_when_none_reported(monkeypatch):
    from obed_edom import inspect as inspect_mod
    from obed_edom import offline_inspect

    monkeypatch.setattr(offline_inspect, "offline_wall_payload", _fake_offline_deck())
    monkeypatch.setattr(inspect_mod, "LAST_BULK_ERRORS", [], raising=False)

    off = two_tier_wall_payload("ignored.key", bulk_geometry_fn=lambda key_path, slides=None: {})
    assert off["_offline"]["bulk_errors"] == []
    assert off["bulkErrors"] == []


def test_two_tier_sidecar_drops_bulk_errors_from_a_different_path(monkeypatch):
    """A stale `LAST_BULK_ERRORS` left by some OTHER caller's `bulk_geometry()` call
    (a different deck path) must never leak into THIS payload's sidecar."""
    from obed_edom import inspect as inspect_mod
    from obed_edom import offline_inspect

    monkeypatch.setattr(offline_inspect, "offline_wall_payload", _fake_offline_deck())

    stale = [{"slide": 9, "kind": "image", "where": "collection", "error": "stale",
             "path": "/some/other/deck.key"}]

    def fn(key_path, slides=None):
        monkeypatch.setattr(inspect_mod, "LAST_BULK_ERRORS", stale, raising=False)
        return {}

    off = two_tier_wall_payload("ignored.key", bulk_geometry_fn=fn)
    assert off["_offline"]["bulk_errors"] == []
    assert off["bulkErrors"] == []


def test_two_tier_sidecar_carries_bulk_notes_but_never_promotes_them(monkeypatch):
    """Notes (informational drift, e.g. bulk:<prop>:length) ride on `LAST_BULK_NOTES`
    and land in the sidecar as `bulk_notes` -- but unlike `bulk_errors` they are NOT
    promoted to a non-underscore top-level key, so they do NOT survive a cache write."""
    from obed_edom import inspect as inspect_mod
    from obed_edom import offline_inspect

    monkeypatch.setattr(offline_inspect, "offline_wall_payload", _fake_offline_deck())

    def fn(key_path, slides=None):
        sample = [{"slide": 2, "kind": "image", "where": "bulk:position:length",
                  "error": "length !== 3", "path": _own_path(key_path)}]
        monkeypatch.setattr(inspect_mod, "LAST_BULK_NOTES", sample, raising=False)
        monkeypatch.setattr(inspect_mod, "LAST_BULK_ERRORS", [], raising=False)
        return {}

    off = two_tier_wall_payload("ignored.key", bulk_geometry_fn=fn)
    assert off["_offline"]["bulk_notes"] == [
        {"slide": 2, "kind": "image", "where": "bulk:position:length", "error": "length !== 3",
         "path": _own_path("ignored.key")}
    ]
    assert "bulkNotes" not in off  # never promoted, unlike bulkErrors


def test_all_skipped_skips_bulk_call(monkeypatch):
    from obed_edom import offline_inspect

    monkeypatch.setattr(
        offline_inspect, "offline_wall_payload", _fake_offline_deck(skipped={1, 2, 3})
    )

    def fn(key_path, slides=None):
        raise AssertionError("bulk_geometry_fn must not be called when every slide is skipped")

    off = two_tier_wall_payload("ignored.key", bulk_geometry_fn=fn)
    side = off["_offline"]
    assert side["bulk_ok"] is True
    assert side["spliced"] == 0
    assert side["bulk_slides"] == 0
    assert side["fallback_slides"] == []


def test_slide_range_intersects_non_skipped(monkeypatch):
    from obed_edom import offline_inspect

    monkeypatch.setattr(offline_inspect, "offline_wall_payload", _fake_offline_deck(skipped={2}))

    seen: dict = {}

    def fn(key_path, slides=None):
        seen["slides"] = slides
        return {}

    two_tier_wall_payload("ignored.key", bulk_geometry_fn=fn, slide_range=(2, 3))
    assert seen["slides"] == [3]


def test_subset_bulk_requests_every_slide_when_none_skipped_and_digests_hold():
    """The Map deck has 0 skipped slides, so ``wanted`` (1-based) must cover every
    slide the JXA payload has (0-based bulk keys aside) — the discriminating
    assertion is the recorded ``slides`` kwarg. The digest equalities are a sanity
    check, not the point: the slide-identity digest never depends on geometry, so a
    subset or partial (some kinds omitted) bulk read holds it by construction."""
    pytest.importorskip("keynote_parser")
    jxa = _cached_payload(MAP_DECK)
    if jxa is None:
        pytest.skip("no exact-bytes JXA payload cached for the current deck bytes")
    from obed_edom.baseline import deck_slide_digests

    full = two_tier_wall_payload(MAP_DECK, bulk_geometry_fn=_bulk_double_from_jxa(jxa))

    seen: dict = {}
    honour_fn = _bulk_double_from_jxa(jxa, honour_slides=True)

    def spy(key_path, slides=None):
        seen["slides"] = slides
        return honour_fn(key_path, slides=slides)

    subset = two_tier_wall_payload(MAP_DECK, bulk_geometry_fn=spy)
    assert seen["slides"] == [s["number"] for s in full["slides"]]

    omit = {(i, k) for i in (1, 2) for k in BULK_KINDS}
    partial = two_tier_wall_payload(
        MAP_DECK, bulk_geometry_fn=_bulk_double_from_jxa(jxa, omit=omit, honour_slides=True)
    )
    assert deck_slide_digests(partial) == deck_slide_digests(full) == deck_slide_digests(subset)


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


def _assert_two_tier_gate_green(deck: Path):
    """THE RESIZER GOLD-DECK GATE. Splicing the JXA group/image/movie/text x/y/w/h
    into the offline payload must make the remap PLAN (transforms + reuses) write-
    affecting-identical to the JXA plan — the gate goes GREEN behind the bulk fn. Font
    size (autoshrink, re-derived on write) and colour are the only fields that still
    differ; both are non-write-affecting (see _ATTR_ONLY_SPEC_FIELDS). Skips when the
    deck / cached payload / CG template is absent (all local-only, Keynote-free)."""
    pytest.importorskip("keynote_parser")
    jxa = _cached_payload(deck)
    if jxa is None:
        pytest.skip("no exact-bytes JXA payload cached for the current deck bytes")
    tmpl_deck = deck.parent / "Base_CG_Assets.key"
    if not tmpl_deck.exists():
        pytest.skip("no CG template deck available for the plan gate")
    template = offline_wall_payload(tmpl_deck)

    from obed_edom.map_remap import plan_payload_transforms, plan_slide_reuses
    from obed_edom.remap_keynote import recipe_for

    off = two_tier_wall_payload(deck, bulk_geometry_fn=_bulk_double_from_jxa(jxa))
    assert off["_offline"]["bulk_ok"] is True
    assert off["_offline"]["fallback_slides"] == [], "full bulk => no slide falls back"
    # Every bulk-kind item is spliced EXCEPT the <=2-per-slide trailing empty
    # placeholder text boxes JXA appends and the offline read omits (placement-
    # neutral; SKILL "Placeholders"). Assert that invariant rather than a magic
    # count, so an edit to the gold deck doesn't falsely fail this.
    bulk_items = sum(1 for s in jxa["slides"]
                     for it in (s.get("items") or []) if it["kind"] in BULK_KINDS)
    slide_count = len(jxa["slides"])
    assert bulk_items - 2 * slide_count <= off["_offline"]["spliced"] <= bulk_items

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
def test_two_tier_splice_makes_write_affecting_gate_green_map_deck():
    # Map deck: 0 rotated-masked images, so it does not exercise the L1 guard; it pins
    # the shape/line/group/autosize-text plan neutrality of the two-tier read.
    _assert_two_tier_gate_green(MAP_DECK)


@pytest.mark.skipif(not FULL_DECK.exists(), reason="local gold deck only")
def test_two_tier_splice_makes_write_affecting_gate_green_full_deck():
    # Full report-card deck carries the rotated-masked images the Map deck lacks (10
    # pre-L1), so THIS is the gate that proves L1's masked-image change is plan-neutral
    # for the resizer: whether L1 flags or vouches those images, the bulk splice
    # overwrites their geometry and the remap plan stays JXA-identical.
    _assert_two_tier_gate_green(FULL_DECK)


@pytest.mark.parametrize("deck", [MAP_DECK, FULL_DECK], ids=["map", "full"])
def test_l1_cleared_rotated_masked_images_are_write_safe(deck):
    """L1's load-bearing property: a masked image the guard CLEARS (rotated-masked no
    longer flagged) is within the 2px write tolerance of the JXA oracle, so a path that
    trusts it without a bulk read (the tier-1 guard, or a future slim-bulk that drops
    the image kind) stays write-safe. Only the VOUCHED masks are checked — a still-
    flagged image falls back and its best-effort value never lands.

    On FULL we also assert that at least one OFF-AXIS mask (frame or mask angle not a
    90° multiple) is vouched — otherwise a regression to the old flag-every-rotated
    guard would leave this test green while silently losing all L1 coverage. MAP has no
    off-axis masks (all vouched masks are axis-aligned), so that leg is FULL-only."""
    pytest.importorskip("keynote_parser")
    if not deck.exists():
        pytest.skip("local gold deck only")
    jxa = _cached_payload(deck)
    if jxa is None:
        pytest.skip("no exact-bytes JXA payload cached for the current deck bytes")
    from obed_edom.iwa_geometry import _geom_dict, _mask_geom, _xywha
    from obed_edom.iwa_runs import _load_deck, slide_order

    def _off_axis(angle: float) -> bool:
        r = angle % 90.0
        return min(r, 90.0 - r) > 0.5

    jby = {s["index"]: {(it["kind"], it["kindIndex"]): it for it in s.get("items") or []}
           for s in jxa["slides"]}
    objects, _a, _b = _load_deck(deck)
    checked = off_axis_vouched = 0
    for index, (sid, _skip) in enumerate(slide_order(objects)):
        if sid not in objects:
            continue
        jmap = jby.get(index, {})
        for rec in compose_geometry(objects[sid], objects):
            if rec.get("geom_source") != "mask" or rec.get("needs_keynote") is not None:
                continue  # only vouched (cleared) masked images
            obj = objects.get(rec["id"]) or {}
            mg = _mask_geom(obj, objects)
            if _off_axis(_xywha(_geom_dict(obj))[4]) or (mg and _off_axis(_xywha(mg)[4])):
                off_axis_vouched += 1  # an image L1 cleared that the old guard flagged
            j = jmap.get((rec["kind"], rec["kindIndex"]))
            if not j or j.get("x") is None:
                continue
            assert abs(rec["x"] - j["x"]) <= 2 and abs(rec["y"] - j["y"]) <= 2, (
                deck.name, index + 1, rec["kind"], rec["kindIndex"],
                (rec["x"], rec["y"]), (j["x"], j["y"]))
            checked += 1
    assert checked > 0, "no vouched masked images found to check"
    if deck == FULL_DECK:
        assert off_axis_vouched > 0, "L1 vouched no off-axis mask — lost its coverage"


@pytest.mark.parametrize("deck", [MAP_DECK, FULL_DECK], ids=["map", "full"])
def test_l2a_cleared_masked_child_groups_are_write_safe(deck):
    """L2a's load-bearing property: a GROUP vouched (needs_keynote None) whose subtree
    contains a masked child is within the 2px write tolerance of the JXA oracle AND
    derives the SAME pin/map role as the JXA frame — so propagating L1's snap into the
    group union (_leaf_bbox) is write-safe for any path that trusts the offline group
    frame (a role flip is the write-affecting failure the px check alone would miss).
    Also asserts ≥1 such vouched group has an OFF-AXIS masked child, else a regression
    to the old flag-every-rotated-masked-child rule would leave this green while losing
    L2a's coverage. (Asserted for BOTH decks — unlike the L1 test's FULL-only guard —
    because MAP's off-axis masks live only as in-group children, never as top-level
    masked-image records, so MAP exercises L2a even though it did not exercise L1.)"""
    pytest.importorskip("keynote_parser")
    if not deck.exists():
        pytest.skip("local gold deck only")
    jxa = _cached_payload(deck)
    if jxa is None:
        pytest.skip("no exact-bytes JXA payload cached for the current deck bytes")
    from obed_edom.iwa_geometry import _geom_dict, _mask_geom, _xywha
    from obed_edom.iwa_runs import _load_deck, slide_order
    from obed_edom.map_remap import is_map_item, is_pin_item

    def _off_axis(angle: float) -> bool:
        r = angle % 90.0
        return min(r, 90.0 - r) > 0.5

    def _masked_children(gid, objects, seen):
        """(has_masked_child, has_off_axis_masked_child) over the group subtree."""
        if gid in seen:
            return (False, False)
        seen.add(gid)
        group = objects.get(gid) or {}
        has = off = False
        for ref in group.get("children") or []:
            cid = ref.get("identifier")
            child = objects.get(str(cid)) if cid is not None else None
            if not child:
                continue
            if child.get("_pbtype") == "TSD.GroupArchive":
                h2, o2 = _masked_children(str(cid), objects, seen)
                has, off = has or h2, off or o2
            elif child.get("_pbtype") in ("TSD.ImageArchive", "TSD.MovieArchive"):
                mg = _mask_geom(child, objects)
                if mg:
                    has = True
                    if _off_axis(_xywha(_geom_dict(child))[4]) or _off_axis(_xywha(mg)[4]):
                        off = True
        return (has, off)

    jby = {s["index"]: {(it["kind"], it["kindIndex"]): it for it in s.get("items") or []}
           for s in jxa["slides"]}
    objects, _a, _b = _load_deck(deck)
    checked = off_axis_vouched = 0
    for index, (sid, _skip) in enumerate(slide_order(objects)):
        if sid not in objects:
            continue
        jmap = jby.get(index, {})
        for rec in compose_geometry(objects[sid], objects):
            if rec["kind"] != "group" or rec.get("needs_keynote") is not None:
                continue  # only vouched groups
            has, off = _masked_children(rec["id"], objects, set())
            if not has:
                continue
            if off:
                off_axis_vouched += 1  # a group L2a cleared that the old rule flagged
            j = jmap.get((rec["kind"], rec["kindIndex"]))
            if not j or j.get("x") is None:
                continue
            for f in ("x", "y", "w", "h"):
                assert abs(rec[f] - j[f]) <= 2, (deck.name, index + 1, f, rec[f], j[f])
            # Role parity: the offline frame must derive the same pin/map role as JXA —
            # a size-driven pin<->other flip is write-affecting even inside the 2px band
            # (the property a future slim-bulk that trusts this frame depends on).
            off_item = {**j, "x": rec["x"], "y": rec["y"], "w": rec["w"], "h": rec["h"]}
            assert is_pin_item(off_item) == is_pin_item(j), (deck.name, index + 1, "pin")
            assert is_map_item(off_item) == is_map_item(j), (deck.name, index + 1, "map")
            checked += 1
    assert checked > 0, "no vouched masked-child groups found to check"
    assert off_axis_vouched > 0, "L2a vouched no off-axis masked-child group"


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
