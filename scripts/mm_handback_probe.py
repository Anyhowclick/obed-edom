#!/usr/bin/env python3
"""Headless HB-1..HB-4 instrument for the Magic Move hand-back geometry fix (plan `keynote_live_handback_geometry` §4).

One fresh headless Chrome per arm, driven through `LiveOutputHost` on the binary-counter fixture (`output/p2-binary`). The
arm switch is the existing `mm_opacity` switch: `on`/`on2` = "auto" (MMO + R6-R8), `off`/`off2` = "off" (today's bytes).
Evidence per run: CDP screenshot pairs 0.5 s apart (slide 1; the settled 1->2 GL frame 2.5 s after settle, or the G2 LIVE
frame under GL auto; the DOM 2 s after build 1; the DOM 2 s after 3->4), the 3->4 settle frame's in-page alpha, the
per-frame 1->2 band profile (G - R, authored rows `BAND_ROWS`) and the page's own engagement read: an `Object.prototype`
setter trap records every leaf that receives `obedMix` (its `textureId`), and the logger counts, per frame, the draws that
bound texture unit 1 (the player's `isBlending` path). The verdict is re-derived from the saved PNGs and records
(`mm_handback_score`); no page-computed sub-verdict is scored.

Gates (integrity, premise, engagement, controls, KB and CvC failures read INCONCLUSIVE, never PASS):
  HB-1  (blocking, GL off, per viewport) max |DOM - GL| over the green and sentinel edges <= `HB_MAX` screen px in `on`
        and `on2`; KB: `off` and `off2` >= `KB_MIN`; CvC per edge (on vs on2, off vs off2; GL and DOM shots) <= `CVC_TOL`.
        Controls per run: GL, DOM and slide-1 pairs and the static movie outline <= `NULL_TOL`; the 1 / 0.5 px shift of
        the GL shot within `SHIFT_TOL`. At both mm12 shots the page must show `MM12_CANVAS` and hide every DOM node
        the player swaps for it (read in page, judged here), so a settled GL frame is never confused with an early
        DOM. Premise: the fixture's texture rects; each run served the current `patch_player` bytes for its mode
        (sha256, so a reused `--out` from an older build cannot merge in); on-arms blend exactly the two
        `BLENDED_TEXTURES`, off-arms none; the settle frame's blended draws are Keynote's own `contents` leaves
        (`KEYNOTE_CONTENTS`: the background at 1->2, background and footprint at 3->4) plus 2 on the on-arms' 1->2.
  HB-2  (blocking, GL auto, 1920) the same metric on the G2 LIVE screenshot; `on` G2 stats LIVE, no stand-down,
        `glErrors` 0, unproven [{4, size}]; `off` (KB, >= `KB_MIN`) must read LIVE, no stand-down, `glErrors` 0,
        unproven [] or INCONCLUSIVE. `frameLen` is reported on both arms, never checked: the player's `setGLFloat`
        queues a uniform write only when the value changed, so the settle frame's call count depends on timing
        (headless off-arm 85 and 86).
  HB-3  (report, 1920 GL off) width(on) - width(off) against move progress and its per-frame step divided by the
        progress step; CvC off2 vs off.
  HB-4  (report, GL off) 3->4 footprint edges, in-page GL alpha vs the DOM screenshot, authored px.
The overall verdict is INCONCLUSIVE unless HB-1 at every viewport in `VIEWPORTS` and HB-2 are all present.

usage: uv run python scripts/mm_handback_probe.py --out DIR [--viewports 1920x1080,...] [--arms on,on2,off,off2] [--gl off,auto]
       uv run python scripts/mm_handback_probe.py --score DIR
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import mm_opacity_probe as mmo  # noqa: E402

from obed_edom import mm_handback_score as hb  # noqa: E402

FIXTURE = mmo.FIXTURE
CANVAS = (1920, 1080)
VIEWPORTS = ((1920, 1080), (2560, 1440), (1600, 1000))
ARMS = {"on": "auto", "on2": "auto", "off": "off", "off2": "off"}
AUTO_ARMS = ("on", "off")
HB_MAX = 0.25
KB_MIN = 1.0
CVC_TOL = 0.05
NULL_TOL = 0.05
SHIFT_TOL = 0.02
STAGE_TOL_PX = 0.5
KEYNOTE_CONTENTS = {"mm12": 1, "mm34": 2}
BLENDED_12 = {"auto": KEYNOTE_CONTENTS["mm12"] + 2, "off": KEYNOTE_CONTENTS["mm12"]}
MM12_CANVAS = "0-canvas"
G2_EXPECTED = {"auto": {"opacityUnproven": [{"slot": mmo.SLOT, "reason": "size"}]},
               "off": {"opacityUnproven": []}}
BAND_ROWS = (740, 760)
SHOTS = ("s1-a", "s1-b", "mm12-a", "mm12-b", "b1-a", "b1-b", "mm34-a", "mm34-b")
GL34 = "gl-mm34"
PAIR_GAP_S = 0.5
SLIDE1_WAIT_S = 2.0
GL_SETTLE_WAIT_S = 2.5
DOM_WAIT_S = 2.0
STEP_CFG = {
    "mm12": {"log": True, "band": list(BAND_ROWS)},
    "mm34": {"log": True, "captureFromMs": mmo.MOVE_MS - mmo.SETTLE_WINDOW_MS},
}

LOGGER_JS = r"""
(function(){
  if (window.__OBED_HB__) return;
  var protos = [];
  if (window.WebGLRenderingContext) protos.push(WebGLRenderingContext.prototype);
  if (window.WebGL2RenderingContext) protos.push(WebGL2RenderingContext.prototype);
  var natives = protos.map(function(P){ return {getParameter: P.getParameter, readPixels: P.readPixels}; });
  function nat(g, name){
    for (var i = 0; i < protos.length; i++) if (protos[i].isPrototypeOf(g)) return natives[i][name];
    return null;
  }
  var ctxState = new WeakMap(), count = 0;
  var H = window.__OBED_HB__ = {label: 'init', cfg: {}, frames: [], bands: [], mix: [], capture: {}, labelStart: {},
    errors: [],
    setLabel: function(label, cfg){ H.label = label; H.cfg = cfg || {}; return true; },
    alphaPng: function(label){
      var c = H.capture[label];
      if (!c) return null;
      var cv = document.createElement('canvas'); cv.width = c.w; cv.height = c.h;
      var ctx = cv.getContext('2d'), img = ctx.createImageData(c.w, c.h), d = img.data;
      for (var y = 0; y < c.h; y++) for (var x = 0; x < c.w; x++){
        var o = (y * c.w + x) * 4;
        d[o] = d[o + 1] = d[o + 2] = c.px[((c.h - 1 - y) * c.w + x) * 4 + 3]; d[o + 3] = 255;
      }
      ctx.putImageData(img, 0, 0);
      return {png: cv.toDataURL('image/png'), frame: c.frame, el: c.el, n: c.n, w: c.w, h: c.h};
    }};
  Object.defineProperty(Object.prototype, 'obedMix', {configurable: true, enumerable: false,
    get: function(){ return undefined; },
    set: function(v){
      Object.defineProperty(this, 'obedMix', {value: v, writable: true, configurable: true, enumerable: true});
      try { H.mix.push({label: H.label, textureId: this.textureId == null ? null : String(this.textureId), value: !!v}); }
      catch (e) { H.errors.push(String(e)); }
    }});
  var swaps = H.swaps = [];
  Object.defineProperty(Object.prototype, 'nodeToSwapId', {configurable: true, enumerable: false,
    get: function(){ return undefined; },
    set: function(v){
      Object.defineProperty(this, 'nodeToSwapId', {value: v, writable: true, configurable: true, enumerable: true});
      swaps.push(this);
    }});
  function stateOf(g){
    var s = ctxState.get(g);
    if (!s){ s = {frame: null, lastDraws: null, unit1: false}; ctxState.set(g, s); }
    return s;
  }
  function g2(){ var a = window.__OBED_GL_REPLAY__; return a && a.version ? String(a.state) : null; }
  function isPlayer(f){ return f.g2 !== 'ARM-POST' && f.g2 !== 'LIVE'; }
  function wrap(name, fn){
    protos.forEach(function(P){
      var orig = P[name];
      P[name] = function(){ return fn.call(this, orig, arguments); };
    });
  }
  wrap('activeTexture', function(orig, args){
    try { if (args[0] === this.TEXTURE1) stateOf(this).unit1 = true; } catch (e) { H.errors.push(String(e)); }
    return orig.apply(this, args);
  });
  wrap('clear', function(orig, args){
    try {
      var s = stateOf(this), t = performance.now();
      if (s.frame && isPlayer(s.frame)) s.lastDraws = s.frame.draws;
      if (H.labelStart[H.label] == null) H.labelStart[H.label] = t;
      s.frame = {label: H.label, i: count++, el: t - H.labelStart[H.label], g2: g2(), draws: 0, blended: 0};
      s.unit1 = false;
      if (H.cfg.log) H.frames.push(s.frame);
    } catch (e) { H.errors.push(String(e)); }
    return orig.apply(this, args);
  });
  function draw(orig, args){
    var s = null, f = null, ord = -1;
    try {
      s = stateOf(this); f = s.frame;
      if (f){ ord = f.draws++; if (s.unit1) f.blended++; }
      s.unit1 = false;
    } catch (e) { H.errors.push(String(e)); }
    var rv = orig.apply(this, args);
    try {
      var cfg = H.cfg;
      if (f && isPlayer(f) && f.label === H.label && (cfg.band || cfg.captureFromMs != null) && s.lastDraws != null &&
          ord === s.lastDraws - 1 && nat(this, 'getParameter').call(this, this.FRAMEBUFFER_BINDING) === null){
        var w = this.drawingBufferWidth, h = this.drawingBufferHeight;
        if (cfg.band){
          var n = cfg.band[1] - cfg.band[0], px = new Uint8Array(w * n * 4), prof = new Array(w);
          nat(this, 'readPixels').call(this, 0, h - cfg.band[1], w, n, this.RGBA, this.UNSIGNED_BYTE, px);
          for (var x = 0; x < w; x++){
            var acc = 0;
            for (var y = 0; y < n; y++){ var o = (y * w + x) * 4; acc += px[o + 1] - px[o]; }
            prof[x] = Math.round(acc / n * 1000) / 1000;
          }
          H.bands.push({label: f.label, i: f.i, el: f.el, w: w, h: h, profile: prof});
        }
        if (cfg.captureFromMs != null && f.el >= cfg.captureFromMs){
          var c = H.capture[f.label];
          if (!c || c.w !== w || c.h !== h) c = H.capture[f.label] = {w: w, h: h, px: new Uint8Array(w * h * 4), n: 0};
          nat(this, 'readPixels').call(this, 0, 0, w, h, this.RGBA, this.UNSIGNED_BYTE, c.px);
          c.frame = f.i; c.el = f.el; c.n++;
        }
      }
    } catch (e) { H.errors.push(String(e)); }
    return rv;
  }
  wrap('drawArrays', draw);
  wrap('drawElements', draw);
})();
"""

SWAP_READ_JS = r"""
(function(){
  function facts(el){
    if (!el) return null;
    var cs = getComputedStyle(el), r = el.getBoundingClientRect(), chain = 1;
    for (var n = el; n && n.nodeType === 1; n = n.parentElement) chain *= parseFloat(getComputedStyle(n).opacity);
    return {id: el.id, connected: el.isConnected, opacity: chain, visibility: cs.visibility, display: cs.display,
            w: r.width, h: r.height};
  }
  var H = window.__OBED_HB__;
  return {canvases: Array.from(document.querySelectorAll('canvas[id$="-canvas"]')).map(facts),
          swaps: (H ? H.swaps : []).map(function(o){
            return {canvasId: o.canvasId == null ? null : String(o.canvasId), id: String(o.nodeToSwapId),
                    node: facts(document.getElementById(o.nodeToSwapId))};
          })};
})()
"""

LOG_READ_JS = (
    "(function(){var H=window.__OBED_HB__;if(!H)return null;var cap={};"
    "Object.keys(H.capture).forEach(function(k){var c=H.capture[k];cap[k]={frame:c.frame,el:c.el,n:c.n,w:c.w,h:c.h};});"
    "return {frames:H.frames,bands:H.bands,mix:H.mix,errors:H.errors,labelStart:H.labelStart,capture:cap};})()"
)


def tag_of(gl: str, viewport: tuple[int, int], arm: str) -> str:
    return f"{gl}-{viewport[0]}x{viewport[1]}-{arm}"


def expected_stage(viewport: tuple[int, int]) -> hb.Stage:
    s = min(viewport[0] / CANVAS[0], viewport[1] / CANVAS[1])
    return hb.Stage(s, (viewport[0] - CANVAS[0] * s) / 2, (viewport[1] - CANVAS[1] * s) / 2)


def stage_of(record: dict[str, Any]) -> hb.Stage | None:
    m = record.get("stage") or {}
    try:
        return hb.Stage(float(m["s"]), float(m["ox"]), float(m["oy"]))
    except (KeyError, TypeError, ValueError):
        return None


def player_frames(record: dict[str, Any], label: str) -> list[dict[str, Any]]:
    frames = ((record.get("log") or {}).get("frames")) or []
    return [f for f in frames if f.get("label") == label and f.get("g2") not in mmo.G2_FRAMES and f.get("draws")]


def engagement(record: dict[str, Any]) -> dict[str, Any]:
    log = record.get("log") or {}
    f12, f34 = player_frames(record, "mm12"), player_frames(record, "mm34")
    return {
        "mixTextures": sorted({str(m.get("textureId")) for m in log.get("mix") or [] if m.get("value")}),
        "blended12": f12[-1]["blended"] if f12 else None,
        "blended34": f34[-1]["blended"] if f34 else None,
    }


def engagement_problems(record: dict[str, Any], eng: dict[str, Any]) -> list[str]:
    mode = record.get("mmOpacity")
    if mode not in BLENDED_12:
        return [f"unknown mm_opacity mode {mode!r}"]
    problems = []
    expected = sorted(hb.BLENDED_TEXTURES) if mode == "auto" else []
    if eng["mixTextures"] != expected:
        problems.append(f"engagement: obedMix leaves {[t[:6] for t in eng['mixTextures']]}, expected {[t[:6] for t in expected]}")
    if eng["blended12"] != BLENDED_12[mode]:
        problems.append(f"engagement: 1->2 settle frame blended draws {eng['blended12']}, expected {BLENDED_12[mode]}")
    if eng["blended34"] != KEYNOTE_CONTENTS["mm34"]:
        problems.append(f"instrument: 3->4 settle frame blended draws {eng['blended34']}, expected {KEYNOTE_CONTENTS['mm34']} "
                        "(Keynote's contents leaves)")
    return problems


def player_shas(fixture: Path) -> dict[str, str]:
    """The sha256 `LiveOutputHost` reports for the player it serves, per `mm_opacity` mode, from today's `patch_player`."""
    from obed_edom.live_runtime import patch_player

    player = (fixture / "html-player" / "assets" / "player" / "main.js").read_bytes()
    return {mode: hashlib.sha256(patch_player(player, mm_opacity=mode == "auto")).hexdigest() for mode in ("auto", "off")}


