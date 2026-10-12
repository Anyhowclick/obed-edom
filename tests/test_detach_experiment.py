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
from unittest.mock import ANY

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
    pinned = live_runtime._pinned
    with dx.serving("V7"):
        assert live_runtime._MM_OPACITY_REPLACEMENTS == tuple(original[:7])
        assert dx.os.environ[live_runtime.MM_OPACITY_ENV] == "auto"
        # The variant's bytes are not the product's pinned digest; the experiment pins them itself.
        assert live_runtime._pinned(b"unpinned", "0" * 64) == b"unpinned"
    assert live_runtime._MM_OPACITY_REPLACEMENTS is original
    assert live_runtime._pinned is pinned
    with dx.serving("off"):
        assert live_runtime._MM_OPACITY_REPLACEMENTS is original
        assert dx.os.environ[live_runtime.MM_OPACITY_ENV] == "off"
    assert live_runtime.MM_OPACITY_ENV not in dx.os.environ


def _synthetic_player() -> bytes:
    return b"\n".join([live_runtime._ANCHOR, *(before for before, _ in live_runtime._MM_OPACITY_REPLACEMENTS)])


@pytest.mark.parametrize("variant", ["V8", "V7", "V5", "V5+8"])
def test_served_sha_is_the_sha_of_exactly_the_variants_replacements(monkeypatch, variant: str) -> None:
    player = _synthetic_player()
    monkeypatch.setitem(live_runtime.SUPPORTED_PLAYERS, hashlib.sha256(player).hexdigest(), (ANY,) * 3)
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


# --- Level 2: served bytes and core trace (plan §1 Level 2) ------------------------------------------------------


def test_level2_install_exposes_the_controller_inside_the_hook_only() -> None:
    patched = dx.level2_install_bytes()
    assert patched.count(b"Object.defineProperty(window, '__obedDebugController', {value: controller});") == 1
    assert patched.replace(dx.L2_INSTALL_REPLACEMENT, dx.L2_INSTALL_ANCHOR) == live_runtime._INSTALL
    with pytest.raises(ValueError, match="install hook anchor"):
        dx.level2_install_bytes(live_runtime._INSTALL.replace(dx.L2_INSTALL_ANCHOR, b"(function(c) {\n"))


def test_level2_install_patches_only_inside_the_context_and_restores() -> None:
    original = live_runtime._INSTALL
    with dx.level2_install():
        assert live_runtime._INSTALL == dx.level2_install_bytes(original)
    assert live_runtime._INSTALL is original


def test_level2_served_sha_differs_from_level1_by_exactly_the_install(monkeypatch) -> None:
    player = _synthetic_player()
    monkeypatch.setitem(live_runtime.SUPPORTED_PLAYERS, hashlib.sha256(player).hexdigest(), (ANY,) * 3)
    with dx.serving("V8"), dx.level2_install():
        served = live_runtime.patch_player(player)
    assert b"__obedDebugController" in served
    assert dx.served_sha256(player, "V8", level2=True) == hashlib.sha256(served).hexdigest()
    assert dx.served_sha256(player, "V8", level2=True) != dx.served_sha256(player, "V8")


def test_level2_served_shas_are_distinct_and_never_a_level1_sha() -> None:
    assert set(dx.L2_SERVED_SHA256) == set(dx.SERVINGS)
    assert len(set(dx.L2_SERVED_SHA256.values())) == len(dx.SERVINGS)
    assert not set(dx.L2_SERVED_SHA256.values()) & set(dx.SERVED_SHA256.values())
    assert dx.expected_served_sha256("V8") == dx.SERVED_SHA256["V8"]
    assert dx.expected_served_sha256("V8", level2=True) == dx.L2_SERVED_SHA256["V8"]


@pytest.mark.skipif(not _PLAYER.is_file(), reason="qual-decks fixture is not in this checkout")
@pytest.mark.parametrize("variant", dx.SERVINGS)
def test_planned_level2_served_shas_match_the_pinned_player(variant: str) -> None:
    assert dx.served_sha256(_PLAYER.read_bytes(), variant, level2=True) == dx.L2_SERVED_SHA256[variant]


CORE_ANCHORS = [anchor for anchor, _ in dx._CORE_TRACE_TRANSFORMS]


