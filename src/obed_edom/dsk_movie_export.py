"""Movie-crop pipeline for the DSK generator (d3): native-wall Keynote export ->
per-slide QuickTime `.m4v` export -> ffmpeg crop/remux, with the operator safety
rails the live probes required (process lock, display poke, RSS watchdog).

Shared by the DSK deck assembly (d4) and the standalone Exporter (d5b). Offline
helpers never touch Keynote; the live path is isolated behind `export_slide_clips`
and `_run_osascript`/`_ffprobe` so tests can fake it. Must not import `web.*`.
Audio is passed through unmodified (incl. volume) to follow the source slide's own behaviour.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from obed_edom import dsk_live, keynote_app
from obed_edom.dsk_live import (
    DEFAULT_BLACK_LAYOUT_NAMES,
    DEFAULT_LAYOUT_TEMPLATE,
    DEFAULT_RSS_LIMIT_BYTES,
    LOCK_PATH,
    LiveBatch,
    _KEYNOTE_QUIT_WAIT_S,
    _acquire_lock,
    _applescript_string_list,
    _as_escape,
    _DisplayPoke,
    _ERROR_RE,
    _fingerprint_source,
    _keynote_pid,
    _keynote_pids,
    _keynote_running,
    _keynote_tell,
    _keynote_terms,
    _osascript_path,
    _PROGRESS_RE,
    _quit_and_wait_for_exit,
    _quit_script,
    _release_lock,
    _run_osascript,
    _run_quit_script,
    _RssWatchdog,
    _sample_rss_bytes,
    acquire_lock,
    fingerprint_source,
    keynote_pid,
    keynote_running,
    ordinal_map,
    quit_and_wait_for_exit,
    release_lock,
    run_osascript,
)
from obed_edom.dsk_plan import ItemId, SlideClass, _delete_order, classify_deck, visible_union
from obed_edom.iwa_runs import attach_group_content_signature
from obed_edom.map_remap import CENTRE_PANEL_RECT, Rect, is_lw_wall
from obed_edom.maps_movie import ffmpeg_exe
from obed_edom.offline_inspect import offline_wall_payload
from obed_edom.remap_keynote import _AS_KIND_NAMES, copy_keynote

_DELETEFAIL_RE = re.compile(r"^DELETEFAIL\t(\d+)\t([^\t]*)\t(-?\d+)\t(.*)$")

_FPS_TOLERANCE = 0.01

CODECS = frozenset(
    {
        "h264",
        "AppleProRes422",
        "AppleProRes422LT",
        "AppleProRes422HQ",
        "AppleProRes422Proxy",
        "AppleProRes4444",
        "HEVC",
    }
)

_FPS_NAMES = {
    12: "FPS12",
    23.98: "FPS2398",
    24: "FPS24",
    25: "FPS25",
    29.97: "FPS2997",
    30: "FPS30",
    50: "FPS50",
    59.94: "FPS5994",
    60: "FPS60",
}

_FPS_RATIONALS = {
    12: 12.0,
    23.98: 24000 / 1001,
    24: 24.0,
    25: 25.0,
    29.97: 30000 / 1001,
    30: 30.0,
    50: 50.0,
    59.94: 60000 / 1001,
    60: 60.0,
}

_PRORES_PROFILES = {
    "AppleProRes422Proxy": "0",
    "AppleProRes422LT": "1",
    "AppleProRes422": "2",
    "AppleProRes422HQ": "3",
    "AppleProRes4444": "4",
}


def _matching_fps_candidate(fps: float) -> float:
    for candidate in _FPS_NAMES:
        if abs(candidate - fps) < 1e-6:
            return candidate
    raise ValueError(f"Unsupported fps for Keynote QuickTime export: {fps}")


def fps_enum_name(fps: float) -> str:
    """Keynote `export` sdef enumerator name for `fps`; raises on an unsupported rate."""
    return _FPS_NAMES[_matching_fps_candidate(fps)]


def fps_rational(fps: float) -> float:
    """True rational value (e.g. 23.98 -> 24000/1001) `fps` names, for tight validation."""
    return _FPS_RATIONALS[_matching_fps_candidate(fps)]


def _crop_encoder_args(codec: str) -> list[str]:
    """ffmpeg re-encode args for the crop path: prores_ks for ProRes codecs, libx264
    otherwise (h264/HEVC), matching the maps_movie ladder shape."""
    if codec in _PRORES_PROFILES:
        return ["prores_ks", "-profile:v", _PRORES_PROFILES[codec]]
    return ["libx264", "-crf", "18", "-preset", "fast"]


@dataclass(frozen=True)
class ClipResult:
    slide: int
    path: Path
    width: int
    height: int
    duration_s: float
    wall_s: float
    crop_width: int


@dataclass(frozen=True)
class _SlideJob:
    slide: int
    ordinal: int
    crop_rect: Rect
    dest: Path
    tmp: Path
    delete_ids: tuple[ItemId, ...] = ()


def clip_name(stem: str, slide: int) -> str:
    """`{stem}.{slide:03d}.mov`, keyed by Keynote slide number. The published clip is a
    QuickTime/.mov container (ProRes-compatible, importable by Keynote and PP7); this is
    distinct from `require_m4v`, which guards Keynote's own export destination."""
    return f"{stem}.{slide:03d}.mov"


