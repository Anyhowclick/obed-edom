#!/usr/bin/env python3
"""HOST gate: does the live host's injected movie-continuity runtime carry decoder
identity and playback clock through the same boundaries P2 proved offline (offline,
in `scripts/p2_recovery_html_adversarial.py`), when driven through `LiveOutputHost`
instead of a bare page?

Three arms in one artifact, each boundary's expectation DERIVED from the installed
plan, never hard-wired: a boundary the plan carries must read TRUE; a boundary the
plan RETIRES must read FALSE and also earn the positive `refused*` verdict (no
painting `<video>` over the movie's rect on the settled destination slide, and
nothing pooled or preserved for its asset), because "did not continue" on its own
asserts nothing.
  A. continuity on -> every carried boundary TRUE, every retired one refused.
  B. OBED_LIVE_CONTINUITY=off -> raw player; continue3to4 expected FALSE (the
     Keynote HTML-export bug the continuity runtime repairs); 1->2 is reported as
     measured, not assumed.
  C. continuity on, but the bridge boundary is stripped by a PROBE-ONLY monkeypatch
     of `ContinuityPlan.to_runtime` (no product switch) -> continue3to4 FALSE while
     the 1->2 boundary keeps arm A's expectation (isolates the repair to the 3->4
     boundary).
Then one ATTACH-mode run (arm A only): the host attaches over CDP to a headless
Chrome this script launches itself, confirms `qualified`, all three verdicts, and a
transparent page background, then kills that Chrome by pid.

Finally two VISIBLE-CONTENT passes in their own host sessions (no sampler: a
screenshot burst would perturb the rAF sampler's clock, so they are never run
inside an arm) -- `V` (continuity on) and `Voff` (continuity off, the raw
export's reference). Every authored movie rect carries a plan-derived
expectation, live or dead, and both are scored: each pass must meet all of them
and must itself contain a live-expected rect that read live and (when the plan
states one) a dead-expected rect that read dead, proving the instrument neither
blind nor always-red from the inside.

Verdicts are decoder-identity + playback-clock based (a stable element id, a
monotonic non-decreasing `video.currentTime`, and -- when continuity is installed --
the runtime's own `footprintOwnerDecoderId`), never a screenshot MAE and never a
sleep as proof. If the tracked movie never decodes, the verdict is INCONCLUSIVE, not
a false pass/fail.

Does not qualify HDMI, alpha compositing, or audio. Offline/local Chrome only.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from obed_edom import live_host as live_host_module  # noqa: E402
from obed_edom import live_continuity as live_continuity_module  # noqa: E402
from obed_edom.html_preview import cache_dir, safe_export_file  # noqa: E402
from obed_edom.live_continuity import ContinuityPlan, Unsupported, derive_plan  # noqa: E402
from obed_edom.html_alpha_probe import (  # noqa: E402
    INPAGE_BAND_COUNT,
    INPAGE_MIN_SAMPLES,
    LIVE_BAND_COLS,
    LIVE_BAND_ROWS,
    combine_oracle_verdicts,
    inpage_mask_is_usable,
    is_character_effect,
    liveness_mask,
    occluder_mask_from_markers,
    score_inpage_liveness,
    score_live_coverage,
)
from obed_edom.live_gl_replay_js import GL_REPLAY_VERSION, js_sha256 as gl_replay_js_sha256  # noqa: E402
from obed_edom.live_host import ADVANCE_ENV, ATTACH_ENV, CONTINUITY_ENV, LiveOutputHost, OutputDisplay, PlayerCommandRejected  # noqa: E402
from obed_edom.p2_verdict import BURST_OFFSETS_MS, CONTROL_INSET_PX, CONTROL_PATCH_PX  # noqa: E402

try:
    from obed_edom.live_host import GOTO_AUTOPLAY_ENV  # noqa: E402
except ImportError:  # pragma: no cover - stream B is landing this constant concurrently
    GOTO_AUTOPLAY_ENV = "OBED_LIVE_GOTO_AUTOPLAY"

import live_host_probe  # noqa: E402 - reuse the headless window-size compensation

FIXTURE = REPO / "output/p2-recovery/html-adversarial/html-player"
ORIGINAL_INDEX = REPO / "output/p2-recovery/html-adversarial/html-unmodified/index.html"
ARTIFACT = Path("output/keynote-live-planning-2026-09-19/live-continuity-probe.json")
PROBE_DIGEST = "b" * 64
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

VIEWPORT_WIDTH, VIEWPORT_HEIGHT = 1920, 1080

MIN_ADVANCE_S = 0.5
MAX_STALL_S = 0.3
MAX_DROP_S = 0.05
RESTART_MAX_START_S = 0.5
RECT_TOLERANCE_PX = 3.0
CLICK_DELAY_S = 1.5
POST_ADVANCE_SETTLE_S = 1.8
VIDEO_DECODE_TIMEOUT_S = 8.0
MAX_ADVANCE_STEPS = 40
# Window discipline (reviewer finding #1/#2): a "sometime before, sometime after"
# check on the whole run cannot see a multi-second freeze or an owner handoff
# that only holds outside the window actually being cut. Every continuity verdict
# is instead scored over a WINDOW: [last settled sample before the boundary scene,
# first settled sample at/after it] padded by WINDOW_PAD_S on each side. 2.0s (well
# over the spec's ">= 0.5s" floor) so the window comfortably covers the preserve
# runtime's own documented remount-retry schedule (delays up to 2000ms in
# `live_continuity_js.py`'s `scheduleRemount`) -- a freeze inside that retry
# window is exactly the failure mode this instrument exists to catch.
WINDOW_PAD_S = 2.0

BURST_POKE_JS = (
    "(function(){var d=document.getElementById('__orpoke');"
    "if(!d){d=document.createElement('div');d.id='__orpoke';"
    "d.style.cssText='position:fixed;left:0;top:0;width:1px;height:1px;z-index:0;';"
    "document.body.appendChild(d);}"
    "d.style.background='rgb('+(Math.floor(Math.random()*255))+',0,0)';return 1;})()"
)
VISIBLE_SETTLE_TIMEOUT_S = 10.0
# A painting `<video>` claims an expected instance rect at the same IoU the
# runtime's own owner resolution uses.
INSTANCE_IOU_MIN = 0.75

# Per-rect expectations the plan states for a settled slide (see
# `rect_expectations`), and the positive verdict each refused boundary must earn.
LIVE, DEAD = "live", "dead"
REFUSAL_VERDICT_KEY = {
    "continue1to2": "refused1to2",
    "restart2to3": "refused2to3",
    "continue3to4": "refused3to4",
}
# A painting `<video>` overlaps a retired movie's rect when it does so by more
# than this in authored px -- edge-touching and AA seams are not an overlap.
REFUSAL_OVERLAP_MIN_PX = 1.0

ARMED_VERDICT_KEY = {"continue1to2": "armed1to2"}
ARMED_READ_GAP_S = 0.5
ARMED_CARRY_DELTA_MAX = 0.02
ARMED_CLOCK_RATE = (0.75, 1.25)
HANDBACK_TIMEOUT_S = 5.0
HANDBACK_DILATE_PX = 2
HANDBACK_RECT_TOLERANCE_PX = 0.5
GL_FORCE_FAIL_REASONS = ("planUnreadable", "rvfcUnavailable", "posterAmbiguous", "occlusionTooHigh")
FORCE_FAIL_SEED_ID = "probe-force-fail"
EXPECTED_GL_MODES = (
    ("arm A", ("arms", "A"), "injected"), ("arm B", ("arms", "B"), "off"), ("arm C", ("arms", "C"), "injected"),
    ("visible pass V", ("visible", "V"), "off"), ("visible pass Voff", ("visible", "Voff"), "off"),
    ("visible pass Vgl", ("visible", "Vgl"), "injected"), ("attach", ("attach",), "unavailable"),
)

# Pass G (goTo autoplay repair): (fromOriginalOrdinal, toOriginalOrdinal) pairs.
GOTO_MATRIX: tuple[tuple[int, int], ...] = ((1, 2), (1, 3), (1, 4), (3, 1), (4, 3))
# 8 shots with a nominal margin over the >=360ms floor `spacing_ok` checks on the measured timestamps.
G_BURST_OFFSETS_MS: tuple[int, ...] = (0, 450, 910, 1360, 1820, 2270, 2730, 3180)
# The one destination the plan requires no-consumption evidence for.
GOTO_CONSUMPTION_CHECK_TO = 2
CHARACTERS_ASSET_KEY = "__characters__"
# A completed dissolve build is static, so "did it fire" is judged by pixel content change, never motion.
CHARACTER_REGION_MAE_MIN = 8.0
# The area outside every expected movie rect must show a pixel this bright somewhere (never a flat
# black overlay) and change by no more than this between two captures (stable, no stray motion).
STATIC_CONTROL_MIN_BRIGHT = 12.0
STATIC_CONTROL_MAX_MAE = 6.0

# In headless Chrome, --window-size=W,H yields innerHeight H-32 (chrome window
# chrome persists even headless) -- reuse live_host_probe's measured compensation
# rather than re-deriving it.
_HEIGHT_PAD = live_host_probe.HEADLESS_CHROME_HEIGHT_PAD

# The probe's OWN read of the stage map, independent of the runtime's --
# `#stage.offsetWidth/Height` is the transform-blind authored size,
# `getBoundingClientRect()` is the on-screen (post-transform) rect. Every
# sampled video rect is converted from screen to authored space in Python
# using this per-sample map, never the runtime's own `stageMap()`. Shared
# verbatim with the visible-content pass (`STAGE_MAP_JS`), which reads it
# once per burst instead of once per frame.
STAGE_MAP_FN_JS = r"""
  function stageMapOf(){
    var el = document.getElementById('stage');
    if (!el) return null;
    var r = el.getBoundingClientRect();
    var ow = el.offsetWidth, oh = el.offsetHeight;
    if (!ow || !oh || !r.width || !r.height) return null;
    return {s: r.width / ow, sy: r.height / oh, ox: r.left, oy: r.top, offsetWidth: ow, offsetHeight: oh};
  }
