"""Pure-logic tests for the nested-bulk-read probe (``scripts.probe_nested_bulk``).

Keynote-free: no ``osacompile``, no terminology resolution. Script builders are checked
by string content only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.probe_nested_bulk as m
from scripts.probe_nested_bulk import (
    KINDS,
    PROPS,
    build_all_reads_applescript,
    build_clone_prep_applescript,
    build_failure_probe_applescript,
    build_jxa_nested_read,
    build_open_close_applescript,
    clone_gw,
    compare_to_bulk,
    deck_allowed_for_live,
    evaluate_criteria,
    nested_to_bulk_shape,
    parse_nested,
    parse_prep_report,
    recommend,
    resolve_zero_char_premise,
    scoped_zero_char_confirmed,
    zero_char_text_item_count,
)

DECK = Path("/tmp/nested-bulk-probe/GW.key")


# ==========================================================================
# parse_nested / parse_prep_report
# ==========================================================================
def test_parse_nested_round_trip_three_levels():
    data = [[[1, 2], [3, 4]], [], [[5, 6]]]
    assert parse_nested(json.dumps(data)) == data


def test_parse_nested_raises_and_prints_on_bad_json(capsys):
    with pytest.raises(json.JSONDecodeError):
        parse_nested("not json")
    assert "parse_nested" in capsys.readouterr().out


def test_parse_prep_report():
    assert parse_prep_report("locked=2 emptyBoxes=1") == {"locked": 2, "emptyBoxes": 1}


def test_parse_prep_report_unparseable_raises():
    with pytest.raises(ValueError):
        parse_prep_report("garbage")


# ==========================================================================
# nested_to_bulk_shape — never substitutes, never raises; omits on shape error
# ==========================================================================
def test_nested_to_bulk_shape_keeps_skipped_slides_in_position():
    by_kind = {
        "text": {
            "position": [[[0, 0]], [], [[10, 10]], []],
            "width": [[100], [], [50], []],
            "height": [[20], [], [30], []],
        }
    }
    shaped, errors = nested_to_bulk_shape(by_kind, 4)
    assert list(shaped) == [0, 1, 2, 3]
    assert shaped[1]["text"] == []
    assert shaped[2]["text"] == [[10.0, 10.0, 50.0, 30.0]]
    assert errors == []


def test_nested_to_bulk_shape_empty_collection_is_empty_list():
    by_kind = {"movie": {"position": [[], []], "width": [[], []], "height": [[], []]}}
    shaped, errors = nested_to_bulk_shape(by_kind, 2)
    assert shaped[0]["movie"] == []
    assert shaped[1]["movie"] == []
    assert errors == []


def test_nested_to_bulk_shape_short_outer_list_is_a_shape_error_not_padded():
    by_kind = {
        "text": {
            "position": [[[0, 0]], [[1, 1]]],  # length 2, slide_count 3
            "width": [[10], [10]],
            "height": [[10], [10]],
        }
    }
    shaped, errors = nested_to_bulk_shape(by_kind, 3)
    outer = [e for e in errors if e["reason"] == "outer_length"]
    assert len(outer) == 3  # position, width, height all short
    assert outer[0]["len"] == 2 and outer[0]["slide_count"] == 3
    assert "text" not in shaped[2]  # never fabricated for the missing slide


def test_nested_to_bulk_shape_short_width_list_is_a_shape_error_not_a_value_row():
    by_kind = {
        "text": {
            "position": [[[0, 0], [1, 1]]],
            "width": [[10]],  # one entry short
            "height": [[10, 10]],
        }
    }
    shaped, errors = nested_to_bulk_shape(by_kind, 1)
    inner = [e for e in errors if e["reason"] == "inner_length"]
    assert len(inner) == 1
    assert inner[0] == {
        "kind": "text", "slide": 0, "reason": "inner_length",
        "position_len": 2, "width_len": 1, "height_len": 2,
    }
    assert "text" not in shaped[0]  # never zero-padded into a bogus row


def test_nested_to_bulk_shape_flattened_width_height_is_inner_shape_error_not_typeerror():
    # A totally flattened read: position/width/height are per-ITEM, not per-SLIDE — the
    # per-slide nesting collapsed. Must never raise TypeError from len(int).
    by_kind = {
        "text": {
            "position": [[100, 200], [110, 210]],
            "width": [10, 10],
            "height": [5, 5],
        }
    }
    shaped, errors = nested_to_bulk_shape(by_kind, 2)
    inner_shape = [e for e in errors if e["reason"] == "inner_shape"]
    assert len(inner_shape) == 2  # one per slide: width/height sublists aren't lists
    assert "text" not in shaped[0]
    assert "text" not in shaped[1]


def test_nested_to_bulk_shape_non_2_element_position_is_inner_shape_error():
    by_kind = {
        "text": {
            "position": [[[0, 0, 0]]],  # a 3-element entry, not [x, y]
            "width": [[10]],
            "height": [[10]],
        }
    }
    shaped, errors = nested_to_bulk_shape(by_kind, 1)
    inner_shape = [e for e in errors if e["reason"] == "inner_shape"]
    assert len(inner_shape) == 1
    assert inner_shape[0]["value"] == [0, 0, 0]
    assert "text" not in shaped[0]


def test_nested_to_bulk_shape_non_numeric_position_never_raises():
    by_kind = {
        "text": {
            "position": [[[None, "x"]]],
            "width": [[10]],
            "height": [[10]],
        }
    }
    shaped, errors = nested_to_bulk_shape(by_kind, 1)
    inner_shape = [e for e in errors if e["reason"] == "inner_shape"]
    assert len(inner_shape) == 1
    assert "text" not in shaped[0]


def test_nested_to_bulk_shape_scalar_outer_value_is_outer_shape_error_not_a_crash():
    # The same collapse class as the live char_counts crash, but on position/width/
    # height directly: a bare scalar instead of any list at all. len(int) must never run.
    by_kind = {"text": {"position": 63, "width": 63, "height": 63}}
    shaped, errors = nested_to_bulk_shape(by_kind, 2)
    outer_shape = [e for e in errors if e["reason"] == "outer_shape"]
    assert len(outer_shape) == 3
    assert {e["prop"] for e in outer_shape} == {"position", "width", "height"}
    assert outer_shape[0]["type"] == "int"
    assert "text" not in shaped[0] and "text" not in shaped[1]


# ==========================================================================
# compare_to_bulk — omission vs confirmed-empty, value/length mismatches
# ==========================================================================
def test_compare_to_bulk_flags_value_mismatch():
    shaped = {0: {"shape": [[1, 1, 1, 1]]}}
    bulk = {0: {"shape": [[2, 2, 2, 2]]}}
    result = compare_to_bulk(shaped, bulk)
    assert result["pass"] is False
    assert result["kind_mismatches"][0]["reason"] == "value"


def test_compare_to_bulk_flags_outer_length_mismatch():
    shaped = {0: {}}
    bulk = {0: {}, 1: {}}
    result = compare_to_bulk(shaped, bulk)
    assert result["outer_length_match"] is False
    assert result["slide_mismatches"] == [1]
    assert result["pass"] is False


def test_compare_to_bulk_allows_text_placeholder_tail():
    shaped = {0: {"text": [[0, 0, 1, 1], [1, 1, 1, 1], [2, 2, 1, 1]]}}
    bulk = {0: {"text": [[0, 0, 1, 1], [1, 1, 1, 1]]}}
    result = compare_to_bulk(shaped, bulk, text_slack=2)
    assert result["pass"] is True
    assert result["kind_mismatches"] == []


def test_compare_to_bulk_rejects_text_tail_beyond_slack():
    shaped = {0: {"text": [[0, 0, 1, 1]] * 5}}
    bulk = {0: {"text": [[0, 0, 1, 1]] * 2}}
    result = compare_to_bulk(shaped, bulk, text_slack=2)
    assert result["pass"] is False
    assert result["kind_mismatches"][0]["reason"] == "length"


def test_compare_to_bulk_non_text_length_mismatch_not_forgiven():
    shaped = {0: {"image": [[0, 0, 1, 1], [1, 1, 1, 1]]}}
    bulk = {0: {"image": [[0, 0, 1, 1]]}}
    result = compare_to_bulk(shaped, bulk)
    assert result["pass"] is False
    assert result["kind_mismatches"][0]["kind"] == "image"


def test_compare_to_bulk_distinguishes_omitted_from_confirmed_empty():
    # slide 0 movie: genuinely empty on both sides -> confirmed.
    # slide 1 movie: shaped never computed it (a shape error upstream) -> omitted.
    shaped = {0: {"movie": []}, 1: {}}
    bulk = {0: {"movie": []}, 1: {"movie": []}}
    result = compare_to_bulk(shaped, bulk)
    assert result["empty_confirmations"] == 1
    omitted = [m for m in result["kind_mismatches"] if m["reason"] == "omitted"]
    assert omitted == [{"slide": 1, "kind": "movie", "reason": "omitted"}]


# ==========================================================================
# zero_char_text_item_count / scoped_zero_char_confirmed / resolve_zero_char_premise
# ==========================================================================
def test_zero_char_text_item_count_counts_zero_entries():
    entry = {"raised": False, "value": [[0, 5, 0], [], [3]]}
    assert zero_char_text_item_count(entry) == (2, "confirmed by char_counts")


def test_zero_char_text_item_count_zero_found_has_its_own_reason():
    entry = {"raised": False, "value": [[5], [3]]}
    assert zero_char_text_item_count(entry) == (0, "no zero-character text item confirmed")


def test_zero_char_text_item_count_absent_vs_raised_have_different_reasons():
    count_absent, reason_absent = zero_char_text_item_count(None)
    count_raised, reason_raised = zero_char_text_item_count({"raised": True, "errNum": -1728})
    assert count_absent is None and count_raised is None
    assert reason_absent != reason_raised
    assert "absent" in reason_absent
    assert "raised" in reason_raised and "-1728" in reason_raised


def test_zero_char_text_item_count_guards_flat_non_nested_value():
    count, reason = zero_char_text_item_count({"raised": False, "value": [0, 5, 3]})
    assert count is None
    assert reason == "char_counts not nested per slide (got list)"


def test_zero_char_text_item_count_guards_scalar_value():
    # The live-run crash: Keynote 15.3.1 collapsed `count of characters of object text
    # of every text item of every slide` to ONE integer, not a nested (or even flat)
    # list. `for slide in value` on a bare int must never raise.
    count, reason = zero_char_text_item_count({"raised": False, "value": 63})
    assert count is None
    assert reason == "char_counts not nested per slide (got int)"

    count, reason = zero_char_text_item_count({"raised": False, "value": None})
    assert count is None
    assert "got NoneType" in reason

    count, reason = zero_char_text_item_count({"raised": False, "value": "oops"})
    assert count is None
    assert "got str" in reason


def test_scoped_zero_char_confirmed():
    assert scoped_zero_char_confirmed({"raised": False, "value": 0}) is True
    assert scoped_zero_char_confirmed({"raised": False, "value": 3}) is False
    assert scoped_zero_char_confirmed({"raised": True, "value": 0}) is False
    assert scoped_zero_char_confirmed(None) is False


def test_resolve_zero_char_premise_prefers_whole_deck_when_it_answers():
    count, reason = resolve_zero_char_premise(
        {"raised": False, "value": [[0]]}, {"raised": False, "value": 0}
    )
    assert count == 1
    assert reason == "confirmed by char_counts"


def test_resolve_zero_char_premise_scalar_whole_deck_value_falls_back_to_scoped():
    # The live-run crash scenario end-to-end: whole-deck char_counts collapsed to a bare
    # int, must not raise, and the scoped fallback still answers.
    count, reason = resolve_zero_char_premise(
        {"raised": False, "value": 63}, {"raised": False, "value": 0}
    )
    assert count == 1
    assert reason == "confirmed by char_counts_scoped"


def test_resolve_zero_char_premise_falls_back_to_scoped():
    count, reason = resolve_zero_char_premise(
        {"raised": True, "errNum": -1728}, {"raised": False, "value": 0}
    )
    assert count == 1
    assert reason == "confirmed by char_counts_scoped"


def test_resolve_zero_char_premise_neither_answers():
    count, reason = resolve_zero_char_premise(
        {"raised": True, "errNum": -1728}, {"raised": True, "errNum": -1728}
    )
    assert count == 0
    assert "raised" in reason


# ==========================================================================
# evaluate_criteria / recommend
# ==========================================================================
def _clean_compare() -> dict:
    return {
        "outer_length_match": True, "slide_mismatches": [], "kind_mismatches": [],
        "empty_confirmations": 1, "pass": True,
    }


def _evaluate(compare=None, timings=None, failure=None, slide_count=10, **kw):
    kw.setdefault("shape_errors", [])
    kw.setdefault("meta_slide_count", slide_count)
    kw.setdefault("bulk_text_counts", {})
    kw.setdefault("zero_char_items", 1)
    kw.setdefault("zero_char_reason", "confirmed by char_counts")
    return evaluate_criteria(
        compare if compare is not None else _clean_compare(),
        timings if timings is not None else {"bulk_seconds_warm": 60.0, "nested_seconds": 10.0},
        failure if failure is not None else {"primary": {"raised": True}},
        slide_count, **kw,
    )


def test_evaluate_criteria_all_green():
    criteria = _evaluate()
    assert all(c["pass"] for c in criteria.values())
    assert criteria["6"]["mode"] == "whole_event_raise"


def test_evaluate_criteria_one_fail():
    compare = _clean_compare()
    compare["kind_mismatches"] = [{"slide": 0, "kind": "shape", "reason": "value"}]
    criteria = _evaluate(compare=compare)
    assert criteria["1"]["pass"] is True
    assert criteria["2"]["pass"] is False


def test_evaluate_criteria_criterion1_fails_on_outer_length_shape_error():
    criteria = _evaluate(shape_errors=[
        {"kind": "text", "prop": "position", "reason": "outer_length", "len": 9, "slide_count": 10}
    ])
    assert criteria["1"]["pass"] is False


def test_evaluate_criteria_criterion1_fails_on_outer_shape_error():
    criteria = _evaluate(shape_errors=[
        {"kind": "text", "prop": "position", "reason": "outer_shape", "type": "int"}
    ])
    assert criteria["1"]["pass"] is False


def test_evaluate_criteria_criterion1_fails_on_meta_disagreement():
    criteria = _evaluate(meta_slide_count=9, slide_count=10)
    assert criteria["1"]["pass"] is False
    assert criteria["1"]["detail"]["meta_slide_count"] == 9


def test_evaluate_criteria_criterion2_fails_on_inner_shape_error():
    criteria = _evaluate(shape_errors=[
        {"kind": "text", "slide": 0, "reason": "inner_shape", "value": [0, 0, 0]}
    ])
    assert criteria["2"]["pass"] is False
    assert criteria["2"]["detail"]["inner_shape_errors"] == 1


def test_evaluate_criteria_criterion3_needs_a_confirmed_empty_and_no_omissions():
    compare = _clean_compare()
    compare["empty_confirmations"] = 0
    assert _evaluate(compare=compare)["3"]["pass"] is False

    compare = _clean_compare()
    compare["kind_mismatches"] = [{"slide": 0, "kind": "movie", "reason": "omitted"}]
    assert _evaluate(compare=compare)["3"]["pass"] is False


def test_evaluate_criteria_end_to_end_through_nested_to_bulk_shape_fails_criterion1():
    by_kind = {"text": {"position": [[[0, 0]]], "width": [[10]], "height": [[10]]}}
    shaped, shape_errors = nested_to_bulk_shape(by_kind, 2)  # outer list length 1, slide_count 2
    bulk = {0: {"text": [[0, 0, 10, 10]]}, 1: {"text": []}}
    compare = compare_to_bulk(shaped, bulk)
    criteria = evaluate_criteria(
        compare, {"bulk_seconds_warm": 60.0, "nested_seconds": 10.0}, {"primary": {"raised": True}}, 2,
        shape_errors=shape_errors, meta_slide_count=2, bulk_text_counts={0: 1, 1: 0},
        zero_char_items=1, zero_char_reason="confirmed by char_counts",
    )
    assert criteria["1"]["pass"] is False


def test_evaluate_criteria_failure_empty_dict_is_unknown_and_fails():
    criteria = _evaluate(failure={})
    assert criteria["6"]["mode"] == "unknown"
    assert criteria["6"]["pass"] is False


def test_evaluate_criteria_needs_zero_char_confirmation_or_unknown():
    criteria = _evaluate(zero_char_items=0, zero_char_reason="no zero-character text item confirmed")
    assert criteria["6"]["mode"] == "unknown"
    assert criteria["6"]["pass"] is False
    assert criteria["6"]["detail"]["reason"] == "no zero-character text item confirmed"


def test_evaluate_criteria_distinguishes_raised_char_counts_from_no_zero_found():
    raised = _evaluate(zero_char_items=0, zero_char_reason="char_counts probe raised (errNum=-1728)")
    absent_zero = _evaluate(zero_char_items=0, zero_char_reason="no zero-character text item confirmed")
    assert raised["6"]["mode"] == absent_zero["6"]["mode"] == "unknown"
    assert raised["6"]["detail"]["reason"] != absent_zero["6"]["detail"]["reason"]


def test_evaluate_criteria_raised_false_complete_value_is_substituted():
    failure = {"primary": {"raised": False, "value": [[3], [5, 2]]}}
    criteria = _evaluate(failure=failure, bulk_text_counts={0: 1, 1: 2})
    assert criteria["6"]["mode"] == "substituted_value"
    assert criteria["6"]["pass"] is True


def test_evaluate_criteria_raised_false_short_sublist_is_silent_partial():
    failure = {"primary": {"raised": False, "value": [[3], [5]]}}  # slide 1 bulk expects 2 items
    criteria = _evaluate(failure=failure, bulk_text_counts={0: 1, 1: 2})
    assert criteria["6"]["mode"] == "silent_partial"
    assert criteria["6"]["pass"] is False


def test_evaluate_criteria_scalar_primary_value_is_unknown_not_a_crash():
    # Same class of collapse as char_counts, but on the "primary" probe's own value.
    failure = {"primary": {"raised": False, "value": 63}}
    criteria = _evaluate(failure=failure, bulk_text_counts={0: 1, 1: 2})
    assert criteria["6"]["mode"] == "unknown"
    assert "not nested per slide" in criteria["6"]["detail"]["reason"]


def test_recommend_implement_nested_on_whole_event_raise():
    criteria = {
        "1": {"pass": True}, "2": {"pass": True}, "3": {"pass": True}, "4": {"pass": True},
        "5": {"pass": True}, "6": {"mode": "whole_event_raise"},
    }
    assert recommend(criteria) == "implement nested (whole_event_raise)"


def test_recommend_implement_nested_on_substituted_value():
    criteria = {
        "1": {"pass": True}, "2": {"pass": True}, "3": {"pass": True}, "4": {"pass": True},
        "5": {"pass": True}, "6": {"mode": "substituted_value"},
    }
    assert recommend(criteria) == "implement nested (substituted_value)"


def test_recommend_silent_partial_falls_back():
    criteria = {
        "1": {"pass": True}, "2": {"pass": True}, "3": {"pass": True}, "4": {"pass": True},
        "5": {"pass": True}, "6": {"mode": "silent_partial"},
    }
    assert recommend(criteria) == "r-bulk-counts-plan"


def test_recommend_unknown_falls_back():
    criteria = {
        "1": {"pass": True}, "2": {"pass": True}, "3": {"pass": True}, "4": {"pass": True},
        "5": {"pass": True}, "6": {"mode": "unknown"},
    }
    assert recommend(criteria) == "r-bulk-counts-plan"


def test_recommend_core_fail_falls_back():
    criteria = {
        "1": {"pass": False}, "2": {"pass": True}, "3": {"pass": True}, "4": {"pass": True},
        "5": {"pass": True}, "6": {"mode": "whole_event_raise"},
    }
    assert recommend(criteria) == "r-bulk-counts-plan"


def test_recommend_slow_nested_falls_back_even_on_whole_event_raise():
    criteria = {
        "1": {"pass": True}, "2": {"pass": True}, "3": {"pass": True}, "4": {"pass": True},
        "5": {"pass": False}, "6": {"mode": "whole_event_raise"},
    }
    assert recommend(criteria) == "r-bulk-counts-plan"


def test_recommend_slow_nested_falls_back_even_on_substituted_value():
    criteria = {
        "1": {"pass": True}, "2": {"pass": True}, "3": {"pass": True}, "4": {"pass": True},
        "5": {"pass": False}, "6": {"mode": "substituted_value"},
    }
    assert recommend(criteria) == "r-bulk-counts-plan"


# ==========================================================================
# AppleScript / JXA builders
# ==========================================================================
def test_build_all_reads_applescript_has_timeout_and_one_every_of_every_per_read():
    script = build_all_reads_applescript(DECK)
    assert "with timeout of 3600 seconds" in script
    for as_kind, _py_kind in KINDS:
        for prop in PROPS:
            needle = f"{prop} of every {as_kind} of every slide of theDoc"
            assert script.count(needle) == 1


def test_build_all_reads_applescript_binds_document_by_name():
    script = build_all_reads_applescript(DECK)
    assert 'close (every document whose name is "GW.key" or name is "GW") saving no' in script
    assert 'if name of theDoc does not start with "GW"' in script


def test_build_all_reads_applescript_close_is_try_wrapped():
    script = build_all_reads_applescript(DECK)
    assert "  try\n    close theDoc saving no\n  end try" in script


def test_build_open_close_applescript_has_no_reads():
    script = build_open_close_applescript(DECK)
    assert "of every slide" not in script
    assert "  try\n    close theDoc saving no\n  end try" in script


def test_build_failure_probe_applescript_wraps_each_probe_in_try():
    script = build_failure_probe_applescript(DECK, empty_text_slide=6)
    assert script.count("on error errMsg number errNum") == 5
    assert "count of characters of object text of every text item of every slide" in script
    assert "count of characters of object text of text item 1 of slide 6 of theDoc" in script
    assert "character 1 of object text of every text item of every slide" in script
    assert "file name of every image of every slide" in script
    assert "object text of every movie of every slide" in script
    assert 'if name of theDoc does not start with "GW"' in script
    assert "  try\n    close theDoc saving no\n  end try" in script


def test_build_failure_probe_char_counts_probe_runs_before_primary():
    script = build_failure_probe_applescript(DECK, empty_text_slide=6)
    assert (script.index("count of characters of object text of every text item")
            < script.index("count of characters of object text of text item 1")
            < script.index("size of character 1 of object text"))


def test_build_failure_probe_scoped_uses_the_given_empty_text_slide():
    script = build_failure_probe_applescript(DECK, empty_text_slide=42)
    assert "of text item 1 of slide 42 of theDoc" in script


def test_obed_escape_order_backslash_then_quote_then_crlf_then_cr_then_lf_then_tab():
    lines = m._OBED_ESCAPE_LINES

    def idx(needle):
        return next(i for i, ln in enumerate(lines) if needle in ln)

    backslash = idx('obedReplace(t, "\\\\"')
    quote = idx('obedReplace(t, "\\""')
    crlf = idx("(return & linefeed)")
    cr_alone = idx("obedReplace(t, return,")
    lf_alone = idx("obedReplace(t, linefeed,")
    tab = idx("obedReplace(t, tab,")

    assert backslash < quote < crlf < cr_alone < lf_alone
    assert tab > backslash


def test_obed_escape_cr_alone_maps_to_backslash_r_not_backslash_n():
    lines = m._OBED_ESCAPE_LINES
    cr_line = next(ln for ln in lines if ln.strip().startswith('set t to my obedReplace(t, return,')
                   and "linefeed" not in ln)
    assert '"\\\\r"' in cr_line
    assert '"\\\\n"' not in cr_line


def test_obed_escape_crlf_pass_maps_to_backslash_r_backslash_n():
    lines = m._OBED_ESCAPE_LINES
    crlf_line = next(ln for ln in lines if "(return & linefeed)" in ln)
    assert '"\\\\r\\\\n"' in crlf_line


def test_build_clone_prep_applescript_locks_and_adds_one_empty_text_box():
    script = build_clone_prep_applescript(DECK, lock_image_slide=2, lock_text_slide=6, empty_text_slide=6)
    assert "set locked of image 1 of slide 2 of theDoc to true" in script
    assert "set locked of text item 1 of slide 6 of theDoc to true" in script
    assert script.count("make new text item") == 1
    assert "tell slide 6 of theDoc to make new text item" in script
    assert 'return "locked=" & lockedCount & " emptyBoxes=" & emptyBoxCount' in script


def test_build_clone_prep_applescript_guards_each_lock_in_its_own_try():
    script = build_clone_prep_applescript(DECK, lock_image_slide=2, lock_text_slide=6, empty_text_slide=6)
    assert script.count("set lockedCount to lockedCount + 1") == 2
    assert ("  try\n    set locked of image 1 of slide 2 of theDoc to true\n"
            "    set lockedCount to lockedCount + 1\n  end try") in script
    assert ("  try\n    set locked of text item 1 of slide 6 of theDoc to true\n"
            "    set lockedCount to lockedCount + 1\n  end try") in script


def test_build_clone_prep_applescript_targets_only_the_clone_path():
    clone = Path("/Users/x/repo/output/nested-bulk-probe/GW.key")
    script = build_clone_prep_applescript(clone, lock_image_slide=2, lock_text_slide=6, empty_text_slide=6)
    assert script.count('POSIX file "') == 1
    assert str(clone) in script


def test_build_jxa_nested_read_uses_bulk_specifiers_and_json_dumps_path():
    script = build_jxa_nested_read(DECK)
    for name in ("textItems", "images", "movies", "groups"):
        for prop in PROPS:
            assert f"doc.slides.{name}.{prop}()" in script
    assert json.dumps(str(DECK.resolve())) in script


# ==========================================================================
# clone_gw / deck_allowed_for_live
# ==========================================================================
def test_clone_gw_refuses_existing(tmp_path, monkeypatch):
    source = tmp_path / "src.key"
    source.write_bytes(b"x")
    dest = tmp_path / "dest.key"
    dest.write_bytes(b"y")
    calls = []
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **k: calls.append((a, k)))

    with pytest.raises(FileExistsError):
        clone_gw(source, dest)
    assert calls == []


def test_clone_gw_invokes_cp_c(tmp_path, monkeypatch):
    source = tmp_path / "src.key"
    source.write_bytes(b"x")
    dest = tmp_path / "out" / "dest.key"
    calls = []
    monkeypatch.setattr(m.subprocess, "run", lambda cmd, check: calls.append(cmd))

    result = clone_gw(source, dest)

    assert result == dest
    assert calls == [["cp", "-c", str(source), str(dest)]]
    assert dest.parent.is_dir()


def test_deck_allowed_for_live_under_out(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    deck = out / "GW.key"
    assert deck_allowed_for_live(deck, out, allow_external=False) is True


def test_deck_allowed_for_live_external_refused_unless_override(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    deck = tmp_path / "elsewhere" / "Map.key"
    assert deck_allowed_for_live(deck, out, allow_external=False) is False
    assert deck_allowed_for_live(deck, out, allow_external=True) is True


# ==========================================================================
# main — argparse-level refusal, no Keynote touched
# ==========================================================================
def test_main_rejects_empty_text_slide_one(tmp_path, capsys):
    with pytest.raises(SystemExit):
        m.main(["--deck", str(tmp_path / "x.key"), "--empty-text-slide", "1"])
    assert "must not be 1" in capsys.readouterr().err


def test_main_rejects_lock_text_slide_one(tmp_path, capsys):
    with pytest.raises(SystemExit):
        m.main(["--deck", str(tmp_path / "x.key"), "--lock-text-slide", "1"])
    assert "must not be 1" in capsys.readouterr().err


def test_main_refuses_live_on_external_deck_without_touching_keynote(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("Keynote must not be touched")

    monkeypatch.setattr(m, "_run_osascript", boom)
    monkeypatch.setattr(m, "_run_jxa", boom)
    monkeypatch.setattr(m, "clone_gw", boom)

    out = tmp_path / "out"
    deck = tmp_path / "elsewhere" / "Map.key"
    deck.parent.mkdir(parents=True)
    deck.write_bytes(b"x")

    rc = m.main(["--deck", str(deck), "--out", str(out), "--live"])

    assert rc == 3


def test_main_prep_aborts_when_locked_or_empty_box_missing(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("Keynote must not be touched")

    monkeypatch.setattr(m, "_run_jxa", boom)
    source = tmp_path / "src.key"
    source.write_bytes(b"x")
    out = tmp_path / "out"

    monkeypatch.setattr(m, "clone_gw", lambda _src, dst: dst)
    monkeypatch.setattr(m, "_run_osascript", lambda _script: "locked=2 emptyBoxes=0")

    rc = m.main(["--deck", str(source), "--out", str(out), "--prep"])

    assert rc == 4


def test_main_findings_filename_carries_the_deck_stem(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("clone_gw/jxa must not run: no --prep, no --with-jxa")

    monkeypatch.setattr(m, "_run_jxa", boom)
    monkeypatch.setattr(m, "clone_gw", boom)

    out = tmp_path / "out"
    out.mkdir()
    deck = out / "GW.key"
    deck.write_bytes(b"x")

    bulk = {0: {"text": [], "image": [], "movie": [], "group": []},
            1: {"text": [], "image": [], "movie": [], "group": []}}

    def fake_run_osascript(script):
        if "make new text item" in script:
            raise AssertionError("prep script should not run without --prep")
        if "count of characters" in script:
            entries = [
                {"name": "char_counts", "raised": False, "value": [[], []]},
                {"name": "char_counts_scoped", "raised": False, "value": 0},
                {"name": "primary", "raised": True, "errNum": -1728, "errMsg": "boom"},
                {"name": "images_filename", "raised": False, "value": [[], []]},
                {"name": "movies_objecttext", "raised": False, "value": [[], []]},
            ]
            return json.dumps(entries)
        if "slideCount" in script:
            entries = [{"kind": "_meta", "prop": "slideCount", "seconds": 0, "value": 2}]
            for as_kind, py_kind in KINDS:
                for prop in PROPS:
                    entries.append({"kind": py_kind, "prop": prop, "seconds": 0, "value": [[], []]})
            return json.dumps(entries)
        return "ok"

    monkeypatch.setattr(m, "_run_osascript", fake_run_osascript)

    import obed_edom.inspect as inspect_mod
    monkeypatch.setattr(inspect_mod, "bulk_geometry", lambda _deck: bulk)

    rc = m.main(["--deck", str(deck), "--out", str(out), "--live"])

    assert rc == 0
    findings_path = out / "findings-GW.json"
    assert findings_path.is_file()
    data = json.loads(findings_path.read_text())
    assert "criteria" in data


def test_main_writes_raw_sidecars_before_parsing(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("clone_gw/jxa must not run: no --prep, no --with-jxa")

    monkeypatch.setattr(m, "_run_jxa", boom)
    monkeypatch.setattr(m, "clone_gw", boom)

    out = tmp_path / "out"
    out.mkdir()
    deck = out / "GW.key"
    deck.write_bytes(b"x")

    bulk = {0: {"text": [], "image": [], "movie": [], "group": []}}

    def fake_run_osascript(script):
        if "slideCount" in script:
            return "NOT VALID JSON"  # mimics a Keynote-side collapse/garble
        return "ok"

    monkeypatch.setattr(m, "_run_osascript", fake_run_osascript)

    import obed_edom.inspect as inspect_mod
    monkeypatch.setattr(inspect_mod, "bulk_geometry", lambda _deck: bulk)

    with pytest.raises(json.JSONDecodeError):
        m.main(["--deck", str(deck), "--out", str(out), "--live"])

    # The sidecars exist and hold the raw text — even though parsing it afterward blew up.
    nested_sidecar = out / "nested-raw-GW.json"
    openclose_sidecar = out / "openclose-raw-GW.txt"
    failure_sidecar = out / "failure-raw-GW.json"
    assert nested_sidecar.is_file()
    assert nested_sidecar.read_text() == "NOT VALID JSON"
    assert openclose_sidecar.is_file()
    assert failure_sidecar.is_file()


def test_main_analysis_exception_still_writes_findings_with_error(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("clone_gw/jxa must not run: no --prep, no --with-jxa")

    monkeypatch.setattr(m, "_run_jxa", boom)
    monkeypatch.setattr(m, "clone_gw", boom)

    out = tmp_path / "out"
    out.mkdir()
    deck = out / "GW.key"
    deck.write_bytes(b"x")

    bulk = {0: {"text": [], "image": [], "movie": [], "group": []}}

    def fake_run_osascript(script):
        if "slideCount" in script:
            return "NOT VALID JSON"
        return "ok"

    monkeypatch.setattr(m, "_run_osascript", fake_run_osascript)

    import obed_edom.inspect as inspect_mod
    monkeypatch.setattr(inspect_mod, "bulk_geometry", lambda _deck: bulk)

    with pytest.raises(json.JSONDecodeError):
        m.main(["--deck", str(deck), "--out", str(out), "--live"])

    findings_path = out / "findings-GW.json"
    assert findings_path.is_file()
    data = json.loads(findings_path.read_text())
    assert "error" in data
    assert "JSONDecodeError" in data["error"]
    assert data["timings"]["nested_seconds"] >= 0
    assert data["timings"]["per_read"] == {}  # crashed before any read entry was parsed
    assert len(data["raw_sidecars"]) == 3
    assert all(Path(p).is_file() for p in data["raw_sidecars"])
