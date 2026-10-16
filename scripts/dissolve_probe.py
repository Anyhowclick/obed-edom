#!/usr/bin/env python3
"""DX-1 headless gate for the dissolve cross-fade, cut and movie-freeze patch (plan `keynote_live_dissolve_crossfade` §9.1).

One fresh headless Chrome per arm (1920x1080 at DSF 1 unless the arm sets `viewport`/`dsf`; its own port), driven through
`LiveOutputHost` (attach on the alpha page, launch on the screen page) or, for `m-raw*`, `RawHost` (the export's own page,
navigator present, Space over CDP, `RAW_INJECTIONS` before the advance; `m-*-prod` on the production bytes with no channel).
The take freezes only on a page granted `snap` (decision 15): DX-1 arms commit it through the privileged channel after
start (`commit_grant`: the attach host's token, or the raw page's own first-run script), `grant-*` / `life-grant-*` let
the launching host grant it itself, and the `grant: "none"` arms (`grant-attach`, `*-prod`, `cef-skip*`) never get it. The resolver serves html-unmodified's index.html, player and slide JSON, PDFs from a fresh
scratch strip (`html_alpha_probe.strip_export_pdf_bg_fills`), decodable movies (P2: html-player H.264; DX-M: the binary
counter re-encoded with an `ENCODINGS` entry unless Q0b qualified the untagged tuple; tone arms: the tone movie, same
encoder) and the arm's in-memory JSON edits, and records provenance. The served player is `live_runtime.patch_player` for
the arm's mode plus its counted splices (`SPLICES`, `+`-joined; a count mismatch refuses); its digest is checked against
`live_runtime.SUPPORTED_PLAYERS` at score time.

The innermost hook (`HOOK_JS`) records per rAF each transition leaf's effective opacity, every transition animation,
the hash and every tagged `<video>` (rect, effective opacity, transition-DOM membership, content box and clipped region,
colour tuple, rVFC records, detach time) and every `window.__obedTakeMs` publication; at the first transition rAF it keeps the textures,
every holder (pixels and geometry) and the blend/isolation chain; before the advance, the foreground inventory (every
later canvas meeting a movie's region, with its pixels). Alpha PNG screenshots run from `PRE_S` before the advance to
T + `POST_S`; cut arms and hide rows add a timestamped per-frame screencast. Reference arms (`m-snap*`, `m-tone`, their
twins) replace the timed burst by the paused, seeked reference-capture profile (`reference_burst`).

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
import fnmatch
import hashlib
import io
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, fields, is_dataclass, replace
from enum import Enum
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

from obed_edom import dsk_movie_export, live_runtime, placement_probe  # noqa: E402
from obed_edom.fixture_paths import main_checkout  # noqa: E402

FIXTURES = main_checkout() / "output" / "fixtures"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
VIEWPORT = (1920, 1080)
FPS = binary.FPS
TAU = 4.0
COMPLEMENT_TOL = 2.0
NO_DIP_MIN = 252.0
MID_E = (0.05, 0.95)
COVERAGE = {"midFrames": 6, "delayShots": 2, "demixable": 3, "afterShow": 6, "toneCells": 0.5}
MIN_MID_FRAMES = COVERAGE["midFrames"]
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
DEMIX_MIN_FRAMES = COVERAGE["demixable"]
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
HANDOFF_S = 3.0
HANDOFF_SHOTS = 2
LIVE_GAP_S = 0.1
PAUSE_FRAME = 300
SLIDE = (1920, 1080)
REF_STATES = (("F50", 0.5), ("B", 0.9995), ("A0", 0.0))
REF_CT_TOL_MS = 1.0
TIMER_MIN_MS = 400
TIMER_EXTRA_MS = 600_000
REF_EFF_TOL = 1e-3
REF_MODEL_TOL = 2.0
PERFECT_TOL = 1.0
MASK_DILATE = 2
MASK_EXCESS = 0.01
TONE_ERODE = 2
TONE_CELL_PX = 16
DARK_MAX = 2.0
VERDICTS = ("PASS", "FAIL", "INCONCLUSIVE", "REPORTED", "N/A")
MOVIE_SUFFIXES = (".mov", ".mp4", ".m4v")
PLACEMENT_SCHEMA_VERSION = 1
PLACEMENT_BACKENDS = ("cef", "chrome-harness")
PREPARATION_CACHE_VERSION = 1

_PREPARATION_CACHE: Path | None = None
_TOOLCHAIN_INPUTS: dict[str, Any] | None = None


class ReadinessTimeout(RuntimeError):
    pass


def set_preparation_cache(path: Path | None) -> None:
    global _PREPARATION_CACHE
    _PREPARATION_CACHE = None if path is None else Path(path).resolve()


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
    "sn-frac": (b"sn=function(z,e,k){return Math.round((z-e)*k*p)/p}", b"sn=function(z,e,k){return(z-e)*k}", 1),
    "snap-shift": (b's.left=a0+"px"', b's.left=a0+1/p+"px"', 1),
    "frac-nooffset-x": (b"fx=dx+(r.left-R.left)+Math.round(cx-r.left)-u0",
                         b"fx=dx+Math.round(cx-r.left)-u0", 1),
    "frac-nooffset-y": (b"fy=dy+(r.top-R.top)+Math.round(cy-r.top)-v0",
                         b"fy=dy+Math.round(cy-r.top)-v0", 1),
    "frac-underlay-omit": (b'g=x.getContext("2d");g.drawImage(v,dx,dy,dw,dh);if("frac"===pl)',
                             b'g=x.getContext("2d");if("frac"===pl)', 1),
}

RAW_STYLE = '<style id="obed-dx-transparent">html,body,#body{background:transparent!important}</style>'
_SVG_PATH = ("var N='http://www.w3.org/2000/svg',s=document.createElementNS(N,'svg'),p=document.createElementNS(N,'path');"
             "p.setAttribute('d','M0 0 L150 0');p.setAttribute('stroke','red');p.setAttribute('stroke-width','40');"
             "p.setAttribute('transform','translate(250 50)');")
_SHADOW_HOST = ("var h=document.createElement('div');h.style.cssText='position:absolute;left:-400px;top:0;width:10px;height:10px';"
                "document.body.appendChild(h);var r=h.attachShadow({mode:'open'});")
_RANGE = "var g=document.createRange();g.selectNodeContents(d);var p=g.getBoundingClientRect(),b=d.getBoundingClientRect();"
_BOXES = "return {box:[b.left,b.top,b.width,b.height],paint:[p.left,p.top,p.width,p.height]}"
RAW_INJECTIONS = {
    "caption": "(function(){var d=document.createElement('div');d.style.cssText='position:absolute;left:-60px;top:900px;width:40px;"
               "height:20px;overflow:visible;white-space:nowrap;color:#fff;font-size:40px';d.textContent='OVERFLOWING-CAPTION';"
               "document.body.appendChild(d);" + _RANGE + _BOXES + "})()",
    "nav-open": "(function(){var s=document.querySelector('.navigatorThumbnailSidebar');if(!s)return null;s.style.transition='none';"
                "s.style.left='0px';var b=s.getBoundingClientRect();return {box:[b.left,b.top,b.width,b.height]}})()",
    "modal": "(function(){var d=document.createElement('dialog');d.style.cssText='position:fixed;left:-400px;top:0;margin:0;width:200px;"
             "height:100px;overflow:hidden';d.textContent='modal';document.body.appendChild(d);d.showModal();"
             "return {open:d.open,modal:document.querySelector(':modal')===d}})()",
    "svg": "(function(){" + _SVG_PATH + "s.setAttribute('style','position:absolute;left:-300px;top:400px;width:200px;height:200px;"
           "overflow:visible;visibility:hidden');var g=document.createElementNS(N,'g');g.setAttribute('style','display:block;"
           "position:relative;overflow:hidden;visibility:visible');g.appendChild(p);s.appendChild(g);document.body.appendChild(s);"
           "var r=p.getBoundingClientRect();return {paint:[r.left,r.top,r.width,r.height]}})()",
    "svgclip": "(function(){" + _SVG_PATH + "var w=document.createElement('div');w.style.cssText='position:absolute;left:-300px;"
               "top:400px;width:200px;height:200px;overflow:hidden';s.setAttribute('style','overflow:visible');s.setAttribute('width',"
               "'200');s.setAttribute('height','200');s.appendChild(p);w.appendChild(s);document.body.appendChild(w);"
               "var b=w.getBoundingClientRect(),r=p.getBoundingClientRect();"
               "return {box:[b.left,b.top,b.width,b.height],paint:[r.left,r.top,r.width,r.height]}})()",
    "script": "(function(){var d=document.createElement('script');d.type='application/json';d.style.cssText='display:block;"
              "position:absolute;left:-60px;top:900px;width:40px;height:20px;white-space:nowrap;color:#fff;font-size:40px';"
              "d.textContent='OVERFLOWING-SCRIPT-TEXT';document.body.appendChild(d);" + _RANGE + _BOXES + "})()",
    "shadow-modal": "(function(){" + _SHADOW_HOST + "r.innerHTML='<style>dialog::backdrop{background:rgba(255,0,0,.5)}</style>"
                    "<dialog>m</dialog>';var d=r.querySelector('dialog');d.showModal();return {open:d.open,modal:d.matches(':modal')}})()",
    "shadow-fixed": "(function(){" + _SHADOW_HOST + "r.innerHTML='<div style=\"position:fixed;left:0;top:0;width:100vw;height:100vh;"
                    "background:rgba(0,255,0,.4)\"></div>';var b=r.firstElementChild.getBoundingClientRect();"
                    "return {paint:[b.left,b.top,b.width,b.height]}})()",
}
"""Each returns the evidence `injection_problems` checks: the box outside the viewport and the paint reaching into it
(caption, script, svgclip's witness), the sidebar at x 0, the open modal dialog, the painted overlay or stroke."""

CUT_ANIMATION = {"additive": False, "timeOffset": 0, "beginTime": 0, "from": {"scalar": False}, "repeatCount": 0,
                 "fillMode": "both", "duration": 0.001, "autoreverses": False, "property": "hidden", "to": {"scalar": True},
                 "removedOnCompletion": False}
FOREGROUND_TEXTURES = ("74EE7166AEA70C8FD2FEDE82CCDC7157", "3652165F1CC62CFCEB8D764941CC3950")
FOREGROUND_RECTS = ((20.0, 4.0, 80.0, 20.0), (60.0, 8.0, 80.0, 20.0))
FOREGROUND_FRAME = "3231B69B05EF0523B6E951F3B1F2B938"
FOREGROUND_SQUARE = "3F22E494EE111203282E35DDB772C32F"
FOREGROUND_SQUARE_RECT = (120.0, 2.0, 120.0, 30.0)
EDGE_FOREGROUND_RECTS = ((-8.0, 80.0, 80.0, 20.0), (180.0, 100.0, 80.0, 20.0))
EDGE_FOREGROUND_SQUARE_RECT = (300.0, 140.0, 120.0, 30.0)
DSK_COUNTER_MOVIE = (FIXTURES / "p2-binary/html-player/assets/08C861A1-CB39-4832-B189-6DF95B7F3396/assets/"
                     "Untitled.mov-0.0000-46.0333.mov")
DSK_COUNTER_SHA256 = "947f8944ba743878133bd0749d3a154c552e0a3cb4482b67ddbe8c23f2bd7203"
DSK_COUNTER_OFFSETS = {
    "clip-10-1000001.mov-0.0000-20.8000.mov": 0.0,
    "clip-10-1000002.mov-0.0000-50.2000.mov": 5.0,
}
DSK_COUNTER_DELTA_S = 5.0
DSK_COUNTER_TIME_TOLERANCE_S = 0.25
DSK_PLAYER_SRC_ANCHORS = (
    (b'A.setAttribute("src",this.src),this.showControls', 1),
    (b'const Q=C.url.native;return null!=Q', 2),
)
NOOFFSET_X_DISPLACEMENT = -80.0
NOOFFSET_Y_DISPLACEMENT = -80.0


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
    viewport: tuple[int, int] | None = None
    dsf: float = 1.0
    drop: str | None = None
    shift: int = 0
    inject: str | None = None
    decoders: int = 1
    letterbox: int = 0
    grant: str = "driver"
    forgery: str | None = None
    placement_value: str | None = None
    placement_mode: str | None = None
    counter_strip: str = "required"
    reason: str | None = None
    regrant: str | None = None
    min_class_px: int = MIN_CLASS_PX


def viewport_of(arm: Arm) -> tuple[int, int]:
    """The arm's CSS viewport: explicit, else `VIEWPORT` with `letterbox` CSS rows added (1920×1200 / 1920×1201)."""
    return arm.viewport or (VIEWPORT[0], VIEWPORT[1] + arm.letterbox)


def device_shape(arm: Arm) -> tuple[int, int]:
    w, h = viewport_of(arm)
    return round(h * arm.dsf), round(w * arm.dsf)


def stage_of(arm: Arm) -> dict[str, float]:
    """`Cg.adjustStageToFit`: the slide scaled to fit the viewport, centred."""
    w, h = viewport_of(arm)
    s = min(w / SLIDE[0], h / SLIDE[1])
    return {"x": (w - SLIDE[0] * s) / 2, "y": (h - SLIDE[1] * s) / 2, "width": SLIDE[0] * s, "height": SLIDE[1] * s}


_ALL = ("out", "in", "overlap")
_ON_EXPECT = {c: "PASS" for c in ("model", "complement", "no_dip", "curve", "monotone", "handoff", "no_flash")}
_MEDIA = {"deck": "p2bin", "slide": 2, "movies": "counter", "continuity": "auto"}
_TONE = {**_MEDIA, "movies": "tone", "capture": "reference", "holders": 1, "classes": _ALL}
_SNAP = {**_MEDIA, "capture": "reference", "holders": 1, "classes": _ALL}
_SNAP_EXPECT = {"holder_pixels": "PASS", "reference": "PASS", "mask": "PASS"}
_ENGAGE = {**_MEDIA, "capture": "engage", "classes": ("out",)}
_SCOPE = {**_MEDIA, "mode": "rendering", "capture": "media", "classes": ("out", "in"), "grant": "none",
          "expect": {"model": "PASS", "scope": "FAIL"}}
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
    "m-tone": Arm(**_TONE, expect={"tone": "PASS", "mask": "PASS"}, twin="m-tone-twin"),
    "m-tone-twin": Arm(**_TONE, splice="fg-omit"),
    "m-tone-raw": Arm(**{**_MEDIA, "movies": "tone"}, capture="paused", classes=("out",), holders=1,
                      expect={"tone": "FAIL"}),
    "perfect-shift": Arm(**_SNAP, shift=1, expect={"reference": "FAIL"}),
    "m-geo-dpr125": Arm(**_ENGAGE, dsf=1.25, expect={"geometry": "FAIL"}),
    "m-geo-2560": Arm(**_ENGAGE, viewport=(2560, 1440), expect={"geometry": "FAIL"}),
    "m-geo-scale": Arm(**_ENGAGE, overrides=("scale",), expect={"geometry": "FAIL"}),
    "m-geo-base": Arm(**_ENGAGE, overrides=("base",), expect={"geometry": "FAIL"}),
    "m-raw": Arm(**_MEDIA, page="raw", capture="media", classes=("out", "in"), holders=1,
                 expect={"exterior": "PASS", "frozen_frame": "PASS"}),
    "m-raw-end": Arm(**{**_ENGAGE, "slide": 4}, page="raw", holders=1, expect={"exterior": "PASS"}),
    "m-raw-svgclip": Arm(**_ENGAGE, page="raw", holders=1, inject="svgclip", expect={"exterior": "PASS"}),
    **{f"m-raw-{n}": Arm(**_ENGAGE, page="raw", inject=n, expect={"exterior": "FAIL"})
       for n in ("caption", "nav-open", "modal", "svg", "script", "shadow-modal", "shadow-fixed")},
    "m-raw-prod": Arm(**_SCOPE, page="raw"),
    "m-preview-prod": Arm(**_SCOPE, page="preview"),
    "cef-skip": Arm(**{**_SCOPE, "mode": "on"}, reason="attached"),
    "cef-skip-dsk": Arm(**{**_SCOPE, "deck": "dsk", "slide": 7, "movies": "h264", "continuity": "off", "mode": "on", "classes": ("out",)},
                        decoders=2, reason="attached", min_class_px=1000),
    "grant-chrome": Arm(**_ENGAGE, page="screen", grant="host", reason="granted", holders=1, expect={"grant": "PASS"}),
    "grant-attach": Arm(**_ENGAGE, grant="none", reason="attached", expect={"grant": "FAIL"}),
    "channel-predefined": Arm(**{**_ENGAGE, "capture": "channel"}, page="screen", grant="host", reason="channel-compromised",
                              expect={"grant": "FAIL"}),
    "life-grant-reload": Arm(**_ENGAGE, page="screen", holders=1, grant="host", reason="granted", regrant="reload",
                             expect={"grant": "PASS"}),
    "m-bridge-off": Arm("p2", 4, mode="off", movies="player", continuity="auto", capture="media", classes=("out",), bridge=True,
                        styles="none", expect={"overlay": "FAIL"}),
    "m-bridge": Arm("p2", 4, movies="player", continuity="auto", capture="media", classes=("out",), bridge=True,
                    expect={"overlay": "REPORTED"}),
    "on-sw": Arm("p2", 2, movies="player", gpu=False, classes=_ALL, expect=_ON_EXPECT),
}

FORGERIES = {
    f"{value}-{kind}": (value, kind)
    for value in ("snap", "frac")
    for kind in ("assignment", "getter")
}
for _page in ("raw", "preview"):
    for _tag in FORGERIES:
        _base = f"m-{_page}-prod"
        ARMS[f"{_base}-forge-{_tag}"] = replace(ARMS[_base], forgery=_tag)
ARMS["m-raw-prod-forge-snap-getter-kb"] = replace(
    ARMS["m-raw-prod"], mode="on", forgery="snap-getter", holders=1,
    expect={"model": "PASS", "scope": "PASS"},
)

LIFECYCLE: dict[str, dict[str, Any]] = {
    "advance": {},
    "replay": {"replay": True},
    "queued-advance": {"actions": ((0.5, "space"),)},
    "queued-skip": {"actions": ((0.5, "skip"),)},
    "goto": {"actions": ((1.3, "goto1"),)},
    "back": {"actions": ((1.3, "back"),)},
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
            styles="on" if _mode == "on" else "none", row=_row, twin=None if _suffix else f"life-{_row}-twin",
            expect={"hidden": "PASS", "shown": "PASS"} if _suffix and _row.startswith("hide") else {})
for _drop, _check in (("hide", "hidden"), ("show", "shown")):
    ARMS[f"life-hide-no{_drop}"] = replace(ARMS["life-hide"], twin=None, drop=_drop, expect={_check: "FAIL"})
for _dsf, _tag in ((1.5, "dsf15"), (2.0, "dsf2")):
    ARMS[f"m-fg-{_tag}"] = replace(ARMS["m-fg"], dsf=_dsf)
SNAP_DPR = {"": 1.0, "dpr15": 1.5, "dpr2": 2.0}
SNAP_ORIGIN = {"": 0, "lbfrac": 121}
SNAP_CLIP = {"": (), "clipx": ("clipx",), "clipy": ("clipy",)}
SNAPS: list[str] = []
for _d, _dpr in SNAP_DPR.items():
    for _o, _lb in SNAP_ORIGIN.items():
        for _c, _clip in SNAP_CLIP.items():
            _name = "-".join(["m-snap", *(t for t in (_d, _o, _c) if t)])
            _cell = {**_SNAP, "dsf": _dpr, "letterbox": _lb, "overrides": _clip}
            SNAPS.append(_name)
            ARMS[_name] = Arm(**_cell, expect=_SNAP_EXPECT | {"geometry": "PASS"}, twin=f"{_name}-twin")
            ARMS[f"{_name}-twin"] = Arm(**_cell, splice="fg-omit")

ARMS["wrongrule-chrome"] = replace(ARMS["m-snap"], placement_value="frac", placement_mode="probe",
                                           expect={**_SNAP_EXPECT, "holder_pixels": "FAIL"}, twin="wrongrule-chrome-twin")
ARMS["wrongrule-chrome-twin"] = replace(ARMS["m-snap-twin"], placement_value="frac", placement_mode="probe")

_CEF_SNAP_ROWS = {
    "m-snap-cef": replace(ARMS["m-snap"], overrides=("edgefg",)),
    "m-snap-cef-far-x": ARMS["m-snap-clipx"],
    "m-snap-cef-far-y": ARMS["m-snap-clipy"],
    "m-snap-cef-near-x": replace(ARMS["m-snap"], overrides=("clipnearx",)),
    "m-snap-cef-near-y": replace(ARMS["m-snap"], overrides=("clipneary",)),
}
for _name, _arm in _CEF_SNAP_ROWS.items():
    ARMS[_name] = replace(_arm, placement_value="frac", twin=f"{_name}-twin")
    ARMS[f"{_name}-twin"] = replace(_arm, placement_value="frac", splice="fg-omit", expect={}, twin=None)
ARMS["m-paused-cef"] = replace(ARMS["m-paused"], placement_value="frac")
ARMS["m-off-cef"] = replace(ARMS["m-off"], placement_value="frac")
ARMS["m-hold-cef"] = replace(ARMS["m-hold"], placement_value="frac")
ARMS["m-fg-cef"] = replace(ARMS["m-fg"], placement_value="frac",
                            expect={**ARMS["m-fg"].expect, "frozen_region": "PASS"})
ARMS["m-fg-omit-cef"] = replace(ARMS["m-fg-omit"], placement_value="frac")
ARMS["m-fg-swap-cef"] = replace(ARMS["m-fg-swap"], placement_value="frac")
ARMS["m-tone-cef"] = replace(ARMS["m-tone"], placement_value="frac", twin="m-tone-cef-twin")
ARMS["m-tone-cef-twin"] = replace(ARMS["m-tone-twin"], placement_value="frac")
ARMS["m-tone-raw-cef"] = replace(ARMS["m-tone-raw"], placement_value="frac", twin="m-tone-cef-twin")
ARMS["wrongrule-cef"] = replace(ARMS["m-snap-cef"], placement_value="snap", expect={**_SNAP_EXPECT, "holder_pixels": "FAIL"},
                                      twin="wrongrule-cef-twin")
ARMS["wrongrule-cef-twin"] = replace(ARMS["m-snap-cef-twin"], placement_value="snap")
ARMS["m-snap-cef-nooffset-x"] = replace(ARMS["m-snap-cef-near-x"], splice="frac-nooffset-x",
                                              overrides=("nooffsetx",),
                                              counter_strip="displaced-x",
                                              expect={**_SNAP_EXPECT, "holder_pixels": "FAIL"}, twin="m-snap-cef-nooffset-x-twin")
ARMS["m-snap-cef-nooffset-x-twin"] = replace(
    ARMS["m-snap-cef-near-x-twin"], overrides=("nooffsetx",), splice="frac-nooffset-x+fg-omit",
    counter_strip="displaced-x"
)
ARMS["m-snap-cef-nooffset-y"] = replace(ARMS["m-snap-cef-near-y"], splice="frac-nooffset-y",
                                              overrides=("nooffsety",),
                                              counter_strip="displaced-y",
                                              expect={**_SNAP_EXPECT, "holder_pixels": "FAIL"}, twin="m-snap-cef-nooffset-y-twin")
ARMS["m-snap-cef-nooffset-y-twin"] = replace(
    ARMS["m-snap-cef-near-y-twin"], overrides=("nooffsety",), splice="frac-nooffset-y+fg-omit",
    counter_strip="displaced-y"
)
ARMS["m-snap-cef-dsk"] = replace(
    ARMS["cef-skip-dsk"], placement_value="frac", grant="driver", holders=2, movies="dsk-counter",
    overrides=("dskcounter",), counter_strip="distinct",
    expect={"frozen_frame": "PASS", "frozen_region": "PASS", "cost": "PASS", "geometry": "PASS"},
)
ARMS["m-snap-cef-underlay-omit"] = replace(
    ARMS["m-snap-cef"], splice="frac-underlay-omit", capture="engage", holders=0, twin=None,
    expect={"holder_pixels": "FAIL"},
)
ARMS["m-geo-frac-origin-chrome"] = replace(
    ARMS["m-snap-lbfrac"], placement_value="frac", placement_mode="probe", capture="engage", holders=0, twin=None,
    expect={"geometry": "FAIL"},
)
for _tag in ("dpr15", "dpr2"):
    ARMS[f"m-geo-frac-{_tag}"] = replace(
        ARMS[f"m-snap-{_tag}"], placement_value="frac", placement_mode="probe", capture="engage", holders=0, twin=None,
        expect={"geometry": "FAIL"},
    )
DISPLACED = {"frac": ("sn-frac", ("m-snap-dpr15", "m-snap-dpr2")), "shift": ("snap-shift", ("m-snap", "m-snap-dpr15", "m-snap-dpr2"))}
"""Displaced-edge FAIL controls on the 1920x1080 cells: `sn` unrounded at DPR 1.5 and 2 (at DPR 1 the alpha scan rejects
it, no holder) and the holder one device px right at every DPR."""
FAILS: list[str] = []
for _tag, (_splice, _cells) in DISPLACED.items():
    for _base in _cells:
        _name = f"{_base}-{_tag}"
        FAILS.append(_name)
        ARMS[_name] = replace(ARMS[_base], splice=_splice, expect=_SNAP_EXPECT | {"holder_pixels": "FAIL"}, twin=f"{_name}-twin")
        ARMS[f"{_name}-twin"] = replace(ARMS[f"{_base}-twin"], splice=f"{_splice}+fg-omit")
TWINS = frozenset(a.twin for a in ARMS.values() if a.twin)

