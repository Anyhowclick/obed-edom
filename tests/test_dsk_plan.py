"""Tests for obed_edom.dsk_plan: slide classification and CG-band fitting.

Pure unit tests use synthetic item dicts and a monkeypatched offline payload,
so they run without decks or Keynote. The deck-backed tests at the bottom
exercise real Sermon_PK decks and are skipped when the local operator files or
the ``keynote_parser`` optional extra are absent (mirrors test_iwa_runs.py).
"""

from pathlib import Path

import pytest

import obed_edom.dsk_plan as dsk_plan
from obed_edom.dsk_plan import (
    Band,
    BandRefusal,
    classify_deck,
    classify_slide,
    fit_item,
    fit_slide,
    read_band,
)
from obed_edom.map_remap import CENTRE_PANEL_RECT, Rect

GW_DECK = Path("/Users/anyhowclick/Desktop/Diff-Checker/Sermon_PK (GW).key")
DSK_DECK = Path("/Users/anyhowclick/Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key")

CENTRE_WALL = (7680.0, 1080.0)


@pytest.fixture(autouse=True)
def no_keynote():
    # None of dsk_plan's paths (offline decode, offline_wall_payload, deck_builds)
    # may ever start Keynote; fail loudly instead of silently launching the app.
    import subprocess

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("Keynote must not start")

    real_run, real_popen = subprocess.run, subprocess.Popen
    subprocess.run = _forbidden
    subprocess.Popen = _forbidden
    try:
        yield
    finally:
        subprocess.run = real_run
        subprocess.Popen = real_popen


def _text_item(kind_index, x=0, y=0, w=100, h=50):
    return {"kind": "text", "kindIndex": kind_index, "x": x, "y": y, "w": w, "h": h}


def _movie_item(kind_index, x=0, y=0, w=100, h=50):
    return {"kind": "movie", "kindIndex": kind_index, "x": x, "y": y, "w": w, "h": h}


def _group_item(kind_index, x, y, w, h):
    return {"kind": "group", "kindIndex": kind_index, "x": x, "y": y, "w": w, "h": h}


def _slide(number, items, skipped=False):
    return {"number": number, "index": number - 1, "skipped": skipped, "items": items}


def _builds(records, transition=None):
    return {"slideId": "x", "builds": records, "transition": transition}


def _build_record():
    return {
        "buildId": "b1",
        "chunkIds": [],
        "chunkOrder": [],
        "chunkReferent": [],
        "kind": "text",
        "kindIndex": 0,
        "effect": "Fade In",
        "animationType": None,
        "identity": ("text", "hi"),
    }


# --------------------------------------------------------------------------
# classify_slide — one test per category.
# --------------------------------------------------------------------------
def test_classify_empty_slide_no_items():
    slide = _slide(1, [])
    out = classify_slide(slide, None, CENTRE_WALL)
    assert out.category == "empty"
    assert out.kept == ()


def test_classify_skipped_slide_forced_empty():
    slide = _slide(2, [_text_item(0)], skipped=True)
    out = classify_slide(slide, _builds([_build_record()]), CENTRE_WALL)
    assert out.category == "empty"
    assert out.number == 2


def test_classify_static_slide():
    slide = _slide(3, [_text_item(0, x=2000, y=100)])
    out = classify_slide(slide, None, CENTRE_WALL)
    assert out.category == "static"
    assert out.build_count == 0
    assert out.movie_count == 0


def test_classify_built_slide():
    slide = _slide(4, [_text_item(0, x=2000, y=100)])
    out = classify_slide(slide, _builds([_build_record()]), CENTRE_WALL)
    assert out.category == "built"
    assert out.build_count == 1


def test_classify_movie_slide():
    slide = _slide(5, [_movie_item(0, x=2000, y=100)])
    out = classify_slide(slide, _builds([]), CENTRE_WALL)
    assert out.category == "movie"
    assert out.movie_count == 1
    assert out.build_count == 0


