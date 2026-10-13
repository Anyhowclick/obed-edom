"""The single, server-owned Chrome player used for HDMI program output.

This is deliberately a small adapter: it does not interpret Keynote scenes or
create a second player for a presenter.  The patched Keynote runtime remains
the authority for whether an input has settled.
"""

from __future__ import annotations

import hashlib
import ipaddress
import io
import json
import math
import mimetypes
import os
import queue
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import Future
from urllib.parse import unquote, urlsplit
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Literal, NoReturn

from PIL import Image
from websockets.sync.client import connect

from .devtools_port import DEVTOOLS_ACTIVE_PORT, ForeignDevToolsEndpoint, verify_devtools_owner, wait_devtools_active_port
from .html_preview import preview_root, safe_export_file
from .live_continuity import ContinuityPlan, Unsupported, codec_report, derive_plan
from .live_continuity_js import CONTINUITY_VERSION, PRESERVE_CORE_JS, js_sha256
from .live_gl_replay_js import GL_REPLAY_VERSION, gl_replay_script
from .live_gl_replay_js import js_sha256 as gl_replay_js_sha256
from .live_runtime import MM_OPACITY_ENV, RUNTIME_VERSION, LiveRuntimeUnsupported, patch_player
from .live_session import PlayerCommandRejected, PlayerObservation
from .managed_obs import (
    CalibrationAdapter,
    CalibrationIO,
    CalibrationRequest,
    CalibrationResult,
    EngineIdentity,
    ProgramCheck,
)
from .placement_probe import (
    ClassifierInput,
    PoseGeometry,
    ProbeCapture,
    ProbeIdentity,
    ProbeSpec,
    ProbeVerdict,
    ToneMap,
    classify_probe,
    load_probe_assets,
    render_probe_page,
)

ATTACH_ENV = "OBED_LIVE_ATTACH"
ATTACH_MATCH_ENV = "OBED_LIVE_ATTACH_MATCH"
ADVANCE_ENV = "OBED_LIVE_ADVANCE"
CONTINUITY_ENV = "OBED_LIVE_CONTINUITY"
GL_REPLAY_ENV = "OBED_LIVE_GL_REPLAY"
GOTO_AUTOPLAY_ENV = "OBED_LIVE_GOTO_AUTOPLAY"
GOTO_AUTOPLAY_DEFERRED_NOTE = "Movies idle until next advance"
_UNSET = object()
_CDP_MAX_MESSAGE_BYTES = 64 * 1024 * 1024
_CHROME_START_TIMEOUT_S = 15.0
QUALIFIED_SNAP_MAJORS = (154,)
_PLACEMENT_ROUND_TRIP = ["true", "snap", "true", "invalid"]
_PLACEMENT_LEASE_MS = 15_000
_PLACEMENT_RENEW_S = 3.0
_PROBE_CAPTURE_SETTLE_S = .3
_PROBE_CAPTURE_INTERVAL_S = .2
_PROBE_MEASURE_S = 15.0
_TONE_UNSET = object()
_CONTINUITY_STAGE_GATE_EXPR = (
    "(()=>{var s=document.getElementById('stage');var r=s?s.getBoundingClientRect():null;"
    "return {ready:!!(window.__OBED_P2_PRESERVE__&&window.__OBED_P2_PRESERVE__.ready===true),"
    "present:!!window.__OBED_P2_PRESERVE__,"
    "info:window.__OBED_CONTINUITY_INFO__||null,"
    "stage:s?{offsetWidth:s.offsetWidth,offsetHeight:s.offsetHeight,"
    "rect:{left:r.left,top:r.top,width:r.width,height:r.height}}:null};})()"
)


def derive_runtime(export_root: Path, slides: list[dict[str, Any]], *, resolver=safe_export_file, **kwargs: Any) -> tuple[ContinuityPlan, dict[str, Any]] | Unsupported:
    try:
        plan = derive_plan(export_root, slides, resolver=resolver, **kwargs)
        if isinstance(plan, Unsupported):
            return plan
        runtime = plan.to_runtime()
    except Exception as exc:  # noqa: BLE001 - fail closed, never let derivation crash the host
        return Unsupported(str(exc))
    return runtime if isinstance(runtime, Unsupported) else (plan, runtime)


