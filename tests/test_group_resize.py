"""Pure-Python tests for the stat-finalize pass.

The pass itself is AppleScript (template-taught number sizes + bring-to-front) and is
validated against Keynote separately. These lock the pure-Python parts: the planner
emitting one job per stat group, and the generated AppleScript embedding the template
sizes and the z-order/badge steps.

Index is verified by content; ascending raise, decrement gated on a verified landing
(Bring-to-Front append semantics). Handlers that name Keynote objects MUST wrap the body in `tell application id`
(not just `using terms from`) or `count of iWork items` fails -1700.
DFS-leaf-signature separator MUST equal iwa_runs._SIG_JOIN ("\\n").
Delete highest-index first.
"""

import re
from pathlib import Path

from obed_edom.keynote import (
    _STAT_ACCUMULATORS,
    _build_stat_finalize_script,
    _parse_detail_tokens,
    _run_stat_finalize,
)
from obed_edom.map_remap import (
    ItemTransform,
    _resync_badge_rows_after_placement,
    adjust_child_resize_indexes,
    badge_members,
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


def _badge_recipe() -> dict:
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
        "badgePlateDst": {"x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        "badgeSlots": {
            "shape:0": {"x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
            "image:0": {"x": 31.0, "y": 59.0, "w": 80.0, "h": 80.0},
        },
        # The title's frame comes from the template's own title box (role="title"
        # branch), not from badgeSlots -- see plan_slide_transforms' title handling.
        "titleDst": {"x": 107.0, "y": 79.5, "w": 296.0, "h": 40.0},
    }


def _slide_with_badge() -> dict:
    return {
        "number": 5,
        "items": [
            _item(
                index=0,
                kindIndex=0,
                kind="image",
                fileName="pasted-image.pdf",
                x=3052,
                y=-12,
                w=1248,
                h=771,
            ),
            _item(
                index=1,
                kindIndex=1,
                kind="image",
                fileName="pasted-image.pdf",
                x=1992,
                y=52,
                w=124,
                h=124,
            ),
            _item(index=2, kindIndex=0, kind="shape", x=1953, y=28, w=767, h=173),
            _item(
                index=3,
                kindIndex=0,
                kind="text",
                text="Global Missions",
                x=2147,
                y=52,
                w=537,
                h=124,
                size=100,
                font="AmplitudeCond-Medium",
            ),
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


def test_badge_raise_report_orders_plate_globe_then_title_last():
    """badge_raise_report reuses badge_slot_keys (largest-first: plate 767x173
    before globe 124x124) and forces the title last, regardless of item order."""
    report: list[dict] = []
    plan_slide_transforms(
        _slide_with_badge(),
        _badge_recipe(),
        wall_size=(7680, 1080),
        badge_raise_report=report,
    )
    assert [(j["kind"], j["index"], j["isTitle"]) for j in report] == [
        ("shape", 1, False),
        ("image", 2, False),
        ("text", 1, True),
    ]
    for job in report:
        assert job["slide"] == 5


def test_badge_raise_report_runs_on_every_slide_not_just_stat_slides():
    """The old obedBadgeRaise only ran on stat-job slides. badge_raise_report has
    no dependency on child_resize_report and is collected even with zero stat groups."""
    report: list[dict] = []
    plan_slide_transforms(
        _slide_with_badge(),
        _badge_recipe(),
        wall_size=(7680, 1080),
        badge_raise_report=report,
        # No child_resize_report passed: no stat jobs collected at all.
    )
    assert len(report) == 3


def test_badge_raise_report_carries_the_planned_frame_for_every_row():
    """A2: obedRaiseItem/obedBadgeFind geometry-guards every raise against the planned
    CG frame, so every row -- plate, globe, and the title -- must carry one. The frame
    comes from the emitted transform, not the mid-loop `mapped` value."""
    report: list[dict] = []
    plan_slide_transforms(
        _slide_with_badge(),
        _badge_recipe(),
        wall_size=(7680, 1080),
        badge_raise_report=report,
    )
    by_kind = {j["kind"]: j for j in report if not j["isTitle"]}
    assert (by_kind["shape"]["x"], by_kind["shape"]["y"], by_kind["shape"]["w"], by_kind["shape"]["h"]) == (
        17.0, 37.0, 411.0, 123.0,
    )
    assert (by_kind["image"]["x"], by_kind["image"]["y"], by_kind["image"]["w"], by_kind["image"]["h"]) == (
        31.0, 59.0, 80.0, 80.0,
    )
    title_row = next(j for j in report if j["isTitle"])
    assert (title_row["x"], title_row["y"], title_row["w"], title_row["h"]) == (107.0, 79.5, 296.0, 40.0)


def test_badge_raise_report_drops_a_hidden_member():
    """A badge member that lands off-canvas (is_visible false, a stray side-panel copy)
    is hidden in pass 1 before it ever gets a badge_dst -- it cannot be buried, so it
    must not appear in the report; the surviving members still carry their frame.

    (The plate must clear PIN_KIND_MAX=180pt on at least one axis or title_plate treats
    it as pin-sized; the sole text landing INSIDE the plate's own rect becomes the
    title -- slide_title_item's plate-based fallback -- so this exercises that path too.)
    """
    recipe = {
        "destWidth": 1920.0,
        "destHeight": 1080.0,
        "mapSrc": {"x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0},
        "mapDst": {"x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0},
        "badgePlateDst": {"x": 17.0, "y": 37.0, "w": 300.0, "h": 80.0},
        "badgeSlots": {"shape:0": {"x": 17.0, "y": 37.0, "w": 300.0, "h": 80.0}},
        "titleDst": {"x": 107.0, "y": 79.5, "w": 296.0, "h": 40.0},
    }
    slide = {
        "number": 3,
        "items": [
            _item(index=0, kindIndex=0, kind="shape", x=1600, y=100, w=300, h=80),
            _item(index=1, kindIndex=0, kind="text", text="Malaysia", x=1650, y=120, w=100, h=40),
            # Off-canvas (x=1905 >= wall_w=1905) but still within the plate's 24pt pad: a
            # geometric "member" that pass 1 deletes before it reaches badge_dst.
            _item(index=2, kindIndex=1, kind="text", text="stray", x=1905, y=110, w=6, h=10),
        ],
    }
    report: list[dict] = []
    plan_slide_transforms(slide, recipe, wall_size=(1905.0, 1080.0), badge_raise_report=report)
    assert [j["kind"] for j in report] == ["shape", "text"]
    for j in report:
        assert {"x", "y", "w", "h"} <= j.keys()


def test_badge_raise_report_frameless_row_when_kind_defaults_disagree():
    """`_badge_hits` defaults a kind-less item's kind to "shape" (map_remap.py) while
    the SAME item's emitted transform defaults to "item" (the generic construction
    path's own `or` default) -- the two dicts then key differently for one item. That
    must not silently drop the row: only role=="hide" may be dropped (it was deleted in
    pass 1 and cannot be buried). Here the plate itself is kind-less, so it is reported
    without a frame, which the existing frameless-row path (keynote.py) turns into a
    whole-slide skip and a badgeUnresolved pre-count -- never a silent bury."""
    recipe = _badge_recipe()
    slide = _slide_with_badge()
    slide["items"][2]["kind"] = ""  # the plate (badgeSlots "shape:0"), now kind-less
    report: list[dict] = []
    plan_slide_transforms(slide, recipe, wall_size=(7680, 1080), badge_raise_report=report)
    plate_row = next(j for j in report if not j["isTitle"] and j["kind"] == "shape")
    assert not ({"x", "y", "w", "h"} <= plate_row.keys())


def test_badge_raise_report_frame_comes_from_the_emitted_transform():
    """The report row's line frame must come from the emitted transform's as_dict() --
    the AppleScript-facing convention (width=length, height=0, from start/end) -- not
    the dataclass's own w/h fields, which for a line are the bounding box (width=0,
    height=length: the template slot's own convention, verified against the shipping
    template's `template_line_slots`) and would be transposed if used directly."""
    recipe = {
        "destWidth": 1920.0,
        "destHeight": 1080.0,
        "mapSrc": {"x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0},
        "mapDst": {"x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0},
        "badgePlateDst": {"x": 17.0, "y": 37.0, "w": 300.0, "h": 80.0},
        "badgeSlots": {
            "shape:0": {"x": 17.0, "y": 37.0, "w": 300.0, "h": 80.0},
            "line:0": {"x": 90.0, "y": 12.0, "w": 0.0, "h": 98.0},
        },
        "titleDst": {"x": 107.0, "y": 79.5, "w": 296.0, "h": 40.0},
        "lineSlots": [
            {"x": 90.0, "y": 12.0, "w": 0.0, "h": 98.0, "start": [90.0, 110.0], "end": [90.0, 12.0]}
        ],
    }
    slide = {
        "number": 3,
        "items": [
            # x in the LW centre panel [1920..5760] -- the 7680x1080 wall_size below hides
            # anything on the side panels, which the earlier x~1600 numbers landed on.
            _item(index=0, kindIndex=0, kind="shape", x=3600, y=100, w=300, h=80),
            # Sole text inside the plate's own rect: becomes the title (unrelated to the
            # line under test, just required for title_plate to elect this shape).
            _item(index=1, kindIndex=0, kind="text", text="Malaysia", x=3650, y=120, w=100, h=40),
            _item(index=2, kindIndex=0, kind="line", x=3660, y=130, w=0, h=98),
        ],
    }
    report: list[dict] = []
    plan_slide_transforms(slide, recipe, wall_size=(7680, 1080), badge_raise_report=report)
    line_row = next(j for j in report if j["kind"] == "line")
    # hypot(110-12) along a vertical run of 98 -> length 98, height 0: as_dict's line
    # rule, not the dataclass bounding box (which this fixture's slot sets to 0, 98).
    assert (line_row["w"], line_row["h"]) == (98.0, 0.0)


def test_badge_raise_report_resyncs_to_a_free_text_placement():
    """A badge text member that is also a free-text placement target is snapshotted
    before _place_free_text moves it; the row must carry the PLACED x/y, not the
    pre-placement position it was built with."""
    title = ItemTransform(slide_number=3, item_index=0, kind="text", kind_index=0, x=107.0, y=79.5, w=296.0, h=40.0)
    report = [{"slide": 3, "isTitle": True, "kind": "text", "index": 1, "x": 107.0, "y": 79.5, "w": 296.0, "h": 40.0}]
    title.x, title.y = 250.0, 60.0  # simulate _place_free_text's in-place move
    _resync_badge_rows_after_placement(report, [title], 3)
    assert (report[0]["x"], report[0]["y"]) == (250.0, 60.0)
    assert (report[0]["w"], report[0]["h"]) == (296.0, 40.0)


def test_badge_members_excludes_the_titles_own_shape_duplicate():
    """A title with a plate has a shape:0 duplicateOf twin at its own rect (the same
    physical object recorded once as kind:"text" via title_plate's dual, once as
    kind:"shape") -- badge_members must not also pick it up as a member, or the same
    object gets raised and probed twice for one physical object."""
    title = _item(index=0, kindIndex=0, kind="text", text="Numbers 16", x=100.0, y=100.0, w=200.0, h=40.0)
    dup = _item(
        index=1, kindIndex=0, kind="shape", x=100.0, y=100.0, w=200.0, h=40.0,
        duplicateOf={"kind": "text", "kindIndex": 0},
    )
    # w=200 clears PIN_KIND_MAX=180 on at least one axis, or is_pin_item would treat it
    # as a pin-sized shape and drop it before the duplicateOf filter is ever exercised.
    genuine = _item(index=2, kindIndex=1, kind="shape", x=150.0, y=145.0, w=200.0, h=20.0)
    slide = {"number": 1, "items": [title, dup, genuine]}
    assert badge_members(slide, title) == [genuine]


# --- Generated AppleScript -------------------------------------------------------


def test_finalize_script_embeds_template_sizes_and_content_addresses():
    # Jobs carry childSig + groupIndex; the handler verifies the index against the census.
    jobs = [
        {"slide": 4, "groupIndex": 1, "childSig": "269"},
        {"slide": 4, "groupIndex": 6, "childSig": "183\nSchools"},
    ]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {"183": 150.0, "269": 200.0})
    # Template sizes are looked up per number.
    assert 'if _t is "183" then return 150.0' in script
    assert 'if _t is "269" then return 200.0' in script
    # The per-job logic is factored into HANDLERS so N jobs compile to N one-line calls,
    # not N inline scan loops (the inline form overflowed the compiler, -2707). Font
    # jobs resolve against the per-slide cache; raise uses recorded targets.
    assert "(sig of _r) is targetSig" in script
    # ...the slide's group signatures are read ONCE (scan-once) and each job's signature
    # is passed as a list literal to a one-line call resolved against that cache.
    assert "set _sigs to my obedSlideSigs(4)" in script
    # Each font call carries the group's affine scale `s` (default 1.0 when absent) so the
    # pass scales non-number text leaves by it (the group frame resize doesn't scale fonts).
    assert 'my obedStatJob(4, _sigs, 1, {"269"}, 1.0, 1, 0.0)' in script
    assert 'my obedStatJob(4, _sigs, 6, {"183", "Schools"}, 1.0, 1, 0.0)' in script
    assert "set size of characters 1 thru -1 of object text of _leaf to (_c1 * s)" in script
    # No baked-in group <digits> of slide object specifiers.
    assert not re.search(r"set g to group \d+ of slide", script)
    assert not re.search(r"set selection of theDoc to \{group \d+ of slide", script)
    assert script.count("Bring to Front") >= 1


def test_finalize_font_call_carries_group_scale():
    """A job's affine scale `s` reaches the AppleScript font call verbatim, so the pass
    scales that group's non-number text leaves by it (fonts don't scale with the frame)."""
    jobs = [{"slide": 4, "groupIndex": 1, "childSig": "CHC Arao", "s": 0.8547}]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {})
    assert 'my obedStatJob(4, _sigs, 1, {"CHC Arao"}, 0.8547, 1, 0.0)' in script


def _raise_slide_handler(script: str) -> str:
    return script[script.index("on obedRaiseSlide") : script.index("end obedRaiseSlide")]


def test_finalize_phase2_raises_resolved_targets_ascending():
    """Phase 2 raises recorded targets per slide, lowest index first (Bring to Front
    appends, so ascending raise order reproduces source stacking)."""
    jobs = [
        {"slide": 4, "groupIndex": 1, "childSig": "111"},
        {"slide": 4, "groupIndex": 3, "childSig": "222"},
        {"slide": 5, "groupIndex": 2, "childSig": "333"},
    ]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {"269": 200.0})
    assert "my obedRaiseSlide(4)" in script
    assert "my obedRaiseSlide(5)" in script
    handler = _raise_slide_handler(script)
    assert "< _mn" in handler
    assert "> _mx" not in handler
    assert "> _mx" in script  # obedApplyDeletes legitimately keeps descending deletes
    assert "set selection of theDoc to {group _mn of slide slideNo of theDoc}" in handler
    assert "obedZRaise" not in script
    assert "obedSigLeaves(group _gi of slide slideNo of theDoc) is sig" not in script


def test_raise_decrements_only_on_a_verified_landing():
    """The remaining indices only shift down when the raised target verifiably landed at
    the real top; a provably-dead raise drops the target without touching the rest."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    handler = _raise_slide_handler(script)
    top_at = handler.index("if _at is _top then")
    mn_at = handler.index("else if _at is _mn then")
    unknown_at = handler.index("    else\n")
    assert top_at < mn_at < unknown_at
    top_branch = handler[top_at:mn_at]
    dead_branch = handler[mn_at:unknown_at]
    assert "- 1" in top_branch
    assert "- 1" not in dead_branch


def test_raise_liveness_probes_top_real_by_frame():
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    handler = _raise_slide_handler(script)
    assert (
        'my obedBadgeFind(slideNo, "group", _top, fx of _f, fy of _f, fw of _f, fh of _f, '
        "true, true, false)" in handler
    )


def test_raise_computes_top_real_once_per_slide():
    """The cost guarantee: obedTopReal/obedKindCount are hoisted out of the drain loop,
    computed once per slide rather than once per raise."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    handler = _raise_slide_handler(script)
    loop_at = handler.index("repeat while (count of _rem) > 0")
    top_real_at = handler.index("obedTopReal")
    kind_count_at = handler.index("obedKindCount")
    assert top_real_at < loop_at
    assert kind_count_at < loop_at
    assert handler.count("obedTopReal") == 1
    assert handler.count("obedKindCount") == 1


def test_raise_unknown_outcome_abandons_the_slide_and_never_guesses():
    """The third outcome (anything but the raised target landing at the real top, or
    provably staying put) increments raiseUnknown and returns -- it never falls through
    to a fourth branch that would decrement on a guess."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    handler = _raise_slide_handler(script)
    unknown_at = handler.index("    else\n")
    end_repeat_at = handler.index("end repeat", unknown_at)
    unknown_branch = handler[unknown_at:end_repeat_at]
    assert "raiseUnknown to raiseUnknown + (count of _rem)" in unknown_branch
    assert "return" in unknown_branch
    assert "- 1" not in unknown_branch
    # One "end if" (the if/else-if/else itself, its report token now unguarded) then the
    # loop's own "end repeat" -- no fourth branch after this one.
    assert unknown_branch.count("end if") == 1


def test_raise_does_not_latch_the_badge_pass():
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    handler = _raise_slide_handler(script)
    assert "badgeFrontDead" not in handler


def test_obed_raise_slide_fronts_only_when_selection_succeeded():
    """Mirror of test_obed_raise_item_fronts_only_when_selection_succeeded: a swallowed
    `set selection` must not fall through to Bring-to-Front on a stale selection."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    handler = _raise_slide_handler(script)
    found_true_at = handler.index("set _found to true")
    front_at = handler.index('my obedFront("raise", slideNo, _mn)')
    guard_at = handler.index("if not _found then")
    assert found_true_at < guard_at < front_at


def test_raise_report_tokens_are_unguarded():
    """Every dead raise gets a report token: the raiseDead line carries no counter guard
    and unconditionally increments. raiseUnknown likewise carries no guard -- each of its
    two emission sites `return`s immediately after, so at most one token per slide can
    ever exist by construction."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    handler = _raise_slide_handler(script)
    assert handler.count('" raiseDead(') == 1
    dead_at = handler.index('" raiseDead(')
    dead_line_start = handler.rindex("\n", 0, dead_at) + 1
    dead_preceding_line_start = handler.rindex("\n", 0, dead_line_start - 1) + 1
    dead_preceding_line = handler[dead_preceding_line_start : dead_line_start - 1]
    assert "if raiseDead" not in dead_preceding_line
    dead_line_end = handler.index("\n", dead_at)
    next_line_end = handler.index("\n", dead_line_end + 1)
    next_line = handler[dead_line_end + 1 : next_line_end]
    assert "set raiseDead to raiseDead + 1" in next_line

    start = 0
    occurrences = 0
    while True:
        token_at = handler.find('" raiseUnknown(', start)
        if token_at == -1:
            break
        occurrences += 1
        line_start = handler.rindex("\n", 0, token_at) + 1
        preceding_line_start = handler.rindex("\n", 0, line_start - 1) + 1
        preceding_line = handler[preceding_line_start : line_start - 1]
        assert "if raiseUnknown" not in preceding_line
        branch_end = handler.index("end if", token_at)
        branch = handler[token_at:branch_end]
        assert "raiseUnknown to raiseUnknown + (count of _rem)" in branch
        assert "return" in branch
        start = token_at + 1
    assert occurrences == 2


def test_stat_accumulators_include_raise_liveness_counters():
    assert "raiseMoved" in _STAT_ACCUMULATORS
    assert "raiseDead" in _STAT_ACCUMULATORS
    assert "raiseUnknown" in _STAT_ACCUMULATORS
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    assert "raiseMoved=" in script
    assert "raiseDead=" in script
    assert "raiseUnknown=" in script
    assert "set raiseMoved to 0" in script
    assert "set raiseDead to 0" in script
    assert "set raiseUnknown to 0" in script


def test_run_stat_finalize_result_dict_exposes_raise_liveness_counters(monkeypatch, tmp_path):
    """End-to-end through _run_stat_finalize's own raw-string parsing, with
    subprocess.run stubbed so no Keynote/osascript actually runs."""
    from types import SimpleNamespace

    import obed_edom.keynote as keynote_mod

    state = {"raw": ""}

    def fake_run(args, *a, **kw):
        if args[0] == "osascript":
            return SimpleNamespace(returncode=0, stdout=state["raw"], stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(keynote_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(keynote_mod.time, "sleep", lambda *_: None)

    jobs = [{"slide": 4, "groupIndex": 1, "childSig": "269"}]

    state["raw"] = (
        "done=1 skipped=0 sized=1 sizeSkips=0 front=1 dedupDeleted=0 dedupShortfall=0 "
        "frontErr= exported=false sigFallback=0 unresolved=0 badgeFallback=0 "
        "badgeUnresolved=0 badgeMoved=0 badgeFrontDead=0 raiseMoved=5 raiseDead=1 "
        "raiseUnknown=2 detail= raiseDead(s=4,idx=2)"
    )
    result = keynote_mod._run_stat_finalize(tmp_path / "x.key", jobs, {"269": 200.0})
    assert result["raiseMoved"] == 5
    assert result["raiseDead"] == 1
    assert result["raiseUnknown"] == 2


def _raise_ground_truth_and_formula(n, targets, dead=frozenset()):
    """Simulate obedRaiseSlide's addressing scheme two ways at once and cross-check them
    every step: `state` is a real list mutated by pop/append (the actual Bring-to-Front
    geometry -- pop the raised item out, append it at the end); `rem` is the pure decrement
    arithmetic the AppleScript performs (no list lookup, just min-pick then subtract 1 from
    everything left after a landed raise). If the arithmetic ever computed the wrong current
    position, `state.index(mn) + 1 != mn` would fire on the very next raise.

    `dead` names targets whose Bring to Front does not land (the group stays put; the
    remaining targets are NOT decremented for it, matching the `_at is _mn` branch).

    `rem` holds (label, tracked_position) pairs: `label` is the target's fixed identity
    (its original index, never changed) and `tracked_position` is what the pure decrement
    arithmetic believes its current position is -- the two coincide only at the start."""
    state = list(range(1, n + 1))
    rem = [(t, t) for t in targets]
    landed: list[int] = []
    dead_out: list[int] = []
    dead_positions: dict[int, int] = {}
    while rem:
        mn_pos = min(p for _, p in rem)
        mn_label = next(label for label, p in rem if p == mn_pos)
        assert state.index(mn_label) + 1 == mn_pos, "formula position desynced from real position"
        if mn_label in dead:
            dead_out.append(mn_label)
            dead_positions[mn_label] = mn_pos
            rem = [(label, p) for label, p in rem if label != mn_label]
        else:
            landed.append(mn_label)
            popped = state.pop(mn_pos - 1)
            assert popped == mn_label
            state.append(popped)
            rem = [
                (label, p - 1) for label, p in rem if label != mn_label
            ]
    return state, landed, dead_out, dead_positions


_RAISE_SHAPES = [
    (5, [2, 5]),  # 2 targets, one already at the top
    (10, [1, 4, 9]),  # 3 targets
    (20, [2, 5, 9, 14, 20]),  # 5 targets, one already at the top
    (40, [1, 3, 7, 12, 18, 25, 33, 40]),  # 8 targets
    (200, list(range(3, 3 + 68 * 2, 2))),  # 68 targets, interleaved with non-targets
]


def test_raise_loop_semantics_preserve_source_order():
    """The important test: it would have caught the original max-first defect. Pins
    semantics (a permutation), not AppleScript strings."""
    for n, targets in _RAISE_SHAPES:
        assert max(targets) <= n
        state, landed, dead_out, _ = _raise_ground_truth_and_formula(n, targets)
        assert dead_out == []
        assert landed == sorted(targets)
        raised_order = [x for x in state if x in targets]
        assert raised_order == sorted(targets)


def test_raise_loop_semantics_dead_raise_leaves_target_unraised_others_in_order():
    for n, targets in _RAISE_SHAPES:
        dead_target = targets[len(targets) // 2]
        state, landed, dead_out, dead_positions = _raise_ground_truth_and_formula(
            n, targets, dead={dead_target}
        )
        assert dead_out == [dead_target]
        assert dead_target not in landed
        assert sorted(landed) == sorted(t for t in targets if t != dead_target)
        raised_order = [x for x in state if x in landed]
        assert raised_order == sorted(landed)
        # The dead target never moved after it was marked dead -- it sits exactly where
        # the formula last computed it to be, and nothing later touches a position below it.
        assert state.index(dead_target) + 1 == dead_positions[dead_target]


def test_finalize_job_without_childsig_is_skipped_not_indexed():
    # A job with no childSig (iwa extra unavailable at plan time) must NOT fall back to
    # a drift-prone index; it is skipped-and-reported.
    jobs = [{"slide": 4, "groupIndex": 1, "childSig": None}]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {"269": 200.0})
    assert "set skipJobs to skipJobs + 1" in script
    assert not re.search(r"set g to group \d+ of slide", script)
    assert not re.search(r"obedSigLeaves\(group _gi of slide 4", script)


def test_finalize_dedup_block_is_count_scoped_and_fail_loud():
    # Two stranded donor copies of the same signature on slide 6, target keeps 1.
    group_removes = [
        {"slide": 6, "childSig": "110\nFull-Time Workers", "expectedKeep": 1},
        {"slide": 6, "childSig": "110\nFull-Time Workers", "expectedKeep": 1},
    ]
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {"269": 200.0}, None, group_removes=group_removes
    )
    # The slide's group signatures are read ONCE (scan-once); dedup is a one-line
    # obedDedupPick call resolved against that cache, carrying the content signature (list
    # literal) and the count-scoped keep/delete args: keep(1)+delete(2). The collected
    # indices are then deleted in one obedApplyDeletes call.
    assert "set _sigs to my obedSlideSigs(6)" in script
    assert 'my obedDedupPick(6, _sigs, {"110", "Full-Time Workers"}, 1, 2)' in script
    assert "my obedApplyDeletes(6, _dels)" in script
    # The handler content-addresses by `sig` (against the cache) and guards live ==
    # keepN+delN before collecting the lowest delN indices to delete.
    assert "(sig of _r) is targetSig" in script
    assert "if (count of _idxs) = (keepN + delN) then" in script
    # Collect the lowest `delete` indices; obedApplyDeletes deletes them highest-first so
    # the lower cached indices stay valid across the slide's dedup jobs.
    assert "repeat with _j from 1 to delN" in script
    assert "delete group _mx of slide slideNo of theDoc" in script
    assert "set dedupDeleted to dedupDeleted + 1" in script
    # Fail-loud branch (adds delN to the shortfall) and the two counters surface in the
    # return string.
    assert "set dedupShortfall to dedupShortfall + delN" in script
    assert "dedupDeleted=" in script and "dedupShortfall=" in script


def test_finalize_dedup_sigless_remove_seeds_shortfall():
    # A group remove with no childSig cannot be content-addressed => straight to the
    # shortfall (reported, never guessed), and the session still runs (no child_resize).
    group_removes = [{"slide": 6, "childSig": None, "expectedKeep": 0}]
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {}, None, group_removes=group_removes
    )
    assert script != ""  # session runs on group_removes alone (decoupled from jobs)
    assert "set dedupShortfall to 1" in script


def test_finalize_normalizer_parity_with_normalize_text():
    """§5: the live AppleScript leaf normalizer (simulated in Python) must agree with
    iwa_runs._normalize_text on representative leaves, or the offline plan signature
    and the live signature silently disagree (the count-scoped dedup then fails loud)."""
    from obed_edom.iwa_runs import _normalize_text
    from obed_edom.keynote import _as_norm_sig_simulate

    samples = [
        "1,522",
        "269",
        "  Full-Time   Workers ",
        "27\nSchools",
        "CHC Arao",  # NBSP
        "line1\nline2\nline3",
        "text￼with object",  # object-replacement char
        "￼  leading obj ",
        "tab\tseparated",
        "u2028 break",  # U+2028 line separator
    ]
    for s in samples:
        assert _as_norm_sig_simulate(s) == _normalize_text(s), repr(s)


def test_finalize_script_empty_when_no_jobs():
    assert _build_stat_finalize_script(Path("/tmp/x.key"), [], {"269": 200.0}) == ""


def test_finalize_script_runs_for_badge_alone_with_zero_stat_jobs():
    """A deck can have a badge and no stat groups at all (slides 1-2 in the diagnosis);
    the pass must still run instead of the old jobs-and-group_removes-only gate."""
    badge_raises = [
        {"slide": 1, "kind": "shape", "index": 1, "isTitle": False, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0}
    ]
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {}, badge_raises=badge_raises
    )
    assert script != ""
    assert (
        'my obedBadgeSlide(1, {{k:"shape", i:1, x:17.000, y:37.000, w:411.000, h:123.000, '
        'mw:true, mh:true}})' in script
    )


def test_finalize_badge_raises_emit_after_raise_slide_in_plate_globe_title_order_in_one_call():
    jobs = [{"slide": 4, "groupIndex": 1, "childSig": "269"}]
    badge_raises = [
        {"slide": 4, "kind": "shape", "index": 1, "isTitle": False, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        {"slide": 4, "kind": "image", "index": 2, "isTitle": False, "x": 31.0, "y": 59.0, "w": 80.0, "h": 80.0},
        {"slide": 4, "kind": "text", "index": 1, "isTitle": True, "x": 107.0, "y": 79.5, "w": 296.0, "h": 40.0},
    ]
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), jobs, {"269": 200.0}, badge_raises=badge_raises
    )
    raise_slide_at = script.index("my obedRaiseSlide(4)")
    badge_slide_at = script.index("my obedBadgeSlide(4,")
    assert raise_slide_at < badge_slide_at
    call_line = script[badge_slide_at : script.index("\n", badge_slide_at)]
    assert call_line.index('k:"shape"') < call_line.index('k:"image"') < call_line.index('k:"text"')
    assert "obedBadgeRaise" not in script


def test_finalize_badge_row_missing_frame_is_skipped_and_counted_unresolved():
    """A frameless row of any kind now suppresses that slide's WHOLE obedBadgeSlide
    call (all-or-nothing extends to emission, not just runtime): every member on the
    slide is pre-counted as unresolved, not just the frameless one."""
    badge_raises = [
        {"slide": 4, "kind": "shape", "index": 1, "isTitle": False, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        {"slide": 4, "kind": "image", "index": 2, "isTitle": False},  # no frame
        {"slide": 4, "kind": "text", "index": 1, "isTitle": True, "x": 107.0, "y": 79.5, "w": 296.0, "h": 40.0},
    ]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), [], {}, badge_raises=badge_raises)
    assert "my obedBadgeSlide(4," not in script
    assert "set badgeUnresolved to 3" in script


def test_stat_accumulators_include_badge_counters():
    assert "badgeFallbacks" in _STAT_ACCUMULATORS
    assert "badgeUnresolved" in _STAT_ACCUMULATORS


def test_stat_accumulators_include_badge_moved_counters():
    assert "badgeMoved" in _STAT_ACCUMULATORS
    assert "badgeFrontDead" in _STAT_ACCUMULATORS


def test_finalize_return_string_carries_badge_counters():
    jobs = [{"slide": 4, "groupIndex": 1, "childSig": "269"}]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {"269": 200.0})
    assert '" badgeFallback=" & badgeFallbacks' in script
    assert '" badgeUnresolved=" & badgeUnresolved' in script
    assert '" badgeMoved=" & badgeMoved' in script
    assert '" badgeFrontDead=" & badgeFrontDead' in script


def test_run_stat_finalize_result_dict_exposes_badge_counters(monkeypatch, tmp_path):
    """End-to-end through _run_stat_finalize's own raw-string parsing, with
    subprocess.run stubbed so no Keynote/osascript actually runs."""
    from types import SimpleNamespace

    import obed_edom.keynote as keynote_mod

    state = {"raw": ""}

    def fake_run(args, *a, **kw):
        if args[0] == "osascript":
            return SimpleNamespace(returncode=0, stdout=state["raw"], stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(keynote_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(keynote_mod.time, "sleep", lambda *_: None)

    jobs = [{"slide": 4, "groupIndex": 1, "childSig": "269"}]

    state["raw"] = (
        "done=1 skipped=0 sized=1 sizeSkips=0 front=1 dedupDeleted=0 dedupShortfall=0 "
        "frontErr= exported=false sigFallback=0 unresolved=0 badgeFallback=2 "
        "badgeUnresolved=3 badgeMoved=4 badgeFrontDead=0 "
        "detail= badgeProbeUnknown(s=1,k=text) badgeSkip(s=3,k=shape)"
    )
    result = keynote_mod._run_stat_finalize(tmp_path / "x.key", jobs, {"269": 200.0})
    assert result["badgeFallback"] == 2
    assert result["badgeUnresolved"] == 3
    assert result["badgeMoved"] == 4
    assert result["badgeFrontDead"] == 0
    assert result["detail"] == "badgeProbeUnknown(s=1,k=text) badgeSkip(s=3,k=shape)"

    state["raw"] = "done=1 skipped=0 sized=0 sizeSkips=0 front=0"
    result_no_detail = keynote_mod._run_stat_finalize(tmp_path / "x.key", jobs, {"269": 200.0})
    assert result_no_detail["detail"] == ""


def test_obed_badge_find_unknown_kind_resolves_to_zero():
    """obedBadgeFind must not default an unrecognized kind to a text-item selection --
    only shape/image/text/line/group/movie are valid; anything else leaves `_p`/
    `_positions` undefined so the frame-match errors are swallowed and `_hit` stays 0
    (unresolved, never guessed). The top-level kind dispatch has no bare else of its own."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {},
        badge_raises=[
            {"slide": 1, "kind": "shape", "index": 1, "isTitle": False, "x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0}
        ],
    )
    handler = script[script.index("on obedBadgeFind") : script.index("end obedBadgeFind")]
    dispatch_at = handler.index('if theKind is "shape" then')
    assert _find_own_else(handler, dispatch_at) is None
    assert 'else if theKind is "text" then' in handler
    assert 'else if theKind is "line" then' in handler
    assert 'else if theKind is "group" then' in handler
    assert 'else if theKind is "movie" then' in handler


def test_obed_raise_item_has_guard_scan_skip_branches_in_order():
    """A2: shape/image indices drift on reuse slides just like groups did. obedBadgeFind
    must try the direct index first (guard), fall back to a bulk-read scan of that kind's
    collection, and only then obedRaiseItem gives up (skip) -- in that order."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {},
        badge_raises=[
            {"slide": 1, "kind": "image", "index": 5, "isTitle": False, "x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0}
        ],
    )
    find_handler = script[script.index("on obedBadgeFind") : script.index("end obedBadgeFind")]
    guard_at = find_handler.index("position of image idx")
    scan_at = find_handler.index("position of every image")
    assert guard_at < scan_at
    raise_handler = script[script.index("on obedRaiseItem") : script.index("end obedRaiseItem")]
    find_call_at = raise_handler.index("my obedBadgeFind(")
    skip_at = raise_handler.index("set badgeUnresolved to badgeUnresolved + 1")
    assert find_call_at < skip_at


def _find_own_else(text: str, if_at: int) -> int | None:
    """Position of the bare 'else' pairing with the 'if ... then' opened at if_at (None
    if it has no else before its matching 'end if'), by depth-counting nested
    'if ... then' opens ('else if' does not nest) against 'end if' closes --
    indentation-independent, unlike a raw '^\\s*else$' scan."""
    i = text.index("then", if_at) + len("then")
    depth = 1
    while i < len(text):
        if text.startswith("end if", i):
            depth -= 1
            if depth == 0:
                return None
            i += len("end if")
        elif text.startswith("else if", i):
            i += len("else if")
        elif depth == 1 and text.startswith("else", i):
            return i
        elif text.startswith("if ", i):
            depth += 1
            i += len("if ")
        else:
            i += 1
    raise AssertionError("unbalanced if/end if")


def test_obed_raise_item_ambiguous_scan_hit_is_unresolved_not_raised():
    """Two same-frame images means the scan finds zero or more than one match;
    obedBadgeFind must return 0 (never select) so obedRaiseItem's caller-side check
    counts it as unresolved."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {},
        badge_raises=[
            {"slide": 1, "kind": "image", "index": 5, "isTitle": False, "x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0}
        ],
    )
    handler = script[script.index("on obedBadgeFind") : script.index("end obedBadgeFind")]
    assert "set selection" not in handler
    hit_at = handler.index("if _hitCount is 1 then")
    end_if_at = handler.index("end if", hit_at)
    unique_branch = handler[hit_at:end_if_at]
    assert "set _hit to _hitIdx" in unique_branch
    # No else: ambiguous (or zero) hits leave _hit at its initial 0, never guessed.
    assert "else" not in unique_branch


def test_obed_raise_item_fronts_only_when_selection_succeeded():
    """A swallowed `set selection` error must not fall through to Bring-to-Front on
    whatever was selected last (a previous badge member, or a stat group left selected
    by obedRaiseSlide on a different slide) -- guard the call on the try's own outcome."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {},
        badge_raises=[
            {"slide": 1, "kind": "shape", "index": 1, "isTitle": False, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        ],
    )
    handler = script[script.index("on obedRaiseItem") : script.index("end obedRaiseItem")]
    found_true_at = handler.index("set _found to true")
    front_at = handler.index('my obedFront("badge", slideNo, _hit)')
    guard_at = handler.index("if not _found then return")
    assert found_true_at < guard_at < front_at


def test_obed_badge_member_floats_never_emit_scientific_notation():
    """Python's default float-to-str can emit `1e-05`, which osacompile does not parse
    as a numeric literal -- badge member floats must be fixed-point."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {},
        badge_raises=[
            {"slide": 1, "kind": "shape", "index": 1, "isTitle": False,
             "x": 1e-05, "y": -2.5e-07, "w": 411.0, "h": 123.0},
        ],
    )
    call_at = script.index("my obedBadgeSlide(1,")
    call_line = script[call_at : script.index("\n", call_at)]
    assert "e-05" not in call_line and "e-07" not in call_line
    assert "x:0.000" in call_line and "y:-0.000" in call_line


def test_obed_badge_find_covers_line_and_text_kinds():
    """The old obedRaiseItem only frame-guarded shape/image; a line member was a
    permanent silent no-op and a text member was a blind index select. Both are now
    resolved by obedBadgeFind like every other kind."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {},
        badge_raises=[
            {"slide": 1, "kind": "line", "index": 1, "isTitle": False, "x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0},
        ],
    )
    handler = script[script.index("on obedBadgeFind") : script.index("end obedBadgeFind")]
    assert "position of every line" in handler
    assert "position of every text item" in handler


def test_badge_text_and_line_rows_do_not_match_on_height_or_text_on_width():
    """An autosize text box's live width AND height are Keynote-derived (it re-shrink-
    wraps to its own natural size at the CG point size, which is unrelated to the
    planner's wall-affine-scaled width) and a rotated line's reported height is its
    bounding box, not its length -- text matches x/y only (mw/mh false), a line matches
    x/y/length (mw true, mh false), shape/image match every axis (mw/mh true)."""
    badge_raises = [
        {"slide": 1, "kind": "shape", "index": 1, "isTitle": False, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        {"slide": 1, "kind": "image", "index": 2, "isTitle": False, "x": 31.0, "y": 59.0, "w": 80.0, "h": 80.0},
        {"slide": 1, "kind": "text", "index": 1, "isTitle": True, "x": 107.0, "y": 79.5, "w": 296.0, "h": 40.0},
        {"slide": 1, "kind": "line", "index": 1, "isTitle": False, "x": 184.0, "y": 97.0, "w": 98.0, "h": 0.0},
    ]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), [], {}, badge_raises=badge_raises)
    call_at = script.index("my obedBadgeSlide(1,")
    call_line = script[call_at : script.index("\n", call_at)]
    assert 'k:"shape", i:1, x:17.000, y:37.000, w:411.000, h:123.000, mw:true, mh:true' in call_line
    assert 'k:"image", i:2, x:31.000, y:59.000, w:80.000, h:80.000, mw:true, mh:true' in call_line
    assert 'k:"text", i:1, x:107.000, y:79.500, w:296.000, h:40.000, mw:false, mh:false' in call_line
    assert 'k:"line", i:1, x:184.000, y:97.000, w:98.000, h:0.000, mw:true, mh:false' in call_line
    matches_handler = script[script.index("on obedFrameMatches") : script.index("end obedFrameMatches")]
    assert "if matchW and not" in matches_handler
    assert "if matchH and not" in matches_handler


def test_obed_badge_slide_resolves_all_members_before_raising_any():
    """All-or-nothing: every member must resolve before anything is raised."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {},
        badge_raises=[
            {"slide": 1, "kind": "shape", "index": 1, "isTitle": False, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        ],
    )
    handler = script[script.index("on obedBadgeSlide") : script.index("end obedBadgeSlide")]
    first_repeat_at = handler.index("repeat with _e in members")
    second_repeat_at = handler.index("repeat with _e in members", first_repeat_at + 1)
    resolve_block = handler[first_repeat_at:second_repeat_at]
    raise_block = handler[second_repeat_at:]
    assert "set badgeUnresolved" in resolve_block
    assert "return" in resolve_block
    assert "obedRaiseItem" not in resolve_block
    assert "obedRaiseItem" in raise_block


def test_obed_badge_slide_raises_plate_first():
    """A 7-row fixture in badge_slot_keys order (plate largest-area-first, mirroring the
    Gold missions badge): the emitted member list literal must start with the plate."""
    badge_raises = [
        {"slide": 3, "kind": "shape", "index": 1, "isTitle": False, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        {"slide": 3, "kind": "text", "index": 1, "isTitle": False, "x": 262.0, "y": 63.5, "w": 154.0, "h": 40.0},
        {"slide": 3, "kind": "text", "index": 2, "isTitle": True, "x": 107.0, "y": 79.5, "w": 66.0, "h": 40.0},
        {"slide": 3, "kind": "text", "index": 3, "isTitle": False, "x": 107.0, "y": 57.0, "w": 113.0, "h": 40.0},
        {"slide": 3, "kind": "text", "index": 4, "isTitle": False, "x": 263.0, "y": 98.5, "w": 117.0, "h": 40.0},
        {"slide": 3, "kind": "image", "index": 1, "isTitle": False, "x": 31.0, "y": 59.0, "w": 80.0, "h": 80.0},
        {"slide": 3, "kind": "line", "index": 1, "isTitle": False, "x": 184.0, "y": 97.0, "w": 98.0, "h": 0.0},
    ]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), [], {}, badge_raises=badge_raises)
    call_at = script.index("my obedBadgeSlide(3,")
    call_line = script[call_at : script.index("\n", call_at)]
    first_member_at = call_line.index('k:"')
    assert call_line[first_member_at:].startswith('k:"shape"')


def test_badge_front_dead_short_circuits_only_later_slides():
    """obedBadgeSlide's entry guard (`if badgeFrontDead is 1 then return`) stops any
    LATER slide from raising once the GUI proves inert. It must NOT also appear inside
    the phase-2 raise loop: the plate has already moved by the time badgeFrontDead can
    trip, so aborting mid-slide would leave it alone at the front over its own un-raised
    siblings -- strictly worse than finishing the slide (every member already resolved
    in phase 1)."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {},
        badge_raises=[
            {"slide": 1, "kind": "shape", "index": 1, "isTitle": False, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        ],
    )
    handler = script[script.index("on obedBadgeSlide") : script.index("end obedBadgeSlide")]
    slide_lines = [l.strip() for l in handler.splitlines() if l.strip()]
    assert slide_lines[0].startswith("on obedBadgeSlide")
    assert slide_lines[1].startswith("global")
    assert slide_lines[2] == "if badgeFrontDead is 1 then return"
    first_repeat_at = handler.index("repeat with _e in members")
    second_repeat_at = handler.index("repeat with _e in members", first_repeat_at + 1)
    raise_block = handler[second_repeat_at:]
    assert "badgeFrontDead" not in raise_block  # phase 2 never re-checks it mid-slide
    raise_handler = script[script.index("on obedRaiseItem") : script.index("end obedRaiseItem")]
    assert "set badgeFrontDead to 1" in raise_handler


def test_badge_phase2_miss_continues_the_slide_without_marking_front_dead():
    """A phase-2 re-resolve miss on a non-first member (indices shift as earlier members
    raise) must not abort the slide or count as a dead GUI raise -- it is reported and
    the remaining members still get their turn."""
    raise_handler = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {},
        badge_raises=[
            {"slide": 1, "kind": "shape", "index": 1, "isTitle": False, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        ],
    )
    handler = raise_handler[raise_handler.index("on obedRaiseItem") : raise_handler.index("end obedRaiseItem")]
    miss_at = handler.index("if _hit is 0 then")
    end_if_at = handler.index("end if", miss_at)
    miss_block = handler[miss_at:end_if_at]
    assert "set badgeUnresolved to badgeUnresolved + 1" in miss_block
    assert 'badgePhase2Miss(s=" & slideNo & ",k=" & theKind & ")' in miss_block
    assert "badgeFrontDead" not in miss_block
    assert "return" in miss_block


def test_obed_kind_count_zero_is_not_a_dead_raise():
    """A failed/zero obedKindCount is 'unknown', not 'dead': it must not set
    badgeFrontDead, so the next raise still re-checks liveness. On a retried-only
    entry it does credit badgeMoved (the blind branch's own count), never
    badgeFrontDead."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {},
        badge_raises=[
            {"slide": 1, "kind": "shape", "index": 1, "isTitle": False, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        ],
    )
    handler = script[script.index("on obedRaiseItem") : script.index("end obedRaiseItem")]
    guard_at = handler.index("if _kindCount is 0 then")
    else_at = handler.index("else", guard_at)
    err_block = handler[guard_at:else_at]
    assert "badgeCountErr(s=" in err_block
    assert "badgeFrontDead" not in err_block
    assert "if _retriedOnly then set badgeMoved to badgeMoved + 1" in err_block


def test_obed_top_real_trims_trailing_placeholders():
    """obedTopReal walks down from the raw kind count past Keynote's trailing empty-
    placeholder members (appended last by JXA, never in the slide's z-order) to find
    the highest REAL member -- the invariant Bring-to-Front can actually satisfy."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {},
        badge_raises=[
            {"slide": 1, "kind": "text", "index": 1, "isTitle": True, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        ],
    )
    assert "on obedTopReal(slideNo, theKind, kindCount)" in script
    handler = script[script.index("on obedTopReal") : script.index("end obedTopReal")]
    assert "set _top to kindCount" in handler
    repeat_at = handler.index("repeat while _top > 0")
    find_at = handler.index(
        "my obedBadgeFind(slideNo, theKind, _top, 0, 0, 1, 1, true, true, false)", repeat_at
    )
    assert find_at > repeat_at
    assert "is not _top then exit repeat" in handler
    assert "set _top to _top - 1" in handler
    raise_handler = script[script.index("on obedRaiseItem") : script.index("end obedRaiseItem")]
    assert "my obedTopReal(slideNo, theKind, _kindCount)" in raise_handler


def test_badge_liveness_probes_the_top_real_index_not_the_kind_count():
    """The post-raise liveness check must probe obedBadgeFind at _topReal (the highest
    REAL member), not raw _kindCount -- trailing layout placeholders inflate _kindCount
    and Bring-to-Front can never move a real object past them."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {},
        badge_raises=[
            {"slide": 1, "kind": "text", "index": 1, "isTitle": True, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        ],
    )
    handler = script[script.index("on obedRaiseItem") : script.index("end obedRaiseItem")]
    assert (
        "my obedBadgeFind(slideNo, theKind, _topReal, fx, fy, fw, fh, matchW, matchH, false)"
        in handler
    )
    assert (
        "my obedBadgeFind(slideNo, theKind, _kindCount, fx, fy, fw, fh, matchW, matchH, false)"
        not in handler
    )
    top_if_at = handler.index("if (badgeMoved is 0 or _frontResult is not 0) and badgeFrontDead is 0 then")
    top_else_at = handler.index("else if badgeFrontDead is 0 then", top_if_at)
    probe_block = handler[top_if_at:top_else_at]
    moved_at = probe_block.index("if _foundAt is _topReal then")
    # One unconditional `badgeMoved + 1` on the verified-landed branch, plus one
    # `if _retriedOnly then` guarded copy on each of the three inconclusive branches.
    assert probe_block.count("set badgeMoved to badgeMoved + 1") == 4
    assert probe_block.count("if _retriedOnly then set badgeMoved to badgeMoved + 1") == 3
    unconditional_at = [
        i for i in range(len(probe_block))
        if probe_block.startswith("set badgeMoved to badgeMoved + 1", i)
        and not probe_block[max(0, i - len("if _retriedOnly then ")):i].endswith(
            "if _retriedOnly then "
        )
    ]
    assert len(unconditional_at) == 1
    assert unconditional_at[0] > moved_at


def test_badge_front_dead_needs_a_testable_probe():
    """badgeFrontDead only fires when the probe was BOTH testable (_topReal >= 2, the
    pre-raise hit was below it) AND conclusive (the re-probe resolved to a real, non-
    zero index still short of _topReal). Every other outcome -- unreadable count,
    untestable topReal/hit, unresolvable re-probe -- is badgeProbeUnknown, never
    badgeFrontDead; on a retried-only entry (badgeMoved non-zero) it also credits
    badgeMoved, exactly as the blind branch would have, so a rescued click on a
    single-kind slide does not lose a count."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {},
        badge_raises=[
            {"slide": 1, "kind": "text", "index": 1, "isTitle": True, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        ],
    )
    handler = script[script.index("on obedRaiseItem") : script.index("end obedRaiseItem")]
    assert handler.count("set badgeFrontDead to 1") == 1
    dead_at = handler.index("set badgeFrontDead to 1")
    preceding = handler[:dead_at].rstrip()
    assert preceding.endswith("else")

    unknown_cond_at = handler.index(
        "if _topReal < 2 or _hit is not less than _topReal then"
    )
    unknown_block = handler[unknown_cond_at : handler.index("else", unknown_cond_at)]
    assert "badgeProbeUnknown(s=" in unknown_block
    assert "if _retriedOnly then set badgeMoved to badgeMoved + 1" in unknown_block
    assert "badgeFrontDead" not in unknown_block

    zero_cond_at = handler.index("else if _foundAt is 0 or _foundAt > _topReal then")
    zero_body_at = zero_cond_at + len("else if _foundAt is 0 or _foundAt > _topReal then")
    zero_block = handler[zero_body_at : handler.index("else", zero_body_at)]
    assert "badgeProbeUnknown(s=" in zero_block
    assert "if _retriedOnly then set badgeMoved to badgeMoved + 1" in zero_block
    assert "badgeFrontDead" not in zero_block


def test_badge_found_above_top_real_is_probe_unknown_not_dead():
    """An over-trimmed _topReal (a real member sitting at ~origin/~1x1 that obedTopReal
    mistook for a placeholder) can put a live raise's re-probe ABOVE _topReal, i.e.
    _foundAt > _topReal. That is inconclusive -- the trim was wrong, not the raise --
    so it must route to badgeProbeUnknown, never badgeFrontDead, and must not latch.
    A retried-only entry does credit badgeMoved here (the blind branch's own count)."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {},
        badge_raises=[
            {"slide": 1, "kind": "text", "index": 1, "isTitle": True, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        ],
    )
    handler = script[script.index("on obedRaiseItem") : script.index("end obedRaiseItem")]
    found_at_cond = handler.index("if _foundAt is _topReal then")
    over_top_cond_at = handler.index("else if _foundAt is 0 or _foundAt > _topReal then", found_at_cond)
    over_top_body_at = over_top_cond_at + len("else if _foundAt is 0 or _foundAt > _topReal then")
    over_top_block = handler[over_top_body_at : handler.index("else", over_top_body_at)]
    assert "badgeProbeUnknown(s=" in over_top_block
    assert "if _retriedOnly then set badgeMoved to badgeMoved + 1" in over_top_block
    assert "badgeFrontDead" not in over_top_block
    assert over_top_cond_at < handler.index("set badgeFrontDead to 1")


def test_badge_probe_unknown_does_not_latch_or_count():
    """Every badgeProbeUnknown outcome must leave badgeFrontDead untouched -- it is
    deliberately inconclusive, not a verdict -- and never set badgeMoved on the same
    statement line (a retried-only entry credits badgeMoved on its own guarded line,
    covered elsewhere); the outer guard must still read `(badgeMoved is 0 or
    _frontResult is not 0) and badgeFrontDead is 0` so a later raise, or a retried
    landed raise, re-probes."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {},
        badge_raises=[
            {"slide": 1, "kind": "text", "index": 1, "isTitle": True, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        ],
    )
    handler = script[script.index("on obedRaiseItem") : script.index("end obedRaiseItem")]
    assert "if (badgeMoved is 0 or _frontResult is not 0) and badgeFrontDead is 0 then" in handler
    unknown_lines = [line for line in handler.splitlines() if "badgeProbeUnknown(s=" in line]
    assert len(unknown_lines) == 2
    for line in unknown_lines:
        assert "badgeMoved" not in line
        assert "badgeFrontDead" not in line


def test_stat_finalize_script_compiles_at_scale():
    """The per-job logic is factored into handlers precisely because the old inline form
    overflowed the AppleScript compiler at real deck scale (`storage error: Internal
    table overflow, -2707`) and stat-finalize never ran. This is the guard that would
    have caught that offline: build a LARGE script (~200 font jobs across several slides
    + ~100 group_removes, with varied signatures incl. an embedded newline, an object-
    replacement char, and a comma-number) and `osacompile` it -- it must compile clean
    (returncode 0, no -2707/-2741). Skips gracefully where `osacompile` is unavailable."""
    import shutil
    import subprocess
    import tempfile

    import pytest

    if shutil.which("osacompile") is None:
        pytest.skip("osacompile unavailable (non-macOS)")

    size_map = {"269": 200.0, "183": 150.0, "110": 120.0, "1,522": 90.0}
    slides = [4, 5, 6, 7, 8, 9]
    jobs = []
    for i in range(200):
        if i % 5 == 0:
            sig = f"{i}\nFull-Time Workers"  # embedded newline (the _SIG_JOIN)
        elif i % 5 == 1:
            sig = "1,522\nGivers"  # comma-number
        elif i % 5 == 2:
            sig = "text￼with obj"  # U+FFFC object-replacement char
        else:
            sig = f"{i}"
        jobs.append({"slide": slides[i % len(slides)], "groupIndex": i, "childSig": sig})
    group_removes = []
    for i in range(100):
        if i % 7 == 0:
            sig = None  # sig-less -> seeded straight into the shortfall
        elif i % 3 == 0:
            sig = "110\nFull-Time Workers"
        elif i % 3 == 1:
            sig = "1,522"
        else:
            sig = f"donor {i}\nline2￼"
        group_removes.append(
            {"slide": slides[i % len(slides)], "childSig": sig, "expectedKeep": 1}
        )
    badge_raises = []
    for slide in range(1, 8):
        badge_raises.append({
            "slide": slide, "kind": "shape", "index": 1, "isTitle": False,
            "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0,
        })
        badge_raises.append({
            "slide": slide, "kind": "image", "index": 2, "isTitle": False,
            "x": 31.0, "y": 59.0, "w": 80.0, "h": 80.0,
        })
        badge_raises.append({
            "slide": slide, "kind": "text", "index": 1, "isTitle": True,
            "x": 107.0, "y": 79.5, "w": 296.0, "h": 40.0,
        })

    script = _build_stat_finalize_script(
        Path("/tmp/x.key"),
        jobs,
        size_map,
        Path("/tmp/prev"),
        group_removes=group_removes,
        badge_raises=badge_raises,
    )
    # Sanity: the factored form stays far below the inline blow-up (~467 KB -> -2707).
    assert len(script.encode("utf-8")) < 100_000

    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as handle:
        handle.write(script)
        script_path = Path(handle.name)
    try:
        proc = subprocess.run(
            ["osacompile", "-o", "/dev/null", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        script_path.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr


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
    adjustments = adjust_child_resize_indexes(child_resize, transforms, set())
    assert child_resize[0]["groupIndex"] == 3
    assert adjustments == [{"slide": 5, "from": 5, "to": 3}]


def test_adjust_excludes_reuse_slides():
    transforms = [_hide(5, 0), _hide(5, 3)]
    child_resize = [{"slide": 5, "groupIndex": 5}]
    adjustments = adjust_child_resize_indexes(child_resize, transforms, {5})
    assert child_resize[0]["groupIndex"] == 0
    assert adjustments == [{"slide": 5, "from": 5, "to": 0}]


def test_adjust_only_counts_hides_lower_than_job():
    # A group hide ABOVE the job (kind_index 5 vs the job's kind_index 1) does not
    # shift it.
    transforms = [_hide(5, 5)]
    child_resize = [{"slide": 5, "groupIndex": 2}]
    adjustments = adjust_child_resize_indexes(child_resize, transforms, set())
    assert child_resize[0]["groupIndex"] == 2
    assert adjustments == []


def test_adjust_only_counts_group_hides():
    # A lower role="hide" of kind "image" must not shift a group job.
    transforms = [_hide(5, 0, kind="image")]
    child_resize = [{"slide": 5, "groupIndex": 5}]
    adjustments = adjust_child_resize_indexes(child_resize, transforms, set())
    assert child_resize[0]["groupIndex"] == 5
    assert adjustments == []


def test_finalize_guard_hit_passes_group_index():
    jobs = [{"slide": 9, "groupIndex": 7, "childSig": "UPG"}]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {})
    assert "my obedStatJob(9, _sigs, 7," in script
    handler = script[script.index("on obedResolveGroup") : script.index("end obedResolveGroup")]
    is_gi = handler.find("is gi")
    one_hit = handler.find("(count of _hits) = 1")
    else_at = handler.find("else")
    assert is_gi != -1 and one_hit != -1 and else_at != -1
    assert is_gi < one_hit < else_at


def test_finalize_resolve_group_both_winning_branches_claim():
    jobs = [{"slide": 9, "groupIndex": 10, "childSig": "UPG", "s": 0.483}]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {})
    handler = script[script.index("on obedResolveGroup") : script.index("end obedResolveGroup")]
    exact_branch = handler[handler.index("if gi > 0") : handler.index("if (allowFallback")]
    fallback_branch = handler[handler.index("if (allowFallback") :]
    assert "set end of claimed to gi" in exact_branch
    assert "set end of claimed to _w" in fallback_branch


def test_finalize_stat_job_appends_raise_target_before_try():
    jobs = [{"slide": 9, "groupIndex": 10, "childSig": "UPG", "s": 0.483}]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {})
    handler = script[script.index("on obedStatJob") : script.index("end obedStatJob")]
    raise_at = handler.index("set end of raiseTargets to")
    try_match = re.search(r"^\s*try$", handler, re.M)
    assert try_match is not None
    assert raise_at < try_match.start()


def test_finalize_accounting_globals_claimed_per_font_slide():
    jobs = [
        {"slide": 4, "groupIndex": 1, "childSig": "A"},
        {"slide": 4, "groupIndex": 2, "childSig": "B"},
        {"slide": 6, "groupIndex": 1, "childSig": "C"},
    ]
    group_removes = [
        {"slide": 6, "childSig": "donor", "expectedKeep": 1},
        {"slide": 6, "childSig": "donor", "expectedKeep": 1},
    ]
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), jobs, {}, None, group_removes=group_removes
    )
    global_line = script.split("\n", 1)[0]
    for name in ("sigFallbacks", "unresolved", "claimed", "raiseTargets"):
        assert name in global_line
    assert "set raiseTargets to {}" in script
    assert "set sigFallbacks to 0" in script
    assert "set unresolved to 0" in script
    init = script[script.index("set theDoc to document 1") : script.index("set _sigs to")]
    assert "set claimed to {}" not in init
    font_phase_slides = {4, 6}
    assert script.count("set claimed to {}") == len(font_phase_slides)
    assert "sigFallback=" in script
    assert "unresolved=" in script


def test_finalize_allow_fallback_gated_by_duplicate_childsig():
    jobs = [
        {"slide": 9, "groupIndex": 10, "childSig": "UPG", "s": 0.483},
        {"slide": 9, "groupIndex": 11, "childSig": "UPG", "s": 0.483},
        {"slide": 9, "groupIndex": 12, "childSig": "CHC", "s": 0.483},
    ]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {})
    assert 'my obedStatJob(9, _sigs, 10, {"UPG"}, 0.483, 0, 0.0)' in script
    assert 'my obedStatJob(9, _sigs, 11, {"UPG"}, 0.483, 0, 0.0)' in script
    assert 'my obedStatJob(9, _sigs, 12, {"CHC"}, 0.483, 1, 0.0)' in script


def test_finalize_twin_jobs_claim_in_order():
    """plan-sparkle-hide.md Change B: two jobs sharing a sig, BOTH flagged `twin`
    (a coincident build-twin pair, map_remap's row["twin"]), emit allowFallback=2
    instead of refusing -- this is the blast-radius-limited widening the plan chose
    over keying on general (s, captionPt) interchangeability."""
    jobs = [
        {"slide": 124, "groupIndex": 6, "childSig": "twinSig", "s": 0.1267, "twin": True},
        {"slide": 124, "groupIndex": 8, "childSig": "twinSig", "s": 0.1267, "twin": True},
    ]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {})
    assert 'my obedStatJob(124, _sigs, 6, {"twinSig"}, 0.1267, 2, 0.0)' in script
    assert 'my obedStatJob(124, _sigs, 8, {"twinSig"}, 0.1267, 2, 0.0)' in script


def test_finalize_mixed_twin_and_untagged_same_sig_refuses():
    """The flag must be unanimous -- one row tagged twin and one plain row sharing the
    same (slide, sig) both refuse (allowFallback=0), same as today with no twin at all."""
    jobs = [
        {"slide": 9, "groupIndex": 6, "childSig": "twinSig", "s": 0.1267, "twin": True},
        {"slide": 9, "groupIndex": 8, "childSig": "twinSig", "s": 0.1267},
    ]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {})
    assert 'my obedStatJob(9, _sigs, 6, {"twinSig"}, 0.1267, 0, 0.0)' in script
    assert 'my obedStatJob(9, _sigs, 8, {"twinSig"}, 0.1267, 0, 0.0)' in script


def test_finalize_twin_branch_precedes_the_single_hit_branch():
    """`allowFallback is not 0` is true for 2 as well as 1 -- the twin branch must come
    first in obedResolveGroup or a 2 silently degrades to the single-hit fallback."""
    jobs = [{"slide": 1, "groupIndex": 0, "childSig": "s", "s": 1.0}]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {})
    assert script.index("allowFallback is 2") < script.index("allowFallback is not 0")


def test_finalize_twin_claims_are_recorded():
    jobs = [{"slide": 1, "groupIndex": 0, "childSig": "s", "s": 1.0}]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {})
    start = script.index("allowFallback is 2")
    branch = script[start : script.index("end if", start)]
    assert "set end of claimed to _w" in branch
    assert "sigFallbacks to sigFallbacks + 1" in branch
    assert "sigTwin(s=" in branch


def test_finalize_reuse_voids_group_index_in_call():
    transforms = [_hide(2, 0)]
    child_resize = [{"slide": 2, "groupIndex": 4, "childSig": "unique-sig"}]
    adjustments = adjust_child_resize_indexes(child_resize, transforms, {2})
    assert child_resize[0]["groupIndex"] == 0
    assert adjustments == [{"slide": 2, "from": 4, "to": 0}]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), child_resize, {})
    assert "my obedStatJob(2, _sigs, 0," in script
    assert ", 0," in script


# --------------------------------------------------------------------------
# Batch 2 — caption point size is job-scoped (child_resize row), never in the
# global statSizeFor size_map. Regression guard for the 38/44 roster collision.
# --------------------------------------------------------------------------
def test_finalize_font_call_carries_caption_point_size():
    jobs = [{"slide": 4, "groupIndex": 1, "childSig": "CHC Arao", "s": 0.9091, "captionPt": 9.0}]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {})
    assert 'my obedStatJob(4, _sigs, 1, {"CHC Arao"}, 0.9091, 1, 9.0)' in script


def test_caption_size_is_job_scoped_not_in_the_size_map():
    # A card job (captionPt 9.0) and a roster job sharing the SAME leaf string
    # (captionPt 0.0, today's scale-by-s behaviour) must not collide: the caption
    # size never enters statSizeFor's digits-only map, only this job's own call.
    jobs = [
        {"slide": 4, "groupIndex": 1, "childSig": "CHC Arao", "s": 0.9091, "captionPt": 9.0},
        {"slide": 4, "groupIndex": 49, "childSig": "CHC Arao", "s": 0.483, "captionPt": 0.0},
    ]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {})
    assert 'if _t is "CHC Arao"' not in script
    assert 'my obedStatJob(4, _sigs, 1, {"CHC Arao"}, 0.9091, 0, 9.0)' in script
    assert 'my obedStatJob(4, _sigs, 49, {"CHC Arao"}, 0.483, 0, 0.0)' in script


def test_stat_size_map_still_digits_only():
    jobs = [{"slide": 4, "groupIndex": 1, "childSig": "269", "s": 1.0}]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {"269": 200.0})
    assert 'if _t is "269" then return 200.0' in script
    assert "return 0" in script


def test_leaf_font_writes_prefer_stat_size_then_caption_then_scale():
    from obed_edom.keynote import _stat_leaf_font_writes

    lines = "\n".join(_stat_leaf_font_writes("g"))
    tgt = lines.index("if _tgt > 0 then")
    leaf = lines.index("else if leafPt > 0 then")
    scale = lines.index("set size of characters 1 thru -1 of object text of _leaf to (_c1 * s)")
    assert tgt < leaf < scale


def test_leaf_font_write_needs_a_positive_scale():
    # s<=0 (e.g. an unresolved group) must not write a bogus/negative font size.
    from obed_edom.keynote import _stat_leaf_font_writes

    lines = "\n".join(_stat_leaf_font_writes("g"))
    assert "else if s > 0 then" in lines
    assert "set size of characters 1 thru -1 of object text of _leaf to (_c1 * s)" in lines


def test_finalize_honours_an_explicit_zero_scale_instead_of_coercing_to_one():
    # Review finding 6: `float(job.get("s") or 1.0)` would silently turn a real 0.0
    # scale into 1.0, making the AppleScript's `else if s > 0` guard unreachable. An
    # explicit 0.0 must reach the script as 0.0 (a missing key still defaults to 1.0).
    zero = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "CHC Arao", "s": 0.0}], {}
    )
    assert 'my obedStatJob(4, _sigs, 1, {"CHC Arao"}, 0.0, 1, 0.0)' in zero

    missing = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "CHC Arao"}], {}
    )
    assert 'my obedStatJob(4, _sigs, 1, {"CHC Arao"}, 1.0, 1, 0.0)' in missing


def test_caption_point_size_zero_reproduces_todays_script():
    # A stat-only job set (captionPt always 0.0) falls through to `_c1 * s`, byte-for-byte
    # what a job dict without "captionPt" produces.
    with_zero = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 6, "groupIndex": 7, "childSig": "183\nSchools", "s": 1.0, "captionPt": 0.0}], {}
    )
    without_key = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 6, "groupIndex": 7, "childSig": "183\nSchools", "s": 1.0}], {}
    )
    assert with_zero == without_key


def test_parse_detail_tokens_groups_by_name():
    tokens = _parse_detail_tokens(
        "raiseDead(s=106,idx=15) sigFallback(s=4,gi=1) raiseDead(s=110,idx=2)"
    )
    assert tokens == {
        "raiseDead": ["s=106,idx=15", "s=110,idx=2"],
        "sigFallback": ["s=4,gi=1"],
    }
    assert _parse_detail_tokens("") == {}
    assert _parse_detail_tokens(None) == {}


def test_parse_detail_tokens_keeps_spaced_error_text():
    """`skip(...)` carries a Keynote error message that may contain spaces (fine, the
    scanner is not whitespace-split) or its own balanced nested parens (captured
    verbatim by depth-counting rather than corrupting neighbouring tokens)."""
    detail = (
        "raiseDead(s=106,idx=15) skip(font,s=4,err=-1728:Keynote got an error) "
        "skip(font,s=5,err=-1728:got (nested) error) raiseDead(s=110,idx=2)"
    )
    tokens = _parse_detail_tokens(detail)
    assert tokens["skip"] == [
        "font,s=4,err=-1728:Keynote got an error",
        "font,s=5,err=-1728:got (nested) error",
    ]
    assert tokens["raiseDead"] == ["s=106,idx=15", "s=110,idx=2"]


def test_parse_detail_tokens_ignores_token_shaped_text_inside_an_error_message():
    """A Keynote error message that itself contains token-shaped text (e.g. quoting
    another `raiseDead(...)`) must not manufacture a phantom top-level token: the
    depth-counting scanner keeps it as part of the enclosing `skip` token's args and
    never rescans consumed text."""
    detail = (
        "skip(font,s=4,err=-1728:Keynote says raiseDead(s=999,idx=1) is invalid) "
        "raiseDead(s=106,idx=15)"
    )
    tokens = _parse_detail_tokens(detail)
    assert tokens["skip"] == [
        "font,s=4,err=-1728:Keynote says raiseDead(s=999,idx=1) is invalid"
    ]
    assert tokens["raiseDead"] == ["s=106,idx=15"]


def test_parse_detail_tokens_boundaries():
    """An unbalanced outer token stops the scan with nothing emitted; a name glued to
    a preceding letter is its own (longer) token, not a phantom match on a suffix; and
    text inside an already-consumed token's args is never rescanned for nested tokens."""
    unbalanced = "skip(font,s=4,err=-1728:oops raiseDead(s=1,idx=1)"
    assert _parse_detail_tokens(unbalanced) == {}

    glued = "xraiseDead(s=1,idx=1)"
    tokens = _parse_detail_tokens(glued)
    assert tokens == {"xraiseDead": ["s=1,idx=1"]}
    assert "raiseDead" not in tokens

    wrapped = "(raiseDead(s=1,idx=1))"
    assert _parse_detail_tokens(wrapped) == {}


def test_run_stat_finalize_exposes_front_err_and_tokens(monkeypatch, tmp_path):
    """End-to-end through _run_stat_finalize's own raw-string parsing, with
    subprocess.run stubbed so no Keynote/osascript actually runs."""
    from types import SimpleNamespace

    import obed_edom.keynote as keynote_mod

    state = {"raw": ""}

    def fake_run(args, *a, **kw):
        if args[0] == "osascript":
            return SimpleNamespace(returncode=0, stdout=state["raw"], stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(keynote_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(keynote_mod.time, "sleep", lambda *_: None)

    jobs = [{"slide": 4, "groupIndex": 1, "childSig": "269"}]

    state["raw"] = (
        "done=1 skipped=0 sized=1 sizeSkips=0 front=1 dedupDeleted=0 dedupShortfall=0 "
        "frontErr= [-1743] [-1743] exported=false sigFallback=1 unresolved=0 badgeFallback=0 "
        "badgeUnresolved=0 badgeMoved=0 badgeFrontDead=0 raiseMoved=0 raiseDead=2 "
        "raiseUnknown=1 detail= raiseDead(s=106,idx=15) raiseDead(s=110,idx=2) "
        "raiseUnknown(s=42,idx=3) sigFallback(s=4,gi=1)"
    )
    result = keynote_mod._run_stat_finalize(tmp_path / "x.key", jobs, {"269": 200.0})
    assert result["frontErr"] == "[-1743] [-1743]"
    assert result["tokens"]["raiseDead"] == ["s=106,idx=15", "s=110,idx=2"]
    assert result["tokens"]["raiseUnknown"] == ["s=42,idx=3"]
    assert result["detail"] == (
        "raiseDead(s=106,idx=15) raiseDead(s=110,idx=2) raiseUnknown(s=42,idx=3) sigFallback(s=4,gi=1)"
    )


def test_run_stat_finalize_front_err_empty_when_absent(monkeypatch, tmp_path):
    """End-to-end through _run_stat_finalize's own raw-string parsing, with
    subprocess.run stubbed so no Keynote/osascript actually runs."""
    from types import SimpleNamespace

    import obed_edom.keynote as keynote_mod

    state = {"raw": ""}

    def fake_run(args, *a, **kw):
        if args[0] == "osascript":
            return SimpleNamespace(returncode=0, stdout=state["raw"], stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(keynote_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(keynote_mod.time, "sleep", lambda *_: None)

    jobs = [{"slide": 4, "groupIndex": 1, "childSig": "269"}]

    state["raw"] = (
        "done=1 skipped=0 sized=1 sizeSkips=0 front=1 dedupDeleted=0 dedupShortfall=0 "
        "frontErr= exported=false"
    )
    result = keynote_mod._run_stat_finalize(tmp_path / "x.key", jobs, {"269": 200.0})
    assert result["frontErr"] == ""
    assert result["tokens"] == {}

    state["raw"] = "done=1 skipped=0 sized=0 sizeSkips=0 front=0"
    result = keynote_mod._run_stat_finalize(tmp_path / "x.key", jobs, {"269": 200.0})
    assert result["frontErr"] == ""
    assert result["tokens"] == {}


def test_say_stat_finalize_detail_logs_every_token_kind():
    from obed_edom.remap_keynote import _say_stat_finalize_detail

    child_resize_result = {
        "tokens": {
            "raiseDead": ["s=106,idx=15", "s=110,idx=2"],
            "raiseUnknown": ["s=42,idx=3"],
            "sigTwin": ["s=1,gi=1"],
            "sigFallback": ["s=4,gi=1"],
            "unresolved": ["s=5,gi=2"],
            "dedupMiss": ["s=6,gi=3"],
            "skip": ["font,s=7,err=-1728:msg"],
            "badgeSkip": ["s=3,k=shape"],
        },
        "frontErr": "[-1743]",
        "detail": "badgeSkip(s=3,k=shape)",
    }
    lines: list[str] = []
    _say_stat_finalize_detail(child_resize_result, [{"slide": 3}], lines.append)

    raise_lines = [line for line in lines if line.startswith("Stat raise detail: ")]
    assert len(raise_lines) == 1
    assert "raiseDead(s=106,idx=15)" in raise_lines[0]
    assert "raiseDead(s=110,idx=2)" in raise_lines[0]
    assert "raiseUnknown(s=42,idx=3)" in raise_lines[0]
    assert "sigFallback" not in raise_lines[0]

    front_err_lines = [
        line
        for line in lines
        if line.startswith("WARNING stat-finalize: GUI Bring to Front returned error(s) [-1743]")
    ]
    assert len(front_err_lines) == 1

    assert "Badge raise detail: badgeSkip(s=3,k=shape)" in lines

    resolve_lines = [line for line in lines if line.startswith("Stat resolve detail: ")]
    assert len(resolve_lines) == 1
    resolve_line = resolve_lines[0]
    for kind in ("sigTwin", "unresolved", "dedupMiss", "skip(", "sigFallback"):
        assert kind in resolve_line
    fallback_at = resolve_line.index("sigFallback")
    for kind in ("sigTwin", "unresolved", "dedupMiss", "skip("):
        assert resolve_line.index(kind) < fallback_at


def test_say_stat_finalize_detail_silent_and_badge_gated():
    from obed_edom.remap_keynote import _say_stat_finalize_detail

    lines: list[str] = []
    _say_stat_finalize_detail({"tokens": {}, "frontErr": "", "detail": ""}, None, lines.append)
    assert lines == []

    lines = []
    _say_stat_finalize_detail(
        {"tokens": {"raiseDead": ["s=1,idx=1"]}, "frontErr": "", "detail": ""},
        None,
        lines.append,
    )
    assert len(lines) == 1
    assert lines[0].startswith("Stat raise detail: ")


def test_say_stat_finalize_detail_caps_sig_fallback():
    """Rare kinds (here `unresolved`) are never dropped; only the `sigFallback` tail is
    capped at `_DETAIL_LOG_CAP`, with the shortfall noted once truncation occurs."""
    from obed_edom.remap_keynote import _DETAIL_LOG_CAP, _say_stat_finalize_detail

    tokens = {
        "unresolved": [f"s={i},gi=1" for i in range(45)],
        "sigFallback": [f"s={i},gi=1" for i in range(110)],
    }
    lines: list[str] = []
    _say_stat_finalize_detail({"tokens": tokens, "frontErr": "", "detail": ""}, None, lines.append)
    resolve_lines = [line for line in lines if line.startswith("Stat resolve detail")]
    assert resolve_lines

    joined = " ".join(resolve_lines)
    assert joined.count("unresolved(") == 45
    assert joined.count("sigFallback(") == _DETAIL_LOG_CAP == 40

    truncated = [line for line in resolve_lines if line.endswith("(+70 more)")]
    assert len(truncated) == 1


def test_say_stat_finalize_detail_chunks_keep_the_prefix():
    """Multi-chunk raise logs must keep the exact greppable `Stat raise detail: `
    prefix on every line, with the `(i/n)` chunk marker placed after it."""
    from obed_edom.remap_keynote import _say_stat_finalize_detail

    raise_dead = [f"s={i},idx=1" for i in range(95)]
    raise_unknown = ["s=999,idx=1"]
    tokens = {"raiseDead": raise_dead, "raiseUnknown": raise_unknown}
    lines: list[str] = []
    _say_stat_finalize_detail({"tokens": tokens, "frontErr": "", "detail": ""}, None, lines.append)

    raise_lines = [line for line in lines if line.startswith("Stat raise detail: ")]
    assert len(raise_lines) == 3
    for line in raise_lines:
        body = line[len("Stat raise detail: ") :]
        assert body.split(" ", 1)[0] in ("(1/3)", "(2/3)", "(3/3)")

    for marker in ("(1/3)", "(2/3)", "(3/3)"):
        assert any(line.startswith(f"Stat raise detail: {marker} ") for line in raise_lines)

    seen: list[str] = []
    for line in raise_lines:
        seen.extend(re.findall(r"raise(?:Dead|Unknown)\(s=\d+,idx=1\)", line))
    expected = [f"raiseDead(s={i},idx=1)" for i in range(95)] + ["raiseUnknown(s=999,idx=1)"]
    assert sorted(seen) == sorted(expected)
    assert len(seen) == 96

    for line in raise_lines:
        assert len(re.findall(r"raise(?:Dead|Unknown)\(", line)) <= 40


def _front_handler(script: str) -> str:
    start = script.index("on obedFront(")
    end = script.index("\nend obedFront\n", start)
    return script[start:end]


def _front_ready_handler(script: str) -> str:
    start = script.index("on obedFrontReady(")
    return script[start : script.index("end obedFrontReady", start)]


def test_obed_front_takes_phase_slide_index_and_tags_front_err():
    """obedFront gets three params, and every call site plus its own error tag passes
    them through, so a raise/badge -1719 can be traced to the exact slide/index/phase."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {},
        badge_raises=[
            {"slide": 1, "kind": "shape", "index": 1, "isTitle": False, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        ],
    )
    assert "on obedFront(phase, slideNo, idx)" in script
    front = _front_handler(script)
    assert '& "@" & phase & ",s=" & slideNo & ",idx=" & idx & ",retry]"' in front
    # All three call sites, explicit -- raise (obedRaiseSlide), retry (obedRaiseRetry),
    # badge (obedRaiseItem, passing the resolved _hit, never the planned idx).
    assert 'my obedFront("raise", slideNo, _mn)' in script
    assert script.count('my obedFront("raise", slideNo, _mn)') == 2
    assert 'my obedFront("badge", slideNo, _hit)' in script
    assert '" exported="' not in front  # never breaks the non-greedy frontErr parser


def test_front_err_tag_is_always_retry_never_the_untagged_shape():
    """Every `frontErr` entry is post-retry by construction now (only a second
    failure ever reaches `frontErr`), so the tag is always `,retry]`; the un-tagged
    shape from before this fix must not appear anywhere in the handler."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    front = _front_handler(script)
    assert front.count('",retry]"') == 1
    assert '",idx=" & idx & ")"' not in front


def test_obed_front_polls_menu_enabled_before_clicking():
    """The poll (now obedFrontReady) always precedes the click, on both attempts."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    front = _front_handler(script)
    ready = _front_ready_handler(script)
    assert front.count("my obedFrontReady(phase, slideNo, idx)") == 2
    first_ready_at = front.index("my obedFrontReady(phase, slideNo, idx)")
    first_click_at = front.index('click menu item "Bring to Front"')
    assert first_ready_at < first_click_at
    assert 'enabled of menu item "Bring to Front"' in ready
    assert "repeat" in ready and "exit repeat" in ready


def test_obed_front_emits_raise_blind_when_not_enabled_and_still_clicks(monkeypatch):
    """OBED_RAISE_SETTLE_MAX=0 collapses the poll to a single read; if it's not enabled,
    raiseBlind is emitted and obedFrontReady still returns, so obedFront still clicks
    unconditionally."""
    monkeypatch.setenv("OBED_RAISE_SETTLE_MAX", "0")
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    ready = _front_ready_handler(script)
    ready_at = ready.index("if not _ready then")
    blind_at = ready.index('raiseBlind(s=" & slideNo & ",idx=" & idx & ",phase=" & phase & ")')
    return_at = ready.index("return _ready")
    assert ready_at < blind_at < return_at
    assert "set raiseBlindCount to raiseBlindCount + 1" in ready
    front = _front_handler(script)
    assert 'click menu item "Bring to Front"' in front


def test_raise_settle_bounds_rejects_invalid_and_non_finite_values(monkeypatch):
    """Negative/non-numeric settle_max, and non-finite settle_min or settle_max (inf,
    nan), must all fall back rather than emit an AppleScript-illegal literal."""
    from obed_edom.keynote import _raise_settle_bounds

    monkeypatch.delenv("OBED_RAISE_SETTLE_MIN", raising=False)
    monkeypatch.delenv("OBED_RAISE_SETTLE_MAX", raising=False)

    monkeypatch.setenv("OBED_RAISE_SETTLE_MAX", "-1")
    assert _raise_settle_bounds() == (0.35, 1.5)

    monkeypatch.setenv("OBED_RAISE_SETTLE_MAX", "not-a-number")
    assert _raise_settle_bounds() == (0.35, 1.5)

    monkeypatch.setenv("OBED_RAISE_SETTLE_MAX", "inf")
    assert _raise_settle_bounds() == (0.35, 1.5)

    monkeypatch.setenv("OBED_RAISE_SETTLE_MAX", "nan")
    assert _raise_settle_bounds() == (0.35, 1.5)

    monkeypatch.delenv("OBED_RAISE_SETTLE_MAX", raising=False)
    monkeypatch.setenv("OBED_RAISE_SETTLE_MIN", "inf")
    assert _raise_settle_bounds() == (0.35, 1.5)

    monkeypatch.setenv("OBED_RAISE_SETTLE_MIN", "nan")
    assert _raise_settle_bounds() == (0.35, 1.5)

    monkeypatch.delenv("OBED_RAISE_SETTLE_MIN", raising=False)
    monkeypatch.setenv("OBED_RAISE_SETTLE_MAX", "0")
    assert _raise_settle_bounds() == (0.35, 0.0)  # exactly 0 stays allowed


def test_obed_front_settle_max_zero_threshold_checked_before_poll_delay(monkeypatch):
    """With settle_max=0 the loop's ceiling check must run before `delay 0.1`, so the
    poll performs exactly one `enabled` read and exits without ever sleeping 0.1 s."""
    monkeypatch.setenv("OBED_RAISE_SETTLE_MAX", "0")
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    ready = _front_ready_handler(script)
    threshold_at = ready.index("if _waited >= 0.000 then exit repeat")
    poll_delay_at = ready.index("delay 0.1")
    assert threshold_at < poll_delay_at


def test_obed_front_settle_env_never_shortens_below_todays_floor(monkeypatch):
    monkeypatch.setenv("OBED_RAISE_SETTLE_MIN", "0.01")
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    ready = _front_ready_handler(script)
    assert "delay 0.350" in ready  # clamped, not 0.010
    front = _front_handler(script)
    assert "delay 0.2" in front  # the post-click settle is never touched by env


def test_obed_front_retries_once_after_a_click_error():
    """A click error in obedFront re-enters the readiness sequence and issues a second
    click; exactly two click sites, the retry's poll strictly precedes its click."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    front = _front_handler(script)
    assert front.count('click menu item "Bring to Front"') == 2
    assert front.count("my obedFrontReady(phase, slideNo, idx)") == 2
    assert front.count("on error errMsg number errNum") == 2
    first_error_at = front.index("on error errMsg number errNum")
    second_ready_at = front.index("my obedFrontReady(phase, slideNo, idx)", first_error_at)
    second_click_at = front.index('click menu item "Bring to Front"', first_error_at)
    assert first_error_at < second_ready_at < second_click_at


def test_obed_front_counts_front_raised_once_per_call():
    """`frontRaised` is incremented exactly once per successful click path, and each
    increment is structurally unreachable from the error path: it sits behind an
    `if _clicked then` guard, outside any `try`, so a throw from the click or from the
    post-click `delay 0.2` can never re-enter this statement -- unlike a bare `try`
    body, where an exception after a successful click (e.g. from `delay 0.2`) would
    fall into `on error` and manufacture a second click and a second increment."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    front = _front_handler(script)
    assert front.count("set frontRaised to frontRaised + 1") == 2
    assert front.count("set _clicked to true") == 2
    assert front.count("if _clicked then") == 2

    first_click_at = front.index('click menu item "Bring to Front"')
    first_clicked_at = front.index("set _clicked to true")
    first_error_at = front.index("on error errMsg number errNum")
    first_guard_at = front.index("if _clicked then")
    first_incr_at = front.index("set frontRaised to frontRaised + 1")
    assert first_click_at < first_clicked_at < first_error_at < first_guard_at < first_incr_at

    # The increment is outside the try/on-error block entirely: nothing between the
    # error handler's `end try` and the guard can re-enter it.
    first_end_try_at = front.index("end try", first_error_at)
    assert first_end_try_at < first_guard_at

    second_clicked_at = front.index("set _clicked to true", first_error_at)
    second_error_at = front.index("on error errMsg number errNum", first_error_at + 1)
    second_end_try_at = front.index("end try", second_error_at)
    second_guard_at = front.index("if _clicked then", first_guard_at + 1)
    second_incr_at = front.index("set frontRaised to frontRaised + 1", first_incr_at + 1)
    assert (
        first_incr_at
        < second_clicked_at
        < second_error_at
        < second_end_try_at
        < second_guard_at
        < second_incr_at
    )


def test_obed_front_first_error_emits_raise_click_retry_token_not_front_err():
    """The first `on error` bumps raiseClickRetried and writes raiseClickRetry(...) into
    `report`; it must not touch `frontErr` -- only a second failure does that."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    front = _front_handler(script)
    first_error_at = front.index("on error errMsg number errNum")
    second_error_at = front.index("on error errMsg number errNum", first_error_at + 1)
    first_error_block = front[first_error_at:second_error_at]
    assert "set raiseClickRetried to raiseClickRetried + 1" in first_error_block
    assert (
        'raiseClickRetry(s=" & slideNo & ",idx=" & idx & ",phase=" & phase & ",err=" & errNum & ")'
        in first_error_block
    )
    assert "frontErr" not in first_error_block


def test_obed_front_second_error_tags_front_err_with_retry():
    """Only the second failure appends to `frontErr`, tagged `,retry]`; the handler
    never emits the literal ` exported=` that both parsers cut on."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    front = _front_handler(script)
    first_error_at = front.index("on error errMsg number errNum")
    second_error_at = front.index("on error errMsg number errNum", first_error_at + 1)
    second_error_block = front[second_error_at:]
    assert (
        '& " [" & errNum & "@" & phase & ",s=" & slideNo & ",idx=" & idx & ",retry]"'
        in second_error_block
    )
    assert front.count("frontErr") == 3  # global decl + "frontErr to frontErr" on the tag line
    assert '" exported="' not in front


def test_raise_click_retry_token_carries_no_error_message_text():
    """`errMsg` must never reach the raiseClickRetry token -- it can contain parens and
    would confuse `_parse_detail_tokens`."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    front = _front_handler(script)
    retry_token_at = front.index('raiseClickRetry(s=" & slideNo')
    token_line_end = front.index("\n", retry_token_at)
    token_line = front[retry_token_at:token_line_end]
    assert "errMsg" not in token_line


def test_badge_probe_reruns_after_a_retried_click():
    """When obedFront reports a retry (non-zero return), obedRaiseItem must enter the
    liveness-probe branch even though badgeMoved is non-zero, and must not take the
    blind `badgeMoved + 1` branch on that path."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {},
        badge_raises=[
            {"slide": 1, "kind": "shape", "index": 1, "isTitle": False, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        ],
    )
    handler = script[script.index("on obedRaiseItem") : script.index("end obedRaiseItem")]
    assert "set _frontResult to my obedFront(\"badge\", slideNo, _hit)" in handler
    top_if_at = handler.index(
        "if (badgeMoved is 0 or _frontResult is not 0) and badgeFrontDead is 0 then"
    )
    top_else_at = handler.index("else if badgeFrontDead is 0 then", top_if_at)
    blind_block = handler[top_else_at:]
    assert "set badgeMoved to badgeMoved + 1" in blind_block
    probe_block = handler[top_if_at:top_else_at]
    assert "set badgeMoved to badgeMoved + 1" in probe_block  # the verified-landed branch


def test_obed_front_post_click_delay_survives_the_retry_path():
    """`delay 0.2` follows each successful click, on both the first and retried
    attempt, and (like `frontRaised`) sits behind the `if _clicked then` guard outside
    the `try`, never on the failure path before the retry's own poll."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    front = _front_handler(script)
    assert front.count("delay 0.2") == 2
    first_click_at = front.index('click menu item "Bring to Front"')
    second_click_at = front.index(
        'click menu item "Bring to Front"', first_click_at + 1
    )
    first_error_at = front.index("on error errMsg number errNum")
    second_error_at = front.index(
        "on error errMsg number errNum", first_error_at + 1
    )
    first_guard_at = front.index("if _clicked then")
    second_guard_at = front.index("if _clicked then", first_guard_at + 1)
    first_delay_at = front.index("delay 0.2")
    assert first_click_at < first_error_at < first_guard_at < first_delay_at
    second_delay_at = front.index("delay 0.2", second_guard_at)
    second_return_at = front.index("return 1", second_delay_at)
    assert (
        second_click_at
        < second_error_at
        < second_guard_at
        < second_delay_at
        < second_return_at
    )


def test_raise_dead_retries_once_with_a_longer_settle_then_reports():
    """A verified dead raise gets exactly one retry (obedRaiseRetry) before it falls
    into the unchanged raiseDead branch; on the retry's success, `_at` becomes `_top`
    and the existing landed-branch decrement runs -- never a second, separate decrement
    living inside the dead branch's own text."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    assert "on obedRaiseRetry(slideNo, _mn, _top, _f)" in script
    retry = script[script.index("on obedRaiseRetry") : script.index("end obedRaiseRetry")]
    assert "set selection of theDoc to {group _mn of slide slideNo of theDoc}" in retry
    assert 'my obedFront("raise", slideNo, _mn)' in retry
    assert "delay 1.050" in retry  # max(1.0, 0.35 * 3)

    handler = _raise_slide_handler(script)
    retry_call_at = handler.index("my obedRaiseRetry(slideNo, _mn, _top, _f)")
    dead_mn_at = handler.index("if (_mn is not _top) and (_at is _mn) then")
    top_at = handler.index("if _at is _top then")
    assert dead_mn_at < retry_call_at < top_at
    assert "set raiseRetried to raiseRetried + 1" in handler
    # Exactly one retry call site, gated by exactly one guard that excludes the
    # vacuous case (_mn is _top) explicitly -- that case can never reach
    # obedRaiseRetry.
    assert handler.count("my obedRaiseRetry(slideNo, _mn, _top, _f)") == 1
    assert handler.count("if (_mn is not _top) and (_at is _mn) then") == 1

    # The pre-existing structural invariants (must stay true post-retry).
    mn_branch_at = handler.index("else if _at is _mn then")
    unknown_at = handler.index("    else\n")
    top_branch = handler[top_at:mn_branch_at]
    dead_branch = handler[mn_branch_at:unknown_at]
    assert "- 1" in top_branch
    assert "- 1" not in dead_branch


def test_raise_vacuous_token_when_target_is_top_real():
    """A target already at `_top` before the click cannot fail the landing probe --
    raiseVacuous marks that, purely observational (the raise still proceeds as usual)."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    handler = _raise_slide_handler(script)
    top_check_at = handler.index("if _mn is _top then")
    front_at = handler.index('my obedFront("raise", slideNo, _mn)')
    assert top_check_at < front_at
    assert 'raiseVacuous(s=" & slideNo & ",idx=" & _mn & ")' in handler
    assert "set raiseVacuous to raiseVacuous + 1" in handler


def test_stat_accumulators_include_raise_blind_counters():
    assert "raiseBlindCount" in _STAT_ACCUMULATORS
    assert "raiseVacuous" in _STAT_ACCUMULATORS
    assert "raiseRetried" in _STAT_ACCUMULATORS
    assert "raiseClickRetried" in _STAT_ACCUMULATORS


def test_finalize_return_string_carries_raise_blind_counters():
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [{"slide": 4, "groupIndex": 1, "childSig": "111"}], {}
    )
    assert "set raiseBlindCount to 0" in script
    assert "set raiseVacuous to 0" in script
    assert "set raiseRetried to 0" in script
    assert "set raiseClickRetried to 0" in script
    assert '" raiseBlindCount=" & raiseBlindCount' in script
    assert '" raiseVacuous=" & raiseVacuous' in script
    assert '" raiseRetried=" & raiseRetried' in script
    assert '" raiseClickRetried=" & raiseClickRetried' in script


def test_run_stat_finalize_result_dict_exposes_raise_blind_counters(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import obed_edom.keynote as keynote_mod

    state = {"raw": ""}

    def fake_run(args, *a, **kw):
        if args[0] == "osascript":
            return SimpleNamespace(returncode=0, stdout=state["raw"], stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(keynote_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(keynote_mod.time, "sleep", lambda *_: None)

    jobs = [{"slide": 4, "groupIndex": 1, "childSig": "269"}]

    state["raw"] = (
        "done=1 skipped=0 sized=1 sizeSkips=0 front=1 dedupDeleted=0 dedupShortfall=0 "
        "frontErr= exported=false sigFallback=0 unresolved=0 badgeFallback=0 "
        "badgeUnresolved=0 badgeMoved=0 badgeFrontDead=0 raiseMoved=5 raiseDead=1 "
        "raiseUnknown=2 raiseBlindCount=3 raiseVacuous=4 raiseRetried=1 "
        "detail= raiseDead(s=4,idx=2)"
    )
    result = keynote_mod._run_stat_finalize(tmp_path / "x.key", jobs, {"269": 200.0})
    assert result["raiseBlindCount"] == 3
    assert result["raiseVacuous"] == 4
    assert result["raiseRetried"] == 1


def test_run_stat_finalize_result_dict_exposes_raise_click_retried(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import obed_edom.keynote as keynote_mod

    state = {"raw": ""}

    def fake_run(args, *a, **kw):
        if args[0] == "osascript":
            return SimpleNamespace(returncode=0, stdout=state["raw"], stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(keynote_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(keynote_mod.time, "sleep", lambda *_: None)

    jobs = [{"slide": 4, "groupIndex": 1, "childSig": "269"}]
    state["raw"] = (
        "done=1 skipped=0 sized=1 sizeSkips=0 front=1 dedupDeleted=0 dedupShortfall=0 "
        "frontErr= exported=false sigFallback=0 unresolved=0 badgeFallback=0 "
        "badgeUnresolved=0 badgeMoved=1 badgeFrontDead=0 raiseMoved=0 raiseDead=0 "
        "raiseUnknown=0 raiseBlindCount=0 raiseVacuous=0 raiseRetried=0 raiseClickRetried=1 "
        "detail= raiseClickRetry(s=8,idx=1,phase=badge,err=-1719)"
    )
    result = keynote_mod._run_stat_finalize(tmp_path / "x.key", jobs, {"269": 200.0})
    assert result["raiseClickRetried"] == 1
    assert result["tokens"]["raiseClickRetry"] == ["s=8,idx=1,phase=badge,err=-1719"]


def test_front_err_retry_tag_round_trips_through_both_parsers(monkeypatch, tmp_path):
    """A post-retry `frontErr` entry carrying `,retry]` must still round-trip through
    both keynote.py's own regex and offline_write_ab.front_err_from_raw."""
    from types import SimpleNamespace

    import obed_edom.keynote as keynote_mod
    from scripts.offline_write_ab import front_err_from_raw

    state = {"raw": ""}

    def fake_run(args, *a, **kw):
        if args[0] == "osascript":
            return SimpleNamespace(returncode=0, stdout=state["raw"], stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(keynote_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(keynote_mod.time, "sleep", lambda *_: None)

    jobs = [{"slide": 4, "groupIndex": 1, "childSig": "269"}]
    state["raw"] = (
        "done=1 skipped=0 sized=1 sizeSkips=0 front=1 dedupDeleted=0 dedupShortfall=0 "
        "frontErr= [-1719@badge,s=8,idx=1,retry] exported=false sigFallback=0 unresolved=0 "
        "badgeFallback=0 badgeUnresolved=0 badgeMoved=0 badgeFrontDead=0 raiseMoved=0 "
        "raiseDead=0 raiseUnknown=0 raiseBlindCount=0 raiseVacuous=0 raiseRetried=0 "
        "raiseClickRetried=1 detail="
    )
    result = keynote_mod._run_stat_finalize(tmp_path / "x.key", jobs, {"269": 200.0})
    assert result["frontErr"] == "[-1719@badge,s=8,idx=1,retry]"
    assert front_err_from_raw(state["raw"]).strip() == "[-1719@badge,s=8,idx=1,retry]"


def test_front_err_entry_round_trips_through_both_parsers(monkeypatch, tmp_path):
    """A richer `frontErr` entry carrying `@phase,s=,idx=` must still round-trip through
    both keynote.py's own regex and offline_write_ab.front_err_from_raw."""
    from types import SimpleNamespace

    import obed_edom.keynote as keynote_mod
    from scripts.offline_write_ab import front_err_from_raw

    state = {"raw": ""}

    def fake_run(args, *a, **kw):
        if args[0] == "osascript":
            return SimpleNamespace(returncode=0, stdout=state["raw"], stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(keynote_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(keynote_mod.time, "sleep", lambda *_: None)

    jobs = [{"slide": 4, "groupIndex": 1, "childSig": "269"}]
    state["raw"] = (
        "done=1 skipped=0 sized=1 sizeSkips=0 front=1 dedupDeleted=0 dedupShortfall=0 "
        "frontErr= [-1719@raise,s=40,idx=1] exported=false sigFallback=0 unresolved=0 "
        "badgeFallback=0 badgeUnresolved=0 badgeMoved=0 badgeFrontDead=0 raiseMoved=0 "
        "raiseDead=1 raiseUnknown=0 raiseBlindCount=0 raiseVacuous=0 raiseRetried=0 detail="
    )
    result = keynote_mod._run_stat_finalize(tmp_path / "x.key", jobs, {"269": 200.0})
    assert result["frontErr"] == "[-1719@raise,s=40,idx=1]"
    assert front_err_from_raw(state["raw"]).strip() == "[-1719@raise,s=40,idx=1]"


def test_say_stat_finalize_detail_logs_raise_blind_and_vacuous():
    from obed_edom.remap_keynote import _say_stat_finalize_detail

    child_resize_result = {
        "tokens": {
            "raiseBlind": ["s=40,idx=1,phase=raise"],
            "raiseVacuous": ["s=20,idx=1"],
        },
        "frontErr": "",
        "detail": "",
    }
    lines: list[str] = []
    _say_stat_finalize_detail(child_resize_result, None, lines.append)
    raise_lines = [line for line in lines if line.startswith("Stat raise detail: ")]
    assert len(raise_lines) == 1
    assert "raiseBlind(s=40,idx=1,phase=raise)" in raise_lines[0]
    assert "raiseVacuous(s=20,idx=1)" in raise_lines[0]


def test_say_stat_finalize_detail_logs_raise_click_retry():
    from obed_edom.remap_keynote import _say_stat_finalize_detail

    child_resize_result = {
        "tokens": {
            "raiseClickRetry": ["s=8,idx=1,phase=badge,err=-1719"],
        },
        "frontErr": "",
        "detail": "",
    }
    lines: list[str] = []
    _say_stat_finalize_detail(child_resize_result, None, lines.append)
    raise_lines = [line for line in lines if line.startswith("Stat raise detail: ")]
    assert len(raise_lines) == 1
    assert "raiseClickRetry(s=8,idx=1,phase=badge,err=-1719)" in raise_lines[0]
