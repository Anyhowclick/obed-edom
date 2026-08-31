"""Tests for offline JXA-frame geometry composition (obed_edom.iwa_geometry).

The composition rules are pure and exercised WITHOUT keynote-parser by building
synthetic IWA archive dicts, including KNOWN-ANSWER rotation cases (the rotated
mask-transform sign is never exercised by the axis-aligned integration decks, so it
is pinned here by hand-computed corners). A local-only integration test reproduces
the composition on a real deck and asserts the plan's per-kind acceptance targets
against that deck's cached exact-bytes JXA payload.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from obed_edom.iwa_geometry import (
    _corners_aabb,
    _frame_rect,
    _frame_transform,
    _line_rect,
    _masked_rect,
    compose_deck_geometry,
    compose_geometry,
)
from obed_edom.iwa_kindindex import derive_kind_index

MAP_DECK = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Map_Extracted_Wall_1st.key")
FULL_DECK = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Full_Report_Card_Wall.key")


# --------------------------------------------------------------------------
# Synthetic IWA archive builders (geometry at the depth each archive uses).
# --------------------------------------------------------------------------
def _geom(x, y, w, h, angle=0.0):
    return {"geometry": {"position": {"x": x, "y": y},
                         "size": {"width": w, "height": h}, "angle": angle}}


def _image(objects, ident, *, x=0.0, y=0.0, w=10.0, h=10.0, angle=0.0, mask=None,
           pbtype="TSD.ImageArchive"):
    obj = {"_pbtype": pbtype, "super": _geom(x, y, w, h, angle)}
    if mask is not None:
        obj["mask"] = {"identifier": mask}
    objects[ident] = obj
    return ident


def _mask(objects, ident, *, x=0.0, y=0.0, w=10.0, h=10.0, angle=0.0):
    objects[ident] = {"_pbtype": "TSD.MaskArchive", "super": _geom(x, y, w, h, angle)}
    return ident


def _group(objects, ident, *, x=0.0, y=0.0, w=0.0, h=0.0, angle=0.0, children=()):
    objects[ident] = {"_pbtype": "TSD.GroupArchive", "super": _geom(x, y, w, h, angle),
                      "children": [{"identifier": c} for c in children]}
    return ident


def _shape(objects, ident, *, x=0.0, y=0.0, w=10.0, h=10.0, angle=0.0, is_textbox=False,
           text="", line=False, natural=None):
    """A TSWP.ShapeInfoArchive (geometry at super.super.geometry)."""
    if line:
        bez = {"naturalSize": {"width": w, "height": 0.0},
               "path": {"elements": [{"type": "moveTo"}, {"type": "lineTo"}]}}
    else:
        nw, nh = natural if natural is not None else (w, h)
        bez = {"naturalSize": {"width": nw, "height": nh},
               "path": {"elements": [{"type": "moveTo"}, {"type": "lineTo"}, {"type": "lineTo"},
                                     {"type": "lineTo"}, {"type": "closeSubpath"}, {"type": "moveTo"}]}}
    obj = {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": is_textbox,
           "super": {"pathsource": {"bezierPathSource": bez},
                     "super": _geom(x, y, w, h, angle)}}
    if text:
        objects[f"{ident}-st"] = {"_pbtype": "TSWP.StorageArchive", "text": [text]}
        obj["ownedStorage"] = {"identifier": f"{ident}-st"}
    objects[ident] = obj
    return ident


def _slide(*ids):
    return {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": i} for i in ids]}


def _one(slide, objects):
    recs = compose_geometry(slide, objects)
    assert len(recs) == 1
    return recs[0]


# --------------------------------------------------------------------------
# The rotation primitive — known-answer (rotate a unit rect 90 about its centre).
# --------------------------------------------------------------------------
def test_transform_unit_rect_90deg_known_answer():
    f = _frame_transform(0.0, 0.0, 1.0, 1.0, 90.0)
    # A unit square rotated 90 about its centre maps its corners onto each other.
    for (lx, ly), (ex, ey) in [((0, 0), (1, 0)), ((1, 0), (1, 1)),
                               ((1, 1), (0, 1)), ((0, 1), (0, 0))]:
        gx, gy = f(lx, ly)
        assert gx == pytest.approx(ex, abs=1e-9)
        assert gy == pytest.approx(ey, abs=1e-9)


def test_frame_rect_rotated_aabb_known_answer():
    # 4x2 rect at origin rotated 90 -> AABB 2 wide x 4 tall, top-left (1,-1);
    # composed SIZE stays the un-rotated (4, 2).
    x, y, w, h = _frame_rect(_geom(0.0, 0.0, 4.0, 2.0, 90.0)["geometry"])
    assert (round(x, 6), round(y, 6)) == (1.0, -1.0)
    assert (w, h) == (4.0, 2.0)
    # AABB of the corners really is 2 wide x 4 tall.
    x0, y0, x1, y1 = _corners_aabb(_frame_transform(0.0, 0.0, 4.0, 2.0, 90.0), 4.0, 2.0)
    assert (round(x1 - x0, 6), round(y1 - y0, 6)) == (2.0, 4.0)


def test_frame_rect_unrotated_is_passthrough():
    assert _frame_rect(_geom(100.0, 50.0, 200.0, 120.0)["geometry"]) == (100.0, 50.0, 200.0, 120.0)


# --------------------------------------------------------------------------
# Masked image — axis-aligned collapse, and a rotated known answer.
# --------------------------------------------------------------------------
def test_masked_rect_axis_aligned_is_image_plus_mask():
    (x, y, w, h), rotated = _masked_rect(_geom(100.0, 50.0, 200.0, 200.0)["geometry"],
                                         _geom(10.0, 20.0, 80.0, 60.0)["geometry"])
    assert (round(x, 6), round(y, 6), w, h) == (110.0, 70.0, 80.0, 60.0)
    assert rotated is False


def test_masked_rect_exact_90_mask_is_vouched():
    # Frame unrotated (identity to slide); mask 4x2 at (2,3) rotated EXACTLY 90 about
    # its own centre (4,4) -> corner AABB (3,2)-(5,6). Size stays the mask's (4,2). An
    # exact 90-multiple composes integer-exact (snapped == raw, zero displacement), so
    # L1 VOUCHES it — rotated is False. (Before L1 the category guard flagged it.)
    (x, y, w, h), rotated = _masked_rect(_geom(0.0, 0.0, 10.0, 10.0)["geometry"],
                                         _geom(2.0, 3.0, 4.0, 2.0, 90.0)["geometry"])
    assert (round(x, 6), round(y, 6)) == (3.0, 2.0)
    assert (w, h) == (4.0, 2.0)
    assert rotated is False


def test_masked_rect_flag_is_displacement_not_angle():
    # The same 1-degree FRAME residual flags or vouches by LEVER ARM, not by angle: a
    # mask far from the frame centre swings past the trust radius, a near one does not.
    # Frame 4000x1000 rotated 1 deg about its centre (2000,500); mask un-rotated.
    frame = _geom(0.0, 0.0, 4000.0, 1000.0, 1.0)["geometry"]
    # Mask at the frame centre: the 1 deg frame spin barely moves it -> vouched.
    (_nx, _ny, _nw, _nh), near_rot = _masked_rect(
        frame, _geom(1950.0, 470.0, 100.0, 60.0)["geometry"])
    assert near_rot is False
    # Mask at the far corner (~1994px from centre): the same 1 deg swings it ~35px,
    # well past 1.5px -> flagged.
    (_fx, _fy, _fw, _fh), far_rot = _masked_rect(
        frame, _geom(10.0, 10.0, 100.0, 60.0)["geometry"])
    assert far_rot is True


def test_masked_image_axis_aligned_record():
    objects = {}
    _mask(objects, "m", x=10.0, y=20.0, w=80.0, h=60.0)
    iid = _image(objects, "i", x=100.0, y=50.0, w=200.0, h=200.0, mask="m")
    rec = _one(_slide(iid), objects)
    assert rec["geom_source"] == "mask"
    assert rec["needs_keynote"] is None
    assert (round(rec["x"], 6), round(rec["y"], 6), rec["w"], rec["h"]) == (110.0, 70.0, 80.0, 60.0)


def test_masked_image_rotated_frame_is_flagged():
    objects = {}
    _mask(objects, "m", x=10.0, y=20.0, w=80.0, h=60.0)
    iid = _image(objects, "i", x=100.0, y=50.0, w=200.0, h=200.0, angle=3.0, mask="m")
    rec = _one(_slide(iid), objects)
    assert rec["geom_source"] == "mask"
    assert rec["needs_keynote"] == "rotated-masked"
    # still emits best-effort geometry, never None
    assert rec["x"] is not None and rec["y"] is not None


def test_unmasked_image_rotated_uses_aabb():
    objects = {}
    iid = _image(objects, "i", x=0.0, y=0.0, w=4.0, h=2.0, angle=90.0)
    rec = _one(_slide(iid), objects)
    assert rec["geom_source"] == "iwa"
    assert rec["needs_keynote"] is None
    assert (round(rec["x"], 6), round(rec["y"], 6), rec["w"], rec["h"]) == (1.0, -1.0, 4.0, 2.0)


def test_dangling_mask_is_flagged():
    # A mask ref that does not resolve: the object IS masked, so the unmasked frame is
    # wrong (JXA reports the mask rect). Must flag, not ship the frame silently
    # (regression guard for the peer's nit #1).
    objects = {}
    iid = _image(objects, "i", x=100.0, y=50.0, w=200.0, h=200.0, mask="does-not-exist")
    rec = _one(_slide(iid), objects)
    assert rec["needs_keynote"] == "masked-unresolved"
    assert (rec["x"], rec["y"], rec["w"], rec["h"]) == (100.0, 50.0, 200.0, 200.0)  # best-effort frame


# --------------------------------------------------------------------------
# Line — 0 / 30 / 90 degrees.
# --------------------------------------------------------------------------
def test_line_horizontal():
    assert _line_rect(_geom(0.0, 0.0, 100.0, 0.0)["geometry"]) == (0.0, 0.0, 100.0, 0.0)


def test_line_vertical():
    x, y, length, h = _line_rect(_geom(0.0, 0.0, 100.0, 0.0, 90.0)["geometry"])
    assert (round(x, 6), round(y, 6), length, h) == (50.0, -50.0, 100.0, 0.0)


def test_line_30deg():
    x, y, length, h = _line_rect(_geom(0.0, 0.0, 100.0, 0.0, 30.0)["geometry"])
    assert x == pytest.approx(50.0 - 50.0 * math.cos(math.radians(30)), abs=1e-6)
    assert y == pytest.approx(-50.0 * math.sin(math.radians(30)), abs=1e-6)
    assert (length, h) == (100.0, 0.0)


def test_line_record_via_bezier_classification():
    objects = {}
    lid = _shape(objects, "ln", x=0.0, y=0.0, w=100.0, h=0.0, line=True)
    rec = _one(_slide(lid), objects)
    assert rec["kind"] == "line"
    assert rec["geom_source"] == "line"
    assert (rec["w"], rec["h"]) == (100.0, 0.0)


# --------------------------------------------------------------------------
# Group — union of two children; rotation and residual flagging.
# --------------------------------------------------------------------------
def test_group_union_of_two_children():
    objects = {}
    _image(objects, "a", x=10.0, y=10.0, w=20.0, h=20.0)
    _image(objects, "b", x=50.0, y=60.0, w=30.0, h=10.0)
    gid = _group(objects, "g", x=0.0, y=0.0, children=["a", "b"])
    rec = _one(_slide(gid), objects)
    assert rec["geom_source"] == "group-union"
    assert rec["needs_keynote"] is None
    assert (rec["x"], rec["y"], rec["w"], rec["h"]) == (10.0, 10.0, 70.0, 60.0)


def test_group_nested_union_translation():
    objects = {}
    _image(objects, "a", x=5.0, y=5.0, w=10.0, h=10.0)
    inner = _group(objects, "inner", x=100.0, y=100.0, children=["a"])
    _image(objects, "b", x=0.0, y=0.0, w=10.0, h=10.0)
    gid = _group(objects, "outer", x=0.0, y=0.0, children=["b", inner])
    rec = _one(_slide(gid), objects)
    # inner child 'a' sits at 100+5=105; union spans (0,0)-(115,115).
    assert (rec["x"], rec["y"], rec["w"], rec["h"]) == (0.0, 0.0, 115.0, 115.0)
    assert rec["needs_keynote"] is None


def test_rotated_group_is_flagged():
    objects = {}
    _image(objects, "a", x=10.0, y=10.0, w=20.0, h=20.0)
    gid = _group(objects, "g", x=0.0, y=0.0, angle=5.0, children=["a"])
    rec = _one(_slide(gid), objects)
    assert rec["needs_keynote"] == "rotated-group"
    assert rec["geom_source"] == "group-union"
    assert rec["x"] is not None  # best-effort geometry still emitted


def test_group_zero_size_child_is_residual_flagged():
    objects = {}
    _shape(objects, "conn", x=10.0, y=10.0, w=0.0, h=40.0)  # zero-width connector
    _image(objects, "a", x=0.0, y=0.0, w=50.0, h=50.0)
    gid = _group(objects, "g", x=0.0, y=0.0, children=["conn", "a"])
    rec = _one(_slide(gid), objects)
    assert rec["needs_keynote"] == "group-residual"


def test_group_union_excludes_zero_extent_child():
    # A zero-extent connector far from the real content must NOT stretch the union
    # (its local origin can sit hundreds of px off the group's real corner). The
    # union is the real image alone; the group is still flagged group-residual.
    objects = {}
    _shape(objects, "conn", x=200.0, y=0.0, w=0.0, h=0.0)  # zero-extent, far right
    _image(objects, "a", x=0.0, y=0.0, w=50.0, h=50.0)
    gid = _group(objects, "g", x=0.0, y=0.0, children=["conn", "a"])
    rec = _one(_slide(gid), objects)
    assert (rec["x"], rec["y"], rec["w"], rec["h"]) == (0.0, 0.0, 50.0, 50.0)
    assert rec["needs_keynote"] == "group-residual"


def test_group_falls_back_to_stored_frame_when_no_real_child():
    # No child has positive width AND height (only a zero-extent connector), so the
    # union is empty and the group's own stored-frame geometry is used.
    objects = {}
    _shape(objects, "conn", x=0.0, y=20.0, w=0.0, h=0.0)
    gid = _group(objects, "g", x=7.0, y=8.0, w=120.0, h=90.0, children=["conn"])
    rec = _one(_slide(gid), objects)
    assert (rec["x"], rec["y"], rec["w"], rec["h"]) == (7.0, 8.0, 120.0, 90.0)


def test_masked_rect_near_zero_rotation_collapses_axis_aligned():
    # A sub-degree residual frame rotation is reported by JXA as the axis-aligned
    # frame+mask box (not the rotated-corner AABB, which sits ~1px off and, via the
    # cover recipe, cascades deck-wide). Below _MASK_ANGLE_EPS => collapse, no flag.
    (x, y, w, h), rotated = _masked_rect(
        _geom(100.0, 50.0, 200.0, 200.0, 0.05)["geometry"],
        _geom(10.0, 20.0, 80.0, 60.0)["geometry"])
    assert (round(x, 6), round(y, 6), w, h) == (110.0, 70.0, 80.0, 60.0)
    assert rotated is False


def test_masked_image_near_zero_rotation_is_not_flagged():
    objects = {}
    _mask(objects, "m", x=10.0, y=20.0, w=80.0, h=60.0)
    iid = _image(objects, "i", x=100.0, y=50.0, w=200.0, h=200.0, angle=0.05, mask="m")
    rec = _one(_slide(iid), objects)
    assert rec["needs_keynote"] is None
    assert (round(rec["x"], 6), round(rec["y"], 6), rec["w"], rec["h"]) == (110.0, 70.0, 80.0, 60.0)


def test_group_near_90_masked_child_is_vouched():
    # L2a: a masked child a couple degrees off its 90-multiple on a SMALL lever arm
    # composes accurately (displacement under _MASK_TRUST_PX), so _leaf_bbox bounds the
    # union and the group is VOUCHED — not forced to fall back. (Before L2a the category
    # rule flagged any rotated masked child; measured to clear 12 real gold-deck groups.)
    objects = {}
    _mask(objects, "m", x=5.0, y=5.0, w=30.0, h=30.0)
    _image(objects, "img", x=0.0, y=0.0, w=40.0, h=40.0, angle=2.0, mask="m")
    gid = _group(objects, "g", x=0.0, y=0.0, children=["img"])
    rec = _one(_slide(gid), objects)
    assert rec["needs_keynote"] is None


def test_group_off_axis_masked_child_is_residual_flagged():
    # L2a: a masked child far off its 90-multiple on a LONG lever arm swings the mask
    # corner well past _MASK_TRUST_PX, so the union is approximate and the group stays
    # flagged group-residual (the same displacement gate as a top-level masked image).
    objects = {}
    _mask(objects, "m", x=10.0, y=10.0, w=100.0, h=60.0)
    _image(objects, "img", x=0.0, y=0.0, w=4000.0, h=1000.0, angle=2.0, mask="m")
    gid = _group(objects, "g", x=0.0, y=0.0, children=["img"])
    rec = _one(_slide(gid), objects)
    assert rec["needs_keynote"] == "group-residual"


def test_group_axis_aligned_masked_child_not_flagged():
    objects = {}
    _mask(objects, "m", x=5.0, y=5.0, w=30.0, h=30.0)
    _image(objects, "img", x=0.0, y=0.0, w=40.0, h=40.0, mask="m")  # angle 0
    gid = _group(objects, "g", x=0.0, y=0.0, children=["img"])
    rec = _one(_slide(gid), objects)
    assert rec["needs_keynote"] is None


def test_group_union_nonzero_origin():
    # Children are stored relative to the group; the union must place them absolutely
    # (the load-bearing group-origin offset). Group at (4438, 21); two children.
    objects = {}
    _shape(objects, "a", x=10.0, y=10.0, w=20.0, h=20.0)
    _shape(objects, "b", x=50.0, y=40.0, w=30.0, h=30.0)
    gid = _group(objects, "g", x=4438.0, y=21.0, children=["a", "b"])
    rec = _one(_slide(gid), objects)
    assert rec["kind"] == "group" and rec["needs_keynote"] is None
    assert rec["x"] == 4448.0 and rec["y"] == 31.0          # 4438+10, 21+10
    assert rec["w"] == 70.0 and rec["h"] == 60.0            # (50+30)-10, (40+30)-10


def test_nested_rotated_group_is_flagged():
    # A rotated NESTED group breaks the translation-only union -> must be flagged even
    # though the OUTER group is un-rotated (regression guard for the peer's nit #2).
    objects = {}
    _shape(objects, "c", x=0.0, y=0.0, w=10.0, h=10.0)
    inner = _group(objects, "inner", x=5.0, y=5.0, w=10.0, h=10.0, angle=30.0, children=["c"])
    outer = _group(objects, "outer", x=0.0, y=0.0, children=[inner])
    rec = _one(_slide(outer), objects)
    assert rec["kind"] == "group" and rec["needs_keynote"] == "group-residual"


# --------------------------------------------------------------------------
# Text — fixed vs autosize.
# --------------------------------------------------------------------------
def test_fixed_text_uses_frame():
    objects = {}
    tid = _shape(objects, "t", x=10.0, y=20.0, w=100.0, h=40.0, is_textbox=True, text="Hi")
    rec = _one(_slide(tid), objects)
    assert rec["kind"] == "text"
    assert rec["geom_source"] == "iwa"
    assert rec["needs_keynote"] is None
    assert (rec["x"], rec["y"], rec["w"], rec["h"]) == (10.0, 20.0, 100.0, 40.0)


def test_autosize_text_x_exact_and_flagged_soft():
    objects = {}
    # zero-height frame at vertical CENTRE 200; naturalSize 120x30.
    tid = _shape(objects, "t", x=15.0, y=200.0, w=0.0, h=0.0, is_textbox=True,
                 text="CHC Kuching", natural=(120.0, 30.0))
    rec = _one(_slide(tid), objects)
    assert rec["kind"] == "text"
    assert rec["geom_source"] == "autosize"
    assert rec["needs_keynote"] == "autosize-soft"
    assert rec["x"] == 15.0                       # x exact for left-aligned
    assert rec["y"] == pytest.approx(200.0 - 15.0)  # top = centre - h/2
    assert (rec["w"], rec["h"]) == (120.0, 30.0)


# --------------------------------------------------------------------------
# Shape and movie.
# --------------------------------------------------------------------------
def test_bare_shape_rotated_aabb():
    objects = {}
    sid = _shape(objects, "s", x=0.0, y=0.0, w=4.0, h=2.0, angle=90.0, is_textbox=False)
    rec = _one(_slide(sid), objects)
    assert rec["kind"] == "shape"
    assert rec["geom_source"] == "iwa"
    assert rec["needs_keynote"] is None
    assert (round(rec["x"], 6), round(rec["y"], 6), rec["w"], rec["h"]) == (1.0, -1.0, 4.0, 2.0)


def test_movie_uses_raw_frame():
    objects = {}
    mid = _image(objects, "mv", x=30.0, y=40.0, w=160.0, h=90.0, pbtype="TSD.MovieArchive")
    rec = _one(_slide(mid), objects)
    assert rec["kind"] == "movie"
    assert rec["geom_source"] == "iwa"
    assert rec["needs_keynote"] is None
    assert (rec["x"], rec["y"], rec["w"], rec["h"]) == (30.0, 40.0, 160.0, 90.0)


def test_masked_movie_falls_through_to_mask_rule():
    objects = {}
    _mask(objects, "m", x=10.0, y=10.0, w=100.0, h=50.0)
    mid = _image(objects, "mv", x=0.0, y=0.0, w=200.0, h=100.0, mask="m",
                 pbtype="TSD.MovieArchive")
    rec = _one(_slide(mid), objects)
    assert rec["geom_source"] == "mask"
    assert (round(rec["x"], 6), round(rec["y"], 6), rec["w"], rec["h"]) == (10.0, 10.0, 100.0, 50.0)


# --------------------------------------------------------------------------
# Geometry-only invariant: composition never touches the addressing.
# --------------------------------------------------------------------------
def test_composition_preserves_kind_and_kindindex():
    objects = {}
    ids = [_shape(objects, "t0", is_textbox=True, text="a"),
           _image(objects, "i0"),
           _shape(objects, "s0", is_textbox=False),
           _image(objects, "m0", pbtype="TSD.MovieArchive"),
           _shape(objects, "d0", is_textbox=True, text="dual",
                  natural=(0.0, 0.0))]
    slide = _slide(*ids)
    derived = derive_kind_index(slide, objects)
    composed = compose_geometry(slide, objects)
    key = lambda r: (r["id"], r["kind"], r["kindIndex"])
    assert [key(r) for r in composed] == [key(r) for r in derived]


# --------------------------------------------------------------------------
# Local integration — compose a real deck and assert the plan's acceptance targets.
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


def _p90(values):
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * 0.9))]


@pytest.mark.skipif(not MAP_DECK.exists(), reason="local gold deck only")
def test_integration_map_deck_acceptance_targets():
    pytest.importorskip("keynote_parser")
    payload = _cached_payload(MAP_DECK)
    if payload is None:
        pytest.skip("no exact-bytes JXA payload cached for the current deck bytes")
    composed = compose_deck_geometry(MAP_DECK)
    pslides = {s["index"]: s for s in payload.get("slides") or []}

    pool: dict[str, list[float]] = {}
    flagged_kinds: dict[str, set] = {}
    autosize_x: list[float] = []
    for idx, recs in composed.items():
        jby = {(it["kind"], it["kindIndex"]): it
               for it in ((pslides.get(idx) or {}).get("items") or [])}
        for rec in recs:
            reason = rec.get("needs_keynote")
            if reason:
                flagged_kinds.setdefault(reason, set()).add(rec["kind"])
            j = jby.get((rec["kind"], rec["kindIndex"]))
            if not j or j.get("x") is None:
                continue
            if rec["kind"] == "text":
                if reason == "autosize-soft":
                    autosize_x.append(abs(rec["x"] - j["x"]))
                continue
            if reason:
                continue
            pool.setdefault(rec["kind"], []).append(
                max(abs(rec["x"] - j["x"]), abs(rec["y"] - j["y"])))

    # image / line / movie: 100% within 2px (non-flagged pool).
    for kind in ("image", "line"):
        deltas = pool.get(kind, [])
        assert deltas, f"no {kind} records paired"
        assert all(d < 2.0 for d in deltas), f"{kind} not all <2px: max={max(deltas):.2f}"
    # shape: p90 <= 2.5px at wall scale (rotation composed -> actually ~0.5).
    shape = pool.get("shape", [])
    assert shape and _p90(shape) <= 2.5, f"shape p90={_p90(shape):.2f} > 2.5"
    # group: >=84% of the non-flagged pool within 2px.
    group = pool.get("group", [])
    assert group and sum(1 for d in group if d < 2.0) / len(group) >= 0.84
    # autosize x: 100% within 2px on the Map deck (all left-aligned).
    assert autosize_x and all(d < 2.0 for d in autosize_x), \
        f"autosize x not all <2px: max={max(autosize_x):.2f}"

    # Flags appear only on the expected kinds: masked images, groups, autosize text.
    assert flagged_kinds.get("rotated-masked", set()) <= {"image", "movie"}
    assert flagged_kinds.get("rotated-group", set()) <= {"group"}
    assert flagged_kinds.get("group-residual", set()) <= {"group"}
    assert flagged_kinds.get("autosize-soft", set()) <= {"text"}
    # No flag reason outside the documented set.
    assert set(flagged_kinds) <= {"rotated-masked", "rotated-group",
                                  "group-residual", "autosize-soft"}


@pytest.mark.skipif(not MAP_DECK.exists(), reason="local gold deck only")
def test_integration_composition_preserves_addressing():
    """Geometry-only invariant on a real deck: (id, kind, kindIndex) identical to derive."""
    pytest.importorskip("keynote_parser")
    if _cached_payload(MAP_DECK) is None:
        pytest.skip("deck bytes not cached")
    from obed_edom.iwa_kindindex import derive_deck_kind_index

    derived = derive_deck_kind_index(MAP_DECK)
    composed = compose_deck_geometry(MAP_DECK)
    assert set(derived) == set(composed)
    key = lambda r: (r["id"], r["kind"], r["kindIndex"])
    for idx in derived:
        assert [key(r) for r in composed[idx]] == [key(r) for r in derived[idx]]
