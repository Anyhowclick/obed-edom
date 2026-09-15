"""W2 piece 4: A/B z-order verdicts on synthetic order lists (Keynote-free).

Mirrors ``tests/test_offline_write_ab_slides.py`` — pure comparison logic, no decks.
"""
from __future__ import annotations

import pytest

from scripts.offline_write_ab import (
    ZORDER_SCHEMA_KEYS,
    ZORDER_SURFACE_KEYS,
    ZORDER_ZERO_KEYS,
    claimed_patched_slides,
    expect_gui_raises,
    expected_zorder_sets,
    front_block_ok,
    front_targets_for_slide,
    persisted_raise_jobs,
    plan_parity,
    run_record,
    same_order,
    suppressed_raise_reasons,
    zorder_counter_reasons,
    zorder_counter_summary,
    zorder_schema_reasons,
    zorder_slide_verdict,
    zorder_write_reasons,
)


def _zorder_write(**overrides):
    record = {
        "slides": [],
        "zorderSlides": 0,
        "zorderStatRaised": 0,
        "zorderBadgeRaised": 0,
        "zorderNoop": 0,
        "zorderRefused": 0,
        "zorderUnresolved": 0,
        "zorderLost": 0,
        "zorderGui": [],
    }
    record.update(overrides)
    return record


def test_same_order_yes_and_no():
    ids = ["a", "b", "c", "d"]
    assert same_order(ids, list(ids)) is True
    assert same_order(ids, ["a", "c", "b", "d"]) is False
    assert same_order([], []) is True


def test_front_block_ok_targets_at_end_in_both_arms():
    targets = ["t1", "t2"]
    a = ["x", "y", "t1", "t2"]
    b = ["y", "x", "t1", "t2"]
    assert front_block_ok(a, b, targets) is True
    assert same_order(a, b) is False  # Gold: non-targets scramble, front block holds


def test_front_block_ok_fails_when_block_differs():
    targets = ["t1", "t2"]
    a = ["x", "t1", "t2"]
    b = ["x", "t2", "t1"]
    assert front_block_ok(a, b, targets) is False


def test_front_block_ok_fails_when_targets_are_not_the_suffix():
    targets = ["t1", "t2"]
    buried = ["t1", "t2", "x"]
    assert front_block_ok(buried, buried, targets) is False
    assert same_order(buried, buried) is True


def test_front_block_ok_empty_targets_is_vacuous_pass():
    assert front_block_ok(["a"], ["b"], []) is True


def test_front_block_ok_rejects_short_orders():
    assert front_block_ok(["t1"], ["t1", "t2"], ["t1", "t2"]) is False


def test_zorder_slide_verdict_missing_orders_fail_both():
    assert zorder_slide_verdict(None, ["a"], ["a"]) == {
        "sameOrder": False, "frontBlockOk": False, "targets": ["a"],
    }
    assert zorder_slide_verdict(["a"], None, ["a"])["frontBlockOk"] is False


def test_zorder_counter_reasons_zero_or_missing_is_green():
    # Zero-key helper only inspects present keys. The gate itself is
    # zorder_write_reasons, which REDs a missing schema instead of reading 0.
    assert zorder_counter_reasons(None) == []
    assert zorder_counter_reasons({}) == []
    assert zorder_counter_reasons({
        "zorderRefused": 0, "zorderUnresolved": [], "zorderLost": "",
    }) == []


def test_zorder_counter_reasons_flags_each_nonzero_key():
    reasons = zorder_counter_reasons({
        "zorderRefused": 1,
        "zorderUnresolved": ["zorderUnresolved(s=4,k=group,i=0)"],
        "zorderLost": ["zorderLost(s=4,id=99)"],
    })
    assert len(reasons) == 3
    assert all(key in " ".join(reasons) for key in ZORDER_ZERO_KEYS)
    assert all(" exported=" not in r for r in reasons)