"""

STAGE_MAP_JS = "(function(){" + STAGE_MAP_FN_JS + "return stageMapOf();})()"

SCENE_ID_JS = "window.__obedLive ? window.__obedLive.snapshot().sceneId : null"
HASH_JS = "String(location.hash || '')"

# Never the oracle handle, its context, `markerBands` or `pause` (Vgl pass only).
GL_REPLAY_READ_JS = r"""
(function(){
  function plain(x){ try { return JSON.parse(JSON.stringify(x)); } catch (e) { return {error: String(e)}; } }
  var out = {t: performance.now(), hash: String(location.hash || ''), ready: null, api: null,
             coreEvents: null, pool: null, facades: []};
  try { out.ready = window.__obedLive ? window.__obedLive.snapshot().ready === true : null; } catch (e) {}
  var api = window.__OBED_GL_REPLAY__;
  if (api && api.version) {
    out.api = plain({version: api.version, state: api.state, standDowns: api.standDowns, events: api.events,
                     stats: typeof api.stats === 'function' ? api.stats() : null});
  }
  var core = window.__OBED_P2_PRESERVE__;
  if (core) {
    out.coreEvents = plain((core.events || []).filter(function(e){
      return e && /^(glreplay-|remount-|preserve-refused|retire)/.test(String(e.kind));
    }));
    try { out.pool = core.snapshot ? plain(core.snapshot()) : null; } catch (e) { out.pool = {error: String(e)}; }
  }
  document.querySelectorAll('video').forEach(function(v){
    var real = v.__obedFacadeFor;
    if (real) out.facades.push({elId: v.__obedElId == null ? null : v.__obedElId,
                                forElId: real.__obedElId == null ? null : real.__obedElId});
  });
  return out;
})()
"""

TWO_RAF_JS = (
    "new Promise(function(r){requestAnimationFrame(function(){requestAnimationFrame(function(){r(true);});});})"
)

# Independent instance evidence for the visible-content pass: pixels inside one
# expected rect cannot separate two live movies, so the DOM is asked which
# `<video>` elements can actually PAINT. A Magic-Move-settled slide paints
# through a stage-wide WebGL canvas with the DOM layer tree at opacity 0 -- such
# a video fails the paint test and is deliberately not listed, and an expected
# rect with no painting video is not an error (the player may be drawing it in
# WebGL; pixel liveness judges that). A browser without `checkVisibility` cannot
# answer this at all: it returns an error object, never a short list.
PAINTING_VIDEOS_JS = r"""
(function(){
  if (typeof Element.prototype.checkVisibility !== 'function') {
    return {error: 'checkVisibility is unavailable in this browser'};
  }
  function opacityProduct(el){
    var product = 1;
    for (var node = el; node && node.nodeType === 1; node = node.parentElement) {
      var value = parseFloat(window.getComputedStyle(node).opacity);
      product *= (isFinite(value) ? value : 1);
    }
    return product;
  }
  var out = [];
  document.querySelectorAll('video').forEach(function(v){
    if (!v.isConnected || !(v.readyState >= 2) || !(v.videoWidth > 0)) return;
    if (!v.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return;
    if (!(opacityProduct(v) > 0.02)) return;
    var r = v.getBoundingClientRect();
    if (!(r.width > 1 && r.height > 1)) return;
    if (r.right <= 0 || r.bottom <= 0 || r.left >= window.innerWidth || r.top >= window.innerHeight) return;
    out.push({
      src: String(v.currentSrc || v.src || '').split('/').pop(),
      elId: (v.__obedElId != null ? v.__obedElId : null),
      rect: {x: r.left, y: r.top, w: r.width, h: r.height}
    });
  });
  return out;
})()
"""

# The runtime's own pool/preserve census, read once at settle. A runtime that is
# not installed answers `null`; anything else that is not a list is an error
# object, never a silently clean census.
PRESERVE_SNAPSHOT_JS = r"""
(function(){
  try {
    if (!(window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.snapshot)) return null;
    return window.__OBED_P2_PRESERVE__.snapshot();
  } catch (e) { return {error: String(e)}; }
})()
"""

SAMPLER_JS = r"""
(function(){
  if (window.__obedContinuityProbe__) return true;
  var nextId = 1;
  var samples = [];
  var MAX_SAMPLES = 20000;
  function idFor(v){ if (v.__obedProbeId == null) v.__obedProbeId = nextId++; return v.__obedProbeId; }
  function stateOf(){
    try { return window.__obedLive ? window.__obedLive.snapshot() : {}; } catch (e) { return {}; }
  }
  // footprintOwnerDecoderId classifies a rect against a FIXED footprint table
  // (the static 1->2 slot) when no rect.key is given -- a rect away from that
  // slot (e.g. the moving/scaling 3->4 destination) is then unclassifiable and
  // returns via:'unknown-key', per its own documented contract ("the caller may
  // pin the asset key directly (rect.key) when it queries a rect the fixed
  // footprint table does not classify"). Resolve the key ourselves from the
  // already-public plan object (window.__OBED_CONTINUITY__, never mutated here)
  // the same way the runtime's own movieAssetKey() does, so ownership can be
  // asked about ANY on-screen position, not just the static footprint.
  function movieKeyFor(src){
    try {
      var plan = window.__OBED_CONTINUITY__;
      var movies = (plan && plan.movies) || {};
      var s = String(src || '').toLowerCase();
      for (var k in movies) {
        var keys = (movies[k] && movies[k].assetKeys) || [];
        for (var i = 0; i < keys.length; i++) {
          if (s.indexOf(String(keys[i]).toLowerCase()) >= 0) return k;
        }
      }
    } catch (e) {}
    return null;
  }
  function ownerOf(rect, src, map){
    try {
      if (!(window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.footprintOwnerDecoderId)) return null;
      if (!map) return null;
      var q = {x: (rect.x - map.ox) / map.s, y: (rect.y - map.oy) / map.s, w: rect.w / map.s, h: rect.h / map.s};
      var key = movieKeyFor(src);
      if (key) q.key = key;
      return window.__OBED_P2_PRESERVE__.footprintOwnerDecoderId(q);
    } catch (e) { return null; }
  }
""" + STAGE_MAP_FN_JS + r"""
  function tick(){
    var t = performance.now();
    var state = stateOf();
    var map = stageMapOf();
    var videos = [];
    document.querySelectorAll('video').forEach(function(v){
      var r = v.getBoundingClientRect();
      var rect = {x: r.left, y: r.top, w: r.width, h: r.height};
      var src = String(v.currentSrc || v.src || '').split('/').pop();
      videos.push({
        id: idFor(v),
        elId: (v.__obedElId != null ? v.__obedElId : null),
        src: src,
        currentTime: v.currentTime,
        paused: v.paused,
        readyState: v.readyState,
        videoWidth: v.videoWidth,
        isConnected: document.contains(v),
        rect: rect,
        footprintOwner: ownerOf(rect, v.currentSrc || v.src || '', map)
      });
    });
    samples.push({t: t, scene: state.sceneId, playerState: state.playerState, busy: state.busy, videos: videos, stageMap: map});
    if (samples.length > MAX_SAMPLES) samples.shift();
    window.__obedContinuityProbe__.raf = requestAnimationFrame(tick);
  }
  window.__obedContinuityProbe__ = {samples: samples};
  window.__obedContinuityProbe__.raf = requestAnimationFrame(tick);
  return true;
})();
"""

ENSURE_PLAYING_JS = (
    "Array.from(document.querySelectorAll('video')).forEach(function(v){"
    "try{v.muted=true;var p=v.play();if(p&&p.catch)p.catch(function(){});}catch(e){}});true"
)

# Use only the runtime-published handle; never acquire a context here.
_INPAGE_LIVENESS_JS_TEMPLATE = r"""
(async function(){
  function notApplicable(reason){ return {applicable: false, status: "n/a", reason: reason}; }
  function inconclusive(reason){ return {applicable: true, status: "inconclusive", reason: reason}; }
  var handle = window.__OBED_GL_ORACLE__;
  if (!handle) { return notApplicable('__ABSENT__'); }
  if (!handle.gl || !handle.canvas || !handle.video ||
      typeof handle.sample !== 'function' || typeof handle.markerBands !== 'function' ||
      typeof handle.pause !== 'function' || typeof handle.resume !== 'function') {
    return inconclusive('handle is present but malformed');
  }
  var expectedScene = window.__obedInpageSceneId;
  var rect = window.__obedInpageRect, instanceId = window.__obedInpageInstanceId;
  var canvas0 = handle.canvas, gl0 = handle.gl, video0 = handle.video;
  var epoch = handle.epoch;
  function liveSceneId(){
    try { return window.__obedLive ? window.__obedLive.snapshot().sceneId : null; } catch (e) { return null; }
  }
  function rectsEqual(a, b){
    return !!a && !!b && a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h;
  }
  function recheck(){
    if (window.__OBED_GL_ORACLE__ !== handle) return 'the runtime handle was replaced';
    if (handle.epoch !== epoch) return 'handle re-recorded during the sample window';
    if (handle.sceneId !== expectedScene || liveSceneId() !== expectedScene) {
      return 'handle scene does not match the scene being scored';
    }
    if (handle.canvas !== canvas0 || handle.gl !== gl0 || handle.video !== video0) {
      return 'handle canvas, gl, or video identity changed';
    }
    var stage = document.getElementById('stage');
    if (!stage || !stage.contains(canvas0)) return 'canvas is not a descendant of #stage';
    if (!canvas0.isConnected) return 'canvas disconnected';
    if (typeof gl0.isContextLost === 'function' && gl0.isContextLost()) return 'context lost';
    if (typeof canvas0.checkVisibility !== 'function' ||
        !canvas0.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) {
      return 'canvas is not visible';
    }
    if (!rectsEqual(handle.rect, rect)) return 'handle rect does not exactly match the scored instance rect';
    if (handle.instanceId !== instanceId) return 'handle instance does not match the scored instance';
    return null;
  }
  var problem = recheck();
  if (problem) { return inconclusive(problem); }
  var opacity = 1;
  for (var node = canvas0; node && node.nodeType === 1; node = node.parentElement) {
    var value = parseFloat(window.getComputedStyle(node).opacity);
    opacity *= (isFinite(value) ? value : 1);
  }
  if (opacity !== 1) { return inconclusive('canvas or an ancestor is not fully opaque'); }

  var markers = await handle.markerBands();
  problem = recheck();
  if (problem) { return inconclusive(problem); }
  if (!markers || markers.epoch !== epoch) {
    markers = await handle.markerBands();
    problem = recheck();
    if (problem) { return inconclusive(problem); }
    if (!markers || markers.epoch !== epoch) {
      return inconclusive('marker epoch does not match the sample epoch');
    }
  }

  var pausedDecoderSamples, samples;
  try {
    await handle.pause();
    problem = recheck();
    if (problem) { return inconclusive(problem); }
    pausedDecoderSamples = await handle.sample(__N__);
    problem = recheck();
    if (problem) { return inconclusive(problem); }
  } finally {
    await handle.resume();
  }
  problem = recheck();
  if (problem) { return inconclusive(problem); }
  samples = await handle.sample(__N__);
  problem = recheck();
  if (problem) { return inconclusive(problem); }

  return {
    applicable: true, status: "ok", canvasId: handle.canvasId, epoch: epoch,
    samples: samples, pausedDecoderSamples: pausedDecoderSamples,
    markerDark: markers.dark, markerLight: markers.light, markerEpoch: markers.epoch,
  };
})()
"""
INPAGE_HANDLE_ABSENT_REASON = "no __OBED_GL_ORACLE__ handle published"
INPAGE_LIVENESS_JS = _INPAGE_LIVENESS_JS_TEMPLATE.replace("__N__", str(INPAGE_MIN_SAMPLES)).replace(
    "__ABSENT__", INPAGE_HANDLE_ABSENT_REASON
)


def parse_viewport_arg(value: str) -> tuple[int, int]:
    """Launch-mode arms run at this viewport (the attach arm ignores it -- see
    `run_attach_arm`, fixed at `VIEWPORT_WIDTH`/`VIEWPORT_HEIGHT` by the live
    host's own attach contract)."""
    try:
        width, height = live_host_probe.parse_viewport(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid --viewport {value!r}: expected WxH") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError(f"invalid --viewport {value!r}: expected WxH") from None
    return width, height


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--original-index", type=Path, default=ORIGINAL_INDEX)
    parser.add_argument("--artifact", type=Path, default=ARTIFACT)
    parser.add_argument(
        "--viewport", type=parse_viewport_arg, default=(VIEWPORT_WIDTH, VIEWPORT_HEIGHT),
        help="Forced headless viewport for the launch-mode arms, e.g. 2560x1440 (default 1920x1080)",
    )
    parser.add_argument(
        "--burst-poke", action="store_true", default=False,
        help="1-px DOM style poke before each burst shot (mutates the deck under test; off by default)",
    )
    parser.add_argument(
        "--pass", dest="only_pass", choices=["G"], default=None,
        help="Run only this pass instead of the full A/B/C + V/Voff + attach run (currently only "
        "'G', the goTo autoplay-repair gate). Omit for the unchanged default full run.",
    )
    parser.add_argument(
        "--attach", action="store_true", default=False,
        help="Pass G only: run the attach-mode arm (click-advance path, forced to 1920x1080) "
        "instead of a launch-mode arm at --viewport.",
    )
    parser.add_argument(
        "--gl-replay", choices=["off", "auto"], default="off",
        help="GL replay for the continuity arms and a third visible pass Vgl (default off: today's run, unchanged)",
    )
    parser.add_argument(
        "--gl-force-fail", metavar="REASON", default=None,
        help="With --gl-replay auto: seed the module's debugForceFail and run only V and a forced Vgl "
        f"(one of {', '.join(GL_FORCE_FAIL_REASONS)}); status is forced-ok/forced-fail, never pass",
    )
    args = parser.parse_args(argv)
    if args.gl_force_fail is not None and (args.gl_replay != "auto" or args.only_pass is not None):
        parser.error("--gl-force-fail requires --gl-replay auto and the full run")
    return args


def prepare_export(fixture: Path, original_index: Path, tag: str) -> Path:
    """Mirror `live_host_probe.main`'s fixture prep: clone the already-built player
    export, then overwrite index.html with the UNMODIFIED one so the host's own
    `_program_html` injects everything fresh (the fixture's index.html already has
    P2's own script tags baked in, which would collide)."""
    destination = cache_dir(PROBE_DIGEST) / f"html-{tag}"
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixture, destination)
    shutil.copy2(original_index, destination / "index.html")
    return destination


def load_slides(export_root: Path) -> list[dict[str, Any]]:
    header = json.loads((export_root / "assets" / "header.json").read_text())
    return [
        {"originalOrdinal": index + 1, "playerIndex": index, "exportedUuid": slide, "skipped": False}
        for index, slide in enumerate(header["slideList"])
    ]


def force_viewport(width: int, height: int) -> None:
    forced = OutputDisplay(0, 0, 0, width, height + _HEIGHT_PAD, True)
    live_host_module.choose_display = lambda *_a, **_k: forced


def ground_truth_plan(export_root: Path, slides: list[dict[str, Any]], *, gl_replay: bool = False) -> ContinuityPlan:
    plan = derive_plan(export_root, slides, gl_replay=gl_replay)
    if isinstance(plan, Unsupported):
        raise SystemExit(f"fixture does not derive a continuity plan: {plan.reason}")
    return plan


def runtime_of(plan: ContinuityPlan) -> dict[str, Any]:
    """The runtime plan the host will install -- the probe's own source of truth for
    what each boundary is supposed to do. A plan that does not translate cannot be
    scored against any expectation at all."""
    runtime = plan.to_runtime()
    if isinstance(runtime, Unsupported):
        raise SystemExit(f"fixture's plan does not translate to a runtime plan: {runtime.reason}")
    return runtime


def matches_asset_keys(asset: Any, asset_keys: Sequence[str]) -> bool:
    """The runtime's own `movieAssetKey` test: an asset key is a lowercase substring
    of the source."""
    lowered = str(asset or "").lower()
    return any(key and str(key).lower() in lowered for key in asset_keys)


def runtime_asset_keys(runtime: dict[str, Any], movie_key: Any) -> list[str]:
    movie = (runtime.get("movies") or {}).get(movie_key)
    keys = movie.get("assetKeys") if isinstance(movie, dict) else None
    return [str(key).lower() for key in keys] if isinstance(keys, list) else []


def retire_fact(
    plan: ContinuityPlan, runtime: dict[str, Any], boundary_keys: dict[int, str]
) -> dict[str, Any] | None:
    """The one `retire` a runtime plan may carry, resolved to the boundary verdict it
    refuses, the destination slide it lands on, and the asset keys and authored rects
    its positive check needs. No retire => None, and every expectation below stays
    exactly what it was before refusals existed."""
    entries = [
        boundary for boundary in runtime.get("boundaries") or []
        if isinstance(boundary, dict) and boundary.get("action") == "retire"
    ]
    if not entries:
        return None
    if len(entries) > 1:
        raise SystemExit("runtime plan carries more than one retire boundary")
    entry = entries[0]
    scene, movie_key = entry.get("atScene"), entry.get("movieKey")
    boundary_key = boundary_keys.get(scene)
    if boundary_key is None:
        raise SystemExit(f"retire boundary at scene {scene!r} is not one of the boundaries under test")
    asset_keys = runtime_asset_keys(runtime, movie_key)
    if not asset_keys:
        raise SystemExit(f"retire boundary names movie key {movie_key!r}, which the plan does not define")
    player_index = next((p for p, s in plan.scene_index_by_player.items() if s == scene), None)
    if player_index is None:
        raise SystemExit(f"retire boundary at scene {scene} has no destination slide")
    rects = [
        _authored_rect(rect)
        for asset, instances in (plan.slide_instances.get(player_index) or {}).items()
        if matches_asset_keys(asset, asset_keys)
        for rect in instances
    ]
    if not rects:
        raise SystemExit(f"retired movie {movie_key!r} has no authored instance on player index {player_index}")
    return {
        "movieKey": movie_key,
        "atScene": scene,
        "boundaryKey": boundary_key,
        "verdictKey": REFUSAL_VERDICT_KEY[boundary_key],
        "playerIndex": player_index,
        "originalOrdinal": player_index + 1,
        "assetKeys": asset_keys,
        "rects": rects,
    }


def armed_fact(
    plan: ContinuityPlan, runtime: dict[str, Any], boundary_keys: dict[int, str]
) -> dict[str, Any]:
    """The flag-on plan's single `glReplay` boundary and its geometry (plan g5g6 §3.2); fails closed."""
    entries = [
        boundary for boundary in runtime.get("boundaries") or []
        if isinstance(boundary, dict) and boundary.get("action") == "glReplay"
    ]
    if len(entries) != 1:
        raise SystemExit(f"flag-on runtime plan carries {len(entries)} glReplay boundaries, expected exactly one")
    entry = entries[0]
    scene, movie_key = entry.get("atScene"), entry.get("movieKey")
    boundary_key = boundary_keys.get(scene)
    if boundary_key not in ARMED_VERDICT_KEY:
        raise SystemExit(f"glReplay boundary at scene {scene!r} is not an armable boundary under test")
    asset_keys = runtime_asset_keys(runtime, movie_key)
    if not asset_keys:
        raise SystemExit(f"glReplay boundary names movie key {movie_key!r}, which the plan does not define")
    player_index = next((p for p, s in plan.scene_index_by_player.items() if s == scene), None)
    if player_index is None:
        raise SystemExit(f"glReplay boundary at scene {scene} has no destination slide")
    by_asset = plan.slide_instances.get(player_index) or {}
    rects = [
        _authored_rect(rect)
        for asset, instances in by_asset.items() if matches_asset_keys(asset, asset_keys)
        for rect in instances
    ]
    labelled = {
        f"{asset}#{index}": _authored_rect(rect)
        for asset, instances in by_asset.items() if matches_asset_keys(asset, asset_keys)
        for index, rect in enumerate(instances, start=1)
    }
    movie_slot = entry.get("movieSlot")
    try:
        slot_rects = [
            {"x": float(r[0]), "y": float(r[1]), "w": float(r[2]), "h": float(r[3])} for r in entry["slotRects"]
        ]
        instance_rect = _authored_rect(entry.get("instanceRect"))
        override_slots = sorted({int(item["slot"]) for item in entry["opacityOverrides"]})
    except (TypeError, KeyError, IndexError, ValueError, VisiblePassError) as exc:
        raise SystemExit(f"glReplay boundary geometry is unreadable: {exc}") from None
    if (
        isinstance(movie_slot, bool) or not isinstance(movie_slot, int) or not 0 <= movie_slot < len(slot_rects)
        or any(not 0 <= slot < len(slot_rects) for slot in override_slots)
    ):
        raise SystemExit("glReplay boundary names a slot outside its slot table")
    instance_id = entry.get("instanceId")
    if labelled.get(instance_id) != instance_rect:
        raise SystemExit(f"glReplay instance {instance_id!r} is not the authored destination instance it names")
    return {
        "movieKey": movie_key,
        "atScene": scene,
        "boundaryKey": boundary_key,
        "verdictKey": ARMED_VERDICT_KEY[boundary_key],
        "playerIndex": player_index,
        "originalOrdinal": player_index + 1,
        "assetKeys": asset_keys,
        "rects": rects,
        "instanceId": instance_id,
        "instanceRect": instance_rect,
        "movieSlot": movie_slot,
        "slotRects": slot_rects,
        "overrideSlots": override_slots,
    }


def rect_expectations(
    plan: ContinuityPlan, runtime: dict[str, Any], *, continuity_on: bool
) -> dict[int, dict[str, str]]:
    """Per slide, per asset: live or dead, derived from the plan alone.

    The first slide is live. The destination of a restart or a bridge is live in
    both passes (the export starts a fresh element there). The destination of a
    RETIRED boundary is dead in both. The destination of a carried (implicit pin)
    boundary is live with the runtime installed and dead without it -- a
    geometry-static Magic Move leaves the raw player's movie frozen.
    """
    retired_by_scene: dict[Any, list[str]] = {}
    action_by_scene: dict[Any, str] = {}
    for boundary in runtime.get("boundaries") or []:
        if not isinstance(boundary, dict):
            continue
        scene = boundary.get("atScene")
        if boundary.get("action") == "retire":
            retired_by_scene.setdefault(scene, []).extend(runtime_asset_keys(runtime, boundary.get("movieKey")))
        else:
            action_by_scene[scene] = str(boundary.get("action"))
    expectations: dict[int, dict[str, str]] = {}
    for position, player_index in enumerate(sorted(plan.scene_index_by_player)):
        scene = plan.scene_index_by_player[player_index]
        action = action_by_scene.get(scene)
        retired = retired_by_scene.get(scene) or []
        per_asset: dict[str, str] = {}
        for asset in plan.slide_instances.get(player_index) or {}:
            if position == 0:
                per_asset[asset] = LIVE
            elif matches_asset_keys(asset, retired):
                per_asset[asset] = DEAD
            elif action in ("restart", "bridge"):
                per_asset[asset] = LIVE
            elif action == "glReplay":
                per_asset[asset] = LIVE if continuity_on else DEAD
            else:
                per_asset[asset] = LIVE if continuity_on else DEAD
        expectations[player_index] = per_asset
    return expectations


def visible_expectations(plan: ContinuityPlan, runtime: dict[str, Any]) -> dict[str, dict[int, dict[str, str]]]:
    return {
        "V": rect_expectations(plan, runtime, continuity_on=True),
        "Voff": rect_expectations(plan, runtime, continuity_on=False),
    }


def ground_truth_facts(plan: ContinuityPlan, *, armed: bool = False) -> dict[str, Any]:
    """Independent, offline ground truth (never injected into the host): the
    bridging asset, the scene onset of each of the three boundaries under test, and
    the authored rects the tracked decoder must be on-screen at either side of each
    boundary (reviewer finding #1: "same id existed sometime before/after" is not
    enough -- it must be at the RIGHT rect, not merely present somewhere)."""
    bridge = None
    pin = None
    for boundary in plan.boundaries:
        for movie in boundary.movies:
            if movie.action == "bridge":
                bridge = (boundary, movie)
            elif movie.action == "pin" and pin is None:
                pin = (boundary, movie)
    if bridge is None:
        raise SystemExit("fixture has no bridge boundary (expected the 3->4 moving Magic Move)")
    if pin is None:
        raise SystemExit("fixture has no pin boundary (expected the 1->2 static Magic Move)")
    _, bridge_movie = bridge
    _, pin_movie = pin
    ordered_players = sorted(plan.scene_index_by_player)
    if len(ordered_players) < 4:
        raise SystemExit("fixture must have at least 4 slides")
    pin_rect = (pin_movie.dst_rect or pin_movie.src_rect)
    if pin_rect is None or bridge_movie.src_rect is None or bridge_movie.dst_rect is None:
        raise SystemExit("fixture's continuity plan is missing a required rect")
    facts = {
        "asset": bridge_movie.asset,
        "onset1to2": plan.scene_index_by_player[ordered_players[1]],
        "boundaryPlayerIndex": ordered_players[1],
        "restartScene": plan.scene_index_by_player[ordered_players[2]],
        "bridgeScene": plan.scene_index_by_player[ordered_players[3]],
        "pinRect": pin_rect.as_dict(),
        "bridgeSrcRect": bridge_movie.src_rect.as_dict(),
        "destRect": bridge_movie.dst_rect.as_dict(),
        "canvas": dict(plan.canvas),
    }
    runtime = runtime_of(plan)
    boundary_keys = {
        facts["onset1to2"]: "continue1to2",
        facts["restartScene"]: "restart2to3",
        facts["bridgeScene"]: "continue3to4",
    }
    retire = retire_fact(plan, runtime, boundary_keys)
    facts["retire"] = retire
    facts["refusedBoundaries"] = [retire["boundaryKey"]] if retire else []
    facts["refusals"] = [dict(item) for item in getattr(plan, "refusals", ()) if isinstance(item, dict)]
    facts["rectExpectations"] = visible_expectations(plan, runtime)
    if armed:
        facts["armed"] = armed_fact(plan, runtime, boundary_keys)
        facts["armedBoundaries"] = [facts["armed"]["boundaryKey"]]
    return facts


def gl_replay_mode(entry: Any) -> str | None:
    continuity = entry.get("continuity") if isinstance(entry, dict) else None
    gl = continuity.get("glReplay") if isinstance(continuity, dict) else None
    return gl.get("mode") if isinstance(gl, dict) else None


def facts_for(
    continuity: Any, facts_off: dict[str, Any], facts_on: dict[str, Any] | None
) -> dict[str, Any]:
    """The flag-on facts only when the host reports the module injected (plan g5g6 D2)."""
    if facts_on is not None and gl_replay_mode({"continuity": continuity}) == "injected":
        return facts_on
    return facts_off


def check_vgl_expectations(
    v: dict[int, dict[str, str]], vgl: dict[int, dict[str, str]], armed: dict[str, Any]
) -> None:
    """Vgl may differ from V only at the armed movie, dead in V and live in Vgl."""
    diffs = {
        (index, asset)
        for index in set(v) | set(vgl)
        for asset in set(v.get(index) or {}) | set(vgl.get(index) or {})
        if (v.get(index) or {}).get(asset) != (vgl.get(index) or {}).get(asset)
    }
    index = armed["playerIndex"]
    wanted = {(index, asset) for asset in vgl.get(index) or {} if matches_asset_keys(asset, armed["assetKeys"])}
    if not wanted or diffs != wanted or any(
        v[i][asset] != DEAD or vgl[i][asset] != LIVE for i, asset in wanted
    ):
        raise SystemExit(f"Vgl expectations differ from V at {sorted(diffs)}, expected exactly {sorted(wanted)}")


@contextmanager
def bridge_disabled() -> Iterator[None]:
    """Arm C only: strip the bridge boundary from every derived runtime plan inside
    this probe PROCESS -- a monkeypatch of `ContinuityPlan.to_runtime`, never a
    product code path. The pin (1->2) and restart (2->3) behaviour are untouched;
    with no bridge boundary the runtime's own `slide4MinHash()` is null, so the
    3->4 magic move falls through to the export's native (broken) restart."""
    original = live_continuity_module.ContinuityPlan.to_runtime

    def patched(self: ContinuityPlan) -> dict[str, Any] | Unsupported:
        runtime = original(self)
        if isinstance(runtime, Unsupported):
            return runtime
        runtime = dict(runtime)
        runtime["boundaries"] = [b for b in runtime.get("boundaries", []) if b.get("action") != "bridge"]
        return runtime

    live_continuity_module.ContinuityPlan.to_runtime = patched
    try:
        yield
    finally:
        live_continuity_module.ContinuityPlan.to_runtime = original


def wait_for_decode(player: LiveOutputHost, timeout_s: float = VIDEO_DECODE_TIMEOUT_S) -> bool:
    transport = player._require_transport()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        ok = transport.evaluate(
            "Array.from(document.querySelectorAll('video')).some("
            "function(v){return v.readyState>=2&&v.videoWidth>0;})"
        )
        if ok:
            return True
        time.sleep(0.1)
    return False


def advance_until_original_slide(
    player: LiveOutputHost, target: int, *, max_steps: int = MAX_ADVANCE_STEPS, settle_s: float = POST_ADVANCE_SETTLE_S
) -> None:
    """Click 'advance' until the host reports it is showing `target` (1-based
    original ordinal), tolerating busy/rejected states the way an operator would --
    never a bare sleep as proof of arrival."""
    for _ in range(max_steps):
        observed = player.observe()
        if observed.original_slide == target:
            return
        if observed.busy:
            time.sleep(0.1)
            continue
        if not player.capabilities()["advance"]["supported"]:
            raise RuntimeError(f"cannot advance further toward slide {target}; stuck at {observed.original_slide}")
        try:
            player.execute("advance")
        except PlayerCommandRejected:
            time.sleep(0.1)
            continue
        time.sleep(settle_s)
    observed = player.observe()
    if observed.original_slide != target:
        raise RuntimeError(f"did not reach slide {target}; stopped at {observed.original_slide}")


def drive_and_sample(
    player: LiveOutputHost, *, observer: Callable[[int], None] | None = None
) -> list[dict[str, Any]]:
    """Slide 2 is the 1->2 magic move, 3 the dissolve (which may straddle slide-2
    builds), 4 the 3->4 magic move. `observer` is called once on each settled slide
    -- the only hook the refusal evidence needs, and never a screenshot."""
    transport = player._require_transport()
    transport.evaluate(SAMPLER_JS)
    transport.evaluate(ENSURE_PLAYING_JS)
    wait_for_decode(player)
    time.sleep(CLICK_DELAY_S)
    for ordinal in (2, 3, 4):
        advance_until_original_slide(player, ordinal)
        if observer is not None:
            observer(ordinal)
    time.sleep(POST_ADVANCE_SETTLE_S)
    samples = transport.evaluate("window.__obedContinuityProbe__.samples")
    return samples if isinstance(samples, list) else []


def track_by_id(samples: list[dict[str, Any]], asset_substr: str) -> dict[int, list[dict[str, Any]]]:
    tracks: dict[int, list[dict[str, Any]]] = {}
    for sample in samples:
        for video in sample.get("videos") or []:
            src = str(video.get("src") or "").lower()
            if asset_substr in src:
                row = dict(video)
                row["t"] = sample.get("t")
                row["scene"] = sample.get("scene")
                row["playerState"] = sample.get("playerState")
                row["busy"] = sample.get("busy")
                tracks.setdefault(video["id"], []).append(row)
    return tracks


def decoded_anywhere(tracks: dict[int, list[dict[str, Any]]]) -> bool:
    return any(
        (row.get("readyState") or 0) >= 2 and (row.get("videoWidth") or 0) > 0
        for rows in tracks.values()
        for row in rows
    )


def stage_map_valid(stage_map: dict[str, Any] | None) -> bool:
    """Fail-closed: missing `#stage`, a zero box, or a non-uniform scale (`|s -
    sy| / s` over 0.1%) is invalid, never silently treated as identity."""
    if not isinstance(stage_map, dict):
        return False
    s, sy = stage_map.get("s"), stage_map.get("sy")
    ow, oh = stage_map.get("offsetWidth"), stage_map.get("offsetHeight")
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (s, sy, ow, oh)):
        return False
    return abs(s - sy) / s <= 0.001


def to_authored_rect(rect: dict[str, float], stage_map: dict[str, Any]) -> dict[str, float]:
    s = stage_map["s"]
    return {
        "x": (rect["x"] - stage_map["ox"]) / s,
        "y": (rect["y"] - stage_map["oy"]) / s,
        "w": rect["w"] / s,
        "h": rect["h"] / s,
    }


def convert_samples_to_authored(samples: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Convert every sampled `<video>` rect from screen to AUTHORED space using
    that sample's own recorded stage map, before any scoring runs -- so every
    existing threshold and red control (all authored) applies unchanged. The
    raw screen rect is kept under `rectScreen` for evidence; a missing/invalid
    stage map leaves `rect` as None, a scoring failure (see `stageMapInvalid`
    in `score_continuity`), never a silent skip."""
    converted: list[dict[str, Any]] = []
    invalid_count = 0
    for entry in samples:
        stage_map = entry.get("stageMap")
        valid = stage_map_valid(stage_map)
        if not valid:
            invalid_count += 1
        new_entry = dict(entry)
        new_videos = []
        for video_row in entry.get("videos") or []:
            new_video = dict(video_row)
            screen_rect = video_row.get("rect")
            new_video["rectScreen"] = screen_rect
            new_video["rect"] = to_authored_rect(screen_rect, stage_map) if valid and isinstance(screen_rect, dict) else None
            new_video["stageMapValid"] = valid
            new_videos.append(new_video)
        new_entry["videos"] = new_videos
        new_entry["stageMapValid"] = valid
        converted.append(new_entry)
    return converted, invalid_count


def expected_stage_fit(canvas: dict[str, Any], viewport: dict[str, Any]) -> dict[str, float]:
    """Aspect-fit of the authored `canvas` into `viewport` -- the stage map the
    player's own `adjustStageToFit` should have produced."""
    fit = live_host_probe.expected_fit(canvas, viewport)
    scale = min(viewport["width"] / canvas["width"], viewport["height"] / canvas["height"])
    return {**fit, "scale": scale}


def stage_screen_rect(stage_map: dict[str, Any]) -> dict[str, float]:
    return {
        "x": stage_map["ox"], "y": stage_map["oy"],
        "width": stage_map["offsetWidth"] * stage_map["s"], "height": stage_map["offsetHeight"] * stage_map["sy"],
    }


def stage_fit_matches(observed: dict[str, float], expected: dict[str, float], tol_px: float = 1.0, tol_rel: float = 0.001) -> bool:
    return all(
        abs(observed[key] - expected[key]) <= max(tol_px, abs(expected[key]) * tol_rel)
        for key in ("x", "y", "width", "height")
    )


def score_stage_fit(samples: list[dict[str, Any]], expected: dict[str, float]) -> dict[str, Any]:
    """A wrong stage fit fails the arm outright: the authored conversion is
    only meaningful against a correctly fitted stage. Boundary scoring only
    ever looks inside the selected decoder's crossing windows, so a
    missing/non-uniform stage-map sample OUTSIDE those windows would
    otherwise never be noticed -- require zero invalid samples across the
    WHOLE arm, not just the fitted ones, and zero samples at all is "no
    evidence", never a pass."""
    valid_maps = [entry["stageMap"] for entry in samples if entry.get("stageMapValid")]
    invalid_count = sum(1 for entry in samples if not entry.get("stageMapValid"))
    if not samples or not valid_maps:
        return {
            "verdict": False, "reason": "no valid stage map samples",
            "sampleCount": len(valid_maps), "invalidCount": invalid_count, "expected": expected,
        }
    mismatches = [stage_screen_rect(m) for m in valid_maps if not stage_fit_matches(stage_screen_rect(m), expected)]
    return {
        "verdict": not mismatches and invalid_count == 0,
        "sampleCount": len(valid_maps), "mismatchCount": len(mismatches), "invalidCount": invalid_count,
        "expected": expected,
    }


def stage_map_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    valid_maps = [entry["stageMap"] for entry in samples if entry.get("stageMapValid")]
    if not valid_maps:
        return {"sampleCount": 0}
    return {
        "sampleCount": len(valid_maps),
        "sMin": min(m["s"] for m in valid_maps), "sMax": max(m["s"] for m in valid_maps),
        "oxMin": min(m["ox"] for m in valid_maps), "oxMax": max(m["ox"] for m in valid_maps),
        "oyMin": min(m["oy"] for m in valid_maps), "oyMax": max(m["oy"] for m in valid_maps),
    }


def rect_matches(rect: dict[str, float] | None, expected: dict[str, float], tolerance: float = RECT_TOLERANCE_PX) -> bool:
    if not isinstance(rect, dict):
        return False
    return all(abs(rect.get(key, 1e9) - expected[key]) <= tolerance for key in ("x", "y", "w", "h"))


def path_progress(
    rect: dict[str, float] | None, src: dict[str, float], dst: dict[str, float], tolerance: float
) -> float | None:
    if not isinstance(rect, dict):
        return None
    keys = ("x", "y", "w", "h")
    if any(not isinstance(rect.get(key), (int, float)) or not math.isfinite(rect[key]) for key in keys):
        return None
    deltas = {key: dst[key] - src[key] for key in keys}
    length_squared = sum(delta * delta for delta in deltas.values())
    if not length_squared:
        return None
    progress = sum((rect[key] - src[key]) * deltas[key] for key in keys) / length_squared
    progress = min(1.0, max(0.0, progress))
    expected = {key: src[key] + progress * deltas[key] for key in keys}
    return progress if rect_matches(rect, expected, tolerance) else None


def is_move_sample(row: dict[str, Any], transition_scene: float | None) -> bool:
    return (
        transition_scene is not None
        and row.get("scene") == transition_scene
        and row.get("playerState") == "Playing"
        and row.get("busy") is True
    )


def is_move_complete(row: dict[str, Any], transition_scene: float | None) -> bool:
    """The move has finished but the player has not yet cut to the next scene:
    still `transition_scene`, but no longer the `Playing`+busy move sample. Real
    traces show the player pass through more than one such state before the cut
    (`IdleAtFinalState`, then `WaitingToJump`, then `SettingUpScene`) -- the movie
    is already parked at the destination rect throughout all of them, so every one
    of them is a "move complete" sample, not only the first."""
    return (
        transition_scene is not None
        and row.get("scene") == transition_scene
        and not is_move_sample(row, transition_scene)
    )


def score_motion(
    rows: list[dict[str, Any]], src: dict[str, float], dst: dict[str, float], tolerance: float
) -> dict[str, Any]:
    progress = [path_progress(row.get("rect"), src, dst, tolerance) for row in rows]
    errors = []
    if not rows:
        errors.append("moving transition not observed")
    elif any(value is None for value in progress):
        errors.append("transition rectangle leaves the shared source-to-destination path")
    else:
        jitter = tolerance / max(abs(dst[key] - src[key]) for key in src)
        if progress[0] > 0.1:
            errors.append("transition begins away from the source")
        if progress[-1] < 0.9:
            errors.append("transition does not approach the destination")
        peak = progress[0]
        for value in progress[1:]:
            if value < peak - jitter:
                errors.append("transition progress reverses")
                break
            peak = max(peak, value)
        if any(b - a > 0.25 for a, b in zip([0.0, *progress], [*progress, 1.0])):
            errors.append("transition jumps over the path")
        interior = [value for value in progress if 0.1 < value < 0.9]
        if len(interior) < 3 or min(interior, default=1.0) > 0.25 or max(interior, default=0.0) < 0.75:
            errors.append("transition lacks meaningful interior samples")
    return {"sampleCount": len(rows), "progress": progress, "errors": errors}


def find_boundary_window(
    samples: list[dict[str, Any]], boundary_scene: float, *, pad_s: float = WINDOW_PAD_S
) -> dict[str, float] | None:
    """The window a continuity verdict is scored over: from the last settled sample
    with `scene < boundary_scene` to the first settled sample with `scene >=
    boundary_scene`, padded by `pad_s` on each side and clipped to the samples
    actually collected. Returns None if the crossing never happened (both sides of
    the boundary must be represented and ordered)."""
    times = [s["t"] for s in samples if s.get("t") is not None]
    if not times:
        return None
    before_times = [s["t"] for s in samples if s.get("scene") is not None and s["scene"] < boundary_scene]
    after_times = [s["t"] for s in samples if s.get("scene") is not None and s["scene"] >= boundary_scene]
    if not before_times or not after_times:
        return None
    last_before = max(before_times)
    first_after = min(after_times)
    if last_before >= first_after:
        return None
    lo, hi = min(times), max(times)
    return {
        "start": max(last_before - pad_s * 1000.0, lo),
        "end": min(first_after + pad_s * 1000.0, hi),
        "lastBeforeT": last_before,
        "firstAfterT": first_after,
    }


def _longest_stall_run(rows: list[dict[str, Any]], max_stall_s: float) -> dict[str, Any]:
    """Accumulate the duration of CONSECUTIVE samples where the unpaused decoder's
    clock did not advance (reviewer finding #2: comparing only consecutive ~16ms
    rAF samples against the threshold never sees a multi-second freeze spread over
    many non-advancing samples). Returns the longest such accumulated run and
    whether it exceeds `max_stall_s`."""
    longest_s = 0.0
    longest_end_ms: float | None = None
    run_s = 0.0
    for a, b in zip(rows, rows[1:]):
        dt_wall = (b["t"] - a["t"]) / 1000.0
        d_clock = b["currentTime"] - a["currentTime"]
        frozen = d_clock <= 1e-3 and not b.get("paused")
        if frozen:
            run_s += dt_wall
            if run_s > longest_s:
                longest_s = run_s
                longest_end_ms = b["t"]
        else:
            run_s = 0.0
    stalled = longest_s > max_stall_s
    return {"longestStallS": round(longest_s, 3), "stalled": stalled, "longestStallEndMs": longest_end_ms}


def score_continuity(
    samples: list[dict[str, Any]],
    asset_substr: str,
    boundary_scene: float,
    src_rect: dict[str, float],
    dst_rect: dict[str, float],
    runtime_installed: bool,
    *,
    min_advance_s: float = MIN_ADVANCE_S,
    max_stall_s: float = MAX_STALL_S,
    max_drop_s: float = MAX_DROP_S,
    rect_tolerance: float = RECT_TOLERANCE_PX,
    pad_s: float = WINDOW_PAD_S,
    transition_scene: float | None = None,
) -> dict[str, Any]:
    """Pure: samples in, verdict dict out. Scores continuity of ONE tracked decoder
    across `boundary_scene`, evaluated only within the crossing window (reviewer
    finding #1), requiring (all within the window):
      - the same element id present in every sampled frame in the window;
      - when `runtime_installed`, every after-cut sample reports that element (by
        the continuity runtime's own `footprintOwnerDecoderId`) as footprint owner;
      - connected at the authored source before / destination after (3px);
      - only a specified Playing transition scene may use a monotonic shared
        source-to-destination path; its IdleAtFinalState must be at destination;
      - a monotonic clock (no drop beyond float jitter);
      - the longest zero-advance run at or under `max_stall_s`;
      - total clock advance within the window at least `min_advance_s`.
    """
    tracks = track_by_id(samples, asset_substr)
    if not decoded_anywhere(tracks):
        return {"verdict": None, "reason": "inconclusive: movie never decoded"}
    window = find_boundary_window(samples, boundary_scene, pad_s=pad_s)
    if window is None:
        return {"verdict": False, "reason": "boundary crossing not observed in samples"}
    if transition_scene is not None:
        # Ground the window's start at the first SETTLED sample of the from-slide's
        # own scene (transition_scene - 1), not a blind pad_s before the crossing
        # into transition_scene: a deliberate decoder restart can sit right before
        # the move, and padding further back reaches into the PRIOR scene, before
        # that restart, where the continuing decoder cannot exist yet -- any
        # missing sample there would be a false failure, not evidence of anything.
        # Grounding here still covers the entire move (which starts later, inside
        # transition_scene) and the settled source phase that precedes it.
        settled_source_times = [
            s["t"]
            for s in samples
            if s.get("scene") == transition_scene - 1 and s.get("busy") is False
        ]
        if settled_source_times:
            window["start"] = min(window["start"], min(settled_source_times))
        else:
            move_window = find_boundary_window(samples, transition_scene, pad_s=pad_s)
            if move_window is not None:
                window["start"] = min(window["start"], move_window["start"])
    windowed = {
        element_id: [r for r in rows if window["start"] <= r["t"] <= window["end"]]
        for element_id, rows in tracks.items()
    }
    windowed = {element_id: rows for element_id, rows in windowed.items() if rows}
    before_ids = {i for i, rows in windowed.items() if any(r["scene"] is not None and r["scene"] < boundary_scene for r in rows)}
    after_ids = {i for i, rows in windowed.items() if any(r["scene"] is not None and r["scene"] >= boundary_scene for r in rows)}
    common = before_ids & after_ids
    if not common:
        return {
            "verdict": False,
            "reason": "no decoder id spans the boundary within the window",
            "beforeIds": sorted(before_ids),
            "afterIds": sorted(after_ids),
            "window": window,
        }
    def _at_expected_rect(row: dict[str, Any]) -> bool:
        if is_move_sample(row, transition_scene):
            return path_progress(row.get("rect"), src_rect, dst_rect, rect_tolerance) is not None
        scene = row.get("scene")
        expected = dst_rect if is_move_complete(row, transition_scene) or (scene is not None and scene >= boundary_scene) else src_rect
        return rect_matches(row.get("rect"), expected, rect_tolerance)

    def _candidate_score(rows: list[dict[str, Any]]) -> tuple[int, int, int]:
        owned = 0
        if runtime_installed:
            for row in rows:
                owner = row.get("footprintOwner")
                if isinstance(owner, dict) and owner.get("elId") is not None and owner.get("elId") == row.get("elId"):
                    owned += 1
        return owned, sum(1 for row in rows if _at_expected_rect(row)), len(rows)

    element_id = max(sorted(common), key=lambda i: _candidate_score(windowed[i]))
    rows = sorted(windowed[element_id], key=lambda r: r["t"])
    before_rows = [r for r in rows if r["scene"] is not None and r["scene"] < boundary_scene]
    after_rows = [r for r in rows if r["scene"] is not None and r["scene"] >= boundary_scene]

    missing_samples = [
        {"t": sample["t"], "scene": sample.get("scene"), "playerState": sample.get("playerState")}
        for sample in samples
        if window["start"] <= sample["t"] <= window["end"]
        and not any(video.get("id") == element_id for video in sample.get("videos") or [])
    ]

    max_drop = 0.0
    for a, b in zip(rows, rows[1:]):
        d_clock = b["currentTime"] - a["currentTime"]
        if d_clock < 0:
            max_drop = max(max_drop, -d_clock)
    stall = _longest_stall_run(rows, max_stall_s)
    advance = rows[-1]["currentTime"] - rows[0]["currentTime"]

    move_rows = [r for r in before_rows if is_move_sample(r, transition_scene)]
    completed_move_rows = [r for r in before_rows if is_move_complete(r, transition_scene)]
    motion = score_motion(move_rows, src_rect, dst_rect, rect_tolerance) if transition_scene is not None else None
    if motion is not None and not any(
        r.get("busy") is False and not is_move_complete(r, transition_scene) for r in before_rows
    ):
        motion["errors"].append("settled source not observed")

    owner_mismatches: list[dict[str, Any]] = []
    if runtime_installed:
        for r in [*move_rows, *completed_move_rows, *after_rows]:
            owner = r.get("footprintOwner")
            owned = isinstance(owner, dict) and owner.get("elId") is not None and owner.get("elId") == r.get("elId")
            if not owned:
                owner_mismatches.append({"t": r["t"], "footprintOwner": owner, "elId": r.get("elId")})

    rect_mismatches: list[dict[str, Any]] = []
    for r in before_rows:
        if not (r.get("isConnected") and _at_expected_rect(r)):
            rect_mismatches.append({"t": r["t"], "phase": "before", "rect": r.get("rect"), "isConnected": r.get("isConnected")})
    for r in after_rows:
        if not (r.get("isConnected") and rect_matches(r.get("rect"), dst_rect, rect_tolerance)):
            rect_mismatches.append({"t": r["t"], "phase": "after", "rect": r.get("rect"), "isConnected": r.get("isConnected")})

    stage_map_invalid: list[dict[str, Any]] = []
    for r in before_rows:
        if r.get("stageMapValid") is False:
            stage_map_invalid.append({"t": r["t"], "phase": "before"})
    for r in after_rows:
        if r.get("stageMapValid") is False:
            stage_map_invalid.append({"t": r["t"], "phase": "after"})

    ok = (
        max_drop <= max_drop_s
        and advance >= min_advance_s
        and not stall["stalled"]
        and not owner_mismatches
        and not rect_mismatches
        and not missing_samples
        and not stage_map_invalid
        and (motion is None or not motion["errors"])
    )
    return {
        "verdict": ok,
        "elementId": element_id,
        "windowAdvanceS": round(advance, 3),
        "maxDropS": round(max_drop, 3),
        "longestStallS": stall["longestStallS"],
        "sampleCount": len(rows),
        "finalRect": rows[-1]["rect"],
        "ownerMismatches": owner_mismatches,
        "rectMismatches": rect_mismatches,
        "missingSamples": missing_samples,
        "stageMapInvalid": stage_map_invalid,
        "motion": motion,
        "window": window,
    }


def score_restart(
    samples: list[dict[str, Any]], asset_substr: str, boundary_scene: float, *, max_start_s: float = RESTART_MAX_START_S
) -> dict[str, Any]:
    """Pure: samples in, verdict dict out. A restart is a genuinely NEW decoder id
    (never seen anywhere with `scene < boundary_scene`, at any time in the run, not
    just within a window) whose own clock starts near zero shortly after the cut."""
    tracks = track_by_id(samples, asset_substr)
    if not decoded_anywhere(tracks):
        return {"verdict": None, "reason": "inconclusive: movie never decoded"}
    before_ids = {i for i, rows in tracks.items() if any(r["scene"] is not None and r["scene"] < boundary_scene for r in rows)}
    after_ids = {i for i, rows in tracks.items() if any(r["scene"] is not None and r["scene"] >= boundary_scene for r in rows)}
    fresh_ids = after_ids - before_ids
    if not fresh_ids:
        return {"verdict": False, "reason": "no distinct decoder id after the boundary", "beforeIds": sorted(before_ids)}

    def first_after_time(i: int) -> float:
        rows = [r for r in tracks[i] if r["scene"] is not None and r["scene"] >= boundary_scene]
        return min((r["t"] for r in rows), default=float("inf"))

    element_id = min(fresh_ids, key=first_after_time)
    rows = sorted((r for r in tracks[element_id] if r["scene"] is not None and r["scene"] >= boundary_scene), key=lambda r: r["t"])
    start_time = rows[0]["currentTime"] if rows else None
    ok = start_time is not None and start_time < max_start_s
    return {"verdict": ok, "elementId": element_id, "startTimeS": start_time, "freshIds": sorted(fresh_ids)}


def score_boundaries(samples: list[dict[str, Any]], facts: dict[str, Any], runtime_installed: bool) -> dict[str, Any]:
    """Pure: samples + ground truth in, the three boundary verdicts out."""
    asset = facts["asset"]
    v12 = score_continuity(samples, asset, facts["onset1to2"], facts["pinRect"], facts["pinRect"], runtime_installed)
    v23 = score_restart(samples, asset, facts["restartScene"])
    v34 = score_continuity(
        samples, asset, facts["bridgeScene"], facts["bridgeSrcRect"], facts["destRect"], runtime_installed,
        transition_scene=facts["bridgeScene"] - 1,
    )
    return {"continue1to2": v12, "restart2to3": v23, "continue3to4": v34}


def rects_overlap(a: dict[str, float], b: dict[str, float], min_px: float = REFUSAL_OVERLAP_MIN_PX) -> bool:
    return (
        min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]) > min_px
        and min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]) > min_px
    )


