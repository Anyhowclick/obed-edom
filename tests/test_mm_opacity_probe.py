"""Synthetic tests for the MO-1 / MO-4 / MO-5 scorers in `scripts/mm_opacity_probe.py`.

No browser, host or export: every run record is built here in the shape the in-page logger and the driver produce.
Each gate must PASS on the patched run, FAIL on each known-bad (patch off, the alpha-squared splice, the patch-off forced
stand-down), and read
INCONCLUSIVE (never PASS) when the instrument's integrity, its control-vs-control or its KB does not hold. A GL-on run where
G2 stands down is VOID.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
_SPEC = importlib.util.spec_from_file_location("mm_opacity_probe", REPO / "scripts" / "mm_opacity_probe.py")
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)

from obed_edom import live_runtime

ALPHA = probe.ALPHA
EFFECT_1_TO_2 = REPO / "tests" / "fixtures" / "live_continuity" / "effect_1_to_2.json"
S_PIXEL = (0, 175, 26, 255)
B_PIXELS = [(0, 0, 0, 0), (10, 20, 30, 128), (40, 60, 20, 255), (0, 0, 0, 0)]
MOVE_FRAMES = 30


def _blend(opacity: float) -> list[int]:
    out = []
    for b in B_PIXELS:
        s = [c / 255 for c in S_PIXEL]
        out += [round((opacity * s[k] + (1 - opacity * s[3]) * b[k] / 255) * 255) for k in range(4)]
    return out


def _frames(label: str, values_per_frame: list[list[float]], progs: list[int], g2: str | None, start: int) -> list[dict]:
    return [
        {"label": label, "ctx": 0, "i": start + n, "el": n * 50.0, "g2": g2, "draws": [[p, v] for p, v in zip(progs, values)], "B": None}
        for n, values in enumerate(values_per_frame)
    ]


def make_run(gl: str = "off", slot_value: float = ALPHA, *, frames: int = MOVE_FRAMES, fade_offset: float = 0.0,
             settle_opacity: float | None = None, hash12: str = "h12", hash34: str = "h34", live_value: float | None = None,
             rest4: float | None = None, unproven: list | None = None, green: int = 60) -> dict[str, Any]:
    g2 = "ARM-PRE" if gl == "auto" else None
    fade = [max(0.0, 1.0 - (n + fade_offset) / (frames - 1)) for n in range(frames)]
    fade[-1] = 0.0
    move = _frames("mm12", [[1, f, 1, 1, slot_value] for f in fade], [0, 1, 2, 3, 4], g2, 0)
    log_frames = list(move)
    if gl == "auto":
        live = ALPHA if live_value is None else live_value
        log_frames += _frames("mm12", [[1, 0, 1, 1, live]] * 10, [0, 1, 2, 3, 4], "LIVE", len(log_frames))
    move34 = _frames("mm34", [[1, 1, 0]] * 25, [5, 6, 7], "RETIRED" if gl == "auto" else None, len(log_frames) + 5)
    log_frames += move34
    opacity = slot_value if settle_opacity is None else settle_opacity
    settle = {
        "mm12": {"frame": move[-1]["i"], "ord": 4, "el": move[-1]["el"], "g2": g2, "B": [c for p in B_PIXELS for c in p],
                 "P": _blend(opacity), "w": 1920, "h": 1080, "hash": hash12, "masks": [[103, 11, 965, 281]]},
        "mm34": {"frame": move34[-1]["i"], "ord": 2, "el": move34[-1]["el"], "g2": move34[-1]["g2"], "B": None, "P": None,
                 "w": 1920, "h": 1080, "hash": hash34},
    }
    run: dict[str, Any] = {
        "gl": gl, "arm": "x",
        "steps": [{"label": "mm12", "expectHash": ["#1", "#2"], "hashBefore": "#1", "hashAfter": "#2"},
                  {"label": "mm34", "expectHash": ["#7", "#8"], "hashBefore": "#7", "hashAfter": "#8"}],
        "log": {"frames": log_frames, "settle": settle, "errors": [], "labelStart": {}},
        "stage": {"x": 0, "y": 0, "width": 1920, "height": 1080},
    }
    if gl == "auto":
        rest = [1, 0, 1, 1, slot_value if rest4 is None else rest4]
        run["g2"] = {"api": {"state": "LIVE", "events": [{"kind": "glreplay-live"}], "stats": {
            "restOpacity": rest, "opacityUnproven": ([] if slot_value == 1 else probe.UNPROVEN_ON) if unproven is None else unproven,
            "occludedBands": 20 if slot_value == 1 else 0}}}
        run["liveGreen"] = [0, green, 0] * 12
    return run


def make_fsd(slot_value: float) -> dict[str, Any]:
    """A forced `frameLengthChanged` stand-down: no LIVE frames; G2's stand-down replays the settled frame at rest opacity."""
    run = make_run("auto", slot_value)
    run["log"]["frames"] = [f for f in run["log"]["frames"] if f["g2"] != "LIVE"]
    run["log"]["frames"] += _frames("mm12", [[1, 0, 1, 1, slot_value]], [0, 1, 2, 3, 4], "STANDDOWN", 900)
    run["g2"]["api"].update(state="RETIRED", standDowns=[probe.FSD_REASON],
                            events=[{"kind": "glreplay-standdown", "detail": {"reason": probe.FSD_REASON}}])
    run["seedSplice"] = {"reason": probe.FSD_REASON, "splices": 1}
    return run