@pytest.mark.parametrize("anchor", CORE_ANCHORS)
def test_each_core_anchor_occurs_exactly_once_in_todays_core(anchor: str) -> None:
    from obed_edom.live_continuity_js import PRESERVE_CORE_JS
    assert PRESERVE_CORE_JS.count(anchor) == 1


@pytest.mark.parametrize("anchor", CORE_ANCHORS)
def test_a_core_without_an_anchor_raises_naming_it(anchor: str) -> None:
    from obed_edom.live_continuity_js import PRESERVE_CORE_JS
    with pytest.raises(ValueError) as caught:
        dx.experiment_core(True, PRESERVE_CORE_JS.replace(anchor, ""))
    assert "core trace" in str(caught.value)


def test_the_plain_core_is_the_shipped_core_and_the_trace_has_its_own_sha() -> None:
    from obed_edom.live_continuity_js import PRESERVE_CORE_JS
    assert dx.experiment_core() == PRESERVE_CORE_JS and dx.experiment_core_sha() == dx.CORE_SHA256
    assert dx.experiment_core_sha(True) != dx.CORE_SHA256


def _undo(core: str, transforms) -> str:
    for anchor, replacement in reversed(transforms):
        assert core.count(replacement) == 1
        core = core.replace(replacement, anchor)
    return core


def test_the_trace_is_a_pure_insertion() -> None:
    """Undoing the trace's replacements gives back the untraced core byte for byte, so the trace adds only its
    wrappers and helpers (identical text in every arm) and changes no branch."""
    traced = dx.experiment_core(trace=True)
    assert _undo(traced, dx._CORE_TRACE_TRANSFORMS) == dx.experiment_core()
    for snippet in (dx._TRACE_HELPERS, dx._SCHEDULE_TRACE, dx._TRY_REMOUNT_TRACE):
        assert traced.count(snippet) == 1


def test_injected_core_serves_the_trace_and_restores_the_host() -> None:
    host = probe.live_host_module
    original_core, original_sha = host.PRESERVE_CORE_JS, host.js_sha256
    with dx.injected_core(True) as sha:
        assert host.PRESERVE_CORE_JS == dx.experiment_core(True) and host.js_sha256() == sha
        assert sha == dx.experiment_core_sha(True)
    assert host.PRESERVE_CORE_JS is original_core and host.js_sha256 is original_sha


def test_level2_sampler_adds_the_page_wraps_and_sequences_i2() -> None:
    js = dx.instrumented_sampler_js(None, level2=True)
    assert '{"control": null, "level2": true}' in js and js.count(dx.LEVEL2_JS) == 1
    assert js.index("window.__obedDetachInstr__ = instr") < js.index("window.__obedDetachL2__ = l2")
    level1 = dx.instrumented_sampler_js(None)
    assert '{"control": null}' in level1 and "__obedDetachL2__ = l2" not in level1
    for name in ("'loadScene'", "'isScenePreloaded'", "'processTextureDidLoadCallback'", "'jumpToScene_partFour'",
                 "'renderEvent'", "'animateEffects'", "'removeChild'"):
        assert name in dx.LEVEL2_JS


# --- Level 2 classification (plan §4 step 3) ---------------------------------------------------------------------


def lc(t: float, op: str, connected: bool, *, remounting: bool = False, layer: str = "layer1", seq=None, el: int = 7):
    row = {"t": t, "rafTs": 990.0, "op": op, "elId": el, "isConnected": connected, "remounting": remounting,
           "parentId": layer, "layerId": layer}
    if seq is not None:
        row["seq"] = seq
    return row


def note(t: float, kind: str, **detail):
    return {"t": t, "kind": kind, "detail": {"elId": 7, **detail}}


def blink_event(t0: float = 1006.0) -> dict[str, Any]:
    return {"tracked": [7], "tSetup": 900.0, "tPlay": 1004.0, "blink": True, "blinkDecoder": True,
            "prepaintEmptyRuns": [{"t0": t0, "t1": t0, "frames": 1}], "prepaintDecoderAbsentRuns": [{"t0": t0, "t1": t0, "frames": 1}]}