def test_classify_mixed_slide():
    slide = _slide(6, [_text_item(0, x=2000, y=100), _movie_item(0, x=2000, y=200)])
    out = classify_slide(slide, _builds([_build_record()]), CENTRE_WALL)
    assert out.category == "mixed"
    assert out.movie_count == 1
    assert out.build_count == 1


# --------------------------------------------------------------------------
# side-panel drop — never propagated across slides.
# --------------------------------------------------------------------------
def test_side_panel_item_dropped_by_default():
    side_item = _text_item(0, x=100, y=100, w=200, h=50)  # wholly in left panel [0,1920)
    slide = _slide(4, [side_item])
    out = classify_slide(slide, None, CENTRE_WALL, include_side=False)
    assert out.kept == ()
    assert out.dropped_side == (("text", 0),)
    assert out.category == "empty"


def test_side_panel_item_kept_when_included():
    side_item = _text_item(0, x=100, y=100, w=200, h=50)
    slide = _slide(4, [side_item])
    out = classify_slide(slide, None, CENTRE_WALL, include_side=True)
    assert out.kept == (("text", 0),)
    assert out.dropped_side == ()


def test_include_side_never_propagates_to_neighbours():
    side_item = _text_item(0, x=100, y=100, w=200, h=50)
    slide3 = _slide(3, [side_item])
    slide5 = _slide(5, [side_item])
    classes = [
        classify_slide(slide3, None, CENTRE_WALL, include_side=False),
        classify_slide(_slide(4, [side_item]), None, CENTRE_WALL, include_side=True),
        classify_slide(slide5, None, CENTRE_WALL, include_side=False),
    ]
    assert classes[0].kept == ()
    assert classes[1].kept == (("text", 0),)
    assert classes[2].kept == ()


def test_group_straddling_centre_and_side_is_centre_content():
    straddling = _group_item(0, x=1800, y=0, w=300, h=1080)  # crosses the 1920 boundary
    slide = _slide(4, [straddling])
    out = classify_slide(slide, None, CENTRE_WALL, include_side=False)
    assert out.kept == (("group", 0),)
    assert out.dropped_side == ()


# --------------------------------------------------------------------------
# grouped movies — TSD.MovieArchive descendants counted via group_movie_counts.
# --------------------------------------------------------------------------
def test_classify_group_movie_centre_counts_as_movie():
    group = _group_item(0, x=2400, y=100, w=800, h=800)
    slide = _slide(7, [group])
    out = classify_slide(slide, _builds([]), CENTRE_WALL, group_movie_counts={0: 1})
    assert out.category == "movie"
    assert out.movie_count == 1
    assert out.kept == (("group", 0),)


def test_classify_group_movie_straddling_centre_and_side_counts():
    straddling = _group_item(0, x=1800, y=0, w=300, h=1080)  # crosses the 1920 boundary
    slide = _slide(8, [straddling])
    out = classify_slide(
        slide, None, CENTRE_WALL, include_side=False, group_movie_counts={0: 2}
    )
    assert out.kept == (("group", 0),)
    assert out.category == "movie"
    assert out.movie_count == 2


def test_classify_group_movie_dropped_side_not_counted():
    side_group = _group_item(0, x=100, y=100, w=200, h=50)  # wholly in left panel
    slide = _slide(9, [side_group])
    out = classify_slide(
        slide, None, CENTRE_WALL, include_side=False, group_movie_counts={0: 3}
    )
    assert out.kept == ()
    assert out.dropped_side == (("group", 0),)
    assert out.category == "empty"
    assert out.movie_count == 0


# --------------------------------------------------------------------------
# group-owned builds — a build on a group's CHILD drawable, invisible to
# iwa_builds.deck_builds (derive_kind_index only enumerates top-level drawables),
# must still count toward that top-level group's build_count.
# --------------------------------------------------------------------------
def test_classify_group_child_build_counts_as_built():
    group = _group_item(0, x=2400, y=100, w=800, h=800)
    slide = _slide(12, [group])
    out = classify_slide(slide, _builds([]), CENTRE_WALL, group_build_counts={0: 1})
    assert out.category == "built"
    assert out.build_count == 1


