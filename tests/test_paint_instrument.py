"""Unit tests for `scripts/paint_instrument.py`, the per-frame "painted" instrument
(plan `keynote_live_continuity_instrument.plan.md` §2, §3.1, §4, §6 "Stream A tests").

The Python half is exercised on synthetic rows. The JS half runs in Node against a small fake DOM
(computed styles, flat-tree parents, a ResizeObserver delivered once per rendering step, a rAF queue
with a microtask checkpoint after each callback) driven by a mini sampler that follows stream B's
frame contract: `seq++ -> control tick -> tick (push row, track, rAF-phase read) -> toggle`.
These prove logic only; the live V2 positive control proves the phase.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

REPO = Path(__file__).resolve().parent.parent
for sub in ("scripts", "src"):
    if str(REPO / sub) not in sys.path:
        sys.path.insert(0, str(REPO / sub))

import paint_instrument as pi  # noqa: E402
from test_live_continuity_js import _node_stdout  # noqa: E402

PERIOD = 1000.0 / 60
SLOT = {"x": 100.0, "y": 100.0, "w": 400.0, "h": 225.0}
STAGE = {"x": 0.0, "y": 0.0, "w": 1920.0, "h": 1080.0}
SCORE_KW = dict(rect_tolerance=3.0, iou_min=0.75, max_gap_frames=3, min_fps=20.0)


def _pv(id: int = 1, src: str = "movie-a.mov", **kw: Any) -> dict[str, Any]:
    base = dict(
        id=id, elId=10 + id, instance=None, src=src, connected=True, facade=False, suppressed=False,
        readyState=4, seeking=False, videoWidth=640, videoHeight=360, currentTime=1.0, paused=False, ended=False,
        checkVisibility=True, visibility="visible", displayNone=None, opacity=1.0, hiding=None, effects=None,
        transform=None, rect=dict(SLOT), visibleRect=dict(SLOT), clippedBy=None, parent="div#body", layer=None,
    )
    base.update(kw)
    return base


def _rows(n: int = 120, videos: Callable[[int], list[dict[str, Any]]] = lambda i: [_pv()],
          stage: dict[str, float] = STAGE) -> list[dict[str, Any]]:
    rows = []
    for i in range(1, n + 1):
        ts = i * PERIOD
        rows.append({"t": ts + 0.1, "seq": i, "ts": ts, "hash": "#1",
                     "pp": {"seq": i, "ts": ts, "t": ts + 0.5, "videos": videos(i), "stageBox": dict(stage), "cover": False}})
    return rows


# ---------------------------------------------------------------- painted_state truth table (§2.3)

TRUTH = [
    ("absent", None, {}, ("unpainted", "absent")),
    ("detached", _pv(connected=False), {}, ("unpainted", "detached")),
    ("facade-is-not-a-painter", _pv(facade=True), {}, ("not-painter", "facade")),
    ("suppressed", _pv(suppressed=True), {}, ("unpainted", "suppressed")),
    ("poster-readyState-1", _pv(readyState=1), {}, ("unpainted", "not-decoded")),
    ("zero-videoHeight", _pv(videoHeight=0), {}, ("unpainted", "not-decoded")),
    ("seeking", _pv(readyState=1, seeking=True), {}, ("unpainted", "seeking")),
    ("nan-opacity-is-unreadable", _pv(opacity=None), {}, ("unreadable", "opacity")),
    ("no-checkVisibility", _pv(checkVisibility=None), {}, ("unreadable", "checkVisibility")),
    ("effects", _pv(effects="div#layer3:filter"), {}, ("unreadable", "effects")),
    # Astra r1 #2: a rotated/skewed (or unmappable) box is not axis-aligned, so no rect read can be trusted.
    ("rotated-or-skewed-box", _pv(transform="div#clip"), {}, ("unreadable", "transform")),
    ("cover", _pv(), {"cover": True}, ("unreadable", "cover")),
    ("display", _pv(displayNone="div#layer104", checkVisibility=False), {}, ("unpainted", "display")),
    ("own-visibility-hidden", _pv(visibility="hidden", checkVisibility=False), {}, ("unpainted", "visibility")),
    # The prototype's bug: an ancestor's `visibility:hidden` (#stageArea) with the element's own value visible paints.
    ("ancestor-visibility-hidden-own-visible", _pv(visibility="visible"), {}, ("painted", None)),
    ("checkVisibility-false", _pv(checkVisibility=False), {}, ("unpainted", "checkVisibility")),
    ("opacity-at-floor", _pv(opacity=0.02, hiding={"node": "div#layer104"}), {}, ("unpainted", "opacity")),
    ("offscreen", _pv(visibleRect=None), {}, ("unpainted", "offscreen")),
    ("sliver", _pv(visibleRect={"x": 0, "y": 0, "w": 1, "h": 200}), {}, ("unpainted", "offscreen")),
    ("partial-opacity", _pv(opacity=0.5), {}, ("partial", "opacity")),
    ("near-opaque-paints", _pv(opacity=0.995), {}, ("painted", None)),
    ("clipped", _pv(visibleRect={**SLOT, "w": 200.0}),
     {"expected": SLOT, "stage": STAGE, "rect_tolerance": 3.0}, ("partial", "clipped")),
    ("painted", _pv(), {"expected": SLOT, "stage": STAGE, "rect_tolerance": 3.0}, ("painted", None)),
]


@pytest.mark.parametrize(("pv", "kw", "expected"), [t[1:] for t in TRUTH], ids=[t[0] for t in TRUTH])
def test_painted_state_truth_table(pv, kw, expected) -> None:
    assert pi.painted_state(pv, **kw) == expected


# ---------------------------------------------------------------- score_paint on synthetic rows (§2.4)

def _hide(lo: int, hi: int, **kw: Any) -> Callable[[int], list[dict[str, Any]]]:
    return lambda i: [_pv(**kw) if lo <= i <= hi else _pv()]


def _drop_pp(rows):
    rows[40]["pp"] = None
    return rows


def _wrong_pp(rows):
    rows[40]["pp"]["seq"] = rows[41]["seq"]
    return rows


def _gap(periods: float):
    def mutate(rows):
        for row in rows[60:]:
            row["ts"] += (periods - 1) * PERIOD
            row["t"] += (periods - 1) * PERIOD
            row["pp"]["ts"] = row["ts"]
            row["pp"]["t"] = row["t"] + 0.4
        return rows
    return mutate


ELSEWHERE = {"x": 1200.0, "y": 600.0, "w": 400.0, "h": 225.0}
LETTERBOX = {"x": 0.0, "y": 60.0, "w": 1920.0, "h": 960.0}
BLEED = {"x": 100.0, "y": 900.0, "w": 400.0, "h": 225.0}
BIG = {"x": 0.0, "y": 0.0, "w": 1200.0, "h": 700.0}

SCORE_CASES = [
    ("clean", _rows(), SLOT, {"status": "ok", "frames": 120, "unpaintedFrames": 0, "longestRun": 0}),
    # c1 geometry: the decoder sits in layer113, the player fades layer104 (its ancestor) to 0 for the Magic Move.
    ("c1-108-dark-frames", _rows(videos=_hide(10, 117, opacity=0.0, checkVisibility=False, parent="div#layer113",
                                               layer="layer113", hiding={"node": "div#layer104", "prop": "opacity", "value": 0})),
     SLOT, {"status": "fail", "unpaintedFrames": 108, "longestRun": 108, "unpaintedSeqs": list(range(10, 118)),
            "_hiding": "div#layer104", "_reason": "div#layer104: 108"}),
    ("14-detached-frames", _rows(videos=_hide(20, 33, connected=False)), SLOT,
     {"status": "fail", "unpaintedFrames": 14, "longestRun": 14, "_firstReason": "detached"}),
    ("partial-0.5", _rows(videos=lambda i: [_pv(opacity=0.5)]), SLOT,
     {"status": "fail", "partialFrames": 120, "unpaintedFrames": 0, "minOpacity": 0.5}),
    ("near-opaque-0.995", _rows(videos=lambda i: [_pv(opacity=0.995)]), SLOT, {"status": "ok", "minOpacity": 0.995}),
    ("same-asset-double", _rows(videos=lambda i: [_pv(), _pv(id=2)]), SLOT, {"status": "fail", "doubleFrames": 120}),
    ("d5-a-prime-elsewhere", _rows(videos=lambda i: [_pv(), _pv(id=2, rect=ELSEWHERE, visibleRect=ELSEWHERE)]), SLOT,
     {"status": "ok"}),
    ("other-asset-at-slot", _rows(videos=lambda i: [_pv(), _pv(id=2, src="movie-b.mov")]), SLOT, {"status": "ok"}),
    ("facade-at-slot", _rows(videos=lambda i: [_pv(), _pv(id=2, facade=True)]), SLOT, {"status": "ok"}),
    ("substitute", _rows(videos=lambda i: [_pv(id=2)]), SLOT,
     {"status": "fail", "substituteFrames": 120, "unpaintedFrames": 0}),
    ("clipped-vs-slot-and-stage", _rows(videos=lambda i: [_pv(visibleRect={**SLOT, "w": 200.0})]), SLOT,
     {"status": "fail", "partialFrames": 120, "_firstReason": "clipped"}),
    ("slot-legitimately-clipped-by-the-stage",
     _rows(videos=lambda i: [_pv(rect=BLEED, visibleRect={**BLEED, "h": 120.0})], stage=LETTERBOX), BLEED,
     {"status": "ok", "outsideStagePx": 0.0}),
    # A held decoder on #body escapes #stageArea's clip: reported, never gated (owner decision 13).
    ("held-decoder-over-the-letterbox", _rows(videos=lambda i: [_pv(rect=BLEED, visibleRect={**BLEED, "h": 180.0})],
                                              stage=LETTERBOX), BLEED,
     {"status": "ok", "outsideStagePx": 400.0 * 60.0}),
    ("missing-pp", _drop_pp(_rows()), SLOT, {"status": "inconclusive", "_reason": "unobserved"}),
    # Astra r4: readability is established before any classification, the no-slot short circuit included.
    ("no-slot-readable-stays-red", _rows(), None, {"status": "fail", "unpaintedFrames": 120, "_firstReason": "no-slot"}),
    ("no-slot-with-an-unreadable-decoder", _rows(videos=lambda i: [_pv(transform="div#x")]), None,
     {"status": "inconclusive", "unpaintedFrames": 0, "_reason": "unreadable"}),
    # A rotated substitute's bounding box meets the slot below the IoU bar: its nearness is unknowable.
    ("unreadable-substitute-overlapping-the-slot", _rows(videos=lambda i: [_pv(id=2, transform="div#x", rect=BIG)]), SLOT,
     {"status": "inconclusive", "unpaintedFrames": 0, "_reason": "unreadable"}),
    # Astra r1 #1: violations never outrank incomplete evidence; the dark frames are still reported.
    ("dark-frames-with-one-unobserved-frame", _drop_pp(_rows(videos=_hide(60, 65, opacity=0.0))), SLOT,
     {"status": "inconclusive", "unpaintedFrames": 6, "_reason": "unobserved"}),
    ("mismatched-pp", _wrong_pp(_rows()), SLOT, {"status": "inconclusive", "_reason": "unobserved"}),
    ("gap-of-4.5-periods", _gap(4.5)(_rows()), SLOT, {"status": "inconclusive", "_reason": "frame gap"}),
    ("one-missed-frame", _gap(2.0)(_rows()), SLOT, {"status": "ok", "_missed": 1}),
]


@pytest.mark.parametrize(("rows", "slot", "expected"), [c[1:] for c in SCORE_CASES], ids=[c[0] for c in SCORE_CASES])
def test_score_paint(rows, slot, expected) -> None:
    result = pi.score_paint(rows, 1, "movie-a", start=0.0, end=math.inf, slot_of=lambda r: slot,
                            stage_box_of=lambda r: r["pp"]["stageBox"], **SCORE_KW)
    for key, value in expected.items():
        if key == "_hiding":
            assert result["firstFailure"]["hiding"]["node"] == value
            assert result["firstFailure"]["parent"] == "div#layer113"
        elif key == "_firstReason":
            assert result["firstFailure"]["reason"] == value
        elif key == "_reason":
            assert any(value in reason for reason in result["reasons"]), result["reasons"]
        elif key == "_missed":
            assert result["coverage"]["missedFrames"] == value and result["coverage"]["ok"]
        else:
            assert result[key] == value, (key, result)


# Astra r6 #1: a pre-paint frame field missing or ill-typed is unobserved (inconclusive), never a reading.
@pytest.mark.parametrize("change", [None, *({k: pi.schema_problem} for k in pi.PP_FIELDS), {"cover": None}],
                         ids=["complete-dark-frames-stay-red", *(f"no-pp.{k}" for k in pi.PP_FIELDS), "null-cover"])
def test_a_pre_paint_frame_field_missing_or_ill_typed_is_inconclusive(change) -> None:
    rows = _rows(videos=_hide(60, 65, opacity=0.0))
    for key, value in (change or {}).items():
        if value is pi.schema_problem:
            del rows[62]["pp"][key]
        else:
            rows[62]["pp"][key] = value
    result = pi.score_paint(rows, 1, "movie-a", start=0.0, end=math.inf, slot_of=lambda r: SLOT,
                            stage_box_of=lambda r: r["pp"].get("stageBox"), **SCORE_KW)
    assert result["status"] == ("fail" if change is None else "inconclusive"), result["reasons"]


def _clean_control() -> tuple[dict[str, Any], dict[str, Any]]:
    record = {"control": {"n": 6, "variant": "ancestor-opacity", "phase": "pin", "timing": "early", "atScene": 2,
                          "depth": 1, "delayTicks": 10},
              "fired": True, "aborted": None, "events": [], "errors": [], "triggerSeq": 5, "onSeq": 15, "offSeq": 21,
              "hiddenTicks": 6, "hiddenSeqs": list(range(15, 21)), "lateSeqs": [], "target": {"elId": 11, "node": "div#body"}}
    paint = pi.score_paint(_rows(videos=_hide(15, 20, opacity=0.0)), 1, "movie-a", start=0.0, end=math.inf,
                           slot_of=lambda r: SLOT, stage_box_of=lambda r: r["pp"]["stageBox"], **SCORE_KW)
    return record, paint


# Astra r6 #2: every recorder and paint-score field the control reads is present and typed, or it is inconclusive.
@pytest.mark.parametrize("change", [
    None, *(("record", k) for k in pi.CONTROL_RECORD_FIELDS), *(("paint", k) for k in pi.PAINT_SCORE_FIELDS),
    ("early-off", None), ("string-on", None),
], ids=["complete-control-passes", *(f"no-record.{k}" for k in pi.CONTROL_RECORD_FIELDS),
        *(f"no-paint.{k}" for k in pi.PAINT_SCORE_FIELDS), "early-offSeq", "string-onSeq"])
def test_a_control_record_or_paint_score_field_missing_is_inconclusive(change) -> None:
    record, paint = _clean_control()
    if change is not None:
        where, key = change
        if where == "early-off":
            record["offSeq"] = 20
        elif where == "string-on":
            record["onSeq"] = "15"
        else:
            del (record if where == "record" else paint)[key]
    assert pi.score_paint_control(record, paint, 6, "early")["status"] == ("pass" if change is None else "inconclusive")


# ---------------------------------------------------------------- sampler_self_check, paint_census

META = {"schema": 2, "rafTicks": 120, "overflow": 0, "errors": [], "lastTs": 120 * PERIOD, "prepaint": 120,
        "ppMismatch": 0, "ppDuplicate": 0, "readCostMs": {"sum": 12.0, "max": 0.4}}


def _duplicated(rows):
    return rows[:50] + [rows[49]] + rows[50:]


SELF_CHECKS = [
    ("clean", _rows(), META, 120 * PERIOD + 5, None),
    ("stale", _rows(), META, 120 * PERIOD + 5 * PERIOD, "sampler stopped"),
    ("errors", _rows(), {**META, "errors": ["prepaint: boom"]}, 120 * PERIOD, "sampler errors"),
    ("duplicate-rows", _duplicated(_rows()), META, 120 * PERIOD, "duplicate rows"),
    ("no-pre-paint-reads", [dict(r, pp=None) for r in _rows()], META, 120 * PERIOD, "no pre-paint reads"),
    # Astra r1 #1: partial pre-paint coverage never vouches.
    ("one-row-without-pp", _drop_pp(_rows()), {**META, "prepaint": 119}, 120 * PERIOD, "1 rows without a pre-paint read"),
    # Astra r1 #4: a consecutive prefix (the tail lost to a malformed drain) does not reconcile with the meta.
    ("tail-not-retained", _rows()[:100], META, 120 * PERIOD, "100 rows retained against meta.rafTicks 120"),
    ("tail-endpoint", _rows()[:100], {**META, "rafTicks": 100, "prepaint": 100}, 120 * PERIOD, "is not meta.lastTs"),
]


@pytest.mark.parametrize(("rows", "meta", "now", "reason"), [c[1:] for c in SELF_CHECKS], ids=[c[0] for c in SELF_CHECKS])
def test_sampler_self_check(rows, meta, now, reason) -> None:
    check = pi.sampler_self_check(rows, meta, read_now=now, max_gap_frames=3)
    assert check["ok"] is (reason is None), check
    if reason:
        assert any(reason in r for r in check["reasons"]), check["reasons"]


def test_paint_census_labels_every_class_and_drops_none() -> None:
    def videos(i):
        if 10 <= i <= 12 or 70 <= i <= 71:
            return [_pv(opacity=0.0)]
        if 50 <= i <= 52:
            return [_pv(opacity=0.0, ended=True)]
        if 30 <= i <= 31:
            return [_pv(connected=False)]
        return [_pv()]

    rows = _rows(videos=videos)
    rows[29]["hash"] = rows[30]["hash"] = "#6"
    rows[60]["pp"] = None
    scored = [(9 * PERIOD, 13 * PERIOD)]
    census = pi.paint_census(rows, {1: scored}, {1: "movie-a"}, scene_count=6)
    assert [(f["class"], f["startSeq"], f["frames"]) for f in census["findings"]] == [
        ("scored", 10, 3), ("endOfShow", 30, 2), ("ended", 50, 3), ("unscored", 70, 2)]
    assert census["counts"] == {"scored": 1, "endOfShow": 1, "ended": 1, "unscored": 1}
    assert census["findings"][1]["reasons"] == {"detached": 2}


# ---------------------------------------------------------------- JS in Node

HARNESS = r"""
(function(){
const DEFAULT_CSS = {opacity: '1', display: 'block', visibility: 'visible', position: 'static', overflowX: 'visible',
  overflowY: 'visible', filter: 'none', clipPath: 'none', maskImage: 'none', transform: 'none', perspective: 'none', willChange: 'auto'};
const CONTROL = {'ancestor-opacity': {opacity: '0'}, 'ancestor-half': {opacity: '0.5'},
  'ancestor-display': {display: 'none'}, 'element-visibility': {visibility: 'hidden'}};
const writes = [];
let installDone = false, harness = false, clock = 0, suppressRO = false, doubleRO = false;
function inShadow(n){ for (; n; n = n.parentNode) if (n.nodeType === 11) return true; return false; }
function logWrite(n, what){ if (installDone && !harness && !inShadow(n) && what.indexOf('data-obed-paint-control') < 0) writes.push(what + ' on ' + (n.id || n.tagName)); }
function flat(n){ const p = n.parentNode; return p && p.nodeType === 11 ? p.host : p; }
function box(r){ r = r || {x: 0, y: 0, w: 0, h: 0}; return {left: r.x, top: r.y, width: r.w, height: r.h, right: r.x + r.w, bottom: r.y + r.h}; }
function getComputedStyle(n){ return Object.assign({}, DEFAULT_CSS, n._css, CONTROL[n.attrs['data-obed-paint-control']] || {}); }
class El {
  constructor(tag, id, css, rect){
    const self = this;
    this.nodeType = 1; this.tagName = tag.toUpperCase(); this.id = id || ''; this._css = css || {}; this._rect = rect || null;
    this.attrs = {}; this.parentNode = null; this.children = [];
    this.style = new Proxy({}, {set(t, k, v){ logWrite(self, 'style.' + String(k)); t[k] = v; return true; }});
  }
  get parentElement(){ return this.parentNode && this.parentNode.nodeType === 1 ? this.parentNode : null; }
  get isConnected(){ for (let n = this; n; n = flat(n)) if (n.nodeType === 9) return true; return false; }
  setAttribute(k, v){ logWrite(this, 'attr ' + k); this.attrs[k] = String(v); }
  removeAttribute(k){ logWrite(this, 'attr ' + k); delete this.attrs[k]; }
  appendChild(c){ logWrite(this, 'childList'); if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.children.push(c); return c; }
  removeChild(c){ logWrite(this, 'childList'); this.children = this.children.filter(x => x !== c); c.parentNode = null; return c; }
  attachShadow(){ const sr = {nodeType: 11, host: this, children: [], appendChild(c){ c.parentNode = sr; sr.children.push(c); return c; }}; return sr; }
  getBoundingClientRect(){
    for (let n = this; n && n.nodeType === 1; n = flat(n)) if (getComputedStyle(n).display === 'none') return box(null);
    return box(this._rect);
  }
  get clientLeft(){ return this._border || 0; } get clientTop(){ return this._border || 0; }
  get offsetWidth(){ return (this._layout || this._rect || {w: 0}).w; } get offsetHeight(){ return (this._layout || this._rect || {h: 0}).h; }
  get clientWidth(){ return this.offsetWidth - 2 * (this._border || 0); } get clientHeight(){ return this.offsetHeight - 2 * (this._border || 0); }
  checkVisibility(){
    if (getComputedStyle(this).visibility !== 'visible') return false;
    for (let n = this; n && n.nodeType === 1; n = flat(n)) {
      const cs = getComputedStyle(n);
      if (cs.display === 'none' || parseFloat(cs.opacity) === 0) return false;
    }
    return true;
  }
}
const Element = El;
function walk(n, f){ for (const c of n.children || []) { f(c); walk(c, f); } }
const document = {nodeType: 9, adoptedStyleSheets: [], createElement: tag => new El(tag),
  querySelectorAll(sel){ const out = []; walk(html, c => { if (c.tagName === 'VIDEO') out.push(c); }); return out; },
  getElementById(id){ let f = null; walk(html, c => { if (!f && c.id === id) f = c; }); return f; }};
const html = new El('html', '', {}, {x: 0, y: 0, w: 1920, h: 1080}); html.parentNode = document; document.documentElement = html;
const body = new El('body', '', {}, {x: 0, y: 0, w: 1920, h: 1080}); html.appendChild(body); document.body = body;
const location = {hash: '#1'};
const snapshot = {busy: false, sceneId: 1};
const window = {innerWidth: 1920, innerHeight: 1080, __OBED_P2_PRESERVE__: {events: []}, __obedLive: {snapshot: () => snapshot},
  __OBED_CONTINUITY__: {movies: {m1: {assetKeys: ['movie-a.mov']}}, boundaries: [{action: 'bridge', atScene: 2, movieKey: 'm1'}]}};
const performance = {now(){ return clock += 0.01; }};
let rafQ = [], micro = [];
function requestAnimationFrame(cb){ rafQ.push(cb); return rafQ.length; }
function queueMicrotask(cb){ micro.push(cb); }
const ROs = [];
class ResizeObserver { constructor(cb){ this.cb = cb; ROs.push(this); } observe(t){ this.target = t; this.last = t.style.width; } }
class CSSStyleSheet { replaceSync(text){ this.text = text; } }
function render(){
  for (const ro of ROs) {
    const w = ro.target.style.width;
    if (w === ro.last) continue;
    ro.last = w;
    if (suppressRO) continue;
    ro.cb([]);
    if (doubleRO) ro.cb([]);
  }
}
function runFrame(ts){
  clock = ts;
  const q = rafQ; rafQ = [];
  for (const cb of q) { cb(ts); while (micro.length) micro.shift()(); }
  render();
}
function video(elId, src, rect){
  const v = new El('video', '', {}, rect);
  Object.assign(v, {__obedElId: elId, src: 'https://h/' + src, currentSrc: 'https://h/' + src, readyState: 4,
    videoWidth: 640, videoHeight: 360, seeking: false, currentTime: 0, paused: false, ended: false});
  return v;
}
function stageMapOf(){ return {s: 1, sy: 1, ox: 0, oy: 0, offsetWidth: 1920, offsetHeight: 1080}; }
__FRAGMENTS__
const samples = [], meta = {schema: 2, rafTicks: 0, overflow: 0, errors: [], lastTs: null};
const probe = {samples: samples, meta: meta};
let nextId = 1, seq = 0;
const skipPush = new Set();
const stageArea = new El('div', 'stageArea', {}, {x: 0, y: 0, w: 1920, h: 1080});
body.appendChild(stageArea);
const keynoteBody = new El('div', 'body', {position: 'relative'}, {x: 0, y: 0, w: 1920, h: 1080});
stageArea.appendChild(keynoteBody);
const pre = installPrepaint(probe);
installDone = true;
function tick(ts){
  const t = performance.now();
  const vids = document.querySelectorAll('video');
  vids.forEach(v => { if (v.__obedProbeId == null) v.__obedProbeId = nextId++; pre.track(v); });
  if (skipPush.has(seq)) meta.overflow++;
  else samples.push({t: t, seq: seq, ts: ts, hash: location.hash, raf: vids.map(paintReadOf)});
  pre.toggle(seq, ts);
}
function frame(ts){
  seq++; meta.rafTicks++; meta.lastTs = ts;
  requestAnimationFrame(frame);
  const ctl = window.__obedPaintControl__;
  if (ctl) ctl.tick(seq, ts);
  tick(ts);
}
requestAnimationFrame(frame);
function act(f){ harness = true; try { f(); } finally { harness = false; } }
__SCENARIO__
})();
"""


def _run_js(scenario: str, control: str = "") -> dict[str, Any]:
    fragments = pi.PAINT_READ_FN_JS + pi.PREPAINT_FN_JS
    script = HARNESS.replace("__FRAGMENTS__", fragments).replace("__SCENARIO__", control + "\n" + scenario)
    return json.loads(_node_stdout(script).strip().splitlines()[-1])


_OUT = "console.log(JSON.stringify({rows: samples, meta: meta, writes: writes, " \
       "record: window.__obedPaintControl__ ? window.__obedPaintControl__.record : null}));"


READS = [
    # The flat-tree walk crosses a closed shadow root to its host: a host at opacity 0 hides the decoder.
    ("shadow-root-ancestor-at-opacity-0", """
