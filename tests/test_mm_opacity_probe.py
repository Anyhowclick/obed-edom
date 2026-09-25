"""Synthetic tests for the MO-1 / MO-4 / MO-5 scorers in `scripts/mm_opacity_probe.py`.

No browser, host or export: every run record is built here in the shape the in-page logger and the driver produce.
Each gate must PASS on the patched run, FAIL on each known-bad (patch off, the alpha-squared splice), and read
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
                 "P": _blend(opacity), "w": 1920, "h": 1080, "hash": hash12},
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
            "occludedBands": 0}}}
        run["liveGreen"] = [0, green, 0] * 12
    return run


def arms(gl: str = "off") -> dict[str, dict[str, Any]]:
    on = make_run(gl, ALPHA, hash12="h12-on")
    off = make_run(gl, 1.0, hash12="h12-off", green=60)
    off2 = make_run(gl, 1.0, hash12="h12-off", fade_offset=0.4, frames=MOVE_FRAMES + 3)
    sq = make_run(gl, ALPHA * ALPHA, hash12="h12-sq", green=18)
    return {"on": on, "off": off, "off2": off2, "sq": sq}


# ------------------------------------------------------------------------------------------------ primitives


def test_f32_matches_webgl_float_storage_and_rejects_non_numbers():
    assert probe.f32(ALPHA) == probe.f32(0.2946862876415253)
    assert probe.f32(ALPHA) != probe.f32(ALPHA * ALPHA)
    assert probe.f32(None) is None and probe.f32(True) is None


def test_sequences_match_constant_equal_and_eased_lerp_by_settle_and_direction():
    assert probe.sequences_match([1, 1, 1], [1, 1])
    assert not probe.sequences_match([1, 1], [ALPHA, ALPHA])
    # rAF timing moves the intermediate lerp values between runs; the settle value and direction must agree.
    assert probe.sequences_match([1, 0.9, 0.5, 0], [0.97, 0.6, 0.1, 0])
    assert not probe.sequences_match([1, 0.5, 0], [1, 0.5, 0.1])
    assert not probe.sequences_match([0, 0.5, 1], [1, 0.5, 0])
    assert not probe.sequences_match([1, 0.2, 0.5, 0], [1, 0.5, 0])
    assert not probe.sequences_match([], [])
    assert not probe.sequences_match([None, None], [None])


def test_settle_residual_is_zero_for_the_true_blend_and_large_for_opaque_or_squared():
    on, off, sq = make_run(), make_run(slot_value=1.0), make_run(slot_value=ALPHA * ALPHA)
    assert probe.settle_residual(on, off, ALPHA)[0] <= 0.5
    assert probe.settle_residual(off, off, ALPHA)[0] > 50
    assert probe.settle_residual(sq, off, ALPHA)[0] > 20


def test_settle_residual_refuses_a_translucent_twin():
    on, off = make_run(), make_run(slot_value=1.0)
    off["log"]["settle"]["mm12"]["P"][3] = 200
    residual, problems = probe.settle_residual(on, off, ALPHA)
    assert residual is None and problems


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
    result = probe.score_mo1(a["on"], a["off"])
    assert result["verdict"] == "PASS", result
    assert result["detail"]["slotDraws"] == MOVE_FRAMES


@pytest.mark.parametrize("gl", ["off", "auto"])
def test_mo1_kb_patch_off_fails(gl):
    a = arms(gl)
    result = probe.score_mo1(a["off2"], a["off"])
    assert result["verdict"] == "FAIL"
    assert not result["checks"]["slotAlpha"] and not result["checks"]["settleBlend"]


@pytest.mark.parametrize("gl", ["off", "auto"])
def test_mo1_kb_alpha_squared_fails(gl):
    a = arms(gl)
    result = probe.score_mo1(a["sq"], a["off"])
    assert result["verdict"] == "FAIL"
    assert not result["checks"]["slotAlpha"] and not result["checks"]["settleBlend"]


def test_mo1_fails_when_the_first_slot_draw_is_opaque():
    a = arms()
    a["on"]["log"]["frames"][0]["draws"][4][1] = 1.0
    assert probe.score_mo1(a["on"], a["off"])["verdict"] == "FAIL"


def test_mo1_fails_when_a_g2_live_replay_draw_is_not_alpha():
    a = arms("auto")
    live = [f for f in a["on"]["log"]["frames"] if f["g2"] == "LIVE"]
    live[3]["draws"][4][1] = 1.0
    result = probe.score_mo1(a["on"], a["off"])
    assert result["verdict"] == "FAIL" and not result["checks"]["liveAlpha"]


def test_mo1_fails_when_another_ordinal_differs_from_the_twin():
    a = arms()
    for f in probe.player_frames(a["on"], "mm12"):
        f["draws"][2][1] = ALPHA
    result = probe.score_mo1(a["on"], a["off"])
    assert result["verdict"] == "FAIL" and result["detail"]["othersMismatch"] == [2]


def test_mo1_fails_when_the_3_to_4_move_differs_from_the_twin():
    a = arms()
    for f in probe.player_frames(a["on"], "mm34"):
        f["draws"][0][1] = 0.5
    result = probe.score_mo1(a["on"], a["off"])
    assert result["verdict"] == "FAIL" and not result["checks"]["move34MatchesTwin"]


def test_mo1_fails_when_settle_pixels_are_off_by_more_than_one():
    a = arms()
    a["on"]["log"]["settle"]["mm12"]["P"][5] += 2
    result = probe.score_mo1(a["on"], a["off"])
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
    result = probe.score_mo1(a["on"], a["off"])
    assert result["verdict"] == "INCONCLUSIVE"
    assert any(needle in p for p in result["problems"]), result["problems"]


def test_mo1_integrity_failure_in_the_twin_is_inconclusive():
    a = arms()
    a["off"]["log"]["errors"].append("x")
    assert probe.score_mo1(a["on"], a["off"])["verdict"] == "INCONCLUSIVE"


def test_mo1_too_few_slot_draws_is_inconclusive():
    on, off = make_run(frames=12), make_run(slot_value=1.0, frames=12)
    result = probe.score_mo1(on, off)
    assert result["verdict"] == "INCONCLUSIVE" and any("< 20" in p for p in result["problems"])


def test_mo1_gl_on_without_live_draws_is_inconclusive():
    a = arms("auto")
    a["on"]["log"]["frames"] = [f for f in a["on"]["log"]["frames"] if f["g2"] != "LIVE"]
    assert probe.score_mo1(a["on"], a["off"])["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize("which", ["on", "off"])
def test_mo1_gl_on_is_void_when_g2_stands_down_in_either_twin(which):
    a = arms("auto")
    a[which]["g2"]["api"]["events"].append({"kind": "glreplay-standdown", "detail": {"reason": "posterAmbiguous"}})
    assert probe.score_mo1(a["on"], a["off"])["verdict"] == "VOID"
    assert probe.score_mode("auto", a)["MO-1"]["verdict"] == "VOID"


def test_mo1_gl_on_is_void_when_g2_never_went_live():
    a = arms("auto")
    a["off"]["g2"]["api"]["state"] = "RETIRED"
    assert probe.score_mo1(a["on"], a["off"])["verdict"] == "VOID"


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


def test_mo4_void_when_g2_stands_down():
    a = arms("auto")
    a["off"]["g2"]["api"]["state"] = "STANDDOWN"
    assert probe.score_mo4(a["on"], a["off"])["verdict"] == "VOID"


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


@pytest.mark.parametrize("gl, gates", [("off", {"MO-1", "MO-5"}), ("auto", {"MO-1", "MO-4", "MO-5"})])
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
    assert {g["verdict"] for g in result.values()} == {"INCONCLUSIVE"} and set(result) == {"MO-1", "MO-4", "MO-5"}


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
