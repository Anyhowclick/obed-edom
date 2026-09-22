"""The single, server-owned Chrome player used for HDMI program output.

This is deliberately a small adapter: it does not interpret Keynote scenes or
create a second player for a presenter.  The patched Keynote runtime remains
the authority for whether an input has settled.
"""

from __future__ import annotations

import ipaddress
import json
import math
import mimetypes
import os
import queue
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from urllib.parse import unquote, urlsplit
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from websockets.sync.client import connect

from .html_preview import preview_root, safe_export_file
from .live_continuity import ContinuityPlan, Unsupported, codec_report, derive_plan
from .live_continuity_js import CONTINUITY_VERSION, PRESERVE_CORE_JS, js_sha256
from .live_runtime import RUNTIME_VERSION, LiveRuntimeUnsupported, patch_player
from .live_session import PlayerCommandRejected, PlayerObservation

ATTACH_ENV = "OBED_LIVE_ATTACH"
ATTACH_MATCH_ENV = "OBED_LIVE_ATTACH_MATCH"
ADVANCE_ENV = "OBED_LIVE_ADVANCE"
CONTINUITY_ENV = "OBED_LIVE_CONTINUITY"
GOTO_AUTOPLAY_ENV = "OBED_LIVE_GOTO_AUTOPLAY"
GOTO_AUTOPLAY_DEFERRED_NOTE = "Movies idle until next advance"
_UNSET = object()
_CDP_MAX_MESSAGE_BYTES = 64 * 1024 * 1024
_CONTINUITY_STAGE_GATE_EXPR = (
    "(()=>{var s=document.getElementById('stage');var r=s?s.getBoundingClientRect():null;"
    "return {ready:!!(window.__OBED_P2_PRESERVE__&&window.__OBED_P2_PRESERVE__.ready===true),"
    "present:!!window.__OBED_P2_PRESERVE__,"
    "info:window.__OBED_CONTINUITY_INFO__||null,"
    "stage:s?{offsetWidth:s.offsetWidth,offsetHeight:s.offsetHeight,"
    "rect:{left:r.left,top:r.top,width:r.width,height:r.height}}:null};})()"
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
                    if relative == "assets/player/main.js":
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
<style id="obed-output-overlay">html,body,#body{background:transparent!important}#body{opacity:0}#slideshowNavigator,#slideNumberDisplay,#helpPlacard{display:none!important}body{cursor:none}</style>
"""
            overlay = """
<script>(function(){var hidden=true;function apply(){var el=document.getElementById('body');if(!el)return;el.style.setProperty('background','transparent','important');el.style.setProperty('opacity',hidden?'0':'1','important');}window.__obedOutput={show(){hidden=false;apply();},hide(){hidden=true;apply();}};var target=document.getElementById('body');if(target){new MutationObserver(apply).observe(target,{attributes:true,attributeFilter:['style','class']});}document.addEventListener('DOMContentLoaded',apply);apply();})();</script>
"""
        else:
            style = """
<style id="obed-output-overlay">#obed-output-black{position:fixed;inset:0;background:#000;z-index:2147483647}#slideshowNavigator,#slideNumberDisplay,#helpPlacard{display:none!important}body{cursor:none}</style>
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
        self._blank_url = "about:blank"
        self._blanked = False

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
            attached_url = str(target.get("url") or "")
            self._blank_url = attached_url if attached_url.startswith("about:blank") else "about:blank"
            self._blanked = False
            self.call("Runtime.enable")
            self.call("Page.enable")
            try: self.call("Log.enable")
            except Exception: pass
            return
        self.profile.mkdir(parents=True, exist_ok=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = int(sock.getsockname()[1])
        args = [
            str(self.chrome), f"--remote-debugging-port={self.port}",
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
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=.3) as response: targets = json.loads(response.read())
                target = next((item for item in targets if item.get("type") == "page" and item.get("webSocketDebuggerUrl")), None)
                if target:
                    self.ws = connect(target["webSocketDebuggerUrl"], open_timeout=2, max_size=_CDP_MAX_MESSAGE_BYTES)
                    break
            except Exception: time.sleep(.05)
        if not self.ws:
            try: self.stop()
            except Exception: pass
            raise LiveHostError("Chrome CDP did not start.")
        self.call("Runtime.enable")
        self.call("Page.enable")
        try: self.call("Log.enable")
        except Exception: pass
        if not self.headless:
            window = self.call("Browser.getWindowForTarget")
            self.call("Browser.setWindowBounds", windowId=window["windowId"], bounds={"windowState": "fullscreen"})

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
            matched = [item for item in pages if any(self.attach_match in item.get(field, "") for field in ("url", "title"))]
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
        with self._lock:
            ws, proc = self.ws, self.proc
            if not ws: raise LiveHostError("Program browser stopped unexpectedly.")
            if proc is not None and proc.poll() is not None: raise LiveHostError("Program browser stopped unexpectedly.")
            self._id += 1
            request_id = self._id
            started = time.monotonic()
            deadline = started + (deadline_s if deadline_s is not None else 15)
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

    def _route_event(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params") or {}
        if method == "Log.entryAdded": self._log("pageLog", entry=params.get("entry"))
        elif method == "Runtime.exceptionThrown": self._log("pageException", detail=params.get("exceptionDetails"))
        elif method == "Runtime.consoleAPICalled" and params.get("type") in ("error", "warning"):
            self._log("pageConsole", level=params.get("type"), args=params.get("args"))

    def evaluate(self, expression: str, deadline_s: float | None = None) -> Any:
        result = self.call("Runtime.evaluate", deadline_s=deadline_s, expression=expression, returnByValue=True, awaitPromise=False)
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
            if self.ws is None and self.proc is None: return
            errors: list[Exception] = []
            if self.ws is not None:
                try: self.ws.close()
                except Exception as exc: errors.append(exc)
                else: self.ws = None
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


@dataclass(frozen=True)
class _GoToAutoplayResult:
    run_length: int | None
    run_kinds: list[Any] | None
    fired: bool | None
    deferred_reason: str | None


class LiveOutputHost:
    def __init__(self, export_root: Path, slides: list[dict[str, Any]], *, display_id: int | None = None, chrome_path: Path = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"), headless: bool = False, transport_factory: Callable[..., ChromeCdp] = ChromeCdp, server_factory: Callable[..., _AssetServer] = _AssetServer, resolver: Callable[[Path, str], Path] = safe_export_file, timeout_s: float = 12.0, attach_endpoint: str | None = _UNSET, attach_match: str | None = None, continuity: str = "auto") -> None:
        if continuity not in ("auto", "off"):
            raise LiveHostError("Continuity must be auto or off.")
        self._continuity_preference = continuity
        self.export_root, self.slides = export_root, slides
        if attach_endpoint is _UNSET:
            attach_endpoint = os.environ.get(ATTACH_ENV) or None
        self._attach_endpoint = _validate_loopback_endpoint(attach_endpoint.strip()) if attach_endpoint and attach_endpoint.strip() else None
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
        self._codec_report: list[dict[str, Any]] = []
        self._codec_warnings: list[str] = []

    def _resolve_codecs(self) -> tuple[list[dict[str, Any]], list[str]]:
        """Codec of every movie the export's slides reference, independent of continuity:
        this must stay populated even when continuity is off or unsupported. A failure to
        probe never blocks the session -- an unreadable codec is just reported as such."""
        try:
            report = codec_report(self.export_root, self.slides, resolver=self.resolver)
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
        try:
            plan = derive_plan(self.export_root, self.slides, resolver=self.resolver)
        except Exception as exc:  # noqa: BLE001 - fail closed, never let derivation crash the host
            return "unsupported", str(exc), None
        if isinstance(plan, Unsupported):
            return "unsupported", plan.reason, None
        runtime = plan.to_runtime()
        if isinstance(runtime, Unsupported):
            return "unsupported", runtime.reason, None
        codec_by_asset = {entry["asset"]: entry for entry in self._codec_report}
        attach = self._attach_endpoint is not None
        for movie in runtime["movies"].values():
            asset = movie["assetKeys"][0]
            entry = codec_by_asset.get(asset)
            family = entry["family"] if entry is not None else "other"
            if not _codec_supported(family, attach=attach, headless=self.headless):
                display = _codec_display(entry)
                return "unsupported", f"movie codec is not playable in this output: {asset} ({display})", None
        self._continuity_not_carried = self._not_carried(plan)
        if self._attach_endpoint:
            runtime = {**runtime, "transparentBackground": True}
        return "pending", None, runtime

    def _not_carried(self, plan: ContinuityPlan) -> list[dict[str, Any]]:
        """Boundaries continuity declines to carry, in operator terms: original slide
        ordinals rather than the plan's player indices."""
        ordinals = {
            slide.get("playerIndex"): slide.get("originalOrdinal")
            for slide in self.slides
            if not slide.get("skipped")
        }
        return [
            {
                "fromSlide": ordinals.get(refusal["fromPlayer"]),
                "toSlide": ordinals.get(refusal["toPlayer"]),
                "asset": refusal["asset"],
                "reason": refusal["reason"],
            }
            for refusal in plan.refusals
        ]

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
        return info

    @property
    def output(self) -> dict[str, Any]:
        """Detected physical output geometry, available before browser startup."""
        if self._attach_endpoint:
            result: dict[str, Any] = {
                "transport": "fill-key", "alpha": True, "audio": False, "bridge": "obs-cdp",
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
        result["continuity"] = self._continuity_info()
        result["codecs"] = list(self._codec_report)
        result["codecWarnings"] = list(self._codec_warnings)
        return result

    def start(self) -> PlayerObservation:
        if self._stopped:
            raise LiveHostError("Program player has been stopped.")
        if self._transport:
            return self.observe()
        self._advance_mode = os.environ.get(ADVANCE_ENV, "key").strip().lower()
        if self._advance_mode not in ("key", "click"):
            raise LiveHostError("OBED_LIVE_ADVANCE must be key or click.")
        self._goto_autoplay_mode = "off" if os.environ.get(GOTO_AUTOPLAY_ENV, "").strip().lower() == "off" else "on"
        self._log_path = _new_log_path()
        self._logger = _SessionLogger(self._log_path)
        self._logger.log(
            "start", mode="attach" if self._attach_endpoint else "hdmi",
            exportRoot=str(self.export_root), runtimeVersion=RUNTIME_VERSION,
            display=(self.display.display_id if self.display else None),
            attachEndpoint=self._attach_endpoint, attachMatch=self._attach_match,
            headless=self.headless, advanceMode=self._advance_mode,
            goToAutoplayMode=self._goto_autoplay_mode,
        )
        try:
            self._validate_export()
            self._expected_scene_count = self._authored_scene_count()
            self._codec_report, self._codec_warnings = self._resolve_codecs()
            self._logger.log("codecs", report=self._codec_report, warnings=self._codec_warnings)
            self._continuity_mode, self._continuity_reason, self._continuity_runtime_plan = self._resolve_continuity_static()
            player = self.resolver(self.export_root, "assets/player/main.js").read_bytes()
            try: patched = patch_player(player)
            except LiveRuntimeUnsupported as exc: raise LiveHostError(str(exc)) from exc
            self._profile = Path(tempfile.mkdtemp(prefix="obed-live-chrome-"))
            continuity_script = (
                _continuity_scripts(self._continuity_runtime_plan, self._canvas)
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
            try: version = self._transport.call("Browser.getVersion")
            except Exception: version = None
            self._logger.log("browserVersion", result=version)
            self._transport.goto(url)
            stage_geometry: dict[str, Any] | None = None
            if self._continuity_mode == "pending":
                self._continuity_mode, self._continuity_reason, stage_geometry, self._continuity_scale = (
                    self._resolve_continuity_pending()
                )
            self._logger.log(
                "continuity", mode=self._continuity_mode, reason=self._continuity_reason,
                runtimePlan=self._continuity_runtime_plan, stage=stage_geometry, scale=self._continuity_scale,
                notCarried=self._continuity_not_carried,
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
        return {"advance": advance, "goTo": go_to, "hide": {"supported": True}, "show": {"supported": True}}

    def observe(self) -> PlayerObservation:
        if not self._transport:
            self.start()
        transport = self._require_transport()
        value = transport.evaluate(
            "window.__obedLive ? window.__obedLive.snapshot() : null"
        )
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
            busy=bool(value.get("busy", True)),
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
            self._send_advance_input(transport)
        elif operation == "goTo":
            if slide is None: raise PlayerCommandRejected("A slide number is required.")
            player_index = next((int(s["playerIndex"]) for s in self.slides if s.get("originalOrdinal") == slide and not s.get("skipped")), None)
            if player_index is None: raise PlayerCommandRejected("Original slide is unavailable or skipped.")
            transport.evaluate("window.focus();document.body.focus()")
            if self._continuity_mode == "qualified":
                transport.evaluate("window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.clear && window.__OBED_P2_PRESERVE__.clear()")
            for digit in str(player_index + 1): transport.key(digit, "Digit" + digit, ord(digit))
            transport.key("Enter", "Enter", 13)
        elif operation == "hide": transport.evaluate("window.__obedOutput.hide()")
        elif operation == "show": transport.evaluate("window.__obedOutput.show()")
        else: raise LiveHostError("Unsupported player operation.")
        if operation in ("hide", "show"):
            return self.observe()
        observed = self._wait_for_ack(before_revision, operation=operation)
        if operation == "goTo":
            return self._repair_goto_autoplay(observed, slide, transport, before_revision)
        return observed

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
            if not self._transport and not self._server and not self._profile:
                if self._logger is not None:
                    self._logger.log("stop", released=[], errors=[], droppedLogRecords=self._logger.dropped)
                    self._logger.close()
                return
            errors: list[Exception] = []
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
