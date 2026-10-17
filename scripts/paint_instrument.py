#!/usr/bin/env python3
"""Per-frame "painted" instrument for the live-continuity probe (`.agents/plans/keynote_live_continuity_instrument.plan.md`).

The page records raw readings (`PAINT_READ_FN_JS`, `PREPAINT_FN_JS`, both composed into the probe's sampler IIFE after
`STAGE_MAP_FN_JS`); Python decides. Never imports the probe: thresholds the probe owns are passed in.
"""
from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter
from typing import Any, Callable, Mapping, Sequence

from obed_edom.live_continuity import canonical_asset_name

SAMPLER_SCHEMA = 2
PAINT_OPACITY_FLOOR = 0.02
PAINT_OPAQUE_MIN = 0.99
PAINT_CONTROL_VARIANTS = ("ancestor-opacity", "ancestor-half", "ancestor-display", "element-visibility")
PAINT_CONTROL_PHASES = ("settled", "bridge", "pin")
PAINT_CONTROL_TIMINGS = ("early", "late")

PAINTED, PARTIAL, UNPAINTED, UNREADABLE, NOT_PAINTER = "painted", "partial", "unpainted", "unreadable", "not-painter"
SEQ_LIST_CAP = 600
RUNS_CAP = 10
LOCAL_CADENCE_DELTAS = 8
WINDOW_PAD_S = 2.0
FORCE_WRAP_WINDOW_AFTER_SEEK_MS = 1000.0

Phases = dict[str, Any]
CarryWindow = dict[str, Any]

COST_RECORDER_JS = r"""
(function(){
  if (window.__obedCost) return true;
  var VERSION = 1, CHUNK_SIZE = 256;
  var stopped = false, errors = [], hooks = Object.create(null), stack = [];
  var frames = store(), frameKey = null, frameTotal = 0, frameTouched = false;
  var lastNow = performance.now();
  function store(){ return {count: 0, chunks: []}; }
  function fail(message){ if (errors.length < 50) errors.push(String(message)); }
  function now(){
    var value = performance.now();
    if (typeof value !== 'number' || !isFinite(value)) { fail('performance.now is not finite'); return lastNow; }
    return value;
  }
  function currentFrame(){
    var timeline = document && document.timeline;
    var value = timeline ? timeline.currentTime : null;
    return typeof value === 'number' && isFinite(value) ? value : 0;
  }
  function append(target, value){
    var index = target.count % CHUNK_SIZE;
    if (index === 0) target.chunks.push(new Float64Array(CHUNK_SIZE));
    target.chunks[target.chunks.length - 1][index] = value;
    target.count++;
  }
  function flushFrame(){
    if (!frameTouched) return;
    append(frames, frameTotal);
    frameTotal = 0;
    frameTouched = false;
  }
  function advance(value){
    var key = currentFrame();
    if (frameKey === null) frameKey = key;
    if (key !== frameKey) { flushFrame(); frameKey = key; }
    var delta = value - lastNow;
    if (!(delta >= 0) || !isFinite(delta)) { fail('clock moved backwards'); delta = 0; }
    if (stack.length) {
      frameTotal += delta;
      frameTouched = true;
      stack[stack.length - 1].exclusive += delta;
    }
    lastNow = value;
  }
  function hookOf(name){
    return typeof name === 'string' && name && name !== 'frame.total' ? hooks[name] : null;
  }
  function install(name){
    if (stopped) return false;
    if (typeof name !== 'string' || !name) { fail('install requires a hook name'); return false; }
    if (name === 'frame.total') return true;
    if (!hooks[name]) hooks[name] = {installed: true, values: store()};
    else hooks[name].installed = true;
    return true;
  }
  function enter(name){
    if (stopped) return false;
    var hook = hookOf(name);
    if (!hook || !hook.installed) { fail('enter of uninstalled hook ' + String(name)); return false; }
    advance(now());
    if (stack.length && stack[stack.length - 1].hook === name) {
      stack[stack.length - 1].depth++;
    } else {
      stack.push({hook: name, exclusive: 0, depth: 1});
    }
    return true;
  }
  function leave(name){
    if (stopped) return false;
    advance(now());
    if (!stack.length) { fail('leave without enter for ' + String(name)); return false; }
    var span = stack[stack.length - 1];
    if (span.hook !== name) { fail('unbalanced leave ' + String(name) + ', expected ' + span.hook); return false; }
    if (span.depth > 1) { span.depth--; return true; }
    stack.pop();
    append(hooks[name].values, span.exclusive);
    return true;
  }
  function stop(){
    if (stopped) return true;
    advance(now());
    if (stack.length) fail('stop with unclosed hooks: ' + stack.map(function(span){ return span.hook; }).join(', '));
    stack.length = 0;
    flushFrame();
    stopped = true;
    return true;
  }
  function values(target, offset, n){
    var start = typeof offset === 'number' && isFinite(offset) ? Math.max(0, Math.floor(offset)) : 0;
    var size = typeof n === 'number' && isFinite(n) ? Math.max(0, Math.floor(n)) : target.count;
    var end = Math.min(target.count, start + size), out = [];
    for (var i = start; i < end; i++) {
      var chunk = target.chunks[Math.floor(i / CHUNK_SIZE)];
      out.push(chunk[i % CHUNK_SIZE]);
    }
    return out;
  }
  function read(name, offset, n){
    var selected = arguments.length ? name : null;
    var result = {version: VERSION, stopped: stopped, errors: errors.slice(), hooks: {}, frames: {count: frames.count, chunks: []}};
    Object.keys(hooks).forEach(function(hook){
      var source = hooks[hook];
      result.hooks[hook] = {installed: source.installed, count: source.values.count, chunks: []};
      if (selected === null || selected === hook) result.hooks[hook].chunks.push(values(source.values, offset, n));
    });
    if (selected === null || selected === 'frame.total') result.frames.chunks.push(values(frames, offset, n));
    return result;
  }
  window.__obedCost = {install: install, enter: enter, leave: leave, stop: stop, read: read};
  return true;
})();
"""


