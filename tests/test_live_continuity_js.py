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
import sys

import pytest

from obed_edom import live_continuity_js


def test_continuity_version_is_pinned_int():
    assert live_continuity_js.CONTINUITY_VERSION == 5
    assert isinstance(live_continuity_js.CONTINUITY_VERSION, int)


def test_js_sha256_matches_pinned_bytes():
    expected = hashlib.sha256(live_continuity_js.PRESERVE_CORE_JS.encode()).hexdigest()
    assert live_continuity_js.js_sha256() == expected
    # Stable across repeated calls (no hidden mutable state feeding the hash).
    assert live_continuity_js.js_sha256() == live_continuity_js.js_sha256()


# `js_sha256()` of the shipped core. Re-pin only when the core's bytes change on
# purpose; a surprise here means the injected runtime moved without a decision.
PINNED_CORE_SHA256 = "e9338aff1cbe0aee74e8e1ac94412a0ffb19f787962961d9ff8ed550ebd01fa4"


def test_js_sha256_matches_the_pinned_literal():
    assert live_continuity_js.js_sha256() == PINNED_CORE_SHA256


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
let connected = false, preserveGeneration = 0, disabled = false;
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


def _run_slot_detach_in_node(
    *,
    stage: dict = _IDENTITY_STAGE,
    mutate: str = "",
    append_throws: bool = False,
    append_noop: bool = False,
    detach: bool = True,
) -> dict:
    """Drive `keepAtSlot` across a DETACH of the bridged video.

    Frame 1 runs while attached (the pin converges on the mapped slide-4 rect);
    the video is then detached (unless `detach=False`, which keeps it connected
    so the every-frame liveness check is exercised on a live node), `mutate`
    runs, and frame 2 exercises the re-attach / retire path. The fake video's
    rect is derived from its own inline style, so a converged pin is a fixed
    point (a static rect would double every frame).
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the JS core")
    core = live_continuity_js.PRESERVE_CORE_JS
    start = core.index("  function slide4Rect() {")
    end = core.index("  function rectOverlapArea(r, rect) {", start)
    fragment = _stage_map_fragment() + core[start:end]
    harness = f"""
let connected = true, disabled = false, preserveGeneration = 0, hash = 9, moves = 0;
const notes = [], frames = [];
const boundary = {{
  atScene: 8, movieKey: 'movie1', durationSeconds: 1.5,
  rect: {{x: 327, y: 709, w: 1266, h: 356}},
}};
const bridgeBoundary = () => boundary;
const currentHashNum = () => hash;
const slide4MinHash = () => 8;
const beginMove = () => {{ moves += 1; }};
const note = (kind, detail) => notes.push({{kind: kind, detail: detail}});
const stage = {{
  appendChild(v) {{
    if ({str(append_throws).lower()}) throw new Error('append failed');
    v.parentNode = stage;
    if (!{str(append_noop).lower()}) connected = true;
  }},
  removeChild(v) {{
    v.parentNode = null;
    connected = false;
  }}
}};
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
  querySelector: () => null, body: stage, contains: () => connected
}};
const requestAnimationFrame = frame => frames.push(frame);
const performance = {{now: () => 0}};
{fragment}
const real = {{
  style: {{left: '0px', top: '0px', width: '10px', height: '10px'}},
  dataset: {{obedRemounted: '1'}}, parentNode: stage, ended: false, paused: true,
  __obedElId: 7, __obedGen: 0,
  play() {{ this.paused = false; return {{catch(){{}}}}; }},
  pause() {{ this.paused = true; }},
  getBoundingClientRect() {{
    return {{
      left: parseFloat(this.style.left) || 0, top: parseFloat(this.style.top) || 0,
      width: parseFloat(this.style.width) || 0, height: parseFloat(this.style.height) || 0,
    }};
  }},
}};
const rect = () => Object.fromEntries(
  ['left', 'top', 'width', 'height'].map(key => [key, parseFloat(real.style[key])])
);
keepAtSlot(real);
frames.shift()();                 // attached frame: the pin converges
const pinned = rect();
if ({str(detach).lower()}) {{
  connected = false;
  real.parentNode = null;
}}
{mutate}
frames.shift()();                 // next frame: re-attach, retire, or end
const afterDetach = rect();
const notesAfterDetach = notes.length;
if (frames.length) frames.shift()();   // a following (re-attached) frame
console.log(JSON.stringify({{
  pinned, afterDetach, connected, moves,
  reattachNotes: notes.filter(n => n.kind === 'bridge-slot-reattach').length,
  failureNotes: notes.filter(n => n.kind === 'bridge-slot-reattach-failed'),
  retiredNotes: notes.filter(n => n.kind === 'bridge-slot-retired'),
  notesAfterDetach,
  resumed: real.paused === false,
  stillRemounted: real.dataset.obedRemounted === '1',
  pinning: !!real.__obedSlotPinning,
  pendingFrames: frames.length,
}}));
"""
    result = subprocess.run([node, "-e", harness], check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "stage", [_IDENTITY_STAGE, _LETTERBOXED_STAGE], ids=["identity", "letterboxed"]
)
def test_slot_pin_reattaches_a_detached_bridged_video(stage):
    """Codex r1 major #4: `keepAtSlot` used to end for good the moment the
    bridged video left the document, and `stash()` refuses `__obedBridged34`,
    so a player cleanup on slide 4 dropped the carried movie permanently. The
    pin must now re-attach it to the bridge stage and keep holding the mapped
    destination rect."""
    result = _run_slot_detach_in_node(stage=stage)
    expected = {
        "left": 327 * stage["s"] + stage["ox"], "top": 709 * stage["s"] + stage["oy"],
        "width": 1266 * stage["s"], "height": 356 * stage["s"],
    }
    assert result["pinned"] == pytest.approx(expected)
    assert result["afterDetach"] == pytest.approx(expected)
    assert result["connected"] is True
    assert result["pinning"] is True
    assert result["pendingFrames"] == 1      # still looping after the re-attach
    assert result["reattachNotes"] == 1      # exactly once per detach
    assert result["notesAfterDetach"] == 1   # the following attached frame adds none
    assert result["resumed"] is True
    assert result["moves"] == 1              # beginMove() before the append


def test_slot_pin_does_not_reattach_after_clear():
    """`clear()` / `disable()` bump `preserveGeneration` and stamp
    `__obedGen = -1`; a detach after that must end the loop, not resurrect a
    retired decoder."""
    result = _run_slot_detach_in_node(mutate="preserveGeneration += 1; real.__obedGen = -1;")
    assert result["reattachNotes"] == 0
    assert result["failureNotes"] == []
    assert result["connected"] is False
    assert result["pinning"] is False
    assert result["pendingFrames"] == 0


def test_slot_pin_does_not_reattach_after_a_per_element_retire():
    """`retire-on-start-movie` stamps `__obedGen = -1` WITHOUT bumping the
    generation — liveness must be read off the element, not a generation
    captured at engage time."""
    result = _run_slot_detach_in_node(mutate="real.__obedGen = -1;")
    assert result["reattachNotes"] == 0
    assert result["pinning"] is False
    assert result["pendingFrames"] == 0


def test_slot_pin_does_not_reattach_when_disabled():
    result = _run_slot_detach_in_node(mutate="disabled = true;")
    assert result["reattachNotes"] == 0
    assert result["pinning"] is False
    assert result["pendingFrames"] == 0


@pytest.mark.parametrize(
    "mutate",
    [
        "preserveGeneration += 1;",   # clear() bumped the generation but missed the element
        "real.__obedGen = -1;",       # a per-element retire stamped it while still connected
        "disabled = true;",
    ],
    ids=["clear-missed-the-element", "per-element-retire", "disabled"],
)
def test_slot_pin_retires_a_connected_decoder_that_is_no_longer_live(mutate):
    """Codex r1 major: liveness used to be read only on the DETACHED path, so a
    `clear()` that bumped the generation without removing the element (or a
    retire that stamped `__obedGen = -1` on a still-connected node) left the pin
    restyling and re-queuing frames forever — the slide-4 overlay survived the
    go-to/retire. The loop must now end on the very next frame and stop the
    overlay painting: pause, remove from the DOM, clear `obedRemounted`."""
    result = _run_slot_detach_in_node(detach=False, mutate=mutate)
    assert result["pinning"] is False
    assert result["pendingFrames"] == 0          # nothing re-queued
    assert result["connected"] is False          # taken out of the DOM
    assert result["resumed"] is False            # paused
    assert result["stillRemounted"] is False
    assert [n["detail"] for n in result["retiredNotes"]] == [{"elId": 7}]
    assert result["reattachNotes"] == 0
    assert result["failureNotes"] == []
    assert result["moves"] == 1                  # beginMove() before the removal


def test_slot_pin_keeps_holding_a_connected_live_decoder():
    """The always-connected, live-generation path is untouched by the liveness
    gate: the pin keeps the mapped rect and keeps looping."""
    result = _run_slot_detach_in_node(detach=False)
    assert result["afterDetach"] == pytest.approx(result["pinned"])
    assert result["connected"] is True
    assert result["pinning"] is True
    assert result["pendingFrames"] == 1
    assert result["retiredNotes"] == []
    assert result["reattachNotes"] == 0
    assert result["stillRemounted"] is True
    assert result["moves"] == 0


def test_slot_pin_does_not_reattach_outside_the_bridge_zone():
    """Scene left the bridge zone (hash < s4): the loop ends as it always did,
    before the re-attach path is even considered."""
    result = _run_slot_detach_in_node(mutate="hash = 7;")
    assert result["reattachNotes"] == 0
    assert result["failureNotes"] == []
    assert result["connected"] is False
    assert result["pinning"] is False
    assert result["pendingFrames"] == 0


def test_slot_pin_does_not_reattach_an_ended_decoder():
    result = _run_slot_detach_in_node(mutate="real.ended = true;")
    assert result["reattachNotes"] == 0
    assert result["pinning"] is False
    assert result["pendingFrames"] == 0


@pytest.mark.parametrize(
    "kwargs,reason",
    [({"append_throws": True}, "append failed"), ({"append_noop": True}, "still-detached")],
    ids=["throws", "still-detached"],
)
def test_slot_pin_reattach_failure_ends_the_loop_without_spinning(kwargs, reason):
    """A re-attach that throws — or that leaves the node still detached — must
    end the loop with one failure note, never re-queue a frame (hot loop)."""
    result = _run_slot_detach_in_node(**kwargs)
    assert result["reattachNotes"] == 0
    assert [n["detail"]["reason"] for n in result["failureNotes"]] == [reason]
    assert result["failureNotes"][0]["detail"]["elId"] == 7
    assert result["pinning"] is False
    assert result["pendingFrames"] == 0


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
const removedAttrs = [];
const Element = { prototype: { removeAttribute(name) {
  removedAttrs.push(name);
  if (String(name).toLowerCase() === 'src') srcStore.set(this, '');
} } };
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
bodyEl.removeChild = function(v) { v.parentNode = null; };
const document = {
  documentElement: elStub(), body: bodyEl, readyState: 'loading',
  getElementById(id) {
    if (id === 'stage') return stageEl || null;
    if (id === 'body') return bodyEl;
    return null;
  },
  querySelectorAll(sel) {
    if (sel === 'video') return videos.slice();
    if (sel === 'video[data-obed-preserved="1"]') {
      return videos.filter((v) => v.dataset.obedPreserved === '1' && document.contains(v));
    }
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
const hashListeners = [];
const window = {
  __OBED_CONTINUITY__: __PLAN__,
  addEventListener(type, fn) { if (type === 'hashchange') hashListeners.push(fn); },
  removeEventListener(){},
};
const moCallbacks = [];
function MutationObserver(cb) {
  moCallbacks.push(cb);
  this.observe = function(){}; this.disconnect = function(){};
}
const location = {hash: '#1'};
/** Move the player to scene `n` and run the core's hashchange listeners. */
function goToScene(n) {
  location.hash = '#' + n;
  hashListeners.slice().forEach((fn) => fn());
}
/** Drive the core's detach MutationObserver as the player's teardown would. */
function detach(v) {
  v.parentNode = null;
  moCallbacks.slice().forEach((cb) => cb([{removedNodes: [v]}]));
}
const performance = {now: () => 0};
const requestAnimationFrame = () => 0;
const setTimeout = () => 0;
const intervals = [];
const setInterval = (fn) => { intervals.push(fn); return 0; };
/** Run the core's keep-warm interval once (it drives the retire sweep). */
function tick() { intervals.slice().forEach((fn) => fn()); }

__CORE__

const P = window.__OBED_P2_PRESERVE__;
__AFTER_CORE__
"""


#: Every inline `<script>` (plan, core, GL module) runs while the document is
#: still `loading`; the harness flips it once the core has installed (K17).
_LOADED = "document.readyState = 'complete';"


def _run_full_core_in_node(
    *, plan: dict, stage: dict | None, script: str, after_core: str = _LOADED
) -> dict:
    """Run the real `PRESERVE_CORE_JS` IIFE against the fake DOM above, then
    `after_core` (the rest of the page's inline scripts, then the load), then
    `script` (which must `console.log(JSON.stringify(...))` its result)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the JS core")
    harness = (
        _FULL_HARNESS_PREAMBLE.replace("__STAGE__", json.dumps(stage))
        .replace("__PLAN__", json.dumps(plan))
        .replace("__AFTER_CORE__", after_core)
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


# --- I2: the retire zone (per-boundary refusal) -------------------------
#
# Contract: one `{"atScene": N, "action": "retire", "movieKey": K}` boundary
# hands K back to the raw player. Measured on the real export (2026-09-20):
# the player detaches the movie while the hash is still the TRANSITION scene
# (`N - 1`) and only rewrites it to `N` ~2 s later — and it rewrites the hash
# WITHOUT ever firing `hashchange`. So the zone is `[N - 1, <next
# restart/bridge atScene>)` and the sweep is driven by the keep-warm interval.
# Inside the zone the runtime must be INVISIBLE: nothing pooled, remounted,
# facaded or reused, and the `src` clear / `removeAttribute('src')` the hooks
# normally swallow must really happen. Every decline notes `preserve-refused`
# (once per key+via); the sweep notes `retire-boundary`.

#: The fixture's shape: retire movie1 at scene 2 (so the zone opens at the #1
#: transition), restart at 6 (zone end), bridge at 8.
_RETIRE_PLAN = {
    "movies": {
        "movie1": {"assetKeys": ["untitled.mov"], "footprint": {"x": 100, "y": 200, "w": 300, "h": 150}},
        "movie2": {"assetKeys": ["wa0125.mov"], "footprint": {"x": 900, "y": 500, "w": 200, "h": 100}},
    },
    "boundaries": [
        {"atScene": 2, "action": "retire", "movieKey": "movie1"},
        {"atScene": 6, "action": "restart"},
        {
            "atScene": 8, "action": "bridge", "movieKey": "movie1",
            "srcRect": {"x": 198, "y": 797, "w": 952, "h": 268},
            "rect": {"x": 327, "y": 709, "w": 1266, "h": 356},
            "durationSeconds": 1.5,
        },
    ],
}
#: Same plan with the retire entry removed — the "behaves exactly as today" control.
_NO_RETIRE_PLAN = {
    "movies": _RETIRE_PLAN["movies"],
    "boundaries": [b for b in _RETIRE_PLAN["boundaries"] if b["action"] != "retire"],
}
#: Scenes the retire zone covers, and the ones just outside it on either side.
_IN_ZONE = [1, 2, 3, 5]
_BEFORE_ZONE = [0]
_AFTER_ZONE = [6, 7]

#: Pool a live `movie1` decoder by driving the player's real teardown path
#: (detach -> the core's MutationObserver -> `stash`). `__SCENE__`/`__SRC__`
#: are substituted per test. The scene is ALWAYS set explicitly: the harness's
#: default hash (`#1`) is itself inside the fixture's zone.
_MAKE_AND_DETACH = r"""
const v = document.createElement('video');
v.readyState = 4; v.currentTime = 1;
v.parentNode = bodyEl;
v.src = '__SRC__';
__SCENE__
detach(v);
"""

_POOL_REPORT = r"""
console.log(JSON.stringify({
  poolKeys: P.poolKeys,
  pooled: P.snapshot().filter(x => !x.fromDom).length,
  preserved: v.dataset.obedPreserved || null,
  refusals: P.events.filter(e => e.kind === 'preserve-refused').map(e => e.detail),
  kinds: P.events.map(e => e.kind),
}));
"""


def _run_retire(script: str, *, plan: dict = _RETIRE_PLAN) -> dict:
    return _run_full_core_in_node(plan=plan, stage=_IDENTITY_STAGE, script=script)


def _detach_script(*, scene: int, src: str = "https://host/untitled.mov") -> str:
    return _MAKE_AND_DETACH.replace("__SCENE__", f"goToScene({scene});").replace("__SRC__", src)


def test_core_never_relies_on_a_hashchange_event():
    """Measured on the real player: it rewrites `location.hash` without firing
    `hashchange`, so the retire sweep must not be registered on it."""
    script = r"""
