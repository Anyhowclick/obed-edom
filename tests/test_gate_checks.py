from __future__ import annotations

import copy
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import gate_checks as checks  # noqa: E402
from continuity_core_variants import variant_sha  # noqa: E402
from obed_edom.live_continuity_js import js_sha256  # noqa: E402
from obed_edom.p2_verdict import build_continuity_plan  # noqa: E402


HOST = checks.live_run_validity.HOST_HEADLESS_CHROME
VALID = {"ok": True, "reasons": [], "policy": {"hostKind": HOST}}
TARGET_ID, TARGET_SCENE = checks.ALPHA_ORDINAL_TARGET
OTHER_ID = "b6to7:vid-20250608-wa0125.mp4#1->vid-20250608-wa0125.mp4#1:carry"
RETIRE_ID = "b8to9:vid-20250608-wa0125.mp4#1->end:retire"
DEPART_ID = "b9to10:vid-20250608-wa0125.mp4#1->end:departure"


def under(**overrides):
    value = {
        "verdict": True, "mode": "continuous",
        "feedLive": {"verdict": True, "checks": [
            {"progress": 0.25, "ok": True}, {"progress": 0.5, "ok": False}, {"progress": 0.75, "ok": False},
        ]},
        "holdFrame": {"verdict": None, "notApplicable": True},
        "noRiderAboveCanvas": {"verdict": True},
        "labelsOverFeed": {"verdict": True},
        "artworkAbove": {"verdict": True},
        "handbackContinuity": {"verdict": True},
    }
    value.update(overrides)
    return value


def feed_record() -> dict:
    specs = [
        {"id": TARGET_ID, "kind": "carry", "expect": True, "action": "bridge", "alias": None,
         "atScene": TARGET_SCENE, "underArtwork": True, "feed": {"to": {"upload": 5}}},
        {"id": OTHER_ID, "kind": "carry", "expect": True, "action": "bridge", "alias": None,
         "atScene": 12, "underArtwork": True, "feed": {"to": {"upload": 6}}},
        {"id": RETIRE_ID, "kind": "retire", "expect": True, "action": "retire", "alias": None,
         "atScene": 16},
        {"id": DEPART_ID, "kind": "departure", "expect": True, "action": "depart", "alias": None,
         "atScene": 18},
    ]
    verdicts = {spec["id"]: {"verdict": True} for spec in specs}
    arm = {
        "verdicts": verdicts,
        TARGET_ID: {"verdict": True, "underArtwork": under()},
        OTHER_ID: {"verdict": True, "underArtwork": under()},
        RETIRE_ID: {"verdict": True},
        DEPART_ID: {"verdict": True},
    }
    return {
        "status": "pass", "runValidity": copy.deepcopy(VALID),
        "groundTruth": {"planSha256": checks.ALPHA_DSK_PLAN_SHA256, "verdicts": specs},
        "arms": {"A": arm},
    }


def host_red_record() -> dict:
    arm = "core:no-pin-hold"
    red = list(checks.RED_ARM_EXPECTATIONS[(checks.DECK_PLAN_SHA256["D2"], arm, "off")])
    return {
        "runValidity": copy.deepcopy(VALID),
        "groundTruth": {
            "planSha256": checks.DECK_PLAN_SHA256["D2"],
            "verdicts": [{"id": red[0], "kind": "carry"}],
        },
        "glReplay": {"requested": "off"}, "status": "pass", "redArm": arm,
        "expectedRedSet": red, "redSet": red, "unknown": [],
        "expectedCoreSha256": variant_sha("no-pin-hold"), "paintFloor": 60,
        "arm": {
            "sampler": {"schema": 2, "selfCheck": {"ok": True}},
            "census": {"1": {"unexpectedVideos": [], "duplicateVideos": []}},
            red[0]: {"paint": {"longestRun": 108}},
        },
    }


def test_feed_null_matches_complete_exact_inventory_and_frozen_reads() -> None:
    record = feed_record()
    result = checks.judge(record, "check_mm_feed", "feed-on-1920", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=0)

    assert result.verdict is checks.Verdict.MATCH
    assert result.exit_code == 0 and result.status == "pass"
    assert result.lines == ("[MM-FEED Alpha_DSK feed-on-1920] exit=0 records=2 status=pass",)
    assert checks.MM_FEED_READ_EXPECTATIONS[("Alpha_DSK", "first-crossfade")] == {0.5: False, 0.75: False}


