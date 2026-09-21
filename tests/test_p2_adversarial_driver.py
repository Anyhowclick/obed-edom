"""Driver-boundary tests for `scripts/p2_recovery_html_adversarial.py`.

These reach the browser/CDP driver (`ChromeCdp`, `_settle_bound_owner_rect`,
`_read_bound_owner_rect`) and the injected-JS strings
(`FOOTPRINT_BADGE_JS`, `NULL_CONTROL_JS`, `SPLIT_EVAL_JS`, `ADVANCE_KEY_WATCH_JS`),
which stay in the script rather than moving to `obed_edom.p2_verdict` -- src must
never launch Chrome or be async. The script is loaded by file path, same as
before the split; the pure-logic tests moved to `obed_edom.p2_verdict` and live
in `tests/test_p2_adversarial.py`, which imports the module instead.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent


def _load_adversarial_module():
    """Import `p2_recovery_html_adversarial` by file path.

    scripts/ and src/ are placed on `sys.path` first so the module's top-level
    `from p2_alpha_spike import ...` / `from obed_edom... import ...` resolve
    during exec (the module also inserts these itself, but doing it here keeps
    the very first import lookup working under a bare pytest invocation).
    """
    for sub in ("scripts", "src"):
        p = str(REPO / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location(
        "p2_recovery_html_adversarial", REPO / "scripts" / "p2_recovery_html_adversarial.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


p2 = _load_adversarial_module()

from test_p2_adversarial import _badge_sample  # noqa: E402


def _load_dissolve_live_module():
    """Import `p2_recovery_html_dissolve_live` by file path, same as `p2` above."""
    for sub in ("scripts", "src"):
        p = str(REPO / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location(
        "p2_recovery_html_dissolve_live", REPO / "scripts" / "p2_recovery_html_dissolve_live.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dissolve_live = _load_dissolve_live_module()


class _RectChrome:
    """Minimal CDP stand-in for `_read_bound_owner_rect`: replays a scripted
    series of owner rects, one per `evaluate()`."""

    def __init__(self, rects, then_moving: bool = False):
        self._rects = list(rects)
        self._then_moving = then_moving
        self.calls = 0

    async def evaluate(self, _script):
        if self.calls < len(self._rects):
            rect = self._rects[self.calls]
        elif self._then_moving:
            rect = _moving_rect(self.calls)
        else:
            rect = self._rects[-1]
        self.calls += 1
        return {"t": 100.0 + 16.7 * self.calls, "rect": rect}


def _moving_rect(i: int, step: float = 4.0):
    return {"x": 198.0 + step * i, "y": 797.0, "w": 952.0, "h": 268.0}


def _moving_rects(n: int):
    return [_moving_rect(i) for i in range(n)]


def _settle(chrome, el_id="el4", monkeypatch=None):
    monkeypatch.setattr(p2, "OWNER_SETTLE_POLL_S", 0.0)
    monkeypatch.setattr(p2, "OWNER_SETTLE_S", 0.5)
    return asyncio.run(p2._settle_bound_owner_rect(chrome, el_id))


def test_owner_rect_settle_rejects_a_still_moving_hash_7_build(monkeypatch):
    """Review r4 MAJOR 2. The hash reaching `#7` proves an instantaneous value,
    not a settled build: the `#7` build's own animation is still running, so a
    press sent there is a press during residual motion. Three CONSECUTIVE
    agreeing rect reads are required, and a moving rect never gets them."""
    chrome = _RectChrome(_moving_rects(4), then_moving=True)
    got = _settle(chrome, monkeypatch=monkeypatch)
    assert got["settled"] is False
    assert got["stableReadings"] < p2.OWNER_SETTLE_READINGS


def test_owner_rect_settle_accepts_a_stopped_build(monkeypatch):
    """...and a stopped rect settles, on exactly the `_couple_owner_rect`
    "measured" agreement the at-cut samples are held to."""
    still = {"x": 198.0, "y": 797.0, "w": 952.0, "h": 268.0}
    chrome = _RectChrome(_moving_rects(2) + [still] * 8)
    got = _settle(chrome, monkeypatch=monkeypatch)
    assert got["settled"] is True
    assert got["stableReadings"] == p2.OWNER_SETTLE_READINGS
    assert got["rect"] == still


def test_owner_rect_settle_fails_closed_without_a_bound_owner(monkeypatch):
    """No bind, no settle -- and no round trips either."""
    chrome = _RectChrome([None])
    got = _settle(chrome, el_id=None, monkeypatch=monkeypatch)
    assert got["settled"] is False
    assert chrome.calls == 0


def test_advance_key_watch_js_accepts_only_a_trusted_non_repeat_keydown():
    """The listener's own filter, read off the source: the event must be a
    `keydown`, an `ArrowRight`, `isTrusted`, and not an auto-repeat -- and a
    refusal is COUNTED (`rejected`), never silently dropped."""
    js = p2.ADVANCE_KEY_WATCH_JS
    assert "e.type !== 'keydown'" in js
    assert "e.key !== 'ArrowRight'" in js
    assert "e.isTrusted === true" in js
    assert "e.repeat !== true" in js
    assert "st.rejected += 1" in js
    assert "keyup" not in js, "a keyup can never stand in for the cut"


# --- review r3 MAJOR 2: one shared in-page split evaluation ----------------- #
def test_split_eval_js_is_one_evaluation_with_the_same_shape_in_both_branches():
    """A1/A2 previously returned LOCALLY at the split while B awaited a CDP
    round trip, so the absolute-target capture loop caught up differently
    afterwards -- settled progression or continuity could differ purely because
    B paused. Both branches are now one evaluation of the SAME source, with the
    same keys out."""
    released = p2.SPLIT_EVAL_JS % {"release": "true"}
    noop = p2.SPLIT_EVAL_JS % {"release": "false"}
    assert released != noop
    assert released.replace("var R = true;", "") == noop.replace("var R = false;", "")
    for key in ("t", "released", "controlPresent", "status", "releaseAt",
                "holdFrames", "paintCount", "coverPatchEnd"):
        assert f"{key}:" in released


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_split_eval_js_returns_the_same_keys_on_both_branches():
    """Executed, not just inspected: with no control present (the positive arms)
    and with one present, the returned object has identical keys."""
    harness = """
      var calls = 0;
      global.performance = {now: function () { return 1234.5; }};
      global.window = {};
      function run(src) { return eval(src); }
      var noop = run(%s);
      window.__OBED_NULL_CTRL__ = {release: function () {
        calls++;
        return {status: 'released', releaseAt: 9, holdFrames: 3, paintCount: 1,
                coverPatchEnd: {sum: 5}};
      }};
      var rel = run(%s);
      console.log(JSON.stringify({noop: Object.keys(noop).sort(),
                                  rel: Object.keys(rel).sort(),
                                  released: [noop.released, rel.released],
                                  calls: calls}));
    """ % (json.dumps(p2.SPLIT_EVAL_JS % {"release": "false"}),
           json.dumps(p2.SPLIT_EVAL_JS % {"release": "true"}))
    out = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["noop"] == got["rel"]
    assert got["released"] == [False, True]
    assert got["calls"] == 1, "the no-op branch must not release anything"


# --- review r3 BLOCKER 1 / MAJOR 3: the badge JS, EXECUTED ------------------ #
_BADGE_HARNESS = r"""
var cells = null, painted = [], rafQ = [], taskQ = [];
var video = {__obedElId: 'el4', rect: {left: 198, top: 797, width: 952, height: 268},
             getBoundingClientRect: function () {
               return {left: this.rect.left, top: this.rect.top,
                       width: this.rect.width, height: this.rect.height};
             }};
