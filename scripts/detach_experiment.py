#!/usr/bin/env python3
"""Scratch driver for the one-frame detach experiment, main relevance arm
(`.agents/plans/keynote_live_continuity_detach_r8.plan.md` §2.3 on branch `claude/s2-detach-experiment`):
P2 host runs on MAIN's core (v5) with main's shipped player (R1-R8).

Port of the S2 driver (a06902d5) to main. Probe side only: the served core and player bytes are the host's
own (R8's identity and the served sha are asserted per run); the Level 1 instrument (plan §1 I1-I6) is
added to the sampler page in this process. One run = the P2 deck through `live_continuity_probe.run_arm`.

GL replay decides whether main carries at P2's 1->2 (atScene 2):
  auto  (managed OBS's product default) a glReplay zone: the decoder is pooled out of the DOM for the Magic
        Move, handed back into the destination's authored layer when the MM canvas leaves the stage, then
        carried (`reuse-decoder` -> facade -> `dom-swap`). The eligible event.
  off   (HDMI's default, the host gate's arm A) a retire zone: the raw player owns the movie, nothing is
        pooled or carried, so a run has 0 eligible events by construction and the controls cannot arm.

  run      one arm -> one record
  control  §1 Controls: `--mode null|positive|timeout0` (page injection at the first carry) or `--mode r8flag`
  batch    `--runs N` serial runs, resumable; invalid / error runs are retaken
  summary  events, blinks and strata of the batch records
  rescore  rebuild every record from its raw dump

Every run appends one record to `<out-dir>/runs.jsonl` and keeps its raw dump in `<out-dir>/raw/<runId>.json.gz`.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import plistlib
import re
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
from obed_edom.live_runtime import MM_OPACITY_ENV  # noqa: E402

R8_ANCHOR = b"this.textureManager.loadScene(B)}unloadTextures(){"
SERVED_SHA256 = "574274e88485745a6f55a8563d43ddfb91299db6e4d749fd34719436ade751bf"
CORE_SHA256 = "e9338aff1cbe0aee74e8e1ac94412a0ffb19f787962961d9ff8ed550ebd01fa4"
VARIANT = "V8"

DECKS = ("P2",)
GL_REPLAY_MODES = ("auto", "off")
DEFAULT_VIEWPORT = (2560, 1440)
CONTROL_MODES = ("null", "positive", "timeout0", "r8flag")
OFF_BY_CONSTRUCTION = "gl-replay off: retire@2, the raw player owns the movie and nothing is carried (0 eligible events by construction)"
CANNOT_ARM = "cannot arm: no reuse-decoder note (the core carried nothing)"

AUTO_IDLE_MAX_MS = 400.0
MM_MIN_MS = 800.0
JUMP_PAD_MS = 200.0
CARRY_WINDOW_MS = 500.0
CONTROL_FALLBACK_MS = 100
INVALID_DT_MS = 50.0
SLOW_DT_MS = 25.0
NOMINAL_FRAME_MS = 1000.0 / 60.0
LOAD_STRATA = (5.0, 15.0)
DONE_STATUSES = frozenset({"ok", "no-events"})
CARRY_KINDS = frozenset({"reuse-decoder"})
CORE_NOTE_RE = re.compile(
    r"^(preserve-on-detach|remount-|reuse-|dom-swap|createElement-video|bridge-3to4|retire|glreplay-(release|zone|hold))"
)
SAMPLE_VIDEO_KEYS = ("id", "elId", "src", "currentTime", "paused", "readyState", "preserved", "remounted", "facade", "rect")

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
  function hashNum(h){ var m = /^#?(\d+)/.exec(String(h || '')); return m ? parseInt(m[1], 10) : null; }
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
                isConnected: v.isConnected, remounting: !!v.__obedRemounting,
                preserved: !!(v.dataset && v.dataset.obedPreserved), remounted: !!(v.dataset && v.dataset.obedRemounted),
                glCarried: !!v.__obedGlCarried, facadeFor: v.__obedFacadeFor ? nn(v.__obedFacadeFor.__obedElId) : null,
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
      var plan = window.__OBED_CONTINUITY__ || {};
      ((plan.boundaries) || []).forEach(function(b){
        var r = b && b.action === 'glReplay' && b.instanceRect;
        if (r) pinCenters.push({atScene: b.atScene, movieKey: b.movieKey, x: r.x + r.w / 2, y: r.y + r.h / 2});
      });
      var movies = plan.movies || {};
      Object.keys(movies).forEach(function(k){
        var r = movies[k] && movies[k].footprint;
        if (r) pinCenters.push({atScene: null, movieKey: k, x: r.x + r.w / 2, y: r.y + r.h / 2});
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
          at.push({atScene: p.atScene, movieKey: p.movieKey, top: document.elementsFromPoint(x, y).slice(0, 3).map(describe), videoAt: inside});
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
  function fire(kind, t){
    if (rec.fired) return;
    rec.fired = true; rec.triggerKind = kind; rec.triggerT = t;
    queueMicrotask(function(){ try { act(); } catch (x) { fail('control', x); } });
  }
  function onNote(e){
    if (rec.fired || !e) return;
    var d = e.detail || {};
    if (rec.armedElId === null) {
      var scene = d.atScene != null ? d.atScene : hashNum(d.sceneHash);
      if (e.kind === 'reuse-decoder' && (rec.atScene === null || scene === rec.atScene)) {
        rec.armedElId = d.oldElId; rec.armedT = e.t; rec.armedAtScene = nn(scene); rec.armedHash = nn(d.sceneHash);
        setTimeout(function(){ fire('fallback', performance.now()); }, cfg.fallbackMs);
      }
      return;
    }
    if (d.elId === rec.armedElId && (e.kind === 'dom-swap' || (PLACED.test(e.kind) && d.inDocument))) fire(e.kind, e.t);
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
  var out = {coreEvents: null, glEvents: null, instrument: null};
  try {
    var core = window.__OBED_P2_PRESERVE__;
    out.coreEvents = core ? JSON.parse(JSON.stringify(core.events || [])) : null;
  } catch (e) { out.coreEvents = {error: String(e)}; }
  try {
    var gl = window.__OBED_GL_REPLAY__;
    out.glEvents = gl ? JSON.parse(JSON.stringify({state: gl.state, standDowns: gl.standDowns, events: gl.events})) : null;
  } catch (e) { out.glEvents = {error: String(e)}; }
  var i = window.__obedDetachInstr__;
  if (i) out.instrument = JSON.parse(JSON.stringify({lifecycle: i.lifecycle, prepaint: i.prepaint, control: i.control, errors: i.errors}));
  return out;
})()
"""


