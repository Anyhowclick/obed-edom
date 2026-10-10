#!/usr/bin/env python3
"""Scratch driver for the one-frame detach experiment (`.agents/plans/keynote_live_continuity_detach_r8.plan.md`).

Probe side only: the served core and player bytes are the host's own, except the player's Magic Move
replacement table, which `serving` slices in this process (V8 = R1-R8, V7 = R1-R7, V5 = R1-R5,
V5+8 = R1-R5 + R8; `off` = OBED_LIVE_MM_OPACITY=off). One run = one deck through
`live_continuity_probe.run_arm` with the Level 1 instrument (plan §1 I1-I6) added to the sampler page.

  run      one arm (`--variant`, `--deck`, `--arm C` = bridges stripped) -> one record
  control  §1 Controls: `--mode null|positive|timeout0` (page injection at the first pin carry, arm A)
           or `--mode r8flag --variant off|V5|V7|V8`
  blocks   §2.4 interleaved blocks of {V8, V7, V5} (or fix arms `V8,V8+a1,V8+a2`), seeded order, deck rotated
           per block, resumable
  summary  §2.3 counts, Fisher one-sided V8 vs every other arm, early stop / futility, and the detach-gap readout
           (teardown / carry removals: same delivery, same checkpoint, pre-paint rows in the gap)
  rescore  rebuild every record from its raw dump
  classify §4 step 3: name the branch (H1-H4) of every blink from its raw dump

`--level2` (run, control, blocks) adds plan §1 Level 2: the player controller exposed through a patched
`live_runtime._INSTALL`, page wraps of the player's preload / jump / render methods and of DOM removals that take a
preserved decoder out, and a trace-only core variant (wraps of `stash`, `scheduleRemount`, `tryRemount`, `beginMove`,
`retireDecoder`; no branch changes). `--core-fix a1|a2` serves a probe-only core fix candidate (plan §3 (a1)/(a2)).
Both are string transforms of the in-process bytes with count-checked anchors; served and core shas are recorded and
checked per run.

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
from obed_edom.live_continuity_js import PRESERVE_CORE_JS  # noqa: E402
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
CORE_FIXES = ("a1", "a2")
FIX_ARM_RE = re.compile(r"^(?P<serving>.+?)\+(?P<fix>a1|a2)$")
L2_INSTALL_ANCHOR = b"(function(controller) {\n"
L2_INSTALL_REPLACEMENT = L2_INSTALL_ANCHOR + b"  Object.defineProperty(window, '__obedDebugController', {value: controller});\n"
L2_SERVED_SHA256 = {
    "off": "b7ad87163010c542130edbad5bdb891e8f258c232b29d4924bee6dfae0c9c800",
    "V5": "c4852e2314ce5956a1e03337c4e66c8be2e1b96d8147ef2392d6afe32052fa11",
    "V7": "b64e9e70cac243f54c9c22250f6100ff9a831409cfd60eac7621abfe9e8f6f6f",
    "V8": "50833d1dee43087263864265ebfd10fd4d383b55a7a76101f5cc9095540d80c6",
    "V5+8": "660fd7fc473a365b4e02dca587e3428792b02e41eae430b183286c807ec99712",
}

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
DETACH_WHY_RE = re.compile(r"^preserve-on-detach")
RETIRE_NOTES = ("retire-boundary", "retire-on-start-movie")
CORE_REMOVERS = ("retireDecoder", "retireVictims", "bindFacade")
PLAYER_CONTEXT_MS = 50.0
PLAYER_CONTEXT_KINDS = frozenset({"jumpToScene", "partFour-start", "partFour-end", "renderEvent-start", "renderEvent-end",
                                  "animateEffects-start", "animateEffects-end", "state"})
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
  var deliveries = 0;
  try {
    new MutationObserver(function(muts){
      var t = performance.now(), s, delivery = ++deliveries, seen = [];
      muts.forEach(function(m){
        [['remove', m.removedNodes], ['add', m.addedNodes]].forEach(function(pair){
          Array.prototype.forEach.call(pair[1], function(node){
            videosIn(node).forEach(function(v){
              if (s === undefined) s = snap();
              var row = {
                t: t, delivery: delivery, rafTs: instr.lastRafTs, op: pair[0], direct: node === v,
                probeId: nn(v.__obedProbeId), elId: nn(v.__obedElId),
                instance: v.__obedInstance != null ? String(v.__obedInstance) : null,
                isConnected: v.isConnected, remounting: !!v.__obedRemounting,
                preserved: !!(v.dataset && v.dataset.obedPreserved), remounted: !!(v.dataset && v.dataset.obedRemounted),
                hold: !!v.__obedHold, holdAction: v.__obedHold ? nn(v.__obedHold.action) : null,
                epoch: nn(v.__obedRemountEpoch), parentId: (m.target && m.target.id) || null,
                layerId: layerOf(m.target), snapshot: s
              };
              if (cfg.level2) row.seq = window.__obedSeq__ = (window.__obedSeq__ || 0) + 1;
              instr.lifecycle.push(row);
              cap(instr.lifecycle);
              seen.push([row, v]);
            });
          });
        });
      });
      if (seen.length) queueMicrotask(function(){
        seen.forEach(function(p){ p[0].connectedAfterRound = p[1].isConnected; });
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

LEVEL2_JS = r"""
(function(){
  if (window.__obedDetachL2__) return;
  var MAX_ROWS = 50000;
  var l2 = {rows: [], errors: [], wrapped: [], textureCalls: {}, installedAt: performance.now()};
  window.__obedDetachL2__ = l2;
  function fail(where, e){ if (l2.errors.length < 50) l2.errors.push(where + ': ' + String(e && e.message || e)); }
  function log(kind, extra){
    var i = window.__obedDetachInstr__;
    var row = {seq: window.__obedSeq__ = (window.__obedSeq__ || 0) + 1, t: performance.now(),
               rafTs: i ? i.lastRafTs : null, kind: kind};
    for (var k in extra) row[k] = extra[k];
    l2.rows.push(row);
    if (l2.rows.length > MAX_ROWS) l2.rows.shift();
  }
  function stack(){
    try {
      return String(new Error().stack || '').split('\n').slice(3, 11).map(function(l){
        return l.trim().replace(/^at /, '').replace(/(?:https?|file):\/\/[^\s)]*\/([^\/\s)]+)/g, '$1');
      });
    } catch (e) { return null; }
  }
  function layerOf(n){ while (n) { if (n.id && n.id.indexOf('layer') === 0) return n.id; n = n.parentElement; } return null; }
  function videos(){ return document.querySelectorAll('video').length; }
  var C = window.__obedDebugController;
  if (!C) { fail('controller', 'window.__obedDebugController is missing'); return; }
  function isMM(i){
    try { var ev = C.script.events[i], f = ev && ev.effects && ev.effects[0]; return !!f && f.name === 'apple:magic-move-implied-motion-path'; }
    catch (e) { return null; }
  }
  function wrap(obj, name, label, before, after){
    if (!obj || typeof obj[name] !== 'function') { fail('wrap', label + ' is missing'); return; }
    var orig = obj[name];
    obj[name] = function(){
      var ctx = null;
      try { ctx = before ? before.apply(this, arguments) : null; } catch (e) { fail(label, e); }
      var out = orig.apply(this, arguments);
      try { if (after) after.call(this, ctx, out, arguments); } catch (e) { fail(label, e); }
      return out;
    };
    l2.wrapped.push(label);
  }
  var inPreload = 0;
  if (typeof C.preloadTextures === 'function') {
    var preload = C.preloadTextures;
    C.preloadTextures = function(){ inPreload += 1; try { return preload.apply(this, arguments); } finally { inPreload -= 1; } };
    l2.wrapped.push('preloadTextures');
  } else fail('wrap', 'preloadTextures is missing');
  var tm = C.textureManager, pc = C.playbackController;
  function slideOf(scene){ try { return C.script.slideIndexFromSceneIndexLookup[scene]; } catch (e) { return null; } }
  function slideReady(slide){ try { return !!tm.isSlidePreloaded(slide); } catch (e) { return null; } }
  wrap(tm, 'loadScene', 'loadScene', function(A, B){
    log('loadScene', {scene: A, slide: slideOf(A), withCallback: !!B, viaPreload: inPreload > 0,
                      prevIsMM: isMM(A - 1), isMM: isMM(A), readyBefore: slideReady(slideOf(A)), state: C.state});
  });
  wrap(tm, 'isScenePreloaded', 'isScenePreloaded', null, function(_, out, args){
    log('isScenePreloaded', {scene: args[0], result: out, state: C.state});
  });
  wrap(tm, 'processTextureDidLoadCallback', 'processTextureDidLoadCallback', function(A, B){
    l2.textureCalls[B] = (l2.textureCalls[B] || 0) + 1;
    return slideReady(B);
  }, function(was, _, args){
    if (!was && slideReady(args[1])) log('slide-ready', {slide: args[1], calls: l2.textureCalls[args[1]]});
  });
  wrap(C, 'jumpToScene', 'jumpToScene', function(A, B){ log('jumpToScene', {scene: A, automatic: !!B, state: C.state}); });
  wrap(C, 'jumpToScene_partFour', 'jumpToScene_partFour', function(A){
    log('partFour-start', {scene: A, videos: videos()}); return A;
  }, function(A){ log('partFour-end', {scene: A, videos: videos()}); });
  wrap(C, 'changeState', 'changeState', function(){ return C.state; }, function(from){
    log('state', {from: from, to: C.state, scene: C.currentSceneIndex});
  });
  wrap(pc, 'renderEvent', 'renderEvent', function(A){
    var scene = A && A.sceneIndex != null ? A.sceneIndex : null;
    log('renderEvent-start', {scene: scene, videos: videos()}); return scene;
  }, function(scene){ log('renderEvent-end', {scene: scene, videos: videos()}); });
  wrap(pc, 'animateEffects', 'animateEffects', function(){
    log('animateEffects-start', {scene: C.currentSceneIndex, videos: videos()});
  }, function(){ log('animateEffects-end', {scene: C.currentSceneIndex, videos: videos()}); });

  function preservedIn(node){
    if (!node || node.nodeType !== 1) return null;
    var list = node.tagName === 'VIDEO' ? [node] : node.getElementsByTagName('video'), ids = null;
    for (var i = 0; i < list.length; i++) {
      var v = list[i];
      if (v.dataset && (v.dataset.obedPreserved || v.dataset.obedRemounted)) (ids = ids || []).push(v.__obedElId == null ? null : v.__obedElId);
    }
    return ids;
  }
  function hook(proto, name, argIndex){
    var orig = proto[name];
    proto[name] = function(){
      var node = argIndex < 0 ? this : arguments[argIndex], ids = null;
      try { if (node && node.isConnected) ids = preservedIn(node); } catch (e) { fail(name, e); }
      if (ids) {
        try {
          var from = node.parentNode;
          log('dom-' + name, {elIds: ids, parentId: (from && from.id) || null, layerId: layerOf(from),
                              targetId: (this && this.id) || null, by: stack()});
        } catch (e) { fail(name, e); }
      }
      return orig.apply(this, arguments);
    };
    l2.wrapped.push('dom-' + name);
  }
  hook(Node.prototype, 'removeChild', 0);
  hook(Node.prototype, 'insertBefore', 0);
  hook(Node.prototype, 'appendChild', 0);
  hook(Node.prototype, 'replaceChild', 1);
  hook(Element.prototype, 'remove', -1);
})();
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
  if (window.__obedDetachL2__) out.level2 = JSON.parse(JSON.stringify(window.__obedDetachL2__));
  if (window.__OBED_DETACH_TRACE__) out.coreTrace = JSON.parse(JSON.stringify(window.__OBED_DETACH_TRACE__));
  return out;
})()
"""

_TRACE_HELPERS = r"""  const __obedTraceRows = [];
  window.__OBED_DETACH_TRACE__ = __obedTraceRows;
  function __obedTrace(kind, v, extra) {
    try {
      const i = window.__obedDetachInstr__;
      const row = {
        seq: window.__obedSeq__ = (window.__obedSeq__ || 0) + 1, t: performance.now(), rafTs: i ? i.lastRafTs : null,
        kind: kind, elId: v && v.__obedElId != null ? v.__obedElId : null,
        isConnected: !!(v && v.isConnected), remounting: !!(v && v.__obedRemounting)
      };
      for (const k in (extra || {})) row[k] = extra[k];
      __obedTraceRows.push(row);
      if (__obedTraceRows.length > 20000) __obedTraceRows.shift();
    } catch (e) {}
  }
  function __obedCaller() {
    try {
      return String(new Error().stack || '').split('\n').slice(2, 9).map(function(l) {
        return l.trim().replace(/^at /, '').replace(/(?:https?|file):\/\/[^\s)]*\/([^\/\s)]+)/g, '$1');
      });
    } catch (e) { return null; }
  }
  function __obedNotedSince(n0) {
    return window.__OBED_P2_PRESERVE__.events.slice(n0).map(function(e) { return e.kind; });
  }