def _shown(facts: dict[str, Any] | None) -> bool:
    return bool(facts) and bool(facts.get("connected")) and (facts.get("opacity") or 0) > 0 and \
        facts.get("visibility") != "hidden" and facts.get("display") != "none" and \
        (facts.get("w") or 0) > 0 and (facts.get("h") or 0) > 0


def swap_problems(record: dict[str, Any]) -> list[str]:
    reads = record.get("mm12Dom") or []
    if len(reads) != 2:
        return [f"mm12: {len(reads)} in-page canvas/DOM reads, expected 2"]
    problems = []
    for n, read in enumerate(reads):
        canvases = [c for c in (read or {}).get("canvases") or [] if (c or {}).get("id") == MM12_CANVAS]
        if len(canvases) != 1 or not _shown(canvases[0]):
            problems.append(f"mm12 read {n}: {MM12_CANVAS} is not shown: {canvases}")
        swaps = [w for w in (read or {}).get("swaps") or [] if w.get("canvasId") == MM12_CANVAS]
        if not swaps:
            problems.append(f"mm12 read {n}: no DOM node swapped for {MM12_CANVAS}")
        problems += [f"mm12 read {n}: swapped DOM node {w.get('id')} is shown" for w in swaps if _shown(w.get("node"))]
    return problems