def check_r8(table: Sequence[tuple[bytes, bytes]] | None = None) -> None:
    """Main ships R1-R8 with R8 (the B+1 preload) last; refuse any other table."""
    table = live_runtime._MM_OPACITY_REPLACEMENTS if table is None else table
    if len(table) != 8 or table[7][0] != R8_ANCHOR:
        raise ValueError("the player replacement table is not the shipped R1-R8 table with R8 last")


@contextmanager
def serving() -> Iterator[None]:
    """Serve main's shipped player (R1-R8, mm opacity on) after asserting R8's identity."""
    check_r8()
    with probe.env_override({MM_OPACITY_ENV: "auto"}):
        yield


def instrumented_sampler_js(control: dict[str, Any] | None = None, sampler: str | None = None) -> str:
    """The probe's sampler with the frame time recorded per tick and the sentinel toggled, preceded by the
    Level 1 instrument (and an optional control injection)."""
    sampler = probe.SAMPLER_JS if sampler is None else sampler
    for anchor in (_TICK_ANCHOR, _PUSH_ANCHOR):
        if sampler.count(anchor) != 1:
            raise ValueError(f"sampler anchor missing or ambiguous: {anchor!r}")
    sampler = sampler.replace(_TICK_ANCHOR, _TICK_REPLACEMENT).replace(_PUSH_ANCHOR, _PUSH_REPLACEMENT)
    cfg = {"control": control, "fallbackMs": CONTROL_FALLBACK_MS}
    return INSTRUMENT_JS.replace("__CFG__", json.dumps(cfg)) + sampler


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


def _detail(event: dict[str, Any]) -> dict[str, Any]:
    detail = event.get("detail")
    return detail if isinstance(detail, dict) else {}


def _timed(events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events if isinstance(e, dict) and isinstance(e.get("t"), (int, float))]