def test_zorder_schema_reasons_missing_or_empty_is_red():
    assert zorder_schema_reasons(None)
    assert zorder_schema_reasons({})
    assert zorder_schema_reasons({"slides": [40], "zorderGui": []})
    complete = _zorder_write(slides=[40])
    assert set(complete) >= set(ZORDER_SCHEMA_KEYS)
    assert zorder_schema_reasons(complete) == []
    no_count = dict(complete)
    del no_count["zorderSlides"]
    assert zorder_schema_reasons(no_count)


def test_expected_zorder_sets_splits_eligible_reuse_and_refused():
    raise_slides = {40, 55, 123, 99}
    patched, gui = expected_zorder_sets(
        raise_slides, compared_slides=[40, 55, 99], refused=[99],
    )
    assert patched == {40, 55}
    assert gui == {123, 99}


def test_zorder_write_reasons_missing_schema_is_red():
    reasons = zorder_write_reasons(
        None, {40, 55}, compared_slides=[40, 55],
    )
    assert reasons
    assert "missing" in reasons[0]
    assert zorder_write_reasons(
        {}, {40}, compared_slides=[40],
    )


def test_zorder_write_reasons_green_when_sets_match():
    assert zorder_write_reasons(
        _zorder_write(slides=[40, 55], zorderGui=[123]),
        {40, 55, 123},
        compared_slides=[40, 55],
    ) == []


def test_zorder_write_reasons_red_when_eligible_left_on_gui():
    # B never patched; suffixes can still match if the GUI raise ran.
    # expected_gui is empty (both slides are compared/eligible), so the RED is slides.
    reasons = zorder_write_reasons(
        _zorder_write(slides=[], zorderGui=[]),
        {40, 55},
        compared_slides=[40, 55],
    )
    assert any("slides=[] != eligible raise slides [40, 55]" in r for r in reasons)


def test_zorder_write_reasons_red_when_gui_omits_reuse():
    reasons = zorder_write_reasons(
        _zorder_write(slides=[40, 55], zorderGui=[]),
        {40, 55, 123},
        compared_slides=[40, 55],
    )
    assert any("zorderGui=[] != ineligible raise slides [123]" in r for r in reasons)


def test_zorder_write_reasons_red_when_eligible_listed_as_gui():
    reasons = zorder_write_reasons(
        _zorder_write(slides=[], zorderGui=[40, 55]),
        {40, 55},
        compared_slides=[40, 55],
    )
    assert any("slides=[] != eligible raise slides [40, 55]" in r for r in reasons)
    assert any("zorderGui=[40, 55] != ineligible raise slides []" in r for r in reasons)


def test_zorder_write_reasons_red_on_count_not_list():
    reasons = zorder_write_reasons(
        _zorder_write(slides=2, zorderGui=0),
        {40, 55},
        compared_slides=[40, 55],
    )
    assert any("not a slide list" in r and "slides=" in r for r in reasons)
    assert any("not a slide list" in r and "zorderGui=" in r for r in reasons)


def test_zorder_write_reasons_red_on_tuple_set_or_empty_string():
    for slides, gui in (
        ((40, 55), ()),
        ({40, 55}, set()),
        (frozenset({40}), frozenset()),
        ("", ""),
    ):
        reasons = zorder_write_reasons(
            _zorder_write(slides=slides, zorderGui=gui),
            {40, 55} if slides != "" else set(),
            compared_slides=[40, 55] if slides != "" else [],
        )
        assert any("not a slide list" in r and "slides=" in r for r in reasons)
        assert any("not a slide list" in r and "zorderGui=" in r for r in reasons)


def test_claimed_patched_slides_count_is_empty_not_crash():
    assert claimed_patched_slides({"slides": 2}) == set()
    assert claimed_patched_slides({"slides": 0}) == set()
    assert claimed_patched_slides({"slides": [40, 55]}) == {40, 55}
    assert claimed_patched_slides({"slides": []}) == set()
    assert claimed_patched_slides(None) == set()


