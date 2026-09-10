"""Movie-crop pipeline for the DSK generator (d3): scratch centre-panel deck ->
per-slide QuickTime `.m4v` export -> ffmpeg crop/remux, with the operator safety
rails the live probes required (process lock, display poke, RSS watchdog).

Shared by the DSK deck assembly (d4) and the standalone Exporter (d5b). Offline
helpers never touch Keynote; the live path is isolated behind `export_slide_clips`
and `_run_osascript`/`_ffprobe` so tests can fake it. Must not import `web.*`.
Audio is passed through unmodified (incl. volume) to follow the source slide's own behaviour.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from obed_edom import keynote_app
from obed_edom.dsk_plan import visible_union
from obed_edom.map_remap import Rect
from obed_edom.maps_geo import CENTRE_ORIGIN_X
from obed_edom.maps_movie import ffmpeg_exe
from obed_edom.offline_inspect import offline_wall_payload
from obed_edom.remap_keynote import copy_keynote

LOCK_PATH = Path.home() / "Library" / "Application Support" / "obed-edom" / "keynote.lock"
DEFAULT_LAYOUT_TEMPLATE = Path.home() / "Desktop" / "Default Templates" / "2026_Lower-Thirds (ENG).key"
DEFAULT_RSS_LIMIT_BYTES = 3_000_000_000
_DISPLAY_POKE_INTERVAL_S = 30
_RSS_WATCHDOG_INTERVAL_S = 2
_APPLESCRIPT_TIMEOUT_S = 3600
_KEYNOTE_QUIT_WAIT_S = 30
_KEYNOTE_QUIT_POLL_S = 0.5
_PROGRESS_RE = re.compile(r"^OBED\t(\d+)\t")
_ERROR_RE = re.compile(r"^ERR\t(\d+)\t(-?\d+)\t(.*)$")
_FPS_TOLERANCE = 0.01

DEFAULT_BLACK_LAYOUT_NAMES: tuple[str, ...] = ("BLACK BLANK", "Black", "BLACK", "black")

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
    scratch_width: int


@dataclass(frozen=True)
class _SlideJob:
    slide: int
    ordinal: int
    width: int
    height: int
    dx: float
    dest: Path
    tmp: Path


def scratch_canvas(slide: int, include_side: Collection[int]) -> tuple[int, int, float]:
    """`(width, height, dx)` for the scratch canvas serving `slide`: centre-panel-only
    3840x1080 translated by `-CENTRE_ORIGIN_X`, or the full 7680x1080 wall untranslated
    when `slide` is marked include_side."""
    if slide in include_side:
        return (7680, 1080, 0.0)
    return (3840, 1080, -float(CENTRE_ORIGIN_X))


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


def ordinal_map(keep: Collection[int]) -> dict[int, int]:
    """Original slide number -> new ordinal after deleting everything not in `keep`."""
    return {n: i + 1 for i, n in enumerate(sorted(set(keep)))}


def _osascript_path(script: str, out_dir: Path) -> Path:
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".applescript", delete=False, dir=str(out_dir)
    )
    handle.write(script)
    handle.close()
    return Path(handle.name)


def _run_osascript(
    script_path: Path,
    *,
    timeout: int = _APPLESCRIPT_TIMEOUT_S,
    register_proc: Callable[[subprocess.Popen], None] | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> subprocess.CompletedProcess:
    """Runs osascript via an owned `Popen` (so a watchdog can `terminate()` it). Exactly one
    reader thread per pipe drains stdout/stderr live -- Keynote's `log` writes to stderr, not
    stdout -- and `on_progress` fires as each `OBED` marker is received, not after the fact.
    Never call `Popen.communicate()` here: it would spawn its own reader on the same pipes."""
    proc = subprocess.Popen(
        ["osascript", str(script_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    if register_proc is not None:
        register_proc(proc)
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def _drain_stdout() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            stdout_lines.append(line)

    def _drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line)
            if on_progress is not None:
                match = _PROGRESS_RE.match(line)
                if match:
                    on_progress(int(match.group(1)))

    stdout_thread = threading.Thread(target=_drain_stdout, daemon=True)
    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    try:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    finally:
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        if register_proc is not None:
            register_proc(None)
    return subprocess.CompletedProcess(proc.args, proc.returncode, "".join(stdout_lines), "".join(stderr_lines))


def _keynote_tell() -> str:
    return f'tell application id "{keynote_app.bundle_id()}"'


def _keynote_terms() -> str:
    return f'using terms from application id "{keynote_app.bundle_id()}"'


def _as_escape(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", '" & return & "')
    )


def _pid_start_time(pid: int) -> str | None:
    try:
        proc = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True)
        text = proc.stdout.strip()
        return text or None
    except Exception:
        return None


def _acquire_lock() -> int:
    """Exclusive, non-blocking `flock` on a persistent lock file for the whole batch. The
    written pid+lstart is diagnostic only; the flock itself is the concurrency guard."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise RuntimeError(f"Keynote lock held ({LOCK_PATH}); refusing to run concurrently.") from None
    payload = f"{os.getpid()}\n{_pid_start_time(os.getpid()) or ''}"
    os.ftruncate(fd, 0)
    os.write(fd, payload.encode())
    os.fsync(fd)
    return fd