def arms(gl: str = "off") -> dict[str, dict[str, Any]]:
    on = make_run(gl, ALPHA, hash12="h12-on")
    off = make_run(gl, 1.0, hash12="h12-off", green=60)
    off2 = make_run(gl, 1.0, hash12="h12-off", fade_offset=0.4, frames=MOVE_FRAMES + 3)
    sq = make_run(gl, ALPHA * ALPHA, hash12="h12-sq", green=18)
    out = {"on": on, "off": off, "off2": off2, "sq": sq}
    if gl == "auto":
        out.update(fsd=make_fsd(ALPHA), fsdoff=make_fsd(1.0))
    return out


def tol_of(a: dict[str, dict[str, Any]]) -> float:
    return probe.fade_tolerance(probe.score_cvc_mo1(a["off"], a["off2"]))


def timed(values: list[float | None], step: float = 50.0, start: float = 0.0) -> list[tuple[float, float | None]]:
    return [(start + n * step, v) for n, v in enumerate(values)]


# ------------------------------------------------------------------------------------------------ primitives


def test_f32_matches_webgl_float_storage_and_rejects_non_numbers():
    assert probe.f32(ALPHA) == probe.f32(0.2946862876415253)
    assert probe.f32(ALPHA) != probe.f32(ALPHA * ALPHA)
    assert probe.f32(None) is None and probe.f32(True) is None


def test_sequences_match_constant_equal_and_eased_lerp_by_settle_and_direction():
    tol = 0.05
    assert probe.sequences_match(timed([1, 1, 1]), timed([1, 1]), tol)
    assert not probe.sequences_match(timed([1, 1]), timed([ALPHA, ALPHA]), tol)
    # rAF timing samples the same lerp at other instants: compared at matching elapsed times, within tol.
    assert probe.sequences_match(timed([1, 0.75, 0.5, 0.25, 0]), timed([0.97, 0.72, 0.46, 0.22, 0], start=10.0), tol)
    assert not probe.sequences_match(timed([1, 0.5, 0]), timed([1, 0.5, 0.1]), tol)
    assert not probe.sequences_match(timed([0, 0.5, 1]), timed([1, 0.5, 0]), tol)
    assert not probe.sequences_match(timed([1, 0.2, 0.5, 0]), timed([1, 0.5, 0]), tol)
    assert not probe.sequences_match([], [], tol)
    assert not probe.sequences_match(timed([None, None]), timed([None]), tol)


def test_sequences_match_fails_a_mis_scaled_fade_with_the_same_direction_and_settle_value():
    # Review r1 F8: 0.5 -> 0 instead of 1 -> 0 kept the direction and the end value, so it used to pass.
    good = timed([1.0, 0.75, 0.5, 0.25, 0.0])
    half = timed([0.5, 0.375, 0.25, 0.125, 0.0])
    assert probe.fade_deviation(good, half) == pytest.approx(0.5)
    assert not probe.sequences_match(good, half, 0.05)
    assert probe.sequences_match(good, good, 0.0)


def test_sequences_match_refuses_a_fade_without_a_tolerance():
    fade = timed([1.0, 0.5, 0.0])
    assert not probe.sequences_match(fade, fade, None)
    assert probe.sequences_match(timed([1, 1]), timed([1]), None)


def test_fade_deviation_interpolates_over_the_overlap_only():
    a = timed([0.0, 1.0, 2.0])
    b = timed([0.5, 1.5, 2.5, 99.0], start=50.0)
    assert probe.fade_deviation(a, b) == pytest.approx(0.5)
    assert probe.fade_deviation(a, timed([1.0], start=500.0)) is None
    assert probe.fade_deviation(a, timed([None, 1.0])) is None


def test_fade_tolerance_is_twice_the_control_pairs_fade_deviation():
    a = arms()
    cvc = probe.score_cvc_mo1(a["off"], a["off2"])
    assert cvc["verdict"] == "PASS" and cvc["detail"]["fadeDeviation"] > 0
    assert probe.fade_tolerance(cvc) == pytest.approx(probe.FADE_TOL_FACTOR * cvc["detail"]["fadeDeviation"])
    assert probe.fade_tolerance(None) is None


def test_ordinal_sequences_count_frames_with_fewer_draws():
    frames = _frames("mm12", [[1, 1, ALPHA], [1, 1, ALPHA], [1, 1]], [0, 1, 2], None, 0)
    seq, narrow = probe.ordinal_sequences(frames)
    assert narrow == 1 and seq[2] == [(0.0, probe.f32(ALPHA)), (50.0, probe.f32(ALPHA))]


def test_settle_residual_is_zero_for_the_true_blend_and_large_for_opaque_or_squared():
    on, off, sq = make_run(), make_run(slot_value=1.0), make_run(slot_value=ALPHA * ALPHA)
    assert probe.settle_residual(on, off, ALPHA)[0] <= 0.5
    assert probe.settle_residual(off, off, ALPHA)[0] > 50
    assert probe.settle_residual(sq, off, ALPHA)[0] > 20


def test_settle_residual_refuses_a_translucent_twin():
    # Q0b: with a 4-px erosion the square's anti-aliased edge column read alpha 218 in the patch-off twin, so P != S there.
    on, off = make_run(), make_run(slot_value=1.0)
    off["log"]["settle"]["mm12"]["P"][3] = 218
    residual, problems = probe.settle_residual(on, off, ALPHA)
    assert residual is None and any("min alpha 218" in p for p in problems)
    assert probe.score_mo1(on, off)["verdict"] == "INCONCLUSIVE"


