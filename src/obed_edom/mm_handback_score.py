"""Pure sub-pixel edge scorer for the Magic Move hand-back geometry gates (plan `keynote_live_handback_geometry` §4).

Frames are plain 2-D luminance / alpha arrays (or RGB(A), reduced to Rec. 709 luma). Step edges use the area method on a
band-averaged profile, strokes the first moment of (p - lo) / (white - lo). ROIs are authored px on the P2 fixture and
map to the frame by `screen = authored * s + origin`; positions come back in frame (screen) px. No browser dependency.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np

MM_EFFECT = "apple:magic-move-implied-motion-path"
MIN_CONTRAST = 10.0
EDGE_WINDOW = 2
STROKE_WINDOW = 3


class Stage(NamedTuple):
    s: float = 1.0
    ox: float = 0.0
    oy: float = 0.0

    def origin(self, axis: str) -> float:
        return self.ox if axis == "x" else self.oy

    def to_authored(self, pos: float, axis: str) -> float:
        return (pos - self.origin(axis)) / self.s


IDENTITY = Stage()


class Edge(NamedTuple):
    """`kind` is `step` (both plateaus from the profile), `white-step` (bright plateau = `white`) or `stroke`. The window
    [lo, hi) runs along `axis`; the profile averages the band [band_lo, band_hi) across it."""

    name: str
    kind: str
    axis: str
    lo: float
    hi: float
    band_lo: float
    band_hi: float


class Reading(NamedTuple):
    pos: float
    width: float | None
    contrast: float


GREEN_EDGES = (
    Edge("green.left", "step", "x", 780, 800, 690, 780),
    Edge("green.right", "step", "x", 1128, 1152, 690, 970),
    Edge("green.top", "step", "y", 663, 687, 800, 1130),
    Edge("green.bottom", "step", "y", 972, 996, 1072, 1135),
)
SENTINEL_EDGES = (
    Edge("sentinel.left", "stroke", "x", 536, 554, 730, 785),
    Edge("sentinel.right", "stroke", "x", 712, 730, 730, 785),
    Edge("sentinel.top", "stroke", "y", 714, 734, 560, 705),
)
HANDBACK_EDGES = GREEN_EDGES + SENTINEL_EDGES
STATIC_EDGES = (
    Edge("movie.left", "white-step", "x", 100, 108, 800, 1050),
    Edge("movie.top", "white-step", "y", 786, 794, 120, 530),
    Edge("movie.right", "white-step", "x", 1062, 1070, 990, 1055),
)
EDGES_12 = HANDBACK_EDGES + STATIC_EDGES
EDGES_34 = (
    Edge("footprint.left", "white-step", "x", 318, 327, 720, 1050),
    Edge("footprint.top", "white-step", "y", 700, 709, 400, 1500),
    Edge("footprint.right", "white-step", "x", 1593, 1601, 720, 1050),
    Edge("footprint.bottom", "white-step", "y", 1065, 1073, 400, 1500),
)

SLIDE1_RECTS = {
    "1FDCDA05A9D9B69366C48F1E0402F644": (975.0, 722.0, 266.0, 236.0),
    "8F325ED21D62F551E0565F9403FB150F": (636.0, 723.0, 178.0, 157.0),
    "935F60DCEA8D1C1684E8FF95B677B4DD": (105.0, 791.0, 960.0, 276.0),
}
SLIDE2_RECTS = {
    "A637A0C40C2B97864E68906B63E15AC5": (542.0, 721.0, 181.0, 161.0),
    "3F22E494EE111203282E35DDB772C32F": (789.0, 673.0, 353.0, 313.0),
    "935F60DCEA8D1C1684E8FF95B677B4DD": (105.0, 791.0, 960.0, 276.0),
}
BLENDED_TEXTURES = frozenset({"1FDCDA05A9D9B69366C48F1E0402F644", "8F325ED21D62F551E0565F9403FB150F"})
RECT_TOL = 1e-6


def luminance(image: Any) -> np.ndarray:
    frame = np.asarray(image, dtype=float)
    if frame.ndim == 2:
        return frame
    return frame[..., :3] @ np.array([0.2126, 0.7152, 0.0722])


def screen_window(edge: Edge, stage: Stage = IDENTITY) -> tuple[int, int, int, int]:
    """The edge's window [a, b) along its axis and band [c, d) across it, in frame px."""
    across = "y" if edge.axis == "x" else "x"
    o, o2 = stage.origin(edge.axis), stage.origin(across)
    return (math.floor(edge.lo * stage.s + o), math.ceil(edge.hi * stage.s + o),
            round(edge.band_lo * stage.s + o2), round(edge.band_hi * stage.s + o2))


def profile(frame: np.ndarray, edge: Edge, stage: Stage = IDENTITY) -> tuple[int, np.ndarray]:
    a, b, c, d = screen_window(edge, stage)
    return a, (frame[c:d, a:b].mean(axis=0) if edge.axis == "x" else frame[a:b, c:d].mean(axis=1))


