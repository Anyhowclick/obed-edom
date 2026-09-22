"""GL-replay runtime (stage G2): the in-page module that replays the settled
Magic-Move frame with the carried decoder's live texture.

Plan: `.agents/plans/keynote_live_gl_replay_g2.plan.md` rev 2 §2. The module is a
sibling of `live_continuity_js.py` -- its own version and sha, so a change here
never rides on the continuity sha -- and is injected by the host (G4) only when
`derive_plan` emitted a `glReplay` boundary. Off means the builder returns `""`
and nothing is injected or evaluated.

The JS reads its boundary entry from `window.__OBED_CONTINUITY__`, re-validates
it in page, consumes only `window.__OBED_P2_PRESERVE__.glReplay` (the G3 seam)
and `window.__obedLive.snapshot()`, and publishes
`window.__OBED_GL_REPLAY__` plus, in LIVE only, the oracle handle
`window.__OBED_GL_ORACLE__` read by `scripts/live_continuity_probe.py`.

`writebackFailed` is a SECONDARY reason: it is only ever recorded alongside the
primary reason that triggered the stand-down, so it has no standalone path and
the fail-closed arm reaches it through whichever primary reason it accompanies.

`debugForceFail` is seeded only from a pre-existing partial
`window.__OBED_GL_REPLAY__` (:28-29 returns whenever one carries a version), so
no product injection can set it. `API.debug` is seeded under the same condition.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

GL_REPLAY_VERSION = 1

GL_REPLAY_JS = r"""
(function(){
  if (typeof window === 'undefined') return;
  var PRESET = window.__OBED_GL_REPLAY__;
  if (PRESET && PRESET.version) return;

  var CONTROL_PATCH_PX = 40;
  var CONTROL_INSET_PX = 4;
  var BAND_COLS = 16;
  var BAND_ROWS = 8;
  var GREEN_INSET_PX = 8;
  var SEAM_VERSION = 1;
  var SEGMENT_CALL_CAP = 512;
  var SETTLE_QUIET_TICKS = 3;
  var OCCLUSION_MAX_FRACTION = 0.5;
  var MARKER_BAND_EPSILON = 0.5;
  var MARKER_PATCH_PX = 8;
  var MVP_TOLERANCE_PX = 1;
  var ABLATION_GRID_PX = 4;
  var ABLATION_DILATION_PX = 8;
  var ABLATION_COVERAGE_MIN = 0.8;
  var UNIFORM_NAMES = ['MVPMatrix', 'mixFactor', 'Opacity', 'Texture', 'Texture2'];
  var CANVAS_ID_RE = /^\d+-canvas$/;

  var API = {
    version: 1,
    state: 'IDLE',
    events: [],
    notes: [],
    standDowns: [],
    debugForceFail: (PRESET && PRESET.debugForceFail) || null,
    stats: function(){ return statsOf(); }
  };

  // Reachable only when a pre-existing partial `window.__OBED_GL_REPLAY__` seeded
  // it, exactly like `debugForceFail`; the product path never creates one.
  if (PRESET){
    API.debug = {
      replay: function(opts){ return replayFrame(opts || {}); },
      programs: function(){
        return state.programs.map(function(prog, slot){
          var loc = state.locations[slot];
          var current = null;
          if (prog && loc && loc.Opacity && state.gl){
            try { current = state.gl.getUniform(prog, loc.Opacity); } catch (e) { current = null; }
          }
          return {slot: slot, program: prog || null, restOpacity: state.restOpacity[slot],
                  override: state.overrides[slot] == null ? null : state.overrides[slot],
                  opacity: current};
        });
      }
    };
  }

  function finite(v){ return typeof v === 'number' && isFinite(v); }
  function rectOf(a){ return {x: a[0], y: a[1], w: a[2], h: a[3]}; }

  function validEntry(e, plan){
    if (!e || typeof e !== 'object') return null;
    if (e.action !== 'glReplay' || e.fallback !== 'retire') return null;
    if (typeof e.atScene !== 'number' || !isFinite(e.atScene) || e.atScene !== Math.floor(e.atScene)) return null;
    if (typeof e.movieKey !== 'string' || !e.movieKey) return null;
    if (!plan.movies || !plan.movies[e.movieKey]) return null;
    var sizes = e.slotSizes, rects = e.slotRects, ovr = e.opacityOverrides;
    if (!Array.isArray(sizes) || !sizes.length) return null;
    if (!Array.isArray(rects) || rects.length !== sizes.length) return null;
    for (var i = 0; i < sizes.length; i++){
      var s = sizes[i];
      if (!Array.isArray(s) || s.length !== 2 || !finite(s[0]) || !finite(s[1]) || s[0] <= 0 || s[1] <= 0) return null;
      var r = rects[i];
      if (!Array.isArray(r) || r.length !== 4) return null;
      for (var k = 0; k < 4; k++) if (!finite(r[k])) return null;
      if (r[2] <= 0 || r[3] <= 0) return null;
    }
    if (!Array.isArray(ovr)) return null;
    for (var j = 0; j < ovr.length; j++){
      var o = ovr[j];
      if (!o || typeof o !== 'object') return null;
      if (typeof o.slot !== 'number' || o.slot !== Math.floor(o.slot) || o.slot < 0 || o.slot >= sizes.length) return null;
      if (!finite(o.opacity) || !(o.opacity > 0) || !(o.opacity < 1)) return null;
      if (o.texW !== sizes[o.slot][0] || o.texH !== sizes[o.slot][1]) return null;
    }
    if (typeof e.instanceId !== 'string' || e.instanceId.indexOf('#') < 0) return null;
    var ir = e.instanceRect;
    if (!ir || typeof ir !== 'object') return null;
    if (!finite(ir.x) || !finite(ir.y) || !finite(ir.w) || !finite(ir.h) || ir.w <= 0 || ir.h <= 0) return null;
    if (typeof e.movieSlot !== 'number' || e.movieSlot !== Math.floor(e.movieSlot)) return null;
    if (e.movieSlot < 0 || e.movieSlot >= sizes.length) return null;
    return e;
  }

  var PLAN = window.__OBED_CONTINUITY__;
  if (!PLAN || typeof PLAN !== 'object' || !Array.isArray(PLAN.boundaries)) return;
  var candidates = PLAN.boundaries.filter(function(b){ return b && b.action === 'glReplay'; });
  if (!candidates.length) return;

  window.__OBED_GL_REPLAY__ = API;
  var ENTRY = candidates.length === 1 ? validEntry(candidates[0], PLAN) : null;

  var INFO = window.__OBED_CONTINUITY_INFO__ || {};
  var MOVIE_SLOT = ENTRY ? ENTRY.movieSlot : 0;

  var state = {
    phase: 'IDLE', recording: false, hot: false, replaying: 0, down: false,
    gl: null, canvas: null, video: null, seam: null,
    segment: [], retained: [], frame: null, frameLen: 0,
    poster: null, posterTex: null, posterUpload: null, posterAmbiguous: false,
    programs: [], locations: [], restOpacity: [], opacityAfterProofs: null,
    overrides: {}, unproven: [],
    epoch: 0, frozenSceneId: null, loopGen: 0, arming: false, pending: null, retainedTick: -1,
    iter: 0, uploads: 0, glErrors: 0, tick: 0, lastPlayerTick: -1,
    lastClearAt: null, readyAt: null, settleGapMs: null, settleToHashMs: null,
    mutationScanMs: null, occluded: null, mask: null,
    paused: false, pausedByUs: false, geometry: null, buffers: null,
    collectors: [], observer: null
  };

  function now(){ return performance.now(); }

  // Every stand-down reason of plan §2.7 is a literal defined once; the sites
  // that can emit it are listed in plan §2.7.
  function assertOr(reason, ok, detail){
    if (ok && API.debugForceFail !== reason) return true;
    // An ARM-PRE requirement that is not yet met is only recorded until the armed
    // context exists; from then on it is an ordinary stand-down (plan §2.2).
    if (state.arming && !state.gl){ state.pending = reason; return false; }
    standDown(reason, detail || null);
    return false;
  }
  function refuseInstall(reason, ok){
    if (ok && API.debugForceFail !== reason) return true;
    API.standDowns.push(reason);
    API.state = 'RETIRED';
    event('glreplay-standdown', {reason: reason});
    return false;
  }
  var CANVAS_REMOVED = 'canvasRemoved';
  var UNFLAGGED_PLAYER_CALL = 'unflaggedPlayerCall';
  var CONTEXT_LOST = 'contextLost';
  var FRAME_LENGTH_CHANGED = 'frameLengthChanged';
  var WRITEBACK_FAILED = 'writebackFailed';

  function requireDelimitedFrame(ok, detail){ return assertOr('frameNotDelimited', ok, detail); }
  function requireVideoFrameCallback(ok){ return assertOr('rvfcUnavailable', ok, null); }

  function event(kind, detail){
    var rec = {kind: kind, detail: detail || {}, t: now()};
    API.events.push(rec);
    if (kind === 'glreplay-opacity-unproven' || kind === 'glreplay-handoff') API.notes.push(rec);
    var seam = state.seam;
    if (seam && typeof seam.note === 'function'){ try { seam.note(kind, rec.detail); } catch (e) {} }
  }

  function currentHashNum(){
    var m = /^#?(\d+)/.exec(String(location.hash || ''));
    return m ? parseInt(m[1], 10) : null;
  }

  function liveSnapshot(){
    try { return window.__obedLive ? window.__obedLive.snapshot() : null; } catch (e) { return null; }
  }

  function statsOf(){
    return {
      version: API.version, state: API.state, epoch: state.epoch, iter: state.iter,
      frameLen: state.frameLen, uploads: state.uploads, glErrors: state.glErrors,
      settleGapMs: state.settleGapMs, settleToHashMs: state.settleToHashMs,
      mutationScanMs: state.mutationScanMs,
      pending: state.pending, occludedBands: state.occluded, occluderMask: state.mask,
      bandCount: BAND_COLS * BAND_ROWS,
      opacityUnproven: state.unproven.slice(),
      restOpacity: state.restOpacity.slice(),
      opacityAfterProofs: state.opacityAfterProofs ? state.opacityAfterProofs.slice() : null,
      programsDistinct: state.programs.every(function(prog, slot){
        return state.programs.indexOf(prog) === slot;
      }),
      greenAuthored: state.geometry ? state.geometry.greenAuthored : null,
      greenRoi: state.geometry ? state.geometry.green : null,
      geometry: state.geometry, canvasId: state.canvas ? state.canvas.id : null
    };
  }

  // ---------------------------------------------------------------- textures
  var boundTex = new WeakMap();
  var lastUpload = new WeakMap();

  function bindingsOf(g){
    var m = boundTex.get(g);
    if (!m){ m = {}; boundTex.set(g, m); }
    return m;
  }

  // ---------------------------------------------------------------- wrapping
  var SKIP = /^(get|is|read|create|delete|checkFramebufferStatus)/;

  function uploadInfo(g, args, name){
    var src = args[args.length - 1];
    var info = {
      call: name, nargs: args.length,
      flipY: g.getParameter(g.UNPACK_FLIP_Y_WEBGL),
      premul: g.getParameter(g.UNPACK_PREMULTIPLY_ALPHA_WEBGL),
      intFmt: args[2], extFmt: args[args.length - 3], type: args[args.length - 2],
      srcType: null, w: null, h: null
    };
    if (typeof HTMLCanvasElement !== 'undefined' && src instanceof HTMLCanvasElement){
      info.srcType = 'canvas'; info.w = src.width; info.h = src.height;
    } else if (typeof HTMLVideoElement !== 'undefined' && src instanceof HTMLVideoElement){
      info.srcType = 'video'; info.w = src.videoWidth; info.h = src.videoHeight;
    } else if (src && src.width && src.height){
      info.srcType = 'other'; info.w = src.width; info.h = src.height;
    }
    return info;
  }

  function onPlayerUpload(g, args, name){
    var info = uploadInfo(g, args, name);
    var tex = bindingsOf(g)[args[0]];
    if (tex) lastUpload.set(tex, info);
    if (!tex || g !== state.gl) return;
    var want = ENTRY.slotSizes[MOVIE_SLOT];
    var matches = info.srcType === 'canvas' && info.w === want[0] && info.h === want[1] &&
      info.extFmt === g.RGBA && info.type === g.UNSIGNED_BYTE && !!info.flipY && !!info.premul;
    if (!matches) return;
    if (!state.posterTex){ state.posterTex = tex; state.posterUpload = info; return; }
    if (tex !== state.posterTex) state.posterAmbiguous = true;
  }

  function wrapContexts(){
    var protos = [];
    if (window.WebGLRenderingContext) protos.push(WebGLRenderingContext.prototype);
    if (window.WebGL2RenderingContext) protos.push(WebGL2RenderingContext.prototype);
    protos.forEach(function(P){
      Object.getOwnPropertyNames(P).forEach(function(name){
        var d;
        try { d = Object.getOwnPropertyDescriptor(P, name); } catch (e) { return; }
        if (!d || typeof d.value !== 'function' || name === 'constructor') return;
        if (d.value.__obedGlReplay) return;
        if (SKIP.test(name)) return;
        var orig = d.value;
        var wrapper = function(){
          if (!state.hot || state.replaying || this !== state.gl) return orig.apply(this, arguments);
          if (state.phase === 'LIVE' || state.phase === 'ARM-POST' ||
              API.debugForceFail === UNFLAGGED_PLAYER_CALL){
            assertOr(UNFLAGGED_PLAYER_CALL, false, {call: name});
            return orig.apply(this, arguments);
          }
          state.lastPlayerTick = state.tick;
          if (name === 'clear') state.lastClearAt = now();
          if (name === 'bindTexture') bindingsOf(this)[arguments[0]] = arguments[1];
          if (name === 'texImage2D' || name === 'texSubImage2D'){
            try { onPlayerUpload(this, arguments, name); } catch (e) {}
          }
          if (state.recording) record(this, name, arguments);
          var rv = orig.apply(this, arguments);
          if (state.recording && name === 'clear') perClearUpload();
          return rv;
        };
        wrapper.__obedGlReplay = 1;
        P[name] = wrapper;
      });
    });
  }

  function record(g, name, args){
    var a = new Array(args.length);
    for (var i = 0; i < args.length; i++) a[i] = args[i];
    var call = {g: g, m: name, a: a};
    if (name === 'clear'){
      var carry = null;
      var seg = state.segment;
      if (seg.length && seg[seg.length - 1].m === 'clearColor') carry = seg.pop();
      if (seg.length){ state.retained = seg; state.retainedTick = state.tick; }
      state.segment = carry ? [carry] : [];
    }
    state.segment.push(call);
    requireDelimitedFrame(state.segment.length <= SEGMENT_CALL_CAP, {len: state.segment.length});
  }

  // ------------------------------------------------------------ GL utilities
  function uploadInto(tex, up, source){
    var g = state.gl;
    state.replaying++;
    try {
      var sb = g.getParameter(g.TEXTURE_BINDING_2D);
      var fy = g.getParameter(g.UNPACK_FLIP_Y_WEBGL);
      var pm = g.getParameter(g.UNPACK_PREMULTIPLY_ALPHA_WEBGL);
      g.bindTexture(g.TEXTURE_2D, tex);
      g.pixelStorei(g.UNPACK_FLIP_Y_WEBGL, up.flipY);
      g.pixelStorei(g.UNPACK_PREMULTIPLY_ALPHA_WEBGL, up.premul);
      g.texImage2D(g.TEXTURE_2D, 0, up.intFmt, up.extFmt, up.type, source);
      g.pixelStorei(g.UNPACK_FLIP_Y_WEBGL, fy);
      g.pixelStorei(g.UNPACK_PREMULTIPLY_ALPHA_WEBGL, pm);
      g.bindTexture(g.TEXTURE_2D, sb);
    } catch (e) {}
    state.replaying--;
  }

  function paintTexture(tex, up, r, gr, b){
    var g = state.gl;
    state.replaying++;
    try {
      var sb = g.getParameter(g.TEXTURE_BINDING_2D);
      var n = MARKER_PATCH_PX, px = new Uint8Array(n * n * 4);
      for (var i = 0; i < n * n; i++){ px[i * 4] = r; px[i * 4 + 1] = gr; px[i * 4 + 2] = b; px[i * 4 + 3] = 255; }
      var fy = g.getParameter(g.UNPACK_FLIP_Y_WEBGL);
      var pm = g.getParameter(g.UNPACK_PREMULTIPLY_ALPHA_WEBGL);
      g.bindTexture(g.TEXTURE_2D, tex);
      g.pixelStorei(g.UNPACK_FLIP_Y_WEBGL, false);
      g.pixelStorei(g.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
      g.texImage2D(g.TEXTURE_2D, 0, up.intFmt, n, n, 0, up.extFmt, up.type, px);
      g.pixelStorei(g.UNPACK_FLIP_Y_WEBGL, fy);
      g.pixelStorei(g.UNPACK_PREMULTIPLY_ALPHA_WEBGL, pm);
      g.bindTexture(g.TEXTURE_2D, sb);
    } catch (e) {}
    state.replaying--;
  }

  function posterOf(tex, up){
    var g = state.gl;
    state.replaying++;
    var out = {complete: false};
    try {
      var sfb = g.getParameter(g.FRAMEBUFFER_BINDING);
      var fb = g.createFramebuffer();
      g.bindFramebuffer(g.FRAMEBUFFER, fb);
      g.framebufferTexture2D(g.FRAMEBUFFER, g.COLOR_ATTACHMENT0, g.TEXTURE_2D, tex, 0);
      var st = g.checkFramebufferStatus(g.FRAMEBUFFER);
      var px = new Uint8Array(up.w * up.h * 4);
      if (st === g.FRAMEBUFFER_COMPLETE) g.readPixels(0, 0, up.w, up.h, g.RGBA, g.UNSIGNED_BYTE, px);
      g.bindFramebuffer(g.FRAMEBUFFER, sfb);
      g.deleteFramebuffer(fb);
      out = {complete: st === g.FRAMEBUFFER_COMPLETE, px: px, w: up.w, h: up.h,
             intFmt: up.intFmt, extFmt: up.extFmt, type: up.type};
    } catch (e) {}
    state.replaying--;
    return out;
  }

  function restorePoster(){
    var g = state.gl, P = state.poster;
    if (!g || !P || !P.px || !state.posterTex) return;
    state.replaying++;
    try {
      var sb = g.getParameter(g.TEXTURE_BINDING_2D);
      var fy = g.getParameter(g.UNPACK_FLIP_Y_WEBGL);
      var pm = g.getParameter(g.UNPACK_PREMULTIPLY_ALPHA_WEBGL);
      g.bindTexture(g.TEXTURE_2D, state.posterTex);
      g.pixelStorei(g.UNPACK_FLIP_Y_WEBGL, false);
      g.pixelStorei(g.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
      g.texImage2D(g.TEXTURE_2D, 0, P.intFmt, P.w, P.h, 0, P.extFmt, P.type, P.px);
      g.pixelStorei(g.UNPACK_FLIP_Y_WEBGL, fy);
      g.pixelStorei(g.UNPACK_PREMULTIPLY_ALPHA_WEBGL, pm);
      g.bindTexture(g.TEXTURE_2D, sb);
    } catch (e) {}
    state.replaying--;
  }

  function perClearUpload(){
    if (!state.posterTex || !state.posterUpload) return;
    if (!resolveVideo()) return;
    var v = state.video;
    if (!assertOr('videoNotReady', v.readyState >= 2, {readyState: v.readyState})) return;
    uploadInto(state.posterTex, state.posterUpload, v);
    state.uploads++;
  }

  function resolveVideo(){
    if (state.video) return true;
    var carried = null;
    try { carried = state.seam.carried(ENTRY.movieKey); } catch (e) { carried = null; }
    var v = carried && carried.video;
    if (!assertOr('assetUnbound', !!v, {reason: carried ? carried.reason : 'no seam answer'})) return false;
    state.video = v;
    return true;
  }

  // ------------------------------------------------------------ replay + read
  // The recorded frame sets `Opacity` for some programs and not others (opacity
  // plan F-10), so every replay writes the value it intends for EVERY draw --
  // otherwise a probe's uniform stays sticky on the program the frame never sets.
  // The rest value is captured per DRAW, immediately before that draw, so two
  // draws sharing one program keep their own value.
  function opacityFor(slot, opts){
    var rest = state.restOpacity[slot];
    if (opts.only != null) return opts.only === slot ? (opts.value == null ? rest : opts.value) : rest;
    if (opts.rest) return rest;
    return state.overrides[slot] != null ? state.overrides[slot] : rest;
  }

  function replayFrame(opts){
    opts = opts || {};
    var F = state.frame;
    if (!F) return 0;
    var g = state.gl;
    state.replaying++;
    var errs = 0, drawSeen = 0;
    for (var i = 0; i < F.length; i++){
      var e = F[i];
      var isDraw = e.m === 'drawArrays' || e.m === 'drawElements';
      if (isDraw){
        var slot = drawSeen++;
        var loc = state.locations[slot];
        if (opts.capture){
          state.restOpacity[slot] = null;
          if (loc && loc.Opacity && state.programs[slot]){
            try { state.restOpacity[slot] = g.getUniform(state.programs[slot], loc.Opacity); }
            catch (x) { state.restOpacity[slot] = null; }
          }
        } else {
          var value = opacityFor(slot, opts);
          if (value != null && loc && loc.Opacity){
            try { g.uniform1f(loc.Opacity, value); } catch (x) { errs++; }
          }
        }
        if (opts.skip === slot) continue;
      }
      try { e.g[e.m].apply(e.g, e.a); } catch (x) { errs++; }
    }
    state.replaying--;
    return errs;
  }

  function toBuffer(r){
    var c = state.canvas;
    var x = Math.min(Math.max(0, Math.round(r.x)), c.width - 1);
    var yTop = Math.round(r.y);
    var y = Math.min(Math.max(0, c.height - (yTop + Math.round(r.h))), c.height - 1);
    return {x: x, y: y,
            w: Math.max(1, Math.min(Math.round(r.w), c.width - x)),
            h: Math.max(1, Math.min(Math.round(r.h), c.height - y))};
  }

  function readInto(roi, buf){
    var g = state.gl;
    g.readPixels(roi.x, roi.y, roi.w, roi.h, g.RGBA, g.UNSIGNED_BYTE, buf);
  }

  function meanOf(px){
    var s = 0, n = px.length / 4;
    for (var i = 0; i < px.length; i += 4) s += px[i] + px[i + 1] + px[i + 2];
    return n ? s / (n * 3) : 0;
  }

  function rgbOf(px){
    var r = 0, g = 0, b = 0, n = px.length / 4;
    for (var i = 0; i < px.length; i += 4){ r += px[i]; g += px[i + 1]; b += px[i + 2]; }
    return n ? [r / n, g / n, b / n] : [0, 0, 0];
  }

  function bandsOf(px, W, H){
    var sum = new Float64Array(BAND_COLS * BAND_ROWS);
    var cnt = new Float64Array(BAND_COLS * BAND_ROWS);
    for (var y = 0; y < H; y++){
      var by = Math.min(BAND_ROWS - 1, Math.floor(y * BAND_ROWS / H));
      var row = y * W * 4;
      for (var x = 0; x < W; x++){
        var bx = Math.min(BAND_COLS - 1, Math.floor(x * BAND_COLS / W));
        var i4 = row + x * 4, k = by * BAND_COLS + bx;
        sum[k] += px[i4] + px[i4 + 1] + px[i4 + 2];
        cnt[k] += 3;
      }
    }
    var out = new Array(BAND_COLS * BAND_ROWS);
    for (var j = 0; j < out.length; j++) out[j] = cnt[j] ? sum[j] / cnt[j] : 0;
    return out;
  }

  function sampleOnce(meta){
    var g = state.gl, G = state.geometry, B = state.buffers;
    var t0 = now();
    state.replaying++;
    var bands = null, control = 0, green = NaN, greenRGB = [NaN, NaN, NaN], err = 0;
    try {
      readInto(G.band, B.band);
      readInto(G.control, B.control);
      bands = bandsOf(B.band, G.band.w, G.band.h);
      control = meanOf(B.control);
      if (G.green){
        readInto(G.green, B.green);
        green = meanOf(B.green);
        greenRGB = rgbOf(B.green);
      }
      err = g.getError();
    } catch (e) { err = -1; }
    state.replaying--;
    if (err) state.glErrors++;
    var v = state.video;
    return {
      t: now(), ms: now() - t0,
      vt: v ? v.currentTime : null,
      mediaTime: meta ? meta.mediaTime : null,
      bands: bands, control: control, green: green, greenRGB: greenRGB, glErr: err
    };
  }

  // ------------------------------------------------------------- geometry
  function largestOutside(slot, movie){
    var cands = [
      {x: slot.x, y: slot.y, w: slot.w, h: movie.y - slot.y},
      {x: slot.x, y: movie.y + movie.h, w: slot.w, h: slot.y + slot.h - (movie.y + movie.h)},
      {x: slot.x, y: slot.y, w: movie.x - slot.x, h: slot.h},
      {x: movie.x + movie.w, y: slot.y, w: slot.x + slot.w - (movie.x + movie.w), h: slot.h}
    ];
    var best = null;
    for (var i = 0; i < cands.length; i++){
      var c = cands[i];
      if (c.w <= 2 * GREEN_INSET_PX || c.h <= 2 * GREEN_INSET_PX) continue;
      if (!best || c.w * c.h > best.w * best.h) best = c;
    }
    if (!best) return null;
    return {x: best.x + GREEN_INSET_PX, y: best.y + GREEN_INSET_PX,
            w: best.w - 2 * GREEN_INSET_PX, h: best.h - 2 * GREEN_INSET_PX};
  }

  function greenAuthored(){
    var movie = rectOf(ENTRY.slotRects[MOVIE_SLOT]);
    for (var i = ENTRY.slotRects.length - 1; i > MOVIE_SLOT; i--){
      var s = rectOf(ENTRY.slotRects[i]);
      var overlaps = s.x < movie.x + movie.w && movie.x < s.x + s.w &&
        s.y < movie.y + movie.h && movie.y < s.y + s.h;
      if (!overlaps) continue;
      return largestOutside(s, movie);
    }
    return null;
  }

  function buildGeometry(){
    var band = toBuffer(ENTRY.instanceRect);
    var control = toBuffer({x: CONTROL_INSET_PX, y: CONTROL_INSET_PX, w: CONTROL_PATCH_PX, h: CONTROL_PATCH_PX});
    var ga = greenAuthored();
    state.geometry = {band: band, control: control, green: ga ? toBuffer(ga) : null, greenAuthored: ga};
    state.buffers = {
      band: new Uint8Array(band.w * band.h * 4),
      control: new Uint8Array(control.w * control.h * 4),
      green: ga ? new Uint8Array(state.geometry.green.w * state.geometry.green.h * 4) : null
    };
  }

  // ------------------------------------------------------------ opacity proofs
  var COUNT_REASON = 'count';

  function provenOr(slot, reason, ok){
    if (ok && API.debugForceFail !== reason) return true;
    unproven(slot, reason);
    return false;
  }

  function unproven(slot, reason){
    if (state.unproven.some(function(u){ return u.slot === slot && u.reason === reason; })) return;
    state.unproven.push({slot: slot, reason: reason});
    delete state.overrides[slot];
    event('glreplay-opacity-unproven', {slot: slot, reason: reason});
  }

  function drawIndices(){
    var out = [];
    for (var i = 0; i < state.frame.length; i++){
      var m = state.frame[i].m;
      if (m === 'drawArrays' || m === 'drawElements') out.push(i);
    }
    return out;
  }

  function programBefore(index){
    for (var i = index - 1; i >= 0; i--){
      if (state.frame[i].m === 'useProgram') return state.frame[i].a[0];
    }
    return null;
  }

  function samplerTextureAt(index, unit){
    var active = 0, bound = {};
    var g = state.gl;
    for (var i = 0; i < index; i++){
      var e = state.frame[i];
      if (e.m === 'activeTexture') active = e.a[0] - g.TEXTURE0;
      else if (e.m === 'bindTexture' && e.a[0] === g.TEXTURE_2D) bound[active] = e.a[1];
    }
    return bound[unit] || null;
  }

  function uniformNames(prog){
    var g = state.gl, names = {};
    try {
      var n = g.getProgramParameter(prog, g.ACTIVE_UNIFORMS);
      for (var i = 0; i < n; i++){
        var info = g.getActiveUniform(prog, i);
        if (info) names[String(info.name).replace(/\[0\]$/, '')] = true;
      }
    } catch (e) {}
    return names;
  }

  function decodeMvp(m, texW, texH){
    var c = state.canvas;
    function project(x, y){
      var cw = m[3] * x + m[7] * y + m[15];
      if (!cw) return null;
      var ndcX = (m[0] * x + m[4] * y + m[12]) / cw;
      var ndcY = (m[1] * x + m[5] * y + m[13]) / cw;
      return {x: (ndcX + 1) / 2 * c.width, y: c.height - (ndcY + 1) / 2 * c.height};
    }
    var p0 = project(0, 0), p1 = project(texW, texH);
    if (!p0 || !p1) return null;
    return {x: Math.min(p0.x, p1.x), y: Math.min(p0.y, p1.y),
            w: Math.abs(p1.x - p0.x), h: Math.abs(p1.y - p0.y)};
  }

  function changedRegion(a, b, roi, inner){
    var box = null, inside = 0, insideTotal = 0;
    for (var y = 0; y < roi.h; y += ABLATION_GRID_PX){
      for (var x = 0; x < roi.w; x += ABLATION_GRID_PX){
        var ax = roi.x + x, ay = roi.y + y;
        var within = ax >= inner.x && ax < inner.x + inner.w && ay >= inner.y && ay < inner.y + inner.h;
        if (within) insideTotal++;
        var i = (y * roi.w + x) * 4;
        if (a[i] === b[i] && a[i + 1] === b[i + 1] && a[i + 2] === b[i + 2]) continue;
        if (within) inside++;
        if (!box) box = {x0: ax, y0: ay, x1: ax, y1: ay};
        else {
          if (ax < box.x0) box.x0 = ax;
          if (ay < box.y0) box.y0 = ay;
          if (ax > box.x1) box.x1 = ax;
          if (ay > box.y1) box.y1 = ay;
        }
      }
    }
    return {box: box, coverage: insideTotal ? inside / insideTotal : 0};
  }

  function proveOpacity(){
    var g = state.gl;
    var draws = drawIndices();
    var slots = ENTRY.slotSizes.length;
    var wanted = {};
    ENTRY.opacityOverrides.forEach(function(o){ wanted[o.slot] = o.opacity; });
    var sizeCount = {};
    ENTRY.slotSizes.forEach(function(s){ var k = s[0] + 'x' + s[1]; sizeCount[k] = (sizeCount[k] || 0) + 1; });

    if (API.debugForceFail === COUNT_REASON || draws.length !== slots){
      for (var s0 = 0; s0 < slots; s0++) if (wanted[s0] != null) unproven(s0, COUNT_REASON);
      return;
    }
    var complete = [];
    for (var j = 0; j < draws.length; j++){
      var program = programBefore(draws[j]);
      state.programs[j] = program;
      var names = program ? uniformNames(program) : {};
      var locations = {};
      if (program){
        UNIFORM_NAMES.forEach(function(n){
          try { locations[n] = g.getUniformLocation(program, n); } catch (e) { locations[n] = null; }
        });
      }
      state.locations[j] = locations;
      complete[j] = !!program && UNIFORM_NAMES.every(function(n){ return names[n] && locations[n]; });
    }
    replayFrame({capture: true});

    for (var i = 0; i < draws.length; i++){
      var prog = state.programs[i], loc = state.locations[i];
      if (wanted[i] == null) continue;
      if (!provenOr(i, 'uniforms', complete[i])) continue;

      var mix = null;
      try { mix = g.getUniform(prog, loc.mixFactor); } catch (e) { mix = null; }
      if (!provenOr(i, 'mixfactor', mix === 1 || mix === 0)) continue;

      var sizeKey = ENTRY.slotSizes[i][0] + 'x' + ENTRY.slotSizes[i][1];
      var unit = null;
      try { unit = g.getUniform(prog, mix === 1 ? loc.Texture : loc.Texture2); } catch (e) { unit = null; }
      var tex = unit == null ? null : samplerTextureAt(draws[i], unit);
      var up = tex ? lastUpload.get(tex) : null;
      if (!provenOr(i, 'size', sizeCount[sizeKey] === 1 && !!up &&
          up.w === ENTRY.slotSizes[i][0] && up.h === ENTRY.slotSizes[i][1])) continue;

      var mvp = null;
      try { mvp = g.getUniform(prog, loc.MVPMatrix); } catch (e) { mvp = null; }
      var decoded = mvp && mvp.length === 16 ? decodeMvp(mvp, ENTRY.slotSizes[i][0], ENTRY.slotSizes[i][1]) : null;
      var want = rectOf(ENTRY.slotRects[i]);
      var ok = decoded && Math.abs(decoded.x - want.x) <= MVP_TOLERANCE_PX &&
        Math.abs(decoded.y - want.y) <= MVP_TOLERANCE_PX &&
        Math.abs(decoded.w - want.w) <= MVP_TOLERANCE_PX &&
        Math.abs(decoded.h - want.h) <= MVP_TOLERANCE_PX;
      if (!provenOr(i, 'mvp', ok)) continue;

      if (!provenOr(i, 'rest-opacity', state.restOpacity[i] === 1)) continue;

      var roi = toBuffer({x: want.x - ABLATION_DILATION_PX, y: want.y - ABLATION_DILATION_PX,
                          w: want.w + 2 * ABLATION_DILATION_PX, h: want.h + 2 * ABLATION_DILATION_PX});
      var clean = new Uint8Array(roi.w * roi.h * 4);
      var ablated = new Uint8Array(roi.w * roi.h * 4);
      var zeroed = new Uint8Array(roi.w * roi.h * 4);
      state.replaying++;
      try {
        replayFrame({rest: true}); readInto(roi, clean);
        replayFrame({skip: i}); readInto(roi, ablated);
        replayFrame({only: i, value: 0}); readInto(roi, zeroed);
      } catch (e) {} finally { replayFrame({rest: true}); }
      state.replaying--;
      var wantGl = toBuffer(want);
      var region = changedRegion(clean, ablated, roi, wantGl);
      var box = region.box;
      var tol = ABLATION_GRID_PX + 2;
      var fits = !!box && Math.abs(box.x0 - wantGl.x) <= tol && Math.abs(box.y0 - wantGl.y) <= tol &&
        Math.abs(box.x1 - (wantGl.x + wantGl.w)) <= tol + ABLATION_GRID_PX &&
        Math.abs(box.y1 - (wantGl.y + wantGl.h)) <= tol + ABLATION_GRID_PX;
      if (!provenOr(i, 'ablation', fits && region.coverage >= ABLATION_COVERAGE_MIN)) continue;

      var identical = true;
      for (var p = 0; p < zeroed.length; p++) if (zeroed[p] !== ablated[p]){ identical = false; break; }
      if (!provenOr(i, 'identity', identical)) continue;

      state.overrides[i] = wanted[i];
    }
    replayFrame({rest: true});
    state.opacityAfterProofs = state.programs.map(function(prog, slot){
      var loc = state.locations[slot];
      if (!prog || !loc || !loc.Opacity) return null;
      try { return g.getUniform(prog, loc.Opacity); } catch (e) { return null; }
    });
  }

  // ------------------------------------------------------------- marker swap
  function markerSwap(){
    var bandsFor = function(r, g2, b){
      paintTexture(state.posterTex, state.posterUpload, r, g2, b);
      replayFrame();
      return sampleOnce(null).bands;
    };
    var dark = bandsFor(0, 0, 0);
    var light = bandsFor(255, 255, 255);
    restorePoster();
    replayFrame();
    var mask = [], occ = 0;
    for (var i = 0; i < dark.length; i++){
      var o = Math.abs(dark[i] - light[i]) <= MARKER_BAND_EPSILON;
      mask.push(o ? 1 : 0);
      if (o) occ++;
    }
    state.mask = mask;
    state.occluded = occ;
    return {dark: dark, light: light};
  }

  // ------------------------------------------------------------- stand-down
  function standDown(reason, detail){
    if (state.down) return;
    state.down = true;
    var started = now();
    state.phase = 'STANDDOWN';
    API.state = 'STANDDOWN';
    state.recording = false;
    state.hot = false;
    state.collectors.forEach(function(c){ c.resolve(c.out); });
    state.collectors = [];
    var g = state.gl;
    var lost = false;
    try { lost = !g || (typeof g.isContextLost === 'function' && g.isContextLost()); } catch (e) { lost = true; }
    var written = [], writtenPrograms = [];
    for (var i = 0; i < state.programs.length; i++){
      if (state.overrides[i] == null || !state.programs[i]) continue;
      if (writtenPrograms.indexOf(state.programs[i]) >= 0) continue;
      var last = i;
      for (var n = i + 1; n < state.programs.length; n++) if (state.programs[n] === state.programs[i]) last = n;
      var loc = state.locations[last];
      if (!loc || !loc.Opacity || state.restOpacity[last] == null) continue;
      writtenPrograms.push(state.programs[i]);
      written.push(last);
    }
    var failed = false;
    if (!lost && written.length){
      state.replaying++;
      try {
        var prev = g.getParameter(g.CURRENT_PROGRAM);
        for (var k = 0; k < written.length; k++){
          var slot = written[k];
          g.useProgram(state.programs[slot]);
          g.uniform1f(state.locations[slot].Opacity, state.restOpacity[slot]);
        }
        g.useProgram(prev);
        if (g.getError() !== 0) failed = true;
      } catch (e) { failed = true; }
      state.replaying--;
    }
    if (!lost) restorePoster();
    if (failed || API.debugForceFail === WRITEBACK_FAILED) API.standDowns.push(WRITEBACK_FAILED);
    API.standDowns.push(reason);
    if (state.pausedByUs && state.video){
      try {
        if (state.seam) state.seam.setKeepWarm(state.video, true);
        var p = state.video.play();
        if (p && p.catch) p.catch(function(){});
      } catch (e) {}
      state.pausedByUs = false;
    }
    try { delete window.__OBED_GL_ORACLE__; } catch (e) {}
    var released = null;
    if (state.seam){
      try { released = state.seam.release(ENTRY.movieKey, {rect: rectOf(ENTRY.slotRects[MOVIE_SLOT])}); }
      catch (e) { released = {ok: false, reason: String(e)}; }
    }
    var payload = Object.assign({released: released, writebackFailed: failed,
      completedMs: now() - started}, detail || {});
    payload.reason = reason;
    event(reason === CANVAS_REMOVED ? 'glreplay-handoff' : 'glreplay-standdown', payload);
    if (state.observer){ try { state.observer.disconnect(); } catch (e) {} }
    state.phase = 'RETIRED';
    API.state = 'RETIRED';
  }

  // ------------------------------------------------------------------- LIVE
  function publishHandle(){
    window.__OBED_GL_ORACLE__ = {
      gl: state.gl,
      canvas: state.canvas,
      video: state.video,
      epoch: state.epoch,
      sceneId: state.frozenSceneId,
      instanceId: ENTRY.instanceId,
      rect: {x: ENTRY.instanceRect.x, y: ENTRY.instanceRect.y, w: ENTRY.instanceRect.w, h: ENTRY.instanceRect.h},
      canvasId: state.canvas.id,
      sample: function(n){ return collect(n); },
      markerBands: function(){
        var m = markerSwap();
        return Promise.resolve({dark: m.dark, light: m.light, epoch: state.epoch});
      },
      pause: function(){
        try { if (state.seam) state.seam.setKeepWarm(state.video, false); } catch (e) {}
        state.paused = true;
        state.pausedByUs = true;
        try { state.video.pause(); } catch (e) {}
        startPausedLoop();
        return Promise.resolve(true);
      },
      resume: function(){
        var p = null;
        try { p = state.video.play(); } catch (e) {}
        try { if (state.seam) state.seam.setKeepWarm(state.video, true); } catch (e) {}
        state.paused = false;
        state.pausedByUs = false;
        var done = function(){ startLiveLoop(); return true; };
        return (p && p.then) ? p.then(done, done) : Promise.resolve(done());
      }
    };
    event('glreplay-live', {canvasId: state.canvas.id, epoch: state.epoch, frameLen: state.frameLen});
  }

  function collect(n){
    return new Promise(function(resolve){
      state.collectors.push({need: n, out: [], resolve: resolve});
    });
  }

  function feedCollectors(sample){
    var keep = [];
    for (var i = 0; i < state.collectors.length; i++){
      var c = state.collectors[i];
      c.out.push(sample);
      if (c.out.length >= c.need) c.resolve(c.out);
      else keep.push(c);
    }
    state.collectors = keep;
  }

  function guards(){
    var c = state.canvas, g = state.gl;
    var stage = document.getElementById('stage');
    if (API.debugForceFail === CANVAS_REMOVED || !c || !c.isConnected || !stage || !stage.contains(c)) return CANVAS_REMOVED;
    if (API.debugForceFail === CONTEXT_LOST || (typeof g.isContextLost === 'function' && g.isContextLost())) return CONTEXT_LOST;
    if (API.debugForceFail === FRAME_LENGTH_CHANGED || state.frame.length !== state.frameLen) return FRAME_LENGTH_CHANGED;
    return null;
  }

  function tickOnce(meta){
    if (state.down) return false;
    var why = guards();
    if (why){ standDown(why, null); return false; }
    if (!state.paused) perLiveUpload();
    replayFrame();
    var sample = sampleOnce(meta);
    state.iter++;
    if (!assertOr('glError', !sample.glErr, {glErr: sample.glErr})) return false;
    feedCollectors(sample);
    return true;
  }

  function perLiveUpload(){
    if (!state.video || state.video.readyState < 2) return;
    uploadInto(state.posterTex, state.posterUpload, state.video);
    state.uploads++;
  }

  function startLiveLoop(){
    if (state.down || state.paused) return;
    var gen = ++state.loopGen;
    var request = function(step){
      try { state.video.requestVideoFrameCallback(step); return true; } catch (e) { return false; }
    };
    var step = function(t, meta){
      if (state.down || state.paused || gen !== state.loopGen) return;
      if (!tickOnce(meta)) return;
      requireVideoFrameCallback(request(step));
    };
    requireVideoFrameCallback(request(step));
  }

  function startPausedLoop(){
    var gen = ++state.loopGen;
    var step = function(){
      if (state.down || !state.paused || gen !== state.loopGen) return;
      if (!tickOnce(null)) return;
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // ---------------------------------------------------------------- ARM-POST
  function isDelimited(seg){
    return !!seg && seg.length > 2 && seg[0].m === 'clearColor' && seg[1].m === 'clear';
  }

  function armPost(){
    state.recording = false;
    var seg = state.segment;
    if (!isDelimited(seg) && isDelimited(state.retained) &&
        state.tick - state.retainedTick <= SETTLE_QUIET_TICKS){
      seg = state.retained;
      event('glreplay-retained-frame', {tick: state.retainedTick, len: seg.length});
    }
    if (!requireDelimitedFrame(isDelimited(seg), {len: seg.length})) return;
    state.frame = seg;
    state.frameLen = seg.length;

    if (!assertOr('posterAmbiguous', !state.posterAmbiguous && !!state.posterTex, null)) return;
    state.poster = posterOf(state.posterTex, {w: ENTRY.slotSizes[MOVIE_SLOT][0], h: ENTRY.slotSizes[MOVIE_SLOT][1],
      intFmt: state.posterUpload.intFmt, extFmt: state.posterUpload.extFmt, type: state.posterUpload.type});
    if (!assertOr('posterUnreadable', state.poster.complete, null)) return;

    buildGeometry();
    markerSwap();
    if (state.down) return;
    var bandCount = BAND_COLS * BAND_ROWS;
    if (!assertOr('occlusionTooHigh', state.occluded <= OCCLUSION_MAX_FRACTION * bandCount,
        {occluded: state.occluded, bands: bandCount})) return;
    proveOpacity();
    if (state.down) return;

    state.epoch++;
    state.phase = 'LIVE';
    API.state = 'LIVE';
    state.hot = true;
    if (!tickOnce(null)) return;
    publishHandle();
    startLiveLoop();
  }

  // ----------------------------------------------------------------- ARM-PRE
  function armObserver(){
    try {
      var observer = new MutationObserver(function(records){
        var at = now();
        if (!state.canvas) return;
        for (var i = 0; i < records.length; i++){
          var removed = records[i].removedNodes;
          for (var j = 0; j < removed.length; j++){
            var n = removed[j];
            if (n.nodeType !== 1) continue;
            if (n === state.canvas || (n.contains && n.contains(state.canvas))){
              state.mutationScanMs = now() - at;
              standDown(CANVAS_REMOVED, null);
              return;
            }
          }
        }
      });
      observer.observe(document.documentElement, {childList: true, subtree: true});
      state.observer = observer;
      return true;
    } catch (e) { return false; }
  }

  // Polled every ARM-PRE tick: a requirement that appears one frame late is not a
  // stand-down until the armed context exists (plan §2.2).
  function preflight(){
    var seam = window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.glReplay;
    if (seam && seam.version !== SEAM_VERSION) seam = null;
    if (seam) state.seam = seam;
    state.arming = true;
    var ok = assertOr('runtimeSeamAbsent', !!seam, null) &&
      assertOr('observerNotArmed', !!state.observer || armObserver(), null) &&
      assertOr('settleSignalAbsent', !!liveSnapshot() || state.segment.length > 0, null) &&
      requireVideoFrameCallback(typeof HTMLVideoElement !== 'undefined' &&
        typeof HTMLVideoElement.prototype.requestVideoFrameCallback === 'function');
    state.arming = false;
    if (ok) state.pending = null;
    return ok;
  }

  function onContextCreated(gl, canvas){
    if (state.gl || state.phase !== 'ARM-PRE' || state.down) return;
    if (!CANVAS_ID_RE.test(String(canvas.id || ''))) return;
    if (!assertOr('canvasShape', canvas.isConnected &&
        canvas.width === INFO.authoredWidth && canvas.height === INFO.authoredHeight,
        {id: canvas.id, w: canvas.width, h: canvas.height})) return;
    state.gl = gl;
    state.canvas = canvas;
    if (!preflight()) return;
    state.recording = true;
    state.hot = true;
    event('glreplay-arm', {canvasId: canvas.id, atScene: ENTRY.atScene});
  }

  function poll(){
    if (state.down) return;
    state.tick++;
    var hash = currentHashNum();
    if (state.phase === 'IDLE'){
      if (hash === ENTRY.atScene - 1){
        state.phase = 'ARM-PRE';
        API.state = 'ARM-PRE';
      }
    }
    if (state.phase === 'ARM-PRE'){
      preflight();
      var snap = liveSnapshot();
      if (state.gl && state.segment.length && state.readyAt == null &&
          snap && snap.ready === true &&
          state.lastPlayerTick >= 0 && state.tick - state.lastPlayerTick >= SETTLE_QUIET_TICKS){
        state.readyAt = now();
        state.settleGapMs = state.lastClearAt == null ? null : state.readyAt - state.lastClearAt;
        if (!assertOr('sceneMismatch', snap.sceneId === ENTRY.atScene - 1,
            {sceneId: snap.sceneId, atScene: ENTRY.atScene})) return;
        state.frozenSceneId = snap.sceneId;
        state.phase = 'ARM-POST';
        API.state = 'ARM-POST';
        armPost();
      }
    } else if (state.phase === 'LIVE' && state.settleToHashMs == null && hash === ENTRY.atScene && state.readyAt != null){
      state.settleToHashMs = now() - state.readyAt;
    }
    requestAnimationFrame(poll);
  }

  // -------------------------------------------------------------- install
  if (!refuseInstall('planUnreadable', !!ENTRY)) return;
  if (!refuseInstall('glReplayUnavailable', !!window.WebGLRenderingContext)) return;

  var origGetContext = HTMLCanvasElement.prototype.getContext;
  if (!origGetContext.__obedGlReplay){
    var wrappedGetContext = function(type){
      var ctx = origGetContext.apply(this, arguments);
      if (ctx && (type === 'webgl' || type === 'webgl2' || type === 'experimental-webgl')){
        try { onContextCreated(ctx, this); } catch (e) {}
      }
      return ctx;
    };
    wrappedGetContext.__obedGlReplay = 1;
    HTMLCanvasElement.prototype.getContext = wrappedGetContext;
  }
  wrapContexts();

  armObserver();
  requestAnimationFrame(poll);
})();
""".strip()


def js_sha256() -> str:
    return hashlib.sha256(GL_REPLAY_JS.encode()).hexdigest()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_gl_replay_entry(runtime_plan: Any) -> dict[str, Any] | None:
    """The one `glReplay` boundary of a runtime plan, or None when the plan carries
    none, carries more than one, or the entry fails any shape check of plan §2.0/§2.8.
    Mirrors the in-page re-validation, which fails closed to `planUnreadable`."""
    if not isinstance(runtime_plan, dict):
        return None
    boundaries = runtime_plan.get("boundaries")
    movies = runtime_plan.get("movies")
    if not isinstance(boundaries, list) or not isinstance(movies, dict):
        return None
    found = [b for b in boundaries if isinstance(b, dict) and b.get("action") == "glReplay"]
    if len(found) != 1:
        return None
    entry = found[0]
    if entry.get("fallback") != "retire":
        return None
    if not _is_int(entry.get("atScene")):
        return None
    key = entry.get("movieKey")
    if not isinstance(key, str) or key not in movies:
        return None

    sizes, rects = entry.get("slotSizes"), entry.get("slotRects")
    if not isinstance(sizes, list) or not sizes:
        return None
    if not isinstance(rects, list) or len(rects) != len(sizes):
        return None
    for size, rect in zip(sizes, rects):
        if not isinstance(size, list) or len(size) != 2:
            return None
        if not all(_is_int(v) and v > 0 for v in size):
            return None
        if not isinstance(rect, list) or len(rect) != 4 or not all(_finite(v) for v in rect):
            return None
        if rect[2] <= 0 or rect[3] <= 0:
            return None

    overrides = entry.get("opacityOverrides")
    if not isinstance(overrides, list):
        return None
    for override in overrides:
        if not isinstance(override, dict):
            return None
        slot = override.get("slot")
        if not _is_int(slot) or not 0 <= slot < len(sizes):
            return None
        opacity = override.get("opacity")
        if not _finite(opacity) or not 0 < opacity < 1:
            return None
        if override.get("texW") != sizes[slot][0] or override.get("texH") != sizes[slot][1]:
            return None

    instance_id = entry.get("instanceId")
    if not isinstance(instance_id, str) or "#" not in instance_id:
        return None
    instance_rect = entry.get("instanceRect")
    if not isinstance(instance_rect, dict) or set(instance_rect) != {"x", "y", "w", "h"}:
        return None
    if not all(_finite(v) for v in instance_rect.values()):
        return None
    if instance_rect["w"] <= 0 or instance_rect["h"] <= 0:
        return None
    slot = entry.get("movieSlot")
    if not _is_int(slot) or not 0 <= slot < len(sizes):
        return None
    return entry


def gl_replay_script(runtime_plan: Any) -> str:
    """The `<script>` tag the host injects after the continuity core, or `""` when the
    plan carries no usable `glReplay` boundary -- the `off` path injects and evaluates
    nothing."""
    if validate_gl_replay_entry(runtime_plan) is None:
        return ""
    body = re.sub(r"</(?=script)", "<\\\\/", GL_REPLAY_JS, flags=re.IGNORECASE)
    return f'<script id="obed-gl-replay">{body}</script>\n'
