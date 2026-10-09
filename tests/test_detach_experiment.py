"""Unit tests for the pure parts of `scripts/detach_experiment.py`, the main-relevance port of the one-frame
detach experiment driver (`.agents/plans/keynote_live_continuity_detach_r8.plan.md` §2.3).

No Chrome, no host. Samples, pre-paint rows, lifecycle rows and core notes are synthetic and shaped like the
instrument's own output: a sampler row per rAF tick (`t`, `rafTs`, `scene`, `playerState`, `videos`), a pre-paint
row per ResizeObserver callback (`t`, `n`, `ids`), an I2 row per `<video>` add/remove, and the core's own notes
(`{kind, detail, t}`). Main's v5 core has no per-decoder instance id: a carry is its `reuse-decoder` note.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parent.parent
for sub in ("scripts", "src"):
    if str(REPO / sub) not in sys.path:
        sys.path.insert(0, str(REPO / sub))

import detach_experiment as dx  # noqa: E402
import live_continuity_probe as probe  # noqa: E402
from obed_edom import live_runtime  # noqa: E402
from obed_edom.live_continuity_js import js_sha256  # noqa: E402

FRAME = 1000.0 / 60.0
MM_SCENES = [1]


def video(el_id: int, remounted: bool = True) -> dict[str, Any]:
    return {"elId": el_id, "remounted": remounted}


def timeline(segments: list[tuple[Any, str, float, list[dict[str, Any]]]], start: float = 1000.0) -> list[dict[str, Any]]:
    """One sampler row per frame for each (scene, state, duration ms, videos) segment."""
    rows, t = [], start
    for scene, state, duration, videos in segments:
        for _ in range(max(1, round(duration / FRAME))):
            rows.append({"t": t + 1.0, "rafTs": t, "scene": scene, "playerState": state, "videos": list(videos)})
            t += FRAME
    return rows


def post_mm(*, waited: bool = False, idle_ms: float = 100.0, mm_ms: float = 1600.0, pre=None, dst=None):
    """P2's 1->2: scene 0 idle, the click MM (scene 1 setup + Playing), idle, then scene 2's setup and `Playing`."""
    pre = [video(7)] if pre is None else pre
    dst = [video(7)] if dst is None else dst
    segments = [
        (0, "IdleAtFinalState", 1500.0, pre),
        (1, "SettingUpScene", 100.0, pre),
        (1, "Playing", mm_ms, pre),
        (1, "IdleAtFinalState", idle_ms, pre),
    ]
    if waited:
        segments.append((1, "WaitingToJump", 83.0, pre))
    segments += [(2, "SettingUpScene", 100.0, pre), (2, "Playing", 600.0, dst)]
    return timeline(segments)


def first_index(samples: list[dict[str, Any]], scene: int, state: str) -> int:
    return next(i for i, row in enumerate(samples) if row["scene"] == scene and row["playerState"] == state)


def carry_note(samples: list[dict[str, Any]], *, old: int = 7, new: int = 12, offset: float = 2.0) -> dict[str, Any]:
    """The core's `reuse-decoder` note just after the last pre-`Playing` sample."""
    t = samples[first_index(samples, 2, "Playing") - 1]["t"] + offset
    return {"t": t, "kind": "reuse-decoder", "detail": {"key": "untitled.mov", "oldElId": old, "newElId": new, "sceneHash": "#2"}}


def prepaint_of(samples: list[dict[str, Any]], blank: frozenset[int] = frozenset()) -> list[dict[str, Any]]:
    """One pre-paint row per frame, 8 ms after that frame's tick; `blank` frames paint no `<video>`."""
    return [
        {"t": row["t"] + 8.0, "rafTs": row["rafTs"], "n": 0 if i in blank else len(row["videos"]),
         "ids": [] if i in blank else [v["elId"] for v in row["videos"]]}
        for i, row in enumerate(samples)
    ]


def classify(samples, lifecycle=(), prepaint=None, core_events=None):
    jumps = dx.post_mm_jumps(samples, MM_SCENES)
    prepaint = prepaint_of(samples) if prepaint is None else prepaint
    core_events = [carry_note(samples)] if core_events is None else core_events
    return [dx.classify_jump(j, samples, list(lifecycle), prepaint, list(core_events), FRAME) for j in jumps]