def measure_edge(frame: np.ndarray, edge: Edge, stage: Stage = IDENTITY, white: float = 255.0) -> Reading:
    a, p = profile(frame, edge, stage)
    if edge.kind == "stroke":
        lo = float(np.median(np.r_[p[:STROKE_WINDOW], p[-STROKE_WINDOW:]]))
        w = np.clip((p - lo) / (white - lo), 0, None)
        total = float(w.sum())
        centre = float((w * (np.arange(a, a + len(p)) + 0.5)).sum() / total) if total > 0 else math.nan
        return Reading(centre, total, float(p.max() - lo))
    e0, e1 = float(p[:EDGE_WINDOW].mean()), float(p[-EDGE_WINDOW:].mean())
    if e0 == e1 and edge.kind == "step":
        return Reading(math.nan, None, 0.0)
    if e1 > e0:
        hi = white if edge.kind == "white-step" else e1
        return Reading(a + float(((hi - p) / (hi - e0)).sum()), None, hi - e0)
    hi = white if edge.kind == "white-step" else e0
    return Reading(a + float(((p - e1) / (hi - e1)).sum()), None, hi - e1)


def measure_edges(image: Any, edges: Iterable[Edge] = EDGES_12, stage: Stage = IDENTITY,
                  white: float = 255.0) -> dict[str, Reading]:
    frame = luminance(image)
    return {e.name: measure_edge(frame, e, stage, white) for e in edges}


def weak_edges(readings: dict[str, Reading], min_contrast: float = MIN_CONTRAST) -> list[str]:
    return [n for n, r in readings.items() if not (r.contrast >= min_contrast and math.isfinite(r.pos))]


def deltas(a: dict[str, Reading], b: dict[str, Reading], names: Iterable[str] | None = None) -> dict[str, float]:
    """Per edge b - a, in frame px."""
    return {n: b[n].pos - a[n].pos for n in (a if names is None else names)}


def max_abs(values: dict[str, float]) -> float:
    return max((abs(v) for v in values.values()), default=math.nan)


def shift_image(image: Any, axis: str, dx: float) -> np.ndarray:
    """The luminance frame moved by `dx` px along `axis` (linear interpolation between integer rolls)."""
    frame = luminance(image)
    k = math.floor(dx)
    t = dx - k
    ax = 1 if axis == "x" else 0
    return (1 - t) * np.roll(frame, k, axis=ax) + t * np.roll(frame, k + 1, axis=ax)


def shift_control(image: Any, edges: Sequence[Edge] = EDGES_12, stage: Stage = IDENTITY, white: float = 255.0,
                  shifts: Sequence[float] = (1.0, 0.5)) -> dict[str, float]:
    """Per shift size, the max |measured - expected| edge move over x and y shifts. Each edge is read on the frame moved
    toward its larger window margin (a thin outline's ramp must stay inside its window); off-axis edges must not move."""
    base = measure_edges(image, edges, stage, white)
    sign = {}
    for e in edges:
        a, b, _, _ = screen_window(e, stage)
        sign[e.name] = 1.0 if b - base[e.name].pos >= base[e.name].pos - a else -1.0
    out = {}
    for dx in shifts:
        errors = []
        for axis in ("x", "y"):
            moved = {d: measure_edges(shift_image(image, axis, d * dx), edges, stage, white) for d in (1.0, -1.0)}
            for e in edges:
                d = sign[e.name] if e.axis == axis else 1.0
                expected = d * dx if e.axis == axis else 0.0
                errors.append(abs(moved[d][e.name].pos - base[e.name].pos - expected))
        out[f"{dx:g}"] = max(errors)
    return out


def score_handback_pair(gl: Any, dom: Any, stage: Stage = IDENTITY, white: float = 255.0,
                        edges: Sequence[Edge] = EDGES_12) -> dict[str, Any]:
    """Settled GL frame vs first DOM frame of the same stage: per-edge DOM - GL (frame px), its max over the hand-back
    edges, the static-control max and the per-edge authored positions."""
    g, d = measure_edges(gl, edges, stage, white), measure_edges(dom, edges, stage, white)
    delta = deltas(g, d)
    return {
        "delta": delta,
        "max": max_abs({n: v for n, v in delta.items() if n in {e.name for e in HANDBACK_EDGES}}),
        "static": max_abs({n: v for n, v in delta.items() if n in {e.name for e in STATIC_EDGES}}),
        "glAuthored": {e.name: stage.to_authored(g[e.name].pos, e.axis) for e in edges},
        "domAuthored": {e.name: stage.to_authored(d[e.name].pos, e.axis) for e in edges},
        "weak": sorted(set(weak_edges(g)) | set(weak_edges(d))),
    }