global.performance = {now: (function () { var t = 0; return function () { return (t += 16.7); }; })()};
global.requestAnimationFrame = function (fn) { rafQ.push(fn); return rafQ.length; };
global.setTimeout = function (fn) { taskQ.push(fn); };
global.document = {
  querySelectorAll: function () { return [video]; },
  body: {appendChild: function () {}},
  createElement: function () {
    return {style: {}, setAttribute: function () {},
            getContext: function () {
              return {fillStyle: '#000000',
                      fillRect: function (x) { cells[Math.round(x / CELL)] = this.fillStyle === '#ffffff' ? 1 : 0; }};
            }};
  }
};
global.window = {devicePixelRatio: 1, innerWidth: 1920};
var CELL = 6;
EVAL_BADGE
window.__OBED_FP_BADGE__.install('el4');
// Flush the install handoff (rAF -> task -> rAF) and then drive frames.
function frame() {
  var q = rafQ; rafQ = [];
  q.forEach(function (fn) { fn(); });
  var t = taskQ; taskQ = [];
  t.forEach(function (fn) { fn(); });
}
function step(label) {
  cells = new Array(NCELL).fill(0);
  frame();
  if (cells.some(function (c) { return c === 1; })) painted.push({label: label, cells: cells.slice()});
}
for (var i = 0; i < 4; i++) { step('pre' + i); video.rect.left += 1.5; }
video.__obedMotion = {started: 500, generation: 3};
for (var j = 0; j < 6; j++) { step('post' + j); video.rect.left += 1.5; }
console.log(JSON.stringify({painted: painted,
                            stats: window.__OBED_FP_BADGE__.stats(),
                            log: window.__OBED_FP_BADGE__.dump()}));
