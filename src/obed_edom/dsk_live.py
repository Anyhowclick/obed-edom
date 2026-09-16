"""Shared live-Keynote scaffold: process lock, display poke, RSS watchdog, osascript
runner, and the quit/fingerprint machinery `dsk_movie_export`'s `export_slide_clips`
(d3) was built around. Extracted so the DSK deck assembly (d4) and stage export (d5)
can reuse the same operator safety rails without depending on the movie-crop pipeline.

Offline helpers (`guard_out_dir`, `ordinal_map`, `layout_import_lines`) never touch
Keynote; the live path is isolated behind `run_osascript`/`LiveBatch` so tests can
fake it. Must not import `web.*`.
"""
from __future__ import annotations

import fcntl
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Collection, Sequence
from pathlib import Path

from obed_edom import keynote_app
from obed_edom.iwa_geometry import compose_geometry
from obed_edom.iwa_runs import _load_deck
from obed_edom.offline_inspect import _canvas_size
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

DEFAULT_BLACK_LAYOUT_NAMES: tuple[str, ...] = ("BLACK BLANK", "Black", "BLACK", "black")
DEFAULT_TRANSPARENT_LAYOUT_NAMES: tuple[str, ...] = ("Blank Black",)


def guard_out_dir(out_dir: Path, deck: Path) -> None:
    """Refuses an `out_dir` Keynote cannot reliably open decks under, or one nested
    inside the source `.key` package."""
    for bad in ("/private/tmp", "/tmp"):
        if str(out_dir) == bad or str(out_dir).startswith(bad + "/"):
            raise ValueError(f"Keynote cannot reliably open decks under {bad}; use a work dir under ~/Desktop.")
    resolved_deck = deck.resolve()
    if str(out_dir) == str(resolved_deck) or str(out_dir).startswith(str(resolved_deck) + "/"):
        raise ValueError(f"out_dir must not be inside the source .key package: {resolved_deck}")


def ordinal_map(keep: Collection[int], parts: dict[int, int] | None = None) -> dict[int, int]:
    """Original slide number -> its FIRST new ordinal after deleting everything not in
    `keep`, each slide claiming `parts.get(n, 1)` consecutive ordinals (default: every
    slide keeps its original single-ordinal meaning when `parts` is omitted)."""
    result: dict[int, int] = {}
    ordinal = 1
    for n in sorted(set(keep)):
        result[n] = ordinal
        ordinal += (parts or {}).get(n, 1)
    return result


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


class LayoutImportRefusal(ValueError):
    """A `check_layout_import_preconditions` precondition failed -- refuse rather
    than let a live import silently keep an unsafe layout."""


def _theme_layout_slides(objects: dict[str, dict]) -> list[tuple[str, dict, dict]]:
    """``[(name, layoutNode, layoutSlide)]`` for every ``KN.ThemeArchive.templates``
    entry -- Keynote's IWA graph has no separate layout type; a layout IS a
    ``KN.SlideArchive`` referenced from the theme's ``templates`` list (each a
    ``KN.SlideNodeArchive`` wrapping the slide, same shape as an ordinary slide)."""
    theme = next((o for o in objects.values() if o.get("_pbtype") == "KN.ThemeArchive"), None)
    if theme is None:
        return []
    out: list[tuple[str, dict, dict]] = []
    for ref in theme.get("templates") or []:
        node = objects.get(str(ref.get("identifier")))
        if not node:
            continue
        slide_id = (node.get("slide") or {}).get("identifier")
        slide = objects.get(str(slide_id)) if slide_id is not None else None
        if slide is None:
            continue
        out.append((slide.get("name") or "", node, slide))
    return out


def _find_layout_by_name(objects: dict[str, dict], name: str) -> dict | None:
    target = name.strip().lower()
    for layout_name, _node, slide in _theme_layout_slides(objects):
        if layout_name.strip().lower() == target:
            return slide
    return None