def gap_raw(lifecycle, notes=(), trace=(), l2rows=None, prepaint=None) -> dict[str, Any]:
    raw = {"instrument": {"lifecycle": list(lifecycle), "prepaint": prepaint or [{"t": 1006.0, "n": 0, "ids": []}]},
           "coreEvents": list(notes), "coreTrace": list(trace)}
    if l2rows is not None:
        raw["level2"] = {"rows": l2rows}
    return raw


# The live signature (Session 2, every eligible event): the teardown detaches the decoder, the core re-homes it in
# the same delivery into the outgoing slide's poster layer, the next delivery removes that layer, and the stash
# returns on `__obedRemounting` (set by the re-home's own move); the carry's dom-swap brings it back.
H3_LIFECYCLE = [lc(1000.0, "remove", True, remounting=True, layer="layer87"), lc(1000.0, "add", True, remounting=True, layer="layer107"),
                lc(1001.0, "remove", False, remounting=True, layer="layer105"), lc(1008.0, "add", True, remounting=True, layer="layer113")]
H3_NOTES = [note(999.5, "preserve-on-detach-subtree"), note(999.5, "remount-scheduled", why="preserve-on-detach-subtree"),
            note(1000.0, "remount-into-authored-layer", inDocument=True), note(1007.0, "reuse-decoder", oldElId=7),
            note(1007.5, "dom-swap")]


def test_the_live_signature_is_h3_then_h1_from_level1_alone() -> None:
    verdict = dx.classify_event(blink_event(), gap_raw(H3_LIFECYCLE, H3_NOTES))
    assert (verdict["hypothesis"], verdict["then"], verdict["basis"]) == ("H3", "H1", "inferred")
    (gap,) = verdict["gaps"]
    assert gap["t0"] == 1001.0 and gap["t1"] == 1008.0 and gap["gapMs"] == 7.0 and gap["paintsInGap"] == 1
    assert gap["prior"]["sameFrame"] and gap["prior"]["layerId"] == "layer87"
    assert gap["readd"]["layerId"] == "layer113"


def test_without_an_earlier_rehome_the_swallowed_detach_is_h1() -> None:
    lifecycle = [lc(1001.0, "remove", False, remounting=True), lc(1008.0, "add", True)]
    verdict = dx.classify_event(blink_event(), gap_raw(lifecycle))
    assert (verdict["hypothesis"], verdict["then"]) == ("H1", None)


def test_the_trace_names_the_guard_and_overrides_the_inference() -> None:
    lifecycle = [lc(1001.0, "remove", False, remounting=False), lc(1008.0, "add", True)]
    stash = {"t": 1001.0, "kind": "stash", "elId": 7, "why": "preserve-on-detach-subtree", "noted": [],
             "pre": {"remounting": True, "detached": None, "assetKey": True, "planAsset": True, "poolable": True,
                     "readyState": 4, "gen": 0, "generation": 0}}
    verdict = dx.classify_event(blink_event(), gap_raw(lifecycle, trace=[stash]))
    assert (verdict["hypothesis"], verdict["basis"]) == ("H1", "trace")


H2_LIFECYCLE = [lc(1001.0, "remove", False), lc(1008.0, "add", True)]
H2_NOTES = [note(1001.0, "preserve-on-detach-subtree"), note(1001.0, "remount-scheduled", why="preserve-on-detach-subtree"),
            note(1001.0, "remount-footprint-rect")]


def test_pooled_and_scheduled_but_still_disconnected_is_h2() -> None:
    verdict = dx.classify_event(blink_event(), gap_raw(H2_LIFECYCLE, H2_NOTES))
    assert (verdict["hypothesis"], verdict["basis"]) == ("H2", "notes")
    assert verdict["gaps"][0]["scheduled"] == 1
    stash = {"t": 1001.0, "kind": "stash", "elId": 7, "why": "preserve-on-detach-subtree",
             "noted": ["preserve-on-detach-subtree", "remount-scheduled"], "pre": {}}
    bail = {"t": 1001.0, "kind": "tryRemount", "elId": 7, "after": False, "state": {"stageMap": False}}
    verdict = dx.classify_event(blink_event(), gap_raw(H2_LIFECYCLE, H2_NOTES, trace=[stash, bail]))
    assert (verdict["hypothesis"], verdict["basis"]) == ("H2", "trace")
    assert verdict["gaps"][0]["tryRemount"] == [{"t": 1001.0, "kind": "tryRemount", "after": False, "state": {"stageMap": False}}]