def run_problems(record: dict[str, Any], images: dict[str, np.ndarray], shas: dict[str, str]) -> list[str]:
    problems = []
    if record.get("error"):
        problems.append(f"run error: {str(record['error']).strip().splitlines()[-1]}")
    if not record.get("loggerInstalled"):
        problems.append("logger not installed")
    log = record.get("log")
    if not log:
        problems.append("no logger output")
    elif log.get("errors"):
        problems.append(f"logger errors: {log['errors'][:3]}")
    for step in record.get("steps") or []:
        expected = step.get("expectHash")
        if expected and [step.get("hashBefore"), step.get("hashAfter")] != list(expected):
            problems.append(f"{step['label']}: hash {step.get('hashBefore')}->{step.get('hashAfter')}, expected {expected}")
    want_mode = "on" if record.get("mmOpacity") == "auto" else "off"
    if ((record.get("output") or {}).get("mmOpacity") or {}).get("mode") != want_mode:
        problems.append(f"served player mm_opacity mode is not {want_mode!r}: {record.get('output')}")
    served = ((record.get("output") or {}).get("mmOpacity") or {}).get("sha256")
    if served is None or served != shas.get(record.get("mmOpacity")):
        problems.append(f"served player sha {served} is not today's patch_player output for {record.get('mmOpacity')!r}")
    problems += swap_problems(record)
    viewport = tuple(record.get("viewport") or ())
    stage, want = stage_of(record), expected_stage(viewport) if len(viewport) == 2 else None
    if stage is None or want is None or abs(stage.s - want.s) > 1e-3 or abs(stage.ox - want.ox) > STAGE_TOL_PX or \
            abs(stage.oy - want.oy) > STAGE_TOL_PX:
        problems.append(f"stage {record.get('stage')} is not the fit {want} of viewport {viewport}")
    problems += hb.premise_problems(record.get("premise"))
    for name in SHOTS:
        img = images.get(name)
        if img is None:
            problems.append(f"screenshot {name} missing")
        elif len(viewport) == 2 and img.shape[:2] != (viewport[1], viewport[0]):
            problems.append(f"screenshot {name} is {img.shape[1]}x{img.shape[0]}, not {viewport[0]}x{viewport[1]}")
    return problems


