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
    TextBox,
    classify_deck,
    classify_slide,
    fit_item,
    fit_slide,
    fit_text_stack,
    is_panel_backdrop,
    mirror_duplicates,
    read_band,
    resolve_font_path,
    wrapped_height,
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


def test_classify_slide_surfaces_mirror_warnings():
    image_a = _image_item(2, 1954, 27, 1381, 921, "wheelchair.jpeg")
    image_b = _image_item(3, 2400, 27, 1381, 921, "wheelchair.jpeg")
    slide = _slide(9, [image_a, image_b])
    out = classify_slide(slide, _builds([]), CENTRE_WALL)
    assert len(out.mirror_warnings) == 1
    assert "not a L/R mirror" in out.mirror_warnings[0]


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
# panel-backdrop drop (D1/F3) — the verse-slide scrim that fills the centre
# panel but not the whole wall, so `is_backdrop` alone never catches it.
# --------------------------------------------------------------------------
def _shape_item(kind_index, x, y, w, h, text=""):
    return {"kind": "shape", "kindIndex": kind_index, "x": x, "y": y, "w": w, "h": h, "text": text}


def test_panel_backdrop_dropped_on_verse_slides():
    # shaped like GW 28's kept scrim (951,0,3840x1080) and GW 57's (2530,0,4482x1080).
    scrim_28 = _shape_item(0, x=951, y=0, w=3840, h=1080)
    badge = _text_item(0, x=2000, y=900, w=400, h=100)
    out_28 = classify_slide(_slide(28, [scrim_28, badge]), None, CENTRE_WALL, include_side=False)
    assert out_28.dropped_backdrop == (("shape", 0),)
    assert ("shape", 0) not in out_28.kept

    scrim_57 = _shape_item(0, x=2530, y=0, w=4482, h=1080)
    out_57 = classify_slide(_slide(57, [scrim_57, badge]), None, CENTRE_WALL, include_side=False)
    assert out_57.dropped_backdrop == (("shape", 0),)
    assert ("shape", 0) not in out_57.kept


def test_panel_backdrop_kept_when_sole_content():
    # GW 33's lone movie (1920,0,3840x1080) -- panel-sized but the slide's only content.
    movie = _movie_item(0, x=1920, y=0, w=3840, h=1080)
    out = classify_slide(_slide(33, [movie]), None, CENTRE_WALL, include_side=False)
    assert out.dropped_backdrop == ()
    assert out.kept == (("movie", 0),)


def test_is_panel_backdrop_tests_wall_frame_under_include_side():
    # Finding 5: include_side no longer skips the scrim test outright -- it tests against
    # the full wall frame instead of the centre panel.
    panel_scrim = _shape_item(0, x=951, y=0, w=3840, h=1080)
    assert is_panel_backdrop(panel_scrim, CENTRE_WALL, include_side=False) is True
    # panel-sized only -- doesn't cover the wider wall frame once side content is kept.
    assert is_panel_backdrop(panel_scrim, CENTRE_WALL, include_side=True) is False

    wall_scrim = _shape_item(0, x=40, y=0, w=7600, h=1080)
    assert is_panel_backdrop(wall_scrim, CENTRE_WALL, include_side=True) is True


# --------------------------------------------------------------------------
# mirror_duplicates (D1/F2) -- symmetric L/R authored pairs, survivor = lowest kindIndex.
# --------------------------------------------------------------------------
def _image_item(kind_index, x, y, w, h, file_name):
    return {"kind": "image", "kindIndex": kind_index, "x": x, "y": y, "w": w, "h": h, "fileName": file_name}