def test_with_the_trace_on_a_missing_stash_row_is_not_inferred() -> None:
    bail = {"t": 1001.0, "kind": "tryRemount", "elId": 7, "after": False}
    verdict = dx.classify_event(blink_event(), gap_raw(H2_LIFECYCLE, H2_NOTES, trace=[bail]))
    assert verdict["hypothesis"] == "unknown" and verdict["reason"] == "stash unseen (trace)"


def test_a_carry_rehome_schedule_is_not_a_detach_remount() -> None:
    lifecycle = [lc(1001.0, "remove", False), lc(1008.0, "add", True)]
    notes = [note(1001.0, "preserve-on-detach-subtree"), note(1007.5, "remount-scheduled", why="pin-rehome")]
    verdict = dx.classify_event(blink_event(), gap_raw(lifecycle, notes))
    assert verdict["hypothesis"] == "unknown" and verdict["reason"] == "pooled, no detach remount scheduled"


def test_a_core_retire_in_the_removals_delivery_is_h4_even_after_a_rehome() -> None:
    notes = [*H3_NOTES, {"t": 1001.0, "kind": "retire-boundary", "detail": {"elIds": [7], "atScene": 5}}]
    assert dx.classify_event(blink_event(), gap_raw(H3_LIFECYCLE, notes))["hypothesis"] == "H4"
    l2 = [{"t": 1000.9, "kind": "dom-removeChild", "elIds": [7], "by": ["retireDecoder (index.html:1:2)", "sweepRetireZone"]}]
    verdict = dx.classify_event(blink_event(), gap_raw(H3_LIFECYCLE, H3_NOTES, l2rows=l2))
    assert verdict["hypothesis"] == "H4" and verdict["reason"] == "remover retireDecoder"


def test_a_player_remover_stack_is_recorded_but_does_not_change_the_branch() -> None:
    l2 = [{"t": 1000.9, "kind": "dom-removeChild", "elIds": [7], "by": ["removeEvent (main.js:1:2291990)"]},
          {"t": 999.0, "kind": "renderEvent-start", "scene": 5}, {"t": 1002.0, "kind": "renderEvent-end", "scene": 5}]
    verdict = dx.classify_event(blink_event(), gap_raw(H3_LIFECYCLE, H3_NOTES, l2rows=l2))
    assert (verdict["hypothesis"], verdict["then"]) == ("H3", "H1")
    gap = verdict["gaps"][0]
    assert gap["remover"]["by"] == ["removeEvent (main.js:1:2291990)"]
    assert [row["kind"] for row in gap["player"]] == ["renderEvent-start", "renderEvent-end"]


def test_an_unexplained_removal_is_unknown_with_its_reason() -> None:
    lifecycle = [lc(1001.0, "remove", False), lc(1008.0, "add", True)]
    verdict = dx.classify_event(blink_event(), gap_raw(lifecycle))
    assert verdict["hypothesis"] == "unknown" and verdict["reason"] == "stash unseen (inferred)"


def test_a_blink_outside_every_gap_is_unknown() -> None:
    verdict = dx.classify_event(blink_event(t0=1020.0), gap_raw(H3_LIFECYCLE, H3_NOTES))
    assert verdict["hypothesis"] == "unknown" and "covers" in verdict["reason"]
    assert len(verdict["gaps"]) == 1


def test_a_non_blink_reports_its_gaps_without_a_hypothesis() -> None:
    event = {**blink_event(), "blink": False, "blinkDecoder": False}
    verdict = dx.classify_event(event, gap_raw(H3_LIFECYCLE, H3_NOTES, prepaint=[{"t": 1010.0, "n": 1, "ids": [7]}]))
    assert verdict["hypothesis"] is None and verdict["gaps"][0]["hypothesis"] == "H3"
    assert verdict["gaps"][0]["paintsInGap"] == 0