def raw_run(samples, prepaint=None, lifecycle=(), *, served=dx.SERVED_SHA256, mode="qualified", core=dx.CORE_SHA256,
            gl_replay="auto", gl_mode="injected", control=None, instrument_control=None, error=None,
            core_events=None) -> dict[str, Any]:
    return {
        "runId": "r1", "config": {"deck": "P2", "variant": "V8", "arm": "A", "glReplay": gl_replay,
                                  "viewport": [2560, 1440], "control": control},
        "meta": {"loadavg": [3.0, 3.0, 3.0]}, "error": error,
        "output": {"mmOpacity": {"sha256": served},
                   "continuity": {"mode": mode, "sha256": core, "glReplay": {"mode": gl_mode, "sha256": "g" * 64}}},
        "arm": {"stageFit": {"verdict": True}},
        "samples": samples,
        "instrument": {"lifecycle": list(lifecycle), "prepaint": prepaint_of(samples) if prepaint is None else prepaint,
                       "control": instrument_control, "errors": []},
        "coreEvents": [carry_note(samples)] if core_events is None else core_events,
        "mmScenes": MM_SCENES,
    }


# --- R8 identity and served bytes ------------------------------------------------------------------------------


def test_main_ships_r1_to_r8_with_the_preload_last() -> None:
    dx.check_r8()
    assert live_runtime._MM_OPACITY_REPLACEMENTS[7][0] == dx.R8_ANCHOR


def test_check_r8_refuses_a_table_without_the_preload_last() -> None:
    table = list(live_runtime._MM_OPACITY_REPLACEMENTS)
    with pytest.raises(ValueError, match="R1-R8"):
        dx.check_r8(table[:7])
    with pytest.raises(ValueError, match="R1-R8"):
        dx.check_r8([table[7], *table[:7]])


def test_serving_sets_mm_opacity_auto_only_inside_the_context(monkeypatch) -> None:
    monkeypatch.delenv(live_runtime.MM_OPACITY_ENV, raising=False)
    original = live_runtime._MM_OPACITY_REPLACEMENTS
    with dx.serving():
        assert dx.os.environ[live_runtime.MM_OPACITY_ENV] == "auto"
        assert live_runtime._MM_OPACITY_REPLACEMENTS is original
    assert live_runtime.MM_OPACITY_ENV not in dx.os.environ


def test_the_planned_core_is_this_checkouts_core() -> None:
    assert dx.CORE_SHA256 == js_sha256()


def test_main_serves_the_same_v8_bytes_as_s2s_v8() -> None:
    assert dx.SERVED_SHA256 == "574274e88485745a6f55a8563d43ddfb91299db6e4d749fd34719436ade751bf"


_PLAYER = probe.FIXTURE / "assets/player/main.js"


@pytest.mark.skipif(not _PLAYER.is_file(), reason="P2 fixture is not in this checkout")
def test_planned_served_sha_matches_the_pinned_player() -> None:
    served = live_runtime.patch_player(_PLAYER.read_bytes(), mm_opacity=True)
    assert hashlib.sha256(served).hexdigest() == dx.SERVED_SHA256


# --- instrument JS --------------------------------------------------------------------------------------------


def test_instrumented_sampler_records_frame_time_and_toggles_the_sentinel() -> None:
    js = dx.instrumented_sampler_js({"mode": "positive", "atScene": 2})
    assert "function tick(ts){" in js and "function tick(){" not in js
    assert "samples.push({t: t, rafTs: ts, scene:" in js
    assert js.count("window.__obedDetachInstr__.toggle(ts)") == 1
    assert '"control": {"mode": "positive", "atScene": 2}' in js
    assert f'"fallbackMs": {dx.CONTROL_FALLBACK_MS}' in js
    assert "attachShadow({mode: 'closed'})" in js
    assert js.index("window.__obedDetachInstr__ = instr") < js.index("window.__obedContinuityProbe__ = {samples")


def test_the_instrument_reads_main_plan_shapes_and_arms_on_the_core_carry() -> None:
    js = dx.instrumented_sampler_js(None)
    assert "b.action === 'glReplay' && b.instanceRect" in js and "movies[k].footprint" in js
    assert "e.kind === 'reuse-decoder'" in js and "hashNum(d.sceneHash)" in js
    assert "__obedInstance" not in js


