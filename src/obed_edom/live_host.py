"""The single, server-owned Chrome player used for HDMI program output.

This is deliberately a small adapter: it does not interpret Keynote scenes or
create a second player for a presenter.  The patched Keynote runtime remains
the authority for whether an input has settled.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from urllib.parse import unquote, urlsplit
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from .html_preview import preview_root, safe_export_file
from .live_continuity import Unsupported, derive_plan
from .live_continuity_js import CONTINUITY_VERSION, PRESERVE_CORE_JS, js_sha256
from .live_runtime import RUNTIME_VERSION, LiveRuntimeUnsupported, patch_player
from .live_session import PlayerCommandRejected, PlayerObservation

ATTACH_ENV = "OBED_LIVE_ATTACH"
ATTACH_MATCH_ENV = "OBED_LIVE_ATTACH_MATCH"
CONTINUITY_ENV = "OBED_LIVE_CONTINUITY"
_CONTINUITY_VIEWPORT_REASON = "viewport is not the authored size (scaled-stage mapping pending)"
_UNSET = object()


def _continuity_plan_script(plan: dict[str, Any], canvas: dict[str, int]) -> str:
    """Embed the runtime plan as `window.__OBED_CONTINUITY__`, installed only when
    the page's own viewport matches the authored canvas (footprints are authored-size
    pixels; scaled-stage mapping is a later increment). `</` and U+2028/2029 are
    escaped so an embedded asset filename cannot break out of the script tag."""
    payload = json.dumps(plan).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    width, height = int(canvas["width"]), int(canvas["height"])
    return (
        '<script id="obed-continuity-plan">(function(){'
        f"var plan={payload};var w={width},h={height};"
        "window.__OBED_CONTINUITY_INFO__={authoredWidth:w,authoredHeight:h,"
        "viewportWidth:window.innerWidth,viewportHeight:window.innerHeight};"
        "if(window.innerWidth===w&&window.innerHeight===h){"
        "window.__OBED_CONTINUITY__=plan;window.__OBED_CONTINUITY_INFO__.installed=true;"
        "}else{window.__OBED_CONTINUITY_INFO__.installed=false;"
        f"window.__OBED_CONTINUITY_INFO__.reason={json.dumps(_CONTINUITY_VIEWPORT_REASON)};"
        "}})();</script>\n"
    )


def _continuity_core_script() -> str:
    core = PRESERVE_CORE_JS.replace("</script", "<\\/script")
    return f'<script id="obed-continuity-core">{core}</script>\n'


def _continuity_scripts(plan: dict[str, Any], canvas: dict[str, int]) -> str:
    return _continuity_plan_script(plan, canvas) + _continuity_core_script()


class LiveHostError(RuntimeError):
    """The owned browser cannot provide an observed player state."""


def _validate_loopback_endpoint(endpoint: str) -> str:
    host = urlsplit(endpoint).hostname
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise LiveHostError("OBED_LIVE_ATTACH must target a loopback CDP endpoint.")
    return endpoint


class _SessionLogger:
    """Append-only JSONL session log; a logging failure never reaches the caller."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._file: Any = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = path.open("a", buffering=1)
        except Exception:
            self._file = None

    def log(self, kind: str, **fields: Any) -> None:
        if self._file is None:
            return
        record = {"ts": time.time(), "kind": kind, **fields}
        try:
            with self._lock:
                self._file.write(json.dumps(record, default=str) + "\n")
                self._file.flush()
        except Exception:
            pass

    def close(self) -> None:
        if self._file is None:
            return
        try:
            with self._lock:
                self._file.close()
        except Exception:
            pass
        finally:
            self._file = None


