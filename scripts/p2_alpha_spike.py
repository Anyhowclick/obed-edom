#!/usr/bin/env python3
"""P2 alpha-capture spike: transparent frames + decoded ProRes 4444.

Re-run from the ``feat/keynote-alpha-p2`` worktree:

    .venv/bin/python scripts/p2_alpha_spike.py

Does not open or modify owner source decks. Does not implement P3.
Does not download a Playwright browser. Uses system Chrome over CDP when present.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import resource
import socket
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from obed_edom.dsk_live import keynote_running  # noqa: E402
from obed_edom.html_alpha_probe import (  # noqa: E402
    CLOCK_MIN_RAF,
    CLOCK_WINDOW_S,
    FPS,
    HEARTBEAT_MIN_EXECUTED,
    IDENTITY_NEAR_DUP_MAE_MAX,
    IDENTITY_OWN_CLOSER_MARGIN,
    PROBE_VERSION,
    current_slide_query_url,
    analyze_rgba,
    black_content_ok,
    capability_row,
    color_key_near_black,
    copy_unmodified_export,
    decode_prores_rgba,
    decoded_alpha_report,
    encode_prores_4444,
    file_identity,
    identities_match,
    inventory_deck,
    inventory_export,
    keynote_document_count,
    leftover_object_layers,
    load_rgba,
    make_black_content_fixture,
    page_websocket_url,
    painted_identity,
    progress_metric,
    render_pdf_page_rgba,
    save_png,
    timing_repeatability,
    write_composites,
    write_json,
    write_patched_export,
)
from obed_edom.html_preview import PLAYER_JS, file_sha256  # noqa: E402

DEFAULT_SOURCE = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Alpha_DSK.key")
DEFAULT_MIXED = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/DSK_Gen_Export_Input.key")
DEFAULT_HTML_REF = Path("/Users/anyhowclick/.cursor/worktrees/obed-edom/jt4h/output/p1-live/dsk-html")
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
SETTLE_S = 1.2
CLICK_WAIT_S = 1.6
HOLD_FRAMES = 8
MOTION_FRAMES = 36  # 1.2 s at 30 fps; LineDraw is 0.7–1.0 s


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


def _serve(root: Path) -> tuple[ThreadingHTTPServer, str]:
    handler = lambda *a, **k: _QuietHandler(*a, directory=str(root), **k)  # noqa: E731
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}/index.html"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _png_to_rgba(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as img:
        rgba = img.convert("RGBA")
        arr = np.frombuffer(rgba.tobytes(), dtype=np.uint8)
        return arr.reshape((rgba.height, rgba.width, 4)).copy()


class ChromeCdp:
    """System Chrome + CDP. Real Input.* events; never calls player function names."""

    START_TIMEOUT_S = 20.0

    def __init__(self, chrome: Path, profile: Path, width: int = 1920, height: int = 1080) -> None:
        self.chrome = chrome
        self.profile = profile
        self.width = width
        self.height = height
        self.proc: subprocess.Popen[bytes] | None = None
        self._ws: Any = None
        self._next_id = 0
        self.peak_rss = 0
        self.console: list[dict[str, Any]] = []
        self.port: int | None = None

    async def start(self) -> None:
        """Spawn Chrome and attach. Anything that goes wrong AFTER the spawn kills
        the process before re-raising: a Chrome whose driver never attached is an
        orphan nothing will ever close, and the next run then shares the machine
        with it."""
        self.profile.mkdir(parents=True, exist_ok=True)
        self._spawn()
        try:
            await self._attach()
        except BaseException:
            self._kill_proc()
            raise

    def _spawn(self) -> None:
        port = _free_port()
        self.port = port
        self.proc = subprocess.Popen(
            [
                str(self.chrome),
                "--headless=new",
                "--disable-gpu",
                f"--remote-debugging-port={port}",
                "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={self.profile}",
                f"--window-size={self.width},{self.height}",
                "--force-device-scale-factor=1",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                "--autoplay-policy=no-user-gesture-required",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    async def _attach(self) -> None:
        import urllib.request
        import websockets

        port = self.port
        ready = False
        deadline = time.monotonic() + self.START_TIMEOUT_S
        while time.monotonic() < deadline:
            self._sample_rss()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=0.5) as resp:
                    json.loads(resp.read().decode())
                    ready = True
                    break
            except Exception:
                await asyncio.sleep(0.1)
        if not ready:
            raise RuntimeError("Chrome CDP did not come up")
        # /json/version is the browser target and has no Runtime/Page domain.
        # Capture must attach to a page target from /json/list.
        ws_url = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=0.5) as resp:
                    targets = json.loads(resp.read().decode())
                ws_url = page_websocket_url(targets)
                if ws_url:
                    break
            except Exception:
                pass
            await asyncio.sleep(0.1)
        if not ws_url:
            raise RuntimeError("Chrome has no page CDP target")
        self._ws = await websockets.connect(ws_url, max_size=None)
        await self.call("Runtime.enable")
        await self.call("Page.enable")
        await self.call("Log.enable")
        await self.call(
            "Emulation.setDeviceMetricsOverride",
            width=self.width,
            height=self.height,
            deviceScaleFactor=1,
            mobile=False,
        )
        await self.call(
            "Emulation.setDefaultBackgroundColorOverride",
            color={"r": 0, "g": 0, "b": 0, "a": 0},
        )

    def _sample_rss(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        try:
            proc = subprocess.run(
                ["ps", "-o", "rss=", "-p", str(self.proc.pid)],
                capture_output=True,
                text=True,
                check=False,
            )
            text = proc.stdout.strip()
            if text:
                self.peak_rss = max(self.peak_rss, int(text) * 1024)
        except Exception:
            return

    async def call(self, method: str, **params: Any) -> Any:
        assert self._ws is not None
        self._next_id += 1
        msg_id = self._next_id
        await self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=30)
            payload = json.loads(raw)
            if payload.get("method") in {"Runtime.consoleAPICalled", "Log.entryAdded", "Runtime.exceptionThrown"}:
                self.console.append(payload)
                continue
            if payload.get("id") == msg_id:
                if "error" in payload:
                    raise RuntimeError(f"CDP {method} failed: {payload['error']}")
                return payload.get("result") or {}

    async def goto(self, url: str) -> None:
        await self.call("Page.navigate", url=url)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                state = await self.evaluate("document.readyState")
            except Exception:
                await asyncio.sleep(0.05)
                continue
            if state == "complete":
                break
            await asyncio.sleep(0.05)

    async def evaluate(self, expression: str, await_promise: bool = False) -> Any:
        result = await self.call("Runtime.evaluate", expression=expression, awaitPromise=await_promise, returnByValue=True)
        if result.get("exceptionDetails"):
            raise RuntimeError(f"evaluate failed: {result['exceptionDetails']}")
        return (result.get("result") or {}).get("value")

    async def screenshot(self) -> np.ndarray:
        result = await self.call("Page.captureScreenshot", format="png", omitBackground=True, fromSurface=True)
        return _png_to_rgba(base64.b64decode(result["data"]))

    async def object_composite(self) -> tuple[np.ndarray | None, list[dict[str, Any]]]:
        raw = await self.evaluate("window.__OBED_P2_PROBE__.objectComposite()")
        if not raw or not raw.get("png"):
            return None, []
        b64 = str(raw["png"]).split(",", 1)[-1]
        return _png_to_rgba(base64.b64decode(b64)), list(raw.get("layers") or [])

    async def key(self, key: str, code: str, vk: int) -> None:
        common = {"key": key, "code": code, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
        await self.call("Input.dispatchKeyEvent", type="keyDown", **common)
        await self.call("Input.dispatchKeyEvent", type="keyUp", **common)

    async def click_center(self) -> None:
        x, y = self.width / 2, self.height / 2
        await self.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        await self.call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
        await self.call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1)

    async def close(self) -> None:
        try:
            if self._ws is not None:
                await self._ws.close()
        except Exception:
            pass
        self._kill_proc()

    def _kill_proc(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)


async def _wait_ready(
    chrome: ChromeCdp,
    timeout_s: float = 20,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = await chrome.evaluate("window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.ready() : {missing:true}")
        if last and last.get("canvasCount", 0) >= 1 and last.get("stageVisibility") == "visible":
            return last
        await asyncio.sleep(0.15)
    return last or {"error": "player never became ready"}


async def _isolate_slide(chrome: ChromeCdp, url: str, exported_1based: int) -> dict[str, Any]:
    """Fresh page via ?currentSlide=N (exported 1-based). Hash would select a scene."""
    await chrome.goto("about:blank")
    await asyncio.sleep(0.05)
    await chrome.goto(current_slide_query_url(url, exported_1based))
    return await _wait_ready(chrome)


async def _wait_painted(chrome: ChromeCdp, timeout_s: float = 12.0, min_progress: float = 0.02) -> np.ndarray | None:
    """Photo/movie PDFs can stay black after canvasCount>=1."""
    last = None
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        last = await chrome.screenshot()
        if progress_metric(last) >= min_progress:
            return last
        await asyncio.sleep(0.2)
    return last


def _load_pdf_rasters(out: Path) -> dict[int, list[np.ndarray]]:
    dest = out / "pdf-rasters"
    by_ordinal: dict[int, list[np.ndarray]] = {}
    if not dest.is_dir():
        return by_ordinal
    for path in sorted(dest.glob("slide-*-page-*.png")):
        try:
            ordinal = int(path.stem.split("-")[1])
        except (IndexError, ValueError):
            continue
        by_ordinal.setdefault(ordinal, []).append(load_rgba(path))
    return by_ordinal


async def _capture_sequence(chrome: ChromeCdp, n: int, fps: int = FPS) -> list[tuple[float, np.ndarray]]:
    """Sample at the declared fps. If a screenshot is late, skip the missed slot.

    Does not grab as-fast-as-possible (that duplicates hold frames and drops motion).
    """
    frames: list[tuple[float, np.ndarray]] = []
    interval = 1.0 / fps
    t0 = time.perf_counter()
    slot = 0
    while len(frames) < n:
        now = time.perf_counter()
        intended = t0 + slot * interval
        if now > intended + interval:
            slot += 1
            continue
        if intended - now > 0:
            await asyncio.sleep(intended - now)
        chrome._sample_rss()
        frame = await chrome.screenshot()
        frames.append((time.perf_counter() - t0, frame))
        slot += 1
    return frames


async def _advance_build(chrome: ChromeCdp) -> dict[str, Any]:
    """Real CDP keyboard/mouse — not jumpToSlide / advanceToNextBuild."""
    before_hash = await chrome.evaluate("window.__OBED_P2_PROBE__.hash()")
    before = await chrome.screenshot()
    before_metric = progress_metric(before)
    await chrome.key(" ", "Space", 32)
    return {
        "input": "Space",
        "dispatched": True,
        "hashBefore": before_hash,
        "progressBefore": before_metric,
        "calledPrivatePlayerFunctions": False,
        "beforeFrame": before,
    }


def _rss_self() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def _write_run_md(out: Path, args: argparse.Namespace) -> None:
    text = f"""# P2 alpha spike — re-run