def test_instrumented_sampler_refuses_a_moved_anchor() -> None:
    with pytest.raises(ValueError, match="anchor"):
        dx.instrumented_sampler_js(None, probe.SAMPLER_JS.replace("function tick(){", "function tick(now){"))


def test_the_default_probe_sampler_is_untouched_outside_the_instrument() -> None:
    original_js, original_drive = probe.SAMPLER_JS, probe.drive_and_sample
    with dx.instrumented({}):
        assert probe.SAMPLER_JS != original_js and probe.drive_and_sample is not original_drive
    assert probe.SAMPLER_JS is original_js and probe.drive_and_sample is original_drive
    assert "rafTs" not in probe.SAMPLER_JS


# --- event extraction and classification ----------------------------------------------------------------------


def test_a_direct_post_mm_jump_with_an_empty_first_playing_frame_is_a_blink() -> None:
    samples = post_mm()
    first = first_index(samples, 2, "Playing")
    samples[first]["videos"] = []
    (event,) = classify(samples, prepaint=prepaint_of(samples, frozenset({first})))
    assert event["eligible"] and event["carried"] and event["tracked"] == [7]
    assert event["carry"]["oldElId"] == 7 and event["carry"]["kind"] == "reuse-decoder"
    assert event["waited"] is False and event["r8Engaged"] is True and event["mmClick"] is True
    assert event["firstPlaying"] == "empty"
    assert event["blinkSamples"] and event["blinkPrepaint"] and event["blink"] and event["blinkDecoder"]
    assert [run["frames"] for run in event["sampleEmptyRuns"]] == [1]
    assert not event["invalid"]


def test_waiting_to_jump_marks_the_stock_path() -> None:
    (event,) = classify(post_mm(waited=True))
    assert event["waited"] is True and event["r8Engaged"] is False
    assert event["eligible"] and not event["blink"] and event["firstPlaying"] == "carried"


def test_a_carry_after_the_first_playing_sample_reads_old() -> None:
    samples = post_mm()
    late = carry_note(samples, offset=FRAME + 2.0)
    (event,) = classify(samples, core_events=[late])
    assert event["eligible"] and event["firstPlaying"] == "old"


def test_an_empty_sample_that_still_paints_is_not_a_blink() -> None:
    samples = post_mm()
    prepaint = prepaint_of(samples)
    samples[first_index(samples, 2, "Playing")]["videos"] = []
    (event,) = classify(samples, prepaint=prepaint)
    assert event["blinkSamples"] and not event["blinkPrepaint"] and not event["blink"]


def test_a_pre_paint_hole_alone_is_reported_but_not_a_blink() -> None:
    samples = post_mm()
    (event,) = classify(samples, prepaint=prepaint_of(samples, frozenset({first_index(samples, 2, "Playing")})))
    assert event["blinkPrepaint"] and not event["blinkSamples"] and not event["blink"]


def test_only_flanked_empty_runs_count() -> None:
    rows = [{"t": i, "videos": v} for i, v in enumerate([[1], [], [], [1], [], []])]
    assert dx.absent_runs(rows, lambda r: not r["videos"]) == [(1, 2)]
    assert dx.absent_runs([{"t": 0, "videos": []}, {"t": 1, "videos": [1]}], lambda r: not r["videos"]) == []


def test_an_empty_run_that_starts_before_the_jump_window_is_not_a_blink() -> None:
    samples = post_mm()
    mm = first_index(samples, 1, "Playing")
    first = first_index(samples, 2, "Playing")
    for row in samples[mm + 1:first - 3]:
        row["videos"] = []
    (event,) = classify(samples, prepaint=prepaint_of(samples, frozenset(range(mm + 1, first - 3))))
    assert not event["blinkSamples"] and not event["blinkPrepaint"]


def gl_auto_post_mm(*, handback_frames_before_play: int = 0) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Main's P2 under GL replay auto, as the live dumps show it: no `<video>` from the MM's first frame (the
    module paints the movie) until the hand-back, which lands after the last setup sample and before the first
    destination `Playing` sample (`handback_frames_before_play` = 0), then the remounted decoder is present.
    No `reuse-decoder` at this jump: the core binds the destination's own element only at a later build."""
    samples = post_mm(idle_ms=650.0)
    mm = first_index(samples, 1, "Playing")
    first = first_index(samples, 2, "Playing")
    mounted = first - handback_frames_before_play
    for row in samples[mm:mounted]:
        row["videos"] = []
    prepaint = prepaint_of(samples)
    t = samples[mounted - 1]["t"] + 8.0
    handback = {"t": t, "kind": "glreplay-release",
                "detail": {"ok": True, "mode": "handoff", "reason": None, "elId": 7, "retired": []}}
    return samples, prepaint, handback