@pytest.mark.parametrize(
    ("mutate", "problem"),
    [
        pytest.param(lambda record: record["arms"]["A"][TARGET_ID]["underArtwork"].pop("holdFrame"),
                     f"{TARGET_ID}.holdFrame missing or malformed", id="absent-hold"),
        pytest.param(lambda record: record["arms"]["A"]["verdicts"].pop(RETIRE_ID),
                     f"missing verdict ids ['{RETIRE_ID}']", id="absent-retirement"),
        pytest.param(lambda record: record["arms"]["A"]["verdicts"].pop(DEPART_ID),
                     f"missing verdict ids ['{DEPART_ID}']", id="absent-departure"),
        pytest.param(lambda record: record["groundTruth"]["verdicts"].append(copy.deepcopy(record["groundTruth"]["verdicts"][0])),
                     f"duplicate spec ids ['{TARGET_ID}']", id="duplicate-id"),
        pytest.param(lambda record: record["arms"]["A"]["verdicts"].__setitem__(TARGET_ID + ":suffix", {"verdict": True}),
                     f"extra verdict ids ['{TARGET_ID}:suffix']", id="substring-collision"),
    ],
)
def test_feed_inventory_mutants_fail_closed(mutate, problem: str) -> None:
    record = feed_record()
    mutate(record)

    result = checks.judge(record, "check_mm_feed", "feed-on-1920", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=0)

    assert result.verdict is checks.Verdict.MISMATCH
    assert any(problem in line for line in result.lines)


def test_alpha_controls_are_scoped_by_exact_id_and_scene_and_na_is_exempt() -> None:
    ordinal = feed_record()
    target = ordinal["arms"]["A"][TARGET_ID]["underArtwork"]
    target.update(
        feedLive={"verdict": False}, holdFrame={"verdict": False}, posterHold={"verdict": True}, verdict=False,
    )
    result = checks.judge(ordinal, "check_mm_feed", "ordinal", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=1)
    assert result.verdict is checks.Verdict.MATCH

    all_rows_mutant = copy.deepcopy(ordinal)
    all_rows_mutant["arms"]["A"][OTHER_ID]["underArtwork"]["feedLive"] = {"verdict": False}
    assert checks.judge(
        all_rows_mutant, "check_mm_feed", "ordinal", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=1,
    ).verdict is checks.Verdict.MISMATCH

    after_feed = feed_record()
    after_feed["arms"]["A"][TARGET_ID]["underArtwork"].update(
        feedLive={"verdict": False}, holdFrame={"verdict": True}, posterHold={"verdict": True}, verdict=False,
    )
    assert checks.judge(
        after_feed, "check_mm_feed", "after-feed", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=1,
    ).verdict is checks.Verdict.MATCH
    after_feed["arms"]["A"][OTHER_ID]["underArtwork"]["holdFrame"] = {"verdict": True}
    assert checks.judge(
        after_feed, "check_mm_feed", "after-feed", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=1,
    ).verdict is checks.Verdict.MISMATCH

    missing_target = feed_record()
    missing_target["groundTruth"]["verdicts"] = [
        spec for spec in missing_target["groundTruth"]["verdicts"] if spec["id"] != TARGET_ID
    ]
    missing_target["arms"]["A"]["verdicts"].pop(TARGET_ID)
    missing_target["arms"]["A"].pop(TARGET_ID)
    result = checks.judge(
        missing_target, "check_mm_feed", "ordinal", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=1,
    )
    assert result.verdict is checks.Verdict.MISMATCH
    assert f"target carry '{TARGET_ID}' atScene {TARGET_SCENE} is missing" in "\n".join(result.lines)

    opacity = feed_record()
    opacity["arms"]["A"][TARGET_ID]["underArtwork"]["labelsOverFeed"] = {
        "verdict": True, "notApplicable": True,
    }
    opacity["arms"]["A"][OTHER_ID]["underArtwork"]["labelsOverFeed"] = {"verdict": False}
    result = checks.judge(
        opacity, "check_mm_feed", "mm-opacity-off", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=1,
    )
    assert result.verdict is checks.Verdict.MATCH
    assert f"    N/A: {TARGET_ID}.labelsOverFeed explicitly notApplicable" in result.lines


def test_invalid_expected_red_precedes_a_matching_registration() -> None:
    record = host_red_record()
    record["runValidity"] = {
        "ok": False, "reasons": ["cost: hook p95 exceeds 8 ms"], "policy": {"hostKind": HOST},
    }

    result = checks.judge(
        record, "check_host_red", "core:no-pin-hold", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=0,
    )

    assert result.verdict is checks.Verdict.INVALID
    assert result.exit_code == 1 and result.lines[-1] == "    INVALID: cost: hook p95 exceeds 8 ms"


