"""Decode a lossless OBS recording of a managed-OBS qualification session into per-phase cadence.

Per output frame: the phase from the 24 px corner marker (grey or anything else = unmeasured), and the burnt-in movie counter.
`counter="grey"` (the P2 fixture): grey = round(N * 255/219 + c), N mod 220, from the index patch; the grey offset c is
fitted over every decoded frame and `rawRepeatFrac` (raw grey unchanged) is reported independently of the fit.
`counter="binary"` (the p2-binary fixture, `binary_counter_movie.py`): the black/white bit strip read at `geometry`
(output origin x, y and scale of the movie), thresholded at the midpoint of its white/black markers; the frame index
itself (no wrap), None on bad markers, an ambiguous block or bad parity (`roiOffsets[phase].fails`). `counter="auto"`
picks binary when the strip decodes on most sampled frames. The patch / strip offset is searched per phase (slide 1's
native movie sits a few px off). Steps bridge undecodable frames (`maxStepPerFrame` = forward step / frames elapsed).
`backwardSteps` excludes loop wraps (`wrapSteps`, given `--loop-frames`);
`ringMaxDelta` is the max |RGB delta| in the 2..8 px ring around each `--ring` rect vs the phase's
first frame (`ringDiag`: worst frame, pixels over the slide2-live ring and over 20, optional crops);
`staticMaxDelta` is the same inside each `--static` rect eroded 4 px. Only the lossless codec (4:2:0) pairs in
`LOSSLESS_FORMATS` are decoded.

usage: uv run python scripts/obs_cadence_decode.py <recording> [--json out.json] [--ring X,Y,W,H] [--loop-frames N] [--counter auto]
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence

import imageio_ffmpeg
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import binary_counter_movie as binary  # noqa: E402
from p2_recovery_html_adversarial import INDEX_PATCH_ROI, MOVIE_ROI, _decode_index_patch  # noqa: E402

PHASES: dict[str, tuple[int, int, int]] = {
    "slide1-native": (255, 0, 0),
    "slide1-paused": (0, 0, 255),
    "slide1-resumed": (255, 255, 0),
    "slide2-live": (0, 255, 0),
    "slide2-hidden": (255, 0, 255),
    "slide2-reshown": (0, 255, 255),
    "slide2-handback": (255, 128, 0),
    "slide2-after": (128, 0, 255),
}
NOT_DECODED = frozenset({"slide2-hidden"})
LOSSLESS_FORMATS = frozenset({("utvideo", "yuv420p")})
RING_PX = (2, 8)
STATIC_ERODE_PX = 4
EDGE_BAND_PX = 4
CROP_PAD = 24
WRAP_TOL = 2
LOOP_SEEK_SKIP = 2
MARK_BOX = (4, 20)
MARK_MAX_DIST = 40.0
STEP = 255 / 219
MOD = 220
EDGE_TRIM = 2
NEAR_MAX_STEP = 3
SEARCH_PX = 4
SEARCH_SAMPLES = 40
BINARY_SEARCH_PX = 8
FIT_GRID = np.linspace(-0.6, 1.2, 181)
COUNTERS = ("grey", "binary")
BINARY_MIN_CONTRAST = 128
BINARY_AMBIGUOUS = 0.25
AUTO_BINARY_MIN = 0.5


Rect = tuple[float, float, float, float]
Geometry = tuple[float, float, float]
MOVIE_GEOMETRY: Geometry = (MOVIE_ROI[0], MOVIE_ROI[1], MOVIE_ROI[2] / binary.WIDTH)


class NotLossless(ValueError):
    pass


def check_lossless(meta: dict[str, Any]) -> None:
    codec, pix_fmt = meta.get("codec"), str(meta.get("pix_fmt") or "").split("(", 1)[0]
    if (codec, pix_fmt) not in LOSSLESS_FORMATS:
        raise NotLossless(f"{codec!r}/{meta.get('pix_fmt')!r} is not an allowlisted lossless codec (4:2:0) {sorted(LOSSLESS_FORMATS)}")


def read_frames(recording: Path) -> tuple[dict[str, Any], Iterator[np.ndarray]]:
    reader = imageio_ffmpeg.read_frames(str(recording), pix_fmt="rgb24")
    meta = next(reader)
    width, height = meta["size"]
    return meta, (np.frombuffer(raw, np.uint8).reshape(height, width, 3) for raw in reader)


def phase_of(frame: np.ndarray) -> tuple[str | None, float]:
    lo, hi = MARK_BOX
    mark = frame[lo:hi, lo:hi].reshape(-1, 3).mean(axis=0)
    name, dist = min(((key, float(np.abs(mark - np.array(rgb)).max())) for key, rgb in PHASES.items()), key=lambda item: item[1])
    return (name if dist < MARK_MAX_DIST else None), dist


def patch_window(frame: np.ndarray, roi: tuple[int, int, int, int] = INDEX_PATCH_ROI, margin: int = SEARCH_PX) -> np.ndarray:
    x, y, w, h = roi
    return frame[y - margin:y + h + margin, x - margin:x + w + margin].copy()


def decode_window(window: np.ndarray, offset: tuple[int, int], roi: tuple[int, int, int, int] = INDEX_PATCH_ROI, margin: int = SEARCH_PX) -> int | None:
    return _decode_index_patch(window, (margin + offset[0], margin + offset[1], roi[2], roi[3]))


def read_strip(frame: np.ndarray, origin: tuple[float, float], scale: float) -> tuple[int | None, str]:
    """(frame index, "ok") off the binary strip at `origin` (output px of the movie's top-left) and `scale`, else
    (None, "bounds" | "marker" | "ambiguous" | "parity")."""
    half = max(1, int(binary.BLOCK * scale / 4))
    levels = []
    for bx, by, bw, bh in binary.BLOCK_RECTS:
        cx, cy = int(round(origin[0] + (bx + bw / 2) * scale)), int(round(origin[1] + (by + bh / 2) * scale))
        if cx - half < 0 or cy - half < 0 or cx + half >= frame.shape[1] or cy + half >= frame.shape[0]:
            return None, "bounds"
        levels.append(float(frame[cy - half:cy + half + 1, cx - half:cx + half + 1, :3].mean()))
    markers = list(zip(binary.START + binary.END, levels[:len(binary.START)] + levels[-len(binary.END):]))
    whites, blacks = [v for bit, v in markers if bit], [v for bit, v in markers if not bit]
    if min(whites) - max(blacks) < BINARY_MIN_CONTRAST:
        return None, "marker"
    white, black = float(np.mean(whites)), float(np.mean(blacks))
    threshold = (white + black) / 2
    coded = levels[len(binary.START):-len(binary.END)]
    if any(abs(v - threshold) < BINARY_AMBIGUOUS * (white - black) for v in coded):
        return None, "ambiguous"
    bits = [int(v > threshold) for v in coded]
    if sum(bits) % 2:
        return None, "parity"
    return int("".join(map(str, bits[:-1])), 2), "ok"


def strip_window(frame: np.ndarray, geometry: Geometry = MOVIE_GEOMETRY, margin: int = BINARY_SEARCH_PX) -> np.ndarray:
    x, y, scale = geometry
    sx, sy, sw, sh = binary.STRIP_RECT
    x0, y0 = int(np.floor(x + sx * scale)) - margin, int(np.floor(y + sy * scale)) - margin
    x1, y1 = int(np.ceil(x + (sx + sw) * scale)) + margin, int(np.ceil(y + (sy + sh) * scale)) + margin
    out = np.zeros((y1 - y0, x1 - x0, 3), np.uint8)
    fx0, fy0, fx1, fy1 = max(0, x0), max(0, y0), min(frame.shape[1], x1), min(frame.shape[0], y1)
    if fx1 > fx0 and fy1 > fy0:
        out[fy0 - y0:fy1 - y0, fx0 - x0:fx1 - x0] = frame[fy0:fy1, fx0:fx1, :3]
    return out


def read_strip_window(window: np.ndarray, offset: tuple[int, int], geometry: Geometry = MOVIE_GEOMETRY,
                      margin: int = BINARY_SEARCH_PX) -> tuple[int | None, str]:
    x, y, scale = geometry
    sx, sy = binary.STRIP_RECT[:2]
    origin_x = x - (np.floor(x + sx * scale) - margin) + offset[0]
    origin_y = y - (np.floor(y + sy * scale) - margin) + offset[1]
    return read_strip(window, (float(origin_x), float(origin_y)), scale)


def best_offset(windows: list[np.ndarray], radius: int = SEARCH_PX, samples: int = SEARCH_SAMPLES,
                decode: Callable[[np.ndarray, tuple[int, int]], int | None] | None = None,
                centre: bool = False) -> tuple[tuple[int, int], int, int]:
    """(dx, dy) that decodes the most sampled frames; ties go to the smallest shift, or with `centre` to the offset
    nearest the centroid of the tied plateau."""
    if not windows:
        return (0, 0), 0, 0
    decode = decode or decode_window
    picks = [windows[i] for i in np.linspace(0, len(windows) - 1, min(samples, len(windows))).round().astype(int)]
    offsets = sorted(itertools.product(range(-radius, radius + 1), repeat=2), key=lambda o: (abs(o[0]) + abs(o[1]), o))
    scored = [(sum(decode(w, o) is not None for w in picks), o) for o in offsets]
    best = max(scored, key=lambda item: item[0])
    if centre:
        plateau = np.array([o for hits, o in scored if hits == best[0]], float)
        mid = plateau.mean(axis=0)
        return min((o for hits, o in scored if hits == best[0]), key=lambda o: (np.hypot(o[0] - mid[0], o[1] - mid[1]), o)), best[0], len(picks)
    return best[1], best[0], len(picks)


def best_strip_offset(windows: list[np.ndarray], geometry: Geometry) -> tuple[tuple[int, int], int, int]:
    return best_offset(windows, BINARY_SEARCH_PX, decode=lambda w, o: read_strip_window(w, o, geometry)[0], centre=True)


def fit_grey_offset(greys: Iterable[int]) -> tuple[float, float, float]:
    """(c, max residual in counter steps at c, residual at c = 0)."""
    values = np.array(list(greys), float)
    if values.size == 0:
        return 0.0, float("nan"), float("nan")

    def residual(c: float) -> float:
        x = (values - c) / STEP
        return float(np.abs(x - np.round(x)).max())

    c = float(min(FIT_GRID, key=residual))
    return c, residual(c), residual(0.0)


def modulus(counter: str) -> int | None:
    return MOD if counter == "grey" else None


def _circular(a: int, b: int, mod: int | None = MOD) -> int:
    if mod is None:
        return abs(a - b)
    d = (a - b) % mod
    return min(d, mod - d)


def step(a: int, b: int, mod: int | None = MOD) -> int:
    return b - a if mod is None else (b - a) % mod


def is_backward(delta: int, mod: int | None = MOD) -> bool:
    return delta < 0 if mod is None else delta > mod // 2


def wrap_step(a: int, b: int, loop_frames: int | None, mod: int | None = MOD) -> int | None:
    """Frames advanced from `a` through the loop point to `b`, or None when `a` is not within `WRAP_TOL` of the last frame."""
    if loop_frames is None:
        return None
    last = loop_frames - 1 if mod is None else (loop_frames - 1) % mod
    pre = step(a, last, mod)
    if pre > WRAP_TOL:
        return None
    return pre + 1 + step(0, b, mod)


def is_wrap(a: int, b: int, loop_frames: int | None, mod: int | None = MOD) -> bool:
    """A loop wrap advances at most a normal step (`WRAP_TOL`) plus the browser's own loop-seek skip (`LOOP_SEEK_SKIP`,
    0-2 frames on the element's clock in 40 headless wraps, `.agents/reviews/continuity-loopmode/gates-r1.md`)."""
    advanced = wrap_step(a, b, loop_frames, mod)
    return advanced is not None and advanced <= WRAP_TOL + LOOP_SEEK_SKIP


def trimmed(seq: list[Any]) -> list[Any]:
    return seq[EDGE_TRIM:-EDGE_TRIM] if len(seq) > 2 * EDGE_TRIM else []


def counters(greys: list[int | None], c: float, counter: str = "grey") -> list[int | None]:
    if counter == "binary":
        return list(greys)
    return [None if g is None else int(round((g - c) / STEP)) % MOD for g in greys]


def phase_stats(greys: list[int | None], c: float, fps: float, loop_frames: int | None = None, counter: str = "grey") -> dict[str, Any]:
    """`greys` are raw patch greys (grey) or frame indices (binary). Histogram, repeat, distinct and gap stats use
    adjacent decoded pairs; backward/wrap steps, `maxForwardStep` and `maxStepPerFrame` (forward step / output frames
    elapsed) pair each decoded frame with the previous decoded one, so an undecodable frame cannot hide a jump.
    `maxStepWindow` is that worst pair's positions in the trimmed phase, `undecodableNearMaxStep` the undecodable frames
    within `NEAR_MAX_STEP` of it."""
    mod = modulus(counter)
    seq = trimmed(greys)
    values = counters(seq, c, counter)
    decoded = [(i, v) for i, v in enumerate(values) if v is not None]
    links = [(i, j, a, b, step(a, b, mod)) for (i, a), (j, b) in zip(decoded, decoded[1:])]
    deltas = [d for i, j, _, _, d in links if j - i == 1]
    backward = [(a, b) for _, _, a, b, d in links if is_backward(d, mod)]
    wrap_steps = [wrap_step(a, b, loop_frames, mod) for a, b in backward if is_wrap(a, b, loop_frames, mod)]
    wraps = len(wrap_steps)
    forward = [(d / (j - i), d, i, j) for i, j, _, _, d in links if not is_backward(d, mod)]
    worst = max(forward, default=None)
    near = sum(1 for v in values[max(0, worst[2] - NEAR_MAX_STEP):worst[3] + NEAR_MAX_STEP + 1] if v is None) if worst else None
    raw_repeats = sum(1 for a, b in zip(seq, seq[1:]) if a is not None and b is not None and a == b)
    hist = Counter(deltas)
    seconds = len(seq) / fps if fps else 0.0
    return {
        "frames": len(seq),
        "decodable": sum(g is not None for g in seq),
        "decodableFrac": round(sum(g is not None for g in seq) / len(seq), 3) if seq else None,
        "deltaHist": {str(k): v for k, v in sorted(hist.items())},
        "repeatFrac": round(hist.get(0, 0) / len(deltas), 3) if deltas else None,
        "rawRepeatFrac": round(raw_repeats / len(deltas), 3) if deltas else None,
        "advancePerS": round(sum(d for d in deltas if not is_backward(d, mod)) / seconds, 2) if seconds else None,
        "distinctPerS": round(sum(1 for d in deltas if d) / seconds, 2) if seconds else None,
        "gapsGE3": sum(1 for d in deltas if d >= 3),
        "maxForwardStep": max((d for _, d, _, _ in forward), default=None),
        "maxStepPerFrame": round(worst[0], 3) if worst else None,
        "maxStepWindow": [worst[2], worst[3]] if worst else None,
        "undecodableNearMaxStep": near,
        "backwardSteps": len(backward) - wraps,
        "wrapSteps": wraps,
        "maxWrapStep": max(wrap_steps, default=None),
        "maxRun": max((len(list(run)) for _, run in itertools.groupby(values)), default=0),
    }


def dilate(rect: Rect, px: int, shape: tuple[int, ...]) -> tuple[int, int, int, int]:
    x, y, w, h = rect
    return (max(0, int(np.floor(x)) - px), max(0, int(np.floor(y)) - px),
            min(shape[1], int(np.ceil(x + w)) + px), min(shape[0], int(np.ceil(y + h)) + px))


def ring_mask(shape: tuple[int, ...], rect: Rect, inner: int = RING_PX[0], outer: int = RING_PX[1]) -> np.ndarray:
    mask = np.zeros(shape[:2], bool)
    x0, y0, x1, y1 = dilate(rect, outer, shape)
    mask[y0:y1, x0:x1] = True
    x0, y0, x1, y1 = dilate(rect, inner, shape)
    mask[y0:y1, x0:x1] = False
    return mask


def edge_band(shape: tuple[int, ...], rect: Rect, px: int = EDGE_BAND_PX) -> np.ndarray:
    mask = np.zeros(shape[:2], bool)
    x0, y0, x1, y1 = dilate(rect, px, shape)
    mask[y0:y1, x0:x1] = True
    x0, y0, x1, y1 = dilate(rect, -px, shape)
    mask[y0:y1, x0:x1] = False
    return mask


def ring_max_delta(reference: np.ndarray, frame: np.ndarray, rect: Rect, mask: np.ndarray | None = None) -> int:
    mask = ring_mask(frame.shape, rect) if mask is None else mask
    if not mask.any():
        return 0
    return int(np.abs(frame[mask].astype(np.int16) - reference[mask].astype(np.int16)).max())


def static_mask(shape: tuple[int, ...], rect: Rect, erode: int = STATIC_ERODE_PX) -> np.ndarray:
    mask = np.zeros(shape[:2], bool)
    x0, y0, x1, y1 = dilate(rect, -erode, shape)
    mask[y0:y1, x0:x1] = True
    return mask


def masked_max_delta(reference: np.ndarray, frame: np.ndarray, mask: np.ndarray) -> int:
    if not mask.any():
        return 0
    return int(np.abs(frame[mask].astype(np.int16) - reference[mask].astype(np.int16)).max())


def over_threshold(reference: np.ndarray, frame: np.ndarray, mask: np.ndarray, tau: int) -> dict[str, Any]:
    over = mask & (np.abs(frame.astype(np.int16) - reference.astype(np.int16)).max(axis=2) > tau)
    ys, xs = np.nonzero(over)
    return {"tau": tau, "count": int(over.sum()),
            "bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1] if xs.size else None}


def save_crops(crops_dir: Path, phase: str, frames: dict[str, np.ndarray], rects: Sequence[Rect]) -> list[str]:
    shape = next(iter(frames.values())).shape
    boxes = [dilate(rect, RING_PX[1] + CROP_PAD, shape) for rect in rects]
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    crops_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for tag, frame in frames.items():
        path = crops_dir / f"{phase}-{tag}.png"
        Image.fromarray(np.ascontiguousarray(frame[y0:y1, x0:x1])).save(path)
        paths.append(str(path))
    return paths


def endpoints(counter: list[int | None], index: list[int]) -> dict[str, list[int] | None]:
    decoded = [(i, n) for i, n in zip(index, counter) if n is not None]
    return {"first": list(decoded[0]) if decoded else None, "last": list(decoded[-1]) if decoded else None}


def choose_counter(counter: str, binary_windows: dict[str, list[np.ndarray]], geometry: Geometry) -> str:
    if counter != "auto":
        return counter
    scored = [best_strip_offset(wins, geometry)[1:] for wins in binary_windows.values() if wins]
    hits, sampled = sum(h for h, _ in scored), sum(n for _, n in scored)
    return "binary" if sampled and hits >= AUTO_BINARY_MIN * sampled else "grey"


def decode_recording(recording: Path, *, rings: Sequence[Rect] | None = None, statics: Sequence[Rect] | None = None,
                     ring_exclude: Sequence[Rect] = (), loop_frames: int | None = None, crops_dir: Path | None = None,
                     counter: str = "auto", geometry: Geometry = MOVIE_GEOMETRY) -> dict[str, Any]:
    if counter not in (*COUNTERS, "auto"):
        raise ValueError(f"counter {counter!r} not in {COUNTERS} or auto")
    meta, frames = read_frames(recording)
    check_lossless(meta)
    fps = float(meta["fps"])
    windows: dict[str, list[np.ndarray]] = {name: [] for name in PHASES}
    strips: dict[str, list[np.ndarray]] = {name: [] for name in PHASES}
    indices: dict[str, list[int]] = {name: [] for name in PHASES}
    ring_refs: dict[str, np.ndarray] = {}
    ring_max: dict[str, int] = {}
    ring_worst: dict[str, tuple[int, np.ndarray]] = {}
    ring_last: dict[str, tuple[int, np.ndarray]] = {}
    over20_max: dict[str, tuple[int, int, np.ndarray]] = {}
    masks: list[np.ndarray] | None = None
    union: np.ndarray | None = None
    static_refs: dict[str, np.ndarray] = {}
    static_max: dict[str, int] = {}
    smask: np.ndarray | None = None
    total = unmarked = 0
    for index, frame in enumerate(frames):
        total += 1
        name, _ = phase_of(frame)
        if name is None:
            unmarked += 1
            continue
        indices[name].append(index)
        if name in NOT_DECODED:
            continue
        if counter != "binary":
            windows[name].append(patch_window(frame))
        if counter != "grey":
            strips[name].append(strip_window(frame, geometry))
        if rings:
            if masks is None:
                excluded = np.zeros(frame.shape[:2], bool)
                for rect in ring_exclude:
                    excluded |= edge_band(frame.shape, rect)
                masks = [ring_mask(frame.shape, rect) & ~excluded for rect in rings]
                union = np.logical_or.reduce(masks)
            if name not in ring_refs:
                ring_refs[name] = frame.copy()
            delta = max(ring_max_delta(ring_refs[name], frame, rect, mask) for rect, mask in zip(rings, masks))
            if delta > ring_max.get(name, -1):
                ring_worst[name] = (index, frame.copy())
            ring_max[name] = max(ring_max.get(name, 0), delta)
            ring_last[name] = (index, frame)
            count = int((np.abs(frame[union].astype(np.int16) - ring_refs[name][union].astype(np.int16)).max(axis=1) > 20).sum())
            if name not in over20_max or count > over20_max[name][0]:
                over20_max[name] = (count, index, frame.copy())
        if statics:
            if smask is None:
                smask = np.logical_or.reduce([static_mask(frame.shape, rect) for rect in statics])
            if name not in static_refs:
                static_refs[name] = frame.copy()
            static_max[name] = max(static_max.get(name, 0), masked_max_delta(static_refs[name], frame, smask))
    counter = choose_counter(counter, strips, geometry)
    offsets: dict[str, Any] = {}
    values: dict[str, list[int | None]] = {}
    for name in PHASES:
        if name in NOT_DECODED:
            continue
        if counter == "grey":
            offset, hits, sampled = best_offset(windows[name])
            offsets[name] = {"offset": list(offset), "sampledDecodable": hits, "sampled": sampled}
            values[name] = [decode_window(w, offset) for w in windows[name]]
        else:
            offset, hits, sampled = best_strip_offset(strips[name], geometry)
            reads = [read_strip_window(w, offset, geometry) for w in strips[name]]
            fails = Counter(reason for _, reason in reads if reason != "ok")
            offsets[name] = {"offset": list(offset), "sampledDecodable": hits, "sampled": sampled, "fails": dict(sorted(fails.items()))}
            values[name] = [value for value, _ in reads]
    if counter == "grey":
        c, residual, residual_c0 = fit_grey_offset(g for seq in values.values() for g in seq if g is not None)
    else:
        c, residual, residual_c0 = 0.0, None, None
    ring_diag: dict[str, Any] = {}
    if rings and union is not None:
        tau = ring_max.get("slide2-live", 0)
        for name, (worst, frame) in ring_worst.items():
            first = indices[name][0]
            count, over_index, over_frame = over20_max[name]
            diag = {"worstFrame": worst, "worstSinceFirstS": round((worst - first) / fps, 3), "firstFrame": first,
                    "lastFrame": ring_last[name][0], "overTau": over_threshold(ring_refs[name], frame, union, tau),
                    "over20": {**over_threshold(ring_refs[name], over_frame, union, 20), "frame": over_index}}
            if crops_dir is not None:
                diag["crops"] = save_crops(crops_dir, name, {"reference": ring_refs[name], "worst": frame,
                                                             "last": ring_last[name][1]}, rings)
            ring_diag[name] = diag
    return {
        "file": str(recording),
        "codec": meta.get("codec"),
        "pixFmt": meta.get("pix_fmt"),
        "size": list(meta["size"]),
        "fps": fps,
        "nFrames": total,
        "unmarkedFrames": unmarked,
        "phaseFrames": {name: len(idx) for name, idx in indices.items()},
        "counter": counter,
        "roi": list(INDEX_PATCH_ROI) if counter == "grey" else None,
        "geometry": list(geometry) if counter == "binary" else None,
        "roiOffsets": offsets,
        "c": round(c, 3),
        "maxResidual": None if residual is None else round(residual, 3),
        "residualAtC0": None if residual_c0 is None else round(residual_c0, 3),
        "loopFrames": loop_frames,
        "rings": [list(r) for r in rings] if rings else None,
        "ringMaxDelta": ring_max if rings else None,
        "ringExclude": [list(r) for r in ring_exclude],
        "ringPixels": int(union.sum()) if union is not None else None,
        "ringDiag": ring_diag if rings else None,
        "statics": [list(r) for r in statics] if statics else None,
        "staticMaxDelta": static_max if statics else None,
        "phases": {name: (phase_stats(seq, c, fps, loop_frames, counter) if seq else None) for name, seq in values.items()},
        "endpoints": {name: endpoints(counters(trimmed(seq), c, counter), trimmed(indices[name])) for name, seq in values.items()},
        "handbackCounters": counters(values.get("slide2-handback") or [], c, counter),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Per-phase cadence of a lossless recording of the managed-OBS rec session.")
    parser.add_argument("recording", type=Path)
    parser.add_argument("--json", type=Path, help="write the decode result here")
    parser.add_argument("--ring", action="append", default=[], help="X,Y,W,H rect (output px) for ringMaxDelta; repeatable")
    parser.add_argument("--static", action="append", default=[], help="X,Y,W,H rect (output px) for staticMaxDelta; repeatable")
    parser.add_argument("--loop-frames", type=int, help="the looping movie's frame count, for wrapSteps")
    parser.add_argument("--crops", type=Path, help="save ring crops (reference, worst, last frame) here")
    parser.add_argument("--counter", choices=(*COUNTERS, "auto"), default="auto", help="movie counter (auto: binary if its strip decodes)")
    parser.add_argument("--geometry", help="X,Y,SCALE of the movie in output px (binary counter; default the P2 slide-2 rect)")
    args = parser.parse_args(argv)
    rings = [tuple(float(v) for v in ring.split(",")) for ring in args.ring]
    statics = [tuple(float(v) for v in rect.split(",")) for rect in args.static]
    geometry = tuple(float(v) for v in args.geometry.split(",")) if args.geometry else MOVIE_GEOMETRY
    result = decode_recording(args.recording, rings=rings or None, statics=statics or None, loop_frames=args.loop_frames,
                              crops_dir=args.crops, counter=args.counter, geometry=geometry)
    print(f"{result['nFrames']} frames @ {result['fps']} fps ({result['codec']}/{result['pixFmt']}), unmarked {result['unmarkedFrames']}, "
          f"counter {result['counter']}, fit c {result['c']} (max residual {result['maxResidual']}, c=0 {result['residualAtC0']})")
    for name, stats in result["phases"].items():
        print(f"  {name:18s} offset {result['roiOffsets'][name]['offset']}  ring {(result['ringMaxDelta'] or {}).get(name)}"
              f"  static {(result['staticMaxDelta'] or {}).get(name)}  {stats}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=1))
        print("WRITTEN", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