console.log(JSON.stringify({hashListeners: hashListeners.length, intervals: intervals.length}));
"""
    result = _run_retire(script)
    assert result["hashListeners"] == 0
    assert result["intervals"] >= 1


@pytest.mark.parametrize("scene", _IN_ZONE, ids=[f"scene{s}" for s in _IN_ZONE])
def test_retire_zone_stash_declines_and_notes_once(scene):
    """The player's detach — which really happens at the TRANSITION scene, one
    before `atScene` — must be refused: nothing pooled, no remount scheduled,
    and `preserve-refused` noted exactly once per (key, via) however many times
    the player tears the movie down."""
    script = _detach_script(scene=scene) + r"""
detach(v);
detach(v);
""" + _POOL_REPORT
    result = _run_retire(script)
    assert result["poolKeys"] == []
    assert result["pooled"] == 0
    assert result["preserved"] is None
    assert result["refusals"] == [
        {"key": "movie1", "scene": scene, "via": "stash", "sceneHash": f"#{scene}"}
    ]
    assert not [k for k in result["kinds"] if k.startswith("remount-")]


@pytest.mark.parametrize("scene", _IN_ZONE, ids=[f"scene{s}" for s in _IN_ZONE])
def test_retire_zone_src_clear_really_clears(scene):
    """The src hook swallows the clear unconditionally today; inside the zone
    the REAL setter must run, or the refused movie still deviates from raw."""
    script = r"""
const v = document.createElement('video');
v.readyState = 4; v.currentTime = 1;
v.parentNode = bodyEl;
v.src = 'https://host/untitled.mov';
goToScene(__SCENE__);
v.src = '';
console.log(JSON.stringify({
  src: v.src,
  pooled: P.snapshot().filter(x => !x.fromDom).length,
  refusals: P.events.filter(e => e.kind === 'preserve-refused').map(e => e.detail),
}));
""".replace("__SCENE__", str(scene))
    result = _run_retire(script)
    assert result["src"] == ""
    assert result["pooled"] == 0
    assert result["refusals"] == [
        {"key": "movie1", "scene": scene, "via": "src-clear", "sceneHash": f"#{scene}"}
    ]


def test_retire_zone_remove_attribute_really_removes():
    script = r"""
const v = document.createElement('video');
v.readyState = 4; v.currentTime = 1;
v.parentNode = bodyEl;
v.src = 'https://host/untitled.mov';
goToScene(1);
v.removeAttribute('src');
v.removeAttribute('src');
console.log(JSON.stringify({
  removedAttrs,
  pooled: P.snapshot().filter(x => !x.fromDom).length,
  refusals: P.events.filter(e => e.kind === 'preserve-refused').map(e => e.detail),
}));
"""
    result = _run_retire(script)
    assert result["removedAttrs"] == ["src", "src"]
    assert result["pooled"] == 0
    assert result["refusals"] == [
        {"key": "movie1", "scene": 1, "via": "removeAttribute", "sceneHash": "#1"}
    ]


def test_retire_zone_blocks_remount_of_a_decoder_pooled_before_the_boundary():
    """`remountAll()` on a decoder pooled at rest on slide 1 (`#0`) must do
    nothing once the scene is in the zone. The hash is moved WITHOUT running
    the interval, so this isolates `tryRemount`'s own guard from the sweep."""
    script = _detach_script(scene=0) + r"""
const pooledBefore = P.snapshot().filter(x => !x.fromDom).length;
location.hash = '#1';
const before = JSON.stringify(v.style);
P.remountAll();
console.log(JSON.stringify({
  pooledBefore,
  styleUntouched: JSON.stringify(v.style) === before,
  remountedInZone: P.events.filter(e => e.kind.indexOf('remount-') === 0 && e.detail.sceneHash === '#1').length,
  refusals: P.events.filter(e => e.kind === 'preserve-refused').map(e => e.detail),
}));
"""
    result = _run_retire(script)
    assert result["pooledBefore"] == 1
    assert result["styleUntouched"] is True
    assert result["remountedInZone"] == 0
    assert result["refusals"] == [{"key": "movie1", "scene": 1, "via": "remount", "sceneHash": "#1"}]


def test_retire_zone_create_element_does_not_facade_or_reuse():
    """A fresh element created inside the zone plays natively: no facade, no
    `reuse-decoder`, and its own `setAttribute('src')` reaches the element."""
    script = _detach_script(scene=0) + r"""
location.hash = '#3';
const fresh = document.createElement('video');
fresh.setAttribute('src', 'https://host/untitled.mov');
console.log(JSON.stringify({
  facade: fresh.dataset.obedFacade || null,
  facadeFor: fresh.__obedFacadeFor ? 1 : 0,
  reuse: P.events.filter(e => e.kind === 'reuse-decoder' || e.kind === 'bridge-3to4').length,
  kinds: P.events.map(e => e.kind),
}));
"""
    result = _run_retire(script)
    assert result["facade"] is None
    assert result["facadeFor"] == 0
    assert result["reuse"] == 0
    assert "retire-on-start-movie" not in result["kinds"]


def test_interval_sweep_retires_a_decoder_pooled_before_the_zone():
    """A decoder legitimately pooled at rest on slide 1 (`#0`) must be retired
    once the hash reaches the zone — driven by the keep-warm interval, since
    the player never fires `hashchange`. Pause, out of the DOM, dead for
    reuse, and said out loud with `retire-boundary`."""
    script = _detach_script(scene=0) + r"""
const elId = v.__obedElId;
const pooledBefore = P.snapshot().filter(x => !x.fromDom).length;
location.hash = '#1';
const sweptBeforeTick = P.events.filter(e => e.kind === 'retire-boundary').length;
tick();
tick();
console.log(JSON.stringify({
  elId, pooledBefore, sweptBeforeTick,
  pooledAfter: P.snapshot().filter(x => !x.fromDom).length,
  poolKeys: P.poolKeys,
  paused: v.paused,
  inDocument: document.contains(v),
  preserved: v.dataset.obedPreserved || null,
  remounted: v.dataset.obedRemounted || null,
  gen: v.__obedGen,
  epoch: v.__obedRemountEpoch,
  retire: P.events.filter(e => e.kind === 'retire-boundary').map(e => e.detail),
}));
"""
    result = _run_retire(script)
    assert result["pooledBefore"] == 1
    assert result["sweptBeforeTick"] == 0
    assert result["pooledAfter"] == 0
    assert result["poolKeys"] == []
    assert result["paused"] is True
    assert result["inDocument"] is False
    assert result["preserved"] is None
    assert result["remounted"] is None
    assert result["gen"] == -1
    assert result["epoch"] == -1
    # Swept once: the second tick finds nothing and must not re-note.
    assert result["retire"] == [
        {"key": "movie1", "elIds": [result["elId"]], "atScene": 2, "sceneHash": "#1"}
    ]


@pytest.mark.parametrize("scene", _BEFORE_ZONE + _AFTER_ZONE, ids=lambda s: f"scene{s}")
def test_interval_sweep_is_silent_outside_the_zone(scene):
    """No `retire-boundary` outside the zone — the note is a positive claim,
    and the interval runs on every scene of the deck."""
    script = _detach_script(scene=scene) + r"""
tick();
console.log(JSON.stringify({
  retire: P.events.filter(e => e.kind === 'retire-boundary').length,
  pooled: P.snapshot().filter(x => !x.fromDom).length,
}));
"""
    result = _run_retire(script)
    assert result["retire"] == 0
    assert result["pooled"] == 1


@pytest.mark.parametrize("scene", _BEFORE_ZONE, ids=lambda s: f"scene{s}")
def test_before_the_retire_zone_preservation_is_unchanged(scene):
    """Slide 1 at rest (`#0`) is one scene before the transition: the implicit
    pin still holds, exactly as today."""
    result = _run_retire(_detach_script(scene=scene) + _POOL_REPORT)
    assert result["poolKeys"] == ["untitled.mov"]
    assert result["pooled"] == 1
    assert result["preserved"] == "1"
    assert result["refusals"] == []
    assert "remount-scheduled" in result["kinds"]


@pytest.mark.parametrize("scene", _AFTER_ZONE, ids=["zone-end", "after-zone-end"])
def test_after_the_zone_end_preservation_works_again(scene):
    """The restart at scene 6 creates a fresh element the export itself plays;
    from 6 on the runtime may preserve it again (that is what the 3->4 bridge
    carries). The zone END keeps the plain `atScene` convention, so the 2->3
    dissolve scene (#5) is still refused."""
    result = _run_retire(_detach_script(scene=scene) + _POOL_REPORT)
    assert result["poolKeys"] == ["untitled.mov"]
    assert result["pooled"] == 1
    assert result["preserved"] == "1"
    assert result["refusals"] == []


def test_bridge_still_engages_at_scene_8_for_the_retired_key():
    """End to end on the fixture's shape: pooled at `#0`, swept when the
    transition opens the zone, refused through 1..5, pooled again at 7,
    bridged at 8 — the retire must not poison the later bridge."""
    script = _detach_script(scene=0) + r"""
location.hash = '#1';
tick();
goToScene(3);
const refused = document.createElement('video');
refused.readyState = 4; refused.currentTime = 1; refused.parentNode = bodyEl;
refused.src = 'https://host/untitled.mov';
detach(refused);
goToScene(7);
const fresh = document.createElement('video');
fresh.readyState = 4; fresh.currentTime = 2; fresh.parentNode = bodyEl;
fresh.src = 'https://host/untitled.mov';
detach(fresh);
const pooledAtSeven = P.snapshot().filter(x => !x.fromDom).length;
goToScene(8);
tick();
const bridged = document.createElement('video');
bridged.setAttribute('src', 'https://host/untitled.mov');
console.log(JSON.stringify({
  pooledAtSeven,
  retire: P.events.filter(e => e.kind === 'retire-boundary').length,
  refusalVias: P.events.filter(e => e.kind === 'preserve-refused').map(e => e.detail.via),
  bridge: P.events.filter(e => e.kind === 'bridge-3to4').map(e => e.detail.oldElId),
  suppressed: !!bridged.__obedSuppressed34,
  freshElId: fresh.__obedElId,
}));
"""
    result = _run_retire(script)
    assert result["pooledAtSeven"] == 1
    assert result["retire"] == 1
    assert result["refusalVias"] == ["stash"]
    assert result["bridge"] == [result["freshElId"]]
    assert result["suppressed"] is True


@pytest.mark.parametrize("scene", _IN_ZONE, ids=[f"scene{s}" for s in _IN_ZONE])
def test_retire_zone_does_not_touch_another_movie_key(scene):
    """The refusal is per-movie: a movie the plan does not retire keeps being
    preserved inside the zone, and the sweep never takes it."""
    script = _detach_script(scene=scene, src="https://host/WA0125.mov") + r"""
tick();
""" + _POOL_REPORT
    result = _run_retire(script)
    assert result["poolKeys"] == ["wa0125.mov"]
    assert result["pooled"] == 1
    assert result["preserved"] == "1"
    assert result["refusals"] == []


@pytest.mark.parametrize(
    "scene", _BEFORE_ZONE + _IN_ZONE + _AFTER_ZONE, ids=lambda s: f"scene{s}"
)
def test_plan_without_a_retire_behaves_exactly_as_today(scene):
    """Same scenes, same teardown, retire entry removed: every scene in what
    WOULD be the zone preserves as before, and the interval sweep is inert."""
    result = _run_full_core_in_node(
        plan=_NO_RETIRE_PLAN, stage=_IDENTITY_STAGE,
        script=_detach_script(scene=scene) + "tick();\n" + _POOL_REPORT,
    )
    assert result["poolKeys"] == ["untitled.mov"]
    assert result["pooled"] == 1
    assert result["preserved"] == "1"
    assert result["refusals"] == []
    assert "retire-boundary" not in result["kinds"]
    assert "remount-scheduled" in result["kinds"]


def test_null_hash_is_allowed():
    """No scene index in the hash: nothing places the player in the zone, so
    preservation stays allowed (unchanged from today)."""
    script = _MAKE_AND_DETACH.replace("__SCENE__", "location.hash = '';").replace(
        "__SRC__", "https://host/untitled.mov"
    ) + "tick();\n" + _POOL_REPORT
    result = _run_retire(script)
    assert result["pooled"] == 1
    assert result["preserved"] == "1"
    assert result["refusals"] == []


# Codex r1 MAJOR: inside the zone the hooks let a REAL `src` clear through, so
# a decoder pooled before the zone loses its src-derived identity exactly when
# the refusal needs it. Identity is stamped (`__obedMovieKey`) and the sweep
# selects from the POOL's key, so an empty-src decoder is still recognised.

#: Pool a movie1 decoder at `#0`, enter the zone, then let the player REALLY
#: clear the src (the in-zone hooks no longer swallow it). `__CLEAR__` is the
#: clearing call under test.
_CLEARED_IN_ZONE = r"""
const v = document.createElement('video');
v.readyState = 4; v.currentTime = 1;
v.parentNode = bodyEl;
v.src = 'https://host/untitled.mov';
goToScene(0);
detach(v);
const elId = v.__obedElId;
const pooledBefore = P.snapshot().filter(x => !x.fromDom).length;
location.hash = '#1';
__CLEAR__
const srcAfterClear = v.src || '';
"""


def _cleared_in_zone(clear: str, tail: str) -> dict:
    return _run_retire(_CLEARED_IN_ZONE.replace("__CLEAR__", clear) + tail)


