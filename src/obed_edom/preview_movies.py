"""Convert every non-H.264 movie an HTML preview export references to H.264 in place, so
the deck plays in every live output. File names, slide JSON and `main.js` are untouched."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from obed_edom.dsk_movie_export import _crop_encoder_args
from obed_edom.html_preview import PreviewError, file_sha256, safe_export_file
from obed_edom.live_codec import (
    MovieGeometry,
    MovieTiming,
    _read_box_header,
    codec_family,
    movie_codec,
    movie_geometry,
    movie_timing,
)
from obed_edom.live_continuity import _referenced_movies
from obed_edom.maps_movie import ffmpeg_exe

ENCODER = "libx264 crf14 fast yuv420p; aac 192k"
MOVIE_SUFFIXES = frozenset({".mov", ".mp4", ".m4v"})
PROGRESS_INTERVAL_S = 5.0
OPAQUE_FIX = "replace it with an opaque movie"

_CODEC_LABELS = {"hevc": "HEVC", "prores": "ProRes", "av1": "AV1", "vp9": "VP9"}
_ALPHA_PIX_FMT_RE = re.compile(r"^(?:yuva|gbrap|ya\d|rgba|bgra|argb|abgr|pal8)")
_VIDEO_STREAM_RE = re.compile(r"Stream #0:\d+.*?: Video: [^,(]+(?:\([^)]*\)\s*)*, ([a-z0-9_]+)")
_YMIN_RE = re.compile(r"lavfi\.signalstats\.YMIN=(\d+(?:\.\d+)?)")
_OUT_TIME_RE = re.compile(r"^out_time_us=(\d+)$")


@dataclass(frozen=True)
class _Movie:
    asset: str
    path: Path
    codec: str
    timing: MovieTiming | None
    geometry: MovieGeometry | None


def _referenced(export_root: Path, slides: list[dict[str, Any]]) -> list[tuple[str, Path]]:
    found = _referenced_movies(export_root, slides, resolver=safe_export_file)
    return [
        (asset, path)
        for asset, paths in sorted(found.items())
        for path in paths
        if path is not None and path.suffix.lower() in MOVIE_SUFFIXES
    ]


def unconverted(export_root: Path, slides: list[dict[str, Any]]) -> list[str]:
    """Export-relative paths of referenced movie files that are not H.264."""
    root = export_root.resolve()
    return sorted(
        path.relative_to(root).as_posix()
        for _asset, path in _referenced(export_root, slides)
        if codec_family(movie_codec(path)) != "h264"
    )


def _codec_label(fourcc: str | None) -> str:
    family = codec_family(fourcc)
    return _CODEC_LABELS.get(family) or fourcc or "unknown"


def _media_data_sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    found = False
    with open(path, "rb") as f:
        end = f.seek(0, 2)
        pos = 0
        while pos < end:
            header = _read_box_header(f, pos, end)
            if header is None:
                return None
            box_type, payload_start, box_end = header
            if box_type == b"mdat":
                found = True
                f.seek(payload_start)
                remaining = box_end - payload_start
                while remaining:
                    chunk = f.read(min(remaining, 1 << 20))
                    if not chunk:
                        return None
                    digest.update(chunk)
                    remaining -= len(chunk)
            pos = box_end
    return digest.hexdigest() if found else None


def _decoded_pix_fmt(exe: str, path: Path) -> str | None:
    proc = subprocess.run([exe, "-nostdin", "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    match = _VIDEO_STREAM_RE.search(proc.stderr)
    return match.group(1) if match else None


def _min_alpha(exe: str, path: Path) -> float | None:
    proc = subprocess.run(
        [
            exe, "-nostdin", "-v", "error", "-i", str(path), "-map", "0:v:0",
            "-vf", "alphaextract,format=gray,signalstats,metadata=print:key=lavfi.signalstats.YMIN:file=-",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    values = [float(v) for v in _YMIN_RE.findall(proc.stdout)]
    if proc.returncode != 0 or not values:
        return None
    return min(values)


def _refusal(exe: str, movie: _Movie) -> str | None:
    if movie.timing is None or movie.geometry is None:
        return "its timing or size cannot be read"
    if movie.geometry.width % 2 or movie.geometry.height % 2:
        return f"its size {movie.geometry.width}×{movie.geometry.height} is odd; H.264 needs even sizes"
    if codec_family(movie.codec) == "hevc" and movie.geometry.depth == 32:
        return f"its transparency cannot be checked; {OPAQUE_FIX}"
    pix_fmt = _decoded_pix_fmt(exe, movie.path)
    if pix_fmt is None:
        return "ffmpeg cannot read its video"
    if _ALPHA_PIX_FMT_RE.match(pix_fmt):
        alpha = _min_alpha(exe, movie.path)
        if alpha is None:
            return f"its transparency cannot be checked; {OPAQUE_FIX}"
        if alpha < 255:
            return f"it has transparency, and H.264 has none; {OPAQUE_FIX}"
    return None


def _encode_argv(exe: str, src: Path, dest: Path, timescale: int) -> list[str]:
    return [
        exe, "-nostdin", "-y", "-v", "error", "-noautorotate", "-i", str(src),
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", *_crop_encoder_args("h264"),
        "-fps_mode", "passthrough", "-video_track_timescale", str(timescale),
        "-c:a", "aac", "-b:a", "192k",
        "-progress", "pipe:1", "-nostats", str(dest),
    ]


def _temp_sibling(path: Path, tag: str) -> Path:
    return path.with_name(f".{path.stem}.{tag}{path.suffix}")


def _encode(exe: str, movie: _Movie, tmp: Path, log: Callable[[str], None]) -> None:
    assert movie.timing is not None
    total = round(movie.timing.presented_s)
    label = f"Converting {movie.asset} to H.264"
    log(f"{label} · 0 / {total} s")
    last = time.monotonic()
    proc = subprocess.Popen(
        _encode_argv(exe, movie.path, tmp, movie.timing.timescale),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None and proc.stderr is not None
    for line in proc.stdout:
        match = _OUT_TIME_RE.match(line.strip())
        if match and time.monotonic() - last >= PROGRESS_INTERVAL_S:
            last = time.monotonic()
            log(f"{label} · {int(match.group(1)) // 1_000_000} / {total} s")
    stderr = proc.stderr.read()
    if proc.wait() != 0:
        raise PreviewError(f"{movie.asset}: H.264 conversion failed: {stderr.strip()[-500:]}")


def _verify(movie: _Movie, tmp: Path) -> str | None:
    source, geometry = movie.timing, movie.geometry
    assert source is not None and geometry is not None
    if movie_codec(tmp) != "avc1":
        return "the converted file is not H.264"
    timing, out = movie_timing(tmp), movie_geometry(tmp)
    if timing is None or out is None:
        return "the converted file's timing or size cannot be read"
    if (out.width, out.height, out.matrix) != (geometry.width, geometry.height, geometry.matrix):
        return "the converted file's size or rotation differs"
    if timing.timescale != source.timescale:
        return "the converted file's timescale differs"
    half_frame = source.stts_duration / source.samples / source.timescale / 2
    if abs(timing.presented_s - source.presented_s) > half_frame:
        return f"the converted file plays {timing.presented_s:.3f} s, not {source.presented_s:.3f} s"
    if source.identity_edits and timing.samples != source.samples:
        return f"the converted file has {timing.samples} frames, not {source.samples}"
    return None


def _swap_copy(original: Path, copy: Path) -> None:
    tmp = _temp_sibling(copy, "link")
    try:
        try:
            os.link(original, tmp)
        except OSError:
            shutil.copy2(original, tmp)
        os.replace(tmp, copy)
    finally:
        tmp.unlink(missing_ok=True)


def convert_movies(
    export_root: Path, slides: list[dict[str, Any]], *, log: Callable[[str], None]
) -> dict[str, Any]:
    """Re-encode every referenced non-H.264 movie to H.264 under its own name, one encode per
    group of copies sharing media data, timing and geometry. Refusals are collected first and
    raised together before anything is written; an encode or verify failure leaves the
    original untouched. Returns the manifest's `movieConversion` record."""
    root = export_root.resolve()
    movies = [
        _Movie(asset, path, codec, movie_timing(path), movie_geometry(path))
        for asset, path in _referenced(export_root, slides)
        if codec_family(codec := movie_codec(path)) != "h264"
    ]
    record: dict[str, Any] = {"encoder": ENCODER, "converted": []}
    if not movies:
        return record
    exe = ffmpeg_exe()
    if not exe:
        raise PreviewError("ffmpeg is needed to convert movies to H.264 and was not found")
    groups: dict[tuple[Any, ...], list[_Movie]] = {}
    for movie in movies:
        groups.setdefault((_media_data_sha256(movie.path), movie.timing, movie.geometry), []).append(movie)
    refused: dict[str, str] = {}
    for key, members in groups.items():
        reason = "its media data cannot be read" if key[0] is None else _refusal(exe, members[0])
        if reason:
            for movie in members:
                refused.setdefault(movie.asset, reason)
    if refused:
        raise PreviewError(
            "Cannot convert movies to H.264: "
            + "; ".join(f"{asset}: {reason}" for asset, reason in sorted(refused.items()))
        )
    for members in groups.values():
        first = members[0]
        source_shas = {movie.path: file_sha256(movie.path) for movie in members}
        tmp = _temp_sibling(first.path, "h264")
        try:
            _encode(exe, first, tmp, log)
            problem = _verify(first, tmp)
            if problem:
                raise PreviewError(f"{first.asset}: {problem}")
            os.replace(tmp, first.path)
        finally:
            tmp.unlink(missing_ok=True)
        for movie in members[1:]:
            _swap_copy(first.path, movie.path)
        sha, size = file_sha256(first.path), first.path.stat().st_size
        record["converted"].extend(
            {
                "path": movie.path.relative_to(root).as_posix(),
                "asset": movie.asset,
                "sourceCodec": _codec_label(movie.codec),
                "sourceSha256": source_shas[movie.path],
                "sha256": sha,
                "bytes": size,
            }
            for movie in members
        )
    record["converted"].sort(key=lambda entry: entry["path"])
    return record