"""


def _run_badge_js() -> dict:
    src = _BADGE_HARNESS.replace(
        "EVAL_BADGE",
        "var NCELL = %d;\n%s" % (p2.FOOTPRINT_BADGE_CELLS, p2.FOOTPRINT_BADGE_JS),
    )
    out = subprocess.run(["node", "-e", src], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# A SIMULATED runtime footprint pin, ordered exactly as `keepThroughBridge` is:
# it starts from a post-frame TASK, applies the rect synchronously there, and
# re-queues from its OWN rAF callback. Registering in the task phase puts it
# BEHIND a badge loop that re-queued from its rAF callback -- which is the
# one-frame lag the re-handoff exists to undo.
_PIN_HARNESS = r"""
var cells = null, rafQ = [], taskQ = [], trace = [], pinTicks = 0;
var video = {__obedElId: 'el4', rect: {left: 200, top: 797, width: 952, height: 268},
             getBoundingClientRect: function () {
               return {left: this.rect.left, top: this.rect.top,
                       width: this.rect.width, height: this.rect.height};
             }};
global.performance = {now: (function () { var t = 0; return function () { return (t += 16.7); }; })()};
global.requestAnimationFrame = function (fn) { rafQ.push(fn); return rafQ.length; };
global.setTimeout = function (fn) { taskQ.push(fn); };
global.document = {
  querySelectorAll: function () { return [video]; },
  body: {appendChild: function () {}},
  createElement: function () {
    return {style: {}, setAttribute: function () {},
            getContext: function () {
              return {fillStyle: '#000000', fillRect: function () {}};
            }};
  }
};
global.window = {devicePixelRatio: 1, innerWidth: 1920};
EVAL_BADGE
var B = window.__OBED_FP_BADGE__;
B.install('el4');
function frame() {
  var q = rafQ; rafQ = [];
  q.forEach(function (fn) { fn(); });
  var t = taskQ; taskQ = [];
  t.forEach(function (fn) { fn(); });
}
function pinTick() {
  pinTicks += 1;
  video.rect.left = 200 + 10 * pinTicks;
  requestAnimationFrame(pinTick);
}
function startPin() {
  taskQ.push(function () {
    if (MARK_ON) video.__obedMotion = {started: 500, generation: 3};
    pinTick();
  });
}
function step(label) {
  var before = B.stats().seq;
  frame();
  var st = B.stats(), log = B.dump(), painted = [];
  for (var s = before + 1; s <= st.seq; s++) painted.push(log[s] ? log[s].rect : null);
  trace.push({label: label, painted: painted, endX: video.rect.left});
}
for (var i = 0; i < 3; i++) step('pre' + i);
startPin();
for (var j = 0; j < 8; j++) step('post' + j);
console.log(JSON.stringify({trace: trace, stats: B.stats()}));
"""


def _run_pin_js(mark_on: bool) -> dict:
    src = (
        _PIN_HARNESS
        .replace("EVAL_BADGE", "var NCELL = %d;\n%s"
                 % (p2.FOOTPRINT_BADGE_CELLS, p2.FOOTPRINT_BADGE_JS))
        .replace("MARK_ON", "true" if mark_on else "false")
    )
    out = subprocess.run(["node", "-e", src], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _pin_residuals(trace):
    """Per frame: (badge-painted x) - (rect the pin left on screen for it). 0 is
    the badge reading BEHIND the pin; negative is the one-frame lag."""
    out = []
    for fr in trace:
        rects = [r for r in fr["painted"] if r is not None]
        if len(rects) == 1:
            out.append((fr["label"], rects[0]["x"] - fr["endX"]))
    return out


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_footprint_badge_lands_behind_a_later_runtime_pin_callback():
    """Review r4 MINOR 2. Deterministic rAF/task ordering, with a simulated
    runtime pin scheduled AFTER the badge callback. Without the re-handoff the
    badge reads the pre-move rect and the composited frame shows the moved one --
    a lag of exactly one pin step, mutually consistent between badge pixels and
    badge log, so the coupling check cannot see it. With the re-handoff the badge
    paints NULL across the transfer and every later frame is residual-0."""
    lagged = _pin_residuals(_run_pin_js(mark_on=False)["trace"])
    after = [r for label, r in lagged if label.startswith("post")]
    assert after and set(after[1:]) == {-10.0}, after

    got = _run_pin_js(mark_on=True)
    assert got["stats"]["rehandoffs"] == 1
    post = [r for label, r in _pin_residuals(got["trace"]) if label.startswith("post")]
    # Exactly ONE lagged frame survives: the frame the pin STARTS on, where the
    # badge has already read before the task that creates the marker runs. It is
    # strictly before the trigger (which is the first poll frame that SEES the
    # departure) and therefore before `coverPaintedAt`, so it can never be in the
    # scored window. The transfer frames then paint a null rect, and every frame
    # that reads at all from there on is exactly on the pin's own rect.
    assert post[0] == -10.0, post
    assert set(post[1:]) == {0.0}, post


def _cells_to_frame(cells) -> np.ndarray:
    cell = p2.FOOTPRINT_BADGE_CELL_PX
    arr = np.zeros((cell * 2, len(cells) * cell, 4), dtype=np.uint8)
    arr[:, :, 3] = 255
    for c, bit in enumerate(cells):
        arr[0:cell, c * cell:(c + 1) * cell, :3] = 255 if bit else 0
    return arr


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_footprint_badge_js_paints_what_python_decodes():
    """End to end across the language boundary: the badge JS is EXECUTED against
    a stub DOM and the cells it actually paints are fed to the real Python
    decoder. The previous badge tests only proved the Python codec was
    self-consistent -- a JS-side encoding bug would have sailed through."""
    got = _run_badge_js()
    frames = [p for p in got["painted"] if p["label"].startswith("pre")]
    assert frames, "the badge must paint on every frame"
    decoded = [p2._decode_footprint_badge(_cells_to_frame(f["cells"])) for f in frames]
    assert all(d is not None and d["crcOk"] for d in decoded), "JS CRC must match Python's"
    seqs = [d["seq"] for d in decoded]
    assert seqs == sorted(set(seqs)), "strictly increasing sequence numbers"
    # ...and each painted rect matches the page's OWN log of that frame, which is
    # exactly what `_fill_badge_coupling` couples.
    for d in decoded:
        logged = got["log"][str(d["seq"])]
        if logged["rect"] is None:
            continue
        assert p2._couple_owner_rect(
            logged["rect"], {k: d[k] for k in ("x", "y", "w", "h")}
        )["source"] == "measured"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_footprint_badge_js_rehandoffs_behind_a_fresh_runtime_pin():
    """Review r3 BLOCKER 1. The install-time handoff only ordered the loop behind
    whatever pin existed THEN; keepThroughBridge's 3->4 pin starts later, from a
    task, so it registers its rAF AFTER this loop has re-queued from its own
    callback and from then on runs after us -- one frame of lag, mutually
    consistent between badge pixels and badge log, invisible to the coupling
    check. On a fresh `__obedMotion` generation the loop re-handoffs, and the
    frames spanning the handoff name a NULL rect so they can only ever be
    `unstable`."""
    got = _run_badge_js()
    assert got["stats"]["rehandoffs"] == 1
    assert got["stats"]["motionStartedAt"] == 500
    null_seqs = {int(s) for s, e in got["log"].items() if e["rect"] is None}
    assert set(got["stats"]["rehandoffSeqs"]) == null_seqs
    assert len(null_seqs) == 2, "this frame AND the intervening handoff frame"
    # A sample that caught one of those frames has a single reading -> unstable.
    seq = min(null_seqs)
    samples = [_badge_sample(seq, {"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0})]
    p2._fill_badge_coupling(samples, {str(seq): got["log"][str(seq)]})
    assert samples[0]["footprintSource"] == "unstable"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_footprint_badge_js_parses():
    result = subprocess.run(
        ["node", "--check", "-"], input=p2.FOOTPRINT_BADGE_JS, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_null_control_js_parses():
    """The JS itself cannot run under pytest (no browser/DOM) -- this only
    checks the `NULL_CONTROL_JS` source is syntactically valid, catching a
    typo/syntax error the Python-side tests above cannot see."""
    result = subprocess.run(
        ["node", "--check", "-"], input=p2.NULL_CONTROL_JS, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr


def test_null_controller_keydown_filter_matches_the_capture_watch():
    """r9 MAJOR 4 in the page source: the controller must apply the watch's own
    trust/repeat/type/key filter, record the EVENT's `timeStamp`, and count what
    it rejected -- the two listeners are only comparable if they agree."""
    import inspect
    body = inspect.getsource(p2)
    fn = body[body.index("function onAdvanceKey"):]
    fn = fn[: fn.index("\n  }") + 4]
    for needle in (
        "e.type !== 'keydown'", "e.key !== 'ArrowRight'", "e.isTrusted !== true",
        "e.repeat === true", "st.advanceKeyRejected += 1", "st.advanceKeyAt = e.timeStamp",
    ):
        assert needle in fn, needle
    assert "performance.now()" not in fn


def test_freeze_bracket_starts_chrome_inside_its_try():
    """The per-arm `close()` must cover `start()` too: starting outside the try
    leaks exactly the arm's Chrome when the attach fails."""
    import inspect

    src = inspect.getsource(p2._run_freeze_bracket)
    body = src[src.index("chrome = ChromeCdp("):]
    body = body[: body.index("finally:")]
    assert body.index("try:") < body.index("await chrome.start()"), (
        "chrome.start() runs outside the try that closes it"
    )