def require_m4v(path: Path) -> Path:
    """Refuse anything but `.m4v`; Keynote's QuickTime exporter rejects `.mov` as an export
    destination. Guards only the Keynote-side scratch export path, not the published clip
    (which is `.mov`; see `clip_name`)."""
    path = Path(path)
    if path.suffix.lower() != ".m4v":
        raise ValueError(f"Keynote's QuickTime exporter refuses non-.m4v destinations: {path}")
    return path


def _clamp_crop(rect: Rect, wall_w: int, wall_h: int) -> tuple[int, int, int, int]:
    """`(x, y, w, h)` integer crop clamped to the frame; raises on a degenerate result."""
    x0 = max(0.0, rect.x)
    y0 = max(0.0, rect.y)
    x1 = min(float(wall_w), rect.x + rect.w)
    y1 = min(float(wall_h), rect.y + rect.h)
    x = int(round(x0))
    y = int(round(y0))
    w = max(0, min(int(round(x1 - x0)), wall_w - x))
    h = max(0, min(int(round(y1 - y0)), wall_h - y))
    if w <= 0 or h <= 0:
        raise ValueError(f"Degenerate crop rect after clamping: {rect} against {wall_w}x{wall_h}")
    return x, y, w, h


def crop_filter(rect: Rect, wall_w: int, wall_h: int) -> str | None:
    """ffmpeg `crop=w:h:x:y`, integer and clamped to the frame; `None` for a no-op
    full-frame crop. Raises `ValueError` for a degenerate crop (including an explicit one)."""
    x, y, w, h = _clamp_crop(rect, wall_w, wall_h)
    if x == 0 and y == 0 and w == wall_w and h == wall_h:
        return None
    return f"crop={w}:{h}:{x}:{y}"


def _normalize_even_crop(x: int, y: int, w: int, h: int, wall_w: int, wall_h: int) -> tuple[int, int, int, int]:
    """`(x, y, w, h)` floored/expanded to even, then re-clamped to the frame; ffmpeg rejects
    odd crop offsets/dims for chroma-subsampled codecs. Raises on a degenerate result."""
    ex = x - (x % 2)
    ey = y - (y % 2)
    ew = w + (x - ex)
    eh = h + (y - ey)
    ew += ew % 2
    eh += eh % 2
    ew = min(ew, wall_w - ex)
    eh = min(eh, wall_h - ey)
    ew -= ew % 2
    eh -= eh % 2
    if ew <= 0 or eh <= 0:
        raise ValueError(f"Degenerate crop after even-normalisation: {(x, y, w, h)} against {wall_w}x{wall_h}")
    return ex, ey, ew, eh