def not_carried(plan: ContinuityPlan, slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per (boundary, movie instance) continuity declines to carry, in operator
    terms: original slide ordinals rather than the plan's player indices, with the
    refusal code and the source instance's objectID."""
    ordinals = {
        slide.get("playerIndex"): slide.get("originalOrdinal")
        for slide in slides
        if not slide.get("skipped")
    }
    return [
        {
            "fromSlide": ordinals.get(refusal["fromPlayer"]),
            "toSlide": ordinals.get(refusal["toPlayer"]),
            "asset": refusal["asset"],
            "objectId": refusal["objectId"],
            "code": refusal["code"],
            "reason": refusal["reason"],
        }
        for refusal in plan.refusals
    ]


def placement_init_script(token: str, *, mode: Literal["knowledge", "probe"] = "knowledge") -> str:
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ValueError("Placement token must be 128-bit lowercase hex.")
    if mode not in ("knowledge", "probe"):
        raise ValueError("Placement mode must be knowledge or probe.")
    return (
        f'(function(){{var T="{token}",M="{mode}",r="invalid",x=0,n=performance.now.bind(performance);'
        'function z(){if("probe"===M&&"invalid"!==r&&n()>=x){r="invalid";x=0}return r}'
        'Object.defineProperty(window,"__obedPlacement",{get:z,enumerable:false,configurable:false});'
        'Object.defineProperty(window,"__obedGrant",{value:function(t,v,m){if(t!==T)return!1;'
        'if("invalid"===v){r="invalid";x=0;return!0}'
        'if("knowledge"===M){if("snap"===v&&void 0===m){r=v;x=0;return!0}r="invalid";x=0;return!1}'
        'if(("snap"===v||"frac"===v)&&Number.isInteger(m)&&m>0&&m<=15000){r=v;x=n()+m;return!0}'
        'r="invalid";x=0;return!1},enumerable:false,configurable:false,writable:false})})();'
    )


def _placement_round_trip_expr(token: str, *, mode: Literal["knowledge", "probe"] = "knowledge") -> str:
    if mode not in ("knowledge", "probe"):
        raise ValueError("Placement mode must be knowledge or probe.")
    lease = ",15000" if mode == "probe" else ""
    return (
        f'(function(){{var o=[],g=window.__obedGrant,T="{token}";try{{try{{o.push(String(g(T,"snap"{lease})),String(window.__obedPlacement))}}'
        'finally{o.push(String(g(T,"invalid")),String(window.__obedPlacement))}}catch(e){o.push(null)}return o})()'
    )


def _placement_set_expr(token: str, value: str, ms: int | None = None) -> str:
    suffix = "" if ms is None else f",{ms}"
    return (
        f'(function(){{try{{return window.__obedGrant("{token}",{json.dumps(value)}{suffix})===true?window.__obedPlacement:null}}'
        'catch(e){return null}})()'
    )


def _placement_renew_expr(token: str, value: str, ms: int) -> str:
    return (
        f'(function(){{try{{if(window.__obedPlacement!=={json.dumps(value)})return null;'
        f'return window.__obedGrant("{token}",{json.dumps(value)},{ms})===true?window.__obedPlacement:null}}'
        'catch(e){return null}})()'
    )


def _continuity_plan_script(plan: dict[str, Any], canvas: dict[str, int]) -> str:
    """Embed the runtime plan as `window.__OBED_CONTINUITY__`, always installed:
    footprints are authored-size pixels and the shared runtime maps authored to
    screen itself from `#stage`; whether the on-screen stage is actually the
    authored size is confirmed later by the host, once the player has laid it
    out. `</` and U+2028/2029 are escaped so an embedded asset filename cannot
    break out of the script tag."""
    payload = json.dumps(plan).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    width, height = int(canvas["width"]), int(canvas["height"])
    return (
        '<script id="obed-continuity-plan">(function(){'
        f"var plan={payload};var w={width},h={height};"
        "window.__OBED_CONTINUITY_INFO__={authoredWidth:w,authoredHeight:h,"
        "viewportWidth:window.innerWidth,viewportHeight:window.innerHeight,installed:true};"
        "window.__OBED_CONTINUITY__=plan;"
        "})();</script>\n"
    )


def _continuity_core_script() -> str:
    core = PRESERVE_CORE_JS.replace("</script", "<\\/script")
    return f'<script id="obed-continuity-core">{core}</script>\n'


def _continuity_scripts(plan: dict[str, Any], canvas: dict[str, int]) -> str:
    return _continuity_plan_script(plan, canvas) + _continuity_core_script()


def _codec_supported(family: str, *, attach: bool, headless: bool) -> bool:
    """h264 decodes everywhere. HEVC is attempted only in headful launch mode: OBS's
    CEF (attach) and headless Chrome are not assumed to decode HEVC (untested either
    way on the owner's Mac, so both fail closed rather than guessing). ProRes never
    plays in Chrome; av1/vp9 decode support here is unverified, so they are kept
    conservative and fail closed like any other unproven codec."""
    if family == "h264":
        return True
    if family == "hevc":
        return not attach and not headless
    return False


def _codec_display(entry: dict[str, Any] | None) -> str:
    if entry is None:
        return "unreadable"
    if entry.get("mixed"):
        return "mixed codecs"
    return entry["codec"] or "unreadable"


class LiveHostError(RuntimeError):
    """The owned browser cannot provide an observed player state."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> Any:
        return None


_DISCOVERY_OPENER = urllib.request.build_opener(_NoRedirect)


def _discovery_get(url: str, timeout: float) -> Any:
    response = _DISCOVERY_OPENER.open(url, timeout=timeout)
    if response.status != 200:
        raise LiveHostError(f"CDP discovery at {url} returned status {response.status}.")
    return response


def _resolves_to_loopback_only(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise LiveHostError(f"Could not resolve {host!r} for a CDP loopback check: {exc}") from exc
    addrs = {info[4][0] for info in infos}
    return bool(addrs) and all(ipaddress.ip_address(addr).is_loopback for addr in addrs)


def _is_loopback_host(host: str) -> bool:
    if host in ("127.0.0.1", "::1"):
        return True
    if host == "localhost":
        return _resolves_to_loopback_only(host)
    return False


def _validate_loopback_endpoint(endpoint: str) -> str:
    try:
        parts = urlsplit(endpoint)
        parts.port
    except ValueError as exc:
        raise LiveHostError("OBED_LIVE_ATTACH must be a valid http loopback endpoint.") from exc
    if parts.scheme != "http":
        raise LiveHostError("OBED_LIVE_ATTACH must be an http loopback endpoint.")
    if parts.username is not None or parts.password is not None:
        raise LiveHostError("OBED_LIVE_ATTACH must not contain userinfo.")
    if parts.path not in ("", "/"):
        raise LiveHostError("OBED_LIVE_ATTACH must not include a path.")
    if parts.query or parts.fragment:
        raise LiveHostError("OBED_LIVE_ATTACH must not include a query or fragment.")
    host = parts.hostname
    if host is None or not _is_loopback_host(host):
        raise LiveHostError("OBED_LIVE_ATTACH must target a loopback CDP endpoint.")
    return endpoint


def _validate_target_ws_url(ws_url: str, endpoint: str) -> str:
    try:
        parts = urlsplit(ws_url)
        parts.port
    except ValueError as exc:
        raise LiveHostError("CDP target websocket URL is invalid.") from exc
    if parts.username is not None or parts.password is not None or parts.fragment:
        raise LiveHostError("CDP target websocket URL must not contain userinfo or a fragment.")
    if parts.scheme != "ws":
        raise LiveHostError(f"CDP target websocket URL has an unexpected scheme: {ws_url}")
    host = parts.hostname
    if host is None or not _is_loopback_host(host):
        raise LiveHostError(f"CDP target websocket is not a loopback address: {ws_url}")
    if parts.port != urlsplit(endpoint).port:
        raise LiveHostError("CDP target websocket port does not match the attach endpoint.")
    return ws_url


class _SessionLogger:
    """Append-only JSONL session log; a logging failure never reaches the caller.

    Writes are enqueued (O(1)) onto a bounded queue and drained by a single daemon
    writer thread, so a slow or wedged log disk can never stall a CDP call or the
    command it is embedded in. A full queue drops the record and counts the drop;
    the count is surfaced to the caller via `dropped` so it can be recorded on the
    session's stop record. Directory creation and file open happen here, inside
    this constructor's own failure boundary, so an unwritable log directory can
    never prevent a show from starting."""

    _QUEUE_MAXSIZE = 2000

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: Any = None
        self._queue: "queue.Queue[dict[str, Any]]" = queue.Queue(maxsize=self._QUEUE_MAXSIZE)
        self._closing = threading.Event()
        self._state_lock = threading.Lock()
        self._dropped = 0
        self._writer: threading.Thread | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("a", buffering=1)
        except Exception:
            self._file = None
        if self._file is not None:
            self._writer = threading.Thread(target=self._drain, daemon=True)
            self._writer.start()

    @property
    def dropped(self) -> int:
        return self._dropped

    def _drain(self) -> None:
        file = self._file
        try:
            while not self._closing.is_set() or not self._queue.empty():
                try:
                    item = self._queue.get(timeout=.1)
                except queue.Empty:
                    continue
                try:
                    file.write(json.dumps(item, default=str) + "\n")
                    file.flush()
                except Exception:
                    pass
        finally:
            try: file.close()
            except Exception: pass
            self._file = None

    def log(self, kind: str, **fields: Any) -> None:
        with self._state_lock:
            if self._file is None or self._closing.is_set():
                return
            record = {"ts": time.time(), "kind": kind, **fields}
            try:
                self._queue.put_nowait(record)
            except queue.Full:
                self._dropped += 1

    def close(self) -> None:
        with self._state_lock:
            self._closing.set()
        if self._writer is not None:
            self._writer.join(timeout=2.0)


def _new_log_path() -> Path:
    directory = preview_root() / "live-logs"
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return directory / f"{stamp}-{os.getpid()}-{time.monotonic_ns()}.jsonl"


@dataclass(frozen=True)
class OutputDisplay:
    display_id: int
    x: int
    y: int
    width: int
    height: int
    primary: bool = False

    def as_output(self) -> dict[str, Any]:
        return {
            "displayId": self.display_id,
            "bounds": {"x": self.x, "y": self.y, "width": self.width, "height": self.height},
            "viewport": {"width": self.width, "height": self.height},
            "canvas": {"width": 1920, "height": 1080},
            "aspect": "16:9",
            "transport": "hdmi",
            "alpha": False,
            "audio": False,
        }

    def as_api(self) -> dict[str, Any]:
        return {"id": str(self.display_id), "name": f"Display {self.display_id}", "width": self.width, "height": self.height,
                "x": self.x, "y": self.y, "primary": self.primary}


def list_displays() -> list[OutputDisplay]:
    """Return Quartz display bounds when available; absence is not HDMI proof."""
    try:
        import Quartz  # type: ignore
        main = Quartz.CGMainDisplayID()
        result = []
        for display_id in Quartz.CGGetActiveDisplayList(32, None, None)[1]:
            rect = Quartz.CGDisplayBounds(display_id)
            result.append(
                OutputDisplay(
                    int(display_id), int(rect.origin.x), int(rect.origin.y),
                    int(rect.size.width), int(rect.size.height),
                    int(display_id) == int(main),
                )
            )
        return result
    except Exception:
        return []


def choose_display(display_id: int | None, displays: list[OutputDisplay] | None = None, *, headless: bool = False) -> OutputDisplay:
    displays = list_displays() if displays is None else displays
    if not displays:
        # Headless/test mode only.  This is intentionally not a display qualification.
        if headless:
            return OutputDisplay(0, 0, 0, 1920, 1080, True)
        raise LiveHostError("No active macOS output display was detected.")
    if display_id is not None:
        for display in displays:
            if display.display_id == display_id:
                return display
        raise LiveHostError("Selected output display is unavailable.")
    return next((display for display in displays if not display.primary), displays[0])


class _AssetServer:
    def __init__(self, root: Path, patched_player: bytes, resolver: Callable[[Path, str], Path] = safe_export_file, *, alpha: bool = False, continuity_script: str = "") -> None:
        self.root, self.patched_player, self.resolver, self.alpha = root, patched_player, resolver, alpha
        self.continuity_script = continuity_script
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self._probe_lock = threading.Lock()
        self._probe_run_id: str | None = None
        self._probe_files: dict[str, tuple[bytes, str]] = {}

    def start(self) -> str:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_: Any) -> None:
                pass

            def do_GET(self) -> None:
                raw = unquote(urlsplit(self.path).path)
                relative = "index.html" if raw in ("", "/") else raw.lstrip("/")
                headers_sent = False
                try:
                    probe = owner._probe_asset(relative)
                    if probe is not None:
                        headers_sent = owner._send_blob(self, *probe)
                    elif relative.startswith("__obed_probe/"):
                        self.send_error(404)
                        headers_sent = True
                    elif relative == "assets/player/main.js":
                        headers_sent = owner._send_bytes(self, owner.patched_player, "application/javascript")
                    elif relative == "program.html":
                        headers_sent = owner._send_bytes(self, owner._program_html(), "text/html")
                    else:
                        path = owner.resolver(owner.root, relative)
                        headers_sent = owner._send_file(self, path)
                except (BrokenPipeError, ConnectionResetError):
                    return
                except Exception:
                    if not headers_sent:
                        self.send_error(404)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.httpd.server_port}/program.html"

    def set_probe_run(self, spec: ProbeSpec | None) -> str | None:
        if spec is None:
            with self._probe_lock:
                self._probe_run_id = None
                self._probe_files = {}
            return None
        if not re.fullmatch(r"[0-9a-f]{32}", spec.run_id):
            raise ValueError("Probe run ID must be 128-bit lowercase hex.")
        assets = load_probe_assets()
        files = {
            "index.html": (render_probe_page(spec), "text/html"),
            assets.pattern.name: (assets.pattern.data, "video/mp4"),
            assets.motion.name: (assets.motion.data, "video/mp4"),
        }
        if set(files) != {"index.html", "placement_probe.mp4", "placement_motion.mp4"}:
            raise ValueError("Probe assets have unexpected names.")
        with self._probe_lock:
            if self.httpd is None:
                raise LiveHostError("Asset server is not running.")
            self._probe_run_id = spec.run_id
            self._probe_files = files
            port = self.httpd.server_port
        return f"http://127.0.0.1:{port}/__obed_probe/{spec.run_id}/index.html"

    def _probe_asset(self, relative: str) -> tuple[bytes, str] | None:
        parts = relative.split("/")
        if len(parts) != 3 or parts[0] != "__obed_probe":
            return None
        with self._probe_lock:
            if parts[1] != self._probe_run_id:
                return None
            return self._probe_files.get(parts[2])

    @staticmethod
    def _send_bytes(handler: BaseHTTPRequestHandler, data: bytes, content_type: str) -> bool:
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        try:
            handler.wfile.write(data)
        except OSError:
            pass
        return True

    @staticmethod
    def _send_blob(handler: BaseHTTPRequestHandler, data: bytes, content_type: str) -> bool:
        start, end = 0, len(data) - 1
        requested = handler.headers.get("Range", "")
        if requested.startswith("bytes="):
            first, _, last = requested[6:].partition("-")
            if not first.isdigit() or (last and not last.isdigit()):
                handler.send_error(416)
                return True
            start = int(first)
            end = int(last) if last else end
            if start > end or end >= len(data):
                handler.send_error(416)
                return True
            handler.send_response(206)
            handler.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        else:
            handler.send_response(200)
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(end - start + 1))
        handler.end_headers()
        try:
            handler.wfile.write(data[start:end + 1])
        except OSError:
            pass
        return True

    @staticmethod
    def _send_file(handler: BaseHTTPRequestHandler, path: Path) -> bool:
        length = path.stat().st_size
        start, end = 0, length - 1
        requested = handler.headers.get("Range", "")
        if requested.startswith("bytes="):
            first, _, last = requested[6:].partition("-")
            if not first.isdigit() or (last and not last.isdigit()):
                handler.send_error(416)
                return True
            start = int(first)
            end = int(last) if last else end
            if start > end or end >= length:
                handler.send_error(416)
                return True
            handler.send_response(206)
            handler.send_header("Content-Range", f"bytes {start}-{end}/{length}")
        else:
            handler.send_response(200)
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        handler.send_header("Content-Length", str(end - start + 1))
        handler.end_headers()
        try:
            with path.open("rb") as source:
                source.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = source.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    handler.wfile.write(chunk)
                    remaining -= len(chunk)
        except OSError:
            pass
        return True

    def _program_html(self) -> bytes:
        source = self.resolver(self.root, "index.html").read_text()
        fit_script = """
<script id="obed-output-fit">Object.defineProperty(document,'webkitIsFullScreen',{get:()=>true});window.addEventListener('load',()=>setTimeout(()=>document.dispatchEvent(new Event('webkitfullscreenchange'))));</script>
"""
        if self.alpha:
            style = """
<style id="obed-output-overlay">html,body,#body{background:transparent!important}#body{opacity:0}#slideshowNavigator,#slideNumberControl,#slideNumberDisplay,#helpPlacard{display:none!important}body{cursor:none}</style>
"""
            overlay = """
<script>(function(){var hidden=true;function apply(){var el=document.getElementById('body');if(!el)return;el.style.setProperty('background','transparent','important');el.style.setProperty('opacity',hidden?'0':'1','important');}window.__obedOutput={show(){hidden=false;apply();},hide(){hidden=true;apply();}};var target=document.getElementById('body');if(target){new MutationObserver(apply).observe(target,{attributes:true,attributeFilter:['style','class']});}document.addEventListener('DOMContentLoaded',apply);apply();})();</script>
"""
        else:
            style = """
<style id="obed-output-overlay">#obed-output-black{position:fixed;inset:0;background:#000;z-index:2147483647}#slideshowNavigator,#slideNumberControl,#slideNumberDisplay,#helpPlacard{display:none!important}body{cursor:none}</style>
"""
            overlay = """
<div id="obed-output-black"></div>
<script>window.__obedOutput={show(){document.getElementById('obed-output-black').style.display='none'},hide(){document.getElementById('obed-output-black').style.display='block'}};</script>
"""
        head = re.search(r"<head[^>]*>", source, flags=re.IGNORECASE)
        body = re.search(r"<body[^>]*>", source, flags=re.IGNORECASE)
        if not head or not body:
            raise LiveHostError("Prepared player document has no usable head and body.")
        source = source[: head.end()] + style + source[head.end() :]
        body = re.search(r"<body[^>]*>", source, flags=re.IGNORECASE)
        assert body is not None
        body_inject = overlay + self.continuity_script + fit_script
        return (source[: body.end()] + body_inject + source[body.end() :]).encode()

    def stop(self) -> None:
        errors: list[Exception] = []
        self.set_probe_run(None)
        if self.httpd is not None:
            for step in (self.httpd.shutdown, self.httpd.server_close):
                try: step()
                except Exception as exc: errors.append(exc)
            if not errors:
                self.httpd = None
        if self.thread is not None:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                errors.append(LiveHostError("Asset server thread did not stop."))
            else:
                self.thread = None
        if errors:
            raise LiveHostError("Asset server did not fully stop.")


class ChromeCdp:
    """Synchronous CDP transport with one socket and serialized request IDs.

    In attach mode (`attach_endpoint` set) no Chrome process is spawned: an
    existing page target reachable over CDP HTTP is discovered and driven in
    place. All observation, key delivery, and ack/settle logic is unchanged.
    """
    def __init__(self, chrome: Path, profile: Path, display: OutputDisplay | None, *, headless: bool = False, attach_endpoint: str | None = None, attach_match: str | None = None, logger: _SessionLogger | None = None, log_path: Path | None = None) -> None:
        self.chrome, self.profile, self.display, self.headless = chrome, profile, display, headless
        self.attach_endpoint = _validate_loopback_endpoint(attach_endpoint) if attach_endpoint else None
        self.attach_match, self.logger, self.log_path = attach_match, logger, log_path
        self.proc: subprocess.Popen[bytes] | None = None
        self.ws: Any = None
        self.port: int | None = None
        self._stderr_file: Any = None
        self._id = 0
        self._lock = threading.Lock()
        self._stop_lock = threading.Lock()
        self._stopped = False
        self._target_ws_url: str | None = None
        self.target_id: str | None = None
        self.target_url: str | None = None
        self._blank_url = "about:blank"
        self._blanked = False
        self._contexts: dict[str, dict[str, Any]] = {}
        self._browser_ws_url: str | None = None
        self._browser_ws: Any = None
        self._browser_id = 0
        self._browser_lock = threading.Lock()

    def _log(self, kind: str, **fields: Any) -> None:
        if self.logger is None: return
        try: self.logger.log(kind, **fields)
        except Exception: pass

    def start(self) -> None:
        if self.attach_endpoint:
            targets = self._list_targets()
            target = self._pick_target(targets)
            ws_url = _validate_target_ws_url(target["webSocketDebuggerUrl"], self.attach_endpoint)
            try:
                self.ws = connect(ws_url, open_timeout=5, max_size=_CDP_MAX_MESSAGE_BYTES)
            except Exception as exc:
                raise LiveHostError(f"Could not attach to CDP target: {exc}") from exc
            self._target_ws_url = ws_url
            self.target_id = target.get("id") if isinstance(target.get("id"), str) else None
            self.target_url = target.get("url") if isinstance(target.get("url"), str) else None
            attached_url = str(target.get("url") or "")
            self._blank_url = attached_url if attached_url.startswith("about:blank") else "about:blank"
            self._blanked = False
            self.call("Runtime.enable")
            self.call("Page.enable")
            try: self.call("Log.enable")
            except Exception: pass
            return
        self.profile.mkdir(parents=True, exist_ok=True)
        (self.profile / DEVTOOLS_ACTIVE_PORT).unlink(missing_ok=True)
        self.port = None
        args = [
            str(self.chrome), "--remote-debugging-port=0",
            "--remote-debugging-address=127.0.0.1", f"--user-data-dir={self.profile}",
            f"--window-size={self.display.width},{self.display.height}",
            f"--window-position={self.display.x},{self.display.y}", "--force-device-scale-factor=1",
            "--autoplay-policy=no-user-gesture-required", "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
            "--mute-audio", "--no-first-run", "--no-default-browser-check",
            "--app=data:text/html,<body style='margin:0;background:black'></body>",
        ]
        if self.headless: args.insert(1, "--headless=new")
        stderr: Any = subprocess.DEVNULL
        if self.log_path is not None:
            try: stderr = self._stderr_file = self.log_path.with_suffix(".chrome.log").open("wb")
            except Exception: stderr = subprocess.DEVNULL
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=stderr)
        try: endpoint = wait_devtools_active_port(self.profile, self.proc, _CHROME_START_TIMEOUT_S)
        except RuntimeError as exc: self._abort_start(f"Chrome CDP did not start: {exc}", exc)
        self.port = endpoint.port
        self._browser_ws_url = f"ws://127.0.0.1:{endpoint.port}{endpoint.browser_path}"
        deadline = time.monotonic() + _CHROME_START_TIMEOUT_S
        while time.monotonic() < deadline:
            self._abort_start_if_exited()
            try:
                verify_devtools_owner(endpoint, .3)
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=.3) as response: targets = json.loads(response.read())
                target = next((item for item in targets if item.get("type") == "page" and item.get("webSocketDebuggerUrl")), None)
                if target:
                    self.ws = connect(target["webSocketDebuggerUrl"], open_timeout=2, max_size=_CDP_MAX_MESSAGE_BYTES)
                    self.target_id = target.get("id") if isinstance(target.get("id"), str) else None
                    self.target_url = target.get("url") if isinstance(target.get("url"), str) else None
                    break
            except ForeignDevToolsEndpoint as exc: self._abort_start(f"Chrome CDP did not start: {exc}", exc)
            except Exception: pass
            time.sleep(.05)
        if not self.ws: self._abort_start("Chrome CDP did not start.")
        self._abort_start_if_exited()
        self.call("Runtime.enable")
        self.call("Page.enable")
        try: self.call("Log.enable")
        except Exception: pass
        if not self.headless:
            window = self.call("Browser.getWindowForTarget")
            self.call("Browser.setWindowBounds", windowId=window["windowId"], bounds={"windowState": "fullscreen"})

    def _abort_start(self, message: str, cause: Exception | None = None) -> NoReturn:
        try: self.stop()
        except Exception: pass
        raise LiveHostError(message) from cause

    def _abort_start_if_exited(self) -> None:
        exit_code = self.proc.poll()
        if exit_code is not None:
            self._abort_start(f"Chrome CDP did not start: Chrome exited ({exit_code}) before its page target was ready")

    def _list_targets(self) -> list[dict[str, Any]]:
        url = self.attach_endpoint.rstrip("/") + "/json/list"
        try:
            with _discovery_get(url, timeout=5) as response:
                return json.loads(response.read())
        except LiveHostError:
            raise
        except Exception as exc:
            raise LiveHostError(f"Could not list CDP targets at {self.attach_endpoint}: {exc}") from exc

    @staticmethod
    def _describe_targets(items: list[dict[str, Any]]) -> str:
        return ", ".join(f"{item.get('id', '')} {item.get('url', '')} ({item.get('title', '')})" for item in items) or "none"

    def _pick_target(self, targets: list[dict[str, Any]]) -> dict[str, Any]:
        pages = [item for item in targets if item.get("type") == "page" and item.get("webSocketDebuggerUrl")]
        if self.attach_match:
            matched = [item for item in pages if item.get("id") == self.attach_match or any(self.attach_match in item.get(field, "") for field in ("url", "title"))]
            if len(matched) != 1:
                raise LiveHostError(
                    f"CDP attach match {self.attach_match!r} did not select exactly one page target; "
                    f"candidates: {self._describe_targets(matched or pages)}"
                )
            return matched[0]
        if len(pages) != 1:
            raise LiveHostError(f"Ambiguous CDP attach target; candidates: {self._describe_targets(pages)}")
        return pages[0]

    def call(self, method: str, deadline_s: float | None = None, **params: Any) -> dict[str, Any]:
        budget = 15.0 if deadline_s is None else deadline_s
        deadline = time.monotonic() + budget
        if budget <= 0 or not self._lock.acquire(timeout=budget):
            self._log("cdpTimeout", method=method)
            raise LiveHostError(f"Program browser did not answer CDP {method} in time.")
        try:
            ws, proc = self.ws, self.proc
            if not ws: raise LiveHostError("Program browser stopped unexpectedly.")
            if proc is not None and proc.poll() is not None: raise LiveHostError("Program browser stopped unexpectedly.")
            self._id += 1
            request_id = self._id
            started = time.monotonic()
            if started >= deadline:
                raise LiveHostError(f"Program browser did not answer CDP {method} in time.")
            ws.send(json.dumps({"id": request_id, "method": method, "params": params}))
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._log("cdpTimeout", method=method)
                    raise LiveHostError(f"Program browser did not answer CDP {method} in time.")
                try: message = json.loads(ws.recv(timeout=remaining))
                except TimeoutError as exc:
                    self._log("cdpTimeout", method=method)
                    raise LiveHostError(f"Program browser did not answer CDP {method} in time.") from exc
                except Exception as exc: raise LiveHostError("Program browser CDP connection failed.") from exc
                if message.get("id") == request_id:
                    duration_ms = (time.monotonic() - started) * 1000
                    if duration_ms > 250: self._log("cdpSlow", method=method, durationMs=round(duration_ms, 1))
                    if "error" in message: raise LiveHostError(f"CDP {method} failed: {message['error'].get('message', 'unknown error')}")
                    return message.get("result") or {}
                if "method" in message: self._route_event(message)
        finally:
            self._lock.release()

    def _route_event(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params") or {}
        if method == "Log.entryAdded": self._log("pageLog", entry=params.get("entry"))
        elif method == "Runtime.exceptionThrown": self._log("pageException", detail=params.get("exceptionDetails"))
        elif method == "Runtime.consoleAPICalled" and params.get("type") in ("error", "warning"):
            self._log("pageConsole", level=params.get("type"), args=params.get("args"))
        elif method == "Runtime.executionContextCreated":
            context = params.get("context") or {}
            aux = context.get("auxData") or {}
            if aux.get("isDefault") is True and isinstance(aux.get("frameId"), str) and isinstance(context.get("uniqueId"), str):
                self._contexts[aux["frameId"]] = {"id": context.get("id"), "uniqueId": context["uniqueId"], "origin": context.get("origin")}
        elif method == "Runtime.executionContextDestroyed":
            unique, context_id = params.get("executionContextUniqueId"), params.get("executionContextId")
            for frame, entry in list(self._contexts.items()):
                if (entry["uniqueId"] == unique) if unique is not None else (entry["id"] == context_id):
                    del self._contexts[frame]
        elif method == "Runtime.executionContextsCleared":
            self._contexts.clear()

    def main_context(self, frame_id: str) -> dict[str, Any] | None:
        """The frame's current default execution context as last reported by CDP events."""
        entry = self._contexts.get(frame_id)
        return dict(entry) if entry is not None else None

    def browser_call(self, method: str, deadline_s: float = 5.0, **params: Any) -> dict[str, Any]:
        """A call on the launched Chrome's browser target, on its own socket and lock."""
        with self._browser_lock:
            if self._stopped or not self._browser_ws_url:
                raise LiveHostError("Program browser target is unavailable.")
            deadline = time.monotonic() + deadline_s
            try:
                if self._browser_ws is None:
                    self._browser_ws = connect(self._browser_ws_url, open_timeout=max(.1, deadline - time.monotonic()), max_size=_CDP_MAX_MESSAGE_BYTES)
                self._browser_id += 1
                self._browser_ws.send(json.dumps({"id": self._browser_id, "method": method, "params": params}))
                return self._recv_matching(self._browser_ws, self._browser_id, deadline)
            except Exception as exc:
                ws, self._browser_ws = self._browser_ws, None
                if ws is not None:
                    try: ws.close()
                    except Exception: pass
                raise LiveHostError(f"Program browser target did not answer {method}.") from exc

    def evaluate(self, expression: str, deadline_s: float | None = None) -> Any:
        return self._evaluate(expression, deadline_s)

    def evaluate_in(self, context: str, expression: str, deadline_s: float | None = None) -> Any:
        """Evaluate only in the execution context with this `uniqueId`; a vanished context fails."""
        if not isinstance(context, str) or not context:
            raise LiveHostError("A unique execution context is required.")
        return self._evaluate(expression, deadline_s, uniqueContextId=context)

    def _evaluate(self, expression: str, deadline_s: float | None, **target: Any) -> Any:
        result = self.call("Runtime.evaluate", deadline_s=deadline_s, expression=expression, returnByValue=True, awaitPromise=False, **target)
        if result.get("exceptionDetails"): raise LiveHostError("Program browser evaluation failed.")
        return (result.get("result") or {}).get("value")

    def key(self, key: str, code: str, vk: int) -> None:
        # No nativeVirtualKeyCode: macOS Chrome routes it through AppKit key equivalents and stalls CDP.
        values = {"key": key, "code": code, "windowsVirtualKeyCode": vk}
        self.call("Input.dispatchKeyEvent", type="keyDown", **values)
        self.call("Input.dispatchKeyEvent", type="keyUp", **values)

    def click_stage(self) -> None:
        point = self.evaluate(
            "(()=>{var stage=document.getElementById('stage');if(!stage)return null;"
            "var r=stage.getBoundingClientRect();if(r.width<=0||r.height<=0)return null;"
            "return [r.left+r.width/2,r.top+r.height/2];})()"
        )
        if not isinstance(point, list) or len(point) != 2 or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            for value in point
        ):
            raise PlayerCommandRejected("Click advance is unavailable: the player stage has no usable centre.")
        values = {"x": point[0], "y": point[1], "button": "left", "clickCount": 1}
        self.call("Input.dispatchMouseEvent", type="mousePressed", **values)
        self.call("Input.dispatchMouseEvent", type="mouseReleased", **values)

    def goto(self, url: str) -> None:
        self.call("Page.navigate", url=url)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.evaluate("document.readyState") == "complete": return
            time.sleep(.05)
        raise LiveHostError("Program page did not finish loading.")

    def _blank_attached_target(self) -> None:
        """Reconnect a fresh, short-lived websocket to the same target and confirm it
        has navigated to about:blank, so a released attach never leaves the last
        program frame on air. Independent of `self.ws`/`_lock`: it never waits on
        a lock another thread may be holding inside `call()`."""
        if not self._target_ws_url:
            raise LiveHostError("No CDP target recorded to blank.")
        deadline = time.monotonic() + 3.0
        try:
            blank_ws = connect(self._target_ws_url, open_timeout=max(0.1, deadline - time.monotonic()))
        except Exception as exc:
            raise LiveHostError(f"Could not reconnect to blank the CDP target: {exc}") from exc
        try:
            blank_ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": self._blank_url}}))
            self._recv_matching(blank_ws, 1, deadline)
            blank_ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {"expression": "location.href", "returnByValue": True}}))
            result = self._recv_matching(blank_ws, 2, deadline)
            value = (result.get("result") or {}).get("value")
            if value != self._blank_url:
                raise LiveHostError(f"CDP target did not confirm {self._blank_url} (saw {value!r}).")
        finally:
            try: blank_ws.close()
            except Exception: pass

    @staticmethod
    def _recv_matching(ws: Any, request_id: int, deadline: float) -> dict[str, Any]:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LiveHostError("Timed out waiting for CDP response while blanking the target.")
            try: message = json.loads(ws.recv(timeout=remaining))
            except TimeoutError as exc:
                raise LiveHostError("Timed out waiting for CDP response while blanking the target.") from exc
            except Exception as exc:
                raise LiveHostError("CDP connection failed while blanking the target.") from exc
            if message.get("id") == request_id:
                if "error" in message:
                    raise LiveHostError(f"CDP call failed while blanking the target: {message['error'].get('message', 'unknown error')}")
                return message.get("result") or {}

    def stop(self) -> None:
        """Idempotent and thread-safe: never waits on `_lock`, so it stays prompt even
        while another thread is blocked inside `call()` on the same instance; closing
        the socket and terminating Chrome there make that blocked call fail promptly.
        Every teardown step is attempted even if an earlier one raises; a resource's
        reference is dropped only once it is actually released, so a raising stop can
        be retried and will only redo the work that is still outstanding.

        In attach mode the active websocket is closed first (unblocking any pending
        `call()`), and only then is the target blanked through a fresh connection;
        the transport is not considered released until blanking has actually
        succeeded, so a stop that fails to blank raises and a later stop retries
        only that step."""
        with self._stop_lock:
            self._stopped = True
            if self.attach_endpoint:
                if self.ws is None and self._target_ws_url is None:
                    self._blanked = True
                    return
                if self.ws is None and self._blanked: return
                errors: list[Exception] = []
                if self.ws is not None:
                    try: self.ws.close()
                    except Exception as exc: errors.append(exc)
                    else: self.ws = None
                if not self._blanked:
                    try:
                        self._blank_attached_target()
                        self._blanked = True
                    except Exception as exc:
                        errors.append(exc)
                if errors: raise LiveHostError("Program browser did not fully stop.")
                return
            if self.ws is None and self.proc is None and self._browser_ws is None: return
            errors: list[Exception] = []
            for name in ("ws", "_browser_ws"):
                ws = getattr(self, name)
                if ws is not None:
                    try: ws.close()
                    except Exception as exc: errors.append(exc)
                    else: setattr(self, name, None)
            proc = self.proc
            if proc is not None:
                if proc.poll() is None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        try:
                            proc.kill()
                            proc.wait(timeout=5)
                        except Exception as exc:
                            errors.append(exc)
                    except Exception as exc:
                        errors.append(exc)
                if proc.poll() is not None: self.proc = None
                else: errors.append(LiveHostError("Program browser process did not exit."))
            if self._stderr_file is not None:
                try: self._stderr_file.close()
                except Exception as exc: errors.append(exc)
                else: self._stderr_file = None
            if errors:
                raise LiveHostError("Program browser did not fully stop.")

    def detach(self) -> None:
        with self._stop_lock:
            self._stopped = True
            errors: list[Exception] = []
            for name in ("ws", "_browser_ws"):
                ws = getattr(self, name)
                if ws is not None:
                    try: ws.close()
                    except Exception as exc: errors.append(exc)
                    else: setattr(self, name, None)
            if errors:
                raise LiveHostError("Program browser transport did not detach cleanly.")