def _pos(readings: dict[str, hb.Reading]) -> dict[str, float]:
    return {n: r.pos for n, r in readings.items()}


def measure_run(record: dict[str, Any], images: dict[str, np.ndarray], shas: dict[str, str]) -> dict[str, Any]:
    """Every per-run reading HB-1/HB-2 need, re-derived from the saved frames; `problems` holds integrity failures."""
    problems = run_problems(record, images, shas)
    eng = engagement(record)
    problems += engagement_problems(record, eng)
    out: dict[str, Any] = {"arm": record.get("arm"), "engagement": eng}
    stage = stage_of(record)
    if stage is None or any(images.get(n) is None for n in SHOTS):
        return {**out, "problems": problems or ["unmeasurable"]}
    read = {n: hb.measure_edges(images[n], hb.STATIC_EDGES if n.startswith("s1") else hb.EDGES_12, stage) for n in SHOTS
            if not n.startswith("mm34")}
    for name, readings in read.items():
        weak = hb.weak_edges(readings)
        if weak:
            problems.append(f"{name}: edge contrast below {hb.MIN_CONTRAST}: {weak}")
    pair = hb.score_handback_pair(images["mm12-a"], images["b1-a"], stage)
    controls = {
        "glNull": hb.max_abs(hb.deltas(read["mm12-a"], read["mm12-b"])),
        "domNull": hb.max_abs(hb.deltas(read["b1-a"], read["b1-b"])),
        "slide1Null": hb.max_abs(hb.deltas(read["s1-a"], read["s1-b"])),
        "static": pair["static"],
        "shift": hb.shift_control(images["mm12-a"], hb.EDGES_12, stage),
    }
    for key in ("glNull", "domNull", "slide1Null", "static"):
        if not controls[key] <= NULL_TOL:
            problems.append(f"control {key} {controls[key]:.4f} > {NULL_TOL}")
    for dx, err in controls["shift"].items():
        if not err <= SHIFT_TOL:
            problems.append(f"control shift {dx} px error {err:.4f} > {SHIFT_TOL}")
    return {**out, "problems": problems, "max": pair["max"], "delta": pair["delta"], "controls": controls,
            "gl": _pos(read["mm12-a"]), "dom": _pos(read["b1-a"]),
            "glAuthored": pair["glAuthored"], "domAuthored": pair["domAuthored"]}