def _release_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _keynote_pids() -> list[int]:
    """Live Keynote pids, matched by `CFBundleExecutable` (never by app display name, which
    varies across installs, e.g. "Keynote Creator Studio"). Falls back to scanning `ps` for a
    `comm` path under the app's `Contents/MacOS/` when `pgrep -x` misses (e.g. a long comm
    truncated by pgrep)."""
    exe = keynote_app.executable_name(keynote_app.bundle_id())
    if exe is None:
        raise RuntimeError("Keynote application not resolvable; cannot determine whether it is running.")
    try:
        proc = subprocess.run(["pgrep", "-x", exe], capture_output=True, text=True)
        pids = [int(l) for l in proc.stdout.strip().splitlines() if l.strip()]
        if pids:
            return pids
    except Exception:
        pass
    app = keynote_app.app_path(keynote_app.bundle_id())
    if app is None:
        return []
    macos_dir = str(app / "Contents" / "MacOS")
    try:
        proc = subprocess.run(["ps", "-axo", "pid=,comm="], capture_output=True, text=True)
    except Exception:
        return []
    pids = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_text, _sep, comm = line.partition(" ")
        if pid_text.isdigit() and comm.strip().startswith(macos_dir):
            pids.append(int(pid_text))
    return pids


def _keynote_running() -> bool:
    return bool(_keynote_pids())


def _keynote_pid() -> int | None:
    pids = _keynote_pids()
    return pids[0] if pids else None


class _DisplayPoke:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._caffeinate: subprocess.Popen | None = None

    def start(self) -> None:
        try:
            self._caffeinate = subprocess.Popen(["caffeinate", "-dimsu"])
        except Exception:
            self._caffeinate = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(_DISPLAY_POKE_INTERVAL_S):
            try:
                subprocess.run(["caffeinate", "-u", "-t", "2"], check=False)
            except Exception:
                pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._caffeinate is not None:
            self._caffeinate.terminate()


class _RssWatchdog:
    """Samples Keynote's RSS and terminates the registered osascript child on breach."""

    def __init__(self, get_pid: Callable[[], int | None], limit_bytes: int, on_breach: Callable[[], None]):
        self._get_pid = get_pid
        self._limit_bytes = limit_bytes
        self._on_breach = on_breach
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.breached = False
        self.peak_rss_bytes = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(_RSS_WATCHDOG_INTERVAL_S):
            pid = self._get_pid()
            if pid is None:
                continue
            rss = _sample_rss_bytes(pid)
            if rss is None:
                continue
            self.peak_rss_bytes = max(self.peak_rss_bytes, rss)
            if rss > self._limit_bytes:
                self.breached = True
                self._on_breach()
                return

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


def _sample_rss_bytes(pid: int) -> int | None:
    try:
        proc = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True)
        text = proc.stdout.strip()
        return int(text) * 1024 if text else None
    except Exception:
        return None


