"""S4 -- oracle handle parity (GL-replay G2 plan rev 2 SS2.4, SS3 S4 row).

Two independent halves, neither of which trusts a hand-typed field list:

1.  **Static parity.** The field set the GL-replay module publishes on
    `window.__OBED_GL_ORACLE__` (parsed out of `GL_REPLAY_JS`) must cover every
    field the consumer actually reads -- and the consumer's list is extracted
    from `live_continuity_probe.INPAGE_LIVENESS_JS` and from
    `html_alpha_probe._valid_inpage_sample`, never written down here. Skips with
    a reason while the module (stream S1) does not exist yet.

2.  **Behavioural parity.** The REAL `INPAGE_LIVENESS_JS` is executed under Node
    against a fake handle carrying exactly that shape, and its output is fed to
    the REAL `live_continuity_probe.inpage_oracle_result`. A live pattern must
    reach the LIVE verdict with the paused-decoder control DEAD; a handle that
    has stood down, one whose `epoch` moves mid-window, and one missing a method
    must each fail closed.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
for _p in (REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from obed_edom import html_alpha_probe  # noqa: E402


def _load_probe():
    spec = importlib.util.spec_from_file_location(
        "live_continuity_probe_for_parity", REPO / "scripts" / "live_continuity_probe.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


probe = _load_probe()


# --------------------------------------------------------------------------
# Field-set extraction (both sides derived from source, never hand-typed)
# --------------------------------------------------------------------------

# `handle.<name>` / `handle["<name>"]` in the probe's in-page script: exactly the
# handle surface the consumer touches.
_HANDLE_READ_RE = re.compile(r"handle(?:\.([A-Za-z_$][\w$]*)|\[[\"']([^\"']+)[\"']\])")


def probe_handle_fields() -> set[str]:
    fields: set[str] = set()
    for dotted, quoted in _HANDLE_READ_RE.findall(probe.INPAGE_LIVENESS_JS):
        fields.add(dotted or quoted)
    return fields


# Sample fields the scorer requires (`_valid_inpage_sample` -- everything it
# reads or converts). `vt`/`mediaTime` are read only by `score_inpage_liveness`
# and are recorded, never required, so they are not in this set.
_SAMPLE_GET_RE = re.compile(r"sample\.get\(\"([A-Za-z_$][\w$]*)\"\)")


def probe_sample_fields() -> set[str]:
    source = inspect.getsource(html_alpha_probe._valid_inpage_sample)
    fields = set(_SAMPLE_GET_RE.findall(source))
    assert 'sample.get("bands")' in source
    fields.add("bands")
    return fields


def _strip_js(source: str) -> str:
    """Blank out strings, regex-free comments -- enough for brace/keys scanning."""
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        ch = source[i]
        if ch in "\"'`":
            quote = ch
            out.append(" ")
            i += 1
            while i < n and source[i] != quote:
                if source[i] == "\\":
                    out.append(" ")
                    i += 1
                if i < n:
                    out.append(" " if source[i] != "\n" else "\n")
                    i += 1
            out.append(" ")
            i += 1
            continue
        if ch == "/" and i + 1 < n and source[i + 1] == "/":
            while i < n and source[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if ch == "/" and i + 1 < n and source[i + 1] == "*":
            while i < n and not (source[i] == "*" and i + 1 < n and source[i + 1] == "/"):
                out.append("\n" if source[i] == "\n" else " ")
                i += 1
            out.append("  ")
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


_ASSIGN_RE = re.compile(r"window\.__OBED_GL_ORACLE__\s*=\s*")
# A key sits at depth 1 immediately after the opening `{` or a comma, so
# `sample: function(n){...}` yields `sample` and not also `function`.
_KEY_RE = re.compile(r"(?:^\{|[{,])\s*([A-Za-z_$][\w$]*)\s*[:(]")


def module_handle_fields(gl_replay_js: str) -> set[str] | None:
    """Top-level keys of the object literal assigned to `window.__OBED_GL_ORACLE__`.

    `None` when the module does not assign an inline object literal there (e.g.
    it builds the handle in a variable first) -- the caller skips rather than
    guessing, because a wrong parse would make this test lie.
    """
    text = _strip_js(gl_replay_js)
    match = _ASSIGN_RE.search(text)
    if not match or text[match.end() : match.end() + 1] != "{":
        return None
    start = match.end()
    depth, end = 0, None
    for i in range(start, len(text)):
        if text[i] in "{[(":
            depth += 1
        elif text[i] in "}])":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        return None
    body = text[start : end + 1]

    depths: list[int] = []
    depth = 0
    for ch in body:
        if ch in "{[(":
            depth += 1
            depths.append(depth)
        elif ch in "}])":
            depths.append(depth)
            depth -= 1
        else:
            depths.append(depth)

    keys: set[str] = set()
    for key_match in _KEY_RE.finditer(body):
        if depths[key_match.start()] == 1:
            keys.add(key_match.group(1))
    return keys or None


def _gl_replay_js() -> str:
    try:
        from obed_edom import live_gl_replay_js  # type: ignore
    except Exception:  # noqa: BLE001 - stream S1 has not landed the module yet
        pytest.skip("src/obed_edom/live_gl_replay_js.py (stream S1) is not available yet")
    return live_gl_replay_js.GL_REPLAY_JS


# --------------------------------------------------------------------------
# Static parity tests
# --------------------------------------------------------------------------


def test_probe_handle_field_extraction_is_not_empty():
    """Guard the instrument: if the probe's script is refactored so that
    `handle.<field>` no longer appears, every parity assertion below would pass
    vacuously."""
    fields = probe_handle_fields()
    assert {"gl", "canvas", "video", "sample", "epoch", "rect"} <= fields
    assert len(fields) >= 10
    sample_fields = probe_sample_fields()
    assert {"bands", "t", "glErr", "greenRGB"} <= sample_fields


_SYNTHETIC_GL_REPLAY_JS = """
(function(){
  var rect = {x: 1, y: 2, w: 3, h: 4};  // not a handle key: nested/other scope
  function publish(){
    window.__OBED_GL_ORACLE__ = {
      gl: gl, canvas: canvas, video: v,
      epoch: state.epoch, sceneId: scene, instanceId: "a#1",
      rect: {x: rect.x, y: rect.y, w: rect.w, h: rect.h},
      canvasId: canvas.id,
      sample: function(n){ return readN(n); },
      markerBands: async function(){ return {dark: d, light: l, epoch: state.epoch}; },
      pause: function(){ return doPause(); },
      resume: function(){ return doResume(); },
      stats: function(){ return {settleGapMs: 0}; },
    };
  }
})();
"""


def test_handle_field_extractor_sees_a_known_literal_and_notices_a_missing_field():
    """Instrument check for `module_handle_fields`: without it, a module whose
    handle silently dropped a field could still 'pass' parity."""
    keys = module_handle_fields(_SYNTHETIC_GL_REPLAY_JS)
    assert keys == {
        "gl", "canvas", "video", "epoch", "sceneId", "instanceId", "rect",
        "canvasId", "sample", "markerBands", "pause", "resume", "stats",
    }
    assert not (probe_handle_fields() - keys)
    crippled = module_handle_fields(_SYNTHETIC_GL_REPLAY_JS.replace("instanceId:", "instanceld:"))
    assert probe_handle_fields() - crippled == {"instanceId"}
    assert module_handle_fields("window.__OBED_GL_ORACLE__ = buildHandle();") is None


def test_module_handle_covers_every_field_the_probe_reads():
    published = module_handle_fields(_gl_replay_js())
    if published is None:
        pytest.skip(
            "GL_REPLAY_JS does not assign an inline object literal to "
            "window.__OBED_GL_ORACLE__; parity cannot be read statically"
        )
    required = probe_handle_fields()
    missing = required - published
    assert not missing, (
        "the module's published handle is missing fields the probe reads "
        f"(scripts/live_continuity_probe.py INPAGE_LIVENESS_JS): {sorted(missing)}"
    )


# --------------------------------------------------------------------------
# Node harness: the real INPAGE_LIVENESS_JS against a fake handle
# --------------------------------------------------------------------------

SCENE_ID = 1
INSTANCE_ID = "untitled.mov#1"
RECT = {"x": 109.35, "y": 795.04, "w": 951.54, "h": 267.62}
CANVAS_ID = "0-canvas"
EPOCH = 7
N_BANDS = html_alpha_probe.INPAGE_BAND_COUNT
N_OCCLUDED = 20  # measured occluder count, well under the 50 % ceiling

# One JS expression per handle field. Every field either side names must have an
# entry here, so an unrecognised published field fails the test loudly instead of
# being silently dropped from the fake.
HANDLE_FIELD_JS: dict[str, str] = {
    "gl": "{ isContextLost: function(){ return false; } }",
    "canvas": "canvas",
    "video": "{ paused: false }",
    "epoch": str(EPOCH),
    "sceneId": str(SCENE_ID),
    "instanceId": json.dumps(INSTANCE_ID),
    "rect": json.dumps(RECT),
    "canvasId": json.dumps(CANVAS_ID),
    "sample": "async function(n){ bumpIf('sample'); return makeSamples(n, paused); }",
    "markerBands": (
        "async function(){ bumpIf('markerBands'); "
        "return {dark: markerDark, light: markerLight, epoch: handle.epoch}; }"
    ),
    "pause": "async function(){ bumpIf('pause'); paused = true; }",
    "resume": "async function(){ bumpIf('resume'); paused = false; }",
}

_HARNESS = r"""
'use strict';
const OPTS = __OPTS__;
const N_BANDS = __N_BANDS__, N_OCCLUDED = __N_OCCLUDED__;