@pytest.mark.parametrize(
    ("mutate", "problem"),
    [
        pytest.param(lambda record: record.__setitem__("paintFloor", 109),
                     "longest unpainted run 108 below the 109-frame floor", id="wrong-paint-floor"),
        pytest.param(lambda record: None, "exit=1", id="nonmatching-rc"),
    ],
)
def test_host_red_mutants_do_not_match(mutate, problem: str) -> None:
    record = host_red_record()
    mutate(record)
    rc = 1 if problem == "exit=1" else 0

    result = checks.judge(
        record, "check_host_red", "core:no-pin-hold", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=rc,
    )

    assert result.verdict is checks.Verdict.MISMATCH
    assert problem in "\n".join(result.lines)


def test_report_rows_are_observations_not_acceptance() -> None:
    assert checks.MM_FEED_REPORT_ROWS == ("entryColdStart",)
    record = feed_record()
    record["arms"]["A"]["entryColdStart"] = {
        "10": {"asset": "counter-a.mov", "scene": 4, "visibleUndecodedDurationMs": 16.6},
    }

    result = checks.judge(record, "check_mm_feed", "feed-on-1920", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=0)

    assert result.verdict is checks.Verdict.MATCH
    assert result.exit_code == 0 and result.status == "pass"
    assert result.lines[-1] == "    REPORT: asset=counter-a.mov scene=4 visibleUndecodedDurationMs=16.6"


def test_plan_registry_uses_ground_truth_sha_not_a_caller_deck_label() -> None:
    record = feed_record()

    result = checks.judge(record, "check_mm_feed", "feed-on-1920", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=0)

    assert result.lines[0].startswith("[MM-FEED Alpha_DSK ")
    assert "D7" not in result.lines[0]


def test_registry_rejects_an_unregistered_host_kind() -> None:
    result = checks.judge(feed_record(), "check_mm_feed", "feed-on-1920", "caller label", rc=0)

    assert result.verdict is checks.Verdict.MISMATCH
    assert result.lines == ("check_mm_feed: unregistered host kind 'caller label'",)


def passg_red_record() -> dict:
    arm = "core:no-pin-hold"
    carry = "b2to3:counter-a.mov#1->counter-a.mov#1:carry"
    red = list(checks.PASSG_RED_EXPECTATIONS[(checks.DECK_PLAN_SHA256["D1"], arm)])
    sha = variant_sha("no-pin-hold")
    return {
        "runValidity": copy.deepcopy(VALID),
        "groundTruth": {"planSha256": checks.DECK_PLAN_SHA256["D1"]},
        "kind": "live-continuity-probe-pass-g", "pass": "G", "status": "pass", "redArm": arm,
        "expectedCoreSha256": sha, "expectedRedSet": list(red), "redSet": list(red), "unknown": [], "paintFloor": 60,
        "armed": {
            "continuity": {"sha256": sha},
            "destinations": [{
                "fromOrdinal": 1, "toOrdinal": 3, "advanceTo": 4,
                "advanceCarry": {"verdicts": {carry: {"paint": {"longestRun": 108}}}},
            }],
        },
        "nullControl": {"continuity": {"sha256": sha}, "destinations": []},
    }


def paint_control_record(spec: str = "6:ancestor-opacity:pin@2") -> dict:
    count = int(spec.split(":", 1)[0])
    hidden = list(range(300, 300 + count))
    target = "b0to1:counter-a.mov#1->counter-a.mov#1:carry"
    paint = {
        "status": "fail", "frames": 120, "unpaintedFrames": count, "partialFrames": 0,
        "doubleFrames": 0, "substituteFrames": 0, "longestRun": count,
        "unpaintedSeqs": hidden, "partialSeqs": [], "coverage": {"ok": True},
        "unobserved": [], "unreadable": [],
    }
    return {
        "runValidity": copy.deepcopy(VALID),
        "groundTruth": {"planSha256": checks.DECK_PLAN_SHA256["D5"]},
        "kind": "live-continuity-probe-paint-control", "status": "pass", "statusReasons": [],
        "control": spec, "expectedCoreSha256": js_sha256(), "targetVerdictId": target,
        "controlRecord": {
            "control": {"n": count, "variant": "ancestor-opacity", "phase": "pin", "timing": "early",
                        "atScene": 2, "depth": 1, "delayTicks": 10},
            "fired": True, "aborted": None, "events": [], "errors": [], "triggerSeq": 290,
            "onSeq": 300, "offSeq": 300 + count, "hiddenTicks": count, "hiddenSeqs": hidden,
            "lateSeqs": [], "target": None,
        },
        "arm": {"sampler": {"schema": 2, "selfCheck": {"ok": True}}, target: {"paint": paint}},
        "redSet": [target] if count else [], "unknown": [],
    }


