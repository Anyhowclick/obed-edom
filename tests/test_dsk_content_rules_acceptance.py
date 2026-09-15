"""Step 11 acceptance: `classify_deck` + `load_assembly_inputs` + `plan_assembly` over the
real `Sermon_PK (GW).key`, one row per the plan's Acceptance table
(`.agents/plans/dsk_content_rules.plan.md`).

Every number here was read back from the deck with these same three functions, not typed
from the plan's prose -- where the plan's table and the measurement disagreed, the plan was
corrected to match this file (GW 5's anchor/crop box, and GW 13/17's t after pass 1 started
using the run-aware wrap estimator instead of the single-font one). Tolerances are 0.5 pt.

All tests are `@pytest.mark.deck` and skip when the GW deck or the `keynote_parser` (iwa)
extra is absent, via the same `_require_gw_deck` skip helper `tests/test_dsk_plan.py`/
`tests/test_dsk_assemble.py` use.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import obed_edom.dsk_assemble as dsa
from obed_edom.dsk_assemble import (
    DEFAULT_BAND,
    SlideDecision,
    load_assembly_inputs,
    plan_assembly,
)
from obed_edom.dsk_plan import classify_deck, resolve_font_path
from obed_edom.map_remap import Rect, item_rect

GW_DECK = Path("/Users/anyhowclick/Desktop/Diff-Checker/Sermon_PK (GW).key")


def _require_gw_deck():
    if not GW_DECK.is_file():
        pytest.skip(f"deck not present (local operator file): {GW_DECK}")
    try:
        import keynote_parser  # noqa: F401
    except Exception:
        pytest.skip("keynote-parser (iwa extra) not installed")


def _require_font(name):
    if resolve_font_path(name) is None:
        pytest.skip(f"font not present on this machine: {name}")


@pytest.fixture(scope="module")
def gw_inputs():
    _require_gw_deck()
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    return payload, {c.number: c for c in classes}, runs


def _plan_one(payload, cls, runs, by_number, *, min_text_pt=dsa.DEFAULT_MIN_TEXT_PT, crop_dir=None, deck=None):
    decisions = {cls.number: SlideDecision(cls.number, "in_deck", anchor="auto")}
    kwargs = dict(band=DEFAULT_BAND, clips={}, runs=runs, min_text_pt=min_text_pt, all_classes=list(by_number.values()))
    if crop_dir is not None:
        kwargs.update(deck=deck, fw_deck=GW_DECK, crop_dir=crop_dir)
    return plan_assembly(payload, [cls], decisions=decisions, **kwargs)


@pytest.mark.deck
def test_gw13_single_text_verse_box_no_split(gw_inputs):
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, by_number, runs = gw_inputs
    cls = by_number[13]
    plan = _plan_one(payload, cls, runs, by_number)

    verse = plan.fits[13][("text", 1)]
    assert verse.x == pytest.approx(43.0, abs=0.5)
    assert verse.w == pytest.approx(1849.0, abs=0.5)
    assert plan.parts.get(13, 1) == 1
    assert 13 not in plan.splits

    run_sizes = sorted({size for _, _, size in plan.run_sizes[13][("text", 1)]})
    assert run_sizes == pytest.approx([56.0, 68.0], abs=0.01)


@pytest.mark.deck
def test_gw17_dedupe_and_stretch_no_overlap(gw_inputs):
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, by_number, runs = gw_inputs
    cls = by_number[17]
    assert {("text", 3), ("text", 4), ("text", 5)} <= set(cls.dropped_duplicate)

    plan = _plan_one(payload, cls, runs, by_number)
    stacked = plan.stacked_ids[17]
    assert stacked == frozenset({("text", 1), ("text", 2)})
    rects = [plan.fits[17][iid] for iid in stacked]
    top, bottom = sorted(rects, key=lambda r: r.y)
    assert top.y + top.h <= bottom.y + 1e-6

    ranges17 = plan.run_sizes[17][("text", 1)]
    assert [(start, end) for start, end, _ in ranges17] == [(1, 3), (4, 20), (21, 30), (31, 79)]
    assert [size for _, _, size in ranges17] == pytest.approx([44.1, 44.1, 53.55, 44.1], abs=0.01)
    t17 = ranges17[0][2] / 70.0
    assert t17 == pytest.approx(0.63, abs=0.01)


@pytest.mark.deck
def test_gw17_forced_split_at_min_text_pt_66(gw_inputs):
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, by_number, runs = gw_inputs
    cls = by_number[17]
    plan = _plan_one(payload, cls, runs, by_number, min_text_pt=66)

    assert plan.parts[17] == 2
    assert plan.ordinal_to_number == {1: 17, 2: 17}
    parts = plan.splits[17]
    assert len(parts) == 2
    for part in parts:
        long_ids = [iid for iid in part.fits if iid[0] == "text" and iid not in (("text", 0),)]
        assert len(long_ids) == 1
        assert ("shape", 0) in part.fits
        assert ("text", 0) in part.fits


@pytest.mark.deck
def test_gw28_panel_backdrop_dropped(gw_inputs):
    _require_gw_deck()
    payload, by_number, runs = gw_inputs
    cls = by_number[28]
    assert ("shape", 0) in cls.dropped_backdrop

    slide28 = next(s for s in payload["slides"] if s["number"] == 28)
    shape0 = next(i for i in slide28["items"] if (i["kind"], i["kindIndex"]) == ("shape", 0))
    assert item_rect(shape0) == Rect(951.0, 0.0, 3840.0, 1080.0)

    plan = _plan_one(payload, cls, runs, by_number)
    verse = next(i for i in slide28["items"] if (i["kind"], i["kindIndex"]) == ("text", 1))
    fitted = plan.fits[28][("text", 1)]
    scale = fitted.w / item_rect(verse).w
    assert scale > 0.8


@pytest.mark.deck
def test_gw48_wheelchair_dedupe_and_right_no_crop(gw_inputs):
    _require_gw_deck()
    payload, by_number, runs = gw_inputs
    cls = by_number[48]
    assert cls.kept == (("image", 2),)
    assert ("image", 3) in cls.dropped_duplicate

    plan = _plan_one(payload, cls, runs, by_number)
    assert plan.anchors[48] == "right"
    fitted = plan.fits[48][("image", 2)]
    assert fitted.x + fitted.w == pytest.approx(1892.0, abs=0.5)
    assert plan.crops.get(48) in (None, {})


@pytest.mark.deck
def test_gw24_dedupe_four_to_two_right(gw_inputs):
    _require_gw_deck()
    payload, by_number, runs = gw_inputs
    cls = by_number[24]
    kept_images = [iid for iid in cls.kept if iid[0] == "image"]
    dropped_images = [iid for iid in cls.dropped_duplicate if iid[0] == "image"]
    assert len(kept_images) == 2
    assert len(dropped_images) == 2

    plan = _plan_one(payload, cls, runs, by_number)
    assert plan.anchors[24] == "right"
    fitted = [plan.fits[24][iid] for iid in kept_images]
    assert max(r.x + r.w for r in fitted) == pytest.approx(1892.0, abs=0.5)


@pytest.mark.deck
def test_gw16_diptych_union_centred(gw_inputs):
    # Two clipped LW-panel halves (aspect 1.77 each) whose union is 3840x1080
    # (aspect 3.56) -- the union-of-kept-rects fix (opus review 1, finding 1)
    # centres this panel-wide two-up instead of right-flushing it.
    _require_gw_deck()
    payload, by_number, runs = gw_inputs
    cls = by_number[16]
    plan = _plan_one(payload, cls, runs, by_number)
    assert plan.anchors[16] == "centre"


@pytest.mark.deck
def test_gw22_diptych_union_centred(gw_inputs):
    # Same shape as GW 16: two clipped LW-panel halves whose union is LW-dimension.
    _require_gw_deck()
    payload, by_number, runs = gw_inputs
    cls = by_number[22]
    plan = _plan_one(payload, cls, runs, by_number)
    assert plan.anchors[22] == "centre"


@pytest.mark.deck
def test_gw21_image_crop_centred(gw_inputs, tmp_path):
    # 4494x1265 post-crop (aspect 3.55) is LW-dimension, so the shape rule centres it.
    _require_gw_deck()
    payload, by_number, runs = gw_inputs
    cls = by_number[21]
    deck = dsa._load_deck(GW_DECK)
    plan = _plan_one(payload, cls, runs, by_number, crop_dir=tmp_path / "crops21", deck=deck)

    crop = plan.crops[21][("image", 0)]
    assert crop.px_box == (57, 1100, 4551, 2365)
    assert crop.source_file_name == "Yang Zheng_YZ_0125.JPG"
    assert crop.visible == Rect(1920.0, 0.0, 3840.0, 1080.0)
    assert crop.path.is_file()

    fitted = plan.fits[21][("image", 0)]
    assert fitted.x + fitted.w / 2.0 == pytest.approx(967.5, abs=0.5)
    assert plan.anchors[21] == "centre"


@pytest.mark.deck
def test_gw5_group_verse_text_slide_no_image(gw_inputs, tmp_path):
    # D1 (Design A): GW 5's group holds a 32-word verse child -> the slide is TEXT, the
    # full-wall photo (and side panels/scrim) is dropped like any other text-slide media,
    # and the group's two children (badge + verse) are stacked into the band directly --
    # no crop, no affine group write. Supersedes the pre-D1 "image crop, right-aligned"
    # expectation the plan's Acceptance table originally carried for this slide.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    payload, by_number, runs = gw_inputs
    cls = by_number[5]
    deck = dsa._load_deck(GW_DECK)
    assert cls.is_text
    assert cls.long_text_ids == (("groupchild", 0, "text", 1),)
    assert ("image", 0) in cls.dropped_media_text

    plan = _plan_one(payload, cls, runs, by_number, crop_dir=tmp_path / "crops5", deck=deck)

    assert not plan.crops.get(5)
    assert ("image", 0) not in plan.fits[5]
    assert ("group", 0) not in plan.fits[5]
    for iid in (("image", 0), ("image", 1), ("image", 2), ("shape", 0)):
        assert iid in plan.deletes[5]

    verse = plan.fits[5][("groupchild", 0, "text", 1)]
    badge = plan.fits[5][("groupchild", 0, "shape", 0)]
    band_top = DEFAULT_BAND.bottom - DEFAULT_BAND.height
    for rect in (verse, badge):
        assert rect.y >= band_top - 0.5
        assert rect.y + rect.h <= DEFAULT_BAND.bottom + 0.5
    assert badge.y + badge.h <= verse.y + 0.5  # badge above verse


@pytest.mark.deck
def test_gw50_51_mirror_pair_dedupe_ahead_of_group_classifier(gw_inputs):
    # GW 50/51: two coincident groups, each holding the same long verse child (D1's
    # mirror_duplicates must stay in front of the group-text classifier). Dedupe drops
    # one whole group (('group', 1)); its own groupchild long id must not survive that
    # drop even though it was derived from the group AFTER dedupe's own item-level check.
    _require_gw_deck()
    _payload, by_number, _runs = gw_inputs
    for number in (50, 51):
        cls = by_number[number]
        assert cls.dropped_duplicate == (("group", 1),)
        assert cls.is_text
        assert cls.long_text_ids == (("groupchild", 0, "text", 1),)
        assert ("group", 1) not in cls.kept


@pytest.mark.deck
def test_gw33_movie_kept_as_sole_content_classify_only(gw_inputs):
    # GW 33's clip is not part of this worktree's banked clips, so plan_assembly's
    # clip-path requirement is exercised only via classification -- the classifier alone
    # already proves R2's backdrop-exemption rule (a panel-sized movie survives as a
    # slide's only content). The movie is 3840x1080 (aspect 3.56), LW-dimension, so the
    # shape rule would centre it despite being the slide's sole content item.
    _require_gw_deck()
    payload, by_number, _runs = gw_inputs
    cls = by_number[33]
    assert cls.kept == (("movie", 0),)
    assert cls.movie_count == 1
    assert cls.category == "mixed"
    slide33 = next(s for s in payload["slides"] if s["number"] == 33)
    wall = (payload["slideWidth"], payload["slideHeight"])
    assert dsa._content_anchor(cls, slide33["items"], include_side=False, wall=wall) == "centre"


@pytest.mark.deck
def test_gw32_movie_classify_side_panels_dropped(gw_inputs):
    _require_gw_deck()
    payload, by_number, _runs = gw_inputs
    cls = by_number[32]
    assert cls.kept == (("movie", 0),)
    assert set(cls.dropped_side) == {("image", 0), ("image", 1)}
    slide32 = next(s for s in payload["slides"] if s["number"] == 32)
    wall = (payload["slideWidth"], payload["slideHeight"])
    assert dsa._content_anchor(cls, slide32["items"], include_side=False, wall=wall) == "centre"


@pytest.mark.deck
def test_gw8_include_side_unchanged_classification():
    _require_gw_deck()
    classes_default = {c.number: c for c in classify_deck(GW_DECK)}
    classes_side = {c.number: c for c in classify_deck(GW_DECK, include_side=frozenset({8}))}
    default8 = classes_default[8]
    side8 = classes_side[8]
    assert side8.kept == default8.kept
    assert side8.dropped_duplicate == default8.dropped_duplicate
    assert side8.dropped_backdrop == default8.dropped_backdrop
    assert side8.category == default8.category

    # kept/duplicate/backdrop/category are unchanged, but the side images don't survive
    # untouched: --include-side 8 lets them past the side filter, then the text-slide
    # media rule drops them instead -- dropped_side and dropped_media_text swap.
    assert default8.dropped_side == (("image", 1), ("image", 2))
    assert default8.dropped_media_text == ()
    assert side8.dropped_side == ()
    assert side8.dropped_media_text == (("image", 1), ("image", 2))


# D1b -- two-column heading+verse band (`.agents/plans/dsk_pieceD1b.plan.md` Section 6).
# GW 44/46/50 numbers below are measured from `plan_assembly`'s own output, not typed
# from the plan doc's pre-implementation estimates -- GW46's heading y/height and the
# verse's run-size lead came out ~1-5pt off the doc's estimate (real wrapped-height
# rounding against the doc's hand math); those two are pinned to the measured value.


@pytest.mark.deck
def test_gw44_two_column_heading_and_verse(gw_inputs):
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    payload, by_number, runs = gw_inputs
    plan = _plan_one(payload, by_number[44], runs, by_number)

    heading = plan.fits[44][("text", 1)]
    badge = plan.fits[44][("shape", 0)]
    verse_badge = plan.fits[44][("groupchild", 0, "shape", 0)]
    verse = plan.fits[44][("groupchild", 0, "text", 1)]

    assert heading.x == pytest.approx(43.0, abs=0.5)
    assert heading.y == pytest.approx(834.8, abs=0.5)
    assert heading.w == pytest.approx(450.0, abs=0.5)
    assert heading.h == pytest.approx(159.8, abs=0.5)
    assert plan.text_sizes[44][("text", 1)] == pytest.approx(60.0, abs=0.01)

    assert badge.x == pytest.approx(245.0, abs=0.5)
    assert badge.y == pytest.approx(778.8, abs=0.5)
    assert badge.w == pytest.approx(46.0, abs=0.01)
    assert badge.h == pytest.approx(46.0, abs=0.01)

    assert verse_badge.x == pytest.approx(501.0, abs=0.5)
    assert verse_badge.y == pytest.approx(719.4, abs=0.5)
    assert verse_badge.w == pytest.approx(645.03, abs=0.5)
    assert verse_badge.h == pytest.approx(92.0, abs=0.5)
    # finding gw44-group-badge: the badge is a dual shape+text group child, so its
    # caption must get an explicit size write -- it used to be invisible to the
    # planner entirely (`iwa_runs._group_child_runs` keyed it under "text"'s own
    # counter, never the "shape" counter this id addresses).
    assert plan.text_sizes[44][("groupchild", 0, "shape", 0)] == pytest.approx(40.0, abs=0.01)

    assert verse.x == pytest.approx(501.0, abs=0.5)
    assert verse.y == pytest.approx(821.4, abs=0.5)
    assert verse.w == pytest.approx(1391.0, abs=0.5)
    assert verse.h == pytest.approx(232.6, abs=0.5)
    assert plan.stack_t[44] == pytest.approx(0.59, abs=0.01)

    lead = min(size for _s, _e, size in plan.run_sizes[44][("groupchild", 0, "text", 1)])
    assert lead == pytest.approx(41.3, abs=0.5)
    assert 44 not in plan.splits
    assert plan.stack_bands[44].x_min == pytest.approx(501.0, abs=0.01)
    assert plan.two_column[44].x_max == pytest.approx(493.0, abs=0.01)


@pytest.mark.deck
def test_gw50_two_column_heading_and_verse(gw_inputs):
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    payload, by_number, runs = gw_inputs
    plan = _plan_one(payload, by_number[50], runs, by_number)

    heading = plan.fits[50][("text", 1)]
    badge = plan.fits[50][("shape", 0)]
    verse_badge = plan.fits[50][("groupchild", 0, "shape", 0)]
    verse = plan.fits[50][("groupchild", 0, "text", 1)]

    assert heading.x == pytest.approx(43.0, abs=0.5)
    assert heading.y == pytest.approx(858.2, abs=0.5)
    assert heading.w == pytest.approx(450.0, abs=0.5)
    assert heading.h == pytest.approx(113.6, abs=0.5)
    assert plan.text_sizes[50][("text", 1)] == pytest.approx(80.0, abs=0.01)

    assert badge.x == pytest.approx(245.0, abs=0.5)
    assert badge.y == pytest.approx(802.2, abs=0.5)

    assert verse_badge.x == pytest.approx(501.0, abs=0.5)
    assert verse_badge.y == pytest.approx(720.0, abs=0.5)
    assert verse_badge.w == pytest.approx(645.03, abs=0.5)
    assert verse_badge.h == pytest.approx(92.0, abs=0.5)
    assert plan.text_sizes[50][("groupchild", 0, "shape", 0)] == pytest.approx(40.0, abs=0.01)

    assert verse.x == pytest.approx(501.0, abs=0.5)
    assert verse.y == pytest.approx(822.0, abs=0.5)
    assert verse.w == pytest.approx(1391.0, abs=0.5)
    assert verse.h == pytest.approx(232.0, abs=0.5)
    assert plan.stack_t[50] == pytest.approx(0.48, abs=0.01)

    lead = min(size for _s, _e, size in plan.run_sizes[50][("groupchild", 0, "text", 1)])
    assert lead == pytest.approx(33.6, abs=0.5)
    assert 50 not in plan.splits


@pytest.mark.deck
def test_gw46_two_column_top_level_verse(gw_inputs):
    # GW46 is the deck's other top-level (non-groupchild) heading+verse slide; its real
    # predecessor GW45 ("Prayer", heading-only) shares GW46's heading text, but the
    # owner-pinned rule (D1b-p2 fix round 2) suppresses a repeat only when the
    # predecessor is itself heading+verse -- GW45 is heading-only, so GW46 keeps its
    # heading and stays two-column, matching gold 30. Re-measured against fix round 2's
    # code: t and lead land on round 1's original pin (t=0.65, lead 45.5), unchanged
    # from the pre-round-1 values -- the real `wrapped_height`/`fit_text_stack` numbers
    # for GW46's actual badge geometry (a top-level 522.57x74.54 shape+text pair, not
    # the 645x92 group-child badge the other five slides share).
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    payload, by_number, runs = gw_inputs
    plan = _plan_one(payload, by_number[46], runs, by_number)

    assert 46 in plan.two_column
    heading = plan.fits[46][("text", 3)]
    badge = plan.fits[46][("shape", 0)]
    verse = plan.fits[46][("text", 2)]

    assert heading.x == pytest.approx(43.0, abs=0.5)
    assert heading.w == pytest.approx(450.0, abs=0.5)
    assert heading.h == pytest.approx(113.56, abs=0.5)
    assert plan.text_sizes[46][("text", 3)] == pytest.approx(80.0, abs=0.01)

    assert badge.x == pytest.approx(245.0, abs=0.5)
    assert badge.w == pytest.approx(46.0, abs=0.01)
    assert badge.h == pytest.approx(46.0, abs=0.01)

    assert verse.x == pytest.approx(501.0, abs=0.5)
    assert verse.w == pytest.approx(1391.0, abs=0.5)
    assert plan.stack_t[46] == pytest.approx(0.65, abs=0.01)

    lead = min(size for _s, _e, size in plan.run_sizes[46][("text", 2)])
    assert lead == pytest.approx(45.5, abs=0.5)
    assert 46 not in plan.splits


@pytest.mark.deck
def test_gw51_52_53_repeat_heading_dropped_full_width(gw_inputs):
    # Owner Q1: GW 50's heading ("Faith") repeats verbatim on 51/52/53 -- gold drops it
    # from all three (gold 35/36/37), keeping the full-width single-column verse.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, by_number, runs = gw_inputs
    decisions = {n: SlideDecision(n, "in_deck", anchor="auto") for n in (50, 51, 52, 53)}
    plan = plan_assembly(
        payload, [by_number[n] for n in (50, 51, 52, 53)],
        decisions=decisions, band=DEFAULT_BAND, clips={}, runs=runs,
        all_classes=list(by_number.values()),
    )

    assert plan.two_column.get(50) is not None
    for number, verse_id in (
        (51, ("groupchild", 0, "text", 1)),
        (52, ("text", 1)),
        (53, ("groupchild", 0, "text", 1)),
    ):
        assert number not in plan.two_column
        verse = plan.fits[number][verse_id]
        assert verse.x == pytest.approx(43.0, abs=0.5)
        assert verse.w == pytest.approx(1849.0, abs=0.5)

    cluster_ids_51 = {("shape", 0), ("text", 0), ("text", 1)}
    cluster_ids_52 = {("shape", 1), ("text", 2), ("text", 3)}
    cluster_ids_53 = {("shape", 0), ("text", 0), ("text", 1)}
    assert cluster_ids_51 <= set(plan.deletes[51])
    assert cluster_ids_52 <= set(plan.deletes[52])
    assert cluster_ids_53 <= set(plan.deletes[53])


@pytest.mark.deck
def test_gw54_unchanged_single_column(gw_inputs):
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, by_number, runs = gw_inputs
    plan = _plan_one(payload, by_number[54], runs, by_number)

    verse = plan.fits[54][("groupchild", 0, "text", 1)]
    assert verse.x == pytest.approx(43.0, abs=0.5)
    assert verse.w == pytest.approx(1849.0, abs=0.5)
    assert 54 not in plan.two_column


@pytest.mark.deck
def test_content_only_gw_selection_drops_text_slides_plan_identical(gw_inputs):
    """`--content-only` over 5,13,21,24,32,33,48 must keep exactly 21,24,32,33,48 (5/13
    are text slides, plan §1.4) and the kept slides' plans must be byte-identical to a
    direct (non-content-only) plan of the same five slides -- `assemble_dsk_deck` only
    ever filters `decisions` before calling `plan_assembly`, never `classes`."""
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, by_number, runs = gw_inputs
    selection = (5, 13, 21, 24, 32, 33, 48)

    text_numbers = {n for n in selection if by_number[n].is_text}
    assert text_numbers == {5, 13}
    kept_numbers = tuple(n for n in selection if n not in text_numbers)
    assert kept_numbers == (21, 24, 32, 33, 48)

    clips = {32: Path("/tmp/gw-clip-32.mov"), 33: Path("/tmp/gw-clip-33.mov")}
    all_classes = list(by_number.values())

    requested_decisions = {
        n: SlideDecision(n, "both" if n in clips else "in_deck", anchor="auto") for n in selection
    }
    content_only_decisions = {n: d for n, d in requested_decisions.items() if n not in text_numbers}

    direct_decisions = {
        n: SlideDecision(n, "both" if n in clips else "in_deck", anchor="auto") for n in kept_numbers
    }

    plan_content_only = plan_assembly(
        payload, all_classes, decisions=content_only_decisions, band=DEFAULT_BAND, clips=clips,
        runs=runs, all_classes=all_classes,
    )
    plan_direct = plan_assembly(
        payload, all_classes, decisions=direct_decisions, band=DEFAULT_BAND, clips=clips,
        runs=runs, all_classes=all_classes,
    )

    assert plan_content_only.kept == kept_numbers
    assert plan_content_only == plan_direct


@pytest.mark.deck
def test_gw57_heading_only_unchanged(gw_inputs):
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, by_number, runs = gw_inputs
    plan = _plan_one(payload, by_number[57], runs, by_number)

    assert 57 not in plan.two_column
    assert 57 not in plan.stack_bands
    heading = plan.fits[57][("text", 1)]
    assert plan.text_sizes[57][("text", 1)] == pytest.approx(140.29535864978902, abs=0.01)
    assert heading.h > 0
