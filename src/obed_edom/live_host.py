"""The single, server-owned Chrome player used for HDMI program output.

This is deliberately a small adapter: it does not interpret Keynote scenes or
create a second player for a presenter.  The patched Keynote runtime remains
the authority for whether an input has settled.
"""

from __future__ import annotations

import json
import mimetypes
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

from .html_preview import safe_export_file
from .live_runtime import LiveRuntimeUnsupported, patch_player
from .live_session import PlayerCommandRejected, PlayerObservation


class LiveHostError(RuntimeError):
    """The owned browser cannot provide an observed player state."""


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
    def __init__(self, root: Path, patched_player: bytes, resolver: Callable[[Path, str], Path] = safe_export_file) -> None:
        self.root, self.patched_player, self.resolver = root, patched_player, resolver
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
                try:
                    if relative == "assets/player/main.js":
                        owner._send_bytes(self, owner.patched_player, "application/javascript")
                    elif relative == "program.html":
                        owner._send_bytes(self, owner._program_html(), "text/html")
                    else:
                        path = owner.resolver(owner.root, relative)
                        owner._send_file(self, path)
                except (BrokenPipeError, ConnectionResetError):
                    return
                except Exception:
                    self.send_error(404)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.httpd.server_port}/program.html"

    @staticmethod
    def _send_bytes(handler: BaseHTTPRequestHandler, data: bytes, content_type: str) -> None:
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)

    @staticmethod
    def _send_file(handler: BaseHTTPRequestHandler, path: Path) -> None:
        length = path.stat().st_size
        start, end = 0, length - 1
        requested = handler.headers.get("Range", "")
        if requested.startswith("bytes="):
            first, _, last = requested[6:].partition("-")
            if not first.isdigit() or (last and not last.isdigit()):
                handler.send_error(416)
                return
            start = int(first)
            end = int(last) if last else end
            if start > end or end >= length:
                handler.send_error(416)
                return
            handler.send_response(206)
            handler.send_header("Content-Range", f"bytes {start}-{end}/{length}")
        else:
            handler.send_response(200)
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        handler.send_header("Content-Length", str(end - start + 1))
        handler.end_headers()
        with path.open("rb") as source:
            source.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = source.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                handler.wfile.write(chunk)
                remaining -= len(chunk)

    def _program_html(self) -> bytes:
        source = self.resolver(self.root, "index.html").read_text()
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
        return (source[: body.end()] + overlay + source[body.end() :]).encode()

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        if self.thread:
            self.thread.join(timeout=2)
            self.thread = None


class ChromeCdp:
    """Synchronous CDP transport with one socket and serialized request IDs."""
    def __init__(self, chrome: Path, profile: Path, display: OutputDisplay, *, headless: bool = False) -> None:
        self.chrome, self.profile, self.display, self.headless = chrome, profile, display, headless
        self.proc: subprocess.Popen[bytes] | None = None
        self.ws: Any = None
        self.port: int | None = None
        self._id = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        from websockets.sync.client import connect
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
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
            self.stop()
            raise LiveHostError("Chrome CDP did not start.")
        self.call("Runtime.enable")
        self.call("Page.enable")
        if not self.headless:
            window = self.call("Browser.getWindowForTarget")
            self.call("Browser.setWindowBounds", windowId=window["windowId"], bounds={"windowState": "fullscreen"})

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        if not self.ws or not self.proc or self.proc.poll() is not None: raise LiveHostError("Program browser stopped unexpectedly.")
        with self._lock:
            self._id += 1
            request_id = self._id
            self.ws.send(json.dumps({"id": request_id, "method": method, "params": params}))
            while True:
                try: message = json.loads(self.ws.recv(timeout=15))
                except Exception as exc: raise LiveHostError("Program browser CDP connection failed.") from exc
                if message.get("id") == request_id:
                    if "error" in message: raise LiveHostError(f"CDP {method} failed: {message['error'].get('message', 'unknown error')}")
                    return message.get("result") or {}

    def evaluate(self, expression: str) -> Any:
        result = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=False)
        if result.get("exceptionDetails"): raise LiveHostError("Program browser evaluation failed.")
        return (result.get("result") or {}).get("value")

    def key(self, key: str, code: str, vk: int) -> None:
        values = {"key": key, "code": code, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
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
        if self.ws:
            try: self.ws.close()
            except Exception: pass
            self.ws = None
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)