const host = new El('div', 'host', {opacity: '0'}, {x: 0, y: 0, w: 1920, h: 1080});
keynoteBody.appendChild(host);
host.attachShadow({mode: 'closed'}).appendChild(v);
""", ("unpainted", "checkVisibility"), {"hiding": {"node": "div#host", "prop": "opacity", "value": 0}, "parent": "#shadow-root", "opacity": 0}),
    ("c1-layer104-over-layer113", """
const l104 = new El('div', 'layer104', {opacity: '0'}, {x: 0, y: 0, w: 1920, h: 1080});
const l113 = new El('div', 'layer113', {}, {x: 0, y: 0, w: 1920, h: 1080});
keynoteBody.appendChild(l104); l104.appendChild(l113); l113.appendChild(v);
""", ("unpainted", "checkVisibility"), {"hiding": {"node": "div#layer104", "prop": "opacity", "value": 0},
                                        "parent": "div#layer113", "layer": "layer113"}),
    ("ancestor-visibility-hidden-own-visible", """
stageArea._css.visibility = 'hidden';
v._css.visibility = 'visible';
keynoteBody.appendChild(v);
""", ("painted", None), {"opacity": 1}),
    ("nan-opacity-ancestor", """
keynoteBody._css.opacity = 'bogus';
keynoteBody.appendChild(v);
""", ("unreadable", "opacity"), {"opacity": None}),
    ("filter-ancestor", """