@dataclass(frozen=True)
class _GoToAutoplayResult:
    run_length: int | None
    run_kinds: list[Any] | None
    fired: bool | None
    deferred_reason: str | None


def _rate_warnings(report: list[dict[str, Any]], rate: int) -> list[str]:
    warnings = []
    for entry in report:
        fps = entry.get("fps")
        if fps is None or abs(fps - rate) <= rate * 0.002:
            continue
        shown = f"{fps:.3f}".rstrip("0").rstrip(".")
        warnings.append(f"{entry['asset']} is {shown} fps but the output is {rate} fps, so it will judder slightly. Re-export it at {rate} fps for smooth motion.")
    return warnings


class _ProgramGuard:
    def __init__(self, transport: ChromeCdp, context: str) -> None:
        self._transport = transport
        self._context = context
        self._key = "__obedProgramGuard_" + secrets.token_hex(8)
        self._last: dict[str, Any] | None = None
        self._baseline_frame_ms: float | None = None

    def _expr(self, operation: str) -> str:
        key = json.dumps(self._key)
        if operation == "begin":
            return (
                f'(function(k){{if(window[k])throw Error("guard exists");var s={{visibilityEvents:0,frames:0,gaps:[],media:{{}}}},'
                'live=true,last=null,raf=0;function visibility(){s.visibilityEvents++}'
                'function tick(t){if(last!==null)s.gaps.push(t-last);last=t;s.frames++;'
                'Array.prototype.forEach.call(document.querySelectorAll("video"),function(v,i){var id=v.id||v.currentSrc||("video-"+i),'
                'm=s.media[id]||(s.media[id]={id:id,playing:false,monotonic:true,lastTime:null,lastAdvanceAt:null,frameMs:null,maxStallMs:0});'
                'if(!v.paused&&v.readyState>=2){m.playing=true;var ct=+v.currentTime;if(m.lastTime!==null&&ct+1e-4<m.lastTime)m.monotonic=false;'
                'if(m.lastTime===null||ct>m.lastTime+1e-4){if(m.lastTime!==null){var fm=(ct-m.lastTime)*1000;m.frameMs=m.frameMs===null?fm:Math.min(m.frameMs,fm);'
                'if(m.lastAdvanceAt!==null&&m.frameMs>0)m.maxStallMs=Math.max(m.maxStallMs,t-m.lastAdvanceAt-m.frameMs)}m.lastTime=ct;m.lastAdvanceAt=t}'
                'else if(m.lastAdvanceAt!==null&&m.frameMs>0)m.maxStallMs=Math.max(m.maxStallMs,t-m.lastAdvanceAt-m.frameMs)}'
                'else if(m.playing)m.monotonic=false});'
                'if(live)raf=requestAnimationFrame(tick)}'
                'function snapshot(){var g=s.gaps.slice().sort(function(a,b){return a-b}),mid=g.length?g[Math.floor(g.length/2)]:null;'
                'return {visibilityEvents:s.visibilityEvents,frames:s.frames,baselineFrameMs:mid,maxRafGapMs:s.gaps.length?Math.max.apply(Math,s.gaps):null,'
                'media:Object.keys(s.media).map(function(id){var m=s.media[id];return {id:m.id,playing:m.playing,monotonic:m.monotonic,'
                'maxStallMs:Math.max(0,m.maxStallMs),frameMs:m.frameMs}})}}'
                'function finish(){live=false;cancelAnimationFrame(raf);document.removeEventListener("visibilitychange",visibility);var out=snapshot();delete window[k];return out}'
                'Object.defineProperty(window,k,{value:{snapshot:snapshot,finish:finish},configurable:true});'
                'document.addEventListener("visibilitychange",visibility);raf=requestAnimationFrame(tick);return true})(' + key + ')'
            )
        method = "finish" if operation == "finish" else "snapshot"
        return f'(function(k){{var g=window[k];return g&&g.{method}?g.{method}():null}})({key})'

    def begin(self) -> None:
        if self._transport.evaluate_in(self._context, self._expr("begin"), deadline_s=1.0) is not True:
            raise LiveHostError("Program guard could not start.")
        deadline = time.monotonic() + .25
        while time.monotonic() < deadline:
            value = self._transport.evaluate_in(self._context, self._expr("sample"), deadline_s=.5)
            self._last = value if isinstance(value, dict) else None
            if self._last is not None and self._last.get("frames", 0) >= 4:
                baseline = self._last.get("baselineFrameMs")
                max_gap = self._last.get("maxRafGapMs")
                if (
                    isinstance(baseline, (int, float)) and not isinstance(baseline, bool) and baseline > 0
                    and isinstance(max_gap, (int, float)) and not isinstance(max_gap, bool)
                    and max_gap <= 2 * baseline
                ):
                    self._baseline_frame_ms = float(baseline)
                return
            time.sleep(.01)

    def sample(self, phase: str) -> None:
        value = self._transport.evaluate_in(self._context, self._expr("sample"), deadline_s=1.0)
        if not isinstance(value, dict):
            raise LiveHostError(f"Program guard sample {phase} is unavailable.")
        self._last = value

    def finish(self) -> ProgramCheck:
        try:
            value = self._transport.evaluate_in(self._context, self._expr("finish"), deadline_s=1.0)
        except Exception as exc:
            return ProgramCheck(None, 0, None, None, (), str(exc))
        if not isinstance(value, dict):
            return ProgramCheck(None, 0, None, None, (), "program telemetry unavailable")
        visibility = value.get("visibilityEvents")
        baseline = self._baseline_frame_ms
        max_gap = value.get("maxRafGapMs")
        media_raw = value.get("media")
        if not isinstance(visibility, int) or isinstance(visibility, bool):
            return ProgramCheck(None, 0, None, None, (), "visibility telemetry unavailable")
        if not isinstance(baseline, (int, float)) or isinstance(baseline, bool) or baseline <= 0:
            return ProgramCheck(None, visibility, None, None, (), "program cadence baseline unavailable")
        if not isinstance(max_gap, (int, float)) or isinstance(max_gap, bool):
            return ProgramCheck(None, visibility, float(baseline), None, (), "program cadence unavailable")
        media = tuple(dict(item) for item in media_raw) if isinstance(media_raw, list) and all(isinstance(item, dict) for item in media_raw) else ()
        if media_raw is None or not isinstance(media_raw, list):
            return ProgramCheck(None, visibility, float(baseline), float(max_gap), (), "program media telemetry unavailable")
        playing = [item for item in media if item.get("playing") is True]
        media_known = all(
            item.get("monotonic") is True
            and isinstance(item.get("frameMs"), (int, float))
            and not isinstance(item.get("frameMs"), bool)
            and item["frameMs"] > 0
            and isinstance(item.get("maxStallMs"), (int, float))
            and not isinstance(item.get("maxStallMs"), bool)
            and item["maxStallMs"] <= item["frameMs"]
            for item in playing
        )
        ok = visibility == 0 and max_gap <= 2 * baseline and media_known
        reason = None if ok else "program cadence or media changed"
        return ProgramCheck(ok, visibility, float(baseline), float(max_gap), media, reason)


