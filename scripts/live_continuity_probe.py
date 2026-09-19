#!/usr/bin/env python3
"""HOST gate: does the live host's injected movie-continuity runtime carry decoder
identity and playback clock through the same boundaries P2 proved offline (offline,
in `scripts/p2_recovery_html_adversarial.py`), when driven through `LiveOutputHost`
instead of a bare page?

Three arms in one artifact:
  A. continuity on -> continue1to2, restart2to3, continue3to4 all TRUE.
  B. OBED_LIVE_CONTINUITY=off -> raw player; continue3to4 expected FALSE (the
     Keynote HTML-export bug the continuity runtime repairs); 1->2 is reported as
     measured, not assumed.
  C. continuity on, but the bridge boundary is stripped by a PROBE-ONLY monkeypatch
     of `ContinuityPlan.to_runtime` (no product switch) -> continue3to4 FALSE while
     continue1to2 stays TRUE (isolates the repair to the 3->4 boundary).
Then one ATTACH-mode run (arm A only): the host attaches over CDP to a headless
Chrome this script launches itself, confirms `qualified`, all three verdicts, and a
transparent page background, then kills that Chrome by pid.

Verdicts are decoder-identity + playback-clock based (a stable element id, a
monotonic non-decreasing `video.currentTime`, and -- when continuity is installed --
the runtime's own `footprintOwnerDecoderId`), never a screenshot MAE and never a
sleep as proof. If the tracked movie never decodes, the verdict is INCONCLUSIVE, not
a false pass/fail.

Does not qualify HDMI, alpha compositing, or audio. Offline/local Chrome only.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from obed_edom import live_host as live_host_module  # noqa: E402
from obed_edom import live_continuity as live_continuity_module  # noqa: E402
from obed_edom.html_preview import cache_dir  # noqa: E402
from obed_edom.live_continuity import ContinuityPlan, Unsupported, derive_plan  # noqa: E402
from obed_edom.live_host import ATTACH_ENV, CONTINUITY_ENV, LiveOutputHost, OutputDisplay, PlayerCommandRejected  # noqa: E402

import live_host_probe  # noqa: E402 - reuse the headless window-size compensation

FIXTURE = Path(
    "/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/"
    "output/p2-recovery/html-adversarial/html-player"
)
ORIGINAL_INDEX = Path(
    "/Users/anyhowclick/Desktop/work/obed-edom/.claude/worktrees/keynote-parser-module-error-46801c/"
    "output/p2-recovery/html-adversarial/html-unmodified/index.html"
)
ARTIFACT = Path("output/keynote-live-planning-2026-09-19/live-continuity-probe.json")
PROBE_DIGEST = "b" * 64
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

VIEWPORT_WIDTH, VIEWPORT_HEIGHT = 1920, 1080

MIN_ADVANCE_S = 0.5
MAX_STALL_S = 0.3
MAX_DROP_S = 0.05
RESTART_MAX_START_S = 0.5
RECT_TOLERANCE_PX = 3.0
CLICK_DELAY_S = 1.5
POST_ADVANCE_SETTLE_S = 1.8
VIDEO_DECODE_TIMEOUT_S = 8.0
MAX_ADVANCE_STEPS = 40
# Window discipline (reviewer finding #1/#2): a "sometime before, sometime after"
# check on the whole run cannot see a multi-second freeze or an owner handoff
# that only holds outside the window actually being cut. Every continuity verdict
# is instead scored over a WINDOW: [last settled sample before the boundary scene,
# first settled sample at/after it] padded by WINDOW_PAD_S on each side. 2.0s (well
# over the spec's ">= 0.5s" floor) so the window comfortably covers the preserve
# runtime's own documented remount-retry schedule (delays up to 2000ms in
# `live_continuity_js.py`'s `scheduleRemount`) -- a freeze inside that retry
# window is exactly the failure mode this instrument exists to catch.
WINDOW_PAD_S = 2.0

# In headless Chrome, --window-size=W,H yields innerHeight H-32 (chrome window
# chrome persists even headless) -- reuse live_host_probe's measured compensation
# rather than re-deriving it.
_HEIGHT_PAD = live_host_probe.HEADLESS_CHROME_HEIGHT_PAD

SAMPLER_JS = r"""
(function(){
  if (window.__obedContinuityProbe__) return true;
  var nextId = 1;
  var samples = [];
  var MAX_SAMPLES = 20000;
  function idFor(v){ if (v.__obedProbeId == null) v.__obedProbeId = nextId++; return v.__obedProbeId; }
  function stateOf(){
    try { return window.__obedLive ? window.__obedLive.snapshot() : {}; } catch (e) { return {}; }
  }
  // footprintOwnerDecoderId classifies a rect against a FIXED footprint table
  // (the static 1->2 slot) when no rect.key is given -- a rect away from that
  // slot (e.g. the moving/scaling 3->4 destination) is then unclassifiable and
  // returns via:'unknown-key', per its own documented contract ("the caller may
  // pin the asset key directly (rect.key) when it queries a rect the fixed
  // footprint table does not classify"). Resolve the key ourselves from the
  // already-public plan object (window.__OBED_CONTINUITY__, never mutated here)
  // the same way the runtime's own movieAssetKey() does, so ownership can be
  // asked about ANY on-screen position, not just the static footprint.
  function movieKeyFor(src){
    try {
      var plan = window.__OBED_CONTINUITY__;
      var movies = (plan && plan.movies) || {};
      var s = String(src || '').toLowerCase();
      for (var k in movies) {
        var keys = (movies[k] && movies[k].assetKeys) || [];
        for (var i = 0; i < keys.length; i++) {
          if (s.indexOf(String(keys[i]).toLowerCase()) >= 0) return k;
        }
      }
    } catch (e) {}
    return null;
  }
  function ownerOf(rect, src, map){
    try {
      if (!(window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.footprintOwnerDecoderId)) return null;
      if (!map) return null;
      var q = {x: (rect.x - map.ox) / map.s, y: (rect.y - map.oy) / map.s, w: rect.w / map.s, h: rect.h / map.s};
      var key = movieKeyFor(src);
      if (key) q.key = key;
      return window.__OBED_P2_PRESERVE__.footprintOwnerDecoderId(q);
    } catch (e) { return null; }
  }
  // The probe's OWN read of the stage map, independent of the runtime's --
  // `#stage.offsetWidth/Height` is the transform-blind authored size,
  // `getBoundingClientRect()` is the on-screen (post-transform) rect. Every
  // sampled video rect is converted from screen to authored space in Python
  // using this per-sample map, never the runtime's own `stageMap()`.
  function stageMapOf(){
    var el = document.getElementById('stage');
    if (!el) return null;
    var r = el.getBoundingClientRect();
    var ow = el.offsetWidth, oh = el.offsetHeight;
    if (!ow || !oh || !r.width || !r.height) return null;
    return {s: r.width / ow, sy: r.height / oh, ox: r.left, oy: r.top, offsetWidth: ow, offsetHeight: oh};
  }
  function tick(){
    var t = performance.now();
    var state = stateOf();
    var map = stageMapOf();
    var videos = [];
    document.querySelectorAll('video').forEach(function(v){
      var r = v.getBoundingClientRect();
      var rect = {x: r.left, y: r.top, w: r.width, h: r.height};
      var src = String(v.currentSrc || v.src || '').split('/').pop();
      videos.push({
        id: idFor(v),
        elId: (v.__obedElId != null ? v.__obedElId : null),
        src: src,
        currentTime: v.currentTime,
        paused: v.paused,
        readyState: v.readyState,
        videoWidth: v.videoWidth,
        isConnected: document.contains(v),
        rect: rect,
        footprintOwner: ownerOf(rect, v.currentSrc || v.src || '', map)
      });
    });
    samples.push({t: t, scene: state.sceneId, playerState: state.playerState, busy: state.busy, videos: videos, stageMap: map});
    if (samples.length > MAX_SAMPLES) samples.shift();
    window.__obedContinuityProbe__.raf = requestAnimationFrame(tick);
  }
  window.__obedContinuityProbe__ = {samples: samples};
  window.__obedContinuityProbe__.raf = requestAnimationFrame(tick);
  return true;
})();
"""

ENSURE_PLAYING_JS = (
    "Array.from(document.querySelectorAll('video')).forEach(function(v){"
    "try{v.muted=true;var p=v.play();if(p&&p.catch)p.catch(function(){});}catch(e){}});true"
)


def parse_viewport_arg(value: str) -> tuple[int, int]:
    """Launch-mode arms run at this viewport (the attach arm ignores it -- see
    `run_attach_arm`, fixed at `VIEWPORT_WIDTH`/`VIEWPORT_HEIGHT` by the live
    host's own attach contract)."""
    try:
        width, height = live_host_probe.parse_viewport(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid --viewport {value!r}: expected WxH") from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError(f"invalid --viewport {value!r}: expected WxH") from None
    return width, height


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--original-index", type=Path, default=ORIGINAL_INDEX)
    parser.add_argument("--artifact", type=Path, default=ARTIFACT)
    parser.add_argument(
        "--viewport", type=parse_viewport_arg, default=(VIEWPORT_WIDTH, VIEWPORT_HEIGHT),
        help="Forced headless viewport for the launch-mode arms, e.g. 2560x1440 (default 1920x1080)",
    )
    return parser.parse_args(argv)


def prepare_export(fixture: Path, original_index: Path, tag: str) -> Path:
    """Mirror `live_host_probe.main`'s fixture prep: clone the already-built player
    export, then overwrite index.html with the UNMODIFIED one so the host's own
    `_program_html` injects everything fresh (the fixture's index.html already has
    P2's own script tags baked in, which would collide)."""
    destination = cache_dir(PROBE_DIGEST) / f"html-{tag}"
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixture, destination)
    shutil.copy2(original_index, destination / "index.html")
    return destination


def load_slides(export_root: Path) -> list[dict[str, Any]]:
    header = json.loads((export_root / "assets" / "header.json").read_text())
    return [
        {"originalOrdinal": index + 1, "playerIndex": index, "exportedUuid": slide, "skipped": False}
        for index, slide in enumerate(header["slideList"])
    ]


def force_viewport(width: int, height: int) -> None:
    forced = OutputDisplay(0, 0, 0, width, height + _HEIGHT_PAD, True)
    live_host_module.choose_display = lambda *_a, **_k: forced


def ground_truth_plan(export_root: Path, slides: list[dict[str, Any]]) -> ContinuityPlan:
    plan = derive_plan(export_root, slides)
    if isinstance(plan, Unsupported):
        raise SystemExit(f"fixture does not derive a continuity plan: {plan.reason}")
    return plan


def ground_truth_facts(plan: ContinuityPlan) -> dict[str, Any]:
    """Independent, offline ground truth (never injected into the host): the
    bridging asset, the scene onset of each of the three boundaries under test, and
    the authored rects the tracked decoder must be on-screen at either side of each
    boundary (reviewer finding #1: "same id existed sometime before/after" is not
    enough -- it must be at the RIGHT rect, not merely present somewhere)."""
    bridge = None
    pin = None
    for boundary in plan.boundaries:
        for movie in boundary.movies:
            if movie.action == "bridge":
                bridge = (boundary, movie)
            elif movie.action == "pin" and pin is None:
                pin = (boundary, movie)
    if bridge is None:
        raise SystemExit("fixture has no bridge boundary (expected the 3->4 moving Magic Move)")
    if pin is None:
        raise SystemExit("fixture has no pin boundary (expected the 1->2 static Magic Move)")
    _, bridge_movie = bridge
    _, pin_movie = pin
    ordered_players = sorted(plan.scene_index_by_player)
    if len(ordered_players) < 4:
        raise SystemExit("fixture must have at least 4 slides")
    pin_rect = (pin_movie.dst_rect or pin_movie.src_rect)
    if pin_rect is None or bridge_movie.src_rect is None or bridge_movie.dst_rect is None:
        raise SystemExit("fixture's continuity plan is missing a required rect")
    return {
        "asset": bridge_movie.asset,
        "onset1to2": plan.scene_index_by_player[ordered_players[1]],
        "restartScene": plan.scene_index_by_player[ordered_players[2]],
        "bridgeScene": plan.scene_index_by_player[ordered_players[3]],
        "pinRect": pin_rect.as_dict(),
        "bridgeSrcRect": bridge_movie.src_rect.as_dict(),
        "destRect": bridge_movie.dst_rect.as_dict(),
        "canvas": dict(plan.canvas),
    }


@contextmanager
def bridge_disabled() -> Iterator[None]:
    """Arm C only: strip the bridge boundary from every derived runtime plan inside
    this probe PROCESS -- a monkeypatch of `ContinuityPlan.to_runtime`, never a
    product code path. The pin (1->2) and restart (2->3) behaviour are untouched;
    with no bridge boundary the runtime's own `slide4MinHash()` is null, so the
    3->4 magic move falls through to the export's native (broken) restart."""
    original = live_continuity_module.ContinuityPlan.to_runtime

    def patched(self: ContinuityPlan) -> dict[str, Any] | Unsupported:
        runtime = original(self)
        if isinstance(runtime, Unsupported):
            return runtime
        runtime = dict(runtime)
        runtime["boundaries"] = [b for b in runtime.get("boundaries", []) if b.get("action") != "bridge"]
        return runtime

    live_continuity_module.ContinuityPlan.to_runtime = patched
    try:
        yield
    finally:
        live_continuity_module.ContinuityPlan.to_runtime = original


def wait_for_decode(player: LiveOutputHost, timeout_s: float = VIDEO_DECODE_TIMEOUT_S) -> bool:
    transport = player._require_transport()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        ok = transport.evaluate(
            "Array.from(document.querySelectorAll('video')).some("
            "function(v){return v.readyState>=2&&v.videoWidth>0;})"
        )
        if ok:
            return True
        time.sleep(0.1)
    return False


def advance_until_original_slide(
    player: LiveOutputHost, target: int, *, max_steps: int = MAX_ADVANCE_STEPS, settle_s: float = POST_ADVANCE_SETTLE_S
) -> None:
    """Click 'advance' until the host reports it is showing `target` (1-based
    original ordinal), tolerating busy/rejected states the way an operator would --
    never a bare sleep as proof of arrival."""
    for _ in range(max_steps):
        observed = player.observe()
        if observed.original_slide == target:
            return
        if observed.busy:
            time.sleep(0.1)
            continue
        if not player.capabilities()["advance"]["supported"]:
            raise RuntimeError(f"cannot advance further toward slide {target}; stuck at {observed.original_slide}")
        try:
            player.execute("advance")
        except PlayerCommandRejected:
            time.sleep(0.1)
            continue
        time.sleep(settle_s)
    observed = player.observe()
    if observed.original_slide != target:
        raise RuntimeError(f"did not reach slide {target}; stopped at {observed.original_slide}")


def drive_and_sample(player: LiveOutputHost) -> list[dict[str, Any]]:
    transport = player._require_transport()
    transport.evaluate(SAMPLER_JS)
    transport.evaluate(ENSURE_PLAYING_JS)
    wait_for_decode(player)
    time.sleep(CLICK_DELAY_S)
    advance_until_original_slide(player, 2)  # 1->2 magic move
    advance_until_original_slide(player, 3)  # 2->3 dissolve (may straddle slide-2 builds)
    advance_until_original_slide(player, 4)  # 3->4 magic move
    time.sleep(POST_ADVANCE_SETTLE_S)
    samples = transport.evaluate("window.__obedContinuityProbe__.samples")
    return samples if isinstance(samples, list) else []


def track_by_id(samples: list[dict[str, Any]], asset_substr: str) -> dict[int, list[dict[str, Any]]]:
    tracks: dict[int, list[dict[str, Any]]] = {}
    for sample in samples:
        for video in sample.get("videos") or []:
            src = str(video.get("src") or "").lower()
            if asset_substr in src:
                row = dict(video)
                row["t"] = sample.get("t")
                row["scene"] = sample.get("scene")
                row["playerState"] = sample.get("playerState")
                row["busy"] = sample.get("busy")
                tracks.setdefault(video["id"], []).append(row)
    return tracks


def decoded_anywhere(tracks: dict[int, list[dict[str, Any]]]) -> bool:
    return any(
        (row.get("readyState") or 0) >= 2 and (row.get("videoWidth") or 0) > 0
        for rows in tracks.values()
        for row in rows
    )


def stage_map_valid(stage_map: dict[str, Any] | None) -> bool:
    """Fail-closed: missing `#stage`, a zero box, or a non-uniform scale (`|s -
    sy| / s` over 0.1%) is invalid, never silently treated as identity."""
    if not isinstance(stage_map, dict):
        return False
    s, sy = stage_map.get("s"), stage_map.get("sy")
    ow, oh = stage_map.get("offsetWidth"), stage_map.get("offsetHeight")
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (s, sy, ow, oh)):
        return False
    return abs(s - sy) / s <= 0.001