def carry_cover_record() -> dict:
    sha = js_sha256()
    return {
        "runValidity": copy.deepcopy(VALID),
        "kind": "live-continuity-probe-carry-cover", "fixture": "/fixture", "control": "green",
        "coreVariant": None, "coreSha256": sha, "continuity": {"sha256": sha}, "status": "pass",
        "bridges": [{
            "boundary": "b1to2", "result": {"verdict": "pass", "maxStripPx": 1, "cleanShare": 1.0,
                                                "undecidedFrames": 0},
            "clock": {"via": "gl", "lagMs": 7.0},
        }],
        "reasons": [],
    }


def test_passg_stub_outcomes_are_byte_stable_and_fail_closed() -> None:
    record = {
        "runValidity": copy.deepcopy(VALID),
        "pass": "G", "status": "pass", "reasons": [],
    }
    matched = checks.judge(record, "check_passg", "D3", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=0)
    assert matched.lines == ("[PASSG D3] status=pass exit=0",)
    assert matched.verdict is checks.Verdict.MATCH

    for status in ("fail", "inconclusive", "error"):
        mutant = {**record, "status": status, "reasons": [f"stub g-{status}"]}
        result = checks.judge(mutant, "check_passg", "D3", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=0)
        assert result.verdict is checks.Verdict.MISMATCH
        assert result.lines == (f"[PASSG D3] status={status} exit=0", f"    stub g-{status}")

    assert checks.judge(
        {**record, "pass": None}, "check_passg", "D3", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=0,
    ).verdict is checks.Verdict.MISMATCH
    assert checks.judge(
        record, "check_passg", "D3", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=1,
    ).verdict is checks.Verdict.MISMATCH


@pytest.mark.parametrize(
    ("mutation", "problem"),
    [
        ("sha", "nullControl installed core sha"),
        ("extra", "red set"),
        ("unknown", "unknown ['G1-2-3:b1to2:carry']"),
        ("floor", "below the 109-frame floor"),
        ("nofloor", "paintFloor missing"),
    ],
)
def test_passg_red_stub_mutants_fail_against_a_matching_registry(mutation: str, problem: str) -> None:
    record = passg_red_record()
    assert checks.judge(
        record, "check_passg_red", "core:no-pin-hold", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=0,
    ).verdict is checks.Verdict.MATCH

    if mutation == "sha":
        record["nullControl"]["continuity"]["sha256"] = "0" * 64
    elif mutation == "extra":
        record["redSet"].append("G2-1-2:b0to1:carry")
    elif mutation == "unknown":
        record["unknown"] = ["G1-2-3:b1to2:carry"]
    elif mutation == "floor":
        record["paintFloor"] = 109
    else:
        record.pop("paintFloor")
    result = checks.judge(
        record, "check_passg_red", "core:no-pin-hold", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=0,
    )
    assert result.verdict is checks.Verdict.MISMATCH
    assert problem in "\n".join(result.lines)


@pytest.mark.parametrize(
    ("mutation", "problem"),
    [
        ("plus", "hiddenTicks 7 != 6"),
        ("shift", "target seq set [301, 302, 303, 304, 305, 306] != injected"),
        ("unfired", "injector never fired"),
        ("control", "control '1:ancestor-half:pin@2' != '6:ancestor-opacity:pin@2'"),
        ("missing-aborted", "controlRecord unreadable: aborted missing"),
        ("missing-events", "controlRecord unreadable: events missing"),
        ("missing-errors", "controlRecord unreadable: errors missing"),
    ],
)
def test_paint_control_stub_mutants_fail_against_a_matching_record(mutation: str, problem: str) -> None:
    record = paint_control_record()
    assert checks.judge(
        record, "check_paint_control", record["control"], checks.live_run_validity.HOST_HEADLESS_CHROME, rc=0,
    ).verdict is checks.Verdict.MATCH

    hidden = record["controlRecord"]["hiddenSeqs"]
    target = record["targetVerdictId"]
    if mutation == "plus":
        record["controlRecord"]["hiddenTicks"] = 7
        record["controlRecord"]["hiddenSeqs"] = list(range(300, 307))
        record["controlRecord"]["offSeq"] = 307
        record["arm"][target]["paint"]["unpaintedSeqs"] = list(range(300, 307))
    elif mutation == "shift":
        record["arm"][target]["paint"]["unpaintedSeqs"] = [value + 1 for value in hidden]
    elif mutation == "unfired":
        record["controlRecord"]["fired"] = False
    elif mutation == "control":
        record["control"] = "1:ancestor-half:pin@2"
    else:
        record["controlRecord"].pop(mutation.removeprefix("missing-"))
    result = checks.judge(
        record, "check_paint_control", "6:ancestor-opacity:pin@2",
        checks.live_run_validity.HOST_HEADLESS_CHROME, rc=0,
    )
    assert result.verdict is checks.Verdict.MISMATCH
    assert problem in "\n".join(result.lines)


