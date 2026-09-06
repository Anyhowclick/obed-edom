"""P2 fly movies: browser-captured frames -> HEVC `Map BG_<slide>.mov` via bundled ffmpeg (JobRunner only)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

MOVIE_DIR = "movies"
FRAMES_DIR = "frames"
_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_ENCODERS: list[list[str]] = [
    ["hevc_videotoolbox", "-tag:v", "hvc1", "-b:v", "40M", "-allow_sw", "1"],
    ["libx265", "-tag:v", "hvc1", "-crf", "18", "-preset", "fast"],
    ["libx264", "-crf", "18", "-preset", "fast"],
]


def safe_slide_id(slide_id: str) -> str:
    return _SAFE_RE.sub("_", str(slide_id)).strip("_") or "slide"


def movie_filename(slide_id: str) -> str:
    return f"Map BG_{safe_slide_id(slide_id)}.mov"


def movie_path(output_dir: Path, slide_id: str) -> Path:
    return Path(output_dir) / MOVIE_DIR / movie_filename(slide_id)


def frames_dir(output_dir: Path, slide_id: str) -> Path:
    return Path(output_dir) / FRAMES_DIR / safe_slide_id(slide_id)


def ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def write_frame(output_dir: Path, slide_id: str, index: int, body: bytes, content_type: str) -> Path:
    folder = frames_dir(output_dir, slide_id)
    if index == 0 and folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)
    ext = ".png" if content_type.startswith("image/png") else ".jpg"
    path = folder / f"{index:05d}{ext}"
    path.write_bytes(body)
    return path


def write_frames_meta(output_dir: Path, slide_id: str, *, fps: int, count: int) -> Path:
    folder = frames_dir(output_dir, slide_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "meta.json"
    path.write_text(json.dumps({"fps": fps, "count": count, "duration": count / fps}))
    return path


_FRAME_EXTS = {".jpg", ".jpeg", ".png"}


def frame_indices(frames: Path) -> list[int]:
    found: dict[int, Path] = {}
    for path in Path(frames).iterdir():
        if path.suffix.lower() not in _FRAME_EXTS or not path.stem.isdigit():
            continue
        found[int(path.stem)] = path
    return sorted(found)


def require_contiguous_frames(frames: Path, expected: int | None = None) -> list[int]:
    """Raise if the sequence does not start at 00000 or has a gap."""
    indices = frame_indices(frames)
    if len(indices) < 2:
        raise ValueError(f"Need at least 2 frames in {frames}, found {len(indices)}")
    if indices[0] != 0:
        raise ValueError(f"Frames must start at 00000, got {indices[0]:05d}")
    for want, got in enumerate(indices):
        if got != want:
            raise ValueError(f"Frame gap in {frames}: expected {want:05d}, got {got:05d}")
    if expected is not None and len(indices) != expected:
        raise ValueError(f"Frame count {len(indices)} does not match meta count {expected}")
    return indices


def _frame_pattern(frames: Path) -> str:
    indices = frame_indices(frames)
    first = next(Path(frames).glob(f"{indices[0]:05d}.*"), None) if indices else None
    if first is not None and first.suffix.lower() == ".png":
        return "%05d.png"
    if any(frames.glob("*.png")):
        return "%05d.png"
    return "%05d.jpg"


def encode_fly_movie(frames: Path, dest: Path, *, fps: int, log=None) -> Path:
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg executable not found")
    require_contiguous_frames(frames)
    pattern = str(frames / _frame_pattern(frames))
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dest = dest.with_name(f".{dest.stem}.tmp{dest.suffix}")
    errors: list[str] = []
    for codec_args in _ENCODERS:
        codec, extra_args = codec_args[0], codec_args[1:]
        cmd = [
            exe,
            "-y",
            "-framerate",
            str(fps),
            "-i",
            pattern,
            "-c:v",
            codec,
            *extra_args,
            "-pix_fmt",
            "yuv420p",
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-movflags",
            "+faststart",
            "-an",
            str(tmp_dest),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=600)
        except Exception as exc:
            errors.append(f"{codec_args[0]}: {exc}")
            if log:
                log(f"encode failed with {codec_args[0]}: {exc}")
            continue
        if proc.returncode == 0 and tmp_dest.exists():
            tmp_dest.rename(dest)
            return dest
        stderr_tail = proc.stderr.decode("utf-8", "replace")[-2000:]
        errors.append(f"{codec_args[0]}: {stderr_tail}")
        if log:
            log(f"encode failed with {codec_args[0]}: {stderr_tail}")
        tmp_dest.unlink(missing_ok=True)
    raise RuntimeError("All encoders failed:\n" + "\n".join(errors))


def encode_pending(output_dir: Path, slides: list[dict], log=None) -> list[dict]:
    output_dir = Path(output_dir)
    next_slides: list[dict] = []
    for slide in slides:
        slide = dict(slide)
        sid = str(slide.get("id"))
        frames = frames_dir(output_dir, sid)
        meta_path = frames / "meta.json"
        movie = movie_path(output_dir, sid)
        if not meta_path.exists():
            if not movie.exists():
                slide.pop("movieMov", None)
                slide.pop("movieDuration", None)
            next_slides.append(slide)
            continue
        meta = json.loads(meta_path.read_text())
        fps = int(meta.get("fps") or 0)
        if fps < 1:
            raise ValueError(f"Invalid fps in {meta_path}")
        expected = meta.get("count")
        expected_n = int(expected) if expected is not None else None
        # meta.json means this was a movie hop — do not soft-skip a short/gapped sequence.
        indices = require_contiguous_frames(frames, expected_n)
        needs_encode = not movie.exists() or movie.stat().st_mtime < meta_path.stat().st_mtime
        if needs_encode:
            encode_fly_movie(frames, movie, fps=fps, log=log)
        slide["movieMov"] = movie_filename(sid)
        slide["movieDuration"] = len(indices) / fps
        next_slides.append(slide)
    return next_slides