@pytest.mark.parametrize(
    "clear", ["v.src = '';", "v.removeAttribute('src');"], ids=["src-clear", "removeAttribute"],
)
def test_sweep_retires_a_pooled_decoder_whose_src_was_really_cleared(clear):
    """`movieAssetKey('')` is null, but the pool still knows the asset key —
    the sweep must select by it, not by the (now empty) live src."""
    tail = r"""
tick();
console.log(JSON.stringify({
  elId, pooledBefore, srcAfterClear,
  pooledAfter: P.snapshot().filter(x => !x.fromDom).length,
  poolKeys: P.poolKeys,
  paused: v.paused,
  inDocument: document.contains(v),
  preserved: v.dataset.obedPreserved || null,
  gen: v.__obedGen,
  retire: P.events.filter(e => e.kind === 'retire-boundary').map(e => e.detail),
}));
"""
    result = _cleared_in_zone(clear, tail)
    assert result["pooledBefore"] == 1
    assert result["srcAfterClear"] == ""
    assert result["pooledAfter"] == 0
    assert result["poolKeys"] == []
    assert result["paused"] is True
    assert result["inDocument"] is False
    assert result["preserved"] is None
    assert result["gen"] == -1
    assert result["retire"] == [
        {"key": "movie1", "elIds": [result["elId"]], "atScene": 2, "sceneHash": "#1"}
    ]


@pytest.mark.parametrize(
    "clear", ["v.src = '';", "v.removeAttribute('src');"], ids=["src-clear", "removeAttribute"],
)
def test_pending_remount_of_an_empty_src_decoder_is_refused_in_zone(clear):
    """A retry scheduled before the zone reaches `tryRemount` after the clear:
    with identity read only off the src it would be allowed to remount. The
    stamped key must refuse it, with a `preserve-refused` via `remount`."""
    tail = r"""
const styleBefore = JSON.stringify(v.style);
P.remountAll();
console.log(JSON.stringify({
  srcAfterClear,
  styleUntouched: JSON.stringify(v.style) === styleBefore,
  remountedInZone: P.events.filter(e => e.kind.indexOf('remount-') === 0 && e.detail.sceneHash === '#1').length,
  refusals: P.events.filter(e => e.kind === 'preserve-refused').map(e => e.detail),
}));
"""
    result = _cleared_in_zone(clear, tail)
    assert result["srcAfterClear"] == ""
    assert result["styleUntouched"] is True
    assert result["remountedInZone"] == 0
    assert {"key": "movie1", "scene": 1, "via": "remount", "sceneHash": "#1"} in result["refusals"]


@pytest.mark.parametrize(
    "clear", ["v.src = '';", "v.removeAttribute('src');"], ids=["src-clear", "removeAttribute"],
)
def test_a_stamped_empty_src_decoder_is_free_again_past_the_zone_end(clear):
    """Companion control that the stamp does not over-reach: the SAME
    really-cleared, still-stamped decoder, carried past the zone without the
    interval ever firing inside it, must at the zone end (`#6`, the restart
    scene — not `#7`, where the bridge motion legitimately takes over) be
    neither swept nor refused, and may remount again."""
    tail = r"""
location.hash = '#6';
tick();
P.remountAll();
console.log(JSON.stringify({
  srcAfterClear,
  stamped: v.__obedMovieKey,
  retire: P.events.filter(e => e.kind === 'retire-boundary').length,
  refusalsAtSix: P.events.filter(e => e.kind === 'preserve-refused' && e.detail.sceneHash === '#6').length,
  remountedAtSix: P.events.filter(e => e.kind.indexOf('remount-') === 0 && e.detail.sceneHash === '#6').length,
}));
"""
    result = _cleared_in_zone(clear, tail)
    assert result["srcAfterClear"] == ""
    assert result["stamped"] == "movie1"
    assert result["retire"] == 0      # the sweep never ran inside the zone here
    assert result["refusalsAtSix"] == 0
    assert result["remountedAtSix"] >= 1


# Codex r2 MAJOR 1: identity must also go STALE correctly. An element given a
# different asset is no longer the movie it was pooled as, so the stamp and the
# pool membership must follow the new source — otherwise the retire sweep
# pauses and removes what is now an unplanned clip.

#: Pool a movie1 decoder at `#0`, then re-assign `__NEXT__` to that very
#: element (both the `.src` setter and `setAttribute` are exercised).
_REASSIGN = r"""
const v = document.createElement('video');
v.readyState = 4; v.currentTime = 1;
v.parentNode = bodyEl;
v.src = 'https://host/untitled.mov';
goToScene(0);
detach(v);
// `P.poolKeys` is only refreshed by `note()`, so read the live census.
const poolNow = () => P.snapshot().filter(x => !x.fromDom).map(x => x.key);
const pooledBefore = poolNow();
__ASSIGN__
const report = () => ({
  pooledBefore,
  poolKeys: poolNow(),
  stamp: v.__obedMovieKey === undefined ? 'unset' : v.__obedMovieKey,
  preserved: v.dataset.obedPreserved || null,
});
"""


def _reassign(via: str, url: str, tail: str) -> dict:
    assign = (
        f"v.src = '{url}';" if via == "setter" else f"v.setAttribute('src', '{url}');"
    )
    return _run_retire(_REASSIGN.replace("__ASSIGN__", assign) + tail)


_SWEEP_TAIL = r"""
location.hash = '#1';
tick();
console.log(JSON.stringify(Object.assign(report(), {
  paused: v.paused,
  inDocument: document.contains(v),
  gen: v.__obedGen === undefined ? 'unset' : v.__obedGen,
  retire: P.events.filter(e => e.kind === 'retire-boundary').map(e => e.detail),
})));
"""


@pytest.mark.parametrize("via", ["setter", "setAttribute"])
def test_reassigning_an_unplanned_asset_drops_pool_membership_and_the_stamp(via):
    """The deliberately unplanned WA0125 clip: the element leaves the pool,
    loses `obedPreserved` and its stamp is CLEARED — so a later in-zone sweep
    must not pause or detach it."""
    result = _reassign(via, "https://host/WA0125-unplanned.mov", _SWEEP_TAIL)
    assert result["pooledBefore"] == ["untitled.mov"]
    assert result["poolKeys"] == []
    assert result["stamp"] is None
    assert result["preserved"] is None
    assert result["retire"] == []
    assert result["paused"] is False
    assert result["inDocument"] is True
    assert result["gen"] == 0


def test_reassigning_the_same_asset_leaves_the_pool_untouched():
    """The reuse/facade path re-assigns the SAME src on a live decoder (via the
    `.src` setter — `bindFacade` forwards onto `real.src`), and that must not
    disturb pool membership or the preserved mark. Only the setter path is
    asserted here: `setAttribute('src')` on an ALREADY-pooled element drains
    its queue through the pre-existing reuse lookup, which is unrelated to
    re-identification and is not a path the player takes."""
    result = _reassign("setter", "https://host/untitled.mov", r"""
console.log(JSON.stringify(report()));
""")
    assert result["poolKeys"] == ["untitled.mov"]
    assert result["stamp"] == "movie1"
    assert result["preserved"] == "1"


@pytest.mark.parametrize("via", ["setter", "setAttribute"])
def test_reassigning_another_planned_key_moves_the_stamp(via):
    """A second PLANNED movie: the stamp follows the new key and the old pool
    membership is dropped (it is not that movie any more)."""
    result = _reassign(via, "https://host/WA0125.mov", r"""
console.log(JSON.stringify(report()));
""")
    assert result["poolKeys"] == []
    assert result["stamp"] == "movie2"
    assert result["preserved"] is None


def test_bind_facade_src_forward_does_not_evict_the_reused_decoder():
    """`bindFacade` forwards `stub.src = url` onto the real decoder; with the
    same asset that must be a no-op for identity (Codex r2: do not break the
    reuse path)."""
    script = r"""
const v = document.createElement('video');
v.readyState = 4; v.currentTime = 1; v.parentNode = bodyEl;
v.src = 'https://host/untitled.mov';
goToScene(0);
detach(v);
const fresh = document.createElement('video');
fresh.setAttribute('src', 'https://host/untitled.mov');
const reused = P.events.filter(e => e.kind === 'reuse-decoder').length;
fresh.src = 'https://host/untitled.mov';   // facade forward onto the real decoder
console.log(JSON.stringify({
  reused,
  facade: fresh.dataset.obedFacade || null,
  realStamp: v.__obedMovieKey,
  realPreserved: v.dataset.obedPreserved || null,
}));
"""
    result = _run_retire(script)
    assert result["reused"] == 1
    assert result["facade"] == "1"
    assert result["realStamp"] == "movie1"
    assert result["realPreserved"] == "1"


# Codex r2 MAJOR 2 (runtime half): the P2 pool census must be able to attribute
# a preserved decoder whose src was really cleared inside the retire zone.


def test_snapshot_reports_a_movie_key_for_a_cleared_src_preserved_element():
    script = r"""
const v = document.createElement('video');
v.readyState = 4; v.currentTime = 1; v.parentNode = bodyEl;
v.src = 'https://host/untitled.mov';
goToScene(0);
detach(v);
const pooled = P.snapshot().filter(x => !x.fromDom);
location.hash = '#1';
v.src = '';
const dom = P.snapshot().filter(x => x.fromDom);
console.log(JSON.stringify({
  srcAfterClear: v.src || '',
  pooledKeys: pooled.map(x => [x.key, x.movieKey]),
  domKeys: dom.map(x => [x.key, x.movieKey]),
}));
"""
    result = _run_retire(script)
    assert result["srcAfterClear"] == ""
    assert result["pooledKeys"] == [["untitled.mov", "movie1"]]
    # `key` stays as-is (back-compat, now empty); `movieKey` still attributes it.
    assert result["domKeys"] == [["", "movie1"]]


def test_snapshot_movie_key_is_null_for_an_unplanned_preserved_element():
    """`movieKey` is a claim, not a guess: an element the plan does not name
    must report null rather than borrowing a neighbouring key."""
    script = r"""
const v = document.createElement('video');
v.readyState = 4; v.currentTime = 1; v.parentNode = bodyEl;
v.src = 'https://host/untitled.mov';
goToScene(0);
detach(v);
v.src = 'https://host/WA0125-unplanned.mov';
v.dataset.obedPreserved = '1';
console.log(JSON.stringify(P.snapshot().map(x => [x.key, x.movieKey, !!x.fromDom])));
"""
    result = _run_retire(script)
    assert result == [["wa0125-unplanned.mov", None, True]]


# --- G3: the glReplay zone and its seam ---------------------------------
#
# Plan: the G3+G4 plan rev 2 §1–§2 (PR #214). A
# `glReplay` boundary is the retire zone run as a one-shot state machine
# (`pending -> armed | retired`, `armed -> released | retired`, `released ->
# retired`). The GL module is faked here as the plain object it publishes
# (`window.__OBED_GL_REPLAY__ = {version, state, standDowns}`); the contract
# that the real module fills those fields the way §2 row 4 and the §1
# `moduleRetired` exclusion rely on is pinned in `tests/test_live_gl_replay_js.py`.
# Every `release` row and every watchdog below is driven by a real state
# (a real `standDowns` array, a real hash, a real detach), never a grep.

#: F4, measured: the big instance's attached own box in authored px (the same at
#: s = 1 and s = 0.8333), 0.012 px off the plan's `instanceRect`.
_GL_MEASURED = {"x": 109.3517, "y": 795.0362, "w": 951.5313, "h": 267.6094}
_GL_INSTANCE = {"x": 109.3517, "y": 795.0362, "w": 951.5430, "h": 267.6215}
_GL_SIBLING = {"x": 1075.7865, "y": 876.2469, "w": 662.7813, "h": 186.4063}
#: `slotRects[movieSlot]`, the texture slot G2 hands back (authored px).
_GL_SLOT = {"x": 105.1231918334961, "y": 790.846923828125, "w": 960.0, "h": 276.0}

_GL_ENTRY = {
    "atScene": 2, "action": "glReplay", "movieKey": "movie1", "fallback": "retire",
    "slotRects": [[0.0, 0.0, 1920.0, 1080.0], [_GL_SLOT["x"], _GL_SLOT["y"], _GL_SLOT["w"], _GL_SLOT["h"]]],
    "movieSlot": 1,
    "instanceId": "untitled.mov#1",
    "instanceRect": _GL_INSTANCE,
}
#: The fixture's retire shape with the retire entry swapped for the flag-on one.
_GL_PLAN = {
    "movies": _RETIRE_PLAN["movies"],
    "boundaries": [_GL_ENTRY] + [b for b in _RETIRE_PLAN["boundaries"] if b["action"] != "retire"],
}
#: The module as published while it waits in ARM-PRE.
_G2_ARMING = {"version": 1, "state": "ARM-PRE", "standDowns": []}

#: The GL module's §2.7 stand-down reasons other than the normal exit.
_G2_FAILURES = [
    "planUnreadable", "runtimeSeamAbsent", "glReplayUnavailable", "settleSignalAbsent",
    "sceneMismatch", "observerNotArmed", "canvasShape", "posterAmbiguous", "posterUnreadable",
    "frameNotDelimited", "contextLost", "rvfcUnavailable", "videoNotReady", "assetUnbound",
    "occlusionTooHigh", "unflaggedPlayerCall", "frameLengthChanged", "glError", "writebackFailed",
]

