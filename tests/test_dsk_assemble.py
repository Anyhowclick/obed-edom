"""Tests for obed_edom.dsk_assemble: pure assembly planning and the generated
AppleScript. No test may launch Keynote; the autouse fixture below raises if
subprocess.run/Popen is reached without an explicit monkeypatch.
"""
from __future__ import annotations

import dataclasses
import math
import re
import subprocess
import zipfile
from pathlib import Path

import pytest

import obed_edom.dsk_assemble as dsa
import obed_edom.dsk_live as dsk_live
from obed_edom.dsk_assemble import (
    AssembleResult,
    AssemblyPlan,
    AssemblyRefusal,
    SlideDecision,
    SplitPart,
    TextRefit,
    _parse_measure_lines,
    assemble_dsk_deck,
    build_assembly_script,
    build_refit_script,
    load_assembly_inputs,
    plan_assembly,
)
import obed_edom.dsk_plan as dsk_plan
from obed_edom.dsk_plan import Band, CropRefusal, classify_slide, line_count, resolve_font_path
from obed_edom.map_remap import Rect

BAND = Band(1054.0, 350.0, 43.0, 1892.0, 4)
WALL = (7680.0, 1080.0)


@pytest.fixture(autouse=True)
def no_keynote(monkeypatch):
    def _forbidden(*_args, **_kwargs):
        raise AssertionError("Keynote must not start")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)
    yield


def _raw_autosize_deck(monkeypatch, kind_index, x, y, w):
    """Minimal objects graph + `_item_object_ids` patch proving `("text", kind_index)`
    is raw-height-zero (genuine Keynote autosize) per `dsa._autosize_text_ids`."""
    objects = {"theObj": {"geometry": {"position": {"x": x, "y": y}, "size": {"width": w, "height": 0.0}, "angle": 0.0}}}
    monkeypatch.setattr(dsa, "_slide_archive_for_number", lambda objects, number: {"slide": number})
    monkeypatch.setattr(
        dsa, "_item_object_ids",
        lambda slide_archive, objects: {("text", kind_index): "theObj"},
    )
    return (objects, {}, {})


def _text_item(kind_index, x=0, y=0, w=100, h=50, runs=None):
    item = {"kind": "text", "kindIndex": kind_index, "x": x, "y": y, "w": w, "h": h}
    if runs is not None:
        item["runs"] = runs
    return item


def _image_item(kind_index, x=0, y=0, w=100, h=50):
    return {"kind": "image", "kindIndex": kind_index, "x": x, "y": y, "w": w, "h": h}


def _movie_item(kind_index, x=0, y=0, w=100, h=50):
    return {"kind": "movie", "kindIndex": kind_index, "x": x, "y": y, "w": w, "h": h}


def _group_item(kind_index, x=0, y=0, w=100, h=50):
    return {"kind": "group", "kindIndex": kind_index, "x": x, "y": y, "w": w, "h": h}


def _slide(number, items, skipped=False):
    return {"number": number, "index": number - 1, "skipped": skipped, "items": items}


def _payload(slides, wall=WALL):
    return {"slideWidth": wall[0], "slideHeight": wall[1], "slides": slides}


def _classify(slide, **kwargs):
    return classify_slide(slide, kwargs.pop("builds", None), WALL, **kwargs)


# --------------------------------------------------------------------------
# plan_assembly -- action mapping, ordinal remapping, empty-slide drop
# --------------------------------------------------------------------------
def test_ordinal_remapping_across_skips():
    slides = [_slide(n, [_image_item(0, x=1920, y=0, w=3840, h=1080)]) for n in (5, 9, 12)]
    payload = _payload(slides)
    classes = [_classify(s) for s in slides]
    decisions = {
        5: SlideDecision(5, "in_deck"),
        9: SlideDecision(9, "skip"),
        12: SlideDecision(12, "in_deck"),
    }
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.kept == (5, 12)
    assert plan.ordinals == {5: 1, 12: 2}


def test_mirror_warnings_reach_plan_warnings():
    image2 = {
        "kind": "image", "kindIndex": 2, "x": 1954, "y": 27, "w": 1381, "h": 921,
        "fileName": "wheelchair.jpeg",
    }
    image3 = {
        "kind": "image", "kindIndex": 3, "x": 4348, "y": 27, "w": 1381, "h": 921,
        "fileName": "wheelchair.jpeg",
    }
    slide = _slide(9, [image2, image3])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {9: SlideDecision(9, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert any("slide 9: " in w and "single vote" in w for w in plan.warnings)


def test_export_clip_action_excluded():
    slide = _slide(1, [_movie_item(0, x=1920, y=-763, w=3840, h=2160)])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "export_clip")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.kept == ()


def test_both_action_included():
    slide = _slide(1, [_movie_item(0, x=1920, y=-763, w=3840, h=2160)])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "both")}
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={1: Path("/clip.mov")}
    )
    assert plan.kept == (1,)


def test_empty_slide_always_dropped():
    slide = _slide(1, [])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.kept == ()


def test_skip_action_excluded():
    slide = _slide(1, [_image_item(0, x=1920, y=0, w=3840, h=1080)])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "skip")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.kept == ()


# --------------------------------------------------------------------------
# keep_side, deletes, clip refusal
# --------------------------------------------------------------------------
def test_keep_side_only_affects_its_own_slide():
    side_item = _image_item(1, x=200, y=0, w=200, h=200)
    slide1 = _slide(1, [_image_item(0, x=1920, y=0, w=3840, h=1080), side_item])
    slide2 = _slide(2, [_image_item(0, x=1920, y=0, w=3840, h=1080), dict(side_item, kindIndex=1)])
    payload = _payload([slide1, slide2])
    c1 = _classify(slide1, include_side=True)
    c2 = _classify(slide2, include_side=False)
    decisions = {
        1: SlideDecision(1, "in_deck", keep_side=True),
        2: SlideDecision(2, "in_deck", keep_side=False),
    }
    plan = plan_assembly(payload, [c1, c2], decisions=decisions, band=BAND, clips={})
    assert ("image", 1) in plan.fits[1]
    assert plan.deletes[2] == (("image", 1),)


def test_clip_slide_without_clip_raises():
    slide = _slide(1, [_movie_item(0, x=1920, y=-763, w=3840, h=2160)])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "in_deck")}
    with pytest.raises(AssemblyRefusal):
        plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})


def test_clip_mapping_must_cover_every_kept_movie_exactly():
    # Codex r1 finding 2: a partial per-item clips[number] mapping must refuse, naming
    # the missing movie id(s), rather than silently dropping the unmapped movie.
    slide = _slide(
        1, [_movie_item(0, x=1920, y=-763, w=1920, h=1080), _movie_item(1, x=3840, y=-763, w=1920, h=1080)]
    )
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "in_deck")}
    with pytest.raises(AssemblyRefusal, match=r"missing kept movie item\(s\)"):
        plan_assembly(
            payload, classes, decisions=decisions, band=BAND,
            clips={1: {("movie", 0): Path("/clip0.mov")}},
        )


def test_clip_single_path_requires_exactly_one_kept_movie():
    # The legacy single-Path form only applies when the slide has exactly one kept
    # movie; two kept movies with a single Path must refuse (Codex r1 finding 2).
    slide = _slide(
        1, [_movie_item(0, x=1920, y=-763, w=1920, h=1080), _movie_item(1, x=3840, y=-763, w=1920, h=1080)]
    )
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "in_deck")}
    with pytest.raises(AssemblyRefusal, match="requires exactly one kept movie"):
        plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={1: Path("/clip.mov")})


def test_delete_order_descending_within_kind():
    slide = _slide(
        1,
        [
            _image_item(0, x=1920, y=0, w=3840, h=1080),
            _movie_item(0, x=0, y=-763, w=3840, h=2160),
            _movie_item(1, x=3840, y=-763, w=3840, h=2160),
        ],
    )
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND,
        clips={1: {("movie", 0): Path("/clip0.mov"), ("movie", 1): Path("/clip1.mov")}},
    )
    assert plan.deletes[1] == (("movie", 1), ("movie", 0))


def test_clip_aspect_guard_derives_insert_rect_from_real_clip_size():
    # Codex r1 finding 7 (round 2): a 101x100 source crop, published by S2 as an
    # even-normalized 102x100 clip, must not be refused even though its aspect (1.02)
    # differs from the 101x100-derived fit rect's aspect (1.01) by ~1%, past a naive
    # 0.5% tolerance. Assembly must instead derive the inserted movie's rect from the
    # CLIP's own aspect (keeping the fit rect's origin and its unconstrained
    # dimension), so the real 102x100 clip inserts without drift and the guard only
    # catches gross (wrong-media) mismatches.
    movie = _movie_item(0, x=1920, y=-763, w=3840, h=2160)
    slide = _slide(1, [movie])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "in_deck")}
    clip_path = Path("/tmp/clip.mov")

    baseline = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={1: clip_path})
    fit_rect = baseline.fits[1][("movie", 0)]
    # Simulate a 101x100 source crop published (even-normalized) as 102x100 -- an
    # aspect drift of ~1%, past the old naive 0.5% tolerance -- scaled to whatever
    # aspect this fit rect actually has, so the test doesn't assume a specific band.
    clip_h = 100.0
    clip_w = round((fit_rect.w / fit_rect.h) * clip_h) + 1.0

    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={1: clip_path},
        clip_sizes={str(clip_path): (clip_w, clip_h)},
    )
    inserted = plan.clip_rects[1][("movie", 0)]
    assert inserted.x == pytest.approx(fit_rect.x)
    assert inserted.y == pytest.approx(fit_rect.y)
    assert inserted.w == pytest.approx(fit_rect.w) or inserted.h == pytest.approx(fit_rect.h)
    assert inserted.w / inserted.h == pytest.approx(clip_w / clip_h)


def test_clip_crops_places_insert_at_affine_transformed_normalized_rect():
    # An odd-origin source crop (x=1921, w=101) is published even-normalized (x=1920,
    # w=102) by the movie exporter as `ClipResult.crop_rect`, in the same wall-space
    # coordinates as the source items. Assembly must carry that rect through the exact
    # same per-slide affine (scale + anchor offset) `fit_slide` used for the movie's own
    # placeholder box, honouring the origin shift from normalization.
    movie = _movie_item(0, x=1920, y=0, w=3840, h=1080)
    slide = _slide(1, [movie])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "in_deck")}
    clip_path = Path("/tmp/clip.mov")

    baseline = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={1: clip_path})
    fit_rect = baseline.fits[1][("movie", 0)]
    scale = fit_rect.w / movie["w"]
    tx = fit_rect.x - movie["x"] * scale
    ty = fit_rect.y - movie["y"] * scale

    crop = Rect(1920.0, 0.0, 102.0, 1080.0)
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={1: clip_path},
        clip_crops={1: {("movie", 0): crop}},
    )
    inserted = plan.clip_rects[1][("movie", 0)]
    assert inserted.x == pytest.approx(crop.x * scale + tx)
    assert inserted.y == pytest.approx(crop.y * scale + ty)
    assert inserted.w == pytest.approx(crop.w * scale)
    assert inserted.h == pytest.approx(crop.h * scale)


def test_clip_crops_uses_wall_clipped_source_rect_for_off_canvas_movie():
    # Codex r4 round-3 #7: an off-canvas movie (y=-667, extending above the wall) must
    # have its affine derived from the VISIBLE rect `fit_slide` fit (the movie
    # intersected with the wall), not the full movie rect -- otherwise a crop already
    # expressed in that same visible rect inserts offset by the clipped portion.
    movie = _movie_item(0, x=1920, y=-667, w=3840, h=2160)
    slide = _slide(1, [movie])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "in_deck")}
    clip_path = Path("/tmp/clip.mov")

    baseline = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={1: clip_path})
    fit_rect = baseline.fits[1][("movie", 0)]

    # The crop matches the wall-visible rect (movie intersected with CENTRE_PANEL_RECT)
    # exactly, so the inserted rect must equal the fit rect of that visible rect.
    crop = Rect(1920.0, 0.0, 3840.0, 1080.0)
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={1: clip_path},
        clip_crops={1: {("movie", 0): crop}},
    )
    inserted = plan.clip_rects[1][("movie", 0)]
    assert inserted.x == pytest.approx(fit_rect.x)
    assert inserted.y == pytest.approx(fit_rect.y)
    assert inserted.w == pytest.approx(fit_rect.w)
    assert inserted.h == pytest.approx(fit_rect.h)


def test_operator_clip_16x10_against_16x9_fit_refused():
    # Operator clips (legacy path, no clip_crops) stay on a strict aspect threshold: a
    # 16x10 clip against a 16:9 fitted rect is a ~13% mismatch, well past 0.5%.
    movie = _movie_item(0, x=1920, y=0, w=3840, h=2160)  # 16:9
    slide = _slide(1, [movie])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "in_deck")}
    clip_path = Path("/tmp/clip.mov")

    with pytest.raises(AssemblyRefusal, match="clip aspect"):
        plan_assembly(
            payload, classes, decisions=decisions, band=BAND, clips={1: clip_path},
            clip_sizes={str(clip_path): (1600.0, 1000.0)},
        )


def test_clip_crops_narrow_2x1080_crop_passes():
    # A 1x1080 crop normalized to 2x1080 changes aspect by 100% -- far past any legacy
    # tolerance -- but with `clip_crops` given, the exact geometry is used directly and
    # no aspect-vs-fit-rect guard applies.
    movie = _movie_item(0, x=1920, y=0, w=3840, h=1080)
    slide = _slide(1, [movie])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "in_deck")}
    clip_path = Path("/tmp/clip.mov")

    crop = Rect(1920.0, 0.0, 2.0, 1080.0)
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={1: clip_path},
        clip_crops={1: {("movie", 0): crop}},
    )
    inserted = plan.clip_rects[1][("movie", 0)]
    assert inserted.w > 0
    assert inserted.h > 0


def test_dropped_side_included_in_deletes_unless_kept():
    side = _image_item(1, x=200, y=0, w=200, h=200)
    slide = _slide(1, [_image_item(0, x=1920, y=0, w=3840, h=1080), side])
    payload = _payload([slide])
    cls = _classify(slide, include_side=False)
    decisions = {1: SlideDecision(1, "in_deck", keep_side=False)}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    assert plan.deletes[1] == (("image", 1),)


def test_slide_owned_backdrop_deleted_even_though_never_kept_or_dropped_side():
    backdrop = _image_item(0, x=0, y=0, w=7680, h=1080)
    kept_text = _text_item(1, x=1920, y=0, w=3698.0, h=494.4, runs=[{"size": 40.0}])
    slide = _slide(1, [backdrop, kept_text])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    assert ("image", 0) in plan.deletes[1]
    assert ("text", 1) not in plan.deletes[1]


def test_invisible_off_canvas_item_deleted():
    off_canvas = _image_item(0, x=-9000, y=0, w=100, h=100)
    kept_text = _text_item(1, x=1920, y=0, w=3698.0, h=494.4, runs=[{"size": 40.0}])
    slide = _slide(1, [off_canvas, kept_text])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    assert ("image", 0) in plan.deletes[1]


# --------------------------------------------------------------------------
# text sizes: uniform, mixed, autosize
# --------------------------------------------------------------------------
def test_text_uniform_run_size_scaled():
    item = _text_item(
        0, x=1920, y=0, w=3698, h=494.4, runs=[{"size": 40.0}, {"size": 40.0}]
    )
    slide = _slide(1, [item])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    fitted = plan.fits[1][("text", 0)]
    assert fitted.w == pytest.approx(1849.0, abs=0.1)
    assert fitted.h == pytest.approx(247.2, abs=0.1)
    scale = fitted.w / 3698.0
    assert plan.text_sizes[1][("text", 0)] == pytest.approx(40.0 * scale, abs=0.01)
    assert plan.warnings == ()


def test_run_size_ranges_full_coverage_multi_size():
    item = {"text": "ab", "runs": [{"text": "a", "size": 10.0}, {"text": "b", "size": 20.0}]}
    ranges, unresolved = dsa._run_size_ranges(item, 1.0)
    assert ranges == ((1, 1, 10.0), (2, 2, 20.0))
    assert unresolved is False


def test_run_size_ranges_uniform_size_returns_scaled_run_size():
    item = {"text": "ab", "runs": [{"text": "a", "size": 10.0}, {"text": "b", "size": 10.0}]}
    ranges, unresolved = dsa._run_size_ranges(item, 0.5)
    assert ranges == 5.0
    assert unresolved is False


def test_run_size_ranges_no_runs_is_safe_to_flatten():
    item = {"text": "ab", "runs": []}
    ranges, unresolved = dsa._run_size_ranges(item, 1.0)
    assert ranges is None
    assert unresolved is False


def test_run_size_ranges_all_none_sizes_is_unresolved():
    item = {"text": "ab", "runs": [{"text": "a", "size": None}, {"text": "b", "size": None}]}
    warnings: list[str] = []
    ranges, unresolved = dsa._run_size_ranges(item, 1.0, item_id=("text", 0), slide_number=1, warnings=warnings)
    assert ranges is None
    assert unresolved is True
    assert warnings == ["slide 1 text 0: run ranges leave a gap"]


def test_run_size_ranges_known_size_then_unresolved_run_is_unresolved():
    # A known-size run followed by a size=None run leaves a coverage gap -- must not be
    # silently flattened to a whole-object write; caller only offers it to opt-in shrink.
    item = {"text": "ab", "runs": [{"text": "a", "size": 10.0}, {"text": "b", "size": None}]}
    warnings: list[str] = []
    ranges, unresolved = dsa._run_size_ranges(item, 1.0, item_id=("text", 0), slide_number=1, warnings=warnings)
    assert ranges is None
    assert unresolved is True
    assert warnings == ["slide 1 text 0: run ranges leave a gap"]


def test_emitted_run_sizes_full_coverage_multi_size():
    item = {"text": "ab", "runs": [{"text": "a", "size": 10.0}, {"text": "b", "size": 20.0}]}
    table = dsa._emitted_run_sizes(item, 1.0, 45.0)
    assert table == ((1, 1, 10.0), (2, 2, 20.0))


def test_emitted_run_sizes_caps_at_50pt_gw13_emphasis_run():
    # Plan §0/owner decision: gold uses a flat 50pt emphasis cap, never the source
    # 85/70 ratio -- GW 13's own 85pt run scaled to the 45pt lead (t = 45/70) would be
    # 54.642857pt uncapped; `_emitted_run_sizes` must emit 50.0 instead.
    item = {
        "text": "lead EMPHASIS lead",
        "runs": [
            {"text": "lead ", "size": 70.0},
            {"text": "EMPHASIS", "size": 85.0},
            {"text": " lead", "size": 70.0},
        ],
    }
    t = 45.0 / 70.0
    assert 85.0 * t == pytest.approx(54.642857142857146)  # uncapped source ratio
    table = dsa._emitted_run_sizes(item, t, 45.0)
    assert table[0] == (1, 5, pytest.approx(45.0))
    assert table[1] == (6, 13, 50.0)
    assert table[2] == (14, 18, pytest.approx(45.0))


def test_run_size_ranges_cap_caps_the_emphasis_run_gw13_non_split_path():
    # S2 task 3: the same flat 50pt cap applies on the NON-split slot-fit path
    # (`_run_size_ranges`, GW 13-shaped) -- one rule (`min(size * scale, cap)`), applied
    # at the single `is_slot_fit` call site in `plan_assembly`, never a generic
    # `fit_text_stack` t (that would wrongly cap a shrink-fit's own emphasis ratio).
    item = {
        "text": "lead EMPHASIS lead",
        "runs": [
            {"text": "lead ", "size": 70.0},
            {"text": "EMPHASIS", "size": 85.0},
            {"text": " lead", "size": 70.0},
        ],
    }
    t = 45.0 / 70.0
    ranges, unresolved = dsa._run_size_ranges(item, t, cap=dsa._EMPHASIS_CAP_PT)
    assert unresolved is False
    assert ranges[0] == (1, 5, pytest.approx(45.0))
    assert ranges[1] == (6, 13, 50.0)
    assert ranges[2] == (14, 18, pytest.approx(45.0))
    uncapped, _ = dsa._run_size_ranges(item, t)
    assert uncapped[1] == (6, 13, pytest.approx(54.642857142857146))


def test_pack_split_lines_greedy_height_budget_over_flat_three_lines():
    # S2/§2.2: pack by height, not line count -- a budget one line-height short of
    # three 45pt lines' worth must split at 2 lines/part, never wait for the 3-line
    # guard to kick in.
    run_table = ((1, 100, 45.0),)
    spans = [(0, 10), (10, 20), (20, 30), (30, 40)]
    slot_h = 3 * dsa._LINE_HEIGHT_FACTOR * 45.0 + dsa._BOX_PADDING_PT - dsa._SPLIT_TOL - 1.0
    chunks = dsa._pack_split_lines(spans, run_table, 45.0, slot_h, 1, ("text", 0))
    assert [len(c) for c in chunks] == [2, 2]


def test_pack_split_lines_respects_the_three_line_guard_even_under_budget():
    run_table = ((1, 100, 10.0),)
    spans = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)]
    slot_h = 1000.0
    chunks = dsa._pack_split_lines(spans, run_table, 45.0, slot_h, 1, ("text", 0))
    assert [len(c) for c in chunks] == [3, 2]


def test_pack_split_lines_single_over_budget_line_refuses_naming_slide_and_box():
    run_table = ((1, 100, 90.0),)
    spans = [(0, 10)]
    with pytest.raises(dsa.AssemblyRefusal, match=r"slide 7 box 2:.*exceeds the slot budget"):
        dsa._pack_split_lines(spans, run_table, 45.0, 50.0, 7, ("text", 2))


def test_pack_split_lines_one_part_result_signals_no_split_needed():
    run_table = ((1, 100, 45.0),)
    spans = [(0, 10), (10, 20)]
    chunks = dsa._pack_split_lines(spans, run_table, 45.0, 1000.0, 1, ("text", 0))
    assert len(chunks) == 1


def test_emitted_run_sizes_uncapped_below_50pt_is_unaffected():
    item = {"text": "ab", "runs": [{"text": "a", "size": 10.0}, {"text": "b", "size": 10.0}]}
    table = dsa._emitted_run_sizes(item, 0.5, 45.0)
    assert table == ((1, 1, 5.0), (2, 2, 5.0))


def test_emitted_run_sizes_any_unresolved_run_makes_the_whole_table_unresolved():
    # Owner-adopted policy (S1/§2.1 step 2): unlike `_run_size_ranges`'s partial-gap
    # tuple, ANY run with no size makes the table wholly "unresolved" -- GW 49 has one
    # resolved run among five; the caller must not silently keep that one range.
    item = {
        "text": "abc",
        "runs": [{"text": "a", "size": 10.0}, {"text": "b", "size": None}, {"text": "c", "size": 10.0}],
    }
    assert dsa._emitted_run_sizes(item, 1.0, 45.0) == "unresolved"


def test_emitted_run_sizes_no_runs_falls_back_to_lead_pt_over_full_text():
    item = {"text": "abcd", "runs": []}
    assert dsa._emitted_run_sizes(item, 1.0, 45.0) == ((1, 4, 45.0),)


def test_emitted_run_sizes_no_runs_no_text_is_empty():
    item = {"text": "", "runs": []}
    assert dsa._emitted_run_sizes(item, 1.0, 45.0) == ()


def test_windowed_run_ranges_restricts_and_collapses_uniform_size():
    table = ((1, 1, 45.0), (2, 6, 50.0), (7, 10, 45.0))
    assert dsa._windowed_run_ranges(table, 0, 1, 45.0) == 45.0
    restricted = dsa._windowed_run_ranges(table, 0, 6, 45.0)
    assert restricted == ((1, 1, 45.0), (2, 6, 50.0))


def test_windowed_run_ranges_window_with_only_resolved_run_outside_it_falls_back_to_lead():
    # Owner decision (finding 1): the window can no longer borrow a neighbouring run's
    # size as its fallback -- a window that intersects no range in the table gets the
    # slot's own lead size, never the out-of-window run's size (here 50.0).
    table = ((200, 210, 50.0),)
    assert dsa._windowed_run_ranges(table, 0, 10, 45.0) == 45.0


def test_text_mixed_run_sizes_warns_and_omits():
    item = _text_item(0, x=1920, y=0, w=200, h=80, runs=[{"size": 20.0}, {"size": 30.0}])
    slide = _slide(1, [item])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    assert ("text", 0) not in plan.text_sizes.get(1, {})
    assert plan.warnings == ("slide 1 text 0 mixed run sizes",)


def test_script_overflow_readback_emitted_for_mixed_run_text():
    item = _text_item(0, x=1920, y=0, w=200, h=80, runs=[{"size": 20.0}, {"size": 30.0}])
    slide = _slide(1, [item])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key")
    )
    assert 'OVERFLOW" & tab & "text:0"' in script


def test_script_overflow_readback_omitted_for_uniform_run_text():
    item = _text_item(
        0, x=1920, y=0, w=3698, h=494.4, runs=[{"size": 40.0}, {"size": 40.0}]
    )
    slide = _slide(1, [item])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key")
    )
    assert 'OVERFLOW" & tab & "text:0"' not in script


def test_refit_script_reopens_and_saves():
    item = _text_item(0, x=1920, y=0, w=200, h=80, runs=[{"size": 20.0}, {"size": 30.0}])
    slide = _slide(1, [item])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    refits = {(1, 0): {("text", 0): TextRefit(Rect(43.0, 704.0, 1892.0, 200.0), run_sizes=44.0)}}
    script = build_refit_script(
        plan, refits, ordinals=plan.ordinals, scratch_path=Path("/tmp/scratch.key"),
        staging_path=Path("/tmp/staged.key"),
    )
    assert 'set theDoc to open theFile' in script
    assert "save theDoc in POSIX file" in script
    assert "close theDoc saving no" in script
    assert "set size of object text of theObj to 44" in script
    assert 'MEASURE" & tab & "text:0"' in script


def test_assemble_parses_measure_lines():
    stderr = 'OBED\t13\tMEASURE\ttext:1\t269.0\nOBED\t13\tOVERFLOW\ttext:1\t269.0\n'
    assert _parse_measure_lines(stderr) == {(13, "text:1"): 269.0}


def test_stacked_unresolved_run_gap_below_full_size_refuses(monkeypatch):
    words = " ".join(["word"] * 12)
    item = _text_item(0, x=1920, y=0, w=3698, h=494.4, runs=[{"text": "a", "size": 10.0}, {"text": "b", "size": None}])
    item["text"] = words
    item["font"] = "Arial"
    item["size"] = 40.0
    slide = _slide(1, [item])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    monkeypatch.setattr(
        dsa, "fit_text_stack", lambda boxes, band, min_text_pt: (0.5, {("text", 0): 20.0}, {("text", 0): 100.0})
    )
    with pytest.raises(AssemblyRefusal, match="run ranges leave a gap"):
        plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})


def test_autosize_detector_graph_backed_vs_graphless_raw_height_zero_parity(monkeypatch):
    # Codex L1 review 1, finding 2: `_autosize_text_ids` centralizes both `plan.autosize`
    # and `SplitPart.autosize` on the graph's raw-height-zero rule; production always
    # supplies a graph (`dsk_assemble.py:3764`), so the graphless path never marks a box
    # autosize on its own (no payload flag exists to do so safely -- `offline_wall_payload`
    # fills a genuine autosize frame's zero height with its saved `naturalSize`). A
    # graphless plan of a raw-height-zero box is therefore fixed-frame (emits `set
    # height`); the graph-backed plan of the SAME box is autosize (no `set height`).
    item = _text_item(0, x=2000, y=0, w=300.0, h=300, runs=[{"size": 20.0}])
    slide = _slide(1, [item])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}

    graphless_plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    assert ("text", 0) not in graphless_plan.autosize.get(1, frozenset())

    deck = _raw_autosize_deck(monkeypatch, 0, x=2000, y=0, w=300.0)
    graph_plan = plan_assembly(
        payload, [cls], decisions=decisions, band=BAND, clips={}, deck=deck, fw_deck="/tmp/does-not-matter.key",
    )
    assert ("text", 0) in graph_plan.autosize[1]


def test_autosize_detector_raw_width_zero_fixed_height_is_never_autosize(monkeypatch):
    # Codex L1 review 1, finding 2: a raw-width-zero/fixed-height box must never be
    # classified autosize, in either the graphless or the graph-backed path -- the old
    # `w == 0.0 or h == 0.0` heuristic wrongly flagged this as autosize on the payload
    # alone.
    item = _text_item(0, x=2000, y=0, w=0.0, h=300, runs=[{"size": 20.0}])
    slide = _slide(1, [item])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}

    graphless_plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    assert ("text", 0) not in graphless_plan.autosize.get(1, frozenset())

    objects = {"theObj": {"geometry": {"position": {"x": 2000, "y": 0}, "size": {"width": 0.0, "height": 300.0}, "angle": 0.0}}}
    monkeypatch.setattr(dsa, "_slide_archive_for_number", lambda objects, number: {"slide": number})
    monkeypatch.setattr(dsa, "_item_object_ids", lambda slide_archive, objects: {("text", 0): "theObj"})
    graph_plan = plan_assembly(
        payload, [cls], decisions=decisions, band=BAND, clips={},
        deck=(objects, {}, {}), fw_deck="/tmp/does-not-matter.key",
    )
    assert ("text", 0) not in graph_plan.autosize.get(1, frozenset())


def test_text_autosize_zero_dimension_flagged(monkeypatch):
    item = _text_item(0, x=2000, y=0, w=0.0, h=300, runs=[{"size": 20.0}])
    slide = _slide(1, [item])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    deck = _raw_autosize_deck(monkeypatch, 0, x=2000, y=0, w=0.0)
    plan = plan_assembly(
        payload, [cls], decisions=decisions, band=BAND, clips={}, deck=deck, fw_deck="/tmp/does-not-matter.key",
    )
    assert ("text", 0) in plan.autosize[1]


# --------------------------------------------------------------------------
# The four real fit numbers, per Band(1054, 350, 43, 1892, 4)
# --------------------------------------------------------------------------
def test_fit_slide_32_movie():
    # 3840x2160 movie at (1920, -763), the GW fixture's slide 32.
    item = _movie_item(0, x=1920, y=-763, w=3840, h=2160)
    slide = _slide(32, [item])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {32: SlideDecision(32, "in_deck")}
    plan = plan_assembly(
        payload, [cls], decisions=decisions, band=BAND, clips={32: Path("/clip.mov")}
    )
    fitted = plan.fits[32][("movie", 0)]
    assert fitted.x == pytest.approx(345.3, abs=0.1)
    assert fitted.y == pytest.approx(704.0, abs=0.1)
    assert fitted.w == pytest.approx(1244.4, abs=0.1)
    assert fitted.h == pytest.approx(350.0, abs=0.1)


def test_fit_slide_13_text():
    # A single centre-panel text item scaled width-bound to the full band width.
    item = _text_item(0, x=1920, y=0, w=3698.0, h=494.4)
    slide = _slide(13, [item])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    fitted = plan.fits[13][("text", 0)]
    assert fitted.x == pytest.approx(43.0, abs=0.1)
    assert fitted.y == pytest.approx(806.8, abs=0.1)
    assert fitted.w == pytest.approx(1849.0, abs=0.1)
    assert fitted.h == pytest.approx(247.2, abs=0.1)


def test_fit_slide_8_include_side_images():
    # Two images whose full-wall union is (0, 0, 7680, 1080): width-bound fit at h=260.
    # item1 is a full centre-panel-sized image; is_panel_backdrop only ever matches shapes
    # (D1), so it is real content here, never dropped as a scrim.
    item1 = _image_item(0, x=0, y=0, w=3840, h=1080)
    item2 = _image_item(1, x=5760, y=0, w=1920, h=1080)
    slide = _slide(8, [item1, item2])
    payload = _payload([slide])
    cls = _classify(slide, include_side=True)
    decisions = {8: SlideDecision(8, "in_deck", keep_side=True)}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    r1 = plan.fits[8][("image", 0)]
    r2 = plan.fits[8][("image", 1)]
    assert r1.h == pytest.approx(260.0, abs=0.1)
    assert r2.h == pytest.approx(260.0, abs=0.1)
    assert r1.x == pytest.approx(43.0, abs=0.1)
    assert r2.x == pytest.approx(1429.8, abs=0.2)


# --------------------------------------------------------------------------
# groups: known children (autosize/uniform text/shared scale), blind fallback, refusal
# --------------------------------------------------------------------------
def test_group_nested_movie_refuses_at_plan_time():
    group = _group_item(0, x=1920, y=0, w=400, h=400)
    slide = _slide(1, [group])
    cls = _classify(slide, group_movie_counts={0: 1})
    payload = _payload([slide])
    decisions = {1: SlideDecision(1, "in_deck")}
    with pytest.raises(AssemblyRefusal, match="movie nested in group"):
        plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})


def test_group_text_without_offline_metadata_refuses():
    group = _group_item(0, x=1920, y=0, w=400, h=200)
    slide = _slide(1, [group])
    slide["groupChildText"] = {0: "Some Caption"}  # metadata says text exists...
    # ...but no groupChildren entry (nested/rotated/masked group -- unavailable offline).
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    with pytest.raises(AssemblyRefusal, match="no offline child metadata"):
        plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})


def test_group_autosize_child_never_gets_height_write_and_relocks_on_error():
    group = _group_item(0, x=1920, y=0, w=400, h=200)
    slide = _slide(1, [group])
    slide["groupChildren"] = {
        0: [{"kind": "text", "kindIndex": 0, "autosize": True, "x": 1920.0, "y": 0.0, "w": 400.0, "h": 200.0}]
    }
    slide["groupChildText"] = {0: "Caption"}
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})

    assert 0 in plan.group_children[1]
    child = plan.group_children[1][0][0]
    assert child["autosize"] is True

    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    ordinal = plan.ordinals[1]
    addr = f"text item 1 of group 1 of slide {ordinal}"
    assert f"set theObj to {addr}" in script
    assert "set width of theObj to" in script
    assert "set height of theObj to" not in script  # the only write in this plan is the autosize child
    assert "on error errMsg number errNum" in script
    assert "if wasLocked then set locked of theObj to true" in script


def test_group_autosize_caption_child_writes_size_before_position():
    # Codex L1 review 1, finding 1: an autosize caption child (single text leaf +
    # groupCaption text_size) must accumulate the size write BEFORE position, same
    # order as the non-group autosize path -- not width -> position -> size.
    group = _group_item(0, x=1920, y=0, w=400, h=200)
    slide = _slide(1, [group])
    slide["groupChildren"] = {
        0: [{"kind": "text", "kindIndex": 0, "autosize": True, "x": 1920.0, "y": 0.0, "w": 400.0, "h": 200.0}]
    }
    slide["groupChildText"] = {0: "Caption"}
    slide["groupCaption"] = {0: {"text": "Caption", "size": 24.0}}
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})

    child = plan.group_children[1][0][0]
    assert child["autosize"] is True

    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    lines = script.splitlines()
    ordinal = plan.ordinals[1]
    addr = f"text item 1 of group 1 of slide {ordinal}"
    start = lines.index(f"          set theObj to {addr}")
    block = lines[start:start + 12]
    assert not any("set height" in l for l in block)
    width_i = next(i for i, l in enumerate(block) if "set width" in l)
    size_i = next(i for i, l in enumerate(block) if "set size" in l)
    position_i = next(i for i, l in enumerate(block) if "set position" in l)
    assert width_i < size_i < position_i, block


def test_group_uniform_single_leaf_caption_text_size_scaled():
    group = _group_item(0, x=1920, y=0, w=400, h=200)
    slide = _slide(1, [group])
    slide["groupChildren"] = {
        0: [{"kind": "text", "kindIndex": 0, "autosize": False, "x": 1920.0, "y": 0.0, "w": 400.0, "h": 200.0}]
    }
    slide["groupChildText"] = {0: "Caption"}
    slide["groupCaption"] = {0: {"text": "Caption", "size": 24.0}}
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})

    scale = plan.group_scale[1]
    assert plan.group_text_sizes[1][0] == pytest.approx(24.0 * scale, abs=0.001)

    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    assert f"set size of object text of theObj to {24.0 * scale:.4f}" in script or "set size of object text of theObj to" in script


def test_group_multi_leaf_text_gets_no_size_write():
    group = _group_item(0, x=1920, y=0, w=400, h=200)
    slide = _slide(1, [group])
    slide["groupChildren"] = {
        0: [
            {"kind": "text", "kindIndex": 0, "autosize": False, "x": 1920.0, "y": 0.0, "w": 200.0, "h": 200.0},
            {"kind": "text", "kindIndex": 1, "autosize": False, "x": 2120.0, "y": 0.0, "w": 200.0, "h": 200.0},
        ]
    }
    slide["groupChildText"] = {0: "A B"}
    # No groupCaption: `_single_text_leaf` refuses whenever a group has more than one
    # non-empty text leaf, so no size is ever attached for this group.
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    assert 1 not in plan.group_text_sizes.get(1, {})
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    assert "set size of object text of theObj" not in script


def test_group_known_children_never_reads_live_group_width():
    group = _group_item(0, x=1920, y=0, w=400, h=200)
    slide = _slide(1, [group])
    slide["groupChildren"] = {
        0: [{"kind": "image", "kindIndex": 0, "autosize": False, "x": 1920.0, "y": 0.0, "w": 400.0, "h": 200.0}]
    }
    slide["groupChildText"] = {}
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    assert plan.group_scale[1] > 0
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    assert "width of theObj" not in [ln.strip().split(" to ")[0] for ln in script.splitlines() if "gw" in ln]
    assert "(width of theObj)" not in script  # never re-derives scale from a live group width


def test_group_blind_fallback_when_no_text_present():
    group = _group_item(0, x=1920, y=0, w=400, h=200)
    slide = _slide(1, [group])
    # No groupChildren / groupChildText at all -- classifier still sees the group.
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    assert 1 not in plan.group_children
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    assert "iWork items of group" in script
    assert "(width of theObj)" not in script  # blind path also uses the precomputed scale, not a live gw read


# --------------------------------------------------------------------------
# D1: a group whose child text triggers the text-slide classifier (Design A) -- its
# children are stacked into the band directly, no affine group write.
# --------------------------------------------------------------------------
_GW5_VERSE = (
    "Matthew 18 19 Again, truly I tell you that if two of you on earth agree about "
    "anything they ask for, it will be done for them by My Father in heaven."
)


def _gw5_shaped_slide_and_plan_inputs():
    photo = _image_item(0, x=1920, y=-1024, w=3840, h=2561)
    group = _group_item(0, x=4702, y=15, w=645, h=92)
    slide = _slide(5, [photo, group])
    slide["groupChildText"] = {0: _GW5_VERSE}
    slide["groupChildSignature"] = {0: f"shape:badge\ntext:{_GW5_VERSE}"}
    slide["groupChildren"] = {0: [
        {"kind": "shape", "kindIndex": 0, "autosize": False, "x": 4702.0, "y": 15.0, "w": 645.0, "h": 92.0},
        {"kind": "text", "kindIndex": 1, "autosize": True, "x": 4303.0, "cy": 89.0, "y": -88.0, "w": 1442.0, "h": 355.0},
    ]}
    slide["groupChildRuns"] = {0: {1: {
        "text": _GW5_VERSE, "font": "AzoSans-Regular", "size": 70.0,
        "runs": [{"text": _GW5_VERSE, "fontName": "AzoSans-Regular", "size": 70.0}],
    }}}
    payload = _payload([slide])
    cls = _classify(slide, group_child_words=slide["groupChildText"], group_children=slide["groupChildren"])
    return slide, payload, cls


def test_group_verse_slide_stacks_children_not_affine():
    _require_font("AzoSans-Regular")
    slide, payload, cls = _gw5_shaped_slide_and_plan_inputs()
    assert cls.is_text
    assert cls.long_text_ids == (("groupchild", 0, "text", 1),)
    assert ("image", 0) in cls.dropped_media_text

    decisions = {5: SlideDecision(5, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})

    assert ("group", 0) not in plan.fits[5]
    assert ("image", 0) not in plan.fits[5]
    assert ("image", 0) in plan.deletes[5]

    band_top = BAND.bottom - BAND.height
    verse_rect = plan.fits[5][("groupchild", 0, "text", 1)]
    badge_rect = plan.fits[5][("groupchild", 0, "shape", 0)]
    assert verse_rect.y >= band_top - 0.01
    assert verse_rect.y + verse_rect.h <= BAND.bottom + 0.01
    assert badge_rect.y + badge_rect.h <= verse_rect.y + 0.01  # badge above verse

    ordinal = plan.ordinals[5]
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    verse_addr = f"text item 2 of group 1 of slide {ordinal}"
    badge_addr = f"shape 1 of group 1 of slide {ordinal}"
    assert f"set theObj to {verse_addr}" in script
    assert f"set theObj to {badge_addr}" in script
    assert "set size of object text of theObj to" in script  # one uniform run -> lead size
    assert "set height of theObj to" not in script.split(verse_addr)[1].split("on error")[0]
    assert f"iWork items of group 1 of slide {ordinal}" not in script
    assert "(width of theObj)" not in script

    assert 'log ("OBED" & tab & "5" & tab & "MEASURE" & tab & "groupchild:0:text:1"' in script


def test_eligible_refit_items_excludes_groupchild():
    # F6/F11: a group's text is fit once offline and never refit live (D1 step 6) --
    # `_eligible_refit_items` must drop the `GroupChildId` even though it is a stacked id.
    slide, payload, cls = _gw5_shaped_slide_and_plan_inputs()
    decisions = {5: SlideDecision(5, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    assert ("groupchild", 0, "text", 1) in plan.stacked_ids[5]
    assert dsa._eligible_refit_items(plan, 5) == frozenset()


def test_build_refit_round_skips_slide_with_groupchild_stacked_id():
    # F6: `plan.short_fit` can carry a `GroupChildId` badge entry, and the old code only
    # avoided the `kind, kind_index = item_id` 3-tuple crash in `build_refit_script` by
    # accident (a box-count mismatch that happened to always trip first). Must now skip
    # explicitly and never emit a refit for the groupchild badge.
    slide, payload, cls = _gw5_shaped_slide_and_plan_inputs()
    decisions = {5: SlideDecision(5, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    assert plan.short_fit.get(5)
    slides_by_number = {s["number"]: s for s in payload["slides"]}
    refits = dsa._build_refit_round(
        plan, slides_by_number, {(5, "text:1")}, {(5, "text:1"): 400.0}, BAND, 24.0, [], {},
    )
    assert refits == {}


def test_group_short_label_stays_in_short_row_at_source_size():
    # F4: stack-vs-short-row must split on each child's own word count (mirroring the
    # top-level rule), not on kind alone -- a short text label in a group whose overall
    # child text is long (so the group still classifies as a text slide) must be left in
    # the short row, unscaled and un-repositioned in width/size, not stretched full-band.
    _require_font("AzoSans-Regular")
    label_text = "Faith"
    group = _group_item(0, x=4702, y=-88, w=1442, h=443)
    slide = _slide(5, [group])
    slide["groupChildText"] = {0: f"{label_text} {_GW5_VERSE}"}
    slide["groupChildSignature"] = {0: f"text:{label_text}\ntext:{_GW5_VERSE}"}
    slide["groupChildren"] = {0: [
        {"kind": "text", "kindIndex": 0, "autosize": True, "x": 4750.0, "cy": 50.0, "y": 20.0, "w": 200.0, "h": 60.0},
        {"kind": "text", "kindIndex": 1, "autosize": True, "x": 4303.0, "cy": 89.0, "y": -88.0, "w": 1442.0, "h": 355.0},
    ]}
    slide["groupChildRuns"] = {0: {
        0: {"text": label_text, "font": "AzoSans-Regular", "size": 40.0,
            "runs": [{"text": label_text, "fontName": "AzoSans-Regular", "size": 40.0}]},
        1: {"text": _GW5_VERSE, "font": "AzoSans-Regular", "size": 70.0,
            "runs": [{"text": _GW5_VERSE, "fontName": "AzoSans-Regular", "size": 70.0}]},
    }}
    payload = _payload([slide])
    cls = _classify(slide, group_child_words=slide["groupChildText"], group_children=slide["groupChildren"])
    assert cls.long_text_ids == (("groupchild", 0, "text", 0), ("groupchild", 0, "text", 1))

    decisions = {5: SlideDecision(5, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})

    assert ("groupchild", 0, "text", 1) in plan.stacked_ids[5]
    assert ("groupchild", 0, "text", 0) not in plan.stacked_ids[5]
    label_rect = plan.fits[5][("groupchild", 0, "text", 0)]
    assert label_rect.w == pytest.approx(200.0)
    assert label_rect.h == pytest.approx(60.0)

    ordinal = plan.ordinals[5]
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    label_addr = f"text item 1 of group 1 of slide {ordinal}"
    body = script.split(f"set theObj to {label_addr}")[1].split("on error")[0]
    assert "set width of theObj" not in body
    assert "set size of object text of theObj" not in body
    assert "set position of theObj" in body


def test_group_verse_slide_refuses_when_a_stacked_child_font_unresolved():
    # F9: the affine-exclusion (`fit.pop`) lived inside the "all boxes resolved" guard,
    # so a text-triggering group whose child font/size can't be resolved used to fall
    # through to the affine group-write path after classification had already dropped
    # the slide's media -- a silently degraded slide. Must now refuse explicitly.
    photo = _image_item(0, x=1920, y=-1024, w=3840, h=2561)
    group = _group_item(0, x=4702, y=15, w=645, h=92)
    slide = _slide(5, [photo, group])
    slide["groupChildText"] = {0: _GW5_VERSE}
    slide["groupChildSignature"] = {0: f"shape:badge\ntext:{_GW5_VERSE}"}
    slide["groupChildren"] = {0: [
        {"kind": "shape", "kindIndex": 0, "autosize": False, "x": 4702.0, "y": 15.0, "w": 645.0, "h": 92.0},
        {"kind": "text", "kindIndex": 1, "autosize": True, "x": 4303.0, "cy": 89.0, "y": -88.0, "w": 1442.0, "h": 355.0},
    ]}
    # No groupChildRuns entry for text child 1 -- font/size unresolved.
    payload = _payload([slide])
    cls = _classify(slide, group_child_words=slide["groupChildText"], group_children=slide["groupChildren"])
    decisions = {5: SlideDecision(5, "in_deck")}
    with pytest.raises(AssemblyRefusal, match="could not be resolved"):
        plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})


def test_groupchild_overflow_refuses_under_text_fit_warn():
    # F5: a `groupchild:` OVERFLOW line means the offline estimator got the group verse
    # wrong, and `_eligible_refit_items` excludes it from ever entering a live refit --
    # under --text-fit warn (the default) that must now be an explicit refusal, not a
    # warning nobody is forced to read.
    slide, payload, cls = _gw5_shaped_slide_and_plan_inputs()
    decisions = {5: SlideDecision(5, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    slides_by_number = {s["number"]: s for s in payload["slides"]}
    overflows = [{"slide": 5, "item": "groupchild:0:text:1", "height": 400.0}]
    with pytest.raises(AssemblyRefusal, match="groupchild:0:text:1 overflow"):
        dsa._run_refit_and_finalize(
            plan, batch=None, slides_by_number=slides_by_number,
            band=BAND, min_text_pt=24.0, allow_split=False, text_fit="warn",
            staging_path=Path("/tmp/staged.key"), measured={}, overflows=overflows,
            warnings=[], log=lambda _msg: None,
        )


def test_groupchild_overflow_stays_a_warning_under_text_fit_shrink():
    # F5, second half: under --text-fit shrink there is still no live fallback for a
    # group's text, so the run must complete without raising and the OVERFLOW line the
    # caller already logged as a warning is left in place.
    slide, payload, cls = _gw5_shaped_slide_and_plan_inputs()
    decisions = {5: SlideDecision(5, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    slides_by_number = {s["number"]: s for s in payload["slides"]}
    overflows = [{"slide": 5, "item": "groupchild:0:text:1", "height": 400.0}]
    warnings = ["slide 5: text groupchild:0:text:1 overflow, height 400.0"]
    dsa._run_refit_and_finalize(
        plan, batch=None, slides_by_number=slides_by_number,
        band=BAND, min_text_pt=24.0, allow_split=False, text_fit="shrink",
        staging_path=Path("/tmp/staged.key"), measured={}, overflows=overflows,
        warnings=warnings, log=lambda _msg: None,
    )
    assert any("groupchild:0:text:1 overflow" in w for w in warnings)


def test_refit_stopped_logs_reason_and_per_box_offline_measures(monkeypatch):
    # r11 GW 17 root cause repro: two boxes sharing one stack `t`, offline measures
    # scaled to the live incident's own corrections (1.37/2.25, not the 3.0 cap -- GW 17
    # never hit the cap, the floor `--min-text-pt 66` is what refused it). Round 1 must
    # log the offline measure for every eligible box and the reason the round produced
    # no write, not vanish silently before the "still overflows" refusal.
    _require_font("AzoSans-Regular")
    box1 = _long_text_item(1, _VERSE_1, y=100)
    box2 = _long_text_item(2, _VERSE_2, y=500)
    slide = _slide(17, [box1, box2])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {17: SlideDecision(17, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    slides_by_number = {s["number"]: s for s in payload["slides"]}
    ordinal = plan.ordinals[17]
    rect1 = plan.fits[17][("text", 1)].h
    rect2 = plan.fits[17][("text", 2)].h
    offline_by_index = {0: round(rect1 * 1.37, 1), 1: round(rect2 * 2.25, 1)}

    def fake_offline_text_rects(key_path, *, deck=None):
        rects = {
            ("text", idx): (43.0, 800.0 + idx * 200, 1849.0, offline_by_index[idx])
            for idx, _iid in enumerate(sorted(plan.stacked_ids[17]))
        }
        return ({ordinal: rects}, set())

    monkeypatch.setattr(dsa, "offline_text_rects", fake_offline_text_rects)

    logs: list[str] = []
    with pytest.raises(AssemblyRefusal, match="slide 17: text text:1 still overflows after refit"):
        dsa._run_refit_and_finalize(
            plan, batch=None, slides_by_number=slides_by_number,
            band=BAND, min_text_pt=66.0, allow_split=False, text_fit="warn",
            staging_path=Path("/tmp/staged.key"), measured={}, overflows=[],
            warnings=[], log=logs.append,
        )
    assert any(
        l.startswith("slide 17: text text:1 offline=") and "over=+" in l for l in logs
    )
    assert any(
        l.startswith("slide 17: text text:2 offline=") and "over=+" in l for l in logs
    )
    assert any(
        l == "refit stopped after round 1: slide 17: fit_text_stack found no t >= floor "
        "(66.0pt) fitting the stack band at correction "
        "{('text', 1): 1.37, ('text', 2): 2.25}"
        for l in logs
    )


def test_group_child_of_unmapped_kind_skipped_not_placed():
    # F7: an unmapped child kind must be skipped, like `_group_known_child_lines`
    # already does -- not given a bogus AppleScript address / a short-row rect.
    photo = _image_item(0, x=1920, y=-1024, w=3840, h=2561)
    group = _group_item(0, x=4702, y=15, w=645, h=92)
    slide = _slide(5, [photo, group])
    slide["groupChildText"] = {0: _GW5_VERSE}
    slide["groupChildSignature"] = {0: f"table:x\ntext:{_GW5_VERSE}"}
    slide["groupChildren"] = {0: [
        {"kind": "table", "kindIndex": 0, "autosize": False, "x": 4702.0, "y": 15.0, "w": 645.0, "h": 92.0},
        {"kind": "text", "kindIndex": 1, "autosize": True, "x": 4303.0, "cy": 89.0, "y": -88.0, "w": 1442.0, "h": 355.0},
    ]}
    slide["groupChildRuns"] = {0: {1: {
        "text": _GW5_VERSE, "font": "AzoSans-Regular", "size": 70.0,
        "runs": [{"text": _GW5_VERSE, "fontName": "AzoSans-Regular", "size": 70.0}],
    }}}
    payload = _payload([slide])
    cls = _classify(slide, group_child_words=slide["groupChildText"], group_children=slide["groupChildren"])
    decisions = {5: SlideDecision(5, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    assert ("groupchild", 0, "table", 0) not in plan.fits[5]


def test_groupchild_id_carries_kind_no_shape_text_kindindex_collision():
    # D1 Codex fix round, Finding 1: kindIndex is assigned PER KIND, so a `shape`
    # kindIndex 1 badge and a `text` kindIndex 1 verse in the same group used to collapse
    # to the same 3-tuple ("groupchild", 0, 1) -- the badge was mistaken for the long
    # child and got no short-row placement. The 4-tuple id (kind-bearing) must keep them
    # apart: the verse is the long/stacked id, the badge gets its own short-row rect.
    _require_font("AzoSans-Regular")
    group = _group_item(0, x=4702, y=-88, w=1442, h=443)
    slide = _slide(5, [group])
    slide["groupChildText"] = {0: _GW5_VERSE}
    slide["groupChildSignature"] = {0: f"shape:badge\ntext:{_GW5_VERSE}"}
    slide["groupChildren"] = {0: [
        {"kind": "shape", "kindIndex": 1, "autosize": False, "x": 4750.0, "y": 20.0, "w": 200.0, "h": 60.0},
        {"kind": "text", "kindIndex": 1, "autosize": True, "x": 4303.0, "cy": 89.0, "y": -88.0, "w": 1442.0, "h": 355.0},
    ]}
    slide["groupChildRuns"] = {0: {1: {
        "text": _GW5_VERSE, "font": "AzoSans-Regular", "size": 70.0,
        "runs": [{"text": _GW5_VERSE, "fontName": "AzoSans-Regular", "size": 70.0}],
    }}}
    payload = _payload([slide])
    cls = _classify(slide, group_child_words=slide["groupChildText"], group_children=slide["groupChildren"])
    assert cls.long_text_ids == (("groupchild", 0, "text", 1),)

    decisions = {5: SlideDecision(5, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})

    assert ("groupchild", 0, "text", 1) in plan.stacked_ids[5]
    assert ("groupchild", 0, "shape", 1) not in plan.stacked_ids[5]
    badge_rect = plan.fits[5][("groupchild", 0, "shape", 1)]
    verse_rect = plan.fits[5][("groupchild", 0, "text", 1)]
    assert badge_rect.w == pytest.approx(200.0)
    assert badge_rect.h == pytest.approx(60.0)
    assert badge_rect.y + badge_rect.h <= verse_rect.y + 0.01

    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    assert "shape 2 of group 1" in script
    assert "text item 2 of group 1" in script


def _dual_membership_group_records():
    """Raw archive for a group whose one child carries BOTH shape and text membership
    (dual membership: assigned kindIndex 0 in each) with a fixed frame (autosize False)
    -- the real `_all_group_child_records` path collapses its `kind` to `shape` while
    keeping `has_text`."""
    objects = {
        "900": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 4702.0, "y": 15.0}, "size": {"width": 645.0, "height": 443.0}, "angle": 0.0},
            "children": [{"identifier": "901"}],
        },
        "901": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True,
            "super": {
                "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 645.0, "height": 443.0}, "angle": 0.0},
                "pathsource": {"editableBezierPathSource": {"identifier": "902"}},
            },
        },
    }
    return dsa._all_group_child_records(objects["900"], objects)


def test_fixed_frame_group_text_over_threshold_refuses():
    # D1 Codex fix round, Finding 2, rebuilt in D1 Codex fix round 2 (Codex MINOR): a
    # group's DFS word join exceeds `text_slide_words` but its only long-text-bearing
    # child is a FIXED FRAME (autosize False) one -- `_is_text_slide_kept` emits no
    # groupchild long id for this group at all, so unguarded it would silently fall
    # through to the normal affine path. Must refuse instead. The dual-membership shape
    # is a raw archive (`_all_group_child_records`, not hand-injected `has_text`), which
    # `kind`-collapses to `shape`.
    records = _dual_membership_group_records()
    assert [r["kind"] for r in records] == ["shape"]
    group = _group_item(0, x=4702, y=15, w=645, h=443)
    slide = _slide(5, [group])
    slide["groupChildText"] = {0: _GW5_VERSE}
    slide["groupChildSignature"] = {0: f"shape:{_GW5_VERSE}"}
    slide["groupChildren"] = {0: records}
    payload = _payload([slide])
    cls = _classify(slide, group_child_words=slide["groupChildText"], group_children=slide["groupChildren"])
    assert not cls.long_text_ids  # no autosize `kind == "text"` child -> no groupchild long id at all
    decisions = {5: SlideDecision(5, "in_deck")}
    with pytest.raises(AssemblyRefusal, match="fixed-frame text inside group 0 unsupported"):
        plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})


def test_fixed_frame_group_text_kind_text_over_threshold_refuses():
    # D1 Codex fix round 2 MAJOR: a fixed-frame (autosize False) child whose ONLY
    # membership is text (no shape) keeps `kind == "text"` from `_all_group_child_records`
    # -- before the fix, `_is_text_slide_kept` mistook it for a supported autosize long
    # id (its check was `kind == "text"` alone) and the refusal's `kind != "text"` guard
    # then let it through unrefused, so it was stacked and emitted with no `set height`.
    # The kind-agnostic `has_text and autosize is False` refusal must still catch it.
    objects = {
        "900": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 4702.0, "y": 15.0}, "size": {"width": 645.0, "height": 443.0}, "angle": 0.0},
            "children": [{"identifier": "901"}],
        },
        "901": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True,
            "super": {"geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 645.0, "height": 443.0}, "angle": 0.0}},
        },
    }
    records = dsa._all_group_child_records(objects["900"], objects)
    assert [r["kind"] for r in records] == ["text"]
    assert [r["autosize"] for r in records] == [False]
    group = _group_item(0, x=4702, y=15, w=645, h=443)
    slide = _slide(5, [group])
    slide["groupChildText"] = {0: _GW5_VERSE}
    slide["groupChildSignature"] = {0: f"text:{_GW5_VERSE}"}
    slide["groupChildren"] = {0: records}
    payload = _payload([slide])
    cls = _classify(slide, group_child_words=slide["groupChildText"], group_children=slide["groupChildren"])
    assert not cls.long_text_ids  # not autosize -> no groupchild long id despite kind == "text"
    decisions = {5: SlideDecision(5, "in_deck")}
    with pytest.raises(AssemblyRefusal, match="fixed-frame text inside group 0 unsupported"):
        plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})


_DUAL_TEXT_12_WORDS = (
    "Matthew eighteen verse fifteen through seventeen tells us how to reconcile today"
)


def _fixed_long_plus_autosize_short_group_records(fixed_text=_DUAL_TEXT_12_WORDS, storage_id="912"):
    """Raw archive for a group with a fixed-frame (autosize False) 12-word text child
    (kindIndex 0) and an autosize 1-word text child (kindIndex 1) -- Codex D1 fix round 3's
    case: the group-level exemption (`group_ki in text_group_kis`) used to hide the fixed
    child once the autosize sibling qualified the group as text-triggering."""
    objects = {
        "900": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 4702.0, "y": 15.0}, "size": {"width": 1442.0, "height": 443.0}, "angle": 0.0},
            "children": [{"identifier": "901"}, {"identifier": "911"}],
        },
        "901": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": storage_id},
            "super": {"geometry": {
                "position": {"x": 0.0, "y": 0.0}, "size": {"width": 645.0, "height": 92.0}, "angle": 0.0,
            }},
        },
        "911": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "913"},
            "super": {
                "geometry": {"position": {"x": 0.0, "y": 100.0}, "size": {"width": 1442.0, "height": 0.0}, "angle": 0.0},
                "pathsource": {"bezierPathSource": {"naturalSize": {"width": 1442.0, "height": 343.0}}},
            },
        },
        "913": {"_pbtype": "TSWP.StorageArchive", "text": ["Amen"]},
    }
    if storage_id != "no-storage":
        objects[storage_id] = {"_pbtype": "TSWP.StorageArchive", "text": [fixed_text]}
    records = dsa._all_group_child_records(objects["900"], objects)
    return records


def test_fixed_frame_long_child_refuses_despite_autosize_short_sibling():
    # D1 Codex fix round 3 MAJOR: a top-level long text box PLUS a group holding a
    # 12-word fixed-frame text child and a 1-word autosize text child. The group's DFS
    # word join (12 + 1 = 13) triggers text classification via the autosize child alone
    # -- the group-level exemption used to let BOTH children fall into short_children,
    # emitting the fixed-frame long child position-only with no `set height`. Per-child
    # words must refuse regardless of the autosize sibling.
    _require_font("AzoSans-Regular")
    records = _fixed_long_plus_autosize_short_group_records()
    assert [(r["kind"], r["autosize"], r["words"]) for r in records] == [
        ("text", False, 12), ("text", True, 1),
    ]
    top_box = _long_text_item(0, _VERSE_1, x=200, y=200, w=1800, h=300)
    group = _group_item(0, x=4702, y=15, w=1442, h=443)
    slide = _slide(5, [top_box, group])
    slide["groupChildText"] = {0: f"{_DUAL_TEXT_12_WORDS} Amen"}
    slide["groupChildSignature"] = {0: f"text:{_DUAL_TEXT_12_WORDS}\ntext:Amen"}
    slide["groupChildren"] = {0: records}
    slide["groupChildRuns"] = {0: {1: {
        "text": "Amen", "font": "AzoSans-Regular", "size": 70.0,
        "runs": [{"text": "Amen", "fontName": "AzoSans-Regular", "size": 70.0}],
    }}}
    payload = _payload([slide])
    cls = _classify(slide, group_child_words=slide["groupChildText"], group_children=slide["groupChildren"])
    assert cls.long_text_ids == (("text", 0), ("groupchild", 0, "text", 1))
    decisions = {5: SlideDecision(5, "in_deck")}
    with pytest.raises(AssemblyRefusal, match="fixed-frame text inside group 0 unsupported"):
        plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})


def test_fixed_frame_child_unresolvable_text_refuses_conservatively():
    # Round 3: a fixed-frame child whose text cannot be resolved (`words` is ``None``,
    # e.g. its `ownedStorage` points nowhere) must refuse conservatively rather than be
    # treated as short.
    records = _fixed_long_plus_autosize_short_group_records(storage_id="no-storage")
    assert records[0]["words"] is None
    top_box = _long_text_item(0, _VERSE_1, x=200, y=200, w=1800, h=300)
    group = _group_item(0, x=4702, y=15, w=1442, h=443)
    slide = _slide(5, [top_box, group])
    slide["groupChildText"] = {0: f"{_DUAL_TEXT_12_WORDS} Amen"}
    slide["groupChildSignature"] = {0: f"text:{_DUAL_TEXT_12_WORDS}\ntext:Amen"}
    slide["groupChildren"] = {0: records}
    slide["groupChildRuns"] = {0: {1: {
        "text": "Amen", "font": "AzoSans-Regular", "size": 70.0,
        "runs": [{"text": "Amen", "fontName": "AzoSans-Regular", "size": 70.0}],
    }}}
    payload = _payload([slide])
    cls = _classify(slide, group_child_words=slide["groupChildText"], group_children=slide["groupChildren"])
    decisions = {5: SlideDecision(5, "in_deck")}
    with pytest.raises(AssemblyRefusal, match="fixed-frame text inside group 0 unsupported"):
        plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})


_TEN_WORD_TEXT = "Matthew eighteen verse fifteen through seventeen tells us how reconcile"


def _fixed_word_boundary_group_records(fixed_text):
    """Variant of `_fixed_long_plus_autosize_short_group_records` with the autosize
    sibling placed clear of the fixed child's x-range, so a NOT-refuse boundary case
    can run `plan_assembly` to completion without tripping the unrelated short-row
    overlap check (F1)."""
    objects = {
        "900": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 4702.0, "y": 15.0}, "size": {"width": 2100.0, "height": 100.0}},
            "children": [{"identifier": "901"}, {"identifier": "911"}],
        },
        "901": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "912"},
            "super": {"geometry": {
                "position": {"x": 0.0, "y": 0.0}, "size": {"width": 100.0, "height": 80.0}, "angle": 0.0,
            }},
        },
        "911": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True, "ownedStorage": {"identifier": "913"},
            "super": {
                "geometry": {"position": {"x": 2000.0, "y": 0.0}, "size": {"width": 100.0, "height": 0.0}, "angle": 0.0},
                "pathsource": {"bezierPathSource": {"naturalSize": {"width": 100.0, "height": 100.0}}},
            },
        },
        "912": {"_pbtype": "TSWP.StorageArchive", "text": [fixed_text]},
        "913": {"_pbtype": "TSWP.StorageArchive", "text": ["Amen"]},
    }
    return dsa._all_group_child_records(objects["900"], objects)


def test_fixed_frame_child_word_count_normalizes_placeholder_at_boundary():
    # D1 Codex fix round 4 MINOR: `_child_word_count` must normalize the child's raw
    # storage text the same way `groupChildText` does (`iwa_runs._normalize_text`)
    # before counting words, so a standalone object-replacement character ("￼")
    # in the storage text doesn't inflate the per-child count past the aggregate's.
    # A fixed-frame child at exactly `text_slide_words` (10) words plus a standalone
    # placeholder token must NOT refuse (10 == threshold after normalisation); the
    # same child with one more real word must refuse.
    at_threshold = _fixed_word_boundary_group_records(f"{_TEN_WORD_TEXT} ￼")
    assert [(r["kind"], r["autosize"], r["words"]) for r in at_threshold] == [
        ("text", False, 10), ("text", True, 1),
    ]
    top_box = _long_text_item(0, _VERSE_1, x=200, y=200, w=1800, h=300)
    group = _group_item(0, x=4702, y=15, w=2100, h=100)
    slide = _slide(5, [top_box, group])
    slide["groupChildText"] = {0: f"{_TEN_WORD_TEXT} Amen"}
    slide["groupChildSignature"] = {0: f"text:{_TEN_WORD_TEXT}\ntext:Amen"}
    slide["groupChildren"] = {0: at_threshold}
    slide["groupChildRuns"] = {0: {1: {
        "text": "Amen", "font": "AzoSans-Regular", "size": 70.0,
        "runs": [{"text": "Amen", "fontName": "AzoSans-Regular", "size": 70.0}],
    }}}
    payload = _payload([slide])
    cls = _classify(slide, group_child_words=slide["groupChildText"], group_children=slide["groupChildren"])
    decisions = {5: SlideDecision(5, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    assert 5 in plan.fits

    over_threshold = _fixed_long_plus_autosize_short_group_records(fixed_text=f"{_TEN_WORD_TEXT} today")
    assert over_threshold[0]["words"] == 11
    slide["groupChildText"] = {0: f"{_TEN_WORD_TEXT} today Amen"}
    slide["groupChildSignature"] = {0: f"text:{_TEN_WORD_TEXT} today\ntext:Amen"}
    slide["groupChildren"] = {0: over_threshold}
    payload = _payload([slide])
    cls = _classify(slide, group_child_words=slide["groupChildText"], group_children=slide["groupChildren"])
    with pytest.raises(AssemblyRefusal, match="fixed-frame text inside group 0 unsupported"):
        plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})


def test_fixed_frame_group_text_under_threshold_unaffected():
    # Companion to the refusal above: a NON-text-triggering group (a short caption, under
    # `text_slide_words`) with a fixed-frame text child on an otherwise ordinary content
    # slide must be unaffected -- the new check only fires for a group whose DFS word
    # join is actually over threshold.
    photo = _image_item(0, x=1920, y=0, w=3840, h=1080)
    group = _group_item(0, x=2000, y=100, w=300, h=80)
    slide = _slide(5, [photo, group])
    caption = "Short caption"
    slide["groupChildText"] = {0: caption}
    slide["groupChildSignature"] = {0: f"shape:{caption}"}
    slide["groupChildren"] = {0: [
        {
            "kind": "shape", "kindIndex": 0, "autosize": False, "has_text": True,
            "x": 2000.0, "y": 100.0, "w": 300.0, "h": 80.0,
        },
    ]}
    payload = _payload([slide])
    cls = _classify(slide, group_child_words=slide["groupChildText"], group_children=slide["groupChildren"])
    assert not cls.is_text
    decisions = {5: SlideDecision(5, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    assert 5 in plan.fits


def test_content_ids_excludes_text_triggering_group():
    # New finding 3: a group already used as a text carrier (its child text triggered
    # the text-slide classification) must never also count towards anchoring content,
    # even when it separately has a media child -- matching `_content_ids`' own
    # docstring rule ("text-only content never counts").
    from obed_edom.dsk_plan import SlideClass

    cls = SlideClass(
        number=5, category="mixed", build_count=0, movie_count=0,
        kept=(("image", 0), ("group", 1)), dropped_side=(), dropped_backdrop=(),
        transition=None, is_text=True, long_text_ids=(("groupchild", 1, "text", 0),),
    )
    group_signature = {1: "image:photo\ntext:verse"}
    without_exclusion = dsa._content_ids(cls, group_signature=group_signature)
    assert ("group", 1) in without_exclusion

    with_exclusion = dsa._content_ids(
        cls, group_signature=group_signature, exclude_group_kis={1},
    )
    assert ("group", 1) not in with_exclusion
    assert ("image", 0) in with_exclusion


def test_image_child_in_text_triggering_group_refuses():
    # New finding 3 (owner decision): an image child inside a text-triggering group is
    # neither dropped nor scaled by the short-row path, unlike a top-level image on a
    # text slide (`dropped_media_text`) -- refuse, consistent with the movie-nested-in-
    # group refusal.
    group = _group_item(0, x=4702, y=15, w=645, h=92)
    slide = _slide(5, [group])
    slide["groupChildText"] = {0: _GW5_VERSE}
    slide["groupChildSignature"] = {0: f"image:photo\ntext:{_GW5_VERSE}"}
    slide["groupChildren"] = {0: [
        {"kind": "image", "kindIndex": 0, "autosize": False, "x": 4702.0, "y": 15.0, "w": 645.0, "h": 92.0},
        {"kind": "text", "kindIndex": 1, "autosize": True, "x": 4303.0, "cy": 89.0, "y": -88.0, "w": 1442.0, "h": 355.0},
    ]}
    slide["groupChildRuns"] = {0: {1: {
        "text": _GW5_VERSE, "font": "AzoSans-Regular", "size": 70.0,
        "runs": [{"text": _GW5_VERSE, "fontName": "AzoSans-Regular", "size": 70.0}],
    }}}
    payload = _payload([slide])
    cls = _classify(slide, group_child_words=slide["groupChildText"], group_children=slide["groupChildren"])
    decisions = {5: SlideDecision(5, "in_deck")}
    with pytest.raises(AssemblyRefusal, match="image nested in text-triggering group"):
        plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})


def test_group_badge_wider_than_band_refuses():
    # Opus D1 review 3 finding 3: the `badge_w > band.width` refusal (dsk_assemble.py,
    # the only new refusal in this round without a discriminating test) -- a synthetic
    # group badge wider than the band must refuse before any clamp is attempted.
    _require_font("AzoSans-Regular")
    photo = _image_item(0, x=1920, y=-1024, w=3840, h=2561)
    group = _group_item(0, x=4702, y=15, w=2000, h=92)
    slide = _slide(5, [photo, group])
    slide["groupChildText"] = {0: _GW5_VERSE}
    slide["groupChildSignature"] = {0: f"shape:badge\ntext:{_GW5_VERSE}"}
    slide["groupChildren"] = {0: [
        {"kind": "shape", "kindIndex": 0, "autosize": False, "x": 4702.0, "y": 15.0, "w": 2000.0, "h": 92.0},
        {"kind": "text", "kindIndex": 1, "autosize": True, "x": 4303.0, "cy": 89.0, "y": -88.0, "w": 1442.0, "h": 355.0},
    ]}
    slide["groupChildRuns"] = {0: {1: {
        "text": _GW5_VERSE, "font": "AzoSans-Regular", "size": 70.0,
        "runs": [{"text": _GW5_VERSE, "fontName": "AzoSans-Regular", "size": 70.0}],
    }}}
    payload = _payload([slide])
    cls = _classify(slide, group_child_words=slide["groupChildText"], group_children=slide["groupChildren"])
    decisions = {5: SlideDecision(5, "in_deck")}
    with pytest.raises(AssemblyRefusal, match="is wider than the band"):
        plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})


def test_group_nested_child_refuses_even_with_top_level_long_text():
    # New finding 2: a text-triggering group's nested (non-flat) text child must refuse
    # unconditionally, even when the slide also has a top-level long text item that
    # would otherwise leave `long_ids` non-empty and let the slide fall through to
    # placing the nested child position-only in the short row with a bogus AppleScript
    # address (re-opening F9 for the nested case).
    top_text = _text_item(0, x=2000, y=0, w=800, h=200)
    top_text["text"] = _GW5_VERSE
    top_text["font"] = "AzoSans-Regular"
    top_text["size"] = 40.0
    top_text["runs"] = [{"text": _GW5_VERSE, "fontName": "AzoSans-Regular", "size": 40.0}]
    group = _group_item(0, x=3000, y=0, w=645, h=92)
    slide = _slide(5, [top_text, group])
    slide["groupChildText"] = {0: _GW5_VERSE}
    slide["groupChildSignature"] = {0: f"text:{_GW5_VERSE}"}
    slide["groupChildren"] = {0: [
        {
            "kind": "text", "kindIndex": 1, "autosize": True, "x": 3050.0, "cy": 89.0,
            "y": -88.0, "w": 1442.0, "h": 355.0, "group_path": (0,),
        },
    ]}
    slide["groupChildRuns"] = {0: {1: {
        "text": _GW5_VERSE, "font": "AzoSans-Regular", "size": 70.0,
        "runs": [{"text": _GW5_VERSE, "fontName": "AzoSans-Regular", "size": 70.0}],
    }}}
    payload = _payload([slide])
    cls = _classify(slide, group_child_words=slide["groupChildText"], group_children=slide["groupChildren"])
    assert cls.is_text
    assert ("text", 0) in cls.long_text_ids
    assert ("groupchild", 0, "text", 1) in cls.long_text_ids

    decisions = {5: SlideDecision(5, "in_deck")}
    with pytest.raises(AssemblyRefusal, match="nested"):
        plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})


def test_group_verse_slide_refuses_without_group_children():
    photo = _image_item(0, x=1920, y=-1024, w=3840, h=2561)
    group = _group_item(0, x=4702, y=15, w=645, h=92)
    slide = _slide(5, [photo, group])
    slide["groupChildText"] = {0: _GW5_VERSE}  # long -- would classify as text...
    # ...but no groupChildren entry (nested/rotated/masked group -- unavailable offline).
    payload = _payload([slide])
    cls = _classify(slide, group_child_words=slide["groupChildText"])
    decisions = {5: SlideDecision(5, "in_deck")}
    with pytest.raises(AssemblyRefusal, match="no offline child metadata"):
        plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})


# --------------------------------------------------------------------------
# _all_group_child_records / _attach_full_group_children:
# raw KN.GroupArchive fixtures -- real FW slide 2 group 1 is a flat TEXTUAL group
# with no autosize child, which iwa_runs.attach_group_children refuses outright.
# --------------------------------------------------------------------------
def test_all_group_child_records_returns_for_flat_group_without_autosize():
    objects = {
        "900": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 200.0, "height": 40.0}, "angle": 0.0},
            "children": [{"identifier": "901"}, {"identifier": "902"}],
        },
        "901": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True,
            "super": {"geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 100.0, "height": 40.0}, "angle": 0.0}},
        },
        "902": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True,
            "super": {"geometry": {"position": {"x": 100.0, "y": 0.0}, "size": {"width": 100.0, "height": 40.0}, "angle": 0.0}},
        },
    }
    records = dsa._all_group_child_records(objects["900"], objects)
    assert records is not None
    assert [r["kind"] for r in records] == ["text", "text"]
    assert [r["autosize"] for r in records] == [False, False]
    assert records[0]["x"] == pytest.approx(0.0)
    assert records[1]["x"] == pytest.approx(100.0)


def test_all_group_child_records_top_anchored_autosize_child_keeps_stored_top():
    # r13 attempt 6, Part B: a group child's own `verticalAlignment` (kFrameAlignTop, code
    # 0) must be honoured the same way `_autosize_rect` honours it for top-level items --
    # composing `y = abs_gy + cy` (the stored top), not `abs_gy + cy - h/2` (the middle-
    # anchored fallback). Numbers pinned to the GW 5 group from the refused r13 staging
    # deck (`~/Desktop/dsk-d4-work/out-r13/Sermon_PK_DSK.refused.key`, object 17548203/
    # 17548251): group at (1075.9092, 408.83987), child local y 457.16013, naturalSize
    # height 115.0 -- before this fix, the composed y was 808.50 (a ~57.9pt undershoot
    # against the 866.4pt slot top), which spuriously refused the assembly.
    objects = {
        "900": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 1075.9092, "y": 408.83987}, "size": {"width": 360.68298, "height": 107.39138}},
            "children": [{"identifier": "901"}],
        },
        "901": {
            "_pbtype": "TSWP.ShapeInfoArchive", "isTextBox": True,
            "super": {
                "geometry": {"position": {"x": -1021.9092, "y": 457.16013}, "size": {"width": 1799.0, "height": 0.0}, "angle": 0.0},
                "pathsource": {"bezierPathSource": {"naturalSize": {"width": 1799.0, "height": 115.0}}},
                "style": {"identifier": "902"},
            },
        },
        "902": {"shapeProperties": {"verticalAlignment": 0}},
    }
    records = dsa._all_group_child_records(objects["900"], objects)
    assert records is not None
    assert records[0]["y"] == pytest.approx(408.83987 + 457.16013)
    assert records[0]["h"] == pytest.approx(115.0)


def test_all_group_child_records_recurses_into_nested_group():
    """Nested groups are walked recursively, not refused."""
    nested = {
        "910": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 10.0, "y": 5.0}, "size": {"width": 200.0, "height": 40.0}, "angle": 0.0},
            "children": [{"identifier": "911"}],
        },
        "911": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 20.0, "y": 0.0}, "size": {"width": 50.0, "height": 40.0}, "angle": 0.0},
            "children": [{"identifier": "912"}],
        },
        "912": {
            "_pbtype": "TSD.ImageArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 30.0, "height": 30.0}, "angle": 0.0},
        },
    }
    records = dsa._all_group_child_records(nested["910"], nested)
    assert records is not None
    assert len(records) == 1
    rec = records[0]
    assert rec["kind"] == "image"
    assert rec["group_path"] == (0,)
    assert rec["x"] == pytest.approx(10.0 + 20.0)
    assert rec["y"] == pytest.approx(5.0 + 0.0)


def test_all_group_child_records_refuses_rotated_group():
    rotated = {
        "920": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 200.0, "height": 40.0}, "angle": 15.0},
            "children": [{"identifier": "921"}],
        },
        "921": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "super": {"geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 100.0, "height": 40.0}, "angle": 0.0}},
        },
    }
    assert dsa._all_group_child_records(rotated["920"], rotated) is None


def test_all_group_child_records_keeps_rotation_on_rotated_leaf():
    """A rotated (unmasked) leaf is scaled and kept, not refused; its recorded position is
    the rotated AABB top-left (as ``iwa_geometry._frame_rect`` computes), not the raw
    pre-rotation frame position -- the two diverge for any non-zero angle."""
    from obed_edom.iwa_geometry import _frame_rect

    objects = {
        "930": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 200.0, "height": 40.0}, "angle": 0.0},
            "children": [{"identifier": "931"}],
        },
        "931": {
            "_pbtype": "TSD.ImageArchive",
            "geometry": {"position": {"x": 10.0, "y": 0.0}, "size": {"width": 30.0, "height": 30.0}, "angle": 1.0},
        },
    }
    records = dsa._all_group_child_records(objects["930"], objects)
    assert records is not None
    rec = records[0]
    expected_x, expected_y, expected_w, expected_h = _frame_rect(objects["931"]["geometry"])
    assert rec["angle"] == pytest.approx(1.0)
    assert rec["x"] == pytest.approx(expected_x)
    assert rec["y"] == pytest.approx(expected_y)
    assert rec["w"] == pytest.approx(expected_w)
    assert rec["h"] == pytest.approx(expected_h)
    assert rec["x"] != pytest.approx(10.0)


def test_attach_full_group_children_attaches_for_non_autosize_group():
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "900"}]},
        "900": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 200.0, "height": 40.0}, "angle": 0.0},
            "children": [{"identifier": "901"}],
        },
        "901": {
            "_pbtype": "TSWP.ShapeInfoArchive",
            "super": {"geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 100.0, "height": 40.0}, "angle": 0.0}},
        },
    }
    payload = {"slides": [{"number": 1, "index": 0, "items": []}]}
    dsa._attach_full_group_children(Path("/tmp/fw.key"), payload, deck=(objects, {}, {}))
    assert 0 in payload["slides"][0]["groupChildren"]


def test_group_known_child_lines_lock_and_relock_the_parent_group_too():
    group = _group_item(0, x=1920, y=0, w=400, h=200)
    slide = _slide(1, [group])
    slide["groupChildren"] = {
        0: [{"kind": "text", "kindIndex": 0, "autosize": False, "x": 1920.0, "y": 0.0, "w": 200.0, "h": 200.0}]
    }
    slide["groupChildText"] = {0: "A"}
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    ordinal = plan.ordinals[1]
    assert f"set theGroupObj to group 1 of slide {ordinal}" in script
    assert "if wasGroupLocked then set locked of theGroupObj to true" in script
    assert "if wasLocked then set locked of theObj to true" in script


# --------------------------------------------------------------------------
# clip slide: repetition/volume read+write is fatal, not swallowed
# --------------------------------------------------------------------------
def test_script_repetition_volume_read_not_swallowed():
    plan = _clip_plan()
    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"), layout_policy="preserve"
    )
    assert "set repMethod0 to (repetition method of" in script
    assert "set movVol0 to (movie volume of" in script
    assert "is not missing value" not in script


# --------------------------------------------------------------------------
# build_assembly_script -- structural snapshot assertions
# --------------------------------------------------------------------------
def _clip_plan():
    movie_item = _movie_item(0, x=1920, y=-763, w=3840, h=2160)
    static_item = _image_item(0, x=1920, y=0, w=3840, h=1080)
    slide_movie = _slide(32, [movie_item])
    slide_static = _slide(8, [static_item])
    payload = _payload([slide_static, slide_movie])
    classes = [_classify(slide_static), _classify(slide_movie)]
    decisions = {
        8: SlideDecision(8, "in_deck"),
        32: SlideDecision(32, "in_deck"),
    }
    return plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={32: Path("/tmp/clip.mov")}
    )


def test_script_deletes_come_first_and_descending():
    plan = _clip_plan()
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    keep_idx = script.index("set keepList to")
    body_idx = script.index('tell theDoc')
    assert body_idx < keep_idx
    delete_idx = script.index("if keepList does not contain i then delete slide i of theDoc")
    assert delete_idx > keep_idx


def test_script_canvas_block_always_present():
    plan = _clip_plan()
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    assert "set width of theDoc to 1920" in script
    assert "set height of theDoc to 1080" in script


def test_script_canvas_resize_precedes_layout_import_and_base_layout_set():
    plan = _clip_plan()
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    resize_idx = script.index(f"set width of theDoc to {plan.canvas[0]}")
    import_idx = script.index("set tmplDoc to open POSIX file")
    base_layout_idx = script.index("set base layout of slide")
    assert resize_idx < import_idx
    assert resize_idx < base_layout_idx


def test_script_canvas_resize_precedes_base_layout_set_without_slide_layout_names():
    plan = _clip_plan()
    script = build_assembly_script(
        plan,
        scratch_path=Path("/tmp/scratch.key"),
        staging_path=Path("/tmp/staged.key"),
        slide_layout_names=None,
    )
    resize_idx = script.index(f"set width of theDoc to {plan.canvas[0]}")
    black_names_idx = script.index("set blackNames to")
    base_layout_idx = script.index("set base layout of slide")
    assert resize_idx < black_names_idx
    assert resize_idx < base_layout_idx


def test_script_layout_preserve_touches_nothing():
    plan = _clip_plan()
    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"), layout_policy="preserve"
    )
    assert "wantLayoutName" not in script
    assert "set base layout of slide" not in script


def test_script_layout_import_is_default_and_imports_every_dsk_layout_name():
    plan = _clip_plan()
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    assert "set base layout of slide" in script
    assert "set tmplDoc to open POSIX file" in script
    for name in dsa.DEFAULT_DSK_LAYOUT_NAMES:
        assert f'set wantLayoutName to "{name}"' in script
    assert script.count("set madeSlide to (make new slide") == len(dsa.DEFAULT_DSK_LAYOUT_NAMES)
    assert script.count("delete donorSlide") == len(dsa.DEFAULT_DSK_LAYOUT_NAMES)


def test_script_target_layout_lookup_is_case_insensitive():
    plan = _clip_plan()
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    assert "ignoring case" in script
    assert "end ignoring" in script
    idx = script.index('set blackNames to')
    assert "(name of lay as text) is in blackNames" in script[idx:]


def test_script_three_name_import_has_three_donor_pairs_and_no_blank():
    plan = _clip_plan()
    script = build_assembly_script(
        plan,
        scratch_path=Path("/tmp/scratch.key"),
        staging_path=Path("/tmp/staged.key"),
        import_layout_names=("Point 3 Lines", "Point (2 Lines)", "Blank Black"),
    )
    assert script.count("set madeSlide to (make new slide") == 3
    assert script.count("delete donorSlide") == 3
    assert 'set wantLayoutName to "Blank"' not in script


# --------------------------------------------------------------------------
# Offline layout resolution/alpha gate -- synthetic KN.ThemeArchive/KN.SlideArchive.
# --------------------------------------------------------------------------
def _layout_objects(*layouts):
    """`layouts`: (node_id, slide_id, name, template_uuid, rects) where `rects` is a
    list of (x, y, w, h) drawable frames. Returns an `objects` dict wired as a
    `KN.ThemeArchive` with one template per layout, each a `KN.SlideNodeArchive` wrapping
    a `KN.SlideArchive` -- mirrors the real graph (no separate layout type)."""
    objects: dict = {"theme": {"_pbtype": "KN.ThemeArchive", "templates": []}}
    for node_id, slide_id, name, template_uuid, rects in layouts:
        drawables = []
        for i, (x, y, w, h) in enumerate(rects):
            did = f"{slide_id}-d{i}"
            objects[did] = {
                "_pbtype": "TSD.ImageArchive",
                "geometry": {"position": {"x": x, "y": y}, "size": {"width": w, "height": h}},
            }
            drawables.append({"identifier": did})
        objects[slide_id] = {"_pbtype": "KN.SlideArchive", "name": name, "drawablesZOrder": drawables}
        objects[node_id] = {
            "_pbtype": "KN.SlideNodeArchive", "slide": {"identifier": slide_id}, "templateSlideId": template_uuid
        }
        objects["theme"]["templates"].append({"identifier": node_id})
    return objects


def _image_drawable_slide(rects):
    drawables = []
    objects: dict = {}
    for i, (x, y, w, h) in enumerate(rects):
        did = f"d{i}"
        objects[did] = {
            "_pbtype": "TSD.ImageArchive",
            "geometry": {"position": {"x": x, "y": y}, "size": {"width": w, "height": h}},
        }
        drawables.append({"identifier": did})
    return {"drawablesZOrder": drawables}, objects


def test_layout_alpha_safe_full_canvas_drawable_is_unsafe():
    slide, objects = _image_drawable_slide([(-10.0, 0.0, 2000.0, 1080.0)])
    assert dsa.layout_alpha_safe(slide, objects, (1920.0, 1080.0)) is False


def test_layout_alpha_safe_band_only_drawable_is_safe():
    slide, objects = _image_drawable_slide([(100.0, 900.0, 500.0, 100.0)])
    assert dsa.layout_alpha_safe(slide, objects, (1920.0, 1080.0)) is True


def test_layout_alpha_safe_zero_drawables_is_safe():
    assert dsa.layout_alpha_safe({"drawablesZOrder": []}, {}, (1920.0, 1080.0)) is True


def test_layout_alpha_safe_full_canvas_via_group_union_is_unsafe():
    objects = {
        "g1": {
            "_pbtype": "TSD.GroupArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 1920.0, "height": 1080.0}, "angle": 0.0},
            "children": [{"identifier": "img1"}],
        },
        "img1": {
            "_pbtype": "TSD.ImageArchive",
            "geometry": {"position": {"x": -10.0, "y": 0.0}, "size": {"width": 2000.0, "height": 1080.0}, "angle": 0.0},
        },
    }
    slide = {"drawablesZOrder": [{"identifier": "g1"}]}
    assert dsa.layout_alpha_safe(slide, objects, (1920.0, 1080.0)) is False


def test_layout_alpha_safe_masked_image_composes_the_mask_not_the_raw_frame():
    objects = {
        "img1": {
            "_pbtype": "TSD.ImageArchive",
            "geometry": {"position": {"x": 0.0, "y": 0.0}, "size": {"width": 1920.0, "height": 1080.0}, "angle": 0.0},
            "mask": {"identifier": "mask1"},
        },
        "mask1": {
            "geometry": {"position": {"x": 100.0, "y": 900.0}, "size": {"width": 500.0, "height": 100.0}, "angle": 0.0},
        },
    }
    slide = {"drawablesZOrder": [{"identifier": "img1"}]}
    assert dsa.layout_alpha_safe(slide, objects, (1920.0, 1080.0)) is True


def test_template_layout_alpha_safe_resolves_by_name(monkeypatch):
    objects = _layout_objects(
        ("n1", "s1", "Blank Black", {"lower": "1", "upper": "1"}, []),
        ("n2", "s2", "Blank", {"lower": "2", "upper": "2"}, [(-10.0, 0.0, 2000.0, 1080.0)]),
    )
    objects["show"] = {"_pbtype": "KN.ShowArchive", "size": {"width": 1920.0, "height": 1080.0}}
    monkeypatch.setattr(dsa, "_load_deck", lambda path: (objects, {}, {}))
    assert dsa.template_layout_alpha_safe(Path("/tmp/template.key"), "Blank Black") is True
    assert dsa.template_layout_alpha_safe(Path("/tmp/template.key"), "blank") is False


def test_template_layout_alpha_safe_missing_name_refuses(monkeypatch):
    objects = _layout_objects()
    objects["show"] = {"_pbtype": "KN.ShowArchive", "size": {"width": 1920.0, "height": 1080.0}}
    monkeypatch.setattr(dsa, "_load_deck", lambda path: (objects, {}, {}))
    with pytest.raises(AssemblyRefusal, match="not found"):
        dsa.template_layout_alpha_safe(Path("/tmp/template.key"), "Nope")


def _dispatched_load_deck(template_objects, fw_objects):
    def _load(path):
        return (template_objects, {}, {}) if str(path) == "template" else (fw_objects, {}, {})

    return _load


def test_check_layout_import_preconditions_ok_when_fw_lacks_layout(monkeypatch):
    template_objects = _layout_objects(("n1", "s1", "Blank Black", {"lower": "1", "upper": "1"}, []))
    template_objects["show"] = {"_pbtype": "KN.ShowArchive", "size": {"width": 1920.0, "height": 1080.0}}
    fw_objects = _layout_objects()
    fw_objects["show"] = {"_pbtype": "KN.ShowArchive", "size": {"width": 7680.0, "height": 1080.0}}
    monkeypatch.setattr(dsk_live, "_load_deck", _dispatched_load_deck(template_objects, fw_objects))
    dsa.check_layout_import_preconditions(
        Path("fw"), layout_template=Path("template"), layout_names=("Blank Black",)
    )


def test_check_layout_import_preconditions_refuses_unsafe_donor(monkeypatch):
    template_objects = _layout_objects(
        ("n1", "s1", "Blank Black", {"lower": "1", "upper": "1"}, [(-10.0, 0.0, 2000.0, 1080.0)])
    )
    template_objects["show"] = {"_pbtype": "KN.ShowArchive", "size": {"width": 1920.0, "height": 1080.0}}
    monkeypatch.setattr(dsk_live, "_load_deck", lambda path: (template_objects, {}, {}))
    with pytest.raises(AssemblyRefusal, match="not alpha-safe"):
        dsa.check_layout_import_preconditions(
            Path("fw"), layout_template=Path("template"), layout_names=("Blank Black",)
        )


def test_check_layout_import_preconditions_dedupe_trap_refuses(monkeypatch):
    template_objects = _layout_objects(("n1", "s1", "Blank Black", {"lower": "1", "upper": "1"}, []))
    template_objects["show"] = {"_pbtype": "KN.ShowArchive", "size": {"width": 1920.0, "height": 1080.0}}
    fw_objects = _layout_objects(
        ("n2", "s2", "Blank Black", {"lower": "9", "upper": "9"}, [(-10.0, 0.0, 8000.0, 1080.0)])
    )
    fw_objects["show"] = {"_pbtype": "KN.ShowArchive", "size": {"width": 7680.0, "height": 1080.0}}
    monkeypatch.setattr(dsk_live, "_load_deck", _dispatched_load_deck(template_objects, fw_objects))
    with pytest.raises(AssemblyRefusal, match="dedupe"):
        dsa.check_layout_import_preconditions(
            Path("fw"), layout_template=Path("template"), layout_names=("Blank Black",)
        )


def test_check_layout_import_preconditions_dedupe_ok_when_fw_layout_safe(monkeypatch):
    template_objects = _layout_objects(("n1", "s1", "Blank Black", {"lower": "1", "upper": "1"}, []))
    template_objects["show"] = {"_pbtype": "KN.ShowArchive", "size": {"width": 1920.0, "height": 1080.0}}
    fw_objects = _layout_objects(("n2", "s2", "Blank Black", {"lower": "9", "upper": "9"}, []))
    fw_objects["show"] = {"_pbtype": "KN.ShowArchive", "size": {"width": 7680.0, "height": 1080.0}}
    monkeypatch.setattr(dsk_live, "_load_deck", _dispatched_load_deck(template_objects, fw_objects))
    dsa.check_layout_import_preconditions(
        Path("fw"), layout_template=Path("template"), layout_names=("Blank Black",)
    )


def _staged_objects(rects):
    objects = _layout_objects(("layoutNode", "layoutSlide", "Blank Black", {"lower": "1", "upper": "1"}, rects))
    objects["show"] = {
        "_pbtype": "KN.ShowArchive",
        "size": {"width": 1920.0, "height": 1080.0},
        "slideTree": {"slides": [{"identifier": "slideNode1"}]},
    }
    objects["slideNode1"] = {"slide": {"identifier": "realSlide1"}}
    objects["realSlide1"] = {
        "name": None, "drawablesZOrder": [], "templateSlide": {"identifier": "layoutSlide"}
    }
    return objects


def test_check_layout_import_preconditions_refuses_blank():
    with pytest.raises(AssemblyRefusal, match="Blank is never alpha-safe"):
        dsa.check_layout_import_preconditions(
            Path("fw"), layout_template=Path("template"), layout_names=("Blank",)
        )


def test_check_layout_import_preconditions_refuses_duplicate_named_donor(monkeypatch):
    template_objects = _layout_objects(
        ("n1", "s1", "Point 3 Lines", {"lower": "1", "upper": "1"}, []),
        ("n2", "s2", "Point 3 Lines", {"lower": "2", "upper": "2"}, []),
    )
    template_objects["show"] = {"_pbtype": "KN.ShowArchive", "size": {"width": 1920.0, "height": 1080.0}}
    fw_objects = _layout_objects()
    fw_objects["show"] = {"_pbtype": "KN.ShowArchive", "size": {"width": 7680.0, "height": 1080.0}}
    monkeypatch.setattr(dsk_live, "_load_deck", _dispatched_load_deck(template_objects, fw_objects))
    with pytest.raises(AssemblyRefusal, match="duplicate-name donor"):
        dsa.check_layout_import_preconditions(
            Path("fw"), layout_template=Path("template"), layout_names=("Point 3 Lines",)
        )


def test_verify_staged_layouts_alpha_safe_refuses_unsafe_layout(monkeypatch):
    objects = _staged_objects([(-10.0, 0.0, 2000.0, 1080.0)])
    monkeypatch.setattr(dsa, "_load_deck", lambda path: (objects, {}, {}))
    plan = AssemblyPlan(
        kept=(13,), ordinals={13: 1}, fits={}, deletes={}, clips={}, text_sizes={}, autosize={}, warnings=()
    )
    with pytest.raises(AssemblyRefusal, match="not alpha-safe"):
        dsa.verify_staged_layouts_alpha_safe(Path("/tmp/staged.key"), plan)


def test_verify_staged_layouts_alpha_safe_passes_when_safe(monkeypatch):
    objects = _staged_objects([])
    monkeypatch.setattr(dsa, "_load_deck", lambda path: (objects, {}, {}))
    plan = AssemblyPlan(
        kept=(13,), ordinals={13: 1}, fits={}, deletes={}, clips={}, text_sizes={}, autosize={}, warnings=()
    )
    dsa.verify_staged_layouts_alpha_safe(Path("/tmp/staged.key"), plan)


LOWER_THIRDS_TEMPLATE = Path.home() / "Desktop" / "Default Templates" / "2026_Lower-Thirds (ENG).key"


def test_real_lower_thirds_template_blank_black_safe_blank_unsafe():
    if not LOWER_THIRDS_TEMPLATE.is_file():
        pytest.skip(f"template not present (local operator file): {LOWER_THIRDS_TEMPLATE}")
    try:
        import keynote_parser  # noqa: F401
    except Exception:
        pytest.skip("keynote-parser (iwa extra) not installed")
    assert dsa.template_layout_alpha_safe(LOWER_THIRDS_TEMPLATE, "Blank Black") is True
    assert dsa.template_layout_alpha_safe(LOWER_THIRDS_TEMPLATE, "Blank") is False


def test_script_never_sets_group_width():
    plan = _clip_plan()
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    assert "set width of group" not in script


def test_script_unlock_relock_present():
    plan = _clip_plan()
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    assert "set locked of theObj to false" in script
    assert "set locked of theObj to true" in script


def test_script_logs_movie_props_for_clip_slides():
    plan = _clip_plan()
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    assert '"repetitionMethod"' in script
    assert '"movieVolume"' in script


def test_script_clip_insert_and_mov_extension():
    plan = _clip_plan()
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    ordinal = plan.ordinals[32]
    assert f"tell slide {ordinal}" in script
    assert "make new image with properties" in script
    assert "count of movies of slide" in script
    assert "set repetition method of newMov to repMethod" in script
    assert "set movie volume of newMov to movVol" in script


def test_script_transition_dissolve_only_on_clip_slides():
    plan = _clip_plan()
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    movie_ordinal = plan.ordinals[32]
    static_ordinal = plan.ordinals[8]
    assert f"set transition properties of slide {movie_ordinal} to " in script
    assert "{transition effect:dissolve, transition duration:0.5}" in script
    assert f"set transition properties of slide {static_ordinal} to " not in script


def test_script_deletes_after_geometry_per_slide():
    plan = _clip_plan()
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    ordinal = plan.ordinals[32]
    geometry_idx = script.index(f'set theObj to movie 1 of slide {ordinal}')
    delete_idx = script.index("delete theObj")
    assert geometry_idx < delete_idx


def test_delete_or_hide_placeholder_lines_branches_on_title_and_body():
    """Keynote refuses ``delete`` on the shape bound as the slide's default title/body
    item (errNum -10003, ``default title item``/``default body item`` are read-only per
    Keynote.sdef) -- hide it via the read-write ``title showing``/``body showing``
    properties instead, matching plain delete for every other shape. Identity is an
    ``is`` comparison inside a ``try`` (``iWork item``/``shape``/``text item`` have no
    ``id`` property per Keynote.sdef), and each hide branch logs a ``HIDDEN`` marker
    naming the object and slot."""
    from obed_edom.remap_keynote import _delete_or_hide_placeholder_lines

    lines = _delete_or_hide_placeholder_lines(17, 17, "shape 2 of slide 17")
    script = "\n".join(lines)
    assert "delete theObj" in script
    assert "set title showing of slide 17 to false" in script
    assert "set body showing of slide 17 to false" in script
    assert "theObj is (default title item of slide 17)" in script
    assert "theObj is (default body item of slide 17)" in script
    assert 'HIDDEN" & tab & "17" & tab & "shape 2 of slide 17" & tab & "title"' in script
    assert 'HIDDEN" & tab & "17" & tab & "shape 2 of slide 17" & tab & "body"' in script
    assert sum(1 for ln in lines if ln.strip() == "try") >= 2


def test_delete_or_hide_placeholder_lines_missing_title_item_falls_through_to_delete():
    """No title item on the slide: ``default title item`` raises inside the wrapping
    ``try``, ``isTitle``/``isBody`` stay false, and the object is plainly deleted."""
    from obed_edom.remap_keynote import _delete_or_hide_placeholder_lines

    lines = _delete_or_hide_placeholder_lines(9, 9, "shape 3 of slide 9")
    script = "\n".join(lines)
    else_idx = script.index("else")
    delete_idx = script.index("delete theObj")
    title_idx = script.index("if isTitle then")
    assert title_idx < else_idx < delete_idx


def test_script_shape_text_dual_dedupes_to_one_delete_address():
    """GW-17-shaped case: ``shape 2`` and ``text item 4`` are the *same* underlying
    object (dual: one id under two kinds), so the planned delete set for this slide
    carries a single address per underlying object; ``build_assembly_script`` must
    still route every one of those addresses through the title/body placeholder guard,
    in the given order, not a bare unconditional ``delete theObj`` (the dedupe itself
    lives in ``dsk_plan._delete_order`` and is covered directly there)."""
    import dataclasses  # noqa: PLC0415

    kept_text = _text_item(0, x=2385, y=20, w=626, h=92, runs=[{"size": 40.0}])
    slide = _slide(17, [kept_text])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {17: SlideDecision(17, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    ordinal = plan.ordinals[17]
    gw17_deletes_deduped = (("shape", 1), ("text", 5), ("text", 3))  # ("text", 4) is shape 1's dual
    plan = dataclasses.replace(plan, deletes={17: gw17_deletes_deduped})
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    assert script.count(f"set title showing of slide {ordinal} to false") == 3
    assert script.count(f"set body showing of slide {ordinal} to false") == 3
    assert "delete theObj" in script
    addrs = [f"shape 2 of slide {ordinal}", f"text item 6 of slide {ordinal}", f"text item 4 of slide {ordinal}"]
    positions = [script.index(f"set theObj to {addr}") for addr in addrs]
    assert positions == sorted(positions)


def test_script_no_literal_keynote_and_has_obed_err_markers():
    plan = _clip_plan()
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    assert '"Keynote"' not in script
    assert 'tell application "Keynote"' not in script
    assert '"OBED"' in script
    assert '"ERR"' in script


# --------------------------------------------------------------------------
# Deck-backed test -- real Sermon_PK (GW).key, skipped when unavailable.
# --------------------------------------------------------------------------
GW_DECK = Path("/Users/anyhowclick/Desktop/Diff-Checker/Sermon_PK (GW).key")


def _require_gw_deck():
    if not GW_DECK.is_file():
        pytest.skip(f"deck not present (local operator file): {GW_DECK}")
    try:
        import keynote_parser  # noqa: F401
    except Exception:
        pytest.skip("keynote-parser (iwa extra) not installed")


GOLD_DECK = Path("/Users/anyhowclick/Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key")


def _require_gold_deck():
    if not GOLD_DECK.is_file():
        pytest.skip(f"deck not present (local operator file): {GOLD_DECK}")
    try:
        import keynote_parser  # noqa: F401
    except Exception:
        pytest.skip("keynote-parser (iwa extra) not installed")


# Plan §1.1 gold-deck layout inventory (`p1_layout_inventory.py`), pinned by slide
# number -- independent of `KN.SlideArchive.templateSlide`, the field under test.
GOLD_SLIDE_LAYOUT_NAMES: dict[int, str] = {
    **{n: "Blank Black" for n in (1, 4, 12, 13, 18, 19, 31, 32, 33, 34, 43)},
    **{n: "Point (2 Lines)" for n in (2, 40, 42)},
    **{n: "Verse Standard (Variation 2)" for n in (
        3, 9, 10, 11, 14, 15, 16, 17, 20, 21, 22, 23, 24, 25, 26, 27, 28, 35, 36, 37, 38
    )},
    **{n: "Verse 1 Line (Variation 2)" for n in (5, 6, 7, 8)},
    **{n: "Point 3 Lines" for n in (29, 30, 39, 41)},
}


@pytest.mark.deck
def test_base_layout_slide_for_ordinal_matches_gold_deck_layout_map():
    _require_gold_deck()
    objects, _id_to_file, _file_ids = dsa._load_deck(GOLD_DECK)
    nodes = dsa._slide_nodes(objects)
    assert len(nodes) == 43
    assert set(GOLD_SLIDE_LAYOUT_NAMES) == set(range(1, 44))
    for ordinal in range(1, len(nodes) + 1):
        expected_name = GOLD_SLIDE_LAYOUT_NAMES[ordinal]
        layout = dsa._base_layout_slide_for_ordinal(objects, ordinal)
        assert layout is not None, f"ordinal {ordinal}: base layout not resolvable"
        assert layout.get("name") == expected_name, f"ordinal {ordinal}: expected {expected_name!r}"


@pytest.mark.deck
def test_base_layout_slide_for_ordinal_matches_legacy_template_slide_id_map():
    """Cross-checks `_base_layout_slide_for_ordinal` (which resolves via the direct
    `templateSlide` object reference) against the legacy `templateSlideId` UUID mapping
    -- an independent resolution path over the same gold deck."""
    _require_gold_deck()
    objects, _id_to_file, _file_ids = dsa._load_deck(GOLD_DECK)
    by_tsid = {}
    for name, node, _slide in dsa._theme_layout_slides(objects):
        import json as _json

        by_tsid[_json.dumps(node.get("templateSlideId"), sort_keys=True)] = name
    nodes = dsa._slide_nodes(objects)
    for ordinal, node in enumerate(nodes, 1):
        import json as _json

        key = _json.dumps(node.get("templateSlideId"), sort_keys=True)
        expected_name = by_tsid[key]
        layout = dsa._base_layout_slide_for_ordinal(objects, ordinal)
        assert layout is not None
        assert layout.get("name") == expected_name


def test_base_layout_slide_for_ordinal_none_when_template_slide_missing():
    objects = {
        "show": {
            "_pbtype": "KN.ShowArchive",
            "slideTree": {"slides": [{"identifier": "node1"}]},
        },
        "node1": {"slide": {"identifier": "slide1"}},
        "slide1": {"_pbtype": "KN.SlideArchive", "name": None},
    }
    assert dsa._base_layout_slide_for_ordinal(objects, 1) is None


def test_base_layout_slide_for_ordinal_none_when_template_slide_dangling():
    objects = {
        "show": {
            "_pbtype": "KN.ShowArchive",
            "slideTree": {"slides": [{"identifier": "node1"}]},
        },
        "node1": {"slide": {"identifier": "slide1"}},
        "slide1": {
            "_pbtype": "KN.SlideArchive",
            "name": None,
            "templateSlide": {"identifier": "nonexistent-layout-slide"},
        },
    }
    assert dsa._base_layout_slide_for_ordinal(objects, 1) is None


def test_verify_staged_layouts_alpha_safe_refuses_missing_template_slide(tmp_path, monkeypatch):
    objects = {
        "show": {
            "_pbtype": "KN.ShowArchive",
            "size": {"width": 1920.0, "height": 1080.0},
            "slideTree": {"slides": [{"identifier": "node1"}]},
        },
        "node1": {"slide": {"identifier": "slide1"}},
        "slide1": {"_pbtype": "KN.SlideArchive", "name": None, "drawablesZOrder": []},
    }
    monkeypatch.setattr(dsa, "_load_deck", lambda path: (objects, {}, {}))
    plan = AssemblyPlan(kept=(1,), ordinals={1: 1}, fits={}, deletes={}, clips={}, text_sizes={}, autosize={}, warnings=())
    with pytest.raises(AssemblyRefusal, match="base layout not resolvable"):
        dsa.verify_staged_layouts_alpha_safe(Path("/tmp/staged.key"), plan)


def test_verify_staged_layouts_alpha_safe_refuses_dangling_template_slide(tmp_path, monkeypatch):
    objects = {
        "show": {
            "_pbtype": "KN.ShowArchive",
            "size": {"width": 1920.0, "height": 1080.0},
            "slideTree": {"slides": [{"identifier": "node1"}]},
        },
        "node1": {"slide": {"identifier": "slide1"}},
        "slide1": {
            "_pbtype": "KN.SlideArchive",
            "name": None,
            "drawablesZOrder": [],
            "templateSlide": {"identifier": "nonexistent-layout-slide"},
        },
    }
    monkeypatch.setattr(dsa, "_load_deck", lambda path: (objects, {}, {}))
    plan = AssemblyPlan(kept=(1,), ordinals={1: 1}, fits={}, deletes={}, clips={}, text_sizes={}, autosize={}, warnings=())
    with pytest.raises(AssemblyRefusal, match="base layout not resolvable"):
        dsa.verify_staged_layouts_alpha_safe(Path("/tmp/staged.key"), plan)


def test_load_and_plan_against_gw_deck():
    _require_gw_deck()
    payload, classes, runs = load_assembly_inputs(GW_DECK, include_side=frozenset({8}))
    decisions = {
        8: SlideDecision(8, "in_deck", keep_side=True),
        13: SlideDecision(13, "in_deck"),
        17: SlideDecision(17, "in_deck"),
        32: SlideDecision(32, "in_deck"),
    }
    plan = plan_assembly(
        payload,
        classes,
        decisions=decisions,
        band=BAND,
        clips={32: Path("/tmp/fake-clip.mov")},
        runs=runs,
    )
    assert plan.ordinals == {8: 1, 13: 2, 17: 3, 32: 4}
    fitted = plan.fits[32][("movie", 0)]
    assert fitted.x == pytest.approx(345.3, abs=0.1)
    assert fitted.y == pytest.approx(704.0, abs=0.1)
    assert fitted.w == pytest.approx(1244.4, abs=0.1)
    assert fitted.h == pytest.approx(350.0, abs=0.1)


def test_gw13_gw17_stack_budget_and_fit_t_under_default_band():
    # Pin the actual shipped result (plan.text_sizes/run_sizes scale, and the stack
    # budget itself) so the badge-fold-in-stack change has to be re-blessed by a future
    # edit, unlike the old test which asserted a bare-band t no shipped path produces.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    decisions = {13: SlideDecision(13, "in_deck"), 17: SlideDecision(17, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, runs=runs)

    t13 = next(iter(plan.run_sizes[13][("text", 1)]))[2] / 70.0
    assert t13 == pytest.approx(0.80, abs=0.01)

    t17 = next(iter(plan.run_sizes[17][("text", 1)]))[2] / 70.0
    assert t17 == pytest.approx(0.63, abs=0.01)

    badge13 = plan.fits[13][("shape", 0)]
    stack13 = [r for iid, r in plan.fits[13].items() if iid in plan.stacked_ids[13]]
    stack_top13 = min(r.y for r in stack13)
    assert stack_top13 - (badge13.y + badge13.h) == pytest.approx(dsa._TEXT_STACK_GAP, abs=0.5)


def test_gw_every_kept_non_movie_slide_plans_under_default_flags(tmp_path):
    """Real deck, real `fw_deck`, default flags, one slide at a time -- the gap
    that let the `plan_crops` 2-tuple early return crash every image-less slide
    on the live crop path while the suite stayed green."""
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    checked = 0
    # 44/50: D1 group-text-child classification (Design A) now correctly makes these
    # text slides too (F1's survey), but each also carries other short top-level content
    # competing for the band's short row -- at default --min-text-pt that budget is too
    # tight and plan_assembly refuses rather than overflow, same defect class as GW 5,
    # just with more content. Out of this brief's GW-5-only scope; not asserted here.
    for number, cls in by_number.items():
        if cls.movie_count > 0 or number in (44, 49, 50):
            continue
        decisions = {number: SlideDecision(number, "in_deck")}
        plan = plan_assembly(
            payload, [cls], decisions=decisions, band=BAND, clips={}, runs=runs,
            deck=deck, fw_deck=GW_DECK, crop_dir=tmp_path / "crops", all_classes=classes,
        )
        assert plan is not None
        checked += 1
    assert checked == 58


def test_gw_text_slides_stay_within_band_top():
    # Band-containment measured through the real placement path (_stacked_text_rects +
    # _short_row_rects via plan_assembly), for every GW text slide -- the defect that
    # put 11 of 21 slides out of band. Not an algebraic identity: this exercises the
    # actual rects plan_assembly writes, so a regression in either placement function
    # is caught here even if the budget math still looks right on paper.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    band_top = BAND.bottom - BAND.height
    checked = 0
    for number, cls in by_number.items():
        if not cls.is_text:
            continue
        decisions = {number: SlideDecision(number, "in_deck")}
        try:
            plan = plan_assembly(
                payload, [cls], decisions=decisions, band=BAND, clips={}, runs=runs, all_classes=classes,
            )
        except AssemblyRefusal:
            # GW 49 has a real run-size coverage gap with t < 1.0 -- refused rather
            # than assembled overflowing; not a band-containment case.
            continue
        fit = dict(plan.fits.get(number, {}))
        for part in plan.splits.get(number, ()):
            fit.update(part.fits)
        if not fit:
            continue
        checked += 1
        assert min(r.y for r in fit.values()) >= band_top - 1e-6, number
    assert checked >= 20


def test_gw44_badge_x_clears_title_right_edge():
    # F1 originally pinned this badge to the group's own fitted x so it cleared the
    # kept title's right edge under the old single-column short row. The
    # repeat-heading check must see the true deck-order predecessor even when
    # planned alone -- GW 51/53 correctly drop their (repeated) heading in every
    # batch (see the repeat-heading tests below, including
    # `test_repeat_heading_gw51_planned_alone_matches_batch`), so this invariant is
    # checked on GW 44 instead, whose heading is genuinely not a repeat:
    # the verse column is a disjoint region starting at `HEADING_COL_W + COL_GUTTER`
    # past the band's left edge, and the heading/title lives in the left column
    # entirely, so the badge still clears it, just via the two-column mechanism.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {44: SlideDecision(44, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[44]], decisions=decisions, band=BAND, clips={}, runs=runs, all_classes=classes,
    )

    title_rect = plan.fits[44][("text", 1)]
    badge_rect = plan.fits[44][("groupchild", 0, "shape", 0)]
    assert badge_rect.x >= title_rect.x + title_rect.w
    assert badge_rect.x == pytest.approx(501.0, abs=0.5)


def test_gw44_50_group_child_badge_caption_gets_text_size_write():
    # finding gw44-group-badge: the verse badge is a dual shape+text group child
    # (`_memberships` -> ["text", "shape"]) -- `iwa_runs._group_child_runs` used to
    # key its caption under "text"'s own counter (never matching its "shape"
    # addressing kindIndex), so the planner never saw its font/size and never wrote
    # a caption size -- the live script wrote the pill's position/size but left the
    # caption at whatever size the group's own (now-arbitrary) resize left it.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    for number in (44, 50):
        decisions = {number: SlideDecision(number, "in_deck")}
        plan = plan_assembly(
            payload, [by_number[number]], decisions=decisions, band=BAND, clips={}, runs=runs,
            all_classes=classes,
        )
        badge_id = ("groupchild", 0, "shape", 0)
        assert plan.text_sizes[number][badge_id] == pytest.approx(40.0)
        script = build_assembly_script(
            plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"),
        )
        addr = "shape 1 of group 1"
        assert "set size of object text of theObj to 40" in script
        # The badge write is addressed via the shape's own AS name/kindIndex.
        assert addr in script


def test_gw_group_text_slides_short_fit_stays_within_band_x():
    # New finding 1: every group-text slide's short-row (badge) groupchild rect must
    # clamp into [band.x_min, band.x_max] -- GW 53's badge overhung the canvas before
    # the clamp. Codex D1b-p2 review 1 finding 5: inspect `plan.short_fit` directly
    # (not every group-child rect in `plan.fits`, which also holds the stacked verse
    # and would pass even if only the verse -- not the badge -- were in band).
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    checked_ids: set[tuple[int, ItemId]] = set()
    for number in (5, 44, 50, 51, 53, 54):
        decisions = {number: SlideDecision(number, "in_deck")}
        try:
            plan = plan_assembly(
                payload, [by_number[number]], decisions=decisions, band=BAND, clips={}, runs=runs,
                all_classes=classes,
            )
        except AssemblyRefusal:
            continue
        for iid, rect in plan.short_fit.get(number, {}).items():
            if iid[0] != "groupchild":
                continue
            assert rect.x >= BAND.x_min - 1e-6, (number, iid)
            assert rect.x + rect.w <= BAND.x_max + 1e-6, (number, iid)
            checked_ids.add((number, iid))
    assert len(checked_ids) >= 4


def test_gw50_badge_x_clamped_to_band_right_edge():
    # New finding 1 originally reproduced a real-deck defect where GW 53's badge,
    # placed at the group's fitted x plus its source offset, overhung the canvas.
    # Codex D1b-p2 review 1 finding 2 fixed the repeat-heading check to see the true
    # deck-order predecessor even when planned alone -- GW 53 now correctly drops its
    # (repeated) heading in every batch (see the repeat-heading tests below), so the
    # two-column force-align (badge x = verse column's own left edge, never the
    # group's fitted x -- no clamp warning needed) is checked here on GW 50 instead,
    # whose heading is genuinely not a repeat.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {50: SlideDecision(50, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[50]], decisions=decisions, band=BAND, clips={}, runs=runs, all_classes=classes,
    )
    badge = plan.fits[50][("groupchild", 0, "shape", 0)]
    assert badge.x == pytest.approx(501.0, abs=0.5)


def test_short_row_rects_regression_moves_badge_out_of_band():
    # Tight synthetic case: stack_top set exactly gap + row_h above band top 704, so a
    # correctly gapped badge lands right on the band boundary. This pins the gap
    # subtraction in _short_row_rects -- a regression that drops or changes it would
    # move the badge off this boundary, out of the band.
    band_top = 704.0
    row_h = 50.0
    stack_top = band_top + dsa._TEXT_STACK_GAP + row_h
    short_fit = {("shape", 0): Rect(43.0, 0.0, 1849.0, row_h)}
    out = dsa._short_row_rects(short_fit, row_h, stack_top)
    badge = out[("shape", 0)]
    assert badge.y == pytest.approx(band_top, abs=1e-6)

    # One point less headroom above the stack moves the badge one point above the band
    # top -- exactly what a dropped or shortened gap in _short_row_rects would do.
    tight = dsa._short_row_rects(short_fit, row_h, stack_top - 1.0)
    assert tight[("shape", 0)].y == pytest.approx(band_top - 1.0, abs=1e-6)


def test_group_stacked_child_lines_writes_size_for_text_bearing_shape_badge():
    # Finding 4: a group-child SHAPE badge (kind collapses to "shape" but carries a
    # resolved text_size, i.e. the selected verse slot badge) must get its `object
    # text` size write and its exact slot width/height, not position-only -- the old
    # code gated the size write on `kind == "text"` alone.
    verse_child = {"kind": "text", "kindIndex": 1}
    verse_rect = Rect(63.1, 100.0, 933.1, 250.0)
    badge_child = {"kind": "shape", "kindIndex": 0}
    badge_rect = Rect(63.1, 785.8, 933.1, 82.1)
    entries = [
        (verse_child, verse_rect, 45.0, None, None),
        (badge_child, badge_rect, 40.0, None, None),
    ]
    lines = dsa._group_stacked_child_lines(1, 1, 0, entries)
    text = "\n".join(lines)
    assert "set size of object text of theObj to 40" in text
    assert "set width of theObj to 933.1" in text
    assert "set height of theObj to 82.1" in text
    # The verse (text kind) still never gets a height write (always autosize).
    verse_lines = dsa._group_stacked_child_lines(1, 1, 0, [(verse_child, verse_rect, 45.0, None, None)])
    verse_text = "\n".join(verse_lines)
    assert "set height of theObj" not in verse_text


def test_group_stacked_child_lines_unselected_short_child_position_only():
    # An unselected short-row group child (no resolved text_size/run_ranges) still gets
    # position only, left at source size, per the owner decision.
    other_child = {"kind": "shape", "kindIndex": 1}
    other_rect = Rect(0.0, 0.0, 50.0, 50.0)
    lines = dsa._group_stacked_child_lines(1, 1, 0, [(other_child, other_rect, None, None, None)])
    text = "\n".join(lines)
    assert "set position of theObj" in text
    assert "set size of object text of theObj" not in text
    assert "set width of theObj" not in text


def test_short_row_rects_pins_slot_badge_exact_y_standard_slot():
    # Finding 4: the SELECTED slot badge is excluded from the generic short-row reflow
    # -- its y stays the exact slot rect (Verse Standard's 785.8), never one reflowed
    # from the row/stack_top geometry (the round-2 bug: 774.3 instead of 785.8).
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    badge_id = ("text", 0)
    short_fit = {badge_id: slot.badge}
    out = dsa._short_row_rects(
        short_fit, row_h=slot.badge.h, stack_top=700.0, pinned_ids=frozenset({badge_id}),
    )
    assert out[badge_id] == slot.badge
    assert out[badge_id].y == 785.8


def test_short_row_rects_pins_slot_badge_exact_y_one_line_slot():
    # Same as above for the 1-line verse slot, whose badge.y is 878.4 -- a different
    # exact value than the Standard slot's, so a hard-coded/shared reflow constant
    # cannot pass both.
    slot = dsa.LAYOUT_SLOTS["Verse 1 Line (Variation 2)"]
    badge_id = ("text", 0)
    short_fit = {badge_id: slot.badge}
    out = dsa._short_row_rects(
        short_fit, row_h=slot.badge.h, stack_top=950.0, pinned_ids=frozenset({badge_id}),
    )
    assert out[badge_id] == slot.badge
    assert out[badge_id].y == 878.4


def test_gw17_28_forced_split_at_floor_66_refuses_gw28_single_box():
    # Acceptance table: forcing --min-text-pt 66 across GW 17/28 must split GW 17 (its
    # two-box stack can't clear the floor at any single t). GW 28's single box, once
    # pass 1 charges the run-aware estimate rather than the single-font underestimate,
    # also can't clear the floor and a lone box can't split -- refuses.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {n: SlideDecision(n, "in_deck") for n in (17, 28)}
    with pytest.raises(AssemblyRefusal, match="does not fit the band even alone"):
        plan_assembly(
            payload, [by_number[17], by_number[28]], decisions=decisions,
            band=BAND, clips={}, runs=runs, min_text_pt=66.0, all_classes=classes,
        )


def test_gw13_forced_floor_66_refuses_its_badge_gapped_single_box():
    # GW 13's own natural fit dropped from t=0.95 to t=0.91 once the stack budget
    # correctly charges the badge gap once, not zero times -- 0.91 * 70
    # is below the 66pt floor, and a single box can't split, so this now refuses
    # rather than assembling unsplit.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {13: SlideDecision(13, "in_deck")}
    with pytest.raises(AssemblyRefusal, match="does not fit the band even alone"):
        plan_assembly(
            payload, [by_number[13]], decisions=decisions, band=BAND, clips={}, runs=runs,
            min_text_pt=66.0, all_classes=classes,
        )


def test_gw13_stacked_text_does_not_overlap_badge():
    # GW 13's chapter badge and its long verse box must not overlap once the
    # verse is stacked -- the owner's reference slide for this bug.
    _require_gw_deck()
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, runs=runs)
    fit13 = plan.fits[13]
    stacked = plan.stacked_ids.get(13, frozenset())
    text_rects = [rect for iid, rect in fit13.items() if iid in stacked]
    assert text_rects, "GW 13's verse box should be stacked"
    for text_rect in text_rects:
        for other_iid, other_rect in fit13.items():
            if other_iid in plan.stacked_ids.get(13, frozenset()):
                continue
            assert dsa._intersect(text_rect, other_rect) is None, (
                f"stacked text overlaps {other_iid}: {text_rect} vs {other_rect}"
            )


def _heading_item(kind_index, text, font="ArgentCF-Bold", w=450, h=150):
    return {"kind": "text", "kindIndex": kind_index, "x": 0, "y": 0, "w": w, "h": h, "text": text, "font": font}


def _number_item(kind_index, text="3", w=35, h=80):
    return {
        "kind": "text", "kindIndex": kind_index, "x": 0, "y": 0, "w": w, "h": h,
        "text": text, "font": "AzoSans-Bold",
    }


def _circle_item(kind_index, w=81, h=81):
    return {"kind": "shape", "kindIndex": kind_index, "x": 0, "y": 0, "w": w, "h": h, "text": ""}


def _verse_item(kind_index, w=1492, h=358):
    return {
        "kind": "text", "kindIndex": kind_index, "x": 0, "y": 0, "w": w, "h": h,
        "text": "A long verse text that keeps going on and on.", "font": "AzoSans-Regular",
    }


def test_heading_cluster_detected():
    from obed_edom.dsk_plan import SlideClass

    heading = _heading_item(0, "Faith")
    number = _number_item(1)
    circle = _circle_item(0)
    verse = _verse_item(2)
    items_by_id = {
        ("text", 0): heading, ("text", 1): number, ("shape", 0): circle, ("text", 2): verse,
    }
    cls = SlideClass(
        number=5, category="static", build_count=0, movie_count=0,
        kept=(("text", 0), ("text", 1), ("shape", 0), ("text", 2)),
        dropped_side=(), dropped_backdrop=(), transition=None,
        is_text=True, long_text_ids=(("text", 2),),
    )
    cluster = dsa._heading_cluster(cls, items_by_id)
    assert cluster == dsa.HeadingCluster(("text", 0), ("text", 1), ("shape", 0))


def test_heading_cluster_rejects_two_headings():
    from obed_edom.dsk_plan import SlideClass

    heading0 = _heading_item(0, "Faith")
    heading1 = _heading_item(3, "Hope")
    number = _number_item(1)
    circle = _circle_item(0)
    verse = _verse_item(2)
    items_by_id = {
        ("text", 0): heading0, ("text", 3): heading1, ("text", 1): number,
        ("shape", 0): circle, ("text", 2): verse,
    }
    cls = SlideClass(
        number=5, category="static", build_count=0, movie_count=0,
        kept=(("text", 0), ("text", 3), ("text", 1), ("shape", 0), ("text", 2)),
        dropped_side=(), dropped_backdrop=(), transition=None,
        is_text=True, long_text_ids=(("text", 2),),
    )
    assert dsa._heading_cluster(cls, items_by_id) is None


def test_heading_cluster_none_without_long_text():
    from obed_edom.dsk_plan import SlideClass

    heading = _heading_item(0, "Faith")
    number = _number_item(1)
    circle = _circle_item(0)
    items_by_id = {("text", 0): heading, ("text", 1): number, ("shape", 0): circle}
    cls = SlideClass(
        number=5, category="static", build_count=0, movie_count=0,
        kept=(("text", 0), ("text", 1), ("shape", 0)),
        dropped_side=(), dropped_backdrop=(), transition=None,
        is_text=False, long_text_ids=(),
    )
    assert dsa._heading_cluster(cls, items_by_id) is None


def test_heading_cluster_gw_deck_measured_slides():
    # Probe (§6): the plan doc's measured D1b set is GW {44, 46, 50, 51, 52, 53}; this
    # fixes that measurement independently of the plan doc's own table.
    _require_gw_deck()
    payload, classes, _runs = load_assembly_inputs(GW_DECK)
    slides_by_number = {s["number"]: s for s in payload["slides"]}
    fires = set()
    for cls in classes:
        items_by_id = {
            (i["kind"], i["kindIndex"]): i for i in slides_by_number[cls.number]["items"]
        }
        if dsa._heading_cluster(cls, items_by_id) is not None:
            fires.add(cls.number)
    for expect_yes in (44, 46, 50, 51, 52, 53):
        assert expect_yes in fires, f"slide {expect_yes} should fire a heading cluster"
    for expect_no in (5, 54, 57):
        assert expect_no not in fires, f"slide {expect_no} should not fire a heading cluster"
    assert fires == {44, 46, 50, 51, 52, 53}


def _cls_for(kept, long_text_ids):
    from obed_edom.dsk_plan import SlideClass

    return SlideClass(
        number=5, category="static", build_count=0, movie_count=0,
        kept=kept, dropped_side=(), dropped_backdrop=(), transition=None,
        is_text=True, long_text_ids=long_text_ids,
    )


def test_heading_cluster_rejects_two_long_boxes():
    heading = _heading_item(0, "Faith")
    number = _number_item(1)
    circle = _circle_item(0)
    verse0 = _verse_item(2)
    verse1 = _verse_item(3)
    items_by_id = {
        ("text", 0): heading, ("text", 1): number, ("shape", 0): circle,
        ("text", 2): verse0, ("text", 3): verse1,
    }
    cls = _cls_for(
        (("text", 0), ("text", 1), ("shape", 0), ("text", 2), ("text", 3)),
        (("text", 2), ("text", 3)),
    )
    assert dsa._heading_cluster(cls, items_by_id) is None


def test_heading_cluster_rejects_unrelated_short_text():
    heading = _heading_item(0, "Faith")
    number = _number_item(1)
    circle = _circle_item(0)
    verse = _verse_item(2)
    stray = _number_item(3, text="Amen")
    stray["font"] = "AzoSans-Bold"
    items_by_id = {
        ("text", 0): heading, ("text", 1): number, ("shape", 0): circle,
        ("text", 2): verse, ("text", 3): stray,
    }
    cls = _cls_for(
        (("text", 0), ("text", 1), ("shape", 0), ("text", 2), ("text", 3)),
        (("text", 2),),
    )
    assert dsa._heading_cluster(cls, items_by_id) is None


def test_heading_cluster_accepts_verse_badge_pair():
    heading = _heading_item(0, "Prayer")
    number = _number_item(1)
    circle = _circle_item(0)
    verse = _verse_item(2)
    badge_text = {
        "kind": "text", "kindIndex": 3, "x": 100, "y": 44, "w": 645, "h": 92,
        "text": "James 5 (AMP)", "font": "AzoSans-Bold",
    }
    badge_shape = {
        "kind": "shape", "kindIndex": 1, "x": 100, "y": 44, "w": 645, "h": 92,
        "text": "James 5 (AMP)",
    }
    items_by_id = {
        ("text", 0): heading, ("text", 1): number, ("shape", 0): circle,
        ("text", 2): verse, ("text", 3): badge_text, ("shape", 1): badge_shape,
    }
    cls = _cls_for(
        (("text", 0), ("text", 1), ("shape", 0), ("text", 2), ("text", 3), ("shape", 1)),
        (("text", 2),),
    )
    cluster = dsa._heading_cluster(cls, items_by_id)
    assert cluster == dsa.HeadingCluster(("text", 0), ("text", 1), ("shape", 0))


def test_heading_cluster_rejects_text_bearing_circle():
    heading = _heading_item(0, "Faith")
    number = _number_item(1)
    circle = _circle_item(0)
    circle["text"] = "3"
    verse = _verse_item(2)
    items_by_id = {("text", 0): heading, ("text", 1): number, ("shape", 0): circle, ("text", 2): verse}
    cls = _cls_for((("text", 0), ("text", 1), ("shape", 0), ("text", 2)), (("text", 2),))
    assert dsa._heading_cluster(cls, items_by_id) is None


def test_heading_cluster_rejects_digit_without_circle():
    heading = _heading_item(0, "Faith")
    number = _number_item(1)
    verse = _verse_item(2)
    items_by_id = {("text", 0): heading, ("text", 1): number, ("text", 2): verse}
    cls = _cls_for((("text", 0), ("text", 1), ("text", 2)), (("text", 2),))
    assert dsa._heading_cluster(cls, items_by_id) is None


def test_heading_cluster_rejects_numeral_not_overlapping_circle():
    heading = _heading_item(0, "Faith")
    number = _number_item(1)
    number["x"] = 500
    number["y"] = 500
    circle = _circle_item(0)
    verse = _verse_item(2)
    items_by_id = {("text", 0): heading, ("text", 1): number, ("shape", 0): circle, ("text", 2): verse}
    cls = _cls_for((("text", 0), ("text", 1), ("shape", 0), ("text", 2)), (("text", 2),))
    assert dsa._heading_cluster(cls, items_by_id) is None


def test_heading_cluster_rejects_two_point_numbers():
    heading = _heading_item(0, "Faith")
    number0 = _number_item(1)
    number1 = _number_item(3, text="4")
    circle = _circle_item(0)
    verse = _verse_item(2)
    items_by_id = {
        ("text", 0): heading, ("text", 1): number0, ("text", 3): number1,
        ("shape", 0): circle, ("text", 2): verse,
    }
    cls = _cls_for(
        (("text", 0), ("text", 1), ("text", 3), ("shape", 0), ("text", 2)),
        (("text", 2),),
    )
    assert dsa._heading_cluster(cls, items_by_id) is None


def test_heading_cluster_rejects_stray_text_over_textless_shape():
    heading = _heading_item(0, "Faith")
    number = _number_item(1)
    circle = _circle_item(0)
    verse = _verse_item(2)
    stray = {
        "kind": "text", "kindIndex": 3, "x": 100, "y": 44, "w": 645, "h": 92,
        "text": "James 5 (AMP)", "font": "AzoSans-Bold",
    }
    decorative_shape = {"kind": "shape", "kindIndex": 1, "x": 100, "y": 44, "w": 645, "h": 92, "text": ""}
    items_by_id = {
        ("text", 0): heading, ("text", 1): number, ("shape", 0): circle,
        ("text", 2): verse, ("text", 3): stray, ("shape", 1): decorative_shape,
    }
    cls = _cls_for(
        (("text", 0), ("text", 1), ("shape", 0), ("text", 2), ("text", 3), ("shape", 1)),
        (("text", 2),),
    )
    assert dsa._heading_cluster(cls, items_by_id) is None


def test_heading_cluster_rejects_two_badge_like_pairs():
    heading = _heading_item(0, "Faith")
    number = _number_item(1)
    circle = _circle_item(0)
    verse = _verse_item(2)
    badge_text0 = {
        "kind": "text", "kindIndex": 3, "x": 100, "y": 44, "w": 645, "h": 92,
        "text": "James 5 (AMP)", "font": "AzoSans-Bold",
    }
    badge_shape0 = {"kind": "shape", "kindIndex": 1, "x": 100, "y": 44, "w": 645, "h": 92, "text": "James 5 (AMP)"}
    badge_text1 = {
        "kind": "text", "kindIndex": 4, "x": 100, "y": 200, "w": 200, "h": 40,
        "text": "Extra badge", "font": "AzoSans-Bold",
    }
    badge_shape1 = {"kind": "shape", "kindIndex": 2, "x": 100, "y": 200, "w": 200, "h": 40, "text": "Extra badge"}
    items_by_id = {
        ("text", 0): heading, ("text", 1): number, ("shape", 0): circle, ("text", 2): verse,
        ("text", 3): badge_text0, ("shape", 1): badge_shape0,
        ("text", 4): badge_text1, ("shape", 2): badge_shape1,
    }
    cls = _cls_for(
        (
            ("text", 0), ("text", 1), ("shape", 0), ("text", 2),
            ("text", 3), ("shape", 1), ("text", 4), ("shape", 2),
        ),
        (("text", 2),),
    )
    assert dsa._heading_cluster(cls, items_by_id) is None


def test_heading_cluster_rejects_badge_text_mismatch():
    heading = _heading_item(0, "Faith")
    number = _number_item(1)
    circle = _circle_item(0)
    verse = _verse_item(2)
    badge_text = {
        "kind": "text", "kindIndex": 3, "x": 100, "y": 44, "w": 645, "h": 92,
        "text": "James 5 (AMP)", "font": "AzoSans-Bold",
    }
    badge_shape = {"kind": "shape", "kindIndex": 1, "x": 100, "y": 44, "w": 645, "h": 92, "text": "Different"}
    items_by_id = {
        ("text", 0): heading, ("text", 1): number, ("shape", 0): circle,
        ("text", 2): verse, ("text", 3): badge_text, ("shape", 1): badge_shape,
    }
    cls = _cls_for(
        (("text", 0), ("text", 1), ("shape", 0), ("text", 2), ("text", 3), ("shape", 1)),
        (("text", 2),),
    )
    assert dsa._heading_cluster(cls, items_by_id) is None


def test_heading_cluster_rejects_second_numeral_matching_a_shape():
    heading = _heading_item(0, "Faith")
    number0 = _number_item(1)
    circle = _circle_item(0)
    verse = _verse_item(2)
    number1 = {"kind": "text", "kindIndex": 3, "x": 300, "y": 300, "w": 35, "h": 35, "text": "4", "font": "AzoSans-Bold"}
    matching_shape = {"kind": "shape", "kindIndex": 1, "x": 300, "y": 300, "w": 35, "h": 35, "text": "4"}
    items_by_id = {
        ("text", 0): heading, ("text", 1): number0, ("shape", 0): circle, ("text", 2): verse,
        ("text", 3): number1, ("shape", 1): matching_shape,
    }
    cls = _cls_for(
        (("text", 0), ("text", 1), ("shape", 0), ("text", 2), ("text", 3), ("shape", 1)),
        (("text", 2),),
    )
    assert dsa._heading_cluster(cls, items_by_id) is None


def test_heading_cluster_rejects_numeral_centre_at_circle_corner():
    heading = _heading_item(0, "Faith")
    circle = _circle_item(0)
    verse = _verse_item(2)
    # Circle centre (40.5, 40.5), radius 40.5+1.0 tol; place numeral centre at
    # the corner (0, 0) -- distance ~57.3pt, well outside the radial tolerance.
    number = {"kind": "text", "kindIndex": 1, "x": -1, "y": -1, "w": 2, "h": 2, "text": "3", "font": "AzoSans-Bold"}
    items_by_id = {("text", 0): heading, ("text", 1): number, ("shape", 0): circle, ("text", 2): verse}
    cls = _cls_for((("text", 0), ("text", 1), ("shape", 0), ("text", 2)), (("text", 2),))
    assert dsa._heading_cluster(cls, items_by_id) is None


def test_heading_cluster_rejects_numeral_just_outside_radius():
    heading = _heading_item(0, "Faith")
    circle = _circle_item(0)
    verse = _verse_item(2)
    # Circle centre (40.5, 40.5); place numeral centre 41.6pt away (radius + 1.1pt),
    # just past the 41.5pt (radius 40.5 + 1.0pt tolerance) boundary.
    number = {
        "kind": "text", "kindIndex": 1, "x": 40.5 - 0.5, "y": (40.5 + 41.6) - 0.5, "w": 1, "h": 1,
        "text": "3", "font": "AzoSans-Bold",
    }
    items_by_id = {("text", 0): heading, ("text", 1): number, ("shape", 0): circle, ("text", 2): verse}
    cls = _cls_for((("text", 0), ("text", 1), ("shape", 0), ("text", 2)), (("text", 2),))
    assert dsa._heading_cluster(cls, items_by_id) is None


def _badge_and_stack_plan():
    _require_font("AzoSans-Regular")
    _require_font("AzoSans-Bold")
    text_item = _long_text_item(1, (_VERSE_1 + " ") * 3)
    badge = _badge_item(0)
    slide = _slide(13, [text_item, badge])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    slides_by_number = {s["number"]: s for s in payload["slides"]}
    return plan, slides_by_number


def test_refit_second_round_accumulates_correction():
    plan, slides_by_number = _badge_and_stack_plan()
    todo = {(13, "text:1")}
    warnings: list[str] = []
    correction: dict = {}
    last_t: dict = {}
    corr_key = (13, ("text", 1))

    measured1 = {(13, "text:1"): 400.0}
    refits1 = dsa._build_refit_round(
        plan, slides_by_number, todo, measured1, BAND, 24.0, warnings, correction, last_t=last_t,
    )
    size1 = refits1[13][("text", 1)].run_sizes
    corr1 = correction[corr_key]

    rect_h = refits1[13][("text", 1)].rect.h
    measured2 = {(13, "text:1"): rect_h + 5.0}
    refits2 = dsa._build_refit_round(
        plan, slides_by_number, todo, measured2, BAND, 24.0, warnings, correction, last_t=last_t,
    )
    size2 = refits2[13][("text", 1)].run_sizes
    corr2 = correction[corr_key]

    assert size2 <= size1
    assert corr2 > corr1, "round 2 must multiply into round 1's correction, not discard it"


def test_refit_second_round_measured_equals_rect_h_leaves_correction_unchanged():
    plan, slides_by_number = _badge_and_stack_plan()
    todo = {(13, "text:1")}
    warnings: list[str] = []
    correction: dict = {}
    last_t: dict = {}
    corr_key = (13, ("text", 1))

    measured1 = {(13, "text:1"): 400.0}
    refits1 = dsa._build_refit_round(
        plan, slides_by_number, todo, measured1, BAND, 24.0, warnings, correction, last_t=last_t,
    )
    corr1 = correction[corr_key]

    rect_h = refits1[13][("text", 1)].rect.h
    measured2 = {(13, "text:1"): rect_h}
    refits2 = dsa._build_refit_round(
        plan, slides_by_number, todo, measured2, BAND, 24.0, warnings, correction, last_t=last_t,
    )
    corr2 = correction[corr_key]

    assert corr2 == corr1, "measured == last written height must leave the correction unchanged"


def test_build_refit_round_records_stop_reason_when_fit_returns_none_at_floor():
    # r11 GW 17 root cause: a corrected height that only clears at t below the
    # `--min-text-pt` floor must not vanish from `refits` without a trace -- the round
    # skip is now recorded in `stop_reasons` so a caller can log why.
    plan, slides_by_number = _badge_and_stack_plan()
    todo = {(13, "text:1")}
    warnings: list[str] = []
    correction: dict = {}
    stop_reasons: dict[int, str] = {}
    measured = {(13, "text:1"): 5000.0}
    refits = dsa._build_refit_round(
        plan, slides_by_number, todo, measured, BAND, 60.0, warnings, correction,
        last_t={}, stop_reasons=stop_reasons,
    )
    assert refits == {}
    assert 13 in stop_reasons
    assert "fit_text_stack found no t" in stop_reasons[13]


def test_build_refit_round_clears_stop_reason_once_a_slide_fits():
    # A slide that failed a prior round but fits this one must not leave a stale reason
    # behind for the caller to misreport.
    plan, slides_by_number = _badge_and_stack_plan()
    todo = {(13, "text:1")}
    stop_reasons: dict[int, str] = {13: "stale reason from an earlier round"}
    refits = dsa._build_refit_round(
        plan, slides_by_number, todo, {(13, "text:1"): 400.0}, BAND, 24.0, [], {},
        last_t={}, stop_reasons=stop_reasons,
    )
    assert 13 in refits
    assert 13 not in stop_reasons


def test_refit_round_re_stacks_badge_position_only():
    plan, slides_by_number = _badge_and_stack_plan()
    todo = {(13, "text:1")}
    warnings: list[str] = []
    original_badge_rect = plan.fits[13][("text", 0)]

    refits = dsa._build_refit_round(
        plan, slides_by_number, todo, {(13, "text:1"): 320.0}, BAND, 24.0, warnings, {}, last_t={},
    )
    badge_refit = refits[13][("text", 0)]
    stack_top = refits[13][("text", 1)].rect.y
    assert badge_refit.run_sizes is None
    assert badge_refit.rect.y + badge_refit.rect.h == pytest.approx(stack_top - dsa._TEXT_STACK_GAP, abs=0.5)
    assert badge_refit.rect.x == original_badge_rect.x
    assert badge_refit.rect.w == original_badge_rect.w
    assert badge_refit.rect.h == original_badge_rect.h


def test_refit_script_addresses_staged_index_after_a_delete_below_the_stack():
    plan, slides_by_number = _badge_and_stack_plan()
    plan.deletes[13] = (("text", 2),)
    refits = {(13, 0): {("text", 1): TextRefit(Rect(43.0, 700.0, 1849.0, 250.0), run_sizes=50.0)}}
    script = dsa.build_refit_script(
        plan, refits, ordinals=plan.ordinals, scratch_path=Path("/tmp/scratch.key"),
        staging_path=Path("/tmp/staged.key"),
    )
    assert "text item 2 of slide 1" in script


def test_refit_shrink_path_writes_measured_fit_size_above_floor(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions = _stacked_assemble_fixture(tmp_path)
    pass1_stderr = "OBED\t13\tdone"
    still_over_stderr = "OBED\t13\tdone"
    shrunk_fits_stderr = "OBED\t13\tdone"
    live_batch_cls, calls = _make_seq_live_batch(
        [pass1_stderr, still_over_stderr, still_over_stderr, shrunk_fits_stderr]
    )
    _patch_common_with_batch(monkeypatch, payload, classes, live_batch_cls)
    monkeypatch.setattr(
        dsa, "offline_text_rects",
        _offline_reader_seq(
            [_text_rects(500.0), _text_rects(500.0), _text_rects(500.0), _text_rects(20.0)]
        ),
    )
    result = assemble_dsk_deck(
        fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve", text_fit="shrink",
    )
    shrink_script = calls[-1].read_text()
    written = float(shrink_script.split("set size of object text of theObj to ")[1].split("\n")[0])
    assert written > dsa.DEFAULT_MIN_TEXT_PT
    assert any("shrunk to" in w and "floor" not in w for w in result.warnings)


def test_refit_shrink_path_clamps_to_floor_when_measured_fit_is_below_it(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions = _stacked_assemble_fixture(tmp_path)
    pass1_stderr = "OBED\t13\tdone"
    still_over_stderr = "OBED\t13\tdone"
    huge_measured_stderr = "OBED\t13\tdone"
    live_batch_cls, calls = _make_seq_live_batch(
        [pass1_stderr, still_over_stderr, still_over_stderr, huge_measured_stderr]
    )
    _patch_common_with_batch(monkeypatch, payload, classes, live_batch_cls)
    monkeypatch.setattr(
        dsa, "offline_text_rects",
        _offline_reader_seq(
            [_text_rects(500.0), _text_rects(5000.0), _text_rects(5000.0), _text_rects(20.0)]
        ),
    )
    result = assemble_dsk_deck(
        fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve", text_fit="shrink",
    )
    shrink_script = calls[-1].read_text()
    written = float(shrink_script.split("set size of object text of theObj to ")[1].split("\n")[0])
    assert written == pytest.approx(dsa.DEFAULT_MIN_TEXT_PT, abs=0.5)
    assert any("shrunk to" in w and "floor" in w for w in result.warnings)


# --------------------------------------------------------------------------
# assemble_dsk_deck -- fake LiveBatch and fake iwa functions, no real Keynote/IWA IO.
# --------------------------------------------------------------------------
import obed_edom.iwa_builds as iwa_builds  # noqa: E402
import obed_edom.iwa_movies as iwa_movies  # noqa: E402
import obed_edom.iwa_write as iwa_write  # noqa: E402


def _make_fake_live_batch(stderr_text, returncode=0):
    class _FakeLiveBatch:
        def __init__(self, deck, out_dir, *, rss_limit_bytes=0, log=print):
            self.deck = Path(deck)
            self.out_dir = Path(out_dir)
            self.work = self.out_dir / "fake-work"
            self.scratch = self.work / self.deck.name

        def __enter__(self):
            self.work.mkdir(parents=True, exist_ok=True)
            self.scratch.mkdir(parents=True, exist_ok=True)
            (self.scratch / "marker").write_bytes(b"scratch")
            return self

        def __exit__(self, exc_type, exc, _tb):
            return False

        def run(self, script_path, *, on_progress=None, retry_on_1712=True):
            return subprocess.CompletedProcess([], returncode, "", stderr_text)

    return _FakeLiveBatch


def _fake_copy_keynote(src, dest):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"fake-assembled-deck")
    return dest


def _assemble_fixture(tmp_path):
    fw_deck = tmp_path / "source.key"
    fw_deck.mkdir()
    (fw_deck / "stub").write_bytes(b"x" * 32)
    out_path = tmp_path / "out" / "assembled.key"

    text_item = _text_item(0, x=1920, y=0, w=3698.0, h=494.4, runs=[{"size": 40.0}])
    movie_item = _movie_item(0, x=1920, y=-763, w=3840, h=2160)
    slide13 = _slide(13, [text_item])
    slide32 = _slide(32, [movie_item])
    payload = _payload([slide13, slide32])
    classes = [_classify(slide13), _classify(slide32)]
    decisions = {13: SlideDecision(13, "in_deck"), 32: SlideDecision(32, "in_deck")}
    clips = {32: Path("/tmp/clip.mov")}
    return fw_deck, out_path, payload, classes, decisions, clips


def _dissolve_transition(duration=0.5):
    return {"attributes": {"databaseEffect": "apple:dissolve", "databaseDuration": duration}}


def _default_fake_deck_builds(path, *, deck=None):
    # Slide 32 / ordinal 2 is the clip slide in `_assemble_fixture`; its output
    # transition must read back as the expected dissolve so `_verify_builds`'s
    # independent clip-transition read-back (Codex r1 finding 10) doesn't spuriously
    # refuse tests that don't care about that check.
    return {
        13: {"slideId": "s13", "builds": [], "transition": None},
        32: {"slideId": "s32", "builds": [], "transition": None},
        1: {"slideId": "o1", "builds": [], "transition": None},
        2: {"slideId": "o2", "builds": [], "transition": _dissolve_transition(0.5)},
    }


def _patch_common(monkeypatch, payload, classes, stderr_text, returncode=0):
    monkeypatch.setattr(
        dsa, "load_assembly_inputs",
        lambda deck, include_side=frozenset(), text_slide_words=10, no_dedupe=False,
        no_drop_panel_backdrop=False: (payload, classes, {}),
    )
    monkeypatch.setattr(dsa, "LiveBatch", _make_fake_live_batch(stderr_text, returncode))
    monkeypatch.setattr(dsa, "copy_keynote", _fake_copy_keynote)
    monkeypatch.setattr(dsa, "_load_deck", lambda path: ({}, {}, {}))
    monkeypatch.setattr(dsa, "deck_builds", _default_fake_deck_builds)
    monkeypatch.setattr(dsa, "_restore_clip_zorder", lambda out_path, plan, warnings: {})
    monkeypatch.setattr(dsa, "_restore_clip_timing", lambda staging_path, plan, log: {})
    monkeypatch.setattr(iwa_write, "card_styles", lambda objects, id_to_file: [])
    monkeypatch.setattr(
        iwa_write,
        "match_card_stroke_styles",
        lambda out_styles, src_styles, *, canvas_scale, min_refs: {
            "widths": {}, "chosen": [], "notes": [], "out_selected": []
        },
    )
    monkeypatch.setattr(iwa_write, "patch_stroke_widths", lambda deck, widths: {"refused": False})
    monkeypatch.setattr(
        iwa_write, "patch_media_stroke", lambda deck, strokes: {"refused": False, "patched": [], "created": []}
    )
    monkeypatch.setattr(iwa_builds, "deck_builds", _default_fake_deck_builds)
    monkeypatch.setattr(
        iwa_builds,
        "verify_builds",
        lambda src_by_number, out_by_number, slides=None: {
            "surplus": [], "missing": [], "transitions": [], "order": []
        },
    )


def test_assemble_parses_movie_props_ordinal_rekey_and_size(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    stderr_text = "\n".join(
        [
            "OBED\t32\trepetitionMethod\tloop",
            "OBED\t32\tmovieVolume\t1.0",
            "OBED\t13\t2026-01-01 00:00:00",
            "OBED\t32\t2026-01-01 00:00:00",
        ]
    )
    _patch_common(monkeypatch, payload, classes, stderr_text)

    captured: dict = {}

    def fake_deck_builds(path, *, deck=None):
        if Path(path) == fw_deck:
            return {
                13: {"slideId": "s13", "builds": [], "transition": None},
                32: {"slideId": "s32", "builds": [], "transition": None},
            }
        return {
            1: {"slideId": "o1", "builds": [], "transition": None},
            2: {"slideId": "o2", "builds": [], "transition": _dissolve_transition(0.5)},
        }

    def fake_verify_builds(src_by_number, out_by_number, slides=None):
        captured["src"] = src_by_number
        captured["out"] = out_by_number
        return {"surplus": [], "missing": [], "transitions": [], "order": []}

    monkeypatch.setattr(iwa_builds, "deck_builds", fake_deck_builds)
    monkeypatch.setattr(iwa_builds, "verify_builds", fake_verify_builds)

    result = assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")

    assert isinstance(result, AssembleResult)
    assert result.movie_props[32]["repetitionMethod"] == "loop"
    assert result.movie_props[32]["movieVolume"] == "1.0"
    assert result.slides_kept == (13, 32)
    assert result.ordinals == {13: 1, 32: 2}
    assert captured["out"] == {
        13: {"slideId": "o1", "builds": [], "transition": None},
        32: {"slideId": "o2", "builds": [], "transition": _dissolve_transition(0.5)},
    }
    assert captured["src"][13]["slideId"] == "s13"
    assert result.clips_inserted == {32: {("movie", 0): Path("/tmp/clip.mov")}}
    assert result.size_bytes > 0
    assert result.source_size_bytes > 0
    assert out_path.exists()


def test_assemble_parses_overflow_lines_into_result_and_warnings(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    stderr_text = "\n".join([
        "OBED\t13\tOVERFLOW\ttext:2\t269.3",
        "OBED\t13\tdone",
        "OBED\t32\tdone",
    ])
    _patch_common(monkeypatch, payload, classes, stderr_text)
    result = assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")
    assert result.overflows == ({"slide": 13, "item": "text:2", "height": 269.3},)
    assert any("slide 13: text text:2 overflow" in w for w in result.warnings)
    assert 13 not in result.movie_props or "OVERFLOW" not in result.movie_props[13]


# --------------------------------------------------------------------------
# Design-B refit loop (D2 step 4).
# --------------------------------------------------------------------------
def _stacked_assemble_fixture(tmp_path):
    fw_deck = tmp_path / "source.key"
    fw_deck.mkdir()
    (fw_deck / "stub").write_bytes(b"x" * 32)
    out_path = tmp_path / "out" / "assembled.key"
    text_item = {
        "kind": "text", "kindIndex": 0, "x": 1920, "y": 0, "w": 3698.0, "h": 300.0,
        "text": " ".join(["word"] * 30), "font": "Helvetica", "size": 40.0,
    }
    slide = _slide(13, [text_item])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {13: SlideDecision(13, "in_deck")}
    return fw_deck, out_path, payload, classes, decisions


def _make_seq_live_batch(stderr_by_call):
    calls: list[Path] = []

    class _SeqFakeLiveBatch:
        def __init__(self, deck, out_dir, *, rss_limit_bytes=0, log=print):
            self.deck = Path(deck)
            self.out_dir = Path(out_dir)
            self.work = self.out_dir / "fake-work"
            self.scratch = self.work / self.deck.name

        def __enter__(self):
            self.work.mkdir(parents=True, exist_ok=True)
            self.scratch.mkdir(parents=True, exist_ok=True)
            (self.scratch / "marker").write_bytes(b"scratch")
            return self

        def __exit__(self, exc_type, exc, _tb):
            return False

        def run(self, script_path, *, on_progress=None, retry_on_1712=True):
            idx = len(calls)
            calls.append(script_path)
            stderr = stderr_by_call[min(idx, len(stderr_by_call) - 1)]
            return subprocess.CompletedProcess([], 0, "", stderr)

    return _SeqFakeLiveBatch, calls


def _patch_common_with_batch(monkeypatch, payload, classes, live_batch_cls):
    monkeypatch.setattr(
        dsa, "load_assembly_inputs",
        lambda deck, include_side=frozenset(), text_slide_words=10, no_dedupe=False,
        no_drop_panel_backdrop=False: (payload, classes, {}),
    )
    monkeypatch.setattr(dsa, "LiveBatch", live_batch_cls)
    monkeypatch.setattr(dsa, "copy_keynote", _fake_copy_keynote)
    monkeypatch.setattr(dsa, "_load_deck", lambda path: ({}, {}, {}))
    monkeypatch.setattr(dsa, "deck_builds", lambda path, *, deck=None: {})
    monkeypatch.setattr(dsa, "_restore_clip_zorder", lambda out_path, plan, warnings: {})
    monkeypatch.setattr(dsa, "_restore_clip_timing", lambda staging_path, plan, log: {})
    monkeypatch.setattr(iwa_write, "card_styles", lambda objects, id_to_file: [])
    monkeypatch.setattr(
        iwa_write, "match_card_stroke_styles",
        lambda out_styles, src_styles, *, canvas_scale, min_refs: {
            "widths": {}, "chosen": [], "notes": [], "out_selected": []
        },
    )
    monkeypatch.setattr(iwa_write, "patch_stroke_widths", lambda deck, widths: {"refused": False})
    monkeypatch.setattr(
        iwa_write, "patch_media_stroke", lambda deck, strokes: {"refused": False, "patched": [], "created": []}
    )
    monkeypatch.setattr(iwa_builds, "deck_builds", lambda path, *, deck=None: {})
    monkeypatch.setattr(
        iwa_builds, "verify_builds",
        lambda src_by_number, out_by_number, slides=None: {
            "surplus": [], "missing": [], "transitions": [], "order": []
        },
    )


def _require_helvetica():
    if resolve_font_path("Helvetica") is None:
        pytest.skip("font not present on this machine: Helvetica")


def _offline_reader_seq(entries):
    """Fakes ``dsa.offline_text_rects``: returns ``entries[i]`` for the i-th call (last
    entry repeats). Each entry is a ``(rects_by_ordinal, soft)`` pair."""
    state = {"i": 0}

    def fake(key_path, *, deck=None):
        i = min(state["i"], len(entries) - 1)
        state["i"] += 1
        return entries[i]

    return fake


def _text_rects(height, *, ordinal=1, kind_index=0, y=704.0, x=43.0, w=1849.0):
    """One offline-reader entry: a single text item's rect on ``ordinal``, top-anchored
    in ``BAND`` by default so a small-enough ``height`` also clears the band check."""
    return ({ordinal: {("text", kind_index): (x, y, w, height)}}, set())


_MISSING_RECTS = ({}, set())


def test_refit_loop_triggers_without_any_live_overflow_line(tmp_path, monkeypatch):
    """The trigger is plan-derived (every stacked box), not the live OVERFLOW line --
    it must fire even when pass 1's live read never reports one (D2b gate finding)."""
    _require_helvetica()
    fw_deck, out_path, payload, classes, decisions = _stacked_assemble_fixture(tmp_path)
    pass1_stderr = "OBED\t13\tdone"
    refit_stderr = "OBED\t13\tdone"
    live_batch_cls, calls = _make_seq_live_batch([pass1_stderr, refit_stderr])
    _patch_common_with_batch(monkeypatch, payload, classes, live_batch_cls)
    monkeypatch.setattr(dsa, "offline_text_rects", _offline_reader_seq([_text_rects(269.0), _text_rects(270.0)]))
    result = assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve")
    assert len(calls) == 2
    assert result.overflows == ()


def test_refit_loop_converges_in_two_rounds(tmp_path, monkeypatch):
    # Genuinely two rounds: pass 1 over budget, round 1 still over budget, round 2
    # fits -- distinct from the single-round trigger test above.
    _require_helvetica()
    fw_deck, out_path, payload, classes, decisions = _stacked_assemble_fixture(tmp_path)
    pass1_stderr = "OBED\t13\tdone"
    round1_stderr = "OBED\t13\tdone"
    round2_stderr = "OBED\t13\tdone"
    live_batch_cls, calls = _make_seq_live_batch([pass1_stderr, round1_stderr, round2_stderr])
    _patch_common_with_batch(monkeypatch, payload, classes, live_batch_cls)
    monkeypatch.setattr(
        dsa, "offline_text_rects",
        _offline_reader_seq([_text_rects(500.0), _text_rects(400.0), _text_rects(270.0)]),
    )
    result = assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve")
    assert len(calls) == 3
    assert result.overflows == ()


def test_refit_loop_treats_band_breach_as_over_budget(tmp_path, monkeypatch):
    """A box whose measured height fits its own rect but whose offline ``y``/``bottom``
    falls outside the slide's stack band must still be treated as over budget."""
    _require_helvetica()
    fw_deck, out_path, payload, classes, decisions = _stacked_assemble_fixture(tmp_path)
    pass1_stderr = "OBED\t13\tdone"
    refit_stderr = "OBED\t13\tdone"
    live_batch_cls, calls = _make_seq_live_batch([pass1_stderr, refit_stderr])
    _patch_common_with_batch(monkeypatch, payload, classes, live_batch_cls)
    breach = _text_rects(100.0, y=1000.0)  # bottom 1100 > BAND.bottom (1054) + 1
    monkeypatch.setattr(dsa, "offline_text_rects", _offline_reader_seq([breach, _text_rects(20.0)]))
    result = assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve")
    assert len(calls) == 2
    assert result.overflows == ()


def test_refit_still_over_budget_eligible_keys_catches_shrink_displaced_sibling():
    # Opus D2b review 1 finding 3: the post-shrink recheck must use the full eligible
    # set, not just the keys that were already failing -- a sibling the shrink pass
    # pushed out of its stack band would otherwise be published unchecked.
    plan = AssemblyPlan(
        kept=(13,), ordinals={13: 1}, deletes={}, clips={}, text_sizes={}, autosize={},
        warnings=(),
        fits={13: {("text", 1): Rect(43.0, 704.0, 1849.0, 260.0), ("text", 2): Rect(43.0, 964.0, 1849.0, 80.0)}},
        stack_bands={13: BAND},
    )
    measured = {(13, "text:1"): 260.0, (13, "text:2"): 78.0}
    bands = {(13, "text:1"): (704.0, 964.0), (13, "text:2"): (1100.0, 1178.0)}
    todo = {(13, "text:1")}
    eligible_keys = {(13, "text:1"), (13, "text:2")}

    over_via_todo = dsa._refit_still_over_budget(plan, measured, todo, bands=bands)
    assert over_via_todo == set(), "text:1 alone looks resolved -- the stale check would miss the sibling"

    over_via_eligible = dsa._refit_still_over_budget(plan, measured, eligible_keys, bands=bands)
    assert (13, "text:2") in over_via_eligible, "text:2 was pushed out of band and must still be caught"


def test_log_offline_measures_split_part_reads_its_own_split_fits():
    # r13 attempt 6, Part A: for a split slide, the long box's rect lives in
    # `plan.splits[number][part].fits`, not `plan.fits[number]` (`plan.fits[number]`
    # holds only the short items' part-0 row rects). `_log_offline_measures` used to
    # look the rect up in `plan.fits` unconditionally, so a split part's measured height
    # was reported as "missing a rect or height" even though it was correctly measured
    # and within budget -- a cosmetic false positive that could mask a real refusal.
    plan = AssemblyPlan(
        kept=(28,), ordinals={28: 8}, deletes={}, clips={}, text_sizes={}, autosize={},
        warnings=(), fits={28: {}},
        splits={28: (
            SplitPart(fits={("text", 1): Rect(54.0, 100.0, 1799.0, 200.0)}, deletes=(), text_sizes={}),
            SplitPart(fits={("text", 1): Rect(54.0, 100.0, 1799.0, 200.0)}, deletes=(), text_sizes={}),
        )},
    )
    measured = {(28, "text:1:8"): 190.0, (28, "text:1:9"): 195.0}
    eligible_keys = {(28, "text:1:8"), (28, "text:1:9")}
    logged = []
    dsa._log_offline_measures(plan, measured, eligible_keys, logged.append)
    assert not any("missing" in line for line in logged)


def test_refit_loop_refuses_when_still_overflowing(tmp_path, monkeypatch):
    _require_helvetica()
    fw_deck, out_path, payload, classes, decisions = _stacked_assemble_fixture(tmp_path)
    pass1_stderr = "OBED\t13\tdone"
    still_over_stderr = "OBED\t13\tdone"
    live_batch_cls, calls = _make_seq_live_batch([pass1_stderr, still_over_stderr, still_over_stderr])
    _patch_common_with_batch(monkeypatch, payload, classes, live_batch_cls)
    monkeypatch.setattr(
        dsa, "offline_text_rects",
        _offline_reader_seq([_text_rects(500.0), _text_rects(500.0), _text_rects(500.0)]),
    )
    with pytest.raises(AssemblyRefusal, match="still overflows after refit"):
        assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve")
    assert len(calls) == 1 + dsa._MAX_REFITS


def test_refit_loop_shrinks(tmp_path, monkeypatch):
    _require_helvetica()
    fw_deck, out_path, payload, classes, decisions = _stacked_assemble_fixture(tmp_path)
    pass1_stderr = "OBED\t13\tdone"
    still_over_stderr = "OBED\t13\tdone"
    shrunk_fits_stderr = "OBED\t13\tdone"
    live_batch_cls, calls = _make_seq_live_batch(
        [pass1_stderr, still_over_stderr, still_over_stderr, shrunk_fits_stderr]
    )
    _patch_common_with_batch(monkeypatch, payload, classes, live_batch_cls)
    monkeypatch.setattr(
        dsa, "offline_text_rects",
        _offline_reader_seq(
            [_text_rects(500.0), _text_rects(500.0), _text_rects(500.0), _text_rects(20.0)]
        ),
    )
    result = assemble_dsk_deck(
        fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve", text_fit="shrink",
    )
    assert result.overflows == ()
    assert any("shrunk to" in w and "pt after refit" in w for w in result.warnings)
    assert len(calls) == 1 + dsa._MAX_REFITS + 1


def test_offline_measure_soft_geometry_item_is_not_a_reason_to_skip(tmp_path, monkeypatch):
    """Gate outcome overrides the original plan step 2: soft_geometry membership is
    expected for every autosize-stacked box and must not gate or skip the read."""
    _require_helvetica()
    fw_deck, out_path, payload, classes, decisions = _stacked_assemble_fixture(tmp_path)
    pass1_stderr = "OBED\t13\tdone"
    refit_stderr = "OBED\t13\tdone"
    live_batch_cls, calls = _make_seq_live_batch([pass1_stderr, refit_stderr])
    _patch_common_with_batch(monkeypatch, payload, classes, live_batch_cls)
    soft_flagged = ({1: {("text", 0): (43.0, 704.0, 1849.0, 269.0)}}, {(1, "text", 0)})
    monkeypatch.setattr(
        dsa, "offline_text_rects", _offline_reader_seq([soft_flagged, _text_rects(270.0)]),
    )
    result = assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve")
    assert len(calls) == 2
    assert result.overflows == ()


def test_shrink_fallback_never_writes_above_pass1_size(tmp_path, monkeypatch):
    _require_helvetica()
    fw_deck = tmp_path / "source.key"
    fw_deck.mkdir()
    (fw_deck / "stub").write_bytes(b"x" * 32)
    out_path = tmp_path / "out" / "assembled.key"
    text_item = {
        "kind": "text", "kindIndex": 0, "x": 1920, "y": 0, "w": 3698.0, "h": 300.0,
        "text": " ".join(["word"] * 120), "font": "Helvetica", "size": 40.0,
    }
    slide = _slide(13, [text_item])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    pass1_size = plan.stack_t[13] * 40.0
    assert plan.stack_t[13] < 1.0, "fixture must exercise pass 1 shrinking for this test to mean anything"

    pass1_stderr = "OBED\t13\tdone"
    still_over_stderr = "OBED\t13\tdone"
    shrink_stderr = "OBED\t13\tdone"
    live_batch_cls, calls = _make_seq_live_batch(
        [pass1_stderr, still_over_stderr, still_over_stderr, shrink_stderr]
    )
    _patch_common_with_batch(monkeypatch, payload, classes, live_batch_cls)
    monkeypatch.setattr(
        dsa, "offline_text_rects",
        _offline_reader_seq(
            [_text_rects(500.0), _text_rects(500.0), _text_rects(500.0), _text_rects(20.0)]
        ),
    )
    result = assemble_dsk_deck(
        fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve", text_fit="shrink",
    )
    assert len(calls) == 1 + dsa._MAX_REFITS + 1
    shrink_warnings = [w for w in result.warnings if "shrunk to" in w or "already at the floor" in w]
    assert shrink_warnings
    marker = "shrunk to " if "shrunk to" in shrink_warnings[0] else "left at "
    written = float(shrink_warnings[0].split(marker)[1].split("pt")[0].split("-")[0])
    assert written <= pass1_size + 0.05, "shrink fallback must never write larger than pass 1's own size"


def test_shrink_fallback_never_writes_above_pass1_size_mixed_run(tmp_path, monkeypatch):
    _require_helvetica()
    fw_deck = tmp_path / "source.key"
    fw_deck.mkdir()
    (fw_deck / "stub").write_bytes(b"x" * 32)
    out_path = tmp_path / "out" / "assembled.key"
    text = " ".join(["word"] * 170)
    split_at = len(text) // 2
    runs = [
        {"text": text[:split_at], "size": 40.0},
        {"text": text[split_at:], "size": 30.0},
    ]
    text_item = {
        "kind": "text", "kindIndex": 0, "x": 1920, "y": 0, "w": 3698.0, "h": 300.0,
        "text": text, "font": "Helvetica", "size": 40.0, "runs": runs,
    }
    slide = _slide(13, [text_item])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    t_prev = plan.stack_t[13]
    assert t_prev < 1.0, "fixture must exercise pass 1 shrinking for this test to mean anything"
    pass1_lo, pass1_hi = 30.0 * t_prev, 40.0 * t_prev

    pass1_stderr = "OBED\t13\tdone"
    shrink_stderr = "OBED\t13\tdone"
    live_batch_cls, calls = _make_seq_live_batch([pass1_stderr, shrink_stderr])
    _patch_common_with_batch(monkeypatch, payload, classes, live_batch_cls)
    monkeypatch.setattr(
        dsa, "offline_text_rects", _offline_reader_seq([_text_rects(500.0), _text_rects(20.0)]),
    )
    result = assemble_dsk_deck(
        fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve", text_fit="shrink",
        min_text_pt=24.0,
    )
    assert len(calls) == 2, "the per-run floor must refuse the refit round outright, going straight to shrink"
    shrink_warnings = [w for w in result.warnings if "shrunk to" in w or "already at the floor" in w]
    assert shrink_warnings
    size_desc = shrink_warnings[0].split("to ")[1].split(" ")[0].split("pt")[0]
    lo_s, _sep, hi_s = size_desc.partition("-")
    lo = float(lo_s)
    hi = float(hi_s) if hi_s else lo
    assert lo <= pass1_lo + 0.05, "shrink fallback must never write a run larger than pass 1's own size"
    assert hi <= pass1_hi + 0.05, "shrink fallback must never write a run larger than pass 1's own size"


def test_shrink_fallback_recheck_catches_sibling_slide_out_of_band(tmp_path, monkeypatch):
    # Opus D2b review 2 nit 2: the post-shrink recheck must use eligible_keys, not just
    # todo -- a sibling slide the shrink pass left displaced out of band must still be
    # caught even though only the over-budget slide was rewritten.
    _require_helvetica()
    fw_deck = tmp_path / "source.key"
    fw_deck.mkdir()
    (fw_deck / "stub").write_bytes(b"x" * 32)
    out_path = tmp_path / "out" / "assembled.key"
    long_text = " ".join(["word"] * 120)
    item13 = {
        "kind": "text", "kindIndex": 0, "x": 1920, "y": 0, "w": 3698.0, "h": 300.0,
        "text": long_text, "font": "Helvetica", "size": 40.0,
    }
    item14 = {
        "kind": "text", "kindIndex": 0, "x": 1920, "y": 0, "w": 3698.0, "h": 300.0,
        "text": long_text, "font": "Helvetica", "size": 40.0,
    }
    slide13 = _slide(13, [item13])
    slide14 = _slide(14, [item14])
    payload = _payload([slide13, slide14])
    classes = [_classify(slide13), _classify(slide14)]
    decisions = {13: SlideDecision(13, "in_deck"), 14: SlideDecision(14, "in_deck")}

    pass1_stderr = "OBED\t13\tdone"
    round_stderr = "OBED\t13\tdone"
    shrink_stderr = "OBED\t13\tdone"
    live_batch_cls, calls = _make_seq_live_batch(
        [pass1_stderr, round_stderr, round_stderr, shrink_stderr]
    )
    _patch_common_with_batch(monkeypatch, payload, classes, live_batch_cls)

    def entry(h13, y13, h14, y14):
        return (
            {1: {("text", 0): (43.0, y13, 1849.0, h13)}, 2: {("text", 0): (43.0, y14, 1849.0, h14)}},
            set(),
        )

    monkeypatch.setattr(
        dsa, "offline_text_rects",
        _offline_reader_seq([
            entry(500.0, 704.0, 20.0, 704.0),  # initial: slide 13 over budget, slide 14 fine
            entry(500.0, 704.0, 20.0, 704.0),  # round 1: still over
            entry(500.0, 704.0, 20.0, 704.0),  # round 2: still over -> refit exhausted
            entry(20.0, 704.0, 20.0, 1200.0),  # post-shrink: slide 13 fixed, slide 14 out of band
        ]),
    )
    with pytest.raises(AssemblyRefusal, match="slide 14: text text:0 still overflows after refit and shrink"):
        assemble_dsk_deck(
            fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve", text_fit="shrink",
        )
    assert len(calls) == 1 + dsa._MAX_REFITS + 1


def test_shrink_fallback_all_runs_below_floor_leaves_size_unchanged(tmp_path, monkeypatch):
    # Opus D2b review 1 finding 1: a box whose source size is already below min_text_pt
    # must not be shrunk further by the fallback -- t_floor = 1.0 clamps t to t_prev
    # (pass 1's own size), and the warning must say "already at the floor".
    _require_helvetica()
    fw_deck = tmp_path / "source.key"
    fw_deck.mkdir()
    (fw_deck / "stub").write_bytes(b"x" * 32)
    out_path = tmp_path / "out" / "assembled.key"
    text_item = {
        "kind": "text", "kindIndex": 0, "x": 1920, "y": 0, "w": 3698.0, "h": 300.0,
        "text": " ".join(["word"] * 30), "font": "Helvetica", "size": 20.0,
    }
    slide = _slide(13, [text_item])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {13: SlideDecision(13, "in_deck")}
    small_band = Band(1054.0, 60.0, 43.0, 1892.0, 4)
    plan = plan_assembly(payload, classes, decisions=decisions, band=small_band, clips={})
    t_prev = plan.stack_t[13]
    assert t_prev == 1.0, "a box already below min_text_pt must fit at t=1.0 (never shrunk by the plan)"
    pass1_size = t_prev * 20.0

    pass1_stderr = "OBED\t13\tdone"
    shrink_stderr = "OBED\t13\tdone"
    live_batch_cls, calls = _make_seq_live_batch([pass1_stderr, shrink_stderr])
    _patch_common_with_batch(monkeypatch, payload, classes, live_batch_cls)
    fitted_y = plan.fits[13][("text", 0)].y
    monkeypatch.setattr(
        dsa, "offline_text_rects",
        _offline_reader_seq([_text_rects(500.0, y=fitted_y), _text_rects(20.0, y=fitted_y)]),
    )
    result = assemble_dsk_deck(
        fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve", text_fit="shrink",
        min_text_pt=24.0, band=small_band,
    )
    assert len(calls) == 2, "the floor must refuse the refit round outright, going straight to shrink"
    floor_warnings = [w for w in result.warnings if "already at the floor" in w]
    assert floor_warnings, result.warnings
    assert not any("shrunk to" in w for w in result.warnings)
    written = float(floor_warnings[0].split("left at ")[1].split("pt")[0])
    assert written == pytest.approx(pass1_size, abs=0.05)


def test_refit_round_dropped_measure_refuses_immediately(tmp_path, monkeypatch):
    # Opus D2b review 1 finding 2: an offline read that stops covering an eligible key
    # mid-loop (here: a fully missing read after round 1) must refuse immediately, not
    # cascade into a wasted extra live round.
    _require_helvetica()
    fw_deck, out_path, payload, classes, decisions = _stacked_assemble_fixture(tmp_path)
    pass1_stderr = "OBED\t13\tdone"
    dropped_measure_stderr = "OBED\t13\tdone"
    live_batch_cls, calls = _make_seq_live_batch([pass1_stderr, dropped_measure_stderr])
    _patch_common_with_batch(monkeypatch, payload, classes, live_batch_cls)
    monkeypatch.setattr(
        dsa, "offline_text_rects",
        _offline_reader_seq([_text_rects(500.0), _MISSING_RECTS, _text_rects(20.0)]),
    )
    with pytest.raises(AssemblyRefusal, match="offline measure missing"):
        assemble_dsk_deck(
            fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve", text_fit="shrink",
        )
    assert len(calls) == 2, "no live pass beyond the one whose offline read went missing"


def test_refit_loop_refuses_immediately_on_unlogged_hide(tmp_path, monkeypatch):
    # Opus D2b review 1 finding 2: an offline read whose per-ordinal text count doesn't
    # match the staged plan (here: an extra staged text item Keynote never logged as
    # HIDDEN) must refuse right away, naming the count mismatch, burning no live passes.
    _require_helvetica()
    fw_deck, out_path, payload, classes, decisions = _stacked_assemble_fixture(tmp_path)
    pass1_stderr = "OBED\t13\tdone"
    live_batch_cls, calls = _make_seq_live_batch([pass1_stderr])
    _patch_common_with_batch(monkeypatch, payload, classes, live_batch_cls)
    unlogged_hide_rects = (
        {1: {("text", 0): (43.0, 704.0, 1849.0, 260.0), ("text", 1): (43.0, 900.0, 1849.0, 20.0)}},
        set(),
    )
    monkeypatch.setattr(dsa, "offline_text_rects", _offline_reader_seq([unlogged_hide_rects]))
    with pytest.raises(AssemblyRefusal, match=r"staged text count 1 != offline text count 2"):
        assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve")
    assert len(calls) == 1


def test_assembly_script_emits_no_measure2_lines():
    """MEASURE2 (the end-of-slide-loop re-read) and its poll are gone (D2b step 4) --
    the offline naturalSize read of the saved deck is the sole refit authority now."""
    plan, _slides_by_number = _badge_and_stack_plan()
    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"),
        layout_policy="preserve",
    )
    assert "MEASURE2" not in script
    assert "set prevH to -1" not in script


def test_refit_script_staged_index_retains_hidden_item_below_stack():
    plan, slides_by_number = _badge_and_stack_plan()
    plan.fits[13][("text", 2)] = plan.fits[13][("text", 0)]
    plan.deletes[13] = (("text", 0),)
    refits = {(13, 0): {("text", 2): TextRefit(Rect(43.0, 700.0, 1849.0, 250.0), run_sizes=50.0)}}

    script_without_hidden = dsa.build_refit_script(
        plan, refits, ordinals=plan.ordinals, scratch_path=Path("/tmp/scratch.key"),
        staging_path=Path("/tmp/staged.key"),
    )
    assert "text item 2 of slide 1" in script_without_hidden

    script_with_hidden = dsa.build_refit_script(
        plan, refits, ordinals=plan.ordinals, scratch_path=Path("/tmp/scratch.key"),
        staging_path=Path("/tmp/staged.key"), hidden={13: frozenset({("text", 0)})},
    )
    assert "text item 3 of slide 1" in script_with_hidden


def test_hidden_marker_appears_in_warnings(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions = _stacked_assemble_fixture(tmp_path)
    pass1_stderr = "\n".join([
        "HIDDEN\t13\tshape 2 of slide 13\ttitle",
        "OBED\t13\tdone",
    ])
    live_batch_cls, calls = _make_seq_live_batch([pass1_stderr])
    _patch_common_with_batch(monkeypatch, payload, classes, live_batch_cls)
    monkeypatch.setattr(dsa, "offline_text_rects", _offline_reader_seq([_text_rects(110.0)]))
    result = assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve")
    assert len(calls) == 1
    assert any("shape 2 of slide 13" in w and "title" in w and "hidden" in w for w in result.warnings)


def test_assemble_dsk_deck_calls_restore_crop_zorder(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")

    captured: dict = {}

    def fake_restore_crop_zorder(fw_deck_arg, staging_path, plan, warnings, *, hidden={}):
        captured["fw_deck"] = fw_deck_arg
        captured["staging_path"] = staging_path
        captured["plan"] = plan
        return {}

    monkeypatch.setattr(dsa, "_restore_crop_zorder", fake_restore_crop_zorder)
    result = assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")
    assert captured["fw_deck"] == fw_deck
    assert captured["plan"] is not None
    assert result.zorder == {}


def test_assemble_builds_surplus_raises_refusal(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")
    monkeypatch.setattr(
        iwa_builds,
        "verify_builds",
        lambda src_by_number, out_by_number, slides=None: {
            "surplus": [{"slide": 13, "effect": "e", "animationType": "a", "identity": "i", "count": 1}],
            "missing": [],
            "transitions": [],
            "order": [],
        },
    )
    with pytest.raises(AssemblyRefusal, match="surplus"):
        assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")


def test_assemble_missing_for_deleted_tolerated_other_slide_raises(tmp_path, monkeypatch):
    """A missing build matching a deleted item is tolerated; one that doesn't refuses
    rather than warning."""
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")

    def fake_deck_builds(path, *, deck=None):
        if Path(path) == fw_deck:
            return {
                13: {"slideId": "s13", "builds": [], "transition": None},
                32: {
                    "slideId": "s32",
                    "builds": [{"kind": "movie", "kindIndex": 0, "effect": "e", "animationType": "a", "identity": "i"}],
                    "transition": None,
                },
            }
        return {
            1: {"slideId": "o1", "builds": [], "transition": None},
            2: {"slideId": "o2", "builds": [], "transition": _dissolve_transition(0.5)},
        }

    monkeypatch.setattr(iwa_builds, "deck_builds", fake_deck_builds)
    monkeypatch.setattr(
        iwa_builds,
        "verify_builds",
        lambda src_by_number, out_by_number, slides=None: {
            "surplus": [],
            "missing": [
                {"slide": 32, "effect": "e", "animationType": "a", "identity": "i", "count": 1},
                {"slide": 13, "effect": "e", "animationType": "a", "identity": "i", "count": 1},
            ],
            "transitions": [],
            "order": [],
        },
    )
    with pytest.raises(AssemblyRefusal, match="not explained by a delete"):
        assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")


def test_assemble_missing_for_deleted_tolerated_no_refusal(tmp_path, monkeypatch):
    """A missing build fully explained by deletions never raises."""
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")

    def fake_deck_builds(path, *, deck=None):
        if Path(path) == fw_deck:
            return {
                13: {"slideId": "s13", "builds": [], "transition": None},
                32: {
                    "slideId": "s32",
                    "builds": [{"kind": "movie", "kindIndex": 0, "effect": "e", "animationType": "a", "identity": "i"}],
                    "transition": None,
                },
            }
        return {
            1: {"slideId": "o1", "builds": [], "transition": None},
            2: {"slideId": "o2", "builds": [], "transition": _dissolve_transition(0.5)},
        }

    monkeypatch.setattr(iwa_builds, "deck_builds", fake_deck_builds)
    monkeypatch.setattr(
        iwa_builds,
        "verify_builds",
        lambda src_by_number, out_by_number, slides=None: {
            "surplus": [],
            "missing": [{"slide": 32, "effect": "e", "animationType": "a", "identity": "i", "count": 1}],
            "transitions": [],
            "order": [],
        },
    )
    result = assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")
    assert result.builds["tolerated_missing"] == [
        {"slide": 32, "effect": "e", "animationType": "a", "identity": "i", "count": 1}
    ]


def test_assemble_clip_slide_transition_mismatch_tolerated_other_raises(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")
    monkeypatch.setattr(
        iwa_builds,
        "verify_builds",
        lambda src_by_number, out_by_number, slides=None: {
            "surplus": [],
            "missing": [],
            "transitions": [
                {"slide": 32, "source": ("magicMove", 1.0), "output": ("none", 0.0)},
                {"slide": 13, "source": ("magicMove", 1.0), "output": ("none", 0.0)},
            ],
            "order": [],
        },
    )
    with pytest.raises(AssemblyRefusal, match="unexplained transition"):
        assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")


def test_assemble_clip_slide_transition_mismatch_alone_is_tolerated(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")
    monkeypatch.setattr(
        iwa_builds,
        "verify_builds",
        lambda src_by_number, out_by_number, slides=None: {
            "surplus": [],
            "missing": [],
            "transitions": [{"slide": 32, "source": ("magicMove", 1.0), "output": ("apple:dissolve", 0.5)}],
            "order": [],
        },
    )
    result = assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")
    assert not any("transition changed on clip slide 32" in w for w in result.warnings)


def test_assemble_reveal_order_mismatch_raises(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")
    monkeypatch.setattr(
        iwa_builds,
        "verify_builds",
        lambda src_by_number, out_by_number, slides=None: {
            "surplus": [],
            "missing": [],
            "transitions": [],
            "order": [{"slide": 13, "at": 0, "source": ("a",), "output": ("b",)}],
        },
    )
    with pytest.raises(AssemblyRefusal, match="reveal-order"):
        assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")


def test_assemble_stroke_guard_refuses_shared_styles(tmp_path, monkeypatch):
    """Realistic two-slide output: ordinals 1,2 map to source slides 13,32 (see
    ``_assemble_fixture``). ``card_styles`` reports OUTPUT-deck ordinals, not source
    numbers, so a style used on ordinal 1 (-> source 13, in kept) and on a bogus ordinal
    5 (no source slide at that ordinal in a 2-slide output -> rekeys to the -5 sentinel,
    never a real kept number) must still be refused after re-keying."""
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")
    monkeypatch.setattr(
        iwa_write,
        "card_styles",
        lambda objects, id_to_file: [
            {
                "id": "style-shared",
                "member": "Index/DocumentStylesheet.iwa",
                "width": None,
                "color": (1.0, 1.0, 1.0, 1.0),
                "pattern": "TSDEmptyPattern",
                "refs": 2,
                "slides": [1, 5],
                "inherited": False,
            }
        ],
    )
    result = assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")
    assert result.stroke["media_refused"] == [
        {"id": "style-shared", "reason": "style refs slides outside kept", "slides": [-5, 13]}
    ]
    assert any("media stroke style-shared refused" in w for w in result.warnings)
    assert "media" not in result.stroke


def test_assemble_stroke_ordinal_rekey_allows_fully_kept_style(tmp_path, monkeypatch):
    """The counterpart to the refusal test: a style used only on ordinals that all map
    to kept source slides (1 -> 13, 2 -> 32) must be granted, not refused -- this is
    exactly the ordinal-vs-source-number bug the rekey fixes."""
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")
    monkeypatch.setattr(
        iwa_write,
        "card_styles",
        lambda objects, id_to_file: [
            {
                "id": "style-kept",
                "member": "Index/DocumentStylesheet.iwa",
                "width": None,
                "color": (1.0, 1.0, 1.0, 1.0),
                "pattern": "TSDEmptyPattern",
                "refs": 2,
                "slides": [1, 2],
                "inherited": False,
            }
        ],
    )
    result = assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")
    assert result.stroke["media"] == {"refused": False, "patched": [], "created": []}
    assert "media_refused" not in result.stroke


def test_assemble_err_line_raises_with_slide_and_number(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(
        monkeypatch, payload, classes, "ERR\t13\t-1708\tSomething failed", returncode=1
    )
    with pytest.raises(AssemblyRefusal, match=r"slide 13.*-1708.*Something failed"):
        assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")


def test_assemble_miss_line_reported_as_warning(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    stderr_text = "\n".join(
        [
            'MISS\t13\ttext item 1 of slide 1\tobject not found',
            "OBED\t13\tdone",
            "OBED\t32\tdone",
        ]
    )
    _patch_common(monkeypatch, payload, classes, stderr_text)
    result = assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")
    assert any("write failed for text item 1 of slide 1" in w for w in result.warnings)


def test_assemble_import_precondition_refusal_before_keynote(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")

    def _refuse(*_a, **_k):
        raise AssemblyRefusal("no donor")

    monkeypatch.setattr(dsa, "check_layout_import_preconditions", _refuse)
    with pytest.raises(AssemblyRefusal, match="no donor"):
        assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="import")
    assert not out_path.exists()


def test_assemble_import_post_check_refusal_blocks_publish(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")
    monkeypatch.setattr(dsa, "check_layout_import_preconditions", lambda *_a, **_k: None)

    def _refuse(*_a, **_k):
        raise AssemblyRefusal("staged layout unsafe")

    monkeypatch.setattr(dsa, "verify_staged_layouts_alpha_safe", _refuse)
    with pytest.raises(AssemblyRefusal, match="staged layout unsafe"):
        assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="import")
    assert not out_path.exists()


def test_restore_stroke_finds_truly_strokeless_media_independently_of_card_styles():
    """`card_styles` (iwa_write.py) omits any style whose stroke resolves to `None` --
    the common case for media with no stroke property at all -- so it never reaches
    `_restore_stroke`'s grants loop over `out_styles`. The independent pass must still
    find and grant it."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "style1": {},
    }
    dsa_module = dsa
    import obed_edom.iwa_write as iwa_write_mod

    orig_load_deck = dsa_module._load_deck
    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_patch_media = iwa_write_mod.patch_media_stroke
    captured: dict = {}
    try:
        dsa_module._load_deck = lambda path: (objects, {}, {})
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {}, "chosen": [], "notes": [], "out_selected": []
            }
        )

        def _fake_patch_media_stroke(deck, grants):
            captured["grants"] = grants
            return {"refused": False, "patched": [], "created": []}

        iwa_write_mod.patch_media_stroke = _fake_patch_media_stroke

        plan = AssemblyPlan(
            kept=(13,), ordinals={13: 1}, fits={13: {("image", 0): Rect(0, 0, 100, 100)}}, deletes={}, clips={},
            text_sizes={}, autosize={}, warnings=(),
        )
        warnings: list[str] = []
        stroke = dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa_module._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.patch_media_stroke = orig_patch_media

    assert captured["grants"]["style1"] == {
        "width": 5.0, "color": (1.0, 1.0, 1.0, 1.0), "pattern": "TSDSolidPattern"
    }
    assert stroke["media"]["refused"] is False


def test_restore_stroke_grants_a_present_but_empty_pattern_style():
    """A style whose stroke submessage exists but is `TSDEmptyPattern` -- Keynote's own
    latent-stroke placeholder -- is "no stroke" for grant purposes, same as a style with
    no stroke submessage at all; deciding by `width is not None` alone would wrongly skip
    it, since Keynote still records a latent width on an empty pattern."""
    import obed_edom.iwa_write as iwa_write_mod

    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_patch_media = iwa_write_mod.patch_media_stroke
    orig_card_styles = iwa_write_mod.card_styles
    orig_load_deck = dsa._load_deck
    captured: dict = {}
    try:
        dsa._load_deck = lambda path: ({}, {}, {})
        iwa_write_mod.card_styles = lambda objects, id_to_file: [{
            "id": "style-empty", "member": "Index/DocumentStylesheet.iwa", "width": 1.0,
            "color": (0.0, 0.0, 0.0, 0.0), "pattern": "TSDEmptyPattern", "refs": 3,
            "slides": [1], "inherited": False,
        }]
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {}, "chosen": [], "notes": [], "out_selected": []
            }
        )

        def _fake_patch_media_stroke(deck, grants):
            captured["grants"] = grants
            return {"refused": False, "patched": [], "created": []}

        iwa_write_mod.patch_media_stroke = _fake_patch_media_stroke

        plan = AssemblyPlan(
            kept=(13,), ordinals={13: 1}, fits={13: {}}, deletes={}, clips={},
            text_sizes={}, autosize={}, warnings=(),
        )
        warnings: list[str] = []
        stroke = dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.patch_media_stroke = orig_patch_media
        iwa_write_mod.card_styles = orig_card_styles

    assert captured["grants"]["style-empty"] == {
        "width": 5.0, "color": (1.0, 1.0, 1.0, 1.0), "pattern": "TSDSolidPattern"
    }
    assert "restore" not in stroke


def test_restore_stroke_divides_a_real_pattern_width_by_canvas_scale():
    """A style with a real (non-empty) pattern and its own width is a genuine stroke that
    survived the assembly at the wrong scale -- the canvas-shrink leak -- and must be
    restored by dividing the output width back down by `canvas_scale`, not granted a
    default white border."""
    import obed_edom.iwa_write as iwa_write_mod

    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_patch_widths = iwa_write_mod.patch_stroke_widths
    orig_card_styles = iwa_write_mod.card_styles
    orig_load_deck = dsa._load_deck
    captured: dict = {}
    try:
        dsa._load_deck = lambda path: ({}, {}, {})
        iwa_write_mod.card_styles = lambda objects, id_to_file: [{
            "id": "style-real", "member": "Index/DocumentStylesheet.iwa", "width": 0.25,
            "color": (0.0, 0.0, 0.0, 1.0), "pattern": "TSDSolidPattern", "refs": 3,
            "slides": [1], "inherited": False,
        }]
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {}, "chosen": [], "notes": [], "out_selected": []
            }
        )

        def _fake_patch_stroke_widths(deck, widths):
            captured["widths"] = widths
            return {"refused": False, "applied": len(widths)}

        iwa_write_mod.patch_stroke_widths = _fake_patch_stroke_widths

        plan = AssemblyPlan(
            kept=(13,), ordinals={13: 1}, fits={13: {}}, deletes={}, clips={},
            text_sizes={}, autosize={}, warnings=(),
        )
        warnings: list[str] = []
        # slideWidth 7680 -> canvas_scale = 1920 / 7680 = 0.25.
        stroke = dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.patch_stroke_widths = orig_patch_widths
        iwa_write_mod.card_styles = orig_card_styles

    assert captured["widths"]["style-real"] == pytest.approx(1.0)
    assert stroke["leak_widths"]["style-real"] == pytest.approx(1.0)
    assert "media" not in stroke


def test_restore_stroke_mints_a_matched_style_escaping_via_a_layout_reference():
    """A style paired by `match_card_stroke_styles` (a solid matched width) must still go
    through the same census as leak widths -- an escaping layout reference, with a
    genuine retained ref elsewhere, mints it instead and it must never reach
    `patch_stroke_widths`, even though `match["widths"]` already has it queued before the
    census runs."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style-matched"}},
        "img2": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style-matched"}},
        "layout1": {"_pbtype": "KN.SlideLayoutArchive", "drawablesZOrder": [{"identifier": "img2"}]},
        "style-matched": {"mediaProperties": {"stroke": {
            "pattern": {"type": "TSDSolidPattern"}, "width": 0.25,
            "color": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0},
        }}},
    }
    orig_load_deck = dsa._load_deck
    import obed_edom.iwa_write as iwa_write_mod

    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_patch_widths = iwa_write_mod.patch_stroke_widths
    orig_patch_media = iwa_write_mod.patch_media_stroke
    captured: dict = {}
    try:
        dsa._load_deck = lambda path: (objects, {}, {})
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {"style-matched": 4.0},
                "chosen": [{"id": "style-matched", "old": 0.25, "new": 4.0, "refs": 3}],
                "notes": [], "out_selected": [],
            }
        )

        def _fake_patch_stroke_widths(deck, widths):
            captured["widths"] = widths
            return {"refused": False, "applied": len(widths)}

        iwa_write_mod.patch_stroke_widths = _fake_patch_stroke_widths
        iwa_write_mod.patch_media_stroke = lambda deck, grants: {"refused": False, "patched": [], "created": []}
        orig_mint = iwa_write_mod.mint_media_style
        iwa_write_mod.mint_media_style = _fake_mint_media_style
        _fake_mint_calls.clear()

        plan = AssemblyPlan(
            kept=(13,), ordinals={13: 1}, fits={13: {("image", 0): Rect(0, 0, 100, 100)}}, deletes={}, clips={},
            text_sizes={}, autosize={}, warnings=(),
        )
        warnings: list[str] = []
        stroke = dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.patch_stroke_widths = orig_patch_widths
        iwa_write_mod.patch_media_stroke = orig_patch_media
        iwa_write_mod.mint_media_style = orig_mint

    assert "widths" not in captured
    assert stroke["chosen"] == []
    assert "media_refused" not in stroke
    assert stroke["minted"]["style-matched"]["drawables"] == ["img1"]
    [mint_call] = [c for c in _fake_mint_calls if c["source_style_id"] == "style-matched"]
    assert mint_call["spec"]["stroke_message"]["width"] == pytest.approx(4.0)


def test_width_restore_escape_is_minted_with_source_width():
    """A style with a real pattern and a shrunk width, escaping via a layout reference
    and not present in `match["widths"]` (a leak width, not a matched one), is minted
    with the width-restore spec: the resolved own stroke, colour/frame preserved, width
    set to the paired/leak source width -- not the grant spec."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style-leak"}},
        "img2": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style-leak"}},
        "layout1": {"_pbtype": "KN.SlideLayoutArchive", "drawablesZOrder": [{"identifier": "img2"}]},
        "style-leak": {"_pbtype": "TSD.MediaStyleArchive", "mediaProperties": {"stroke": {
            "pattern": {"type": "TSDSolidPattern"}, "width": 0.25,
            "color": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0}, "frame": {"frameName": "Formal Shadow"},
        }}},
    }
    orig_load_deck = dsa._load_deck
    import obed_edom.iwa_write as iwa_write_mod

    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_patch_media = iwa_write_mod.patch_media_stroke
    orig_mint = iwa_write_mod.mint_media_style
    try:
        dsa._load_deck = lambda path: (objects, {}, {})
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {}, "chosen": [], "notes": [], "out_selected": []
            }
        )
        iwa_write_mod.patch_media_stroke = lambda deck, grants: {"refused": False, "patched": [], "created": []}
        iwa_write_mod.mint_media_style = _fake_mint_media_style
        _fake_mint_calls.clear()

        plan = AssemblyPlan(
            kept=(13,), ordinals={13: 1}, fits={13: {("image", 0): Rect(0, 0, 100, 100)}}, deletes={}, clips={},
            text_sizes={}, autosize={}, warnings=(),
        )
        warnings: list[str] = []
        stroke = dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.patch_media_stroke = orig_patch_media
        iwa_write_mod.mint_media_style = orig_mint

    assert "media_refused" not in stroke
    assert stroke["minted"]["style-leak"]["drawables"] == ["img1"]
    [mint_call] = [c for c in _fake_mint_calls if c["source_style_id"] == "style-leak"]
    spec = mint_call["spec"]
    assert "stroke_message" in spec
    assert spec["stroke_message"]["pattern"] == {"type": "TSDSolidPattern"}
    assert spec["stroke_message"]["color"] == {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0}
    assert spec["stroke_message"]["frame"] == {"frameName": "Formal Shadow"}
    # slideWidth 7680 -> canvas_scale = 1920 / 7680 = 0.25 -> source width = 0.25 / 0.25.
    assert spec["stroke_message"]["width"] == pytest.approx(1.0)


def test_mint_refusal_falls_back_to_refused_media():
    """A mint that refuses must fall back to `stroke["media_refused"]` (and the standard
    "refused" warning), never silently disappear the style."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "img2": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "layout1": {"_pbtype": "KN.SlideLayoutArchive", "drawablesZOrder": [{"identifier": "img2"}]},
        "style1": {"mediaProperties": {"stroke": {
            "pattern": {"type": "TSDEmptyPattern"}, "width": 1.0,
            "color": {"r": 0.0, "g": 0.0, "b": 0.0, "a": 0.0},
        }}},
    }
    orig_load_deck = dsa._load_deck
    import obed_edom.iwa_write as iwa_write_mod

    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_patch_media = iwa_write_mod.patch_media_stroke
    orig_mint = iwa_write_mod.mint_media_style
    try:
        dsa._load_deck = lambda path: (objects, {}, {})
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {}, "chosen": [], "notes": [], "out_selected": []
            }
        )
        iwa_write_mod.patch_media_stroke = lambda deck, grants: {"refused": False, "patched": [], "created": []}
        iwa_write_mod.mint_media_style = lambda deck, source_style_id, drawable_ids, spec: {
            "refused": True, "reason": "reparse gate failed",
        }

        plan = AssemblyPlan(
            kept=(13,), ordinals={13: 1}, fits={13: {("image", 0): Rect(0, 0, 100, 100)}}, deletes={}, clips={},
            text_sizes={}, autosize={}, warnings=(),
        )
        warnings: list[str] = []
        stroke = dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.patch_media_stroke = orig_patch_media
        iwa_write_mod.mint_media_style = orig_mint

    assert "minted" not in stroke
    [entry] = [r for r in stroke["media_refused"] if r["id"] == "style1"]
    assert entry["reason"] == "reparse gate failed"
    assert any("style1 mint refused: reparse gate failed" in w for w in warnings)


def test_mint_refusal_with_no_reason_falls_back_to_unknown():
    """A mint refusal that carries no `"reason"` key must still produce a warning,
    falling back to the literal "unknown"."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "img2": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "layout1": {"_pbtype": "KN.SlideLayoutArchive", "drawablesZOrder": [{"identifier": "img2"}]},
        "style1": {"mediaProperties": {"stroke": {
            "pattern": {"type": "TSDEmptyPattern"}, "width": 1.0,
            "color": {"r": 0.0, "g": 0.0, "b": 0.0, "a": 0.0},
        }}},
    }
    orig_load_deck = dsa._load_deck
    import obed_edom.iwa_write as iwa_write_mod

    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_patch_media = iwa_write_mod.patch_media_stroke
    orig_mint = iwa_write_mod.mint_media_style
    try:
        dsa._load_deck = lambda path: (objects, {}, {})
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {}, "chosen": [], "notes": [], "out_selected": []
            }
        )
        iwa_write_mod.patch_media_stroke = lambda deck, grants: {"refused": False, "patched": [], "created": []}
        iwa_write_mod.mint_media_style = lambda deck, source_style_id, drawable_ids, spec: {"refused": True}

        plan = AssemblyPlan(
            kept=(13,), ordinals={13: 1}, fits={13: {("image", 0): Rect(0, 0, 100, 100)}}, deletes={}, clips={},
            text_sizes={}, autosize={}, warnings=(),
        )
        warnings: list[str] = []
        dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.patch_media_stroke = orig_patch_media
        iwa_write_mod.mint_media_style = orig_mint

    assert any(w.endswith("mint refused: unknown") for w in warnings)


def test_restore_stroke_drives_the_real_mint_media_style_end_to_end(tmp_path):
    """No fake: a real in-memory deck, a real layout escape, a real retained ref on the
    kept slide -- ``_restore_stroke`` must actually call the real ``mint_media_style``
    and land a real ``TSD.MediaStyleArchive`` variation in the output deck, re-pointing
    only the retained drawable."""
    pytest.importorskip("keynote_parser")

    from test_iwa_write import _arch, _geom
    from test_stroke_probe import _build_deck

    layout_img = _arch(900101, "TSD.ImageArchive", {"style": {"identifier": 900}, "super": _geom(0, 0, 10, 10)})
    layout_root = _arch(900102, "KN.SlideArchive", {"drawablesZOrder": [{"identifier": 900101}]})

    out_path = _build_deck(
        tmp_path / "out.key", stylesheet_root=True, metadata=True,
        extra_slide_archives=(layout_img, layout_root),
    )
    fw_path = _build_deck(tmp_path / "fw.key")

    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1}, fits={1: {("image", 0): Rect(0, 0, 100, 100)}}, deletes={}, clips={},
        text_sizes={}, autosize={}, warnings=(),
    )
    warnings: list[str] = []
    stroke = dsa._restore_stroke(fw_path, out_path, plan, {"slideWidth": 7680.0}, 999, warnings, print)

    assert "900" not in {r["id"] for r in stroke.get("media_refused", [])}
    assert stroke["minted"]["900"]["drawables"] == ["300"]
    new_id = stroke["minted"]["900"]["new_id"]

    from obed_edom.iwa_runs import _load_deck
    objects, _id_to_file, _fi = _load_deck(out_path)
    minted = objects[new_id]
    assert minted["_pbtype"] == "TSD.MediaStyleArchive"
    assert minted["super"]["parent"]["identifier"] == "900"
    assert minted["super"]["isVariation"] is True
    assert objects["300"]["style"]["identifier"] == new_id
    assert objects["301"]["style"]["identifier"] == "900"
    assert objects["900"]["mediaProperties"]["stroke"]["width"] == pytest.approx(0.25)


def test_restore_stroke_patches_an_eligible_matched_style():
    """A matched style whose only references are retained staged media on kept slides
    passes the census and reaches `patch_stroke_widths` with the matched (not leaked)
    width."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style-matched"}},
        "style-matched": {"mediaProperties": {"stroke": {
            "pattern": {"type": "TSDSolidPattern"}, "width": 0.25,
            "color": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0},
        }}},
    }
    orig_load_deck = dsa._load_deck
    import obed_edom.iwa_write as iwa_write_mod

    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_patch_widths = iwa_write_mod.patch_stroke_widths
    captured: dict = {}
    try:
        dsa._load_deck = lambda path: (objects, {}, {})
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {"style-matched": 4.0},
                "chosen": [{"id": "style-matched", "old": 0.25, "new": 4.0, "refs": 3}],
                "notes": [], "out_selected": [],
            }
        )

        def _fake_patch_stroke_widths(deck, widths):
            captured["widths"] = widths
            return {"refused": False, "applied": len(widths)}

        iwa_write_mod.patch_stroke_widths = _fake_patch_stroke_widths

        plan = AssemblyPlan(
            kept=(13,), ordinals={13: 1}, fits={13: {("image", 0): Rect(0, 0, 100, 100)}}, deletes={}, clips={},
            text_sizes={}, autosize={}, warnings=(),
        )
        warnings: list[str] = []
        stroke = dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.patch_stroke_widths = orig_patch_widths

    assert captured["widths"] == {"style-matched": 4.0}
    assert stroke["chosen"] == [{"id": "style-matched", "old": 0.25, "new": 4.0, "refs": 3}]
    assert "media_refused" not in stroke


def test_restore_stroke_mints_a_style_escaping_via_a_layout_reference():
    """`card_styles`' `slides` only tracks refs reachable via a slide's own
    `drawablesZOrder` walk, so a second image sharing the style but living outside any
    slide (a layout/master reference) never shows up there and the old `style["slides"]`
    check alone would wrongly grant it. The full `out_objects` census must catch it; with
    a genuine retained ref (`img1`) present, the style is minted for it rather than
    refused."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "img2": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "layout1": {"_pbtype": "KN.SlideLayoutArchive", "drawablesZOrder": [{"identifier": "img2"}]},
        "style1": {"mediaProperties": {"stroke": {
            "pattern": {"type": "TSDEmptyPattern"}, "width": 1.0,
            "color": {"r": 0.0, "g": 0.0, "b": 0.0, "a": 0.0},
        }}},
    }
    orig_load_deck = dsa._load_deck
    import obed_edom.iwa_write as iwa_write_mod

    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_patch_media = iwa_write_mod.patch_media_stroke
    orig_mint = iwa_write_mod.mint_media_style
    try:
        dsa._load_deck = lambda path: (objects, {}, {})
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {}, "chosen": [], "notes": [], "out_selected": []
            }
        )
        iwa_write_mod.patch_media_stroke = lambda deck, grants: {"refused": False, "patched": [], "created": []}
        iwa_write_mod.mint_media_style = _fake_mint_media_style

        plan = AssemblyPlan(
            kept=(13,), ordinals={13: 1}, fits={13: {("image", 0): Rect(0, 0, 100, 100)}}, deletes={}, clips={},
            text_sizes={}, autosize={}, warnings=(),
        )
        warnings: list[str] = []
        stroke = dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.patch_media_stroke = orig_patch_media
        iwa_write_mod.mint_media_style = orig_mint

    assert "media" not in stroke
    assert "media_refused" not in stroke
    assert stroke["minted"]["style1"]["drawables"] == ["img1"]


def test_restore_stroke_minted_style_with_an_orphan_referrer_skips_the_patched_warning():
    """A style with a genuine escape, a retained ref and an orphan referrer is minted --
    the source style is left untouched, so the orphan must not be reported via the
    "patched with N unreached referrer(s)" warning, which only applies to a global
    patch."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "img2": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "img-orphan": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "layout1": {"_pbtype": "KN.SlideLayoutArchive", "drawablesZOrder": [{"identifier": "img2"}]},
        "style1": {"mediaProperties": {"stroke": {
            "pattern": {"type": "TSDEmptyPattern"}, "width": 1.0,
            "color": {"r": 0.0, "g": 0.0, "b": 0.0, "a": 0.0},
        }}},
    }
    orig_load_deck = dsa._load_deck
    import obed_edom.iwa_write as iwa_write_mod

    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_patch_media = iwa_write_mod.patch_media_stroke
    orig_mint = iwa_write_mod.mint_media_style
    try:
        dsa._load_deck = lambda path: (objects, {}, {})
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {}, "chosen": [], "notes": [], "out_selected": []
            }
        )
        iwa_write_mod.patch_media_stroke = lambda deck, grants: {"refused": False, "patched": [], "created": []}
        iwa_write_mod.mint_media_style = _fake_mint_media_style

        plan = AssemblyPlan(
            kept=(13,), ordinals={13: 1}, fits={13: {("image", 0): Rect(0, 0, 100, 100)}}, deletes={}, clips={},
            text_sizes={}, autosize={}, warnings=(),
        )
        warnings: list[str] = []
        stroke = dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.patch_media_stroke = orig_patch_media
        iwa_write_mod.mint_media_style = orig_mint

    assert stroke["minted"]["style1"]["drawables"] == ["img1"]
    assert stroke["orphan_refs"] == {"style1": 1}
    assert not any("patched with" in w for w in warnings)


def test_restore_stroke_reports_unbuildable_mint_spec_reason():
    """A style with a real (non-empty) pattern but no width has no buildable mint spec --
    the refusal reason must say so, not fall back to the generic escaping-media
    message."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "img2": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "layout1": {"_pbtype": "KN.SlideLayoutArchive", "drawablesZOrder": [{"identifier": "img2"}]},
        "style1": {"_pbtype": "TSD.MediaStyleArchive"},
    }
    orig_load_deck = dsa._load_deck
    import obed_edom.iwa_write as iwa_write_mod

    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_card_styles = iwa_write_mod.card_styles
    try:
        dsa._load_deck = lambda path: (objects, {}, {})
        iwa_write_mod.card_styles = lambda out_objects, id_to_file: [{
            "id": "style1", "member": "Index/DocumentStylesheet.iwa", "width": None,
            "color": None, "pattern": "TSDSolidPattern", "refs": 2, "slides": [1], "inherited": False,
        }]
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {}, "chosen": [], "notes": [], "out_selected": []
            }
        )

        plan = AssemblyPlan(
            kept=(13,), ordinals={13: 1}, fits={13: {("image", 0): Rect(0, 0, 100, 100)}}, deletes={}, clips={},
            text_sizes={}, autosize={}, warnings=(),
        )
        warnings: list[str] = []
        stroke = dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.card_styles = orig_card_styles

    [entry] = [r for r in stroke["media_refused"] if r["id"] == "style1"]
    assert entry["reason"] == "no mint spec buildable (unresolvable stroke)"


def test_restore_stroke_mints_a_style_via_a_transitive_child_escape():
    """A style with its own real stroke ("style-parent") must not be patched globally if
    a CHILD style that inherits it via `super.parent` ("style-child", referenced only
    from a layout/master image) escapes -- patching the parent globally would also
    repaint that inheritor, so the census must walk inheritance, not just direct
    `style.identifier` refs; with a genuine retained ref (`img1`) present, the style is
    minted for it instead of refused."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style-parent"}},
        "img2": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style-child"}},
        "group1": {"_pbtype": "TSD.GroupArchive", "children": [{"identifier": "img2"}]},
        "master1": {"_pbtype": "KN.MasterSlideArchive", "drawablesZOrder": [{"identifier": "group1"}]},
        "style-parent": {"_pbtype": "TSD.MediaStyleArchive", "mediaProperties": {"stroke": {
            "pattern": {"type": "TSDSolidPattern"}, "width": 0.25,
            "color": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0},
        }}},
        "style-child": {"_pbtype": "TSD.MediaStyleArchive", "super": {"parent": {"identifier": "style-parent"}}},
    }
    orig_load_deck = dsa._load_deck
    import obed_edom.iwa_write as iwa_write_mod

    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_patch_widths = iwa_write_mod.patch_stroke_widths
    captured: dict = {}
    try:
        dsa._load_deck = lambda path: (objects, {}, {})
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {}, "chosen": [], "notes": [], "out_selected": []
            }
        )

        def _fake_patch_stroke_widths(deck, widths):
            captured["widths"] = widths
            return {"refused": False, "applied": len(widths)}

        iwa_write_mod.patch_stroke_widths = _fake_patch_stroke_widths
        orig_mint = iwa_write_mod.mint_media_style
        iwa_write_mod.mint_media_style = _fake_mint_media_style

        plan = AssemblyPlan(
            kept=(13,), ordinals={13: 1}, fits={13: {("image", 0): Rect(0, 0, 100, 100)}}, deletes={}, clips={},
            text_sizes={}, autosize={}, warnings=(),
        )
        warnings: list[str] = []
        stroke = dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.patch_stroke_widths = orig_patch_widths
        iwa_write_mod.mint_media_style = orig_mint

    assert "widths" not in captured
    assert "media_refused" not in stroke
    assert stroke["minted"]["style-parent"]["drawables"] == ["img1"]


def test_restore_stroke_mints_parent_and_inheritor_each_for_their_own_retained_ref():
    """A retained drawable on the INHERITOR style (`img2` on `style-child`) must not
    leak into the parent's (`style-parent`) retained set via `_retained_refs`'
    ``str(sid) == style_id`` filter. Both styles escape (a layout/master ref each)
    and each is minted only for its own retained ref."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [
            {"identifier": "node1"}, {"identifier": "node2"},
        ]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "node2": {"slide": {"identifier": "slide2"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}]},
        "slide2": {"drawablesZOrder": [{"identifier": "img2"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style-parent"}},
        "img2": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style-child"}},
        "escape_parent": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style-parent"}},
        "escape_child": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style-child"}},
        "master1": {"_pbtype": "KN.MasterSlideArchive", "drawablesZOrder": [
            {"identifier": "escape_parent"}, {"identifier": "escape_child"},
        ]},
        "style-parent": {"_pbtype": "TSD.MediaStyleArchive", "mediaProperties": {"stroke": {
            "pattern": {"type": "TSDSolidPattern"}, "width": 0.25,
            "color": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0},
        }}},
        "style-child": {"_pbtype": "TSD.MediaStyleArchive", "super": {"parent": {"identifier": "style-parent"}}},
    }
    orig_load_deck = dsa._load_deck
    import obed_edom.iwa_write as iwa_write_mod

    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_patch_widths = iwa_write_mod.patch_stroke_widths
    orig_mint = iwa_write_mod.mint_media_style
    try:
        dsa._load_deck = lambda path: (objects, {}, {})
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {}, "chosen": [], "notes": [], "out_selected": []
            }
        )
        iwa_write_mod.patch_stroke_widths = lambda deck, widths: {"refused": False, "applied": len(widths)}
        iwa_write_mod.mint_media_style = _fake_mint_media_style

        plan = AssemblyPlan(
            kept=(13, 14), ordinals={13: 1, 14: 2},
            fits={13: {("image", 0): Rect(0, 0, 100, 100)}, 14: {("image", 0): Rect(0, 0, 100, 100)}},
            deletes={}, clips={}, text_sizes={}, autosize={}, warnings=(),
        )
        warnings: list[str] = []
        stroke = dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.patch_stroke_widths = orig_patch_widths
        iwa_write_mod.mint_media_style = orig_mint

    assert "media_refused" not in stroke
    assert stroke["minted"]["style-parent"]["drawables"] == ["img1"]
    assert stroke["minted"]["style-child"]["drawables"] == ["img2"]


def test_restore_stroke_mints_a_style_escaping_via_a_slide_archive_outside_the_tree():
    """On a real Keynote build there is no `KN.SlideLayoutArchive`/`KN.MasterSlideArchive`
    object at all -- layouts and masters are plain `KN.SlideArchive` objects living
    outside the show's own `slideTree`. The reachability walk must treat such an object
    as a layout/master root, not just the two named archive types; with a genuine
    retained ref (`img1`) present, the style is minted for it rather than refused."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "img1"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "img2": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "template1": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "img2"}]},
        "style1": {"mediaProperties": {"stroke": {
            "pattern": {"type": "TSDEmptyPattern"}, "width": 1.0,
            "color": {"r": 0.0, "g": 0.0, "b": 0.0, "a": 0.0},
        }}},
    }
    orig_load_deck = dsa._load_deck
    import obed_edom.iwa_write as iwa_write_mod

    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_patch_media = iwa_write_mod.patch_media_stroke
    orig_mint = iwa_write_mod.mint_media_style
    try:
        dsa._load_deck = lambda path: (objects, {}, {})
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {}, "chosen": [], "notes": [], "out_selected": []
            }
        )
        iwa_write_mod.patch_media_stroke = lambda deck, grants: {"refused": False, "patched": [], "created": []}
        iwa_write_mod.mint_media_style = _fake_mint_media_style

        plan = AssemblyPlan(
            kept=(13,), ordinals={13: 1}, fits={13: {("image", 0): Rect(0, 0, 100, 100)}}, deletes={}, clips={},
            text_sizes={}, autosize={}, warnings=(),
        )
        warnings: list[str] = []
        stroke = dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.patch_media_stroke = orig_patch_media
        iwa_write_mod.mint_media_style = orig_mint

    assert "media" not in stroke
    assert "media_refused" not in stroke
    assert stroke["minted"]["style1"]["drawables"] == ["img1"]


def test_layout_master_reachable_ids_non_empty_for_slide_archive_outside_tree():
    """Guards against a future rename of the accessor silently emptying the reachable
    set again: on a deck whose only layout/master root is a `KN.SlideArchive` outside
    the show tree, the set must be non-empty and contain that root's drawable."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": []},
        "template1": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "img-template"}]},
        "img-template": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "style1": {},
    }
    orig_load_deck = dsa._load_deck
    import obed_edom.iwa_write as iwa_write_mod

    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_card_styles = iwa_write_mod.card_styles
    orig_patch_media = iwa_write_mod.patch_media_stroke
    captured: dict = {}
    try:
        dsa._load_deck = lambda path: (objects, {}, {})
        iwa_write_mod.card_styles = lambda out_objects, id_to_file: []
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {}, "chosen": [], "notes": [], "out_selected": []
            }
        )

        def _fake_patch_media_stroke(deck, grants):
            captured["grants"] = grants
            return {"refused": False, "patched": [], "created": []}

        iwa_write_mod.patch_media_stroke = _fake_patch_media_stroke

        plan = AssemblyPlan(
            kept=(13,), ordinals={13: 1}, fits={13: {}}, deletes={}, clips={}, text_sizes={}, autosize={},
            warnings=(),
        )
        warnings: list[str] = []
        stroke = dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.card_styles = orig_card_styles
        iwa_write_mod.patch_media_stroke = orig_patch_media

    assert "grants" not in captured
    assert "orphan_refs" not in stroke


def test_restore_stroke_treats_an_output_slide_with_no_source_ordinal_as_an_escape():
    """A second-pass strokeless style whose only reference is on an output slide with no
    `inverse_ordinals` entry must land in the "outside kept" escape branch, not vanish
    as an orphan -- both classes of media should be refused the same way."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "style1": {},
    }
    captured: dict = {}
    plan = AssemblyPlan(
        kept=(13,), ordinals={}, fits={}, deletes={}, clips={}, text_sizes={}, autosize={}, warnings=(),
    )
    stroke = _stroke_census_harness(objects, plan, captured=captured)

    assert "grants" not in captured
    assert "orphan_refs" not in stroke
    assert len(stroke["media_refused"]) == 1
    assert stroke["media_refused"][0]["id"] == "style1"


def test_restore_stroke_via_transitive_child_ignores_a_shadowing_grandchild():
    """`style-grandchild` descends from `style-parent` through `style-child`, but
    `style-child` carries its own `mediaProperties.stroke` -- `_resolve_stroke` stops
    there, so `style-grandchild` never inherits `style-parent`'s stroke. Patching
    `style-parent` must not be refused merely because `style-grandchild` escapes via a
    layout reference."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style-parent"}},
        "img-grandchild": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style-grandchild"}},
        "layout1": {"_pbtype": "KN.SlideLayoutArchive", "drawablesZOrder": [{"identifier": "img-grandchild"}]},
        "style-parent": {"_pbtype": "TSD.MediaStyleArchive", "mediaProperties": {"stroke": {
            "pattern": {"type": "TSDSolidPattern"}, "width": 0.25,
            "color": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 1.0},
        }}},
        "style-child": {
            "_pbtype": "TSD.MediaStyleArchive",
            "super": {"parent": {"identifier": "style-parent"}},
            "mediaProperties": {"stroke": {
                "pattern": {"type": "TSDSolidPattern"}, "width": 0.5,
                "color": {"r": 0.0, "g": 0.0, "b": 0.0, "a": 1.0},
            }},
        },
        "style-grandchild": {
            "_pbtype": "TSD.MediaStyleArchive", "super": {"parent": {"identifier": "style-child"}},
        },
    }
    orig_load_deck = dsa._load_deck
    import obed_edom.iwa_write as iwa_write_mod

    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_patch_widths = iwa_write_mod.patch_stroke_widths
    captured: dict = {}
    try:
        dsa._load_deck = lambda path: (objects, {}, {})
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {}, "chosen": [], "notes": [], "out_selected": []
            }
        )

        def _fake_patch_stroke_widths(deck, widths):
            captured["widths"] = widths
            return {"refused": False, "applied": len(widths)}

        iwa_write_mod.patch_stroke_widths = _fake_patch_stroke_widths

        plan = AssemblyPlan(
            kept=(13,), ordinals={13: 1}, fits={13: {("image", 0): Rect(0, 0, 100, 100)}}, deletes={}, clips={},
            text_sizes={}, autosize={}, warnings=(),
        )
        warnings: list[str] = []
        stroke = dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.patch_stroke_widths = orig_patch_widths

    assert "media_refused" not in stroke
    assert captured["widths"]["style-parent"] == pytest.approx(1.0)


def test_restore_stroke_mints_a_strokeless_parent_whose_strokeless_child_escapes_via_layout():
    """`style1` is strokeless (grant candidate) and `style-child` inherits from it with
    no own stroke either. `style-child` is referenced only from a layout, so granting
    `style1` a stroke would silently repaint `style-child` too. The census must count
    `style-child` as an inheritor of `style1` even though `style1` itself has no stroke
    yet; since `img1` is a genuine retained ref, the style is minted for it rather than
    refused, leaving `style1` (and the layout's `style-child` ref) untouched."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "img-child": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style-child"}},
        "layout1": {"_pbtype": "KN.SlideLayoutArchive", "drawablesZOrder": [{"identifier": "img-child"}]},
        "style1": {"_pbtype": "TSD.MediaStyleArchive"},
        "style-child": {
            "_pbtype": "TSD.MediaStyleArchive",
            "super": {"parent": {"identifier": "style1"}},
        },
    }
    captured: dict = {}
    plan = AssemblyPlan(
        kept=(13,), ordinals={13: 1}, fits={13: {("image", 0): Rect(0, 0, 100, 100)}}, deletes={}, clips={},
        text_sizes={}, autosize={}, warnings=(),
    )
    stroke = _stroke_census_harness(objects, plan, captured=captured)

    assert "grants" not in captured
    assert "media_refused" not in stroke
    assert stroke["minted"]["style1"]["drawables"] == ["img1"]


_fake_mint_calls: list[dict] = []


def _fake_mint_media_style(deck, source_style_id, drawable_ids, spec):
    _fake_mint_calls.append({
        "source_style_id": source_style_id, "drawable_ids": list(drawable_ids), "spec": spec,
    })
    return {"refused": False, "new_id": f"{source_style_id}-mint", "drawables": list(drawable_ids)}


def _stroke_census_harness(objects, plan, *, captured):
    import obed_edom.iwa_write as iwa_write_mod

    orig_load_deck = dsa._load_deck
    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_card_styles = iwa_write_mod.card_styles
    orig_patch_media = iwa_write_mod.patch_media_stroke
    orig_mint = iwa_write_mod.mint_media_style
    try:
        dsa._load_deck = lambda path: (objects, {}, {})
        iwa_write_mod.card_styles = lambda out_objects, id_to_file: [{
            "id": "style1", "member": "Index/DocumentStylesheet.iwa", "width": None,
            "color": None, "pattern": None, "refs": 2, "slides": [1], "inherited": False,
        }]
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {}, "chosen": [], "notes": [], "out_selected": []
            }
        )

        def _fake_patch_media_stroke(deck, grants):
            captured["grants"] = grants
            return {"refused": False, "patched": [], "created": []}

        iwa_write_mod.patch_media_stroke = _fake_patch_media_stroke
        iwa_write_mod.mint_media_style = _fake_mint_media_style
        warnings: list[str] = []
        return dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.card_styles = orig_card_styles
        iwa_write_mod.patch_media_stroke = orig_patch_media
        iwa_write_mod.mint_media_style = orig_mint


def test_escaping_style_with_no_retained_refs_still_refuses():
    """`style1`'s only referrers are a layout image (escape reason "layout/master") and a
    non-retained kept-slide image (escape reason "non-retained (deleted/not-staged)
    object") -- both escaping, none retained, so `_retained_refs` is empty and the style
    must be refused, never minted, even though `_escaping_refs` is non-empty."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img2"}]},
        "img2": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "layout1": {"_pbtype": "KN.SlideLayoutArchive", "drawablesZOrder": [{"identifier": "img-layout"}]},
        "img-layout": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "style1": {},
    }
    plan = AssemblyPlan(
        kept=(13,), ordinals={13: 1}, fits={13: {}}, deletes={}, clips={}, text_sizes={}, autosize={},
        warnings=(),
    )
    captured: dict = {}
    _fake_mint_calls.clear()
    stroke = _stroke_census_harness(objects, plan, captured=captured)

    assert not _fake_mint_calls
    assert "minted" not in stroke
    assert stroke["media_refused"] == [{
        "id": "style1",
        "reason": "style refs escaping media: layout/master; non-retained (deleted/not-staged) object",
        "slides": [13],
    }]
    row = stroke["media_refused"][0]
    assert "minted" not in stroke
    assert "mint" not in row


def test_restore_stroke_grants_with_an_orphan_referrer_counted_not_refused():
    """A style with two retained refs on a kept slide plus a third referrer reachable from
    no slide, layout or master (archive cruft) grants normally -- the orphan cannot render,
    so it is counted into `orphan_refs`, not treated as an escape."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}, {"identifier": "img2"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "img2": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "img-orphan": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "style1": {},
    }
    plan = AssemblyPlan(
        kept=(13,), ordinals={13: 1},
        fits={13: {("image", 0): Rect(0, 0, 100, 100), ("image", 1): Rect(0, 0, 100, 100)}},
        deletes={}, clips={}, text_sizes={}, autosize={}, warnings=(),
    )
    captured: dict = {}
    stroke = _stroke_census_harness(objects, plan, captured=captured)

    assert captured["grants"]["style1"] == {
        "width": 5.0, "color": (1.0, 1.0, 1.0, 1.0), "pattern": "TSDSolidPattern"
    }
    assert stroke["orphan_refs"] == {"style1": 1}
    assert "media_refused" not in stroke


def test_restore_stroke_treats_a_drawable_shared_with_a_template_slide_as_an_escape():
    """`img1` is reachable both from the kept slide's `drawablesZOrder` and from a
    template `KN.SlideArchive` (outside the show's slide tree, so layout/master
    reachable) -- a mixed retained/escaping placement. It must never enter the retained
    set for minting; the style is minted for `img2` alone."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}, {"identifier": "img2"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "img2": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "template_slide": {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "img1"}]},
        "style1": {},
    }
    plan = AssemblyPlan(
        kept=(13,), ordinals={13: 1},
        fits={13: {("image", 0): Rect(0, 0, 100, 100), ("image", 1): Rect(0, 0, 100, 100)}},
        deletes={}, clips={}, text_sizes={}, autosize={}, warnings=(),
    )
    captured: dict = {}
    stroke = _stroke_census_harness(objects, plan, captured=captured)

    assert "grants" not in captured
    assert "media_refused" not in stroke
    assert stroke["minted"]["style1"]["drawables"] == ["img2"]


def test_restore_stroke_mints_a_style_with_a_verified_layout_referrer():
    """The same orphan referrer, but reachable via a real `KN.SlideLayoutArchive`
    `drawablesZOrder` -- a genuine layout escape, not counted as an orphan -- is minted
    for the two genuine retained refs rather than refused."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}, {"identifier": "img2"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "img2": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "img-orphan": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "layout1": {"_pbtype": "KN.SlideLayoutArchive", "drawablesZOrder": [{"identifier": "img-orphan"}]},
        "style1": {},
    }
    plan = AssemblyPlan(
        kept=(13,), ordinals={13: 1},
        fits={13: {("image", 0): Rect(0, 0, 100, 100), ("image", 1): Rect(0, 0, 100, 100)}},
        deletes={}, clips={}, text_sizes={}, autosize={}, warnings=(),
    )
    captured: dict = {}
    stroke = _stroke_census_harness(objects, plan, captured=captured)

    assert "grants" not in captured
    assert "media_refused" not in stroke
    assert stroke["minted"]["style1"]["drawables"] == ["img1", "img2"]
    assert "orphan_refs" not in stroke


def test_restore_stroke_mints_a_style_with_a_verified_master_referrer_nested_in_a_group():
    """Same as the layout case, but the referrer is nested inside a `TSD.GroupArchive`
    that sits on a `KN.MasterSlideArchive` `drawablesZOrder` -- the reachability walk must
    recurse into group children, exactly like the slide walk; the style is still minted
    for the two genuine retained refs rather than refused."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}, {"identifier": "img2"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "img2": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "img-orphan": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "group1": {"_pbtype": "TSD.GroupArchive", "children": [{"identifier": "img-orphan"}]},
        "master1": {"_pbtype": "KN.MasterSlideArchive", "drawablesZOrder": [{"identifier": "group1"}]},
        "style1": {},
    }
    plan = AssemblyPlan(
        kept=(13,), ordinals={13: 1},
        fits={13: {("image", 0): Rect(0, 0, 100, 100), ("image", 1): Rect(0, 0, 100, 100)}},
        deletes={}, clips={}, text_sizes={}, autosize={}, warnings=(),
    )
    captured: dict = {}
    stroke = _stroke_census_harness(objects, plan, captured=captured)

    assert "grants" not in captured
    assert "media_refused" not in stroke
    assert stroke["minted"]["style1"]["drawables"] == ["img1", "img2"]
    assert "orphan_refs" not in stroke


def test_restore_stroke_grants_an_inherited_empty_pattern_style():
    """An inherited style resolves an empty pattern up the `super.parent` chain -- the
    grant classification is by the RESOLVED pattern, not by whether the child style
    carries its own stroke."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style-child"}},
        "style-child": {"super": {"parent": {"identifier": "style-parent"}}},
        "style-parent": {"mediaProperties": {"stroke": {
            "pattern": {"type": "TSDEmptyPattern"}, "width": 1.0,
            "color": {"r": 0.0, "g": 0.0, "b": 0.0, "a": 0.0},
        }}},
    }
    orig_load_deck = dsa._load_deck
    import obed_edom.iwa_write as iwa_write_mod

    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_patch_media = iwa_write_mod.patch_media_stroke
    captured: dict = {}
    try:
        dsa._load_deck = lambda path: (objects, {}, {})
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {}, "chosen": [], "notes": [], "out_selected": []
            }
        )

        def _fake_patch_media_stroke(deck, grants):
            captured["grants"] = grants
            return {"refused": False, "patched": [], "created": []}

        iwa_write_mod.patch_media_stroke = _fake_patch_media_stroke

        plan = AssemblyPlan(
            kept=(13,), ordinals={13: 1}, fits={13: {("image", 0): Rect(0, 0, 100, 100)}}, deletes={}, clips={},
            text_sizes={}, autosize={}, warnings=(),
        )
        warnings: list[str] = []
        stroke = dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.patch_media_stroke = orig_patch_media

    assert captured["grants"]["style-child"] == {
        "width": 5.0, "color": (1.0, 1.0, 1.0, 1.0), "pattern": "TSDSolidPattern"
    }
    assert "media_refused" not in stroke


def test_restore_stroke_restores_an_inherited_solid_pattern_width():
    """An inherited style resolving a real (solid) pattern must have its width restored
    -- divided by `canvas_scale` like an own stroke -- but written via `patch_media_stroke`
    (creating the child's own stroke) since `patch_stroke_widths` refuses inherited-only
    ids that carry no own stroke."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style-child"}},
        "style-child": {"super": {"parent": {"identifier": "style-parent"}}},
        "style-parent": {"mediaProperties": {"stroke": {
            "pattern": {"type": "TSDSolidPattern", "phase": 0.0, "count": 0,
                        "pattern": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]},
            "width": 0.25, "cap": "ButtCap", "join": "MiterJoin", "miterLimit": 4.0,
            "color": {"model": "rgb", "r": 0.0, "g": 0.0, "b": 0.0, "a": 1.0, "rgbspace": "srgb"},
        }}},
    }
    orig_load_deck = dsa._load_deck
    import obed_edom.iwa_write as iwa_write_mod

    orig_match = iwa_write_mod.match_card_stroke_styles
    orig_patch_media = iwa_write_mod.patch_media_stroke
    captured: dict = {}
    try:
        dsa._load_deck = lambda path: (objects, {}, {})
        iwa_write_mod.match_card_stroke_styles = (
            lambda out_styles, src_styles, *, canvas_scale, min_refs: {
                "widths": {}, "chosen": [], "notes": [], "out_selected": []
            }
        )

        def _fake_patch_media_stroke(deck, grants):
            captured["grants"] = grants
            return {"refused": False, "patched": [], "created": []}

        iwa_write_mod.patch_media_stroke = _fake_patch_media_stroke

        plan = AssemblyPlan(
            kept=(13,), ordinals={13: 1}, fits={13: {("image", 0): Rect(0, 0, 100, 100)}}, deletes={}, clips={},
            text_sizes={}, autosize={}, warnings=(),
        )
        warnings: list[str] = []
        # slideWidth 7680 -> canvas_scale = 1920 / 7680 = 0.25 -> 0.25 / 0.25 = 1.0.
        stroke = dsa._restore_stroke(
            Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, {"slideWidth": 7680.0}, 1, warnings, print
        )
    finally:
        dsa._load_deck = orig_load_deck
        iwa_write_mod.match_card_stroke_styles = orig_match
        iwa_write_mod.patch_media_stroke = orig_patch_media

    parent_stroke = objects["style-parent"]["mediaProperties"]["stroke"]
    expected = {**parent_stroke, "width": pytest.approx(1.0)}
    assert captured["grants"]["style-child"] == {"stroke_message": expected}
    assert "media_refused" not in stroke


# --------------------------------------------------------------------------
# _staged_retained_ids: the stroke pass compares STAGED
# post-delete/insert kindIndex against SOURCE plan.fits ids -- deletions renumber
# surviving siblings, and an inserted clip shifts movie indices.
# --------------------------------------------------------------------------
def test_staged_retained_ids_remaps_after_a_deletion_shift():
    # Source images 0 deleted; images 1, 2 kept -- staged as 0, 1.
    plan = AssemblyPlan(
        kept=(8,), ordinals={8: 1},
        fits={8: {("image", 1): Rect(0, 0, 1, 1), ("image", 2): Rect(0, 0, 1, 1)}},
        deletes={8: (("image", 0),)}, clips={}, text_sizes={}, autosize={}, warnings=(),
    )
    assert dsa._staged_retained_ids(8, plan) == {("image", 0), ("image", 1)}


def test_staged_retained_ids_retains_same_kind_item_after_hidden_placeholder():
    # Opus D2b review 1 finding 8 (C6 wiring): a delete-refused placeholder (Keynote's
    # HIDDEN marker) keeps ("text", 0) staged; a same-kind sibling scheduled to survive
    # ("text", 1)) must still rank one slot after it, not collide with it.
    plan = AssemblyPlan(
        kept=(13,), ordinals={13: 1},
        fits={13: {("text", 0): Rect(0, 0, 1, 1), ("text", 1): Rect(0, 0, 1, 1)}},
        deletes={13: (("text", 0),)}, clips={}, text_sizes={}, autosize={}, warnings=(),
    )
    assert dsa._staged_retained_ids(13, plan) == {("text", 0)}
    assert dsa._staged_retained_ids(13, plan, hidden=frozenset({("text", 0)})) == {("text", 0), ("text", 1)}


def test_merge_split_part_builds_dedupes_repeated_item_after_hidden_placeholder():
    # Opus D2b review 1 finding 8 (C6 wiring): a hidden placeholder (("text", 0)) shifts
    # every later staged text index by one. A short item genuinely repeated across both
    # split parts (("text", 2), staged as index 2 once the placeholder is accounted for)
    # must be recognised as the same item and deduped to a single build -- without
    # ``hidden`` its staged index falls outside the (mis-)computed rank list, so it is
    # never matched back to a source id and the surplus build is counted twice instead.
    r1 = Rect(0, 0, 1, 1)
    split_parts = (
        SplitPart(
            fits={("text", 1): r1, ("text", 2): r1}, deletes=(("text", 0),), text_sizes={},
            stacked_ids=frozenset({("text", 1)}),
        ),
        SplitPart(
            fits={("text", 1): r1, ("text", 2): r1}, deletes=(("text", 0),), text_sizes={},
            stacked_ids=frozenset({("text", 1)}),
        ),
    )
    plan = AssemblyPlan(
        kept=(17,), ordinals={17: 1}, fits={17: {}}, deletes={}, clips={},
        text_sizes={}, autosize={}, warnings=(), splits={17: split_parts},
    )
    badge_build = {
        "buildId": "b", "chunkIds": [], "chunkOrder": [], "chunkReferent": [],
        "kind": "text", "kindIndex": 2, "effect": "apple:fade-in", "animationType": "In",
        "identity": ("text", "badge"),
    }
    ordinal_recs = [(1, {"builds": [dict(badge_build)]}), (2, {"builds": [dict(badge_build)]})]

    merged_with_hidden = dsa._merge_split_part_builds(
        ordinal_recs, plan, 17, hidden=frozenset({("text", 0)})
    )
    assert merged_with_hidden == [badge_build], "the repeated badge must be deduped to one build"

    merged_without_hidden = dsa._merge_split_part_builds(ordinal_recs, plan, 17)
    assert merged_without_hidden == [badge_build, badge_build], (
        "without the hidden placeholder the staged index is miscomputed and the "
        "repeat is not recognised, doubling the build"
    )


def test_staged_retained_ids_places_inserted_clip_after_kept_movies():
    plan = AssemblyPlan(
        kept=(32,), ordinals={32: 1}, fits={32: {}},
        deletes={32: (("movie", 0),)}, clips={32: {("movie", 0): Path("/tmp/clip.mov")}},
        text_sizes={}, autosize={}, warnings=(),
    )
    assert dsa._staged_retained_ids(32, plan) == {("movie", 0)}


def test_staged_retained_ids_inserted_clip_after_a_kept_movie():
    plan = AssemblyPlan(
        kept=(5,), ordinals={5: 1}, fits={5: {("movie", 1): Rect(0, 0, 1, 1)}},
        deletes={}, clips={5: {("movie", 0): Path("/tmp/clip.mov")}},
        text_sizes={}, autosize={}, warnings=(),
    )
    assert dsa._staged_retained_ids(5, plan) == {("movie", 0), ("movie", 1)}


def test_staged_retained_ids_excludes_the_deleted_movie_before_ranking():
    # The classifier-fit wall filter still includes the visible movie being replaced --
    # plan.fits[32] carries movie 0 even though plan.deletes[32] deletes it. It must not
    # occupy a staged index that the inserted clip then reuses.
    plan = AssemblyPlan(
        kept=(32,), ordinals={32: 1},
        fits={32: {("movie", 0): Rect(0, 0, 1, 1), ("image", 3): Rect(0, 0, 1, 1)}},
        deletes={32: (("movie", 0),)}, clips={32: {("movie", 0): Path("/tmp/clip.mov")}},
        text_sizes={}, autosize={}, warnings=(),
    )
    assert dsa._staged_retained_ids(32, plan) == {("image", 0), ("movie", 0)}


def test_staged_retained_ids_group_child_traversal_unaffected_by_deletion():
    # A group child's own (kind, kindIndex) is addressed independently of a sibling
    # top-level deletion elsewhere on the slide; the group id itself must still rank.
    plan = AssemblyPlan(
        kept=(9,), ordinals={9: 1},
        fits={9: {("group", 0): Rect(0, 0, 1, 1), ("image", 2): Rect(0, 0, 1, 1)}},
        deletes={9: (("image", 0), ("image", 1))}, clips={},
        text_sizes={}, autosize={}, warnings=(),
        group_children={9: {0: [
            {"kind": "image", "kindIndex": 0, "autosize": False, "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "group_path": ()},
        ]}},
    )
    assert dsa._staged_retained_ids(9, plan) == {("group", 0), ("image", 0)}


def test_staged_retained_ids_reads_the_split_parts_own_fits_and_deletes():
    # A split slide's staged ranking must come from that part's own fits/deletes,
    # not the unsplit slide's -- otherwise part 1's staged indices are computed against
    # a fit set that still contains the other part's long box.
    plan = AssemblyPlan(
        kept=(17,), ordinals={17: 2}, fits={17: {("text", 1): Rect(0, 0, 1, 1), ("text", 2): Rect(0, 0, 1, 1)}},
        deletes={17: ()}, clips={}, text_sizes={}, autosize={}, warnings=(),
        parts={17: 2}, ordinal_to_number={2: 17, 3: 17},
        splits={17: (
            SplitPart(fits={("text", 1): Rect(0, 0, 1, 1)}, deletes=(("text", 2),), text_sizes={}),
            SplitPart(fits={("text", 2): Rect(0, 0, 1, 1)}, deletes=(("text", 1),), text_sizes={}),
        )},
    )
    assert dsa._staged_retained_ids(17, plan, part=0) == {("text", 0)}
    assert dsa._staged_retained_ids(17, plan, part=1) == {("text", 0)}


def test_cropped_image_keeps_source_file_name_for_stroke():
    # GW 21 shaped: fits={image0}, deletes={image0,1,2}; the crop id is deleted, but
    # the crop's re-insert must still rank as a retained staged image (finding 3).
    from obed_edom.dsk_plan import CropSpec

    spec = CropSpec(path=Path("/tmp/crop.jpg"), source_file_name="crop.jpg", px_box=(0, 0, 1, 1), visible=Rect(0, 0, 1, 1))
    plan = AssemblyPlan(
        kept=(21,), ordinals={21: 1}, fits={21: {("image", 0): Rect(0, 0, 1, 1)}},
        deletes={21: (("image", 0), ("image", 1), ("image", 2))}, clips={},
        text_sizes={}, autosize={}, warnings=(),
        crops={21: {("image", 0): spec}},
    )
    assert dsa._staged_retained_ids(21, plan) == {("image", 0)}


# --------------------------------------------------------------------------
# _verify_builds surplus tolerance: Keynote auto-attaches an
# apple:movie-start build to an inserted clip; tolerate it only on that clip's own
# slide and only for that clip's own filename.
# --------------------------------------------------------------------------
def test_verify_builds_tolerates_clip_auto_attached_movie_start(monkeypatch):
    from obed_edom import iwa_builds

    plan = AssemblyPlan(
        kept=(32,), ordinals={32: 1}, fits={32: {}}, deletes={32: (("movie", 0),)},
        clips={32: {("movie", 0): Path("/tmp/clip.mov")}}, text_sizes={}, autosize={}, warnings=(),
    )
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: {32: {"slideId": "s", "builds": [{
            "buildId": "b", "chunkIds": [], "chunkOrder": [], "chunkReferent": [],
            "kind": "movie", "kindIndex": 0, "effect": "apple:movie-start",
            "animationType": "In", "identity": ("movie", "source.mov"),
        }], "transition": None}}
        if "fw" in str(path) else {1: {"slideId": "o", "builds": [], "transition": _dissolve_transition(0.5)}},
    )
    monkeypatch.setattr(
        iwa_builds, "verify_builds",
        lambda src_by_number, out_by_number, slides=None: {
            "surplus": [{
                "slide": 32, "effect": "apple:movie-start", "animationType": "In",
                "identity": ("movie", "clip.mov"), "count": 1,
            }],
            "missing": [{
                "slide": 32, "effect": "apple:movie-start", "animationType": "In",
                "identity": ("movie", "source.mov"), "count": 1,
            }],
            "transitions": [], "order": [],
        },
    )
    warnings: list[str] = []
    builds = dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)
    assert builds["tolerated_surplus"] == [{
        "slide": 32, "effect": "apple:movie-start", "animationType": "In",
        "identity": ("movie", "clip.mov"), "count": 1,
    }]
    assert builds["tolerated_missing"] == [{
        "slide": 32, "effect": "apple:movie-start", "animationType": "In",
        "identity": ("movie", "source.mov"), "count": 1,
    }]


def test_verify_builds_tolerates_single_movie_start_surplus_without_a_paired_source_build(monkeypatch):
    """One auto-added apple:movie-start per inserted clip identity is tolerated
    regardless of whether a source build went missing (finding 4 fix)."""
    from obed_edom import iwa_builds

    plan = AssemblyPlan(
        kept=(32,), ordinals={32: 1}, fits={32: {}}, deletes={32: (("movie", 0),)},
        clips={32: {("movie", 0): Path("/tmp/clip.mov")}}, text_sizes={}, autosize={}, warnings=(),
    )
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: {32: {"slideId": "s", "builds": [], "transition": None}}
        if "fw" in str(path) else {1: {"slideId": "o", "builds": [], "transition": _dissolve_transition(0.5)}},
    )
    monkeypatch.setattr(
        iwa_builds, "verify_builds",
        lambda src_by_number, out_by_number, slides=None: {
            "surplus": [{
                "slide": 32, "effect": "apple:movie-start", "animationType": "In",
                "identity": ("movie", "clip.mov"), "count": 1,
            }],
            "missing": [], "transitions": [], "order": [],
        },
    )
    warnings: list[str] = []
    builds = dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)
    assert builds["tolerated_surplus"] == [{
        "slide": 32, "effect": "apple:movie-start", "animationType": "In",
        "identity": ("movie", "clip.mov"), "count": 1,
    }]


def test_verify_builds_refuses_surplus_movie_start_count_exceeding_source(monkeypatch):
    from obed_edom import iwa_builds

    plan = AssemblyPlan(
        kept=(32,), ordinals={32: 1}, fits={32: {}}, deletes={32: (("movie", 0),)},
        clips={32: {("movie", 0): Path("/tmp/clip.mov")}}, text_sizes={}, autosize={}, warnings=(),
    )
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: {32: {"slideId": "s", "builds": [{
            "buildId": "b", "chunkIds": [], "chunkOrder": [], "chunkReferent": [],
            "kind": "movie", "kindIndex": 0, "effect": "apple:movie-start",
            "animationType": "In", "identity": ("movie", "source.mov"),
        }], "transition": None}}
        if "fw" in str(path) else {1: {"slideId": "o", "builds": [], "transition": _dissolve_transition(0.5)}},
    )
    monkeypatch.setattr(
        iwa_builds, "verify_builds",
        lambda src_by_number, out_by_number, slides=None: {
            "surplus": [{
                "slide": 32, "effect": "apple:movie-start", "animationType": "In",
                "identity": ("movie", "clip.mov"), "count": 2,
            }],
            "missing": [{
                "slide": 32, "effect": "apple:movie-start", "animationType": "In",
                "identity": ("movie", "source.mov"), "count": 1,
            }],
            "transitions": [], "order": [],
        },
    )
    warnings: list[str] = []
    with pytest.raises(AssemblyRefusal, match="builds verify surplus"):
        dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)


def _movie_start_plan_and_src(monkeypatch, *, missing_count, surplus_count):
    from obed_edom import iwa_builds

    plan = AssemblyPlan(
        kept=(32,), ordinals={32: 1}, fits={32: {}}, deletes={32: (("movie", 0),)},
        clips={32: {("movie", 0): Path("/tmp/clip.mov")}}, text_sizes={}, autosize={}, warnings=(),
    )
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: {32: {"slideId": "s", "builds": [{
            "buildId": "b", "chunkIds": [], "chunkOrder": [], "chunkReferent": [],
            "kind": "movie", "kindIndex": 0, "effect": "apple:movie-start",
            "animationType": "In", "identity": ("movie", "source.mov"),
        }] * 2, "transition": None}}
        if "fw" in str(path) else {1: {"slideId": "o", "builds": [], "transition": _dissolve_transition(0.5)}},
    )
    monkeypatch.setattr(
        iwa_builds, "verify_builds",
        lambda src_by_number, out_by_number, slides=None: {
            "surplus": [{
                "slide": 32, "effect": "apple:movie-start", "animationType": "In",
                "identity": ("movie", "clip.mov"), "count": surplus_count,
            }],
            "missing": [{
                "slide": 32, "effect": "apple:movie-start", "animationType": "In",
                "identity": ("movie", "source.mov"), "count": missing_count,
            }],
            "transitions": [], "order": [],
        },
    )
    return plan


def test_verify_builds_refuses_movie_start_surplus_exceeding_the_missing_budget(monkeypatch):
    """Two source movie-start builds are available, but only 1 is reported missing -- the
    tolerated budget is `min(2, 1) == 1`, so a surplus of 2 must NOT be fully tolerated
    even though it fits under the source count alone."""
    plan = _movie_start_plan_and_src(monkeypatch, missing_count=1, surplus_count=2)
    warnings: list[str] = []
    with pytest.raises(AssemblyRefusal, match="builds verify surplus"):
        dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)


def test_verify_builds_tolerates_movie_start_surplus_within_the_missing_budget(monkeypatch):
    plan = _movie_start_plan_and_src(monkeypatch, missing_count=1, surplus_count=1)
    warnings: list[str] = []
    builds = dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)
    assert builds["tolerated_surplus"] == [{
        "slide": 32, "effect": "apple:movie-start", "animationType": "In",
        "identity": ("movie", "clip.mov"), "count": 1,
    }]


def test_verify_builds_refuses_movie_start_surplus_beyond_one_per_clip_even_at_the_full_source_count(monkeypatch):
    """Tolerance is capped at ONE auto-added movie-start per inserted clip identity,
    independent of how many source movie-starts were deleted (finding 4 fix) -- a
    surplus of 2 is refused even though 2 source builds went missing."""
    plan = _movie_start_plan_and_src(monkeypatch, missing_count=2, surplus_count=2)
    warnings: list[str] = []
    with pytest.raises(AssemblyRefusal, match="builds verify surplus"):
        dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)


def test_verify_builds_refuses_surplus_not_matching_the_clip_filename(monkeypatch):
    from obed_edom import iwa_builds

    plan = AssemblyPlan(
        kept=(32,), ordinals={32: 1}, fits={32: {}}, deletes={32: (("movie", 0),)},
        clips={32: {("movie", 0): Path("/tmp/clip.mov")}}, text_sizes={}, autosize={}, warnings=(),
    )
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: {32: {"slideId": "s", "builds": [], "transition": None}}
        if "fw" in str(path) else {1: {"slideId": "o", "builds": [], "transition": _dissolve_transition(0.5)}},
    )
    monkeypatch.setattr(
        iwa_builds, "verify_builds",
        lambda src_by_number, out_by_number, slides=None: {
            "surplus": [{
                "slide": 32, "effect": "apple:movie-start", "animationType": "In",
                "identity": ("movie", "other.mov"), "count": 1,
            }],
            "missing": [], "transitions": [], "order": [],
        },
    )
    warnings: list[str] = []
    with pytest.raises(AssemblyRefusal, match="builds verify surplus"):
        dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)


def test_verify_builds_refuses_clip_slide_whose_transition_write_silently_failed(monkeypatch):
    # Codex r1 finding 10 (round 2): a failed transition write leaves the source
    # magic-move transition untouched, which produces NO diff in `report["transitions"]`
    # (source == output). The old code only inspected that diff report, so this silent
    # failure passed unnoticed. `_verify_builds` must now independently read back every
    # clip slide's actual staged transition and refuse when it isn't the expected
    # dissolve, regardless of what the diff report says.
    from obed_edom import iwa_builds

    plan = AssemblyPlan(
        kept=(32,), ordinals={32: 1}, fits={32: {}}, deletes={32: (("movie", 0),)},
        clips={32: {("movie", 0): Path("/tmp/clip.mov")}}, text_sizes={}, autosize={}, warnings=(),
    )
    unchanged_magic_move = _magic_move_transition(1.0)
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: {32: {"slideId": "s", "builds": [], "transition": unchanged_magic_move}}
        if "fw" in str(path) else {1: {"slideId": "o", "builds": [], "transition": unchanged_magic_move}},
    )
    monkeypatch.setattr(
        iwa_builds, "verify_builds",
        lambda src_by_number, out_by_number, slides=None: {
            "surplus": [], "missing": [], "transitions": [], "order": [],
        },
    )
    warnings: list[str] = []
    with pytest.raises(AssemblyRefusal, match="not the expected dissolve"):
        dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)


def test_assemble_clips_inserted_returns_original_paths_not_deleted_staged_copies(tmp_path, monkeypatch):
    # New finding 4: `AssembleResult.clips_inserted` must return the caller's
    # normalised original clip mapping, not the `batch.work`-staged copies that
    # `_stage_unique_clips` makes for insertion (and that `LiveBatch` deletes on exit).
    fw_deck, out_path, payload, classes, decisions, _clips = _assemble_fixture(tmp_path)
    real_clip = tmp_path / "real-clip.mov"
    real_clip.write_bytes(b"clip")
    clips = {32: real_clip}
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")

    result = assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")

    assert result.clips_inserted == {32: {("movie", 0): real_clip}}


# --------------------------------------------------------------------------
# Nested group script emission: lock/relock at every level.
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Mixed-run autosize text: overflow read-back and --text-fit shrink.
# --------------------------------------------------------------------------
def test_plan_assembly_records_shrink_size_for_mixed_run_autosize_text(monkeypatch):
    text = _text_item(0, x=3000, y=0, w=0.0, h=100.0, runs=[{"size": 30.0}, {"size": 60.0}])
    slide = _slide(1, [text])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    deck = _raw_autosize_deck(monkeypatch, 0, x=3000, y=0, w=0.0)
    plan = plan_assembly(
        payload, [cls], decisions=decisions, band=BAND, clips={}, deck=deck, fw_deck="/tmp/does-not-matter.key",
    )
    assert ("text", 0) in plan.autosize.get(1, frozenset())
    assert 1 not in plan.text_sizes
    assert ("text", 0) in plan.shrink_text_sizes.get(1, {})
    fitted = plan.fits[1][("text", 0)]
    visible = dsa._intersect(dsa.item_rect(text), Rect(0.0, 0.0, *dsa.LW_WALL_SIZE))
    scale = fitted.w / visible.w if visible.w > 0 else fitted.h / visible.h
    assert plan.shrink_text_sizes[1][("text", 0)] == pytest.approx(60.0 * scale)


def test_plan_assembly_records_no_shrink_size_for_mixed_run_fixed_frame_text():
    text = _text_item(0, x=3000, y=0, w=300.0, h=100.0, runs=[{"size": 30.0}, {"size": 60.0}])
    slide = _slide(1, [text])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    assert ("text", 0) not in plan.autosize.get(1, frozenset())
    assert 1 not in plan.text_sizes
    assert ("text", 0) not in plan.shrink_text_sizes.get(1, {})


def test_slide_lines_emits_overflow_readback_for_autosize_text():
    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1},
        fits={1: {("text", 0): Rect(100.0, 200.0, 300.0, 50.0)}},
        deletes={1: ()}, clips={}, text_sizes={}, autosize={1: frozenset({("text", 0)})},
        warnings=(),
    )
    lines = dsa._slide_lines(plan, 1, 1)
    script = "\n".join(lines)
    assert 'log ("OBED" & tab & "1" & tab & "OVERFLOW" & tab & "text:0"' in script
    assert "set curH to (height of text item 1 of slide 1)" in script


def test_slide_lines_shrink_sets_size_from_max_run_size():
    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1},
        fits={1: {("text", 0): Rect(100.0, 200.0, 300.0, 50.0)}},
        deletes={1: ()}, clips={}, text_sizes={}, autosize={1: frozenset({("text", 0)})},
        warnings=(), shrink_text_sizes={1: {("text", 0): 42.5}},
    )
    warn_script = "\n".join(dsa._slide_lines(plan, 1, 1, text_fit="warn"))
    assert "set size of object text of theObj to 42.5" not in warn_script

    shrink_script = "\n".join(dsa._slide_lines(plan, 1, 1, text_fit="shrink"))
    assert "set size of object text of theObj to 42.5" in shrink_script


def test_slide_lines_non_cluster_autosize_text_writes_size_before_position():
    # L1: a plain top-level autosize text item (not a two-column cluster) must also
    # skip `set height` and write position last, after width and size.
    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1},
        fits={1: {("text", 0): Rect(100.0, 200.0, 300.0, 50.0)}},
        deletes={1: ()}, clips={}, text_sizes={1: {("text", 0): 42.0}},
        autosize={1: frozenset({("text", 0)})}, warnings=(),
    )
    lines = dsa._slide_lines(plan, 1, 1)
    start = lines.index("          set theObj to text item 1 of slide 1")
    block = lines[start:start + 12]
    assert not any("set height" in l for l in block)
    width_i = next(i for i, l in enumerate(block) if "set width" in l)
    size_i = next(i for i, l in enumerate(block) if "set size" in l)
    position_i = next(i for i, l in enumerate(block) if "set position" in l)
    assert width_i < size_i < position_i


def test_build_refit_script_non_cluster_autosize_text_writes_size_before_position(monkeypatch):
    item = _text_item(0, x=2000, y=0, w=0.0, h=300, runs=[{"size": 20.0}])
    slide = _slide(1, [item])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    deck = _raw_autosize_deck(monkeypatch, 0, x=2000, y=0, w=0.0)
    plan = plan_assembly(
        payload, [cls], decisions=decisions, band=BAND, clips={}, deck=deck, fw_deck="/tmp/does-not-matter.key",
    )
    assert ("text", 0) in plan.autosize[1]
    refits = {(1, 0): {("text", 0): TextRefit(Rect(43.0, 704.0, 1892.0, 200.0), run_sizes=44.0)}}
    script = build_refit_script(
        plan, refits, ordinals=plan.ordinals, scratch_path=Path("/tmp/scratch.key"),
        staging_path=Path("/tmp/staged.key"),
    )
    lines = script.splitlines()
    start = next(i for i, l in enumerate(lines) if "set theObj to text item 1 of slide 1" in l)
    block = lines[start:start + 12]
    assert not any("set height" in l for l in block)
    width_i = next(i for i, l in enumerate(block) if "set width" in l)
    size_i = next(i for i, l in enumerate(block) if "set size" in l)
    position_i = next(i for i, l in enumerate(block) if "set position" in l)
    assert width_i < size_i < position_i


def test_group_known_child_lines_locks_and_relocks_each_nested_level():
    group = _group_item(0, x=1920, y=0, w=400, h=200)
    slide = _slide(1, [group])
    slide["groupChildren"] = {
        0: [{
            "kind": "image", "kindIndex": 0, "autosize": False,
            "x": 1920.0, "y": 0.0, "w": 200.0, "h": 200.0, "group_path": (0,),
        }]
    }
    slide["groupChildText"] = {}
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    ordinal = plan.ordinals[1]
    assert f"image 1 of group 1 of group 1 of slide {ordinal}" in script
    assert "set theGroupObj to group 1 of slide" in script
    assert "if wasGroupLocked then set locked of theGroupObj to true" in script
    assert "set gObj1 to group 1 of group 1 of slide" in script
    assert "if gLocked1 then set locked of gObj1 to true" in script


# --------------------------------------------------------------------------
# CLI -- decision construction from argv.
# --------------------------------------------------------------------------
def test_cli_dsk_assemble_builds_decisions(tmp_path, monkeypatch):
    from obed_edom import cli

    source = tmp_path / "src.key"
    source.mkdir()
    monkeypatch.setattr(
        "obed_edom.offline_inspect.offline_wall_payload",
        lambda path, deck=None: {"slideWidth": 7680.0, "slideHeight": 1080.0, "slideCount": 100, "slides": []},
    )
    captured: dict = {}

    monkeypatch.setattr("obed_edom.dsk_movie_export._ffprobe", lambda _path: (1920, 1080, 24.0, 2.0))

    def fake_assemble_dsk_deck(
        src, out, *, decisions, reference_deck, clips, log, layout_policy, black_layout_names, import_layout_names, stroke_min_refs,
        text_fit, min_text_pt=24.0, allow_split=True, text_slide_words=10, crop_dir=None,
        no_image_crop=False, no_auto_anchor=False, no_dedupe=False, no_drop_panel_backdrop=False,
        split_overrides=None, rss_limit_bytes=None, no_pills=False, no_style=False, content_only=False,
        **_kwargs,
    ):
        captured["decisions"] = decisions
        captured["clips"] = clips
        captured["reference_deck"] = reference_deck
        captured["layout_policy"] = layout_policy
        captured["black_layout_names"] = black_layout_names
        captured["stroke_min_refs"] = stroke_min_refs
        captured["clip_sizes"] = _kwargs.get("clip_sizes")
        return AssembleResult(
            path=out,
            slides_kept=(13, 32),
            ordinals={13: 1, 32: 2},
            fits={},
            clips_inserted={},
            stroke={},
            zorder={},
            builds={},
            size_bytes=1,
            source_size_bytes=1,
            wall_s=0.1,
            warnings=(),
            movie_props={},
        )

    monkeypatch.setattr("obed_edom.dsk_assemble.assemble_dsk_deck", fake_assemble_dsk_deck)

    clip_path = tmp_path / "clip.mov"
    clip_path.write_bytes(b"fake-mov")

    rc = cli.main(
        [
            "dsk-assemble",
            str(source),
            "--out",
            str(tmp_path / "out.key"),
            "--slides",
            "13,32",
            "--include-side",
            "13",
            "--anchor",
            "32=left",
            "--clip",
            f"32={clip_path}",
            "--layout",
            "import",
            "--stroke-min-refs",
            "2",
        ]
    )

    assert rc == 0
    decisions = captured["decisions"]
    assert decisions[13].action == "in_deck"
    assert decisions[13].keep_side is True
    assert decisions[13].anchor == "auto"
    assert decisions[32].action == "both"
    assert decisions[32].keep_side is False
    assert decisions[32].anchor == "left"
    assert captured["clips"] == {32: clip_path}
    assert captured["layout_policy"] == "import"
    assert captured["black_layout_names"] == dsa.DEFAULT_TRANSPARENT_LAYOUT_NAMES
    assert captured["stroke_min_refs"] == 2
    assert captured["reference_deck"] is None
    assert captured["clip_sizes"] == {str(clip_path): (1920, 1080)}


def test_default_transparent_layout_names_aliases_dsk_live():
    from obed_edom import dsk_stage_export as dse

    assert dsa.DEFAULT_TRANSPARENT_LAYOUT_NAMES is dsk_live.DEFAULT_TRANSPARENT_LAYOUT_NAMES
    assert dse.DEFAULT_TRANSPARENT_LAYOUT_NAMES is dsk_live.DEFAULT_TRANSPARENT_LAYOUT_NAMES


def test_cli_dsk_assemble_layout_name_override(tmp_path, monkeypatch):
    from obed_edom import cli

    source = tmp_path / "src.key"
    source.mkdir()
    monkeypatch.setattr(
        "obed_edom.offline_inspect.offline_wall_payload",
        lambda path, deck=None: {"slideWidth": 7680.0, "slideHeight": 1080.0, "slideCount": 100, "slides": []},
    )
    captured: dict = {}

    def fake_assemble_dsk_deck(
        src, out, *, decisions, reference_deck, clips, log, layout_policy, black_layout_names, import_layout_names, stroke_min_refs,
        text_fit, min_text_pt=24.0, allow_split=True, text_slide_words=10, crop_dir=None,
        no_image_crop=False, no_auto_anchor=False, no_dedupe=False, no_drop_panel_backdrop=False,
        split_overrides=None, rss_limit_bytes=None, no_pills=False, no_style=False, content_only=False,
        **_kwargs,
    ):
        captured["black_layout_names"] = black_layout_names
        return AssembleResult(
            path=out, slides_kept=(13,), ordinals={13: 1}, fits={}, clips_inserted={}, stroke={}, zorder={}, builds={},
            size_bytes=1, source_size_bytes=1, wall_s=0.1, warnings=(), movie_props={},
        )

    monkeypatch.setattr("obed_edom.dsk_assemble.assemble_dsk_deck", fake_assemble_dsk_deck)
    rc = cli.main(
        [
            "dsk-assemble", str(source), "--out", str(tmp_path / "out.key"),
            "--slides", "13", "--layout-name", "Custom Blank",
        ]
    )
    assert rc == 0
    assert captured["black_layout_names"] == ("Custom Blank",)


# --------------------------------------------------------------------------
# CLI -- validation of canvas size and malformed --anchor/--clip values.
# --------------------------------------------------------------------------
def _cli_source(tmp_path, monkeypatch, *, wall=(7680.0, 1080.0)):
    from obed_edom import cli

    source = tmp_path / "src.key"
    source.mkdir()
    monkeypatch.setattr(
        "obed_edom.offline_inspect.offline_wall_payload",
        lambda path, deck=None: {
            "slideWidth": wall[0], "slideHeight": wall[1], "slideCount": 100, "slides": []
        },
    )
    monkeypatch.setattr(
        "obed_edom.dsk_assemble.assemble_dsk_deck",
        lambda *a, **k: pytest.fail("assemble_dsk_deck must not run for a rejected CLI call"),
    )
    return cli, source


def test_cli_dsk_assemble_rejects_non_wall_canvas(tmp_path, monkeypatch, capsys):
    cli, source = _cli_source(tmp_path, monkeypatch, wall=(3840.0, 1080.0))
    rc = cli.main(["dsk-assemble", str(source), "--out", str(tmp_path / "out.key"), "--slides", "13"])
    assert rc == 1
    assert "7680x1080" in capsys.readouterr().err


def test_cli_dsk_assemble_rejects_anchor_without_equals(tmp_path, monkeypatch, capsys):
    cli, source = _cli_source(tmp_path, monkeypatch)
    rc = cli.main(
        ["dsk-assemble", str(source), "--out", str(tmp_path / "out.key"), "--slides", "13", "--anchor", "13"]
    )
    assert rc == 1
    assert "expected SLIDE=anchor" in capsys.readouterr().err


def test_cli_dsk_assemble_rejects_bad_anchor_value(tmp_path, monkeypatch, capsys):
    cli, source = _cli_source(tmp_path, monkeypatch)
    rc = cli.main(
        [
            "dsk-assemble", str(source), "--out", str(tmp_path / "out.key"),
            "--slides", "13", "--anchor", "13=top",
        ]
    )
    assert rc == 1
    assert "anchor must be one of" in capsys.readouterr().err


def test_cli_dsk_assemble_rejects_anchor_slide_not_in_slides(tmp_path, monkeypatch, capsys):
    cli, source = _cli_source(tmp_path, monkeypatch)
    rc = cli.main(
        [
            "dsk-assemble", str(source), "--out", str(tmp_path / "out.key"),
            "--slides", "13", "--anchor", "32=left",
        ]
    )
    assert rc == 1
    assert "not in --slides" in capsys.readouterr().err


def test_cli_dsk_assemble_rejects_clip_path_not_mov(tmp_path, monkeypatch, capsys):
    cli, source = _cli_source(tmp_path, monkeypatch)
    not_mov = tmp_path / "clip.mp4"
    not_mov.write_bytes(b"x")
    rc = cli.main(
        [
            "dsk-assemble", str(source), "--out", str(tmp_path / "out.key"),
            "--slides", "32", "--clip", f"32={not_mov}",
        ]
    )
    assert rc == 1
    assert "must end with .mov" in capsys.readouterr().err


def test_cli_dsk_assemble_rejects_missing_clip_path(tmp_path, monkeypatch, capsys):
    cli, source = _cli_source(tmp_path, monkeypatch)
    rc = cli.main(
        [
            "dsk-assemble", str(source), "--out", str(tmp_path / "out.key"),
            "--slides", "32", "--clip", f"32={tmp_path / 'missing.mov'}",
        ]
    )
    assert rc == 1
    assert "does not exist" in capsys.readouterr().err


def test_cli_dsk_assemble_rejects_clip_slide_not_in_slides(tmp_path, monkeypatch, capsys):
    cli, source = _cli_source(tmp_path, monkeypatch)
    clip_path = tmp_path / "clip.mov"
    clip_path.write_bytes(b"x")
    rc = cli.main(
        [
            "dsk-assemble", str(source), "--out", str(tmp_path / "out.key"),
            "--slides", "13", "--clip", f"32={clip_path}",
        ]
    )
    assert rc == 1
    assert "not in --slides" in capsys.readouterr().err


def test_cli_dsk_assemble_rejects_slide_out_of_deck_bounds(tmp_path, monkeypatch, capsys):
    cli, source = _cli_source(tmp_path, monkeypatch)
    rc = cli.main(
        ["dsk-assemble", str(source), "--out", str(tmp_path / "out.key"), "--slides", "999"]
    )
    assert rc == 1
    assert "out of range" in capsys.readouterr().err


def test_cli_dsk_assemble_rejects_include_side_not_subset_of_slides(tmp_path, monkeypatch, capsys):
    cli, source = _cli_source(tmp_path, monkeypatch)
    rc = cli.main(
        [
            "dsk-assemble", str(source), "--out", str(tmp_path / "out.key"),
            "--slides", "13", "--include-side", "32",
        ]
    )
    assert rc == 1
    assert "not in --slides" in capsys.readouterr().err


def test_cli_dsk_assemble_rejects_missing_reference_deck(tmp_path, monkeypatch, capsys):
    cli, source = _cli_source(tmp_path, monkeypatch)
    rc = cli.main(
        [
            "dsk-assemble", str(source), "--out", str(tmp_path / "out.key"),
            "--slides", "13", "--reference-deck", str(tmp_path / "missing-ref.key"),
        ]
    )
    assert rc == 1
    assert "Reference deck not found" in capsys.readouterr().err


def test_cli_dsk_assemble_rejects_missing_layout_template(tmp_path, monkeypatch, capsys):
    cli, source = _cli_source(tmp_path, monkeypatch)
    monkeypatch.setattr("obed_edom.dsk_assemble.DEFAULT_LAYOUT_TEMPLATE", tmp_path / "no-template.key")
    rc = cli.main(
        ["dsk-assemble", str(source), "--out", str(tmp_path / "out.key"), "--slides", "13"]
    )
    assert rc == 1
    assert "Layout template not found" in capsys.readouterr().err


def test_restore_stroke_refuses_when_media_census_raises(monkeypatch):
    """The fail-closed census in `_restore_stroke` must refuse -- not raise or silently
    proceed -- when the per-slide collection helper (`derive_kind_index`) itself blows
    up. Neither `patch_stroke_widths` nor `patch_media_stroke` may be reached once the
    census has failed."""
    objects = {
        "show": {"_pbtype": "KN.ShowArchive", "slideTree": {"slides": [{"identifier": "node1"}]}},
        "node1": {"slide": {"identifier": "slide1"}, "isSkipped": False},
        "slide1": {"drawablesZOrder": [{"identifier": "img1"}]},
        "img1": {"_pbtype": "TSD.ImageArchive", "style": {"identifier": "style1"}},
        "style1": {},
    }
    def _boom(*args, **kwargs):
        raise RuntimeError("kind index blew up")

    monkeypatch.setattr(dsa, "derive_kind_index", _boom)

    plan = AssemblyPlan(
        kept=(13,), ordinals={13: 1}, fits={13: {("image", 0): Rect(0, 0, 100, 100)}}, deletes={}, clips={},
        text_sizes={}, autosize={}, warnings=(),
    )
    captured: dict = {}
    stroke = _stroke_census_harness(objects, plan, captured=captured)

    assert stroke["refused"] is True
    assert "census" in stroke["reason"]
    assert "grants" not in captured
    assert "widths" not in captured


# --------------------------------------------------------------------------
# Text slides: classification, band stretch, split, and merged build verify
# (content-rules-plan.md D4/D6/D7 -- steps 4, 6, 7). Font-dependent cases skip
# when the machine doesn't have the font (F9's own carve-out).
# --------------------------------------------------------------------------
def _require_font(name):
    if resolve_font_path(name) is None:
        pytest.skip(f"font not present on this machine: {name}")


_VERSE_1 = "For God so loved the world that he gave his only begotten Son"
_VERSE_2 = (
    "that whosoever believeth in him should not perish but have life "
    "everlasting amen and amen forevermore"
)


def _long_text_item(kind_index, text, *, x=2000, y=200, w=1800, h=300, font="AzoSans-Regular", size=70.0):
    item = _text_item(kind_index, x=x, y=y, w=w, h=h)
    item["text"] = text
    item["font"] = font
    item["size"] = size
    return item


def _badge_item(kind_index, *, x=2000, y=50, w=400, h=80):
    item = _text_item(kind_index, x=x, y=y, w=w, h=h)
    item["text"] = "Genesis 11"
    item["font"] = "AzoSans-Bold"
    item["size"] = 40.0
    return item


def test_text_slide_drops_media_keeps_badge():
    _require_font("AzoSans-Regular")
    text_item = _long_text_item(1, _VERSE_1)
    badge = _badge_item(0)
    image = _image_item(2, x=2500, y=300, w=800, h=400)
    slide = _slide(13, [text_item, badge, image])
    payload = _payload([slide])
    classes = [_classify(slide)]
    assert classes[0].is_text
    assert classes[0].long_text_ids == (("text", 1),)
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert ("image", 2) not in plan.fits[13]
    assert ("image", 2) in plan.deletes[13]
    assert ("text", 1) in plan.fits[13]
    assert ("text", 0) in plan.fits[13]


def test_text_slide_words_threaded_into_fit():
    _require_font("AzoSans-Regular")
    text_item = _long_text_item(1, _VERSE_1)
    image = _image_item(2, x=2500, y=300, w=800, h=400)
    slide = _slide(13, [text_item, image])
    payload = _payload([slide])
    classes = [_classify(slide, text_slide_words=30)]
    assert not classes[0].is_text
    assert ("image", 2) in classes[0].kept
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, text_slide_words=30)
    assert ("image", 2) in plan.fits[13]
    assert ("image", 2) not in plan.deletes[13]


def test_text_slide_box_stretches_to_band():
    _require_font("AzoSans-Regular")
    text_item = _long_text_item(1, _VERSE_1)
    slide = _slide(13, [text_item])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    rect = plan.fits[13][("text", 1)]
    assert rect.x == pytest.approx(BAND.x_min)
    assert rect.w == pytest.approx(BAND.width)
    assert plan.text_sizes[13][("text", 1)] <= text_item["size"] + 1e-6


def test_stacked_mixed_run_box_preserves_run_size_ratios():
    # A stacked mixed-run box must scale each run by t, not flatten to one size.
    _require_font("AzoSans-Regular")
    text = _VERSE_1
    split_at = 20
    runs = [
        {"text": text[:split_at], "size": 70.0},
        {"text": text[split_at:], "size": 85.0},
    ]
    item = _text_item(1, x=2000, y=200, w=1800, h=300, runs=runs)
    item["text"] = text
    item["font"] = "AzoSans-Regular"
    item["size"] = 70.0
    slide = _slide(13, [item])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    ranges = plan.run_sizes[13][("text", 1)]
    assert len(ranges) == 2
    assert ("text", 1) not in plan.text_sizes.get(13, {})
    sizes_by_range = sorted(ranges, key=lambda r: r[0])
    t = sizes_by_range[0][2] / 70.0
    assert sizes_by_range[1][2] == pytest.approx(85.0 * t, abs=1e-6)
    assert sizes_by_range[0] == (1, split_at, pytest.approx(70.0 * t))
    assert sizes_by_range[1] == (split_at + 1, len(text), pytest.approx(85.0 * t))

    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key")
    )
    assert f"set size of characters 1 thru {split_at} of object text of theObj to" in script
    assert f"set size of characters {split_at + 1} thru {len(text)} of object text of theObj to" in script
    # Overflow read-back still runs for a stacked box, even though it got a size write.
    assert 'OVERFLOW" & tab & "text:1"' in script


def test_stacked_box_uniform_run_size_differs_from_leading_size():
    # Runs cover the text uniformly at a size other than the item's own leading size --
    # the flat write must use the run size scaled by t, not the leading size scaled by t.
    _require_font("AzoSans-Regular")
    text = _VERSE_1
    runs = [{"text": text, "size": 85.0}]
    item = _text_item(1, x=2000, y=200, w=1800, h=300, runs=runs)
    item["text"] = text
    item["font"] = "AzoSans-Regular"
    item["size"] = 70.0
    slide = _slide(13, [item])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert ("text", 1) not in plan.run_sizes.get(13, {})

    baseline = _text_item(1, x=2000, y=200, w=1800, h=300, runs=None)
    baseline["text"] = text
    baseline["font"] = "AzoSans-Regular"
    baseline["size"] = 70.0
    baseline_slide = _slide(13, [baseline])
    baseline_payload = _payload([baseline_slide])
    baseline_classes = [_classify(baseline_slide)]
    baseline_plan = plan_assembly(
        baseline_payload, baseline_classes, decisions=decisions, band=BAND, clips={}
    )
    t = baseline_plan.text_sizes[13][("text", 1)] / 70.0

    assert plan.text_sizes[13][("text", 1)] == pytest.approx(85.0 * t, abs=1e-6)


def test_stacked_box_gap_in_run_coverage_preserves_source_sizing():
    # A run with size=None (no full per-run coverage) must not be silently flattened
    # to a whole-object write -- only offered under an explicit --text-fit shrink.
    _require_font("AzoSans-Regular")
    text = _VERSE_1
    split_at = 20
    runs = [
        {"text": text[:split_at], "size": 70.0},
        {"text": text[split_at:], "size": None},
    ]
    item = _text_item(1, x=2000, y=200, w=1800, h=300, runs=runs)
    item["text"] = text
    item["font"] = "AzoSans-Regular"
    item["size"] = 70.0
    slide = _slide(13, [item])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert ("text", 1) not in plan.run_sizes.get(13, {})
    assert ("text", 1) not in plan.text_sizes.get(13, {})
    assert ("text", 1) in plan.shrink_text_sizes.get(13, {})
    assert any("run ranges leave a gap" in w for w in plan.warnings)

    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key")
    )
    assert "set size of object text of theObj" not in script


def test_stacked_box_gap_in_run_coverage_at_t_ge_1_warns_of_flat_write_under_shrink():
    # Same coverage gap at t >= 1, but under --text-fit shrink the flat write still
    # happens -- the warning must say so, not claim source sizing is preserved.
    _require_font("AzoSans-Regular")
    text = _VERSE_1
    split_at = 20
    runs = [
        {"text": text[:split_at], "size": 70.0},
        {"text": text[split_at:], "size": None},
    ]
    item = _text_item(1, x=2000, y=200, w=1800, h=300, runs=runs)
    item["text"] = text
    item["font"] = "AzoSans-Regular"
    item["size"] = 70.0
    slide = _slide(13, [item])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, text_fit="shrink")
    assert ("text", 1) in plan.shrink_text_sizes.get(13, {})
    assert any(
        "flattening run sizes to the lead size under --text-fit shrink" in w and "box 1" in w
        for w in plan.warnings
    )
    assert not any("preserving source sizing" in w for w in plan.warnings)

    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"),
        text_fit="shrink",
    )
    assert "set size of object text of theObj to" in script


def _gw49_shaped_item(kind_index, *, x=2000, y=200, w=1800, h=300, split_at=20, size=150.0):
    # GW 49-shaped: a run-size coverage gap (mostly size=None) whose only remaining fit
    # needs t < 1.0 -- exercises text_fit threaded through to this path.
    text = _VERSE_1
    runs = [
        {"text": text[:split_at], "size": size},
        {"text": text[split_at:], "size": None},
    ]
    item = _text_item(kind_index, x=x, y=y, w=w, h=h, runs=runs)
    item["text"] = text
    item["font"] = "AzoSans-Regular"
    item["size"] = size
    return item


def test_unresolved_gap_below_t1_refuses_under_warn_text_fit():
    _require_font("AzoSans-Regular")
    item = _gw49_shaped_item(1)
    slide = _slide(13, [item])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {13: SlideDecision(13, "in_deck")}
    with pytest.raises(AssemblyRefusal, match=r"fit t=0\.\d\d < 1\.0"):
        plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, text_fit="warn")


def test_unresolved_gap_below_t1_flattens_lead_size_under_shrink_text_fit():
    _require_font("AzoSans-Regular")
    item = _gw49_shaped_item(1)
    slide = _slide(13, [item])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, text_fit="shrink")
    assert ("text", 1) not in plan.run_sizes.get(13, {})
    assert ("text", 1) not in plan.text_sizes.get(13, {})
    assert ("text", 1) in plan.shrink_text_sizes[13]
    assert plan.shrink_text_sizes[13][("text", 1)] == pytest.approx(123.0, abs=0.01)
    assert any(
        "flattening run sizes to the lead size under --text-fit shrink" in w and "box 1" in w
        for w in plan.warnings
    )

    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"),
        text_fit="shrink",
    )
    assert "set size of object text of theObj to" in script


def test_split_part_unresolved_gap_below_t1_refuses_under_warn_text_fit():
    _require_font("AzoSans-Regular")
    box1 = _gw49_shaped_item(1)
    box2 = _long_text_item(2, _VERSE_2, y=500, size=200.0)
    slide = _slide(17, [box1, box2])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {17: SlideDecision(17, "in_deck")}
    with pytest.raises(AssemblyRefusal, match=r"fit t=0\.\d\d < 1\.0"):
        plan_assembly(
            payload, classes, decisions=decisions, band=BAND, clips={}, text_fit="warn", min_text_pt=60.0,
        )


def test_split_part_unresolved_gap_below_t1_flattens_under_shrink_text_fit():
    _require_font("AzoSans-Regular")
    box1 = _gw49_shaped_item(1)
    box2 = _long_text_item(2, _VERSE_2, y=500, size=200.0)
    slide = _slide(17, [box1, box2])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {17: SlideDecision(17, "in_deck")}
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={}, text_fit="shrink", min_text_pt=60.0,
    )
    assert plan.parts.get(17) == 2
    assert ("text", 1) in plan.shrink_text_sizes[17]
    assert any(
        "flattening run sizes to the lead size under --text-fit shrink" in w and "box 1" in w
        for w in plan.warnings
    )


def test_gw49_plans_under_shrink_and_refuses_under_warn():
    # Read-only probe: GW 49's real run-size coverage gap with t < 1.0.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    if 49 not in by_number:
        pytest.skip("GW deck has no slide 49")
    decisions = {49: SlideDecision(49, "in_deck")}
    with pytest.raises(AssemblyRefusal):
        plan_assembly(
            payload, [by_number[49]], decisions=decisions, band=BAND, clips={}, runs=runs, text_fit="warn",
            all_classes=classes,
        )
    plan = plan_assembly(
        payload, [by_number[49]], decisions=decisions, band=BAND, clips={}, runs=runs, text_fit="shrink",
        all_classes=classes,
    )
    assert plan.shrink_text_sizes.get(49) or plan.splits.get(49)


def test_gw49_single_box_split_refuses_under_warn_naming_box_and_run():
    # S1/§2.1 step 2 (Codex's prescription): GW 49 has 4 of 5 runs with no resolved
    # size (83 chars) -- `_emitted_run_sizes` marks the whole box "unresolved" rather
    # than emitting the old 25.0pt (100 * 45/180) that skipped the unresolved runs and
    # picked a fallback from the one resolved run. Under warn this must refuse, naming
    # the box (and the first unresolved run) rather than write blind.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    if 49 not in by_number:
        pytest.skip("GW deck has no slide 49")
    decisions = {49: SlideDecision(49, "in_deck")}
    with pytest.raises(AssemblyRefusal, match=r"box.*run.*unresolved"):
        plan_assembly(
            payload, [by_number[49]], decisions=decisions, band=BAND, clips={}, runs=runs, text_fit="warn",
            all_classes=classes, fw_deck=GW_DECK, layout_policy="import",
        )


def test_gw49_single_box_split_flattens_to_45pt_lead_under_shrink():
    # Under shrink, every part of GW 49's split flattens to the slot's own 45pt lead --
    # never the old 25.0pt (100 * 45/180) that only ever saw the one resolved run.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    if 49 not in by_number:
        pytest.skip("GW deck has no slide 49")
    decisions = {49: SlideDecision(49, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[49]], decisions=decisions, band=BAND, clips={}, runs=runs, text_fit="shrink",
        all_classes=classes, fw_deck=GW_DECK, layout_policy="import",
    )
    parts = plan.splits.get(49)
    assert parts
    for part in parts:
        for sizes in list(part.text_sizes.values()) + list(part.run_sizes.values()):
            flat = (sizes,) if isinstance(sizes, float) else sizes
            for entry in flat:
                size = entry if isinstance(entry, float) else entry[2]
                assert size == pytest.approx(45.0)
    assert any(
        "run sizes unresolved" in w and "flattening" in w for w in plan.warnings
    )


def test_stacked_mixed_run_box_keeps_run_ranges_under_text_fit_shrink():
    # Shrink no longer flattens a stacked mixed-run box -- it writes the same
    # per-run ranges (scaled by the fit factor) as warn mode, since flattening it was
    # the one path that contradicted "source gives style".
    _require_font("AzoSans-Regular")
    text = _VERSE_1
    split_at = 20
    runs = [
        {"text": text[:split_at], "size": 70.0},
        {"text": text[split_at:], "size": 85.0},
    ]
    item = _text_item(1, x=2000, y=200, w=1800, h=300, runs=runs)
    item["text"] = text
    item["font"] = "AzoSans-Regular"
    item["size"] = 70.0
    slide = _slide(13, [item])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"),
        text_fit="shrink",
    )
    assert "set size of characters" in script


def test_john17_after_dedupe_does_not_overlap():
    _require_font("AzoSans-Regular")
    box1 = _long_text_item(1, _VERSE_1, y=100)
    box2 = _long_text_item(2, _VERSE_2, y=500)
    slide = _slide(17, [box1, box2])
    payload = _payload([slide])
    classes = [_classify(slide)]
    assert classes[0].long_text_ids == (("text", 1), ("text", 2))
    decisions = {17: SlideDecision(17, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    rect1 = plan.fits[17][("text", 1)]
    rect2 = plan.fits[17][("text", 2)]
    assert dsa._intersect(rect1, rect2) is None
    assert plan.parts.get(17, 1) == 1


# --------------------------------------------------------------------------
# Split (step 6).
# --------------------------------------------------------------------------
def test_no_split_when_fit_found():
    _require_font("AzoSans-Regular")
    box1 = _long_text_item(1, _VERSE_1, y=100)
    box2 = _long_text_item(2, _VERSE_2, y=500)
    slide = _slide(17, [box1, box2])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {17: SlideDecision(17, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.parts.get(17, 1) == 1
    assert 17 not in plan.splits


def test_split_ordinals_shift_following_slides():
    _require_font("AzoSans-Regular")
    s13 = _slide(13, [_long_text_item(1, _VERSE_1, y=100)])
    box1 = _long_text_item(1, _VERSE_1, y=100)
    box2 = _long_text_item(2, _VERSE_2, y=500)
    badge = _badge_item(0)
    s17 = _slide(17, [box1, box2, badge])
    s21 = _slide(21, [_long_text_item(1, _VERSE_1, y=100)])
    payload = _payload([s13, s17, s21])
    classes = [_classify(s13), _classify(s17), _classify(s21)]
    decisions = {n: SlideDecision(n, "in_deck") for n in (13, 17, 21)}
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={}, min_text_pt=66.0
    )
    assert plan.parts[17] == 2
    assert plan.ordinals == {13: 1, 17: 2, 21: 4}
    assert plan.ordinal_to_number == {1: 13, 2: 17, 3: 17, 4: 21}


def test_split_parts_one_long_box_each_keeps_badge():
    _require_font("AzoSans-Regular")
    box1 = _long_text_item(1, _VERSE_1, y=100)
    box2 = _long_text_item(2, _VERSE_2, y=500)
    badge = _badge_item(0)
    slide = _slide(17, [box1, box2, badge])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {17: SlideDecision(17, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, min_text_pt=66.0)
    assert plan.parts[17] == 2
    parts = plan.splits[17]
    assert len(parts) == 2
    part1, part2 = parts
    assert ("text", 1) in part1.fits and ("text", 2) not in part1.fits
    assert ("text", 2) in part2.fits and ("text", 1) not in part2.fits
    assert ("text", 0) in part1.fits and ("text", 0) in part2.fits
    assert ("text", 2) in part1.deletes
    assert ("text", 1) in part2.deletes


def test_split_parts_both_carry_the_badges_size_write():
    _require_font("AzoSans-Regular")
    box1 = _long_text_item(1, _VERSE_1, y=100)
    box2 = _long_text_item(2, _VERSE_2, y=500)
    badge = _badge_item(0)
    badge["runs"] = [{"text": badge["text"], "size": badge["size"]}]
    slide = _slide(17, [box1, box2, badge])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {17: SlideDecision(17, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, min_text_pt=66.0)
    from obed_edom.remap_keynote import _as_num

    unsplit_plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert unsplit_plan.parts.get(17, 1) == 1
    badge_size = unsplit_plan.text_sizes[17][("text", 0)]
    assert plan.text_sizes[17][("text", 0)] == badge_size
    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"),
        layout_policy="preserve",
    )
    write_line = f"set size of object text of theObj to {_as_num(badge_size)}"
    assert script.count(write_line) == 2
    assert "OVERFLOW\\ttext:0" not in script


def test_split_script_duplicates_in_descending_order():
    _require_font("AzoSans-Regular")
    box1 = _long_text_item(1, _VERSE_1, y=100)
    box2 = _long_text_item(2, _VERSE_2, y=500)
    s17 = _slide(17, [box1, box2])
    s21 = _slide(21, [_long_text_item(1, _VERSE_1, y=100)])
    payload = _payload([s17, s21])
    classes = [_classify(s17), _classify(s21)]
    decisions = {n: SlideDecision(n, "in_deck") for n in (17, 21)}
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={}, min_text_pt=66.0
    )
    assert plan.parts[17] == 2
    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"),
        layout_policy="preserve",
    )
    dup_line = "duplicate slide 1 to after slide 1 of theDoc"
    assert dup_line in script
    dup_idx = script.index(dup_line)
    slide21_write_idx = script.index('log ("OBED" & tab & "21"')
    assert dup_idx < slide21_write_idx


def test_split_script_duplicates_two_split_slides_in_descending_order():
    # Two split slides (13, 17): the higher base ordinal's duplicate must be emitted
    # first -- otherwise an already-emitted low-ordinal duplicate line shifts under it.
    _require_font("AzoSans-Regular")
    s13 = _slide(13, [_long_text_item(1, _VERSE_1, y=100), _long_text_item(2, _VERSE_2, y=500)])
    s17 = _slide(17, [_long_text_item(1, _VERSE_1, y=100), _long_text_item(2, _VERSE_2, y=500)])
    payload = _payload([s13, s17])
    classes = [_classify(s13), _classify(s17)]
    decisions = {n: SlideDecision(n, "in_deck") for n in (13, 17)}
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={}, min_text_pt=66.0
    )
    assert plan.parts[13] == 2
    assert plan.parts[17] == 2
    assert plan.ordinals[13] == 1
    assert plan.ordinals[17] == 3
    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"),
        layout_policy="preserve",
    )
    # Duplicate lines address PRE-duplication ordinals (one slide per kept number, in
    # keep order) -- 13 is base ordinal 1, 17 is base ordinal 2 -- not the post-split
    # `plan.ordinals` used for the geometry writes below.
    dup13_idx = script.index("duplicate slide 1 to after slide 1 of theDoc")
    dup17_idx = script.index("duplicate slide 2 to after slide 2 of theDoc")
    assert dup17_idx < dup13_idx


def test_split_refused_when_single_box_cannot_fit():
    _require_font("AzoSans-Regular")
    huge = " ".join(["lorem"] * 400)
    box1 = _long_text_item(1, huge, y=100)
    box2 = _long_text_item(2, _VERSE_2, y=500)
    slide = _slide(17, [box1, box2])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {17: SlideDecision(17, "in_deck")}
    with pytest.raises(AssemblyRefusal, match="does not fit the band even alone"):
        plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})


# --------------------------------------------------------------------------
# _verify_builds across split parts (step 7).
# --------------------------------------------------------------------------
def _dissolve_build(kind_index, identity):
    return {
        "buildId": f"b{kind_index}", "chunkIds": [], "chunkOrder": [], "chunkReferent": [],
        "kind": "text", "kindIndex": kind_index, "effect": "apple:dissolve character",
        "animationType": "In", "identity": identity,
    }


def test_verify_builds_merges_split_parts(monkeypatch):
    from obed_edom import iwa_builds

    src_builds = {17: {
        "slideId": "s",
        "builds": [_dissolve_build(1, ("text", "part one")), _dissolve_build(2, ("text", "part two"))],
        "transition": None,
    }}
    out_builds = {
        2: {"slideId": "o1", "builds": [_dissolve_build(0, ("text", "part one"))], "transition": None},
        3: {"slideId": "o2", "builds": [_dissolve_build(0, ("text", "part two"))], "transition": None},
    }
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: src_builds if "fw" in str(path) else out_builds,
    )

    plan = AssemblyPlan(
        kept=(17,), ordinals={17: 2}, fits={17: {}}, deletes={17: ()}, clips={}, text_sizes={},
        autosize={}, warnings=(), parts={17: 2}, ordinal_to_number={2: 17, 3: 17},
        splits={17: (
            SplitPart(fits={}, deletes=(("text", 2),), text_sizes={}),
            SplitPart(fits={}, deletes=(("text", 1),), text_sizes={}),
        )},
    )
    warnings: list[str] = []
    builds = dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)
    assert len(builds["out_rekeyed"][17]["builds"]) == 2
    assert builds["tolerated_missing"] == []
    assert builds["report"]["surplus"] == []


def test_verify_builds_sums_two_long_boxes_sharing_an_identity_key(monkeypatch):
    # Two split boxes with identical text share an (effect, animationType, identity)
    # key -- each part's own long box must still be summed, not merged to the common-key
    # max meant for a short item repeated across parts, or this spuriously refuses a
    # missing build. The two boxes have DISTINCT source ids (text:1, text:3), and each
    # part deletes the lower-index text:0 -- so the staged (post-delete) rank of each
    # long box is 0, not its raw source index. A classifier that compared raw source
    # ids to the output's staged kindIndex would never recognise either box as "long",
    # would fall through to the short-item max path, and would collapse the two builds
    # (which share an identity key) down to one instead of summing them.
    from obed_edom import iwa_builds

    shared = _dissolve_build(1, ("text", "shared verse"))
    src_builds = {17: {"slideId": "s", "builds": [shared, shared], "transition": None}}
    out_builds = {
        2: {"slideId": "o1", "builds": [_dissolve_build(0, ("text", "shared verse"))], "transition": None},
        3: {"slideId": "o2", "builds": [_dissolve_build(0, ("text", "shared verse"))], "transition": None},
    }
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: src_builds if "fw" in str(path) else out_builds,
    )

    plan = AssemblyPlan(
        kept=(17,), ordinals={17: 2}, fits={17: {}}, deletes={17: ()}, clips={}, text_sizes={},
        autosize={}, warnings=(), parts={17: 2}, ordinal_to_number={2: 17, 3: 17},
        splits={17: (
            SplitPart(
                fits={("text", 1): None}, deletes=(("text", 0), ("text", 3)), text_sizes={},
                stacked_ids=frozenset({("text", 1)}),
            ),
            SplitPart(
                fits={("text", 3): None}, deletes=(("text", 0), ("text", 1)), text_sizes={},
                stacked_ids=frozenset({("text", 3)}),
            ),
        )},
    )
    warnings: list[str] = []
    builds = dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)
    assert len(builds["out_rekeyed"][17]["builds"]) == 2
    assert builds["report"]["surplus"] == []
    assert builds["report"]["missing"] == []


def test_verify_builds_refuses_a_long_box_build_dropped_from_one_part(monkeypatch):
    # A box deleted in one part but kept in the other must still show its build in the
    # part that keeps it -- tolerating missing builds only for boxes deleted in every
    # part must not paper over a genuinely lost build on a surviving box.
    from obed_edom import iwa_builds

    src_builds = {17: {
        "slideId": "s",
        "builds": [_dissolve_build(1, ("text", "part one")), _dissolve_build(2, ("text", "part two"))],
        "transition": None,
    }}
    out_builds = {
        2: {"slideId": "o1", "builds": [_dissolve_build(0, ("text", "part one"))], "transition": None},
        3: {"slideId": "o2", "builds": [], "transition": None},
    }
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: src_builds if "fw" in str(path) else out_builds,
    )

    plan = AssemblyPlan(
        kept=(17,), ordinals={17: 2}, fits={17: {}}, deletes={17: ()}, clips={}, text_sizes={},
        autosize={}, warnings=(), parts={17: 2}, ordinal_to_number={2: 17, 3: 17},
        splits={17: (
            SplitPart(fits={}, deletes=(("text", 2),), text_sizes={}),
            SplitPart(fits={}, deletes=(("text", 1),), text_sizes={}),
        )},
    )
    warnings: list[str] = []
    with pytest.raises(AssemblyRefusal):
        dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)


def test_verify_builds_refuses_surplus_across_parts(monkeypatch):
    from obed_edom import iwa_builds

    src_builds = {17: {
        "slideId": "s", "builds": [_dissolve_build(1, ("text", "part one"))], "transition": None,
    }}
    out_builds = {
        2: {"slideId": "o1", "builds": [_dissolve_build(0, ("text", "part one"))], "transition": None},
        3: {"slideId": "o2", "builds": [_dissolve_build(0, ("text", "surplus"))], "transition": None},
    }
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: src_builds if "fw" in str(path) else out_builds,
    )

    plan = AssemblyPlan(
        kept=(17,), ordinals={17: 2}, fits={17: {}}, deletes={17: ()}, clips={}, text_sizes={},
        autosize={}, warnings=(), parts={17: 2}, ordinal_to_number={2: 17, 3: 17},
        splits={17: (
            SplitPart(fits={}, deletes=(), text_sizes={}),
            SplitPart(fits={}, deletes=(), text_sizes={}),
        )},
    )
    warnings: list[str] = []
    with pytest.raises(AssemblyRefusal, match="surplus"):
        dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)


def test_verify_builds_tolerates_badge_build_repeated_on_every_part(monkeypatch):
    # A build on a short item (badge) repeated on every part must be counted
    # once against the single source build, not refused as surplus.
    from obed_edom import iwa_builds

    src_builds = {17: {
        "slideId": "s", "builds": [_dissolve_build(0, ("text", "badge"))], "transition": None,
    }}
    out_builds = {
        2: {"slideId": "o1", "builds": [_dissolve_build(0, ("text", "badge"))], "transition": None},
        3: {"slideId": "o2", "builds": [_dissolve_build(0, ("text", "badge"))], "transition": None},
    }
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: src_builds if "fw" in str(path) else out_builds,
    )
    # Badge (text:5) is a genuine short item -- present in every part's own fits, so
    # its build key is recognised as "repeated" rather than summed as a per-part
    # one-off.
    plan = AssemblyPlan(
        kept=(17,), ordinals={17: 2}, fits={17: {}}, deletes={17: ()}, clips={}, text_sizes={},
        autosize={}, warnings=(), parts={17: 2}, ordinal_to_number={2: 17, 3: 17},
        splits={17: (
            SplitPart(fits={("text", 5): None}, deletes=(("text", 2),), text_sizes={}),
            SplitPart(fits={("text", 5): None}, deletes=(("text", 1),), text_sizes={}),
        )},
    )
    warnings: list[str] = []
    builds = dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)
    assert len(builds["out_rekeyed"][17]["builds"]) == 1
    assert builds["report"]["surplus"] == []


def test_verify_builds_tolerates_badge_build_repeated_twice_on_every_part(monkeypatch):
    # A source slide carrying two identical builds on a repeated short item
    # must merge to two, not collapse to one via first-occurrence dedupe -- that traded
    # a surplus refusal for a missing-build refusal.
    from obed_edom import iwa_builds

    badge = _dissolve_build(0, ("text", "badge"))
    src_builds = {17: {"slideId": "s", "builds": [badge, badge], "transition": None}}
    out_builds = {
        2: {"slideId": "o1", "builds": [badge, badge], "transition": None},
        3: {"slideId": "o2", "builds": [badge, badge], "transition": None},
    }
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: src_builds if "fw" in str(path) else out_builds,
    )
    # Badge (text:5) is a genuine short item -- present in every part's own fits, so
    # its build key is recognised as "repeated" rather than summed.
    plan = AssemblyPlan(
        kept=(17,), ordinals={17: 2}, fits={17: {}}, deletes={17: ()}, clips={}, text_sizes={},
        autosize={}, warnings=(), parts={17: 2}, ordinal_to_number={2: 17, 3: 17},
        splits={17: (
            SplitPart(fits={("text", 5): None}, deletes=(("text", 2),), text_sizes={}),
            SplitPart(fits={("text", 5): None}, deletes=(("text", 1),), text_sizes={}),
        )},
    )
    warnings: list[str] = []
    builds = dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)
    assert len(builds["out_rekeyed"][17]["builds"]) == 2
    assert builds["report"]["surplus"] == []
    assert builds["report"]["missing"] == []


def test_verify_builds_refuses_badge_build_surviving_only_one_part(monkeypatch):
    # A one-build badge repeated on every part but only actually carried by one of
    # them (counters [1, 0]) must not be summed to one and matched against the single
    # source build -- that would conceal the dropped build on the other part.
    from obed_edom import iwa_builds

    badge = _dissolve_build(0, ("text", "badge"))
    src_builds = {17: {"slideId": "s", "builds": [badge], "transition": None}}
    out_builds = {
        2: {"slideId": "o1", "builds": [badge], "transition": None},
        3: {"slideId": "o2", "builds": [], "transition": None},
    }
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: src_builds if "fw" in str(path) else out_builds,
    )
    # Badge (text:5) is present in every part's own fits -- a genuine short item, so
    # its build key is recognised as "repeated"; the [1, 0] split-count disagreement
    # must not be summed away.
    plan = AssemblyPlan(
        kept=(17,), ordinals={17: 2}, fits={17: {}}, deletes={17: ()}, clips={}, text_sizes={},
        autosize={}, warnings=(), parts={17: 2}, ordinal_to_number={2: 17, 3: 17},
        splits={17: (
            SplitPart(fits={("text", 5): None}, deletes=(("text", 2),), text_sizes={}),
            SplitPart(fits={("text", 5): None}, deletes=(("text", 1),), text_sizes={}),
        )},
    )
    warnings: list[str] = []
    with pytest.raises(AssemblyRefusal):
        dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)


# --------------------------------------------------------------------------
# S4 -- build policy on split boxes: planning refusal for a character/word-level
# build, and cloned-build multiplicity/identity-narrowing at verify time.
# --------------------------------------------------------------------------
def test_refuse_split_box_char_word_builds_names_box_and_effect():
    with pytest.raises(AssemblyRefusal, match=r"box 3.*apple:dissolve character"):
        dsa._refuse_split_box_char_word_builds(
            17, ("text", 3),
            {17: {"builds": [
                {"kind": "text", "kindIndex": 3, "effect": "apple:dissolve character", "animationType": "In"},
            ]}},
        )


def test_refuse_split_box_char_word_builds_matches_word_and_klnsparkle_suffixes():
    for effect in ("apple:dissolve word", "com.apple.iWork.Keynote.KLNSparkle"):
        with pytest.raises(AssemblyRefusal):
            dsa._refuse_split_box_char_word_builds(
                17, ("text", 3),
                {17: {"builds": [{"kind": "text", "kindIndex": 3, "effect": effect, "animationType": "In"}]}},
            )


def test_refuse_split_box_char_word_builds_ignores_other_boxes_and_whole_object_builds():
    dsa._refuse_split_box_char_word_builds(
        17, ("text", 3),
        {17: {"builds": [
            {"kind": "text", "kindIndex": 9, "effect": "apple:dissolve character", "animationType": "In"},
            {"kind": "text", "kindIndex": 3, "effect": "apple:dissolve", "animationType": "In"},
        ]}},
    )


def _char_window_split_part(part_no: int, kind_index: int, deletes: tuple, char_window: tuple) -> SplitPart:
    item_id = ("text", kind_index)
    return SplitPart(
        fits={item_id: Rect(0.0, 0.0, 100.0, 100.0)}, deletes=deletes, text_sizes={},
        stacked_ids=frozenset({item_id}), char_window=char_window, char_total=30,
    )


def test_verify_builds_char_window_split_clean_with_exactly_len_parts_copies(monkeypatch):
    from obed_edom import iwa_builds

    src_dissolve = {
        "buildId": "b0", "chunkIds": [], "chunkOrder": [], "chunkReferent": [],
        "kind": "text", "kindIndex": 1, "effect": "apple:dissolve", "animationType": "In",
        "identity": ("text", "whole box text here"),
    }
    src_builds = {17: {"slideId": "s", "builds": [src_dissolve], "transition": None}}
    part_texts = ["whole box", "box text", "text here"]
    out_builds = {
        2 + i: {
            "slideId": f"o{i}",
            "builds": [dict(src_dissolve, kindIndex=0, identity=("text", t))],
            "transition": None,
        }
        for i, t in enumerate(part_texts)
    }
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: src_builds if "fw" in str(path) else out_builds,
    )
    plan = AssemblyPlan(
        kept=(17,), ordinals={17: 2}, fits={17: {}}, deletes={17: ()}, clips={}, text_sizes={},
        autosize={}, warnings=(), parts={17: 3}, ordinal_to_number={2: 17, 3: 17, 4: 17},
        splits={17: tuple(_char_window_split_part(i, 1, (), (1, 10)) for i in range(3))},
    )
    warnings: list[str] = []
    builds = dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)
    assert len(builds["out_rekeyed"][17]["builds"]) == 3
    assert any("cloned build on split part" in w for w in warnings)


def _run_char_window_verify(out_builds_per_ordinal: list[list[dict]], monkeypatch, src_dissolve: dict):
    from obed_edom import iwa_builds

    src_builds = {17: {"slideId": "s", "builds": [src_dissolve], "transition": None}}
    out_builds = {
        2 + i: {"slideId": f"o{i}", "builds": builds_here, "transition": None}
        for i, builds_here in enumerate(out_builds_per_ordinal)
    }
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: src_builds if "fw" in str(path) else out_builds,
    )
    plan = AssemblyPlan(
        kept=(17,), ordinals={17: 2}, fits={17: {}}, deletes={17: ()}, clips={}, text_sizes={},
        autosize={}, warnings=(), parts={17: 3}, ordinal_to_number={2: 17, 3: 17, 4: 17},
        splits={17: tuple(_char_window_split_part(i, 1, (), (1, 10)) for i in range(3))},
    )
    warnings: list[str] = []
    return dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)


def test_verify_builds_char_window_split_mismatches_with_two_copies(monkeypatch):
    src_dissolve = {
        "buildId": "b0", "chunkIds": [], "chunkOrder": [], "chunkReferent": [],
        "kind": "text", "kindIndex": 1, "effect": "apple:dissolve", "animationType": "In",
        "identity": ("text", "whole box text here"),
    }
    part_texts = ["whole box", "box text"]
    per_ordinal = [[dict(src_dissolve, kindIndex=0, identity=("text", t))] for t in part_texts] + [[]]
    with pytest.raises(AssemblyRefusal, match="surplus"):
        _run_char_window_verify(per_ordinal, monkeypatch, src_dissolve)


def test_verify_builds_char_window_split_mismatches_with_four_copies(monkeypatch):
    src_dissolve = {
        "buildId": "b0", "chunkIds": [], "chunkOrder": [], "chunkReferent": [],
        "kind": "text", "kindIndex": 1, "effect": "apple:dissolve", "animationType": "In",
        "identity": ("text", "whole box text here"),
    }
    part_texts = ["whole box", "box text", "text here"]
    per_ordinal = [[dict(src_dissolve, kindIndex=0, identity=("text", t))] for t in part_texts]
    per_ordinal[0] = per_ordinal[0] * 2
    with pytest.raises(AssemblyRefusal, match="surplus"):
        _run_char_window_verify(per_ordinal, monkeypatch, src_dissolve)


def test_verify_builds_char_window_split_unrelated_identity_is_genuine_mismatch(monkeypatch):
    from obed_edom import iwa_builds

    src_dissolve = {
        "buildId": "b0", "chunkIds": [], "chunkOrder": [], "chunkReferent": [],
        "kind": "text", "kindIndex": 1, "effect": "apple:dissolve", "animationType": "In",
        "identity": ("text", "whole box text here"),
    }
    src_builds = {17: {"slideId": "s", "builds": [src_dissolve], "transition": None}}
    part_texts = ["whole box", "box text", "completely unrelated"]
    out_builds = {
        2 + i: {
            "slideId": f"o{i}",
            "builds": [dict(src_dissolve, kindIndex=0, identity=("text", t))],
            "transition": None,
        }
        for i, t in enumerate(part_texts)
    }
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: src_builds if "fw" in str(path) else out_builds,
    )
    plan = AssemblyPlan(
        kept=(17,), ordinals={17: 2}, fits={17: {}}, deletes={17: ()}, clips={}, text_sizes={},
        autosize={}, warnings=(), parts={17: 3}, ordinal_to_number={2: 17, 3: 17, 4: 17},
        splits={17: tuple(_char_window_split_part(i, 1, (), (1, 10)) for i in range(3))},
    )
    warnings: list[str] = []
    with pytest.raises(AssemblyRefusal):
        dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)


# --------------------------------------------------------------------------
# S5: single-box char-window split of a group-child verse -- the two group refusals
# (band-fit and slot-fit) are dropped for a SINGLE retained group-child box, and its
# cloned build is the GROUP's own build, not the child's.
# --------------------------------------------------------------------------
def _char_window_groupchild_split_part(kind_index: int, char_window: tuple) -> SplitPart:
    item_id = ("groupchild", 0, "text", kind_index)
    return SplitPart(
        fits={item_id: Rect(0.0, 0.0, 100.0, 100.0)}, deletes=(), text_sizes={},
        stacked_ids=frozenset({item_id}), char_window=char_window, char_total=30,
    )


def test_verify_builds_groupchild_char_window_split_clones_the_group_build(monkeypatch):
    # Finding 4: GW 5/54's real identity is ("group", "Matthew 18\n<full verse>") -- the
    # badge/heading child stays a stable prefix and only the verse child narrows. A
    # synthetic identity with no such badge prefix (the old fixture) misses the case
    # `_identity_is_narrowed_slice` must handle child-wise.
    from obed_edom import iwa_builds

    full_verse = "In whole box text here completely more"
    src_dissolve = {
        "buildId": "b0", "chunkIds": [], "chunkOrder": [], "chunkReferent": [],
        "kind": "group", "kindIndex": 0, "effect": "apple:dissolve", "animationType": "In",
        "identity": ("group", f"Matthew 18\n{full_verse}"),
    }
    src_builds = {17: {"slideId": "s", "builds": [src_dissolve], "transition": None}}
    part_texts = ["In whole box", "text here completely", "more"]
    out_builds = {
        2 + i: {
            "slideId": f"o{i}",
            "builds": [dict(src_dissolve, identity=("group", f"Matthew 18\n{t}"))],
            "transition": None,
        }
        for i, t in enumerate(part_texts)
    }
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: src_builds if "fw" in str(path) else out_builds,
    )
    plan = AssemblyPlan(
        kept=(17,), ordinals={17: 2}, fits={17: {}}, deletes={17: ()}, clips={}, text_sizes={},
        autosize={}, warnings=(), parts={17: 3}, ordinal_to_number={2: 17, 3: 17, 4: 17},
        splits={17: tuple(_char_window_groupchild_split_part(1, (1, 10)) for _ in range(3))},
    )
    warnings: list[str] = []
    builds = dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)
    assert len(builds["out_rekeyed"][17]["builds"]) == 3
    assert any("cloned build on split part" in w for w in warnings)


def test_verify_builds_groupchild_char_window_split_truncated_badge_refuses(monkeypatch):
    # Finding 2 (review 4): each part's badge child is truncated ("Matthew" instead of
    # "Matthew 18") while the verse child (the actual split target, index 1) narrows
    # legitimately -- the badge is not the designated split child, so the clone must be
    # refused and the resulting identity mismatch surfaces as a real build refusal.
    from obed_edom import iwa_builds

    full_verse = "In whole box text here completely more"
    src_dissolve = {
        "buildId": "b0", "chunkIds": [], "chunkOrder": [], "chunkReferent": [],
        "kind": "group", "kindIndex": 0, "effect": "apple:dissolve", "animationType": "In",
        "identity": ("group", f"Matthew 18\n{full_verse}"),
    }
    src_builds = {17: {"slideId": "s", "builds": [src_dissolve], "transition": None}}
    part_texts = ["In whole box", "text here completely", "more"]
    out_builds = {
        2 + i: {
            "slideId": f"o{i}",
            "builds": [dict(src_dissolve, identity=("group", f"Matthew\n{t}"))],
            "transition": None,
        }
        for i, t in enumerate(part_texts)
    }
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: src_builds if "fw" in str(path) else out_builds,
    )
    plan = AssemblyPlan(
        kept=(17,), ordinals={17: 2}, fits={17: {}}, deletes={17: ()}, clips={}, text_sizes={},
        autosize={}, warnings=(), parts={17: 3}, ordinal_to_number={2: 17, 3: 17, 4: 17},
        splits={17: tuple(_char_window_groupchild_split_part(1, (1, 10)) for _ in range(3))},
    )
    warnings: list[str] = []
    with pytest.raises(AssemblyRefusal):
        dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)


def test_merge_split_part_builds_selects_source_by_owner_not_effect_type_alone():
    # Finding 2 (review 4): two groups share (kind, effect, animationType) but have
    # different kindIndex/identity -- listing the OTHER group's build first in
    # ``src_builds`` must not steal the clone: the split group's own build (kindIndex 0,
    # the split's owner) is the only legitimate source, keyed by owner not merely
    # (kind, effect, animationType).
    full_verse = "In whole box text here completely more"
    split_dissolve = {
        "buildId": "b0", "chunkIds": [], "chunkOrder": [], "chunkReferent": [],
        "kind": "group", "kindIndex": 0, "effect": "apple:dissolve", "animationType": "In",
        "identity": ("group", f"Matthew 18\n{full_verse}"),
    }
    other_group_dissolve = {
        "buildId": "b1", "chunkIds": [], "chunkOrder": [], "chunkReferent": [],
        "kind": "group", "kindIndex": 1, "effect": "apple:dissolve", "animationType": "In",
        "identity": ("group", "Luke 5\nsome other unrelated verse entirely"),
    }
    src_builds = [other_group_dissolve, split_dissolve]
    part_texts = ["In whole box", "text here completely", "more"]
    ordinal_recs = [
        (2 + i, {"builds": [dict(split_dissolve, identity=("group", f"Matthew 18\n{t}"))]})
        for i, t in enumerate(part_texts)
    ]
    plan = AssemblyPlan(
        kept=(17,), ordinals={17: 2}, fits={17: {}}, deletes={17: ()}, clips={}, text_sizes={},
        autosize={}, warnings=(), parts={17: 3}, ordinal_to_number={2: 17, 3: 17, 4: 17},
        splits={17: tuple(_char_window_groupchild_split_part(1, (1, 10)) for _ in range(3))},
    )
    warnings: list[str] = []
    merged = dsa._merge_split_part_builds(
        ordinal_recs, plan, 17, src_builds=src_builds, warnings=warnings,
    )
    assert len(merged) == 3
    assert all(b["identity"] == split_dissolve["identity"] for b in merged)
    assert any("cloned build on split part" in w for w in warnings)


def test_identity_is_narrowed_slice_gw5_54_shaped_group_identity_child_wise():
    # Finding 4: a literal GW 5/54-shaped identity ("group", "Matthew 18\n<verse>") --
    # the unchanged badge child ("Matthew 18") must match exactly and only the verse
    # child may narrow, for the first, middle, and final part of a 3-way split.
    full_verse = "In the beginning was the Word and the Word was with God"
    src_identity = ("group", f"Matthew 18\n{full_verse}")
    first = ("group", "Matthew 18\nIn the beginning was the Word")
    middle = ("group", "Matthew 18\nthe Word was with")
    final = ("group", "Matthew 18\nwas with God")
    for part in (first, middle, final):
        assert dsa._identity_is_narrowed_slice(part, src_identity, split_child_index=1)

    # A changed badge child must refuse even if the verse child is a valid slice.
    wrong_badge = ("group", "Luke 5\nIn the beginning was the Word")
    assert not dsa._identity_is_narrowed_slice(wrong_badge, src_identity, split_child_index=1)

    # A verse "slice" that is not actually contained in the source verse must refuse.
    not_a_slice = ("group", "Matthew 18\nsomething not in the verse at all")
    assert not dsa._identity_is_narrowed_slice(not_a_slice, src_identity, split_child_index=1)

    # A different child count (badge dropped) must refuse rather than fall back to the
    # whole-string substring check.
    dropped_child = ("group", "In the beginning was the Word")
    assert not dsa._identity_is_narrowed_slice(dropped_child, src_identity, split_child_index=1)

    # Finding 2 (review 4): a truncated badge ("Matthew" vs "Matthew 18") alongside an
    # UNCHANGED verse child must refuse -- the badge (index 0) is not the designated
    # split child (index 1), so it may not narrow even though it is a substring.
    truncated_badge = ("group", f"Matthew\n{full_verse}")
    assert not dsa._identity_is_narrowed_slice(truncated_badge, src_identity, split_child_index=1)

    # Without a resolved split-child index, no group child may narrow at all -- an
    # unknown owner must never be treated as a safe slice.
    assert not dsa._identity_is_narrowed_slice(first, src_identity)


def test_refuse_split_box_char_word_builds_group_child_checks_the_groups_own_build():
    # S5: a groupchild box's cloneable build lives on the GROUP object -- a
    # character-level build on the group refuses splitting its child.
    builds = {1: {"builds": [{"kind": "group", "kindIndex": 0, "effect": "apple:sparkle character"}]}}
    with pytest.raises(AssemblyRefusal, match="groupchild 0:text:1"):
        dsa._refuse_split_box_char_word_builds(1, ("groupchild", 0, "text", 1), builds)


def test_refuse_split_box_char_word_builds_group_child_ignores_unrelated_group_and_whole_object():
    builds = {
        1: {"builds": [
            {"kind": "group", "kindIndex": 1, "effect": "apple:sparkle character"},
            {"kind": "group", "kindIndex": 0, "effect": "apple:dissolve"},
        ]}
    }
    dsa._refuse_split_box_char_word_builds(1, ("groupchild", 0, "text", 1), builds)


@pytest.mark.deck
def test_gw5_54_group_child_verse_splits_at_the_standard_slot():
    # Owner Q2/finding 3 + S5: GW 5/54's group-child verse used to refuse (grouped
    # verse text, band or slot). Piece S5 drops that refusal for the single-box case
    # -- both now split into the Verse Standard (Variation 2) slot, windows pinned to
    # the current pack (S2's height-budget pack over the run-aware spans).
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    expected = {5: [2, 2, 1], 54: [3, 2]}
    for number, expected_lines in expected.items():
        cls = by_number[number]
        decisions = {number: SlideDecision(number, "in_deck")}
        plan = plan_assembly(
            payload, [cls], decisions=decisions, band=BAND, clips={}, runs=runs,
            all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
        )
        assert number in plan.splits, f"slide {number}: expected a split"
        assert plan.layout_names[number] == "Verse Standard (Variation 2)"
        parts = plan.splits[number]
        assert len(parts) == len(expected_lines), f"slide {number}: part count"
        verse_id = cls.long_text_ids[0]
        assert verse_id[0] == "groupchild"
        _tag, g_ki, _c_kind, c_ki = verse_id
        c_info = payload["slides"][number - 1]["groupChildRuns"][g_ki][c_ki]
        full_text, font = c_info["text"], c_info["font"]
        for i, part in enumerate(parts):
            assert part.stacked_ids == frozenset({verse_id})
            start, end = part.char_window
            part_text = full_text[start - 1:end]
            lc = line_count(part_text, font, 45.0, slot.verse.w)
            assert lc == expected_lines[i], f"slide {number} part {i}: line count"
            assert lc <= 3
            assert part.fits[verse_id].x == pytest.approx(slot.verse.x)
            assert part.fits[verse_id].w == pytest.approx(slot.verse.w)
            assert part.fits[verse_id].y == pytest.approx(slot.verse.y)

        # Every part's emitted script addresses the same group-child object, orders
        # width -> size -> delete -> position, never sets height, and keeps the
        # child-then-group lock/unlock nesting.
        for part_no, part in enumerate(parts):
            ordinal = plan.ordinals[number] + part_no
            lines = dsa._slide_lines(plan, number, ordinal, part=part_no)
            text = "\n".join(lines)
            addr = f"text item {c_ki + 1} of group {g_ki + 1} of slide {ordinal}"
            assert f"set theObj to {addr}" in text
            assert f"set theGroupObj to group {g_ki + 1} of slide {ordinal}" in text
            w_idx = text.index("set width of theObj")
            size_idx = text.index("of object text of theObj to", w_idx)
            delete_idx = text.index("delete characters", size_idx)
            pos_idx = text.index("set position of theObj", delete_idx)
            assert w_idx < size_idx < delete_idx < pos_idx
            child_block_start = text.index(addr)
            child_block_end = text.index("if wasLocked then set locked of theObj to true", child_block_start)
            assert "set height of theObj" not in text[child_block_start:child_block_end]
            assert text.index("wasGroupLocked to true", 0, w_idx) is not None or "wasGroupLocked" in text


@pytest.mark.deck
def test_gw44_50_51_53_group_child_verse_unaffected_by_s5():
    # A/B vs pre-S5 behaviour: GW 44/50 (two-column, don't reach the split path) and
    # GW 51/53 (fit the slot without splitting) must be entirely unchanged by dropping
    # the two group split refusals -- they never reach the branches S5 touched.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {n: SlideDecision(n, "in_deck") for n in (44, 50, 51, 53)}
    plan = plan_assembly(
        payload, [by_number[n] for n in (44, 50, 51, 53)], decisions=decisions, band=BAND, clips={},
        runs=runs, all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
    )
    names = dsa.resolve_slide_layouts(payload, classes, plan)
    assert 44 not in plan.splits and 50 not in plan.splits
    assert 51 not in plan.splits and 53 not in plan.splits
    assert names[44] == "Point 3 Lines"
    assert names[50] == "Point 3 Lines"
    assert names[51] == "Verse Standard (Variation 2)"
    assert names[53] == "Verse Standard (Variation 2)"


def test_identity_is_narrowed_slice_accepts_contiguous_slice_rejects_unrelated():
    assert dsa._identity_is_narrowed_slice(("text", "box text"), ("text", "whole box text here"))
    assert dsa._identity_is_narrowed_slice(("group", "abc"), ("group", "abc"))
    assert not dsa._identity_is_narrowed_slice(("text", "unrelated"), ("text", "whole box text here"))
    assert not dsa._identity_is_narrowed_slice(("text", "x"), ("group", "x"))


# --------------------------------------------------------------------------
# placement by shape (D3/step 9, owner correction 2026-09-12) -- SlideDecision
# (anchor="auto") is the CLI's "operator gave no explicit --anchor" sentinel;
# plan_assembly derives the anchor from the union of the kept content rects --
# the same clip `fit_slide` uses, restricted to content -- not their
# count: a union w/h >= 2.5 (LW-dimension) centres the slide; otherwise 1-2
# squarish items go right, 3+ centre. Text and side panels never count.
# --------------------------------------------------------------------------
def test_single_content_item_right_aligned():
    slide = _slide(48, [_image_item(2, x=1954, y=27, w=1381, h=921)])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {48: SlideDecision(48, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    rect = plan.fits[48][("image", 2)]
    assert rect.x + rect.w == pytest.approx(BAND.x_max)
    assert plan.anchors[48] == "right"


def test_two_squarish_items_right_aligned():
    slide = _slide(24, [_image_item(0, x=1943, y=-14, w=504, h=1080), _image_item(1, x=3200, y=-14, w=504, h=1080)])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {24: SlideDecision(24, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[24] == "right"


def test_lw_dimension_item_centred():
    slide = _slide(32, [_movie_item(0, x=1920, y=0, w=3840, h=1080)])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {32: SlideDecision(32, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={32: Path("/tmp/clip.mov")})
    assert plan.anchors[32] == "centre"
    rect = plan.fits[32][("movie", 0)]
    assert rect.x + rect.w / 2.0 == pytest.approx((BAND.x_min + BAND.x_max) / 2.0)


def test_three_squarish_items_centred():
    slide = _slide(3, [
        _image_item(0, x=1500, y=0, w=500, h=500),
        _image_item(1, x=2000, y=0, w=500, h=500),
        _image_item(2, x=2500, y=0, w=500, h=500),
    ])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {3: SlideDecision(3, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[3] == "centre"


def test_lw_item_among_squarish_centres():
    slide = _slide(4, [
        _image_item(0, x=1500, y=0, w=500, h=500),
        _movie_item(1, x=1920, y=0, w=3840, h=1080),
    ])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {4: SlideDecision(4, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={4: Path("/tmp/clip.mov")})
    assert plan.anchors[4] == "centre"


def test_lw_aspect_boundary_2_5_centres():
    slide = _slide(40, [_image_item(0, x=2960, y=0, w=2000, h=800)])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {40: SlideDecision(40, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[40] == "centre"


def test_lw_aspect_boundary_2_49_does_not_centre():
    slide = _slide(41, [_image_item(0, x=2960, y=0, w=1990, h=800)])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {41: SlideDecision(41, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[41] == "right"


def test_three_items_with_one_lw_still_centred():
    slide = _slide(42, [
        _image_item(0, x=1500, y=0, w=500, h=500),
        _image_item(1, x=2000, y=0, w=500, h=500),
        _movie_item(2, x=1920, y=0, w=3840, h=1080),
    ])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {42: SlideDecision(42, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={42: Path("/tmp/clip.mov")})
    assert plan.anchors[42] == "centre"


def test_mixed_group_bbox_with_caption_centres():
    # A squarish photo (aspect 1.0) whose group bbox is widened by a caption strip to
    # an LW-dimension rect (w/h >= 2.5) centres on the strength of the group bbox, not
    # the media leaf alone (D3: "its measured rect is the group bbox, caption included").
    group = _group_item(0, x=1920, y=0, w=2600, h=1000)
    slide = _slide(43, [group])
    slide["groupChildSignature"] = {0: "image:photo.jpg\ntext:a wide caption strip"}
    slide["groupChildren"] = {
        0: [{"kind": "image", "kindIndex": 0, "x": 1920.0, "y": 0.0, "w": 1000.0, "h": 1000.0}]
    }
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {43: SlideDecision(43, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[43] == "centre"


def test_side_panel_item_excluded_from_placement_with_include_side():
    # GW 8 shaped: one centre item plus two kept side-panel images -- with
    # --include-side, the side pair must not push the anchor to centre or otherwise
    # change it purely because they were kept rather than dropped.
    centre = _image_item(0, x=1954, y=27, w=1381, h=921)
    side_l = _image_item(1, x=0, y=0, w=1920, h=1080)
    side_r = _image_item(2, x=5760, y=0, w=1920, h=1080)
    slide = _slide(44, [centre, side_l, side_r])
    payload = _payload([slide])
    classes = [_classify(slide, include_side=True)]
    decisions = {44: SlideDecision(44, "in_deck", anchor="auto", keep_side=True)}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[44] == "right"


def test_union_of_two_halves_diptych_centres():
    # GW 16 shape: two 1912x1080 halves side by side, each clipped aspect ~1.77 (below
    # 2.5), but their union is 3824x1080 (aspect ~3.55, LW-dimension) -- the union fix
    # (opus review 1, finding 1) centres this instead of right-flushing a two-up.
    left = _image_item(0, x=1920, y=0, w=1912, h=1080)
    right = _image_item(1, x=3832, y=0, w=1912, h=1080)
    slide = _slide(45, [left, right])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {45: SlideDecision(45, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[45] == "centre"


def test_text_and_picture_slide_stacks_full_band_width():
    """A text slide that also keeps a non-full-wall picture (a media group survives the
    text-slide media drop, unlike a bare image/movie) still stacks its long text boxes
    across the full band width, not narrowed to make room for the picture."""
    _require_helvetica()
    text_item = {
        "kind": "text", "kindIndex": 0, "x": 1920, "y": 0, "w": 3698.0, "h": 300.0,
        "text": " ".join(["word"] * 16), "font": "Helvetica", "size": 40.0,
    }
    picture = _group_item(0, x=5000, y=100, w=800, h=200)
    slide = _slide(13, [text_item, picture])
    slide["groupChildSignature"] = {0: "image:photo.jpg"}
    slide["groupChildren"] = {
        0: [{"kind": "image", "kindIndex": 0, "x": 5000.0, "y": 100.0, "w": 800.0, "h": 200.0}]
    }
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    long_rect = plan.fits[13][("text", 0)]
    assert long_rect.x == pytest.approx(BAND.x_min)
    assert long_rect.w == pytest.approx(BAND.width)


def test_explicit_anchor_overrides_auto():
    slide = _slide(48, [_image_item(2, x=1954, y=27, w=1381, h=921)])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {48: SlideDecision(48, "in_deck", anchor="left")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[48] == "left"
    assert plan.fits[48][("image", 2)].x == pytest.approx(BAND.x_min)


def _magic_move_transition(duration=1.0):
    return {"attributes": {"databaseEffect": "apple:magic-move", "databaseDuration": duration}}


def test_magic_move_chain_anchor_from_source_head_even_when_head_not_requested():
    # An 11->12 magic-move chain: requesting slide 12 alone must still anchor it from
    # slide 11's own content, even though 11 is not in this run's kept set (Codex r1
    # finding 3) -- chain topology comes from the full source build sequence.
    head_slide = _slide(11, [_image_item(0, x=1954, y=27, w=1381, h=921)])
    tail_image = _image_item(0, x=4702, y=15, w=645, h=92)
    tail_group = _group_item(0, x=4702, y=15, w=645, h=92)
    tail_slide = _slide(12, [tail_image, tail_group])
    tail_slide["groupChildSignature"] = {0: "image:photo.jpg\ntext:caption"}
    tail_slide["groupChildren"] = {
        0: [{"kind": "image", "kindIndex": 0, "x": 4702.0, "y": 15.0, "w": 645.0, "h": 92.0}]
    }
    payload = _payload([head_slide, tail_slide])
    classes = [_classify(head_slide), _classify(tail_slide)]
    decisions = {12: SlideDecision(12, "in_deck", anchor="auto")}
    builds = {
        11: {"slideId": "s11", "builds": [], "transition": _magic_move_transition()},
        12: {"slideId": "s12", "builds": [], "transition": None},
    }
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={}, builds=builds, all_classes=classes,
    )
    assert plan.chain_head[12] == 11
    assert plan.anchors[12] == "right"


def test_magic_move_chain_anchor_survives_excluded_middle_slide():
    # 11->12->13 chain; excluding 12 from this run must not break the chain -- 13 still
    # anchors from 11 (Codex r1 finding 3, test (b)).
    head_slide = _slide(11, [_image_item(0, x=1954, y=27, w=1381, h=921)])
    mid_slide = _slide(12, [_image_item(0, x=1954, y=27, w=1381, h=921)])
    tail_image = _image_item(0, x=4702, y=15, w=645, h=92)
    tail_group = _group_item(0, x=4702, y=15, w=645, h=92)
    tail_slide = _slide(13, [tail_image, tail_group])
    tail_slide["groupChildSignature"] = {0: "image:photo.jpg\ntext:caption"}
    tail_slide["groupChildren"] = {
        0: [{"kind": "image", "kindIndex": 0, "x": 4702.0, "y": 15.0, "w": 645.0, "h": 92.0}]
    }
    payload = _payload([head_slide, mid_slide, tail_slide])
    classes = [_classify(head_slide), _classify(mid_slide), _classify(tail_slide)]
    decisions = {
        11: SlideDecision(11, "in_deck", anchor="auto"),
        13: SlideDecision(13, "in_deck", anchor="auto"),
    }
    builds = {
        11: {"slideId": "s11", "builds": [], "transition": _magic_move_transition()},
        12: {"slideId": "s12", "builds": [], "transition": _magic_move_transition()},
        13: {"slideId": "s13", "builds": [], "transition": None},
    }
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={}, builds=builds, all_classes=classes,
    )
    assert plan.anchors[11] == "right"
    assert plan.chain_head[13] == 11
    assert plan.anchors[13] == "right"


def test_text_items_do_not_count_towards_placement():
    slide = _slide(48, [_image_item(2, x=1954, y=27, w=1381, h=921), _text_item(0, x=2000, y=900, w=400, h=100)])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {48: SlideDecision(48, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[48] == "right"


def test_text_only_group_does_not_count_towards_placement():
    # GW 5 shaped: image0 + a text-only badge group0 -- one content item, so "right".
    image = _image_item(0, x=1954, y=27, w=1381, h=921)
    badge = _group_item(0, x=4702, y=15, w=645, h=92)
    slide = _slide(5, [image, badge])
    slide["groupChildSignature"] = {0: "text:Matthew 18 19 Again, truly I tell you"}
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {5: SlideDecision(5, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[5] == "right"


def test_group_with_media_child_counts_towards_placement():
    image = _image_item(0, x=1954, y=27, w=1381, h=921)
    group = _group_item(0, x=4702, y=15, w=645, h=92)
    slide = _slide(6, [image, group])
    slide["groupChildSignature"] = {0: "image:photo.jpg\ntext:caption"}
    slide["groupChildren"] = {
        0: [{"kind": "image", "kindIndex": 0, "x": 4702.0, "y": 15.0, "w": 645.0, "h": 92.0}]
    }
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {6: SlideDecision(6, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[6] == "centre"


def test_group_shape_plus_text_badge_does_not_count_towards_placement():
    # GW 7/37 shaped: a rounded-rect badge behind text, no image leaf anywhere on the
    # slide -- zero content, so centre (not right, which the shape: leaf used to force).
    badge = _group_item(0, x=4702, y=15, w=645, h=92)
    slide = _slide(7, [badge])
    slide["groupChildSignature"] = {0: "shape:scalarPathSource:kTSDRoundedRectangle:525.9x98.4\ntext:Elohim (plural)"}
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {7: SlideDecision(7, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[7] == "centre"


def test_keep_side_content_anchor_clips_to_centre_panel():
    # A 3000x1000 item at x=1000 straddles the LW centre-panel boundary (panel is
    # [1920, 5760]). Even with keep_side=True, the anchor must clip against the
    # centre panel (2080x1000, aspect < 2.5), not the full wall (aspect 3.0) --
    # codex review 1, finding 1.
    item = _image_item(0, x=1000, y=0, w=3000, h=1000)
    slide = _slide(49, [item])
    payload = _payload([slide])
    classes = [_classify(slide, include_side=True)]
    decisions = {49: SlideDecision(49, "in_deck", anchor="auto", keep_side=True)}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[49] == "right"


def test_rotated_image_anchor_uses_transformed_aabb():
    # Production payload semantics (codex placement review 4): x/y is already the rotated
    # frame's AABB top-left, w/h is its UNROTATED size. A raw 400x1000 frame at (2220,0)
    # rotated 90 degrees has exact AABB (1920,300,1000,400) -- payload carries that AABB
    # top-left with the original 400x1000 size. Aspect 1000/400=2.5 is LW-dimension; the
    # old (unrotated-origin) reading would re-rotate the AABB point and miss the panel.
    item = _image_item(0, x=1920, y=300, w=400, h=1000)
    item["rotation"] = 90
    slide = _slide(50, [item])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {50: SlideDecision(50, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[50] == "centre"


def test_content_item_aabb_rotated_group_extent_is_still_correct():
    # Codex placement review 7, finding 1: a rotated top-level media group with
    # unresolved children never reaches `_content_anchor` in production (see
    # `test_rotated_media_only_group_refused_before_placement`) -- but
    # `_content_item_aabb`/`_content_visibles_by_kept` themselves must still compute the
    # right transformed extent for the cases that DO legitimately reach them (rotated
    # top-level images/movies). AABB top-left (2200,300) with unrotated 400x1000 stays
    # put; only the 1000x400 extent is derived.
    group = _group_item(0, x=2200, y=300, w=400, h=1000)
    group["rotation"] = 90
    visibles = dsa._content_visibles_by_kept([group], [("group", 0)])
    rect = visibles[("group", 0)]
    assert rect.x == pytest.approx(2200.0)
    assert rect.y == pytest.approx(300.0)
    assert rect.w == pytest.approx(1000.0)
    assert rect.h == pytest.approx(400.0)


def test_rotated_item_panel_edge_uses_exact_offline_payload_aabb():
    # codex placement review 4, finding 1's own worked example: a raw 400x1000 frame at
    # (2220,0) rotated 90 degrees. offline_inspect/_compose_record write that through
    # _frame_rect as AABB top-left (1920,300) with unrotated size (400,1000) -- exactly
    # on the centre panel's left edge (panel starts at x=1920). _content_item_aabb must
    # reproduce the exact AABB (1920,300,1000,400), not clip or shift it.
    item = _image_item(0, x=1920, y=300, w=400, h=1000)
    item["rotation"] = 90
    aabb = dsa._content_item_aabb(item)
    assert aabb.x == pytest.approx(1920.0)
    assert aabb.y == pytest.approx(300.0)
    assert aabb.w == pytest.approx(1000.0)
    assert aabb.h == pytest.approx(400.0)


def test_fractionally_rotated_masked_item_uses_extent_formula():
    # A masked image's payload w/h is already its D2 masked rect (iwa_geometry docstring:
    # "masked=mask rect"), still reported as an unrotated size at the AABB top-left --
    # same contract as an unmasked frame. A residual (non-90-snapped) rotation must still
    # derive its extents from w/h/rotation, not re-rotate x/y: exercise a threshold-typical
    # fractional angle (0.5 degrees) below the geometry layer's own snap gate.
    item = _image_item(0, x=1920, y=300, w=400, h=1000)
    item["rotation"] = 0.5
    aabb = dsa._content_item_aabb(item)
    theta = math.radians(0.5)
    expected_w = abs(400 * math.cos(theta)) + abs(1000 * math.sin(theta))
    expected_h = abs(400 * math.sin(theta)) + abs(1000 * math.cos(theta))
    assert aabb.x == pytest.approx(1920.0)
    assert aabb.y == pytest.approx(300.0)
    assert aabb.w == pytest.approx(expected_w)
    assert aabb.h == pytest.approx(expected_h)
    assert aabb.w != pytest.approx(400.0)
    assert aabb.h != pytest.approx(1000.0)


def test_exact_90_rotation_swaps_extents_without_float_residue():
    # Codex placement review 5, finding 1: sin/cos at exactly 90 degrees leaves float
    # residue (400x1000 rotated 90 -> 1000x400.00000000000006), whose aspect
    # 2.4999999999999996 falls just under the 2.5 LW threshold. An AABB at y=0 (unlike
    # the y=300 case elsewhere in this file, where intersection subtraction happens to
    # erase the residue) exposes it directly: assert the exact swap and that the anchor
    # still reads "centre".
    item = _image_item(0, x=1920, y=0, w=400, h=1000)
    item["rotation"] = 90
    aabb = dsa._content_item_aabb(item)
    assert aabb.x == 1920.0
    assert aabb.y == 0.0
    assert aabb.w == 1000.0
    assert aabb.h == 400.0
    slide = _slide(52, [item])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {52: SlideDecision(52, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[52] == "centre"


def test_rotated_item_crossing_side_panel_counts_by_transformed_aabb():
    # Codex placement review 6, finding 1 (fixing review 5 finding 2's incomplete repair):
    # a 400x1000 frame at x=1500 (left of the centre panel's x=1920 edge) rotated 90
    # degrees has transformed AABB (1500,y,1000,400), crossing into the centre panel by
    # 580pt. `dsk_plan._filter_kept_items`'s side-panel classifier (`_is_side_panel_item`)
    # must not pre-drop it via the unrotated frame -- it now measures the same
    # transformed AABB (`_content_item_aabb`) that `_content_visibles_by_kept` uses, so
    # the item is kept and anchors "right" whether or not side panels are kept
    # (`include_side` mirrors `keep_side`, matching the production `classify_deck` call).
    item = _image_item(0, x=1500, y=300, w=400, h=1000)
    item["rotation"] = 90
    for keep_side in (False, True):
        slide = _slide(53, [dict(item)])
        payload = _payload([slide])
        classes = [_classify(slide, include_side=keep_side)]
        assert ("image", 0) in classes[0].kept
        decisions = {53: SlideDecision(53, "in_deck", anchor="auto", keep_side=keep_side)}
        plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
        assert plan.anchors[53] == "right"
        visibles = dsa._content_visibles_by_kept(slide["items"], [("image", 0)])
        rect = visibles[("image", 0)]
        assert rect.x == pytest.approx(1920.0)
        assert rect.w == pytest.approx(580.0)
        assert rect.h == pytest.approx(400.0)


def test_rotated_top_level_group_refused_before_placement():
    # Codex placement review 5, finding 3: does a rotated top-level group ever reach
    # `_content_anchor` at all, or does `plan_assembly`'s own "nested/rotated/masked
    # group" refusal (children metadata missing) always catch it first? Measure through
    # the real production path -- `iwa_geometry.compose_geometry` for the group's
    # composed x/y/w/h, `iwa_runs._slide_group_child_text`/`_group_child_records` for the
    # same groupChildText/groupChildren the offline loader attaches -- rather than
    # hand-supplying an already-correct AABB the way `test_rotated_group_anchor_uses_-
    # transformed_aabb` above does.
    #
    # A rotated top-level group with a media child and a caption TEXT child composes
    # through `_compose_record`'s group-union branch (translation-only child union,
    # flagged "rotated-group") -- NOT the "AABB position + unrotated size" contract
    # `_content_item_aabb` assumes for frames. But `_group_child_records` refuses (returns
    # None) for ANY rotated group regardless of content, while `_slide_group_child_text`
    # still finds the caption leaf regardless of rotation -- so `has_text and children is
    # None` always fires first. See D3 in dsk_content_rules.plan.md for the fixed
    # invariant: rotated groups never reach anchoring at all, so `_content_anchor`/
    # `_content_item_aabb` need not (and cannot correctly) special-case them.
    from obed_edom.iwa_geometry import compose_geometry
    from obed_edom.iwa_runs import _group_child_records, _slide_group_child_text

    objects = {
        "500": {
            "_pbtype": "TSD.GroupArchive",
            "super": {"geometry": {
                "position": {"x": 2200.0, "y": 300.0},
                "size": {"width": 400.0, "height": 1000.0}, "angle": 90.0,
            }},
            "children": [{"identifier": "501"}, {"identifier": "502"}],
        },
        "501": {"_pbtype": "TSD.ImageArchive", "super": {"geometry": {
            "position": {"x": 0.0, "y": 0.0},
            "size": {"width": 400.0, "height": 700.0}, "angle": 0.0,
        }}},
        "502": {
            "_pbtype": "TSWP.ShapeInfoArchive", "ownedStorage": {"identifier": "600"},
            "super": {"geometry": {
                "position": {"x": 0.0, "y": 700.0},
                "size": {"width": 400.0, "height": 300.0}, "angle": 0.0,
            }},
        },
        "600": {"_pbtype": "TSWP.StorageArchive", "text": ["Caption"]},
    }
    slide_archive = {"drawablesZOrder": [{"identifier": "500"}]}
    records = compose_geometry(slide_archive, objects)
    assert records == [{
        "id": "500", "kind": "group", "kindIndex": 0,
        "x": 2200.0, "y": 300.0, "w": 400.0, "h": 1000.0, "text": "",
        "geom_source": "group-union", "needs_keynote": "rotated-group",
    }]
    group_child_text = _slide_group_child_text(slide_archive, objects, {})
    assert group_child_text == {0: "Caption"}
    assert _group_child_records(objects["500"], objects) is None

    group = _group_item(0, x=2200.0, y=300.0, w=400.0, h=1000.0)
    group["rotation"] = 90
    slide = _slide(54, [group])
    slide["groupChildSignature"] = {0: "image:photo.jpg\ntext:Caption"}
    slide["groupChildText"] = group_child_text
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {54: SlideDecision(54, "in_deck", anchor="auto")}
    with pytest.raises(AssemblyRefusal, match="nested/rotated/masked group"):
        plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})


def test_rotated_media_only_group_refused_before_placement():
    # Codex placement review 7, finding 1: the "nested/rotated/masked group" refusal
    # only fired on `has_text`, so a rotated group with an image/movie leaf and no text
    # child sailed past it into `_content_anchor`, which then used the group's blind
    # group-union geometry (not the AABB-position/unrotated-size contract
    # `_content_item_aabb` assumes) as if it were a valid content rect. Same rotated
    # group shape as `test_rotated_top_level_group_refused_before_placement` above but
    # with only an image child -- must refuse the same way.
    group = _group_item(0, x=2200.0, y=300.0, w=400.0, h=1000.0)
    group["rotation"] = 90
    slide = _slide(55, [group])
    slide["groupChildSignature"] = {0: "image:photo.jpg"}
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {55: SlideDecision(55, "in_deck", anchor="auto")}
    with pytest.raises(AssemblyRefusal, match="nested/rotated/masked group"):
        plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})


def test_group_has_media_missing_none_empty_signature():
    # codex review 1, finding 2: missing mapping entry, None, and "" are not content.
    assert dsa._group_has_media(None) is False
    assert dsa._group_has_media("") is False


def test_lone_unresolved_group_defaults_to_centre():
    # A single group with no signature entry at all (mapping miss) has zero proven
    # content, so the zero-content default of "centre" applies, not "right".
    group = _group_item(0, x=4702, y=15, w=645, h=92)
    slide = _slide(50, [group])
    slide["groupChildSignature"] = {}
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {50: SlideDecision(50, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[50] == "centre"


def test_no_auto_anchor_flag_forces_centre():
    slide = _slide(48, [_image_item(2, x=1954, y=27, w=1381, h=921)])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {48: SlideDecision(48, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, no_auto_anchor=True)
    assert plan.anchors[48] == "centre"


def test_lone_zero_area_item_defaults_to_centre():
    # codex review 2, finding 1: a single zero-width item is proven content_ids-wise
    # but has no positive-area rect, so the zero-content default of "centre" applies.
    item = _image_item(0, x=1954, y=27, w=0, h=921)
    slide = _slide(51, [item])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {51: SlideDecision(51, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[51] == "centre"


def test_valid_item_plus_degenerate_media_counts_by_positive_area_only():
    # codex review 2, finding 1: two zero-area media items must not push the count
    # to 3+; only the one squarish positive-area rect counts, so anchor is "right".
    valid = _image_item(0, x=1954, y=27, w=1381, h=921)
    degenerate_a = _image_item(1, x=4702, y=15, w=0, h=92)
    degenerate_b = _image_item(2, x=4702, y=200, w=645, h=0)
    slide = _slide(52, [valid, degenerate_a, degenerate_b])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {52: SlideDecision(52, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert plan.anchors[52] == "right"


# --------------------------------------------------------------------------
# deletes/refusals (step 10)
# --------------------------------------------------------------------------
def test_deletes_include_backdrop_duplicate_and_cropped(monkeypatch):
    from obed_edom.dsk_plan import CropSpec

    scrim = {"kind": "shape", "kindIndex": 0, "x": 951, "y": 0, "w": 3840, "h": 1080, "text": ""}
    badge = _text_item(0, x=2000, y=900, w=400, h=100)
    image = _image_item(0, x=1954, y=27, w=1381, h=921)
    slide = _slide(28, [scrim, badge, image])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {28: SlideDecision(28, "in_deck", anchor="auto")}

    fake_spec = CropSpec(path=Path("/tmp/fake.jpg"), source_file_name="fake.jpg", px_box=(0, 0, 1, 1), visible=Rect(0, 0, 1, 1))
    monkeypatch.setattr(dsa, "plan_crops", lambda *a, **k: ({("image", 0): fake_spec}, [], ()))
    monkeypatch.setattr(dsa, "_slide_archive_for_number", lambda objects, number: {})
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={},
        deck=({}, {}, {}), fw_deck="/tmp/does-not-matter.key",
    )
    assert ("shape", 0) in plan.deletes[28]
    assert ("image", 0) in plan.deletes[28]
    assert plan.crops[28][("image", 0)] is fake_spec


def test_plan_assembly_loads_deck_itself_when_deck_is_none(monkeypatch):
    from obed_edom.dsk_plan import CropSpec

    fake_spec = CropSpec(path=Path("/tmp/fake.jpg"), source_file_name="fake.jpg", px_box=(0, 0, 1, 1), visible=Rect(0, 0, 1, 1))
    loaded: dict = {}

    def fake_load_deck(path):
        loaded["path"] = path
        return ({}, {}, {})

    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "plan_crops", lambda *a, **k: ({("image", 0): fake_spec}, [], ()))
    monkeypatch.setattr(dsa, "_slide_archive_for_number", lambda objects, number: {})
    image = _image_item(0, x=1954, y=27, w=1381, h=921)
    slide = _slide(5, [image])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {5: SlideDecision(5, "in_deck", anchor="auto")}
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={},
        deck=None, fw_deck="/tmp/does-not-matter.key", crop_dir=Path("/tmp/crops"),
    )
    assert loaded["path"] == "/tmp/does-not-matter.key"
    assert plan.crops[5][("image", 0)] is fake_spec


def test_refusal_cleans_up_pending_temp_files(tmp_path, monkeypatch):
    """A later slide's refusal must unlink an earlier slide's still-pending temp
    write; the final path, never having been touched, must not exist either."""
    from obed_edom.dsk_plan import CropRefusal, CropSpec

    temp_path = tmp_path / "3" / ".photo.jpg.tmp"
    temp_path.parent.mkdir(parents=True)
    temp_path.write_bytes(b"fake")
    final_path = tmp_path / "3" / "photo.jpg"
    fake_spec = CropSpec(path=final_path, source_file_name="photo.jpg", px_box=(0, 0, 1, 1), visible=Rect(0, 0, 1, 1))

    def fake_plan_crops(*a, **k):
        number = k.get("number")
        if number == 3:
            return ({("image", 0): fake_spec}, [], ((temp_path, final_path),))
        raise CropRefusal(f"slide {number} image 0: crop window under 8px")

    monkeypatch.setattr(dsa, "plan_crops", fake_plan_crops)
    monkeypatch.setattr(dsa, "_slide_archive_for_number", lambda objects, number: {})
    slide3 = _slide(3, [_image_item(0, x=1954, y=27, w=1381, h=921)])
    slide5 = _slide(5, [_image_item(0, x=1954, y=27, w=1381, h=921)])
    payload = _payload([slide3, slide5])
    classes = [_classify(slide3), _classify(slide5)]
    decisions = {
        3: SlideDecision(3, "in_deck", anchor="auto"),
        5: SlideDecision(5, "in_deck", anchor="auto"),
    }
    assert temp_path.exists()
    with pytest.raises(AssemblyRefusal):
        plan_assembly(
            payload, classes, decisions=decisions, band=BAND, clips={},
            deck=({}, {}, {}), fw_deck="/tmp/does-not-matter.key",
        )
    assert not temp_path.exists()
    assert not final_path.exists()


def test_commit_pending_crop_writes_unlinks_remaining_temps_on_mid_loop_failure(tmp_path, monkeypatch):
    """The second of three renames fails: the first final is already committed, the
    third temp must be unlinked rather than left orphaned, and the failure must
    surface as an `AssemblyRefusal` naming the failed path and what already committed."""
    pending = []
    for i in range(3):
        final_path = tmp_path / f"final{i}.jpg"
        temp_path = tmp_path / f"temp{i}.jpg"
        temp_path.write_bytes(b"crop")
        pending.append((temp_path, final_path))

    real_replace = dsa.os.replace

    def flaky_replace(src, dst):
        if str(src) == str(pending[1][0]):
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(dsa.os, "replace", flaky_replace)
    with pytest.raises(AssemblyRefusal, match=str(pending[1][1])):
        dsa._commit_pending_crop_writes(pending)

    assert pending[0][1].exists()
    assert not pending[0][0].exists()
    assert not pending[1][0].exists()
    assert not pending[1][1].exists()
    assert not pending[2][0].exists()
    assert not pending[2][1].exists()


def test_commit_pending_crop_writes_removes_empty_slide_directory_on_mid_loop_failure(tmp_path, monkeypatch):
    """Same mid-loop failure as above, but with each pending write in its own slide
    directory: the unaffected slides committed before the failure keep their dirs,
    but the third slide's dir -- never committed, only unlinked -- must not survive."""
    pending = []
    for i in range(3):
        slide_dir = tmp_path / str(i)
        slide_dir.mkdir()
        final_path = slide_dir / "final.jpg"
        temp_path = slide_dir / "temp.jpg"
        temp_path.write_bytes(b"crop")
        pending.append((temp_path, final_path))

    real_replace = dsa.os.replace

    def flaky_replace(src, dst):
        if str(src) == str(pending[1][0]):
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(dsa.os, "replace", flaky_replace)
    with pytest.raises(AssemblyRefusal, match=str(pending[1][1])):
        dsa._commit_pending_crop_writes(pending)

    assert (tmp_path / "0").exists()
    assert not (tmp_path / "1").exists()
    assert not (tmp_path / "2").exists()


def test_discard_pending_crop_writes_removes_empty_slide_directory(tmp_path):
    slide_dir = tmp_path / "5"
    slide_dir.mkdir()
    temp_path = slide_dir / ".photo.jpg.tmp"
    temp_path.write_bytes(b"crop")
    final_path = slide_dir / "photo.jpg"

    dsa._discard_pending_crop_writes([(temp_path, final_path)])

    assert not temp_path.exists()
    assert not slide_dir.exists()


def test_refusal_preserves_preexisting_final_file(tmp_path, monkeypatch):
    """A later slide's refusal must leave an earlier slide's crop *final* path
    untouched -- only the pending temp write is unlinked, never the final file."""
    from obed_edom.dsk_plan import CropRefusal, CropSpec

    final_path = tmp_path / "3" / "photo.jpg"
    final_path.parent.mkdir(parents=True)
    final_path.write_bytes(b"pre-existing")
    temp_path = tmp_path / "3" / ".photo.jpg.tmp"
    temp_path.write_bytes(b"fake-crop")
    fake_spec = CropSpec(
        path=final_path, source_file_name="photo.jpg", px_box=(0, 0, 1, 1), visible=Rect(0, 0, 1, 1),
    )

    def fake_plan_crops(*a, **k):
        number = k.get("number")
        if number == 3:
            return ({("image", 0): fake_spec}, [], ((temp_path, final_path),))
        raise CropRefusal(f"slide {number} image 0: crop window under 8px")

    monkeypatch.setattr(dsa, "plan_crops", fake_plan_crops)
    monkeypatch.setattr(dsa, "_slide_archive_for_number", lambda objects, number: {})
    slide3 = _slide(3, [_image_item(0, x=1954, y=27, w=1381, h=921)])
    slide5 = _slide(5, [_image_item(0, x=1954, y=27, w=1381, h=921)])
    payload = _payload([slide3, slide5])
    classes = [_classify(slide3), _classify(slide5)]
    decisions = {
        3: SlideDecision(3, "in_deck", anchor="auto"),
        5: SlideDecision(5, "in_deck", anchor="auto"),
    }
    with pytest.raises(AssemblyRefusal):
        plan_assembly(
            payload, classes, decisions=decisions, band=BAND, clips={},
            deck=({}, {}, {}), fw_deck="/tmp/does-not-matter.key",
        )
    assert final_path.read_bytes() == b"pre-existing"
    assert not temp_path.exists()


def test_plan_assembly_real_multi_slide_refusal_preserves_earlier_slide_bytes(tmp_path, monkeypatch):
    """Real (unmocked) `plan_crops`, driven through `plan_assembly`: slide 3 crops
    over a pre-existing file at its final path, slide 5's crop then genuinely
    refuses (crop window under `MIN_CROP_PX`) -- the pre-existing bytes at slide
    3's final path must survive untouched and no temp file may be left behind."""
    from PIL import Image
    import zipfile as _zipfile

    img = Image.new("RGB", (6000, 4000), "red")
    buf_path = tmp_path / "photo.jpg"
    img.save(buf_path, quality=95)

    key_path = tmp_path / "deck.key"
    with _zipfile.ZipFile(key_path, "w") as zf:
        zf.write(buf_path, "Data/photo-0.jpg")
        zf.write(buf_path, "Data/photo-1.jpg")

    # Slide 3: GW-3-shaped geometry that genuinely crops (see test_crop_box_from_frame_mask_and_lw).
    obj_a = {
        "super": {"geometry": {"position": {"x": 1920, "y": -981.6}, "size": {"width": 3840, "height": 2560}, "angle": 0.0}},
        "naturalSize": {"width": 6000, "height": 4000},
        "mask": {"identifier": "mask-a"},
        "data": {"identifier": "0"},
    }
    mask_a = {"geometry": {"position": {"x": 0, "y": 808}, "size": {"width": 3840, "height": 1472}, "angle": 0.0}}
    # Slide 5: same frame/naturalSize, but a mask sliver that clips to under 8px tall.
    obj_b = {
        "super": {"geometry": {"position": {"x": 1920, "y": -981.6}, "size": {"width": 3840, "height": 2560}, "angle": 0.0}},
        "naturalSize": {"width": 6000, "height": 4000},
        "mask": {"identifier": "mask-b"},
        "data": {"identifier": "1"},
    }
    mask_b = {"geometry": {"position": {"x": 0, "y": 978.6}, "size": {"width": 3840, "height": 6}, "angle": 0.0}}
    objects = {"imgA": obj_a, "mask-a": mask_a, "imgB": obj_b, "mask-b": mask_b}

    crop_dir = tmp_path / "crops"
    final_path = crop_dir / "3" / "photo-0.jpg"
    final_path.parent.mkdir(parents=True)
    final_path.write_bytes(b"pre-existing")

    def fake_slide_archive_for_number(objects, number):
        return {"which": "A" if number == 3 else "B"}

    def fake_item_object_ids(slide_archive, objects):
        return {("image", 0): "imgA"} if slide_archive.get("which") == "A" else {("image", 0): "imgB"}

    monkeypatch.setattr(dsa, "_slide_archive_for_number", fake_slide_archive_for_number)
    monkeypatch.setattr(dsk_plan, "_item_object_ids", fake_item_object_ids)

    image_a = _image_item(0, x=1954, y=27, w=1381, h=921)
    image_a["fileName"] = "photo-0.jpg"
    image_b = _image_item(0, x=1954, y=27, w=1381, h=921)
    image_b["fileName"] = "photo-1.jpg"
    slide3 = _slide(3, [image_a])
    slide5 = _slide(5, [image_b])
    payload = _payload([slide3, slide5])
    classes = [_classify(slide3), _classify(slide5)]
    decisions = {
        3: SlideDecision(3, "in_deck", anchor="auto"),
        5: SlideDecision(5, "in_deck", anchor="auto"),
    }

    with pytest.raises(AssemblyRefusal, match="crop window under"):
        plan_assembly(
            payload, classes, decisions=decisions, band=BAND, clips={},
            deck=(objects, {}, {}), fw_deck=key_path, crop_dir=crop_dir,
        )

    assert final_path.read_bytes() == b"pre-existing"
    assert [p for p in final_path.parent.iterdir()] == [final_path]


def test_plan_assembly_real_fw_deck_skips_text_only_slide(tmp_path, monkeypatch):
    """Real (unmocked) `plan_crops`, driven through `plan_assembly`, over a payload
    with a text-only slide next to an image slide -- the empty-`image_ids` branch
    of `plan_crops` must return a plan, not raise (regression for the 2-tuple
    early return that broke every slide with no kept image)."""
    from PIL import Image
    import zipfile as _zipfile

    img = Image.new("RGB", (6000, 4000), "red")
    buf_path = tmp_path / "photo.jpg"
    img.save(buf_path, quality=95)

    key_path = tmp_path / "deck.key"
    with _zipfile.ZipFile(key_path, "w") as zf:
        zf.write(buf_path, "Data/photo.jpg")

    obj = {
        "super": {"geometry": {"position": {"x": 1954, "y": 27}, "size": {"width": 1381, "height": 921}, "angle": 0.0}},
        "naturalSize": {"width": 6000, "height": 4000},
        "data": {"identifier": "0"},
    }
    objects = {"img": obj}

    def fake_slide_archive_for_number(objects, number):
        return {"which": "image" if number == 3 else "text"}

    def fake_item_object_ids(slide_archive, objects):
        return {("image", 0): "img"} if slide_archive.get("which") == "image" else {}

    monkeypatch.setattr(dsa, "_slide_archive_for_number", fake_slide_archive_for_number)
    monkeypatch.setattr(dsk_plan, "_item_object_ids", fake_item_object_ids)

    image = _image_item(0, x=1954, y=27, w=1381, h=921)
    image["fileName"] = "photo.jpg"
    slide3 = _slide(3, [image])
    slide5 = _slide(5, [_text_item(0, x=1920, y=0, w=1000, h=200, runs=[{"text": "hello"}])])
    payload = _payload([slide3, slide5])
    classes = [_classify(slide3), _classify(slide5)]
    decisions = {
        3: SlideDecision(3, "in_deck", anchor="auto"),
        5: SlideDecision(5, "in_deck", anchor="auto"),
    }

    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={},
        deck=(objects, {}, {}), fw_deck=key_path, crop_dir=tmp_path / "crops",
    )

    assert 5 not in plan.crops


def test_rotated_image_falls_back_through_plan_assembly(tmp_path, monkeypatch):
    from PIL import Image
    import zipfile as _zipfile

    img = Image.new("RGB", (6000, 4000), "red")
    buf_path = tmp_path / "photo.jpg"
    img.save(buf_path, quality=95)
    key_path = tmp_path / "deck.key"
    with _zipfile.ZipFile(key_path, "w") as zf:
        zf.write(buf_path, "Data/photo.jpg")

    obj = {
        "super": {"geometry": {
            "position": {"x": 1954, "y": 27}, "size": {"width": 1381, "height": 921}, "angle": 5.0,
        }},
        "naturalSize": {"width": 6000, "height": 4000},
        "data": {"identifier": "1"},
    }
    objects = {"img": obj}
    monkeypatch.setattr(dsk_plan, "_item_object_ids", lambda slide_archive, objects: {("image", 0): "img"})
    monkeypatch.setattr(dsa, "_slide_archive_for_number", lambda objects, number: {})

    image = {"kind": "image", "kindIndex": 0, "rotation": 0, "x": 1954, "y": 27, "w": 1381, "h": 921}
    slide = _slide(5, [image])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {5: SlideDecision(5, "in_deck", anchor="auto")}
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={},
        deck=(objects, {}, {}), fw_deck=key_path, crop_dir=tmp_path / "crops",
    )
    assert plan.crops == {}
    assert any("rotated" in w for w in plan.warnings)


def test_unconsumed_split_refusal_cleans_up_pending_temp_files(tmp_path, monkeypatch):
    from obed_edom.dsk_plan import CropSpec

    temp_path = tmp_path / "3" / ".photo.jpg.tmp"
    temp_path.parent.mkdir(parents=True)
    temp_path.write_bytes(b"fake")
    final_path = tmp_path / "3" / "photo.jpg"
    fake_spec = CropSpec(path=final_path, source_file_name="photo.jpg", px_box=(0, 0, 1, 1), visible=Rect(0, 0, 1, 1))

    monkeypatch.setattr(dsa, "plan_crops", lambda *a, **k: ({("image", 0): fake_spec}, [], ((temp_path, final_path),)))
    monkeypatch.setattr(dsa, "_slide_archive_for_number", lambda objects, number: {})
    slide3 = _slide(3, [_image_item(0, x=1954, y=27, w=1381, h=921)])
    payload = _payload([slide3])
    classes = [_classify(slide3)]
    decisions = {3: SlideDecision(3, "in_deck", anchor="auto")}
    assert temp_path.exists()
    with pytest.raises(AssemblyRefusal, match="does not apply"):
        plan_assembly(
            payload, classes, decisions=decisions, band=BAND, clips={},
            deck=({}, {}, {}), fw_deck="/tmp/does-not-matter.key",
            split_overrides={3: 2},
        )
    assert not temp_path.exists()
    assert not final_path.exists()


def test_unconsumed_split_refusal_preserves_preexisting_final_file(tmp_path, monkeypatch):
    from obed_edom.dsk_plan import CropSpec

    final_path = tmp_path / "3" / "photo.jpg"
    final_path.parent.mkdir(parents=True)
    final_path.write_bytes(b"fake")
    temp_path = tmp_path / "3" / ".photo.jpg.tmp"
    temp_path.write_bytes(b"fake-crop")
    fake_spec = CropSpec(
        path=final_path, source_file_name="photo.jpg", px_box=(0, 0, 1, 1), visible=Rect(0, 0, 1, 1),
    )

    monkeypatch.setattr(dsa, "plan_crops", lambda *a, **k: ({("image", 0): fake_spec}, [], ((temp_path, final_path),)))
    monkeypatch.setattr(dsa, "_slide_archive_for_number", lambda objects, number: {})
    slide3 = _slide(3, [_image_item(0, x=1954, y=27, w=1381, h=921)])
    payload = _payload([slide3])
    classes = [_classify(slide3)]
    decisions = {3: SlideDecision(3, "in_deck", anchor="auto")}
    with pytest.raises(AssemblyRefusal, match="does not apply"):
        plan_assembly(
            payload, classes, decisions=decisions, band=BAND, clips={},
            deck=({}, {}, {}), fw_deck="/tmp/does-not-matter.key",
            split_overrides={3: 2},
        )
    assert final_path.read_bytes() == b"fake"
    assert not temp_path.exists()


def test_crop_min_window_refuses(monkeypatch):
    from obed_edom.dsk_plan import CropRefusal

    def _raise(*a, **k):
        raise CropRefusal("slide 5 image 0: crop window under 8px")

    monkeypatch.setattr(dsa, "plan_crops", _raise)
    monkeypatch.setattr(dsa, "_slide_archive_for_number", lambda objects, number: {})
    slide = _slide(5, [_image_item(0, x=1954, y=27, w=1381, h=921)])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {5: SlideDecision(5, "in_deck", anchor="auto")}
    with pytest.raises(AssemblyRefusal):
        plan_assembly(
            payload, classes, decisions=decisions, band=BAND, clips={},
            deck=({}, {}, {}), fw_deck="/tmp/does-not-matter.key",
        )


def test_crop_insert_lines_match_clip_idiom(monkeypatch):
    from obed_edom.dsk_plan import CropSpec
    from obed_edom.dsk_assemble import build_assembly_script

    fake_spec = CropSpec(
        path=Path("/tmp/crops/3/photo.jpg"), source_file_name="photo.jpg",
        px_box=(0, 0, 100, 100), visible=Rect(0, 0, 100, 100),
    )
    image = _image_item(0, x=1954, y=27, w=1381, h=921)
    slide = _slide(3, [image])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {3: SlideDecision(3, "in_deck", anchor="auto")}
    monkeypatch.setattr(dsa, "plan_crops", lambda *a, **k: ({("image", 0): fake_spec}, [], ()))
    monkeypatch.setattr(dsa, "_slide_archive_for_number", lambda objects, number: {})
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={},
        deck=({}, {}, {}), fw_deck="/tmp/does-not-matter.key",
    )
    text = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/out.key"))
    assert 'make new image with properties {file:(POSIX file "/tmp/crops/3/photo.jpg") as alias}' in text
    assert "count of images of slide" in text
    assert "did not import" in text


def test_restore_crop_zorder_moves_cropped_image_to_source_index(tmp_path, monkeypatch):
    # GW-5-shaped: source z-order [imgS, grpS], imgS (the crop source) deleted -- the
    # re-inserted image (last in the out z-order) must move back to index 0.
    from obed_edom.dsk_plan import CropSpec
    import zipfile as _zipfile

    src_slide = {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "imgS"}, {"identifier": "grpS"}]}
    out_slide = {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "grpO"}, {"identifier": "imgO"}]}
    out_image = {"_pbtype": "TSD.ImageArchive", "data": {"identifier": "d1"}}
    src_objects = {"slideS": src_slide}
    out_objects = {"slideO": out_slide, "imgO": out_image, "grpO": {"_pbtype": "TSD.GroupArchive"}}

    def fake_load_deck(path):
        return (src_objects, {}, {}) if str(path) == "src.key" else (out_objects, {}, {})

    def fake_slide_order(objects):
        return [("slideS", False)] if objects is src_objects else [("slideO", False)]

    def fake_derive_kind_index(slide_archive, objects):
        if slide_archive is src_slide:
            return [
                {"id": "imgS", "kind": "image", "kindIndex": 0},
                {"id": "grpS", "kind": "group", "kindIndex": 0},
            ]
        return []

    out_path = tmp_path / "out.key"
    with _zipfile.ZipFile(out_path, "w"):
        pass

    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "slide_order", fake_slide_order)
    monkeypatch.setattr(dsa, "derive_kind_index", fake_derive_kind_index)
    monkeypatch.setattr(dsa, "_build_data_index", lambda names: {"d1": "photo.jpg"})
    monkeypatch.setattr(dsa, "_data_identifier", lambda obj: (obj.get("data") or {}).get("identifier"))

    spec = CropSpec(path=Path("/tmp/photo.jpg"), source_file_name="photo.jpg", px_box=(0, 0, 1, 1), visible=Rect(0, 0, 1, 1))
    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1}, fits={1: {}},
        deletes={1: (("image", 0),)}, clips={}, text_sizes={}, autosize={}, warnings=(),
        crops={1: {("image", 0): spec}},
    )

    captured: dict = {}

    def fake_reorder(out_path_arg, slide_id, moves):
        captured["slide_id"] = slide_id
        captured["moves"] = moves
        return {"refused": False}

    monkeypatch.setattr(dsa, "reorder_drawables", fake_reorder)

    warnings: list = []
    result = dsa._restore_crop_zorder("src.key", out_path, plan, warnings)
    assert captured["slide_id"] == "slideO"
    assert captured["moves"] == {"imgO": 0}
    assert result[1] == {"refused": False}
    assert warnings == []


def test_restore_crop_zorder_hidden_delete_still_counts_as_present(tmp_path, monkeypatch):
    # Opus D2b review 2 nit 3: a planned delete Keynote refused (a HIDDEN placeholder)
    # is still present in the output z-order, so it must not be counted as deleted when
    # computing the crop's target index -- same class of bug as C6, different function.
    from obed_edom.dsk_plan import CropSpec
    import zipfile as _zipfile

    src_slide = {
        "_pbtype": "KN.SlideArchive",
        "drawablesZOrder": [{"identifier": "shapeS"}, {"identifier": "imgS"}, {"identifier": "grpS"}],
    }
    out_slide = {"_pbtype": "KN.SlideArchive", "drawablesZOrder": [{"identifier": "grpO"}, {"identifier": "imgO"}]}
    out_image = {"_pbtype": "TSD.ImageArchive", "data": {"identifier": "d1"}}
    src_objects = {"slideS": src_slide}
    out_objects = {"slideO": out_slide, "imgO": out_image, "grpO": {"_pbtype": "TSD.GroupArchive"}}

    def fake_load_deck(path):
        return (src_objects, {}, {}) if str(path) == "src.key" else (out_objects, {}, {})

    def fake_slide_order(objects):
        return [("slideS", False)] if objects is src_objects else [("slideO", False)]

    def fake_derive_kind_index(slide_archive, objects):
        if slide_archive is src_slide:
            return [
                {"id": "shapeS", "kind": "shape", "kindIndex": 0},
                {"id": "imgS", "kind": "image", "kindIndex": 0},
                {"id": "grpS", "kind": "group", "kindIndex": 0},
            ]
        return []

    out_path = tmp_path / "out.key"
    with _zipfile.ZipFile(out_path, "w"):
        pass

    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "slide_order", fake_slide_order)
    monkeypatch.setattr(dsa, "derive_kind_index", fake_derive_kind_index)
    monkeypatch.setattr(dsa, "_build_data_index", lambda names: {"d1": "photo.jpg"})
    monkeypatch.setattr(dsa, "_data_identifier", lambda obj: (obj.get("data") or {}).get("identifier"))

    spec = CropSpec(path=Path("/tmp/photo.jpg"), source_file_name="photo.jpg", px_box=(0, 0, 1, 1), visible=Rect(0, 0, 1, 1))
    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1}, fits={1: {}},
        deletes={1: (("shape", 0), ("image", 0))}, clips={}, text_sizes={}, autosize={}, warnings=(),
        crops={1: {("image", 0): spec}},
    )

    captured: dict = {}

    def fake_reorder(out_path_arg, slide_id, moves):
        captured["moves"] = moves
        return {"refused": False}

    monkeypatch.setattr(dsa, "reorder_drawables", fake_reorder)

    warnings: list = []
    result = dsa._restore_crop_zorder(
        "src.key", out_path, plan, warnings, hidden={1: frozenset({("shape", 0)})}
    )
    assert captured["moves"] == {"imgO": 1}, "the hidden shape is still present, so the image belongs after it"
    assert result[1] == {"refused": False}
    assert warnings == []


def test_restore_crop_zorder_two_crops_compose_correctly(tmp_path, monkeypatch):
    # src_z = [A(image0, cropped), B(shape0, kept), C(image1, cropped)]. Both A and C
    # are deleted+replaced; computed against the SOURCE list, targets are A->0, C->1.
    # Applying naively in crop_specs (sorted-by-source-id) order would push B to the
    # top; applying in ascending target order must land [newA, B, newC].
    import zipfile as _zipfile
    from obed_edom.dsk_plan import CropSpec

    src_slide = {
        "_pbtype": "KN.SlideArchive",
        "drawablesZOrder": [{"identifier": "A"}, {"identifier": "B"}, {"identifier": "C"}],
    }
    out_slide = {
        "_pbtype": "KN.SlideArchive",
        "drawablesZOrder": [{"identifier": "B"}, {"identifier": "newA"}, {"identifier": "newC"}],
    }
    out_images = {
        "newA": {"_pbtype": "TSD.ImageArchive", "data": {"identifier": "dA"}},
        "newC": {"_pbtype": "TSD.ImageArchive", "data": {"identifier": "dC"}},
    }
    src_objects = {"slideS": src_slide}
    out_objects = {"slideO": out_slide, "B": {"_pbtype": "TSD.ShapeArchive"}, **out_images}

    def fake_load_deck(path):
        return (src_objects, {}, {}) if str(path) == "src.key" else (out_objects, {}, {})

    def fake_slide_order(objects):
        return [("slideS", False)] if objects is src_objects else [("slideO", False)]

    def fake_derive_kind_index(slide_archive, objects):
        return [
            {"id": "A", "kind": "image", "kindIndex": 0},
            {"id": "B", "kind": "shape", "kindIndex": 0},
            {"id": "C", "kind": "image", "kindIndex": 1},
        ]

    out_path = tmp_path / "out.key"
    with _zipfile.ZipFile(out_path, "w"):
        pass

    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "slide_order", fake_slide_order)
    monkeypatch.setattr(dsa, "derive_kind_index", fake_derive_kind_index)
    monkeypatch.setattr(dsa, "_build_data_index", lambda names: {"dA": "a.jpg", "dC": "c.jpg"})
    monkeypatch.setattr(dsa, "_data_identifier", lambda obj: (obj.get("data") or {}).get("identifier"))

    spec_a = CropSpec(path=Path("/tmp/a.jpg"), source_file_name="a.jpg", px_box=(0, 0, 1, 1), visible=Rect(0, 0, 1, 1))
    spec_c = CropSpec(path=Path("/tmp/c.jpg"), source_file_name="c.jpg", px_box=(0, 0, 1, 1), visible=Rect(0, 0, 1, 1))
    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1}, fits={1: {}},
        deletes={1: (("image", 0), ("image", 1))}, clips={}, text_sizes={}, autosize={}, warnings=(),
        crops={1: {("image", 0): spec_a, ("image", 1): spec_c}},
    )

    captured: dict = {}

    def fake_reorder(out_path_arg, slide_id, moves):
        captured["moves"] = moves
        # Mimic reorder_drawables' own sequential-application contract.
        order = list(out_slide["drawablesZOrder"])
        order = [str(ref["identifier"]) for ref in order]
        for did, idx in moves.items():
            order.remove(did)
            order.insert(idx, did)
        captured["final_order"] = order
        return {"refused": False}

    monkeypatch.setattr(dsa, "reorder_drawables", fake_reorder)

    warnings: list = []
    dsa._restore_crop_zorder("src.key", out_path, plan, warnings)
    assert captured["moves"] == {"newA": 0, "newC": 2}
    assert captured["final_order"] == ["newA", "B", "newC"]
    assert warnings == []


def test_split_and_crop_together_refuses(monkeypatch):
    from obed_edom.dsk_plan import CropSpec

    _require_font("AzoSans-Regular")
    fake_spec = CropSpec(path=Path("/tmp/fake.jpg"), source_file_name="fake.jpg", px_box=(0, 0, 1, 1), visible=Rect(0, 0, 1, 1))
    monkeypatch.setattr(dsa, "plan_crops", lambda *a, **k: ({("image", 0): fake_spec}, [], ()))
    monkeypatch.setattr(dsa, "_slide_archive_for_number", lambda objects, number: {})
    box1 = _long_text_item(1, _VERSE_1, y=100)
    box2 = _long_text_item(2, _VERSE_2, y=500)
    slide = _slide(17, [box1, box2])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {17: SlideDecision(17, "in_deck", anchor="auto")}
    with pytest.raises(AssemblyRefusal, match="split and image crop"):
        plan_assembly(
            payload, classes, decisions=decisions, band=BAND, clips={}, min_text_pt=66.0,
            deck=({}, {}, {}), fw_deck="/tmp/does-not-matter.key",
        )


def test_stage_unique_clips_gives_distinct_basenames_for_duplicate_source_names(tmp_path):
    # Two different source clips that happen to share a basename must be staged under
    # distinct basenames before insertion, so `_restore_clip_zorder` never has to
    # disambiguate a real collision (Codex r1 finding 5).
    src_dir_a = tmp_path / "a"
    src_dir_b = tmp_path / "b"
    src_dir_a.mkdir()
    src_dir_b.mkdir()
    clip_a = src_dir_a / "clip.mov"
    clip_b = src_dir_b / "clip.mov"
    clip_a.write_bytes(b"AAAA")
    clip_b.write_bytes(b"BBBB")

    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1}, fits={1: {}}, deletes={1: ()}, text_sizes={}, autosize={}, warnings=(),
        clips={1: {("movie", 0): clip_a, ("movie", 1): clip_b}},
    )
    staged = dsa._stage_unique_clips(plan, tmp_path / "work")
    staged_paths = staged.clips[1]
    names = {p.name for p in staged_paths.values()}
    assert len(names) == 2
    assert staged_paths[("movie", 0)].read_bytes() == b"AAAA"
    assert staged_paths[("movie", 1)].read_bytes() == b"BBBB"


def test_restore_clip_zorder_refuses_on_duplicate_clip_basenames(tmp_path, monkeypatch):
    # Two clips inserted on the same slide happen to share a basename -- fileName
    # matching alone cannot tell them apart, so this must refuse rather than guess
    # (Codex r1 finding 5).
    import zipfile as _zipfile

    out_slide = {
        "_pbtype": "KN.SlideArchive",
        "drawablesZOrder": [{"identifier": "mov1"}, {"identifier": "mov2"}],
    }
    mov1 = {"_pbtype": "TSD.MovieArchive", "movieData": {"identifier": "d1"}}
    mov2 = {"_pbtype": "TSD.MovieArchive", "movieData": {"identifier": "d2"}}
    out_objects = {"slideO": out_slide, "mov1": mov1, "mov2": mov2}

    def fake_load_deck(path):
        return (out_objects, {}, {})

    def fake_slide_order(objects):
        return [("slideO", False)]

    out_path = tmp_path / "out.key"
    with _zipfile.ZipFile(out_path, "w"):
        pass

    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "slide_order", fake_slide_order)
    monkeypatch.setattr(dsa, "_build_data_index", lambda names: {"d1": "clip.mov", "d2": "clip.mov"})
    monkeypatch.setattr(dsa, "_data_identifier", lambda obj: (obj.get("movieData") or {}).get("identifier"))

    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1}, fits={1: {}}, deletes={1: ()}, text_sizes={}, autosize={}, warnings=(),
        clips={1: {("movie", 0): Path("/a/clip.mov"), ("movie", 1): Path("/b/clip.mov")}},
    )
    warnings: list = []
    with pytest.raises(AssemblyRefusal, match="matched 2 drawable"):
        dsa._restore_clip_zorder(out_path, plan, warnings)


def test_restore_clip_zorder_refuses_when_a_preexisting_movie_shares_the_clip_basename(tmp_path, monkeypatch):
    # A pre-existing (untouched) movie in the deck happens to share the inserted clip's
    # basename -- ambiguous by fileName alone, so this must refuse, not silently pick
    # one (Codex r1 finding 5).
    import zipfile as _zipfile

    out_slide = {
        "_pbtype": "KN.SlideArchive",
        "drawablesZOrder": [{"identifier": "movPre"}, {"identifier": "movNew"}],
    }
    mov_pre = {"_pbtype": "TSD.MovieArchive", "movieData": {"identifier": "dPre"}}
    mov_new = {"_pbtype": "TSD.MovieArchive", "movieData": {"identifier": "dNew"}}
    out_objects = {"slideO": out_slide, "movPre": mov_pre, "movNew": mov_new}

    def fake_load_deck(path):
        return (out_objects, {}, {})

    def fake_slide_order(objects):
        return [("slideO", False)]

    out_path = tmp_path / "out.key"
    with _zipfile.ZipFile(out_path, "w"):
        pass

    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "slide_order", fake_slide_order)
    monkeypatch.setattr(dsa, "_build_data_index", lambda names: {"dPre": "clip.mov", "dNew": "clip.mov"})
    monkeypatch.setattr(dsa, "_data_identifier", lambda obj: (obj.get("movieData") or {}).get("identifier"))

    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1}, fits={1: {}}, deletes={1: ()}, text_sizes={}, autosize={}, warnings=(),
        clips={1: {("movie", 0): Path("/a/clip.mov")}},
    )
    warnings: list = []
    with pytest.raises(AssemblyRefusal, match="matched 2 drawable"):
        dsa._restore_clip_zorder(out_path, plan, warnings)


def test_restore_crop_zorder_real_pair_end_to_end(tmp_path):
    """No mocked ``reorder_drawables``: a real source deck and a real staged (output)
    deck, both real ``.key`` zips -- ``_restore_crop_zorder`` must find the crop insert
    by fileName and actually rewrite the output deck's ``drawablesZOrder``."""
    pytest.importorskip("keynote_parser")
    import io
    import zipfile as _zipfile
    from test_iwa_write import _arch, _geom, _member
    from obed_edom.dsk_plan import CropSpec
    from obed_edom.iwa_runs import _load_deck

    img_s = _arch(230, "TSD.ImageArchive", {"data": {"identifier": 5}, "super": _geom(300, 100, 120, 60)})
    grp_s = _arch(250, "TSD.GroupArchive", {"super": _geom(500, 500, 30, 30), "children": [{"identifier": 251}]})
    child_s = _arch(251, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _geom(0, 0, 30, 30)})
    slide_s = _arch(100, "KN.SlideArchive", {"drawablesZOrder": [{"identifier": 230}, {"identifier": 250}]})
    show_s = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 10}]}})
    node_s = _arch(10, "KN.SlideNodeArchive", {"slide": {"identifier": 100}, "isSkipped": False})
    src_path = tmp_path / "src.key"
    buf = io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show_s, node_s]))
        z.writestr("Index/Slide-100.iwa", _member([slide_s, img_s, grp_s, child_s]))
    src_path.write_bytes(buf.getvalue())

    grp_o = _arch(350, "TSD.GroupArchive", {"super": _geom(500, 500, 30, 30), "children": [{"identifier": 351}]})
    child_o = _arch(351, "TSWP.ShapeInfoArchive", {"isTextBox": False, "super": _geom(0, 0, 30, 30)})
    img_o = _arch(330, "TSD.ImageArchive", {"data": {"identifier": 9}, "super": _geom(300, 100, 120, 60)})
    slide_o = _arch(
        200,
        "KN.SlideArchive",
        {
            "drawablesZOrder": [{"identifier": 350}, {"identifier": 330}],
            "ownedDrawables": [{"identifier": 350}, {"identifier": 330}],
        },
    )
    show_o = _arch(2, "KN.ShowArchive", {"slideTree": {"slides": [{"identifier": 20}]}})
    node_o = _arch(20, "KN.SlideNodeArchive", {"slide": {"identifier": 200}, "isSkipped": False})
    out_path = tmp_path / "out.key"
    buf = io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as z:
        z.writestr("Index/Document.iwa", _member([show_o, node_o]))
        z.writestr("Index/Slide-200.iwa", _member([slide_o, img_o, grp_o, child_o]))
        z.writestr("Data/photo-9.jpg", b"fake-jpeg-bytes")
    out_path.write_bytes(buf.getvalue())

    spec = CropSpec(path=Path("/tmp/photo.jpg"), source_file_name="photo.jpg", px_box=(0, 0, 1, 1), visible=Rect(0, 0, 1, 1))
    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1}, fits={1: {}},
        deletes={1: (("image", 0),)}, clips={}, text_sizes={}, autosize={}, warnings=(),
        crops={1: {("image", 0): spec}},
    )
    warnings: list = []
    result = dsa._restore_crop_zorder(src_path, out_path, plan, warnings)
    assert result[1]["refused"] is False
    objects, _id_to_file, _file_ids = _load_deck(out_path)
    assert [ref["identifier"] for ref in objects["200"]["drawablesZOrder"]] == ["330", "350"]
    assert [ref["identifier"] for ref in objects["200"]["ownedDrawables"]] == ["330", "350"]
    assert warnings == []


def test_split_override_forces_split_even_when_it_would_fit():
    _require_font("AzoSans-Regular")
    box1 = _long_text_item(1, _VERSE_1, y=100)
    box2 = _long_text_item(2, _VERSE_2, y=500)
    slide = _slide(17, [box1, box2])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {17: SlideDecision(17, "in_deck", anchor="auto")}
    # Without an override, GW 17's two boxes fit as one stack at the default floor.
    plan_natural = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})
    assert 17 not in plan_natural.splits
    plan_forced = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={}, split_overrides={17: 2},
    )
    assert plan_forced.parts[17] == 2
    assert len(plan_forced.splits[17]) == 2


def test_split_override_refuses_on_part_count_mismatch():
    _require_font("AzoSans-Regular")
    box1 = _long_text_item(1, _VERSE_1, y=100)
    box2 = _long_text_item(2, _VERSE_2, y=500)
    slide = _slide(17, [box1, box2])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {17: SlideDecision(17, "in_deck", anchor="auto")}
    with pytest.raises(AssemblyRefusal, match="--split requests 3"):
        plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, split_overrides={17: 3})


def test_split_override_refuses_when_slide_has_no_long_text_boxes():
    slide = _slide(18, [_image_item(0)])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {18: SlideDecision(18, "in_deck", anchor="auto")}
    with pytest.raises(AssemblyRefusal, match="slide 18: --split does not apply"):
        plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, split_overrides={18: 2})


def test_min_text_pt_forces_split():
    _require_font("AzoSans-Regular")
    box1 = _long_text_item(1, _VERSE_1, y=100)
    box2 = _long_text_item(2, _VERSE_2, y=500)
    slide = _slide(17, [box1, box2])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {17: SlideDecision(17, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, min_text_pt=66.0)
    assert plan.parts[17] == 2
    assert len(plan.splits[17]) == 2


# --------------------------------------------------------------------------
# D1b -- two-column heading+verse band, wired into plan_assembly.
# --------------------------------------------------------------------------
def _two_column_slide(number, verse_text, *, verse_w=1800, verse_h=300):
    # Coordinates fall inside `CENTRE_PANEL_RECT` (x in [1920, 5760]) -- outside it,
    # `classify_slide` drops these items as side-panel content.
    circle = {"kind": "shape", "kindIndex": 0, "x": 2200, "y": 300, "w": 81, "h": 81, "text": ""}
    number_item = {
        "kind": "text", "kindIndex": 1, "x": 2220, "y": 320, "w": 41, "h": 41,
        "text": "3", "font": "AzoSans-Bold", "size": 60.0,
    }
    heading = {
        "kind": "text", "kindIndex": 2, "x": 2000, "y": 500, "w": 1600, "h": 150,
        "text": "Faith", "font": "ArgentCF-Bold", "size": 80.0,
    }
    verse = {
        "kind": "text", "kindIndex": 3, "x": 3800, "y": 700, "w": verse_w, "h": verse_h,
        "text": verse_text, "font": "AzoSans-Regular", "size": 70.0,
    }
    return _slide(number, [circle, number_item, heading, verse])


def test_two_column_rects_forwards_min_text_pt_floor():
    # Codex D1b-p2 review 1 finding 1: `_two_column_rects` must pass its own
    # `min_text_pt` to `fit_heading_pt` (D1b Section 4's `[80 ... min_text_pt]`),
    # not the module's `DEFAULT_MIN_TEXT_PT` -- a heading that only fits at 28pt
    # must succeed at the default 24pt floor and refuse at a supplied 60pt floor.
    _require_font("AzoSans-Regular")
    heading_id = ("text", 2)
    number_id = ("text", 1)
    circle_id = ("shape", 0)
    items_by_id = {
        heading_id: {
            "kind": "text", "kindIndex": 2, "text": "Faith Hope and Love Abide",
            "font": "AzoSans-Regular", "size": 80.0,
        },
        number_id: {
            "kind": "text", "kindIndex": 1, "text": "3", "font": "AzoSans-Bold", "size": 60.0,
        },
        circle_id: {"kind": "shape", "kindIndex": 0, "text": ""},
    }
    cluster = dsa.HeadingCluster(heading_id, number_id, circle_id)
    band = Band(1054.0, 110.0, 43.0, 501.0, 4)
    warnings: list[str] = []

    rects, text_sizes, run_sizes, _left = dsa._two_column_rects(
        17, cluster, items_by_id, band, 900.0, 24.0, warnings,
    )
    assert text_sizes[heading_id] == pytest.approx(28.0, abs=0.01)

    with pytest.raises(AssemblyRefusal, match="does not fit"):
        dsa._two_column_rects(17, cluster, items_by_id, band, 900.0, 60.0, warnings)


def _two_column_cluster_items(heading_runs):
    heading_id = ("text", 2)
    number_id = ("text", 1)
    circle_id = ("shape", 0)
    items_by_id = {
        heading_id: {
            "kind": "text", "kindIndex": 2, "text": "Faith Hope",
            "font": "AzoSans-Regular", "size": 80.0, "runs": heading_runs,
        },
        number_id: {"kind": "text", "kindIndex": 1, "text": "3", "font": "AzoSans-Bold", "size": 60.0},
        circle_id: {"kind": "shape", "kindIndex": 0, "text": ""},
    }
    cluster = dsa.HeadingCluster(heading_id, number_id, circle_id)
    return cluster, items_by_id, heading_id, number_id


def test_two_column_rects_run_size_ranges_uniform_heading():
    # Codex D1b-p2 review 1 finding 4: heading/numeral sizing must go through
    # `_run_size_ranges` (`t = heading_pt / source_size` for the heading, `46/81`
    # for the numeral) -- a uniform run collapses to `text_sizes`, never `run_sizes`.
    _require_font("AzoSans-Regular")
    heading_runs = [{"text": "Faith ", "size": 80.0}, {"text": "Hope", "size": 80.0}]
    cluster, items_by_id, heading_id, number_id = _two_column_cluster_items(heading_runs)
    band = Band(1054.0, 350.0, 43.0, 501.0, 4)
    rects, text_sizes, run_sizes, _left = dsa._two_column_rects(
        17, cluster, items_by_id, band, 900.0, 24.0, [],
    )
    assert heading_id in text_sizes
    assert heading_id not in run_sizes
    assert number_id in text_sizes


def test_two_column_rects_run_size_ranges_mixed_heading():
    # A mixed-size heading run must land in `run_sizes` as scaled per-run ranges,
    # not be flattened to one `text_sizes` entry.
    _require_font("AzoSans-Regular")
    heading_runs = [{"text": "Faith ", "size": 80.0}, {"text": "Hope", "size": 60.0}]
    cluster, items_by_id, heading_id, _number_id = _two_column_cluster_items(heading_runs)
    band = Band(1054.0, 350.0, 43.0, 501.0, 4)
    rects, text_sizes, run_sizes, _left = dsa._two_column_rects(
        17, cluster, items_by_id, band, 900.0, 24.0, [],
    )
    assert heading_id not in text_sizes
    assert heading_id in run_sizes
    # The heading text ("Faith Hope") fits at MAX_HEADING_PT (80.0) in this wide,
    # tall band, matching its 80.0 source size -- scale 1.0.
    ranges = run_sizes[heading_id]
    assert ranges[0] == (1, 6, pytest.approx(80.0, abs=0.01))
    assert ranges[1] == (7, 10, pytest.approx(60.0, abs=0.01))


def test_two_column_short_fit_excludes_heading():
    # Codex D1b-p2 review 1 finding 5: a fixture with no verse badge only proves
    # exclusion of the heading cluster, not that `short_fit` holds the badge and
    # nothing else -- add a synthetic verse badge (kindIndex 4, short AzoSans text,
    # not part of the heading cluster) and assert `short_fit[17]` is exactly it.
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    slide = _two_column_slide(17, _VERSE_1)
    badge_text = {
        "kind": "text", "kindIndex": 4, "x": 3800, "y": 600, "w": 300, "h": 50,
        "text": "John 3:16", "font": "AzoSans-Bold", "size": 30.0,
    }
    badge_shape = {
        "kind": "shape", "kindIndex": 1, "x": 3800, "y": 600, "w": 300, "h": 50,
        "text": "John 3:16",
    }
    slide["items"].extend([badge_text, badge_shape])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {17: SlideDecision(17, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})

    assert plan.stack_bands[17].x_min == pytest.approx(501.0, abs=0.01)
    short_fit = plan.short_fit.get(17, {})
    assert set(short_fit) == {("text", 4), ("shape", 1)}
    assert ("text", 1) not in short_fit
    assert ("text", 2) not in short_fit
    assert ("shape", 0) not in short_fit
    assert ("text", 2) in plan.fits[17]
    assert plan.fits[17][("text", 2)].x == pytest.approx(43.0, abs=0.01)
    assert plan.two_column[17].x_max == pytest.approx(493.0, abs=0.01)


def test_two_column_repeat_heading_dropped_when_planned_alone():
    # Codex D1b-p2 review 1 finding 2: the repeat-heading predecessor is the true
    # deck-order previous non-empty slide, independent of the planning batch --
    # slide 21 alone (its predecessor 20 outside `classes`) must still see 20's
    # matching "Faith" heading, via `_full_classes_by_number`'s reclassification of
    # the whole payload (review 2), and drop its own.
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    slide_20 = _two_column_slide(20, _VERSE_1)
    slide_21 = _two_column_slide(21, _VERSE_2)
    payload = _payload([slide_20, slide_21])
    classes = [_classify(slide_21)]
    all_classes = [_classify(slide_20), _classify(slide_21)]
    decisions = {21: SlideDecision(21, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, all_classes=all_classes)

    assert 21 not in plan.two_column
    verse = plan.fits[21][("text", 3)]
    assert verse.x == pytest.approx(43.0, abs=0.01)
    cluster_ids = {("shape", 0), ("text", 1), ("text", 2)}
    assert cluster_ids <= set(plan.deletes[21])


def test_two_column_repeat_heading_survives_heading_only_predecessor():
    # Owner-pinned rule (D1b-p2 fix round 2, GW45->46): suppression requires the
    # immediate predecessor to itself be heading+verse -- a heading-only predecessor
    # (heading cluster, no verse) shares slide 22's "Faith" heading text but must not
    # drop it.
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    slide_21 = _slide(21, [_heading_item(0, "Faith")])
    slide_22 = _two_column_slide(22, _VERSE_1)
    payload = _payload([slide_21, slide_22])
    classes = [_classify(slide_22)]
    all_classes = [_classify(slide_21), _classify(slide_22)]
    decisions = {22: SlideDecision(22, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, all_classes=all_classes)

    assert 22 in plan.two_column
    assert plan.fits[22][("text", 2)].x == pytest.approx(43.0, abs=0.01)


def test_two_column_repeat_heading_survives_headingless_predecessor():
    # Codex D1b-p2 review 1 finding 2: a headingless intervening slide breaks the
    # run -- slide 22's immediate predecessor (21, an image slide) has no heading,
    # so 22 must keep its own "Faith" heading even though slide 20 (further back,
    # outside `classes` too) shares that text.
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    slide_20 = _two_column_slide(20, _VERSE_1)
    slide_21 = _slide(21, [_image_item(0, x=2000, y=200, w=1000, h=500)])
    slide_22 = _two_column_slide(22, _VERSE_2)
    payload = _payload([slide_20, slide_21, slide_22])
    classes = [_classify(slide_22)]
    all_classes = [_classify(slide_20), _classify(slide_21), _classify(slide_22)]
    decisions = {22: SlideDecision(22, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, all_classes=all_classes)

    assert 22 in plan.two_column
    assert plan.fits[22][("text", 2)].x == pytest.approx(43.0, abs=0.01)


def _two_column_slide_group_child_verse(number, verse_text, *, verse_w=1800, verse_h=300):
    # Same left-column heading cluster as `_two_column_slide`, but the verse is a
    # group child (GW 44/50/51/53's real shape) rather than a top-level text.
    circle = {"kind": "shape", "kindIndex": 0, "x": 2200, "y": 300, "w": 81, "h": 81, "text": ""}
    number_item = {
        "kind": "text", "kindIndex": 1, "x": 2220, "y": 320, "w": 41, "h": 41,
        "text": "3", "font": "AzoSans-Bold", "size": 60.0,
    }
    heading = {
        "kind": "text", "kindIndex": 2, "x": 2000, "y": 500, "w": 1600, "h": 150,
        "text": "Faith", "font": "ArgentCF-Bold", "size": 80.0,
    }
    group = _group_item(0, x=3800, y=700, w=verse_w, h=verse_h)
    slide = _slide(number, [circle, number_item, heading, group])
    slide["groupChildText"] = {0: verse_text}
    slide["groupChildSignature"] = {0: f"shape:badge\ntext:{verse_text}"}
    slide["groupChildren"] = {0: [
        {"kind": "shape", "kindIndex": 0, "autosize": False, "x": 3800.0, "y": 700.0, "w": 300.0, "h": 60.0},
        {"kind": "text", "kindIndex": 1, "autosize": True, "x": 3800.0, "y": 760.0, "w": float(verse_w), "h": float(verse_h) - 60.0},
    ]}
    return slide


def test_repeat_heading_predecessor_uses_group_child_verse():
    # Codex D1b-p2 review 2/3 MAJOR: a predecessor outside the planning batch must be
    # classified through the exact same inputs (here, group-child text/children) as
    # `_heading_cluster` requires -- there is no fallback reclassification any more
    # (D1b-p2 fix round 4), so the caller supplies `all_classes` with the predecessor
    # classified with its group-child kwargs, and slide 20's group-child-verse heading
    # cluster is recognised, dropping slide 21's (planned alone) repeated heading.
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    slide_20 = _two_column_slide_group_child_verse(20, _VERSE_1)
    slide_21 = _two_column_slide(21, _VERSE_2)
    payload = _payload([slide_20, slide_21])
    classes = [_classify(slide_21)]
    predecessor_cls = _classify(
        slide_20, group_child_words=slide_20["groupChildText"], group_children=slide_20["groupChildren"],
    )
    all_classes = [predecessor_cls, _classify(slide_21)]
    decisions = {21: SlideDecision(21, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, all_classes=all_classes)

    predecessor_items = {(it["kind"], it["kindIndex"]): it for it in slide_20["items"]}
    assert dsa._heading_cluster(predecessor_cls, predecessor_items) is not None

    assert 21 not in plan.two_column
    verse = plan.fits[21][("text", 3)]
    assert verse.x == pytest.approx(43.0, abs=0.01)


def test_repeat_heading_predecessor_unmatched_badge_does_not_suppress():
    # Codex D1b-p2 review 2 MAJOR parity case: a predecessor whose extra top-level
    # text does NOT match any shape's rect+text (the badge rule in `_heading_cluster`)
    # is not itself a two-column-eligible cluster, so it must not suppress a
    # same-heading successor -- the old approximation never checked the badge rule
    # at all and would have wrongly suppressed.
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    slide_20 = _two_column_slide(20, _VERSE_1)
    unmatched_badge = {
        "kind": "text", "kindIndex": 4, "x": 3000, "y": 900, "w": 300, "h": 50,
        "text": "John 3:16", "font": "AzoSans-Bold", "size": 30.0,
    }
    slide_20["items"].append(unmatched_badge)
    slide_21 = _two_column_slide(21, _VERSE_2)
    payload = _payload([slide_20, slide_21])
    classes = [_classify(slide_21)]
    predecessor_cls = _classify(slide_20)
    all_classes = [predecessor_cls, _classify(slide_21)]
    decisions = {21: SlideDecision(21, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, all_classes=all_classes)

    predecessor_items = {(it["kind"], it["kindIndex"]): it for it in slide_20["items"]}
    assert dsa._heading_cluster(predecessor_cls, predecessor_items) is None

    assert 21 in plan.two_column
    assert plan.fits[21][("text", 2)].x == pytest.approx(43.0, abs=0.01)


def test_repeat_heading_predecessor_multiple_long_text_ids_does_not_suppress():
    # Codex D1b-p2 review 2 MAJOR parity case: `_heading_cluster` refuses whenever
    # `cls.long_text_ids` has more than one entry -- a predecessor with two long-text
    # boxes is not two-column-eligible and must not suppress a same-heading
    # successor. The old approximation had no `cls.long_text_ids` to consult and
    # would have wrongly suppressed (any text over the word threshold sufficed).
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    slide_20 = _two_column_slide(20, _VERSE_1)
    second_long_text = {
        "kind": "text", "kindIndex": 4, "x": 2000, "y": 900, "w": 1800, "h": 300,
        "text": _VERSE_2, "font": "AzoSans-Regular", "size": 70.0,
    }
    slide_20["items"].append(second_long_text)
    slide_21 = _two_column_slide(21, _VERSE_2)
    payload = _payload([slide_20, slide_21])
    classes = [_classify(slide_21)]
    predecessor_cls = _classify(slide_20)
    all_classes = [predecessor_cls, _classify(slide_21)]
    decisions = {21: SlideDecision(21, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={}, all_classes=all_classes)

    assert len(predecessor_cls.long_text_ids) == 2
    predecessor_items = {(it["kind"], it["kindIndex"]): it for it in slide_20["items"]}
    assert dsa._heading_cluster(predecessor_cls, predecessor_items) is None

    assert 21 in plan.two_column
    assert plan.fits[21][("text", 2)].x == pytest.approx(43.0, abs=0.01)


def test_repeat_heading_predecessor_include_side_matches_batch_classification():
    # D1b-p2 fix round 4: `_full_classes_by_number` no longer reclassifies -- it uses
    # the caller's `all_classes` verbatim, so a predecessor's `include_side` setting
    # (which can keep a side-panel long-text box that would otherwise be dropped,
    # adding a second `long_text_ids` entry and breaking the heading cluster) is
    # respected exactly as whole-deck batch classification computed it.
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    slide_20 = _two_column_slide(20, _VERSE_1)
    side_text = {
        "kind": "text", "kindIndex": 4, "x": 100, "y": 200, "w": 800, "h": 300,
        "text": "A side panel caption that runs on for quite a lot of words indeed.",
        "font": "AzoSans-Regular", "size": 40.0,
    }
    slide_20["items"].append(side_text)
    slide_21 = _two_column_slide(21, _VERSE_2)
    payload = _payload([slide_20, slide_21])
    classes = [_classify(slide_21)]
    decisions = {21: SlideDecision(21, "in_deck", anchor="auto")}

    predecessor_no_side = _classify(slide_20, include_side=False)
    assert len(predecessor_no_side.long_text_ids) == 1
    plan_no_side = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={},
        all_classes=[predecessor_no_side, _classify(slide_21)],
    )
    assert 21 not in plan_no_side.two_column

    predecessor_with_side = _classify(slide_20, include_side=True)
    assert len(predecessor_with_side.long_text_ids) == 2
    predecessor_items = {(it["kind"], it["kindIndex"]): it for it in slide_20["items"]}
    assert dsa._heading_cluster(predecessor_with_side, predecessor_items) is None
    plan_with_side = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={},
        all_classes=[predecessor_with_side, _classify(slide_21)],
    )
    assert 21 in plan_with_side.two_column


def test_repeat_heading_connection_line_only_slide_breaks_run_consistently_with_batch():
    # D1b-p2 fix round 4: a connection-line-only intervening slide (no kept items) is
    # `category == "empty"` with zero connection-line builds and transparent to the
    # repeat-heading run, but `category == "built"` with a connection-line build --
    # `_full_classes_by_number` must see whichever the caller's `all_classes` (batch
    # classification) actually computed, not an approximation that always leaves
    # connection-line counts at zero.
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    slide_20 = _two_column_slide(20, _VERSE_1)
    slide_21 = _slide(21, [])
    slide_22 = _two_column_slide(22, _VERSE_1)
    payload = _payload([slide_20, slide_21, slide_22])
    classes = [_classify(slide_22)]
    decisions = {22: SlideDecision(22, "in_deck", anchor="auto")}

    transparent = _classify(slide_21, connection_line_builds=0)
    assert transparent.category == "empty"
    plan_transparent = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={},
        all_classes=[_classify(slide_20), transparent, _classify(slide_22)],
    )
    assert 22 not in plan_transparent.two_column

    breaks_run = _classify(slide_21, connection_line_builds=1)
    assert breaks_run.category == "built"
    plan_breaks = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={},
        all_classes=[_classify(slide_20), breaks_run, _classify(slide_22)],
    )
    assert 22 in plan_breaks.two_column


def test_plan_assembly_subset_of_deck_without_all_classes_raises():
    # D1b-p2 fix round 4 ORCHESTRATOR DECISION: the reclassification fallback is
    # deleted -- planning a subset of a deck-backed payload (`classes` narrower than
    # `payload`'s slides) without `all_classes` must refuse rather than silently
    # reclassify through inputs that can disagree with batch classification.
    slide_20 = _two_column_slide(20, _VERSE_1)
    slide_21 = _two_column_slide(21, _VERSE_2)
    payload = _payload([slide_20, slide_21])
    classes = [_classify(slide_21)]
    decisions = {21: SlideDecision(21, "in_deck", anchor="auto")}
    with pytest.raises(ValueError, match="all_classes"):
        plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})


def test_repeat_heading_gw51_planned_alone_matches_batch():
    # Codex D1b-p2 review 2 MAJOR real-deck assertion: GW 51 planned alone must
    # match its plan in the GW 50-53 batch -- heading dropped, verse
    # x=43/w=1849 -- and the other GW rows stay as measured (44/46/50 two-column,
    # 51/52/53 full-width).
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    numbers = (44, 46, 50, 51, 52, 53)
    decisions = {n: SlideDecision(n, "in_deck") for n in numbers}
    batch = plan_assembly(
        payload, [by_number[n] for n in numbers], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes,
    )
    assert set(batch.two_column) == {44, 46, 50}
    for n, verse_id in ((51, ("groupchild", 0, "text", 1)), (52, ("text", 1)), (53, ("groupchild", 0, "text", 1))):
        verse = batch.fits[n][verse_id]
        assert verse.x == pytest.approx(43.0, abs=0.01)

    alone_decisions = {51: SlideDecision(51, "in_deck")}
    alone = plan_assembly(
        payload, [by_number[51]], decisions=alone_decisions, band=BAND, clips={}, runs=runs, all_classes=classes,
    )
    assert 51 not in alone.two_column
    alone_verse = alone.fits[51][("groupchild", 0, "text", 1)]
    batch_verse = batch.fits[51][("groupchild", 0, "text", 1)]
    assert alone_verse.x == pytest.approx(batch_verse.x, abs=0.01)
    assert alone_verse.w == pytest.approx(batch_verse.w, abs=0.01)
    assert alone_verse.x == pytest.approx(43.0, abs=0.01)
    assert alone_verse.w == pytest.approx(1849.0, abs=0.5)


def test_build_refit_round_recentres_two_column_heading():
    # Codex D1b-p2 review 1 finding 3: a refit round that recomputes the verse's
    # top must rederive the left-block (heading cluster) centring off the NEW
    # right-block centre, not leave it pinned to the original plan's position.
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    slide = _two_column_slide(17, _VERSE_1)
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {17: SlideDecision(17, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})

    verse_id = ("text", 3)
    heading_id = ("text", 2)
    circle_id = ("shape", 0)
    number_id = ("text", 1)
    predicted_h = plan.fits[17][verse_id].h
    predicted_heading_y = plan.fits[17][heading_id].y
    measured_h = predicted_h * 1.3
    slides_by_number = {s["number"]: s for s in payload["slides"]}
    refits = dsa._build_refit_round(
        plan, slides_by_number, {(17, "text:3")}, {(17, "text:3"): measured_h}, BAND, 24.0, [], {},
    )

    assert heading_id in refits[17]
    assert circle_id in refits[17]
    assert number_id in refits[17]
    new_heading_y = refits[17][heading_id].rect.y
    assert new_heading_y != pytest.approx(predicted_heading_y, abs=0.01)

    left_band = plan.two_column[17]
    new_verse_top = min(
        r.rect.y for iid, r in refits[17].items() if iid[0] != "shape" and iid != heading_id
    )
    heading_block_h = dsa.NUMBER_BADGE_PT + dsa._TEXT_STACK_GAP + plan.fits[17][heading_id].h
    right_block_centre = (new_verse_top + left_band.bottom) / 2.0
    expected_circle_y = right_block_centre - heading_block_h / 2.0
    assert refits[17][circle_id].rect.y == pytest.approx(expected_circle_y, abs=0.5)


def test_build_refit_script_writes_visual_top_y_for_recentred_cluster():
    # Probe result round 2 (`<scratchpad>/probe-autosize/log.txt`): `position` is
    # already the live visual top-left of an autosize box, so `build_refit_script`
    # must write the refit's `rect.y` untouched -- no vertical-alignment transform --
    # matching `_slide_lines`'s own (now transform-free) position write for the
    # same recentred heading.
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    slide = _two_column_slide(17, _VERSE_1)
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {17: SlideDecision(17, "in_deck", anchor="auto")}
    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={})

    verse_id = ("text", 3)
    heading_id = ("text", 2)
    predicted_h = plan.fits[17][verse_id].h
    measured_h = predicted_h * 1.3
    slides_by_number = {s["number"]: s for s in payload["slides"]}
    refits = dsa._build_refit_round(
        plan, slides_by_number, {(17, "text:3")}, {(17, "text:3"): measured_h}, BAND, 24.0, [], {},
    )
    new_heading_y = refits[17][heading_id].rect.y

    script = build_refit_script(
        plan, {(n, 0): items for n, items in refits.items()}, ordinals=plan.ordinals,
        scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"),
    )
    staged_heading_id = dsa._staged_id_for(17, plan, heading_id, hidden=frozenset())
    heading_addr = f"text item {staged_heading_id[1] + 1} of slide {plan.ordinals[17]}"
    lines = script.splitlines()
    start = next(i for i, l in enumerate(lines) if f"set theObj to {heading_addr}" in l)
    block = lines[start:start + 14]
    position_line = next(l for l in block if "set position" in l)
    assert position_line == (
        f"          set position of theObj to {{{dsa._as_num(plan.fits[17][heading_id].x)}, "
        f"{dsa._as_num(new_heading_y)}}}"
    )


def test_two_column_refuses_instead_of_splitting():
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    long_verse = " ".join([_VERSE_1, _VERSE_2, _VERSE_1, _VERSE_2, _VERSE_1, _VERSE_2])
    slide = _two_column_slide(17, long_verse)
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {17: SlideDecision(17, "in_deck", anchor="auto")}
    with pytest.raises(AssemblyRefusal, match="two-column verse does not fit"):
        plan_assembly(
            payload, classes, decisions=decisions, band=BAND, clips={},
            min_text_pt=60.0, allow_split=True,
        )


# --------------------------------------------------------------------------
# _offline_measure (D2b step 2) -- staged-index inversion, offline reader faked.
# --------------------------------------------------------------------------
def test_offline_measure_maps_staged_index_back_to_source_index(monkeypatch):
    plan, _slides_by_number = _badge_and_stack_plan()
    plan.fits[13][("text", 2)] = plan.fits[13][("text", 0)]
    plan.deletes[13] = (("text", 0),)
    warnings: list[str] = []
    monkeypatch.setattr(
        dsa, "offline_text_rects",
        lambda key_path, *, deck=None: (
            {1: {("text", 0): (43.0, 800.0, 1849.0, 300.0), ("text", 1): (100.0, 50.0, 200.0, 60.0)}},
            set(),
        ),
    )
    measured, bands, measure_warnings = dsa._offline_measure(Path("/tmp/staged.key"), plan, {}, warnings)
    assert measured[(13, "text:1")] == 300.0
    assert measured[(13, "text:2")] == 60.0
    assert bands[(13, "text:1")] == (800.0, 1100.0)
    assert not warnings
    assert not measure_warnings


def test_offline_measure_warns_and_skips_on_staged_count_mismatch(monkeypatch):
    plan, _slides_by_number = _badge_and_stack_plan()
    warnings: list[str] = []
    monkeypatch.setattr(
        dsa, "offline_text_rects",
        lambda key_path, *, deck=None: ({1: {("text", 0): (0.0, 0.0, 0.0, 0.0)}}, set()),
    )
    measured, _bands, measure_warnings = dsa._offline_measure(Path("/tmp/staged.key"), plan, {}, warnings)
    assert measured == {}
    assert any("staged text count" in w and "offline text count" in w for w in warnings)
    assert any("staged text count" in w and "offline text count" in w for w in measure_warnings)


def test_offline_measure_hidden_placeholder_retains_staged_id(monkeypatch):
    # Opus D2b review 1 finding 9: the reviewer's probe_hidden.py scenario -- Keynote
    # refuses to delete ("text", 0), so the staging deck retains 3 text items; the
    # ``hidden`` map keeps the offline read from treating this as a count mismatch and
    # correctly identity-maps the retained placeholder back to its source index.
    plan, _slides_by_number = _badge_and_stack_plan()
    plan.fits[13][("text", 2)] = plan.fits[13][("text", 0)]
    plan.deletes[13] = (("text", 0),)
    rects = {
        1: {
            ("text", 0): (43.0, 800.0, 1849.0, 300.0),
            ("text", 1): (100.0, 50.0, 200.0, 60.0),
            ("text", 2): (0.0, 0.0, 0.0, 10.0),
        },
    }
    monkeypatch.setattr(dsa, "offline_text_rects", lambda key_path, *, deck=None: (rects, set()))

    warnings: list[str] = []
    measured, _bands, measure_warnings = dsa._offline_measure(
        Path("/tmp/staged.key"), plan, {13: frozenset({("text", 0)})}, warnings,
    )
    assert measured[(13, "text:0")] == 300.0
    assert measured[(13, "text:1")] == 60.0
    assert measured[(13, "text:2")] == 10.0
    assert not warnings
    assert not measure_warnings

    unlogged_warnings: list[str] = []
    unlogged_measured, _bands2, unlogged_measure_warnings = dsa._offline_measure(
        Path("/tmp/staged.key"), plan, {}, unlogged_warnings,
    )
    assert unlogged_measured == {}
    assert any("staged text count 2 != offline text count 3" in w for w in unlogged_warnings)
    assert any("staged text count 2 != offline text count 3" in w for w in unlogged_measure_warnings)


# --------------------------------------------------------------------------
# r13 root cause fix landed in the live pass (script-side placeholder cleanup, not the
# offline reader): a genuinely missing staged box must still refuse.
# --------------------------------------------------------------------------
def test_offline_measure_still_refuses_when_a_staged_box_is_genuinely_missing(monkeypatch):
    plan, _slides_by_number = _badge_and_stack_plan()
    rects = {
        1: {
            ("text", 0): (63.0, 786.0, 933.0, 262.4),
        },
    }
    monkeypatch.setattr(dsa, "offline_text_rects", lambda key_path: (rects, set()))

    warnings: list[str] = []
    measured, _bands, measure_warnings = dsa._offline_measure(Path("/tmp/staged.key"), plan, {}, warnings)

    assert measured == {}
    assert any("staged text count 2 != offline text count 1" in w for w in warnings)
    assert any("staged text count 2 != offline text count 1" in w for w in measure_warnings)


# --------------------------------------------------------------------------
# C1 (Codex review 1) -- a failed refit/shrink pass must never be accepted.
# --------------------------------------------------------------------------
def test_refit_round_refuses_on_nonzero_batch_returncode(tmp_path, monkeypatch):
    _require_helvetica()
    fw_deck, out_path, payload, classes, decisions = _stacked_assemble_fixture(tmp_path)

    class _FailingRefitBatch:
        def __init__(self, deck, out_dir, *, rss_limit_bytes=0, log=print):
            self.deck = Path(deck)
            self.out_dir = Path(out_dir)
            self.work = self.out_dir / "fake-work"
            self.scratch = self.work / self.deck.name
            self._n = 0

        def __enter__(self):
            self.work.mkdir(parents=True, exist_ok=True)
            self.scratch.mkdir(parents=True, exist_ok=True)
            (self.scratch / "marker").write_bytes(b"scratch")
            return self

        def __exit__(self, exc_type, exc, _tb):
            return False

        def run(self, script_path, *, on_progress=None, retry_on_1712=True):
            self._n += 1
            if self._n == 1:
                return subprocess.CompletedProcess([], 0, "", "OBED\t13\tdone")
            return subprocess.CompletedProcess([], 1, "", "some Keynote error")

    _patch_common_with_batch(monkeypatch, payload, classes, _FailingRefitBatch)
    monkeypatch.setattr(dsa, "offline_text_rects", _offline_reader_seq([_text_rects(500.0)]))
    with pytest.raises(AssemblyRefusal, match="refit round 1 failed"):
        assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve")


def test_refit_round_refuses_on_miss_line(tmp_path, monkeypatch):
    _require_helvetica()
    fw_deck, out_path, payload, classes, decisions = _stacked_assemble_fixture(tmp_path)

    class _MissRefitBatch:
        def __init__(self, deck, out_dir, *, rss_limit_bytes=0, log=print):
            self.deck = Path(deck)
            self.out_dir = Path(out_dir)
            self.work = self.out_dir / "fake-work"
            self.scratch = self.work / self.deck.name
            self._n = 0

        def __enter__(self):
            self.work.mkdir(parents=True, exist_ok=True)
            self.scratch.mkdir(parents=True, exist_ok=True)
            (self.scratch / "marker").write_bytes(b"scratch")
            return self

        def __exit__(self, exc_type, exc, _tb):
            return False

        def run(self, script_path, *, on_progress=None, retry_on_1712=True):
            self._n += 1
            if self._n == 1:
                return subprocess.CompletedProcess([], 0, "", "OBED\t13\tdone")
            return subprocess.CompletedProcess(
                [], 0, "", "MISS\t13\ttext item 1 of slide 1\tsome AppleScript error"
            )

    _patch_common_with_batch(monkeypatch, payload, classes, _MissRefitBatch)
    monkeypatch.setattr(dsa, "offline_text_rects", _offline_reader_seq([_text_rects(500.0)]))
    with pytest.raises(AssemblyRefusal, match="write failed for slide 13"):
        assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve")


# --------------------------------------------------------------------------
# C4 (Codex review 1) -- a still-overflowing box after shrink must refuse, never
# publish with a nonempty AssembleResult.overflows.
# --------------------------------------------------------------------------
def test_shrink_fallback_refuses_when_still_over_budget_after_shrink(tmp_path, monkeypatch):
    _require_helvetica()
    fw_deck, out_path, payload, classes, decisions = _stacked_assemble_fixture(tmp_path)
    pass1_stderr = "OBED\t13\tdone"
    still_over_stderr = "OBED\t13\tdone"
    shrunk_still_over_stderr = "OBED\t13\tdone"
    live_batch_cls, calls = _make_seq_live_batch(
        [pass1_stderr, still_over_stderr, still_over_stderr, shrunk_still_over_stderr]
    )
    _patch_common_with_batch(monkeypatch, payload, classes, live_batch_cls)
    monkeypatch.setattr(
        dsa, "offline_text_rects",
        _offline_reader_seq(
            [_text_rects(500.0), _text_rects(500.0), _text_rects(500.0), _text_rects(5000.0)]
        ),
    )
    with pytest.raises(AssemblyRefusal, match="still overflows after refit and shrink"):
        assemble_dsk_deck(
            fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve", text_fit="shrink",
        )


# --------------------------------------------------------------------------
# r11 refit brief item 4 -- keep the staging deck on refusal after pass 1 saved.
# --------------------------------------------------------------------------
def test_refusal_after_pass1_saves_copies_staging_deck_next_to_out(tmp_path, monkeypatch):
    _require_helvetica()
    fw_deck, out_path, payload, classes, decisions = _stacked_assemble_fixture(tmp_path)

    class _SavingRefusingBatch:
        def __init__(self, deck, out_dir, *, rss_limit_bytes=0, log=print):
            self.deck = Path(deck)
            self.out_dir = Path(out_dir)
            self.work = self.out_dir / "fake-work"
            self.scratch = self.work / self.deck.name

        def __enter__(self):
            self.work.mkdir(parents=True, exist_ok=True)
            self.scratch.mkdir(parents=True, exist_ok=True)
            (self.scratch / "marker").write_bytes(b"scratch")
            return self

        def run(self, script_path, *, on_progress=None, retry_on_1712=True):
            staging_path = self.work / f"staged-{out_path.name}"
            staging_path.write_bytes(b"staged-deck-bytes")
            return subprocess.CompletedProcess([], 0, "", "OBED\t13\tdone")

        def __exit__(self, exc_type, exc, _tb):
            return False

    _patch_common_with_batch(monkeypatch, payload, classes, _SavingRefusingBatch)
    monkeypatch.setattr(dsa, "offline_text_rects", _offline_reader_seq([_text_rects(5000.0)]))
    logs: list[str] = []
    with pytest.raises(AssemblyRefusal, match="still overflows after refit"):
        assemble_dsk_deck(
            fw_deck, out_path, decisions=decisions, clips={}, layout_policy="preserve", log=logs.append,
        )
    refused_path = out_path.parent / f"{out_path.stem}.refused.key"
    assert refused_path.exists()
    assert not out_path.exists()
    assert any(str(refused_path) in l for l in logs)


# --------------------------------------------------------------------------
# Live r12 finding -- two-column heading/numeral floating off-canvas: the boxes are
# genuine Keynote-autosize text frames (raw geometry height 0), so an emitted
# `set height` is silently overridden by Keynote on save. `plan.autosize` must carry
# them so `_slide_lines` skips the height write, matching the group-child convention.
# --------------------------------------------------------------------------
def _cluster_deck_objects(*, heading_autosize, number_autosize):
    heading_obj = {
        "geometry": {
            "position": {"x": 2000, "y": 500}, "size": {"width": 1600, "height": 0.0 if heading_autosize else 150},
            "angle": 0.0,
        },
    }
    number_obj = {
        "geometry": {
            "position": {"x": 2220, "y": 320}, "size": {"width": 41, "height": 0.0 if number_autosize else 41},
            "angle": 0.0,
        },
    }
    return {"headingObj": heading_obj, "numberObj": number_obj}


def _patch_cluster_object_ids(monkeypatch, heading_kindindex, number_kindindex):
    monkeypatch.setattr(dsa, "_slide_archive_for_number", lambda objects, number: {"slide": number})
    monkeypatch.setattr(
        dsa, "_item_object_ids",
        lambda slide_archive, objects: {
            ("text", heading_kindindex): "headingObj", ("text", number_kindindex): "numberObj",
        },
    )


def test_two_column_autosize_heading_and_numeral_skip_set_height(monkeypatch):
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    slide = _two_column_slide(17, _VERSE_1)
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {17: SlideDecision(17, "in_deck", anchor="auto")}
    objects = _cluster_deck_objects(heading_autosize=True, number_autosize=True)
    _patch_cluster_object_ids(monkeypatch, heading_kindindex=2, number_kindindex=1)

    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={}, deck=(objects, {}, {}),
    )
    heading_id = ("text", 2)
    number_id = ("text", 1)
    assert heading_id in plan.autosize[17]
    assert number_id in plan.autosize[17]

    lines = dsa._slide_lines(plan, 17, 1)
    for item_id, kind_index, label in ((heading_id, 2, "heading"), (number_id, 1, "numeral")):
        rect = plan.fits[17][item_id]
        addr = f"text item {kind_index + 1} of slide 1"
        start = lines.index(f"          set theObj to {addr}")
        block = lines[start:start + 12]
        assert not any("set height" in l for l in block), (label, block)
        width_i = next(i for i, l in enumerate(block) if "set width" in l)
        position_i = next(i for i, l in enumerate(block) if "set position" in l)
        assert block[position_i] == (
            f"          set position of theObj to {{{dsa._as_num(rect.x)}, {dsa._as_num(rect.y)}}}"
        ), (label, block)
        assert width_i < position_i, (label, block)
        size_indices = [i for i, l in enumerate(block) if "set size" in l]
        assert size_indices, (label, block)
        assert all(i < position_i for i in size_indices), (
            "position must be written after width and size for cluster autosize items", label, block,
        )


def test_two_column_fixed_frame_heading_still_gets_set_height(monkeypatch):
    _require_font("AzoSans-Regular")
    _require_font("ArgentCF-Bold")
    slide = _two_column_slide(17, _VERSE_1)
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {17: SlideDecision(17, "in_deck", anchor="auto")}
    objects = _cluster_deck_objects(heading_autosize=False, number_autosize=False)
    _patch_cluster_object_ids(monkeypatch, heading_kindindex=2, number_kindindex=1)

    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={}, deck=(objects, {}, {}),
    )
    heading_id = ("text", 2)
    number_id = ("text", 1)
    assert heading_id not in plan.autosize.get(17, frozenset())
    assert number_id not in plan.autosize.get(17, frozenset())

    lines = dsa._slide_lines(plan, 17, 1)
    for kind_index, label in ((2, "heading"), (1, "numeral")):
        addr = f"text item {kind_index + 1} of slide 1"
        start = lines.index(f"          set theObj to {addr}")
        block = lines[start:start + 12]
        assert any("set height" in l for l in block), (label, block)


def test_gw44_cluster_heading_and_numeral_are_autosize():
    # Live r12 finding, measured on the real deck: GW 44's heading (text 1) and
    # numeral (text 0) are genuine Keynote-autosize text frames (raw geometry height
    # 0), which is why the r12 live run's `set height` was silently overridden and
    # the heading rendered off-canvas.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {44: SlideDecision(44, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[44]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK,
    )
    cluster = plan.two_column_cluster[44]
    assert cluster.heading_id in plan.autosize[44]
    assert cluster.number_id in plan.autosize[44]

    ordinal = plan.ordinals[44]
    lines = dsa._slide_lines(plan, 44, ordinal)
    for item_id, label in ((cluster.heading_id, "heading"), (cluster.number_id, "numeral")):
        rect = plan.fits[44][item_id]
        kind_index = item_id[1]
        addr = f"text item {kind_index + 1} of slide {ordinal}"
        start = lines.index(f"          set theObj to {addr}")
        block = lines[start:start + 12]
        position_i = next(i for i, l in enumerate(block) if "set position" in l)
        size_indices = [i for i, l in enumerate(block) if "set size" in l]
        assert size_indices, (label, block)
        assert all(i < position_i for i in size_indices), (label, block)
        assert block[position_i] == (
            f"          set position of theObj to {{{dsa._as_num(rect.x)}, {dsa._as_num(rect.y)}}}"
        ), (label, block)


def _gw_raw_autosize_text_ids(number):
    deck = dsa._load_deck(GW_DECK)
    objects_graph = deck[0]
    id_slide_archive = dsa._slide_archive_for_number(objects_graph, number)
    id_by_item = dsa._item_object_ids(id_slide_archive, objects_graph)
    payload, classes, _runs = load_assembly_inputs(GW_DECK)
    slides_by_number = {s["number"]: s for s in payload["slides"]}
    text_ids = [
        ("text", item["kindIndex"]) for item in slides_by_number[number]["items"] if item["kind"] == "text"
    ]
    return dsa._autosize_text_ids(text_ids, id_by_item, objects_graph)


def _write_block_at(lines, addr):
    obj_i = lines.index(f"          set theObj to {addr}")
    start = next(
        i for i in range(obj_i, -1, -1) if lines[i] == "        set wasLocked to false"
    )
    for end in range(start + 1, len(lines)):
        if lines[end] == "        set wasLocked to false":
            return lines[start:end]
    return lines[start:]


def test_gw13_stacked_long_box_is_raw_autosize_position_last():
    # L1 regression (Codex D1b live review 2 follow-up): GW 13's stacked verse box
    # (text 1) is a genuine raw-autosize frame (raw geometry height 0) even though
    # it is a plain top-level text item, not a two-column cluster -- confirm the
    # generalised detection flags it and `_slide_lines` writes size before position
    # with no `set height`.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[13]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK,
    )
    raw_autosize = _gw_raw_autosize_text_ids(13)
    assert ("text", 1) in raw_autosize
    assert ("text", 1) in plan.autosize[13]

    ordinal = plan.ordinals[13]
    lines = dsa._slide_lines(plan, 13, ordinal)
    addr = f"text item 2 of slide {ordinal}"
    block = _write_block_at(lines, addr)
    assert not any("set height" in l for l in block), block
    width_i = next(i for i, l in enumerate(block) if "set width" in l)
    position_i = next(i for i, l in enumerate(block) if "set position" in l)
    size_indices = [i for i, l in enumerate(block) if "set size" in l]
    assert size_indices, block
    assert width_i < min(size_indices) and max(size_indices) < position_i, block


def test_gw17_stacked_long_boxes_are_raw_autosize_position_last():
    # Same L1 regression as GW 13, on GW 17's two stacked verse boxes (text 1, text 2)
    # -- L1 fix round 1 correction: text 4 is raw-autosize per the graph but is not
    # kept/planned on slide 17 (deleted before planning), so asserting on it made this
    # test vacuously pass under the old skip-if-absent guard; text 1 and 2 are the two
    # stacked boxes actually present in plan.fits.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {17: SlideDecision(17, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[17]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK,
    )
    raw_autosize = _gw_raw_autosize_text_ids(17)
    assert ("text", 1) in raw_autosize
    assert ("text", 2) in raw_autosize

    ordinal = plan.ordinals[17]
    lines = dsa._slide_lines(plan, 17, ordinal)
    assert ("text", 1) in plan.fits.get(17, {})
    assert ("text", 2) in plan.fits.get(17, {})
    for kind_index in (1, 2):
        iid = ("text", kind_index)
        assert iid in plan.autosize[17]
        addr = f"text item {kind_index + 1} of slide {ordinal}"
        block = _write_block_at(lines, addr)
        assert not any("set height" in l for l in block), (kind_index, block)
        width_i = next(i for i, l in enumerate(block) if "set width" in l)
        position_i = next(i for i, l in enumerate(block) if "set position" in l)
        size_indices = [i for i, l in enumerate(block) if "set size" in l]
        assert size_indices, (kind_index, block)
        assert width_i < min(size_indices) and max(size_indices) < position_i, (kind_index, block)


# --------------------------------------------------------------------------
# L3 -- layout slot table + per-class base layout
# --------------------------------------------------------------------------

def test_layout_slots_pinned_to_plan_section_1_2():
    """Values re-measured via plan-layout/p6_template_table.py against the template
    deck (2026_Lower-Thirds (ENG).key); pinned here so a future change to the table
    is a deliberate, reviewed edit."""
    verse = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    assert verse.verse == Rect(53.6, 866.4, 1799.0, 177.0)
    assert verse.verse_pt == 45.0
    assert verse.verse_align == "left"
    assert verse.badge == Rect(63.1, 785.8, 933.1, 82.1)
    assert verse.badge_pt == 40.0

    verse1 = dsa.LAYOUT_SLOTS["Verse 1 Line (Variation 2)"]
    assert verse1.verse == Rect(53.6, 967.0, 1812.9, 73.0)
    assert verse1.badge == Rect(63.1, 878.4, 945.9, 77.0)

    point3 = dsa.LAYOUT_SLOTS["Point 3 Lines"]
    assert point3.text == Rect(53.6, 860.9, 1812.9, 177.0)
    assert point3.text_pt == 45.0
    assert point3.text_align == "centre"

    point2 = dsa.LAYOUT_SLOTS["Point (2 Lines)"]
    assert point2.text == Rect(53.6, 886.9, 1812.9, 177.0)

    blank = dsa.LAYOUT_SLOTS["Blank Black"]
    assert blank.verse is None and blank.text is None and blank.badge is None


def test_layout_for_slide_two_column_always_point_3_lines():
    assert dsa.layout_for_slide(category="verse", two_column=True, line_count=1) == "Point 3 Lines"
    assert dsa.layout_for_slide(category="content", two_column=True, line_count=None) == "Point 3 Lines"


def test_layout_for_slide_content_always_blank_black():
    assert dsa.layout_for_slide(category="content", two_column=False, line_count=None) == "Blank Black"
    assert dsa.layout_for_slide(category="content", two_column=False, line_count=3) == "Blank Black"


@pytest.mark.parametrize(
    "category,lines,expected",
    [
        ("verse", 1, "Verse 1 Line (Variation 2)"),
        ("verse", 2, "Verse Standard (Variation 2)"),
        ("verse", 3, "Verse Standard (Variation 2)"),
        ("verse", 4, None),
        ("point", 1, "Point (2 Lines)"),
        ("point", 2, "Point (2 Lines)"),
        ("point", 3, "Point 3 Lines"),
        ("point", 4, None),
    ],
)
def test_layout_for_slide_line_count_table(category, lines, expected):
    assert dsa.layout_for_slide(category=category, two_column=False, line_count=lines) == expected


def test_layout_for_slide_none_line_count_unresolved():
    assert dsa.layout_for_slide(category="verse", two_column=False, line_count=None) is None
    assert dsa.layout_for_slide(category="point", two_column=False, line_count=None) is None


def _verse_slide(number, verse_text="For God so loved the world", badge_text="John 3:16"):
    verse = _text_item(1, x=43.0, y=810.0, w=1849.0, h=200.0, runs=[{"text": verse_text, "size": 45.0}])
    verse["text"] = verse_text
    verse["font"] = "AzoSans-Regular"
    badge = _text_item(0, x=44.0, y=719.0, w=651.0, h=81.0, runs=[{"text": badge_text, "size": 40.0}])
    badge["text"] = badge_text
    badge["font"] = "AzoSans-Bold"
    return _slide(number, [verse, badge])


def _point_slide(number, text="Whatever we put into the hands of God"):
    item = _text_item(1, x=43.0, y=838.0, w=1849.0, h=215.0, runs=[{"text": text, "size": 45.0}])
    item["text"] = text
    item["font"] = "AzoSans-Regular"
    return _slide(number, [item])


def _content_slide(number):
    return _slide(number, [_image_item(0, x=0, y=0, w=1920, h=1080)])


def test_resolve_slide_layouts_and_apply_slot_rects_verse_and_point_and_content():
    from obed_edom.dsk_plan import SlideClass

    _require_font("AzoSans-Regular")
    verse = _verse_slide(1)
    point = _point_slide(2)
    content = _content_slide(3)
    payload = _payload([verse, point, content], wall=(1920.0, 1080.0))
    classes = [
        SlideClass(
            number=1, category="built", build_count=0, movie_count=0,
            kept=(("text", 1), ("text", 0)), dropped_side=(), dropped_backdrop=(),
            transition=None, is_text=True, long_text_ids=(("text", 1),),
        ),
        SlideClass(
            number=2, category="built", build_count=0, movie_count=0,
            kept=(("text", 1),), dropped_side=(), dropped_backdrop=(),
            transition=None, is_text=True, long_text_ids=(("text", 1),),
        ),
        SlideClass(
            number=3, category="static", build_count=0, movie_count=0,
            kept=(("image", 0),), dropped_side=(), dropped_backdrop=(),
            transition=None, is_text=False, long_text_ids=(),
        ),
    ]
    # Finding 2 (L3 fix round B): `resolve_slide_layouts` no longer recomputes a
    # category/line-count independently -- it just reads back the layout
    # `plan_assembly` already chose and threaded into `fits`/`text_sizes` while planning
    # (`plan.layout_names`, single source of truth), so an ``AssemblyPlan`` whose
    # `layout_names` says "verse" must have its verse rect already at that slot.
    verse_slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    point_slot = dsa.LAYOUT_SLOTS["Point 3 Lines"]
    plan = AssemblyPlan(
        kept=(1, 2, 3), ordinals={1: 1, 2: 2, 3: 3}, fits={
            1: {("text", 1): verse_slot.verse, ("text", 0): verse_slot.badge},
            2: {("text", 1): point_slot.text},
            3: {("image", 0): Rect(0.0, 0.0, 1920.0, 1080.0)},
        }, deletes={}, clips={},
        text_sizes={1: {("text", 1): 45.0, ("text", 0): 40.0}, 2: {("text", 1): 45.0}},
        autosize={}, warnings=(),
        layout_names={1: "Verse Standard (Variation 2)", 2: "Point 3 Lines"},
    )

    names = dsa.resolve_slide_layouts(payload, classes, plan)
    assert names[1] == "Verse Standard (Variation 2)"
    assert names[2] == "Point 3 Lines"
    assert names[3] == "Blank Black"

    verse_id = classes[0].long_text_ids[0]
    assert plan.fits[1][verse_id] == verse_slot.verse
    assert plan.text_sizes[1][verse_id] == 45.0
    badge_iid = next(iid for iid in classes[0].kept if iid != verse_id and iid[0] == "text")
    assert plan.fits[1][badge_iid] == verse_slot.badge
    assert plan.fits[1][badge_iid].x == 63.1
    assert plan.text_sizes[1][badge_iid] == 40.0

    assert plan.fits[3] == {("image", 0): Rect(0.0, 0.0, 1920.0, 1080.0)}


def test_build_assembly_script_per_slide_layout_names():
    plan = _clip_plan()
    names = {8: "Point 3 Lines", 32: "Blank Black"}
    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"),
        slide_layout_names=names,
    )
    assert 'set wantLayoutName to "Point 3 Lines"' in script or "Point 3 Lines" in script
    assert "resolvedLayout" in script
    assert "set base layout of slide" in script
    assert "blackNames" not in script


# --------------------------------------------------------------------------
# r13 root cause -- `set base layout` materializes the layout's own unfilled tagged
# slots (verse/badge text, pill image) onto the slide as new, slide-owned drawables
# PREPENDED ahead of the slide's real content, shifting every downstream index-addressed
# write/delete. The live pass must delete those materialized instances immediately after
# each `set base layout`, before any other per-slide statement.
# --------------------------------------------------------------------------
def test_build_assembly_script_emits_layout_placeholder_cleanup_for_verse_slide():
    plan = _clip_plan()
    names = {8: "Verse Standard (Variation 2)", 32: "Blank Black"}
    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"),
        slide_layout_names=names,
    )
    lines = script.splitlines()
    ordinal = plan.ordinals[8]
    set_line = next(
        ln for ln in lines
        if ln.startswith(f"      set base layout of slide {ordinal} of theDoc to resolvedLayout")
    )
    set_idx = lines.index(set_line)

    expected = [
        f"      set textBefore to count of text items of slide {ordinal} of theDoc",
        f"      set imagesBefore to count of images of slide {ordinal} of theDoc",
        f"      set moviesBefore to count of movies of slide {ordinal} of theDoc",
        f"      set groupsBefore to count of groups of slide {ordinal} of theDoc",
        set_line,
        f"      set textAfter to count of text items of slide {ordinal} of theDoc",
        f"      set imagesAfter to count of images of slide {ordinal} of theDoc",
        f"      set moviesAfter to count of movies of slide {ordinal} of theDoc",
        f"      set groupsAfter to count of groups of slide {ordinal} of theDoc",
        '      if moviesAfter is not moviesBefore then error "layout placeholders: '
        'slide 8 movies changed after set base layout"',
        '      if groupsAfter is not groupsBefore then error "layout placeholders: '
        'slide 8 groups changed after set base layout"',
        "      repeat (textAfter - textBefore) times",
        f"        delete text item 1 of slide {ordinal} of theDoc",
        "      end repeat",
        "      repeat (imagesAfter - imagesBefore) times",
        f"        delete image 1 of slide {ordinal} of theDoc",
        "      end repeat",
        f"      set textFinal to count of text items of slide {ordinal} of theDoc",
        f"      set imagesFinal to count of images of slide {ordinal} of theDoc",
        '      if textFinal is not textBefore then error "layout placeholders: slide 8 '
        'text " & textFinal & " != " & textBefore & " after cleanup"',
        '      if imagesFinal is not imagesBefore then error "layout placeholders: slide 8 '
        'images " & imagesFinal & " != " & imagesBefore & " after cleanup"',
    ]
    start = set_idx - 4
    assert lines[start : start + len(expected)] == expected

    # The cleanup (and every other slide's `set base layout`) precedes ALL `_slide_lines`
    # per-slide statements -- every base-layout line comes before the first per-slide
    # `on error` marker `_slide_lines` emits.
    first_slide_body_idx = next(i for i, ln in enumerate(lines) if 'log ("OBED"' in ln)
    assert start < first_slide_body_idx
    assert all("set base layout of slide" not in ln for ln in lines[first_slide_body_idx:])


def test_build_assembly_script_preserve_emits_no_layout_cleanup():
    plan = _clip_plan()
    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"),
        layout_policy="preserve",
    )
    assert "set base layout of slide" not in script
    assert "textBefore" not in script
    assert "layout placeholders" not in script


def test_gw13_resolves_verse_standard_and_slot_rects(tmp_path):
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[13]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
    )
    names = dsa.resolve_slide_layouts(payload, classes, plan)
    assert names[13] == "Verse Standard (Variation 2)"
    verse_id = by_number[13].long_text_ids[0]
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    verse_rect = plan.fits[13][verse_id]
    # Finding 1: the verse is TOP-anchored inside the slot band (content-height rect,
    # not a literal slot-rect override) -- x/w/y match the slot exactly (position-last,
    # per the gold measurement/deletion probe), and the saved height stays within the
    # slot's own height (`stack_bands[13]` IS the slot band, see below).
    assert verse_rect.x == slot.verse.x
    assert verse_rect.w == slot.verse.w
    assert verse_rect.y == pytest.approx(slot.verse.y)
    assert verse_rect.h <= slot.verse.h
    badge_id, badge_twin_id = dsa._find_verse_badge_id(by_number[13], {
        (item["kind"], item["kindIndex"]): item for item in payload["slides"][12]["items"]
    })
    assert badge_id is not None
    assert plan.fits[13][badge_id].x == 63.1
    # Finding 4: the badge is snapped to the EXACT slot rect, not reflowed from the
    # verse content top (previously 774.3 instead of 785.8 for a full Standard slot).
    assert plan.fits[13][badge_id].y == 785.8
    # Badge twin (finding: GW13's badge is a text item WITH a duplicate outline shape
    # sharing its source rect/text) -- both must land on the exact same slot rect, not
    # just the text half, else the shape twin keeps its own independently-fitted rect
    # and the visible glyphs split away from the slot.
    assert badge_twin_id is not None and badge_twin_id[0] == "shape"
    assert plan.slot_badge_twin_ids[13] == badge_twin_id
    assert plan.fits[13][badge_twin_id] == plan.fits[13][badge_id] == slot.badge

    # Finding 2: `stack_bands`/`run_sizes` derive from the SAME slot as `fits`, not a
    # post-plan override left behind -- GW 13's verse keeps a mixed-emphasis run (its
    # 85pt highlight against the 70pt body), so `_slide_lines` must see the 45pt-scaled
    # ranges in `run_sizes` (it prefers `run_sizes` over `text_sizes`), pinned exactly:
    # t = 45 / 70 (the body/lead size), so the 85pt run becomes 85 * 45/70 = 54.642857pt,
    # capped at gold's 50pt (S2/owner decision) -- the non-split-slot sibling of the
    # split path's own cap, applied by `_run_size_ranges(..., cap=_EMPHASIS_CAP_PT)` at
    # the slot-fit call site only (`is_slot_fit`), never a generic `fit_text_stack` t.
    assert plan.stack_bands[13] == dsa._slot_band(slot.verse)
    expected_ranges = [
        (1, 1, 45.0), (2, 6, 45.0), (7, 10, 45.0), (11, 90, 45.0),
        (91, 146, 50.0), (147, 149, 45.0),
    ]
    actual_ranges = plan.run_sizes[13][verse_id]
    assert len(actual_ranges) == len(expected_ranges)
    for (a_start, a_end, a_size), (e_start, e_end, e_size) in zip(actual_ranges, expected_ranges):
        assert a_start == e_start and a_end == e_end
        assert a_size == pytest.approx(e_size)

    # The emitted script sets THIS slide's base layout by literal ordinal, matching
    # `plan.layout_names[13]` -- the old blanket-assignment bug (finding 1 of the
    # earlier review) would still have satisfied a looser "any base layout line" check.
    slide_layout_names = dsa.resolve_slide_layouts(payload, classes, plan)
    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"),
        layout_policy="import", slide_layout_names=slide_layout_names,
    )
    ordinal = plan.ordinals[13]
    assert f'set base layout of slide {ordinal} of theDoc to resolvedLayout' in script

    # Both the text item and its shape twin get the slot's exact width/height/position
    # written -- neither is left to its own independently-fitted rect.
    text_addr = f"text item {badge_id[1] + 1} of slide {ordinal}"
    shape_addr = f"shape {badge_twin_id[1] + 1} of slide {ordinal}"
    for addr in (text_addr, shape_addr):
        idx = script.index(f"set theObj to {addr}")
        block = script[idx : idx + 400]
        assert f"set width of theObj to {dsa._as_num(slot.badge.w)}" in block
        assert f"set height of theObj to {dsa._as_num(slot.badge.h)}" in block
        assert (
            f"set position of theObj to {{{dsa._as_num(slot.badge.x)}, {dsa._as_num(slot.badge.y)}}}"
            in block
        )


def test_build_refit_round_keeps_slot_rect_as_refit_authority(tmp_path):
    # Finding 2's refit-authority requirement: a live refit round must re-fit INSIDE the
    # slot, not `DEFAULT_BAND` -- `_build_refit_round` already reads `plan.stack_bands`,
    # so once planning threads the slot band in there (rather than leaving it behind a
    # post-plan override), a refit naturally stays inside the slot without any change to
    # `_build_refit_round` itself.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {13: SlideDecision(13, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[13]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
    )
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    assert plan.stack_bands[13] == dsa._slot_band(slot.verse)
    verse_id = by_number[13].long_text_ids[0]
    slides_by_number = {s["number"]: s for s in payload["slides"]}
    predicted_h = plan.fits[13][verse_id].h
    refits = dsa._build_refit_round(
        plan, slides_by_number, {(13, "text:1")}, {(13, "text:1"): predicted_h + 10.0},
        BAND, 24.0, [], {},
    )
    refit_rect = refits[13][verse_id].rect
    assert refit_rect.x == slot.verse.x
    assert refit_rect.w == slot.verse.w
    assert refit_rect.y == pytest.approx(slot.verse.y)
    assert refit_rect.h <= slot.verse.h + 0.01


def test_gw38_verse_over_three_lines_splits_at_the_standard_slot():
    # Owner Q2/finding 3: GW 38's verse (a real deck slide, found by scanning the WHOLE
    # deck rather than only the r12b keep list) needs 7 lines at 45pt in the Standard
    # slot width (1799pt) -- it must split into parts of at most 3 lines each, every
    # part fitted against the Standard verse/badge slots, never `DEFAULT_BAND`.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    cls38 = by_number[38]
    verse_id = cls38.long_text_ids[0]
    items = {(it["kind"], it["kindIndex"]): it for it in payload["slides"][37]["items"]}
    full_text = items[verse_id]["text"]
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    assert dsa._find_verse_badge_id(cls38, items)[0] is not None
    assert line_count(full_text, items[verse_id]["font"], 45.0, slot.verse.w) > 3

    decisions = {38: SlideDecision(38, "in_deck")}
    plan = plan_assembly(
        payload, [cls38], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
    )
    assert plan.layout_names[38] == "Verse Standard (Variation 2)"
    parts = plan.splits[38]
    assert len(parts) >= 3

    seen_end = 0
    for part in parts:
        assert part.fits[verse_id] == slot.verse
        start, end = part.char_window
        assert part.char_total == len(full_text)
        # Contiguous in source order, modulo the wrap-point separator(s) dropped between
        # two consecutive wrapped lines (`wrap_line_spans_runs` excludes them, S1): at
        # most a space/thin-space plus a hard paragraph break (U+2028/U+2029), never a
        # real character of verse text.
        gap = full_text[seen_end:start - 1]
        assert 0 <= len(gap) <= 2
        assert all(ch in " \xa0   " for ch in gap)
        seen_end = end
        part_text = full_text[start - 1:end]
        assert line_count(part_text, items[verse_id]["font"], 45.0, slot.verse.w) <= 3
    assert seen_end == len(full_text)


def test_gw38_split_part_emits_character_deletes_outside_its_window():
    # The emitter must trim the live box down to just this part's text (copy-and-
    # transform, never a literal text replacement) -- deleting the tail first, then the
    # head, both indexed against the box's ORIGINAL (pre-delete) text so they land on
    # the same characters whose sizes were just set.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    cls38 = by_number[38]
    decisions = {38: SlideDecision(38, "in_deck")}
    plan = plan_assembly(
        payload, [cls38], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
    )
    ordinal = plan.ordinals[38]
    part0_lines = dsa._slide_lines(plan, 38, ordinal, part=0)
    part0 = "\n".join(part0_lines)
    part = plan.splits[38][0]
    start, end = part.char_window
    total = part.char_total
    assert f"delete characters {end + 1} thru {total} of object text of theObj" in part0
    assert start == 1  # part 0 starts at the top of the box -- no head delete expected
    assert "delete characters 1 thru" not in part0


def test_gw38_split_part_run_sizes_capped_at_50pt():
    # GW 38 part 0 carries an emphasis run that would scale to 85 * 45/70 =
    # 54.642857...pt uncapped -- owner decision: gold's flat 50pt cap applies, never
    # the source ratio (pin GW 38's own runs, real deck).
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {38: SlideDecision(38, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[38]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, fw_deck=GW_DECK, layout_policy="import",
    )
    part0 = plan.splits[38][0]
    verse_id = next(iter(part0.stacked_ids))
    sizes = {round(sz, 2) for _lo, _hi, sz in part0.run_sizes[verse_id]}
    assert 50.0 in sizes
    assert round(85.0 * 45.0 / 70.0, 2) not in sizes  # 54.64pt, the uncapped ratio


def test_gw38_split_refuses_a_character_level_build_on_the_split_box():
    # S4 §3: a real char-window split candidate (GW 38) whose box carries a
    # character-level build must be refused during planning, naming the box and effect,
    # before any split geometry/deletes are emitted.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    cls38 = by_number[38]
    verse_id = cls38.long_text_ids[0]
    decisions = {38: SlideDecision(38, "in_deck")}
    builds = {38: {"builds": [
        {"kind": verse_id[0], "kindIndex": verse_id[1], "effect": "apple:dissolve character", "animationType": "In"},
    ]}}
    with pytest.raises(AssemblyRefusal, match=rf"box {verse_id[1]}.*apple:dissolve character"):
        plan_assembly(
            payload, [cls38], decisions=decisions, band=BAND, clips={}, runs=runs,
            all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
            builds=builds,
        )


# --------------------------------------------------------------------------- S3: split
# part geometry + per-ordinal offline measurement/refit/refusal (dsk_layout_split_engine
# plan §1.3/§2.3/§3 S3, dsk_pieceD2b's offline naturalSize/refit machinery extended to
# split parts).


def _two_part_split_plan(number: int, base_ordinal: int) -> tuple[AssemblyPlan, dict]:
    """A minimal char-window two-part split on one source box, both parts sharing the
    slide's stack band/slot rect -- just enough to exercise ``_offline_measure``/
    ``_eligible_refit_items``/``_refit_still_over_budget`` without a real deck."""
    item_id = ("text", 1)
    rect = Rect(43.0, 800.0, 1849.0, 200.0)
    part0 = SplitPart(
        fits={item_id: rect}, deletes=(), text_sizes={}, stacked_ids=frozenset({item_id}),
        autosize=frozenset({item_id}), char_window=(1, 40), char_total=80,
    )
    part1 = SplitPart(
        fits={item_id: rect}, deletes=(), text_sizes={},
        run_sizes={item_id: ((1, 40, 45.0),)}, stacked_ids=frozenset({item_id}),
        autosize=frozenset({item_id}), char_window=(41, 80), char_total=80,
    )
    plan = AssemblyPlan(
        kept=(number,), ordinals={number: base_ordinal}, fits={}, deletes={}, clips={},
        text_sizes={}, autosize={}, warnings=(), splits={number: (part0, part1)},
        stack_bands={number: BAND},
    )
    item = _text_item(1, x=43, y=800, w=1849, h=200, runs=[{"size": 45.0}])
    slides_by_number = {number: _slide(number, [item])}
    return plan, slides_by_number


def test_offline_measure_keys_split_parts_by_output_ordinal():
    plan, _slides = _two_part_split_plan(14, base_ordinal=5)

    def fake_offline_text_rects(_key_path, *, deck=None):
        rects_by_ordinal = {
            5: {("text", 0): (43.0, 800.0, 1849.0, 120.0)},
            6: {("text", 0): (43.0, 800.0, 1849.0, 150.0)},
        }
        return (rects_by_ordinal, set())

    import obed_edom.dsk_assemble as _dsa
    orig = _dsa.offline_text_rects
    _dsa.offline_text_rects = fake_offline_text_rects
    try:
        warnings: list[str] = []
        measured, bands, measure_warnings = dsa._offline_measure(Path("/tmp/staged.key"), plan, {}, warnings)
    finally:
        _dsa.offline_text_rects = orig
    assert measure_warnings == []
    assert measured == {(14, "text:1:5"): 120.0, (14, "text:1:6"): 150.0}
    assert bands[(14, "text:1:5")] == (800.0, 920.0)
    assert bands[(14, "text:1:6")] == (800.0, 950.0)


def test_eligible_refit_items_includes_split_parts_keyed_by_ordinal():
    plan, _slides = _two_part_split_plan(14, base_ordinal=5)
    eligible = dsa._eligible_refit_items(plan, 14)
    assert eligible == frozenset({(5, ("text", 1)), (6, ("text", 1))})


def test_refit_still_over_budget_reads_split_part_rect_and_slide_band():
    plan, _slides = _two_part_split_plan(14, base_ordinal=5)
    measured = {(14, "text:1:5"): 250.0, (14, "text:1:6"): 150.0}
    over = dsa._refit_still_over_budget(plan, measured, {(14, "text:1:5"), (14, "text:1:6")})
    assert over == {(14, "text:1:5")}


def test_split_part_still_over_budget_after_max_refits_refuses_under_text_fit_warn():
    # A part's rect/geometry is never re-windowed live (C5) -- an over-budget part must
    # still exhaust `_MAX_REFITS` measurement rounds (each reading the same offline
    # naturalSize, since nothing live ever corrects it) before it refuses.
    plan, slides_by_number = _two_part_split_plan(14, base_ordinal=5)

    def fake_offline_text_rects(_key_path, *, deck=None):
        rects_by_ordinal = {
            5: {("text", 0): (43.0, 800.0, 1849.0, 260.0)},  # over part 0's 200pt rect
            6: {("text", 0): (43.0, 800.0, 1849.0, 150.0)},  # part 1 fits
        }
        return (rects_by_ordinal, set())

    import obed_edom.dsk_assemble as _dsa
    monkeypatch_orig = _dsa.offline_text_rects
    _dsa.offline_text_rects = fake_offline_text_rects
    try:
        logs: list[str] = []
        with pytest.raises(AssemblyRefusal, match="slide 14: text text:1:5 still overflows after refit"):
            dsa._run_refit_and_finalize(
                plan, batch=None, slides_by_number=slides_by_number,
                band=BAND, min_text_pt=24.0, allow_split=True, text_fit="warn",
                staging_path=Path("/tmp/staged.key"), measured={}, overflows=[],
                warnings=[], log=logs.append,
            )
    finally:
        _dsa.offline_text_rects = monkeypatch_orig
    assert any("split slide, part geometry is not re-run" in l for l in logs)


def test_offline_measure_missing_for_split_part_refuses_immediately():
    plan, slides_by_number = _two_part_split_plan(14, base_ordinal=5)

    def fake_offline_text_rects_missing_part1(_key_path, *, deck=None):
        # Ordinal 6 (part 1) is entirely absent from the saved deck's read.
        return ({5: {("text", 0): (43.0, 800.0, 1849.0, 120.0)}}, set())

    import obed_edom.dsk_assemble as _dsa
    orig = _dsa.offline_text_rects
    _dsa.offline_text_rects = fake_offline_text_rects_missing_part1
    try:
        with pytest.raises(AssemblyRefusal, match="text:1:6 offline measure missing"):
            dsa._run_refit_and_finalize(
                plan, batch=None, slides_by_number=slides_by_number,
                band=BAND, min_text_pt=24.0, allow_split=True, text_fit="warn",
                staging_path=Path("/tmp/staged.key"), measured={}, overflows=[],
                warnings=[], log=lambda _msg: None,
            )
    finally:
        _dsa.offline_text_rects = orig


def test_split_part_emitted_script_order_is_width_size_delete_position_no_height():
    plan, _slides = _two_part_split_plan(14, base_ordinal=5)
    ordinal = plan.ordinals[14] + 1  # part 1's own ordinal
    part1_lines = dsa._slide_lines(plan, 14, ordinal, part=1)
    script = "\n".join(part1_lines)
    assert "set height" not in script
    width_i = next(i for i, l in enumerate(part1_lines) if "set width of theObj" in l)
    size_i = next(i for i, l in enumerate(part1_lines) if "set size of characters" in l)
    delete_i = next(i for i, l in enumerate(part1_lines) if l.strip().startswith("delete characters 1 thru"))
    position_i = next(i for i, l in enumerate(part1_lines) if "set position of theObj" in l)
    assert width_i < size_i < delete_i < position_i


@pytest.mark.deck
def test_gw38_split_part_rects_pinned_to_the_standard_slot():
    # Finding 2/3/6: every part's verse rect is the exact Standard slot (top-anchored,
    # position-last), the badge is snapped to the slot badge on every part (not the
    # pre-fix (63.1, 774.3) reflowed position), `layout_names`/`slot_badge_ids` are
    # recorded, and the recorded band/measurement key are the Standard slot band --
    # never the reduced pre-split band. Windows are pinned literals from the review.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {38: SlideDecision(38, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[38]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
    )
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    assert plan.layout_names[38] == "Verse Standard (Variation 2)"
    assert plan.stack_bands[38] == dsa._slot_band(slot.verse)
    assert 38 in plan.stack_t
    badge_id = plan.slot_badge_ids.get(38)
    assert badge_id is not None
    expected_windows = [(1, 91), (93, 185), (187, 271), (273, 296)]
    parts = plan.splits[38]
    assert len(parts) == len(expected_windows)
    for part, expected_window in zip(parts, expected_windows):
        verse_id = next(iter(part.stacked_ids))
        rect = part.fits[verse_id]
        assert (round(rect.x, 1), round(rect.y, 1), round(rect.w, 1)) == (53.6, 866.4, 1799.0)
        assert part.char_window == expected_window
        badge_rect = part.fits[badge_id]
        assert (round(badge_rect.x, 1), round(badge_rect.y, 1)) == (63.1, 785.8)


def test_gw38_split_literal_band_badge_keys_deletes_and_zero_build_multiplicity():
    # Review 4 finding 3: pins the band/badge as LITERAL numbers (not recomputed via
    # `_slot_band`), the offline measurement keys, all four per-part delete sequences
    # (tail then head, literal character ranges), and that GW 38's source slide carries
    # zero builds -- so a real assembled deck's split parts clone zero builds, never a
    # surplus/missing multiset mismatch.
    from obed_edom.iwa_builds import deck_builds

    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {38: SlideDecision(38, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[38]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
    )
    assert plan.stack_bands[38] == Band(1043.4, 177.0, 53.6, 1852.6, 4)
    badge_id = plan.slot_badge_ids[38]
    verse_id = next(iter(plan.splits[38][0].stacked_ids))
    assert verse_id == ("text", 1)
    for part in plan.splits[38]:
        assert part.fits[badge_id] == Rect(63.1, 785.8, 933.1, 82.1)

    ordinal0 = plan.ordinals[38]
    assert dsa._eligible_refit_items(plan, 38) == frozenset(
        (ordinal0 + i, verse_id) for i in range(4)
    )
    expected_deletes = [
        ["delete characters 92 thru 296 of object text of theObj"],
        [
            "delete characters 186 thru 296 of object text of theObj",
            "delete characters 1 thru 92 of object text of theObj",
        ],
        [
            "delete characters 272 thru 296 of object text of theObj",
            "delete characters 1 thru 186 of object text of theObj",
        ],
        ["delete characters 1 thru 272 of object text of theObj"],
    ]
    for part_no, expected in enumerate(expected_deletes):
        lines = dsa._slide_lines(plan, 38, ordinal0 + part_no, part=part_no)
        got = [line.strip() for line in lines if "delete characters" in line]
        assert got == expected

    assert deck_builds(GW_DECK)[38]["builds"] == []


# Local operator deck; removed in the 2026-09-16 dsk-d4-work cleanup, so this skips unless regenerated.
R12B = Path.home() / "Desktop/dsk-d4-work/out-r12b/Sermon_PK_DSK.key"


def _require_r12b_deck():
    if not R12B.is_file():
        pytest.skip(f"deck not present (local operator file): {R12B}")


# `evidence-r12b/run.out`'s own post-refit offline reads for the deck's unsplit stacked
# boxes -- pinned so this S3 change (widening `_offline_measure` to also cover split
# parts) provably leaves an unsplit slide's own measurement untouched. r12b predates the
# split engine (no `plan.splits` entries at all), so rather than re-deriving a plan that
# now might legitimately split some of these slides (S1/S2 moved GW 28 onto a real
# split), this reads the SAVED deck itself as the source of truth for which staged text
# items exist per ordinal -- an identity `(kind, idx)` plan, matching `_offline_measure`'s
# non-split branch, which S3 leaves untouched (it only added a new split branch above it).
R12B_UNSPLIT_OFFLINE_H = {13: 219.0, 28: 241.0, 46: 179.0, 52: 193.0}
R12B_UNSPLIT_STAGED_IDX = {13: 1, 28: 1, 46: 2, 52: 1}
R12B_ORDINAL = {13: 2, 28: 7, 46: 11, 52: 15}


@pytest.mark.deck
def test_offline_measure_unsplit_keys_match_r12b_run_out_regression():
    _require_r12b_deck()
    warnings: list[str] = []
    for number, expected_h in R12B_UNSPLIT_OFFLINE_H.items():
        ordinal = R12B_ORDINAL[number]
        rects_by_ordinal, _soft = dsa.offline_text_rects(R12B)
        text_count = sum(1 for kind, _idx in rects_by_ordinal.get(ordinal, {}) if kind == "text")
        plan = AssemblyPlan(
            kept=(number,), ordinals={number: ordinal},
            fits={number: {("text", i): Rect(0.0, 0.0, 0.0, 0.0) for i in range(text_count)}},
            deletes={number: ()}, clips={}, text_sizes={}, autosize={}, warnings=(),
        )
        measured, _bands, measure_warnings = dsa._offline_measure(R12B, plan, {}, warnings)
        assert measure_warnings == [], f"slide {number}: {measure_warnings}"
        key = (number, f"text:{R12B_UNSPLIT_STAGED_IDX[number]}")
        assert measured.get(key) == pytest.approx(expected_h, abs=1.0), f"slide {number}: {measured}"


# S2/§1.1 re-measurement (height-budget pack, post-cap): expected part count and, per
# part, the flat-45pt line count of that part's own text (pinned literals, not derived
# from the function under test). GW 28/30/36/52 moved off the old flat 3-line chunker's
# no-op 1-part "split" to a real 2-part split; GW 18/38 gained a part (the old chunker's
# fixed 3-line boundary under-filled a part relative to the height budget); GW 12/19/20/
# 29/35 keep the same part count as before S2 (their boundaries may still shift a few
# characters against the old chunker, untested here). GW 49 stays refused (S1's
# unresolved-run policy, out of S2's scope) and GW 5/54 stay refused (group-child,
# S5's scope).
GW_S2_SPLIT_CANDIDATES: dict[int, list[int]] = {
    12: [2, 2],
    18: [2, 2, 1],
    19: [2, 3],
    20: [3, 2],
    28: [2, 1],
    29: [3, 1],
    30: [2, 1],
    35: [3, 2],
    36: [2, 1],
    38: [2, 2, 2, 1],
    52: [2, 1],
}


@pytest.mark.deck
def test_gw_s2_split_candidates_part_counts_and_line_counts_pinned():
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    for number, expected_lines in GW_S2_SPLIT_CANDIDATES.items():
        cls = by_number[number]
        decisions = {number: SlideDecision(number, "in_deck")}
        plan = plan_assembly(
            payload, [cls], decisions=decisions, band=BAND, clips={}, runs=runs,
            all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
        )
        assert number in plan.splits, f"slide {number}: expected a split"
        parts = plan.splits[number]
        assert len(parts) == len(expected_lines), f"slide {number}: part count"
        items = {(it["kind"], it["kindIndex"]): it for it in payload["slides"][number - 1]["items"]}
        verse_id = cls.long_text_ids[0]
        full_text = items[verse_id]["text"]
        for i, part in enumerate(parts):
            start, end = part.char_window
            part_text = full_text[start - 1:end]
            lc = line_count(part_text, items[verse_id]["font"], 45.0, slot.verse.w)
            assert lc == expected_lines[i], f"slide {number} part {i}: line count"
            assert lc <= 3


@pytest.mark.deck
def test_gw28_30_36_52_never_produce_a_one_part_split():
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    for number in (28, 30, 36, 52):
        decisions = {number: SlideDecision(number, "in_deck")}
        plan = plan_assembly(
            payload, [by_number[number]], decisions=decisions, band=BAND, clips={}, runs=runs,
            all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
        )
        assert number in plan.splits
        assert len(plan.splits[number]) >= 2, f"slide {number}: no-op 1-part split"


def test_gw21_image_slide_resolves_blank_black():
    _require_gw_deck()
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {21: SlideDecision(21, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[21]], decisions=decisions, band=BAND, clips={}, runs=runs, all_classes=classes,
    )
    names = dsa.resolve_slide_layouts(payload, classes, plan)
    assert names[21] == "Blank Black"


def test_gw44_50_two_column_resolves_point_3_lines_geometry_unchanged():
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {44: SlideDecision(44, "in_deck"), 50: SlideDecision(50, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[44], by_number[50]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
    )
    names = dsa.resolve_slide_layouts(payload, classes, plan)
    assert names[44] == "Point 3 Lines"
    assert names[50] == "Point 3 Lines"
    plan_preserve = plan_assembly(
        payload, [by_number[44], by_number[50]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="preserve",
    )
    assert plan.fits[44] == plan_preserve.fits[44]
    assert plan.fits[50] == plan_preserve.fits[50]


def test_find_verse_badge_id_requires_matched_text_shape_not_any_lone_text():
    # Finding 1: the badge predicate is the SAME one D1b's `_heading_cluster` uses for
    # its own badge -- a top-level text matching exactly one top-level shape's rect and
    # text -- never "any lone extra text". A lone extra text with no matching shape
    # (e.g. a stray caption) must NOT be treated as a badge.
    from obed_edom.dsk_plan import SlideClass

    verse = _text_item(1, x=43.0, y=810.0, w=1849.0, h=200.0, runs=[{"text": "verse body", "size": 45.0}])
    verse["text"] = "verse body"
    verse["font"] = "AzoSans-Regular"
    stray = _text_item(0, x=44.0, y=719.0, w=651.0, h=81.0, runs=[{"text": "unmatched caption", "size": 40.0}])
    stray["text"] = "unmatched caption"
    stray["font"] = "AzoSans-Bold"
    items_by_id = {("text", 1): verse, ("text", 0): stray}
    cls = SlideClass(
        number=1, category="built", build_count=0, movie_count=0,
        kept=(("text", 1), ("text", 0)), dropped_side=(), dropped_backdrop=(),
        transition=None, is_text=True, long_text_ids=(("text", 1),),
    )
    assert dsa._find_verse_badge_id(cls, items_by_id) == (None, None)

    badge_shape = {"kind": "shape", "kindIndex": 0, "x": 44.0, "y": 719.0, "w": 651.0, "h": 81.0}
    badge_shape["text"] = "unmatched caption"
    items_by_id_with_shape = dict(items_by_id)
    items_by_id_with_shape[("shape", 0)] = badge_shape
    cls_with_shape = dsk_plan.SlideClass(
        **{**cls.__dict__, "kept": (("text", 1), ("text", 0), ("shape", 0))}
    )
    # Finding 1 (badge twin): the matched shape is a real, independent duplicate object
    # (an outline twin drawn over the plain text badge), returned alongside the text id
    # so both can be pinned to the slot rect.
    assert dsa._find_verse_badge_id(cls_with_shape, items_by_id_with_shape) == (("text", 0), ("shape", 0))


def test_find_verse_badge_id_falls_back_to_retained_group_child_short_fit():
    # Finding 1: a group-child verse (GW5/51/53/54-shaped) leaves no top-level text
    # badge behind -- the badge is a retained group-child short item, already placed in
    # `short_fit` by the time the badge predicate runs.
    from obed_edom.dsk_plan import SlideClass

    cls = SlideClass(
        number=1, category="built", build_count=0, movie_count=0,
        kept=(("group", 0),), dropped_side=(), dropped_backdrop=(),
        transition=None, is_text=True, long_text_ids=(("groupchild", 0, "text", 1),),
    )
    short_fit = {("groupchild", 0, "shape", 0): Rect(63.1, 0.0, 645.0, 92.0)}
    assert dsa._find_verse_badge_id(cls, {}, short_fit=short_fit) == (("groupchild", 0, "shape", 0), None)
    # Ambiguous with two group-child short items: refuse to guess.
    short_fit_ambiguous = dict(short_fit)
    short_fit_ambiguous[("groupchild", 0, "shape", 1)] = Rect(63.1, 0.0, 200.0, 92.0)
    assert dsa._find_verse_badge_id(cls, {}, short_fit=short_fit_ambiguous) == (None, None)


def test_gw51_group_child_verse_resolves_verse_standard_and_slot_rects():
    # Finding 1: GW 51 repeats GW 50's "Faith" heading -- the two-column cluster drops
    # (D1b's repeat-heading rule), leaving a plain group-child verse whose badge is the
    # retained group-child reference ("Luke 5") -- it must resolve to the verse layout,
    # not silently fall back to Blank Black (the round-B bug).
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {51: SlideDecision(51, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[51]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
    )
    names = dsa.resolve_slide_layouts(payload, classes, plan)
    assert names[51] == "Verse Standard (Variation 2)"
    verse_id = by_number[51].long_text_ids[0]
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    verse_rect = plan.fits[51][verse_id]
    assert verse_rect.x == slot.verse.x
    assert verse_rect.w == slot.verse.w
    assert verse_rect.y == pytest.approx(slot.verse.y)
    badge_ids = [
        iid for iid in plan.fits[51]
        if iid[0] == "groupchild" and iid != verse_id
    ]
    assert len(badge_ids) == 1
    badge_id = badge_ids[0]
    badge_rect = plan.fits[51][badge_id]
    assert badge_rect.x == slot.badge.x
    assert badge_rect.w == slot.badge.w
    assert badge_rect.h == slot.badge.h
    # Finding 4: the badge is EXCLUDED from the generic short-row reflow -- its y must
    # be the exact slot y, not one reflowed from the verse content top.
    assert badge_rect.y == slot.badge.y
    assert plan.slot_badge_ids[51] == badge_id


def test_staged_group_child_rect_reads_back_gw51_verse_and_badge(monkeypatch):
    # Finding 5: `_staged_group_child_rect` (the staged verifier's group-child geometry
    # composer) must find and compose GW 51's real verse + badge children -- neither
    # `None` (not found) nor an empty read -- reusing `_all_group_child_records` against
    # the slide's own group object rather than skipping group-child ids as before.
    from obed_edom.iwa_runs import slide_order  # noqa: PLC0415

    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    objects, _id_to_file, _file_ids = deck
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {51: SlideDecision(51, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[51]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
    )
    order = list(slide_order(objects))
    slide_id, _skipped = order[50]  # slide number 51, 0-indexed
    slide = objects[str(slide_id)]
    verse_id = by_number[51].long_text_ids[0]
    badge_id = plan.slot_badge_ids[51]

    verse_rect = dsa._staged_group_child_rect(objects, slide, 51, plan, verse_id)
    badge_rect = dsa._staged_group_child_rect(objects, slide, 51, plan, badge_id)
    assert verse_rect is not None
    assert badge_rect is not None
    assert verse_rect.w > 0 and verse_rect.h > 0
    assert badge_rect.w > 0 and badge_rect.h > 0


def test_gw17_two_top_level_boxes_stack_inside_the_verse_slot():
    # Finding 1: GW 17's verse is split across two top-level text boxes (not a
    # group) -- both must stack inside the SAME verse slot, not fall back to Blank
    # Black for having more than one long text box.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {17: SlideDecision(17, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[17]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
    )
    names = dsa.resolve_slide_layouts(payload, classes, plan)
    assert names[17] == "Verse Standard (Variation 2)"
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    long_ids = by_number[17].long_text_ids
    assert len(long_ids) == 2
    for iid in long_ids:
        rect = plan.fits[17][iid]
        assert rect.x == slot.verse.x
        assert rect.w == slot.verse.w
    tops = sorted(plan.fits[17][iid].y for iid in long_ids)
    bottoms = sorted(plan.fits[17][iid].y + plan.fits[17][iid].h for iid in long_ids)
    assert tops[0] == pytest.approx(slot.verse.y)
    assert bottoms[-1] <= slot.verse.y + slot.verse.h + 0.01


def test_gw17_forced_split_routes_the_generic_multi_box_branch_through_the_slot():
    # Finding 1 (review 4): GW 17's two top-level boxes fit jointly (the case above),
    # so a forced ``--split`` is the only way to exercise the generic per-box split
    # branch while a slot layout is still in effect (the same branch a GW17-shaped
    # slide would fall through to if it did NOT fit jointly). Every part must be
    # top-anchored to the slot's own band, the badge pinned exactly to the slot badge,
    # and `slot_badge_ids`/`stack_bands` recorded -- not the legacy bottom-stacked,
    # badge-unchecked placement review 4 flagged.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {17: SlideDecision(17, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[17]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
        split_overrides={17: 2},
    )
    assert plan.layout_names[17] == "Verse Standard (Variation 2)"
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    assert plan.stack_bands[17] == dsa._slot_band(slot.verse)
    badge_id = plan.slot_badge_ids.get(17)
    assert badge_id is not None
    long_ids = by_number[17].long_text_ids
    assert plan.parts[17] == 2
    assert len(plan.splits[17]) == 2
    for part in plan.splits[17]:
        assert part.fits[badge_id] == slot.badge
        verse_id = next(iid for iid in long_ids if iid in part.fits)
        verse_rect = part.fits[verse_id]
        assert verse_rect.x == slot.verse.x
        assert verse_rect.w == slot.verse.w
        assert verse_rect.y == pytest.approx(slot.verse.y)


_SET_SIZE_RE = re.compile(
    r"set size (?:of characters \d+ thru \d+ )?of object text of theObj to (-?[\d.]+)"
)


@pytest.mark.deck
def test_gw17_forced_multi_box_split_emits_45pt_lead_and_caps_emphasis():
    # DSK §4 item 12: the generic multi-box split branch used to scale every box via
    # the bare (uncapped) `fit_text_stack` fit, off the slot entirely -- GW 17's forced
    # 2-way split emitted a 54.6pt lead and a 66.3pt emphasis run instead of the slot's
    # 45pt lead and gold's 50pt emphasis cap. The slot-authoritative sub-path fixes
    # both: the lead box's own `slot_pt/box.size` scale, and
    # `_run_size_ranges(..., cap=_EMPHASIS_CAP_PT)`.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {17: SlideDecision(17, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[17]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
        split_overrides={17: 2},
    )
    assert plan.stack_t[17] == pytest.approx(45.0 / 70.0)
    ordinal0 = plan.ordinals[17]
    all_sizes: list[float] = []
    for part_no in range(plan.parts[17]):
        lines = dsa._slide_lines(plan, 17, ordinal0 + part_no, part=part_no)
        for line in lines:
            m = _SET_SIZE_RE.search(line)
            if m:
                all_sizes.append(float(m.group(1)))
    assert any(sz == pytest.approx(45.0) for sz in all_sizes)
    assert max(all_sizes) <= 50.0 + 1e-6


def test_gw38_one_part_fallback_matches_the_direct_slot_fit_geometry(monkeypatch):
    # Review 4 finding 3: no end-to-end `plan_assembly` fixture previously reached the
    # one-part fallback (`len(chunks) == 1`, S2/§2.2 -- the height-budget pack fits in
    # one part after all). Forcing `_pack_split_lines` to always report a single chunk
    # (GW 38's own real box otherwise always needs 4 parts) exercises that exact branch;
    # its geometry/badge/band/run size/split_t must equal the direct (non-split) slot
    # fit's own literal numbers -- the one-part fallback is a no-op split, not a
    # different placement.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    cls38 = by_number[38]
    verse_id = cls38.long_text_ids[0]
    items = {(it["kind"], it["kindIndex"]): it for it in payload["slides"][37]["items"]}
    full_len = len(items[verse_id]["text"])
    monkeypatch.setattr(dsa, "_pack_split_lines", lambda *a, **k: [[(0, full_len)]])

    decisions = {38: SlideDecision(38, "in_deck")}
    plan = plan_assembly(
        payload, [cls38], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
    )
    assert plan.layout_names[38] == "Verse Standard (Variation 2)"
    assert 38 not in plan.splits
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    split_t = slot.verse_pt / items[verse_id]["size"]
    stack_band = dsa._slot_band(slot.verse)
    box_runs = tuple(
        dsk_plan.Run(
            r.get("text") or "", r.get("fontName") or items[verse_id]["font"],
            (r.get("size") or items[verse_id]["size"]) * split_t,
        )
        for r in items[verse_id]["runs"]
    )
    expected_h = dsk_plan.wrapped_height_runs(box_runs, stack_band.width)
    verse_rect = plan.fits[38][verse_id]
    assert verse_rect.x == slot.verse.x
    assert verse_rect.w == slot.verse.w
    assert verse_rect.y == pytest.approx(slot.verse.y)
    assert verse_rect.h == pytest.approx(expected_h)
    assert plan.stack_bands[38] == stack_band
    badge_id = plan.slot_badge_ids[38]
    assert plan.fits[38][badge_id] == slot.badge
    assert plan.stack_t[38] == pytest.approx(split_t)
    sizes = {round(sz, 2) for _lo, _hi, sz in plan.run_sizes[38][verse_id]}
    assert 50.0 in sizes  # the same 50pt emphasis cap as the split path (S1/S2)


def test_gw52_repeat_heading_dropped_resolves_verse_standard():
    # Finding 1: GW 52 repeats GW 51's "Faith" heading -- once D1b drops it, the
    # remaining top-level text is the badge ("Luke 5") matched to its shape, so the
    # slide must resolve to a verse layout, not `Point 3 Lines` (the round-B bug, where
    # `_find_verse_badge_id` read the pre-plan `cls.kept`, still counting the
    # about-to-be-deleted heading/number/circle as ambiguous extra texts).
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {52: SlideDecision(52, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[52]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
    )
    names = dsa.resolve_slide_layouts(payload, classes, plan)
    assert names[52] == "Verse Standard (Variation 2)"
    assert 52 in plan.splits  # GW 52's verse needs more than 3 lines at 45pt
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    for part in plan.splits[52]:
        verse_id = by_number[52].long_text_ids[0]
        assert part.fits[verse_id] == slot.verse
        # Badge twin fix: BOTH the text half `_find_verse_badge_id` matched and its
        # duplicate outline shape twin are snapped to the badge slot -- the shape twin is
        # a real, independent object (not the same live item queried twice), and leaving
        # it unpinned split the visible badge away from the slot (GW 13/38/52).
        snapped = [
            iid for iid, rect in part.fits.items()
            if iid != verse_id and rect.x == slot.badge.x and rect.w == slot.badge.w
            and rect.h == slot.badge.h
        ]
        assert len(snapped) == 2
        assert set(iid[0] for iid in snapped) == {"text", "shape"}


def test_gw52_split_parts_each_get_the_dropped_heading_cluster_deletes():
    # r13 attempt 5 refusal: GW 52's repeat-heading cluster (shape/number/heading text)
    # was folded into `deletes[number]` but a stale pre-cluster `base_deletes` local was
    # threaded into each `SplitPart`, so every split part kept the heading cluster's 2
    # text items live (staged text count 2 != offline text count 4). Every part must
    # carry the SAME deletes as the (would-be) non-split slide, in the same
    # highest-index-first order, and identically across parts.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {52: SlideDecision(52, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[52]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
    )
    assert 52 in plan.splits
    parts = plan.splits[52]
    assert len(parts) == 2
    expected = plan.deletes[52]
    heading_ids = {("shape", 1), ("text", 3), ("text", 2)}
    assert heading_ids <= set(expected)
    for part in parts:
        assert part.deletes == expected

    ordinal0 = plan.ordinals[52]
    for part_no, part in enumerate(parts):
        lines = dsa._slide_lines(plan, 52, ordinal0 + part_no, part=part_no)
        delete_object_count = sum(1 for line in lines if line.strip() == "delete theObj")
        assert delete_object_count == len(part.deletes)


def test_gw51_repeat_heading_non_split_deletes_unchanged():
    # Regression pin: GW 51 (repeat heading, NOT split) must keep emitting the exact
    # same delete set it did before the split-part fix -- the fix only threads the
    # already-correct `deletes[number]` into split parts, it must not perturb the
    # non-split path at all.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {51: SlideDecision(51, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[51]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
    )
    assert 51 not in plan.splits
    assert plan.deletes[51] == (
        ("group", 1), ("image", 1), ("image", 0), ("shape", 0), ("text", 1), ("text", 0),
    )
    ordinal = plan.ordinals[51]
    lines = dsa._slide_lines(plan, 51, ordinal, part=0)
    delete_object_count = sum(1 for line in lines if line.strip() == "delete theObj")
    assert delete_object_count == len(plan.deletes[51])


def test_gw44_50_unchanged_by_finding_1_role_resolver():
    # Finding 5 regression: the two-column path (GW 44/50, first occurrence of their
    # heading) must still resolve `Point 3 Lines` with D1b's hand geometry byte-
    # identical -- finding 1's broadened slot eligibility must never touch a two-column
    # slide.
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {44: SlideDecision(44, "in_deck"), 50: SlideDecision(50, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[44], by_number[50]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
    )
    names = dsa.resolve_slide_layouts(payload, classes, plan)
    assert names[44] == "Point 3 Lines"
    assert names[50] == "Point 3 Lines"
    plan_preserve = plan_assembly(
        payload, [by_number[44], by_number[50]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="preserve",
    )
    assert plan.fits[44] == plan_preserve.fits[44]
    assert plan.fits[50] == plan_preserve.fits[50]


def test_verify_staged_layouts_refuses_wrong_layout_name(monkeypatch, tmp_path):
    # Finding 4: an alpha-safe but WRONG base layout must refuse, not silently pass --
    # the pre-existing check only asserted alpha-safety, which every layout in
    # `LAYOUT_SLOTS` satisfies.
    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1}, fits={}, deletes={}, clips={},
        text_sizes={}, autosize={}, warnings=(),
        stacked_ids={}, short_fit={},
    )

    def fake_load_deck(_path):
        return ({}, {}, {})

    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "_canvas_size", lambda objects: (1920.0, 1080.0))
    monkeypatch.setattr(dsa, "layout_alpha_safe", lambda *_a, **_k: True)
    monkeypatch.setattr(dsa, "_base_layout_slide_for_ordinal", lambda objects, ordinal: {"name": "Blank Black"})
    monkeypatch.setattr(dsa, "_slide_archive_for_ordinal", lambda objects, ordinal: {"id": "slide1"})

    with pytest.raises(AssemblyRefusal, match="resolved to 'Blank Black'"):
        dsa.verify_staged_layouts_alpha_safe(
            tmp_path / "staged.key", plan, expected_layout_names={1: "Verse Standard (Variation 2)"}
        )


def test_verify_staged_layouts_refuses_wrong_verse_rect(monkeypatch, tmp_path):
    # Finding 4: the right layout name with a retained verse rect that does NOT match
    # the slot must also refuse. `fits` carries the single retained text item so
    # `_staged_id_for` (finding 5) translates source id (text, 1) to staged (text, 0).
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1}, fits={1: {("text", 1): slot.verse}}, deletes={}, clips={},
        text_sizes={}, autosize={}, warnings=(),
        stacked_ids={1: frozenset({("text", 1)})}, short_fit={},
    )

    def fake_load_deck(_path):
        return ({}, {}, {})

    wrong_rec = {"kind": "text", "kindIndex": 0, "x": 0.0, "y": 0.0, "w": 100.0, "h": 50.0}
    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "_canvas_size", lambda objects: (1920.0, 1080.0))
    monkeypatch.setattr(dsa, "layout_alpha_safe", lambda *_a, **_k: True)
    monkeypatch.setattr(
        dsa, "_base_layout_slide_for_ordinal",
        lambda objects, ordinal: {"name": "Verse Standard (Variation 2)"},
    )
    monkeypatch.setattr(dsa, "_slide_archive_for_ordinal", lambda objects, ordinal: {"id": "slide1"})
    monkeypatch.setattr(dsa, "compose_geometry", lambda slide, objects: [wrong_rec])

    with pytest.raises(AssemblyRefusal, match="does not match"):
        dsa.verify_staged_layouts_alpha_safe(
            tmp_path / "staged.key", plan, expected_layout_names={1: "Verse Standard (Variation 2)"}
        )


def test_verify_staged_layouts_accepts_matching_verse_rect(monkeypatch, tmp_path):
    # Finding 1/6: a TOP-anchored, contained verse rect (y == slot.y, h < slot.h, the
    # gold measurement/deletion-probe shape -- not the old bottom-aligned fixture) must
    # pass. `fits` carries both retained top-level items so `_staged_id_for` ranks them
    # (badge (text, 0) -> staged (text, 0), verse (text, 1) -> staged (text, 1)); the
    # badge rect is the CORRECT slot badge x/y/w/h (finding 4/7: a wrong y must no
    # longer pass silently -- see test_verify_staged_layouts_refuses_wrong_badge_y).
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1},
        fits={1: {("text", 1): slot.verse, ("text", 0): slot.badge}}, deletes={}, clips={},
        text_sizes={}, autosize={}, warnings=(),
        stacked_ids={1: frozenset({("text", 1)})},
        short_fit={1: {("text", 0): slot.badge}},
        slot_badge_ids={1: ("text", 0)},
    )

    def fake_load_deck(_path):
        return ({}, {}, {})

    verse_rec = {
        "kind": "text", "kindIndex": 1,
        "x": slot.verse.x, "y": slot.verse.y, "w": slot.verse.w, "h": 100.0,
    }
    badge_rec = {
        "kind": "text", "kindIndex": 0,
        "x": slot.badge.x, "y": slot.badge.y, "w": slot.badge.w, "h": slot.badge.h,
    }
    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "_canvas_size", lambda objects: (1920.0, 1080.0))
    monkeypatch.setattr(dsa, "layout_alpha_safe", lambda *_a, **_k: True)
    monkeypatch.setattr(
        dsa, "_base_layout_slide_for_ordinal",
        lambda objects, ordinal: {"name": "Verse Standard (Variation 2)"},
    )
    monkeypatch.setattr(dsa, "_slide_archive_for_ordinal", lambda objects, ordinal: {"id": "slide1"})
    monkeypatch.setattr(dsa, "compose_geometry", lambda slide, objects: [verse_rec, badge_rec])

    dsa.verify_staged_layouts_alpha_safe(
        tmp_path / "staged.key", plan, expected_layout_names={1: "Verse Standard (Variation 2)"}
    )


def test_verify_staged_layouts_refuses_verse_overflowing_slot_height(monkeypatch, tmp_path):
    # Finding 1/6: a verse rect at the correct top-anchored x/y but taller than
    # slot.h + 2.0pt must refuse -- the old bottom-only check let an oversized box
    # extend above the slot as long as its bottom matched.
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1},
        fits={1: {("text", 1): slot.verse, ("text", 0): slot.badge}}, deletes={}, clips={},
        text_sizes={}, autosize={}, warnings=(),
        stacked_ids={1: frozenset({("text", 1)})},
        short_fit={1: {("text", 0): slot.badge}},
        slot_badge_ids={1: ("text", 0)},
    )

    def fake_load_deck(_path):
        return ({}, {}, {})

    verse_rec = {
        "kind": "text", "kindIndex": 1,
        "x": slot.verse.x, "y": slot.verse.y, "w": slot.verse.w, "h": slot.verse.h + 20.0,
    }
    badge_rec = {
        "kind": "text", "kindIndex": 0,
        "x": slot.badge.x, "y": slot.badge.y, "w": slot.badge.w, "h": slot.badge.h,
    }
    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "_canvas_size", lambda objects: (1920.0, 1080.0))
    monkeypatch.setattr(dsa, "layout_alpha_safe", lambda *_a, **_k: True)
    monkeypatch.setattr(
        dsa, "_base_layout_slide_for_ordinal",
        lambda objects, ordinal: {"name": "Verse Standard (Variation 2)"},
    )
    monkeypatch.setattr(dsa, "_slide_archive_for_ordinal", lambda objects, ordinal: {"id": "slide1"})
    monkeypatch.setattr(dsa, "compose_geometry", lambda slide, objects: [verse_rec, badge_rec])

    with pytest.raises(AssemblyRefusal, match="does not match"):
        dsa.verify_staged_layouts_alpha_safe(
            tmp_path / "staged.key", plan, expected_layout_names={1: "Verse Standard (Variation 2)"}
        )


def test_verify_staged_layouts_refuses_group_child_overflowing_slot_height(monkeypatch, tmp_path):
    # Finding 5: a group-child split part (GW 5/54-shaped) has no offline run-aware fit
    # of its own, so a mis-sized part must still refuse at STAGE-VERIFY time on the
    # SAVED group geometry (`_staged_group_child_rect`, never a stale live `height`
    # read) -- exact top + saved-height containment against the slot, the same
    # ``stacked``-loop containment check a top-level text item gets.
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    verse_id = ("groupchild", 0, "text", 1)
    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1},
        fits={1: {verse_id: slot.verse}}, deletes={}, clips={},
        text_sizes={}, autosize={}, warnings=(),
        stacked_ids={1: frozenset({verse_id})},
        short_fit={1: {}},
    )

    def fake_load_deck(_path):
        return ({}, {}, {})

    overflowing_rect = Rect(slot.verse.x, slot.verse.y, slot.verse.w, slot.verse.h + 20.0)
    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "_canvas_size", lambda objects: (1920.0, 1080.0))
    monkeypatch.setattr(dsa, "layout_alpha_safe", lambda *_a, **_k: True)
    monkeypatch.setattr(
        dsa, "_base_layout_slide_for_ordinal",
        lambda objects, ordinal: {"name": "Verse Standard (Variation 2)"},
    )
    monkeypatch.setattr(dsa, "_slide_archive_for_ordinal", lambda objects, ordinal: {"id": "slide1"})
    monkeypatch.setattr(dsa, "compose_geometry", lambda slide, objects: [])
    monkeypatch.setattr(
        dsa, "_staged_group_child_rect",
        lambda objects, slide, number, plan, item_id, *, part=0, hidden=frozenset(): overflowing_rect,
    )

    with pytest.raises(AssemblyRefusal, match="does not match"):
        dsa.verify_staged_layouts_alpha_safe(
            tmp_path / "staged.key", plan, expected_layout_names={1: "Verse Standard (Variation 2)"}
        )


def test_verify_staged_layouts_refuses_wrong_badge_y(monkeypatch, tmp_path):
    # Finding 4/7: a badge rect matching x/w/h but NOT y must refuse -- the old
    # x/w/h-only check let this through.
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1},
        fits={1: {("text", 1): slot.verse, ("text", 0): slot.badge}}, deletes={}, clips={},
        text_sizes={}, autosize={}, warnings=(),
        stacked_ids={1: frozenset({("text", 1)})},
        short_fit={1: {("text", 0): slot.badge}},
        slot_badge_ids={1: ("text", 0)},
    )

    def fake_load_deck(_path):
        return ({}, {}, {})

    verse_rec = {
        "kind": "text", "kindIndex": 1,
        "x": slot.verse.x, "y": slot.verse.y + slot.verse.h - 100.0, "w": slot.verse.w, "h": 100.0,
    }
    badge_rec = {
        "kind": "text", "kindIndex": 0,
        "x": slot.badge.x, "y": slot.badge.y - 11.5, "w": slot.badge.w, "h": slot.badge.h,
    }
    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "_canvas_size", lambda objects: (1920.0, 1080.0))
    monkeypatch.setattr(dsa, "layout_alpha_safe", lambda *_a, **_k: True)
    monkeypatch.setattr(
        dsa, "_base_layout_slide_for_ordinal",
        lambda objects, ordinal: {"name": "Verse Standard (Variation 2)"},
    )
    monkeypatch.setattr(dsa, "_slide_archive_for_ordinal", lambda objects, ordinal: {"id": "slide1"})
    monkeypatch.setattr(dsa, "compose_geometry", lambda slide, objects: [verse_rec, badge_rec])

    with pytest.raises(AssemblyRefusal, match="does not match"):
        dsa.verify_staged_layouts_alpha_safe(
            tmp_path / "staged.key", plan, expected_layout_names={1: "Verse Standard (Variation 2)"}
        )


def test_verify_staged_layouts_post_delete_staged_index(monkeypatch, tmp_path):
    # Finding 5: an earlier same-kind object (text, 0) is deleted -- the verse's source
    # id (text, 1) must be translated through `_staged_id_for` to its staged rank
    # (text, 0), not looked up by the raw source id (which no longer exists staged).
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1},
        fits={1: {("text", 1): slot.verse}}, deletes={1: (("text", 0),)}, clips={},
        text_sizes={}, autosize={}, warnings=(),
        stacked_ids={1: frozenset({("text", 1)})}, short_fit={},
    )

    def fake_load_deck(_path):
        return ({}, {}, {})

    staged_rec = {"kind": "text", "kindIndex": 0, "x": slot.verse.x, "y": slot.verse.y, "w": slot.verse.w, "h": slot.verse.h}
    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "_canvas_size", lambda objects: (1920.0, 1080.0))
    monkeypatch.setattr(dsa, "layout_alpha_safe", lambda *_a, **_k: True)
    monkeypatch.setattr(
        dsa, "_base_layout_slide_for_ordinal",
        lambda objects, ordinal: {"name": "Verse Standard (Variation 2)"},
    )
    monkeypatch.setattr(dsa, "_slide_archive_for_ordinal", lambda objects, ordinal: {"id": "slide1"})
    monkeypatch.setattr(dsa, "compose_geometry", lambda slide, objects: [staged_rec])

    dsa.verify_staged_layouts_alpha_safe(
        tmp_path / "staged.key", plan, expected_layout_names={1: "Verse Standard (Variation 2)"}
    )


# --------------------------------------------------------------------------- GW 17 joint stack fit


def _gw17_joint_plan(box1_h: float = 66.6, box2_h: float = 43.33):
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    box1 = Rect(slot.verse.x, slot.verse.y, slot.verse.w, box1_h)
    box2 = Rect(slot.verse.x, slot.verse.y + box1_h, slot.verse.w, box2_h)
    plan = AssemblyPlan(
        kept=(17,), ordinals={17: 1},
        fits={17: {("text", 1): box1, ("text", 2): box2}}, deletes={}, clips={},
        text_sizes={}, autosize={}, warnings=(),
        stacked_ids={17: frozenset({("text", 1), ("text", 2)})}, short_fit={},
    )
    return slot, box1, box2, plan


def _patch_gw17_verify(monkeypatch, recs):
    def fake_load_deck(_path):
        return ({}, {}, {})

    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "_canvas_size", lambda objects: (7680.0, 1080.0))
    monkeypatch.setattr(dsa, "layout_alpha_safe", lambda *_a, **_k: True)
    monkeypatch.setattr(
        dsa, "_base_layout_slide_for_ordinal",
        lambda objects, ordinal: {"name": "Verse Standard (Variation 2)"},
    )
    monkeypatch.setattr(dsa, "_slide_archive_for_ordinal", lambda objects, ordinal: {"id": "slide1"})
    monkeypatch.setattr(dsa, "compose_geometry", lambda slide, objects: recs)


def test_verify_staged_layouts_gw17_joint_stack_contained_passes(monkeypatch, tmp_path):
    """GW 17: two long verse boxes jointly fitted into ONE slot -- box 1 sits at the
    slot top, box 2 is stacked directly below it, and the union stays inside the slot.
    The old per-box "y == slot.y" rule refused box 2 outright; the stack rule must
    accept it."""
    _slot, box1, box2, plan = _gw17_joint_plan()
    recs = [
        {"kind": "text", "kindIndex": 0, "x": box1.x, "y": box1.y, "w": box1.w, "h": box1.h},
        {"kind": "text", "kindIndex": 1, "x": box2.x, "y": box2.y, "w": box2.w, "h": box2.h},
    ]
    _patch_gw17_verify(monkeypatch, recs)
    dsa.verify_staged_layouts_alpha_safe(
        tmp_path / "staged.key", plan, expected_layout_names={17: "Verse Standard (Variation 2)"}
    )


def test_verify_staged_layouts_gw17_joint_stack_overlap_refuses(monkeypatch, tmp_path):
    """The second box overlapping the first (its top short of the previous box's
    bottom by more than 2.0pt) must refuse."""
    _slot, box1, box2, plan = _gw17_joint_plan()
    recs = [
        {"kind": "text", "kindIndex": 0, "x": box1.x, "y": box1.y, "w": box1.w, "h": box1.h},
        {"kind": "text", "kindIndex": 1, "x": box2.x, "y": box2.y - 20.0, "w": box2.w, "h": box2.h},
    ]
    _patch_gw17_verify(monkeypatch, recs)
    with pytest.raises(AssemblyRefusal, match="does not match"):
        dsa.verify_staged_layouts_alpha_safe(
            tmp_path / "staged.key", plan, expected_layout_names={17: "Verse Standard (Variation 2)"}
        )


def test_verify_staged_layouts_gw17_joint_stack_union_past_bottom_refuses(monkeypatch, tmp_path):
    """The union of the stacked boxes running past the slot's own bottom by more than
    2.0pt must refuse even though each box individually fits its own rect."""
    _slot, box1, box2, plan = _gw17_joint_plan(box1_h=100.0, box2_h=100.0)
    recs = [
        {"kind": "text", "kindIndex": 0, "x": box1.x, "y": box1.y, "w": box1.w, "h": box1.h},
        {"kind": "text", "kindIndex": 1, "x": box2.x, "y": box2.y, "w": box2.w, "h": box2.h},
    ]
    _patch_gw17_verify(monkeypatch, recs)
    with pytest.raises(AssemblyRefusal, match="does not match"):
        dsa.verify_staged_layouts_alpha_safe(
            tmp_path / "staged.key", plan, expected_layout_names={17: "Verse Standard (Variation 2)"}
        )


@pytest.mark.deck
def test_verify_staged_layouts_gw17_real_deck_pins_stacked_rects():
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {17: SlideDecision(17, "in_deck")}
    plan = plan_assembly(
        payload, [by_number[17]], decisions=decisions, band=BAND, clips={}, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
    )
    names = dsa.resolve_slide_layouts(payload, classes, plan)
    assert names[17] == "Verse Standard (Variation 2)"
    stacked = sorted(plan.stacked_ids.get(17, frozenset()))
    assert len(stacked) == 2
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    fits = plan.fits[17]
    ordered = sorted(stacked, key=lambda iid: fits[iid].y)
    assert ordered[0] == ("text", 1)
    assert fits[ordered[0]].y == pytest.approx(slot.verse.y, abs=1.0)
    assert fits[ordered[1]].y == pytest.approx(
        fits[ordered[0]].y + fits[ordered[0]].h + dsa._TEXT_STACK_GAP, abs=2.0
    )


# Local operator deck; removed in the 2026-09-16 dsk-d4-work cleanup, so this skips unless regenerated.
R13_REFUSED_DECK = Path("/Users/anyhowclick/Desktop/dsk-d4-work/out-r13/attempt10.refused.key")
R13_CLIPS_DIR = Path("/Users/anyhowclick/Desktop/dsk-d4-work/clips-r8")
R13_SLIDES = (5, 13, 17, 21, 24, 28, 32, 33, 38, 44, 46, 48, 50, 51, 52, 53, 54)


def test_verify_staged_layouts_gw17_real_refused_deck_now_passes():
    """Live r13 attempt 10 refused slide 17 (ordinal 5) because the old stacked-box
    check chained each later box's expected top off the PREVIOUS box's ACTUAL
    (autosize-rendered) height/gap -- Keynote rendered GW 17's first box a few points
    shorter than the plan predicted, so the chained expected top drifted from the
    second box's actual position even though every box sat right where the plan
    put it. The fixed rule checks each box against its OWN ``plan.fits`` rect instead;
    this reproduces the exact refused deck and plan and confirms it now passes."""
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    if not R13_REFUSED_DECK.is_file():
        pytest.skip(f"refused deck not present (local operator file): {R13_REFUSED_DECK}")
    clips = {
        32: R13_CLIPS_DIR / "Sermon_PK (GW).032.mov",
        33: R13_CLIPS_DIR / "Sermon_PK (GW).033.mov",
    }
    if not all(p.is_file() for p in clips.values()):
        pytest.skip(f"movie clips not present (local operator files): {R13_CLIPS_DIR}")
    deck = dsa._load_deck(GW_DECK)
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    builds_by_number = iwa_builds.deck_builds(GW_DECK, deck=deck)
    decisions = {n: SlideDecision(n, "in_deck") for n in R13_SLIDES}
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips=clips, runs=runs,
        all_classes=classes, deck=deck, fw_deck=GW_DECK, layout_policy="import",
        builds=builds_by_number,
    )
    names = dsa.resolve_slide_layouts(payload, classes, plan)
    assert names[17] == "Verse Standard (Variation 2)"
    dsa.verify_staged_layouts_alpha_safe(R13_REFUSED_DECK, plan, expected_layout_names=names)


# --------------------------------------------------------------------------- L5 D1b point layout


def test_verify_staged_layouts_d1b_point_layout_uses_plan_rects(monkeypatch, tmp_path):
    """A D1b two-column slide (``plan.two_column``) resolving to ``Point 3 Lines`` is
    checked against the PLAN's own D1b rects, not the ``Point 3 Lines`` slot table --
    the two are known to diverge (L5, deferred design item)."""
    d1b_verse = Rect(501.0, 821.0, 1391.0, 209.81)
    plan = AssemblyPlan(
        kept=(44,), ordinals={44: 1},
        fits={44: {("text", 1): d1b_verse}}, deletes={}, clips={},
        text_sizes={}, autosize={}, warnings=(),
        stacked_ids={44: frozenset({("text", 1)})}, short_fit={},
        two_column={44: dsa.DEFAULT_BAND},
    )

    def fake_load_deck(_path):
        return ({}, {}, {})

    rec = {"kind": "text", "kindIndex": 0, "x": d1b_verse.x, "y": d1b_verse.y, "w": d1b_verse.w, "h": d1b_verse.h}
    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "_canvas_size", lambda objects: (7680.0, 1080.0))
    monkeypatch.setattr(dsa, "layout_alpha_safe", lambda *_a, **_k: True)
    monkeypatch.setattr(dsa, "_base_layout_slide_for_ordinal", lambda objects, ordinal: {"name": "Point 3 Lines"})
    monkeypatch.setattr(dsa, "_slide_archive_for_ordinal", lambda objects, ordinal: {"id": "slide1"})
    monkeypatch.setattr(dsa, "compose_geometry", lambda slide, objects: [rec])

    logs: list[str] = []
    dsa.verify_staged_layouts_alpha_safe(
        tmp_path / "staged.key", plan, expected_layout_names={44: "Point 3 Lines"}, log=logs.append,
    )
    assert any("point layout verified against the plan rects" in l for l in logs)


def test_verify_staged_layouts_d1b_point_layout_refuses_outside_band(monkeypatch, tmp_path):
    """A D1b two-column point box whose saved rect matches the plan's own fit but has
    drifted outside the shared stack band (704-1054) must still refuse."""
    d1b_verse = Rect(501.0, 821.0, 1391.0, 209.81)
    plan = AssemblyPlan(
        kept=(44,), ordinals={44: 1},
        fits={44: {("text", 1): d1b_verse}}, deletes={}, clips={},
        text_sizes={}, autosize={}, warnings=(),
        stacked_ids={44: frozenset({("text", 1)})}, short_fit={},
        two_column={44: dsa.DEFAULT_BAND},
    )

    def fake_load_deck(_path):
        return ({}, {}, {})

    # matches the plan's own rect x/w/y/h, but sits above the 704pt band top.
    rec = {"kind": "text", "kindIndex": 0, "x": d1b_verse.x, "y": 500.0, "w": d1b_verse.w, "h": d1b_verse.h}
    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "_canvas_size", lambda objects: (7680.0, 1080.0))
    monkeypatch.setattr(dsa, "layout_alpha_safe", lambda *_a, **_k: True)
    monkeypatch.setattr(dsa, "_base_layout_slide_for_ordinal", lambda objects, ordinal: {"name": "Point 3 Lines"})
    monkeypatch.setattr(dsa, "_slide_archive_for_ordinal", lambda objects, ordinal: {"id": "slide1"})
    monkeypatch.setattr(dsa, "compose_geometry", lambda slide, objects: [rec])

    with pytest.raises(AssemblyRefusal, match="does not match"):
        dsa.verify_staged_layouts_alpha_safe(
            tmp_path / "staged.key", plan, expected_layout_names={44: "Point 3 Lines"}
        )


def test_verify_staged_layouts_non_two_column_point_layout_keeps_slot_rule(monkeypatch, tmp_path):
    """A verse-layout ordinal (not a D1b two-column slide) still enforces the exact
    slot rect -- the plan-rect exception is scoped to ``plan.two_column`` point
    layouts only."""
    slot = dsa.LAYOUT_SLOTS["Verse Standard (Variation 2)"]
    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1},
        fits={1: {("text", 1): slot.verse}}, deletes={}, clips={},
        text_sizes={}, autosize={}, warnings=(),
        stacked_ids={1: frozenset({("text", 1)})}, short_fit={},
    )

    def fake_load_deck(_path):
        return ({}, {}, {})

    wrong_rec = {"kind": "text", "kindIndex": 0, "x": 0.0, "y": 0.0, "w": 100.0, "h": 50.0}
    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "_canvas_size", lambda objects: (1920.0, 1080.0))
    monkeypatch.setattr(dsa, "layout_alpha_safe", lambda *_a, **_k: True)
    monkeypatch.setattr(
        dsa, "_base_layout_slide_for_ordinal", lambda objects, ordinal: {"name": "Verse Standard (Variation 2)"},
    )
    monkeypatch.setattr(dsa, "_slide_archive_for_ordinal", lambda objects, ordinal: {"id": "slide1"})
    monkeypatch.setattr(dsa, "compose_geometry", lambda slide, objects: [wrong_rec])

    with pytest.raises(AssemblyRefusal, match="does not match"):
        dsa.verify_staged_layouts_alpha_safe(
            tmp_path / "staged.key", plan, expected_layout_names={1: "Verse Standard (Variation 2)"}
        )


# --------------------------------------------------------------------------- S2 style wiring


def test_has_style_target_verse_and_point_layouts():
    assert dsa._has_style_target({1: "Verse Standard (Variation 2)"})
    assert dsa._has_style_target({1: "Point (2 Lines)"})
    assert not dsa._has_style_target({1: "Blank Black"})
    assert not dsa._has_style_target({})
    assert not dsa._has_style_target(None)


def test_assemble_dsk_deck_calls_style_pass_after_pill_pass(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")

    order: list[str] = []

    def fake_write_style_pass(staging_path, slide_layout_names, warnings, log):
        order.append("style")
        return staging_path

    def fake_write_pill_pass(staging_path, plan, slide_layout_names, warnings, log, *, hidden={}):
        order.append("pill")
        return staging_path

    monkeypatch.setattr(dsa, "_write_style_pass", fake_write_style_pass)
    monkeypatch.setattr(dsa, "_write_pill_pass", fake_write_pill_pass)
    result = assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")
    assert order == ["style", "pill"]
    assert result.path == out_path


def test_assemble_dsk_deck_no_style_skips_pass(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")

    def fake_write_style_pass(*_args, **_kwargs):
        raise AssertionError("must not be called with no_style=True")

    monkeypatch.setattr(dsa, "_write_style_pass", fake_write_style_pass)
    result = assemble_dsk_deck(
        fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve", no_style=True,
    )
    assert result.path == out_path


def test_style_write_refusal_becomes_assembly_refusal(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")

    def fake_has_style_target(_names):
        return True

    def fake_write_styles(_key_path, *, out_path, spec=None):
        raise dsa.StyleWriteRefused("boom")

    monkeypatch.setattr(dsa, "_has_style_target", fake_has_style_target)
    monkeypatch.setattr(dsa, "write_styles", fake_write_styles)
    with pytest.raises(AssemblyRefusal, match="style write refused"):
        assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")


def test_cli_dsk_assemble_no_style_flag(tmp_path, monkeypatch):
    from obed_edom import cli

    source = tmp_path / "src.key"
    source.mkdir()
    monkeypatch.setattr(
        "obed_edom.offline_inspect.offline_wall_payload",
        lambda path, deck=None: {"slideWidth": 7680.0, "slideHeight": 1080.0, "slideCount": 100, "slides": []},
    )
    captured: dict = {}

    def fake_assemble_dsk_deck(
        src, out, *, decisions, reference_deck, clips, log, layout_policy, black_layout_names, import_layout_names, stroke_min_refs,
        text_fit, min_text_pt=24.0, allow_split=True, text_slide_words=10, crop_dir=None,
        no_image_crop=False, no_auto_anchor=False, no_dedupe=False, no_drop_panel_backdrop=False,
        split_overrides=None, rss_limit_bytes=None, no_pills=False, no_style=False, content_only=False,
        **_kwargs,
    ):
        captured["no_style"] = no_style
        return AssembleResult(
            path=out, slides_kept=(13,), ordinals={13: 1}, fits={}, clips_inserted={}, stroke={}, zorder={},
            builds={}, size_bytes=1, source_size_bytes=1, wall_s=0.1, warnings=(), movie_props={},
        )

    monkeypatch.setattr("obed_edom.dsk_assemble.assemble_dsk_deck", fake_assemble_dsk_deck)

    rc = cli.main(
        ["dsk-assemble", str(source), "--out", str(tmp_path / "out.key"), "--slides", "13", "--no-style"]
    )

    assert rc == 0
    assert captured["no_style"] is True


# --------------------------------------------------------------------------- L4 pill wiring


def test_pill_specs_builder_standard_one_line_skip_and_split_parts(monkeypatch, tmp_path):
    """`_pill_specs`: verse layouts (standard/one_line) each get a `PillSpec`, a
    non-verse layout is skipped, and a split slide's each part gets its OWN pill built
    from that part's own staged badge id (finding: `_staged_id_for` is part-aware)."""
    plan = AssemblyPlan(
        kept=(10, 20, 30, 40), ordinals={10: 1, 20: 2, 30: 3, 40: 4},
        fits={}, deletes={}, clips={}, text_sizes={}, autosize={}, warnings=(),
        ordinal_to_number={1: 10, 2: 20, 3: 30, 4: 40, 5: 40},
        slot_badge_ids={10: ("text", 1), 20: ("text", 1), 40: ("text", 1)},
        layout_names={
            10: "Verse Standard (Variation 2)",
            20: "Verse 1 Line (Variation 2)",
            30: "Point 3 Lines",
            40: "Verse Standard (Variation 2)",
        },
        splits={40: (SplitPart(fits={}, deletes=(), text_sizes={}), SplitPart(fits={}, deletes=(), text_sizes={}))},
    )

    objects = {f"obj{ordinal}": {"_id": f"obj{ordinal}"} for ordinal in (1, 2, 4, 5)}

    def fake_load_deck(_path):
        return (objects, {}, {})

    def fake_slide_for_ordinal(_objects, ordinal):
        return {"ordinal": ordinal}

    def fake_staged_id_for(_number, _plan, badge_id, *, part=0, hidden=frozenset()):
        assert badge_id == ("text", 1)
        return ("text", 0)

    def fake_compose_geometry(slide, _objects):
        ordinal = slide["ordinal"]
        return [{"kind": "text", "kindIndex": 0, "id": f"obj{ordinal}", "text": f"Badge{ordinal}"}]

    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "_slide_archive_for_ordinal", fake_slide_for_ordinal)
    monkeypatch.setattr(dsa, "_staged_id_for", fake_staged_id_for)
    monkeypatch.setattr(dsa, "compose_geometry", fake_compose_geometry)
    monkeypatch.setattr(dsa, "shape_style", lambda obj, objects, cache: obj)
    monkeypatch.setattr(dsa, "shaped_width", lambda text, style: float(len(text)) * 10.0)

    specs = dsa._pill_specs(tmp_path / "staged.key", plan, plan.layout_names)

    assert set(specs) == {1, 2, 4, 5}
    assert specs[1].layout == "standard"
    assert specs[2].layout == "one_line"
    assert specs[1].width == pytest.approx(len("Badge1") * 10.0 + dsa.VERSE_BADGE_PAD_PT)
    assert specs[2].width == pytest.approx(len("Badge2") * 10.0 + dsa.VERSE_BADGE_PAD_PT)
    # split parts (ordinals 4 and 5, both slide 40): each part's own pill, same layout.
    assert specs[4].layout == specs[5].layout == "standard"
    assert specs[4].width == pytest.approx(len("Badge4") * 10.0 + dsa.VERSE_BADGE_PAD_PT)
    assert specs[5].width == pytest.approx(len("Badge5") * 10.0 + dsa.VERSE_BADGE_PAD_PT)


def test_pill_specs_no_verse_layouts_is_empty(tmp_path):
    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1}, fits={}, deletes={}, clips={}, text_sizes={}, autosize={}, warnings=(),
        ordinal_to_number={1: 1}, layout_names={1: "Point 3 Lines"},
    )
    assert dsa._pill_specs(tmp_path / "staged.key", plan, plan.layout_names) == {}
    assert dsa._pill_specs(tmp_path / "staged.key", plan, None) == {}


def test_pill_specs_group_child_badge_yields_pill_spec(monkeypatch, tmp_path):
    """GW 5/54-shaped: the slot badge is a group-child id (a 4-tuple), not a plain
    (kind, kindIndex) pair -- `_staged_id_for` unpacking it raised "too many values to
    unpack (expected 2)". `_pill_specs` must resolve it via
    `_staged_group_child_record` instead, reading the child's own caption text/object."""
    badge_id = ("groupchild", 0, "shape", 0)
    plan = AssemblyPlan(
        kept=(5,), ordinals={5: 1}, fits={}, deletes={}, clips={}, text_sizes={}, autosize={}, warnings=(),
        ordinal_to_number={1: 5},
        slot_badge_ids={5: badge_id},
        layout_names={5: "Verse Standard (Variation 2)"},
    )

    objects = {"child-obj": {"_id": "child-obj"}}

    def fake_load_deck(_path):
        return (objects, {}, {})

    def fake_slide_for_ordinal(_objects, ordinal):
        return {"ordinal": ordinal}

    child_record = {"kind": "shape", "kindIndex": 0, "id": "child-obj", "text": "Genesis 1", "x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}

    def fake_staged_group_child_record(_objects, _slide, number, _plan, item_id, *, part=0, hidden=frozenset()):
        assert number == 5
        assert item_id == badge_id
        return child_record

    monkeypatch.setattr(dsa, "_load_deck", fake_load_deck)
    monkeypatch.setattr(dsa, "_slide_archive_for_ordinal", fake_slide_for_ordinal)
    monkeypatch.setattr(dsa, "_staged_group_child_record", fake_staged_group_child_record)
    monkeypatch.setattr(dsa, "shape_style", lambda obj, objects, cache: obj)
    monkeypatch.setattr(dsa, "shaped_width", lambda text, style: float(len(text)) * 10.0)

    specs = dsa._pill_specs(tmp_path / "staged.key", plan, plan.layout_names)

    assert set(specs) == {1}
    assert specs[1].layout == "standard"
    assert specs[1].width == pytest.approx(len("Genesis 1") * 10.0 + dsa.VERSE_BADGE_PAD_PT)


def test_pill_specs_group_child_badge_unresolved_refuses(monkeypatch, tmp_path):
    badge_id = ("groupchild", 0, "shape", 0)
    plan = AssemblyPlan(
        kept=(5,), ordinals={5: 1}, fits={}, deletes={}, clips={}, text_sizes={}, autosize={}, warnings=(),
        ordinal_to_number={1: 5},
        slot_badge_ids={5: badge_id},
        layout_names={5: "Verse Standard (Variation 2)"},
    )
    monkeypatch.setattr(dsa, "_load_deck", lambda _path: ({}, {}, {}))
    monkeypatch.setattr(dsa, "_slide_archive_for_ordinal", lambda _objects, ordinal: {"ordinal": ordinal})
    monkeypatch.setattr(dsa, "_staged_group_child_record", lambda *_a, **_k: None)

    with pytest.raises(AssemblyRefusal, match="not staged"):
        dsa._pill_specs(tmp_path / "staged.key", plan, plan.layout_names)


def test_assemble_dsk_deck_calls_pill_pass(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")

    captured: dict = {}

    def fake_write_pill_pass(staging_path, plan, slide_layout_names, warnings, log, *, hidden={}):
        captured["staging_path"] = staging_path
        captured["plan"] = plan
        return staging_path

    monkeypatch.setattr(dsa, "_write_pill_pass", fake_write_pill_pass)
    result = assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")
    assert captured["plan"] is not None
    assert result.path == out_path


def test_assemble_dsk_deck_no_pills_skips_pass(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")

    def fake_write_pill_pass(*_args, **_kwargs):
        raise AssertionError("must not be called with no_pills=True")

    monkeypatch.setattr(dsa, "_write_pill_pass", fake_write_pill_pass)
    result = assemble_dsk_deck(
        fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve", no_pills=True,
    )
    assert result.path == out_path


def test_pill_write_refusal_becomes_assembly_refusal(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")

    def fake_pill_specs(_staging_path, _plan, _names, *, hidden={}):
        return {1: dsa.PillSpec(300.0, "standard")}

    def fake_write_pills(_key_path, *, slides, out_path):
        raise dsa.OfflineWriteRefused("boom")

    monkeypatch.setattr(dsa, "_pill_specs", fake_pill_specs)
    monkeypatch.setattr(dsa, "write_pills", fake_write_pills)
    with pytest.raises(AssemblyRefusal, match="pill write refused"):
        assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")


def test_generic_post_pass_exception_keeps_staging_deck_as_failed_key(tmp_path, monkeypatch):
    """A bug in a post-pass (not an `AssemblyRefusal`, e.g. the group-child badge
    unpacking crash) must not silently drop the staging deck the way an uncaught
    exception used to -- it is kept as `*.failed.key`, its traceback is logged, and the
    exception surfaces as an `AssemblyRefusal` naming the failing pass."""
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")

    class _StagingSavingBatch:
        def __init__(self, deck, out_dir, *, rss_limit_bytes=0, log=print):
            self.deck = Path(deck)
            self.out_dir = Path(out_dir)
            self.work = self.out_dir / "fake-work"
            self.scratch = self.work / self.deck.name

        def __enter__(self):
            self.work.mkdir(parents=True, exist_ok=True)
            self.scratch.mkdir(parents=True, exist_ok=True)
            (self.scratch / "marker").write_bytes(b"scratch")
            return self

        def run(self, script_path, *, on_progress=None, retry_on_1712=True):
            staging_path = self.work / f"staged-{out_path.name}"
            staging_path.write_bytes(b"staged-deck-bytes")
            return subprocess.CompletedProcess([], 0, "", "OBED\t13\tdone\nOBED\t32\tdone")

        def __exit__(self, exc_type, exc, _tb):
            return False

    monkeypatch.setattr(dsa, "LiveBatch", _StagingSavingBatch)

    def fake_write_pill_pass(*_args, **_kwargs):
        badge_id = ("groupchild", 0, "shape", 0)
        kind, idx = badge_id  # noqa: F841 -- reproduces the "too many values to unpack" crash

    monkeypatch.setattr(dsa, "_write_pill_pass", fake_write_pill_pass)
    logs: list[str] = []
    with pytest.raises(AssemblyRefusal, match=r"pill: ValueError"):
        assemble_dsk_deck(
            fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve", log=logs.append,
        )
    failed_path = out_path.parent / f"{out_path.stem}.failed.key"
    assert failed_path.exists()
    assert not out_path.exists()
    assert any(str(failed_path) in l for l in logs)
    assert any("Traceback" in l for l in logs)


_GOLD_DECK = Path.home() / "Desktop/Diff-Checker/Sermon_PK (DSK)_with mistakes.key"
_needs_gold_deck = pytest.mark.skipif(not _GOLD_DECK.exists(), reason="local gold deck only")

# Step 0 measurement table (plan §1.4/report): source badge text, pinned mask width, and
# the width law's residual (mask - shaped_width - VERSE_BADGE_PAD_PT) for each gold slide.
# Slide 20 is excluded from the fit (its badge text, "Samuel 10", is a known content
# defect -- the verse body itself is 1 Samuel 10:10); slide 23 is a real ~11pt outlier,
# kept in the fit and pinned here rather than silently tightened away.
_GOLD_PILL_WIDTH_LAW_TABLE: dict[int, tuple[str, float, float]] = {
    3: ("Matthew 18", 301.8292, 2.0),
    5: ("Genesis 1", 258.04858, 2.0),
    9: ("Genesis 11", 279.41565, 2.0),
    23: ("2 Chronicles 5", 355.3282, 11.5),
    35: ("Luke 5", 202.55704, 2.0),
    38: ("2 Corinthians 2", 362.11707, 2.0),
}


@_needs_gold_deck
def test_pill_width_law_pinned_to_gold_table():
    from obed_edom.iwa_runs import _load_deck_full, slide_order

    objects, _id_to_file, _file_ids, _hor = _load_deck_full(_GOLD_DECK, strict=True)
    order = slide_order(objects)
    for ordinal, (badge_text, mask_width, tol) in _GOLD_PILL_WIDTH_LAW_TABLE.items():
        slide_id, _skipped = order[ordinal - 1]
        slide = objects[slide_id]
        id_by_item = dsk_plan._item_object_ids(slide, objects)
        obj_id = id_by_item[("text", 1)]
        obj = objects[obj_id]
        law_width = dsa._pill_width_for_badge(badge_text, obj, objects, {})
        assert law_width == pytest.approx(mask_width, abs=tol), (ordinal, badge_text)


# --------------------------------------------------------------------------
# Clip start timing (visual order + AssemblyPlan.clip_timing) -- feat/dsk-clip-timing
# --------------------------------------------------------------------------
def _timing_deck(monkeypatch, flags_by_kind_index):
    """Minimal objects graph resolving each ("movie", kindIndex) to a TSD.MovieArchive
    stub carrying the given `playsAcrossSlides` flag, for slide 1."""
    objects = {
        f"movieObj{ki}": {"playsAcrossSlides": flag}
        for ki, flag in flags_by_kind_index.items()
    }
    monkeypatch.setattr(dsa, "_slide_archive_for_number", lambda objects, number: {"slide": number})
    monkeypatch.setattr(
        dsa, "_item_object_ids",
        lambda slide_archive, objects: {("movie", ki): f"movieObj{ki}" for ki in flags_by_kind_index},
    )
    return (objects, {}, {})


def test_clip_timing_two_continuity_movies_leftmost_after_transition(monkeypatch):
    # FW 13 shape: kindIndex reversed vs x -- movie 1 is placed LEFT of movie 0, both
    # continuity (playsAcrossSlides True). Visual order must be [left, right] regardless
    # of kindIndex, insertion (clips dict order) must follow it, and the timing plan
    # must be leftmost -> after_transition, the other -> with_build_1.
    left = _movie_item(1, x=0, y=0, w=3840, h=2160)
    right = _movie_item(0, x=3840, y=0, w=3840, h=2160)
    slide = _slide(1, [left, right])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "in_deck")}
    clips = {1: {("movie", 0): Path("/tmp/clip0.mov"), ("movie", 1): Path("/tmp/clip1.mov")}}
    deck = _timing_deck(monkeypatch, {0: True, 1: True})

    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips=clips,
        deck=deck, fw_deck="/tmp/does-not-matter.key",
    )

    assert list(plan.clips[1]) == [("movie", 1), ("movie", 0)]
    assert plan.clip_timing[1] == ((("movie", 1), "after_transition"), (("movie", 0), "with_build_1"))


def test_clip_timing_continuity_plus_distinct_cascades_after_previous(monkeypatch):
    # One continuity clip (leftmost, After Transition) and one distinct-movie clip
    # (flag False) cascades After Previous, after the continuity group.
    left = _movie_item(0, x=0, y=0, w=3840, h=2160)
    right = _movie_item(1, x=3840, y=0, w=3840, h=2160)
    slide = _slide(1, [left, right])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "in_deck")}
    clips = {1: {("movie", 0): Path("/tmp/clip0.mov"), ("movie", 1): Path("/tmp/clip1.mov")}}
    deck = _timing_deck(monkeypatch, {0: True, 1: False})

    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips=clips,
        deck=deck, fw_deck="/tmp/does-not-matter.key",
    )

    assert list(plan.clips[1]) == [("movie", 0), ("movie", 1)]
    assert plan.clip_timing[1] == ((("movie", 0), "after_transition"), (("movie", 1), "after_previous"))


def test_clip_timing_single_movie_after_transition():
    movie = _movie_item(0, x=1920, y=0, w=3840, h=1080)
    slide = _slide(1, [movie])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "in_deck")}
    clip_path = Path("/tmp/clip.mov")

    plan = plan_assembly(payload, classes, decisions=decisions, band=BAND, clips={1: clip_path})

    assert plan.clip_timing[1] == ((("movie", 0), "after_transition"),)


def test_clip_timing_fw_dsk_order_mismatch_refuses(monkeypatch):
    # If the FW-space and DSK-fitted visual orders ever disagree, refuse rather than
    # guess which order should win.
    left = _movie_item(0, x=0, y=0, w=3840, h=2160)
    right = _movie_item(1, x=3840, y=0, w=3840, h=2160)
    slide = _slide(1, [left, right])
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "in_deck")}
    clips = {1: {("movie", 0): Path("/tmp/clip0.mov"), ("movie", 1): Path("/tmp/clip1.mov")}}

    calls = {"n": 0}
    real_order = dsa.visual_movie_order

    def fake_order(rects):
        calls["n"] += 1
        order = real_order(rects)
        # Flip the second (DSK-space) call's result so it disagrees with the first.
        return list(reversed(order)) if calls["n"] == 2 else order

    monkeypatch.setattr(dsa, "visual_movie_order", fake_order)

    with pytest.raises(AssemblyRefusal, match="does not match"):
        plan_assembly(payload, classes, decisions=decisions, band=BAND, clips=clips)


def test_restore_clip_timing_resolves_by_basename_and_calls_patch(tmp_path, monkeypatch):
    # `_restore_clip_timing` must resolve each inserted clip to its staged
    # TSD.MovieArchive id the same way `_restore_clip_zorder` does (unique basename
    # match), and hand `iwa_movies.patch_clip_start_timing` a plan keyed by slideId with
    # ClipTiming entries in the plan's given order.
    staging_path = tmp_path / "staged.key"
    with zipfile.ZipFile(staging_path, "w"):
        pass

    objects = {
        "s1": {"drawablesZOrder": [{"identifier": "outA"}, {"identifier": "outB"}]},
        "outA": {"_pbtype": "TSD.MovieArchive", "movieData": {"identifier": "dataA"}},
        "outB": {"_pbtype": "TSD.MovieArchive", "movieData": {"identifier": "dataB"}},
    }
    monkeypatch.setattr(dsa, "_load_deck", lambda path: (objects, {}, {}))
    monkeypatch.setattr(dsa, "slide_order", lambda objs: [("s1", False)])
    monkeypatch.setattr(dsa, "_data_identifier", lambda obj: (obj.get("movieData") or {}).get("identifier"))
    monkeypatch.setattr(
        dsa, "_build_data_index", lambda names: {"dataA": "clip0.mov", "dataB": "clip1.mov"}
    )

    captured: dict = {}

    def fake_patch(deck, plans):
        captured["deck"] = deck
        captured["plans"] = plans
        return {slide_id: {t.movie_id: {} for t in entries} for slide_id, entries in plans.items()}

    monkeypatch.setattr(iwa_movies, "patch_clip_start_timing", fake_patch)

    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1}, fits={}, deletes={}, clips={
            1: {("movie", 0): Path("/tmp/clip0.mov"), ("movie", 1): Path("/tmp/clip1.mov")}
        },
        text_sizes={}, autosize={}, warnings=(),
        clip_timing={1: ((("movie", 0), "after_transition"), (("movie", 1), "with_build_1"))},
    )

    result = dsa._restore_clip_timing(staging_path, plan, lambda _msg: None)

    assert captured["deck"] == staging_path
    assert captured["plans"] == {
        "s1": [
            iwa_movies.ClipTiming("outA", "after_transition"),
            iwa_movies.ClipTiming("outB", "with_build_1"),
        ]
    }
    assert 1 in result


def test_restore_clip_timing_refuses_on_partial_clip_timing(tmp_path, monkeypatch):
    # A hand-built AssemblyPlan whose clip_timing for a two-clip slide names only one
    # clip must refuse rather than silently leave the other clip's timing unresolved.
    staging_path = tmp_path / "staged.key"
    with zipfile.ZipFile(staging_path, "w"):
        pass

    objects = {
        "s1": {"drawablesZOrder": [{"identifier": "outA"}, {"identifier": "outB"}]},
        "outA": {"_pbtype": "TSD.MovieArchive", "movieData": {"identifier": "dataA"}},
        "outB": {"_pbtype": "TSD.MovieArchive", "movieData": {"identifier": "dataB"}},
    }
    monkeypatch.setattr(dsa, "_load_deck", lambda path: (objects, {}, {}))
    monkeypatch.setattr(dsa, "slide_order", lambda objs: [("s1", False)])
    monkeypatch.setattr(dsa, "_data_identifier", lambda obj: (obj.get("movieData") or {}).get("identifier"))
    monkeypatch.setattr(
        dsa, "_build_data_index", lambda names: {"dataA": "clip0.mov", "dataB": "clip1.mov"}
    )

    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1}, fits={}, deletes={}, clips={
            1: {("movie", 0): Path("/tmp/clip0.mov"), ("movie", 1): Path("/tmp/clip1.mov")}
        },
        text_sizes={}, autosize={}, warnings=(),
        clip_timing={1: ((("movie", 0), "after_transition"),)},
    )

    with pytest.raises(AssemblyRefusal, match="partial or duplicate"):
        dsa._restore_clip_timing(staging_path, plan, lambda _msg: None)


def test_restore_clip_timing_refuses_on_ambiguous_basename_match(tmp_path, monkeypatch):
    staging_path = tmp_path / "staged.key"
    with zipfile.ZipFile(staging_path, "w"):
        pass

    objects = {
        "s1": {"drawablesZOrder": [{"identifier": "outA"}, {"identifier": "outB"}]},
        "outA": {"_pbtype": "TSD.MovieArchive"},
        "outB": {"_pbtype": "TSD.MovieArchive"},
    }
    monkeypatch.setattr(dsa, "_load_deck", lambda path: (objects, {}, {}))
    monkeypatch.setattr(dsa, "slide_order", lambda objs: [("s1", False)])
    # Both drawables resolve to the SAME basename -- ambiguous, must refuse.
    monkeypatch.setattr(dsa, "_data_identifier", lambda obj: "dataShared")
    monkeypatch.setattr(dsa, "_build_data_index", lambda names: {"dataShared": "clip0.mov"})

    plan = AssemblyPlan(
        kept=(1,), ordinals={1: 1}, fits={}, deletes={}, clips={
            1: {("movie", 0): Path("/tmp/clip0.mov")}
        },
        text_sizes={}, autosize={}, warnings=(),
        clip_timing={1: ((("movie", 0), "after_transition"),)},
    )

    with pytest.raises(AssemblyRefusal):
        dsa._restore_clip_timing(staging_path, plan, lambda _msg: None)


def test_assemble_dsk_deck_post_pass_order_zorder_then_timing_then_builds(tmp_path, monkeypatch):
    fw_deck, out_path, payload, classes, decisions, clips = _assemble_fixture(tmp_path)
    _patch_common(monkeypatch, payload, classes, "OBED\t13\tdone\nOBED\t32\tdone")

    order: list[str] = []
    monkeypatch.setattr(dsa, "_restore_clip_zorder", lambda out_path, plan, warnings: order.append("zorder") or {})
    monkeypatch.setattr(dsa, "_restore_clip_timing", lambda staging_path, plan, log: order.append("timing") or {})

    real_verify_builds = dsa._verify_builds

    def fake_verify_builds(fw_deck, out_path, plan, warnings, *, hidden={}):
        order.append("builds")
        return real_verify_builds(fw_deck, out_path, plan, warnings, hidden=hidden)

    monkeypatch.setattr(dsa, "_verify_builds", fake_verify_builds)

    assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")

    assert order == ["zorder", "timing", "builds"]


def test_verify_builds_tolerates_two_reordered_clip_movie_starts_and_transition(monkeypatch):
    # Regression (dsk-clip-timing): with two inserted clips on one slide, one at chunk
    # 0 (After Transition) and the other With Build 1/After Previous, the per-identity
    # movie-start surplus tolerance and the independent transition read-back must both
    # still pass -- neither cares about WHERE in the chunk order a clip's own
    # apple:movie-start build sits, only that it is a fresh (unpaired) auto-attach.
    plan = AssemblyPlan(
        kept=(32,), ordinals={32: 1}, fits={32: {}}, deletes={32: ()},
        clips={32: {("movie", 0): Path("/tmp/clip0.mov"), ("movie", 1): Path("/tmp/clip1.mov")}},
        text_sizes={}, autosize={}, warnings=(),
        clip_timing={32: ((("movie", 0), "after_transition"), (("movie", 1), "with_build_1"))},
    )
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: (
            {32: {"slideId": "s", "builds": [], "transition": None}}
            if "fw" in str(path)
            else {1: {"slideId": "o", "builds": [], "transition": _dissolve_transition(0.5)}}
        ),
    )
    monkeypatch.setattr(
        iwa_builds, "verify_builds",
        lambda src_by_number, out_by_number, slides=None: {
            "surplus": [
                {
                    "slide": 32, "effect": "apple:movie-start", "animationType": "In",
                    "identity": ("movie", "clip0.mov"), "count": 1,
                },
                {
                    "slide": 32, "effect": "apple:movie-start", "animationType": "In",
                    "identity": ("movie", "clip1.mov"), "count": 1,
                },
            ],
            "missing": [], "transitions": [], "order": [],
        },
    )
    warnings: list[str] = []
    builds = dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)
    assert {s["identity"] for s in builds["tolerated_surplus"]} == {
        ("movie", "clip0.mov"), ("movie", "clip1.mov"),
    }
