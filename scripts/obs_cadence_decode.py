"""Decode a lossless OBS recording of the managed-OBS `rec` session into per-phase cadence.

Per output frame: the phase from the 24 px corner marker (grey or anything else = unmeasured), and the burnt-in movie counter
(grey = round(N * 255/219 + c), N mod 220) from the fixture's index patch. The patch ROI is
searched per phase (slide 1's native movie sits a few px off), the grey offset c is fitted
over every decoded frame, and `rawRepeatFrac` (raw grey unchanged) is reported independently
of the fit.

usage: uv run python scripts/obs_cadence_decode.py <recording> [--json out.json]
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Iterator

import imageio_ffmpeg
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p2_recovery_html_adversarial import INDEX_PATCH_ROI, _decode_index_patch  # noqa: E402

PHASES: dict[str, tuple[int, int, int]] = {
    "slide1-native": (255, 0, 0),
    "slide1-paused": (0, 0, 255),
    "slide1-resumed": (255, 255, 0),
}
MARK_BOX = (4, 20)
MARK_MAX_DIST = 40.0
STEP = 255 / 219
MOD = 220
EDGE_TRIM = 2
SEARCH_PX = 4
SEARCH_SAMPLES = 40
FIT_GRID = np.linspace(-0.6, 1.2, 181)


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


def phase_stats(greys: list[int | None], c: float, fps: float) -> dict[str, Any]:
    seq = greys[EDGE_TRIM:-EDGE_TRIM] if len(greys) > 2 * EDGE_TRIM else []
    counter = [None if g is None else int(round((g - c) / STEP)) % MOD for g in seq]
    deltas = [(b - a) % MOD for a, b in zip(counter, counter[1:]) if a is not None and b is not None]
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
        "maxRun": max((len(list(run)) for _, run in itertools.groupby(counter)), default=0),
    }


def decode_recording(recording: Path) -> dict[str, Any]:
    meta, frames = read_frames(recording)
    fps = float(meta["fps"])
    windows: dict[str, list[np.ndarray]] = {name: [] for name in PHASES}
    total = unmarked = 0
    for frame in frames:
        total += 1
        name, _ = phase_of(frame)
        if name is None:
            unmarked += 1
            continue
        windows[name].append(patch_window(frame))
    offsets: dict[str, Any] = {}
    greys: dict[str, list[int | None]] = {}
    for name, wins in windows.items():
        offset, hits, sampled = best_offset(wins)
        offsets[name] = {"offset": list(offset), "sampledDecodable": hits, "sampled": sampled}
        greys[name] = [decode_window(w, offset) for w in wins]
    c, residual, residual_c0 = fit_grey_offset(g for seq in greys.values() for g in seq if g is not None)
    return {
        "file": str(recording),
        "size": list(meta["size"]),
        "fps": fps,
        "nFrames": total,
        "unmarkedFrames": unmarked,
        "roi": list(INDEX_PATCH_ROI),
        "roiOffsets": offsets,
        "c": round(c, 3),
        "maxResidual": round(residual, 3),
        "residualAtC0": round(residual_c0, 3),
        "phases": {name: (phase_stats(seq, c, fps) if seq else None) for name, seq in greys.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Per-phase cadence of a lossless recording of the managed-OBS rec session.")
    parser.add_argument("recording", type=Path)
    parser.add_argument("--json", type=Path, help="write the decode result here")
    args = parser.parse_args(argv)
    result = decode_recording(args.recording)
    print(f"{result['nFrames']} frames @ {result['fps']} fps, unmarked {result['unmarkedFrames']}, "
          f"fit c {result['c']} (max residual {result['maxResidual']}, c=0 {result['residualAtC0']})")
    for name, stats in result["phases"].items():
        print(f"  {name:18s} offset {result['roiOffsets'][name]['offset']}  {stats}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=1))
        print("WRITTEN", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