_GL_PRELUDE = r"""
const INSTANCE = __INSTANCE__, MEASURED = __MEASURED__, SIBLING = __SIBLING__, SLOT = __SLOT__;
const G2 = window.__OBED_GL_REPLAY__;
const S = P.glReplay;
function screenOf(r) {
  const m = P.stageMap();
  return {left: r.x * m.s + m.ox, top: r.y * m.s + m.oy, width: r.w * m.s, height: r.h * m.s};
}
/** A playing, attached movie <video> whose own box is `rect` (authored px). */
function makeMovie(rect, src) {
  const v = document.createElement('video');
  v.readyState = 4; v.currentTime = 1; v.paused = false;
  v.parentNode = bodyEl;
  v.src = src || 'https://host/untitled.mov';
  v.__styleAttr = 'position: absolute; width: ' + rect.w + 'px; height: ' + rect.h + 'px;';
  v._rect = screenOf(rect);
  return v;
}
/** The player's Magic-Move teardown: a detached node has an all-zero own box (F3). */
function playerDetach(v) {
  v._rect = {left: 0, top: 0, width: 0, height: 0};
  detach(v);
}
/**
 * The fixture's teardown (r1 `preserve-on-detach-subtree`): the movie's LAYER is
 * removed, so the node keeps its (now detached, zero-box) parent — the K6 case.
 */
function playerDetachSubtree(v) {
  const layer = {
    id: 'layer-' + v.__obedElId, parentNode: bodyEl, parentElement: null,
    getBoundingClientRect: () => ({left: 0, top: 0, width: 0, height: 0}),
    querySelectorAll: (sel) => (sel === 'video' && v.parentNode === layer ? [v] : []),
    removeChild(node) { node.parentNode = null; node.parentElement = null; },
  };
  v.parentNode = layer;
  v.parentElement = layer;
  v.__inStage = false;
  v._rect = {left: 0, top: 0, width: 0, height: 0};
  layer.parentNode = null;
  moCallbacks.slice().forEach((cb) => cb([{removedNodes: [layer]}]));
  return layer;
}
/** The measured 1->2 flow up to G2 arming: rest capture on #1, detach, `glreplay-arm`. */
function arm() {
  location.hash = '#1';
  const big = makeMovie(MEASURED), sib = makeMovie(SIBLING);
  tick();
  const bigLayer = playerDetachSubtree(big);
  playerDetachSubtree(sib);
  S.note('glreplay-arm', {canvasId: '0-canvas', atScene: 2});
  return {big: big, sib: sib, bigLayer: bigLayer};
}
function goLive() {
  const carried = S.carried('movie1');
  S.note('glreplay-live', {canvasId: '0-canvas', epoch: 1, frameLen: 88});
  location.hash = '#2';
  return carried;
}
function standDown(list) {
  G2.standDowns = list;
  G2.state = 'STANDDOWN';
}
/** The destination instance's authored-layer poster canvas at `rect` (authored px). */
function posterLayer(rect, opts) {
  const m = P.stageMap();
  const o = opts || {};
  let reads = 0;
  const parent = {
    __screenOrigin: {x: m.ox, y: m.oy}, __scale: m.s,
    insertBefore(node) {
      node.parentNode = this; node.__inStage = true;
      if (!o.misplace) node.previousSibling = canvas;
    },
    appendChild(node) { node.parentNode = this; node.__inStage = true; },
    removeChild(node) { node.parentNode = null; node.__inStage = false; node.previousSibling = null; },
  };
  const canvas = {
    id: '935F-canvas', parentNode: parent, nextSibling: null,
    getBoundingClientRect() {
      reads += 1;
      if (o.throwOnRead && reads >= o.throwOnRead) throw new Error('layout gone');
      return screenOf(rect);
    },
  };
  canvases.push(canvas);
  return canvas;
}
/** `beginMove`'s flag is cleared on the next macrotask; the harness never runs timers. */
function settleMoves() { videos.forEach((v) => { v.__obedRemounting = false; }); }
function census(v) {
  return {
    elId: v.__obedElId, paused: v.paused, inDocument: document.contains(v), gen: v.__obedGen,
    pooled: P.snapshot().some(x => !x.fromDom && x.elId === v.__obedElId),
    preserved: v.dataset.obedPreserved || null, remounted: v.dataset.obedRemounted || null,
    glPooled: !!v.__obedGlPooled, src: v.src || '',
  };
}
function zones() {
  return P.events.filter(e => e.kind === 'glreplay-zone')
    .map(e => [e.detail.from, e.detail.to, e.detail.reason, e.detail.sceneHash]);
}
function notesOf(kind) { return P.events.filter(e => e.kind === kind).map(e => e.detail); }
function kinds() { return P.events.map(e => e.kind); }
"""


def _gl_after_core(module: dict | None, *, loaded: bool = True) -> str:
    seed = "" if module is None else f"window.__OBED_GL_REPLAY__ = {json.dumps(module)};\n"
    return seed + (_LOADED if loaded else "")


def _gl_prelude(*, instance: dict = _GL_INSTANCE, measured: dict = _GL_MEASURED) -> str:
    return (
        _GL_PRELUDE.replace("__INSTANCE__", json.dumps(instance))
        .replace("__MEASURED__", json.dumps(measured))
        .replace("__SIBLING__", json.dumps(_GL_SIBLING))
        .replace("__SLOT__", json.dumps(_GL_SLOT))
    )


def _run_gl(
    script: str,
    *,
    stage: dict = _IDENTITY_STAGE,
    plan: dict = _GL_PLAN,
    module: dict | None = _G2_ARMING,
    loaded: bool = True,
    instance: dict = _GL_INSTANCE,
    measured: dict = _GL_MEASURED,
) -> dict:
    return _run_full_core_in_node(
        plan=plan, stage=stage,
        script=_gl_prelude(instance=instance, measured=measured) + script,
        after_core=_gl_after_core(module, loaded=loaded),
    )


def _screen(rect: dict, stage: dict) -> dict:
    s, ox, oy = stage["s"], stage["ox"], stage["oy"]
    return {"x": rect["x"] * s + ox, "y": rect["y"] * s + oy, "w": rect["w"] * s, "h": rect["h"] * s}


# --- seam shape, flag-off ---


def test_gl_seam_carries_exactly_the_g2_members():
    result = _run_gl(r"""
console.log(JSON.stringify({keys: Object.keys(S).sort(), version: S.version, inPage: P.version}));
""")
    assert result == {
        "keys": ["carried", "movieKeyOf", "note", "release", "setKeepWarm", "version"],
        "version": 1,
        "inPage": 8,
    }


@pytest.mark.parametrize(
    "plan", [_RETIRE_PLAN, _NO_RETIRE_PLAN, _MOVIE_PLAN], ids=["retire", "no-retire", "movie-only"],
)
def test_flag_off_plans_install_no_gl_seam_and_note_no_zone(plan):
    """Control: without a `glReplay` entry the preserve object keeps today's
    shape and nothing zone-related is ever noted."""
    result = _run_full_core_in_node(plan=plan, stage=_IDENTITY_STAGE, script=_detach_script(scene=1) + r"""
tick();
console.log(JSON.stringify({
  hasSeam: 'glReplay' in P,
  zoneNotes: P.events.filter(e => e.kind.indexOf('glreplay-') === 0).length,
}));
""")
    assert result == {"hasSeam": False, "zoneNotes": 0}


def test_movie_key_of_reads_the_stamp_after_a_real_clear():
    result = _run_gl(r"""
const v = makeMovie(MEASURED);
const before = S.movieKeyOf(v);
const other = S.movieKeyOf(makeMovie(SIBLING, 'https://host/WA0125.mov'));
console.log(JSON.stringify({before, other, none: S.movieKeyOf(null)}));
""")
    assert result == {"before": "movie1", "other": "movie2", "none": None}


# --- pending resolution (K17 readyState, module checks) ---


def test_pending_resolves_to_armed_at_the_first_consult_after_load():
    result = _run_gl(r"""
const before = zones();
tick();
console.log(JSON.stringify({before, after: zones()}));
""")
    assert result["before"] == []
    assert result["after"] == [["pending", "armed", "moduleReady", "#1"]]


def test_a_consult_while_loading_stays_pending_and_is_retire_class():
    """K17: every inline script (plan < core < module) runs before `readyState`
    leaves `loading`. A consult then stays pending, which refuses like retire."""
    result = _run_gl(r"""
location.hash = '#1';
const v = makeMovie(MEASURED);
tick();
playerDetach(v);
const carried = S.carried('movie1');
const whileLoading = {zones: zones(), pooled: census(v).pooled, carried: carried.reason,
  refusals: notesOf('preserve-refused').map(d => d.via)};
document.readyState = 'interactive';
tick();
console.log(JSON.stringify({whileLoading, afterLoad: zones()}));
""", loaded=False)
    assert result["whileLoading"] == {
        "zones": [], "pooled": False, "carried": "notArmed", "refusals": ["stash"],
    }
    assert result["afterLoad"] == [["pending", "armed", "moduleReady", "#1"]]


@pytest.mark.parametrize(
    "module,plan,reason",
    [
        (None, _GL_PLAN, "moduleAbsent"),
        ({"version": 2, "state": "IDLE", "standDowns": []}, _GL_PLAN, "moduleVersion"),
        ({"version": 1, "state": "RETIRED", "standDowns": ["planUnreadable"]}, _GL_PLAN, "moduleRetired"),
        (_G2_ARMING, {**_GL_PLAN, "boundaries": [{**_GL_ENTRY, "fallback": "hold"}] + _GL_PLAN["boundaries"][1:]},
         "entryInvalid"),
        (_G2_ARMING, {**_GL_PLAN, "boundaries": [{**_GL_ENTRY, "instanceRect": {**_GL_INSTANCE, "w": 0}}]
                      + _GL_PLAN["boundaries"][1:]}, "entryInvalid"),
        (_G2_ARMING, {**_GL_PLAN, "boundaries": [{k: v for k, v in _GL_ENTRY.items() if k != "instanceRect"}]
                      + _GL_PLAN["boundaries"][1:]}, "entryInvalid"),
    ],
    ids=["module-absent", "module-version-2", "module-retired", "fallback-not-retire", "zero-width-rect",
         "no-instance-rect"],
)
def test_pending_falls_back_to_retire_when_the_module_or_entry_is_unusable(module, plan, reason):
    result = _run_gl(r"""
const ctx = arm();
console.log(JSON.stringify({zones: zones(), big: census(ctx.big), carried: S.carried('movie1').reason,
  refusals: notesOf('preserve-refused').map(d => d.via)}));
""", module=module, plan=plan)
    assert result["zones"] == [["pending", "retired", reason, "#1"]]
    assert result["big"]["pooled"] is False
    assert result["carried"] == "notArmed"
    assert "stash" in result["refusals"]


def test_entry_naming_an_unplanned_movie_is_invalid():
    plan = {**_GL_PLAN, "boundaries": [{**_GL_ENTRY, "movieKey": "movie9"}] + _GL_PLAN["boundaries"][1:]}
    result = _run_gl("tick();\nconsole.log(JSON.stringify(zones()));\n", plan=plan)
    assert result == [["pending", "retired", "entryInvalid", "#1"]]


# --- armed call sites (§1 rows 1-8) ---


def test_armed_pools_the_detached_move_scene_decoders_but_never_mounts_them():
    """Rows 1-2: both same-asset decoders detached on the move scene are pooled
    and stamped; the detach remount is held (no epoch, no timers, no hashchange
    listener), one `glreplay-hold` per key+via, never `preserve-refused`."""
    result = _run_gl(r"""
const ctx = arm();
console.log(JSON.stringify({
  big: census(ctx.big), sib: census(ctx.sib),
  epochs: [ctx.big.__obedRemountEpoch === undefined, ctx.sib.__obedRemountEpoch === undefined],
  hashListeners: hashListeners.length,
  holds: notesOf('glreplay-hold'),
  remounts: kinds().filter(k => k.indexOf('remount-') === 0),
  refusals: notesOf('preserve-refused'),
}));
""")
    for who in ("big", "sib"):
        assert result[who]["pooled"] is True
        assert result[who]["glPooled"] is True
        assert result[who]["inDocument"] is False
        assert result[who]["remounted"] is None
        assert result[who]["paused"] is False
    assert result["epochs"] == [True, True]
    assert result["hashListeners"] == 0
    assert result["holds"] == [{"key": "movie1", "via": "remount", "sceneHash": "#1"}]
    assert result["remounts"] == []
    assert result["refusals"] == []


@pytest.mark.parametrize("case", ["still-attached-on-move-scene", "detached-on-destination"])
def test_armed_stash_declines_an_attached_or_off_scene_decoder(case):
    script = {
        "still-attached-on-move-scene": r"""
location.hash = '#1';
tick();
const v = makeMovie(MEASURED);
moCallbacks.slice().forEach((cb) => cb([{removedNodes: [v]}]));
""",
        "detached-on-destination": r"""
arm();
location.hash = '#2';
const v = makeMovie(MEASURED);
playerDetach(v);
""",
    }[case] + r"""
console.log(JSON.stringify({v: census(v), zoneTo: zones().map(z => z[1]),
  refusals: notesOf('preserve-refused').map(d => d.via)}));
"""
    result = _run_gl(script)
    assert result["v"]["pooled"] is False
    assert result["v"]["glPooled"] is False
    assert result["zoneTo"] == ["armed"]
    assert result["refusals"] == ["stash"]


def test_armed_remount_is_held_for_every_caller():
    """Row 3: `remountAll` (and so every timer and `onHash` retry, which call
    the same `tryRemount`) is held while armed — including a decoder pooled
    under pin on the scene before, whose timers were created before the zone."""
    result = _run_gl(r"""
location.hash = '#0';
const early = makeMovie(MEASURED);
tick();
early.__styleAttr = '';
playerDetach(early);
const ctx = arm();
const before = {big: JSON.stringify(ctx.big.style), sib: JSON.stringify(ctx.sib.style)};
const eventsBefore = P.events.length;
P.remountAll();
console.log(JSON.stringify({
  bigUntouched: JSON.stringify(ctx.big.style) === before.big,
  sibUntouched: JSON.stringify(ctx.sib.style) === before.sib,
  inDocument: [document.contains(ctx.big), document.contains(ctx.sib)],
  newRemounts: P.events.slice(eventsBefore).filter(e => e.kind.indexOf('remount-') === 0).length,
  holds: notesOf('glreplay-hold').map(d => d.via),
}));
""")
    assert result["bigUntouched"] is True
    assert result["sibUntouched"] is True
    assert result["inDocument"] == [False, False]
    assert result["newRemounts"] == 0
    assert result["holds"] == ["remount"]


@pytest.mark.parametrize("via", ["src-clear", "removeAttribute"])
def test_armed_src_clear_on_an_attached_decoder_really_clears(via):
    """K12(a): at `atScene - 1` an ATTACHED element's clear is never swallowed
    (a swallow would `play()` it where the player wanted it blank)."""
    clear = "v.src = '';" if via == "src-clear" else "v.removeAttribute('src');"
    result = _run_gl(r"""
location.hash = '#1';
tick();
const v = makeMovie(MEASURED);
__CLEAR__
console.log(JSON.stringify({v: census(v), refusals: notesOf('preserve-refused').map(d => d.via),
  holds: notesOf('glreplay-hold').length}));
""".replace("__CLEAR__", clear))
    assert result["v"]["src"] == ""
    assert result["v"]["pooled"] is False
    assert result["refusals"] == [via]
    assert result["holds"] == 0


@pytest.mark.parametrize("via", ["src-clear", "removeAttribute"])
def test_armed_src_clear_on_an_armed_pooled_decoder_is_swallowed_on_the_destination(via):
    """K12(b): a real clear on the carried decoder while LIVE would kill G2's
    source silently; it is held at any in-zone scene."""
    clear = "ctx.big.src = '';" if via == "src-clear" else "ctx.big.removeAttribute('src');"
    result = _run_gl(r"""
const ctx = arm();
location.hash = '#2';
__CLEAR__
console.log(JSON.stringify({big: census(ctx.big), holds: notesOf('glreplay-hold').map(d => d.via),
  refusals: notesOf('preserve-refused').length}));
""".replace("__CLEAR__", clear))
    assert result["big"]["src"] == "https://host/untitled.mov"
    assert result["big"]["pooled"] is True
    assert result["holds"] == ["remount", via]
    assert result["refusals"] == 0


@pytest.mark.parametrize("via", ["src-clear", "removeAttribute"])
def test_armed_src_clear_on_a_detached_move_scene_decoder_stashes_and_swallows(via):
    """Arming §3: a clear on a detached element on the move scene is the
    `stash` + swallow path, and the decoder is pooled armed."""
    clear = "v.src = '';" if via == "src-clear" else "v.removeAttribute('src');"
    result = _run_gl(r"""
location.hash = '#1';
tick();
const v = makeMovie(MEASURED);
v.parentNode = null;
__CLEAR__
console.log(JSON.stringify({v: census(v), refusals: notesOf('preserve-refused').length}));
""".replace("__CLEAR__", clear))
    assert result["v"]["src"] == "https://host/untitled.mov"
    assert result["v"]["pooled"] is True
    assert result["v"]["glPooled"] is True
    assert result["refusals"] == 0


