"""Alpha Keynote's own hidden, version-pinned OBS for DeckLink fill + key.

AK seeds an isolated OBS config tree under its own HOME, launches OBS.app via
NSWorkspace, waits for readiness, watches liveness and quits it cleanly. OBS is
never modified, never force-killed, and its `.sentinel` is never touched.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import plistlib
import queue
import secrets
import socket
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from websockets.sync.client import connect

from .obs_websocket import ObsRequestError, ObsWebsocket, ObsWebsocketError

log = logging.getLogger(__name__)

PINNED_OBS = "32.2.2"
OBS_BUNDLE_ID = "com.obsproject.obs-studio"
OBS_APP = Path("/Applications/OBS.app")
DEFAULT_HOME = Path.home() / "Library/Application Support/Obed-Edom/managed-obs"
TREE_RELPATH = Path("Library/Application Support/obs-studio")
PAGE_URL = "about:blank#obed-ak"
PAGE_MARK = "#obed-ak"
DECKLINK_OUTPUT = "decklink_output"
DECKLINK_PROPS = "plugin_config/decklink-output-ui/decklinkOutputProps.json"
SAFE_MODE_LINE = "[Safe Mode] Safe mode launch selected"
RATES: dict[int, tuple[str, int]] = {25: ("25 PAL", 50), 30: ("30", 60)}
KEYERS = ("external", "off")
_CANVAS_UUID = "6c69626f-6273-4c00-9d88-c5136d61696e"

WARNINGS: dict[str, tuple[str, str, str | None]] = {
    "obsMissing": ("block", f"Output engine not installed. Install OBS {PINNED_OBS} into Applications, then press Check again.", "check"),
    "obsVersion": ("block", "Output engine is OBS {found}; Alpha Keynote needs OBS " + PINNED_OBS + ". Install " + PINNED_OBS + ", then press Check again.", "check"),
    "obsUncleanExit": ("warn", "OBS closed unexpectedly last time. It has been restarted; check the output before going live.", None),
    "obsWaiting": ("block", "OBS is waiting for an answer or a permission. Press Show OBS, answer it, then press Check again.", "show"),
    "obsSafeMode": ("block", "OBS started in Safe Mode, so Alpha Keynote cannot watch it. Press Restart output engine and choose Normal Mode when OBS asks.", "restart"),
    "obsExited": ("block", "OBS stopped unexpectedly — nothing is going to the keyer. Press Restart output engine. OBS may then ask a question (see Show OBS).", "restart"),
    "obsPageLost": ("block", "OBS lost the Alpha Keynote page — nothing is going to the keyer. Press Restart output engine.", "restart"),
    "noDevice": ("warn", "No output device set for {rate} fps — the keyer receives nothing. With the UltraStudio connected, press Set up output device (one time).", "setupDevice"),
    "deviceInactive": ("block", "Alpha Keynote cannot open the UltraStudio. If ProPresenter is running, remove its SDI screen in Screen Configuration or quit ProPresenter; otherwise check the Thunderbolt cable and Desktop Video. Then press Release output and Take output again.", "quit"),
    "stuck": ("block", "OBS is not responding to Quit. Press Show OBS and quit it from the OBS menu, then press Check again.", "show"),
    "ownedElsewhere": ("block", "The output engine is being used by another dashboard window (pid {pid}). Close that dashboard first.", "check"),
    "engineError": ("block", "The output engine hit an internal error. Press Restart output engine.", "restart"),
}


class ManagedObsError(RuntimeError):
    """The managed OBS could not be launched or controlled."""


def last_version(version: str) -> int:
    major, minor, patch = (int(part) for part in version.split("."))
    return (major << 24) | (minor << 16) | patch


def rate_info(rate: int) -> dict[str, Any]:
    canvas, source = RATES[rate]
    return {"output": rate, "canvas": canvas, "source": source}


@dataclass(frozen=True)
class TreeConfig:
    rate: int
    keyer: str
    ws_port: int
    ws_password: str
    device: dict[str, Any] | None = None
    record_dir: Path | None = None
    version: str = PINNED_OBS


def _ini(sections: list[tuple[str, list[tuple[str, Any]]]]) -> bytes:
    blocks = ["[" + name + "]\n" + "".join(f"{key}={value}\n" for key, value in items) for name, items in sections]
    return "\n".join(blocks).encode()


def _scene_collection(cfg: TreeConfig) -> dict[str, Any]:
    prev_ver = last_version(cfg.version)
    source_uuid, scene_uuid = str(uuid.uuid4()), str(uuid.uuid4())
    common = {"mixers": 0, "sync": 0, "flags": 0, "volume": 1.0, "balance": 0.5, "enabled": True, "muted": False,
              "push-to-mute": False, "push-to-mute-delay": 0, "push-to-talk": False, "push-to-talk-delay": 0,
              "deinterlace_mode": 0, "deinterlace_field_order": 0, "monitoring_type": 0, "private_settings": {}}
    browser = {"prev_ver": prev_ver, "name": "Program", "uuid": source_uuid, "id": "browser_source", "versioned_id": "browser_source",
               "settings": {"url": PAGE_URL, "width": 1920, "height": 1080, "fps": RATES[cfg.rate][1], "fps_custom": True,
                            "shutdown": False, "reroute_audio": False},
               "hotkeys": {}, **common}
    item = {"name": "Program", "source_uuid": source_uuid, "visible": True, "locked": True, "rot": 0.0,
            "scale_ref": {"x": 1920.0, "y": 1080.0}, "align": 5, "bounds_type": 2, "bounds_align": 0, "bounds_crop": False,
            "crop_left": 0, "crop_top": 0, "crop_right": 0, "crop_bottom": 0, "id": 1, "group_item_backup": False,
            "pos": {"x": 0.0, "y": 0.0}, "scale": {"x": 1.0, "y": 1.0}, "bounds": {"x": 1920.0, "y": 1080.0},
            "scale_filter": "disable", "blend_method": "default", "blend_type": "normal",
            "show_transition": {"duration": 300}, "hide_transition": {"duration": 300}, "private_settings": {}}
    scene = {"prev_ver": prev_ver, "name": "AK", "uuid": scene_uuid, "id": "scene", "versioned_id": "scene",
             "settings": {"id_counter": 1, "custom_size": False, "items": [item]}, "hotkeys": {},
             "canvas_uuid": _CANVAS_UUID, **common}
    return {"name": "AK", "sources": [browser, scene], "groups": [], "scene_order": [{"name": "AK"}],
            "current_scene": "AK", "current_program_scene": "AK", "canvases": [], "current_transition": "Cut",
            "transition_duration": 300, "transitions": [],
            "quick_transitions": [{"name": "Cut", "duration": 300, "hotkeys": [], "id": 1, "fade_to_black": False}],
            "saved_projectors": [], "preview_locked": True, "scaling_enabled": False, "scaling_level": 0,
            "scaling_off_x": 0.0, "scaling_off_y": 0.0, "modules": {}, "resolution": {"x": 1920, "y": 1080}, "version": 2}


def _decklink_props(cfg: TreeConfig) -> dict[str, Any] | None:
    device = cfg.device or {}
    mode_id = (device.get("modeIds") or {}).get(str(cfg.rate))
    if not device.get("deviceHash") or mode_id is None:
        return None
    return {"device_hash": device["deviceHash"], "device_name": device.get("deviceName") or "", "mode_id": mode_id,
            "keyer": 1 if cfg.keyer == "external" else 0, "auto_start": True, "pixel_format": device.get("pixelFormat")}


def render_tree(cfg: TreeConfig) -> dict[str, bytes]:
    """Every file AK owns in the OBS tree, keyed by path relative to the tree."""
    if cfg.rate not in RATES:
        raise ValueError(f"Unsupported output rate {cfg.rate!r}.")
    if cfg.keyer not in KEYERS:
        raise ValueError(f"Unsupported keyer {cfg.keyer!r}.")
    profile: list[tuple[str, list[tuple[str, Any]]]] = [
        ("General", [("Name", "AK")]),
        ("Video", [("BaseCX", 1920), ("BaseCY", 1080), ("OutputCX", 1920), ("OutputCY", 1080), ("FPSType", 0),
                   ("FPSCommon", RATES[cfg.rate][0]), ("ColorFormat", "NV12"), ("ColorSpace", "709"), ("ColorRange", "Partial")]),
        ("Output", [("Mode", "Simple")]),
    ]
    if cfg.record_dir is not None:
        profile.append(("SimpleOutput", [("FilePath", cfg.record_dir), ("RecFilePath", cfg.record_dir), ("RecFormat2", "hybrid_mov"),
                                         ("RecQuality", "Lossless"), ("RecRB", "false")]))
    profile.append(("Audio", [("SampleRate", 48000), ("ChannelSetup", "Stereo")]))
    files = {
        "global.ini": _ini([("General", [("LastVersion", last_version(cfg.version)), ("MacOSPermissionsDialogLastShown", 1)])]),
        "user.ini": _ini([
            ("General", [("Pre19Defaults", "false"), ("Pre21Defaults", "false"), ("Pre23Defaults", "false"),
                         ("Pre24.1Defaults", "false"), ("FirstRun", "true")]),
            ("Basic", [("Profile", "AK"), ("ProfileDir", "AK"), ("SceneCollection", "AK"), ("SceneCollectionFile", "AK.json"),
                       ("ConfigOnNewProfile", "false")]),
        ]),
        "basic/profiles/AK/basic.ini": _ini(profile),
        "basic/scenes/AK.json": json.dumps(_scene_collection(cfg), indent=1).encode(),
        "plugin_config/obs-websocket/config.json": json.dumps(
            {"first_load": False, "server_enabled": True, "server_port": cfg.ws_port, "alerts_enabled": False,
             "auth_required": True, "server_password": cfg.ws_password}, indent=1).encode(),
    }
    props = _decklink_props(cfg)
    if props is not None:
        files[DECKLINK_PROPS] = json.dumps(props, indent=1).encode()
    return files


def write_tree(tree: Path, files: dict[str, bytes]) -> None:
    for relpath, data in files.items():
        path = tree / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Launcher(Protocol):
    def launch(self, app: Path, args: list[str], env: dict[str, str], *, hidden: bool) -> tuple[int, float]: ...
    def alive(self, pid: int, launch_date: float | None) -> bool: ...
    def terminate(self, pid: int, launch_date: float | None) -> bool: ...
    def show(self, pid: int, launch_date: float | None) -> bool: ...


class AppKitLauncher:
    """NSWorkspace launch and NSRunningApplication control, by pid + launch date only."""

    _LAUNCH_TIMEOUT_S = 15.0

    def launch(self, app: Path, args: list[str], env: dict[str, str], *, hidden: bool) -> tuple[int, float]:
        import AppKit
        import Foundation

        config = AppKit.NSWorkspaceOpenConfiguration.configuration()
        config.setArguments_(args)
        config.setEnvironment_(env)
        config.setCreatesNewApplicationInstance_(True)
        config.setHides_(hidden)
        config.setActivates_(not hidden)
        done = threading.Event()
        result: dict[str, Any] = {}

        def handler(running: Any, error: Any) -> None:
            result["app"], result["error"] = running, error
            done.set()

        url = Foundation.NSURL.fileURLWithPath_(str(app))
        AppKit.NSWorkspace.sharedWorkspace().openApplicationAtURL_configuration_completionHandler_(url, config, handler)
        deadline = time.monotonic() + self._LAUNCH_TIMEOUT_S
        while not done.is_set() and time.monotonic() < deadline:
            Foundation.NSRunLoop.currentRunLoop().runUntilDate_(Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.1))
        if not done.is_set():
            raise ManagedObsError("OBS did not launch in time.")
        running = result.get("app")
        if running is None:
            raise ManagedObsError(f"OBS could not be launched: {result.get('error')}")
        launched = running.launchDate()
        return int(running.processIdentifier()), launched.timeIntervalSince1970() if launched is not None else time.time()

    @staticmethod
    def _running(pid: int, launch_date: float | None) -> Any:
        import AppKit

        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None
        except PermissionError:
            pass
        app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None or app.isTerminated() or app.bundleIdentifier() != OBS_BUNDLE_ID:
            return None
        launched = app.launchDate()
        if launch_date is not None and launched is not None and abs(launched.timeIntervalSince1970() - launch_date) > 1.0:
            return None
        return app

    def alive(self, pid: int, launch_date: float | None) -> bool:
        return self._running(pid, launch_date) is not None

    def terminate(self, pid: int, launch_date: float | None) -> bool:
        app = self._running(pid, launch_date)
        return bool(app is not None and app.terminate())

    def show(self, pid: int, launch_date: float | None) -> bool:
        import AppKit

        app = self._running(pid, launch_date)
        if app is None:
            return False
        app.unhide()
        return bool(app.activateWithOptions_(AppKit.NSApplicationActivateAllWindows))


def discover_obs(app: Path) -> dict[str, Any]:
    """`{path, version, bundleId}` from the bundle's Info.plist; `version` None when missing."""
    try:
        with (app / "Contents/Info.plist").open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return {"path": str(app), "version": None, "bundleId": None}
    return {"path": str(app), "version": info.get("CFBundleShortVersionString"), "bundleId": info.get("CFBundleIdentifier")}


