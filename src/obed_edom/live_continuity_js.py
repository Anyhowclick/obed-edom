"""Shared preserve-runtime JS core injected by P2 scripts and (later) the live host.

PRESERVE_CORE_JS mirrors 'src/obed_edom/live_runtime.py': one pinned copy of the
injected bytes, versioned and hashed. Verbatim carry-over from
`scripts/p2_recovery_html_dissolve_live.py` PRESERVE_SCRIPT (I0 step A), with the
dead canvas texture-feed stack removed (I0 step B) and the fixture constants
parameterised via one injected plan object (I0 step C).

Plan object (`window.__OBED_CONTINUITY__`, set before this script runs; absent,
or any `schema` other than 2 => the core installs nothing):
    {
      "schema": 2,
      "movies": {
        "<movieKey>": {"assetKeys": ["<substring(s) of the <video> src>"],
                        "footprint": {"x": int, "y": int, "w": int, "h": int}}
      },
      "boundaries": [   // one entry per (boundary, planned instance)
        {"atScene": <scene index>, "action": "pin" | "bridge" | "restart" | "retire" | "glReplay",
         "movieKey": "<movieKey>",
         "src": {"objectId": "<export objectID>", "rect": {"x", "y", "w", "h"}},
         "dst": {"objectId": ..., "rect": ...},        // pin/bridge/glReplay; restart optional
         "loop": <bool>,                               // pin/bridge/glReplay
         "durationSeconds": <positive exported duration>,   // bridge
         "reason": "refused" | "ends"}                 // retire
      ],
      "transparentBackground": <bool, optional, default false>
    }
`movies[k].footprint` (the asset's first planned instance rect) is read only
by `footprintOwnerDecoderId`, for the instrument; nothing positions from it.
`transparentBackground` gates `forceTransparentChrome()`: true for the
alpha/attach output and for the P2 scripts (their fixed black background is
the runtime's, not the player's), false for HDMI where the player's own black
background must show through untouched (owner decision 2a).

Instance identity is the export's objectID: the player sets a movie element's
`id` to `objectID + "-video"` before its `src`, so the src hooks stamp
`__obedInstance`; a carry re-stamps the carried decoder to the entry's
`dst.objectId` (after a bridge its DOM id still names the old source). A
decoder is pooled only when the entry naming its instance as `src` is a
pin/bridge/glReplay (or a restart of a decoder the runtime already holds, so
the outgoing movie survives the Dissolve); every other `<video>` passes
through. At the fresh `dst` element of a pin/bridge the one candidate (pooled
or held) whose instance is the entry's `src` is carried: a pin facades the
fresh element onto it, a bridge moves it `src.rect -> dst.rect` over the
transition scene and suppresses the fresh element. Zero or several
candidates, or a `loop` mismatch, refuse that one boundary (`preserve-refused`
with `reason`) and the fresh element plays raw. A restart retires a held
`src` decoder when a fresh element of the same movie sets `src` at or after
`atScene`. A retire hands `src` back to the raw player from the transition
scene (`atScene - 1`, where the player already detaches the movie): nothing
pooled, clears really run, every declining hook notes `preserve-refused`
(once per instance and hook) and the keep-warm interval sweeps held/pooled
decoders, noting `retire-boundary` -- refusal is asserted by a positive event,
never by silence.

A "glReplay" entry (`fallback: "retire"`, `instanceRect` authored px) is the
same retire-class zone run as a one-shot state machine for the GL-replay module
(`live_gl_replay_js.py`), keyed on its src/dst instances from `atScene - 1` to
the next entry naming `dst` as `src`: `pending -> armed | retired`, `armed ->
released | retired`, `released -> retired`, each transition noted
`glreplay-zone {key, from, to, reason}`. `pending` and `retired` refuse like
the retire zone; `armed` pools the detached `src` decoder but never mounts or
paints it; `released` is pin. The module talks to it only through
`window.__OBED_P2_PRESERVE__.glReplay` (installed only for such a plan).
Plan: the G3+G4 plan §1–§2 (PR #214).

The bridge moves during the preceding transition scene using linear interpolation
over the exported duration. This is a fallback for WebGL movie geometry with no
unambiguous animated DOM rectangle; it does not attest native Keynote easing.

Scaled-stage mapping (I3): the player scales `#stage` with a CSS transform, so
`#stage.offsetWidth/Height` (authored px, transform-blind) and
`#stage.getBoundingClientRect()` (on-screen px) diverge whenever the viewport
is not the authored canvas size. `stageMap()` reads both live (no caching) and
returns `{s, ox, oy, authoredWidth, authoredHeight}`, `null` when `#stage` is
missing, degenerate, or non-uniformly scaled. Plan rects (`movies[k].footprint`,
entry `src.rect`/`dst.rect`) are authored px; `getBoundingClientRect()`
measurements are screen px. Stage-level overlays (appended to `document.body`)
write screen px via `toScreen()`; in-layer remounts (inside `#stage`) divide by
`s`. `disable()` clears preserved state and makes every hook a pass-through
for the host to fall back to the raw player without a reload, but only before
anything has ever been preserved — once a video has been stashed it returns
`false` and does nothing, since a later disable cannot unwind a live facade,
bridge or suppress loop.
"""
from __future__ import annotations

import hashlib

CONTINUITY_VERSION = 6