def test_armed_create_element_is_raw_and_leaves_the_pool_untouched():
    """Row 6: no facade, no reuse, no retire-on-start; the fresh element's own
    `setAttribute('src')` reaches it."""
    result = _run_gl(r"""
const ctx = arm();
location.hash = '#2';
const fresh = document.createElement('video');
fresh.setAttribute('src', 'https://host/untitled.mov');
console.log(JSON.stringify({
  facade: fresh.dataset.obedFacade || null,
  reuse: kinds().filter(k => k === 'reuse-decoder' || k === 'bridge-3to4' || k === 'retire-on-start-movie'),
  pooled: [census(ctx.big).pooled, census(ctx.sib).pooled],
  holds: notesOf('glreplay-hold').map(d => d.via),
}));
""")
    assert result["facade"] is None
    assert result["reuse"] == []
    assert result["pooled"] == [True, True]
    assert result["holds"] == ["remount", "reuse"]


def test_armed_interval_neither_retires_nor_notes_a_boundary():
    """Row 7: transitions live in `zoneState()`; the armed sweep retires nothing."""
    result = _run_gl(r"""
const ctx = arm();
tick();
location.hash = '#2';
tick();
console.log(JSON.stringify({big: census(ctx.big), sib: census(ctx.sib),
  retire: notesOf('retire-boundary').length, zones: zones().length}));
""")
    assert result["retire"] == 0
    assert result["zones"] == 1
    assert result["big"]["pooled"] is True and result["big"]["paused"] is False
    assert result["sib"]["pooled"] is True and result["sib"]["paused"] is False


def test_keep_warm_skips_only_the_carried_decoder_while_suspended():
    """Row 8 + `setKeepWarm`: honoured only for the memoised carried decoder."""
    result = _run_gl(r"""
const ctx = arm();
S.carried('movie1');
ctx.big.pause(); ctx.sib.pause();
S.setKeepWarm(ctx.big, false);
S.setKeepWarm(ctx.sib, false);
tick();
const suspended = {big: ctx.big.paused, sib: ctx.sib.paused};
S.setKeepWarm(ctx.big, true);
tick();
console.log(JSON.stringify({suspended, resumed: ctx.big.paused}));
""")
    assert result == {"suspended": {"big": True, "sib": False}, "resumed": False}


# --- instance selection (§2) ---


@pytest.mark.parametrize(
    "stage", [_IDENTITY_STAGE, _SCALED_STAGE, _LETTERBOXED_STAGE], ids=["identity", "scaled", "letterboxed"],
)
def test_carried_binds_the_measured_instance_after_the_detach_zeroed_its_screen_rect(stage):
    """The detach capture overwrites `__obedRect` with the removed parent's
    origin (F3); `__obedAuthoredRect` is written only from the element's own
    attached box and survives it, so the big instance binds at every stage."""
    result = _run_gl(r"""
const ctx = arm();
const first = S.carried('movie1');
const second = S.carried('movie1');
console.log(JSON.stringify({
  bigRect: ctx.big.__obedRect,
  isBig: first.video === ctx.big, reason: first.reason, memo: second.video === ctx.big,
  stamped: !!ctx.big.__obedGlCarried, memoArmedPooled: ctx.big.__obedGlPooled === true,
  carriedNotes: notesOf('glreplay-carried'),
  bigId: ctx.big.__obedElId, sibId: ctx.sib.__obedElId,
}));
""", stage=stage)
    assert (result["bigRect"]["x"], result["bigRect"]["y"]) == (0, 0)
    assert result["isBig"] is True
    assert result["reason"] is None
    assert result["memo"] is True
    assert result["stamped"] is True
    assert result["memoArmedPooled"] is True
    [note] = result["carriedNotes"]
    assert note["elId"] == result["bigId"]
    assert note["delta"] == pytest.approx(0.0121, abs=1e-6)
    assert note["delta"] <= 0.02
    cands = {c["elId"]: c["rect"] for c in note["candidates"]}
    assert set(cands) == {result["bigId"], result["sibId"]}
    assert cands[result["bigId"]] == pytest.approx(_GL_MEASURED)
    assert cands[result["sibId"]] == pytest.approx(_GL_SIBLING)


#: The only rect-matching decoder, pooled armed, then made ineligible (review A7).
_ONLY_MATCH = r"""
location.hash = '#1';
const v = makeMovie(MEASURED);
tick();
playerDetach(v);
if (!v.__obedGlPooled) throw new Error('not pooled armed');
__MUTATE__
const r = S.carried('movie1');"""
_ONLY_MATCH_MUTATIONS = {
    "attached": "v.parentNode = bodyEl;",
    "ended": "v.ended = true;",
    "stale-generation": "v.__obedGen = -2;",
    "remounted": "v.dataset.obedRemounted = '1';",
    "not-armed-pooled": "v.__obedGlPooled = false;",
    "is-a-facade": "v.__obedFacadeFor = makeMovie(SIBLING);",
}


@pytest.mark.parametrize(
    "case,reason",
    [
        ("nothing-pooled", "notPooled"),
        ("never-measured", "unmeasured"),
        ("parent-box-only", "unmeasured"),
        ("lone-sibling", "ambiguous"),
        ("two-at-the-instance", "ambiguous"),
        ("unmeasured-does-not-block", None),
        ("wrong-movie", "notArmed"),
        ("disabled", "disabled"),
        ("only-match-attached", "notPooled"),
        ("only-match-ended", "notPooled"),
        ("only-match-stale-generation", "notPooled"),
        ("only-match-remounted", "notPooled"),
        ("only-match-not-armed-pooled", "notPooled"),
        ("only-match-is-a-facade", "notPooled"),
    ],
)
def test_carried_fails_closed_and_never_binds_the_only_video(case, reason):
    script = {
        "nothing-pooled": "location.hash = '#1'; tick(); const r = S.carried('movie1');",
        "never-measured": r"""
location.hash = '#1';
const v = makeMovie(MEASURED);
playerDetach(v);
const r = S.carried('movie1');""",
        "parent-box-only": r"""
location.hash = '#1';
const v = makeMovie(MEASURED);
v._rect = {left: 0, top: 0, width: 0, height: 0};
v.parentElement = {getBoundingClientRect: () => screenOf(MEASURED), parentElement: null};
tick();
v.parentElement = null;
playerDetach(v);
const r = S.carried('movie1');
if (!(v.__obedRect && v.__obedRect.w > 1)) throw new Error('the parent walk never captured');""",
        "lone-sibling": r"""
location.hash = '#1';
const v = makeMovie(SIBLING);
tick();
playerDetach(v);
const r = S.carried('movie1');""",
        "two-at-the-instance": r"""
location.hash = '#1';
const a = makeMovie(MEASURED), b = makeMovie(INSTANCE);
tick();
playerDetach(a); playerDetach(b);
const r = S.carried('movie1');""",
        "unmeasured-does-not-block": r"""
location.hash = '#1';
const a = makeMovie(MEASURED);
tick();
const late = makeMovie(MEASURED);
playerDetach(a); playerDetach(late);
const r = S.carried('movie1');
if (r.video !== a) throw new Error('bound the wrong decoder');""",
        "wrong-movie": "const ctx = arm(); const r = S.carried('movie2');",
        **{f"only-match-{k}": _ONLY_MATCH.replace("__MUTATE__", m) for k, m in _ONLY_MATCH_MUTATIONS.items()},
        "disabled": "P.disable(); const r = S.carried('movie1');",
    }[case] + "\nconsole.log(JSON.stringify({reason: r.reason, bound: !!r.video}));\n"
    result = _run_gl(script)
    assert result == {"reason": reason, "bound": reason is None}


# --- release (§2 table) ---


@pytest.mark.parametrize("stage", [_IDENTITY_STAGE, _LETTERBOXED_STAGE], ids=["identity", "letterboxed"])
def test_release_hands_off_into_the_authored_layer_at_the_mapped_instance_rect(stage):
    """Row 10 (A2 option (a)): siblings retired, `__obedRect =
    toScreen(instanceRect)` — G2's slot rect is validated (row 7), never used
    for placement — so the DOM movie sits in its authored frame from build 1,
    where the hand-off `keepAtFootprint` loop then holds it. No footprint
    fallback, remounted next to the pre-checked canvas, zone `released`."""
    result = _run_gl(r"""
const ctx = arm();
goLive();
const canvas = posterLayer(SLOT);
standDown(['canvasRemoved']);
const parentBefore = ctx.big.__obedParent === ctx.bigLayer;
const out = S.release('movie1', {rect: SLOT});
console.log(JSON.stringify({
  out, zones: zones(), big: census(ctx.big), sib: census(ctx.sib), parentBefore,
  parentAfterIsNull: ctx.big.__obedParent === null,
  bigId: ctx.big.__obedElId, sibId: ctx.sib.__obedElId,
  landed: ctx.big.parentNode === canvas.parentNode && ctx.big.previousSibling === canvas,
  rect: ctx.big.__obedRect, parentGuard: ctx.big.__obedParent,
  rendered: ctx.big.getBoundingClientRect(),
  styleSize: [parseFloat(ctx.big.style.width), parseFloat(ctx.big.style.height)],
  remounts: P.events.filter(e => e.kind.indexOf('remount-') === 0).map(e => [e.kind, e.detail.rect || null]),
  releaseNotes: notesOf('glreplay-release'),
  retire: notesOf('retire-boundary').length,
}));
""", stage=stage)
    screen = _screen(_GL_INSTANCE, stage)
    assert result["styleSize"] == pytest.approx([_GL_INSTANCE["w"], _GL_INSTANCE["h"]])
    assert result["out"] == {
        "ok": True, "reason": None, "mode": "handoff", "elId": result["bigId"], "retired": [result["sibId"]],
    }
    assert result["zones"] == [["pending", "armed", "moduleReady", "#1"], ["armed", "released", "handoff", "#2"]]
    assert result["landed"] is True
    assert result["rect"] == pytest.approx(screen)
    assert result["parentGuard"] is None
    assert result["parentBefore"] is True
    assert result["parentAfterIsNull"] is True
    assert result["rendered"] == pytest.approx(
        {"left": screen["x"], "top": screen["y"], "width": screen["w"], "height": screen["h"]}
    )
    assert [k for k, _ in result["remounts"]] == ["remount-into-authored-layer"]
    assert result["remounts"][0][1] == pytest.approx(screen)
    assert result["big"]["inDocument"] is True
    assert result["big"]["paused"] is False
    assert result["big"]["remounted"] == "1"
    assert result["sib"] == {**result["sib"], "paused": True, "inDocument": False, "gen": -1, "pooled": False}
    assert result["retire"] == 0
    [note] = result["releaseNotes"]
    assert {k: v for k, v in note.items() if k != "sceneHash"} == result["out"]


def test_release_rows_1_to_3_answer_without_side_effects():
    result = _run_gl(r"""
const ctx = arm();
goLive();
posterLayer(SLOT);
standDown(['canvasRemoved']);
const zonesBefore = zones().length;
const unknown = S.release('movie2', {rect: SLOT});
const afterUnknown = {zones: zones().length, big: census(ctx.big), sib: census(ctx.sib)};
const first = S.release('movie1', {rect: SLOT});
const second = S.release('movie1', {rect: SLOT});
console.log(JSON.stringify({zonesBefore, unknown, afterUnknown, first: first.mode, second}));
""")
    assert result["unknown"] == {"ok": False, "reason": "unknownMovie", "mode": None, "elId": None, "retired": []}
    assert result["afterUnknown"]["zones"] == result["zonesBefore"]
    assert result["afterUnknown"]["big"]["pooled"] is True
    assert result["afterUnknown"]["sib"]["pooled"] is True
    assert result["first"] == "handoff"
    assert result["second"] == {"ok": False, "reason": "notArmed", "mode": None, "elId": None, "retired": []}


def test_release_after_disable_answers_disabled():
    result = _run_gl(r"""
P.disable();
standDown(['canvasRemoved']);
console.log(JSON.stringify(S.release('movie1', {rect: SLOT})));
""")
    assert result == {"ok": False, "reason": "disabled", "mode": None, "elId": None, "retired": []}


def _assert_retired_like_today(result: dict, reason: str, **extra) -> None:
    assert result["out"]["ok"] is True
    assert result["out"]["mode"] == "retire"
    assert result["out"]["reason"] == reason
    zone = result["lastZone"]
    assert (zone["from"], zone["to"], zone["reason"]) == ("armed", "retired", reason)
    for k, v in extra.items():
        assert zone[k] == v
    for who in ("big", "sib"):
        c = result[who]
        assert (c["paused"], c["inDocument"], c["gen"], c["pooled"]) == (True, False, -1, False), (who, c)
    assert sorted(result["out"]["retired"]) == sorted([result["big"]["elId"], result["sib"]["elId"]])


_RELEASE_REPORT = r"""
console.log(JSON.stringify({
  out, big: census(ctx.big), sib: census(ctx.sib),
  lastZone: notesOf('glreplay-zone').slice(-1)[0],
}));
"""


@pytest.mark.parametrize("reason", [r for r in _G2_FAILURES if r != "writebackFailed"])
def test_release_retires_on_every_primary_failure(reason):
    """Row 4 (OD-1 default): any primary stand-down other than `canvasRemoved`
    — the LAST element of the module's real `standDowns` — retires, even LIVE."""
    result = _run_gl(r"""
const ctx = arm();
goLive();
posterLayer(SLOT);
standDown(['__REASON__']);
const out = S.release('movie1', {rect: SLOT});
""".replace("__REASON__", reason) + _RELEASE_REPORT)
    _assert_retired_like_today(result, "failure", standDown=reason)


@pytest.mark.parametrize(
    "stand_downs,expected",
    [
        (["writebackFailed", "contextLost"], ("failure", "contextLost")),
        (["writebackFailed", "canvasRemoved"], ("handoff", None)),
        ([], ("failure", None)),
        (None, ("failure", None)),
    ],
    ids=["writeback-then-contextLost", "writeback-then-canvasRemoved", "empty", "unreadable"],
)
def test_release_reads_the_primary_as_the_last_stand_down(stand_downs, expected):
    result = _run_gl(r"""
const ctx = arm();
goLive();
posterLayer(SLOT);
standDown(__LIST__);
const out = S.release('movie1', {rect: SLOT});
""".replace("__LIST__", json.dumps(stand_downs)) + _RELEASE_REPORT)
    mode, stand_down = expected
    if mode == "handoff":
        assert result["out"]["mode"] == "handoff"
    else:
        _assert_retired_like_today(result, "failure", standDown=stand_down)


@pytest.mark.parametrize("scene", [1, 2])
def test_release_retires_a_canvas_removed_that_never_went_live(scene):
    """Row 4b (K2): `canvasRemoved` fires in any phase once the canvas is set,
    and a forced one fires at the first tick, before LIVE."""
    result = _run_gl(r"""
const ctx = arm();
S.carried('movie1');
location.hash = '#__SCENE__';
posterLayer(SLOT);
standDown(['canvasRemoved']);
const out = S.release('movie1', {rect: SLOT});
""".replace("__SCENE__", str(scene)) + _RELEASE_REPORT)
    _assert_retired_like_today(result, "notLive")


def test_release_off_the_destination_retires():
    """Row 5: a go-to back off the destination during LIVE (`hn < atScene`)."""
    result = _run_gl(r"""
const ctx = arm();
goLive();
location.hash = '#1';
posterLayer(SLOT);
standDown(['canvasRemoved']);
const out = S.release('movie1', {rect: SLOT});
""" + _RELEASE_REPORT)
    _assert_retired_like_today(result, "notOnDestination")