def test_settle_roi_erodes_geometry_plus_the_settled_scale():
    assert probe.SETTLED_SCALE == pytest.approx(313 / 157)
    # 4 px alone is Q0b's ROI, whose x = 793 column carries the magnified edge texel.
    assert probe.settle_roi(4) == [793, 205, 16, 148]
    assert probe.settle_roi() == probe.settle_roi(4 + 2) == [795, 207, 12, 144]


def test_settle_roi_matches_the_effect_fixture_slot_4():
    effect = json.loads(EFFECT_1_TO_2.read_text())
    wrapper = effect["baseLayer"]["layers"][-1]
    leaf = wrapper["layers"][0]
    assert (wrapper["initialState"]["position"]["pointX"], wrapper["initialState"]["position"]["pointY"]) == probe.SLOT_FROM_CENTER
    assert (leaf["initialState"]["width"], leaf["initialState"]["height"]) == probe.SLOT_TEX


def test_movie_masks_come_from_the_plan_boundary_padded_to_gl_rects():
    runtime = {"boundaries": [
        {"atScene": 6, "movieSlot": 0, "slotRects": [[0, 0, 10, 10]], "instanceRect": {"x": 0, "y": 0, "w": 10, "h": 10}},
        {"atScene": 2, "movieSlot": 1, "slotRects": [[0, 0, 1920, 1080], [105.12, 790.85, 960.0, 276.0]],
         "instanceRect": {"x": 109.35, "y": 795.04, "w": 951.54, "h": 267.62}},
    ]}
    assert probe.movie_masks(runtime) == [[103, 11, 965, 281], [107, 15, 956, 272]]
    assert probe.movie_masks({"boundaries": []}) == []
    assert probe.gl_mask([10, 20, 5, 5], pad=0) == [10, 1055, 5, 5]


def test_mo1_settle_hash_without_a_movie_mask_is_inconclusive():
    a = arms()
    a["on"]["log"]["settle"]["mm12"]["masks"] = []
    result = probe.score_mo1(a["on"], a["off"], ALPHA, tol_of(a))
    assert result["verdict"] == "INCONCLUSIVE" and any("movie mask" in p for p in result["problems"])


def test_square_splice_anchor_is_unique_in_the_patch_and_refuses_otherwise():
    node = live_runtime._MM_OPACITY_NODE
    assert node.count(probe.SQUARE_SPLICE[0]) == 1
    assert probe.square_splice(node).count(probe.SQUARE_SPLICE[1]) == 1
    with pytest.raises(ValueError):
        probe.square_splice(b"no anchor here")
    with pytest.raises(ValueError):
        probe.square_splice(node + node)


def test_square_splice_draws_alpha_squared_on_p2_slot_4():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to run the patch's node rule")
    effect = json.loads(EFFECT_1_TO_2.read_text())

    def leaves(methods: bytes) -> list[Any]:
        script = """
const F = {%s};
const out = [];
function walk(A, X){
  if (A.texture) out.push(X === undefined ? null : F.__obedChainOpacity(X, A));
  (A.layers || []).forEach(function(child){ walk(child, F.__obedChainOpacity(X, A)); });
}
walk(%s, undefined);
console.log(JSON.stringify(out));
""" % (methods.decode().replace("}__obedChainOpacity", "},__obedChainOpacity"), json.dumps(effect["baseLayer"]))
        return json.loads(subprocess.run([node, "-e", script], check=True, text=True, capture_output=True).stdout)

    good, bad = leaves(live_runtime._MM_OPACITY_NODE), leaves(probe.square_splice(live_runtime._MM_OPACITY_NODE))
    assert len(good) == len(bad) == 5
    assert good[4] == pytest.approx(ALPHA) and bad[4] == pytest.approx(ALPHA * ALPHA)
    assert good[:4] == bad[:4]


# ------------------------------------------------------------------------------------------------ MO-1


@pytest.mark.parametrize("gl", ["off", "auto"])
def test_mo1_passes_the_patched_run(gl):
    a = arms(gl)
    result = probe.score_mo1(a["on"], a["off"], ALPHA, tol_of(a))
    assert result["verdict"] == "PASS", result
    assert result["detail"]["slotDraws"] == MOVE_FRAMES


@pytest.mark.parametrize("gl", ["off", "auto"])
def test_mo1_kb_patch_off_fails(gl):
    a = arms(gl)
    result = probe.score_mo1(a["off2"], a["off"], ALPHA, tol_of(a))
    assert result["verdict"] == "FAIL"
    assert not result["checks"]["slotAlpha"] and not result["checks"]["settleBlend"]


@pytest.mark.parametrize("gl", ["off", "auto"])
def test_mo1_kb_alpha_squared_fails(gl):
    a = arms(gl)
    result = probe.score_mo1(a["sq"], a["off"], ALPHA, tol_of(a))
    assert result["verdict"] == "FAIL"
    assert not result["checks"]["slotAlpha"] and not result["checks"]["settleBlend"]


def test_mo1_fails_when_the_first_slot_draw_is_opaque():
    a = arms()
    a["on"]["log"]["frames"][0]["draws"][4][1] = 1.0
    assert probe.score_mo1(a["on"], a["off"], ALPHA, tol_of(a))["verdict"] == "FAIL"


