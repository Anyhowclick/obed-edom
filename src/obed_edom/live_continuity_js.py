"""Shared preserve-runtime JS core injected by P2 scripts and (later) the live host.

PRESERVE_CORE_JS mirrors 'src/obed_edom/live_runtime.py': one pinned copy of the
injected bytes, versioned and hashed. Verbatim carry-over from
`scripts/p2_recovery_html_dissolve_live.py` PRESERVE_SCRIPT (I0 step A), with the
dead canvas texture-feed stack removed (I0 step B) and the fixture constants
parameterised via one injected plan object (I0 step C).

Plan object (`window.__OBED_CONTINUITY__`, set before this script runs; absent
=> the core installs nothing):
    {
      "movies": {
        "<movieKey>": {"assetKeys": ["<substring(s) of the <video> src>"],
                        "footprint": {"x": int, "y": int, "w": int, "h": int}}
      },
      "boundaries": [
        {"atScene": <scene index>, "action": "restart" | "bridge",
         "rect": {"x": int, "y": int, "w": int, "h": int},   // "bridge" only
         "movieKey": "<movieKey>"}                            // "bridge" only
      ],
      "transparentBackground": <bool, optional, default false>
    }
`transparentBackground` gates `forceTransparentChrome()`: true for the
alpha/attach output and for the P2 scripts (their fixed black background is
the runtime's, not the player's), false for HDMI where the player's own black
background must show through untouched (owner decision 2a).
A scene index at or after a boundary's `atScene` (and before any later
boundary) is in that boundary's zone; before the first boundary the implicit
action is "pin" (the movie continues across the cut at a static footprint —
the existing 1->2 handling, which needs no boundary entry). "restart" retires
the preserved decoder so the export's fresh element plays; "bridge" carries
the preserved decoder to `rect`, suppressing the export's fresh element. A
later increment derives this plan from export data instead of a fixture.
"""
from __future__ import annotations

import hashlib

CONTINUITY_VERSION = 1