def test_release_past_the_zone_end_finds_the_zone_already_retired():
    """A3: at `hn >= retireZoneEnd` the armed watchdog retires the zone
    (`leftDestination`) before `release` reads its rows, so row 5's upper
    bound is reached through the watchdog and `release` answers `notArmed`.
    Out of the zone only the armed-pooled decoders and the memo are retired."""
    result = _run_gl(r"""
const ctx = arm();
goLive();
location.hash = '#6';
posterLayer(SLOT);
standDown(['canvasRemoved']);
const out = S.release('movie1', {rect: SLOT});
console.log(JSON.stringify({out, zone: zones().slice(-1)[0], big: census(ctx.big), sib: census(ctx.sib),
  retired: notesOf('retire-boundary').map(x => x.elIds)}));
""")
    assert result["out"] == {"ok": False, "reason": "notArmed", "mode": None, "elId": None, "retired": []}
    assert result["zone"] == ["armed", "retired", "leftDestination", "#6"]
    assert result["retired"] == [[result["big"]["elId"], result["sib"]["elId"]]]
    for who in ("big", "sib"):
        assert (result[who]["paused"], result[who]["gen"], result[who]["pooled"]) == (True, -1, False)


@pytest.mark.parametrize(
    "mutate,reason",
    [
        ("", "noCarried"),
        ("S.carried('movie1'); ctx.big.__obedGen = 99;", "noCarried"),
        ("S.carried('movie1'); ctx.big.ended = true;", "ended"),
        ("S.carried('movie1'); ctx.big.readyState = 1;", "noCarried"),
        ("S.carried('movie1'); srcStore.set(ctx.big, '');", "noCarried"),
    ],
    ids=["no-memo", "stale-memo", "ended", "not-ready", "empty-src"],
)
def test_release_without_a_live_carried_decoder_retires(mutate, reason):
    """Row 6 (+K12(b): an empty-src memo would hand off an empty <video>)."""
    result = _run_gl(r"""
const ctx = arm();
__MUTATE__
S.note('glreplay-live', {});
location.hash = '#2';
posterLayer(SLOT);
standDown(['canvasRemoved']);
const out = S.release('movie1', {rect: SLOT});
console.log(JSON.stringify({out, zone: notesOf('glreplay-zone').slice(-1)[0],
  sib: census(ctx.sib), big: census(ctx.big)}));
""".replace("__MUTATE__", mutate))
    assert result["out"]["mode"] == "retire"
    assert result["out"]["reason"] == reason
    assert (result["zone"]["from"], result["zone"]["to"], result["zone"]["reason"]) == ("armed", "retired", reason)
    assert result["sib"]["paused"] is True and result["sib"]["inDocument"] is False
    assert result["big"]["inDocument"] is False


_BAD_RECTS = {
    "null": None,
    "nan": {**_GL_SLOT, "x": float("nan")},
    "width-1": {**_GL_SLOT, "w": 1},
    "misses-the-instance": {**_GL_SLOT, "x": _GL_SLOT["x"] + 5},
    "margin-over-8": {"x": _GL_INSTANCE["x"] - 9, "y": _GL_SLOT["y"], "w": _GL_SLOT["w"] + 18, "h": _GL_SLOT["h"]},
}


@pytest.mark.parametrize("label", list(_BAD_RECTS))
def test_release_with_a_bad_rect_retires(label):
    rect = _BAD_RECTS[label]
    rect_js = "null" if rect is None else json.dumps(rect)
    result = _run_gl(r"""
const ctx = arm();
goLive();
posterLayer(SLOT);
standDown(['canvasRemoved']);
const out = S.release('movie1', {rect: __RECT__});
""".replace("__RECT__", rect_js) + _RELEASE_REPORT)
    _assert_retired_like_today(result, "badRect")


@pytest.mark.parametrize("stage", [_IDENTITY_STAGE, _LETTERBOXED_STAGE], ids=["near-zero", "near-stage-origin"])
def test_release_rect_that_would_take_the_footprint_fallback_retires(stage):
    """Row 7 near-origin guard: a hand-off rect `tryRemount` would read as
    unpositioned is refused before the fallback can engage. Both cases trip
    `nearStageOrigin`: the `nearZero` leg mirrors `tryRemount`'s own test and is
    implied by it at identity, and unreachable letterboxed while the rect must
    contain `instanceRect` (review A10) — kept, not separately testable."""
    at_origin = {"x": 1, "y": 1, "w": 100, "h": 50}
    result = _run_gl(r"""
const ctx = arm();
goLive();
posterLayer({x: 0.5, y: 0.5, w: 101, h: 51});
standDown(['canvasRemoved']);
const out = S.release('movie1', {rect: {x: 0.5, y: 0.5, w: 101, h: 51}});
""" + _RELEASE_REPORT, stage=stage,
        plan={**_GL_PLAN, "boundaries": [{**_GL_ENTRY, "instanceRect": at_origin}] + _GL_PLAN["boundaries"][1:]},
        instance=at_origin, measured=at_origin)
    _assert_retired_like_today(result, "badRect")


def test_release_without_a_stage_map_retires():
    result = _run_gl(r"""
const ctx = arm();
goLive();
posterLayer(SLOT);
standDown(['canvasRemoved']);
stageEl.offsetWidth = 0;
const out = S.release('movie1', {rect: SLOT});
""" + _RELEASE_REPORT)
    _assert_retired_like_today(result, "noStageMap")


def test_release_without_the_authored_layer_retires_instead_of_a_top_z_append():
    """Row 9: the hand-off lands in the authored layer or not at all."""
    result = _run_gl(r"""
const ctx = arm();
goLive();
standDown(['canvasRemoved']);
const out = S.release('movie1', {rect: SLOT});
console.log(JSON.stringify({
  out, big: census(ctx.big), sib: census(ctx.sib), lastZone: notesOf('glreplay-zone').slice(-1)[0],
  remounts: kinds().filter(k => k.indexOf('remount-') === 0),
}));
""")
    _assert_retired_like_today(result, "noAuthoredLayer")
    assert result["remounts"] == []


def test_release_whose_remount_does_not_land_retires_the_carried_decoder():
    """Row 10 landing check: the remount did not end next to the pre-checked
    canvas ⇒ `remountFailed`, and the released memo is retired too."""
    result = _run_gl(r"""
const ctx = arm();
goLive();
posterLayer(SLOT, {misplace: true});
standDown(['canvasRemoved']);
const out = S.release('movie1', {rect: SLOT});
console.log(JSON.stringify({out, zones: zones().map(z => z.slice(0, 3)), big: census(ctx.big),
  sib: census(ctx.sib)}));
""")
    assert result["out"]["mode"] == "retire"
    assert result["out"]["reason"] == "remountFailed"
    assert sorted(result["out"]["retired"]) == sorted([result["big"]["elId"], result["sib"]["elId"]])
    assert result["zones"][-2:] == [["armed", "released", "handoff"], ["released", "retired", "remountFailed"]]
    assert (result["big"]["paused"], result["big"]["inDocument"], result["big"]["gen"]) == (True, False, -1)


def test_release_that_throws_after_the_checks_retires_release_error():
    """K13: `tryRemount` itself throws inside `release` (the canvas's layout
    read fails on its second call, i.e. inside `tryRemount`'s own lookup)."""
    result = _run_gl(r"""
const ctx = arm();
goLive();
posterLayer(SLOT, {throwOnRead: 2});
standDown(['canvasRemoved']);
let threw = null, out = null;
try { out = S.release('movie1', {rect: SLOT}); } catch (e) { threw = String(e); }
console.log(JSON.stringify({threw, out, zones: zones().map(z => z.slice(0, 3)), big: census(ctx.big),
  lastZone: notesOf('glreplay-zone').slice(-1)[0]}));
""")
    assert result["threw"] is None
    assert result["out"]["ok"] is True
    assert result["out"]["mode"] == "retire"
    assert result["out"]["reason"] == "releaseError"
    assert result["zones"][-1] == ["released", "retired", "releaseError"]
    assert result["lastZone"]["message"] == "layout gone"
    assert (result["big"]["paused"], result["big"]["inDocument"], result["big"]["gen"]) == (True, False, -1)


def test_release_decides_by_its_own_rows_not_the_module_retired_watchdog():
    """§1: `release` evaluates `zoneState()` WITHOUT the `moduleRetired`
    watchdog (the module only goes RETIRED after `release` returns). Forced
    here by a module that already reads RETIRED: the answer must still be the
    row-4 decision, attributed to the module's own primary reason."""
    result = _run_gl(r"""
const ctx = arm();
goLive();
posterLayer(SLOT);
standDown(['glError']);
G2.state = 'RETIRED';
const out = S.release('movie1', {rect: SLOT});
""" + _RELEASE_REPORT)
    _assert_retired_like_today(result, "failure", standDown="glError")


def test_release_during_pending_resolves_the_zone_first():
    """K13: with no consult since load, `release` must resolve `pending`
    first — a `notArmed` answer here would let the zone arm later."""
    result = _run_gl(r"""
standDown(['assetUnbound']);
const out = S.release('movie1', {rect: SLOT});
console.log(JSON.stringify({out, zones: zones().map(z => z.slice(0, 3))}));
""")
    assert result["out"] == {"ok": True, "reason": "failure", "mode": "retire", "elId": None, "retired": []}
    assert result["zones"] == [["pending", "armed", "moduleReady"], ["armed", "retired", "failure"]]


# --- watchdogs and later transitions (§1) ---


@pytest.mark.parametrize("released_first", [False, True], ids=["release-never-called", "release-left-it-armed"])
def test_module_retired_while_armed_retires_the_zone(released_first):
    """K13: `moduleRetired` fires whether or not `release` was ever called —
    here a `release` that answered without deciding left the zone armed."""
    result = _run_gl(r"""
const ctx = arm();
goLive();
const answered = __RELEASE__;
const zonesBefore = zones().length;
G2.state = 'RETIRED';
tick();
console.log(JSON.stringify({answered, zonesBefore, zone: zones().slice(-1)[0], big: census(ctx.big),
  sib: census(ctx.sib), retired: notesOf('retire-boundary').map(x => x.elIds)}));
""".replace("__RELEASE__", "S.release('movie2', {rect: SLOT}).reason" if released_first else "null"))
    assert result["answered"] == ("unknownMovie" if released_first else None)
    assert result["zonesBefore"] == 1
    assert result["zone"] == ["armed", "retired", "moduleRetired", "#2"]
    for who in ("big", "sib"):
        c = result[who]
        assert (c["paused"], c["inDocument"], c["gen"], c["pooled"]) == (True, False, -1, False), (who, c)
    assert result["retired"] == [[result["big"]["elId"], result["sib"]["elId"]]]


@pytest.mark.parametrize("consult", ["tick", "detach", "seam"])
def test_unengaged_fires_at_the_first_consult_on_the_destination(consult):
    """A go-to (or any non-WebGL move) never sends `glreplay-arm` on the move
    scene; the zone retires at the FIRST consult with `hn >= atScene`,
    whichever it is, without waiting for the interval."""
    first = {
        "tick": "tick();",
        "detach": "playerDetach(makeMovie(MEASURED));",
        "seam": "S.movieKeyOf(ctx.big);",
    }[consult]
    result = _run_gl(r"""
location.hash = '#1';
const ctx = {big: makeMovie(MEASURED)};
tick();
location.hash = '#2';
__FIRST__
const v = makeMovie(MEASURED);
playerDetach(v);
console.log(JSON.stringify({zones: zones(), v: census(v)}));
""".replace("__FIRST__", first))
    assert result["zones"] == [["pending", "armed", "moduleReady", "#1"], ["armed", "retired", "unengaged", "#2"]]
    assert result["v"]["pooled"] is False


def test_arm_note_off_the_move_scene_does_not_engage_the_zone():
    """`armSeen` counts only a `glreplay-arm` received while `hn === atScene - 1`."""
    result = _run_gl(r"""
location.hash = '#0';
tick();
S.note('glreplay-arm', {canvasId: '0-canvas', atScene: 2});
location.hash = '#2';
tick();
console.log(JSON.stringify(zones().map(z => z.slice(0, 3))));
""")
    assert result == [["pending", "armed", "moduleReady"], ["armed", "retired", "unengaged"]]


def test_go_to_slide_3_then_advance_keeps_the_3_to_4_bridge():
    """K1 / R5: go-to slide 3 from slide 1 jumps #1 -> #6 with no arm note.
    `unengaged` fires at #6; G2's sticky ARM-PRE then arms on the 3->4 context
    and stands down `assetUnbound`, and `release` answers `notArmed` without
    touching the pooled + DOM-preserved slide-3 decoder the bridge carries."""
    result = _run_gl(r"""
location.hash = '#1';
tick();
location.hash = '#6';
tick();
const atSix = zones().map(z => z.slice(0, 4));
goToScene(7);
const d = makeMovie(MEASURED);
playerDetach(d);
S.note('glreplay-arm', {canvasId: '1-canvas', atScene: 2});
const carried = S.carried('movie1').reason;
standDown(['assetUnbound']);
const out = S.release('movie1', {rect: SLOT});
G2.state = 'RETIRED';
tick();
const dAfterRelease = census(d);
goToScene(8);
tick();
const bridged = document.createElement('video');
bridged.setAttribute('src', 'https://host/untitled.mov');
console.log(JSON.stringify({
  atSix, carried, out, dAfterRelease, dId: d.__obedElId,
  retired: notesOf('retire-boundary').map(x => x.elIds),
  bridge: notesOf('bridge-3to4').map(x => x.oldElId),
  zonesAfter: zones().length,
}));
""")
    assert result["atSix"] == [["pending", "armed", "moduleReady", "#1"], ["armed", "retired", "unengaged", "#6"]]
    assert result["carried"] == "notArmed"
    assert result["out"] == {"ok": False, "reason": "notArmed", "mode": None, "elId": None, "retired": []}
    d = result["dAfterRelease"]
    assert (d["pooled"], d["preserved"], d["paused"], d["gen"]) == (True, "1", False, 0)
    assert all(result["dId"] not in ids for ids in result["retired"])
    assert result["bridge"] == [result["dId"]]
    assert result["zonesAfter"] == 2


def test_out_of_zone_retire_touches_only_armed_pooled_decoders_and_the_memo():
    """K1: a transition outside `[atScene-1, retireZoneEnd)` never runs today's
    key-wide sweep, so a decoder pooled there under pin survives. Driven by a
    go-to back to #0 while armed (A3 retires an armed zone at #7 on the first
    consult, so #0 is where an out-of-zone armed state can still hold a pin
    decoder when the watchdog fires)."""
    result = _run_gl(r"""
const ctx = arm();
S.carried('movie1');
goToScene(0);
const d = makeMovie(SIBLING);
playerDetach(d);
G2.state = 'RETIRED';
tick();
console.log(JSON.stringify({
  zone: zones().slice(-1)[0], d: census(d), big: census(ctx.big), sib: census(ctx.sib),
  retired: notesOf('retire-boundary').map(x => x.elIds),
}));
""")
    assert result["zone"] == ["armed", "retired", "moduleRetired", "#0"]
    assert result["retired"] == [[result["big"]["elId"], result["sib"]["elId"]]]
    for who in ("big", "sib"):
        assert (result[who]["paused"], result[who]["gen"]) == (True, -1)
    d = result["d"]
    assert (d["pooled"], d["preserved"], d["paused"], d["gen"]) == (True, "1", False, 0)
    assert d["inDocument"] is True


