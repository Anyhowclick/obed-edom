"""Unit tests for the pure parts of `scripts/detach_experiment.py`, the scratch driver of the one-frame detach
experiment (`.agents/plans/keynote_live_continuity_detach_r8.plan.md`).

No Chrome, no host. Samples, pre-paint rows and lifecycle rows are synthetic and shaped like the instrument's
own output: a sampler row per rAF tick (`t`, `rafTs`, `scene`, `playerState`, `videos`), a pre-paint row per
ResizeObserver callback (`t`, `n`, `ids`), and an I2 row per `<video>` add/remove.
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
SRC, DST = "src-instance", "dst-instance"


def video(el_id: int, instance: str, remounted: bool = True) -> dict[str, Any]:
    return {"elId": el_id, "instance": instance, "remounted": remounted}


def timeline(segments: list[tuple[Any, str, float, list[dict[str, Any]]]], start: float = 1000.0) -> list[dict[str, Any]]:
    """One sampler row per frame for each (scene, state, duration ms, videos) segment."""
    rows, t = [], start
    for scene, state, duration, videos in segments:
        for _ in range(max(1, round(duration / FRAME))):
            rows.append({"t": t + 1.0, "rafTs": t, "scene": scene, "playerState": state, "videos": list(videos)})
            t += FRAME
    return rows


def post_mm(*, waited: bool = False, idle_ms: float = 100.0, mm_ms: float = 1600.0, pre=None, dst=None):
    pre = [video(7, SRC)] if pre is None else pre
    dst = [video(7, DST)] if dst is None else dst
    segments = [
        (3, "IdleAtFinalState", 1500.0, pre),
        (4, "SettingUpScene", 100.0, pre),
        (4, "Playing", mm_ms, pre),
        (4, "IdleAtFinalState", idle_ms, pre),
    ]
    if waited:
        segments.append((4, "WaitingToJump", 83.0, pre))
    segments += [(5, "SettingUpScene", 100.0, pre), (5, "Playing", 600.0, dst)]
    return timeline(segments)


def first_index(samples: list[dict[str, Any]], scene: int, state: str) -> int:
    return next(i for i, row in enumerate(samples) if row["scene"] == scene and row["playerState"] == state)


def prepaint_of(samples: list[dict[str, Any]], blank: frozenset[int] = frozenset()) -> list[dict[str, Any]]:
    """One pre-paint row per frame, 8 ms after that frame's tick; `blank` frames paint no `<video>`."""
    return [
        {"t": row["t"] + 8.0, "rafTs": row["rafTs"], "n": 0 if i in blank else len(row["videos"]),
         "ids": [] if i in blank else [v["elId"] for v in row["videos"]]}
        for i, row in enumerate(samples)
    ]


def classify(samples, lifecycle=(), prepaint=None, core_events=()):
    jumps = dx.post_mm_jumps(samples)
    prepaint = prepaint_of(samples) if prepaint is None else prepaint
    return [dx.classify_jump(j, samples, list(lifecycle), prepaint, list(core_events), FRAME) for j in jumps]


def raw_run(samples, prepaint=None, lifecycle=(), *, variant="V8", served=None, mode="qualified", core=dx.CORE_SHA256,
            control=None, instrument_control=None, error=None) -> dict[str, Any]:
    return {
        "runId": "r1", "config": {"deck": "D4", "variant": variant, "arm": "C", "viewport": [2560, 1440], "control": control},
        "meta": {"loadavg": [3.0, 3.0, 3.0]}, "error": error,
        "output": {"mmOpacity": {"sha256": dx.SERVED_SHA256[variant] if served is None else served},
                   "continuity": {"mode": mode, "sha256": core}},
        "arm": {"stageFit": {"verdict": True}},
        "samples": samples,
        "instrument": {"lifecycle": list(lifecycle), "prepaint": prepaint_of(samples) if prepaint is None else prepaint,
                       "control": instrument_control, "errors": []},
        "coreEvents": [],
    }


# --- R8 identity, slicing and served bytes ---------------------------------------------------------------------


def test_variants_slice_the_shipped_table_with_r8_last() -> None:
    table = live_runtime._MM_OPACITY_REPLACEMENTS
    assert dx.variant_replacements("V8") == tuple(table)
    assert dx.variant_replacements("V7") == tuple(table[:7])
    assert dx.variant_replacements("V5") == tuple(table[:5])
    assert dx.variant_replacements("V5+8") == tuple(table[:5]) + (table[7],)
    assert dx.variant_replacements("V5+8")[-1][0] == dx.R8_ANCHOR


