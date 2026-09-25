#!/usr/bin/env python3
"""Headless MO-1 / MO-4 / MO-5 instrument for the Magic Move opacity patch (plan `keynote_live_mm_opacity` §10).

One fresh headless Chrome per arm, driven through `LiveOutputHost` on the binary-counter fixture (`output/p2-binary`) at
1920x1080. An innermost logger (`Page.addScriptToEvaluateOnNewDocument`, true natives) records, per clear-delimited frame,
every draw's program and the `Opacity` value in effect for it, and at the settle frame of each Magic Move one readPixels pair:
the settle ROI before slot 4 and the full buffer after the frame's last draw (settle ROI + hash).

Arms, per GL-replay mode (`off`, `auto`):
  on    mm_opacity="auto" (the patch)
  off   mm_opacity="off" (today's player bytes: the KB and the twin)
  off2  mm_opacity="off" again (control vs control)
  sq    the patch with `__obedNodeOpacity` spliced to multiply the model value in (alpha squared: the KB)

Gates (each counts only if its CvC reads 0 and its KB FAILs, else INCONCLUSIVE; an integrity problem is INCONCLUSIVE):
  MO-1  every slot-4 draw of the 1->2 move (>= 20) and every G2 LIVE draw of its program reads Opacity == alpha (float32);
        every other ordinal of 1->2 and every ordinal of 3->4 matches the patch-off twin; settle max |P - E| <= 1 with
        E = alpha*S + (1 - alpha*S_a)*B (premultiplied, S = the twin's settle P). A GL-on gate is VOID if G2 stands down in
        either twin.
  MO-4  (GL auto) patch on: unproven == [{4, rest-opacity}], rest slot 4 == alpha; patch off: unproven == [], rest
        [1,0,1,1,1]; LIVE screenshot ROI_top identical on vs off.
  MO-5  settle-frame hash of 3->4 identical on vs off; of 1->2 different.

usage: uv run python scripts/mm_opacity_probe.py --out DIR [--gl off,auto] [--arms on,off,off2,sq]
       uv run python scripts/mm_opacity_probe.py --score DIR
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import struct
import subprocess
import sys
import time
import traceback
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

FIXTURE = Path("/Users/anyhowclick/Desktop/work/obed-edom/output/p2-binary")
ALPHA = 0.29468628764152527
VIEWPORT = (1920, 1080)
SLOT = 4
MIN_SLOT_DRAWS = 20
SETTLE_TOL = 1.0
MOVE_MS = 1500.0
SETTLE_WINDOW_MS = 60.0
SETTLE_ROI_GL = (793, 205, 16, 148)
ROI_TOP = (793, 727, 16, 58)
REST_OFF = [1, 0, 1, 1, 1]
UNPROVEN_ON = [{"slot": SLOT, "reason": "rest-opacity"}]
G2_FRAMES = ("ARM-POST", "LIVE")
LIVE_WAIT_S = 15.0
LIVE_HOLD_S = 2.5
MAX_HEADLESS = 3
ARMS = {"on": "auto", "off": "off", "off2": "off", "sq": "auto"}
PLAN = (
    ("mm12", ("#1", "#2"), {"settleFromMs": MOVE_MS - SETTLE_WINDOW_MS, "roi": list(SETTLE_ROI_GL), "roiOrdinal": SLOT}),
    ("b1", None, {}),
    ("b2", None, {}),
    ("b3", None, {}),
    ("d23", None, {}),
    ("mm34", ("#7", "#8"), {"settleFromMs": MOVE_MS - SETTLE_WINDOW_MS}),
)
SQUARE_SPLICE = (b"?g.to.scalar:null:B.opacity", b"?g.to.scalar*B.opacity:null:B.opacity")

LOGGER_JS = r"""
(function(){
  if (window.__OBED_MMO__) return;
  var protos = [];
  if (window.WebGLRenderingContext) protos.push(WebGLRenderingContext.prototype);
  if (window.WebGL2RenderingContext) protos.push(WebGL2RenderingContext.prototype);
  var natives = protos.map(function(P){ return {getParameter: P.getParameter, readPixels: P.readPixels}; });
  function nat(g, name){
    for (var i = 0; i < protos.length; i++) if (protos[i].isPrototypeOf(g)) return natives[i][name];
    return null;
  }
  var ids = new WeakMap(), nextId = {ctx: 0, prog: 0};
  function idOf(x, kind){ if (!x) return null; if (!ids.has(x)) ids.set(x, nextId[kind]++); return ids.get(x); }
  var locs = new WeakMap(), opacity = new WeakMap(), ctxState = new WeakMap();
  var M = window.__OBED_MMO__ = {label: 'init', cfg: {}, frames: [], settle: {}, labelStart: {}, errors: [],
    setLabel: function(label, cfg){ M.label = label; M.cfg = cfg || {}; return true; }};
  function stateOf(g){
    var s = ctxState.get(g);
    if (!s){ s = {prog: null, frame: null, lastPlayerDraws: null}; ctxState.set(g, s); }
    return s;
  }
  function g2(){ var a = window.__OBED_GL_REPLAY__; return a && a.version ? String(a.state) : null; }
  function isPlayer(f){ return f.g2 !== 'ARM-POST' && f.g2 !== 'LIVE'; }
  function readRoi(g, r){
    var px = new Uint8Array(r[2] * r[3] * 4);
    nat(g, 'readPixels').call(g, r[0], r[1], r[2], r[3], g.RGBA, g.UNSIGNED_BYTE, px);
    return Array.prototype.slice.call(px);
  }
  function readFull(g, r){
    var w = g.drawingBufferWidth, h = g.drawingBufferHeight, px = new Uint8Array(w * h * 4);
    nat(g, 'readPixels').call(g, 0, 0, w, h, g.RGBA, g.UNSIGNED_BYTE, px);
    var u = new Uint32Array(px.buffer), a = 0x811c9dc5, b = 0x9747b28c;
    for (var i = 0; i < u.length; i++){ a = Math.imul(a ^ u[i], 16777619); b = Math.imul(b ^ u[i], 2246822519) ^ (b >>> 13); }
    var out = {w: w, h: h, hash: (a >>> 0).toString(16) + ':' + (b >>> 0).toString(16), P: null};
    if (r){
      out.P = [];
      for (var y = r[1]; y < r[1] + r[3]; y++)
        for (var k = (y * w + r[0]) * 4, e = k + r[2] * 4; k < e; k++) out.P.push(px[k]);
    }
    return out;
  }
  function wrap(name, fn){
    protos.forEach(function(P){
      var orig = P[name];
      P[name] = function(){ return fn.call(this, orig, arguments); };
    });
  }
  wrap('getUniformLocation', function(orig, args){
    var loc = orig.apply(this, args);
    try { if (loc && String(args[1]) === 'Opacity') locs.set(loc, args[0]); } catch (e) { M.errors.push(String(e)); }
    return loc;
  });
  wrap('useProgram', function(orig, args){
    try { stateOf(this).prog = args[0] || null; } catch (e) { M.errors.push(String(e)); }
    return orig.apply(this, args);
  });
  wrap('uniform1f', function(orig, args){
    try { var p = args[0] ? locs.get(args[0]) : null; if (p) opacity.set(p, args[1]); } catch (e) { M.errors.push(String(e)); }
    return orig.apply(this, args);
  });
  wrap('clear', function(orig, args){
    try {
      var s = stateOf(this), t = performance.now();
      if (s.frame && isPlayer(s.frame)) s.lastPlayerDraws = s.frame.draws.length;
      if (M.labelStart[M.label] == null) M.labelStart[M.label] = t;
      s.frame = {label: M.label, ctx: idOf(this, 'ctx'), i: M.frames.length, el: t - M.labelStart[M.label], g2: g2(),
                 draws: [], B: null};
      M.frames.push(s.frame);
    } catch (e) { M.errors.push(String(e)); }
    return orig.apply(this, args);
  });
  function draw(orig, args){
    var s, f, ord = -1, cfg = M.cfg, tail = false;
    try {
      s = stateOf(this); f = s.frame;
      if (f){
        ord = f.draws.length;
        f.draws.push([idOf(s.prog, 'prog'), s.prog && opacity.has(s.prog) ? opacity.get(s.prog) : null]);
        tail = cfg.settleFromMs != null && isPlayer(f) && f.el >= cfg.settleFromMs &&
               nat(this, 'getParameter').call(this, this.FRAMEBUFFER_BINDING) === null;
        if (tail && cfg.roi && ord === cfg.roiOrdinal) f.B = readRoi(this, cfg.roi);
      }
    } catch (e) { M.errors.push(String(e)); tail = false; }
    var rv = orig.apply(this, args);
    try {
      if (tail && s.lastPlayerDraws != null && ord === s.lastPlayerDraws - 1){
        var full = readFull(this, cfg.roi || null);
        M.settle[f.label] = {frame: f.i, ord: ord, el: f.el, g2: f.g2, B: f.B, P: full.P, w: full.w, h: full.h,
                             hash: full.hash};
      }
    } catch (e) { M.errors.push(String(e)); }
    return rv;
  }
  wrap('drawArrays', draw);
  wrap('drawElements', draw);
})();
"""

LOG_READ_JS = (
    "(function(){var M=window.__OBED_MMO__;return M?{frames:M.frames,settle:M.settle,errors:M.errors,"
    "labelStart:M.labelStart}:null;})()"
)


def f32(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def square_splice(player: bytes) -> bytes:
    """Known-bad alpha-squared player: each node contributes its animated value times its model value."""
    before, after = SQUARE_SPLICE
    if player.count(before) != 1:
        raise ValueError("alpha-squared splice anchor is missing or ambiguous")
    return player.replace(before, after)


def player_frames(run: dict[str, Any], label: str) -> list[dict[str, Any]]:
    log = run.get("log") or {}
    return [f for f in log.get("frames") or [] if f.get("label") == label and f.get("g2") not in G2_FRAMES and f.get("draws")]


def live_frames(run: dict[str, Any], label: str) -> list[dict[str, Any]]:
    log = run.get("log") or {}
    return [f for f in log.get("frames") or [] if f.get("label") == label and f.get("g2") == "LIVE"]


def ordinal_sequences(frames: list[dict[str, Any]]) -> dict[int, list[float | None]]:
    width = max((len(f["draws"]) for f in frames), default=0)
    return {o: [f32(f["draws"][o][1]) for f in frames if len(f["draws"]) == width] for o in range(width)}


def _collapse(values: list[float | None]) -> list[float | None]:
    out: list[float | None] = []
    for value in values:
        if not out or out[-1] != value:
            out.append(value)
    return out


def _direction(values: list[float | None]) -> int | None:
    if any(v is None for v in values):
        return None
    steps = {(b > a) - (b < a) for a, b in pairwise(values)}
    return steps.pop() if len(steps) == 1 else None


def sequences_match(a: list[float | None], b: list[float | None]) -> bool:
    """Constant sequences must be equal; an eased lerp (timed by rAF) must share its settle value and direction."""
    ca, cb = _collapse(a), _collapse(b)
    if not ca or not cb or None in ca or None in cb:
        return False
    if len(ca) == 1 or len(cb) == 1:
        return ca == cb
    direction = _direction(ca)
    return direction is not None and direction == _direction(cb) and ca[-1] == cb[-1]


def slot_program(frames: list[dict[str, Any]], slot: int = SLOT) -> tuple[Any, list[str]]:
    problems = []
    progs = {f["draws"][slot][0] for f in frames if len(f["draws"]) > slot}
    if len(progs) != 1:
        problems.append(f"slot {slot} program is not unique across the move: {sorted(map(str, progs))}")
    if any(len(f["draws"]) <= slot for f in frames):
        problems.append(f"a move frame has no slot {slot} draw")
    return (next(iter(progs)) if len(progs) == 1 else None), problems


def g2_void(run: dict[str, Any]) -> str | None:
    if run.get("gl") != "auto":
        return None
    api = ((run.get("g2") or {}).get("api")) or {}
    if api.get("state") != "LIVE":
        return f"G2 did not hold LIVE (state {api.get('state')!r})"
    if any((e or {}).get("kind") == "glreplay-standdown" for e in api.get("events") or []):
        return "G2 stood down"
    return None


def run_problems(run: dict[str, Any]) -> list[str]:
    problems = []
    if run.get("error"):
        problems.append(f"run error: {str(run['error']).strip().splitlines()[-1]}")
    log = run.get("log")
    if not log:
        return problems + ["no logger output"]
    if log.get("errors"):
        problems.append(f"logger errors: {log['errors'][:3]}")
    for step in run.get("steps") or []:
        expected = step.get("expectHash")
        if expected and [step.get("hashBefore"), step.get("hashAfter")] != list(expected):
            problems.append(f"{step['label']}: hash {step.get('hashBefore')}->{step.get('hashAfter')}, expected {expected}")
    for label, roi in (("mm12", True), ("mm34", False)):
        frames = player_frames(run, label)
        settle = (log.get("settle") or {}).get(label)
        if not frames:
            problems.append(f"{label}: no player frames")
            continue
        if not settle:
            problems.append(f"{label}: no settle read")
            continue
        last = frames[-1]
        if settle.get("frame") != last["i"] or settle.get("ord") != len(last["draws"]) - 1:
            problems.append(f"{label}: settle read is not the last draw of the last player frame")
        if roi and (settle.get("ord") != SLOT or not settle.get("B") or not settle.get("P")):
            problems.append(f"{label}: settle ROI pair missing or not at slot {SLOT}")
    return problems


def settle_residual(cand: dict[str, Any], twin: dict[str, Any], alpha: float) -> tuple[float | None, list[str]]:
    c = ((cand.get("log") or {}).get("settle") or {}).get("mm12") or {}
    t = ((twin.get("log") or {}).get("settle") or {}).get("mm12") or {}
    if not c.get("B") or not c.get("P") or not t.get("P"):
        return None, ["settle ROI missing"]
    B = np.asarray(c["B"], dtype=float).reshape(-1, 4) / 255.0
    P = np.asarray(c["P"], dtype=float).reshape(-1, 4)
    S = np.asarray(t["P"], dtype=float).reshape(-1, 4) / 255.0
    if not (B.shape == P.shape == S.shape):
        return None, ["settle ROI sizes differ"]
    if not np.all(S[:, 3] == 1.0):
        return None, ["twin settle ROI is not opaque, so its P is not S"]
    E = alpha * S + (1.0 - alpha * S[:, 3:4]) * B
    return float(np.max(np.abs(P - E * 255.0))), []


def _verdict(problems: list[str], checks: dict[str, bool], void: str | None = None) -> str:
    if void:
        return "VOID"
    if problems:
        return "INCONCLUSIVE"
    return "PASS" if all(checks.values()) else "FAIL"


def score_mo1(cand: dict[str, Any], twin: dict[str, Any], alpha: float = ALPHA) -> dict[str, Any]:
    problems = run_problems(cand) + [f"twin: {p}" for p in run_problems(twin)]
    void = g2_void(cand) or g2_void(twin)
    checks: dict[str, bool] = {}
    detail: dict[str, Any] = {}
    frames, twin_frames = player_frames(cand, "mm12"), player_frames(twin, "mm12")
    prog, slot_problems = slot_program(frames)
    problems += slot_problems
    slot_values = [f32(f["draws"][SLOT][1]) for f in frames if len(f["draws"]) > SLOT]
    detail["slotDraws"] = len(slot_values)
    detail["slotValues"] = sorted({v for v in slot_values if v is not None}) + ([None] if None in slot_values else [])
    if len(slot_values) < MIN_SLOT_DRAWS:
        problems.append(f"only {len(slot_values)} slot-{SLOT} draws (< {MIN_SLOT_DRAWS})")
    checks["slotAlpha"] = bool(slot_values) and all(v == f32(alpha) for v in slot_values)
    if cand.get("gl") == "auto":
        live = [f32(v) for f in live_frames(cand, "mm12") for p, v in f["draws"] if p == prog]
        detail["liveSlotDraws"] = len(live)
        if not live and not void:
            problems.append("no G2 LIVE draw of the slot program")
        checks["liveAlpha"] = bool(live) and all(v == f32(alpha) for v in live)
    seq, twin_seq = ordinal_sequences(frames), ordinal_sequences(twin_frames)
    if len(seq) != len(twin_seq):
        problems.append(f"1->2 draw count {len(seq)} vs twin {len(twin_seq)}")
    detail["othersMismatch"] = [o for o in seq if o != SLOT and not sequences_match(seq[o], twin_seq.get(o, []))]
    checks["othersMatchTwin"] = not detail["othersMismatch"] and len(seq) == len(twin_seq)
    seq34, twin34 = ordinal_sequences(player_frames(cand, "mm34")), ordinal_sequences(player_frames(twin, "mm34"))
    detail["move34Mismatch"] = [o for o in seq34 if not sequences_match(seq34[o], twin34.get(o, []))]
    checks["move34MatchesTwin"] = bool(seq34) and not detail["move34Mismatch"] and len(seq34) == len(twin34)
    residual, residual_problems = settle_residual(cand, twin, alpha)
    problems += residual_problems
    detail["settleResidual"] = residual
    checks["settleBlend"] = residual is not None and residual <= SETTLE_TOL
    return {"verdict": _verdict(problems, checks, void), "checks": checks, "problems": problems, "void": void, "detail": detail}


def score_cvc_mo1(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    problems = run_problems(a) + run_problems(b)
    checks = {}
    for label in ("mm12", "mm34"):
        sa, sb = ordinal_sequences(player_frames(a, label)), ordinal_sequences(player_frames(b, label))
        checks[f"{label}Uniforms"] = bool(sa) and len(sa) == len(sb) and all(sequences_match(sa[o], sb[o]) for o in sa)
    pa = ((a.get("log") or {}).get("settle") or {}).get("mm12") or {}
    pb = ((b.get("log") or {}).get("settle") or {}).get("mm12") or {}
    checks["settleP"] = bool(pa.get("P")) and pa.get("P") == pb.get("P")
    return {"verdict": _verdict(problems, checks, g2_void(a) or g2_void(b)), "checks": checks, "problems": problems}


def _g2_stats(run: dict[str, Any]) -> dict[str, Any]:
    return (((run.get("g2") or {}).get("api")) or {}).get("stats") or {}


def score_mo4(cand: dict[str, Any], twin: dict[str, Any], alpha: float = ALPHA) -> dict[str, Any]:
    problems = []
    for name, run in (("", cand), ("twin: ", twin)):
        if run.get("gl") != "auto":
            problems.append(f"{name}not a GL-replay run")
        if run.get("error"):
            problems.append(f"{name}run error")
        if not _g2_stats(run):
            problems.append(f"{name}no G2 stats")
        if not run.get("liveGreen"):
            problems.append(f"{name}no LIVE screenshot ROI")
        if run.get("stage") != {"x": 0, "y": 0, "width": VIEWPORT[0], "height": VIEWPORT[1]}:
            problems.append(f"{name}stage is not the full {VIEWPORT} viewport: {run.get('stage')}")
    void = g2_void(cand) or g2_void(twin)
    on, off = _g2_stats(cand), _g2_stats(twin)
    rest = on.get("restOpacity") or []
    checks = {
        "unprovenOn": on.get("opacityUnproven") == UNPROVEN_ON,
        "restSlotAlpha": len(rest) > SLOT and f32(rest[SLOT]) == f32(alpha),
        "restOthersOff": rest[:SLOT] == REST_OFF[:SLOT],
        "unprovenOff": off.get("opacityUnproven") == [],
        "restOff": off.get("restOpacity") == REST_OFF,
        "liveGreenEqual": bool(cand.get("liveGreen")) and cand.get("liveGreen") == twin.get("liveGreen"),
    }
    detail = {"rest": rest, "unproven": on.get("opacityUnproven"), "restTwin": off.get("restOpacity"),
              "unprovenTwin": off.get("opacityUnproven"), "occludedBands": on.get("occludedBands"),
              "occludedBandsTwin": off.get("occludedBands"), "greenMean": _mean(cand.get("liveGreen")),
              "greenMeanTwin": _mean(twin.get("liveGreen"))}
    return {"verdict": _verdict(problems, checks, void), "checks": checks, "problems": problems, "void": void, "detail": detail}


def score_cvc_mo4(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    problems = [p for p in score_mo4(a, b)["problems"]]
    sa, sb = _g2_stats(a), _g2_stats(b)
    checks = {
        "liveGreen": bool(a.get("liveGreen")) and a.get("liveGreen") == b.get("liveGreen"),
        "rest": sa.get("restOpacity") == sb.get("restOpacity"),
        "unproven": sa.get("opacityUnproven") == sb.get("opacityUnproven"),
    }
    return {"verdict": _verdict(problems, checks, g2_void(a) or g2_void(b)), "checks": checks, "problems": problems}


def _mean(pixels: Any) -> list[float] | None:
    if not pixels:
        return None
    return [round(float(v), 3) for v in np.asarray(pixels, dtype=float).reshape(-1, 3).mean(axis=0)]


def _hash(run: dict[str, Any], label: str) -> str | None:
    return (((run.get("log") or {}).get("settle") or {}).get(label) or {}).get("hash")


def score_mo5(cand: dict[str, Any], twin: dict[str, Any]) -> dict[str, Any]:
    problems = []
    for name, run in (("", cand), ("twin: ", twin)):
        if run.get("error"):
            problems.append(f"{name}run error")
        for label in ("mm12", "mm34"):
            if not _hash(run, label):
                problems.append(f"{name}{label}: no settle hash")
    checks = {
        "move34Equal": _hash(cand, "mm34") is not None and _hash(cand, "mm34") == _hash(twin, "mm34"),
        "move12Differs": _hash(cand, "mm12") is not None and _hash(cand, "mm12") != _hash(twin, "mm12"),
    }
    return {"verdict": _verdict(problems, checks), "checks": checks, "problems": problems}


def score_cvc_mo5(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    problems = [p for p in score_mo5(a, b)["problems"]]
    checks = {f"{label}Equal": _hash(a, label) is not None and _hash(a, label) == _hash(b, label) for label in ("mm12", "mm34")}
    return {"verdict": _verdict(problems, checks), "checks": checks, "problems": problems}


def gate(primary: dict[str, Any], cvc: dict[str, Any] | None, kbs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """PASS/FAIL only when the CvC reads 0 and every KB FAILs; otherwise INCONCLUSIVE (VOID passes through)."""
    reasons = []
    if cvc is None:
        reasons.append("no control-vs-control pair")
    elif cvc["verdict"] != "PASS":
        reasons.append(f"CvC {cvc['verdict']}")
    for name, kb in kbs.items():
        if kb is None:
            reasons.append(f"KB {name} missing")
        elif kb["verdict"] != "FAIL":
            reasons.append(f"KB {name} {kb['verdict']} (must FAIL)")
    if primary["verdict"] == "VOID":
        verdict = "VOID"
    elif primary["verdict"] == "INCONCLUSIVE" or reasons:
        verdict = "INCONCLUSIVE"
    else:
        verdict = primary["verdict"]
    return {"verdict": verdict, "reasons": reasons, "primary": primary, "cvc": cvc, "kb": kbs}


def score_mode(gl: str, runs: dict[str, dict[str, Any]], alpha: float = ALPHA) -> dict[str, dict[str, Any]]:
    on, off, off2, sq = (runs.get(k) for k in ("on", "off", "off2", "sq"))
    if on is None or off is None:
        names = ("MO-1", "MO-4", "MO-5") if gl == "auto" else ("MO-1", "MO-5")
        return {n: {"verdict": "INCONCLUSIVE", "reasons": ["patch-on or patch-off run missing"]} for n in names}
    out = {
        "MO-1": gate(score_mo1(on, off, alpha), score_cvc_mo1(off, off2) if off2 else None, {
            "patch-off": score_mo1(off2, off, alpha) if off2 else None,
            "alpha-squared": score_mo1(sq, off, alpha) if sq else None,
        }),
        "MO-5": gate(score_mo5(on, off), score_cvc_mo5(off, off2) if off2 else None, {}),
    }
    if gl == "auto":
        out["MO-4"] = gate(score_mo4(on, off, alpha), score_cvc_mo4(off, off2) if off2 else None, {
            "alpha-squared": score_mo4(sq, off, alpha) if sq else None,
        })
    return out


def score_all(runs: dict[str, dict[str, dict[str, Any]]], alpha: float = ALPHA) -> dict[str, Any]:
    modes = {gl: score_mode(gl, arms, alpha) for gl, arms in runs.items()}
    verdicts = [g["verdict"] for m in modes.values() for g in m.values()]
    order = ("FAIL", "INCONCLUSIVE", "VOID", "PASS")
    overall = next((v for v in order if v in verdicts), "INCONCLUSIVE")
    return {"overall": overall, "modes": modes}


def headless_chromes() -> int:
    out = subprocess.run(["pgrep", "-f", "--", "--headless=new"], capture_output=True, text=True, check=False).stdout.split()
    count = 0
    for pid in out:
        cmd = subprocess.run(["ps", "-o", "command=", "-p", pid], capture_output=True, text=True, check=False).stdout
        count += "--type=" not in cmd and "Google Chrome" in cmd
    return count


@contextlib.contextmanager
def square_player(active: bool) -> Iterator[None]:
    from obed_edom import live_host

    if not active:
        yield
        return
    real = live_host.patch_player

    def patched(player: bytes, *, mm_opacity: bool = True) -> bytes:
        out = real(player, mm_opacity=mm_opacity)
        return square_splice(out) if mm_opacity else out

    live_host.patch_player = patched
    try:
        yield
    finally:
        live_host.patch_player = real


def run_arm(fixture: Path, gl: str, arm: str) -> dict[str, Any]:
    import live_continuity_probe as probe
    import live_host_probe

    from obed_edom.live_host import ChromeCdp, LiveOutputHost

    class LoggedCdp(ChromeCdp):
        def start(self) -> None:
            super().start()
            self.call("Page.addScriptToEvaluateOnNewDocument", source=LOGGER_JS)

    record: dict[str, Any] = {"gl": gl, "arm": arm, "mmOpacityKwarg": ARMS[arm], "steps": []}
    probe.force_viewport(*VIEWPORT)
    dest = probe.prepare_export(fixture / "html-player", fixture / "html-unmodified" / "index.html", f"mmo-{gl}-{arm}")
    host = LiveOutputHost(dest, probe.load_slides(dest), headless=True, gl_replay=gl, mm_opacity=ARMS[arm],
                          transport_factory=LoggedCdp)
    try:
        with square_player(arm == "sq"):
            host.start()
        record["output"] = {k: host.output.get(k) for k in ("mmOpacity", "continuity")}
        transport = host._require_transport()
        evaluate = transport.evaluate
        record["loggerInstalled"] = evaluate("!!window.__OBED_MMO__")
        host.execute("show")
        record["decoded"] = probe.wait_for_decode(host)
        record["stage"] = evaluate(
            "(function(){var r=document.getElementById('stage').getBoundingClientRect();"
            "return {x:r.x,y:r.y,width:r.width,height:r.height};})()")
        time.sleep(2.0)
        for label, expect, cfg in PLAN:
            evaluate(f"window.__OBED_MMO__.setLabel({json.dumps(label)}, {json.dumps(cfg)})")
            step: dict[str, Any] = {"label": label, "expectHash": expect, "hashBefore": evaluate(probe.HASH_JS)}
            host.execute("advance")
            _, step["settleS"] = live_host_probe.wait_for_settlement(host, timeout_s=30)
            if label == "mm12" and gl == "auto":
                started = time.monotonic()
                while time.monotonic() - started < LIVE_WAIT_S:
                    state = ((evaluate(probe.GL_REPLAY_READ_JS) or {}).get("api") or {}).get("state")
                    if state in ("LIVE", "STANDDOWN", "RETIRED"):
                        break
                    time.sleep(0.1)
                time.sleep(LIVE_HOLD_S)
                record["g2"] = evaluate(probe.GL_REPLAY_READ_JS)
                frame = probe.decode_png(transport.call("Page.captureScreenshot", format="png")["data"])
                x, y, w, h = ROI_TOP
                record["liveGreen"] = frame[y:y + h, x:x + w].reshape(-1).tolist()
            else:
                time.sleep(LIVE_HOLD_S if label.startswith("mm") else 1.5)
            step["hashAfter"] = evaluate(probe.HASH_JS)
            record["steps"].append(step)
        record["log"] = evaluate(LOG_READ_JS, deadline_s=60)
    except Exception:  # noqa: BLE001
        record["error"] = traceback.format_exc()
    finally:
        try:
            host.stop()
        except Exception as exc:  # noqa: BLE001
            record["stopError"] = str(exc)
        shutil.rmtree(dest, ignore_errors=True)
    return record


def load_runs(out: Path) -> dict[str, dict[str, dict[str, Any]]]:
    runs: dict[str, dict[str, dict[str, Any]]] = {}
    for path in sorted((out / "runs").glob("*.json")):
        record = json.loads(path.read_text())
        runs.setdefault(record["gl"], {})[record["arm"]] = record
    return runs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--score", type=Path, help="re-score the runs saved under DIR/runs without a browser")
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--gl", default="off,auto")
    parser.add_argument("--arms", default=",".join(ARMS))
    args = parser.parse_args(argv)
    if (args.out is None) == (args.score is None):
        parser.error("give exactly one of --out or --score")
    args.gl = [g for g in args.gl.split(",") if g]
    args.arms = [a for a in args.arms.split(",") if a]
    if not set(args.gl) <= {"off", "auto"} or not set(args.arms) <= set(ARMS):
        parser.error("--gl takes off,auto; --arms takes " + ",".join(ARMS))
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = args.score or args.out
    if args.out is not None:
        (out / "runs").mkdir(parents=True, exist_ok=True)
        for gl in args.gl:
            for arm in args.arms:
                running = headless_chromes()
                if running >= MAX_HEADLESS:
                    raise SystemExit(f"{running} headless Chromes already running (limit {MAX_HEADLESS}); refusing to start another")
                record = run_arm(args.fixture, gl, arm)
                (out / "runs" / f"{gl}-{arm}.json").write_text(json.dumps(record))
                print(f"{gl}-{arm}: {'error' if record.get('error') else 'ok'}", flush=True)
    verdict = score_all(load_runs(out))
    (out / "verdict.json").write_text(json.dumps(verdict, indent=1, default=str))
    for gl, gates in verdict["modes"].items():
        for name, result in gates.items():
            print(f"{gl} {name}: {result['verdict']} {result.get('reasons') or ''}")
    print(f"overall: {verdict['overall']}")
    return 0 if verdict["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