keynoteBody._css.filter = 'blur(2px)';
keynoteBody.appendChild(v);
""", ("unreadable", "effects"), {"effects": "div#body:filter"}),
    ("overflow-clipping-ancestor", """
const clip = new El('div', 'clip', {overflowX: 'hidden', overflowY: 'hidden'}, {x: 100, y: 100, w: 200, h: 225});
keynoteBody.appendChild(clip); clip.appendChild(v);
""", ("partial", "clipped"), {"visibleRect": {"x": 100, "y": 100, "w": 200, "h": 225}, "clippedBy": "div#clip"}),
    # Astra r1 #2: under scale(.5) a 400x450 layout padding box (10 px border) is 200x225 on screen; the unscaled
    # clientWidth/clientHeight/clientLeft read it as 400x450 at (105, 105), leaving the decoder nearly uncut.
    ("scaled-clipping-ancestor-in-screen-px", """
const clip = new El('div', 'clip', {overflowX: 'hidden', overflowY: 'hidden', transform: 'matrix(0.5, 0, 0, 0.5, 0, 0)'},
                    {x: 95, y: 95, w: 210, h: 235});
clip._layout = {w: 420, h: 470}; clip._border = 10;
keynoteBody.appendChild(clip); clip.appendChild(v);
""", ("partial", "clipped"), {"visibleRect": {"x": 100, "y": 100, "w": 200, "h": 225}, "clippedBy": "div#clip", "transform": None}),
    ("rotated-ancestor-is-unreadable", """