def test_mo1_fails_when_a_g2_live_replay_draw_is_not_alpha():
    a = arms("auto")
    live = [f for f in a["on"]["log"]["frames"] if f["g2"] == "LIVE"]
    live[3]["draws"][4][1] = 1.0
    result = probe.score_mo1(a["on"], a["off"], ALPHA, tol_of(a))
    assert result["verdict"] == "FAIL" and not result["checks"]["liveAlpha"]


def test_mo1_fails_when_another_ordinal_differs_from_the_twin():
    a = arms()
    for f in probe.player_frames(a["on"], "mm12"):
        f["draws"][2][1] = ALPHA
    result = probe.score_mo1(a["on"], a["off"], ALPHA, tol_of(a))
    assert result["verdict"] == "FAIL" and result["detail"]["othersMismatch"] == [2]


def test_mo1_fails_a_mis_scaled_fade_on_another_ordinal():
    a = arms()
    for f in probe.player_frames(a["on"], "mm12"):
        f["draws"][1][1] *= 0.5
    result = probe.score_mo1(a["on"], a["off"], ALPHA, tol_of(a))
    assert result["verdict"] == "FAIL" and result["detail"]["othersMismatch"] == [1]
    assert probe.score_mode("off", a)["MO-1"]["verdict"] == "FAIL"


@pytest.mark.parametrize("who, label", [("on", "mm12"), ("off", "mm12"), ("on", "mm34")])
def test_mo1_move_frame_with_fewer_draws_is_inconclusive_not_dropped(who, label):
    a = arms()
    probe.player_frames(a[who], label)[3]["draws"].pop()
    result = probe.score_mo1(a["on"], a["off"], ALPHA, tol_of(a))
    assert result["verdict"] == "INCONCLUSIVE"
    assert any(f"{label}: 1 move frame(s) drew fewer" in p for p in result["problems"]), result["problems"]


def test_cvc_move_frame_with_fewer_draws_is_inconclusive():
    a = arms()
    probe.player_frames(a["off2"], "mm12")[2]["draws"].pop()
    assert probe.score_cvc_mo1(a["off"], a["off2"])["verdict"] == "INCONCLUSIVE"
    assert probe.score_mode("off", a)["MO-1"]["verdict"] == "INCONCLUSIVE"


def test_mo1_fails_when_the_3_to_4_move_differs_from_the_twin():
    a = arms()
    for f in probe.player_frames(a["on"], "mm34"):
        f["draws"][0][1] = 0.5
    result = probe.score_mo1(a["on"], a["off"], ALPHA, tol_of(a))
    assert result["verdict"] == "FAIL" and not result["checks"]["move34MatchesTwin"]


def test_mo1_fails_when_settle_pixels_are_off_by_more_than_one():
    a = arms()
    a["on"]["log"]["settle"]["mm12"]["P"][5] += 2
    result = probe.score_mo1(a["on"], a["off"], ALPHA, tol_of(a))
    assert result["verdict"] == "FAIL" and result["detail"]["settleResidual"] > 1


@pytest.mark.parametrize("mutate, needle", [
    (lambda r: r.__setitem__("error", "Traceback\nRuntimeError: boom"), "run error"),
    (lambda r: r.__setitem__("log", None), "no logger output"),
    (lambda r: r["log"]["errors"].append("TypeError"), "logger errors"),
    (lambda r: r["steps"][0].__setitem__("hashAfter", "#3"), "hash"),
    (lambda r: r["log"]["settle"].pop("mm12"), "no settle read"),
    (lambda r: r["log"]["settle"]["mm12"].__setitem__("frame", 3), "not the last draw"),
    (lambda r: r["log"]["settle"]["mm12"].__setitem__("B", None), "ROI pair"),
    (lambda r: r["log"]["settle"]["mm34"].__setitem__("ord", 1), "mm34: settle read"),
    (lambda r: r["log"]["frames"][5]["draws"][4].__setitem__(0, 9), "not unique"),
])
def test_mo1_integrity_failures_are_inconclusive_never_pass(mutate, needle):
    a = arms()
    mutate(a["on"])
    result = probe.score_mo1(a["on"], a["off"], ALPHA, tol_of(a))
    assert result["verdict"] == "INCONCLUSIVE"
    assert any(needle in p for p in result["problems"]), result["problems"]


def test_mo1_integrity_failure_in_the_twin_is_inconclusive():
    a = arms()
    a["off"]["log"]["errors"].append("x")
    assert probe.score_mo1(a["on"], a["off"], ALPHA, tol_of(a))["verdict"] == "INCONCLUSIVE"


def test_mo1_too_few_slot_draws_is_inconclusive():
    on, off = make_run(frames=12), make_run(slot_value=1.0, frames=12)
    result = probe.score_mo1(on, off)
    assert result["verdict"] == "INCONCLUSIVE" and any("< 20" in p for p in result["problems"])