def layer_rects(layer: dict[str, Any], *, visible_only: bool = False) -> dict[str, tuple[float, float, float, float]]:
    """Texture id -> (x, y, w, h) of every leaf, the player's own `bounds.offset` sum (rounded to 1e-6 per level)."""
    out: dict[str, tuple[float, float, float, float]] = {}

    def walk(node: dict[str, Any], x: float, y: float) -> None:
        t, a = node["initialState"], node["initialState"]["anchorPoint"]
        x += round(1e6 * (t["position"]["pointX"] - a["pointX"] * t["width"])) / 1e6
        y += round(1e6 * (t["position"]["pointY"] - a["pointY"] * t["height"])) / 1e6
        if node.get("texture") and not (visible_only and t.get("hidden")):
            out[node["texture"]] = (x, y, float(t["width"]), float(t["height"]))
        for child in node.get("layers") or []:
            walk(child, x, y)

    walk(layer, 0.0, 0.0)
    return out


def export_texture_rects(export_root: Path) -> dict[str, dict[str, list[float]]]:
    """Slide 1's Magic Move leaves and slide 2's visible `events[0]` leaves, as read from an HTML export."""
    assets = Path(export_root) / "assets"
    slides = json.loads((assets / "header.json").read_text())["slideList"]
    s1, s2 = (json.loads((assets / sid / f"{sid}.json").read_text()) for sid in slides[:2])
    moves = [e for ev in s1["events"] for e in ev["effects"] if e["name"] == MM_EFFECT]
    if len(moves) != 1:
        return {"slide1": {}, "slide2": {}}
    return {"slide1": {k: list(v) for k, v in layer_rects(moves[0]["baseLayer"]).items()},
            "slide2": {k: list(v) for k, v in layer_rects(s2["events"][0]["baseLayer"], visible_only=True).items()}}


def premise_problems(rects: dict[str, dict[str, Sequence[float]]] | None) -> list[str]:
    problems = []
    for side, expected in (("slide1", SLIDE1_RECTS), ("slide2", SLIDE2_RECTS)):
        got = (rects or {}).get(side) or {}
        for tid, rect in expected.items():
            seen = got.get(tid)
            if seen is None or len(seen) != 4 or any(abs(u - v) > RECT_TOL for u, v in zip(seen, rect)):
                problems.append(f"premise: {side} texture {tid[:6]} rect {seen} != {list(rect)}")
    return problems


def band_extent(values: Sequence[float], level_min: float = MIN_CONTRAST, window: int = 6) -> tuple[float, float, float] | None:
    """Left and right area-method edges of the one bright run in a 1-D profile, and its plateau (median above
    `level_min`). None when the profile has no plateau or the run touches the profile's ends."""
    p = np.asarray(values, dtype=float)
    bright = p > level_min
    if not bright.any():
        return None
    hi = float(np.median(p[bright]))
    idx = np.flatnonzero(p > 0.5 * hi)
    left, right = int(idx[0]), int(idx[-1])
    if left < window or right + window + 1 > len(p):
        return None
    wl = np.clip(p[left - window:left + window], 0, hi)
    wr = np.clip(p[right - window + 1:right + window + 1], 0, hi)
    return (left - window + float(((hi - wl) / hi).sum()), right - window + 1 + float((wr / hi).sum()), hi)


def inflight_series(frames: Iterable[dict[str, Any]]) -> np.ndarray:
    """Rows (el, left, right) of every frame whose band has one measurable bright run, in elapsed order."""
    rows = []
    for f in frames:
        ext = band_extent(f.get("profile") or [])
        if ext is not None:
            rows.append((float(f["el"]), ext[0], ext[1]))
    rows.sort()
    return np.asarray(rows, dtype=float).reshape(-1, 3)


def _progress(series: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    if len(series) < 3:
        return None
    centre, width = (series[:, 1] + series[:, 2]) / 2, series[:, 2] - series[:, 1]
    span = centre[-1] - centre[0]
    if abs(span) < 1.0:
        return None
    return (centre - centre[0]) / span, width


def inflight_compare(cand: np.ndarray, twin: np.ndarray, min_dprogress: float = 0.01) -> dict[str, Any]:
    """Width(cand) - width(twin) against move progress (each run's own centre path, 0 -> 1); the per-frame step of that
    difference divided by the frame's progress step (a dropped frame would otherwise double a raw step)."""
    a, b = _progress(cand), _progress(twin)
    if a is None or b is None:
        return {"frames": [len(cand), len(twin)], "error": "no measurable move in one run"}
    (pa, wa), (pb, wb) = a, b
    ob = np.argsort(pb)
    inside = (pa >= pb[ob][0]) & (pa <= pb[ob][-1])
    p, dw = pa[inside], wa[inside] - np.interp(pa[inside], pb[ob], wb[ob])
    order = np.argsort(p)
    p, dw = p[order], dw[order]
    dp, ddw = np.diff(p), np.diff(dw)
    keep = dp >= min_dprogress
    rate = np.abs(ddw[keep] / dp[keep])
    return {
        "frames": [len(cand), len(twin)],
        "matched": int(inside.sum()),
        "end": float(wa[-1] - wb[-1]),
        "rawStepMax": float(np.abs(ddw).max()) if len(ddw) else None,
        "stepPerProgressMax": float(rate.max()) if len(rate) else None,
        "stepPerProgressMedian": float(np.median(rate)) if len(rate) else None,
        "curve": [[round(float(x), 3), round(float(y), 3)] for x, y in zip(p, dw)],
    }