PRESERVE_CORE_JS = r"""
(function(){
  // Fail-closed: no plan, no install. The caller (P2 script or, later, the
  // live host) injects window.__OBED_CONTINUITY__ before this script tag runs.
  var OBED_PLAN = window.__OBED_CONTINUITY__;
  if (!OBED_PLAN) return;
  if (window.__OBED_P2_PRESERVE__) return;
  window.__OBED_P2_PRESERVE__ = {
    version: 6,
    mode: 'decoder-preserve',
    events: [],
    poolKeys: [],
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
        document.querySelectorAll('video[data-obed-preserved="1"]').forEach(function(v) {
          try {
            v.pause();
            delete v.dataset.obedPreserved;
            v.__obedRemountEpoch = -1;
            v.__obedGen = -1;
            if (v.parentNode) v.parentNode.removeChild(v);
          } catch (e) {}
        });
        note('pool-cleared', {
          remountEpoch: remountEpoch,
          preserveGeneration: preserveGeneration
        });
      } finally {
        suppressRemount = false;
      }
    },
    snapshot: function() {
      const out = [];
      pool.forEach(function(q, key) {
        (q || []).forEach(function(v) {
          out.push({
            key: key,
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
        out.push({
          key: assetKey(v.currentSrc || v.src || ''),
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
    /** Which live decoder owns a screen rect's movie footprint. */
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
      // Collect the positioned movie <video>s (DOM + pool, deduped) whose rendered
      // rect closely MATCHES the footprint, THEN decide ownership from the global
      // maximum overlap — order-independent so a later-best cannot mis-clear an
      // earlier tie. Gate on intersection-over-union (IoU), not bare overlap: IoU
      // penalises BOTH a too-small owner (partial / quarter-sized / mis-scaled
      // remount rendering smaller than the authored box) AND a too-large one (a
      // giant surface that merely contains the footprint), so only a <video>
      // rendered at ~the footprint geometry can own it (fail closed otherwise).
      const fpArea = Math.max(1, rect.w * rect.h);
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
        const ov = rectOverlapArea(r, rect);
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
      const distinct = [];
      near.forEach(function(x) { if (distinct.indexOf(x.v) < 0) distinct.push(x.v); });
      if (distinct.length > 1) {
        return {elId: null, key: null, via: 'ambiguous', contextType: null};
      }
      const owner = near.reduce(function(a, b) { return b.iou > a.iou ? b : a; });
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
  // Boundaries are {atScene, action: 'restart'|'bridge', rect?, movieKey?},
  // generic scene-index cut points the plan supplies (I0 step C). The lowest
  // atScene for a given action is that action's onset.
  function boundariesByAction(action) {
    const arr = (OBED_PLAN && Array.isArray(OBED_PLAN.boundaries)) ? OBED_PLAN.boundaries : [];
    return arr.filter(function(b) { return b && b.action === action && typeof b.atScene === 'number'; });
  }
  function restartMinHash() {
    const restarts = boundariesByAction('restart');
    if (!restarts.length) return Infinity;
    return restarts.reduce(function(m, b) { return Math.min(m, b.atScene); }, Infinity);
  }
  // First scene of the bridged destination (e.g. the 3->4 magic-move slide).
  // The dissolve restart zone is [restartMinHash, slide4MinHash); at/after
  // slide4MinHash a fresh element is the export's broken autoplay-from-0 for a
  // magic move that is AUTHORED continuity ("Play across slides") and must be
  // BRIDGED (reuse the live decoder), not retired. null => no bridge.
  function slide4MinHash() {
    const bridges = boundariesByAction('bridge');
    if (!bridges.length) return null;
    return bridges.reduce(function(m, b) { return Math.min(m, b.atScene); }, Infinity);
  }
  function bridgeBoundary() {
    const bridges = boundariesByAction('bridge');
    if (!bridges.length) return null;
    return bridges.reduce(function(a, b) { return b.atScene < a.atScene ? b : a; });
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
  function stash(v, why) {
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
    if (!(v.readyState >= 2 || v.currentTime > 0.05)) return;
    tag(v);
    if (!pool.has(key)) pool.set(key, []);
    const q = pool.get(key);
    if (q.indexOf(v) < 0) q.push(v);
    v.dataset.obedPreserved = '1';
    // Remember layout so we can remount as a visible overlay after Magic Move
    // tears the video layer down and leaves only the WebGL/poster texture.
    try {
      const r = v.getBoundingClientRect();
      if (r.width > 1 && r.height > 1) {
        v.__obedRect = {x: r.left, y: r.top, w: r.width, h: r.height};
      } else {
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
   * z-order (no reparent, no forced z-index). Runs only through the 1->2 window and
   * stops at the 2->3 restart boundary / retire so the restart teardown is untouched.
   */
  function keepAtFootprint(v, tx, ty) {
    if (v.__obedPinning) return;
    v.__obedPinning = true;
    function frame() {
      if (v.__obedRemountEpoch === -1 || v.ended || !document.contains(v)) {
        v.__obedPinning = false; return;
      }
      const hn = currentHashNum();
      if (hn != null && hn >= restartMinHash()) { v.__obedPinning = false; return; }
      if (v.dataset.obedRemounted === '1') {
        const cur = v.getBoundingClientRect();
        if (cur.width > 1 && cur.height > 1) {
          const dx = tx - cur.left, dy = ty - cur.top;
          if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
            v.style.left = ((parseFloat(v.style.left) || 0) + dx) + 'px';
            v.style.top = ((parseFloat(v.style.top) || 0) + dy) + 'px';
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
  function slide4Rect() {
    const b = bridgeBoundary();
    const r = b && b.rect;
    if (r && typeof r === 'object' && r.w > 1 && r.h > 1) return r;
    return null;
  }
  function keepAtSlot(real, stub) {
    if (real.__obedSlotPinning) return;
    real.__obedSlotPinning = true;
    const s4 = slide4MinHash();
    function frame() {
      const hn = currentHashNum();
      if (real.ended || !document.contains(real)
          || (s4 != null && hn != null && hn < s4)) {
        real.__obedSlotPinning = false; return;
      }
      // Pin to the authored slide-4 destination rect (measure-and-correct so it
      // holds through the containing layer's magic-move transform). Defeats a
      // re-detach's fresh scheduleRemount/footprint-fallback from dragging the
      // bridged decoder off the slide-4 slot at the #8->#9 boundary.
      const dest = slide4Rect();
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
  function bridgeTo34(v) {
    v.__obedBridged34 = true;
    v.__obedRemountEpoch = -1;   // cancel any pending 1->2 remount for v
    v.__obedPinning = false;
    const dest = slide4Rect();
    const stage = document.getElementById('body') || document.querySelector('[class*="stage"]') || document.body;
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
    keepAtSlot(v, null);
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
    const posTol = 10, sizeTol = 16;
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
  function tryRemount(v, epoch) {
    if (!v || suppressRemount) return;
    if (epoch != null && epoch !== remountEpoch) {
      note('remount-stale', {elId: v.__obedElId, epoch: epoch, current: remountEpoch});
      return;
    }
    if (v.__obedRemountEpoch === -1 || v.ended) return;
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
    if (!(v.__obedRect && v.__obedRect.w > 1)) captureLayout(v);
    let box = v.__obedRect || {};
    // Detach can leave getBoundingClientRect at 0,0 relative to a parent that is already gone.
    // Fall back to the authored movie footprint (its real on-screen slot) — never overlay at 0,0.
    if (!(box.w > 1 && box.h > 1) || (Math.abs(box.x) < 2 && Math.abs(box.y) < 2)) {
      const movies = planMovies();
      const fps = Object.keys(movies).map(function(k) { return movies[k].footprint; }).filter(Boolean);
      const fp = fps.length ? fps[((v.__obedElId || 1) - 1) % fps.length] : {x: 0, y: 0, w: box.w, h: box.h};
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
        v.style.position = 'absolute';
        v.style.width = box.w + 'px';
        v.style.height = box.h + 'px';
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
        v.style.left = (box.x - cur.left) + 'px';
        v.style.top = (box.y - cur.top) + 'px';
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
  function bindFacade(stub, real) {
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
      if (stub.parentNode && real !== stub) {
        try {
          const parent = stub.parentNode;
          const next = stub.nextSibling;
          parent.removeChild(stub);
          if (real.parentNode && real.parentNode !== parent) {
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
        const parent = v.parentElement;
        const pr = parent ? parent.getBoundingClientRect() : {left: 0, top: 0};
        v.__obedRect = {
          x: pr.left || 0,
          y: pr.top || 0,
          w: parseFloat(mw[1]),
          h: parseFloat(mh[1])
        };
        return v.__obedRect.w > 1;
      }
    } catch (e) {}
    return false;
  }

  // Detached decoders often pause; keep pooled clocks alive through Magic Move.
  // Refresh layout while videos are still attached (detach often zeroes the box).
  setInterval(function(){
    document.querySelectorAll('video').forEach(function(v){ captureLayout(v); });
    pool.forEach(function(q){
      (q || []).forEach(function(v){
        try {
          if (v && v.paused && !v.ended) {
            const p = v.play();
            if (p && p.catch) p.catch(function(){});
          }
        } catch (e) {}
      });
    });
  }, 200);

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
        if (empty && this instanceof HTMLVideoElement) {
          stash(this, 'preserve-skip-clear');
          // Skip clearing so the decoder stays attached to its resource.
          return;
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
    if (String(name).toLowerCase() === 'src' && this instanceof HTMLVideoElement) {
      stash(this, 'preserve-skip-removeAttribute');
      return;
    }
    return origRemove.call(this, name);
  };

  // Pool videos that are detached without an src clear (common slide teardown path).
  new MutationObserver(function(muts){
    muts.forEach(function(m){
      m.removedNodes.forEach(function(node){
        if (node instanceof HTMLVideoElement) stash(node, 'preserve-on-detach');
        else if (node && node.querySelectorAll) {
          node.querySelectorAll('video').forEach(function(v){ stash(v, 'preserve-on-detach-subtree'); });
        }
      });
    });
  }).observe(document.documentElement, {childList: true, subtree: true});

  const origCreate = Document.prototype.createElement;
  Document.prototype.createElement = function(name, opts) {
    const el = origCreate.call(this, name, opts);
    if (String(name).toLowerCase() !== 'video') return el;
    tag(el);
    el.__obedGen = preserveGeneration;
    note('createElement-video', {elId: el.__obedElId, gen: preserveGeneration});
    const origSA = el.setAttribute.bind(el);
    el.setAttribute = function(attr, value) {
      if (String(attr).toLowerCase() === 'src') {
        const key = assetKey(value);
        const hn = currentHashNum();
        const boundary = restartMinHash();
        const s4 = slide4MinHash();
        const q = pool.get(key);
        // Retire ONLY inside the 2->3 dissolve restart zone [boundary, s4). A
        // fresh element at/after s4 is the 3->4 magic-move destination (authored
        // continuity broken by the export's autoplay-from-0) and falls through to
        // the reuse path below so the live decoder BRIDGES the moving cut.
        const inDissolveRestartZone = hn != null && hn >= boundary
          && (s4 == null || hn < s4);
        if (inDissolveRestartZone && q && q.length) {
          // On/after the restart boundary this is the authored fresh Start
          // Movie — never stitch a preserved decoder onto it.
          note('reuse-skip-boundary', {key: key, newElId: el.__obedElId, hashNum: hn, boundary: boundary, queueLen: q.length});
          // Retire the old decoders for THIS key only so they stop remounting
          // over the restart movie and polluting slide-3 clock scoring. A
          // continuing movie under a different key is never touched.
          const elIds = [];
          while (q.length) {
            const old = q.shift();
            elIds.push(old.__obedElId);
            try { old.pause(); } catch (e) {}
            try {
              if (old.parentNode) old.parentNode.removeChild(old);
            } catch (e) {}
            delete old.dataset.obedPreserved;
            delete old.dataset.obedRemounted;
            old.__obedRemountEpoch = -1;
            old.__obedGen = -1;
          }
          pool.delete(key);
          note('retire-on-start-movie', {key: key, elIds: elIds, hashNum: hn});
        } else {
          // Never reuse a decoder from an older preserve generation.
          let preserved = null;
          if (q && q.length) {
            while (q.length) {
              const cand = q.shift();
              if ((cand.__obedGen == null ? 0 : cand.__obedGen) < preserveGeneration) {
                note('reuse-skip-stale', {
                  key: key, elId: cand.__obedElId,
                  gen: cand.__obedGen, current: preserveGeneration
                });
                continue;
              }
              preserved = cand;
              break;
            }
            if (q.length === 0) pool.delete(key);
          }
          if (preserved && preserved !== el) {
            tag(preserved);
            const bridging34 = s4 != null && hn != null && hn >= s4;
            note(bridging34 ? 'bridge-3to4' : 'reuse-decoder', {
              key: key, newElId: el.__obedElId, oldElId: preserved.__obedElId,
              preservedT: preserved.currentTime, paused: preserved.paused,
              readyState: preserved.readyState,
              queueLeft: q ? q.length : 0
            });
            if (bridging34) {
              // 3->4 magic-move continuity: keep the preserved live decoder as a
              // visible overlay at the slide-4 destination (bridgeTo34 + keepAtSlot)
              // and SUPPRESS the export's fresh autoplay-from-0 element so only the
              // continuing decoder composites. A visibility-gated footprint owner
              // then resolves the overlay, not the hidden restart. We do NOT
              // bindFacade here (a one-shot DOM swap did not survive slide-4's
              // second build): the overlay is authoritative, el is inert.
              bridgeTo34(preserved);
              el.__obedSuppressed34 = true;
              keepSuppressed(el);
              return origSA(attr, value);
            }
            try {
              if (el.id) preserved.id = el.id;
              const st = el.getAttribute('style');
              if (st) preserved.setAttribute('style', st);
            } catch (e) {}
            bindFacade(el, preserved);
            return;
          }
        }
      }
      return origSA(attr, value);
    };
    return el;
  };
})();
""".strip()


def js_sha256() -> str:
    return hashlib.sha256(PRESERVE_CORE_JS.encode()).hexdigest()