def test_the_shared_sequence_orders_rows_whose_times_tie() -> None:
    """With coarse timers the core's stash row can read the same `t` as the previous I2 row; the sequence still puts
    it inside the removal's delivery."""
    lifecycle = [lc(1000.0, "add", True, seq=10), lc(1000.0, "remove", False, seq=13), lc(1008.0, "add", True, seq=20)]
    stash = {"t": 1000.0, "seq": 12, "kind": "stash", "elId": 7, "why": "preserve-on-detach", "noted": ["preserve-on-detach"],
             "pre": {}}
    notes = [note(1000.0, "remount-scheduled", why="preserve-on-detach")]
    verdict = dx.classify_event(blink_event(), gap_raw(lifecycle, notes, trace=[stash]))
    assert verdict["gaps"][0]["stash"] == "pooled"
    late = {**stash, "seq": 14}
    assert dx.classify_event(blink_event(), gap_raw(lifecycle, notes, trace=[late]))["gaps"][0]["stash"] == "unseen"


@pytest.mark.parametrize(("pre", "noted", "reason"), [
    ({"remounting": True, "detached": None}, [], "remounting"),
    ({"remounting": True, "detached": False}, [], "remounting"),
    ({"remounting": True, "detached": True, "assetKey": True, "planAsset": True, "poolable": True, "readyState": 4},
     ["preserve-on-detach"], "pooled"),
    ({"facade": True, "assetKey": True}, [], "facade"),
    ({"gen": -1, "generation": 0}, [], "retired"),
    ({"gen": 0, "generation": 1, "assetKey": True}, [], "stale-gen"),
    ({"assetKey": True, "planAsset": False}, [], "not-plan-asset"),
    ({"assetKey": True, "planAsset": True, "poolable": True}, ["preserve-refused"], "zone-refused"),
    ({"assetKey": True, "planAsset": True, "poolable": False}, [], "not-poolable"),
    ({"assetKey": True, "planAsset": True, "poolable": True, "readyState": 1, "currentTime": 0.0}, [], "not-ready"),
    ({"assetKey": True, "planAsset": True, "poolable": True, "readyState": 4}, [], "unknown"),
    (None, [], "not-video"),
])
def test_stash_reason_mirrors_the_guard_order(pre, noted, reason: str) -> None:
    assert dx.stash_reason({"why": "preserve-on-detach", "pre": pre, "noted": noted}) == reason


def test_a_record_carries_the_blinks_hypothesis() -> None:
    samples = post_mm()
    first = first_index(samples, 5, "Playing")
    samples[first]["videos"] = []
    prepaint = prepaint_of(samples, frozenset({first}))
    t_hole = prepaint[first]["t"]
    lifecycle = [lc(t_hole - 5.0, "remove", False, remounting=True), lc(t_hole + 5.0, "add", True)]
    record = dx.build_record(raw_run(samples, prepaint, lifecycle))
    (event,) = record["events"]
    assert event["blink"] and event["hypothesis"] == {"hypothesis": "H1", "then": None,
                                                       "reason": "stash returned on __obedRemounting (inferred)",
                                                       "basis": "inferred"}
    rows = dx.classification_rows(record, raw_run(samples, prepaint, lifecycle))
    assert len(rows) == 1 and rows[0]["hypothesis"] == "H1"
    assert dx.tally_classification(rows)["V8"]["hypotheses"] == {"H1": 1}


def test_a_level2_record_without_level2_data_is_an_error() -> None:
    raw = raw_run(post_mm())
    raw["config"].update(level2=True, expectedServedSha256=dx.SERVED_SHA256["V8"])
    record = dx.build_record(raw)
    assert record["status"] == "error" and any("level 2" in r for r in record["reasons"])
    raw["level2"] = {"rows": [], "errors": [], "wrapped": ["loadScene"]}
    raw["coreTrace"] = [{"t": 1.0, "kind": "stash"}]
    assert dx.build_record(raw)["status"] == "ok"


def test_records_check_the_configured_core_and_served_shas() -> None:
    raw = raw_run(post_mm(), served=dx.L2_SERVED_SHA256["V8"], core=dx.experiment_core_sha(True))
    raw["config"].update(serving="V8", variant="V8",
                         expectedServedSha256=dx.L2_SERVED_SHA256["V8"], expectedCoreSha256=dx.experiment_core_sha(True))
    raw.update(level2={"rows": [], "errors": [], "wrapped": []}, coreTrace=[{"t": 1.0}])
    raw["config"]["level2"] = True
    record = dx.build_record(raw)
    assert record["servedShaOk"] and record["coreShaOk"] and record["status"] == "ok"
    raw["output"]["continuity"]["sha256"] = dx.CORE_SHA256
    assert dx.build_record(raw)["status"] == "error"