# --- `--reuse-export` must fail closed, never fall through to a real Keynote
# export or delete prior evidence (`.agents/plans/keynote-alpha.md:20` documents
# it as "Offline, no Keynote") ------------------------------------------------- #
def test_reuse_export_refuses_rather_than_exporting_via_keynote_when_the_export_is_missing(
    tmp_path, monkeypatch
):
    """With `--reuse-export` set and the reusable export missing, `main()` must
    refuse before anything destructive or Keynote/Chrome-launching runs -- not
    silently fall through to a real export."""
    monkeypatch.setattr(p2, "OUT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["p2_recovery_html_adversarial.py", "--reuse-export"])

    export_calls = []
    rmtree_calls = []
    keynote_calls = []
    run_calls = []
    monkeypatch.setattr(p2, "export_html", lambda *a, **k: export_calls.append((a, k)))
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: rmtree_calls.append((a, k)))
    monkeypatch.setattr(p2, "keynote_running", lambda: keynote_calls.append(True) or False)
    monkeypatch.setattr(asyncio, "run", lambda *a, **k: run_calls.append((a, k)))

    with pytest.raises(SystemExit, match="missing reusable export"):
        p2.main()

    assert export_calls == [], "export_html must never run when the reuse export is missing"
    assert rmtree_calls == [], "nothing destructive may run before the refusal"
    assert keynote_calls == [], "Keynote must never be probed before the refusal"
    assert run_calls == [], "the async driver must never start before the refusal"


