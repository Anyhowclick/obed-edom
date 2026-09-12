"""Tests for obed_edom.dsk_assemble: pure assembly planning and the generated
AppleScript. No test may launch Keynote; the autouse fixture below raises if
subprocess.run/Popen is reached without an explicit monkeypatch.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import obed_edom.dsk_assemble as dsa
from obed_edom.dsk_assemble import (
    AssembleResult,
    AssemblyPlan,
    AssemblyRefusal,
    SlideDecision,
    SplitPart,
    assemble_dsk_deck,
    build_assembly_script,
    load_assembly_inputs,
    plan_assembly,
)
from obed_edom.dsk_plan import Band, classify_slide, resolve_font_path
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


def test_delete_order_descending_within_kind():
    slide = _slide(
        1,
        [
            _image_item(0, x=1920, y=0, w=3840, h=1080),
            _movie_item(0, x=1920, y=-763, w=3840, h=2160),
            _movie_item(1, x=1920, y=-763, w=3840, h=2160),
        ],
    )
    payload = _payload([slide])
    classes = [_classify(slide)]
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(
        payload, classes, decisions=decisions, band=BAND, clips={1: Path("/clip.mov")}
    )
    assert plan.deletes[1] == (("movie", 1), ("movie", 0))


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


def test_text_autosize_zero_dimension_flagged():
    item = _text_item(0, x=2000, y=0, w=0.0, h=300, runs=[{"size": 20.0}])
    slide = _slide(1, [item])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
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
    assert "set repMethod to (repetition method of" in script
    assert "set movVol to (movie volume of" in script
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


def test_script_layout_preserve_touches_nothing():
    plan = _clip_plan()
    script = build_assembly_script(
        plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"), layout_policy="preserve"
    )
    assert "blackLayoutName" not in script
    assert "set base layout of slide" not in script


def test_script_layout_import_is_default_and_uses_only_template_donor():
    plan = _clip_plan()
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    assert "blackLayoutName" in script
    assert "set base layout of slide" in script
    assert "set tmplDoc to open POSIX file" in script
    assert '"Blank Black"' in script
    # "import" never pre-searches theDoc's OWN layouts to find a black layout to reuse --
    # blackLayoutName starts "" and only layout_import_lines (donor-only) can set it.
    assert '  if blackLayoutName is "" and lname is in approvedBlackNames then set blackLayoutName to lname' not in script


def test_script_target_layout_lookup_is_case_insensitive():
    plan = _clip_plan()
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    assert "ignoring case" in script
    assert "end ignoring" in script
    idx = script.index("ignoring case")
    assert "(name of lay as text) is blackLayoutName" in script[idx:]


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
    monkeypatch.setattr(dsa, "_load_deck", _dispatched_load_deck(template_objects, fw_objects))
    dsa.check_layout_import_preconditions(
        Path("fw"), layout_template=Path("template"), black_layout_names=("Blank Black",)
    )


def test_check_layout_import_preconditions_refuses_unsafe_donor(monkeypatch):
    template_objects = _layout_objects(
        ("n1", "s1", "Blank Black", {"lower": "1", "upper": "1"}, [(-10.0, 0.0, 2000.0, 1080.0)])
    )
    template_objects["show"] = {"_pbtype": "KN.ShowArchive", "size": {"width": 1920.0, "height": 1080.0}}
    monkeypatch.setattr(dsa, "_load_deck", lambda path: (template_objects, {}, {}))
    with pytest.raises(AssemblyRefusal, match="not alpha-safe"):
        dsa.check_layout_import_preconditions(
            Path("fw"), layout_template=Path("template"), black_layout_names=("Blank Black",)
        )


def test_check_layout_import_preconditions_dedupe_trap_refuses(monkeypatch):
    template_objects = _layout_objects(("n1", "s1", "Blank Black", {"lower": "1", "upper": "1"}, []))
    template_objects["show"] = {"_pbtype": "KN.ShowArchive", "size": {"width": 1920.0, "height": 1080.0}}
    fw_objects = _layout_objects(
        ("n2", "s2", "Blank Black", {"lower": "9", "upper": "9"}, [(-10.0, 0.0, 8000.0, 1080.0)])
    )
    fw_objects["show"] = {"_pbtype": "KN.ShowArchive", "size": {"width": 7680.0, "height": 1080.0}}
    monkeypatch.setattr(dsa, "_load_deck", _dispatched_load_deck(template_objects, fw_objects))
    with pytest.raises(AssemblyRefusal, match="dedupe"):
        dsa.check_layout_import_preconditions(
            Path("fw"), layout_template=Path("template"), black_layout_names=("Blank Black",)
        )


def test_check_layout_import_preconditions_dedupe_ok_when_fw_layout_safe(monkeypatch):
    template_objects = _layout_objects(("n1", "s1", "Blank Black", {"lower": "1", "upper": "1"}, []))
    template_objects["show"] = {"_pbtype": "KN.ShowArchive", "size": {"width": 1920.0, "height": 1080.0}}
    fw_objects = _layout_objects(("n2", "s2", "Blank Black", {"lower": "9", "upper": "9"}, []))
    fw_objects["show"] = {"_pbtype": "KN.ShowArchive", "size": {"width": 7680.0, "height": 1080.0}}
    monkeypatch.setattr(dsa, "_load_deck", _dispatched_load_deck(template_objects, fw_objects))
    dsa.check_layout_import_preconditions(
        Path("fw"), layout_template=Path("template"), black_layout_names=("Blank Black",)
    )


def _staged_objects(rects):
    objects = _layout_objects(("layoutNode", "layoutSlide", "Blank Black", {"lower": "1", "upper": "1"}, rects))
    objects["show"] = {
        "_pbtype": "KN.ShowArchive",
        "size": {"width": 1920.0, "height": 1080.0},
        "slideTree": {"slides": [{"identifier": "slideNode1"}]},
    }
    objects["slideNode1"] = {"slide": {"identifier": "realSlide1"}, "templateSlideId": {"lower": "1", "upper": "1"}}
    objects["realSlide1"] = {"name": None, "drawablesZOrder": []}
    return objects


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


def test_script_transition_none_only_on_clip_slides():
    plan = _clip_plan()
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    movie_ordinal = plan.ordinals[32]
    static_ordinal = plan.ordinals[8]
    assert f"set transition properties of slide {movie_ordinal} to " in script
    assert "{transition effect:no transition effect}" in script
    assert f"set transition properties of slide {static_ordinal} to " not in script


def test_script_deletes_after_geometry_per_slide():
    plan = _clip_plan()
    script = build_assembly_script(plan, scratch_path=Path("/tmp/scratch.key"), staging_path=Path("/tmp/staged.key"))
    ordinal = plan.ordinals[32]
    geometry_idx = script.index(f'set theObj to movie 1 of slide {ordinal}')
    delete_idx = script.index("delete theObj")
    assert geometry_idx < delete_idx


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
    assert t13 == pytest.approx(0.95, abs=0.01)

    t17 = next(iter(plan.run_sizes[17][("text", 1)]))[2] / 70.0
    assert t17 == pytest.approx(0.74, abs=0.01)

    badge13 = plan.fits[13][("shape", 0)]
    stack13 = [r for iid, r in plan.fits[13].items() if iid in plan.stacked_ids[13]]
    stack_top13 = min(r.y for r in stack13)
    assert stack_top13 - (badge13.y + badge13.h) == pytest.approx(dsa._TEXT_STACK_GAP, abs=0.5)


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
        plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={}, runs=runs)
        fit = dict(plan.fits.get(number, {}))
        for part in plan.splits.get(number, ()):
            fit.update(part.fits)
        if not fit:
            continue
        checked += 1
        assert min(r.y for r in fit.values()) >= band_top - 1e-6, number
    assert checked >= 20


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


def test_gw13_17_28_forced_split_at_floor_66_leaves_gw13_unsplit():
    # Acceptance table: forcing --min-text-pt 66 across GW 13/17/28 must split only
    # GW 17 (its two-box stack can't clear the floor at any single t), assembling to
    # 4 slides total, not refuse GW 13 or GW 28 (their single boxes clear the floor
    # unsplit).
    _require_gw_deck()
    _require_font("AzoSans-Regular")
    payload, classes, runs = load_assembly_inputs(GW_DECK)
    by_number = {c.number: c for c in classes}
    decisions = {n: SlideDecision(n, "in_deck") for n in (13, 17, 28)}
    plan = plan_assembly(
        payload, [by_number[13], by_number[17], by_number[28]], decisions=decisions,
        band=BAND, clips={}, runs=runs, min_text_pt=66.0,
    )
    assert plan.kept == (13, 17, 28)
    assert 13 not in plan.splits
    assert 28 not in plan.splits
    assert plan.parts.get(17) == 2
    assert sum(plan.parts.get(n, 1) for n in plan.kept) == 4


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


# --------------------------------------------------------------------------
# assemble_dsk_deck -- fake LiveBatch and fake iwa functions, no real Keynote/IWA IO.
# --------------------------------------------------------------------------
import obed_edom.iwa_builds as iwa_builds  # noqa: E402
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

        def run(self, script_path, *, on_progress=None):
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


def _patch_common(monkeypatch, payload, classes, stderr_text, returncode=0):
    monkeypatch.setattr(
        dsa, "load_assembly_inputs", lambda deck, include_side=frozenset(): (payload, classes, {})
    )
    monkeypatch.setattr(dsa, "LiveBatch", _make_fake_live_batch(stderr_text, returncode))
    monkeypatch.setattr(dsa, "copy_keynote", _fake_copy_keynote)
    monkeypatch.setattr(dsa, "_load_deck", lambda path: ({}, {}, {}))
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
    monkeypatch.setattr(iwa_builds, "deck_builds", lambda path, *, deck=None: {})
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
            2: {"slideId": "o2", "builds": [], "transition": None},
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
        32: {"slideId": "o2", "builds": [], "transition": None},
    }
    assert captured["src"][13]["slideId"] == "s13"
    assert result.clips_inserted == {32: Path("/tmp/clip.mov")}
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
            2: {"slideId": "o2", "builds": [], "transition": None},
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
            2: {"slideId": "o2", "builds": [], "transition": None},
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
            "transitions": [{"slide": 32, "source": ("magicMove", 1.0), "output": ("none", 0.0)}],
            "order": [],
        },
    )
    result = assemble_dsk_deck(fw_deck, out_path, decisions=decisions, clips=clips, layout_policy="preserve")
    assert any("transition changed on clip slide 32" in w for w in result.warnings)


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


def test_staged_retained_ids_places_inserted_clip_after_kept_movies():
    plan = AssemblyPlan(
        kept=(32,), ordinals={32: 1}, fits={32: {}},
        deletes={32: (("movie", 0),)}, clips={32: (Path("/tmp/clip.mov"), ("movie", 0))},
        text_sizes={}, autosize={}, warnings=(),
    )
    assert dsa._staged_retained_ids(32, plan) == {("movie", 0)}


def test_staged_retained_ids_inserted_clip_after_a_kept_movie():
    plan = AssemblyPlan(
        kept=(5,), ordinals={5: 1}, fits={5: {("movie", 1): Rect(0, 0, 1, 1)}},
        deletes={}, clips={5: (Path("/tmp/clip.mov"), ("movie", 0))},
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
        deletes={32: (("movie", 0),)}, clips={32: (Path("/tmp/clip.mov"), ("movie", 0))},
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


# --------------------------------------------------------------------------
# _verify_builds surplus tolerance: Keynote auto-attaches an
# apple:movie-start build to an inserted clip; tolerate it only on that clip's own
# slide and only for that clip's own filename.
# --------------------------------------------------------------------------
def test_verify_builds_tolerates_clip_auto_attached_movie_start(monkeypatch):
    from obed_edom import iwa_builds

    plan = AssemblyPlan(
        kept=(32,), ordinals={32: 1}, fits={32: {}}, deletes={32: (("movie", 0),)},
        clips={32: (Path("/tmp/clip.mov"), ("movie", 0))}, text_sizes={}, autosize={}, warnings=(),
    )
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: {32: {"slideId": "s", "builds": [{
            "buildId": "b", "chunkIds": [], "chunkOrder": [], "chunkReferent": [],
            "kind": "movie", "kindIndex": 0, "effect": "apple:movie-start",
            "animationType": "In", "identity": ("movie", "source.mov"),
        }], "transition": None}}
        if "fw" in str(path) else {1: {"slideId": "o", "builds": [], "transition": None}},
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


def test_verify_builds_refuses_surplus_movie_start_with_no_paired_source_build(monkeypatch):
    from obed_edom import iwa_builds

    plan = AssemblyPlan(
        kept=(32,), ordinals={32: 1}, fits={32: {}}, deletes={32: (("movie", 0),)},
        clips={32: (Path("/tmp/clip.mov"), ("movie", 0))}, text_sizes={}, autosize={}, warnings=(),
    )
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: {32: {"slideId": "s", "builds": [], "transition": None}}
        if "fw" in str(path) else {1: {"slideId": "o", "builds": [], "transition": None}},
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
    with pytest.raises(AssemblyRefusal, match="builds verify surplus"):
        dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)


def test_verify_builds_refuses_surplus_movie_start_count_exceeding_source(monkeypatch):
    from obed_edom import iwa_builds

    plan = AssemblyPlan(
        kept=(32,), ordinals={32: 1}, fits={32: {}}, deletes={32: (("movie", 0),)},
        clips={32: (Path("/tmp/clip.mov"), ("movie", 0))}, text_sizes={}, autosize={}, warnings=(),
    )
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: {32: {"slideId": "s", "builds": [{
            "buildId": "b", "chunkIds": [], "chunkOrder": [], "chunkReferent": [],
            "kind": "movie", "kindIndex": 0, "effect": "apple:movie-start",
            "animationType": "In", "identity": ("movie", "source.mov"),
        }], "transition": None}}
        if "fw" in str(path) else {1: {"slideId": "o", "builds": [], "transition": None}},
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
        clips={32: (Path("/tmp/clip.mov"), ("movie", 0))}, text_sizes={}, autosize={}, warnings=(),
    )
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: {32: {"slideId": "s", "builds": [{
            "buildId": "b", "chunkIds": [], "chunkOrder": [], "chunkReferent": [],
            "kind": "movie", "kindIndex": 0, "effect": "apple:movie-start",
            "animationType": "In", "identity": ("movie", "source.mov"),
        }] * 2, "transition": None}}
        if "fw" in str(path) else {1: {"slideId": "o", "builds": [], "transition": None}},
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


def test_verify_builds_tolerates_movie_start_surplus_at_the_full_source_count(monkeypatch):
    plan = _movie_start_plan_and_src(monkeypatch, missing_count=2, surplus_count=2)
    warnings: list[str] = []
    builds = dsa._verify_builds(Path("/tmp/fw.key"), Path("/tmp/out.key"), plan, warnings)
    assert builds["tolerated_surplus"] == [{
        "slide": 32, "effect": "apple:movie-start", "animationType": "In",
        "identity": ("movie", "clip.mov"), "count": 2,
    }]


def test_verify_builds_refuses_surplus_not_matching_the_clip_filename(monkeypatch):
    from obed_edom import iwa_builds

    plan = AssemblyPlan(
        kept=(32,), ordinals={32: 1}, fits={32: {}}, deletes={32: (("movie", 0),)},
        clips={32: (Path("/tmp/clip.mov"), ("movie", 0))}, text_sizes={}, autosize={}, warnings=(),
    )
    monkeypatch.setattr(
        iwa_builds, "deck_builds",
        lambda path, *, deck=None: {32: {"slideId": "s", "builds": [], "transition": None}}
        if "fw" in str(path) else {1: {"slideId": "o", "builds": [], "transition": None}},
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


# --------------------------------------------------------------------------
# Nested group script emission: lock/relock at every level.
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Mixed-run autosize text: overflow read-back and --text-fit shrink.
# --------------------------------------------------------------------------
def test_plan_assembly_records_shrink_size_for_mixed_run_autosize_text():
    text = _text_item(0, x=3000, y=0, w=0.0, h=100.0, runs=[{"size": 30.0}, {"size": 60.0}])
    slide = _slide(1, [text])
    payload = _payload([slide])
    cls = _classify(slide)
    decisions = {1: SlideDecision(1, "in_deck")}
    plan = plan_assembly(payload, [cls], decisions=decisions, band=BAND, clips={})
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

    def fake_assemble_dsk_deck(
        src, out, *, decisions, reference_deck, clips, log, layout_policy, black_layout_names, stroke_min_refs,
        text_fit,
    ):
        captured["decisions"] = decisions
        captured["clips"] = clips
        captured["reference_deck"] = reference_deck
        captured["layout_policy"] = layout_policy
        captured["black_layout_names"] = black_layout_names
        captured["stroke_min_refs"] = stroke_min_refs
        return AssembleResult(
            path=out,
            slides_kept=(13, 32),
            ordinals={13: 1, 32: 2},
            fits={},
            clips_inserted={},
            stroke={},
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
    assert decisions[13].anchor == "centre"
    assert decisions[32].action == "both"
    assert decisions[32].keep_side is False
    assert decisions[32].anchor == "left"
    assert captured["clips"] == {32: clip_path}
    assert captured["layout_policy"] == "import"
    assert captured["black_layout_names"] == dsa.DEFAULT_TRANSPARENT_LAYOUT_NAMES
    assert captured["stroke_min_refs"] == 2
    assert captured["reference_deck"] is None


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
        src, out, *, decisions, reference_deck, clips, log, layout_policy, black_layout_names, stroke_min_refs,
        text_fit,
    ):
        captured["black_layout_names"] = black_layout_names
        return AssembleResult(
            path=out, slides_kept=(13,), ordinals={13: 1}, fits={}, clips_inserted={}, stroke={}, builds={},
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
    assert builds["report"]["surplus"] == []
    assert builds["report"]["missing"] == []
