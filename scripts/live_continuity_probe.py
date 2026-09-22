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
from obed_edom.html_preview import cache_dir  # noqa: E402
from obed_edom.live_continuity import ContinuityPlan, Unsupported, derive_plan  # noqa: E402
from obed_edom.html_alpha_probe import (  # noqa: E402
    INPAGE_MIN_SAMPLES,
    combine_oracle_verdicts,
    inpage_mask_is_usable,
    occluder_mask_from_markers,
    score_inpage_liveness,
)
from obed_edom.live_host import ATTACH_ENV, CONTINUITY_ENV, LiveOutputHost, OutputDisplay, PlayerCommandRejected  # noqa: E402
from obed_edom.p2_verdict import BURST_OFFSETS_MS, CONTROL_INSET_PX, CONTROL_PATCH_PX  # noqa: E402

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
    return parser.parse_args(argv)


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


def ground_truth_plan(export_root: Path, slides: list[dict[str, Any]]) -> ContinuityPlan:
    plan = derive_plan(export_root, slides)
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
            else:
                per_asset[asset] = LIVE if continuity_on else DEAD
        expectations[player_index] = per_asset
    return expectations


def visible_expectations(plan: ContinuityPlan, runtime: dict[str, Any]) -> dict[str, dict[int, dict[str, str]]]:
    return {
        "V": rect_expectations(plan, runtime, continuity_on=True),
        "Voff": rect_expectations(plan, runtime, continuity_on=False),
    }


def ground_truth_facts(plan: ContinuityPlan) -> dict[str, Any]:
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
    retire = retire_fact(plan, runtime, {
        facts["onset1to2"]: "continue1to2",
        facts["restartScene"]: "restart2to3",
        facts["bridgeScene"]: "continue3to4",
    })
    facts["retire"] = retire
    facts["refusedBoundaries"] = [retire["boundaryKey"]] if retire else []
    facts["refusals"] = [dict(item) for item in getattr(plan, "refusals", ()) if isinstance(item, dict)]
    facts["rectExpectations"] = visible_expectations(plan, runtime)
    return facts


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
    viewport: tuple[int, int], expected_stage: dict[str, float],
) -> dict[str, Any]:
    force_viewport(*viewport)
    player = LiveOutputHost(export_root, slides, headless=True)
    result: dict[str, Any] = {"arm": name}
    try:
        player.start()
        result["continuity"] = player.output["continuity"]
        evidence: dict[str, Any] = {}
        raw_samples = drive_and_sample(player, observer=refusal_observer(player, facts, evidence))
        samples, invalid_count = convert_samples_to_authored(raw_samples)
        result["samples"] = samples
        result["sampleCount"] = len(samples)
        result["stageMapInvalidCount"] = invalid_count
        result["stageMap"] = stage_map_summary(samples)
        result["stageFit"] = score_stage_fit(samples, expected_stage)
        runtime_installed = result["continuity"].get("mode") == "qualified"
        result.update(score_boundaries(samples, facts, runtime_installed))
        result.update(score_refusals(evidence, facts, runtime_installed))
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
    expected_stage: dict[str, float],
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
            player = LiveOutputHost(export_root, slides, headless=True)
            try:
                player.start()
                output = player.output
                result["continuity"] = output["continuity"]
                result["output"] = {key: value for key, value in output.items() if key != "continuity"}
                transport = player._require_transport()
                plan_transparent = transport.evaluate(
                    "!!(window.__OBED_CONTINUITY__ && window.__OBED_CONTINUITY__.transparentBackground)"
                )
                computed_background = transport.evaluate("getComputedStyle(document.documentElement).backgroundColor")
                result["transparentBackground"] = {"plan": bool(plan_transparent), "computedBackground": computed_background}
                evidence: dict[str, Any] = {}
                raw_samples = drive_and_sample(player, observer=refusal_observer(player, facts, evidence))
                samples, invalid_count = convert_samples_to_authored(raw_samples)
                result["samples"] = samples
                result["sampleCount"] = len(samples)
                result["stageMapInvalidCount"] = invalid_count
                result["stageMap"] = stage_map_summary(samples)
                result["stageFit"] = score_stage_fit(samples, expected_stage)
                runtime_installed = result["continuity"].get("mode") == "qualified"
                result.update(score_boundaries(samples, facts, runtime_installed))
                result.update(score_refusals(evidence, facts, runtime_installed))
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
    """`None` only when the handle itself is absent (Codex r2 Spec 3): every
    other case -- malformed, mismatched identity, a stale/replaced handle --
    is an APPLICABLE inconclusive result, never n/a."""
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
            expectations=expectations, offsets_ms=offsets_ms, poke=poke, now=now, sleep=sleep,
        ))
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
    expectations: dict[int, dict[str, str]] | None = None, burst_poke: bool = False,
) -> dict[str, Any]:
    """One visible-content pass in its own host session, scored against the plan's
    own per-rect expectations for this mode. No `SAMPLER_JS`: the burst's captures
    would perturb the rAF sampler's clock, which is why this is a separate pass and
    not an arm."""
    force_viewport(*viewport)
    result: dict[str, Any] = {"pass": name, "status": "ok", "viewport": {"width": viewport[0], "height": viewport[1]}}
    player = LiveOutputHost(export_root, slides, headless=True)
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
    all_gated = [
        boundary_verdict(a, "continue1to2"), boundary_verdict(a, "restart2to3"), boundary_verdict(a, "continue3to4"),
        boundary_verdict(b, "continue3to4"),
        boundary_verdict(c, "continue1to2"), boundary_verdict(c, "continue3to4"),
        boundary_verdict(attach, "continue1to2"), boundary_verdict(attach, "restart2to3"), boundary_verdict(attach, "continue3to4"),
    ]
    if any(v is None for v in all_gated):
        return "inconclusive", ["at least one gated boundary verdict is inconclusive (movie never decoded)"]

    reasons: list[str] = []
    refused = refused_boundaries(result)

    a_mode, b_mode, c_mode, attach_mode = continuity_mode(a), continuity_mode(b), continuity_mode(c), continuity_mode(attach)
    a_boundary_reasons = boundary_expectation_reasons(a, "arm A", "continue1to2", refused)
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

    c_boundary_reasons = boundary_expectation_reasons(c, "arm C", "continue1to2", refused)
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

    ok = a_ok and b_ok and c_ok and attach_ok and not visible
    if not ok and not reasons:
        reasons.append("a boundary verdict did not match the expected pattern for its arm")
    return ("pass" if ok else "fail"), reasons