class LiveOutputHost:
    def __init__(self, export_root: Path, slides: list[dict[str, Any]], *, display_id: int | None = None, chrome_path: Path = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"), headless: bool = False, transport_factory: Callable[..., ChromeCdp] = ChromeCdp, server_factory: Callable[..., _AssetServer] = _AssetServer, resolver: Callable[[Path, str], Path] = safe_export_file, timeout_s: float = 12.0, attach_endpoint: str | None = _UNSET, attach_match: str | None = None, continuity: str = "auto", gl_replay: str = _UNSET, mm_opacity: str = _UNSET, bridge: str | None = None, output_rate: int | None = None, calibration: CalibrationAdapter | None = None, placement_mode: Literal["knowledge", "probe"] | None = None) -> None:
        if continuity not in ("auto", "off"):
            raise LiveHostError("Continuity must be auto or off.")
        if gl_replay is not _UNSET and gl_replay not in ("auto", "off"):
            raise LiveHostError("GL replay must be auto or off.")
        if mm_opacity is not _UNSET and mm_opacity not in ("auto", "off"):
            raise LiveHostError("Magic Move opacity must be auto or off.")
        if placement_mode is not None and placement_mode not in ("knowledge", "probe"):
            raise LiveHostError("Placement mode must be knowledge or probe.")
        self._continuity_preference = continuity
        self._bridge = bridge if bridge is not None else "obs-cdp"
        self._output_rate = output_rate
        self._gl_replay_request = gl_replay
        self._gl_replay_preference = "off"
        self._mm_opacity_request = mm_opacity
        self._mm_opacity_preference = "auto"
        self._mm_opacity_info: dict[str, str] | None = None
        self.export_root, self.slides = export_root, slides
        if attach_endpoint is _UNSET:
            attach_endpoint = os.environ.get(ATTACH_ENV) or None
        self._attach_endpoint = _validate_loopback_endpoint(attach_endpoint.strip()) if attach_endpoint and attach_endpoint.strip() else None
        self._managed_obs = self._attach_endpoint is not None and self._bridge == "obs-managed"
        self._calibration = calibration
        self._placement_mode: Literal["knowledge", "probe"] = placement_mode or (
            "probe" if calibration is not None and self._bridge == "obs-managed" else "knowledge"
        )
        self._attach_match = (attach_match if attach_match is not None else os.environ.get(ATTACH_MATCH_ENV)) or None
        if self._attach_endpoint:
            self.display: OutputDisplay | None = None
            self._viewport = {"width": 1920, "height": 1080}
        else:
            self.display = choose_display(display_id, headless=headless)
            self._viewport = {"width": self.display.width, "height": self.display.height}
        self.chrome_path, self.headless, self.transport_factory, self.server_factory, self.resolver, self.timeout_s = chrome_path, headless, transport_factory, server_factory, resolver, timeout_s
        self._transport: ChromeCdp | None = None
        self._server: _AssetServer | None = None
        self._original_by_player = {
            int(slide["playerIndex"]): int(slide["originalOrdinal"])
            for slide in slides
            if not slide.get("skipped") and isinstance(slide.get("playerIndex"), int)
        }
        self._stopped = False
        self._stop_lock = threading.Lock()
        self._profile: Path | None = None
        self._runtime_revision: int | None = None
        self._can_advance: bool | None = None
        self._can_go_to: bool | None = None
        self._canvas = {"width": 1920, "height": 1080}
        self._expected_scene_count: int | None = None
        self._logger: _SessionLogger | None = None
        self._log_path: Path | None = None
        self._last_logged_observation: tuple[Any, ...] | None = None
        self._advance_mode = "key"
        self._goto_autoplay_mode = "on"
        self._auto_play_run_length: int | None = None
        self._auto_play_run_kinds: list[Any] | None = None
        self._runtime_version_seen: int | None = None
        self._slide_number_showing = False
        self._last_observation: PlayerObservation | None = None
        self._last_goto_autoplay: _GoToAutoplayResult | None = None
        self._continuity_mode: str = "off"
        self._continuity_reason: str | None = None
        self._continuity_runtime_plan: dict[str, Any] | None = None
        self._continuity_scale: float | None = None
        self._continuity_not_carried: list[dict[str, Any]] = []
        self._gl_replay_mode = "off"
        self._gl_replay_reason: str | None = None
        self._gl_replay_script = ""
        self._codec_report: list[dict[str, Any]] = []
        self._codec_warnings: list[str] = []
        self._placement_token = ""
        self._placement_frame: str | None = None
        self._placement_origin: str | None = None
        self._placement_context: str | None = None
        self._placement_version_reason: str | None = "version-unavailable"
        self._placement_lock = threading.RLock()
        self._connection_generation = 0
        self._probe_future: Future[CalibrationResult] | None = None
        self._probe_thread: threading.Thread | None = None
        self._probe_run_id: str | None = None
        self._probe_context: str | None = None
        self._probe_manual = False
        self._probe_engine: EngineIdentity | None = None
        self._engine_identity: EngineIdentity | None = None
        self._probe_fingerprint: tuple[str, float, int, int] | None = None
        self._automatic_probe_key: tuple[EngineIdentity, int, str] | None = None
        self._lease_deadline_s: float | None = None
        self._renew_stop = threading.Event()
        self._renew_thread: threading.Thread | None = None
        self._reconnect_revoke_required = False
        self._player_busy = True
        self._placement: dict[str, Any] = {
            "state": "invalid", "grant": None, "reason": None, "at": None,
            "product": None, "gpuCompositing": None, "method": None,
            "probeId": None, "leaseMs": None, "leaseExpiresAt": None,
            "tone": {"observed": None, "applied": "identity"},
            "automaticProbesDisabled": False,
        }

    def _resolve_codecs(self) -> tuple[list[dict[str, Any]], list[str]]:
        """Codec of every movie the export's slides reference, independent of continuity:
        this must stay populated even when continuity is off or unsupported. A failure to
        probe never blocks the session -- an unreadable codec is just reported as such."""
        try:
            report = codec_report(self.export_root, self.slides, resolver=self.resolver, with_fps=self._output_rate is not None)
        except Exception:  # noqa: BLE001 - fail closed, never let codec probing crash the host
            return [], []
        attach = self._attach_endpoint is not None
        warnings = [
            f"{entry['asset']} ({_codec_display(entry)}) may not play in this output"
            for entry in report
            if not _codec_supported(entry["family"], attach=attach, headless=self.headless)
        ]
        return report, warnings

    def _resolve_continuity_static(self) -> tuple[str, str | None, dict[str, Any] | None]:
        """Resolve continuity mode from the export alone, before the browser starts.
        `pending` means a runtime plan was derived and must still be confirmed truthfully
        from the page (the stage gate check only the page can perform, once the player has
        laid the stage out)."""
        if self._continuity_preference == "off" or os.environ.get(CONTINUITY_ENV) == "off":
            return "off", None, None
        derived = None
        if self._gl_replay_preference == "auto":
            self._gl_replay_mode, self._gl_replay_reason, derived, self._gl_replay_script = self._resolve_gl_replay()
        if derived is None:
            derived = self._derive_runtime()
        if isinstance(derived, Unsupported):
            return "unsupported", derived.reason, None
        plan, runtime = derived
        codec_by_asset = {entry["asset"]: entry for entry in self._codec_report}
        attach = self._attach_endpoint is not None
        for movie in runtime["movies"].values():
            asset = movie["assetKeys"][0]
            entry = codec_by_asset.get(asset)
            family = entry["family"] if entry is not None else "other"
            if not _codec_supported(family, attach=attach, headless=self.headless):
                display = _codec_display(entry)
                if self._gl_replay_mode == "injected":
                    self._gl_replay_mode, self._gl_replay_reason, self._gl_replay_script = "unavailable", "continuity unsupported", ""
                return "unsupported", f"movie codec is not playable in this output: {asset} ({display})", None
        self._continuity_not_carried = not_carried(plan, self.slides)
        if self._attach_endpoint:
            runtime = {**runtime, "transparentBackground": True}
        return "pending", None, runtime

    def _derive_runtime(self, **kwargs: Any) -> tuple[ContinuityPlan, dict[str, Any]] | Unsupported:
        return derive_runtime(self.export_root, self.slides, resolver=self.resolver, **kwargs)

    def _resolve_gl_replay(self) -> tuple[str, str | None, tuple[ContinuityPlan, dict[str, Any]] | None, str]:
        """GL replay `(mode, reason, flag-on derivation, script)` for `auto`. The derivation
        is None unless the module is injected; the caller then derives exactly as the off path.
        External attach is refused; the managed OBS is qualified (OD-2)."""
        if self._attach_endpoint and not self._managed_obs:
            return "unavailable", "attach output not qualified", None, ""
        if CONTINUITY_VERSION < 5:
            return "unavailable", "continuity core predates GL replay", None, ""
        derived = self._derive_runtime(gl_replay=True)
        if isinstance(derived, Unsupported):
            return "unavailable", derived.reason, None, ""
        if not any(b.get("action") == "glReplay" for b in derived[1]["boundaries"]):
            return "notApplicable", None, None, ""
        script = gl_replay_script(derived[1])
        if not script:
            return "unavailable", "GL replay entry is not usable", None, ""
        return "injected", None, derived, script

    def _stage_gate_outcome(self, stage: Any) -> tuple[str, str | None, float | None]:
        """Fail-closed judgement of one stage-geometry reading against the authored canvas."""
        if not isinstance(stage, dict):
            return "unsupported", "stage is not the authored size", None
        offset_width, offset_height, rect = stage.get("offsetWidth"), stage.get("offsetHeight"), stage.get("rect")
        def numeric(value: Any) -> bool: return isinstance(value, (int, float)) and not isinstance(value, bool)
        if not (
            numeric(offset_width) and numeric(offset_height)
            and int(offset_width) == self._canvas["width"] and int(offset_height) == self._canvas["height"]
            and isinstance(rect, dict)
        ):
            return "unsupported", "stage is not the authored size", None
        width, height = rect.get("width"), rect.get("height")
        if not (numeric(width) and numeric(height) and width > 1 and height > 1):
            return "unsupported", "stage is not the authored size", None
        scale_x, scale_y = width / offset_width, height / offset_height
        if abs(scale_x - scale_y) > 0.001 * ((scale_x + scale_y) / 2):
            return "unsupported", "stage scale is non-uniform", None
        return "qualified", None, scale_x

    def _disable_continuity_runtime(self) -> bool:
        result = self._transport.evaluate(
            "(()=>{var p=window.__OBED_P2_PRESERVE__;if(p&&p.disable)p.disable();"
            "return !!(p&&p.disabled===true);})()"
        )
        return result is True

    def _resolve_continuity_pending(self) -> tuple[str, str | None, dict[str, Any] | None, float | None]:
        """Confirm the `pending` runtime plan once the page has run: the shared runtime
        must have installed, then the host's own JS gates the on-screen `#stage` against
        the authored canvas (poll: the player lays the stage out asynchronously, after
        `goto` returns). Any unsupported outcome that finds a preserve object already
        present disables it, even when it never reached `ready` (a core can install
        partial hooks/observers and then throw before setting `ready`), so a half- or
        never-qualified continuity session never plays silently."""
        deadline = time.monotonic() + self.timeout_s
        readback = self._transport.evaluate(_CONTINUITY_STAGE_GATE_EXPR)
        ready = isinstance(readback, dict) and readback.get("ready") is True
        present = isinstance(readback, dict) and readback.get("present") is True
        stage = readback.get("stage") if isinstance(readback, dict) else None
        if not ready:
            if present and not self._disable_continuity_runtime():
                raise LiveHostError("Continuity runtime could not be confirmed disabled after an unsupported stage gate.")
            return "unsupported", "runtime failed to install", stage, None
        mode, reason, scale = self._stage_gate_outcome(stage)
        while mode != "qualified" and time.monotonic() < deadline:
            time.sleep(.05)
            readback = self._transport.evaluate(_CONTINUITY_STAGE_GATE_EXPR)
            stage = readback.get("stage") if isinstance(readback, dict) else None
            mode, reason, scale = self._stage_gate_outcome(stage)
        if mode != "qualified" and not self._disable_continuity_runtime():
            raise LiveHostError("Continuity runtime could not be confirmed disabled after an unsupported stage gate.")
        return mode, reason, stage, scale

    def _continuity_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"mode": self._continuity_mode, "version": CONTINUITY_VERSION, "sha256": js_sha256()}
        if self._continuity_reason is not None:
            info["reason"] = self._continuity_reason
        if self._continuity_mode == "qualified" and self._continuity_scale is not None:
            info["scale"] = round(self._continuity_scale, 4)
        if self._continuity_not_carried:
            info["notCarried"] = [dict(entry) for entry in self._continuity_not_carried]
        info["glReplay"] = self._gl_replay_info()
        return info

    def _gl_replay_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"mode": self._gl_replay_mode}
        if self._gl_replay_reason is not None:
            info["reason"] = self._gl_replay_reason
        info["version"] = GL_REPLAY_VERSION
        info["sha256"] = gl_replay_js_sha256()
        return info

    @property
    def output(self) -> dict[str, Any]:
        """Detected physical output geometry, available before browser startup."""
        if self._attach_endpoint:
            result: dict[str, Any] = {
                "transport": "fill-key", "alpha": True, "audio": False, "bridge": self._bridge,
                "viewport": dict(self._viewport), "canvas": dict(self._canvas),
                "width": self._viewport["width"], "height": self._viewport["height"],
            }
        else:
            result = {
                **self.display.as_output(),
                "viewport": dict(self._viewport),
                "canvas": dict(self._canvas),
                "width": self._viewport["width"],
                "height": self._viewport["height"],
            }
        if self._log_path is not None:
            result["logPath"] = str(self._log_path)
        if self._mm_opacity_info is not None:
            result["mmOpacity"] = dict(self._mm_opacity_info)
        result["continuity"] = self._continuity_info()
        result["placement"] = dict(self._placement)
        result["codecs"] = list(self._codec_report)
        result["codecWarnings"] = list(self._codec_warnings)
        if self._output_rate is not None:
            result["rateWarnings"] = _rate_warnings(self._codec_report, self._output_rate)
        return result

    def start(self) -> PlayerObservation:
        if self._stopped:
            raise LiveHostError("Program player has been stopped.")
        if self._transport:
            return self.observe()
        self._advance_mode = os.environ.get(ADVANCE_ENV, "key").strip().lower()
        if self._advance_mode not in ("key", "click"):
            raise LiveHostError("OBED_LIVE_ADVANCE must be key or click.")
        if self._gl_replay_request is not _UNSET:
            self._gl_replay_preference = self._gl_replay_request
        else:
            env_gl_replay = os.environ.get(GL_REPLAY_ENV, "").strip().lower()
            if env_gl_replay not in ("", "off", "auto"):
                raise LiveHostError("OBED_LIVE_GL_REPLAY must be off or auto.")
            self._gl_replay_preference = env_gl_replay or ("auto" if self._managed_obs else "off")
        if self._mm_opacity_request is not _UNSET:
            self._mm_opacity_preference = self._mm_opacity_request
        else:
            env_mm_opacity = os.environ.get(MM_OPACITY_ENV, "").strip().lower()
            if env_mm_opacity not in ("", "off", "auto"):
                raise LiveHostError("OBED_LIVE_MM_OPACITY must be off or auto.")
            self._mm_opacity_preference = env_mm_opacity or "auto"
        self._goto_autoplay_mode = "off" if os.environ.get(GOTO_AUTOPLAY_ENV, "").strip().lower() == "off" else "on"
        self._log_path = _new_log_path()
        self._logger = _SessionLogger(self._log_path)
        self._logger.log(
            "start", mode="attach" if self._attach_endpoint else "hdmi",
            exportRoot=str(self.export_root), runtimeVersion=RUNTIME_VERSION,
            display=(self.display.display_id if self.display else None),
            attachEndpoint=self._attach_endpoint, attachMatch=self._attach_match,
            headless=self.headless, advanceMode=self._advance_mode,
            goToAutoplayMode=self._goto_autoplay_mode, glReplayPreference=self._gl_replay_preference,
            mmOpacityPreference=self._mm_opacity_preference,
        )
        try:
            self._validate_export()
            self._expected_scene_count = self._authored_scene_count()
            self._codec_report, self._codec_warnings = self._resolve_codecs()
            self._logger.log("codecs", report=self._codec_report, warnings=self._codec_warnings)
            self._continuity_mode, self._continuity_reason, self._continuity_runtime_plan = self._resolve_continuity_static()
            player = self.resolver(self.export_root, "assets/player/main.js").read_bytes()
            mm_opacity_on = self._mm_opacity_preference == "auto"
            try: patched = patch_player(player, mm_opacity=mm_opacity_on)
            except LiveRuntimeUnsupported as exc: raise LiveHostError(str(exc)) from exc
            self._mm_opacity_info = {"mode": "on" if mm_opacity_on else "off", "sha256": hashlib.sha256(patched).hexdigest()}
            self._profile = Path(tempfile.mkdtemp(prefix="obed-live-chrome-"))
            continuity_script = (
                _continuity_scripts(self._continuity_runtime_plan, self._canvas) + self._gl_replay_script
                if self._continuity_runtime_plan is not None
                else ""
            )
            self._server = self.server_factory(
                self.export_root, patched, self.resolver, alpha=bool(self._attach_endpoint),
                continuity_script=continuity_script,
            )
            url = self._server.start()
            self._transport = self.transport_factory(
                self.chrome_path, self._profile, self.display, headless=self.headless,
                attach_endpoint=self._attach_endpoint, attach_match=self._attach_match,
                logger=self._logger, log_path=self._log_path,
            )
            self._transport.start()
            self._connection_generation += 1
            try: version = self._transport.call("Browser.getVersion")
            except Exception: version = None
            self._logger.log("browserVersion", result=version)
            self._install_placement_channel(version, url)
            self._transport.goto(url)
            stage_geometry: dict[str, Any] | None = None
            if self._continuity_mode == "pending":
                self._continuity_mode, self._continuity_reason, stage_geometry, self._continuity_scale = (
                    self._resolve_continuity_pending()
                )
                if self._continuity_mode != "qualified" and self._gl_replay_mode == "injected":
                    self._gl_replay_mode, self._gl_replay_reason, self._gl_replay_script = "unavailable", "continuity unsupported", ""
            self._logger.log(
                "continuity", mode=self._continuity_mode, reason=self._continuity_reason,
                runtimePlan=self._continuity_runtime_plan, stage=stage_geometry, scale=self._continuity_scale,
                notCarried=self._continuity_not_carried, glReplay=self._gl_replay_info(),
            )
            observed = self._wait_settled()
            try: dpr = self._transport.evaluate("window.devicePixelRatio")
            except Exception: dpr = None
            self._logger.log("viewport", viewport=dict(self._viewport), devicePixelRatio=dpr)
            return observed
        except Exception:
            try: self.stop()
            except Exception: pass
            raise

    def _install_placement_channel(self, version: Any, url: str) -> None:
        self._placement_token = secrets.token_hex(16)
        product = version.get("product") if isinstance(version, dict) else None
        self._placement["product"] = product if isinstance(product, str) else None
        self._placement["method"] = self._placement_mode
        if isinstance(product, str):
            match = re.fullmatch(r"(?:Headless)?Chrome/(\d+)\.[\d.]+", product)
            self._placement_version_reason = None if match and int(match.group(1)) in QUALIFIED_SNAP_MAJORS else "unqualified-version"
        try:
            self._transport.call(
                "Page.addScriptToEvaluateOnNewDocument",
                source=placement_init_script(self._placement_token, mode=self._placement_mode),
            )
            if not self._attach_endpoint or self._placement_mode == "probe":
                frame = self._transport.call("Page.getFrameTree")["frameTree"]["frame"]["id"]
                if not isinstance(frame, str): raise LiveHostError("Program main frame is unreadable.")
                self._placement_frame = frame
        except Exception as exc:
            if self._attach_endpoint and self._placement_mode != "probe":
                self._logger.log("placementChannel", error=str(exc))
            else:
                self._set_placement(None, "channel-compromised", state="invalid")
                return
        if self._attach_endpoint and self._placement_mode != "probe":
            self._set_placement(None, "attached", state="invalid")
        elif self._placement_mode == "probe":
            reason = "not-calibrated" if self._calibration is not None else "unsupported"
            self._set_placement(None, reason, state="invalid")
        parts = urlsplit(url)
        self._placement_origin = f"{parts.scheme}://{parts.netloc}"

    def _set_placement(
        self,
        grant: str | None,
        reason: str | None,
        gpu: str | None = None,
        *,
        state: Literal["invalid", "probing", "valid"] | None = None,
        tone: str | None | object = _TONE_UNSET,
        lease_ms: int | None = None,
    ) -> None:
        with self._placement_lock:
            resolved_state = state or ("valid" if grant is not None else "invalid")
            self._placement.update(
                state=resolved_state,
                grant=grant if resolved_state == "valid" else None,
                reason=reason,
                gpuCompositing=gpu,
                at=time.time(),
                leaseMs=lease_ms if resolved_state == "valid" else None,
                leaseExpiresAt=(time.time() + lease_ms / 1000) if resolved_state == "valid" and lease_ms is not None else None,
            )
            if tone is not _TONE_UNSET:
                self._placement["tone"] = {"observed": tone, "applied": "identity"}
            if resolved_state != "valid":
                self._lease_deadline_s = None
            elif lease_ms is not None:
                self._lease_deadline_s = time.monotonic() + lease_ms / 1000
        if self._logger is not None:
            self._logger.log("placement", **self._placement)

    def _gpu_compositing(self) -> str | None:
        try: info = self._require_transport().browser_call("SystemInfo.getInfo")
        except Exception: return None
        gpu = info.get("gpu") if isinstance(info, dict) else None
        status = gpu.get("featureStatus") if isinstance(gpu, dict) else None
        value = status.get("gpu_compositing") if isinstance(status, dict) else None
        return value if isinstance(value, str) else None

    def _revoke_placement(self, context: str) -> bool:
        try:
            return self._require_transport().evaluate_in(
                context, _placement_set_expr(self._placement_token, "invalid"), deadline_s=1.0,
            ) == "invalid"
        except LiveHostError:
            return False

    def _sync_placement(self) -> None:
        if self._placement["reason"] == "channel-compromised":
            return
        if self._placement_mode == "probe":
            self._sync_probe_placement()
        else:
            self._sync_knowledge_placement()

    def _reconnect_managed_transport(self) -> bool:
        if not self._managed_obs or self._stopped or self._attach_endpoint is None:
            return False
        old = self._transport
        if old is None:
            return False
        self._cancel_probe("disconnected")
        try:
            if hasattr(old, "detach"):
                old.detach()
            else:
                old.stop()
        except Exception as exc:
            if self._logger is not None:
                self._logger.log("placementReconnectDetach", error=str(exc))
        self._transport = None
        replacement: ChromeCdp | None = None
        try:
            replacement = self.transport_factory(
                self.chrome_path,
                self._profile,
                self.display,
                headless=self.headless,
                attach_endpoint=self._attach_endpoint,
                attach_match=self._attach_match,
                logger=self._logger,
                log_path=self._log_path,
            )
            replacement.start()
            try: version = replacement.call("Browser.getVersion", deadline_s=2.0)
            except Exception: version = None
            replacement.call(
                "Page.addScriptToEvaluateOnNewDocument",
                deadline_s=2.0,
                source=placement_init_script(self._placement_token, mode="probe"),
            )
            frame = replacement.call("Page.getFrameTree", deadline_s=2.0)["frameTree"]["frame"]["id"]
            entry = replacement.main_context(frame) if isinstance(frame, str) else None
            context = entry.get("uniqueId") if isinstance(entry, dict) and entry.get("origin") == self._placement_origin else None
            if not isinstance(context, str):
                raise LiveHostError("Managed program context is unavailable after reconnect.")
            self._transport = replacement
            self._placement_frame = frame
            self._placement_context = context
            self._connection_generation += 1
            product = version.get("product") if isinstance(version, dict) else None
            self._placement["product"] = product if isinstance(product, str) else None
            if not self._revoke_placement(context):
                self._set_placement(None, "channel-compromised", state="invalid")
                try: replacement.evaluate("window.__obedOutput.hide()", deadline_s=1.0)
                except Exception: pass
                return False
            self._reconnect_revoke_required = False
            self._set_placement(None, "disconnected", state="invalid")
            if self._logger is not None:
                self._logger.log("placementReconnect", connectionGeneration=self._connection_generation, context=context)
            return True
        except Exception as exc:
            if replacement is not None:
                try:
                    if hasattr(replacement, "detach"):
                        replacement.detach()
                    else:
                        replacement.stop()
                except Exception: pass
            self._transport = None
            self._set_placement(None, "disconnected", state="invalid")
            if self._logger is not None:
                self._logger.log("placementReconnect", error=str(exc))
            return False

    def _program_context(self) -> str | None:
        if self._placement_frame is None:
            return None
        entry = self._require_transport().main_context(self._placement_frame)
        if entry is None or entry.get("origin") != self._placement_origin:
            return None
        context = entry.get("uniqueId")
        return context if isinstance(context, str) else None

    def _sync_knowledge_placement(self) -> None:
        if self._attach_endpoint or self._placement_frame is None:
            return
        transport = self._require_transport()
        context = self._program_context()
        if context != self._placement_context:
            self._placement_context = None
            with self._placement_lock:
                self._placement["grant"] = None
                self._placement["state"] = "invalid"
        if context is None:
            return
        if context == self._placement_context:
            if self._placement["grant"] == "snap":
                gpu = self._gpu_compositing()
                if gpu != "enabled":
                    self._revoke_placement(context)
                    self._set_placement(None, "revoked-fingerprint", gpu)
            return
        self._placement_context = context
        reason, gpu = self._placement_version_reason, None
        if reason is None:
            gpu = self._gpu_compositing()
            if gpu != "enabled": reason = "software-compositing"
        if reason is not None:
            self._revoke_placement(context)
            self._set_placement(None, reason, gpu)
            return
        committed = None
        try:
            trip = transport.evaluate_in(context, _placement_round_trip_expr(self._placement_token, mode="knowledge"))
            if trip == _PLACEMENT_ROUND_TRIP:
                committed = transport.evaluate_in(context, _placement_set_expr(self._placement_token, "snap"))
        except LiveHostError:
            self._placement_context = None
            return
        if committed != "snap":
            self._revoke_placement(context)
            self._set_placement(None, "channel-compromised", gpu)
            try: transport.evaluate("window.__obedOutput.hide()")
            except LiveHostError: pass
            return
        self._set_placement("snap", "granted", gpu)

    def _probe_fingerprint_read(self, context: str, *, deadline_s: float = 1.0) -> tuple[str, float, int, int] | None:
        try:
            value = self._require_transport().evaluate_in(
                context, "[navigator.userAgent,window.devicePixelRatio,window.innerWidth,window.innerHeight]", deadline_s=deadline_s,
            )
        except Exception:
            return None
        if (
            not isinstance(value, list) or len(value) != 4 or not isinstance(value[0], str)
            or not isinstance(value[1], (int, float)) or isinstance(value[1], bool)
            or not all(isinstance(item, int) and not isinstance(item, bool) and item > 0 for item in value[2:])
        ):
            return None
        return value[0], float(value[1]), value[2], value[3]

    def _cancel_probe(self, reason: str) -> None:
        with self._placement_lock:
            run_id = self._probe_run_id
        if run_id is not None and self._calibration is not None:
            try: self._calibration.cancel(run_id, timeout_s=0)
            except Exception: pass
        self._set_placement(None, reason, state="invalid")

    def _sync_probe_placement(self) -> None:
        if self._calibration is None or not self._managed_obs:
            return
        context = self._program_context()
        try: engine = self._calibration.identity()
        except Exception: engine = None
        if engine != self._engine_identity:
            if self._engine_identity is not None:
                if context is not None:
                    self._reconnect_revoke_required = not self._revoke_placement(context)
                self._cancel_probe("disconnected" if engine is None else "revoked-fingerprint")
            self._engine_identity = engine
            with self._placement_lock:
                self._placement["automaticProbesDisabled"] = False
        if context != self._placement_context:
            old_context = self._placement_context
            if old_context is not None:
                self._revoke_placement(old_context)
            self._placement_context = context
            self._reconnect_revoke_required = False
            if self._probe_run_id is not None:
                self._cancel_probe("stale-result")
            elif self._placement["grant"] is not None:
                self._set_placement(None, "revoked-fingerprint", state="invalid")
        if context is None or engine is None:
            if self._placement["state"] == "valid":
                self._set_placement(None, "disconnected", state="invalid")
            return
        if self._reconnect_revoke_required:
            if not self._revoke_placement(context):
                self._set_placement(None, "disconnected", state="invalid")
                return
            self._reconnect_revoke_required = False
        if self._placement["state"] == "valid":
            fingerprint = self._probe_fingerprint_read(context)
            if fingerprint != self._probe_fingerprint:
                if not self._revoke_placement(context):
                    self._reconnect_revoke_required = True
                self._automatic_probe_key = None
                self._set_placement(None, "revoked-fingerprint", state="invalid")
            return
        if self._probe_run_id is not None:
            if self._probe_future is None and not self._player_busy:
                self._start_scheduled_probe()
            return
        if self._placement["automaticProbesDisabled"]:
            return
        if self._automatic_probe_key == (engine, self._connection_generation, context):
            return
        self._schedule_probe(context, engine, manual=False)

    def _schedule_probe(self, context: str, engine: EngineIdentity, *, manual: bool) -> None:
        if self._probe_run_id is not None:
            raise PlayerCommandRejected("Calibration is already running.")
        run_id = secrets.token_hex(16)
        self._probe_run_id = run_id
        self._probe_context = context
        self._probe_manual = manual
        self._probe_engine = engine
        if not manual:
            self._automatic_probe_key = (engine, self._connection_generation, context)
        self._placement["probeId"] = run_id
        self._revoke_placement(context)
        if self._player_busy:
            self._set_placement(None, "waiting-for-transition", state="probing")
            return
        self._start_scheduled_probe()

    def _start_scheduled_probe(self) -> None:
        run_id, context, engine = self._probe_run_id, self._probe_context, self._probe_engine
        if run_id is None or context is None or engine is None or self._probe_future is not None:
            return
        if self._server is None or not hasattr(self._server, "set_probe_run"):
            self._finish_probe_state("probe-failed")
            return
        fingerprint = self._probe_fingerprint_read(context)
        if fingerprint is None or fingerprint[1:] != (1.0, 1920, 1080):
            self._finish_probe_state("revoked-fingerprint")
            return
        spec = ProbeSpec(run_id, 1920, 1080, (self._output_rate or 25) * 2, 1.0)
        try:
            url = self._server.set_probe_run(spec)
            if not isinstance(url, str):
                raise LiveHostError("Probe URL is unavailable.")
            target_id = self._attach_match or getattr(self._transport, "target_id", None)
            if not isinstance(target_id, str) or not target_id:
                raise LiveHostError("Managed program target is unavailable.")
            request = CalibrationRequest(
                spec, url, engine, target_id, context, self._connection_generation,
            )
            guard = _ProgramGuard(self._require_transport(), context)
            future = self._calibration.start(request, measure=self._measure_probe, guard=guard)
        except Exception as exc:
            if self._logger is not None: self._logger.log("placementProbeStart", probeId=run_id, error=str(exc))
            try: self._server.set_probe_run(None)
            except Exception: pass
            self._finish_probe_state("probe-failed")
            return
        self._probe_fingerprint = fingerprint
        self._probe_future = future
        self._set_placement(None, "calibrating", state="probing")
        self._probe_thread = threading.Thread(
            target=self._await_probe_result,
            args=(run_id, request, future),
            name="obed-placement-probe",
            daemon=True,
        )
        self._probe_thread.start()

    def _finish_probe_state(self, reason: str, *, suppress: bool = False, tone: str | None | object = _TONE_UNSET) -> None:
        with self._placement_lock:
            probe_id = self._probe_run_id
            self._probe_run_id = None
            self._probe_context = None
            self._probe_engine = None
            self._probe_future = None
            self._probe_manual = False
            if suppress:
                self._placement["automaticProbesDisabled"] = True
        if self._logger is not None:
            self._logger.log("placementProbeRejected", probeId=probe_id, reason=reason, suppressed=suppress)
        self._set_placement(None, reason, state="invalid", tone=tone)

    @staticmethod
    def _probe_geometry(value: Any) -> PoseGeometry:
        if not isinstance(value, dict):
            raise LiveHostError("Probe geometry is unavailable.")
        pose = value.get("pose")
        rect = value.get("rect")
        content = value.get("contentBox")
        box = value.get("box")
        snap_dy, frac_dy = value.get("snapDy"), value.get("fracDy")
        if pose not in (0, 1):
            raise LiveHostError("Probe pose is invalid.")
        if not all(isinstance(items, list) and len(items) == 4 for items in (rect, content, box)):
            raise LiveHostError("Probe bounds are invalid.")
        if not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in rect + content):
            raise LiveHostError("Probe bounds are invalid.")
        if not all(isinstance(item, int) and not isinstance(item, bool) for item in box):
            raise LiveHostError("Probe pixel bounds are invalid.")
        if not isinstance(snap_dy, int) or isinstance(snap_dy, bool) or not isinstance(frac_dy, int) or isinstance(frac_dy, bool):
            raise LiveHostError("Probe candidate offsets are invalid.")
        geometry = PoseGeometry(
            pose,
            tuple(float(item) for item in rect),
            tuple(float(item) for item in content),
            tuple(box),
            snap_dy,
            frac_dy,
        )
        left, top, width, height = geometry.box
        if left < 0 or top < 0 or width < 1 or height < 1 or left + width > 1920 or top + height + max(snap_dy, frac_dy) > 1080:
            raise LiveHostError("Probe bounds exceed the source canvas.")
        return geometry

    @staticmethod
    def _probe_nonce_matches(png: bytes, nonce: str) -> bool:
        try:
            with Image.open(io.BytesIO(png)) as source:
                image = source.convert("RGBA")
        except Exception:
            return False
        if image.size != (1920, 1080):
            return False
        bits = f"{int(nonce, 16):0128b}"
        pixels = image.load()
        for index, bit in enumerate(bits):
            x0, y0 = 1600 + (index % 16) * 8, 16 + (index // 16) * 8
            values = [pixels[x, y] for x in (x0 + 3, x0 + 4) for y in (y0 + 3, y0 + 4)]
            if any(pixel[3] != 255 for pixel in values):
                return False
            if bit == "0" and any(max(pixel[:3]) > 32 for pixel in values):
                return False
            if bit == "1" and any(min(pixel[:3]) < 223 for pixel in values):
                return False
        return True

    @staticmethod
    def _probe_snapshot(transport: ChromeCdp, context: str, *, deadline_s: float) -> dict[str, Any]:
        value = transport.evaluate_in(
            context,
            "window.__obedProbe&&window.__obedProbe.snapshot?window.__obedProbe.snapshot():null",
            deadline_s=deadline_s,
        )
        if not isinstance(value, dict):
            raise LiveHostError("Probe page snapshot is unavailable.")
        return value

    def _measure_probe(self, channel: CalibrationIO) -> ClassifierInput:
        deadline = min(channel.deadline_s, time.monotonic() + _PROBE_MEASURE_S)
        transport = self.transport_factory(
            self.chrome_path,
            self._profile or Path(tempfile.gettempdir()),
            None,
            headless=False,
            attach_endpoint=channel.cdp_endpoint,
            attach_match=channel.request.url,
            logger=self._logger,
            log_path=self._log_path,
        )
        captures: list[ProbeCapture] = []
        geometries: dict[int, PoseGeometry] = {}
        identity: ProbeIdentity | None = None
        last_capture_start = 0.0
        try:
            transport.start()
            target_id = getattr(transport, "target_id", None)
            if not isinstance(target_id, str):
                raise LiveHostError("Probe target identity is unavailable.")
            target_url = getattr(transport, "target_url", channel.request.url)
            if target_url != channel.request.url:
                raise LiveHostError("Probe target URL does not match the registered run.")
            frame = transport.call("Page.getFrameTree", deadline_s=min(1.0, deadline - time.monotonic()))["frameTree"]["frame"]["id"]
            entry = transport.main_context(frame) if isinstance(frame, str) else None
            context = entry.get("uniqueId") if isinstance(entry, dict) else None
            if not isinstance(context, str):
                raise LiveHostError("Probe context is unavailable.")
            sequence = 0

            def capture(phase: str, pose: int | None) -> tuple[ProbeCapture, dict[str, Any]]:
                nonlocal identity, last_capture_start, sequence
                channel.check_current()
                if channel.cancel_event.is_set() or time.monotonic() >= deadline:
                    raise LiveHostError("Probe measurement was cancelled or timed out.")
                sequence += 1
                nonce = secrets.token_hex(16)
                command = json.dumps({"runId": channel.request.spec.run_id, "sequence": sequence, "nonce": nonce, "phase": phase, "pose": pose})
                accepted = transport.evaluate_in(
                    context,
                    f"window.__obedProbe&&window.__obedProbe.command({command})",
                    deadline_s=min(1.0, deadline - time.monotonic()),
                )
                if accepted is not True:
                    raise LiveHostError("Probe page rejected a capture command.")
                observed = None
                while time.monotonic() < deadline:
                    channel.check_current()
                    snapshot = self._probe_snapshot(transport, context, deadline_s=min(.5, deadline - time.monotonic()))
                    if snapshot.get("runId") == channel.request.spec.run_id and snapshot.get("paintedSequence") == sequence:
                        observed = time.monotonic()
                        break
                    if channel.cancel_event.wait(.01):
                        raise LiveHostError("Probe measurement was cancelled.")
                if observed is None:
                    raise LiveHostError("Probe page did not paint in time.")
                wait_s = max(_PROBE_CAPTURE_SETTLE_S - (time.monotonic() - observed), _PROBE_CAPTURE_INTERVAL_S - (time.monotonic() - last_capture_start), 0)
                if channel.cancel_event.wait(wait_s):
                    raise LiveHostError("Probe measurement was cancelled.")
                started = time.monotonic()
                if started >= deadline:
                    raise LiveHostError("Probe measurement timed out.")
                png = channel.capture_png(timeout_s=min(2.0, deadline - started))
                finished = time.monotonic()
                last_capture_start = started
                if finished > deadline or started - observed < _PROBE_CAPTURE_SETTLE_S or not self._probe_nonce_matches(png, nonce):
                    raise LiveHostError("Probe capture freshness could not be verified.")
                if snapshot.get("sequence") != sequence or snapshot.get("phase") != phase or snapshot.get("pose") != pose:
                    raise LiveHostError("Probe capture state does not match its command.")
                ua, dpr = snapshot.get("ua"), snapshot.get("dpr")
                if not isinstance(ua, str) or dpr != 1:
                    raise LiveHostError("Probe fingerprint is unsupported.")
                current_identity = ProbeIdentity(
                    channel.request.spec.run_id,
                    channel.source_uuid,
                    target_id,
                    context,
                    channel.request.connection_generation,
                    ua,
                    float(dpr),
                )
                if identity is None:
                    identity = current_identity
                elif current_identity != identity:
                    raise LiveHostError("Probe identity changed during measurement.")
                item = ProbeCapture(current_identity, sequence, nonce, phase, pose, png, observed, started, finished)
                captures.append(item)
                return item, snapshot

            freshness: list[ProbeCapture] = []
            for _ in range(3):
                item, _snapshot = capture("motion", None)
                freshness.append(item)
            ready_state: int | None = None
            video_size: tuple[int, int] | None = None
            color_tuple: tuple[str, str, str, bool] | None = None
            still: list[ProbeCapture] = []
            for pose in (0, 1):
                for _ in range(2):
                    item, snapshot = capture("pattern", pose)
                    still.append(item)
                    geometry = self._probe_geometry(snapshot.get("geometry"))
                    if geometry.pose != pose:
                        raise LiveHostError("Probe pose geometry changed.")
                    if pose in geometries and geometries[pose] != geometry:
                        raise LiveHostError("Probe pose geometry is unstable.")
                    geometries[pose] = geometry
                    candidate_ready = snapshot.get("readyState")
                    size = snapshot.get("videoSize")
                    colors = snapshot.get("colorTuple")
                    if not isinstance(candidate_ready, int) or candidate_ready < 2:
                        raise LiveHostError("Probe video is not decoded.")
                    if not isinstance(size, list) or len(size) != 2 or not all(isinstance(item, int) for item in size):
                        raise LiveHostError("Probe video dimensions are unavailable.")
                    if not isinstance(colors, list) or len(colors) != 4 or not all(isinstance(item, str) for item in colors[:3]) or not isinstance(colors[3], bool):
                        raise LiveHostError("Probe color tuple is unavailable.")
                    current_size = (size[0], size[1])
                    current_colors = (colors[0], colors[1], colors[2], colors[3])
                    if ready_state is not None and (candidate_ready != ready_state or current_size != video_size or current_colors != color_tuple):
                        raise LiveHostError("Probe decode state changed.")
                    ready_state, video_size, color_tuple = candidate_ready, current_size, current_colors
            if identity is None or ready_state is None or video_size is None or color_tuple is None or video_size != (1920, 540):
                raise LiveHostError("Probe evidence is incomplete.")
            assets = load_probe_assets()
            return ClassifierInput(
                channel.request.spec,
                (assets.manifest_sha256, assets.pattern.sha256, assets.motion.sha256),
                identity,
                ready_state,
                video_size,
                color_tuple,
                tuple(freshness),
                tuple(geometries[index] for index in (0, 1)),
                tuple(still),
            )
        finally:
            try: transport.stop()
            except Exception: pass

    def _await_probe_result(self, run_id: str, request: CalibrationRequest, future: Future[CalibrationResult]) -> None:
        try:
            result = future.result()
        except Exception as exc:
            if self._logger is not None: self._logger.log("placementProbe", probeId=run_id, error=str(exc))
            result = None
        try:
            try:
                self._complete_probe(run_id, request, result)
            except Exception as exc:
                if self._logger is not None: self._logger.log("placementProbe", probeId=run_id, error=str(exc))
                with self._placement_lock:
                    current = run_id == self._probe_run_id and not self._stopped
                if current:
                    self._finish_probe_state("probe-failed")
        finally:
            server = self._server
            if server is not None and hasattr(server, "set_probe_run"):
                try: server.set_probe_run(None)
                except Exception: pass

    def _complete_probe(self, run_id: str, request: CalibrationRequest, result: CalibrationResult | None) -> None:
        with self._placement_lock:
            if self._stopped or run_id != self._probe_run_id:
                return
        if result is None:
            self._finish_probe_state("probe-failed")
            return
        if result.request != request:
            self._finish_probe_state("stale-result")
            return
        if any("cancel" in item.lower() for item in result.errors):
            self._finish_probe_state("cancelled")
            return
        if result.evidence is None:
            self._finish_probe_state("probe-failed")
            return
        if result.program is None or result.program.ok is not True:
            self._finish_probe_state("program-disturbed" if result.program is not None and result.program.ok is False else "probe-failed", suppress=result.program is not None and result.program.ok is False)
            return
        if not result.isolation_ok:
            self._finish_probe_state("isolation-failed", suppress=True)
            return
        if not result.cleanup_verified or not result.restored:
            self._finish_probe_state("cleanup-failed")
            return
        if result.persistence is not None and result.persistence.authoritative and result.persistence.ok is not True:
            self._finish_probe_state("persistence-failed")
            return
        if result.errors:
            self._finish_probe_state("probe-failed")
            return
        try: classified = classify_probe(result.evidence)
        except Exception as exc:
            if self._logger is not None: self._logger.log("placementClassifier", probeId=run_id, error=str(exc))
            self._finish_probe_state("probe-failed")
            return
        if self._logger is not None:
            self._logger.log(
                "placementClassifier",
                probeId=run_id,
                verdict=classified.verdict.value,
                tone=(classified.tone_map.value if classified.tone_map else None),
                reason=classified.reason,
                scores=[{
                    "pose": score.pose,
                    "toneMap": score.tone_map.value,
                    "snapShare": score.snap_share,
                    "fracShare": score.frac_share,
                    "innerPixels": score.inner_pixels,
                } for score in classified.scores],
                isolationOk=result.isolation_ok,
                cleanupVerified=result.cleanup_verified,
                restored=result.restored,
                programOk=result.program.ok,
                errors=list(result.errors),
                durationMs=round((result.finished_s - result.started_s) * 1000, 1),
            )
        if not classified.grant_eligible or classified.tone_map != ToneMap.GPU_ANALYTIC or classified.verdict not in (ProbeVerdict.SNAP, ProbeVerdict.FRAC):
            self._finish_probe_state(
                "probe-failed",
                tone=classified.tone_map.value if classified.tone_map is not None else None,
            )
            return
        context = request.program_context_id
        try:
            current_context = self._program_context()
            current_engine = self._calibration.identity() if self._calibration is not None else None
        except Exception:
            current_context, current_engine = None, None
        if (
            self._connection_generation != request.connection_generation
            or current_context != context
            or current_engine != request.engine
            or result.evidence.identity.run_id != run_id
            or result.evidence.identity.connection_generation != request.connection_generation
        ):
            self._finish_probe_state("stale-result")
            return
        fingerprint = self._probe_fingerprint_read(context)
        expected = (result.evidence.identity.ua, result.evidence.identity.dpr, 1920, 1080)
        if fingerprint != expected or fingerprint != self._probe_fingerprint:
            self._revoke_placement(context)
            self._finish_probe_state("revoked-fingerprint")
            return
        grant = classified.verdict.value
        try:
            trip = self._require_transport().evaluate_in(
                context,
                _placement_round_trip_expr(self._placement_token, mode="probe"),
                deadline_s=1.0,
            )
            if trip != _PLACEMENT_ROUND_TRIP or self._program_context() != context or self._calibration is None or self._calibration.identity() != request.engine:
                raise LiveHostError("Placement context changed during commit.")
            committed = self._require_transport().evaluate_in(
                context,
                _placement_set_expr(self._placement_token, grant, _PLACEMENT_LEASE_MS),
                deadline_s=1.0,
            )
        except Exception:
            self._revoke_placement(context)
            self._finish_probe_state("stale-result")
            return
        if committed != grant:
            self._revoke_placement(context)
            self._finish_probe_state("channel-compromised")
            try: self._require_transport().evaluate("window.__obedOutput.hide()")
            except Exception: pass
            return
        self._reconnect_revoke_required = False
        with self._placement_lock:
            self._probe_run_id = None
            self._probe_context = None
            self._probe_engine = None
            self._probe_future = None
            self._probe_manual = False
        self._probe_fingerprint = fingerprint
        self._set_placement(grant, "granted", tone=classified.tone_map.value, lease_ms=_PLACEMENT_LEASE_MS)
        self._start_renewal_thread()

    def _start_renewal_thread(self) -> None:
        with self._placement_lock:
            if self._renew_thread is not None and self._renew_thread.is_alive():
                return
            self._renew_stop.clear()
            self._renew_thread = threading.Thread(target=self._renew_loop, name="obed-placement-renewal", daemon=True)
            self._renew_thread.start()

    def _renew_loop(self) -> None:
        while not self._renew_stop.wait(_PLACEMENT_RENEW_S):
            self._renew_probe_lease()

    def _renew_probe_lease(self) -> bool:
        with self._placement_lock:
            if self._stopped or self._placement["state"] != "valid" or self._placement["method"] != "probe":
                return False
            context = self._placement_context
            deadline = self._lease_deadline_s
            grant = self._placement["grant"]
            engine = self._engine_identity
        if context is None or deadline is None or grant not in ("snap", "frac"):
            return False
        remaining = deadline - time.monotonic()
        if remaining <= .2:
            self._set_placement(None, "leaseLapsed", state="invalid")
            return False
        current_engine = None
        try: current_engine = self._calibration.identity() if self._calibration is not None else None
        except Exception: pass
        current_context = self._program_context()
        fingerprint = self._probe_fingerprint_read(context, deadline_s=min(1.0, remaining / 2)) if current_context == context else None
        if current_engine != engine or fingerprint != self._probe_fingerprint:
            revoked = self._revoke_placement(context)
            if not revoked:
                self._reconnect_revoke_required = True
            self._set_placement(None, "revoked-fingerprint" if current_engine is not None else "disconnected", state="invalid")
            return False
        remaining = deadline - time.monotonic()
        if remaining <= .2:
            self._set_placement(None, "leaseLapsed", state="invalid")
            return False
        try:
            committed = self._require_transport().evaluate_in(
                context,
                _placement_renew_expr(self._placement_token, grant, _PLACEMENT_LEASE_MS),
                deadline_s=min(1.0, remaining / 2),
            )
        except Exception:
            self._set_placement(None, "leaseLapsed", state="invalid")
            return False
        if committed != grant:
            self._set_placement(None, "leaseLapsed", state="invalid")
            return False
        self._set_placement(grant, "granted", tone=ToneMap.GPU_ANALYTIC.value, lease_ms=_PLACEMENT_LEASE_MS)
        return True

    def _validate_export(self) -> None:
        header_path = self.resolver(self.export_root, "assets/header.json")
        try:
            header = json.loads(header_path.read_text())
            width = int(header["slideWidth"])
            height = int(header["slideHeight"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LiveHostError("Prepared export has no valid 16:9 header.") from exc
        if width * 9 != height * 16:
            raise LiveHostError("Prepared export is not 16:9.")
        if header.get("showMode") != 0:
            raise LiveHostError("Prepared export is not in manual presentation mode.")
        self._canvas = {"width": width, "height": height}

    def _authored_scene_count(self) -> int | None:
        count = 0
        parsed = 0
        for slide in self.slides:
            if slide.get("skipped"):
                continue
            player_index = slide.get("playerIndex")
            uuid = slide.get("exportedUuid")
            if not isinstance(player_index, int) or not isinstance(uuid, str):
                continue
            parsed += 1
            relative = f"assets/{uuid}/{uuid}.jsonp"
            payload = self.resolver(self.export_root, relative).read_text().strip()
            prefix = "local_slide("
            if not payload.startswith(prefix) or not payload.rstrip().endswith(")"):
                raise LiveHostError("Prepared export has an unreadable authored scene list.")
            try:
                scene_data = json.loads(payload[len(prefix) :].strip().rstrip(")").strip())
                events = scene_data["json"]["events"]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise LiveHostError("Prepared export has an unreadable authored scene list.") from exc
            if not isinstance(events, list) or not events:
                raise LiveHostError("Prepared export has no authored scenes for a playable slide.")
            count += len(events)
        return count if parsed else None

    def capabilities(self) -> dict[str, dict[str, Any]]:
        advance: dict[str, Any] = {"supported": self._can_advance is not False}
        if self._can_advance is False:
            advance["reason"] = "Player has no next manual action."
        go_to: dict[str, Any] = {
            "supported": self._can_go_to is not False,
            "semantics": "restart-at-initial-state+autoplay" if self._goto_autoplay_mode != "off" else "restart-at-initial-state",
        }
        if self._can_go_to is False:
            go_to["reason"] = "Player is not ready for go-to."
        try: calibration_ready = self._calibration is not None and self._calibration.identity() is not None
        except Exception: calibration_ready = False
        recalibrate: dict[str, Any] = {
            "supported": self._managed_obs and calibration_ready and self._probe_run_id is None,
        }
        if not recalibrate["supported"]:
            recalibrate["reason"] = (
                "Calibration is already running."
                if self._probe_run_id is not None
                else (
                    "Waiting for connection to output host"
                    if self._managed_obs and self._calibration is not None
                    else "Recalibration is available only for managed OBS output."
                )
            )
        return {
            "advance": advance,
            "goTo": go_to,
            "hide": {"supported": True},
            "show": {"supported": True},
            "recalibrate": recalibrate,
        }

    def observe(self) -> PlayerObservation:
        if not self._transport:
            self.start()
        transport = self._require_transport()
        try:
            value = transport.evaluate("window.__obedLive ? window.__obedLive.snapshot() : null")
        except LiveHostError:
            if not self._reconnect_managed_transport():
                raise
            transport = self._require_transport()
            value = transport.evaluate("window.__obedLive ? window.__obedLive.snapshot() : null")
        if not isinstance(value, dict): raise LiveHostError("Recognised player observation is unavailable.")
        revision = value.get("revision")
        self._runtime_revision = revision if isinstance(revision, int) and not isinstance(revision, bool) else None
        self._can_advance = bool(value.get("canAdvance"))
        self._can_go_to = bool(value.get("canGoTo"))
        run_length = value.get("autoPlayRunLength")
        self._auto_play_run_length = run_length if isinstance(run_length, int) and not isinstance(run_length, bool) else None
        run_kinds = value.get("autoPlayRunKinds")
        self._auto_play_run_kinds = run_kinds if isinstance(run_kinds, list) else None
        version_seen = value.get("runtimeVersion")
        self._runtime_version_seen = version_seen if isinstance(version_seen, int) and not isinstance(version_seen, bool) else None
        self._slide_number_showing = value.get("slideNumberShowing") is True
        self._player_busy = bool(value.get("busy", True))
        viewport = transport.evaluate("[window.innerWidth, window.innerHeight]")
        if (
            isinstance(viewport, list)
            and len(viewport) == 2
            and all(isinstance(item, int) and item > 0 for item in viewport)
        ):
            self._viewport = {"width": viewport[0], "height": viewport[1]}
        index = value.get("exportedSlideIndex")
        if isinstance(index, bool) or not isinstance(index, int): original = None
        else: original = self._original_by_player.get(index)
        scene = value.get("sceneId")
        scene_count = value.get("sceneCount")
        if (
            value.get("ready")
            and
            self._expected_scene_count is not None
            and scene_count != self._expected_scene_count
        ):
            raise LiveHostError("Player fell back from the authored build renderer.")
        self._sync_placement()
        visible_expr = (
            "getComputedStyle(document.getElementById('body')).opacity!=='0'"
            if self._attach_endpoint
            else "document.getElementById('obed-output-black').style.display==='none'"
        )
        observation = PlayerObservation(
            original_slide=original,
            scene_id=str(scene) if scene is not None else None,
            build_index=value.get("buildIndex") if isinstance(value.get("buildIndex"), int) else None,
            revision=self._runtime_revision,
            busy=self._player_busy,
            output_visible=bool(transport.evaluate(visible_expr)),
            output=self.output,
        )
        self._log_observation_change(observation)
        self._last_observation = observation
        return observation

    def _log_observation_change(self, observation: PlayerObservation) -> None:
        if self._logger is None: return
        snapshot = (observation.original_slide, observation.scene_id, observation.busy, observation.output_visible)
        if snapshot != self._last_logged_observation:
            self._last_logged_observation = snapshot
            self._logger.log(
                "observation", originalSlide=observation.original_slide, sceneId=observation.scene_id,
                busy=observation.busy, outputVisible=observation.output_visible,
            )

    def _video_snapshot(self, transport: ChromeCdp) -> Any:
        try:
            return transport.evaluate(
                "Array.from(document.querySelectorAll('video')).map(v=>{"
                "var q=v.getVideoPlaybackQuality?v.getVideoPlaybackQuality():{};"
                "return {src:(v.currentSrc||v.src||'').split('/').pop(),currentTime:v.currentTime,"
                "paused:v.paused,readyState:v.readyState,videoWidth:v.videoWidth,videoHeight:v.videoHeight,"
                "droppedFrames:q.droppedVideoFrames,totalFrames:q.totalVideoFrames};})",
                deadline_s=1.5,
            )
        except LiveHostError as exc:
            return "timeout" if "did not answer" in str(exc) else None
        except Exception:
            return None

    def execute(self, operation: str, slide: int | None = None) -> PlayerObservation:
        transport = self._require_transport()
        started = time.monotonic()
        before = self.observe()
        before_revision, before_scene = self._runtime_revision, before.scene_id
        self._last_goto_autoplay = None
        if operation == "recalibrate":
            if self._calibration is None or not self._managed_obs:
                raise PlayerCommandRejected("Recalibration is available only for managed OBS output.")
            if self._probe_run_id is not None:
                raise PlayerCommandRejected("Calibration is already running.")
            context = self._program_context()
            try: engine = self._calibration.identity()
            except Exception: engine = None
            if context is None or engine is None:
                raise PlayerCommandRejected("Waiting for connection to output host")
            self._schedule_probe(context, engine, manual=True)
            observed = replace(before, output=self.output)
            self._last_observation = observed
            self._log_execute(operation, slide, "ok", started, before_revision, before_revision, before_scene, before_scene, None, transport)
            return observed
        try:
            observed = self._execute(operation, slide, transport, before, before_revision)
        except PlayerCommandRejected as exc:
            self._log_execute(operation, slide, "rejected", started, before_revision, before_revision, before_scene, before_scene, str(exc), transport)
            raise
        except Exception as exc:
            self._log_execute(operation, slide, "error", started, before_revision, self._runtime_revision, before_scene, before_scene, str(exc), transport)
            raise
        self._log_execute(operation, slide, "ok", started, before_revision, self._runtime_revision, before_scene, observed.scene_id, None, transport)
        return observed

    def _log_execute(self, operation: str, slide: int | None, outcome: str, started: float, revision_before: int | None, revision_after: int | None, scene_before: str | None, scene_after: str | None, error: str | None, transport: ChromeCdp) -> None:
        if self._logger is None: return
        fields: dict[str, Any] = {
            "operation": operation, "slide": slide, "outcome": outcome,
            "durationMs": round((time.monotonic() - started) * 1000, 1),
            "revisionBefore": revision_before, "revisionAfter": revision_after,
            "sceneBefore": scene_before, "sceneAfter": scene_after,
            "videos": self._video_snapshot(transport),
        }
        if operation == "goTo" and self._last_goto_autoplay is not None:
            fields["autoPlayRunLength"] = self._last_goto_autoplay.run_length
            fields["autoPlayRunKinds"] = self._last_goto_autoplay.run_kinds
            fields["autoPlayFired"] = self._last_goto_autoplay.fired
            fields["autoPlayDeferredReason"] = self._last_goto_autoplay.deferred_reason
        if error is not None: fields["error"] = error
        self._logger.log("execute", **fields)

    def _execute(self, operation: str, slide: int | None, transport: ChromeCdp, before: PlayerObservation, before_revision: int | None) -> PlayerObservation:
        if operation == "advance" and before.busy:
            raise PlayerCommandRejected("Player is busy.")
        if operation == "advance" and not self._can_advance:
            raise PlayerCommandRejected("Player has no next manual action.")
        if operation == "goTo" and before.busy:
            raise PlayerCommandRejected("Player is busy.")
        if operation == "advance":
            self._await_click_target()
            self._prepare_navigation_placement()
            self._send_advance_input(transport)
        elif operation == "goTo":
            if slide is None: raise PlayerCommandRejected("A slide number is required.")
            player_index = next((int(s["playerIndex"]) for s in self.slides if s.get("originalOrdinal") == slide and not s.get("skipped")), None)
            if player_index is None: raise PlayerCommandRejected("Original slide is unavailable or skipped.")
            self._prepare_navigation_placement()
            transport.evaluate("window.focus();document.body.focus()")
            if self._continuity_mode == "qualified":
                transport.evaluate("window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.clear && window.__OBED_P2_PRESERVE__.clear()")
            for digit in str(player_index + 1): transport.key(digit, "Digit" + digit, ord(digit))
            transport.key("Enter", "Enter", 13)
        elif operation == "hide": transport.evaluate("window.__obedOutput.hide()")
        elif operation == "show":
            if self._placement["reason"] == "channel-compromised":
                raise PlayerCommandRejected("Output stays hidden: the placement channel failed its check.")
            transport.evaluate("window.__obedOutput.show()")
        else: raise LiveHostError("Unsupported player operation.")
        if operation in ("hide", "show"):
            return self.observe()
        observed = self._wait_for_ack(before_revision, operation=operation)
        if operation == "goTo":
            return self._repair_goto_autoplay(observed, slide, transport, before_revision)
        return observed

    def _prepare_navigation_placement(self) -> None:
        if self._reconnect_revoke_required:
            context = self._program_context()
            if context is None or not self._revoke_placement(context):
                raise PlayerCommandRejected("Waiting for connection to output host")
            self._reconnect_revoke_required = False
        if self._placement["state"] == "valid" and self._placement["method"] == "probe":
            self._renew_probe_lease()

    def _await_click_target(self) -> None:
        """The player spends a click hiding its slide-number overlay (shown by go-to digits) instead of advancing."""
        if self._advance_mode != "click": return
        deadline = time.monotonic() + self.timeout_s
        while self._slide_number_showing:
            if time.monotonic() >= deadline:
                raise PlayerCommandRejected("Click advance is unavailable while the slide-number overlay is showing.")
            time.sleep(.05)
            self.observe()

    def _send_advance_input(self, transport: ChromeCdp) -> None:
        transport.evaluate("window.focus();document.body.focus()")
        if self._advance_mode == "click": transport.click_stage()
        else: transport.key(" ", "Space", 32)

    def _repair_goto_autoplay(self, ack_observed: PlayerObservation, slide: int | None, transport: ChromeCdp, before_revision: int | None) -> PlayerObservation:
        """Start the destination's leading automatic-play run after go-to settles."""
        if self._goto_autoplay_mode == "off":
            return ack_observed
        phase = "pre_dispatch"
        target_reached = False
        run_length: int | None = None
        run_kinds: list[Any] | None = None
        try:
            settled = replace(self._wait_settled(expected_slide=slide, previous_revision=before_revision), go_to_target_reached=True)
            target_reached = True
            run_length, run_kinds = self._auto_play_run_length, self._auto_play_run_kinds
            if run_length is None:
                return self._goto_autoplay_deferred("runLength null", run_length, run_kinds)
            if not (isinstance(self._runtime_version_seen, int) and self._runtime_version_seen >= RUNTIME_VERSION):
                return self._goto_autoplay_deferred("runtime version", run_length, run_kinds)
            if run_length == 0:
                self._last_goto_autoplay = _GoToAutoplayResult(0, run_kinds, False, None)
                return settled
            if not self._can_advance:
                return self._goto_autoplay_deferred("busy", run_length, run_kinds)
            marker = (settled.scene_id, settled.revision)
            self._await_click_target()
            fresh = self.observe()
            if (fresh.scene_id, fresh.revision) != marker or self._auto_play_run_length != run_length:
                return self._goto_autoplay_deferred("changed before fire", run_length, run_kinds)
            phase = "dispatch_attempted"
            self._prepare_navigation_placement()
            self._send_advance_input(transport)
            self._wait_for_ack(settled.revision, operation="advance")
            phase = "acknowledged"
            final = replace(self._wait_settled(previous_revision=settled.revision), go_to_target_reached=True)
        except (LiveHostError, PlayerCommandRejected) as exc:
            return self._goto_autoplay_after_failure(phase, exc, run_length, run_kinds, target_reached)
        self._last_goto_autoplay = _GoToAutoplayResult(run_length, run_kinds, True, None)
        return final

    def _goto_autoplay_after_failure(self, phase: str, exc: Exception, run_length: int | None, run_kinds: list[Any] | None, target_reached: bool) -> PlayerObservation:
        """Only a `pre_dispatch` failure is safe to call idle: once input delivery has
        begun, its outcome may be unknown (never claim it's safe to press advance). The
        target-reached marker is preserved whenever the jump itself already settled, so a
        later plain observation can't reject a go-to that already succeeded."""
        observation = replace(self._last_observation, go_to_target_reached=target_reached)
        if phase == "pre_dispatch":
            reason = "settle timeout" if "did not settle" in str(exc) else f"pre-dispatch error: {exc}"
            self._last_goto_autoplay = _GoToAutoplayResult(run_length, run_kinds, False, reason)
            return replace(observation, auto_play_deferred=GOTO_AUTOPLAY_DEFERRED_NOTE)
        if phase == "acknowledged":
            self._last_goto_autoplay = _GoToAutoplayResult(run_length, run_kinds, True, f"settle unconfirmed: {exc}")
        else:
            self._last_goto_autoplay = _GoToAutoplayResult(run_length, run_kinds, None, f"delivery unknown: {exc}")
        return observation

    def _goto_autoplay_deferred(self, reason: str, run_length: int | None = None, run_kinds: list[Any] | None = None) -> PlayerObservation:
        self._last_goto_autoplay = _GoToAutoplayResult(run_length, run_kinds, False, reason)
        return replace(self._last_observation, auto_play_deferred=GOTO_AUTOPLAY_DEFERRED_NOTE)

    def _wait_for_ack(self, previous_revision: int | None, *, operation: str | None = None) -> PlayerObservation:
        """Wait for actual input delivery, without treating it as scene completion."""
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            observed = self.observe()
            if self._runtime_revision != previous_revision:
                return observed
            time.sleep(.05)
        if operation == "goTo":
            raise PlayerCommandRejected("Go-to unavailable: the player did not acknowledge digit/Enter key input before the timeout. Click advance cannot select a slide.")
        raise LiveHostError("Player did not acknowledge the command before the timeout.")

    def _wait_settled(self, expected_slide: int | None = None, previous_scene: str | None = None, previous_revision: int | None = None) -> PlayerObservation:
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            try:
                observed = self.observe()
            except LiveHostError as exc:
                if "observation is unavailable" not in str(exc):
                    raise
                time.sleep(.05)
                continue
            changed = self._runtime_revision != previous_revision
            if not observed.busy and changed and (expected_slide is None or observed.original_slide == expected_slide): return observed
            time.sleep(.05)
        raise LiveHostError("Player did not settle before the command timeout.")

    def _require_transport(self) -> ChromeCdp:
        if not self._transport: raise LiveHostError("Program player is not running.")
        return self._transport

    def stop(self) -> None:
        """Idempotent and thread-safe: an operator abort may call this from one thread
        while another is blocked inside `execute()`/`observe()`.  A second, concurrent
        or subsequent, call is a harmless no-op that waits only for the first call's
        teardown.  Every step (transport, asset server, temp profile) is attempted even
        if an earlier one raises; a resource's reference is dropped only once it is
        actually released, so a raising stop can be retried and only redoes what is
        still held."""
        with self._stop_lock:
            self._stopped = True
            self._renew_stop.set()
            with self._placement_lock:
                run_id = self._probe_run_id
                probe_thread = self._probe_thread
                renew_thread = self._renew_thread
            cancellation_error: Exception | None = None
            placement_stop_deadline = time.monotonic() + 5.0
            if run_id is not None and self._calibration is not None:
                try:
                    if not self._calibration.cancel(run_id, timeout_s=max(0.0, placement_stop_deadline - time.monotonic())):
                        cancellation_error = LiveHostError("Calibration cleanup was not verified before stop.")
                except Exception as exc:
                    cancellation_error = exc
            for thread in (probe_thread, renew_thread):
                if thread is not None and thread is not threading.current_thread():
                    thread.join(timeout=max(0.0, placement_stop_deadline - time.monotonic()))
                    if thread.is_alive() and cancellation_error is None:
                        cancellation_error = LiveHostError("Placement worker did not stop.")
            if self._placement_context is not None and self._transport is not None:
                self._revoke_placement(self._placement_context)
            self._set_placement(None, "stopped", state="invalid")
            self._probe_run_id = None
            self._probe_future = None
            if not self._transport and not self._server and not self._profile:
                if self._logger is not None:
                    self._logger.log("stop", released=[], errors=[], droppedLogRecords=self._logger.dropped)
                    self._logger.close()
                if cancellation_error is not None:
                    raise LiveHostError("Program player did not fully stop.") from cancellation_error
                return
            errors: list[Exception] = []
            if cancellation_error is not None:
                errors.append(cancellation_error)
            released: list[str] = []
            if self._transport is not None:
                try: self._transport.stop()
                except Exception as exc: errors.append(exc)
                else: self._transport = None; released.append("transport")
            if self._server is not None:
                try: self._server.stop()
                except Exception as exc: errors.append(exc)
                else: self._server = None; released.append("server")
            if self._profile is not None:
                try: shutil.rmtree(self._profile)
                except Exception as exc: errors.append(exc)
                else: self._profile = None; released.append("profile")
            if self._logger is not None:
                self._logger.log("stop", released=released, errors=[str(exc) for exc in errors], droppedLogRecords=self._logger.dropped)
                self._logger.close()
            if errors:
                raise LiveHostError("Program player did not fully stop.")