const stage = {nodeType: 1, isConnected: true, parentElement: null};
const canvas = {
  nodeType: 1, id: __CANVAS_ID__, isConnected: true, parentElement: stage,
  checkVisibility: function(){ return OPTS.visible !== false; },
};
stage.contains = function(node){ return node === canvas; };

globalThis.window = globalThis;
globalThis.document = {
  getElementById: function(id){ return id === 'stage' ? stage : null; },
};
window.getComputedStyle = function(){ return {opacity: '1'}; };
window.__obedLive = {snapshot: function(){ return {sceneId: __SCENE_ID__}; }};
window.__obedInpageSceneId = __SCENE_ID__;
window.__obedInpageRect = __RECT__;
window.__obedInpageInstanceId = __INSTANCE_ID__;

let paused = false;
let clock = 1000;
const markerDark = [], markerLight = [];
for (let i = 0; i < N_BANDS; i++) {
  markerDark.push(0);
  // An occluded band does not move between the dark and light marker frames.
  markerLight.push(i < N_OCCLUDED ? 0.2 : 60);
}

function makeSamples(n, isPaused){
  const out = [];
  for (let k = 0; k < n; k++) {
    const bands = [];
    for (let i = 0; i < N_BANDS; i++) {
      // Paused decoder: the replayed texture is frozen, so no band moves.
      bands.push(isPaused ? 10 + (i % 5) : 10 + (i % 5) + 2 * k);
    }
    clock += 4.4;
    out.push({
      t: clock, ms: 4.4, vt: 0.5 + k / 60, mediaTime: 0.5 + k / 60,
      bands: bands, control: 50, green: 100, greenRGB: [29, 177, 0], glErr: 0,
    });
  }
  return out;
}

