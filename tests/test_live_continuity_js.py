"""Load-bearing tests for `src/obed_edom/live_continuity_js.py` (I0).

The P2 adversarial gate (`scripts/p2_recovery_html_adversarial.py`) is the
oracle for whether `PRESERVE_CORE_JS` actually behaves correctly against a
real Keynote HTML export — these tests only cover what a full gate run is too
slow/heavy to exercise on every change: the module's Python-level contract
(hash/version pinning, single copy of the bytes) and the fail-closed no-plan
guard, behaviourally, in a minimal Node sandbox (no browser, no fixture).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess

import pytest

from obed_edom import live_continuity_js


def test_continuity_version_is_pinned_int():
    assert live_continuity_js.CONTINUITY_VERSION == 3
    assert isinstance(live_continuity_js.CONTINUITY_VERSION, int)


def test_js_sha256_matches_pinned_bytes():
    expected = hashlib.sha256(live_continuity_js.PRESERVE_CORE_JS.encode()).hexdigest()
    assert live_continuity_js.js_sha256() == expected
    # Stable across repeated calls (no hidden mutable state feeding the hash).
    assert live_continuity_js.js_sha256() == live_continuity_js.js_sha256()


def test_p2_dissolve_live_reexports_the_same_object():
    """`PRESERVE_SCRIPT` must be the shared core, not a second copy of the bytes."""
    import importlib.util
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    for p in (repo / "src", repo / "scripts"):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    spec = importlib.util.spec_from_file_location(
        "p2_recovery_html_dissolve_live", repo / "scripts" / "p2_recovery_html_dissolve_live.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    assert mod.PRESERVE_SCRIPT is live_continuity_js.PRESERVE_CORE_JS


def _run_core_in_node(*, plan, fail_install=False, call_disable_after=False) -> dict:
    """Execute PRESERVE_CORE_JS in a minimal DOM-less sandbox and report what
    it installed. `plan` is JSON-serialisable or None (no plan injected)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the JS core")
    plan_js = "undefined" if plan is None else json.dumps(plan)
    harness = f"""
const events = [];
function el() {{
  return {{
    addEventListener() {{}}, removeEventListener() {{}}, querySelectorAll() {{ return []; }},
    style: {{ setProperty() {{}} }}, dataset: {{}}, getAttribute() {{ return null; }},
  }};
}}
const window = {{ __OBED_CONTINUITY__: {plan_js}, addEventListener() {{}}, removeEventListener() {{}} }};
const document = {{
  documentElement: el(), body: el(),
  getElementById() {{ return null; }},
  querySelectorAll() {{ return []; }},
  addEventListener() {{}},
}};
function HTMLVideoElement() {{}}
function HTMLMediaElement() {{}}
HTMLMediaElement.prototype = {{}};
HTMLVideoElement.prototype = Object.create(HTMLMediaElement.prototype);
const Element = {{ prototype: {{ removeAttribute() {{}} }} }};
const Document = {{ prototype: {{ createElement: el }} }};
const location = {{ hash: '' }};
const performance = {{ now() {{ return 0; }} }};
const MutationObserver = function() {{
  this.observe = function() {{ if ({str(fail_install).lower()}) throw new Error('install failed'); }};
}};
const requestAnimationFrame = function() {{}};
const setInterval = function() {{}};
const setTimeout = function() {{}};
let installThrew = null;
try {{
{live_continuity_js.PRESERVE_CORE_JS}
}} catch (e) {{
  installThrew = String(e && e.message || e);
}}
let disableThrew = null, disableReturned = null;
if ({str(call_disable_after).lower()}) {{
  try {{
    disableReturned = window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.disable();
  }} catch (e) {{
    disableThrew = String(e && e.message || e);
  }}
}}
console.log(JSON.stringify({{
  threw: installThrew, installed: !!window.__OBED_P2_PRESERVE__,
  ready: !!(window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.ready),
  disabled: !!(window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.disabled),
  disableThrew, disableReturned,
}}));
"""
    result = subprocess.run([node, "-e", harness], check=True, text=True, capture_output=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_no_plan_guard_leaves_page_untouched():
    """Fail-closed: with no `window.__OBED_CONTINUITY__`, the core must install
    nothing (never even reach the `__OBED_P2_PRESERVE__` idempotency object)."""
    out = _run_core_in_node(plan=None)
    assert out == {
        "threw": None, "installed": False, "ready": False, "disabled": False,
        "disableThrew": None, "disableReturned": None,
    }


def test_with_plan_installs_the_preserve_object():
    plan = {
        "movies": {"movie1": {"assetKeys": ["untitled.mov"], "footprint": {"x": 1, "y": 2, "w": 3, "h": 4}}},
        "boundaries": [{"atScene": 6, "action": "restart"}],
    }
    out = _run_core_in_node(plan=plan)
    assert out == {
        "threw": None, "installed": True, "ready": True, "disabled": False,
        "disableThrew": None, "disableReturned": None,
    }


def test_transparent_chrome_gated_by_plan_flag():
    """`forceTransparentChrome` must run only when the plan opts in (owner
    decision 2a: off for HDMI, on for alpha/attach and the P2 fixtures)."""
    js = live_continuity_js.PRESERVE_CORE_JS
    assert "if (OBED_PLAN.transparentBackground === true) {" in js
    call_idx = js.index("forceTransparentChrome();")
    gate_idx = js.index("if (OBED_PLAN.transparentBackground === true) {")
    assert gate_idx < call_idx


def test_preserve_core_js_source_declares_the_fail_closed_guard():
    """String-level guard check: the very first executable statements read the
    plan and bail before creating any state, regardless of runtime behaviour."""
    js = live_continuity_js.PRESERVE_CORE_JS
    guard_idx = js.index("window.__OBED_CONTINUITY__")
    preserve_idx = js.index("__OBED_P2_PRESERVE__ = {")
    assert guard_idx < preserve_idx
    assert "if (!OBED_PLAN) return;" in js


def test_partial_install_never_sets_ready():
    out = _run_core_in_node(plan={"movies": {}, "boundaries": []}, fail_install=True)
    assert out == {
        "threw": "install failed", "installed": True, "ready": False, "disabled": False,
        "disableThrew": None, "disableReturned": None,
    }


def test_disable_survives_a_partial_install():
    """Codex round 1, 1a: a core that throws midway (before `ready`) must
    still be `disable()`-able without a TDZ ReferenceError — `disabled` (and
    everything else `disable()` touches before its `try`) is hoisted above the
    `window.__OBED_P2_PRESERVE__` assignment."""
    out = _run_core_in_node(
        plan={"movies": {}, "boundaries": []}, fail_install=True, call_disable_after=True,
    )
    assert out["threw"] == "install failed"
    assert out["disableThrew"] is None
    assert out["disableReturned"] is True
    assert out["disabled"] is True
    assert out["ready"] is False


#: Default `stageMap()` fixture: s=1, origin (0,0) — numerically IDENTICAL to the
#: pre-I3 (unscaled) behaviour, so tests that don't care about scaling keep
#: their original expected numbers.
_IDENTITY_STAGE = {"ow": 1920, "oh": 1080, "s": 1, "ox": 0, "oy": 0}
#: s = 4/3, origin (0,0) — the measured HDMI 2560x1440-on-1920x1080 case.
_SCALED_STAGE = {"ow": 1920, "oh": 1080, "s": 4 / 3, "ox": 0, "oy": 0}
#: Letterboxed 1600x1000 on a 1920x1080 authored canvas: s = 1600/1920,
#: non-zero origin (2560x1440 alone can't see an offset bug — origin is (0,0)).
_LETTERBOXED_STAGE = {"ow": 1920, "oh": 1080, "s": 1600 / 1920, "ox": 0, "oy": 50}


def _stage_map_fragment() -> str:
    """`stageMap()` / `toScreen()` / `noteStageMapUnavailable()`, extracted verbatim."""
    core = live_continuity_js.PRESERVE_CORE_JS
    start = core.index("  const stageMapWarned = {};")
    end = core.index("  function assetKey(src) {", start)
    return core[start:end]


def _run_bridge_motion_in_node(*, stop_before_retry: bool = False, stage: dict = _IDENTITY_STAGE) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the JS core")
    core = live_continuity_js.PRESERVE_CORE_JS
    start = core.index("  function slide4Rect() {")
    end = core.index("  function keepAtSlot", start)
    motion = _stage_map_fragment() + core[start:end]
    harness = f"""
let now = 0, connected = false, preserveGeneration = 0;
const frames = [];
const boundary = {{
  atScene: 8, movieKey: 'movie1', durationSeconds: 1.5,
  srcRect: {{x: 198, y: 797, w: 952, h: 268}},
  rect: {{x: 327, y: 709, w: 1266, h: 356}},
}};
const bridgeBoundary = () => boundary;
const currentHashNum = () => 7;
const movieAssetKey = () => 'movie1';
const beginMove = () => {{}};
const note = () => {{}};
const stage = {{appendChild(v) {{connected = true; v.parentNode = stage;}}}};
const stageMapEl = {{
  offsetWidth: {json.dumps(stage["ow"])}, offsetHeight: {json.dumps(stage["oh"])},
  getBoundingClientRect: () => ({{
    left: {json.dumps(stage["ox"])}, top: {json.dumps(stage["oy"])},
    width: {json.dumps(stage["ow"])} * {json.dumps(stage["s"])},
    height: {json.dumps(stage["oh"])} * {json.dumps(stage["s"])}
  }})
}};
const document = {{
  getElementById: (id) => id === 'stage' ? stageMapEl : stage,
  body: stage, contains: () => connected
}};
const performance = {{now: () => now}};
const requestAnimationFrame = frame => frames.push(frame);
const video = {{style: {{}}, dataset: {{}}, parentNode: null, __obedRemountEpoch: 0}};
{motion}
keepThroughBridge(video);
now = 500;
frames.shift()();
const beforeDetach = parseFloat(video.style.left);
connected = false;
video.parentNode = null;
if ({str(stop_before_retry).lower()}) frames.shift()();
now = 550;
keepThroughBridge(video);
const reattached = connected;
frames.shift()();
const afterRetry = Object.fromEntries(
  ['left', 'top', 'width', 'height'].map(key => [key, parseFloat(video.style[key])])
);
const beforeClear = JSON.stringify(video.style);
preserveGeneration += 1;
now = 900;
frames.shift()();
console.log(JSON.stringify({{
  beforeDetach, reattached, afterRetry,
  unchangedAfterClear: JSON.stringify(video.style) === beforeClear,
  pendingFramesAfterClear: frames.length,
  pinningAfterClear: video.__obedMotionPinning,
}}));
"""
    result = subprocess.run([node, "-e", harness], check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize("stop_before_retry", [False, True])
def test_bridge_redetach_reconnects_without_rewinding_motion(stop_before_retry):
    result = _run_bridge_motion_in_node(stop_before_retry=stop_before_retry)
    assert result["beforeDetach"] == pytest.approx(241)
    assert result["reattached"] is True
    assert result["afterRetry"] == pytest.approx({
        "left": 245.3, "top": 764.7333333333,
        "width": 1067.1333333333, "height": 300.2666666667,
    })


def test_bridge_motion_scaled_stage_maps_authored_rect_to_screen():
    """`keepThroughBridge` interpolates in AUTHORED space then maps once — at
    s=4/3, origin (0,0) every written screen px is the identity-case value × s."""
    identity = _run_bridge_motion_in_node(stage=_IDENTITY_STAGE)
    scaled = _run_bridge_motion_in_node(stage=_SCALED_STAGE)
    s = _SCALED_STAGE["s"]
    assert scaled["beforeDetach"] == pytest.approx(identity["beforeDetach"] * s)
    for key in ("left", "top", "width", "height"):
        assert scaled["afterRetry"][key] == pytest.approx(identity["afterRetry"][key] * s)


def test_bridge_motion_letterboxed_stage_offsets_the_vertical_origin():
    """A non-zero stage origin (letterboxed 1600x1000) only shifts y/top —
    2560x1440 alone (origin (0,0)) can't see an offset-mapping bug."""
    identity = _run_bridge_motion_in_node(stage=_IDENTITY_STAGE)
    letterboxed = _run_bridge_motion_in_node(stage=_LETTERBOXED_STAGE)
    s = _LETTERBOXED_STAGE["s"]
    oy = _LETTERBOXED_STAGE["oy"]
    assert letterboxed["beforeDetach"] == pytest.approx(identity["beforeDetach"] * s)
    assert letterboxed["afterRetry"]["left"] == pytest.approx(identity["afterRetry"]["left"] * s)
    assert letterboxed["afterRetry"]["top"] == pytest.approx(identity["afterRetry"]["top"] * s + oy)
    assert letterboxed["afterRetry"]["width"] == pytest.approx(identity["afterRetry"]["width"] * s)
    assert letterboxed["afterRetry"]["height"] == pytest.approx(identity["afterRetry"]["height"] * s)


def test_clear_generation_stops_bridge_motion_callbacks():
    result = _run_bridge_motion_in_node()
    assert result["unchangedAfterClear"] is True
    assert result["pendingFramesAfterClear"] == 0
    assert result["pinningAfterClear"] is False


def _run_slot_and_bridge34_in_node(*, stage: dict) -> dict:
    """`keepAtSlot` and `bridgeTo34` both place a `<video>` on `document.body`
    (screen px) at the AUTHORED `slide4Rect()` — this exercises both against
    the same stage fixture in one Node process."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the JS core")
    core = live_continuity_js.PRESERVE_CORE_JS
    motion_start = core.index("  function slide4Rect() {")
    motion_end = core.index("  function rectOverlapArea(r, rect) {", motion_start)
    bridge_start = core.index("  function bridgeTo34(v) {")
    bridge_end = core.index("  function keepSuppressed(el) {", bridge_start)
    fragment = (
        _stage_map_fragment()
        + core[motion_start:motion_end]
        + core[bridge_start:bridge_end]
    )
    harness = f"""
let connected = false, preserveGeneration = 0;
const frames = [];
const boundary = {{
  atScene: 8, movieKey: 'movie1', durationSeconds: 1.5,
  rect: {{x: 327, y: 709, w: 1266, h: 356}},
}};
const bridgeBoundary = () => boundary;
const currentHashNum = () => 7;
const slide4MinHash = () => null;
const beginMove = () => {{}};
const note = () => {{}};
const stage = {{appendChild(v) {{connected = true; v.parentNode = stage;}}}};
const stageMapEl = {{
  offsetWidth: {json.dumps(stage["ow"])}, offsetHeight: {json.dumps(stage["oh"])},
  getBoundingClientRect: () => ({{
    left: {json.dumps(stage["ox"])}, top: {json.dumps(stage["oy"])},
    width: {json.dumps(stage["ow"])} * {json.dumps(stage["s"])},
    height: {json.dumps(stage["oh"])} * {json.dumps(stage["s"])}
  }})
}};
const document = {{
  getElementById: (id) => id === 'stage' ? stageMapEl : stage,
  body: stage, contains: () => connected
}};
const requestAnimationFrame = frame => frames.push(frame);
{fragment}
connected = true;   // real is already attached (bridgeTo34 appends before keepAtSlot runs)
const real = {{
  style: {{}}, dataset: {{}}, parentNode: null, ended: false,
  getBoundingClientRect: () => ({{left: 0, top: 0, width: 10, height: 10}})
}};
keepAtSlot(real);
frames.shift()();
const slotDest = {{left: parseFloat(real.style.left), top: parseFloat(real.style.top),
  width: parseFloat(real.style.width), height: parseFloat(real.style.height)}};

connected = false;
const bridged = {{
  style: {{}}, dataset: {{}}, parentNode: null, ended: false, paused: true,
  play() {{ this.paused = false; return {{catch(){{}}}}; }}
}};
bridgeTo34(bridged);
const bridgeDest = {{left: parseFloat(bridged.style.left), top: parseFloat(bridged.style.top),
  width: parseFloat(bridged.style.width), height: parseFloat(bridged.style.height)}};

console.log(JSON.stringify({{slotDest, bridgeDest}}));
"""
    result = subprocess.run([node, "-e", harness], check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize("stage", [_IDENTITY_STAGE, _SCALED_STAGE, _LETTERBOXED_STAGE], ids=["identity", "scaled", "letterboxed"])
def test_keep_at_slot_and_bridge_to_34_map_the_authored_dest_rect(stage):
    result = _run_slot_and_bridge34_in_node(stage=stage)
    s, ox, oy = stage["s"], stage["ox"], stage["oy"]
    expected = {
        "left": 327 * s + ox, "top": 709 * s + oy,
        "width": 1266 * s, "height": 356 * s,
    }
    assert result["slotDest"] == pytest.approx(expected)
    assert result["bridgeDest"] == pytest.approx(expected)


# --- Full-core (real DOM hooks) harness ---------------------------------
#
# The remaining I3 checks (footprint fallback, in-layer measure-and-correct
# convergence, `findMovieCanvas` tolerance scaling, `footprintOwnerDecoderId`,
# `stageMap()` null cases, `disable()`) exercise `PRESERVE_CORE_JS` through its
# REAL public hooks (`createElement('video')`, the patched `src` setter, the
# exposed `window.__OBED_P2_PRESERVE__` API) against a small fake DOM, rather
# than extracting more internal functions by name — this is what actually
# calls `tryRemount`/`stash` in production, so it exercises the real dispatch
# (posterCanvas lookup, in-stage detection, disabled-hook gating) instead of a
# hand-picked subset of it.

_FULL_HARNESS_PREAMBLE = r"""
const videos = [];
const canvases = [];
function makeVideo() {
  const v = Object.create(HTMLVideoElement.prototype);
  v.style = {};
  v.style.removeProperty = function(prop) {
    delete this[prop.replace(/-([a-z])/g, (m, c) => c.toUpperCase())];
  };
  v.dataset = {};
  v.parentNode = null;
  v.nextSibling = null;
  v.previousSibling = null;
  v.readyState = 0; v.videoWidth = 0; v.videoHeight = 0;
  v.paused = true; v.ended = false; v.currentTime = 0;
  v.play = function(){ this.paused = false; return {catch(){}}; };
  v.pause = function(){ this.paused = true; };
  v._rect = {left: 0, top: 0, width: 0, height: 0};
  // Models "rendered rect = parentOrigin + style x s": once re-parented into
  // a posterParent (marking __inStage/__screenOrigin/__scale), the rect is
  // recomputed live from the video's own inline style, exactly as a scaled
  // #stage would render it. Before that it returns the static capture rect.
  v.getBoundingClientRect = function() {
    if (this.parentNode && this.parentNode.__screenOrigin) {
      const o = this.parentNode.__screenOrigin;
      const s = this.parentNode.__scale || 1;
      return {
        left: o.x + (parseFloat(this.style.left) || 0) * s,
        top: o.y + (parseFloat(this.style.top) || 0) * s,
        width: (parseFloat(this.style.width) || 0) * s,
        height: (parseFloat(this.style.height) || 0) * s,
      };
    }
    return this._rect;
  };
  v.setAttribute = function(name, val) { if (name === 'style') this.__styleAttr = val; };
  v.getAttribute = function(name) { if (name === 'style') return this.__styleAttr || ''; return null; };
  v.removeAttribute = function(name) { return Element.prototype.removeAttribute.call(this, name); };
  videos.push(v);
  return v;
}
function HTMLMediaElement() {}
function HTMLVideoElement() {}
HTMLVideoElement.prototype = Object.create(HTMLMediaElement.prototype);
const srcStore = new WeakMap();
Object.defineProperty(HTMLMediaElement.prototype, 'src', {
  configurable: true, enumerable: true,
  get() { return srcStore.get(this) || ''; },
  set(v) { srcStore.set(this, v); },
});
const Document = { prototype: { createElement(name) {
  if (String(name).toLowerCase() === 'video') return makeVideo();
  return {style: {setProperty(){}}, getContext(){ return {drawImage(){}}; }, toDataURL(){ return ''; }};
} } };
const Element = { prototype: { removeAttribute(name) {} } };
function elStub() {
  return {style: {setProperty(){}}, addEventListener(){}, removeEventListener(){}, getAttribute(){ return null; }};
}
const STAGE_CFG = __STAGE__;
const stageEl = STAGE_CFG && {
  offsetWidth: STAGE_CFG.ow, offsetHeight: STAGE_CFG.oh,
  getBoundingClientRect: () => ({
    left: STAGE_CFG.ox, top: STAGE_CFG.oy,
    width: STAGE_CFG.ow * (STAGE_CFG.sx != null ? STAGE_CFG.sx : STAGE_CFG.s),
    height: STAGE_CFG.oh * (STAGE_CFG.sy != null ? STAGE_CFG.sy : STAGE_CFG.s),
  }),
  contains: (node) => !!(node && node.__inStage),
};
const bodyEl = elStub();
bodyEl.appendChild = function(v) { v.parentNode = bodyEl; v.__inStage = false; };
const document = {
  documentElement: elStub(), body: bodyEl,
  getElementById(id) {
    if (id === 'stage') return stageEl || null;
    if (id === 'body') return bodyEl;
    return null;
  },
  querySelectorAll(sel) {
    if (sel === 'video') return videos.slice();
    if (sel === 'video[data-obed-preserved="1"]') return videos.filter((v) => v.dataset.obedPreserved === '1');
    if (sel === 'canvas') return canvases.slice();
    return [];
  },
  contains(node) {
    let n = node;
    while (n) {
      if (n === bodyEl || n === document.documentElement) return true;
      if (n.__inStage) return true;
      n = n.parentNode;
    }
    return false;
  },
  addEventListener(){}, removeEventListener(){},
  createElement(name, opts) { return Document.prototype.createElement.call(document, name, opts); },
};
function getComputedStyle(el) {
  return {
    display: el.style.display || 'block',
    visibility: el.style.visibility || 'visible',
    opacity: el.style.opacity != null ? el.style.opacity : '1',
    zIndex: el.style.zIndex != null && el.style.zIndex !== '' ? el.style.zIndex : 'auto',
  };
}
const window = {__OBED_CONTINUITY__: __PLAN__, addEventListener(){}, removeEventListener(){}};
function MutationObserver(cb) { this.observe = function(){}; this.disconnect = function(){}; }
const location = {hash: '#1'};
const performance = {now: () => 0};
const requestAnimationFrame = () => 0;
const setTimeout = () => 0;
const setInterval = () => 0;

__CORE__

const P = window.__OBED_P2_PRESERVE__;
"""


def _run_full_core_in_node(*, plan: dict, stage: dict | None, script: str) -> dict:
    """Run the real `PRESERVE_CORE_JS` IIFE against the fake DOM above, then
    `script` (which must `console.log(JSON.stringify(...))` its result)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the JS core")
    harness = (
        _FULL_HARNESS_PREAMBLE.replace("__STAGE__", json.dumps(stage))
        .replace("__PLAN__", json.dumps(plan))
        .replace("__CORE__", live_continuity_js.PRESERVE_CORE_JS)
        + script
    )
    result = subprocess.run([node, "-e", harness], check=True, text=True, capture_output=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


_MOVIE_PLAN = {
    "movies": {"movie1": {"assetKeys": ["untitled.mov"], "footprint": {"x": 100, "y": 200, "w": 300, "h": 150}}},
    "boundaries": [],
}


@pytest.mark.parametrize("stage", [_IDENTITY_STAGE, _SCALED_STAGE, _LETTERBOXED_STAGE], ids=["identity", "scaled", "letterboxed"])
def test_stage_map_matches_measured_formula(stage):
    result = _run_full_core_in_node(
        plan=_MOVIE_PLAN, stage=stage,
        script="console.log(JSON.stringify(P.stageMap()));",
    )
    assert result == pytest.approx({
        "s": stage["s"], "ox": stage["ox"], "oy": stage["oy"],
        "authoredWidth": stage["ow"], "authoredHeight": stage["oh"],
    })


def test_stage_map_null_when_stage_missing():
    result = _run_full_core_in_node(plan=_MOVIE_PLAN, stage=None, script="console.log(JSON.stringify(P.stageMap()));")
    assert result is None


def test_stage_map_null_when_box_is_degenerate():
    zero_box = dict(_IDENTITY_STAGE, ow=0)
    result = _run_full_core_in_node(plan=_MOVIE_PLAN, stage=zero_box, script="console.log(JSON.stringify(P.stageMap()));")
    assert result is None


def test_stage_map_null_when_scale_is_non_uniform():
    non_uniform = dict(_SCALED_STAGE)
    non_uniform.pop("s")
    non_uniform["sx"] = 4 / 3
    non_uniform["sy"] = 4 / 3 * 1.01  # > 0.1% relative difference
    result = _run_full_core_in_node(plan=_MOVIE_PLAN, stage=non_uniform, script="console.log(JSON.stringify(P.stageMap()));")
    assert result is None


@pytest.mark.parametrize("stage", [_IDENTITY_STAGE, _SCALED_STAGE, _LETTERBOXED_STAGE], ids=["identity", "scaled", "letterboxed"])
def test_remount_footprint_fallback_maps_the_authored_footprint(stage):
    """When a preserved `<video>`'s captured rect is degenerate, `tryRemount`
    falls back to the plan footprint — which is AUTHORED px and must be mapped
    to SCREEN px (`box.w > 1 ? box.w : fp.w` mixes it with an already-screen box)."""
    script = r"""
const v = document.createElement('video');
v.readyState = 4; v.currentTime = 1;
v.src = 'https://host/untitled.mov';
v._rect = {left: 0, top: 0, width: 0, height: 0};
v.src = '';
P.remountAll();
const evt = P.events.find(e => e.kind === 'remount-footprint-rect');
console.log(JSON.stringify(evt && evt.detail && evt.detail.rect));
"""
    result = _run_full_core_in_node(plan=_MOVIE_PLAN, stage=stage, script=script)
    s, ox, oy = stage["s"], stage["ox"], stage["oy"]
    assert result == pytest.approx({"x": 100 * s + ox, "y": 200 * s + oy, "w": 300 * s, "h": 150 * s})


def test_remount_footprint_fallback_triggers_at_literal_zero_or_the_live_stage_origin():
    """`tryRemount`'s "looks unpositioned" check fires on EITHER the literal
    viewport origin (a detached element has no layout box, so its rect is
    (0,0) in viewport space regardless of where the stage sits — the real
    1->2 letterboxed-gate regression) OR the live stage origin (Codex's
    zero-layout-attached-parent case via `captureLayout`'s style fallback)."""
    script = r"""
const v = document.createElement('video');
v.readyState = 4; v.currentTime = 1;
v.src = 'https://host/untitled.mov';
v._rect = {left: __OX__, top: __OY__, width: 400, height: 200};
v.src = '';
P.remountAll();
const evt = P.events.find(e => e.kind === 'remount-footprint-rect');
console.log(JSON.stringify(evt && evt.detail && evt.detail.rect));
"""

    def _run(stage, at_x, at_y):
        js = script.replace("__OX__", json.dumps(at_x)).replace("__OY__", json.dumps(at_y))
        return _run_full_core_in_node(plan=_MOVIE_PLAN, stage=stage, script=js)

    for stage, box_origin in (
        (_IDENTITY_STAGE, (_IDENTITY_STAGE["ox"], _IDENTITY_STAGE["oy"])),  # nearZero == nearStageOrigin
        (_LETTERBOXED_STAGE, (_LETTERBOXED_STAGE["ox"], _LETTERBOXED_STAGE["oy"])),  # nearStageOrigin (0,50)
        (_LETTERBOXED_STAGE, (0, 0)),  # nearZero: real detach rect, stage origin is (0,50)
    ):
        s, ox, oy = stage["s"], stage["ox"], stage["oy"]
        result = _run(stage, *box_origin)
        # x/y are always replaced by the mapped footprint origin; w/h stay the
        # (already valid, >1px) captured size — only the trigger origin varies.
        assert result == pytest.approx({"x": 100 * s + ox, "y": 200 * s + oy, "w": 400, "h": 200}), (stage, box_origin)


def test_remount_does_not_treat_a_real_off_origin_rect_as_unpositioned():
    """Companion regression guard: a box that is genuinely away from the
    stage origin must NOT be forced through the footprint fallback."""
    script = r"""
const v = document.createElement('video');
v.readyState = 4; v.currentTime = 1;
v.src = 'https://host/untitled.mov';
v._rect = {left: 900, top: 450, width: 400, height: 200};
v.src = '';
P.remountAll();
console.log(JSON.stringify({
  fellBackToFootprint: P.events.some(e => e.kind === 'remount-footprint-rect'),
}));
"""
    result = _run_full_core_in_node(plan=_MOVIE_PLAN, stage=_LETTERBOXED_STAGE, script=script)
    assert result == {"fellBackToFootprint": False}


def test_remount_footprint_fallback_notes_once_when_stage_map_unavailable():
    script = r"""
const v = document.createElement('video');
v.readyState = 4; v.currentTime = 1;
v.src = 'https://host/untitled.mov';
v._rect = {left: 0, top: 0, width: 0, height: 0};
v.src = '';
P.remountAll();
P.remountAll();
const warn = P.events.filter(e => e.kind === 'stage-map-unavailable' && e.detail.consumer === 'remount-footprint-rect');
console.log(JSON.stringify({warnCount: warn.length, sawRect: P.events.some(e => e.kind === 'remount-footprint-rect')}));
"""
    result = _run_full_core_in_node(plan=_MOVIE_PLAN, stage=None, script=script)
    assert result == {"warnCount": 1, "sawRect": False}


@pytest.mark.parametrize("stage", [_IDENTITY_STAGE, _SCALED_STAGE], ids=["identity", "scaled"])
def test_in_layer_remount_converges_in_one_step_under_scale(stage):
    """`tryRemount`'s authored-layer branch divides width/height and the
    measure-and-correct delta by `s` — against a fake element whose rendered
    rect is `parentOrigin + style * s`, the SECOND measurement (after the
    single correction) must land exactly on the SCREEN-px footprint."""
    script = r"""
const posterParent = {
  __screenOrigin: {x: 40, y: 70}, __scale: __S__,
  insertBefore(node) { node.parentNode = this; node.__inStage = true; },
  appendChild(node) { node.parentNode = this; node.__inStage = true; },
};
canvases.push({
  id: 'posterCanvas1', parentNode: posterParent, nextSibling: null,
  getBoundingClientRect: () => ({left: 500, top: 300, width: 200, height: 100}),
});
const v = document.createElement('video');
v.readyState = 4; v.currentTime = 1;
v._rect = {left: 500, top: 300, width: 200, height: 100};
v.src = 'https://host/untitled.mov';
v.src = '';
P.remountAll();
const rendered = v.getBoundingClientRect();
console.log(JSON.stringify({
  style: {width: v.style.width, height: v.style.height, left: v.style.left, top: v.style.top},
  rendered,
}));
""".replace("__S__", json.dumps(stage["s"]))
    result = _run_full_core_in_node(plan=_MOVIE_PLAN, stage=stage, script=script)
    assert result["rendered"] == pytest.approx({"left": 500, "top": 300, "width": 200, "height": 100})
    s = stage["s"]
    assert float(result["style"]["width"].rstrip("px")) == pytest.approx(200 / s)
    assert float(result["style"]["height"].rstrip("px")) == pytest.approx(100 / s)


@pytest.mark.parametrize("dx,stage,should_match", [
    (12, _SCALED_STAGE, True),   # 12 screen-px off, tol = 10*4/3 = 13.33 -> matches
    (12, _IDENTITY_STAGE, False),  # same 12px off, tol = 10*1 = 10 -> does not match
])
def test_find_movie_canvas_tolerance_scales_with_s(dx, stage, should_match):
    script = r"""
canvases.push({
  id: 'c1', parentNode: {insertBefore(){}, appendChild(){}}, nextSibling: null,
  getBoundingClientRect: () => ({left: 500 + __DX__, top: 300, width: 200, height: 100}),
});
const v = document.createElement('video');
v.readyState = 4; v.currentTime = 1;
v._rect = {left: 500, top: 300, width: 200, height: 100};
v.src = 'https://host/untitled.mov';
v.src = '';
P.remountAll();
console.log(JSON.stringify({
  matched: P.events.some(e => e.kind === 'remount-into-authored-layer'),
  fellThrough: P.events.some(e => e.kind === 'remount-done'),
}));
""".replace("__DX__", json.dumps(dx))
    result = _run_full_core_in_node(plan=_MOVIE_PLAN, stage=stage, script=script)
    assert result["matched"] is should_match
    assert result["fellThrough"] is not should_match


def test_footprint_owner_decoder_id_resolves_an_authored_rect_via_mapped_screen_rect():
    script = r"""
const v = document.createElement('video');
v.readyState = 4; v.currentTime = 2; v.videoWidth = 640; v.videoHeight = 480;
v.parentNode = bodyEl;
v.src = 'https://host/untitled.mov';
v._rect = {left: 133.33333333333331, top: 266.66666666666663, width: 400, height: 200};
const owner = P.footprintOwnerDecoderId({x: 100, y: 200, w: 300, h: 150});
console.log(JSON.stringify(owner));
"""
    result = _run_full_core_in_node(plan=_MOVIE_PLAN, stage=_SCALED_STAGE, script=script)
    assert result["via"] == "footprint-video"
    assert result["key"] == "movie1"
    assert isinstance(result["elId"], int)
    assert result["contextType"] is None


def test_footprint_owner_decoder_id_no_stage_map():
    script = r"""
console.log(JSON.stringify(P.footprintOwnerDecoderId({x: 100, y: 200, w: 300, h: 150})));
"""
    result = _run_full_core_in_node(plan=_MOVIE_PLAN, stage=None, script=script)
    assert result == {"elId": None, "key": None, "via": "no-stage-map", "contextType": None}


def test_disable_makes_every_hook_a_pass_through():
    script = r"""
const disableReturned = P.disable();
const v = document.createElement('video');   // createElement patch itself isn't gated; only its src hook
v.src = 'https://host/untitled.mov';
const before = P.events.length;
v.src = '';   // patched src setter: stash() must NOT run (pass-through instead)
v.removeAttribute('src');   // must be a no-op call to the (stub) original, not stash()
const afterEvents = P.events.length;
P.remountAll();   // tryRemount is a no-op when disabled
console.log(JSON.stringify({
  disableReturned,
  disabled: P.disabled,
  ready: P.ready,
  eventsGrew: afterEvents !== before,
  styleUntouchedByRemountAll: JSON.stringify(v.style) === '{}',
}));
"""
    result = _run_full_core_in_node(plan=_MOVIE_PLAN, stage=_IDENTITY_STAGE, script=script)
    assert result == {
        "disableReturned": True, "disabled": True, "ready": True,
        "eventsGrew": False, "styleUntouchedByRemountAll": True,
    }


def test_disable_after_a_stash_is_refused():
    """Codex round 1, 1b: once `stash()` has ever pooled a video, `disable()`
    is no longer safe (it can't unwind a facade/bridge/suppress loop) — it
    must do nothing and return `false`, leaving every hook still active."""
    script = r"""
const v = document.createElement('video');
v.readyState = 4; v.currentTime = 1;
v.src = 'https://host/untitled.mov';
v.src = '';   // stash() pools it -> everPreserved becomes true
const disableReturned = P.disable();
console.log(JSON.stringify({
  disableReturned,
  disabled: !!P.disabled,
}));
"""
    result = _run_full_core_in_node(plan=_MOVIE_PLAN, stage=_IDENTITY_STAGE, script=script)
    assert result == {"disableReturned": False, "disabled": False}
