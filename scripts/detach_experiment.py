#!/usr/bin/env python3
"""Scratch driver for the one-frame detach experiment (`.agents/plans/keynote_live_continuity_detach_r8.plan.md`).

Probe side only: the served core and player bytes are the host's own, except the player's Magic Move
replacement table, which `serving` slices in this process (V8 = R1-R8, V7 = R1-R7, V5 = R1-R5,
V5+8 = R1-R5 + R8; `off` = OBED_LIVE_MM_OPACITY=off). One run = one deck through
`live_continuity_probe.run_arm` with the Level 1 instrument (plan §1 I1-I6) added to the sampler page.

  run      one arm (`--variant`, `--deck`, `--arm C` = bridges stripped) -> one record
  control  §1 Controls: `--mode null|positive|timeout0` (page injection at the first pin carry, arm A)
           or `--mode r8flag --variant off|V5|V7|V8`
  blocks   §2.4 interleaved blocks of {V8, V7, V5}, seeded order, deck rotated per block, resumable
  summary  §2.3 counts, Fisher one-sided V8 vs V7 / V5, early stop / futility
  rescore  rebuild every record from its raw dump

Every run appends one record to `<out-dir>/runs.jsonl` and keeps its raw dump in `<out-dir>/raw/<runId>.json.gz`.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import plistlib
import random
import re
import secrets
import statistics
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

REPO = Path(__file__).resolve().parents[1]
for _sub in ("src", "scripts"):
    if str(REPO / _sub) not in sys.path:
        sys.path.insert(0, str(REPO / _sub))

import live_continuity_probe as probe  # noqa: E402
from obed_edom import live_runtime  # noqa: E402
from obed_edom.fixture_paths import fixture  # noqa: E402
from obed_edom.live_runtime import MM_OPACITY_ENV  # noqa: E402

R8_ANCHOR = b"this.textureManager.loadScene(B)}unloadTextures(){"
VARIANT_INDICES: dict[str, tuple[int, ...]] = {
    "V8": (0, 1, 2, 3, 4, 5, 6, 7),
    "V7": (0, 1, 2, 3, 4, 5, 6),
    "V5": (0, 1, 2, 3, 4),
    "V5+8": (0, 1, 2, 3, 4, 7),
}
SERVINGS = ("off", *VARIANT_INDICES)
R8_SERVINGS = frozenset({"V8", "V5+8"})
SERVED_SHA256 = {
    "off": "7cf00b5606365ec9ca6276ec7c8ed7f55c119f6f6bf310e25857f3579acb75de",
    "V5": "21476f78a584d978796c8580cb302749a568536394fc01b616344c7d98655afe",
    "V7": "3730d38efd2649fcb0768febea1d429cd5ed643a8d3ba0e9d16a6149e0087733",
    "V8": "574274e88485745a6f55a8563d43ddfb91299db6e4d749fd34719436ade751bf",
    "V5+8": "ac8dcda082fa2cb2e3261fe9e5fc48d08c50cc4e59b459ffa1903e0778bc37a8",
}
CORE_SHA256 = "9c4fc61fcce22e8acf3b1dab9a6eb66722e7e0ae9dcf943bda69e3bcbd87ea01"

BLOCK_VARIANTS = ("V8", "V7", "V5")
BLOCK_DECKS = ("D4", "D1", "D6")
DECKS = ("D1", "D2", "D3", "D4", "D5", "D6", "P2")
DEFAULT_VIEWPORT = (2560, 1440)
CONTROL_MODES = ("null", "positive", "timeout0", "r8flag")

AUTO_IDLE_MAX_MS = 400.0
MM_MIN_MS = 800.0
JUMP_PAD_MS = 200.0
CARRY_WINDOW_MS = 500.0
INVALID_DT_MS = 50.0
SLOW_DT_MS = 25.0
NOMINAL_FRAME_MS = 1000.0 / 60.0
LOAD_STRATA = (5.0, 15.0)
EARLY_STOP_BLOCKS = 15
EARLY_STOP_V8_BLINKS = 6
FUTILITY_EVENTS = 30
FUTILITY_V8_BLINKS = 3
TARGET_EVENTS = 30
DONE_STATUSES = frozenset({"ok", "no-events"})
CORE_NOTE_RE = re.compile(r"^(preserve-on-detach|remount-|reuse-|dom-swap|createElement-video|bridge-3to4|retire)")
SAMPLE_VIDEO_KEYS = ("id", "elId", "instance", "src", "currentTime", "paused", "readyState", "preserved",
                     "remounted", "facade", "rect")

_TICK_ANCHOR = "  function tick(){\n    var t = performance.now();\n"
_TICK_REPLACEMENT = (
    "  function tick(ts){\n    var t = performance.now();\n"
    "    if (window.__obedDetachInstr__) window.__obedDetachInstr__.toggle(ts);\n"
)
_PUSH_ANCHOR = "samples.push({t: t, scene: state.sceneId,"
_PUSH_REPLACEMENT = "samples.push({t: t, rafTs: ts, scene: state.sceneId,"

INSTRUMENT_JS = r"""
(function(cfg){
  if (window.__obedDetachInstr__) return;
  var MAX_ROWS = 50000;
  var instr = {lifecycle: [], prepaint: [], control: null, errors: [], lastRafTs: null};
  instr.toggle = function(ts){ instr.lastRafTs = ts; };
  window.__obedDetachInstr__ = instr;
  function fail(where, e){ if (instr.errors.length < 50) instr.errors.push(where + ': ' + String(e && e.message || e)); }
  function cap(rows){ if (rows.length > MAX_ROWS) rows.shift(); }
""" + probe.STAGE_MAP_FN_JS + r"""
  function layerOf(n){ while (n) { if (n.id && n.id.indexOf('layer') === 0) return n.id; n = n.parentElement; } return null; }
  function snap(){
    try { var s = window.__obedLive.snapshot(); return {playerState: s.playerState, sceneId: s.sceneId, revision: s.revision}; }
    catch (e) { return null; }
  }
  function videosIn(node){
    if (node instanceof HTMLVideoElement) return [node];
    return node && node.querySelectorAll ? Array.prototype.slice.call(node.querySelectorAll('video')) : [];
  }
  function nn(x){ return x == null ? null : x; }
  try {
    new MutationObserver(function(muts){
      var t = performance.now(), s;
      muts.forEach(function(m){
        [['remove', m.removedNodes], ['add', m.addedNodes]].forEach(function(pair){
          Array.prototype.forEach.call(pair[1], function(node){
            videosIn(node).forEach(function(v){
              if (s === undefined) s = snap();
              instr.lifecycle.push({
                t: t, rafTs: instr.lastRafTs, op: pair[0], direct: node === v,
                probeId: nn(v.__obedProbeId), elId: nn(v.__obedElId),
                instance: v.__obedInstance != null ? String(v.__obedInstance) : null,
                isConnected: v.isConnected, remounting: !!v.__obedRemounting,
                preserved: !!(v.dataset && v.dataset.obedPreserved), remounted: !!(v.dataset && v.dataset.obedRemounted),
                hold: !!v.__obedHold, holdAction: v.__obedHold ? nn(v.__obedHold.action) : null,
                epoch: nn(v.__obedRemountEpoch), parentId: (m.target && m.target.id) || null,
                layerId: layerOf(m.target), snapshot: s
              });
              cap(instr.lifecycle);
            });
          });
        });
      });
    }).observe(document.documentElement, {childList: true, subtree: true});
  } catch (e) { fail('lifecycle', e); }

  var pinCenters = null;
  function pins(){
    if (pinCenters) return pinCenters;
    pinCenters = [];
    try {
      var plan = window.__OBED_CONTINUITY__;
      ((plan && plan.boundaries) || []).forEach(function(b){
        var r = b && b.action === 'pin' && b.dst && b.dst.rect;
        if (r) pinCenters.push({atScene: b.atScene, x: r.x + r.w / 2, y: r.y + r.h / 2});
      });
    } catch (e) { fail('pins', e); }
    return pinCenters;
  }
  function describe(el){
    if (!el) return null;
    if (el instanceof HTMLVideoElement) return 'video:' + nn(el.__obedElId);
    return el.tagName.toLowerCase() + (el.id ? '#' + el.id : '');
  }
  try {
    var host = document.createElement('div');
    host.style.cssText = 'position:fixed;left:-16px;top:-16px;width:8px;height:8px;overflow:hidden;opacity:0;pointer-events:none;';
    var sentinel = document.createElement('div');
    sentinel.style.cssText = 'display:block;width:1px;height:1px;';
    host.attachShadow({mode: 'closed'}).appendChild(sentinel);
    document.documentElement.appendChild(host);
    var wide = false;
    instr.toggle = function(ts){ instr.lastRafTs = ts; wide = !wide; sentinel.style.width = wide ? '2px' : '1px'; };
    new ResizeObserver(function(){
      try {
        var t = performance.now();
        var vids = Array.prototype.slice.call(document.querySelectorAll('video'));
        var rects = vids.map(function(v){ return v.getBoundingClientRect(); });
        var map = stageMapOf();
        var at = [];
        if (map) pins().forEach(function(p){
          var x = map.ox + p.x * map.s, y = map.oy + p.y * map.sy, inside = [];
          rects.forEach(function(r, i){ if (x >= r.left && x < r.right && y >= r.top && y < r.bottom) inside.push(nn(vids[i].__obedElId)); });
          at.push({atScene: p.atScene, top: document.elementsFromPoint(x, y).slice(0, 3).map(describe), videoAt: inside});
        });
        instr.prepaint.push({t: t, rafTs: instr.lastRafTs, n: vids.length, ids: vids.map(function(v){ return nn(v.__obedElId); }), pins: at});
        cap(instr.prepaint);
      } catch (e) { fail('prepaint', e); }
    }).observe(sentinel);
  } catch (e) { fail('sentinel', e); }

  var ctl = cfg.control;
  if (!ctl) return;
  var rec = {mode: ctl.mode, atScene: nn(ctl.atScene), fired: false, armedElId: null};
  instr.control = rec;
  var PLACED = /^remount-(authored-parent|into-authored-layer|done)$/;
  function act(){
    var v = null;
    document.querySelectorAll('video').forEach(function(x){ if (x.__obedElId === rec.armedElId) v = x; });
    if (!v) { rec.skipped = 'not-connected'; return; }
    var parent = v.parentNode, next = v.nextSibling;
    rec.parentId = parent.id || null;
    rec.layerId = layerOf(parent);
    v.__obedRemounting = true;
    setTimeout(function(){ v.__obedRemounting = false; }, 0);
    rec.rafTsAtRemove = instr.lastRafTs;
    rec.tRemove = performance.now();
    parent.removeChild(v);
    function reinsert(){
      rec.tReinsert = performance.now();
      rec.rafTsAtReinsert = instr.lastRafTs;
      if (v.isConnected) { rec.preempted = true; return; }
      if (!parent.isConnected) { rec.parentGone = true; return; }
      parent.insertBefore(v, next && next.parentNode === parent ? next : null);
      if (v.paused && !v.ended) { var p = v.play(); if (p && p.catch) p.catch(function(){}); }
    }
    if (ctl.mode === 'null') reinsert();
    else if (ctl.mode === 'positive') requestAnimationFrame(function(){ requestAnimationFrame(function(){ setTimeout(reinsert, 0); }); });
    else setTimeout(reinsert, 0);
  }
  function onNote(e){
    if (rec.fired || !e) return;
    var d = e.detail || {};
    if (rec.armedElId === null) {
      if (e.kind === 'reuse-decoder' && (rec.atScene === null || d.atScene === rec.atScene)) {
        rec.armedElId = d.oldElId; rec.armedT = e.t; rec.armedAtScene = nn(d.atScene);
      }
      return;
    }
    if (d.elId === rec.armedElId && (e.kind === 'dom-swap' || (PLACED.test(e.kind) && d.inDocument))) {
      rec.fired = true; rec.triggerKind = e.kind; rec.triggerT = e.t;
      queueMicrotask(function(){ try { act(); } catch (x) { fail('control', x); } });
    }
  }
  try {
    var events = window.__OBED_P2_PRESERVE__.events, push = events.push;
    events.push = function(){
      var r = push.apply(this, arguments);
      for (var i = 0; i < arguments.length; i++) { try { onNote(arguments[i]); } catch (x) { fail('control', x); } }
      return r;
    };
  } catch (e) { fail('control-hook', e); }
})(__CFG__);
"""

INSTRUMENT_READ_JS = r"""
(function(){
  var out = {coreEvents: null, instrument: null};
  try {
    var core = window.__OBED_P2_PRESERVE__;
    out.coreEvents = core ? JSON.parse(JSON.stringify(core.events || [])) : null;
  } catch (e) { out.coreEvents = {error: String(e)}; }
  var i = window.__obedDetachInstr__;
  if (i) out.instrument = JSON.parse(JSON.stringify({lifecycle: i.lifecycle, prepaint: i.prepaint, control: i.control, errors: i.errors}));
  return out;
})()
"""


def variant_replacements(variant: str, table: Sequence[tuple[bytes, bytes]] | None = None) -> tuple[tuple[bytes, bytes], ...]:
    """The served replacement table of `variant`, sliced from the full R1-R8 table after asserting R8's identity."""
    table = live_runtime._MM_OPACITY_REPLACEMENTS if table is None else table
    if len(table) != 8 or table[7][0] != R8_ANCHOR:
        raise ValueError("the player replacement table is not the R1-R8 table this experiment slices")
    if variant not in VARIANT_INDICES:
        raise ValueError(f"unknown variant {variant!r}; expected one of {tuple(VARIANT_INDICES)}")
    return tuple(table[i] for i in VARIANT_INDICES[variant])