def layout_alpha_safe(slide_archive: dict, objects: dict[str, dict], canvas: tuple[float, float]) -> bool:
    """A slide/layout PNG-exports opaque whenever it owns a drawable spanning the full
    ``canvas`` (``x<=0``, ``y<=0``, ``x+w>=W``, ``y+h>=H``); one with no such drawable
    -- including zero drawables -- exports transparent. Frames come from
    ``compose_geometry`` (masks, rotation and group unions composed, not raw
    ``geometry``)."""
    width, height = canvas
    for rec in compose_geometry(slide_archive, objects):
        x, y, w, h = rec["x"], rec["y"], rec["w"], rec["h"]
        if x <= 0 and y <= 0 and x + w >= width and y + h >= height:
            return False
    return True


def check_layout_import_preconditions(
    fw_deck: Path,
    *,
    layout_template: Path,
    layout_names: Sequence[str],
) -> None:
    """Offline plan-time precondition for a live layout import, run before Keynote ever
    launches, for every name in `layout_names`. Shared by DSK assembly and the movie/stage
    exporters so none of them can bake in an unsafe same-named FW-owned layout. Refuses
    (``LayoutImportRefusal``) when:

    - a name is ``Blank`` -- never alpha-safe, never an import candidate.
    - `layout_template` has more than one layout named `name` -- a duplicate-name donor
      would be picked arbitrarily by `layout_import_lines`' own exact-name search.
    - `layout_template` has no layout named `name`, or that layout is not alpha-safe --
      importing a donor that isn't alpha-safe defeats the point.
    - `fw_deck` already owns a layout named `name` and it is NOT alpha-safe: the live
      import (`layout_import_lines`) skips a name `fw_deck` already owns, so it would
      silently keep the FW deck's own (unsafe) layout instead of the template's donor.
    """
    for name in layout_names:
        if name.strip().lower() == "blank":
            raise LayoutImportRefusal(f"refusing to import layout {name!r}: Blank is never alpha-safe")

    template_objects, _tf, _tfi = _load_deck(layout_template)
    fw_objects, _ff, _ffi = _load_deck(fw_deck)
    template_canvas = _canvas_size(template_objects)
    fw_canvas = _canvas_size(fw_objects)

    template_name_counts: dict[str, int] = {}
    for layout_name, _node, _slide in _theme_layout_slides(template_objects):
        key = layout_name.strip().lower()
        template_name_counts[key] = template_name_counts.get(key, 0) + 1

    for name in layout_names:
        key = name.strip().lower()
        if template_name_counts.get(key, 0) > 1:
            raise LayoutImportRefusal(
                f"layout template {layout_template} has "
                f"{template_name_counts[key]} layouts named {name!r}; a duplicate-name "
                "donor would be picked arbitrarily"
            )

        donor_slide = _find_layout_by_name(template_objects, name)
        if donor_slide is None:
            raise LayoutImportRefusal(f"no layout named {name!r} found in layout template {layout_template}")
        if not layout_alpha_safe(donor_slide, template_objects, template_canvas):
            raise LayoutImportRefusal(f"layout template donor {name!r} in {layout_template} is not alpha-safe")

        fw_owned = _find_layout_by_name(fw_objects, name)
        if fw_owned is not None and not layout_alpha_safe(fw_owned, fw_objects, fw_canvas):
            raise LayoutImportRefusal(
                f"FW deck already owns a layout named {name!r} that is not alpha-safe; "
                "layout_import_lines' own dedupe (skip a name fw_deck already owns) "
                "would keep it instead of importing the template's donor"
            )