CONTROLS: dict[str, tuple[tuple[str, ...], ...]] = {
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
    "holder_pixels": (tuple(SNAPS), (*FAILS, "wrongrule-chrome", "case:holder-shift")),
    "reference": ((*SNAPS, *FAILS, "case:reference-valid"), ("perfect-shift",),
                  ("case:reference-stale", "case:reference-extra", "case:reference-unpaused")),
    "mask": ((*SNAPS, *FAILS, "m-tone", "case:mask-production"), (),
             ("case:mask-whole", "case:mask-shift3", "case:mask-empty")),
    "geometry": (tuple(SNAPS), ("m-geo-dpr125", "m-geo-2560", "m-geo-scale", "m-geo-base")),
    "exterior": (("m-raw", "m-raw-end", "m-raw-svgclip"),
                 tuple(f"m-raw-{n}" for n in ("caption", "nav-open", "modal", "svg", "script", "shadow-modal", "shadow-fixed"))),
    "hidden": (("life-hide-twin", "life-hide-screen-twin"), ("life-hide-nohide",), ("case:hide-duplicate", "case:hide-shift")),
    "shown": (("life-hide-twin", "life-hide-screen-twin"), ("life-hide-noshow",)),
    "grant": (("grant-chrome",), ("grant-attach", "channel-predefined")),
    "scope": (("m-raw-prod-forge-snap-getter-kb",),
              tuple(n for n in ARMS if (n in ("m-raw-prod", "m-preview-prod") or "-prod-forge-" in n)
                    and n != "m-raw-prod-forge-snap-getter-kb")),
}
"""Per gated check: (positive controls -> PASS, negative controls -> FAIL[, scorer cases that must be INCONCLUSIVE])."""

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
    var r = {id: X.vids.length, src: String(v.currentSrc || v.src || '').split('/').pop(), rv: [], rvAt: [],
             freezeDraws: [], detach: null, tuple: null, err: null};
    recs.set(v, r); X.vids.push(r); els.push(v);
    function cb(t, md) {
      r.rv.push([md.presentationTime, md.mediaTime, md.presentedFrames, md.expectedDisplayTime]); r.rvAt.push(performance.now());
      if (r.rv.length > 900) { r.rv.splice(0, r.rv.length - 900); r.rvAt.splice(0, r.rvAt.length - 900); }
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
  var nativeDrawImage = CanvasRenderingContext2D.prototype.drawImage;
  CanvasRenderingContext2D.prototype.drawImage = function (source) {
    if (!(source && source.tagName === 'VIDEO')) return nativeDrawImage.apply(this, arguments);
    track(source);
    var r = recs.get(source);
    if (!(X.armed && this.canvas && !this.canvas.isConnected && !this.canvas.id))
      return nativeDrawImage.apply(this, arguments);
    var draw = {startedAt: performance.now(), argumentCount: arguments.length,
                beforeTimestampUs: null, afterTimestampUs: null,
                finishedAt: null, durationMs: null, beforeError: null, afterError: null};
    function timestamp(key) {
      var f = null;
      try { f = new VideoFrame(source); draw[key + 'TimestampUs'] = f.timestamp; }
      catch (e) { draw[key + 'Error'] = String(e); }
      finally { if (f) f.close(); }
    }
    timestamp('before');
    try { return nativeDrawImage.apply(this, arguments); }
    finally {
      timestamp('after');
      draw.finishedAt = performance.now(); draw.durationMs = draw.finishedAt - draw.startedAt;
      r.freezeDraws.push(draw);
    }
  };
  var takeValue, takes = [];
  Object.defineProperty(window, '__obedTakeMs', {configurable: true, get: function () { return takeValue; },
    set: function (v) { takeValue = v; takes.push([performance.now(), typeof v === 'number' && isFinite(v) ? v : null]); }});
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
    var rec = {t: t, hash: location.hash, scene: snap && snap.sceneId};
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
    live: function () { var r = X.raf, k = r.length - 1; return k > 0 && !r[k].eff && r.slice(0, k).some(function (x) { return !!x.eff; }); },
    dump: function () {
      var f = X.first && Object.assign({}, X.first, {png: null, holders: X.first.holders.map(function (h) { return Object.assign({}, h, {png: null}); })});
      return {raf: X.raf, first: f, vids: X.vids, timeOrigin: performance.timeOrigin, takes: takes};
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
    foreground: function (withPng) {
      var G = stage(), out = {}, all = Array.prototype.slice.call(document.getElementsByTagName('*'));
      if (!G) return out;
      els.forEach(function (v) {
        var g = v.isConnected && G.contains(v) && geo(v);
        if (!g) return;
        var R = g.region;
        out[recs.get(v).id] = Array.prototype.filter.call(G.querySelectorAll('canvas'), function (c) {
          var o = c.getBoundingClientRect();
          return (v.compareDocumentPosition(c) & 4) && c.checkVisibility({opacityProperty: true, visibilityProperty: true}) &&
            o.right > R[0] && o.left < R[0] + R[2] && o.bottom > R[1] && o.top < R[1] + R[3];
        }).map(function (c) {
          return {id: c.id, rect: box(c.getBoundingClientRect()), alpha: eff(c, null), order: all.indexOf(c),
                  png: withPng === false ? null : png(c)};
        });
      });
      return out;
    },
    presentation: function () {
      scan();
      var G = stage();
      return els.map(function (v) {
        var r = recs.get(v), q = v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : {}, rv = r.rv[r.rv.length - 1];
        return {hookId:r.id, elementId:v.id || null, src:v.getAttribute('src') || '', currentSrc:v.currentSrc || '',
                currentTime:v.currentTime, paused:v.paused, readyState:v.readyState,
                videoWidth:v.videoWidth, videoHeight:v.videoHeight,
                totalFrames:q.totalVideoFrames == null ? null : q.totalVideoFrames,
                presentedFrames:rv ? rv[2] : null, connected:v.isConnected && (!G || G.contains(v))};
      }).filter(function (v) { return v.connected; });
    },
    ready: function () { return !!X.first; },
    inventory: function () {
      var L = leaves();
      return (document.getAnimations ? document.getAnimations() : []).map(function (a) {
        var t = a.effect && a.effect.target, i = !!(t && L && t.contains(L[0])), o = !!(t && L && t.contains(L[1]));
        return {target: t ? t.id : null, leaf: i === o ? null : (i ? 'in' : 'out'), state: a.playState};
      });
    },
    seek: function (f) {
      var A = document.getAnimations();
      A.forEach(function (a) { a.pause(); });
      A.forEach(function (a) { a.currentTime = f * a.effect.getComputedTiming().duration; });
      return new Promise(function (done) {
        var n = 0;
        (function step() { if (++n < 5) requestAnimationFrame(step); else setTimeout(function () {
          var L = leaves(), G = stage();
          done({anims: document.getAnimations().map(function (a) {
                  var t = a.effect && a.effect.target;
                  return {target: t ? t.id : null, state: a.playState, ct: a.currentTime, dur: a.effect.getComputedTiming().duration};
                }), eff: L ? L.map(function (c) { return eff(c, G); }) : null, dom: !!L});
        }, 150); })();
      });
    },
    holderRect: function () {
      var G = stage(), h = G && Array.prototype.filter.call(G.querySelectorAll('div'), holder)[0], p = devicePixelRatio;
      if (!h) return null;
      var r = h.firstElementChild.getBoundingClientRect();
      return [Math.round(r.left * p), Math.round(r.top * p), Math.round(r.right * p), Math.round(r.bottom * p)];
    },
    perfect: function (url, shift) {
      var G = stage(), h = G && Array.prototype.filter.call(G.querySelectorAll('div'), holder)[0];
      if (!h) return null;
      var c = h.firstElementChild, i = new Image();
      i.src = url;
      return i.decode().then(function () {
        var g = c.getContext('2d');
        g.globalAlpha = 1; g.clearRect(0, 0, c.width, c.height); g.drawImage(i, shift, 0);
        return new Promise(function (done) {
          var n = 0;
          (function step() { if (++n < 5) requestAnimationFrame(step); else setTimeout(function () { done({dom: !!leaves()}); }, 150); })();
        });
      });
    },
    finish: function () { document.getAnimations().forEach(function (a) { try { a.finish(); } catch (e) {} }); },
    delay: function (min, extra) {
      if (X.timers) return false;
      var T = X.timers = {min: min, extra: extra, list: [], set: window.setTimeout, clear: window.clearTimeout};
      window.setTimeout = function (f, ms) {
        var r = Array.prototype.slice.call(arguments, 2);
        if (typeof f !== 'function' || !((+ms || 0) >= min)) return T.set.apply(window, arguments);
        var e = {f: f, r: r, ms: +ms, done: false};
        e.id = T.set.call(window, function () { e.done = true; f.apply(window, r); }, +ms + extra);
        T.list.push(e);
        return e.id;
      };
      window.clearTimeout = function (id) { T.list.forEach(function (e) { if (e.id === id) e.done = true; }); return T.clear.call(window, id); };
      return true;
    },
    release: function () {
      var T = X.timers;
      if (!T) return null;
      window.setTimeout = T.set; window.clearTimeout = T.clear; X.timers = null;
      T.list.forEach(function (e) { if (!e.done) { T.clear.call(window, e.id); e.done = true; try { e.f.apply(window, e.r); } catch (err) {} } });
      return {minMs: T.min, extraMs: T.extra, delayedMs: T.list.map(function (e) { return e.ms; })};
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
      var P = X.pause = {id: r.id, frame: frame, state: 'seeking'}, seeked = false, shown = false;
      var settle = function () { if (X.pause === P) P.state = shown ? 'presented' : 'seeked'; };
      best.pause();
      best.requestVideoFrameCallback(function cb(now, meta) {
        if (Math.round(meta.mediaTime * fps) !== frame) { best.requestVideoFrameCallback(cb); return; }
        shown = true;
        if (seeked) settle();
      });
      best.addEventListener('seeked', function () { seeked = true; settle(); }, {once: true});
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
PLACEMENT_JS = "('__obedPlacement' in window)?String(window.__obedPlacement):null"
POSITIONING_JS = r"""
(function(){
  var s = null, core = null, G = document.getElementById('stage'), videos = [];
  try { s = window.__obedLive.snapshot(); } catch (e) {}
  try { core = window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.snapshot(); } catch (e) {}
  try { videos = window.__obedDx.presentation(); } catch (e) {}
  var canvases = G ? Array.prototype.map.call(G.querySelectorAll('canvas'), function(c) { return c.id || ''; }) : [];
  var holders = G ? Array.prototype.filter.call(G.querySelectorAll('div'), function(d) {
    var c=d.firstElementChild; return !d.id && d.children.length===1 && c && c.tagName==='CANVAS' && !c.id && d.style.overflow==='hidden';
  }).length : null;
  var foreground = null;
  try {
    var raw = window.__obedDx.foreground(false); foreground = {};
    Object.keys(raw || {}).forEach(function(k) { foreground[k] = (raw[k] || []).map(function(c) {
      return {id:c.id, rect:c.rect, alpha:c.alpha, order:c.order};
    }); });
  } catch (e) {}
  return {runtime:s, hash:String(location.hash || ''), videos:videos, continuity:core,
          preservedStage:G ? G.querySelectorAll('video[data-obed-preserved="1"]').length : null,
          canvases:canvases, holders:holders, foreground:foreground, stage:!!G};
})()
"""
PREDEFINE_JS = ("Object.defineProperty(window,'__obedPlacement',{get:function(){return 'snap'},enumerable:false,"
                "configurable:false})")
"""`channel-predefined`: a forged `snap` getter defined before the host's first-run script, which then throws."""
FORGERY_JS = {
    f"{value}-assignment": ("(function(){window.__obedPlacement=%s;var d=Object.getOwnPropertyDescriptor(window,'__obedPlacement');"
                              "return {read:String(window.__obedPlacement),kind:'assignment',configurable:d.configurable,"
                              "enumerable:d.enumerable,writable:d.writable===true}})()") % json.dumps(value)
    for value in ("snap", "frac")
} | {
    f"{value}-getter": ("(function(){Object.defineProperty(window,'__obedPlacement',{get:function(){return %s},enumerable:false,"
                          "configurable:false});var d=Object.getOwnPropertyDescriptor(window,'__obedPlacement');"
                          "return {read:String(window.__obedPlacement),kind:'getter',configurable:d.configurable,"
                          "enumerable:d.enumerable,writable:false}})()") % json.dumps(value)
    for value in ("snap", "frac")
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def placement_file_ref(path: Path, run_dir: Path, *, mtime_ns: int | None = None,
                       saved_by_obs: bool | None = None, retained: bool | None = None) -> dict[str, Any]:
    path, run_dir = path.resolve(), run_dir.resolve()
    try:
        relative = path.relative_to(run_dir)
    except ValueError as exc:
        raise ValueError(f"placement evidence must be below its run directory: {path}") from exc
    if not path.is_file():
        raise ValueError(f"placement evidence file is missing: {path}")
    ref: dict[str, Any] = {"path": relative.as_posix(), "sha256": sha256_file(path)}
    if mtime_ns is not None:
        ref["mtimeNs"] = int(mtime_ns)
    if saved_by_obs is not None:
        ref["savedByObs"] = bool(saved_by_obs)
    if retained is not None:
        ref["retained"] = bool(retained)
    return ref


def _placement_ref_bytes(ref: Any, run_dir: Path, *, collection: bool = False, load: bool = True) -> bytes:
    if not isinstance(ref, dict) or set(("path", "sha256")) - set(ref):
        raise ValueError(f"malformed placement FileRef: {ref!r}")
    relative = Path(ref["path"])
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != ref["path"]:
        raise ValueError(f"placement FileRef is not a normalized relative path: {ref.get('path')!r}")
    path = (run_dir / relative).resolve()
    try:
        path.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"placement FileRef escapes its run directory: {ref['path']!r}") from exc
    retained = ref.get("retained", True)
    if not isinstance(retained, bool):
        raise ValueError(f"malformed placement FileRef retention: {ref!r}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(ref["sha256"])):
        raise ValueError(f"placement FileRef digest mismatch: {ref['path']!r}")
    if path.is_file() and sha256_file(path) != ref["sha256"]:
        raise ValueError(f"placement FileRef digest mismatch: {ref['path']!r}")
    if retained and not path.is_file():
        raise ValueError(f"placement FileRef is missing: {ref['path']!r}")
    if load and not path.is_file():
        raise ValueError(f"placement FileRef was not retained: {ref['path']!r}")
    if collection and (not integer(ref.get("mtimeNs")) or not isinstance(ref.get("savedByObs"), bool)):
        raise ValueError(f"malformed placement CollectionRef: {ref!r}")
    return path.read_bytes() if load else b""


def _placement_capture_name(capture: placement_probe.ProbeCapture, trail: tuple[str, ...]) -> str:
    label = "-".join(re.sub(r"[^a-zA-Z0-9_.-]", "-", part) for part in trail if part) or "capture"
    pose = "none" if capture.pose is None else str(capture.pose)
    return f"{label}-{capture.phase}-{pose}-{capture.sequence}.png"


def serialize_placement_calibration(value: Any, run_dir: Path) -> dict[str, Any]:
    """Strict §11.6 JSON conversion. Probe PNG bytes become digest-bound files; transaction evidence references input."""
    run_dir.mkdir(parents=True, exist_ok=True)
    capture_dir = run_dir / "placement"
    root_input = value.get("input") if isinstance(value, dict) else None

    def convert(item: Any, trail: tuple[str, ...]) -> Any:
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, placement_probe.ProbeCapture):
            capture_dir.mkdir(parents=True, exist_ok=True)
            path = capture_dir / _placement_capture_name(item, trail)
            if path.exists() and path.read_bytes() != item.png:
                raise ValueError(f"two placement captures map to {path.name}")
            path.write_bytes(item.png)
            return {f.name: placement_file_ref(path, run_dir) if f.name == "png" else convert(getattr(item, f.name), (*trail, f.name))
                    for f in fields(item)}
        if is_dataclass(item):
            return {f.name: ({"$ref": "#/placementCalibration/input"}
                              if f.name == "evidence" and getattr(item, f.name) is root_input and root_input is not None
                              else convert(getattr(item, f.name), (*trail, f.name))) for f in fields(item)}
        if isinstance(item, dict):
            if not all(isinstance(k, str) for k in item):
                raise TypeError(f"placement record keys must be strings at {trail!r}")
            return {k: convert(v, (*trail, k)) for k, v in item.items()}
        if isinstance(item, (tuple, list)):
            return [convert(v, (*trail, str(i))) for i, v in enumerate(item)]
        if isinstance(item, bytes):
            raise TypeError(f"raw bytes are allowed only as ProbeCapture.png at {trail!r}")
        if isinstance(item, Path):
            raise TypeError(f"Path is not a placement record value; use a FileRef at {trail!r}")
        if item is None or isinstance(item, (str, int, float, bool)):
            if isinstance(item, float) and not math.isfinite(item):
                raise TypeError(f"non-finite placement record number at {trail!r}")
            return item
        raise TypeError(f"unsupported placement record value {type(item).__name__} at {trail!r}")

    encoded = convert(value, ())
    if not isinstance(encoded, dict):
        raise TypeError("placementCalibration must be a record")
    return encoded


def _probe_identity(value: dict[str, Any]) -> placement_probe.ProbeIdentity:
    return placement_probe.ProbeIdentity(**value)


def _probe_capture(value: dict[str, Any], run_dir: Path) -> placement_probe.ProbeCapture:
    return placement_probe.ProbeCapture(identity=_probe_identity(value["identity"]), sequence=value["sequence"], nonce=value["nonce"],
                                        phase=value["phase"], pose=value["pose"], png=_placement_ref_bytes(value["png"], run_dir),
                                        paint_observed_s=value["paint_observed_s"], capture_started_s=value["capture_started_s"],
                                        capture_finished_s=value["capture_finished_s"])


def placement_classifier_input(value: dict[str, Any], run_dir: Path) -> placement_probe.ClassifierInput:
    return placement_probe.ClassifierInput(
        spec=placement_probe.ProbeSpec(**value["spec"]), assets_sha256=tuple(value["assets_sha256"]),
        identity=_probe_identity(value["identity"]), ready_state=value["ready_state"], video_size=tuple(value["video_size"]),
        color_tuple=tuple(value["color_tuple"]), freshness=tuple(_probe_capture(v, run_dir) for v in value["freshness"]),
        poses=tuple(placement_probe.PoseGeometry(pose=v["pose"], rect=tuple(v["rect"]), content_box=tuple(v["content_box"]),
                                                  box=tuple(v["box"]), snap_dy=v["snap_dy"], frac_dy=v["frac_dy"])
                    for v in value["poses"]),
        captures=tuple(_probe_capture(v, run_dir) for v in value["captures"]),
    )


def placement_probe_result(value: dict[str, Any]) -> placement_probe.ProbeResult:
    return placement_probe.ProbeResult(
        verdict=placement_probe.ProbeVerdict(value["verdict"]),
        tone_map=None if value.get("tone_map") is None else placement_probe.ToneMap(value["tone_map"]),
        grant_eligible=value["grant_eligible"], reason=value["reason"],
        scores=tuple(placement_probe.PoseScore(pose=s["pose"], tone_map=placement_probe.ToneMap(s["tone_map"]),
                                               snap_share=s["snap_share"], frac_share=s["frac_share"],
                                               inner_pixels=s["inner_pixels"]) for s in value["scores"]),
    )


def deserialize_placement_calibration(value: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    """Resolve §11.6 dataclasses and verify every capture/FileRef for Keynote-free rescoring."""
    from obed_edom import managed_obs

    decoded = dict(value)
    input_value = value.get("input")
    evidence = placement_classifier_input(input_value, run_dir) if isinstance(input_value, dict) else None
    decoded["input"] = evidence
    if isinstance(value.get("classification"), dict):
        decoded["classification"] = placement_probe_result(value["classification"])
    if isinstance(value.get("engine"), dict):
        decoded["engine"] = managed_obs.EngineIdentity(**value["engine"])

    def request(item: Any) -> Any:
        if not isinstance(item, dict):
            return None
        return managed_obs.CalibrationRequest(spec=placement_probe.ProbeSpec(**item["spec"]), url=item["url"],
                                              engine=managed_obs.EngineIdentity(**item["engine"]),
                                              program_target_id=item["program_target_id"],
                                              program_context_id=item["program_context_id"],
                                              connection_generation=item["connection_generation"],
                                              placement=item.get("placement", "preview"))

    decoded["request"] = request(value.get("request"))
    tx = value.get("transaction")
    if isinstance(tx, dict):
        program = managed_obs.ProgramCheck(**{**tx["program"], "media": tuple(tx["program"]["media"])}) if isinstance(tx.get("program"), dict) else None
        persistence = managed_obs.PersistenceCheck(**{**tx["persistence"], "differences": tuple(tx["persistence"]["differences"]),
                                                       "allowed": tuple(tx["persistence"]["allowed"])}) if isinstance(tx.get("persistence"), dict) else None
        tx_evidence = evidence if tx.get("evidence") == {"$ref": "#/placementCalibration/input"} else None
        decoded["transaction"] = managed_obs.CalibrationResult(
            request=request(tx.get("request")), evidence=tx_evidence, program=program,
            isolation_ok=tx["isolation_ok"], cleanup_verified=tx["cleanup_verified"], restored=tx["restored"],
            persistence=persistence, errors=tuple(tx["errors"]), started_s=tx["started_s"], finished_s=tx["finished_s"])
    return decoded


def placement_schema_problems(value: Any, run_dir: Path) -> list[str]:
    required = {"schemaVersion", "backend", "placement", "obsVersion", "engine", "request", "assets", "player", "input",
                "classification", "transaction", "events", "persistence", "integrity", "gates"}
    if not isinstance(value, dict):
        return ["placementCalibration is not a record"]
    problems = [f"placementCalibration missing {name}" for name in sorted(required - set(value))]
    problems += [f"placementCalibration has unsupported {name}" for name in sorted(set(value) - required)]
    if value.get("schemaVersion") != PLACEMENT_SCHEMA_VERSION:
        problems.append(f"schemaVersion {value.get('schemaVersion')!r} != {PLACEMENT_SCHEMA_VERSION}")
    if value.get("backend") not in PLACEMENT_BACKENDS:
        problems.append(f"backend {value.get('backend')!r} is not one of {PLACEMENT_BACKENDS}")
    asset_fields = {"manifestSha256", "patternSha256", "motionSha256"}
    player_fields = {"stockSha256", "liveSha256", "renderingSha256"}
    assets = value.get("assets") if isinstance(value.get("assets"), dict) else {}
    player = value.get("player") if isinstance(value.get("player"), dict) else {}
    if set(assets) != asset_fields:
        problems.append(f"assets fields {sorted(assets)} != {sorted(asset_fields)}")
    if set(player) != player_fields:
        problems.append(f"player fields {sorted(player)} != {sorted(player_fields)}")
    for name, digest in [*(assets.items()), *(player.items())]:
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            problems.append(f"{name} is not a full sha256")
    try:
        decoded = deserialize_placement_calibration(value, run_dir)
        transaction_value = value.get("transaction")
        if transaction_value is not None:
            if not isinstance(transaction_value, dict):
                problems.append("transaction is not a record")
            elif ((value.get("input") is None and transaction_value.get("evidence") is not None)
                  or (value.get("input") is not None
                      and transaction_value.get("evidence") != {"$ref": "#/placementCalibration/input"})):
                problems.append("transaction evidence does not match placementCalibration.input")
        if decoded.get("transaction") is not None and decoded["transaction"].evidence is not decoded.get("input"):
            problems.append("transaction evidence does not resolve to placementCalibration.input")
        persistence = value.get("persistence")
        if isinstance(persistence, dict):
            persistence_fields = {"baseline", "nullBefore", "nullAfter", "cleanup", "quit", "backup",
                                  "lastRemovalMtimeNs", "checks"}
            if set(persistence) != persistence_fields:
                problems.append(f"persistence fields {sorted(persistence)} != {sorted(persistence_fields)}")
            if not integer(persistence.get("lastRemovalMtimeNs")):
                problems.append("persistence lastRemovalMtimeNs is not an integer")
            for name in ("baseline", "nullBefore", "nullAfter", "cleanup", "quit"):
                if persistence.get(name) is not None:
                    _placement_ref_bytes(persistence[name], run_dir, collection=True)
            for ref in persistence.get("backup") or []:
                _placement_ref_bytes(ref, run_dir)
        integrity = value.get("integrity") if isinstance(value.get("integrity"), dict) else {}
        if set(integrity) != {"recording", "rgba", "telemetry"}:
            problems.append("integrity fields are not recording/rgba/telemetry")
        if integrity.get("recording") is not None:
            _placement_ref_bytes(integrity["recording"], run_dir, load=False)
        for ref in integrity.get("rgba") or []:
            _placement_ref_bytes(ref, run_dir)
        if integrity.get("telemetry") is not None:
            _placement_ref_bytes(integrity["telemetry"], run_dir)
        events = value.get("events")
        if not isinstance(events, list) or any(not isinstance(event, dict) or set(event) != {"at", "event", "placement"}
                                              or not number(event["at"]) or not isinstance(event["event"], str)
                                              or not isinstance(event["placement"], dict) for event in events):
            problems.append("events are malformed")
        gates = value.get("gates")
        if not isinstance(gates, dict) or any(not isinstance(gate, dict)
                                              or set(gate) != {"verdict", "problems", "detail"}
                                              or gate["verdict"] not in ("PASS", "FAIL", "INCONCLUSIVE", "REPORTED")
                                              or not isinstance(gate["problems"], list) or not isinstance(gate["detail"], dict)
                                              for gate in gates.values()):
            problems.append("gates are malformed")
    except (KeyError, TypeError, ValueError) as exc:
        problems.append(f"placementCalibration malformed: {type(exc).__name__}: {exc}")
    return problems


def counted_splice(player: bytes, before: bytes, after: bytes, count: int) -> bytes:
    found = player.count(before)
    if found != count:
        raise ValueError(f"splice anchor {before[:40]!r} found {found} times, expected {count}")
    return player.replace(before, after)


def apply_splices(player: bytes, splice: str | None) -> bytes:
    """The arm's counted splices (`+`-joined `SPLICES` names), in order."""
    for name in splice.split("+") if splice else ():
        player = counted_splice(player, *SPLICES[name])
    return player


def served_player(stock: bytes, mode: str, splice: str | None = None) -> bytes:
    """`patch_player` for `on`/`off`; `rendering` = the production preview/raw bytes (`patch_rendering`, no hook)."""
    patched = live_runtime.patch_rendering(stock) if mode == "rendering" else live_runtime.patch_player(stock, mm_opacity=mode == "on")
    return apply_splices(patched, splice)


PIN_INDEX = {"on": 0, "off": 1, "rendering": 2}


@contextlib.contextmanager
def serving(splice: str | None) -> Iterator[None]:
    """`LiveOutputHost` serves `patch_player` output plus the arm's counted splices (if any) while this is active."""
    from obed_edom import live_host

    if splice is None:
        yield
        return
    real = live_host.patch_player

    def spliced(player: bytes, *, mm_opacity: bool = True) -> bytes:
        return apply_splices(real(player, mm_opacity=mm_opacity), splice)

    live_host.patch_player = spliced
    try:
        yield
    finally:
        live_host.patch_player = real


def hooked_transport(base: type | None = None, *, before: str | None = None) -> type:
    """A `ChromeCdp` (or `base`) subclass that installs `HOOK_JS` as the innermost new-document script; `before` is
    installed ahead of every script the host adds after `start` (`channel-predefined`)."""
    if base is None:
        from obed_edom.live_host import ChromeCdp as base

    class HookedCdp(base):
        def start(self) -> None:
            super().start()
            for source in (before, HOOK_JS) if before else (HOOK_JS,):
                self.call("Page.addScriptToEvaluateOnNewDocument", source=source)

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


def _preparation_key(kind: str, inputs: dict[str, Any]) -> str:
    payload = {"version": PREPARATION_CACHE_VERSION, "kind": kind, "inputs": inputs}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _immutable(path: Path) -> None:
    path.chmod(0o444)


def _atomic_file(dest: Path, write: Callable[[Path], Any]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{secrets.token_hex(8)}.tmp")
    try:
        write(tmp)
        _immutable(tmp)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def _atomic_tree(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{secrets.token_hex(8)}.tmp")
    try:
        shutil.copytree(source, tmp)
        for path in (p for p in tmp.rglob("*") if p.is_file()):
            _immutable(path)
        if dest.exists():
            shutil.rmtree(dest)
        os.replace(tmp, dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _valid_cached_entry(entry: Path, key: str) -> tuple[Path, dict[str, Any]] | None:
    try:
        manifest = json.loads((entry / "manifest.json").read_text())
        tree = entry / "tree"
        outputs = manifest.get("outputs")
        if manifest.get("key") != key or not isinstance(outputs, list) or not outputs:
            return None
        for output in outputs:
            relative = Path(output["path"])
            if relative.is_absolute() or any(part in ("", ".", "..") for part in relative.parts):
                return None
            path = tree / relative
            if not path.is_file() or sha256_file(path) != output["sha256"]:
                return None
        info = manifest.get("info")
        asset = next((output for output in outputs if output["path"] == "asset"), None)
        if not isinstance(info, dict) or asset is not None and info.get("sha256") != asset["sha256"]:
            return None
        return tree, info
    except (KeyError, OSError, ValueError, TypeError):
        return None


def _cached_preparation_file(kind: str, inputs: dict[str, Any], dest: Path,
                             build: Callable[[Path], dict[str, Any]], *, directory: bool = False) -> dict[str, Any]:
    assert _PREPARATION_CACHE is not None
    key = _preparation_key(kind, inputs)
    parent = _PREPARATION_CACHE / kind
    entry = parent / key
    cached = _valid_cached_entry(entry, key)
    if cached is None:
        if entry.exists():
            shutil.rmtree(entry)
        parent.mkdir(parents=True, exist_ok=True)
        temp: Path | None = Path(tempfile.mkdtemp(prefix=f".{key}-", dir=parent))
        try:
            tree = temp / "tree"
            tree.mkdir()
            info = {k: v for k, v in build(tree).items() if k != "path"}
            outputs = [{"path": path.relative_to(tree).as_posix(), "sha256": sha256_file(path)}
                       for path in sorted(tree.rglob("*")) if path.is_file()]
            asset = next((output for output in outputs if output["path"] == "asset"), None)
            if not directory and asset is None:
                raise RuntimeError(f"preparation cache build produced no asset for {kind}")
            if asset is not None:
                info["sha256"] = asset["sha256"]
            manifest = {"version": PREPARATION_CACHE_VERSION, "key": key, "inputs": inputs,
                        "outputs": outputs, "info": info}
            (temp / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
            for path in (p for p in tree.rglob("*") if p.is_file()):
                _immutable(path)
            _immutable(temp / "manifest.json")
            try:
                os.replace(temp, entry)
            except OSError:
                cached = _valid_cached_entry(entry, key)
                if cached is None:
                    raise
            else:
                temp = None
                cached = _valid_cached_entry(entry, key)
        finally:
            if temp is not None:
                shutil.rmtree(temp, ignore_errors=True)
    if cached is None:
        raise RuntimeError(f"preparation cache fill failed for {kind} {key}")
    tree, info = cached
    if directory:
        _atomic_tree(tree, dest)
        return info
    _atomic_file(dest, lambda path: shutil.copyfile(tree / "asset", path))
    result = {**info, "path": str(dest)}
    _atomic_file(dest.with_suffix(".json"), lambda path: path.write_text(json.dumps(result, sort_keys=True)))
    return result


def _toolchain_inputs() -> dict[str, Any]:
    import imageio_ffmpeg

    global _TOOLCHAIN_INPUTS
    if _TOOLCHAIN_INPUTS is None:
        _TOOLCHAIN_INPUTS = {"ffmpegSha256": sha256_file(Path(imageio_ffmpeg.get_ffmpeg_exe())),
                             "pillowVersion": Image.__version__, "numpyVersion": np.__version__}
    return dict(_TOOLCHAIN_INPUTS)


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
    if _PREPARATION_CACHE is not None:
        layout = binary.layout() if kind == "counter" else tone_layout()
        inputs = {"kind": kind, "encoding": encoding, "encodingArgs": ENCODINGS[encoding],
                  "dimensions": [binary.WIDTH, binary.HEIGHT], "mediaFps": FPS,
                  "frameCount": n, "durationS": seconds, "layout": layout,
                  "generatorSha256": sha256_file(Path(binary.__file__)),
                  "driverSha256": sha256_file(Path(__file__)), **_toolchain_inputs()}

        def build(tree: Path) -> dict[str, Any]:
            info = encode_movie(tree / "asset", counter_frames(n) if kind == "counter" else tone_frames(n), encoding=encoding)
            info.update(kind=kind, seconds=seconds, layout=layout)
            return info

        return _cached_preparation_file("generated-movies", inputs, dest, build)
    info = encode_movie(dest, counter_frames(n) if kind == "counter" else tone_frames(n), encoding=encoding)
    info.update(kind=kind, seconds=seconds, layout=binary.layout() if kind == "counter" else tone_layout())
    meta.write_text(json.dumps(info))
    return info


def h264_copy(scratch: Path, source: Path) -> dict[str, Any] | None:
    """A ProRes movie (undecodable in Chrome) re-encoded with `ENCODINGS[DEFAULT_ENCODING]`; None for any other codec."""
    import imageio_ffmpeg

    probe = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(source)], capture_output=True, text=True)
    if "Video: prores" not in probe.stderr:
        return None
    digest = binary.sha256_file(source)
    dest = scratch / "movies" / f"h264-{digest[:16]}.mov"
    meta = dest.with_suffix(".json")
    if dest.is_file() and meta.is_file():
        return json.loads(meta.read_text())
    if _PREPARATION_CACHE is not None:
        inputs = {"sourceSha256": digest, "encoding": DEFAULT_ENCODING,
                  "encodingArgs": ENCODINGS[DEFAULT_ENCODING], **_toolchain_inputs()}

        def build(tree: Path) -> dict[str, Any]:
            path = tree / "asset"
            tmp = path.with_suffix(".tmp.mp4")
            cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(source),
                   *ENCODINGS[DEFAULT_ENCODING], "-an", "-movflags", "+faststart", str(tmp)]
            done = subprocess.run(cmd, capture_output=True, text=True)
            if done.returncode != 0 or not tmp.is_file():
                raise RuntimeError(f"ffmpeg transcode failed: {done.stderr[-800:]}")
            tmp.replace(path)
            return {"path": str(path), "sha256": binary.sha256_file(path), "encoding": DEFAULT_ENCODING,
                    "source": digest, "kind": "h264"}

        return _cached_preparation_file("transcodes", inputs, dest, build)
    tmp = dest.with_suffix(".tmp.mp4")
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(source), *ENCODINGS[DEFAULT_ENCODING], "-an",
           "-movflags", "+faststart", str(tmp)]
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0 or not tmp.is_file():
        raise RuntimeError(f"ffmpeg transcode failed: {done.stderr[-800:]}")
    tmp.replace(dest)
    info = {"path": str(dest), "sha256": binary.sha256_file(dest), "encoding": DEFAULT_ENCODING, "source": digest, "kind": "h264"}
    meta.write_text(json.dumps(info))
    return info


def scratch_strip(scratch: Path, deck: str) -> tuple[Path, dict[str, Any]]:
    from obed_edom.html_alpha_probe import strip_export_pdf_bg_fills

    root = scratch / f"strip-{deck}"
    report = root / "strip.json"
    source = DECKS[deck].unmodified
    if not source.is_dir():
        raise RuntimeError(f"fixture missing: {source}")
    if report.is_file():
        return root, json.loads(report.read_text())
    if _PREPARATION_CACHE is not None:
        import obed_edom.html_alpha_probe as alpha_probe

        paths = sorted(p for p in source.rglob("*") if p.suffix.lower() in (".pdf", ".pdfp") and p.is_file())
        inputs = {"sources": [{"path": p.relative_to(source).as_posix(), "sha256": sha256_file(p)} for p in paths],
                  "transformSha256": sha256_file(Path(alpha_probe.__file__))}

        def build(tree: Path) -> dict[str, Any]:
            for path in paths:
                dest = tree / path.relative_to(source)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
            raw = strip_export_pdf_bg_fills(tree)
            summary = {"pdfCount": raw["pdfCount"],
                       "rewritten": [{"pdf": r["pdf"], "pages": r["strippedPages"], "sha256": r["sha256"]}
                                     for r in raw["rewritten"]]}
            if not summary["rewritten"]:
                raise RuntimeError(f"strip of {deck} removed no background fill")
            (tree / "strip.json").write_text(json.dumps(summary))
            return summary

        summary = _cached_preparation_file("stripped-assets", inputs, root, build, directory=True)
        return root, summary
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
    """The outgoing slide's (1-based) dissolve/cut: global scene, texture ids (incoming, outgoing), kind, timing, hashes.
    The hash is the player's `updateWindowHistory`: the scene index, +1 at IdleAtFinalState; after the last scene the
    show holds there, so a terminal transition settles on `#<scene count>`."""
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
            "hashBefore": f"#{scene - 1 if flat[scene].get('automaticPlay') else scene}",
            "hashAfter": f"#{len(flat) if nxt is None else nxt}", "sceneCount": len(flat),
            "automaticScenes": [i for i, e in enumerate(flat) if e.get("automaticPlay")]}


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


def _edge_foreground(doc: dict[str, Any], event: int) -> None:
    _foreground(doc, event)
    builds = list(_effects(doc["events"]))
    video = [(n, p) for n, p in _layers(builds[0]["baseLayer"]) if n.get("isVideoLayer")]
    if len(video) != 1 or video[0][1] is None:
        raise ValueError("expected one video layer inside the renderMovie build")
    parent = video[0][1]
    parent["layers"] = [child for child in parent["layers"] if child.get("texture") != FOREGROUND_FRAME]
    textures = {child.get("texture"): child for child in parent["layers"] if child.get("texture") in FOREGROUND_TEXTURES}
    branches = [child for child in parent["layers"]
                if any(grandchild.get("texture") == FOREGROUND_SQUARE for grandchild in child.get("layers") or [])]
    if set(textures) != set(FOREGROUND_TEXTURES) or len(branches) != 1:
        raise ValueError("expected the inset foreground layers")
    for texture, rect in zip(FOREGROUND_TEXTURES, EDGE_FOREGROUND_RECTS):
        x, y, w, h = rect
        textures[texture]["initialState"].update(position={"pointX": x + w / 2, "pointY": y + h / 2}, width=w, height=h)
    x, y, w, h = EDGE_FOREGROUND_SQUARE_RECT
    branch = branches[0]
    branch["initialState"].update(position={"pointX": x + w / 2, "pointY": y + h / 2}, width=w, height=h)
    for child in branch["layers"]:
        child["initialState"].update(position={"pointX": w / 2, "pointY": h / 2}, width=w, height=h)


def _video_layer(doc: dict[str, Any]) -> dict[str, Any]:
    builds = list(_effects(doc["events"]))
    video = [n for b in builds for n, _ in _layers(b["baseLayer"]) if n.get("isVideoLayer")]
    if len(video) != 1:
        raise ValueError(f"expected one video layer in the slide's renderMovie builds, found {len(video)}")
    return video[0]


def _clip(axis: str) -> Callable[[dict[str, Any], int], None]:
    """The movie's parent layer clips (`masksToBounds`) with its far edge moved to 60 % into the movie + 0.37 px on
    `axis`, its near edge kept: a rectangular clip at a fractional position (§9.0 item 5)."""
    def edit(doc: dict[str, Any], event: int) -> None:
        builds = list(_effects(doc["events"]))
        hits = [(n, p) for b in builds for n, p in _layers(b["baseLayer"]) if n.get("isVideoLayer")]
        if len(hits) != 1 or hits[0][1] is None:
            raise ValueError("expected one video layer with a parent in the slide's renderMovie builds")
        video, parent = (h["initialState"] for h in hits[0])
        size, coord = ("width", "pointX") if axis == "x" else ("height", "pointY")
        near = video["position"][coord] - video["anchorPoint"][coord] * video[size]
        left = parent["position"][coord] - parent["anchorPoint"][coord] * parent[size]
        parent[size] = near + 0.6 * video[size] + 0.37
        parent["position"] = {**parent["position"], coord: left + parent["anchorPoint"][coord] * parent[size]}
        parent["masksToBounds"] = True
    return edit


def _clip_near(axis: str) -> Callable[[dict[str, Any], int], None]:
    def edit(doc: dict[str, Any], event: int) -> None:
        builds = list(_effects(doc["events"]))
        hits = [(n, p) for b in builds for n, p in _layers(b["baseLayer"]) if n.get("isVideoLayer")]
        if len(hits) != 1 or hits[0][1] is None:
            raise ValueError("expected one video layer with a parent in the slide's renderMovie builds")
        video_node, parent_node = hits[0]
        video, parent = video_node["initialState"], parent_node["initialState"]
        origin = parent.get("boundsOrigin")
        if origin is None and isinstance(parent.get("bounds"), dict):
            origin = parent["bounds"].get("origin")
        origin_values = ([origin.get("pointX"), origin.get("pointY")] if isinstance(origin, dict)
                         else list(origin) if isinstance(origin, (list, tuple)) else [0.0, 0.0] if origin is None else [origin])
        identity4 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        if (len(origin_values) != 2 or not all(number(value) and value == 0 for value in origin_values)
                or parent.get("affineTransform") != [1, 0, 0, 1, 0, 0]
                or parent.get("sublayerTransform") != identity4
                or parent.get("rotation") != 0 or parent.get("scale") != 1):
            raise ValueError("near clipping requires a zero bounds origin and an untransformed parent")
        size, coord = ("width", "pointX") if axis == "x" else ("height", "pointY")
        content_near = video["position"][coord] - video["anchorPoint"][coord] * video[size]
        clip_near = content_near + 0.4 * video[size] + 0.37
        parent_far = parent["position"][coord] + (1 - parent["anchorPoint"][coord]) * parent[size]
        parent[size] -= clip_near
        parent["position"] = {**parent["position"], coord: parent_far - (1 - parent["anchorPoint"][coord]) * parent[size]}
        for child in parent_node["layers"]:
            state = child["initialState"]
            state["position"] = {**state["position"], coord: state["position"][coord] - clip_near}
        parent["masksToBounds"] = True
    return edit


def _dsk_counter(doc: dict[str, Any], event: int) -> None:
    builds = list(_effects(doc["events"]))
    by_asset = {build.get("movie", {}).get("asset"): build for build in builds}
    expected = {Path(name).stem for name in DSK_COUNTER_OFFSETS}
    if set(by_asset) != expected:
        raise ValueError(f"expected the two DSK movie assets, found {sorted(by_asset)}")
    for filename, offset in DSK_COUNTER_OFFSETS.items():
        asset = (doc.get("assets") or {}).get(Path(filename).stem)
        urls = asset.get("url") if isinstance(asset, dict) else None
        expected_url = f"assets/{filename}"
        if not isinstance(urls, dict) or urls.get("native") != expected_url:
            raise ValueError(f"expected native DSK movie URL {expected_url!r}")
        if offset:
            urls["native"] = f"{expected_url}#t={offset:g}"
            if urls.get("web") == expected_url:
                urls["web"] = urls["native"]


def _nooffset(doc: dict[str, Any], event: int, axis: str, displacement: float) -> None:
    _clip_near(axis)(doc, event)
    hits = [(n, p) for b in _effects(doc["events"]) for n, p in _layers(b["baseLayer"]) if n.get("isVideoLayer")]
    if len(hits) != 1 or hits[0][1] is None:
        raise ValueError("expected one video layer with a parent in the slide's renderMovie builds")
    video, parent = (node["initialState"] for node in hits[0])
    size, coord = ("width", "pointX") if axis == "x" else ("height", "pointY")
    parent_near = parent["position"][coord] - parent["anchorPoint"][coord] * parent[size]
    video_near = parent_near + video["position"][coord] - video["anchorPoint"][coord] * video[size]
    parent["position"] = {**parent["position"], coord: parent["position"][coord] + displacement - video_near}


def _nooffset_x(doc: dict[str, Any], event: int) -> None:
    _nooffset(doc, event, "x", NOOFFSET_X_DISPLACEMENT)


def _nooffset_y(doc: dict[str, Any], event: int) -> None:
    _nooffset(doc, event, "y", NOOFFSET_Y_DISPLACEMENT)


def _scale(doc: dict[str, Any], event: int) -> None:
    _video_layer(doc)["initialState"]["affineTransform"] = [1.5, 0, 0, 1.5, 0, 0]


def _base(doc: dict[str, Any], event: int) -> None:
    for i, e in enumerate(doc["events"]):
        if i != event:
            state = e["baseLayer"]["initialState"]
            state["width"], state["position"] = SLIDE[0] / 2, {**state["position"], "pointX": SLIDE[0] / 4}


SLIDE_OVERRIDES: dict[str, Callable[[dict[str, Any], int], None]] = {"cut": _cut, "automatic": _automatic, "fg": _foreground,
                                                                    "edgefg": _edge_foreground,
                                                                    "dskcounter": _dsk_counter,
                                                                    "nooffsetx": _nooffset_x,
                                                                    "nooffsety": _nooffset_y,
                                                                    "scale": _scale, "base": _base, "clipx": _clip("x"), "clipy": _clip("y"),
                                                                    "clipnearx": _clip_near("x"), "clipneary": _clip_near("y")}
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
    if not unmod.is_dir():
        raise RuntimeError(f"fixture missing: {unmod}")
    strip_root, strip_report = scratch_strip(scratch, arm.deck) if arm.strip else (None, None)
    files: dict[str, Path] = {}
    movies: dict[str, dict[str, Any]] = {}

    def base(rel: str) -> Path:
        if rel in files:
            return files[rel]
        if rel.lower().endswith(MOVIE_SUFFIXES) and arm.movies:
            if arm.movies == "dsk-counter":
                filename = Path(rel).name
                target_prefix = f"assets/{header['slideList'][arm.slide - 1]}/assets/"
                if filename in DSK_COUNTER_OFFSETS and rel.startswith(target_prefix):
                    if not DSK_COUNTER_MOVIE.is_file():
                        raise RuntimeError(f"fixture missing: {DSK_COUNTER_MOVIE}")
                    digest = binary.sha256_file(DSK_COUNTER_MOVIE)
                    if digest != DSK_COUNTER_SHA256:
                        raise ValueError(f"DSK counter movie digest {digest!r} does not match its release pin")
                    fps = dsk_counter_fps()
                    if fps is None:
                        raise ValueError("DSK counter movie frame rate is unavailable")
                    info = {"path": str(DSK_COUNTER_MOVIE), "bytes": DSK_COUNTER_MOVIE.stat().st_size,
                            "sha256": digest, "seconds": binary.SECONDS, "fps": fps,
                            "frames": binary.frame_count(binary.SECONDS, round(fps)),
                            "seekOffsetS": DSK_COUNTER_OFFSETS[filename]}
                else:
                    info = h264_copy(scratch, unmod / rel) if (unmod / rel).is_file() else None
                    if info is None:
                        return unmod / rel
                movies[rel] = info
                files[rel] = Path(info["path"])
                return files[rel]
            if arm.movies == "h264":
                info = h264_copy(scratch, unmod / rel) if (unmod / rel).is_file() else None
                if info is not None:
                    movies[rel] = info
                files[rel] = Path(info["path"]) if info else unmod / rel
                return files[rel]
            if arm.movies != "player" and not fnmatch.fnmatch(Path(rel).name, binary.MOVIE_GLOB):
                return unmod / rel
            if arm.movies == "player" or (arm.movies == "counter" and decision.get("counterEncoding") == "h264-untagged"):
                if deck.player is None:
                    raise FileNotFoundError(rel)
                if not deck.player.is_dir():
                    raise RuntimeError(f"fixture missing: {deck.player}")
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
    stock = (unmod / "assets/player/main.js").read_bytes()
    if arm.movies == "dsk-counter" and any(stock.count(anchor) != count for anchor, count in DSK_PLAYER_SRC_ANCHORS):
        raise ValueError("DSK player does not have the pinned native-URL-to-video-src path")
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
    if arm.movies:
        for path in sorted(unmod.rglob("*")):
            if path.suffix.lower() in MOVIE_SUFFIXES and path.is_file():
                resolver(unmod, str(path.relative_to(unmod)))
    target = find_target(lambda rel: read_doc(resolver(unmod, rel)), arm.slide)
    served = {"mode": arm.mode, "splice": arm.splice, "stockSha256": sha256_bytes(stock),
              "expected": sha256_bytes(served_player(stock, arm.mode, arm.splice))}
    slides = [{"originalOrdinal": i + 1, "playerIndex": i, "exportedUuid": u, "skipped": False}
              for i, u in enumerate(read_doc(resolver(unmod, "assets/header.json"))["slideList"])]
    provenance = {"deck": arm.deck, "unmodified": str(unmod), "player": str(deck.player) if deck.player else None,
                  "strip": strip_report, "overrides": overrides, "movies": arm.movies, "decision": decision}
    return Resolved(unmod, resolver, slides, target, served, provenance, movies)


def ease_in_out(p: float, x1: float = 0.42, y1: float = 0.0, x2: float = 0.58, y2: float = 1.0) -> float:
    if p <= 0 or p >= 1:
        return 0.0 if p <= 0 else 1.0
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
    observed snapshot value s the median live value (all kept in `medians`); one shared table if the channels agree
    within `agree` at every s (else `kind` "fallback", the 3-D case); unobserved s interpolated linearly; L[0] = 0,
    L[255] = 255 pinned; "analytic" (endpoint observations included) when the gamma-1.961 curve is within `analytic_tol` of every observed per-channel median,
    else "table". Empty, non-finite, out-of-range or mismatched samples are "INCONCLUSIVE"."""
    snap, liv = np.asarray(snapshot, dtype=float), np.asarray(live, dtype=float)
    if (snap.ndim != 2 or snap.shape[1:] != (3,) or snap.shape != liv.shape or not len(snap) or not np.isfinite(snap).all()
            or not np.isfinite(liv).all() or (snap != np.rint(snap)).any() or snap.min() < 0 or snap.max() > 255
            or liv.min() < 0 or liv.max() > 255):
        return {"kind": "INCONCLUSIVE", "table": None, "observed": [], "disagree": [], "medians": {},
                "problems": ["empty, non-finite, out-of-range or mismatched (N, 3) samples"]}
    snap = snap.astype(int)
    medians: dict[int, list[float]] = {}
    for s in np.unique(snap):
        medians[int(s)] = [float(np.median(liv[snap[:, c] == s, c])) for c in range(3) if np.any(snap[:, c] == s)]
    disagree = sorted(s for s, per in medians.items() if max(per) - min(per) > agree)
    observed = sorted(medians)
    inner = [s for s in observed if 0 < s < 255]
    if disagree:
        return {"kind": "fallback", "table": None, "observed": observed, "disagree": disagree, "medians": medians}
    xs = [0, *inner, 255]
    ys = [0.0, *(float(np.median(medians[s])) for s in inner), 255.0]
    table = np.clip(np.rint(np.interp(np.arange(256), xs, ys)), 0, 255).astype(np.uint8)
    curve = analytic_lut()
    analytic = bool(inner) and all(abs(m - float(curve[s])) <= analytic_tol for s in observed for m in medians[s])
    return {"kind": "analytic" if analytic else "table", "table": table.tolist(), "observed": observed, "disagree": [],
            "medians": medians}


def premul(img: np.ndarray) -> np.ndarray:
    out = np.array(img, dtype=np.float32, copy=True)
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
    """out-only, in-only and the both-opaque class (α_A = α_B = 255; no colour filter: α does not depend on colour), each
    without the 1 px ring around any partial-α pixel of A or B: antialiased edges are rasteriser-dependent (CEF 127 draws
    an inside AA corner the export texture has at 255 as α 223)."""
    aA, aB = A[..., 3], B[..., 3]
    keep = ~dilate(((aA > 0) & (aA < 255)) | ((aB > 0) & (aB < 255)), 1)
    return {"out": (aA == 255) & (aB == 0) & keep, "in": (aA == 0) & (aB == 255) & keep, "overlap": (aA == 255) & (aB == 255) & keep}


def far_mask(Ap: np.ndarray, Bp: np.ndarray) -> np.ndarray:
    return np.abs(Ap - Bp)[..., :3].sum(axis=2) > OVERLAP_DIFF_MIN


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


def _prepare_fit(A: np.ndarray, B: np.ndarray, keep: np.ndarray,
                 screen: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray, bool, np.ndarray, np.ndarray, float]:
    Ap, Bp = premul(A), premul(B)
    if screen:
        Ap, Bp = Ap[..., :3], Bp[..., :3]
    d = (Bp - Ap)[keep]
    fit = np.abs(d).sum(axis=1) > FIT_DIFF_MIN
    den = float((d[fit] ** 2).sum())
    return Ap, Bp, keep, screen, d, fit, den


def _fit_frame(F: np.ndarray, prepared: tuple[np.ndarray, np.ndarray, np.ndarray, bool, np.ndarray,
                                              np.ndarray, float]) -> tuple[float, float]:
    Ap, Bp, keep, screen, d, fit, den = prepared
    Fp = F[..., :3].astype(np.float32) if screen else premul(F)
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


def number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def class_range(F: np.ndarray, mask: np.ndarray) -> tuple[float, float] | None:
    alpha = F[..., 3][mask]
    return (float(alpha.min()), float(alpha.max())) if alpha.size else None


def complement_error(inside: tuple[float, float], outside: tuple[float, float]) -> float:
    """The worst |alpha_in-only + alpha_out-only - 255| over every in-only/out-only pixel pair."""
    return max(abs(inside[0] + outside[0] - 255), abs(inside[1] + outside[1] - 255))


def score_fade(frames: list[np.ndarray], A: np.ndarray, B: np.ndarray, *, exclude: list[Iterable[float]] = (),
               classes: Iterable[str] = (), cal: Calibration = Calibration(), screen: bool = False,
               min_frames: int = MIN_MID_FRAMES, min_class_px: int = MIN_CLASS_PX) -> dict[str, Any]:
    """Model, complement and no-dip over transition frames (time order); `exclude` = media rects (padded here). The
    complement and overlap-alpha bounds hold for every class pixel of every admitted (fitted transition) frame; the
    model only on mid frames."""
    shape = A.shape[:2]
    problems = []
    if A.shape != B.shape or any(f.shape[:2] != shape for f in frames):
        return {"problems": ["texture and screenshot sizes differ"], "rows": [], "checks": {}}
    masks = texture_classes(A, B)
    keep = ~rect_mask(shape, exclude, MEDIA_PAD_PX)
    sizes = {k: int((masks[k] & keep).sum()) for k in masks}
    problems += [f"class {k}: {sizes[k]} px < {min_class_px}" for k in classes if sizes[k] < min_class_px]
    prepared = _prepare_fit(A, B, keep, screen)
    rows = []
    for F in frames:
        e, res = _fit_frame(F, prepared)
        row: dict[str, Any] = {"e": e, "residual": res}
        if not screen:
            row.update({k: class_range(F, masks[k] & keep) for k in ("out", "in", "overlap")})
        rows.append(row)
    if any(not number(r["e"]) or not number(r["residual"]) for r in rows):
        problems.append("a transition frame has no finite fit")
    mid = [r for r in rows if number(r["e"]) and MID_E[0] < r["e"] < MID_E[1]]
    if len(mid) < min_frames:
        problems.append(f"{len(mid)} mid frames < {min_frames}")
    admitted = [r for r in rows if number(r["e"])]
    checks = {"model": bool(mid) and all(r["residual"] <= cal.tau for r in mid)}
    if not screen and {"in", "out"} <= set(classes) and not any(r["in"] is None or r["out"] is None for r in admitted):
        checks["complement"] = bool(mid) and all(complement_error(r["in"], r["out"]) <= cal.complement for r in admitted)
    if not screen and "overlap" in classes and not any(r["overlap"] is None for r in admitted):
        checks["no_dip"] = bool(mid) and all(r["overlap"][0] >= cal.no_dip for r in admitted)
    return {"problems": problems, "rows": rows, "mid": len(mid), "classPx": sizes, "checks": checks}


def running_anims(rec: dict[str, Any]) -> list[dict[str, Any]]:
    return [a for a in rec.get("anims") or [] if a.get("ct") is not None and a.get("state") in ("running", "finished")]


def score_curve(raf: list[dict[str, Any]], min_frames: int = MIN_MID_FRAMES) -> dict[str, Any]:
    """Every rAF with a running transition animation has exactly two, one per leaf, with finite start, currentTime,
    value and a positive duration; one start time; |in + out - 1| and |in - ease-in-out(ct / T)| within tolerance.
    rAFs where both are still pending (running, ct 0, no start time yet, as `anim_problem` admits) carry no timing and
    are not curve samples, but only before any timed sample and when `pending` confirms their initial values and effective
    opacities."""
    both, problems = [], []
    for r in raf:
        for a in r.get("anims") or []:
            bad = anim_problem(a)
            if bad:
                problems.append(f"rAF at {r.get('t')}: malformed animation record ({bad})")
        anims = running_anims(r)
        if not anims:
            continue
        if sorted(str(a.get("leaf")) for a in anims) != ["in", "out"]:
            problems.append(f"rAF at {r.get('t')}: animations {[a.get('leaf') for a in anims]} (need one per leaf)")
            continue
        if all(a.get("start") is None and a.get("ct") == 0 for a in anims):
            if both or not pending(r):
                problems.append(f"rAF at {r.get('t')}: pending animations after timed samples or off their initial values (eff {r.get('eff')})")
            continue
        if not all(number(a.get(k)) for a in anims for k in ("start", "ct", "dur", "value")) or not all(a["dur"] > 0 for a in anims):
            problems.append(f"rAF at {r.get('t')}: malformed animation record")
            continue
        both.append({a["leaf"]: a for a in anims})
    if len(both) < min_frames:
        problems.append(f"{len(both)} rAFs with both leaf animations < {min_frames}")
    if problems:
        return result(None, problems[:5])
    starts = {a["start"] for f in both for a in f.values()}
    sums = max(abs(f["in"]["value"] + f["out"]["value"] - 1) for f in both)
    devs = max(abs(f["in"]["value"] - ease_in_out(f["in"]["ct"] / f["in"]["dur"])) for f in both)
    return result(len(starts) == 1 and sums <= CURVE_SUM_TOL and devs <= CURVE_EASE_TOL, startTimes=sorted(starts),
                  maxSumErr=sums, maxEaseErr=devs, frames=len(both))


def score_monotone(es: list[float], min_frames: int = MIN_MID_FRAMES) -> dict[str, Any]:
    if len(es) < min_frames or not all(number(e) for e in es):
        return result(None, [f"{len(es)} fitted transition frames (need {min_frames}, all finite)"])
    drops = [b - a for a, b in zip(es, es[1:])]
    return result(min(drops, default=0) >= -MONOTONE_SLACK and es[-1] >= HANDOFF_E_MIN, worstStep=min(drops, default=0), last=es[-1])


def score_handoff(last: np.ndarray | None, first: np.ndarray | None, exclude: list[Iterable[float]] = (),
                  cal: Calibration = Calibration()) -> dict[str, Any]:
    if last is None or first is None:
        return result(None, ["last transition or first live frame not identified"])
    if last.shape != first.shape:
        return result(None, ["hand-off frames differ in size"])
    keep = ~rect_mask(last.shape[:2], exclude, MEDIA_PAD_PX)
    if not keep.any():
        return result(None, ["no hand-off pixel outside the media rects"])
    h = float(np.abs(premul(first) - premul(last))[keep].max())
    return result(h <= cal.tau, H=h)


def leaf_effs(rec: dict[str, Any]) -> list[float] | None:
    eff = rec.get("eff")
    return list(eff) if isinstance(eff, list) and len(eff) == 2 and all(number(v) and 0 <= v <= 1 for v in eff) else None


PENDING_INITIAL = {"in": 0.0, "out": 1.0}


def pending(rec: dict[str, Any]) -> bool:
    """Every transition animation still pending (no start time, currentTime 0), each animated leaf's effective opacity
    and animation value at its declared initial value (incoming 0, outgoing 1)."""
    anims, eff = rec.get("anims"), leaf_effs(rec)
    return bool(anims) and eff is not None and all(
        isinstance(a, dict) and a.get("start") is None and a.get("ct") == 0 and a.get("leaf") in PENDING_INITIAL
        and a.get("value") == PENDING_INITIAL[a["leaf"]] and eff[a["leaf"] == "out"] == PENDING_INITIAL[a["leaf"]]
        for a in anims)


def raf_gaps(records: list[dict[str, Any]]) -> tuple[list[float], list[float]]:
    """(forbidden, pre-start) rAF gaps > `RAF_GAP_MS`. A gap is pre-start (allowed) only when nothing has started by its
    end, the record ending it is `pending` and the record starting it has the same effective opacities: nothing changed
    during the gap, so that record is what was painted throughout it (CEF's first transition frame)."""
    forbidden, pre = [], []
    started = False
    for a, b in zip(records, records[1:]):
        started = started or any(isinstance(x, dict) and x.get("start") is not None for r in (a, b) for x in r.get("anims") or [])
        gap = b["t"] - a["t"]
        if gap > RAF_GAP_MS:
            (pre if not started and pending(b) and leaf_effs(a) is not None and leaf_effs(a) == leaf_effs(b) else forbidden).append(gap)
    return forbidden, pre


def first_animation_t(raf: list[dict[str, Any]]) -> float | None:
    return next((float(r["t"]) for r in raf if any(number(a.get("ct")) and a["ct"] > 0 for a in r.get("anims") or [])), None)


def score_no_flash(raf: list[dict[str, Any]], window_in_alpha: list[float] | None = None,
                   cal: Calibration = Calibration()) -> dict[str, Any]:
    """Incoming effective opacity 0 in every rAF with the transition DOM before the first animation frame (at least one
    such rAF, no gap); delay arms add the in-only alpha (every pixel) of every screenshot inside that window (>= 2)."""
    start = first_animation_t(raf)
    window = [r for r in raf if r.get("eff") is not None and (start is None or r["t"] < start)]
    problems = []
    if start is None:
        problems.append("no animation frame")
    if not window:
        problems.append("no rAF with the transition DOM before the first animation frame")
    elif any(leaf_effs(r) is None for r in window):
        problems.append("malformed leaf opacity in the window")
    elif raf_gaps(window)[0]:
        problems.append("rAF gap in the window")
    if window_in_alpha is not None:
        if len(window_in_alpha) < 2:
            problems.append(f"{len(window_in_alpha)} screenshots in the delay window < 2")
        if not all(number(a) for a in window_in_alpha):
            problems.append("malformed in-only alpha in the delay window")
    if problems:
        return result(None, problems, windowRafs=len(window))
    ok = all(leaf_effs(r)[0] == 0 for r in window) and all(a <= cal.complement for a in window_in_alpha or [])
    return result(ok, windowRafs=len(window), windowAlpha=window_in_alpha)


def score_cut(raf: list[dict[str, Any]], cast: list[dict[str, Any]], cal: Calibration = Calibration()) -> dict[str, Any]:
    """rAFs from DOM insertion: incoming 0 before the cut's first animation frame, then in + out = 1 through the frame
    where incoming reaches 1 (included); every screencast (or CEF source) frame within the complement over every
    in-only/out-only pixel pair, and at least one whose whole capture interval [t0, t1] (a screencast frame has
    t0 = t1) lies inside [DOM insertion, cut completion]; a straddling capture alone is INCONCLUSIVE."""
    dom = [r for r in raf if r.get("eff") is not None]
    if not dom:
        return result(None, ["no rAF with the transition DOM"])
    if any(leaf_effs(r) is None for r in dom):
        return result(None, ["malformed leaf opacity"])
    problems = []
    start = first_animation_t(raf)
    pre = [r for r in dom if start is None or r["t"] < start]
    post = [r for r in dom if start is not None and r["t"] >= start]
    done = next((i for i, r in enumerate(post) if r["eff"][0] >= 1), None)
    after = [r for r in raf if done is not None and r["t"] > post[done]["t"]]
    if start is None or done is None or len(after) < CUT_AFTER_FRAMES:
        problems.append("rAF coverage does not reach 3 frames after the cut")
    if not pre:
        problems.append("no rAF before the cut's first animation frame")
    if raf_gaps(dom)[0]:
        problems.append("rAF gap inside the cut")
    if any(not number(c.get("t0")) or not number(c.get("t1")) or c["t1"] < c["t0"] or c.get("in") is None or c.get("out") is None
           for c in cast):
        problems.append("malformed screencast frame")
    end = post[done]["t"] if done is not None else None
    inside = [c for c in cast if end is not None and number(c.get("t0")) and number(c.get("t1")) and dom[0]["t"] <= c["t0"] and c["t1"] <= end]
    if not inside:
        problems.append("no screencast frame inside [DOM insertion, cut completion]")
    if problems:
        return result(None, problems)
    swap = post[:done + 1]
    worst = max(complement_error(c["in"], c["out"]) for c in cast)
    ok = all(r["eff"][0] == 0 for r in pre) and all(abs(r["eff"][0] + r["eff"][1] - 1) <= CUT_SUM_TOL for r in swap) and worst <= cal.complement
    return result(ok, preRafs=len(pre), swapRafs=len(swap), inside=len(inside), worstCast=worst)


def decode_strip(image: np.ndarray, origin: tuple[float, float] = (0.0, 0.0), scale: float = 1.0) -> int | None:
    return read_strip(np.asarray(image), origin, scale)[0]


def demix(F: np.ndarray, B: np.ndarray, e: float) -> np.ndarray:
    """Ô = (F - e·B) / (1 - e) as unclipped float premultiplied RGBA (residual and constancy checks read this)."""
    return (premul(F) - e * premul(B)) / (1 - e)


def straight(o: np.ndarray) -> np.ndarray:
    """A clipped straight-RGBA uint8 copy of a premultiplied image, for strip decoding only."""
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


def score_frozen(holder_index: int | None, reference: int | None, demixed: list[int | None], *, holder: bool = True) -> dict[str, Any]:
    """The holder (unless `holder` is False: the patch-off arm has none by design) and every Ô decode to the reference."""
    problems = []
    if reference is None:
        problems.append("no reference rVFC record before the detach")
    if holder and holder_index is None:
        problems.append("holder strip does not decode")
    ok = (not holder or holder_index == reference) and all(i == reference for i in demixed)
    return result(ok, problems, holder=holder_index, reference=reference, demixed=demixed)


def _demix_limit(cal: Calibration, e: float) -> float:
    return cal.tau / (1 - e)


def score_region(regions: list[np.ndarray], es: list[float], cal: Calibration = Calibration()) -> dict[str, Any]:
    """Ô (unclipped premultiplied RGBA) over the movie region constant across admitted frames: per frame
    max |Ô - median| <= tau / (1 - e) on every channel, alpha included."""
    if len(regions) < DEMIX_MIN_FRAMES or len(regions) != len(es) or not all(number(e) for e in es):
        return result(None, [f"{len(regions)} demixed frames (need {DEMIX_MIN_FRAMES}, one finite e each)"])
    stack = np.stack([np.asarray(r, np.float32) for r in regions])
    if stack.size == 0 or not np.isfinite(stack).all():
        return result(None, ["empty or non-finite demixed region"])
    med = np.median(stack, axis=0)
    spreads = [float(np.abs(s - med).max()) for s in stack]
    return result(all(s <= _demix_limit(cal, e) for s, e in zip(spreads, es)), spreads=spreads)


def score_foreground(candidates: list[np.ndarray], s_live: np.ndarray, mask: np.ndarray,
                     cal: Calibration = Calibration(), *, demix_es: list[float] | None = None) -> dict[str, Any]:
    if not mask.any():
        return result(None, ["no counter-block pixel under the foreground"])
    es = demix_es or []
    if len(candidates) != len(es) + 1 or not all(number(e) and 0 <= e < 1 for e in es):
        return result(None, ["foreground candidates do not match finite demix progress"])
    worsts = [float(np.abs(c[..., :3].astype(np.float32) - s_live[..., :3])[mask].max()) for c in candidates]
    limits = [cal.tau, *(_demix_limit(cal, e) for e in es)]
    return result(all(worst <= limit for worst, limit in zip(worsts, limits)), worst=max(worsts), worsts=worsts,
                  limits=limits, pixels=int(mask.sum()))


def score_tone(holder: np.ndarray, s_live: np.ndarray, s_live2: np.ndarray, mask: np.ndarray, *, identity: bool) -> dict[str, Any]:
    problems = []
    if not mask.any():
        problems.append("empty tone mask")
    cvc = float(np.abs(s_live[..., :3].astype(np.float32) - s_live2[..., :3])[mask].max()) if mask.any() else None
    if cvc is not None and cvc > TONE_CVC:
        problems.append(f"S_live CvC {cvc} > {TONE_CVC}")
    worst = float(np.abs(holder[..., :3].astype(np.float32) - s_live[..., :3])[mask].max()) if mask.any() else None
    return result(worst is not None and worst <= TONE_TOL, problems, report=identity, worst=worst, cvc=cvc)


def score_cost(publications: list[Any], start: float | None, end: float | None) -> dict[str, Any]:
    """Each `window.__obedTakeMs` publication ([page ms, take ms], in order) of the exercised take, i.e. published inside
    [advance request, first transition rAF], is finite and <= 50 ms; none there (or a malformed one) is INCONCLUSIVE."""
    if not number(start) or not number(end):
        return result(None, ["no advance time or transition rAF to place the take"])
    if any(not isinstance(p, (list, tuple)) or len(p) != 2 or not number(p[0]) for p in publications):
        return result(None, [f"malformed take publication in {publications}"])
    if any(b[0] <= a[0] for a, b in zip(publications, publications[1:])):
        return result(None, ["take publications duplicated or out of order"])
    current = [p[1] for p in publications if start <= p[0] <= end]
    if len(current) != 1 or not number(current[0]) or current[0] < 0:
        return result(None, [f"need exactly one finite take cost published for the exercised take: {current}"])
    return result(max(current) <= COST_MS, takeMs=current)


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
    if movie_rect is None or len(movie_rect) != 4:
        return result(None, ["no outgoing movie rect"])
    fade = [r for r in raf if r.get("eff") is not None]
    if not fade:
        return result(None, ["no rAF of the fade"])
    videos = [v for r in fade for v in r.get("videos") or [] if v.get("on")]
    if any(not number(v.get("eff")) or len(v.get("rect") or []) != 4 or not isinstance(v.get("inT"), bool) for v in videos):
        return result(None, ["malformed video record in the fade"])
    hits = sorted({v["id"] for v in videos if not v["inT"] and v["eff"] > 0 and overlaps(v["rect"], movie_rect)})
    if hits:
        return result(False, overlay=hits)
    if region["verdict"] == "INCONCLUSIVE":
        return result(None, region["problems"])
    return result(region["verdict"] == "PASS", overlay=[], region=region["verdict"])


def jround(z: float) -> int:
    """JavaScript `Math.round` (the take's `sn`)."""
    return math.floor(z + 0.5)


def dilate(mask: np.ndarray, r: int) -> np.ndarray:
    """Square dilation by `r` px, without wrapping at the edges."""
    h, w = mask.shape
    padded = np.pad(mask, r)
    out = np.zeros_like(mask)
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            out |= padded[dy:dy + h, dx:dx + w]
    return out


def device_box(rect: Iterable[float], dsf: float) -> tuple[int, int, int, int] | None:
    """A holder's CSS [x, y, w, h] as device (x0, y0, x1, y1): the origin painted at `jround(x·DPR)` (a fractional
    letterbox origin snaps there, fix A), the size its device size; None unless that size is whole (within 1e-3)."""
    x, y, w, h = rect
    if any(abs(v * dsf - round(v * dsf)) > 1e-3 for v in (w, h)):
        return None
    x0, y0 = jround(x * dsf), jround(y * dsf)
    return x0, y0, x0 + round(w * dsf), y0 + round(h * dsf)


def device_rects(rects: Iterable[Iterable[float]], dsf: float) -> list[list[float]]:
    return [[v * dsf for v in r] for r in rects]


def box_mask(shape: tuple[int, int], box: tuple[int, int, int, int], inset: int = 0) -> np.ndarray:
    mask = np.zeros(shape, bool)
    x0, y0, x1, y1 = box
    mask[max(0, y0 + inset):max(0, y1 - inset), max(0, x0 + inset):max(0, x1 - inset)] = True
    return mask


def paste_holder(image: np.ndarray, holder: dict[str, Any], shape: tuple[int, int], dsf: float) -> np.ndarray | None:
    """The holder backing pasted 1:1 at its device rect (exact on the qualified geometry: the backing is device pixels),
    clipped to the holder; None unless the backing is exactly that device size."""
    canvas, clip = device_box(holder["canvasRect"], dsf), device_box(holder["rect"], dsf)
    if canvas is None or clip is None or image.shape[:2] != (canvas[3] - canvas[1], canvas[2] - canvas[0]):
        return None
    out = np.zeros((*shape, 4), np.uint8)
    x0, y0, x1, y1 = canvas
    ys, xs = slice(max(0, y0), min(shape[0], y1)), slice(max(0, x0), min(shape[1], x1))
    if ys.stop > ys.start and xs.stop > xs.start:
        out[ys, xs] = image[ys.start - y0:ys.stop - y0, xs.start - x0:xs.stop - x0]
    out[~box_mask(shape, clip)] = 0
    return out


def holder_strip(image: np.ndarray, holder: dict[str, Any], decoder: dict[str, Any], dsf: float) -> int | None:
    """The strip read from a device-scale holder: the content box's offset in the canvas, scale `dw / videoWidth`."""
    cx, cy, cw, _ = decoder["content"]
    hx, hy = holder["canvasRect"][:2]
    return decode_strip(image, ((cx - hx) * dsf, (cy - hy) * dsf), cw * dsf / decoder["size"][0])


def holder_strip_geometry(holder: dict[str, Any], decoder: dict[str, Any]) -> str | None:
    canvas, content, size = holder.get("canvasRect"), decoder.get("content"), decoder.get("size")
    if not box_ok(canvas) or not box_ok(content) or not isinstance(size, list) or len(size) != 2 or not all(number(v) for v in size):
        return None
    if canvas[2] <= 0 or canvas[3] <= 0 or size[0] <= 0 or size[1] <= 0:
        return None
    sx, sy, sw, sh = binary.STRIP_RECT
    scale = content[2] / size[0]
    ax0, ay0, aw, ah = content[0] + sx * scale, content[1] + sy * scale, sw * scale, sh * scale
    bx0, by0, bw, bh = canvas
    ax1, ay1, bx1, by1 = ax0 + aw, ay0 + ah, bx0 + bw, by0 + bh
    if ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0:
        return "outside"
    if bx0 <= ax0 and by0 <= ay0 and ax1 <= bx1 and ay1 <= by1:
        return "inside"
    return "partial"


def production_support(record: dict[str, Any], images: Mapping[str, np.ndarray], decoder_id: Any, shape: tuple[int, int],
                       dsf: float, holder: Iterable[float]) -> tuple[np.ndarray, list[str]]:
    """α > 0 support of every inventoried later canvas (independent of the take) at its device rect, snapped as fix A's
    `sn` does relative to the holder: device edge = holder device origin + jround((z − holder origin)·DPR)."""
    support = np.zeros(shape, bool)
    inventory = (record.get("foreground") or {}).get(str(decoder_id))
    if not isinstance(inventory, list):
        return support, ["no foreground inventory for the bound decoder"]
    problems = []
    for c in inventory:
        img = images.get(c.get("image") or "")
        if img is None or img.ndim != 3 or not img.size:
            problems.append(f"foreground canvas {c.get('id')} has no pixels")
            continue
        x, y, w, h = c["rect"]
        hx, hy = list(holder)[:2]
        ox, oy = jround(hx * dsf), jround(hy * dsf)
        x0, x1 = (ox + jround((v - hx) * dsf) for v in (x, x + w))
        y0, y1 = (oy + jround((v - hy) * dsf) for v in (y, y + h))
        if x1 <= x0 or y1 <= y0 or not c["alpha"] > 0:
            continue
        a = coverage_support(img[..., 3] > 0, (y1 - y0, x1 - x0))
        ys, xs = slice(max(0, y0), min(shape[0], y1)), slice(max(0, x0), min(shape[1], x1))
        if ys.stop > ys.start and xs.stop > xs.start:
            support[ys, xs] |= a[ys.start - y0:ys.stop - y0, xs.start - x0:xs.stop - x0]
    return support, problems


def coverage_support(alpha: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """A canvas's α > 0 support drawn into a `size` (rows, cols) device rect, by exact coverage: a device px is in the
    support iff it overlaps (positive area) a source px with α > 0. No resampling filter, so a non-integer scale (DPR 1.5)
    neither inflates nor drops support."""
    out = alpha
    for axis, n in ((0, size[0]), (1, size[1])):
        src = out.shape[axis]
        step = src / n
        lo = np.floor(np.arange(n) * step + 1e-9).astype(int)
        hi = np.maximum(lo + 1, np.ceil((np.arange(n) + 1) * step - 1e-9).astype(int))
        cum = np.concatenate([np.zeros((1, out.shape[1 - axis]) if axis == 0 else (out.shape[0], 1), int),
                              np.cumsum(out, axis=axis, dtype=int)], axis=axis)
        out = (np.take(cum, hi, axis=axis) - np.take(cum, lo, axis=axis)) > 0
    return out


def twin_difference(record: dict[str, Any], images: Mapping[str, np.ndarray], twin: tuple[dict[str, Any], Mapping[str, np.ndarray]],
                    shape: tuple[int, int], dsf: float) -> tuple[np.ndarray, list[str]]:
    """Pixels where the holder differs from its same-frame `m-fg-omit` twin's holder (exact), at the holder's device rect."""
    dm = np.zeros(shape, bool)
    holders = [((r.get("dump") or {}).get("first") or {}).get("holders") or [] for r in (record, twin[0])]
    pixels = [im.get("holder-0") for im in (images, twin[1])]
    frames = [(r.get("paused") or {}).get("frame") for r in (record, twin[0])]
    if any(len(h) != 1 for h in holders) or any(p is None for p in pixels):
        return dm, ["holder or twin holder missing"]
    if frames[0] != frames[1] or not number(frames[0]):
        return dm, [f"twin paused on frame {frames[1]}, run on {frames[0]}"]
    if any(abs(a - b) > 1e-3 for k in ("rect", "canvasRect") for a, b in zip(holders[0][0][k], holders[1][0][k])):
        return dm, ["twin holder geometry differs"]
    box = device_box(holders[0][0]["canvasRect"], dsf)
    if box is None or pixels[0].shape != pixels[1].shape or pixels[0].shape[:2] != (box[3] - box[1], box[2] - box[0]):
        return dm, ["holder backings are not the same device size"]
    diff = np.abs(pixels[0].astype(int) - pixels[1].astype(int)).max(axis=2) > 0
    x0, y0, x1, y1 = box
    ys, xs = slice(max(0, y0), min(shape[0], y1)), slice(max(0, x0), min(shape[1], x1))
    dm[ys, xs] = diff[ys.start - y0:ys.stop - y0, xs.start - x0:xs.stop - x0]
    return dm, []


def verify_mask(support: np.ndarray, difference: np.ndarray, region: np.ndarray) -> tuple[np.ndarray, list[str], dict[str, Any]]:
    """The production mask (support dilated `MASK_DILATE` px, inside the holder region) checked against the twin
    difference: missed (difference outside the mask) must be 0, excess (mask farther than `MASK_DILATE` px from any
    difference) at most `MASK_EXCESS` of the mask; an empty mask or difference cannot be verified."""
    mask = dilate(support, MASK_DILATE) & region
    dm = difference & region
    missed, excess = int((dm & ~mask).sum()), int((mask & ~dilate(dm, MASK_DILATE)).sum())
    detail = {"maskPx": int(mask.sum()), "diffPx": int(dm.sum()), "missed": missed, "excess": excess}
    problems = []
    if not dm.any():
        problems.append("twin difference empty: the foreground was not exercised")
    if not mask.any():
        problems.append("empty production mask")
    if missed:
        problems.append(f"production mask misses {missed} twin-difference px")
    if mask.any() and excess > MASK_EXCESS * mask.sum():
        problems.append(f"production mask excess {excess} px > {MASK_EXCESS:.0%} of {int(mask.sum())}")
    return mask, problems, detail


def region_split(diff: np.ndarray, box: tuple[int, int, int, int], keep: np.ndarray) -> dict[str, float | None]:
    """Max of a per-pixel difference over the holder region's interior (inset 1 device px) and edge band, on `keep`."""
    shape = diff.shape
    full, inner = box_mask(shape, box), box_mask(shape, box, 1)
    out: dict[str, float | None] = {}
    for name, m in (("interior", inner & keep), ("edge", full & ~inner & keep)):
        out[name] = float(diff[m].max()) if m.any() else None
    return out


def score_holder_pixels(a0: np.ndarray | None, live: np.ndarray | None, box: tuple[int, int, int, int] | None,
                        mask: np.ndarray | None, lut: np.ndarray | None, cal: Calibration = Calibration()) -> dict[str, Any]:
    """|L_path(A0) − S_live| (premultiplied) over the holder region outside the verified production mask; interior and
    edge band each ≤ τ. `L_path` is the measured map of the arm's compositing path, applied to A0 inside the region."""
    problems = []
    if a0 is None or live is None or a0.shape != live.shape:
        problems.append("A0 or S_live missing or of different sizes")
    if box is None:
        problems.append("holder region not on the device grid")
    if mask is None:
        problems.append("no verified production mask")
    if lut is None or np.shape(lut) != (256,):
        problems.append("no L_path for the arm's compositing path")
    if problems:
        return result(None, problems)
    region = box_mask(a0.shape[:2], box)
    toned = a0.copy()
    toned[..., :3][region] = np.asarray(lut, np.uint8)[a0[..., :3][region]]
    split = region_split(np.abs(premul(toned) - premul(live)).max(axis=2), box, ~mask)
    if None in split.values():
        return result(None, ["no kept interior or edge-band px"], **split)
    return result(max(split.values()) <= cal.tau, **split)


def score_displaced_holder(a0: np.ndarray | None, live: np.ndarray | None, holder: dict[str, Any] | None,
                           decoder: dict[str, Any] | None, stage: dict[str, Any] | None, mask: np.ndarray | None,
                           lut: np.ndarray | None, axis: str, dsf: float,
                           cal: Calibration = Calibration()) -> dict[str, Any]:
    problems = []
    if axis not in ("x", "y"):
        problems.append(f"invalid displacement axis {axis!r}")
    if a0 is None or live is None or a0.shape != live.shape:
        problems.append("A0 or S_live missing or of different sizes")
    if not isinstance(holder, dict) or not box_ok(holder.get("canvasRect")):
        problems.append("holder canvas geometry missing or malformed")
    if not isinstance(decoder, dict) or not box_ok(decoder.get("rect")) or not box_ok(decoder.get("content")):
        problems.append("decoder geometry missing or malformed")
    if not isinstance(stage, dict) or not number(stage.get(axis)):
        problems.append("stage geometry missing or malformed")
    if mask is None:
        problems.append("no verified production mask")
    if lut is None or np.shape(lut) != (256,):
        problems.append("no L_path for the arm's compositing path")
    if problems:
        return result(None, problems)
    index = 0 if axis == "x" else 1
    displacement_css = decoder["rect"][index] - stage[axis]
    displacement_px = displacement_css * dsf
    if abs(displacement_px) < 1:
        return result(None, [f"predicted {axis} displacement is less than one device pixel"],
                      displacementCss=displacement_css, displacementPx=displacement_px)
    canvas = holder["canvasRect"]
    shifted = list(decoder["content"])
    shifted[index] -= displacement_css
    target_canvas = list(canvas)
    target_canvas[index] -= displacement_css
    x0, y0 = max(canvas[0], shifted[0], target_canvas[0]), max(canvas[1], shifted[1], target_canvas[1])
    x1 = min(canvas[0] + canvas[2], shifted[0] + shifted[2], target_canvas[0] + target_canvas[2])
    y1 = min(canvas[1] + canvas[3], shifted[1] + shifted[3], target_canvas[1] + target_canvas[3])
    if x1 <= x0 or y1 <= y0:
        return result(None, ["predicted displaced content overlap is empty"],
                      displacementCss=displacement_css, displacementPx=displacement_px)
    px0, py0, px1, py1 = math.ceil(x0 * dsf), math.ceil(y0 * dsf), math.floor(x1 * dsf), math.floor(y1 * dsf)
    lo, hi = math.floor(displacement_px), math.ceil(displacement_px)
    shifts = ((lo, 0), (hi, 0)) if axis == "x" else ((0, lo), (0, hi))
    px0 = max(0, px0, *(-dx for dx, _ in shifts))
    py0 = max(0, py0, *(-dy for _, dy in shifts))
    px1 = min(a0.shape[1], px1, *(live.shape[1] - dx for dx, _ in shifts))
    py1 = min(a0.shape[0], py1, *(live.shape[0] - dy for _, dy in shifts))
    if px1 <= px0 or py1 <= py0:
        return result(None, ["predicted displaced overlap falls outside the captured images"], displacementCss=displacement_css)
    keep = ~mask[py0:py1, px0:px1]
    for dx, dy in shifts:
        keep &= ~mask[py0 + dy:py1 + dy, px0 + dx:px1 + dx]
    if not keep.any():
        return result(None, ["no unmasked pixels in the predicted displaced overlap"], displacementCss=displacement_css)
    toned = a0.copy()
    toned[py0:py1, px0:px1, :3] = np.asarray(lut, np.uint8)[toned[py0:py1, px0:px1, :3]]
    reference = premul(toned[py0:py1, px0:px1])
    samples = [premul(live[py0 + dy:py1 + dy, px0 + dx:px1 + dx]) for dx, dy in shifts]
    lower, upper = np.minimum(*samples) - cal.tau, np.maximum(*samples) + cal.tau
    outside = np.maximum(np.maximum(lower - reference, reference - upper), 0).max(axis=2)
    worst = float(outside[keep].max())
    return result(worst == 0, displacementCss=displacement_css, displacementPx=displacement_px,
                  sampleOffsetsPx=[lo, hi], overlapPx=int(keep.sum()), worst=worst, attribution="displaced content")


def score_perfect(perfect: np.ndarray | None, live: np.ndarray | None, box: tuple[int, int, int, int] | None,
                  cal: Calibration = Calibration()) -> dict[str, Any]:
    """The `perfect` screenshot (holder canvas = S_live's own device pixels) vs S_live over the holder region: ≤ 1 PASS,
    > τ FAIL (the 1-px `perfect-shift` negative); anything between is INCONCLUSIVE."""
    if perfect is None or live is None or perfect.shape != live.shape or box is None:
        return result(None, ["perfect or S_live missing, or the holder region not on the device grid"])
    split = region_split(np.abs(premul(perfect) - premul(live)).max(axis=2), box, np.ones(live.shape[:2], bool))
    if None in split.values():
        return result(None, ["empty holder interior or edge band"], **split)
    worst = max(split.values())
    if PERFECT_TOL < worst <= cal.tau:
        return result(None, [f"perfect residual {worst} between {PERFECT_TOL} and τ"], **split)
    return result(worst <= PERFECT_TOL, **split)


def reference_problems(record: dict[str, Any], images: Mapping[str, np.ndarray], arm: Arm, ev: Any,
                       cal: Calibration = Calibration()) -> list[str]:
    """Reference-capture profile integrity (§9.1): exact inventory, paused states read back as requested, stable pairs
    under their own ids (`ref-<state>-<0|1>`, the images scoring reads), A0/F50/B pairwise different where both the
    textures and the captured A0 and B differ (>= `MIN_CLASS_PX` px),
    |F50 − (A0 + B)/2| ≤ `REF_MODEL_TOL`, the transition DOM present at every capture, `perfect` stable, drawn with the
    arm's shift onto exactly the holder canvas's device box, all after the advance and in capture order."""
    ref = record.get("reference")
    if not isinstance(ref, dict):
        return ["no reference capture"]
    problems = []
    shape = device_shape(arm)
    timers = ref.get("timers")
    if (not isinstance(timers, dict) or timers.get("minMs") != TIMER_MIN_MS or timers.get("extraMs") != TIMER_EXTRA_MS
            or not timers.get("delayedMs")):
        problems.append(f"player timers not held back through the reference capture: {timers!r}")
    ids = ((record.get("dump") or {}).get("first") or {}).get("layerIds") or []
    inv = ref.get("inventory") if isinstance(ref.get("inventory"), list) else []
    targets = sorted(str(a.get("target")) for a in inv)
    if (len(inv) != 2 or sorted(str(a.get("leaf")) for a in inv) != ["in", "out"] or any(a.get("state") != "running" for a in inv)
            or len(set(targets)) != 2 or not all(re.fullmatch(r"layer\d+-opacity", t) and t in ids for t in targets)):
        problems.append(f"animation inventory is not exactly the two running transition animations: {inv}")
    states = ref.get("states") if isinstance(ref.get("states"), list) else []
    perfect = ref.get("perfect") if isinstance(ref.get("perfect"), dict) else {}
    if [(s.get("label"), s.get("f")) for s in states] != list(REF_STATES):
        return problems + [f"reference states {[s.get('label') for s in states]} != {[n for n, _ in REF_STATES]}"]
    want = {"F50": (0.5, 0.5), "A0": (0.0, 1.0)}
    shots: dict[str, np.ndarray] = {}
    for s in [*states, {**perfect, "label": "perfect"}]:
        label = s["label"]
        names = s.get("shots") or []
        if names != [f"ref-{label}-0", f"ref-{label}-1"]:
            problems.append(f"{label}: capture ids {names} are not its own two")
            continue
        pair = [images.get(n) for n in names]
        if any(p is None or p.shape != (*shape, 4) for p in pair):
            problems.append(f"{label}: two full-device screenshots required")
            continue
        if not np.array_equal(pair[0], pair[1]):
            problems.append(f"{label}: unstable pair")
        if s.get("dom") is not True:
            problems.append(f"{label}: transition DOM absent")
        shots[label] = pair[0]
        if label == "perfect":
            continue
        anims = s.get("anims") if isinstance(s.get("anims"), list) else []
        if sorted(str(a.get("target")) for a in anims) != targets or any(
                a.get("state") != "paused" or not number(a.get("dur")) or a["dur"] <= 0 or not number(a.get("ct"))
                or abs(a["ct"] - s["f"] * a["dur"]) > REF_CT_TOL_MS for a in anims):
            problems.append(f"{label}: animations not exactly the inventory, paused at {s['f']}·T ± {REF_CT_TOL_MS} ms")
        eff = leaf_effs(s)
        if eff is None:
            problems.append(f"{label}: no rendered leaf opacities")
        elif label == "B" and eff[0] < 1 - REF_EFF_TOL:
            problems.append(f"B: incoming opacity {eff[0]} < {1 - REF_EFF_TOL}")
        elif label in want and any(abs(v - w) > REF_EFF_TOL for v, w in zip(eff, want[label])):
            problems.append(f"{label}: leaf opacities {eff} != {want[label]}")
    times = [record.get("advanceAt"), *(s.get("t") for s in [*states, perfect])]
    if not all(number(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        problems.append("reference captures untimed, before the advance or out of order")
    holders = ((record.get("dump") or {}).get("first") or {}).get("holders") or []
    canvas = device_box(holders[0]["canvasRect"], arm.dsf) if holders and quad(holders[0].get("canvasRect")) else None
    rect = perfect.get("rect")
    if (perfect.get("shift") != arm.shift or canvas is None or not quad(rect) or tuple(rect) != canvas
            or not (0 <= canvas[0] < canvas[2] <= shape[1] and 0 <= canvas[1] < canvas[3] <= shape[0])):
        problems.append(f"perfect drawn with shift {perfect.get('shift')} (arm {arm.shift}) at {rect}, not the holder canvas {canvas}")
    if {"F50", "B", "A0"} <= set(shots):
        if ev.A is None or ev.B is None or ev.A.shape[:2] != shape:
            problems.append("no textures to qualify the reference states")
        else:
            p = {k: premul(v) for k, v in shots.items()}
            far = far_mask(premul(ev.A), premul(ev.B)) & far_mask(p["A0"], p["B"])
            if int(far.sum()) < MIN_CLASS_PX:
                problems.append(f"{int(far.sum())} px where both the textures and the A0/B captures differ < {MIN_CLASS_PX}")
            elif any(float(np.abs(p[a] - p[b])[far].max()) <= cal.tau for a, b in (("A0", "F50"), ("F50", "B"), ("A0", "B"))):
                problems.append("A0, F50 and B not pairwise different (a stale or reused frame)")
            model = float(np.abs(p["F50"] - (p["A0"] + p["B"]) / 2).max())
            if model > REF_MODEL_TOL:
                problems.append(f"|F50 − (A0 + B)/2| = {model} > {REF_MODEL_TOL}")
    return problems


def engage_problems(record: dict[str, Any], ev: Any) -> list[str]:
    """Engagement completeness (shared): exactly one take published inside [advance, transition DOM], the transition DOM
    present, a holder list recorded."""
    insert = next((r["t"] for r in ev.raf if r.get("eff") is not None), None)
    problems = list(score_cost((record.get("dump") or {}).get("takes") or [], record.get("advanceAt"), insert)["problems"])
    if insert is None:
        problems.append("no transition DOM")
    if not isinstance(((record.get("dump") or {}).get("first") or {}).get("holders"), list):
        problems.append("holder list missing")
    return problems


def score_engaged(record: dict[str, Any], ev: Any, arm: Arm) -> dict[str, Any]:
    """Exterior gate / geometry guard: INCONCLUSIVE unless `engage_problems` holds; FAIL with no holder; PASS when every
    holder sits under `holder_parent` and binds to its own decoder."""
    problems = engage_problems(record, ev)
    if problems:
        return result(None, problems)
    first = (record.get("dump") or {}).get("first") or {}
    holders = first["holders"]
    if not holders:
        return result(False, holders=0)
    parent = holder_parent(first, arm)
    bound, bind = bind_holders(holders, [d for d in decoders_of(record) if d.get("region")])
    ids = [str(d.get("id")) for _, d in bound]
    if parent is None or any(h.get("parent") != parent for h in holders) or bind or len(set(ids)) != len(holders):
        return result(None, [f"holders {[h.get('parent') for h in holders]} not each bound under {parent}"] + bind)
    return result(True, holders=len(bound))


def dark(image: np.ndarray, screen: bool) -> bool:
    return float(image[..., :3].max() if screen else image[..., 3].max()) <= DARK_MAX


HIDE_PROGRESS_TOL = 0.02


def image_progress(F: np.ndarray, A: np.ndarray, B: np.ndarray, keep: np.ndarray, *, screen: bool) -> float:
    """Progress read from the pixels: on the out-only class (B transparent) both stock and patch show (1 − e)·A, so
    e = 1 − <F, A> / <A, A> (premultiplied; screen pages RGB over black). NaN with fewer than `MIN_CLASS_PX` px."""
    out = texture_classes(A, B)["out"] & keep
    if int(out.sum()) < MIN_CLASS_PX:
        return math.nan
    Ap = premul(A)[out][:, :3 if screen else 4]
    Fp = (F[..., :3].astype(np.float32) if screen else premul(F))[out][:, :3 if screen else 4]
    den = float((Ap * Ap).sum())
    return 1 - float((Fp * Ap).sum()) / den if den else math.nan


def score_hide(cast: list[dict[str, Any]], actions: Mapping[str, float], raf: list[dict[str, Any]], *, screen: bool,
               A: np.ndarray | None = None, B: np.ndarray | None = None, exclude: list[Iterable[float]] = (),
               cal: Calibration = Calibration()) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Hide/show rows from timestamped screencast frames ({t, img}). Capture integrity, returned as shared problems:
    CDP times strictly increasing, each within one rAF interval of a rAF record, and every content frame's pixel
    progress (`image_progress`) inside the rAF progress over [t − 1, t + 1] rAF intervals (± `HIDE_PROGRESS_TOL`);
    ≥ 1 frame wholly inside [hide, show]; ≥ 6 after-show frames with rAF progress in (0.05, 0.95), all dark or all
    distinct content. Then `hidden`: those inside frames dark (α / RGB ≤ `DARK_MAX`); `shown`: content after show
    (all dark = FAIL); `after_show`: the model ≤ τ on the after-show frames."""
    problems = []
    times = [float(r["t"]) for r in raf]
    ts = [c.get("t") for c in cast]
    hide, show = actions.get("hide"), actions.get("show")
    if not cast or not all(number(t) for t in ts) or any(b <= a for a, b in zip(ts, ts[1:])):
        problems.append("screencast timestamps missing, non-finite, duplicated or out of order")
    elif not times or any(min(abs(t - r) for r in times) > RAF_SLACK_MS for t in ts):
        problems.append("a screencast timestamp is not within one rAF interval of a rAF record")
    if not number(hide) or not number(show) or show <= hide:
        problems.append("hide/show times missing")
    if A is None or B is None or A.shape != B.shape:
        problems.append("no textures to read screencast progress")
    if problems:
        return {k: result(None, problems) for k in ("hidden", "shown", "after_show")}, problems
    keep = ~rect_mask(A.shape[:2], exclude, MEDIA_PAD_PX)

    def window(t: float) -> list[float]:
        return [1 - e[1] for r in raf if abs(float(r["t"]) - t) <= RAF_SLACK_MS for e in [leaf_effs(r)] if e is not None]

    for c in cast:
        span = window(c["t"])
        if span and not dark(c["img"], screen):
            e = image_progress(c["img"], A, B, keep, screen=screen)
            if not number(e) or not min(span) - HIDE_PROGRESS_TOL <= e <= max(span) + HIDE_PROGRESS_TOL:
                problems.append(f"screencast frame at {c['t']:.1f} shows progress {e:.3f}, rAF log {min(span):.3f}..{max(span):.3f}")
                break
    inside = [c for c in cast if hide + RAF_SLACK_MS <= c["t"] <= show]
    if not inside:
        problems.append("no screencast frame inside the hidden interval")
    def mid(t: float) -> bool:
        span = window(t)
        return bool(span) and MID_E[0] < sum(span) / len(span) < MID_E[1]

    after = [c for c in cast if c["t"] >= show + RAF_SLACK_MS and mid(c["t"])]
    blank = [dark(c["img"], screen) for c in after]
    hashes = [hashlib.sha256(np.ascontiguousarray(c["img"]).tobytes()).hexdigest() for c in after]
    if len(after) < COVERAGE["afterShow"]:
        problems.append(f"{len(after)} timestamped after-show mid frames < {COVERAGE['afterShow']}")
    elif any(blank) and not all(blank):
        problems.append("after-show frames mix dark and content")
    elif not any(blank) and len(set(hashes)) != len(hashes):
        problems.append("duplicate after-show frame")
    if problems:
        return {k: result(None, problems) for k in ("hidden", "shown", "after_show")}, problems
    out = {"hidden": result(all(dark(c["img"], screen) for c in inside), frames=len(inside)),
           "shown": result(not all(blank), frames=len(after))}
    if all(blank):
        out["after_show"] = result(False, frames=len(after))
    else:
        prepared = _prepare_fit(A, B, keep, screen)
        fits = [_fit_frame(c["img"], prepared) for c in after]
        if not all(number(e) and number(r) for e, r in fits):
            out["after_show"] = result(None, ["an after-show frame has no finite fit"])
        else:
            out["after_show"] = result(all(r <= cal.tau for _, r in fits), residuals=[r for _, r in fits])
    return out, []


def score_cvc(a: list[float], b: list[float]) -> dict[str, Any]:
    if not a or not b or not all(number(v) for v in [*a, *b]):
        return result(None, ["missing or non-finite mid-frame residuals"])
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


@dataclass(frozen=True)
class Profile:
    """A capture profile: the arms a round requires, the checks only reported there, and whether DX-1's headless
    process/load requirements apply. Gated checks keep their `CONTROLS`; reported ones lose them."""
    name: str
    arms: tuple[str, ...]
    reported: tuple[str, ...] = ()
    headless: bool = True
    lifecycle: bool = True
    overrides: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = ()
    mid_frames: int = MIN_MID_FRAMES
    placement: str | None = None
    not_run: tuple[str, ...] = ()

    def arm(self, name: str, identity: bool | None = None) -> Arm:
        arm = ARMS[name]
        expect = {k: "REPORTED" if k in self.reported or (k == "tone" and identity) else v for k, v in arm.expect.items()}
        return replace(arm, expect=expect)

    def controls(self) -> dict[str, tuple[tuple[str, ...], ...]]:
        return {k: dict(self.overrides).get(k, v) for k, v in CONTROLS.items() if k not in self.reported}

    def required(self, identity: bool | None) -> tuple[str, ...]:
        """Every arm scored on its own: not a twin (twins are scored inside their arm or row), except the hide-capture
        controls, which carry their own contract."""
        scored = (n for n in self.arms if (n not in TWINS and (ARMS[n].row is None or ARMS[n].twin is not None)) or
                  (ARMS[n].row is not None and ARMS[n].expect))
        return tuple(n for n in scored if not (n == "m-tone-raw" and identity))


CEF_ONLY = ("cef-skip", "cef-skip-dsk")
CEF_PLACEMENT_ONLY = tuple(n for n in ARMS if "cef" in n and n not in CEF_ONLY)
DX1 = Profile("DX-1", tuple(n for n in ARMS if n not in (*CEF_ONLY, *CEF_PLACEMENT_ONLY)))
CEF = Profile("CEF", ("opaque-off", "off", "noblend", "on2", "cut-on", "cut-off", "on", "opaque-on", *CEF_ONLY),
              reported=("no_flash", "screen", "geometry", "exterior", "hidden", "shown", "frozen_frame", "frozen_region",
                        "foreground", "tone", "overlay", "cost", "holder_pixels", "reference", "mask", "grant"),
              headless=False, lifecycle=False, overrides=(("scope", ((), CEF_ONLY)),), mid_frames=5)
"""DX-2 (§9.2): the DX-1 cross-fade, cut and opaque arms OBS can carry plus `cef-skip` (P2 2->3, DSK 7->8): CEF never
gets the snapped-placement grant (decision 15), so each publishes a take with no holder; checks without a CEF arm are
reported."""

CEF_PLACEMENT_POSITIVES = tuple(_CEF_SNAP_ROWS)
CEF_PLACEMENT_ARMS = (
    "opaque-off", "off", "noblend", "on2", "cut-on", "cut-off", "on", "opaque-on",
    *CEF_PLACEMENT_POSITIVES,
    *(f"{name}-twin" for name in CEF_PLACEMENT_POSITIVES),
    "m-paused-cef", "m-off-cef", "m-hold-cef", "m-fg-cef", "m-fg-omit-cef", "m-fg-swap-cef",
    "m-tone-cef", "m-tone-cef-twin", "m-tone-raw-cef", "m-snap-cef-dsk", "wrongrule-cef", "wrongrule-cef-twin",
    "m-snap-cef-nooffset-x", "m-snap-cef-nooffset-x-twin", "m-snap-cef-nooffset-y", "m-snap-cef-nooffset-y-twin",
    "m-snap-cef-underlay-omit", "perfect-shift", "m-geo-scale", "m-geo-base",
)
CEF_PLACEMENT = Profile(
    "CEF-placement", CEF_PLACEMENT_ARMS,
    reported=("no_flash", "screen", "cut", "exterior", "hidden", "shown", "tone", "overlay", "scope", "grant"),
    headless=False, lifecycle=False, placement="frac",
    overrides=(
        ("frozen_frame", (("m-paused-cef",), ("m-off-cef",))),
        ("frozen_region", (("m-fg-cef",), ("m-hold-cef",))),
        ("foreground", (("m-fg-cef",), ("m-fg-omit-cef", "m-fg-swap-cef", "case:fg-shifted", "case:fg-double", "case:fg-swapped"))),
        ("tone", (("m-tone-cef",), ("m-tone-raw-cef",))),
        ("holder_pixels", (CEF_PLACEMENT_POSITIVES,
                           ("m-snap-cef-nooffset-x", "m-snap-cef-nooffset-y", "m-snap-cef-underlay-omit", "wrongrule-cef",
                            "case:holder-shift"))),
        ("reference", ((*CEF_PLACEMENT_POSITIVES, "case:reference-valid"), ("perfect-shift",),
                       ("case:reference-stale", "case:reference-extra", "case:reference-unpaused"))),
        ("mask", ((*CEF_PLACEMENT_POSITIVES, "m-tone-cef", "case:mask-production"), (),
                  ("case:mask-whole", "case:mask-shift3", "case:mask-empty"))),
        ("geometry", ((*CEF_PLACEMENT_POSITIVES, "m-snap-cef-dsk"),
                      ("m-geo-scale", "m-geo-base"))),
    ),
    mid_frames=5,
)

_DEV_RENDERER_ARMS = (
    "opaque-off", "off", "noblend", "on2", "on", "m-snap-cef", "m-snap-cef-twin",
    "wrongrule-cef", "wrongrule-cef-twin", "perfect-shift", "m-tone-cef", "m-tone-cef-twin",
    "m-geo-scale", "m-paused-cef", "m-off-cef", "m-fg-cef", "m-hold-cef", "m-fg-omit-cef",
    "m-fg-swap-cef", "m-snap-cef-underlay-omit",
)
_DEV_HARNESS_ARMS = (
    *_DEV_RENDERER_ARMS,
    "m-snap-cef-nooffset-x", "m-snap-cef-nooffset-x-twin",
    "m-snap-cef-nooffset-y", "m-snap-cef-nooffset-y-twin", "m-geo-base", "m-snap-cef-dsk",
)


def _dev_overrides(arms: tuple[str, ...]) -> tuple[tuple[str, tuple[tuple[str, ...], ...]], ...]:
    selected = set(arms)
    return tuple(
        (check, tuple(tuple(name for name in names if name.startswith("case:") or name in selected) for names in controls))
        for check, controls in dict(CEF_PLACEMENT.overrides).items()
    )


CEF_PLACEMENT_DEV_RENDERER = Profile(
    "CEF-placement-DEV-renderer", _DEV_RENDERER_ARMS,
    reported=(*CEF_PLACEMENT.reported, "cost"), headless=False, lifecycle=False, placement="frac",
    overrides=_dev_overrides(_DEV_RENDERER_ARMS), mid_frames=5, not_run=("cost",),
)
CEF_PLACEMENT_DEV_HARNESS = Profile(
    "CEF-placement-DEV-harness", _DEV_HARNESS_ARMS,
    reported=CEF_PLACEMENT.reported, headless=False, lifecycle=False, placement="frac",
    overrides=_dev_overrides(_DEV_HARNESS_ARMS), mid_frames=5,
)
CEF_PLACEMENT_DEV_PROFILES = {
    "renderer": CEF_PLACEMENT_DEV_RENDERER,
    "harness": CEF_PLACEMENT_DEV_HARNESS,
}


def profile_coverage_problems(profile: Profile) -> list[str]:
    problems = []
    if not set(profile.not_run) <= set(profile.reported):
        problems.append(f"not_run outside reported: {sorted(set(profile.not_run) - set(profile.reported))}")
    for check, controls in profile.controls().items():
        live_controls = [name for names in controls for name in names if not name.startswith("case:")]
        missing = [name for name in live_controls if name not in profile.arms]
        candidates = [name for name in profile.arms if profile.arm(name, False).expect.get(check) == "PASS"]
        if missing:
            problems.append(f"{check}: live controls outside profile: {missing}")
        if not candidates:
            problems.append(f"{check}: no live PASS candidate")
    if not {"on", "on2"} <= set(profile.arms):
        problems.append("cvc: on/on2 candidates missing")
    return problems


ANIM_STATES = ("idle", "running", "paused", "finished")
TIMED_STATES = ("running", "paused", "finished")
ACTION_NAMES = ("space", "skip", "back", "goto1", "hide", "show")


def quad(value: Any, n: int = 4) -> bool:
    return isinstance(value, list) and len(value) == n and all(number(v) for v in value)


def box_ok(value: Any) -> bool:
    """A finite [x, y, width, height] with non-negative width and height."""
    return quad(value) and value[2] >= 0 and value[3] >= 0


def unit(value: Any) -> bool:
    return number(value) and 0 <= value <= 1


def integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def anim_problem(a: Any) -> str | None:
    """One transition-animation record: leaf and CSS play state from their enums, finite value, positive duration;
    `ct`/`start` present, finite when populated, resolved current time in a timed state, and resolved start time for a
    finished animation. Paused animations and running animations with a pending play task may have no start time."""
    if not isinstance(a, dict):
        return "not a record"
    if a.get("leaf") not in ("in", "out") or a.get("state") not in ANIM_STATES:
        return f"leaf/state {a.get('leaf')!r}/{a.get('state')!r}"
    if not unit(a.get("value")) or not number(a.get("dur")) or a["dur"] <= 0:
        return "value outside [0, 1] or duration not positive"
    if "ct" not in a or "start" not in a:
        return "ct/start absent"
    for key in ("ct", "start"):
        if a[key] is not None and not number(a[key]):
            return f"{key} not finite"
    if a["ct"] is not None and a["ct"] < 0:
        return "negative currentTime"
    if a["state"] in TIMED_STATES and (a["ct"] is None or (a["state"] == "finished" and a["start"] is None)):
        return f"null timing while {a['state']}"
    return None


def video_problem(v: Any) -> str | None:
    """One per-rAF video record: integer id, boolean `on`; connected ones with finite rect and opacity, boolean
    membership/paused flags and a null or finite geometry."""
    if not isinstance(v, dict) or not integer(v.get("id")) or not isinstance(v.get("on"), bool):
        return "id/on"
    if not v["on"]:
        return None
    if not box_ok(v.get("rect")) or not unit(v.get("eff")) or not all(isinstance(v.get(k), bool) for k in ("inT", "inStage", "paused")):
        return "rect (non-negative size) / opacity in [0, 1] / flags"
    geo = v.get("geo", "absent")
    if geo is not None and not (isinstance(geo, dict) and box_ok(geo.get("content")) and box_ok(geo.get("region"))
                                and quad(geo.get("size"), 2) and min(geo["size"]) > 0):
        return "geometry"
    return None


def schema_problems(record: dict[str, Any]) -> list[str]:
    """One schema check per record kind (animation, video, decoder/rVFC, take publication, cast, holder, lifecycle
    action, foreground-inventory canvas, reference capture), run before any scorer filters records; any violation is a
    shared integrity failure."""
    dump = record.get("dump") if isinstance(record.get("dump"), dict) else {}
    problems = []
    for r in dump.get("raf") or []:
        if not isinstance(r, dict):
            continue
        bad = [x for x in (anim_problem(a) for a in r.get("anims") or []) if x]
        if bad:
            problems.append(f"animation record at {r.get('t')}: {bad[0]}")
        videos = r.get("videos") if isinstance(r.get("videos"), list) else []
        bad = [x for x in (video_problem(v) for v in videos) if x]
        ids = [v.get("id") for v in videos if isinstance(v, dict)]
        if bad or len(set(map(str, ids))) != len(ids):
            problems.append(f"video record at {r.get('t')}: {bad[0] if bad else 'duplicate id'}")
    vids = dump.get("vids", [])
    if not isinstance(vids, list) or not all(
            isinstance(v, dict) and integer(v.get("id")) and isinstance(v.get("rv"), list)
            and all(isinstance(x, list) and len(x) in (3, 4) and all(number(n) for n in x)
                    and x[1] >= 0 and x[2] >= 0 for x in v["rv"])
            and isinstance(v.get("rvAt"), list) and len(v["rvAt"]) == len(v["rv"])
            and all(number(value) for value in v["rvAt"])
            and isinstance(v.get("freezeDraws", []), list)
            and all(isinstance(draw, dict)
                    and all(number(draw.get(key)) for key in ("startedAt", "finishedAt", "durationMs"))
                    and (draw.get("argumentCount") is None or integer(draw.get("argumentCount")))
                    and all(draw.get(key) is None or number(draw.get(key))
                            for key in ("beforeTimestampUs", "afterTimestampUs"))
                    and all(draw.get(key) is None or isinstance(draw.get(key), str)
                            for key in ("beforeError", "afterError")) for draw in v.get("freezeDraws", []))
            and (v.get("detach") is None or number(v.get("detach")))
            and all(v.get(k) is None or isinstance(v.get(k), str) for k in ("tuple", "err", "src")) for v in vids) \
            or len({v.get("id") for v in vids if isinstance(v, dict)}) != len(vids):
        problems.append("decoder/rVFC records malformed")
    takes = dump.get("takes", [])
    if not isinstance(takes, list) or not all(isinstance(t, list) and len(t) == 2 and number(t[0]) and (t[1] is None or (number(t[1]) and t[1] >= 0))
                                              for t in takes):
        problems.append("take publications malformed")
    cast = record.get("cast", [])
    if not isinstance(cast, list) or not all(isinstance(c, dict) and isinstance(c.get("name"), str) and c["name"]
                                             and (number(c.get("t")) or (number(c.get("t0")) and number(c.get("t1")))) for c in cast):
        problems.append("cast records malformed")
    first = dump.get("first") if isinstance(dump.get("first"), dict) else {}
    holders = first.get("holders", [])
    if not isinstance(holders, list) or not all(isinstance(h, dict) and box_ok(h.get("rect")) and box_ok(h.get("canvasRect"))
                                                and isinstance(h.get("natural"), list) and len(h["natural"]) == 2
                                                and all(integer(n) and n > 0 for n in h["natural"])
                                                and isinstance(h.get("parent", ""), str) for h in holders):
        problems.append("holder records malformed")
    actions = record.get("actions", [])
    if not isinstance(actions, list) or not all(isinstance(a, dict) and a.get("name") in ACTION_NAMES and number(a.get("t"))
                                                and a.get("dropped", True) is True for a in actions):
        problems.append("lifecycle actions malformed")
    foreground = record.get("foreground", {})
    if not isinstance(foreground, dict) or not all(
            isinstance(k, str) and k.isdigit() and isinstance(cs, list) and all(fg_canvas_ok(c) for c in cs) for k, cs in foreground.items()):
        problems.append("foreground inventory malformed")
    if "reference" in record and not reference_ok(record["reference"]):
        problems.append("reference capture records malformed")
    return problems


def fg_canvas_ok(c: Any) -> bool:
    """One foreground-inventory canvas: id, CSS rect, effective opacity, document-order index, its pixels' image name."""
    return (isinstance(c, dict) and isinstance(c.get("id"), str) and box_ok(c.get("rect")) and unit(c.get("alpha"))
            and integer(c.get("order")) and c["order"] >= 0 and isinstance(c.get("image"), str) and bool(c["image"]))


def reference_ok(ref: Any) -> bool:
    """Types and enums of the reference-capture block (inventory, paused states, perfect); semantics are checked by
    `reference_problems`."""
    def shots(s: dict[str, Any]) -> bool:
        return isinstance(s.get("shots"), list) and all(isinstance(n, str) and n for n in s["shots"])

    def anim(a: Any, timed: bool) -> bool:
        return (isinstance(a, dict) and (a.get("target") is None or isinstance(a["target"], str)) and a.get("state") in ANIM_STATES
                and (not timed or (number(a.get("dur")) and (a.get("ct") is None or number(a["ct"])))))

    if not isinstance(ref, dict) or not isinstance(ref.get("inventory"), list) or not isinstance(ref.get("states"), list):
        return False
    if not all(anim(a, False) and a.get("leaf") in ("in", "out", None) for a in ref["inventory"]):
        return False
    for s in ref["states"]:
        if not (isinstance(s, dict) and isinstance(s.get("label"), str) and number(s.get("f")) and number(s.get("t")) and shots(s)
                and isinstance(s.get("dom"), bool) and isinstance(s.get("anims"), list) and all(anim(a, True) for a in s["anims"])
                and (s.get("eff") is None or leaf_effs(s) is not None)):
            return False
    t = ref.get("timers", {"minMs": TIMER_MIN_MS, "extraMs": TIMER_EXTRA_MS, "delayedMs": []})
    if not (isinstance(t, dict) and number(t.get("minMs")) and number(t.get("extraMs")) and isinstance(t.get("delayedMs"), list)
            and all(number(v) and v >= 0 for v in t["delayedMs"])):
        return False
    p = ref.get("perfect")
    return (isinstance(p, dict) and integer(p.get("shift")) and (p.get("rect") is None or quad(p["rect"])) and shots(p)
            and (not p["shots"] or (isinstance(p.get("dom"), bool) and number(p.get("t")))))


def raf_problems(raf: Any) -> list[str]:
    """Every rAF record well formed: finite, strictly increasing `t`; `eff` absent or two finite leaf opacities with an
    `anims` list beside it; `anims` and `videos` (always present; observed empty = []) lists of records; no gap > `RAF_GAP_MS` while the transition DOM is present
    except a pre-start one (`raf_gaps`)."""
    if not isinstance(raf, list) or not all(isinstance(r, dict) for r in raf):
        return ["rAF log is not a list of records"]
    if not all(number(r.get("t")) for r in raf) or any(b["t"] <= a["t"] for a, b in zip(raf, raf[1:])):
        return ["rAF times missing, non-finite, duplicated or out of order"]
    bad = [r["t"] for r in raf if ("eff" in r and (leaf_effs(r) is None or not isinstance(r.get("anims"), list)))
           or not isinstance(r.get("videos"), list)
           or not all(isinstance(r.get(k, []), list) and all(isinstance(x, dict) for x in r.get(k, [])) for k in ("anims", "videos"))]
    if bad:
        return [f"malformed rAF records at {bad[:3]}"]
    span = [i for i, r in enumerate(raf) if "eff" in r]
    if span and span != list(range(span[0], span[-1] + 1)):
        return ["the transition DOM vanishes and reappears inside one capture"]
    fade = raf[span[0]:span[-1] + 1] if span else []
    return ["rAF gap inside the transition"] if raf_gaps(fade)[0] else []


PAUSED = ("paused", "reference")


def injection_problems(name: str, value: Any, viewport: tuple[int, int]) -> list[str]:
    """The injection's own evidence that it took effect where the control needs it (`RAW_INJECTIONS`): a border box
    wholly left of the viewport whose paint reaches into it (caption, script; the SVG witness box), the sidebar slid to
    x 0 and meeting the viewport, an open modal dialog (top layer: position-independent), an overlay or stroke painting
    inside the viewport."""
    if not isinstance(value, dict):
        return [f"injection {name} did not apply: {value!r}"]

    def rect(key: str) -> list[float] | None:
        r = value.get(key)
        return r if box_ok(r) and r[2] > 0 and r[3] > 0 else None

    def off_left(key: str) -> bool:
        r = rect(key)
        return r is not None and r[0] + r[2] <= 0

    def in_view(key: str) -> bool:
        r = rect(key)
        return r is not None and overlaps(r, [0, 0, *viewport])

    ok = {"caption": lambda: off_left("box") and in_view("paint"),
          "script": lambda: off_left("box") and in_view("paint"),
          "svgclip": lambda: off_left("box") and in_view("paint"),
          "svg": lambda: in_view("paint"),
          "shadow-fixed": lambda: in_view("paint"),
          "nav-open": lambda: in_view("box") and abs(value["box"][0]) < 0.5,
          "modal": lambda: value.get("open") is True and value.get("modal") is True,
          "shadow-modal": lambda: value.get("open") is True and value.get("modal") is True}[name]()
    return [] if ok else [f"injection {name} evidence does not show it took effect: {value!r}"]


def capture_problems(record: dict[str, Any], images: Mapping[str, np.ndarray], arm: Arm, profile: Profile = DX1,
                     cal: Calibration = Calibration()) -> list[str]:
    """Capture integrity (§9.1): any violation makes every check of the arm INCONCLUSIVE."""
    problems = []
    shape = device_shape(arm)
    if record.get("error"):
        problems.append(f"run error: {str(record['error']).strip().splitlines()[-1]}")
    target, served, dump = record.get("target") or {}, record.get("served") or {}, record.get("dump") or {}
    first = dump.get("first") or {}
    if not dump.get("raf"):
        problems.append("no rAF records")
    else:
        problems += raf_problems(dump["raf"])
    problems += schema_problems(record)
    if not target.get("textures") or first.get("textures") != target.get("textures"):
        problems.append(f"texture ids {first.get('textures')} != {target.get('textures')}")
    for key in ("hashBefore", "hashAfter"):
        want, got = target.get(key), record.get(key)
        if not isinstance(want, str) or not isinstance(got, str) or not re.fullmatch(r"#\d+", got) or not re.fullmatch(r"#\d+", want):
            problems.append(f"{key}: expected {want!r}, observed {got!r} (both required)")
        elif want != got and (key == "hashBefore" or arm.row is None):
            problems.append(f"{key} {got} != {want}")
    if record.get("page") != arm.page:
        problems.append(f"page mode {record.get('page')} != {arm.page}")
    pins = live_runtime.SUPPORTED_PLAYERS.get(served.get("stockSha256") or "")
    output_sha = ((record.get("output") or {}).get("mmOpacity") or {}).get("sha256")
    if pins is None:
        problems.append("stock player is not a supported player")
    elif not output_sha or output_sha != served.get("expected"):
        problems.append(f"served digest {output_sha} != expected {served.get('expected')}")
    elif arm.splice is None and output_sha != pins[PIN_INDEX[arm.mode]]:
        problems.append("served digest is not the pinned digest for the mode")
    stage, want = record.get("stage"), stage_of(arm)
    if not isinstance(stage, dict) or not all(number(stage.get(k)) and abs(stage[k] - v) <= 0.5 for k, v in want.items()):
        problems.append(f"stage {stage} is not the fitted slide {want}")
    load = record.get("load")
    if profile.headless and (not number(load) or load >= MAX_LOAD or record.get("headlessBefore") != 0):
        problems.append(f"load {record.get('load')} / headless before {record.get('headlessBefore')}")
    meta = record.get("shots") or []
    if (len({s.get("name") for s in meta}) != len(meta) or any(not number(s.get("t0")) or not number(s.get("t1")) or s["t1"] < s["t0"] for s in meta)
            or any(b["t0"] <= a["t0"] for a, b in zip(meta, meta[1:]) if number(a.get("t0")) and number(b.get("t0")))):
        problems.append("duplicate, untimed or out-of-order screenshot records")
    shots = [images.get(s.get("name")) for s in meta]
    if (not shots and arm.capture != "reference") or any(s is None or s.shape != (*shape, 4) for s in shots):
        problems.append("screenshots missing or not full-device RGBA")
    if any(device_texture(images.get(k), arm) is None for k in ("tex-in", "tex-out")):
        problems.append("textures missing or not the stage's CSS or device size")
    launch = record.get("launch") if isinstance(record.get("launch"), dict) else {}
    flags = [a for a in launch.get("chromeArgs") or [] if isinstance(a, str) and a.startswith("--force-device-scale-factor=")]
    if arm.dsf != 1 and (flags != [f"--force-device-scale-factor={arm.dsf:g}"] or launch.get("metricsOverride", "absent") is not None):
        problems.append(f"devicePixelRatio {arm.dsf} not from the Chrome launch flag (emulated or unrecorded): {launch or None}")
    dsf, viewport = record.get("dsf"), record.get("viewport")
    if not number(dsf) or not 0.5 <= dsf <= 4 or abs(dsf - arm.dsf) > 1e-6:
        problems.append(f"recorded devicePixelRatio {dsf!r} is not the arm's {arm.dsf}")
    if not (isinstance(viewport, list) and len(viewport) == 2 and all(integer(v) and v > 0 for v in viewport)
            and tuple(viewport) == viewport_of(arm)):
        problems.append(f"recorded viewport {viewport!r} is not the arm's {list(viewport_of(arm))}")
    if first and not isinstance(first.get("holders"), list):
        problems.append("holder list missing")
    holders = first.get("holders") or []
    if arm.holders is not None and len(holders) != arm.holders:
        problems.append(f"{len(holders)} holders, expected {arm.holders}")
    for i, h in enumerate(holders):
        img = images.get(f"holder-{i}")
        natural = h.get("natural") or []
        if not all(len(h.get(k) or []) == 4 and all(number(v) for v in h[k]) for k in ("rect", "canvasRect")):
            problems.append(f"holder {i} geometry malformed")
            continue
        box = device_box(h["canvasRect"], arm.dsf)
        if img is None or len(natural) != 2 or img.shape[:2] != (natural[1], natural[0]):
            problems.append(f"holder {i} pixels missing or not its backing size")
        elif box is None or list(natural) != [box[2] - box[0], box[3] - box[1]]:
            problems.append(f"holder {i} backing {natural} is not its device rect {box}")
    problems += styles_problems(first.get("chain"), arm.styles)
    if arm.capture in (*PAUSED, "media", "lifecycle") or arm.movies:
        live = [images.get(k) for k in ("live-0", "live-1")]
        if any(x is None or x.shape != (*shape, 4) for x in live):
            problems.append("S_live pair missing")
        elif arm.capture in PAUSED and not np.array_equal(live[0], live[1]):
            problems.append("the two paused S_live differ")
    if arm.capture in PAUSED and ((record.get("paused") or {}).get("state") != "presented"
                                  or not number((record.get("paused") or {}).get("frame"))):
        problems.append(f"movie not paused on a presented frame: {record.get('paused')}")
    if arm.capture == "lifecycle" and (images.get("settled") is None or images["settled"].shape != (*shape, 4)):
        problems.append("no settled frame")
    if (arm.row or "").startswith("hide") and (not record.get("cast") or any(images.get(c.get("name")) is None
                                                                             or images[c["name"]].shape != (*shape, 4)
                                                                             for c in record.get("cast") or [])):
        problems.append("hide row without its full-device screencast")
    dropped = {a.get("name") for a in record.get("actions") or [] if isinstance(a, dict) and a.get("dropped")}
    if dropped != ({arm.drop} if arm.drop else set()):
        problems.append(f"dropped actions {sorted(map(str, dropped))} != the arm's {arm.drop!r}")
    if arm.inject:
        problems += injection_problems(arm.inject, record.get("inject"), viewport_of(arm))
    problems += placement_problems(record, arm, profile)
    if arm.capture in ("reference", "engage"):
        ev = evidence(record, images, arm)
        problems += class_problems(ev.A, ev.B, ev.media, arm.classes, arm.min_class_px)
        if arm.capture == "reference":
            problems += reference_problems(record, images, arm, ev, cal)
    return problems


def placement_problems(record: dict[str, Any], arm: Arm, profile: Profile = DX1) -> list[str]:
    """The page's own `__obedPlacement` read just before the advance: `snap` on a DX-1 arm granted through the host's
    privileged channel (the host's token, or the raw page's first-run script); without a grant `invalid` on a host page
    (the first-run script is always installed) and absent on the production raw/preview page; a reload row also reads
    `invalid` in the fresh document before the host's re-grant and `snap` after it."""
    read = record.get("placement", "missing")
    if arm.forgery:
        value, kind = FORGERIES[arm.forgery]
        forged = record.get("forgery")
        problems = []
        if not isinstance(forged, dict) or forged.get("read") != value or forged.get("kind") != kind:
            problems.append(f"forgery {arm.forgery!r} did not take effect: {forged!r}")
        if kind == "getter" and (forged or {}).get("configurable") is not False:
            problems.append(f"forged getter is configurable: {forged!r}")
        if read != value:
            problems.append(f"page placement {read!r} != forged {value!r} before the advance")
        return problems
    if arm.grant == "none":
        want = None if arm.page in ("raw", "preview") else "invalid"
    elif arm.placement_value is not None:
        want = arm.placement_value
    elif profile.placement is not None:
        want = profile.placement
    elif profile.headless:
        want = "snap"
    else:
        return []
    problems = [] if read == want else [f"page placement {read!r} != {want!r} before the advance"]
    if arm.regrant == "reload" and (record.get("reload") or {}).get("before") != "invalid":
        problems.append(f"no fresh `invalid` document before the re-grant: {record.get('reload')}")
    return problems


def class_problems(A: np.ndarray | None, B: np.ndarray | None, exclude: list[Iterable[float]], classes: Iterable[str],
                   min_px: int = MIN_CLASS_PX) -> list[str]:
    """§9.1 spatial completeness, independent of temporal coverage: every required texture class has >= `min_px` px
    outside the media rects (+ `MEDIA_PAD_PX`)."""
    if A is None or B is None or A.shape != B.shape:
        return ["no textures for the required classes"]
    keep = ~rect_mask(A.shape[:2], exclude, MEDIA_PAD_PX)
    masks = texture_classes(A, B)
    return [f"class {k}: {int((masks[k] & keep).sum())} px < {min_px}" for k in classes if int((masks[k] & keep).sum()) < min_px]


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
    dsf: float = 1.0
    destination: list[list[float]] = field(default_factory=list)


def media_rects(record: dict[str, Any], dsf: float = 1.0, *, handoff: bool = True) -> list[list[float]]:
    """Every tagged `<video>` rect seen in the stage during the capture and every holder rect, in device px. Without
    `handoff`, only up to the last rAF with the transition DOM: the destination's movies that start after the hand-off
    are texture pixels in every transition frame, and excluding them could empty a required class."""
    dump = record.get("dump") or {}
    raf = dump.get("raf") or []
    last = max((i for i, r in enumerate(raf) if r.get("eff") is not None), default=None)
    if not handoff and last is not None:
        raf = raf[:last + 1]
    media = [v["rect"] for r in raf for v in r.get("videos") or [] if v.get("on") and v.get("inStage") and v.get("rect")]
    media += [h["rect"] for h in (dump.get("first") or {}).get("holders") or [] if h.get("rect")]
    return device_rects({tuple(round(x, 1) for x in m) for m in media}, dsf)


def device_texture(texture: np.ndarray | None, arm: Arm) -> np.ndarray | None:
    """A transition texture (the leaf canvas backing: the slide) placed on the device screen at the stage's device box,
    resampled (bilinear) from the stage's CSS size at DPR != 1; None unless it is exactly the stage's CSS or device size."""
    if texture is None or texture.ndim != 3 or texture.shape[2] != 4 or not texture.size:
        return None
    stage = stage_of(arm)
    x0, y0 = jround(stage["x"] * arm.dsf), jround(stage["y"] * arm.dsf)
    w, h = round(stage["width"] * arm.dsf), round(stage["height"] * arm.dsf)
    if texture.shape[:2] not in ((h, w), (round(stage["height"]), round(stage["width"]))):
        return None
    if texture.shape[:2] != (h, w):
        texture = np.asarray(Image.fromarray(np.ascontiguousarray(texture)).resize((w, h), Image.BILINEAR))
    out = np.zeros((*device_shape(arm), 4), np.uint8)
    ys, xs = slice(max(0, y0), min(out.shape[0], y0 + h)), slice(max(0, x0), min(out.shape[1], x0 + w))
    out[ys, xs] = texture[ys.start - y0:ys.stop - y0, xs.start - x0:xs.stop - x0]
    return out


def evidence(record: dict[str, Any], images: Mapping[str, np.ndarray], arm: Arm) -> Evidence:
    dsf = arm.dsf
    dump = record.get("dump") or {}
    raf = dump.get("raf") or []
    meta = record.get("shots") or []
    shots = [images[s["name"]] for s in meta if s.get("name") in images]
    timed = len(shots) == len(meta) and all(number(s.get("t0")) and number(s.get("t1")) for s in meta)
    phases = shot_phases(meta, raf) if timed else ["ambiguous"] * len(shots)
    first = dump.get("first") or {}
    holders = []
    A, B = device_texture(images.get("tex-out"), arm), device_texture(images.get("tex-in"), arm)
    for i, h in enumerate(first.get("holders") or []):
        img = images.get(f"holder-{i}")
        if img is None or A is None or not quad(h.get("canvasRect")) or not quad(h.get("rect")):
            continue
        placed = paste_holder(img, h, A.shape[:2], dsf)
        if placed is None:
            continue
        holders.append(placed)
        A = over(placed, A)
    return Evidence(shots, phases, A, B, holders, media_rects(record, dsf, handoff=False), raf,
                    [i for i, p in enumerate(phases) if p == "transition"], dsf, media_rects(record, dsf))


def _fade_of(ev: Evidence, arm: Arm, cal: Calibration, min_frames: int = MIN_MID_FRAMES) -> dict[str, Any]:
    frames = [ev.shots[i] for i in ev.transition]
    return score_fade(frames, ev.A, ev.B, exclude=ev.media, classes=arm.classes, cal=cal, screen=arm.page == "screen",
                      min_frames=min_frames, min_class_px=arm.min_class_px)


def capture_coverage(record: dict[str, Any], images: Mapping[str, np.ndarray], arm: Arm,
                     min_frames: int = MIN_MID_FRAMES, cal: Calibration = Calibration()) -> dict[str, Any]:
    try:
        profile = replace(CEF_PLACEMENT, mid_frames=min_frames)
        scored = score_arm(record, images, arm, cal, profile=profile)
        fitted = scored.get("fitted", [])
        mid = sum(number(row[0]) and MID_E[0] < row[0] < MID_E[1] for row in fitted)
        return {"midFrames": mid, "fitted": fitted, "problems": scored.get("problems", [])}
    except MALFORMED as exc:
        return {"midFrames": 0, "fitted": [], "problems": [f"malformed capture: {type(exc).__name__}: {exc}"]}


def _handoff_frames(ev: Evidence) -> tuple[np.ndarray | None, np.ndarray | None]:
    if not ev.transition:
        return None, None
    last = ev.transition[-1]
    first = next((i for i in range(last + 1, len(ev.phases)) if ev.phases[i] == "live"), None)
    return ev.shots[last], None if first is None else ev.shots[first]


def pre_detach(decoder: dict[str, Any]) -> list[list[float]]:
    """The rVFC records before the detach; none unless every record is well formed, strictly later than the previous
    one and never presents fewer frames (a duplicated or reordered log is malformed)."""
    detach, rv = decoder.get("detach"), decoder.get("rv")
    if not number(detach) or not isinstance(rv, list):
        return []
    if not all(isinstance(r, (list, tuple)) and len(r) in (3, 4) and all(number(v) for v in r) for r in rv):
        return []
    if any(b[0] <= a[0] or b[2] < a[2] for a, b in zip(rv, rv[1:])):
        return []
    return [r for r in rv if r[0] <= detach]


def frame_at_freeze_draw(decoder: dict[str, Any], counter_fps: float | None,
                         advance_at: float | None, first_effective_raf_at: float | None,
                         ) -> tuple[int | None, dict[str, Any], list[str]]:
    recorded = decoder.get("freezeDraws")
    draws = ([draw for draw in recorded if isinstance(draw, dict) and number(draw.get("startedAt"))
              and number(advance_at) and number(first_effective_raf_at)
              and advance_at <= draw["startedAt"] <= first_effective_raf_at]
             if isinstance(recorded, list) else [])
    detail = {"draws": draws, "recordedDrawCount": len(recorded) if isinstance(recorded, list) else None,
              "window": [advance_at, first_effective_raf_at], "rvfcRows": decoder.get("rv"),
              "rvfcCallbackAt": decoder.get("rvAt")}
    if counter_fps is None or not draws:
        return None, detail, ["no VideoFrame timestamp around the freeze draw"]
    problems: list[str] = []
    full_timestamps = []
    repair_timestamps: list[tuple[int, float]] = []
    for index, draw in enumerate(draws):
        argument_count = draw.get("argumentCount")
        if argument_count not in (5, 9):
            problems.append(f"freeze draw {index} has unsupported argument count {argument_count!r}")
            continue
        before, after = draw.get("beforeTimestampUs"), draw.get("afterTimestampUs")
        if not number(before) or not number(after):
            problems.append(f"freeze draw {index} has no before/after VideoFrame timestamp")
        elif before != after:
            problems.append(f"freeze draw {index} VideoFrame timestamp changed from {before} to {after}")
        elif argument_count == 5:
            full_timestamps.append(before)
        else:
            repair_timestamps.append((index, before))
    if not full_timestamps:
        problems.append("no full-size freeze draw with a VideoFrame timestamp")
    elif len(set(full_timestamps)) > 1:
        problems.append(f"full-size freeze draws used different VideoFrame timestamps: {full_timestamps}")
    reference = round(full_timestamps[0] / 1_000_000 * counter_fps) if full_timestamps else None
    repair_frames = [(index, round(timestamp / 1_000_000 * counter_fps))
                     for index, timestamp in repair_timestamps]
    diagnostics = []
    if reference is not None:
        for index, frame in repair_frames:
            if frame == reference + 1:
                diagnostics.append(f"repair draw {index} used frame {frame}, one frame after reference {reference}")
            elif frame != reference:
                problems.append(f"repair draw {index} used frame {frame}, expected {reference} or {reference + 1}")
    detail["fullSizeFrames"] = [round(timestamp / 1_000_000 * counter_fps) for timestamp in full_timestamps]
    detail["repairFrames"] = [frame for _, frame in repair_frames]
    detail["diagnostics"] = diagnostics
    return (reference if reference is not None and not problems else None), detail, problems


def holder_parent(first: dict[str, Any], arm: Arm) -> str | None:
    """Where the arm's holders belong, from the textures' ancestry (`chain` = [incoming, outgoing]): the one
    `layer<id>-opacity` wrapper above the outgoing texture only; for the `hold` splice, the nearest common `layer<id>`."""
    chain = first.get("chain")
    if not isinstance(chain, list) or len(chain) != 2 or not all(isinstance(c, list) for c in chain):
        return None
    ids = [[str(n.get("id")) for n in c if isinstance(n, dict)] for c in chain]
    if "hold" in (arm.splice or "").split("+"):
        hits = [i for i in ids[1] if re.fullmatch(r"layer\d+", i) and i in ids[0]][:1]
    else:
        hits = [i for i in ids[1] if re.fullmatch(r"layer\d+-opacity", i) and i not in ids[0]]
    return hits[0] if len(hits) == 1 else None


def media_arm(arm: Arm) -> bool:
    """Arms whose movie evidence is shared integrity whatever checks they carry (§9.1 media evidence)."""
    return arm.capture in ("media", "paused", "reference", "engage") or bool(set(MEDIA_CHECKS) & set(arm.expect))


MEDIA_CHECKS = ("frozen_frame", "frozen_region", "foreground", "tone", "overlay")


def dsk_counter_fps() -> float | None:
    if not DSK_COUNTER_MOVIE.is_file() or binary.sha256_file(DSK_COUNTER_MOVIE) != DSK_COUNTER_SHA256:
        return None
    try:
        _, _, fps, _ = dsk_movie_export._ffprobe(DSK_COUNTER_MOVIE)
    except (OSError, RuntimeError, ValueError):
        return None
    return fps if number(fps) and fps > 0 else None


def _dsk_first_rvfc_times(decoder: dict[str, Any]) -> tuple[float, float] | None:
    rv = decoder.get("rv") or []
    rows = [row for row in rv if isinstance(row, (list, tuple)) and len(row) in (3, 4)
            and number(row[0]) and number(row[1])]
    if rows and rows[0][1] == 0:
        rows = rows[1:]
    return (float(rows[0][0]), float(rows[0][1])) if rows else None


def _dsk_decoder_offset(decoder: dict[str, Any]) -> float | None:
    src = decoder.get("src")
    if not isinstance(src, str):
        return None
    for filename, offset in DSK_COUNTER_OFFSETS.items():
        expected = f"{filename}#t={offset:g}" if offset else filename
        if src == expected:
            return offset
    return None


def record_dsk_counter_timing(record: dict[str, Any], arm: Arm) -> None:
    if arm.counter_strip != "distinct":
        return
    first = ((record.get("dump") or {}).get("first") or {})
    holders = first.get("holders") or []
    outgoing = [decoder for decoder in decoders_of(record)
                if decoder.get("region") and decoder.get("detach") is not None]
    bound, _ = bind_holders(holders, outgoing)
    rows = []
    counter_fps = dsk_counter_fps()
    insert = next((row["t"] for row in (record.get("dump") or {}).get("raf") or []
                   if isinstance(row, dict) and "eff" in row), None)
    advance = record.get("advanceAt")
    for index, decoder in bound:
        selected, detail, problems = frame_at_freeze_draw(decoder, counter_fps, advance, insert)
        rows.append({"holderIndex": index, "id": decoder.get("id"),
                     "firstMediaTimeS": (times[1] if (times := _dsk_first_rvfc_times(decoder)) else None),
                     "freezeFrame": selected, "freezeDraw": detail, "freezeDrawProblems": problems})
    cost = score_cost((record.get("dump") or {}).get("takes") or [], record.get("advanceAt"), insert)
    record["dskCounterTiming"] = {"expectedDeltaS": DSK_COUNTER_DELTA_S,
                                  "toleranceS": DSK_COUNTER_TIME_TOLERANCE_S,
                                  "counterFps": counter_fps, "takeMs": cost["detail"].get("takeMs"),
                                  "decoders": rows}


def media_integrity(record: dict[str, Any], images: Mapping[str, np.ndarray], arm: Arm,
                    es: list[float]) -> tuple[dict[str, Any] | None, int | None, list[str]]:
    """Shared media evidence (§9.1) for every outgoing movie: a patch-on arm with holders binds each to a distinct decoder
    (`arm.holders` of them) under `holder_parent`, its strip decoding at device scale (not on `fg` arms, whose layers
    cover the counter blocks by design; their reference is the rVFC record and the requested paused frame); DSK
    distinct-counter holders instead use the VideoFrame timestamp sampled around each native draw, with rVFC rows retained
    as diagnostics; otherwise exactly
    `arm.decoders` detached decoders. Each decoder: colour tuple, geometry, foreground inventory, the last pre-detach rVFC
    record (= the reference; a paused arm's requested frame must equal it), detach inside [advance, transition DOM],
    playback before a patch-off advance; timed captures add >= 3 demixable frames. Returns (first decoder, its reference,
    problems); any problem voids every media check and the arm."""
    first = (record.get("dump") or {}).get("first") or {}
    holders = first.get("holders") or []
    decoders = [d for d in decoders_of(record) if d.get("region")]
    outgoing = [d for d in decoders if d.get("detach") is not None]
    problems: list[str] = []
    needs_holder = arm.mode == "on" and bool(arm.holders)
    pairs: list[tuple[int | None, dict[str, Any]]] = []
    if not needs_holder:
        if arm.mode == "off" and holders:
            problems.append("a holder on the patch-off arm")
        if len(outgoing) != arm.decoders:
            problems.append(f"{len(outgoing)} detached decoders (need exactly {arm.decoders})")
        else:
            pairs = [(None, d) for d in outgoing]
    else:
        bound, bind_problems = bind_holders(holders, decoders)
        problems += bind_problems
        ids = [d.get("id") for _, d in bound]
        if len(holders) != arm.holders or len(bound) != arm.holders or len(set(map(str, ids))) != len(ids):
            problems.append(f"{len(set(map(str, ids)))} distinct bound decoders for {len(holders)} holders (need {arm.holders})")
        parent = holder_parent(first, arm)
        if parent is None or any(h.get("parent") != parent for h in holders):
            problems.append(f"holders {[h.get('parent') for h in holders]} not all in {parent} (from the outgoing texture's ancestry)")
        if not problems:
            pairs = list(bound)
    if not pairs:
        problems.append("no decoder for the outgoing movie")
    reference = None
    decoder_references: dict[Any, int] = {}
    holder_indices: dict[Any, int] = {}
    first_rvfc_times: dict[Any, tuple[float, float]] = {}
    counter_fps = dsk_counter_fps() if arm.counter_strip == "distinct" else None
    if arm.counter_strip == "distinct" and counter_fps is None:
        problems.append("pinned DSK counter frame rate is unavailable")
    insert = next((r["t"] for r in (record.get("dump") or {}).get("raf") or [] if isinstance(r, dict) and "eff" in r), None)
    advance = record.get("advanceAt")
    foreground = record.get("foreground") if isinstance(record.get("foreground"), dict) else {}
    for k, (index, decoder) in enumerate(pairs):
        holder_index = None
        if not isinstance(decoder.get("tuple"), str) or not COLOUR_TUPLE.fullmatch(decoder["tuple"]):
            problems.append(f"decoder colour tuple missing or malformed: {decoder.get('tuple')!r} (an error is not a tuple)")
        inventory = foreground.get(str(decoder.get("id")))
        if not isinstance(inventory, list) or not all(fg_canvas_ok(c) for c in inventory):
            problems.append("no well-formed foreground inventory for the bound decoder")
        content, size = decoder.get("content") or [], decoder.get("size") or []
        if len(content) != 4 or len(size) != 2 or not all(number(v) for v in [*content, *size]) or size[0] <= 0:
            problems.append("decoder geometry malformed")
        elif index is not None and "fg" not in arm.overrides:
            img = images.get(f"holder-{index}")
            if img is None:
                problems.append("holder pixels missing")
            else:
                holder_index = holder_strip(img, holders[index], decoder, arm.dsf)
            if img is not None and holder_index is None:
                geometry = holder_strip_geometry(holders[index], decoder)
                displaced = arm.counter_strip in ("displaced-x", "displaced-y") and geometry == "inside"
                clipped = geometry == "outside" and arm.capture in PAUSED
                if not displaced and not clipped:
                    problems.append("holder pixels missing or the holder strip does not decode at its device scale")
        if not (number(advance) and number(insert) and number(decoder.get("detach")) and advance <= decoder["detach"] <= insert):
            problems.append(f"detach {decoder.get('detach')} not inside [advance {advance}, transition DOM {insert}]")
        before = pre_detach(decoder)
        drawn, _, draw_problems = (frame_at_freeze_draw(decoder, counter_fps, advance, insert)
                                    if arm.counter_strip == "distinct" else (None, {}, []))
        problems += draw_problems
        if not before and arm.counter_strip != "distinct":
            problems.append("no well-formed, ordered rVFC record before the detach")
        if before:
            first_rvfc = _dsk_first_rvfc_times(decoder)
            if first_rvfc is not None:
                first_rvfc_times[decoder.get("id")] = first_rvfc
        decoder_reference = drawn if arm.counter_strip == "distinct" else (
            round(before[-1][1] * FPS) if before else None
        )
        if decoder_reference is not None:
            if k == 0:
                reference = decoder_reference
            if arm.counter_strip == "distinct" and index is not None:
                decoder_references[decoder.get("id")] = decoder_reference
                if holder_index is not None:
                    holder_indices[decoder.get("id")] = holder_index
                if holder_index is not None and holder_index != decoder_reference:
                    problems.append(f"holder {index} frame {holder_index} != decoder {decoder.get('id')} frame {decoder_reference}")
            if arm.mode == "off" and before[-1][2] < MIN_PRESENTED:
                problems.append(f"fewer than {MIN_PRESENTED} presented frames before the advance")
    if arm.counter_strip == "distinct" and (len(decoder_references) != arm.holders
                                             or len(set(decoder_references.values())) != len(decoder_references)):
        problems.append(f"holder decoder frame identities are not distinct: {list(decoder_references.values())}")
    if arm.counter_strip == "distinct":
        timing = record.get("dskCounterTiming")
        rows = timing.get("decoders") if isinstance(timing, dict) else None
        recorded = ({row.get("id"): (row.get("holderIndex"), row.get("freezeFrame")) for row in rows}
                    if isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
                    and len({row.get("id") for row in rows}) == len(rows) else {})
        paired = {decoder.get("id"): (index, decoder_references.get(decoder.get("id")))
                  for index, decoder in pairs}
        if (not isinstance(timing, dict) or timing.get("expectedDeltaS") != DSK_COUNTER_DELTA_S
                or timing.get("toleranceS") != DSK_COUNTER_TIME_TOLERANCE_S
                or timing.get("counterFps") != counter_fps or recorded != paired
                or not isinstance(timing.get("takeMs"), list) or len(timing["takeMs"]) != 1):
            problems.append("DSK draw-timestamp/take-cost record missing or inconsistent")
        offsets = {_dsk_decoder_offset(decoder): decoder.get("id") for _, decoder in pairs}
        if set(offsets) != set(DSK_COUNTER_OFFSETS.values()) or len(offsets) != len(pairs):
            problems.append("DSK decoder sources do not identify the base and #t=5 clips")
        else:
            base_id, offset_id = offsets[0.0], offsets[DSK_COUNTER_DELTA_S]
            if counter_fps is not None and set(holder_indices) == {base_id, offset_id}:
                frame_delta = holder_indices[offset_id] - holder_indices[base_id]
                expected_frames = DSK_COUNTER_DELTA_S * counter_fps
                index_tolerance = round(DSK_COUNTER_TIME_TOLERANCE_S * counter_fps)
                if abs(frame_delta - expected_frames) > index_tolerance:
                    problems.append(f"DSK #t=5 holder frame is not {expected_frames:g} ± "
                                    f"{index_tolerance} after the base holder: "
                                    f"{[holder_indices[base_id], holder_indices[offset_id]]}; first rVFC "
                                    f"presentation/media times: base {first_rvfc_times.get(base_id)}, "
                                    f"#t=5 {first_rvfc_times.get(offset_id)}")
            else:
                problems.append("DSK holder frame indices are missing for the paired decoders")
    if arm.capture in PAUSED:
        requested = (record.get("paused") or {}).get("frame")
        if reference is None or requested != reference:
            problems.append(f"paused reference {reference} != requested frame {requested}")
    if arm.capture not in ("reference", "engage") and demixable(es)[1] < DEMIX_MIN_FRAMES:
        problems.append(f"fewer than {DEMIX_MIN_FRAMES} demixable frames pairwise >= {DEMIX_SPREAD} apart")
    return (pairs[0][1] if pairs else None), reference, list(dict.fromkeys(problems))


def _voided(res: dict[str, Any], problems: list[str]) -> dict[str, Any]:
    return {**res, "verdict": "INCONCLUSIVE", "problems": problems + res["problems"]} if problems else res


def score_media(record: dict[str, Any], images: Mapping[str, np.ndarray], ev: Evidence, arm: Arm, fade: dict[str, Any],
                cal: Calibration, *, identity: bool | None, mask: np.ndarray | None = None) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Frozen frame, frozen region, foreground, tone and overlay (DX-M), each void unless `media_integrity` holds; the
    shared media-integrity problems are returned too, so they reach the arm even when every media check is report-only.
    Tone reads the exposed cells outside the verified production `mask`; its coverage rule is shared integrity."""
    es = [r["e"] for r in fade["rows"]]
    decoder, reference, problems = media_integrity(record, images, arm, es)
    idx, _ = demixable(es)
    frames = [ev.shots[ev.transition[i]] for i in idx]
    demixed = [demix(f, ev.B, es[i]) for f, i in zip(frames, idx)] if ev.B is not None else []
    out: dict[str, dict[str, Any]] = {}
    origin = scale = None
    if decoder is not None and "decoder geometry malformed" not in problems:
        cx, cy, cw, _ = decoder["content"]
        origin, scale = (cx * arm.dsf, cy * arm.dsf), cw * arm.dsf / decoder["size"][0]
    needs_holder = arm.mode == "on" and bool(arm.holders)
    holder_img = images.get("holder-0")
    first_holders = ((record.get("dump") or {}).get("first") or {}).get("holders") or []
    holder_index = (holder_strip(holder_img, first_holders[0], decoder, arm.dsf)
                    if needs_holder and holder_img is not None and first_holders and origin is not None else None)
    strip_geometry = (holder_strip_geometry(first_holders[0], decoder)
                      if needs_holder and first_holders and decoder is not None else None)
    if holder_index is None and strip_geometry == "outside" and arm.capture in PAUSED:
        holder_index = reference
    o_indices = [decode_strip(straight(o), origin, scale) for o in demixed] if origin else []
    out["frozen_frame"] = _voided(score_frozen(holder_index, reference, o_indices, holder=needs_holder), problems)
    if strip_geometry == "outside":
        out["frozen_frame"]["detail"]["strip"] = "strip clipped by geometry"
    region_rect = device_rects([decoder["region"]], arm.dsf)[0] if decoder and decoder.get("region") else None
    region_mask = rect_mask(ev.A.shape[:2], [region_rect]) if region_rect and ev.A is not None else None
    if region_mask is not None and region_mask.any():
        ys, xs = np.where(region_mask)
        crop = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
        region = score_region([o[crop] for o in demixed], [es[i] for i in idx], cal)
    else:
        region = result(None, ["no movie region"])
    out["frozen_region"] = _voided(region, problems)
    overlay = score_overlay(ev.raf, decoder.get("rect") if decoder else None, out["frozen_region"])
    if arm.bridge:
        fade_t = [r["t"] for r in ev.raf if r.get("eff") is not None]
        live_ids = {v["id"] for r in ev.raf if r.get("eff") is not None for v in r.get("videos") or [] if v.get("on") and not v.get("inT")}
        tagged = [v for v in (record.get("dump") or {}).get("vids") or [] if v.get("id") in live_ids
                  and any(fade_t and number(rv[0]) and fade_t[0] <= rv[0] <= fade_t[-1] for rv in v.get("rv") or [])]
        if not tagged:
            overlay = result(None, ["no bridged decoder tagged with rVFC records in the fade"])
    out["overlay"] = _voided(overlay, problems)
    live = images.get("live-0")
    if live is None or not ev.holders or origin is None:
        missing = problems + ["no holder, S_live or decoder geometry"]
        out["foreground"] = result(None, missing)
        out["tone"] = result(None, missing)
        return out, problems
    shape = live.shape[:2]
    later = [c for cs in (record.get("foreground") or {}).values() for c in cs if len(c.get("rect") or []) == 4]
    fg_rects = device_rects([c["rect"] for c in later if c.get("id") in (*FOREGROUND_TEXTURES, FOREGROUND_SQUARE)], arm.dsf)
    fg_mask = block_mask(shape, origin, scale) & rect_mask(shape, fg_rects)
    pair = [r for r in fg_rects if any(overlaps(r, q) for q in fg_rects if q is not r)]
    fg = score_foreground([ev.holders[0], *[straight(o) for o in demixed]], live, fg_mask, cal,
                          demix_es=[es[i] for i in idx] if ev.B is not None else [])
    if not (rect_mask(shape, pair) & fg_mask).any():
        fg = result(None, ["foreground layers do not overlap over the counter blocks"] + fg["problems"])
    out["foreground"] = _voided(fg, problems)
    layout = next(iter((record.get("movies") or {}).values()), {}).get("layout") or {}
    live2 = images.get("live-1")
    if mask is None:
        tone = result(None, ["no verified production mask"])
    else:
        exposed, coverage = tone_coverage(layout, shape, origin, scale, mask)
        if "tone" in arm.expect:
            problems = problems + coverage
        if identity is None:
            tone = result(None, ["no Q0b decision record"])
        elif live2 is None:
            tone = result(None, ["no second S_live"])
        else:
            tone = score_tone(ev.holders[0], live, live2, exposed, identity=identity)
    out["tone"] = _voided(tone, problems)
    return out, problems


def tone_coverage(layout: dict[str, Any], shape: tuple[int, int], origin: tuple[float, float], scale: float,
                  mask: np.ndarray | None) -> tuple[np.ndarray, list[str]]:
    """Exposed tone px (each ramp step / patch eroded `TONE_ERODE` px, outside the verified mask) and the coverage rule:
    a cell counts with >= `TONE_CELL_PX` exposed px; >= `COVERAGE["toneCells"]` of the ramp steps and of the patches."""
    exposed = np.zeros(shape, bool)
    problems = []
    for kind in ("ramp", "patches"):
        cells = layout.get(kind) or []
        counted = 0
        for cell in cells:
            m = source_mask(shape, [cell], origin, scale, erode=TONE_ERODE) & (~mask if mask is not None else True)
            exposed |= m
            counted += int(m.sum()) >= TONE_CELL_PX
        if not cells or counted < COVERAGE["toneCells"] * len(cells):
            problems.append(f"tone coverage: {counted}/{len(cells)} {kind} cells exposed < {COVERAGE['toneCells']:.0%}")
    return exposed, problems


def malformed(expect: Iterable[str], exc: Exception) -> dict[str, Any]:
    problem = f"malformed record: {type(exc).__name__}: {exc}"
    checks = {k: result(None, [problem]) for k in expect}
    return {"outcome": "INCONCLUSIVE", "checks": checks, "mismatch": sorted(checks), "problems": [problem],
            "midResiduals": [], "fitted": []}


COLOUR_TUPLE = re.compile(r"[a-z0-9-]+/[a-z0-9-]+/[a-z0-9-]+/(true|false)")
MALFORMED = (TypeError, ValueError, KeyError, IndexError, AttributeError)


def score_grant(record: dict[str, Any], ev: Any, arm: Arm) -> dict[str, Any]:
    """Grant channel (§3.3): PASS when the host committed `snap` (reason `granted`) and the take bound its holder; FAIL
    when the host recorded no grant with the arm's reason and the take published without a holder; anything else
    (a reason other than the arm's, a holder without a grant, a grant without a holder) INCONCLUSIVE."""
    placement = (record.get("output") or {}).get("placement")
    if not isinstance(placement, dict) or placement.get("reason") != arm.reason:
        return result(None, [f"output.placement {placement} does not carry reason {arm.reason!r}"])
    engaged = score_engaged(record, ev, arm)
    granted = placement.get("grant") == "snap"
    if engaged["verdict"] == "INCONCLUSIVE" or (engaged["verdict"] == "PASS") != granted:
        return result(None, engaged["problems"] + [f"grant {placement.get('grant')!r} with engagement {engaged['verdict']}"])
    return result(granted, holders=engaged["detail"].get("holders", 0))


def score_channel(record: dict[str, Any], arm: Arm) -> dict[str, Any]:
    """`channel-predefined`: the host's round trip fails against a predefined getter, so it reports
    `channel-compromised`, keeps the output hidden and refuses `show` -> FAIL; anything else INCONCLUSIVE."""
    placement = (record.get("output") or {}).get("placement")
    problems = [f"run error: {str(record['error']).strip().splitlines()[-1]}"] if record.get("error") else []
    if not isinstance(placement, dict) or placement.get("reason") != arm.reason or placement.get("grant") is not None:
        problems.append(f"output.placement {placement} is not a refused grant with reason {arm.reason!r}")
    if record.get("showRefused") is not True:
        problems.append(f"show was not refused: {record.get('showRefused')!r}")
    checks = {"grant": result(None if problems else False, problems)}
    outcome = "INCONCLUSIVE" if problems else ("MATCH" if arm.expect.get("grant") == "FAIL" else "MISMATCH")
    return {"outcome": outcome, "checks": checks, "mismatch": [] if outcome != "MISMATCH" else ["grant"], "problems": problems,
            "midResiduals": [], "fitted": []}


def score_arm(record: dict[str, Any], images: Mapping[str, np.ndarray], arm: Arm, cal: Calibration = Calibration(), *,
              identity: bool | None = None, profile: Profile = DX1, twin: tuple[dict[str, Any], Mapping[str, np.ndarray]] | None = None,
              lut: np.ndarray | None = None) -> dict[str, Any]:
    """Every check in the arm's contract; integrity problems, or a record too malformed to read, make each one
    INCONCLUSIVE. `twin` = the arm's same-frame twin run (mask verification); `lut` = its compositing path's `L_path`."""
    try:
        if arm.capture == "channel":
            return score_channel(record, arm)
        return _score_arm(record, images, arm, cal, identity=identity, profile=profile, twin=twin, lut=lut)
    except MALFORMED as exc:
        return malformed(arm.expect, exc)


def verified_mask(record: dict[str, Any], images: Mapping[str, np.ndarray], arm: Arm, profile: Profile, cal: Calibration,
                  twin: tuple[dict[str, Any], Mapping[str, np.ndarray]] | None) -> tuple[np.ndarray | None, list[str]]:
    """The production mask of the arm's one holder, verified against its twin (§9.1); problems are shared integrity."""
    if arm.holders == 0 and arm.expect == {"holder_pixels": "FAIL"}:
        return None, []
    if arm.twin is None:
        return None, (["no twin to verify the production mask"] if {"holder_pixels", "tone", "mask"} & set(arm.expect) else [])
    if twin is None:
        return None, [f"twin {arm.twin} missing"]
    spec = ARMS[arm.twin]
    problems = [f"twin: {p}" for p in capture_problems(twin[0], twin[1], spec, profile, cal) + media_integrity(twin[0], twin[1], spec, [])[2]]
    shape = device_shape(arm)
    holders = ((record.get("dump") or {}).get("first") or {}).get("holders") or []
    bound, bind = bind_holders(holders[:1], [d for d in decoders_of(record) if d.get("region")])
    box = device_box(holders[0]["rect"], arm.dsf) if holders else None
    if not bound or bind or box is None:
        return None, problems + bind + ["no bound holder on the device grid for the production mask"]
    support, found = production_support(record, images, bound[0][1]["id"], shape, arm.dsf, holders[0]["rect"])
    difference, differ = twin_difference(record, images, twin, shape, arm.dsf)
    mask, verify, _ = verify_mask(support, difference, box_mask(shape, box))
    problems += found + differ + verify
    return (None if problems else mask), problems


def _score_arm(record: dict[str, Any], images: Mapping[str, np.ndarray], arm: Arm, cal: Calibration, *,
               identity: bool | None, profile: Profile, twin: tuple[dict[str, Any], Mapping[str, np.ndarray]] | None,
               lut: np.ndarray | None) -> dict[str, Any]:
    problems = capture_problems(record, images, arm, profile, cal)
    ev = evidence(record, images, arm)
    checks: dict[str, dict[str, Any]] = {}
    timed = arm.capture not in ("reference", "engage")
    if timed and ev.A is not None and ev.B is not None:
        fade = _fade_of(ev, arm, cal, profile.mid_frames)
    else:
        fade = {"problems": ["no textures"] if timed else [], "rows": [], "checks": {}}
    problems += fade["problems"] if arm.capture != "cut" else [p for p in fade["problems"] if p.startswith("class ")]
    if media_arm(arm):
        problems += media_integrity(record, images, arm, [r["e"] for r in fade["rows"]])[2]
    if arm.capture == "engage":
        problems += engage_problems(record, ev)
    mask, mask_problems = verified_mask(record, images, arm, profile, cal, twin)
    problems += mask_problems
    for name in ("model", "complement", "no_dip", "screen"):
        if name in arm.expect:
            key = "model" if name == "screen" else name
            checks[name] = result(fade["checks"].get(key), fade["problems"] or ([] if key in fade["checks"] else [f"no {key} evidence"]),
                                  mid=fade.get("mid"))
    if "curve" in arm.expect:
        checks["curve"] = score_curve(ev.raf)
    if "monotone" in arm.expect:
        checks["monotone"] = score_monotone([r["e"] for r in fade["rows"]], profile.mid_frames)
    if "handoff" in arm.expect:
        checks["handoff"] = score_handoff(*_handoff_frames(ev), exclude=ev.destination, cal=cal)
    masks = texture_classes(ev.A, ev.B) if ev.A is not None and ev.B is not None else None
    if "no_flash" in arm.expect:
        window = None
        if arm.capture == "delay":
            start = first_animation_t(ev.raf)
            meta = record.get("shots") or []
            window = [] if masks is None or start is None else [
                float(ev.shots[i][..., 3][masks["in"]].max()) for i in ev.transition if masks["in"].any() and meta[i]["t1"] < start]
        checks["no_flash"] = score_no_flash(ev.raf, window, cal)
    if "cut" in arm.expect:
        cast = []
        for c in record.get("cast") or []:
            img = images.get(c.get("name"))
            ok = masks is not None and img is not None and img.shape[:2] == masks["in"].shape
            cast.append({"t0": c.get("t0", c.get("t")), "t1": c.get("t1", c.get("t")), "in": class_range(img, masks["in"]) if ok else None,
                         "out": class_range(img, masks["out"]) if ok else None})
        checks["cut"] = score_cut(ev.raf, cast, cal)
    if {"holder_pixels", "reference", "mask"} & set(arm.expect):
        holders = ((record.get("dump") or {}).get("first") or {}).get("holders") or []
        box = device_box(holders[0]["rect"], arm.dsf) if holders and quad(holders[0].get("rect")) else None
        live = images.get("live-0")
        if arm.holders == 0 and not holders:
            insert = next((row["t"] for row in ev.raf if row.get("eff") is not None), None)
            refusal_problems = list(score_cost((record.get("dump") or {}).get("takes") or [],
                                               record.get("advanceAt"), insert)["problems"])
            if record.get("placement") != "frac":
                refusal_problems.append(f"page placement {record.get('placement')!r} did not exercise frac")
            checks["holder_pixels"] = result(None if refusal_problems else False, refusal_problems,
                                               alphaRefusal=not refusal_problems)
        else:
            checks["holder_pixels"] = score_holder_pixels(images.get("ref-A0-0"), live, box, mask, lut, cal)
            decoder = next((d for d in decoders_of(record) if d.get("id") == (record.get("paused") or {}).get("id")), None)
            if arm.counter_strip in ("displaced-x", "displaced-y"):
                attribution = score_displaced_holder(
                    images.get("ref-A0-0"), live, holders[0] if holders else None, decoder, record.get("stage"), mask,
                    lut, arm.counter_strip[-1], arm.dsf, cal,
                )
                checks["holder_pixels"]["detail"]["attribution"] = attribution
                if attribution["verdict"] != "PASS":
                    checks["holder_pixels"] = result(
                        None, [f"displaced-holder attribution {attribution['verdict']}: "
                               f"{'; '.join(attribution['problems']) or attribution['detail']!r}"],
                        holderPixels=checks["holder_pixels"], attribution=attribution,
                    )
            if decoder is not None and holders and holder_strip_geometry(holders[0], decoder) == "outside":
                checks["holder_pixels"]["detail"]["strip"] = "strip clipped by geometry"
        checks["reference"] = score_perfect(images.get("ref-perfect-0"), live, box, cal)
        checks["mask"] = result(mask is not None, [] if mask is not None else ["production mask not verified"])
    for name in ("geometry", "exterior", "scope"):
        if name in arm.expect:
            checks[name] = score_engaged(record, ev, arm)
    if "grant" in arm.expect:
        checks["grant"] = score_grant(record, ev, arm)
    if set(MEDIA_CHECKS) & set(arm.expect):
        media, shared = score_media(record, images, ev, arm, fade, cal, identity=identity, mask=mask)
        checks.update({k: v for k, v in media.items() if k in arm.expect})
        problems += [p for p in shared if p not in problems]
    if "cost" in arm.expect:
        insert = next((r["t"] for r in ev.raf if r.get("eff") is not None), None)
        checks["cost"] = score_cost((record.get("dump") or {}).get("takes") or [], record.get("advanceAt"), insert)
    problems = list(dict.fromkeys(problems))
    checks = {k: v for k, v in checks.items() if k in arm.expect}
    for name, expected in arm.expect.items():
        if expected == "N/A":
            checks[name] = result(None)
        elif expected == "REPORTED" and name in checks and checks[name]["verdict"] in ("PASS", "FAIL"):
            checks[name] = {**checks[name], "verdict": "REPORTED", "detail": {**checks[name]["detail"], "outcome": checks[name]["verdict"]}}
    if problems:
        checks = {k: {**v, "verdict": "INCONCLUSIVE" if v["verdict"] != "N/A" else "N/A", "problems": problems + v["problems"]}
                  for k, v in checks.items()}
    blocking = [k for k, want in arm.expect.items() if want not in ("REPORTED", "N/A")]
    mismatch = sorted(k for k in blocking if checks.get(k, {}).get("verdict") != arm.expect[k])
    inconclusive = bool(problems) or any(checks.get(k, {}).get("verdict", "INCONCLUSIVE") == "INCONCLUSIVE" for k in blocking)
    outcome = "INCONCLUSIVE" if inconclusive else ("MATCH" if not mismatch else "MISMATCH")
    return {"outcome": outcome, "checks": checks, "mismatch": mismatch, "problems": problems,
            "midResiduals": [r["residual"] for r in fade["rows"] if number(r["e"]) and MID_E[0] < r["e"] < MID_E[1]],
            "fitted": [(r["e"], i) for r, i in zip(fade["rows"], ev.transition)]}


def score_settled(run: np.ndarray | None, twin: np.ndarray | None, exclude: list[Iterable[float]], cal: Calibration) -> dict[str, Any]:
    if run is None or twin is None or run.shape != twin.shape:
        return result(None, ["settled frame of run or twin missing"])
    keep = ~rect_mask(run.shape[:2], exclude, MEDIA_PAD_PX)
    if not keep.any():
        return result(None, ["no settled pixel outside the media rects"])
    diff = float(np.abs(premul(run) - premul(twin))[keep].max())
    return result(diff <= cal.tau, diff=diff)


def score_cleanup(residue: Any) -> dict[str, Any]:
    keys = ("layers", "rules", "holders")
    if not isinstance(residue, dict) or not all(isinstance(residue.get(k), int) and not isinstance(residue.get(k), bool) for k in keys):
        return result(None, [f"residue malformed: {residue}"])
    return result(not any(residue[k] for k in keys), residue=residue)


def score_lifecycle(record: dict[str, Any], images: Mapping[str, np.ndarray], twin: tuple[dict[str, Any], Mapping[str, np.ndarray]] | None,
                    arm: Arm, cal: Calibration = Calibration(), profile: Profile = DX1) -> dict[str, Any]:
    """One lifecycle row against its fully validated stock twin (§9.1 lifecycle scenario); unreadable -> INCONCLUSIVE."""
    try:
        return _score_lifecycle(record, images, twin, arm, cal, profile)
    except MALFORMED as exc:
        return malformed(("settled", "destination", "cleanup", "complement", "no_flash"), exc)


def _score_lifecycle(record: dict[str, Any], images: Mapping[str, np.ndarray], twin: tuple[dict[str, Any], Mapping[str, np.ndarray]] | None,
                     arm: Arm, cal: Calibration, profile: Profile) -> dict[str, Any]:
    row = arm.row or ""
    spec = LIFECYCLE.get(row, {})
    problems = capture_problems(record, images, arm, profile)
    if twin is None:
        problems.append("stock twin missing")
    else:
        problems += [f"twin: {p}" for p in capture_problems(twin[0], twin[1], ARMS[arm.twin or ""], profile)]
    problems += action_problems(record, spec)
    if twin is not None:
        problems += [f"twin: {p}" for p in action_problems(twin[0], spec)]
    if spec.get("replay") and not (record.get("pre") or {}).get("first"):
        problems.append("replay: no first-pass capture")
    if spec.get("end") and record.get("residueAfterGoto") is None:
        problems.append("end of show: no residue after go-to 1")
    ev = evidence(record, images, arm)
    first = (record.get("dump") or {}).get("first") or {}
    checks: dict[str, dict[str, Any]] = {}
    exclude = ev.destination + (media_rects(twin[0], arm.dsf) if twin else [])
    checks["settled"] = score_settled(images.get("settled"), twin[1].get("settled") if twin else None, exclude, cal)
    hashes = (record.get("hashAfter"), twin[0].get("hashAfter") if twin else None)
    checks["destination"] = result(hashes[0] == hashes[1], [] if all(isinstance(h, str) for h in hashes) else ["destination hash missing"],
                                   hash=hashes[0], twin=hashes[1])
    ids = first.get("layerIds")
    if isinstance(ids, list) and ids and len(set(map(str, ids))) == len(ids) and all(isinstance(i, str) and re.match(r"layer\d+", i) for i in ids):
        checks["cleanup"] = score_cleanup(record.get("residueAfterGoto") if spec.get("end") else record.get("residue"))
    else:
        checks["cleanup"] = result(None, ["no valid transition layer-id inventory to bind the cleanup to"])
    if row in ("advance", "replay", "automatic", "loop-wrap"):
        checks["holder"] = result(len(first.get("holders") or []) == 1, holders=len(first.get("holders") or []))
    if row == "replay":
        pre = ((record.get("pre") or {}).get("first")) or {}
        fresh = bool(pre.get("layerIds")) and not set(pre["layerIds"]) & set(first.get("layerIds") or [])
        checks["fresh"] = result(fresh and len(pre.get("holders") or []) == 1, preIds=pre.get("layerIds"), ids=first.get("layerIds"))
    meta = record.get("shots") or []
    actions = {a["name"]: a["t"] for a in record.get("actions") or [] if number(a.get("t"))}
    hidden: list[int] = []
    if row.startswith("hide"):
        hidden = [i for i, s in enumerate(meta) if "hide" in actions and "show" in actions
                  and actions["hide"] + RAF_SLACK_MS <= s["t0"] and s["t1"] <= actions["show"]]
        hide, shared = hide_checks(record, images, ev, arm, cal)
        checks.update(hide)
        problems += [p for p in shared if p not in problems]
    straddle = [i for i, s in enumerate(meta) if "hide" in actions and "show" in actions
                and s["t1"] >= actions["hide"] and s["t0"] - RAF_SLACK_MS <= actions["show"]]
    visible = [i for i in ev.transition if i not in hidden and i not in straddle]
    if ev.A is not None and ev.B is not None:
        fade = score_fade([ev.shots[i] for i in visible], ev.A, ev.B, exclude=ev.media, classes=("out", "in"), cal=cal,
                          screen=arm.page == "screen", min_frames=COVERAGE["midFrames"])
        if arm.page == "screen":
            checks["model"] = result(fade["checks"].get("model"), fade["problems"])
        else:
            checks["complement"] = result(fade["checks"].get("complement"), fade["problems"] or
                                          ([] if "complement" in fade["checks"] else ["no complement evidence"]))
        if row == "automatic":
            auto = replace(arm, holders=1, capture="media")
            frozen, shared = score_media(record, images, ev, auto, fade, cal, identity=None)
            checks["frozen_frame"] = frozen["frozen_frame"]
            problems += [p for p in shared if p not in problems]
            checks["frozen_delay"] = score_delay_freeze(record, images, ev, auto, [r["e"] for r in fade["rows"]])
    else:
        checks["complement"] = result(None, ["no textures"])
    checks["no_flash"] = score_no_flash(ev.raf, None, cal)
    if problems:
        checks = {k: {**v, "verdict": "INCONCLUSIVE", "problems": problems + v["problems"]} for k, v in checks.items()}
    verdicts = [c["verdict"] for c in checks.values()]
    outcome = "INCONCLUSIVE" if "INCONCLUSIVE" in verdicts else ("MATCH" if all(v == "PASS" for v in verdicts) else "MISMATCH")
    return {"outcome": outcome, "checks": checks, "problems": problems}


def hide_checks(record: dict[str, Any], images: Mapping[str, np.ndarray], ev: Evidence, arm: Arm,
                cal: Calibration) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """`score_hide` on the run's timestamped screencast (a dropped action keeps its recorded time)."""
    cast = [{"t": c.get("t"), "img": images[c["name"]]} for c in record.get("cast") or [] if c.get("name") in images]
    if len(cast) != len(record.get("cast") or []):
        problem = ["screencast frame pixels missing"]
        return {k: result(None, problem) for k in ("hidden", "shown", "after_show")}, problem
    actions = {a["name"]: a["t"] for a in record.get("actions") or [] if isinstance(a, dict) and number(a.get("t"))}
    return score_hide(cast, actions, ev.raf, screen=arm.page == "screen", A=ev.A, B=ev.B, exclude=ev.media, cal=cal)


def score_hide_capture(record: dict[str, Any], images: Mapping[str, np.ndarray], arm: Arm, cal: Calibration = Calibration(),
                       profile: Profile = DX1) -> dict[str, Any]:
    """A hide-capture control scored on its own (§9 Hide / show): the stock twins (hidden, shown -> PASS) and the
    dropped-action arms (`life-hide-nohide` hidden -> FAIL, `life-hide-noshow` shown -> FAIL)."""
    try:
        problems = capture_problems(record, images, arm, profile, cal) + action_problems(record, LIFECYCLE[arm.row or ""])
        hide, shared = hide_checks(record, images, evidence(record, images, arm), arm, cal)
    except MALFORMED as exc:
        return malformed(arm.expect, exc)
    problems += [p for p in shared if p not in problems]
    checks = {k: hide[k] for k in arm.expect}
    if problems:
        checks = {k: {**v, "verdict": "INCONCLUSIVE", "problems": problems + v["problems"]} for k, v in checks.items()}
    verdicts = {k: c["verdict"] for k, c in checks.items()}
    outcome = ("INCONCLUSIVE" if "INCONCLUSIVE" in verdicts.values() else
               "MATCH" if verdicts == dict(arm.expect) else "MISMATCH")
    return {"outcome": outcome, "checks": checks, "problems": problems}


def action_problems(record: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    """The row's timed actions recorded in order, strictly later each, after the advance and inside the transition."""
    want = [name for _, name in spec.get("actions", ())]
    if not want:
        return []
    acts = record.get("actions")
    if not isinstance(acts, list) or not all(isinstance(a, dict) and isinstance(a.get("name"), str) and number(a.get("t")) for a in acts):
        return ["actions missing or malformed"]
    got = [a for a in acts if a["name"] in want]
    raf = [r for r in (record.get("dump") or {}).get("raf") or [] if isinstance(r, dict) and "eff" in r and number(r.get("t"))]
    advance = record.get("advanceAt")
    problems = []
    if [a["name"] for a in got] != want:
        problems.append(f"actions {[a['name'] for a in got]} != {want}")
    elif any(b["t"] <= a["t"] for a, b in zip(got, got[1:])):
        problems.append("actions out of order")
    elif not raf or not number(advance) or not all(advance <= a["t"] and raf[0]["t"] <= a["t"] <= raf[-1]["t"] + RAF_SLACK_MS for a in got):
        problems.append("an action lies outside [advance, transition DOM]")
    return problems


def score_delay_freeze(record: dict[str, Any], images: Mapping[str, np.ndarray], ev: Evidence, arm: Arm, es: list[float]) -> dict[str, Any]:
    """Through an automatic event's delay (transition DOM present, no animation yet) the movie region decodes to the
    frozen reference in every screenshot; no screenshot in the delay is INCONCLUSIVE."""
    decoder, reference, problems = media_integrity(record, images, arm, es)
    start = first_animation_t(ev.raf)
    meta = record.get("shots") or []
    window = [i for i in ev.transition if start is not None and meta[i]["t1"] < start]
    if len(window) < COVERAGE["delayShots"]:
        problems = problems + [f"{len(window)} screenshots inside the delay < {COVERAGE['delayShots']}"]
    if problems or decoder is None:
        return result(None, problems or ["no decoder"])
    cx, cy, cw, _ = decoder["content"]
    seen = [decode_strip(ev.shots[i], (cx * arm.dsf, cy * arm.dsf), cw * arm.dsf / decoder["size"][0]) for i in window]
    return result(all(v == reference for v in seen), reference=reference, delay=seen)


def _reference_case(variant: str, cal: Calibration) -> dict[str, Any]:
    """A 60x40 reference capture (A red, B blue): valid, a reused (stale) F50, an extra running animation, an unpaused one."""
    from types import SimpleNamespace

    arm = Arm("p2bin", 2, capture="reference", viewport=(60, 40))
    A = np.zeros((40, 60, 4), np.uint8)
    A[...] = (200, 40, 30, 255)
    B = A.copy()
    B[...] = (20, 90, 150, 255)
    F50 = np.rint((A.astype(float) + B) / 2).astype(np.uint8)
    pictures = {"F50": F50, "B": B, "A0": A, "perfect": A}
    if variant == "stale":
        pictures["F50"] = A
    images = {f"ref-{k}-{j}": v.copy() for k, v in pictures.items() for j in range(2)}
    targets = ("layer3-opacity", "layer4-opacity")
    inventory = [{"target": t, "leaf": leaf, "state": "running"} for t, leaf in zip(targets, ("in", "out"))]
    if variant == "extra":
        inventory.append({"target": "layer9", "leaf": None, "state": "running"})
    effs = {"F50": [0.5, 0.5], "B": [0.9995, 0.0005], "A0": [0.0, 1.0]}
    states = [{"label": label, "f": f, "t": 10.0 * (k + 1), "dom": True, "eff": effs[label], "shots": [f"ref-{label}-0", f"ref-{label}-1"],
               "anims": [{"target": t, "state": "running" if variant == "unpaused" and label == "F50" else "paused", "ct": f * 1500.0,
                          "dur": 1500.0} for t in targets]} for k, (label, f) in enumerate(REF_STATES)]
    record = {"reference": {"inventory": inventory, "states": states,
                            "timers": {"minMs": TIMER_MIN_MS, "extraMs": TIMER_EXTRA_MS, "delayedMs": [1500.0]},
                            "perfect": {"shift": 0, "rect": [0, 0, 60, 40], "dom": True, "t": 50.0, "shots": ["ref-perfect-0", "ref-perfect-1"]}},
              "dump": {"first": {"layerIds": ["layer2", *targets], "holders": [{"rect": [0, 0, 60, 40], "canvasRect": [0, 0, 60, 40]}]}},
              "advanceAt": 1.0}
    return result(True, reference_problems(record, images, arm, SimpleNamespace(A=A, B=B), cal))


def _mask_case(variant: str) -> dict[str, Any]:
    """A 30x20 holder region with a 4x12 foreground: the production support, the whole region, a 3-px shift, empty."""
    shape, box = (20, 30), (2, 2, 28, 18)
    difference = np.zeros(shape, bool)
    difference[8:12, 10:22] = True
    support = {"production": difference.copy(), "whole": box_mask(shape, box), "shift3": np.roll(difference, 3, axis=1),
               "empty": np.zeros(shape, bool)}[variant]
    _, problems, detail = verify_mask(support, difference, box_mask(shape, box))
    return result(True, problems, **detail)


def _holder_shift_case(cal: Calibration) -> dict[str, Any]:
    live = np.zeros((12, 16, 4), np.uint8)
    live[..., 3] = 255
    live[..., :3] = (np.arange(16) % 4 * 40)[None, :, None]
    shifted = live.copy()
    shifted[2:10, 3:14] = live[2:10, 2:13]
    mask = np.zeros((12, 16), bool)
    mask[2:4, 2:4] = True
    return score_holder_pixels(shifted, live, (2, 2, 14, 10), mask, np.arange(256), cal)


def _hide_case(variant: str) -> dict[str, Any]:
    """A 50x50 outgoing-only world (A opaque, B transparent), rAFs and screencast frames every 40 ms, progress
    0.06..0.94, frames at α = (1 − e)·255; hide at 40, show at 120: dark between; a duplicated last frame, or one
    frame's timestamp 20 ms off its rAF."""
    A = np.zeros((50, 50, 4), np.uint8)
    A[...] = (200, 40, 30, 255)
    B = np.zeros_like(A)
    raf = [{"t": 40.0 * k, "eff": [0.06 + 0.044 * k, 0.94 - 0.044 * k], "anims": []} for k in range(21)]
    cast = []
    for k in range(1, 20):
        img = A.copy()
        img[..., 3] = 0 if 40 < 40 * k <= 120 else round((0.94 - 0.044 * k) * 255)
        cast.append({"t": 40.0 * k, "img": img})
    if variant == "duplicate":
        cast[-1]["img"] = cast[-2]["img"].copy()
    if variant == "shift":
        cast[8]["t"] += 20.0
    checks, _ = score_hide(cast, {"hide": 40.0, "show": 120.0}, raf, screen=False, A=A, B=B)
    parts = [checks["hidden"], checks["shown"]]
    return result(all(c["verdict"] == "PASS" for c in parts), [p for c in parts for p in c["problems"]])


def scorer_cases(cal: Calibration = Calibration()) -> dict[str, dict[str, Any]]:
    """Synthetic scorer controls named in §9's control table and the CvC/lifecycle gates, scored with the calibration."""
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
    clean = {"layers": 0, "rules": 0, "holders": 0}
    return {
        "case:curve-linear": score_curve(linear),
        "case:monotone-dip": score_monotone([0.06, 0.2, 0.4, 0.3, 0.7, 0.9, 1.0]),
        "case:handoff-unchanged": score_handoff(flat, flat.copy(), cal=cal),
        "case:handoff-step": score_handoff(flat, step, cal=cal),
        "case:cut-complementary": score_cut(cut, [{"t0": 16.0, "t1": 16.0, "in": (127.5, 127.5), "out": (127.5, 127.5)}], cal),
        "case:fg-shifted": score_foreground([shifted], live, mask, cal),
        "case:fg-double": score_foreground([double], live, mask, cal),
        "case:fg-swapped": score_foreground([swapped], live, mask, cal),
        "case:cost-50": score_cost([[1.0, COST_MS]], 0.0, 2.0),
        "case:cost-50-eps": score_cost([[1.0, COST_MS + 1e-6]], 0.0, 2.0),
        "case:cvc-same": score_cvc([1.2, 1.3, 1.5], [1.2, 1.3, 1.5]),
        "case:cvc-shifted": score_cvc([1.2, 1.3, 1.5], [2.4, 2.5, 2.7]),
        "case:settled-same": score_settled(flat, flat.copy(), [], cal),
        "case:settled-step": score_settled(flat, step, [], cal),
        "case:cleanup-clean": score_cleanup(clean),
        "case:cleanup-residue": score_cleanup({**clean, "rules": 2}),
        "case:holder-shift": _holder_shift_case(cal),
        **{f"case:reference-{v}": _reference_case(v, cal) for v in ("valid", "stale", "extra", "unpaused")},
        **{f"case:mask-{v}": _mask_case(v) for v in ("production", "whole", "shift3", "empty")},
        **{f"case:hide-{v}": _hide_case(v) for v in ("valid", "duplicate", "shift")},
    }


EXTRA_CONTROLS = {"cvc": (("case:cvc-same",), ("case:cvc-shifted",)),
                  "lifecycle": (("case:settled-same", "case:cleanup-clean"), ("case:settled-step", "case:cleanup-residue"))}


def score_round(scored: dict[str, dict[str, Any]], cal: Calibration = Calibration(), *, identity: bool | None = None,
                extra: dict[str, dict[str, Any]] | None = None, profile: Profile = DX1) -> dict[str, Any]:
    """Every arm the profile requires must be present. Per gated check every control is read first (complete capture,
    positive PASS, negative FAIL; anything else invalidates); only then do the candidates (other arms expecting PASS)
    count. The CvC and (DX-1) lifecycle gates have scorer-case controls; their candidates are required too."""
    extra = extra or {}
    cases = scorer_cases(cal)
    missing = [n for n in profile.required(identity) if n not in scored]
    gates: dict[str, Any] = {}

    def read(controls: tuple[tuple[str, ...], ...], check: str) -> list[str]:
        reasons = []
        for name, want in [(n, v) for names, v in zip(controls, ("PASS", "FAIL", "INCONCLUSIVE")) for n in names]:
            if want == "INCONCLUSIVE" and name not in cases:
                reasons.append(f"control {name}: only scorer cases may be INCONCLUSIVE controls")
                continue
            if name in cases:
                got = cases[name]["verdict"]
            else:
                arm = scored.get(name) or {}
                if arm.get("problems") or arm.get("outcome") != "MATCH":
                    reasons.append(f"control {name}: {arm.get('outcome') or 'missing'} (its whole contract must match)")
                    continue
                got = (arm.get("checks") or {}).get(check, {}).get("verdict")
            if got != want:
                reasons.append(f"control {name}: {got or 'missing'} (must {want})")
        return reasons

    for check, controls in profile.controls().items():
        if check == "tone" and identity is not False:
            gates[check] = {"verdict": "REPORTED", "reasons": ["identity L or no decision record: tone is report-only"]}
            continue
        reasons = read(controls, check)
        candidates = {n: s["checks"].get(check, {}).get("verdict") for n, s in scored.items()
                      if n not in sum(controls, ()) and n in ARMS and profile.arm(n, identity).expect.get(check) == "PASS"}
        verdict = "INCONCLUSIVE" if reasons or any(v not in ("PASS", "FAIL") for v in candidates.values()) else (
            "FAIL" if "FAIL" in candidates.values() else "PASS")
        gates[check] = {"verdict": verdict, "reasons": reasons, "candidates": candidates}
    for check in profile.not_run:
        gates[check] = {"verdict": "NOT RUN", "reasons": [f"{profile.name} does not run this family"], "candidates": {}}
    blocking = {"cvc": {"cvc": (extra.get("cvc") or {}).get("verdict")}}
    if profile.lifecycle:
        blocking["lifecycle"] = {n: {"MATCH": "PASS", "MISMATCH": "FAIL"}.get(s["outcome"], "INCONCLUSIVE")
                                 for n, s in scored.items() if n in ARMS and ARMS[n].row is not None and ARMS[n].twin is not None}
        if not blocking["lifecycle"]:
            blocking["lifecycle"] = {"rows": None}
    for check, candidates in blocking.items():
        reasons = read(EXTRA_CONTROLS[check], check)
        verdict = "INCONCLUSIVE" if reasons or any(v not in ("PASS", "FAIL") for v in candidates.values()) else (
            "FAIL" if "FAIL" in candidates.values() else "PASS")
        gates[check] = {"verdict": verdict, "reasons": reasons, "candidates": candidates}
    gates.update({k: v for k, v in extra.items() if k not in gates})
    arms = {n: s["outcome"] for n, s in scored.items()}
    verdicts = [g["verdict"] for g in gates.values() if g["verdict"] in ("PASS", "FAIL", "INCONCLUSIVE")]
    verdicts += ["FAIL" if o == "MISMATCH" else "INCONCLUSIVE" for o in arms.values() if o != "MATCH"]
    if missing:
        verdicts.append("INCONCLUSIVE")
    coverage = profile_coverage_problems(profile) if profile in CEF_PLACEMENT_DEV_PROFILES.values() else []
    if coverage:
        verdicts.append("INCONCLUSIVE")
    overall = next((v for v in ("FAIL", "INCONCLUSIVE") if v in verdicts), "PASS" if verdicts else "INCONCLUSIVE")
    return {"overall": overall, "gates": gates, "arms": arms, "missing": sorted(set(missing)),
            "profile": profile.name, "coverageProblems": coverage}


def decode_rgba(data: str | bytes) -> np.ndarray:
    raw = base64.b64decode(data.split(",", 1)[1] if isinstance(data, str) and data.startswith("data:") else data)
    return np.asarray(Image.open(io.BytesIO(raw)).convert("RGBA"))


def pending_scene(snapshot: dict[str, Any] | None) -> int | None:
    if not snapshot or not snapshot.get("ready"):
        return None
    return snapshot.get("scene") if snapshot.get("state") == "IdleAtInitialState" else snapshot.get("next")


def measure_placement_probe(*, spec: placement_probe.ProbeSpec, identity: placement_probe.ProbeIdentity,
                            evaluate: Callable[[str], Any], capture_png: Callable[[], bytes],
                            check_current: Callable[[], None] = lambda: None,
                            clock: Callable[[], float] = time.monotonic,
                            sleep: Callable[[float], None] = time.sleep) -> placement_probe.ClassifierInput:
    """Drive §11.1's page API for the Chrome harness."""
    assets = placement_probe.load_probe_assets()
    sequence = 0
    previous_start: float | None = None
    freshness: list[placement_probe.ProbeCapture] = []
    captures: list[placement_probe.ProbeCapture] = []
    poses: dict[int, placement_probe.PoseGeometry] = {}
    last_snapshot: dict[str, Any] | None = None
    deadline = clock() + 15.0

    def one(phase: str, pose: int | None) -> placement_probe.ProbeCapture:
        nonlocal sequence, previous_start, last_snapshot
        sequence += 1
        nonce = secrets.token_hex(16)
        command = {"runId": spec.run_id, "sequence": sequence, "nonce": nonce, "phase": phase, "pose": pose}
        if evaluate(f"window.__obedProbe.command({json.dumps(command, separators=(',', ':'))})") is not True:
            raise RuntimeError(f"probe page rejected sequence {sequence}")
        while True:
            check_current()
            if clock() >= deadline:
                raise TimeoutError("placement probe exceeded 15 seconds")
            snapshot = evaluate("window.__obedProbe.snapshot()")
            if (isinstance(snapshot, dict) and snapshot.get("runId") == spec.run_id
                    and snapshot.get("sequence") == sequence and snapshot.get("paintedSequence") == sequence
                    and snapshot.get("phase") == phase and snapshot.get("pose") == pose):
                last_snapshot = snapshot
                break
            sleep(0.01)
        observed = clock()
        start_not_before = max(observed + 0.3, (previous_start + 0.2) if previous_start is not None else observed)
        sleep(max(0.0, start_not_before - clock()))
        check_current()
        started = clock()
        png = capture_png()
        finished = clock()
        if finished - started > 2.0:
            raise TimeoutError(f"placement capture {sequence} exceeded 2 seconds")
        previous_start = started
        return placement_probe.ProbeCapture(identity=identity, sequence=sequence, nonce=nonce, phase=phase, pose=pose, png=png,
                                            paint_observed_s=observed, capture_started_s=started, capture_finished_s=finished)

    for _ in range(3):
        freshness.append(one("motion", None))
    for pose in (0, 1):
        for _ in range(2):
            captures.append(one("pattern", pose))
        geometry = (last_snapshot or {}).get("geometry")
        if not isinstance(geometry, dict):
            raise RuntimeError(f"probe pose {pose} did not publish geometry")
        poses[pose] = placement_probe.PoseGeometry(
            pose=geometry["pose"], rect=tuple(geometry["rect"]), content_box=tuple(geometry["contentBox"]),
            box=tuple(geometry["box"]), snap_dy=geometry["snapDy"], frac_dy=geometry["fracDy"])
    if last_snapshot is None:
        raise RuntimeError("probe page published no snapshot")
    return placement_probe.ClassifierInput(
        spec=spec, assets_sha256=(assets.manifest_sha256, assets.pattern.sha256, assets.motion.sha256), identity=identity,
        ready_state=last_snapshot["readyState"], video_size=tuple(last_snapshot["videoSize"]),
        color_tuple=tuple(last_snapshot["colorTuple"]), freshness=tuple(freshness), poses=(poses[0], poses[1]),
        captures=tuple(captures),
    )


def run_chrome_placement_probe(*, gpu: bool) -> dict[str, Any]:
    from obed_edom.live_host import ChromeCdp, _AssetServer

    profile = Path(tempfile.mkdtemp(prefix="placement-chrome-"))
    proc = transport = server = None
    try:
        spec = placement_probe.ProbeSpec(secrets.token_hex(16), 1920, 1080, 60, 1.0)
        server = _AssetServer(REPO, b"")
        server.start()
        url = server.set_probe_run(spec)
        if url is None:
            raise RuntimeError("probe server did not publish a URL")
        proc, port, args = start_chrome(profile, gpu=gpu, viewport=(1920, 1080), dsf=1.0)
        transport = ChromeCdp(CHROME, profile, None, headless=True, attach_endpoint=f"http://127.0.0.1:{port}")
        transport.start()
        transport.call("Emulation.setDeviceMetricsOverride", width=1920, height=1080, deviceScaleFactor=1, mobile=False)
        transport.goto(url)
        deadline = time.monotonic() + 10.0
        snapshot = None
        while time.monotonic() < deadline:
            snapshot = transport.evaluate("window.__obedProbe&&window.__obedProbe.snapshot?window.__obedProbe.snapshot():null")
            if isinstance(snapshot, dict):
                break
            time.sleep(0.05)
        frame = transport.call("Page.getFrameTree")["frameTree"]["frame"]["id"]
        context = transport.main_context(frame)
        context_id = context.get("uniqueId") if isinstance(context, dict) else None
        target_id = getattr(transport, "target_id", None)
        if not isinstance(context_id, str) or not isinstance(target_id, str):
            raise RuntimeError("Chrome probe identity is unavailable")
        identity = placement_probe.ProbeIdentity(spec.run_id, None, target_id, context_id, 0,
                                                  str(transport.evaluate("navigator.userAgent")),
                                                  float(transport.evaluate("window.devicePixelRatio")))

        def capture() -> bytes:
            encoded = transport.call("Page.captureScreenshot", format="png", fromSurface=True)["data"]
            return base64.b64decode(encoded, validate=True)

        evidence = measure_placement_probe(spec=spec, identity=identity, evaluate=transport.evaluate, capture_png=capture)
        result = placement_probe.classify_probe(evidence)
        return {"input": evidence, "classification": result,
                "launch": {"gpu": gpu, "chromeArgs": args[1:], "runId": spec.run_id},
                "toneRows": {"complete": False, "observed": result.tone_map.value if result.tone_map else None,
                             "applied": "identity", "problems": ["extended W5 ramp/patch/skin rows not captured"]}}
    finally:
        if transport is not None:
            with contextlib.suppress(Exception):
                transport.stop()
        if proc is not None and proc.poll() is None:
            proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=8)
            if proc.poll() is None:
                proc.kill()
        if server is not None and server.httpd is not None:
            server.httpd.shutdown()
        shutil.rmtree(profile, ignore_errors=True)


def wait_ready(evaluate: Callable[[str], Any], timeout_s: float = 30.0, snapshot_js: str = SNAPSHOT_JS) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        snap = evaluate(snapshot_js)
        if snap and snap.get("ready"):
            return snap
        time.sleep(0.05)
    raise RuntimeError("player never became ready")


def navigate(host: Any, scene: int, limit: int, *, deadline: float | None = None) -> int:
    """Advance until the next advance plays `scene`."""
    evaluate = host._require_transport().evaluate
    advances = 0
    for _ in range(limit + 1):
        timeout = 30.0 if deadline is None else max(0.0, deadline - time.monotonic())
        snap = wait_ready(evaluate, timeout_s=timeout, snapshot_js=getattr(host, "snapshot_js", SNAPSHOT_JS))
        if pending_scene(snap) == scene:
            return advances
        host.execute("advance")
        advances += 1
        if hasattr(host, "await_advance"):
            host.await_advance(snap)
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


def evaluate_async(transport: Any, expression: str, deadline_s: float = 30.0) -> Any:
    result = transport.call("Runtime.evaluate", deadline_s=deadline_s, expression=expression, returnByValue=True, awaitPromise=True)
    if result.get("exceptionDetails"):
        raise RuntimeError(f"page evaluation failed: {json.dumps(result['exceptionDetails'])[:400]}")
    return (result.get("result") or {}).get("value")


def collect(evaluate: Callable[..., Any], record: dict[str, Any], images: dict[str, np.ndarray], tag: str = "") -> None:
    """Disarm the hook and add its dump, textures and holder pixels to the run."""
    evaluate("window.__obedDx.disarm()")
    record["dump"] = evaluate("window.__obedDx.dump()", deadline_s=60)
    pictures = evaluate("window.__obedDx.images()", deadline_s=120) or {}
    for key, png in zip(("tex-in", "tex-out"), pictures.get("tex") or []):
        if png:
            images[tag + key] = decode_rgba(png)
    for i, png in enumerate(pictures.get("holders") or []):
        if png:
            images[f"{tag}holder-{i}"] = decode_rgba(png)


def reference_burst(host: Any, target: dict[str, Any], capture: Callable[[], np.ndarray], live: np.ndarray,
                    shift: int = 0) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """§9.1 reference-capture profile: at the first transition rAF the animation inventory; every document animation
    paused and seeked to each `REF_STATES` fraction of its duration, read back and screenshotted twice; then the holder
    canvas overwritten with `live`'s own device pixels (`shift` px right) and screenshotted twice; then finished. Page
    timers of >= `TIMER_MIN_MS` set from just before the advance are held back by `TIMER_EXTRA_MS` (the player's
    end-of-transition teardown would otherwise remove the transition DOM before `perfect` at DPR 2) and released, and
    recorded, after the finish."""
    transport = host._require_transport()
    evaluate = transport.evaluate
    origin = evaluate(f"window.__obedDx.arm({json.dumps(target['textures'])})")["timeOrigin"]

    def now() -> float:
        return time.time() * 1000.0 - origin

    evaluate(f"window.__obedDx.delay({TIMER_MIN_MS}, {TIMER_EXTRA_MS})")
    record: dict[str, Any] = {"shots": [], "actions": [], "cast": [], "advanceAt": now()}
    images: dict[str, np.ndarray] = {}
    errors: list[str] = []

    def advance() -> None:
        try:
            host.execute("advance")
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    thread = threading.Thread(target=advance, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not evaluate("window.__obedDx.ready()"):
        time.sleep(0.005)
    ref: dict[str, Any] = {"inventory": evaluate("window.__obedDx.inventory()"), "states": []}
    for label, f in REF_STATES:
        state = evaluate_async(transport, f"window.__obedDx.seek({f})") or {}
        state.update(label=label, f=f, t=now(), shots=[])
        for j in range(2):
            images[f"ref-{label}-{j}"] = capture()
            state["shots"].append(f"ref-{label}-{j}")
        ref["states"].append(state)
    rect = evaluate("window.__obedDx.holderRect()")
    perfect: dict[str, Any] = {"shift": shift, "rect": rect, "shots": []}
    if rect:
        buf = io.BytesIO()
        Image.fromarray(live[rect[1]:rect[3], rect[0]:rect[2]]).save(buf, "PNG")
        url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        perfect.update(evaluate_async(transport, f"window.__obedDx.perfect({json.dumps(url)}, {shift})") or {})
        perfect["t"] = now()
        for j in range(2):
            images[f"ref-perfect-{j}"] = capture()
            perfect["shots"].append(f"ref-perfect-{j}")
    ref["perfect"] = perfect
    evaluate("window.__obedDx.finish()")
    ref["timers"] = evaluate("window.__obedDx.release()")
    record["reference"] = ref
    thread.join(timeout=30)
    collect(evaluate, record, images)
    if errors:
        record["advanceErrors"] = errors
    return record, images


def _shot_record(name: str, t0: float, t1: float) -> dict[str, Any]:
    return {"name": name, "t0": t0, "t1": t1, "durationMs": t1 - t0}


def burst(host: Any, target: dict[str, Any], capture: Callable[[], np.ndarray], *, actions: Iterable[tuple[float, str]] = (),
          screencast: Callable[[], Any] | None = None, lead_s: float = 0.0, tag: str = "",
          drop: str | None = None, handoff: bool = False) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Arm the hook, screenshot from `PRE_S` before the advance to T + `POST_S` (+ `lead_s`), run timed `actions`; the
    action named `drop` is recorded at its time (`dropped`) but not performed. With `handoff`, keep capturing (up to
    `HANDOFF_S` more) until one screenshot starts after the transition DOM has gone: the player keeps the finished
    transition until the next scene is ready, often past `POST_S`, and the hand-off needs a first live frame."""
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
        started, thread, live = time.monotonic(), None, 0
        while time.monotonic() - started < span or (handoff and live < HANDOFF_SHOTS and time.monotonic() - started < span + HANDOFF_S):
            if handoff and thread is not None and time.monotonic() - started >= span:
                live = live + 1 if live or evaluate("window.__obedDx.live()") else 0
            elapsed = time.monotonic() - started
            if thread is None and elapsed >= PRE_S:
                record["advanceAt"] = now()
                thread = threading.Thread(target=advance, daemon=True)
                thread.start()
            while thread is not None and pending and elapsed - PRE_S >= pending[0][0]:
                name = pending.pop(0)[1]
                if name == drop:
                    record["actions"].append({"name": name, "t": now(), "dropped": True})
                else:
                    act(host, name)
                    record["actions"].append({"name": name, "t": now()})
            t0 = now()
            img = capture()
            name = f"{tag}shot-{len(record['shots']):03d}"
            images[name] = img
            record["shots"].append(_shot_record(name, t0, now()))
        if thread is not None:
            thread.join(timeout=30)
    for k, (ts, img) in enumerate(cast):
        name = f"{tag}cast-{k:03d}"
        images[name] = img
        record["cast"].append({"name": name, "t": ts * 1000.0 - origin})
    collect(evaluate, record, images, tag)
    if errors:
        record["advanceErrors"] = errors
    return record, images


def settle(host: Any, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    while host.observe().busy and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.5)


def _drive_legacy(host: Any, arm: Arm, target: dict[str, Any], capture: Callable[[], np.ndarray], *,
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
    if arm.capture in PAUSED:
        record["pauseId"] = evaluate(f"window.__obedDx.pause({PAUSE_FRAME}, {FPS})")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and (evaluate("window.__obedDx.paused()") or {}).get("state") != "presented":
            time.sleep(0.05)
        time.sleep(0.3)
        record["paused"] = evaluate("window.__obedDx.paused()")
    if arm.inject:
        record["inject"] = evaluate(RAW_INJECTIONS[arm.inject])
        time.sleep(0.3)
    record["stage"] = evaluate(STAGE_JS)
    record["placement"] = evaluate(PLACEMENT_JS)
    record["dsf"] = evaluate("devicePixelRatio")
    record["viewport"] = evaluate("[innerWidth, innerHeight]")
    foreground = evaluate("window.__obedDx.foreground()") or {}
    for vid, canvases in foreground.items() if isinstance(foreground, dict) else ():
        for k, c in enumerate(canvases if isinstance(canvases, list) else ()):
            png = c.pop("png", None) if isinstance(c, dict) else None
            if png:
                images[f"fg-{vid}-{k}"] = decode_rgba(png)
                c["image"] = f"fg-{vid}-{k}"
    record["foreground"] = foreground
    images["live-0"] = capture()
    time.sleep(LIVE_GAP_S)
    images["live-1"] = capture()
    record["hashBefore"] = evaluate("String(location.hash||'')")
    lead = target["previousS"] + target["beginS"] if target["automatic"] else 0.0
    if arm.capture == "reference":
        shots, shot_images = reference_burst(host, target, capture, images["live-0"], arm.shift)
    else:
        shots, shot_images = burst(host, target, capture, actions=row.get("actions", ()), screencast=screencast, lead_s=lead,
                                   handoff="handoff" in arm.expect,
                                   drop=arm.drop)
    record.update(shots)
    record_dsk_counter_timing(record, arm)
    images.update(shot_images)
    settle(host)
    images["settled"] = capture()
    record["hashAfter"] = evaluate("String(location.hash||'')")
    ids = ((record.get("dump") or {}).get("first") or {}).get("layerIds") or []
    record["residue"] = evaluate(f"window.__obedDx.residue({json.dumps(ids)})") if ids else None
    if row.get("end"):
        host.execute("goTo", 1)
        settle(host)
        record["residueAfterGoto"] = evaluate(f"window.__obedDx.residue({json.dumps(ids)})") if ids else None
    return record, images


def _position_snapshot(evaluate: Callable[[str], Any]) -> dict[str, Any]:
    value = evaluate(POSITIONING_JS)
    return value if isinstance(value, dict) else {}


def _predicate(passed: bool, observed: Any = None) -> dict[str, Any]:
    return {"passed": bool(passed), "observed": observed}


def _pending_from_runtime(runtime: Any) -> int | None:
    if not isinstance(runtime, dict):
        return None
    return pending_scene({"scene": runtime.get("sceneId"), "next": runtime.get("nextSceneId"),
                          "state": runtime.get("playerState"), "ready": runtime.get("ready")})


def _dsk_urls(videos: list[dict[str, Any]]) -> tuple[list[str], list[float | None]]:
    urls = [str(video.get("src") or video.get("currentSrc") or "") for video in videos]
    offsets = []
    for url in urls:
        match = re.search(r"(?:#|%23)t=([0-9]+(?:\.[0-9]+)?)", url)
        offsets.append(float(match.group(1)) if match else 0.0 if url else None)
    return urls, offsets


def _position_predicates(snapshot: dict[str, Any], arm: Arm, target: dict[str, Any], goal: int) -> dict[str, dict[str, Any]]:
    runtime = snapshot.get("runtime")
    videos = snapshot.get("videos") if isinstance(snapshot.get("videos"), list) else []
    expected_decoders = arm.decoders if arm.movies else 0
    identities = [str(v.get("src") or v.get("currentSrc") or "") for v in videos if isinstance(v, dict)]
    decoded = [v for v in videos if isinstance(v, dict) and isinstance(v.get("readyState"), int)
               and v["readyState"] >= 2 and number(v.get("currentTime"))
               and number(v.get("videoWidth")) and v["videoWidth"] > 0
               and number(v.get("videoHeight")) and v["videoHeight"] > 0]
    urls, offsets = _dsk_urls(videos)
    dsk_ok = True
    if arm.movies == "dsk-counter":
        dsk_ok = (len(urls) == 2 and sorted(Path(url.split("#", 1)[0]).name for url in urls) == sorted(DSK_COUNTER_OFFSETS)
                  and sorted(offset for offset in offsets if offset is not None) == sorted(DSK_COUNTER_OFFSETS.values()))
    foreground = snapshot.get("foreground")
    foreground_required = bool(set(arm.overrides) & {"fg", "edgefg"})
    foreground_ok = isinstance(foreground, dict) and any(bool(value) for value in foreground.values())
    return {
        "pendingSceneBuild": _predicate(_pending_from_runtime(runtime) == goal,
                                         {"expected": goal, "runtime": runtime}),
        "automaticPlayback": _predicate(isinstance(runtime, dict) and runtime.get("ready") is True
                                          and str(runtime.get("playerState") or "").startswith("Idle"), runtime),
        "slideNumberControl": _predicate(isinstance(runtime, dict) and runtime.get("slideNumberShowing") is not True,
                                           runtime.get("slideNumberShowing") if isinstance(runtime, dict) else None),
        "decoderIdentity": _predicate(len(videos) == expected_decoders and all(identities) if expected_decoders else not videos,
                                        {"expected": expected_decoders, "sources": identities}),
        "presentedFrame": _predicate(len(decoded) == expected_decoders if expected_decoders else True,
                                      [{k: v.get(k) for k in ("src", "elementId", "currentTime", "readyState", "totalFrames",
                                                               "presentedFrames")}
                                       for v in videos if isinstance(v, dict)]),
        "urlFragment": _predicate(dsk_ok, {"urls": urls, "offsets": offsets}),
        "continuityState": _predicate(
            snapshot.get("continuity") in (None, []) and snapshot.get("preservedStage") == 0
            if arm.continuity != "off" else True,
            {"pool": snapshot.get("continuity"), "preservedStage": snapshot.get("preservedStage")}),
        "foreground": _predicate(foreground_ok if foreground_required else True,
                                   foreground),
        "textureInventory": _predicate(snapshot.get("stage") is True and isinstance(snapshot.get("canvases"), list)
                                        and bool(snapshot["canvases"]), snapshot.get("canvases")),
        "holderAdmission": _predicate(snapshot.get("holders") == 0, snapshot.get("holders")),
        "destinationReadiness": _predicate(snapshot.get("hash") == target["hashBefore"],
                                            {"expected": target["hashBefore"], "hash": snapshot.get("hash")}),
    }


def _predicates_pass(predicates: Mapping[str, Mapping[str, Any]]) -> bool:
    return bool(predicates) and all(value.get("passed") is True for value in predicates.values())


def _await_position(evaluate: Callable[[str], Any], arm: Arm, target: dict[str, Any], goal: int,
                    deadline: float) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    predicates: dict[str, dict[str, Any]] = {}
    snapshot: dict[str, Any] = {}
    while time.monotonic() < deadline:
        snapshot = _position_snapshot(evaluate)
        predicates = _position_predicates(snapshot, arm, target, goal)
        if _predicates_pass(predicates):
            break
        time.sleep(0.05)
    return predicates, snapshot


def _goto_autoplay(host: Any) -> dict[str, Any] | None:
    value = getattr(host, "_last_goto_autoplay", None)
    if value is None:
        return None
    return {"runLength": getattr(value, "run_length", None), "runKinds": getattr(value, "run_kinds", None),
            "fired": getattr(value, "fired", None), "deferredReason": getattr(value, "deferred_reason", None)}


def _adjacent_continuity_carries(host: Any, target: dict[str, Any]) -> list[dict[str, Any]] | None:
    report = (getattr(host, "output", {}) or {}).get("continuity")
    if not isinstance(report, dict):
        return None
    if report.get("mode") != "qualified":
        return []
    plan = getattr(host, "_continuity_runtime_plan", None)
    entries = plan.get("boundaries") if isinstance(plan, dict) else None
    if not isinstance(entries, list):
        return None
    adjacent = {target["scene"] - target.get("event", 0), target["scene"] + 1}
    return [entry for entry in entries if isinstance(entry, dict) and entry.get("atScene") in adjacent
            and entry.get("action") in ("pin", "bridge", "glReplay")]


def _goto_fallback_reasons(host: Any, arm: Arm, target: dict[str, Any]) -> list[str]:
    reasons = []
    if arm.row is not None:
        reasons.append("lifecycle-row")
    if arm.bridge:
        reasons.append("bridge")
    if arm.page != "alpha":
        reasons.append(f"page-{arm.page}")
    if target["automatic"]:
        reasons.append("automatic-target")
    if arm.continuity != "off":
        carries = _adjacent_continuity_carries(host, target)
        if carries is None:
            reasons.append("continuity-report-unavailable")
        elif carries:
            reasons.append("continuity-carried")
    return reasons


def _position(host: Any, arm: Arm, target: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    evaluate = host._require_transport().evaluate
    goal = target["scene"] - 1 if target["automatic"] else target["scene"]
    fallback = _goto_fallback_reasons(host, arm, target)
    if fallback:
        try:
            ordinary_advances = navigate(host, goal, target["sceneCount"])
        except Exception as exc:  # noqa: BLE001
            raise ReadinessTimeout(f"sequential positioning failed: {type(exc).__name__}: {exc}") from exc
        predicates = _position_predicates(_position_snapshot(evaluate), arm, target, goal)
        return {"path": "sequential", "fromSlide": 1, "ordinaryAdvances": ordinary_advances,
                "durationMs": round((time.monotonic() - started) * 1000.0, 1),
                "fallbackReasons": fallback, "gotoAutoplay": _goto_autoplay(host), "predicates": predicates}
    deadline = started + 15.0
    try:
        host.execute("goTo", arm.slide)
        autoplay = _goto_autoplay(host)
        if autoplay is not None and autoplay["deferredReason"]:
            raise ReadinessTimeout(f"go-to autoplay deferred: {autoplay['deferredReason']}")
        ordinary_advances = navigate(host, goal, target["sceneCount"], deadline=deadline)
    except ReadinessTimeout:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ReadinessTimeout(f"go-to positioning failed: {type(exc).__name__}: {exc}") from exc
    predicates, _ = _await_position(evaluate, arm, target, goal, deadline)
    if not _predicates_pass(predicates):
        failed = [name for name, value in predicates.items() if value.get("passed") is not True]
        raise ReadinessTimeout(f"positioning readiness timed out for {failed}")
    return {"path": "goTo-slide+ordinary-builds", "fromSlide": arm.slide, "ordinaryAdvances": ordinary_advances,
            "durationMs": round((time.monotonic() - started) * 1000.0, 1),
            "fallbackReasons": [], "gotoAutoplay": autoplay, "predicates": predicates}


def _painted(image: np.ndarray, arm: Arm) -> bool:
    expected = device_shape(arm)
    return (isinstance(image, np.ndarray) and image.shape == (expected[0], expected[1], 4)
            and bool(np.any(image)))


def _video_key(video: dict[str, Any]) -> tuple[str, Any]:
    return (str(video.get("src") or video.get("currentSrc") or ""),
            video.get("elementId") if video.get("elementId") is not None else video.get("hookId"))


def _advanced(before: list[dict[str, Any]], after: list[dict[str, Any]], count: int) -> tuple[bool, list[dict[str, Any]]]:
    before_by_key = {_video_key(video): video for video in before if isinstance(video, dict)}
    after_by_key = {_video_key(video): video for video in after if isinstance(video, dict)}
    rows = []
    for key in sorted(set(before_by_key) & set(after_by_key), key=str):
        first, second = before_by_key[key], after_by_key[key]
        frames = (first.get("totalFrames"), second.get("totalFrames"))
        presented = (first.get("presentedFrames"), second.get("presentedFrames"))
        moved = ((all(number(value) for value in frames) and frames[1] > frames[0])
                 or (all(number(value) for value in presented) and presented[1] > presented[0]))
        enough = number(presented[1]) and presented[1] >= MIN_PRESENTED
        rows.append({"source": key[0], "elementId": key[1], "frames": frames, "presentedFrames": presented,
                     "currentTime": (first.get("currentTime"), second.get("currentTime")),
                     "advanced": moved, "enoughPresented": enough})
    complete = len(before_by_key) == len(after_by_key) == len(rows) == count
    return complete and all(row["advanced"] and row["enoughPresented"] for row in rows), rows


def _capture_base(snapshot: dict[str, Any], arm: Arm, target: dict[str, Any], goal: int) -> dict[str, dict[str, Any]]:
    predicates = _position_predicates(snapshot, arm, target, goal)
    names = ("pendingSceneBuild", "automaticPlayback", "slideNumberControl", "decoderIdentity", "presentedFrame",
             "urlFragment", "destinationReadiness")
    return {name: predicates[name] for name in names}


def _capture_readiness(host: Any, arm: Arm, target: dict[str, Any], capture: Callable[[], np.ndarray], *,
                       paused: bool, pause_id: Any = None,
                       timeout_s: float = 15.0) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    started = time.monotonic()
    evaluate = host._require_transport().evaluate
    goal = target["scene"] - 1 if target["automatic"] else target["scene"]
    deadline = time.monotonic() + timeout_s
    predicates: dict[str, dict[str, Any]] = {}
    attempts: list[dict[str, Any]] = []
    first_passed_at: float | None = None
    first_image = second_image = np.empty((0, 0, 4), np.uint8)
    while time.monotonic() < deadline:
        first = _position_snapshot(evaluate)
        base = _capture_base(first, arm, target, goal)
        pause = evaluate("window.__obedDx.paused()") if paused else None
        if paused:
            base["presentedFrame"] = _predicate(isinstance(pause, dict) and pause.get("state") == "presented"
                                                 and pause.get("id") == pause_id, pause)
        if not _predicates_pass(base):
            time.sleep(0.05)
            continue
        if first_passed_at is None:
            first_passed_at = time.monotonic()
        wait = 0.3 - (time.monotonic() - first_passed_at)
        if wait > 0:
            time.sleep(min(0.05, wait))
            continue
        first_image = capture()
        time.sleep(LIVE_GAP_S)
        second = _position_snapshot(evaluate)
        second_image = capture()
        predicates = _capture_base(second, arm, target, goal)
        predicates["obsPainted"] = _predicate(_painted(first_image, arm) and _painted(second_image, arm),
                                               {"first": list(first_image.shape), "second": list(second_image.shape)})
        if paused:
            predicates["presentedFrame"] = base["presentedFrame"]
            predicates["stableCapturedPixels"] = _predicate(first_image.shape == second_image.shape
                                                              and np.array_equal(first_image, second_image))
        else:
            predicates["advancingObs"] = _predicate(first_image.shape == second_image.shape
                                                       and not np.array_equal(first_image, second_image))
            if arm.movies:
                before_videos = first.get("videos") if isinstance(first.get("videos"), list) else []
                after_videos = second.get("videos") if isinstance(second.get("videos"), list) else []
                advanced, rows = _advanced(before_videos, after_videos, arm.decoders)
                predicates["advancingPresentation"] = _predicate(advanced, rows)
        failed = [name for name, value in predicates.items() if value.get("passed") is not True]
        attempts.append({"atMs": round((time.monotonic() - started) * 1000.0, 1), "failedPredicates": failed})
        if paused or not failed:
            return ({"durationMs": round((time.monotonic() - started) * 1000.0, 1), "predicates": predicates,
                     "attempts": attempts},
                    first_image, second_image)
        if len(attempts) >= 10:
            raise ReadinessTimeout(f"capture readiness timed out after 10 pixel attempts for {failed}")
        time.sleep(0.05)
    failed = [name for name, value in predicates.items() if value.get("passed") is not True]
    raise ReadinessTimeout(f"capture readiness timed out for {failed}")


def _final_readiness(host: Any, arm: Arm, target: dict[str, Any], capture: Callable[[], np.ndarray],
                     timeout_s: float = 15.0) -> tuple[dict[str, Any], np.ndarray]:
    started = time.monotonic()
    evaluate = host._require_transport().evaluate
    deadline = time.monotonic() + timeout_s
    predicates: dict[str, dict[str, Any]] = {}
    image = np.empty((0, 0, 4), np.uint8)
    while time.monotonic() < deadline:
        busy = host.observe().busy
        snapshot = _position_snapshot(evaluate)
        if not busy and snapshot.get("hash") == target["hashAfter"]:
            image = capture()
            runtime = snapshot.get("runtime")
            expected = int(str(target["hashAfter"]).lstrip("#"))
            predicates = {
                "correctScene": _predicate(_pending_from_runtime(runtime) == expected,
                                             {"expected": expected, "runtime": runtime}),
                "playerIdle": _predicate(not busy, busy),
                "destinationReadiness": _predicate(snapshot.get("hash") == target["hashAfter"],
                                                    {"expected": target["hashAfter"], "hash": snapshot.get("hash")}),
                "obsPainted": _predicate(_painted(image, arm), list(image.shape)),
            }
            if _predicates_pass(predicates):
                return {"durationMs": round((time.monotonic() - started) * 1000.0, 1), "predicates": predicates}, image
        time.sleep(0.05)
    failed = [name for name, value in predicates.items() if value.get("passed") is not True]
    raise ReadinessTimeout(f"final readiness timed out for {failed or ['playerIdle', 'destinationReadiness']}")


def _drive_placement(host: Any, arm: Arm, target: dict[str, Any], capture: Callable[[], np.ndarray], *,
                     screencast: Callable[[], Any] | None = None,
                     placement_read: Callable[[Any], None] | None = None,
                     ) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    if arm.row is not None or arm.inject or arm.bridge:
        raise ValueError("placement driver does not support lifecycle, injection or bridge arms")
    transport = host._require_transport()
    evaluate = transport.evaluate
    host.execute("show")
    record: dict[str, Any] = {"positioning": _position(host, arm, target)}
    images: dict[str, np.ndarray] = {}
    if arm.capture in PAUSED:
        record["pauseId"] = evaluate(f"window.__obedDx.pause({PAUSE_FRAME}, {FPS})")
    record["stage"] = evaluate(STAGE_JS)
    record["placement"] = evaluate(PLACEMENT_JS)
    if placement_read is not None:
        placement_read(record["placement"])
    record["dsf"] = evaluate("devicePixelRatio")
    record["viewport"] = evaluate("[innerWidth, innerHeight]")
    foreground = evaluate("window.__obedDx.foreground()") or {}
    for vid, canvases in foreground.items() if isinstance(foreground, dict) else ():
        for k, canvas in enumerate(canvases if isinstance(canvases, list) else ()):
            png = canvas.pop("png", None) if isinstance(canvas, dict) else None
            if png:
                images[f"fg-{vid}-{k}"] = decode_rgba(png)
                canvas["image"] = f"fg-{vid}-{k}"
    record["foreground"] = foreground
    ready, images["live-0"], images["live-1"] = _capture_readiness(
        host, arm, target, capture, paused=arm.capture in PAUSED, pause_id=record.get("pauseId"))
    if arm.capture in PAUSED:
        record["paused"] = evaluate("window.__obedDx.paused()")
    record["hashBefore"] = evaluate("String(location.hash||'')")
    lead = target["previousS"] + target["beginS"] if target["automatic"] else 0.0
    if arm.capture == "reference":
        shots, shot_images = reference_burst(host, target, capture, images["live-0"], arm.shift)
    else:
        shots, shot_images = burst(host, target, capture, actions=(), screencast=screencast, lead_s=lead,
                                   handoff="handoff" in arm.expect, drop=arm.drop)
    record.update(shots)
    record_dsk_counter_timing(record, arm)
    images.update(shot_images)
    final, images["settled"] = _final_readiness(host, arm, target, capture)
    record["readiness"] = {"durationMs": round(ready["durationMs"] + final["durationMs"], 1),
                           "beforeCapture": ready, "afterTransition": final}
    record["hashAfter"] = evaluate("String(location.hash||'')")
    ids = ((record.get("dump") or {}).get("first") or {}).get("layerIds") or []
    record["residue"] = evaluate(f"window.__obedDx.residue({json.dumps(ids)})") if ids else None
    return record, images


def drive(host: Any, arm: Arm, target: dict[str, Any], capture: Callable[[], np.ndarray], *,
          screencast: Callable[[], Any] | None = None, placement: bool = False,
          placement_read: Callable[[Any], None] | None = None,
          ) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    if placement:
        return _drive_placement(
            host, arm, target, capture, screencast=screencast, placement_read=placement_read)
    return _drive_legacy(host, arm, target, capture, screencast=screencast)


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


def start_chrome(profile: Path, *, gpu: bool, viewport: tuple[int, int] | None = None,
                 dsf: float = 1.0) -> tuple[subprocess.Popen[bytes], int, list[str]]:
    from obed_edom.devtools_port import DEVTOOLS_ACTIVE_PORT, verify_devtools_owner, wait_devtools_active_port

    profile.mkdir(parents=True, exist_ok=True)
    (profile / DEVTOOLS_ACTIVE_PORT).unlink(missing_ok=True)
    args = [str(CHROME), "--headless=new", "--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={profile}", "--window-size={},{}".format(*(viewport or VIEWPORT)), f"--force-device-scale-factor={dsf:g}",
            "--autoplay-policy=no-user-gesture-required", "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows", "--mute-audio", "--no-first-run",
            "--no-default-browser-check", *([] if gpu else ["--disable-gpu"]), "about:blank"]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    endpoint = wait_devtools_active_port(profile, proc, 20)
    verify_devtools_owner(endpoint, 2)
    return proc, endpoint.port, args


def raw_snapshot_js(automatic: Iterable[int]) -> str:
    """The raw page's readiness from what the production bytes expose (the controller is a module `let`, out of reach):
    the hash the player writes only at idle (`updateWindowHistory`: the next scene to play), no running animation, and
    that scene not automatic (the player is about to play it by itself; `automatic` from the slide JSON)."""
    return ("(function(){var m=/^#(\\d+)$/.exec(location.hash||''),h=m?+m[1]:null,b=document.getAnimations().some("
            "function(a){return a.playState==='running'});return {ready:document.readyState==='complete'&&h!==null&&!b&&"
            f"{json.dumps(sorted(automatic))}.indexOf(h)<0,state:'IdleAtInitialState',scene:h}}}})()")


ADVANCE_ACK_S = 30.0


class RawHost:
    """The raw export page (its own `index.html` with `RAW_STYLE`, navigator present; `preview` adds the Build Preview
    diagnostics as `web.app` serves them) on the arm's served player, driven with Space over CDP: the subset of
    `LiveOutputHost` that `drive` uses. With `grant`, the host's first-run script is installed before navigation under a
    fresh token (`placement_token`), the privileged channel `commit_grant` uses; without it the page has no channel."""
    def __init__(self, resolved: Resolved, player: bytes, scratch: Path, endpoint: str, tag: str, *, preview: bool = False,
                 grant: bool = True) -> None:
        import secrets

        from obed_edom.html_preview import inject_player_diagnostics
        from obed_edom.live_host import _AssetServer

        index = (resolved.root / "index.html").read_text()
        head = re.search(r"<head[^>]*>", index, flags=re.I)
        if head is None:
            raise ValueError("export index.html has no <head>")
        page = scratch / "raw" / tag / "index.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(index[:head.end()] + RAW_STYLE + index[head.end():])
        if preview:
            page.write_text(inject_player_diagnostics(page.read_text()))
        self.placement_token = secrets.token_hex(16) if grant else None
        self.snapshot_js = raw_snapshot_js(resolved.target["automaticScenes"])

        def resolver(root: Path, relative: str) -> Path:
            return page if relative == "index.html" else resolved.resolver(root, relative)

        self.server = _AssetServer(resolved.root, player, resolver)
        self.transport = hooked_transport()(CHROME, page.parent / "profile", None, headless=True, attach_endpoint=endpoint)
        self.output = {"mmOpacity": {"sha256": sha256_bytes(player)}, "page": "preview" if preview else "raw",
                       "indexSha256": binary.sha256_file(page)}

    def start(self, width: int, height: int, dsf: float) -> None:
        base = self.server.start().rsplit("/", 1)[0]
        self.transport.start()
        if self.placement_token:
            from obed_edom.live_host import placement_init_script

            self.transport.call("Page.addScriptToEvaluateOnNewDocument", source=placement_init_script(self.placement_token))
        if dsf == 1:
            self.transport.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)
        self.transport.call("Emulation.setDefaultBackgroundColorOverride", color={"r": 0, "g": 0, "b": 0, "a": 0})
        self.transport.goto(f"{base}/index.html")
        wait_ready(self.transport.evaluate, snapshot_js=self.snapshot_js)

    def stop(self) -> None:
        try:
            self.transport.stop()
        finally:
            if self.server.httpd is not None:
                self.server.httpd.shutdown()

    def _require_transport(self) -> Any:
        return self.transport

    def execute(self, name: str, *_: Any) -> None:
        if name == "advance":
            self.transport.key(" ", "Space", 32)
        elif name != "show":
            raise RuntimeError(f"raw page cannot {name}")

    def await_advance(self, before: dict[str, Any] | None) -> None:
        """`navigate`'s acknowledgement: the hash moves off the pressed scene (it is rewritten only at the next idle), so
        a stale `ready` is never pressed again into the player's queue."""
        deadline = time.monotonic() + ADVANCE_ACK_S
        while time.monotonic() < deadline:
            now = self.transport.evaluate(self.snapshot_js)
            if now and before and now.get("scene") != before.get("scene"):
                return
            time.sleep(0.05)
        raise RuntimeError(f"the player did not take the advance from {before}")

    def observe(self) -> Any:
        from types import SimpleNamespace

        snap = self.transport.evaluate(self.snapshot_js)
        return SimpleNamespace(busy=not (snap and snap.get("ready")))


GRANT_WAIT_S = 10.0


def commit_grant(evaluate: Callable[[str], Any], token: str | None, value: str = "snap", ms: int | None = None) -> dict[str, Any]:
    """Use the privileged channel, including the script-only leased wrong-rule controls."""
    args = f"{json.dumps(token)},{json.dumps(value)}" + ("" if ms is None else f",{ms}")
    ok = evaluate(f"window.__obedGrant({args})") if token else None
    return {"committed": ok is True, "read": evaluate(PLACEMENT_JS)}


def host_grant(host: Any, evaluate: Callable[[str], Any], timeout_s: float = GRANT_WAIT_S) -> Any:
    """Let the host run its own round trip (at `observe`) and return the page's read once it is `snap` or at timeout."""
    deadline = time.monotonic() + timeout_s
    while True:
        host.observe()
        read = evaluate(PLACEMENT_JS)
        if read == "snap" or time.monotonic() > deadline:
            return read
        time.sleep(0.1)


def regrant_after_reload(host: Any, transport: Any) -> dict[str, Any]:
    """`life-grant-reload`: a fresh document reads `invalid` until the host's next `observe` re-grants it."""
    transport.call("Page.reload", ignoreCache=True)
    wait_ready(transport.evaluate)
    before = transport.evaluate(PLACEMENT_JS)
    return {"before": before, "after": host_grant(host, transport.evaluate)}


def run_arm(name: str, scratch: Path, decision: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    import live_continuity_probe as probe

    from obed_edom.live_host import LiveOutputHost, PlayerCommandRejected

    arm = ARMS[name]
    width, height = viewport_of(arm)
    record: dict[str, Any] = {"arm": name, "page": arm.page, "load": os.getloadavg()[0], "headlessBefore": mmo.headless_chromes()}
    images: dict[str, np.ndarray] = {}
    proc = host = None
    profile = Path(tempfile.mkdtemp(prefix="dissolve-probe-"))
    try:
        resolved = resolve(arm, scratch, decision, tag=name)
        record.update(resolved.fields())
        attach = port = None
        if arm.page in ("alpha", "raw", "preview"):
            proc, port, args = start_chrome(profile, gpu=arm.gpu, viewport=(width, height), dsf=arm.dsf)
            attach = f"http://127.0.0.1:{port}"
            record["launch"] = {"chromeArgs": args[1:], "metricsOverride": None}
        elif arm.dsf != 1:
            raise RuntimeError("a DPR != 1 arm needs its own Chrome launch with the flag (the screen page launches at DSF 1)")
        else:
            probe.force_viewport(width, height)
        if arm.page in ("raw", "preview"):
            stock = (resolved.root / "assets/player/main.js").read_bytes()
            host = RawHost(resolved, served_player(stock, arm.mode, arm.splice), scratch, attach, name, preview=arm.page == "preview",
                           grant=arm.grant == "driver")
            host.start(width, height, arm.dsf)
        else:
            before = PREDEFINE_JS if arm.capture == "channel" else None
            extra = {"placement_mode": arm.placement_mode} if arm.placement_mode else {}
            host = LiveOutputHost(resolved.root, resolved.slides, headless=True, resolver=resolved.resolver,
                                  transport_factory=hooked_transport(before=before), attach_endpoint=attach, continuity=arm.continuity,
                                  gl_replay="off", mm_opacity="auto" if arm.mode == "on" else "off", chrome_path=CHROME, **extra)
            with serving(arm.splice):
                host.start()
        transport = host._require_transport()
        if arm.capture == "channel":
            host.observe()
            try:
                host.execute("show")
                record["showRefused"] = False
            except PlayerCommandRejected as exc:
                record["showRefused"], record["showError"] = True, str(exc)
            record["output"] = {"placement": host.output.get("placement")}
            return record, images
        if arm.dsf == 1:
            transport.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)
            if "launch" in record:
                record["launch"]["metricsOverride"] = {"width": width, "height": height, "deviceScaleFactor": 1}
        if arm.page in ("alpha", "raw", "preview"):
            transport.call("Emulation.setDefaultBackgroundColorOverride", color={"r": 0, "g": 0, "b": 0, "a": 0})
        if arm.grant == "driver":
            value = arm.placement_value or "snap"
            record["grant"] = commit_grant(transport.evaluate, getattr(host, "placement_token", None) or host._placement_token,
                                             value, 15_000 if arm.placement_mode == "probe" else None)
        elif arm.grant == "host":
            record["grant"] = {"read": host_grant(host, transport.evaluate)}
            if arm.regrant == "reload":
                record["reload"] = regrant_after_reload(host, transport)
        if arm.forgery:
            record["forgery"] = transport.evaluate(FORGERY_JS[arm.forgery])
        record["output"] = {k: host.output.get(k) for k in ("mmOpacity", "continuity", "page", "indexSha256", "placement")
                            if k in host.output}
        port = port or transport.port

        def capture() -> np.ndarray:
            return decode_rgba(transport.call("Page.captureScreenshot", format="png", fromSurface=True)["data"])

        cast = arm.capture == "cut" or (arm.row or "").startswith("hide")
        driven, images = drive(host, arm, resolved.target, capture, screencast=(lambda: screencast_frames(port)) if cast else None)
        record.update(driven)
        record.update(resolved.fields())
        if "placement" in host.output:
            record["output"]["placement"] = host.output["placement"]
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
    saved = dict(record)
    if "placementCalibration" in saved:
        saved["placementCalibration"] = serialize_placement_calibration(saved["placementCalibration"], run)
    (run / "record.json").write_text(json.dumps(saved, default=str))


class RunImages(Mapping):
    """A saved run's PNGs with an arm-scoped immutable decode cache."""

    def __init__(self, folder: Path) -> None:
        self.paths = {p.stem: p for p in folder.glob("*.png")}
        self._cache: dict[str, np.ndarray] = {}
        self.decode_s = 0.0
        self.decode_bytes = 0
        self.decode_count = 0

    def __getitem__(self, key: str) -> np.ndarray:
        if key in self._cache:
            return self._cache[key]
        started = time.monotonic()
        path = self.paths[key]
        with Image.open(path) as opened:
            image = np.asarray(opened.convert("RGBA"))
        image.setflags(write=False)
        self.decode_s += time.monotonic() - started
        self.decode_bytes += path.stat().st_size
        self.decode_count += 1
        self._cache[key] = image
        return image

    def release(self) -> None:
        self._cache.clear()

    def __iter__(self) -> Iterator[str]:
        return iter(self.paths)

    def __len__(self) -> int:
        return len(self.paths)


def load_runs(out: Path) -> dict[str, tuple[dict[str, Any], Mapping[str, np.ndarray]]]:
    return {path.parent.name: (json.loads(path.read_text()), RunImages(path.parent))
            for path in sorted((out / "runs").glob("*/record.json"))}


def path_lut(decision: dict[str, Any] | None, gpu: bool) -> np.ndarray | None:
    """`L_path` from the decision record's `lPath` {"gpu"|"software": "analytic" | "identity" | 256 ints}; None if absent."""
    spec = ((decision or {}).get("lPath") or {}).get("gpu" if gpu else "software")
    if spec == "analytic":
        return analytic_lut()
    if spec == "identity":
        return np.arange(256, dtype=np.uint8)
    if isinstance(spec, list) and len(spec) == 256 and all(integer(v) and 0 <= v <= 255 for v in spec):
        return np.asarray(spec, np.uint8)
    return None


def launch_lut(runs: Mapping[str, tuple[dict[str, Any], Mapping[str, np.ndarray]]], cal: Calibration = Calibration(),
               profile: Profile = CEF) -> tuple[np.ndarray | None, dict[str, Any]]:
    """`L_path` measured in this launch (§9.2): the `m-tone` session's holder (the `drawImage` snapshot) against its
    `S_live` (the compositor) on the verified exposed tone cells, through `build_lut`; the session must be complete,
    its mask verified against `m-tone-twin` and its coverage met. None, with the reasons, otherwise."""
    tone_name = "m-tone-cef" if profile.placement == "frac" else "m-tone"
    arm = profile.arm(tone_name)
    detail: dict[str, Any] = {"source": f"{tone_name} (this launch)", "kind": None, "samples": 0, "problems": []}
    if tone_name not in runs:
        detail["problems"] = [f"no {tone_name} session in this launch"]
        return None, detail
    record, images = runs[tone_name]
    try:
        decoder, _, problems = media_integrity(record, images, arm, [])
        problems = capture_problems(record, images, arm, profile, cal) + problems
        mask, verify = verified_mask(record, images, arm, profile, cal, runs.get(arm.twin or ""))
        problems += verify
        ev = evidence(record, images, arm)
        if not problems and mask is not None and decoder is not None and ev.holders:
            cx, cy, cw, _ = decoder["content"]
            layout = next(iter((record.get("movies") or {}).values()), {}).get("layout") or {}
            exposed, coverage = tone_coverage(layout, mask.shape, (cx * arm.dsf, cy * arm.dsf), cw * arm.dsf / decoder["size"][0], mask)
            problems += coverage
            if not coverage:
                table = build_lut(ev.holders[0][exposed][:, :3], images["live-0"][exposed][:, :3])
                detail.update(kind=table["kind"], samples=int(exposed.sum()))
                if table["kind"] in ("analytic", "table"):
                    return np.asarray(table["table"], np.uint8), detail
                problems += table.get("problems") or [f"measured map is {table['kind']}"]
        elif not problems:
            problems.append("no verified mask, decoder or holder")
    except MALFORMED as exc:
        problems = [f"malformed record: {type(exc).__name__}: {exc}"]
    detail["problems"] = problems
    return None, detail


def score_runs(runs: dict[str, tuple[dict[str, Any], Mapping[str, np.ndarray]]], decision: dict[str, Any] | None = None,
               cal: Calibration = Calibration(), *, profile: Profile = DX1, lut: np.ndarray | None = None) -> dict[str, Any]:
    """Score every run the profile names (DX-1 here; DX-2 passes `CEF` and `launch_lut`'s map) and the round. DX-1 reads
    `L_path` from the decision record; DX-2 never falls back to it (no launch map -> holder pixels INCONCLUSIVE)."""
    started = time.monotonic()
    identity = None if not decision or "L" not in decision else decision["L"] == "identity"
    required = set(profile.required(identity))
    scored = {}

    def release(name: str | None) -> None:
        if name not in runs:
            return
        images = runs[name][1]
        if isinstance(images, RunImages):
            images.release()

    for name, (record, images) in runs.items():
        if name not in required:
            continue
        arm = profile.arm(name, identity)
        if arm.row is not None and arm.twin is None:
            scored[name] = score_hide_capture(record, images, arm, cal, profile)
        elif arm.row is not None:
            scored[name] = score_lifecycle(record, images, runs.get(arm.twin), arm, cal, profile)
        else:
            scored[name] = score_arm(record, images, arm, cal, identity=identity, profile=profile,
                                     twin=runs.get(arm.twin) if arm.twin else None,
                                     lut=lut if lut is not None else path_lut(decision, arm.gpu) if profile.headless else None)
        release(name)
        if arm.twin in runs:
            release(arm.twin)
    extra = {}
    if "on" in scored and "on2" in scored:
        extra["cvc"] = score_cvc(scored["on"]["midResiduals"], scored["on2"]["midResiduals"])
    if "opaque-on" in scored and "opaque-off" in scored:
        def frames(name: str) -> list[tuple[float, np.ndarray]]:
            record, images = runs[name]
            shots = [images[s["name"]] for s in record.get("shots") or []]
            return [(e, premul(shots[i])) for e, i in scored[name]["fitted"] if number(e) and 0.03 < e < 0.97 and i < len(shots)]
        extra["matched"] = matched_report(frames("opaque-on"), frames("opaque-off"))
        release("opaque-on")
        release("opaque-off")
    verdict = score_round(scored, cal, identity=identity, extra=extra, profile=profile)
    verdict["detail"] = scored
    verdict["timingS"] = {
        "pixelScoring": round(time.monotonic() - started, 6),
        "pngDecode": round(sum(getattr(images, "decode_s", 0.0) for _, images in runs.values()), 6),
        "pngDecodeCount": sum(getattr(images, "decode_count", 0) for _, images in runs.values()),
        "pngBytes": sum(getattr(images, "decode_bytes", 0) for _, images in runs.values()),
    }
    for _, images in runs.values():
        if isinstance(images, RunImages):
            images.release()
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
    args.arms = list(DX1.arms) if args.arms == "all" else [a for a in args.arms.split(",") if a]
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