def test_the_slice_refuses_a_table_whose_r8_is_not_the_preload() -> None:
    table = list(live_runtime._MM_OPACITY_REPLACEMENTS)
    with pytest.raises(ValueError, match="R1-R8"):
        dx.variant_replacements("V7", table[:7])
    with pytest.raises(ValueError, match="R1-R8"):
        dx.variant_replacements("V7", [table[7], *table[:7]])
    with pytest.raises(ValueError, match="unknown variant"):
        dx.variant_replacements("V6", table)


def test_serving_patches_only_inside_the_context_and_restores(monkeypatch) -> None:
    monkeypatch.delenv(live_runtime.MM_OPACITY_ENV, raising=False)
    original = live_runtime._MM_OPACITY_REPLACEMENTS
    with dx.serving("V7"):
        assert live_runtime._MM_OPACITY_REPLACEMENTS == tuple(original[:7])
        assert dx.os.environ[live_runtime.MM_OPACITY_ENV] == "auto"
    assert live_runtime._MM_OPACITY_REPLACEMENTS is original
    with dx.serving("off"):
        assert live_runtime._MM_OPACITY_REPLACEMENTS is original
        assert dx.os.environ[live_runtime.MM_OPACITY_ENV] == "off"
    assert live_runtime.MM_OPACITY_ENV not in dx.os.environ


def _synthetic_player() -> bytes:
    return b"\n".join([live_runtime._ANCHOR, *(before for before, _ in live_runtime._MM_OPACITY_REPLACEMENTS)])


@pytest.mark.parametrize("variant", ["V8", "V7", "V5", "V5+8"])
def test_served_sha_is_the_sha_of_exactly_the_variants_replacements(monkeypatch, variant: str) -> None:
    player = _synthetic_player()
    monkeypatch.setattr(live_runtime, "PLAYER_SHA256", hashlib.sha256(player).hexdigest())
    with dx.serving(variant):
        served = live_runtime.patch_player(player)
    applied = set(dx.VARIANT_INDICES[variant])
    for index, (before, after) in enumerate(live_runtime._MM_OPACITY_REPLACEMENTS):
        assert (after in served) is (index in applied)
        assert (before in served) is (index not in applied)
    assert dx.served_sha256(player, variant) == hashlib.sha256(served).hexdigest()


def test_the_planned_core_is_this_checkouts_core() -> None:
    assert dx.CORE_SHA256 == js_sha256()


def test_served_shas_of_the_four_variants_and_off_are_distinct() -> None:
    assert set(dx.SERVED_SHA256) == set(dx.SERVINGS)
    assert len(set(dx.SERVED_SHA256.values())) == len(dx.SERVED_SHA256)
    assert all(len(sha) == 64 for sha in dx.SERVED_SHA256.values())


_PLAYER = Path(dx.fixture("qual-decks")) / "D4/html-unmodified/assets/player/main.js"


@pytest.mark.skipif(not _PLAYER.is_file(), reason="qual-decks fixture is not in this checkout")
@pytest.mark.parametrize("variant", dx.SERVINGS)
def test_planned_served_shas_match_the_pinned_player(variant: str) -> None:
    assert dx.served_sha256(_PLAYER.read_bytes(), variant) == dx.SERVED_SHA256[variant]


# --- instrument JS --------------------------------------------------------------------------------------------


def test_instrumented_sampler_records_frame_time_and_toggles_the_sentinel() -> None:
    js = dx.instrumented_sampler_js({"mode": "positive", "atScene": 5})
    assert "function tick(ts){" in js and "function tick(){" not in js
    assert "samples.push({t: t, rafTs: ts, scene:" in js
    assert js.count("window.__obedDetachInstr__.toggle(ts)") == 1
    assert '{"control": {"mode": "positive", "atScene": 5}}' in js
    assert "attachShadow({mode: 'closed'})" in js
    assert js.index("window.__obedDetachInstr__ = instr") < js.index("window.__obedContinuityProbe__ = {samples")


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
    first = first_index(samples, 5, "Playing")
    samples[first]["videos"] = []
    (event,) = classify(samples, prepaint=prepaint_of(samples, frozenset({first})))
    assert event["eligible"] and event["carried"] and event["tracked"] == [7]
    assert event["waited"] is False and event["r8Engaged"] is True and event["mmClick"] is True
    assert event["firstPlaying"] == "empty"
    assert event["blinkSamples"] and event["blinkPrepaint"] and event["blink"] and event["blinkDecoder"]
    assert [run["frames"] for run in event["sampleEmptyRuns"]] == [1]
    assert not event["invalid"]