function bumpIf(hook){ if (OPTS.epochBumpOn === hook) handle.epoch += 1; }

const handle = __HANDLE__;
for (const field of (OPTS.dropFields || [])) delete handle[field];
window.__OBED_GL_ORACLE__ = handle;
if (OPTS.standDown) delete window.__OBED_GL_ORACLE__;

(async function(){
  const result = await (__PROBE_JS__);
  console.log(JSON.stringify(result));
})().catch(function(e){
  console.log(JSON.stringify({harnessError: String((e && e.stack) || e)}));
  process.exitCode = 1;
});
"""


def run_probe_js_in_node(**opts) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to execute INPAGE_LIVENESS_JS")

    published = None
    try:
        from obed_edom import live_gl_replay_js  # type: ignore

        published = module_handle_fields(live_gl_replay_js.GL_REPLAY_JS)
    except Exception:  # noqa: BLE001 - S1 not landed: fall back to the probe's own contract
        published = None
    fields = published if published is not None else probe_handle_fields()

    unknown = set(fields) - set(HANDLE_FIELD_JS)
    assert not unknown, (
        "handle field(s) with no fake-value recipe in this test: "
        f"{sorted(unknown)} -- extend HANDLE_FIELD_JS deliberately"
    )
    missing = probe_handle_fields() - set(fields)
    assert not missing, f"fake handle would omit fields the probe reads: {sorted(missing)}"

    handle_js = "{\n" + ",\n".join(f"  {k}: {HANDLE_FIELD_JS[k]}" for k in sorted(fields)) + "\n}"
    script = (
        _HARNESS.replace("__OPTS__", json.dumps(opts))
        .replace("__N_BANDS__", str(N_BANDS))
        .replace("__N_OCCLUDED__", str(N_OCCLUDED))
        .replace("__CANVAS_ID__", json.dumps(CANVAS_ID))
        .replace("__SCENE_ID__", json.dumps(SCENE_ID))
        .replace("__RECT__", json.dumps(RECT))
        .replace("__INSTANCE_ID__", json.dumps(INSTANCE_ID))
        .replace("__HANDLE__", handle_js)
        .replace("__PROBE_JS__", probe.INPAGE_LIVENESS_JS)
    )
    run = subprocess.run([node, "-e", script], text=True, capture_output=True)
    assert run.returncode == 0, f"node failed: {run.stderr}\n{run.stdout}"
    raw = json.loads(run.stdout.strip().splitlines()[-1])
    assert "harnessError" not in raw, raw["harnessError"]
    return raw


def test_live_handle_reaches_ok_and_scores_live_with_a_dead_paused_control():
    raw = run_probe_js_in_node()
    assert raw["status"] == "ok", raw
    assert raw["canvasId"] == CANVAS_ID
    assert raw["epoch"] == EPOCH == raw["markerEpoch"]
    assert len(raw["samples"]) == html_alpha_probe.INPAGE_MIN_SAMPLES
    assert len(raw["pausedDecoderSamples"]) == html_alpha_probe.INPAGE_MIN_SAMPLES

    scored = probe.inpage_oracle_result(raw)
    assert scored is not None
    assert scored["status"] == "live", scored["reason"]
    assert scored["verdict"] is True
    assert scored["nBands"] == N_BANDS
    assert scored["occludedBands"] == N_OCCLUDED
    assert scored["judgedBands"] == N_BANDS - N_OCCLUDED
    assert scored["liveBands"] == N_BANDS - N_OCCLUDED or scored["liveBands"] == N_BANDS
    assert scored["glErrAny"] == 0
    paused = scored["controls"]["pausedDecoder"]
    assert paused["status"] == "dead" and paused["verdict"] is False, paused


def test_handle_absent_after_stand_down_is_not_applicable():
    raw = run_probe_js_in_node(standDown=True)
    assert raw == {
        "applicable": False,
        "status": "n/a",
        "reason": probe.INPAGE_HANDLE_ABSENT_REASON,
    }
    assert probe.inpage_applicability_reason(raw) == probe.INPAGE_HANDLE_ABSENT_REASON
    assert probe.inpage_oracle_result(raw) is None


@pytest.mark.parametrize("hook", ["markerBands", "pause", "sample", "resume"])
def test_epoch_moving_mid_window_is_rejected(hook):
    raw = run_probe_js_in_node(epochBumpOn=hook)
    assert raw["applicable"] is True
    assert raw["status"] == "inconclusive"
    assert raw["reason"] == "handle re-recorded during the sample window", raw
    scored = probe.inpage_oracle_result(raw)
    assert scored["verdict"] is None and scored["status"] == "inconclusive"


@pytest.mark.parametrize("field", ["gl", "canvas", "video", "sample", "markerBands", "pause", "resume"])
def test_a_handle_missing_any_required_field_is_inconclusive(field):
    raw = run_probe_js_in_node(dropFields=[field])
    assert raw == {
        "applicable": True,
        "status": "inconclusive",
        "reason": "handle is present but malformed",
    }
    assert probe.inpage_oracle_result(raw)["verdict"] is None


def test_an_invisible_canvas_is_inconclusive():
    """The fake is only trustworthy if the probe's own visibility re-check bites."""
    raw = run_probe_js_in_node(visible=False)
    assert raw["status"] == "inconclusive"
    assert raw["reason"] == "canvas is not visible", raw
