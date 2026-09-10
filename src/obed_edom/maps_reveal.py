"""Brush-on reveal movies for landmark objects: numpy/PIL frames piped to the bundled ffmpeg as ProRes 4444 (alpha)."""

from __future__ import annotations

import hashlib
import math
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterator

import cv2
import numpy as np
from PIL import Image

from obed_edom.maps_movie import MOVIE_DIR, encode_fly_movie, ffmpeg_exe, frames_dir, safe_slide_id
from obed_edom.watercolour import _blur, _noise

MAX_LONG_SIDE = 1600
REVEAL_DIR = "reveal"
REVEAL_ALGO_VERSION = 3
REVEAL_FPS = 30
DEFAULT_STROKES = 4
STROKE_SPAN = 0.18
STROKE_EDGE = 0.06
STROKE_SAMPLES = 96
FIELD_SCALE_LONG = 0.25
FIELD_SCALE_SHORT = 0.5
FIELD_SCALE_CUTOFF = 1200


def reveal_path(output_dir: Path, slide_id: str, church_id: str, audience: str = "lw") -> Path:
    suffix = "-cg" if audience == "cg" else ""
    return Path(output_dir) / REVEAL_DIR / f"{safe_slide_id(slide_id)}-{safe_slide_id(church_id)}{suffix}.mov"


def reveal_seed(church_id: str) -> int:
    return int.from_bytes(hashlib.sha256(church_id.encode()).digest()[:8], "big")


def _fingerprint_path(dest: Path) -> Path:
    return dest.with_suffix(dest.suffix + ".fp")