def _build_export_script(
    *,
    scratch_path: Path,
    stem: str,
    layout_template: Path | None,
    per_slide: Sequence[_SlideJob],
    codec: str,
    fps: float,
    black_layout_names: Sequence[str] = DEFAULT_BLACK_LAYOUT_NAMES,
) -> str:
    """One AppleScript, one document open for the whole batch, exported at its own native
    size; the clip is always cropped afterwards by ffmpeg, never by a Keynote resize."""
    keep = sorted({j.slide for j in per_slide})
    stem_name = _as_escape(scratch_path.stem)
    doc_name = _as_escape(scratch_path.name)
    fps_name = fps_enum_name(fps)
    approved_names = _applescript_string_list(black_layout_names)
    lines = [
        _keynote_terms(),
        _keynote_tell(),
        "  with timeout of 3600 seconds",
        "    activate",
        "    try",
        f'      close (every document whose name is "{stem_name}" or name is "{doc_name}") saving no',
        "      delay 0.3",
        "    end try",
        f'    set theFile to POSIX file "{_as_escape(str(scratch_path))}"',
        "    set theDoc to open theFile",
        "    delay 8",
        f'    if (name of theDoc) is not "{stem_name}" and (name of theDoc) is not "{doc_name}" then',
        '      error "scratch document name mismatch"',
        "    end if",
        "    tell theDoc",
        "      set slideCount to count of slides",
        f"      set keepList to {{{', '.join(str(n) for n in keep)}}}",
        "      repeat with i from slideCount to 1 by -1",
        "        if keepList does not contain i then delete slide i of theDoc",
        "      end repeat",
        '      set blackName to ""',
        f"      set approvedBlackNames to {approved_names}",
        "      repeat with lay in slide layouts of theDoc",
        "        set lname to (name of lay as text)",
        "        ignoring case",
        '          if blackName is "" and lname is in approvedBlackNames then set blackName to lname',
        "        end ignoring",
        "      end repeat",
        "      set blackLayoutName to blackName",
        "      set donorSlide to missing value",
    ]
    if layout_template is not None:
        lines += dsk_live.layout_import_lines("theDoc", "approvedBlackNames", layout_template)
    lines += [
        '      if blackLayoutName is "" then',
        '        error "no layout matching \\"black\\" resolvable in the FW deck or layout_template"',
        "      end if",
        "      set targetLayout to missing value",
        "      repeat with lay in slide layouts of theDoc",
        "        if (name of lay as text) is blackLayoutName then",
        "          set targetLayout to lay",
        "          exit repeat",
        "        end if",
        "      end repeat",
        "      if targetLayout is missing value then error \"resolved layout name not found in theDoc\"",
        "      repeat with s in slides of theDoc",
        "        if s is not donorSlide then set base layout of s to targetLayout",
        "      end repeat",
        "      repeat with s in slides of theDoc",
        "        if s is not donorSlide and (name of base layout of s as text) is not blackLayoutName then",
        '          error "base layout verify failed"',
        "        end if",
        "      end repeat",
        "      if donorSlide is not missing value then delete donorSlide",
        "      repeat with s in slides of theDoc",
        "        set skipped of s to true",
        "      end repeat",
    ]
    for j in sorted(per_slide, key=lambda j: j.ordinal):
        lines.append(f"      set skipped of slide {j.ordinal} of theDoc to false")
        for kind, kind_index in _delete_order(j.delete_ids):
            name = _AS_KIND_NAMES.get(kind)
            if not name:
                raise ValueError(f"Slide {j.slide}: no AppleScript class name for delete kind {kind!r}")
            addr = f"{name} {kind_index + 1} of slide {j.ordinal}"
            lines += [
                "      try",
                f"        set theObj to {addr}",
                "        if locked of theObj then set locked of theObj to false",
                "        delete theObj",
                "      on error errMsg number errNum",
                f'        log ("DELETEFAIL" & tab & "{j.slide}" & tab & "{addr}" & tab & errNum & tab & errMsg)',
                "      end try",
            ]
        lines += [
            "      try",
            f'        export theDoc to POSIX file "{_as_escape(str(j.tmp))}" as QuickTime movie with properties '
            f"{{movie format:native size, movie codec:{codec}, movie framerate:{fps_name}, skipped slides:false}}",
            "      on error errMsg number errNum",
            f'        log ("ERR" & tab & "{j.slide}" & tab & errNum & tab & errMsg)',
            "        error errMsg number errNum",
            "      end try",
            f'      log ("OBED" & tab & "{j.slide}" & tab & ((current date) as string))',
            f"      set skipped of slide {j.ordinal} of theDoc to true",
        ]
    lines += [
        "    end tell",
        "    try",
        "      close theDoc saving no",
        "    end try",
        "  end timeout",
        "end tell",
        "end using terms from",
    ]
    return "\n".join(lines)


