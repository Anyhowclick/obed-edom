#!/usr/bin/env python3
"""HTML adversarial gate on owner-edited Minimal Alpha_DSK (4 slides).

Proves, with --preserve + PDF bg-strip:
  - empty canvas stays transparent
  - authored opaque black (white-bordered) survives strip
  - green panel keeps partial alpha (~75/255 authored opacity, not colour-keyed)
  - 1→2 Magic Move: the carry is REFUSED (slide 2 draws artwork over the movie),
    so slide 2 must look exactly like the raw export
  - 2→3: movies deliberately RESTART (must not be stitched by preserve)
  - 3→4 moving Magic Move: the bridged movie CONTINUES and paints

P3 stays off. Never writes owner source decks.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import shutil
import socket
import sys
import threading
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from p2_alpha_spike import CHROME, ChromeCdp, _wait_ready  # noqa: E402
from p2_recovery_html_dissolve_live import (  # noqa: E402
    MOVIE1_TOKEN,
    MOVIE2_TOKEN,
    _ensure_videos_playing,
    _media_snapshot,
    _movie_key,
    _norm_hash,
    _replace_hevc_movies,
    _wait_hash_clean,
    inject_continuity_plan,
    inject_preserve,
)
from obed_edom.dsk_live import keynote_running  # noqa: E402
from obed_edom.html_alpha_probe import (  # noqa: E402
    analyze_rgba,
    file_identity,
    footprint_at,
    index_patch_roi_for,
    inventory_deck,
    score_composited_index_run,
    score_index_progression,
    score_motion_across_flip,
    score_playback_continuity,
    score_restart_at_slide_boundary,
    score_restart_movie_from_observations,
    score_visible_movie_motion,
    score_visible_slide,
    strip_export_pdf_bg_fills,
    write_json,
    write_patched_export,
)
from obed_edom.html_preview import export_html  # noqa: E402
from live_continuity_probe import (  # noqa: E402
    BURST_OFFSETS_MS,
    CONTROL_INSET_PX,
    CONTROL_PATCH_PX,
)

SOURCE = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Minimal Alpha_DSK.key")
OUT = REPO / "output" / "p2-recovery" / "html-adversarial"
CLICK_DELAY_S = 1.5
TRANS_S = 1.5
DENSE_FPS = 20
POST_SETTLE_S = 0.6

# Slide shape ROIs from inventory (1920×1080). Inset past white border.
# Slide-1 (pre) positions on the owner-revised deck (measured): black sentinel canvas
# ~[975,722,266,236], green square ~[636,723,178,157]; both sampled ABOVE the movie top
# (~791) so black reads opaque and green reads its authored partial alpha (translucent).
BLACK_ROI_S1 = (1010, 740, 180, 45)
BLACK_ROI_S2 = (545 + 20, 724 + 20, 174 - 40, 154 - 40)
GREEN_ROI_S1 = (660, 735, 150, 45)
# Owner-authored z-order (front->back): green square -> larger movie -> black square
# -> smaller movie. So relative to the LARGER movie the green square is IN FRONT and
# the black sentinel is BEHIND. Black sentinel canvas ~[542,721,181,161], larger movie
# ~[105,791,960,276], green square ~[789,673,353,313] (measured on the exported deck).
# The script's one "this ROI is opaque black" level: `_score_black` calls a patch
# black at rgbMean <= this, and blackBehind calls the movie visible above it.
BLACK_RGB_MEAN_MAX = 40.0
BLACK_ABOVE_ROI = (560, 730, 140, 50)    # black sentinel above the movie -> opaque black present
BLACK_BEHIND_ROI = (560, 800, 140, 70)   # black sentinel ∩ movie -> the MOVIE must show (black behind)
GREEN_FRONT_ROI = (820, 810, 160, 120)   # green square ∩ movie -> translucent green IN FRONT
EMPTY_CORNERS = ((1864, 8, 48, 48), (1864, 1024, 48, 48))  # right side stays emptier after MM
# Large continuing movie footprint on slide 1 (inventory). Center is unobscured.
MOVIE_ROI = (109, 795, 952, 268)
# Second movie (WA0125) footprint on slide 1/2 — feeds the continuity plan's
# movie2 entry. Probe-side ONLY (the leftover-overlay census): naming it in the
# injected continuity plan is what let the runtime pool and remount it.
MOVIE2_ROI = (109, 500, 663, 186)
# The disposable movie's frame-index stimulus patch occupies the top-left
# 120x48 of its 1920x540 source; map it to screen space via the movie's own
# footprint fraction (see _write_h264_pattern in p2_recovery_html_dissolve_live.py).
# Inset well inside the ~60x24 on-screen patch: the full mapped size spills past
# the patch's bottom-right edge into the high-contrast grating (std explodes ->
# the neutrality gate rejects it). A shrunk inner ROI stays flat (std ~0).
INDEX_PATCH_ROI = (
    MOVIE_ROI[0] + 2,
    MOVIE_ROI[1],
    max(1, round(MOVIE_ROI[2] * 120 / 1920) - 18),
    max(1, round(MOVIE_ROI[3] * 48 / 540) - 10),
)
# On slide 3 the restarted movie renders at a DIFFERENT screen rect (~x232,
# shifted right of the slide-2 footprint) and slightly smaller, so INDEX_PATCH_ROI
# above reads the black margin. This is the slide-3 movie's index patch, measured
# empirically from the restart frames (largest flat-neutral region that decodes
# the counter across the window). A wrong ROI decodes to non-flat pixels -> None
# -> score_index_progression fails closed on min_decodable, never a false pass.
INDEX_PATCH_ROI_SLIDE3 = (233, 800, 24, 12)
# HTML event index where slide 2 begins (the 1→2 Magic Move destination, whose
# carry the derived plan REFUSES: slide 2 draws the green square over the movie).
SLIDE2_MIN_HASH = 2
# The player holds `#1` for the WHOLE 1->2 Magic Move and only flips to `#2`
# after the move, yet it detaches the slide-1 videos at `#1` — so the retire zone
# starts one scene early (same convention as the bridge's move scene) and a
# remount during the transition is exactly the defect this gate must catch.
RETIRE_ZONE_MIN_HASH = SLIDE2_MIN_HASH - 1
# HTML event index where slide 3 begins (2 + 4 events before it → scene #6).
SLIDE3_MIN_HASH = 6
# ---- 3->4 moving Magic Move constants (positive control; measured Phase 0) ----
# Slide 4's first scene (the 3->4 magic-move destination). Scene map:
# s1=#1, s2≈#2-5, s3=#6-7, 3->4 MM lands slide 4 at #8, settles #8/#9.
SLIDE4_MIN_HASH = 8
# movie1 (untitled.mov) on-screen footprint at the slide-3 endpoint (SOURCE) and
# the slide-4 endpoint (DEST) — empirically measured, matching the authored
# translate+scale ((195.5,794.6)960x276 -> (324.3,706.0)1274x364).
SLIDE3_MOVIE_RECT = (198, 795, 952, 268)
SLIDE4_MOVIE_RECT = (327, 709, 1266, 356)
# Noise-floor control patch for the settled-slide-4 visible-content burst: a
# CONTROL_PATCH_PX square inset into the first empty corner, sized/inset by the
# probe's own constants so both instruments read the same floor.
SLIDE4_CONTROL_RECT = {
    "x": EMPTY_CORNERS[0][0] + CONTROL_INSET_PX,
    "y": EMPTY_CORNERS[0][1] + CONTROL_INSET_PX,
    "w": CONTROL_PATCH_PX,
    "h": CONTROL_PATCH_PX,
}
# PRESERVE assetKey for untitled.mov (movie1) — used to key the 3->4 footprint
# owner query so the retiring right-side WA0125 the grown box overlaps is excluded.
MOVIE1_KEY = "movie1"
# Fixed expected movie keys for restart evidence (not derived from observations).
# untitled.mov (movie1, Shibuya crossing) is the restart target; after the
# case-insensitive _movie_key fix, both its DOM src and pooled assetKey
# observations collapse under "movie1".
EXPECTED_MOVIE_KEYS = ("movie1",)
# Wall-clock gap required between slide-3 samples to claim progression.
PROGRESSION_WALL_S = 0.25
PROGRESSION_MEDIA_S = 0.20
# Operator-wait acceptance profiles: click delay, pre-advance straddle capture,
# and post-MM settle before draining slide-2 builds. "fast" is prior behaviour.
WAIT_PROFILES = {
    "fast": {"clickDelayS": CLICK_DELAY_S, "preAdvanceFrames": 4, "preAdvanceGapS": 0.05, "postMmSettleS": 0.4},
    "slow": {"clickDelayS": 3.5, "preAdvanceFrames": 10, "preAdvanceGapS": 0.2, "postMmSettleS": 1.5},
}

# Preserve notes that mean a movie was actually carried (pooled decoder reused,
# placed or swapped back in) — the notes a retire zone must never produce.
CARRY_EVENT_KINDS = frozenset({
    "remount-scheduled",
    "remount-done",
    "remount-authored-parent",
    "remount-into-authored-layer",
    "remount-footprint-rect",
    "reuse-decoder",
    "dom-swap",
    "facade-block-clear",
})

# Carry-note census for the retire zone, counted in the page: the target's
# elements are resolved and the window applied BEFORE the sample is sliced, so
# `total` is authoritative however many routine notes other movies produced.
CARRY_CENSUS_JS = r"""(() => {
  const p = window.__OBED_P2_PRESERVE__;
  if (!p || !p.events) return null;
  const KEY = '__KEY__';
  const TOKEN = '__TOKEN__';
  const KINDS = __CARRY_KINDS__;
  const LO = __ZONE_LO__;
  const HI = __ZONE_HI__;
  function mineByKey(e) {
    const k = String((e.detail && e.detail.key) || '').toLowerCase();
    return k === KEY || (!!k && k.indexOf(TOKEN) >= 0);
  }
  const ids = {};
  p.events.forEach((e) => {
    if (!mineByKey(e)) return;
    const d = e.detail || {};
    [d.elId, d.newElId].forEach((i) => { if (i !== undefined && i !== null) ids[String(i)] = 1; });
    (d.elIds || []).forEach((i) => { ids[String(i)] = 1; });
  });
  const hits = p.events.filter((e) => {
    if (KINDS.indexOf(e.kind) < 0) return false;
    const d = e.detail || {};
    const mine = mineByKey(e) || ids[String(d.elId)] === 1 || ids[String(d.newElId)] === 1;
    if (!mine) return false;
    const m = /^#(\d+)/.exec(String(d.sceneHash || ''));
    const n = m ? parseInt(m[1], 10) : -1;
    return n >= LO && n < HI;
  });
  return {
    key: KEY,
    total: hits.length,
    sample: hits.slice(0, 20),
    loScene: LO,
    hiScene: HI,
    eventsSeen: p.events.length
  };
})()""".replace(
    "__CARRY_KINDS__", json.dumps(sorted(CARRY_EVENT_KINDS))
).replace("__KEY__", MOVIE1_KEY).replace(
    "__TOKEN__", MOVIE1_TOKEN.lower()
).replace("__ZONE_LO__", str(RETIRE_ZONE_MIN_HASH)).replace(
    "__ZONE_HI__", str(SLIDE3_MIN_HASH)
)

# Pool census on settled slide 2: `snapshot()` lists every pooled decoder AND
# every `data-obed-preserved` element still in the DOM, so "nothing was ever
# pooled" can be read off the real pool instead of inferred from silence.
POOL_CENSUS_JS = """(() => {
  const p = window.__OBED_P2_PRESERVE__;
  if (!p || !p.snapshot) return null;
  return {entries: p.snapshot(), sceneHash: String(location.hash || '')};
})()"""

# Leftover-overlay query over the slide-1/2 movie footprints. `count` is OUR
# remount overlays only (a fresh authored movie legitimately (re)starting in the
# same footprint is unmarked and must not be flagged); `paintingCount` is every
# <video> that actually paints there — on a WebGL-composited slide the player's
# own layer tree sits at opacity 0, so an opacity-blind test would flag it.
LINGERING_MOVIE_OVERLAYS_JS = """(() => {
  const footprints = [
    {x: 109, y: 795, w: 952, h: 268},
    {x: 109, y: 500, w: 663, h: 186}
  ];
  function overlaps(r, fp) {
    const ix = Math.max(0, Math.min(r.left + r.width, fp.x + fp.w) - Math.max(r.left, fp.x));
    const iy = Math.max(0, Math.min(r.top + r.height, fp.y + fp.h) - Math.max(r.top, fp.y));
    const inter = ix * iy;
    const minArea = Math.min(r.width * r.height, fp.w * fp.h);
    return minArea > 0 && inter > 0.25 * minArea;
  }
  function boxed(v) {
    if (!document.contains(v)) return null;
    const st = getComputedStyle(v);
    if (st.visibility === 'hidden' || st.display === 'none') return null;
    const r = v.getBoundingClientRect();
    if (!(r.width > 1 && r.height > 1)) return null;
    return footprints.some((fp) => overlaps(r, fp)) ? r : null;
  }
  function opacityProduct(el) {
    let p = 1;
    let n = el;
    while (n && n.nodeType === 1) {
      const o = parseFloat(getComputedStyle(n).opacity);
      if (!isNaN(o)) p *= o;
      n = n.parentElement;
    }
    return p;
  }
  const vids = Array.prototype.slice.call(
    document.querySelectorAll('video[data-obed-remounted="1"]')
  );
  const lingering = vids.filter((v) => boxed(v));
  const all = Array.prototype.slice.call(document.querySelectorAll('video'));
  const painting = all.filter((v) => {
    if (!boxed(v)) return false;
    if (v.checkVisibility && !v.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) return false;
    return opacityProduct(v) > 0.02;
  });
  return {
    count: lingering.length,
    elIds: lingering.map((v) => v.__obedElId || null),
    preservedCount: lingering.filter(
      (v) => v.dataset && v.dataset.obedPreserved === '1'
    ).length,
    paintingCount: painting.length,
    paintingElIds: painting.map((v) => v.__obedElId || null)
  };
})()"""

# --- Phase 2: composited-freeze negative control (Arm A) thresholds ---------- #
# The freeze control proves the COUNTER gate (`score_composited_index_run`) is not
# vacuous: it injects a persistent VISIBLE stale cover over the burnt-in counter so
# `index_run` goes RED ("freeze run at cut") while the live-<video> decoder + rVFC
# stay green. A strong margin (not just >max_freeze_run==2) is required so the RED is
# unmistakably the injected freeze, not coarse-capture jitter.
FREEZE_MIN_RUN = 6            # freezeRunAtCut must reach this (margin over the gate's 2)
FREEZE_MIN_AFTER = 6         # samples after the flip (n - flip_index) needed to form the run
RVFC_MIN_ADVANCE_S = 0.5    # the decoder must run >=0.5s through the hold (0.05 is too weak)
MAX_RAF_GAP_MS = 100.0      # a per-rAF hold-log gap beyond this => INCONCLUSIVE, not a verdict
STALE_INDEX_TOL = 2         # +/- yuv rounding on the decoded frozen counter
COVER_MATCH_TOL = 6.0       # frozen decode mean must match the cover's painted patch mean
MIN_STALE_TIME_S = 0.3      # the stale frame must be from genuine playback (not a t=0 unrendered black)
HOLD_HASHCHANGE_TOL_MS = 50.0  # holdStartedAt must be within this of the hashchange event (1->2, retired)
COVER_LEFT_FRAC = 0.4       # mirrors NULL_CONTROL_JS's LEFT_FRAC (subRect) -- keep in sync
COVER_TRACK_TOL_PX = 2.0    # cover rect vs measured*COVER_LEFT_FRAC tolerance (plan p2_freeze_control_3to4 §4)
STAGE_ORIGIN_TOL_PX = 0.5   # stageOrigin must read (0,0) at arm (plan §2, cover geometry)
FOOTPRINT_COUPLE_TOL_PX = 1.5  # before/after owner-rect agreement for a screenshot to count
                                # "measured" rather than "unstable" (review Blocker 2b)
# TRANS_S (1.5s) mirrors the moving MM's own export duration (boundary.durationSeconds,
# consumed by keepThroughBridge -- src/obed_edom/live_continuity_js.py ~L677). A trigger
# firing within the first quarter of that duration is unambiguously "at move start", not
# a late fire the scorer would otherwise accept as if it were (review MAJOR 5 / plan §2).
MOVE_START_WINDOW_FRAC = 0.25
MOVE_START_WINDOW_S = TRANS_S * MOVE_START_WINDOW_FRAC

# The Arm-A composited-freeze control, injected into the live page BEFORE the 3->4
# advance. `window.__OBED_NULL_CTRL__` = {arm(rect, hash1), status(), release()}.
# Re-bracketed at the 3->4 moving Magic Move (the 1->2 carry is refused, so there is
# no carried movie to freeze there -- see the plan). Single mode now (no fork): the
# 1->2 arm/trigger is not used by any other caller, so this replaces it rather than
# adding a second code path.
#   - arm(): resolve the footprint owner (footprintOwnerDecoderId) at the PRE-move
#     (slide-3) rect, record the armed hash + the stage origin (the partial cover is
#     `position:fixed` viewport px while the moving <video> is stage-absolute px --
#     they only coincide while the stage origin is (0,0)), and start a single per-rAF
#     poll for EITHER the runtime's own move signal (`__obedMotion`, set by
#     `keepThroughBridge` on the bridged <video> the instant it starts translating)
#     or, as a fallback, the `#7`->`#8` hash flip (the player never fires `hashchange`
#     during the move; the hash only flips ~2s later, after the move ends).
#   - trigger(via): 'motion' | 'hash' (recorded as `firedVia` -- a hash-only fire means
#     the move is already over and the cover tracked nothing, an INCONCLUSIVE-only
#     signal for the scorer). Capture the owner <video>'s CURRENT frame synchronously
#     into an ID-LESS scratch canvas (so the player's drawImage recorder, which only
#     records draws into a canvas WITH an id, stays inert), then paint the left-fraction
#     sub-region ONCE onto an ID-LESS fixed top-z opaque cover canvas.
#   - hold: per-rAF re-resolve the owner by elId, re-measure its LIVE rect (never the
#     modelled/interpolated one), retrack the cover's left-fraction sub-rect onto it,
#     re-append if detached, and log the cover rect + the measured rect (so the scorer
#     can compute `coverTracksFootprint` within 2px) plus whether the counter patch
#     center hit-tests to the cover. The cover is PARTIAL (left ~40% of the owner rect)
#     so it covers the counter patch but not the slide-1/2 composition ROIs.
#   - release(): remove the cover, stop the loop, snapshot the frozen-patch checksum and
#     wall time (`coverPatchEnd`). Capture is AT THE TRIGGER (never at arm()): an early
#     capture makes the first in-hold decode step BACKWARD -> a wrong-reason negative
#     anomaly. The caller releases BETWEEN the last at-cut capture and the settled-
#     slide-4 visible-content burst (a cover left in place would red `footprintFullyLive`
#     for the wrong reason).
NULL_CONTROL_JS = r"""
(function () {
  if (window.__OBED_NULL_CTRL__) return;
  var P = window.__OBED_P2_PRESERVE__;
  var dpr = window.devicePixelRatio || 1;
  var LEFT_FRAC = 0.4;

  var st = {
    arm: 'A',
    status: 'idle',
    armedHash: null,
    armedRect: null,
    armedElId: null,
    armedOwnerRect: null,
    armedAt: null,
    stageOrigin: null,
    boundDecoderId: null,
    fellBackToArmOwner: false,
    ownerDisconnectedInWindow: false,
    firedVia: null,
    movedFromRect: null,
    movedToRect: null,
    obedMotionAtTrigger: null,
    holdStartedAt: null,
    releaseAt: null,
    staleCurrentTime: null,
    staleIndexExpected: null,
    paintCount: 0,
    coverPatchStart: null,
    coverPatchEnd: null,
    coverPatchMean: null,
    ownerReadyState: null,
    ownerAmbiguousInWindow: false,
    holdFrames: 0,
    rafLog: [],
    error: null
  };
  var cover = null;
  var scratch = null;
  var rafId = null;
  var retryStartedAt = null;
  var triggerDeadline = null;

  // Local footprint shim: the CURRENT footprint rect. On 1->2 the footprint is
  // static (MOVIE_ROI == armedRect); when the owner <video> is resolved we prefer
  // its LIVE getBoundingClientRect. This is the single seam for the 3->4 moving
  // footprint (where footprint_at()/index_patch_roi_for() would map it) — a drop-in.
  function footprintNow(ownerEl) {
    if (ownerEl) {
      var r = ownerEl.getBoundingClientRect();
      if (r.width > 1 && r.height > 1) return {x: r.left, y: r.top, w: r.width, h: r.height};
    }
    return st.armedRect;
  }

  function elById(elId) {
    if (elId == null) return null;
    var vids = document.querySelectorAll('video');
    for (var i = 0; i < vids.length; i++) {
      if (vids[i].__obedElId === elId) return vids[i];
    }
    return null;
  }

  // Two-tier: ONCE bound (trigger has resolved a decoder), the footprint owner is
  // the SAME <video> element for the rest of the hold -- keepThroughBridge moves it
  // by repositioning the node in place, never replacing it -- so tracking is by
  // elId, never by re-deriving ownership from a rect that is now stale (the video
  // has translated+scaled away from the armed/pre-move rect). Before binding
  // (arm() and the first trigger check), fall back to the IoU-based resolver at the
  // armed (pre-move) rect, which is still valid then.
  function resolveOwnerEl() {
    if (st.boundDecoderId != null) {
      var bound = elById(st.boundDecoderId);
      if (bound) return bound;
      // Once bound, the owner must stay THAT element for the rest of the hold
      // (keepThroughBridge moves it in place, never replaces it) -- losing it
      // is a disconnect, not a cue to re-derive a different owner.
      st.ownerDisconnectedInWindow = true;
      return null;
    }
    var elId = null;
    try {
      var res = (P && P.footprintOwnerDecoderId) ? P.footprintOwnerDecoderId(st.armedRect) : null;
      if (res) {
        if (res.via === 'ambiguous') st.ownerAmbiguousInWindow = true;
        if (res.elId != null) elId = res.elId;
      }
    } catch (e) {
      // Record, never swallow: a resolver exception must fail the hold closed
      // (noControlError), not silently fall back to the armed owner.
      st.error = st.error || ('resolver:' + String(e && e.message || e));
    }
    if (elId == null) { st.fellBackToArmOwner = true; elId = st.armedElId; }
    var el = elById(elId);
    if (el) st.boundDecoderId = elId;
    return el;
  }

  function subRect(fp) { return {x: fp.x, y: fp.y, w: fp.w * LEFT_FRAC, h: fp.h}; }

  function counterPatchPixels() {
    if (!cover) return null;
    try {
      var ctx = cover.getContext('2d', {alpha: false});
      var w = Math.min(cover.width, 60), h = Math.min(cover.height, 24);
      var d = ctx.getImageData(0, 0, w, h).data;
      var s = 0, n = 0;
      for (var i = 0; i < d.length; i += 4) { s = (s + d[i] + d[i + 1] + d[i + 2]) % 2147483647; n += 3; }
      return {sum: s, w: w, h: h, mean: n ? s / n : null};
    } catch (e) { return {error: String(e && e.message || e)}; }
  }

  function paintCover() {
    if (!cover || !scratch) return;
    try {
      var ctx = cover.getContext('2d', {alpha: false});
      // canvas -> canvas (source is a <canvas>, not a <video>) so the player's
      // drawImage recorder is inert. Paint the left-fraction sub-region.
      var sw = Math.max(1, Math.round(scratch.width * LEFT_FRAC));
      ctx.drawImage(scratch, 0, 0, sw, scratch.height, 0, 0, cover.width, cover.height);
      st.paintCount += 1;
    } catch (e) { st.error = 'paint:' + String(e && e.message || e); }
  }

  function patchCenter(fp) {
    // Center of the burnt-in counter patch (top-left of the footprint), in CSS px.
    return {x: fp.x + Math.min(fp.w * LEFT_FRAC * 0.5, 22), y: fp.y + 8};
  }

  function trigger(via) {
    if (st.status !== 'armed') return;
    st.status = 'holding';
    st.firedVia = via;
    st.holdStartedAt = performance.now();
    // At the 1->2 flip the movie is briefly mid-remount (PRESERVE detaches/reattaches
    // the <video>), so the footprint owner can be transiently null AT the trigger
    // instant. Retry owner resolution for <=150ms before capturing the stale frame —
    // capturing against a null/unready owner paints BLACK (a wrong-reason freeze).
    triggerDeadline = st.holdStartedAt + 150;
    beginHold();
  }

  function beginHold() {
    if (st.status !== 'holding') return;
    var ownerEl = resolveOwnerEl();
    var probe = ownerEl ? (ownerEl.__obedFacadeFor || ownerEl) : null;
    var ready = !!(probe && probe.readyState >= 2 && probe.videoWidth > 0);
    if (!ready && performance.now() < triggerDeadline) {
      retryStartedAt = retryStartedAt || st.holdStartedAt;
      requestAnimationFrame(beginHold);
      return;
    }
    var real = probe;
    var fp = footprintNow(ownerEl);

    st.ownerReadyState = real ? (real.readyState || 0) : null;
    scratch = document.createElement('canvas');  // ID-LESS: recorder stays inert
    scratch.width = Math.max(1, Math.round(fp.w * dpr));
    scratch.height = Math.max(1, Math.round(fp.h * dpr));
    // readyState>=2 (HAVE_CURRENT_DATA) AND currentTime>=0.3: videoWidth>0 alone does
    // NOT guarantee a DECODED frame, and a video at t~0 draws BLACK (an unrendered first
    // frame), which reads as a frozen counter (index 0) for the wrong reason. The
    // continuing 1->2 movie is always ~1.5s at the flip, so require genuine playback.
    // (Do NOT range-check the drawn luma: getImageData returns full-range RGB while the
    // counter is encoded in tv-range [16,235] luma, so a valid dark/bright counter frame
    // is not black — distinguish unrendered by readiness/time, not pixel bounds.)
    if (real && real.readyState >= 2 && real.videoWidth > 0 && real.currentTime >= 0.3) {
      try {
        scratch.getContext('2d').drawImage(real, 0, 0, scratch.width, scratch.height);
        st.staleCurrentTime = real.currentTime;
        st.staleIndexExpected = 16 + (Math.round(real.currentTime * 30) % 220);
      } catch (e) { st.error = 'scratch-draw:' + String(e && e.message || e); }
    } else {
      st.error = 'owner-video-not-ready-at-trigger:rs=' + (real ? real.readyState : 'none')
        + ',t=' + (real ? real.currentTime : 'none');
    }

    var sr = subRect(fp);
    cover = document.createElement('canvas');  // ID-LESS
    cover.setAttribute('data-obed-null-control', '1');
    cover.width = Math.max(1, Math.round(sr.w * dpr));
    cover.height = Math.max(1, Math.round(sr.h * dpr));
    cover.style.position = 'fixed';
    cover.style.left = sr.x + 'px';
    cover.style.top = sr.y + 'px';
    cover.style.width = sr.w + 'px';
    cover.style.height = sr.h + 'px';
    cover.style.zIndex = '2147483647';
    cover.style.opacity = '1';
    cover.style.filter = 'none';
    cover.style.pointerEvents = 'auto';
    cover.style.margin = '0';
    cover.style.padding = '0';
    document.body.appendChild(cover);

    paintCover();  // ONCE
    st.coverPatchStart = counterPatchPixels();
    st.coverPatchMean = (st.coverPatchStart && st.coverPatchStart.mean != null)
      ? st.coverPatchStart.mean : null;
    // coverPatchMean is a DIAGNOSTIC only (a decoded-RGB mean): it is NOT range-checked,
    // because a valid dark/bright counter frame decodes near 0/255 in RGB. The
    // unrendered-black case is caught by the readiness+currentTime guard above; the
    // scorer's everyInHoldStale then requires the composited decodes to be CONSTANT and
    // to MATCH this cover mean (both RGB) — a genuine same-space comparison.
    loop();
  }

  function loop() {
    if (st.status !== 'holding') return;
    var now = performance.now();
    // Log the ACTUAL DOM rects left by the PREVIOUS frame FIRST, before this
    // frame updates anything -- coverTracksFootprint/coverHitTest100 must compare
    // independently-measured rects, never the same local value twice (review
    // MAJOR 4). The cover was already positioned once in beginHold() before the
    // first loop() call, so frame 0 is not a special case.
    var ownerEl = resolveOwnerEl();
    if (ownerEl) retryStartedAt = null;
    var loggedCoverRect = cover ? rectOf(cover) : null;
    var loggedOwnerRect = rectOf(ownerEl);
    var top = null;
    if (loggedOwnerRect) {
      var pc = patchCenter(loggedOwnerRect);
      top = document.elementFromPoint(pc.x, pc.y);
    }
    st.rafLog.push({
      t: now, elementFromPointIsCover: top === cover, ownerResolved: !!ownerEl,
      coverRect: loggedCoverRect, measuredRect: loggedOwnerRect,
      boundDecoderId: st.boundDecoderId
    });
    st.holdFrames += 1;
    // Now update the cover for THIS frame -- the NEXT loop() call logs it.
    var fp = footprintNow(ownerEl);
    var sr = subRect(fp);
    if (cover) {
      if (!cover.isConnected) document.body.appendChild(cover);  // re-append if detached
      cover.style.left = sr.x + 'px';
      cover.style.top = sr.y + 'px';
      cover.style.width = sr.w + 'px';
      cover.style.height = sr.h + 'px';
    }
    rafId = requestAnimationFrame(loop);
  }

  // `__obedMotion` (set by keepThroughBridge -- src/obed_edom/live_continuity_js.py
  // ~L661) is recorded here for FORENSICS ONLY: keepThroughBridge runs -- and can
  // create/keep the marker -- while merely SETTLED at #7, before any advance
  // click, so the marker's mere existence is not proof the move has started. The
  // real trigger below is a MEASURED departure of the bound owner's own rect from
  // its rect at arm() time.
  function motionInfoOf(el) {
    var m = el && el.__obedMotion;
    if (!m) return null;
    var atScene = (m.boundary && typeof m.boundary.atScene === 'number') ? m.boundary.atScene : null;
    return {started: m.started, generation: m.generation, atScene: atScene};
  }

  function rectOf(el) {
    if (!el) return null;
    var r = el.getBoundingClientRect();
    if (!(r.width > 1 && r.height > 1)) return null;
    return {x: r.left, y: r.top, w: r.width, h: r.height};
  }

  function rectDeparted(a, b) {
    if (!a || !b) return false;
    return Math.abs(a.x - b.x) > 1 || Math.abs(a.y - b.y) > 1
      || Math.abs(a.w - b.w) > 1 || Math.abs(a.h - b.h) > 1;
  }

  function normHash(h) {
    var s = String(h == null ? '' : h);
    var q = s.indexOf('?');
    if (q >= 0) s = s.slice(0, q);
    var m = s.match(/^(#\d+)/);
    return m ? m[1] : s;
  }

  window.__OBED_NULL_CTRL__ = {
    arm: function (rect, hash1) {
      var armedHash = normHash(hash1);
      var curHash = normHash(location.hash);
      if (curHash !== armedHash) {
        return {
          ok: false,
          error: 'hash-mismatch-at-arm:armed=' + armedHash + ',actual=' + curHash
        };
      }
      var ownerEl = resolveOwnerEl();
      if (!ownerEl) {
        return {ok: false, error: 'owner-unresolved-at-arm'};
      }
      var ownerRect = rectOf(ownerEl);
      if (!ownerRect) {
        return {ok: false, error: 'owner-rect-unavailable-at-arm'};
      }
      st.armedRect = rect;
      st.armedHash = armedHash;
      st.armedAt = performance.now();
      var stageEl = document.getElementById('stage');
      var stageR = stageEl ? stageEl.getBoundingClientRect() : null;
      st.stageOrigin = stageR ? {x: stageR.left, y: stageR.top} : {x: null, y: null};
      st.armedElId = ownerEl.__obedElId;
      st.armedOwnerRect = ownerRect;
      st.boundDecoderId = st.armedElId;  // bind NOW -- the same element the whole hold
      st.fellBackToArmOwner = false;
      st.status = 'armed';
      // Single rAF poll for EITHER a MEASURED departure of the bound owner's rect
      // from its armed rect (the real move start) or, as a fallback, the `#7`->`#8`
      // hash flip (the player never fires `hashchange` during the move -- dead on
      // this player -- and the hash only flips ~2s later, after the move ends).
      (function poll() {
        if (st.status !== 'armed') return;
        var el = resolveOwnerEl();
        var r = rectOf(el);
        if (rectDeparted(st.armedOwnerRect, r)) {
          st.movedFromRect = st.armedOwnerRect;
          st.movedToRect = r;
          st.obedMotionAtTrigger = motionInfoOf(el);
          trigger('moved');
          return;
        }
        if (normHash(location.hash) !== st.armedHash) {
          st.obedMotionAtTrigger = motionInfoOf(el);
          trigger('hash');
          return;
        }
        requestAnimationFrame(poll);
      })();
      return {
        ok: true, armedElId: st.armedElId, armedHash: st.armedHash,
        stageOrigin: st.stageOrigin, armedOwnerRect: st.armedOwnerRect
      };
    },
    status: function () {
      return {
        arm: st.arm, status: st.status, armedHash: st.armedHash, armedElId: st.armedElId,
        armedOwnerRect: st.armedOwnerRect,
        movedFromRect: st.movedFromRect, movedToRect: st.movedToRect,
        obedMotionAtTrigger: st.obedMotionAtTrigger,
        stageOrigin: st.stageOrigin,
        boundDecoderId: st.boundDecoderId, fellBackToArmOwner: st.fellBackToArmOwner,
        ownerDisconnectedInWindow: st.ownerDisconnectedInWindow,
        firedVia: st.firedVia,
        holdStartedAt: st.holdStartedAt, releaseAt: st.releaseAt,
        staleCurrentTime: st.staleCurrentTime, staleIndexExpected: st.staleIndexExpected,
        paintCount: st.paintCount, coverPatchStart: st.coverPatchStart,
        coverPatchEnd: st.coverPatchEnd, coverPatchMean: st.coverPatchMean,
        ownerReadyState: st.ownerReadyState,
        ownerAmbiguousInWindow: st.ownerAmbiguousInWindow,
        holdFrames: st.holdFrames, rafLog: st.rafLog, error: st.error
      };
    },
    release: function () {
      if (st.status === 'holding') st.coverPatchEnd = counterPatchPixels();
      st.status = 'released';
      st.releaseAt = performance.now();
      if (rafId != null) { cancelAnimationFrame(rafId); rafId = null; }
      if (cover && cover.parentNode) cover.parentNode.removeChild(cover);
      return this.status();
    }
  };
})();
"""


def _arg_value(name: str, default: str) -> str:
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def _crop(arr: np.ndarray, xywh: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = xywh
    H, W = arr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    return arr[y0:y1, x0:x1]


def _decode_index_patch(arr: np.ndarray, roi: tuple[int, int, int, int] = INDEX_PATCH_ROI) -> int | None:
    """Decode the frame-index stimulus patch off a composite screenshot.

    None if the mapped ROI isn't a flat neutral patch (composite not settled,
    ROI mislocated, or occluded) — never guess a value from noisy pixels.
    """
    patch = _crop(arr, roi)
    if patch.size == 0:
        return None
    rgb = patch[:, :, :3].astype(np.float64)
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    if max(float(r.std()), float(g.std()), float(b.std())) > 8:
        return None
    if max(float(np.abs(r - g).max()), float(np.abs(g - b).max())) > 12:
        return None
    return int(round(float(rgb.mean())))


def _layer_identity(node: dict) -> str | None:
    """Stable identity for an authored layer/object node, used to fold a steady
    texture only into the SAME object that owns the resolved crossfade (Codex
    F5). Size equality is NOT identity: two same-sized movies each own a
    footprint-sized steady, so folding by size would feed movie1 into movie2's
    canvases. Magic Move persists an object's id across the 1->2 pair, so the id
    is the join key. Returns None when the node carries no id — the caller then
    folds no steady rather than guessing.
    """
    for k in ("id", "objectID", "uuid", "layerUUID"):
        v = node.get(k)
        if isinstance(v, (str, int)) and str(v):
            return f"{k}:{v}"
    return None


def _extract_movie_layers(
    events: object,
    footprint_wh: tuple[float, float] | None = None,
    tol: float = 30.0,
) -> tuple[dict[str | None, set[str]], list[dict]]:
    """Walk ONE slide-UUID JSON's `events` tree for the footprint movie's textures.

    Returns `(steady_by_owner, crossfades)` for the layer(s) whose enclosing
    `initialState` w/h matches `footprint_wh` (so a differently-sized OTHER
    movie's layer is excluded; `footprint_wh=None` disables the gate):

      - `steady_by_owner` — `{ownerId | None: {texture, ...}}`: each footprint
        video layer's steady-state `isVideoLayer` texture(s), keyed by the
        owning object's identity (`_layer_identity`). Keeping the owner (not a
        flat set) is what lets `_derive_movie_texids` fold a steady into ONLY the
        object that owns the boundary crossfade (Codex F5). An id-less layer's
        steady lands under `None` and is never folded.
      - `crossfades` — `[{"from", "to", "owner", "withinMagicMove"}, ...]` from
        `property == "contents"` animations with `from != to`: the poster swap's
        outgoing (`from`) and incoming (`to`) textures, tagged with the enclosing
        video layer's identity (`owner`, may be None) and whether an ancestor is
        an `apple:magic-move-*` transition (`withinMagicMove`). A same-texture
        (`from == to`) tween is a background/opacity animation, not a crossfade.

    This function never unions across slides. The caller
    (`_derive_movie_texids`) resolves the single footprint motion-path Magic Move
    `contents` crossfade (a poster swap on the 1->2 or 3->4 motion-path MM — NOT
    the 2->3 boundary, which is an `apple:dissolve`, not a Magic Move) from these
    per-slide pieces and preserves each occurrence's provenance.
    """
    steady_by_owner: dict[str | None, set[str]] = {}
    crossfades: list[dict] = []

    def size_matches(size: tuple[float, float] | None) -> bool:
        if footprint_wh is None:
            return True
        if size is None:
            return False
        return abs(size[0] - footprint_wh[0]) <= tol and abs(size[1] - footprint_wh[1]) <= tol

    def walk(
        o: object,
        layer_size: tuple[float, float] | None,
        owner: str | None,
        in_mm: bool,
    ) -> None:
        if isinstance(o, dict):
            size = layer_size
            init = o.get("initialState")
            if isinstance(init, dict) and isinstance(init.get("width"), (int, float)) and isinstance(
                init.get("height"), (int, float)
            ):
                size = (init["width"], init["height"])
            # A `contents` crossfade is the movie's OWN poster swap only when it
            # sits inside a Magic Move transition (Keynote authors the enclosing
            # layer name `apple:magic-move-*`). The crossfade lives in a separate
            # event subtree from the steady `isVideoLayer`, and this deck's layers
            # carry no id on the video node itself, so this authored transition
            # marker — not layer identity or texture-set membership — is what
            # distinguishes a real poster swap from a same-sized background tween.
            name = o.get("name")
            # Require an AUTHORED Magic Move TRANSITION node: `type == "transition"`
            # AND an `apple:magic-move-*` name — not a loose "magic-move" substring
            # (Codex r2 F2: "not-a-magic-move-caption" must not match) and not a
            # non-transition group that merely bears the name (Codex r3 F2).
            if (
                o.get("type") == "transition"
                and isinstance(name, str)
                and name.lower().startswith("apple:magic-move")
            ):
                in_mm = True
            if o.get("isVideoLayer"):
                owner = _layer_identity(o)
            if o.get("isVideoLayer") and o.get("texture") and size_matches(size):
                steady_by_owner.setdefault(owner, set()).add(o["texture"])
            if o.get("property") == "contents" and size_matches(size):
                frm = (o.get("from") or {}).get("texture")
                to = (o.get("to") or {}).get("texture")
                if frm and to and frm != to:
                    crossfades.append(
                        {"from": frm, "to": to, "owner": owner, "withinMagicMove": in_mm}
                    )
            for v in o.values():
                walk(v, size, owner, in_mm)
        elif isinstance(o, list):
            for v in o:
                walk(v, layer_size, owner, in_mm)

    walk(events, None, None, False)
    return steady_by_owner, crossfades


def _derive_movie_texids(
    player_dir: Path,
    footprint_wh: tuple[float, float] = (MOVIE_ROI[2], MOVIE_ROI[3]),
    decoder_key: str = EXPECTED_MOVIE_KEYS[0],
) -> dict:
    """Resolve the single footprint-movie Magic Move `contents` crossfade and
    emit Contract-1's `{decoderKey, outgoing, incoming}` (see
    `.agents/plans/step1-ownership-contracts.md`).

    CORRECTED MODEL (2026-09-19): Keynote stores a transition under its OUTGOING
    slide (a transition authored on slide N applies N->N+1). The deck's footprint
    Magic Moves are the motion-path MMs at 1->2 and 3->4; the 2->3 boundary is an
    `apple:dissolve` (a movie RESTART, NOT a Magic Move) and owns no `contents`
    poster crossfade. So the single footprint magic-move `contents` poster swap
    this resolves is a MOTION-PATH Magic Move (1->2 or 3->4) — tagged
    `"boundary": "motion-path-mm"`, NOT the earlier (wrong) "2to3". It is
    provenance-only: no gate consumes it. The 1->2 movie is a live `<video>`
    (no canvas feed), so this crossfade is NOT injected for a 1->2 feed anymore;
    `movie-texids.json` is kept for provenance only.

    NOT a whole-deck union (Codex defect #5): the boundary is the ONE
    footprint-sized `contents` crossfade under a Magic Move transition
    (`withinMagicMove`) — the movie's own poster swap; `from` -> `outgoing`,
    `to` -> `incoming`. The crossfade's `from`/`to` are transition posters that
    never appear as slide-1/2 steady textures (empirically true on this deck), so
    steady-texture anchoring cannot match them; the authored `apple:magic-move-*`
    transition marker is what ties the poster swap to the movie when no object
    identity is on the video node. The animation may be stored under any slide's
    JSON, so crossfades are gathered across the deck.

    "Unambiguous" = EXACTLY ONE distinct magic-move footprint crossfade exists
    (Codex F3). There is NO whole-deck "sole footprint-sized crossfade" fallback:
    a same-sized nonmovie `contents` tween on slide 4 is rejected because it is
    NOT inside a Magic Move (and a different-sized movie's crossfade by the size
    gate). Zero such candidates, or more than one, returns
    `{"decoderKey": null, "outgoing": [], "incoming": [], "warning": ...}` —
    NEVER a whole-deck union. Occurrence provenance (slide uuid + count) is
    preserved and EXPOSES a repeat; note the documented residual (contract doc):
    the SAME `(from, to)` pair genuinely occurring at two distinct boundaries is
    still accepted as one (the authored JSON carries no per-boundary tag to tell
    it apart from redundant storage of one boundary). Not present on this deck.

    `outgoing`/`incoming` are exactly the crossfade `from`/`to` posters. No steady
    texture is folded in (Codex r2 F5): a footprint-sized steady cannot be proven
    to belong to THIS movie by size alone, and the magic-move crossfade carries no
    object identity to tie one to it; the runtime player-draw wrapper discovers the
    true canvas<->decoder binding instead.
    """
    header_path = player_dir / "assets" / "header.json"
    try:
        header = json.loads(header_path.read_text())
    except Exception as e:  # noqa: BLE001
        return {"decoderKey": None, "outgoing": [], "incoming": [], "warning": f"header read failed: {e}"}
    slide_list = header.get("slideList") or []
    if len(slide_list) < 2:
        return {
            "decoderKey": None,
            "outgoing": [],
            "incoming": [],
            "warning": f"need >=2 slides to resolve the 1->2 boundary, got {len(slide_list)}",
            "slideList": slide_list,
        }

    occurrences: list[dict] = []  # {from, to, owner, slide} — provenance kept per hit
    scanned: list[str] = []
    for uuid in slide_list:
        path = player_dir / "assets" / uuid / f"{uuid}.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except Exception:  # noqa: BLE001
            continue
        scanned.append(uuid)
        _steady_by_owner, cfs = _extract_movie_layers(
            data.get("events") or [], footprint_wh=footprint_wh
        )
        for cf in cfs:
            occurrences.append({**cf, "slide": uuid})

    # Select the boundary crossfade STRUCTURALLY: a footprint-sized `contents`
    # crossfade under a Magic Move transition (`withinMagicMove`) — the movie's
    # own poster swap. Its `from`/`to` are transition-only poster textures that
    # never appear as slide-1/2 steady state, so steady-texture anchoring cannot
    # match them (and the whole-deck "sole crossfade" fallback that Codex F3
    # flagged was the only thing that used to resolve this). A spurious same-sized
    # *background* `contents` tween is rejected because it is not inside a Magic
    # Move; a differently-sized movie's crossfade is rejected by the footprint
    # size gate. DISTINCT by (from, to); provenance retained.
    movie_cfs: dict[tuple[str, str], list[dict]] = {}
    for occ in occurrences:
        if occ.get("withinMagicMove"):
            movie_cfs.setdefault((occ["from"], occ["to"]), []).append(occ)

    if len(movie_cfs) != 1:
        crossfade_summary = [
            {"from": f, "to": t, "count": len(occs), "slides": sorted({o["slide"] for o in occs})}
            for (f, t), occs in sorted(movie_cfs.items())
        ]
        return {
            "decoderKey": None,
            "outgoing": [],
            "incoming": [],
            "warning": (
                f"1->2 boundary not uniquely resolvable: {len(movie_cfs)} distinct "
                f"magic-move footprint crossfade(s) among {len(occurrences)} occurrence(s)"
            ),
            "scannedSlideUuids": scanned,
            "slideList": slide_list,
            "movieCrossfadeCandidates": crossfade_summary,
        }

    (frm, to), occs = next(iter(movie_cfs.items()))

    # outgoing = the crossfade `from` (pre-cut poster), incoming = `to` (post-cut
    # poster). No steady folding (Codex r2 F5): a footprint-sized steady texture
    # cannot be proven to belong to THIS movie by size, and on the real deck the
    # magic-move crossfade carries no object identity to tie a steady to it. The
    # provable, honest hint is exactly the two poster textures; at runtime the
    # player-draw wrapper (dissolve_live.py) discovers the true canvas<->decoder
    # binding, so the static hint need not (and must not) guess the steady canvas.
    return {
        "decoderKey": decoder_key,
        "boundary": "motion-path-mm",
        "outgoing": [frm],
        "incoming": [to],
        "boundaryCrossfade": {"from": frm, "to": to},
        "boundaryOccurrences": [{"slide": o["slide"], "owner": o["owner"]} for o in occs],
        "scannedSlideUuids": scanned,
        "slideList": slide_list,
    }


def build_continuity_plan(bridge34: bool) -> dict:
    """The runtime plan injected into the player — equal to
    `derive_plan(...).to_runtime()` for this fixture, plus the transparent
    background the P2 export needs.

    `movies` names movie1 ONLY: naming the slide-3-only WA0125 clip admits it to
    the runtime's `stash()` plan-name filter, which pools it at the 3->4 detach
    and remounts it at the fallback footprint (the stray 62e1ab7 fixed for the
    product by not naming it). `MOVIE2_ROI` stays a probe-side constant.

    `bridge34=False` removes the 3->4 bridge ONLY; the 1->2 retire and the 2->3
    restart stay, so `--disable-bridge34` turns exactly one finding red.
    """
    plan: dict = {
        "movies": {
            "movie1": {
                "assetKeys": [MOVIE1_TOKEN.lower()],
                "footprint": dict(zip(("x", "y", "w", "h"), MOVIE_ROI)),
            },
        },
        "boundaries": [
            {"atScene": SLIDE2_MIN_HASH, "action": "retire", "movieKey": MOVIE1_KEY},
            {"atScene": SLIDE3_MIN_HASH, "action": "restart"},
        ],
        "transparentBackground": True,
    }
    if bridge34:
        plan["boundaries"].append({
            "atScene": SLIDE4_MIN_HASH,
            "action": "bridge",
            "movieKey": MOVIE1_KEY,
            "srcRect": {"x": 198, "y": 797, "w": 952, "h": 268},
            "durationSeconds": TRANS_S,
            "rect": dict(zip(("x", "y", "w", "h"), SLIDE4_MOVIE_RECT)),
        })
    return plan


def _event_scene(event: dict) -> int | None:
    detail = event.get("detail")
    if not isinstance(detail, dict):
        return None
    for key in ("scene", "atScene", "hashNum"):
        value = detail.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return _hash_num(detail.get("sceneHash"))


def _target_elids(events: list[dict], target_key: str) -> set:
    """Element ids the runtime has ever attributed to `target_key`."""
    ids: set = set()
    for e in events:
        detail = e.get("detail")
        if not isinstance(detail, dict):
            continue
        if _movie_key(detail.get("key") or "") != target_key:
            continue
        for field in ("elId", "newElId"):
            if detail.get(field) is not None:
                ids.add(detail[field])
        for el in detail.get("elIds") or []:
            ids.add(el)
    return ids


def refusalEvents(events: list[dict], target_key: str, min_scene: int) -> list[dict]:
    """`preserve-refused` / `retire-boundary` notes for `target_key` at/after `min_scene`."""
    out = []
    for e in events:
        if e.get("kind") not in ("preserve-refused", "retire-boundary"):
            continue
        detail = e.get("detail") if isinstance(e.get("detail"), dict) else {}
        if _movie_key(detail.get("key") or "") != target_key:
            continue
        scene = _event_scene(e)
        if scene is None or scene < min_scene:
            continue
        out.append(e)
    return out


def carryEvents(events: list[dict], target_key: str, lo_scene: int, hi_scene: int) -> list[dict]:
    """Preservation notes that would mean the movie WAS carried in `[lo, hi)`.

    Only notes that mean a carry actually happened — `remount-suppressed`,
    `remount-stale`, `remount-no-stage` and the `*-error` notes all mean the
    opposite and must not turn the refusal red.
    """
    el_ids = _target_elids(events, target_key)
    out = []
    for e in events:
        kind = str(e.get("kind") or "")
        if kind not in CARRY_EVENT_KINDS:
            continue
        detail = e.get("detail") if isinstance(e.get("detail"), dict) else {}
        keyed = _movie_key(detail.get("key") or "") == target_key
        el_match = any(detail.get(f) in el_ids for f in ("elId", "newElId") if detail.get(f) is not None)
        if not (keyed or el_match):
            continue
        scene = _event_scene(e)
        if scene is None or not (lo_scene <= scene < hi_scene):
            continue
        out.append(e)
    return out


def carryCensusVerdict(
    census: object, events: list[dict], target_key: str, lo_scene: int, hi_scene: int
) -> dict:
    """Clause (c)'s count. The in-page census is authoritative (`total` is taken
    before any slicing); the fetched notes are a belt. A missing or malformed
    census fails closed — absence cannot be proven from a bounded sample."""
    local = carryEvents(events, target_key, lo_scene, hi_scene)
    if not isinstance(census, dict) or not isinstance(census.get("total"), int):
        return {
            "ok": False,
            "total": None,
            "reason": "carry census missing or malformed",
            "census": census,
            "localMatches": local[:6],
            "localMatchesN": len(local),
        }
    total = int(census["total"])
    return {
        "ok": total == 0 and not local,
        "total": total,
        "reason": None if (total == 0 and not local) else "carry notes inside the retire zone",
        "census": {k: v for k, v in census.items() if k != "sample"},
        "sample": (census.get("sample") or [])[:6],
        "localMatches": local[:6],
        "localMatchesN": len(local),
    }


def poolCensusVerdict(
    census: object, target_key: str, lo_scene: int, hi_scene: int
) -> dict:
    """The real pool on settled slide 2: zero pooled AND zero `fromDom`
    preserved entries for the target's asset. A census that is missing,
    malformed or taken outside the retire zone is NOT evidence.

    Entries are attributed by the stamped `movieKey` first, then by `key`. A
    preserved decoder whose src was really cleared reports an EMPTY key, so an
    entry with neither is unattributable and invalidates the whole census — a
    non-empty key that maps to no plan movie is provably another asset and is
    tolerated."""
    if not isinstance(census, dict) or not isinstance(census.get("entries"), list):
        return {"ok": False, "reason": "pool census missing or malformed", "census": census}
    scene = _hash_num(census.get("sceneHash"))
    if scene is None or not (lo_scene <= scene < hi_scene):
        return {
            "ok": False,
            "reason": "pool census taken outside the retire zone",
            "sceneHash": census.get("sceneHash"),
        }
    mine = []
    unattributable = []
    for e in census["entries"]:
        if not isinstance(e, dict):
            unattributable.append(e)
            continue
        stamped = e.get("movieKey")
        raw = str(e.get("key") or "")
        if isinstance(stamped, str) and stamped:
            attributed = _movie_key(stamped)
        elif raw:
            attributed = _movie_key(raw)
        else:
            unattributable.append(e)
            continue
        if attributed == target_key:
            mine.append(e)
    if unattributable:
        return {
            "ok": False,
            "reason": "pool census holds an unattributable entry",
            "sceneHash": census.get("sceneHash"),
            "entriesN": len(census["entries"]),
            "unattributable": unattributable[:6],
            "unattributableN": len(unattributable),
        }
    return {
        "ok": not mine,
        "reason": None if not mine else "the target movie is still pooled on slide 2",
        "sceneHash": census.get("sceneHash"),
        "entriesN": len(census["entries"]),
        "entriesForTarget": mine[:6],
        "entriesForTargetN": len(mine),
        "fromDomForTargetN": sum(1 for e in mine if e.get("fromDom")),
    }


def frozenCompositeAfterFlip(
    motion_across_flip: object,
    flip_rois: object = None,
    settled_roi: object = None,
    *,
    min_after_pairs: int = 4,
    min_rgb_mean: float = BLACK_RGB_MEAN_MAX,
) -> dict:
    """Clause (e): the movie ROI must be PIXEL-FROZEN for the whole post-flip
    window and have been LIVE before it — the raw export's own behaviour once
    the carry is refused (a carried movie shows after-pair MAE >> eps).

    Stillness alone is not enough: an ROI that went dead/all-black after the cut
    and recovered later is also "still". The post-flip frames must therefore also
    be CONTENT-VALID — not blank (rgbMean above the script's own opaque-black
    level) and equal, within the same `pairEps`, to the composite the slide-2
    settle point actually rests on.

    The burnt-in counter cannot serve here: on the refused slide the patch ROI
    shows the export's poster photo, so it never decodes. Fails closed when the
    scored window, the post-flip ROIs or the settled ROI are absent, short or
    malformed.
    """
    m = motion_across_flip if isinstance(motion_across_flip, dict) else {}
    after = m.get("afterPairMae")
    eps = m.get("pairEps")
    if not isinstance(after, list) or not isinstance(eps, (int, float)):
        return {"frozen": False, "reason": "no scored flip window", "n": 0}
    if any(not isinstance(v, (int, float)) for v in after):
        return {"frozen": False, "reason": "non-numeric pair mae", "n": len(after)}
    if len(after) < min_after_pairs:
        return {
            "frozen": False,
            "reason": "insufficient after-pairs to judge a freeze",
            "n": len(after),
            "afterPairMae": after,
        }
    still = all(float(v) <= float(eps) for v in after)
    live_before = bool(m.get("beforeOk"))
    flip_index = m.get("flipIndex")
    rois = list(flip_rois or [])
    content = {"ok": False, "reason": "no post-flip ROI frames"}
    if isinstance(flip_index, int) and 0 <= flip_index < len(rois) and settled_roi is not None:
        after_rois = rois[flip_index:]
        means = [float(np.asarray(r)[..., :3].mean()) for r in after_rois]
        settled_maes = [_mae_rgb(np.asarray(r), np.asarray(settled_roi)) for r in after_rois]
        blank = [v for v in means if v <= float(min_rgb_mean)]
        off = [v for v in settled_maes if v > float(eps)]
        content = {
            "ok": bool(after_rois and not blank and not off),
            "reason": (
                "post-flip ROI is blank/black" if blank
                else "post-flip ROI does not match the settled slide-2 composite" if off
                else None
            ),
            "n": len(after_rois),
            "rgbMeans": means,
            "settledMae": settled_maes,
            "minRgbMean": float(min_rgb_mean),
        }
    elif settled_roi is None:
        content = {"ok": False, "reason": "no settled slide-2 ROI"}
    reason = None
    if not still:
        reason = "composite kept moving on the refused slide"
    elif not live_before:
        reason = "no motion before the flip — the instrument is blind"
    elif not content["ok"]:
        reason = content["reason"]
    return {
        "frozen": bool(still and live_before and content["ok"]),
        "reason": reason,
        "content": content,
        "n": len(after),
        "afterPairMae": after,
        "beforePairMae": m.get("beforePairMae"),
        "pairEps": eps,
        "liveBeforeFlip": live_before,
        "flipIndex": m.get("flipIndex"),
    }


def frozenIndexAfterFlip(
    index_samples: list[dict], flip_index: int | None, *, min_samples: int = 4
) -> dict:
    """The composited counter must NOT advance after the 1->2 flip (the raw
    export's own behaviour once the carry is refused). Fails closed when the
    patch is not decodable often enough to judge."""
    if flip_index is None:
        return {"frozen": False, "reason": "no scene-hash flip observed", "n": 0}
    decoded = [
        s.get("index")
        for s in index_samples[flip_index:]
        if s.get("index") is not None
    ]
    if len(decoded) < min_samples:
        return {
            "frozen": False,
            "reason": "insufficient decodable samples after the flip",
            "n": len(decoded),
            "indices": decoded,
        }
    frozen = len(set(decoded)) == 1
    return {
        "frozen": frozen,
        "reason": None if frozen else "counter advanced on the refused slide",
        "n": len(decoded),
        "indices": decoded,
        "distinct": sorted(set(decoded)),
    }


def refusedCarry1to2(
    injected_plan: dict,
    preserve_events: list[dict],
    lingering: dict,
    motion_across_flip: object,
    flip_rois: object,
    settled_slide2_roi: object,
    index_samples: list[dict],
    flip_index: int | None,
    hash1: object,
    hash2: object,
    player_build_errors: list,
    carry_census: object = None,
    *,
    target_key: str = MOVIE1_KEY,
    retire_scene: int = SLIDE2_MIN_HASH,
    zone_scene: int = RETIRE_ZONE_MIN_HASH,
    restart_scene: int = SLIDE3_MIN_HASH,
) -> dict:
    """Fail-CLOSED verdict that the 1->2 carry was REFUSED and slide 2 therefore
    looks exactly like the raw export (plan §4).

    All of: (a) the injected plan retires `target_key` at `retire_scene`;
    (b) a positive refusal event at scene >= `zone_scene` (the runtime declines
    to preserve during the transition scene, which the player still hashes as
    `retire_scene - 1`); (c) zero carry notes for that movie anywhere in the
    retire zone `[zone_scene, restart_scene)`, the transition scene included;
    (d) no lingering preserved/remounted overlay and nothing painting over the
    slide-1/2 footprints on settled slide 2; (e) the composite in the movie ROI
    pixel-FROZEN across the post-flip window (live before it) with a real 1->2
    hash change; (f) no player build error.
    """
    boundaries = (injected_plan or {}).get("boundaries") or []
    plan_retire = next(
        (
            b
            for b in boundaries
            if b.get("action") == "retire"
            and b.get("atScene") == retire_scene
            and b.get("movieKey") == target_key
        ),
        None,
    )
    refusals = refusalEvents(preserve_events, target_key, zone_scene)
    carried = carryCensusVerdict(
        carry_census, preserve_events, target_key, zone_scene, restart_scene
    )
    lingering = lingering or {}
    no_lingering = bool(
        lingering.get("count", 1) == 0
        and lingering.get("preservedCount", 1) == 0
        and lingering.get("paintingCount", 1) == 0
    )
    frozen = frozenCompositeAfterFlip(motion_across_flip, flip_rois, settled_slide2_roi)
    index_diagnostic = frozenIndexAfterFlip(index_samples, flip_index)
    from_n = _strict_hash_num(hash1)
    to_n = _strict_hash_num(hash2)
    hash_changed = bool(
        from_n is not None and to_n is not None and to_n > from_n and to_n >= retire_scene
    )
    ok = bool(
        plan_retire
        and refusals
        and carried["ok"]
        and no_lingering
        and frozen["frozen"]
        and hash_changed
        and not player_build_errors
    )
    reasons = []
    if not plan_retire:
        reasons.append("injected plan has no retire boundary for the target key")
    if not refusals:
        reasons.append("no preserve-refused/retire-boundary event in the retire zone")
    if not carried["ok"]:
        reasons.append(carried["reason"] or "the movie was carried inside the retire zone")
    if not no_lingering:
        reasons.append("a preserved/remounted/painting <video> lingers on slide 2")
    if not frozen["frozen"]:
        reasons.append(frozen.get("reason") or "composite not frozen")
    if not hash_changed:
        reasons.append("no valid forward 1->2 boundary")
    if player_build_errors:
        reasons.append("player build error")
    return {
        "ok": ok,
        "planRetire": plan_retire,
        "refusalEvents": refusals[:6],
        "refusalEventsN": len(refusals),
        "carryInRetireZone": carried,
        "carryEventsInRetireZoneN": carried["total"],
        "lingering": lingering,
        "frozenComposite": frozen,
        "frozenIndexNonGating": index_diagnostic,
        "hash": f"{hash1}->{hash2}",
        "hashChanged": hash_changed,
        "playerBuildErrors": player_build_errors,
        "reasons": reasons,
    }


def neverPooledEvidence(
    preserve_events: list[dict],
    carry_census: object = None,
    pool_census: object = None,
    *,
    target_key: str = MOVIE1_KEY,
    zone_scene: int = RETIRE_ZONE_MIN_HASH,
    restart_scene: int = SLIDE3_MIN_HASH,
) -> dict:
    """"Nothing was ever pooled" — the stronger substitute for the
    reuse-skip/retire pair once the target key is retired before the restart.

    Requires a positive refusal note, zero carry notes in the retire zone, AND a
    well-formed pool census taken on settled slide 2 that holds no pooled or
    `fromDom` preserved entry for the key — a detached decoder can sit in the
    pool through slide 2 without ever being reused, so silence is not evidence.
    An invalid census invalidates the route (the original positive pair is then
    required).
    """
    refusals = refusalEvents(preserve_events, target_key, zone_scene)
    carried = carryCensusVerdict(
        carry_census, preserve_events, target_key, zone_scene, restart_scene
    )
    pooled = poolCensusVerdict(pool_census, target_key, zone_scene, restart_scene)
    return {
        "ok": bool(refusals and carried["ok"] and pooled["ok"]),
        "refusalEventsN": len(refusals),
        "carryInRetireZone": carried,
        "carryEventsInRetireZoneN": carried["total"],
        "poolCensus": pooled,
    }


def footprintFullyLive(
    frames: list,
    *,
    expected_rect: tuple[int, int, int, int] = SLIDE4_MOVIE_RECT,
    control_rect: dict | None = None,
) -> dict:
    """Settled slide 4 must PAINT the carried movie: `score_visible_slide` over
    the bridged footprint, with imported thresholds. Anything but
    `verdict is True` (including `inconclusive`) fails."""
    if len(frames) < 2:
        return {"ok": False, "verdict": None, "status": "inconclusive",
                "reason": "insufficient burst frames", "n": len(frames)}
    scored = score_visible_slide(
        frames,
        [{**dict(zip(("x", "y", "w", "h"), expected_rect)), "label": "slide4Movie"}],
        control_rect or SLIDE4_CONTROL_RECT,
    )
    return {"ok": scored.get("verdict") is True, "n": len(frames), **scored}


def liveContinuity1to2(
    motion_across_flip: dict,
    flip_samples: list[dict],
    presented_samples: list[dict],
    hash1: object,
    hash2: object,
    restart_min_hash: object = None,
) -> dict:
    """Fail-CLOSED sub-verdict for live-`<video>` continuity through the 1->2
    Magic Move (corrected model — see the handover CORRECTION 2026-09-18 and the
    Step-2 contract, Stream B). The 1->2 movie is a live `<video>` at the
    footprint, NOT a fed 2D canvas, so the old deck-texid / canvas-feed checks
    (`bothSidedTexids`, `contextType2d`, `incomingFeedDraw`) are DROPPED entirely:
    they assumed a 2D-canvas surface that does not exist for 1->2, and the deck
    texids they keyed off are the provenance-only motion-path Magic Move poster
    swap (a 1->2 or 3->4 crossfade, never a fed surface in-window here). A live
    `<video>` owner reports `contextType=null`, so this gate requires NO 2D
    context and NO texid membership.

    `ok` iff ALL hold (absence of any ⇒ fail closed; the failing name is
    recorded):
      - `boundaryValid` — `hash1` and `hash2` both parse AND `num(hash2) >
        num(hash1)`: a genuine FORWARD entry into the 1->2 window. A regressive
        (`#1->#0`), equal, or unparseable hash pair cannot place the after-window.
      - `stableFootprintDecoder` — exactly ONE distinct non-null `decoderId`
        covering a strong majority (>=70%) of the after-window, defined as samples
        strictly inside `[num(hash2), restart_min_hash)` (NOT merely
        `sceneHash != hash1`, which would admit a pre-advance or a 2->3 restart
        frame). A same-key handoff (>=2 distinct non-null ids) or a mostly-
        unresolved window fails; a few transient null frames (the <video> briefly
        mid-remount during the fast MM animation) are tolerated.
      - `crossingIdentity` — the PRE-flip footprint owner (flip_samples with
        hn <= num(hash1)) is resolved AND is exactly the same single decoder as the
        after-window owner. This rejects a same-key HANDOFF (D1 owns before, sibling
        D2 slides into the footprint after): post-flip stability + rVFC advance alone
        cannot see it because D2's own clock is already advancing. Derived from
        flip_samples (jitter-tolerant), not the two exact crossing frames, and NOT
        the aliased pixel crossing-MAE.
      - `rvfcAdvance` — the bound footprint decoder's rVFC `presentedMediaTime`
        advances (> 0.05) within `[num(hash2), restart_min_hash)`, proving the
        live `<video>` is actually presenting new frames across the cut. Fails
        closed on an invalid boundary, a null bound decoder, or <2 samples.

    `motionAcrossFlip.ok` (the pixel crossing-MAE verdict) is NOT gated here — it
    aliases to ~0 ("frozen crossing") on the disposable two-state grating, the
    exact parity-aliasing that `score_index_progression` defeats; gating it would
    reintroduce that flake. Composited motion is proven by the top-level
    `visible_motion.ok` + `index_run.ok` (the aliasing-immune burnt-in counter);
    this sub-verdict adds decoder IDENTITY + crossing continuity + LIVENESS.

    `flip_samples` supply the after-window decoder identity (roi/sceneHash/
    decoderId). `presented_samples` (media snapshots carrying `videos`) supply the
    bound decoder's own rVFC clock. `restart_min_hash` upper-bounds both windows.
    """
    motion_ok = bool((motion_across_flip or {}).get("ok"))

    n1 = _strict_hash_num(hash1)
    n2 = _strict_hash_num(hash2)
    n_restart = restart_min_hash if isinstance(restart_min_hash, int) else _strict_hash_num(restart_min_hash)
    # A missing/malformed restart bound leaves the after-window unbounded above (a
    # #99 sample would count) — so the bound is REQUIRED for a valid boundary (the
    # function itself stays fail-closed, not only the production caller).
    boundary_valid = n1 is not None and n2 is not None and n2 > n1 and n_restart is not None

    def _in_window(s: dict) -> bool:
        hn = _strict_hash_num(s.get("sceneHash"))
        if hn is None or n2 is None or hn < n2:
            return False
        if n_restart is not None and hn >= n_restart:
            return False
        return True

    post = [s for s in (flip_samples or []) if _in_window(s)] if boundary_valid else []
    distinct_ids = sorted({s.get("decoderId") for s in post}, key=lambda x: (x is None, str(x)))
    # ONE dominant footprint owner: exactly one DISTINCT non-null decoderId across
    # the after-window, covering a strong majority of it. A same-key HANDOFF is >=2
    # distinct non-null ids -> fail. A mostly-unresolved window -> fail. A few
    # transient unresolved (null) frames are tolerated: the footprint <video> is
    # briefly mid-remount during the fast MM animation, so ~1 capture per run can
    # land in that gap even though the movie is continuously present otherwise
    # (measured: when placed its footprint IoU is ~0.998, never marginal) — a
    # zero-null rule turned that instrument jitter into a spurious RED. Rejecting
    # the real failure modes while tolerating jitter keeps this fail-closed.
    non_null_ids = [s.get("decoderId") for s in post if s.get("decoderId") is not None]
    distinct_non_null = sorted(set(non_null_ids))
    non_null_frac = (len(non_null_ids) / len(post)) if post else 0.0
    # A tolerated null must be a genuine ABSENCE gap, never a masked handoff: a null
    # from `footprintOwnerDecoderId` returning `via=='ambiguous'` means TWO decoders
    # both cover the footprint (D1 leaving + D2 arriving) — a handoff in progress —
    # so ANY ambiguous after-frame fails closed rather than being tolerated as jitter.
    # (A frame where a single OTHER decoder owns the footprint is not null; it makes
    # distinct_non_null == 2 and fails anyway.)
    has_ambiguous_owner = any(s.get("ownerAmbiguous") for s in post)
    stable = (
        bool(post)
        and len(distinct_non_null) == 1
        and non_null_frac >= 0.7
        and not has_ambiguous_owner
    )
    bound_decoder_id = distinct_non_null[0] if stable else None

    # Handoff defense, derived from flip_samples (jitter-tolerant): the PRE-flip
    # footprint owner (frames with hn <= n1) must be resolved and be EXACTLY the same
    # single decoder as the after-window owner. A different pre-flip owner (D1 before,
    # D2 after) is a same-key HANDOFF -> fail. Deriving this from flip_samples rather
    # than the two exact crossing frames score_motion_across_flip picks tolerates a
    # transient unresolved frame at the flip instant (which flaked crossingDecoder
    # Stable on the slow profile) while still requiring before-evidence (empty pre
    # owners -> fail closed). Movie-key correctness is already guaranteed by
    # footprintOwnerDecoderId (it owns a footprint only when assetKey matches it).
    pre = (
        [s for s in (flip_samples or [])
         if (lambda h: h is not None and h <= n1)(_strict_hash_num(s.get("sceneHash")))]
        if boundary_valid else []
    )
    pre_owner_ids = sorted({s.get("decoderId") for s in pre if s.get("decoderId") is not None},
                           key=str)
    pre_ambiguous = any(s.get("ownerAmbiguous") for s in pre)
    crossing_identity = bool(
        bound_decoder_id is not None
        and pre_owner_ids == [bound_decoder_id]
        and not pre_ambiguous
    )

    # rVFC advance of the bound footprint <video>, bounded to the SAME window.
    if not boundary_valid:
        rvfc = {"ok": False, "reason": "invalid 1->2 boundary", "n": 0}
    elif bound_decoder_id is None:
        rvfc = {"ok": False, "reason": "no bound decoder", "n": 0}
    else:
        bounded = [s for s in (presented_samples or []) if _in_window(s)]
        rvfc = _presented_time_advances(bounded, bound_decoder_id, n2)
    rvfc_ok = bool(rvfc.get("ok"))

    checks = {
        "boundaryValid": boundary_valid,
        "stableFootprintDecoder": stable,
        "crossingIdentity": crossing_identity,
        "rvfcAdvance": rvfc_ok,
    }
    failed = [name for name, ok in checks.items() if not ok]
    return {
        "ok": not failed,
        "failed": failed,
        "boundDecoderId": bound_decoder_id,
        "boundaryValid": {"ok": boundary_valid, "n1": n1, "n2": n2, "restart": n_restart},
        "stableFootprintDecoder": {
            "ok": stable,
            "distinctDecoderIds": distinct_ids,
            "distinctNonNull": distinct_non_null,
            "nonNullFrac": round(non_null_frac, 3),
            "afterN": len(post),
        },
        "crossingIdentity": {
            "ok": crossing_identity,
            "preOwnerIds": pre_owner_ids,
            "afterOwner": bound_decoder_id,
        },
        "rvfcAdvance": rvfc,
        # Reported for provenance only — NOT a gating sub-condition (aliased pixel
        # crossing-MAE; the crossing IDENTITY fields above ARE gated).
        "motionAcrossFlipOk": motion_ok,
    }


def movingContinuity3to4(
    owner_samples: list[dict],
    presented_samples: list[dict],
    slide3_movie_decoder: object,
    hash3: object,
    hash4: object,
    slide4_min_hash: int,
) -> dict:
    """Fail-CLOSED sub-verdict for playback continuity through the 3->4 moving
    Magic Move (positive control). The owner authored "Play movie across slides"
    but the HTML export RESTARTS movie1 on a fresh decoder at the grown slide-4
    footprint (see the Phase-0 diagnosis); the PRESERVE 3->4 bridge repairs it by
    keeping the SAME decoder playing while its box translates+scales. This gate
    proves the repair engaged — a raw (unbridged) export restarts and fails it.

    `ok` iff ALL hold (absence of any ⇒ fail closed; the failing name recorded):
      - `boundaryValid` — `hash3`/`hash4` parse, `num(hash4) > num(hash3)`, and
        `num(hash4) >= slide4_min_hash`: a genuine forward entry into slide 4.
      - `stableSlide4Owner` — exactly ONE distinct non-null footprint decoderId
        across the after-window (`hn >= num(hash4)`), covering a strong majority
        (>=70%); no `ownerAmbiguous` frame (two decoders at the slot). Owner is
        resolved by the caller at the MOVING interpolated footprint, keyed to
        movie1 (so the retiring right-side WA0125 the grown box overlaps is
        excluded).
      - `crossingIdentity` — that single slide-4 owner IS the SAME decoder that
        played slide 3 (`slide3_movie_decoder`, the 2->3 restart decoder). This is
        the ANTI-RESTART check: the export's fresh autoplay-from-0 element is a
        DIFFERENT decoder and fails here; only the bridged continuing decoder
        passes.
      - `rvfcMonotonic` — that decoder's rVFC `presentedMediaTime` ADVANCES
        (> 0.05) across the after-window and never rewinds (a reset-to-~0 restart
        would rewind), proving the live clock continues rather than restarting.
    """
    n3 = _strict_hash_num(hash3)
    n4 = _strict_hash_num(hash4)
    boundary_valid = (
        n3 is not None and n4 is not None and n4 > n3
        and isinstance(slide4_min_hash, int) and n4 >= slide4_min_hash
    )

    def _after(s: dict) -> bool:
        hn = _strict_hash_num(s.get("sceneHash"))
        return hn is not None and n4 is not None and hn >= n4

    after = [s for s in (owner_samples or []) if _after(s)] if boundary_valid else []
    non_null_ids = [s.get("decoderId") for s in after if s.get("decoderId") is not None]
    distinct_non_null = sorted({str(x) for x in non_null_ids})
    non_null_frac = (len(non_null_ids) / len(after)) if after else 0.0
    has_ambiguous = any(s.get("ownerAmbiguous") for s in after)
    stable = (
        bool(after)
        and len(distinct_non_null) == 1
        and non_null_frac >= 0.7
        and not has_ambiguous
    )
    slide4_owner = non_null_ids[0] if stable else None

    crossing_identity = bool(
        slide4_owner is not None
        and slide3_movie_decoder is not None
        and str(slide4_owner) == str(slide3_movie_decoder)
    )

    if not boundary_valid:
        rvfc = {"ok": False, "reason": "invalid 3->4 boundary", "n": 0}
    elif slide4_owner is None:
        rvfc = {"ok": False, "reason": "no stable slide-4 owner", "n": 0}
    else:
        bounded = [s for s in (presented_samples or []) if _after(s)]
        rvfc = _presented_time_advances(bounded, slide4_owner, n4)
    rvfc_ok = bool(rvfc.get("ok"))

    checks = {
        "boundaryValid": boundary_valid,
        "stableSlide4Owner": stable,
        "crossingIdentity": crossing_identity,
        "rvfcMonotonic": rvfc_ok,
    }
    failed = [name for name, ok in checks.items() if not ok]
    return {
        "ok": not failed,
        "failed": failed,
        "slide4Owner": slide4_owner,
        "slide3MovieDecoder": slide3_movie_decoder,
        "boundaryValid": {"ok": boundary_valid, "n3": n3, "n4": n4, "slide4Min": slide4_min_hash},
        "stableSlide4Owner": {
            "ok": stable,
            "distinctNonNull": distinct_non_null,
            "nonNullFrac": round(non_null_frac, 3),
            "afterN": len(after),
        },
        "crossingIdentity": {"ok": crossing_identity},
        "rvfcMonotonic": rvfc,
    }


def _score_black(arr: np.ndarray, roi: tuple[int, int, int, int]) -> dict:
    patch = _crop(arr, roi)
    if patch.size == 0:
        return {"ok": False, "reason": "empty crop", "roi": list(roi)}
    a = patch[:, :, 3].astype(np.float64)
    rgb = patch[:, :, :3].astype(np.float64)
    return {
        "ok": bool(a.mean() >= 240 and rgb.mean() <= BLACK_RGB_MEAN_MAX),
        "alphaMean": float(a.mean()),
        "rgbMean": float(rgb.mean()),
        "shape": list(patch.shape[:2]),
        "roi": list(roi),
    }


def _score_green(arr: np.ndarray, roi: tuple[int, int, int, int] = GREEN_ROI_S1) -> dict:
    patch = _crop(arr, roi)
    if patch.size == 0:
        return {"ok": False, "reason": "empty crop"}
    a = patch[:, :, 3].astype(np.float64)
    g = patch[:, :, 1].astype(np.float64)
    partial = bool((a.mean() > 30) and (a.mean() < 230))
    greenish = bool(g.mean() > patch[:, :, 0].mean() + 15)
    return {
        "ok": partial and greenish,
        "alphaMean": float(a.mean()),
        "greenMean": float(g.mean()),
        "partial": partial,
        "greenish": greenish,
        "shape": list(patch.shape[:2]),
    }


def _score_green_front_composite(
    composite: np.ndarray,
    roi: tuple[int, int, int, int],
    footprint: tuple[int, int, int, int],
    source: np.ndarray | None,
) -> dict:
    """Prove the green square is IN FRONT of the movie by diffing the composite
    against the movie1 decoder's OWN source pixels for the same mapped region.

    A standalone "is this ROI greenish" test is satisfied by the movie's own
    green content even with the square BEHIND it. If the translucent green
    square (~75/255 alpha) is genuinely in front, compositing green-over-movie
    must shift the region toward green and away from red relative to the raw
    source; if it's behind, composite == source and the deltas are ~0.
    Fails closed (ok=False) if the decoder source can't be sampled — no
    fallback to the standalone greenish test.
    """
    comp_patch = _crop(composite, roi)
    if comp_patch.size == 0:
        return {"ok": False, "reason": "empty composite crop"}
    comp_rgb = comp_patch[:, :, :3].astype(np.float64).reshape(-1, 3).mean(axis=0)
    if source is None or source.size == 0:
        return {
            "ok": False,
            "reason": "no decoder source sample",
            "compositeRGB": comp_rgb.tolist(),
            "sourceRGB": None,
            "dG": None,
            "dR": None,
        }
    fx, fy, fw, fh = footprint
    gx, gy, gw, gh = roi
    nx0, ny0 = (gx - fx) / fw, (gy - fy) / fh
    nw, nh = gw / fw, gh / fh
    sh, sw = source.shape[:2]
    x0, y0 = max(0, int(round(nx0 * sw))), max(0, int(round(ny0 * sh)))
    x1, y1 = min(sw, int(round((nx0 + nw) * sw))), min(sh, int(round((ny0 + nh) * sh)))
    source_patch = source[y0:y1, x0:x1]
    if source_patch.size == 0:
        return {
            "ok": False,
            "reason": "empty mapped source crop",
            "compositeRGB": comp_rgb.tolist(),
            "sourceRGB": None,
            "dG": None,
            "dR": None,
            "mappedRect": [x0, y0, x1, y1],
        }
    source_rgb = source_patch[:, :, :3].astype(np.float64).reshape(-1, 3).mean(axis=0)
    dG = float(comp_rgb[1] - source_rgb[1])
    dR = float(comp_rgb[0] - source_rgb[0])
    greenish = bool(comp_rgb[1] > comp_rgb[0] + 15)
    ok = bool(dG >= 20 and dR < 0 and greenish)
    return {
        "ok": ok,
        "compositeRGB": comp_rgb.tolist(),
        "sourceRGB": source_rgb.tolist(),
        "dG": dG,
        "dR": dR,
        "greenish": greenish,
        "mappedRect": [x0, y0, x1, y1],
    }


def _score_empty(arr: np.ndarray) -> dict:
    fracs = []
    for c in EMPTY_CORNERS:
        patch = _crop(arr, c)
        if patch.size == 0:
            continue
        fracs.append(float((patch[:, :, 3] < 8).mean()))
    a = analyze_rgba(arr)
    return {
        "ok": bool(fracs) and all(f >= 0.9 for f in fracs) and a["transparentFrac"] >= 0.35,
        "cornerTransparentFrac": fracs,
        "transparentFrac": a["transparentFrac"],
        "alphaMin": a["alphaMin"],
    }


def _times(
    samples: list[dict], key: str = "primary", decoder_id: object | None = None
) -> list[float | None]:
    """Track a movie's clock across samples.

    `key="primary"`/`"min"` give the max/min currentTime across ALL playing
    videos (informational only). Any other `key` gives that asset key's clock;
    when `decoder_id` is given it is BOUND to that one decoder — only videos
    whose `decoderId == decoder_id` (a DOM/pool mirror of the same element)
    contribute, never a max across sibling same-key decoders. A stall on the
    bound decoder then surfaces as a non-advancing (or None) clock instead of
    being masked by a fresh/pooled same-key instance sitting at a higher time.
    """
    out: list[float | None] = []
    for s in samples:
        vids = s.get("videos") or []
        times = [
            float(v["currentTime"])
            for v in vids
            if v.get("currentTime") is not None and (v.get("readyState") or 0) >= 2
        ]
        if key == "primary":
            out.append(max(times) if times else None)
        elif key == "min":
            out.append(min(times) if times else None)
        else:
            hits = [
                float(v["currentTime"])
                for v in vids
                if _movie_key(v.get("src") or "") == key
                and v.get("currentTime") is not None
                and (decoder_id is None or v.get("decoderId") == decoder_id)
            ]
            out.append(max(hits) if hits else None)
    return out


def _score_black_auto(arr: np.ndarray) -> dict:
    """Find authored opaque black via near-pure opaque black pixels."""
    a = arr[:, :, 3]
    rgb = arr[:, :, :3]
    mask = (a > 250) & (rgb.max(axis=2) < 12)
    count = int(mask.sum())
    if count < 200:
        return {"ok": False, "reason": "no opaque black blob", "count": count}
    ys, xs = np.where(mask)
    vals = rgb[mask].astype(np.float64)
    return {
        "ok": bool(vals.mean() <= 12 and count >= 200),
        "count": count,
        "bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
        "alphaMean": 255.0,
        "rgbMean": float(vals.mean()),
    }


def _hash_num(h: str | None) -> int | None:
    m = __import__("re").match(r"#(\d+)", _norm_hash(h))
    return int(m.group(1)) if m else None


def _strict_hash_num(h: object) -> int | None:
    """Strict scene-hash parse for boundary validation: FULL-match `#<digits>`
    after stripping only a `?query` suffix. Unlike `_hash_num`'s prefix match, a
    malformed value like `#1junk` returns None (fail closed) rather than 1."""
    s = str(h if h is not None else "")
    if "?" in s:
        s = s.split("?", 1)[0]
    m = __import__("re").fullmatch(r"#(\d+)", s)
    return int(m.group(1)) if m else None


def _mae_rgb(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape or a.size == 0:
        return float("inf")
    return float(np.mean(np.abs(a[:, :, :3].astype(np.float64) - b[:, :, :3].astype(np.float64))))


def _presented_time_advances(samples: list[dict], decoder_id: object, min_hash: int) -> dict:
    """rVFC-presented mediaTime advancement for a decoder, on/after min_hash.

    An alternate, pixel-independent signal for presentedMotionOk: the decoder
    is genuinely presenting new frames even if the composed-ROI pixel check
    is inconclusive (e.g. a still moment in the source pattern).
    """
    if decoder_id is None:
        return {"ok": False, "reason": "no decoderId", "n": 0}
    vals: list[float] = []
    for s in samples:
        hn = _hash_num(s.get("sceneHash"))
        if hn is None or hn < min_hash:
            continue
        for v in s.get("videos") or []:
            if v.get("decoderId") == decoder_id and v.get("presentedMediaTime") is not None:
                vals.append(float(v["presentedMediaTime"]))
    if len(vals) < 2:
        return {"ok": False, "reason": "insufficient presented-time samples", "n": len(vals)}
    # ORDERED forward progression: net advance > 0.05 AND never regress more than
    # 0.05 below ANY previously-presented time (compare to the running max, not just
    # the adjacent step — a cumulative rewind split into small steps like
    # 10.00->9.96->9.92->10.10 would slip past an adjacent-delta check). `max-min`
    # accepted a plain rewind (10.0->1.0 reads as +9.0); a genuinely playing
    # decoder's rVFC media time is monotonic, so any material regression is a
    # restart/seek, not continuity — reject it (fail closed).
    advance = vals[-1] - vals[0]
    running_max = vals[0]
    worst_regression = 0.0
    for v in vals[1:]:
        worst_regression = min(worst_regression, v - running_max)
        running_max = max(running_max, v)
    ok = advance > 0.05 and worst_regression >= -0.05
    return {"ok": bool(ok), "n": len(vals), "advance": advance, "worstRegression": worst_regression}


def _score_visible_movie_motion(frame_paths: list[Path], roi: tuple[int, int, int, int] = MOVIE_ROI) -> dict:
    """Require sustained composed movie ROI motion — clock-only / one cut is not enough."""
    if len(frame_paths) < 3:
        return {"ok": False, "reason": "need >=3 frames", "n": len(frame_paths)}
    x, y, w, h = roi
    # Inset a few pixels to avoid borders, but keep the full movie face — a tiny
    # center crop can sit on a static overlay / testsrc bullseye and false-fail.
    inset = 8
    patches = []
    for p in frame_paths:
        arr = np.array(Image.open(p))
        patch = arr[y + inset : y + h - inset, x + inset : x + w - inset]
        if patch.size == 0:
            continue
        patches.append(patch)
    scored = score_visible_movie_motion(patches)
    scored["roi"] = list(roi)
    return scored


def _per_movie_obs(snap: dict) -> list[dict]:
    """Per-decoder observations; prefer entries with videoWidth>0 over null-width dupes."""
    by_id: dict[object, dict] = {}
    order: list[object] = []

    def _ingest(row: dict) -> None:
        did = row.get("decoderId")
        key = (did if did is not None else id(row), row.get("key"), row.get("fromPreservePool"))
        prev = by_id.get(key)
        if prev is None:
            by_id[key] = row
            order.append(key)
            return
        # Prefer the observation that has real decoded dimensions.
        pw = prev.get("videoWidth") or 0
        rw = row.get("videoWidth") or 0
        if rw > 0 and pw <= 0:
            by_id[key] = row
        elif rw > 0 and pw > 0:
            # Same width family — keep the one with a clock if the other lacks it.
            if prev.get("currentTime") is None and row.get("currentTime") is not None:
                by_id[key] = row

    for v in snap.get("videos") or []:
        src = v.get("src") or ""
        _ingest(
            {
                "key": _movie_key(src),
                "srcTail": str(src)[-80:],
                "currentTime": v.get("currentTime"),
                "presentedMediaTime": v.get("presentedMediaTime"),
                "videoWidth": v.get("w") if v.get("w") is not None else v.get("videoWidth"),
                "videoHeight": v.get("h") if v.get("h") is not None else v.get("videoHeight"),
                "paused": v.get("paused"),
                "readyState": v.get("readyState"),
                "decoderId": v.get("decoderId"),
                "fromPreservePool": bool(v.get("fromPreservePool")),
            }
        )
    for p in snap.get("preservePool") or []:
        _ingest(
            {
                "key": _movie_key(p.get("key") or ""),
                "srcTail": p.get("key"),
                "currentTime": p.get("currentTime"),
                "presentedMediaTime": None,
                "videoWidth": p.get("videoWidth"),
                "videoHeight": p.get("videoHeight"),
                "paused": p.get("paused"),
                "readyState": p.get("readyState"),
                "decoderId": p.get("elId"),
                "fromPreservePool": True,
                "inDocument": p.get("inDocument"),
            }
        )
    return [by_id[k] for k in order]


def _annotate_sample(snap: dict, *, phase: str, capture_offset_s: float, scene_hash: str) -> dict:
    return {
        **snap,
        "phase": phase,
        "captureOffsetS": capture_offset_s,
        "sceneHash": scene_hash,
        "movies": _per_movie_obs(snap),
    }


def _score_neighbours_retained_clocks(
    samples: list[dict], restart_keys: list[str], min_hash: int
) -> dict:
    """Neighbour (non-restart-target) movies must not be disrupted by the restart.

    movie2 (WA0125) plays alongside the untitled.mov (movie1) restart on slide 3
    but may itself start fresh there — a near-zero first observation is not a
    disruption. Only a backward clock jump (a reset caused by our own
    retirement leaking onto the wrong key) fails this check. Informational —
    does not gate deliberateRestart2to3.
    """
    neighbour_keys = sorted(
        {
            m.get("key")
            for s in samples
            for m in (s.get("movies") or [])
            if m.get("key") and m.get("key") not in restart_keys
        }
    )
    per_key: dict[str, dict] = {}
    for key in neighbour_keys:
        obs = []
        for s in samples:
            hn = _hash_num(s.get("sceneHash"))
            if hn is None or hn < min_hash:
                continue
            for m in s.get("movies") or []:
                if m.get("key") == key and m.get("currentTime") is not None:
                    obs.append(float(m["currentTime"]))
        if len(obs) < 2:
            per_key[key] = {"ok": False, "reason": "insufficient obs", "n": len(obs)}
            continue
        max_backward_jump = max(
            (obs[i] - obs[i + 1] for i in range(len(obs) - 1)), default=0.0
        )
        not_reset = max_backward_jump <= 0.35
        per_key[key] = {
            "ok": bool(not_reset),
            "n": len(obs),
            "first": obs[0],
            "last": obs[-1],
            "min": min(obs),
            "max": max(obs),
            "maxBackwardJump": max_backward_jump,
        }
    ok = bool(per_key) and all(v["ok"] for v in per_key.values())
    return {"ok": ok, "keys": neighbour_keys, "perKey": per_key}


def _score_canvas_identical(frame_paths: list[Path]) -> dict:
    if len(frame_paths) < 2:
        return {"ok": False, "n": len(frame_paths)}
    arrs = [np.array(Image.open(p)) for p in frame_paths]
    identical = all(np.array_equal(arrs[0], a) for a in arrs[1:])
    return {
        "allFramesIdentical": identical,
        "n": len(arrs),
        "firstLastMae": _mae_rgb(arrs[0], arrs[-1]),
    }


async def _advance_until_hash_changes(chrome: ChromeCdp, max_steps: int = 8) -> list[str]:
    """Drain builds until hash changes at least once (legacy helper)."""
    return await _advance_until_hash_at_least(chrome, min_hash=None, max_steps=max_steps)


async def _advance_until_hash_at_least(
    chrome: ChromeCdp, *, min_hash: int | None, max_steps: int = 16
) -> list[str]:
    """Keep advancing until hash number >= min_hash (or any change if min_hash is None)."""
    log, _ = await _advance_until_hash_at_least_sampling(
        chrome, min_hash=min_hash, max_steps=max_steps, sample=False
    )
    return log


async def _advance_until_hash_at_least_sampling(
    chrome: ChromeCdp,
    *,
    min_hash: int | None,
    max_steps: int = 16,
    click_wall: float | None = None,
    sample_hz: float = 10.0,
    sample: bool = True,
) -> tuple[list[str], list[dict]]:
    """Advance builds while densely sampling media (scene + per-movie).

    Sampling continues *through* each advance wait so a near-zero Start Movie
    clock is not missed between drain steps.
    """
    log: list[str] = []
    samples: list[dict] = []
    if click_wall is None:
        click_wall = time.monotonic()
    dt = 1.0 / max(1.0, sample_hz)

    async def _snap(phase: str) -> dict:
        h = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        media = await _media_snapshot_with_pool(chrome) if sample else {"videos": [], "preservePool": []}
        row = _annotate_sample(
            media,
            phase=phase,
            capture_offset_s=time.monotonic() - click_wall,
            scene_hash=h,
        )
        if sample:
            samples.append(row)
        return row

    for step in range(max_steps):
        row = await _snap(f"drain-pre-{step}")
        n = _hash_num(row["sceneHash"])
        if min_hash is not None and n is not None and n >= min_hash:
            log.append(f"already:{row['sceneHash']}")
            return log, samples

        hash0 = row["sceneHash"]
        prefer = "arrow" if step % 2 == 0 else "space"
        # Try arrow/space/click in turn while sampling continuously during the wait.
        order = ["arrow", "space", "click"] if prefer == "arrow" else ["space", "arrow", "click"]
        changed = None
        for name in order:
            if name == "arrow":
                await chrome.key("ArrowRight", "ArrowRight", 39)
            elif name == "space":
                await chrome.key(" ", "Space", 32)
            else:
                await chrome.click_center()
            deadline = time.monotonic() + 4.0
            next_sample = time.monotonic()
            while time.monotonic() < deadline:
                now = time.monotonic()
                if sample and now >= next_sample:
                    await _snap(f"drain-wait-{step}-{name}")
                    next_sample = now + dt
                h = _norm_hash(
                    await chrome.evaluate(
                        "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
                    )
                )
                if h != hash0:
                    changed = f"{name}:{hash0}->{h}"
                    break
                await asyncio.sleep(0.02)
            if changed:
                break
        if changed is None:
            changed = f"none:{hash0}->{hash0}"
        log.append(changed)
        await _snap(f"drain-post-{step}")
        nn = _hash_num(changed.split("->")[-1] if "->" in changed else "")
        if changed.startswith("none:"):
            # One stuck step is inconclusive; try alternate input next loop.
            continue
        if min_hash is None:
            if nn is not None and n is not None and nn != n:
                return log, samples
        elif nn is not None and nn >= min_hash:
            return log, samples
    return log, samples


def _caps(samples: list[dict]) -> list[float | None]:
    return [s.get("captureOffsetS") for s in samples]


async def _media_snapshot_with_pool(chrome: ChromeCdp) -> dict:
    snap = await _media_snapshot(chrome) or {}
    pool = await chrome.evaluate(
        "window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.snapshot "
        "? window.__OBED_P2_PRESERVE__.snapshot() : []"
    )
    snap = dict(snap)
    snap["preservePool"] = pool or []
    # Prefer live DOM videos; fall back to pooled detached decoders for MM gaps.
    # Also merge pool clocks when DOM videos are frozen/missing.
    dom = list(snap.get("videos") or [])
    if pool:
        pool_vids = [
            {
                "src": p.get("key") or "",
                "currentTime": p.get("currentTime"),
                "paused": p.get("paused"),
                "readyState": p.get("readyState"),
                "decoderId": p.get("elId"),
                "fromPreservePool": True,
            }
            for p in pool
        ]
        if not dom:
            snap["videos"] = pool_vids
        else:
            # Keep DOM entries but ensure we can see advancing pool clocks too.
            snap["videos"] = dom + pool_vids
        snap["videoCount"] = len(snap["videos"])
    return snap


def _resolve_target_media(media: dict, decoder_id: object) -> dict | None:
    """Decoded width / currentTime for a decoderId, across native videos + pool."""
    if decoder_id is None:
        return None
    for v in media.get("videos") or []:
        if v.get("decoderId") == decoder_id:
            w = v.get("w") if v.get("w") is not None else v.get("videoWidth")
            return {"w": w, "currentTime": v.get("currentTime")}
    for p in media.get("preservePool") or []:
        if p.get("elId") == decoder_id:
            return {"w": p.get("videoWidth"), "currentTime": p.get("currentTime")}
    return None


async def _footprint_target(chrome: ChromeCdp, media: dict, roi: tuple[int, int, int, int]) -> dict:
    """Decoder that currently owns the movie footprint (active texture-feed
    canvas first, else the positioned <video> overlapping it most) — stable
    across the Magic Move cut so score_motion_across_flip's crossing-decoder
    check reflects the actual target movie, not whichever video happened
    to be first in the DOM.
    """
    x, y, w, h = roi
    owner = await chrome.evaluate(
        "window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.footprintOwnerDecoderId "
        f"? window.__OBED_P2_PRESERVE__.footprintOwnerDecoderId({{x:{x}, y:{y}, w:{w}, h:{h}}}) "
        ": {elId: null, key: null, via: 'unavailable'}"
    ) or {"elId": None, "key": None, "via": "unavailable"}
    decoder_id = owner.get("elId")
    context_type = owner.get("contextType")  # passively recorded by PRESERVE_SCRIPT (Stream A)
    resolved = _resolve_target_media(media, decoder_id)
    if resolved is not None:
        return {
            "decoderId": decoder_id,
            "w": resolved.get("w"),
            "movieKey": owner.get("key"),
            "contextType": context_type,
            "via": owner.get("via"),
        }
    # Footprint owner unresolved: fail the gate, never a ready-video fallback
    # (Contract 2 — a first-decoded fallback would bind some OTHER movie).
    return {
        "decoderId": None,
        "w": None,
        "movieKey": None,
        "contextType": context_type,
        "via": owner.get("via", "none"),
    }


def _owner_ambiguous(before: dict, after: dict) -> bool:
    """A footprint frame is handoff/ambiguous when EITHER screenshot-bracket endpoint
    resolved ownership as `ambiguous` (two decoders both cover the footprint), OR the
    two endpoints resolved to DIFFERENT non-null owners (the owner changed mid-capture
    — a handoff in flight). Such a frame must never be tolerated as a mere absence gap
    by the after-window null tolerance."""
    if before.get("via") == "ambiguous" or after.get("via") == "ambiguous":
        return True
    b, a = before.get("decoderId"), after.get("decoderId")
    return bool(b is not None and a is not None and b != a)


async def _pre_advance_frames(
    chrome: ChromeCdp, run_dir: Path, prefix: str, click_wall: float, n: int, gap_s: float
) -> list[dict]:
    """Capture composed frames BEFORE firing the advance.

    score_motion_across_flip needs a genuine before-flip segment; without this,
    dense capture starting only after the hash has already changed makes
    flipIndex==0 with no pre-flip pairs to score.
    """
    frames: list[dict] = []
    for i in range(n):
        media = await _media_snapshot_with_pool(chrome)
        # Bracket the screenshot: read sceneHash + footprint owner both before AND
        # after so a flip mid-capture can be detected instead of silently mislabeling
        # a post-flip frame with pre-flip (or vice versa) identity metadata.
        scene_hash_before = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        target_before = await _footprint_target(chrome, media, MOVIE_ROI)
        capture_wall = time.monotonic()
        arr = await chrome.screenshot()
        name = f"{prefix}-pre{i:02d}.png"
        Image.fromarray(arr).save(run_dir / name)
        scene_hash_after = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        target_after = await _footprint_target(chrome, media, MOVIE_ROI)
        bracket_consistent = bool(
            scene_hash_before == scene_hash_after
            and target_before.get("decoderId") == target_after.get("decoderId")
            and target_before.get("movieKey") == target_after.get("movieKey")
        )
        frames.append(
            {
                "name": name,
                "i": -(n - i),
                "empty": _score_empty(arr),
                "sceneHash": scene_hash_after,
                "captureOffsetS": capture_wall - click_wall,
                "decoderId": target_after.get("decoderId") if bracket_consistent else None,
                "w": target_after.get("w") if bracket_consistent else None,
                "movieKey": target_after.get("movieKey") if bracket_consistent else None,
                "contextType": target_after.get("contextType") if bracket_consistent else None,
                "targetVia": target_after.get("via"),
                "ownerAmbiguous": _owner_ambiguous(target_before, target_after),
                "bracketConsistent": bracket_consistent,
                "index": _decode_index_patch(arr),
            }
        )
        if gap_s > 0:
            await asyncio.sleep(gap_s)
    return frames


async def _dense_after_click(
    chrome: ChromeCdp, run_dir: Path, prefix: str, click_wall: float | None = None,
    *, sample_decoder: bool = False,
) -> tuple[list[dict], list[dict], list[dict]]:
    samples: list[dict] = []
    frames: list[dict] = []
    decoder_frames: list[dict] = []
    # Anchor dense window to *now* so a prior wait cannot collapse all frames.
    start = time.monotonic()
    if click_wall is None:
        click_wall = start
    n = int((TRANS_S + POST_SETTLE_S) * DENSE_FPS)
    dt = 1.0 / DENSE_FPS
    for i in range(n):
        target = start + (i + 1) * dt
        while time.monotonic() < target:
            await asyncio.sleep(0.001)
        capture_wall = time.monotonic()
        media = await _media_snapshot_with_pool(chrome)
        do_shot = i % 2 == 0 or i == n - 1
        if do_shot:
            # Bracket the screenshot (see _pre_advance_frames) so a flip mid-capture
            # is detected rather than silently mislabeling the frame.
            scene_hash_before = _norm_hash(
                await chrome.evaluate(
                    "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
                )
            )
            target_before = await _footprint_target(chrome, media, MOVIE_ROI)
            arr = await chrome.screenshot()
            name = f"{prefix}-t{i:03d}.png"
            Image.fromarray(arr).save(run_dir / name)
            scene_hash_after = _norm_hash(
                await chrome.evaluate(
                    "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
                )
            )
            target_after = await _footprint_target(chrome, media, MOVIE_ROI)
            bracket_consistent = bool(
                scene_hash_before == scene_hash_after
                and target_before.get("decoderId") == target_after.get("decoderId")
                and target_before.get("movieKey") == target_after.get("movieKey")
            )
            frames.append(
                {
                    "name": name,
                    "i": i,
                    "empty": _score_empty(arr),
                    "sceneHash": scene_hash_after,
                    "captureOffsetS": capture_wall - click_wall,
                    "decoderId": target_after.get("decoderId") if bracket_consistent else None,
                    "w": target_after.get("w") if bracket_consistent else None,
                    "movieKey": target_after.get("movieKey") if bracket_consistent else None,
                    "contextType": target_after.get("contextType") if bracket_consistent else None,
                    "targetVia": target_after.get("via"),
                    "ownerAmbiguous": _owner_ambiguous(target_before, target_after),
                    "bracketConsistent": bracket_consistent,
                    "index": _decode_index_patch(arr),
                }
            )
        if sample_decoder and (i % 8 == 0 or i == n - 1) and len(decoder_frames) < 6:
            el_id = None
            pool = media.get("preservePool") or []
            if pool:
                el_id = pool[0].get("elId")
            else:
                for v in media.get("videos") or []:
                    if v.get("decoderId") is not None:
                        el_id = v.get("decoderId")
                        break
            fr = None
            if el_id is not None:
                fr = await chrome.evaluate(
                    f"window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.sampleFrame"
                    f" ? window.__OBED_P2_PRESERVE__.sampleFrame({int(el_id)}) : null"
                )
            if not (fr and fr.get("ok") and fr.get("dataURL")):
                fr = await chrome.evaluate(
                    """(() => {
                      const p = window.__OBED_P2_PRESERVE__;
                      const vids = Array.from(document.querySelectorAll('video'));
                      if (p && p.sampleFrame) {
                        for (const v of vids) {
                          if (v.__obedElId == null) continue;
                          const out = p.sampleFrame(v.__obedElId);
                          if (out && out.ok && out.dataURL) return out;
                        }
                      }
                      for (const v of vids) {
                        const real = v.__obedFacadeFor || v;
                        if (!(real && real.videoWidth > 0)) continue;
                        try {
                          const c = document.createElement('canvas');
                          const w = Math.min(320, real.videoWidth);
                          const h = Math.round(w * real.videoHeight / real.videoWidth);
                          c.width = w; c.height = h;
                          c.getContext('2d').drawImage(real, 0, 0, w, h);
                          return {
                            ok: true,
                            elId: real.__obedElId || null,
                            currentTime: real.currentTime,
                            width: w,
                            height: h,
                            dataURL: c.toDataURL('image/jpeg', 0.7),
                            via: 'direct-draw',
                            videoCount: vids.length
                          };
                        } catch (e) {
                          return {
                            ok: false,
                            reason: 'direct-draw-failed',
                            message: String(e && e.message || e)
                          };
                        }
                      }
                      return {
                        ok: false,
                        reason: 'no-video-pixels',
                        videoCount: vids.length,
                        preserve: !!p,
                        snap: p && p.snapshot ? p.snapshot() : [],
                        firstFail: (function(){
                          const snap = p && p.snapshot ? p.snapshot() : [];
                          if (!snap.length || !p || !p.sampleFrame) return null;
                          return p.sampleFrame(snap[0].elId);
                        })()
                      };
                    })()"""
                )
            if fr and fr.get("ok") and fr.get("dataURL"):
                raw = fr["dataURL"].split(",", 1)[-1]
                img = Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
                path = run_dir / f"decoder-t{len([d for d in decoder_frames if d.get('path')]):02d}.jpg"
                img.save(path)
                decoder_frames.append(
                    {
                        "path": str(path),
                        "currentTime": fr.get("currentTime"),
                        "elId": fr.get("elId", el_id),
                        "i": i,
                        "via": fr.get("via"),
                    }
                )
            elif fr is not None and sum(1 for d in decoder_frames if not d.get("path")) < 2:
                decoder_frames.append({"ok": False, "i": i, "detail": fr, "triedElId": el_id})
        samples.append(
            {
                **media,
                "i": i,
                "captureOffsetS": capture_wall - click_wall,
                # Normalise the media snapshot's location hash to `sceneHash` so a
                # dense sample is a valid presented-time sample (it carries `videos`
                # with rVFC presentedMediaTime; _presented_time_advances keys the
                # window off `sceneHash`).
                "sceneHash": _norm_hash(media.get("hash")),
            }
        )
    return samples, frames, decoder_frames


async def _footprint_owner_keyed(
    chrome: ChromeCdp, rect: tuple[float, float, float, float], key: str
) -> dict:
    """Resolve the footprint owner at an arbitrary (moving) rect, keyed to a movie
    so the fixed footprint table need not classify it. Excludes hidden siblings
    (PRESERVE's isCompositing), so the suppressed 3->4 restart element and the
    retiring right-side WA0125 the grown box overlaps cannot tie."""
    x, y, w, h = (int(round(v)) for v in rect)
    owner = await chrome.evaluate(
        "window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.footprintOwnerDecoderId "
        f"? window.__OBED_P2_PRESERVE__.footprintOwnerDecoderId({{x:{x}, y:{y}, w:{w}, h:{h}, key:'{key}'}}) "
        ": {elId: null, key: null, via: 'unavailable'}"
    ) or {"elId": None, "key": None, "via": "unavailable"}
    return owner


async def _bind_footprint_owner(
    chrome: ChromeCdp, key: str, hint_rect: tuple[float, float, float, float]
) -> str | None:
    """Resolve the footprint owner ONCE, while it still sits on the pre-move
    (slide-3) rect, and bind its `__obedElId` (review Blocker 2a: mid-move the
    video has already translated away from any modelled hint, so re-resolving
    ownership by IoU during the move is unreliable). The bound id is read
    directly for the rest of the capture -- never re-derived."""
    owner = await _footprint_owner_keyed(chrome, hint_rect, key)
    return owner.get("elId")


async def _read_bound_owner_rect(chrome: ChromeCdp, el_id: str) -> dict | None:
    """Live `getBoundingClientRect()` of the bound owner, read directly by
    `__obedElId` -- no IoU, no hint. `None` if disconnected or laid out to zero
    size."""
    rect = await chrome.evaluate(
        "(function(){var vids=document.querySelectorAll('video');"
        f"var want={json.dumps(el_id)};"
        "for(var i=0;i<vids.length;i++){if(vids[i].__obedElId===want){"
        "var r=vids[i].getBoundingClientRect();"
        "if(r.width>1&&r.height>1){return {x:r.left,y:r.top,w:r.width,h:r.height};}"
        "return null;}}"
        "return null;})()"
    )
    if not rect:
        return None
    return {"x": rect["x"], "y": rect["y"], "w": rect["w"], "h": rect["h"]}


def _couple_owner_rect(before: dict | None, after: dict | None) -> dict:
    """Couple rect + pixels (review Blocker 2b): a sample is `measured` only when
    BOTH a before- and an after-screenshot rect read exist and agree within
    `FOOTPRINT_COUPLE_TOL_PX` -- otherwise `unstable` (still decoded, off the
    BEFORE rect, for forensics, but never counted in an at-cut run and counted
    as a failure by `allInHoldMeasured`). BEFORE is used for the ROI because the
    screenshot begins compositing from that state; using AFTER would attribute
    any post-capture repositioning to the decoded frame."""
    if before is None and after is None:
        return {"source": "none"}
    if before is None or after is None:
        return {"source": "unstable", "before": before, "after": after}
    if (
        abs(before["x"] - after["x"]) <= FOOTPRINT_COUPLE_TOL_PX
        and abs(before["y"] - after["y"]) <= FOOTPRINT_COUPLE_TOL_PX
        and abs(before["w"] - after["w"]) <= FOOTPRINT_COUPLE_TOL_PX
        and abs(before["h"] - after["h"]) <= FOOTPRINT_COUPLE_TOL_PX
    ):
        return {**before, "source": "measured"}
    return {"source": "unstable", "before": before, "after": after}


def _moving_index_run_at_cut(index_samples: list[dict]) -> tuple[dict, bool]:
    """`flip_index` is identified on the FULL ordered sample list (the first
    sample whose hash reaches slide 4), not on the measured-only subsequence
    (review Blocker 2c: scoring the measured-only subsequence made "flip_index"
    the first LATE resolvable sample, not the real cut). The flip sample and the
    FREEZE_MIN_AFTER samples after it must all be `measured`, else the run is not
    trustworthy for an at-cut verdict -- returns `flipWindowDecodable=False`,
    which the caller treats as INCONCLUSIVE."""
    flip_index_full = next(
        (
            i for i, s in enumerate(index_samples)
            if (_hash_num(s.get("sceneHash")) or -1) >= SLIDE4_MIN_HASH
        ),
        None,
    )
    if flip_index_full is None:
        return {"ok": False, "reason": "no sample reached slide 4", "flipIndex": None}, False
    lo = max(0, flip_index_full - 1)
    hi = min(len(index_samples) - 1, flip_index_full + FREEZE_MIN_AFTER)
    window_decodable = all(
        index_samples[i].get("footprintSource") == "measured" for i in range(lo, hi + 1)
    )
    if not window_decodable:
        return (
            {"ok": False, "reason": "flip window not decodable", "flipIndex": flip_index_full},
            False,
        )
    measured = [s for s in index_samples if s.get("footprintSource") == "measured"]
    flip_index_measured = next(
        i for i, s in enumerate(measured) if s is index_samples[flip_index_full]
    )
    result = score_composited_index_run(measured, flip_index=flip_index_measured)
    return result, True


async def _advance_to_slide4_capture(
    chrome: ChromeCdp,
    run_dir: Path,
    prefix: str,
    click_wall: float,
    *,
    bound_owner_id: str | None = None,
    release_cb=None,
) -> tuple[list[dict], list[dict], list[dict], str, dict]:
    """Advance slide 3 -> slide 4 through the moving Magic Move while densely
    sampling the footprint owner at the INTERPOLATED footprint (footprint_at,
    keyed movie1), the rVFC media clocks, and the composited counter decoded at
    the MEASURED footprint (plan section 1, "measure, don't model").

    `bound_owner_id` -- the footprint owner's `__obedElId`, resolved ONCE before
    the move (review Blocker 2a) -- is read directly every sample via
    `_read_bound_owner_rect`, immediately before AND immediately after the
    screenshot; `_couple_owner_rect` requires both reads to agree within
    `FOOTPRINT_COUPLE_TOL_PX` for `index_samples[i]["footprintSource"] ==
    "measured"` (else `"unstable"`; `"modelled"`/`"none"` as before when no
    owner is bound at all).

    `release_cb`, if given, is awaited exactly once -- as soon as the at-cut hold
    window (the flip plus >= FREEZE_MIN_AFTER MEASURED samples after it) closes,
    BEFORE any later sample in this same loop is captured (review Blocker 3).
    Positive arms pass `release_cb=None` and simply have no cover, so ALL THREE
    arms follow the identical capture schedule -- `settledIndexProgressionOk` and
    `footprintFullyLive` are computed only from samples captured after this point
    in every arm, making them comparable.

    Returns (owner_samples, media_samples, index_samples, final_hash,
    capture_meta) where capture_meta = {"lastAtCutOffsetS", "releaseOffsetS",
    "releaseStatus"}.
    """
    owner_samples: list[dict] = []
    media_samples: list[dict] = []
    index_samples: list[dict] = []
    fps = DENSE_FPS
    dt = 1.0 / fps
    n = int((TRANS_S + POST_SETTLE_S + 3.0) * fps)
    start = time.monotonic()
    flip_offset: float | None = None
    last_adv = -10.0
    flip_seen = False
    post_flip_measured = 0
    last_at_cut_offset_s: float | None = None
    release_offset_s: float | None = None
    release_status: dict | None = None
    offset = 0.0
    for i in range(n):
        target = start + (i + 1) * dt
        while time.monotonic() < target:
            await asyncio.sleep(0.001)
        capture_wall = time.monotonic()
        offset = capture_wall - click_wall
        scene_hash = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        hn = _hash_num(scene_hash)
        if i % 8 == 0:
            await _ensure_videos_playing(chrome)
        if hn is not None and hn < SLIDE4_MIN_HASH and (offset - last_adv) > 0.9:
            await chrome.key("ArrowRight", "ArrowRight", 39)
            last_adv = offset
        reached4 = hn is not None and hn >= SLIDE4_MIN_HASH
        if reached4 and flip_offset is None:
            flip_offset = offset
        if reached4:
            progress = (
                max(0.0, min(1.0, (offset - flip_offset) / TRANS_S))
                if flip_offset is not None else 1.0
            )
        else:
            progress = 0.0
        fp = footprint_at(progress, SLIDE3_MOVIE_RECT, SLIDE4_MOVIE_RECT)
        media = await _media_snapshot_with_pool(chrome)
        owner_before = await _footprint_owner_keyed(chrome, fp, MOVIE1_KEY)
        rect_before = (
            await _read_bound_owner_rect(chrome, bound_owner_id)
            if bound_owner_id is not None else None
        )
        arr = await chrome.screenshot()
        rect_after = (
            await _read_bound_owner_rect(chrome, bound_owner_id)
            if bound_owner_id is not None else None
        )
        if i % 2 == 0 or i == n - 1:
            Image.fromarray(arr).save(run_dir / f"{prefix}-t{i:03d}.png")
        owner_after = await _footprint_owner_keyed(chrome, fp, MOVIE1_KEY)
        ambiguous = (
            owner_before.get("via") == "ambiguous"
            or owner_after.get("via") == "ambiguous"
            or (
                owner_before.get("elId") is not None
                and owner_after.get("elId") is not None
                and owner_before.get("elId") != owner_after.get("elId")
            )
        )
        owner_samples.append(
            {
                "sceneHash": scene_hash,
                "captureOffsetS": offset,
                "progress": round(progress, 3),
                "footprint": [round(v, 1) for v in fp],
                "decoderId": owner_after.get("elId"),
                "ownerAmbiguous": ambiguous,
                "via": owner_after.get("via"),
            }
        )
        media_samples.append({**media, "sceneHash": scene_hash, "captureOffsetS": offset})
        measured = _couple_owner_rect(rect_before, rect_after)
        footprint_source = measured.get("source")
        if footprint_source == "measured":
            roi_rect = (measured["x"], measured["y"], measured["w"], measured["h"])
        elif footprint_source == "unstable":
            fallback = measured.get("before") or measured.get("after")
            roi_rect = (
                (fallback["x"], fallback["y"], fallback["w"], fallback["h"])
                if fallback else fp
            )
        elif fp is not None:
            footprint_source = "modelled"
            roi_rect = fp
        else:
            footprint_source = "none"
            roi_rect = None
        index_samples.append(
            {
                "index": _decode_index_patch(arr, index_patch_roi_for(roi_rect)) if roi_rect else None,
                "sceneHash": scene_hash,
                "captureOffsetS": offset,
                "progress": round(progress, 3),
                "footprintSource": footprint_source,
                "measuredRect": (
                    {"x": measured["x"], "y": measured["y"], "w": measured["w"], "h": measured["h"]}
                    if footprint_source == "measured" else None
                ),
            }
        )
        if not flip_seen and reached4:
            flip_seen = True
        if flip_seen and footprint_source == "measured":
            post_flip_measured += 1
        if (
            release_cb is not None
            and release_offset_s is None
            and flip_seen
            and post_flip_measured >= FREEZE_MIN_AFTER
        ):
            last_at_cut_offset_s = offset
            release_offset_s = time.monotonic() - click_wall
            release_status = await release_cb()
    if release_cb is not None and release_offset_s is None:
        # The at-cut window never closed (e.g. the flip never resolved to a
        # measured sample) -- release anyway, before returning, so a stuck cover
        # cannot red footprintFullyLive for the wrong reason.
        last_at_cut_offset_s = offset
        release_offset_s = time.monotonic() - click_wall
        release_status = await release_cb()
    final_hash = _norm_hash(
        await chrome.evaluate(
            "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
        )
    )
    capture_meta = {
        "lastAtCutOffsetS": last_at_cut_offset_s,
        "releaseOffsetS": release_offset_s,
        "releaseStatus": release_status,
    }
    return owner_samples, media_samples, index_samples, final_hash, capture_meta


async def _capture_3to4_snapshot(
    chrome: ChromeCdp,
    run_dir: Path,
    prefix: str,
    wait_profile: dict,
    *,
    inject_null: bool,
) -> dict:
    """Capture + score ONE 3->4 moving Magic Move boundary and return a comparable
    findings snapshot for the A-B-A freeze bracket. Replaces `_capture_1to2_snapshot`
    (dead: the 1->2 carry is refused by the derived plan, so there is no carried
    movie to freeze there; 3->4 still carries -- see the plan).

    Drains to hash `#7` == SLIDE4_MIN_HASH-1 (the last slide-3 build; arming at #6
    would fire on the 6->7 build). When `inject_null`, installs + arms the Arm-A
    composited-freeze control (`window.__OBED_NULL_CTRL__`) there, BEFORE the 3->4
    advance -- it fires on a MEASURED departure of the bound owner's own rect from
    its rect at arm time (the real move start), with a `#7`->`#8` hash-poll
    fallback, holds a partial stale cover tracking the MEASURED (never modelled)
    owner rect, and releases mid-capture as soon as the at-cut hold window closes
    -- BEFORE the settled-progression samples and the visible-content burst
    (review Blocker 3; a cover left in place through those would red
    `footprintFullyLive` for the wrong reason).
    """
    await asyncio.sleep(wait_profile["clickDelayS"])
    hash_now = _norm_hash(
        await chrome.evaluate(
            "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
        )
    )
    # As in the retired 1->2 capture: on a re-navigated same-session boot the route
    # hash can transiently read '' even after boot settles. Wait for a clean
    # #<digits> before trusting it as a real boundary anchor.
    _h_deadline = time.monotonic() + 3.0
    while _strict_hash_num(hash_now) is None and time.monotonic() < _h_deadline:
        await asyncio.sleep(0.1)
        await _ensure_videos_playing(chrome)
        hash_now = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )

    # Drain slide 1/2/3 builds to #7 == SLIDE4_MIN_HASH - 1 (the last slide-3
    # build), so arm() below sees the genuine pre-move boundary, not an earlier one.
    arm_hash = SLIDE4_MIN_HASH - 1
    arm_hash_str = f"#{arm_hash}"
    drain_deadline = time.monotonic() + 8.0
    while (_hash_num(hash_now) or -1) < arm_hash and time.monotonic() < drain_deadline:
        await chrome.key("ArrowRight", "ArrowRight", 39)
        await asyncio.sleep(0.3)
        await _ensure_videos_playing(chrome)
        hash_now = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
    hash3 = hash_now

    perf_now_at_click: float | None = None
    arm_result: dict | None = None
    if inject_null:
        # Review Blocker 1: `arm()` normalises the hash internally now, but a
        # pre-arm mismatch (the drain loop overshot, or hash3 is not the clean
        # "#7" the arm-time assert expects) must not silently arm at the wrong
        # boundary -- treat it as an error, same as an in-JS mismatch would be.
        if _norm_hash(hash3) != arm_hash_str:
            arm_result = {
                "ok": False,
                "error": f"pre-arm-hash-mismatch:expected={arm_hash_str},actual={_norm_hash(hash3)}",
            }
        else:
            await chrome.evaluate(NULL_CONTROL_JS)
            x, y, w, h = SLIDE3_MOVIE_RECT
            arm_result = await chrome.evaluate(
                f"window.__OBED_NULL_CTRL__.arm({{x:{x}, y:{y}, w:{w}, h:{h}, key:{json.dumps(MOVIE1_KEY)}}}, "
                f"{json.dumps(arm_hash_str)})"
            )
            perf_now_at_click = await chrome.evaluate("performance.now()")

    # Bind the ROI footprint owner ONCE before the move, while it still sits on
    # the slide-3 rect (review Blocker 2a) -- independent of the null control's
    # OWN binding above (JS-side, for cover tracking); both resolve the same
    # element in practice, each bound once for its own purpose.
    bound_owner_id: str | None = None
    if (_hash_num(hash3) or -1) < SLIDE4_MIN_HASH:
        bound_owner_id = await _bind_footprint_owner(chrome, MOVIE1_KEY, SLIDE3_MOVIE_RECT)

    release_meta: dict = {"status": None}

    async def _release_cb() -> dict | None:
        status = await chrome.evaluate("window.__OBED_NULL_CTRL__.release()")
        release_meta["status"] = status
        return status

    click_wall = time.monotonic()
    if (_hash_num(hash3) or -1) < SLIDE4_MIN_HASH:
        await chrome.key("ArrowRight", "ArrowRight", 39)
    (
        owner_samples,
        media_samples,
        index_samples,
        hash4,
        capture_meta,
    ) = await _advance_to_slide4_capture(
        chrome, run_dir, prefix, click_wall,
        bound_owner_id=bound_owner_id,
        release_cb=_release_cb if inject_null else None,
    )

    last_at_cut_offset_s = capture_meta.get("lastAtCutOffsetS")
    release_offset_s = capture_meta.get("releaseOffsetS")
    null_status: dict | None = release_meta.get("status") if inject_null else None
    if inject_null and null_status is None:
        # release_cb never fired for some reason -- fall back to an explicit
        # status() read so the hold-fired guard below can still see it.
        null_status = await chrome.evaluate("window.__OBED_NULL_CTRL__.status()")

    # Settled slide-4 visible-content burst -- collected AFTER _advance_to_
    # slide4_capture returns, i.e. strictly after the mid-loop release above.
    burst_start_wall = time.monotonic()
    slide4_burst: list[np.ndarray] = []
    for off_ms in BURST_OFFSETS_MS:
        gap = (burst_start_wall + off_ms / 1000.0) - time.monotonic()
        if gap > 0:
            await asyncio.sleep(gap)
        shot = await chrome.screenshot()
        slide4_burst.append(np.asarray(shot)[:, :, :3])
        Image.fromarray(shot).save(run_dir / f"{prefix}-burst-t{off_ms:04d}.png")
    footprint_live = footprintFullyLive(slide4_burst)

    # Post-release only (review Blocker 3): a sample captured before the
    # mid-loop release is still under the cover in B, so it must not feed the
    # settled progression in ANY arm (A1/A2 have no cover, but follow the
    # identical release-offset gate so all three schedules stay comparable).
    settled_samples = [
        s for s in index_samples
        if (_hash_num(s.get("sceneHash")) or -1) >= SLIDE4_MIN_HASH
        and float(s.get("progress") or 0.0) >= 0.98
        and (release_offset_s is None or (s.get("captureOffsetS") or -1.0) > release_offset_s)
    ]
    settled_index_seq = [s.get("index") for s in settled_samples]
    settled_index_progression = score_index_progression(settled_index_seq)
    first_settled_offset_s = min(
        (s.get("captureOffsetS") for s in settled_samples if s.get("captureOffsetS") is not None),
        default=None,
    )

    moving_index_run_at_cut, flip_window_decodable = _moving_index_run_at_cut(index_samples)

    pre_flip_owners = [
        s for s in owner_samples if (_hash_num(s.get("sceneHash")) or -1) < SLIDE4_MIN_HASH
    ]
    slide3_movie_decoder = pre_flip_owners[-1].get("decoderId") if pre_flip_owners else None
    moving_continuity = movingContinuity3to4(
        owner_samples, media_samples, slide3_movie_decoder, hash3, hash4, SLIDE4_MIN_HASH,
    )
    player_build_errors = await chrome.evaluate(
        "(window.__OBED_P2_PRESERVE__ ? window.__OBED_P2_PRESERVE__.events"
        ".filter(function (e) { return e.kind === 'player-build-error'; }) : [])"
    ) or []
    bridge_events = await chrome.evaluate(
        "window.__OBED_P2_PRESERVE__ ? window.__OBED_P2_PRESERVE__.events"
        ".filter(function(e){return e.kind==='bridge-3to4';}).slice(-6) : []"
    ) or []
    bridge_engaged = bool(bridge_events)

    burst_start_offset_s = burst_start_wall - click_wall

    composited_pass = bool(
        moving_continuity.get("ok", False)
        and moving_index_run_at_cut.get("ok", False)
        and footprint_live.get("ok", False)
        and not player_build_errors
    )
    return {
        "hash3": hash3,
        "hash4": hash4,
        "armHash": arm_hash_str,
        "armResult": arm_result,
        "movingIndexRunAtCut": moving_index_run_at_cut,
        "flipWindowDecodable": flip_window_decodable,
        "settledIndexProgression": settled_index_progression,
        "movingContinuity3to4": moving_continuity,
        "footprintFullyLive": footprint_live,
        "continueThroughMovingMagicMove3to4Pass": composited_pass,
        "indexSequence": [s.get("index") for s in index_samples],
        "footprintSources": [s.get("footprintSource") for s in index_samples],
        "captureOffsets": [s.get("captureOffsetS") for s in index_samples],
        "ownerSamples": owner_samples,
        "ownerDecoderId": slide3_movie_decoder,
        "playerBuildErrors": player_build_errors,
        "bridgeEngaged": bridge_engaged,
        "bridgeEvents": bridge_events,
        "nullControl": null_status,
        "perfNowAtClick": perf_now_at_click,
        "lastAtCutHoldOffsetS": last_at_cut_offset_s,
        "releaseOffsetS": release_offset_s,
        "firstSettledOffsetS": first_settled_offset_s,
        "burstStartOffsetS": burst_start_offset_s,
    }


# Sub-verdicts that MUST be invariant across A1/B/A2 (the freeze must change ONLY
# the counter): decoder liveness/identity + boundary/composition on the 3->4
# moving Magic Move, none of which the partial left-cover touches.
# `movingIndexRunAtCut` and `continueThroughMovingMagicMove3to4Pass` are
# DELIBERATELY excluded — they are what the freeze flips RED in B (plan
# p2_freeze_control_3to4.plan.md §4, "the slide-1/2 composition keys go").
_ISOLATION_KEYS = (
    "movingContinuityOk",
    "movingContinuityFailedEmpty",
    "rvfcMonotonicOk",
    "crossingIdentityOk",
    "stableSlide4OwnerOk",
    "boundaryValidOk",
    "footprintFullyLiveOk",
    "settledIndexProgressionOk",
    "playerBuildErrorsEmpty",
    "bridgeEngaged",
)


def _isolation_view(snap: dict) -> dict:
    """The invariant booleans extracted from a 3->4 snapshot for A1==B==A2 checks."""
    mc = snap.get("movingContinuity3to4") or {}
    return {
        "movingContinuityOk": bool(mc.get("ok")),
        "movingContinuityFailedEmpty": (mc.get("failed") == []),
        "rvfcMonotonicOk": bool((mc.get("rvfcMonotonic") or {}).get("ok")),
        "crossingIdentityOk": bool((mc.get("crossingIdentity") or {}).get("ok")),
        "stableSlide4OwnerOk": bool((mc.get("stableSlide4Owner") or {}).get("ok")),
        "boundaryValidOk": bool((mc.get("boundaryValid") or {}).get("ok")),
        "footprintFullyLiveOk": bool((snap.get("footprintFullyLive") or {}).get("ok")),
        "settledIndexProgressionOk": bool((snap.get("settledIndexProgression") or {}).get("ok")),
        "playerBuildErrorsEmpty": (snap.get("playerBuildErrors") == []),
        "bridgeEngaged": bool(snap.get("bridgeEngaged")),
    }


def _cover_tracks_footprint(raf_log: list[dict]) -> bool:
    """100% of hold frames: the logged cover rect must equal `subRect(measuredRect)`
    (NULL_CONTROL_JS's own derivation -- left-fraction of the ACTUALLY MEASURED
    owner rect read at the START of that rAF, never the modelled one, and never
    the value this frame itself just set -- review MAJOR 4) within
    `COVER_TRACK_TOL_PX`. Fails closed on a missing log or a missing rect on any
    frame."""
    if not raf_log:
        return False
    for r in raf_log:
        cover = r.get("coverRect")
        measured = r.get("measuredRect")
        if not cover or not measured:
            return False
        expected_w = float(measured.get("w") or 0.0) * COVER_LEFT_FRAC
        if (
            abs(float(cover.get("x") or 0.0) - float(measured.get("x") or 0.0)) > COVER_TRACK_TOL_PX
            or abs(float(cover.get("y") or 0.0) - float(measured.get("y") or 0.0)) > COVER_TRACK_TOL_PX
            or abs(float(cover.get("w") or 0.0) - expected_w) > COVER_TRACK_TOL_PX
            or abs(float(cover.get("h") or 0.0) - float(measured.get("h") or 0.0)) > COVER_TRACK_TOL_PX
        ):
            return False
    return True


def _score_freeze_control(a1: dict, b: dict, a2: dict) -> dict:
    """Pure A-B-A verdict for `freezeControlCaughtByCounter`, re-bracketed at the
    3->4 moving Magic Move (plan p2_freeze_control_3to4.plan.md §4; the 1->2 carry
    is refused, so there is no carried movie to freeze there).

    Passes IFF the injected freeze turns the at-cut counter RED for the right
    reason while every other sub-verdict stays green (and equal) in ALL three
    runs. Returns `{"ok", "verdict", "reason", "checks", ...}` where `verdict` is
    one of "pass" / "fail" / "inconclusive".

    A hold that never fired is INCONCLUSIVE, never PASS/FAIL: a silently-unfired
    hold makes B look exactly like a passing positive (index_run green), which
    must NOT be read as "the gate is vacuous". So holdStartedAt is checked BEFORE
    the two-tier integrity/verdict split below.
    """
    nc = b.get("nullControl") or {}
    checks: dict[str, object] = {}

    # --- Guard: the hold must have fired, and continuously (else INCONCLUSIVE) ---
    hold_started = nc.get("holdStartedAt")
    if hold_started is None or nc.get("status") not in ("holding", "released"):
        return {
            "ok": False,
            "verdict": "inconclusive",
            "reason": "freeze hold never fired (holdStartedAt is null) — cannot judge the counter",
            "nullControlStatus": nc.get("status"),
            "checks": checks,
        }
    raf_log = nc.get("rafLog") or []
    raf_ts = [r.get("t") for r in raf_log if isinstance(r.get("t"), (int, float))]
    # The gap from the move-start TRIGGER to the first hold frame is bounded too
    # (review MAJOR 5): a slow first rAF after trigger leaves the cover behind
    # the movie for that whole span, same as an inter-frame stall.
    raf_ts_from_trigger = ([hold_started] + raf_ts) if hold_started is not None else raf_ts
    max_gap_ms = max(
        (raf_ts_from_trigger[i + 1] - raf_ts_from_trigger[i] for i in range(len(raf_ts_from_trigger) - 1)),
        default=0.0,
    )
    # Unlike the retired static 1->2 footprint, the 3->4 cover TRACKS a moving
    # target every rAF (re-derived from the measured owner rect); a rAF stall
    # here leaves the cover behind the movie, not merely unobserved, so the gap
    # is DISQUALIFYING (owner decision, plan §4) rather than diagnostic-only.

    perf_click = b.get("perfNowAtClick")
    release_at = nc.get("releaseAt")
    hold_offset_s = (hold_started - perf_click) / 1000.0 if perf_click is not None else None
    release_offset_s_nc = (
        (release_at - perf_click) / 1000.0
        if (perf_click is not None and release_at is not None)
        else None
    )
    offsets = b.get("captureOffsets") or []
    seq = b.get("indexSequence") or []
    sources = b.get("footprintSources") or []
    idx = b.get("movingIndexRunAtCut") or {}
    flip_index = idx.get("flipIndex")

    in_hold_positions = [
        i for i, off in enumerate(offsets)
        if off is not None and hold_offset_s is not None and off >= hold_offset_s
        and (release_offset_s_nc is None or off <= release_offset_s_nc)
    ]
    first_in_hold = min(in_hold_positions) if in_hold_positions else None
    in_hold_decodes = [seq[i] for i in in_hold_positions if i < len(seq)]
    _decoded = [v for v in in_hold_decodes if v is not None]
    # "Frozen" = the in-hold composite decodes are CONSTANT and match the cover's ACTUAL
    # painted content (coverPatchMean) — NOT the currentTime-derived staleIndexExpected,
    # which runs ahead of the presented frame by the video's presentation lag. Tying the
    # frozen composite to the cover's own pixels is lag-immune and stronger (it proves
    # the composite shows the cover); the decoder staying live (rvfcRanThroughHold)
    # proves the counter WOULD advance if it were not covered.
    cover_mean = nc.get("coverPatchMean")
    stale_ok = bool(
        in_hold_decodes
        and len(_decoded) == len(in_hold_decodes)
        and (max(_decoded) - min(_decoded)) <= STALE_INDEX_TOL
        and cover_mean is not None
        and abs(sum(_decoded) / len(_decoded) - cover_mean) <= COVER_MATCH_TOL
    )
    all_in_hold_measured = bool(in_hold_positions) and all(
        (sources[i] if i < len(sources) else None) == "measured" for i in in_hold_positions
    )

    flip_index_present = isinstance(flip_index, int)
    flip_window_decodable = bool(b.get("flipWindowDecodable"))
    n_total = idx.get("n")
    n_after = (n_total - flip_index) if (flip_index_present and isinstance(n_total, int)) else 0

    mc = b.get("movingContinuity3to4") or {}
    stage_origin = nc.get("stageOrigin") or {}
    stage_origin_zero = bool(
        stage_origin.get("x") is not None
        and stage_origin.get("y") is not None
        and abs(float(stage_origin["x"])) <= STAGE_ORIGIN_TOL_PX
        and abs(float(stage_origin["y"])) <= STAGE_ORIGIN_TOL_PX
    )
    all_cover = bool(raf_log) and all(r.get("elementFromPointIsCover") for r in raf_log)

    # release ordering (review Blocker 3, renamed from
    # `releaseBetweenLastCaptureAndBurst` -- its meaning changed: release now
    # happens MID-CAPTURE, strictly before the first post-release settled sample
    # too, not just before the burst).
    last_at_cut = b.get("lastAtCutHoldOffsetS")
    release_offset_s = b.get("releaseOffsetS")
    first_settled = b.get("firstSettledOffsetS")
    burst_start = b.get("burstStartOffsetS")
    release_ordered = bool(
        release_offset_s is not None
        and last_at_cut is not None
        and burst_start is not None
        and last_at_cut < release_offset_s
        and (first_settled is None or release_offset_s < first_settled)
        and release_offset_s < burst_start
    )

    # --- The counter went RED for exactly the injected freeze -------------------
    checks["indexRunRed"] = idx.get("ok") is False
    checks["reasonFreezeRunAtCut"] = idx.get("reason") == "freeze run at cut"
    checks["freezeRunMargin"] = bool((idx.get("freezeRunAtCut") or 0) >= FREEZE_MIN_RUN)
    checks["noNegativeAnomaly"] = idx.get("negativeAnomaly") is False
    checks["flipIndexPresent"] = flip_index_present
    checks["flipWindowDecodable"] = flip_window_decodable
    checks["enoughAfterFlip"] = n_after >= FREEZE_MIN_AFTER

    # --- The decoder stayed LIVE through the freeze (RED isolated to counter) ----
    checks["movingContinuityOk"] = bool(mc.get("ok"))
    checks["boundDecoderIsSlide3Decoder"] = (
        nc.get("boundDecoderId") is not None
        and nc.get("boundDecoderId") == b.get("ownerDecoderId")
    )
    # De-vacuumed (review MAJOR 4): once bound-by-id, ambiguity resolution never
    # re-runs, so "no ambiguous resolution" alone is vacuous. Require ALSO that
    # the bound element (a) never reported disconnected, (b) resolved on every
    # logged rAF, and (c) stayed the SAME element id for the whole hold.
    raf_bound_ids = [r.get("boundDecoderId") for r in raf_log]
    checks["noOwnerAmbiguousInWindow"] = bool(
        nc.get("ownerAmbiguousInWindow") is False
        and nc.get("ownerDisconnectedInWindow") is False
        and bool(raf_log)
        and all(r.get("ownerResolved") for r in raf_log)
        and nc.get("boundDecoderId") is not None
        and all(bid == nc.get("boundDecoderId") for bid in raf_bound_ids)
    )
    checks["rvfcRanThroughHold"] = bool(
        (mc.get("rvfcMonotonic") or {}).get("advance") is not None
        and (mc.get("rvfcMonotonic") or {}).get("advance") >= RVFC_MIN_ADVANCE_S
    )
    checks["playerBuildErrorsEmpty"] = (b.get("playerBuildErrors") == [])
    checks["bridgeEngaged"] = bool(b.get("bridgeEngaged"))

    # --- The freeze fired correctly, at the right moment, over the right target -
    # `firedVia == "moved"` is a MEASURED departure of the bound owner's rect
    # from its armed rect (review MAJOR 5: `__obedMotion`'s mere existence is not
    # proof of move start -- keepThroughBridge can create/keep it while merely
    # SETTLED at #7). Both this and the plain advance-timing check now share the
    # same bounded window: the trigger must land within the first
    # MOVE_START_WINDOW_FRAC of the move's own duration (TRANS_S) after the
    # click, not merely after it with no ceiling.
    checks["firedAtMoveStart"] = bool(
        nc.get("firedVia") == "moved"
        and hold_offset_s is not None
        and -0.05 <= hold_offset_s <= MOVE_START_WINDOW_S
    )
    checks["firedAfterAdvance"] = bool(
        hold_offset_s is not None and -0.05 <= hold_offset_s <= MOVE_START_WINDOW_S
    )
    checks["stageOriginZero"] = stage_origin_zero
    checks["noControlError"] = nc.get("error") is None
    checks["ownerReadyAtTrigger"] = bool(
        nc.get("ownerReadyState") is not None and nc.get("ownerReadyState") >= 2
    )
    # The stale frame must come from genuine playback (currentTime >= MIN_STALE_TIME_S),
    # NOT a t~0 unrendered black frame. NB: do NOT range-check cover_mean against [16,235]
    # — that is tv-range LUMA, while cover_mean is decoded RGB (a valid dark/bright counter
    # is not "out of alphabet"). everyInHoldStale ties the composite to cover_mean (both RGB).
    checks["staleFrameFromPlayback"] = bool(
        nc.get("staleCurrentTime") is not None and nc.get("staleCurrentTime") >= MIN_STALE_TIME_S
    )
    checks["paintedOnce"] = nc.get("paintCount") == 1
    checks["coverPatchStable"] = bool(
        nc.get("coverPatchStart") is not None
        and nc.get("coverPatchStart") == nc.get("coverPatchEnd")
    )
    checks["coverHitTest100"] = all_cover
    checks["coverTracksFootprint"] = _cover_tracks_footprint(raf_log)
    checks["loopLive"] = len(raf_ts) >= 10
    checks["everyInHoldStale"] = stale_ok
    checks["allInHoldMeasured"] = all_in_hold_measured
    checks["releaseStrictlyBeforeSettleAndBurst"] = release_ordered
    checks["maxRafGapOk"] = max_gap_ms <= MAX_RAF_GAP_MS

    # --- Bracketing positives are GREEN ----------------------------------------
    checks["positivesGreen"] = bool(
        a1.get("continueThroughMovingMagicMove3to4Pass")
        and a2.get("continueThroughMovingMagicMove3to4Pass")
        and (a1.get("movingIndexRunAtCut") or {}).get("ok")
        and (a2.get("movingIndexRunAtCut") or {}).get("ok")
    )

    # --- Isolation: every invariant sub-verdict GREEN and equal across A1/B/A2 --
    # (review MAJOR 4: equality alone let all-False-but-equal pass.)
    iv_a1, iv_b, iv_a2 = _isolation_view(a1), _isolation_view(b), _isolation_view(a2)
    isolation_diffs = {
        k: {"a1": iv_a1[k], "b": iv_b[k], "a2": iv_a2[k]}
        for k in _ISOLATION_KEYS
        if not (iv_a1[k] == iv_b[k] == iv_a2[k])
    }
    isolation_all_green = all(iv_a1[k] and iv_b[k] and iv_a2[k] for k in _ISOLATION_KEYS)
    checks["isolationEqual"] = (isolation_diffs == {}) and isolation_all_green

    # Two tiers: tier-1 hold INTEGRITY (the control delivered the stimulus at the
    # right moment/target and was observed) — any failure is INCONCLUSIVE, because
    # a control that did not fire/hold correctly makes B look like a passing
    # positive and would be misread as "the gate is vacuous". tier-2 is the
    # VERDICT (the counter caught the freeze, RED isolated to the counter) —
    # PASS/FAIL only once integrity holds. On a MOVING footprint a rAF stall
    # (maxRafGapOk) is disqualifying integrity, not diagnostic-only (plan §4).
    integrity_keys = (
        "firedAtMoveStart", "firedAfterAdvance", "stageOriginZero", "noControlError",
        "ownerReadyAtTrigger", "staleFrameFromPlayback", "paintedOnce", "coverPatchStable",
        "coverHitTest100", "coverTracksFootprint", "loopLive", "everyInHoldStale",
        "flipIndexPresent", "flipWindowDecodable", "enoughAfterFlip",
        "releaseStrictlyBeforeSettleAndBurst", "allInHoldMeasured", "bridgeEngaged",
        "maxRafGapOk",
    )
    verdict_keys = (
        "indexRunRed", "reasonFreezeRunAtCut", "freezeRunMargin", "noNegativeAnomaly",
        "movingContinuityOk", "boundDecoderIsSlide3Decoder", "noOwnerAmbiguousInWindow",
        "rvfcRanThroughHold", "playerBuildErrorsEmpty", "positivesGreen", "isolationEqual",
    )
    integrity_failed = [k for k in integrity_keys if not checks.get(k)]
    verdict_failed = [k for k in verdict_keys if not checks.get(k)]
    if integrity_failed:
        ok, verdict, reason = False, "inconclusive", f"hold integrity failed: {integrity_failed}"
    elif not verdict_failed:
        ok, verdict, reason = True, "pass", None
    else:
        ok, verdict, reason = False, "fail", f"gate checks failed: {verdict_failed}"
    failed = integrity_failed + verdict_failed
    return {
        "ok": ok,
        "verdict": verdict,
        "reason": reason,
        "checks": checks,
        "integrityFailed": integrity_failed,
        "verdictFailed": verdict_failed,
        "failed": failed,
        "maxRafGapMs": max_gap_ms,
        "isolationDiffs": isolation_diffs,
        "freeze": {
            "holdStartedAt": hold_started,
            "holdOffsetS": hold_offset_s,
            "releaseOffsetS": release_offset_s_nc,
            "inHoldPositions": in_hold_positions,
            "inHoldDecodes": in_hold_decodes,
            "firstInHold": first_in_hold,
            "flipIndex": flip_index,
            "nAfterFlip": n_after,
            "maxRafGapMs": max_gap_ms,
            "rafFrames": len(raf_ts),
            "coverHitTestAll": all_cover,
            "coverTracksFootprint": checks["coverTracksFootprint"],
            "paintCount": nc.get("paintCount"),
            "firedVia": nc.get("firedVia"),
            "fellBackToArmOwner": nc.get("fellBackToArmOwner"),
            "boundDecoderId": nc.get("boundDecoderId"),
            "armedElId": nc.get("armedElId"),
            "armedOwnerRect": nc.get("armedOwnerRect"),
            "movedFromRect": nc.get("movedFromRect"),
            "movedToRect": nc.get("movedToRect"),
            "obedMotionAtTrigger": nc.get("obedMotionAtTrigger"),
            "coverPatchMean": cover_mean,
            "ownerReadyState": nc.get("ownerReadyState"),
            "stageOrigin": stage_origin,
            "error": nc.get("error"),
        },
        "isolationViews": {"a1": iv_a1, "b": iv_b, "a2": iv_a2},
    }

def _freeze_control_blocks_success(verdict: str | None, bridge34_disabled: bool) -> bool:
    """Owner decision 8b: does this `freeze_control` verdict block overall
    `success`? "pass" never blocks; "skipped" blocks EXCEPT under
    `--disable-bridge34` (the only arm with nothing to freeze); every other
    verdict ("inconclusive", "fail", or anything unrecognised) blocks, same as
    today — never weaken this to a pass on an unrecognised verdict."""
    if verdict == "pass":
        return False
    if verdict == "skipped":
        return not bridge34_disabled
    return True


async def _run_freeze_bracket(
    player_dir: Path, runs_dir: Path, wait_profile: dict, wait_profile_name: str
) -> dict:
    """A-B-A composited-freeze bracket on the 3->4 moving Magic Move boundary:
    positive -> freeze-control -> positive, one re-navigated Chrome (same
    session/profile) per run, its own HTTP server. Returns the
    `_score_freeze_control` verdict + the three snapshots (Phase 2).

    Re-bracketed off the 1->2 boundary (retired -- the derived plan REFUSES that
    carry, so there is no carried movie to freeze there; 3->4 still carries). SKIPPED
    (no boot, no bracket) when `--disable-bridge34` disables the 3->4 carry -- nothing
    to freeze in that arm."""
    if "--disable-bridge34" not in sys.argv:
        bridge34 = True
    else:
        bridge34 = False
    if not bridge34:
        return {
            "skipped": True,
            "reason": "bridge disabled",
            "verdict": "skipped",
            "ok": False,
            "waitProfile": wait_profile_name,
        }

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(player_dir), **k)

        def log_message(self, fmt, *args):  # noqa: A003
            return

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}/index.html"

    bdir = runs_dir / "freeze-bracket"
    if bdir.exists():
        shutil.rmtree(bdir)
    bdir.mkdir()
    # A FRESH Chrome per run: the player's SPA hash routing only establishes location
    # on a FIRST navigation — re-navigating the same session (2nd/3rd boot) leaves the
    # route hash '' indefinitely, which armed the null-control on '' and triggered on
    # the boot settle. Each run being a first-load gives a real #1 boundary. The A-B-A
    # comparison is unaffected (same code + fixture; the isolation check is per-snapshot).
    snaps: dict[str, dict] = {}
    try:
        for label, inject in (("a1", False), ("b", True), ("a2", False)):
            rd = bdir / label
            rd.mkdir()
            chrome = ChromeCdp(CHROME, bdir / f"chrome-profile-{label}")
            await chrome.start()
            try:
                await _boot(chrome, base)
                # The restart + 3->4 bridge boundaries are already in the continuity
                # plan baked into this player_dir's index.html by the main run above.
                snaps[label] = await _capture_3to4_snapshot(
                    chrome, rd, "mm34", wait_profile, inject_null=inject
                )
            finally:
                await chrome.close()
    finally:
        httpd.shutdown()

    verdict = _score_freeze_control(snaps["a1"], snaps["b"], snaps["a2"])
    verdict["waitProfile"] = wait_profile_name
    verdict["snapshots"] = snaps
    return verdict


async def _boot(chrome: ChromeCdp, base: str) -> dict:
    # Re-navigation in the SAME session (the freeze A-B-A bracket boots 3x) can leave
    # the player's route hash unsettled — `_wait_hash_clean` returns '' on timeout and
    # the boot used to proceed anyway. A caller that then arms the null-control on that
    # '' hash triggers on the player's own ''->#1 settle (BEFORE the advance), painting
    # a cover before the movie has a decoded frame. Retry the whole boot until BOTH the
    # hash is clean (#<digits>) AND a movie is genuinely playing.
    ready = None
    live_hash = None
    media: dict = {}
    for attempt in range(3):
        await chrome.goto("about:blank")
        await asyncio.sleep(0.05)
        await chrome.goto(f"{base}?currentSlide=1")
        ready = await _wait_ready(chrome)
        live_hash = await _wait_hash_clean(chrome)
        await _ensure_videos_playing(chrome)
        playing: list = []
        for _ in range(60):
            media = await _media_snapshot(chrome)
            vids = media.get("videos") or []
            playing = [
                v
                for v in vids
                if (v.get("readyState") or 0) >= 2 and not v.get("paused") and (v.get("currentTime") or 0) > 0.05
            ]
            if playing:
                break
            await _ensure_videos_playing(chrome)
            await asyncio.sleep(0.1)
        cur = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        if _strict_hash_num(cur) is not None and playing:
            return {"ready": ready, "liveHash": cur, "media": media, "attempts": attempt + 1}
        live_hash = cur
    return {"ready": ready, "liveHash": live_hash, "media": media, "attempts": 3, "bootDegraded": True}


async def _run(player: Path) -> dict:
    reuse = "--reuse-export" in sys.argv
    disposable_mode = "--disposable" in sys.argv
    # The 3->4 magic-move bridge is ON by default (the repair). --disable-bridge34
    # skips injecting the bridge config so the raw export restarts movie1 at slide
    # 4 — used to demonstrate continueThroughMovingMagicMove3to4 is RED without the
    # bridge (honest gate), never a false pass.
    bridge34 = "--disable-bridge34" not in sys.argv
    wait_profile_name = _arg_value("--wait-profile", "fast")
    wait_profile = WAIT_PROFILES[wait_profile_name]
    if OUT.exists() and not reuse:
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    runs = OUT / "runs"
    if runs.exists():
        shutil.rmtree(runs)
    runs.mkdir()

    before = file_identity(SOURCE)
    write_json(OUT / "fingerprints-before.json", before.as_dict())
    inv = inventory_deck(SOURCE)
    write_json(
        OUT / "inventory.json",
        {
            "source": before.as_dict(),
            "canvas": inv["canvas"],
            "slideCount": inv["slideCount"],
            "slides": [
                {
                    "originalOrdinal": s["originalOrdinal"],
                    "transition": s.get("transition"),
                    "magicMove": s.get("magicMove"),
                    "hasMovieStart": s.get("hasMovieStart"),
                    "builds": s.get("builds"),
                }
                for s in inv["slides"]
            ],
        },
    )

    unmodified = OUT / "html-unmodified"
    disposable_dir = OUT / "html-disposable"
    player_dir = OUT / "html-player"
    if reuse and (unmodified / "index.html").is_file():
        print("reusing HTML export at", unmodified)
    else:
        print("HTML export…")
        if unmodified.exists():
            shutil.rmtree(unmodified)
        export_html(SOURCE, unmodified, log=print)

    asset_replace_info: dict | None = None
    if disposable_mode:
        # Clone from the on-disk unmodified export — no Keynote required.
        if disposable_dir.exists():
            shutil.rmtree(disposable_dir)
        shutil.copytree(unmodified, disposable_dir)
        asset_replace_info = _replace_hevc_movies(disposable_dir)
        write_json(OUT / "asset-replace.json", asset_replace_info)
        source_dir = disposable_dir
    else:
        source_dir = unmodified

    strip_info = strip_export_pdf_bg_fills(source_dir)
    write_json(OUT / "pdf-strip.json", strip_info)
    print("stripped", [r["pdf"] for r in (strip_info.get("rewritten") or [])])
    if player_dir.exists():
        shutil.rmtree(player_dir)
    write_patched_export(source_dir, player_dir)
    preserve = inject_preserve(player_dir)
    write_json(OUT / "preserve-inject.json", preserve)
    # The 1->2 retire hands movie1 back to the player at slide 2 (refused carry);
    # the 3->4 bridge keeps the movie1 decoder playing across the moving cut.
    continuity_plan = build_continuity_plan(bridge34)
    plan_inject = inject_continuity_plan(player_dir, continuity_plan)
    write_json(OUT / "continuity-plan-inject.json", {**plan_inject, "plan": continuity_plan})

    # HTTP serve
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(player_dir), **k)

        def log_message(self, fmt, *args):  # noqa: A003
            return

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}/index.html"

    run_dir = runs / "primary"
    run_dir.mkdir()
    chrome = ChromeCdp(CHROME, run_dir / "chrome-profile")
    await chrome.start()
    try:
        boot = await _boot(chrome, base)
        # The continuity plan (restart boundary, and the 3->4 bridge boundary iff
        # bridge34) is already baked into index.html by inject_continuity_plan
        # above, present before the core script ran at page load.
        # Derive the footprint movie's Magic Move crossfade texture ids. Under
        # the corrected model this is a motion-path Magic Move poster swap (1->2
        # or 3->4 under outgoing-slide storage; the 2->3 boundary is a dissolve,
        # not a Magic Move) — see `_derive_movie_texids`. Written for provenance
        # only and NO LONGER injected as `window.__OBED_MOVIE_TEXIDS__`: the 1->2
        # movie is a live `<video>`, not a fed 2D canvas, so the canvas-feed is gone.
        texids_info = _derive_movie_texids(player_dir)
        write_json(OUT / "movie-texids.json", texids_info)
        await asyncio.sleep(wait_profile["clickDelayS"])
        media_pre = await _media_snapshot_with_pool(chrome)
        pre = await chrome.screenshot()
        Image.fromarray(pre).save(run_dir / "pre.png")
        pre_scores = {
            "empty": _score_empty(pre),
            "black": _score_black(pre, BLACK_ROI_S1),
            "green": _score_green(pre, GREEN_ROI_S1),
        }

        hash1 = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        # --- Transition A: 1→2 Magic Move + continue ---
        samples_a = [{"phase": "pre", "captureOffsetS": 0.0, **media_pre}]
        click_wall_a = time.monotonic()
        # Capture a few frames BEFORE firing the advance so the dense window
        # straddles the flip (movie already playing from boot at hash1).
        pre_frames_a = await _pre_advance_frames(
            chrome,
            run_dir,
            "mm12",
            click_wall_a,
            wait_profile["preAdvanceFrames"],
            wait_profile["preAdvanceGapS"],
        )
        # Fire the advance WITHOUT blocking on hash-settle — ChromeCdp has no
        # concurrent recv, so a blocking poll here would push dense capture
        # past the flip instant. Confirm the flip afterward instead.
        await chrome.key("ArrowRight", "ArrowRight", 39)
        immediate = await _media_snapshot_with_pool(chrome)
        samples_a.append(
            {
                **immediate,
                "phase": "hash-changed",
                "captureOffsetS": time.monotonic() - click_wall_a,
            }
        )
        dense_a, frames_a, decoder_frames = await _dense_after_click(
            chrome, run_dir, "mm12", click_wall_a, sample_decoder=True
        )
        samples_a.extend(dense_a)
        hash2 = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        if hash2 == hash1:
            # MM may still be settling past the dense window; short grace poll.
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline and hash2 == hash1:
                await asyncio.sleep(0.05)
                hash2 = _norm_hash(
                    await chrome.evaluate(
                        "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
                    )
                )
        method_a = f"arrow-nonblocking:{hash1}->{hash2}"
        mid = await chrome.screenshot()
        Image.fromarray(mid).save(run_dir / "after-1to2.png")
        # Sample the movie1 decoder's OWN frame (not the composite) as close to the
        # mid screenshot as possible, to prove the green square composites IN FRONT
        # of it rather than just "this ROI looks greenish" (which the movie's own
        # green content can satisfy on its own).
        media_for_green = await _media_snapshot_with_pool(chrome)
        green_target = await _footprint_target(chrome, media_for_green, MOVIE_ROI)
        green_decoder_id = green_target.get("decoderId")
        green_source_arr: np.ndarray | None = None
        if green_decoder_id is not None:
            green_sample = await chrome.evaluate(
                "window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.sampleFrame "
                f"? window.__OBED_P2_PRESERVE__.sampleFrame({int(green_decoder_id)}) : {{ok: false}}"
            )
            if green_sample and green_sample.get("ok") and green_sample.get("dataURL"):
                raw = green_sample["dataURL"].split(",", 1)[-1]
                green_source_arr = np.array(
                    Image.open(io.BytesIO(base64.b64decode(raw))).convert("RGB")
                )
                Image.fromarray(green_source_arr).save(run_dir / "green-front-source.jpg")
        mid_scores = {
            "empty": _score_empty(mid),
            "black": _score_black_auto(mid),
            "blackFixedRoi": _score_black(mid, BLACK_ROI_S2),
            "green": _score_green(mid, GREEN_ROI_S1),
            # New z-order composition (green front, movie, black behind).
            "blackAbove": _score_black(mid, BLACK_ABOVE_ROI),
            "blackBehind": _score_black(mid, BLACK_BEHIND_ROI),
            "greenFront": _score_green(mid, GREEN_FRONT_ROI),
            "greenFrontComposite": _score_green_front_composite(
                mid, GREEN_FRONT_ROI, MOVIE_ROI, green_source_arr
            ),
        }

        # Bind continuity to the ONE footprint-owner decoder's own clock, not
        # "primary" (max across ALL videos) nor max-of-same-key (a fresh/pooled
        # movie1 instance sitting higher must not mask the bound decoder's stall).
        # If the footprint owner is unresolved, emit all-None (the gate fails) —
        # never a same-key fallback.
        primary_times_a = _times(samples_a, "primary")
        min_times_a = _times(samples_a, "min")
        target_times_a = (
            _times(samples_a, EXPECTED_MOVIE_KEYS[0], decoder_id=green_decoder_id)
            if green_decoder_id is not None
            else [None] * len(samples_a)
        )
        cont = score_playback_continuity(
            target_times_a,
            click_i=0,
            capture_offsets=_caps(samples_a),
            dissolve_s=TRANS_S,
            position_eps=1.25,  # MM can take >0.75s before first pooled sample
        )
        mm_paths = sorted(run_dir.glob("mm12-t*.png"))
        visible_motion = _score_visible_movie_motion(mm_paths, MOVIE_ROI)
        capture_race_frames_a = sum(
            1 for f in [*pre_frames_a, *frames_a] if f.get("bracketConsistent") is False
        )
        flip_samples = []
        for f in [*pre_frames_a, *frames_a]:
            if f.get("sceneHash") is None:
                continue
            farr = np.array(Image.open(run_dir / f["name"]))
            flip_samples.append(
                {
                    "roi": _crop(farr, MOVIE_ROI),
                    "sceneHash": f["sceneHash"],
                    "captureOffsetS": f.get("captureOffsetS"),
                    "decoderId": f.get("decoderId"),
                    "w": f.get("w"),
                    "movieKey": f.get("movieKey"),
                    "contextType": f.get("contextType"),
                    "ownerAmbiguous": f.get("ownerAmbiguous"),
                }
            )
        motion_across_flip = score_motion_across_flip(
            flip_samples, start_hash=hash1, expected_key=EXPECTED_MOVIE_KEYS[0]
        )
        flip_rois = [s["roi"] for s in flip_samples]
        # Composited-freeze check: decode the frame-index patch off every dense
        # capture and confirm it keeps progressing across the MM cut, rather than
        # sticking on the newborn canvas's stale poster frame for 1-2 frames.
        index_samples = [
            {
                "index": f.get("index"),
                "sceneHash": f.get("sceneHash"),
                "captureOffsetS": f.get("captureOffsetS"),
            }
            for f in [*pre_frames_a, *frames_a]
        ]
        flip_index = next(
            (
                i
                for i, s in enumerate(index_samples)
                if s["sceneHash"] is not None and s["sceneHash"] != hash1
            ),
            None,
        )
        if flip_index is None:
            index_run = {"ok": False, "reason": "no scene-hash flip observed in dense window"}
        else:
            index_run = score_composited_index_run(index_samples, flip_index=flip_index)
        decoder_motion: dict = {"ok": False, "n": 0, "attempts": len(decoder_frames)}
        ok_frames = [d for d in decoder_frames if d.get("path")]
        if len(ok_frames) >= 2:
            d0 = np.array(Image.open(ok_frames[0]["path"]))
            d1 = np.array(Image.open(ok_frames[-1]["path"]))
            decoder_motion = {
                "ok": _mae_rgb(d0, d1) >= 2.0,
                "n": len(ok_frames),
                "firstLastMae": _mae_rgb(d0, d1),
                "t0": ok_frames[0].get("currentTime"),
                "t1": ok_frames[-1].get("currentTime"),
            }
        elif decoder_frames:
            decoder_motion = {
                "ok": False,
                "n": len(ok_frames),
                "attempts": len(decoder_frames),
                "firstFailure": next((d for d in decoder_frames if not d.get("path")), None),
            }

        # 2→3 restart must come from the authored Start Movie (PRESERVE_SCRIPT's
        # boundary guard), not a manual pool clear.
        await asyncio.sleep(wait_profile["postMmSettleS"])
        settled2 = await chrome.screenshot()
        Image.fromarray(settled2).save(run_dir / "settled-slide2.png")
        settled_slide2_roi = _crop(settled2, MOVIE_ROI)
        lingering_on_slide2 = await chrome.evaluate(
            LINGERING_MOVIE_OVERLAYS_JS
        ) or {"error": "evaluate returned nothing"}
        # The real pool, on settled slide 2 and inside the retire zone: the only
        # proof that nothing of movie1 is sitting detached in it.
        pool_census_s2 = await chrome.evaluate(POOL_CENSUS_JS) or {
            "error": "pool census unavailable"
        }
        await _ensure_videos_playing(chrome)
        media_mid = await _media_snapshot_with_pool(chrome)
        h_mid = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        click_wall_b = time.monotonic()
        samples_b = [
            _annotate_sample(
                media_mid, phase="pre", capture_offset_s=0.0, scene_hash=h_mid
            )
        ]
        # Drain slide-2 builds while sampling continuously through the #6 boundary.
        methods_b, drain_samples = await _advance_until_hash_at_least_sampling(
            chrome,
            min_hash=SLIDE3_MIN_HASH,
            max_steps=16,
            click_wall=click_wall_b,
            sample_hz=12.0,
        )
        samples_b.extend(drain_samples)
        dense_b, frames_b, _ = await _dense_after_click(
            chrome, run_dir, "restart23", click_wall_b
        )
        # Annotate dense samples with scene hash snapshots (best-effort).
        for s in dense_b:
            s.setdefault("phase", "dense-post")
            s["movies"] = _per_movie_obs(s)
            if "sceneHash" not in s:
                s["sceneHash"] = None
        samples_b.extend(dense_b)
        hash3 = _norm_hash(
            await chrome.evaluate(
                "window.__OBED_P2_PROBE__ ? window.__OBED_P2_PROBE__.hash() : location.hash"
            )
        )
        for s in samples_b:
            if s.get("sceneHash") is None:
                s["sceneHash"] = hash3
        post = await chrome.screenshot()
        Image.fromarray(post).save(run_dir / "after-2to3.png")
        preserved_on_slide3 = await chrome.evaluate(
            """(() => {
              const vids = Array.prototype.slice.call(
                document.querySelectorAll('video[data-obed-preserved="1"]')
              );
              const visible = vids.filter((v) => {
                if (!document.contains(v)) return false;
                const st = getComputedStyle(v);
                if (st.visibility === 'hidden' || st.display === 'none') return false;
                const r = v.getBoundingClientRect();
                return r.width > 1 && r.height > 1;
              });
              return {total: vids.length, visible: visible.length};
            })()"""
        ) or {"total": 0, "visible": 0}
        lingering_movie_overlays = await chrome.evaluate(
            LINGERING_MOVIE_OVERLAYS_JS
        ) or {"count": 0, "elIds": [], "preservedCount": 0}
        post_black = _score_black_auto(post)
        post_green = _score_green(post, GREEN_ROI_S1)
        overlay_gone_by_roi = (not post_black.get("ok")) and (not post_green.get("ok"))
        restart_paths = sorted(run_dir.glob("restart23-t*.png"))
        restart_canvas = _score_canvas_identical(restart_paths)

        # Per-movie timeline across the drain→slide3 boundary.
        movie_keys = sorted(
            {
                m.get("key")
                for s in samples_b
                for m in (s.get("movies") or [])
                if m.get("key")
            }
        )
        restart_scores: dict = {}
        for key in ["primary", "min", *movie_keys]:
            times = _times(samples_b, key)
            scored = score_playback_continuity(
                times, click_i=0, capture_offsets=_caps(samples_b), dissolve_s=TRANS_S
            )
            first = scored.get("firstAfterClick")
            pre_t = scored.get("preTime")
            restarted = bool(
                scored.get("remountRestart")
                or scored.get("hardRestartVsPre")
                or (first is not None and float(first) < 0.35)
                or (
                    pre_t is not None
                    and first is not None
                    and float(first) + 0.35 < float(pre_t)
                )
            )
            # Observations on/after slide-3 scenes only.
            slide3_obs = []
            for s in samples_b:
                hn = _hash_num(s.get("sceneHash"))
                if hn is None or hn < SLIDE3_MIN_HASH:
                    continue
                for m in s.get("movies") or []:
                    if key in ("primary", "min") or m.get("key") == key:
                        slide3_obs.append(
                            {
                                "t": m.get("currentTime"),
                                "w": m.get("videoWidth"),
                                "captureOffsetS": s.get("captureOffsetS"),
                                "sceneHash": s.get("sceneHash"),
                                "phase": s.get("phase"),
                                "key": m.get("key"),
                            }
                        )
            earliest_slide3 = next(
                (o for o in slide3_obs if o.get("t") is not None), None
            )
            restart_scores[key] = {
                **{k: scored.get(k) for k in (
                    "preTime", "firstAfterClick", "postTime", "remountRestart",
                    "hardRestartVsPre", "continuesThroughDissolve",
                )},
                "restarted": restarted,
                "earliestSlide3Obs": earliest_slide3,
                "slide3ObsN": len(slide3_obs),
            }

        # Fetch by kind server-side — a flat last-120 slice lets ~100+ routine
        # remount-done events crowd out the few guard/retire/clear events that
        # findings actually depend on.
        preserve_events = await chrome.evaluate(
            r"""(() => {
              const p = window.__OBED_P2_PRESERVE__;
              if (!p) return [];
              const keep = [
                'reuse-skip-boundary', 'retire-on-start-movie', 'pool-cleared',
                'reuse-decoder', 'createElement-video',
                // The retire zone asserts refusal by a POSITIVE event, and its
                // absence-of-carry clause needs the pool-consuming notes too.
                'preserve-refused', 'retire-boundary', 'dom-swap',
                'remount-error', 'facade-block-clear',
                'texture-feed-start', 'texture-feed-stop',
                // F1a: engagement events the fail-closed 1->2 gate keys off — a
                // texture-feed-draw / mo-prepaint-draw into an incoming canvas is
                // the ONLY positive proof the feed drew; the skip notes explain a
                // non-engagement so the gate fails for a named reason, not silently.
                'texture-feed-draw', 'texture-feed-skip', 'texture-feed-skip-canvas',
                'mo-prepaint-skip',
                'player-build-error', 'mo-prepaint-draw', 'mo-no-stage'
              ];
              const important = p.events.filter((e) => keep.indexOf(e.kind) >= 0);
              // Keep the EARLIEST remounts as well: a carry inside the retire
              // zone happens long before the last-20 window.
              const remountAll = p.events.filter((e) => e.kind === 'remount-done');
              const remounts = remountAll.slice(0, 12).concat(remountAll.slice(12).slice(-20));
              const moNoTexids = p.events.filter((e) => e.kind === 'mo-no-texids').slice(-5);
              return important.concat(remounts).concat(moNoTexids);
            })()"""
        ) or []
        # Carry census: counted IN THE PAGE over the full event log and filtered
        # to movie1 BEFORE any slicing, so a bounded sample can never hide an
        # offending note behind another movie's routine ones.
        carry_census = await chrome.evaluate(CARRY_CENSUS_JS) or {
            "error": "carry census unavailable"
        }
        clear_i = next(
            (i for i, e in enumerate(preserve_events) if e.get("kind") == "pool-cleared"),
            None,
        )
        reuse_after_clear = [
            e
            for i, e in enumerate(preserve_events)
            if e.get("kind") == "reuse-decoder" and (clear_i is None or i > clear_i)
        ]
        reuse_skip_boundary_events = [
            e for e in preserve_events if e.get("kind") == "reuse-skip-boundary"
        ]
        retire_events = [e for e in preserve_events if e.get("kind") == "retire-on-start-movie"]
        target_key = EXPECTED_MOVIE_KEYS[0]
        reuse_skip_boundary_for_target = [
            e
            for e in reuse_skip_boundary_events
            if _movie_key((e.get("detail") or {}).get("key") or "") == target_key
        ]
        retire_events_for_target = [
            e
            for e in retire_events
            if _movie_key((e.get("detail") or {}).get("key") or "") == target_key
        ]
        # Reuse of a preserved decoder is the LEGITIMATE 1→2 continue mechanism; only a
        # reuse on/after the restart boundary would stitch a fake restart. Scope the ban there.
        reuse_after_boundary = [
            e
            for e in preserve_events
            if e.get("kind") == "reuse-decoder"
            and (_hash_num((e.get("detail") or {}).get("sceneHash")) or -1) >= SLIDE3_MIN_HASH
        ]
        reached_slide3 = (_hash_num(hash3) or -1) >= SLIDE3_MIN_HASH
        # Fixed expected keys — never derive solely from what happened to be observed.
        intended_keys = list(EXPECTED_MOVIE_KEYS)
        # Composed-ROI corroboration on slide 3. The burnt-in frame-index counter
        # (parity-immune) is the gating signal; pixel-MAE is kept as a diagnostic
        # only. The slide-2 grating aliases to a ~50/50 per-pair change under the
        # work-bound capture cadence, which made MAE-based motion a ~1/3 coin flip
        # (2->3 restart flake, Fable root-cause 2026-09-18); the counter marches
        # forward every presented frame regardless of grating phase.
        restart_pixel_motion = _score_visible_movie_motion(restart_paths, MOVIE_ROI)
        restart_index_seq = [
            _decode_index_patch(np.asarray(Image.open(p).convert("RGBA")), INDEX_PATCH_ROI_SLIDE3)
            for p in restart_paths
        ]
        restart_index_progression = score_index_progression(restart_index_seq)
        per_movie_boundary: dict[str, dict] = {}
        for key in intended_keys:
            obs = []
            for s in samples_b:
                for m in s.get("movies") or []:
                    if m.get("key") != key or m.get("currentTime") is None:
                        continue
                    obs.append(
                        {
                            "t": float(m["currentTime"]),
                            "w": m.get("videoWidth"),
                            "captureOffsetS": float(s.get("captureOffsetS") or 0.0),
                            "sceneHash": s.get("sceneHash"),
                            "phase": s.get("phase"),
                            "decoderId": m.get("decoderId"),
                        }
                    )
            per_movie_boundary[key] = score_restart_movie_from_observations(
                obs,
                slide_min_hash=SLIDE3_MIN_HASH,
                progression_wall_s=PROGRESSION_WALL_S,
                progression_media_s=PROGRESSION_MEDIA_S,
            )
            # presentedMotionOk: the TARGET decoder's own rVFC mediaTime progression
            # is mandatory (a frozen restart decoder must not pass just because some
            # OTHER movie/animation moves the shared ROI); on-screen progression is
            # required too as corroboration, via the parity-immune burnt-in index
            # counter (pixelMotion stays as a diagnostic only — see above).
            restart_decoder_id = per_movie_boundary[key].get("restartDecoderId")
            presented_rvfc = _presented_time_advances(samples_b, restart_decoder_id, SLIDE3_MIN_HASH)
            per_movie_boundary[key]["presentedMotionOk"] = bool(
                presented_rvfc.get("ok") and restart_index_progression.get("ok")
            )
            per_movie_boundary[key]["presentedMotionDetail"] = {
                "indexProgression": restart_index_progression,
                "pixelMotion": restart_pixel_motion,
                "rvfcAdvance": presented_rvfc,
            }
        # Tie the guard/retire evidence to the SPECIFIC decoder that earned the
        # restart score — a reuse-skip-boundary/retire for the target key that
        # happened to some OTHER decoder does not prove this decoder is genuine.
        target_restart_decoder_id = per_movie_boundary.get(target_key, {}).get("restartDecoderId")
        reuse_skip_boundary_matching_restart = [
            e
            for e in reuse_skip_boundary_for_target
            if (e.get("detail") or {}).get("newElId") == target_restart_decoder_id
        ]
        # Belt-and-suspenders on top of reuse_after_boundary's blanket ban: explicitly
        # forbid a reuse-decoder for the target key at/after the boundary that either
        # supplies the exact element we scored as the restart, or looks like a
        # near-zero decoder being handed off (not a genuine fresh createElement).
        reuse_decoder_events = [e for e in preserve_events if e.get("kind") == "reuse-decoder"]
        reuse_stitched_restart = [
            e
            for e in reuse_decoder_events
            if _movie_key((e.get("detail") or {}).get("key") or "") == target_key
            and (_hash_num((e.get("detail") or {}).get("sceneHash")) or -1) >= SLIDE3_MIN_HASH
            and (
                (e.get("detail") or {}).get("newElId") == target_restart_decoder_id
                or abs(float((e.get("detail") or {}).get("preservedT") or 0.0)) < 0.35
            )
        ]
        boundary = score_restart_at_slide_boundary(
            reached_slide=reached_slide3,
            per_movie=per_movie_boundary,
            expected_keys=intended_keys,
            canvas_all_identical=bool(restart_canvas.get("allFramesIdentical")),
        )
        restart_playback_ok = bool(boundary["ok"])
        restart_inconclusive = bool(boundary["inconclusive"])
        restart_verdict = str(boundary["verdict"])
        missing_slide3 = list(boundary["missingSlide3Media"])
        # Stash for report detail.
        near_zero_on_slide3 = any(v["nearZeroAtBoundary"] for v in per_movie_boundary.values())
        earliest_any = None
        for v in per_movie_boundary.values():
            e = v.get("earliest")
            if e and (earliest_any is None or float(e["t"]) < float(earliest_any["t"])):
                earliest_any = e
        restart_observed = bool(boundary["allMoviesOk"])
        drain_samples_n = len(drain_samples)
        neighbours_retained = _score_neighbours_retained_clocks(
            samples_b, intended_keys, SLIDE3_MIN_HASH
        )

        # ================= Transition C: 3->4 moving Magic Move =================
        # (positive control — new finding continueThroughMovingMagicMove3to4;
        #  everything below is delimited for merge with Peer B's adversarial edits)
        await _ensure_videos_playing(chrome)
        click_wall_c = time.monotonic()
        (
            owner_samples_c,
            media_samples_c,
            index_samples_c,
            hash4,
            _capture_meta_c,
        ) = await _advance_to_slide4_capture(chrome, run_dir, "mm34", click_wall_c)
        # Counter progression is scored over the SETTLED slide-4 window (footprint
        # fully at the destination rect, progress>=0.98) so the moving ROI lands on
        # the decoder's flat patch: mid-transition frames sample a moving/animating
        # box and decode garbage. Liveness THROUGH the cut is proven separately by
        # movingContinuity3to4's rVFC advance; this corroborates that the settled
        # slide-4 composite shows live frames, not a frozen poster.
        slide4_index_seq = [
            s.get("index") for s in index_samples_c
            if (_hash_num(s.get("sceneHash")) or -1) >= SLIDE4_MIN_HASH
            and float(s.get("progress") or 0.0) >= 0.98
        ]
        moving_index_run = score_index_progression(slide4_index_seq)
        # REPORT-only (owner decision 8a): the freeze-control at-cut run scorer
        # (`score_composited_index_run`, flip at the first MEASURED sample reaching
        # slide 4) computed here for `continueThroughMovingMagicMove3to4`'s detail.
        # Never gates that finding's `pass` -- only one clean fast/slow/bridge-off
        # round earns it a place in the pass condition.
        measured_index_samples_c = [
            s for s in index_samples_c if s.get("footprintSource") == "measured"
        ]
        _flip_idx_at_cut = next(
            (
                i for i, s in enumerate(measured_index_samples_c)
                if (_hash_num(s.get("sceneHash")) or -1) >= SLIDE4_MIN_HASH
            ),
            None,
        )
        if _flip_idx_at_cut is None:
            moving_index_run_at_cut = {
                "ok": False,
                "reason": "no measured sample reached slide 4",
            }
        else:
            moving_index_run_at_cut = score_composited_index_run(
                measured_index_samples_c, flip_index=_flip_idx_at_cut
            )
        bridge_events = await chrome.evaluate(
            "window.__OBED_P2_PRESERVE__ ? window.__OBED_P2_PRESERVE__.events"
            ".filter(function(e){return e.kind==='bridge-3to4';}).slice(-6) : []"
        ) or []
        slide4_after = await chrome.screenshot()
        Image.fromarray(slide4_after).save(run_dir / "after-3to4.png")
        # Visible-content burst on the SETTLED slide-4 destination: unevenly
        # spaced so a two-state grating cannot alias into "static".
        burst_start = time.monotonic()
        slide4_burst: list[np.ndarray] = []
        for off_ms in BURST_OFFSETS_MS:
            gap = (burst_start + off_ms / 1000.0) - time.monotonic()
            if gap > 0:
                await asyncio.sleep(gap)
            shot = await chrome.screenshot()
            slide4_burst.append(np.asarray(shot)[:, :, :3])
            Image.fromarray(shot).save(run_dir / f"slide4-live-t{off_ms:04d}.png")
        footprint_live = footprintFullyLive(slide4_burst)
        # ================= end Transition C =================
    finally:
        await chrome.close()
        httpd.shutdown()

    after = file_identity(SOURCE)
    write_json(OUT / "fingerprints-after.json", after.as_dict())

    player_build_errors = [e for e in preserve_events if e.get("kind") == "player-build-error"]

    # Fail-closed live-<video> continuity sub-verdict — a necessary condition for
    # the 1->2 finding under the corrected model. It proves the ONE footprint
    # decoder is stable across the cut, its rVFC presentedMediaTime advances, and
    # composited ROI motion crosses the flip. Absence of any sub-condition fails
    # the gate closed. samples_a carries the `videos` rVFC clocks.
    live_continuity = liveContinuity1to2(
        motion_across_flip, flip_samples, samples_a, hash1, hash2,
        restart_min_hash=SLIDE3_MIN_HASH,
    )

    # Fail-closed positive-control sub-verdict for the 3->4 moving Magic Move: the
    # bridged movie1 decoder (the SAME one that played slide 3) must own the
    # translated+scaled slide-4 footprint with a monotonic rVFC clock (not the
    # export's fresh autoplay-from-0 restart). slide3_movie_decoder is the decoder
    # the 2->3 restart scoring already bound for movie1 (el4).
    slide3_movie_decoder = (
        (per_movie_boundary.get(EXPECTED_MOVIE_KEYS[0]) or {}).get("restartDecoderId")
    )
    moving_continuity = movingContinuity3to4(
        owner_samples_c, media_samples_c, slide3_movie_decoder,
        hash3, hash4, SLIDE4_MIN_HASH,
    )

    # The 1->2 carry is refused by the derived plan: assert the refusal was
    # honoured and slide 2 is indistinguishable from the raw export.
    refused_carry = refusedCarry1to2(
        continuity_plan,
        preserve_events,
        lingering_on_slide2,
        motion_across_flip,
        flip_rois,
        settled_slide2_roi,
        index_samples,
        flip_index,
        hash1,
        hash2,
        player_build_errors,
        carry_census,
    )
    # With movie1 never pooled, the reuse-skip/retire pair at the 2->3 boundary
    # cannot fire; "nothing was ever pooled" is the stronger substitute.
    never_pooled = neverPooledEvidence(preserve_events, carry_census, pool_census_s2)

    findings = [
        {"id": "sourceUnchanged", "pass": after.as_dict() == before.as_dict()},
        {"id": "emptyCanvasPre", "pass": pre_scores["empty"]["ok"], "detail": pre_scores["empty"]},
        {"id": "blackSentinelOpaquePre", "pass": pre_scores["black"]["ok"], "detail": pre_scores["black"]},
        {"id": "greenTranslucentPre", "pass": pre_scores["green"]["ok"], "detail": pre_scores["green"]},
        {
            "id": "refusedCarry1to2",
            "pass": refused_carry["ok"],
            "status": "failed-by-player" if player_build_errors else None,
            "detail": {
                "refusedCarry1to2": refused_carry,
                "lingeringOnSlide2": lingering_on_slide2,
                "poolCensusOnSlide2": pool_census_s2,
                "injectedBoundaries": continuity_plan["boundaries"],
                "diagnosticsNonGating": [
                    "continues", "noJump", "remountRestart", "pre", "firstAfter", "post",
                    "visibleMovieMotion", "indexRun", "indexSequence", "movieTexids",
                    "liveContinuity1to2", "motionAcrossFlip", "decoderMotion", "reuseEvents",
                ],
                "continues": cont.get("continuesThroughDissolve"),
                "noJump": cont.get("noJump"),
                "remountRestart": cont.get("remountRestart"),
                "pre": cont.get("preTime"),
                "firstAfter": cont.get("firstAfterClick"),
                "post": cont.get("postTime"),
                "hash": f"{hash1}->{hash2}",
                "method": method_a,
                "visibleMovieMotion": visible_motion,
                "indexRun": index_run,
                "flipIndex": flip_index,
                "indexSequence": [s.get("index") for s in index_samples],
                "movieTexids": {
                    "decoderKey": texids_info.get("decoderKey"),
                    "boundary": texids_info.get("boundary"),
                    "outgoing": texids_info.get("outgoing"),
                    "incoming": texids_info.get("incoming"),
                },
                "movieTexidsWarning": texids_info.get("warning"),
                "liveContinuity1to2": live_continuity,
                "motionAcrossFlip": motion_across_flip,
                "decoderMotion": decoder_motion,
                "targetKey": EXPECTED_MOVIE_KEYS[0],
                "primaryTimes": primary_times_a,
                "minTimes": min_times_a,
                "captureRaceFramesN": capture_race_frames_a,
                "playerBuildErrors": player_build_errors,
                "reuseEvents": [
                    e for e in preserve_events if e.get("kind") == "reuse-decoder"
                ][:8],
                "note": (
                    "The derived plan REFUSES the 1->2 carry (slide 2 draws the green square "
                    "OVER the movie), so this finding asserts the refusal was honoured and "
                    "slide 2 looks exactly like the raw export. Pass requires ALL of: (a) the "
                    f"injected plan retires movie1 at scene {SLIDE2_MIN_HASH}; (b) at least one "
                    "positive preserve-refused/retire-boundary event for movie1 at scene >= "
                    f"{RETIRE_ZONE_MIN_HASH} (refusal is asserted by an event, never by silence; "
                    "the player holds the PREVIOUS hash for the whole Magic Move, so the "
                    "preserve-refused notes land at that scene and the swept retire-boundary at "
                    f"{SLIDE2_MIN_HASH}); (c) ZERO carry notes (remount-scheduled/-done/-placed, "
                    "reuse-decoder, dom-swap, facade-block-clear) for movie1 or its elements "
                    f"anywhere in the retire zone [{RETIRE_ZONE_MIN_HASH}, {SLIDE3_MIN_HASH}) — "
                    "the transition scene INCLUDED, since the player detaches the slide-1 videos "
                    "while still on it and a remount there is what leaves a decoder painting on "
                    "slide 2. The carry notes are counted IN THE PAGE over the whole event log, "
                    "filtered to movie1 before any slicing, and the gate reads that total (a "
                    "missing or malformed census fails closed); "
                    "(d) on settled slide 2, zero preserved/remounted leftovers AND zero PAINTING "
                    "<video>s over the slide-1/2 footprints (the player composites slide 2 in "
                    "WebGL with its layer tree at opacity 0, so the paint test is opacity-aware); "
                    "(e) the composite in the movie ROI PIXEL-FROZEN across the whole post-flip "
                    "window (every after-pair MAE <= the scorer's own pairEps, >= 4 after-pairs) "
                    "while it was LIVE before the flip — the raw export's own behaviour, and a "
                    "carried movie would show after-pair MAE far above eps — with a real forward "
                    "1->2 hash change. The burnt-in counter CANNOT serve here: on the refused "
                    "slide the patch ROI shows the export's poster photo, not the grating, so it "
                    "never decodes; frozenIndexNonGating keeps it as a diagnostic. (f) no "
                    "player-build-error. The former continuity evidence (continues/indexRun/"
                    "liveContinuity1to2/motionAcrossFlip/movieTexids) is all false BY DESIGN now "
                    "and is kept as NON-GATING diagnostics only."
                ),
            },
        },
        {
            "id": "blackSurvivesAfter1to2",
            "pass": mid_scores["black"]["ok"],
            "detail": mid_scores["black"],
        },
        {
            "id": "emptyCanvasAfter1to2",
            "pass": mid_scores["empty"]["ok"],
            "detail": mid_scores["empty"],
        },
        {
            "id": "overlappingArtworkComposedAfter1to2",
            "pass": bool(
                mid_scores["blackAbove"]["ok"]
                and mid_scores["blackBehind"]["rgbMean"] > BLACK_RGB_MEAN_MAX
                and not mid_scores["blackBehind"]["ok"]
                and mid_scores["greenFront"]["greenish"]
            ),
            "detail": {
                "blackAbove": mid_scores["blackAbove"],
                "blackBehind": mid_scores["blackBehind"],
                "greenFrontComposite": mid_scores["greenFrontComposite"],
                "greenFront": mid_scores["greenFront"],
                "blackAuto": mid_scores["black"],
            },
            "note": (
                "Authored z-order front->back: green square, larger movie, black sentinel, "
                "smaller movie. Verifies the composition against the LARGER movie: the black "
                "sentinel is opaque above the movie (blackAbove ok), is OCCLUDED by the movie "
                "where they overlap (blackBehind shows the movie, rgbMean>40, not opaque black), "
                "and the green square is IN FRONT (greenFront greenish). The disposable movie is a "
                "NEUTRAL grayscale grating (r==g==b), so greenish uniquely means the green square "
                "composites in front — it is NOT satisfiable by the movie's own colour (Codex's "
                "content-dependence concern). greenFrontComposite (composite vs decoder source) is "
                "kept as extra evidence but not gating, since a fast movie races the source sample. "
                "Green's translucency is proven separately by greenTranslucentPre on slide 1. A "
                "root-level overlay on top would fail blackBehind (black would show); green behind "
                "would fail greenFront (the neutral grating, not green, would show). "
                "NOT re-scoped under the baseline: the REFUSAL is what keeps this finding "
                "honest — with the 1->2 carry refused nothing of ours overlays slide 2, so the "
                "authored z-order the player composites IS the one scored here. blackBehind now "
                "reads the FROZEN poster grating instead of a live one; both are mid-grey "
                "(rgbMean>40) and the threshold is deliberately untouched — a dip is a true red "
                "to investigate, never a threshold to loosen."
            ),
        },
        {
            "id": "reachedSlide3",
            "pass": reached_slide3,
            "detail": {
                "hash": f"{hash2}->{hash3}",
                "minHash": SLIDE3_MIN_HASH,
                "methods": methods_b,
            },
        },
        {
            "id": "overlayRemovedOnLeave",
            "pass": bool(
                preserved_on_slide3.get("visible", 1) == 0
                and lingering_movie_overlays.get("count", 1) == 0
            ),
            "detail": {
                "preservedVideosOnSlide3": preserved_on_slide3,
                "lingeringMovieOverlays": lingering_movie_overlays,
                "roiCheck": {"black": post_black, "green": post_green},
                "roiOverlayGone": overlay_gone_by_roi,
                "hash": hash3,
            },
            "note": (
                "Requires zero visible preserved videos AND zero visible <video> "
                "elements overlapping the slide-1/2 movie footprints on slide 3 "
                "(catches a lingering overlay even if it lost its preserved marker). "
                "The ROI check is informational only, not gating."
            ),
        },
        {
            "id": "deliberateRestart2to3",
            "pass": restart_playback_ok,
            "verdict": restart_verdict,
            "detail": {
                "movies": restart_scores,
                "perMovieBoundary": per_movie_boundary,
                "missingSlide3Media": missing_slide3,
                "hash": f"{hash2}->{hash3}",
                "methods": methods_b,
                "reachedSlide3": reached_slide3,
                "restartObservedNearZero": restart_observed or near_zero_on_slide3,
                "nearZeroOnSlide3": near_zero_on_slide3,
                "earliestSlide3Obs": earliest_any,
                "restartInconclusive": restart_inconclusive,
                "restartCanvas": restart_canvas,
                "poolCleared": clear_i is not None,
                "reuseAfterClear": reuse_after_clear[:6],
                "reuseSkipBoundaryEvents": reuse_skip_boundary_events[:6],
                "retireEvents": retire_events[:6],
                "neighboursRetainedClocks": bool(neighbours_retained.get("ok")),
                "neighboursRetainedClocksDetail": neighbours_retained,
                "drainSampleN": drain_samples_n,
                "note": (
                    "Pass only when each intended movie has slide-3 observations "
                    "with near-zero at the boundary and later progression. "
                    "Pre-boundary restart_observed alone is not a pass. "
                    "Missing slide-3 media → inconclusive/fail. "
                    "Restart now comes from the authored Start Movie via the "
                    "boundary-guarded reuse skip, not a manual pool clear."
                ),
            },
        },
        {
            "id": "preserveDidNotBlockRestart",
            "pass": bool(
                restart_playback_ok
                and clear_i is None
                and target_restart_decoder_id is not None
                and (
                    (
                        len(reuse_skip_boundary_matching_restart) >= 1
                        and len(retire_events_for_target) >= 1
                    )
                    or never_pooled["ok"]
                )
                and len(reuse_after_boundary) == 0
                and len(reuse_stitched_restart) == 0
            ),
            "verdict": restart_verdict if restart_playback_ok or restart_inconclusive else "fail",
            "note": (
                "decoder-preserve must not stitch a deliberate Start Movie restart. "
                "Requires: no manual pool-cleared event at all, a reuse-skip-boundary "
                "whose newElId IS the decoder that earned deliberateRestart2to3 "
                "(not just any target-key event), a retire-on-start-movie for the "
                "target key, zero reuse-decoder events ON/AFTER the boundary "
                "(pre-boundary 1→2 reuse is the legitimate continue), and no "
                "reuse-decoder for the target key that supplies the same restart "
                "element or a near-zero-then-reset preservedT — the fresh restart "
                "element must be a genuine createElement, not a reused decoder. "
                "The negative clauses are verbatim; the POSITIVE pair (a "
                "reuse-skip-boundary matching the restart decoder AND a "
                "retire-on-start-movie) is required UNLESS the target key was retired "
                f"at scene {SLIDE2_MIN_HASH}: a preserve-refused/retire-boundary event "
                "with no pool-consuming note (remount-*/reuse-decoder/dom-swap/"
                f"facade-block-clear) for that key before scene {SLIDE3_MIN_HASH} means "
                "the pool was EMPTY at the boundary, so neither event CAN fire. That is "
                "a strengthening, not a weakening — 'nothing was ever pooled' beats 'the "
                "pool was skipped', and it is carried by a positive event. The runtime "
                "emits no stash note, so the route additionally requires a POOL CENSUS "
                "taken on settled slide 2, inside the retire zone "
                f"[{RETIRE_ZONE_MIN_HASH}, {SLIDE3_MIN_HASH}), holding zero pooled and zero "
                "fromDom preserved entries for the key — a detached decoder can sit in the "
                "pool through slide 2 without ever being reused, so absence-of-notes alone is "
                "not evidence. A census that is missing, malformed or taken outside the zone "
                "invalidates the route, and the original positive pair is required instead."
            ),
            "detail": {
                "targetKey": target_key,
                "targetRestartDecoderId": target_restart_decoder_id,
                "poolCleared": clear_i is not None,
                "reuseSkipBoundaryForTargetN": len(reuse_skip_boundary_for_target),
                "reuseSkipBoundaryMatchingRestartN": len(reuse_skip_boundary_matching_restart),
                "retireEventsForTargetN": len(retire_events_for_target),
                "neverPooledEvidence": never_pooled,
                "reuseAfterBoundary": reuse_after_boundary[:6],
                "reuseAfterBoundaryScenes": [
                    (e.get("detail") or {}).get("sceneHash") for e in reuse_after_boundary[:6]
                ],
                "reuseStitchedRestart": reuse_stitched_restart[:6],
                "reuseSkipBoundaryEvents": reuse_skip_boundary_events[:6],
                "retireEvents": retire_events[:6],
            },
        },
        # ===== NEW FINDING: 3->4 moving Magic Move continuity (positive control) =====
        # Delimited for merge with Peer B's adversarial edits.
        {
            "id": "continueThroughMovingMagicMove3to4",
            "pass": bool(
                moving_continuity.get("ok", False)
                and moving_index_run.get("ok", False)
                and footprint_live.get("ok", False)
                and not player_build_errors
            ),
            "status": "failed-by-player" if player_build_errors else None,
            "detail": {
                "movingContinuity3to4": moving_continuity,
                "movingIndexRun": moving_index_run,
                "movingIndexRunAtCut": moving_index_run_at_cut,
                "footprintFullyLive": footprint_live,
                "burstOffsetsMs": list(BURST_OFFSETS_MS),
                "slide4ControlRect": SLIDE4_CONTROL_RECT,
                "hash": f"{hash3}->{hash4}",
                "slide4MinHash": SLIDE4_MIN_HASH,
                "slide3MovieRect": list(SLIDE3_MOVIE_RECT),
                "slide4MovieRect": list(SLIDE4_MOVIE_RECT),
                "bridgeEnabled": bridge34,
                "bridgeEvents": bridge_events,
                "ownerVias": [s.get("via") for s in owner_samples_c][:40],
                "slide4IndexSequence": slide4_index_seq,
                "playerBuildErrors": player_build_errors,
                "note": (
                    "The owner authored 3->4 as continuity ('Play movie across slides'), "
                    "but the HTML export RESTARTS movie1 on a fresh decoder at the grown "
                    "slide-4 footprint (Phase-0 diagnosis). The PRESERVE 3->4 bridge repairs "
                    "it by keeping the SAME decoder (the 2->3 restart decoder that played "
                    "slide 3) playing while its box translates+scales into slide 4, "
                    "suppressing the export's fresh autoplay-from-0 element. Pass gate is "
                    "movingContinuity3to4 (fail-closed: reached slide 4 (hn>=SLIDE4_MIN_HASH); "
                    "ONE stable non-null footprint owner across the slide-4 window, resolved "
                    "at the MOVING interpolated footprint keyed to movie1 so the retiring "
                    "right-side WA0125 the grown box overlaps is excluded; CROSSING IDENTITY "
                    "= that owner IS the slide-3 movie decoder, the anti-restart check a "
                    "fresh decoder fails; rVFC presentedMediaTime advancing >0.05 and never "
                    "rewinding = the live clock continues, not restarts) AND movingIndexRun "
                    "(the composited counter, decoded at the MOVING index_patch_roi_for ROI, "
                    "marches forward on slide 4) AND footprintFullyLive (the settled "
                    "slide-4 destination rect must PAINT: a 12-shot unevenly spaced burst "
                    "scored by html_alpha_probe.score_visible_slide with imported "
                    "thresholds, control patch inside the first empty corner; anything but "
                    "verdict True — including an inconclusive noise floor — fails). A raw "
                    "export with --disable-bridge34 "
                    "RESTARTS (fresh decoder) and fails crossingIdentity -> RED, so this is "
                    "an honest gate, never a false pass. A player-build-error fails it as "
                    "failed-by-player."
                ),
            },
        },
    ]

    # Phase 2 — composited-freeze negative control (Arm A), A-B-A bracket on the
    # 3->4 moving Magic Move boundary (the 1->2 carry is refused, so there is no
    # carried movie to freeze there — see the plan). Proves the COUNTER gate
    # (`movingIndexRunAtCut`) is not vacuous: an injected persistent VISIBLE
    # partial stale cover, tracking the MOVING measured footprint, turns it RED
    # ("freeze run at cut") in B while the bridged decoder + rVFC stay live, and
    # every other sub-verdict is identical across the two bracketing positives.
    # Runs on fresh boots (its own server + re-navigated Chrome per arm), so it
    # never perturbs the main pass above. SKIPPED under --disable-bridge34 (no
    # carry to freeze in that arm).
    freeze_control = await _run_freeze_bracket(player_dir, runs, wait_profile, wait_profile_name)
    freeze_blocks_success = _freeze_control_blocks_success(freeze_control.get("verdict"), not bridge34)
    findings.append(
        {
            "id": "freezeControlCaughtByCounter",
            "pass": not freeze_blocks_success,
            "verdict": freeze_control.get("verdict"),
            "detail": freeze_control,
            "note": (
                "Negative control (Arm A: bridged decoder LIVE, composite FROZEN), "
                "re-bracketed on the 3->4 moving Magic Move (the 1->2 carry is refused, "
                "so there is nothing to freeze there). An A-B-A bracket injects a partial "
                "(left ~40% of the MEASURED owner rect, re-tracked every rAF through the "
                "translate+scale) stale cover over the burnt-in counter for the middle run "
                "only. PASS requires: the at-cut counter run RED with reason 'freeze run "
                f"at cut' and freezeRunAtCut >= {FREEZE_MIN_RUN} (margin, no negative "
                "anomaly, flip window decodable on the measured-only sequence); the bridged "
                "decoder STILL live in B (movingContinuity3to4 ok, bound decoder == the "
                f"slide-3 movie decoder, rVFC advance >= {RVFC_MIN_ADVANCE_S}s, no "
                "player-build-error, bridge engaged); the freeze provably fired AT THE MOVE "
                "START (firedVia == 'motion', never a hash-only fire), the stage origin was "
                "(0,0) at arm, painted once, cover patch pixels identical hold-start vs "
                "release, elementFromPoint == cover for 100% of hold frames, the cover "
                "tracked the measured footprint within 2px on every hold frame, every "
                "in-hold decode from a MEASURED sample and == the expected stale index "
                "+/-2, released strictly between the last at-cut capture and the settled "
                "visible-content burst, and no per-rAF hold-log gap > "
                f"{MAX_RAF_GAP_MS:.0f}ms (disqualifying on this MOVING footprint); BOTH "
                "bracketing positives green; and every invariant sub-verdict equal across "
                "A1/B/A2. A hold that never fired is INCONCLUSIVE, never PASS/FAIL (an "
                "unfired hold would masquerade as a passing positive). Bridge-disabled: the "
                "bracket is SKIPPED (nothing to freeze), which is non-blocking ONLY in that "
                "arm — a 'skipped' verdict blocks success in every other arm."
            ),
        }
    )

    # Restart inconclusive must not count as overall success. The freeze bracket's
    # own pass/block rule lives in `_freeze_control_blocks_success` (owner decision
    # 8b): "inconclusive"/"fail" always block; "skipped" blocks unless the 3->4
    # bridge itself was disabled for this run (nothing to freeze there either).
    success = all(f["pass"] for f in findings) and not restart_inconclusive
    report = {
        "probe": "p2_recovery_html_adversarial",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": before.as_dict(),
        "sourceUnchanged": after.as_dict() == before.as_dict(),
        "deckFixture": "Minimal Alpha_DSK.key (owner adversarial 4-slide)",
        "fixture": "disposable-h264" if disposable_mode else "hevc-original",
        "assetReplace": asset_replace_info,
        "waitProfile": wait_profile_name,
        "waitProfileValues": wait_profile,
        "clickDelayS": wait_profile["clickDelayS"],
        "reusedExport": reuse,
        "stripPdf": strip_info,
        "preserve": preserve,
        "boot": boot,
        "preScores": pre_scores,
        "midScores": mid_scores,
        "continuityPlan": continuity_plan,
        "refusedCarry1to2": refused_carry,
        "footprintFullyLive": footprint_live,
        "continue1to2": cont,
        "visibleMovieMotion": visible_motion,
        "motionAcrossFlip": motion_across_flip,
        "decoderMotion": decoder_motion,
        "restart2to3": restart_scores,
        "perMovieBoundary": per_movie_boundary,
        "restartCanvas": restart_canvas,
        "restartVerdict": restart_verdict,
        "hashes": {"h1": hash1, "h2": hash2, "h3": hash3, "h4": hash4},
        "movingContinuity3to4": moving_continuity,
        "movingIndexRun3to4": moving_index_run,
        "bridge34Enabled": bridge34,
        "preserveEvents": preserve_events,
        "findings": findings,
        "freezeControl": freeze_control,
        "success": success,
        "p3": "still unwired",
        "rois": {
            "blackS1": BLACK_ROI_S1,
            "blackS2": BLACK_ROI_S2,
            "greenS1": GREEN_ROI_S1,
            "emptyCorners": EMPTY_CORNERS,
            "movie": list(MOVIE_ROI),
        },
        "tokens": {"movie1": MOVIE1_TOKEN, "movie2": MOVIE2_TOKEN},
        "note": (
            "Disposable H.264 fixture: Untitled.mov replaced with a browser-decodable "
            "yuv420p test pattern under the same filenames."
            if disposable_mode
            else (
                "Untitled.mov in this export is HEVC Main 10 — Chrome often advances "
                "currentTime (AAC) with videoWidth=0 (audio-only clock); decode/motion/"
                "restart findings cannot pass on this fixture. Pass --disposable to gate "
                "on the browser-decodable H.264 clone instead."
            )
        ),
    }
    write_json(OUT / "report.json", report)

    lines = [
        "# HTML adversarial gate — Minimal Alpha_DSK",
        "",
        f"Generated: {report['generated']}",
        f"Source unchanged: **{report['sourceUnchanged']}**",
        f"success: **{success}**",
        "",
        "## Findings",
        "",
    ]
    for f in findings:
        extra = f" — {f['note']}" if f.get("note") else ""
        verdict = f" ({f['verdict']})" if f.get("verdict") and f["verdict"] != ("pass" if f["pass"] else "fail") else ""
        lines.append(f"- {f['id']}: **{f['pass']}**{verdict}{extra}")
    lines += ["", f"Samples: `{OUT}`", "", "P3 still unwired."]
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return report


def main() -> int:
    reuse = "--reuse-export" in sys.argv
    if keynote_running() and not reuse:
        raise SystemExit(
            "Keynote is already running — refuse to force-quit an owner session. "
            "Quit Keynote and re-run, or pass --reuse-export."
        )
    report = asyncio.run(_run(OUT / "html-player"))
    return 0 if report.get("sourceUnchanged") and report.get("success") else (2 if not report.get("sourceUnchanged") else 1)


if __name__ == "__main__":
    raise SystemExit(main())