@pytest.mark.parametrize(
    ("mutation", "problem"),
    [
        ("status", "status 'fail' != 'pass'"),
        ("sha", "installed core sha is not the arm's"),
        ("fixture", "fixture 'elsewhere' != '/fixture'"),
        ("control", "control 'red' != 'green'"),
        ("clock", "bridge clocks ['fallback'] are not all 'gl'"),
    ],
)
def test_carry_cover_stub_mutants_fail_against_a_matching_record(mutation: str, problem: str) -> None:
    record = carry_cover_record()
    arm = json.dumps({"label": "green", "wanted": "pass", "fixture": "/fixture", "control": "green", "variant": None})
    assert checks.judge(
        record, "check_cc", arm, checks.live_run_validity.HOST_HEADLESS_CHROME, rc=0,
    ).verdict is checks.Verdict.MATCH

    if mutation == "status":
        record["status"] = "fail"
    elif mutation == "sha":
        record["continuity"]["sha256"] = "0" * 64
    elif mutation == "fixture":
        record["fixture"] = "elsewhere"
    elif mutation == "control":
        record["control"] = "red"
    else:
        record["bridges"][0]["clock"]["via"] = "fallback"
    result = checks.judge(record, "check_cc", arm, checks.live_run_validity.HOST_HEADLESS_CHROME, rc=0)
    assert result.verdict is checks.Verdict.MISMATCH
    assert problem in "\n".join(result.lines)


def test_expect_stub_match_and_record_exit_mapping() -> None:
    args = ["--wait-profile", "fast"]
    plan = build_continuity_plan(True)
    unstripped = __import__("hashlib").sha256(json.dumps(plan).encode()).hexdigest()
    ids = ["refusedCarry1to2", *[f"filler{index}" for index in range(14)]]
    text = "\n".join([
        f"Core variant: none · injected core sha256: {js_sha256()}",
        f"Strip: none · injected plan sha256: {unstripped}",
        "Freeze bracket: run", "success: **True**", "Source unchanged: **True**",
        *[f"- {finding}: **True**" for finding in ids],
    ])
    record = {
        "text": text, "args": args,
        "expectedRed": "", "expectedInconclusive": "",
    }
    result = checks.judge(record, "expect", "AUTO", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=0)
    assert result.verdict is checks.Verdict.MATCH and result.exit_code == 0
    assert result.lines[0] == "    validity: not applicable (P2 adversarial harness has no instrument capture)"
    assert result.lines[-1] == "    expected red: {}; expected inconclusive: {} -> MATCH"

    record["expectedRed"] = "RECORD"
    result = checks.judge(record, "expect", "AUTO", checks.live_run_validity.HOST_HEADLESS_CHROME, rc=0)
    assert result.verdict is checks.Verdict.RECORDED and result.exit_code == 3
    assert result.lines[-1] == "    expected red: (none registered) -> RECORDED"


def test_today_shaped_record_without_run_validity_is_invalid() -> None:
    record = feed_record()
    record.pop("runValidity")

    result = checks.judge(record, "check_mm_feed", "feed-on-1920", HOST, rc=0)

    assert result.verdict is checks.Verdict.INVALID
    assert result.lines == (
        "[MM-FEED Alpha_DSK feed-on-1920] exit=0 records=2 status=pass",
        "    INVALID: runValidity is missing or malformed",
    )

    wrong_host = feed_record()
    wrong_host["runValidity"]["policy"]["hostKind"] = "managed OBS 30"
    result = checks.judge(wrong_host, "check_mm_feed", "feed-on-1920", HOST, rc=0)
    assert result.verdict is checks.Verdict.INVALID
    assert result.lines[-1] == "    INVALID: runValidity policy hostKind 'managed OBS 30' != 'headless Chrome'"