def cvc(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Max per-edge |a - b| over the GL and DOM shots of two twin runs."""
    if "gl" not in a or "gl" not in b:
        return math.nan
    return max(max(abs(a[k][n] - b[k][n]) for n in a[k]) for k in ("gl", "dom"))


def _verdict(problems: list[str], checks: dict[str, bool]) -> str:
    if problems:
        return "INCONCLUSIVE"
    return "PASS" if checks and all(checks.values()) else "FAIL"


def score_hb1(measured: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing = [arm for arm in ARMS if arm not in measured]
    if missing:
        return {"verdict": "INCONCLUSIVE", "problems": [f"arms missing: {missing}"], "checks": {}}
    problems = [f"{arm}: {p}" for arm, m in measured.items() for p in m["problems"]]
    for arm in ("off", "off2"):
        if not measured[arm].get("max", math.nan) >= KB_MIN:
            problems.append(f"KB {arm} max {measured[arm].get('max')} < {KB_MIN} (must fail)")
    twins = {f"{a}~{b}": cvc(measured[a], measured[b]) for a, b in (("on", "on2"), ("off", "off2"))}
    for name, value in twins.items():
        if not value <= CVC_TOL:
            problems.append(f"CvC {name} {value} > {CVC_TOL}")
    checks = {f"{arm}Max": measured[arm].get("max", math.nan) <= HB_MAX for arm in ("on", "on2")}
    return {"verdict": _verdict(problems, checks), "problems": problems, "checks": checks,
            "detail": {"max": {arm: m.get("max") for arm, m in measured.items()}, "cvc": twins,
                       "delta": {arm: m.get("delta") for arm, m in measured.items()},
                       "controls": {arm: m.get("controls") for arm, m in measured.items()},
                       "engagement": {arm: m.get("engagement") for arm, m in measured.items()}}}


def g2_stats_problems(record: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    api = ((record.get("g2") or {}).get("api")) or {}
    stats = api.get("stats") or {}
    problems = []
    if api.get("state") != "LIVE":
        problems.append(f"G2 state {api.get('state')!r}, not LIVE")
    if api.get("standDowns") or any((e or {}).get("kind") == "glreplay-standdown" for e in api.get("events") or []):
        problems.append(f"G2 stood down: {api.get('standDowns')}")
    if stats.get("glErrors") != 0:
        problems.append(f"G2 glErrors {stats.get('glErrors')}")
    for key, value in expected.items():
        if stats.get(key) != value:
            problems.append(f"G2 {key} {stats.get(key)!r}, expected {value!r}")
    return problems


def score_hb2(records: dict[str, dict[str, Any]], measured: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing = [arm for arm in AUTO_ARMS if arm not in measured]
    if missing:
        return {"verdict": "INCONCLUSIVE", "problems": [f"arms missing: {missing}"], "checks": {}}
    on, off = measured["on"], measured["off"]
    problems = [f"{arm}: {p}" for arm in AUTO_ARMS for p in measured[arm]["problems"]]
    problems += [f"off: {p}" for p in g2_stats_problems(records["off"], G2_EXPECTED["off"])]
    if not off.get("max", math.nan) >= KB_MIN:
        problems.append(f"KB off max {off.get('max')} < {KB_MIN} (must fail)")
    on_g2 = g2_stats_problems(records["on"], G2_EXPECTED["auto"])
    checks = {"liveVsDom": on.get("max", math.nan) <= HB_MAX, "g2Stats": not on_g2}
    stats = {arm: (((records[arm].get("g2") or {}).get("api")) or {}).get("stats") or {} for arm in AUTO_ARMS}
    return {"verdict": _verdict(problems, checks), "problems": problems, "checks": checks,
            "detail": {"max": {"on": on.get("max"), "off": off.get("max")}, "g2On": on_g2,
                       "frameLen": {arm: stats[arm].get("frameLen") for arm in AUTO_ARMS}, "g2Stats": stats}}


def band_series(record: dict[str, Any]) -> np.ndarray:
    bands = ((record.get("log") or {}).get("bands")) or []
    return hb.inflight_series(b for b in bands if b.get("label") == "mm12" and b.get("w") == CANVAS[0])


def report_hb3(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if any(arm not in records for arm in ("on", "off", "off2")):
        return {"verdict": "REPORT", "problems": ["on, off and off2 runs are needed"]}
    series = {arm: band_series(records[arm]) for arm in ("on", "off", "off2")}
    return {"verdict": "REPORT", "engagedOn": not engagement_problems(records["on"], engagement(records["on"])),
            "onVsOff": hb.inflight_compare(series["on"], series["off"]),
            "cvcOff2VsOff": hb.inflight_compare(series["off2"], series["off"])}


def report_hb4(record: dict[str, Any], images: dict[str, np.ndarray]) -> dict[str, Any]:
    stage, gl = stage_of(record), images.get(GL34)
    problems = []
    f34 = player_frames(record, "mm34")
    cap = record.get("gl34") or {}
    if gl is None or not f34 or cap.get("frame") != f34[-1]["i"]:
        problems.append("3->4 in-page capture missing or not the last player frame")
    if stage is None or images.get("mm34-a") is None or images.get("mm34-b") is None or gl is None:
        return {"problems": problems + ["unmeasurable"]}
    g = hb.measure_edges(gl, hb.EDGES_34)
    d, d2 = (hb.measure_edges(images[n], hb.EDGES_34, stage) for n in ("mm34-a", "mm34-b"))
    return {"problems": problems + [f"weak: {w}" for w in hb.weak_edges(g) + hb.weak_edges(d)],
            "domNull": hb.max_abs(hb.deltas(d, d2)),
            "domMinusGlAuthored": {e.name: stage.to_authored(d[e.name].pos, e.axis) - g[e.name].pos for e in hb.EDGES_34}}


def score_all(runs: dict[str, tuple[dict[str, Any], dict[str, np.ndarray]]], shas: dict[str, str]) -> dict[str, Any]:
    """`runs` maps `tag_of(gl, viewport, arm)` to (record, images); `shas` is `player_shas` of the fixture."""
    measured = {tag: measure_run(rec, imgs, shas) for tag, (rec, imgs) in runs.items()}
    gates: dict[str, Any] = {}
    for vp in VIEWPORTS:
        arms = {arm: measured[t] for arm in ARMS if (t := tag_of("off", vp, arm)) in measured}
        if arms:
            gates[f"HB-1 {vp[0]}x{vp[1]}"] = score_hb1(arms)
    auto = {arm: t for arm in AUTO_ARMS if (t := tag_of("auto", VIEWPORTS[0], arm)) in runs}
    if auto:
        gates["HB-2"] = score_hb2({a: runs[t][0] for a, t in auto.items()}, {a: measured[t] for a, t in auto.items()})
    off1920 = {arm: runs[t][0] for arm in ARMS if (t := tag_of("off", VIEWPORTS[0], arm)) in runs}
    if off1920:
        gates["HB-3"] = report_hb3(off1920)
    gates["HB-4"] = {"verdict": "REPORT", "runs": {tag: report_hb4(rec, imgs) for tag, (rec, imgs) in runs.items()
                                                   if rec.get("gl") == "off" and rec.get("arm") in ("on", "off")}}
    required = [f"HB-1 {w}x{h}" for w, h in VIEWPORTS] + ["HB-2"]
    missing = [name for name in required if name not in gates]
    blocking = [gates[name]["verdict"] for name in required if name in gates]
    overall = "INCONCLUSIVE" if missing else next(v for v in ("FAIL", "INCONCLUSIVE", "PASS") if v in blocking)
    return {"overall": overall, "missing": missing, "gates": gates}


def run_arm(fixture: Path, viewport: tuple[int, int], gl: str, arm: str, out_dir: Path) -> dict[str, Any]:
    import live_continuity_probe as probe
    import live_host_probe

    from obed_edom.live_host import ChromeCdp, LiveOutputHost

    class LoggedCdp(ChromeCdp):
        def start(self) -> None:
            super().start()
            self.call("Page.addScriptToEvaluateOnNewDocument", source=LOGGER_JS)

    record: dict[str, Any] = {"viewport": list(viewport), "gl": gl, "arm": arm, "mmOpacity": ARMS[arm], "steps": [],
                              "shots": {}}
    out_dir.mkdir(parents=True, exist_ok=True)
    probe.force_viewport(*viewport)
    dest = probe.prepare_export(fixture / "html-player", fixture / "html-unmodified" / "index.html",
                                f"hb-{tag_of(gl, viewport, arm)}")
    record["premise"] = hb.export_texture_rects(dest)
    host = LiveOutputHost(dest, probe.load_slides(dest), headless=True, gl_replay=gl, mm_opacity=ARMS[arm],
                          transport_factory=LoggedCdp)
    try:
        host.start()
        record["output"] = {k: host.output.get(k) for k in ("mmOpacity", "continuity")}
        transport = host._require_transport()
        evaluate = transport.evaluate

        def pair(name: str, wait_s: float) -> None:
            time.sleep(wait_s)
            for suffix in ("a", "b"):
                if suffix == "b":
                    time.sleep(PAIR_GAP_S)
                data = transport.call("Page.captureScreenshot", format="png")["data"]
                (out_dir / f"{name}-{suffix}.png").write_bytes(base64.b64decode(data))
                record["shots"][f"{name}-{suffix}"] = {"file": f"{name}-{suffix}.png", "t": time.monotonic()}
                if name == "mm12":
                    record.setdefault("mm12Dom", []).append(evaluate(SWAP_READ_JS))

        record["loggerInstalled"] = evaluate("!!window.__OBED_HB__")
        host.execute("show")
        record["decoded"] = probe.wait_for_decode(host)
        record["stage"] = evaluate(probe.STAGE_MAP_JS)
        pair("s1", SLIDE1_WAIT_S)
        for label, expect, _ in mmo.PLAN:
            evaluate(f"window.__OBED_HB__.setLabel({json.dumps(label)}, {json.dumps(STEP_CFG.get(label, {}))})")
            step: dict[str, Any] = {"label": label, "expectHash": expect, "hashBefore": evaluate(probe.HASH_JS)}
            host.execute("advance")
            _, step["settleS"] = live_host_probe.wait_for_settlement(host, timeout_s=30)
            step["hashAfter"] = mmo.wait_for_hash(evaluate, probe.HASH_JS, expect[1] if expect else None)
            record["steps"].append(step)
            if label == "mm12" and gl == "auto":
                started = time.monotonic()
                while time.monotonic() - started < mmo.LIVE_WAIT_S:
                    state = ((evaluate(probe.GL_REPLAY_READ_JS) or {}).get("api") or {}).get("state")
                    if state in ("LIVE", "STANDDOWN", "RETIRED"):
                        break
                    time.sleep(0.1)
                time.sleep(mmo.LIVE_HOLD_S)
                record["g2"] = evaluate(probe.GL_REPLAY_READ_JS)
                pair("mm12", 0.0)
            elif label == "mm12":
                pair("mm12", GL_SETTLE_WAIT_S)
            elif label in ("b1", "mm34"):
                pair(label, DOM_WAIT_S)
            else:
                time.sleep(1.5)
        record["log"] = evaluate(LOG_READ_JS, deadline_s=60)
        cap = evaluate("window.__OBED_HB__.alphaPng('mm34')", deadline_s=60)
        if cap:
            (out_dir / f"{GL34}.png").write_bytes(base64.b64decode(cap.pop("png").split(",", 1)[1]))
            record["gl34"] = {**cap, "file": f"{GL34}.png"}
    except Exception:  # noqa: BLE001
        record["error"] = traceback.format_exc()
    finally:
        try:
            host.stop()
        except Exception as exc:  # noqa: BLE001
            record["stopError"] = str(exc)
        shutil.rmtree(dest, ignore_errors=True)
    (out_dir / "record.json").write_text(json.dumps(record))
    return record


def load_png(path: Path) -> np.ndarray | None:
    from PIL import Image

    if not path.is_file():
        return None
    return np.asarray(Image.open(io.BytesIO(path.read_bytes())).convert("RGB"))


def load_runs(out: Path) -> dict[str, tuple[dict[str, Any], dict[str, np.ndarray]]]:
    runs = {}
    for path in sorted((out / "runs").glob("*/record.json")):
        record = json.loads(path.read_text())
        files = {name: (record.get("shots") or {}).get(name, {}).get("file") for name in SHOTS}
        files[GL34] = (record.get("gl34") or {}).get("file")
        images = {name: img for name, f in files.items() if f and (img := load_png(path.parent / f)) is not None}
        runs[tag_of(record["gl"], tuple(record["viewport"]), record["arm"])] = (record, images)
    return runs


def parse_viewport(value: str) -> tuple[int, int]:
    w, h = value.lower().split("x")
    return int(w), int(h)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--score", type=Path, help="re-score the runs saved under DIR/runs without a browser")
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--viewports", default=",".join(f"{w}x{h}" for w, h in VIEWPORTS))
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--gl", default="off,auto", help="auto runs only the on and off arms at 1920x1080 (HB-2)")
    args = parser.parse_args(argv)
    if (args.out is None) == (args.score is None):
        parser.error("give exactly one of --out or --score")
    args.viewports = [parse_viewport(v) for v in args.viewports.split(",") if v]
    args.arms = [a for a in args.arms.split(",") if a]
    args.gl = [g for g in args.gl.split(",") if g]
    if not set(args.arms) <= set(ARMS) or not set(args.gl) <= {"off", "auto"} or not set(args.viewports) <= set(VIEWPORTS):
        parser.error(f"--arms takes {','.join(ARMS)}; --gl off,auto; --viewports from {VIEWPORTS}")
    return args


def plan_runs(args: argparse.Namespace) -> list[tuple[tuple[int, int], str, str]]:
    runs = [(vp, "off", arm) for vp in args.viewports for arm in args.arms] if "off" in args.gl else []
    if "auto" in args.gl and VIEWPORTS[0] in args.viewports:
        runs += [(VIEWPORTS[0], "auto", arm) for arm in AUTO_ARMS if arm in args.arms]
    return runs


def _rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(v) for v in value]
    return value


def _fmt(value: Any) -> str:
    return json.dumps(_rounded(value), default=str)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = args.score or args.out
    if args.out is not None:
        for vp, gl, arm in plan_runs(args):
            running = mmo.headless_chromes()
            if running >= mmo.MAX_HEADLESS:
                raise SystemExit(f"{running} headless Chromes already running (limit {mmo.MAX_HEADLESS}); refusing to start another")
            tag = tag_of(gl, vp, arm)
            record = run_arm(args.fixture, vp, gl, arm, out / "runs" / tag)
            print(f"{tag}: {'error' if record.get('error') else 'ok'}", flush=True)
    verdict = score_all(load_runs(out), player_shas(args.fixture))
    (out / "verdict.json").write_text(json.dumps(verdict, indent=1, default=str))
    for name, gate in verdict["gates"].items():
        if name == "HB-4":
            for tag, row in gate["runs"].items():
                print(f"HB-4 {tag}: {_fmt(row.get('domMinusGlAuthored'))} {row.get('problems') or ''}")
            continue
        if name == "HB-3":
            print(f"HB-3: REPORT engagedOn={gate.get('engagedOn')} {gate.get('problems') or ''}")
            for key in ("onVsOff", "cvcOff2VsOff"):
                print(f"  {key}: {_fmt({k: v for k, v in (gate.get(key) or {}).items() if k != 'curve'})}")
            continue
        detail = gate.get("detail") or {}
        print(f"{name}: {gate['verdict']} max={_fmt(detail.get('max'))} cvc={_fmt(detail.get('cvc'))} "
              f"{'frameLen=' + _fmt(detail['frameLen']) + ' ' if 'frameLen' in detail else ''}"
              f"{gate.get('problems') or ''}")
    missing = f" (missing {', '.join(verdict['missing'])})" if verdict["missing"] else ""
    print(f"overall: {verdict['overall']}{missing}")
    return 0 if verdict["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