_HANDOFF = r"""
const ctx = arm();
S.carried('movie1');
S.setKeepWarm(ctx.big, false);
S.note('glreplay-live', {});
location.hash = '#2';
const canvas = posterLayer(SLOT);
standDown(['canvasRemoved']);
const handoff = S.release('movie1', {rect: SLOT});
if (handoff.mode !== 'handoff') throw new Error('no hand-off: ' + JSON.stringify(handoff));
"""


def test_released_is_pin_for_the_rest_of_the_destination():
    """Rows 6-8 in `released` (K16): the keep-warm flag is cleared, a later
    decoder pooled on the destination survives the interval, and a fresh
    element reuses the kept decoder exactly as pin does."""
    result = _run_gl(_HANDOFF + r"""
const noWarm = !!ctx.big.__obedGlNoWarm;
const e = makeMovie(SIBLING);
playerDetach(e);
tick();
const eAfterTick = census(e);
const fresh = document.createElement('video');
fresh.setAttribute('src', 'https://host/untitled.mov');
console.log(JSON.stringify({noWarm, eAfterTick, retire: notesOf('retire-boundary').length,
  reuse: notesOf('reuse-decoder').map(x => x.oldElId), bigId: ctx.big.__obedElId,
  zones: zones().length}));
""")
    assert result["noWarm"] is False
    assert result["eAfterTick"]["pooled"] is True
    assert result["retire"] == 0
    assert result["reuse"] == [result["bigId"]]
    assert result["zones"] == 2


def test_leaving_the_destination_retires_the_released_decoder():
    result = _run_gl(_HANDOFF + r"""
goToScene(1);
tick();
console.log(JSON.stringify({zone: zones().slice(-1)[0], big: census(ctx.big),
  retired: notesOf('retire-boundary').map(x => x.elIds), bigId: ctx.big.__obedElId}));
""")
    assert result["zone"] == ["released", "retired", "leftDestination", "#1"]
    assert (result["big"]["paused"], result["big"]["inDocument"], result["big"]["gen"]) == (True, False, -1)
    assert result["retired"] == [[result["bigId"]]]


@pytest.mark.parametrize("state", ["armed", "released"])
def test_clear_retires_the_zone_and_pauses_what_the_pool_drop_left_playing(state):
    """K14: `pool.clear()` drops pooled decoders without pausing them."""
    setup = "const ctx = arm();\nlocation.hash = '#2';\n" if state == "armed" else _HANDOFF
    result = _run_gl(setup + r"""
P.clear();
console.log(JSON.stringify({zone: zones().slice(-1)[0].slice(0, 3), big: census(ctx.big), sib: census(ctx.sib)}));
""")
    assert result["zone"] == [state, "retired", "cleared"]
    for who in ("big", "sib"):
        assert result[who]["paused"] is True, who
        assert result[who]["inDocument"] is False, who
        assert result[who]["pooled"] is False, who


def test_seam_note_passes_only_the_modules_own_kinds():
    """K15: the module can never forge a G3 note G6 counts."""
    result = _run_gl(r"""
location.hash = '#1';
tick();
const before = P.events.length;
['glreplay-zone', 'glreplay-carried', 'glreplay-release', 'glreplay-hold', 'retire-boundary',
 'preserve-refused', 'bogus'].forEach(k => S.note(k, {forged: true}));
const forged = P.events.slice(before).filter(e => e.detail.forged).length;
['glreplay-arm', 'glreplay-live', 'glreplay-standdown', 'glreplay-handoff',
 'glreplay-opacity-unproven', 'glreplay-retained-frame'].forEach(k => S.note(k, {mine: k}));
console.log(JSON.stringify({forged, passed: P.events.filter(e => e.detail.mine).map(e => [e.kind, e.detail.mine])}));
""")
    assert result["forged"] == 0
    assert result["passed"] == [[k, k] for k in (
        "glreplay-arm", "glreplay-live", "glreplay-standdown", "glreplay-handoff",
        "glreplay-opacity-unproven", "glreplay-retained-frame",
    )]


def test_g3_note_schemas():
    result = _run_gl(_HANDOFF + r"""
const shape = (kind) => notesOf(kind).map(d => Object.keys(d).sort());
console.log(JSON.stringify({zone: shape('glreplay-zone'), carried: shape('glreplay-carried'),
  hold: shape('glreplay-hold'), release: shape('glreplay-release')}));
""")
    assert result["zone"] == [["from", "key", "reason", "sceneHash", "to"]] * 2
    assert result["carried"] == [["candidates", "delta", "elId", "sceneHash"]]
    assert result["hold"] == [["key", "sceneHash", "via"]]
    assert result["release"] == [["elId", "mode", "ok", "reason", "retired", "sceneHash"]]


# --- the retire family on a glReplay plan with no usable module ---
#
# Plan §5: the whole retire test family above runs again on the flag-on plan
# with the module absent, RETIRED, or at version 2. The zone goes pending ->
# retired at its first consult, so every outcome must be identical to the
# literal retire, plus exactly one `glreplay-zone` note.

_RETIRE_FAMILY = [
    test_core_never_relies_on_a_hashchange_event,
    test_retire_zone_stash_declines_and_notes_once,
    test_retire_zone_src_clear_really_clears,
    test_retire_zone_remove_attribute_really_removes,
    test_retire_zone_blocks_remount_of_a_decoder_pooled_before_the_boundary,
    test_retire_zone_create_element_does_not_facade_or_reuse,
    test_interval_sweep_retires_a_decoder_pooled_before_the_zone,
    test_interval_sweep_is_silent_outside_the_zone,
    test_before_the_retire_zone_preservation_is_unchanged,
    test_after_the_zone_end_preservation_works_again,
    test_bridge_still_engages_at_scene_8_for_the_retired_key,
    test_retire_zone_does_not_touch_another_movie_key,
    test_null_hash_is_allowed,
    test_sweep_retires_a_pooled_decoder_whose_src_was_really_cleared,
    test_pending_remount_of_an_empty_src_decoder_is_refused_in_zone,
    test_a_stamped_empty_src_decoder_is_free_again_past_the_zone_end,
]


def _family_cases() -> list:
    cases = []
    for fn in _RETIRE_FAMILY:
        marks = [m for m in getattr(fn, "pytestmark", []) if m.name == "parametrize"]
        if not marks:
            cases.append(pytest.param(fn, {}, id=fn.__name__))
            continue
        [mark] = marks
        name = mark.args[0]
        for value in mark.args[1]:
            cases.append(pytest.param(fn, {name: value}, id=f"{fn.__name__}[{value}]"))
    return cases


_UNUSABLE_MODULES = {
    "absent": (None, "moduleAbsent"),
    "retired": ({"version": 1, "state": "RETIRED", "standDowns": ["glReplayUnavailable"]}, "moduleRetired"),
    "version-2": ({"version": 2, "state": "IDLE", "standDowns": []}, "moduleVersion"),
}


@pytest.mark.parametrize("module", list(_UNUSABLE_MODULES))
@pytest.mark.parametrize("fn,kwargs", _family_cases())
def test_retire_family_holds_on_a_gl_replay_plan_without_a_usable_module(fn, kwargs, module, monkeypatch):
    seed, reason = _UNUSABLE_MODULES[module]
    zone_notes: list = []

    def run_on_gl_plan(script: str, *, plan: dict = _RETIRE_PLAN) -> dict:
        assert plan is _RETIRE_PLAN
        epilogue = r"""
tick();
console.log(JSON.stringify(P.events.filter(e => e.kind === 'glreplay-zone').map(e => e.detail)));
"""
        node = shutil.which("node")
        if not node:
            pytest.skip("Node is required to exercise the JS core")
        harness = (
            _FULL_HARNESS_PREAMBLE.replace("__STAGE__", json.dumps(_IDENTITY_STAGE))
            .replace("__PLAN__", json.dumps(_GL_PLAN))
            .replace("__AFTER_CORE__", _gl_after_core(seed))
            .replace("__CORE__", live_continuity_js.PRESERVE_CORE_JS)
            + script + epilogue
        )
        out = subprocess.run([node, "-e", harness], check=True, text=True, capture_output=True)
        lines = out.stdout.strip().splitlines()
        zone_notes.append(json.loads(lines[-1]))
        return json.loads(lines[-2])

    monkeypatch.setattr(sys.modules[__name__], "_run_retire", run_on_gl_plan)
    fn(**kwargs)
    assert zone_notes, "the family test never ran the core"
    for notes in zone_notes:
        assert [(n["from"], n["to"], n["reason"], n["key"]) for n in notes] == [
            ("pending", "retired", reason, "movie1")
        ]



# --- review r1 (`git show a56474f3:.agents/reviews/gl-replay-g3/opus-r1-a.md`) ------------------


def test_armed_retires_a_decoder_pooled_before_the_zone_and_hands_off_only_the_carried_one():
    """A1: a decoder pooled and remounted under pin on the scene before the
    move (a source-slide build) must be retired by the first in-zone tick,
    exactly as the literal retire does, and must never be the decoder a later
    `reuse-decoder` facades onto after the hand-off."""
    result = _run_gl(r"""
location.hash = '#0';
tick();
const early = makeMovie(SIBLING);
playerDetach(early);
const earlyAtZero = census(early);
const ctx = arm();
const earlyArmed = census(early);
const retiredAtOne = notesOf('retire-boundary').map(x => [x.elIds, x.sceneHash]);
S.carried('movie1');
S.note('glreplay-live', {});
location.hash = '#2';
posterLayer(SLOT);
standDown(['canvasRemoved']);
const out = S.release('movie1', {rect: SLOT});
const fresh = document.createElement('video');
fresh.setAttribute('src', 'https://host/untitled.mov');
console.log(JSON.stringify({earlyAtZero, earlyArmed, retiredAtOne, out, earlyId: early.__obedElId,
  bigId: ctx.big.__obedElId, sibId: ctx.sib.__obedElId,
  reuse: notesOf('reuse-decoder').map(x => x.oldElId)}));
""")
    assert result["earlyAtZero"]["inDocument"] is True
    assert result["earlyAtZero"]["remounted"] == "1"
    e = result["earlyArmed"]
    assert (e["paused"], e["inDocument"], e["gen"], e["pooled"]) == (True, False, -1, False)
    assert result["retiredAtOne"] == [[[result["earlyId"]], "#1"]]
    assert result["out"]["mode"] == "handoff"
    assert result["out"]["retired"] == [result["sibId"]]
    assert result["reuse"] == [result["bigId"]]


def test_release_retires_every_in_zone_same_asset_decoder_except_the_carried_one():
    """A1(2): the sibling set is every pooled or DOM-preserved decoder of the
    key except the memo, not only the armed-pooled ones — forced here by a
    same-asset decoder pooled under pin that the armed sweep has not reached."""
    result = _run_gl(r"""
const ctx = arm();
S.carried('movie1');
S.note('glreplay-live', {});
location.hash = '#2';
const other = makeMovie(SIBLING);
other.dataset.obedPreserved = '1';
posterLayer(SLOT);
standDown(['canvasRemoved']);
const out = S.release('movie1', {rect: SLOT});
console.log(JSON.stringify({out, other: census(other), otherId: other.__obedElId, sibId: ctx.sib.__obedElId}));
""")
    assert result["out"]["mode"] == "handoff"
    assert sorted(result["out"]["retired"]) == sorted([result["sibId"], result["otherId"]])
    o = result["other"]
    assert (o["paused"], o["inDocument"], o["gen"]) == (True, False, -1)


def test_a_natural_facade_stub_is_never_bound():
    """A1(3): a stub `bindFacade` proxies onto a pooled decoder answers the
    candidate checks through the real decoder; it must never be carried."""
    result = _run_gl(r"""
location.hash = '#0';
tick();
const real = makeMovie(SIBLING);
playerDetach(real);
const stub = document.createElement('video');
stub.setAttribute('src', 'https://host/untitled.mov');
if (stub.__obedFacadeFor !== real) throw new Error('no facade');
stub.parentNode = bodyEl;
stub._rect = screenOf(MEASURED);
location.hash = '#1';
tick();
playerDetach(stub);
const r = S.carried('movie1');
console.log(JSON.stringify({reason: r.reason, bound: !!r.video, stubArmedPooled: !!stub.__obedGlPooled}));
""")
    assert result == {"reason": "notPooled", "bound": False, "stubArmedPooled": True}


def test_armed_zone_retires_when_the_hash_reaches_the_next_flow():
    """A3: with `armSeen`, an armed zone at `hn >= retireZoneEnd` used to stay
    armed and let the next flow bridge the carried decoder while armed."""
    plan = {**_GL_PLAN, "boundaries": [b for b in _GL_PLAN["boundaries"] if b["action"] != "restart"]}
    result = _run_gl(r"""
const ctx = arm();
goLive();
goToScene(8);
tick();
const fresh = document.createElement('video');
fresh.setAttribute('src', 'https://host/untitled.mov');
console.log(JSON.stringify({zone: zones().slice(-1)[0], big: census(ctx.big),
  bridged: notesOf('bridge-3to4').map(x => x.oldElId), bigId: ctx.big.__obedElId}));
""", plan=plan)
    assert result["zone"] == ["armed", "retired", "leftDestination", "#8"]
    assert result["bigId"] not in result["bridged"]
    assert (result["big"]["paused"], result["big"]["gen"]) == (True, -1)


@pytest.mark.parametrize("via", ["src-clear", "removeAttribute"])
def test_armed_clear_on_a_reattached_armed_pooled_decoder_really_clears(via):
    """A4: an attached element is never kept painting, even one pooled armed."""
    clear = "ctx.big.src = '';" if via == "src-clear" else "ctx.big.removeAttribute('src');"
    result = _run_gl(r"""
const ctx = arm();
location.hash = '#2';
ctx.big.parentNode = bodyEl;
__CLEAR__
console.log(JSON.stringify({src: ctx.big.src || '', refusals: notesOf('preserve-refused').map(d => d.via),
  holds: notesOf('glreplay-hold').map(d => d.via)}));
""".replace("__CLEAR__", clear))
    assert result["src"] == ""
    assert result["refusals"] == [via]
    assert result["holds"] == ["remount"]


@pytest.mark.parametrize("via", ["src-clear", "removeAttribute"])
def test_armed_clear_is_real_when_stash_declines_the_detached_decoder(via):
    """A5: a detached move-scene clear is swallowed only when `stash` pooled
    the decoder; otherwise nothing would ever retire the kept src."""
    clear = "v.src = '';" if via == "src-clear" else "v.removeAttribute('src');"
    result = _run_gl(r"""
location.hash = '#1';
tick();
const v = makeMovie(MEASURED);
v.readyState = 1; v.currentTime = 0;
v.parentNode = null;
__CLEAR__
console.log(JSON.stringify({src: v.src || '', pooled: census(v).pooled,
  refusals: notesOf('preserve-refused').map(d => d.via)}));
""".replace("__CLEAR__", clear))
    assert result == {"src": "", "pooled": False, "refusals": [via]}