@pytest.mark.parametrize("value", [None, {"verdict": None}, {"verdict": None, "notApplicable": True}])
def test_feed_on_hold_requires_explicit_na_on_continuous_mode(value) -> None:
    record = feed_record()
    row = record["arms"]["A"][TARGET_ID]["underArtwork"]
    if value is None:
        row.pop("holdFrame")
    else:
        row["holdFrame"] = value
        if value.get("notApplicable"):
            row["mode"] = "standDown"

    result = checks.judge(record, "check_mm_feed", "feed-on-1920", HOST, rc=0)

    assert result.verdict is checks.Verdict.MISMATCH
    assert f"{TARGET_ID}.holdFrame" in "\n".join(result.lines)


def test_attach_once_uses_attach_holder_without_fallback() -> None:
    record = feed_record()
    attach = record["arms"]["A"]
    for spec in record["groundTruth"]["verdicts"]:
        if spec.get("underArtwork"):
            attach[spec["id"]]["underArtwork"].update(
                holdFrame={"verdict": True}, posterHold={"verdict": True}, feedLive={"verdict": False},
            )
    record["attach"] = attach
    record["arms"] = {"A": {"verdicts": attach["verdicts"]}}
    assert checks.judge(record, "check_mm_feed", "attach-once", HOST, rc=0).verdict is checks.Verdict.MATCH

    record.pop("attach")
    result = checks.judge(record, "check_mm_feed", "attach-once", HOST, rc=0)
    assert result.verdict is checks.Verdict.MISMATCH
    assert "attach missing or malformed" in "\n".join(result.lines)


def test_unknown_mm_feed_label_is_not_the_registered_empty_row() -> None:
    result = checks.judge(feed_record(), "check_mm_feed", "departure-early-hide", HOST, rc=1)
    assert result.verdict is checks.Verdict.MISMATCH
    assert result.lines[-1] == "    MISMATCH: unregistered MM-FEED label"


@pytest.mark.parametrize("label", ["feed-on", "feed-off", "from-only-crossfade", "from-only-single"])
def test_internal_mm_feed_row_names_are_not_registered_shell_labels(label: str) -> None:
    result = checks.judge(feed_record(), "check_mm_feed", label, HOST, rc=0)

    assert result.verdict is checks.Verdict.MISMATCH
    assert result.lines[-1] == "    MISMATCH: unregistered MM-FEED label"


def test_mm_opacity_na_is_exact_and_needs_other_false_evidence() -> None:
    record = feed_record()
    record["arms"]["A"][TARGET_ID]["underArtwork"]["labelsOverFeed"] = {
        "verdict": True, "notApplicable": True,
    }
    record["arms"]["A"][OTHER_ID]["underArtwork"]["labelsOverFeed"] = {"verdict": False}
    assert checks.judge(record, "check_mm_feed", "mm-opacity-off", HOST, rc=1).verdict is checks.Verdict.MATCH

    wrong_row = copy.deepcopy(record)
    wrong_row["arms"]["A"][TARGET_ID]["underArtwork"]["labelsOverFeed"] = {"verdict": False}
    wrong_row["arms"]["A"][OTHER_ID]["underArtwork"]["labelsOverFeed"] = {
        "verdict": True, "notApplicable": True,
    }
    result = checks.judge(wrong_row, "check_mm_feed", "mm-opacity-off", HOST, rc=1)
    assert result.verdict is checks.Verdict.MISMATCH
    assert "is not registered as notApplicable" in "\n".join(result.lines)

    no_false = copy.deepcopy(record)
    no_false["arms"]["A"][OTHER_ID]["underArtwork"]["labelsOverFeed"] = {"verdict": True}
    result = checks.judge(no_false, "check_mm_feed", "mm-opacity-off", HOST, rc=1)
    assert result.verdict is checks.Verdict.MISMATCH
    assert "has no evidenced labelsOverFeed False row" in "\n".join(result.lines)


def test_host_red_census_canonicalizes_a_real_trimmed_proxy_url() -> None:
    arm = "strip:bridge@4"
    red = list(checks.RED_ARM_EXPECTATIONS[(checks.DECK_PLAN_SHA256["D1"], arm, "off")])
    carry = red[0]
    record = {
        "runValidity": copy.deepcopy(VALID),
        "groundTruth": {"planSha256": checks.DECK_PLAN_SHA256["D1"], "verdicts": [{"id": carry, "kind": "carry"}]},
        "glReplay": {"requested": "off"}, "status": "pass", "redArm": arm,
        "expectedRedSet": red, "redSet": red, "unknown": [], "expectedCoreSha256": js_sha256(),
        "arm": {
            "sampler": {"schema": 2, "selfCheck": {"ok": True}},
            "census": {
                "3": {"unexpectedVideos": [{"src": "file:///tmp/Counter-A.mov-0.0000-46.0333.mov"}], "duplicateVideos": []},
                "4": {"unexpectedVideos": [{"src": "http://127.0.0.1/Counter-A.mov-0.0000-46.0333.mov?x=1"}], "duplicateVideos": []},
            },
            carry: {},
        },
    }
    result = checks.judge(record, "check_host_red", arm, HOST, rc=0)
    assert result.verdict is checks.Verdict.MATCH


