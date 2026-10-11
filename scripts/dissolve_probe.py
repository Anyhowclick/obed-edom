#!/usr/bin/env python3
"""DX-1 headless gate for the dissolve cross-fade, cut and movie-freeze patch (plan `keynote_live_dissolve_crossfade` §9.1).

One fresh headless Chrome per arm (1920x1080, DSF 1, its own port), driven through `LiveOutputHost` (attach on the alpha
page, launch on the screen page). The resolver serves html-unmodified's index.html, player and slide JSON, PDFs from a fresh
scratch strip (`html_alpha_probe.strip_export_pdf_bg_fills`), decodable movies (P2: html-player H.264; DX-M: the binary
counter re-encoded with an `ENCODINGS` entry unless Q0b qualified the untagged tuple; tone arms: the tone movie, same
encoder) and the arm's in-memory JSON edits, and records provenance. The served player is `live_runtime.patch_player` for
the arm's mode plus at most one counted splice (`SPLICES`; a count mismatch refuses); its digest is checked against
`live_runtime.SUPPORTED_PLAYERS` at score time.

The innermost hook (`HOOK_JS`) records per rAF each transition leaf's effective opacity, every transition animation,
the hash and every tagged `<video>` (rect, effective opacity, transition-DOM membership, content box and clipped region,
colour tuple, rVFC records, detach time) and `window.__obedTakeMs`; at the first transition rAF it keeps the textures,
every holder (pixels and geometry) and the blend/isolation chain. Alpha PNG screenshots run from `PRE_S` before the
advance to T + `POST_S`; cut arms add a per-frame screencast.

The scorer is pure (numpy in, verdicts out) and takes a `Calibration` (DX-2 injects its CEF tau, complement and no-dip).
Missing or malformed evidence is INCONCLUSIVE and never satisfies an expected FAIL; every check's controls (§9) are read
before its candidates count.

usage: uv run python scripts/dissolve_probe.py --out DIR [--arms on,off,...] [--decision Q0B.json]
       uv run python scripts/dissolve_probe.py --score DIR [--decision Q0B.json]
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import binary_counter_movie as binary  # noqa: E402
import mm_opacity_probe as mmo  # noqa: E402
from obs_cadence_decode import read_strip  # noqa: E402

from obed_edom import live_runtime  # noqa: E402

FIXTURES = Path("/Users/anyhowclick/Desktop/work/obed-edom/output/fixtures")
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
VIEWPORT = (1920, 1080)
FPS = binary.FPS
TAU = 4.0
COMPLEMENT_TOL = 2.0
NO_DIP_MIN = 252.0
MID_E = (0.05, 0.95)
MIN_MID_FRAMES = 6
MIN_CLASS_PX = 2000
FIT_DIFF_MIN = 20.0
OVERLAP_DIFF_MIN = 30.0
CURVE_SUM_TOL = 1e-5
CURVE_EASE_TOL = 1e-4
MONOTONE_SLACK = 0.01
HANDOFF_E_MIN = 0.99
CUT_SUM_TOL = 1e-3
CUT_AFTER_FRAMES = 3
DEMIX_E_MAX = 0.8
DEMIX_MIN_FRAMES = 3
DEMIX_SPREAD = 0.1
BIND_TOL_PX = 1.0
MEDIA_PAD_PX = 2
TONE_TOL = 2.0
TONE_CVC = 1.0
COST_MS = 50.0
CVC_TOL = 1.0
MATCHED_BOUND = 2.0
MIN_PRESENTED = 10
MAX_LOAD = 4.0
RAF_SLACK_MS = 17.0
RAF_GAP_MS = 50.0
BLOCK_INSET = 8
PRE_S = 0.35
POST_S = 0.6
SETTLE_S = 1.5
LIVE_GAP_S = 0.1
PAUSE_FRAME = 300
VERDICTS = ("PASS", "FAIL", "INCONCLUSIVE", "REPORTED", "N/A")
MOVIE_SUFFIXES = (".mov", ".mp4", ".m4v")


@dataclass(frozen=True)
class Calibration:
    tau: float = TAU
    complement: float = COMPLEMENT_TOL
    no_dip: float = NO_DIP_MIN


@dataclass(frozen=True)
class Deck:
    unmodified: Path
    player: Path | None = None


DECKS = {
    "p2": Deck(FIXTURES / "p2-recovery/html-adversarial/html-unmodified", FIXTURES / "p2-recovery/html-adversarial/html-player"),
    "p2bin": Deck(FIXTURES / "p2-binary/html-unmodified", FIXTURES / "p2-binary/html-player"),
    "dsk": Deck(FIXTURES / "minimal-alpha-dsk-17c0c938/html"),
    "d2": Deck(FIXTURES / "qual-decks/D2/html-unmodified"),
}

_TAGS_709 = ["-vf", "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv"]
_H264 = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "baseline", "-crf", "8", "-g", "30"]
ENCODINGS = {
    "h264-untagged": _H264,
    "h264-bt709": _H264 + _TAGS_709,
    "hevc-main10-bt709": ["-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-profile:v", "main10", "-crf", "8", "-g", "30",
                          "-tag:v", "hvc1", *_TAGS_709],
}
DEFAULT_ENCODING = "h264-bt709"

SPLICES = {
    "noblend": (b"plus-lighter", b"normal", 2),
    "delay": (b"},1e3*g)", b"},1e3*g+300)", 1),
    "hold": (b'var O=A.layers[0].layers[1],W=document.getElementById("layer"+O.layerId+("cut"===C.obedDissolve?"":"-opacity"))',
             b'var O=A.layers[0],W=document.getElementById("layer"+O.layerId)', 1),
    "fg-omit": (b"Y.forEach(", b"[].forEach(", 1),
    "fg-swap": (b"Y.forEach(", b"Y.reverse().forEach(", 1),
    "lut-identity": (b"d[j]=L[d[j]],d[j+1]=L[d[j+1]],d[j+2]=L[d[j+2]]", b"d[j]=d[j],d[j+1]=d[j+1],d[j+2]=d[j+2]", 1),
}

CUT_ANIMATION = {"additive": False, "timeOffset": 0, "beginTime": 0, "from": {"scalar": False}, "repeatCount": 0,
                 "fillMode": "both", "duration": 0.001, "autoreverses": False, "property": "hidden", "to": {"scalar": True},
                 "removedOnCompletion": False}
FOREGROUND_TEXTURES = ("74EE7166AEA70C8FD2FEDE82CCDC7157", "3652165F1CC62CFCEB8D764941CC3950")
FOREGROUND_RECTS = ((20.0, 4.0, 80.0, 20.0), (60.0, 8.0, 80.0, 20.0))
FOREGROUND_SQUARE = "3F22E494EE111203282E35DDB772C32F"
FOREGROUND_SQUARE_RECT = (120.0, 2.0, 120.0, 30.0)


@dataclass(frozen=True)
class Arm:
    deck: str
    slide: int
    mode: str = "on"
    page: str = "alpha"
    strip: bool = True
    splice: str | None = None
    overrides: tuple[str, ...] = ()
    movies: str | None = None
    continuity: str = "off"
    gpu: bool = True
    capture: str = "fade"
    classes: tuple[str, ...] = ()
    styles: str = "on"
    holders: int | None = None
    expect: dict[str, str] = field(default_factory=dict)
    row: str | None = None
    bridge: bool = False
    twin: str | None = None


_ALL = ("out", "in", "overlap")
_ON_EXPECT = {c: "PASS" for c in ("model", "complement", "no_dip", "curve", "monotone", "handoff", "no_flash")}
_MEDIA = {"deck": "p2bin", "slide": 2, "movies": "counter", "continuity": "auto"}
ARMS: dict[str, Arm] = {
    "on": Arm("p2", 2, movies="player", classes=_ALL, expect=_ON_EXPECT),
    "on-dsk": Arm("dsk", 5, classes=_ALL, expect=_ON_EXPECT),
    "on-d2": Arm("d2", 2, classes=("overlap",),
                 expect={c: "PASS" for c in ("model", "no_dip", "curve", "monotone", "handoff")} | {"complement": "N/A"}),
    "on2": Arm("p2", 2, movies="player", classes=_ALL, expect=_ON_EXPECT),
    "off": Arm("p2", 2, mode="off", movies="player", classes=("out", "in"), styles="none",
               expect={"complement": "FAIL", "model": "FAIL", "handoff": "PASS"}),
    "off-dsk": Arm("dsk", 5, mode="off", classes=("out", "in"), styles="none",
                   expect={"complement": "FAIL", "model": "FAIL", "handoff": "PASS"}),
    "noblend": Arm("p2", 2, splice="noblend", movies="player", classes=_ALL, styles="noblend",
                   expect={"no_dip": "FAIL", "complement": "PASS", "model": "FAIL"}),
    "opaque-off": Arm("p2", 2, mode="off", strip=False, movies="player", classes=("overlap",), styles="none",
                      expect={c: "PASS" for c in ("model", "no_dip", "monotone", "handoff")}),
    "opaque-on": Arm("p2", 2, strip=False, movies="player", classes=("overlap",),
                     expect={c: "PASS" for c in ("model", "no_dip", "monotone", "handoff")}),
    "screen-off": Arm("p2", 2, mode="off", page="screen", movies="player", classes=("out", "in"), styles="none",
                      expect={"screen": "FAIL"}),
    "screen-on": Arm("p2", 2, page="screen", movies="player", classes=("out", "in"), expect={"screen": "PASS"}),
    "delay-off": Arm("p2", 2, mode="off", splice="delay", movies="player", capture="delay", classes=("in",), styles="none",
                     expect={"no_flash": "FAIL"}),
    "delay-on": Arm("p2", 2, splice="delay", movies="player", capture="delay", classes=("in",), expect={"no_flash": "PASS"}),
    "cut-off": Arm("p2", 2, mode="off", overrides=("cut",), movies="player", capture="cut", classes=("out", "in"),
                   styles="none", expect={"cut": "FAIL"}),
    "cut-on": Arm("p2", 2, overrides=("cut",), movies="player", capture="cut", classes=("out", "in"), styles="cut",
                  expect={"cut": "PASS"}),
    "m-on": Arm(**_MEDIA, capture="media", classes=("out", "in"), holders=1,
                expect={c: "PASS" for c in ("frozen_frame", "frozen_region", "model", "overlay", "cost")}),
    "m-paused": Arm(**_MEDIA, capture="paused", classes=("out", "in"), holders=1, expect={"frozen_frame": "PASS"}),
    "m-off": Arm(**_MEDIA, mode="off", capture="media", classes=("out", "in"), styles="none", holders=0,
                 expect={"frozen_frame": "FAIL"}),
    "m-hold": Arm(**_MEDIA, splice="hold", capture="media", classes=("out", "in"), holders=1,
                  expect={"frozen_region": "FAIL"}),
    "m-fg": Arm(**_MEDIA, overrides=("fg",), capture="paused", classes=("out",), holders=1,
                expect={"foreground": "PASS", "model": "N/A"}),
    "m-fg-omit": Arm(**_MEDIA, overrides=("fg",), splice="fg-omit", capture="paused", classes=("out",), holders=1,
                     expect={"foreground": "FAIL", "model": "N/A"}),
    "m-fg-swap": Arm(**_MEDIA, overrides=("fg",), splice="fg-swap", capture="paused", classes=("out",), holders=1,
                     expect={"foreground": "FAIL", "model": "N/A"}),
    "m-tone": Arm(**{**_MEDIA, "movies": "tone"}, capture="paused", classes=("out",), holders=1, expect={"tone": "PASS"}),
    "m-tone-raw": Arm(**{**_MEDIA, "movies": "tone"}, splice="lut-identity", capture="paused", classes=("out",), holders=1,
                      expect={"tone": "FAIL"}),
    "m-bridge-off": Arm("p2", 4, mode="off", movies="player", continuity="auto", capture="media", classes=("out",), bridge=True,
                        styles="none", expect={"overlay": "FAIL"}),
    "m-bridge": Arm("p2", 4, movies="player", continuity="auto", capture="media", classes=("out",), bridge=True,
                    expect={"overlay": "REPORTED"}),
    "on-sw": Arm("p2", 2, movies="player", gpu=False, classes=_ALL, expect=_ON_EXPECT),
}

LIFECYCLE: dict[str, dict[str, Any]] = {
    "advance": {},
    "replay": {"replay": True},
    "queued-advance": {"actions": ((0.5, "space"),)},
    "queued-skip": {"actions": ((0.5, "skip"),)},
    "goto": {"actions": ((0.5, "goto1"),)},
    "back": {"actions": ((0.5, "back"),)},
    "hide": {"actions": ((0.5, "hide"), (1.0, "show"))},
    "hide-screen": {"actions": ((0.5, "hide"), (1.0, "show")), "page": "screen"},
    "automatic": {"overrides": ("automatic",)},
    "loop-wrap": {"overrides": ("loop",), "slide": 4},
    "end-of-show": {"slide": 4, "end": True},
}
for _row, _spec in LIFECYCLE.items():
    for _mode, _suffix in (("on", ""), ("off", "-twin")):
        ARMS[f"life-{_row}{_suffix}"] = Arm(
            "p2bin", _spec.get("slide", 2), mode=_mode, page=_spec.get("page", "alpha"), overrides=_spec.get("overrides", ()),
            movies="counter", continuity="auto", capture="lifecycle", classes=("out", "in"),
            styles="on" if _mode == "on" else "none", row=_row, twin=None if _suffix else f"life-{_row}-twin")

CONTROLS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "model": (("opaque-off",), ("off", "noblend")),
    "complement": (("noblend",), ("off",)),
    "no_dip": (("opaque-off",), ("noblend",)),
    "curve": (("on2",), ("case:curve-linear",)),
    "monotone": (("opaque-off",), ("case:monotone-dip",)),
    "no_flash": (("delay-on",), ("delay-off",)),
    "screen": (("screen-on",), ("screen-off",)),
    "handoff": (("off", "case:handoff-unchanged"), ("case:handoff-step",)),
    "cut": (("cut-on", "case:cut-complementary"), ("cut-off",)),
    "frozen_frame": (("m-paused",), ("m-off",)),
    "frozen_region": (("m-on",), ("m-hold",)),
    "foreground": (("m-fg",), ("m-fg-omit", "m-fg-swap", "case:fg-shifted", "case:fg-double", "case:fg-swapped")),
    "tone": (("m-tone",), ("m-tone-raw",)),
    "overlay": (("m-on",), ("m-bridge-off",)),
    "cost": (("case:cost-50",), ("case:cost-50-eps",)),
}

HOOK_JS = r"""
(function () {
  if (window.__obedDx) return;
  var X = {armed: false, tex: null, raf: [], first: null, vids: [], pause: null}, recs = new WeakMap(), els = [];
  function box(r) { return [r.left, r.top, r.width, r.height]; }
  function stage() { return document.getElementById('stage'); }
  function holder(d) {
    var c = d.firstElementChild;
    return d.tagName === 'DIV' && !d.id && d.style.overflow === 'hidden' && d.children.length === 1 && c.tagName === 'CANVAS' && !c.id;
  }
  function eff(el, stop) {
    var q = el.checkVisibility && !el.checkVisibility({visibilityProperty: true}) ? 0 : 1;
    for (var n = el; q && n && n.nodeType === 1 && n !== stop; n = n.parentElement) q *= +getComputedStyle(n).opacity;
    return q;
  }
  function geo(v) {
    var r = v.getBoundingClientRect(), z = getComputedStyle(v), vw = v.videoWidth, vh = v.videoHeight, h = document.documentElement;
    if (!vw || !vh) return null;
    var f = z.objectFit === 'fill' ? 0 : Math.min(r.width / vw, r.height / vh), cw = f ? vw * f : r.width, ch = f ? vh * f : r.height;
    var cx = r.left + (r.width - cw) / 2, cy = r.top + (r.height - ch) / 2, c = [cx, cy, cx + cw, cy + ch];
    for (var a = v.parentElement; a; a = a.parentElement) {
      var w = getComputedStyle(a), vp = a === h || (a === document.body && getComputedStyle(h).overflowX === 'visible');
      if (w.overflowX === 'visible' || (!vp && w.position === 'static')) continue;
      var b = vp ? {left: 0, top: 0, right: innerWidth, bottom: innerHeight} : a.getBoundingClientRect();
      c = [Math.max(c[0], b.left), Math.max(c[1], b.top), Math.min(c[2], b.right), Math.min(c[3], b.bottom)];
    }
    return {content: [cx, cy, cw, ch], region: [c[0], c[1], c[2] - c[0], c[3] - c[1]], size: [vw, vh]};
  }
  function track(v) {
    if (recs.has(v)) return;
    var r = {id: X.vids.length, src: String(v.currentSrc || v.src || '').split('/').pop(), rv: [], detach: null, tuple: null, err: null};
    recs.set(v, r); X.vids.push(r); els.push(v);
    function cb(t, md) {
      r.rv.push([performance.now(), md.mediaTime, md.presentedFrames]);
      if (r.rv.length > 900) r.rv.splice(0, r.rv.length - 900);
      if (!r.tuple && !r.err) {
        try { var f = new VideoFrame(v), c = f.colorSpace; r.tuple = [c.primaries, c.transfer, c.matrix, c.fullRange].join('/'); f.close(); }
        catch (e) { r.err = String(e); }
      }
      if (r.detach === null) v.requestVideoFrameCallback(cb);
    }
    if (v.requestVideoFrameCallback) v.requestVideoFrameCallback(cb);
  }
  function scan() {
    var vs = document.getElementsByTagName('video');
    for (var i = 0; i < vs.length; i++) track(vs[i]);
    for (var j = 0; j < els.length; j++) { var r = recs.get(els[j]); if (r.detach === null && !els[j].isConnected) r.detach = performance.now(); }
  }
  new MutationObserver(scan).observe(document, {childList: true, subtree: true});
  function leaves() {
    var G = stage();
    if (!G || !X.tex) return null;
    var L = X.tex.map(function (id) { var m = G.querySelectorAll('canvas[id="' + id + '"]'); return m.length === 1 ? m[0] : null; });
    return L[0] && L[1] ? L : null;
  }
  function rootOf(L) { var a = L[0]; while (a && !a.contains(L[1])) a = a.parentElement; return a && a.parentElement; }
  function layerIds(T) {
    return [T].concat(Array.prototype.slice.call(T.querySelectorAll('[id^="layer"]')))
      .map(function (e) { return e.id; }).filter(function (s) { return /^layer\d+/.test(s); });
  }
  function anims(L) {
    return (document.getAnimations ? document.getAnimations() : []).filter(function (a) {
      var t = a.effect && a.effect.target; return !!t && t.contains(L[0]) !== t.contains(L[1]);
    }).map(function (a) {
      var t = a.effect.target, g = a.effect.getTiming();
      return {leaf: t.contains(L[0]) ? 'in' : 'out', target: t.id, name: a.animationName || null, ct: a.currentTime,
              start: a.startTime, state: a.playState, dur: typeof g.duration === 'number' ? g.duration : null,
              value: +getComputedStyle(t).opacity};
    });
  }
  function chain(c) {
    var out = [], G = stage();
    for (var n = c; n && n !== G; n = n.parentElement) {
      var s = getComputedStyle(n);
      out.push({id: n.id, opacity: s.opacity, blend: s.mixBlendMode, isolation: s.isolation, tstyle: s.transformStyle});
    }
    return out;
  }
  function png(c) { try { return c.toDataURL('image/png'); } catch (e) { return null; } }
  function first(L, T, t) {
    var hs = Array.prototype.filter.call(T.querySelectorAll('div'), holder);
    return {t: t, textures: L.map(function (c) { return c.id; }), size: L.map(function (c) { return [c.width, c.height]; }),
      png: L.map(png), chain: L.map(chain), layerIds: layerIds(T),
      holders: hs.map(function (h) {
        var c = h.firstElementChild;
        return {parent: h.parentElement.id, style: [h.style.left, h.style.top, h.style.width, h.style.height],
                rect: box(h.getBoundingClientRect()), canvasRect: box(c.getBoundingClientRect()), natural: [c.width, c.height], png: png(c)};
      })};
  }
  function tick() {
    if (!X.armed) return;
    var t = performance.now(), G = stage(), L = leaves(), T = L && rootOf(L), snap = null;
    try { snap = window.__obedLive.snapshot(); } catch (e) {}
    var rec = {t: t, hash: location.hash, scene: snap && snap.sceneId, take: window.__obedTakeMs === undefined ? null : window.__obedTakeMs};
    if (L) {
      rec.eff = L.map(function (c) { return eff(c, G); });
      rec.anims = anims(L);
      if (!X.first) X.first = first(L, T, t);
    }
    rec.videos = els.map(function (v) {
      var r = recs.get(v), o = {id: r.id, on: v.isConnected};
      if (o.on) {
        o.rect = box(v.getBoundingClientRect()); o.eff = eff(v, null); o.inT = !!(T && T.contains(v));
        o.inStage = !!(G && G.contains(v)); o.geo = geo(v); o.paused = v.paused;
      }
      return o;
    });
    X.raf.push(rec);
    requestAnimationFrame(tick);
  }
  window.__obedDx = {
    arm: function (tex) { scan(); X.tex = tex; X.armed = true; X.raf = []; X.first = null; requestAnimationFrame(tick);
                          return {timeOrigin: performance.timeOrigin, now: performance.now()}; },
    disarm: function () { X.armed = false; return X.raf.length; },
    dump: function () {
      var f = X.first && Object.assign({}, X.first, {png: null, holders: X.first.holders.map(function (h) { return Object.assign({}, h, {png: null}); })});
      return {raf: X.raf, first: f, vids: X.vids, timeOrigin: performance.timeOrigin, takeMs: window.__obedTakeMs === undefined ? null : window.__obedTakeMs};
    },
    images: function () { return X.first && {tex: X.first.png, holders: X.first.holders.map(function (h) { return h.png; })}; },
    residue: function (ids) {
      var nums = {}, layers = 0, rules = 0, G = stage();
      ids.forEach(function (s) { var m = /^layer(\d+)/.exec(s); if (m) nums[m[1]] = 1; });
      Array.prototype.forEach.call(document.querySelectorAll('[id^="layer"]'), function (e) { var m = /^layer(\d+)/.exec(e.id); if (m && nums[m[1]]) layers++; });
      Array.prototype.forEach.call(document.styleSheets, function (s) {
        var rs; try { rs = s.cssRules; } catch (e) { return; }
        Array.prototype.forEach.call(rs, function (r) {
          var m = r.selectorText && r.selectorText.match(/#layer(\d+)/g);
          if (m && m.some(function (x) { return nums[x.slice(6)]; }) && /mix-blend-mode|isolation/.test(r.cssText)) rules++;
        });
      });
      return {layers: layers, rules: rules, holders: G ? Array.prototype.filter.call(G.querySelectorAll('div'), holder).length : 0};
    },
    foreground: function () {
      var G = stage(), out = {};
      if (!G) return out;
      els.forEach(function (v) {
        var g = v.isConnected && G.contains(v) && geo(v);
        if (!g) return;
        var R = g.region;
        out[recs.get(v).id] = Array.prototype.filter.call(G.querySelectorAll('canvas'), function (c) {
          var o = c.getBoundingClientRect();
          return (v.compareDocumentPosition(c) & 4) && c.checkVisibility({opacityProperty: true, visibilityProperty: true}) &&
            o.right > R[0] && o.left < R[0] + R[2] && o.bottom > R[1] && o.top < R[1] + R[3];
        }).map(function (c) { return {id: c.id, rect: box(c.getBoundingClientRect())}; });
      });
      return out;
    },
    pause: function (frame, fps) {
      var G = stage(), best = null, area = 0;
      els.forEach(function (v) {
        if (!v.isConnected || !G || !G.contains(v) || v.readyState < 2) return;
        var r = v.getBoundingClientRect();
        if (r.width * r.height > area) { area = r.width * r.height; best = v; }
      });
      if (!best) return null;
      var r = recs.get(best);
      X.pause = {id: r.id, frame: frame, state: 'seeking'};
      best.pause();
      best.addEventListener('seeked', function () {
        X.pause.state = 'seeked';
        best.requestVideoFrameCallback(function () { X.pause.state = 'presented'; });
      }, {once: true});
      best.currentTime = (frame + 0.5) / fps;
      return r.id;
    },
    paused: function () { return X.pause; }
  };
})();
"""
SNAPSHOT_JS = ("(function(){var s=null;try{s=window.__obedLive.snapshot()}catch(e){}return s?{scene:s.sceneId,"
               "next:s.nextSceneId,state:s.playerState,ready:s.ready}:null})()")
STAGE_JS = mmo.STAGE_JS


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def counted_splice(player: bytes, before: bytes, after: bytes, count: int) -> bytes:
    found = player.count(before)
    if found != count:
        raise ValueError(f"splice anchor {before[:40]!r} found {found} times, expected {count}")
    return player.replace(before, after)


def served_player(stock: bytes, mode: str, splice: str | None = None) -> bytes:
    patched = live_runtime.patch_player(stock, mm_opacity=mode == "on")
    return counted_splice(patched, *SPLICES[splice]) if splice else patched


@contextlib.contextmanager
def serving(splice: str | None) -> Iterator[None]:
    """`LiveOutputHost` serves `patch_player` output plus the arm's counted splice (if any) while this is active."""
    from obed_edom import live_host

    if splice is None:
        yield
        return
    real = live_host.patch_player

    def spliced(player: bytes, *, mm_opacity: bool = True) -> bytes:
        return counted_splice(real(player, mm_opacity=mm_opacity), *SPLICES[splice])

    live_host.patch_player = spliced
    try:
        yield
    finally:
        live_host.patch_player = real


def hooked_transport(base: type | None = None) -> type:
    """A `ChromeCdp` (or `base`) subclass that installs `HOOK_JS` as the innermost new-document script."""
    if base is None:
        from obed_edom.live_host import ChromeCdp as base

    class HookedCdp(base):
        def start(self) -> None:
            super().start()
            self.call("Page.addScriptToEvaluateOnNewDocument", source=HOOK_JS)

    return HookedCdp


def ycbcr709(rgb: Iterable[float]) -> tuple[int, int, int]:
    r, g, b = (v / 255.0 for v in rgb)
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return round(16 + 219 * y), round(128 + 224 * (b - y) / 1.8556), round(128 + 224 * (r - y) / 1.5748)


def tone_layout() -> dict[str, Any]:
    ramp = [(80 + (i % 110) * 16, 64 + (i // 110) * 72, 16, 64, 16 + i) for i in range(220)]
    colours = [[round(f * c) for c in base] for base in ((255, 0, 0), (0, 255, 0), (0, 0, 255), (0, 255, 255),
                                                         (255, 0, 255), (255, 255, 0)) for f in (0.25, 0.5, 0.75, 1.0)]
    colours += [[255, 224, 189], [234, 192, 134], [198, 134, 66], [141, 85, 36]]
    patches = [(64 + (i % 14) * 128, 216 + (i // 14) * 128, 96, 96, rgb) for i, rgb in enumerate(colours)]
    return {"sourceSize": [binary.WIDTH, binary.HEIGHT], "fps": FPS, "stripRect": list(binary.STRIP_RECT),
            "blockRects": [list(r) for r in binary.BLOCK_RECTS], "ramp": [list(r) for r in ramp],
            "patches": [[x, y, w, h, list(rgb)] for x, y, w, h, rgb in patches]}


def tone_planes(layout: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    w, h = layout["sourceSize"]
    y = np.full((h, w), binary.Y_BACKGROUND, np.uint8)
    u = np.full((h // 2, w // 2), 128, np.uint8)
    v = np.full((h // 2, w // 2), 128, np.uint8)
    for x0, y0, rw, rh, luma in layout["ramp"]:
        y[y0:y0 + rh, x0:x0 + rw] = luma
    for x0, y0, rw, rh, rgb in layout["patches"]:
        ly, cb, cr = ycbcr709(rgb)
        y[y0:y0 + rh, x0:x0 + rw] = ly
        u[y0 // 2:(y0 + rh) // 2, x0 // 2:(x0 + rw) // 2] = cb
        v[y0 // 2:(y0 + rh) // 2, x0 // 2:(x0 + rw) // 2] = cr
    return y, u, v


def counter_frames(n: int) -> Iterator[bytes]:
    from PIL import ImageFont

    font = ImageFont.load_default(size=binary.DIGITS_SIZE)
    for index in range(n):
        yield binary.yuv420p(binary.luma_frame(index, font))


def tone_frames(n: int, layout: dict[str, Any] | None = None) -> Iterator[bytes]:
    y, u, v = tone_planes(layout or tone_layout())
    chroma = u.tobytes() + v.tobytes()
    for index in range(n):
        frame = y.copy()
        for bit, (bx, by, bw, bh) in zip(binary.strip_bits(index), binary.BLOCK_RECTS):
            frame[by:by + bh, bx:bx + bw] = binary.Y_WHITE if bit else binary.Y_BLACK
        yield frame.tobytes() + chroma


def encode_movie(dest: Path, frames: Iterable[bytes], *, encoding: str, size: tuple[int, int] = (binary.WIDTH, binary.HEIGHT),
                 fps: int = FPS) -> dict[str, Any]:
    """Raw yuv420p frames through `ENCODINGS[encoding]` into `dest` (Keynote's .mov name, MP4 bytes)."""
    import imageio_ffmpeg

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp.mp4")
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "yuv420p",
           "-s", f"{size[0]}x{size[1]}", "-r", str(fps), "-i", "-", *ENCODINGS[encoding], "-an", "-movflags", "+faststart", str(tmp)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    count = 0
    try:
        for frame in frames:
            proc.stdin.write(frame)
            count += 1
    finally:
        proc.stdin.close()
    stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
    if proc.wait() != 0 or not tmp.is_file():
        raise RuntimeError(f"ffmpeg encode failed: {stderr[-800:]}")
    tmp.replace(dest)
    return {"path": str(dest), "sha256": binary.sha256_file(dest), "encoding": encoding, "frames": count, "fps": fps}


def scratch_movie(scratch: Path, kind: str, encoding: str, seconds: float) -> dict[str, Any]:
    dest = scratch / "movies" / f"{kind}-{encoding}-{seconds}.mov"
    meta = dest.with_suffix(".json")
    if dest.is_file() and meta.is_file():
        return json.loads(meta.read_text())
    n = binary.frame_count(seconds)
    info = encode_movie(dest, counter_frames(n) if kind == "counter" else tone_frames(n), encoding=encoding)
    info.update(kind=kind, seconds=seconds, layout=binary.layout() if kind == "counter" else tone_layout())
    meta.write_text(json.dumps(info))
    return info


def scratch_strip(scratch: Path, deck: str) -> tuple[Path, dict[str, Any]]:
    from obed_edom.html_alpha_probe import strip_export_pdf_bg_fills

    root = scratch / f"strip-{deck}"
    report = root / "strip.json"
    if report.is_file():
        return root, json.loads(report.read_text())
    source = DECKS[deck].unmodified
    for path in sorted(p for p in source.rglob("*") if p.suffix.lower() in (".pdf", ".pdfp") and p.is_file()):
        dest = root / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    raw = strip_export_pdf_bg_fills(root)
    summary = {"pdfCount": raw["pdfCount"], "rewritten": [{"pdf": r["pdf"], "pages": r["strippedPages"], "sha256": r["sha256"]}
                                                          for r in raw["rewritten"]]}
    if not summary["rewritten"]:
        raise RuntimeError(f"strip of {deck} removed no background fill")
    report.write_text(json.dumps(summary))
    return root, summary


def read_doc(path: Path) -> Any:
    return json.loads(path.read_text())


def jsonp_text(original: str, doc: Any) -> str:
    match = re.match(r"\s*(\w+)\(\s*(\{.*\})\s*\)\s*;?\s*$", original, re.S)
    if not match:
        raise ValueError("unexpected jsonp wrapper")
    inner = json.loads(match.group(2))
    if isinstance(inner, dict) and "json" in inner and "name" in inner:
        inner["json"] = doc
    else:
        inner = doc
    return f"{match.group(1)}( {json.dumps(inner)} )"


def slide_doc_path(uuid: str) -> str:
    return f"assets/{uuid}/{uuid}.json"


def transition_event(doc: dict[str, Any]) -> int:
    hits = [i for i, e in enumerate(doc.get("events") or []) if (e.get("effects") or [{}])[0].get("type") == "transition"
            and (e.get("effects") or [{}])[0].get("name") in ("apple:dissolve", "none")]
    if len(hits) != 1:
        raise ValueError(f"expected exactly one dissolve/cut transition event, found {hits}")
    return hits[0]


def find_target(read: Callable[[str], Any], slide: int) -> dict[str, Any]:
    """The outgoing slide's (1-based) dissolve/cut: global scene, texture ids (incoming, outgoing), kind, timing, hashes."""
    header = read("assets/header.json")
    docs = [read(slide_doc_path(uuid)) for uuid in header["slideList"]]
    flat = [e for d in docs for e in d["events"]]
    event = transition_event(docs[slide - 1])
    scene = sum(len(d["events"]) for d in docs[:slide - 1]) + event
    effect = flat[scene]["effects"][0]
    leaves = effect["baseLayer"]["layers"][0]["layers"]
    nxt, loop = scene + 1, bool(header.get("loopSlideshow"))
    for _ in range(len(flat) + 1):
        if nxt >= len(flat):
            if not loop:
                nxt = None
                break
            nxt = 0
        if not flat[nxt].get("automaticPlay"):
            break
        nxt += 1
    return {"slide": slide, "uuid": header["slideList"][slide - 1], "event": event, "scene": scene,
            "kind": "cut" if effect["name"] == "none" else "dissolve", "textures": [leaves[0]["texture"], leaves[1]["texture"]],
            "durationS": float(effect["duration"]), "beginS": float(effect.get("beginTime") or 0),
            "automatic": bool(flat[scene].get("automaticPlay")), "previousS": float((flat[scene - 1]["effects"] or [{}])[0].get("duration") or 0) if scene else 0.0,
            "hashBefore": f"#{scene - 1 if flat[scene].get('automaticPlay') else scene}", "hashAfter": None if nxt is None else f"#{nxt}", "sceneCount": len(flat)}


def _cut(doc: dict[str, Any], event: int) -> None:
    effect = doc["events"][event]["effects"][0]
    effect["name"], effect["duration"] = "none", 0.001
    effect["baseLayer"]["layers"][0]["layers"][1]["animations"] = [dict(CUT_ANIMATION)]


def _automatic(doc: dict[str, Any], event: int) -> None:
    doc["events"][event]["automaticPlay"] = True
    doc["events"][event]["effects"][0]["beginTime"] = 0.5


def _texture_layer(texture: str, rect: tuple[float, float, float, float], template: dict[str, Any]) -> dict[str, Any]:
    x, y, w, h = rect
    state = json.loads(json.dumps(template["initialState"]))
    state.update(position={"pointX": x + w / 2, "pointY": y + h / 2}, width=w, height=h, hidden=False, opacity=1,
                 anchorPoint={"pointX": 0.5, "pointY": 0.5})
    return {"animations": [], "layers": [], "initialState": state, "texture": texture}


def _effects(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        if node.get("name") == "renderMovie" and isinstance(node.get("baseLayer"), dict):
            yield node
        for value in node.values():
            yield from _effects(value)
    elif isinstance(node, list):
        for value in node:
            yield from _effects(value)


def _layers(layer: dict[str, Any]) -> Iterator[tuple[dict[str, Any], dict[str, Any] | None]]:
    stack: list[tuple[dict[str, Any], dict[str, Any] | None]] = [(layer, None)]
    while stack:
        node, parent = stack.pop()
        yield node, parent
        stack.extend((child, node) for child in node.get("layers") or [])


def _foreground(doc: dict[str, Any], event: int) -> None:
    builds = list(_effects(doc["events"]))
    if len(builds) != 1:
        raise ValueError(f"expected one renderMovie build on the slide, found {len(builds)}")
    video = [(n, p) for n, p in _layers(builds[0]["baseLayer"]) if n.get("isVideoLayer")]
    if len(video) != 1 or video[0][1] is None:
        raise ValueError("expected one video layer inside the renderMovie build")
    node, parent = video[0]
    square = [(n, p) for n, p in _layers(doc["events"][0]["baseLayer"])
              if any(c.get("texture") == FOREGROUND_SQUARE for c in n.get("layers") or [])]
    if len(square) != 1 or square[0][1] is None:
        raise ValueError("expected one translucent square branch in the scene")
    branch, owner = square[0]
    owner["layers"].remove(branch)
    for event_doc in doc["events"][1:]:
        for n, p in _layers(event_doc["baseLayer"]):
            if p is not None and any(c.get("texture") == FOREGROUND_SQUARE for c in n.get("layers") or []):
                p["layers"].remove(n)
    x, y, w, h = FOREGROUND_SQUARE_RECT
    branch["initialState"].update(position={"pointX": x + w / 2, "pointY": y + h / 2}, width=w, height=h)
    for child in branch["layers"]:
        child["initialState"].update(position={"pointX": w / 2, "pointY": h / 2}, width=w, height=h)
    parent["layers"].extend([_texture_layer(t, r, node) for t, r in zip(FOREGROUND_TEXTURES, FOREGROUND_RECTS)] + [branch])


SLIDE_OVERRIDES: dict[str, Callable[[dict[str, Any], int], None]] = {"cut": _cut, "automatic": _automatic, "fg": _foreground}
HEADER_OVERRIDES: dict[str, Callable[[dict[str, Any]], None]] = {"loop": lambda header: header.update(loopSlideshow=1)}


@dataclass
class Resolved:
    root: Path
    resolver: Callable[[Path, str], Path]
    slides: list[dict[str, Any]]
    target: dict[str, Any]
    served: dict[str, Any]
    provenance: dict[str, Any]
    movies: dict[str, dict[str, Any]]

    def fields(self) -> dict[str, Any]:
        """The run-record keys the scorer reads from the resolver."""
        return {"target": self.target, "served": self.served, "provenance": self.provenance,
                "movies": {k: {kk: vv for kk, vv in v.items() if kk != "path"} for k, v in self.movies.items()}}


def resolve(arm: Arm, scratch: Path, decision: dict[str, Any] | None = None, *, tag: str = "arm") -> Resolved:
    """Read-only resolver for one arm: unmodified page, player and JSON; scratch-stripped PDFs; decodable movies; edits."""
    decision = decision or {}
    deck = DECKS[arm.deck]
    unmod = deck.unmodified
    strip_root, strip_report = scratch_strip(scratch, arm.deck) if arm.strip else (None, None)
    files: dict[str, Path] = {}
    movies: dict[str, dict[str, Any]] = {}

    def base(rel: str) -> Path:
        if rel in files:
            return files[rel]
        if rel.lower().endswith(MOVIE_SUFFIXES) and arm.movies:
            if arm.movies == "player" or (arm.movies == "counter" and decision.get("counterEncoding") == "h264-untagged"):
                if deck.player is None:
                    raise FileNotFoundError(rel)
                return deck.player / rel
            seconds = binary.movie_seconds(Path(rel))
            info = scratch_movie(scratch, arm.movies, decision.get(f"{arm.movies}Encoding", DEFAULT_ENCODING), seconds)
            movies[rel] = info
            return Path(info["path"])
        if strip_root is not None and rel.lower().endswith((".pdf", ".pdfp")) and (strip_root / rel).is_file():
            return strip_root / rel
        return unmod / rel

    def resolver(_root: Path, relative: str) -> Path:
        rel = (relative or "").strip()
        if not rel or rel.startswith("/") or "\\" in rel or any(p in ("", ".", "..") for p in Path(rel).parts):
            raise FileNotFoundError(relative)
        path = base(rel)
        if not path.is_file():
            raise FileNotFoundError(relative)
        return path

    header = read_doc(unmod / "assets/header.json")
    overrides: dict[str, str] = {}
    out_dir = scratch / "overrides" / tag
    if arm.overrides:
        uuid = header["slideList"][arm.slide - 1]
        rel = slide_doc_path(uuid)
        doc = read_doc(unmod / rel)
        written: dict[str, Any] = {}
        for name in arm.overrides:
            if name in SLIDE_OVERRIDES:
                SLIDE_OVERRIDES[name](doc, transition_event(doc))
                written[rel] = doc
            else:
                HEADER_OVERRIDES[name](header)
                written["assets/header.json"] = header
        for path, data in written.items():
            for suffix, text in ((".json", json.dumps(data)), (".jsonp", jsonp_text((unmod / path).with_suffix(".jsonp").read_text(), data))):
                dest = out_dir / Path(path).with_suffix(suffix)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text)
                key = str(Path(path).with_suffix(suffix))
                files[key] = dest
                overrides[key] = binary.sha256_file(dest)
    target = find_target(lambda rel: read_doc(resolver(unmod, rel)), arm.slide)
    stock = (unmod / "assets/player/main.js").read_bytes()
    served = {"mode": arm.mode, "splice": arm.splice, "stockSha256": sha256_bytes(stock),
              "expected": sha256_bytes(served_player(stock, arm.mode, arm.splice))}
    slides = [{"originalOrdinal": i + 1, "playerIndex": i, "exportedUuid": u, "skipped": False}
              for i, u in enumerate(read_doc(resolver(unmod, "assets/header.json"))["slideList"])]
    provenance = {"deck": arm.deck, "unmodified": str(unmod), "player": str(deck.player) if deck.player else None,
                  "strip": strip_report, "overrides": overrides, "movies": arm.movies, "decision": decision}
    return Resolved(unmod, resolver, slides, target, served, provenance, movies)


def ease_in_out(p: float, x1: float = 0.42, y1: float = 0.0, x2: float = 0.58, y2: float = 1.0) -> float:
    p = min(1.0, max(0.0, p))
    lo, hi = 0.0, 1.0
    for _ in range(60):
        t = (lo + hi) / 2
        x = 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t ** 2 * x2 + t ** 3
        lo, hi = (t, hi) if x < p else (lo, t)
    t = (lo + hi) / 2
    return 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t ** 2 * y2 + t ** 3


def analytic_lut() -> np.ndarray:
    v = (np.arange(256) / 255.0) ** 1.961
    s = np.where(v <= 0.0031308, 12.92 * v, 1.055 * np.power(v, 1 / 2.4) - 0.055)
    return np.clip(np.rint(255 * s), 0, 255).astype(np.uint8)


def build_lut(snapshot: np.ndarray, live: np.ndarray, *, agree: float = 1.0, analytic_tol: float = 1.0) -> dict[str, Any]:
    """Q0b 1's measured LUT from paired (N, 3) snapshot/live pixels of eroded ramp and patch interiors: per channel and
    observed snapshot value s the median live value; one shared table if the channels agree within `agree` at every s
    (else `kind` "fallback", the 3-D case); unobserved s interpolated linearly; L[0] = 0, L[255] = 255; "analytic" when
    the gamma-1.961 curve is within `analytic_tol` at every observed s, else "table"."""
    snap, liv = np.asarray(snapshot).reshape(-1, 3).astype(int), np.asarray(live, dtype=float).reshape(-1, 3)
    medians: dict[int, list[float]] = {}
    for s in np.unique(snap):
        per = [float(np.median(liv[snap[:, c] == s, c])) for c in range(3) if np.any(snap[:, c] == s)]
        medians[int(s)] = per
    disagree = sorted(s for s, per in medians.items() if max(per) - min(per) > agree)
    observed = sorted(s for s in medians if 0 < s < 255)
    if disagree:
        return {"kind": "fallback", "table": None, "observed": observed, "disagree": disagree}
    xs = [0, *observed, 255]
    ys = [0.0, *(float(np.median(medians[s])) for s in observed), 255.0]
    table = np.clip(np.rint(np.interp(np.arange(256), xs, ys)), 0, 255).astype(np.uint8)
    curve = analytic_lut()
    analytic = bool(observed) and all(abs(float(np.median(medians[s])) - float(curve[s])) <= analytic_tol for s in observed)
    return {"kind": "analytic" if analytic else "table", "table": table.tolist(), "observed": observed, "disagree": []}


def premul(img: np.ndarray) -> np.ndarray:
    out = np.asarray(img, dtype=np.float32).copy()
    out[..., :3] *= out[..., 3:4] / 255.0
    return out


def rect_mask(shape: tuple[int, int], rects: Iterable[Iterable[float]], pad: float = 0.0) -> np.ndarray:
    mask = np.zeros(shape, bool)
    for x, y, w, h in rects:
        x0, y0 = max(0, math.floor(x - pad)), max(0, math.floor(y - pad))
        x1, y1 = min(shape[1], math.ceil(x + w + pad)), min(shape[0], math.ceil(y + h + pad))
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = True
    return mask


def source_mask(shape: tuple[int, int], rects: Iterable[Iterable[float]], origin: tuple[float, float], scale: float,
                erode: float = 0.0) -> np.ndarray:
    """Source-px rects ([x, y, w, h, ...]) mapped to screen at `origin`/`scale`, each eroded by `erode` screen px."""
    mask = np.zeros(shape, bool)
    for rect in rects:
        x, y, w, h = rect[:4]
        x0, y0 = math.ceil(origin[0] + x * scale + erode), math.ceil(origin[1] + y * scale + erode)
        x1, y1 = math.floor(origin[0] + (x + w) * scale - erode), math.floor(origin[1] + (y + h) * scale - erode)
        if x1 > x0 and y1 > y0:
            mask[max(0, y0):min(shape[0], y1), max(0, x0):min(shape[1], x1)] = True
    return mask


def block_mask(shape: tuple[int, int], origin: tuple[float, float], scale: float) -> np.ndarray:
    inner = [(x + BLOCK_INSET, y + BLOCK_INSET, w - 2 * BLOCK_INSET, h - 2 * BLOCK_INSET) for x, y, w, h in binary.BLOCK_RECTS]
    return source_mask(shape, inner, origin, scale)


def texture_classes(A: np.ndarray, B: np.ndarray) -> dict[str, np.ndarray]:
    aA, aB = A[..., 3], B[..., 3]
    far = np.abs(premul(A) - premul(B))[..., :3].sum(axis=2) > OVERLAP_DIFF_MIN
    return {"out": (aA == 255) & (aB == 0), "in": (aA == 0) & (aB == 255), "overlap": (aA == 255) & (aB == 255) & far}


def place(image: np.ndarray, canvas_rect: Iterable[float], clip_rect: Iterable[float], shape: tuple[int, int]) -> np.ndarray:
    """A natural-size RGBA canvas drawn at its screen rect, clipped to its holder's rect, on a transparent screen."""
    out = np.zeros((*shape, 4), np.uint8)
    cx, cy, cw, ch = canvas_rect
    x0, y0 = round(cx), round(cy)
    w, h = max(1, round(cw)), max(1, round(ch))
    scaled = np.asarray(Image.fromarray(np.ascontiguousarray(image)).resize((w, h), Image.BILINEAR))
    clip = rect_mask(shape, [clip_rect])
    ys, xs = slice(max(0, y0), min(shape[0], y0 + h)), slice(max(0, x0), min(shape[1], x0 + w))
    if ys.stop > ys.start and xs.stop > xs.start:
        out[ys, xs] = scaled[ys.start - y0:ys.stop - y0, xs.start - x0:xs.stop - x0]
    out[~clip] = 0
    return out


def over(top: np.ndarray, bottom: np.ndarray) -> np.ndarray:
    t, b = premul(top), premul(bottom)
    out = t + b * (1 - t[..., 3:4] / 255.0)
    a = out[..., 3:4]
    rgb = np.where(a > 0, out[..., :3] * 255.0 / np.maximum(a, 1e-6), 0)
    return np.clip(np.rint(np.concatenate([rgb, a], axis=2)), 0, 255).astype(np.uint8)


def fit_frame(F: np.ndarray, A: np.ndarray, B: np.ndarray, keep: np.ndarray, *, screen: bool = False) -> tuple[float, float]:
    """(e, max residual) of `F` against (1 - e)·A + e·B, premultiplied, on `keep`; screen pages compare RGB over black."""
    Ap, Bp = premul(A), premul(B)
    Fp = F[..., :3].astype(np.float32) if screen else premul(F)
    if screen:
        Ap, Bp = Ap[..., :3], Bp[..., :3]
    d = (Bp - Ap)[keep]
    fit = np.abs(d).sum(axis=1) > FIT_DIFF_MIN
    den = float((d[fit] ** 2).sum())
    if not den:
        return math.nan, math.nan
    e = float(((Fp - Ap)[keep][fit] * d[fit]).sum() / den)
    residual = np.abs(Fp - ((1 - e) * Ap + e * Bp))[keep]
    return e, float(residual.max()) if residual.size else math.nan


def result(ok: bool | None, problems: Iterable[str] = (), *, report: bool = False, **detail: Any) -> dict[str, Any]:
    problems = list(problems)
    if problems:
        verdict = "INCONCLUSIVE"
    elif report:
        verdict = "REPORTED"
    elif ok is None:
        verdict = "N/A"
    else:
        verdict = "PASS" if ok else "FAIL"
    return {"verdict": verdict, "problems": problems, "detail": detail}


def shot_phases(shots: list[dict[str, Any]], raf: list[dict[str, Any]]) -> list[str]:
    """Per screenshot "pre", "transition", "live" or "ambiguous" from the rAF records spanning its capture window."""
    times = [(float(r["t"]), bool(r.get("eff"))) for r in raf]
    insert = next((t for t, present in times if present), None)
    out = []
    for shot in shots:
        lo, hi = shot["t0"] - RAF_SLACK_MS, shot["t1"]
        before = [p for t, p in times if t <= lo]
        states = {p for t, p in times if lo < t <= hi} | ({before[-1]} if before else set())
        if states == {True}:
            out.append("transition")
        elif states == {False}:
            out.append("pre" if insert is None or hi < insert else "live")
        else:
            out.append("ambiguous")
    return out


def score_fade(frames: list[np.ndarray], A: np.ndarray, B: np.ndarray, *, exclude: list[Iterable[float]] = (),
               classes: Iterable[str] = (), cal: Calibration = Calibration(), screen: bool = False,
               min_frames: int = MIN_MID_FRAMES) -> dict[str, Any]:
    """Model, complement and no-dip over transition frames (time order); `exclude` = media rects (padded here)."""
    shape = A.shape[:2]
    problems = []
    if A.shape != B.shape or any(f.shape[:2] != shape for f in frames):
        return {"problems": ["texture and screenshot sizes differ"], "rows": [], "checks": {}}
    masks = texture_classes(A, B)
    keep = ~rect_mask(shape, exclude, MEDIA_PAD_PX)
    sizes = {k: int((masks[k] & keep).sum()) for k in masks}
    problems += [f"class {k}: {sizes[k]} px < {MIN_CLASS_PX}" for k in classes if sizes[k] < MIN_CLASS_PX]
    rows = []
    for F in frames:
        e, res = fit_frame(F, A, B, keep, screen=screen)
        row = {"e": e, "residual": res}
        if not screen:
            for k in ("out", "in", "overlap"):
                m = masks[k] & keep
                row[k] = float(np.median(F[..., 3][m])) if m.any() else None
        rows.append(row)
    if any(not math.isfinite(r["e"]) for r in rows):
        problems.append("a transition frame has no fit")
    mid = [r for r in rows if math.isfinite(r["e"]) and MID_E[0] < r["e"] < MID_E[1]]
    if len(mid) < min_frames:
        problems.append(f"{len(mid)} mid frames < {min_frames}")
    checks = {"model": bool(mid) and all(r["residual"] <= cal.tau for r in mid)}
    if not screen and {"in", "out"} <= set(classes):
        checks["complement"] = bool(mid) and all(abs(r["in"] + r["out"] - 255) <= cal.complement for r in mid)
    if not screen and "overlap" in classes:
        checks["no_dip"] = bool(mid) and all(r["overlap"] >= cal.no_dip for r in mid)
    return {"problems": problems, "rows": rows, "mid": len(mid), "classPx": sizes, "checks": checks}


def leaf_anims(rec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {a["leaf"]: a for a in rec.get("anims") or [] if a.get("ct") is not None and a.get("state") in ("running", "finished")}


def score_curve(raf: list[dict[str, Any]], min_frames: int = MIN_MID_FRAMES) -> dict[str, Any]:
    both = [leaf_anims(r) for r in raf if len(leaf_anims(r)) == 2]
    if len(both) < min_frames:
        return result(None, [f"{len(both)} rAFs with both leaf animations < {min_frames}"])
    starts = {a["start"] for f in both for a in f.values()}
    sums = max(abs(f["in"]["value"] + f["out"]["value"] - 1) for f in both)
    devs = []
    for f in both:
        dur = f["in"].get("dur")
        if not dur:
            return result(None, ["animation without a duration"])
        devs.append(abs(f["in"]["value"] - ease_in_out(f["in"]["ct"] / dur)))
    return result(len(starts) == 1 and sums <= CURVE_SUM_TOL and max(devs) <= CURVE_EASE_TOL, startTimes=sorted(starts, key=str),
                  maxSumErr=sums, maxEaseErr=max(devs), frames=len(both))


def score_monotone(es: list[float], min_frames: int = MIN_MID_FRAMES) -> dict[str, Any]:
    if len(es) < min_frames or not all(math.isfinite(e) for e in es):
        return result(None, [f"{len(es)} fitted transition frames (need {min_frames}, all finite)"])
    drops = [b - a for a, b in zip(es, es[1:])]
    return result(min(drops, default=0) >= -MONOTONE_SLACK and es[-1] >= HANDOFF_E_MIN, worstStep=min(drops, default=0), last=es[-1])


def score_handoff(last: np.ndarray | None, first: np.ndarray | None, exclude: list[Iterable[float]] = (),
                  cal: Calibration = Calibration()) -> dict[str, Any]:
    if last is None or first is None:
        return result(None, ["last transition or first live frame not identified"])
    keep = ~rect_mask(last.shape[:2], exclude, MEDIA_PAD_PX)
    h = float(np.abs(premul(first) - premul(last))[keep].max())
    return result(h <= cal.tau, H=h)


def first_animation_t(raf: list[dict[str, Any]]) -> float | None:
    return next((float(r["t"]) for r in raf if any((a.get("ct") or 0) > 0 for a in r.get("anims") or [])), None)


def score_no_flash(raf: list[dict[str, Any]], window_in_alpha: list[float] | None = None,
                   cal: Calibration = Calibration()) -> dict[str, Any]:
    """Incoming effective opacity 0 in every rAF with the transition DOM before the first animation frame; delay arms
    add the in-only alpha of every screenshot inside that window (>= 2 needed)."""
    start = first_animation_t(raf)
    window = [r for r in raf if r.get("eff") and (start is None or r["t"] < start)]
    problems = []
    if start is None:
        problems.append("no animation frame")
    if window_in_alpha is not None:
        if len(window_in_alpha) < 2:
            problems.append(f"{len(window_in_alpha)} screenshots in the delay window < 2")
        if not window:
            problems.append("no rAF in the delay window")
        elif any(b["t"] - a["t"] > RAF_GAP_MS for a, b in zip(window, window[1:])):
            problems.append("rAF gap in the delay window")
    ok = all(r["eff"][0] == 0 for r in window) and all(a <= cal.complement for a in window_in_alpha or [])
    return result(ok, problems, windowRafs=len(window), windowAlpha=window_in_alpha)


def score_cut(raf: list[dict[str, Any]], cast: list[tuple[float, float]], cast_inside: int,
              cal: Calibration = Calibration()) -> dict[str, Any]:
    """rAFs from DOM insertion: incoming 0 before the cut's first animation frame, then in + out = 1 until incoming 1;
    every screencast (or CEF source) frame |alpha_in-only + alpha_out-only - 255| <= complement."""
    dom = [r for r in raf if r.get("eff")]
    problems = []
    if not dom:
        return result(None, ["no rAF with the transition DOM"])
    start = first_animation_t(raf)
    pre = [r for r in dom if start is None or r["t"] < start]
    post = [r for r in dom if start is not None and r["t"] >= start]
    done = next((i for i, r in enumerate(post) if r["eff"][0] >= 1), None)
    after = [r for r in raf if done is not None and r["t"] > post[done]["t"]]
    if start is None or done is None or len(after) < CUT_AFTER_FRAMES:
        problems.append("rAF coverage does not reach 3 frames after the cut")
    if any(b["t"] - a["t"] > RAF_GAP_MS for a, b in zip(dom, dom[1:])):
        problems.append("rAF gap inside the cut")
    if cast_inside < 1:
        problems.append("no screencast frame inside the cut")
    swap = post[:done] if done is not None else post
    ok = (all(r["eff"][0] == 0 for r in pre) and all(abs(r["eff"][0] + r["eff"][1] - 1) <= CUT_SUM_TOL for r in swap)
          and all(abs(i + o - 255) <= cal.complement for i, o in cast))
    return result(ok, problems, preRafs=len(pre), swapRafs=len(swap), worstCast=max((abs(i + o - 255) for i, o in cast), default=None))


def decode_strip(image: np.ndarray, origin: tuple[float, float] = (0.0, 0.0), scale: float = 1.0) -> int | None:
    return read_strip(np.asarray(image), origin, scale)[0]


def demix(F: np.ndarray, B: np.ndarray, e: float) -> np.ndarray:
    """Ô = (F - e·B) / (1 - e), premultiplied, as straight RGBA uint8."""
    o = (premul(F) - e * premul(B)) / (1 - e)
    a = np.clip(o[..., 3:4], 0, 255)
    rgb = np.where(a > 0, o[..., :3] * 255.0 / np.maximum(a, 1e-6), 0)
    return np.clip(np.rint(np.concatenate([rgb, a], axis=2)), 0, 255).astype(np.uint8)


def demixable(es: list[float]) -> tuple[list[int], int]:
    """Indices of admitted frames with e <= DEMIX_E_MAX, and the largest subset pairwise >= DEMIX_SPREAD apart."""
    idx = [i for i, e in enumerate(es) if MID_E[0] < e <= DEMIX_E_MAX]
    spread, last = 0, -math.inf
    for e in sorted(es[i] for i in idx):
        if e - last >= DEMIX_SPREAD:
            spread, last = spread + 1, e
    return idx, spread


def bind_holders(holders: list[dict[str, Any]], decoders: list[dict[str, Any]], tol: float = BIND_TOL_PX) -> tuple[list[tuple[int, dict[str, Any]]], list[str]]:
    """Each holder binds to the one decoder whose admitted region matches its screen rect within `tol` px."""
    bound, problems = [], []
    for i, h in enumerate(holders):
        hits = [d for d in decoders if d.get("region") and all(abs(a - b) <= tol for a, b in zip(h["rect"], d["region"]))]
        if len(hits) != 1:
            problems.append(f"holder {i} matches {len(hits)} decoders")
        else:
            bound.append((i, hits[0]))
    return bound, problems


def reference_index(decoder: dict[str, Any], fps: float = FPS) -> int | None:
    detach = decoder.get("detach")
    prior = [r for r in decoder.get("rv") or [] if detach is not None and r[0] <= detach]
    return round(prior[-1][1] * fps) if prior else None


def score_frozen(holder_index: int | None, reference: int | None, demixed: list[int | None], *, holder: bool = True) -> dict[str, Any]:
    """The holder (unless `holder` is False: the patch-off arm has none by design) and every Ô decode to the reference."""
    problems = []
    if reference is None:
        problems.append("no reference rVFC record before the detach")
    if holder and holder_index is None:
        problems.append("holder strip does not decode")
    ok = (not holder or holder_index == reference) and all(i == reference for i in demixed)
    return result(ok, problems, holder=holder_index, reference=reference, demixed=demixed)


def score_region(regions: list[np.ndarray], es: list[float], cal: Calibration = Calibration()) -> dict[str, Any]:
    """Ô over the movie region constant across admitted frames: per frame max |Ô - median| <= tau / (1 - e)."""
    if len(regions) < DEMIX_MIN_FRAMES:
        return result(None, [f"{len(regions)} demixed frames < {DEMIX_MIN_FRAMES}"])
    stack = np.stack([r[..., :3].astype(np.float32) for r in regions])
    med = np.median(stack, axis=0)
    spreads = [float(np.abs(s - med).max()) for s in stack]
    return result(all(s <= cal.tau / (1 - e) for s, e in zip(spreads, es)), spreads=spreads)


def score_foreground(candidates: list[np.ndarray], s_live: np.ndarray, mask: np.ndarray,
                     cal: Calibration = Calibration()) -> dict[str, Any]:
    if not mask.any():
        return result(None, ["no counter-block pixel under the foreground"])
    worst = max(float(np.abs(c[..., :3].astype(np.float32) - s_live[..., :3])[mask].max()) for c in candidates)
    return result(worst <= cal.tau, worst=worst, pixels=int(mask.sum()))


def score_tone(holder: np.ndarray, s_live: np.ndarray, s_live2: np.ndarray, mask: np.ndarray, *, identity: bool) -> dict[str, Any]:
    problems = []
    if not mask.any():
        problems.append("empty tone mask")
    cvc = float(np.abs(s_live[..., :3].astype(np.float32) - s_live2[..., :3])[mask].max()) if mask.any() else None
    if cvc is not None and cvc > TONE_CVC:
        problems.append(f"S_live CvC {cvc} > {TONE_CVC}")
    worst = float(np.abs(holder[..., :3].astype(np.float32) - s_live[..., :3])[mask].max()) if mask.any() else None
    return result(worst is not None and worst <= TONE_TOL, problems, report=identity, worst=worst, cvc=cvc)


def score_cost(takes: list[Any]) -> dict[str, Any]:
    values = [t for t in takes if isinstance(t, (int, float)) and not isinstance(t, bool)]
    if not takes or len(values) != len(takes) or not all(math.isfinite(t) for t in values):
        return result(None, [f"take cost missing or non-finite: {takes}"])
    return result(max(values) <= COST_MS, takeMs=values)


def contains(outer: Iterable[float], inner: Iterable[float]) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ox <= ix and oy <= iy and ox + ow >= ix + iw and oy + oh >= iy + ih


def overlaps(a: Iterable[float], b: Iterable[float]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def score_overlay(raf: list[dict[str, Any]], movie_rect: Iterable[float] | None, region: dict[str, Any]) -> dict[str, Any]:
    """No tagged `<video>` outside the transition DOM with effective opacity > 0 meets the outgoing movie rect in any rAF
    of the fade, and Ô there does not drift (`region` = `score_region`)."""
    if movie_rect is None:
        return result(None, ["no outgoing movie rect"])
    fade = [r for r in raf if r.get("eff")]
    if not fade:
        return result(None, ["no rAF of the fade"])
    hits = sorted({v["id"] for r in fade for v in r.get("videos") or []
                   if v.get("on") and not v.get("inT") and (v.get("eff") or 0) > 0 and overlaps(v["rect"], movie_rect)})
    if hits:
        return result(False, overlay=hits)
    if region["verdict"] == "INCONCLUSIVE":
        return result(None, region["problems"])
    return result(region["verdict"] == "PASS", overlay=[], region=region["verdict"])


def score_cvc(a: list[float], b: list[float]) -> dict[str, Any]:
    if not a or not b:
        return result(None, ["no mid-frame residuals"])
    qa, qb = np.quantile(a, [0, 0.5, 1]), np.quantile(b, [0, 0.5, 1])
    diff = float(np.abs(qa - qb).max())
    return result(diff <= CVC_TOL, quantileDiff=diff)


def matched_report(on: list[tuple[float, np.ndarray]], off: list[tuple[float, np.ndarray]]) -> dict[str, Any]:
    """Opaque on vs off at matched eased progress (off interpolated linearly in fitted e); reported against bound 2."""
    off = sorted(off, key=lambda x: x[0])
    worst = []
    for e, F in on:
        lo = max((o for o in off if o[0] <= e), key=lambda o: o[0], default=None)
        hi = min((o for o in off if o[0] >= e), key=lambda o: o[0], default=None)
        if lo is None or hi is None or hi[0] == lo[0]:
            continue
        w = (e - lo[0]) / (hi[0] - lo[0])
        worst.append(float(np.abs(F.astype(np.float32) - ((1 - w) * lo[1] + w * hi[1])).max()))
    if not worst:
        return result(None, ["no matched frames"])
    return result(None, report=True, maxDiff=max(worst), bound=MATCHED_BOUND, within=max(worst) <= MATCHED_BOUND)


def decoders_of(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Each tagged decoder with its last region, content box and rect in the live slide before the transition DOM."""
    dump = record.get("dump") or {}
    last: dict[int, dict[str, Any]] = {}
    for r in dump.get("raf") or []:
        if r.get("eff"):
            break
        for v in r.get("videos") or []:
            if v.get("on") and v.get("geo") and v.get("inStage") and not v.get("inT"):
                last[v["id"]] = v
    out = []
    for vid in dump.get("vids") or []:
        seen = last.get(vid["id"])
        out.append({**vid, "region": seen["geo"]["region"] if seen else None, "content": seen["geo"]["content"] if seen else None,
                    "size": seen["geo"]["size"] if seen else None, "rect": seen["rect"] if seen else None})
    return out


def styles_problems(chain: list[list[dict[str, Any]]] | None, styles: str) -> list[str]:
    if styles == "cut":
        return []
    if not chain or len(chain) != 2:
        return ["no blend/isolation chain"]
    want = {"on": ("plus-lighter", "isolate"), "noblend": ("normal", "isolate"), "none": ("normal", "auto")}[styles]
    problems = []
    for leaf in chain:
        layers = [c for c in leaf if re.fullmatch(r"layer\d+", c.get("id") or "")]
        if len(layers) < 2:
            problems.append("leaf chain without leaf and container layers")
            continue
        if (layers[0]["blend"], layers[1]["isolation"]) != want:
            problems.append(f"leaf {layers[0]['id']} blend {layers[0]['blend']}, container isolation {layers[1]['isolation']}; want {want}")
    return problems


def capture_problems(record: dict[str, Any], images: Mapping[str, np.ndarray], arm: Arm) -> list[str]:
    """Capture integrity (§9.1): any violation makes every check of the arm INCONCLUSIVE."""
    problems = []
    if record.get("error"):
        problems.append(f"run error: {str(record['error']).strip().splitlines()[-1]}")
    target, served, dump = record.get("target") or {}, record.get("served") or {}, record.get("dump") or {}
    first = dump.get("first") or {}
    if not dump.get("raf"):
        problems.append("no rAF records")
    if first.get("textures") != target.get("textures"):
        problems.append(f"texture ids {first.get('textures')} != {target.get('textures')}")
    if record.get("hashBefore") != target.get("hashBefore"):
        problems.append(f"hash before {record.get('hashBefore')} != {target.get('hashBefore')}")
    if target.get("hashAfter") is not None and record.get("hashAfter") != target.get("hashAfter") and arm.row is None:
        problems.append(f"hash after {record.get('hashAfter')} != {target.get('hashAfter')}")
    if record.get("page") != arm.page:
        problems.append(f"page mode {record.get('page')} != {arm.page}")
    pins = live_runtime.SUPPORTED_PLAYERS.get(served.get("stockSha256") or "")
    output_sha = ((record.get("output") or {}).get("mmOpacity") or {}).get("sha256")
    if pins is None:
        problems.append("stock player is not a supported player")
    elif output_sha != served.get("expected"):
        problems.append(f"served digest {output_sha} != expected {served.get('expected')}")
    elif arm.splice is None and output_sha != pins[0 if arm.mode == "on" else 1]:
        problems.append("served digest is not the pinned digest for the mode")
    if record.get("stage") != {"x": 0, "y": 0, "width": VIEWPORT[0], "height": VIEWPORT[1]}:
        problems.append(f"stage {record.get('stage')} is not the full viewport")
    load = record.get("load")
    if not isinstance(load, (int, float)) or load >= MAX_LOAD or record.get("headlessBefore") != 0:
        problems.append(f"load {record.get('load')} / headless before {record.get('headlessBefore')}")
    shots = [images.get(s["name"]) for s in record.get("shots") or []]
    if not shots or any(s is None or s.shape != (VIEWPORT[1], VIEWPORT[0], 4) for s in shots):
        problems.append("screenshots missing or not 1920x1080 RGBA")
    if any(images.get(k) is None for k in ("tex-in", "tex-out")):
        problems.append("textures not captured")
    if arm.holders is not None and len(first.get("holders") or []) != arm.holders:
        problems.append(f"{len(first.get('holders') or [])} holders, expected {arm.holders}")
    problems += styles_problems(first.get("chain"), arm.styles)
    if arm.capture in ("paused", "media", "lifecycle") or arm.movies:
        live = [images.get(k) for k in ("live-0", "live-1")]
        if any(x is None for x in live):
            problems.append("S_live pair missing")
        elif arm.capture == "paused" and not np.array_equal(live[0], live[1]):
            problems.append("the two paused S_live differ")
    if arm.capture == "paused" and (record.get("paused") or {}).get("state") != "presented":
        problems.append(f"movie not paused on a presented frame: {record.get('paused')}")
    if arm.capture == "lifecycle" and images.get("settled") is None:
        problems.append("no settled frame")
    return problems


@dataclass
class Evidence:
    """What one run's record and images say, derived once for every check."""
    shots: list[np.ndarray]
    phases: list[str]
    A: np.ndarray | None
    B: np.ndarray | None
    holders: list[np.ndarray]
    media: list[list[float]]
    raf: list[dict[str, Any]]
    transition: list[int]


def media_rects(record: dict[str, Any]) -> list[list[float]]:
    """Every tagged `<video>` rect seen in the stage during the capture and every holder rect."""
    dump = record.get("dump") or {}
    media = [v["rect"] for r in dump.get("raf") or [] for v in r.get("videos") or [] if v.get("on") and v.get("inStage") and v.get("rect")]
    media += [h["rect"] for h in (dump.get("first") or {}).get("holders") or []]
    return [list(m) for m in {tuple(round(x, 1) for x in m) for m in media}]


def evidence(record: dict[str, Any], images: Mapping[str, np.ndarray]) -> Evidence:
    dump = record.get("dump") or {}
    raf = dump.get("raf") or []
    meta = record.get("shots") or []
    shots = [images[s["name"]] for s in meta if s["name"] in images]
    phases = shot_phases(meta, raf) if len(shots) == len(meta) else ["ambiguous"] * len(shots)
    first = dump.get("first") or {}
    holders = []
    A, B = images.get("tex-out"), images.get("tex-in")
    for i, h in enumerate(first.get("holders") or []):
        img = images.get(f"holder-{i}")
        if img is None or A is None:
            continue
        placed = place(img, h["canvasRect"], h["rect"], A.shape[:2])
        holders.append(placed)
        A = over(placed, A)
    return Evidence(shots, phases, A, B, holders, media_rects(record), raf, [i for i, p in enumerate(phases) if p == "transition"])


def _fade_of(ev: Evidence, arm: Arm, cal: Calibration) -> dict[str, Any]:
    frames = [ev.shots[i] for i in ev.transition]
    return score_fade(frames, ev.A, ev.B, exclude=ev.media, classes=arm.classes, cal=cal, screen=arm.page == "screen")


def _handoff_frames(ev: Evidence) -> tuple[np.ndarray | None, np.ndarray | None]:
    if not ev.transition:
        return None, None
    last = ev.transition[-1]
    first = next((i for i in range(last + 1, len(ev.phases)) if ev.phases[i] == "live"), None)
    return ev.shots[last], None if first is None else ev.shots[first]


def score_media(record: dict[str, Any], images: Mapping[str, np.ndarray], ev: Evidence, arm: Arm, fade: dict[str, Any],
                cal: Calibration, *, identity: bool | None) -> dict[str, dict[str, Any]]:
    """Frozen frame, frozen region, foreground, tone and overlay (DX-M) with the media-evidence rules."""
    first = (record.get("dump") or {}).get("first") or {}
    holders = first.get("holders") or []
    decoders = [d for d in decoders_of(record) if d.get("region")]
    problems = []
    outgoing = [d for d in decoders if d.get("detach") is not None]
    if arm.mode == "off":
        if holders:
            problems.append("a holder on the patch-off arm")
        if len(outgoing) != 1:
            problems.append(f"{len(outgoing)} detached decoders (need exactly one)")
        bound = [(None, outgoing[0])] if len(outgoing) == 1 else []
    else:
        bound, bind_problems = bind_holders(holders, decoders)
        problems += bind_problems
        if not holders:
            problems.append("no bound D4 holder")
    decoder = bound[0][1] if bound else None
    if decoder is not None:
        if not decoder.get("tuple"):
            problems.append("decoder colour tuple missing")
        before = [r for r in decoder.get("rv") or [] if decoder.get("detach") is not None and r[0] <= decoder["detach"]]
        if arm.mode == "off" and (not before or before[-1][2] < MIN_PRESENTED):
            problems.append(f"fewer than {MIN_PRESENTED} presented frames before the advance")
    es = [r["e"] for r in fade["rows"]]
    idx, spread = demixable(es)
    if spread < DEMIX_MIN_FRAMES:
        problems.append(f"{spread} demixable frames pairwise >= {DEMIX_SPREAD} apart < {DEMIX_MIN_FRAMES}")
    frames = [ev.shots[ev.transition[i]] for i in idx]
    demixed = [demix(f, ev.B, es[i]) for f, i in zip(frames, idx)] if ev.B is not None else []
    out: dict[str, dict[str, Any]] = {}
    origin = scale = None
    if decoder is not None and decoder.get("content") and decoder.get("size"):
        cx, cy, cw, _ = decoder["content"]
        origin, scale = (cx, cy), cw / decoder["size"][0]
    if origin is None:
        problems.append("no decoder geometry")
    reference = (record.get("paused") or {}).get("frame") if arm.capture == "paused" else (reference_index(decoder) if decoder else None)
    holder_img = images.get("holder-0")
    holder_index = decode_strip(holder_img) if holder_img is not None and holders else None
    o_indices = [decode_strip(o, origin, scale) for o in demixed] if origin else []
    out["frozen_frame"] = score_frozen(holder_index, reference, o_indices, holder=arm.mode != "off")
    out["frozen_frame"]["problems"] = problems + out["frozen_frame"]["problems"]
    if out["frozen_frame"]["problems"]:
        out["frozen_frame"]["verdict"] = "INCONCLUSIVE"
    region_rect = decoder["region"] if decoder else None
    region_mask = rect_mask(ev.A.shape[:2], [region_rect]) if region_rect and ev.A is not None else None
    if region_mask is not None and region_mask.any():
        ys, xs = np.where(region_mask)
        crop = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
        region = score_region([o[crop] for o in demixed], [es[i] for i in idx], cal)
    else:
        region = result(None, ["no movie region"])
    region["problems"] = problems + region["problems"]
    if region["problems"]:
        region["verdict"] = "INCONCLUSIVE"
    out["frozen_region"] = region
    movie = decoder or (outgoing[0] if len(outgoing) == 1 else None)
    out["overlay"] = score_overlay(ev.raf, movie.get("rect") if movie else None, region)
    if arm.bridge:
        fade_t = [r["t"] for r in ev.raf if r.get("eff")]
        live = {v["id"] for r in ev.raf if r.get("eff") for v in r.get("videos") or [] if v.get("on") and not v.get("inT")}
        tagged = [v for v in (record.get("dump") or {}).get("vids") or [] if v["id"] in live
                  and any(fade_t and fade_t[0] <= rv[0] <= fade_t[-1] for rv in v.get("rv") or [])]
        if not tagged:
            out["overlay"] = result(None, ["no bridged decoder tagged with rVFC records in the fade"])
    live = images.get("live-0")
    if live is not None and ev.holders and origin is not None:
        shape = live.shape[:2]
        later = [c for cs in (record.get("foreground") or {}).values() for c in cs]
        fg_rects = [c["rect"] for c in later if c.get("id") in (*FOREGROUND_TEXTURES, FOREGROUND_SQUARE)]
        mask = block_mask(shape, origin, scale) & rect_mask(shape, fg_rects)
        pair = [r for r in fg_rects if any(overlaps(r, q) for q in fg_rects if q is not r)]
        fg_problems = list(problems) + ([] if rect_mask(shape, pair).any() and mask.any() else ["foreground layers do not overlap over the counter blocks"])
        fg_res = score_foreground([ev.holders[0], *demixed], live, mask, cal)
        fg_res["problems"] = fg_problems + fg_res["problems"]
        if fg_res["problems"]:
            fg_res["verdict"] = "INCONCLUSIVE"
        out["foreground"] = fg_res
        layout = next(iter((record.get("movies") or {}).values()), {}).get("layout") or {}
        tone_rects = (layout.get("ramp") or []) + (layout.get("patches") or [])
        partial = [c["rect"] for c in later if not contains(c["rect"], decoder["region"])]
        tone_mask = source_mask(shape, tone_rects, origin, scale, erode=2) & ~rect_mask(shape, partial, 2)
        if identity is None:
            out["tone"] = result(None, ["no Q0b decision record"])
        else:
            out["tone"] = score_tone(ev.holders[0], live, images.get("live-1", live), tone_mask, identity=identity)
            if problems:
                out["tone"] = result(None, problems + out["tone"]["problems"])
    else:
        missing = problems + ["no holder, S_live or decoder geometry"]
        out["foreground"] = result(None, missing)
        out["tone"] = result(None, missing)
    return out


def score_arm(record: dict[str, Any], images: Mapping[str, np.ndarray], arm: Arm, cal: Calibration = Calibration(), *,
              identity: bool | None = None) -> dict[str, Any]:
    """Every check in the arm's contract; integrity problems make each one INCONCLUSIVE."""
    problems = capture_problems(record, images, arm)
    ev = evidence(record, images)
    checks: dict[str, dict[str, Any]] = {}
    fade = _fade_of(ev, arm, cal) if ev.A is not None and ev.B is not None else {"problems": ["no textures"], "rows": [], "checks": {}}
    problems += [p for p in fade["problems"] if p.startswith("class ")]
    for name in ("model", "complement", "no_dip", "screen"):
        if name in arm.expect:
            key = "model" if name == "screen" else name
            checks[name] = result(fade["checks"].get(key), fade["problems"], mid=fade.get("mid"))
    if "curve" in arm.expect:
        checks["curve"] = score_curve(ev.raf)
    if "monotone" in arm.expect:
        checks["monotone"] = score_monotone([r["e"] for r in fade["rows"]])
    if "handoff" in arm.expect:
        checks["handoff"] = score_handoff(*_handoff_frames(ev), exclude=ev.media, cal=cal)
    if "no_flash" in arm.expect:
        window = None
        if arm.capture == "delay" and ev.B is not None and ev.A is not None:
            start = first_animation_t(ev.raf) or math.inf
            inonly = texture_classes(ev.A, ev.B)["in"]
            window = [float(np.median(ev.shots[i][..., 3][inonly])) for i in ev.transition
                      if (record.get("shots") or [])[i]["t1"] < start]
        checks["no_flash"] = score_no_flash(ev.raf, window, cal)
    if "cut" in arm.expect:
        cast_rows, inside = [], 0
        dom = [r["t"] for r in ev.raf if r.get("eff")]
        if ev.A is not None and ev.B is not None and dom:
            m = texture_classes(ev.A, ev.B)
            for c in record.get("cast") or []:
                img = images.get(c["name"])
                if img is None or img.shape[:2] != m["in"].shape:
                    continue
                cast_rows.append((float(np.median(img[..., 3][m["in"]])), float(np.median(img[..., 3][m["out"]]))))
                inside += dom[0] <= c["t"] <= dom[-1] + 3 * RAF_SLACK_MS
        checks["cut"] = score_cut(ev.raf, cast_rows, inside, cal)
    if {"frozen_frame", "frozen_region", "foreground", "tone", "overlay"} & set(arm.expect):
        media = score_media(record, images, ev, arm, fade, cal, identity=identity)
        checks.update({k: v for k, v in media.items() if k in arm.expect})
    if "cost" in arm.expect:
        checks["cost"] = score_cost(sorted({r["take"] for r in ev.raf if r.get("take") is not None}, key=str))
    for name, expected in arm.expect.items():
        if expected == "N/A":
            checks[name] = result(None)
        elif expected == "REPORTED" and name in checks and checks[name]["verdict"] in ("PASS", "FAIL"):
            checks[name] = {**checks[name], "verdict": "REPORTED", "detail": {**checks[name]["detail"], "outcome": checks[name]["verdict"]}}
    if problems:
        checks = {k: {**v, "verdict": "INCONCLUSIVE" if v["verdict"] != "N/A" else "N/A", "problems": problems + v["problems"]}
                  for k, v in checks.items()}
    mismatch = sorted(k for k, want in arm.expect.items() if checks.get(k, {}).get("verdict") != want)
    inconclusive = any(checks.get(k, {}).get("verdict") == "INCONCLUSIVE" for k in arm.expect)
    outcome = "INCONCLUSIVE" if inconclusive else ("MATCH" if not mismatch else "MISMATCH")
    return {"outcome": outcome, "checks": checks, "mismatch": mismatch, "problems": problems,
            "midResiduals": [r["residual"] for r in fade["rows"] if math.isfinite(r["e"]) and MID_E[0] < r["e"] < MID_E[1]],
            "fitted": [(r["e"], i) for r, i in zip(fade["rows"], ev.transition)]}


def score_lifecycle(record: dict[str, Any], images: Mapping[str, np.ndarray], twin: tuple[dict[str, Any], Mapping[str, np.ndarray]] | None,
                    arm: Arm, cal: Calibration = Calibration()) -> dict[str, Any]:
    """One lifecycle row against its stock twin (§9.1 lifecycle scenario)."""
    row = arm.row or ""
    problems = capture_problems(record, images, arm)
    if twin is None:
        problems.append("stock twin missing")
    ev = evidence(record, images)
    first = (record.get("dump") or {}).get("first") or {}
    checks: dict[str, dict[str, Any]] = {}
    settled = images.get("settled")
    if twin is not None and settled is not None and twin[1].get("settled") is not None:
        keep = ~rect_mask(settled.shape[:2], ev.media + media_rects(twin[0]), MEDIA_PAD_PX)
        diff = float(np.abs(premul(settled) - premul(twin[1]["settled"]))[keep].max())
        checks["settled"] = result(diff <= cal.tau, diff=diff)
        if row in ("queued-advance", "queued-skip"):
            checks["hash"] = result(record.get("hashAfter") == twin[0].get("hashAfter"), hash=record.get("hashAfter"),
                                    twin=twin[0].get("hashAfter"))
    else:
        checks["settled"] = result(None, ["settled frame of run or twin missing"])
    residue = record.get("residue") or {}
    if row == "end-of-show":
        after = record.get("residueAfterGoto") or {}
        checks["cleanup"] = result(bool(after) and not any(after.values()), residue=residue, afterGoto=after)
    else:
        checks["cleanup"] = result(bool(residue) and not any(residue.values()), residue=residue)
    if row in ("advance", "replay", "automatic", "loop-wrap"):
        checks["holder"] = result(len(first.get("holders") or []) == 1, holders=len(first.get("holders") or []))
    if row == "replay":
        pre = ((record.get("pre") or {}).get("first")) or {}
        fresh = bool(pre) and not set(pre.get("layerIds") or []) & set(first.get("layerIds") or [])
        checks["fresh"] = result(fresh and len(pre.get("holders") or []) == 1, preIds=pre.get("layerIds"), ids=first.get("layerIds"))
    visible = list(ev.transition)
    actions = {a["name"]: a["t"] for a in record.get("actions") or []}
    if row.startswith("hide"):
        hidden = [i for i, s in enumerate(record.get("shots") or []) if actions.get("hide", math.inf) + RAF_SLACK_MS <= s["t0"]
                  and s["t1"] <= actions.get("show", -math.inf)]
        screen = arm.page == "screen"
        dark = [bool(np.all(ev.shots[i][..., :3] == 0)) if screen else bool(np.all(ev.shots[i][..., 3] == 0)) for i in hidden]
        checks["hidden"] = result(all(dark), [] if hidden else ["no screenshot while hidden"], frames=len(hidden))
        visible = [i for i in visible if i not in hidden and (record.get("shots") or [])[i]["t0"] >= actions.get("show", math.inf)]
        if ev.A is not None and ev.B is not None:
            post = score_fade([ev.shots[i] for i in visible], ev.A, ev.B, exclude=ev.media, classes=(), cal=cal,
                              screen=screen, min_frames=1)
            checks["model-after-show"] = result(post["checks"].get("model"), post["problems"])
    if ev.A is not None and ev.B is not None and not row.startswith("hide"):
        fade = score_fade([ev.shots[i] for i in visible], ev.A, ev.B, exclude=ev.media, classes=("out", "in"), cal=cal, min_frames=1)
        checks["complement"] = result(fade["checks"].get("complement"), fade["problems"])
    checks["no_flash"] = score_no_flash(ev.raf, None, cal)
    if problems:
        checks = {k: {**v, "verdict": "INCONCLUSIVE", "problems": problems + v["problems"]} for k, v in checks.items()}
    verdicts = [c["verdict"] for c in checks.values()]
    outcome = "INCONCLUSIVE" if "INCONCLUSIVE" in verdicts else ("MATCH" if all(v == "PASS" for v in verdicts) else "MISMATCH")
    return {"outcome": outcome, "checks": checks, "problems": problems}


def scorer_cases(cal: Calibration = Calibration()) -> dict[str, dict[str, Any]]:
    """Synthetic scorer controls named in §9's control table, scored with the run's calibration."""
    flat = np.zeros((8, 8, 4), np.uint8)
    flat[..., 3] = 255
    flat[..., :3] = 100
    step = flat.copy()
    step[2:4, 2:4, :3] = 100 + int(cal.tau) + 2
    live = flat.copy()
    live[2:6, 2:6, :3] = 200
    mask = rect_mask((8, 8), [(2, 2, 4, 4)])
    shifted = flat.copy()
    shifted[4:8, 4:8, :3] = 200
    double = flat.copy()
    double[2:6, 2:6, :3] = 150
    swapped = flat.copy()
    swapped[2:6, 2:6, :3] = 60
    linear = [{"t": i, "eff": [i / 10, 1 - i / 10], "anims": [
        {"leaf": "in", "ct": i * 150.0, "start": 0, "state": "running", "dur": 1500.0, "value": i / 10},
        {"leaf": "out", "ct": i * 150.0, "start": 0, "state": "running", "dur": 1500.0, "value": 1 - i / 10}]} for i in range(1, 9)]
    cut = ([{"t": 0.0, "eff": [0, 1], "anims": []}]
           + [{"t": 16.0 * k, "eff": [v, 1 - v], "anims": [{"ct": 0.5}]} for k, v in ((1, 0.5), (2, 1.0))]
           + [{"t": 16.0 * k} for k in (3, 4, 5)])
    return {
        "case:curve-linear": score_curve(linear),
        "case:monotone-dip": score_monotone([0.06, 0.2, 0.4, 0.3, 0.7, 0.9, 1.0]),
        "case:handoff-unchanged": score_handoff(flat, flat.copy(), cal=cal),
        "case:handoff-step": score_handoff(flat, step, cal=cal),
        "case:cut-complementary": score_cut(cut, [(127.5, 127.5)], 1, cal),
        "case:fg-shifted": score_foreground([shifted], live, mask, cal),
        "case:fg-double": score_foreground([double], live, mask, cal),
        "case:fg-swapped": score_foreground([swapped], live, mask, cal),
        "case:cost-50": score_cost([COST_MS]),
        "case:cost-50-eps": score_cost([COST_MS + 1e-6]),
    }


def score_round(scored: dict[str, dict[str, Any]], cal: Calibration = Calibration(), *, identity: bool | None = None,
                extra: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Per §9 check: every control is read first (positive PASS, negative FAIL; missing or INCONCLUSIVE invalidates);
    only then do the candidates (other arms expecting PASS) count."""
    cases = scorer_cases(cal)
    gates: dict[str, Any] = {}
    for check, (positive, negative) in CONTROLS.items():
        if check == "tone" and identity is not False:
            gates[check] = {"verdict": "REPORTED", "reasons": ["identity L or no decision record: tone is report-only"]}
            continue
        reasons = []
        for name, want in [(n, "PASS") for n in positive] + [(n, "FAIL") for n in negative]:
            got = cases[name]["verdict"] if name in cases else ((scored.get(name) or {}).get("checks") or {}).get(check, {}).get("verdict")
            if got != want:
                reasons.append(f"control {name}: {got or 'missing'} (must {want})")
        candidates = {n: s["checks"][check]["verdict"] for n, s in scored.items()
                      if n not in positive + negative and ARMS.get(n) and ARMS[n].expect.get(check) == "PASS" and check in s["checks"]}
        if reasons:
            verdict = "INCONCLUSIVE"
        elif any(v != "PASS" for v in candidates.values()):
            verdict = "INCONCLUSIVE" if "INCONCLUSIVE" in candidates.values() else "FAIL"
        else:
            verdict = "PASS"
        gates[check] = {"verdict": verdict, "reasons": reasons, "candidates": candidates}
    gates.update(extra or {})
    arms = {n: s["outcome"] for n, s in scored.items()}
    verdicts = [g["verdict"] for g in gates.values() if g["verdict"] in ("PASS", "FAIL", "INCONCLUSIVE")]
    verdicts += ["FAIL" if o == "MISMATCH" else "INCONCLUSIVE" for o in arms.values() if o != "MATCH"]
    overall = next((v for v in ("FAIL", "INCONCLUSIVE") if v in verdicts), "PASS" if verdicts else "INCONCLUSIVE")
    return {"overall": overall, "gates": gates, "arms": arms}


def decode_rgba(data: str | bytes) -> np.ndarray:
    raw = base64.b64decode(data.split(",", 1)[1] if isinstance(data, str) and data.startswith("data:") else data)
    return np.asarray(Image.open(io.BytesIO(raw)).convert("RGBA"))


def pending_scene(snapshot: dict[str, Any] | None) -> int | None:
    if not snapshot or not snapshot.get("ready"):
        return None
    return snapshot.get("scene") if snapshot.get("state") == "IdleAtInitialState" else snapshot.get("next")


def wait_ready(evaluate: Callable[[str], Any], timeout_s: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        snap = evaluate(SNAPSHOT_JS)
        if snap and snap.get("ready"):
            return snap
        time.sleep(0.05)
    raise RuntimeError("player never became ready")


def navigate(host: Any, scene: int, limit: int) -> None:
    """Advance until the next advance plays `scene`."""
    evaluate = host._require_transport().evaluate
    for _ in range(limit + 1):
        if pending_scene(wait_ready(evaluate)) == scene:
            return
        host.execute("advance")
    raise RuntimeError(f"scene {scene} not reached in {limit} advances")


def act(host: Any, name: str) -> None:
    transport = host._require_transport()
    keys = {"space": [(" ", "Space", 32)], "skip": [("]", "BracketRight", 221)], "back": [("ArrowLeft", "ArrowLeft", 37)],
            "goto1": [("1", "Digit1", 49), ("Enter", "Enter", 13)]}
    if name == "advance":
        host.execute("advance")
    elif name in keys:
        for key in keys[name]:
            transport.key(*key)
    else:
        transport.evaluate(f"window.__obedOutput.{name}()")


def burst(host: Any, target: dict[str, Any], capture: Callable[[], np.ndarray], *, actions: Iterable[tuple[float, str]] = (),
          screencast: Callable[[], Any] | None = None, lead_s: float = 0.0, tag: str = "") -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Arm the hook, screenshot from `PRE_S` before the advance to T + `POST_S` (+ `lead_s`), run timed `actions`."""
    evaluate = host._require_transport().evaluate
    origin = evaluate(f"window.__obedDx.arm({json.dumps(target['textures'])})")["timeOrigin"]

    def now() -> float:
        return time.time() * 1000.0 - origin

    record: dict[str, Any] = {"shots": [], "actions": [], "cast": []}
    images: dict[str, np.ndarray] = {}
    pending = sorted(actions)
    span = PRE_S + lead_s + target["beginS"] + target["durationS"] + POST_S + max((t for t, _ in pending), default=0.0)
    errors: list[str] = []

    def advance() -> None:
        try:
            host.execute("advance")
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    with (screencast() if screencast else contextlib.nullcontext([])) as frames:
        cast = frames
        started, thread = time.monotonic(), None
        while time.monotonic() - started < span:
            elapsed = time.monotonic() - started
            if thread is None and elapsed >= PRE_S:
                record["advanceAt"] = now()
                thread = threading.Thread(target=advance, daemon=True)
                thread.start()
            while thread is not None and pending and elapsed - PRE_S >= pending[0][0]:
                name = pending.pop(0)[1]
                act(host, name)
                record["actions"].append({"name": name, "t": now()})
            t0 = now()
            img = capture()
            name = f"{tag}shot-{len(record['shots']):03d}"
            images[name] = img
            record["shots"].append({"name": name, "t0": t0, "t1": now()})
        if thread is not None:
            thread.join(timeout=30)
    for k, (ts, img) in enumerate(cast):
        name = f"{tag}cast-{k:03d}"
        images[name] = img
        record["cast"].append({"name": name, "t": ts * 1000.0 - origin})
    evaluate("window.__obedDx.disarm()")
    record["dump"] = evaluate("window.__obedDx.dump()", deadline_s=60)
    pictures = evaluate("window.__obedDx.images()", deadline_s=120) or {}
    for key, png in zip(("tex-in", "tex-out"), pictures.get("tex") or []):
        if png:
            images[tag + key] = decode_rgba(png)
    for i, png in enumerate(pictures.get("holders") or []):
        if png:
            images[f"{tag}holder-{i}"] = decode_rgba(png)
    if errors:
        record["advanceErrors"] = errors
    return record, images


def settle(host: Any, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while host.observe().busy and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.5)


def drive(host: Any, arm: Arm, target: dict[str, Any], capture: Callable[[], np.ndarray], *,
          screencast: Callable[[], Any] | None = None) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """The one parametrized driver for every arm and lifecycle row on a started host (headless here, CEF in DX-2)."""
    transport = host._require_transport()
    evaluate = transport.evaluate
    row = LIFECYCLE.get(arm.row or "", {})
    host.execute("show")
    record: dict[str, Any] = {}
    goal = target["scene"] - 1 if target["automatic"] else target["scene"]
    navigate(host, goal, target["sceneCount"])
    images: dict[str, np.ndarray] = {}
    if row.get("replay"):
        time.sleep(SETTLE_S)
        pre, _ = burst(host, target, capture, tag="pre-")
        record["pre"] = pre["dump"]
        settle(host)
        host.execute("goTo", arm.slide)
        navigate(host, goal, target["sceneCount"])
    time.sleep(SETTLE_S)
    if arm.capture == "paused":
        record["pauseId"] = evaluate(f"window.__obedDx.pause({PAUSE_FRAME}, {FPS})")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and (evaluate("window.__obedDx.paused()") or {}).get("state") != "presented":
            time.sleep(0.05)
        time.sleep(0.3)
        record["paused"] = evaluate("window.__obedDx.paused()")
    record["stage"] = evaluate(STAGE_JS)
    record["foreground"] = evaluate("window.__obedDx.foreground()")
    images["live-0"] = capture()
    time.sleep(LIVE_GAP_S)
    images["live-1"] = capture()
    record["hashBefore"] = evaluate("String(location.hash||'')")
    lead = target["previousS"] + target["beginS"] if target["automatic"] else 0.0
    shots, shot_images = burst(host, target, capture, actions=row.get("actions", ()), screencast=screencast, lead_s=lead)
    record.update(shots)
    images.update(shot_images)
    settle(host)
    images["settled"] = capture()
    record["hashAfter"] = evaluate("String(location.hash||'')")
    ids = ((record.get("dump") or {}).get("first") or {}).get("layerIds") or []
    record["residue"] = evaluate(f"window.__obedDx.residue({json.dumps(ids)})")
    if row.get("end"):
        host.execute("goTo", 1)
        settle(host)
        record["residueAfterGoto"] = evaluate(f"window.__obedDx.residue({json.dumps(ids)})")
    return record, images


@contextlib.contextmanager
def screencast_frames(port: int) -> Iterator[list[tuple[float, np.ndarray]]]:
    """Every composited frame (PNG) over a second CDP connection, as (epoch seconds, RGBA)."""
    from websockets.sync.client import connect

    frames: list[tuple[float, np.ndarray]] = []
    stop = threading.Event()
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as response:
        pages = [t for t in json.loads(response.read()) if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    if len(pages) != 1:
        raise RuntimeError(f"{len(pages)} page targets for the screencast")

    def run() -> None:
        with connect(pages[0]["webSocketDebuggerUrl"], max_size=None, open_timeout=5) as ws:
            ws.send(json.dumps({"id": 1, "method": "Page.startScreencast", "params": {"format": "png", "everyNthFrame": 1}}))
            k = 0
            while not stop.is_set():
                try:
                    msg = json.loads(ws.recv(timeout=0.2))
                except TimeoutError:
                    continue
                if msg.get("method") == "Page.screencastFrame":
                    params = msg["params"]
                    k += 1
                    frames.append((float(params["metadata"].get("timestamp") or math.nan), decode_rgba(params["data"])))
                    ws.send(json.dumps({"id": 1000 + k, "method": "Page.screencastFrameAck", "params": {"sessionId": params["sessionId"]}}))
            ws.send(json.dumps({"id": 2, "method": "Page.stopScreencast"}))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    time.sleep(0.3)
    try:
        yield frames
    finally:
        stop.set()
        thread.join(timeout=10)


def start_chrome(profile: Path, *, gpu: bool) -> tuple[subprocess.Popen[bytes], int]:
    from obed_edom.devtools_port import DEVTOOLS_ACTIVE_PORT, verify_devtools_owner, wait_devtools_active_port

    profile.mkdir(parents=True, exist_ok=True)
    (profile / DEVTOOLS_ACTIVE_PORT).unlink(missing_ok=True)
    args = [str(CHROME), "--headless=new", "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={profile}", f"--window-size={VIEWPORT[0]},{VIEWPORT[1]}", "--force-device-scale-factor=1",
            "--autoplay-policy=no-user-gesture-required", "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows", "--mute-audio", "--no-first-run",
            "--no-default-browser-check", *([] if gpu else ["--disable-gpu"]), "about:blank"]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    endpoint = wait_devtools_active_port(profile, proc, 20)
    verify_devtools_owner(endpoint, 2)
    return proc, endpoint.port


def run_arm(name: str, scratch: Path, decision: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    import live_continuity_probe as probe

    from obed_edom.live_host import LiveOutputHost

    arm = ARMS[name]
    record: dict[str, Any] = {"arm": name, "page": arm.page, "load": os.getloadavg()[0], "headlessBefore": mmo.headless_chromes()}
    images: dict[str, np.ndarray] = {}
    proc = host = None
    profile = Path(tempfile.mkdtemp(prefix="dissolve-probe-"))
    try:
        resolved = resolve(arm, scratch, decision, tag=name)
        record.update(resolved.fields())
        attach = port = None
        if arm.page == "alpha":
            proc, port = start_chrome(profile, gpu=arm.gpu)
            attach = f"http://127.0.0.1:{port}"
        else:
            probe.force_viewport(*VIEWPORT)
        host = LiveOutputHost(resolved.root, resolved.slides, headless=True, resolver=resolved.resolver,
                              transport_factory=hooked_transport(), attach_endpoint=attach, continuity=arm.continuity,
                              gl_replay="off", mm_opacity="auto" if arm.mode == "on" else "off")
        with serving(arm.splice):
            host.start()
        transport = host._require_transport()
        transport.call("Emulation.setDeviceMetricsOverride", width=VIEWPORT[0], height=VIEWPORT[1], deviceScaleFactor=1, mobile=False)
        if arm.page == "alpha":
            transport.call("Emulation.setDefaultBackgroundColorOverride", color={"r": 0, "g": 0, "b": 0, "a": 0})
        record["output"] = {k: host.output.get(k) for k in ("mmOpacity", "continuity")}
        port = port or transport.port

        def capture() -> np.ndarray:
            return decode_rgba(transport.call("Page.captureScreenshot", format="png", fromSurface=True)["data"])

        driven, images = drive(host, arm, resolved.target, capture,
                               screencast=(lambda: screencast_frames(port)) if arm.capture == "cut" else None)
        record.update(driven)
    except Exception:  # noqa: BLE001
        record["error"] = traceback.format_exc()
    finally:
        if host is not None:
            try:
                host.stop()
            except Exception as exc:  # noqa: BLE001
                record["stopError"] = str(exc)
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    return record, images


def save_run(out: Path, name: str, record: dict[str, Any], images: Mapping[str, np.ndarray]) -> None:
    run = out / "runs" / name
    run.mkdir(parents=True, exist_ok=True)
    for key, img in images.items():
        Image.fromarray(img).save(run / f"{key}.png")
    (run / "record.json").write_text(json.dumps(record, default=str))


class RunImages(Mapping):
    """A saved run's PNGs, decoded on access (a round does not fit in memory at once)."""

    def __init__(self, folder: Path) -> None:
        self.paths = {p.stem: p for p in folder.glob("*.png")}

    def __getitem__(self, key: str) -> np.ndarray:
        return np.asarray(Image.open(self.paths[key]).convert("RGBA"))

    def __iter__(self) -> Iterator[str]:
        return iter(self.paths)

    def __len__(self) -> int:
        return len(self.paths)


def load_runs(out: Path) -> dict[str, tuple[dict[str, Any], Mapping[str, np.ndarray]]]:
    return {path.parent.name: (json.loads(path.read_text()), RunImages(path.parent))
            for path in sorted((out / "runs").glob("*/record.json"))}


def score_runs(runs: dict[str, tuple[dict[str, Any], Mapping[str, np.ndarray]]], decision: dict[str, Any] | None = None,
               cal: Calibration = Calibration()) -> dict[str, Any]:
    identity = None if not decision or "L" not in decision else decision["L"] == "identity"
    scored = {}
    for name, (record, images) in runs.items():
        arm = ARMS.get(name)
        if arm is None or (arm.row is not None and arm.twin is None):
            continue
        if identity and "tone" in arm.expect:
            arm = replace(arm, expect={**arm.expect, "tone": "REPORTED"})
        if arm.row is not None:
            scored[name] = score_lifecycle(record, images, runs.get(arm.twin), arm, cal)
        else:
            scored[name] = score_arm(record, images, arm, cal, identity=identity)
    extra = {}
    if "on" in scored and "on2" in scored:
        extra["cvc"] = score_cvc(scored["on"]["midResiduals"], scored["on2"]["midResiduals"])
    if "opaque-on" in runs and "opaque-off" in runs:
        def frames(name: str) -> list[tuple[float, np.ndarray]]:
            record, images = runs[name]
            shots = [images[s["name"]] for s in record.get("shots") or []]
            return [(e, premul(shots[i])) for e, i in scored[name]["fitted"] if 0.03 < e < 0.97 and i < len(shots)]
        extra["matched"] = matched_report(frames("opaque-on"), frames("opaque-off"))
    verdict = score_round(scored, cal, identity=identity, extra=extra)
    verdict["detail"] = scored
    return verdict


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--score", type=Path, help="re-score the runs saved under DIR/runs without a browser")
    parser.add_argument("--arms", default="all", help="comma list of " + ",".join(ARMS))
    parser.add_argument("--scratch", type=Path, help="scratch for strips, movies and edits (default DIR/scratch)")
    parser.add_argument("--decision", type=Path, help="Q0b decision record JSON: L, counterEncoding, toneEncoding")
    args = parser.parse_args(argv)
    if (args.out is None) == (args.score is None):
        parser.error("give exactly one of --out or --score")
    args.arms = list(ARMS) if args.arms == "all" else [a for a in args.arms.split(",") if a]
    if not set(args.arms) <= set(ARMS):
        parser.error("unknown arm: " + ",".join(sorted(set(args.arms) - set(ARMS))))
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = args.score or args.out
    decision = json.loads(args.decision.read_text()) if args.decision else None
    if args.out is not None:
        scratch = args.scratch or out / "scratch"
        for name in args.arms:
            if name == "m-tone-raw" and decision and decision.get("L") == "identity":
                continue
            running, load = mmo.headless_chromes(), os.getloadavg()[0]
            if running or load >= MAX_LOAD:
                raise SystemExit(f"{running} headless Chromes running, 1-min load {load:.2f}; refusing to start {name}")
            record, images = run_arm(name, scratch, decision)
            save_run(out, name, record, images)
            print(f"{name}: {'error' if record.get('error') else 'ok'}", flush=True)
    verdict = score_runs(load_runs(out), decision)
    (out / "verdict.json").write_text(json.dumps(verdict, indent=1, default=str))
    for check, gate in verdict["gates"].items():
        print(f"{check}: {gate['verdict']} {gate.get('reasons') or ''}")
    for name, outcome in verdict["arms"].items():
        print(f"arm {name}: {outcome}")
    print(f"overall: {verdict['overall']}")
    return 0 if verdict["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