def test_level2_r8_flag_needs_the_preload_log_to_agree() -> None:
    samples = post_mm(waited=False)
    (jump,) = dx.post_mm_jumps(samples)
    assert jump["tMmIdle"] < jump["tMmSetup"] < jump["tSetup"]
    preload = {"t": jump["tMmIdle"] + 10.0, "kind": "loadScene", "scene": jump["scene"], "viaPreload": True, "prevIsMM": True}
    raw = raw_run(samples, variant="V8", control="r8flag")
    raw["level2"] = {"installedAt": 0.0, "rows": [preload]}
    assert dx.build_record(raw)["controlVerdict"]["status"] == "pass"
    raw["level2"] = {"installedAt": 0.0, "rows": []}
    verdict = dx.build_record(raw)["controlVerdict"]
    assert verdict["status"] == "fail" and verdict["l2Preload"] == [False]
    raw["level2"] = {"installedAt": jump["tMmIdle"] + 1.0, "rows": [preload]}
    assert dx.build_record(raw)["controlVerdict"]["l2Preload"] == [None]
    stock = raw_run(post_mm(waited=True), variant="V7", control="r8flag")
    stock["level2"] = {"installedAt": 0.0, "rows": []}
    assert dx.build_record(stock)["controlVerdict"]["status"] == "pass"


def test_summary_tallies_blink_hypotheses() -> None:
    record = _block_record(0, "V8", 2, 2)
    record["events"][0]["hypothesis"] = {"hypothesis": "H3", "then": "H1"}
    record["events"][1]["hypothesis"] = {"hypothesis": "H2", "then": None}
    assert dx.summarize([record], 1)["perVariant"]["V8"]["byHypothesis"] == {"H3>H1": 1, "H2": 1}


def test_blocks_accept_level2_and_refuse_the_retired_fix_arms(tmp_path: Path) -> None:
    args = dx.parse_args(["blocks", "--out-dir", str(tmp_path), "--blocks", "2", "--variants", "V8,V5+8", "--level2"])
    assert args.variants == ["V8", "V5+8"] and args.level2
    with pytest.raises(SystemExit):
        dx.parse_args(["blocks", "--out-dir", str(tmp_path), "--blocks", "2", "--variants", "V8,V8+a1"])
    with pytest.raises(SystemExit):
        dx.parse_args(["run", "--out-dir", str(tmp_path), "--variant", "V8", "--deck", "D4", "--core-fix", "a1"])


def test_the_first_destination_paint_at_the_pin_is_reported() -> None:
    samples = post_mm()
    prepaint = prepaint_of(samples)
    first = first_index(samples, 5, "Playing")
    prepaint[first]["pins"] = [{"atScene": 4, "top": ["canvas#x"], "videoAt": []},
                               {"atScene": 5, "top": ["video:7", "canvas#y"], "videoAt": [7]}]
    (event,) = classify(samples, prepaint=prepaint)
    assert event["pinPaint"] == {"t": prepaint[first]["t"], "top": ["video:7", "canvas#y"], "videoAt": [7], "decoderAtPin": True}
    prepaint[first]["pins"][1]["videoAt"] = [9]
    (event,) = classify(samples, prepaint=prepaint)
    assert event["pinPaint"]["decoderAtPin"] is False


# --- detach gaps by phase: same delivery / same checkpoint (owner decision 2026-10-10: a1 is the fix) -------------


def test_i2_numbers_its_deliveries_and_reads_connectivity_after_the_round() -> None:
    """The post-round read is a microtask queued inside I2's callback: it runs after every observer of the same
    notify round (the facade observers are created later, so they are delivered after I2) and before any rendering."""
    js = dx.instrumented_sampler_js(None)
    assert "delivery = ++deliveries" in js and "t: t, delivery: delivery, rafTs:" in js
    assert "queueMicrotask(function(){\n        seen.forEach(function(p){ p[0].connectedAfterRound = p[1].isConnected; });" in js