def test_mirror_duplicates_text_pair():
    # GW 17 text1/text4 (John 17:21 body): (1965,89,1468x193) / (4262,89,1468x193), on
    # opposite halves of the 7680 wall.
    same_text = "21 That all of them may be one..."
    text1 = _text_item(1, x=1965, y=89, w=1468, h=193)
    text1["text"] = same_text
    text4 = _text_item(4, x=4262, y=89, w=1468, h=193)
    text4["text"] = same_text
    dropped, warnings = mirror_duplicates([text1, text4], CENTRE_WALL)
    assert dropped == {("text", 4): ("text", 1)}
    assert len(warnings) == 1 and "single vote" in warnings[0]

    # GW 18 text1/text3 (Acts 4:31 body): exact mirror about the midline.
    text1b = _text_item(1, x=1965, y=89, w=1468, h=193)
    text1b["text"] = "31 After they prayed..."
    text3b = _text_item(3, x=4262, y=89, w=1468, h=193)
    text3b["text"] = "31 After they prayed..."
    dropped_b, warnings_b = mirror_duplicates([text1b, text3b], CENTRE_WALL)
    assert dropped_b == {("text", 3): ("text", 1)}
    assert len(warnings_b) == 1 and "single vote" in warnings_b[0]


def test_mirror_duplicates_image_pair():
    # GW 48 image2/image3 (wheelchair jpeg), measured: (1954,27,1381x921) / (4348,27,1381x921),
    # same fileName, opposite halves of the wall (F2/F4).
    image2 = _image_item(2, 1954, 27, 1381, 921, "WhatsApp Image 2026-08-14 at 09.17.25.jpeg")
    image3 = _image_item(3, 4348, 27, 1381, 921, "WhatsApp Image 2026-08-14 at 09.17.25.jpeg")
    dropped, warnings = mirror_duplicates([image2, image3], CENTRE_WALL)
    assert dropped == {("image", 3): ("image", 2)}
    assert len(warnings) == 1 and "single vote" in warnings[0]

    # GW 24-shaped: two same-file pairs at the deck's real image2/3 widths (504x919), each
    # placed as a mirror about the 3840 midline (synthetic positions -- the real GW 24
    # four-image "2x2 photo compare" swaps fileNames between its geometrically-mirrored
    # slots rather than repeating one file L/R, so it doesn't exercise this same-fileName
    # rule; see test_mirror_duplicates_gw24_cluster for the real cluster shape).
    image_a1 = _image_item(10, 1944, 23, 504, 919, "1.png")
    image_a2 = _image_item(11, 5232, 23, 504, 919, "1.png")
    image_b1 = _image_item(12, 2484, 23, 504, 919, "2.png")
    image_b2 = _image_item(13, 4692, 23, 504, 919, "2.png")
    dropped_24, warnings_24 = mirror_duplicates(
        [image_a1, image_a2, image_b1, image_b2], CENTRE_WALL
    )
    assert dropped_24 == {("image", 11): ("image", 10), ("image", 13): ("image", 12)}
    assert warnings_24 == ()


def test_mirror_duplicates_keeps_non_mirror_pair_with_warning():
    # same content, both on the same half of the wall -- not a L/R duplicate.
    image_a = _image_item(2, 1954, 27, 1381, 921, "wheelchair.jpeg")
    image_b = _image_item(3, 2400, 27, 1381, 921, "wheelchair.jpeg")
    dropped, warnings = mirror_duplicates([image_a, image_b], CENTRE_WALL)
    assert dropped == {}
    assert len(warnings) == 1
    assert "not a L/R mirror" in warnings[0]


def test_mirror_duplicates_gw24_cluster():
    # GW 24's real cluster, measured (content-rules-plan D1 finding 3): fileName "1.png"
    # is image2 (left) / image5 (right); fileName "2.png" is image3 (left) / image4
    # (right). Both same-fileName groups sit on opposite halves of the wall, so both
    # dedupe -- 4 items in, 2 survive, one of each file (kindIndex 2 and 3).
    image2 = _image_item(2, 1944, 23, 504, 919, "1.png")
    image3 = _image_item(3, 2484, 23, 504, 919, "2.png")
    image4 = _image_item(4, 5233, 23, 504, 919, "2.png")
    image5 = _image_item(5, 4693, 23, 504, 919, "1.png")
    dropped, warnings = mirror_duplicates([image2, image3, image4, image5], CENTRE_WALL)
    assert dropped == {("image", 5): ("image", 2), ("image", 4): ("image", 3)}
    assert warnings == ()


