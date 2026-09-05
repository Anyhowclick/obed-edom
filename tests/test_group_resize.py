"""Pure-Python tests for the stat-finalize pass.

The pass itself is AppleScript (template-taught number sizes + bring-to-front) and is
validated against Keynote separately. These lock the pure-Python parts: the planner
emitting one job per stat group, and the generated AppleScript embedding the template
sizes and the z-order/badge steps.

Index is verified by content; descending raise relies on Bring-to-Front append
semantics. Handlers that name Keynote objects MUST wrap the body in `tell application id`
(not just `using terms from`) or `count of iWork items` fails -1700.
DFS-leaf-signature separator MUST equal iwa_runs._SIG_JOIN ("\\n").
Delete highest-index first.
"""

import re
from pathlib import Path

from obed_edom.keynote import _STAT_ACCUMULATORS, _build_stat_finalize_script, _run_stat_finalize
from obed_edom.map_remap import (
    ItemTransform,
    adjust_child_resize_indexes,
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


def test_badge_raise_report_frame_comes_from_the_emitted_transform():
    """A badge line's `mapped` is overwritten by lineSlots AFTER the mid-loop badge_dst
    merge (2625-2628): the report row must carry that final value, not the stale one."""
    recipe = {
        "destWidth": 1920.0,
        "destHeight": 1080.0,
        "mapSrc": {"x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0},
        "mapDst": {"x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0},
        "badgePlateDst": {"x": 17.0, "y": 37.0, "w": 300.0, "h": 80.0},
        "badgeSlots": {
            "shape:0": {"x": 17.0, "y": 37.0, "w": 300.0, "h": 80.0},
            "line:0": {"x": 90.0, "y": 60.0, "w": 20.0, "h": 0.0},
        },
        "titleDst": {"x": 107.0, "y": 79.5, "w": 296.0, "h": 40.0},
        "lineSlots": [{"x": 90.0, "y": 60.0, "w": 98.0, "h": 0.0}],
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
            _item(index=2, kindIndex=0, kind="line", x=3660, y=130, w=20, h=0),
        ],
    }
    report: list[dict] = []
    plan_slide_transforms(slide, recipe, wall_size=(7680, 1080), badge_raise_report=report)
    line_row = next(j for j in report if j["kind"] == "line")
    assert line_row["w"] == 98.0  # from lineSlots, not the 20.0 badge_dst merge value


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


def test_finalize_phase2_raises_resolved_targets_descending():
    """Phase 2 raises recorded targets per slide, highest index first (Bring to Front appends)."""
    jobs = [
        {"slide": 4, "groupIndex": 1, "childSig": "111"},
        {"slide": 4, "groupIndex": 3, "childSig": "222"},
        {"slide": 5, "groupIndex": 2, "childSig": "333"},
    ]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {"269": 200.0})
    assert "my obedRaiseSlide(4)" in script
    assert "my obedRaiseSlide(5)" in script
    assert "> _mx" in script
    assert "set selection of theDoc to {group _mx of slide slideNo of theDoc}" in script
    assert "obedZRaise" not in script
    assert "obedSigLeaves(group _gi of slide slideNo of theDoc) is sig" not in script


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
    assert 'my obedBadgeSlide(1, {{k:"shape", i:1, x:17.0, y:37.0, w:411.0, h:123.0, mh:true}})' in script


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

    raw = (
        "done=1 skipped=0 sized=1 sizeSkips=0 front=1 dedupDeleted=0 dedupShortfall=0 "
        "frontErr= exported=false sigFallback=0 unresolved=0 badgeFallback=2 "
        "badgeUnresolved=3 badgeMoved=4 badgeFrontDead=0 detail="
    )

    def fake_run(args, *a, **kw):
        if args[0] == "osascript":
            return SimpleNamespace(returncode=0, stdout=raw, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(keynote_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(keynote_mod.time, "sleep", lambda *_: None)

    jobs = [{"slide": 4, "groupIndex": 1, "childSig": "269"}]
    result = keynote_mod._run_stat_finalize(tmp_path / "x.key", jobs, {"269": 200.0})
    assert result["badgeFallback"] == 2
    assert result["badgeUnresolved"] == 3
    assert result["badgeMoved"] == 4
    assert result["badgeFrontDead"] == 0


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


def test_badge_text_and_line_rows_do_not_match_on_height():
    """An autosize text box's live height is Keynote-derived and a rotated line's
    reported height is its bounding box, not its length -- neither is a frame the
    planner can guard. mh (matchH) must be false for text/line, true for shape/image."""
    badge_raises = [
        {"slide": 1, "kind": "shape", "index": 1, "isTitle": False, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        {"slide": 1, "kind": "image", "index": 2, "isTitle": False, "x": 31.0, "y": 59.0, "w": 80.0, "h": 80.0},
        {"slide": 1, "kind": "text", "index": 1, "isTitle": True, "x": 107.0, "y": 79.5, "w": 296.0, "h": 40.0},
        {"slide": 1, "kind": "line", "index": 1, "isTitle": False, "x": 184.0, "y": 97.0, "w": 98.0, "h": 0.0},
    ]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), [], {}, badge_raises=badge_raises)
    call_at = script.index("my obedBadgeSlide(1,")
    call_line = script[call_at : script.index("\n", call_at)]
    assert 'k:"shape", i:1, x:17.0, y:37.0, w:411.0, h:123.0, mh:true' in call_line
    assert 'k:"image", i:2, x:31.0, y:59.0, w:80.0, h:80.0, mh:true' in call_line
    assert 'k:"text", i:1, x:107.0, y:79.5, w:296.0, h:40.0, mh:false' in call_line
    assert 'k:"line", i:1, x:184.0, y:97.0, w:98.0, h:0.0, mh:false' in call_line
    matches_handler = script[script.index("on obedFrameMatches") : script.index("end obedFrameMatches")]
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


def test_badge_front_dead_short_circuits_further_raises():
    """obedBadgeSlide starts with `if badgeFrontDead is 1 then return`, and obedRaiseItem
    sets badgeFrontDead when the raised object does not end up last of its kind (the GUI
    Bring-to-Front proved inert) -- so no later member or slide attempts a raise."""
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {},
        badge_raises=[
            {"slide": 1, "kind": "shape", "index": 1, "isTitle": False, "x": 17.0, "y": 37.0, "w": 411.0, "h": 123.0},
        ],
    )
    slide_lines = [l.strip() for l in
                   script[script.index("on obedBadgeSlide") : script.index("end obedBadgeSlide")].splitlines()
                   if l.strip()]
    assert slide_lines[0].startswith("on obedBadgeSlide")
    assert slide_lines[1].startswith("global")
    assert slide_lines[2] == "if badgeFrontDead is 1 then return"
    raise_handler = script[script.index("on obedRaiseItem") : script.index("end obedRaiseItem")]
    assert "set badgeFrontDead to 1" in raise_handler


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