def test_the_glreplay_handback_is_the_carry_of_its_jump() -> None:
    samples, prepaint, handback = gl_auto_post_mm()
    (event,) = classify(samples, prepaint=prepaint, core_events=[handback])
    assert event["scene"] == 2 and event["mmScene"] == 1 and event["autoJump"] is False and event["mmClick"]
    assert event["eligible"] and event["carried"] and event["tracked"] == [7] and event["path"] == "handback"
    assert event["carry"] == {"t": handback["t"], "kind": "glreplay-handoff", "oldElId": 7, "newElId": None}
    assert event["handback"] == {"t": handback["t"], "mode": "handoff", "elId": 7}
    assert event["firstPlaying"] == "carried"
    assert not event["blink"] and not event["sampleEmptyRuns"] and not event["prepaintEmptyRuns"]


def test_a_handback_a_frame_before_play_is_still_eligible_and_scored_unchanged() -> None:
    samples, prepaint, handback = gl_auto_post_mm(handback_frames_before_play=2)
    first = first_index(samples, 2, "Playing")
    samples[first]["videos"] = []
    prepaint[first] = {**prepaint[first], "n": 0, "ids": []}
    (event,) = classify(samples, prepaint=prepaint, core_events=[handback])
    assert event["eligible"] and event["blink"] and event["blinkDecoder"]
    assert [run["frames"] for run in event["sampleEmptyRuns"]] == [1]


def test_a_failed_or_retiring_release_is_not_a_handback() -> None:
    samples, prepaint, handback = gl_auto_post_mm()
    retire = {**handback, "detail": {**handback["detail"], "mode": "retire", "reason": "badRect"}}
    (event,) = classify(samples, prepaint=prepaint, core_events=[retire])
    assert not event["eligible"] and event["path"] is None and event["handback"] is None


def test_a_handback_outside_the_jump_window_is_not_this_jumps_carry() -> None:
    samples, prepaint, handback = gl_auto_post_mm()
    early = {**handback, "t": samples[first_index(samples, 1, "Playing")]["t"]}
    (event,) = classify(samples, prepaint=prepaint, core_events=[early])
    assert not event["eligible"] and event["handback"] is None


def test_paint_at_pin_lists_the_top_element_per_pre_paint() -> None:
    rows = [{"t": 1.0, "pins": [{"top": ["canvas#gl", "div"], "videoAt": []}]},
            {"t": 2.0, "pins": [{"top": ["video:7"], "videoAt": [7]}]}, {"t": 3.0, "pins": []}, {"t": 9.0, "pins": [{}]}]
    assert dx.paint_at_pin(rows, 0.0, 5.0) == [{"t": 1.0, "top": "canvas#gl", "videoAt": []},
                                               {"t": 2.0, "top": "video:7", "videoAt": [7]}]


def test_only_jumps_out_of_a_magic_move_scene_count_and_click_jumps_are_kept() -> None:
    assert dx.post_mm_jumps(post_mm(), []) == []
    assert dx.post_mm_jumps(post_mm(), [0]) == []
    (click,) = dx.post_mm_jumps(post_mm(idle_ms=dx.AUTO_IDLE_MAX_MS + 250), MM_SCENES)
    assert click["autoJump"] is False and click["idleMs"] >= dx.AUTO_IDLE_MAX_MS
    (auto,) = dx.post_mm_jumps(post_mm(), MM_SCENES)
    assert auto["autoJump"] is True and auto["scene"] == 2


@pytest.mark.skipif(not (probe.FIXTURE / "assets/header.json").is_file(), reason="P2 fixture is not in this checkout")
def test_p2s_magic_moves_are_scenes_1_and_7() -> None:
    assert dx.magic_move_scenes(probe.FIXTURE) == [1, 7]