def test_run_refuses_before_any_destructive_or_expensive_work_when_the_export_is_missing(
    tmp_path, monkeypatch
):
    """`main()`'s guard only protects the CLI entry point -- `_run` itself must be
    self-protecting too, since it already runs `shutil.rmtree(OUT / "runs")`,
    hashes the deck (`file_identity`), `inventory_deck`, and writes JSON before
    its old reuse check. Calls `_run` directly (real `asyncio.run`, not stubbed)
    with prior `runs/` evidence on disk and no reusable export."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    marker = runs_dir / "marker.txt"
    marker.write_text("prior run evidence")

    monkeypatch.setattr(p2, "OUT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["p2_recovery_html_adversarial.py", "--reuse-export"])

    rmtree_calls = []
    identity_calls = []
    inventory_calls = []
    export_calls = []
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: rmtree_calls.append((a, k)))
    monkeypatch.setattr(p2, "file_identity", lambda *a, **k: identity_calls.append((a, k)))
    monkeypatch.setattr(p2, "inventory_deck", lambda *a, **k: inventory_calls.append((a, k)))
    monkeypatch.setattr(p2, "export_html", lambda *a, **k: export_calls.append((a, k)))

    with pytest.raises(SystemExit, match="missing reusable export"):
        asyncio.run(p2._run(tmp_path / "html-player"))

    assert rmtree_calls == [], "nothing destructive may run before the refusal"
    assert identity_calls == [], "the deck must not be hashed before the refusal"
    assert inventory_calls == [], "the deck must not be inventoried before the refusal"
    assert export_calls == [], "export_html must never run when the reuse export is missing"
    assert marker.read_text() == "prior run evidence", "prior runs/ evidence must survive the refusal"


def test_dissolve_live_reuse_export_refuses_rather_than_deleting_prior_evidence_when_the_export_is_missing(
    tmp_path, monkeypatch
):
    """Plain `--reuse-export` (no `--handoff`/`--preserve`) with the export
    missing used to fall to the bake branch, which deletes EVERY prior run's
    evidence (`shutil.rmtree(OUT)`) before a real Keynote export. It must instead
    refuse -- and must not even hash the real 169 MB deck first."""
    monkeypatch.setattr(dissolve_live, "OUT", tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["p2_recovery_html_dissolve_live.py", "--reuse-export"]
    )

    export_calls = []
    rmtree_calls = []
    keynote_calls = []
    run_calls = []
    identity_calls = []
    inventory_calls = []
    monkeypatch.setattr(dissolve_live, "export_html", lambda *a, **k: export_calls.append((a, k)))
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: rmtree_calls.append((a, k)))
    monkeypatch.setattr(dissolve_live, "keynote_running", lambda: keynote_calls.append(True) or False)
    monkeypatch.setattr(asyncio, "run", lambda *a, **k: run_calls.append((a, k)))
    monkeypatch.setattr(
        dissolve_live, "file_identity",
        lambda *a, **k: identity_calls.append((a, k)) or {"sha256": "x"},
    )
    monkeypatch.setattr(
        dissolve_live, "inventory_deck",
        lambda *a, **k: inventory_calls.append((a, k)) or {},
    )

    with pytest.raises(SystemExit, match="missing reusable export"):
        dissolve_live.main()

    assert export_calls == [], "export_html must never run when the reuse export is missing"
    assert rmtree_calls == [], "prior evidence must not be deleted before the refusal"
    assert keynote_calls == [], "Keynote must never be probed before the refusal"
    assert run_calls == [], "the async driver must never start before the refusal"


def test_burst_offsets_come_from_the_probe():
    """One burst cadence for both instruments — never a re-tuned local copy."""
    if str(REPO / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO / "scripts"))
    import live_continuity_probe

    assert p2.BURST_OFFSETS_MS == live_continuity_probe.BURST_OFFSETS_MS
    assert len(set(p2.BURST_OFFSETS_MS)) == len(p2.BURST_OFFSETS_MS)


def test_findings_inventory_is_still_fourteen_and_renamed():
    import re

    ids = re.findall(
        r'"id": "(\w+)"',
        (REPO / "scripts" / "p2_recovery_html_adversarial.py").read_text(encoding="utf-8"),
    )
    assert len(ids) == 14
    assert "refusedCarry1to2" in ids
    assert "continueThroughMagicMove1to2" not in ids
    assert "freezeControlCaughtByCounter" in ids


# --------------------------------------------------------------------------- #
# Chrome lifecycle: a spawned browser the driver never attached to is an ORPHAN
# (observed live: a `chrome-profile-a2` headless Chrome outliving its run by
# 36 minutes, parent launchd, holding the machine while the next round tried to
# measure trigger latency on it).
# --------------------------------------------------------------------------- #
def test_chrome_start_kills_its_process_when_the_attach_fails(tmp_path, monkeypatch):
    """`/usr/bin/yes` stays alive under Chrome's argv and never opens a CDP port,
    so `start()` must fail AND leave no process behind."""
    import subprocess
    from pathlib import Path

    if str(REPO / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO / "scripts"))
    import p2_alpha_spike as spike

    monkeypatch.setattr(spike.ChromeCdp, "START_TIMEOUT_S", 0.3)
    c = spike.ChromeCdp(Path("/usr/bin/yes"), tmp_path / "profile")
    with pytest.raises(RuntimeError):
        asyncio.run(c.start())
    assert c.proc is not None
    assert c.proc.poll() is not None, "Chrome survived a failed start()"
    assert isinstance(c.proc, subprocess.Popen)