_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _cdp_targets(port: int, timeout: float = 1.0) -> list[dict[str, Any]]:
    with _HTTP.open(f"http://127.0.0.1:{port}/json/list", timeout=timeout) as response:
        targets = json.loads(response.read())
    if not isinstance(targets, list):
        raise ManagedObsError("CDP /json/list did not return a list.")
    return [item for item in targets if isinstance(item, dict)]


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=1))
    os.replace(tmp, path)


class ManagedObs:
    """One per dashboard process. Public actions return at once; the work runs on
    a single engine thread in submission order. `state()` is the dashboard JSON."""

    def __init__(self, home: Path = DEFAULT_HOME, *, launcher: Launcher | None = None, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, obs_app: Path = OBS_APP, pick_port: Callable[[], int] = free_port,
                 record_dir: Path | None = None, ready_timeout_s: float = 20.0, poll_s: float = 0.2, liveness_s: float = 2.0,
                 quit_timeout_s: float = 10.0, device_grace_s: float = 5.0) -> None:
        self.home = Path(home)
        self.tree = self.home / TREE_RELPATH
        self._launcher = launcher if launcher is not None else AppKitLauncher()
        self._clock, self._sleep, self._obs_app, self._pick_port = clock, sleep, Path(obs_app), pick_port
        self._record_dir = record_dir
        self._ready_timeout_s, self._poll_s, self._liveness_s = ready_timeout_s, poll_s, liveness_s
        self._quit_timeout_s, self._device_grace_s = quit_timeout_s, device_grace_s
        self._lock = threading.RLock()
        self._jobs: "queue.Queue[Callable[[], None] | None]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock_file: Any = None
        self._orphans_checked = False
        self._obs: dict[str, Any] | None = None
        self._state = "stopped"
        self._reason: str | None = None
        self._rate, self._keyer = 25, "external"
        self._launched: tuple[int, str] | None = None
        self._setup_rate: int | None = None
        self._warnings: dict[str, dict[str, Any]] = {}
        self._pid: int | None = None
        self._launch_date: float | None = None
        self._launch_clock: float | None = None
        self._cdp_port: int | None = None
        self._ws_port: int | None = None
        self._ws_password: str | None = None
        self._target_id: str | None = None
        self._ready_at: float | None = None
        self._inactive_reads = 0

    @property
    def cdp_endpoint(self) -> str | None:
        with self._lock:
            return f"http://127.0.0.1:{self._cdp_port}" if self._cdp_port and self._pid else None

    @property
    def target_id(self) -> str | None:
        with self._lock:
            return self._target_id

    def device(self) -> dict[str, Any] | None:
        return _read_json(self.home / "ak-device.json")

    def state(self) -> dict[str, Any]:
        with self._lock:
            if self._obs is None:
                self._obs = discover_obs(self._obs_app)
            obs = self._obs
            device = self.device()
            mode_set = bool(device and device.get("deviceHash") and str(self._rate) in (device.get("modeIds") or {}))
            warnings = [dict(entry) for entry in self._warnings.values()]
            discovery = self._discovery_warning(obs)
            if discovery is not None and all(entry["id"] != discovery["id"] for entry in warnings):
                warnings.insert(0, discovery)
            if not mode_set:
                warnings.append(self._warning("noDevice", rate=self._rate))
            state = "unavailable" if discovery is not None and self._pid is None else self._state
            payload: dict[str, Any] = {
                "state": state,
                "obs": {"path": obs["path"], "version": obs["version"], "pinned": PINNED_OBS},
                "rate": rate_info(self._rate),
                "device": {"name": (device or {}).get("deviceName"), "set": mode_set},
                "keyer": self._keyer,
                "setup": self._setup_rate,
                "warnings": warnings,
            }
            reason = discovery["id"] if state == "unavailable" else self._reason
            if reason:
                payload["reason"] = reason
            return payload

    def configure(self, rate: int, keyer: str) -> None:
        """Record the preferred rate and keyer shown by `state()`; never starts or locks."""
        self._validate(rate, keyer)
        with self._lock:
            self._rate, self._keyer = rate, keyer

    def has_orphan(self) -> bool:
        """True when `ak-engine.json` names a live OBS (matching launch date) that is not ours."""
        record = _read_json(self._record_path()) or {}
        pid, launch_date = record.get("pid"), record.get("launchDate")
        with self._lock:
            ours = self._pid
        return isinstance(pid, int) and pid != ours and self._launcher.alive(pid, launch_date)

    def ensure_started(self, rate: int, keyer: str) -> None:
        self._validate(rate, keyer)
        self._submit(lambda: self._ensure_started(rate, keyer))

    def restart(self, rate: int, keyer: str) -> None:
        self._validate(rate, keyer)
        self._submit(lambda: self._restart(rate, keyer))

    def quit(self) -> None:
        self._submit(lambda: self._acquire() and self._quit())

    def check(self) -> None:
        self._submit(self._check)

    def show(self) -> None:
        self._submit(self._show)

    def reset_page(self) -> None:
        self._submit(self._reset_page)

    def setup_device_begin(self, rate: int) -> None:
        self._validate(rate, self._keyer)
        self._submit(lambda: self._setup_begin(rate))

    def setup_device_done(self) -> None:
        self._submit(self._setup_done)

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Block until every action submitted so far has run (for shutdown and tests)."""
        done = threading.Event()
        self._submit(done.set)
        return done.wait(timeout)

    def close(self) -> None:
        """Stop the engine thread and release the lock; OBS itself is left as it is."""
        with self._lock:
            thread, self._thread = self._thread, None
        if thread is not None:
            self._jobs.put(None)
            thread.join(timeout=self._quit_timeout_s + 5)
        with self._lock:
            if self._lock_file is not None:
                self._lock_file.close()
                self._lock_file = None

    @staticmethod
    def _validate(rate: int, keyer: str) -> None:
        if rate not in RATES:
            raise ValueError(f"Unsupported output rate {rate!r}; supported: {sorted(RATES)}.")
        if keyer not in KEYERS:
            raise ValueError(f"Unsupported keyer {keyer!r}; supported: {list(KEYERS)}.")

    def _submit(self, job: Callable[[], None]) -> None:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="managed-obs", daemon=True)
                self._thread.start()
        self._jobs.put(job)

    def _run(self) -> None:
        while True:
            try:
                job = self._jobs.get(timeout=self._liveness_s)
            except queue.Empty:
                job = self._liveness
            if job is None:
                return
            try:
                job()
            except Exception as exc:
                log.error("managed OBS engine action failed: %s", type(exc).__name__)
                with self._lock:
                    self._set("blocked", "engineError")
                    self._warnings["engineError"] = self._warning("engineError")

    @staticmethod
    def _warning(warning_id: str, **fields: Any) -> dict[str, Any]:
        severity, text, action = WARNINGS[warning_id]
        entry: dict[str, Any] = {"id": warning_id, "severity": severity, "text": text.format(**fields) if fields else text}
        if action:
            entry["action"] = action
        return entry

    def _discovery_warning(self, obs: dict[str, Any]) -> dict[str, Any] | None:
        if obs["version"] is None or obs["bundleId"] != OBS_BUNDLE_ID:
            return self._warning("obsMissing")
        if obs["version"] != PINNED_OBS:
            return self._warning("obsVersion", found=obs["version"])
        return None

    def _set(self, state: str, reason: str | None = None) -> None:
        self._state, self._reason = state, reason

    def _record_path(self) -> Path:
        return self.home / "ak-engine.json"

    def _write_record(self, **changes: Any) -> None:
        record = _read_json(self._record_path()) or {}
        record.update(changes)
        _write_json(self._record_path(), record)

    def _acquire(self) -> bool:
        """Take the process-lifetime engine lock and quit any orphan, once."""
        if self._lock_file is None:
            self.home.mkdir(parents=True, exist_ok=True)
            handle = (self.home / "ak-engine.lock").open("a+")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.seek(0)
                holder = handle.read().strip() or "unknown"
                handle.close()
                with self._lock:
                    self._set("blocked", "ownedElsewhere")
                    self._warnings = {"ownedElsewhere": self._warning("ownedElsewhere", pid=holder)}
                return False
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()))
            handle.flush()
            with self._lock:
                self._lock_file = handle
                self._warnings.pop("ownedElsewhere", None)
                if self._reason == "ownedElsewhere":
                    self._set("stopped")
        if not self._orphans_checked:
            self._orphans_checked = True
            record = _read_json(self._record_path()) or {}
            pid, launch_date = record.get("pid"), record.get("launchDate")
            if isinstance(pid, int) and self._launcher.alive(pid, launch_date):
                log.info("quitting orphaned managed OBS pid %s", pid)
                with self._lock:
                    self._pid, self._launch_date = pid, launch_date
                return self._quit()
        return True

    def _discover(self) -> bool:
        obs = discover_obs(self._obs_app)
        with self._lock:
            self._obs = obs
            warning = self._discovery_warning(obs)
            if warning is not None and self._pid is None:
                self._set("unavailable", warning["id"])
                return False
            if self._state == "unavailable":
                self._set("stopped")
        return warning is None

    def _alive(self) -> bool:
        return self._pid is not None and self._launcher.alive(self._pid, self._launch_date)

    def _ensure_started(self, rate: int, keyer: str) -> None:
        if not self._acquire():
            return
        with self._lock:
            running = self._pid is not None and self._state in ("starting", "ready", "blocked")
            same = (rate, keyer) == self._launched and self._setup_rate is None
        if running and self._alive():
            if not same:
                self._restart(rate, keyer)
            return
        if self._state == "stuck":
            return
        self._launch(rate, keyer, hidden=True)

    def _restart(self, rate: int, keyer: str) -> None:
        if not self._acquire():
            return
        if self._quit():
            self._launch(rate, keyer, hidden=True)

    def _launch(self, rate: int, keyer: str, *, hidden: bool) -> None:
        if not self._discover():
            return
        previous = _read_json(self._record_path()) or {}
        cdp_port, ws_port, password = self._pick_port(), self._pick_port(), secrets.token_urlsafe(32)
        with self._lock:
            self._warnings = {}
            if previous.get("pid") and previous.get("cleanExit") is False:
                self._warnings["obsUncleanExit"] = self._warning("obsUncleanExit")
            self._rate, self._keyer = rate, keyer
            self._launched = (rate, keyer)
            self._setup_rate = None if hidden else rate
            self._pid = self._launch_date = self._target_id = self._ready_at = None
            self._cdp_port, self._ws_port, self._ws_password = cdp_port, ws_port, password
            self._inactive_reads = 0
            self._set("starting")
        _write_json(self._record_path(), {"pid": None, "launchDate": None, "cdpPort": cdp_port, "wsPort": ws_port, "cleanExit": False})
        self._seed(TreeConfig(rate=rate, keyer=keyer, ws_port=ws_port, ws_password=password, device=self.device(), record_dir=self._record_dir))
        args = ["--multi", "--disable-updater", "--disable-missing-files-check"]
        if hidden:
            args.append("--minimize-to-tray")
        args.append(f"--remote-debugging-port={cdp_port}")
        env = {"CFFIXED_USER_HOME": str(self.home), "HOME": str(self.home)}
        launched_at = time.time()
        pid, launch_date = self._launcher.launch(self._obs_app, args, env, hidden=hidden)
        with self._lock:
            self._pid, self._launch_date, self._launch_clock = pid, launch_date, self._clock()
        self._write_record(pid=pid, launchDate=launch_date)
        log.info("launched managed OBS pid %s (cdp %s, websocket %s, %s)", pid, cdp_port, ws_port, "hidden" if hidden else "visible")
        self._await_ready(min(launch_date, launched_at))

    def _seed(self, cfg: TreeConfig) -> None:
        if self._alive():
            raise ManagedObsError("Refusing to seed the OBS tree while the managed OBS is running.")
        files = render_tree(cfg)
        write_tree(self.tree, files)
        if DECKLINK_PROPS not in files:
            (self.tree / DECKLINK_PROPS).unlink(missing_ok=True)

    def _safe_mode_logged(self, since: float) -> bool:
        try:
            logs = [path for path in (self.tree / "logs").glob("*.txt") if path.stat().st_mtime >= since - 1.0]
        except OSError:
            return False
        if not logs:
            return False
        newest = max(logs, key=lambda path: path.stat().st_mtime)
        try:
            return SAFE_MODE_LINE in newest.read_text(errors="replace")
        except OSError:
            return False

    def _page_target(self) -> str | None:
        try:
            targets = _cdp_targets(self._cdp_port)
        except Exception:
            return None
        pages = [item for item in targets if item.get("type") == "page" and PAGE_MARK in str(item.get("url") or "")]
        return str(pages[0].get("id")) if len(pages) == 1 and pages[0].get("id") else None

    def _obs_version(self) -> str | None:
        try:
            with ObsWebsocket(self._ws_port, self._ws_password, timeout=2.0) as ws:
                return str(ws.request("GetVersion").get("obsVersion"))
        except ObsWebsocketError:
            return None

    def _await_ready(self, since: float) -> None:
        deadline = self._clock() + self._ready_timeout_s
        target_id: str | None = None
        version: str | None = None
        while True:
            if not self._alive():
                self._on_exit()
                return
            if self._safe_mode_logged(since):
                with self._lock:
                    self._set("blocked", "safeMode")
                    self._warnings["obsSafeMode"] = self._warning("obsSafeMode")
                return
            target_id = target_id or self._page_target()
            version = version or self._obs_version()
            if version is not None and version != PINNED_OBS:
                log.warning("managed OBS reports version %s, pinned %s", version, PINNED_OBS)
                with self._lock:
                    self._set("blocked", "obsVersion")
                    self._warnings["obsVersion"] = self._warning("obsVersion", found=version)
                return
            if target_id and version:
                log.info("managed OBS ready: OBS %s, page target %s", version, target_id)
                with self._lock:
                    self._target_id, self._ready_at = target_id, self._clock()
                    for warning_id in ("obsWaiting", "obsSafeMode", "obsPageLost", "deviceInactive", "engineError"):
                        self._warnings.pop(warning_id, None)
                    self._set("blocked", "deviceSetup") if self._setup_rate is not None else self._set("ready")
                return
            if self._clock() >= deadline:
                with self._lock:
                    if target_id and not version:
                        self._set("blocked", "safeMode")
                        self._warnings["obsSafeMode"] = self._warning("obsSafeMode")
                    else:
                        self._set("blocked", "timeout")
                        self._warnings["obsWaiting"] = self._warning("obsWaiting")
                return
            self._sleep(self._poll_s)

    def _on_exit(self) -> None:
        with self._lock:
            setup = self._setup_rate is not None
            self._pid = self._launch_date = self._target_id = self._ready_at = None
            if setup:
                self._set("blocked", "deviceSetup")
            else:
                self._set("blocked", "exited")
                self._warnings["obsExited"] = self._warning("obsExited")
        if setup:
            self._write_record(cleanExit=True)
        log.warning("managed OBS exited without AK asking" if not setup else "managed OBS closed during device setup")

    def _liveness(self) -> None:
        with self._lock:
            if self._pid is None or self._state not in ("ready", "blocked"):
                return
            target_id, ready_at, reason = self._target_id, self._ready_at, self._reason
        if not self._alive():
            self._on_exit()
            return
        if reason in ("timeout", "safeMode", "obsVersion", "engineError"):
            return
        if target_id is not None:
            try:
                ids = {str(item.get("id")) for item in _cdp_targets(self._cdp_port)}
            except Exception:
                ids = None
            if ids is not None and target_id not in ids:
                with self._lock:
                    self._set("blocked", "pageLost")
                    self._warnings["obsPageLost"] = self._warning("obsPageLost")
                return
        if ready_at is not None and self._setup_rate is None and self._clock() - ready_at >= self._device_grace_s:
            self._check_device()

    def _check_device(self) -> None:
        """W11 after two consecutive inactive reads; one active read clears it. A connection
        error or timeout is an unknown read and changes nothing."""
        device = self.device() or {}
        rate = self._launched[0] if self._launched else None
        if not device.get("deviceHash") or str(rate) not in (device.get("modeIds") or {}):
            return
        try:
            with ObsWebsocket(self._ws_port, self._ws_password, timeout=2.0) as ws:
                active = bool(ws.request("GetOutputStatus", {"outputName": DECKLINK_OUTPUT}).get("outputActive"))
        except ObsRequestError as exc:
            log.warning("GetOutputStatus(%s) refused: code %s", DECKLINK_OUTPUT, exc.code)
            active = False
        except ObsWebsocketError as exc:
            log.warning("GetOutputStatus(%s) failed: %s", DECKLINK_OUTPUT, type(exc).__name__)
            return
        with self._lock:
            if active:
                self._inactive_reads = 0
                self._warnings.pop("deviceInactive", None)
                if self._reason == "deviceInactive":
                    self._set("ready")
                return
            self._inactive_reads += 1
            if self._inactive_reads >= 2:
                self._set("blocked", "deviceInactive")
                self._warnings["deviceInactive"] = self._warning("deviceInactive")

    def _quit(self) -> bool:
        """Quit our OBS cleanly; True once it is gone. Never force-kills."""
        with self._lock:
            pid, launch_date = self._pid, self._launch_date
        if pid is None or not self._launcher.alive(pid, launch_date):
            with self._lock:
                self._pid = self._launch_date = self._target_id = self._ready_at = None
                self._warnings = {}
                if self._state != "unavailable":
                    self._set("stopped")
            return True
        with self._lock:
            self._set("quitting")
        self._launcher.terminate(pid, launch_date)
        deadline = self._clock() + self._quit_timeout_s
        while self._launcher.alive(pid, launch_date):
            if self._clock() >= deadline:
                log.warning("managed OBS pid %s did not quit within %ss", pid, self._quit_timeout_s)
                with self._lock:
                    self._set("stuck", "stuck")
                    self._warnings["stuck"] = self._warning("stuck")
                return False
            self._sleep(self._poll_s)
        self._write_record(cleanExit=True)
        with self._lock:
            self._pid = self._launch_date = self._target_id = self._ready_at = None
            self._warnings = {}
            self._set("stopped")
        log.info("managed OBS pid %s quit cleanly", pid)
        return True

    def _check(self) -> None:
        if not self._acquire():
            return
        self._discover()
        with self._lock:
            state, reason = self._state, self._reason
        if state == "stuck":
            if not self._alive():
                self._write_record(cleanExit=True)
                with self._lock:
                    self._pid = self._launch_date = self._target_id = self._ready_at = None
                    self._warnings.pop("stuck", None)
                    self._set("stopped")
            return
        if self._pid is None:
            return
        if state == "blocked" and reason in ("timeout", "safeMode", "pageLost", "engineError"):
            with self._lock:
                self._set("starting")
                for warning_id in ("obsWaiting", "obsSafeMode", "obsPageLost", "engineError"):
                    self._warnings.pop(warning_id, None)
            self._await_ready(self._launch_date or 0.0)
            return
        self._liveness()

    def _show(self) -> None:
        with self._lock:
            pid, launch_date = self._pid, self._launch_date
        if pid is not None:
            self._launcher.show(pid, launch_date)

    def _reset_page(self) -> None:
        with self._lock:
            target_id, port = self._target_id, self._cdp_port
        if target_id is None or port is None or self._pid is None:
            return
        try:
            target = next((item for item in _cdp_targets(port) if str(item.get("id")) == target_id), None)
            ws_url = str((target or {}).get("webSocketDebuggerUrl") or "")
            if not ws_url.startswith(f"ws://127.0.0.1:{port}/"):
                raise ManagedObsError("CDP target is missing or not on the managed OBS loopback port.")
            with connect(ws_url, open_timeout=3) as ws:
                ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": PAGE_URL}}))
                deadline = time.monotonic() + 3.0
                while json.loads(ws.recv(timeout=max(0.01, deadline - time.monotonic()))).get("id") != 1:
                    pass
        except Exception as exc:
            log.warning("could not reset the managed OBS page: %s", type(exc).__name__)

    def _setup_begin(self, rate: int) -> None:
        if not self._acquire():
            return
        if self._quit():
            self._launch(rate, self._keyer, hidden=False)

    def _setup_done(self) -> None:
        if not self._acquire():
            return
        with self._lock:
            rate = self._setup_rate
        if rate is None:
            return
        if not self._quit():
            return
        with self._lock:
            self._setup_rate = None
            self._set("stopped")
        props = _read_json(self.tree / DECKLINK_PROPS) or {}
        device_hash, mode_id = props.get("device_hash"), props.get("mode_id")
        if not device_hash or mode_id is None:
            log.warning("device setup finished without a DeckLink device and mode in %s", DECKLINK_PROPS)
            return
        record = self.device() or {}
        mode_ids = dict(record.get("modeIds") or {}) if record.get("deviceHash") == device_hash else {}
        mode_ids[str(rate)] = mode_id
        _write_json(self.home / "ak-device.json", {"deviceHash": device_hash, "deviceName": props.get("device_name"),
                                                   "modeIds": mode_ids, "pixelFormat": props.get("pixel_format")})
        log.info("recorded output device %s for %s fps", props.get("device_name"), rate)