@contextmanager
def serving(variant: str) -> Iterator[None]:
    """Serve `variant`'s player bytes from this process's `patch_player` (no product file changes)."""
    if variant not in SERVINGS:
        raise ValueError(f"unknown serving {variant!r}; expected one of {SERVINGS}")
    original = live_runtime._MM_OPACITY_REPLACEMENTS
    table = original if variant == "off" else variant_replacements(variant, original)
    live_runtime._MM_OPACITY_REPLACEMENTS = table
    try:
        with probe.env_override({MM_OPACITY_ENV: "off" if variant == "off" else "auto"}):
            yield
    finally:
        live_runtime._MM_OPACITY_REPLACEMENTS = original


def served_sha256(player: bytes, variant: str) -> str:
    with serving(variant):
        return hashlib.sha256(live_runtime.patch_player(player, mm_opacity=variant != "off")).hexdigest()


def instrumented_sampler_js(control: dict[str, Any] | None = None, sampler: str | None = None) -> str:
    """The probe's sampler with the frame time recorded per tick and the sentinel toggled, preceded by the
    Level 1 instrument (and an optional control injection)."""
    sampler = probe.SAMPLER_JS if sampler is None else sampler
    for anchor in (_TICK_ANCHOR, _PUSH_ANCHOR):
        if sampler.count(anchor) != 1:
            raise ValueError(f"sampler anchor missing or ambiguous: {anchor!r}")
    sampler = sampler.replace(_TICK_ANCHOR, _TICK_REPLACEMENT).replace(_PUSH_ANCHOR, _PUSH_REPLACEMENT)
    return INSTRUMENT_JS.replace("__CFG__", json.dumps({"control": control})) + sampler