def test_waiting_to_jump_marks_the_stock_path() -> None:
    (event,) = classify(post_mm(waited=True))
    assert event["waited"] is True and event["r8Engaged"] is False
    assert event["eligible"] and not event["blink"] and event["firstPlaying"] == "carried"


def test_an_empty_sample_that_still_paints_is_not_a_blink() -> None:
    samples = post_mm()
    prepaint = prepaint_of(samples)
    samples[first_index(samples, 5, "Playing")]["videos"] = []
    (event,) = classify(samples, prepaint=prepaint)
    assert event["blinkSamples"] and not event["blinkPrepaint"] and not event["blink"]


def test_a_pre_paint_hole_alone_is_reported_but_not_a_blink() -> None:
    samples = post_mm()
    (event,) = classify(samples, prepaint=prepaint_of(samples, frozenset({first_index(samples, 5, "Playing")})))
    assert event["blinkPrepaint"] and not event["blinkSamples"] and not event["blink"]


def test_only_flanked_empty_runs_count() -> None:
    rows = [{"t": i, "videos": v} for i, v in enumerate([[1], [], [], [1], [], []])]
    assert dx.absent_runs(rows, lambda r: not r["videos"]) == [(1, 2)]
    assert dx.absent_runs([{"t": 0, "videos": []}, {"t": 1, "videos": [1]}], lambda r: not r["videos"]) == []


def test_an_empty_run_that_starts_before_the_jump_window_is_not_a_blink() -> None:
    samples = post_mm()
    mm = first_index(samples, 4, "Playing")
    first = first_index(samples, 5, "Playing")
    for row in samples[mm + 1:first - 3]:
        row["videos"] = []
    (event,) = classify(samples, prepaint=prepaint_of(samples, frozenset(range(mm + 1, first - 3))))
    assert not event["blinkSamples"] and not event["blinkPrepaint"]


def test_a_long_idle_or_a_short_playing_is_not_a_post_mm_jump() -> None:
    assert dx.post_mm_jumps(post_mm(idle_ms=dx.AUTO_IDLE_MAX_MS + 50)) == []
    assert dx.post_mm_jumps(post_mm(mm_ms=dx.MM_MIN_MS - 100)) == []
    assert len(dx.post_mm_jumps(post_mm())) == 1


def test_eligibility_needs_a_remounted_decoder_that_is_carried() -> None:
    (raw,) = classify(post_mm(pre=[video(7, SRC, remounted=False)]))
    assert not raw["eligible"] and raw["tracked"] == []
    (uncarried,) = classify(post_mm(dst=[video(7, SRC)]))
    assert not uncarried["eligible"] and not uncarried["carried"]
    (replaced,) = classify(post_mm(dst=[video(9, DST, remounted=False)]))
    assert not replaced["eligible"]


def test_a_long_frame_inside_the_jump_window_is_invalid() -> None:
    samples = post_mm()
    first = first_index(samples, 5, "Playing")
    for row in samples[first:]:
        row["rafTs"] += 60.0
        row["t"] += 60.0
    (event,) = classify(samples)
    assert event["invalid"] and event["maxDtMs"] > dx.INVALID_DT_MS
    record = dx.build_record(raw_run(samples))
    assert record["status"] == "invalid"


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
    setup = samples[first_index(samples, 5, "SettingUpScene")]
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
    t = samples[first_index(samples, 5, "Playing")]["t"]
    notes = [{"t": t, "kind": "dom-swap", "detail": {"elId": 7}}, {"t": t, "kind": "reuse-decoder", "detail": {"oldElId": 7}},
             {"t": t, "kind": "facade-error", "detail": "x"}, {"t": 0.0, "kind": "dom-swap", "detail": {"elId": 7}}]
    (event,) = classify(samples, core_events=notes)
    assert [(n["kind"], n["elId"]) for n in event["coreNotes"]] == [("dom-swap", 7), ("reuse-decoder", 7)]


# --- record status -------------------------------------------------------------------------------------------


def test_record_status_follows_served_bytes_continuity_and_events() -> None:
    samples = post_mm()
    assert dx.build_record(raw_run(samples))["status"] == "ok"
    wrong = dx.build_record(raw_run(samples, served=dx.SERVED_SHA256["V7"]))
    assert wrong["status"] == "error" and not wrong["servedShaOk"]
    assert dx.build_record(raw_run(samples, mode="unsupported"))["status"] == "error"
    assert dx.build_record(raw_run(samples, core="0" * 64))["status"] == "error"
    assert dx.build_record(raw_run(samples, error="boom"))["status"] == "error"
    assert dx.build_record(raw_run(post_mm(dst=[video(7, SRC)])))["status"] == "no-events"