const clip = new El('div', 'clip', {overflowX: 'hidden', overflowY: 'hidden',
                    transform: 'matrix(0.7071, 0.7071, -0.7071, 0.7071, 0, 0)'}, {x: 100, y: 100, w: 200, h: 225});
keynoteBody.appendChild(clip); clip.appendChild(v);
""", ("unreadable", "transform"), {"transform": "div#clip"}),
    # Astra r2 B: a reflection flips which border is on the left; the unsigned mapping read it as fully painted.
    ("reflected-ancestor-is-unreadable", """
const clip = new El('div', 'clip', {overflowX: 'hidden', overflowY: 'hidden', transform: 'matrix(-1, 0, 0, 1, 0, 0)'},
                    {x: 100, y: 100, w: 140, h: 225});
keynoteBody.appendChild(clip); clip.appendChild(v);
""", ("unreadable", "transform"), {"transform": "div#clip"}),
    # An absolutely positioned decoder escapes a non-positioned clipping ancestor (its containing block is #body).
    ("absolute-escapes-static-overflow", """
const clip = new El('div', 'clip', {overflowX: 'hidden', overflowY: 'hidden'}, {x: 100, y: 100, w: 200, h: 225});
v._css.position = 'absolute';
keynoteBody.appendChild(clip); clip.appendChild(v);
""", ("painted", None), {"visibleRect": {"x": 100, "y": 100, "w": 400, "h": 225}, "clippedBy": None}),
]


@pytest.mark.parametrize(("dom", "state", "fields"), [r[1:] for r in READS], ids=[r[0] for r in READS])
def test_paint_read_walks_the_flat_tree(dom: str, state, fields) -> None:
    out = _run_js("const v = video(7, 'movie-a.mov', {x: 100, y: 100, w: 400, h: 225}); v.__obedProbeId = 1;\n" + dom
                  + "\nconsole.log(JSON.stringify(paintReadOf(v)));")
    assert pi.painted_state(out, expected=SLOT, stage=STAGE, rect_tolerance=3.0) == state
    for key, value in fields.items():
        assert out[key] == value, (key, out)


def test_prepaint_reads_once_per_frame_tracks_detached_decoders_and_never_writes_the_light_dom() -> None:
    out = _run_js("""