def trim_samples(samples: Any) -> list[dict[str, Any]]:
    rows = samples if isinstance(samples, list) else []
    return [
        {
            "t": row.get("t"), "rafTs": row.get("rafTs"), "scene": row.get("scene"),
            "playerState": row.get("playerState"),
            "videos": [{key: video.get(key) for key in SAMPLE_VIDEO_KEYS} for video in row.get("videos") or []],
        }
        for row in rows if isinstance(row, dict)
    ]


@contextmanager
def instrumented(sink: dict[str, Any], control: dict[str, Any] | None = None) -> Iterator[None]:
    """Install the instrument through the probe's own sampler seam and read it back before the host stops."""
    original_js, original_drive = probe.SAMPLER_JS, probe.drive_and_sample

    def drive(player: Any, **kwargs: Any) -> list[dict[str, Any]]:
        samples = original_drive(player, **kwargs)
        sink["samples"] = trim_samples(samples)
        sink["output"] = {key: player.output.get(key) for key in ("mmOpacity", "continuity", "viewport")}
        sink.update(player._require_transport().evaluate(INSTRUMENT_READ_JS) or {})
        return samples

    probe.SAMPLER_JS = instrumented_sampler_js(control, original_js)
    probe.drive_and_sample = drive
    try:
        yield
    finally:
        probe.SAMPLER_JS, probe.drive_and_sample = original_js, original_drive


