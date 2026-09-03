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

from obed_edom.keynote import _build_stat_finalize_script, _run_stat_finalize
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
    assert 'my obedStatJob(4, _sigs, 1, {"269"}, 1.0, 1)' in script
    assert 'my obedStatJob(4, _sigs, 6, {"183", "Schools"}, 1.0, 1)' in script
    assert "set size of characters 1 thru -1 of object text of _leaf to (_c1 * s)" in script
    # No baked-in group <digits> of slide object specifiers.
    assert not re.search(r"set g to group \d+ of slide", script)
    assert not re.search(r"set selection of theDoc to \{group \d+ of slide", script)
    assert script.count("Bring to Front") >= 1
    # The badge is searched for and raised too.
    assert "Global Missions" in script


def test_finalize_font_call_carries_group_scale():
    """A job's affine scale `s` reaches the AppleScript font call verbatim, so the pass
    scales that group's non-number text leaves by it (fonts don't scale with the frame)."""
    jobs = [{"slide": 4, "groupIndex": 1, "childSig": "CHC Arao", "s": 0.8547}]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), jobs, {})
    assert 'my obedStatJob(4, _sigs, 1, {"CHC Arao"}, 0.8547, 1)' in script


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
    badge_raises = [{"slide": 1, "kind": "shape", "index": 1, "isTitle": False}]
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {}, badge_raises=badge_raises
    )
    assert script != ""
    assert 'my obedRaiseItem(1, "shape", 1)' in script


def test_finalize_badge_raises_emit_after_raise_slide_in_plate_globe_title_order():
    jobs = [{"slide": 4, "groupIndex": 1, "childSig": "269"}]
    badge_raises = [
        {"slide": 4, "kind": "shape", "index": 1, "isTitle": False},
        {"slide": 4, "kind": "image", "index": 2, "isTitle": False},
        {"slide": 4, "kind": "text", "index": 1, "isTitle": True},
    ]
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), jobs, {"269": 200.0}, badge_raises=badge_raises
    )
    raise_slide_at = script.index("my obedRaiseSlide(4)")
    shape_at = script.index('my obedRaiseItem(4, "shape", 1)')
    image_at = script.index('my obedRaiseItem(4, "image", 2)')
    badge_at = script.index("my obedBadgeRaise(4)")
    assert raise_slide_at < shape_at < image_at < badge_at
    # The title never gets an indexed raise call -- it stays content-search only.
    assert 'my obedRaiseItem(4, "text"' not in script


def test_finalize_obed_badge_raise_exits_on_first_hit():
    """The old obedBadgeRaise ran all three search loops unconditionally, so only the
    LAST match in the last loop ever stayed selected. Each loop must now stop the
    others once a match is found."""
    script = _build_stat_finalize_script(Path("/tmp/x.key"), [], {})
    assert script == ""  # sanity: still gated when nothing is asked for
    script = _build_stat_finalize_script(
        Path("/tmp/x.key"), [], {}, badge_raises=[{"slide": 1, "kind": "text", "index": 1, "isTitle": True}]
    )
    handler = script[script.index("on obedBadgeRaise") : script.index("end obedBadgeRaise")]
    assert handler.count("if _found then exit repeat") == 4
    assert "if not _found then" in handler


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
        badge_raises.append({"slide": slide, "kind": "shape", "index": 1, "isTitle": False})
        badge_raises.append({"slide": slide, "kind": "image", "index": 2, "isTitle": False})
        badge_raises.append({"slide": slide, "kind": "text", "index": 1, "isTitle": True})

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
    try_at = handler.index("    try")
    assert raise_at < try_at


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
    assert 'my obedStatJob(9, _sigs, 10, {"UPG"}, 0.483, 0)' in script
    assert 'my obedStatJob(9, _sigs, 11, {"UPG"}, 0.483, 0)' in script
    assert 'my obedStatJob(9, _sigs, 12, {"CHC"}, 0.483, 1)' in script


def test_finalize_reuse_voids_group_index_in_call():
    transforms = [_hide(2, 0)]
    child_resize = [{"slide": 2, "groupIndex": 4, "childSig": "unique-sig"}]
    adjustments = adjust_child_resize_indexes(child_resize, transforms, {2})
    assert child_resize[0]["groupIndex"] == 0
    assert adjustments == [{"slide": 2, "from": 4, "to": 0}]
    script = _build_stat_finalize_script(Path("/tmp/x.key"), child_resize, {})
    assert "my obedStatJob(2, _sigs, 0," in script
    assert ", 0," in script