def handback_of(core_events: Sequence[dict[str, Any]], tracked: set[Any], w1: float) -> dict[str, Any] | None:
    """The GL replay hand-back (`glreplay-release`, one-shot per deck) of a tracked decoder by `w1`, if any."""
    for e in _timed(core_events):
        d = _detail(e)
        if e.get("kind") == "glreplay-release" and e["t"] <= w1 and d.get("elId") in tracked:
            return {"t": e["t"], "mode": d.get("mode"), "reason": d.get("reason"), "elId": d.get("elId")}
    return None


def classify_jump(
    jump: dict[str, Any], samples: Sequence[dict[str, Any]], lifecycle: Sequence[dict[str, Any]],
    prepaint: Sequence[dict[str, Any]], core_events: Sequence[dict[str, Any]], frame_ms: float,
) -> dict[str, Any]:
    """One post-MM jump: eligibility (a pool-remounted decoder before it, carried across it), the blink by
    flanked-empty sample and by pre-paint, the teardown's frame phase, the re-home, and INVALID.

    Main's v5 core has no per-decoder instance id, so the carry is the core's own `reuse-decoder` note of a
    tracked decoder (`oldElId`), after the last sample before the first destination `Playing` and within
    CARRY_WINDOW_MS of it: the S2 driver's "instance changed after that sample"."""
    w0, w1 = jump["tSetup"] - JUMP_PAD_MS, jump["tPlay"] + JUMP_PAD_MS
    first = jump["playIndex"]
    pre_row = samples[first - 1] if first > 0 else None
    pre = pre_row["videos"] if pre_row else []
    tracked = {v["elId"] for v in pre if v.get("remounted") and v.get("elId") is not None}
    t_pre = pre_row["t"] if pre_row else float("-inf")
    carry = next((
        {"t": e["t"], "kind": e["kind"], "oldElId": _detail(e).get("oldElId"), "newElId": _detail(e).get("newElId")}
        for e in _timed(core_events)
        if e.get("kind") in CARRY_KINDS and _detail(e).get("oldElId") in tracked
        and t_pre < e["t"] <= jump["tPlay"] + CARRY_WINDOW_MS
    ), None)
    carried = carry is not None
    at_play = samples[first]["videos"]
    first_playing = "empty" if not at_play else "carried" if carried and carry["t"] <= samples[first]["t"] and any(
        v.get("elId") == carry["oldElId"] for v in at_play
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
        {"t": e["t"], "kind": e.get("kind"), "elId": _detail(e).get("elId", _detail(e).get("oldElId"))}
        for e in _timed(core_events)
        if w0 <= e["t"] <= w1 and CORE_NOTE_RE.match(str(e.get("kind")))
    ]
    max_dt = window_max_dt(samples, w0, w1)
    blink_samples, blink_prepaint = bool(sample_empty), bool(paint_empty)
    handback = handback_of(core_events, tracked, w1)
    return {
        **{key: jump[key] for key in ("scene", "mmScene", "waited", "mmWaited", "mmClick", "idleMs", "mmMs", "tSetup", "tPlay")},
        "r8Engaged": not jump["waited"],
        "eligible": bool(tracked) and carried, "tracked": sorted(tracked), "carried": carried, "carry": carry,
        "firstPlaying": first_playing,
        "handback": handback, "path": "handback" if handback else "remount" if tracked else None,
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
    those counts; r8flag: `waited` false (R8 engaged) at every post-MM jump after a click MM. A control that never
    saw a `reuse-decoder` note is `cannot-arm`, never a pass."""
    config = raw.get("config") or {}
    mode = config.get("control")
    samples = _rows(raw.get("samples"))
    instrument = raw.get("instrument") or {}
    prepaint = _rows(instrument.get("prepaint"))
    if mode == "r8flag":
        checked = [e for e in events if e["mmClick"]]
        wrong = [e["scene"] for e in checked if e["waited"]]
        status = "pass" if checked and not wrong else "fail"
        reasons = [] if checked else ["no post-MM jump after a click MM"]
        reasons += [f"scene {scene}: waited (R8 not engaged)" for scene in wrong]
        return {"mode": mode, "status": status, "reasons": reasons, "expectWaited": False,
                "jumps": len(checked), "waited": [e["waited"] for e in checked]}
    ctl = instrument.get("control") or {}
    if ctl.get("armedElId") is None:
        reasons = [CANNOT_ARM] + ([OFF_BY_CONSTRUCTION] if config.get("glReplay") == "off" else [])
        return {"mode": mode, "status": "cannot-arm", "reasons": reasons, "control": ctl}
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
    gl = continuity.get("glReplay") if isinstance(continuity.get("glReplay"), dict) else {}
    gl_mode = gl.get("mode")
    arm = raw.get("arm") or {}
    stage_fit = arm.get("stageFit")
    record = {
        **{key: raw.get(key) for key in ("runId", "startedAt", "wallS", "meta", "error")},
        **config,
        "servedSha256": served, "expectedServedSha256": SERVED_SHA256, "servedShaOk": served == SERVED_SHA256,
        "coreSha256": continuity.get("sha256"), "coreShaOk": continuity.get("sha256") == CORE_SHA256,
        "continuityMode": continuity.get("mode"), "glReplayMode": gl_mode, "glReplaySha256": gl.get("sha256"),
        "stageFitOk": bool(stage_fit.get("verdict")) if isinstance(stage_fit, dict) else None,
        "rafStats": stats, "instrumentErrors": instrument.get("errors"),
        "events": events,
    }
    reasons = []
    if raw.get("error"):
        reasons.append(f"run error: {raw['error']}")
    if not record["servedShaOk"]:
        reasons.append(f"served player sha {served} != expected {SERVED_SHA256}")
    if record["continuityMode"] != "qualified" or not record["coreShaOk"]:
        reasons.append(f"continuity {record['continuityMode']} core {record['coreSha256']}")
    if config.get("glReplay") == "auto" and gl_mode != "injected":
        reasons.append(f"gl replay requested auto but the host reports {gl_mode}")
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
        if config.get("glReplay") == "off":
            reasons.append(OFF_BY_CONSTRUCTION)
    else:
        status = "ok"
    record["status"], record["reasons"] = status, reasons
    record["eligibleEvents"] = len(eligible)
    record["blinks"] = sum(e["blink"] for e in eligible)
    if config.get("control"):
        record["controlVerdict"] = score_control(raw, events)
    return record


def pending_slots(runs: int, records: Sequence[dict[str, Any]], max_attempts: int) -> list[dict[str, Any]]:
    """The batch slots still owed, in order: a slot is done once a record is ok / no-events, and abandoned after
    `max_attempts` records (invalid or error retakes)."""
    attempts: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        if isinstance(record.get("slot"), int):
            attempts.setdefault(record["slot"], []).append(record)
    todo = []
    for slot in range(runs):
        done = attempts.get(slot, [])
        if any(r.get("status") in DONE_STATUSES for r in done) or len(done) >= max_attempts:
            continue
        todo.append({"slot": slot, "attempt": len(done) + 1})
    return todo


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


def summarize(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Per batch slot, its first done record: runs, eligible events and blinks, with strata by path, phase,
    hand-back and load. Any blink is a live main bug (plan §2.3)."""
    batch = [r for r in records if isinstance(r.get("slot"), int)]
    statuses: dict[str, int] = {}
    for r in batch:
        statuses[r.get("status")] = statuses.get(r.get("status"), 0) + 1
    chosen: dict[int, dict[str, Any]] = {}
    for r in batch:
        if r.get("status") in DONE_STATUSES and r["slot"] not in chosen:
            chosen[r["slot"]] = r
    row: dict[str, Any] = {
        "runs": 0, "events": 0, "blinks": 0, "blinkSamplesOnly": 0, "blinkPrepaintOnly": 0, "blinkDecoder": 0,
        "byPath": {}, "byPhase": {}, "byCarryPath": {}, "byLoad": {}, "glReplay": sorted({str(r.get("glReplay")) for r in chosen.values()}),
    }
    for _, r in sorted(chosen.items()):
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
            _bump(row["byCarryPath"], e.get("path"), e["blink"])
            _bump(row["byLoad"], load_stratum(r.get("meta")), e["blink"])
    decision = "blink: live main bug" if row["blinks"] else "no eligible events" if row["runs"] and not row["events"] else (
        "clean" if row["runs"] else "n/a"
    )
    return {"statuses": statuses, **row, "decision": decision}


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


def execute_run(
    out_dir: Path, run_id: str, *, arm: str, gl_replay: str, viewport: tuple[int, int],
    control: dict[str, Any] | None = None, extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One live P2 arm under the shipped serving and the instrument; writes the raw dump and appends the record."""
    config = {"deck": "P2", "variant": VARIANT, "arm": arm, "glReplay": gl_replay, "viewport": list(viewport),
              "control": control["mode"] if control else None, "controlAtScene": control and control.get("atScene"),
              **(extra or {})}
    raw: dict[str, Any] = {"runId": run_id, "config": config, "meta": collect_metadata(),
                           "startedAt": datetime.now().isoformat(timespec="seconds"), "error": None}
    started = time.monotonic()
    sink: dict[str, Any] = {}
    try:
        with probe.run_scope(out_dir / "detach-run.json") as root:
            export = probe.prepare_export(probe.FIXTURE, probe.ORIGINAL_INDEX, root, "detach")
            slides = probe.load_slides(export)
            plan = probe.ground_truth_plan(export, slides)
            facts = probe.ground_truth_facts(plan)
            probe.bind_dom_ids(facts, probe.movie_nodes(export, slides))
            facts_on = probe.gl_ground_truth(export, slides, facts)[1] if gl_replay == "auto" else None
            expected_stage = probe.expected_stage_fit(facts["canvas"], {"width": viewport[0], "height": viewport[1]})
            with ExitStack() as stack:
                stack.enter_context(serving())
                stack.enter_context(probe.env_override({probe.CONTINUITY_ENV: None}))
                stack.enter_context(instrumented(sink, control))
                if arm == "C":
                    stack.enter_context(probe.bridge_disabled())
                result = probe.run_arm(arm, export, slides, facts, viewport, expected_stage,
                                       gl_replay=gl_replay, facts_on=facts_on)
        raw["arm"] = {key: result.get(key) for key in ("continuity", "stageFit", "stageMapInvalidCount", "unplannedWraps",
                                                       "verdicts", "stopError", "factsSet")}
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


def _brief(record: dict[str, Any]) -> dict[str, Any]:
    keys = ("runId", "status", "reasons", "deck", "variant", "arm", "glReplay", "glReplayMode", "servedShaOk",
            "eligibleEvents", "blinks", "wallS", "controlVerdict")
    brief = {key: record.get(key) for key in keys if key in record}
    brief["events"] = [
        {key: e.get(key) for key in ("scene", "eligible", "waited", "path", "blink", "blinkSamples", "blinkPrepaint",
                                     "firstPlaying", "invalid", "maxDtMs")} | {"phase": (e.get("teardown") or {}).get("phase")}
        for e in record.get("events") or []
    ]
    if isinstance(brief.get("controlVerdict"), dict):
        brief["controlVerdict"] = {k: v for k, v in brief["controlVerdict"].items() if k != "control"}
    return brief


def _stamp() -> str:
    return f"{datetime.now():%Y%m%dT%H%M%S}"


def cmd_run(args: argparse.Namespace) -> int:
    run_id = f"{_stamp()}-{VARIANT}-P2-{args.arm}-gl{args.gl_replay}"
    record = execute_run(args.out_dir, run_id, arm=args.arm, gl_replay=args.gl_replay, viewport=args.viewport)
    print(json.dumps(_brief(record), indent=2, default=str))
    return 0 if record["status"] in DONE_STATUSES else 1


def cmd_control(args: argparse.Namespace) -> int:
    control = None if args.mode == "r8flag" else {"mode": args.mode, "atScene": args.at_scene}
    run_id = f"{_stamp()}-ctl-{args.mode}-{VARIANT}-P2-{args.arm}-gl{args.gl_replay}"
    record = execute_run(args.out_dir, run_id, arm=args.arm, gl_replay=args.gl_replay, viewport=args.viewport,
                         control=control, extra={"control": args.mode})
    print(json.dumps(_brief(record), indent=2, default=str))
    verdict = record.get("controlVerdict") or {}
    return 0 if verdict.get("status") in ("pass", "recorded") else 1


def _manifest(args: argparse.Namespace) -> dict[str, Any]:
    path = args.out_dir / "batch.json"
    wanted = {"arm": args.arm, "glReplay": args.gl_replay, "viewport": list(args.viewport)}
    if path.exists():
        manifest = json.loads(path.read_text())
        clash = {k: (manifest.get(k), v) for k, v in wanted.items() if manifest.get(k) != v}
        if clash:
            raise SystemExit(f"{path} was started with different settings: {clash}")
        manifest["runs"] = max(manifest["runs"], args.runs)
    else:
        manifest = {"runs": args.runs, **wanted, "createdAt": datetime.now().isoformat(timespec="seconds")}
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def cmd_batch(args: argparse.Namespace) -> int:
    manifest = _manifest(args)
    jsonl = args.out_dir / "runs.jsonl"
    print(json.dumps(manifest, default=str))
    while todo := pending_slots(manifest["runs"], read_jsonl(jsonl), args.max_attempts):
        slot = todo[0]
        run_id = f"main-{slot['slot']:02d}-{VARIANT}-P2-{manifest['arm']}-gl{manifest['glReplay']}-a{slot['attempt']}"
        record = execute_run(
            args.out_dir, run_id, arm=manifest["arm"], gl_replay=manifest["glReplay"],
            viewport=tuple(manifest["viewport"]), extra={"slot": slot["slot"], "attempt": slot["attempt"]},
        )
        print(json.dumps(_brief(record), default=str), flush=True)
        if (record["servedSha256"] is not None and not record["servedShaOk"]) or (
            record.get("continuityMode") == "qualified" and not record["coreShaOk"]
        ):
            raise SystemExit(f"{run_id}: served bytes are not main's shipped bytes; stopping ({record['reasons']})")
    records = read_jsonl(jsonl)
    print(json.dumps(summarize(records), indent=2, default=str))
    attempts: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        if isinstance(record.get("slot"), int):
            attempts.setdefault(record["slot"], []).append(record)
    abandoned = sorted(s for s, rs in attempts.items() if not any(r.get("status") in DONE_STATUSES for r in rs))
    if abandoned:
        print(f"abandoned slots after {args.max_attempts} attempts: {abandoned}")
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    print(json.dumps(summarize(read_jsonl(args.out_dir / "runs.jsonl")), indent=2, default=str))
    return 0


def cmd_rescore(args: argparse.Namespace) -> int:
    out = args.out_dir / "runs.rescored.jsonl"
    out.unlink(missing_ok=True)
    for path in sorted((args.out_dir / "raw").glob("*.json.gz")):
        with gzip.open(path, "rt") as handle:
            append_jsonl(out, build_record(json.load(handle)))
    print(json.dumps(summarize(read_jsonl(out)), indent=2, default=str))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def live(p: argparse.ArgumentParser) -> None:
        p.add_argument("--out-dir", type=Path, required=True)
        p.add_argument("--deck", choices=DECKS, default="P2")
        p.add_argument("--arm", choices=("A", "C"), default="A", help="A = as shipped; C = bridges stripped")
        p.add_argument("--gl-replay", choices=GL_REPLAY_MODES, default="auto",
                       help="auto = managed OBS's default (carries at @2); off = HDMI's default (retire@2, no carry)")
        p.add_argument("--viewport", type=probe.parse_viewport_arg, default=DEFAULT_VIEWPORT)

    run = sub.add_parser("run", help="one instrumented arm")
    live(run)
    run.set_defaults(func=cmd_run)

    control = sub.add_parser("control", help="one §1 control run")
    live(control)
    control.add_argument("--mode", choices=CONTROL_MODES, required=True)
    control.add_argument("--at-scene", type=int, default=None, help="arm at this scene's carry (default: the first)")
    control.set_defaults(func=cmd_control)

    batch = sub.add_parser("batch", help="N serial runs, resumable")
    live(batch)
    batch.add_argument("--runs", type=int, required=True)
    batch.add_argument("--max-attempts", type=int, default=3)
    batch.set_defaults(func=cmd_batch)

    for name, func in (("summary", cmd_summary), ("rescore", cmd_rescore)):
        p = sub.add_parser(name)
        p.add_argument("--out-dir", type=Path, required=True)
        p.set_defaults(func=func)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