class LiveOutputHost:
    def __init__(self, export_root: Path, slides: list[dict[str, Any]], *, display_id: int | None = None, chrome_path: Path = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"), headless: bool = False, transport_factory: Callable[..., ChromeCdp] = ChromeCdp, server_factory: Callable[..., _AssetServer] = _AssetServer, resolver: Callable[[Path, str], Path] = safe_export_file, timeout_s: float = 12.0) -> None:
        self.export_root, self.slides, self.display = export_root, slides, choose_display(display_id, headless=headless)
        self.chrome_path, self.headless, self.transport_factory, self.server_factory, self.resolver, self.timeout_s = chrome_path, headless, transport_factory, server_factory, resolver, timeout_s
        self._transport: ChromeCdp | None = None
        self._server: _AssetServer | None = None
        self._original_by_player = {
            int(slide["playerIndex"]): int(slide["originalOrdinal"])
            for slide in slides
            if not slide.get("skipped") and isinstance(slide.get("playerIndex"), int)
        }
        self._stopped = False
        self._profile: Path | None = None
        self._runtime_revision: int | None = None
        self._can_advance: bool | None = None
        self._can_go_to: bool | None = None
        self._canvas = {"width": 1920, "height": 1080}
        self._viewport = {"width": self.display.width, "height": self.display.height}
        self._expected_scene_count: int | None = None

    @property
    def output(self) -> dict[str, Any]:
        """Detected physical output geometry, available before browser startup."""
        return {
            **self.display.as_output(),
            "viewport": dict(self._viewport),
            "canvas": dict(self._canvas),
            "width": self._viewport["width"],
            "height": self._viewport["height"],
        }

    def start(self) -> PlayerObservation:
        if self._stopped:
            raise LiveHostError("Program player has been stopped.")
        if self._transport:
            return self.observe()
        self._validate_export()
        self._expected_scene_count = self._authored_scene_count()
        player = self.resolver(self.export_root, "assets/player/main.js").read_bytes()
        try: patched = patch_player(player)
        except LiveRuntimeUnsupported as exc: raise LiveHostError(str(exc)) from exc
        self._profile = Path(tempfile.mkdtemp(prefix="obed-live-chrome-"))
        try:
            self._server = self.server_factory(self.export_root, patched, self.resolver)
            url = self._server.start()
            self._transport = self.transport_factory(self.chrome_path, self._profile, self.display, headless=self.headless)
            self._transport.start()
            self._transport.goto(url)
            return self._wait_settled()
        except Exception:
            self.stop()
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
        return PlayerObservation(
            original_slide=original,
            scene_id=str(scene) if scene is not None else None,
            build_index=value.get("buildIndex") if isinstance(value.get("buildIndex"), int) else None,
            revision=self._runtime_revision,
            busy=bool(value.get("busy", True)),
            output_visible=bool(
                transport.evaluate(
                    "document.getElementById('obed-output-black').style.display==='none'"
                )
            ),
            output=self.output,
        )

    def execute(self, operation: str, slide: int | None = None) -> PlayerObservation:
        transport = self._require_transport()
        before = self.observe()
        before_revision = self._runtime_revision
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
        self._stopped = True
        if self._transport:
            self._transport.stop()
            self._transport = None
        if self._server:
            self._server.stop()
            self._server = None
        if self._profile:
            shutil.rmtree(self._profile, ignore_errors=True)
            self._profile = None
