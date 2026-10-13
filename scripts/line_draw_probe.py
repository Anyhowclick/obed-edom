#!/usr/bin/env python3
"""Headless pixel gate for Keynote Line Draw builds.

usage: uv run python scripts/line_draw_probe.py DECK --manifest MANIFEST --out DIR
       uv run python scripts/line_draw_probe.py DECK --manifest MANIFEST --out DIR --calibrate
       uv run python scripts/line_draw_probe.py DECK --out DIR --arms keyer --keyer-port PORT --keyer-password PASSWORD
       uv run python scripts/line_draw_probe.py --score DIR
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import math
import os
import shutil
import sys
import threading
import time
import traceback
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from obed_edom import live_host  # noqa: E402
from obed_edom.live_host import LiveOutputHost, PlayerCommandRejected  # noqa: E402
from obed_edom.obs_websocket import ObsWebsocket  # noqa: E402
from obed_edom.fixture_paths import fixture  # noqa: E402

DEFAULT_ARMS = ("on", "off", "head-static", "head-diamond-tail", "head-protrusions",
                "hold-p1", "hide-show", "destroy", "busy", "neighbour")
SPLICES = {
    "busy": (
        (
            b"snapshot() {",
            b"probeJumpToScene(A,B){return controller.jumpToScene(A,B)},snapshot() {",
            1,
        ),
    ),
    "head-diamond-tail": (
        (
            b'var r=E.getContext("2d"),D=r.getImageData(0,0,a,I),',
            b'var r=E.getContext("2d");if(Q.arrow){var pp=this.__obedLineAt(Q.geo,Q.geo.length),ux=Math.cos(pp.a),uy=Math.sin(pp.a),vx=-uy,vy=ux,cx=pp.x-13*ux,cy=pp.y-13*uy;r.save(),r.scale(G,G),r.fillStyle="#0ff",r.beginPath(),r.moveTo(cx+7*ux,cy+7*uy),r.lineTo(cx+14*vx,cy+14*vy),r.lineTo(cx-7*ux,cy-7*uy),r.lineTo(cx-14*vx,cy-14*vy),r.closePath(),r.fill(),r.restore()}var D=r.getImageData(0,0,a,I),',
            1,
        ),
        (
            b"if(diff>OBED_LINE_DRAW_HEAD_DIFF_MAX)throw 0;",
            b"window.__obedLineProbeDiff=diff;if(diff>OBED_LINE_DRAW_HEAD_DIFF_MAX)throw 0;",
            1,
        ),
    ),
    "head-protrusions": (
        (
            b'var r=E.getContext("2d"),D=r.getImageData(0,0,a,I),',
            b'var r=E.getContext("2d");if(Q.arrow){var pp=this.__obedLineAt(Q.geo,Q.geo.length),ux=Math.cos(pp.a),uy=Math.sin(pp.a),vx=-uy,vy=ux,cx=pp.x-7*ux,cy=pp.y-7*uy;r.save(),r.scale(G,G),r.fillStyle="#0ff";for(var side=-1;side<=1;side+=2){var bx=cx+side*15*vx,by=cy+side*15*vy;r.fillRect(bx-2.5,by-2.5,5,5)}r.restore()}var D=r.getImageData(0,0,a,I),',
            1,
        ),
        (
            b"if(diff>OBED_LINE_DRAW_HEAD_DIFF_MAX)throw 0;",
            b"window.__obedLineProbeDiff=diff;if(diff>OBED_LINE_DRAW_HEAD_DIFF_MAX)throw 0;",
            1,
        ),
    ),
    "head-static": ((b"this.__obedLineAt(A.geo,i)", b"this.__obedLineAt(A.geo,A.d)", 1),),
    "hold-p1": (
        (
            b'state.animation.addEventListener("finish",state.finish),state.animation.addEventListener("cancel",state.cancel)',
            b'state.animation.addEventListener("cancel",state.cancel)',
            1,
        ),
        (
            b"this.cssRenderer.__obedLineDrawComplete(A);for(var B=this.renderEffects(A.effects),",
            b"setTimeout(this.cssRenderer.__obedLineDrawComplete.bind(this.cssRenderer,A),120);for(var B=this.renderEffects(A.effects),",
            1,
        ),
    ),
    "destroy": (
        (
            b"snapshot() {",
            b"probeDestroy(){var e=controller.playbackController&&controller.playbackController.kpfEvent;if(!e)return!1;e.destroy();return!0},snapshot() {",
            1,
        ),
    ),
}
HOOK = r"""
(()=>{if(window.__obedLineProbe)return;var P=window.__obedLineProbe={frames:[],leafVisibility:[]},known=new Map,leaves=new Map;function f(){var a=[],n=[],v=[],s=window.__obedLive&&window.__obedLive.snapshot();
document.querySelectorAll('canvas[data-obed-line-draw]').forEach(function(c){var id=c.dataset.obedLineDraw,p=c.parentElement,l=p&&p.querySelector('canvas:not([data-obed-line-draw])');known.set(id,c),l&&leaves.set(id,l)});known.forEach(function(c,id){var r=c.getBoundingClientRect(),z=document.getAnimations().find(function(x){var t=x.effect&&x.effect.target;return /^layer.*-opacity$/.test(x.animationName||'')&&t&&(t===c.parentElement||t.contains(c))});a.push({id:id,box:[r.left,r.top,r.width,r.height],draws:c.__obedLineDraws||0,headDiff:c.__obedLineHeadDiff,connected:c.isConnected,animationName:z&&z.animationName})});leaves.forEach(function(c,id){v.push({id:id,visibility:c.style.visibility,connected:c.isConnected})}),P.leafVisibility=v;
document.getAnimations().forEach(function(x){if(/^layer.*-opacity$/.test(x.animationName||''))n.push({name:x.animationName,startTime:x.startTime,currentTime:x.currentTime,playState:x.playState})});
P.frames.push({t:performance.now(),scene:s&&s.sceneId,state:s&&s.playerState,overlays:a,animations:n});if(P.frames.length>1000)P.frames.shift();requestAnimationFrame(f)}requestAnimationFrame(f)})()
"""


def decode_png(data: str) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(base64.b64decode(data))).convert("RGBA"))


def encode_png(image: np.ndarray, path: Path) -> None:
    Image.fromarray(image.astype(np.uint8), "RGBA").save(path)


def metric_timestamp(transport: Any) -> float:
    metrics = transport.call("Performance.getMetrics").get("metrics", [])
    return float(next(item["value"] for item in metrics if item["name"] == "Timestamp"))


def screenshot(transport: Any) -> np.ndarray:
    return decode_png(transport.call("Page.captureScreenshot", format="png", fromSurface=True)["data"])


@contextlib.contextmanager
def screencast_frames(port: int) -> Iterator[list[tuple[float, float, np.ndarray]]]:
    from websockets.sync.client import connect

    frames: list[tuple[float, float, np.ndarray]] = []
    stop = threading.Event()
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as response:
        pages = [item for item in json.loads(response.read()) if item.get("type") == "page" and item.get("webSocketDebuggerUrl")]
    if len(pages) != 1:
        raise RuntimeError(f"{len(pages)} page targets for the screencast")

    def receive() -> None:
        with connect(pages[0]["webSocketDebuggerUrl"], max_size=None, open_timeout=5) as ws:
            ws.send(json.dumps({"id": 1, "method": "Page.startScreencast", "params": {"format": "png", "everyNthFrame": 1}}))
            index = 0
            while not stop.is_set():
                try:
                    message = json.loads(ws.recv(timeout=0.2))
                except TimeoutError:
                    continue
                if message.get("method") != "Page.screencastFrame":
                    continue
                params = message["params"]
                presented = float(params["metadata"].get("timestamp") or math.nan)
                received = time.monotonic()
                frames.append((presented, received, decode_png(params["data"])))
                index += 1
                ws.send(json.dumps({"id": 1000 + index, "method": "Page.screencastFrameAck", "params": {"sessionId": params["sessionId"]}}))
            ws.send(json.dumps({"id": 2, "method": "Page.stopScreencast"}))

    thread = threading.Thread(target=receive, daemon=True)
    thread.start()
    time.sleep(0.3)
    try:
        yield frames
    finally:
        stop.set()
        thread.join(timeout=10)


def bind_frame_clock(captured: list[tuple[float, float, np.ndarray]]) -> tuple[list[tuple[float, np.ndarray]], dict[str, Any]]:
    pairs = [(presented, received) for presented, received, _ in captured if math.isfinite(presented)]
    if not pairs:
        raise RuntimeError("screencast supplied no finite presentation timestamps")
    offset = min(received - presented for presented, received in pairs)
    frames = [(presented + offset, frame) for presented, _, frame in captured]
    lags = [(received - presented - offset) * 1000 for presented, received in pairs]
    clock = {"domain": "monotonic", "screencastToMonotonic": offset, "maxDeliveryLagMs": max(lags),
             "samples": len(pairs)}
    return frames, clock


def counted_splice(player: bytes, before: bytes, after: bytes, count: int) -> bytes:
    found = player.count(before)
    if found != count:
        raise RuntimeError(f"Line Draw splice count {found}, expected {count}: {before[:80]!r}")
    return player.replace(before, after)


@contextlib.contextmanager
def serving(arm: str) -> Iterator[None]:
    replacements = SPLICES.get(arm, ())
    if not replacements:
        yield
        return
    original = live_host.patch_player

    def patched(player: bytes, *, mm_opacity: bool = True) -> bytes:
        result = original(player, mm_opacity=mm_opacity)
        if mm_opacity:
            for before, after, count in replacements:
                result = counted_splice(result, before, after, count)
        return result

    live_host.patch_player = patched
    try:
        yield
    finally:
        live_host.patch_player = original


def resolver(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise FileNotFoundError(relative)
    return path


def line_effects(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("name") in ("com.apple.iWork.Keynote.LineDraw", "com.apple.iWork.Keynote.LineDrawForLine"):
            found.append(value)
        for child in value.values():
            found.extend(line_effects(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(line_effects(child))
    return found


def textured_leaf(layer: dict[str, Any]) -> dict[str, Any]:
    if layer.get("texturedRectangle"):
        return layer
    leaves = [textured_leaf(child) for child in layer.get("layers", []) if any_line_texture(child)]
    if len(leaves) != 1:
        raise ValueError("Line Draw effect does not have one textured leaf")
    return leaves[0]


def any_line_texture(layer: dict[str, Any]) -> bool:
    return bool(layer.get("texturedRectangle")) or any(any_line_texture(child) for child in layer.get("layers", []))


def slide_json(root: Path, manifest: dict[str, Any], ordinal: int) -> tuple[Path, dict[str, Any]]:
    slide = manifest["slides"][ordinal - 1]
    candidates = []
    for key in ("json", "path", "slide", "url"):
        if isinstance(slide, dict) and isinstance(slide.get(key), str):
            candidates.append(root / slide[key])
    if isinstance(slide, dict) and isinstance(slide.get("assetPaths"), dict) and isinstance(slide["assetPaths"].get("payload"), str):
        candidates.append(root / slide["assetPaths"]["payload"])
    if isinstance(slide, str):
        candidates.append(root / slide)
    for candidate in candidates:
        if candidate.suffix == ".jsonp":
            candidate = candidate.with_suffix(".json")
        if candidate.is_file():
            return candidate, json.loads(candidate.read_text())
    header = json.loads((root / "assets/header.json").read_text())
    ids = header.get("slideList") or header.get("slides") or []
    item = ids[ordinal - 1]
    slide_id = item if isinstance(item, str) else item.get("slideId") or item.get("id")
    path = root / "assets" / slide_id / f"{slide_id}.json"
    return path, json.loads(path.read_text())


def flatten(elements: list[dict[str, Any]]) -> tuple[list[tuple[float, float, float]], float]:
    start = elements[0]["points"][0]
    current = (float(start[0]), float(start[1]))
    points = [(current[0], current[1], 0.0)]
    length = 0.0
    for element in elements[1:]:
        kind = element["type"]
        if kind == "MoveToPoint":
            continue
        if kind == "CloseSubpath":
            samples = [tuple(start)]
        elif kind == "AddLine":
            samples = [tuple(element["points"][0])]
        elif kind == "AddCurve":
            p0 = current
            p1, p2, p3 = element["points"]
            samples = []
            for index in range(1, 97):
                value = index / 96
                back = 1 - value
                samples.append((back**3 * p0[0] + 3 * back**2 * value * p1[0] + 3 * back * value**2 * p2[0] + value**3 * p3[0],
                                back**3 * p0[1] + 3 * back**2 * value * p1[1] + 3 * back * value**2 * p2[1] + value**3 * p3[1]))
        else:
            raise ValueError(kind)
        for sample in samples:
            length += math.hypot(sample[0] - current[0], sample[1] - current[1])
            current = float(sample[0]), float(sample[1])
            points.append((current[0], current[1], length))
    return points, length


def at_length(points: list[tuple[float, float, float]], value: float) -> tuple[float, float, float]:
    value = min(max(value, 0.0), points[-1][2])
    for left, right in zip(points, points[1:]):
        if value <= right[2]:
            ratio = (value - left[2]) / max(right[2] - left[2], 1e-12)
            return left[0] + ratio * (right[0] - left[0]), left[1] + ratio * (right[1] - left[1]), math.atan2(right[1] - left[1], right[0] - left[0])
    left, right = points[-2:]
    return right[0], right[1], math.atan2(right[1] - left[1], right[0] - left[0])


def ease(value: float) -> float:
    guess = value
    for _ in range(8):
        back = 1 - guess
        error = 3 * back**2 * guess * 0.42 + 3 * back * guess**2 * 0.58 + guess**3 - value
        slope = 3 * back**2 * 0.42 + 6 * back * guess * (0.58 - 0.42) + 3 * guess**2 * (1 - 0.58)
        if abs(error) < 1e-7 or not slope:
            break
        guess = min(max(guess - error / slope, 0), 1)
    return 3 * (1 - guess) * guess**2 + guess**3


def effect_geometry(effect: dict[str, Any], rect: list[float]) -> dict[str, Any]:
    leaf = textured_leaf(effect["baseLayer"])
    path = leaf["texturedRectangle"]["shapePath"]["elements"]
    points, length = flatten(path)
    return {"name": effect["name"], "objectID": effect.get("objectID") or effect["baseLayer"].get("objectID"),
            "duration": float(effect["duration"]), "leaf": leaf, "rect": rect,
            "baseState": effect["baseLayer"].get("initialState", {}), "points": points, "length": length,
            "stroke": leaf["texturedRectangle"]["repGenerationDictionary"]["strokeWidth"],
            "animationName": None}


def state_origin(state: dict[str, Any]) -> tuple[float, float]:
    position = state["position"]
    anchor = state.get("anchorPoint", {"pointX": 0.5, "pointY": 0.5})
    return (float(position["pointX"]) - float(anchor["pointX"]) * float(state["width"]),
            float(position["pointY"]) - float(anchor["pointY"]) * float(state["height"]))


def textured_leaf_rects(layer: dict[str, Any], origin: tuple[float, float] = (0, 0)) -> list[list[float]]:
    state = layer["initialState"]
    local = state_origin(state)
    absolute = origin[0] + local[0], origin[1] + local[1]
    found = [[absolute[0], absolute[1], float(state["width"]), float(state["height"])]] \
        if layer.get("texturedRectangle") else []
    for child in layer.get("layers", []):
        found.extend(textured_leaf_rects(child, absolute))
    return found


def build_chains(slide: dict[str, Any]) -> list[list[dict[str, Any]]]:
    chains = []

    def append(effect: dict[str, Any], chain: list[dict[str, Any]]) -> None:
        if str(effect.get("type", "")).startswith("build"):
            chain.append(effect)
        for child in effect.get("effects", []):
            append(child, chain)

    for event in slide.get("events", []):
        chain: list[dict[str, Any]] = []
        for effect in event.get("effects", []):
            append(effect, chain)
        if chain:
            chains.append(chain)
    return chains


def later_build_rects(slide: dict[str, Any], geometries: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    seed = geometries[0]
    state = seed["baseState"]
    authored = state_origin(state)
    scale_x = float(seed["rect"][2]) / float(state["width"])
    scale_y = float(seed["rect"][3]) / float(state["height"])
    if abs(scale_x - scale_y) > 0.002:
        raise ValueError(f"non-uniform stage scale {scale_x}, {scale_y}")
    scale = (scale_x + scale_y) / 2
    offset_x = float(seed["rect"][0]) - authored[0] * scale
    offset_y = float(seed["rect"][1]) - authored[1] * scale
    line_ids = {str(geometry["objectID"]) for geometry in geometries}
    result: dict[str, list[dict[str, Any]]] = {object_id: [] for object_id in line_ids}
    for chain in build_chains(slide):
        for index, effect in enumerate(chain):
            object_id = str(effect.get("objectID") or effect.get("baseLayer", {}).get("objectID"))
            if object_id not in result:
                continue
            for later in chain[index + 1:]:
                for rect in textured_leaf_rects(later["baseLayer"]):
                    result[object_id].append({
                        "effect": str(later.get("objectID") or later["baseLayer"].get("objectID")),
                        "name": later.get("name"),
                        "rect": [offset_x + rect[0] * scale, offset_y + rect[1] * scale,
                                 rect[2] * scale, rect[3] * scale],
                    })
    return result


def scene_geometry(transport: Any, effects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for effect in effects:
        texture = textured_leaf(effect["baseLayer"]).get("texture")
        rect = transport.evaluate(f"(()=>{{var e=document.getElementById({json.dumps(texture)});if(!e)return null;var r=e.getBoundingClientRect();return [r.left,r.top,r.width,r.height]}})()")
        result.append(effect_geometry(effect, rect))
    return result


def authored_geometries(effects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for effect in effects:
        rects = textured_leaf_rects(effect["baseLayer"])
        if len(rects) != 1:
            raise ValueError(f"expected one authored texture rect, found {len(rects)}")
        result.append(effect_geometry(effect, rects[0]))
    return result


def sample_points(geometry: dict[str, Any], count: int = 96, end_length: float | None = None) -> list[tuple[int, int]]:
    rect = geometry["rect"]
    leaf = geometry["leaf"]["initialState"]
    end_length = geometry["length"] if end_length is None else end_length
    samples = []
    for index in range(count):
        x, y, _ = at_length(geometry["points"], end_length * index / max(count - 1, 1))
        samples.append((round(rect[0] + x / leaf["width"] * rect[2]), round(rect[1] + y / leaf["height"] * rect[3])))
    return samples


def revealed_front(frame: np.ndarray, before: np.ndarray, final: np.ndarray,
                   samples: list[tuple[int, int]], start: int = 0) -> float:
    values = []
    for x, y in samples:
        y0, y1 = max(0, y - 1), min(frame.shape[0], y + 2)
        x0, x1 = max(0, x - 1), min(frame.shape[1], x + 2)
        target = final[y0:y1, x0:x1, :3].astype(float)
        origin = before[y0:y1, x0:x1, :3].astype(float)
        live = frame[y0:y1, x0:x1, :3].astype(float)
        changed = np.abs(target - origin).max(axis=2) > 12
        values.append(bool(changed.any()) and float(np.abs(live - target)[changed].mean()) <= 10)
    front = min(range(start, len(values) + 1),
                key=lambda cut: sum(not value for value in values[start:cut]) + sum(values[cut:]))
    return front / len(values)


def revealed_error(frame: np.ndarray, before: np.ndarray, final: np.ndarray,
                   samples: list[tuple[int, int]], expected: float, start: int,
                   front_band: float, head_band: float) -> tuple[float | None, int]:
    errors = []
    eligible = 0
    for index, (x, y) in enumerate(samples[start:], start):
        position = index / max(len(samples) - 1, 1)
        if expected - front_band <= position <= expected + head_band:
            continue
        y0, y1 = max(0, y - 1), min(frame.shape[0], y + 2)
        x0, x1 = max(0, x - 1), min(frame.shape[1], x + 2)
        target = final[y0:y1, x0:x1, :3].astype(float)
        origin = before[y0:y1, x0:x1, :3].astype(float)
        live = frame[y0:y1, x0:x1, :3].astype(float)
        changed = np.abs(target - origin).max(axis=2) > 12
        if not changed.any():
            continue
        eligible += 1
        visible = float(np.abs(live - target)[changed].mean()) <= 10
        if position < expected and not visible:
            errors.append(expected - position)
        elif position > expected and visible:
            errors.append(position - expected)
    return max(errors, default=0.0), eligible


def score_frames(record: dict[str, Any], geometries: list[dict[str, Any]], before: np.ndarray, final: np.ndarray,
                 frames: list[tuple[float, np.ndarray]], origins: dict[str, np.ndarray] | None = None) -> dict[str, Any]:
    checks: dict[str, Any] = {"body": [], "handback": {}, "lifecycle": record.get("lifecycle", {})}
    begin = float(record["advanceFrameTime"])
    offset = 0.0
    post_show_errors = []
    lifecycle = record.get("lifecycle", {})
    show_ready = None
    if record["arm"] == "hide-show" and "hideAt" in lifecycle and "showAt" in lifecycle:
        hidden = [item for item in frames if lifecycle["hideAt"] <= item[0] - begin <= lifecycle["showAt"]]
        if hidden:
            hidden_frame = hidden[-1][1].astype(int)
            visible = [item for item in frames if item[0] - begin > lifecycle["showAt"]
                       and float(np.abs(item[1].astype(int) - hidden_frame).mean()) > 1]
            if visible:
                show_ready = visible[0][0]
    for geometry in geometries:
        effect_offset = float(record.get("effectStarts", {}).get(str(geometry["objectID"]), offset))
        effect_begin = begin + effect_offset
        origin = before
        prior = [item for item in frames if item[0] < effect_begin]
        if prior:
            origin = prior[-1][1]
        if origins and str(geometry["objectID"]) in origins:
            origin = origins[str(geometry["objectID"])]
        arrow_body = geometry["name"].endswith("LineDrawForLine")
        samples = sample_points(geometry, end_length=geometry["length"] - 8.09 if arrow_body else None)
        sample_support = 0
        for x, y in samples:
            y0, y1 = max(0, y - 1), min(final.shape[0], y + 2)
            x0, x1 = max(0, x - 1), min(final.shape[1], x + 2)
            sample_support += (np.abs(final[y0:y1, x0:x1, :3].astype(int)
                                      - origin[y0:y1, x0:x1, :3].astype(int)).max(axis=2) > 12).any()
        start = 0
        if arrow_body:
            for index, (x, y) in enumerate(samples):
                y0, y1 = max(0, y - 1), min(final.shape[0], y + 2)
                x0, x1 = max(0, x - 1), min(final.shape[1], x + 2)
                if (np.abs(final[y0:y1, x0:x1, :3].astype(int)
                           - origin[y0:y1, x0:x1, :3].astype(int)).max(axis=2) > 12).any():
                    start = index
                    break
        rows = []
        errors = []
        eligible_counts = []
        for timestamp, frame in frames:
            local = timestamp - effect_begin
            if local < -0.04 or local > geometry["duration"] + 0.08:
                continue
            absolute = timestamp - begin
            if "hideAt" in lifecycle and lifecycle["hideAt"] <= absolute \
                    and (show_ready is None or timestamp < show_ready):
                continue
            progress = ease(min(max(local / geometry["duration"], 0), 1))
            actual = revealed_front(frame, origin, final, samples, start)
            expected = progress
            if geometry["name"].endswith("LineDrawForLine"):
                d = 8.09
                expected = max(progress * geometry["length"], d) - d
                expected /= max(geometry["length"] - d, 1e-12)
                if expected < start / len(samples):
                    continue
                domain = geometry["length"] - d
                band = (geometry["stroke"] / 2 + 1.5) / domain
                error, eligible = revealed_error(frame, origin, final, samples, expected, start, band, (d + 13) / domain)
                eligible_counts.append(eligible)
                if eligible < 8:
                    continue
            else:
                error = abs(actual - expected)
            errors.append(error)
            if record["arm"] == "hide-show" and show_ready is not None and timestamp >= show_ready:
                post_show_errors.append(error)
            rows.append({"t": round(local, 4), "actual": round(actual, 4), "expected": round(expected, 4)})
        frame_step = float(np.median([right[0] - left[0] for left, right in zip(frames, frames[1:])])) \
            if len(frames) > 1 else 1
        allowance = 2 * frame_step / geometry["duration"] + 0.04
        maximum = round(max(errors), 4) if errors else None
        passed = maximum is not None and maximum <= allowance
        failures = [] if passed else [{"check": "body.maxError", "effect": geometry["name"], "measured": maximum,
                                       "maximum": round(allowance, 4), "frameCount": len(rows)}]
        status = None
        eligible_max = max(eligible_counts, default=sample_support)
        if sample_support < 8 or arrow_body and eligible_max < 8:
            status = "INCONCLUSIVE"
            failures = [{"check": "body.eligibleSamples", "effect": geometry["name"],
                         "measured": min(sample_support, eligible_max), "minimum": 8}]
            passed = None
        check = {"name": geometry["name"], "frames": rows, "maxError": maximum,
                 "allowance": round(allowance, 4), "sampleSupport": sample_support,
                 "eligibleSamples": eligible_counts,
                 "failedChecks": failures, "pass": passed}
        if status:
            check.update({"status": status, "reason": "too few eligible body samples"})
        checks["body"].append(check)
        offset += geometry["duration"]
    handback: dict[str, Any] = {"endEqualsOff": None, "settledSha256": record.get("settledSha256"),
                                "popProgress": None, "heldP1EqualsStock": None, "effects": []}
    overlay_rows = record.get("overlayFrames", [])
    painted_any = False
    roi_diffs = []
    held_missing = []
    for geometry in geometries:
        object_id = str(geometry["objectID"])
        painted = [(row, overlay) for row in overlay_rows for overlay in row.get("overlays", [])
                   if str(overlay.get("id")) == object_id and overlay.get("connected", True)
                   and overlay.get("draws", 0) > 0]
        effect_handback = {"objectID": object_id, "name": geometry["name"], "lastPaintedMs": None,
                           "popProgress": None, "popMaximum": None, "popResidual": None, "heldP1": None,
                           "popApplicable": True, "popNotApplicable": None}
        if painted and frames:
            painted_any = True
            last_ms = painted[-1][0]["t"]
            effect_handback["lastPaintedMs"] = last_ms
            last_absolute = (last_ms - record["advancePerformanceMs"]) / 1000
            if (record["arm"] == "hide-show" and "hideAt" in lifecycle and "showAt" in lifecycle
                    and lifecycle["hideAt"] <= last_absolute <= lifecycle["showAt"]):
                effect_handback["popApplicable"] = False
                effect_handback["popNotApplicable"] = "last painted frame falls inside the hidden interval"
                effect_handback["lastPaintedFromAdvance"] = round(last_absolute, 4)
                handback["effects"].append(effect_handback)
                continue
            last_time = begin + (last_ms - record["advancePerformanceMs"]) / 1000
            before_cast = min(frames, key=lambda item: abs(item[0] - last_time))
            after_cast = next((item for item in frames if item[0] > before_cast[0]), before_cast)
            samples = sample_points(geometry)
            effect_offset = float(record.get("effectStarts", {}).get(object_id, 0))
            prior = [item for item in frames if item[0] < begin + effect_offset]
            origin = prior[-1][1] if prior else before
            if origins and object_id in origins:
                origin = origins[object_id]
            last_front = revealed_front(before_cast[1], origin, final, samples)
            stock_front = revealed_front(after_cast[1], origin, final, samples)
            effect_handback["popProgress"] = round(abs(stock_front - last_front), 4)
            frame_step = float(np.median([right[0] - left[0] for left, right in zip(frames, frames[1:])])) \
                if len(frames) > 1 else 1 / 30
            effect_handback["popMaximum"] = round(frame_step / geometry["duration"], 4)
            later = record.get("laterBuildRects", {}).get(object_id, [])
            swept = []
            for item in later:
                boxes = [overlay.get("box") for row in overlay_rows for overlay in row.get("overlays", [])
                         if str(overlay.get("id")) == str(item.get("effect")) and overlay.get("box")
                         and overlay["box"][2] > 0 and overlay["box"][3] > 0]
                if boxes:
                    left = min(box[0] for box in boxes)
                    top = min(box[1] for box in boxes)
                    right = max(box[0] + box[2] for box in boxes)
                    bottom = max(box[1] + box[3] for box in boxes)
                    swept.append({"effect": item.get("effect"), "name": item.get("name"),
                                  "rect": [left, top, right - left, bottom - top]})
            pop_rect = painted[-1][1].get("box") or geometry["rect"]
            px0, py0 = max(0, math.floor(pop_rect[0])), max(0, math.floor(pop_rect[1]))
            px1 = min(final.shape[1], math.ceil(pop_rect[0] + pop_rect[2]))
            py1 = min(final.shape[0], math.ceil(pop_rect[1] + pop_rect[3]))
            pop_delta = np.abs(before_cast[1][py0:py1, px0:px1, :3].astype(int)
                               - final[py0:py1, px0:px1, :3].astype(int))
            pop_covered = np.zeros(pop_delta.shape[:2], dtype=bool)
            pys, pxs = np.mgrid[py0:py1, px0:px1]
            for item in later:
                left, top, width, height = item["rect"]
                pop_covered |= ((pxs + 0.5 >= left) & (pxs + 0.5 < left + width)
                                & (pys + 0.5 >= top) & (pys + 0.5 < top + height))
            pop_pixels = pop_delta.max(axis=2) if pop_delta.size else np.zeros(pop_covered.shape, dtype=int)
            effect_handback["popResidual"] = {
                "overTolerancePixels": int(np.count_nonzero(pop_pixels[~pop_covered] > 1)),
                "comparedPixels": int(np.count_nonzero(~pop_covered)),
                "tolerancePerChannel": 1,
            }
            if record["arm"] == "hold-p1":
                complete = []
                for row, overlay in painted:
                    name = overlay.get("animationName") or geometry.get("animationName")
                    animation = next((item for item in row.get("animations", []) if item.get("name") == name
                                      and item.get("currentTime") is not None), None)
                    if animation and float(animation["currentTime"]) >= geometry["duration"] * 1000:
                        complete.append((row, overlay, animation))
                if not complete:
                    held_missing.append(geometry["name"])
                    handback["effects"].append(effect_handback)
                    continue
                held_row, _, held_animation = complete[-1]
                held_time = begin + (float(held_row["t"]) - record["advancePerformanceMs"]) / 1000
                held_cast = min(frames, key=lambda item: abs(item[0] - held_time))
                rect = geometry["rect"]
                x0, y0 = max(0, math.floor(rect[0])), max(0, math.floor(rect[1]))
                x1, y1 = min(final.shape[1], math.ceil(rect[0] + rect[2])), min(final.shape[0], math.ceil(rect[1] + rect[3]))
                delta = np.abs(held_cast[1][y0:y1, x0:x1].astype(int) - final[y0:y1, x0:x1].astype(int))
                covered = np.zeros(delta.shape[:2], dtype=bool)
                ys, xs = np.mgrid[y0:y1, x0:x1]
                for item in [*later, *swept]:
                    left, top, width, height = item["rect"]
                    covered |= ((xs + 0.5 >= left) & (xs + 0.5 < left + width)
                                & (ys + 0.5 >= top) & (ys + 0.5 < top + height))
                eligible = ~covered
                pixel_delta = delta.max(axis=2) if delta.size else np.zeros(covered.shape, dtype=int)
                compared = delta[eligible]
                roi_diffs.append({
                    "effect": geometry["name"],
                    "maxDiff": int(compared.max()) if compared.size else None,
                    "meanDiff": round(float(compared.mean()), 6) if compared.size else None,
                    "differentPixels": int(np.count_nonzero(pixel_delta[eligible])) if compared.size else None,
                    "overTolerancePixels": int(np.count_nonzero(pixel_delta[eligible] > 1)) if compared.size else None,
                    "comparedPixels": int(np.count_nonzero(eligible)),
                    "excludedPixels": int(np.count_nonzero(covered)),
                    "excludedDifferentPixels": int(np.count_nonzero(pixel_delta[covered])) if covered.any() else 0,
                    "tolerancePerChannel": 1,
                    "telemetryTimeMs": held_row["t"],
                    "animationCurrentTimeMs": held_animation["currentTime"],
                    "animationDurationMs": geometry["duration"] * 1000,
                    "frameTime": held_cast[0],
                    "laterBuildRects": later,
                    "laterBuildSweptBounds": swept,
                })
                effect_handback["heldP1"] = roi_diffs[-1]
        handback["effects"].append(effect_handback)
    pop_values = [item["popProgress"] for item in handback["effects"] if item["popProgress"] is not None]
    handback["popProgress"] = max(pop_values, default=None)
    if record["arm"] == "hold-p1":
        handback["heldP1RoiDiff"] = roi_diffs
        handback["heldP1EqualsStock"] = not held_missing and len(roi_diffs) == len(geometries) and all(
            item["comparedPixels"] > 0 and item["overTolerancePixels"] == 0 for item in roi_diffs)
        handback["heldP1MissingTelemetry"] = held_missing
    failures = [failure for item in checks["body"] for failure in item["failedChecks"]]
    if not painted_any:
        failures.append({"check": "overlay.frames", "measured": 0, "minimum": 1})
    for item in handback["effects"]:
        if item["popApplicable"] and (item["popProgress"] is None or item["popProgress"] > item["popMaximum"]):
            failures.append({"check": "handback.popProgress", "effect": item["name"],
                             "measured": item["popProgress"], "maximum": item["popMaximum"]})
    if record["arm"] == "hold-p1":
        if handback["heldP1EqualsStock"] is not True:
            failures.append({"check": "handback.heldP1EqualsStock", "measured": handback["heldP1EqualsStock"],
                             "expected": True, "roiDiff": handback.get("heldP1RoiDiff")})
    if record["arm"] == "hide-show":
        allowance = max((item["allowance"] for item in checks["body"]), default=0.2)
        maximum = round(max(post_show_errors), 4) if post_show_errors else None
        resumed = show_ready is not None and maximum is not None and maximum <= allowance
        checks["lifecycle"] = {**record.get("lifecycle", {}), "postShowFrames": len(post_show_errors),
                               "presentationReadyAt": round(show_ready - begin, 4) if show_ready else None,
                               "presentationLatencyMs": round((show_ready - begin - lifecycle["showAt"]) * 1000, 1)
                               if show_ready else None,
                               "resumeMaxError": maximum, "allowance": allowance, "resumed": resumed}
        if not resumed:
            failures.append({"check": "hideShow.resumeMaxError", "measured": maximum, "maximum": allowance,
                             "frameCount": len(post_show_errors)})
    checks["handback"] = handback
    checks["failedChecks"] = failures
    inconclusive = [item for item in checks["body"] if item.get("status") == "INCONCLUSIVE"]
    if held_missing:
        inconclusive.append({"reason": f"no held p=1 stock Animation telemetry for {', '.join(held_missing)}"})
    if record["arm"] == "hide-show" and show_ready is None:
        inconclusive.append({"reason": "no presented frame after show"})
    checks["pass"] = None if inconclusive else not failures
    if inconclusive:
        checks.update({"status": "INCONCLUSIVE", "reason": "; ".join(item["reason"] for item in inconclusive)})
    return checks


def wait_settled(host: LiveOutputHost, timeout: float = 12) -> None:
    deadline = time.monotonic() + timeout
    while host.observe().busy and time.monotonic() < deadline:
        time.sleep(0.03)
    time.sleep(0.25)


def animation_effect_starts(record: dict[str, Any], geometries: list[dict[str, Any]]) -> dict[str, float]:
    if record.get("advancePerformanceMs") is None:
        raise ValueError("advance performance timestamp is missing")
    starts = {}
    clocks = {}
    for geometry in geometries:
        name = geometry["animationName"]
        rows = [(row, animation) for row in record.get("overlayFrames", [])
                for animation in row.get("animations", []) if animation.get("name") == name]
        direct = [float(animation["startTime"]) for _, animation in rows
                  if animation.get("startTime") is not None and math.isfinite(float(animation["startTime"]))]
        derived = [float(row["t"]) - float(animation["currentTime"]) for row, animation in rows
                   if animation.get("currentTime") is not None and math.isfinite(float(animation["currentTime"]))]
        if not direct and not derived:
            raise ValueError(f"no stock Animation clock for {name}")
        start = float(np.median(direct or derived))
        object_id = str(geometry["objectID"])
        starts[object_id] = (start - float(record["advancePerformanceMs"])) / 1000
        clocks[object_id] = {"animationName": name, "startTime": start,
                             "samples": len(direct or derived), "source": "startTime" if direct else "t-currentTime"}
    record["effectClocks"] = clocks
    return starts


def run_arm(root: Path, slides: list[Any], manifest: dict[str, Any], ordinal: int, arm: str, out: Path) -> dict[str, Any]:
    host = LiveOutputHost(root, slides, headless=True, resolver=resolver, continuity="off", mm_opacity="off" if arm == "off" else "auto")
    record: dict[str, Any] = {"arm": arm}
    frames: list[tuple[float, np.ndarray]] = []
    captured_rows: list[tuple[float, float, np.ndarray]] = []
    try:
        with serving(arm):
            host.start()
        host.execute("show")
        host.execute("goTo", ordinal)
        wait_settled(host)
        transport = host._require_transport()
        transport.call("Performance.enable")
        transport.evaluate(HOOK)
        before = screenshot(transport)
        _, slide = slide_json(root, manifest, ordinal)
        effects = line_effects(slide)
        if len(effects) != 2:
            raise RuntimeError(f"expected two Line Draw effects, found {len(effects)}")
        geometries = scene_geometry(transport, effects)
        record["geometries"] = geometries
        record["laterBuildRects"] = later_build_rects(slide, geometries)
        with screencast_frames(transport.port) as captured:
            record["advanceTimestamp"] = metric_timestamp(transport)
            record["advancePerformanceMs"] = transport.evaluate("performance.now()")
            record["advanceFrameTime"] = time.monotonic()
            host.execute("advance")
            if arm == "busy":
                time.sleep(0.18)
                try:
                    host.execute("goTo", 1)
                    record["hostGoToBusyRefused"] = False
                except PlayerCommandRejected:
                    record["hostGoToBusyRefused"] = True
                record["jumpBefore"] = transport.evaluate("window.__obedLive.snapshot().sceneId")
                record["jumpResult"] = transport.evaluate("window.__obedLive.probeJumpToScene(0,false)")
                record["jumpAfter"] = transport.evaluate("window.__obedLive.snapshot().sceneId")
            elif arm == "hide-show":
                time.sleep(0.3)
                hide_at = time.monotonic() - record["advanceFrameTime"]
                host.execute("hide")
                time.sleep(0.75)
                host.execute("show")
                record["lifecycle"] = {"hideAt": hide_at,
                                       "showAt": time.monotonic() - record["advanceFrameTime"]}
            elif arm == "destroy":
                time.sleep(0.95)
                arrow_id = str(next(geometry["objectID"] for geometry in geometries
                                    if geometry["name"].endswith("LineDrawForLine")))
                record["destroyAt"] = metric_timestamp(transport)
                record["destroyAtMs"] = transport.evaluate("performance.now()")
                record["destroyResult"] = False
                try:
                    atomic = transport.evaluate(
                        f"(()=>{{var c=document.querySelector('canvas[data-obed-line-draw={json.dumps(arrow_id)}]'),"
                        "p=c?{id:c.dataset.obedLineDraw,draws:c.__obedLineDraws||0,connected:c.isConnected}:null,"
                        "r=window.__obedLive.probeDestroy();return {pre:p,result:r,at:performance.now()}})()"
                    )
                    record["preDestroyOverlay"] = atomic["pre"]
                    record["destroyResult"] = atomic["result"]
                    record["destroyAtMs"] = atomic["at"]
                except Exception:
                    record["destroyActionError"] = traceback.format_exc()
            time.sleep(2.9)
            captured_rows = list(captured)
        frames, record["frameClock"] = bind_frame_clock(captured_rows)
        final = screenshot(transport)
        probe = transport.evaluate("window.__obedLineProbe") or {}
        record["overlayFrames"] = probe.get("frames", [])
        record["leafCanvases"] = probe.get("leafVisibility", [])
        record["hiddenLeafCanvases"] = [item for item in record["leafCanvases"]
                                         if item.get("visibility") == "hidden"]
        record["probeHeadDiff"] = transport.evaluate(
            "null==window.__obedLineProbeDiff?null:window.__obedLineProbeDiff"
        )
        animation_names = {str(overlay.get("id")): overlay.get("animationName")
                           for row in record["overlayFrames"] for overlay in row.get("overlays", [])
                           if overlay.get("animationName")}
        for geometry in geometries:
            geometry["animationName"] = animation_names.get(str(geometry["objectID"]))
        record["overlayResidue"] = transport.evaluate("document.querySelectorAll('canvas[data-obed-line-draw]').length")
        record["mmOpacity"] = host.output.get("mmOpacity")
        record["settledSha256"] = __import__("hashlib").sha256(final.tobytes()).hexdigest()
        record["frameCount"] = len(frames)
        arm_out = out / arm
        arm_out.mkdir(parents=True, exist_ok=True)
        encode_png(before, arm_out / "before.png")
        encode_png(final, arm_out / "settled.png")
        frame_times = []
        for index, ((presented, received, _), (timestamp, frame)) in enumerate(zip(captured_rows, frames)):
            encode_png(frame, arm_out / f"frame-{index:04d}.png")
            frame_times.append({"screencast": presented, "receivedMonotonic": received, "scoreTime": timestamp})
        (arm_out / "timestamps.json").write_text(json.dumps([timestamp for timestamp, _ in frames], indent=1))
        (arm_out / "frame-times.json").write_text(json.dumps(frame_times, indent=1))
        if arm == "destroy":
            after = [item for item in record["overlayFrames"] if item["t"] >= record["destroyAtMs"]]
            elapsed = record["destroyAt"] - record["advanceTimestamp"]
            deadline = sum(geometry["duration"] for geometry in geometries)
            pre = record.get("preDestroyOverlay") or {}
            post_arrow = [overlay for item in after for overlay in item.get("overlays", [])
                          if str(overlay.get("id")) == str(pre.get("id"))]
            lifecycle = {"overlayExisted": bool(pre.get("connected")) and pre.get("draws", 0) > 0,
                         "disposed": bool(record["destroyResult"]) and record["overlayResidue"] == 0,
                         "leafVisibilityRestored": not record["hiddenLeafCanvases"],
                         "hiddenLeafCanvases": record["hiddenLeafCanvases"],
                         "postDestroyConnectedFrames": sum(bool(overlay.get("connected")) for overlay in post_arrow),
                         "postDestroyRedraws": max((overlay.get("draws", 0) for overlay in post_arrow),
                                                   default=pre.get("draws", 0)) - pre.get("draws", 0),
                         "destroyElapsed": round(elapsed, 4), "buildDeadline": round(deadline, 4),
                         "beforeBuildDeadline": elapsed < deadline}
            failures = []
            if record.get("destroyActionError"):
                failures.append({"check": "destroy.action", "error": record["destroyActionError"]})
            if not lifecycle["overlayExisted"]:
                failures.append({"check": "destroy.overlayExisted", "measured": record.get("preDestroyOverlay"),
                                 "expected": "connected arrow overlay with at least one draw"})
            if not lifecycle["disposed"]:
                failures.append({"check": "destroy.disposed", "destroyResult": record["destroyResult"],
                                 "overlayResidue": record["overlayResidue"], "expectedResidue": 0})
            if not lifecycle["leafVisibilityRestored"]:
                failures.append({"check": "destroy.hiddenLeafVisibility",
                                 "measured": lifecycle["hiddenLeafCanvases"], "expected": []})
            if lifecycle["postDestroyConnectedFrames"]:
                failures.append({"check": "destroy.postConnectedFrames", "measured": lifecycle["postDestroyConnectedFrames"],
                                 "maximum": 0})
            if lifecycle["postDestroyRedraws"]:
                failures.append({"check": "destroy.postDestroyRedraws", "measured": lifecycle["postDestroyRedraws"],
                                 "maximum": 0})
            if not lifecycle["beforeBuildDeadline"]:
                failures.append({"check": "destroy.deadline", "measured": lifecycle["destroyElapsed"],
                                 "maximum": lifecycle["buildDeadline"]})
            record["lifecycle"] = lifecycle
            record["failedChecks"] = failures
    except Exception:
        record["error"] = traceback.format_exc()
    finally:
        try:
            host.stop()
        except Exception as exc:
            record["stopError"] = repr(exc)
    return record


def keyer_arm(port: int, password: str | None, source: str, out: Path, seconds: float,
              geometries: list[dict[str, Any]]) -> dict[str, Any]:
    frames = []
    started = time.monotonic()
    with ObsWebsocket(port, password, timeout=5) as websocket:
        while time.monotonic() - started < seconds:
            response = websocket.request("GetSourceScreenshot", {"sourceName": source, "imageFormat": "png", "imageWidth": 1920,
                                                                  "imageHeight": 1080, "imageCompressionQuality": 100})
            frames.append((time.monotonic() - started, decode_png(response["imageData"].split(",", 1)[-1])))
    arm_out = out / "keyer"
    arm_out.mkdir(parents=True, exist_ok=True)
    for index, (_, frame) in enumerate(frames):
        encode_png(frame, arm_out / f"frame-{index:04d}.png")
    if len(frames) < 3:
        failure = {"check": "keyer.frames", "measured": len(frames), "minimum": 3}
        return {"arm": "keyer", "frameCount": len(frames), "status": "INCONCLUSIVE",
                "reason": "keyer capture supplied fewer than three frames", "failedChecks": [failure], "pass": None}
    before, final = frames[0][1], frames[-1][1]
    spatial = []
    for geometry in geometries:
        samples = sample_points(geometry)
        support = sum((np.abs(final[max(0, y - 1):min(final.shape[0], y + 2),
                                      max(0, x - 1):min(final.shape[1], x + 2), :3].astype(int)
                              - before[max(0, y - 1):min(before.shape[0], y + 2),
                                       max(0, x - 1):min(before.shape[1], x + 2), :3].astype(int)).max(axis=2) > 12).any()
                      for x, y in samples)
        fronts = [revealed_front(frame, before, final, samples) for _, frame in frames]
        partial_frames = [index for index, front in enumerate(fronts[1:-1], 1) if 0.08 < front < 0.92]
        partial_fronts = [fronts[index] for index in partial_frames]
        increasing = len(partial_fronts) >= 2 and all(right > left for left, right in zip(partial_fronts, partial_fronts[1:]))
        spatial.append({"objectID": str(geometry["objectID"]), "name": geometry["name"],
                        "sampleSupport": support, "fronts": [round(value, 4) for value in fronts],
                        "partialFrames": partial_frames,
                        "partialFronts": [round(value, 4) for value in partial_fronts],
                        "partialIncreasing": increasing})
    if any(item["sampleSupport"] < 8 for item in spatial):
        failure = {"check": "keyer.sampleSupport", "measured": spatial, "minimum": 8}
        return {"arm": "keyer", "frameCount": len(frames), "status": "INCONCLUSIVE",
                "reason": "keyer capture did not bracket the Line Draw build", "spatialReveal": spatial,
                "failedChecks": [failure], "pass": None}
    partial = all(item["partialIncreasing"] for item in spatial)
    end_deltas = [int(np.abs(frame.astype(int) - final.astype(int)).max()) for _, frame in frames[-3:]]
    settled = max(end_deltas, default=255) <= 1
    failures = []
    if not partial:
        failures.append({"check": "keyer.partialReveal", "measured": spatial,
                         "expected": "each path has at least two partial frames with strictly increasing fronts"})
    if not settled:
        failures.append({"check": "keyer.stockEnd", "measuredMaxLsb": max(end_deltas, default=None), "maximum": 1})
    return {"arm": "keyer", "frameCount": len(frames), "partialReveal": partial, "spatialReveal": spatial,
            "endMaxLsb": max(end_deltas, default=None), "failedChecks": failures, "pass": not failures}


def compare_label_dissolve(out: Path, on: dict[str, Any], off: dict[str, Any]) -> dict[str, Any]:
    on_times = json.loads((out / "on" / "timestamps.json").read_text())
    off_times = json.loads((out / "off" / "timestamps.json").read_text())
    later = [item for items in on.get("laterBuildRects", {}).values() for item in items
             if item.get("name") == "apple:dissolve"]
    if not later:
        failure = {"check": "labelDissolve.rect", "measured": 0, "minimum": 1}
        return {"frames": 0, "rect": None, "maxMeanDelta": None, "failedChecks": [failure], "pass": False}
    rect = later[-1]["rect"]
    starts = {}
    for arm, run in (("on", on), ("off", off)):
        line_names = {geometry.get("animationName") for geometry in run.get("geometries", [])}
        line_starts = [clock["startTime"] for clock in run.get("effectClocks", {}).values()]
        candidates = [float(animation["startTime"]) for row in run.get("overlayFrames", [])
                      for animation in row.get("animations", []) if animation.get("name") not in line_names
                      and animation.get("startTime") is not None
                      and (not line_starts or float(animation["startTime"]) > max(line_starts))]
        if not candidates:
            failure = {"check": "labelDissolve.clock", "arm": arm, "measured": 0, "minimum": 1}
            return {"frames": 0, "rect": rect, "maxMeanDelta": None,
                    "failedChecks": [failure], "pass": False}
        start = min(candidates)
        starts[arm] = run["advanceFrameTime"] + (start - run["advancePerformanceMs"]) / 1000
    deltas = []
    for index, timestamp in enumerate(on_times):
        elapsed = timestamp - starts["on"]
        if not -0.03 <= elapsed <= 0.9:
            continue
        match = min(range(len(off_times)), key=lambda item: abs((off_times[item] - starts["off"]) - elapsed))
        left = np.asarray(Image.open(out / "on" / f"frame-{index:04d}.png").convert("RGBA"), dtype=float)
        right = np.asarray(Image.open(out / "off" / f"frame-{match:04d}.png").convert("RGBA"), dtype=float)
        x0, y0 = max(0, math.floor(rect[0])), max(0, math.floor(rect[1]))
        x1, y1 = min(left.shape[1], math.ceil(rect[0] + rect[2])), min(left.shape[0], math.ceil(rect[1] + rect[3]))
        deltas.append(float(np.abs(left[y0:y1, x0:x1] - right[y0:y1, x0:x1]).mean()))
    maximum = max(deltas) if deltas else None
    passed = maximum is not None and maximum <= 2
    failures = [] if passed else [{"check": "labelDissolve.maxMeanDelta", "measured": maximum, "maximum": 2,
                                   "frameCount": len(deltas)}]
    return {"frames": len(deltas), "rect": rect, "clock": "stock-layer-opacity-animation",
            "maxMeanDelta": maximum,
            "failedChecks": failures, "pass": passed}


def neighbour_arm(alpha_root: Path, manifest: dict[str, Any], out: Path) -> dict[str, Any]:
    record: dict[str, Any] = {"arm": "neighbour"}
    scratch = out / "_neighbour_export"
    host = None
    try:
        if scratch.exists():
            shutil.rmtree(scratch)
        shutil.copytree(fixture("p2-binary") / "html-player", scratch)
        alpha_entry = manifest["slides"][1]
        payload = alpha_root / alpha_entry["assetPaths"]["payload"]
        shutil.copytree(payload.parent, scratch / "assets" / payload.parent.name)
        header_path = scratch / "assets" / "header.json"
        header = json.loads(header_path.read_text())
        header["slideList"].insert(0, payload.parent.name)
        header["slideCount"] = len(header["slideList"])
        header_path.write_text(json.dumps(header, separators=(",", ":")))
        (scratch / "assets" / "header.jsonp").write_text(f"local_header( {json.dumps(header, separators=(',', ':'))} )")
        slides = [{"originalOrdinal": index + 1, "playerIndex": index, "exportedUuid": slide, "skipped": False}
                  for index, slide in enumerate(header["slideList"])]
        host = LiveOutputHost(scratch, slides, headless=True, resolver=resolver, continuity="off", mm_opacity="auto")
        host.start()
        record["placement"] = host.output.get("placement")
        record["codecs"] = host.output.get("codecs")
        if (record["placement"] or {}).get("grant") != "snap":
            reason = (record["placement"] or {}).get("reason") or "no placement decision"
            record.update({"status": "INCONCLUSIVE", "reason": f"movie snap grant unavailable: {reason}",
                           "pass": None})
            return record
        host.execute("show")
        host.execute("goTo", 1)
        wait_settled(host)
        host.execute("advance")
        wait_settled(host)
        host.execute("goTo", 3)
        wait_settled(host)
        transport = host._require_transport()
        transport.call("Performance.enable")
        time.sleep(1)
        rect = transport.evaluate("(()=>{var v=Array.from(document.querySelectorAll('video')).find(x=>x.checkVisibility({opacityProperty:true,visibilityProperty:true}));if(!v)return null;var r=v.getBoundingClientRect();return [r.left,r.top,r.width,r.height]})()")
        if not rect:
            record.update({"status": "INCONCLUSIVE", "reason": "H.264 P2 movie is not visible before its Dissolve",
                           "videoElementCount": transport.evaluate("document.querySelectorAll('video').length"),
                           "pass": None})
            return record
        before = screenshot(transport)
        with screencast_frames(transport.port) as captured:
            record["advanceTimestamp"] = metric_timestamp(transport)
            record["advanceFrameTime"] = time.monotonic()
            host.execute("advance")
            time.sleep(2.2)
            captured_rows = list(captured)
        frames, record["frameClock"] = bind_frame_clock(captured_rows)
        final = screenshot(transport)
        arm_out = out / "neighbour"
        arm_out.mkdir(parents=True, exist_ok=True)
        encode_png(before, arm_out / "before.png")
        encode_png(final, arm_out / "settled.png")
        frame_times = []
        for index, ((presented, received, _), (timestamp, frame)) in enumerate(zip(captured_rows, frames)):
            encode_png(frame, arm_out / f"frame-{index:04d}.png")
            frame_times.append({"screencast": presented, "receivedMonotonic": received, "scoreTime": timestamp})
        (arm_out / "timestamps.json").write_text(json.dumps([timestamp for timestamp, _ in frames], indent=1))
        (arm_out / "frame-times.json").write_text(json.dumps(frame_times, indent=1))
        record["frameCount"] = len(frames)
        record["rect"] = rect
        x0, y0 = max(0, math.floor(rect[0])), max(0, math.floor(rect[1]))
        x1, y1 = min(before.shape[1], math.ceil(rect[0] + rect[2])), min(before.shape[0], math.ceil(rect[1] + rect[3]))
        rows = []
        for timestamp, frame in frames:
            elapsed = timestamp - record["advanceFrameTime"]
            if 0 <= elapsed <= 1.1:
                roi = frame[y0:y1, x0:x1, :3].astype(float)
                rows.append({"t": elapsed, "toBefore": float(np.abs(roi - before[y0:y1, x0:x1, :3]).mean()),
                             "toEnd": float(np.abs(roi - final[y0:y1, x0:x1, :3]).mean()), "mean": float(roi.mean())})
        record["frames"] = rows
        record["freezeHeld"] = bool(rows) and rows[0]["toBefore"] <= rows[0]["toEnd"] and min(row["mean"] for row in rows) > 1
        record["pass"] = record["freezeHeld"]
        if not record["pass"]:
            record["failedChecks"] = [{"check": "neighbour.freezeHeld", "measured": record["freezeHeld"],
                                       "expected": True, "frameCount": len(rows),
                                       "firstToBefore": rows[0]["toBefore"] if rows else None,
                                       "firstToEnd": rows[0]["toEnd"] if rows else None,
                                       "minimumMean": min((row["mean"] for row in rows), default=None)}]
    except Exception:
        record["error"] = traceback.format_exc()
        record["pass"] = False
    finally:
        if host:
            try:
                host.stop()
            except Exception as exc:
                record["stopError"] = repr(exc)
    return record


def saved_frames(out: Path, arm: str) -> tuple[np.ndarray, np.ndarray, list[tuple[float, np.ndarray]]]:
    arm_out = out / arm
    before_path = arm_out / "before.png"
    settled_path = arm_out / "settled.png"
    timestamps_path = arm_out / "timestamps.json"
    missing = [path.name for path in (before_path, settled_path, timestamps_path) if not path.is_file()]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    timestamps = json.loads(timestamps_path.read_text())
    frame_paths = sorted(arm_out.glob("frame-*.png"))
    if len(timestamps) != len(frame_paths):
        raise ValueError(f"{len(timestamps)} timestamps for {len(frame_paths)} frames")
    before = np.asarray(Image.open(before_path).convert("RGBA"))
    final = np.asarray(Image.open(settled_path).convert("RGBA"))
    frames = [(float(timestamp), np.asarray(Image.open(path).convert("RGBA")))
              for timestamp, path in zip(timestamps, frame_paths)]
    shapes = {before.shape, final.shape, *(frame.shape for _, frame in frames)}
    if len(shapes) != 1:
        raise ValueError(f"inconsistent frame shapes: {sorted(shapes)}")
    if not frames:
        raise ValueError("no saved frames")
    if any(not math.isfinite(timestamp) for timestamp, _ in frames):
        raise ValueError("non-finite frame timestamp")
    if any(right[0] <= left[0] for left, right in zip(frames, frames[1:])):
        raise ValueError("frame timestamps are not strictly increasing")
    return before, final, frames


def destroy_score(record: dict[str, Any]) -> dict[str, Any]:
    record.pop("finalElements", None)
    lifecycle = dict(record.get("lifecycle", {}))
    lifecycle.pop("finalElementsEqualOff", None)
    lifecycle.pop("offFinalElements", None)
    if not isinstance(record.get("hiddenLeafCanvases"), list):
        failure = {"check": "destroy.hiddenLeafVisibilityTelemetry", "measured": None,
                   "expected": "saved hidden leaf canvas list"}
        return {"body": [], "handback": {}, "lifecycle": lifecycle, "failedChecks": [failure], "pass": None,
                "status": "INCONCLUSIVE", "reason": "destroy hidden-leaf visibility telemetry is missing"}
    failures = []
    if record.get("destroyActionError"):
        failures.append({"check": "destroy.action", "error": record["destroyActionError"]})
    if lifecycle.get("overlayExisted") is not True:
        failures.append({"check": "destroy.overlayExisted", "measured": record.get("preDestroyOverlay"),
                         "expected": "connected arrow overlay with at least one draw"})
    if lifecycle.get("disposed") is not True:
        failures.append({"check": "destroy.disposed", "measured": lifecycle.get("disposed"), "expected": True,
                         "overlayResidue": record.get("overlayResidue")})
    if record.get("hiddenLeafCanvases"):
        failures.append({"check": "destroy.hiddenLeafVisibility", "measured": record["hiddenLeafCanvases"],
                         "expected": []})
    if lifecycle.get("postDestroyConnectedFrames") != 0:
        failures.append({"check": "destroy.postConnectedFrames", "measured": lifecycle.get("postDestroyConnectedFrames"),
                         "maximum": 0})
    if lifecycle.get("postDestroyRedraws") != 0:
        failures.append({"check": "destroy.postDestroyRedraws", "measured": lifecycle.get("postDestroyRedraws"),
                         "maximum": 0})
    if lifecycle.get("beforeBuildDeadline") is not True:
        failures.append({"check": "destroy.deadline", "measured": lifecycle.get("destroyElapsed"),
                         "maximum": lifecycle.get("buildDeadline")})
    return {"body": [], "handback": {}, "lifecycle": lifecycle,
            "failedChecks": failures, "pass": not failures}


def finalize_report(report: dict[str, Any], out: Path) -> None:
    by_name = {run["arm"]: run for run in report["runs"]}
    on = by_name.get("on")
    off = by_name.get("off")
    busy = by_name.get("busy")
    if on and off and on.get("status") != "INCONCLUSIVE" and off.get("status") != "INCONCLUSIVE":
        same = on.get("settledSha256") == off.get("settledSha256")
        on["score"]["handback"]["endEqualsOff"] = same
        if not same:
            on["score"]["failedChecks"].append(
                {"check": "handback.endEqualsOff", "onSha256": on.get("settledSha256"),
                 "offSha256": off.get("settledSha256"), "expected": "equal"}
            )
        label = compare_label_dissolve(out, on, off)
        on["score"]["labelDissolve"] = label
        on["score"]["failedChecks"].extend(label["failedChecks"])
        on["score"]["pass"] = not on["score"]["failedChecks"]
    def arrow_refused(arm: str) -> bool:
        run = by_name.get(arm, {})
        geometries = run.get("geometries", [])
        arrow = next((str(item["objectID"]) for item in geometries
                      if item["name"].endswith("LineDrawForLine")), None)
        line = next((str(item["objectID"]) for item in geometries
                     if not item["name"].endswith("LineDrawForLine")), None)
        seen = {str(overlay.get("id")) for row in run.get("overlayFrames", [])
                for overlay in row.get("overlays", []) if overlay.get("draws", 0) > 0}
        return arrow is not None and line in seen and arrow not in seen

    def refusal_control(arm: str) -> bool | None:
        run = by_name.get(arm)
        if not run or run.get("status") == "INCONCLUSIVE":
            return None
        measured = run.get("probeHeadDiff")
        if not isinstance(measured, (int, float)) or not math.isfinite(measured):
            run.update({"status": "INCONCLUSIVE", "reason": "pre-threshold head-difference telemetry is missing",
                        "pass": None})
            return None
        return arrow_refused(arm) and measured > 48

    def arrow_pop_residual(run: dict[str, Any] | None) -> dict[str, Any]:
        return next((item.get("popResidual") or {} for item in (run or {}).get("score", {})
                    .get("handback", {}).get("effects", []) if item.get("name", "").endswith("LineDrawForLine")), {})

    on_pop = arrow_pop_residual(on)
    static_pop = arrow_pop_residual(by_name.get("head-static"))
    static_margin = max(8, math.ceil(float(on_pop.get("comparedPixels") or 0) * 0.05))
    static_fails = (static_pop.get("overTolerancePixels") is not None
                    and on_pop.get("overTolerancePixels") is not None
                    and static_pop["overTolerancePixels"] > on_pop["overTolerancePixels"] + static_margin)

    controls = {
        "offFailsReveal": off is not None and off.get("status") != "INCONCLUSIVE"
        and any(item.get("pass") is False for item in off.get("score", {}).get("body", [])),
        "headStaticFailsHandback": static_fails,
        "diamondTailRefused": refusal_control("head-diamond-tail"),
        "pairedProtrusionsRefused": refusal_control("head-protrusions"),
        "busyGoToRefused": busy is not None and busy.get("hostGoToBusyRefused") is True
        and busy.get("jumpBefore") == busy.get("jumpAfter"),
    }
    measurements = {
        "offFailsReveal": {"bodyPasses": [item.get("pass") for item in off.get("score", {}).get("body", [])]
                           if off else None},
        "headStaticFailsHandback": {"onResidual": on_pop, "staticResidual": static_pop,
                                    "minimumAdditionalPixels": static_margin},
        "diamondTailRefused": {"refused": arrow_refused("head-diamond-tail"),
                               "headDifference": by_name.get("head-diamond-tail", {}).get("probeHeadDiff"),
                               "minimumExclusive": 48},
        "pairedProtrusionsRefused": {"refused": arrow_refused("head-protrusions"),
                                     "headDifference": by_name.get("head-protrusions", {}).get("probeHeadDiff"),
                                     "minimumExclusive": 48},
        "busyGoToRefused": {"hostRefused": busy.get("hostGoToBusyRefused") if busy else None,
                             "jumpResult": busy.get("jumpResult") if busy else None,
                             "sceneBefore": busy.get("jumpBefore") if busy else None,
                             "sceneAfter": busy.get("jumpAfter") if busy else None},
    }
    report["controls"] = controls
    report["controlMeasurements"] = measurements
    failures = [{"check": f"controls.{name}", **measurements[name], "expected": True}
                for name, passed in controls.items() if not passed]
    for run in report["runs"]:
        if run.get("status") == "INCONCLUSIVE":
            run["pass"] = None
        elif run["arm"] == "off":
            run["pass"] = controls["offFailsReveal"]
        elif run["arm"] == "head-static":
            run["pass"] = controls["headStaticFailsHandback"]
        elif run["arm"] == "head-diamond-tail":
            run["pass"] = controls["diamondTailRefused"]
        elif run["arm"] == "head-protrusions":
            run["pass"] = controls["pairedProtrusionsRefused"]
        else:
            run["pass"] = run.get("score", {}).get("pass", run.get("pass", False)) is True
        if (run.get("status") != "INCONCLUSIVE"
                and run["arm"] not in ("off", "head-static", "head-diamond-tail", "head-protrusions")
                and run.get("pass") is False):
            arm_failures = run.get("score", {}).get("failedChecks", run.get("failedChecks", []))
            failures.extend({**failure, "check": f"arms.{run['arm']}.{failure['check']}"}
                            for failure in arm_failures)
            if not arm_failures:
                failures.append({"check": f"arms.{run['arm']}.pass", "measured": False, "expected": True,
                                 "error": run.get("error")})
    report["failedChecks"] = failures
    inconclusive_runs = [run for run in report["runs"] if run.get("status") == "INCONCLUSIVE"]
    candidates = [run for run in report["runs"] if run.get("status") != "INCONCLUSIVE"]
    report["pass"] = not inconclusive_runs and all(run.get("pass") is True for run in candidates) and all(controls.values())
    report["inconclusive"] = [{"arm": run["arm"], "reason": run.get("reason")} for run in report["runs"]
                              if run.get("status") == "INCONCLUSIVE"]


def score_saved_run(out: Path) -> dict[str, Any]:
    source = out / "report.json"
    report = json.loads(source.read_text())
    report["rescoredFrom"] = str(source.resolve())
    retired = [run["arm"] for run in report["runs"] if run["arm"] in ("head-notch", "head-offset")]
    report["runs"] = [run for run in report["runs"] if run["arm"] not in ("head-notch", "head-offset")]
    report["removedArms"] = retired
    evidence: dict[str, tuple[np.ndarray, np.ndarray, list[tuple[float, np.ndarray]]]] = {}
    for run in report["runs"]:
        if run["arm"] in ("neighbour", "keyer") and run.get("status") == "INCONCLUSIVE":
            continue
        try:
            evidence[run["arm"]] = saved_frames(out, run["arm"])
        except Exception as exc:
            run.update({"status": "INCONCLUSIVE", "reason": f"offline evidence integrity: {exc}", "pass": None})
    geometries = next((run.get("geometries") for run in report["runs"] if run.get("geometries")), None)
    report["offlineGeometry"] = {"source": "saved" if geometries else "unavailable"}
    if not geometries:
        reason = "saved live geometry is missing; legacy overlay-affine recovery is not valid evidence"
        report["offlineGeometry"]["reason"] = reason
        for run in report["runs"]:
            if run["arm"] not in ("neighbour", "keyer") and run.get("status") != "INCONCLUSIVE":
                run.update({"status": "INCONCLUSIVE", "reason": f"offline evidence integrity: {reason}", "pass": None})
    later_rectangles = None
    if geometries is not None:
        try:
            manifest = json.loads(Path(report["manifest"]).read_text())
            _, slide = slide_json(Path(report["deck"]), manifest, int(report["slide"]))
            later_rectangles = later_build_rects(slide, geometries)
            report["laterBuildRects"] = later_rectangles
        except Exception as exc:
            hold = next((run for run in report["runs"] if run["arm"] == "hold-p1"), None)
            if hold and hold.get("status") != "INCONCLUSIVE":
                hold.update({"status": "INCONCLUSIVE",
                             "reason": f"offline evidence integrity: later-build rectangles unavailable: {exc}",
                             "pass": None})
    report["offlineClock"] = {"source": "stock-layer-opacity-animation", "perArm": {}}
    for run in report["runs"]:
        if run["arm"] not in evidence or run.get("status") == "INCONCLUSIVE" or geometries is None:
            continue
        missing = [name for name in ("advanceFrameTime", "advancePerformanceMs", "frameClock", "overlayFrames")
                   if name not in run]
        if missing:
            run.update({"status": "INCONCLUSIVE",
                        "reason": f"offline evidence integrity: missing {', '.join(missing)}", "pass": None})
            continue
        try:
            run["effectStarts"] = animation_effect_starts(run, geometries)
        except Exception as exc:
            run.update({"status": "INCONCLUSIVE",
                        "reason": f"offline evidence integrity: {exc}", "pass": None})
            continue
        report["offlineClock"]["perArm"][run["arm"]] = run["effectClocks"]
        run["geometries"] = geometries
        if later_rectangles is not None:
            run["laterBuildRects"] = later_rectangles
        run.pop("status", None)
        run.pop("reason", None)
    origins: dict[str, np.ndarray] = {}
    reference_before = None
    on = next((run for run in report["runs"] if run["arm"] == "on" and run.get("status") != "INCONCLUSIVE"), None)
    if on and "on" in evidence and geometries is not None:
        reference_before, _, on_frames = evidence["on"]
        for geometry in geometries:
            effect_begin = float(on["advanceFrameTime"]) + float(on["effectStarts"].get(str(geometry["objectID"]), 0))
            prior = [item for item in on_frames if item[0] < effect_begin]
            origins[str(geometry["objectID"])] = prior[-1][1] if prior else reference_before
    for run in report["runs"]:
        if run["arm"] not in evidence or run.get("status") == "INCONCLUSIVE" or geometries is None:
            continue
        before, final, frames = evidence[run["arm"]]
        run["score"] = (destroy_score(run) if run["arm"] == "destroy"
                        else score_frames(run, geometries, before, final, frames, origins))
        if (run["score"].get("status") == "INCONCLUSIVE"
                and run["arm"] not in ("off", "head-static", "head-diamond-tail", "head-protrusions")):
            run.update({"status": "INCONCLUSIVE", "reason": run["score"]["reason"], "pass": None})
    finalize_report(report, out)
    target = out / "rescored-report.json"
    target.write_text(json.dumps(report, indent=1, default=lambda value: value.item() if isinstance(value, np.generic) else str(value)))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("deck", type=Path, nargs="?")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--score", type=Path)
    parser.add_argument("--slide", type=int, default=2)
    parser.add_argument("--arms", default=",".join(DEFAULT_ARMS))
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--keyer-port", type=int)
    parser.add_argument("--keyer-password", default=os.getenv("OBED_OBS_PASSWORD"))
    parser.add_argument("--keyer-source", default="AK")
    parser.add_argument("--keyer-seconds", type=float, default=3.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.score:
        report = score_saved_run(args.score.resolve())
        print(json.dumps({"pass": report["pass"], "arms": [{"arm": run["arm"], "status": run.get("status"),
                                                               "reason": run.get("reason"), "pass": run.get("pass"),
                                                               "failedChecks": run.get("score", {}).get("failedChecks",
                                                                                                          run.get("failedChecks", []))}
                                                              for run in report["runs"]]}, indent=1))
        return 0 if report["pass"] else 1
    if args.deck is None or args.out is None:
        raise SystemExit("deck and --out are required unless --score is used")
    args.out.mkdir(parents=True, exist_ok=True)
    arms = ("calibrate",) if args.calibrate else tuple(item.strip() for item in args.arms.split(",") if item.strip())
    if arms == ("keyer",):
        if not args.keyer_port:
            raise SystemExit("--keyer-port is required for the keyer arm")
        manifest_path = args.manifest or args.deck.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        _, slide = slide_json(args.deck.resolve(), manifest, args.slide)
        geometries = authored_geometries(line_effects(slide))
        report = {"runs": [keyer_arm(args.keyer_port, args.keyer_password, args.keyer_source, args.out,
                                     args.keyer_seconds, geometries)]}
        report["pass"] = report["runs"][0]["pass"]
        report["inconclusive"] = []
    else:
        manifest_path = args.manifest or args.deck.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        runs = [neighbour_arm(args.deck.resolve(), manifest, args.out) if arm == "neighbour"
                else run_arm(args.deck.resolve(), manifest["slides"], manifest, args.slide, arm, args.out) for arm in arms]
        report = {"deck": str(args.deck.resolve()), "manifest": str(manifest_path.resolve()), "slide": args.slide, "runs": runs}
        if not args.calibrate:
            (args.out / "report.json").write_text(json.dumps(report, indent=1, default=lambda value: value.item() if isinstance(value, np.generic) else str(value)))
            report = score_saved_run(args.out)
    if args.calibrate:
        values = [frame.get("headDiff") for run in report["runs"] for item in run.get("overlayFrames", [])
                  for frame in item.get("overlays", []) if frame.get("headDiff") is not None]
        measured = values[0] if values else None
        report["calibration"] = {"ownerArrowSymmetricDifference": measured, "samples": len(values)}
        report["pass"] = all("error" not in run for run in report["runs"]) and measured is not None
        if measured is None:
            report["failedChecks"] = [{"check": "calibration.ownerArrowSymmetricDifference", "measured": None,
                                       "expected": "integer"}]
        print(f"owner-arrow-symmetric-difference={measured if measured is not None else 'unmeasured'}")
    (args.out / "report.json").write_text(json.dumps(report, indent=1, default=lambda value: value.item() if isinstance(value, np.generic) else str(value)))
    print(json.dumps({"pass": report["pass"], "arms": [{"arm": run["arm"], "error": run.get("error"),
                                                         "status": run.get("status"), "reason": run.get("reason"),
                                                         "pass": run.get("pass", run.get("score", {}).get("pass")),
                                                         "failedChecks": run.get("score", {}).get("failedChecks",
                                                                                                    run.get("failedChecks", []))}
                                                        for run in report["runs"]]}, indent=1))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