def test_classify_group_child_build_dropped_side_not_counted():
    side_group = _group_item(0, x=100, y=100, w=200, h=50)  # wholly in left panel
    slide = _slide(13, [side_group])
    out = classify_slide(
        slide, _builds([]), CENTRE_WALL, include_side=False, group_build_counts={0: 5}
    )
    assert out.kept == ()
    assert out.category == "empty"
    assert out.build_count == 0


def _group_archive(objects, ident, child_ids):
    objects[ident] = {
        "_pbtype": "TSD.GroupArchive",
        "children": [{"identifier": cid} for cid in child_ids],
    }
    return ident


def _drawables_zorder(*ids):
    return [{"identifier": i} for i in ids]


def _build_archive(objects, ident, drawable_id):
    objects[ident] = {"_pbtype": "KN.BuildArchive", "drawable": {"identifier": drawable_id}}
    return ident


def test_slide_group_build_counts_child_owned_build():
    objects = {
        "child1": {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": False},
        "grp1": None,
    }
    _group_archive(objects, "grp1", ["child1"])
    _build_archive(objects, "b1", "child1")
    slide = {
        "_pbtype": "KN.SlideArchive",
        "drawablesZOrder": _drawables_zorder("grp1"),
        "builds": [{"identifier": "b1"}],
    }
    counts = dsk_plan._slide_group_build_counts(slide, objects)
    assert counts == {0: 1}


def test_slide_group_build_counts_group_owned_build_not_counted():
    # A build targeting the group's OWN drawable (not a descendant) is already
    # resolved by iwa_builds.deck_builds -- this helper must not double-count it.
    objects = {
        "child1": {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": False},
        "grp1": None,
    }
    _group_archive(objects, "grp1", ["child1"])
    _build_archive(objects, "b1", "grp1")
    slide = {
        "_pbtype": "KN.SlideArchive",
        "drawablesZOrder": _drawables_zorder("grp1"),
        "builds": [{"identifier": "b1"}],
    }
    counts = dsk_plan._slide_group_build_counts(slide, objects)
    assert counts == {}


def test_classify_deck_nested_group_build(monkeypatch):
    # Integrated classify_deck-level case: a build owned by a group's child,
    # driven through the real deck_group_build_counts pipeline rather than
    # classify_slide's own group_build_counts= kwarg directly.
    objects = {
        "child1": {"_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": False},
        "grp1": None,
    }
    _group_archive(objects, "grp1", ["child1"])
    _build_archive(objects, "b1", "child1")
    objects["slide1"] = {
        "drawablesZOrder": _drawables_zorder("grp1"),
        "builds": [{"identifier": "b1"}],
    }

    payload = {
        "path": "x",
        "slideWidth": 7680.0,
        "slideHeight": 1080.0,
        "slideCount": 1,
        "slides": [_slide(1, [_group_item(0, x=2400, y=100, w=800, h=800)])],
    }

    monkeypatch.setattr(dsk_plan, "offline_wall_payload", lambda *a, **k: payload)
    monkeypatch.setattr(dsk_plan, "slide_order", lambda _objects: [("slide1", False)])
    monkeypatch.setattr(
        dsk_plan, "deck_builds", lambda *a, **k: {1: {"slideId": "slide1", "builds": [], "transition": None}}
    )

    classes = {c.number: c for c in dsk_plan.classify_deck("unused.key", deck=(objects, {}, {}))}
    assert classes[1].category == "built"
    assert classes[1].build_count == 1


def test_classify_deck_connection_line_only_slide_is_built(monkeypatch):
    # Integrated classify_deck-level case: a slide whose only content is a
    # connection line with a build. derive_kind_index has no connection-line
    # kind, so the payload carries no items for it -- kept stays empty, but
    # connection_line_builds still drives the category to "built".
    objects = {
        "line1": {"_pbtype": "TSD.ConnectionLineArchive"},
    }
    _build_archive(objects, "b1", "line1")
    objects["slide1"] = {
        "drawablesZOrder": _drawables_zorder("line1"),
        "builds": [{"identifier": "b1"}],
    }

    payload = {
        "path": "x",
        "slideWidth": 7680.0,
        "slideHeight": 1080.0,
        "slideCount": 1,
        "slides": [_slide(1, [])],
    }

    monkeypatch.setattr(dsk_plan, "offline_wall_payload", lambda *a, **k: payload)
    monkeypatch.setattr(dsk_plan, "slide_order", lambda _objects: [("slide1", False)])
    monkeypatch.setattr(
        dsk_plan, "deck_builds", lambda *a, **k: {1: {"slideId": "slide1", "builds": [], "transition": None}}
    )

    classes = {c.number: c for c in dsk_plan.classify_deck("unused.key", deck=(objects, {}, {}))}
    assert classes[1].category == "built"
    assert classes[1].kept == ()
    assert classes[1].connection_line_builds == 1


# --------------------------------------------------------------------------
# build filtering — a build on a dropped-side item must not affect classification.
# --------------------------------------------------------------------------
def test_classify_filters_build_on_dropped_side_item():
    side_item = _text_item(0, x=100, y=100, w=200, h=50)  # side panel only
    centre_item = _text_item(1, x=2000, y=100)
    slide = _slide(10, [side_item, centre_item])
    build_on_side = _build_record()  # kind text, kindIndex 0 -> the dropped side item
    out = classify_slide(slide, _builds([build_on_side]), CENTRE_WALL, include_side=False)
    assert out.category == "static"
    assert out.build_count == 0


# --------------------------------------------------------------------------
# read_band — modal maths, monkeypatched offline payload.
# --------------------------------------------------------------------------
def _band_payload(items_per_slide):
    slides = []
    for i, items in enumerate(items_per_slide, start=1):
        slides.append(_slide(i, items))
    return {"path": "x", "slideWidth": 7680.0, "slideHeight": 1080.0, "slideCount": len(slides), "slides": slides}


def _band_item(kind_index, x, y, w, h, kind="image"):
    return {"kind": kind, "kindIndex": kind_index, "x": x, "y": y, "w": w, "h": h}


def test_read_band_modal_pair(monkeypatch):
    payload = _band_payload(
        [
            [_band_item(0, 100, 704, 300, 350)],
            [_band_item(0, 200, 704, 300, 350)],
            [_band_item(0, 50, 704, 300, 350)],
            [_band_item(0, 400, 800, 100, 200)],
        ]
    )
    monkeypatch.setattr(dsk_plan, "offline_wall_payload", lambda *a, **k: payload)
    band = read_band("unused.key", deck={})
    assert band.bottom == 1054.0
    assert band.height == 350.0
    assert band.x_min == 50.0
    assert band.x_max == 500.0
    assert band.sample_count == 3


def test_read_band_excludes_backdrop_and_skipped(monkeypatch):
    payload = _band_payload(
        [
            [_band_item(0, 100, 704, 300, 350)],
            [_band_item(0, 200, 704, 300, 350)],
            [_band_item(0, 50, 704, 300, 350)],
        ]
    )
    # A full-canvas backdrop would itself form a competing 3-sample modal pair if
    # not excluded, forcing a spurious tie against the real band above.
    payload["slides"].append(_slide(4, [_band_item(1, 0, 0, 7680, 1080)]))
    payload["slides"].append(_slide(5, [_band_item(2, 0, 0, 7680, 1080)]))
    payload["slides"].append(_slide(6, [_band_item(3, 0, 0, 7680, 1080)]))
    # A skipped slide carrying an otherwise-qualifying item must not count either.
    payload["slides"].append(_slide(7, [_band_item(0, 300, 704, 300, 350)], skipped=True))
    monkeypatch.setattr(dsk_plan, "offline_wall_payload", lambda *a, **k: payload)
    band = read_band("unused.key", deck={})
    assert band.bottom == 1054.0
    assert band.height == 350.0
    assert band.sample_count == 3


def test_read_band_ambiguous_tie_refuses(monkeypatch):
    payload = _band_payload(
        [
            [_band_item(0, 100, 704, 300, 350)],
            [_band_item(0, 200, 704, 300, 350)],
            [_band_item(0, 50, 704, 300, 350)],
            [_band_item(0, 100, 500, 200, 300)],
            [_band_item(0, 200, 500, 200, 300)],
            [_band_item(0, 50, 500, 200, 300)],
        ]
    )
    monkeypatch.setattr(dsk_plan, "offline_wall_payload", lambda *a, **k: payload)
    with pytest.raises(BandRefusal):
        read_band("unused.key", deck={})


def test_read_band_refuses_fewer_than_three():
    payload = _band_payload(
        [
            [_band_item(0, 100, 704, 300, 350)],
            [_band_item(0, 200, 704, 300, 350)],
        ]
    )

    def _payload(*_a, **_k):
        return payload

    real = dsk_plan.offline_wall_payload
    dsk_plan.offline_wall_payload = _payload
    try:
        with pytest.raises(BandRefusal):
            read_band("unused.key", deck={})
    finally:
        dsk_plan.offline_wall_payload = real


# --------------------------------------------------------------------------
# fit_item — numeric acceptance cases from the brief.
# --------------------------------------------------------------------------
# x_min/x_max mirror the accepted DSK deck band (test_dsk_deck_band) -- width 1849.
BAND = Band(bottom=1054.0, height=350.0, x_min=43.0, x_max=1892.0, sample_count=7)


def test_fit_item_gw_slide32_movie():
    rect = fit_item(Rect(1920.0, -763.0, 3840.0, 2160.0), BAND)
    assert rect.h == pytest.approx(350.0, abs=0.1)
    assert rect.w == pytest.approx(1244.4, abs=0.1)
    assert rect.y == pytest.approx(704.0, abs=0.1)
    assert rect.x == pytest.approx(345.3, abs=0.1)


def test_fit_item_3840x1080_source_matches():
    rect = fit_item(Rect(1920.0, 0.0, 3840.0, 1080.0), BAND)
    assert rect.w == pytest.approx(1244.4, abs=0.1)
    assert rect.h == pytest.approx(350.0, abs=0.1)


def test_fit_item_full_wall_width_bound():
    rect = fit_item(
        Rect(0.0, 0.0, 7680.0, 1080.0), BAND, wall_rect=Rect(0.0, 0.0, 7680.0, 1080.0)
    )
    assert rect.w == pytest.approx(1849.0, abs=0.1)
    assert rect.h == pytest.approx(260.0, abs=0.1)


def test_fit_item_centre_anchor_default():
    rect = fit_item(Rect(1920.0, 0.0, 3840.0, 1080.0), BAND, anchor="centre")
    centre = BAND.x_min + BAND.width / 2.0
    assert (rect.x + rect.w / 2.0) == pytest.approx(centre, abs=0.1)


def test_fit_item_offscreen_returns_zero_rect():
    rect = fit_item(Rect(-500.0, 0.0, 100.0, 100.0), BAND)
    assert rect.w == 0.0
    assert rect.h == 0.0


def test_fit_item_left_anchor():
    rect = fit_item(Rect(1920.0, 0.0, 3840.0, 1080.0), BAND, anchor="left")
    assert rect.x == pytest.approx(BAND.x_min, abs=0.1)


def test_fit_item_right_anchor():
    rect = fit_item(Rect(1920.0, 0.0, 3840.0, 1080.0), BAND, anchor="right")
    assert (rect.x + rect.w) == pytest.approx(BAND.x_max, abs=0.1)


# --------------------------------------------------------------------------
# fit_slide — single shared scale, relative offsets preserved.
# --------------------------------------------------------------------------
def test_fit_slide_requires_kept_or_wall():
    items = [_movie_item(0, x=1920, y=0, w=1000, h=500)]
    with pytest.raises(ValueError):
        fit_slide(items, BAND, include_side=False)


def test_fit_slide_rejects_both_kept_and_wall():
    items = [_movie_item(0, x=1920, y=0, w=1000, h=500)]
    with pytest.raises(ValueError):
        fit_slide(items, BAND, include_side=False, kept=[("movie", 0)], wall=CENTRE_WALL)


def test_fit_slide_shared_scale_and_relative_offsets():
    items = [
        _movie_item(0, x=1920, y=0, w=1000, h=500),
        _movie_item(1, x=3000, y=100, w=500, h=300),
    ]
    placed = fit_slide(items, BAND, include_side=False, wall=CENTRE_WALL)
    assert set(placed) == {("movie", 0), ("movie", 1)}
    r0, r1 = placed[("movie", 0)], placed[("movie", 1)]

    orig0, orig1 = Rect(1920, 0, 1000, 500), Rect(3000, 100, 500, 300)
    scale0 = r0.w / orig0.w
    scale1 = r1.w / orig1.w
    assert scale0 == pytest.approx(scale1, abs=1e-9)

    dx_orig = orig1.x - orig0.x
    dx_placed = r1.x - r0.x
    assert dx_placed == pytest.approx(dx_orig * scale0, abs=0.05)


def test_fit_slide_full_wall_width_bound():
    # A full-wall item would be dropped as a backdrop by the `wall` filter, so this
    # exercises the fit math directly via `kept` (mirrors fit_item's own full-wall case).
    items = [_movie_item(0, x=0, y=0, w=7680, h=1080)]
    placed = fit_slide(items, BAND, include_side=True, kept=[("movie", 0)])
    r = placed[("movie", 0)]
    assert r.w == pytest.approx(1849.0, abs=0.1)
    assert r.h == pytest.approx(260.0, abs=0.1)


def test_fit_slide_union_uses_clipped_visible_extent():
    # A straddling item's off-centre portion must not widen the union used for the
    # shared scale -- fitting the raw item and a pre-clipped equivalent must agree.
    straddling = _movie_item(0, x=1800, y=0, w=300, h=1080)
    other = _movie_item(1, x=3000, y=100, w=500, h=300)
    placed_raw = fit_slide([straddling, other], BAND, include_side=False, wall=CENTRE_WALL)

    clipped = _movie_item(0, x=1920, y=0, w=180, h=1080)
    placed_clipped = fit_slide([clipped, other], BAND, include_side=False, wall=CENTRE_WALL)

    r_raw, r_clipped = placed_raw[("movie", 0)], placed_clipped[("movie", 0)]
    assert r_raw.x == pytest.approx(r_clipped.x, abs=0.05)
    assert r_raw.w == pytest.approx(r_clipped.w, abs=0.05)


def test_fit_slide_kept_param_restricts_items():
    items = [
        _movie_item(0, x=1920, y=0, w=1000, h=500),
        _movie_item(1, x=3000, y=100, w=500, h=300),
    ]
    placed = fit_slide(items, BAND, include_side=False, kept=[("movie", 0)])
    assert set(placed) == {("movie", 0)}


def test_fit_slide_wall_param_applies_classifier_filter():
    side_item = _movie_item(0, x=100, y=100, w=200, h=50)  # side panel only
    centre_item = _movie_item(1, x=3000, y=100, w=500, h=300)
    placed = fit_slide(
        [side_item, centre_item], BAND, include_side=False, wall=CENTRE_WALL
    )
    assert set(placed) == {("movie", 1)}


# --------------------------------------------------------------------------
# Zero-thickness lines -- visible per is_visible, must not vanish during fitting.
# --------------------------------------------------------------------------
def _line_item(kind_index, x, y, w, h):
    return {"kind": "line", "kindIndex": kind_index, "x": x, "y": y, "w": w, "h": h}


def test_classify_line_only_slide_is_static():
    slide = _slide(11, [_line_item(0, x=2000, y=500, w=400, h=0)])
    out = classify_slide(slide, None, CENTRE_WALL)
    assert out.category == "static"
    assert out.kept == (("line", 0),)


def test_fit_slide_line_only_keeps_zero_thickness():
    # No height constraint on a zero-height union: scale is set by width alone, so
    # the line stretches to the full band width and stays flat.
    items = [_line_item(0, x=2000, y=500, w=400, h=0)]
    placed = fit_slide(items, BAND, include_side=False, wall=CENTRE_WALL)
    r = placed[("line", 0)]
    assert r.h == 0.0
    assert r.w == pytest.approx(BAND.width, abs=0.1)


def test_fit_slide_line_and_image_shared_scale():
    line = _line_item(0, x=2000, y=500, w=400, h=0)
    image = _movie_item(1, x=1920, y=0, w=3840, h=1080)
    placed = fit_slide([line, image], BAND, include_side=False, wall=CENTRE_WALL)
    r_line, r_image = placed[("line", 0)], placed[("movie", 1)]
    assert r_line.h == 0.0
    scale = r_image.w / 3840.0
    assert r_line.w == pytest.approx(400.0 * scale, abs=0.1)


# --------------------------------------------------------------------------
# Deck-backed tests — real Sermon_PK decks; skipped when unavailable.
# --------------------------------------------------------------------------
def _require_deck(path):
    if not path.is_file():
        pytest.skip(f"deck not present (local operator file): {path}")
    try:
        import keynote_parser  # noqa: F401
    except Exception:
        pytest.skip("keynote-parser (iwa extra) not installed")


GW_CATEGORIES = {
    1: "empty", 2: "built", 3: "empty", 4: "empty", 5: "built", 6: "empty", 7: "built",
    8: "static", 9: "empty", 10: "static", 11: "static", 12: "static", 13: "static",
    14: "static", 15: "static", 16: "static", 17: "built", 18: "static", 19: "static",
    20: "built", 21: "static", 22: "static", 23: "empty", 24: "static", 25: "empty",
    26: "empty", 27: "empty", 28: "static", 29: "static", 30: "static", 31: "empty",
    32: "mixed", 33: "mixed", 34: "empty", 35: "static", 36: "static", 37: "built",
    38: "static", 39: "empty", 40: "empty", 41: "empty", 42: "static", 43: "empty",
    44: "built", 45: "static", 46: "static", 47: "empty", 48: "static", 49: "static",
    50: "static", 51: "static", 52: "static", 53: "static", 54: "built", 55: "static",
    56: "empty", 57: "static", 58: "empty", 59: "static", 60: "static", 61: "static",
    62: "empty", 63: "empty",
}

DSK_CATEGORIES = {
    1: "static", 2: "empty", 3: "static", 4: "empty", 5: "built", 6: "static",
    7: "static", 8: "static", 9: "static", 10: "static", 11: "static", 12: "static",
    13: "mixed", 14: "built", 15: "static", 16: "static", 17: "built", 18: "static",
    19: "static", 20: "static", 21: "static", 22: "static", 23: "static", 24: "static",
    25: "static", 26: "built", 27: "static", 28: "static", 29: "built", 30: "built",
    31: "empty", 32: "static", 33: "static", 34: "static", 35: "static", 36: "static",
    37: "static", 38: "static", 39: "empty", 40: "static", 41: "empty", 42: "static",
    43: "static",
}


def test_gw_deck_builds_and_categories():
    # Slides 3 and 6 carry real builds in the raw IWA graph but are marked
    # `isSkipped` in this deck, so classify_slide's skipped->empty rule zeroes
    # their build_count: {3, 6} are excluded here versus deck_builds' raw set.
    _require_deck(GW_DECK)
    from obed_edom.iwa_builds import deck_builds

    raw_built = {n for n, v in deck_builds(GW_DECK).items() if v["builds"]}
    assert raw_built == {2, 3, 5, 6, 7, 17, 20, 32, 33, 37, 44, 54}

    classes = {c.number: c for c in classify_deck(GW_DECK)}
    assert {n: c.category for n, c in classes.items()} == GW_CATEGORIES
    built_numbers = {n for n, c in classes.items() if c.build_count > 0}
    assert built_numbers == {2, 5, 7, 17, 20, 32, 33, 37, 44, 54}
    # Slides 7 and 37 each carry TSD.ConnectionLineArchive builds -- a kind
    # derive_kind_index never addresses, so deck_builds drops them; build_count
    # must still equal the raw per-slide build total via connection_line_builds.
    GW_BUILD_COUNTS = {2: 3, 5: 1, 7: 6, 17: 2, 20: 2, 32: 1, 33: 1, 37: 3, 44: 1, 54: 1}
    assert {n: c.build_count for n, c in classes.items() if c.build_count > 0} == GW_BUILD_COUNTS
    GW_CONNECTION_LINE_BUILDS = {7: 2, 37: 1}
    assert {
        n: c.connection_line_builds for n, c in classes.items() if c.connection_line_builds > 0
    } == GW_CONNECTION_LINE_BUILDS
    assert all(
        c.connection_line_builds == 0
        for n, c in classes.items()
        if n not in GW_CONNECTION_LINE_BUILDS
    )
    # Both slides carry a movie plus a kept build on another item: mixed, not movie.
    assert classes[32].category == "mixed"
    assert classes[32].movie_count == 1
    assert classes[32].build_count == 1
    assert classes[33].category == "mixed"
    assert classes[33].movie_count == 1
    assert classes[33].build_count == 1


def test_dsk_deck_builds():
    _require_deck(DSK_DECK)
    classes = {c.number: c for c in classify_deck(DSK_DECK)}
    assert {n: c.category for n, c in classes.items()} == DSK_CATEGORIES
    built_numbers = {n for n, c in classes.items() if c.build_count > 0}
    assert built_numbers == {5, 13, 14, 17, 26, 29, 30}
    DSK_BUILD_COUNTS = {5: 1, 13: 1, 14: 1, 17: 1, 26: 1, 29: 2, 30: 2}
    assert {n: c.build_count for n, c in classes.items() if c.build_count > 0} == DSK_BUILD_COUNTS
    # Slide 13's build resolves directly to its top-level movie (movie:0) via
    # iwa_builds.deck_builds; movie_count and build_count both being > 0 is what
    # makes it "mixed" here (see test_classify_group_child_build_counts_as_built
    # and test_classify_deck_nested_group_build below for the descendant-owned case).
    assert classes[13].category == "mixed"


def test_dsk_deck_band():
    _require_deck(DSK_DECK)
    band = read_band(DSK_DECK)
    assert band.bottom == 1054.0
    assert band.height == 350.0
    assert band.x_min == 43.0
    assert band.x_max == 1892.0
    assert band.sample_count == 4


def test_gw_deck_slide32_fitted_rect():
    _require_deck(DSK_DECK)
    _require_deck(GW_DECK)
    band = read_band(DSK_DECK)
    rect = fit_item(Rect(1920.0, -763.0, 3840.0, 2160.0), band)
    assert rect.w == pytest.approx(1244.4, abs=0.1)
    assert rect.h == pytest.approx(350.0, abs=0.1)
    assert rect.y == pytest.approx(704.0, abs=0.1)