def test_parse_loadavg_and_strata() -> None:
    assert dx.parse_loadavg("{ 2.31 12.45 22.60 }") == [2.31, 12.45, 22.6]
    assert dx.parse_loadavg("error: nope") is None
    assert [dx.load_stratum({"loadavg": [x, 0, 0]}) for x in (1.0, 6.0, 30.0)] == ["low", "mid", "high"]
    assert dx.load_stratum({}) is None


# --- controls ------------------------------------------------------------------------------------------------


def control_run(mode: str, *, absent_ticks: int, absent_paints: int, same_delivery: bool = False) -> dict[str, Any]:
    """The control removes the decoder after frame 20's paint and re-inserts it after the paint `absent_ticks` frames later."""
    samples = timeline([(5, "Playing", 1000.0, [video(7, DST)])])
    remove_at = 20
    t_remove = samples[remove_at]["t"] + 10.0
    prepaint = prepaint_of(samples)
    for i in range(remove_at + 1, remove_at + 1 + absent_ticks):
        samples[i]["videos"] = []
    for i in range(remove_at + 1, remove_at + 1 + absent_paints):
        prepaint[i] = {**prepaint[i], "n": 0, "ids": []}
    t_reinsert = t_remove if same_delivery else samples[remove_at + absent_ticks]["t"] + 12.0
    ctl = {"mode": mode, "fired": True, "armedElId": 7, "tRemove": t_remove, "tReinsert": t_reinsert}
    lifecycle = [{"t": t_remove + 0.1, "op": "remove", "elId": 7, "isConnected": False},
                 {"t": t_reinsert + 0.1, "op": "add", "elId": 7}]
    return raw_run(samples, prepaint, lifecycle, control=mode, instrument_control=ctl)


def test_null_control_passes_with_no_empty_frame_and_one_delivery() -> None:
    verdict = dx.score_control(control_run("null", absent_ticks=0, absent_paints=0, same_delivery=True), [])
    assert verdict["status"] == "pass", verdict["reasons"]


def test_null_control_fails_when_anything_flags() -> None:
    verdict = dx.score_control(control_run("null", absent_ticks=1, absent_paints=0), [])
    assert verdict["status"] == "fail"


def test_positive_control_passes_when_samples_and_pre_paint_both_see_two_frames() -> None:
    verdict = dx.score_control(control_run("positive", absent_ticks=2, absent_paints=2), [])
    assert verdict["status"] == "pass", verdict["reasons"]
    assert verdict["ticksBetween"] == 2 and verdict["sampleAbsentFrames"] == 2 and verdict["prepaintAbsentFrames"] == 2


def test_positive_control_fails_when_pre_paint_misses_the_hole() -> None:
    verdict = dx.score_control(control_run("positive", absent_ticks=2, absent_paints=0), [])
    assert verdict["status"] == "fail"


def test_a_control_that_never_fired_fails() -> None:
    raw = control_run("positive", absent_ticks=2, absent_paints=2)
    raw["instrument"]["control"] = {"mode": "positive", "fired": False}
    assert dx.score_control(raw, [])["status"] == "fail"


def test_timeout0_is_recorded_with_agreement() -> None:
    verdict = dx.score_control(control_run("timeout0", absent_ticks=1, absent_paints=1), [])
    assert verdict["status"] == "recorded" and verdict["agree"] is True


@pytest.mark.parametrize(("variant", "waited", "status"), [
    ("V8", False, "pass"), ("V8", True, "fail"), ("V7", True, "pass"), ("V7", False, "fail"),
    ("V5", True, "pass"), ("off", True, "pass"), ("V5+8", False, "pass"),
])
def test_r8_flag_control(variant: str, waited: bool, status: str) -> None:
    raw = raw_run(post_mm(waited=waited), variant=variant, control="r8flag")
    record = dx.build_record(raw)
    assert record["controlVerdict"]["status"] == status


# --- blocks, resume, summary ---------------------------------------------------------------------------------


def test_block_plan_is_seeded_permuted_and_rotates_decks() -> None:
    plan = dx.block_plan(1234, 9)
    assert plan == dx.block_plan(1234, 9)
    assert [b["deck"] for b in plan] == ["D4", "D1", "D6"] * 3
    assert all(sorted(b["order"]) == sorted(dx.BLOCK_VARIANTS) for b in plan)
    assert len({tuple(b["order"]) for b in plan}) > 1
    assert [b["order"] for b in plan] != [b["order"] for b in dx.block_plan(4321, 9)]
    assert dx.block_plan(1234, 12)[:9] == plan


