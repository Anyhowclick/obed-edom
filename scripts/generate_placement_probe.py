#!/usr/bin/env python3
"""Generate the pinned placement and freshness probe movies."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

WIDTH = 1920
HEIGHT = 540
FPS = 30
DURATION_S = 3
SEED = 7
FFMPEG = Path("/opt/homebrew/bin/ffmpeg")
X264 = Path("/opt/homebrew/opt/x264")
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src" / "obed_edom" / "data"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pattern(width: int = WIDTH, height: int = HEIGHT, seed: int = SEED) -> np.ndarray:
    image = np.zeros((height, width, 3), np.uint8)
    rng = np.random.default_rng(seed)
    x3, y2 = width // 3, height // 2
    x = 4
    for bar_width in [1, 1, 2, 2, 3, 3, 4, 5, 6, 8, 1, 2, 1, 3]:
        if x + bar_width >= x3:
            break
        image[2:y2, x : x + bar_width] = 255
        x += bar_width * 2 + 1
    while x + 2 < x3:
        image[2:y2, x] = 255
        x += 3
    y = 3
    for bar_height in [1, 1, 2, 2, 3, 4, 6, 1, 2, 1]:
        if y + bar_height >= y2:
            break
        image[y : y + bar_height, x3 : 2 * x3] = 255
        y += bar_height * 2 + 1
    while y + 2 < y2:
        image[y, x3 : 2 * x3] = 255
        y += 3
    yy, xx = np.mgrid[0:y2, 2 * x3 : width]
    image[0:y2, 2 * x3 : width] = (((yy + xx) & 1) * 255)[..., None]
    for index in range(16):
        image[y2:height, index * x3 // 16 : (index + 1) * x3 // 16] = int(round(index * 255 / 15))
    colors = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 0),
        (0, 255, 255),
        (255, 0, 255),
        (200, 120, 60),
        (60, 120, 200),
    ]
    for index, color in enumerate(colors):
        image[y2:height, x3 + index * x3 // 8 : x3 + (index + 1) * x3 // 8] = color
    blocks = rng.integers(0, 2, ((height - y2 + 3) // 4, (width - 2 * x3 + 3) // 4)) * 255
    image[y2:height, 2 * x3 : width] = np.kron(blocks, np.ones((4, 4)))[
        : height - y2, : width - 2 * x3, None
    ]
    image[0, :] = image[-1, :] = 255
    image[:, 0] = image[:, -1] = 255
    return image


def motion_frame(index: int) -> np.ndarray:
    image = np.full((HEIGHT, WIDTH, 3), 64, np.uint8)
    for bit in range(16):
        value = (index >> (15 - bit)) & 1
        x0 = bit * WIDTH // 16
        x1 = (bit + 1) * WIDTH // 16
        image[:, x0:x1] = 255 if value else 0
    image[0, :] = image[-1, :] = 255
    image[:, 0] = image[:, -1] = 255
    return image


def encode_args(source: str, output: Path) -> list[str]:
    return [
        str(FFMPEG),
        "-y",
        "-loglevel",
        "error",
        "-loop",
        "1",
        "-i",
        source,
        "-t",
        str(DURATION_S),
        "-r",
        str(FPS),
        "-vf",
        "scale=out_color_matrix=bt709:out_range=tv",
        "-c:v",
        "libx264",
        "-profile:v",
        "high",
        "-qp",
        "1",
        "-pix_fmt",
        "yuv420p",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-color_range",
        "tv",
        "-x264-params",
        "colorprim=bt709:transfer=bt709:colormatrix=bt709",
        "-movflags",
        "+faststart",
        str(output),
    ]


def encode_pattern(png: Path, output: Path) -> list[str]:
    args = encode_args(str(png), output)
    subprocess.run(args, check=True)
    return args


def encode_motion(frames: Path, output: Path) -> None:
    args = [
        str(FFMPEG),
        "-y",
        "-loglevel",
        "error",
        "-framerate",
        str(FPS),
        "-i",
        str(frames / "%03d.png"),
        "-t",
        str(DURATION_S),
        "-vf",
        "scale=out_color_matrix=bt709:out_range=tv",
        "-c:v",
        "libx264",
        "-profile:v",
        "high",
        "-qp",
        "1",
        "-pix_fmt",
        "yuv420p",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-color_range",
        "tv",
        "-x264-params",
        "colorprim=bt709:transfer=bt709:colormatrix=bt709:keyint=30:min-keyint=30:scenecut=0",
        "-an",
        "-movflags",
        "+faststart",
        str(output),
    ]
    subprocess.run(args, check=True)


def version_line(*args: str) -> str:
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout.splitlines()[0]


def generate(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="obed-placement-") as raw:
        temporary = Path(raw)
        pattern_png = temporary / "placement_probe.png"
        Image.fromarray(pattern()).save(pattern_png)
        pattern_out = output_dir / "placement_probe.mp4"
        argv = encode_pattern(pattern_png, pattern_out)
        repeat_out = temporary / "placement_probe-repeat.mp4"
        encode_pattern(pattern_png, repeat_out)
        frames = temporary / "motion"
        frames.mkdir()
        for index in range(FPS * DURATION_S):
            Image.fromarray(motion_frame(index)).save(frames / f"{index:03d}.png")
        motion_out = output_dir / "placement_motion.mp4"
        encode_motion(frames, motion_out)
        normalized_argv = [
            "{ffmpeg}"
            if value == str(FFMPEG)
            else "{input}"
            if value == str(pattern_png)
            else "{output}"
            if value == str(pattern_out)
            else value
            for value in argv
        ]
        ffmpeg_version = version_line(str(FFMPEG), "-version")
        x264_version = f"x264 {X264.resolve().name}"
        manifest = {
            "schemaVersion": 1,
            "pattern": {
                "file": pattern_out.name,
                "sha256": sha256(pattern_out),
                "bytes": pattern_out.stat().st_size,
                "width": WIDTH,
                "height": HEIGHT,
                "fps": FPS,
                "durationS": DURATION_S,
                "frameTimeS": 1,
                "colorTuple": ["bt709", "bt709", "bt709", False],
            },
            "motion": {
                "file": motion_out.name,
                "sha256": sha256(motion_out),
                "bytes": motion_out.stat().st_size,
                "width": WIDTH,
                "height": HEIGHT,
                "fps": FPS,
                "durationS": DURATION_S,
            },
            "generator": {
                "sha256": sha256(Path(__file__)),
                "python": platform.python_version(),
                "numpy": np.__version__,
                "pillow": Image.__version__,
                "ffmpeg": ffmpeg_version,
                "x264": x264_version,
                "argv": normalized_argv,
                "pngSha256": sha256(pattern_png),
                "repeatSha256": sha256(repeat_out),
            },
        }
    manifest_path = output_dir / "placement_probe.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DATA)
    args = parser.parse_args(argv)
    manifest = generate(args.output_dir.resolve())
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