def test_mirror_duplicates_gw20_shaped_tail_survives_body_side():
    # GW 20-shaped (review round-2 finding 2): title text + title shape mirror pairs both
    # vote for the left copy (lower kindIndex is on the left in both), but the overflow
    # tail pair's own lowest kindIndex happens to sit on the right. Per-pair kindIndex alone
    # would let the tail survive from the opposite side of the body -- the slide-wide
    # majority vote must instead pull the tail survivor onto the same (left) side as the body.
    title_text_left = _text_item(0, x=2385, y=21, w=100, h=50)
    title_text_left["text"] = "Acts 4"
    title_text_right = _text_item(3, x=5355, y=21, w=100, h=50)
    title_text_right["text"] = "Acts 4"

    title_shape_left = _shape_item(0, x=2385, y=21, w=100, h=50, text="Acts 4 shape")
    title_shape_right = _shape_item(3, x=5355, y=21, w=100, h=50, text="Acts 4 shape")

    tail_right = _text_item(4, x=5389, y=413, w=100, h=50)
    tail_right["text"] = "in them all."
    tail_left = _text_item(5, x=3092, y=413, w=100, h=50)
    tail_left["text"] = "in them all."

    dropped, warnings = mirror_duplicates(
        [title_text_left, title_text_right, title_shape_left, title_shape_right, tail_right, tail_left],
        CENTRE_WALL,
    )
    assert dropped[("text", 3)] == ("text", 0)
    assert dropped[("shape", 3)] == ("shape", 0)
    # the tail survives from the left, matching the body -- not text4 (its own lower
    # kindIndex), which would detach it onto the opposite side of the wall from the verse.
    assert dropped[("text", 4)] == ("text", 5)
    assert len(warnings) == 1 and "margin of 1" in warnings[0]


def test_mirror_duplicates_gw7_shaped_keyless_pair():
    # GW 7-shaped (review round-3 finding 1): a text-keyed title pair and a group-keyed
    # badge pair both translate by 2446pt; a textless shape pair at the same translation
    # carries no content key and must be matched geometrically off that modal offset.
    text0 = _text_item(0, x=2385, y=21, w=100, h=50)
    text0["text"] = "Acts 7"
    text2 = _text_item(2, x=4831, y=21, w=100, h=50)
    text2["text"] = "Acts 7"

    group0 = _group_item(0, x=2640, y=100, w=526, h=98)
    group1 = _group_item(1, x=5086, y=100, w=526, h=98)

    shape1 = _shape_item(1, x=2813, y=200, w=187, h=83)
    shape3 = _shape_item(3, x=5259, y=200, w=187, h=83)

    dropped, warnings = mirror_duplicates(
        [text0, text2, group0, group1, shape1, shape3],
        CENTRE_WALL,
        group_child_text={0: "badge", 1: "badge"},
    )
    assert dropped[("text", 2)] == ("text", 0)
    assert dropped[("group", 1)] == ("group", 0)
    assert dropped[("shape", 3)] == ("shape", 1)
    assert warnings == ()


def test_mirror_duplicates_gw24_shaped_keyless_pairs():
    # GW 24-shaped (review round-3 finding 1): two same-file image pairs establish a modal
    # 2749pt translation; two textless shape pairs at that same translation are keyless and
    # must be matched geometrically, not dropped as unresolved duplicates.
    image2 = _image_item(2, 1944, 27, 504, 919, "1.png")
    image3 = _image_item(3, 2484, 27, 504, 919, "2.png")
    image4 = _image_item(4, 5233, 27, 504, 919, "2.png")
    image5 = _image_item(5, 4693, 27, 504, 919, "1.png")

    shape0 = _shape_item(0, x=2536, y=27, w=388, h=325)
    shape2 = _shape_item(2, x=5285, y=27, w=388, h=325)
    shape1 = _shape_item(1, x=2536, y=400, w=388, h=140)
    shape3 = _shape_item(3, x=5285, y=400, w=388, h=140)

    dropped, warnings = mirror_duplicates(
        [image2, image3, image4, image5, shape0, shape1, shape2, shape3], CENTRE_WALL
    )
    assert dropped[("image", 5)] == ("image", 2)
    assert dropped[("image", 4)] == ("image", 3)
    assert dropped[("shape", 2)] == ("shape", 0)
    assert dropped[("shape", 3)] == ("shape", 1)
    assert warnings == ()


