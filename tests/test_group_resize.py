"""Pure-Python tests for the stat-finalize pass.

The pass itself is AppleScript (template-taught number sizes + bring-to-front) and is
validated against Keynote separately. These lock the pure-Python parts: the planner
emitting one job per stat group, and the generated AppleScript embedding the template
sizes and the z-order/badge steps.
"""

import re
from pathlib import Path

from obed_edom.keynote import _build_stat_finalize_script, _run_stat_finalize
from obed_edom.map_remap import (
    ItemTransform,
    adjust_child_resize_for_deleted_hides,
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


# --- Planner job emission --------------------------------------------------------


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


# --- Generated AppleScript -------------------------------------------------------


def test_finalize_script_embeds_template_sizes_and_bring_to_front():
    jobs = [{"slide": 4, "groupIndex": 1}, {"slide": 4, "groupIndex": 6}]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {"183": 150.0, "269": 200.0})
    # Template sizes are looked up per number.
    assert 'if _t is "183" then return 150.0' in script
    assert 'if _t is "269" then return 200.0' in script
    # Each stat group is addressed by its index and brought to front.
    assert "group 1 of slide 4" in script
    assert "group 6 of slide 4" in script
    assert script.count("Bring to Front") >= 1
    # The badge is searched for and raised too.
    assert "Global Missions" in script


def test_finalize_phase2_raises_groups_descending_per_slide():
    """Phase 2 z-order must raise groups in descending order per slide. Bring to Front
    moves the raised group to the end of the groups collection, shifting later indices
    down. Ascending-order raises would mis-address later groups; descending order keeps
    each group N addressing its intended group (raising a higher index never disturbs
    lower ones)."""
    # Input jobs in ascending order across two slides.
    jobs = [
        {"slide": 4, "groupIndex": 1},
        {"slide": 4, "groupIndex": 3},
        {"slide": 4, "groupIndex": 6},
        {"slide": 5, "groupIndex": 2},
        {"slide": 5, "groupIndex": 4},
    ]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {"269": 200.0})

    # Extract all phase-2 z-order "set selection" lines. Phase 2 uses
    # "set selection of theDoc to {group N of slide S of theDoc}", unique to phase 2.
    # Phase 1 uses "set g to group N" instead.
    phase2_pattern = r"set selection of theDoc to \{group (\d+) of slide (\d+) of theDoc\}"
    phase2_matches = re.findall(phase2_pattern, script)
    assert len(phase2_matches) == 5, f"Expected 5 phase-2 selections, got {len(phase2_matches)}"

    # Group matches by slide and assert descending group indices per slide.
    by_slide = {}
    for group_str, slide_str in phase2_matches:
        group_idx = int(group_str)
        slide_num = int(slide_str)
        if slide_num not in by_slide:
            by_slide[slide_num] = []
        by_slide[slide_num].append(group_idx)

    # Slide 4 should have groups in order [6, 3, 1] (descending).
    assert by_slide[4] == [6, 3, 1], f"Slide 4 groups should be [6, 3, 1], got {by_slide[4]}"
    # Slide 5 should have groups in order [4, 2] (descending).
    assert by_slide[5] == [4, 2], f"Slide 5 groups should be [4, 2], got {by_slide[5]}"

    # Verify phase-1 sizing lines still exist for all groups (order not asserted).
    # Phase 1 uses "set g to group N of slide S" pattern.
    phase1_pattern = r"set g to group (\d+) of slide (\d+) of theDoc"
    phase1_matches = re.findall(phase1_pattern, script)
    assert len(phase1_matches) == 5, f"Expected 5 phase-1 sizing groups, got {len(phase1_matches)}"

    # Verify the expected groups appear in phase-1 sizing.
    phase1_groups_by_slide = {}
    for group_str, slide_str in phase1_matches:
        group_idx = int(group_str)
        slide_num = int(slide_str)
        if slide_num not in phase1_groups_by_slide:
            phase1_groups_by_slide[slide_num] = set()
        phase1_groups_by_slide[slide_num].add(group_idx)

    assert phase1_groups_by_slide[4] == {1, 3, 6}
    assert phase1_groups_by_slide[5] == {2, 4}


