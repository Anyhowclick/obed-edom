"""Tone-independent frame-counter movie and the p2-binary fixture for the managed-OBS qualification harness.

Chromium's native <video> layer applies a midtone curve that drawImage/texImage2D (GL replay's canvas) do not, so the
P2 movie's grey-coded index patch reads several frames apart on the two paths. This movie keeps the P2 pattern's
container, geometry, rate, duration and scrolling neutral grating (`_write_h264_pattern` in
`p2_recovery_html_dissolve_live.py`) but codes the frame index as pure black / pure white blocks (luma 16 / 235, cb = cr
= 128), which both paths render as 0 / 255. Strip at the top-left, source px: blocks `BLOCK` square on a mid-grey
background, `GUTTER` apart, in the order start marker (white, black), `DATA_BITS` index bits MSB first, one even-parity
bit, end marker (black, white). Large frame digits are burnt in below the strip for humans.

The fixture builder copies the P2 fixture (never writing under output/fixtures/p2-recovery/), swaps every H.264 test-pattern
`Untitled.mov-*.mov` (html-player and html-disposable; html-unmodified keeps the Keynote originals and only its
index.html is read) for this movie at the matching duration, and writes `fixture.json`.

usage: uv run python scripts/binary_counter_movie.py --movie OUT.mov [--seconds 46.0333]
       uv run python scripts/binary_counter_movie.py --build-fixture [DEST]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from obed_edom.fixture_paths import fixture

REPO = Path(__file__).resolve().parents[1]
P2_FIXTURE = fixture("p2-recovery") / "html-adversarial"
BINARY_FIXTURE = fixture("p2-binary")
FIXTURE_BASE = "p2-recovery/html-adversarial"
MANIFEST = "fixture.json"
GENERATOR = "scripts/binary_counter_movie.py"
MOVIE_GLOB = "Untitled.mov-*.mov"
REPLACED_TREES = ("html-player", "html-disposable")
SKIPPED_TOP = frozenset({"runs"})
GENERATOR_VERSION = 1

WIDTH, HEIGHT, FPS = 1920, 540, 30
SECONDS = 46.0333
Y_BLACK, Y_WHITE, Y_BACKGROUND = 16, 235, 126
GRATING = (25, 230)
GRATING_PERIOD, GRATING_PX_PER_S = 48, 720
DATA_BITS = 12
BLOCK, GUTTER = 32, 8
START, END = (1, 0), (0, 1)
N_BLOCKS = len(START) + DATA_BITS + 1 + len(END)
BLOCK_RECTS = tuple((GUTTER + i * (BLOCK + GUTTER), GUTTER, BLOCK, BLOCK) for i in range(N_BLOCKS))
STRIP_RECT = (0, 0, GUTTER + N_BLOCKS * (BLOCK + GUTTER), BLOCK + 2 * GUTTER)
DIGITS_RECT = (40, 120, 600, 260)
DIGITS_SIZE = 220
CRF = 8
KEYINT = 30
COUNTER_FORMAT = "binary-counter-v1"
MIN_CONTRAST = 128.0
AMBIGUOUS_RATIO = 0.25


def layout() -> dict[str, Any]:
    return {
        "format": COUNTER_FORMAT, "sourceSize": [WIDTH, HEIGHT], "fps": FPS, "block": BLOCK, "gutter": GUTTER,
        "blockRects": [list(rect) for rect in BLOCK_RECTS], "stripRect": list(STRIP_RECT),
        "dataBits": DATA_BITS, "start": list(START), "end": list(END), "parity": "even",
        "minContrast": MIN_CONTRAST, "ambiguousRatio": AMBIGUOUS_RATIO,
        "order": "start(W,K), 12 index bits MSB first, even parity, end(K,W)",
        "luma": {"black": Y_BLACK, "white": Y_WHITE, "background": Y_BACKGROUND},
        "digitsRect": list(DIGITS_RECT),
    }


def decode_counter(levels: Any, counter_layout: dict[str, Any] | None) -> dict[str, Any]:
    raw = list(levels) if isinstance(levels, (list, tuple)) else []
    if not isinstance(counter_layout, dict):
        return {"counter": None, "levels": raw, "reason": "layout"}
    rects = counter_layout.get("blockRects")
    start, end = counter_layout.get("start"), counter_layout.get("end")
    data_bits = counter_layout.get("dataBits")
    minimum = counter_layout.get("minContrast")
    ambiguous_ratio = counter_layout.get("ambiguousRatio")
    integral_data_bits = isinstance(data_bits, (int, float)) and not isinstance(data_bits, bool) \
        and math.isfinite(data_bits) and data_bits > 0 and int(data_bits) == data_bits
    if counter_layout.get("format") != COUNTER_FORMAT or not isinstance(rects, list) \
            or not rects or not isinstance(start, list) or not start or not isinstance(end, list) or not end \
            or not integral_data_bits or len(rects) != len(start) + int(data_bits) + 1 + len(end) \
            or not isinstance(minimum, (int, float)) or isinstance(minimum, bool) or not math.isfinite(minimum) \
            or minimum <= 0 \
            or not isinstance(ambiguous_ratio, (int, float)) or isinstance(ambiguous_ratio, bool) \
            or not math.isfinite(ambiguous_ratio) or not 0 <= ambiguous_ratio < .5 \
            or counter_layout.get("parity") != "even":
        return {"counter": None, "levels": raw, "reason": "layout"}
    if len(raw) != len(rects) or any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in raw
    ):
        return {"counter": None, "levels": raw, "reason": "read"}
    marker_levels = [*raw[:len(start)], *raw[-len(end):]]
    marker_bits = [*start, *end]
    whites = [value for bit, value in zip(marker_bits, marker_levels, strict=True) if bit == 1]
    blacks = [value for bit, value in zip(marker_bits, marker_levels, strict=True) if bit == 0]
    contrast = min(whites) - max(blacks) if whites and blacks else -math.inf
    if contrast < minimum:
        return {"counter": None, "levels": raw, "reason": "marker"}
    white, black = statistics.mean(whites), statistics.mean(blacks)
    threshold = (white + black) / 2
    coded = raw[len(start):-len(end)]
    if any(abs(value - threshold) < ambiguous_ratio * (white - black) for value in coded):
        return {"counter": None, "levels": raw, "reason": "ambiguous"}
    bits = [int(value > threshold) for value in coded]
    if sum(bits) % 2:
        return {"counter": None, "levels": raw, "reason": "parity"}
    value = 0
    for bit in bits[:-1]:
        value = value * 2 + bit
    return {"counter": value, "levels": raw, "reason": None}


def decoder_conformance_vectors() -> list[dict[str, Any]]:
    canonical = layout()

    def levels_for(value: int) -> list[float]:
        return [255.0 if bit else 0.0 for bit in strip_bits(value)]

    levels = levels_for(1380)
    cases = [
        {"name": "counter-0", "levels": levels_for(0), "counter": 0, "reason": None},
        {"name": "ok", "levels": list(levels), "counter": 1380, "reason": None},
        {"name": "counter-4095", "levels": levels_for(4095), "counter": 4095, "reason": None},
    ]
    marker = list(levels)
    marker[0] = 0.0
    cases.append({"name": "marker", "levels": marker, "counter": None, "reason": "marker"})
    contrast_edge = list(levels)
    contrast_edge[0] = MIN_CONTRAST
    contrast_edge[-1] = MIN_CONTRAST
    cases.append({"name": "contrast-edge", "levels": contrast_edge, "counter": 1380, "reason": None})
    exact_cut = list(levels)
    exact_cut[len(START) + 2] = 127.5
    cases.append({"name": "exact-cut", "levels": exact_cut, "counter": None, "reason": "ambiguous"})
    ambiguous = list(levels)
    ambiguous[len(START) + 2] = 128.0
    cases.append({"name": "ambiguous", "levels": ambiguous, "counter": None, "reason": "ambiguous"})
    lower_edge = list(levels_for(0))
    lower_edge[len(START)] = 63.75
    cases.append({"name": "lower-band-edge", "levels": lower_edge, "counter": 0, "reason": None})
    upper_edge = list(levels_for(4095))
    upper_edge[len(START)] = 191.25
    cases.append({"name": "upper-band-edge", "levels": upper_edge, "counter": 4095, "reason": None})
    asymmetric = list(levels)
    asymmetric[0], asymmetric[-1], asymmetric[1], asymmetric[-2] = 255.0, 200.0, 0.0, 40.0
    asymmetric[len(START) + 1] = 174.0
    cases.append({"name": "asymmetric-markers", "levels": asymmetric, "counter": None, "reason": "ambiguous"})
    parity = list(levels)
    parity[len(START) + DATA_BITS] = 255.0 - parity[len(START) + DATA_BITS]
    cases.append({"name": "parity", "levels": parity, "counter": None, "reason": "parity"})
    cases.append({"name": "read", "levels": [0.0], "counter": None, "reason": "read"})
    cases.append({"name": "layout", "levels": list(levels), "layout": {}, "counter": None, "reason": "layout"})
    odd = {**canonical, "parity": "odd"}
    cases.append({"name": "odd-before-ambiguous", "levels": exact_cut, "layout": odd,
                  "counter": None, "reason": "layout"})
    cases.append({"name": "empty-end", "levels": list(levels), "layout": {**canonical, "end": []},
                  "counter": None, "reason": "layout"})
    cases.append({"name": "fractional-data-bits", "levels": list(levels),
                  "layout": {**canonical, "dataBits": DATA_BITS + .5}, "counter": None, "reason": "layout"})
    cases.append({"name": "integral-float-data-bits", "levels": list(levels),
                  "layout": {**canonical, "dataBits": float(DATA_BITS)}, "counter": 1380, "reason": None})
    cases.append({"name": "none-layout", "levels": list(levels), "layout": None,
                  "counter": None, "reason": "layout"})
    return cases


def strip_bits(index: int) -> list[int]:
    if not 0 <= index < 1 << DATA_BITS:
        raise ValueError(f"frame index {index} does not fit {DATA_BITS} bits")
    data = [(index >> (DATA_BITS - 1 - i)) & 1 for i in range(DATA_BITS)]
    return [*START, *data, sum(data) % 2, *END]


def luma_frame(index: int, font: ImageFont.FreeTypeFont) -> np.ndarray:
    x = np.arange(WIDTH)
    row = np.where((x + index * GRATING_PX_PER_S // FPS) % GRATING_PERIOD > GRATING_PERIOD // 2, GRATING[1], GRATING[0])
    y = np.broadcast_to(row.astype(np.uint8), (HEIGHT, WIDTH)).copy()
    sx, sy, sw, sh = STRIP_RECT
    y[sy:sy + sh, sx:sx + sw] = Y_BACKGROUND
    for bit, (bx, by, bw, bh) in zip(strip_bits(index), BLOCK_RECTS):
        y[by:by + bh, bx:bx + bw] = Y_WHITE if bit else Y_BLACK
    dx, dy, dw, dh = DIGITS_RECT
    digits = Image.new("L", (dw, dh), 0)
    ImageDraw.Draw(digits).text((dw // 2, dh // 2), str(index), fill=255, font=font, anchor="mm")
    mask = np.asarray(digits, np.float32) / 255
    y[dy:dy + dh, dx:dx + dw] = np.round(Y_BLACK + mask * (Y_WHITE - Y_BLACK)).astype(np.uint8)
    return y


def yuv420p(luma: np.ndarray) -> bytes:
    chroma = np.full((HEIGHT // 2) * (WIDTH // 2) * 2, 128, np.uint8)
    return luma.tobytes() + chroma.tobytes()


def frame_count(seconds: float, fps: int = FPS) -> int:
    return int(round(seconds * fps))


def write_movie(dest: Path, *, seconds: float = SECONDS, fps: int = FPS) -> dict[str, Any]:
    """H.264 baseline yuv420p MP4 bytes (named like the Keynote export), CRF `CRF`, keyframe every `KEYINT` frames."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.mp4")
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "yuv420p",
           "-s", f"{WIDTH}x{HEIGHT}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "baseline",
           "-crf", str(CRF), "-g", str(KEYINT), "-an", "-movflags", "+faststart", str(tmp)]
    font = ImageFont.load_default(size=DIGITS_SIZE)
    frames = frame_count(seconds, fps)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for index in range(frames):
            proc.stdin.write(yuv420p(luma_frame(index, font)))
    finally:
        proc.stdin.close()
    stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
    if proc.wait() != 0 or not tmp.is_file():
        raise RuntimeError(f"ffmpeg encode failed: {stderr[-800:]}")
    tmp.replace(dest)
    return {"path": str(dest), "bytes": dest.stat().st_size, "sha256": sha256_file(dest), "seconds": seconds, "fps": fps, "frames": frames}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def movie_seconds(path: Path) -> float:
    return float(path.name.rsplit("-", 1)[-1].removesuffix(".mov"))


