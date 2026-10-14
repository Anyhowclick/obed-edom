"""Magic Move texture-feed runtime for carried movie decoders.

The module is injected after the continuity core and reads its bindings from
``window.__OBED_CONTINUITY__``.  It owns a separate version and SHA so changes
do not move the continuity-core pin.
"""

from __future__ import annotations

import hashlib
import re

MM_FEED_VERSION = 1

MM_FEED_JS = r"""
(function(){
  'use strict';
  if (typeof window === 'undefined' || window.__OBED_MM_FEED__) return;

  var CONTINUOUS = __OBED_MM_FEED_CONTINUOUS__;
  var ONCE = __OBED_MM_FEED_ONCE__;
  var CANVAS_ID_RE = /^\d+-canvas$/;
  var PLAN = window.__OBED_CONTINUITY__;
  if ((!CONTINUOUS && !ONCE) || !PLAN || !Array.isArray(PLAN.boundaries)) return;

  var records = {};
  var contexts = new WeakMap();
  var warmContext = null;

  function finiteInt(value){
    return typeof value === 'number' && isFinite(value) && value === Math.floor(value);
  }

  function validTextureBinding(value){
    return !!value && finiteInt(value.upload) && value.upload > 0 &&
      Array.isArray(value.size) && value.size.length === 2 &&
      finiteInt(value.size[0]) && value.size[0] > 0 &&
      finiteInt(value.size[1]) && value.size[1] > 0;
  }

  function validFeed(feed){
    return !!feed && finiteInt(feed.draw) && feed.draw > 0 &&
      finiteInt(feed.drawCount) && feed.drawCount >= feed.draw &&
      validTextureBinding(feed.from) &&
      (feed.to === null || validTextureBinding(feed.to)) &&
      (!feed.to || feed.to.upload !== feed.from.upload);
  }

  function publicEntry(mode){
    return {
      mode: mode,
      state: 'armed',
      reason: null,
      hold: null,
      framesFed: 0,
      maxInterFeedGapMs: 0,
      p95Ms: 0
    };
  }

  function makeRecord(boundary){
    var mode = CONTINUOUS ? 'continuous' : 'once';
    return {
      boundary: boundary,
      binding: boundary.feed,
      public: publicEntry(mode),
      valid: validFeed(boundary.feed),
      armed: false,
      claimed: false,
      onceRequested: false,
      onceDone: false,
      textures: null,
      lastFeedAt: null,
      gaps: [],
      wasIdle: false,
      departed: false,
      stoodDownThisIdle: false,
      wrapped: false
    };
  }

  PLAN.boundaries.forEach(function(boundary){
    if (!boundary || boundary.underArtwork !== true || !boundary.feed ||
        !finiteInt(boundary.atScene) || boundary.atScene < 1 ||
        !boundary.src || typeof boundary.src.objectId !== 'string' || !boundary.src.objectId ||
        records[boundary.src.objectId]) return;
    records[boundary.src.objectId] = makeRecord(boundary);
  });

  var entries = {};
  Object.keys(records).forEach(function(objectId){ entries[objectId] = records[objectId].public; });
  if (!Object.keys(records).length) return;

  function now(){
    return typeof performance !== 'undefined' && performance && typeof performance.now === 'function'
      ? performance.now() : Date.now();
  }

  function currentScene(){
    var match = /^#?(\d+)/.exec(String(location.hash || ''));
    return match ? parseInt(match[1], 10) : null;
  }

  function snapshot(){
    try { return window.__obedLive && typeof window.__obedLive.snapshot === 'function'
      ? window.__obedLive.snapshot() : null; }
    catch (e) { return null; }
  }

  function idleAtSource(record){
    if (currentScene() !== record.boundary.atScene - 1) return false;
    var value = snapshot();
    if (!value) return false;
    if (value.busy === true) return false;
    if (typeof value.playerState !== 'string' || value.playerState.indexOf('IdleAt') !== 0) return false;
    return value.sceneId == null || value.sceneId === record.boundary.atScene - 1;
  }

  function feedSeam(){
    var preserve = window.__OBED_P2_PRESERVE__;
    var feed = preserve && preserve.feed;
    return feed && feed.version === 1 ? feed : null;
  }

  function decoderFor(objectId){
    var seam = feedSeam();
    try { return seam && typeof seam.decoderFor === 'function' ? seam.decoderFor(objectId) : null; }
    catch (e) { return null; }
  }

  function percentile95(values){
    if (!values.length) return 0;
    var ordered = values.slice().sort(function(a, b){ return a - b; });
    return ordered[Math.max(0, Math.ceil(ordered.length * 0.95) - 1)];
  }

  function noteFeed(record){
    var at = now();
    if (record.lastFeedAt !== null) record.gaps.push(at - record.lastFeedAt);
    record.lastFeedAt = at;
    record.public.framesFed += 1;
    record.public.maxInterFeedGapMs = record.gaps.length ? Math.max.apply(null, record.gaps) : 0;
    record.public.p95Ms = percentile95(record.gaps);
  }

  function standDown(record, reason, hold){
    if (record.public.state === 'stoodDown') return;
    record.armed = false;
    record.stoodDownThisIdle = true;
    record.public.state = 'stoodDown';
    record.public.reason = reason;
    record.public.hold = hold || (record.public.framesFed ? 'unavailable' : 'baked');
    var seam = feedSeam();
    try {
      if (seam && typeof seam.onStandDown === 'function') seam.onStandDown(record.boundary.src.objectId, reason);
    } catch (e) {}
  }

  function warm(decoder){
    if (!decoder || decoder.readyState < 2 || typeof document === 'undefined') return;
    try {
      if (!warmContext){
        var canvas = document.createElement('canvas');
        canvas.width = 1;
        canvas.height = 1;
        warmContext = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
      }
      var gl = warmContext;
      if (!gl) return;
      var texture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, decoder);
      gl.deleteTexture(texture);
    } catch (e) {}
  }

  function reset(record){
    var mode = CONTINUOUS ? 'continuous' : 'once';
    record.public.mode = mode;
    record.public.state = 'armed';
    record.public.reason = null;
    record.public.hold = null;
    record.public.framesFed = 0;
    record.public.maxInterFeedGapMs = 0;
    record.public.p95Ms = 0;
    record.armed = false;
    record.claimed = false;
    record.onceRequested = false;
    record.onceDone = false;
    record.textures = null;
    record.lastFeedAt = null;
    record.gaps = [];
    record.stoodDownThisIdle = false;
    record.wrapped = false;
  }

  function arm(record){
    if (record.armed || record.stoodDownThisIdle) return;
    if (!record.valid){
      standDown(record, 'binding-invalid', 'baked');
      return;
    }
    var decoder = decoderFor(record.boundary.src.objectId);
    warm(decoder);
    record.armed = true;
    if (CONTINUOUS){
      var seam = feedSeam();
      var claimed = false;
      try {
        claimed = !!decoder && !!seam && typeof seam.claim === 'function' &&
          seam.claim(record.boundary.src.objectId) === true;
      } catch (e) { claimed = false; }
      if (claimed){
        record.claimed = true;
        record.public.mode = 'continuous';
      } else if (ONCE){
        record.public.mode = 'once';
      } else {
        standDown(record, 'claim-refused', 'baked');
      }
    }
  }

  function poll(){
    Object.keys(records).forEach(function(objectId){
      var record = records[objectId];
      var sourceScene = record.boundary.atScene - 1;
      if (record.wasIdle && currentScene() !== sourceScene) record.departed = true;
      var idle = idleAtSource(record);
      if (idle && record.departed){
        reset(record);
        record.departed = false;
      }
      if (idle){
        arm(record);
        record.wasIdle = true;
      }
    });
    requestAnimationFrame(poll);
  }

  function activeRecords(){
    var scene = currentScene();
    return Object.keys(records).map(function(key){ return records[key]; }).filter(function(record){
      return record.armed &&
        (record.boundary.atScene - 1 === scene ||
          record.boundary.atScene === scene && !record.wrapped) &&
        record.public.state !== 'stoodDown';
    });
  }

  function videoSource(value){
    if (!value) return false;
    if (typeof HTMLVideoElement !== 'undefined' && value instanceof HTMLVideoElement) return true;
    return typeof value.currentTime === 'number' && typeof value.readyState === 'number';
  }

  function uploadInfo(gl, args){
    var source = args.length < 9 ? args[5] : null;
    var width = args.length >= 9 ? args[3] : source && (source.videoWidth || source.naturalWidth || source.width);
    var height = args.length >= 9 ? args[4] : source && (source.videoHeight || source.naturalHeight || source.height);
    return {
      source: source,
      width: width,
      height: height,
      internalFormat: args[2],
      format: args.length >= 9 ? args[6] : args[3],
      type: args.length >= 9 ? args[7] : args[4],
      flipY: !!gl.getParameter(gl.UNPACK_FLIP_Y_WEBGL),
      premultiply: !!gl.getParameter(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL)
    };
  }

  function sameSize(meta, binding){
    return !!meta && meta.ordinal === binding.upload &&
      meta.width === binding.size[0] && meta.height === binding.size[1];
  }

  function hasMixFactor(state){
    var values = state.programValues.get(state.program);
    return !!values && Object.prototype.hasOwnProperty.call(values, 'mixFactor');
  }

  function knowsMixFactor(state){
    var names = state.programNames.get(state.program);
    return !!names && names.mixFactor === true;
  }

  function bindingAtDraw(state, record){
    var gl = state.gl;
    var binding = record.binding;
    if (state.unit !== gl.TEXTURE0 || !state.program) return null;
    if (binding.to ? !hasMixFactor(state) : (hasMixFactor(state) || knowsMixFactor(state))) return null;
    var fromTexture = state.bindings.get(gl.TEXTURE0);
    var fromMeta = fromTexture && state.textureInfo.get(fromTexture);
    if (!fromTexture || !sameSize(fromMeta, binding.from)) return null;
    var out = [{unit: gl.TEXTURE0, texture: fromTexture, meta: fromMeta, binding: binding.from}];
    if (binding.to){
      var toTexture = state.bindings.get(gl.TEXTURE0 + 1);
      var toMeta = toTexture && state.textureInfo.get(toTexture);
      if (!toTexture || !sameSize(toMeta, binding.to)) return null;
      out.push({unit: gl.TEXTURE0 + 1, texture: toTexture, meta: toMeta, binding: binding.to});
    }
    return out;
  }

  function restoreCall(state, name, args){
    return state.original[name].apply(state.gl, args);
  }

  function uploadDecoder(state, record, targets, decoder){
    var gl = state.gl;
    var savedUnit = state.unit;
    var savedFlip = !!gl.getParameter(gl.UNPACK_FLIP_Y_WEBGL);
    var savedPremultiply = !!gl.getParameter(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL);
    var savedBindings = targets.map(function(target){
      return {unit: target.unit, texture: state.bindings.get(target.unit) || null};
    });
    var failed = false;
    state.internal += 1;
    try {
      var uploadTargets = record.binding.to ? [targets[0], targets[1]] : [targets[0]];
      uploadTargets.forEach(function(target){
        restoreCall(state, 'activeTexture', [target.unit]);
        restoreCall(state, 'bindTexture', [gl.TEXTURE_2D, target.texture]);
        restoreCall(state, 'pixelStorei', [gl.UNPACK_FLIP_Y_WEBGL, target.meta.flipY]);
        restoreCall(state, 'pixelStorei', [gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, target.meta.premultiply]);
        restoreCall(state, 'texImage2D', [gl.TEXTURE_2D, 0, target.meta.internalFormat,
          target.meta.format, target.meta.type, decoder]);
      });
    } catch (e) {
      failed = true;
    } finally {
      try {
        savedBindings.forEach(function(saved){
          restoreCall(state, 'activeTexture', [saved.unit]);
          restoreCall(state, 'bindTexture', [gl.TEXTURE_2D, saved.texture]);
        });
        restoreCall(state, 'pixelStorei', [gl.UNPACK_FLIP_Y_WEBGL, savedFlip]);
        restoreCall(state, 'pixelStorei', [gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, savedPremultiply]);
        restoreCall(state, 'activeTexture', [savedUnit]);
      } catch (e) {
        failed = true;
      }
      state.internal -= 1;
    }
    return !failed;
  }

  function textureConflict(state, record, targets){
    for (var i = 0; i < targets.length; i++){
      var owner = state.textureOwners.get(targets[i].texture);
      if (owner && owner !== record) return owner;
    }
    return null;
  }

  function feedAtDraw(state, record){
    var decoder = decoderFor(record.boundary.src.objectId);
    if (!decoder){
      standDown(record, 'decoder-mismatch', record.public.framesFed ? 'exact' : 'baked');
      return;
    }
    if (decoder.readyState < 2) return;
    state.eligible.add(record);
    if (record.textures){
      var currentTextures = [state.bindings.get(state.gl.TEXTURE0)];
      if (record.binding.to) currentTextures.push(state.bindings.get(state.gl.TEXTURE0 + 1));
      if (record.textures.length !== currentTextures.length || record.textures.some(function(texture, index){
        return texture !== currentTextures[index];
      })){
        standDown(record, 'identity-change', 'unavailable');
        return;
      }
    }
    var targets = bindingAtDraw(state, record);
    if (!targets){
      standDown(record, 'binding-mismatch', record.public.framesFed ? 'unavailable' : 'baked');
      return;
    }
    var conflict = textureConflict(state, record, targets);
    if (conflict){
      standDown(conflict, 'shared-texture', conflict.public.framesFed ? 'unavailable' : 'baked');
      standDown(record, 'shared-texture', record.public.framesFed ? 'unavailable' : 'baked');
      return;
    }
    if (!uploadDecoder(state, record, targets, decoder)){
      standDown(record, 'upload-failed', record.public.framesFed ? 'unavailable' : 'baked');
      return;
    }
    if (!record.textures) record.textures = targets.map(function(target){ return target.texture; });
    targets.forEach(function(target){ state.textureOwners.set(target.texture, record); });
    state.fed.add(record);
    noteFeed(record);
    if (record.public.mode === 'once'){
      record.onceDone = true;
      record.public.state = 'held';
      record.public.hold = 'exact';
    } else {
      record.public.state = 'fed';
    }
  }

  function finishFrame(state){
    state.active.forEach(function(record){
      if (record.public.state === 'stoodDown' || record.public.mode === 'once' && record.onceDone) return;
      var shouldFeed = record.public.mode === 'continuous' || record.onceRequested;
      if (shouldFeed && state.reached.has(record) && !state.fed.has(record)){
        standDown(record, 'no-feed', record.public.framesFed ? 'exact' : 'baked');
      }
    });
    var error = state.original.getError.apply(state.gl, []);
    if (error !== state.gl.NO_ERROR){
      state.active.forEach(function(record){
        if (record.public.state !== 'stoodDown') standDown(record, 'gl-error', record.public.framesFed ? 'unavailable' : 'baked');
      });
    }
  }

  function wrapContext(gl, canvas, active){
    if (contexts.has(gl)) return;
    var names = ['activeTexture', 'bindTexture', 'pixelStorei', 'texImage2D', 'useProgram',
      'getUniformLocation', 'uniform1f', 'uniform1fv', 'clear', 'drawArrays', 'drawElements', 'getError'];
    var original = {};
    for (var i = 0; i < names.length; i++){
      if (typeof gl[names[i]] !== 'function') return;
      original[names[i]] = gl[names[i]];
    }
    var state = {
      gl: gl,
      canvas: canvas,
      original: original,
      active: active,
      unit: gl.getParameter(gl.ACTIVE_TEXTURE),
      bindings: new Map(),
      textureInfo: new WeakMap(),
      textureOwners: new WeakMap(),
      program: gl.getParameter(gl.CURRENT_PROGRAM),
      locationNames: new Map(),
      programNames: new Map(),
      programValues: new Map(),
      regularUploads: 0,
      draws: 0,
      eligible: new Set(),
      reached: new Set(),
      fed: new Set(),
      frameOpen: false,
      internal: 0
    };
    contexts.set(gl, state);
    active.forEach(function(record){ record.wrapped = true; });

    gl.activeTexture = function(unit){
      if (!state.internal) state.unit = unit;
      return original.activeTexture.apply(gl, arguments);
    };
    gl.bindTexture = function(target, texture){
      if (!state.internal && target === gl.TEXTURE_2D) state.bindings.set(state.unit, texture);
      return original.bindTexture.apply(gl, arguments);
    };
    gl.pixelStorei = function(){ return original.pixelStorei.apply(gl, arguments); };
    gl.useProgram = function(program){
      if (!state.internal) state.program = program;
      return original.useProgram.apply(gl, arguments);
    };
    gl.getUniformLocation = function(program, name){
      var location = original.getUniformLocation.apply(gl, arguments);
      if (!state.internal && location !== null){
        state.locationNames.set(location, name);
        var known = state.programNames.get(program) || {};
        known[name] = true;
        state.programNames.set(program, known);
      }
      return location;
    };
    function uniform(name, args){
      if (!state.internal){
        var uniformName = state.locationNames.get(args[0]);
        if (uniformName && state.program){
          var values = state.programValues.get(state.program) || {};
          values[uniformName] = args[1];
          state.programValues.set(state.program, values);
        }
      }
      return original[name].apply(gl, args);
    }
    gl.uniform1f = function(){ return uniform('uniform1f', arguments); };
    gl.uniform1fv = function(){ return uniform('uniform1fv', arguments); };
    gl.texImage2D = function(){
      if (!state.internal){
        var info = uploadInfo(gl, arguments);
        var texture = state.bindings.get(state.unit);
        if (texture && !videoSource(info.source)){
          info.ordinal = ++state.regularUploads;
          state.textureInfo.set(texture, info);
        }
      }
      return original.texImage2D.apply(gl, arguments);
    };
    gl.clear = function(){
      if (state.frameOpen) finishFrame(state);
      state.draws = 0;
      state.eligible = new Set();
      state.reached = new Set();
      state.fed = new Set();
      state.frameOpen = true;
      return original.clear.apply(gl, arguments);
    };
    function draw(name, args){
      state.draws += 1;
      state.active.forEach(function(record){
        if (!record.armed || record.public.state === 'stoodDown' || record.binding.draw !== state.draws) return;
        var shouldFeed = record.public.mode === 'continuous' || record.onceRequested && !record.onceDone;
        if (!shouldFeed) return;
        var decoder = decoderFor(record.boundary.src.objectId);
        if (decoder && decoder.readyState >= 2) state.reached.add(record);
        feedAtDraw(state, record);
      });
      var result = original[name].apply(gl, args);
      var drawCount = state.active.reduce(function(value, record){
        return Math.max(value, record.binding.drawCount);
      }, 0);
      if (state.draws === drawCount){
        finishFrame(state);
        state.frameOpen = false;
      }
      return result;
    }
    gl.drawArrays = function(){ return draw('drawArrays', arguments); };
    gl.drawElements = function(){ return draw('drawElements', arguments); };
    try {
      canvas.addEventListener('webglcontextlost', function(){
        state.active.forEach(function(record){ standDown(record, 'context-lost', 'unavailable'); });
      }, false);
    } catch (e) {}
  }

  var api = {
    version: 1,
    once: function(objectId){
      var record = records[objectId];
      if (!ONCE || !record || !record.valid) return false;
      if (record.onceRequested) return true;
      if (record.public.mode === 'continuous' && record.claimed) return false;
      if (record.public.state === 'stoodDown'){
        record.armed = true;
        record.public.state = 'armed';
        record.public.reason = null;
        record.public.hold = null;
      }
      if (!record.armed) return false;
      record.public.mode = 'once';
      record.onceRequested = true;
      return true;
    },
    take: function(controller, scene){
      api.take.lastAt = now();
      api.take.lastScene = scene == null ? null : scene;
    },
    entries: entries
  };
  window.__OBED_MM_FEED__ = api;

  var originalGetContext = HTMLCanvasElement.prototype.getContext;
  var wrappedGetContext = function(type){
    var context = originalGetContext.apply(this, arguments);
    if (context && CANVAS_ID_RE.test(String(this.id || '')) &&
        (type === 'webgl' || type === 'webgl2' || type === 'experimental-webgl')){
      var active = activeRecords();
      if (active.length) wrapContext(context, this, active);
    }
    return context;
  };
  wrappedGetContext.__obedMmFeed = 1;
  HTMLCanvasElement.prototype.getContext = wrappedGetContext;

  poll();
})();
""".strip()


def js_sha256() -> str:
    return hashlib.sha256(MM_FEED_JS.encode()).hexdigest()


PINNED_MM_FEED_SHA256 = "f1fe0dd644359962c4c71cce46424ac3e24eb4ac42d1f9053a103d24463b81bf"


def mm_feed_script(*, continuous: bool, once: bool) -> str:
    """Return the feed module's script tag with the two availability flags embedded."""
    if not isinstance(continuous, bool) or not isinstance(once, bool):
        raise TypeError("continuous and once must be bool")
    body = MM_FEED_JS.replace("__OBED_MM_FEED_CONTINUOUS__", "true" if continuous else "false")
    body = body.replace("__OBED_MM_FEED_ONCE__", "true" if once else "false")
    body = re.sub(r"</(?=script)", "<\\\\/", body, flags=re.IGNORECASE)
    return f'<script id="obed-mm-feed">{body}</script>\n'