def main() -> None:
    args = parse_args()
    if not args.fixture.is_dir():
        raise SystemExit(f"fixture is unavailable: {args.fixture}")
    if not args.original_index.is_file():
        raise SystemExit(f"original index is unavailable: {args.original_index}")
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
        save()

        result["arms"] = {}
        result["arms"]["A"] = run_arm("A", export_a, slides_a, facts, viewport, expected_stage)
        save()

        export_b = prepare_export(args.fixture, args.original_index, "arm-b")
        with env_override({CONTINUITY_ENV: "off"}):
            result["arms"]["B"] = run_arm("B", export_b, load_slides(export_b), facts, viewport, expected_stage)
        save()

        export_c = prepare_export(args.fixture, args.original_index, "arm-c")
        with bridge_disabled():
            result["arms"]["C"] = run_arm("C", export_c, load_slides(export_c), facts, viewport, expected_stage)
        save()

        result["leftoverChromeAfterArms"] = check_no_leftover_chrome()
        save()

        evidence_dir = artifact.parent / "visible"
        export_v = prepare_export(args.fixture, args.original_index, "visible-v")
        result["visible"] = {}
        result["visible"]["V"] = run_visible_pass(
            "V", export_v, load_slides(export_v), plan, viewport, expected_stage, evidence_dir,
            facts["rectExpectations"]["V"], burst_poke=args.burst_poke,
        )
        result["leftoverChromeAfterVisibleV"] = check_no_leftover_chrome()
        save()

        export_voff = prepare_export(args.fixture, args.original_index, "visible-voff")
        with env_override({CONTINUITY_ENV: "off"}):
            result["visible"]["Voff"] = run_visible_pass(
                "Voff", export_voff, load_slides(export_voff), plan, viewport, expected_stage, evidence_dir,
                facts["rectExpectations"]["Voff"], burst_poke=args.burst_poke,
            )
        result["leftoverChromeAfterVisible"] = check_no_leftover_chrome()
        save()

        export_attach = prepare_export(args.fixture, args.original_index, "attach")
        result["attach"] = run_attach_arm(export_attach, load_slides(export_attach), facts, artifact.parent, attach_expected_stage)
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
    )
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
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