# V8: the teardown's second removal is swallowed and comes back only at the carry's dom-swap, a task later.
V8_EVENT = {"tracked": [7], "tSetup": 900.0, "tPlay": 1004.0}
V8_LIFECYCLE = [*H3_LIFECYCLE[:3], lc(1007.2, "add", True, el=8, layer="layer113"), lc(1008.0, "add", True, layer="layer113")]

# a1: the teardown removal is re-homed inside the core's own delivery; the carry task then removes the outgoing layer
# with the (now held) decoder in it, in the same delivery that inserts the facade stub, and the facade observer swaps it
# back in the next round of that checkpoint.
A1_LIFECYCLE = [lc(1000.0, "remove", True, remounting=True, layer="layer105"), lc(1000.0, "add", True, remounting=True, layer="layer110"),
                lc(1008.0, "add", True, el=8, layer="layer113"), lc(1008.0, "remove", False, layer="layer105"),
                lc(1008.9, "remove", False, el=8, remounting=True, layer="layer113"), lc(1008.9, "add", True, remounting=True, layer="layer113")]
A1_NOTES = [note(999.5, "preserve-on-detach-subtree"), note(999.5, "remount-into-authored-layer", inDocument=True),
            note(1007.0, "reuse-decoder", oldElId=7, newElId=8), note(1008.4, "dom-swap")]


def test_v8_teardown_gap_crosses_a_delivery_and_a_paint() -> None:
    raw = gap_raw(V8_LIFECYCLE, [*H3_NOTES[:3], note(1007.0, "reuse-decoder", oldElId=7, newElId=8), note(1007.5, "dom-swap")],
                  prepaint=[{"t": 1005.0, "n": 0, "ids": []}])
    phases = dx.removal_phases(V8_EVENT, raw)
    assert phases["carry"] is None
    assert phases["teardown"] == {"removals": 2, "sameDelivery": False, "sameCheckpoint": False, "basis": ["proxy"],
                                  "gapMs": 7.0, "paintsInGap": 1, "domSwapAfterMs": 6.5}


def test_a1_teardown_is_same_delivery_and_the_carry_removal_same_checkpoint() -> None:
    phases = dx.removal_phases(V8_EVENT, gap_raw(A1_LIFECYCLE, A1_NOTES, prepaint=[{"t": 1010.0, "n": 1, "ids": [7]}]))
    assert phases["teardown"] == {"removals": 1, "sameDelivery": True, "sameCheckpoint": True, "basis": ["delivery"],
                                  "gapMs": 0.0, "paintsInGap": 0, "domSwapAfterMs": None}
    assert phases["carry"] == {"removals": 1, "sameDelivery": False, "sameCheckpoint": True, "basis": ["proxy"],
                               "gapMs": 0.9, "paintsInGap": 0, "domSwapAfterMs": 0.4}


def test_the_proxy_refuses_an_intervening_delivery_a_new_frame_or_a_paint() -> None:
    def carry(lifecycle, prepaint=None):
        raw = gap_raw(lifecycle, A1_NOTES, prepaint=prepaint or [{"t": 1010.0, "n": 1, "ids": [7]}])
        return dx.removal_phases(V8_EVENT, raw)["carry"]["sameCheckpoint"]

    assert carry(A1_LIFECYCLE)
    assert not carry([*A1_LIFECYCLE[:4], lc(1008.5, "add", True, el=9), *A1_LIFECYCLE[4:]])
    assert not carry([*A1_LIFECYCLE[:5], {**A1_LIFECYCLE[5], "rafTs": 1006.0}])
    assert not carry(A1_LIFECYCLE, prepaint=[{"t": 1008.5, "n": 0, "ids": []}])
    assert not carry(A1_LIFECYCLE[:5])


