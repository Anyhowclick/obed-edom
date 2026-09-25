"""Synthetic tests for the hand-back geometry scorer (`obed_edom.mm_handback_score`) and the HB-1..HB-4 gate logic in
`scripts/mm_handback_probe.py`.

No browser, host or export. Frames are rendered here with exact box-filter coverage (every pixel holds the area of it
covered by the object), in authored px mapped to the frame by `screen = authored * s + origin`. The scene reproduces the
P2 1->2 hand-back from the plan's table: the DOM draws the authored content rects, the known-bad (today's) settled GL frame
draws them 0.8-2.8 px off. HB-1 must PASS when the on-arms settle on the DOM geometry, FAIL when they do not, and read
INCONCLUSIVE (never PASS) whenever the KB does not fail, a CvC or null control drifts, the premise or the engagement read
does not hold.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
_SPEC = importlib.util.spec_from_file_location("mm_handback_probe", REPO / "scripts" / "mm_handback_probe.py")
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)

from obed_edom import mm_handback_score as hb

DOM = {
    "green.left": 790.153, "green.right": 1140.989, "green.top": 674.900, "green.bottom": 984.968,
    "sentinel.left": 545.191, "sentinel.right": 719.647, "sentinel.top": 724.366,
    "movie.left": 106.776, "movie.top": 792.579, "movie.right": 1063.459,
}
KNOWN_BAD = {**DOM, "green.left": 792.240, "green.right": 1138.211, "green.top": 675.723, "green.bottom": 983.108,
             "sentinel.left": 544.052, "sentinel.right": 720.665, "sentinel.top": 723.331}
KB_MAX = max(abs(DOM[k] - KNOWN_BAD[k]) for k in DOM)
GREEN_LUMA = 40.0
SENTINEL_STROKE = 4.0
OUTLINE = 4.0


def cover(n: int, a: float, b: float) -> np.ndarray:
    i = np.arange(n)
    return np.clip(np.minimum(i + 1, b) - np.maximum(i, a), 0, 1)


def paint(img: np.ndarray, x0: float, x1: float, y0: float, y1: float, value: float) -> None:
    c = np.outer(cover(img.shape[0], y0, y1), cover(img.shape[1], x0, x1))
    img *= 1 - c
    img += value * c


def render(scene: dict[str, float], size: tuple[int, int] = (1920, 1080), stage: hb.Stage = hb.IDENTITY) -> np.ndarray:
    """Float luma frame of the P2 hand-back scene: green fill, sentinel white strokes (centres), movie white outline."""
    img = np.zeros((size[1], size[0]))

    def box(x0: float, x1: float, y0: float, y1: float, value: float) -> None:
        paint(img, x0 * stage.s + stage.ox, x1 * stage.s + stage.ox, y0 * stage.s + stage.oy, y1 * stage.s + stage.oy, value)

    g = scene
    box(g["green.left"], g["green.right"], g["green.top"], g["green.bottom"], GREEN_LUMA)
    h = SENTINEL_STROKE / 2
    box(g["sentinel.left"] - h, g["sentinel.left"] + h, g["sentinel.top"] - h, 880, 255)
    box(g["sentinel.right"] - h, g["sentinel.right"] + h, g["sentinel.top"] - h, 880, 255)
    box(g["sentinel.left"] - h, g["sentinel.right"] + h, g["sentinel.top"] - h, g["sentinel.top"] + h, 255)
    box(g["movie.left"], g["movie.left"] + OUTLINE, g["movie.top"], 1067, 255)
    box(g["movie.right"] - OUTLINE, g["movie.right"], g["movie.top"], 1067, 255)
    box(g["movie.left"], g["movie.right"], g["movie.top"], g["movie.top"] + OUTLINE, 255)
    return img


def rgb(frame: np.ndarray) -> np.ndarray:
    return np.repeat(np.clip(np.rint(frame), 0, 255).astype(np.uint8)[..., None], 3, axis=2)


# ---------------------------------------------------------------------------------------------------------------------
# Scorer primitives


@pytest.mark.parametrize("pos", [10.0, 10.3, 10.5, 10.77])
@pytest.mark.parametrize("axis", ["x", "y"])
def test_box_filtered_step_edges_read_back_sub_pixel(pos: float, axis: str) -> None:
    rising, falling = np.zeros((40, 40)), np.zeros((40, 40))
    if axis == "x":
        paint(rising, pos, 40, 0, 40, 60)
        paint(falling, 0, pos, 0, 40, 60)
    else:
        paint(rising, 0, 40, pos, 40, 60)
        paint(falling, 0, 40, 0, pos, 60)
    edge = hb.Edge("e", "step", axis, 2, 20, 5, 35)
    for frame in (rising, falling):
        reading = hb.measure_edge(frame, edge)
        assert abs(reading.pos - pos) < 0.01
        assert reading.contrast == pytest.approx(60)


@pytest.mark.parametrize("pos", [10.0, 10.3, 10.77])
def test_white_step_reads_an_outline_edge_in_both_directions(pos: float) -> None:
    """The window ends inside a thin white outline; the far side of the outline (the movie interior) is outside it."""
    rising, falling = np.zeros((40, 40)), np.zeros((40, 40))
    paint(rising, pos, 13.0, 0, 40, 255)
    paint(falling, 3.0, pos, 0, 40, 255)
    assert abs(hb.measure_edge(rising, hb.Edge("e", "white-step", "x", 4, 12, 5, 35)).pos - pos) < 0.01
    assert abs(hb.measure_edge(falling, hb.Edge("e", "white-step", "x", 4, 18, 5, 35)).pos - pos) < 0.01


@pytest.mark.parametrize(("centre", "width"), [(20.0, 4.0), (20.37, 4.0), (19.81, 2.72), (20.5, 3.33)])
def test_stroke_centroid_and_width(centre: float, width: float) -> None:
    """The first moment puts each partial end pixel's weight at the pixel centre, so a box-filtered stroke reads its
    centre plus (cR(1 - cR) - cL(1 - cL)) / 2W (cL, cR = end-pixel coverages): at most 0.125 / W px, 0 at symmetric
    phases. The width (the zeroth moment) is exact."""
    a, b = centre - width / 2, centre + width / 2
    frame = np.zeros((40, 40))
    paint(frame, 0, 40, a, b, 255)
    reading = hb.measure_edge(frame, hb.Edge("s", "stroke", "y", 10, 30, 5, 35))
    c_left, c_right = math.ceil(a) - a, b - math.floor(b)
    bias = (c_right * (1 - c_right) - c_left * (1 - c_left)) / (2 * width)
    assert abs(bias) <= 0.125 / width
    assert reading.pos == pytest.approx(centre + bias, abs=1e-9)
    assert reading.width == pytest.approx(width, abs=1e-9)


def test_luminance_passes_2d_frames_through_and_reduces_rgb() -> None:
    plane = np.arange(12.0).reshape(3, 4)
    assert np.array_equal(hb.luminance(plane), plane)
    assert np.allclose(hb.luminance(np.repeat(plane[..., None], 4, axis=2)), plane)


def test_scene_reads_back_its_authored_positions() -> None:
    readings = hb.measure_edges(render(DOM))
    for name, value in DOM.items():
        assert abs(readings[name].pos - value) < 0.01, name
    assert not hb.weak_edges(readings)


@pytest.mark.parametrize("dx", [1.0, 0.5])
def test_shift_positive_control_reads_the_shift(dx: float) -> None:
    frame = render(KNOWN_BAD)
    base = hb.measure_edges(frame)
    for axis in ("x", "y"):
        moved = hb.measure_edges(hb.shift_image(frame, axis, dx))
        for e in hb.EDGES_12:
            if e.name.startswith("movie") and e.axis == axis:
                continue
            assert moved[e.name].pos - base[e.name].pos == pytest.approx(dx if e.axis == axis else 0.0, abs=1e-6), e.name
    assert all(err < 1e-6 for err in hb.shift_control(frame).values())


def test_shift_control_moves_a_thin_outline_toward_its_margin() -> None:
    """At s 0.833 the movie outline is 3.3 px and its ramp ends 1 px inside the window: the control shifts it outward."""
    stage = hb.Stage(1600 / 1920, 0, 50)
    frame = render(DOM, (1600, 1000), stage)
    assert all(err < 1e-6 for err in hb.shift_control(frame, hb.EDGES_12, stage).values())


def test_shift_control_catches_a_broken_estimator(monkeypatch: pytest.MonkeyPatch) -> None:
    real = hb.measure_edge
    monkeypatch.setattr(hb, "measure_edge", lambda f, e, s=hb.IDENTITY, w=255.0: real(f, e, s, w)._replace(
        pos=round(real(f, e, s, w).pos)))
    assert max(hb.shift_control(render(DOM)).values()) >= 0.5


@pytest.mark.parametrize(("size", "stage"), [
    ((2560, 1440), hb.Stage(2560 / 1920, 0, 0)),
    ((1600, 1000), hb.Stage(1600 / 1920, 0, 50)),
    ((1920, 1080), hb.IDENTITY),
])
def test_stage_mapping_letterbox_and_scale(size: tuple[int, int], stage: hb.Stage) -> None:
    dom, gl = render(DOM, size, stage), render(KNOWN_BAD, size, stage)
    pair = hb.score_handback_pair(gl, dom, stage)
    for name, value in DOM.items():
        bias = 0.125 / (SENTINEL_STROKE * stage.s) if name.startswith("sentinel") else 0.0
        assert abs(pair["domAuthored"][name] - value) < 0.01 + bias / stage.s, name
        assert abs(pair["glAuthored"][name] - KNOWN_BAD[name]) < 0.01 + bias / stage.s, name
        assert pair["delta"][name] == pytest.approx((DOM[name] - KNOWN_BAD[name]) * stage.s, abs=0.01 + 2 * bias), name
    assert pair["max"] == pytest.approx(KB_MAX * stage.s, abs=0.01)
    assert pair["static"] < 0.01
    assert not pair["weak"]
    assert hb.score_handback_pair(dom, dom, stage)["max"] == 0.0


def test_screen_window_maps_the_authored_window() -> None:
    edge = hb.Edge("e", "step", "x", 780, 800, 690, 780)
    assert hb.screen_window(edge, hb.Stage(1600 / 1920, 0, 50)) == (650, 667, 625, 700)
    assert hb.screen_window(edge, hb.Stage(2560 / 1920, 0, 0)) == (1040, 1067, 920, 1040)


def test_premise_texture_rects() -> None:
    rects = {"slide1": {k: list(v) for k, v in hb.SLIDE1_RECTS.items()},
             "slide2": {k: list(v) for k, v in hb.SLIDE2_RECTS.items()}}
    assert hb.premise_problems(rects) == []
    bad = copy.deepcopy(rects)
    bad["slide2"]["3F22E494EE111203282E35DDB772C32F"][0] = 789.5
    assert len(hb.premise_problems(bad)) == 1
    assert hb.premise_problems(None)


def test_layer_rects_mirror_the_player_offsets_and_skip_hidden_destinations() -> None:
    def leaf(texture: str | None, x: float, y: float, w: float, h: float, hidden: bool = False, layers: list | None = None):
        node = {"initialState": {"position": {"pointX": x + w / 2, "pointY": y + h / 2},
                                 "anchorPoint": {"pointX": 0.5, "pointY": 0.5}, "width": w, "height": h, "hidden": hidden},
                "layers": layers or []}
        if texture:
            node["texture"] = texture
        return node

    root = leaf(None, 0, 0, 1920, 1080, layers=[leaf("A", 10, 20, 100, 50, layers=[leaf("B", 5, 5, 10, 10)]),
                                               leaf("C", 1, 2, 3, 4, hidden=True)])
    assert hb.layer_rects(root) == {"A": (10, 20, 100, 50), "B": (15, 25, 10, 10), "C": (1, 2, 3, 4)}
    assert "C" not in hb.layer_rects(root, visible_only=True)


def test_layer_rects_round_half_up_like_the_player_and_flag_duplicate_textures() -> None:
    def leaf(texture: str, x: float) -> dict[str, Any]:
        return {"texture": texture, "initialState": {"position": {"pointX": x, "pointY": 0.0},
                                                     "anchorPoint": {"pointX": 0.0, "pointY": 0.0}, "width": 1, "height": 1}}

    assert round(2.5) == 2 and hb.js_round6(2.5e-6) == pytest.approx(3e-6)
    root = {"initialState": {"position": {"pointX": 0.0, "pointY": 0.0}, "anchorPoint": {"pointX": 0.0, "pointY": 0.0},
                             "width": 1920, "height": 1080},
            "layers": [leaf("A", 2.5e-6), leaf("B", 1.0), leaf("B", 2.0)]}
    rects = hb.layer_rects(root)
    assert rects["A"][0] == pytest.approx(3e-6, abs=1e-12)
    assert rects["B"] is None
    premise = {"slide1": {**{k: list(v) for k, v in hb.SLIDE1_RECTS.items()}, "935F60DCEA8D1C1684E8FF95B677B4DD": None},
               "slide2": {k: list(v) for k, v in hb.SLIDE2_RECTS.items()}}
    assert len(hb.premise_problems(premise)) == 1


REAL_EXPORT = Path("/Users/anyhowclick/Desktop/work/obed-edom/output/p2-binary/html-player")


@pytest.mark.skipif(not (REAL_EXPORT / "assets" / "header.json").is_file(), reason="P2 binary fixture not present")
def test_real_fixture_premise_holds() -> None:
    assert hb.premise_problems(hb.export_texture_rects(REAL_EXPORT)) == []


# ---------------------------------------------------------------------------------------------------------------------
# HB-1 / HB-2 gate logic


SHAS = {"auto": "a" * 64, "off": "b" * 64}
SWAP_NODE = "layer-slide1"


def canvas_read(*, canvas_opacity: float = 1.0, swap_opacity: float = 0.0, swapped: bool = True) -> dict[str, Any]:
    canvas = {"id": probe.MM12_CANVAS, "connected": True, "opacity": canvas_opacity, "visibility": "visible",
              "display": "inline", "w": 1920, "h": 1080}
    node = {"id": SWAP_NODE, "connected": True, "opacity": swap_opacity, "visibility": "visible", "display": "block",
            "w": 1920, "h": 1080}
    swaps = [{"canvasId": probe.MM12_CANVAS, "id": SWAP_NODE, "node": node}] if swapped else []
    return {"canvases": [canvas], "swaps": swaps + [{"canvasId": "2-canvas", "id": "layer-slide3", "node": {**node, "opacity": 1}}]}


def make_record(arm: str, viewport: tuple[int, int] = (1920, 1080), gl: str = "off", *, engaged: bool | None = None,
                blended34: int = 2) -> dict[str, Any]:
    mode = probe.ARMS[arm]
    engaged = (mode == "auto") if engaged is None else engaged
    stage = probe.expected_stage(viewport)
    frames = [{"label": "mm12", "i": n, "el": n * 17.0, "g2": None, "draws": 5, "blended": 3 if engaged else 1}
              for n in range(80)]
    frames += [{"label": "mm34", "i": 100 + n, "el": n * 17.0, "g2": None, "draws": 3, "blended": blended34}
               for n in range(80)]
    return {
        "viewport": list(viewport), "gl": gl, "arm": arm, "mmOpacity": mode, "loggerInstalled": True,
        "output": {"mmOpacity": {"mode": "on" if mode == "auto" else "off", "sha256": SHAS[mode]}},
        "mm12Dom": [canvas_read(), canvas_read()],
        "stage": {"s": stage.s, "sy": stage.s, "ox": stage.ox, "oy": stage.oy, "offsetWidth": 1920, "offsetHeight": 1080},
        "premise": {"slide1": {k: list(v) for k, v in hb.SLIDE1_RECTS.items()},
                    "slide2": {k: list(v) for k, v in hb.SLIDE2_RECTS.items()}},
        "steps": [{"label": "mm12", "expectHash": ["#1", "#2"], "hashBefore": "#1", "hashAfter": "#2"},
                  {"label": "mm34", "expectHash": ["#7", "#8"], "hashBefore": "#7", "hashAfter": "#8"}],
        "log": {"frames": frames, "bands": [], "errors": [], "capture": {"mm34": {"frame": 179}},
                "mix": [{"label": "mm12", "textureId": t, "value": True} for t in sorted(hb.BLENDED_TEXTURES)] if engaged else []},
        "gl34": {"frame": 179},
    }


_FRAMES: dict[Any, np.ndarray] = {}


def frame_of(scene: dict[str, float], viewport: tuple[int, int]) -> np.ndarray:
    key = (tuple(sorted(scene.items())), viewport)
    if key not in _FRAMES:
        _FRAMES[key] = rgb(render(scene, viewport, probe.expected_stage(viewport)))
    return _FRAMES[key]


def make_images(gl_scene: dict[str, float], viewport: tuple[int, int] = (1920, 1080),
                gl_scene_b: dict[str, float] | None = None) -> dict[str, np.ndarray]:
    dom, gl = frame_of(DOM, viewport), frame_of(gl_scene, viewport)
    return {"s1-a": dom, "s1-b": dom, "mm12-a": gl, "mm12-b": frame_of(gl_scene_b or gl_scene, viewport),
            "b1-a": dom, "b1-b": dom, "mm34-a": dom, "mm34-b": dom}


def hb1_runs(viewport: tuple[int, int] = (1920, 1080), *, on_scene: dict[str, float] = DOM,
             off_scene: dict[str, float] = KNOWN_BAD) -> dict[str, tuple[dict[str, Any], dict[str, np.ndarray]]]:
    return {arm: (make_record(arm, viewport), make_images(on_scene if probe.ARMS[arm] == "auto" else off_scene, viewport))
            for arm in probe.ARMS}


def score_hb1(runs: dict[str, tuple[dict[str, Any], dict[str, np.ndarray]]]) -> dict[str, Any]:
    return probe.score_hb1({arm: probe.measure_run(rec, imgs, SHAS) for arm, (rec, imgs) in runs.items()})


@pytest.mark.parametrize("viewport", [(1920, 1080), (1600, 1000)])
def test_hb1_passes_when_on_arms_settle_on_the_dom(viewport: tuple[int, int]) -> None:
    result = score_hb1(hb1_runs(viewport))
    assert result["verdict"] == "PASS", result["problems"]
    s = probe.expected_stage(viewport).s
    assert result["detail"]["max"]["on"] < 0.05
    assert result["detail"]["max"]["off"] == pytest.approx(KB_MAX * s, abs=0.05)
    assert result["detail"]["cvc"] == {"on~on2": 0.0, "off~off2": 0.0}


def test_hb1_fails_when_on_arms_keep_todays_geometry() -> None:
    result = score_hb1(hb1_runs(on_scene=KNOWN_BAD))
    assert result["verdict"] == "FAIL"
    assert result["checks"] == {"onMax": False, "on2Max": False}


def test_hb1_fails_just_over_the_threshold() -> None:
    near = {**DOM, "green.right": DOM["green.right"] - 0.3}
    assert score_hb1(hb1_runs(on_scene=near))["verdict"] == "FAIL"
    under = {**DOM, "green.right": DOM["green.right"] - 0.2}
    assert score_hb1(hb1_runs(on_scene=under))["verdict"] == "PASS"


def test_hb1_inconclusive_when_the_known_bad_does_not_fail() -> None:
    result = score_hb1(hb1_runs(off_scene=DOM))
    assert result["verdict"] == "INCONCLUSIVE"
    assert any(p.startswith("KB off ") for p in result["problems"])


def test_hb1_inconclusive_when_twins_disagree() -> None:
    runs = hb1_runs()
    drift = {**DOM, "green.left": DOM["green.left"] + 0.1}
    runs["on2"] = (runs["on2"][0], make_images(drift))
    result = score_hb1(runs)
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["detail"]["cvc"]["on~on2"] == pytest.approx(0.1, abs=0.02)


def test_hb1_inconclusive_when_a_null_pair_drifts() -> None:
    runs = hb1_runs()
    runs["off"] = (runs["off"][0], make_images(KNOWN_BAD, gl_scene_b={**KNOWN_BAD, "green.top": KNOWN_BAD["green.top"] + 0.2}))
    result = score_hb1(runs)
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("control glNull" in p for p in result["problems"])


def test_hb1_inconclusive_when_the_static_control_moves() -> None:
    runs = hb1_runs()
    moved = {**DOM, "movie.left": DOM["movie.left"] + 0.3}
    runs["on"] = (runs["on"][0], make_images(moved))
    assert any("control static" in p for p in score_hb1(runs)["problems"])


def test_hb1_inconclusive_when_the_premise_breaks() -> None:
    runs = hb1_runs()
    runs["on"][0]["premise"]["slide1"]["8F325ED21D62F551E0565F9403FB150F"] = [636, 723, 180, 157]
    result = score_hb1(runs)
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("premise" in p for p in result["problems"])


@pytest.mark.parametrize(("arm", "engaged"), [("on", False), ("on2", False), ("off", True)])
def test_hb1_inconclusive_unless_engagement_matches_the_arm(arm: str, engaged: bool) -> None:
    runs = hb1_runs()
    runs[arm] = (make_record(arm, engaged=engaged), runs[arm][1])
    result = score_hb1(runs)
    assert result["verdict"] == "INCONCLUSIVE"
    assert any(p.startswith(f"{arm}: engagement") for p in result["problems"])


def test_hb1_engagement_needs_both_leaves_and_both_blended_draws() -> None:
    runs = hb1_runs()
    runs["on"][0]["log"]["mix"] = runs["on"][0]["log"]["mix"][:1]
    assert score_hb1(runs)["verdict"] == "INCONCLUSIVE"
    runs = hb1_runs()
    for f in runs["on"][0]["log"]["frames"]:
        if f["label"] == "mm12":
            f["blended"] = 2
    assert score_hb1(runs)["verdict"] == "INCONCLUSIVE"


def test_hb1_inconclusive_when_the_blend_counter_misses_keynotes_own_crossfade() -> None:
    runs = hb1_runs()
    runs["off"] = (make_record("off", blended34=1), runs["off"][1])
    assert any("instrument: 3->4" in p for p in score_hb1(runs)["problems"])


def test_hb1_inconclusive_on_integrity_failures() -> None:
    for mutate in (
        lambda r: r.update(error="Traceback\nRuntimeError: boom"),
        lambda r: r["log"]["errors"].append("x"),
        lambda r: r["steps"][0].update(hashAfter="#1"),
        lambda r: r["output"]["mmOpacity"].update(mode="off"),
        lambda r: r["stage"].update(oy=12.0),
        lambda r: r.update(loggerInstalled=False),
    ):
        runs = hb1_runs()
        mutate(runs["on"][0])
        assert score_hb1(runs)["verdict"] == "INCONCLUSIVE"


def test_hb1_inconclusive_when_a_shot_is_missing_or_the_wrong_size() -> None:
    runs = hb1_runs()
    del runs["on"][1]["b1-b"]
    assert score_hb1(runs)["verdict"] == "INCONCLUSIVE"
    runs = hb1_runs()
    runs["on"][1]["b1-b"] = runs["on"][1]["b1-b"][:1000]
    assert score_hb1(runs)["verdict"] == "INCONCLUSIVE"


def test_hb1_inconclusive_when_an_arm_is_missing() -> None:
    runs = hb1_runs()
    del runs["off2"]
    assert score_hb1(runs)["verdict"] == "INCONCLUSIVE"


def test_hb1_inconclusive_when_an_edge_is_absent() -> None:
    runs = hb1_runs()
    blank = np.zeros_like(runs["on"][1]["b1-a"])
    runs["on"] = (runs["on"][0], {**runs["on"][1], "b1-a": blank, "b1-b": blank})
    result = score_hb1(runs)
    assert result["verdict"] == "INCONCLUSIVE"
    assert any("contrast" in p for p in result["problems"])


G2_ON = {"state": "LIVE", "standDowns": [], "events": [],
         "stats": {"frameLen": 96, "glErrors": 0, "opacityUnproven": [{"slot": 4, "reason": "size"}]}}
G2_OFF = {"state": "LIVE", "standDowns": [], "events": [], "stats": {"frameLen": 88, "glErrors": 0, "opacityUnproven": []}}


def hb2_inputs(on_api: dict[str, Any] = G2_ON, off_api: dict[str, Any] = G2_OFF, on_scene: dict[str, float] = DOM):
    records = {"on": {**make_record("on", gl="auto"), "g2": {"api": copy.deepcopy(on_api)}},
               "off": {**make_record("off", gl="auto"), "g2": {"api": copy.deepcopy(off_api)}}}
    images = {"on": make_images(on_scene), "off": make_images(KNOWN_BAD)}
    return records, {arm: probe.measure_run(records[arm], images[arm], SHAS) for arm in records}


def test_hb2_passes_on_live_matching_the_dom_with_the_new_g2_baseline() -> None:
    result = probe.score_hb2(*hb2_inputs())
    assert result["verdict"] == "PASS", result["problems"]


@pytest.mark.parametrize("mutate", [
    lambda a: a["stats"].update(opacityUnproven=[{"slot": 4, "reason": "rest-opacity"}]),
    lambda a: a["stats"].update(glErrors=1),
    lambda a: a.update(standDowns=["frameLengthChanged"]),
    lambda a: a.update(state="STANDDOWN"),
])
def test_hb2_fails_on_the_on_arm_g2_stats(mutate: Any) -> None:
    api = copy.deepcopy(G2_ON)
    mutate(api)
    result = probe.score_hb2(*hb2_inputs(on_api=api))
    assert result["verdict"] == "FAIL"
    assert result["checks"]["g2Stats"] is False


def test_hb2_fails_when_live_keeps_todays_geometry() -> None:
    result = probe.score_hb2(*hb2_inputs(on_scene=KNOWN_BAD))
    assert result["verdict"] == "FAIL"
    assert result["checks"] == {"liveVsDom": False, "g2Stats": True}


@pytest.mark.parametrize("mutate", [
    lambda a: a["stats"].update(opacityUnproven=[{"slot": 4, "reason": "size"}]),
    lambda a: a.update(state="STANDDOWN"),
    lambda a: a["stats"].update(glErrors=2),
])
def test_hb2_inconclusive_when_the_off_twin_is_off_baseline(mutate: Any) -> None:
    api = copy.deepcopy(G2_OFF)
    mutate(api)
    assert probe.score_hb2(*hb2_inputs(off_api=api))["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize(("on_len", "off_len"), [(96, 85), (88, 86), (97, 88)])
def test_hb2_reports_frame_length_on_both_arms_without_checking_it(on_len: int, off_len: int) -> None:
    """`setGLFloat` writes a uniform only when its value changed, so the settle frame's call count is timing-dependent
    (headless off-arm 85 and 86). An on-arm 88 or 97 used to FAIL HB-2."""
    on_api, off_api = copy.deepcopy(G2_ON), copy.deepcopy(G2_OFF)
    on_api["stats"]["frameLen"], off_api["stats"]["frameLen"] = on_len, off_len
    result = probe.score_hb2(*hb2_inputs(on_api=on_api, off_api=off_api))
    assert result["verdict"] == "PASS", result["problems"]
    assert result["detail"]["frameLen"] == {"on": on_len, "off": off_len}


# ---------------------------------------------------------------------------------------------------------------------
# HB-3 / HB-4 reports


def band_frames(extra_width: float, frames: int = 60, jitter: float = 0.0) -> list[dict[str, Any]]:
    """A green run moving 636 -> 789 (left) and growing 174.5 -> 350.8 px, eased; `extra_width` is added at settle,
    linearly in progress (the blend)."""
    out = []
    for n in range(frames):
        z = 0.5 - 0.5 * math.cos(math.pi * n / (frames - 1))
        left = 636.0 + (789.0 - 636.0) * z + jitter * ((n * 7919) % 3 - 1) * 0.01
        width = 174.5 + (350.8 - 174.5) * z + extra_width * z
        row = np.zeros(1920)
        c = cover(1920, left, left + width)
        row += 41.0 * c
        out.append({"label": "mm12", "el": n * 25.0, "w": 1920, "profile": row.tolist()})
    return out


def test_band_extent_reads_a_box_filtered_run() -> None:
    row = 41.0 * cover(1920, 700.3, 1010.77)
    left, right, hi = hb.band_extent(row)
    assert (left, right, hi) == (pytest.approx(700.3, abs=1e-6), pytest.approx(1010.77, abs=1e-6), 41.0)
    assert hb.band_extent(np.zeros(1920)) is None


def test_inflight_compare_on_vs_off_and_control_vs_control() -> None:
    on, off, off2 = (hb.inflight_series(band_frames(w)) for w in (4.8, 0.0, 0.0))
    blend = hb.inflight_compare(on, off)
    assert blend["end"] == pytest.approx(4.8, abs=1e-3)
    assert blend["stepPerProgressMedian"] == pytest.approx(4.8, rel=0.05)
    control = hb.inflight_compare(off2, off)
    assert control["end"] == pytest.approx(0.0, abs=1e-6)
    assert control["stepPerProgressMax"] < 1e-3


def test_inflight_step_is_divided_by_the_progress_step() -> None:
    """A dropped frame doubles the raw step of the difference but not the step per unit progress."""
    on, off = hb.inflight_series(band_frames(4.8)), hb.inflight_series(band_frames(0.0))
    dropped = np.delete(on, 30, axis=0)
    full, gap = hb.inflight_compare(on, off), hb.inflight_compare(dropped, off)
    assert gap["rawStepMax"] > 1.5 * full["rawStepMax"]
    assert gap["stepPerProgressMax"] == pytest.approx(full["stepPerProgressMax"], rel=0.05)


def test_report_hb3_uses_the_saved_bands() -> None:
    records = {arm: make_record(arm) for arm in ("on", "off", "off2")}
    for arm, width in (("on", 4.8), ("off", 0.0), ("off2", 0.0)):
        records[arm]["log"]["bands"] = band_frames(width)
    report = probe.report_hb3(records)
    assert report["verdict"] == "REPORT"
    assert report["engagedOn"] is True
    assert report["onVsOff"]["end"] == pytest.approx(4.8, abs=1e-3)
    assert report["cvcOff2VsOff"]["end"] == pytest.approx(0.0, abs=1e-6)


def footprint(rect: tuple[float, float, float, float], size: tuple[int, int], stage: hb.Stage) -> np.ndarray:
    x, y, w, h = rect
    img = np.zeros((size[1], size[0]))
    for x0, x1, y0, y1 in ((x, x + w, y, y + OUTLINE), (x, x + w, y + h - OUTLINE, y + h),
                           (x, x + OUTLINE, y, y + h), (x + w - OUTLINE, x + w, y, y + h)):
        paint(img, x0 * stage.s + stage.ox, x1 * stage.s + stage.ox, y0 * stage.s + stage.oy, y1 * stage.s + stage.oy, 255)
    return img


def test_report_hb4_in_page_alpha_vs_dom_in_authored_px() -> None:
    viewport = (1600, 1000)
    stage = probe.expected_stage(viewport)
    record = make_record("on", viewport)
    dom = footprint((324.278, 705.981, 1270.273, 360.548), viewport, stage)
    gl = footprint((324.251, 706.020, 1271.498, 361.196), (1920, 1080), hb.IDENTITY)
    report = probe.report_hb4(record, {"mm34-a": dom, "mm34-b": dom, probe.GL34: gl})
    assert report["problems"] == []
    assert report["domNull"] == 0.0
    got = report["domMinusGlAuthored"]
    assert got["footprint.left"] == pytest.approx(0.027, abs=0.01)
    assert got["footprint.right"] == pytest.approx(-1.198, abs=0.01)
    stale = {**record, "gl34": {"frame": 3}}
    assert probe.report_hb4(stale, {"mm34-a": dom, "mm34-b": dom, probe.GL34: gl})["problems"]


# ---------------------------------------------------------------------------------------------------------------------
# End to end: saved evidence re-scored from disk


def full_runs(on_scene: dict[str, float] = DOM) -> dict[str, tuple[dict[str, Any], dict[str, np.ndarray]]]:
    """Every run the overall verdict needs: HB-1 at the three viewports and HB-2, keyed by `tag_of`."""
    runs = {probe.tag_of("off", vp, arm): run for vp in probe.VIEWPORTS
            for arm, run in hb1_runs(vp, on_scene=on_scene).items()}
    for arm, api, scene in (("on", G2_ON, on_scene), ("off", G2_OFF, KNOWN_BAD)):
        runs[probe.tag_of("auto", probe.VIEWPORTS[0], arm)] = (
            {**make_record(arm, gl="auto"), "g2": {"api": copy.deepcopy(api)}}, make_images(scene))
    return runs


def test_overall_needs_every_hb1_viewport_and_hb2() -> None:
    """A partial set (one viewport, or no HB-2) used to read PASS."""
    runs = full_runs()
    assert probe.score_all(runs, SHAS)["overall"] == "PASS"
    for drop in (probe.tag_of("off", (1600, 1000), "on2"), probe.tag_of("auto", (1920, 1080), "on")):
        partial = {t: r for t, r in runs.items() if t != drop}
        assert probe.score_all(partial, SHAS)["overall"] == "INCONCLUSIVE"
    only_1920 = {t: r for t, r in runs.items() if "1920x1080" in t}
    verdict = probe.score_all(only_1920, SHAS)
    assert verdict["overall"] == "INCONCLUSIVE"
    assert verdict["missing"] == ["HB-1 2560x1440", "HB-1 1600x1000"]
    assert verdict["gates"]["HB-1 1920x1080"]["verdict"] == "PASS"


def test_overall_inconclusive_when_a_run_served_another_build() -> None:
    """A record left in a reused `--out` by an older build used to merge in unnoticed."""
    runs = full_runs()
    runs[probe.tag_of("off", (2560, 1440), "on")][0]["output"]["mmOpacity"]["sha256"] = "c" * 64
    verdict = probe.score_all(runs, SHAS)
    assert verdict["overall"] == "INCONCLUSIVE"
    assert any("served player sha" in p for p in verdict["gates"]["HB-1 2560x1440"]["problems"])
    runs = full_runs()
    del runs[probe.tag_of("auto", (1920, 1080), "off")][0]["output"]["mmOpacity"]["sha256"]
    assert probe.score_all(runs, SHAS)["gates"]["HB-2"]["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize(("reads", "needle"), [
    ([canvas_read(canvas_opacity=0.0), canvas_read()], "0-canvas is not shown"),
    ([canvas_read(), canvas_read(swap_opacity=1.0)], "is shown"),
    ([canvas_read(swapped=False), canvas_read()], "no DOM node swapped"),
    ([canvas_read()], "1 in-page canvas/DOM reads"),
])
def test_hb1_inconclusive_unless_the_mm12_shot_is_the_gl_canvas(reads: list[dict[str, Any]], needle: str) -> None:
    """An early slide-2 DOM (canvas gone, or the swapped node back) reads 0 against the DOM exactly like a fixed GL
    settle, and used to PASS."""
    runs = hb1_runs()
    runs["on"][0]["mm12Dom"] = reads
    result = score_hb1(runs)
    assert result["verdict"] == "INCONCLUSIVE"
    assert any(needle in p for p in result["problems"]), result["problems"]


def test_swap_read_judges_node_visibility_in_python() -> None:
    hidden = [{**canvas_read(), "swaps": [{"canvasId": "0-canvas", "id": "n", "node": node}]}
              for node in (None, {"connected": False, "opacity": 1, "w": 5, "h": 5},
                           {"connected": True, "opacity": 1, "visibility": "hidden", "w": 5, "h": 5},
                           {"connected": True, "opacity": 1, "display": "none", "w": 5, "h": 5})]
    for read in hidden:
        assert probe.swap_problems({"mm12Dom": [read, read]}) == []


def write_runs(root: Path, runs: dict[str, tuple[dict[str, Any], dict[str, np.ndarray]]]) -> None:
    for (record, images) in runs.values():
        run_dir = root / "runs" / probe.tag_of(record["gl"], tuple(record["viewport"]), record["arm"])
        run_dir.mkdir(parents=True)
        record = copy.deepcopy(record)
        record["shots"] = {}
        for name, img in images.items():
            Image.fromarray(img).save(run_dir / f"{name}.png")
            record["shots"][name] = {"file": f"{name}.png"}
        (run_dir / "record.json").write_text(json.dumps(record))


def test_score_mode_rederives_the_verdict_from_saved_frames(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "player_shas", lambda fixture: SHAS)
    write_runs(tmp_path, full_runs())
    assert probe.main(["--score", str(tmp_path)]) == 0
    verdict = json.loads((tmp_path / "verdict.json").read_text())
    assert verdict["overall"] == "PASS"
    assert verdict["gates"]["HB-1 1920x1080"]["verdict"] == "PASS"
    assert "overall: PASS" in capsys.readouterr().out


def test_score_mode_never_passes_on_a_page_computed_verdict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe, "player_shas", lambda fixture: SHAS)
    runs = full_runs(on_scene=KNOWN_BAD)
    for record, _ in runs.values():
        record["verdict"] = "PASS"
        record["max"] = 0.0
    write_runs(tmp_path, runs)
    assert probe.main(["--score", str(tmp_path)]) == 1
    assert json.loads((tmp_path / "verdict.json").read_text())["overall"] == "FAIL"


def test_plan_runs_and_args() -> None:
    args = probe.parse_args(["--out", "x"])
    runs = probe.plan_runs(args)
    assert len(runs) == 3 * 4 + 2
    assert [(vp, arm) for vp, gl, arm in runs if gl == "auto"] == [((1920, 1080), "on"), ((1920, 1080), "off")]
    with pytest.raises(SystemExit):
        probe.parse_args(["--out", "x", "--arms", "sq"])
    with pytest.raises(SystemExit):
        probe.parse_args(["--out", "x", "--score", "y"])