def test_mirror_duplicates_gw50_shaped_right_survivor_keyless_pair():
    # GW 50-shaped (review round-4 finding 1): the confirmed pair's survivor is on the
    # right, so off = dupe_cx - survivor_cx is negative; the keyless pass must still match
    # a shape pair whose kindIndex order runs left-to-right (a positive geometric delta).
    group0 = _group_item(0, x=4642, y=100, w=526, h=98)
    group1 = _group_item(1, x=2393, y=100, w=526, h=98)

    shape1 = _shape_item(1, x=2562.5, y=200, w=187, h=83)
    shape3 = _shape_item(3, x=4811.5, y=200, w=187, h=83)

    dropped, warnings = mirror_duplicates(
        [group0, group1, shape1, shape3],
        CENTRE_WALL,
        group_child_text={0: "badge", 1: "badge"},
    )
    assert dropped[("group", 1)] == ("group", 0)
    assert dropped[("shape", 1)] == ("shape", 3)
    assert len(warnings) == 1 and "single vote" in warnings[0]


def test_mirror_duplicates_group_same_text_differing_media_not_deduped():
    # Review round-2 finding 1: same caption, different child imagery must not dedupe --
    # the group identity has to be a complete content signature, not text alone.
    group0 = _group_item(0, x=2640, y=100, w=526, h=98)
    group1 = _group_item(1, x=5086, y=100, w=526, h=98)

    dropped, warnings = mirror_duplicates(
        [group0, group1],
        CENTRE_WALL,
        group_child_text={0: "text:badge\nimage:left.png", 1: "text:badge\nimage:right.png"},
    )
    assert dropped == {}
    assert warnings == ()


def test_mirror_duplicates_group_unresolved_signature_keeps_and_warns():
    # Review round-2 finding 1: when a group's content signature can't be established
    # (e.g. unresolved child media), both items are kept and a warning is raised.
    group0 = _group_item(0, x=2640, y=100, w=526, h=98)
    group1 = _group_item(1, x=5086, y=100, w=526, h=98)

    dropped, warnings = mirror_duplicates(
        [group0, group1],
        CENTRE_WALL,
        group_child_text={0: None, 1: None},
    )
    assert dropped == {}
    assert len(warnings) == 2
    assert all("unresolved" in w for w in warnings)


def test_mirror_duplicates_group_empty_signature_map_still_warns():
    # Review round-3 finding 2: an empty/absent mapping must still warn per missing group,
    # not silently keep everything.
    group0 = _group_item(0, x=2640, y=100, w=526, h=98)
    group1 = _group_item(1, x=5086, y=100, w=526, h=98)

    dropped, warnings = mirror_duplicates([group0, group1], CENTRE_WALL, group_child_text={})
    assert dropped == {}
    assert len(warnings) == 2
    assert all("missing content signature" in w for w in warnings)


def test_mirror_duplicates_keyless_pass_keeps_same_side_pair():
    # Finding 3: two identical textless shapes on the same side of the wall, separated by
    # the slide's modal translation, must not be treated as a mirror -- only cross-wall
    # keyless pairs are dedupe candidates.
    text0 = _text_item(0, x=2385, y=21, w=100, h=50)
    text0["text"] = "Acts 7"
    text2 = _text_item(2, x=4831, y=21, w=100, h=50)
    text2["text"] = "Acts 7"

    shape1 = _shape_item(1, x=2813, y=200, w=187, h=83)
    shape2 = _shape_item(2, x=5259, y=200, w=187, h=83)
    same_side_a = _shape_item(3, x=100, y=400, w=187, h=83)
    same_side_b = _shape_item(4, x=2546, y=400, w=187, h=83)

    dropped, _ = mirror_duplicates(
        [text0, text2, shape1, shape2, same_side_a, same_side_b], CENTRE_WALL
    )
    assert dropped[("shape", 2)] == ("shape", 1)
    assert ("shape", 4) not in dropped
    assert ("shape", 3) not in dropped