def layout_import_lines(doc_var: str, layout_names: str | Sequence[str], template_path: Path) -> list[str]:
    """AppleScript lines that import every layout in `layout_names` (a single name is a
    special case of one) missing from `doc_var` -- one donor slide per missing layout,
    made in `template_path` with `base layout` set to the exact-named template layout,
    moved into `doc_var`, then deleted. A name `doc_var` already owns (case-insensitive)
    is left untouched -- Keynote's own name-based import dedupe never runs, so it can't
    silently keep an unsafe FW-owned layout instead."""
    if isinstance(layout_names, str):
        layout_names = [layout_names]
    lines = [
        "      try",
        f'        set tmplDoc to open POSIX file "{_as_escape(str(template_path))}"',
        "        delay 2",
        "        set pendingDonor to missing value",
    ]
    for name in layout_names:
        escaped_name = _as_escape(name)
        lines += [
            f'        set wantLayoutName to "{escaped_name}"',
            "        set haveLayout to false",
            f"        repeat with lay in slide layouts of {doc_var}",
            "          ignoring case",
            "            if (name of lay as text) is wantLayoutName then set haveLayout to true",
            "          end ignoring",
            "          if haveLayout then exit repeat",
            "        end repeat",
            "        if not haveLayout then",
            "          set donorLayout to missing value",
            "          repeat with lay in slide layouts of tmplDoc",
            "            ignoring case",
            "              if (name of lay as text) is wantLayoutName then set donorLayout to lay",
            "            end ignoring",
            "            if donorLayout is not missing value then exit repeat",
            "          end repeat",
            f'          if donorLayout is missing value then error "no layout named \\"{escaped_name}\\" found in layout_template"',
            "          set madeSlide to (make new slide at end of slides of tmplDoc with properties {base layout:donorLayout})",
            "          set pendingDonor to madeSlide",
            f"          move madeSlide to end of slides of {doc_var}",
            f"          set donorSlide to slide (count of slides of {doc_var}) of {doc_var}",
            "          set pendingDonor to donorSlide",
            "          delete donorSlide",
            "          set pendingDonor to missing value",
            "        end if",
        ]
    lines += [
        "        close tmplDoc saving no",
        "      on error errMsg number errNum",
        "        try",
        "          if pendingDonor is not missing value then delete pendingDonor",
        "        end try",
        "        try",
        "          close tmplDoc saving no",
        "        end try",
        '        error "layout import failed: " & errMsg number errNum',
        "      end try",
    ]
    return lines


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


# Public aliases for the names shared as API with d4/d5, alongside the underscore names
# kept for dsk_movie_export's existing internal/test seams.
acquire_lock = _acquire_lock
release_lock = _release_lock
keynote_running = _keynote_running
keynote_pid = _keynote_pid
run_osascript = _run_osascript
quit_and_wait_for_exit = _quit_and_wait_for_exit
DisplayPoke = _DisplayPoke
RssWatchdog = _RssWatchdog
fingerprint_source = _fingerprint_source