def refusal_evidence(transport: Any) -> dict[str, Any]:
    """One lightweight triple of `evaluate`s on a settled slide -- never per rAF and
    never a screenshot, either of which would perturb the arms' sampler clock."""
    return {
        "stageMap": transport.evaluate(STAGE_MAP_JS),
        "painting": transport.evaluate(PAINTING_VIDEOS_JS),
        "poolSnapshot": transport.evaluate(PRESERVE_SNAPSHOT_JS),
    }


def refusal_observer(
    player: Any, facts: dict[str, Any], out: dict[str, Any]
) -> Callable[[int], None] | None:
    retire = facts.get("retire")
    if not retire:
        return None

    def observe(ordinal: int) -> None:
        if ordinal != retire["originalOrdinal"]:
            return
        wait_until_settled(player)
        out[retire["verdictKey"]] = refusal_evidence(player._require_transport())

    return observe


def score_refusal(sample: Any, retire: dict[str, Any], runtime_installed: bool) -> dict[str, Any]:
    """The POSITIVE half of a refused boundary: on the settled destination slide the
    retired movie is back under the raw player -- no painting `<video>` over its
    authored rect, and nothing pooled or preserved for its asset. "Did not continue"
    on its own is vacuous, so every way of not knowing is a False here, never a pass."""
    if not isinstance(sample, dict):
        return {"verdict": False, "reason": "no refusal evidence was sampled on the destination slide"}
    stage_map = sample.get("stageMap")
    if not stage_map_valid(stage_map):
        return {"verdict": False, "reason": "stage map is missing or untrustworthy at the refusal sample"}
    try:
        videos = painting_videos(sample.get("painting"), stage_map)
    except VisiblePassError as exc:
        return {"verdict": False, "reason": str(exc)}
    over = [video for video in videos if any(rects_overlap(video["authored"], rect) for rect in retire["rects"])]
    pooled: list[dict[str, Any]] = []
    if runtime_installed:
        snapshot = sample.get("poolSnapshot")
        if not isinstance(snapshot, list):
            return {"verdict": False, "reason": f"preserve snapshot is unreadable: {snapshot!r}"}
        pooled = [
            entry for entry in snapshot
            if isinstance(entry, dict) and matches_asset_keys(entry.get("key"), retire["assetKeys"])
        ]
    reason = None
    if over:
        reason = f"{len(over)} painting video(s) still overlap the retired movie on its destination slide"
    elif pooled:
        reason = f"{len(pooled)} pooled/preserved decoder(s) still hold the retired movie's asset"
    return {
        "verdict": not over and not pooled, "paintingOverRect": over, "pooled": pooled, "reason": reason,
    }


def score_refusals(
    evidence: dict[str, Any], facts: dict[str, Any], runtime_installed: bool
) -> dict[str, Any]:
    retire = facts.get("retire")
    if not retire:
        return {}
    key = retire["verdictKey"]
    return {key: score_refusal(evidence.get(key), retire, runtime_installed)}


def hash_number(value: Any) -> int | None:
    match = re.fullmatch(r"#?(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def armed_evidence(
    transport: Any, *, gap_s: float = ARMED_READ_GAP_S, sleep: Callable[[float], None] = time.sleep
) -> list[dict[str, Any]]:
    """Two reads of the settled armed slide, `gap_s` apart; never the oracle handle."""
    reads: list[dict[str, Any]] = []
    for index in range(2):
        if index:
            sleep(gap_s)
        read = refusal_evidence(transport)
        read["glReplay"] = transport.evaluate(GL_REPLAY_READ_JS)
        reads.append(read)
    return reads


