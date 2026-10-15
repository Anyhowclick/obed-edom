"""Convert preview movies to opaque H.264 or VP9 WebM with alpha in place.

File names, slide JSON and `main.js` are untouched.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
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
    webm_info,
)
from obed_edom.live_continuity import _referenced_movies, canonical_asset_name
from obed_edom.maps_movie import ffmpeg_exe

ENCODER = "libx264 crf14 fast yuv420p; aac 192k"
ALPHA_ENCODER = "libvpx-vp9 crf20 yuva420p; silent WebM"
MOVIE_SUFFIXES = frozenset({".mov", ".mp4", ".m4v"})
PROGRESS_INTERVAL_S = 5.0
OPAQUE_FIX = "replace it with an opaque movie"

_CODEC_LABELS = {"hevc": "HEVC", "prores": "ProRes", "av1": "AV1", "vp9": "VP9"}
_ALPHA_PIX_FMT_RE = re.compile(r"^(?:yuva|gbrap|ya\d|rgba|bgra|argb|abgr|pal8)")
_VIDEO_STREAM_RE = re.compile(r"Stream #0:\d+.*?: Video: [^,(]+(?:\([^)]*\)\s*)*, ([a-z0-9_]+)")
_AUDIO_STREAM_RE = re.compile(r"Stream #0:\d+.*?: Audio:")
_YMIN_RE = re.compile(r"lavfi\.signalstats\.YMIN=(\d+(?:\.\d+)?)")
_OUT_TIME_RE = re.compile(r"^out_time_us=(\d+)$")
_FRAME_RE = re.compile(r"^frame=(\d+)$", re.MULTILINE)
_PSNR_RE = re.compile(r"average:(inf|\d+(?:\.\d+)?)")
_WEB_URL_RE = re.compile(r"^[a-z]+://", re.IGNORECASE)

_H264_TARGET = "H.264"
_ALPHA_TARGET = "VP9 alpha"
_IDENTITY_MATRIX = (65536, 0, 0, 0, 65536, 0, 0, 0, 1073741824)


@dataclass(frozen=True)
class _Movie:
    asset: str
    path: Path
    codec: str | None
    timing: MovieTiming | None
    geometry: MovieGeometry | None


def _referenced(export_root: Path, slides: list[dict[str, Any]]) -> tuple[list[tuple[str, Path]], list[str]]:
    """Referenced local movie files, plus the export-relative paths of local movies that do not
    resolve to a file (web movies are not files and are left out of both)."""
    missing: list[str] = []

    def resolver(root: Path, relative: str) -> Path:
        try:
            return safe_export_file(root, relative)
        except PreviewError:
            url = relative.split("/", 2)[-1]
            if Path(relative).suffix.lower() in MOVIE_SUFFIXES and not _WEB_URL_RE.match(url):
                missing.append(relative)
            raise

    found = _referenced_movies(export_root, slides, resolver=resolver)
    files = [
        (asset, path)
        for asset, paths in sorted(found.items())
        for path in paths
        if path is not None and path.suffix.lower() in MOVIE_SUFFIXES
    ]
    return files, sorted(set(missing))


def unconverted(export_root: Path, slides: list[dict[str, Any]]) -> list[str]:
    """Referenced movie paths that are missing or not an accepted playback target."""
    root = export_root.resolve()
    files, missing = _referenced(export_root, slides)
    return sorted(
        [
            path.relative_to(root).as_posix()
            for _asset, path in files
            if not _accepted(path)
        ]
        + missing
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


def _accepted(path: Path) -> bool:
    info = webm_info(path)
    return info.alpha if info is not None else codec_family(movie_codec(path)) == "h264"


def _decoded_pix_fmt(exe: str, path: Path) -> tuple[str | None, bool]:
    proc = subprocess.run(
        [exe, "-nostdin", "-hide_banner", "-i", str(path)], capture_output=True, text=True
    )
    match = _VIDEO_STREAM_RE.search(proc.stderr)
    return (match.group(1) if match else None, _AUDIO_STREAM_RE.search(proc.stderr) is not None)


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


def _conversion_target(exe: str, movie: _Movie) -> tuple[str | None, str | None]:
    if movie.timing is None or movie.geometry is None:
        return None, "its timing or size cannot be read"
    if movie.geometry.width % 2 or movie.geometry.height % 2:
        return None, f"its size {movie.geometry.width}×{movie.geometry.height} is odd; conversion needs even sizes"
    if codec_family(movie.codec) == "hevc" and movie.geometry.depth == 32:
        return None, f"its transparency cannot be checked; {OPAQUE_FIX}"
    pix_fmt, has_audio = _decoded_pix_fmt(exe, movie.path)
    if pix_fmt is None:
        return None, "ffmpeg cannot read its video"
    if _ALPHA_PIX_FMT_RE.match(pix_fmt):
        alpha = _min_alpha(exe, movie.path)
        if alpha is None:
            return None, f"its transparency cannot be checked; {OPAQUE_FIX}"
        if alpha < 255:
            if codec_family(movie.codec) != "prores":
                return None, "it has transparency; alpha conversion currently supports ProRes movies"
            if movie.geometry.matrix != _IDENTITY_MATRIX or not movie.timing.identity_edits:
                return None, "its rotation or edits are not supported for alpha conversion"
            if has_audio:
                return None, "it has audio; alpha conversion currently supports silent movies"
            return _ALPHA_TARGET, None
    return _H264_TARGET, None


def _encode_argv(exe: str, src: Path, dest: Path, timescale: int) -> list[str]:
    return [
        exe, "-nostdin", "-y", "-v", "error", "-noautorotate", "-i", str(src),
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", *_crop_encoder_args("h264"),
        "-fps_mode", "passthrough", "-video_track_timescale", str(timescale),
        "-c:a", "aac", "-b:a", "192k",
        "-progress", "pipe:1", "-nostats", str(dest),
    ]


def _alpha_encode_argv(exe: str, src: Path, dest: Path) -> list[str]:
    return [
        exe, "-nostdin", "-y", "-v", "error", "-noautorotate", "-i", str(src),
        "-map", "0:v:0", "-an", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
        "-crf", "20", "-b:v", "0", "-row-mt", "1", "-fps_mode", "passthrough",
        "-progress", "pipe:1", "-nostats", "-f", "webm", str(dest),
    ]


def _temp_sibling(path: Path, tag: str) -> Path:
    return path.with_name(f".{path.stem}.{tag}{path.suffix}")


def _encode(exe: str, movie: _Movie, tmp: Path, target: str, log: Callable[[str], None]) -> None:
    assert movie.timing is not None
    total = round(movie.timing.presented_s)
    label = f"Converting {movie.asset} to {target}"
    log(f"{label} · 0 / {total} s")
    last = time.monotonic()
    argv = (
        _alpha_encode_argv(exe, movie.path, tmp)
        if target == _ALPHA_TARGET
        else _encode_argv(exe, movie.path, tmp, movie.timing.timescale)
    )
    with tempfile.TemporaryFile(mode="w+") as errors:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            match = _OUT_TIME_RE.match(line.strip())
            if match and time.monotonic() - last >= PROGRESS_INTERVAL_S:
                last = time.monotonic()
                log(f"{label} · {int(match.group(1)) // 1_000_000} / {total} s")
        if proc.wait() != 0:
            errors.seek(0)
            raise PreviewError(f"{movie.asset}: {target} conversion failed: {errors.read().strip()[-500:]}")


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


def _decoded_frames(exe: str, path: Path) -> int | None:
    proc = subprocess.run(
        [
            exe, "-nostdin", "-v", "error", "-c:v", "libvpx-vp9", "-i", str(path), "-map", "0:v:0",
            "-progress", "pipe:1", "-nostats", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    frames = [int(value) for value in _FRAME_RE.findall(proc.stdout)]
    return frames[-1] if proc.returncode == 0 and frames else None


def _alpha_psnr(exe: str, source: Path, result: Path) -> float | None:
    proc = subprocess.run(
        [
            exe, "-nostdin", "-hide_banner", "-v", "info", "-i", str(source),
            "-c:v", "libvpx-vp9", "-i", str(result),
            "-filter_complex",
            "[0:v:0]alphaextract,format=gray[a];[1:v:0]alphaextract,format=gray[b];[a][b]psnr[out]",
            "-map", "[out]", "-an", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    matches = _PSNR_RE.findall(proc.stderr)
    if proc.returncode != 0 or not matches:
        return None
    return float("inf") if matches[-1] == "inf" else float(matches[-1])


def _verify_alpha(exe: str, movie: _Movie, tmp: Path) -> str | None:
    source, geometry = movie.timing, movie.geometry
    assert source is not None and geometry is not None
    info = webm_info(tmp)
    if info is None:
        return "the converted file is not VP9 WebM"
    if not info.alpha:
        return "lost transparency during conversion"
    if (info.width, info.height) != (geometry.width, geometry.height):
        return "the converted file's size differs"
    half_frame = source.stts_duration / source.samples / source.timescale / 2
    if abs(info.duration_s - source.presented_s) > half_frame:
        return f"the converted file plays {info.duration_s:.3f} s, not {source.presented_s:.3f} s"
    frames = _decoded_frames(exe, tmp)
    if frames != source.samples:
        count = frames if frames is not None else "an unreadable number of"
        return f"the converted file has {count} frames, not {source.samples}"
    psnr = _alpha_psnr(exe, movie.path, tmp)
    if psnr is None:
        return "its converted transparency cannot be compared"
    if psnr < 48:
        return f"its converted transparency is only {psnr:.1f} dB PSNR"
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
    """Convert referenced movies to an accepted playback target under their own names, one
    encode per group of copies sharing media data, timing and geometry. Refusals are collected
    and raised together before anything is written; an encode or verify failure leaves the
    original untouched. Returns the manifest's `movieConversion` record."""
    root = export_root.resolve()
    files, missing = _referenced(export_root, slides)
    movies = []
    for asset, path in files:
        if not _accepted(path):
            movies.append(_Movie(asset, path, movie_codec(path), movie_timing(path), movie_geometry(path)))
    record: dict[str, Any] = {"encoder": ENCODER, "alphaEncoder": ALPHA_ENCODER, "converted": []}
    refused = {canonical_asset_name(relative): "its file is missing from the export" for relative in missing}
    if not movies and not refused:
        return record
    exe = ffmpeg_exe()
    if movies and not exe:
        raise PreviewError("ffmpeg is needed to convert movies and was not found")
    groups: dict[tuple[Any, ...], list[_Movie]] = {}
    for movie in movies:
        groups.setdefault((_media_data_sha256(movie.path), movie.timing, movie.geometry), []).append(movie)
    group_targets: dict[tuple[Any, ...], str] = {}
    for key, members in groups.items():
        if key[0] is None:
            for movie in members:
                refused.setdefault(movie.asset, "its media data cannot be read")
            continue
        target, reason = _conversion_target(exe, members[0])
        if reason:
            for movie in members:
                refused.setdefault(movie.asset, reason)
        elif target is not None:
            group_targets[key] = target
    if refused:
        raise PreviewError(
            "Cannot convert movies for playback: "
            + "; ".join(f"{asset}: {reason}" for asset, reason in sorted(refused.items()))
        )
    for key, members in groups.items():
        first = members[0]
        target = group_targets[key]
        tmp = _temp_sibling(first.path, "vp9" if target == _ALPHA_TARGET else "h264")
        try:
            source_shas = {movie.path: file_sha256(movie.path) for movie in members}
            _encode(exe, first, tmp, target, log)
            problem = _verify_alpha(exe, first, tmp) if target == _ALPHA_TARGET else _verify(first, tmp)
            if problem:
                raise PreviewError(f"{first.asset}: {problem}")
            os.replace(tmp, first.path)
            sha, size = file_sha256(first.path), first.path.stat().st_size
        except OSError as exc:
            raise PreviewError(f"{first.asset}: {target} conversion failed: {exc}") from exc
        finally:
            tmp.unlink(missing_ok=True)
        for movie in members[1:]:
            try:
                _swap_copy(first.path, movie.path)
            except OSError as exc:
                raise PreviewError(f"{movie.asset}: {target} conversion failed: {exc}") from exc
        record["converted"].extend(
            {
                "path": movie.path.relative_to(root).as_posix(),
                "asset": movie.asset,
                "sourceCodec": _codec_label(movie.codec),
                "targetCodec": target,
                "sourceSha256": source_shas[movie.path],
                "sha256": sha,
                "bytes": size,
            }
            for movie in members
        )
    record["converted"].sort(key=lambda entry: entry["path"])
    return record