"""

_STASH_TRACE = r"""  function stash(v, why, detached) {
    const n0 = window.__OBED_P2_PRESERVE__.events.length;
    let pre = null;
    try {
      if (v instanceof HTMLVideoElement) {
        const src = v.currentSrc || v.src || '';
        pre = {
          isConnected: v.isConnected, remounting: !!v.__obedRemounting,
          detached: detached === undefined ? null : !!detached, disabled: disabled,
          bridged34: !!v.__obedBridged34, suppressed34: !!v.__obedSuppressed34, facade: !!v.__obedFacadeFor,
          gen: v.__obedGen == null ? null : v.__obedGen, generation: preserveGeneration,
          assetKey: !!assetKey(src), planAsset: !!movieAssetKey(src), poolable: poolable(v),
          readyState: v.readyState, currentTime: v.currentTime
        };
      }
    } catch (e) {}
    __obedStashInner(v, why, detached);
    __obedTrace('stash', v, {why: String(why), pre: pre, noted: __obedNotedSince(n0)});
  }
  function __obedStashInner(v, why"""

_SCHEDULE_TRACE = r"""  function scheduleRemount(v, why) {
    const before = !!(v && v.isConnected);
    const n0 = window.__OBED_P2_PRESERVE__.events.length;
    __obedScheduleRemountInner(v, why);
    __obedTrace('scheduleRemount', v, {why: String(why), before: before, noted: __obedNotedSince(n0)});
  }
  function __obedScheduleRemountInner(v, why) {
"""

_TRY_REMOUNT_TRACE = r"""  function tryRemount(v, epoch) {
    const before = !!(v && v.isConnected);
    const n0 = window.__OBED_P2_PRESERVE__.events.length;
    __obedTryRemountInner(v, epoch);
    const after = !!(v && v.isConnected);
    const parent = v ? v.parentNode : null;
    const extra = {
      epoch: epoch == null ? null : epoch, before: before, after: after, noted: __obedNotedSince(n0),
      parentId: parent ? (parent.id || null) : null, layerId: parent ? ((nearestLayer(parent) || {}).id || null) : null
    };
    if (!after && v) {
      extra.state = {
        disabled: disabled, suppress: suppressRemount, staleEpoch: epoch != null && epoch !== remountEpoch,
        dead: v.__obedRemountEpoch === -1 || !!v.ended, stageMap: !!stageMap(),
        authoredParent: !!(v.__obedParent && document.contains(v.__obedParent))
      };
    }
    __obedTrace('tryRemount', v, extra);
  }
  function __obedTryRemountInner(v, epoch) {
"""

_BEGIN_MOVE = "  function beginMove(v) {\n    v.__obedRemounting = true;\n    setTimeout(function(){ v.__obedRemounting = false; }, 0);\n  }\n"

_CORE_TRACE_TRANSFORMS: tuple[tuple[str, str], ...] = (
    ("  let disabled = false;\n  let everPreserved = false;\n",
     _TRACE_HELPERS + "  let disabled = false;\n  let everPreserved = false;\n"),
    ("  function stash(v, why", _STASH_TRACE),
    ("  function scheduleRemount(v, why) {\n", _SCHEDULE_TRACE),
    ("  function tryRemount(v, epoch) {\n", _TRY_REMOUNT_TRACE),
    (_BEGIN_MOVE,
     "  function beginMove(v) {\n    v.__obedRemounting = true;\n    __obedTrace('beginMove', v, {by: __obedCaller()});\n"
     "    setTimeout(function(){ v.__obedRemounting = false; __obedTrace('remounting-clear', v); }, 0);\n  }\n"),
    ("  function retireDecoder(v) {\n",
     "  function retireDecoder(v) {\n    __obedTrace('retireDecoder', v, {by: __obedCaller()});\n"),
)

_A2_FALLBACK = r"""  function tryRemount(v, epoch) {
    __obedPlaceRemount(v, epoch);
    if (!v || disabled || suppressRemount || v.isConnected) return;
    if (v.__obedRemountEpoch === -1 || v.ended || v.__obedGen === -1 || v.__obedFacadeFor) return;
    if (epoch != null && epoch !== remountEpoch) return;
    if (held.indexOf(v) < 0 && !isPooled(v)) return;
    if (zoneMode(v) !== 'allow') return;
    __obedRemountStageOverlay(v);
  }
  function __obedRemountStageOverlay(v) {
    const map = stageMap();
    const rest = restingRect(v);
    const last = v.__obedRect && v.__obedRect.w > 1 && v.__obedRect.h > 1 ? v.__obedRect : null;
    const box = rest && map ? toScreen(rest, map) : last;
    if (!box) {
      note('remount-fallback-none', {elId: v.__obedElId});
      return;
    }
    const stage = document.getElementById('body') || document.querySelector('[class*="stage"]') || document.body;
    if (!stage) {
      note('remount-no-stage', {elId: v.__obedElId});
      return;
    }
    try {
      v.__obedRect = box;
      v.style.position = 'absolute';
      v.style.left = box.x + 'px';
      v.style.top = box.y + 'px';
      v.style.width = box.w + 'px';
      v.style.height = box.h + 'px';
      v.style.visibility = 'visible';
      v.style.display = 'block';
      v.style.opacity = '1';
      if (/^-?\d+$/.test(String(v.__obedZ))) {
        v.style.zIndex = String(v.__obedZ);
      } else {
        v.style.removeProperty('z-index');
      }
      v.style.pointerEvents = 'none';
      if (v.__obedId && !document.getElementById(v.__obedId)) v.id = v.__obedId;
      beginMove(v);
      stage.appendChild(v);
      if (v.paused && !v.ended) {
        const p = v.play();
        if (p && p.catch) p.catch(function(){});
      }
      v.dataset.obedRemounted = '1';
      note('remount-fallback-stage', {
        elId: v.__obedElId, rect: box, fromRest: !!(rest && map), inDocument: document.contains(v)
      });
    } catch (e) {
      note('remount-error', {elId: v.__obedElId, message: String(e && e.message || e)});
    }
  }
  function __obedPlaceRemount(v, epoch) {
"""

_CORE_FIX_TRANSFORMS: dict[str, tuple[tuple[str, str], ...]] = {
    # The detach observer treats a removed decoder as a self-move only while it is still connected at delivery; a
    # disconnected one is always stashed, past the `__obedRemounting` time-window guard (kept for every other caller).
    "a1": (
        ("  function stash(v, why) {\n", "  function stash(v, why, detached) {\n"),
        ("    if (v.__obedRemounting) return;\n", "    if (v.__obedRemounting && !detached) return;\n"),
        ("          stash(node, 'preserve-on-detach');\n", "          stash(node, 'preserve-on-detach', !node.isConnected);\n"),
        ("            stash(v, 'preserve-on-detach-subtree');\n",
         "            stash(v, 'preserve-on-detach-subtree', !v.isConnected);\n"),
    ),
    # tryRemount never returns with a pooled or held decoder disconnected: when placement leaves it out of the
    # document, fall back to the stage overlay at its resting rect (or its last screen rect without a stage map).
    "a2": (("  function tryRemount(v, epoch) {\n", _A2_FALLBACK),),
}


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


def level2_install_bytes(install: bytes | None = None) -> bytes:
    """The player observation hook with the controller exposed as `window.__obedDebugController` (plan §1 L2a)."""
    install = live_runtime._INSTALL if install is None else install
    if install.count(L2_INSTALL_ANCHOR) != 1:
        raise ValueError("the live_runtime install hook anchor is missing or ambiguous")
    return install.replace(L2_INSTALL_ANCHOR, L2_INSTALL_REPLACEMENT)


@contextmanager
def level2_install() -> Iterator[None]:
    original = live_runtime._INSTALL
    live_runtime._INSTALL = level2_install_bytes(original)
    try:
        yield
    finally:
        live_runtime._INSTALL = original


def served_sha256(player: bytes, variant: str, level2: bool = False) -> str:
    with ExitStack() as stack:
        stack.enter_context(serving(variant))
        if level2:
            stack.enter_context(level2_install())
        return hashlib.sha256(live_runtime.patch_player(player, mm_opacity=variant != "off")).hexdigest()


def expected_served_sha256(variant: str, level2: bool = False) -> str | None:
    return (L2_SERVED_SHA256 if level2 else SERVED_SHA256).get(variant)


def transform_core(core: str, label: str, transforms: Sequence[tuple[str, str]]) -> str:
    """`core` with each anchor replaced; `ValueError` unless every anchor occurs exactly once."""
    for anchor, replacement in transforms:
        count = core.count(anchor)
        if count != 1:
            raise ValueError(f"core {label}: anchor {anchor.strip()[:80]!r} occurs {count} times, expected exactly once")
        core = core.replace(anchor, replacement)
    return core


def experiment_core(fix: str | None = None, trace: bool = False, core: str = PRESERVE_CORE_JS) -> str:
    """The core this run serves: the fix candidate's transforms first, then the trace wraps (identical in every arm)."""
    if fix is not None:
        if fix not in CORE_FIXES:
            raise ValueError(f"unknown core fix {fix!r}; expected one of {CORE_FIXES}")
        core = transform_core(core, fix, _CORE_FIX_TRANSFORMS[fix])
    if trace:
        core = transform_core(core, "trace", _CORE_TRACE_TRANSFORMS)
    return core


def experiment_core_sha(fix: str | None = None, trace: bool = False) -> str:
    return hashlib.sha256(experiment_core(fix, trace).encode()).hexdigest()


@contextmanager
def injected_core(fix: str | None, trace: bool) -> Iterator[str]:
    """Serve `experiment_core(fix, trace)` from this process's host (as the probe's `injected_core_variant`); yields its sha."""
    host = probe.live_host_module
    core = experiment_core(fix, trace)
    sha = hashlib.sha256(core.encode()).hexdigest()
    original_core, original_sha = host.PRESERVE_CORE_JS, host.js_sha256
    host.PRESERVE_CORE_JS, host.js_sha256 = core, (lambda: sha)
    try:
        yield sha
    finally:
        host.PRESERVE_CORE_JS, host.js_sha256 = original_core, original_sha


def parse_arm(label: str) -> tuple[str, str | None]:
    """`"V8+a1"` -> `("V8", "a1")`; `"V5+8"` -> `("V5+8", None)`."""
    match = FIX_ARM_RE.match(label)
    serving_name, fix = (match["serving"], match["fix"]) if match else (label, None)
    if serving_name not in VARIANT_INDICES:
        raise ValueError(f"unknown arm {label!r}: serving {serving_name!r} is not one of {tuple(VARIANT_INDICES)}")
    return serving_name, fix


def arm_label(variant: str, fix: str | None) -> str:
    return f"{variant}+{fix}" if fix else variant


def instrumented_sampler_js(control: dict[str, Any] | None = None, sampler: str | None = None, level2: bool = False) -> str:
    """The probe's sampler with the frame time recorded per tick and the sentinel toggled, preceded by the
    Level 1 instrument (and an optional control injection), and with `level2`, the Level 2 page wraps."""
    sampler = probe.SAMPLER_JS if sampler is None else sampler
    for anchor in (_TICK_ANCHOR, _PUSH_ANCHOR):
        if sampler.count(anchor) != 1:
            raise ValueError(f"sampler anchor missing or ambiguous: {anchor!r}")
    sampler = sampler.replace(_TICK_ANCHOR, _TICK_REPLACEMENT).replace(_PUSH_ANCHOR, _PUSH_REPLACEMENT)
    cfg = {"control": control, "level2": True} if level2 else {"control": control}
    return INSTRUMENT_JS.replace("__CFG__", json.dumps(cfg)) + (LEVEL2_JS if level2 else "") + sampler


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
def instrumented(sink: dict[str, Any], control: dict[str, Any] | None = None, level2: bool = False) -> Iterator[None]:
    """Install the instrument through the probe's own sampler seam and read it back before the host stops."""
    original_js, original_drive = probe.SAMPLER_JS, probe.drive_and_sample

    def drive(player: Any, **kwargs: Any) -> list[dict[str, Any]]:
        samples = original_drive(player, **kwargs)
        sink["samples"] = trim_samples(samples)
        sink["output"] = {key: player.output.get(key) for key in ("mmOpacity", "continuity", "viewport")}
        sink.update(player._require_transport().evaluate(INSTRUMENT_READ_JS) or {})
        return samples

    probe.SAMPLER_JS = instrumented_sampler_js(control, original_js, level2)
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
            "tMmSetup": samples[runs[m - 1]["i"]]["t"], "tMmIdle": samples[runs[before]["i"]]["t"] if mm_click else None,
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
    first_paint = next((row for row in prepaint if row["t"] >= jump["tPlay"]), None)
    pin_paint = next((pin for pin in (first_paint or {}).get("pins") or [] if pin.get("atScene") == jump["scene"]), None)
    return {
        **{key: jump.get(key) for key in ("scene", "mmScene", "waited", "mmWaited", "mmClick", "idleMs", "mmMs", "tSetup", "tPlay",
                                          "tMmSetup", "tMmIdle")},
        "r8Engaged": not jump["waited"],
        "eligible": bool(tracked) and carried, "tracked": sorted(tracked), "carried": carried,
        "firstPlaying": first_playing,
        "sampleEmptyRuns": sample_empty, "prepaintEmptyRuns": paint_empty,
        "sampleDecoderAbsentRuns": sample_decoder, "prepaintDecoderAbsentRuns": paint_decoder,
        "blinkSamples": blink_samples, "blinkPrepaint": blink_prepaint, "blink": blink_samples and blink_prepaint,
        "blinkDecoder": bool(sample_decoder) and bool(paint_decoder),
        "severity": severity,
        "pinPaint": None if pin_paint is None else {
            "t": first_paint["t"], "top": pin_paint.get("top"), "videoAt": pin_paint.get("videoAt"),
            "decoderAtPin": bool(tracked.intersection(pin_paint.get("videoAt") or [])),
        },
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


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _between(row: dict[str, Any], lo: dict[str, Any] | None, hi: dict[str, Any]) -> bool:
    """`row` lies after `lo` (exclusive; None = open) and before the I2 row `hi`: by the shared Level 2 sequence when
    all carry one (the core's observer is delivered before I2's, so its rows precede `hi`), else by time, (lo.t, hi.t]."""
    seqs = [_num(r.get("seq")) for r in (row, hi) + ((lo,) if lo is not None else ())]
    if all(s is not None for s in seqs):
        return (lo is None or seqs[0] > seqs[2]) and seqs[0] < seqs[1]
    t = _num(row.get("t"))
    return t is not None and (lo is None or t > lo["t"]) and t <= hi["t"]


def _after(row: dict[str, Any], lo: dict[str, Any] | None, hi: dict[str, Any] | None) -> bool:
    """`row` lies after `lo` (exclusive) and no later than `hi` (None = open), by sequence when both ends have one."""
    t, s = _num(row.get("t")), _num(row.get("seq"))
    if t is None:
        return False
    if lo is not None:
        ls = _num(lo.get("seq"))
        if (s <= ls) if (s is not None and ls is not None) else (t <= lo["t"]):
            return False
    if hi is not None:
        hs = _num(hi.get("seq"))
        if (s >= hs) if (s is not None and hs is not None) else (t > hi["t"]):
            return False
    return True


def note_el_ids(note: dict[str, Any]) -> set[Any]:
    detail = note.get("detail")
    if not isinstance(detail, dict):
        return set()
    ids = {detail.get("elId"), detail.get("oldElId")} | set(detail.get("elIds") or [])
    return {i for i in ids if i is not None}


def stash_reason(row: dict[str, Any]) -> str:
    """Why a traced `stash` call pooled (`pooled`) or returned silently, mirroring the core's guard order."""
    if row.get("why") in (row.get("noted") or []):
        return "pooled"
    pre = row.get("pre")
    if not isinstance(pre, dict):
        return "not-video"
    gen, generation = pre.get("gen"), pre.get("generation")
    checks = (
        ("disabled", pre.get("disabled")),
        ("remounting", pre.get("remounting") and pre.get("detached") is not True),
        ("bridged34", pre.get("bridged34")),
        ("suppressed34", pre.get("suppressed34")),
        ("facade", pre.get("facade")),
        ("retired", gen == -1),
        ("stale-gen", isinstance(generation, int) and (gen or 0) < generation),
        ("no-key", not pre.get("assetKey")),
        ("not-plan-asset", not pre.get("planAsset")),
        ("zone-refused", "preserve-refused" in (row.get("noted") or [])),
        ("not-poolable", not pre.get("poolable")),
        ("not-ready", not ((pre.get("readyState") or 0) >= 2 or (pre.get("currentTime") or 0) > 0.05)),
    )
    return next((name for name, hit in checks if hit), "unknown")


def _gap_stash(el: Any, prev: dict[str, Any] | None, removal: dict[str, Any], trace: list[dict[str, Any]],
               notes: list[dict[str, Any]]) -> tuple[str, str]:
    """(outcome, basis) of the core's `stash` for the removal: the trace row when there is one, else the core notes
    (a `preserve-on-detach*` note = pooled), else inferred from the I2 row's `__obedRemounting`."""
    rows = [r for r in trace if r.get("kind") == "stash" and r.get("elId") == el and DETACH_WHY_RE.match(str(r.get("why")))
            and _between(r, prev, removal)]
    if rows:
        return stash_reason(rows[-1]), "trace"
    if trace:
        return "unseen", "trace"
    if any(DETACH_WHY_RE.match(str(n.get("kind"))) and el in note_el_ids(n) and _between(n, prev, removal) for n in notes):
        return "pooled", "notes"
    return ("remounting" if removal.get("remounting") else "unseen"), "inferred"


def _compact(row: dict[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    return {key: row[key] for key in ("seq", "t", "rafTs", "kind", *keys) if key in row}


def classify_gap(
    lifecycle: list[dict[str, Any]], index: int, *, prepaint: list[dict[str, Any]], notes: list[dict[str, Any]],
    trace: list[dict[str, Any]], l2rows: list[dict[str, Any]], w0: float,
) -> dict[str, Any]:
    """Plan §4 step 3 for one I2 removal that left a tracked decoder disconnected at delivery (a detach gap).

    Rule, in order:
      H4  the removal is a core remover's: a retire note / traced `retireDecoder` naming the decoder in the removal's
          delivery, a `dom-swap` note there (the stub swap took it out), or a Level 2 remover stack through
          retireDecoder / retireVictims / bindFacade.
      H1  the core's detach `stash` returned on the `__obedRemounting` self-move guard (trace; or, without the trace,
          no `preserve-on-detach*` note for the decoder in that delivery and the I2 row reads `remounting`).
      H2  the stash pooled it and scheduled a detach remount, yet it stayed disconnected (tryRemount bailed).
      H3  any of H1/H2/unknown above, after an earlier removal of the same decoder inside the jump window that was
          re-homed (connected at its delivery, or a connected add before this removal): re-homed, then removed again.
          `then` names the second removal's branch.
      unknown  anything else (another stash guard, pooled but never scheduled, no evidence), with the reason.
    """
    removal = lifecycle[index]
    el = removal.get("elId")
    prev = next((row for row in reversed(lifecycle[:index]) if row.get("elId") == el), None)
    readd = next((row for row in lifecycle[index + 1:]
                  if row.get("elId") == el and row.get("op") == "add" and row.get("isConnected")), None)
    retire = [n for n in notes if n.get("kind") in RETIRE_NOTES and el in note_el_ids(n) and _between(n, prev, removal)]
    retire += [r for r in trace if r.get("kind") == "retireDecoder" and r.get("elId") == el and _between(r, prev, removal)]
    swap = [n for n in notes if n.get("kind") == "dom-swap" and el in note_el_ids(n) and _between(n, prev, removal)]
    removers = [r for r in l2rows if str(r.get("kind")).startswith("dom-") and el in (r.get("elIds") or [])
                and _between(r, prev, removal)]
    remover = removers[-1] if removers else None
    core_remover = next((name for name in CORE_REMOVERS for frame in (remover or {}).get("by") or []
                         if name in str(frame)), None)
    stash, basis = _gap_stash(el, prev, removal, trace, notes)
    scheduled = [n for n in notes if n.get("kind") == "remount-scheduled" and el in note_el_ids(n)
                 and DETACH_WHY_RE.match(str((n.get("detail") or {}).get("why"))) and _after(n, prev, readd)]
    tries = [r for r in trace if r.get("kind") == "tryRemount" and r.get("elId") == el and _after(r, prev, readd)]
    if retire or swap or core_remover:
        base = "H4"
        reason = "retire" if retire else "dom-swap" if swap else f"remover {core_remover}"
    elif stash == "remounting":
        base, reason = "H1", f"stash returned on __obedRemounting ({basis})"
    elif stash == "pooled" and scheduled:
        base, reason = "H2", "pooled and scheduled, still disconnected"
    elif stash == "pooled":
        base, reason = "unknown", "pooled, no detach remount scheduled"
    else:
        base, reason = "unknown", f"stash {stash} ({basis})"
    earlier = [
        (i, row) for i, row in enumerate(lifecycle[:index])
        if row.get("elId") == el and row.get("op") == "remove" and _num(row.get("t")) is not None and row["t"] >= w0
    ]
    prior = next((
        row for i, row in earlier
        if row.get("isConnected") or any(r.get("elId") == el and r.get("op") == "add" and r.get("isConnected")
                                         for r in lifecycle[i + 1:index])
    ), None)
    hypothesis = "H3" if prior is not None and base != "H4" else base
    t1 = readd["t"] if readd is not None else None
    paints = [p for p in prepaint if p["t"] > removal["t"] and (t1 is None or p["t"] < t1)]
    span_end = (t1 if t1 is not None else removal["t"]) + 5.0
    return {
        "hypothesis": hypothesis, "then": base if hypothesis == "H3" else None, "reason": reason, "basis": basis,
        "elId": el, "t0": removal["t"], "t1": t1, "gapMs": None if t1 is None else round(t1 - removal["t"], 3),
        "rafTs": removal.get("rafTs"), "paintsInGap": len(paints),
        "removal": _compact(removal, ("op", "direct", "isConnected", "remounting", "parentId", "layerId")),
        "readd": None if readd is None else _compact(readd, ("op", "parentId", "layerId")),
        "prior": None if prior is None else {
            **_compact(prior, ("isConnected", "parentId", "layerId")),
            "sameFrame": prior.get("rafTs") == removal.get("rafTs"), "beforeMs": round(removal["t"] - prior["t"], 3),
        },
        "stash": stash, "remover": None if remover is None else _compact(remover, ("kind", "parentId", "layerId", "by")),
        "scheduled": len(scheduled),
        "tryRemount": [_compact(r, ("after", "state", "noted", "parentId", "layerId")) for r in tries],
        "player": [_compact(r, ("scene", "videos", "from", "to")) for r in l2rows
                   if r.get("kind") in PLAYER_CONTEXT_KINDS and removal["t"] - PLAYER_CONTEXT_MS <= r["t"] <= span_end],
    }


def classify_event(event: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """Every detach gap of the event's tracked decoders inside its jump window, and for a blink (document or
    decoder), the hypothesis of the gap that covers the first pre-paint hole."""
    instrument = raw.get("instrument") or {}
    lifecycle = _rows(instrument.get("lifecycle"))
    prepaint = _rows(instrument.get("prepaint"))
    notes = _rows(raw.get("coreEvents"))
    trace = _rows(raw.get("coreTrace"))
    l2rows = _rows((raw.get("level2") or {}).get("rows"))
    tracked = set(event.get("tracked") or [])
    w0, w1 = event["tSetup"] - JUMP_PAD_MS, event["tPlay"] + CARRY_WINDOW_MS
    gaps = [
        classify_gap(lifecycle, i, prepaint=prepaint, notes=notes, trace=trace, l2rows=l2rows, w0=w0)
        for i, row in enumerate(lifecycle)
        if row.get("op") == "remove" and row.get("elId") in tracked and not row.get("isConnected")
        and _num(row.get("t")) is not None and w0 <= row["t"] <= w1
    ]
    holes = event.get("prepaintEmptyRuns") if event.get("blink") else (
        event.get("prepaintDecoderAbsentRuns") if event.get("blinkDecoder") else None)
    out: dict[str, Any] = {"blink": bool(event.get("blink")), "blinkDecoder": bool(event.get("blinkDecoder")),
                           "gaps": gaps, "hypothesis": None, "then": None, "reason": None, "basis": None}
    if not holes:
        return out
    start = holes[0]["t0"]
    covering = next((g for g in gaps if g["t0"] < start and (g["t1"] is None or g["t1"] > start)), None)
    if covering is None:
        out.update(hypothesis="unknown", reason="no detach gap of a tracked decoder covers the first pre-paint hole")
    else:
        out.update({key: covering[key] for key in ("hypothesis", "then", "reason", "basis")})
    return out


def _delivery(row: dict[str, Any]) -> Any:
    return row.get("delivery", row.get("t"))


def removal_gap(lifecycle: list[dict[str, Any]], index: int, prepaint: list[dict[str, Any]],
                notes: list[dict[str, Any]]) -> dict[str, Any]:
    """One I2 removal of a tracked decoder. `sameDelivery`: connected at its own I2 delivery (the core's observer,
    delivered first, put it back). `sameCheckpoint`: back before the microtask checkpoint ended, so no frame could paint
    without it: observed by the instrument's post-round microtask (`connectedAfterRound`); on older dumps a proxy (the
    re-add is the next I2 delivery, in the same frame, with no pre-paint row between)."""
    removal = lifecycle[index]
    el = removal.get("elId")
    if removal.get("isConnected"):
        return {"t": removal["t"], "sameDelivery": True, "sameCheckpoint": True, "basis": "delivery", "gapMs": 0.0,
                "paintsInGap": 0, "domSwapAfterMs": None}
    at = next((i for i in range(index + 1, len(lifecycle)) if lifecycle[i].get("elId") == el
               and lifecycle[i].get("op") == "add" and lifecycle[i].get("isConnected")), None)
    readd = lifecycle[at] if at is not None else None
    paints = None if readd is None else sum(removal["t"] < p["t"] < readd["t"] for p in prepaint)
    if "connectedAfterRound" in removal:
        same, basis = bool(removal["connectedAfterRound"]), "observed"
    else:
        ends = {_delivery(removal), None if readd is None else _delivery(readd)}
        same = readd is not None and paints == 0 and removal.get("rafTs") == readd.get("rafTs") and all(
            _delivery(row) in ends for row in lifecycle[index + 1:at])
        basis = "proxy"
    swap = None if readd is None else next((n["t"] for n in notes if n.get("kind") == "dom-swap" and el in note_el_ids(n)
                                            and removal["t"] <= n["t"] <= readd["t"]), None)
    return {"t": removal["t"], "sameDelivery": False, "sameCheckpoint": same, "basis": basis,
            "gapMs": None if readd is None else round(readd["t"] - removal["t"], 3), "paintsInGap": paints,
            "domSwapAfterMs": None if swap is None else round(swap - removal["t"], 3)}


def removal_phases(event: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    """Every removal of the event's tracked decoders in its window, split at the carry (the decoder's first
    `reuse-decoder` note in the window): `teardown` = delivered before it (the H3 removal), `carry` = from it on. Per
    phase: all re-homed in the same delivery / the same checkpoint, the longest wall-clock gap and the paints in gaps."""
    instrument = raw.get("instrument") or {}
    lifecycle = _rows(instrument.get("lifecycle"))
    prepaint = _rows(instrument.get("prepaint"))
    notes = _rows(raw.get("coreEvents"))
    w0, w1 = event["tSetup"] - JUMP_PAD_MS, event["tPlay"] + CARRY_WINDOW_MS
    gaps: dict[str, list[dict[str, Any]]] = {"teardown": [], "carry": []}
    for el in event.get("tracked") or []:
        carry_t = min((n["t"] for n in notes if n.get("kind") == "reuse-decoder" and (n.get("detail") or {}).get("oldElId") == el
                       and _num(n.get("t")) is not None and w0 <= n["t"] <= w1), default=None)
        for i, row in enumerate(lifecycle):
            if row.get("op") == "remove" and row.get("elId") == el and _num(row.get("t")) is not None and w0 <= row["t"] <= w1:
                phase = "carry" if carry_t is not None and row["t"] >= carry_t else "teardown"
                gaps[phase].append(removal_gap(lifecycle, i, prepaint, notes))
    out: dict[str, Any] = {}
    for phase, rows in gaps.items():
        if not rows:
            out[phase] = None
            continue
        spans = [g["gapMs"] for g in rows]
        out[phase] = {
            "removals": len(rows), "sameDelivery": all(g["sameDelivery"] for g in rows),
            "sameCheckpoint": all(g["sameCheckpoint"] for g in rows),
            "basis": sorted({g["basis"] for g in rows if not g["sameDelivery"]}) or ["delivery"],
            "gapMs": None if None in spans else max(spans),
            "paintsInGap": sum(g["paintsInGap"] or 0 for g in rows),
            "domSwapAfterMs": max((g["domSwapAfterMs"] for g in rows if g["domSwapAfterMs"] is not None), default=None),
        }
    return out


def new_removal_tally() -> dict[str, Any]:
    return {phase: {"events": 0, "sameDelivery": 0, "sameCheckpoint": 0, "paintsInGap": 0, "gapMsMax": None, "basis": []}
            for phase in ("teardown", "carry")}


def bump_removals(tally: dict[str, Any], removals: Any) -> None:
    for phase, cell in tally.items():
        row = (removals or {}).get(phase) if isinstance(removals, dict) else None
        if not row:
            continue
        cell["events"] += 1
        cell["sameDelivery"] += int(row["sameDelivery"])
        cell["sameCheckpoint"] += int(row["sameCheckpoint"])
        cell["paintsInGap"] += row["paintsInGap"]
        if row["gapMs"] is not None:
            cell["gapMsMax"] = row["gapMs"] if cell["gapMsMax"] is None else max(cell["gapMsMax"], row["gapMs"])
        cell["basis"] = sorted(set(cell["basis"]) | set(row["basis"]))


def removal_readout(arm: str, tally: dict[str, Any]) -> str:
    """`V8+a1: teardown sameDelivery 23/23; carry sameDelivery 0/23, sameCheckpoint 23/23 (proxy); pre-paint in gap 0`."""
    parts = []
    for phase, cell in tally.items():
        n = cell["events"]
        basis = [b for b in cell["basis"] if b != "delivery"]
        text = f"{phase} sameDelivery {cell['sameDelivery']}/{n}"
        if cell["sameDelivery"] < n:
            text += f", sameCheckpoint {cell['sameCheckpoint']}/{n} ({'+'.join(basis)}), gapMs max {cell['gapMsMax']}"
        parts.append(text)
    paints = sum(cell["paintsInGap"] for cell in tally.values())
    return f"{arm}: {'; '.join(parts)}; pre-paint in gap {paints}"


def serving_of(config: dict[str, Any]) -> Any:
    return config.get("serving") or config.get("variant")


def r8_preload_seen(level2: dict[str, Any], jumps: Sequence[dict[str, Any]]) -> list[bool | None]:
    """Per post-MM jump: did the player issue R8's preload of the jump's scene (`loadScene` from `preloadTextures`,
    the scene before it a Magic Move) before the MM's setup? None when the page wraps installed after the MM's idle began."""
    rows = [r for r in _rows(level2.get("rows")) if r.get("kind") == "loadScene"]
    installed = _num(level2.get("installedAt"))
    out: list[bool | None] = []
    for jump in jumps:
        idle, setup = _num(jump.get("tMmIdle")), _num(jump.get("tMmSetup"))
        if installed is None or idle is None or setup is None or installed > idle:
            out.append(None)
            continue
        out.append(any(r.get("scene") == jump["scene"] and r.get("viaPreload") and r.get("prevIsMM")
                       and _num(r.get("t")) is not None and r["t"] < setup for r in rows))
    return out


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
        expect_waited = serving_of(config) not in R8_SERVINGS
        checked = [e for e in events if e["mmClick"]]
        wrong = [e["scene"] for e in checked if e["waited"] != expect_waited]
        reasons = [] if checked else ["no post-MM jump after a click MM"]
        reasons += [f"scene {scene}: waited != {expect_waited}" for scene in wrong]
        out = {"mode": mode, "expectWaited": expect_waited, "jumps": len(checked), "waited": [e["waited"] for e in checked]}
        if isinstance(raw.get("level2"), dict):
            seen = r8_preload_seen(raw["level2"], checked)
            judged = [(e["scene"], s) for e, s in zip(checked, seen) if s is not None]
            if not judged:
                reasons.append("level 2: no post-MM jump whose pre-MM idle followed the page wraps")
            reasons += [f"scene {scene}: level 2 R8 preload logged = {s}, expected {not expect_waited}"
                        for scene, s in judged if s != (not expect_waited)]
            out["l2Preload"] = seen
        out["status"] = "pass" if checked and not reasons else "fail"
        out["reasons"] = reasons
        return out
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
    expected = config.get("expectedServedSha256") or SERVED_SHA256.get(serving_of(config))
    expected_core = config.get("expectedCoreSha256") or CORE_SHA256
    arm = raw.get("arm") or {}
    stage_fit = arm.get("stageFit")
    record = {
        **{key: raw.get(key) for key in ("runId", "startedAt", "wallS", "meta", "error")},
        **config,
        "servedSha256": served, "expectedServedSha256": expected, "servedShaOk": served is not None and served == expected,
        "coreSha256": continuity.get("sha256"), "coreShaOk": continuity.get("sha256") == expected_core,
        "continuityMode": continuity.get("mode"),
        "stageFitOk": bool(stage_fit.get("verdict")) if isinstance(stage_fit, dict) else None,
        "rafStats": stats, "instrumentErrors": instrument.get("errors"),
        "events": events,
    }
    level2 = raw.get("level2")
    if isinstance(level2, dict) or config.get("level2"):
        level2 = level2 if isinstance(level2, dict) else {}
        record["level2Errors"] = level2.get("errors")
        record["level2Wrapped"] = level2.get("wrapped")
        record["coreTraceRows"] = len(_rows(raw.get("coreTrace")))
    for event in events:
        if event["eligible"]:
            event["removals"] = removal_phases(event, raw)
        if event["eligible"] and (event["blink"] or event["blinkDecoder"]):
            verdict = classify_event(event, raw)
            event["hypothesis"] = {key: verdict[key] for key in ("hypothesis", "then", "reason", "basis")}
    reasons = []
    if raw.get("error"):
        reasons.append(f"run error: {raw['error']}")
    if not record["servedShaOk"]:
        reasons.append(f"served player sha {served} != expected {expected}")
    if record["continuityMode"] != "qualified" or not record["coreShaOk"]:
        reasons.append(f"continuity {record['continuityMode']} core {record['coreSha256']}")
    if record["stageFitOk"] is False:
        reasons.append("stage fit failed")
    if config.get("level2") and (record.get("level2Errors") or record.get("level2Wrapped") is None or not record["coreTraceRows"]):
        reasons.append(f"level 2 instrument incomplete: errors {record.get('level2Errors')}, "
                       f"trace rows {record['coreTraceRows']}")
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
            "byPath": {}, "byPhase": {}, "byLoad": {}, "byDeck": {}, "byHypothesis": {}, "removals": new_removal_tally(),
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
            bump_removals(row["removals"], e.get("removals"))
            if e["blink"]:
                h = e.get("hypothesis") or {}
                name = f"{h.get('hypothesis')}>{h['then']}" if h.get("then") else h.get("hypothesis")
                row["byHypothesis"][str(name)] = row["byHypothesis"].get(str(name), 0) + 1
    tests = {
        f"V8vs{other}": fisher_one_sided(per["V8"]["blinks"], per["V8"]["events"], per[other]["blinks"], per[other]["events"])
        for other in sorted(per) if "V8" in per and other != "V8"
    }
    arms = set(BLOCK_VARIANTS) if set(BLOCK_VARIANTS) <= set(per) else set(per)
    complete = sum(1 for variants in blocks.values() if arms <= variants)
    return {"readout": [removal_readout(arm, row["removals"]) for arm, row in sorted(per.items())],
            "statuses": statuses, "completeBlocks": complete, "perVariant": per, "fisherOneSided": tests,
            "decision": decide(per, complete)}


def decide(per: dict[str, dict[str, Any]], complete_blocks: int) -> str:
    """§2.3 on the R8 A/B; on a fix A/B (V8 against V8+fix arms) only whether every arm reached the target."""
    fix_arms = [arm for arm in per if FIX_ARM_RE.match(arm)]
    if "V8" in per and fix_arms and not set(BLOCK_VARIANTS) <= set(per):
        return "target-met" if all(per[arm]["events"] >= TARGET_EVENTS for arm in ("V8", *fix_arms)) else "continue"
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
    control: dict[str, Any] | None = None, extra: dict[str, Any] | None = None, core_fix: str | None = None,
    level2: bool = False,
) -> dict[str, Any]:
    """One live arm under the given serving, core and instrument; writes the raw dump and appends the record."""
    fixture_dir, original_index = deck_paths(deck)
    config = {"deck": deck, "variant": arm_label(variant, core_fix), "serving": variant, "coreFix": core_fix,
              "level2": level2, "arm": arm, "viewport": list(viewport),
              "control": control["mode"] if control else None, "controlAtScene": control and control.get("atScene"),
              "expectedServedSha256": expected_served_sha256(variant, level2),
              "expectedCoreSha256": experiment_core_sha(core_fix, level2), **(extra or {})}
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
            if level2:
                stack.enter_context(level2_install())
            if core_fix or level2:
                stack.enter_context(injected_core(core_fix, level2))
            stack.enter_context(probe.env_override({probe.CONTINUITY_ENV: None}))
            stack.enter_context(instrumented(sink, control, level2))
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
                                     "invalid", "maxDtMs", "hypothesis", "removals")} | {"phase": (e.get("teardown") or {}).get("phase")}
        for e in record.get("events") or []
    ]
    if isinstance(brief.get("controlVerdict"), dict):
        brief["controlVerdict"] = {k: v for k, v in brief["controlVerdict"].items() if k != "control"}
    return brief


def _run_tag(args: argparse.Namespace) -> str:
    return _safe(arm_label(args.variant, args.core_fix)) + ("-L2" if args.level2 else "")


def cmd_run(args: argparse.Namespace) -> int:
    run_id = f"{datetime.now():%Y%m%dT%H%M%S}-{_run_tag(args)}-{args.deck}-{args.arm}"
    record = execute_run(args.out_dir, run_id, deck=args.deck, variant=args.variant, arm=args.arm, viewport=args.viewport,
                         core_fix=args.core_fix, level2=args.level2)
    print(json.dumps(_brief(record), indent=2, default=str))
    return 0 if record["status"] in DONE_STATUSES else 1


def cmd_control(args: argparse.Namespace) -> int:
    control = None if args.mode == "r8flag" else {"mode": args.mode, "atScene": args.at_scene}
    run_id = f"{datetime.now():%Y%m%dT%H%M%S}-ctl-{args.mode}-{_run_tag(args)}-{args.deck}-{args.arm}"
    record = execute_run(args.out_dir, run_id, deck=args.deck, variant=args.variant, arm=args.arm, viewport=args.viewport,
                         control=control, extra={"control": args.mode}, core_fix=args.core_fix, level2=args.level2)
    print(json.dumps(_brief(record), indent=2, default=str))
    verdict = record.get("controlVerdict") or {}
    return 0 if verdict.get("status") in ("pass", "recorded") else 1


def _manifest(args: argparse.Namespace) -> dict[str, Any]:
    path = args.out_dir / "blocks.json"
    wanted = {"blocks": args.blocks, "variants": args.variants, "decks": args.decks, "arm": args.arm,
              "viewport": list(args.viewport), "level2": args.level2}
    if path.exists():
        manifest = json.loads(path.read_text())
        if args.seed is not None and args.seed != manifest["seed"]:
            raise SystemExit(f"{path} has seed {manifest['seed']}, not {args.seed}")
        clash = {k: (manifest.get(k, False if k == "level2" else None), v) for k, v in wanted.items()
                 if k != "blocks" and manifest.get(k, False if k == "level2" else None) != v}
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
        level2 = bool(manifest.get("level2"))
        serving_name, fix = parse_arm(run["variant"])
        run_id = f"s{seed}-b{run['block']:02d}-{_safe(run['variant'])}{'-L2' if level2 else ''}-{run['deck']}-a{run['attempt']}"
        record = execute_run(
            args.out_dir, run_id, deck=run["deck"], variant=serving_name, arm=manifest["arm"],
            viewport=tuple(manifest["viewport"]), extra={"seed": seed, "block": run["block"], "attempt": run["attempt"],
                                                         "order": run["order"]},
            core_fix=fix, level2=level2,
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


def classification_rows(record: dict[str, Any], raw: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per eligible event of the run: its blink flags, hypothesis (blinks only) and every detach gap."""
    rows = []
    for event in record.get("events") or []:
        if not event.get("eligible"):
            continue
        verdict = classify_event(event, raw)
        rows.append({
            **{key: record.get(key) for key in ("runId", "variant", "serving", "coreFix", "level2", "deck", "block")},
            **{key: event.get(key) for key in ("scene", "waited", "blink", "blinkDecoder", "invalid", "removals")},
            "phase": (event.get("teardown") or {}).get("phase"), **verdict,
        })
    return rows


def tally_classification(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for row in rows:
        cell = out.setdefault(str(row.get("variant")), {"events": 0, "blinks": 0, "hypotheses": {}, "gapsAll": {},
                                                        "removals": new_removal_tally()})
        cell["events"] += 1
        bump_removals(cell["removals"], row.get("removals"))
        cell["blinks"] += int(bool(row.get("blink")))
        if row.get("blink"):
            name = f"{row['hypothesis']}>{row['then']}" if row.get("then") else str(row.get("hypothesis"))
            cell["hypotheses"][name] = cell["hypotheses"].get(name, 0) + 1
        for gap in row.get("gaps") or []:
            name = f"{gap['hypothesis']}>{gap['then']}" if gap.get("then") else str(gap.get("hypothesis"))
            key = f"{name}|{'painted' if gap.get('paintsInGap') else 'unpainted'}"
            cell["gapsAll"][key] = cell["gapsAll"].get(key, 0) + 1
    return out


def cmd_classify(args: argparse.Namespace) -> int:
    out_path = args.output or args.out_dir / "classify.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.unlink(missing_ok=True)
    rows: list[dict[str, Any]] = []
    for record in read_jsonl(args.out_dir / "runs.jsonl"):
        if record.get("status") != "ok" or (args.seed is not None and record.get("seed") != args.seed):
            continue
        raw_path = args.out_dir / "raw" / f"{record['runId']}.json.gz"
        if not raw_path.exists():
            continue
        with gzip.open(raw_path, "rt") as handle:
            raw = json.load(handle)
        for row in classification_rows(build_record(raw), raw):
            append_jsonl(out_path, row)
            rows.append(row)
    for row in rows:
        if row.get("blink"):
            print(json.dumps({key: row.get(key) for key in ("runId", "variant", "deck", "scene", "waited", "phase",
                                                             "hypothesis", "then", "reason", "basis")}, default=str))
    tally = tally_classification(rows)
    print(json.dumps(tally, indent=2, default=str))
    for arm, cell in sorted(tally.items()):
        print(removal_readout(arm, cell["removals"]))
    return 0


def cmd_rescore(args: argparse.Namespace) -> int:
    out = args.output or args.out_dir / "runs.rescored.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
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

    def bytes_options(p: argparse.ArgumentParser, fix: bool = True) -> None:
        p.add_argument("--level2", action="store_true", help="plan §1 Level 2: controller wraps and the core trace")
        if fix:
            p.add_argument("--core-fix", choices=CORE_FIXES, default=None, help="probe-only core fix candidate (plan §3)")

    run = sub.add_parser("run", help="one instrumented arm")
    live(run, "C")
    bytes_options(run)
    run.add_argument("--variant", choices=SERVINGS, required=True)
    run.add_argument("--deck", choices=DECKS, required=True)
    run.set_defaults(func=cmd_run)

    control = sub.add_parser("control", help="one §1 control run")
    live(control, "A")
    bytes_options(control)
    control.add_argument("--mode", choices=CONTROL_MODES, required=True)
    control.add_argument("--variant", choices=SERVINGS, default="V8")
    control.add_argument("--deck", choices=DECKS, default="D4")
    control.add_argument("--at-scene", type=int, default=None, help="fire at this pin boundary (default: the first)")
    control.set_defaults(func=cmd_control)

    blocks = sub.add_parser("blocks", help="the interleaved A/B, resumable (arms: V8, V7, V5, V5+8, or V8+a1 / V8+a2)")
    live(blocks, "C")
    bytes_options(blocks, fix=False)
    blocks.add_argument("--blocks", type=int, required=True)
    blocks.add_argument("--seed", type=int, default=None)
    blocks.add_argument("--variants", type=lambda s: s.split(","), default=list(BLOCK_VARIANTS))
    blocks.add_argument("--decks", type=lambda s: s.split(","), default=list(BLOCK_DECKS))
    blocks.add_argument("--max-attempts", type=int, default=3)
    blocks.add_argument("--no-stop-rules", dest="stop_rules", action="store_false")
    blocks.set_defaults(func=cmd_blocks)

    for name, func in (("summary", cmd_summary), ("rescore", cmd_rescore), ("classify", cmd_classify)):
        p = sub.add_parser(name)
        p.add_argument("--out-dir", type=Path, required=True)
        p.add_argument("--seed", type=int, default=None)
        if name != "summary":
            default = "classify.jsonl" if name == "classify" else "runs.rescored.jsonl"
            p.add_argument("--output", type=Path, default=None, help=f"default: <out-dir>/{default}")
        p.set_defaults(func=func)

    args = parser.parse_args(argv)
    if args.command == "blocks":
        bad = [d for d in args.decks if d not in DECKS]
        for label in args.variants:
            try:
                parse_arm(label)
            except ValueError:
                bad.append(label)
        if bad:
            parser.error(f"unknown variants/decks: {bad}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