@pytest.mark.parametrize("mutation", ["missing", "malformed", "foreign-red"])
def test_host_red_floor_requires_a_registered_verdict_inventory(mutation: str) -> None:
    record = host_red_record()
    if mutation == "missing":
        record["groundTruth"].pop("verdicts")
    elif mutation == "malformed":
        record["groundTruth"]["verdicts"] = "not-a-list"
    else:
        record["redSet"] = record["expectedRedSet"] = ["b9to10:foreign.mov#1->foreign.mov#1:carry"]
    result = checks.judge(record, "check_host_red", "core:no-pin-hold", HOST, rc=0)
    assert result.verdict is checks.Verdict.MISMATCH
    assert "groundTruth.verdicts missing or malformed" in "\n".join(result.lines) or "is not a registered spec id" in "\n".join(result.lines)


def test_passg_red_foreign_floor_id_preserves_run_none_line() -> None:
    record = passg_red_record()
    foreign = "G9-9-9:b0to1:counter-a.mov#1->counter-a.mov#1:carry"
    record["expectedRedSet"] = record["redSet"] = [foreign]
    checks.PASSG_RED_EXPECTATIONS[(checks.DECK_PLAN_SHA256["D1"], "core:no-pin-hold")]
    result = checks.judge(record, "check_passg_red", "core:no-pin-hold", HOST, rc=0)
    assert result.verdict is checks.Verdict.MISMATCH
    assert f"{foreign} longest unpainted run None below the 60-frame floor" in "\n".join(result.lines)


def test_passg_red_foreign_destination_names_the_missing_measurement() -> None:
    record = passg_red_record()
    foreign = "G9-9-9:destination"
    record["expectedRedSet"] = record["redSet"] = [foreign]
    result = checks.judge(record, "check_passg_red", "core:no-pin-hold", HOST, rc=0)

    assert result.verdict is checks.Verdict.MISMATCH
    assert f"{foreign} has no measured leg or armed destination" in result.lines[-1]


@pytest.mark.parametrize("rc", ["missing", "stale(other-round 0)"])
def test_non_numeric_status_is_an_ordered_mismatch(rc: str) -> None:
    record = {"runValidity": copy.deepcopy(VALID), "pass": "G", "status": "pass", "reasons": []}
    result = checks.judge(record, "check_passg", "D1", HOST, rc=rc)
    assert result.verdict is checks.Verdict.MISMATCH
    assert result.lines == (f"[PASSG D1] status=pass exit={rc}",)


@pytest.mark.parametrize(
    ("gate_kind", "arm", "line"),
    [
        ("check_mm_feed", "feed-on-1920", "[MM-FEED D7 feed-on-1920] no artifact (missing) exit=missing"),
        ("check_host_red", "core:stash-any", "[HOST core:stash-any] no artifact (missing) -> MISMATCH"),
        ("check_passg", "D1", "[PASSG D1] no artifact (missing) exit=missing"),
        ("check_passg_red", "core:no-pin-hold", "[PASSG-RED unknown --core-variant no-pin-hold] no artifact (missing) exit=missing"),
        ("check_paint_control", "6:ancestor-opacity:pin@2", "[PAINT-CONTROL unknown 6:ancestor-opacity:pin@2] no artifact (missing) exit=missing"),
        ("check_cc", json.dumps({"label": "green", "wanted": "pass", "fixture": "/fixture", "control": "green", "variant": None}),
         "[CARRY-COVER green] no artifact (missing) exit=missing"),
    ],
)
def test_load_errors_keep_no_artifact_lines(gate_kind: str, arm: str, line: str) -> None:
    record = {"_loadError": "missing", "_deckLabel": "D7" if gate_kind == "check_mm_feed" else None}
    result = checks.judge(record, gate_kind, arm, HOST, rc="missing")
    assert result.verdict is checks.Verdict.MISMATCH
    assert result.lines == (line,)


