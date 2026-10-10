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

SAMPLER_SCHEMA = 2
PAINT_OPACITY_FLOOR = 0.02
PAINT_OPAQUE_MIN = 0.99
PAINT_CONTROL_VARIANTS = ("ancestor-opacity", "ancestor-half", "ancestor-display", "element-visibility")
PAINT_CONTROL_PHASES = ("settled", "bridge", "pin")
PAINT_CONTROL_TIMINGS = ("early", "late")

PAINTED, PARTIAL, UNPAINTED, UNREADABLE, NOT_PAINTER = "painted", "partial", "unpainted", "unreadable", "not-painter"
SEQ_LIST_CAP = 600
RUNS_CAP = 10

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
    if (paintSet(cs.rotate)) return true;
    var t = String(cs.transform || 'none');
    if (t === 'none') return false;
    var m = /^matrix\(([^)]*)\)$/.exec(t);
    if (!m) return true;
    var p = m[1].split(',').map(parseFloat);
    return p.length !== 6 || !p.every(isFinite) || p[1] !== 0 || p[2] !== 0;
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
    var refs = [], seen = new WeakSet(), currentSeq = null, currentTs = null, wide = false;
    function fail(where, e){ if (meta.errors.length < 50) meta.errors.push(where + ': ' + String(e && e.message || e)); }
    function track(v){ if (!seen.has(v)) { seen.add(v); refs.push(new WeakRef(v)); } }
    var host = document.createElement('div');
    host.style.cssText = 'position:fixed;left:-16px;top:-16px;width:8px;height:8px;overflow:hidden;opacity:0;pointer-events:none;';
    var sentinel = document.createElement('div');
    sentinel.style.cssText = 'display:block;width:1px;height:1px;';
    host.attachShadow({mode: 'closed'}).appendChild(sentinel);
    document.documentElement.appendChild(host);
    new ResizeObserver(function(){
      var t = performance.now();
      try {
        if (currentSeq === null) return;
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
        fail('prepaint', e);
      } finally {
        var cost = performance.now() - t;
        meta.readCostMs.sum += cost;
        if (cost > meta.readCostMs.max) meta.readCostMs.max = cost;
      }
    }).observe(sentinel);
    function toggle(seq, ts){
      currentSeq = seq;
      currentTs = ts;
      wide = !wide;
      sentinel.style.width = wide ? '2px' : '1px';
    }
    return {toggle: toggle, track: track};
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
    outside the stage is `outsideStagePx` in `score_paint`, never partial."""
    if not isinstance(pv, dict):
        return UNPAINTED, "absent"
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


def frame_coverage(rows: list[dict[str, Any]], *, max_gap_frames: int, min_fps: float) -> dict[str, Any]:
    """Carry-cover's rule on rAF timestamps: any delta over `(max_gap_frames + 0.5) × median period`, a cadence
    under `min_fps`, or a missing sampler row (a seq gap) fails coverage."""
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
        allowed = (max_gap_frames + 0.5) * period
        missed = [d for d in deltas if d > 1.5 * period]
        out.update(fps=round(1000.0 / period, 2), maxGapAllowedMs=round(allowed, 3),
                   missedFrames=sum(max(0, round(d / period) - 1) for d in missed),
                   missedMs=round(sum(d - period for d in missed), 3))
        if period > 1000.0 / min_fps:
            reasons.append(f"cadence {period:.1f} ms is slower than {min_fps:g} fps")
        if max(deltas) > allowed:
            reasons.append(f"frame gap {max(deltas):.1f} ms exceeds {allowed:.1f} ms")
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
    if pp.get("seq") != row.get("seq") or pp.get("ts") != row.get("ts"):
        return "pre-paint read of another frame"
    if not (_num(pp.get("t")) and _num(row.get("t")) and pp["t"] >= row["t"]):
        return "pre-paint read before the rAF read"
    if not isinstance(pp.get("videos"), list):
        return "pre-paint read without videos"
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
    asset_substr: str,
    *,
    start: float,
    end: float,
    slot_of: Callable[[dict[str, Any]], dict[str, float] | None],
    stage_box_of: Callable[[dict[str, Any]], dict[str, float] | None],
    rect_tolerance: float,
    iou_min: float,
    max_gap_frames: int,
    min_fps: float,
) -> dict[str, Any]:
    """Plan §2.4 over the rows with `start <= t <= end`. `slot_of`/`stage_box_of` and every `pv.rect`/`visibleRect`
    must share one coordinate space. An unobserved or unreadable frame, failed coverage or no rows is inconclusive
    whatever else the window shows; on complete evidence any violating frame fails."""
    window_rows = sorted((r for r in rows if _num(r.get("t")) and start <= r["t"] <= end), key=lambda r: r.get("seq") or 0)
    coverage = frame_coverage(window_rows, max_gap_frames=max_gap_frames, min_fps=min_fps)
    period = coverage.get("periodMs")
    asset = asset_substr.lower()
    violations: list[dict[str, Any]] = []
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
        slot, stage = _box(slot_of(row)), _box(stage_box_of(row))
        if stage is None:
            unreadable.append(dict(frame, reason="stage box"))
            continue
        if slot is None:
            violations.append(dict(frame, kind=UNPAINTED, reason="no-slot"))
            continue
        expected = _meet(slot, stage)
        cover = bool(row["pp"].get("cover"))
        carried_state: tuple[str, str | None] = (UNPAINTED, "absent")
        carried_pv: dict[str, Any] | None = None
        at_slot: list[dict[str, Any]] = []
        blind = False
        for pv in row["pp"]["videos"]:
            if not isinstance(pv, dict) or asset not in str(pv.get("src") or "").lower():
                continue
            state = painted_state(pv, cover=cover, expected=expected, stage=stage, rect_tolerance=rect_tolerance)
            mine = pv.get("id") == element_id
            near = _iou(_box(pv.get("rect")), slot) >= iou_min
            if mine:
                carried_state, carried_pv = state, pv
                if _num(pv.get("opacity")):
                    min_opacity = pv["opacity"] if min_opacity is None else min(min_opacity, pv["opacity"])
                if state[0] in (PAINTED, PARTIAL):
                    outside = max(outside, _area(_box(pv.get("visibleRect"))) - _area(_meet(_box(pv.get("visibleRect")), stage)))
            if state[0] == UNREADABLE and (mine or near):
                blind = True
                unreadable.append(dict(frame, reason=state[1], id=pv.get("id")))
            if state[0] in (PAINTED, PARTIAL) and near:
                at_slot.append(pv)
        if blind:
            continue
        ids = [pv.get("id") for pv in at_slot]
        if len(at_slot) >= 2:
            kind, reason = "double", f"ids {ids}"
        elif ids == [element_id]:
            if carried_state[0] == PAINTED:
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
    for key in ("overflow", "ppMismatch", "ppDuplicate"):
        value = meta.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            reasons.append(f"meta.{key} missing")
        elif value:
            reasons.append(f"meta.{key} = {value}")
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
    unreadable frame) are inconclusive. `redSet == [target]` is the caller's check."""
    reasons: list[str] = []
    blockers: list[str] = []
    paint = _paint_of(target_verdict)
    if not isinstance(record, dict):
        return {"status": "fail", "reasons": ["no control record"]}
    control = record.get("control") or {}
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
    if paint is None:
        reasons.append("target verdict has no paint score")
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