def test_mirror_duplicates_keyless_pair_needs_confirmed_pairs():
    # negative: no keyed pairs at all -- the geometric pass never runs, so two equal-sized
    # textless shapes at a plausible separation are kept, not invented as a mirror pair.
    shape_a = _shape_item(0, x=2536, y=27, w=388, h=325)
    shape_b = _shape_item(1, x=5285, y=27, w=388, h=325)
    dropped, warnings = mirror_duplicates([shape_a, shape_b], CENTRE_WALL)
    assert dropped == {}
    assert warnings == ()


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

    classes = {c.number: c for c in dsk_plan.classify_deck("unused.key", deck=(objects, {}, {}), payload=payload)}
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

    classes = {c.number: c for c in dsk_plan.classify_deck("unused.key", deck=(objects, {}, {}), payload=payload)}
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


def test_fit_slide_wall_and_kept_agree_after_dedupe_gw17_shaped():
    # Review round-2 finding 1: `fit_slide(wall=...)` must see the same deduped kept set as
    # `fit_slide(kept=classify_slide(...).kept)` -- GW17-shaped mirrored verse body, one
    # authored copy left, one right, identical text.
    text1 = _text_item(1, x=1965, y=169, w=1468, h=193)
    text1["text"] = "21 That all of them may be one..."
    text4 = _text_item(4, x=4262, y=169, w=1468, h=193)
    text4["text"] = "21 That all of them may be one..."
    items = [text1, text4]

    cls = classify_slide(_slide(17, items), None, CENTRE_WALL)
    assert cls.kept == (("text", 1),)
    assert cls.dropped_duplicate == (("text", 4),)

    fit_wall = fit_slide(items, BAND, include_side=False, wall=CENTRE_WALL)
    fit_kept = fit_slide(items, BAND, include_side=False, kept=cls.kept)
    assert fit_wall == fit_kept

    # Fitted from the surviving copy's own 1468x193 extent alone -- not the duplicate
    # union (which would span the whole wall and squeeze the verse into its left third) --
    # so it lands exactly where a single unmirrored copy would, centred in the band.
    rect = fit_wall[("text", 1)]
    expected = fit_item(Rect(1965.0, 169.0, 1468.0, 193.0), BAND)
    assert rect.x == pytest.approx(expected.x, abs=0.1)
    assert rect.y == pytest.approx(expected.y, abs=0.1)
    assert rect.w == pytest.approx(expected.w, abs=0.1)
    assert rect.h == pytest.approx(expected.h, abs=0.1)


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
    # GW 33's panel-filling movie rect; is_panel_backdrop only ever matches shapes (D1),
    # so a panel-sized movie is never dropped alongside other kept content.
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
    # must still equal the raw per-slide build total via connection_line_builds, minus
    # any build whose drawable is dropped as a mirror duplicate (7, 17, 20; F2), including
    # slide 7's keyless shape3 badge (round-3 finding 1).
    GW_BUILD_COUNTS = {2: 3, 5: 1, 7: 4, 17: 1, 20: 1, 32: 1, 33: 1, 37: 3, 44: 1, 54: 1}
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


# --------------------------------------------------------------------------
# wrapped_height / fit_text_stack -- the wrap estimator (F9, D4, step 5).
# --------------------------------------------------------------------------

TEXT_BAND = Band(1054.0, 350.0, 43.0, 1892.0, 4)


def _require_font(name):
    if resolve_font_path(name) is None:
        pytest.skip(f"font not present on this machine: {name}")