def test_malformed_slides_count_does_not_crash_orchestration():
    # main() used to TypeError on `{int(s) for s in 2}` before zorder_write_reasons.
    zw = _zorder_write(slides=2, zorderGui=0)
    suppressed = claimed_patched_slides(zw)
    reasons = zorder_write_reasons(zw, {40, 55}, compared_slides=[40, 55])
    assert suppressed == set()
    assert any("not a slide list" in r for r in reasons)
    assert expect_gui_raises(
        [{"slide": 40, "childSig": "n=1"}], [{"slide": 55}], zw,
    ) is True
    assert suppressed_raise_reasons(
        {"tokens": {"raiseDead": ["s=40,idx=1"]}}, suppressed,
    ) == []


def test_zorder_write_reasons_refused_belongs_on_gui():
    assert zorder_write_reasons(
        _zorder_write(slides=[40], zorderGui=[99]),
        {40, 99},
        compared_slides=[40, 99],
        refused=[99],
    ) == []


def test_zorder_counter_summary_surfaces_piece3_names():
    line = zorder_counter_summary({"zorderSlides": 2, "zorderGui": 1})
    assert line.startswith("Stat zorder detail:")
    for key in ZORDER_SURFACE_KEYS:
        assert f"{key}=" in line
    assert " exported=" not in line


def test_suppressed_raise_reasons_from_tokens_and_front_err():
    result = {
        "tokens": {"raiseDead": ["s=40,idx=1"], "raiseUnknown": ["s=55,idx=2"]},
        "frontErr": "[-1719@raise,s=56,idx=1]",
        "raw": "frontErr=[-1719@raise,s=56,idx=1] exported=false",
    }
    reasons = suppressed_raise_reasons(result, {40, 55, 56})
    assert len(reasons) == 3
    assert any("raiseDead(s=40)" in r for r in reasons)
    assert any("raiseUnknown(s=55)" in r for r in reasons)
    assert any("frontErr s=56" in r for r in reasons)
    assert all(" exported=" not in r for r in reasons)


def test_suppressed_raise_reasons_ignores_non_suppressed_slides():
    result = {
        "tokens": {"raiseDead": ["s=40,idx=1"]},
        "frontErr": "[-1719@raise,s=99,idx=1]",
        "raw": "",
    }
    assert suppressed_raise_reasons(result, {55}) == []
    assert suppressed_raise_reasons(result, []) == []
    assert suppressed_raise_reasons(None, {40}) == []


def test_expect_gui_raises_false_when_every_raise_slide_is_suppressed():
    jobs = [{"slide": 40, "childSig": "n=1"}, {"slide": 55, "childSig": "n=2"}]
    badges = [{"slide": 56}]
    assert expect_gui_raises(jobs, badges, {"slides": [40, 55, 56]}) is False
    assert expect_gui_raises(jobs, badges, {"slides": [40]}) is True
    assert expect_gui_raises(jobs, badges, None) is True
    assert expect_gui_raises([], [], {"slides": [40]}) is False


def test_front_targets_stat_then_badge_order():
    # SOURCE/wall addressing. Stats append in ascending groupIndex (g1 then g2);
    # badges stay in row order (plate then pin), so pin is frontmost.
    id_by_addr = {("group", 0): "g1", ("group", 1): "g2", ("shape", 0): "plate", ("shape", 1): "pin"}
    targets = front_targets_for_slide(
        id_by_addr=id_by_addr,
        stat_jobs=[
            {"slide": 1, "groupIndex": 2, "childSig": "n=2"},  # g2, listed first
            {"slide": 1, "groupIndex": 1, "childSig": "n=1"},  # g1
        ],
        badge_rows=[
            {"slide": 1, "kind": "shape", "index": 1},
            {"slide": 1, "kind": "shape", "index": 2},
        ],
        hide_specs=[],
    )
    assert targets == ["g1", "g2", "plate", "pin"]