def reveal_fingerprint(
    asset: Path,
    *,
    duration: float,
    opacity: float,
    seed: int,
    width: int,
    height: int,
    strokes: int = DEFAULT_STROKES,
) -> str:
    stat = asset.stat()
    payload = "|".join(
        str(part)
        for part in (
            stat.st_mtime_ns,
            stat.st_size,
            duration,
            opacity,
            seed,
            width,
            height,
            strokes,
            REVEAL_ALGO_VERSION,
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def reveal_stale(dest: Path, fingerprint: str) -> bool:
    fp_path = _fingerprint_path(dest)
    if not dest.is_file() or not fp_path.is_file():
        return True
    return fp_path.read_text().strip() != fingerprint


def _smoothstep(a: np.ndarray) -> np.ndarray:
    return a * a * (3 - 2 * a)


def _blur_coarse(a: np.ndarray, sigma: float, scale: float = 0.25) -> np.ndarray:
    """Blur at a fraction of resolution then resize back up — a per-frame blur is too costly at full res."""
    if sigma <= 0:
        return a
    h, w = a.shape
    sh, sw = max(2, round(h * scale)), max(2, round(w * scale))
    small = cv2.resize(a, (sw, sh), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), max(sigma * scale, 0.6))
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def _bezier_polyline(
    p0: np.ndarray, p1: np.ndarray, p2: np.ndarray, n: int, wobble: float = 0.0
) -> tuple[np.ndarray, np.ndarray]:
    u = np.linspace(0.0, 1.0, n)
    pts = (1 - u)[:, None] ** 2 * p0 + 2 * (1 - u)[:, None] * u[:, None] * p1 + u[:, None] ** 2 * p2
    if wobble:
        pts = pts.copy()
        pts[:, 1] += wobble * np.sin(4 * np.pi * u)
    seg_len = np.hypot(*np.diff(pts, axis=0).T)
    arc = np.concatenate([[0.0], np.cumsum(seg_len)])
    total = arc[-1] if arc[-1] > 0 else 1.0
    return pts, (arc / total).astype(np.float32)


def _stroke_dist_arc(
    row_lo: int, row_hi: int, w: int, pts: np.ndarray, arc_norm: np.ndarray, scale: float
) -> tuple[np.ndarray, np.ndarray]:
    """Nearest-segment distance and arc-position fields, computed on a coarse grid then resized up."""
    rows = row_hi - row_lo
    coarse_h = max(2, round(rows * scale))
    coarse_w = max(2, round(w * scale))
    cy = np.linspace(row_lo, row_hi - 1, coarse_h, dtype=np.float32)
    cx = np.linspace(0, w - 1, coarse_w, dtype=np.float32)
    gyy, gxx = np.meshgrid(cy, cx, indexing="ij")
    a, b = pts[:-1], pts[1:]
    ab = b - a
    denom = np.where(ab[:, 0] ** 2 + ab[:, 1] ** 2 == 0, 1e-6, ab[:, 0] ** 2 + ab[:, 1] ** 2).reshape(-1, 1, 1)
    ax, ay = a[:, 0].reshape(-1, 1, 1), a[:, 1].reshape(-1, 1, 1)
    abx, aby = ab[:, 0].reshape(-1, 1, 1), ab[:, 1].reshape(-1, 1, 1)
    t = np.clip(((gxx[None] - ax) * abx + (gyy[None] - ay) * aby) / denom, 0, 1)
    d = np.hypot(gxx[None] - (ax + t * abx), gyy[None] - (ay + t * aby))
    idx = np.argmin(d, axis=0, keepdims=True)
    dist_c = np.take_along_axis(d, idx, axis=0)[0]
    arc0, arc1 = arc_norm[:-1].reshape(-1, 1, 1), arc_norm[1:].reshape(-1, 1, 1)
    arc_seg = arc0 + t * (arc1 - arc0)
    arc_c = np.take_along_axis(arc_seg, idx, axis=0)[0]
    dist = cv2.resize(dist_c.astype(np.float32), (w, rows), interpolation=cv2.INTER_LINEAR)
    arc = cv2.resize(arc_c.astype(np.float32), (w, rows), interpolation=cv2.INTER_LINEAR)
    return dist, arc


def _plan_strokes(
    shape: tuple[int, int], alpha: np.ndarray, rng: np.random.Generator, strokes_count: int
) -> list[dict]:
    """Ground-up bezier brush strokes: each stroke's slab carries distance-to-curve and arc-position fields."""
    h, w = shape
    ys, xs = np.nonzero(alpha > 8)
    if ys.size == 0:
        x0, y0, x1, y1 = 0, 0, w - 1, h - 1
    else:
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
    bw = max(1, x1 - x0)
    bh = max(1, y1 - y0)
    short = min(bw, bh)
    k = max(2, int(strokes_count))
    band_h = bh / k
    wid = band_h * 1.35
    feather = max(1.0, 0.10 * wid)
    cov_feather = 0.015 * short
    field_scale = FIELD_SCALE_LONG if max(h, w) > FIELD_SCALE_CUTOFF else FIELD_SCALE_SHORT

    raw = []
    for i in range(k):
        cy = y1 - (i + 0.5) * band_h + rng.uniform(-0.15, 0.15) * band_h
        p0 = np.array([x0 - 0.15 * bw, cy + rng.uniform(-0.06, 0.06) * bh], np.float32)
        p2 = np.array([x1 + 0.15 * bw, cy + rng.uniform(-0.06, 0.06) * bh], np.float32)
        if i % 2:
            p0, p2 = p2, p0
        p1 = (p0 + p2) / 2 + np.array([0.0, rng.uniform(-0.12, 0.12) * bh], np.float32)
        wobble = rng.uniform(0.015, 0.035) * bh
        raw.append((cy, p0, p1, p2, wobble))
    raw.sort(key=lambda r: -r[0])

    strokes = []
    for idx, (cy, p0, p1, p2, wobble) in enumerate(raw):
        row_lo = max(0, int(math.floor(cy - 1.2 * wid)))
        row_hi = min(h, int(math.ceil(cy + 1.2 * wid)) + 1)
        if row_hi <= row_lo:
            continue
        pts, arc_norm = _bezier_polyline(p0, p1, p2, STROKE_SAMPLES, wobble)
        dist, arc = _stroke_dist_arc(row_lo, row_hi, w, pts, arc_norm, field_scale)

        taper = 0.55 + 0.45 * np.power(np.clip(np.sin(np.pi * arc), 0, None), 0.6)
        noise_pts = _blur(rng.normal(0, 1, (1, 16)).astype(np.float32), 1.5).ravel()
        noise_pts = noise_pts / (np.abs(noise_pts).max() + 1e-6)
        lowfreq = np.interp(arc.ravel(), np.linspace(0, 1, noise_pts.size, dtype=np.float32), noise_pts)
        lowfreq = lowfreq.reshape(arc.shape).astype(np.float32)
        w_s = wid * taper * (1 + 0.18 * lowfreq)

        edge_noise = _noise(rng, dist.shape, 0.01 * short)
        edge_noise = np.clip(edge_noise / (edge_noise.std() * 3 + 1e-6), -1, 1)
        profile = np.clip((w_s / 2 + edge_noise * 0.12 * wid - dist) / feather, 0, 1)

        bristle_col = _blur(rng.random((row_hi - row_lo, 1)).astype(np.float32), 1.2)
        lo, hi = float(bristle_col.min()), float(bristle_col.max())
        bristle_col = (bristle_col - lo) / (hi - lo) if hi > lo else bristle_col
        edge_prox = np.clip(dist / (w_s / 2 + 1e-6), 0, 1)
        bristle = (0.82 + 0.18 * bristle_col) * (0.85 + 0.30 * edge_prox)

        cap_edge = STROKE_EDGE * (1 + 0.6 * np.clip(dist / (w_s / 2 + 1e-6), 0, 2))

        strokes.append(
            dict(
                row_slice=slice(row_lo, row_hi),
                dist=dist,
                arc=arc,
                profile=profile,
                bristle=bristle,
                cap_edge=cap_edge,
                cov_feather=cov_feather,
                t_start=idx * (1 - STROKE_SPAN) / max(1, k - 1),
            )
        )
    return strokes


def reveal_frames(rgba: np.ndarray, *, count: int, seed: int, strokes: int = DEFAULT_STROKES) -> Iterator[np.ndarray]:
    rng = np.random.default_rng(seed)
    h, w = rgba.shape[:2]
    alpha = rgba[:, :, 3].astype(np.float32)
    planned = _plan_strokes((h, w), alpha, rng, strokes)
    prev_total = np.zeros((h, w), np.float32)
    for i in range(count):
        t = i / max(1, count - 1)
        total = np.zeros((h, w), np.float32)
        for st in planned:
            rs = st["row_slice"]
            p = np.clip((t - st["t_start"]) / STROKE_SPAN, 0, 1)
            cov = _smoothstep(np.clip((p - st["arc"]) / st["cap_edge"], 0, 1))
            cov = _blur_coarse(cov, st["cov_feather"])
            total[rs] += cov * st["profile"] * st["bristle"]
        total = np.clip(total, 0, 1)
        total = np.maximum(prev_total, total)
        if i == count - 1:
            total[:] = 1.0
        prev_total = total
        frame = rgba.copy()
        frame[:, :, 3] = np.round(alpha * total).astype(np.uint8)
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
    fps: int = REVEAL_FPS,
    opacity: float = 1.0,
    strokes: int = DEFAULT_STROKES,
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
    frames = reveal_frames(rgba, count=count, seed=seed, strokes=strokes)
    try:
        _run_ffmpeg_stdin(cmd, frames, is_cancelled)
    except Exception:
        tmp_dest.unlink(missing_ok=True)
        raise
    tmp_dest.rename(dest)
    if fingerprint is not None:
        _fingerprint_path(dest).write_text(fingerprint)
    return dest


def reveal_movie_fingerprint(base_png: Path, landmarks: list[dict]) -> str:
    stat = Path(base_png).stat()
    geometry = tuple(
        (
            str(landmark["asset"]),
            landmark["x"],
            landmark["y"],
            landmark["w"],
            landmark["h"],
            landmark["duration"],
            landmark["seed"],
            landmark.get("opacity", 1.0),
            landmark.get("strokes", DEFAULT_STROKES),
        )
        for landmark in landmarks
    )
    payload = "|".join(str(part) for part in (stat.st_mtime_ns, stat.st_size, geometry, REVEAL_ALGO_VERSION))
    return hashlib.sha256(payload.encode()).hexdigest()


def reveal_movie_path(output_dir: Path, slide_id: str, audience: str = "lw") -> Path:
    suffix = "_CG" if audience == "cg" else ""
    return Path(output_dir) / MOVIE_DIR / f"Map BG_{safe_slide_id(slide_id)}-reveal{suffix}.mov"


def render_slide_reveal_movie(
    base_png: Path,
    country_png: Path | None,
    landmarks: list[dict],
    dest: Path,
    *,
    output_dir: Path,
    slide_id: str,
    audience: str = "lw",
    size: tuple[int, int],
    fps: int = 30,
    fingerprint: str | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> Path:
    """Composite paint-on reveals for one or more landmarks onto the slide's base map, as an opaque bg movie."""
    w, h = size
    with Image.open(base_png) as image:
        base = image.convert("RGBA")
        if base.size != (w, h):
            base = base.resize((w, h), Image.LANCZOS)
    if country_png is not None and Path(country_png).is_file():
        with Image.open(country_png) as image:
            country = image.convert("RGBA")
            if country.size != (w, h):
                country = country.resize((w, h), Image.LANCZOS)
            base = Image.alpha_composite(base, country)
    base_rgb = np.array(base.convert("RGB"), np.uint8)

    prepared = []
    for landmark in landmarks:
        with Image.open(landmark["asset"]) as image:
            asset = image.convert("RGBA").resize((max(1, int(landmark["w"])), max(1, int(landmark["h"]))), Image.LANCZOS)
        rgba = np.array(asset)
        opacity = float(landmark.get("opacity", 1.0))
        if opacity < 1:
            rgba = rgba.copy()
            rgba[:, :, 3] = np.round(rgba[:, :, 3].astype(np.float32) * opacity).astype(np.uint8)
        count = max(2, round(float(landmark["duration"]) * fps))
        frames = list(
            reveal_frames(
                rgba, count=count, seed=int(landmark["seed"]), strokes=int(landmark.get("strokes", DEFAULT_STROKES))
            )
        )
        prepared.append(dict(x=int(landmark["x"]), y=int(landmark["y"]), frames=frames))

    tail = round(0.3 * fps)
    total = tail + (max((len(item["frames"]) for item in prepared)) if prepared else 2)
    folder = frames_dir(output_dir, f"{slide_id}__reveal", audience)
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(total):
        canvas = base_rgb.copy()
        for item in prepared:
            _raise_frame_cancelled(is_cancelled)
            frame = item["frames"][min(i, len(item["frames"]) - 1)]
            x, y = item["x"], item["y"]
            fh, fw = frame.shape[:2]
            slab = canvas[y : y + fh, x : x + fw]
            if slab.shape[:2] != (fh, fw):
                continue
            alpha = frame[:, :, 3:4].astype(np.float32) / 255.0
            canvas[y : y + fh, x : x + fw] = np.round(
                frame[:, :, :3].astype(np.float32) * alpha + slab.astype(np.float32) * (1 - alpha)
            ).astype(np.uint8)
        Image.fromarray(canvas, "RGB").save(folder / f"{i:05d}.png")
    result = encode_fly_movie(folder, dest, fps=fps, is_cancelled=is_cancelled)
    if fingerprint is not None:
        _fingerprint_path(dest).write_text(fingerprint)
    return result


def _raise_frame_cancelled(is_cancelled: Callable[[], bool] | None) -> None:
    if is_cancelled and is_cancelled():
        raise RuntimeError("Export cancelled.")