PRESERVE_CORE_JS = r"""
(function(){
  // Fail-closed: no plan, no install. The caller (P2 script or, later, the
  // live host) injects window.__OBED_CONTINUITY__ before this script tag runs.
  var OBED_PLAN = window.__OBED_CONTINUITY__;
  if (!OBED_PLAN || OBED_PLAN.schema !== 2) return;
  if (window.__OBED_P2_PRESERVE__) return;
  let disabled = false;
  let everPreserved = false;
  window.__OBED_P2_PRESERVE__ = {
    version: 9,
    mode: 'decoder-preserve',
    events: [],
    poolKeys: [],
    stageMap: function() { return stageMap(); },
    disable: function() {
      if (everPreserved) return false;
      disabled = true;
      try { window.__OBED_P2_PRESERVE__.clear(); } catch (e) {}
      window.__OBED_P2_PRESERVE__.disabled = true;
      return true;
    },
    remountAll: function() {
      let n = 0;
      pool.forEach(function(q) {
        (q || []).forEach(function(v) {
          tryRemount(v);
          n += 1;
        });
      });
      document.querySelectorAll('video[data-obed-preserved="1"]').forEach(function(v) {
        tryRemount(v);
        n += 1;
      });
      return n;
    },
    clear: function() {
      // Drop pooled handles and tear down remount overlays so a deliberate
      // restart measurement is not polluted by continued slide-1/2 clocks.
      remountEpoch += 1;
      preserveGeneration += 1;
      suppressRemount = true;
      try {
        pool.clear();
        const dropped = held.splice(0, held.length);
        Array.from(document.querySelectorAll('video[data-obed-preserved="1"]')).concat(dropped).forEach(function(v) {
          if (v.__obedGen === -1) return;
          try {
            v.pause();
            delete v.dataset.obedPreserved;
            v.__obedRemountEpoch = -1;
            v.__obedGen = -1;
            if (v.parentNode) {
              beginMove(v);
              v.parentNode.removeChild(v);
            }
          } catch (e) {}
        });
        note('pool-cleared', {
          remountEpoch: remountEpoch,
          preserveGeneration: preserveGeneration
        });
      } finally {
        suppressRemount = false;
      }
      if (zone === 'armed' || zone === 'released') retireZone('cleared');
    },
    snapshot: function() {
      const out = [];
      pool.forEach(function(q, key) {
        (q || []).forEach(function(v) {
          out.push({
            key: key,
            movieKey: movieAssetKey(key) || v.__obedMovieKey || null,
            instance: v.__obedInstance || null,
            elId: v.__obedElId,
            currentTime: v.currentTime,
            paused: v.paused,
            readyState: v.readyState,
            ended: v.ended,
            inDocument: document.contains(v),
            videoWidth: v.videoWidth,
            videoHeight: v.videoHeight
          });
        });
      });
      document.querySelectorAll('video[data-obed-preserved="1"]').forEach(function(v) {
        const src = v.currentSrc || v.src || '';
        out.push({
          key: assetKey(src),
          // A really-cleared src leaves `key` empty; the stamp still attributes it.
          movieKey: movieKeyFor(v, src),
          instance: v.__obedInstance || null,
          elId: v.__obedElId,
          currentTime: v.currentTime,
          paused: v.paused,
          readyState: v.readyState,
          ended: v.ended,
          inDocument: document.contains(v),
          fromDom: true,
          videoWidth: v.videoWidth,
          videoHeight: v.videoHeight
        });
      });
      return out;
    },
    /** Draw a pooled/preserved video frame to a data URL (decoder pixels, not page composite). */
    sampleFrame: function(elId) {
      let target = null;
      let where = null;
      pool.forEach(function(q) {
        (q || []).forEach(function(v) {
          if (v.__obedElId === elId) { target = v; where = 'pool'; }
        });
      });
      if (!target) {
        document.querySelectorAll('video').forEach(function(v) {
          if (v.__obedElId === elId) { target = v; where = 'dom'; }
        });
      }
      // Facade stubs proxy clocks but have no decoded pixels — draw the real decoder.
      if (target && target.__obedFacadeFor) {
        target = target.__obedFacadeFor;
        where = (where || 'facade') + '+real';
      }
      if (!target) {
        return {ok: false, reason: 'not-found', elId: elId, snap: window.__OBED_P2_PRESERVE__.snapshot()};
      }
      const vw = target.videoWidth || 0;
      const vh = target.videoHeight || 0;
      if (!(vw > 0 && vh > 0)) {
        return {
          ok: false,
          reason: 'no-video-pixels',
          elId: elId,
          where: where,
          currentTime: target.currentTime,
          readyState: target.readyState,
          videoWidth: vw,
          videoHeight: vh,
          paused: target.paused,
          inDocument: document.contains(target)
        };
      }
      const c = document.createElement('canvas');
      const w = Math.min(320, vw);
      const h = Math.round(w * vh / vw);
      c.width = w; c.height = h;
      try {
        c.getContext('2d').drawImage(target, 0, 0, w, h);
        return {
          ok: true,
          elId: elId,
          realElId: target.__obedElId,
          where: where,
          currentTime: target.currentTime,
          width: w,
          height: h,
          dataURL: c.toDataURL('image/jpeg', 0.7)
        };
      } catch (e) {
        return {ok: false, reason: 'draw-failed', message: String(e && e.message || e), elId: elId, where: where};
      }
    },
    /** Which live decoder owns an authored rect's movie footprint. */
    /**
     * Corrected 1->2 model (Step 2): the continuing movie is a live `<video>` at
     * the footprint, never fed into a 2D canvas, so a canvas-authored resolution
     * can never own it. Resolve the owner from the POSITIONED movie `<video>`s
     * instead: the decoded movie
     * `<video>` whose rendered rect best-overlaps `rect`. The two `untitled.mov`
     * instances share assetKey `movie1`, so OVERLAP (not asset key) disambiguates
     * them — the off-footprint sibling has zero overlap. Fail closed on an unknown
     * footprint, zero overlap, or a distinct-decoder tie in the top overlap band.
     * A `<video>` has no 2D context stamp, so contextType is null.
     *
     * `rect` is AUTHORED px (I3): classify the key against the plan footprint
     * table in the same authored space (no scaling needed), then map to screen
     * px once before comparing against `getBoundingClientRect()`.
     */
    footprintOwnerDecoderId: function(rect) {
      // The caller may pin the asset key directly (rect.key) when it queries a
      // rect the fixed footprint table does not classify — e.g. the moving/scaling
      // 3->4 slot, resolved by interpolated rect + assetKey==untitled. Otherwise
      // classify by the fixed slide-1/2 footprint table.
      const wantKey = (rect && rect.key) ? rect.key : footprintKeyForRect(rect);
      // Unresolved footprint key -> fail closed, never admit any movie key
      // (Codex r5 F2): the helper must not own a rect it cannot identify.
      if (wantKey == null) return {elId: null, key: null, via: 'unknown-key', contextType: null};
      const map = stageMap();
      if (!map) return {elId: null, key: null, via: 'no-stage-map', contextType: null};
      const screenRect = toScreen(rect, map);
      // Collect the positioned movie <video>s (DOM + pool, deduped) whose rendered
      // rect closely MATCHES the footprint, THEN decide ownership from the global
      // maximum overlap — order-independent so a later-best cannot mis-clear an
      // earlier tie. Gate on intersection-over-union (IoU), not bare overlap: IoU
      // penalises BOTH a too-small owner (partial / quarter-sized / mis-scaled
      // remount rendering smaller than the authored box) AND a too-large one (a
      // giant surface that merely contains the footprint), so only a <video>
      // rendered at ~the footprint geometry can own it (fail closed otherwise).
      const fpArea = Math.max(1, screenRect.w * screenRect.h);
      const cands = [];
      const seen = [];
      function consider(v) {
        if (!(v instanceof HTMLVideoElement) || seen.indexOf(v) >= 0) return;
        seen.push(v);
        if (!(v.readyState >= 2 && v.videoWidth > 0)) return;
        const key = movieAssetKey(v.currentSrc || v.src || '');
        if (key !== wantKey) return;
        // A hidden element does not composite, so it cannot own the visible
        // footprint. Skip it — otherwise a suppressed 3->4 restart sibling (same
        // untitled key, same slot, opacity 0) would tie with the visible bridged
        // overlay and fail the owner resolution as ambiguous.
        if (!isCompositing(v)) return;
        const r = v.getBoundingClientRect();
        if (!(r.width > 1 && r.height > 1)) return;
        const ov = rectOverlapArea(r, screenRect);
        if (!(ov > 0)) return;
        const union = (r.width * r.height) + fpArea - ov;
        const iou = union > 0 ? ov / union : 0;
        // High IoU floor: the rendered rect must closely match the footprint. 0.75
        // rejects a 60%-width partial (0.60), a 125%-uniform-scale container (0.64),
        // and a 160%-width surface (0.625) that a looser floor admitted.
        if (!(iou >= 0.75)) return;
        cands.push({v: v, ov: ov, iou: iou, key: key});
      }
      document.querySelectorAll('video').forEach(consider);
      pool.forEach(function(q) { (q || []).forEach(consider); });
      if (!cands.length) return {elId: null, key: null, via: 'none', contextType: null};
      // Rank by IoU, not raw overlap: an OVERSIZED sibling that merely contains the
      // footprint has large overlap but low IoU, and must not beat the true owner.
      let bestIou = 0;
      cands.forEach(function(x) { if (x.iou > bestIou) bestIou = x.iou; });
      const tol = Math.max(1e-6, bestIou * 0.05);
      // Everything within tol of the global-max IoU is the "top band". If it holds
      // more than ONE distinct decoder, ownership is AMBIGUOUS -> null (fail closed).
      const eps = Math.max(1e-9, bestIou * 1e-9);
      const near = cands.filter(function(x) { return x.iou >= bestIou - tol - eps; });
      let distinct = [];
      near.forEach(function(x) { if (distinct.indexOf(x.v) < 0) distinct.push(x.v); });
      // An unplanned same-asset copy (no entry names its instance) never makes
      // the planned instance's footprint ambiguous; a tie among planned ones does.
      if (distinct.length > 1) distinct = distinct.filter(isPlannedDecoder);
      if (distinct.length !== 1) {
        return {elId: null, key: null, via: 'ambiguous', contextType: null};
      }
      const owner = near.filter(function(x) { return x.v === distinct[0]; })
        .reduce(function(a, b) { return b.iou > a.iou ? b : a; });
      return {elId: owner.v.__obedElId, key: owner.key, via: 'footprint-video', contextType: null};
    }
  };
  const pool = new Map(); // assetKey -> HTMLVideoElement[] (FIFO; same file may appear twice)
  let nextId = 1;
  let suppressRemount = false;
  let remountEpoch = 0;
  // clear() bumps this so pre-clear decoders cannot re-enter the pool / remount.
  // Videos created after clear get the new generation and remount normally.
  let preserveGeneration = 0;
  const stageMapWarned = {};
  const refusedNoted = {};
  // Plan rects are AUTHORED px; getBoundingClientRect() and <body>-level overlays
  // are SCREEN px; inline styles inside the transform-scaled #stage are AUTHORED px.
  function stageMap() {
    const stage = document.getElementById('stage');
    if (!stage) return null;
    const ow = stage.offsetWidth, oh = stage.offsetHeight;
    if (!(ow > 1 && oh > 1)) return null;
    const r = stage.getBoundingClientRect();
    if (!(r.width > 1 && r.height > 1)) return null;
    const sx = r.width / ow, sy = r.height / oh;
    const avg = (sx + sy) / 2;
    if (!(avg > 0) || Math.abs(sx - sy) / avg > 0.001) return null;
    return {s: sx, ox: r.left, oy: r.top, authoredWidth: ow, authoredHeight: oh};
  }
  function toScreen(rect, map) {
    const m = map || stageMap();
    if (!m) return null;
    return {x: rect.x * m.s + m.ox, y: rect.y * m.s + m.oy, w: rect.w * m.s, h: rect.h * m.s};
  }
  function noteStageMapUnavailable(kind) {
    if (stageMapWarned[kind]) return;
    stageMapWarned[kind] = true;
    note('stage-map-unavailable', {consumer: kind});
  }
  function assetKey(src) {
    const s = String(src || '');
    const tail = (s.split('/').pop() || s).split('?')[0];
    const m = tail.match(/^(.+\.(mov|mp4|m4v))-\d+\.\d+-\d+\.\d+\.\2$/i);
    if (m) return m[1].toLowerCase();
    return tail.toLowerCase();
  }
  function currentHashNum() {
    const m = /^#?(\d+)/.exec(String(location.hash || ''));
    return m ? parseInt(m[1], 10) : null;
  }
  // One entry per (boundary, planned instance); `src`/`dst` name export objectIDs.
  const CARRY_ACTIONS = ['pin', 'bridge', 'glReplay'];
  const ENTRIES = (Array.isArray(OBED_PLAN.boundaries) ? OBED_PLAN.boundaries : []).filter(function(b) {
    return !!b && typeof b.atScene === 'number' && typeof b.action === 'string'
      && !!b.src && typeof b.src.objectId === 'string';
  });
  // The entry naming `inst` as its src: that instance's next boundary (at most one).
  function nextEntry(inst) {
    if (inst == null) return null;
    for (let i = 0; i < ENTRIES.length; i++) {
      if (ENTRIES[i].src.objectId === inst) return ENTRIES[i];
    }
    return null;
  }
  // The pin/bridge whose fresh `dst` element is `inst`.
  function carryEntryTo(inst) {
    if (inst == null) return null;
    for (let i = 0; i < ENTRIES.length; i++) {
      const b = ENTRIES[i];
      if ((b.action === 'pin' || b.action === 'bridge') && b.dst && b.dst.objectId === inst) return b;
    }
    return null;
  }
  // The player sets `id = objectID + "-video"` before `src` (F1), so the src hooks can stamp it.
  function instanceFromId(v) {
    const id = String((v && v.id) || '');
    return /-video$/.test(id) ? id.slice(0, -6) : null;
  }
  function instanceOf(v) {
    return v && v.__obedInstance != null ? v.__obedInstance : null;
  }
  function namesInstance(b, inst) {
    return inst != null && (b.src.objectId === inst || (!!b.dst && b.dst.objectId === inst));
  }
  function glZoneEnd() {
    const n = GL.dst ? nextEntry(GL.dst.objectId) : null;
    return n ? n.atScene : Infinity;
  }
  // The zone OPENS on the transition scene (`atScene - 1`, the same convention
  // keepThroughBridge uses for the move scene): the player detaches the movie
  // while the hash is still the transition's, so a zone starting at atScene
  // would pool and remount the refused movie for the whole Magic Move. Idle at
  // the end of the source slide the hash already reads `atScene - 1`, so a
  // retire opens there only once the player has torn the instance down
  // (`hasDeparted`). A retire names only its `src` instance, so it needs no end;
  // a glReplay zone ends at the next entry naming its `dst`.
  function inRetireZone(b) {
    const hn = currentHashNum();
    if (hn == null) return false;
    if (b === GL) return hn >= b.atScene - 1 && hn < glZoneEnd();
    return hn >= b.atScene || (hn === b.atScene - 1 && hasDeparted(b.src.objectId));
  }
  // Identity must survive a real src clear: inside the zone the hooks let the
  // player's clear through, so `movieAssetKey(src)` goes null on a decoder we
  // already know. `stash()` and the createElement src hook stamp
  // `__obedMovieKey` the first time the key is resolvable; read it back here.
  function movieKeyFor(v, src) {
    return movieAssetKey(src) || (v && v.__obedMovieKey) || null;
  }
  /**
   * Re-identify a <video> on a non-empty source assignment. An element given a
   * DIFFERENT asset is no longer the movie it was pooled as, so drop its pool
   * membership and preserved mark before restamping — and the stamp becomes
   * null when the new asset is not in the plan, or the retire sweep would take
   * an element that is now an unplanned clip. Assigning the SAME asset changes
   * nothing: the reuse/facade path re-assigns src on a live decoder.
   */
  function reidentify(v, value) {
    const next = assetKey(value);
    if (!next) return;
    const prev = v.__obedAssetKey != null ? v.__obedAssetKey : assetKey(v.currentSrc || v.src || '');
    v.__obedAssetKey = next;
    if (prev === next) {
      if (v.__obedInstance === undefined) v.__obedInstance = instanceFromId(v);
      return;
    }
    if (GL) {
      v.__obedGlPooled = false;
      const gi = glPooled.indexOf(v);
      if (gi >= 0) glPooled.splice(gi, 1);
      if (carriedMemo === v) carriedMemo = null;
      delete v.__obedAuthoredRect;
      delete v.__obedAuthoredRectScene;
    }
    if (prev) {
      unpool(v);
      const hi = held.indexOf(v);
      if (hi >= 0) held.splice(hi, 1);
      delete v.__obedHold;
      delete v.dataset.obedPreserved;
    }
    v.__obedMovieKey = movieAssetKey(value);
    v.__obedInstance = instanceFromId(v);
  }
  const holdNoted = {};
  // Decoders the runtime carries (facaded pin, bridge overlay, released glReplay):
  // the player never detaches them, so they never reach `stash`.
  const held = [];
  const GL = ENTRIES.filter(function(b) { return b.action === 'glReplay'; })
    .reduce(function(a, b) { return a && a.atScene <= b.atScene ? a : b; }, null);
  const GL_NOTE_KINDS = ['glreplay-arm', 'glreplay-live', 'glreplay-standdown', 'glreplay-handoff',
    'glreplay-opacity-unproven', 'glreplay-retained-frame'];
  let zone = GL ? 'pending' : null;
  let armSeen = false;
  let liveSeen = false;
  let carriedMemo = null;
  const glPooled = [];
  /**
   * How this instance may be preserved at the current scene: 'allow', 'refuse'
   * (a retire zone for its `src`, or a pending/retired glReplay zone), or, for a
   * glReplay zone, 'armed' (pool-but-never-mount) / 'released' (pin). Always
   * evaluates `zoneState()` first.
   */
  function zoneMode(v) {
    const z = zoneState(false);
    const inst = instanceOf(v);
    if (inst == null) return 'allow';
    if (GL && namesInstance(GL, inst) && inRetireZone(GL)) {
      return (z === 'armed' || z === 'released') ? z : 'refuse';
    }
    const n = nextEntry(inst);
    return n && n.action === 'retire' && inRetireZone(n) ? 'refuse' : 'allow';
  }
  function noteRefused(v, src, via, extra) {
    const key = movieKeyFor(v, src);
    const inst = instanceOf(v);
    const seen = [key, via, inst, extra ? extra.reason : ''].join('|');
    if (refusedNoted[seen]) return;
    refusedNoted[seen] = true;
    note('preserve-refused', Object.assign({key: key, scene: currentHashNum(), via: via, instance: inst}, extra || {}));
  }
  function noteHold(v, src, via) {
    const key = movieKeyFor(v, src);
    const seen = key + '|' + via;
    if (holdNoted[seen]) return;
    holdNoted[seen] = true;
    note('glreplay-hold', {key: key, via: via});
  }
  function finiteRect(r, min) {
    return !!r && typeof r === 'object' && [r.x, r.y, r.w, r.h].every(function(n) {
      return typeof n === 'number' && isFinite(n);
    }) && r.w > min && r.h > min;
  }
  function glEntryValid() {
    return GL.fallback === 'retire' && Object.prototype.hasOwnProperty.call(planMovies(), GL.movieKey)
      && finiteRect(GL.instanceRect, 0) && !!GL.dst && typeof GL.dst.objectId === 'string';
  }
  function setZone(to, reason, extra) {
    const from = zone;
    zone = to;
    note('glreplay-zone', Object.assign({key: GL.movieKey, from: from, to: to, reason: reason}, extra || {}));
  }
  /**
   * The one owner of every glReplay zone transition except `release`'s own.
   * `inRelease` skips the `moduleRetired` watchdog: the module is in STANDDOWN
   * while it calls `release` and only goes RETIRED after it returns.
   */
  function zoneState(inRelease) {
    if (!GL) return null;
    if (disabled && zone !== 'retired') {
      retireZone('disabled');
      return zone;
    }
    if (zone === 'pending') {
      if (document.readyState === 'loading') return zone;
      const m = window.__OBED_GL_REPLAY__;
      const why = !glEntryValid() ? 'entryInvalid'
        : !m ? 'moduleAbsent'
        : m.version !== 1 ? 'moduleVersion'
        : m.state === 'RETIRED' ? 'moduleRetired' : null;
      if (why) {
        retireZone(why);
        return zone;
      }
      setZone('armed', 'moduleReady');
    }
    const hn = currentHashNum();
    if (zone === 'armed') {
      const m = window.__OBED_GL_REPLAY__;
      if (!inRelease && m && m.state === 'RETIRED') retireZone('moduleRetired');
      else if (hn != null && hn >= GL.atScene && !armSeen) retireZone('unengaged');
      else if (hn != null && hn >= glZoneEnd()) retireZone('leftDestination');
    } else if (zone === 'released' && hn != null && hn < GL.atScene) {
      retireZone('leftDestination');
    }
    return zone;
  }
  /**
   * Transition to `retired`: retire the carried memo and every decoder pooled
   * while armed at any scene, plus today's retire-zone selection only inside
   * the zone, so a decoder pooled under pin/bridge/restart elsewhere survives.
   */
  function retireZone(reason, extra) {
    setZone('retired', reason, extra);
    const victims = [];
    [carriedMemo].concat(glPooled).forEach(function(v) {
      if (v && v.__obedGen !== -1 && victims.indexOf(v) < 0
          && movieKeyFor(v, v.currentSrc || v.src || '') === GL.movieKey) victims.push(v);
    });
    if (inRetireZone(GL)) zoneVictims(GL, victims);
    return retireVictims(GL, victims, true);
  }
  function isLive(v) {
    return (v.__obedGen == null ? 0 : v.__obedGen) === preserveGeneration;
  }
  function authoredRectOf(r) {
    if (!GL) return null;
    const m = stageMap();
    if (!m) return null;
    return {x: (r.left - m.ox) / m.s, y: (r.top - m.oy) / m.s, w: r.width / m.s, h: r.height / m.s};
  }
  function rectDelta(a, b) {
    return Math.max(Math.abs(a.x - b.x), Math.abs(a.y - b.y), Math.abs(a.w - b.w), Math.abs(a.h - b.h));
  }
  function glCarried(movieKey) {
    const z = zoneState(false);
    if (disabled) return {video: null, reason: 'disabled'};
    if (z !== 'armed' || movieKey !== GL.movieKey) return {video: null, reason: 'notArmed'};
    if (carriedMemo) return {video: carriedMemo, reason: null};
    const cands = [];
    pool.forEach(function(q) {
      (q || []).forEach(function(v) {
        if (cands.indexOf(v) >= 0 || document.contains(v)) return;
        if (v.__obedInstance !== GL.src.objectId) return;
        if (movieKeyFor(v, v.currentSrc || v.src || '') !== movieKey) return;
        if (!isLive(v) || v.ended || v.dataset.obedRemounted === '1' || !v.__obedGlPooled || v.__obedFacadeFor) return;
        cands.push(v);
      });
    });
    if (!cands.length) return {video: null, reason: 'notPooled'};
    const measured = cands.filter(function(v) {
      return finiteRect(v.__obedAuthoredRect, 0) && v.__obedAuthoredRectScene === GL.atScene - 1;
    });
    if (!measured.length) return {video: null, reason: 'unmeasured'};
    const matches = measured.filter(function(v) { return rectDelta(v.__obedAuthoredRect, GL.instanceRect) <= 1.0; });
    if (matches.length !== 1) return {video: null, reason: 'ambiguous'};
    const v = matches[0];
    carriedMemo = v;
    v.__obedGlCarried = true;
    note('glreplay-carried', {
      elId: v.__obedElId,
      delta: rectDelta(v.__obedAuthoredRect, GL.instanceRect),
      candidates: cands.map(function(c) { return {elId: c.__obedElId, rect: c.__obedAuthoredRect || null}; })
    });
    return {video: v, reason: null};
  }
  function handbackRectOk(r, map) {
    if (!finiteRect(r, 1)) return false;
    const ir = GL.instanceRect;
    const left = ir.x - r.x, top = ir.y - r.y;
    const right = (r.x + r.w) - (ir.x + ir.w), bottom = (r.y + r.h) - (ir.y + ir.h);
    if (![left, top, right, bottom].every(function(m) { return m >= -0.5 && m <= 8; })) return false;
    if (!map) return true;
    const s = toScreen(GL.instanceRect, map);
    const nearZero = Math.abs(s.x) < 2 && Math.abs(s.y) < 2;
    const nearStageOrigin = Math.abs(s.x - map.ox) < 2 && Math.abs(s.y - map.oy) < 2;
    return !nearZero && !nearStageOrigin;
  }
  function lastStandDown() {
    try {
      const sd = window.__OBED_GL_REPLAY__.standDowns;
      return Array.isArray(sd) && sd.length ? sd[sd.length - 1] : null;
    } catch (e) {
      return null;
    }
  }
  /** Seam `release`: hand the carried decoder to pin, or fall back to retire (plan §2). */
  function glRelease(movieKey, opts) {
    const out = {ok: false, reason: null, mode: null, elId: null, retired: []};
    let decided = false;
    function retire(reason, extra) {
      decided = true;
      out.ok = true;
      out.mode = 'retire';
      out.reason = reason;
      out.elId = carriedMemo ? carriedMemo.__obedElId : null;
      out.retired = out.retired.concat(retireZone(reason, extra));
    }
    try {
      const z = zoneState(true);
      if (disabled) {
        out.reason = 'disabled';
      } else if (!GL || movieKey !== GL.movieKey) {
        out.reason = 'unknownMovie';
      } else if (z !== 'armed') {
        out.reason = 'notArmed';
      } else {
        decided = true;
        releaseArmed(opts, out, retire);
      }
    } catch (e) {
      const message = String(e && e.message || e);
      if (zone === 'armed' || zone === 'released') {
        retire('releaseError', {message: message});
      } else if (decided) {
        retireVictims(GL, [carriedMemo].concat(glPooled).filter(function(v) { return v && v.__obedGen !== -1; }), true);
        out.ok = true;
        out.mode = 'retire';
        out.reason = 'releaseError';
      } else {
        out.reason = 'releaseError';
      }
    }
    note('glreplay-release', out);
    return out;
  }
  function releaseArmed(opts, out, retire) {
    const primary = lastStandDown();
    if (primary !== 'canvasRemoved') return retire('failure', {standDown: primary == null ? null : String(primary)});
    if (!liveSeen) return retire('notLive');
    const hn = currentHashNum();
    if (!(hn != null && hn >= GL.atScene && hn < glZoneEnd())) return retire('notOnDestination');
    const v = carriedMemo;
    if (!v || !isLive(v) || movieKeyFor(v, v.currentSrc || v.src || '') !== GL.movieKey) return retire('noCarried');
    if (v.ended) return retire('ended');
    if (!(v.readyState >= 2) || !(v.currentSrc || v.src)) return retire('noCarried');
    const rect = opts && opts.rect;
    const map = stageMap();
    if (!handbackRectOk(rect, map)) return retire('badRect');
    if (!map) return retire('noStageMap');
    const screen = toScreen(GL.instanceRect, map);
    const canvas = findMovieCanvas(screen, v);
    if (!canvas || !canvas.parentNode) return retire('noAuthoredLayer');
    const siblings = zoneVictims(GL, glPooled.filter(function(x) {
      return x.__obedGen !== -1 && movieKeyFor(x, x.currentSrc || x.src || '') === GL.movieKey;
    })).filter(function(x) { return x !== v; });
    out.retired = retireVictims(GL, siblings, false);
    v.__obedRect = screen;
    v.__obedParent = null;
    v.__obedGlNoWarm = false;
    hold(v, GL);
    setZone('released', 'handoff');
    tryRemount(v);
    if (!(v.parentNode === canvas.parentNode && v.previousSibling === canvas)) return retire('remountFailed');
    out.ok = true;
    out.mode = 'handoff';
    out.elId = v.__obedElId;
  }
  function nearestLayer(el) {
    let n = el;
    while (n) {
      if (n.id && n.id.indexOf('layer') === 0) return n;
      n = n.parentElement;
    }
    return null;
  }
  function note(kind, detail) {
    const d = Object.assign({}, detail || {}, {sceneHash: String(location.hash || '')});
    window.__OBED_P2_PRESERVE__.events.push({kind: kind, detail: d, t: performance.now()});
    window.__OBED_P2_PRESERVE__.poolKeys = Array.from(pool.keys());
  }
  function tag(v) {
    if (!v.__obedElId) v.__obedElId = nextId++;
    if (v.__obedGen == null) v.__obedGen = preserveGeneration;
    return v.__obedElId;
  }
  /**
   * Pool only a decoder whose instance's next entry carries it, or one the
   * runtime already holds into a restart (it keeps painting through the Dissolve
   * until the fresh element retires it). Every other `<video>` passes through.
   */
  function poolable(v) {
    const n = nextEntry(instanceOf(v));
    return !!n && (CARRY_ACTIONS.indexOf(n.action) >= 0 || (n.action === 'restart' && held.indexOf(v) >= 0));
  }
  /**
   * The hash reads `atScene - 1` both while the player idles at the end of the
   * source slide (it shows the NEXT scene when idle) and while it plays that
   * transition scene. The player tears no <video> down at rest, so any teardown
   * of its own at that hash marks the transition. The mark is per scene, not per
   * instance: a decoder the runtime placed itself may never be torn down. It
   * lapses as soon as the hash moves. A retire whose transition this is hands
   * its held decoder back right there, so the raw player draws the fade-out.
   */
  let departure = null;
  function noteDeparture(v) {
    if (v.__obedRemounting) return;
    const hn = currentHashNum();
    if (hn == null) return;
    departure = {scene: hn, gen: preserveGeneration};
    ENTRIES.forEach(function(b) {
      if (b.action === 'retire' && b.atScene - 1 === hn) retireVictims(b, zoneVictims(b, []), true);
    });
  }
  function hasDeparted(inst) {
    const n = nextEntry(inst);
    const hn = currentHashNum();
    return !!n && !!departure && departure.gen === preserveGeneration
      && departure.scene === hn && hn === n.atScene - 1;
  }
  function isPlannedDecoder(v) {
    const inst = instanceOf(v);
    return held.indexOf(v) >= 0 || isPooled(v)
      || (inst != null && ENTRIES.some(function(b) { return namesInstance(b, inst); }));
  }
  function isPooled(v) {
    let found = false;
    pool.forEach(function(q) { if ((q || []).indexOf(v) >= 0) found = true; });
    return found;
  }
  function unpool(v) {
    const empties = [];
    pool.forEach(function(q, key) {
      const left = (q || []).filter(function(x) { return x !== v; });
      if (left.length === (q || []).length) return;
      if (left.length) pool.set(key, left); else empties.push(key);
    });
    empties.forEach(function(key) { pool.delete(key); });
  }
  // The carried decoder now IS the destination instance (F1: a bridge leaves its DOM id stale).
  function hold(v, entry) {
    v.__obedInstance = entry.dst.objectId;
    v.__obedHold = entry;
    if (held.indexOf(v) < 0) held.push(v);
  }
  function stash(v, why) {
    if (disabled) return;
    if (!(v instanceof HTMLVideoElement)) return;
    // Our own remount moves briefly detach the node; that self-triggered detach
    // must not re-stash and re-schedule a remount (exponential reschedule blowup).
    if (v.__obedRemounting) return;
    // A decoder bridged through the 3->4 magic move is held at the slide-4 slot by
    // keepAtSlot; a re-detach must not re-stash/re-remount it back onto the
    // slide-1/2 footprint (that dropped it to the fallback position at #8->#9).
    if (v.__obedBridged34) return;
    // The export's 3->4 restart element is suppressed (hidden overlay); a re-detach
    // must not remount it onto the footprint where it would paint its grating over
    // the bridged decoder (covering the composited counter patch).
    if (v.__obedSuppressed34) return;
    // A facade stub is never a decoder: pooled when the dom-swap took it out, it
    // was remounted beside the carried decoder, two painters for one instance.
    if (v.__obedFacadeFor) return;
    if (v.__obedGen === -1) return;
    if ((v.__obedGen == null ? 0 : v.__obedGen) < preserveGeneration) {
      note('stash-stale-gen', {
        elId: v.__obedElId, why: why,
        gen: v.__obedGen, current: preserveGeneration
      });
      return;
    }
    const src = v.currentSrc || v.src || '';
    const key = assetKey(src);
    if (!key) return;
    // Only movies the plan names are preserved. Anything else (e.g. a movie that simply
    // ends with its slide) is left to the player; pooling it remounted it at the fallback
    // footprint on later slides (seen on slide 4 in OBS, 2026-09-19).
    if (!movieAssetKey(src)) return;
    v.__obedMovieKey = movieAssetKey(src);
    const mode = zoneMode(v);
    const armedPool = mode === 'armed' && instanceOf(v) === GL.src.objectId
      && currentHashNum() === GL.atScene - 1 && !document.contains(v);
    if (mode === 'refuse' || (mode === 'armed' && !armedPool)) {
      noteRefused(v, src, 'stash');
      return;
    }
    if (!armedPool && !poolable(v)) return;
    if (!(v.readyState >= 2 || v.currentTime > 0.05)) return;
    tag(v);
    if (armedPool) {
      v.__obedGlPooled = true;
      if (glPooled.indexOf(v) < 0) glPooled.push(v);
    }
    if (!pool.has(key)) pool.set(key, []);
    const q = pool.get(key);
    if (q.indexOf(v) < 0) q.push(v);
    everPreserved = true;
    v.dataset.obedPreserved = '1';
    // Remember layout so we can remount as a visible overlay after Magic Move
    // tears the video layer down and leaves only the WebGL/poster texture.
    try {
      const r = v.getBoundingClientRect();
      if (r.width > 1 && r.height > 1) {
        v.__obedRect = {x: r.left, y: r.top, w: r.width, h: r.height};
        const authored = authoredRectOf(r);
        if (authored) {
          v.__obedAuthoredRect = authored;
          v.__obedAuthoredRectScene = currentHashNum();
        }
      } else if (!(GL && zone === 'released' && v === carriedMemo)) {
        captureLayout(v);
      }
      v.__obedStyle = v.getAttribute('style') || '';
      v.__obedId = v.id || '';
      const inlineZ = v.style.zIndex;
      v.__obedZ = (inlineZ !== '' && inlineZ != null) ? inlineZ : getComputedStyle(v).zIndex;
      // Only capture while still attached — a later detach-triggered stash()
      // must not clobber the authored position with nulls.
      if (v.parentNode) {
        v.__obedParent = v.parentNode;
        v.__obedNextSibling = v.nextSibling;
        v.__obedLayer = nearestLayer(v.parentElement);
      }
    } catch (e) {}
    note(why, {
      key: key, elId: v.__obedElId, t: v.currentTime, queue: q.length,
      paused: v.paused, readyState: v.readyState, srcTail: String(src).slice(-60)
    });
    // Keep decoder warm even if destroy()/detach paused it.
    if (v.paused && !v.ended) {
      const p = v.play();
      if (p && p.catch) p.catch(function(){});
    }
    if (String(why || '').indexOf('detach') >= 0) {
      scheduleRemount(v, why);
    }
  }

  /**
   * After Magic Move, Keynote HTML detaches <video> and never recreateElement
   * for continuing movies — the composed stage keeps the static poster texture.
   * Remount the preserved decoder as a visible DOM overlay at its last rect so
   * colour frames cover the poster (same path handleMovieDidStart uses).
   */
  function scheduleRemount(v, why) {
    if (disabled) return;
    const scheduleSrc = v ? (v.currentSrc || v.src || '') : '';
    const mode = zoneMode(v);
    if (mode === 'armed') {
      noteHold(v, scheduleSrc, 'remount');
      return;
    }
    if (mode === 'refuse') {
      noteRefused(v, scheduleSrc, 'remount');
      return;
    }
    if (suppressRemount) {
      note('remount-suppressed', {elId: v && v.__obedElId, why: why});
      return;
    }
    const epoch = remountEpoch;
    v.__obedRemountEpoch = epoch;
    note('remount-scheduled', {elId: v.__obedElId, why: why, epoch: epoch});
    // Remount SYNCHRONOUSLY in the same task as the detach so the footprint has no
    // owner-less frame at the flip instant (the detach->50ms-timeout gap otherwise
    // leaves the first post-flip capture with a null footprint decoder, failing the
    // crossing/after-window decoder-stability checks). The authored-layer poster
    // canvas may not exist yet this early; tryRemount then falls back to the
    // stage/body overlay at the (already-correct) __obedRect, and the later timed
    // retries move it into the poster's authored-z slot before the Finding-2 frame.
    tryRemount(v, epoch);
    const delays = [50, 200, 500, 900, 1400, 2000];
    delays.forEach(function(ms) {
      setTimeout(function(){ tryRemount(v, epoch); }, ms);
    });
    // Bridge the immediate transition only — remove after the first hashchange so a
    // preserved movie does not keep getting re-overlaid on later, unrelated scenes.
    function onHash() {
      window.removeEventListener('hashchange', onHash);
      setTimeout(function(){ tryRemount(v, epoch); }, 80);
      setTimeout(function(){ tryRemount(v, epoch); }, 400);
    }
    window.addEventListener('hashchange', onHash);
  }

  // A pin hold ends at a restart of its instance, so the restart teardown is untouched.
  function pinEnd(v) {
    const n = nextEntry(instanceOf(v));
    return n && n.action === 'restart' ? n.atScene : Infinity;
  }
  /**
   * Hold a remounted continuing movie's <video> at the on-screen footprint EVERY
   * frame through the 1->2 Magic Move. The video is re-parented into the movie's
   * authored poster layer (for correct z-order), but that layer is itself being
   * ANIMATED by the Magic Move, so a one-shot measure-and-correct only holds until
   * the next animation frame drags the child off the footprint — leaving sparse
   * on-footprint frames (the residual flake: footprintOwnerDecoderId returns null
   * on a drifted capture, failing the after-window decoder-stability check). A rAF
   * loop re-applies the measure-and-correct offset every frame so the RENDERED rect
   * stays at (tx,ty) despite the containing layer's transform, keeping authored
   * z-order (no reparent, no forced z-index). Runs until a restart of the held
   * instance (`pinEnd`) or a retire, so the restart teardown is untouched.
   */
  function keepAtFootprint(v, tx, ty) {
    if (v.__obedPinning) return;
    v.__obedPinning = true;
    const token = v.__obedPinToken = (v.__obedPinToken || 0) + 1;
    function frame() {
      if (v.__obedPinToken !== token) return;
      if (v.__obedRemountEpoch === -1 || v.ended || !document.contains(v)) {
        v.__obedPinning = false; return;
      }
      const hn = currentHashNum();
      if (hn != null && hn >= pinEnd(v)) { v.__obedPinning = false; return; }
      if (v.dataset.obedRemounted === '1') {
        const cur = v.getBoundingClientRect();
        if (cur.width > 1 && cur.height > 1) {
          const dx = tx - cur.left, dy = ty - cur.top;
          if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
            const stageEl = document.getElementById('stage');
            const inStage = !!(stageEl && stageEl.contains(v));
            const map = inStage ? stageMap() : null;
            if (inStage && !map) {
              noteStageMapUnavailable('keepAtFootprint');
            } else {
              const divisor = map ? map.s : 1;
              v.style.left = ((parseFloat(v.style.left) || 0) + dx / divisor) + 'px';
              v.style.top = ((parseFloat(v.style.top) || 0) + dy / divisor) + 'px';
            }
          }
        }
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  /**
   * 3->4 magic-move moving-target pin. Unlike keepAtFootprint (which holds a
   * bridged 1->2 decoder at a STATIC on-screen point), the 3->4 movie box
   * TRANSLATES + SCALES from the slide-3 rect to the larger slide-4 rect across
   * the cut, so the target moves every frame. `real` (the live continuing
   * decoder) is DOM-swapped by bindFacade into the player's slide-4 movie slot,
   * inheriting that layer's magic-move transform, so it should follow the
   * animation on its own; this loop re-asserts that by measure-correcting `real`
   * onto the authored movie poster canvas nearest its current rect every frame,
   * defeating any residual drag from a stale 1->2 remount. Runs from the 3->4
   * bridge engage until the decoder retires (`__obedRemountEpoch === -1` is the
   * bridge's OWN sentinel here, so this loop ignores it) or leaves the DOM.
   */
  function dstRect(entry) {
    const r = entry && entry.dst && entry.dst.rect;
    if (r && typeof r === 'object' && r.w > 1 && r.h > 1) return r;
    return null;
  }
  function keepThroughBridge(v) {
    const boundary = nextEntry(instanceOf(v));
    const hn = currentHashNum();
    if (!boundary || boundary.action !== 'bridge' || hn !== boundary.atScene - 1
        || !dstRect(boundary) || !boundary.src.rect || !(boundary.durationSeconds > 0)) return false;
    // Idle on the source slide the hash already reads `atScene - 1`; a pending
    // remount of a held or pinned decoder must not start the move before the
    // player tears the slide down.
    if (!hasDeparted(instanceOf(v))) return false;
    // The move owns the decoder now: end any footprint hold, or it drags the
    // landed decoder back to the source slot once the hash settles (live D2).
    if (v.__obedPinning) {
      v.__obedPinning = false;
      v.__obedPinToken = (v.__obedPinToken || 0) + 1;
    }
    const generation = preserveGeneration;
    if (!v.__obedMotion || v.__obedMotion.generation !== generation
        || v.__obedMotion.boundary !== boundary) {
      v.__obedMotion = {started: performance.now(), generation: generation, boundary: boundary};
    }
    const started = v.__obedMotion.started;
    const src = boundary.src.rect, dest = boundary.dst.rect;
    const stage = document.getElementById('body') || document.body;
    if (v.parentNode !== stage) {
      beginMove(v);
      stage.appendChild(v);
    }
    if (v.__obedMotionPinning) return true;
    v.__obedMotionPinning = true;
    v.style.position = 'absolute';
    v.style.visibility = 'visible';
    v.style.display = 'block';
    v.style.opacity = '1';
    v.style.pointerEvents = 'none';
    v.dataset.obedRemounted = '1';
    function frame() {
      const scene = currentHashNum();
      if (generation !== preserveGeneration || v.__obedGen === -1
          || v.ended || !document.contains(v) || scene !== boundary.atScene - 1) {
        v.__obedMotionPinning = false;
        return;
      }
      const progress = Math.min(1, Math.max(0, (performance.now() - started) / (1000 * boundary.durationSeconds)));
      const authored = {
        x: src.x + (dest.x - src.x) * progress,
        y: src.y + (dest.y - src.y) * progress,
        w: src.w + (dest.w - src.w) * progress,
        h: src.h + (dest.h - src.h) * progress
      };
      const screenRect = toScreen(authored);
      if (!screenRect) {
        noteStageMapUnavailable('keepThroughBridge');
      } else {
        v.style.left = screenRect.x + 'px';
        v.style.top = screenRect.y + 'px';
        v.style.width = screenRect.w + 'px';
        v.style.height = screenRect.h + 'px';
      }
      requestAnimationFrame(frame);
    }
    frame();
    note('bridge-motion-start', {elId: v.__obedElId, durationSeconds: boundary.durationSeconds,
      srcRect: src, rect: dest, geometrySource: 'export-duration-interpolation'});
    return true;
  }
  function bridgeStage() {
    return document.getElementById('body') || document.querySelector('[class*="stage"]') || document.body;
  }
  /**
   * Is a bridged decoder still ours to hold? Liveness is
   * `__obedGen === preserveGeneration`, not `__obedRemountEpoch` (bridgeTo34
   * sets that to -1 as its own sentinel): clear()/disable() bump the generation
   * and retire-on-start-movie stamps -1, so both end the pin.
   */
  function slotLive(real) {
    if (disabled) return false;
    return (real.__obedGen == null ? 0 : real.__obedGen) === preserveGeneration;
  }
  /**
   * End a slot pin whose decoder is no longer live. The node may still be
   * connected (clear() bumped the generation but missed or failed to remove it),
   * in which case leaving it would keep the slide-4 overlay painting after a
   * go-to/retire, so pause it and take it out of the DOM as well.
   */
  function retireSlot(real) {
    try { real.pause(); } catch (e) {}
    try {
      if (real.parentNode) {
        beginMove(real);
        real.parentNode.removeChild(real);
      }
    } catch (e) {}
    delete real.dataset.obedRemounted;
    note('bridge-slot-retired', {elId: real.__obedElId});
  }
  /**
   * Re-attach a bridged decoder the player detached while slide 4 is still up.
   * stash() ignores bridged decoders, so nothing else would bring it back.
   */
  function reattachToSlot(real) {
    if (real.ended || !slotLive(real)) return false;
    const stage = bridgeStage();
    let failure = stage ? null : 'no-stage';
    if (!failure) {
      try {
        beginMove(real);
        stage.appendChild(real);
      } catch (e) {
        failure = String(e && e.message || e);
      }
    }
    if (!failure && !document.contains(real)) failure = 'still-detached';
    if (failure) {
      note('bridge-slot-reattach-failed', {elId: real.__obedElId, reason: failure});
      return false;
    }
    note('bridge-slot-reattach', {elId: real.__obedElId});
    if (real.paused && !real.ended) {
      const p = real.play();
      if (p && p.catch) p.catch(function(){});
    }
    return true;
  }
  function keepAtSlot(real, entry) {
    if (real.__obedSlotPinning) return;
    real.__obedSlotPinning = true;
    function frame() {
      const hn = currentHashNum();
      if (real.ended || (hn != null && hn < entry.atScene) || real.__obedHold !== entry) {
        real.__obedSlotPinning = false; return;
      }
      if (!slotLive(real)) {
        retireSlot(real);
        real.__obedSlotPinning = false; return;
      }
      // A held overlay is never detached, so the next bridge's move starts here,
      // once the player has left the slide (not while it idles on it).
      const next = nextEntry(instanceOf(real));
      if (next && next.action === 'bridge' && hn === next.atScene - 1 && hasDeparted(instanceOf(real))) {
        real.__obedSlotPinning = false;
        keepThroughBridge(real);
        return;
      }
      if (!document.contains(real) && !reattachToSlot(real)) {
        real.__obedSlotPinning = false; return;
      }
      // Pin to the authored slide-4 destination rect (measure-and-correct so it
      // holds through the containing layer's magic-move transform), so neither
      // the layer's transform nor a re-detach drags the bridged decoder off the
      // slide-4 slot at the #8->#9 boundary.
      const destAuthored = dstRect(entry);
      const dest = destAuthored ? toScreen(destAuthored) : null;
      if (destAuthored && !dest) noteStageMapUnavailable('keepAtSlot');
      const cur = real.getBoundingClientRect();
      if (dest && cur.width > 1 && cur.height > 1) {
        const dx = dest.x - cur.left, dy = dest.y - cur.top;
        if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
          real.style.left = ((parseFloat(real.style.left) || 0) + dx) + 'px';
          real.style.top = ((parseFloat(real.style.top) || 0) + dy) + 'px';
        }
        if (Math.abs(cur.width - dest.w) > 1) real.style.width = dest.w + 'px';
        if (Math.abs(cur.height - dest.h) > 1) real.style.height = dest.h + 'px';
        real.style.visibility = 'visible';
        real.style.display = 'block';
        real.style.opacity = '1';
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  function rectOverlapArea(r, rect) {
    const ix = Math.max(0, Math.min(r.left + r.width, rect.x + rect.w) - Math.max(r.left, rect.x));
    const iy = Math.max(0, Math.min(r.top + r.height, rect.y + rect.h) - Math.max(r.top, rect.y));
    return ix * iy;
  }
  // A <video> only contributes to the composite when attached and not hidden by
  // display/visibility/opacity. Used to exclude a suppressed 3->4 restart sibling
  // from footprint-owner resolution (it decodes but does not paint).
  function isCompositing(v) {
    if (!document.contains(v)) return false;
    if (v.__obedSuppressed34) return false;
    try {
      const st = getComputedStyle(v);
      if (st.display === 'none' || st.visibility === 'hidden') return false;
      if (parseFloat(st.opacity) <= 0.02) return false;
    } catch (e) {}
    return true;
  }
  /**
   * Bridge a preserved live decoder through the 3->4 magic move: keep it as a
   * visible overlay at the slide-4 destination rect (same mechanism proven for
   * 1->2, but at the grown/translated slot and running in the slide-4 window),
   * so its clock CONTINUES while the export's fresh autoplay-from-0 element is
   * suppressed. Absolute-positioned on the stage at the destination rect (a
   * root-stage append lands on top, covering the export's poster/hidden restart);
   * keepAtSlot then holds it there through the layer transform and any re-detach.
   */
  function bridgeTo34(v, entry) {
    v.__obedBridged34 = true;
    v.__obedRemountEpoch = -1;   // cancel any pending 1->2 remount for v
    v.__obedPinning = false;
    const destAuthored = dstRect(entry);
    const dest = destAuthored ? toScreen(destAuthored) : null;
    if (destAuthored && !dest) noteStageMapUnavailable('bridgeTo34');
    const stage = bridgeStage();
    try {
      if (stage && v.parentNode !== stage) {
        beginMove(v);
        stage.appendChild(v);
      }
      v.style.position = 'absolute';
      if (dest) {
        v.style.left = dest.x + 'px';
        v.style.top = dest.y + 'px';
        v.style.width = dest.w + 'px';
        v.style.height = dest.h + 'px';
      }
      v.style.visibility = 'visible';
      v.style.display = 'block';
      v.style.opacity = '1';
      v.style.pointerEvents = 'none';
      v.dataset.obedRemounted = '1';
      if (v.paused && !v.ended) {
        const p = v.play();
        if (p && p.catch) p.catch(function(){});
      }
    } catch (e) {
      note('bridge-3to4-error', {elId: v.__obedElId, message: String(e && e.message || e)});
    }
    keepAtSlot(v, entry);
  }
  /**
   * Keep the export's suppressed 3->4 restart element hidden every frame. A
   * one-shot opacity/visibility override is wiped when the player re-styles the
   * element on slide 4's later build, letting its grating paint over the bridged
   * decoder's composited counter patch. Re-assert the hide each rAF so only the
   * continuing decoder composites.
   */
  function keepSuppressed(el) {
    if (el.__obedSuppressPinning) return;
    el.__obedSuppressPinning = true;
    function frame() {
      if (!el.__obedSuppressed34 || !document.contains(el)) {
        el.__obedSuppressPinning = false; return;
      }
      try {
        el.style.setProperty('opacity', '0', 'important');
        el.style.setProperty('visibility', 'hidden', 'important');
      } catch (e) {}
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }
  /**
   * Find the movie's own authored poster <canvas> (its layer's stacking
   * context) by matching footprint geometry — MM destroys the video's
   * authored parent, so we can't walk up from the video itself. Requires a
   * UNIQUE best match: collect every canvas within tolerance, rank by
   * geometric distance, and break ties by the video's own authored layer
   * (outgoing vs incoming MM), then DOM order (incoming layer is later).
   */
  function findMovieCanvas(box, v) {
    if (!(box && box.w > 1 && box.h > 1)) return null;
    const maxArea = box.w * box.h * 1.5;
    const mapTol = stageMap();
    const tolScale = mapTol ? mapTol.s : 1;
    const posTol = 10 * tolScale, sizeTol = 16 * tolScale;
    const candidates = [];
    const canvases = document.querySelectorAll('canvas');
    for (let i = 0; i < canvases.length; i++) {
      const c = canvases[i];
      const r = c.getBoundingClientRect();
      if (!(r.width > 1 && r.height > 1)) continue;
      if (r.width * r.height > maxArea) continue;
      const dx = Math.abs(r.left - box.x);
      const dy = Math.abs(r.top - box.y);
      const dw = Math.abs(r.width - box.w);
      const dh = Math.abs(r.height - box.h);
      if (dx <= posTol && dy <= posTol && dw <= sizeTol && dh <= sizeTol) {
        candidates.push({c: c, dist: dx + dy + dw + dh, order: i});
      }
    }
    if (!candidates.length) return null;
    const minDist = candidates.reduce((m, c) => Math.min(m, c.dist), Infinity);
    const tied = candidates.filter((c) => Math.abs(c.dist - minDist) <= 0.01);
    if (tied.length === 1) return tied[0].c;
    // Distance tie: try to resolve by the video's own authored layer.
    const layerMatches = tied.filter(
      (c) => v && v.__obedLayer && nearestLayer(c.c.parentElement) === v.__obedLayer
    );
    if (layerMatches.length === 1) return layerMatches[0].c;
    // Still ambiguous (0 or >=2 equally-good candidates) — do not guess.
    note('remount-canvas-ambiguous', {
      elId: v && v.__obedElId,
      box: box,
      candidateN: tied.length,
      layerMatchN: layerMatches.length
    });
    return null;
  }
  // Movie definitions ({assetKeys: [...], footprint: {x,y,w,h}}) come from the
  // plan, keyed by a generic movie id (e.g. 'movie1'). No fixture literals here.
  function planMovies() {
    return (OBED_PLAN && OBED_PLAN.movies && typeof OBED_PLAN.movies === 'object') ? OBED_PLAN.movies : {};
  }
  // Asset identity of a movie <video> by its source, never elId parity (which
  // lets a second movie alias onto the wrong movie's canvas).
  function movieAssetKey(src) {
    const s = String(src || '').toLowerCase();
    const movies = planMovies();
    for (const k in movies) {
      const keys = (movies[k] && movies[k].assetKeys) || [];
      for (let i = 0; i < keys.length; i++) {
        if (s.indexOf(String(keys[i]).toLowerCase()) >= 0) return k;
      }
    }
    return null;
  }
  function footprintKeyForRect(rect) {
    let bestKey = null, bestDist = Infinity;
    const movies = planMovies();
    for (const k in movies) {
      const fp = movies[k] && movies[k].footprint;
      if (!fp) continue;
      const dx = Math.abs(fp.x - rect.x), dy = Math.abs(fp.y - rect.y);
      const dw = Math.abs(fp.w - rect.w), dh = Math.abs(fp.h - rect.h);
      if (dx <= 20 && dy <= 20 && dw <= 30 && dh <= 30) {
        const dist = dx + dy + dw + dh;
        if (dist < bestDist) { bestDist = dist; bestKey = k; }
      }
    }
    return bestKey;
  }
  window.addEventListener('error', function(e) {
    note('player-build-error', {
      errorType: 'error',
      message: String((e && e.message) || e),
      filename: e && e.filename,
      lineno: e && e.lineno
    });
  });
  window.addEventListener('unhandledrejection', function(e) {
    const reason = e && e.reason;
    note('player-build-error', {
      errorType: 'unhandledrejection',
      message: String((reason && reason.message) || reason || 'unhandledrejection')
    });
  });
  // Mark a node as being moved by us so the MutationObserver's detach handler
  // skips re-stashing it (clears on the next macrotask, after the observer runs).
  function beginMove(v) {
    v.__obedRemounting = true;
    setTimeout(function(){ v.__obedRemounting = false; }, 0);
  }
  /**
   * Hand one preserved decoder back to the player: pause it, take it out of the
   * DOM and mark it dead so nothing re-pools, re-reuses or re-remounts it.
   * Shared by the `retire-on-start-movie` branch and the retire-zone sweep.
   */
  function retireDecoder(v) {
    try { v.pause(); } catch (e) {}
    try {
      if (v.parentNode) v.parentNode.removeChild(v);
    } catch (e) {}
    delete v.dataset.obedPreserved;
    delete v.dataset.obedRemounted;
    v.__obedRemountEpoch = -1;
    v.__obedGen = -1;
    const hi = held.indexOf(v);
    if (hi >= 0) held.splice(hi, 1);
    return v.__obedElId;
  }
  /**
   * Retire every decoder of the retired movie once the hash enters the zone —
   * the safety net for anything pooled before it. Driven by the keep-warm
   * interval, not `hashchange`: the player rewrites `location.hash` without
   * ever firing that event (measured on the real export, 2026-09-20).
   */
  function sweepRetireZone() {
    zoneState(false);
    ENTRIES.forEach(function(b) {
      if ((b.action !== 'retire' && b !== GL) || !inRetireZone(b)) return;
      if (b === GL && zone === 'released') return;
      if (b === GL && zone === 'armed') {
        retireVictims(b, zoneVictims(b, []).filter(function(v) { return !v.__obedGlPooled; }), true);
        return;
      }
      retireVictims(b, zoneVictims(b, []), true);
    });
  }
  /**
   * Every decoder the runtime preserves for the instance(s) `b` hands back: a
   * retire's `src`, a glReplay's `src` or `dst`. By the instance stamp, never
   * the live src — a real in-zone clear empties that.
   */
  function zoneVictims(b, victims) {
    function take(v) {
      const inst = instanceOf(v);
      const mine = b === GL ? namesInstance(b, inst) : inst === b.src.objectId;
      if (mine && v.__obedGen !== -1 && victims.indexOf(v) < 0) victims.push(v);
    }
    pool.forEach(function(q) { (q || []).forEach(take); });
    held.forEach(take);
    document.querySelectorAll('video[data-obed-preserved="1"]').forEach(take);
    return victims;
  }
  function retireVictims(b, victims, noteIt) {
    if (!victims.length) return [];
    const elIds = victims.map(function(v) {
      beginMove(v);
      return retireDecoder(v);
    });
    const empties = [];
    pool.forEach(function(q, key) {
      const left = (q || []).filter(function(v) { return victims.indexOf(v) < 0; });
      if (left.length) pool.set(key, left); else empties.push(key);
    });
    empties.forEach(function(key) { pool.delete(key); });
    if (noteIt) note('retire-boundary', {key: b.movieKey, elIds: elIds, atScene: b.atScene, instance: b.src.objectId});
    return elIds;
  }
  // Where this instance rests on its slide: the holding entry's `dst.rect`, else its next entry's `src.rect`.
  function restingRect(v) {
    if (v.__obedHold && v.__obedHold.dst) return v.__obedHold.dst.rect || null;
    const n = nextEntry(instanceOf(v));
    return n ? n.src.rect || null : null;
  }
  function tryRemount(v, epoch) {
    if (disabled) return;
    if (!v || suppressRemount) return;
    const remountSrc = v.currentSrc || v.src || '';
    const mode = zoneMode(v);
    if (mode === 'armed') {
      noteHold(v, remountSrc, 'remount');
      return;
    }
    if (mode === 'refuse') {
      noteRefused(v, remountSrc, 'remount');
      return;
    }
    if (epoch != null && epoch !== remountEpoch) {
      note('remount-stale', {elId: v.__obedElId, epoch: epoch, current: remountEpoch});
      return;
    }
    if (v.__obedRemountEpoch === -1 || v.ended) return;
    if (keepThroughBridge(v)) return;
    if (v.__obedParent && document.contains(v.__obedParent)) {
      try {
        const anchor = (v.__obedNextSibling && v.__obedNextSibling.parentNode === v.__obedParent)
          ? v.__obedNextSibling : null;
        if (v.parentNode !== v.__obedParent || v.nextSibling !== anchor) {
          beginMove(v);
          v.__obedParent.insertBefore(v, anchor);
        }
        if (v.__obedStyle != null) v.setAttribute('style', v.__obedStyle);
        v.style.visibility = 'visible';
        v.style.display = 'block';
        v.style.opacity = '1';
        v.style.pointerEvents = 'none';
        if (/^-?\d+$/.test(String(v.__obedZ))) {
          v.style.zIndex = String(v.__obedZ);
        } else {
          v.style.removeProperty('z-index');
        }
        if (v.paused && !v.ended) {
          const p = v.play();
          if (p && p.catch) p.catch(function(){});
        }
        v.dataset.obedRemounted = '1';
        note('remount-authored-parent', {
          elId: v.__obedElId,
          key: assetKey(v.currentSrc || v.src || ''),
          layer: v.__obedLayer ? (v.__obedLayer.id || null) : null,
          z: v.__obedZ,
          videoWidth: v.videoWidth,
          currentTime: v.currentTime,
          inDocument: document.contains(v)
        });
        return;
      } catch (e) {
        note('remount-authored-parent-error', {elId: v.__obedElId, message: String(e && e.message || e)});
      }
    }
    if (GL && zone === 'released' && carriedMemo && v.__obedFacadeFor === carriedMemo && carriedMemo.__obedRect) {
      v.__obedRect = Object.assign({}, carriedMemo.__obedRect);
    }
    if (!(v.__obedRect && v.__obedRect.w > 1)) captureLayout(v);
    let box = v.__obedRect || {};
    const boxMap = stageMap();
    const nearZero = Math.abs(box.x) < 2 && Math.abs(box.y) < 2;
    const nearStageOrigin = !!boxMap && Math.abs(box.x - boxMap.ox) < 2 && Math.abs(box.y - boxMap.oy) < 2;
    // Detach can leave getBoundingClientRect at the literal viewport origin (no
    // layout box) or at the live stage origin (a zero-layout attached parent).
    // Fall back to the instance's planned resting rect (its real on-screen slot).
    if (!(box.w > 1 && box.h > 1) || nearZero || nearStageOrigin) {
      const rest = restingRect(v);
      let fp;
      if (rest) {
        if (!boxMap) {
          noteStageMapUnavailable('remount-footprint-rect');
          return;
        }
        fp = toScreen(rest, boxMap);
      } else {
        fp = {x: 0, y: 0, w: box.w, h: box.h};
      }
      box = {x: fp.x, y: fp.y, w: (box.w > 1 ? box.w : fp.w), h: (box.h > 1 ? box.h : fp.h)};
      note('remount-footprint-rect', {elId: v.__obedElId, rect: box});
    }
    v.__obedRect = box;
    // Prefer the movie's own authored poster canvas — its layer's stacking
    // context is what makes later-authored artwork (green/black) paint in
    // front. A root-stage append (below) always lands on top of everything.
    const posterCanvas = findMovieCanvas(box, v);
    if (posterCanvas && posterCanvas.parentNode) {
      try {
        if (!(v.parentNode === posterCanvas.parentNode && v.previousSibling === posterCanvas)) {
          beginMove(v);
          posterCanvas.parentNode.insertBefore(v, posterCanvas.nextSibling);
        }
        const stageEl = document.getElementById('stage');
        const inStage = !!(stageEl && stageEl.contains(v));
        const map = inStage ? stageMap() : null;
        if (inStage && !map) {
          noteStageMapUnavailable('remount-into-authored-layer');
          return;
        }
        const divisor = map ? map.s : 1;
        v.style.position = 'absolute';
        v.style.width = (box.w / divisor) + 'px';
        v.style.height = (box.h / divisor) + 'px';
        // The poster canvas's parent (its authored MM layer) may carry a
        // Magic-Move transform, so box.x/box.y (the ON-SCREEN footprint) are NOT
        // valid raw left/top in that containing block — writing them raw
        // double-counts the layer offset and renders the movie off-stage (the
        // observed [214,1586] freeze). Place by measure-and-correct: zero,
        // measure the rendered origin, then offset by the footprint delta so the
        // RENDERED rect equals the on-screen footprint, transform-agnostic —
        // while keeping the poster's authored z-order (a forced/top z-index would
        // paint the movie over the green square and break Finding 2).
        v.style.left = '0px';
        v.style.top = '0px';
        const cur = v.getBoundingClientRect();
        v.style.left = ((box.x - cur.left) / divisor) + 'px';
        v.style.top = ((box.y - cur.top) / divisor) + 'px';
        v.style.visibility = 'visible';
        v.style.display = 'block';
        v.style.opacity = '1';
        v.style.pointerEvents = 'none';
        v.style.removeProperty('z-index');
        if (v.paused && !v.ended) {
          const p = v.play();
          if (p && p.catch) p.catch(function(){});
        }
        v.dataset.obedRemounted = '1';
        // Hold it at the footprint every frame — the authored layer is animated by
        // the MM, so a one-shot placement drifts off between animation frames.
        keepAtFootprint(v, box.x, box.y);
        note('remount-into-authored-layer', {
          elId: v.__obedElId,
          key: assetKey(v.currentSrc || v.src || ''),
          canvasId: posterCanvas.id || null,
          rect: box,
          videoWidth: v.videoWidth,
          currentTime: v.currentTime,
          inDocument: document.contains(v)
        });
        return;
      } catch (e) {
        note('remount-into-authored-layer-error', {elId: v.__obedElId, message: String(e && e.message || e)});
      }
    }
    if (GL && zone === 'released' && carriedMemo && (v === carriedMemo || v.__obedFacadeFor === carriedMemo)) {
      noteHold(v, remountSrc, 'stage');
      return;
    }
    const stage = document.getElementById('body') || document.querySelector('[class*="stage"]') || document.body;
    if (!stage) {
      note('remount-no-stage', {elId: v.__obedElId});
      return;
    }
    try {
      v.style.position = 'absolute';
      v.style.left = box.x + 'px';
      v.style.top = box.y + 'px';
      v.style.width = box.w + 'px';
      v.style.height = box.h + 'px';
      v.style.visibility = 'visible';
      v.style.display = 'block';
      v.style.opacity = '1';
      // Restore the authored layer instead of forcing a max z-index over everything.
      if (/^-?\d+$/.test(String(v.__obedZ))) {
        v.style.zIndex = String(v.__obedZ);
      } else {
        v.style.removeProperty('z-index');
      }
      v.style.pointerEvents = 'none';
      if (v.__obedId && !document.getElementById(v.__obedId)) v.id = v.__obedId;
      if (!document.contains(v) || v.parentNode !== stage) {
        beginMove(v);
        stage.appendChild(v);
      }
      if (v.paused && !v.ended) {
        const p = v.play();
        if (p && p.catch) p.catch(function(){});
      }
      v.dataset.obedRemounted = '1';
      note('remount-done', {
        elId: v.__obedElId,
        key: assetKey(v.currentSrc || v.src || ''),
        rect: box,
        z: v.__obedZ,
        videoWidth: v.videoWidth,
        currentTime: v.currentTime,
        inDocument: document.contains(v)
      });
    } catch (e) {
      note('remount-error', {elId: v.__obedElId, message: String(e && e.message || e)});
    }
  }
  /**
   * `rehomed`: the runtime placed `real` itself (a pin out of a held bridge
   * overlay), so an inserted stub is only taken out, never swapped for `real`.
   */
  function bindFacade(stub, real, rehomed) {
    stub.__obedFacadeFor = real;
    stub.dataset.obedFacade = '1';
    stub.play = function(){ return real.play(); };
    stub.pause = function(){ return real.pause(); };
    try {
      Object.defineProperty(stub, 'currentTime', {
        configurable: true,
        get: function(){ return real.currentTime; },
        set: function(v){ real.currentTime = v; }
      });
      ['paused','ended','readyState','networkState','videoWidth','videoHeight','duration','muted','loop','playbackRate'].forEach(function(prop){
        Object.defineProperty(stub, prop, {
          configurable: true,
          get: function(){ return real[prop]; },
          set: function(v){ try { real[prop] = v; } catch (e) {} }
        });
      });
      Object.defineProperty(stub, 'src', {
        configurable: true,
        get: function(){ return real.src; },
        set: function(v){
          if (v === '' || v == null) {
            note('facade-block-clear', {elId: real.__obedElId, t: real.currentTime});
            return;
          }
          real.src = v;
        }
      });
    } catch (e) {
      note('facade-error', String(e && e.message || e));
    }
    const mo = new MutationObserver(function(){
      if (stub.parentNode && real !== stub && real.__obedGen === preserveGeneration && real.__obedRemountEpoch !== -1) {
        if (rehomed) {
          try {
            beginMove(stub);
            stub.parentNode.removeChild(stub);
          } catch (e) {}
          mo.disconnect();
          return;
        }
        if (GL && zone === 'released' && real === carriedMemo) {
          const layerCanvas = findMovieCanvas(real.__obedRect, real);
          if (!layerCanvas || stub.parentNode !== layerCanvas.parentNode) {
            try {
              beginMove(stub);
              stub.parentNode.removeChild(stub);
            } catch (e) {}
            noteHold(real, real.currentSrc || real.src || '', 'stage');
            return;
          }
        }
        try {
          const parent = stub.parentNode;
          const next = stub.nextSibling;
          beginMove(stub);
          parent.removeChild(stub);
          if (real.parentNode && real.parentNode !== parent) {
            beginMove(real);
            try { real.parentNode.removeChild(real); } catch (e2) {}
          }
          if (next) parent.insertBefore(real, next); else parent.appendChild(real);
          real.style.visibility = 'visible';
          real.style.display = '';
          if (real.paused && !real.ended) {
            const p = real.play();
            if (p && p.catch) p.catch(function(){});
          }
          note('dom-swap', {elId: real.__obedElId, t: real.currentTime, paused: real.paused});
          mo.disconnect();
          // The stub's slot sits under the destination's WebGL poster until the
          // player's own movie starts, which a stub never does (live D5 slide 3:
          // clock advancing, pixels frozen). Re-home the decoder above its poster
          // canvas in this layer, at the holding entry's `dst.rect`.
          const hold = real.__obedHold;
          const screen = hold && hold.dst && hold.dst.rect ? toScreen(hold.dst.rect) : null;
          if (screen) {
            real.__obedLayer = nearestLayer(parent) || real.__obedLayer;
            real.__obedParent = null;
            real.__obedRect = screen;
            scheduleRemount(real, 'pin-rehome');
          }
        } catch (e) {
          note('dom-swap-error', String(e && e.message || e));
        }
      }
    });
    mo.observe(document.documentElement, {childList: true, subtree: true});
  }

  // Keep page chrome transparent even if the player assigns an opaque body colour.
  function forceTransparentChrome() {
    try {
      document.documentElement.style.setProperty('background', 'transparent', 'important');
      document.documentElement.style.setProperty('background-color', 'transparent', 'important');
      if (document.body) {
        document.body.style.setProperty('background', 'transparent', 'important');
        document.body.style.setProperty('background-color', 'transparent', 'important');
      }
      const body = document.getElementById('body');
      if (body) {
        body.style.setProperty('background', 'transparent', 'important');
        body.style.setProperty('background-color', 'transparent', 'important');
      }
    } catch (e) {}
  }
  if (OBED_PLAN.transparentBackground === true) {
    forceTransparentChrome();
    new MutationObserver(forceTransparentChrome).observe(document.documentElement, {
      attributes: true, subtree: true, attributeFilter: ['style', 'bgcolor', 'class']
    });
  }

  function captureLayout(v) {
    if (!(v instanceof HTMLVideoElement)) return false;
    try {
      let el = v;
      for (let i = 0; i < 8 && el; i++) {
        const r = el.getBoundingClientRect();
        if (r.width > 1 && r.height > 1) {
          v.__obedRect = {x: r.left, y: r.top, w: r.width, h: r.height};
          if (i === 0) {
            const authored = authoredRectOf(r);
            if (authored) {
              v.__obedAuthoredRect = authored;
              v.__obedAuthoredRectScene = currentHashNum();
            }
          }
          v.__obedStyle = v.getAttribute('style') || v.__obedStyle || '';
          v.__obedId = v.id || v.__obedId || '';
          return true;
        }
        el = el.parentElement;
      }
      // Style may still carry authored movie box even when the layout box is zero.
      const st = v.getAttribute('style') || v.__obedStyle || '';
      const mw = /width:\s*([\d.]+)px/i.exec(st);
      const mh = /height:\s*([\d.]+)px/i.exec(st);
      if (mw && mh && parseFloat(mw[1]) > 1 && parseFloat(mh[1]) > 1) {
        const map = stageMap();
        if (!map) {
          noteStageMapUnavailable('captureLayout');
          return false;
        }
        const parent = v.parentElement;
        const pr = parent ? parent.getBoundingClientRect() : {left: 0, top: 0};
        v.__obedRect = {
          x: pr.left || 0,
          y: pr.top || 0,
          w: parseFloat(mw[1]) * map.s,
          h: parseFloat(mh[1]) * map.s
        };
        return v.__obedRect.w > 1;
      }
    } catch (e) {}
    return false;
  }

  // Detached decoders often pause; keep pooled clocks alive through Magic Move.
  // Refresh layout while videos are still attached (detach often zeroes the box).
  setInterval(function(){
    if (disabled) return;
    if (departure && currentHashNum() !== departure.scene) departure = null;
    sweepRetireZone();
    document.querySelectorAll('video').forEach(function(v){ captureLayout(v); });
    pool.forEach(function(q){
      (q || []).forEach(function(v){
        try {
          if (v && v.paused && !v.ended && !v.__obedGlNoWarm) {
            const p = v.play();
            if (p && p.catch) p.catch(function(){});
          }
        } catch (e) {}
      });
    });
  }, 200);

  /**
   * A src clear/removal: swallow it (true) so the decoder keeps its resource, or
   * let the real clear run (false). Only a decoder `stash` pooled, or one the
   * runtime holds, is swallowed; a suppressed bridge `dst` element really clears
   * when the player ends its slide, so a chain of bridges leaks no hidden
   * decoder. Armed: a detached armed-pooled decoder is held; a detached one on
   * the move scene is swallowed only if `stash` pooled it; anything else really
   * clears, so it never keeps painting.
   */
  function swallowClear(v, cur, why, via) {
    const mode = zoneMode(v);
    if (mode === 'armed') {
      if (v.__obedGlPooled && !document.contains(v)) {
        noteHold(v, cur, via);
        return true;
      }
      if (currentHashNum() === GL.atScene - 1 && !document.contains(v)) {
        stash(v, why);
        if (v.__obedGlPooled) return true;
      }
    } else if (mode !== 'refuse') {
      stash(v, why);
      return isPooled(v) || held.indexOf(v) >= 0;
    }
    noteRefused(v, cur, via);
    return false;
  }
  function patchSrcAccessor(proto, label) {
    const desc = Object.getOwnPropertyDescriptor(proto, 'src');
    if (!desc || !desc.set) {
      note('src-accessor-missing', {label: label});
      return;
    }
    Object.defineProperty(proto, 'src', {
      configurable: true, enumerable: desc.enumerable, get: desc.get,
      set: function(val) {
        const empty = val === '' || val == null;
        if (!empty && this instanceof HTMLVideoElement) reidentify(this, val);
        if (!disabled && empty && this instanceof HTMLVideoElement) {
          const cur = this.currentSrc || desc.get.call(this) || '';
          if (swallowClear(this, cur, 'preserve-skip-clear', 'src-clear')) return;
        }
        return desc.set.call(this, val);
      }
    });
    note('src-accessor-patched', {label: label});
  }
  patchSrcAccessor(HTMLMediaElement.prototype, 'HTMLMediaElement');
  patchSrcAccessor(HTMLVideoElement.prototype, 'HTMLVideoElement');

  const origRemove = Element.prototype.removeAttribute;
  Element.prototype.removeAttribute = function(name) {
    if (!disabled && String(name).toLowerCase() === 'src' && this instanceof HTMLVideoElement) {
      const cur = this.currentSrc || this.src || '';
      if (swallowClear(this, cur, 'preserve-skip-removeAttribute', 'removeAttribute')) return;
    }
    return origRemove.call(this, name);
  };

  // Pool videos that are detached without an src clear (common slide teardown path).
  new MutationObserver(function(muts){
    muts.forEach(function(m){
      m.removedNodes.forEach(function(node){
        if (node instanceof HTMLVideoElement) {
          noteDeparture(node);
          stash(node, 'preserve-on-detach');
        } else if (node && node.querySelectorAll) {
          node.querySelectorAll('video').forEach(function(v){
            noteDeparture(v);
            stash(v, 'preserve-on-detach-subtree');
          });
        }
      });
    });
  }).observe(document.documentElement, {childList: true, subtree: true});

  // Pooled ∪ held: a held decoder is never detached, so it never reaches the pool.
  function carryCandidates() {
    const out = [];
    function take(v) {
      if (v.__obedGen !== -1 && out.indexOf(v) < 0) out.push(v);
    }
    pool.forEach(function(q) { (q || []).forEach(take); });
    held.forEach(take);
    return out;
  }
  function isCarrySource(c, entry) {
    return c.__obedInstance === entry.src.objectId;
  }
  /**
   * The one live candidate whose instance is `entry.src`, or null after noting
   * why this boundary is refused (the fresh element then plays raw).
   */
  function pickCarried(el, value, entry) {
    const found = [];
    carryCandidates().forEach(function(c) {
      if (c === el || !isCarrySource(c, entry)) return;
      if ((c.__obedGen == null ? 0 : c.__obedGen) < preserveGeneration) {
        note('reuse-skip-stale', {
          key: assetKey(value), elId: c.__obedElId,
          gen: c.__obedGen, current: preserveGeneration
        });
        return;
      }
      found.push(c);
    });
    const reason = found.length === 0 ? 'absent'
      : found.length > 1 ? 'ambiguous'
      : !!found[0].loop !== !!entry.loop ? 'loopMismatch' : null;
    if (!reason) return found[0];
    noteRefused(el, value, 'reuse', {
      reason: reason, atScene: entry.atScene, src: entry.src.objectId,
      candidates: found.map(function(c) { return c.__obedElId; })
    });
    return null;
  }
  function authoredOfScreen(r) {
    const m = stageMap();
    if (!m || !r) return null;
    return {x: (r.x - m.ox) / m.s, y: (r.y - m.oy) / m.s, w: r.w / m.s, h: r.h / m.s};
  }
  /**
   * Carry `preserved` into the fresh `dst` element `el`. A pin facades `el` onto
   * it; a bridge keeps it as a visible overlay at `dst.rect` (bridgeTo34 +
   * keepAtSlot) and SUPPRESSES `el`, the export's broken autoplay-from-0, so
   * only the continuing decoder composites. A visibility-gated footprint owner
   * then resolves the overlay, not the hidden restart. The bridge does NOT
   * bindFacade (a one-shot DOM swap did not survive slide-4's second build):
   * the overlay is authoritative, el is inert. The rects on the note are
   * diagnostic only; identity is the objectID.
   */
  function carry(el, value, preserved, entry) {
    const key = assetKey(value);
    const bridge = entry.action === 'bridge';
    unpool(preserved);
    hold(preserved, entry);
    tag(preserved);
    note(bridge ? 'bridge-3to4' : 'reuse-decoder', {
      key: key, newElId: el.__obedElId, oldElId: preserved.__obedElId,
      preservedT: preserved.currentTime, paused: preserved.paused,
      readyState: preserved.readyState,
      oldGen: preserved.__obedGen, generation: preserveGeneration,
      queueLeft: (pool.get(key) || []).length,
      atScene: entry.atScene, src: entry.src.objectId, dst: entry.dst.objectId,
      srcRect: entry.src.rect || null, measuredRect: authoredOfScreen(preserved.__obedRect)
    });
    if (bridge) {
      bridgeTo34(preserved, entry);
      el.__obedSuppressed34 = true;
      keepSuppressed(el);
      return;
    }
    // Out of a held bridge overlay the player's own layer paints under its
    // WebGL poster (live D1/D3/D4: clock advancing, pixels frozen), so re-home
    // the decoder the way a pooled pin is remounted: into the destination
    // poster's authored layer, measure-and-corrected at `dst.rect`.
    const rehome = !!preserved.__obedBridged34;
    if (rehome) {
      preserved.__obedBridged34 = false;
      preserved.__obedRemountEpoch = remountEpoch;
    }
    try {
      if (el.id) preserved.id = preserved.__obedId = el.id;
      const st = el.getAttribute('style');
      if (st && !rehome) preserved.setAttribute('style', st);
    } catch (e) {}
    bindFacade(el, preserved, rehome);
    if (rehome) {
      const screen = toScreen(entry.dst.rect);
      if (screen) preserved.__obedRect = screen;
      preserved.__obedParent = null;
      scheduleRemount(preserved, 'pin-rehome');
    }
  }
  /**
   * A fresh element of a restarted movie at/after the restart's `atScene` is
   * the authored fresh Start Movie — never stitch a preserved decoder onto it.
   * Retire the decoders still carrying THIS restart's `src` so they stop
   * remounting over the restart movie; any other instance is never touched.
   * Not at `atScene - 1`: that would blank the outgoing movie during the Dissolve.
   */
  function retireRestarted(el, value) {
    const mk = movieAssetKey(value);
    const hn = currentHashNum();
    if (mk == null || hn == null) return;
    ENTRIES.forEach(function(b) {
      if (b.action !== 'restart' || b.movieKey !== mk || hn < b.atScene) return;
      const olds = carryCandidates().filter(function(c) { return c !== el && isCarrySource(c, b); });
      if (!olds.length) return;
      const key = assetKey(value);
      note('reuse-skip-boundary', {key: key, newElId: el.__obedElId, hashNum: hn, boundary: b.atScene, queueLen: olds.length});
      const elIds = olds.map(function(c) {
        unpool(c);
        return retireDecoder(c);
      });
      note('retire-on-start-movie', {key: key, elIds: elIds, hashNum: hn});
    });
  }
  const origCreate = Document.prototype.createElement;
  Document.prototype.createElement = function(name, opts) {
    const el = origCreate.call(this, name, opts);
    if (String(name).toLowerCase() !== 'video') return el;
    tag(el);
    el.__obedGen = preserveGeneration;
    note('createElement-video', {elId: el.__obedElId, gen: preserveGeneration});
    const origSA = el.setAttribute.bind(el);
    el.setAttribute = function(attr, value) {
      if (disabled || String(attr).toLowerCase() !== 'src') return origSA(attr, value);
      reidentify(el, value);
      const mode = zoneMode(el);
      if (mode === 'armed') noteHold(el, value, 'reuse');
      if (mode !== 'allow') return origSA(attr, value);
      retireRestarted(el, value);
      const entry = carryEntryTo(instanceOf(el));
      const preserved = entry ? pickCarried(el, value, entry) : null;
      if (!preserved) return origSA(attr, value);
      carry(el, value, preserved, entry);
      if (entry.action === 'bridge') return origSA(attr, value);
    };
    return el;
  };
  if (GL) {
    window.__OBED_P2_PRESERVE__.glReplay = {
      version: 1,
      carried: function(movieKey) { return glCarried(movieKey); },
      movieKeyOf: function(v) {
        zoneState(false);
        return v ? movieKeyFor(v, v.currentSrc || v.src || '') : null;
      },
      setKeepWarm: function(v, on) {
        zoneState(false);
        if (v && v === carriedMemo) v.__obedGlNoWarm = !on;
      },
      release: function(movieKey, opts) { return glRelease(movieKey, opts); },
      note: function(kind, detail) {
        zoneState(false);
        if (GL_NOTE_KINDS.indexOf(kind) < 0) return;
        if (kind === 'glreplay-arm' && currentHashNum() === GL.atScene - 1) armSeen = true;
        if (kind === 'glreplay-live') liveSeen = true;
        note(kind, detail);
      }
    };
  }
  window.__OBED_P2_PRESERVE__.ready = true;
})();
""".strip()


def js_sha256() -> str:
    return hashlib.sha256(PRESERVE_CORE_JS.encode()).hexdigest()