const v = video(7, 'movie-a.mov', {x: 100, y: 100, w: 400, h: 225});
act(() => keynoteBody.appendChild(v));
for (let i = 1; i <= 12; i++) {
  suppressRO = i === 4; doubleRO = i === 8;
  if (i === 6) skipPush.add(6);
  if (i === 9) act(() => keynoteBody.removeChild(v));
  runFrame(i * 1000 / 60);
}
""" + _OUT)
    rows, meta = out["rows"], out["meta"]
    assert out["writes"] == []
    assert [r["seq"] for r in rows] == [1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12]
    assert [r["seq"] for r in rows if "pp" not in r] == [4]
    for row in rows:
        if "pp" in row:
            assert (row["pp"]["seq"], row["pp"]["ts"]) == (row["seq"], row["ts"]) and row["pp"]["t"] >= row["t"]
    assert (meta["prepaint"], meta["ppMismatch"], meta["ppDuplicate"], meta["overflow"]) == (10, 1, 1, 1)
    # Frame 9 onwards: the decoder left the DOM; the WeakRef set still reports it, as detached.
    detached = [r["pp"]["videos"] for r in rows if r["seq"] >= 9]
    assert all(len(vs) == 1 and pi.painted_state(vs[0]) == ("unpainted", "detached") for vs in detached)
    assert all(r["raf"] == [] for r in rows if r["seq"] >= 9)
    check = pi.sampler_self_check(rows, meta, read_now=12 * PERIOD, max_gap_frames=3)
    assert not check["ok"]
    assert {r.split(" = ")[0] for r in check["reasons"] if " = " in r} == {"meta.overflow", "meta.ppMismatch", "meta.ppDuplicate"}
    assert check["rowsWithoutPp"] == 1 and check["seqGaps"] == 1


CONTROL_SETUPS = {
    "pin": ("ancestor-opacity", 1, """