def to_authored_rect(rect: dict[str, float], stage_map: dict[str, Any]) -> dict[str, float]:
    s = stage_map["s"]
    return {
        "x": (rect["x"] - stage_map["ox"]) / s,
        "y": (rect["y"] - stage_map["oy"]) / s,
        "w": rect["w"] / s,
        "h": rect["h"] / s,
    }


def convert_samples_to_authored(samples: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Convert every sampled `<video>` rect from screen to AUTHORED space using
    that sample's own recorded stage map, before any scoring runs -- so every
    existing threshold and red control (all authored) applies unchanged. The
    raw screen rect is kept under `rectScreen` for evidence; a missing/invalid
    stage map leaves `rect` as None, a scoring failure (see `stageMapInvalid`
    in `score_continuity`), never a silent skip."""
    converted: list[dict[str, Any]] = []
    invalid_count = 0
    for entry in samples:
        stage_map = entry.get("stageMap")
        valid = stage_map_valid(stage_map)
        if not valid:
            invalid_count += 1
        new_entry = dict(entry)
        new_videos = []
        for video_row in entry.get("videos") or []:
            new_video = dict(video_row)
            screen_rect = video_row.get("rect")
            new_video["rectScreen"] = screen_rect
            new_video["rect"] = to_authored_rect(screen_rect, stage_map) if valid and isinstance(screen_rect, dict) else None
            new_video["stageMapValid"] = valid
            new_videos.append(new_video)
        new_entry["videos"] = new_videos
        new_entry["stageMapValid"] = valid
        converted.append(new_entry)
    return converted, invalid_count


def expected_stage_fit(canvas: dict[str, Any], viewport: dict[str, Any]) -> dict[str, float]:
    """Aspect-fit of the authored `canvas` into `viewport` -- the stage map the
    player's own `adjustStageToFit` should have produced."""
    fit = live_host_probe.expected_fit(canvas, viewport)
    scale = min(viewport["width"] / canvas["width"], viewport["height"] / canvas["height"])
    return {**fit, "scale": scale}


def stage_screen_rect(stage_map: dict[str, Any]) -> dict[str, float]:
    return {
        "x": stage_map["ox"], "y": stage_map["oy"],
        "width": stage_map["offsetWidth"] * stage_map["s"], "height": stage_map["offsetHeight"] * stage_map["sy"],
    }


def stage_fit_matches(observed: dict[str, float], expected: dict[str, float], tol_px: float = 1.0, tol_rel: float = 0.001) -> bool:
    return all(
        abs(observed[key] - expected[key]) <= max(tol_px, abs(expected[key]) * tol_rel)
        for key in ("x", "y", "width", "height")
    )


def score_stage_fit(samples: list[dict[str, Any]], expected: dict[str, float]) -> dict[str, Any]:
    """A wrong stage fit fails the arm outright: the authored conversion is
    only meaningful against a correctly fitted stage. Boundary scoring only
    ever looks inside the selected decoder's crossing windows, so a
    missing/non-uniform stage-map sample OUTSIDE those windows would
    otherwise never be noticed -- require zero invalid samples across the
    WHOLE arm, not just the fitted ones, and zero samples at all is "no
    evidence", never a pass."""
    valid_maps = [entry["stageMap"] for entry in samples if entry.get("stageMapValid")]
    invalid_count = sum(1 for entry in samples if not entry.get("stageMapValid"))
    if not samples or not valid_maps:
        return {
            "verdict": False, "reason": "no valid stage map samples",
            "sampleCount": len(valid_maps), "invalidCount": invalid_count, "expected": expected,
        }
    mismatches = [stage_screen_rect(m) for m in valid_maps if not stage_fit_matches(stage_screen_rect(m), expected)]
    return {
        "verdict": not mismatches and invalid_count == 0,
        "sampleCount": len(valid_maps), "mismatchCount": len(mismatches), "invalidCount": invalid_count,
        "expected": expected,
    }


def stage_map_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    valid_maps = [entry["stageMap"] for entry in samples if entry.get("stageMapValid")]
    if not valid_maps:
        return {"sampleCount": 0}
    return {
        "sampleCount": len(valid_maps),
        "sMin": min(m["s"] for m in valid_maps), "sMax": max(m["s"] for m in valid_maps),
        "oxMin": min(m["ox"] for m in valid_maps), "oxMax": max(m["ox"] for m in valid_maps),
        "oyMin": min(m["oy"] for m in valid_maps), "oyMax": max(m["oy"] for m in valid_maps),
    }


def rect_matches(rect: dict[str, float] | None, expected: dict[str, float], tolerance: float = RECT_TOLERANCE_PX) -> bool:
    if not isinstance(rect, dict):
        return False
    return all(abs(rect.get(key, 1e9) - expected[key]) <= tolerance for key in ("x", "y", "w", "h"))


def path_progress(
    rect: dict[str, float] | None, src: dict[str, float], dst: dict[str, float], tolerance: float
) -> float | None:
    if not isinstance(rect, dict):
        return None
    keys = ("x", "y", "w", "h")
    if any(not isinstance(rect.get(key), (int, float)) or not math.isfinite(rect[key]) for key in keys):
        return None
    deltas = {key: dst[key] - src[key] for key in keys}
    length_squared = sum(delta * delta for delta in deltas.values())
    if not length_squared:
        return None
    progress = sum((rect[key] - src[key]) * deltas[key] for key in keys) / length_squared
    progress = min(1.0, max(0.0, progress))
    expected = {key: src[key] + progress * deltas[key] for key in keys}
    return progress if rect_matches(rect, expected, tolerance) else None


def is_move_sample(row: dict[str, Any], transition_scene: float | None) -> bool:
    return (
        transition_scene is not None
        and row.get("scene") == transition_scene
        and row.get("playerState") == "Playing"
        and row.get("busy") is True
    )


def is_move_complete(row: dict[str, Any], transition_scene: float | None) -> bool:
    """The move has finished but the player has not yet cut to the next scene:
    still `transition_scene`, but no longer the `Playing`+busy move sample. Real
    traces show the player pass through more than one such state before the cut
    (`IdleAtFinalState`, then `WaitingToJump`, then `SettingUpScene`) -- the movie
    is already parked at the destination rect throughout all of them, so every one
    of them is a "move complete" sample, not only the first."""
    return (
        transition_scene is not None
        and row.get("scene") == transition_scene
        and not is_move_sample(row, transition_scene)
    )


def score_motion(
    rows: list[dict[str, Any]], src: dict[str, float], dst: dict[str, float], tolerance: float
) -> dict[str, Any]:
    progress = [path_progress(row.get("rect"), src, dst, tolerance) for row in rows]
    errors = []
    if not rows:
        errors.append("moving transition not observed")
    elif any(value is None for value in progress):
        errors.append("transition rectangle leaves the shared source-to-destination path")
    else:
        jitter = tolerance / max(abs(dst[key] - src[key]) for key in src)
        if progress[0] > 0.1:
            errors.append("transition begins away from the source")
        if progress[-1] < 0.9:
            errors.append("transition does not approach the destination")
        peak = progress[0]
        for value in progress[1:]:
            if value < peak - jitter:
                errors.append("transition progress reverses")
                break
            peak = max(peak, value)
        if any(b - a > 0.25 for a, b in zip([0.0, *progress], [*progress, 1.0])):
            errors.append("transition jumps over the path")
        interior = [value for value in progress if 0.1 < value < 0.9]
        if len(interior) < 3 or min(interior, default=1.0) > 0.25 or max(interior, default=0.0) < 0.75:
            errors.append("transition lacks meaningful interior samples")
    return {"sampleCount": len(rows), "progress": progress, "errors": errors}


def find_boundary_window(
    samples: list[dict[str, Any]], boundary_scene: float, *, pad_s: float = WINDOW_PAD_S
) -> dict[str, float] | None:
    """The window a continuity verdict is scored over: from the last settled sample
    with `scene < boundary_scene` to the first settled sample with `scene >=
    boundary_scene`, padded by `pad_s` on each side and clipped to the samples
    actually collected. Returns None if the crossing never happened (both sides of
    the boundary must be represented and ordered)."""
    times = [s["t"] for s in samples if s.get("t") is not None]
    if not times:
        return None
    before_times = [s["t"] for s in samples if s.get("scene") is not None and s["scene"] < boundary_scene]
    after_times = [s["t"] for s in samples if s.get("scene") is not None and s["scene"] >= boundary_scene]
    if not before_times or not after_times:
        return None
    last_before = max(before_times)
    first_after = min(after_times)
    if last_before >= first_after:
        return None
    lo, hi = min(times), max(times)
    return {
        "start": max(last_before - pad_s * 1000.0, lo),
        "end": min(first_after + pad_s * 1000.0, hi),
        "lastBeforeT": last_before,
        "firstAfterT": first_after,
    }


def _longest_stall_run(rows: list[dict[str, Any]], max_stall_s: float) -> dict[str, Any]:
    """Accumulate the duration of CONSECUTIVE samples where the unpaused decoder's
    clock did not advance (reviewer finding #2: comparing only consecutive ~16ms
    rAF samples against the threshold never sees a multi-second freeze spread over
    many non-advancing samples). Returns the longest such accumulated run and
    whether it exceeds `max_stall_s`."""
    longest_s = 0.0
    longest_end_ms: float | None = None
    run_s = 0.0
    for a, b in zip(rows, rows[1:]):
        dt_wall = (b["t"] - a["t"]) / 1000.0
        d_clock = b["currentTime"] - a["currentTime"]
        frozen = d_clock <= 1e-3 and not b.get("paused")
        if frozen:
            run_s += dt_wall
            if run_s > longest_s:
                longest_s = run_s
                longest_end_ms = b["t"]
        else:
            run_s = 0.0
    stalled = longest_s > max_stall_s
    return {"longestStallS": round(longest_s, 3), "stalled": stalled, "longestStallEndMs": longest_end_ms}


def score_continuity(
    samples: list[dict[str, Any]],
    asset_substr: str,
    boundary_scene: float,
    src_rect: dict[str, float],
    dst_rect: dict[str, float],
    runtime_installed: bool,
    *,
    min_advance_s: float = MIN_ADVANCE_S,
    max_stall_s: float = MAX_STALL_S,
    max_drop_s: float = MAX_DROP_S,
    rect_tolerance: float = RECT_TOLERANCE_PX,
    pad_s: float = WINDOW_PAD_S,
    transition_scene: float | None = None,
) -> dict[str, Any]:
    """Pure: samples in, verdict dict out. Scores continuity of ONE tracked decoder
    across `boundary_scene`, evaluated only within the crossing window (reviewer
    finding #1), requiring (all within the window):
      - the same element id present in every sampled frame in the window;
      - when `runtime_installed`, every after-cut sample reports that element (by
        the continuity runtime's own `footprintOwnerDecoderId`) as footprint owner;
      - connected at the authored source before / destination after (3px);
      - only a specified Playing transition scene may use a monotonic shared
        source-to-destination path; its IdleAtFinalState must be at destination;
      - a monotonic clock (no drop beyond float jitter);
      - the longest zero-advance run at or under `max_stall_s`;
      - total clock advance within the window at least `min_advance_s`.
    """
    tracks = track_by_id(samples, asset_substr)
    if not decoded_anywhere(tracks):
        return {"verdict": None, "reason": "inconclusive: movie never decoded"}
    window = find_boundary_window(samples, boundary_scene, pad_s=pad_s)
    if window is None:
        return {"verdict": False, "reason": "boundary crossing not observed in samples"}
    if transition_scene is not None:
        # Ground the window's start at the first SETTLED sample of the from-slide's
        # own scene (transition_scene - 1), not a blind pad_s before the crossing
        # into transition_scene: a deliberate decoder restart can sit right before
        # the move, and padding further back reaches into the PRIOR scene, before
        # that restart, where the continuing decoder cannot exist yet -- any
        # missing sample there would be a false failure, not evidence of anything.
        # Grounding here still covers the entire move (which starts later, inside
        # transition_scene) and the settled source phase that precedes it.
        settled_source_times = [
            s["t"]
            for s in samples
            if s.get("scene") == transition_scene - 1 and s.get("busy") is False
        ]
        if settled_source_times:
            window["start"] = min(window["start"], min(settled_source_times))
        else:
            move_window = find_boundary_window(samples, transition_scene, pad_s=pad_s)
            if move_window is not None:
                window["start"] = min(window["start"], move_window["start"])
    windowed = {
        element_id: [r for r in rows if window["start"] <= r["t"] <= window["end"]]
        for element_id, rows in tracks.items()
    }
    windowed = {element_id: rows for element_id, rows in windowed.items() if rows}
    before_ids = {i for i, rows in windowed.items() if any(r["scene"] is not None and r["scene"] < boundary_scene for r in rows)}
    after_ids = {i for i, rows in windowed.items() if any(r["scene"] is not None and r["scene"] >= boundary_scene for r in rows)}
    common = before_ids & after_ids
    if not common:
        return {
            "verdict": False,
            "reason": "no decoder id spans the boundary within the window",
            "beforeIds": sorted(before_ids),
            "afterIds": sorted(after_ids),
            "window": window,
        }
    def _at_expected_rect(row: dict[str, Any]) -> bool:
        if is_move_sample(row, transition_scene):
            return path_progress(row.get("rect"), src_rect, dst_rect, rect_tolerance) is not None
        scene = row.get("scene")
        expected = dst_rect if is_move_complete(row, transition_scene) or (scene is not None and scene >= boundary_scene) else src_rect
        return rect_matches(row.get("rect"), expected, rect_tolerance)

    def _candidate_score(rows: list[dict[str, Any]]) -> tuple[int, int, int]:
        owned = 0
        if runtime_installed:
            for row in rows:
                owner = row.get("footprintOwner")
                if isinstance(owner, dict) and owner.get("elId") is not None and owner.get("elId") == row.get("elId"):
                    owned += 1
        return owned, sum(1 for row in rows if _at_expected_rect(row)), len(rows)

    element_id = max(sorted(common), key=lambda i: _candidate_score(windowed[i]))
    rows = sorted(windowed[element_id], key=lambda r: r["t"])
    before_rows = [r for r in rows if r["scene"] is not None and r["scene"] < boundary_scene]
    after_rows = [r for r in rows if r["scene"] is not None and r["scene"] >= boundary_scene]

    missing_samples = [
        {"t": sample["t"], "scene": sample.get("scene"), "playerState": sample.get("playerState")}
        for sample in samples
        if window["start"] <= sample["t"] <= window["end"]
        and not any(video.get("id") == element_id for video in sample.get("videos") or [])
    ]

    max_drop = 0.0
    for a, b in zip(rows, rows[1:]):
        d_clock = b["currentTime"] - a["currentTime"]
        if d_clock < 0:
            max_drop = max(max_drop, -d_clock)
    stall = _longest_stall_run(rows, max_stall_s)
    advance = rows[-1]["currentTime"] - rows[0]["currentTime"]

    move_rows = [r for r in before_rows if is_move_sample(r, transition_scene)]
    completed_move_rows = [r for r in before_rows if is_move_complete(r, transition_scene)]
    motion = score_motion(move_rows, src_rect, dst_rect, rect_tolerance) if transition_scene is not None else None
    if motion is not None and not any(
        r.get("busy") is False and not is_move_complete(r, transition_scene) for r in before_rows
    ):
        motion["errors"].append("settled source not observed")

    owner_mismatches: list[dict[str, Any]] = []
    if runtime_installed:
        for r in [*move_rows, *completed_move_rows, *after_rows]:
            owner = r.get("footprintOwner")
            owned = isinstance(owner, dict) and owner.get("elId") is not None and owner.get("elId") == r.get("elId")
            if not owned:
                owner_mismatches.append({"t": r["t"], "footprintOwner": owner, "elId": r.get("elId")})

    rect_mismatches: list[dict[str, Any]] = []
    for r in before_rows:
        if not (r.get("isConnected") and _at_expected_rect(r)):
            rect_mismatches.append({"t": r["t"], "phase": "before", "rect": r.get("rect"), "isConnected": r.get("isConnected")})
    for r in after_rows:
        if not (r.get("isConnected") and rect_matches(r.get("rect"), dst_rect, rect_tolerance)):
            rect_mismatches.append({"t": r["t"], "phase": "after", "rect": r.get("rect"), "isConnected": r.get("isConnected")})

    stage_map_invalid: list[dict[str, Any]] = []
    for r in before_rows:
        if r.get("stageMapValid") is False:
            stage_map_invalid.append({"t": r["t"], "phase": "before"})
    for r in after_rows:
        if r.get("stageMapValid") is False:
            stage_map_invalid.append({"t": r["t"], "phase": "after"})

    ok = (
        max_drop <= max_drop_s
        and advance >= min_advance_s
        and not stall["stalled"]
        and not owner_mismatches
        and not rect_mismatches
        and not missing_samples
        and not stage_map_invalid
        and (motion is None or not motion["errors"])
    )
    return {
        "verdict": ok,
        "elementId": element_id,
        "windowAdvanceS": round(advance, 3),
        "maxDropS": round(max_drop, 3),
        "longestStallS": stall["longestStallS"],
        "sampleCount": len(rows),
        "finalRect": rows[-1]["rect"],
        "ownerMismatches": owner_mismatches,
        "rectMismatches": rect_mismatches,
        "missingSamples": missing_samples,
        "stageMapInvalid": stage_map_invalid,
        "motion": motion,
        "window": window,
    }


def score_restart(
    samples: list[dict[str, Any]], asset_substr: str, boundary_scene: float, *, max_start_s: float = RESTART_MAX_START_S
) -> dict[str, Any]:
    """Pure: samples in, verdict dict out. A restart is a genuinely NEW decoder id
    (never seen anywhere with `scene < boundary_scene`, at any time in the run, not
    just within a window) whose own clock starts near zero shortly after the cut."""
    tracks = track_by_id(samples, asset_substr)
    if not decoded_anywhere(tracks):
        return {"verdict": None, "reason": "inconclusive: movie never decoded"}
    before_ids = {i for i, rows in tracks.items() if any(r["scene"] is not None and r["scene"] < boundary_scene for r in rows)}
    after_ids = {i for i, rows in tracks.items() if any(r["scene"] is not None and r["scene"] >= boundary_scene for r in rows)}
    fresh_ids = after_ids - before_ids
    if not fresh_ids:
        return {"verdict": False, "reason": "no distinct decoder id after the boundary", "beforeIds": sorted(before_ids)}

    def first_after_time(i: int) -> float:
        rows = [r for r in tracks[i] if r["scene"] is not None and r["scene"] >= boundary_scene]
        return min((r["t"] for r in rows), default=float("inf"))

    element_id = min(fresh_ids, key=first_after_time)
    rows = sorted((r for r in tracks[element_id] if r["scene"] is not None and r["scene"] >= boundary_scene), key=lambda r: r["t"])
    start_time = rows[0]["currentTime"] if rows else None
    ok = start_time is not None and start_time < max_start_s
    return {"verdict": ok, "elementId": element_id, "startTimeS": start_time, "freshIds": sorted(fresh_ids)}


def score_boundaries(samples: list[dict[str, Any]], facts: dict[str, Any], runtime_installed: bool) -> dict[str, Any]:
    """Pure: samples + ground truth in, the three boundary verdicts out."""
    asset = facts["asset"]
    v12 = score_continuity(samples, asset, facts["onset1to2"], facts["pinRect"], facts["pinRect"], runtime_installed)
    v23 = score_restart(samples, asset, facts["restartScene"])
    v34 = score_continuity(
        samples, asset, facts["bridgeScene"], facts["bridgeSrcRect"], facts["destRect"], runtime_installed,
        transition_scene=facts["bridgeScene"] - 1,
    )
    return {"continue1to2": v12, "restart2to3": v23, "continue3to4": v34}


@contextmanager
def env_override(overrides: dict[str, str | None]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in overrides}
    for key, value in overrides.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_arm(
    name: str, export_root: Path, slides: list[dict[str, Any]], facts: dict[str, Any],
    viewport: tuple[int, int], expected_stage: dict[str, float],
) -> dict[str, Any]:
    force_viewport(*viewport)
    player = LiveOutputHost(export_root, slides, headless=True)
    result: dict[str, Any] = {"arm": name}
    try:
        player.start()
        result["continuity"] = player.output["continuity"]
        raw_samples = drive_and_sample(player)
        samples, invalid_count = convert_samples_to_authored(raw_samples)
        result["samples"] = samples
        result["sampleCount"] = len(samples)
        result["stageMapInvalidCount"] = invalid_count
        result["stageMap"] = stage_map_summary(samples)
        result["stageFit"] = score_stage_fit(samples, expected_stage)
        runtime_installed = result["continuity"].get("mode") == "qualified"
        result.update(score_boundaries(samples, facts, runtime_installed))
    finally:
        try:
            player.stop()
        except Exception as exc:  # noqa: BLE001 - record, never mask an earlier failure
            result["stopError"] = str(exc)
    return result


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def launch_attach_chrome(port: int, profile: Path) -> subprocess.Popen:
    profile.mkdir(parents=True, exist_ok=True)
    args = [
        str(CHROME), "--headless=new", f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1", f"--user-data-dir={profile}",
        f"--window-size={VIEWPORT_WIDTH},{VIEWPORT_HEIGHT + _HEIGHT_PAD}",
        "--force-device-scale-factor=1", "--autoplay-policy=no-user-gesture-required",
        "--no-first-run", "--no-default-browser-check", "--mute-audio",
    ]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_for_cdp(port: int, timeout_s: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=0.5) as response:
                if json.loads(response.read()):
                    return
        except Exception:
            time.sleep(0.1)
    raise SystemExit(f"attach Chrome did not open a CDP target on port {port}")


def force_exact_viewport(port: int, width: int, height: int) -> None:
    """`--window-size` on a bare headless Chrome (no `--app=` window) does not
    yield an exact `innerWidth`/`innerHeight` (window chrome eats a variable
    amount depending on flags/version); pin the renderer's device metrics
    directly instead of guessing another padding constant. The override is
    target-scoped and survives the host's later, separate CDP attach."""
    from websockets.sync.client import connect

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
        targets = json.loads(response.read())
    page = next(item for item in targets if item.get("type") == "page" and item.get("webSocketDebuggerUrl"))
    ws = connect(page["webSocketDebuggerUrl"], open_timeout=5)
    try:
        ws.send(json.dumps({
            "id": 1, "method": "Emulation.setDeviceMetricsOverride",
            "params": {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
        }))
        ws.recv(timeout=5)
    finally:
        ws.close()


def run_attach_arm(
    export_root: Path, slides: list[dict[str, Any]], facts: dict[str, Any], scratch: Path,
    expected_stage: dict[str, float],
) -> dict[str, Any]:
    # The live host forces attach mode to 1920x1080 by contract regardless of
    # `--viewport`; the attach arm stays pinned to that, never the CLI value.
    port = free_port()
    profile = scratch / "attach-chrome-profile"
    if profile.exists():
        shutil.rmtree(profile)
    chrome_proc = launch_attach_chrome(port, profile)
    result: dict[str, Any] = {"arm": "attach", "attachViewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}}
    try:
        wait_for_cdp(port)
        force_exact_viewport(port, VIEWPORT_WIDTH, VIEWPORT_HEIGHT)
        with env_override({ATTACH_ENV: f"http://127.0.0.1:{port}"}):
            player = LiveOutputHost(export_root, slides, headless=True)
            try:
                player.start()
                output = player.output
                result["continuity"] = output["continuity"]
                result["output"] = {key: value for key, value in output.items() if key != "continuity"}
                transport = player._require_transport()
                plan_transparent = transport.evaluate(
                    "!!(window.__OBED_CONTINUITY__ && window.__OBED_CONTINUITY__.transparentBackground)"
                )
                computed_background = transport.evaluate("getComputedStyle(document.documentElement).backgroundColor")
                result["transparentBackground"] = {"plan": bool(plan_transparent), "computedBackground": computed_background}
                raw_samples = drive_and_sample(player)
                samples, invalid_count = convert_samples_to_authored(raw_samples)
                result["samples"] = samples
                result["sampleCount"] = len(samples)
                result["stageMapInvalidCount"] = invalid_count
                result["stageMap"] = stage_map_summary(samples)
                result["stageFit"] = score_stage_fit(samples, expected_stage)
                runtime_installed = result["continuity"].get("mode") == "qualified"
                result.update(score_boundaries(samples, facts, runtime_installed))
            finally:
                try:
                    player.stop()
                except Exception as exc:  # noqa: BLE001
                    result["stopError"] = str(exc)
    finally:
        chrome_proc.terminate()
        try:
            chrome_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            chrome_proc.kill()
            chrome_proc.wait(timeout=5)
        result["chromePid"] = chrome_proc.pid
        result["chromeExitCode"] = chrome_proc.poll()
    return result


def check_no_leftover_chrome() -> str:
    try:
        completed = subprocess.run(["pgrep", "-fl", "obed-live-chrome"], capture_output=True, text=True)
        return completed.stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return f"pgrep failed: {exc}"


def boundary_verdict(entry: dict[str, Any], key: str) -> bool | None:
    value = entry.get(key)
    return value.get("verdict") if isinstance(value, dict) else None


def continuity_mode(entry: dict[str, Any]) -> str | None:
    continuity = entry.get("continuity")
    return continuity.get("mode") if isinstance(continuity, dict) else None


def background_alpha(css: str | None) -> float:
    """Parse a CSS `rgb()`/`rgba()` color's alpha channel. An `rgb()` string has no
    alpha channel at all, which computed-style renders as fully opaque -- treat
    that as alpha 1.0, never as "unknown => pass"."""
    if not css:
        return 1.0
    match = re.match(r"rgba?\(([^)]*)\)", css.strip())
    if not match:
        return 1.0
    parts = [p.strip() for p in match.group(1).split(",")]
    if len(parts) != 4:
        return 1.0
    try:
        return float(parts[3])
    except ValueError:
        return 1.0


def stage_fit_ok(entry: dict[str, Any]) -> bool:
    """Fail-closed: only an explicit truthy `stageFit.verdict` passes. A missing
    `stageFit` (an arm that crashed before scoring it, or a caller that never
    set the key) is not evidence of a correct fit and must not pass."""
    stage_fit = entry.get("stageFit")
    if not isinstance(stage_fit, dict):
        return False
    return bool(stage_fit.get("verdict"))


def stage_fit_reason(entry: dict[str, Any], label: str) -> str | None:
    if stage_fit_ok(entry):
        return None
    if not isinstance(entry.get("stageFit"), dict):
        return f"{label} stageFit missing"
    return f"{label} stageFit failed"


def overall_status(result: dict[str, Any]) -> tuple[str, list[str]]:
    """Pure: the assembled result dict in, (status, reasons) out. Reviewer finding
    #3: a green boundary verdict does not by itself prove the RIGHT mechanism was
    active -- arms A/C must actually have qualified continuity installed, arm B
    must actually have it off, and the attach arm's page must actually be
    transparent, or the verdict is not trustworthy even if the boundary math
    passed."""
    arms = result.get("arms", {})
    attach = result.get("attach", {})
    a, b, c = arms.get("A", {}), arms.get("B", {}), arms.get("C", {})
    all_gated = [
        boundary_verdict(a, "continue1to2"), boundary_verdict(a, "restart2to3"), boundary_verdict(a, "continue3to4"),
        boundary_verdict(b, "continue3to4"),
        boundary_verdict(c, "continue1to2"), boundary_verdict(c, "continue3to4"),
        boundary_verdict(attach, "continue1to2"), boundary_verdict(attach, "restart2to3"), boundary_verdict(attach, "continue3to4"),
    ]
    if any(v is None for v in all_gated):
        return "inconclusive", ["at least one gated boundary verdict is inconclusive (movie never decoded)"]

    reasons: list[str] = []

    a_mode, b_mode, c_mode, attach_mode = continuity_mode(a), continuity_mode(b), continuity_mode(c), continuity_mode(attach)
    a_ok = bool(boundary_verdict(a, "continue1to2")) and bool(boundary_verdict(a, "restart2to3")) and bool(boundary_verdict(a, "continue3to4"))
    if a_mode != "qualified":
        a_ok = False
        reasons.append(f"arm A continuity.mode={a_mode!r}, expected 'qualified'")
    reason = stage_fit_reason(a, "arm A")
    if reason:
        a_ok = False
        reasons.append(reason)

    b_ok = boundary_verdict(b, "continue3to4") is False
    if b_mode != "off":
        b_ok = False
        reasons.append(f"arm B continuity.mode={b_mode!r}, expected 'off'")
    reason = stage_fit_reason(b, "arm B")
    if reason:
        b_ok = False
        reasons.append(reason)

    c_ok = boundary_verdict(c, "continue3to4") is False and boundary_verdict(c, "continue1to2") is True
    if c_mode != "qualified":
        c_ok = False
        reasons.append(f"arm C continuity.mode={c_mode!r}, expected 'qualified'")
    reason = stage_fit_reason(c, "arm C")
    if reason:
        c_ok = False
        reasons.append(reason)

    attach_ok = (
        bool(boundary_verdict(attach, "continue1to2"))
        and bool(boundary_verdict(attach, "restart2to3"))
        and bool(boundary_verdict(attach, "continue3to4"))
    )
    if attach_mode != "qualified":
        attach_ok = False
        reasons.append(f"attach continuity.mode={attach_mode!r}, expected 'qualified'")
    alpha = background_alpha((attach.get("transparentBackground") or {}).get("computedBackground"))
    if alpha != 0:
        attach_ok = False
        reasons.append(f"attach background alpha={alpha}, expected 0")
    reason = stage_fit_reason(attach, "attach")
    if reason:
        attach_ok = False
        reasons.append(reason)

    ok = a_ok and b_ok and c_ok and attach_ok
    if not ok and not reasons:
        reasons.append("a boundary verdict did not match the expected pattern for its arm")
    return ("pass" if ok else "fail"), reasons


def main() -> None:
    args = parse_args()
    if not args.fixture.is_dir():
        raise SystemExit(f"fixture is unavailable: {args.fixture}")
    if not args.original_index.is_file():
        raise SystemExit(f"original index is unavailable: {args.original_index}")
    artifact = args.artifact
    artifact.parent.mkdir(parents=True, exist_ok=True)
    viewport = args.viewport
    result: dict[str, Any] = {
        "kind": "live-continuity-probe",
        "fixture": str(args.fixture),
        "originalIndex": str(args.original_index),
        "status": "running",
        "viewport": {"width": viewport[0], "height": viewport[1]},
        "attachViewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
    }

    def save() -> None:
        artifact.write_text(json.dumps(result, indent=2, default=str) + "\n")

    save()
    try:
        export_a = prepare_export(args.fixture, args.original_index, "arm-a")
        slides_a = load_slides(export_a)
        plan = ground_truth_plan(export_a, slides_a)
        facts = ground_truth_facts(plan)
        result["groundTruth"] = {
            key: facts[key]
            for key in ("asset", "onset1to2", "restartScene", "bridgeScene", "pinRect", "bridgeSrcRect", "destRect", "canvas")
        }
        expected_stage = expected_stage_fit(facts["canvas"], {"width": viewport[0], "height": viewport[1]})
        attach_expected_stage = expected_stage_fit(facts["canvas"], {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT})
        result["expectedStage"] = expected_stage
        result["attachExpectedStage"] = attach_expected_stage
        save()

        result["arms"] = {}
        result["arms"]["A"] = run_arm("A", export_a, slides_a, facts, viewport, expected_stage)
        save()

        export_b = prepare_export(args.fixture, args.original_index, "arm-b")
        with env_override({CONTINUITY_ENV: "off"}):
            result["arms"]["B"] = run_arm("B", export_b, load_slides(export_b), facts, viewport, expected_stage)
        save()

        export_c = prepare_export(args.fixture, args.original_index, "arm-c")
        with bridge_disabled():
            result["arms"]["C"] = run_arm("C", export_c, load_slides(export_c), facts, viewport, expected_stage)
        save()

        result["leftoverChromeAfterArms"] = check_no_leftover_chrome()
        save()

        export_attach = prepare_export(args.fixture, args.original_index, "attach")
        result["attach"] = run_attach_arm(export_attach, load_slides(export_attach), facts, artifact.parent, attach_expected_stage)
        result["leftoverChromeAfterAttach"] = check_no_leftover_chrome()
        save()

        result["status"], result["statusReasons"] = overall_status(result)
    except Exception as exc:  # noqa: BLE001 - always leave a readable artifact behind
        result["status"] = "error"
        result["error"] = str(exc)
    finally:
        save()

    summary = {
        "status": result.get("status"),
        "statusReasons": result.get("statusReasons"),
        "arms": {
            name: {key: boundary_verdict(entry, key) for key in ("continue1to2", "restart2to3", "continue3to4")}
            for name, entry in result.get("arms", {}).items()
        },
        "attach": {key: boundary_verdict(result.get("attach", {}), key) for key in ("continue1to2", "restart2to3", "continue3to4")},
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