def test_the_observed_post_round_read_overrides_the_proxy_and_deliveries_split_tied_times() -> None:
    observed = [dict(row, delivery=i) for i, row in enumerate(A1_LIFECYCLE)]
    observed[3]["connectedAfterRound"] = True
    phases = dx.removal_phases(V8_EVENT, gap_raw(observed, A1_NOTES))
    assert phases["carry"]["sameCheckpoint"] and phases["carry"]["basis"] == ["observed"]
    observed[3]["connectedAfterRound"] = False
    assert not dx.removal_phases(V8_EVENT, gap_raw(observed, A1_NOTES))["carry"]["sameCheckpoint"]
    tied = [dict(row, delivery=1 if row["t"] < 1008.0 else 2 if row["t"] == 1008.0 else 3) for row in A1_LIFECYCLE]
    tied[4]["t"] = tied[5]["t"] = 1008.0
    assert dx.removal_phases(V8_EVENT, gap_raw(tied, A1_NOTES))["carry"]["sameCheckpoint"]
    tied.insert(4, lc(1008.0, "add", True, el=9) | {"delivery": 5})
    assert not dx.removal_phases(V8_EVENT, gap_raw(tied, A1_NOTES))["carry"]["sameCheckpoint"]


def test_records_summary_and_classify_print_the_readout() -> None:
    a1 = dx.removal_phases(V8_EVENT, gap_raw(A1_LIFECYCLE, A1_NOTES))
    records = [_block_record(b, arm, 0, 1) for b in range(2) for arm in ("V8", "V8+a1")]
    for record in records:
        if record["variant"] == "V8+a1":
            record["events"][0]["removals"] = a1
    summary = dx.summarize(records, 1)
    assert summary["readout"] == [
        "V8: teardown sameDelivery 0/0; carry sameDelivery 0/0; pre-paint in gap 0",
        "V8+a1: teardown sameDelivery 2/2; carry sameDelivery 0/2, sameCheckpoint 2/2 (proxy), gapMs max 0.9; "
        "pre-paint in gap 0",
    ]
    rows = [{"variant": "V8+a1", "removals": a1}] * 2
    assert dx.tally_classification(rows)["V8+a1"]["removals"] == summary["perVariant"]["V8+a1"]["removals"]


def test_build_record_attaches_the_phases_to_eligible_events_only() -> None:
    record = dx.build_record(raw_run(post_mm()))
    (event,) = record["events"]
    assert event["eligible"] and event["removals"] == {"teardown": None, "carry": None}
    (ineligible,) = dx.build_record(raw_run(post_mm(dst=[video(7, SRC)])))["events"]
    assert "removals" not in ineligible


def test_rescore_and_classify_write_where_told(tmp_path: Path) -> None:
    out = tmp_path / "rescore" / "runs.rescored.jsonl"
    args = dx.parse_args(["rescore", "--out-dir", str(tmp_path / "evidence"), "--output", str(out)])
    assert args.output == out
    assert dx.parse_args(["classify", "--out-dir", str(tmp_path), "--output", str(out)]).output == out
    assert dx.parse_args(["rescore", "--out-dir", str(tmp_path)]).output is None


def test_a_run_prepares_its_export_inside_its_own_probe_run_scope(monkeypatch, tmp_path) -> None:
    """The S2 rebase (#247) gave `prepare_export` a per-run `root`; a stale call only surfaces live as a
    record error, so bind the driver's call against the real signature and check the scope it runs in."""
    import contextlib
    import inspect

    real = inspect.signature(probe.prepare_export)
    scopes: list[Path] = []
    calls: list[Any] = []

    @contextlib.contextmanager
    def fake_scope(artifact: Path):
        scopes.append(artifact)
        yield tmp_path / "scope"

    def fake_prepare(*args: Any, **kwargs: Any) -> Path:
        calls.append(real.bind(*args, **kwargs).arguments)
        raise RuntimeError("stop after prepare")

    monkeypatch.setattr(dx, "deck_paths", lambda deck: (tmp_path / "fixture", tmp_path / "index.html"))
    monkeypatch.setattr(dx, "collect_metadata", lambda: {})
    monkeypatch.setattr(probe, "run_scope", fake_scope)
    monkeypatch.setattr(probe, "prepare_export", fake_prepare)
    monkeypatch.setattr(probe, "check_no_leftover_chrome", lambda: "")

    out_dir = tmp_path / "out"
    dx.execute_run(out_dir, "run-1", deck="D4", variant="V8", arm="A", viewport=(2560, 1440))

    assert scopes == [out_dir / "run-1"]
    assert calls and calls[0]["root"] == tmp_path / "scope"
    raw = dx.read_jsonl(out_dir / "runs.jsonl")[0]
    assert "stop after prepare" in " ".join(raw.get("reasons") or [])
