"""Step 11 acceptance: `classify_deck` + `load_assembly_inputs` + `plan_assembly` over the
real `Sermon_PK (GW).key`, one row per the plan's Acceptance table
(`.agents/plans/dsk_content_rules.plan.md`).

Every number here was read back from the deck with these same three functions, not typed
from the plan's prose -- where the plan's table and the measurement disagreed, the plan was
corrected to match this file (GW 5's anchor/crop box, GW 13's t, and GW 17's t after the
badge-fold-in-stack change moved it from the F9-era 0.91 to 0.74). Tolerances are 0.5 pt.

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


def _plan_one(payload, cls, runs, *, min_text_pt=dsa.DEFAULT_MIN_TEXT_PT, crop_dir=None, deck=None):
    decisions = {cls.number: SlideDecision(cls.number, "in_deck", anchor="auto")}
    kwargs = dict(band=DEFAULT_BAND, clips={}, runs=runs, min_text_pt=min_text_pt)
    if crop_dir is not None:
        kwargs.update(deck=deck, fw_deck=GW_DECK, crop_dir=crop_dir)
    return plan_assembly(payload, [cls], decisions=decisions, **kwargs)


@pytest.mark.deck
def test_gw13_single_text_verse_box_no_split(gw_inputs):
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, by_number, runs = gw_inputs
    cls = by_number[13]
    plan = _plan_one(payload, cls, runs)

    verse = plan.fits[13][("text", 1)]
    assert verse.x == pytest.approx(43.0, abs=0.5)
    assert verse.w == pytest.approx(1849.0, abs=0.5)
    assert plan.parts.get(13, 1) == 1
    assert 13 not in plan.splits

    run_sizes = sorted({size for _, _, size in plan.run_sizes[13][("text", 1)]})
    assert run_sizes == pytest.approx([63.7, 77.35], abs=0.01)


@pytest.mark.deck
def test_gw17_dedupe_and_stretch_no_overlap(gw_inputs):
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, by_number, runs = gw_inputs
    cls = by_number[17]
    assert {("text", 3), ("text", 4), ("text", 5)} <= set(cls.dropped_duplicate)

    plan = _plan_one(payload, cls, runs)
    stacked = plan.stacked_ids[17]
    assert stacked == frozenset({("text", 1), ("text", 2)})
    rects = [plan.fits[17][iid] for iid in stacked]
    top, bottom = sorted(rects, key=lambda r: r.y)
    assert top.y + top.h <= bottom.y + 1e-6

    ranges17 = plan.run_sizes[17][("text", 1)]
    assert [(start, end) for start, end, _ in ranges17] == [(1, 3), (4, 20), (21, 30), (31, 79)]
    assert [size for _, _, size in ranges17] == pytest.approx([51.8, 51.8, 62.9, 51.8], abs=0.01)
    t17 = ranges17[0][2] / 70.0
    assert t17 == pytest.approx(0.74, abs=0.01)


@pytest.mark.deck
def test_gw17_forced_split_at_min_text_pt_66(gw_inputs):
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, by_number, runs = gw_inputs
    cls = by_number[17]
    plan = _plan_one(payload, cls, runs, min_text_pt=66)

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

    plan = _plan_one(payload, cls, runs)
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

    plan = _plan_one(payload, cls, runs)
    assert plan.anchors[48] == "right"
    fitted = plan.fits[48][("image", 2)]
    assert fitted.x + fitted.w == pytest.approx(1892.0, abs=0.5)
    assert plan.crops.get(48) in (None, {})


@pytest.mark.deck
def test_gw24_dedupe_four_to_two_centred(gw_inputs):
    _require_gw_deck()
    payload, by_number, runs = gw_inputs
    cls = by_number[24]
    kept_images = [iid for iid in cls.kept if iid[0] == "image"]
    dropped_images = [iid for iid in cls.dropped_duplicate if iid[0] == "image"]
    assert len(kept_images) == 2
    assert len(dropped_images) == 2

    plan = _plan_one(payload, cls, runs)
    assert plan.anchors[24] == "centre"


@pytest.mark.deck
def test_gw21_image_crop_right_aligned(gw_inputs, tmp_path):
    _require_gw_deck()
    payload, by_number, runs = gw_inputs
    cls = by_number[21]
    deck = dsa._load_deck(GW_DECK)
    plan = _plan_one(payload, cls, runs, crop_dir=tmp_path / "crops21", deck=deck)

    crop = plan.crops[21][("image", 0)]
    assert crop.px_box == (57, 1100, 4551, 2365)
    assert crop.source_file_name == "Yang Zheng_YZ_0125.JPG"
    assert crop.visible == Rect(1920.0, 0.0, 3840.0, 1080.0)
    assert crop.path.is_file()

    fitted = plan.fits[21][("image", 0)]
    assert fitted.x + fitted.w == pytest.approx(1892.0, abs=0.5)
    assert plan.anchors[21] == "right"


@pytest.mark.deck
def test_gw5_image_crop_right_aligned(gw_inputs, tmp_path):
    # The plan's Acceptance table originally guessed a "5120x2160-ish" crop box and said
    # nothing about placement; the deck disagrees on both counts -- the measured crop box
    # is (0,1365,5120,2806) of the 5120x3414 source file, and slide 5's only *content*
    # item (the caption group has no image/movie leaf, so it doesn't count) puts it right,
    # not centred. The plan's table has been corrected to match this measurement.
    _require_gw_deck()
    payload, by_number, runs = gw_inputs
    cls = by_number[5]
    deck = dsa._load_deck(GW_DECK)
    plan = _plan_one(payload, cls, runs, crop_dir=tmp_path / "crops5", deck=deck)

    crop = plan.crops[5][("image", 0)]
    assert crop.px_box == (0, 1365, 5120, 2806)
    assert crop.source_file_name == "WhatsApp Image 2026-03-28 at 23.40.20.jpeg"

    assert plan.anchors[5] == "right"
    fitted = plan.fits[5][("image", 0)]
    assert fitted.x + fitted.w == pytest.approx(1892.0, abs=0.5)


@pytest.mark.deck
def test_gw33_movie_kept_as_sole_content_classify_only(gw_inputs):
    # GW 33's clip is not part of this worktree's banked clips, so plan_assembly's
    # clip-path requirement is exercised only via classification -- the classifier alone
    # already proves R2's backdrop-exemption rule (a panel-sized movie survives as a
    # slide's only content).
    _require_gw_deck()
    _payload, by_number, _runs = gw_inputs
    cls = by_number[33]
    assert cls.kept == (("movie", 0),)
    assert cls.movie_count == 1
    assert cls.category == "mixed"


@pytest.mark.deck
def test_gw32_movie_classify_side_panels_dropped(gw_inputs):
    _require_gw_deck()
    _payload, by_number, _runs = gw_inputs
    cls = by_number[32]
    assert cls.kept == (("movie", 0),)
    assert set(cls.dropped_side) == {("image", 0), ("image", 1)}


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