def test_a_repurposed_armed_pooled_decoder_is_neither_a_victim_nor_carried():
    """A6: `reidentify` drops the armed stamp, and `retireZone` checks the key."""
    result = _run_gl(r"""
const ctx = arm();
ctx.sib.src = 'https://host/WA0125.mov';
ctx.sib.parentNode = bodyEl;
G2.state = 'RETIRED';
tick();
console.log(JSON.stringify({sib: census(ctx.sib), zone: zones().slice(-1)[0].slice(0, 3)}));
""")
    assert result["zone"] == ["armed", "retired", "moduleRetired"]
    s = result["sib"]
    assert (s["paused"], s["inDocument"], s["gen"], s["glPooled"]) == (False, True, 0, False)


def test_a_repurposed_memo_is_not_handed_off():
    """A6 row 6: the memo's source moved to another asset without the hooks
    seeing it (a raw attribute write) — release must not hand it off."""
    result = _run_gl(r"""
const ctx = arm();
S.carried('movie1');
S.note('glreplay-live', {});
location.hash = '#2';
srcStore.set(ctx.big, 'https://host/WA0125.mov');
posterLayer(SLOT);
standDown(['canvasRemoved']);
const out = S.release('movie1', {rect: SLOT});
console.log(JSON.stringify({out}));
""")
    assert result["out"]["mode"] == "retire"
    assert result["out"]["reason"] == "noCarried"


def test_a_reassigned_memo_is_forgotten():
    """A6 `reidentify`: a hooked re-assignment clears the memo and the stamp."""
    result = _run_gl(r"""
const ctx = arm();
S.carried('movie1');
ctx.big.src = 'https://host/WA0125.mov';
S.note('glreplay-live', {});
location.hash = '#2';
posterLayer(SLOT);
standDown(['canvasRemoved']);
const out = S.release('movie1', {rect: SLOT});
console.log(JSON.stringify({out, glPooled: !!ctx.big.__obedGlPooled}));
""")
    assert result["out"]["reason"] == "noCarried"
    assert result["out"]["elId"] is None
    assert result["glPooled"] is False


def test_stash_attached_branch_writes_the_authored_rect():
    """A7: `stash`'s own attached-box capture (a pin src clear on #0, no
    interval tick) is a second, independent writer of `__obedAuthoredRect`."""
    result = _run_gl(r"""
location.hash = '#0';
const v = makeMovie(MEASURED);
v.src = '';
console.log(JSON.stringify({pooled: census(v).pooled, rect: v.__obedAuthoredRect || null}));
""", stage=_LETTERBOXED_STAGE)
    assert result["pooled"] is True
    assert result["rect"] == pytest.approx(_GL_MEASURED)


def test_disable_retires_a_zone_it_would_otherwise_leave_armed():
    """A9: with the interval stopped, no watchdog could ever end the zone."""
    result = _run_gl(r"""
P.disable();
const r = S.carried('movie1');
console.log(JSON.stringify({reason: r.reason, zones: zones().map(z => z.slice(0, 3))}));
""")
    assert result == {"reason": "disabled", "zones": [["pending", "retired", "disabled"]]}


def test_a_retire_that_throws_midway_still_retires_every_armed_decoder():
    """A11: `retireDecoder` throws once (its `dataset` write) after the zone
    already reads `retired`; the catch must finish retiring the armed pool."""
    result = _run_gl(r"""
const ctx = arm();
goLive();
posterLayer(SLOT);
let throws = 1;
const ds = ctx.big.dataset;
ctx.big.dataset = new Proxy(ds, {deleteProperty(t, k) {
  if (throws > 0) { throws -= 1; throw new Error('dataset gone'); }
  delete t[k]; return true;
}});
standDown(['glError']);
let threw = null, out = null;
try { out = S.release('movie1', {rect: SLOT}); } catch (e) { threw = String(e); }
console.log(JSON.stringify({threw, out, big: census(ctx.big), sib: census(ctx.sib), throwsLeft: throws}));
""")
    assert result["threw"] is None
    assert result["throwsLeft"] == 0
    assert (result["out"]["ok"], result["out"]["mode"], result["out"]["reason"]) == (True, "retire", "releaseError")
    for who in ("big", "sib"):
        c = result[who]
        assert (c["paused"], c["inDocument"], c["gen"]) == (True, False, -1), (who, c)


def test_facade_swap_never_resurrects_a_retired_decoder():
    """A13 / K20: a facade bound in `released` whose stub is inserted after the
    zone retired must not re-insert and play the retired decoder."""
    result = _run_gl(_HANDOFF + r"""
const fresh = document.createElement('video');
fresh.setAttribute('src', 'https://host/untitled.mov');
if (fresh.__obedFacadeFor !== ctx.big) throw new Error('no facade onto the memo');
goToScene(1);
tick();
fresh.parentNode = bodyEl;
moCallbacks.slice().forEach((cb) => cb([{removedNodes: []}]));
console.log(JSON.stringify({big: census(ctx.big), swaps: notesOf('dom-swap').length}));
""")
    assert result["swaps"] == 0
    b = result["big"]
    assert (b["paused"], b["inDocument"], b["gen"]) == (True, False, -1)


def test_facade_swap_still_happens_for_a_live_decoder():
    """Control for A13: the liveness gate keeps pin's ordinary facade swap."""
    result = _run_gl(r"""
location.hash = '#0';
tick();
const real = makeMovie(SIBLING);
playerDetach(real);
const fresh = document.createElement('video');
fresh.setAttribute('src', 'https://host/untitled.mov');
fresh.parentNode = bodyEl;
moCallbacks.slice().forEach((cb) => cb([{removedNodes: []}]));
console.log(JSON.stringify({swaps: notesOf('dom-swap').length}));
""")
    assert result == {"swaps": 1}



# --- A2 (owner: option (a) + guard G + the stash rule) -------------------
#
# `git show a56474f3:.agents/reviews/gl-replay-g3/a2-advice.md`: after the hand-off the carried
# decoder (and a facade bound to it) must never take the top-z stage append,
# and a detach must not overwrite its last attached rect.


def test_released_memo_and_its_facade_never_take_the_stage_append():
    """Guard G: the 2->3 transition window (hash still #5) has no matching
    poster canvas; the memo and its facade are held (`glreplay-hold` via
    `stage`), never appended over the transition."""
    result = _run_gl(_HANDOFF + r"""
const stub = document.createElement('video');
stub.setAttribute('src', 'https://host/untitled.mov');
if (stub.__obedFacadeFor !== ctx.big) throw new Error('no facade onto the memo');
canvases.length = 0;
location.hash = '#5';
settleMoves();
playerDetachSubtree(ctx.big);
stub.parentNode = bodyEl;
playerDetach(stub);
console.log(JSON.stringify({
  memoInBody: ctx.big.parentNode === bodyEl, stubInBody: stub.parentNode === bodyEl,
  memoInDocument: document.contains(ctx.big), stubInDocument: document.contains(stub),
  stubPooled: census(stub).pooled,
  done: notesOf('remount-done').map(d => d.elId),
  holds: notesOf('glreplay-hold').map(d => d.via),
}));
""")
    assert result["stubPooled"] is True
    assert result["memoInBody"] is False and result["stubInBody"] is False
    assert result["memoInDocument"] is False and result["stubInDocument"] is False
    assert result["done"] == []
    assert "stage" in result["holds"]


def test_released_pin_still_appends_a_decoder_that_is_not_the_carried_one():
    """Control for guard G: ordinary pin on any other decoder is unchanged."""
    result = _run_gl(_HANDOFF + r"""
canvases.length = 0;
const other = makeMovie(SIBLING);
tick();
playerDetach(other);
console.log(JSON.stringify({done: notesOf('remount-done').map(d => d.elId), otherId: other.__obedElId,
  inBody: other.parentNode === bodyEl}));
""")
    assert result["done"] == [result["otherId"]]
    assert result["inBody"] is True


@pytest.mark.parametrize("stage", [_IDENTITY_STAGE, _LETTERBOXED_STAGE], ids=["identity", "letterboxed"])
def test_released_memo_keeps_its_rect_across_a_subtree_detach(stage):
    """The stash rule: a detach in `released` does not let `captureLayout`'s
    zero-origin style fallback overwrite the memo's rect, so `tryRemount`
    never reaches the elId-parity footprint fallback for it."""
    result = _run_gl(_HANDOFF + r"""
const before = Object.assign({}, ctx.big.__obedRect);
location.hash = '#3';
settleMoves();
playerDetachSubtree(ctx.big);
console.log(JSON.stringify({before, after: ctx.big.__obedRect,
  footprint: notesOf('remount-footprint-rect').map(d => d.elId),
  landed: notesOf('remount-into-authored-layer').map(d => d.rect)}));
""", stage=stage)
    screen = _screen(_GL_INSTANCE, stage)
    assert result["before"] == pytest.approx(screen)
    assert result["after"] == pytest.approx(screen)
    assert result["footprint"] == []
    assert len(result["landed"]) == 2
    assert result["landed"][1] == pytest.approx(screen)


# --- Codex r1 (`git show a56474f3:.agents/reviews/gl-replay-g3/codex-r1.md`) --------------


def _insert(node: str, parent: str) -> str:
    """The player inserts `node` under `parent`; the observers see an insertion record."""
    return (
        f"{node}.parentNode = {parent};\n"
        f"moCallbacks.slice().forEach((cb) => cb([{{addedNodes: [{node}], removedNodes: []}}]));\n"
    )


def test_released_facade_inserted_top_z_never_swaps_the_carried_decoder_in():
    """G34-01: the 2->3 transition window (#5, no matching poster canvas). The
    player inserts the fresh stub bound to the carried decoder under `#body`;
    the facade observer fires while the stub is STILL attached. The swap would
    move the carried decoder top-z and play it, bypassing guard G."""
    result = _run_gl(_HANDOFF + r"""
canvases.length = 0;
location.hash = '#5';
settleMoves();
playerDetachSubtree(ctx.big);
const stub = document.createElement('video');
stub.setAttribute('src', 'https://host/untitled.mov');
if (stub.__obedFacadeFor !== ctx.big) throw new Error('no facade onto the memo');
""" + _insert("stub", "bodyEl") + r"""
const ids = [ctx.big.__obedElId, stub.__obedElId];
const forIds = (kind) => notesOf(kind).filter(d => ids.indexOf(d.elId) >= 0).length;
console.log(JSON.stringify({
  swaps: notesOf('dom-swap').length, done: forIds('remount-done'), footprint: forIds('remount-footprint-rect'),
  memoInBody: ctx.big.parentNode === bodyEl, memoInDocument: document.contains(ctx.big),
  stubInBody: stub.parentNode === bodyEl,
  holds: notesOf('glreplay-hold').map(d => d.via),
}));
""")
    assert result["swaps"] == 0
    assert result["done"] == 0
    assert result["footprint"] == 0
    assert result["memoInBody"] is False and result["memoInDocument"] is False
    assert result["stubInBody"] is False
    assert "stage" in result["holds"]


def test_released_facade_inserted_in_the_poster_layer_still_swaps():
    """Control for G34-01: a stub the player inserts into the carried decoder's
    own authored poster layer is swapped exactly as pin does."""
    result = _run_gl(_HANDOFF + r"""
const stub = document.createElement('video');
stub.setAttribute('src', 'https://host/untitled.mov');
""" + _insert("stub", "canvas.parentNode") + r"""
console.log(JSON.stringify({swaps: notesOf('dom-swap').map(d => d.elId), bigId: ctx.big.__obedElId,
  memoInLayer: ctx.big.parentNode === canvas.parentNode}))
""")
    assert result["swaps"] == [result["bigId"]]
    assert result["memoInLayer"] is True


def test_released_facade_detached_without_a_rect_uses_the_carried_rect():
    """G34-01 (copy): a detached, media-less facade has no rect of its own; it
    must not reach the elId-parity footprint fallback before guard G."""
    result = _run_gl(_HANDOFF + r"""
const stub = document.createElement('video');
stub.setAttribute('src', 'https://host/untitled.mov');
canvases.length = 0;
location.hash = '#5';
stub.parentNode = bodyEl;
playerDetach(stub);
console.log(JSON.stringify({
  footprint: notesOf('remount-footprint-rect').map(d => d.elId),
  done: notesOf('remount-done').map(d => d.elId),
  stubRect: stub.__obedRect || null, memoRect: ctx.big.__obedRect,
  stubInDocument: document.contains(stub), stubPooled: census(stub).pooled,
}));
""")
    assert result["stubPooled"] is True
    assert result["footprint"] == []
    assert result["done"] == []
    assert result["stubRect"] == pytest.approx(result["memoRect"])
    assert result["stubInDocument"] is False


@pytest.mark.parametrize("plan", [_RETIRE_PLAN, _NO_RETIRE_PLAN], ids=["retire", "no-retire"])
@pytest.mark.parametrize("via", ["setter", "setAttribute"])
def test_flag_off_source_reassignment_adds_no_gl_expando(plan, via):
    """G34-02: without a `glReplay` entry the default path must not grow a new
    own property on the player's videos."""
    assign = (lambda url: f"v.src = '{url}';") if via == "setter" else (lambda url: f"v.setAttribute('src', '{url}');")
    script = (
        "const v = document.createElement('video');\nv.readyState = 4; v.currentTime = 1; v.parentNode = bodyEl;\n"
        + assign("https://host/untitled.mov") + "\n" + assign("https://host/WA0125.mov") + "\n"
        + assign("https://host/untitled.mov") + "\n"
        + r"""console.log(JSON.stringify({
  own: ['__obedGlPooled', '__obedAuthoredRect', '__obedAuthoredRectScene', '__obedGlNoWarm', '__obedGlCarried']
    .filter(k => Object.prototype.hasOwnProperty.call(v, k)),
}));
"""
    )
    result = _run_full_core_in_node(plan=plan, stage=_IDENTITY_STAGE, script=script)
    assert result == {"own": []}


def test_a_capture_from_an_earlier_scene_never_measures_the_move():
    """G34-03: a decoder measured at the target geometry on an earlier scene,
    moved to the sibling geometry, and detached on the move scene before any
    capture there, must answer `unmeasured` — not bind on the stale rect."""
    result = _run_gl(r"""
location.hash = '#0';
const v = makeMovie(MEASURED);
tick();
const staleScene = v.__obedAuthoredRectScene;
location.hash = '#1';
v._rect = screenOf(SIBLING);
playerDetach(v);
const r = S.carried('movie1');
console.log(JSON.stringify({staleScene, pooled: census(v).glPooled, reason: r.reason, bound: !!r.video}));
""")
    assert result == {"staleScene": 0, "pooled": True, "reason": "unmeasured", "bound": False}


def test_changing_assets_clears_the_authored_capture():
    """G34-03: `reidentify` drops both the rect and its scene on an asset change."""
    result = _run_gl(r"""
location.hash = '#1';
const v = makeMovie(MEASURED);
tick();
const before = [!!v.__obedAuthoredRect, v.__obedAuthoredRectScene];
v.src = 'https://host/WA0125.mov';
console.log(JSON.stringify({before, after: [Object.prototype.hasOwnProperty.call(v, '__obedAuthoredRect'),
  Object.prototype.hasOwnProperty.call(v, '__obedAuthoredRectScene')]}));
""")
    assert result == {"before": [True, 1], "after": [False, False]}
