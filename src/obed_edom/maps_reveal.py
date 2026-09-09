"""Brush-on reveal movies for landmark objects: numpy/PIL frames piped to the bundled ffmpeg as ProRes 4444 (alpha)."""

from __future__ import annotations

import hashlib
import math
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterator

import numpy as np
from PIL import Image

from obed_edom.maps_movie import ffmpeg_exe, safe_slide_id
from obed_edom.watercolour import _noise, _norm, _strokes

MAX_LONG_SIDE = 1600
REVEAL_DIR = "reveal"
REVEAL_ALGO_VERSION = 1


def reveal_path(output_dir: Path, slide_id: str, church_id: str, audience: str = "lw") -> Path:
    suffix = "-cg" if audience == "cg" else ""
    return Path(output_dir) / REVEAL_DIR / f"{safe_slide_id(slide_id)}-{safe_slide_id(church_id)}{suffix}.mov"


def reveal_seed(church_id: str) -> int:
    return int.from_bytes(hashlib.sha256(church_id.encode()).digest()[:8], "big")


def _fingerprint_path(dest: Path) -> Path:
    return dest.with_suffix(dest.suffix + ".fp")


def reveal_fingerprint(
    asset: Path, *, duration: float, opacity: float, seed: int, width: int, height: int
) -> str:
    stat = asset.stat()
    payload = "|".join(
        str(part)
        for part in (stat.st_mtime_ns, stat.st_size, duration, opacity, seed, width, height, REVEAL_ALGO_VERSION)
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def reveal_stale(dest: Path, fingerprint: str) -> bool:
    fp_path = _fingerprint_path(dest)
    if not dest.is_file() or not fp_path.is_file():
        return True
    return fp_path.read_text().strip() != fingerprint


def _smoothstep(a: np.ndarray) -> np.ndarray:
    return a * a * (3 - 2 * a)


def _progress_field(shape: tuple[int, int], rng: np.random.Generator) -> np.ndarray:
    h, w = shape
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    base = (x / max(1, w - 1) + (1 - y / max(1, h - 1))) / 2
    blob = _norm(_noise(rng, shape, sigma=max(h, w) / 24))
    bristle = _strokes(shape, rng, angles=(math.radians(35),), length=48, bias=0.2, scale=1.0)
    field = np.clip(base * 0.78 + 0.14 * blob + 0.08 * bristle, 0, 1)
    lo, hi = float(field.min()), float(field.max())
    return (field - lo) / (hi - lo) if hi > lo else field


def reveal_frames(rgba: np.ndarray, *, count: int, seed: int) -> Iterator[np.ndarray]:
    rng = np.random.default_rng(seed)
    h, w = rgba.shape[:2]
    progress = _progress_field((h, w), rng)
    alpha = rgba[:, :, 3].astype(np.float32)
    for i in range(count):
        t = i / max(1, count - 1)
        a = np.clip((t * 1.15 - progress) / 0.15, 0, 1)
        frame = rgba.copy()
        frame[:, :, 3] = np.round(alpha * _smoothstep(a)).astype(np.uint8)
        yield frame


def _kill(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _run_ffmpeg_stdin(
    cmd: list[str], frames: Iterator[np.ndarray], is_cancelled: Callable[[], bool] | None
) -> None:
    # stdout/stderr go to temp files (not pipes) so writing frames to stdin can never block on a full pipe.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr)
        try:
            for frame in frames:
                if is_cancelled and is_cancelled():
                    _kill(proc)
                    raise RuntimeError("Export cancelled.")
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
            while proc.poll() is None:
                if is_cancelled and is_cancelled():
                    _kill(proc)
                    raise RuntimeError("Export cancelled.")
                time.sleep(0.05)
        finally:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        if proc.returncode != 0:
            stderr.seek(0)
            raise RuntimeError(f"ffmpeg failed: {stderr.read().decode('utf-8', 'replace')[-2000:]}")


def render_reveal(
    asset: Path,
    dest: Path,
    *,
    duration: float,
    seed: int,
    fps: int = 30,
    opacity: float = 1.0,
    fingerprint: str | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> Path:
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg executable not found")
    with Image.open(asset) as image:
        rgba_image = image.convert("RGBA")
        long_side = max(rgba_image.width, rgba_image.height)
        if long_side > MAX_LONG_SIDE:
            # Keynote scales the movie to the item frame anyway.
            scale = MAX_LONG_SIDE / long_side
            rgba_image = rgba_image.resize(
                (max(1, round(rgba_image.width * scale)), max(1, round(rgba_image.height * scale))), Image.LANCZOS
            )
        rgba = np.array(rgba_image)
    if opacity < 1:
        rgba = rgba.copy()
        rgba[:, :, 3] = np.round(rgba[:, :, 3].astype(np.float32) * opacity).astype(np.uint8)
    h, w = rgba.shape[:2]
    count = max(2, round(duration * fps))
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = dest.with_name(f".{dest.stem}.tmp{dest.suffix}")
    cmd = [
        exe,
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgba",
        "-s",
        f"{w}x{h}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-c:v",
        "prores_ks",
        "-profile:v",
        "4444",
        "-pix_fmt",
        "yuva444p10le",
        "-vendor",
        "apl0",
        "-movflags",
        "+faststart",
        "-an",
        str(tmp_dest),
    ]
    frames = reveal_frames(rgba, count=count, seed=seed)
    try:
        _run_ffmpeg_stdin(cmd, frames, is_cancelled)
    except Exception:
        tmp_dest.unlink(missing_ok=True)
        raise
    tmp_dest.rename(dest)
    if fingerprint is not None:
        _fingerprint_path(dest).write_text(fingerprint)
    return dest