const v = video(7, 'movie-a.mov', {x: 100, y: 100, w: 400, h: 225});
act(() => keynoteBody.appendChild(v));
const fire = () => window.__OBED_P2_PRESERVE__.events.push({kind: 'pin-hold-start', detail: {elId: 7, atScene: 2, sceneHash: '#1'}, t: clock});
"""),
    "bridge": ("element-visibility", 1, """
const v = video(7, 'movie-a.mov', {x: 100, y: 100, w: 400, h: 225});
act(() => keynoteBody.appendChild(v));
const fire = () => window.__OBED_P2_PRESERVE__.events.push({kind: 'bridge-motion-start', detail: {elId: 7, sceneHash: '#1'}, t: clock});
"""),
    "settled": ("ancestor-display", 2, """
const v = video(7, 'movie-a.mov', {x: 100, y: 100, w: 400, h: 225});
const l104 = new El('div', 'layer104', {}, {x: 0, y: 0, w: 1920, h: 1080});
const l113 = new El('div', 'layer113', {}, {x: 0, y: 0, w: 1920, h: 1080});
act(() => { keynoteBody.appendChild(l104); l104.appendChild(l113); l113.appendChild(v); });
v.readyState = 1; snapshot.busy = true;
const fire = () => { v.readyState = 4; snapshot.busy = false; };
"""),
}
CONTROL_SETUPS["pin-half"] = ("ancestor-half", 1, CONTROL_SETUPS["pin"][2])
TRIGGER_FRAME, DELAY, FRAMES = 5, 10, 60


def _control_run(setup: str, n: int, timing: str, extra: str = "") -> tuple[dict[str, Any], str]:
    variant, depth, dom = CONTROL_SETUPS[setup]
    phase = setup.split("-")[0]
    control = pi.paint_control_js(n, variant, phase, 2, timing=timing, depth=depth, delay_ticks=DELAY)
    scenario = dom + f"""