def test_expect_missing_log_has_no_traceback() -> None:
    result = checks.judge({"_loadError": "missing"}, "expect", "AUTO", HOST, rc="missing")
    assert result.lines == ("    no log (missing) -> MISMATCH",)
    assert result.verdict is checks.Verdict.MISMATCH


@pytest.mark.parametrize(
    ("variant", "control", "wanted", "clock", "status"),
    [
        ("linear-bridge", "red", "fail", "gl", "fail"),
        (None, "null", "fail", "gl", "fail"),
        ("no-gl-clock", "red", "fail", "fallback", "fail"),
        ("linear-bridge", "red", "fail", "gl", "inconclusive"),
    ],
)
def test_cc_red_null_and_inconclusive_controls(variant, control: str, wanted: str, clock: str, status: str) -> None:
    record = carry_cover_record()
    sha = variant_sha(variant) if variant else js_sha256()
    record.update(coreVariant=variant, control=control, status=status, coreSha256=sha, continuity={"sha256": sha})
    record["bridges"][0]["clock"]["via"] = clock
    label = f"--core-variant {variant}" if variant else "--carry-cover-null"
    arm = json.dumps({"label": label, "wanted": wanted, "fixture": "/fixture", "control": control, "variant": variant})
    result = checks.judge(record, "check_cc", arm, HOST, rc=1)
    assert result.verdict is (checks.Verdict.MATCH if status == wanted else checks.Verdict.MISMATCH)


def test_host_red_sampler_and_floor_controls_fail_closed() -> None:
    no_self = host_red_record()
    no_self["arm"]["sampler"].pop("selfCheck")
    assert "arm.sampler is not schema 2" in "\n".join(
        checks.judge(no_self, "check_host_red", "core:no-pin-hold", HOST, rc=0).lines
    )
    no_floor = host_red_record()
    no_floor.pop("paintFloor")
    assert "paintFloor missing" in "\n".join(
        checks.judge(no_floor, "check_host_red", "core:no-pin-hold", HOST, rc=0).lines
    )

    gl_mismatch = host_red_record()
    gl_mismatch["_argvGlReplay"] = "auto"
    result = checks.judge(gl_mismatch, "check_host_red", "core:no-pin-hold", HOST, rc=0)
    assert result.verdict is checks.Verdict.MISMATCH
    assert "glReplay.requested 'off' != argv 'auto'" in "\n".join(result.lines)


def test_paint_control_minus_one_tick_is_a_mismatch() -> None:
    record = paint_control_record()
    record["controlRecord"]["hiddenTicks"] = 5
    result = checks.judge(record, "check_paint_control", record["control"], HOST, rc=0)
    assert result.verdict is checks.Verdict.MISMATCH
    assert "hiddenTicks 5 != 6" in "\n".join(result.lines)


ADFEB552_FIXTURES = REPO / "tests/fixtures/gate_checks/adfeb552"
ADFEB552_EXPECTATIONS = json.loads((ADFEB552_FIXTURES / "expected-lines.json").read_text())


def _remove_lines(lines: list[str], removed: list[str]) -> list[str]:
    remaining = Counter(removed)
    kept = []
    for line in lines:
        if remaining[line]:
            remaining[line] -= 1
        else:
            kept.append(line)
    assert not +remaining
    return kept


@pytest.mark.parametrize("name", sorted(ADFEB552_EXPECTATIONS))
def test_minimized_adfeb552_old_heredoc_comparison(name: str) -> None:
    expected = ADFEB552_EXPECTATIONS[name]
    record = checks._load(str(ADFEB552_FIXTURES / name))
    record.update(expected["runtimeFields"])
    current_lines = tuple(_remove_lines(expected["oldLines"], expected["removed"]) + expected["added"])

    unqualified = checks.judge(
        record, expected["gateKind"], expected["arm"], HOST, rc=expected["rc"],
    )
    qualified_record = copy.deepcopy(record)
    qualified_record["runValidity"] = {"ok": True, "policy": {"hostKind": HOST}}
    qualified = checks.judge(
        qualified_record, expected["gateKind"], expected["arm"], HOST, rc=expected["rc"],
    )

    assert unqualified.verdict is checks.Verdict.INVALID
    assert unqualified.exit_code == 1 and unqualified.status == "invalid"
    assert unqualified.lines == (*current_lines, "    INVALID: runValidity is missing or malformed")
    assert qualified.verdict is checks.Verdict(expected["verdict"])
    assert qualified.exit_code == (0 if qualified.verdict is checks.Verdict.MATCH else 1)
    assert qualified.status == ("pass" if qualified.verdict is checks.Verdict.MATCH else "fail")
    assert qualified.lines == current_lines