def test_eligibility_needs_a_remounted_decoder_that_the_core_carries() -> None:
    (raw,) = classify(post_mm(pre=[video(7, remounted=False)]))
    assert not raw["eligible"] and raw["tracked"] == []
    (uncarried,) = classify(post_mm(), core_events=[])
    assert not uncarried["eligible"] and not uncarried["carried"]
    samples = post_mm()
    (other,) = classify(samples, core_events=[carry_note(samples, old=9)])
    assert not other["eligible"]
    early = carry_note(samples, offset=-FRAME)
    (before,) = classify(samples, core_events=[early])
    assert not before["eligible"]
    bridge = {**carry_note(samples), "kind": "bridge-3to4"}
    (bridged,) = classify(samples, core_events=[bridge])
    assert not bridged["eligible"]


def test_a_long_frame_inside_the_jump_window_is_invalid() -> None:
    samples = post_mm()
    first = first_index(samples, 2, "Playing")
    for row in samples[first:]:
        row["rafTs"] += 60.0
        row["t"] += 60.0
    (event,) = classify(samples)
    assert event["invalid"] and event["maxDtMs"] > dx.INVALID_DT_MS
    assert dx.build_record(raw_run(samples))["status"] == "invalid"


def test_a_long_frame_outside_the_jump_window_is_valid() -> None:
    samples = post_mm()
    for row in samples[5:]:
        row["rafTs"] += 60.0
        row["t"] += 60.0
    (event,) = classify(samples)
    assert not event["invalid"]
    assert dx.build_record(raw_run(samples))["rafStats"]["over50"] == 1


def test_teardown_phase_and_same_delivery_rehome() -> None:
    samples = post_mm()
    setup = samples[first_index(samples, 2, "SettingUpScene")]
    t = setup["rafTs"] + 12.0
    lifecycle = [
        {"t": t, "rafTs": setup["rafTs"], "op": "remove", "elId": 7, "isConnected": True, "remounting": False},
        {"t": t, "rafTs": setup["rafTs"], "op": "add", "elId": 7, "parentId": "x", "layerId": "layer-1"},
    ]
    (event,) = classify(samples, lifecycle)
    assert event["teardown"]["phaseMs"] == 12.0 and event["teardown"]["phase"] == "late"
    assert event["rehome"]["sameDelivery"] is True and event["rehome"]["layerId"] == "layer-1"


def test_phase_buckets() -> None:
    assert [dx.phase_bucket(f) for f in (None, 0.1, 0.5, 0.9, 1.4)] == [None, "early", "mid", "late", "late"]


def test_core_notes_in_the_window_are_kept_with_their_decoder() -> None:
    samples = post_mm()
    t = samples[first_index(samples, 2, "Playing")]["t"]
    notes = [{"t": t, "kind": "dom-swap", "detail": {"elId": 7}}, {"t": t, "kind": "reuse-decoder", "detail": {"oldElId": 7}},
             {"t": t, "kind": "glreplay-release", "detail": {"elId": 7, "mode": "handoff"}},
             {"t": t, "kind": "facade-error", "detail": "x"}, {"t": 0.0, "kind": "dom-swap", "detail": {"elId": 7}}]
    (event,) = classify(samples, core_events=notes)
    assert [(n["kind"], n["elId"]) for n in event["coreNotes"]] == [
        ("dom-swap", 7), ("reuse-decoder", 7), ("glreplay-release", 7)]


# --- record status -------------------------------------------------------------------------------------------


def test_record_status_follows_served_bytes_continuity_gl_and_events() -> None:
    samples = post_mm()
    record = dx.build_record(raw_run(samples))
    assert record["status"] == "ok" and record["eligibleEvents"] == 1 and record["glReplayMode"] == "injected"
    wrong = dx.build_record(raw_run(samples, served="0" * 64))
    assert wrong["status"] == "error" and not wrong["servedShaOk"]
    assert dx.build_record(raw_run(samples, mode="unsupported"))["status"] == "error"
    assert dx.build_record(raw_run(samples, core="0" * 64))["status"] == "error"
    assert dx.build_record(raw_run(samples, error="boom"))["status"] == "error"
    assert dx.build_record(raw_run(samples, gl_mode="off"))["status"] == "error"
    assert dx.build_record(raw_run(samples, core_events=[]))["status"] == "no-events"


