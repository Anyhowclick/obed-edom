"""Pure-Python tests for the stat-group child-resize pass.

These lock the coordinate math (plan B1/B2) and the planner's job emission without
touching Keynote: ``child_target`` is the single reference implementation the
AppleScript template mirrors verbatim, so getting it right here gets it right there.
Keynote validation of the AppleScript pass itself is a separate step.
"""

import pytest

from obed_edom.map_remap import (
    Rect,
    TEXT_DOWN_SCALE,
    child_target,
    pack_columns_from_left,
    plan_slide_transforms,
)


def _item(**kwargs):
    rec = {
        "index": 0,
        "kind": "shape",
        "x": 0,
        "y": 0,
        "w": 10,
        "h": 10,
        "text": "",
        "fileName": "",
        "locked": False,
    }
    rec.update(kwargs)
    return rec


def _missions_map_recipe() -> dict:
    return {
        "destWidth": 1920.0,
        "destHeight": 1080.0,
        "mapSrc": {"x": 3052.0, "y": -12.0, "w": 1248.0, "h": 771.0},
        "mapDst": {"x": 11.0, "y": 18.0, "w": 1067.0, "h": 659.0},
        "groups": [
            {
                "s": 0.8547,
                "tx": -2597.5,
                "ty": 28.3,
                "src": {"x": 3052.0, "y": -12.0, "w": 1248.0, "h": 771.0},
                "dst": {"x": 11.0, "y": 18.0, "w": 1067.0, "h": 659.0},
            }
        ],
    }


def _overlaps(a: Rect, b: Rect) -> bool:
    return (
        a.x < b.x + b.w
        and b.x < a.x + a.w
        and a.y < b.y + b.h
        and b.y < a.y + a.h
    )


# --- B1/B2 coordinate round-trip -------------------------------------------------


def test_child_target_round_trip_has_no_double_count():
    """Wall leaf -> JXA whole-group move -> child_target lands at the intended
    scaled position, with no double-count of the move (plan B1)."""
    s = 0.42
    wall_origin = (5770.0, -174.0)
    anchor = (16.0, 40.0)  # where JXA moved the group's top-left
    wall_leaf = (5900.0, 20.0)
    leaf_w, leaf_h, leaf_font = 200.0, 120.0, 100.0

    # JXA moves the whole group to the anchor; every child translates with it.
    leaf_live_x = wall_leaf[0] + (anchor[0] - wall_origin[0])
    leaf_live_y = wall_leaf[1] + (anchor[1] - wall_origin[1])

    x, y, w, h, font = child_target(
        anchor[0], anchor[1], leaf_live_x, leaf_live_y, leaf_w, leaf_h, leaf_font, s
    )

    # Intended target: anchor + (wallLeaf - wallOrigin) * s.
    assert x == pytest.approx(anchor[0] + (wall_leaf[0] - wall_origin[0]) * s)
    assert y == pytest.approx(anchor[1] + (wall_leaf[1] - wall_origin[1]) * s)
    assert w == pytest.approx(leaf_w * s)
    assert h == pytest.approx(leaf_h * s)  # both dims scale -> icon keeps aspect
    assert font == pytest.approx(leaf_font * s)


def test_child_target_nested_leaf_does_not_compound():
    """A deeper leaf uses the SAME top-level group origin (plan B2): nesting must
    not compound. Scaling around a sub-group origin instead would be wrong, and the
    top-level origin gives the intended position."""
    s = 0.42
    wall_origin = (5770.0, -174.0)
    anchor = (16.0, 40.0)
    # A nested leaf, further from the group origin than a top-level one.
    nested_wall = (6300.0, 600.0)

    nested_live_x = nested_wall[0] + (anchor[0] - wall_origin[0])
    nested_live_y = nested_wall[1] + (anchor[1] - wall_origin[1])

    # Correct: computed from the top-level origin regardless of depth.
    x, y, _w, _h, _f = child_target(
        anchor[0], anchor[1], nested_live_x, nested_live_y, 50.0, 40.0, 30.0, s
    )
    assert x == pytest.approx(anchor[0] + (nested_wall[0] - wall_origin[0]) * s)
    assert y == pytest.approx(anchor[1] + (nested_wall[1] - wall_origin[1]) * s)

    # A hypothetical sub-group origin (offset from the top-level one) would give a
    # different, wrong answer — which is exactly why the pass only ever uses the
    # top-level origin for every leaf.
    sub_origin = (anchor[0] + 120.0, anchor[1] + 90.0)
    wrong_x, wrong_y, _, _, _ = child_target(
        sub_origin[0], sub_origin[1], nested_live_x, nested_live_y, 50.0, 40.0, 30.0, s
    )
    assert wrong_x != pytest.approx(x)
    assert wrong_y != pytest.approx(y)


# --- Scaled-footprint packing ----------------------------------------------------


def test_scaled_footprints_pack_without_overlap():
    """The group boxes shrink to leaf size, so packing their scaled footprints keeps
    the shrunk clusters tight and non-overlapping."""
    s = TEXT_DOWN_SCALE
    walls = [
        Rect(16.0, 100.0, 537.0, 271.0),
        Rect(16.0, 400.0, 575.0, 76.0),
        Rect(16.0, 500.0, 300.0, 300.0),
    ]
    scaled = [Rect(r.x, r.y, r.w * s, r.h * s) for r in walls]
    placed = pack_columns_from_left(scaled, 1920.0, 1080.0)
    assert len(placed) == len(walls)
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            assert not _overlaps(placed[i], placed[j]), (i, j, placed[i], placed[j])


# --- Job emission ----------------------------------------------------------------


def _slide_with_groups() -> dict:
    return {
        "number": 4,
        "items": [
            _item(
                index=4,
                kindIndex=0,
                kind="image",
                fileName="pasted-image.pdf",
                x=3052,
                y=-12,
                w=1248,
                h=771,
            ),
            _item(index=166, kindIndex=0, kind="group", x=4438, y=21, w=575, h=76),
            _item(index=167, kindIndex=1, kind="group", x=4438, y=200, w=537, h=271),
        ],
    }


def test_one_job_per_stat_group():
    report: list[dict] = []
    out = plan_slide_transforms(
        _slide_with_groups(),
        _missions_map_recipe(),
        wall_size=(7680, 1080),
        child_resize_report=report,
    )
    groups = [t for t in out if t.kind == "group"]
    assert len(groups) == 2  # both groups reached the group branch
    assert len(report) == 2  # one job per stat group
    for job in report:
        assert job["slide"] == 4
        assert job["s"] == TEXT_DOWN_SCALE
    # groupIndex is the group's 1-based AppleScript index (kindIndex + 1).
    assert {job["groupIndex"] for job in report} == {1, 2}


def test_no_report_when_not_requested():
    """The pass is opt-in: without a report list the planner emits nothing extra and
    the transforms are unchanged (no stat-group jobs, no crash)."""
    out = plan_slide_transforms(
        _slide_with_groups(),
        _missions_map_recipe(),
        wall_size=(7680, 1080),
    )
    assert [t for t in out if t.kind == "group"]  # groups still planned