def _new_log_path() -> Path:
    directory = preview_root() / "live-logs"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return directory / f"{stamp}-{os.getpid()}.jsonl"


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

    def _log(self, kind: str, **fields: Any) -> None:
        if self.logger is None: return
        try: self.logger.log(kind, **fields)
        except Exception: pass

    def start(self) -> None:
        from websockets.sync.client import connect
        if self.attach_endpoint:
            targets = self._list_targets()
            target = self._pick_target(targets)
            try:
                self.ws = connect(target["webSocketDebuggerUrl"], open_timeout=5)
            except Exception as exc:
                raise LiveHostError(f"Could not attach to CDP target: {exc}") from exc
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
                    self.ws = connect(target["webSocketDebuggerUrl"], open_timeout=2)
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
        try:
            with urllib.request.urlopen(self.attach_endpoint.rstrip("/") + "/json/list", timeout=5) as response:
                return json.loads(response.read())
        except Exception as exc:
            raise LiveHostError(f"Could not list CDP targets at {self.attach_endpoint}: {exc}") from exc

    def _pick_target(self, targets: list[dict[str, Any]]) -> dict[str, Any]:
        pages = [item for item in targets if item.get("type") == "page" and item.get("webSocketDebuggerUrl")]
        if self.attach_match:
            matched = [item for item in pages if self.attach_match in (item.get("url", "") + item.get("title", ""))]
            if matched: return matched[0]
        if len(pages) == 1: return pages[0]
        candidates = ", ".join(f"{item.get('title', '')} ({item.get('url', '')})" for item in pages) or "none"
        raise LiveHostError(f"Ambiguous CDP attach target; candidates: {candidates}")

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        with self._lock:
            ws, proc = self.ws, self.proc
            if not ws: raise LiveHostError("Program browser stopped unexpectedly.")
            if proc is not None and proc.poll() is not None: raise LiveHostError("Program browser stopped unexpectedly.")
            self._id += 1
            request_id = self._id
            started = time.monotonic()
            ws.send(json.dumps({"id": request_id, "method": method, "params": params}))
            while True:
                try: message = json.loads(ws.recv(timeout=15))
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

    def evaluate(self, expression: str) -> Any:
        result = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=False)
        if result.get("exceptionDetails"): raise LiveHostError("Program browser evaluation failed.")
        return (result.get("result") or {}).get("value")

    def key(self, key: str, code: str, vk: int) -> None:
        # No nativeVirtualKeyCode: macOS Chrome routes it through AppKit key equivalents and stalls CDP.
        values = {"key": key, "code": code, "windowsVirtualKeyCode": vk}
        self.call("Input.dispatchKeyEvent", type="keyDown", **values)
        self.call("Input.dispatchKeyEvent", type="keyUp", **values)

    def goto(self, url: str) -> None:
        self.call("Page.navigate", url=url)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.evaluate("document.readyState") == "complete": return
            time.sleep(.05)
        raise LiveHostError("Program page did not finish loading.")

    def stop(self) -> None:
        """Idempotent and thread-safe: never waits on `_lock`, so it stays prompt even
        while another thread is blocked inside `call()` on the same instance; closing
        the socket and terminating Chrome there make that blocked call fail promptly.
        Every teardown step is attempted even if an earlier one raises; a resource's
        reference is dropped only once it is actually released, so a raising stop can
        be retried and will only redo the work that is still outstanding."""
        with self._stop_lock:
            self._stopped = True
            if self.ws is None and self.proc is None: return
            errors: list[Exception] = []
            if self.attach_endpoint:
                if self.ws is not None:
                    if self._lock.acquire(blocking=False):
                        self._lock.release()
                        try: self.call("Page.navigate", url="about:blank")
                        except Exception: pass
                    try: self.ws.close()
                    except Exception as exc: errors.append(exc)
                    else: self.ws = None
                if errors: raise LiveHostError("Program browser did not fully stop.")
                return
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