def test_gl_replay_off_is_no_events_by_construction() -> None:
    record = dx.build_record(raw_run(post_mm(), gl_replay="off", gl_mode="off", core_events=[]))
    assert record["status"] == "no-events" and record["eligibleEvents"] == 0
    assert dx.OFF_BY_CONSTRUCTION in record["reasons"]


def test_parse_loadavg_and_strata() -> None:
    assert dx.parse_loadavg("{ 2.31 12.45 22.60 }") == [2.31, 12.45, 22.6]
    assert dx.parse_loadavg("error: nope") is None
    assert [dx.load_stratum({"loadavg": [x, 0, 0]}) for x in (1.0, 6.0, 30.0)] == ["low", "mid", "high"]
    assert dx.load_stratum({}) is None


# --- controls ------------------------------------------------------------------------------------------------


def control_run(mode: str, *, absent_ticks: int, absent_paints: int, same_delivery: bool = False) -> dict[str, Any]:
    """The control removes the decoder after frame 20's paint and re-inserts it after the paint `absent_ticks` frames later."""
    samples = timeline([(3, "Playing", 1000.0, [video(7)])])
    remove_at = 20
    t_remove = samples[remove_at]["t"] + 10.0
    prepaint = prepaint_of(samples)
    for i in range(remove_at + 1, remove_at + 1 + absent_ticks):
        samples[i]["videos"] = []
    for i in range(remove_at + 1, remove_at + 1 + absent_paints):
        prepaint[i] = {**prepaint[i], "n": 0, "ids": []}
    t_reinsert = t_remove if same_delivery else samples[remove_at + absent_ticks]["t"] + 12.0
    ctl = {"mode": mode, "fired": True, "armedElId": 7, "tRemove": t_remove, "tReinsert": t_reinsert, "triggerKind": "dom-swap"}
    lifecycle = [{"t": t_remove + 0.1, "op": "remove", "elId": 7, "isConnected": False},
                 {"t": t_reinsert + 0.1, "op": "add", "elId": 7}]
    return raw_run(samples, prepaint, lifecycle, control=mode, instrument_control=ctl, core_events=[])


def test_null_control_passes_with_no_empty_frame_and_one_delivery() -> None:
    verdict = dx.score_control(control_run("null", absent_ticks=0, absent_paints=0, same_delivery=True), [])
    assert verdict["status"] == "pass", verdict["reasons"]


def test_null_control_fails_when_anything_flags() -> None:
    assert dx.score_control(control_run("null", absent_ticks=1, absent_paints=0), [])["status"] == "fail"


def test_positive_control_passes_when_samples_and_pre_paint_both_see_two_frames() -> None:
    verdict = dx.score_control(control_run("positive", absent_ticks=2, absent_paints=2), [])
    assert verdict["status"] == "pass", verdict["reasons"]
    assert verdict["ticksBetween"] == 2 and verdict["sampleAbsentFrames"] == 2 and verdict["prepaintAbsentFrames"] == 2


def test_positive_control_fails_when_pre_paint_misses_the_hole() -> None:
    assert dx.score_control(control_run("positive", absent_ticks=2, absent_paints=0), [])["status"] == "fail"


def test_a_control_that_armed_but_never_fired_fails() -> None:
    raw = control_run("positive", absent_ticks=2, absent_paints=2)
    raw["instrument"]["control"] = {"mode": "positive", "fired": False, "armedElId": 7}
    assert dx.score_control(raw, [])["status"] == "fail"


@pytest.mark.parametrize("gl_replay", ["off", "auto"])
def test_a_control_with_no_carry_cannot_arm_and_never_passes(gl_replay: str) -> None:
    raw = control_run("null", absent_ticks=0, absent_paints=0, same_delivery=True)
    raw["config"]["glReplay"] = gl_replay
    raw["instrument"]["control"] = {"mode": "null", "fired": False, "armedElId": None}
    verdict = dx.score_control(raw, [])
    assert verdict["status"] == "cannot-arm" and dx.CANNOT_ARM in verdict["reasons"]
    assert (dx.OFF_BY_CONSTRUCTION in verdict["reasons"]) is (gl_replay == "off")


def test_timeout0_is_recorded_with_agreement() -> None:
    verdict = dx.score_control(control_run("timeout0", absent_ticks=1, absent_paints=1), [])
    assert verdict["status"] == "recorded" and verdict["agree"] is True