def test_front_targets_stat_uses_source_addr_after_group_hide():
    # groupIndex 1 is hide-bridged (saved ki 0) = wall group 1 after hiding wall 0.
    id_by_addr = {("group", 0): "deleted", ("group", 1): "kept"}
    targets = front_targets_for_slide(
        id_by_addr=id_by_addr,
        stat_jobs=[{"slide": 1, "groupIndex": 1, "childSig": "n=1"}],
        badge_rows=[],
        hide_specs=[{"slide": 1, "role": "hide", "kind": "group", "kindIndex": 0}],
    )
    assert targets == ["kept"]


def test_front_targets_badge_looks_up_wall_index_in_source():
    id_by_addr = {("shape", 0): "hidden", ("shape", 1): "kept"}
    targets = front_targets_for_slide(
        id_by_addr=id_by_addr,
        stat_jobs=[],
        badge_rows=[{"slide": 3, "kind": "shape", "index": 2}],
        hide_specs=[{"slide": 3, "role": "hide", "kind": "shape", "kindIndex": 0}],
    )
    assert targets == ["kept"]


def test_persisted_raise_jobs_legacy_neither_key():
    assert persisted_raise_jobs({"transforms": []}, {}) is None


def test_persisted_raise_jobs_refuses_one_key_only():
    with pytest.raises(ValueError, match="only one of"):
        persisted_raise_jobs({"transforms": []}, {"statJobs": [{"slide": 1}]})
    with pytest.raises(ValueError, match="only one of"):
        persisted_raise_jobs({"badgeRaises": []}, {})


def test_persisted_raise_jobs_refuses_split_plan_and_record():
    with pytest.raises(ValueError, match="only one of"):
        persisted_raise_jobs(
            {"statJobs": [{"slide": 1}]},
            {"badgeRaises": [{"slide": 2}]},
        )


def test_run_record_refuses_one_job_key():
    kwargs = dict(
        commit="c", deck_digest="dA", source_digest="dS",
        child_resize={"ok": True}, applied=1, missed=0,
        offline_write={"slides": [1]}, spec_id_map={},
    )
    with pytest.raises(ValueError, match="only one of"):
        run_record(
            **kwargs,
            plan={"transforms": [], "reuses": [], "statJobs": [{"slide": 1}]},
        )
    with pytest.raises(ValueError, match="only one of"):
        run_record(
            **kwargs,
            plan={"transforms": [], "reuses": [], "badgeRaises": [{"slide": 2}]},
        )


def test_persisted_raise_jobs_reads_both_from_record():
    assert persisted_raise_jobs(
        {"transforms": []},
        {"statJobs": [{"slide": 1}], "badgeRaises": [{"slide": 2}]},
    ) == ([{"slide": 1}], [{"slide": 2}])


def test_plan_parity_w2_both_arms_suppress_compared_set():
    plan = {"transforms": [{"slide": 1}], "reuses": [], "suppressGeometry": [5, 6]}
    assert plan_parity(plan, plan, compared_slides=[5, 6]) == []


def test_run_record_persists_zorder_write_and_job_lists():
    record = run_record(
        commit="c", deck_digest="dA", source_digest="dS",
        plan={"transforms": [], "reuses": [], "suppressGeometry": [1],
              "statJobs": [{"slide": 3, "childSig": "n=1"}],
              "badgeRaises": [{"slide": 8}]},
        child_resize={"ok": True}, applied=1, missed=0,
        offline_write={"slides": [1], "specs": {1: []}},
        spec_id_map={},
        zorder_write={"zorderSlides": 1, "slides": [3], "zorderRefused": 0},
        expect_raises=False,
    )
    assert record["zorderWrite"]["zorderSlides"] == 1
    assert record["statJobs"] == [{"slide": 3, "childSig": "n=1"}]
    assert record["badgeRaises"] == [{"slide": 8}]
    assert record["expectRaises"] is False
    assert "specs" not in record["offlineWrite"]