def boundary_observer(
    player: Any, facts: dict[str, Any], out: dict[str, Any], *, sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> Callable[[int], None] | None:
    """`refusal_observer`, or two armed reads once the destination hash settles."""
    armed = facts.get("armed")
    if not armed:
        return refusal_observer(player, facts, out)

    def observe(ordinal: int) -> None:
        if ordinal != armed["originalOrdinal"]:
            return
        if not wait_for_destination_hash(player, armed["atScene"], sleep=sleep, now=now):
            out[armed["verdictKey"]] = {"reason": f"hash never settled at #{armed['atScene']} before the first read"}
            return
        out[armed["verdictKey"]] = armed_evidence(player._require_transport(), sleep=sleep)

    return observe


def wait_for_destination_hash(
    player: Any, scene: int, *, timeout_s: float = VISIBLE_SETTLE_TIMEOUT_S,
    now: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Bounded: the page hash is exactly `#scene` and the player is not busy."""
    transport = player._require_transport()
    deadline = now() + timeout_s
    while True:
        if hash_number(transport.evaluate(HASH_JS)) == scene and not player.observe().busy:
            return True
        if now() >= deadline:
            return False
        sleep(0.05)


def _notes(state: dict[str, Any], kind: str, source: str = "coreEvents") -> list[dict[str, Any]]:
    if source == "api":
        api = state.get("api")
        events = api.get("events") if isinstance(api, dict) else None
    else:
        events = state.get(source)
    if not isinstance(events, list):
        return []
    return [
        event.get("detail") if isinstance(event.get("detail"), dict) else {}
        for event in events if isinstance(event, dict) and event.get("kind") == kind
    ]


def _carried_el_id(state: Any) -> Any:
    carried = _notes(state, "glreplay-carried") if isinstance(state, dict) else []
    return carried[0].get("elId") if len(carried) == 1 else None


def _movie_entries(pool: list[Any], armed: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        entry for entry in pool
        if isinstance(entry, dict)
        and (matches_asset_keys(entry.get("key"), armed["assetKeys"]) or entry.get("movieKey") == armed["movieKey"])
    ]


def _armed_live(states: list[dict[str, Any]], armed: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    stats = []
    for state in states:
        api = state.get("api")
        stat = api.get("stats") if isinstance(api, dict) else None
        if not (
            isinstance(stat, dict) and api.get("state") == "LIVE" and api.get("standDowns") == []
            and stat.get("glErrors") == 0
            and (hash_number(state.get("hash")) or -1) >= armed["atScene"]
        ):
            return False, {"reason": "a read is not LIVE on its destination", "state": api}
        stats.append(stat)
    first, second = stats
    times = [_finite_number(state.get("t")) for state in states]
    counters = [
        (_finite_number(first.get(key)), _finite_number(second.get(key))) for key in ("iter", "uploads")
    ]
    ok = (
        first.get("epoch") is not None and first.get("epoch") == second.get("epoch")
        and all(a is not None and b is not None and b > a for a, b in counters)
        and None not in times and times[1] - times[0] >= ARMED_READ_GAP_S * 1000.0
    )
    return ok, {"epochs": [first.get("epoch"), second.get("epoch")], "counters": counters, "t": times}


def _armed_events(state: dict[str, Any], armed: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    if not isinstance(state.get("coreEvents"), list):
        return False, {"reason": "runtime notes are unreadable"}
    arms, lives = _notes(state, "glreplay-arm"), _notes(state, "glreplay-live")
    zones = [(z.get("from"), z.get("to"), z.get("reason")) for z in _notes(state, "glreplay-zone")]
    carried = _notes(state, "glreplay-carried")
    downs = _notes(state, "glreplay-standdown") + _notes(state, "glreplay-handoff")
    delta = _finite_number(carried[0].get("delta")) if len(carried) == 1 else None
    live_hash = hash_number(lives[0].get("sceneHash")) if len(lives) == 1 else None
    at = armed["atScene"]
    ok = (
        len(arms) == 1 and hash_number(arms[0].get("sceneHash")) == at - 1
        and live_hash is not None and live_hash >= at - 1
        and not downs
        and zones == [("pending", "armed", "moduleReady")]
        and delta is not None and 0 <= delta <= ARMED_CARRY_DELTA_MAX
    )
    return ok, {"arms": arms, "lives": lives, "zones": zones, "carried": carried, "downs": downs}


def _armed_no_painting(reads: list[dict[str, Any]], armed: dict[str, Any]) -> tuple[bool, list[Any]]:
    over: list[Any] = []
    for read in reads:
        stage_map = read.get("stageMap")
        if not stage_map_valid(stage_map):
            return False, ["stage map is missing or untrustworthy"]
        try:
            videos = painting_videos(read.get("painting"), stage_map)
        except VisiblePassError as exc:
            return False, [str(exc)]
        over.extend(v for v in videos if any(rects_overlap(v["authored"], rect) for rect in armed["rects"]))
    return not over, over


def _armed_pool(states: list[dict[str, Any]], armed: dict[str, Any], carried: Any) -> tuple[bool, dict[str, Any]]:
    if carried is None:
        return False, {"reason": "no single glreplay-carried note names the carried decoder"}
    clock: list[tuple[float | None, float | None]] = []
    for state in states:
        pool = state.get("pool")
        if not isinstance(pool, list):
            return False, {"reason": f"pool census is unreadable: {pool!r}"}
        movie = _movie_entries(pool, armed)
        mine = [entry for entry in movie if entry.get("elId") == carried]
        if len(mine) != 1 or any(entry.get("inDocument") is not False or entry.get("fromDom") for entry in movie):
            return False, {"reason": "pool is not {carried} plus out-of-document siblings", "movie": movie}
        entry = mine[0]
        if entry.get("paused") is not False or not ((_finite_number(entry.get("readyState")) or 0) >= 2):
            return False, {"reason": "carried decoder is paused or not decoding", "carried": entry}
        clock.append((_finite_number(state.get("t")), _finite_number(entry.get("currentTime"))))
    (t0, c0), (t1, c1) = clock
    if None in (t0, c0, t1, c1) or t1 <= t0:
        return False, {"reason": "carried clock is unreadable", "clock": clock}
    rate = (c1 - c0) / ((t1 - t0) / 1000.0)
    low, high = ARMED_CLOCK_RATE
    return (c1 > c0 and low <= rate <= high), {"clock": clock, "rate": rate}


def pre_flip_owner_ids(samples: list[dict[str, Any]], armed: dict[str, Any]) -> list[Any]:
    """Footprint owners resolved at the armed instance rect before the flip (None if unresolved)."""
    owners: list[Any] = []
    for sample in samples or []:
        scene = sample.get("scene")
        if not isinstance(scene, (int, float)) or scene >= armed["atScene"]:
            continue
        for video in sample.get("videos") or []:
            if matches_asset_keys(video.get("src"), armed["assetKeys"]) and rect_matches(video.get("rect"), armed["instanceRect"]):
                owner = video.get("footprintOwner")
                owners.append(owner.get("elId") if isinstance(owner, dict) else None)
    return owners


def score_armed(
    reads: Any, armed: dict[str, Any], continuity: Any, *, owner_ids: Any = None
) -> dict[str, Any]:
    """`armed1to2` (plan g5g6 §3.3): every clause holds; missing is False, never None."""
    checks = {"mode": False, "live": False, "events": False, "noPainting": False, "pool": False, "owner": False}
    detail: dict[str, Any] = {}
    gl = continuity.get("glReplay") if isinstance(continuity, dict) else None
    checks["mode"] = (
        isinstance(gl, dict) and gl.get("mode") == "injected"
        and gl.get("version") == GL_REPLAY_VERSION and gl.get("sha256") == gl_replay_js_sha256()
    )
    if (
        isinstance(reads, list) and len(reads) == 2
        and all(isinstance(read, dict) and isinstance(read.get("glReplay"), dict) for read in reads)
    ):
        states = [read["glReplay"] for read in reads]
        checks["live"], detail["live"] = _armed_live(states, armed)
        checks["events"], detail["events"] = _armed_events(states[-1], armed)
        checks["noPainting"], detail["paintingOverRect"] = _armed_no_painting(reads, armed)
        carried = _carried_el_id(states[-1])
        checks["pool"], detail["pool"] = _armed_pool(states, armed, carried)
        owners = [o for o in owner_ids if o is not None] if isinstance(owner_ids, list) else []
        checks["owner"] = carried is not None and bool(owners) and all(o == carried for o in owners)
        detail["preFlipOwners"] = sorted({str(o) for o in owners})
    else:
        detail["reason"] = "the armed slide was not read twice"
    failing = [name for name, ok in checks.items() if not ok]
    return {
        "verdict": not failing, "checks": checks, "detail": detail,
        "reason": f"armed checks failed: {failing}" if failing else None,
    }


def score_positive_halves(
    evidence: dict[str, Any], facts: dict[str, Any], runtime_installed: bool, continuity: Any,
    samples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """`score_refusals` plus, for an armed fact set, its `armed1to2`."""
    scored = score_refusals(evidence, facts, runtime_installed)
    armed = facts.get("armed")
    if armed:
        scored[armed["verdictKey"]] = score_armed(
            evidence.get(armed["verdictKey"]), armed, continuity, owner_ids=pre_flip_owner_ids(samples or [], armed),
        )
    return scored


@contextmanager
def env_override(overrides: dict[str, str | None]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in overrides}
    for key, value in overrides.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_arm(
    name: str, export_root: Path, slides: list[dict[str, Any]], facts: dict[str, Any],
    viewport: tuple[int, int], expected_stage: dict[str, float], *,
    gl_replay: str = "off", facts_on: dict[str, Any] | None = None,
) -> dict[str, Any]:
    force_viewport(*viewport)
    player = LiveOutputHost(export_root, slides, headless=True, gl_replay=gl_replay)
    result: dict[str, Any] = {"arm": name}
    try:
        player.start()
        result["continuity"] = player.output["continuity"]
        arm_facts = facts_for(result["continuity"], facts, facts_on)
        if facts_on is not None:
            result["factsSet"] = "on" if arm_facts is facts_on else "off"
        evidence: dict[str, Any] = {}
        raw_samples = drive_and_sample(player, observer=boundary_observer(player, arm_facts, evidence))
        samples, invalid_count = convert_samples_to_authored(raw_samples)
        result["samples"] = samples
        result["sampleCount"] = len(samples)
        result["stageMapInvalidCount"] = invalid_count
        result["stageMap"] = stage_map_summary(samples)
        result["stageFit"] = score_stage_fit(samples, expected_stage)
        runtime_installed = result["continuity"].get("mode") == "qualified"
        result.update(score_boundaries(samples, arm_facts, runtime_installed))
        result.update(score_positive_halves(evidence, arm_facts, runtime_installed, result["continuity"], samples))
    finally:
        try:
            player.stop()
        except Exception as exc:  # noqa: BLE001 - record, never mask an earlier failure
            result["stopError"] = str(exc)
    return result


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def launch_attach_chrome(port: int, profile: Path) -> subprocess.Popen:
    profile.mkdir(parents=True, exist_ok=True)
    args = [
        str(CHROME), "--headless=new", f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1", f"--user-data-dir={profile}",
        f"--window-size={VIEWPORT_WIDTH},{VIEWPORT_HEIGHT + _HEIGHT_PAD}",
        "--force-device-scale-factor=1", "--autoplay-policy=no-user-gesture-required",
        "--no-first-run", "--no-default-browser-check", "--mute-audio",
    ]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_for_cdp(port: int, timeout_s: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=0.5) as response:
                if json.loads(response.read()):
                    return
        except Exception:
            time.sleep(0.1)
    raise SystemExit(f"attach Chrome did not open a CDP target on port {port}")


def force_exact_viewport(port: int, width: int, height: int) -> None:
    """`--window-size` on a bare headless Chrome (no `--app=` window) does not
    yield an exact `innerWidth`/`innerHeight` (window chrome eats a variable
    amount depending on flags/version); pin the renderer's device metrics
    directly instead of guessing another padding constant. The override is
    target-scoped and survives the host's later, separate CDP attach."""
    from websockets.sync.client import connect

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
        targets = json.loads(response.read())
    page = next(item for item in targets if item.get("type") == "page" and item.get("webSocketDebuggerUrl"))
    ws = connect(page["webSocketDebuggerUrl"], open_timeout=5)
    try:
        ws.send(json.dumps({
            "id": 1, "method": "Emulation.setDeviceMetricsOverride",
            "params": {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
        }))
        ws.recv(timeout=5)
    finally:
        ws.close()


def run_attach_arm(
    export_root: Path, slides: list[dict[str, Any]], facts: dict[str, Any], scratch: Path,
    expected_stage: dict[str, float], *, gl_replay: str = "off", facts_on: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # The live host forces attach mode to 1920x1080 by contract regardless of
    # `--viewport`; the attach arm stays pinned to that, never the CLI value.
    port = free_port()
    profile = scratch / "attach-chrome-profile"
    if profile.exists():
        shutil.rmtree(profile)
    chrome_proc = launch_attach_chrome(port, profile)
    result: dict[str, Any] = {"arm": "attach", "attachViewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}}
    try:
        wait_for_cdp(port)
        force_exact_viewport(port, VIEWPORT_WIDTH, VIEWPORT_HEIGHT)
        with env_override({ATTACH_ENV: f"http://127.0.0.1:{port}"}):
            player = LiveOutputHost(export_root, slides, headless=True, gl_replay=gl_replay)
            try:
                player.start()
                output = player.output
                result["continuity"] = output["continuity"]
                attach_facts = facts_for(result["continuity"], facts, facts_on)
                if facts_on is not None:
                    result["factsSet"] = "on" if attach_facts is facts_on else "off"
                result["output"] = {key: value for key, value in output.items() if key != "continuity"}
                transport = player._require_transport()
                plan_transparent = transport.evaluate(
                    "!!(window.__OBED_CONTINUITY__ && window.__OBED_CONTINUITY__.transparentBackground)"
                )
                computed_background = transport.evaluate("getComputedStyle(document.documentElement).backgroundColor")
                result["transparentBackground"] = {"plan": bool(plan_transparent), "computedBackground": computed_background}
                evidence: dict[str, Any] = {}
                raw_samples = drive_and_sample(player, observer=boundary_observer(player, attach_facts, evidence))
                samples, invalid_count = convert_samples_to_authored(raw_samples)
                result["samples"] = samples
                result["sampleCount"] = len(samples)
                result["stageMapInvalidCount"] = invalid_count
                result["stageMap"] = stage_map_summary(samples)
                result["stageFit"] = score_stage_fit(samples, expected_stage)
                runtime_installed = result["continuity"].get("mode") == "qualified"
                result.update(score_boundaries(samples, attach_facts, runtime_installed))
                result.update(score_positive_halves(evidence, attach_facts, runtime_installed, result["continuity"], samples))
            finally:
                try:
                    player.stop()
                except Exception as exc:  # noqa: BLE001
                    result["stopError"] = str(exc)
    finally:
        chrome_proc.terminate()
        try:
            chrome_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            chrome_proc.kill()
            chrome_proc.wait(timeout=5)
        result["chromePid"] = chrome_proc.pid
        result["chromeExitCode"] = chrome_proc.poll()
    return result


class VisiblePassError(RuntimeError):
    """A visible-content pass could not be scored at all (no ground truth, an
    unreadable screenshot, a stage map the probe refuses to trust). Never a
    verdict: the pass records it as `status: "error"` and the overall status
    fails on it."""


def _scorers() -> tuple[Callable[..., Any], Callable[..., Any]]:
    from obed_edom.html_alpha_probe import liveness_mask, score_visible_slide

    return liveness_mask, score_visible_slide


def evaluate_async(transport: Any, expression: str) -> Any:
    """`Runtime.evaluate` with `awaitPromise=True`, for a handle whose
    `sample()`/`markerBands()`/`pause()`/`resume()` return Promises -- the
    probe's own `evaluate` always awaits `False`."""
    result = transport.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
    if result.get("exceptionDetails"):
        raise VisiblePassError("in-page oracle evaluation failed")
    return (result.get("result") or {}).get("value")


def inpage_applicability_reason(raw: Any) -> str | None:
    """The canonical absent-handle reason for exactly that n/a response, else
    `None`: every other case -- malformed, mismatched identity, a stale or
    replaced handle -- is an APPLICABLE inconclusive result, never n/a."""
    if (
        isinstance(raw, dict) and raw.get("applicable") is False
        and raw.get("status") == "n/a" and raw.get("reason") == INPAGE_HANDLE_ABSENT_REASON
    ):
        return INPAGE_HANDLE_ABSENT_REASON
    return None


def inpage_oracle_result(raw: Any) -> dict[str, Any] | None:
    """`INPAGE_LIVENESS_JS`'s result, scored into the in-page verdict. `None`
    only for a well-formed not-applicable result -- no runtime handle at all --
    so it contributes nothing to `combine_oracle_verdicts` (plan SS4.2's
    applicability gate). Anything malformed, a scene/rect/instance/canvas
    mismatch, a stale or replaced handle, an epoch mismatch, an unusable
    occluder mask, non-distinct sample callbacks, or a paused-decoder control
    that does not read DEAD is an APPLICABLE INCONCLUSIVE result, never n/a
    and never LIVE (Codex r1 Specs 2-6, 8-9; Codex r2 Specs 3, 5, 6).
    """
    if inpage_applicability_reason(raw) is not None:
        return None
    if not isinstance(raw, dict) or raw.get("applicable") is not True:
        return {"verdict": None, "status": "inconclusive", "reason": "in-page oracle probe returned an unusable result", "n": 0}
    if raw.get("status") != "ok":
        return {"verdict": None, "status": "inconclusive", "reason": raw.get("reason") or "in-page oracle inconclusive", "n": 0}

    samples = raw.get("samples") or []
    paused_samples = raw.get("pausedDecoderSamples") or []
    sample_epoch, marker_epoch = raw.get("epoch"), raw.get("markerEpoch")
    if sample_epoch is None or marker_epoch is None or sample_epoch != marker_epoch:
        return {"verdict": None, "status": "inconclusive", "reason": "marker epoch does not match the sample epoch", "n": len(samples)}

    mask = occluder_mask_from_markers(raw.get("markerDark") or [], raw.get("markerLight") or [])
    if not inpage_mask_is_usable(mask):
        return {"verdict": None, "status": "inconclusive", "reason": "occluder mask unusable", "n": len(samples)}

    scored = score_inpage_liveness(samples, occluder_mask=mask["mask"])
    paused = score_inpage_liveness(paused_samples, occluder_mask=mask["mask"])
    result = {
        **scored,
        "controls": {"pausedDecoder": paused},
        "rawSamples": samples,
        "rawPausedSamples": paused_samples,
        "markerDark": raw.get("markerDark"),
        "markerLight": raw.get("markerLight"),
    }
    if paused.get("verdict") is not False:
        result["verdict"] = None
        result["status"] = "inconclusive"
        result["reason"] = "paused-decoder control did not read dead"
    return result


def measure_inpage_oracle_with_paused_control(
    transport: Any, rect_authored: dict[str, float], scene_id: Any, instance_id: Any
) -> dict[str, Any] | None:
    """One rect's in-page GL read, bound to the scene, authored rect, and
    movie-instance identity being scored, taken in the same armed state the
    screenshot burst just captured. `None` when no handle is published. A
    timeout or a rejected promise (Codex r2 Spec 4) degrades to an applicable
    INCONCLUSIVE for this rect, never a `status:error` for the whole pass."""
    try:
        transport.evaluate(
            f"window.__obedInpageRect = {json.dumps(rect_authored)};"
            f"window.__obedInpageSceneId = {json.dumps(scene_id)};"
            f"window.__obedInpageInstanceId = {json.dumps(instance_id)}; true"
        )
        raw = evaluate_async(transport, INPAGE_LIVENESS_JS)
        return inpage_oracle_result(raw)
    except Exception as exc:  # noqa: BLE001 - an oracle failure degrades this rect, it never crashes the pass
        return {"verdict": None, "status": "inconclusive", "reason": f"in-page oracle evaluation failed: {exc}", "n": 0}


def combine_rect_oracles(entry: dict[str, Any], inpage: dict[str, Any] | None) -> dict[str, Any]:
    """Pure: fold one screenshot `perRect` entry -- whose `verdict` means
    "expectation met", opposite polarity for a dead-expected rect -- with its
    in-page physical-liveness read (Codex r1 Spec 2). Converts the screenshot
    verdict to physical LIVE/DEAD via `expect`, combines physical liveness,
    then translates the combined physical verdict back to expectation-met.
    An applicable but INCONCLUSIVE in-page read never lets a met expectation
    stand uncorroborated (Codex r2 Spec 1): that holds regardless of `expect`,
    not only when the physical reading happens to be LIVE."""
    expect = entry.get("expect", LIVE)
    met = entry.get("verdict")
    physical = None if met is None else (met if expect != DEAD else not met)
    physical_status = "live" if physical is True else ("dead" if physical is False else "inconclusive")
    screenshot_physical = {"verdict": physical, "status": physical_status, "reason": entry.get("reason")}
    combined = combine_oracle_verdicts(screenshot_physical, inpage)
    combined_physical = combined["verdict"]
    reason = combined.get("reason")
    if met is True and inpage is not None and inpage.get("verdict") is None:
        combined_physical = None
        reason = reason or f"in-page oracle inconclusive: {inpage.get('reason')}"
    if combined_physical is None:
        final_verdict = None
    else:
        final_verdict = combined_physical if expect != DEAD else not combined_physical
    return {
        **entry,
        "verdict": final_verdict,
        "reason": reason,
        "oracles": {
            "screenshot": {"verdict": met, "status": entry.get("status", physical_status), "liveFrac": entry.get("liveFrac")},
            "inpage": inpage,
        },
    }


def frame_shas(frames: Sequence[np.ndarray]) -> list[str]:
    """Per-frame sha256, the same recipe as P2's `frameSha256` -- forensic only,
    recorded so a recurrence of the stale-surface misread is diagnosable from
    the artifact alone; it cannot itself detect a misread burst and must feed
    no verdict (plan SS4.1)."""
    return [hashlib.sha256(np.ascontiguousarray(frame).tobytes()).hexdigest() for frame in frames]


def decode_png(data: str) -> np.ndarray:
    """Base64 PNG (as `Page.captureScreenshot` returns it) to an RGB uint8 array."""
    buffer = np.frombuffer(base64.b64decode(data), dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise VisiblePassError("screenshot did not decode as a PNG")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def burst_deadlines(start: float, offsets_ms: tuple[int, ...] = BURST_OFFSETS_MS) -> list[float]:
    """Absolute monotonic deadlines for one burst -- scheduled against `start`,
    never accumulated per shot, so a slow capture cannot drift the later offsets."""
    return [start + offset / 1000.0 for offset in offsets_ms]


def to_screen_rect(rect: dict[str, float], stage_map: dict[str, Any]) -> dict[str, float]:
    """Inverse of `to_authored_rect`: authored px to on-screen px."""
    s = stage_map["s"]
    return {
        "x": rect["x"] * s + stage_map["ox"],
        "y": rect["y"] * s + stage_map["oy"],
        "w": rect["w"] * s,
        "h": rect["h"] * s,
    }


def control_region(
    stage: dict[str, float], viewport: tuple[int, int], *, size: int = CONTROL_PATCH_PX, inset: int = CONTROL_INSET_PX
) -> dict[str, Any]:
    """A patch that is provably static: a letterbox bar when the fitted stage does
    not fill the viewport, else the stage's own top-left corner inset by `inset`
    px. Records which was used -- a noise floor measured over the wrong region is
    not evidence."""
    width, height = viewport
    if stage["y"] >= size:
        return {"x": max(0, int(width / 2 - size / 2)), "y": 0, "w": size, "h": size, "source": "letterbox-top"}
    if stage["x"] >= size:
        return {"x": 0, "y": max(0, int(height / 2 - size / 2)), "w": size, "h": size, "source": "letterbox-left"}
    return {"x": int(stage["x"]) + inset, "y": int(stage["y"]) + inset, "w": size, "h": size, "source": "stage-corner"}


def _authored_rect(rect: Any) -> dict[str, float]:
    source = rect.as_dict() if hasattr(rect, "as_dict") else rect
    if not isinstance(source, dict) or not all(key in source for key in ("x", "y", "w", "h")):
        raise VisiblePassError(f"unusable authored rect in slide_instances: {rect!r}")
    return {key: float(source[key]) for key in ("x", "y", "w", "h")}


def slide_instances_of(plan: ContinuityPlan) -> dict[int, dict[str, list[Any]]]:
    """Every movie instance the export authors on each slide. `slide_rects` drops
    multi-instance assets, so it cannot stand in here: an absent or empty
    `slide_instances` is no ground truth at all, never a fallback."""
    instances = getattr(plan, "slide_instances", None)
    if not isinstance(instances, dict) or not instances:
        raise VisiblePassError("plan has no slide_instances")
    return instances


def expected_screen_rects(
    instances: dict[int, dict[str, list[Any]]], player_index: int, stage_map: dict[str, Any],
    expectations: dict[int, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Each authored instance rect plus the expectation the plan states for it. An
    asset the expectations do not mention is expected LIVE -- the stricter reading
    in both passes, and what every rect was before refusals existed."""
    by_asset = instances.get(player_index)
    if by_asset is None:
        raise VisiblePassError(f"plan has no slide_instances for player index {player_index}")
    stated = (expectations or {}).get(player_index) or {}
    rects: list[dict[str, Any]] = []
    for asset in sorted(by_asset):
        for index, rect in enumerate(by_asset[asset], start=1):
            authored = _authored_rect(rect)
            rects.append({
                "label": f"{asset}#{index}",
                "authored": authored,
                "screen": to_screen_rect(authored, stage_map),
                "expect": DEAD if stated.get(asset) == DEAD else LIVE,
            })
    return rects


def rect_iou(a: dict[str, float], b: dict[str, float]) -> float:
    overlap_w = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    overlap_h = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
    if overlap_w <= 0 or overlap_h <= 0:
        return 0.0
    intersection = overlap_w * overlap_h
    union = a["w"] * a["h"] + b["w"] * b["h"] - intersection
    return intersection / union if union > 0 else 0.0


def painting_videos(raw: Any, stage_map: dict[str, Any]) -> list[dict[str, Any]]:
    """`PAINTING_VIDEOS_JS`'s result in authored px. Anything but a list of
    well-formed rows is an instrument error, never an empty (and therefore
    silently clean) list."""
    if not isinstance(raw, list):
        raise VisiblePassError(f"painting-video probe returned {raw!r}")
    videos: list[dict[str, Any]] = []
    for row in raw:
        rect = row.get("rect") if isinstance(row, dict) else None
        if not isinstance(rect, dict) or not all(
            isinstance(rect.get(key), (int, float)) and math.isfinite(rect[key]) for key in ("x", "y", "w", "h")
        ):
            raise VisiblePassError(f"painting-video probe returned an unusable row: {row!r}")
        screen = {key: float(rect[key]) for key in ("x", "y", "w", "h")}
        videos.append({
            "src": row.get("src"), "elId": row.get("elId"),
            "screen": screen, "authored": to_authored_rect(screen, stage_map),
        })
    return videos


def match_painting_videos(videos: list[dict[str, Any]], expected: list[dict[str, Any]]) -> dict[str, Any]:
    """Every painting `<video>` must claim exactly one LIVE-expected instance rect,
    and no rect may be claimed twice -- the only evidence that separates two
    live movies sharing one rect, which pixels alone cannot. A video painting a
    DEAD-expected rect claims nothing: the plan says that movie is back under the
    raw player, so a `<video>` there is unexpected however live its pixels are."""
    claims: dict[str, list[dict[str, Any]]] = {}
    unexpected: list[dict[str, Any]] = []
    for video in videos:
        scores = [
            (rect_iou(video["authored"], item["authored"]), item["label"], item.get("expect", LIVE))
            for item in expected
        ]
        best_iou, best_label, best_expect = max(scores, default=(0.0, None, LIVE))
        if best_iou >= INSTANCE_IOU_MIN and best_expect != DEAD:
            claims.setdefault(best_label, []).append(video)
        else:
            unexpected.append({**video, "bestIou": best_iou, "bestLabel": best_label, "bestExpect": best_expect})
    duplicates = [
        {"label": label, "videos": claimants} for label, claimants in claims.items() if len(claimants) > 1
    ]
    reason = None
    if unexpected:
        reason = f"{len(unexpected)} painting video(s) match no expected movie instance"
    elif duplicates:
        reason = f"{len(duplicates)} expected movie instance(s) are painted by more than one video"
    return {
        "verdict": not unexpected and not duplicates, "painting": videos,
        "unexpectedVideos": unexpected, "duplicateVideos": duplicates, "reason": reason,
    }


def clipped_rect_labels(expected: list[dict[str, Any]], viewport: tuple[int, int], tolerance: float = 0.5) -> list[str]:
    """Expected rects that do not lie wholly inside the screenshot. Scoring one
    would measure a truncated rect, so it is an instrument error, not a red."""
    width, height = viewport
    return [
        item["label"] for item in expected
        if item["screen"]["x"] < -tolerance or item["screen"]["y"] < -tolerance
        or item["screen"]["x"] + item["screen"]["w"] > width + tolerance
        or item["screen"]["y"] + item["screen"]["h"] > height + tolerance
    ]


def wait_until_settled(
    host: Any, *, timeout_s: float = VISIBLE_SETTLE_TIMEOUT_S, now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Bounded: a player that never clears `busy` makes the slide INCONCLUSIVE, it
    does not hang the pass."""
    deadline = now() + timeout_s
    while now() < deadline:
        if not host.observe().busy:
            return True
        sleep(0.05)
    return False


def capture_burst(
    transport: Any, *, offsets_ms: tuple[int, ...] = BURST_OFFSETS_MS, poke: bool = False,
    now: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[np.ndarray], list[float]]:
    start = now()
    frames: list[np.ndarray] = []
    actual_ms: list[float] = []
    for deadline in burst_deadlines(start, offsets_ms):
        remaining = deadline - now()
        if remaining > 0:
            sleep(remaining)
        actual_ms.append(round((now() - start) * 1000.0, 1))
        if poke:
            transport.evaluate(BURST_POKE_JS)
        frames.append(decode_png(transport.call("Page.captureScreenshot", format="png")["data"]))
    return frames, actual_ms


def visible_evidence_writer(directory: Path, pass_name: str) -> Callable[[dict[str, Any], list[np.ndarray]], dict[str, str]]:
    liveness_mask, _ = _scorers()

    def write(record: dict[str, Any], frames: list[np.ndarray]) -> dict[str, str]:
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{pass_name}-slide{record.get('originalOrdinal')}"
        mask_path = directory / f"{stem}-mask.png"
        shot_path = directory / f"{stem}-shot0.png"
        mask = np.asarray(liveness_mask(frames)).astype(np.uint8) * 255
        cv2.imwrite(str(mask_path), mask)
        cv2.imwrite(str(shot_path), cv2.cvtColor(frames[0], cv2.COLOR_RGB2BGR))
        result = {"mask": str(mask_path), "shot0": str(shot_path)}
        inpage_records = [
            rect["oracles"]["inpage"] for rect in record.get("perRect") or []
            if isinstance(rect.get("oracles"), dict) and rect["oracles"].get("inpage") is not None
        ]
        if inpage_records:
            inpage_path = directory / f"{stem}-inpage.json"
            inpage_path.write_text(json.dumps(inpage_records, indent=2, default=str))
            result["inpage"] = str(inpage_path)
        return result

    return write


def measure_and_combine_slide_oracles(
    expected: list[dict[str, Any]], per_rect: list[dict[str, Any]], transport: Any, scene_id: Any,
    screenshot_verdict: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool | None, str]:
    """Measure each rect's in-page oracle (bound to `scene_id` and its authored
    rect) and fold it with the screenshot verdict via the pure
    `combine_rect_oracles` (plan SS4.4). A rect disagreement or an
    in-page-inconclusive-over-live rect turns the slide `None`/"inconclusive";
    otherwise the combined per-rect verdicts equal the screenshot-only ones
    exactly, so the slide verdict falls back to the screenshot scorer's own
    (already stray-AND-ed) `verdict`/`status`. With the in-page oracle inert
    (n/a everywhere) this reproduces today's verdict bit-for-bit; only the
    additive `oracles` key changes."""
    combined_per_rect = [
        combine_rect_oracles(
            entry,
            measure_inpage_oracle_with_paused_control(transport, item["authored"], scene_id, item["label"])
            if entry.get("rect") else None,
        )
        for item, entry in zip(expected, per_rect)
    ]
    if any(entry["verdict"] is None for entry in combined_per_rect):
        return combined_per_rect, None, "inconclusive"
    return combined_per_rect, screenshot_verdict.get("verdict"), screenshot_verdict.get("status")


def visible_slide_record(
    host: Any, slide: dict[str, Any], instances: dict[int, dict[str, list[Any]]], viewport: tuple[int, int], *,
    scorer: Callable[..., Any], evidence: Callable[[dict[str, Any], list[np.ndarray]], dict[str, str]] | None = None,
    expectations: dict[int, dict[str, str]] | None = None,
    offsets_ms: tuple[int, ...] = BURST_OFFSETS_MS, poke: bool = False, now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    rescore: Callable[[dict[str, Any], list[np.ndarray]], None] | None = None,
) -> dict[str, Any]:
    """One settled slide, scored from a screenshot burst. Every way of not knowing
    -- unsettled player, a scene that moved under the burst, a screenshot that is
    not the forced viewport, an untrustworthy stage map, an expected rect that
    clips off the screenshot, missing ground truth -- ends as `verdict: None`,
    never as a pass and never as the RED that the `Voff` control has to earn.
    Pixel liveness is scored alongside independent DOM instance evidence: a
    slide whose pixels pass but whose painting `<video>` elements do not match
    the expected instances one-for-one is RED."""
    transport = host._require_transport()
    record: dict[str, Any] = {
        "playerIndex": int(slide["playerIndex"]), "originalOrdinal": slide.get("originalOrdinal"),
        "sceneId": None, "expectedRects": [], "perRect": [], "stray": None, "noiseFloor": None,
        "shotOffsetsMs": [], "stageMap": None, "instanceCheck": None, "status": "error", "verdict": None,
    }
    if not wait_until_settled(host, now=now, sleep=sleep):
        record.update(status="inconclusive", reason="player never settled before the burst")
        return record

    frames: list[np.ndarray] | None = None
    stage_map: Any = None
    painting_raw: Any = None
    for attempt in (1, 2):
        scene_before = transport.evaluate(SCENE_ID_JS)
        stage_map = transport.evaluate(STAGE_MAP_JS)
        painting_raw = transport.evaluate(PAINTING_VIDEOS_JS)
        try:
            shots, offsets = capture_burst(transport, offsets_ms=offsets_ms, poke=poke, now=now, sleep=sleep)
        except VisiblePassError as exc:
            record.update(reason=str(exc))
            return record
        record.update(sceneId=scene_before, shotOffsetsMs=offsets, stageMap=stage_map, attempts=attempt)
        if transport.evaluate(SCENE_ID_JS) == scene_before and not host.observe().busy:
            frames = shots
            break
    if frames is None:
        record.update(status="inconclusive", reason="scene changed or the player went busy during the burst")
        return record
    shas = frame_shas(frames)
    record["burstProfile"] = {
        "offsetsMs": [float(v) for v in offsets_ms], "poke": bool(poke), "fromSurface": False,
        "uniqueShas": len(set(shas)), "shas": shas,
    }

    if not stage_map_valid(stage_map):
        record.update(reason="stage map is missing or untrustworthy at burst time")
        return record
    wrong = next((frame for frame in frames if (frame.shape[1], frame.shape[0]) != viewport), None)
    if wrong is not None:
        record.update(reason=f"screenshot is {wrong.shape[1]}x{wrong.shape[0]}, expected {viewport[0]}x{viewport[1]}")
        return record
    try:
        expected = expected_screen_rects(instances, record["playerIndex"], stage_map, expectations)
        painting = painting_videos(painting_raw, stage_map)
    except VisiblePassError as exc:
        record.update(reason=str(exc))
        return record
    record["expectedRects"] = expected
    clipped = clipped_rect_labels(expected, viewport)
    if clipped:
        record.update(reason=f"expected rect(s) {clipped} clip outside the {viewport[0]}x{viewport[1]} screenshot")
        return record

    instance_check = match_painting_videos(painting, expected)
    control = control_region(stage_screen_rect(stage_map), viewport)
    scored = scorer(
        frames,
        [{**item["screen"], "label": item["label"], "expect": item["expect"]} for item in expected],
        control,
    )
    per_rect = scored.get("perRect") or []
    if per_rect:
        per_rect, verdict, status = measure_and_combine_slide_oracles(
            expected, per_rect, transport, record["sceneId"], scored
        )
    else:
        verdict, status = scored.get("verdict"), scored.get("status")
    record.update(
        control=control, instanceCheck=instance_check, perRect=per_rect, stray=scored.get("stray"),
        noiseFloor=scored.get("noiseFloor"), verdict=verdict, status=status,
    )
    if rescore is not None:
        rescore(record, frames)
    if record["verdict"] is True and not instance_check["verdict"]:
        record.update(verdict=False, status="fail", reason=instance_check["reason"])
    if evidence is not None and record["verdict"] is not True:
        record["evidence"] = evidence(record, frames)
    return record


def run_visible_slides(
    host: Any, slides: list[dict[str, Any]], instances: dict[int, dict[str, list[Any]]], viewport: tuple[int, int], *,
    scorer: Callable[..., Any] | None = None, evidence: Callable[..., dict[str, str]] | None = None,
    expectations: dict[int, dict[str, str]] | None = None,
    advance: Callable[..., None] = advance_until_original_slide, offsets_ms: tuple[int, ...] = BURST_OFFSETS_MS,
    poke: bool = False, now: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
    rescore: Callable[[dict[str, Any], list[np.ndarray]], None] | None = None,
    after_slide: Callable[[Any, dict[str, Any], dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Every original slide in order: slide 1 as the player opens it, the rest
    reached with the same advance-and-settle discipline the arms use."""
    if scorer is None:
        scorer = _scorers()[1]
    records: list[dict[str, Any]] = []
    for slide in sorted((s for s in slides if not s.get("skipped")), key=lambda s: s["originalOrdinal"]):
        if slide["originalOrdinal"] != 1:
            advance(host, slide["originalOrdinal"])
        records.append(visible_slide_record(
            host, slide, instances, viewport, scorer=scorer, evidence=evidence,
            expectations=expectations, offsets_ms=offsets_ms, poke=poke, now=now, sleep=sleep, rescore=rescore,
        ))
        if after_slide is not None:
            after_slide(host, slide, records[-1])
    return records


def visible_stage_samples(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each slide's burst-time stage map as a `score_stage_fit` sample, so a
    visible pass is gated on the same fit the arms are: V and Voff run in
    separate sessions, and a shifted or cropped Voff could otherwise report an
    off-image expected rect as an ordinary red."""
    return [
        {"stageMap": slide.get("stageMap"), "stageMapValid": stage_map_valid(slide.get("stageMap"))}
        for slide in slides
    ]


def visible_stage_summary(slides: list[dict[str, Any]], expected: dict[str, float]) -> dict[str, Any]:
    valid = [slide["stageMap"] for slide in slides if stage_map_valid(slide.get("stageMap"))]
    if not valid:
        return {"sampleCount": 0, "expected": expected, "matches": False}
    observed = [stage_screen_rect(stage_map) for stage_map in valid]
    return {
        "sampleCount": len(valid), "expected": expected, "observed": observed[0],
        "matches": all(stage_fit_matches(rect, expected) for rect in observed),
    }


def run_visible_pass(
    name: str, export_root: Path, slides: list[dict[str, Any]], plan: ContinuityPlan,
    viewport: tuple[int, int], expected_stage: dict[str, float], evidence_dir: Path,
    expectations: dict[int, dict[str, str]] | None = None, burst_poke: bool = False, *,
    gl_replay: str = "off", rescore: Callable[[dict[str, Any], list[np.ndarray]], None] | None = None,
    after_slide: Callable[[Any, dict[str, Any], dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """One visible-content pass in its own host session, scored against the plan's
    own per-rect expectations for this mode. No `SAMPLER_JS`: the burst's captures
    would perturb the rAF sampler's clock, which is why this is a separate pass and
    not an arm."""
    force_viewport(*viewport)
    result: dict[str, Any] = {"pass": name, "status": "ok", "viewport": {"width": viewport[0], "height": viewport[1]}}
    player = LiveOutputHost(export_root, slides, headless=True, gl_replay=gl_replay)
    try:
        instances = slide_instances_of(plan)
        player.start()
        result["continuity"] = player.output["continuity"]
        player.execute("show")
        transport = player._require_transport()
        transport.evaluate(ENSURE_PLAYING_JS)
        wait_for_decode(player)
        time.sleep(CLICK_DELAY_S)
        result["slides"] = run_visible_slides(
            player, slides, instances, viewport, poke=burst_poke,
            evidence=visible_evidence_writer(evidence_dir, name), expectations=expectations,
            rescore=rescore, after_slide=after_slide,
        )
    except Exception as exc:  # noqa: BLE001 - a pass that cannot be scored is an error, never a verdict
        result["status"] = "error"
        result["error"] = str(exc)
    finally:
        try:
            player.stop()
        except Exception as exc:  # noqa: BLE001 - record, never mask an earlier failure
            result["stopError"] = str(exc)
    scored = result.get("slides") or []
    result["stageMap"] = visible_stage_summary(scored, expected_stage)
    result["stageFit"] = score_stage_fit(visible_stage_samples(scored), expected_stage)
    result["verdict"] = bool(scored) and all(slide.get("verdict") is True for slide in scored)
    return result


def occluded_screen_cells(
    gl_mask: Any, *, cols: int = LIVE_BAND_COLS, rows: int = LIVE_BAND_ROWS
) -> list[tuple[int, int]]:
    """The module's occluder mask (GL row 0 = bottom) as screen `(row, col)` cells."""
    if not isinstance(gl_mask, (list, tuple)) or len(gl_mask) != cols * rows or any(v not in (0, 1) for v in gl_mask):
        raise ValueError(f"occluder mask is not {cols * rows} cells of 0/1")
    return sorted((rows - 1 - k // cols, k % cols) for k, v in enumerate(gl_mask) if v == 1)


def _recompute_slide_verdict(record: dict[str, Any]) -> None:
    per_rect = record.get("perRect") or []
    if any(entry.get("verdict") is None for entry in per_rect):
        record.update(verdict=None, status="inconclusive")
        return
    ok = all(entry.get("verdict") is True for entry in per_rect) and (record.get("stray") or {}).get("verdict") is True
    record.update(verdict=ok, status="pass" if ok else "fail")


def apply_occlusion_rescore(record: dict[str, Any], frames: list[np.ndarray], label: str) -> None:
    """Gate one rect's screenshot half on its same-epoch occluder mask (plan g5g6 §3.5)."""
    expected = record.get("expectedRects") or []
    per_rect = record.get("perRect") or []
    index = next((i for i, item in enumerate(expected) if item.get("label") == label), None)
    if index is None or index >= len(per_rect):
        return
    entry = per_rect[index]
    oracles = entry.get("oracles") if isinstance(entry.get("oracles"), dict) else {}
    inpage = oracles.get("inpage")
    screenshot = oracles.get("screenshot") or {}
    occlusion: dict[str, Any] = {
        "unmasked": {
            "verdict": screenshot.get("verdict"), "liveFrac": entry.get("liveFrac"),
            "deadColumnBands": entry.get("deadColumnBands"), "deadRowBands": entry.get("deadRowBands"),
        },
    }
    base = {key: value for key, value in entry.items() if key not in ("oracles", "occlusion")}
    marks = (
        occluder_mask_from_markers(inpage.get("markerDark") or [], inpage.get("markerLight") or [])
        if isinstance(inpage, dict) else {"verdict": False}
    )
    if marks.get("verdict"):
        cells = occluded_screen_cells(marks["mask"])
        masked = score_live_coverage(liveness_mask(frames), expected[index]["screen"], occluded_cells=cells)
        occlusion.update(status="ok", cells=len(cells), bandCount=len(marks["mask"]), masked=masked)
        base.update({key: masked[key] for key in ("verdict", "liveFrac", "deadColumnBands", "deadRowBands", "reason")})
    else:
        occlusion["status"] = "unavailable"
        base.update(verdict=None, reason="no same-epoch occluder mask for the armed rect")
    combined = combine_rect_oracles(base, inpage)
    combined["occlusion"] = occlusion
    per_rect[index] = combined
    record["perRect"] = per_rect
    _recompute_slide_verdict(record)


def occlusion_rescorer(armed: dict[str, Any]) -> Callable[[dict[str, Any], list[np.ndarray]], None]:
    def rescore(record: dict[str, Any], frames: list[np.ndarray]) -> None:
        if record.get("playerIndex") == armed["playerIndex"]:
            apply_occlusion_rescore(record, frames, armed["instanceId"])

    return rescore


def score_vgl_armed_slide(entry: Any, armed: dict[str, Any]) -> dict[str, Any]:
    """Vgl's armed slide (plan g5g6 §3.4): LIVE in both oracles, paused DEAD, no painting video."""
    checks = {key: False for key in ("slide", "inpageLive", "pausedDead", "screenshotLive", "masked", "noPainting")}
    slide = next((s for s in visible_slides_of(entry) if s.get("playerIndex") == armed["playerIndex"]), None)
    rect = next(
        (r for r in (slide or {}).get("perRect") or [] if isinstance(r, dict) and r.get("label") == armed["instanceId"]),
        None,
    )
    if slide is not None and rect is not None:
        oracles = rect.get("oracles") if isinstance(rect.get("oracles"), dict) else {}
        inpage = oracles.get("inpage") if isinstance(oracles.get("inpage"), dict) else {}
        paused = ((inpage.get("controls") or {}).get("pausedDecoder") or {}) if isinstance(inpage.get("controls"), dict) else {}
        painting = (slide.get("instanceCheck") or {}).get("painting")
        checks.update(
            slide=slide.get("verdict") is True,
            inpageLive=inpage.get("verdict") is True,
            pausedDead=paused.get("verdict") is False,
            screenshotLive=rect.get("expect") == LIVE and (oracles.get("screenshot") or {}).get("status") == "live"
            and (oracles.get("screenshot") or {}).get("verdict") is True,
            masked=(rect.get("occlusion") or {}).get("status") == "ok",
            noPainting=isinstance(painting, list) and not any(
                isinstance(v, dict) and isinstance(v.get("authored"), dict)
                and any(rects_overlap(v["authored"], r) for r in armed["rects"])
                for v in painting
            ),
        )
    failing = [key for key, ok in checks.items() if not ok]
    return {"verdict": not failing, "checks": checks, "reason": f"failed {failing}" if failing else None}


def _handback_ready(read: Any, target: int, expect_handoff: bool) -> bool:
    if not isinstance(read, dict) or hash_number(read.get("hash")) != target or read.get("ready") is not True:
        return False
    if not expect_handoff:
        return True
    return _handed_off(read)


def _handed_off(read: Any) -> bool:
    """Exactly one module `glreplay-handoff` and exactly one runtime release, a hand-off."""
    if not isinstance(read, dict):
        return False
    releases = _notes(read, "glreplay-release")
    return (
        len(_notes(read, "glreplay-handoff", "api")) == 1
        and len(releases) == 1 and releases[0].get("mode") == "handoff"
    )


def capture_handback(
    host: Any, armed: dict[str, Any], *, expect_handoff: bool, timeout_s: float = HANDBACK_TIMEOUT_S,
    now: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any], np.ndarray | None]:
    """One post-build-1 capture (plan g5g6 §3.6); early or past-hash is inconclusive."""
    transport = host._require_transport()
    target = armed["atScene"] + 1
    record: dict[str, Any] = {"status": "inconclusive", "reason": None, "targetHash": target, "expectHandoff": expect_handoff}
    try:
        record["before"] = transport.evaluate(GL_REPLAY_READ_JS)
        host.execute("advance")
    except Exception as exc:  # noqa: BLE001 - a hand-back that cannot start proves nothing
        record["reason"] = f"advance failed: {exc}"
        return record, None
    deadline = now() + timeout_s
    while True:
        read = transport.evaluate(GL_REPLAY_READ_JS)
        number = hash_number(read.get("hash")) if isinstance(read, dict) else None
        if number is not None and number > target:
            record.update(reason=f"hash passed #{target} before the capture", polled=read)
            return record, None
        if _handback_ready(read, target, expect_handoff) and not host.observe().busy:
            break
        if now() >= deadline:
            record.update(reason=f"hand-back preconditions unmet after {timeout_s}s", polled=read)
            return record, None
        sleep(0.05)
    try:
        evaluate_async(transport, TWO_RAF_JS)
        frame = decode_png(transport.call("Page.captureScreenshot", format="png")["data"])
    except Exception as exc:  # noqa: BLE001
        record["reason"] = f"hand-back capture failed: {exc}"
        return record, None
    record.update(
        stageMap=transport.evaluate(STAGE_MAP_JS), painting=transport.evaluate(PAINTING_VIDEOS_JS),
        preserve=transport.evaluate(PRESERVE_SNAPSHOT_JS), after=transport.evaluate(GL_REPLAY_READ_JS),
    )
    after = record["after"]
    if not isinstance(after, dict) or hash_number(after.get("hash")) != target:
        record["reason"] = "hash moved during the hand-back capture"
        return record, None
    record["status"] = "ok"
    return record, frame


def handback_hook(
    armed: dict[str, Any], sink: dict[str, Any], *, expect_handoff: bool, refusal: bool = False,
) -> Callable[[Any, dict[str, Any], dict[str, Any]], None]:
    """`after_slide` that captures the hand-back on the armed slide into `sink`."""
    def after_slide(host: Any, slide: dict[str, Any], record: dict[str, Any]) -> None:
        if slide.get("originalOrdinal") != armed["originalOrdinal"]:
            return
        if refusal:
            sink["refusal"] = refusal_evidence(host._require_transport())
        sink["record"], sink["frame"] = capture_handback(host, armed, expect_handoff=expect_handoff)

    return after_slide


def green_slot(slot_rects: list[dict[str, float]], movie_slot: int) -> int | None:
    """The module's green-patch slot: the last slot after the movie's that overlaps it."""
    movie = slot_rects[movie_slot]
    for index in range(len(slot_rects) - 1, movie_slot, -1):
        slot = slot_rects[index]
        if (slot["x"] < movie["x"] + movie["w"] and movie["x"] < slot["x"] + slot["w"]
                and slot["y"] < movie["y"] + movie["h"] and movie["y"] < slot["y"] + slot["h"]):
            return index
    return None


def handback_mask_rects(
    armed: dict[str, Any], stage_map: dict[str, Any], *, dilate_px: float = HANDBACK_DILATE_PX, poke: bool = False,
) -> list[dict[str, float]]:
    """Dilated screen rects of the instance, movie, override and green slots, plus the poke pixel."""
    slots = armed["slotRects"]
    indices = {armed["movieSlot"], *armed["overrideSlots"]}
    green = green_slot(slots, armed["movieSlot"])
    if green is not None:
        indices.add(green)
    rects = []
    for rect in [armed["instanceRect"], *(slots[i] for i in sorted(indices))]:
        screen = to_screen_rect(rect, stage_map)
        rects.append({
            "x": screen["x"] - dilate_px, "y": screen["y"] - dilate_px,
            "w": screen["w"] + 2 * dilate_px, "h": screen["h"] + 2 * dilate_px,
        })
    if poke:
        rects.append({"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0})
    return rects


def handback_parity(
    v_record: Any, v_frame: np.ndarray | None, g_record: Any, g_frame: np.ndarray | None, armed: dict[str, Any], *,
    poke: bool = False, dilate_px: float = HANDBACK_DILATE_PX,
) -> dict[str, Any]:
    """max|V - Vgl| over every pixel outside both captures' masks must be 0."""
    records = (v_record, g_record)
    if any(not isinstance(r, dict) or r.get("status") != "ok" for r in records) or v_frame is None or g_frame is None:
        return {"verdict": None, "reason": "a hand-back capture is inconclusive"}
    if any(not stage_map_valid(r.get("stageMap")) for r in records):
        return {"verdict": None, "reason": "a hand-back stage map is missing or untrustworthy"}
    if v_frame.shape != g_frame.shape:
        return {"verdict": None, "reason": f"hand-back captures differ in shape: {v_frame.shape} vs {g_frame.shape}"}
    height, width = v_frame.shape[:2]
    outside = np.ones((height, width), dtype=bool)
    rects = [rect for r in records for rect in handback_mask_rects(armed, r["stageMap"], dilate_px=dilate_px, poke=poke)]
    for rect in rects:
        x0, y0 = max(0, math.floor(rect["x"])), max(0, math.floor(rect["y"]))
        x1, y1 = min(width, math.ceil(rect["x"] + rect["w"])), min(height, math.ceil(rect["y"] + rect["h"]))
        if x1 > x0 and y1 > y0:
            outside[y0:y1, x0:x1] = False
    delta = np.abs(v_frame[:, :, :3].astype(np.int16) - g_frame[:, :, :3].astype(np.int16)).max(axis=2)
    if not outside.any():
        return {"verdict": None, "reason": "the mask covers the whole capture"}
    out, inside = delta[outside], delta[~outside]
    max_outside = int(out.max())
    return {
        "verdict": max_outside == 0, "maxOutside": max_outside, "nChangedOutside": int((out > 0).sum()),
        "maxInside": int(inside.max()) if inside.size else 0, "maskRects": rects,
        "reason": None if max_outside == 0 else f"{int((out > 0).sum())} px differ outside the mask",
    }


def score_handback_carry(record: Any, armed: dict[str, Any]) -> dict[str, Any]:
    """Vgl after build 1: carried paints alone, released by hand-off, never remounted."""
    checks = {"painting": False, "release": False, "noRemount": False, "handoff": False}
    detail: dict[str, Any] = {}
    record = record if isinstance(record, dict) else {}
    after = record.get("after") if isinstance(record.get("after"), dict) else {}
    checks["handoff"] = _handed_off(after)
    before = record.get("before") if isinstance(record.get("before"), dict) else {}
    carried = _carried_el_id(after)
    stage_map = record.get("stageMap")
    if carried is not None and stage_map_valid(stage_map):
        try:
            videos = painting_videos(record.get("painting"), stage_map)
        except VisiblePassError as exc:
            videos, detail["painting"] = None, str(exc)
        if videos is not None:
            movie = [v for v in videos if matches_asset_keys(v.get("src"), armed["assetKeys"])]
            want = to_screen_rect(armed["instanceRect"], stage_map)
            detail["painting"] = movie
            checks["painting"] = len(movie) == 1 and movie[0].get("elId") == carried and all(
                abs(movie[0]["screen"][k] - want[k]) <= HANDBACK_RECT_TOLERANCE_PX for k in ("x", "y", "w", "h")
            )
    pool = before.get("pool")
    pooled = sorted({e.get("elId") for e in _movie_entries(pool, armed)}, key=str) if isinstance(pool, list) else None
    releases = _notes(after, "glreplay-release")
    detail.update(pooled=pooled, releases=releases)
    if carried is not None and pooled is not None and carried in pooled and len(releases) == 1:
        release = releases[0]
        retired = release.get("retired")
        checks["release"] = (
            release.get("mode") == "handoff" and isinstance(retired, list)
            and sorted(retired, key=str) == [e for e in pooled if e != carried]
        )
    if carried is not None:
        facades = [
            f.get("elId") for read in (before, after) for f in read.get("facades") or []
            if isinstance(f, dict) and f.get("forElId") == carried
        ]
        guarded = {carried, *facades}
        remounts = [
            {"kind": kind, **note} for kind in ("remount-done", "remount-footprint-rect")
            for note in _notes(after, kind) if note.get("elId") in guarded
        ]
        detail.update(guarded=sorted(guarded, key=str), remounts=remounts)
        checks["noRemount"] = not remounts
    failing = [key for key, ok in checks.items() if not ok]
    return {"verdict": not failing, "checks": checks, "carried": carried, "detail": detail,
            "reason": f"failed {failing}" if failing else None}


def score_handback(
    v_record: Any, v_frame: np.ndarray | None, g_record: Any, g_frame: np.ndarray | None, armed: dict[str, Any], *,
    poke: bool = False, dilate_px: float = HANDBACK_DILATE_PX,
) -> dict[str, Any]:
    parity = handback_parity(v_record, v_frame, g_record, g_frame, armed, poke=poke, dilate_px=dilate_px)
    carry = score_handback_carry(g_record, armed)
    if parity["verdict"] is None:
        return {"verdict": None, "parity": parity, "carry": carry, "reason": parity["reason"]}
    verdict = parity["verdict"] is True and carry["verdict"] is True
    reason = None if verdict else "; ".join(r for r in (parity.get("reason"), carry.get("reason")) if r)
    return {"verdict": verdict, "parity": parity, "carry": carry, "reason": reason}


def handback_latency(record: Any) -> dict[str, Any]:
    """Report-only: the module's mutation-scan and hand-off completion times."""
    after = record.get("after") if isinstance(record, dict) else None
    api = after.get("api") if isinstance(after, dict) else None
    stats = api.get("stats") if isinstance(api, dict) and isinstance(api.get("stats"), dict) else {}
    handoffs = _notes(after, "glreplay-handoff", "api") if isinstance(after, dict) else []
    return {"mutationScanMs": stats.get("mutationScanMs"), "completedMs": handoffs[-1].get("completedMs") if handoffs else None}


@contextmanager
def forced_fail_seed(reason: str) -> Iterator[dict[str, Any]]:
    """Splice a `debugForceFail` seed ahead of the host's GL-replay tag (plan g5g6 §3.8)."""
    original = live_host_module.gl_replay_script
    payload = json.dumps({"debugForceFail": reason}).replace("</", "<\\/")
    seed = f'<script id="{FORCE_FAIL_SEED_ID}">window.__OBED_GL_REPLAY__={payload};</script>\n'
    splice: dict[str, Any] = {"reason": reason, "splices": 0}

    def patched(runtime_plan: Any) -> str:
        combined = seed + original(runtime_plan)
        if combined.count(f'id="{FORCE_FAIL_SEED_ID}"') != 1 or combined.count('id="obed-gl-replay"') != 1:
            raise RuntimeError("force-fail seed must land once, ahead of exactly one GL-replay module tag")
        splice["splices"] += 1
        return combined

    live_host_module.gl_replay_script = patched
    try:
        yield splice
    finally:
        live_host_module.gl_replay_script = original


def score_forced(
    *, v_pass: Any, g_pass: Any, refusal: Any, g_handback: Any, parity: Any, reason: str, splice: Any,
) -> dict[str, Any]:
    """`forced-ok` iff the forced page is V's flag-off twin (plan g5g6 §3.8); never `pass`."""
    after = g_handback.get("after") if isinstance(g_handback, dict) and isinstance(g_handback.get("after"), dict) else None
    zones = _notes(after, "glreplay-zone") if after else []
    last = zones[-1] if zones else {}
    api = after.get("api") if after and isinstance(after.get("api"), dict) else {}
    stand_downs = api.get("standDowns") if isinstance(api.get("standDowns"), list) else []
    v_verdicts = [slide.get("verdict") for slide in visible_slides_of(v_pass)]
    g_verdicts = [slide.get("verdict") for slide in visible_slides_of(g_pass)]
    checks = {
        "splice": isinstance(splice, dict) and splice.get("splices") == 1,
        "mode": gl_replay_mode(g_pass) == "injected",
        "slides": bool(g_verdicts) and all(v is True for v in g_verdicts)
        and not visible_pass_reasons(g_pass, "VglForced", "qualified"),
        "reference": gl_replay_mode(v_pass) == "off" and not visible_pass_reasons(v_pass, "V", "qualified"),
        "matchesV": v_verdicts == g_verdicts,
        "refused": isinstance(refusal, dict) and refusal.get("verdict") is True,
        "zone": last.get("to") == "retired" and reason in stand_downs and (
            (last.get("reason") == "failure" and last.get("standDown") == reason) or last.get("reason") == "moduleRetired"
        ),
        "noLive": after is not None and not _notes(after, "glreplay-live") and not _notes(after, "glreplay-live", "api"),
        "parity": isinstance(parity, dict) and parity.get("verdict") is True,
        "knownReason": reason in GL_FORCE_FAIL_REASONS,
    }
    failing = [key for key, ok in checks.items() if not ok]
    return {"status": "forced-fail" if failing else "forced-ok", "checks": checks, "reason": f"failed {failing}" if failing else None}


def goto_rect_expectations(v_expectations: dict[int, dict[str, str]], *, armed: bool) -> dict[int, dict[str, str]]:
    """Pure: armed reuses the plan's own `V` expectations; disarmed marks every asset dead (plan §2)."""
    if armed:
        return v_expectations
    return {index: {asset: DEAD for asset in per} for index, per in v_expectations.items()}


def spacing_ok(
    offsets_ms: Sequence[float], *, min_gap_ms: float = 360.0, expected_count: int = len(G_BURST_OFFSETS_MS)
) -> bool | None:
    """Fail-closed on the REALIZED timestamps: exactly `expected_count` finite values, each
    consecutive gap >= `min_gap_ms`; a wrong count or a non-finite value is inconclusive, not a pass."""
    values = list(offsets_ms) if isinstance(offsets_ms, Sequence) else []
    if len(values) != expected_count or not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values
    ):
        return None
    return all(b - a >= min_gap_ms for a, b in zip(values, values[1:]))


def capture_is_fresh(live_expected: bool, unique_shas: Any, *, min_unique: int = 2) -> bool | None:
    """Fail-closed sanity control: a live-expected destination's burst frames must show at least
    `min_unique` distinct images (`burstProfile.uniqueShas`); an unreadable count is inconclusive,
    not a pass -- a stale/frozen capture must never silently read as a genuinely dead rect."""
    if not live_expected:
        return True
    if not isinstance(unique_shas, int) or isinstance(unique_shas, bool):
        return None
    return unique_shas >= min_unique


def combine_verdicts(*values: bool | None) -> bool | None:
    """Tri-state AND: any unknown makes the whole thing unknown, never a
    silent pass or fail."""
    if any(value is None for value in values):
        return None
    return all(values)


def read_execute_log(log_path: str | Path | None) -> list[dict[str, Any]]:
    """The host's own JSONL execute log (`player.output["logPath"]`), read
    defensively: a missing file, an unreadable line, or a non-object record is
    skipped, never raised."""
    if not log_path:
        return []
    try:
        lines = Path(log_path).read_text().splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def find_execute_record(records: list[dict[str, Any]], *, operation: str, slide: int) -> dict[str, Any] | None:
    for record in reversed(records):
        if record.get("kind") == "execute" and record.get("operation") == operation and record.get("slide") == slide:
            return record
    return None


def wait_for_execute_record(
    log_path: str | Path | None, *, operation: str, slide: int, timeout_s: float = 2.0,
    now: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any] | None:
    """The host's execute log is drained by a background writer thread, so a
    record can lag its call by a few ms -- poll briefly rather than assume it
    is already flushed. Bounded: a record that never lands is `None`, never a
    hang."""
    deadline = now() + timeout_s
    record = None
    while now() < deadline:
        record = find_execute_record(read_execute_log(log_path), operation=operation, slide=slide)
        if record is not None:
            return record
        sleep(0.05)
    return record


def score_no_consumption(
    observed_scene_id: str | None, expected_scene_id: str | None, execute_record: dict[str, Any] | None,
) -> dict[str, Any]:
    """Pure: the settled scene plus the host's own execute-log evidence in, a
    verdict out. `autoPlayRunLength`/`autoPlayRunKinds`/`autoPlayFired` are
    read defensively -- another stream is landing them on `live_host.py`
    concurrently -- so a record that predates them is INCONCLUSIVE, never a
    false pass."""
    scene_ok = observed_scene_id is not None and observed_scene_id == expected_scene_id
    if not isinstance(execute_record, dict):
        return {"verdict": None, "sceneOk": scene_ok, "reason": "no execute-log record for this goTo"}
    run_length, fired = execute_record.get("autoPlayRunLength"), execute_record.get("autoPlayFired")
    if run_length is None or fired is None:
        return {
            "verdict": None, "sceneOk": scene_ok, "autoPlayRunLength": run_length, "autoPlayFired": fired,
            "reason": "execute log has no autoPlayRunLength/autoPlayFired yet",
        }
    log_ok = run_length == 0 and fired is False
    ok = scene_ok and log_ok
    return {
        "verdict": bool(ok), "sceneOk": scene_ok, "logOk": log_ok, "autoPlayRunLength": run_length,
        "autoPlayRunKinds": execute_record.get("autoPlayRunKinds"), "autoPlayFired": fired,
        "reason": None if ok else "scene or execute-log evidence contradicts no-consumption",
    }


GOTO_TELEMETRY_FIELDS = ("autoPlayRunLength", "autoPlayRunKinds", "autoPlayFired", "autoPlayDeferredReason")


def goto_telemetry(execute_record: dict[str, Any] | None) -> dict[str, Any]:
    """The four autoplay-repair fields off one goTo's execute-log record, for attaching to a
    destination artifact regardless of arm; absent fields read `None`, never raise."""
    return {field: (execute_record or {}).get(field) for field in GOTO_TELEMETRY_FIELDS}


def telemetry_present(execute_record: dict[str, Any] | None) -> bool | None:
    """`True` only when the execute-log record carries all four autoplay-repair fields (even if a
    field's own value is legitimately `null`); otherwise inconclusive, never a silent pass."""
    if isinstance(execute_record, dict) and all(field in execute_record for field in GOTO_TELEMETRY_FIELDS):
        return True
    return None


def _crop_screen_rect(frame: np.ndarray, rect: dict[str, float]) -> np.ndarray:
    height, width = frame.shape[:2]
    x0, y0 = max(0, int(round(rect["x"]))), max(0, int(round(rect["y"])))
    x1, y1 = min(width, int(round(rect["x"] + rect["w"]))), min(height, int(round(rect["y"] + rect["h"])))
    if x1 <= x0 or y1 <= y0:
        return np.zeros((0, 0, 3), dtype=frame.dtype)
    return frame[y0:y1, x0:x1]


def score_region_changed(
    before: np.ndarray, after: np.ndarray, rect: dict[str, float], *, min_mae: float = CHARACTER_REGION_MAE_MIN,
) -> dict[str, Any]:
    """Pure: two full-frame screenshots plus a screen-space rect in, a verdict
    out. Proves a click-driven build actually fired by comparing pixel
    content (not motion) before/after one `advance` -- a completed dissolve is
    static, so `liveness_mask` alone cannot see it."""
    crop_before, crop_after = _crop_screen_rect(before, rect), _crop_screen_rect(after, rect)
    if crop_before.size == 0 or crop_after.size == 0:
        return {"verdict": False, "mae": None, "reason": "characters region crop is empty"}
    if crop_before.shape != crop_after.shape:
        return {"verdict": False, "mae": None, "reason": "characters region crop shape mismatch"}
    mae = float(np.mean(np.abs(crop_before[:, :, :3].astype(np.float64) - crop_after[:, :, :3].astype(np.float64))))
    ok = mae >= min_mae
    return {"verdict": ok, "mae": mae, "minMae": min_mae, "reason": None if ok else "characters region did not change after the advance"}


def _exclusion_mask(shape: tuple[int, int], exclude_rects: Sequence[dict[str, float]]) -> np.ndarray:
    mask = np.ones(shape, dtype=bool)
    height, width = shape
    for rect in exclude_rects:
        x0, y0 = max(0, int(rect.get("x", 0))), max(0, int(rect.get("y", 0)))
        x1 = min(width, int(rect.get("x", 0) + rect.get("w", 0)))
        y1 = min(height, int(rect.get("y", 0) + rect.get("h", 0)))
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = False
    return mask


def score_static_control(
    transport: Any, exclude_rects: Sequence[dict[str, float]], *,
    min_bright: float = STATIC_CONTROL_MIN_BRIGHT, max_mae: float = STATIC_CONTROL_MAX_MAE, gap_s: float = 0.4,
) -> dict[str, Any]:
    """The area outside every expected movie rect must show genuinely rendered content (never a
    uniform black overlay) and stay stable, so a wrong-slide or still-black capture cannot pass."""
    first = decode_png(transport.call("Page.captureScreenshot", format="png")["data"])
    time.sleep(gap_s)
    second = decode_png(transport.call("Page.captureScreenshot", format="png")["data"])
    if first.size == 0 or first.shape != second.shape:
        return {"verdict": False, "max": None, "mae": None, "reason": "static control capture is empty or mismatched"}
    mask = _exclusion_mask(first.shape[:2], exclude_rects)
    if not mask.any():
        return {"verdict": None, "max": None, "mae": None, "reason": "no area outside the expected movie rects to measure"}
    region_a, region_b = first[mask][:, :3], second[mask][:, :3]
    max_value = float(max(region_a.max(), region_b.max()))
    mae = float(np.mean(np.abs(region_a.astype(np.float64) - region_b.astype(np.float64))))
    non_black, stable = max_value >= min_bright, mae <= max_mae
    reason = None
    if not non_black:
        reason = f"no rendered content outside the movie rects (brightest pixel {max_value:.1f} < {min_bright})"
    elif not stable:
        reason = f"content outside the movie rects changed unexpectedly (mae={mae:.1f}, max {max_mae})"
    return {"verdict": non_black and stable, "max": max_value, "mae": mae, "reason": reason}


def _rect_from_layer_state(state: dict[str, Any]) -> dict[str, float] | None:
    position = state.get("position") or {}
    anchor = state.get("anchorPoint") or {}
    width, height = state.get("width"), state.get("height")
    px, py = position.get("pointX"), position.get("pointY")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (width, height, px, py)):
        return None
    ax = anchor.get("pointX") if isinstance(anchor.get("pointX"), (int, float)) else 0.5
    ay = anchor.get("pointY") if isinstance(anchor.get("pointY"), (int, float)) else 0.5
    return {"x": float(px - ax * width), "y": float(py - ay * height), "w": float(width), "h": float(height)}


def _walk_character_rects(node: Any) -> list[dict[str, float]]:
    """Every authored rect of an `apple:*character*` buildIn effect (Keynote's
    dissolve-character build), walked the way `flatten_effect_names` walks
    `effects`, but keeping the geometry that function drops."""
    found: list[dict[str, float]] = []
    if isinstance(node, dict):
        base_layer = node.get("baseLayer")
        if is_character_effect(node.get("name")) and isinstance(base_layer, dict):
            rect = _rect_from_layer_state(base_layer.get("initialState") or {})
            if rect is not None:
                found.append(rect)
        for child in node.get("effects") or []:
            found.extend(_walk_character_rects(child))
    elif isinstance(node, list):
        for child in node:
            found.extend(_walk_character_rects(child))
    return found


def _union_rect(rects: Sequence[dict[str, float]]) -> dict[str, float] | None:
    if not rects:
        return None
    x0, y0 = min(r["x"] for r in rects), min(r["y"] for r in rects)
    x1, y1 = max(r["x"] + r["w"] for r in rects), max(r["y"] + r["h"] for r in rects)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def character_region_rect(export_root: Path, slide: dict[str, Any]) -> dict[str, float] | None:
    """The authored bounding box of this slide's own `apple:*character*` builds
    (ground truth read straight from the export's per-slide JSON, the way
    `derive_plan` reads it), or `None` if the slide has none. Pass G's own
    no-consumption evidence: unrelated to any tracked movie asset, so it
    cannot be derived from `plan.slide_instances`."""
    uuid = slide.get("exportedUuid")
    if not isinstance(uuid, str) or not uuid:
        return None
    try:
        data = json.loads(safe_export_file(export_root, f"assets/{uuid}/{uuid}.json").read_text())
        events = data["events"]
    except Exception:  # noqa: BLE001 - no character region is a valid, checkable answer
        return None
    rects: list[dict[str, float]] = [
        rect
        for event in (events if isinstance(events, list) else [])
        if isinstance(event, dict)
        for rect in _walk_character_rects(event.get("effects"))
    ]
    return _union_rect(rects)


def score_no_build_consumed(
    player: LiveOutputHost, expected_scene_id: str | None, character_rect: dict[str, float],
    stage_map: dict[str, Any], *, execute_record: dict[str, Any] | None,
) -> dict[str, Any]:
    """Scene + execute-log evidence the click-driven builds are still pending, plus pixel evidence
    the characters' region only changes after one more `advance` -- proving it really was pending."""
    observed = player.observe()
    consumption = score_no_consumption(observed.scene_id, expected_scene_id, execute_record)
    transport = player._require_transport()
    screen_rect = to_screen_rect(character_rect, stage_map)
    before = decode_png(transport.call("Page.captureScreenshot", format="png")["data"])
    player.execute("advance")
    wait_until_settled(player)
    # A click-driven build's own animation is invisible to `busy`; give it the same settle margin
    # every advance-driven arrival gets elsewhere in this file.
    time.sleep(POST_ADVANCE_SETTLE_S)
    after = decode_png(transport.call("Page.captureScreenshot", format="png")["data"])
    changed = score_region_changed(before, after, screen_rect)
    return {
        "consumption": consumption, "regionChanged": changed,
        "verdict": combine_verdicts(consumption.get("verdict"), changed.get("verdict")),
    }


def resolve_no_consumption(
    player: LiveOutputHost, expected_scene_id: str | None, character_rect: dict[str, float] | None,
    stage_map: dict[str, Any] | None, *, execute_record: dict[str, Any] | None,
) -> dict[str, Any]:
    """Fail-closed: missing/unreadable characters geometry or an invalid stage map is inconclusive
    (never silently `True`) and never touches `player`; only then is the real evidence scored."""
    if character_rect is None:
        return {"verdict": None, "reason": "characters region rect is unavailable (missing/unreadable slide geometry)"}
    if not stage_map_valid(stage_map):
        return {"verdict": None, "reason": "stage map invalid at the no-consumption sample"}
    return score_no_build_consumed(player, expected_scene_id, character_rect, stage_map, execute_record=execute_record)


def run_goto_destination(
    player: LiveOutputHost, from_ordinal: int, to_ordinal: int, slides: list[dict[str, Any]],
    instances: dict[int, dict[str, list[Any]]], viewport: tuple[int, int], *,
    expectations: dict[int, dict[str, str]], evidence: Callable[..., dict[str, str]] | None,
    expected_scene_id: str | None, character_rect: dict[str, float] | None,
    armed: bool, require_no_consumption: bool,
) -> dict[str, Any]:
    """One goTo, driven for real through `LiveOutputHost.execute`, scored with the same
    `visible_slide_record` the V/Voff passes use -- never a re-derived scorer."""
    reasons: list[str] = []
    player.execute("goTo", from_ordinal)
    # `execute("goTo")`'s own returned observation is not settled when the autoplay repair is
    # disarmed (it is the bare digit/Enter ack); check the requested slide only AFTER settling.
    wait_until_settled(player)
    from_observed = player.observe()
    source_reached = from_observed.original_slide == from_ordinal
    if not source_reached:
        reasons.append(f"source goTo did not reach slide {from_ordinal} (landed on {from_observed.original_slide!r})")
    slide = next(s for s in slides if s["originalOrdinal"] == to_ordinal)
    player.execute("goTo", to_ordinal)
    wait_until_settled(player)
    to_observed = player.observe()
    destination_reached = to_observed.original_slide == to_ordinal
    if not destination_reached:
        reasons.append(f"destination goTo did not reach slide {to_ordinal} (landed on {to_observed.original_slide!r})")
    # `execute("goTo")` settling is a DOM/runtime fact, not a compositor one; give it the same
    # margin `advance_until_original_slide` gives every advance-driven arrival before a burst.
    time.sleep(POST_ADVANCE_SETTLE_S)
    record = visible_slide_record(
        player, slide, instances, viewport, scorer=_scorers()[1], evidence=evidence,
        expectations=expectations, offsets_ms=G_BURST_OFFSETS_MS,
    )
    transport = player._require_transport()
    video_count = transport.evaluate("document.querySelectorAll('video').length")
    live_expected = any(item.get("expect") == LIVE for item in record.get("expectedRects") or [])
    video_ok = (not live_expected) or (isinstance(video_count, int) and not isinstance(video_count, bool) and video_count > 0)
    spaced = spacing_ok(record.get("shotOffsetsMs") or [])
    unique_shas = (record.get("burstProfile") or {}).get("uniqueShas")
    capture_fresh = capture_is_fresh(live_expected, unique_shas)
    if record.get("verdict") is not True:
        reasons.append(f"destination {to_ordinal} rects do not meet expectations (status={record.get('status')!r})")
    if not video_ok:
        reasons.append(f"destination {to_ordinal} has a live-expected movie but no <video> element")
    if spaced is not True:
        reasons.append(f"destination {to_ordinal} burst spacing is unproven or too fast: {record.get('shotOffsetsMs')}")
    if capture_fresh is not True:
        reasons.append(f"destination {to_ordinal} burst captured {unique_shas} distinct frame(s) (live-expected: {live_expected})")

    stage_map = record.get("stageMap")
    exclude_rects = [item["screen"] for item in record.get("expectedRects") or [] if isinstance(item.get("screen"), dict)]
    static_control = score_static_control(transport, exclude_rects)
    if static_control.get("verdict") is not True:
        reasons.append(f"destination {to_ordinal} static content control: {static_control}")

    execute_record = wait_for_execute_record(player.output.get("logPath"), operation="goTo", slide=to_ordinal)
    telemetry = goto_telemetry(execute_record)
    telemetry_ok = telemetry_present(execute_record) if armed else True
    if telemetry_ok is not True:
        reasons.append(f"destination {to_ordinal} armed execute-log telemetry is missing: {telemetry}")

    no_consumption = None
    if require_no_consumption:
        no_consumption = resolve_no_consumption(
            player, expected_scene_id, character_rect, stage_map, execute_record=execute_record,
        )
        if no_consumption.get("verdict") is not True:
            reasons.append(f"no-consumption check for destination {to_ordinal}: {no_consumption}")

    verdict = combine_verdicts(
        record.get("verdict"), video_ok, spaced, capture_fresh, source_reached, destination_reached,
        static_control.get("verdict"), telemetry_ok,
        no_consumption.get("verdict") if require_no_consumption else True,
    )
    return {
        "fromOrdinal": from_ordinal, "toOrdinal": to_ordinal, "record": record, "videoElementCount": video_count,
        "sourceReached": source_reached, "destinationReached": destination_reached,
        "staticControl": static_control, "autoPlay": telemetry, "noConsumption": no_consumption,
        "verdict": verdict, "reasons": reasons,
    }


def destinations_of(entry: Any) -> list[dict[str, Any]]:
    if not isinstance(entry, dict):
        return []
    destinations = entry.get("destinations")
    return [d for d in destinations if isinstance(d, dict)] if isinstance(destinations, list) else []


def overall_status_g(result: dict[str, Any]) -> tuple[str, list[str]]:
    """Pure: both arms need EVERY destination verdict True (for the null control that means the
    DEAD expectation was genuinely met -- a LIVE reading there is the "green null control" the
    plan requires to fail this pass) and a visible output; else fail, or inconclusive on any None."""
    armed_entry, off_entry = result.get("armed") or {}, result.get("nullControl") or {}
    armed, off = destinations_of(armed_entry), destinations_of(off_entry)
    if len(armed) != len(GOTO_MATRIX) or len(off) != len(GOTO_MATRIX):
        return "error", ["pass G did not score every goTo destination in both arms"]
    reasons: list[str] = []
    for label, entry, group in (("armed", armed_entry, armed), ("null control", off_entry, off)):
        if entry.get("outputVisible") is not True:
            reasons.append(f"{label} output was not visible after show() (outputVisible={entry.get('outputVisible')!r})")
        if entry.get("stopError"):
            reasons.append(f"{label} player.stop() failed: {entry.get('stopError')}")
        for dest in group:
            if dest.get("verdict") is not True:
                detail = "; ".join(dest.get("reasons") or []) or f"verdict={dest.get('verdict')!r}"
                reasons.append(f"{label} goTo {dest.get('fromOrdinal')}->{dest.get('toOrdinal')}: {detail}")
    if any(dest.get("verdict") is None for dest in armed + off):
        return "inconclusive", reasons
    return ("pass" if not reasons else "fail"), reasons


def warm_up_for_screenshots(player: LiveOutputHost) -> Any:
    """Every screenshot-scoring pass must call this before its first burst: a fresh session starts
    hidden behind the output-black overlay until `execute("show")` runs (mirrors `run_visible_pass`'s
    own warm-up). Returns the `show()` observation so a caller can verify `output_visible`."""
    shown = player.execute("show")
    transport = player._require_transport()
    transport.evaluate(ENSURE_PLAYING_JS)
    wait_for_decode(player)
    time.sleep(CLICK_DELAY_S)
    return shown


def _run_goto_arm(
    export_root: Path, slides: list[dict[str, Any]], *, env: dict[str, str | None], tag: str, armed: bool,
    instances: dict[int, dict[str, list[Any]]], expectations: dict[int, dict[str, str]], viewport: tuple[int, int],
    evidence_dir: Path, character_rect: dict[str, float] | None, onset_scene_id: str, gl_replay: str = "off",
) -> dict[str, Any]:
    """One armed or null-control goTo session: start, warm up, drive the whole `GOTO_MATRIX`, stop."""
    result: dict[str, Any] = {}
    evidence = visible_evidence_writer(evidence_dir, tag)
    with env_override(env):
        player = LiveOutputHost(export_root, slides, headless=True, gl_replay=gl_replay)
        try:
            player.start()
            shown = warm_up_for_screenshots(player)
            result["continuity"] = player.output["continuity"]
            result["outputVisible"] = shown.output_visible
            result["destinations"] = [
                run_goto_destination(
                    player, from_ordinal, to_ordinal, slides, instances, viewport,
                    expectations=expectations, evidence=evidence,
                    expected_scene_id=onset_scene_id if to_ordinal == GOTO_CONSUMPTION_CHECK_TO else None,
                    character_rect=character_rect, armed=armed,
                    require_no_consumption=armed and to_ordinal == GOTO_CONSUMPTION_CHECK_TO,
                )
                for from_ordinal, to_ordinal in GOTO_MATRIX
            ]
        finally:
            try:
                player.stop()
            except Exception as exc:  # noqa: BLE001 - record, never mask an earlier failure
                result["stopError"] = str(exc)
    return result


def run_pass_g(args: argparse.Namespace) -> dict[str, Any]:
    """Drive every `GOTO_MATRIX` entry through the real goTo, once armed and once with
    `GOTO_AUTOPLAY_ENV=off` (the null control), via `_run_goto_arm`."""
    plan_export = prepare_export(args.fixture, args.original_index, "pass-g-plan")
    plan_slides = load_slides(plan_export)
    plan = ground_truth_plan(plan_export, plan_slides)
    facts = ground_truth_facts(plan)
    instances = slide_instances_of(plan)
    v_expectations = facts["rectExpectations"]["V"]

    consumption_slide = next(s for s in plan_slides if s["originalOrdinal"] == GOTO_CONSUMPTION_CHECK_TO)
    character_rect = character_region_rect(plan_export, consumption_slide)
    consumption_index = int(consumption_slide["playerIndex"])

    instances_g = {index: dict(assets) for index, assets in instances.items()}
    expectations_g = {index: dict(assets) for index, assets in v_expectations.items()}
    if character_rect is not None:
        instances_g.setdefault(consumption_index, {})[CHARACTERS_ASSET_KEY] = [character_rect]
        expectations_g.setdefault(consumption_index, {})[CHARACTERS_ASSET_KEY] = DEAD

    viewport = (VIEWPORT_WIDTH, VIEWPORT_HEIGHT) if args.attach else args.viewport
    evidence_dir = args.artifact.parent / "visible"
    onset_scene_id = str(facts["onset1to2"])

    result: dict[str, Any] = {"pass": "G", "attach": bool(args.attach), "viewport": {"width": viewport[0], "height": viewport[1]}}
    chrome_proc: subprocess.Popen | None = None
    try:
        env: dict[str, str | None] = {}
        if args.attach:
            port = free_port()
            profile = args.artifact.parent / "attach-chrome-profile-g"
            if profile.exists():
                shutil.rmtree(profile)
            chrome_proc = launch_attach_chrome(port, profile)
            wait_for_cdp(port)
            force_exact_viewport(port, VIEWPORT_WIDTH, VIEWPORT_HEIGHT)
            env = {ATTACH_ENV: f"http://127.0.0.1:{port}", ADVANCE_ENV: "click"}
        else:
            force_viewport(*viewport)

        export_armed = prepare_export(args.fixture, args.original_index, "pass-g-armed")
        result["armed"] = _run_goto_arm(
            export_armed, load_slides(export_armed), env=env, tag="G", armed=True,
            instances=instances_g, expectations=goto_rect_expectations(expectations_g, armed=True),
            viewport=viewport, evidence_dir=evidence_dir, character_rect=character_rect, onset_scene_id=onset_scene_id,
            gl_replay=args.gl_replay,
        )

        export_off = prepare_export(args.fixture, args.original_index, "pass-g-off")
        result["nullControl"] = _run_goto_arm(
            export_off, load_slides(export_off), env={**env, GOTO_AUTOPLAY_ENV: "off"}, tag="Goff", armed=False,
            instances=instances_g, expectations=goto_rect_expectations(expectations_g, armed=False),
            viewport=viewport, evidence_dir=evidence_dir, character_rect=character_rect, onset_scene_id=onset_scene_id,
            gl_replay=args.gl_replay,
        )
    finally:
        if chrome_proc is not None:
            chrome_proc.terminate()
            try:
                chrome_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome_proc.kill()
                chrome_proc.wait(timeout=5)
            result["chromePid"] = chrome_proc.pid
            result["chromeExitCode"] = chrome_proc.poll()

    result["status"], result["reasons"] = overall_status_g(result)
    return result


def run_pass_g_cli(args: argparse.Namespace) -> None:
    artifact = args.artifact
    artifact.parent.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"kind": "live-continuity-probe-pass-g", "status": "running"}

    def save() -> None:
        artifact.write_text(json.dumps(result, indent=2, default=str) + "\n")

    save()
    try:
        result.update(run_pass_g(args))
    except Exception as exc:  # noqa: BLE001 - always leave a readable artifact behind
        result["status"] = "error"
        result["error"] = str(exc)
    finally:
        save()
    print(json.dumps({"status": result.get("status"), "reasons": result.get("reasons")}, indent=2))


def check_no_leftover_chrome() -> str:
    try:
        completed = subprocess.run(["pgrep", "-fl", "obed-live-chrome"], capture_output=True, text=True)
        return completed.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return f"pgrep failed: {exc}"


def boundary_verdict(entry: dict[str, Any], key: str) -> bool | None:
    value = entry.get(key)
    return value.get("verdict") if isinstance(value, dict) else None


def continuity_mode(entry: dict[str, Any]) -> str | None:
    continuity = entry.get("continuity")
    return continuity.get("mode") if isinstance(continuity, dict) else None


def background_alpha(css: str | None) -> float:
    """Parse a CSS `rgb()`/`rgba()` color's alpha channel. An `rgb()` string has no
    alpha channel at all, which computed-style renders as fully opaque -- treat
    that as alpha 1.0, never as "unknown => pass"."""
    if not css:
        return 1.0
    match = re.match(r"rgba?\(([^)]*)\)", css.strip())
    if not match:
        return 1.0
    parts = [p.strip() for p in match.group(1).split(",")]
    if len(parts) != 4:
        return 1.0
    try:
        return float(parts[3])
    except ValueError:
        return 1.0


def stage_fit_ok(entry: dict[str, Any]) -> bool:
    """Fail-closed: only an explicit truthy `stageFit.verdict` passes. A missing
    `stageFit` (an arm that crashed before scoring it, or a caller that never
    set the key) is not evidence of a correct fit and must not pass."""
    stage_fit = entry.get("stageFit")
    if not isinstance(stage_fit, dict):
        return False
    return bool(stage_fit.get("verdict"))


def stage_fit_reason(entry: dict[str, Any], label: str) -> str | None:
    if stage_fit_ok(entry):
        return None
    if not isinstance(entry.get("stageFit"), dict):
        return f"{label} stageFit missing"
    return f"{label} stageFit failed"


def visible_slides_of(entry: Any) -> list[dict[str, Any]]:
    if not isinstance(entry, dict):
        return []
    slides = entry.get("slides")
    return [slide for slide in slides if isinstance(slide, dict)] if isinstance(slides, list) else []


def visible_pass_reasons(entry: Any, label: str, expected_mode: str) -> list[str]:
    """Fail-closed, in the style of `stage_fit_reason`: a pass that is absent,
    errored, ran the wrong mechanism, was not fitted as expected on every
    slide's burst, leaked its browser, or scored nothing is not evidence -- and
    when it is not, its slide verdicts are not consulted at all."""
    if not isinstance(entry, dict):
        return [f"visible pass {label} missing"]
    if entry.get("status") == "error" or entry.get("error"):
        return [f"visible pass {label} errored: {entry.get('error')}"]
    if not stage_fit_ok(entry):
        missing = not isinstance(entry.get("stageFit"), dict)
        return [f"visible pass {label} stage fit {'missing' if missing else 'failed'}"]
    reasons: list[str] = []
    mode = continuity_mode(entry)
    if mode != expected_mode:
        reasons.append(f"visible pass {label} continuity.mode={mode!r}, expected {expected_mode!r}")
    if entry.get("stopError"):
        reasons.append(f"visible pass {label} player.stop() failed: {entry.get('stopError')}")
    if not visible_slides_of(entry):
        reasons.append(f"visible pass {label} scored no slides")
    return reasons


def visible_rect_expectation_counts(entry: Any) -> dict[str, int]:
    """How many per-rect expectations a pass stated, and how many it met. Only
    slides that were actually scored count: an inconclusive or errored slide proves
    nothing in either direction."""
    counts = {"liveTotal": 0, "liveMet": 0, "deadTotal": 0, "deadMet": 0}
    for slide in visible_slides_of(entry):
        if slide.get("status") not in ("pass", "fail"):
            continue
        for rect in slide.get("perRect") or []:
            if not isinstance(rect, dict) or rect.get("expect") not in (LIVE, DEAD):
                continue
            prefix = LIVE if rect.get("expect") == LIVE else DEAD
            counts[f"{prefix}Total"] += 1
            if rect.get("verdict") is True:
                counts[f"{prefix}Met"] += 1
    return counts


def plan_states_dead(result: dict[str, Any], name: str) -> bool:
    """Whether the PLAN states any dead expectation for a pass -- read from the
    plan, not from the records, so a slide that went inconclusive cannot quietly
    drop the dead half of the two-sided proof."""
    expectations = (result.get("groundTruth") or {}).get("rectExpectations")
    per_pass = expectations.get(name) if isinstance(expectations, dict) else None
    if not isinstance(per_pass, dict):
        return False
    return any(
        expect == DEAD for slide in per_pass.values() if isinstance(slide, dict)
        for expect in slide.values()
    )


def visible_expectation_reasons(entry: Any, label: str, *, requires_dead: bool = False) -> list[str]:
    """A pass that states per-rect expectations is scored against them: every slide
    must meet its own, and the pass must prove the instrument two-sided FROM THE
    INSIDE -- at least one live-expected rect that read live, and, when the plan
    states any dead expectation, at least one dead-expected rect that read dead."""
    reasons = [
        f"visible pass {label} slide {slide.get('originalOrdinal')} does not meet its per-rect "
        f"expectations (status={slide.get('status')!r})"
        for slide in visible_slides_of(entry) if slide.get("verdict") is not True
    ]
    counts = visible_rect_expectation_counts(entry)
    if not counts["liveMet"]:
        reasons.append(
            f"visible pass {label} has no live-expected rect that read live, so the instrument is simply always-red"
        )
    if (requires_dead or counts["deadTotal"]) and not counts["deadMet"]:
        reasons.append(
            f"visible pass {label} has no dead-expected rect that read dead, so the instrument is blind to a frozen movie"
        )
    return reasons


def visible_live_everywhere_reasons(entry: Any) -> list[str]:
    """`V` without stated expectations: live on every settled slide."""
    return [
        f"visible pass V slide {slide.get('originalOrdinal')} is not fully live (status={slide.get('status')!r})"
        for slide in visible_slides_of(entry) if slide.get("verdict") is not True
    ]


def visible_control_reasons(entry: Any, result: dict[str, Any]) -> list[str]:
    """`Voff` without stated expectations: the instrument's own control, which must
    be BOTH red where the raw export breaks (the 1->2 destination slide, derived
    from the plan -- movies do keep playing before any transition) AND live on
    slide 1: red everywhere would mean an always-red instrument, live everywhere a
    blind one."""
    reasons: list[str] = []
    slides = visible_slides_of(entry)
    first = next((slide for slide in slides if slide.get("originalOrdinal") == 1), None)
    if first is None or first.get("verdict") is not True:
        reasons.append("visible pass Voff slide 1 is not live, so the instrument is simply always-red")
    expected_red = (result.get("groundTruth") or {}).get("boundaryPlayerIndex")
    red = next((slide for slide in slides if slide.get("playerIndex") == expected_red), None)
    if not isinstance(expected_red, int) or isinstance(expected_red, bool):
        reasons.append("visible pass Voff expected-red slide is unknown (no groundTruth.boundaryPlayerIndex)")
    elif red is None:
        reasons.append(f"visible pass Voff never scored the expected-red slide (playerIndex {expected_red})")
    elif red.get("verdict") is not False:
        reasons.append(
            f"visible pass Voff slide {red.get('originalOrdinal')} is not RED "
            f"(verdict={red.get('verdict')!r}), so the instrument is blind to the raw-export defect"
        )
    return reasons


def visible_reasons(result: dict[str, Any]) -> list[str]:
    """Both passes are scored against the plan's per-rect expectations when they
    state any; a pass whose records carry none at all falls back to the rules that
    predate refusals, which is exactly what a plan without a retire produces."""
    visible = result.get("visible")
    visible = visible if isinstance(visible, dict) else {}
    on, off = visible.get("V"), visible.get("Voff")

    reasons = visible_pass_reasons(on, "V", "qualified")
    if not reasons:
        counts = visible_rect_expectation_counts(on)
        reasons = (
            visible_expectation_reasons(on, "V", requires_dead=plan_states_dead(result, "V"))
            if counts["liveTotal"] or counts["deadTotal"]
            else visible_live_everywhere_reasons(on)
        )

    off_reasons = visible_pass_reasons(off, "Voff", "off")
    if not off_reasons:
        counts = visible_rect_expectation_counts(off)
        off_reasons = (
            visible_expectation_reasons(off, "Voff", requires_dead=plan_states_dead(result, "Voff"))
            if counts["liveTotal"] or counts["deadTotal"]
            else visible_control_reasons(off, result)
        )
    return reasons + off_reasons


def refused_boundaries(result: dict[str, Any]) -> list[str]:
    ground = result.get("groundTruth")
    keys = ground.get("refusedBoundaries") if isinstance(ground, dict) else None
    return [key for key in keys if key in REFUSAL_VERDICT_KEY] if isinstance(keys, list) else []


def boundary_expectation_reasons(
    entry: dict[str, Any], label: str, key: str, refused: Sequence[str]
) -> list[str]:
    """One continuity boundary's arm expectation, derived from the plan: a boundary
    the plan CARRIES must read True; one the plan RETIRES must read False and also
    carry its positive `refused*` verdict, without which "did not continue" asserts
    nothing at all."""
    verdict = boundary_verdict(entry, key)
    if key not in refused:
        return [] if verdict is True else [f"{label} {key}={verdict!r}, expected True (the plan carries this boundary)"]
    reasons: list[str] = []
    if verdict is not False:
        reasons.append(f"{label} {key}={verdict!r}, expected False (the plan retires this boundary)")
    positive = REFUSAL_VERDICT_KEY[key]
    value = boundary_verdict(entry, positive)
    if value is None:
        reasons.append(f"{label} has no {positive} verdict, so the refusal is unproven")
    elif value is not True:
        scored = entry.get(positive)
        detail = scored.get("reason") if isinstance(scored, dict) else None
        reasons.append(f"{label} {positive}={value!r}: {detail}")
    return reasons


def armed_reasons(entry: dict[str, Any], label: str) -> list[str]:
    """An armed arm's 1->2 expectation: `armed1to2` must read True."""
    value = boundary_verdict(entry, "armed1to2")
    if value is True:
        return []
    if value is None:
        return [f"{label} has no armed1to2 verdict, so the armed boundary is unproven"]
    scored = entry.get("armed1to2")
    return [f"{label} armed1to2={value!r}: {scored.get('reason') if isinstance(scored, dict) else None}"]


def gl_requested(result: dict[str, Any]) -> bool:
    gl = result.get("glReplay")
    return isinstance(gl, dict) and gl.get("requested") == "auto"


def gl_mode_reasons(result: dict[str, Any]) -> list[str]:
    reasons = []
    for label, path, expected in EXPECTED_GL_MODES:
        entry: Any = result
        for key in path:
            entry = entry.get(key) if isinstance(entry, dict) else None
        mode = gl_replay_mode(entry)
        if mode != expected:
            reasons.append(f"{label} glReplay.mode={mode!r}, expected {expected!r}")
    return reasons


def gl_replay_reasons(result: dict[str, Any]) -> tuple[list[str], list[str]]:
    """`--gl-replay auto` failures and inconclusives (modes, Vgl, hand-back)."""
    fails = gl_mode_reasons(result)
    armed = (result.get("groundTruthGl") or {}).get("armed")
    if not isinstance(armed, dict):
        return fails + ["groundTruthGl.armed is missing, so nothing armed can be scored"], []
    vgl = (result.get("visible") or {}).get("Vgl")
    vgl_reasons = visible_pass_reasons(vgl, "Vgl", "qualified")
    if not vgl_reasons:
        vgl_reasons = visible_expectation_reasons(vgl, "Vgl")
        armed_slide = score_vgl_armed_slide(vgl, armed)
        if armed_slide["verdict"] is not True:
            vgl_reasons.append(f"visible pass Vgl armed slide: {armed_slide['reason']}")
    fails.extend(vgl_reasons)
    handback = result.get("handback")
    verdict = handback.get("verdict") if isinstance(handback, dict) else None
    reason = handback.get("reason") if isinstance(handback, dict) else "not captured"
    if verdict is False:
        fails.append(f"hand-back failed: {reason}")
    return fails, ([f"hand-back inconclusive: {reason}"] if verdict is None else [])


def overall_status(result: dict[str, Any]) -> tuple[str, list[str]]:
    """Pure: the assembled result dict in, (status, reasons) out. Reviewer finding
    #3: a green boundary verdict does not by itself prove the RIGHT mechanism was
    active -- arms A/C must actually have qualified continuity installed, arm B
    must actually have it off, and the attach arm's page must actually be
    transparent, or the verdict is not trustworthy even if the boundary math
    passed."""
    arms = result.get("arms", {})
    attach = result.get("attach", {})
    a, b, c = arms.get("A", {}), arms.get("B", {}), arms.get("C", {})
    a_armed, c_armed = gl_replay_mode(a) == "injected", gl_replay_mode(c) == "injected"
    all_gated = [
        *([] if a_armed else [boundary_verdict(a, "continue1to2")]),
        boundary_verdict(a, "restart2to3"), boundary_verdict(a, "continue3to4"),
        boundary_verdict(b, "continue3to4"),
        *([] if c_armed else [boundary_verdict(c, "continue1to2")]), boundary_verdict(c, "continue3to4"),
        boundary_verdict(attach, "continue1to2"), boundary_verdict(attach, "restart2to3"), boundary_verdict(attach, "continue3to4"),
    ]
    if any(v is None for v in all_gated):
        return "inconclusive", ["at least one gated boundary verdict is inconclusive (movie never decoded)"]

    reasons: list[str] = []
    refused = refused_boundaries(result)

    a_mode, b_mode, c_mode, attach_mode = continuity_mode(a), continuity_mode(b), continuity_mode(c), continuity_mode(attach)
    a_boundary_reasons = (
        armed_reasons(a, "arm A") if a_armed else boundary_expectation_reasons(a, "arm A", "continue1to2", refused)
    )
    reasons.extend(a_boundary_reasons)
    a_ok = not a_boundary_reasons and bool(boundary_verdict(a, "restart2to3")) and bool(boundary_verdict(a, "continue3to4"))
    if a_mode != "qualified":
        a_ok = False
        reasons.append(f"arm A continuity.mode={a_mode!r}, expected 'qualified'")
    reason = stage_fit_reason(a, "arm A")
    if reason:
        a_ok = False
        reasons.append(reason)

    b_ok = boundary_verdict(b, "continue3to4") is False
    if b_mode != "off":
        b_ok = False
        reasons.append(f"arm B continuity.mode={b_mode!r}, expected 'off'")
    reason = stage_fit_reason(b, "arm B")
    if reason:
        b_ok = False
        reasons.append(reason)

    c_boundary_reasons = (
        armed_reasons(c, "arm C") if c_armed else boundary_expectation_reasons(c, "arm C", "continue1to2", refused)
    )
    reasons.extend(c_boundary_reasons)
    c_ok = boundary_verdict(c, "continue3to4") is False and not c_boundary_reasons
    if c_mode != "qualified":
        c_ok = False
        reasons.append(f"arm C continuity.mode={c_mode!r}, expected 'qualified'")
    reason = stage_fit_reason(c, "arm C")
    if reason:
        c_ok = False
        reasons.append(reason)

    attach_boundary_reasons = boundary_expectation_reasons(attach, "attach", "continue1to2", refused)
    reasons.extend(attach_boundary_reasons)
    attach_ok = (
        not attach_boundary_reasons
        and bool(boundary_verdict(attach, "restart2to3"))
        and bool(boundary_verdict(attach, "continue3to4"))
    )
    if attach_mode != "qualified":
        attach_ok = False
        reasons.append(f"attach continuity.mode={attach_mode!r}, expected 'qualified'")
    alpha = background_alpha((attach.get("transparentBackground") or {}).get("computedBackground"))
    if alpha != 0:
        attach_ok = False
        reasons.append(f"attach background alpha={alpha}, expected 0")
    reason = stage_fit_reason(attach, "attach")
    if reason:
        attach_ok = False
        reasons.append(reason)

    visible = visible_reasons(result)
    reasons.extend(visible)

    gl_fails, gl_unknown = gl_replay_reasons(result) if gl_requested(result) else ([], [])
    reasons.extend(gl_fails)

    ok = a_ok and b_ok and c_ok and attach_ok and not visible and not gl_fails
    if not ok and not reasons:
        reasons.append("a boundary verdict did not match the expected pattern for its arm")
    if ok and gl_unknown:
        return "inconclusive", reasons + gl_unknown
    return ("pass" if ok else "fail"), reasons


def write_handback_shot(evidence_dir: Path, name: str, sink: dict[str, Any]) -> None:
    frame, record = sink.get("frame"), sink.get("record")
    if frame is None or not isinstance(record, dict):
        return
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / f"{name}-handback.png"
    cv2.imwrite(str(path), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    record["shot"] = str(path)


def gl_ground_truth(export_root: Path, slides: list[dict[str, Any]], facts: dict[str, Any]) -> tuple[
    ContinuityPlan, dict[str, Any], dict[int, dict[str, str]]
]:
    """The flag-on plan, its facts, and Vgl's expectations."""
    plan_on = ground_truth_plan(export_root, slides, gl_replay=True)
    facts_on = ground_truth_facts(plan_on, armed=True)
    vgl = rect_expectations(plan_on, runtime_of(plan_on), continuity_on=True)
    check_vgl_expectations(facts["rectExpectations"]["V"], vgl, facts_on["armed"])
    return plan_on, facts_on, vgl


def run_forced_fail(args: argparse.Namespace) -> dict[str, Any]:
    """`--gl-force-fail`: V and a forced Vgl, scored with the flag-off facts."""
    reason = args.gl_force_fail
    viewport = args.viewport
    evidence_dir = args.artifact.parent / "visible"
    export_plan = prepare_export(args.fixture, args.original_index, "forced-plan")
    plan_slides = load_slides(export_plan)
    plan = ground_truth_plan(export_plan, plan_slides)
    facts = ground_truth_facts(plan)
    armed = gl_ground_truth(export_plan, plan_slides, facts)[1]["armed"]
    retire = facts["retire"]
    if not retire or retire["boundaryKey"] != armed["boundaryKey"]:
        raise SystemExit("a forced stand-down needs the flag-off plan to retire the armed boundary")
    expected_stage = expected_stage_fit(facts["canvas"], {"width": viewport[0], "height": viewport[1]})
    result: dict[str, Any] = {"groundTruth": {"retire": retire, "armed": armed}, "visible": {}}

    v_sink: dict[str, Any] = {}
    export_v = prepare_export(args.fixture, args.original_index, "forced-v")
    result["visible"]["V"] = run_visible_pass(
        "V", export_v, load_slides(export_v), plan, viewport, expected_stage, evidence_dir,
        facts["rectExpectations"]["V"], burst_poke=args.burst_poke, gl_replay="off",
        after_slide=handback_hook(armed, v_sink, expect_handoff=False),
    )
    write_handback_shot(evidence_dir, "V", v_sink)
    result["visible"]["V"]["handback"] = v_sink.get("record")

    g_sink: dict[str, Any] = {}
    export_g = prepare_export(args.fixture, args.original_index, "forced-vgl")
    with forced_fail_seed(reason) as splice:
        result["visible"]["VglForced"] = run_visible_pass(
            "VglForced", export_g, load_slides(export_g), plan, viewport, expected_stage, evidence_dir,
            facts["rectExpectations"]["V"], burst_poke=args.burst_poke, gl_replay="auto",
            after_slide=handback_hook(armed, g_sink, expect_handoff=False, refusal=True),
        )
    write_handback_shot(evidence_dir, "VglForced", g_sink)
    g_pass = result["visible"]["VglForced"]
    g_pass["handback"] = g_sink.get("record")
    result["splice"] = dict(splice)
    result["refused1to2"] = score_refusal(g_sink.get("refusal"), retire, continuity_mode(g_pass) == "qualified")
    result["parity"] = handback_parity(
        v_sink.get("record"), v_sink.get("frame"), g_sink.get("record"), g_sink.get("frame"), armed, poke=args.burst_poke,
    )
    result["forced"] = score_forced(
        v_pass=result["visible"]["V"], g_pass=g_pass, refusal=result["refused1to2"], g_handback=g_sink.get("record"),
        parity=result["parity"], reason=reason, splice=splice,
    )
    result["status"] = result["forced"]["status"]
    result["leftoverChrome"] = check_no_leftover_chrome()
    return result


def check_fixture(args: argparse.Namespace) -> None:
    if not args.fixture.is_dir():
        raise SystemExit(f"fixture is unavailable: {args.fixture}")
    if not args.original_index.is_file():
        raise SystemExit(f"original index is unavailable: {args.original_index}")


def run_forced_fail_cli(args: argparse.Namespace) -> None:
    artifact = args.artifact
    artifact.parent.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "kind": "live-continuity-probe-gl-forced-fail", "status": "running",
        "glReplay": {"requested": "auto", "forcedFail": args.gl_force_fail},
        "viewport": {"width": args.viewport[0], "height": args.viewport[1]},
    }

    def save() -> None:
        artifact.write_text(json.dumps(result, indent=2, default=str) + "\n")

    save()
    try:
        check_fixture(args)
        result.update(run_forced_fail(args))
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - always leave a readable artifact behind
        result["status"] = "forced-fail"
        result["error"] = str(exc)
    finally:
        save()
    print(json.dumps({"status": result.get("status"), "forced": result.get("forced")}, indent=2, default=str))


def main() -> None:
    args = parse_args()
    if args.gl_force_fail is not None:
        run_forced_fail_cli(args)
        return
    check_fixture(args)
    if args.only_pass == "G":
        run_pass_g_cli(args)
        return
    auto = args.gl_replay == "auto"
    artifact = args.artifact
    artifact.parent.mkdir(parents=True, exist_ok=True)
    viewport = args.viewport
    result: dict[str, Any] = {
        "kind": "live-continuity-probe",
        "fixture": str(args.fixture),
        "originalIndex": str(args.original_index),
        "status": "running",
        "viewport": {"width": viewport[0], "height": viewport[1]},
        "attachViewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
    }
    if auto:
        result["glReplay"] = {"requested": "auto"}

    def save() -> None:
        artifact.write_text(json.dumps(result, indent=2, default=str) + "\n")

    save()
    try:
        export_a = prepare_export(args.fixture, args.original_index, "arm-a")
        slides_a = load_slides(export_a)
        plan = ground_truth_plan(export_a, slides_a)
        facts = ground_truth_facts(plan)
        result["groundTruth"] = {
            key: facts[key]
            for key in (
                "asset", "onset1to2", "boundaryPlayerIndex", "restartScene", "bridgeScene",
                "pinRect", "bridgeSrcRect", "destRect", "canvas",
                "retire", "refusedBoundaries", "refusals", "rectExpectations",
            )
        }
        expected_stage = expected_stage_fit(facts["canvas"], {"width": viewport[0], "height": viewport[1]})
        attach_expected_stage = expected_stage_fit(facts["canvas"], {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT})
        result["expectedStage"] = expected_stage
        result["attachExpectedStage"] = attach_expected_stage
        facts_on: dict[str, Any] | None = None
        if auto:
            plan_on, facts_on, vgl_expectations = gl_ground_truth(export_a, slides_a, facts)
            result["groundTruthGl"] = {
                "armed": facts_on["armed"], "armedBoundaries": facts_on["armedBoundaries"],
                "rectExpectations": {"Vgl": vgl_expectations},
            }
        save()

        result["arms"] = {}
        result["arms"]["A"] = run_arm(
            "A", export_a, slides_a, facts, viewport, expected_stage, gl_replay=args.gl_replay, facts_on=facts_on,
        )
        save()

        export_b = prepare_export(args.fixture, args.original_index, "arm-b")
        with env_override({CONTINUITY_ENV: "off"}):
            result["arms"]["B"] = run_arm(
                "B", export_b, load_slides(export_b), facts, viewport, expected_stage, gl_replay="off",
            )
        save()

        export_c = prepare_export(args.fixture, args.original_index, "arm-c")
        with bridge_disabled():
            result["arms"]["C"] = run_arm(
                "C", export_c, load_slides(export_c), facts, viewport, expected_stage,
                gl_replay=args.gl_replay, facts_on=facts_on,
            )
        save()

        result["leftoverChromeAfterArms"] = check_no_leftover_chrome()
        save()

        evidence_dir = artifact.parent / "visible"
        export_v = prepare_export(args.fixture, args.original_index, "visible-v")
        result["visible"] = {}
        v_sink: dict[str, Any] = {}
        result["visible"]["V"] = run_visible_pass(
            "V", export_v, load_slides(export_v), plan, viewport, expected_stage, evidence_dir,
            facts["rectExpectations"]["V"], burst_poke=args.burst_poke, gl_replay="off",
            after_slide=handback_hook(facts_on["armed"], v_sink, expect_handoff=False) if facts_on else None,
        )
        if auto:
            write_handback_shot(evidence_dir, "V", v_sink)
            result["visible"]["V"]["handback"] = v_sink.get("record")
        result["leftoverChromeAfterVisibleV"] = check_no_leftover_chrome()
        save()

        export_voff = prepare_export(args.fixture, args.original_index, "visible-voff")
        with env_override({CONTINUITY_ENV: "off"}):
            result["visible"]["Voff"] = run_visible_pass(
                "Voff", export_voff, load_slides(export_voff), plan, viewport, expected_stage, evidence_dir,
                facts["rectExpectations"]["Voff"], burst_poke=args.burst_poke, gl_replay="off",
            )
        result["leftoverChromeAfterVisible"] = check_no_leftover_chrome()
        save()

        if facts_on is not None:
            armed = facts_on["armed"]
            g_sink: dict[str, Any] = {}
            export_vgl = prepare_export(args.fixture, args.original_index, "visible-vgl")
            vgl = run_visible_pass(
                "Vgl", export_vgl, load_slides(export_vgl), plan_on, viewport, expected_stage, evidence_dir,
                vgl_expectations, burst_poke=args.burst_poke, gl_replay="auto",
                rescore=occlusion_rescorer(armed), after_slide=handback_hook(armed, g_sink, expect_handoff=True),
            )
            write_handback_shot(evidence_dir, "Vgl", g_sink)
            vgl["handback"] = g_sink.get("record")
            vgl["armedSlide"] = score_vgl_armed_slide(vgl, armed)
            result["visible"]["Vgl"] = vgl
            result["handback"] = score_handback(
                v_sink.get("record"), v_sink.get("frame"), g_sink.get("record"), g_sink.get("frame"), armed,
                poke=args.burst_poke,
            )
            result["latency"] = handback_latency(g_sink.get("record"))
            result["leftoverChromeAfterVisibleGl"] = check_no_leftover_chrome()
            save()

        export_attach = prepare_export(args.fixture, args.original_index, "attach")
        result["attach"] = run_attach_arm(
            export_attach, load_slides(export_attach), facts, artifact.parent, attach_expected_stage,
            gl_replay=args.gl_replay, facts_on=facts_on,
        )
        result["leftoverChromeAfterAttach"] = check_no_leftover_chrome()
        save()

        result["status"], result["statusReasons"] = overall_status(result)
    except Exception as exc:  # noqa: BLE001 - always leave a readable artifact behind
        result["status"] = "error"
        result["error"] = str(exc)
    finally:
        save()

    verdict_keys = ("continue1to2", "restart2to3", "continue3to4") + tuple(
        REFUSAL_VERDICT_KEY[key] for key in refused_boundaries(result)
    ) + (tuple(ARMED_VERDICT_KEY.values()) if auto else ())
    summary = {
        "status": result.get("status"),
        "statusReasons": result.get("statusReasons"),
        "arms": {
            name: {key: boundary_verdict(entry, key) for key in verdict_keys}
            for name, entry in result.get("arms", {}).items()
        },
        "attach": {key: boundary_verdict(result.get("attach", {}), key) for key in verdict_keys},
        "visible": {
            name: {
                "verdict": entry.get("verdict"),
                "slides": [slide.get("verdict") for slide in visible_slides_of(entry)],
            }
            for name, entry in (result.get("visible") or {}).items()
        },
    }
    if auto:
        summary["handback"] = (result.get("handback") or {}).get("verdict")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