def test_pending_runs_resume_and_retake_invalid() -> None:
    plan = dx.block_plan(7, 2)
    first, second = plan[0]["order"][:2]
    records = [
        {"seed": 7, "block": 0, "variant": first, "status": "ok"},
        {"seed": 7, "block": 0, "variant": second, "status": "invalid"},
        {"seed": 99, "block": 0, "variant": plan[0]["order"][2], "status": "ok"},
    ]
    todo = dx.pending_runs(plan, records, 7, max_attempts=3)
    assert [(r["block"], r["variant"], r["attempt"]) for r in todo[:2]] == [(0, second, 2), (0, plan[0]["order"][2], 1)]
    assert len(todo) == 5
    records += [{"seed": 7, "block": 0, "variant": second, "status": "error"}] * 2
    assert all((r["block"], r["variant"]) != (0, second) for r in dx.pending_runs(plan, records, 7, max_attempts=3))


def test_read_jsonl_skips_a_torn_last_line(tmp_path: Path) -> None:
    path = tmp_path / "runs.jsonl"
    dx.append_jsonl(path, {"a": 1})
    with path.open("a") as handle:
        handle.write('{"b": ')
    assert dx.read_jsonl(path) == [{"a": 1}]


def test_fisher_one_sided_matches_the_plans_numbers() -> None:
    assert dx.fisher_one_sided(5, 30, 0, 30) == pytest.approx(0.0261, abs=5e-4)
    assert dx.fisher_one_sided(6, 30, 0, 30) == pytest.approx(0.0119, abs=5e-4)
    assert dx.fisher_one_sided(0, 30, 0, 30) == 1.0
    assert dx.fisher_one_sided(0, 30, 5, 30) == 1.0
    assert dx.fisher_one_sided(3, 10, 3, 10) > 0.5


def _block_record(block: int, variant: str, blinks: int, events: int, *, seed: int = 1, phase: str = "late") -> dict[str, Any]:
    return {
        "seed": seed, "block": block, "variant": variant, "deck": "D4", "status": "ok", "meta": {"loadavg": [2.0, 2.0, 2.0]},
        "events": [
            {"eligible": True, "blink": i < blinks, "blinkSamples": i < blinks, "blinkPrepaint": i < blinks,
             "blinkDecoder": i < blinks, "waited": variant != "V8", "teardown": {"phase": phase}}
            for i in range(events)
        ],
    }


def test_summary_early_stop_needs_fifteen_blocks_and_six_v8_blinks() -> None:
    records = [_block_record(b, v, int(v == "V8" and b < 6), 2) for b in range(15) for v in dx.BLOCK_VARIANTS]
    summary = dx.summarize(records, 1)
    assert summary["completeBlocks"] == 15 and summary["decision"] == "early-stop"
    assert summary["perVariant"]["V8"]["blinks"] == 6 and summary["perVariant"]["V8"]["events"] == 30
    assert summary["perVariant"]["V8"]["byPath"] == {"direct": [30, 6]}
    assert summary["perVariant"]["V8"]["byPhase"] == {"late": [30, 6]}
    assert summary["fisherOneSided"]["V8vsV7"] == pytest.approx(dx.fisher_one_sided(6, 30, 0, 30))
    assert dx.summarize(records[:-3], 1)["decision"] == "continue"


def test_summary_futility_and_target() -> None:
    futile = [_block_record(b, v, int(v == "V8" and b < 2), 2) for b in range(15) for v in dx.BLOCK_VARIANTS]
    assert dx.summarize(futile, 1)["decision"] == "futility"
    met = [_block_record(b, v, int(b < 4), 2) for b in range(15) for v in dx.BLOCK_VARIANTS]
    assert dx.summarize(met, 1)["decision"] == "target-met"


def test_summary_counts_one_done_record_per_slot_and_ignores_other_records() -> None:
    records = [
        {**_block_record(0, "V8", 0, 1), "status": "invalid"},
        _block_record(0, "V8", 1, 1),
        _block_record(0, "V8", 0, 1),
        {"runId": "control", "block": None, "variant": "V8", "status": "ok", "events": []},
    ]
    summary = dx.summarize(records, 1)
    assert summary["perVariant"]["V8"]["runs"] == 1 and summary["perVariant"]["V8"]["blinks"] == 1
    assert summary["statuses"] == {"invalid": 1, "ok": 2}
    assert summary["decision"] == "n/a"