def _ffprobe(path: Path) -> tuple[int, int, float, float]:
    """`(width, height, fps, duration_s)` via ffprobe, falling back to `ffmpeg -i`
    stderr parsing; rejects zero dimensions/fps/duration."""
    exe = ffmpeg_exe()
    probe_exe = None
    if exe:
        candidate = Path(exe).with_name("ffprobe")
        if candidate.exists():
            probe_exe = str(candidate)
    probe_exe = probe_exe or shutil.which("ffprobe")
    width = height = 0
    fps = duration = 0.0
    probe_failed = False
    if probe_exe:
        try:
            proc = subprocess.run(
                [
                    probe_exe,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height,r_frame_rate",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            data = json.loads(proc.stdout)
            stream = (data.get("streams") or [{}])[0]
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            rate = str(stream.get("r_frame_rate") or "0/1")
            num, _, den = rate.partition("/")
            fps = float(num) / float(den) if den and float(den) else 0.0
            duration = float((data.get("format") or {}).get("duration") or 0.0)
        except Exception:
            probe_failed = True
    if not probe_exe or probe_failed or not (width and height and fps and duration):
        if not exe:
            raise RuntimeError(f"ffprobe unavailable/failed and no ffmpeg fallback for {path}")
        proc = subprocess.run([exe, "-i", str(path)], capture_output=True, text=True)
        text = proc.stderr
        dur_m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", text)
        if dur_m:
            h, m, s = dur_m.groups()
            duration = int(h) * 3600 + int(m) * 60 + float(s)
        stream_m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})[,\s].*?(\d+(?:\.\d+)?)\s*fps", text)
        if not stream_m:
            raise RuntimeError(f"Could not parse ffmpeg -i output for {path}:\n{text[-1000:]}")
        width, height, fps = int(stream_m.group(1)), int(stream_m.group(2)), float(stream_m.group(3))
    if not (width and height and fps and duration):
        raise RuntimeError(f"Probed zero width/height/fps/duration for {path}: {width}x{height} {fps}fps {duration}s")
    return width, height, fps, duration


