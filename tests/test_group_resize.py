"""Pure-Python tests for the stat-finalize pass.

The pass itself is AppleScript (template-taught number sizes + bring-to-front) and is
validated against Keynote separately. These lock the pure-Python parts: the planner
emitting one job per stat group, and the generated AppleScript embedding the template
sizes and the z-order/badge steps.
"""

from pathlib import Path

from obed_edom.keynote import _build_stat_finalize_script
from obed_edom.map_remap import plan_slide_transforms


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


def test_finalize_script_empty_when_no_jobs():
    assert _build_stat_finalize_script(Path("/tmp/x.key"), [], {"269": 200.0}) == ""