From the `feat/keynote-alpha-p2` worktree (do not run inside the P1 worktree):

```bash
cd {REPO}
.venv/bin/python scripts/p2_alpha_spike.py \\
  --source "{args.source}" \\
  --html-ref "{args.html_ref}" \\
  --mixed "{args.mixed}" \\
  --out "{out}"
```

Offline inventory only:

```bash
.venv/bin/python scripts/p2_alpha_spike.py --skip-capture --out "{out}"
```

Requirements: the repo `.venv` (`uv sync --extra iwa --extra test`), system
Google Chrome (no Playwright download), and the unmodified P1 HTML export.
Never opens `Alpha_DSK.key` or `Alpha_Wall.key`. P3 is not implemented.
"""
    (out / "RUN.md").write_text(text, encoding="utf-8")


def _capability_matrix(
    dsk: dict[str, Any],
    export: dict[str, Any] | None,
    captures: dict[int, dict[str, Any]],
    alphas: dict[int, dict[str, Any]],
    mixed: dict[str, Any] | None,
) -> dict[str, Any]:
    export_by_ord = {row["originalOrdinal"]: row for row in (export or {}).get("slides") or []}
    rows = []
    for slide in dsk["slides"]:
        ordinal = slide["originalOrdinal"]
        exp = export_by_ord.get(ordinal)
        rows.append(
            capability_row(
                ordinal=ordinal,
                skipped=slide["skipped"],
                magic_move=slide["magicMove"],
                has_character=slide["hasCharacterEffect"],
                has_build_out=slide["hasBuildOut"],
                has_movie=slide["hasMovieStart"],
                has_line_draw=slide["hasLineDraw"],
                iwa_clicks=slide["iwa"]["operatorClickCount"],
                kpf_clicks=None if exp is None else exp["kpfClickCount"],
                capture=captures.get(ordinal),
                alpha=alphas.get(ordinal),
                canvas=(dsk["canvas"]["width"], dsk["canvas"]["height"]),
            )
        )
    mixed_rows = []
    if mixed and mixed.get("slides"):
        for slide in mixed["slides"]:
            if slide["originalOrdinal"] not in {11, 12, 13}:
                continue
            mixed_rows.append(
                capability_row(
                    ordinal=slide["originalOrdinal"],
                    skipped=slide["skipped"],
                    magic_move=slide["magicMove"],
                    has_character=slide["hasCharacterEffect"],
                    has_build_out=slide["hasBuildOut"],
                    has_movie=slide["hasMovieStart"],
                    has_line_draw=slide["hasLineDraw"],
                    iwa_clicks=slide["iwa"]["operatorClickCount"],
                    kpf_clicks=None,
                    capture={"error": "HTML capture not run (1.8 GB wall deck, 7680×1080)"},
                    alpha=None,
                    canvas=(mixed["canvas"]["width"], mixed["canvas"]["height"]),
                )
            )
    return {
        "effects": {
            "automatic": "partial — Alpha_DSK slide 3 LineDrawForLine + dissolve are automatic=True companions of one click",
            "with-previous": "same as automatic companions on slide 3; delay=0",
            "after-previous": "unsupported — no delayed after-previous chain on Alpha_DSK",
            "build-out": "unsupported — none on Alpha_DSK",
            "magicMove": "unsupported — Alpha_DSK has no Magic Move (every transition is none). DSK_Gen_Export_Input slides 11–12 have Magic Move and are refused",
            "characterEffects": "unsupported — none on Alpha_DSK",
            "lineDraws": "supported as one operator click (LineDraw + LineDrawForLine + dissolve)",
            "movieStart": "refused for transparent animation — Alpha_DSK slide 5 and mixed slides 11–13",
            "mixedVideo": "unsupported — DSK_Gen_Export_Input 11–13 are automatic movie-start on a 7680×1080 wall canvas",
        },
        "alphaDskHasMagicMove": False,
        "slides": rows,
        "mixedMovieSlides": mixed_rows,
    }


def _report_md(out: Path, report: dict[str, Any]) -> None:
    lines = [
        "# P2 alpha / timing capability report",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Probe version: {PROBE_VERSION}",
        f"Declared FPS: {FPS}",
        "",
        "## Source fingerprints",
        "",
        "Alpha_DSK.key must be unchanged (sha256, mtime, inode, size).",
        "",
        "```json",
        json.dumps(report.get("fingerprints"), indent=2),
        "```",
        "",
        "## Identity (Gate 1)",
        "",
        json.dumps((report.get("captureExtras") or {}).get("identity"), indent=2),
        "",
        "## What was captured",
        "",
        report.get("summaryText", ""),
        "",
        "## Capability matrix",
        "",
        json.dumps(report.get("capability"), indent=2),
        "",
        "## Whether P3 should proceed",
        "",
        report.get("p3Advice", ""),
        "",
        "## Paths",
        "",
        f"- Output root: `{out}`",
        f"- RUN.md: `{out / 'RUN.md'}`",
        "",
    ]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _run_capture(
    chrome: ChromeCdp,
    url: str,
    export: dict[str, Any],
    out: Path,
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]], dict[str, Any]]:
    captures: dict[int, dict[str, Any]] = {}
    alphas: dict[int, dict[str, Any]] = {}
    extras: dict[str, Any] = {"clock": None, "clicks": {}, "timing": None, "console": [], "identity": {}}
    rasters = _load_pdf_rasters(out)
    previous_plates: dict[int, np.ndarray] = {}
    previous_layers: dict[int, list[dict[str, Any]]] = {}
    await chrome.goto("about:blank")
    await chrome.goto(current_slide_query_url(url, 1))
    ready = await _wait_ready(chrome)
    extras["ready"] = ready
    extras["probeVersion"] = await chrome.evaluate("window.__OBED_P2_PROBE__ && window.__OBED_P2_PROBE__.version")
    if extras["probeVersion"] != PROBE_VERSION:
        raise RuntimeError(f"probe version {extras['probeVersion']!r} is not {PROBE_VERSION}")
    extras["clockIdle"] = await chrome.evaluate(
        f"window.__OBED_P2_PROBE__.clock({int(CLOCK_WINDOW_S * 1000)})",
        await_promise=True,
    )
    extras["clock"] = await chrome.evaluate(
        f"window.__OBED_P2_PROBE__.heartbeat({int(CLOCK_WINDOW_S * 1000)})",
        await_promise=True,
    )
    extras["clock"]["pass"] = int(extras["clock"].get("executed") or 0) >= HEARTBEAT_MIN_EXECUTED
    extras["clock"]["declaredMinExecuted"] = HEARTBEAT_MIN_EXECUTED
    extras["clock"]["idleRequested"] = extras["clockIdle"].get("requested")
    extras["clock"]["note"] = "idle zero requests is not a freeze; heartbeat counts executed callbacks"
    extras["privateFnsOnWindow"] = await chrome.evaluate(
        "({jump: typeof window.jumpToSlide, next: typeof window.advanceToNextBuild, back: typeof window.goBackToPreviousBuild})"
    )

    for slide in export["slides"]:
        ordinal = slide["originalOrdinal"]
        dest = out / "frames" / f"slide-{ordinal:02d}"
        dest.mkdir(parents=True, exist_ok=True)
        ready = await _isolate_slide(chrome, url, int(slide["currentSlide"]))
        await asyncio.sleep(SETTLE_S)
        extras.setdefault("canvasAlpha", {})[ordinal] = await chrome.evaluate("window.__OBED_P2_PROBE__.canvasAlpha()")
        live_hash = await chrome.evaluate("window.__OBED_P2_PROBE__.hash()")
        live_search = await chrome.evaluate("window.__OBED_P2_PROBE__.ready().search")
        initial = await _wait_painted(chrome)
        if initial is None:
            initial = await chrome.screenshot()
        write_composites(initial, dest / "initial-page", "settled")
        save_png(initial, dest / "initial-page" / "0000.png")
        obj, layers = await chrome.object_composite()
        extras.setdefault("objectLayers", {})[ordinal] = layers
        if obj is not None:
            write_composites(obj, dest / "initial-objects", "settled")
            save_png(obj, dest / "initial-objects" / "0000.png")
        identity = painted_identity(
            initial,
            ordinal=ordinal,
            live_hash=str(live_hash or ""),
            rasters_by_ordinal=rasters,
            previous_plates=previous_plates,
            layers=layers,
            previous_layers=previous_layers,
            expected_starting_scene=int(slide["startingScene"]),
            require_starting_scene=False,
        )
        identity["liveSearch"] = live_search
        identity["requestedUrl"] = current_slide_query_url("index.html", int(slide["currentSlide"]))
        leftover = leftover_object_layers(layers, previous_layers)
        if leftover and leftover not in identity["reasons"]:
            identity["reasons"].append(leftover)
            identity["pass"] = False
        extras["identity"][ordinal] = identity
        write_json(dest / "identity.json", identity)
        # Gate 3 scores the composed page only. Object-composites never set alpha pass.
        analysis = analyze_rgba(initial, content_rects=slide.get("accessibilityRects") or [])
        analysis["source"] = "page-screenshot"
        analysis["pageAlphaMin"] = int(initial[:, :, 3].min())
        click_info: dict[str, Any] | None = None
        motion_a: list[tuple[float, np.ndarray]] = []
        motion_b: list[tuple[float, np.ndarray]] = []
        slide_timing: dict[str, Any] | None = None
        wants_click = slide["kpfClickCount"] > 0 and not any(
            "movie-start" in str((fx.get("name") or "")).lower()
            or str((fx.get("name") or "")).lower() == "rendermovie"
            for ev in slide["kpfOperatorClicks"]
            for fx in ev.get("effects") or []
        )
        if wants_click and identity["pass"]:
            raf0 = await chrome.evaluate("window.__OBED_P2_PROBE__.rafTimes.length")
            click_info = await _advance_build(chrome)
            motion = await _capture_sequence(chrome, MOTION_FRAMES)
            raf1 = await chrome.evaluate("window.__OBED_P2_PROBE__.rafTimes.length")
            after = motion[-1][1] if motion else click_info.pop("beforeFrame")
            before = click_info.pop("beforeFrame")
            hash_after = await chrome.evaluate("window.__OBED_P2_PROBE__.hash()")
            click_info["advanced"] = not np.array_equal(before, after)
            click_info["hashAfter"] = hash_after
            click_info["sceneAfter"] = str(hash_after or "")
            click_info["sceneChanged"] = str(hash_after or "") != str(click_info.get("hashBefore") or "")
            click_info["progressAfter"] = progress_metric(after)
            click_info["rgbMae"] = float(np.mean(np.abs(before.astype(np.int16) - after.astype(np.int16))))
            click_info["rafDuringClick"] = int(raf1) - int(raf0)
            after_ident = painted_identity(
                after,
                ordinal=ordinal,
                live_hash=str(hash_after or ""),
                rasters_by_ordinal=rasters,
                previous_plates={k: v for k, v in previous_plates.items() if k != ordinal},
                expected_starting_scene=int(slide["startingScene"]),
                require_starting_scene=False,
            )
            click_info["identityAfter"] = after_ident
            click_info["stillIdentifiable"] = bool(after_ident.get("pass"))
            click_info["gate1InitialPass"] = True
            if not after_ident.get("pass"):
                click_info["reasons"] = ["click settled plate failed painted identity"]
            elif click_info["sceneChanged"]:
                click_info["reasons"] = [
                    f"scene {click_info.get('hashBefore')} → {hash_after} (allowed if this slide remains identifiable)"
                ]
            distinct = 1
            for i in range(1, len(motion)):
                if not np.array_equal(motion[i][1], motion[i - 1][1]):
                    distinct += 1
            click_info["distinctMotionFrames"] = distinct
            save_png(before, dest / "click-1" / "before.png")
            motion_a = motion
            for index, (_ts, frame) in enumerate(motion):
                save_png(frame, dest / "click-1" / f"{index:04d}.png")
            if motion:
                last = motion[-1][1]
                write_composites(last, dest / "click-1-settled-page", "settled")
                obj_last, _layers = await chrome.object_composite()
                if obj_last is not None:
                    write_composites(obj_last, dest / "click-1-settled-objects", "settled")
                write_json(dest / "click-1" / "timestamps.json", [ts for ts, _frame in motion])
            ready = await _isolate_slide(chrome, url, int(slide["currentSlide"]))
            await asyncio.sleep(SETTLE_S)
            await _advance_build(chrome)
            motion_b = await _capture_sequence(chrome, MOTION_FRAMES)
            slide_timing = timing_repeatability(motion_a, motion_b)
            extras["timing"] = slide_timing
            extras["clicks"][ordinal] = {k: v for k, v in click_info.items() if k != "beforeFrame"}
        elif wants_click and not identity["pass"]:
            extras["clicks"][ordinal] = {
                "skipped": True,
                "reason": "Gate 1 identity failed; Space is not a LineDraw proof on a stale plate",
            }
        previous_plates[ordinal] = initial
        if layers:
            previous_layers[ordinal] = layers
        write_json(dest / "identity.json", identity)
        captures[ordinal] = {
            "ready": ready,
            "identity": identity,
            "click": None if click_info is None else {k: v for k, v in click_info.items() if k != "beforeFrame"},
            "timing": slide_timing,
            "initialShape": list(initial.shape),
            "pageOpaque": int(initial[:, :, 3].min()) >= 255,
        }
        alphas[ordinal] = analysis
        write_json(dest / "alpha.json", analysis)

    ident_ok = all(
        (captures.get(s["originalOrdinal"]) or {}).get("identity", {}).get("pass")
        for s in export["slides"]
    )
    genesis_click = extras.get("clicks", {}).get(3) or {}
    genesis_motion = bool(genesis_click.get("stillIdentifiable")) and int(genesis_click.get("distinctMotionFrames") or 0) >= 2
    extras["control"] = {
        "identitiesPassed": ident_ok,
        "genesisStillIdentifiable": genesis_click.get("stillIdentifiable"),
        "genesisDistinctMotionFrames": genesis_click.get("distinctMotionFrames"),
        "heartbeatExecuted": (extras.get("clock") or {}).get("executed"),
        "textureTrace": None,
    }
    if ident_ok and genesis_motion and (extras.get("clock") or {}).get("pass"):
        await _isolate_slide(chrome, url, 2)
        await asyncio.sleep(SETTLE_S)
        initial_tex = await chrome.evaluate("window.__OBED_P2_PROBE__.textureInventory()")
        await chrome.key(" ", "Space", 32)
        await asyncio.sleep(1.0)
        final_tex = await chrome.evaluate("window.__OBED_P2_PROBE__.textureInventory()")
        extras["control"]["textureTrace"] = {"genesisInitial": initial_tex, "genesisAfterSpace": final_tex}
        extras["control"]["note"] = (
            "inspect only; no colour-key; do not drop full-size canvases; "
            "stop if full-slide textures flatten background and artwork"
        )
    else:
        extras["control"]["textureTraceSkipped"] = "identity/motion/heartbeat not all green"
    extras["console"] = chrome.console
    extras["probeConsole"] = await chrome.evaluate("window.__OBED_P2_PROBE__.console")
    extras["identityTolerances"] = {
        "nearDupMaeMax": IDENTITY_NEAR_DUP_MAE_MAX,
        "ownCloserMargin": IDENTITY_OWN_CLOSER_MARGIN,
    }
    return captures, alphas, extras



def _mixed_inventory(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False, "path": str(path), "reason": "file not on this machine"}
    ident = file_identity(path)
    inv = inventory_deck(path)
    return {
        "available": True,
        "identity": ident.as_dict(),
        "inventory": {
            "canvas": inv["canvas"],
            "slideCount": inv["slideCount"],
            "skipped": inv["skipped"],
            "slides": [s for s in inv["slides"] if s["originalOrdinal"] in {11, 12, 13}],
        },
        "htmlCapture": "not run — 1.8 GB source, 7680×1080 wall canvas, Magic Move + automatic movie-start",
    }


def _pdf_raster_notes(export_root: Path, export: dict[str, Any], out: Path) -> list[dict[str, Any]]:
    notes = []
    dest = out / "pdf-rasters"
    dest.mkdir(parents=True, exist_ok=True)
    for slide in export["slides"]:
        uuid = slide["exportedUuid"]
        pdfs = list((Path(export_root) / "assets" / uuid).rglob("*.pdf"))
        pdfs = [p for p in pdfs if p.suffix == ".pdf" and not str(p).endswith(".pdfp")]
        if not pdfs:
            continue
        pdf = pdfs[0]
        pages = []
        for index in range(min(3, len(slide["opacity"]["pdfPages"]))):
            arr = render_pdf_page_rgba(pdf, index)
            if arr is None:
                pages.append({"index": index, "rendered": False})
                continue
            analysis = analyze_rgba(arr)
            save_png(arr, dest / f"slide-{slide['originalOrdinal']:02d}-page-{index}.png")
            pages.append(
                {
                    "index": index,
                    "rendered": True,
                    "shape": list(arr.shape),
                    "transparentFrac": analysis["transparentFrac"],
                    "emptyBackgroundOk": analysis["samples"]["emptyBackgroundOk"],
                    "pass": analysis["pass"],
                }
            )
        notes.append({"originalOrdinal": slide["originalOrdinal"], "pdf": str(pdf), "pages": pages})
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--html-ref", type=Path, default=DEFAULT_HTML_REF)
    parser.add_argument("--mixed", type=Path, default=DEFAULT_MIXED)
    parser.add_argument("--out", type=Path, default=REPO / "output" / "p2-alpha-spike")
    parser.add_argument("--skip-capture", action="store_true")
    parser.add_argument("--fps", type=int, default=FPS)
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    _write_run_md(out, args)

    before = file_identity(args.source)
    write_json(out / "fingerprints-before.json", before.as_dict())
    if before.sha256 != "d8de34a942806f54fd401acb3ca7070774d1bb13331dc5dc39b200d63f64795c":
        # Do not refuse a legitimate replacement, but record drift against the plan table.
        pass

    keynote = {
        "running": keynote_running(),
        "documentCount": keynote_document_count(),
        "quit": False,
        "note": "P2 HTML path does not open Keynote. Quit is allowed only when document count is 0.",
    }
    if keynote["running"] and keynote["documentCount"] == 0:
        keynote["note"] = "Keynote is running with 0 documents; left running (HTML path does not need it)."
    elif keynote["running"] and (keynote["documentCount"] or 0) > 0:
        keynote["note"] = "Keynote holds documents — refusing any Keynote-touching step."

    fixture = make_black_content_fixture()
    keyed = color_key_near_black(fixture)
    fixture_dir = out / "fixtures"
    write_composites(fixture, fixture_dir, "black-content")
    write_composites(keyed, fixture_dir, "color-keyed-black")
    fixture_alpha = analyze_rgba(fixture, content_rects=[{"x": 200, "y": 200, "width": 600, "height": 200}])
    black_check = {
        "fixturePreservesBlack": black_content_ok(fixture),
        "colorKeyDestroysBlack": not black_content_ok(keyed),
        "fixtureAlphaPass": fixture_alpha["pass"],
        "colorKeyAlphaWouldLie": analyze_rgba(keyed)["pass"],
    }

    dsk = inventory_deck(args.source)
    write_json(out / "inventory-dsk.json", dsk)
    mixed = _mixed_inventory(args.mixed)
    write_json(out / "inventory-mixed.json", mixed)

    if not args.html_ref.is_dir():
        after = file_identity(args.source)
        write_json(out / "fingerprints-after.json", after.as_dict())
        report = {
            "fingerprints": {"before": before.as_dict(), "after": after.as_dict(), "unchanged": identities_match(before, after)},
            "keynote": keynote,
            "blackContent": black_check,
            "summaryText": f"HTML reference missing at {args.html_ref}. Inventory-only run.",
            "p3Advice": "P3 must not proceed — no capture evidence.",
            "capability": _capability_matrix(dsk, None, {}, {}, mixed.get("inventory")),
        }
        write_json(out / "report.json", report)
        _report_md(out, report)
        print(report["summaryText"])
        return 2

    unmodified = copy_unmodified_export(args.html_ref, out / "html-unmodified")
    patched = write_patched_export(out / "html-unmodified", out / "html-patched")
    export = inventory_export(Path(unmodified["root"]), dsk)
    write_json(out / "inventory-export.json", export)
    pdf_notes = _pdf_raster_notes(Path(unmodified["root"]), export, out)
    write_json(out / "pdf-rasters.json", pdf_notes)

    captures: dict[int, dict[str, Any]] = {}
    alphas: dict[int, dict[str, Any]] = {}
    extras: dict[str, Any] = {}
    capture_error = None
    if not args.skip_capture:
        if not CHROME.is_file():
            capture_error = "system Google Chrome is not installed; Playwright was not downloaded"
        else:
            server, url = _serve(Path(patched["root"]))
            chrome = ChromeCdp(CHROME, out / f"chrome-profile-{os.getpid()}-{int(time.time())}")
            try:
                asyncio.run(_boot_and_capture(chrome, url, export, out, captures, alphas, extras))
            except Exception as exc:
                import traceback
                capture_error = f"{exc}\n{traceback.format_exc()}"
            finally:
                server.shutdown()
    else:
        extras["skipped"] = True

    if capture_error:
        extras["error"] = capture_error
        for slide in dsk["slides"]:
            captures.setdefault(slide["originalOrdinal"], {"error": capture_error})

    # ProRes: always encode the black-content fixture (proves decoded alpha, not the codec name).
    # If slide 3 motion frames exist, encode those too.
    prores: dict[str, Any] = {}
    fixture_frames = [fixture, fixture, fixture]
    movie = encode_prores_4444(fixture_frames, out / "movies" / "black-content.mov", fps=args.fps)
    decoded = decode_prores_rgba(movie, out / "movies" / "black-content-decoded")
    prores["blackContent"] = {
        "movie": str(movie),
        "decoded": [str(p) for p in decoded],
        "decodedAlpha": decoded_alpha_report(fixture_frames, decoded),
        "blackPreservedAfterDecode": all(black_content_ok(load_rgba(p)) for p in decoded),
    }
    click_dir = out / "frames" / "slide-03" / "click-1"
    if click_dir.is_dir():
        motion_paths = sorted(p for p in click_dir.glob("*.png") if p.stem.isdigit())
        if motion_paths:
            frames = [load_rgba(p) for p in motion_paths]
            movie3 = encode_prores_4444(frames, out / "movies" / "slide-03-click1.mov", fps=args.fps)
            decoded3 = decode_prores_rgba(movie3, out / "movies" / "slide-03-click1-decoded")
            prores["slide3"] = {
                "movie": str(movie3),
                "decoded": [str(p) for p in decoded3],
                "decodedAlpha": decoded_alpha_report(frames, decoded3),
            }

    after = file_identity(args.source)
    write_json(out / "fingerprints-after.json", after.as_dict())
    capability = _capability_matrix(dsk, export, captures, alphas, mixed.get("inventory"))
    elapsed = time.monotonic() - started
    disk = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    slide_pass = []
    slide_fail = []
    for row in capability["slides"]:
        label = f"slide {row['originalOrdinal']}"
        if row["skipped"]:
            slide_fail.append(f"{label} skipped")
        elif row["refusals"]:
            slide_fail.append(f"{label}: {'; '.join(row['refusals'])}")
        elif row["supportedStaticAlpha"] or row["supportedAnimatedAlpha"]:
            slide_pass.append(label)
        else:
            slide_fail.append(label)

    any_static = any(row.get("supportedStaticAlpha") for row in capability["slides"])
    any_animated = any(row.get("supportedAnimatedAlpha") for row in capability["slides"])
    p3 = (
        "P3 should wait. No slide met identity then composed page alpha"
        + ("" if any_animated else " (and timing for animated clicks)")
        + ". Keep P1 HTML preview and stage-PNG export. Do not wire transparent animation export."
    )
    if any_animated:
        p3 = (
            "P3 should wait for owner review of the asset contract. "
            "At least one slide met identity, timing, and composed page alpha. "
            "Do not enable mixed video, Magic Move, or movie-start. Keep PNG stage export as the default."
        )
    elif any_static:
        p3 = (
            "P3 should wait. Static composed alpha passed identity on a subset, "
            "but no animated click group met timing + genuine alpha. Do not wire Exporter alpha."
        )
    if capture_error:
        p3 = (
            "P3 should wait. Capture blocker: "
            + capture_error
            + ". Inventory, opacity tracing, black-content, and synthetic ProRes still ran."
        )

    ident_pass = [
        f"slide {row['originalOrdinal']}"
        for row in capability["slides"]
        if row.get("identity")
    ]
    summary = (
        f"Captured={'no' if args.skip_capture or capture_error else 'yes'}. "
        f"Identity: {', '.join(ident_pass) or 'none'}. "
        f"Passed: {', '.join(slide_pass) or 'none'}. "
        f"Failed/refused: {', '.join(slide_fail) or 'none'}. "
        f"Samples under {out}. "
        f"P3: wait."
    )
    report = {
        "probeVersion": PROBE_VERSION,
        "fps": args.fps,
        "tolerances": {
            "clockWindowS": CLOCK_WINDOW_S,
            "clockMinRaf": CLOCK_MIN_RAF,
            "repeatProgressMaeMax": 0.02,
            "repeatTimestampErrMaxS": 1 / FPS,
            "decodedAlphaMaeMax": 3.0,
            "identityNearDupMaeMax": IDENTITY_NEAR_DUP_MAE_MAX,
            "identityOwnCloserMargin": IDENTITY_OWN_CLOSER_MARGIN,
        },
        "fingerprints": {
            "before": before.as_dict(),
            "after": after.as_dict(),
            "unchanged": identities_match(before, after),
        },
        "keynote": keynote,
        "renderer": {
            "creator": export.get("creator"),
            "exportContract": export.get("exportContract"),
            "playerDigest": unmodified["playerDigest"],
            "playerUnchangedAfterPatch": patched["playerDigest"] == unmodified["playerDigest"],
            "patches": patched["patches"],
            "playerMarkers": export.get("playerMarkers"),
        },
        "blackContent": black_check,
        "pdfRasters": pdf_notes,
        "captures": captures,
        "alphas": alphas,
        "captureExtras": extras,
        "prores": prores,
        "capability": capability,
        "runtime": {
            "elapsedS": elapsed,
            "selfMaxRssBytes": _rss_self(),
            "chromePeakRssBytes": extras.get("chromePeakRss"),
            "diskBytes": disk,
        },
        "summaryText": summary,
        "p3Advice": p3,
    }
    if extras.get("clock"):
        report["runtime"]["chromePeakRssBytes"] = extras.get("chromePeakRss")
    write_json(out / "report.json", report)
    write_json(out / "capability.json", capability)
    _report_md(out, report)
    print(summary)
    print(f"Report: {out / 'REPORT.md'}")
    if not identities_match(before, after):
        print("SOURCE DECK CHANGED — this is a P2 failure", file=sys.stderr)
        return 3
    return 0 if not capture_error else 2


async def _boot_and_capture(
    chrome: ChromeCdp,
    url: str,
    export: dict[str, Any],
    out: Path,
    captures: dict[int, dict[str, Any]],
    alphas: dict[int, dict[str, Any]],
    extras: dict[str, Any],
) -> None:
    await chrome.start()
    try:
        cap, alp, extra = await _run_capture(chrome, url, export, out)
        captures.update(cap)
        alphas.update(alp)
        extras.update(extra)
        extras["chromePeakRss"] = chrome.peak_rss
    finally:
        await chrome.close()


if __name__ == "__main__":
    raise SystemExit(main())
