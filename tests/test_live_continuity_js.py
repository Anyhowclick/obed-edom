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
    assert live_continuity_js.CONTINUITY_VERSION == 2
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


def _run_core_in_node(*, plan, fail_install=False) -> dict:
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
try {{
{live_continuity_js.PRESERVE_CORE_JS}
}} catch (e) {{
  console.log(JSON.stringify({{threw: String(e && e.message || e), ready: !!(window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.ready)}}));
  process.exit(0);
}}
console.log(JSON.stringify({{installed: !!window.__OBED_P2_PRESERVE__, ready: !!(window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.ready)}}));
"""
    result = subprocess.run([node, "-e", harness], check=True, text=True, capture_output=True)
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_no_plan_guard_leaves_page_untouched():
    """Fail-closed: with no `window.__OBED_CONTINUITY__`, the core must install
    nothing (never even reach the `__OBED_P2_PRESERVE__` idempotency object)."""
    out = _run_core_in_node(plan=None)
    assert out == {"installed": False, "ready": False}


def test_with_plan_installs_the_preserve_object():
    plan = {
        "movies": {"movie1": {"assetKeys": ["untitled.mov"], "footprint": {"x": 1, "y": 2, "w": 3, "h": 4}}},
        "boundaries": [{"atScene": 6, "action": "restart"}],
    }
    out = _run_core_in_node(plan=plan)
    assert out == {"installed": True, "ready": True}


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
    assert out == {"threw": "install failed", "ready": False}


def _run_bridge_motion_in_node(*, stop_before_retry: bool = False) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the JS core")
    core = live_continuity_js.PRESERVE_CORE_JS
    start = core.index("  function keepThroughBridge(v) {")
    end = core.index("  function keepAtSlot", start)
    motion = core[start:end]
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
const document = {{getElementById: () => stage, body: stage, contains: () => connected}};
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


def test_clear_generation_stops_bridge_motion_callbacks():
    result = _run_bridge_motion_in_node()
    assert result["unchangedAfterClear"] is True
    assert result["pendingFramesAfterClear"] == 0
    assert result["pinningAfterClear"] is False