def _applescript_string_list(values: Sequence[str]) -> str:
    return "{" + ", ".join(f'"{_as_escape(v)}"' for v in values) + "}"


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
    """One AppleScript, one document open for the whole batch. Canvas groups are processed
    widest-first so the document width only ever shrinks between exports, never grows back up
    right before one (observed to leave the export pillarboxed at the narrower width)."""
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
        lines += [
            '      if blackLayoutName is "" then',
            "        try",
            f'          set tmplDoc to open POSIX file "{_as_escape(str(layout_template))}"',
            "          delay 2",
            '          set donorLayoutName to ""',
            "          set donorLayout to missing value",
            "          repeat with lay in slide layouts of tmplDoc",
            "            set tname to (name of lay as text)",
            "            ignoring case",
            '              if donorLayoutName is "" and tname is in approvedBlackNames then',
            "                set donorLayoutName to tname",
            "                set donorLayout to lay",
            "              end if",
            "            end ignoring",
            "          end repeat",
            '          if donorLayoutName is "" then error "no black layout found in layout_template"',
            "          set madeSlide to (make new slide at end of slides of tmplDoc with properties {base layout:donorLayout})",
            "          move madeSlide to end of slides of theDoc",
            "          set donorSlide to slide (count of slides of theDoc) of theDoc",
            "          set blackLayoutName to donorLayoutName",
            "          close tmplDoc saving no",
            "        on error errMsg number errNum",
            "          try",
            "            close tmplDoc saving no",
            "          end try",
            '          error "layout import failed: " & errMsg number errNum',
            "        end try",
            "      end if",
        ]
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
    groups = sorted({(j.width, j.height, j.dx) for j in per_slide}, key=lambda g: g[0], reverse=True)
    for group_w, group_h, dx in groups:
        group_jobs = [j for j in per_slide if (j.width, j.height, j.dx) == (group_w, group_h, dx)]
        lines += [
            f"      set width of theDoc to {group_w}",
            f"      set height of theDoc to {group_h}",
        ]
        if dx != 0:
            for j in group_jobs:
                lines += [
                    f"      repeat with itm in iWork items of slide {j.ordinal} of theDoc",
                    "        set wasLocked to locked of itm",
                    "        if wasLocked then set locked of itm to false",
                    "        set {ix, iy} to (position of itm)",
                    f"        set position of itm to {{ix + ({dx}), iy}}",
                    "        if wasLocked then set locked of itm to true",
                    "      end repeat",
                ]
        for j in group_jobs:
            lines += [
                f"      set skipped of slide {j.ordinal} of theDoc to false",
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


def _quit_script(stem: str, doc_name: str) -> str:
    """Closes only the owned scratch document (by stem or filename) then quits Keynote.
    Caller must only invoke this when Keynote is already running -- never to launch it."""
    stem_escaped = _as_escape(stem)
    doc_escaped = _as_escape(doc_name)
    return "\n".join(
        [
            _keynote_terms(),
            _keynote_tell(),
            "  try",
            f'    close (every document whose name is "{stem_escaped}" or name is "{doc_escaped}") saving no',
            "  end try",
            "  try",
            "    quit",
            "  end try",
            "end tell",
            "end using terms from",
        ]
    )


def _run_quit_script(stem: str, doc_name: str, out_dir: Path) -> None:
    quit_path = _osascript_path(_quit_script(stem, doc_name), out_dir)
    try:
        _run_osascript(quit_path, timeout=60)
    finally:
        quit_path.unlink(missing_ok=True)


def _quit_and_wait_for_exit(stem: str, doc_name: str, out_dir: Path) -> None:
    """Quits the owned scratch document's Keynote, then blocks until no Keynote process
    remains (bounded), so a retry never recopies the scratch under a still-open document.
    Raises if Keynote is still running at the deadline: the caller must not treat that as
    a clean exit and must not recopy the scratch onto a document Keynote may still hold open."""
    if _keynote_running():
        _run_quit_script(stem, doc_name, out_dir)
    deadline = time.monotonic() + _KEYNOTE_QUIT_WAIT_S
    while _keynote_running() and time.monotonic() < deadline:
        time.sleep(_KEYNOTE_QUIT_POLL_S)
    if _keynote_running():
        raise RuntimeError("Keynote still running after quit; refusing to retry the export batch.")


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
    even-normalised crop + re-encode via `_crop_encoder_args`. Probes `raw` first and asserts
    it matches the scratch canvas. Returns the expected `(width, height)` of `dest` so the
    caller can validate the ffprobe result against it."""
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg executable not found")
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw_w, raw_h, _raw_fps, _raw_duration = _ffprobe(raw)
    if (raw_w, raw_h) != (wall_w, wall_h):
        raise RuntimeError(f"Raw export {raw} is {raw_w}x{raw_h}, expected scratch canvas {wall_w}x{wall_h}")
    if crop_rect is None:
        _run_ffmpeg_stage([exe, "-y", "-i", str(raw), "-c", "copy", str(dest)])
        return wall_w, wall_h
    x, y, w, h = _clamp_crop(crop_rect, wall_w, wall_h)
    if x == 0 and y == 0 and w == wall_w and h == wall_h:
        _run_ffmpeg_stage([exe, "-y", "-i", str(raw), "-c", "copy", str(dest)])
        return wall_w, wall_h
    x, y, w, h = _normalize_even_crop(x, y, w, h, wall_w, wall_h)
    flt = f"crop={w}:{h}:{x}:{y}"
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


def _fingerprint_source(path: Path) -> tuple:
    """Identity of the source `.key` for before/after integrity comparison: for a package
    (directory), every member's relative path, size, and mtime_ns; for a single file, the
    same for that file."""
    if path.is_dir():
        entries: list[tuple[str, int, int]] = []
        for root, _dirs, files in os.walk(path):
            for name in files:
                member = Path(root) / name
                st = member.stat()
                entries.append((str(member.relative_to(path)), st.st_size, st.st_mtime_ns))
        return tuple(sorted(entries))
    st = path.stat()
    return ((path.name, st.st_size, st.st_mtime_ns),)


def _derive_include_side_crop(fw_deck: Path, slides: Collection[int]) -> dict[int, Rect]:
    payload = offline_wall_payload(fw_deck)
    wall = (float(payload["slideWidth"]), float(payload["slideHeight"]))
    by_number = {s["number"]: s for s in payload["slides"]}
    derived: dict[int, Rect] = {}
    for n in slides:
        slide = by_number.get(n)
        if slide is None:
            raise ValueError(f"Slide {n} not found in {fw_deck} for include_side crop derivation")
        union = visible_union(slide["items"], include_side=True, wall=wall)
        if union is None or union.w <= 0 or union.h <= 0:
            raise ValueError(f"Slide {n}: degenerate visible union for include_side crop; pass crop_rects explicitly.")
        derived[n] = union
    return derived


def export_slide_clips(
    fw_deck: Path,
    slides: Sequence[int],
    out_dir: Path,
    *,
    include_side: Collection[int] = (),
    codec: str = "AppleProRes422LT",
    fps: float = 30,
    crop_rects: Mapping[int, Rect] | None = None,
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
    for bad in ("/private/tmp", "/tmp"):
        if str(out_dir) == bad or str(out_dir).startswith(bad + "/"):
            raise ValueError(f"Keynote cannot reliably open decks under {bad}; use a work dir under ~/Desktop.")
    resolved_deck = fw_deck.resolve()
    if str(out_dir) == str(resolved_deck) or str(out_dir).startswith(str(resolved_deck) + "/"):
        raise ValueError(f"out_dir must not be inside the source .key package: {resolved_deck}")

    include_side = set(include_side)
    crop_rects = dict(crop_rects or {})
    missing_crop = [n for n in include_side if n in slides and n not in crop_rects]
    if missing_crop:
        crop_rects.update(_derive_include_side_crop(fw_deck, missing_crop))

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
            w, h, dx = scratch_canvas(n, include_side)
            per_slide.append(
                _SlideJob(
                    slide=n,
                    ordinal=ordinals[n],
                    width=w,
                    height=h,
                    dx=dx,
                    dest=dests[n],
                    tmp=require_m4v(work / f"tmp.{n:04d}.m4v"),
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
        for line in (proc.stderr or "").splitlines():
            error_m = _ERROR_RE.match(line)
            if error_m:
                last_error = (int(error_m.group(2)), error_m.group(3))

        if proc.returncode != 0:
            if last_error is not None:
                errnum, errmsg = last_error
                raise RuntimeError(f"Keynote export failed (errNum {errnum}): {errmsg}")
            raise RuntimeError(f"Keynote export AppleScript failed:\n{proc.stderr}")

        results: list[ClipResult] = []
        for job in per_slide:
            if not job.tmp.exists():
                raise RuntimeError(f"Expected export missing for slide {job.slide}: {job.tmp}")
            crop_rect = crop_rects.get(job.slide) if job.slide in include_side else None
            publish_tmp = work / f"pub.{job.slide:04d}.mov"
            expected_w, expected_h = _ffmpeg_process(
                job.tmp, publish_tmp, crop_rect=crop_rect, wall_w=job.width, wall_h=job.height, codec=codec
            )
            width, height, fps_out, duration = _ffprobe(publish_tmp)
            if (width, height) != (expected_w, expected_h):
                raise RuntimeError(
                    f"Slide {job.slide}: exported {width}x{height} does not match expected "
                    f"{expected_w}x{expected_h}"
                )
            if abs(fps_out - expected_fps) > _FPS_TOLERANCE:
                raise RuntimeError(f"Slide {job.slide}: exported fps {fps_out} does not match requested {fps}")
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
                    scratch_width=job.width,
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