def _linear_percentile(values: Sequence[float], percentile: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    rank = (len(ordered) - 1) * percentile / 100.0
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def summarize_instrument_cost(
    recording: Mapping[str, Any], applicability: Mapping[str, bool], *, budget_ms: float = 8.0
) -> dict[str, dict[str, Any]]:
    """Summarize every recorded duration without truncating the capture."""
    hooks = recording.get("hooks") if isinstance(recording, Mapping) else None
    frames = recording.get("frames") if isinstance(recording, Mapping) else None
    recording_complete = (
        recording.get("version") == 1
        and recording.get("stopped") is True
        and recording.get("errors") == []
    ) if isinstance(recording, Mapping) else False
    out: dict[str, dict[str, Any]] = {}
    for hook, applicable in applicability.items():
        source = frames if hook == "frame.total" else hooks.get(hook) if isinstance(hooks, Mapping) else None
        source_installed = hook == "frame.total" and isinstance(frames, Mapping)
        if isinstance(source, Mapping) and hook != "frame.total":
            source_installed = source.get("installed") is True
        chunks = source.get("chunks") if isinstance(source, Mapping) else []
        durations = [
            float(value)
            for chunk in chunks if isinstance(chunks, list) and isinstance(chunk, list)
            for value in chunk
            if _finite(value) is not None and float(value) >= 0
        ] if isinstance(chunks, list) else []
        declared = source.get("count") if isinstance(source, Mapping) else 0
        complete = recording_complete and (
            isinstance(declared, int) and not isinstance(declared, bool) and declared == len(durations)
        )
        measured = applicable is True and source_installed and complete
        count = len(durations) if measured else 0
        p95 = _linear_percentile(durations, 95.0) if measured else None
        maximum = max(durations) if measured and durations else None
        out[str(hook)] = {
            "applicable": applicable is True,
            "installed": measured,
            "count": count,
            "p95": p95,
            "max": maximum,
            "overBudget": sum(value > budget_ms for value in durations) if measured else 0,
        }
    return out


def _finite(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def _connected(video: Mapping[str, Any]) -> bool | None:
    value = video.get("isConnected") if "isConnected" in video else video.get("connected")
    return value if isinstance(value, bool) else None


def _readable_nonzero_rect(video: Mapping[str, Any]) -> bool:
    rect = video.get("rect")
    if not isinstance(rect, Mapping):
        rect = video.get("rectScreen")
    return bool(
        isinstance(rect, Mapping)
        and all(_finite(rect.get(key)) is not None for key in ("x", "y", "w", "h"))
        and float(rect["w"]) > 0.0
        and float(rect["h"]) > 0.0
    )


def _visible_observation(observation: Mapping[str, Any]) -> bool:
    return observation.get("connected") is True and observation.get("readableNonzeroRect") is True


def _decoded_observation(observation: Mapping[str, Any]) -> bool:
    if (_finite(observation.get("readyState")) or -math.inf) < 2.0:
        return False
    return "videoWidth" not in observation or (_finite(observation.get("videoWidth")) or 0.0) > 0.0


def read_phases(rows: Sequence[Mapping[str, Any]], plan: Mapping[str, Any]) -> Phases:
    """Read row phases and decoder mounts once."""
    phase_rows: list[dict[str, Any]] = []
    mounts: dict[tuple[Any, str], dict[str, Any]] = {}
    for index, source_row in enumerate(rows):
        row = {
            "index": index,
            "t": source_row.get("t"),
            "ts": source_row.get("ts"),
            "seq": source_row.get("seq"),
            "scene": source_row.get("scene"),
            "playerState": source_row.get("playerState"),
            "busy": source_row.get("busy"),
            "nextSceneId": source_row.get("nextSceneId"),
            "hash": source_row.get("hash"),
            "videos": [],
        }
        phase_rows.append(row)
        videos = source_row.get("videos")
        if not isinstance(videos, Sequence) or isinstance(videos, (str, bytes)):
            continue
        for video in videos:
            if not isinstance(video, Mapping) or video.get("id") is None:
                continue
            identity = video["id"]
            asset = canonical_asset_name(video.get("src"))
            observation = {
                "id": identity,
                "asset": asset,
                "rowIndex": index,
                "t": source_row.get("t"),
                "scene": source_row.get("scene"),
                "readyState": video.get("readyState"),
                "connected": _connected(video),
                "readableNonzeroRect": _readable_nonzero_rect(video),
            }
            if "videoWidth" in video:
                observation["videoWidth"] = video.get("videoWidth")
            row["videos"].append(observation)
            if not asset:
                continue
            mount = mounts.setdefault((identity, asset), {
                "id": identity,
                "asset": asset,
                "observations": [],
            })
            mount["observations"].append(observation)

    entry_cold: dict[str, dict[str, Any]] = {}
    for mount in mounts.values():
        identity = mount["id"]
        observations = sorted(
            (obs for obs in mount["observations"] if _finite(obs.get("t")) is not None), key=lambda obs: obs["t"]
        )
        first = observations[0] if observations else None
        decoded = [obs for obs in observations if _visible_observation(obs) and _decoded_observation(obs)]
        first_decoded = decoded[0] if decoded else None
        before_decode = [obs for obs in observations if first_decoded is None or obs["t"] < first_decoded["t"]]
        visible_undecoded = [
            obs for obs in before_decode
            if _visible_observation(obs) and (_finite(obs.get("readyState")) or -math.inf) < 2.0
        ]
        first_t = first["t"] if first is not None else None
        decoded_t = first_decoded["t"] if first_decoded is not None else None
        missing_endpoints = {
            "mountTime": first is not None and first["rowIndex"] == 0,
            "firstDecoded": first_decoded is None,
        }
        cold_scenes = sorted({obs["scene"] for obs in before_decode if _finite(obs.get("scene")) is not None})
        if not before_decode and first is not None and _finite(first.get("scene")) is not None:
            cold_scenes = [first["scene"]]
        entry_cold[str(identity)] = {
            "asset": mount["asset"],
            "firstSeenT": first_t,
            "firstDecodedT": decoded_t,
            "durationMs": round(decoded_t - first_t, 3) if (
                decoded_t is not None and first_t is not None and not missing_endpoints["mountTime"]
            ) else None,
            "rows": len(before_decode),
            "visibleUndecodedRows": len(visible_undecoded),
            "visibleUndecodedDurationMs": round(
                max(0.0, (decoded_t if decoded_t is not None else visible_undecoded[-1]["t"])
                    - visible_undecoded[0]["t"]), 3
            ) if visible_undecoded else 0.0,
            "scene": cold_scenes[0] if len(cold_scenes) == 1 else None,
            "scenes": cold_scenes,
            "missingEndpoints": missing_endpoints,
        }

    return {
        "rows": phase_rows,
        "mounts": mounts,
        "entryColdStart": entry_cold,
    }


def _add_unreadable(items: list[dict[str, Any]], reason: str, times: Sequence[Any] = ()) -> None:
    hit = next((item for item in items if item["reason"] == reason), None)
    clean = [value for value in times if _finite(value) is not None]
    if hit is None:
        items.append({"reason": reason, "times": clean[:5]})
    else:
        hit["times"] = list(dict.fromkeys([*hit["times"], *clean]))[:5]


def _clip_for(phases: Phases, spec: Mapping[str, Any]) -> dict[str, float | None]:
    rows = phases.get("rows") or []
    source, until = _finite(spec.get("sourceScene")), _finite(spec.get("untilScene"))
    at_scene = _finite(spec.get("atScene"))
    start = end = None
    if source is not None:
        values = [row["t"] for row in rows if _finite(row.get("t")) is not None
                  and (scene := _finite(row.get("scene"))) is not None and scene >= source]
        start = min(values) if values else None
    if until is not None and at_scene is not None and until - 1.0 > at_scene:
        values = [row["t"] for row in rows if _finite(row.get("t")) is not None
                  and (scene := _finite(row.get("scene"))) is not None and scene >= until - 1.0]
        end = min(values) - 1e-6 if values else None
    return {"start": start, "end": end}


def _base_bounds(window: CarryWindow) -> tuple[float | None, float | None]:
    crossing = window.get("crossing")
    if not isinstance(crossing, Mapping):
        return None, None
    clip = window.get("chainClip") if isinstance(window.get("chainClip"), Mapping) else {}
    forced = window.get("forcedSeek") if isinstance(window.get("forcedSeek"), Mapping) else {}
    floors = [value for value in (_finite(clip.get("start")), _finite(forced.get("start"))) if value is not None]
    grounded = _finite(window.get("groundedStart"))
    if grounded is None:
        return None, None
    start = max([grounded, *floors])
    ends = [value for value in (_finite(crossing.get("end")), _finite(clip.get("end"))) if value is not None]
    return start, min(ends) if ends else None


def window_bounds(phases: Phases, window: CarryWindow, element_id: Any) -> tuple[float | None, float | None]:
    """Union the legacy and settled-source starts, then skip one unambiguous cold-start prefix."""
    start, end = _base_bounds(window)
    if start is None or end is None:
        return None, None
    floors = [
        value for value in (
            _finite((window.get("chainClip") or {}).get("start")),
            _finite((window.get("forcedSeek") or {}).get("start")),
        ) if value is not None
    ]
    source = _finite(window.get("sourceScene"))
    if source is not None:
        def decoded_in_scene(scene: float) -> list[float]:
            visit = max(
                (row["t"] for row in phases.get("rows") or []
                 if _finite(row.get("t")) is not None
                 and (value := _finite(row.get("scene"))) is not None and value < scene),
                default=-math.inf,
            )
            return [
                row["t"] for row in phases.get("rows") or []
                if _finite(row.get("t")) is not None and row["t"] > visit
                and _finite(row.get("scene")) == scene and row.get("busy") is False
                and any(
                    observation.get("id") == element_id
                    and (_finite(observation.get("readyState")) or -math.inf) >= 2.0
                    for observation in row.get("videos") or []
                )
            ]

        decoded = decoded_in_scene(source)
        paint_start = min(decoded) if decoded else start
        start = min(start, max([paint_start, *floors]))
    asset = window.get("asset")
    rows = sorted(
        (row for row in phases.get("rows") or [] if _finite(row.get("t")) is not None and start <= row["t"] <= end),
        key=lambda row: row["t"],
    )
    decoded_before = any(
        observation.get("id") == element_id
        and observation.get("asset") == asset
        and _finite(observation.get("t")) is not None
        and observation["t"] < start
        and _decoded_observation(observation)
        for mount in (phases.get("mounts") or {}).values()
        for observation in mount.get("observations") or []
    )
    prefix: list[dict[str, Any]] = []
    for row in rows:
        observations = [
            observation for observation in row.get("videos") or []
            if observation.get("id") == element_id and observation.get("asset") == asset
        ]
        observation = observations[0] if len(observations) == 1 else None
        ready = _finite(observation.get("readyState")) if observation is not None else None
        if (
            decoded_before
            or observation is None
            or not _visible_observation(observation)
            or ready is None
            or ready >= 2.0
        ):
            break
        prefix.append(row)
    if prefix:
        following = rows[len(prefix)] if len(prefix) < len(rows) else None
        if following is not None:
            start = following["t"]
        first_seen = prefix[0]["t"]
        duration = round(start - first_seen, 3)
    else:
        first_seen = None
        duration = 0.0
    window["coldStart"] = {"rows": len(prefix), "durationMs": duration, "firstSeenT": first_seen}
    interval = window.get("glInterval")
    if isinstance(interval, Mapping):
        window.setdefault("glSegments", {})[element_id] = _gl_segments(phases, start, end, interval)
    return start, end


def _gl_segments(phases: Phases, start: float, end: float, interval: Mapping[str, Any]) -> list[dict[str, float]]:
    if end < start:
        return []
    rows = [row for row in phases.get("rows") or [] if _finite(row.get("t")) is not None and start <= row["t"] <= end]
    def frame_time(row: Mapping[str, Any]) -> float:
        ts = _finite(row.get("ts"))
        return ts if ts is not None else row["t"]

    before = [row for row in rows if frame_time(row) < interval["start"]]
    after = [row for row in rows if frame_time(row) > interval["end"]]
    segments = []
    if before:
        segments.append({"start": start, "end": max(row["t"] for row in before)})
    if after:
        segments.append({"start": min(row["t"] for row in after), "end": end})
    return segments


def carry_window(
    phases: Phases,
    spec: Mapping[str, Any],
    *,
    forced_seek: Mapping[str, Any] | None = None,
    gl_interval: Mapping[str, Any] | None = None,
) -> CarryWindow:
    """Build the legacy base window and its constraints."""
    unreadable: list[dict[str, Any]] = []
    rows = sorted(
        (row for row in phases.get("rows") or [] if _finite(row.get("t")) is not None), key=lambda row: row["t"]
    )
    boundary = _finite(spec.get("atScene"))
    transition = _finite(spec.get("transitionScene"))
    crossing = None
    if boundary is None:
        _add_unreadable(unreadable, "carry spec has no readable atScene")
    elif not rows:
        _add_unreadable(unreadable, "boundary crossing not observed")
    else:
        first_placed = next((index for index, row in enumerate(rows) if _finite(row.get("scene")) is not None), None)
        unplaced = [] if first_placed is None else [
            row["t"] for row in rows[first_placed:] if _finite(row.get("scene")) is None
        ]
        before = [row["t"] for row in rows if (scene := _finite(row.get("scene"))) is not None
                  and scene < boundary]
        after = [row["t"] for row in rows if (scene := _finite(row.get("scene"))) is not None
                 and scene >= boundary]
        if unplaced:
            _add_unreadable(unreadable, "boundary crossing has an unplaced row after sampling began", unplaced)
        elif before and after and max(before) < min(after):
            crossing = {
                "start": max(max(before) - WINDOW_PAD_S * 1000.0, rows[0]["t"]),
                "end": min(min(after) + WINDOW_PAD_S * 1000.0, rows[-1]["t"]),
                "lastBeforeT": max(before),
                "firstAfterT": min(after),
            }
        else:
            _add_unreadable(unreadable, "boundary crossing not observed", [*(before[-2:] if before else []), *(after[:2] if after else [])])

    grounded_start = crossing["start"] if crossing is not None else None
    if crossing is not None and transition is not None:
        source = transition - 1.0
        earlier = max(
            (row["t"] for row in rows if (scene := _finite(row.get("scene"))) is not None and scene < source),
            default=-math.inf,
        )
        settled = [
            row["t"] for row in rows
            if row["t"] > earlier and _finite(row.get("scene")) == source and row.get("busy") is False
        ]
        if settled:
            grounded_start = min(grounded_start, min(settled))
        else:
            move_before = [row["t"] for row in rows if (scene := _finite(row.get("scene"))) is not None and scene < transition]
            move_after = [row["t"] for row in rows if (scene := _finite(row.get("scene"))) is not None and scene >= transition]
            if move_before and move_after and max(move_before) < min(move_after):
                move_start = max(max(move_before) - WINDOW_PAD_S * 1000.0, rows[0]["t"])
                grounded_start = min(grounded_start, move_start)
        grounding = [
            row["t"] for row in rows
            if earlier < row["t"] < grounded_start and (
                _finite(row.get("scene")) is None
                or _finite(row.get("scene")) == source and not isinstance(row.get("busy"), bool)
            )
        ]
        if grounding:
            _add_unreadable(unreadable, "a row that could ground the start earlier has an unreadable phase", grounding)

    chain_clip = None if forced_seek is not None else _clip_for(phases, spec)
    forced = None
    if forced_seek is not None:
        seeked = _finite(forced_seek.get("seekedT"))
        if seeked is None:
            _add_unreadable(unreadable, "forced seek has no readable seekedT")
        else:
            forced = {
                "seekedT": seeked,
                "start": seeked + FORCE_WRAP_WINDOW_AFTER_SEEK_MS,
            }
    valid_gl = (
        isinstance(gl_interval, Mapping)
        and _finite(gl_interval.get("start")) is not None
        and _finite(gl_interval.get("end")) is not None
        and float(gl_interval["end"]) >= float(gl_interval["start"])
    )
    window: CarryWindow = {
        "crossing": crossing,
        "groundedStart": grounded_start,
        "sourceScene": (transition if transition is not None else boundary) - 1.0 if boundary is not None else None,
        "asset": canonical_asset_name(spec.get("asset")),
        "forcedSeek": forced,
        "glInterval": dict(gl_interval) if valid_gl else None,
        "glSegments": {},
        "unreadable": unreadable,
    }
    if chain_clip is not None:
        window["chainClip"] = chain_clip
    return window

PAINT_READ_FN_JS = r"""
  function labelOf(n){
    if (!n) return null;
    if (n.nodeType === 11) return '#shadow-root';
    if (n.nodeType === 9) return '#document';
    if (n.nodeType !== 1) return '#node';
    return String(n.tagName || '').toLowerCase() + (n.id ? '#' + n.id : '');
  }
  function flatParent(n){
    var p = n ? n.parentNode : null;
    if (p && p.nodeType === 11) return p.host || null;
    return p || null;
  }
  function layerOf(n){
    for (; n; n = flatParent(n)) {
      if (n.nodeType === 1 && n.id && String(n.id).indexOf('layer') === 0) return n.id;
    }
    return null;
  }
  function paintBoxOf(r){ return {x: r.left, y: r.top, w: r.width, h: r.height}; }
  function paintMeet(a, b){
    var x = Math.max(a.x, b.x), y = Math.max(a.y, b.y);
    var r = Math.min(a.x + a.w, b.x + b.w), bottom = Math.min(a.y + a.h, b.y + b.h);
    return r > x && bottom > y ? {x: x, y: y, w: r - x, h: bottom - y} : null;
  }
  function coverUp(){
    var el = document.getElementById('obed-output-black');
    return !!el && getComputedStyle(el).display !== 'none';
  }
  function stageBox(){
    var el = document.getElementById('stageArea');
    return el ? paintBoxOf(el.getBoundingClientRect()) : null;
  }
  function paintSet(value){ return !!value && value !== 'none'; }
  function paintEffectOf(cs){
    if (paintSet(cs.filter)) return 'filter';
    if (paintSet(cs.clipPath)) return 'clip-path';
    if (paintSet(cs.maskImage) || paintSet(cs.webkitMaskImage)) return 'mask-image';
    return null;
  }
  function paintMakesBlock(cs){
    return paintSet(cs.transform) || paintSet(cs.perspective) || paintSet(cs.filter)
      || /transform|perspective|filter/.test(String(cs.willChange || ''));
  }
  function paintSkewed(cs){
    if (paintSet(cs.rotate) || (paintSet(cs.scale) && /-/.test(String(cs.scale)))) return true;
    var t = String(cs.transform || 'none');
    if (t === 'none') return false;
    var m = /^matrix\(([^)]*)\)$/.exec(t);
    if (!m) return true;
    var p = m[1].split(',').map(parseFloat);
    return p.length !== 6 || !p.every(isFinite) || p[1] !== 0 || p[2] !== 0 || p[0] < 0 || p[3] < 0;
  }
  function paintClipBox(n){
    if (typeof n.offsetWidth !== 'number' || typeof n.offsetHeight !== 'number') return null;
    var b = n.getBoundingClientRect();
    var sx = n.offsetWidth ? b.width / n.offsetWidth : 0, sy = n.offsetHeight ? b.height / n.offsetHeight : 0;
    return {x: b.left + n.clientLeft * sx, y: b.top + n.clientTop * sy, w: n.clientWidth * sx, h: n.clientHeight * sy};
  }
  function paintClips(n, cs){
    if (n === document.documentElement) return false;
    if (n === document.body && getComputedStyle(document.documentElement).overflowX === 'visible') return false;
    return cs.overflowX !== 'visible' || cs.overflowY !== 'visible';
  }
  function paintReadOf(v){
    var rect = paintBoxOf(v.getBoundingClientRect());
    var pv = {
      id: v.__obedProbeId != null ? v.__obedProbeId : null,
      elId: v.__obedElId != null ? v.__obedElId : null,
      instance: v.__obedInstance != null ? String(v.__obedInstance) : null,
      src: String(v.currentSrc || v.src || '').split('/').pop(),
      connected: v.isConnected === true, facade: !!v.__obedFacadeFor, suppressed: !!v.__obedSuppressed34,
      readyState: v.readyState, seeking: !!v.seeking, videoWidth: v.videoWidth, videoHeight: v.videoHeight,
      currentTime: v.currentTime, paused: v.paused, ended: v.ended,
      checkVisibility: null, visibility: null, displayNone: null, opacity: null, hiding: null, effects: null, transform: null,
      rect: rect, visibleRect: null, clippedBy: null, parent: labelOf(v.parentNode), layer: layerOf(v)
    };
    if (!pv.connected) return pv;
    if (typeof v.checkVisibility === 'function') {
      pv.checkVisibility = v.checkVisibility({checkOpacity: true, checkVisibilityCSS: true, contentVisibilityAuto: true,
                                              opacityProperty: true, visibilityProperty: true});
    }
    var own = getComputedStyle(v);
    pv.visibility = own.visibility;
    var visible = paintMeet(rect, {x: 0, y: 0, w: window.innerWidth, h: window.innerHeight});
    if (!visible || visible.w < rect.w || visible.h < rect.h) pv.clippedBy = 'viewport';
    var product = 1, reached = false, mode = own.position;
    for (var n = v; n; n = flatParent(n)) {
      if (n.nodeType !== 1) break;
      var cs = n === v ? own : getComputedStyle(n);
      var op = parseFloat(cs.opacity);
      product = isFinite(op) ? product * op : NaN;
      var none = cs.display === 'none';
      if (none && pv.displayNone === null) pv.displayNone = labelOf(n);
      if (pv.hiding === null && (none || op <= 0.02)) {
        pv.hiding = {node: labelOf(n), prop: none ? 'display' : 'opacity', value: none ? 'none' : op};
      }
      var fx = paintEffectOf(cs);
      if (fx && pv.effects === null) pv.effects = labelOf(n) + ':' + fx;
      if (pv.transform === null && paintSkewed(cs)) pv.transform = labelOf(n);
      if (n !== v) {
        var contains = mode === 'fixed' ? paintMakesBlock(cs)
          : mode === 'absolute' ? (cs.position !== 'static' || paintMakesBlock(cs)) : true;
        if (contains) {
          if (visible && paintClips(n, cs)) {
            var clipBox = paintClipBox(n);
            if (!clipBox && pv.transform === null) pv.transform = labelOf(n);
            var next = clipBox ? paintMeet(visible, clipBox) : null;
            if ((!next || next.w < visible.w || next.h < visible.h) && pv.clippedBy === null) pv.clippedBy = labelOf(n);
            visible = next;
          }
          mode = cs.position;
        }
      }
      if (n === document.documentElement) { reached = true; break; }
    }
    pv.opacity = reached && isFinite(product) ? product : null;
    pv.visibleRect = visible;
    return pv;
  }
"""

PREPAINT_FN_JS = r"""
  function installPrepaint(probe){
    if (typeof ResizeObserver !== 'function') throw new Error('paint instrument: ResizeObserver is unavailable');
    if (typeof WeakRef !== 'function') throw new Error('paint instrument: WeakRef is unavailable');
    if (typeof Element.prototype.checkVisibility !== 'function') throw new Error('paint instrument: checkVisibility is unavailable');
    var meta = probe.meta;
    if (!Array.isArray(meta.errors)) meta.errors = [];
    ['prepaint', 'ppMismatch', 'ppDuplicate'].forEach(function(k){ if (typeof meta[k] !== 'number') meta[k] = 0; });
    if (!meta.readCostMs) meta.readCostMs = {sum: 0, max: 0};
    var refs = [], seen = new WeakSet(), currentSeq = null, currentTs = null, wide = false, active = false;
    meta.prepaintObserver = {installed: false, active: false, disconnected: false, callbacks: 0, ignored: 0, failures: 0};
    function fail(where, e){ if (meta.errors.length < 50) meta.errors.push(where + ': ' + String(e && e.message || e)); }
    function track(v){ if (!seen.has(v)) { seen.add(v); refs.push(new WeakRef(v)); } }
    var host = document.createElement('div');
    host.style.cssText = 'position:fixed;left:-16px;top:-16px;width:8px;height:8px;overflow:hidden;opacity:0;pointer-events:none;';
    var sentinel = document.createElement('div');
    sentinel.style.cssText = 'display:block;width:1px;height:1px;';
    host.attachShadow({mode: 'closed'}).appendChild(sentinel);
    document.documentElement.appendChild(host);
    var observer = new ResizeObserver(function(){
      var t = performance.now();
      if (window.__obedCost && typeof window.__obedCost.enter === 'function') window.__obedCost.enter('paint.prePaint');
      meta.prepaintObserver.callbacks++;
      try {
        if (!active || currentSeq === null) { meta.prepaintObserver.ignored++; return; }
        var row = probe.samples.length ? probe.samples[probe.samples.length - 1] : null;
        if (!row || row.seq !== currentSeq) { meta.ppMismatch++; return; }
        if (row.pp) { meta.ppDuplicate++; return; }
        document.querySelectorAll('video').forEach(track);
        var videos = [];
        refs = refs.filter(function(ref){
          var v = ref.deref();
          if (!v) return false;
          videos.push(paintReadOf(v));
          return true;
        });
        row.pp = {seq: currentSeq, ts: currentTs, t: t, videos: videos, stageMap: stageMapOf(), stageBox: stageBox(), cover: coverUp()};
        meta.prepaint++;
      } catch (e) {
        meta.prepaintObserver.failures++;
        fail('prepaint', e);
      } finally {
        var cost = performance.now() - t;
        meta.readCostMs.sum += cost;
        if (cost > meta.readCostMs.max) meta.readCostMs.max = cost;
        if (window.__obedCost && typeof window.__obedCost.leave === 'function') window.__obedCost.leave('paint.prePaint');
      }
    });
    observer.observe(sentinel);
    active = true;
    meta.prepaintObserver.installed = true;
    meta.prepaintObserver.active = true;
    if (window.__obedCost && typeof window.__obedCost.install === 'function') window.__obedCost.install('paint.prePaint');
    function toggle(seq, ts){
      if (!active) return;
      currentSeq = seq;
      currentTs = ts;
      wide = !wide;
      sentinel.style.width = wide ? '2px' : '1px';
    }
    function start(){
      if (active) return true;
      observer.observe(sentinel);
      active = true;
      meta.prepaintObserver.active = true;
      meta.prepaintObserver.disconnected = false;
      return true;
    }
    function stop(){
      if (!active) return true;
      active = false;
      observer.disconnect();
      meta.prepaintObserver.active = false;
      meta.prepaintObserver.disconnected = true;
      return true;
    }
    return {toggle: toggle, track: track, start: start, stop: stop};
  }
"""

_PAINT_CONTROL_JS = r"""
(function(cfg){
  if (window.__obedPaintControl__) return true;
  var ATTR = 'data-obed-paint-control';
  var PLACEMENT = /^(stash|remount|rehome|dom-swap|retire|bridge)/;
  var rec = {control: cfg, fired: false, triggerSeq: null, onSeq: null, offSeq: null, hiddenTicks: null, hiddenSeqs: [],
             target: null, aborted: null, events: [], errors: [], lateSeqs: []};
  var sheet = new CSSStyleSheet();
  sheet.replaceSync('[' + ATTR + '="ancestor-opacity"]{opacity:0!important}'
    + '[' + ATTR + '="ancestor-half"]{opacity:.5!important}'
    + '[' + ATTR + '="ancestor-display"]{display:none!important}'
    + '[' + ATTR + '="element-visibility"]{visibility:hidden!important}');
  document.adoptedStyleSheets = document.adoptedStyleSheets.concat([sheet]);
  var late = cfg.timing === 'late';
  var seqNow = null, cursor = 0, onAt = null, done = false, hidden = false;
  var video = null, node = null, videoParent = null, nodeParent = null, parentBox = null, onT = null;
  function fail(where, e){ if (rec.errors.length < 50) rec.errors.push(where + ': ' + String(e && e.message || e)); }
  function hashNum(h){ var m = /^#?(\d+)/.exec(String(h || '')); return m ? parseInt(m[1], 10) : null; }
  function assetNameOf(src){
    var name = String(src || '').split('?')[0].split('/').pop();
    var m = /^(.+)-\d+\.\d+-\d+\.\d+\.[A-Za-z0-9]+$/.exec(name);
    return (m ? m[1] : name).toLowerCase();
  }
  function label(n){ return n ? String(n.tagName || '').toLowerCase() + (n.id ? '#' + n.id : '') : null; }
  function boxOf(n){ var r = n.getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height}; }
  function videos(){ return Array.prototype.slice.call(document.querySelectorAll('video')).filter(function(v){ return !v.__obedFacadeFor; }); }
  function byElId(id){ return videos().filter(function(v){ return v.__obedElId === id; })[0] || null; }
  function abort(reason){
    rec.aborted = reason;
    if (hidden) { node.removeAttribute(ATTR); hidden = false; rec.offSeq = seqNow; finish(); }
    done = true;
  }
  function placementEvents(t0, t1){
    var core = window.__OBED_P2_PRESERVE__;
    ((core && core.events) || []).forEach(function(e){
      if (!e || !(e.t >= t0 && e.t <= t1) || !PLACEMENT.test(String(e.kind))) return;
      var d = e.detail || {};
      var mine = d.elId === rec.target.elId || (Array.isArray(d.elIds) && d.elIds.indexOf(rec.target.elId) >= 0);
      if (mine) rec.events.push({kind: String(e.kind), t: e.t});
    });
  }
  function finish(){
    rec.hiddenTicks = rec.offSeq - rec.onSeq;
    rec.hiddenSeqs = [];
    for (var s = rec.onSeq; s < rec.offSeq; s++) rec.hiddenSeqs.push(s);
    placementEvents(onT, performance.now());
    done = true;
  }
  function apply(on){
    if (done) return;
    if (on) {
      videoParent = video.parentNode;
      nodeParent = node.parentNode;
      parentBox = nodeParent && nodeParent.getBoundingClientRect ? boxOf(nodeParent) : null;
      onT = performance.now();
      node.setAttribute(ATTR, cfg.variant);
      hidden = true;
      rec.fired = true;
      rec.onSeq = seqNow;
    } else {
      node.removeAttribute(ATTR);
      hidden = false;
      rec.offSeq = seqNow;
      finish();
    }
  }
  function schedule(on, expected){
    queueMicrotask(function(){
      requestAnimationFrame(function(){
        try {
          rec.lateSeqs.push(seqNow);
          if (seqNow !== expected) fail('late', 'late writer ran at seq ' + seqNow + ', expected ' + expected);
          apply(on);
        } catch (e) { fail('late', e); }
      });
    });
  }
  function act(on, k){ if (late) schedule(on, k); else apply(on); }
  function trigger(){
    var core = window.__OBED_P2_PRESERVE__;
    if (cfg.phase === 'settled') {
      var snap = window.__obedLive ? window.__obedLive.snapshot() : null;
      if (!snap || snap.busy !== false || hashNum(location.hash) !== cfg.atScene - 1) return null;
      var plan = window.__OBED_CONTINUITY__ || {};
      var b = ((plan.boundaries) || []).filter(function(x){ return x && x.action === 'bridge' && x.atScene === cfg.atScene; })[0];
      var movie = b && plan.movies && plan.movies[b.movieKey];
      if (!movie) { abort('no bridge boundary at scene ' + cfg.atScene); return null; }
      var names = (movie.assetKeys || []).map(assetNameOf);
      var decoded = videos().filter(function(v){
        return v.isConnected && v.readyState >= 2 && v.videoWidth > 0 && names.indexOf(assetNameOf(v.currentSrc || v.src)) >= 0;
      });
      if (decoded.length > 1) { abort(decoded.length + ' decoded elements of the asset on the settled source scene'); return null; }
      return decoded[0] || null;
    }
    var evs = (core && core.events) || [];
    if (cursor > evs.length) cursor = 0;
    for (; cursor < evs.length; cursor++) {
      var e = evs[cursor], d = (e && e.detail) || {};
      var hit = cfg.phase === 'pin'
        ? e && e.kind === 'pin-hold-start' && d.atScene === cfg.atScene
        : e && e.kind === 'bridge-motion-start' && hashNum(d.sceneHash) === cfg.atScene - 1;
      if (!hit) continue;
      cursor++;
      var v = byElId(d.elId);
      if (!v) abort('decoder ' + d.elId + ' not found');
      return v;
    }
    return null;
  }
  function targetOf(v){
    if (cfg.variant === 'element-visibility') return v;
    var n = v;
    for (var i = 0; i < cfg.depth; i++) {
      n = n.parentElement;
      if (!n || n === document.documentElement) return null;
    }
    return n;
  }
  function moved(a, b){
    if (!a || !b) return a !== b;
    return Math.abs(a.x - b.x) > 0.5 || Math.abs(a.y - b.y) > 0.5 || Math.abs(a.w - b.w) > 0.5 || Math.abs(a.h - b.h) > 0.5;
  }
  function tick(seq, ts){
    seqNow = seq;
    if (done) return;
    try {
      if (onAt === null) {
        var v = trigger();
        if (done || !v) return;
        video = v;
        node = targetOf(v);
        rec.triggerSeq = seq;
        rec.target = {elId: v.__obedElId != null ? v.__obedElId : null, node: label(node)};
        if (!node) { abort('depth ' + cfg.depth + ' reaches the document element'); return; }
        onAt = seq + cfg.delayTicks;
      }
      if (hidden) {
        if (video.parentNode !== videoParent) { abort('decoder parent changed'); return; }
        if (node.parentNode !== nodeParent) { abort('target parent changed'); return; }
        if (parentBox && moved(boxOf(nodeParent), parentBox)) { abort('target parent rect changed'); return; }
      }
      if (cfg.n === 0) {
        if (seq === onAt) { rec.fired = true; rec.onSeq = rec.offSeq = seq; onT = performance.now(); finish(); }
        return;
      }
      var k = late ? seq + 1 : seq;
      if (k === onAt) act(true, k);
      else if (k === onAt + cfg.n) act(false, k);
    } catch (e) { fail('tick', e); }
  }
  window.__obedPaintControl__ = {record: rec, tick: tick};
  return true;
})(__CFG__);
"""


def paint_control_js(
    n: int, variant: str, phase: str, at_scene: int, *, timing: str = "early", depth: int = 1, delay_ticks: int = 10
) -> str:
    """The positive-control injector (plan §4), evaluated after `SAMPLER_JS`; the sampler's `frame(ts)` calls
    `window.__obedPaintControl__.tick(seq, ts)` before its own tick, and the result is `.record`."""
    if variant not in PAINT_CONTROL_VARIANTS:
        raise ValueError(f"unknown paint-control variant {variant!r}; expected one of {PAINT_CONTROL_VARIANTS}")
    if phase not in PAINT_CONTROL_PHASES:
        raise ValueError(f"unknown paint-control phase {phase!r}; expected one of {PAINT_CONTROL_PHASES}")
    if timing not in PAINT_CONTROL_TIMINGS:
        raise ValueError(f"unknown paint-control timing {timing!r}; expected one of {PAINT_CONTROL_TIMINGS}")
    for name, value, low in (("n", n, 0), ("at_scene", at_scene, 2), ("depth", depth, 1), ("delay_ticks", delay_ticks, 1)):
        if isinstance(value, bool) or not isinstance(value, int) or value < low:
            raise ValueError(f"paint-control {name} must be an int >= {low}, got {value!r}")
    if variant == "ancestor-display" and phase != "settled":
        raise ValueError("ancestor-display is only valid at the settled phase")
    if phase == "settled" and variant != "element-visibility" and depth < 2:
        raise ValueError("the settled phase requires depth >= 2")
    cfg = {"n": n, "variant": variant, "phase": phase, "atScene": at_scene, "timing": timing, "depth": depth,
           "delayTicks": delay_ticks}
    return _PAINT_CONTROL_JS.replace("__CFG__", json.dumps(cfg, sort_keys=True))


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _box(value: Any) -> dict[str, float] | None:
    if isinstance(value, dict) and all(_num(value.get(k)) for k in ("x", "y", "w", "h")):
        return value
    return None


def _meet(a: dict[str, float] | None, b: dict[str, float] | None) -> dict[str, float] | None:
    if a is None or b is None:
        return None
    x, y = max(a["x"], b["x"]), max(a["y"], b["y"])
    right, bottom = min(a["x"] + a["w"], b["x"] + b["w"]), min(a["y"] + a["h"], b["y"] + b["h"])
    return {"x": x, "y": y, "w": right - x, "h": bottom - y} if right > x and bottom > y else None


def _area(rect: dict[str, float] | None) -> float:
    return rect["w"] * rect["h"] if rect else 0.0


def _iou(a: dict[str, float] | None, b: dict[str, float] | None) -> float:
    overlap = _area(_meet(a, b))
    union = _area(a) + _area(b) - overlap
    return overlap / union if overlap and union > 0 else 0.0


def _rects_match(a: dict[str, float] | None, b: dict[str, float] | None, tolerance: float) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return all(abs(a[k] - b[k]) <= tolerance for k in ("x", "y", "w", "h"))


def _id_ok(value: Any) -> bool:
    return value is not None and not isinstance(value, bool) and isinstance(value, (int, str))


def _bool_ok(value: Any) -> bool:
    return isinstance(value, bool)


def _str_or_null(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _int_ok(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _ints_ok(value: Any) -> bool:
    return isinstance(value, list) and all(_int_ok(item) for item in value)


def is_box(value: Any) -> bool:
    return _box(value) is not None


def schema_problem(value: Any, fields: Mapping[str, Callable[[Any], bool]]) -> str | None:
    """Why `value` cannot be read against `fields`: not an object, or a field missing or ill-typed (an explicit null
    is a reading only where the field's check allows it), else None. Every schema in this instrument uses it."""
    if not isinstance(value, dict):
        return "not an object"
    for key, valid in fields.items():
        if key not in value:
            return f"{key} missing"
        if not valid(value[key]):
            return f"{key} ill-typed"
    return None


PV_FIELDS: dict[str, Callable[[Any], bool]] = {
    "id": _id_ok,
    "src": lambda value: isinstance(value, str),
    "connected": _bool_ok,
    "facade": _bool_ok,
    "suppressed": _bool_ok,
    "seeking": _bool_ok,
    "readyState": _num,
    "videoWidth": _num,
    "videoHeight": _num,
    "opacity": lambda value: value is None or _num(value),
    "checkVisibility": lambda value: value is None or isinstance(value, bool),
    "visibility": _str_or_null,
    "displayNone": _str_or_null,
    "effects": _str_or_null,
    "transform": _str_or_null,
    "rect": lambda value: _box(value) is not None,
    "visibleRect": lambda value: value is None or _box(value) is not None,
}


PP_FIELDS: dict[str, Callable[[Any], bool]] = {
    "seq": _int_ok,
    "ts": _num,
    "t": _num,
    "cover": _bool_ok,
    "videos": lambda value: isinstance(value, list),
    "stageBox": lambda value: value is None or is_box(value),
}
CONTROL_SPEC_FIELDS: dict[str, Callable[[Any], bool]] = {
    "n": _int_ok,
    "variant": lambda value: value in PAINT_CONTROL_VARIANTS,
    "phase": lambda value: value in PAINT_CONTROL_PHASES,
    "timing": lambda value: value in PAINT_CONTROL_TIMINGS,
    "atScene": _int_ok,
    "depth": _int_ok,
    "delayTicks": _int_ok,
}
CONTROL_RECORD_FIELDS: dict[str, Callable[[Any], bool]] = {
    "control": lambda value: schema_problem(value, CONTROL_SPEC_FIELDS) is None,
    "fired": _bool_ok,
    "aborted": _str_or_null,
    "events": lambda value: isinstance(value, list) and all(isinstance(item, dict) for item in value),
    "errors": lambda value: isinstance(value, list),
    "triggerSeq": lambda value: value is None or _int_ok(value),
    "onSeq": lambda value: value is None or _int_ok(value),
    "offSeq": lambda value: value is None or _int_ok(value),
    "hiddenTicks": lambda value: value is None or _int_ok(value),
    "hiddenSeqs": _ints_ok,
    "lateSeqs": lambda value: isinstance(value, list) and all(item is None or _int_ok(item) for item in value),
    "target": lambda value: value is None or isinstance(value, dict),
}
PAINT_SCORE_FIELDS: dict[str, Callable[[Any], bool]] = {
    "status": lambda value: value in ("ok", "fail", "inconclusive"),
    "frames": _int_ok,
    "coverage": lambda value: isinstance(value, dict),
    "unobserved": lambda value: isinstance(value, list),
    "unreadable": lambda value: isinstance(value, list),
    "unpaintedSeqs": _ints_ok,
    "partialSeqs": _ints_ok,
    "unpaintedFrames": _int_ok,
    "partialFrames": _int_ok,
    "doubleFrames": _int_ok,
    "substituteFrames": _int_ok,
}


def pv_schema_problem(pv: Any) -> str | None:
    """`schema_problem` against `PV_FIELDS` (e.g. `visibleRect: null` is the offscreen reading, a missing one is not)."""
    return schema_problem(pv, PV_FIELDS)


def pp_schema_problem(pp: Any) -> str | None:
    """`schema_problem` of a frame's pre-paint read against `PP_FIELDS` (`cover` a present bool)."""
    return schema_problem(pp, PP_FIELDS)


def control_record_problem(record: Any) -> str | None:
    """Why an injector record cannot vouch for a control: `CONTROL_RECORD_FIELDS`, and once fired without an abort
    (itself inconclusive), integer `onSeq`/`offSeq`/`hiddenTicks` with `offSeq == onSeq + control.n` (never an
    early off), else None."""
    problem = schema_problem(record, CONTROL_RECORD_FIELDS)
    if problem or not record["fired"] or record["aborted"]:
        return problem
    on, off, ticks = record["onSeq"], record["offSeq"], record["hiddenTicks"]
    if not (_int_ok(on) and _int_ok(off) and _int_ok(ticks)):
        return "fired without integer onSeq/offSeq/hiddenTicks"
    if off != on + record["control"]["n"]:
        return f"offSeq {off} is not onSeq {on} + n {record['control']['n']}"
    return None


def painted_state(
    pv: dict[str, Any] | None,
    *,
    cover: bool = False,
    expected: dict[str, float] | None = None,
    stage: dict[str, float] | None = None,
    rect_tolerance: float | None = None,
) -> tuple[str, str | None]:
    """Plan §2.3, first matching rule wins; `cover` is the frame's `pp.cover`. Rule 13 (clipped) applies only when
    `rect_tolerance` is given: `visibleRect ∩ stage` against `expected` (= slot ∩ stage). A held decoder painting
    outside the stage is `outsideStagePx` in `score_paint`, never partial. A read failing `pv_schema_problem` is
    unreadable before any rule."""
    if pv is None:
        return UNPAINTED, "absent"
    problem = pv_schema_problem(pv)
    if problem:
        return UNREADABLE, f"schema: {problem}"
    if pv.get("connected") is not True:
        return UNPAINTED, "detached"
    if pv.get("facade"):
        return NOT_PAINTER, "facade"
    if pv.get("suppressed"):
        return UNPAINTED, "suppressed"
    ready, width, height = pv.get("readyState"), pv.get("videoWidth"), pv.get("videoHeight")
    if not (_num(ready) and ready >= 2 and _num(width) and width > 0 and _num(height) and height > 0):
        return UNPAINTED, "seeking" if pv.get("seeking") else "not-decoded"
    opacity, visible = pv.get("opacity"), pv.get("checkVisibility")
    if not _num(opacity):
        return UNREADABLE, "opacity"
    if not isinstance(visible, bool):
        return UNREADABLE, "checkVisibility"
    if not isinstance(pv.get("visibility"), str):
        return UNREADABLE, "visibility"
    if pv.get("effects"):
        return UNREADABLE, "effects"
    if pv.get("transform"):
        return UNREADABLE, "transform"
    if cover:
        return UNREADABLE, "cover"
    if pv.get("displayNone"):
        return UNPAINTED, "display"
    if pv.get("visibility") != "visible":
        return UNPAINTED, "visibility"
    if not visible:
        return UNPAINTED, "checkVisibility"
    if opacity <= PAINT_OPACITY_FLOOR:
        return UNPAINTED, "opacity"
    rect = _box(pv.get("visibleRect"))
    if rect is None or rect["w"] <= 1 or rect["h"] <= 1:
        return UNPAINTED, "offscreen"
    if opacity < PAINT_OPAQUE_MIN:
        return PARTIAL, "opacity"
    if rect_tolerance is not None and not _rects_match(_meet(rect, stage), expected, rect_tolerance):
        return PARTIAL, "clipped"
    return PAINTED, None


def _period(rows: Sequence[dict[str, Any]]) -> float | None:
    ts = [r["ts"] for r in rows if _num(r.get("ts"))]
    deltas = [b - a for a, b in zip(ts, ts[1:])]
    return statistics.median(deltas) if deltas else None


def local_period(before: Sequence[float], after: Sequence[float], fallback: float) -> float:
    """The rAF period one delta is judged at when nothing inside it is observed: the slower of the medians of the up to
    `LOCAL_CADENCE_DELTAS` deltas either side (Chrome drops to 30 Hz while two videos play); else `fallback`."""
    return max((float(statistics.median(s)) for s in (before, after) if s), default=fallback)


def _local_periods(deltas: list[float], fallback: float) -> list[float]:
    k = LOCAL_CADENCE_DELTAS
    return [local_period(deltas[max(0, i - k):i], deltas[i + 1:i + 1 + k], fallback) for i in range(len(deltas))]


def frame_coverage(rows: list[dict[str, Any]], *, max_gap_frames: int, min_fps: float) -> dict[str, Any]:
    """Carry-cover's rule on rAF timestamps: any delta over `(max_gap_frames + 0.5) × local period`, a cadence
    under `min_fps`, or a missing sampler row (a seq gap) fails coverage. The local period is `local_period` with the
    window's median as fallback."""
    reasons: list[str] = []
    if any(not _num(r.get("ts")) or not isinstance(r.get("seq"), int) for r in rows):
        return {"ok": False, "reasons": ["rows without seq/ts"], "frames": len(rows)}
    if len(rows) < 2:
        return {"ok": False, "reasons": [f"{len(rows)} frames"], "frames": len(rows)}
    ts = [r["ts"] for r in rows]
    deltas = [b - a for a, b in zip(ts, ts[1:])]
    period = statistics.median(deltas)
    seq_gaps = sum(b["seq"] - a["seq"] - 1 for a, b in zip(rows, rows[1:]) if b["seq"] != a["seq"] + 1)
    out: dict[str, Any] = {"frames": len(rows), "periodMs": round(period, 3), "maxGapMs": round(max(deltas), 3),
                           "seqGaps": seq_gaps}
    if period <= 0:
        reasons.append(f"non-increasing rAF timestamps (median delta {period:g} ms)")
    else:
        gap, local = max(zip(deltas, _local_periods(deltas, period)), key=lambda g: g[0] / g[1] if g[1] > 0 else math.inf)
        allowed = (max_gap_frames + 0.5) * local
        missed = [d for d in deltas if d > 1.5 * period]
        out.update(fps=round(1000.0 / period, 2),
                   worstGap={"ms": round(gap, 3), "periodMs": round(local, 3), "allowedMs": round(allowed, 3)},
                   missedFrames=sum(max(0, round(d / period) - 1) for d in missed),
                   missedMs=round(sum(d - period for d in missed), 3))
        if period > 1000.0 / min_fps:
            reasons.append(f"cadence {period:.1f} ms is slower than {min_fps:g} fps")
        if gap > allowed:
            reasons.append(f"frame gap {gap:.1f} ms exceeds {allowed:.1f} ms ({local:.1f} ms local period)")
    if any(d <= 0 for d in deltas) and period > 0:
        reasons.append("non-increasing rAF timestamps")
    if seq_gaps:
        reasons.append(f"{seq_gaps} sampler rows missing (seq gaps)")
    out.update(ok=not reasons, reasons=reasons)
    return out


def _pp_problem(row: dict[str, Any]) -> str | None:
    pp = row.get("pp")
    if not isinstance(pp, dict):
        return "no pre-paint read"
    problem = pp_schema_problem(pp)
    if problem:
        return f"pre-paint read {problem}"
    if pp["seq"] != row.get("seq") or pp["ts"] != row.get("ts"):
        return "pre-paint read of another frame"
    if not (_num(row.get("t")) and pp["t"] >= row["t"]):
        return "pre-paint read before the rAF read"
    return None


def _runs(frames: list[dict[str, Any]], period: float | None) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for f in frames:
        if runs and f["seq"] == runs[-1]["endSeq"] + 1:
            run = runs[-1]
            run.update(endSeq=f["seq"], frames=run["frames"] + 1, t1=f["t"], ts1=f["ts"])
        else:
            run = {"startSeq": f["seq"], "endSeq": f["seq"], "frames": 1, "t0": f["t"], "t1": f["t"],
                   "ts0": f["ts"], "ts1": f["ts"], "kinds": Counter(), "reasons": Counter(), "hiding": f.get("hiding")}
            runs.append(run)
        run["kinds"][f["kind"]] += 1
        run["reasons"][f["reason"] or f["kind"]] += 1
    for run in runs:
        run["ms"] = round(run.pop("ts1") - run.pop("ts0") + (period or 0.0), 3)
        run["kinds"], run["reasons"] = dict(run["kinds"]), dict(run["reasons"])
    return runs


def score_paint(
    rows: list[dict[str, Any]],
    element_id: int,
    asset: str,
    *,
    start: float,
    end: float,
    slot_of: Callable[[dict[str, Any]], dict[str, float] | None],
    stage_box_of: Callable[[dict[str, Any]], dict[str, float] | None],
    rect_tolerance: float,
    iou_min: float,
    max_gap_frames: int,
    min_fps: float,
    unreadable_of: Callable[[dict[str, Any]], str | None] | None = None,
    wrap_times: Sequence[float] = (),
) -> dict[str, Any]:
    """Plan §2.4 over the rows with `start <= t <= end`. `slot_of`/`stage_box_of` and every `pv.rect`/`visibleRect`
    must share one coordinate space. Readability comes before any classification: a frame is unreadable when the
    carried decoder, or any decoder of the asset whose rect meets the slot (any, without a slot), reads unreadable.
    An unobserved or unreadable frame, failed coverage or no rows is inconclusive whatever else the window shows;
    on complete evidence any violating frame (no slot included) fails. `unreadable_of(row)` names a frame whose
    context the caller cannot read (e.g. its phase), which is unreadable before any slot is chosen. Identity comes
    before source: `element_id` and every id whose src is exactly the asset (canonical name) on any of `rows` is a
    decoder of the asset. A frame where one names no source, or where two pre-paint reads share an id, is unreadable;
    so is one where a painter that names no source at all (painted, partial or unreadable) meets the slot (any, without
    a slot). A read naming another asset is never the movie: on a decoder of the asset that paints where it meets the
    slot it is a substitute (red), and unreadable there when its paint is. The browser's loop seek is excused (owner
    decision 14, pixel-checked: the last frame stays painted): on a classified wrap sample (`wrap_times`) whose sampler
    read has the carried decoder looping, its `seeking` read waives only the decode-readiness rule, and every other
    rule still judges the frame; a frame that then paints is `seekExcused`."""
    window_rows = sorted((r for r in rows if _num(r.get("t")) and start <= r["t"] <= end), key=lambda r: r.get("seq") or 0)
    coverage = frame_coverage(window_rows, max_gap_frames=max_gap_frames, min_fps=min_fps)
    period = coverage.get("periodMs")
    asset_name = canonical_asset_name(asset)
    movie = {element_id} | {
        pv["id"] for r in rows if isinstance(r, dict) and isinstance(r.get("pp"), dict) and isinstance(r["pp"].get("videos"), list)
        for pv in r["pp"]["videos"] if pv_schema_problem(pv) is None and canonical_asset_name(pv["src"]) == asset_name
    }
    violations: list[dict[str, Any]] = []
    seek_excused: list[dict[str, Any]] = []
    unobserved: list[dict[str, Any]] = []
    unreadable: list[dict[str, Any]] = []
    min_opacity: float | None = None
    outside = 0.0
    for row in window_rows:
        problem = _pp_problem(row)
        if problem:
            unobserved.append({"seq": row.get("seq"), "t": row.get("t"), "problem": problem})
            continue
        frame = {"seq": row["seq"], "t": row["t"], "ts": row["ts"]}
        context = unreadable_of(row) if unreadable_of is not None else None
        if context:
            unreadable.append(dict(frame, reason=context))
            continue
        slot, stage = _box(slot_of(row)), _box(stage_box_of(row))
        loop_seek = row["t"] in wrap_times and any(
            isinstance(v, dict) and v.get("id") == element_id and v.get("loop") is True for v in row.get("videos") or []
        )
        waived = False
        if stage is None:
            unreadable.append(dict(frame, reason="stage box"))
            continue
        expected = _meet(slot, stage)
        cover = row["pp"]["cover"]
        carried_state: tuple[str, str | None] = (UNPAINTED, "absent")
        carried_pv: dict[str, Any] | None = None
        at_slot: list[dict[str, Any]] = []
        foreign: list[dict[str, Any]] = []
        blind = False
        ids = [pv["id"] for pv in row["pp"]["videos"] if pv_schema_problem(pv) is None]
        if len(ids) != len(set(ids)):
            unreadable.append(dict(frame, reason="two pre-paint reads share an id"))
            continue
        for pv in row["pp"]["videos"]:
            problem = pv_schema_problem(pv)
            if problem:
                blind = True
                unreadable.append(dict(frame, reason=f"schema: {problem}", id=pv.get("id") if isinstance(pv, dict) else None))
                continue
            name = canonical_asset_name(pv["src"])
            if name and name != asset_name and pv["id"] not in movie:
                continue
            if not name and pv["id"] in movie:
                blind = True
                unreadable.append(dict(frame, reason="a decoder of the asset names no source", id=pv["id"]))
                continue
            state = painted_state(pv, cover=cover, expected=expected, stage=stage,
                                  rect_tolerance=rect_tolerance if slot is not None else None)
            if loop_seek and pv["id"] == element_id and state == (UNPAINTED, "seeking"):
                waived = True
                state = painted_state({**pv, "readyState": 2}, cover=cover, expected=expected, stage=stage,
                                      rect_tolerance=rect_tolerance if slot is not None else None)
            if not name:
                rect = _box(pv.get("rect"))
                if state[0] in (PAINTED, PARTIAL, UNREADABLE) and (slot is None or rect is None or _meet(rect, slot) is not None):
                    blind = True
                    unreadable.append(dict(frame, reason="a painter that names no source meets the slot", id=pv["id"]))
                continue
            if name != asset_name:
                rect = _box(pv.get("rect"))
                if slot is None or rect is None or _meet(rect, slot) is not None:
                    if state[0] == UNREADABLE:
                        blind = True
                        unreadable.append(dict(frame, reason=state[1], id=pv["id"]))
                    elif state[0] in (PAINTED, PARTIAL):
                        foreign.append(pv)
                continue
            mine = pv.get("id") == element_id
            near = _iou(_box(pv.get("rect")), slot) >= iou_min
            if mine:
                carried_state, carried_pv = state, pv
                if _num(pv.get("opacity")):
                    min_opacity = pv["opacity"] if min_opacity is None else min(min_opacity, pv["opacity"])
                if state[0] in (PAINTED, PARTIAL):
                    outside = max(outside, _area(_box(pv.get("visibleRect"))) - _area(_meet(_box(pv.get("visibleRect")), stage)))
            rect = _box(pv.get("rect"))
            if state[0] == UNREADABLE and (mine or slot is None or rect is None or _meet(rect, slot) is not None):
                blind = True
                unreadable.append(dict(frame, reason=state[1], id=pv.get("id")))
            if state[0] in (PAINTED, PARTIAL) and near:
                at_slot.append(pv)
        if blind:
            continue
        if slot is None:
            violations.append(dict(frame, kind=UNPAINTED, reason="no-slot"))
            continue
        ids = [pv.get("id") for pv in at_slot]
        if foreign:
            kind, reason = "substitute", f"id {foreign[0]['id']} of the asset paints another asset"
        elif len(at_slot) >= 2:
            kind, reason = "double", f"ids {ids}"
        elif ids == [element_id]:
            if carried_state[0] == PAINTED:
                if waived:
                    seek_excused.append(frame)
                continue
            kind, reason = PARTIAL, carried_state[1]
        elif at_slot:
            kind, reason = "substitute", f"id {ids[0]}"
        else:
            kind = UNPAINTED
            reason = carried_state[1] if carried_state[0] != PAINTED and carried_state[0] != PARTIAL else "off-slot"
        violations.append(dict(frame, kind=kind, reason=reason,
                               hiding=(carried_pv or {}).get("hiding"), parent=(carried_pv or {}).get("parent"),
                               layer=(carried_pv or {}).get("layer")))
    kinds = Counter(v["kind"] for v in violations)
    runs = _runs(violations, period)
    deltas = {r["seq"]: (b["ts"] - r["ts"]) for r, b in zip(window_rows, window_rows[1:]) if _num(r.get("ts")) and _num(b.get("ts"))}
    unpainted = [v for v in violations if v["kind"] == UNPAINTED]
    reasons: list[str] = []
    for kind, count in sorted(kinds.items()):
        where = Counter((v.get("hiding") or {}).get("node") or v["reason"] for v in violations if v["kind"] == kind)
        reasons.append(f"{count} {kind} frames ({', '.join(f'{k}: {n}' for k, n in where.most_common(3))})")
    if not window_rows:
        reasons.append("no sampler rows in the window")
    if unobserved:
        reasons.append(f"{len(unobserved)} frames unobserved before paint")
    if unreadable:
        reasons.append(f"{len(unreadable)} frames unreadable")
    if window_rows and not coverage["ok"]:
        reasons.append("coverage: " + "; ".join(coverage["reasons"]))
    status = "inconclusive" if _evidence_gaps(len(window_rows), coverage, unobserved, unreadable) else (
        "fail" if violations else "ok")
    return {
        "status": status,
        "reasons": reasons,
        "frames": len(window_rows),
        "window": {"start": start, "end": end},
        "unpaintedFrames": len(unpainted),
        "unpaintedMs": round(sum(deltas.get(v["seq"], period or 0.0) for v in unpainted), 3),
        "partialFrames": kinds.get(PARTIAL, 0),
        "doubleFrames": kinds.get("double", 0),
        "substituteFrames": kinds.get("substitute", 0),
        "minOpacity": min_opacity,
        "firstFailure": violations[0] if violations else None,
        "longestRun": max((r["frames"] for r in runs), default=0),
        "runs": runs[:RUNS_CAP],
        "unpaintedSeqs": [v["seq"] for v in unpainted][:SEQ_LIST_CAP],
        "partialSeqs": [v["seq"] for v in violations if v["kind"] == PARTIAL][:SEQ_LIST_CAP],
        "unobserved": unobserved[:RUNS_CAP],
        "unreadable": unreadable[:RUNS_CAP],
        "coverage": coverage,
        "outsideStagePx": round(outside, 1),
        "seekExcused": seek_excused,
    }


def _evidence_gaps(frames: Any, coverage: Any, unobserved: Any, unreadable: Any) -> list[str]:
    gaps: list[str] = []
    if not frames:
        gaps.append("no frames")
    if not (isinstance(coverage, dict) and coverage.get("ok") is True):
        gaps.append("coverage failed")
    if unobserved:
        gaps.append("frames unobserved before paint")
    if unreadable:
        gaps.append("frames unreadable")
    return gaps


def sampler_self_check(
    rows: list[dict[str, Any]], meta: dict[str, Any], *, read_now: float, max_gap_frames: int
) -> dict[str, Any]:
    """Plan §2.1 sampler liveness over every drained row of an arm: overflow, errors, duplicate or mismatched
    pre-paint reads, rows out of order or missing, a row without a pre-paint read, retained rows that do not
    reconcile with `meta.rafTicks`/`meta.prepaint`/`meta.lastTs`, or a stale last tick fail."""
    reasons: list[str] = []
    if not isinstance(meta, dict):
        return {"ok": False, "reasons": ["sampler meta missing"], "rows": len(rows)}
    if meta.get("schema") != SAMPLER_SCHEMA:
        reasons.append(f"meta.schema {meta.get('schema')!r}, expected {SAMPLER_SCHEMA}")
    if meta.get("running") is not False:
        reasons.append("meta.running is not false after stop")
    started_at, stopped_at = _finite(meta.get("startedAt")), _finite(meta.get("stoppedAt"))
    if started_at is None:
        reasons.append("meta.startedAt missing")
    if stopped_at is None:
        reasons.append("meta.stoppedAt missing")
    elif started_at is not None and stopped_at < started_at:
        reasons.append("meta.stoppedAt precedes meta.startedAt")
    if stopped_at is not None and (_finite(read_now) is None or read_now != stopped_at):
        reasons.append("self-check read time is not meta.stoppedAt")
    for key in ("overflow", "ppMismatch", "ppDuplicate"):
        value = meta.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            reasons.append(f"meta.{key} missing")
        elif value:
            reasons.append(f"meta.{key} = {value}")
    read_cost = meta.get("readCostMs")
    if not isinstance(read_cost, dict) or any(
        _finite(read_cost.get(key)) is None or read_cost[key] < 0 for key in ("sum", "max")
    ):
        reasons.append("meta.readCostMs missing or malformed")
    elif read_cost["max"] > read_cost["sum"]:
        reasons.append("meta.readCostMs.max exceeds sum")
    errors = meta.get("errors")
    if not isinstance(errors, list):
        reasons.append("meta.errors missing")
    elif errors:
        reasons.append(f"{len(errors)} sampler errors: {errors[0]}")
    seqs = [r.get("seq") for r in rows]
    if any(not isinstance(s, int) for s in seqs):
        reasons.append("rows without seq")
        seqs = [s for s in seqs if isinstance(s, int)]
    duplicates = len(seqs) - len(set(seqs))
    out_of_order = sum(1 for a, b in zip(seqs, seqs[1:]) if b <= a)
    gaps = sum(b - a - 1 for a, b in zip(seqs, seqs[1:]) if b > a + 1)
    if duplicates:
        reasons.append(f"{duplicates} duplicate rows")
    if out_of_order:
        reasons.append(f"{out_of_order} rows out of order")
    if gaps:
        reasons.append(f"{gaps} rows missing (seq gaps)")
    with_pp = sum(1 for r in rows if isinstance(r.get("pp"), dict))
    if rows and not with_pp:
        reasons.append("no pre-paint reads")
    elif with_pp < len(rows):
        reasons.append(f"{len(rows) - with_pp} rows without a pre-paint read")
    if not rows:
        reasons.append("no rows")
    for key, retained in (("rafTicks", len(rows)), ("prepaint", with_pp)):
        value = meta.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            reasons.append(f"meta.{key} missing")
        elif value != retained:
            reasons.append(f"{retained} rows retained against meta.{key} {value}")
    observer = meta.get("prepaintObserver")
    observer_accounted = None
    if not isinstance(observer, dict):
        reasons.append("meta.prepaintObserver missing")
    else:
        for key, expected in (("installed", True), ("active", False), ("disconnected", True)):
            if observer.get(key) is not expected:
                reasons.append(f"meta.prepaintObserver.{key} is not {str(expected).lower()}")
        counters = {}
        for key in ("callbacks", "ignored", "failures"):
            value = observer.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                reasons.append(f"meta.prepaintObserver.{key} missing")
            else:
                counters[key] = value
        if len(counters) == 3:
            outcomes = [meta.get(key) for key in ("prepaint", "ppMismatch", "ppDuplicate")]
            if all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in outcomes):
                expected_callbacks = sum(outcomes) + counters["ignored"] + counters["failures"]
                observer_accounted = counters["callbacks"] == expected_callbacks
                if not observer_accounted:
                    reasons.append(
                        f"meta.prepaintObserver callbacks {counters['callbacks']} do not reconcile with {expected_callbacks} outcomes"
                    )
    period = _period(rows)
    last_ts = meta.get("lastTs")
    stale_ms = round(read_now - last_ts, 3) if _num(last_ts) and _num(read_now) else None
    if stale_ms is None:
        reasons.append("meta.lastTs missing")
    elif rows and rows[-1].get("ts") != last_ts:
        reasons.append(f"last retained row ts {rows[-1].get('ts')!r} is not meta.lastTs {last_ts!r}")
    elif period is not None and stale_ms > (max_gap_frames + 1) * period:
        reasons.append(f"sampler stopped {stale_ms:.1f} ms before the read (> {(max_gap_frames + 1) * period:.1f} ms)")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "rows": len(rows),
        "rowsWithPp": with_pp,
        "rowsWithoutPp": len(rows) - with_pp,
        "seqGaps": gaps,
        "staleMs": stale_ms,
        "periodMs": None if period is None else round(period, 3),
        "rafTicks": meta.get("rafTicks"),
        "prepaint": meta.get("prepaint"),
        "startedAt": meta.get("startedAt"),
        "stoppedAt": meta.get("stoppedAt"),
        "prepaintObserver": observer,
        "observerAccountingComplete": observer_accounted,
        "readCostMs": meta.get("readCostMs"),
    }


def _hash_num(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    match = re.match(r"^#?(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


def paint_census(
    rows: list[dict[str, Any]],
    carried: Mapping[int, Sequence[Sequence[float]]],
    asset_by_id: Mapping[int, str],
    *,
    scene_count: int,
) -> dict[str, Any]:
    """Every painted→not→painted run of a carried element (probe id → its scored `(start, end)` windows), with a
    triage class: `scored` (overlaps a scored window), `endOfShow` (`hash >= scene_count`), `ended` (the clip
    reported `ended`), else `unscored`. No class removes an entry; rows without a pre-paint read are skipped."""
    findings: list[dict[str, Any]] = []
    observed = sorted((r for r in rows if _pp_problem(r) is None), key=lambda r: r["seq"])
    for element_id, windows in carried.items():
        gap: list[tuple[dict[str, Any], dict[str, Any] | None, str | None]] = []
        was_painted = False
        for row in observed:
            pv = next((v for v in row["pp"]["videos"] if isinstance(v, dict) and v.get("id") == element_id), None)
            state, reason = painted_state(pv, cover=bool(row["pp"].get("cover")))
            if state == PAINTED:
                if was_painted and gap:
                    findings.append(_census_entry(element_id, asset_by_id.get(element_id), gap, windows, scene_count))
                gap, was_painted = [], True
            elif was_painted:
                gap.append((row, pv, reason if state != PARTIAL else "partial"))
    classes = Counter(f["class"] for f in findings)
    return {"findings": findings, "counts": dict(classes), "elements": len(carried)}


def _census_entry(
    element_id: int, asset: str | None, gap: list[tuple[dict[str, Any], dict[str, Any] | None, str | None]],
    windows: Sequence[Sequence[float]], scene_count: int,
) -> dict[str, Any]:
    first, last = gap[0][0], gap[-1][0]
    hashes = [_hash_num(row.get("hash")) for row, _, _ in gap]
    if any(lo <= last["t"] and first["t"] <= hi for lo, hi in windows):
        klass = "scored"
    elif any(h is not None and h >= scene_count for h in hashes):
        klass = "endOfShow"
    elif any(pv and pv.get("ended") for _, pv, _ in gap):
        klass = "ended"
    else:
        klass = "unscored"
    return {
        "elementId": element_id, "asset": asset, "class": klass,
        "startSeq": first["seq"], "endSeq": last["seq"], "frames": len(gap),
        "t0": first["t"], "t1": last["t"],
        "reasons": dict(Counter(reason or "unknown" for _, _, reason in gap)),
        "hashes": sorted({h for h in hashes if h is not None}),
    }


def _paint_of(verdict: Any) -> dict[str, Any] | None:
    if not isinstance(verdict, dict):
        return None
    if "unpaintedSeqs" in verdict and "status" in verdict:
        return verdict
    for holder in (verdict, verdict.get("scored")):
        if isinstance(holder, dict) and isinstance(holder.get("paint"), dict):
            return holder["paint"]
    return None


def score_paint_control(record: dict[str, Any], target_verdict: dict[str, Any], n: int, timing: str) -> dict[str, Any]:
    """Plan §4 positive control, against the target carry's `score_paint` result (or a verdict holding it under
    `paint`). Pass needs the exact injected seq set on complete evidence; integrity breaks (abort, placement events,
    injector errors), an inconclusive paint score or any evidence gap (no frames, failed coverage, an unobserved or
    unreadable frame) are inconclusive, as is a record failing `control_record_problem` or a paint score failing
    `PAINT_SCORE_FIELDS`. `redSet == [target]` is the caller's check."""
    reasons: list[str] = []
    blockers: list[str] = []
    paint = _paint_of(target_verdict)
    if not isinstance(record, dict):
        return {"status": "fail", "reasons": ["no control record"]}
    record_problem = control_record_problem(record)
    if record_problem:
        return {"status": "inconclusive", "reasons": [f"control record unreadable: {record_problem}"], "expectedSeqs": [],
                "observedSeqs": None, "fired": record.get("fired") is True, "hiddenTicks": record.get("hiddenTicks")}
    control = record["control"]
    if control.get("n") != n or control.get("timing") != timing:
        reasons.append(f"control record is n={control.get('n')} timing={control.get('timing')}, expected n={n} timing={timing}")
    if record.get("aborted"):
        blockers.append(f"injector aborted: {record['aborted']}")
    if record.get("events"):
        blockers.append(f"placement events during the hide: {sorted({e.get('kind') for e in record['events']})}")
    if record.get("errors"):
        blockers.append(f"injector errors: {record['errors'][0]}")
    if not record.get("fired"):
        reasons.append("control never fired")
    on, off = record.get("onSeq"), record.get("offSeq")
    expected = list(range(on, on + n)) if isinstance(on, int) else []
    if record.get("hiddenTicks") != n:
        reasons.append(f"hiddenTicks {record.get('hiddenTicks')} != {n}")
    if record.get("hiddenSeqs") != expected:
        reasons.append(f"injector hidden seqs {record.get('hiddenSeqs')} != {expected}")
    if timing == "late" and n and record.get("lateSeqs") != [on, off]:
        reasons.append(f"late writer seqs {record.get('lateSeqs')} != {[on, off]}")
    observed: list[int] | None = None
    paint_problem = schema_problem(paint, PAINT_SCORE_FIELDS) if paint is not None else None
    if paint is None:
        blockers.append("target verdict has no paint score")
    elif paint_problem:
        blockers.append(f"paint score unreadable: {paint_problem}")
    else:
        gaps = _evidence_gaps(paint.get("frames"), paint.get("coverage"), paint.get("unobserved"), paint.get("unreadable"))
        if paint.get("status") == "inconclusive" or gaps:
            blockers.append("paint score inconclusive: " + "; ".join(paint.get("reasons") or gaps))
        half = control.get("variant") == "ancestor-half"
        seq_key, count_key, zero_key = (
            ("partialSeqs", "partialFrames", "unpaintedFrames") if half else ("unpaintedSeqs", "unpaintedFrames", "partialFrames")
        )
        observed = paint.get(seq_key)
        if observed != expected or paint.get(count_key) != len(expected):
            reasons.append(f"{seq_key} {observed} != injected {expected}")
        for key in (zero_key, "doubleFrames", "substituteFrames"):
            if paint.get(key):
                reasons.append(f"{key} = {paint.get(key)}")
    status = "inconclusive" if blockers else ("fail" if reasons else "pass")
    return {"status": status, "reasons": blockers + reasons, "expectedSeqs": expected, "observedSeqs": observed,
            "fired": bool(record.get("fired")), "hiddenTicks": record.get("hiddenTicks")}
