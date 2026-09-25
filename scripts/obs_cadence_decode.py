"""Decode a lossless OBS recording of a managed-OBS qualification session into per-phase cadence.

Per output frame: the phase from the 24 px corner marker (grey or anything else = unmeasured), and the burnt-in movie counter
(grey = round(N * 255/219 + c), N mod 220) from the fixture's index patch. The patch ROI is
searched per phase (slide 1's native movie sits a few px off), the grey offset c is fitted
over every decoded frame, and `rawRepeatFrac` (raw grey unchanged) is reported independently
of the fit. `backwardSteps` excludes loop wraps (`wrapSteps`, given `--loop-frames`);
`ringMaxDelta` is the max |RGB delta| in the 2..8 px ring around each `--ring` rect vs the phase's
first frame (`ringDiag`: worst frame, pixels over the slide2-live ring and over 20, optional crops);
`staticMaxDelta` is the same inside each `--static` rect eroded 4 px. Only codecs in `LOSSLESS_CODECS` are decoded.

usage: uv run python scripts/obs_cadence_decode.py <recording> [--json out.json] [--ring X,Y,W,H] [--loop-frames N]
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import imageio_ffmpeg
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p2_recovery_html_adversarial import INDEX_PATCH_ROI, _decode_index_patch  # noqa: E402

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
LOSSLESS_CODECS = frozenset({"utvideo"})
RING_PX = (2, 8)
STATIC_ERODE_PX = 4
EDGE_BAND_PX = 4
CROP_PAD = 24
WRAP_TOL = 2
MARK_BOX = (4, 20)
MARK_MAX_DIST = 40.0
STEP = 255 / 219
MOD = 220
EDGE_TRIM = 2
SEARCH_PX = 4
SEARCH_SAMPLES = 40
FIT_GRID = np.linspace(-0.6, 1.2, 181)


Rect = tuple[float, float, float, float]


class NotLossless(ValueError):
    pass


def check_lossless(meta: dict[str, Any]) -> None:
    if meta.get("codec") not in LOSSLESS_CODECS:
        raise NotLossless(f"codec {meta.get('codec')!r} (pix_fmt {meta.get('pix_fmt')!r}) is not in {sorted(LOSSLESS_CODECS)}")


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


def best_offset(windows: list[np.ndarray], radius: int = SEARCH_PX, samples: int = SEARCH_SAMPLES) -> tuple[tuple[int, int], int, int]:
    """(dx, dy) that decodes the most sampled frames; ties go to the smallest shift."""
    if not windows:
        return (0, 0), 0, 0
    picks = [windows[i] for i in np.linspace(0, len(windows) - 1, min(samples, len(windows))).round().astype(int)]
    offsets = sorted(itertools.product(range(-radius, radius + 1), repeat=2), key=lambda o: (abs(o[0]) + abs(o[1]), o))
    scored = [(sum(decode_window(w, o) is not None for w in picks), o) for o in offsets]
    best = max(scored, key=lambda item: item[0])
    return best[1], best[0], len(picks)


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


def _circular(a: int, b: int) -> int:
    d = (a - b) % MOD
    return min(d, MOD - d)


def is_wrap(a: int, b: int, loop_frames: int | None) -> bool:
    return loop_frames is not None and _circular(a, (loop_frames - 1) % MOD) <= WRAP_TOL and _circular(b, 0) <= WRAP_TOL


def trimmed(seq: list[Any]) -> list[Any]:
    return seq[EDGE_TRIM:-EDGE_TRIM] if len(seq) > 2 * EDGE_TRIM else []


def counters(greys: list[int | None], c: float) -> list[int | None]:
    return [None if g is None else int(round((g - c) / STEP)) % MOD for g in greys]


def phase_stats(greys: list[int | None], c: float, fps: float, loop_frames: int | None = None) -> dict[str, Any]:
    seq = trimmed(greys)
    counter = counters(seq, c)
    pairs = [(a, b) for a, b in zip(counter, counter[1:]) if a is not None and b is not None]
    deltas = [(b - a) % MOD for a, b in pairs]
    backward = [(a, b) for a, b in pairs if (b - a) % MOD > MOD // 2]
    wraps = sum(1 for a, b in backward if is_wrap(a, b, loop_frames))
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
        "advancePerS": round(sum(deltas) / seconds, 2) if seconds else None,
        "distinctPerS": round(sum(1 for d in deltas if d) / seconds, 2) if seconds else None,
        "gapsGE3": sum(1 for d in deltas if d >= 3),
        "maxForwardStep": max((d for d in deltas if d <= MOD // 2), default=None),
        "backwardSteps": len(backward) - wraps,
        "wrapSteps": wraps,
        "maxRun": max((len(list(run)) for _, run in itertools.groupby(counter)), default=0),
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


def decode_recording(recording: Path, *, rings: Sequence[Rect] | None = None, statics: Sequence[Rect] | None = None,
                     ring_exclude: Sequence[Rect] = (), loop_frames: int | None = None, crops_dir: Path | None = None) -> dict[str, Any]:
    meta, frames = read_frames(recording)
    check_lossless(meta)
    fps = float(meta["fps"])
    windows: dict[str, list[np.ndarray]] = {name: [] for name in PHASES}
    indices: dict[str, list[int]] = {name: [] for name in PHASES}
    ring_refs: dict[str, np.ndarray] = {}
    ring_max: dict[str, int] = {}
    ring_worst: dict[str, tuple[int, np.ndarray]] = {}
    ring_last: dict[str, tuple[int, np.ndarray]] = {}
    masks: list[np.ndarray] | None = None
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
        windows[name].append(patch_window(frame))
        if rings:
            if masks is None:
                excluded = np.zeros(frame.shape[:2], bool)
                for rect in ring_exclude:
                    excluded |= edge_band(frame.shape, rect)
                masks = [ring_mask(frame.shape, rect) & ~excluded for rect in rings]
            if name not in ring_refs:
                ring_refs[name] = frame.copy()
            delta = max(ring_max_delta(ring_refs[name], frame, rect, mask) for rect, mask in zip(rings, masks))
            if delta > ring_max.get(name, -1):
                ring_worst[name] = (index, frame.copy())
            ring_max[name] = max(ring_max.get(name, 0), delta)
            ring_last[name] = (index, frame)
        if statics:
            if smask is None:
                smask = np.logical_or.reduce([static_mask(frame.shape, rect) for rect in statics])
            if name not in static_refs:
                static_refs[name] = frame.copy()
            static_max[name] = max(static_max.get(name, 0), masked_max_delta(static_refs[name], frame, smask))
    offsets: dict[str, Any] = {}
    greys: dict[str, list[int | None]] = {}
    for name, wins in windows.items():
        if name in NOT_DECODED:
            continue
        offset, hits, sampled = best_offset(wins)
        offsets[name] = {"offset": list(offset), "sampledDecodable": hits, "sampled": sampled}
        greys[name] = [decode_window(w, offset) for w in wins]
    c, residual, residual_c0 = fit_grey_offset(g for seq in greys.values() for g in seq if g is not None)
    ring_diag: dict[str, Any] = {}
    if rings and masks is not None:
        union = np.logical_or.reduce(masks)
        tau = ring_max.get("slide2-live", 0)
        for name, (worst, frame) in ring_worst.items():
            first = indices[name][0]
            diag = {"worstFrame": worst, "worstSinceFirstS": round((worst - first) / fps, 3), "firstFrame": first,
                    "lastFrame": ring_last[name][0], "overTau": over_threshold(ring_refs[name], frame, union, tau),
                    "over20": over_threshold(ring_refs[name], frame, union, 20)}
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
        "roi": list(INDEX_PATCH_ROI),
        "roiOffsets": offsets,
        "c": round(c, 3),
        "maxResidual": round(residual, 3),
        "residualAtC0": round(residual_c0, 3),
        "loopFrames": loop_frames,
        "rings": [list(r) for r in rings] if rings else None,
        "ringMaxDelta": ring_max if rings else None,
        "ringExclude": [list(r) for r in ring_exclude],
        "ringPixels": int(np.logical_or.reduce(masks).sum()) if masks else None,
        "ringDiag": ring_diag if rings else None,
        "statics": [list(r) for r in statics] if statics else None,
        "staticMaxDelta": static_max if statics else None,
        "phases": {name: (phase_stats(seq, c, fps, loop_frames) if seq else None) for name, seq in greys.items()},
        "endpoints": {name: endpoints(counters(trimmed(seq), c), trimmed(indices[name])) for name, seq in greys.items()},
        "handbackCounters": counters(greys.get("slide2-handback") or [], c),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Per-phase cadence of a lossless recording of the managed-OBS rec session.")
    parser.add_argument("recording", type=Path)
    parser.add_argument("--json", type=Path, help="write the decode result here")
    parser.add_argument("--ring", action="append", default=[], help="X,Y,W,H rect (output px) for ringMaxDelta; repeatable")
    parser.add_argument("--static", action="append", default=[], help="X,Y,W,H rect (output px) for staticMaxDelta; repeatable")
    parser.add_argument("--loop-frames", type=int, help="the looping movie's frame count, for wrapSteps")
    parser.add_argument("--crops", type=Path, help="save ring crops (reference, worst, last frame) here")
    args = parser.parse_args(argv)
    rings = [tuple(float(v) for v in ring.split(",")) for ring in args.ring]
    statics = [tuple(float(v) for v in rect.split(",")) for rect in args.static]
    result = decode_recording(args.recording, rings=rings or None, statics=statics or None, loop_frames=args.loop_frames,
                              crops_dir=args.crops)
    print(f"{result['nFrames']} frames @ {result['fps']} fps ({result['codec']}/{result['pixFmt']}), unmarked {result['unmarkedFrames']}, "
          f"fit c {result['c']} (max residual {result['maxResidual']}, c=0 {result['residualAtC0']})")
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