def read_manifest(fixture: Path) -> dict[str, Any]:
    path = fixture / MANIFEST
    return json.loads(path.read_text()) if path.is_file() else {}


def verify_fixture(fixture: Path) -> dict[str, Any] | None:
    """None for a fixture without a manifest; else the manifest and movie sha256s, after checking every replaced movie
    on disk against its manifest sha256 (SystemExit on a mismatch)."""
    path = fixture / MANIFEST
    if not path.is_file():
        return None
    manifest = json.loads(path.read_text())
    bad = [r["path"] for r in manifest.get("replaced") or [] if not (fixture / r["path"]).is_file()
           or sha256_file(fixture / r["path"]) != r["sha256"]]
    if bad or not manifest.get("replaced"):
        raise SystemExit(f"fixture {fixture} does not match its {MANIFEST}: {bad[:5] or 'no replaced movies'}")
    return {"manifestSha256": sha256_file(path), "movieSha256": sorted({r["sha256"] for r in manifest["replaced"]})}


def build_fixture(dest: Path = BINARY_FIXTURE, source: Path = P2_FIXTURE) -> dict[str, Any]:
    source, dest = source.resolve(), dest.expanduser().resolve()
    if "p2-recovery" in dest.parts or dest == source:
        raise SystemExit(f"refusing to write {dest}: never under output/fixtures/p2-recovery/")
    if dest.exists() and any(dest.iterdir()):
        if read_manifest(dest).get("generator") != GENERATOR:
            raise SystemExit(f"refusing to replace {dest}: not empty and its {MANIFEST} does not name {GENERATOR}")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for item in sorted(source.iterdir()):
        if item.name in SKIPPED_TOP:
            continue
        (shutil.copytree if item.is_dir() else shutil.copy2)(item, dest / item.name)
    movies: dict[float, dict[str, Any]] = {}
    replaced = []
    for tree in REPLACED_TREES:
        for path in sorted((dest / tree).rglob(MOVIE_GLOB)):
            seconds = movie_seconds(path)
            if seconds not in movies:
                movies[seconds] = write_movie(dest / f".movie-{seconds}.mov", seconds=seconds)
            shutil.copyfile(movies[seconds]["path"], path)
            replaced.append({"path": str(path.relative_to(dest)), "sha256": movies[seconds]["sha256"], "seconds": seconds})
    for info in movies.values():
        Path(info["path"]).unlink()
    if not replaced:
        raise SystemExit(f"no {MOVIE_GLOB} under {REPLACED_TREES} in {source}")
    manifest = {"counter": "binary", "base": FIXTURE_BASE, "source": str(source), "generator": GENERATOR,
                "generatorVersion": GENERATOR_VERSION, "encode": {"codec": "libx264", "profile": "baseline", "pixFmt": "yuv420p",
                                                                 "crf": CRF, "keyint": KEYINT},
                "movies": [{k: v for k, v in info.items() if k != "path"} for info in movies.values()], "replaced": replaced,
                "layout": layout()}
    (dest / MANIFEST).write_text(json.dumps(manifest, indent=1))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Binary frame-counter movie / p2-binary fixture builder (offline ffmpeg only).")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--movie", type=Path, help="write one movie here")
    group.add_argument("--build-fixture", type=Path, nargs="?", const=BINARY_FIXTURE, metavar="DEST",
                       help=f"copy {P2_FIXTURE} to DEST (default {BINARY_FIXTURE}) with binary-counter movies")
    parser.add_argument("--seconds", type=float, default=SECONDS)
    args = parser.parse_args(argv)
    if args.movie:
        print(json.dumps(write_movie(args.movie, seconds=args.seconds)))
    else:
        manifest = build_fixture(args.build_fixture)
        print("BUILT", args.build_fixture, json.dumps(manifest["movies"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
