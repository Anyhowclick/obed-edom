"""Alpha Keynote's own hidden, version-pinned OBS for DeckLink fill + key.

AK seeds an isolated OBS config tree under its own HOME, launches OBS.app via
NSWorkspace, waits for readiness, watches liveness and quits it cleanly. OBS is
never modified, never force-killed, and its `.sentinel` is never touched.
"""

from __future__ import annotations

import base64
import binascii
import fcntl
import json
import logging
import os
import plistlib
import queue
import re
import secrets
import socket
import subprocess
import threading
import time
import urllib.request
import uuid
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Protocol
from urllib.parse import urlsplit

from websockets.sync.client import connect

from .obs_websocket import ObsRequestError, ObsWebsocket, ObsWebsocketError, ObsWebsocketTimeout
from .placement_probe import ClassifierInput, ProbeSpec

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
    "obsUnreachable": ("block", "Alpha Keynote cannot reach OBS. Press Restart output engine.", "restart"),
    "obsIdentityUnknown": ("block", "Alpha Keynote cannot confirm which OBS is its own, so it will not start or stop OBS. Quit any OBS you opened yourself, then press Check again.", "check"),
    "noDevice": ("warn", "No output device set for {rate} fps — the keyer receives nothing. With the UltraStudio connected, press Set up output device (one time).", "setupDevice"),
    "deviceInactive": ("block", "Alpha Keynote cannot open the UltraStudio. If ProPresenter is running, remove its SDI screen in Screen Configuration or quit ProPresenter; otherwise check the Thunderbolt cable and Desktop Video. Then press Release output and Take output again.", "quit"),
    "stuck": ("block", "OBS is not responding to Quit. Press Show OBS and quit it from the OBS menu, then press Check again.", "show"),
    "ownedElsewhere": ("block", "The output engine is being used by another dashboard window (pid {pid}). Close that dashboard first.", "check"),
    "engineError": ("block", "The output engine hit an internal error. Press Restart output engine.", "restart"),
}


class ManagedObsError(RuntimeError):
    """The managed OBS could not be launched or controlled."""


class _CalibrationRefused(ManagedObsError):
    pass


class _CalibrationCancelled(ManagedObsError):
    pass


class _CalibrationTimeout(ManagedObsError):
    pass


class _CalibrationIsolationViolation(ManagedObsError):
    pass


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


@dataclass(frozen=True)
class ObsProcess:
    """One running OBS app as enumerated; `handle` is the object terminate/show act on."""

    pid: int
    launch_date: float | None
    handle: Any = field(default=None, compare=False, repr=False)


class Launcher(Protocol):
    def launch(self, app: Path, args: list[str], env: dict[str, str], *, hidden: bool,
               on_launched: Callable[[int, float | None], None]) -> tuple[int, float | None]: ...
    def processes(self) -> list[ObsProcess]: ...
    def env_marker(self, pid: int, home: Path) -> bool | None: ...
    def terminate(self, process: ObsProcess) -> bool: ...
    def show(self, process: ObsProcess) -> bool: ...


def _home_marker(command: str, home: Path) -> bool:
    return re.search("(?:^| )CFFIXED_USER_HOME=" + re.escape(str(home)) + r"(?=$| [A-Za-z_][A-Za-z0-9_]*=)", command.strip()) is not None


def _epoch(date: Any) -> float | None:
    return date.timeIntervalSince1970() if date is not None else None