class LiveBatch:
    """Owns one live-Keynote batch end to end, in the same order `export_slide_clips`
    (dsk_movie_export, d3) uses: refuse-if-running -> lock -> poke start -> unique work
    dir under `out_dir` -> pristine `copy_keynote` scratch -> `run` the AppleScript with
    an RSS watchdog and a single -1712 retry (quit-and-wait + recopy) -> on exit: quit
    Keynote if still running, clean up the work dir, compare the source fingerprint, and
    release the lock. New API for d4/d5; `export_slide_clips` does not use it (its
    generated-script/attempt-counting shape doesn't map onto `.run()` without changing
    its behaviour)."""

    def __init__(
        self,
        deck: Path,
        out_dir: Path,
        *,
        rss_limit_bytes: int = DEFAULT_RSS_LIMIT_BYTES,
        log: Callable[[str], None] = print,
    ) -> None:
        self.deck = Path(deck)
        self.out_dir = Path(out_dir).resolve()
        self.rss_limit_bytes = rss_limit_bytes
        self.log = log
        self.work: Path | None = None
        self.scratch: Path | None = None
        self._lock_fd: int | None = None
        self._poke: _DisplayPoke | None = None
        self._watchdog: _RssWatchdog | None = None
        self._src_fingerprint: tuple | None = None
        self._primary_exc: Exception | None = None

    def __enter__(self) -> "LiveBatch":
        guard_out_dir(self.out_dir, self.deck)
        if _keynote_running():
            raise RuntimeError("Keynote is already running; close it before an export batch (strictly serial).")
        self._lock_fd = _acquire_lock()
        try:
            self._src_fingerprint = _fingerprint_source(self.deck)
            self._poke = _DisplayPoke()
            self._poke.start()
            self.work = self.out_dir / f".dsk-export-{self.deck.stem}-{uuid.uuid4().hex}"
            self.work.mkdir(parents=True, exist_ok=True)
            self.scratch = self.work / self.deck.name
            copy_keynote(self.deck, self.scratch)
        except Exception:
            try:
                if self._poke is not None:
                    self._poke.stop()
            except Exception:
                pass
            try:
                if self.work is not None:
                    shutil.rmtree(self.work, ignore_errors=True)
            except Exception:
                pass
            try:
                if self._lock_fd is not None:
                    _release_lock(self._lock_fd)
            except Exception:
                pass
            try:
                if _keynote_running():
                    stem_name = self.deck.stem
                    doc_name = self.deck.name
                    if self.scratch is not None:
                        stem_name, doc_name = self.scratch.stem, self.scratch.name
                    _run_quit_script(stem_name, doc_name, self.out_dir)
            except Exception:
                pass
            raise
        return self

    def run(
        self,
        script_path: Path,
        *,
        on_progress: Callable[[int], None] | None = None,
        retry_on_1712: bool = True,
    ) -> subprocess.CompletedProcess:
        """Runs `script_path` under the RSS watchdog, retrying once on a -1712 timeout
        (quit-and-wait for a clean exit, then a pristine re-copy of the scratch).
        `retry_on_1712=False` (a refit pass against an already-written scratch) disables
        the retry -- re-copying would discard the earlier pass's writes -- so a -1712
        there aborts the batch instead."""
        assert self.scratch is not None and self.work is not None
        stem_name = self.scratch.stem
        doc_name = self.scratch.name

        osa_proc_holder: list[subprocess.Popen | None] = [None]

        def register_proc(proc: subprocess.Popen | None) -> None:
            osa_proc_holder[0] = proc

        def on_breach() -> None:
            proc = osa_proc_holder[0]
            if proc is not None:
                proc.terminate()
            self.log(f"RSS watchdog breach (limit {self.rss_limit_bytes} bytes); terminating export.")

        self._watchdog = _RssWatchdog(_keynote_pid, self.rss_limit_bytes, on_breach)
        self._watchdog.start()

        attempts = 0
        proc = None
        while True:
            attempts += 1
            if attempts > 1:
                copy_keynote(self.deck, self.scratch)
            proc = _run_osascript(script_path, register_proc=register_proc, on_progress=on_progress)
            if proc.returncode == 0 or "-1712" not in (proc.stderr or "") or attempts >= 2 or not retry_on_1712:
                break
            self.log("AppleScript -1712 timeout; retrying export batch once.")
            _quit_and_wait_for_exit(stem_name, doc_name, self.out_dir)
        return proc

    def __exit__(self, exc_type, exc, _tb) -> None:
        self._primary_exc = exc
        assert self.scratch is not None and self.work is not None
        stem_name = self.scratch.stem
        doc_name = self.scratch.name
        if self._watchdog is not None:
            try:
                self._watchdog.stop()
            except Exception:
                pass
            self.log(f"Keynote peak RSS: {self._watchdog.peak_rss_bytes} bytes (limit {self.rss_limit_bytes} bytes)")
        try:
            if _keynote_running():
                _run_quit_script(stem_name, doc_name, self.out_dir)
        except Exception:
            pass
        try:
            if self._poke is not None:
                self._poke.stop()
        except Exception:
            pass
        try:
            shutil.rmtree(self.work, ignore_errors=True)
        except Exception:
            pass
        try:
            if self._lock_fd is not None:
                _release_lock(self._lock_fd)
        except Exception:
            pass
        try:
            after_fingerprint = _fingerprint_source(self.deck)
        except OSError:
            after_fingerprint = None
        if self._src_fingerprint is not None and after_fingerprint != self._src_fingerprint:
            mismatch_msg = f"Source deck changed during export: {self.deck}"
            if self._primary_exc is None:
                raise RuntimeError(mismatch_msg)
            self.log(mismatch_msg)