def test_finalize_script_empty_when_no_jobs():
    assert _build_stat_finalize_script(Path("/tmp/x.key"), [], {"269": 200.0}) == ""


# --- Folded preview export -------------------------------------------------------


def test_finalize_script_folds_export_when_dir_given():
    jobs = [{"slide": 4, "groupIndex": 1}]
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), jobs, {"269": 200.0}, Path("/tmp/prev")
    )
    # The export runs against the already-open theDoc, in its own try, and reports back.
    assert "export theDoc to exportFolder as slide images" in script
    assert "image format:PNG" in script
    assert "skipped slides:false" in script
    assert "/tmp/prev" in script
    assert 'set exported to "true"' in script
    assert '" exported=" & exported' in script
    # The stat sizes/z-order are saved before the export try, so a render failure
    # cannot lose them; the close is separate so a save/export failure still closes.
    save_at = script.index("save theDoc")
    export_at = script.index("export theDoc to exportFolder")
    close_at = script.index("close theDoc saving yes")
    assert save_at < export_at < close_at
    # Large decks need the long timeout, not the 120s osascript default.
    assert "with timeout of 3600 seconds" in script
    assert "with timeout of 600 seconds" not in script


def test_finalize_script_no_export_without_dir():
    jobs = [{"slide": 4, "groupIndex": 1}]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {"269": 200.0})
    assert "export theDoc to exportFolder" not in script
    # The exported flag still exists and is reported (always "false" here).
    assert 'set exported to "false"' in script
    assert '" exported=" & exported' in script


def test_run_stat_finalize_no_jobs_reports_not_exported():
    # No stat-group jobs means no session opens, so nothing is exported — the caller
    # must fall back to a standalone export. No osascript is invoked on this path.
    result = _run_stat_finalize(Path("/tmp/x.key"), [], {"269": 200.0}, export_dir=None)
    assert result["skipped"] is True
    assert result["exported"] is False


# --- deleteHides index adjustment ------------------------------------------------


def _hide(slide: int, kind_index: int, kind: str = "group") -> ItemTransform:
    """A role="hide" transform, mirroring how _hide_item_transform builds one."""
    return ItemTransform(
        slide_number=slide,
        item_index=kind_index,
        kind=kind,
        x=0.0,
        y=0.0,
        w=10.0,
        h=10.0,
        role="hide",
        kind_index=kind_index,
        opacity=0.0,
    )


def test_adjust_shifts_job_down_by_lower_group_hides():
    # Two group hides below the stat group (kind_index 0 and 3); the job addresses
    # group 5 (kind_index 4), so it drops by 2 to group 3.
    transforms = [_hide(5, 0), _hide(5, 3)]
    child_resize = [{"slide": 5, "groupIndex": 5}]
    adjustments = adjust_child_resize_for_deleted_hides(child_resize, transforms, set())
    assert child_resize[0]["groupIndex"] == 3
    assert adjustments == [{"slide": 5, "from": 5, "to": 3}]


def test_adjust_excludes_reuse_slides():
    transforms = [_hide(5, 0), _hide(5, 3)]
    child_resize = [{"slide": 5, "groupIndex": 5}]
    adjustments = adjust_child_resize_for_deleted_hides(child_resize, transforms, {5})
    assert child_resize[0]["groupIndex"] == 5  # untouched
    assert adjustments == []


def test_adjust_only_counts_hides_lower_than_job():
    # A group hide ABOVE the job (kind_index 5 vs the job's kind_index 1) does not
    # shift it.
    transforms = [_hide(5, 5)]
    child_resize = [{"slide": 5, "groupIndex": 2}]
    adjustments = adjust_child_resize_for_deleted_hides(child_resize, transforms, set())
    assert child_resize[0]["groupIndex"] == 2
    assert adjustments == []


def test_adjust_only_counts_group_hides():
    # A lower role="hide" of kind "image" must not shift a group job.
    transforms = [_hide(5, 0, kind="image")]
    child_resize = [{"slide": 5, "groupIndex": 5}]
    adjustments = adjust_child_resize_for_deleted_hides(child_resize, transforms, set())
    assert child_resize[0]["groupIndex"] == 5
    assert adjustments == []