@pytest.mark.parametrize(("waited", "status"), [(False, "pass"), (True, "fail")])
def test_r8_flag_control(waited: bool, status: str) -> None:
    record = dx.build_record(raw_run(post_mm(waited=waited), control="r8flag"))
    assert record["controlVerdict"]["status"] == status


def test_r8_flag_ignores_a_waited_jump_out_of_a_dissolve() -> None:
    """P2's scene 6 follows the 2->3 dissolve (scene 5): stock timing there is expected, R8 only preloads for an MM."""
    samples = post_mm()
    t = samples[-1]["rafTs"] + FRAME
    samples += timeline([(5, "SettingUpScene", 100.0, []), (5, "Playing", 1600.0, []), (5, "IdleAtFinalState", 83.0, []),
                         (5, "WaitingToJump", 183.0, []), (6, "SettingUpScene", 83.0, []), (6, "Playing", 300.0, [])], start=t)
    record = dx.build_record(raw_run(samples, control="r8flag"))
    assert [e["scene"] for e in record["events"]] == [2]
    assert record["controlVerdict"]["status"] == "pass" and record["controlVerdict"]["jumps"] == 1


# --- batch, resume, summary ----------------------------------------------------------------------------------


def test_pending_slots_resume_and_retake_invalid() -> None:
    records = [
        {"slot": 0, "status": "ok"},
        {"slot": 1, "status": "invalid"},
        {"runId": "control", "status": "ok"},
    ]
    todo = dx.pending_slots(4, records, max_attempts=3)
    assert todo == [{"slot": 1, "attempt": 2}, {"slot": 2, "attempt": 1}, {"slot": 3, "attempt": 1}]
    records += [{"slot": 1, "status": "error"}] * 2
    assert [r["slot"] for r in dx.pending_slots(4, records, max_attempts=3)] == [2, 3]


def test_read_jsonl_skips_a_torn_last_line(tmp_path: Path) -> None:
    path = tmp_path / "runs.jsonl"
    dx.append_jsonl(path, {"a": 1})
    with path.open("a") as handle:
        handle.write('{"b": ')
    assert dx.read_jsonl(path) == [{"a": 1}]


def _slot_record(slot: int, blinks: int, events: int, *, status: str = "ok") -> dict[str, Any]:
    return {
        "slot": slot, "glReplay": "auto", "status": status, "meta": {"loadavg": [2.0, 2.0, 2.0]},
        "events": [
            {"eligible": True, "blink": i < blinks, "blinkSamples": i < blinks, "blinkPrepaint": i < blinks,
             "blinkDecoder": i < blinks, "waited": False, "path": "handback", "teardown": {"phase": "late"}}
            for i in range(events)
        ],
    }


def test_summary_counts_one_done_record_per_slot() -> None:
    records = [
        {**_slot_record(0, 0, 1), "status": "invalid"},
        _slot_record(0, 1, 1),
        _slot_record(0, 0, 1),
        _slot_record(1, 0, 1),
        {"runId": "control", "status": "ok", "events": []},
    ]
    summary = dx.summarize(records)
    assert summary["runs"] == 2 and summary["events"] == 2 and summary["blinks"] == 1
    assert summary["statuses"] == {"invalid": 1, "ok": 3}
    assert summary["byPath"] == {"direct": [2, 1]} and summary["byCarryPath"] == {"handback": [2, 1]}
    assert summary["decision"] == "blink: live main bug"


def test_summary_decisions() -> None:
    assert dx.summarize([_slot_record(s, 0, 1) for s in range(10)])["decision"] == "clean"
    off = [{**_slot_record(s, 0, 0), "status": "no-events", "glReplay": "off"} for s in range(3)]
    assert dx.summarize(off)["decision"] == "no eligible events"
    assert dx.summarize([])["decision"] == "n/a"


def test_cli_defaults_are_the_launch_arm_with_gl_replay_auto_at_2560() -> None:
    args = dx.parse_args(["batch", "--out-dir", "x", "--runs", "10"])
    assert (args.deck, args.arm, args.gl_replay, args.viewport) == ("P2", "A", "auto", (2560, 1440))
    with pytest.raises(SystemExit):
        dx.parse_args(["run", "--out-dir", "x", "--deck", "D4"])