def _run_ffmpeg_stage(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({' '.join(cmd)}):\n{proc.stderr[-2000:]}")


def _ffmpeg_process(
    raw: Path, dest: Path, *, crop_rect: Rect | None, wall_w: int, wall_h: int, codec: str
) -> tuple[int, int]:
    """Publishes `raw` to `dest` (a `.mov`): `-c copy` remux when there's no crop, else an
    even-normalised crop + re-encode. Returns the expected `(width, height)` of `dest`."""
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg executable not found")
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw_w, raw_h, _raw_fps, _raw_duration = _ffprobe(raw)
    if (raw_w, raw_h) != (wall_w, wall_h):
        raise RuntimeError(f"Raw export {raw} is {raw_w}x{raw_h}, expected native wall size {wall_w}x{wall_h}")
    if crop_rect is None:
        _run_ffmpeg_stage([exe, "-y", "-i", str(raw), "-c", "copy", str(dest)])
        return wall_w, wall_h
    x, y, w, h = _clamp_crop(crop_rect, wall_w, wall_h)
    if x == 0 and y == 0 and w == wall_w and h == wall_h:
        _run_ffmpeg_stage([exe, "-y", "-i", str(raw), "-c", "copy", str(dest)])
        return wall_w, wall_h
    x, y, w, h = _normalize_even_crop(x, y, w, h, wall_w, wall_h)
    flt = crop_filter(Rect(x, y, w, h), wall_w, wall_h)
    encoder, *extra = _crop_encoder_args(codec)
    _run_ffmpeg_stage(
        [
            exe,
            "-y",
            "-i",
            str(raw),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-vf",
            flt,
            "-c:v",
            encoder,
            *extra,
            "-c:a",
            "copy",
            str(dest),
        ]
    )
    return w, h


_BLACK_LEVEL = 16
_QUADRANT_W_FRAC = 0.55
_QUADRANT_H_FRAC = 0.95
_SAMPLE_FRACTIONS = (0.25, 0.5, 0.75)
_MIN_EXPECTED_COVERAGE = 0.5
_LOW_INFO_DENSITY = 0.02


def _non_black_stats(path: Path, *, at_s: float = 1.0) -> tuple[tuple[int, int, int, int] | None, float]:
    """Non-black pixel bbox and density (fraction of pixels above `_BLACK_LEVEL`) of the
    frame at `at_s` seconds into `path`, via an ffmpeg frame grab + PIL."""
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg executable not found")
    with tempfile.TemporaryDirectory() as tmp:
        frame_path = Path(tmp) / "frame.png"
        proc = subprocess.run(
            [exe, "-y", "-ss", str(at_s), "-i", str(path), "-frames:v", "1", str(frame_path)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not frame_path.exists():
            raise RuntimeError(f"ffmpeg frame extraction failed for {path}:\n{proc.stderr[-2000:]}")
        with Image.open(frame_path) as img:
            gray = img.convert("L")
            mask = gray.point(lambda p: 255 if p > _BLACK_LEVEL else 0)
            histogram = mask.histogram()
            total = sum(histogram)
            density = (histogram[255] / total) if total else 0.0
            return mask.getbbox(), density


def _clip_sample_times(duration: float) -> tuple[float, ...]:
    hi = max(duration - 0.05, 0.0)
    return tuple(sorted({min(max(duration * f, 0.0), hi) for f in _SAMPLE_FRACTIONS}))


def _assert_clip_covers_frame(
    path: Path,
    width: int,
    height: int,
    *,
    duration: float,
    expected: Rect | None = None,
    log: Callable[[str], None] = print,
) -> None:
    """Refuses `path` when non-black content over sampled frames is confined to a quadrant
    of `width`x`height` or covers too little of `expected`; low-density samples warn instead."""
    boxes = []
    for t in _clip_sample_times(duration):
        bbox, density = _non_black_stats(path, at_s=t)
        if bbox is None:
            continue
        if density < _LOW_INFO_DENSITY:
            log(f"Clip {path} at {t:.2f}s: non-black density {density:.2%} is low-information; excluded from content assert.")
            continue
        boxes.append(bbox)
    if not boxes:
        log(f"Clip {path}: no sample had enough non-black content; content assert skipped.")
        return
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    bbox_w, bbox_h = x1 - x0, y1 - y0

    top_left_confined = x1 <= _QUADRANT_W_FRAC * width and y1 <= _QUADRANT_H_FRAC * height
    expected_top_left = (
        expected is not None
        and expected.x + expected.w <= _QUADRANT_W_FRAC * width
        and expected.y + expected.h <= _QUADRANT_H_FRAC * height
    )
    if top_left_confined and not expected_top_left:
        raise RuntimeError(
            f"Clip {path}: non-black content confined to {bbox_w}x{bbox_h} of a {width}x{height} "
            f"frame ({(x0, y0, x1, y1)}); refusing the coal-slide signature."
        )

    if expected is not None and expected.w > 0 and expected.h > 0:
        inter_w = max(0.0, min(x1, expected.x + expected.w) - max(x0, expected.x))
        inter_h = max(0.0, min(y1, expected.y + expected.h) - max(y0, expected.y))
        expected_area = expected.w * expected.h
        if (inter_w * inter_h) < _MIN_EXPECTED_COVERAGE * expected_area:
            raise RuntimeError(
                f"Clip {path}: non-black content {(x0, y0, x1, y1)} covers less than "
                f"{_MIN_EXPECTED_COVERAGE:.0%} of the expected content rect {expected}."
            )


def _derive_include_side_crop(payload: dict, slides: Collection[int]) -> dict[int, Rect]:
    wall = (float(payload["slideWidth"]), float(payload["slideHeight"]))
    by_number = {s["number"]: s for s in payload["slides"]}
    derived: dict[int, Rect] = {}
    for n in slides:
        slide = by_number.get(n)
        if slide is None:
            raise ValueError(f"Slide {n} not found for include_side crop derivation")
        union = visible_union(
            slide["items"], include_side=True, wall=wall, group_child_text=slide.get("groupChildSignature")
        )
        if union is None or union.w <= 0 or union.h <= 0:
            raise ValueError(f"Slide {n}: degenerate visible union for include_side crop; pass crop_rects explicitly.")
        derived[n] = union
    return derived


def _expected_content_rect(
    payload: dict, slide_number: int, *, include_side: bool, crop_origin: tuple[int, int], wall: tuple[float, float]
) -> Rect | None:
    """The slide's offline `visible_union`, remapped from wall space into the exported
    clip's own frame pixels (the clip's origin is `crop_origin` in wall space)."""
    by_number = {s["number"]: s for s in payload["slides"]}
    slide = by_number.get(slide_number)
    if slide is None:
        return None
    union = visible_union(
        slide["items"], include_side=include_side, wall=wall, group_child_text=slide.get("groupChildSignature")
    )
    if union is None:
        return None
    ox, oy = crop_origin
    return Rect(union.x - ox, union.y - oy, union.w, union.h)


def _derive_delete_ids(
    classes: Mapping[int, SlideClass],
    slides_by_number: Mapping[int, dict],
    slides: Collection[int],
) -> dict[int, tuple[ItemId, ...]]:
    """Non-content drawable ids for each of ``slides`` -- side/backdrop/duplicate drops plus
    anything else the classifier excludes. Refuses an empty/skipped slide outright."""
    derived: dict[int, tuple[ItemId, ...]] = {}
    for n in slides:
        cls = classes.get(n)
        slide = slides_by_number.get(n)
        if cls is None or slide is None:
            raise ValueError(f"Slide {n} not found in classified deck")
        if cls.category == "empty":
            raise ValueError(f"Slide {n} is empty/skipped; refusing to derive delete ids for it")
        all_ids = {(item["kind"], item["kindIndex"]) for item in slide.get("items") or []}
        excluded_ids = all_ids - set(cls.kept) - set(cls.dropped_side)
        derived[n] = _delete_order(list(cls.dropped_side) + list(excluded_ids))
    return derived


def _validate_delete_ids(number: int, ids: Collection[ItemId], cls: SlideClass, slide: dict) -> None:
    """Refuses a supplied delete id absent from the slide, or one that is part of ``cls.kept``."""
    all_ids = {(item["kind"], item["kindIndex"]) for item in slide.get("items") or []}
    supplied = set(ids)
    invalid = supplied - all_ids
    if invalid:
        raise ValueError(f"Slide {number}: delete_ids {sorted(invalid)} not present on the slide")
    overlap = supplied & set(cls.kept)
    if overlap:
        raise ValueError(f"Slide {number}: delete_ids {sorted(overlap)} are kept content; refusing")


def export_slide_clips(
    fw_deck: Path,
    slides: Sequence[int],
    out_dir: Path,
    *,
    include_side: Collection[int] = (),
    codec: str = "AppleProRes422LT",
    fps: float = 30,
    crop_rects: Mapping[int, Rect] | None = None,
    delete_ids: Mapping[int, Collection[ItemId]] | None = None,
    log: Callable[[str], None] = print,
    rss_limit_bytes: int = DEFAULT_RSS_LIMIT_BYTES,
    layout_template: Path | None = None,
    black_layout_names: Sequence[str] = DEFAULT_BLACK_LAYOUT_NAMES,
) -> list[ClipResult]:
    fw_deck = Path(fw_deck)
    out_dir = Path(out_dir).resolve()
    if codec not in CODECS:
        raise ValueError(f"Unsupported codec {codec!r}; expected one of {sorted(CODECS)}")
    fps_enum_name(fps)
    expected_fps = fps_rational(fps)
    dsk_live.guard_out_dir(out_dir, fw_deck)

    payload = offline_wall_payload(fw_deck)
    attach_group_content_signature(fw_deck, payload)
    wall_w, wall_h = int(payload["slideWidth"]), int(payload["slideHeight"])
    if not is_lw_wall(wall_w, wall_h):
        raise ValueError(f"{fw_deck} is {wall_w}x{wall_h}, not a 7680x1080 LW wall deck.")

    include_side = set(include_side)
    slides_by_number = {s["number"]: s for s in payload["slides"]}
    classes = {
        c.number: c
        for c in classify_deck(fw_deck, include_side=frozenset(include_side), payload=payload)
    }

    crop_rects = dict(crop_rects or {})
    missing_crop = [n for n in include_side if n in slides and n not in crop_rects]
    if missing_crop:
        crop_rects.update(_derive_include_side_crop(payload, missing_crop))

    delete_ids = dict(delete_ids or {})
    for n in slides:
        cls = classes.get(n)
        slide = slides_by_number.get(n)
        if cls is None or slide is None:
            raise ValueError(f"Slide {n} not found in {fw_deck}")
        for w in cls.mirror_warnings:
            log(f"slide {n}: {w}")
        if cls.category == "empty":
            raise ValueError(f"Slide {n} is empty/skipped; refusing to export it")
        if n in delete_ids:
            _validate_delete_ids(n, delete_ids[n], cls, slide)
    missing_deletes = [n for n in slides if n not in delete_ids]
    if missing_deletes:
        delete_ids.update(_derive_delete_ids(classes, slides_by_number, missing_deletes))

    dests = {n: out_dir / clip_name(fw_deck.stem, n) for n in slides}

    if _keynote_running():
        raise RuntimeError("Keynote is already running; close it before an export batch (strictly serial).")

    primary_exc: Exception | None = None
    lock_fd = _acquire_lock()
    try:
        poke = _DisplayPoke()
        watchdog: _RssWatchdog | None = None
        scratch: Path | None = None
        stem_name = fw_deck.stem
        doc_name = fw_deck.name
        src_fingerprint: tuple | None = None
        src_fingerprint = _fingerprint_source(fw_deck)
        t0 = time.monotonic()
        poke.start()
        work = out_dir / f".dsk-export-{fw_deck.stem}-{uuid.uuid4().hex}"
        work.mkdir(parents=True, exist_ok=True)
        scratch = work / fw_deck.name
        stem_name = scratch.stem
        doc_name = scratch.name

        keep = sorted(dests)
        ordinals = ordinal_map(keep)
        per_slide: list[_SlideJob] = []
        for n in keep:
            crop_rect = crop_rects[n] if n in include_side else CENTRE_PANEL_RECT
            per_slide.append(
                _SlideJob(
                    slide=n,
                    ordinal=ordinals[n],
                    crop_rect=crop_rect,
                    dest=dests[n],
                    tmp=require_m4v(work / f"tmp.{n:04d}.m4v"),
                    delete_ids=tuple(delete_ids.get(n, ())),
                )
            )

        resolved_template = layout_template or DEFAULT_LAYOUT_TEMPLATE
        resolved_template = resolved_template if resolved_template.exists() else None
        script = _build_export_script(
            scratch_path=scratch,
            stem=fw_deck.stem,
            layout_template=resolved_template,
            per_slide=per_slide,
            codec=codec,
            fps=fps,
            black_layout_names=black_layout_names,
        )
        script_path = _osascript_path(script, work)

        osa_proc_holder: list[subprocess.Popen | None] = [None]

        def register_proc(proc: subprocess.Popen | None) -> None:
            osa_proc_holder[0] = proc

        def on_breach() -> None:
            proc = osa_proc_holder[0]
            if proc is not None:
                proc.terminate()
            log(f"RSS watchdog breach (limit {rss_limit_bytes} bytes); terminating export.")

        watchdog = _RssWatchdog(_keynote_pid, rss_limit_bytes, on_breach)
        watchdog.start()

        elapsed_by_slide: dict[int, float] = {}

        def on_progress(slide: int) -> None:
            elapsed_by_slide[slide] = time.monotonic() - t0

        attempts = 0
        proc = None
        while True:
            attempts += 1
            copy_keynote(fw_deck, scratch)
            proc = _run_osascript(script_path, register_proc=register_proc, on_progress=on_progress)
            if proc.returncode == 0 or "-1712" not in (proc.stderr or "") or attempts >= 2:
                break
            log("AppleScript -1712 timeout; retrying export batch once.")
            _quit_and_wait_for_exit(stem_name, doc_name, out_dir)

        last_error: tuple[int, str] | None = None
        delete_fail: tuple[int, str, int, str] | None = None
        for line in (proc.stderr or "").splitlines():
            error_m = _ERROR_RE.match(line)
            if error_m:
                last_error = (int(error_m.group(2)), error_m.group(3))
            delete_fail_m = _DELETEFAIL_RE.match(line)
            if delete_fail_m and delete_fail is None:
                delete_fail = (
                    int(delete_fail_m.group(1)),
                    delete_fail_m.group(2),
                    int(delete_fail_m.group(3)),
                    delete_fail_m.group(4),
                )

        if delete_fail is not None:
            slide, addr, errnum, errmsg = delete_fail
            raise RuntimeError(
                f"Keynote delete failed on slide {slide} ({addr}, errNum {errnum}): {errmsg}"
            )

        if proc.returncode != 0:
            if last_error is not None:
                errnum, errmsg = last_error
                raise RuntimeError(f"Keynote export failed (errNum {errnum}): {errmsg}")
            raise RuntimeError(f"Keynote export AppleScript failed:\n{proc.stderr}")

        results: list[ClipResult] = []
        for job in per_slide:
            if not job.tmp.exists():
                raise RuntimeError(f"Expected export missing for slide {job.slide}: {job.tmp}")
            publish_tmp = work / f"pub.{job.slide:04d}.mov"
            expected_w, expected_h = _ffmpeg_process(
                job.tmp, publish_tmp, crop_rect=job.crop_rect, wall_w=wall_w, wall_h=wall_h, codec=codec
            )
            width, height, fps_out, duration = _ffprobe(publish_tmp)
            if (width, height) != (expected_w, expected_h):
                raise RuntimeError(
                    f"Slide {job.slide}: exported {width}x{height} does not match expected "
                    f"{expected_w}x{expected_h}"
                )
            if abs(fps_out - expected_fps) > _FPS_TOLERANCE:
                raise RuntimeError(f"Slide {job.slide}: exported fps {fps_out} does not match requested {fps}")
            crop_x, crop_y, crop_w, crop_h = _clamp_crop(job.crop_rect, wall_w, wall_h)
            crop_x, crop_y, crop_w, crop_h = _normalize_even_crop(crop_x, crop_y, crop_w, crop_h, wall_w, wall_h)
            expected_rect = _expected_content_rect(
                payload,
                job.slide,
                include_side=job.slide in include_side,
                crop_origin=(crop_x, crop_y),
                wall=(float(wall_w), float(wall_h)),
            )
            _assert_clip_covers_frame(publish_tmp, width, height, duration=duration, expected=expected_rect, log=log)
            job.dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(publish_tmp, job.dest)
            results.append(
                ClipResult(
                    slide=job.slide,
                    path=job.dest,
                    width=width,
                    height=height,
                    duration_s=duration,
                    wall_s=elapsed_by_slide.get(job.slide, time.monotonic() - t0),
                    crop_width=crop_w,
                )
            )

        return results
    except Exception as exc:
        primary_exc = exc
        raise
    finally:
        if watchdog is not None:
            try:
                watchdog.stop()
            except Exception:
                pass
        try:
            if _keynote_running():
                _run_quit_script(stem_name, doc_name, out_dir)
        except Exception:
            pass
        try:
            poke.stop()
        except Exception:
            pass
        try:
            if scratch is not None:
                shutil.rmtree(scratch.parent, ignore_errors=True)
        except Exception:
            pass
        try:
            _release_lock(lock_fd)
        except Exception:
            pass
        try:
            after_fingerprint = _fingerprint_source(fw_deck)
        except OSError:
            after_fingerprint = None
        if src_fingerprint is not None and after_fingerprint != src_fingerprint:
            mismatch_msg = f"Source deck changed during export: {fw_deck}"
            if primary_exc is None:
                raise RuntimeError(mismatch_msg)
            log(mismatch_msg)