class LiveOutputHost:
    def __init__(self, export_root: Path, slides: list[dict[str, Any]], *, display_id: int | None = None, chrome_path: Path = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"), headless: bool = False, transport_factory: Callable[..., ChromeCdp] = ChromeCdp, server_factory: Callable[..., _AssetServer] = _AssetServer, resolver: Callable[[Path, str], Path] = safe_export_file, timeout_s: float = 12.0, attach_endpoint: str | None = _UNSET, attach_match: str | None = None) -> None:
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
        self._continuity_mode: str = "off"
        self._continuity_reason: str | None = None
        self._continuity_runtime_plan: dict[str, Any] | None = None

    def _resolve_continuity_static(self) -> tuple[str, str | None, dict[str, Any] | None]:
        """Resolve continuity mode from the export alone, before the browser starts.
        `pending` means a runtime plan was derived and must still be confirmed truthfully
        from the page (the viewport-authored-size check only the page can perform)."""
        if os.environ.get(CONTINUITY_ENV) == "off":
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
        if self._attach_endpoint:
            runtime = {**runtime, "transparentBackground": True}
        return "pending", None, runtime

    def _continuity_info(self) -> dict[str, Any]:
        info: dict[str, Any] = {"mode": self._continuity_mode, "version": CONTINUITY_VERSION, "sha256": js_sha256()}
        if self._continuity_reason is not None:
            info["reason"] = self._continuity_reason
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
        return result

    def start(self) -> PlayerObservation:
        if self._stopped:
            raise LiveHostError("Program player has been stopped.")
        if self._transport:
            return self.observe()
        self._log_path = _new_log_path()
        self._logger = _SessionLogger(self._log_path)
        self._logger.log(
            "start", mode="attach" if self._attach_endpoint else "hdmi",
            exportRoot=str(self.export_root), runtimeVersion=RUNTIME_VERSION,
            display=(self.display.display_id if self.display else None),
            attachEndpoint=self._attach_endpoint, attachMatch=self._attach_match,
            headless=self.headless,
        )
        self._validate_export()
        self._expected_scene_count = self._authored_scene_count()
        self._continuity_mode, self._continuity_reason, self._continuity_runtime_plan = self._resolve_continuity_static()
        player = self.resolver(self.export_root, "assets/player/main.js").read_bytes()
        try: patched = patch_player(player)
        except LiveRuntimeUnsupported as exc: raise LiveHostError(str(exc)) from exc
        self._profile = Path(tempfile.mkdtemp(prefix="obed-live-chrome-"))
        try:
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
            if self._continuity_mode == "pending":
                installed = bool(self._transport.evaluate("!!window.__OBED_P2_PRESERVE__"))
                if installed:
                    self._continuity_mode, self._continuity_reason = "qualified", None
                else:
                    self._continuity_mode, self._continuity_reason = "unsupported", _CONTINUITY_VIEWPORT_REASON
            self._logger.log(
                "continuity", mode=self._continuity_mode, reason=self._continuity_reason,
                runtimePlan=self._continuity_runtime_plan,
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
            "semantics": "restart-at-initial-state",
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
                "droppedFrames:q.droppedVideoFrames,totalFrames:q.totalVideoFrames};})"
            )
        except Exception:
            return None

    def execute(self, operation: str, slide: int | None = None) -> PlayerObservation:
        transport = self._require_transport()
        started = time.monotonic()
        before = self.observe()
        before_revision, before_scene = self._runtime_revision, before.scene_id
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
        if error is not None: fields["error"] = error
        self._logger.log("execute", **fields)

    def _execute(self, operation: str, slide: int | None, transport: ChromeCdp, before: PlayerObservation, before_revision: int | None) -> PlayerObservation:
        if operation == "advance" and before.busy:
            raise PlayerCommandRejected("Player is busy.")
        if operation == "advance" and not self._can_advance:
            raise PlayerCommandRejected("Player has no next manual action.")
        if operation == "goTo" and before.busy:
            raise PlayerCommandRejected("Player is busy.")
        if operation in ("advance", "goTo"):
            transport.evaluate("window.focus();document.body.focus()")
        if operation == "advance": transport.key(" ", "Space", 32)
        elif operation == "goTo":
            if slide is None: raise PlayerCommandRejected("A slide number is required.")
            player_index = next((int(s["playerIndex"]) for s in self.slides if s.get("originalOrdinal") == slide and not s.get("skipped")), None)
            if player_index is None: raise PlayerCommandRejected("Original slide is unavailable or skipped.")
            if self._continuity_mode == "qualified":
                transport.evaluate("window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.clear && window.__OBED_P2_PRESERVE__.clear()")
            for digit in str(player_index + 1): transport.key(digit, "Digit" + digit, ord(digit))
            transport.key("Enter", "Enter", 13)
        elif operation == "hide": transport.evaluate("window.__obedOutput.hide()")
        elif operation == "show": transport.evaluate("window.__obedOutput.show()")
        else: raise LiveHostError("Unsupported player operation.")
        if operation in ("hide", "show"):
            return self.observe()
        return self._wait_for_ack(before_revision)

    def _wait_for_ack(self, previous_revision: int | None) -> PlayerObservation:
        """Wait for actual input delivery, without treating it as scene completion."""
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            observed = self.observe()
            if self._runtime_revision != previous_revision:
                return observed
            time.sleep(.05)
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
                    self._logger.log("stop", released=[], errors=[])
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
                self._logger.log("stop", released=released, errors=[str(exc) for exc in errors])
                self._logger.close()
            if errors:
                raise LiveHostError("Program player did not fully stop.")