def state_runs(samples: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for index, row in enumerate(samples):
        key = (row.get("scene"), row.get("playerState"))
        if runs and runs[-1]["key"] == key:
            runs[-1]["j"] = index
        else:
            runs.append({"key": key, "scene": key[0], "state": key[1], "i": index, "j": index})
    return runs


def _run_ms(samples: Sequence[dict[str, Any]], runs: list[dict[str, Any]], n: int) -> float:
    end = samples[runs[n + 1]["i"]]["t"] if n + 1 < len(runs) else samples[runs[n]["j"]]["t"]
    return float(end - samples[runs[n]["i"]]["t"])


def post_mm_jumps(samples: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every automatic jump straight after a Magic Move: Playing (MM, >= MM_MIN_MS) -> IdleAtFinalState
    (< AUTO_IDLE_MAX_MS) -> [WaitingToJump] -> SettingUpScene -> Playing. `waited` is plan §1 I5."""
    runs = state_runs(samples)
    jumps = []
    for n, run in enumerate(runs):
        if run["state"] != "Playing" or n < 4 or runs[n - 1]["state"] != "SettingUpScene":
            continue
        k = n - 2
        waited = runs[k]["state"] == "WaitingToJump"
        if waited:
            k -= 1
        if k < 2 or runs[k]["state"] != "IdleAtFinalState":
            continue
        idle_ms = _run_ms(samples, runs, k)
        m = k - 1
        if idle_ms >= AUTO_IDLE_MAX_MS or runs[m]["state"] != "Playing" or runs[m - 1]["state"] != "SettingUpScene":
            continue
        mm_ms = _run_ms(samples, runs, m)
        if mm_ms < MM_MIN_MS:
            continue
        before = m - 2
        mm_waited = before >= 0 and runs[before]["state"] == "WaitingToJump"
        if mm_waited:
            before -= 1
        mm_click = before >= 0 and runs[before]["state"] in ("IdleAtFinalState", "IdleAtInitialState") and (
            _run_ms(samples, runs, before) >= AUTO_IDLE_MAX_MS
        )
        jumps.append({
            "scene": run["scene"], "mmScene": runs[m]["scene"], "waited": waited, "mmWaited": mm_waited,
            "mmClick": mm_click, "idleMs": round(idle_ms, 1), "mmMs": round(mm_ms, 1),
            "setupIndex": runs[n - 1]["i"], "playIndex": run["i"],
            "tSetup": samples[runs[n - 1]["i"]]["t"], "tPlay": samples[run["i"]]["t"],
        })
    return jumps


def absent_runs(rows: Sequence[dict[str, Any]], absent: Callable[[dict[str, Any]], bool]) -> list[tuple[int, int]]:
    """Maximal runs of `absent` rows with a present row on both sides."""
    runs, start = [], None
    for index, row in enumerate(rows):
        if absent(row):
            if start is None:
                start = index
        elif start is not None:
            if start > 0:
                runs.append((start, index - 1))
            start = None
    return runs


def runs_in_window(rows: Sequence[dict[str, Any]], runs: list[tuple[int, int]], w0: float, w1: float) -> list[dict[str, Any]]:
    """The runs that start inside [w0, w1] (a Magic Move's own empty run ends there; it never starts there)."""
    return [{"t0": rows[a]["t"], "t1": rows[b]["t"], "frames": b - a + 1} for a, b in runs if w0 <= rows[a]["t"] <= w1]


def frame_time(row: dict[str, Any]) -> float:
    return float(row["rafTs"] if isinstance(row.get("rafTs"), (int, float)) else row["t"])


def frame_deltas(samples: Sequence[dict[str, Any]]) -> list[tuple[float, float]]:
    """(frame time, delta to the previous frame) per sample after the first."""
    times = [frame_time(row) for row in samples]
    return [(times[i], times[i] - times[i - 1]) for i in range(1, len(times))]


def raf_stats(samples: Sequence[dict[str, Any]]) -> dict[str, Any]:
    deltas = sorted(dt for _, dt in frame_deltas(samples))
    if not deltas:
        return {"n": 0, "medianMs": None, "p95Ms": None, "over25": 0, "over50": 0, "maxMs": None}
    return {
        "n": len(deltas), "medianMs": round(statistics.median(deltas), 3),
        "p95Ms": round(deltas[min(len(deltas) - 1, math.ceil(0.95 * len(deltas)) - 1)], 3),
        "over25": sum(dt > SLOW_DT_MS for dt in deltas), "over50": sum(dt > INVALID_DT_MS for dt in deltas),
        "maxMs": round(deltas[-1], 3),
    }


def window_max_dt(samples: Sequence[dict[str, Any]], w0: float, w1: float) -> float:
    """Largest frame interval overlapping [w0, w1]."""
    times = [frame_time(row) for row in samples]
    overlapping = [times[i] - times[i - 1] for i in range(1, len(times)) if times[i - 1] <= w1 and times[i] >= w0]
    return max(overlapping, default=0.0)


def phase_bucket(fraction: float | None) -> str | None:
    if fraction is None:
        return None
    return "early" if fraction < 1 / 3 else "mid" if fraction < 2 / 3 else "late"


def _phase(row: dict[str, Any] | None, frame_ms: float) -> dict[str, Any] | None:
    if row is None:
        return None
    raf = row.get("rafTs")
    phase_ms = row["t"] - raf if isinstance(raf, (int, float)) else None
    fraction = phase_ms / frame_ms if phase_ms is not None and frame_ms > 0 else None
    return {
        "t": row["t"], "rafTs": raf, "elId": row.get("elId"), "isConnected": row.get("isConnected"),
        "remounting": row.get("remounting"), "phaseMs": None if phase_ms is None else round(phase_ms, 3),
        "phaseFrac": None if fraction is None else round(fraction, 4), "phase": phase_bucket(fraction),
    }


def classify_jump(
    jump: dict[str, Any], samples: Sequence[dict[str, Any]], lifecycle: Sequence[dict[str, Any]],
    prepaint: Sequence[dict[str, Any]], core_events: Sequence[dict[str, Any]], frame_ms: float,
) -> dict[str, Any]:
    """One post-MM jump: eligibility (a pool-remounted decoder before it, carried across it), the blink by
    flanked-empty sample and by pre-paint, the teardown's frame phase, the re-home, and INVALID."""
    w0, w1 = jump["tSetup"] - JUMP_PAD_MS, jump["tPlay"] + JUMP_PAD_MS
    first = jump["playIndex"]
    pre = samples[first - 1]["videos"] if first > 0 else []
    tracked = {v["elId"] for v in pre if v.get("remounted") and v.get("elId") is not None}
    pre_instance = {v["elId"]: v.get("instance") for v in pre if v.get("elId") in tracked}
    carried = any(
        v.get("elId") in tracked and v.get("instance") != pre_instance[v["elId"]]
        for row in samples[first:] if row["t"] <= jump["tPlay"] + CARRY_WINDOW_MS
        for v in row["videos"]
    )
    at_play = samples[first]["videos"]
    first_playing = "empty" if not at_play else "carried" if any(
        v.get("elId") in tracked and v.get("instance") != pre_instance[v["elId"]] for v in at_play
    ) else "old"

    def doc_empty(row: dict[str, Any]) -> bool:
        return not row.get("videos")

    def decoder_absent(row: dict[str, Any]) -> bool:
        return not any(v.get("elId") in tracked for v in row.get("videos") or [])

    def prepaint_empty(row: dict[str, Any]) -> bool:
        return not row.get("n")

    def prepaint_decoder_absent(row: dict[str, Any]) -> bool:
        return not tracked.intersection(row.get("ids") or [])

    sample_empty = runs_in_window(samples, absent_runs(samples, doc_empty), w0, w1)
    sample_decoder = runs_in_window(samples, absent_runs(samples, decoder_absent), w0, w1) if tracked else []
    paint_runs = absent_runs(prepaint, prepaint_empty)
    paint_empty = runs_in_window(prepaint, paint_runs, w0, w1)
    paint_decoder = runs_in_window(prepaint, absent_runs(prepaint, prepaint_decoder_absent), w0, w1) if tracked else []
    severity = [prepaint[a].get("pins") for a, _ in paint_runs if w0 <= prepaint[a]["t"] <= w1]

    in_window = [row for row in lifecycle if w0 <= row["t"] <= w1]
    teardown = next((row for row in in_window if row["op"] == "remove"), None)
    tracked_removal = next((row for row in in_window if row["op"] == "remove" and row.get("elId") in tracked), None)
    rehome = None
    if tracked_removal is not None:
        rehome = next((
            row for row in lifecycle
            if row["op"] == "add" and row.get("elId") == tracked_removal["elId"] and row["t"] >= tracked_removal["t"]
            and row["t"] <= jump["tPlay"] + CARRY_WINDOW_MS
        ), None)
    notes = [
        {"t": e.get("t"), "kind": e.get("kind"),
         "elId": (e.get("detail") or {}).get("elId", (e.get("detail") or {}).get("oldElId"))
         if isinstance(e.get("detail"), dict) else None}
        for e in core_events
        if isinstance(e, dict) and isinstance(e.get("t"), (int, float)) and w0 <= e["t"] <= w1
        and CORE_NOTE_RE.match(str(e.get("kind")))
    ]
    max_dt = window_max_dt(samples, w0, w1)
    blink_samples, blink_prepaint = bool(sample_empty), bool(paint_empty)
    return {
        **{key: jump[key] for key in ("scene", "mmScene", "waited", "mmWaited", "mmClick", "idleMs", "mmMs", "tSetup", "tPlay")},
        "r8Engaged": not jump["waited"],
        "eligible": bool(tracked) and carried, "tracked": sorted(tracked), "carried": carried,
        "firstPlaying": first_playing,
        "sampleEmptyRuns": sample_empty, "prepaintEmptyRuns": paint_empty,
        "sampleDecoderAbsentRuns": sample_decoder, "prepaintDecoderAbsentRuns": paint_decoder,
        "blinkSamples": blink_samples, "blinkPrepaint": blink_prepaint, "blink": blink_samples and blink_prepaint,
        "blinkDecoder": bool(sample_decoder) and bool(paint_decoder),
        "severity": severity,
        "teardown": _phase(teardown, frame_ms), "trackedRemoval": _phase(tracked_removal, frame_ms),
        "rehome": None if rehome is None else {
            "t": rehome["t"], "sameDelivery": rehome["t"] == tracked_removal["t"],
            "afterRemovalMs": round(rehome["t"] - tracked_removal["t"], 3), "parentId": rehome.get("parentId"),
            "layerId": rehome.get("layerId"),
        },
        "coreNotes": notes,
        "maxDtMs": round(max_dt, 3), "invalid": max_dt > INVALID_DT_MS,
    }


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def score_control(raw: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Plan §1 Controls. null: 0 flags; positive: the decoder absent in exactly the 2-3 sampler ticks and the 2-3
    pre-paint callbacks between removal and re-insert; timeout0: recorded, with whether both instruments agree with
    those counts; r8flag: `waited` matches the serving at every post-MM jump after a click MM."""
    config = raw.get("config") or {}
    mode = config.get("control")
    samples = _rows(raw.get("samples"))
    instrument = raw.get("instrument") or {}
    prepaint = _rows(instrument.get("prepaint"))
    if mode == "r8flag":
        expect_waited = config.get("variant") not in R8_SERVINGS
        checked = [e for e in events if e["mmClick"]]
        wrong = [e["scene"] for e in checked if e["waited"] != expect_waited]
        status = "pass" if checked and not wrong else "fail"
        reasons = [] if checked else ["no post-MM jump after a click MM"]
        reasons += [f"scene {scene}: waited != {expect_waited}" for scene in wrong]
        return {"mode": mode, "status": status, "reasons": reasons, "expectWaited": expect_waited,
                "jumps": len(checked), "waited": [e["waited"] for e in checked]}
    ctl = instrument.get("control") or {}
    if not ctl.get("fired") or ctl.get("skipped") or not isinstance(ctl.get("tRemove"), (int, float)):
        return {"mode": mode, "status": "fail", "reasons": [f"control did not act: {ctl}"], "control": ctl}
    el_id, t_remove = ctl.get("armedElId"), ctl["tRemove"]
    t_reinsert = ctl.get("tReinsert") if isinstance(ctl.get("tReinsert"), (int, float)) else t_remove
    sample_absent = runs_in_window(samples, absent_runs(samples, lambda r: not any(
        v.get("elId") == el_id for v in r.get("videos") or [])), t_remove, t_reinsert)
    paint_absent = runs_in_window(prepaint, absent_runs(prepaint, lambda r: el_id not in (r.get("ids") or [])),
                                  t_remove, t_reinsert)
    ticks = sum(t_remove < row["t"] < t_reinsert for row in samples)
    paints = sum(t_remove < row["t"] < t_reinsert for row in prepaint)
    lifecycle = [row for row in _rows(instrument.get("lifecycle")) if row.get("elId") == el_id]
    removal = next((row for row in lifecycle if row["op"] == "remove" and row["t"] >= t_remove), None)
    readd = next((row for row in lifecycle if row["op"] == "add" and removal is not None and row["t"] >= removal["t"]), None)
    sample_frames = sum(run["frames"] for run in sample_absent)
    paint_frames = sum(run["frames"] for run in paint_absent)
    w0, w1 = t_remove - JUMP_PAD_MS, t_reinsert + JUMP_PAD_MS
    near_sample_empty = runs_in_window(samples, absent_runs(samples, lambda r: not r.get("videos")), w0, w1)
    near_paint_empty = runs_in_window(prepaint, absent_runs(prepaint, lambda r: not r.get("n")), w0, w1)
    out = {
        "mode": mode, "control": ctl, "ticksBetween": ticks, "paintsBetween": paints, "sampleAbsentFrames": sample_frames,
        "prepaintAbsentFrames": paint_frames, "nearSampleEmptyRuns": near_sample_empty,
        "nearPrepaintEmptyRuns": near_paint_empty,
        "lifecycle": {"removeT": removal and removal["t"], "addT": readd and readd["t"],
                      "removeIsConnected": removal and removal["isConnected"]},
    }
    reasons: list[str] = []
    if ctl.get("preempted") or ctl.get("parentGone"):
        reasons.append("the decoder was re-homed before the control re-inserted it" if ctl.get("preempted")
                       else "the decoder's parent left the document before the re-insert")
    if mode == "null":
        if sample_frames or paint_frames or near_sample_empty or near_paint_empty:
            reasons.append("the null control flagged an empty frame")
        if removal is None or readd is None or removal["t"] != readd["t"]:
            reasons.append("I2 did not show remove and add in one delivery")
        out["status"] = "fail" if reasons else "pass"
    elif mode == "positive":
        if not (2 <= ticks <= 3 and sample_frames == ticks and paint_frames == paints and 2 <= paints <= 3):
            reasons.append(f"samples {sample_frames}/{ticks} ticks, pre-paint {paint_frames}/{paints} paints: "
                           "disagree or not ~2 frames")
        out["status"] = "fail" if reasons else "pass"
    else:
        out["agree"] = (sample_frames == ticks) and (paint_frames == paints)
        out["status"] = "recorded" if not reasons else "fail"
    out["reasons"] = reasons
    return out


def build_record(raw: dict[str, Any]) -> dict[str, Any]:
    """The per-run JSONL record, a pure function of the raw dump."""
    config = raw.get("config") or {}
    samples = _rows(raw.get("samples"))
    instrument = raw.get("instrument") or {}
    core_events = _rows(raw.get("coreEvents"))
    stats = raf_stats(samples)
    frame_ms = stats["medianMs"] or NOMINAL_FRAME_MS
    events = [
        classify_jump(jump, samples, _rows(instrument.get("lifecycle")), _rows(instrument.get("prepaint")), core_events, frame_ms)
        for jump in post_mm_jumps(samples)
    ] if samples else []
    output = raw.get("output") or {}
    served = (output.get("mmOpacity") or {}).get("sha256")
    continuity = output.get("continuity") or {}
    expected = SERVED_SHA256.get(config.get("variant"))
    arm = raw.get("arm") or {}
    stage_fit = arm.get("stageFit")
    record = {
        **{key: raw.get(key) for key in ("runId", "startedAt", "wallS", "meta", "error")},
        **config,
        "servedSha256": served, "expectedServedSha256": expected, "servedShaOk": served is not None and served == expected,
        "coreSha256": continuity.get("sha256"), "coreShaOk": continuity.get("sha256") == CORE_SHA256,
        "continuityMode": continuity.get("mode"),
        "stageFitOk": bool(stage_fit.get("verdict")) if isinstance(stage_fit, dict) else None,
        "rafStats": stats, "instrumentErrors": instrument.get("errors"),
        "events": events,
    }
    reasons = []
    if raw.get("error"):
        reasons.append(f"run error: {raw['error']}")
    if not record["servedShaOk"]:
        reasons.append(f"served player sha {served} != expected {expected}")
    if record["continuityMode"] != "qualified" or not record["coreShaOk"]:
        reasons.append(f"continuity {record['continuityMode']} core {record['coreSha256']}")
    if record["stageFitOk"] is False:
        reasons.append("stage fit failed")
    eligible = [e for e in events if e["eligible"]]
    if reasons:
        status = "error"
    elif any(e["invalid"] for e in eligible):
        status = "invalid"
        reasons.append("a frame interval > 50 ms inside a jump window")
    elif not eligible:
        status = "no-events"
    else:
        status = "ok"
    record["status"], record["reasons"] = status, reasons
    record["eligibleEvents"] = len(eligible)
    record["blinks"] = sum(e["blink"] for e in eligible)
    if config.get("control"):
        record["controlVerdict"] = score_control(raw, events)
    return record


def block_plan(seed: int, blocks: int, variants: Sequence[str] = BLOCK_VARIANTS, decks: Sequence[str] = BLOCK_DECKS) -> list[dict[str, Any]]:
    """Per block: the deck (rotated) and a seeded random order of the variants."""
    plan = []
    for block in range(blocks):
        order = list(variants)
        random.Random(f"{seed}:{block}").shuffle(order)
        plan.append({"block": block, "deck": decks[block % len(decks)], "order": order})
    return plan


def slot_attempts(records: Sequence[dict[str, Any]], seed: int) -> dict[tuple[int, str], list[dict[str, Any]]]:
    slots: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for record in records:
        if record.get("seed") == seed and record.get("block") is not None:
            slots.setdefault((record["block"], record["variant"]), []).append(record)
    return slots


def pending_runs(plan: Sequence[dict[str, Any]], records: Sequence[dict[str, Any]], seed: int, max_attempts: int) -> list[dict[str, Any]]:
    """The runs still owed, in plan order: a slot is done once a record is ok / no-events, and abandoned after
    `max_attempts` records (invalid or error retakes)."""
    slots = slot_attempts(records, seed)
    todo = []
    for block in plan:
        for variant in block["order"]:
            done = slots.get((block["block"], variant), [])
            if any(r.get("status") in DONE_STATUSES for r in done) or len(done) >= max_attempts:
                continue
            todo.append({"block": block["block"], "deck": block["deck"], "variant": variant, "attempt": len(done) + 1,
                         "order": block["order"]})
    return todo


def fisher_one_sided(a: int, n1: int, c: int, n2: int) -> float:
    """P(X >= a) for the first group's events under the hypergeometric null (H1: group 1 rate is higher)."""
    k, n = a + c, n1 + n2
    total = math.comb(n, k)
    return sum(math.comb(n1, x) * math.comb(n2, k - x) for x in range(a, min(n1, k) + 1)) / total if total else 1.0


def load_stratum(meta: Any) -> str | None:
    load = (meta or {}).get("loadavg") if isinstance(meta, dict) else None
    if not load:
        return None
    low, high = LOAD_STRATA
    return "low" if load[0] < low else "mid" if load[0] < high else "high"


def _bump(table: dict[str, list[int]], key: Any, blink: bool) -> None:
    cell = table.setdefault(str(key), [0, 0])
    cell[0] += 1
    cell[1] += int(blink)


def summarize(records: Sequence[dict[str, Any]], seed: int | None = None) -> dict[str, Any]:
    """§2.3: per-variant event and blink counts from each block slot's done record, Fisher V8 vs V7 / V5,
    strata by path, phase and load, and the early-stop / futility decision."""
    block_records = [r for r in records if r.get("block") is not None and (seed is None or r.get("seed") == seed)]
    statuses: dict[str, int] = {}
    for r in block_records:
        statuses[r.get("status")] = statuses.get(r.get("status"), 0) + 1
    chosen: dict[tuple[Any, int, str], dict[str, Any]] = {}
    for r in block_records:
        key = (r.get("seed"), r["block"], r["variant"])
        if r.get("status") in DONE_STATUSES and key not in chosen:
            chosen[key] = r
    per: dict[str, dict[str, Any]] = {}
    blocks: dict[tuple[Any, int], set[str]] = {}
    for (run_seed, block, variant), r in sorted(chosen.items(), key=lambda kv: (str(kv[0][0]), kv[0][1], kv[0][2])):
        blocks.setdefault((run_seed, block), set()).add(variant)
        row = per.setdefault(variant, {
            "runs": 0, "events": 0, "blinks": 0, "blinkSamplesOnly": 0, "blinkPrepaintOnly": 0, "blinkDecoder": 0,
            "byPath": {}, "byPhase": {}, "byLoad": {}, "byDeck": {},
        })
        row["runs"] += 1
        for e in r.get("events") or []:
            if not e.get("eligible"):
                continue
            row["events"] += 1
            row["blinks"] += int(e["blink"])
            row["blinkSamplesOnly"] += int(e["blinkSamples"] and not e["blinkPrepaint"])
            row["blinkPrepaintOnly"] += int(e["blinkPrepaint"] and not e["blinkSamples"])
            row["blinkDecoder"] += int(e.get("blinkDecoder", False))
            _bump(row["byPath"], "waited" if e["waited"] else "direct", e["blink"])
            _bump(row["byPhase"], (e.get("teardown") or {}).get("phase"), e["blink"])
            _bump(row["byLoad"], load_stratum(r.get("meta")), e["blink"])
            _bump(row["byDeck"], r.get("deck"), e["blink"])
    tests = {
        f"V8vs{other}": fisher_one_sided(per["V8"]["blinks"], per["V8"]["events"], per[other]["blinks"], per[other]["events"])
        for other in ("V7", "V5") if "V8" in per and other in per
    }
    complete = sum(1 for variants in blocks.values() if set(BLOCK_VARIANTS) <= variants)
    return {"statuses": statuses, "completeBlocks": complete, "perVariant": per, "fisherOneSided": tests,
            "decision": decide(per, complete)}


def decide(per: dict[str, dict[str, Any]], complete_blocks: int) -> str:
    if not set(BLOCK_VARIANTS) <= set(per):
        return "n/a"
    v8, v7, v5 = (per[v] for v in BLOCK_VARIANTS)
    if complete_blocks >= EARLY_STOP_BLOCKS and v8["blinks"] >= EARLY_STOP_V8_BLINKS and v7["blinks"] == v5["blinks"] == 0:
        return "early-stop"
    if v8["events"] >= FUTILITY_EVENTS and v8["blinks"] < FUTILITY_V8_BLINKS:
        return "futility"
    if all(per[v]["events"] >= TARGET_EVENTS for v in BLOCK_VARIANTS):
        return "target-met"
    return "continue"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text().splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a") as handle:
        handle.write(json.dumps(record, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _command(args: list[str]) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception as exc:  # noqa: BLE001 - metadata only
        return f"error: {exc}"


def parse_loadavg(text: str) -> list[float] | None:
    values = re.findall(r"\d+(?:\.\d+)?", text or "")
    return [float(v) for v in values[:3]] if len(values) >= 3 else None


def chrome_version() -> str | None:
    try:
        with (probe.CHROME.parents[1] / "Info.plist").open("rb") as handle:
            return plistlib.load(handle).get("CFBundleShortVersionString")
    except Exception:  # noqa: BLE001 - metadata only
        return None


def collect_metadata() -> dict[str, Any]:
    """Plan §1 I6, read before each run (never launches Chrome)."""
    loadavg = _command(["sysctl", "-n", "vm.loadavg"])
    chrome = _command(["pgrep", "-f", "Google Chrome"])
    return {
        "wallClock": datetime.now().isoformat(timespec="seconds"),
        "loadavg": parse_loadavg(loadavg), "loadavgRaw": loadavg, "uptime": _command(["uptime"]),
        "chromeProcesses": len([line for line in chrome.splitlines() if line.strip().isdigit()]),
        "obedLiveChrome": probe.check_no_leftover_chrome(), "therm": _command(["pmset", "-g", "therm"]),
        "chromeVersion": chrome_version(), "gitHead": _command(["git", "-C", str(REPO), "rev-parse", "HEAD"]),
    }


def deck_paths(deck: str) -> tuple[Path, Path]:
    if deck == "P2":
        return probe.FIXTURE, probe.ORIGINAL_INDEX
    root = fixture("qual-decks") / deck / "html-unmodified"
    return root, root / "index.html"


def execute_run(
    out_dir: Path, run_id: str, *, deck: str, variant: str, arm: str, viewport: tuple[int, int],
    control: dict[str, Any] | None = None, extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One live arm under the given serving and instrument; writes the raw dump and appends the record."""
    fixture_dir, original_index = deck_paths(deck)
    config = {"deck": deck, "variant": variant, "arm": arm, "viewport": list(viewport),
              "control": control["mode"] if control else None, "controlAtScene": control and control.get("atScene"),
              **(extra or {})}
    raw: dict[str, Any] = {"runId": run_id, "config": config, "meta": collect_metadata(),
                           "startedAt": datetime.now().isoformat(timespec="seconds"), "error": None}
    started = time.monotonic()
    sink: dict[str, Any] = {}
    try:
        export = probe.prepare_export(fixture_dir, original_index, "detach")
        slides = probe.load_slides(export)
        plan = probe.ground_truth_plan(export, slides)
        facts = probe.ground_truth_facts(plan, arrival=probe.arrival_starts(export, slides, plan))
        probe.bind_dom_ids(facts, probe.movie_nodes(export, slides))
        expected_stage = probe.expected_stage_fit(facts["canvas"], {"width": viewport[0], "height": viewport[1]})
        with ExitStack() as stack:
            stack.enter_context(serving(variant))
            stack.enter_context(probe.env_override({probe.CONTINUITY_ENV: None}))
            stack.enter_context(instrumented(sink, control))
            if arm == "C":
                stack.enter_context(probe.bridge_disabled())
            result = probe.run_arm(arm, export, slides, facts, viewport, expected_stage)
        raw["arm"] = {key: result.get(key) for key in ("continuity", "stageFit", "stageMapInvalidCount", "unplannedWraps",
                                                       "verdicts", "stopError")}
    except Exception as exc:  # noqa: BLE001 - always leave a record behind
        raw["error"] = f"{type(exc).__name__}: {exc}"
    raw.update(sink)
    raw["wallS"] = round(time.monotonic() - started, 1)
    raw["leftoverChromeAfter"] = probe.check_no_leftover_chrome()
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(raw_dir / f"{run_id}.json.gz", "wt") as handle:
        json.dump(raw, handle, default=str)
    record = build_record(raw)
    append_jsonl(out_dir / "runs.jsonl", record)
    return record


def _safe(name: str) -> str:
    return name.replace("+", "p")


def _brief(record: dict[str, Any]) -> dict[str, Any]:
    keys = ("runId", "status", "reasons", "deck", "variant", "arm", "servedShaOk", "eligibleEvents", "blinks", "wallS",
            "controlVerdict")
    brief = {key: record.get(key) for key in keys if key in record}
    brief["events"] = [
        {key: e.get(key) for key in ("scene", "eligible", "waited", "blink", "blinkSamples", "blinkPrepaint", "firstPlaying",
                                     "invalid", "maxDtMs")} | {"phase": (e.get("teardown") or {}).get("phase")}
        for e in record.get("events") or []
    ]
    if isinstance(brief.get("controlVerdict"), dict):
        brief["controlVerdict"] = {k: v for k, v in brief["controlVerdict"].items() if k != "control"}
    return brief


def cmd_run(args: argparse.Namespace) -> int:
    run_id = f"{datetime.now():%Y%m%dT%H%M%S}-{_safe(args.variant)}-{args.deck}-{args.arm}"
    record = execute_run(args.out_dir, run_id, deck=args.deck, variant=args.variant, arm=args.arm, viewport=args.viewport)
    print(json.dumps(_brief(record), indent=2, default=str))
    return 0 if record["status"] in DONE_STATUSES else 1


def cmd_control(args: argparse.Namespace) -> int:
    control = None if args.mode == "r8flag" else {"mode": args.mode, "atScene": args.at_scene}
    run_id = f"{datetime.now():%Y%m%dT%H%M%S}-ctl-{args.mode}-{_safe(args.variant)}-{args.deck}-{args.arm}"
    record = execute_run(args.out_dir, run_id, deck=args.deck, variant=args.variant, arm=args.arm, viewport=args.viewport,
                         control=control, extra={"control": args.mode})
    print(json.dumps(_brief(record), indent=2, default=str))
    verdict = record.get("controlVerdict") or {}
    return 0 if verdict.get("status") in ("pass", "recorded") else 1


def _manifest(args: argparse.Namespace) -> dict[str, Any]:
    path = args.out_dir / "blocks.json"
    wanted = {"blocks": args.blocks, "variants": args.variants, "decks": args.decks, "arm": args.arm,
              "viewport": list(args.viewport)}
    if path.exists():
        manifest = json.loads(path.read_text())
        if args.seed is not None and args.seed != manifest["seed"]:
            raise SystemExit(f"{path} has seed {manifest['seed']}, not {args.seed}")
        clash = {k: (manifest.get(k), v) for k, v in wanted.items() if k != "blocks" and manifest.get(k) != v}
        if clash:
            raise SystemExit(f"{path} was started with different settings: {clash}")
        manifest["blocks"] = max(manifest["blocks"], args.blocks)
    else:
        manifest = {"seed": args.seed if args.seed is not None else secrets.randbelow(2**31), **wanted,
                    "createdAt": datetime.now().isoformat(timespec="seconds")}
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def cmd_blocks(args: argparse.Namespace) -> int:
    manifest = _manifest(args)
    seed = manifest["seed"]
    plan = block_plan(seed, manifest["blocks"], manifest["variants"], manifest["decks"])
    jsonl = args.out_dir / "runs.jsonl"
    print(json.dumps({"seed": seed, "blocks": manifest["blocks"], "plan": plan}, default=str))
    while True:
        records = read_jsonl(jsonl)
        todo = pending_runs(plan, records, seed, args.max_attempts)
        if not todo:
            break
        decision = summarize(records, seed)["decision"]
        if args.stop_rules and decision in ("early-stop", "futility"):
            print(f"stopping: {decision}")
            break
        run = todo[0]
        run_id = f"s{seed}-b{run['block']:02d}-{_safe(run['variant'])}-{run['deck']}-a{run['attempt']}"
        record = execute_run(
            args.out_dir, run_id, deck=run["deck"], variant=run["variant"], arm=manifest["arm"],
            viewport=tuple(manifest["viewport"]), extra={"seed": seed, "block": run["block"], "attempt": run["attempt"],
                                                         "order": run["order"]},
        )
        print(json.dumps(_brief(record), default=str), flush=True)
        if (record["servedSha256"] is not None and not record["servedShaOk"]) or (
            record.get("continuityMode") == "qualified" and not record["coreShaOk"]
        ):
            raise SystemExit(f"{run_id}: served bytes are not the planned arm's; stopping ({record['reasons']})")
    summary = summarize(read_jsonl(jsonl), seed)
    print(json.dumps(summary, indent=2, default=str))
    abandoned = [k for k, v in slot_attempts(read_jsonl(jsonl), seed).items()
                 if len(v) >= args.max_attempts and not any(r.get("status") in DONE_STATUSES for r in v)]
    if abandoned:
        print(f"abandoned slots after {args.max_attempts} attempts: {sorted(abandoned)}")
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    records = read_jsonl(args.out_dir / "runs.jsonl")
    print(json.dumps(summarize(records, args.seed), indent=2, default=str))
    return 0


def cmd_rescore(args: argparse.Namespace) -> int:
    out = args.out_dir / "runs.rescored.jsonl"
    out.unlink(missing_ok=True)
    for path in sorted((args.out_dir / "raw").glob("*.json.gz")):
        with gzip.open(path, "rt") as handle:
            append_jsonl(out, build_record(json.load(handle)))
    print(json.dumps(summarize(read_jsonl(out), args.seed), indent=2, default=str))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def live(p: argparse.ArgumentParser, arm: str) -> None:
        p.add_argument("--out-dir", type=Path, required=True)
        p.add_argument("--arm", choices=("A", "C"), default=arm, help="A = continuity on; C = bridges stripped")
        p.add_argument("--viewport", type=probe.parse_viewport_arg, default=DEFAULT_VIEWPORT)

    run = sub.add_parser("run", help="one instrumented arm")
    live(run, "C")
    run.add_argument("--variant", choices=SERVINGS, required=True)
    run.add_argument("--deck", choices=DECKS, required=True)
    run.set_defaults(func=cmd_run)

    control = sub.add_parser("control", help="one §1 control run")
    live(control, "A")
    control.add_argument("--mode", choices=CONTROL_MODES, required=True)
    control.add_argument("--variant", choices=SERVINGS, default="V8")
    control.add_argument("--deck", choices=DECKS, default="D4")
    control.add_argument("--at-scene", type=int, default=None, help="fire at this pin boundary (default: the first)")
    control.set_defaults(func=cmd_control)

    blocks = sub.add_parser("blocks", help="the interleaved A/B, resumable")
    live(blocks, "C")
    blocks.add_argument("--blocks", type=int, required=True)
    blocks.add_argument("--seed", type=int, default=None)
    blocks.add_argument("--variants", type=lambda s: s.split(","), default=list(BLOCK_VARIANTS))
    blocks.add_argument("--decks", type=lambda s: s.split(","), default=list(BLOCK_DECKS))
    blocks.add_argument("--max-attempts", type=int, default=3)
    blocks.add_argument("--no-stop-rules", dest="stop_rules", action="store_false")
    blocks.set_defaults(func=cmd_blocks)

    for name, func in (("summary", cmd_summary), ("rescore", cmd_rescore)):
        p = sub.add_parser(name)
        p.add_argument("--out-dir", type=Path, required=True)
        p.add_argument("--seed", type=int, default=None)
        p.set_defaults(func=func)

    args = parser.parse_args(argv)
    if args.command == "blocks":
        bad = [v for v in args.variants if v not in VARIANT_INDICES] + [d for d in args.decks if d not in DECKS]
        if bad:
            parser.error(f"unknown variants/decks: {bad}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