def test_mo1_gl_on_without_live_draws_is_inconclusive():
    a = arms("auto")
    a["on"]["log"]["frames"] = [f for f in a["on"]["log"]["frames"] if f["g2"] != "LIVE"]
    assert probe.score_mo1(a["on"], a["off"], ALPHA, tol_of(a))["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize("which", ["on", "off"])
def test_mo1_gl_on_is_void_when_g2_stands_down_in_either_twin(which):
    a = arms("auto")
    a[which]["g2"]["api"]["events"].append({"kind": "glreplay-standdown", "detail": {"reason": "posterAmbiguous"}})
    assert probe.score_mo1(a["on"], a["off"], ALPHA, tol_of(a))["verdict"] == "VOID"
    assert probe.score_mode("auto", a)["MO-1"]["verdict"] == "VOID"


def test_mo1_gl_on_is_void_when_g2_never_went_live():
    a = arms("auto")
    a["off"]["g2"]["api"]["state"] = "RETIRED"
    assert probe.score_mo1(a["on"], a["off"], ALPHA, tol_of(a))["verdict"] == "VOID"


def test_g2_handoff_is_not_a_stand_down():
    run = make_run("auto")
    run["g2"]["api"]["events"].append({"kind": "glreplay-handoff", "detail": {"reason": "canvasRemoved"}})
    assert probe.g2_void(run) is None
    assert probe.g2_void(make_run("off")) is None


# ------------------------------------------------------------------------------------------------ MO-4


def test_mo4_passes_the_patched_g2_facts():
    a = arms("auto")
    result = probe.score_mo4(a["on"], a["off"])
    assert result["verdict"] == "PASS", result


def test_mo4_kb_alpha_squared_fails_on_rest_and_live_green():
    a = arms("auto")
    result = probe.score_mo4(a["sq"], a["off"])
    assert result["verdict"] == "FAIL"
    assert not result["checks"]["restSlotAlpha"] and not result["checks"]["liveGreenEqual"]


def test_mo4_patch_off_run_fails_the_patched_expectations():
    a = arms("auto")
    result = probe.score_mo4(a["off2"], a["off"])
    assert result["verdict"] == "FAIL"
    assert not result["checks"]["unprovenOn"] and not result["checks"]["restSlotAlpha"]


@pytest.mark.parametrize("mutate, check", [
    (lambda a: a["on"]["g2"]["api"]["stats"].__setitem__("opacityUnproven", probe.UNPROVEN_ON + [{"slot": 2, "reason": "rest-opacity"}]), "unprovenOn"),
    (lambda a: a["on"]["g2"]["api"]["stats"].__setitem__("opacityUnproven", []), "unprovenOn"),
    (lambda a: a["off"]["g2"]["api"]["stats"].__setitem__("opacityUnproven", [{"slot": 4, "reason": "rest-opacity"}]), "unprovenOff"),
    (lambda a: a["off"]["g2"]["api"]["stats"].__setitem__("restOpacity", [1, 0, 1, 1, ALPHA]), "restOff"),
    (lambda a: a["on"]["g2"]["api"]["stats"]["restOpacity"].__setitem__(1, 1), "restOthersOff"),
    (lambda a: a["on"].__setitem__("liveGreen", [0, 61, 0] * 12), "liveGreenEqual"),
    (lambda a: a["on"]["g2"]["api"]["stats"].__setitem__("occludedBands", 20), "occludedBandsOn"),
    (lambda a: a["off"]["g2"]["api"]["stats"].__setitem__("occludedBands", 0), "occludedBandsOff"),
])
def test_mo4_fails_each_moved_fact(mutate, check):
    a = arms("auto")
    mutate(a)
    result = probe.score_mo4(a["on"], a["off"])
    assert result["verdict"] == "FAIL" and not result["checks"][check]


@pytest.mark.parametrize("mutate", [
    lambda r: r.__setitem__("gl", "off"),
    lambda r: r.__setitem__("liveGreen", None),
    lambda r: r["g2"]["api"].__setitem__("stats", None),
    lambda r: r.__setitem__("stage", {"x": 0, "y": 16, "width": 1920, "height": 1080}),
    lambda r: r.__setitem__("error", "boom"),
])
def test_mo4_integrity_failures_are_inconclusive(mutate):
    a = arms("auto")
    mutate(a["on"])
    assert probe.score_mo4(a["on"], a["off"])["verdict"] == "INCONCLUSIVE"


def test_mo4_asserts_occluded_bands_0_on_and_20_off():
    a = arms("auto")
    result = probe.score_mo4(a["on"], a["off"])
    assert result["checks"]["occludedBandsOn"] and result["checks"]["occludedBandsOff"]
    assert (result["detail"]["occludedBands"], result["detail"]["occludedBandsTwin"]) == (0, 20)


def test_mo4_cvc_reads_occluded_bands():
    a = arms("auto")
    a["off2"]["g2"]["api"]["stats"]["occludedBands"] = 19
    assert not probe.score_cvc_mo4(a["off"], a["off2"])["checks"]["occludedBands"]
    assert probe.score_mode("auto", a)["MO-4"]["verdict"] == "INCONCLUSIVE"


def test_mo4_void_when_g2_stands_down():
    a = arms("auto")
    a["off"]["g2"]["api"]["state"] = "STANDDOWN"
    assert probe.score_mo4(a["on"], a["off"])["verdict"] == "VOID"


# ------------------------------------------------------------------------------------------------ MO-4 forced stand-down


def test_standdown_passes_the_patched_replay_and_fails_the_patch_off_kb():
    a = arms("auto")
    good = probe.score_standdown(a["fsd"])
    assert good["verdict"] == "PASS", good
    assert good["detail"]["standdownSlotValues"] == [probe.f32(ALPHA)]
    bad = probe.score_standdown(a["fsdoff"])
    assert bad["verdict"] == "FAIL" and not bad["checks"]["standdownAlpha"]


def test_standdown_ignores_live_and_player_frames():
    run = make_fsd(ALPHA)
    run["log"]["frames"] += _frames("mm12", [[1, 0, 1, 1, 1.0]], [0, 1, 2, 3, 4], "LIVE", 950)
    assert probe.score_standdown(run)["verdict"] == "PASS"
    run["log"]["frames"][-2]["draws"][4][1] = 1.0
    assert probe.score_standdown(run)["verdict"] == "FAIL"


@pytest.mark.parametrize("mutate, needle", [
    (lambda r: r.__setitem__("gl", "off"), "not a GL-replay run"),
    (lambda r: r.__setitem__("error", "Traceback\nRuntimeError: boom"), "run error"),
    (lambda r: r.__setitem__("log", None), "no logger output"),
    (lambda r: r["log"]["errors"].append("TypeError"), "logger errors"),
    (lambda r: r.__setitem__("seedSplice", {"splices": 0}), "seed"),
    (lambda r: r["g2"]["api"].__setitem__("standDowns", ["writebackFailed", probe.FSD_REASON]), "stand-downs"),
    (lambda r: r["g2"]["api"].__setitem__("standDowns", []), "stand-downs"),
    (lambda r: r["log"].__setitem__("frames", [f for f in r["log"]["frames"] if f["g2"] != "STANDDOWN"]), "no slot-4 draw"),
])
def test_standdown_integrity_failures_are_inconclusive(mutate, needle):
    run = make_fsd(ALPHA)
    mutate(run)
    result = probe.score_standdown(run)
    assert result["verdict"] == "INCONCLUSIVE"
    assert any(needle in p for p in result["problems"]), result["problems"]


def test_standdown_gate_needs_its_run_its_kb_and_the_mo4_cvc():
    a = arms("auto")
    assert probe.score_mode("auto", a)["MO-4 stand-down"]["verdict"] == "PASS"
    for drop in ("fsd", "fsdoff", "off2"):
        b = arms("auto")
        b.pop(drop)
        assert probe.score_mode("auto", b)["MO-4 stand-down"]["verdict"] == "INCONCLUSIVE", drop
    b = arms("auto")
    b["fsdoff"] = make_fsd(ALPHA)
    result = probe.score_mode("auto", b)["MO-4 stand-down"]
    assert result["verdict"] == "INCONCLUSIVE" and any("patch-off" in r for r in result["reasons"])


def test_standdown_gate_fails_a_replay_that_pops_opaque():
    a = arms("auto")
    a["fsd"] = make_fsd(1.0)
    assert probe.score_mode("auto", a)["MO-4 stand-down"]["verdict"] == "FAIL"


# ------------------------------------------------------------------------------------------------ MO-5


def test_mo5_passes_equal_3_to_4_and_different_1_to_2():
    a = arms()
    assert probe.score_mo5(a["on"], a["off"])["verdict"] == "PASS"


def test_mo5_fails_when_3_to_4_moves_or_1_to_2_does_not():
    a = arms()
    a["on"]["log"]["settle"]["mm34"]["hash"] = "other"
    assert probe.score_mo5(a["on"], a["off"])["verdict"] == "FAIL"
    a = arms()
    assert probe.score_mo5(a["off2"], a["off"])["verdict"] == "FAIL"


def test_mo5_missing_hash_is_inconclusive():
    a = arms()
    a["off"]["log"]["settle"]["mm34"]["hash"] = None
    assert probe.score_mo5(a["on"], a["off"])["verdict"] == "INCONCLUSIVE"


# ------------------------------------------------------------------------------------------------ gates


@pytest.mark.parametrize("gl, gates", [("off", {"MO-1", "MO-5"}), ("auto", {"MO-1", "MO-4", "MO-4 stand-down", "MO-5"})])
def test_full_mode_passes_with_cvc_and_kbs(gl, gates):
    result = probe.score_mode(gl, arms(gl))
    assert set(result) == gates
    for name, g in result.items():
        assert g["verdict"] == "PASS", (name, g["reasons"], g["primary"])


def test_score_all_reports_the_worst_gate():
    runs = {"off": arms("off"), "auto": arms("auto")}
    assert probe.score_all(runs)["overall"] == "PASS"
    runs["auto"]["on"]["g2"]["api"]["stats"]["opacityUnproven"] = []
    assert probe.score_all(runs)["overall"] == "FAIL"


@pytest.mark.parametrize("drop", ["off2", "sq"])
def test_gate_without_its_cvc_or_kb_is_inconclusive(drop):
    a = arms("auto")
    a.pop(drop)
    result = probe.score_mode("auto", a)
    assert result["MO-1"]["verdict"] == "INCONCLUSIVE"
    assert result["MO-4"]["verdict"] == "INCONCLUSIVE"


def test_gate_is_inconclusive_when_a_kb_does_not_fail():
    a = arms()
    a["sq"] = copy.deepcopy(a["on"])
    result = probe.score_mode("off", a)
    assert result["MO-1"]["verdict"] == "INCONCLUSIVE"
    assert any("alpha-squared" in r for r in result["MO-1"]["reasons"])


def test_gate_is_inconclusive_when_control_vs_control_differs():
    a = arms()
    a["off2"]["log"]["settle"]["mm12"]["P"][1] += 1
    assert probe.score_mode("off", a)["MO-1"]["verdict"] == "INCONCLUSIVE"
    a = arms()
    a["off2"]["log"]["settle"]["mm34"]["hash"] = "jitter"
    assert probe.score_mode("off", a)["MO-5"]["verdict"] == "INCONCLUSIVE"
    a = arms("auto")
    a["off2"]["liveGreen"] = [0, 59, 0] * 12
    assert probe.score_mode("auto", a)["MO-4"]["verdict"] == "INCONCLUSIVE"


def test_gate_keeps_a_primary_fail_when_controls_hold():
    a = arms()
    a["on"] = make_run(slot_value=0.5, hash12="h12-half")
    assert probe.score_mode("off", a)["MO-1"]["verdict"] == "FAIL"


def test_missing_primary_runs_are_inconclusive():
    result = probe.score_mode("auto", {"off": make_run("auto", 1.0)})
    assert {g["verdict"] for g in result.values()} == {"INCONCLUSIVE"}
    assert set(result) == {"MO-1", "MO-4", "MO-4 stand-down", "MO-5"}


def test_score_cli_rescores_saved_runs(tmp_path):
    (tmp_path / "runs").mkdir()
    for gl in ("off", "auto"):
        for arm, run in arms(gl).items():
            run["arm"] = arm
            (tmp_path / "runs" / f"{gl}-{arm}.json").write_text(json.dumps(run))
    assert probe.main(["--score", str(tmp_path)]) == 0
    assert json.loads((tmp_path / "verdict.json").read_text())["overall"] == "PASS"


def test_cli_requires_exactly_one_mode_and_known_arms():
    with pytest.raises(SystemExit):
        probe.parse_args([])
    with pytest.raises(SystemExit):
        probe.parse_args(["--out", "x", "--arms", "on,bogus"])
    assert probe.parse_args(["--out", "x"]).arms == list(probe.ALL_ARMS)


def test_cli_runs_the_forced_stand_down_arms_under_gl_auto_only(monkeypatch, tmp_path):
    ran: list[tuple[str, str]] = []
    monkeypatch.setattr(probe, "headless_chromes", lambda: 0)
    monkeypatch.setattr(probe, "run_arm", lambda fixture, gl, arm: ran.append((gl, arm)) or {"gl": gl, "arm": arm, "error": "x"})
    probe.main(["--out", str(tmp_path), "--arms", "on,fsd,fsdoff"])
    assert ran == [("off", "on"), ("auto", "on"), ("auto", "fsd"), ("auto", "fsdoff")]


def test_logger_parses_and_touches_only_the_declared_gl_surface():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to parse the logger")
    subprocess.run([node, "-e", "new Function(require('fs').readFileSync(0, 'utf8'))"], input=probe.LOGGER_JS,
                   check=True, text=True)
    for name in ("getUniformLocation", "useProgram", "uniform1f", "clear", "drawArrays", "drawElements"):
        assert f"wrap('{name}'" in probe.LOGGER_JS
    assert probe.LOGGER_JS.count("wrap('") == 6
    assert "getUniform'" not in probe.LOGGER_JS and "getUniform(" not in probe.LOGGER_JS


def _run_logger(node: str, movie_value: int, square_value: int) -> dict:
    # A fake WebGL context in Node: pixels left of x = 2 are the "movie" (varies per run), the rest follow the draw count.
    script = """
const window = globalThis;
function WebGLRenderingContext(){}
const P = WebGLRenderingContext.prototype;
Object.assign(P, {FRAMEBUFFER_BINDING: 1, RGBA: 2, UNSIGNED_BYTE: 3, drawingBufferWidth: 8, drawingBufferHeight: 6,
  getUniformLocation(p, n){ return {p: p, n: n}; }, useProgram(){}, uniform1f(){}, clear(){ this.drawn = 0; },
  drawArrays(){ this.drawn++; }, drawElements(){ this.drawn++; }, getParameter(){ return null; },
  readPixels(x, y, w, h, f, t, out){
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) for (let c = 0; c < 4; c++)
      out[(j * w + i) * 4 + c] = x + i < 2 ? %d : this.drawn * %d;
  }});
%s
const gl = new WebGLRenderingContext();
const progs = [{}, {}];
const locs = progs.map(p => gl.getUniformLocation(p, 'Opacity'));
window.__OBED_MMO__.setLabel('mm12', {settleFromMs: 0, roi: [1, 1, 2, 2], roiOrdinal: 1, masks: [[0, 0, 2, 6]]});
for (let f = 0; f < 3; f++){
  gl.clear(16384);
  progs.forEach((p, k) => { gl.useProgram(p); if (f === 0) gl.uniform1f(locs[k], k ? 0.25 : 1); gl.drawArrays(4, 0, 6); });
}
const M = window.__OBED_MMO__;
console.log(JSON.stringify({frames: M.frames, settle: M.settle, errors: M.errors}));
""" % (movie_value, square_value, probe.LOGGER_JS)
    return json.loads(subprocess.run([node, "-e", script], check=True, text=True, capture_output=True).stdout)


def test_logger_records_value_in_effect_and_one_masked_settle_read_on_the_last_frame():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to run the logger")
    a, b, c = _run_logger(node, 7, 10), _run_logger(node, 99, 10), _run_logger(node, 7, 11)
    assert a["errors"] == []
    assert [f["draws"] for f in a["frames"]] == [[[0, 1], [1, 0.25]]] * 3
    settle = a["settle"]["mm12"]
    assert settle["frame"] == 2 and settle["ord"] == 1
    assert settle["B"] == [7, 7, 7, 7, 10, 10, 10, 10] * 2
    assert settle["P"] == [7, 7, 7, 7, 20, 20, 20, 20] * 2
    assert a["settle"]["mm12"]["hash"] == b["settle"]["mm12"]["hash"]
    assert a["settle"]["mm12"]["hash"] != c["settle"]["mm12"]["hash"]


def test_wait_for_hash_returns_the_expected_hash_once_seen_else_the_last_read():
    reads = iter(["#1", "#1", "#2", "#3"])
    assert probe.wait_for_hash(lambda _e: next(reads), "x", "#2", timeout_s=5) == "#2"
    assert probe.wait_for_hash(lambda _e: "#9", "x", "#8", timeout_s=0) == "#9"
    assert probe.wait_for_hash(lambda _e: "#4", "x", None) == "#4"


# ------------------------------------------------------------------------------------------------ drive (shared step loop)


class FakeTransport:
    """Answers the driver's page reads; records every `setLabel` payload the logger would receive."""

    HASHES = ["#1", "#2", "#3", "#4", "#5", "#7", "#8"]

    def __init__(self, host: "FakeHost") -> None:
        self.host, self.labels = host, {}

    def evaluate(self, expression: str, deadline_s: float | None = None) -> Any:
        import live_continuity_probe as lcp

        prefix = "window.__OBED_MMO__.setLabel("
        if expression.startswith(prefix):
            label, cfg = json.loads("[" + expression[len(prefix):-1] + "]")
            self.labels[label] = cfg
            return True
        if expression == lcp.HASH_JS:
            return self.HASHES[self.host.advances]
        if expression == lcp.GL_REPLAY_READ_JS:
            return {"api": {"state": "LIVE"}}
        if expression == probe.LOG_READ_JS:
            return {"frames": [], "settle": {}, "errors": []}
        if expression == probe.STAGE_JS:
            return {"x": 0, "y": 0, "width": 1920, "height": 1080}
        return True


class FakeHost:
    def __init__(self) -> None:
        self.advances, self.ops = 0, []
        self.transport = FakeTransport(self)

    def _require_transport(self) -> FakeTransport:
        return self.transport

    def execute(self, operation: str, slide: int | None = None) -> None:
        self.ops.append(operation)
        self.advances += operation == "advance"


def drive_once(monkeypatch, gl: str, masks: list[list[int]]) -> tuple[FakeHost, dict[str, Any]]:
    import live_continuity_probe as lcp
    import live_host_probe

    monkeypatch.setattr(lcp, "wait_for_decode", lambda host: {"ok": True})
    monkeypatch.setattr(live_host_probe, "wait_for_settlement", lambda host, timeout_s: ({}, 0.1))
    monkeypatch.setattr(probe.time, "sleep", lambda s: None)
    host, record = FakeHost(), {"gl": gl, "steps": []}
    probe.drive(host, record, probe.step_extra(masks), lambda: np.full((1080, 1920, 4), 7, np.uint8))
    return host, record


@pytest.mark.parametrize("gl", ["off", "auto"])
def test_drive_sends_the_settle_roi_and_movie_masks_to_the_logger_at_1_to_2(monkeypatch, gl):
    # Review r1 F1: MO-3's copied loop sent the bare PLAN config, so its logger never read B/P and every gate was
    # INCONCLUSIVE. The shared driver must merge the ROI and masks into mm12's payload (and only there).
    masks = [[103, 11, 965, 281], [107, 15, 956, 272]]
    host, record = drive_once(monkeypatch, gl, masks)
    sent = host.transport.labels
    assert list(sent) == [label for label, _, _ in probe.PLAN]
    assert sent["mm12"]["roi"] == probe.settle_roi() and sent["mm12"]["masks"] == masks
    assert sent["mm12"]["roiOrdinal"] == probe.SLOT and sent["mm12"]["settleFromMs"] == probe.MOVE_MS - probe.SETTLE_WINDOW_MS
    assert "roi" not in sent["mm34"] and "masks" not in sent["mm34"]
    assert host.ops == ["show"] + ["advance"] * len(probe.PLAN)
    steps = {s["label"]: s for s in record["steps"]}
    assert [steps["mm12"]["hashBefore"], steps["mm12"]["hashAfter"]] == ["#1", "#2"]
    assert [steps["mm34"]["hashBefore"], steps["mm34"]["hashAfter"]] == ["#7", "#8"]
    assert record["log"] == {"frames": [], "settle": {}, "errors": []} and record["loggerInstalled"] is True
    if gl == "auto":
        assert record["g2"] == {"api": {"state": "LIVE"}}
        assert record["liveGreen"] == [7] * (probe.ROI_TOP[2] * probe.ROI_TOP[3] * 3)
    else:
        assert "g2" not in record and "liveGreen" not in record


def test_boundary_masks_match_movie_masks_for_the_same_entry():
    entry = {"atScene": 2, "movieSlot": 1, "slotRects": [[0, 0, 1920, 1080], {"x": 105.12, "y": 790.85, "w": 960.0, "h": 276.0}],
             "instanceRect": {"x": 109.35, "y": 795.04, "w": 951.54, "h": 267.62}}
    assert probe.boundary_masks(entry) == probe.movie_masks({"boundaries": [entry]}) == [[103, 11, 965, 281], [107, 15, 956, 272]]