def test_wrapped_height_matches_golden_boxes():
    # F9's golden-box height model, exercised against every long text box of the actual
    # golden deck (the DSK deck, not GW): predicted lines within a one-sided upper bound
    # of the item's own laid-out height at its own (unscaled) size and width. Only the
    # over-prediction direction is policed: `observed` is the item's frame height, an
    # upper bound on the actual laid-out text, so under-prediction is not necessarily
    # estimator error.
    # ArgentCF-Bold over-predicts by >2 lines (golden slide 33) -- a known predictor
    # limit on that font, xfailed by name rather than hidden by scoping the test down.
    _require_deck(DSK_DECK)
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    from obed_edom.dsk_assemble import load_assembly_inputs

    payload, classes, _runs = load_assembly_inputs(DSK_DECK)
    by_number = {c.number: c for c in classes}
    slides_by_number = {s["number"]: s for s in payload["slides"]}
    checked = 0
    failures = []
    for number, cls in by_number.items():
        if number == 33:
            continue
        items_by_id = {(i["kind"], i["kindIndex"]): i for i in slides_by_number[number]["items"]}
        for item_id in cls.long_text_ids:
            item = items_by_id[item_id]
            font, size = item.get("font"), item.get("size")
            if not font or not size:
                continue
            predicted = wrapped_height(item["text"], font, size, item["w"])
            assert predicted is not None
            observed_lines = (item["h"] - 21.0) / (1.157 * size)
            predicted_lines = (predicted - 21.0) / (1.157 * size)
            checked += 1
            if not (predicted_lines - observed_lines <= 1.0 + 1e-2):
                failures.append((number, item_id, predicted_lines - observed_lines))
    assert checked >= 29
    assert not failures, failures


@pytest.mark.xfail(reason="ArgentCF-Bold over-predicts golden slide 33 by >2 lines -- known predictor limit")
def test_wrapped_height_golden_slide_33_argentcf_bold():
    _require_deck(DSK_DECK)
    _require_font("ArgentCF-Bold")
    from obed_edom.dsk_assemble import load_assembly_inputs

    payload, classes, _runs = load_assembly_inputs(DSK_DECK)
    by_number = {c.number: c for c in classes}
    slides_by_number = {s["number"]: s for s in payload["slides"]}
    cls = by_number[33]
    items_by_id = {(i["kind"], i["kindIndex"]): i for i in slides_by_number[33]["items"]}
    (item_id,) = cls.long_text_ids
    item = items_by_id[item_id]
    font, size = item["font"], item["size"]
    predicted = wrapped_height(item["text"], font, size, item["w"])
    assert predicted is not None
    observed_lines = (item["h"] - 21.0) / (1.157 * size)
    predicted_lines = (predicted - 21.0) / (1.157 * size)
    assert predicted_lines - observed_lines <= 1.0 + 1e-6


def test_wrapped_height_missing_font_warns():
    assert resolve_font_path("NotARealFontXYZ") is None
    assert wrapped_height("hello world", "NotARealFontXYZ", 40.0, 1849.0) is None


def test_fit_text_stack_bare_band_ordering():
    # Unit test of fit_text_stack alone against a bare band with no badge subtracted --
    # not the shipped product t (see test_gw13_gw17_stack_budget_and_fit_t_under_default_band
    # for that, computed through the badge-aware per-slide budget).
    _require_deck(GW_DECK)
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    from obed_edom.dsk_assemble import load_assembly_inputs

    payload, classes, _runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    slides_by_number = {s["number"]: s for s in payload["slides"]}

    def _t_for(number):
        cls = by_number[number]
        items_by_id = {(i["kind"], i["kindIndex"]): i for i in slides_by_number[number]["items"]}
        boxes = [
            TextBox(iid, items_by_id[iid]["text"], items_by_id[iid]["font"], items_by_id[iid]["size"])
            for iid in cls.long_text_ids
        ]
        result = fit_text_stack(boxes, TEXT_BAND, 24.0)
        assert result is not None
        return result[0]

    t17, t38, t49 = _t_for(17), _t_for(38), _t_for(49)
    assert t17 > t49  # heavier GW 49 badge needs more shrink than the two-box GW 17
    assert t17 == pytest.approx(0.87, abs=0.02)