class AppKitLauncher:
    """NSWorkspace launch; running OBS apps by bundle id; the CFFIXED_USER_HOME marker via `ps -E`.
    terminate/show act on the enumerated NSRunningApplication itself, re-checked just before acting."""

    _LAUNCH_TIMEOUT_S = 15.0

    def launch(self, app: Path, args: list[str], env: dict[str, str], *, hidden: bool,
               on_launched: Callable[[int, float | None], None]) -> tuple[int, float | None]:
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
            try:
                if running is not None:
                    result["launched"] = (int(running.processIdentifier()), _epoch(running.launchDate()))
                    on_launched(*result["launched"])
                result["error"] = error
            except Exception as exc:
                result["error"] = exc
            finally:
                done.set()

        url = Foundation.NSURL.fileURLWithPath_(str(app))
        AppKit.NSWorkspace.sharedWorkspace().openApplicationAtURL_configuration_completionHandler_(url, config, handler)
        deadline = time.monotonic() + self._LAUNCH_TIMEOUT_S
        while not done.is_set() and time.monotonic() < deadline:
            Foundation.NSRunLoop.currentRunLoop().runUntilDate_(Foundation.NSDate.dateWithTimeIntervalSinceNow_(0.1))
        if not done.is_set():
            raise ManagedObsError("OBS did not launch in time.")
        if "launched" not in result:
            raise ManagedObsError(f"OBS could not be launched: {result.get('error')}")
        return result["launched"]

    def processes(self) -> list[ObsProcess]:
        import AppKit

        return [ObsProcess(int(app.processIdentifier()), _epoch(app.launchDate()), app)
                for app in AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(OBS_BUNDLE_ID)
                if not app.isTerminated()]

    def env_marker(self, pid: int, home: Path) -> bool | None:
        try:
            result = subprocess.run(["ps", "-Eww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return False if not result.stdout.strip() else None
        return _home_marker(result.stdout, home)

    @staticmethod
    def _verified(process: ObsProcess) -> Any:
        app = process.handle
        if app is None or app.isTerminated() or int(app.processIdentifier()) != process.pid or app.bundleIdentifier() != OBS_BUNDLE_ID:
            return None
        launched = _epoch(app.launchDate())
        if (launched is None) != (process.launch_date is None):
            return None
        if launched is not None and abs(launched - process.launch_date) > 1.0:
            return None
        return app

    def terminate(self, process: ObsProcess) -> bool:
        app = self._verified(process)
        return bool(app is not None and app.terminate())

    def show(self, process: ObsProcess) -> bool:
        import AppKit

        app = self._verified(process)
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


_FAILURE_LIMIT = 3
_RECHECKABLE = ("timeout", "safeMode", "pageLost", "obsUnreachable", "engineError", "identityUnknown")
_TRANSIENT_WARNINGS = ("obsWaiting", "obsSafeMode", "obsPageLost", "obsUnreachable", "obsIdentityUnknown", "deviceInactive", "engineError")
OUTPUT_MODES = ("screen", "keyer")


CALIBRATION_SCENE = "AK-Calibrate"
PROBE_SOURCE = "AK-Probe"
PROGRAM_SCENE = "AK"
OBS_CANVAS = "Main"
PREVIEW_OUTPUT = "decklink_preview_output"
CALIBRATION_DEADLINE_S = 15.0
CALIBRATION_CLEANUP_S = 5.0
CALIBRATION_MAX_MESSAGE_BYTES = 16 * 1024 * 1024
_ABSENT: dict[str, bool] = {"$absent": True}
_PREVIEW_OUTPUT_ABSENT = "No output was found with the name `decklink_preview_output`."
_INPUT_ABSENT = "No source was found by the name of `AK-Probe` within the canvas `Main`."
_SCENE_ABSENT = "No source was found by the name of `AK-Calibrate` within the canvas `Main`."


@dataclass(frozen=True)
class EngineIdentity:
    pid: int
    launch_date: float
    ready_generation: int


@dataclass(frozen=True)
class CalibrationRequest:
    spec: ProbeSpec
    url: str
    engine: EngineIdentity
    program_target_id: str
    program_context_id: str
    connection_generation: int
    placement: Literal["preview", "offcanvas"] = "preview"


@dataclass(frozen=True)
class ProgramCheck:
    ok: bool | None
    visibility_events: int
    baseline_frame_ms: float | None
    max_raf_gap_ms: float | None
    media: tuple[dict[str, object], ...]
    reason: str | None


class ProgramGuard(Protocol):
    def begin(self) -> None: ...
    def sample(self, phase: str) -> None: ...
    def finish(self) -> ProgramCheck: ...


class CalibrationIO(Protocol):
    request: CalibrationRequest
    source_uuid: str
    cdp_endpoint: str
    cancel_event: threading.Event
    deadline_s: float

    def capture_png(self, *, timeout_s: float = 2.0) -> bytes: ...
    def check_current(self) -> None: ...


@dataclass(frozen=True)
class CollectionSnapshot:
    state: dict[str, object]
    mtime_ns: int
    saved_by_obs: bool


@dataclass(frozen=True)
class PersistenceRule:
    path: str
    before: object
    after: object


@dataclass(frozen=True)
class PersistenceCheck:
    phase: str
    authoritative: bool
    ok: bool | None
    differences: tuple[str, ...]
    allowed: tuple[str, ...]


@dataclass(frozen=True)
class CalibrationResult:
    request: CalibrationRequest
    evidence: ClassifierInput | None
    program: ProgramCheck | None
    isolation_ok: bool
    cleanup_verified: bool
    restored: bool
    persistence: PersistenceCheck | None
    errors: tuple[str, ...]
    started_s: float
    finished_s: float


class CalibrationAdapter(Protocol):
    def identity(self) -> EngineIdentity | None: ...
    def start(self, request: CalibrationRequest, *, measure: Callable[[CalibrationIO], ClassifierInput],
              guard: ProgramGuard) -> Future[CalibrationResult]: ...
    def cancel(self, run_id: str, *, timeout_s: float = 5.0) -> bool: ...


def _normalise_collection(value: dict[str, Any]) -> dict[str, object]:
    state = json.loads(json.dumps(value))
    sources = state.get("sources")
    if not isinstance(sources, list):
        raise ManagedObsError("OBS scene collection has no sources list.")
    by_name: dict[str, Any] = {}
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("name"), str) or source["name"] in by_name:
            raise ManagedObsError("OBS scene collection has an invalid source name.")
        by_name[source["name"]] = source
    state["sources"] = by_name
    return state


def read_collection(path: Path, *, saved_by_obs: bool) -> CollectionSnapshot:
    try:
        stat = path.stat()
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ManagedObsError(f"Could not read OBS scene collection: {type(exc).__name__}.") from exc
    if not isinstance(value, dict):
        raise ManagedObsError("OBS scene collection is not a JSON object.")
    return CollectionSnapshot(_normalise_collection(value), stat.st_mtime_ns, saved_by_obs)


def _canonical_null_state(state: dict[str, object]) -> dict[str, object]:
    copied = json.loads(json.dumps(state))
    sources = copied.get("sources")
    if not isinstance(sources, dict):
        return copied
    uuids = {source.get("uuid"): name for name, source in sources.items()
             if isinstance(source, dict) and isinstance(source.get("uuid"), str)}

    def replace(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        return f"$source:{uuids[value]}" if isinstance(value, str) and value in uuids else value

    return replace(copied)


def _pointer_part(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _state_differences(before: Any, after: Any, path: str = "") -> list[tuple[str, object, object]]:
    if isinstance(before, dict) and isinstance(after, dict):
        differences: list[tuple[str, object, object]] = []
        for key in sorted(before.keys() | after.keys()):
            child = f"{path}/{_pointer_part(str(key))}"
            if key not in before:
                differences.append((child, _ABSENT, after[key]))
            elif key not in after:
                differences.append((child, before[key], _ABSENT))
            else:
                differences.extend(_state_differences(before[key], after[key], child))
        return differences
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return [(path, before, after)]
        differences = []
        for index, (left, right) in enumerate(zip(before, after)):
            differences.extend(_state_differences(left, right, f"{path}/{index}"))
        return differences
    return [] if before == after else [(path or "/", before, after)]


def persistence_allowlist(null_before: CollectionSnapshot, null_after: CollectionSnapshot) -> tuple[PersistenceRule, ...]:
    before = _canonical_null_state(null_before.state)
    after = _canonical_null_state(null_after.state)
    return tuple(PersistenceRule(path, left, right) for path, left, right in _state_differences(before, after))


STEP0_NULL_ALLOWLIST = (
    PersistenceRule("/modules/auto-scene-switcher", _ABSENT,
                    {"interval": 300, "non_matching_scene": "", "switch_if_not_matching": False,
                     "active": False, "switches": []}),
    PersistenceRule("/modules/output-timer", _ABSENT,
                    {"streamTimerHours": 0, "streamTimerMinutes": 0, "streamTimerSeconds": 0,
                     "recordTimerHours": 0, "recordTimerMinutes": 0, "recordTimerSeconds": 0,
                     "autoStartStreamTimer": False, "autoStartRecordTimer": False, "pauseRecordTimer": False}),
    PersistenceRule("/modules/scripts-tool", _ABSENT, []),
    PersistenceRule("/virtual-camera", _ABSENT, {"type2": 3}),
    PersistenceRule("/scaling_level", 0, -49),
    PersistenceRule("/sources/Program/hotkeys/ObsBrowser.Refresh", _ABSENT, []),
    PersistenceRule("/sources/Program/hotkeys/libobs.mute", _ABSENT, []),
    PersistenceRule("/sources/Program/hotkeys/libobs.unmute", _ABSENT, []),
    PersistenceRule("/sources/Program/hotkeys/libobs.push-to-mute", _ABSENT, []),
    PersistenceRule("/sources/Program/hotkeys/libobs.push-to-talk", _ABSENT, []),
    PersistenceRule("/sources/AK/hotkeys/OBSBasic.SelectScene", _ABSENT, []),
    PersistenceRule("/sources/AK/hotkeys/libobs.hide_scene_item.1", _ABSENT, []),
    PersistenceRule("/sources/AK/hotkeys/libobs.show_scene_item.1", _ABSENT, []),
    PersistenceRule("/sources/AK/settings/items/0/bounds_rel", _ABSENT, {"x": 3.555555582046509, "y": 2.0}),
    PersistenceRule("/sources/AK/settings/items/0/pos_rel", _ABSENT, {"x": -1.7777777910232544, "y": -1.0}),
    PersistenceRule("/sources/AK/settings/items/0/scale_rel", _ABSENT, {"x": 1.0, "y": 1.0}),
)


def _monotonic_id_counter(path: str, before: object, after: object, baseline: dict[str, object]) -> bool:
    parts = path.split("/")
    if len(parts) != 5 or parts[1] != "sources" or parts[3:] != ["settings", "id_counter"]:
        return False
    sources = baseline.get("sources")
    source = sources.get(parts[2]) if isinstance(sources, dict) else None
    return (isinstance(source, dict) and source.get("id") == "scene" and isinstance(before, int)
            and not isinstance(before, bool) and isinstance(after, int) and not isinstance(after, bool) and after >= before)


def check_persistence(before: CollectionSnapshot, after: CollectionSnapshot, *, null_allowlist: tuple[PersistenceRule, ...],
                      phase: Literal["cleanup", "quit"], last_removal_mtime_ns: int) -> PersistenceCheck:
    if phase not in ("cleanup", "quit"):
        raise ValueError(f"Unsupported persistence phase {phase!r}.")
    rules = {rule.path: rule for rule in null_allowlist}
    denied: list[str] = []
    allowed: list[str] = []
    for path, left, right in _state_differences(before.state, after.state):
        rule = rules.get(path)
        if rule is not None and left == rule.before and right == rule.after:
            allowed.append(path)
        elif _monotonic_id_counter(path, left, right, before.state):
            allowed.append(path)
        else:
            denied.append(path)
    authoritative = phase == "quit" or after.mtime_ns > last_removal_mtime_ns
    return PersistenceCheck(phase, authoritative, not denied if authoritative else None,
                            tuple(denied), tuple(allowed))


@dataclass
class _CalibrationRun:
    request: CalibrationRequest
    future: Future[CalibrationResult]
    cancel_event: threading.Event
    done_event: threading.Event
    measurement_ws: ObsWebsocket | None = None
    thread: threading.Thread | None = None
    cleanup_verified: bool = False


@dataclass
class _CalibrationSnapshot:
    studio_enabled: bool
    preview_name: str | None
    preview_uuid: str | None
    program_name: str
    program_uuid: str
    video: dict[str, Any]
    program_items: list[dict[str, Any]]


@dataclass
class _CalibrationInstall:
    scene_created: bool = False
    input_created: bool = False
    source_uuid: str | None = None
    ref_requested: bool = False
    ref_id: int | None = None
    target_id: str | None = None


class _CalibrationIO:
    def __init__(self, engine: "ManagedObs", run: _CalibrationRun, ws: ObsWebsocket,
                 snapshot: _CalibrationSnapshot, source_uuid: str, ref_id: int | None,
                 guard: ProgramGuard, deadline_s: float) -> None:
        self.request = run.request
        self.source_uuid = source_uuid
        self.cdp_endpoint = engine.cdp_endpoint or ""
        self.cancel_event = run.cancel_event
        self.deadline_s = deadline_s
        self._engine, self._run, self._ws = engine, run, ws
        self._snapshot, self._ref_id, self._guard = snapshot, ref_id, guard

    def check_current(self) -> None:
        self._engine._calibration_check_current(self._run, self.deadline_s)

    def capture_png(self, *, timeout_s: float = 2.0) -> bytes:
        self._guard.sample("before-capture")
        try:
            self._engine._calibration_verify_ownership(self._run, self.deadline_s)
            self._engine._verify_calibration_isolation(self._run, self._ws, self._snapshot, self.source_uuid, self._ref_id,
                                                       self.deadline_s)
            data = self._engine._calibration_request(
                self._run, self._ws, "GetSourceScreenshot",
                {"sourceName": PROBE_SOURCE, "imageFormat": "png", "imageWidth": self.request.spec.width,
                 "imageHeight": self.request.spec.height}, self.deadline_s, timeout_s=timeout_s)
            encoded = data.get("imageData")
            if not isinstance(encoded, str) or "," not in encoded:
                raise ManagedObsError("OBS returned malformed calibration screenshot data.")
            try:
                png = base64.b64decode(encoded.split(",", 1)[1], validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ManagedObsError("OBS returned invalid calibration screenshot base64.") from exc
            if not png.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ManagedObsError("OBS returned a non-PNG calibration screenshot.")
            self._engine._verify_calibration_isolation(self._run, self._ws, self._snapshot, self.source_uuid, self._ref_id,
                                                       self.deadline_s)
            return png
        finally:
            self._guard.sample("after-capture")


class _ManagedCalibrationAdapter:
    def __init__(self, engine: "ManagedObs") -> None:
        self._engine = engine

    def identity(self) -> EngineIdentity | None:
        return self._engine._calibration_identity()

    def start(self, request: CalibrationRequest, *, measure: Callable[[CalibrationIO], ClassifierInput],
              guard: ProgramGuard) -> Future[CalibrationResult]:
        return self._engine._start_calibration(request, measure=measure, guard=guard)

    def cancel(self, run_id: str, *, timeout_s: float = 5.0) -> bool:
        return self._engine._cancel_calibration(run_id, timeout_s=timeout_s)


class ManagedObs:
    """One per dashboard process. Public actions return at once; the work runs on
    a single engine thread in submission order. `state()` is the dashboard JSON.

    Identity is tri-state. An OBS process is ours only when it is a running OBS app
    whose environment carries `CFFIXED_USER_HOME=<home>` and, when a launch date is
    recorded, whose launch date matches. When that cannot be established AK fails
    closed: it launches nothing, writes no tree file and terminates nothing."""

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
        self._jobs: "queue.Queue[tuple[Callable[[], Any], bool] | None]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._drained = False
        self._quit_on_exit = False
        self._worker_exiting = False
        self._lock_file: Any = None
        self._obs: dict[str, Any] | None = None
        self._state = "stopped"
        self._reason: str | None = None
        self._pending = 0
        self._pending_state: str | None = None
        self._rate, self._keyer = 25, "external"
        self._desired: tuple[str, int, str] | None = None
        self._apply_queued = False
        self._launched: tuple[int, str] | None = None
        self._setup_rate: int | None = None
        self._setup_jobs = 0
        self._warnings: dict[str, dict[str, Any]] = {}
        self._pid: int | None = None
        self._launch_date: float | None = None
        self._cdp_port: int | None = None
        self._ws_port: int | None = None
        self._ws_password: str | None = None
        self._target_id: str | None = None
        self._ready_at: float | None = None
        self._ready_generation = 0
        self._calibration_run: _CalibrationRun | None = None
        self._calibration_completed: dict[str, bool] = {}
        self._calibration_adapter = _ManagedCalibrationAdapter(self)
        self._inactive_reads = self._cdp_failures = self._ws_failures = self._unknown_ticks = 0

    @property
    def cdp_endpoint(self) -> str | None:
        with self._lock:
            return f"http://127.0.0.1:{self._cdp_port}" if self._cdp_port and self._pid else None

    @property
    def target_id(self) -> str | None:
        with self._lock:
            return self._target_id

    @property
    def active(self) -> bool:
        """True while our OBS runs (as last observed) or an action that may launch or quit it is pending."""
        with self._lock:
            return self._pending > 0 or self._pid is not None

    @property
    def setup_active(self) -> bool:
        """True while device setup is queued, in progress, or waiting for Done."""
        with self._lock:
            return self._setup_jobs > 0 or self._setup_rate is not None

    def calibration_adapter(self) -> CalibrationAdapter:
        return self._calibration_adapter

    def _calibration_identity(self) -> EngineIdentity | None:
        with self._lock:
            if self._state != "ready" or self._pid is None or self._launch_date is None or self._ready_generation <= 0:
                return None
            return EngineIdentity(self._pid, self._launch_date, self._ready_generation)

    @staticmethod
    def _validate_calibration_url(request: CalibrationRequest) -> None:
        run_id = request.spec.run_id
        parsed = urlsplit(request.url)
        if not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise ManagedObsError("Calibration run ID must be 32 lowercase hex characters.")
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username is not None
                or parsed.password is not None or parsed.port is None or parsed.query or parsed.fragment
                or parsed.path != f"/__obed_probe/{run_id}/index.html"):
            raise ManagedObsError("Calibration URL is not the registered loopback probe page.")

    def _start_calibration(self, request: CalibrationRequest, *, measure: Callable[[CalibrationIO], ClassifierInput],
                           guard: ProgramGuard) -> Future[CalibrationResult]:
        identity = self._calibration_identity()
        if identity is None or request.engine != identity:
            raise ManagedObsError("Calibration engine identity is stale or not ready.")
        if request.placement not in ("preview", "offcanvas"):
            raise ManagedObsError(f"Unsupported calibration placement {request.placement!r}.")
        if request.program_target_id != self.target_id or not request.program_context_id or request.connection_generation < 0:
            raise ManagedObsError("Calibration program binding is stale or incomplete.")
        self._validate_calibration_url(request)
        if (request.spec.width, request.spec.height, request.spec.dpr) != (1920, 1080, 1.0):
            raise ManagedObsError("Managed OBS calibration requires 1920x1080 at DPR 1.")
        with self._lock:
            launched = self._launched
        if launched is None or request.spec.fps != RATES[launched[0]][1]:
            raise ManagedObsError("Calibration frame rate does not match the managed program source.")
        with self._lock:
            if self._calibration_run is not None:
                raise ManagedObsError("Calibration is already running.")
            future: Future[CalibrationResult] = Future()
            run = _CalibrationRun(request, future, threading.Event(), threading.Event())
            thread = threading.Thread(target=self._calibration_worker, args=(run, measure, guard),
                                      name=f"managed-obs-calibration-{request.spec.run_id[:8]}", daemon=True)
            run.thread = thread
            self._calibration_run = run
            thread.start()
        return future

    def _cancel_calibration(self, run_id: str, *, timeout_s: float = CALIBRATION_CLEANUP_S) -> bool:
        timeout_s = max(0.0, min(float(timeout_s), CALIBRATION_CLEANUP_S))
        with self._lock:
            run = self._calibration_run
            if run is None:
                return self._calibration_completed.get(run_id, True)
            if run.request.spec.run_id != run_id:
                return False
            run.cancel_event.set()
            transport = run.measurement_ws
        if transport is not None:
            transport.close()
        if not run.done_event.wait(timeout_s):
            return False
        return run.cleanup_verified

    def _signal_calibration_cancel(self) -> _CalibrationRun | None:
        with self._lock:
            run = self._calibration_run
            if run is not None:
                run.cancel_event.set()
                transport = run.measurement_ws
            else:
                transport = None
        if transport is not None:
            transport.close()
        return run

    def _drain_calibration(self) -> bool:
        run = self._signal_calibration_cancel()
        if run is None:
            return True
        if not run.done_event.wait(CALIBRATION_CLEANUP_S):
            log.error("managed OBS calibration cleanup did not finish within %ss", CALIBRATION_CLEANUP_S)
            return False
        return run.cleanup_verified

    def _calibration_check_current(self, run: _CalibrationRun, deadline_s: float, *, cancelled: bool = True) -> None:
        if cancelled and run.cancel_event.is_set():
            raise _CalibrationCancelled("Calibration was cancelled.")
        if self._clock() >= deadline_s:
            raise _CalibrationTimeout("Calibration deadline elapsed.")
        with self._lock:
            current = self._calibration_run is run
            identity = (self._pid, self._launch_date, self._ready_generation)
            ready = self._state == "ready"
        expected = run.request.engine
        if not current or not ready or identity != (expected.pid, expected.launch_date, expected.ready_generation):
            raise ManagedObsError("Calibration engine generation changed.")

    def _calibration_verify_ownership(self, run: _CalibrationRun, deadline_s: float, *, cancelled: bool = True) -> None:
        self._calibration_check_current(run, deadline_s, cancelled=cancelled)
        expected = run.request.engine
        if self._identity(expected.pid, expected.launch_date) != "ours":
            raise ManagedObsError("Calibration engine ownership could not be verified.")
        self._calibration_check_current(run, deadline_s, cancelled=cancelled)

    def _calibration_request(self, run: _CalibrationRun, ws: ObsWebsocket, request_type: str,
                             data: dict[str, Any] | None, deadline_s: float, *, timeout_s: float | None = None,
                             cancelled: bool = True) -> dict[str, Any]:
        self._calibration_check_current(run, deadline_s, cancelled=cancelled)
        remaining = deadline_s - self._clock()
        request_timeout = min(remaining, timeout_s if timeout_s is not None else remaining)
        result = ws.request(request_type, data, timeout=request_timeout)
        self._calibration_check_current(run, deadline_s, cancelled=cancelled)
        return result

    @staticmethod
    def _scene_identity(data: dict[str, Any], prefix: str) -> tuple[str, str]:
        name = data.get(f"{prefix}SceneName") or data.get("sceneName")
        scene_uuid = data.get(f"{prefix}SceneUuid") or data.get("sceneUuid")
        if not isinstance(name, str) or not isinstance(scene_uuid, str):
            raise ManagedObsError(f"OBS returned an incomplete {prefix.lower()} scene identity.")
        return name, scene_uuid

    def _snapshot_calibration(self, run: _CalibrationRun, ws: ObsWebsocket,
                              deadline_s: float) -> tuple[_CalibrationSnapshot, CollectionSnapshot]:
        transition = self._calibration_request(run, ws, "GetCurrentSceneTransition", None, deadline_s)
        if transition.get("transitionName") != "Cut" or transition.get("transitionKind") != "cut_transition":
            raise _CalibrationRefused("Calibration requires the Cut scene transition.")
        log.info("calibration precheck GetCurrentSceneTransition: %s/%s",
                 transition.get("transitionName"), transition.get("transitionKind"))
        cursor = self._calibration_request(run, ws, "GetCurrentSceneTransitionCursor", None, deadline_s)
        if float(cursor.get("transitionCursor", -1.0)) != 1.0:
            raise _CalibrationRefused("Calibration cannot start while a scene transition is in flight.")
        try:
            output = self._calibration_request(run, ws, "GetOutputStatus", {"outputName": PREVIEW_OUTPUT}, deadline_s)
        except ObsRequestError as exc:
            if (exc.request_type, exc.code, exc.comment) != ("GetOutputStatus", 600, _PREVIEW_OUTPUT_ABSENT):
                raise _CalibrationRefused("DeckLink preview output state is unreadable.") from exc
            log.info("calibration precheck GetOutputStatus(%s): absent code %s", PREVIEW_OUTPUT, exc.code)
        else:
            if output.get("outputActive") is not False:
                raise _CalibrationRefused("DeckLink preview output is active.")
            log.info("calibration precheck GetOutputStatus(%s): inactive", PREVIEW_OUTPUT)
        program = self._calibration_request(run, ws, "GetCurrentProgramScene", None, deadline_s)
        program_name, program_uuid = self._scene_identity(program, "currentProgram")
        if program_name != PROGRAM_SCENE:
            raise _CalibrationRefused("Managed OBS program scene is not AK.")
        studio = self._calibration_request(run, ws, "GetStudioModeEnabled", None, deadline_s)
        studio_enabled = studio.get("studioModeEnabled") is True
        preview_name = preview_uuid = None
        try:
            preview = self._calibration_request(run, ws, "GetCurrentPreviewScene", None, deadline_s)
        except ObsRequestError as exc:
            if studio_enabled or (exc.request_type, exc.code, exc.comment) != ("GetCurrentPreviewScene", 506, None):
                raise _CalibrationRefused("Studio preview state is unreadable.") from exc
        else:
            if not studio_enabled:
                raise _CalibrationRefused("OBS returned a preview scene while Studio Mode was off.")
            preview_name, preview_uuid = self._scene_identity(preview, "currentPreview")
        video = self._calibration_request(run, ws, "GetVideoSettings", None, deadline_s)
        if (video.get("baseWidth"), video.get("baseHeight"), video.get("outputWidth"), video.get("outputHeight")) != (
                1920, 1080, 1920, 1080):
            raise _CalibrationRefused("Managed OBS canvas dimensions changed.")
        program_input = self._calibration_request(run, ws, "GetInputSettings", {"inputName": "Program"}, deadline_s)
        program_settings = program_input.get("inputSettings") or {}
        if (program_input.get("inputKind") != "browser_source"
                or (program_settings.get("width"), program_settings.get("height"), program_settings.get("fps"),
                    program_settings.get("fps_custom")) != (1920, 1080, run.request.spec.fps, True)):
            raise _CalibrationRefused("Calibration geometry does not match the managed program source.")
        scenes = self._calibration_request(run, ws, "GetSceneList", None, deadline_s).get("scenes")
        inputs = self._calibration_request(run, ws, "GetInputList", None, deadline_s).get("inputs")
        items = self._calibration_request(run, ws, "GetSceneItemList", {"sceneName": PROGRAM_SCENE}, deadline_s).get("sceneItems")
        if not isinstance(scenes, list) or not isinstance(inputs, list) or not isinstance(items, list):
            raise _CalibrationRefused("OBS scene graph is unreadable.")
        if any(scene.get("sceneName") == CALIBRATION_SCENE for scene in scenes if isinstance(scene, dict)):
            raise _CalibrationRefused("An unowned AK-Calibrate scene already exists.")
        if any(source.get("inputName") == PROBE_SOURCE for source in inputs if isinstance(source, dict)):
            raise _CalibrationRefused("An unowned AK-Probe input already exists.")
        if any(item.get("sourceName") == CALIBRATION_SCENE for item in items if isinstance(item, dict)):
            raise _CalibrationRefused("An unowned AK-Calibrate program item already exists.")
        path = self.tree / "basic/scenes/AK.json"
        stat = path.stat()
        saved_by_obs = self._launch_date is not None and stat.st_mtime_ns > int(self._launch_date * 1_000_000_000)
        baseline = read_collection(path, saved_by_obs=saved_by_obs)
        return _CalibrationSnapshot(studio_enabled, preview_name, preview_uuid, program_name, program_uuid,
                                    dict(video), list(items)), baseline

    def _install_calibration(self, run: _CalibrationRun, ws: ObsWebsocket, snapshot: _CalibrationSnapshot,
                             install: _CalibrationInstall, deadline_s: float) -> None:
        if not snapshot.studio_enabled:
            self._calibration_request(run, ws, "SetStudioModeEnabled", {"studioModeEnabled": True}, deadline_s)
            preview = self._calibration_request(run, ws, "GetCurrentPreviewScene", None, deadline_s)
            snapshot.preview_name, snapshot.preview_uuid = self._scene_identity(preview, "currentPreview")
        install.scene_created = True
        try:
            created = self._calibration_request(run, ws, "CreateScene", {"sceneName": CALIBRATION_SCENE}, deadline_s)
        except ObsRequestError:
            install.scene_created = False
            raise
        scene_uuid = created.get("sceneUuid")
        if not isinstance(scene_uuid, str):
            raise _CalibrationIsolationViolation("OBS did not return the calibration scene UUID.")
        install.input_created = True
        try:
            source = self._calibration_request(
                run, ws, "CreateInput",
                {"sceneName": CALIBRATION_SCENE, "inputName": PROBE_SOURCE, "inputKind": "browser_source",
                 "inputSettings": {"url": run.request.url, "width": run.request.spec.width,
                                   "height": run.request.spec.height, "fps": run.request.spec.fps,
                                   "fps_custom": True, "shutdown": False, "restart_when_active": False,
                                   "reroute_audio": True}, "sceneItemEnabled": True}, deadline_s)
        except ObsRequestError:
            install.input_created = False
            raise
        source_uuid = source.get("inputUuid")
        if not isinstance(source_uuid, str):
            raise _CalibrationIsolationViolation("OBS did not return the calibration source UUID.")
        install.source_uuid = source_uuid
        log.info("installed calibration scene %s and source %s for run %s", scene_uuid, source_uuid,
                 run.request.spec.run_id)
        tracks = {str(index): False for index in range(1, 7)}
        self._calibration_request(run, ws, "SetInputMute", {"inputName": PROBE_SOURCE, "inputMuted": True}, deadline_s)
        self._calibration_request(run, ws, "SetInputAudioTracks",
                                  {"inputName": PROBE_SOURCE, "inputAudioTracks": tracks}, deadline_s)
        self._calibration_request(run, ws, "SetInputAudioMonitorType",
                                  {"inputName": PROBE_SOURCE, "monitorType": "OBS_MONITORING_TYPE_NONE"}, deadline_s)
        self._verify_probe_source(run, ws, source_uuid, scene_uuid, tracks, deadline_s)
        if run.request.placement == "preview":
            self._calibration_request(run, ws, "SetCurrentPreviewScene", {"sceneName": CALIBRATION_SCENE}, deadline_s)
        else:
            install.ref_requested = True
            try:
                item = self._calibration_request(run, ws, "CreateSceneItem",
                                                 {"sceneName": PROGRAM_SCENE, "sourceName": CALIBRATION_SCENE,
                                                  "sceneItemEnabled": False}, deadline_s)
            except ObsRequestError:
                install.ref_requested = False
                raise
            ref_id = item.get("sceneItemId")
            if not isinstance(ref_id, int):
                raise _CalibrationIsolationViolation("OBS did not return the calibration scene item ID.")
            install.ref_id = ref_id
            x = float(snapshot.video["baseWidth"]) + 128.0
            transform = {"positionX": x, "positionY": 0.0, "rotation": 0.0, "scaleX": 1.0, "scaleY": 1.0,
                         "cropLeft": 0, "cropTop": 0, "cropRight": 0, "cropBottom": 0, "cropToBounds": False,
                         "boundsType": "OBS_BOUNDS_NONE"}
            self._calibration_request(run, ws, "SetSceneItemTransform",
                                      {"sceneName": PROGRAM_SCENE, "sceneItemId": ref_id,
                                       "sceneItemTransform": transform}, deadline_s)
            self._verify_offcanvas_transform(run, ws, ref_id, snapshot, deadline_s, enabled=False)
            self._calibration_request(run, ws, "SetSceneItemEnabled",
                                      {"sceneName": PROGRAM_SCENE, "sceneItemId": ref_id,
                                       "sceneItemEnabled": True}, deadline_s)
        install.target_id = self._await_probe_target(run, deadline_s, present=True)
        self._verify_calibration_isolation(run, ws, snapshot, source_uuid, install.ref_id, deadline_s)

    def _verify_probe_source(self, run: _CalibrationRun, ws: ObsWebsocket, source_uuid: str, scene_uuid: str,
                             tracks: dict[str, bool], deadline_s: float) -> None:
        inputs = self._calibration_request(run, ws, "GetInputList", None, deadline_s).get("inputs")
        scenes = self._calibration_request(run, ws, "GetSceneList", None, deadline_s).get("scenes")
        source_rows = [item for item in inputs or [] if item.get("inputName") == PROBE_SOURCE]
        scene_rows = [item for item in scenes or [] if item.get("sceneName") == CALIBRATION_SCENE]
        if len(source_rows) != 1 or source_rows[0].get("inputUuid") != source_uuid:
            raise _CalibrationIsolationViolation("Calibration source identity did not read back.")
        if len(scene_rows) != 1 or scene_rows[0].get("sceneUuid") != scene_uuid:
            raise _CalibrationIsolationViolation("Calibration scene identity did not read back.")
        settings = self._calibration_request(run, ws, "GetInputSettings", {"inputName": PROBE_SOURCE}, deadline_s)
        expected = {"url": run.request.url, "width": 1920, "height": 1080, "fps": run.request.spec.fps,
                    "fps_custom": True, "shutdown": False, "reroute_audio": True}
        actual = settings.get("inputSettings") or {}
        if settings.get("inputKind") != "browser_source" or any(actual.get(key) != value for key, value in expected.items()):
            raise _CalibrationIsolationViolation("Calibration browser settings did not read back.")
        muted = self._calibration_request(run, ws, "GetInputMute", {"inputName": PROBE_SOURCE}, deadline_s)
        audio_tracks = self._calibration_request(run, ws, "GetInputAudioTracks", {"inputName": PROBE_SOURCE}, deadline_s)
        monitor = self._calibration_request(run, ws, "GetInputAudioMonitorType", {"inputName": PROBE_SOURCE}, deadline_s)
        filters = self._calibration_request(run, ws, "GetSourceFilterList", {"sourceName": PROBE_SOURCE}, deadline_s)
        if (muted.get("inputMuted") is not True or audio_tracks.get("inputAudioTracks") != tracks
                or monitor.get("monitorType") != "OBS_MONITORING_TYPE_NONE" or filters.get("filters") != []):
            raise _CalibrationIsolationViolation("Calibration source audio or filters are not isolated.")

    def _verify_offcanvas_transform(self, run: _CalibrationRun, ws: ObsWebsocket, ref_id: int,
                                    snapshot: _CalibrationSnapshot, deadline_s: float, *, enabled: bool) -> None:
        response = self._calibration_request(run, ws, "GetSceneItemTransform",
                                             {"sceneName": PROGRAM_SCENE, "sceneItemId": ref_id}, deadline_s)
        transform = response.get("sceneItemTransform") or {}
        fixed = {"positionX": float(snapshot.video["baseWidth"]) + 128.0, "positionY": 0.0,
                 "rotation": 0.0, "scaleX": 1.0, "scaleY": 1.0,
                 "cropLeft": 0, "cropTop": 0, "cropRight": 0, "cropBottom": 0,
                 "cropToBounds": False, "boundsType": "OBS_BOUNDS_NONE", "boundsWidth": 0.0,
                 "boundsHeight": 0.0, "boundsAlignment": 0, "alignment": 5,
                 "sourceWidth": 1920.0, "sourceHeight": 1080.0, "width": 1920.0, "height": 1080.0}
        if any(transform.get(key) != value for key, value in fixed.items()):
            raise _CalibrationIsolationViolation("Off-canvas calibration transform changed.")
        x, width = transform.get("positionX"), transform.get("width")
        if not isinstance(x, (int, float)) or not isinstance(width, (int, float)) or width <= 0 or x < snapshot.video["baseWidth"]:
            raise _CalibrationIsolationViolation("Off-canvas calibration bounds intersect the canvas.")
        items = self._calibration_request(run, ws, "GetSceneItemList", {"sceneName": PROGRAM_SCENE}, deadline_s).get("sceneItems")
        row = next((item for item in items or [] if item.get("sceneItemId") == ref_id), None)
        if (row is None or row.get("sourceName") != CALIBRATION_SCENE or row.get("sceneItemEnabled") is not enabled
                or row.get("sceneItemBlendMode") != "OBS_BLEND_NORMAL" or row.get("isGroup") is not False):
            raise _CalibrationIsolationViolation("Off-canvas calibration scene item state changed.")

    def _target_rows(self, timeout_s: float = 1.0) -> list[dict[str, Any]]:
        with self._lock:
            port = self._cdp_port
        return _cdp_targets(port, timeout=max(0.01, min(1.0, timeout_s))) if port is not None else []

    def _await_probe_target(self, run: _CalibrationRun, deadline_s: float, *, present: bool) -> str | None:
        while True:
            self._calibration_check_current(run, deadline_s, cancelled=present)
            try:
                rows = [row for row in self._target_rows(deadline_s - self._clock())
                        if row.get("type") == "page" and row.get("url") == run.request.url]
            except Exception as exc:
                raise ManagedObsError("Calibration CDP targets are unreadable.") from exc
            if (len(rows) == 1) is present:
                if present and str(rows[0].get("id")) == run.request.program_target_id:
                    raise _CalibrationIsolationViolation("Calibration target collided with the program target.")
                return str(rows[0].get("id")) if present else None
            if self._clock() + self._poll_s >= deadline_s:
                wanted = "appear" if present else "disappear"
                raise ManagedObsError(f"Calibration CDP target did not {wanted}.")
            self._sleep(self._poll_s)

    def _verify_calibration_isolation(self, run: _CalibrationRun, ws: ObsWebsocket,
                                      snapshot: _CalibrationSnapshot, source_uuid: str, ref_id: int | None,
                                      deadline_s: float) -> None:
        transition = self._calibration_request(run, ws, "GetCurrentSceneTransition", None, deadline_s)
        cursor = self._calibration_request(run, ws, "GetCurrentSceneTransitionCursor", None, deadline_s)
        if (transition.get("transitionName"), transition.get("transitionKind"), cursor.get("transitionCursor")) != (
                "Cut", "cut_transition", 1.0):
            raise _CalibrationIsolationViolation("Calibration transition state changed.")
        try:
            output = self._calibration_request(run, ws, "GetOutputStatus", {"outputName": PREVIEW_OUTPUT}, deadline_s)
        except ObsRequestError as exc:
            if (exc.request_type, exc.code, exc.comment) != ("GetOutputStatus", 600, _PREVIEW_OUTPUT_ABSENT):
                raise ManagedObsError("DeckLink preview output state changed or became unreadable.") from exc
        else:
            if output.get("outputActive") is not False:
                raise _CalibrationIsolationViolation("DeckLink preview output became active.")
        program = self._calibration_request(run, ws, "GetCurrentProgramScene", None, deadline_s)
        if self._scene_identity(program, "currentProgram") != (snapshot.program_name, snapshot.program_uuid):
            raise _CalibrationIsolationViolation("Calibration changed the program scene.")
        video = self._calibration_request(run, ws, "GetVideoSettings", None, deadline_s)
        if any(video.get(key) != snapshot.video.get(key) for key in ("baseWidth", "baseHeight", "outputWidth", "outputHeight")):
            raise _CalibrationIsolationViolation("Calibration canvas dimensions changed.")
        targets = self._target_rows(deadline_s - self._clock())
        if run.request.program_target_id not in {str(row.get("id")) for row in targets}:
            raise _CalibrationIsolationViolation("Calibration lost the program CDP target.")
        if len([row for row in targets if row.get("type") == "page" and row.get("url") == run.request.url]) != 1:
            raise _CalibrationIsolationViolation("Calibration probe target identity changed.")
        inputs = self._calibration_request(run, ws, "GetInputList", None, deadline_s).get("inputs") or []
        source_rows = [row for row in inputs if isinstance(row, dict) and row.get("inputName") == PROBE_SOURCE]
        settings = self._calibration_request(run, ws, "GetInputSettings", {"inputName": PROBE_SOURCE}, deadline_s)
        source_settings = settings.get("inputSettings") or {}
        if (len(source_rows) != 1 or source_rows[0].get("inputUuid") != source_uuid
                or settings.get("inputKind") != "browser_source"
                or (source_settings.get("url"), source_settings.get("width"), source_settings.get("height"),
                    source_settings.get("fps")) != (run.request.url, 1920, 1080, run.request.spec.fps)):
            raise _CalibrationIsolationViolation("Calibration source identity or geometry changed.")
        muted = self._calibration_request(run, ws, "GetInputMute", {"inputName": PROBE_SOURCE}, deadline_s)
        tracks = self._calibration_request(run, ws, "GetInputAudioTracks", {"inputName": PROBE_SOURCE}, deadline_s)
        monitor = self._calibration_request(run, ws, "GetInputAudioMonitorType", {"inputName": PROBE_SOURCE}, deadline_s)
        if (muted.get("inputMuted") is not True
                or tracks.get("inputAudioTracks") != {str(index): False for index in range(1, 7)}
                or monitor.get("monitorType") != "OBS_MONITORING_TYPE_NONE"):
            raise _CalibrationIsolationViolation("Calibration source audio isolation changed.")
        active = self._calibration_request(run, ws, "GetSourceActive", {"sourceName": PROBE_SOURCE}, deadline_s)
        expected_active = run.request.placement == "offcanvas"
        if active.get("videoActive") is not expected_active or active.get("videoShowing") is not True:
            raise _CalibrationIsolationViolation("Calibration source is not active in the selected isolated placement.")
        items = self._calibration_request(run, ws, "GetSceneItemList", {"sceneName": PROGRAM_SCENE}, deadline_s).get("sceneItems")
        if run.request.placement == "preview":
            studio = self._calibration_request(run, ws, "GetStudioModeEnabled", None, deadline_s)
            preview = self._calibration_request(run, ws, "GetCurrentPreviewScene", None, deadline_s)
            if studio.get("studioModeEnabled") is not True or self._scene_identity(preview, "currentPreview")[0] != CALIBRATION_SCENE:
                raise _CalibrationIsolationViolation("Calibration preview placement changed.")
            if items != snapshot.program_items:
                raise _CalibrationIsolationViolation("Calibration changed the program scene graph.")
        elif ref_id is None:
            raise _CalibrationIsolationViolation("Off-canvas calibration reference is missing.")
        else:
            self._verify_offcanvas_transform(run, ws, ref_id, snapshot, deadline_s, enabled=True)
            original = [item for item in items or [] if item.get("sceneItemId") != ref_id]
            if original != snapshot.program_items:
                raise _CalibrationIsolationViolation("Calibration changed an existing program scene item.")

    @staticmethod
    def _remove_absent(exc: ObsRequestError, request_type: str) -> bool:
        expected = _INPUT_ABSENT if request_type == "RemoveInput" else _SCENE_ABSENT
        return (exc.request_type, exc.code, exc.comment) == (request_type, 600, expected)

    def _cleanup_calibration(self, run: _CalibrationRun, snapshot: _CalibrationSnapshot | None,
                             install: _CalibrationInstall, baseline: CollectionSnapshot | None,
                             guard: ProgramGuard, errors: list[str]) -> tuple[bool, bool, PersistenceCheck | None, bool]:
        deadline_s = self._clock() + CALIBRATION_CLEANUP_S
        cleanup_ok = False
        restored = (snapshot is None and not install.scene_created and not install.input_created
                    and not install.ref_requested and install.ref_id is None)
        absent = False
        isolation_violation = False
        isolation_reasons: list[str] = []
        cleanup_error_count = len(errors)
        last_removal_mtime_ns = time.time_ns()
        try:
            self._calibration_verify_ownership(run, deadline_s, cancelled=False)
            with ObsWebsocket(self._ws_port, self._ws_password, timeout=min(2.0, CALIBRATION_CLEANUP_S),
                              max_message_bytes=CALIBRATION_MAX_MESSAGE_BYTES) as ws:
                def request(name: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
                    return self._calibration_request(run, ws, name, data, deadline_s, cancelled=False)

                if snapshot is not None and install.ref_requested and install.ref_id is None:
                    try:
                        items = request("GetSceneItemList", {"sceneName": PROGRAM_SCENE}).get("sceneItems") or []
                        refs = [item.get("sceneItemId") for item in items if item.get("sourceName") == CALIBRATION_SCENE]
                        if len(refs) == 1 and isinstance(refs[0], int):
                            install.ref_id = refs[0]
                        elif refs:
                            errors.append("cleanup-reference: calibration scene item identity is ambiguous")
                            isolation_violation = True
                    except Exception as exc:
                        errors.append(f"cleanup-reference: {type(exc).__name__}: {exc}")
                if snapshot is not None and install.ref_id is not None:
                    try:
                        request("SetSceneItemEnabled", {"sceneName": PROGRAM_SCENE, "sceneItemId": install.ref_id,
                                                        "sceneItemEnabled": False})
                    except Exception as exc:
                        errors.append(f"cleanup-disable: {type(exc).__name__}: {exc}")
                if snapshot is not None and not snapshot.studio_enabled and snapshot.preview_name is None:
                    try:
                        if request("GetStudioModeEnabled").get("studioModeEnabled") is True:
                            preview = request("GetCurrentPreviewScene")
                            snapshot.preview_name, snapshot.preview_uuid = self._scene_identity(preview, "currentPreview")
                    except Exception as exc:
                        errors.append(f"restore-preview-snapshot: {type(exc).__name__}: {exc}")
                if snapshot is not None and snapshot.preview_name is not None:
                    try:
                        studio = request("GetStudioModeEnabled")
                        if studio.get("studioModeEnabled") is not True:
                            request("SetStudioModeEnabled", {"studioModeEnabled": True})
                        request("SetCurrentPreviewScene", {"sceneName": snapshot.preview_name})
                    except Exception as exc:
                        errors.append(f"restore-preview: {type(exc).__name__}: {exc}")
                if install.ref_id is not None:
                    try:
                        request("RemoveSceneItem", {"sceneName": PROGRAM_SCENE, "sceneItemId": install.ref_id})
                    except Exception as exc:
                        errors.append(f"remove-scene-item: {type(exc).__name__}: {exc}")
                removals = []
                if install.input_created:
                    removals.append(("RemoveInput", {"inputName": PROBE_SOURCE}))
                if install.scene_created:
                    removals.append(("RemoveScene", {"sceneName": CALIBRATION_SCENE}))
                for request_type, data in removals:
                    try:
                        request(request_type, data)
                    except ObsRequestError as exc:
                        if not self._remove_absent(exc, request_type):
                            errors.append(f"{request_type}: {type(exc).__name__}: {exc}")
                    except Exception as exc:
                        errors.append(f"{request_type}: {type(exc).__name__}: {exc}")
                last_removal_mtime_ns = time.time_ns()
                while self._clock() < deadline_s:
                    try:
                        inputs = request("GetInputList").get("inputs") or []
                        scenes = request("GetSceneList").get("scenes") or []
                        items = request("GetSceneItemList", {"sceneName": PROGRAM_SCENE}).get("sceneItems") or []
                        absent = (not any(row.get("inputName") == PROBE_SOURCE for row in inputs)
                                  and not any(row.get("sceneName") == CALIBRATION_SCENE for row in scenes)
                                  and not any(row.get("sourceName") == CALIBRATION_SCENE for row in items))
                        if absent:
                            break
                    except Exception as exc:
                        errors.append(f"absence-poll: {type(exc).__name__}: {exc}")
                        break
                    self._sleep(min(0.1, max(0.0, deadline_s - self._clock())))
                if not absent:
                    errors.append("absence-poll: calibration resources remain")
                    isolation_violation = True
                try:
                    self._await_probe_target(run, deadline_s, present=False)
                except Exception as exc:
                    errors.append(f"target-cleanup: {type(exc).__name__}: {exc}")
                    absent = False
                    if "did not disappear" in str(exc):
                        isolation_violation = True
                if snapshot is not None:
                    try:
                        current = request("GetCurrentProgramScene")
                        if self._scene_identity(current, "currentProgram") != (snapshot.program_name, snapshot.program_uuid):
                            isolation_violation = True
                            isolation_reasons.append("isolation: program scene changed during cleanup")
                            request("SetCurrentProgramScene", {"sceneName": snapshot.program_name})
                    except Exception as exc:
                        errors.append(f"restore-program: {type(exc).__name__}: {exc}")
                    try:
                        studio_now = request("GetStudioModeEnabled").get("studioModeEnabled") is True
                        if snapshot.studio_enabled and not studio_now:
                            request("SetStudioModeEnabled", {"studioModeEnabled": True})
                        elif not snapshot.studio_enabled and studio_now:
                            request("SetStudioModeEnabled", {"studioModeEnabled": False})
                    except Exception as exc:
                        errors.append(f"restore-studio: {type(exc).__name__}: {exc}")
                    try:
                        studio = request("GetStudioModeEnabled").get("studioModeEnabled") is True
                        program = self._scene_identity(request("GetCurrentProgramScene"), "currentProgram")
                        current_items = request("GetSceneItemList", {"sceneName": PROGRAM_SCENE}).get("sceneItems")
                        preview_ok = True
                        if snapshot.studio_enabled:
                            preview_ok = self._scene_identity(request("GetCurrentPreviewScene"), "currentPreview") == (
                                snapshot.preview_name, snapshot.preview_uuid)
                        else:
                            try:
                                request("GetCurrentPreviewScene")
                            except ObsRequestError as exc:
                                preview_ok = (exc.request_type, exc.code, exc.comment) == ("GetCurrentPreviewScene", 506, None)
                            else:
                                preview_ok = False
                        restored = (studio == snapshot.studio_enabled and program == (snapshot.program_name, snapshot.program_uuid)
                                    and current_items == snapshot.program_items and preview_ok)
                        if not restored:
                            isolation_violation = True
                            errors.append("isolation: restored OBS state did not match snapshot")
                    except Exception as exc:
                        errors.append(f"restore-readback: {type(exc).__name__}: {exc}")
        except Exception as exc:
            errors.append(f"cleanup-connection: {type(exc).__name__}: {exc}")
        cleanup_ok = absent and len(errors) == cleanup_error_count
        errors.extend(isolation_reasons)
        try:
            guard.sample("restored")
        except Exception as exc:
            errors.append(f"guard-restored: {type(exc).__name__}: {exc}")
            restored = False
        persistence = None
        if baseline is not None:
            try:
                path = self.tree / "basic/scenes/AK.json"
                after = read_collection(path, saved_by_obs=True)
                persistence = check_persistence(baseline, after, null_allowlist=STEP0_NULL_ALLOWLIST,
                                                phase="cleanup", last_removal_mtime_ns=last_removal_mtime_ns)
                if persistence.authoritative and persistence.ok is False:
                    errors.append("persistence: scene collection differs after cleanup")
            except Exception as exc:
                errors.append(f"persistence: {type(exc).__name__}: {exc}")
        return cleanup_ok, restored, persistence, isolation_violation

    def _calibration_worker(self, run: _CalibrationRun, measure: Callable[[CalibrationIO], ClassifierInput],
                            guard: ProgramGuard) -> None:
        started_s = self._clock()
        deadline_s = started_s + CALIBRATION_DEADLINE_S
        evidence = None
        program = None
        isolation_ok = True
        io: _CalibrationIO | None = None
        errors: list[str] = []
        snapshot = None
        baseline = None
        install = _CalibrationInstall()
        try:
            guard.begin()
            guard.sample("before-install")
            with ObsWebsocket(self._ws_port, self._ws_password, timeout=2.0,
                              max_message_bytes=CALIBRATION_MAX_MESSAGE_BYTES) as ws:
                with self._lock:
                    if self._calibration_run is run:
                        run.measurement_ws = ws
                snapshot, baseline = self._snapshot_calibration(run, ws, deadline_s)
                self._calibration_verify_ownership(run, deadline_s)
                self._install_calibration(run, ws, snapshot, install, deadline_s)
                guard.sample("installed")
                if install.source_uuid is None:
                    raise _CalibrationIsolationViolation("Calibration source was not installed.")
                io = _CalibrationIO(self, run, ws, snapshot, install.source_uuid, install.ref_id, guard, deadline_s)
                evidence = measure(io)
                if (not isinstance(evidence, ClassifierInput) or evidence.spec != run.request.spec
                        or evidence.identity.run_id != run.request.spec.run_id
                        or evidence.identity.source_uuid != install.source_uuid
                        or evidence.identity.target_id != install.target_id
                        or evidence.identity.connection_generation != run.request.connection_generation
                        or not evidence.identity.target_id or evidence.identity.target_id == run.request.program_target_id
                        or not evidence.identity.context_id or evidence.identity.dpr != run.request.spec.dpr):
                    raise _CalibrationIsolationViolation("Calibration evidence identity does not match the installed probe.")
        except _CalibrationIsolationViolation as exc:
            isolation_ok = False
            errors.append(f"isolation: {type(exc).__name__}: {exc}")
        except _CalibrationCancelled as exc:
            errors.append(f"cancelled: {type(exc).__name__}: {exc}")
        except (_CalibrationTimeout, ObsWebsocketTimeout) as exc:
            errors.append(f"timeout: {type(exc).__name__}: {exc}")
        except _CalibrationRefused as exc:
            errors.append(f"refused: {type(exc).__name__}: {exc}")
        except Exception as exc:
            reason = "refused" if not any((install.scene_created, install.input_created, install.ref_requested)) else "calibration"
            errors.append(f"{reason}: {type(exc).__name__}: {exc}")
        finally:
            with self._lock:
                if self._calibration_run is run:
                    run.measurement_ws = None
            try:
                guard.sample("before-cleanup")
            except Exception as exc:
                errors.append(f"guard-before-cleanup: {type(exc).__name__}: {exc}")
            cleanup_verified, restored, persistence, cleanup_isolation_violation = self._cleanup_calibration(
                run, snapshot, install, baseline, guard, errors)
            isolation_ok = isolation_ok and not cleanup_isolation_violation
            try:
                program = guard.finish()
            except Exception as exc:
                errors.append(f"guard-finish: {type(exc).__name__}: {exc}")
            result = CalibrationResult(run.request, evidence, program, isolation_ok, cleanup_verified, restored,
                                       persistence, tuple(errors), started_s, self._clock())
            with self._lock:
                run.cleanup_verified = cleanup_verified and restored
                self._calibration_completed[run.request.spec.run_id] = run.cleanup_verified
                while len(self._calibration_completed) > 32:
                    self._calibration_completed.pop(next(iter(self._calibration_completed)))
                if self._calibration_run is run:
                    self._calibration_run = None
            run.done_event.set()
            run.future.set_result(result)

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
            if self._pending_state is not None:
                state, reason = self._pending_state, None
            elif discovery is not None and self._pid is None and self._reason != "identityUnknown":
                state, reason = "unavailable", discovery["id"]
            else:
                state, reason = self._state, self._reason
            payload: dict[str, Any] = {
                "state": state,
                "taken": self._pid is not None,
                "obs": {"path": obs["path"], "version": obs["version"], "pinned": PINNED_OBS},
                "rate": rate_info(self._rate),
                "device": {"name": (device or {}).get("deviceName"), "set": mode_set},
                "keyer": self._keyer,
                "setup": self._setup_rate,
                "warnings": warnings,
            }
            if reason:
                payload["reason"] = reason
            return payload

    def configure(self, rate: int, keyer: str) -> None:
        """Record the preferred rate and keyer shown by `state()`; never starts or locks."""
        self._validate(rate, keyer)
        with self._lock:
            self._rate, self._keyer = rate, keyer

    def apply_settings(self, mode: str, rate: int, keyer: str) -> None:
        """Converge a running engine on the latest output settings: Screen quits it, a Keyer
        rate/keyer change restarts it; selecting Keyer never launches. Queued calls coalesce."""
        if mode not in OUTPUT_MODES:
            raise ValueError(f"Unsupported output mode {mode!r}; supported: {list(OUTPUT_MODES)}.")
        self._validate(rate, keyer)
        with self._lock:
            self._rate, self._keyer = rate, keyer
            self._desired = (mode, rate, keyer)
            taken = self._pid is not None or self._pending_state == "starting"
            publish = ""
            if mode == "screen" and self.active:
                publish = "quitting"
            elif mode == "keyer" and taken and (rate, keyer) != self._launched:
                publish = "starting"
            if self._apply_queued:
                if publish:
                    self._pending_state = publish
                return
            self._apply_queued = self._submit(self._apply, publish)

    def has_orphan(self) -> bool:
        """True when a running OBS carries our home marker and is not our current engine, or when
        that cannot be determined (so a `check()` surfaces obsIdentityUnknown)."""
        orphans = self._orphans()
        return orphans is None or bool(orphans)

    def ensure_started(self, rate: int, keyer: str) -> None:
        self._validate(rate, keyer)
        with self._lock:
            noop = (self._pending == 0 and self._pid is not None and self._state == "ready"
                    and self._launched == (rate, keyer) and self._setup_rate is None) or self._state == "stuck"
        self._submit(lambda: self._ensure_started(rate, keyer), None if noop else "starting")

    def restart(self, rate: int, keyer: str) -> None:
        self._validate(rate, keyer)
        self._signal_calibration_cancel()
        self._submit(lambda: self._restart(rate, keyer), "starting")

    def quit(self) -> None:
        self._signal_calibration_cancel()
        self._submit(lambda: self._acquire() and self._quit() and self._quit_orphans(), "quitting")

    def check(self, reset_page: bool = False) -> None:
        """Re-evaluate the engine; with `reset_page`, also return a ready engine's page to
        `about:blank#obed-ak`, publishing "starting" until that has run."""
        if reset_page:
            self._signal_calibration_cancel()
        self._submit(lambda: self._check(reset_page), "starting" if reset_page else None)

    def show(self) -> None:
        self._submit(self._show)

    def setup_device_begin(self, rate: int) -> None:
        self._validate(rate, self._keyer)
        self._signal_calibration_cancel()
        self._submit_setup(lambda: self._setup_begin(rate), "starting")

    def setup_device_done(self) -> None:
        self._signal_calibration_cancel()
        self._submit_setup(self._setup_done, "quitting")

    def _submit_setup(self, job: Callable[[], Any], pending: str) -> None:
        def run() -> None:
            try:
                job()
            finally:
                with self._lock:
                    self._setup_jobs -= 1

        with self._lock:
            self._setup_jobs += 1
            if not self._submit(run, pending):
                self._setup_jobs -= 1

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Block until every action submitted so far has run (for tests)."""
        done = threading.Event()
        return self._submit(done.set) and done.wait(timeout)

    def shutdown(self, timeout: float) -> bool:
        """Terminal and idempotent: drop queued actions, cancel readiness waits, then quit our
        OBS cleanly (never a kill) as the engine thread's last act. The engine lock is released
        only once that thread has ended; False means it has not yet (call again to keep waiting)."""
        self._drain_calibration()
        with self._lock:
            self._stopping.set()
            self._quit_on_exit = True
            self._drain_once()
            if (self._thread is None or self._worker_exiting) and self._pid is not None:
                self._start_worker()
            thread = self._thread
            if thread is not None:
                self._jobs.put(None)
        return self._join(thread, timeout)

    def close(self, timeout: float = 5.0) -> bool:
        """Stop the engine thread; OBS is quit only if `shutdown()` asked for it. The lock is
        released only once the thread has ended."""
        self._drain_calibration()
        with self._lock:
            self._stopping.set()
            self._drain_once()
            thread = self._thread
            if thread is not None:
                self._jobs.put(None)
        return self._join(thread, timeout)

    def _drain_once(self) -> None:
        if self._drained:
            return
        self._drained = True
        while True:
            try:
                item = self._jobs.get_nowait()
            except queue.Empty:
                break
            if item is not None and item[1]:
                self._finish_pending()
        self._apply_queued = False
        self._setup_jobs = 0

    def _start_worker(self) -> None:
        self._worker_exiting = False
        self._thread = threading.Thread(target=self._run, name="managed-obs", daemon=True)
        self._thread.start()

    def _join(self, thread: threading.Thread | None, timeout: float) -> bool:
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                log.warning("managed OBS engine thread did not stop within %ss; keeping the engine lock", timeout)
                return False
        with self._lock:
            if self._thread is thread:
                self._thread = None
            if self._lock_file is not None:
                self._lock_file.close()
                self._lock_file = None
        return True

    @staticmethod
    def _validate(rate: int, keyer: str) -> None:
        if rate not in RATES:
            raise ValueError(f"Unsupported output rate {rate!r}; supported: {sorted(RATES)}.")
        if keyer not in KEYERS:
            raise ValueError(f"Unsupported keyer {keyer!r}; supported: {list(KEYERS)}.")

    def _submit(self, job: Callable[[], Any], pending: str | None = None) -> bool:
        """Queue `job`. A `pending` string (even "") counts as pending for `active`; a
        non-empty one is also published as the state until the queue has run it."""
        with self._lock:
            if self._stopping.is_set():
                return False
            if self._thread is None:
                self._start_worker()
            if pending is not None:
                self._pending += 1
                if pending:
                    self._pending_state = pending
            self._jobs.put((job, pending is not None))
        return True

    def _finish_pending(self) -> None:
        with self._lock:
            self._pending -= 1
            if self._pending == 0:
                self._pending_state = None

    def _run(self) -> None:
        while True:
            try:
                item = self._jobs.get(timeout=self._liveness_s)
            except queue.Empty:
                if self._stopping.is_set():
                    continue
                item = (self._liveness, False)
            if item is None:
                with self._lock:
                    quit_now = self._quit_on_exit
                    self._worker_exiting = not quit_now
                if quit_now:
                    try:
                        self._quit()
                    except Exception as exc:
                        log.error("managed OBS shutdown quit failed: %s", type(exc).__name__)
                with self._lock:
                    self._worker_exiting = True
                return
            job, counted = item
            try:
                job()
            except Exception as exc:
                log.error("managed OBS engine action failed: %s", type(exc).__name__)
                with self._lock:
                    self._set("blocked", "engineError")
                    self._warnings["engineError"] = self._warning("engineError")
            finally:
                if counted:
                    self._finish_pending()

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

    def _block(self, reason: str, warning_id: str, **fields: Any) -> None:
        with self._lock:
            self._set("blocked", reason)
            self._warnings[warning_id] = self._warning(warning_id, **fields)

    def _identity_unknown(self) -> None:
        log.warning("cannot confirm which OBS is the managed one; refusing to start or stop OBS")
        self._block("identityUnknown", "obsIdentityUnknown")

    def _record_path(self) -> Path:
        return self.home / "ak-engine.json"

    def _forget_process(self) -> None:
        self._ready_generation += 1
        self._pid = self._launch_date = self._target_id = self._ready_at = None

    def _acquire(self) -> bool:
        """Take the process-lifetime engine lock (W13 when another dashboard holds it)."""
        if self._lock_file is not None:
            return True
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

    def _identify(self, pid: int, launch_date: float | None) -> tuple[str, ObsProcess | None]:
        """("ours", process) · ("gone", None): no such OBS, pid reused or not our home · ("unknown", None).
        Absence from LaunchServices is "gone" only when `ps -E` agrees the pid is not ours."""
        try:
            process = next((item for item in self._launcher.processes() if item.pid == pid), None)
        except Exception:
            return "unknown", None
        if process is None:
            marker = self._launcher.env_marker(pid, self.home)
            if marker is False:
                return "gone", None
            log.info("LaunchServices does not list OBS pid %s but ps -E marker is %s; identity unknown", pid, marker)
            return "unknown", None
        if launch_date is not None:
            if process.launch_date is None:
                return "unknown", None
            if abs(process.launch_date - launch_date) > 1.0:
                return "gone", None
        marker = self._launcher.env_marker(pid, self.home)
        if marker is None:
            return "unknown", None
        return ("ours", process) if marker else ("gone", None)

    def _identity(self, pid: int, launch_date: float | None) -> str:
        return self._identify(pid, launch_date)[0]

    def _orphans(self) -> list[ObsProcess] | None:
        """Running OBS apps with our home marker other than the current engine; None when unknown."""
        with self._lock:
            current = self._pid
        try:
            processes = self._launcher.processes()
        except Exception:
            return None
        orphans = []
        for process in processes:
            if process.pid == current:
                continue
            marker = self._launcher.env_marker(process.pid, self.home)
            if marker is None:
                return None
            if marker:
                orphans.append(process)
        return orphans

    def _terminate_and_wait(self, pid: int, launch_date: float | None) -> str:
        """"gone" (already gone) · "rejected" (not verifiably ours; nothing sent) · "terminated" · "stuck"."""
        identity, process = self._identify(pid, launch_date)
        if identity == "gone":
            return "gone"
        if identity == "unknown" or process is None:
            return "rejected"
        if not self._launcher.terminate(process):
            return "gone" if self._identity(pid, launch_date) == "gone" else "rejected"
        deadline = self._clock() + self._quit_timeout_s
        while self._identity(pid, launch_date) != "gone":
            if self._clock() >= deadline:
                return "stuck"
            self._sleep(self._poll_s)
        return "terminated"

    def _stuck(self, pid: int, launch_date: float | None) -> None:
        log.warning("managed OBS pid %s did not quit within %ss", pid, self._quit_timeout_s)
        with self._lock:
            self._pid, self._launch_date = pid, launch_date
            self._set("stuck", "stuck")
            self._warnings["stuck"] = self._warning("stuck")

    def _quit(self) -> bool:
        """Quit our OBS cleanly; True once it is gone. Never force-kills."""
        self._drain_calibration()
        with self._lock:
            pid, launch_date = self._pid, self._launch_date
        if pid is not None:
            with self._lock:
                self._set("quitting")
            outcome = self._terminate_and_wait(pid, launch_date)
            if outcome == "stuck":
                self._stuck(pid, launch_date)
                return False
            if outcome == "rejected":
                self._identity_unknown()
                return False
            if outcome == "terminated":
                self._mark_clean(pid)
                log.info("managed OBS pid %s quit cleanly", pid)
        with self._lock:
            self._forget_process()
            self._warnings = {}
            if self._state != "unavailable":
                self._set("stopped")
        return True

    def _quit_orphans(self) -> bool:
        """Quit every OBS that carries our home marker but is not our engine. False (and
        nothing written or launched) when one is stuck or ownership cannot be determined.
        The record is latched unclean first, so the next launch shows W3."""
        orphans = self._orphans()
        if orphans is None:
            self._identity_unknown()
            return False
        if orphans:
            record = _read_json(self._record_path()) or {}
            record["cleanExit"] = False
            _write_json(self._record_path(), record)
        for process in orphans:
            log.info("quitting orphaned managed OBS pid %s", process.pid)
            with self._lock:
                previous = (self._state, self._reason)
                self._set("quitting")
            outcome = self._terminate_and_wait(process.pid, process.launch_date)
            if outcome == "stuck":
                self._stuck(process.pid, process.launch_date)
                return False
            if outcome == "rejected":
                self._identity_unknown()
                return False
            with self._lock:
                self._set(*previous)
        with self._lock:
            if self._reason == "identityUnknown" and self._pid is None:
                self._warnings.pop("obsIdentityUnknown", None)
                self._set("stopped")
        return True

    def _mark_clean(self, pid: int) -> None:
        record = _read_json(self._record_path())
        if record is not None and record.get("pid") == pid:
            record["cleanExit"] = True
            _write_json(self._record_path(), record)

    def _ensure_started(self, rate: int, keyer: str) -> None:
        if not self._acquire():
            return
        with self._lock:
            pid, launch_date, state = self._pid, self._launch_date, self._state
            same = (rate, keyer) == self._launched and self._setup_rate is None
        if state == "stuck":
            return
        if pid is not None and state in ("starting", "ready", "blocked") and self._identity(pid, launch_date) != "gone":
            if not same:
                self._restart(rate, keyer)
            return
        self._launch(rate, keyer, hidden=True)

    def _restart(self, rate: int, keyer: str) -> None:
        if self._acquire() and self._quit():
            self._launch(rate, keyer, hidden=True)

    def _apply(self) -> None:
        with self._lock:
            self._apply_queued = False
            desired, self._desired = self._desired, None
            pid, launched, setup = self._pid, self._launched, self._setup_rate
        if desired is None or pid is None or not self._acquire():
            return
        mode, rate, keyer = desired
        if mode == "screen":
            self._quit()
        elif (rate, keyer) != launched and setup is None:
            self._restart(rate, keyer)

    def _launch(self, rate: int, keyer: str, *, hidden: bool) -> None:
        if self._stopping.is_set() or not self._discover():
            return
        if not self._quit_orphans():
            return
        previous_clean = (_read_json(self._record_path()) or {}).get("cleanExit")
        cdp_port, ws_port, password = self._pick_port(), self._pick_port(), secrets.token_urlsafe(32)
        with self._lock:
            self._warnings = {}
            if previous_clean is False:
                self._warnings["obsUncleanExit"] = self._warning("obsUncleanExit")
            self._rate, self._keyer = rate, keyer
            self._launched = (rate, keyer)
            self._setup_rate = None if hidden else rate
            self._cdp_port, self._ws_port, self._ws_password = cdp_port, ws_port, password
            self._inactive_reads = self._cdp_failures = self._ws_failures = self._unknown_ticks = 0
            self._set("starting")
        self._seed(TreeConfig(rate=rate, keyer=keyer, ws_port=ws_port, ws_password=password, device=self.device(), record_dir=self._record_dir))
        with self._lock:
            self._forget_process()
            if self._stopping.is_set():
                self._set("stopped")
                return
        args = ["--multi", "--disable-updater", "--disable-missing-files-check"]
        if hidden:
            args.append("--minimize-to-tray")
        args.append(f"--remote-debugging-port={cdp_port}")
        env = {"CFFIXED_USER_HOME": str(self.home), "HOME": str(self.home)}

        def on_launched(pid: int, launch_date: float | None) -> None:
            with self._lock:
                if self._pid == pid:
                    return
                self._pid, self._launch_date = pid, launch_date
            _write_json(self._record_path(), {"pid": pid, "launchDate": launch_date, "cdpPort": cdp_port, "wsPort": ws_port, "cleanExit": False})

        launched_at = time.time()
        pid, launch_date = self._launcher.launch(self._obs_app, args, env, hidden=hidden, on_launched=on_launched)
        on_launched(pid, launch_date)
        log.info("launched managed OBS pid %s (cdp %s, websocket %s, %s)", pid, cdp_port, ws_port, "hidden" if hidden else "visible")
        self._await_ready(min(launch_date or launched_at, launched_at))

    def _seed(self, cfg: TreeConfig) -> None:
        """The only writer of the OBS tree: refuses unless no OBS of ours is (or may be) running."""
        with self._lock:
            pid, launch_date = self._pid, self._launch_date
        if (pid is not None and self._identity(pid, launch_date) != "gone") or self._orphans() != []:
            raise ManagedObsError("Refusing to seed the OBS tree while a managed OBS is or may be running.")
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
        """Ready only when one pass verifies the pid is ours and sees both the marked page and a pinned GetVersion."""
        deadline = self._clock() + self._ready_timeout_s
        with self._lock:
            pid, launch_date = self._pid, self._launch_date
        while not self._stopping.is_set():
            identity = self._identity(pid, launch_date)
            if identity == "gone":
                self._on_exit()
                return
            if self._safe_mode_logged(since):
                self._block("safeMode", "obsSafeMode")
                return
            target_id, version = self._page_target(), self._obs_version()
            if version is not None and version != PINNED_OBS:
                log.warning("managed OBS reports version %s, pinned %s", version, PINNED_OBS)
                self._block("obsVersion", "obsVersion", found=version)
                return
            if identity == "ours" and target_id and version:
                log.info("managed OBS ready: OBS %s, page target %s", version, target_id)
                with self._lock:
                    self._ready_generation += 1
                    self._target_id, self._ready_at = target_id, self._clock()
                    self._inactive_reads = self._cdp_failures = self._ws_failures = self._unknown_ticks = 0
                    for warning_id in _TRANSIENT_WARNINGS:
                        self._warnings.pop(warning_id, None)
                    self._set("blocked", "deviceSetup") if self._setup_rate is not None else self._set("ready")
                return
            if self._clock() >= deadline:
                if identity == "unknown":
                    self._identity_unknown()
                elif target_id:
                    self._block("safeMode", "obsSafeMode")
                else:
                    self._block("timeout", "obsWaiting")
                return
            self._sleep(self._poll_s)

    def _on_exit(self) -> None:
        self._signal_calibration_cancel()
        with self._lock:
            setup = self._setup_rate is not None
            self._forget_process()
            if setup:
                self._set("blocked", "deviceSetup")
            else:
                self._set("blocked", "exited")
                self._warnings["obsExited"] = self._warning("obsExited")
        log.warning("managed OBS closed during device setup" if setup else "managed OBS exited without AK asking")

    def _liveness(self) -> None:
        with self._lock:
            if self._pid is None or self._state not in ("ready", "blocked"):
                return
            pid, launch_date, target_id, ready_at, reason = self._pid, self._launch_date, self._target_id, self._ready_at, self._reason
            launched_rate = self._launched[0] if self._launched else None
        identity = self._identity(pid, launch_date)
        ids: set[str] | None = None
        if identity == "gone" and target_id is not None:
            try:
                ids = {str(item.get("id")) for item in _cdp_targets(self._cdp_port)}
            except Exception:
                ids = None
            if ids is not None and target_id in ids:
                log.info("OBS pid %s reads gone but CDP still lists target %s; identity unknown", pid, target_id)
                identity = "unknown"
        if identity == "gone":
            self._on_exit()
            return
        if reason in ("timeout", "safeMode", "obsVersion", "engineError", "deviceSetup", "stuck") or target_id is None:
            return
        self._unknown_ticks = self._unknown_ticks + 1 if identity == "unknown" else 0
        try:
            if ids is None:
                ids = {str(item.get("id")) for item in _cdp_targets(self._cdp_port)}
            self._cdp_failures = 0
        except Exception:
            self._cdp_failures += 1
        device = self.device() or {}
        device_due = (bool(device.get("deviceHash")) and str(launched_rate) in (device.get("modeIds") or {})
                      and ready_at is not None and self._clock() - ready_at >= self._device_grace_s)
        active: bool | None = None
        try:
            with ObsWebsocket(self._ws_port, self._ws_password, timeout=2.0) as ws:
                ws.request("GetVersion")
                if device_due:
                    try:
                        active = bool(ws.request("GetOutputStatus", {"outputName": DECKLINK_OUTPUT}).get("outputActive"))
                    except ObsRequestError as exc:
                        log.warning("GetOutputStatus(%s) refused: code %s", DECKLINK_OUTPUT, exc.code)
                        active = False
            self._ws_failures = 0
        except ObsWebsocketError as exc:
            log.warning("managed OBS websocket check failed: %s", type(exc).__name__)
            self._ws_failures += 1
        if active is True:
            self._inactive_reads = 0
        elif active is False:
            self._inactive_reads += 1
        conditions = (
            ("identityUnknown", "obsIdentityUnknown", self._unknown_ticks >= _FAILURE_LIMIT),
            ("pageLost", "obsPageLost", (ids is not None and target_id not in ids) or self._cdp_failures >= _FAILURE_LIMIT),
            ("obsUnreachable", "obsUnreachable", self._ws_failures >= _FAILURE_LIMIT),
            ("deviceInactive", "deviceInactive", self._inactive_reads >= 2 or (reason == "deviceInactive" and active is None)),
        )
        with self._lock:
            for _, warning_id, raised in conditions:
                if raised:
                    self._warnings[warning_id] = self._warning(warning_id)
                else:
                    self._warnings.pop(warning_id, None)
            blocking = next((condition_reason for condition_reason, _, raised in conditions if raised), None)
            if blocking is not None:
                self._set("blocked", blocking)
            elif self._state != "ready":
                self._set("ready")

    def _check(self, reset_page: bool = False) -> None:
        if not self._acquire():
            return
        self._discover()
        with self._lock:
            state, reason, pid, launch_date = self._state, self._reason, self._pid, self._launch_date
        if state == "stuck":
            if pid is None or self._identity(pid, launch_date) == "gone":
                with self._lock:
                    self._forget_process()
                    self._warnings.pop("stuck", None)
                    self._set("stopped")
            return
        if not self._quit_orphans() or pid is None:
            return
        if reason == "obsVersion":
            with self._lock:
                fixed = self._obs is not None and self._discovery_warning(self._obs) is None
                launched, setup = self._launched, self._setup_rate
            if fixed and launched is not None and setup is None:
                self._restart(*launched)
        elif state == "blocked" and reason in _RECHECKABLE:
            with self._lock:
                self._set("starting")
                self._inactive_reads = self._cdp_failures = self._ws_failures = self._unknown_ticks = 0
                for warning_id in _TRANSIENT_WARNINGS:
                    self._warnings.pop(warning_id, None)
            self._await_ready(launch_date or 0.0)
        else:
            self._liveness()
        if reset_page and self._state == "ready":
            self._reset_page()

    def _show(self) -> None:
        with self._lock:
            pid, launch_date = self._pid, self._launch_date
        if pid is None:
            return
        identity, process = self._identify(pid, launch_date)
        if identity == "ours" and process is not None:
            self._launcher.show(process)

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
        if self._acquire() and self._quit():
            self._launch(rate, self._keyer, hidden=False)

    def _setup_done(self) -> None:
        if not self._acquire():
            return
        with self._lock:
            rate = self._setup_rate
        if rate is None or not self._quit():
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
