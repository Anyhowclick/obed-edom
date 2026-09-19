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
import os
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
  function sceneOf(){
    try { return window.__obedLive ? window.__obedLive.snapshot().sceneId : null; } catch (e) { return null; }
  }
  function ownerOf(rect){
    try {
      return (window.__OBED_P2_PRESERVE__ && window.__OBED_P2_PRESERVE__.footprintOwnerDecoderId)
        ? window.__OBED_P2_PRESERVE__.footprintOwnerDecoderId(rect) : null;
    } catch (e) { return null; }
  }
  function tick(){
    var t = performance.now();
    var scene = sceneOf();
    var videos = [];
    document.querySelectorAll('video').forEach(function(v){
      var r = v.getBoundingClientRect();
      var rect = {x: r.left, y: r.top, w: r.width, h: r.height};
      videos.push({
        id: idFor(v),
        src: String(v.currentSrc || v.src || '').split('/').pop(),
        currentTime: v.currentTime,
        paused: v.paused,
        readyState: v.readyState,
        videoWidth: v.videoWidth,
        isConnected: document.contains(v),
        rect: rect,
        footprintOwner: ownerOf(rect)
      });
    });
    samples.push({t: t, scene: scene, videos: videos});
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--original-index", type=Path, default=ORIGINAL_INDEX)
    parser.add_argument("--artifact", type=Path, default=ARTIFACT)
    return parser.parse_args()


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
    the authored slide-4 destination rect the bridged decoder must land on."""
    bridge = None
    for boundary in plan.boundaries:
        for movie in boundary.movies:
            if movie.action == "bridge":
                bridge = (boundary, movie)
    if bridge is None:
        raise SystemExit("fixture has no bridge boundary (expected the 3->4 moving Magic Move)")
    boundary, movie = bridge
    ordered_players = sorted(plan.scene_index_by_player)
    if len(ordered_players) < 4:
        raise SystemExit("fixture must have at least 4 slides")
    return {
        "asset": movie.asset,
        "onset1to2": plan.scene_index_by_player[ordered_players[1]],
        "restartScene": plan.scene_index_by_player[ordered_players[2]],
        "bridgeScene": plan.scene_index_by_player[ordered_players[3]],
        "destRect": movie.dst_rect.as_dict(),
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
                tracks.setdefault(video["id"], []).append(row)
    return tracks


def decoded_anywhere(tracks: dict[int, list[dict[str, Any]]]) -> bool:
    return any(
        (row.get("readyState") or 0) >= 2 and (row.get("videoWidth") or 0) > 0
        for rows in tracks.values()
        for row in rows
    )


def rect_matches(rect: dict[str, float], expected: dict[str, float], tolerance: float = RECT_TOLERANCE_PX) -> bool:
    return all(abs(rect.get(key, 1e9) - expected[key]) <= tolerance for key in ("x", "y", "w", "h"))


def score_continuity(
    tracks: dict[int, list[dict[str, Any]]],
    boundary_scene: float,
    *,
    min_advance_s: float = MIN_ADVANCE_S,
    max_stall_s: float = MAX_STALL_S,
    max_drop_s: float = MAX_DROP_S,
) -> dict[str, Any]:
    if not decoded_anywhere(tracks):
        return {"verdict": None, "reason": "inconclusive: movie never decoded"}
    before_ids = {i for i, rows in tracks.items() if any(r["scene"] is not None and r["scene"] < boundary_scene for r in rows)}
    after_ids = {i for i, rows in tracks.items() if any(r["scene"] is not None and r["scene"] >= boundary_scene for r in rows)}
    common = before_ids & after_ids
    if not common:
        return {"verdict": False, "reason": "no decoder id spans the boundary", "beforeIds": sorted(before_ids), "afterIds": sorted(after_ids)}
    element_id = max(common, key=lambda i: len(tracks[i]))
    rows = sorted(tracks[element_id], key=lambda r: r["t"])
    max_drop = 0.0
    stalls: list[dict[str, Any]] = []
    for a, b in zip(rows, rows[1:]):
        dt_wall = (b["t"] - a["t"]) / 1000.0
        d_clock = b["currentTime"] - a["currentTime"]
        if d_clock < 0:
            max_drop = max(max_drop, -d_clock)
        elif d_clock <= 1e-3 and not b["paused"] and dt_wall > max_stall_s:
            stalls.append({"atMs": b["t"], "gapS": round(dt_wall, 3)})
    advance = rows[-1]["currentTime"] - rows[0]["currentTime"]
    ok = max_drop <= max_drop_s and advance >= min_advance_s and not stalls
    return {
        "verdict": ok,
        "elementId": element_id,
        "advanceS": round(advance, 3),
        "maxDropS": round(max_drop, 3),
        "stalls": stalls,
        "sampleCount": len(rows),
        "finalRect": rows[-1]["rect"],
    }


def score_restart(
    tracks: dict[int, list[dict[str, Any]]], boundary_scene: float, *, max_start_s: float = RESTART_MAX_START_S
) -> dict[str, Any]:
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


def score_boundaries(samples: list[dict[str, Any]], facts: dict[str, Any]) -> dict[str, Any]:
    tracks = track_by_id(samples, facts["asset"])
    v12 = score_continuity(tracks, facts["onset1to2"])
    v23 = score_restart(tracks, facts["restartScene"])
    v34 = score_continuity(tracks, facts["bridgeScene"])
    if v34.get("verdict") and not rect_matches(v34["finalRect"], facts["destRect"]):
        v34 = {**v34, "verdict": False, "reason": "final rect does not match the derived slide-4 destination", "expectedRect": facts["destRect"]}
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


def run_arm(name: str, export_root: Path, slides: list[dict[str, Any]], facts: dict[str, Any]) -> dict[str, Any]:
    force_viewport(VIEWPORT_WIDTH, VIEWPORT_HEIGHT)
    player = LiveOutputHost(export_root, slides, headless=True)
    result: dict[str, Any] = {"arm": name}
    try:
        player.start()
        result["continuity"] = player.output["continuity"]
        samples = drive_and_sample(player)
        result["sampleCount"] = len(samples)
        result.update(score_boundaries(samples, facts))
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


def run_attach_arm(export_root: Path, slides: list[dict[str, Any]], facts: dict[str, Any], scratch: Path) -> dict[str, Any]:
    port = free_port()
    profile = scratch / "attach-chrome-profile"
    if profile.exists():
        shutil.rmtree(profile)
    chrome_proc = launch_attach_chrome(port, profile)
    result: dict[str, Any] = {"arm": "attach"}
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
                samples = drive_and_sample(player)
                result["sampleCount"] = len(samples)
                result.update(score_boundaries(samples, facts))
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


def overall_status(result: dict[str, Any]) -> str:
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
        return "inconclusive"
    a_ok = bool(boundary_verdict(a, "continue1to2")) and bool(boundary_verdict(a, "restart2to3")) and bool(boundary_verdict(a, "continue3to4"))
    b_ok = boundary_verdict(b, "continue3to4") is False
    c_ok = boundary_verdict(c, "continue3to4") is False and boundary_verdict(c, "continue1to2") is True
    attach_ok = (
        bool(boundary_verdict(attach, "continue1to2"))
        and bool(boundary_verdict(attach, "restart2to3"))
        and bool(boundary_verdict(attach, "continue3to4"))
    )
    return "pass" if (a_ok and b_ok and c_ok and attach_ok) else "fail"


def main() -> None:
    args = parse_args()
    if not args.fixture.is_dir():
        raise SystemExit(f"fixture is unavailable: {args.fixture}")
    if not args.original_index.is_file():
        raise SystemExit(f"original index is unavailable: {args.original_index}")
    artifact = args.artifact
    artifact.parent.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "kind": "live-continuity-probe",
        "fixture": str(args.fixture),
        "originalIndex": str(args.original_index),
        "status": "running",
    }

    def save() -> None:
        artifact.write_text(json.dumps(result, indent=2, default=str) + "\n")

    save()
    try:
        export_a = prepare_export(args.fixture, args.original_index, "arm-a")
        slides_a = load_slides(export_a)
        plan = ground_truth_plan(export_a, slides_a)
        facts = ground_truth_facts(plan)
        result["groundTruth"] = {key: facts[key] for key in ("asset", "onset1to2", "restartScene", "bridgeScene", "destRect")}
        save()

        result["arms"] = {}
        result["arms"]["A"] = run_arm("A", export_a, slides_a, facts)
        save()

        export_b = prepare_export(args.fixture, args.original_index, "arm-b")
        with env_override({CONTINUITY_ENV: "off"}):
            result["arms"]["B"] = run_arm("B", export_b, load_slides(export_b), facts)
        save()

        export_c = prepare_export(args.fixture, args.original_index, "arm-c")
        with bridge_disabled():
            result["arms"]["C"] = run_arm("C", export_c, load_slides(export_c), facts)
        save()

        result["leftoverChromeAfterArms"] = check_no_leftover_chrome()
        save()

        export_attach = prepare_export(args.fixture, args.original_index, "attach")
        result["attach"] = run_attach_arm(export_attach, load_slides(export_attach), facts, artifact.parent)
        result["leftoverChromeAfterAttach"] = check_no_leftover_chrome()
        save()

        result["status"] = overall_status(result)
    except Exception as exc:  # noqa: BLE001 - always leave a readable artifact behind
        result["status"] = "error"
        result["error"] = str(exc)
    finally:
        save()

    summary = {
        "status": result.get("status"),
        "arms": {
            name: {key: boundary_verdict(entry, key) for key in ("continue1to2", "restart2to3", "continue3to4")}
            for name, entry in result.get("arms", {}).items()
        },
        "attach": {key: boundary_verdict(result.get("attach", {}), key) for key in ("continue1to2", "restart2to3", "continue3to4")},
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