for (let i = 1; i <= {FRAMES}; i++) {{
  if (i === {TRIGGER_FRAME}) fire();
  {extra}
  runFrame(i * 1000 / 60);
}}
""" + _OUT
    return _run_js(scenario, control), variant


def _carried_seqs(rows: list[dict[str, Any]], key: str, state: str) -> list[int]:
    out = []
    for row in rows[TRIGGER_FRAME - 1:]:
        pvs = row["pp"]["videos"] if key == "pp" else row["raf"]
        mine = [pv for pv in pvs if pv["elId"] == 7]
        if pi.painted_state(mine[0] if mine else None)[0] == state:
            out.append(row["seq"])
    return out


@pytest.mark.parametrize("timing", pi.PAINT_CONTROL_TIMINGS)
@pytest.mark.parametrize("n", [0, 1, 6, 30])
@pytest.mark.parametrize("setup", ["pin", "bridge", "settled", "pin-half"])
def test_the_injector_hides_exactly_k_to_k_plus_n_minus_1_before_paint(setup: str, n: int, timing: str) -> None:
    out, variant = _control_run(setup, n, timing)
    record, rows = out["record"], out["rows"]
    k = TRIGGER_FRAME + DELAY
    injected = list(range(k, k + n))
    assert out["writes"] == []
    assert record["fired"] and record["aborted"] is None and record["errors"] == [] and record["events"] == []
    assert (record["triggerSeq"], record["onSeq"], record["hiddenTicks"], record["hiddenSeqs"]) == (TRIGGER_FRAME, k, n, injected)
    state = "partial" if variant == "ancestor-half" else "unpainted"
    assert _carried_seqs(rows, "pp", state) == injected
    # Known-bad for the phase: under `late` a rAF-phase reader sees the set shifted by one frame.
    shifted = [s + 1 for s in injected] if timing == "late" else injected
    assert _carried_seqs(rows, "raf", state) == shifted
    if timing == "late" and n:
        assert record["lateSeqs"] == [k, k + n]

    paint = pi.score_paint(rows, 1, "movie-a", start=rows[TRIGGER_FRAME - 1]["t"], end=math.inf,
                           slot_of=lambda r: SLOT, stage_box_of=lambda r: r["pp"]["stageBox"], **SCORE_KW)
    assert pi.score_paint_control(record, {"scored": {"paint": paint}}, n, timing)["status"] == "pass"
    assert pi.score_paint_control(record, paint, n + 1, timing)["status"] == "fail"
    if n:
        shifted_paint = dict(paint, **{"partialSeqs" if state == "partial" else "unpaintedSeqs": [s + 1 for s in injected]})
        assert pi.score_paint_control(record, shifted_paint, n, timing)["status"] == "fail"
    # Astra r1 #1: the exact set on incomplete evidence never passes, whether the score said so or not.
    rows[-1]["pp"] = None
    gappy = pi.score_paint(rows, 1, "movie-a", start=rows[TRIGGER_FRAME - 1]["t"], end=math.inf,
                           slot_of=lambda r: SLOT, stage_box_of=lambda r: r["pp"]["stageBox"], **SCORE_KW)
    assert gappy["status"] == "inconclusive"
    for evidence in (gappy, dict(paint, unobserved=gappy["unobserved"]), dict(paint, coverage={"ok": False})):
        assert pi.score_paint_control(record, evidence, n, timing)["status"] == "inconclusive"


@pytest.mark.parametrize(("extra", "expected"), [
    ("if (i === 17) act(() => { const other = new El('div', 'other', {}, {x: 0, y: 0, w: 1920, h: 1080}); keynoteBody.appendChild(other); other.appendChild(v); });",
     "decoder parent changed"),
    ("if (i === 17) window.__OBED_P2_PRESERVE__.events.push({kind: 'remount-done', detail: {elId: 7}, t: clock + 1});",
     "placement events"),
], ids=["parent-change-aborts", "placement-event"])
def test_injector_integrity_breaks_are_inconclusive(extra: str, expected: str) -> None:
    out, _ = _control_run("pin", 6, "early", extra)
    record = out["record"]
    paint = pi.score_paint(out["rows"], 1, "movie-a", start=0.0, end=math.inf, slot_of=lambda r: SLOT,
                           stage_box_of=lambda r: r["pp"]["stageBox"], **SCORE_KW)
    result = pi.score_paint_control(record, paint, 6, "early")
    assert result["status"] == "inconclusive"
    assert any(expected in r for r in result["reasons"]), result["reasons"]
    if expected == "decoder parent changed":
        assert record["aborted"] == expected and record["hiddenTicks"] == 2


@pytest.mark.parametrize(("args", "kw"), [
    ((6, "ancestor-display", "pin", 2), {}),
    ((6, "ancestor-opacity", "settled", 2), {"depth": 1}),
    ((6, "ancestor-opacity", "pin", 2), {"timing": "later"}),
    ((6, "ancestor-opacity", "pin", 2), {"delay_ticks": 0}),
    ((-1, "ancestor-opacity", "pin", 2), {}),
], ids=["display-outside-settled", "settled-depth-1", "unknown-timing", "no-delay", "negative-n"])
def test_paint_control_js_refuses(args, kw) -> None:
    with pytest.raises(ValueError):
        pi.paint_control_js(*args, **kw)
