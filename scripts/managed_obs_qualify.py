"""Live qualification of the product managed OBS (plan §9 "Live harness"). Launches OBS on this Mac.

Each take: product `ManagedObs` (scratch home, lossless recording profile) -> websocket StartRecord ->
the `rec` session on the P2 fixture through `LiveOutputHost` attached to the engine's page ->
StopRecord -> clean quit -> `obs_cadence_decode` -> assertions -> `<out>/runs/<arm>-<ts>.json`.

Phases (24 px corner marker): slide1-native 6 s red, advance, slide2-live 8 s green, paused 3 s blue
(every playing <video> paused: the null control), resumed 4 s yellow, advance (build 1), afterBuild
6 s magenta. GL replay is refused under attach, so every phase measures native playback.

Arms: 2x (source = 2 x canvas, the product setting) and positive (source = canvas, the positive
control). Cadence is asserted at rate 25 and report-only at 30; lifecycle and validity always.
Refuses to start while any OBS runs; keeps the Mac awake with caffeinate; a Sleep/Wake in
`pmset -g log` during a take marks it INVALID.

usage: uv run python scripts/managed_obs_qualify.py --arm both --rate 25 --takes 2 --out DIR
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from obed_edom import managed_obs  # noqa: E402
from obed_edom.html_preview import cache_dir  # noqa: E402
from obed_edom.live_host import LiveOutputHost  # noqa: E402
from obed_edom.managed_obs import ManagedObs  # noqa: E402
from obed_edom.obs_websocket import ObsWebsocket  # noqa: E402

import obs_cadence_decode  # noqa: E402
from live_host_probe import wait_for_settlement  # noqa: E402

FIXTURE = REPO / "output/p2-recovery/html-adversarial"
DEFAULT_HOME = Path.home() / "Library/Application Support/Obed-Edom/qualify-home"
USER_OBS_TREE = Path.home() / "Library/Application Support/obs-studio"
WS_CONFIG = "plugin_config/obs-websocket/config.json"
KEYER = "off"
READY_TIMEOUT_S = 40.0
QUIT_TIMEOUT_S = 20.0

NATIVE_PHASES = ("slide1-native", "slide2-live")
NULL_PHASE = "slide2-paused"
LIMITS = {"nativeRepeatMax2x": 0.15, "decodableMin": 0.9, "nullRepeatMin": 0.95, "nativeRepeatMinPositive": 0.18}

MARK_JS = ("(function(c){var m=document.getElementById('obs-mark'); if(!m){m=document.createElement('div'); m.id='obs-mark';"
           " m.style.cssText='position:fixed;left:0;top:0;width:24px;height:24px;z-index:2147483647;pointer-events:none';"
           " document.documentElement.appendChild(m);} m.style.background=c; return performance.now();})('%s')")
VIDEOS_JS = ("Array.prototype.map.call(document.querySelectorAll('video'), function(v){"
             "return {src:String(v.currentSrc).split('/').pop(), paused:v.paused, rs:v.readyState, t:v.currentTime};})")
PAUSE_JS = ("(function(){var vs=Array.prototype.filter.call(document.querySelectorAll('video'), function(v){return !v.paused;});"
            " vs.forEach(function(v){v.pause();}); window.__OBS_QUALIFY_PAUSED__=vs; return vs.length;})()")
RESUME_JS = ("(function(){var vs=window.__OBS_QUALIFY_PAUSED__||[]; vs.forEach(function(v){v.play();});"
             " delete window.__OBS_QUALIFY_PAUSED__; return vs.length;})()")


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def obs_running() -> bool:
    return subprocess.run(["pgrep", "-x", "OBS"], capture_output=True).returncode == 0


def tree_snapshot(root: Path) -> dict[str, list[int]]:
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): [p.stat().st_size, p.stat().st_mtime_ns]
            for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()}


def snapshot_diff(before: dict[str, list[int]], after: dict[str, list[int]], limit: int = 20) -> dict[str, Any]:
    changed = sorted(k for k in before.keys() & after.keys() if before[k] != after[k])
    added, removed = sorted(after.keys() - before.keys()), sorted(before.keys() - after.keys())
    return {"unchanged": not (changed or added or removed), "changed": changed[:limit], "added": added[:limit], "removed": removed[:limit]}


def sleep_events(since: datetime, until: datetime) -> list[str]:
    log = subprocess.run(["pmset", "-g", "log"], capture_output=True, text=True).stdout
    pattern = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) [+-]\d{4} (Sleep|Wake|DarkWake) {2,}")
    events = []
    for line in log.splitlines():
        match = pattern.match(line)
        if match and since <= datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S") <= until:
            events.append(line.strip()[:120])
    return events


@contextlib.contextmanager
def source_fps(rate: int, fps: int) -> Iterator[None]:
    """Harness-only: seed the browser source at `fps` (ManagedObs has no source-fps option)."""
    with mock.patch.dict(managed_obs.RATES, {rate: (managed_obs.RATES[rate][0], fps)}):
        yield


def websocket_credentials(engine: ManagedObs) -> tuple[int, str]:
    """Port and password from the websocket config ManagedObs seeded (it exposes neither)."""
    config = json.loads((engine.tree / WS_CONFIG).read_text())
    return int(config["server_port"]), str(config["server_password"])


def wait_engine(engine: ManagedObs, done: tuple[str, ...], timeout_s: float) -> tuple[dict[str, Any], float]:
    started = time.monotonic()
    while True:
        state = engine.state()
        if state["state"] in done or time.monotonic() - started >= timeout_s:
            return state, round(time.monotonic() - started, 2)
        time.sleep(0.1)


def make_export(tag: str) -> tuple[Path, list[dict[str, Any]]]:
    dest = cache_dir(hashlib.sha256(f"managed-obs-qualify-{tag}-{os.getpid()}".encode()).hexdigest()) / "html"
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURE / "html-player", dest)
    shutil.copy2(FIXTURE / "html-unmodified/index.html", dest / "index.html")
    header = json.loads((dest / "assets/header.json").read_text())
    slides = [{"originalOrdinal": i + 1, "playerIndex": i, "exportedUuid": uuid, "skipped": False}
              for i, uuid in enumerate(header["slideList"])]
    return dest, slides


def rec_session(endpoint: str, target_id: str, rate: int, tag: str) -> dict[str, Any]:
    dest, slides = make_export(tag)
    host = LiveOutputHost(dest, slides, attach_endpoint=endpoint, attach_match=target_id, bridge="obs-managed", output_rate=rate)
    out: dict[str, Any] = {"phases": []}

    def ev(js: str) -> Any:
        return host._require_transport().evaluate(js)

    def phase(name: str, color: str, secs: float) -> None:
        perf = ev(MARK_JS % color)
        out["phases"].append({"name": name, "color": color, "perf": perf, "wall": time.time(),
                              "hash": ev("String(location.hash)"), "videos": ev(VIDEOS_JS)})
        print(f"    phase {name} {color} {out['phases'][-1]['hash']}", flush=True)
        time.sleep(secs)

    try:
        host.observe()
        out["output"] = host.output
        host.execute("show")
        time.sleep(1.2)
        out["viewport"] = ev("[window.innerWidth, window.innerHeight, window.devicePixelRatio]")
        phase("slide1-native", "#ff0000", 6)
        host.execute("advance")
        wait_for_settlement(host, timeout_s=30.0)
        time.sleep(0.8)
        phase("slide2-live", "#00ff00", 8)
        out["pausedVideos"] = ev(PAUSE_JS)
        phase("slide2-paused", "#0000ff", 3)
        out["resumedVideos"] = ev(RESUME_JS)
        phase("slide2-resumed", "#ffff00", 4)
        host.execute("advance")
        wait_for_settlement(host, timeout_s=30.0)
        phase("slide2-afterBuild", "#ff00ff", 6)
    except Exception:
        out["fatal"] = traceback.format_exc()[-3000:]
        print(out["fatal"], flush=True)
    finally:
        try:
            host.stop()
        finally:
            shutil.rmtree(dest.parent, ignore_errors=True)
    return out


def cadence_checks(arm: str, decode: dict[str, Any]) -> list[dict[str, Any]]:
    phases = decode.get("phases") or {}
    checks = []

    def check(name: str, value: Any, ok: bool, limit: str) -> None:
        checks.append({"check": name, "value": value, "limit": limit, "ok": bool(ok)})

    for name in NATIVE_PHASES:
        stats = phases.get(name) or {}
        repeat, decodable = stats.get("repeatFrac"), stats.get("decodableFrac")
        check(f"{name}.decodable", decodable, decodable is not None and decodable >= LIMITS["decodableMin"], f">= {LIMITS['decodableMin']}")
        if arm == "2x":
            check(f"{name}.repeat", repeat, repeat is not None and repeat <= LIMITS["nativeRepeatMax2x"], f"<= {LIMITS['nativeRepeatMax2x']}")
        else:
            check(f"{name}.repeat", repeat, repeat is not None and repeat >= LIMITS["nativeRepeatMinPositive"], f">= {LIMITS['nativeRepeatMinPositive']}")
    null = (phases.get(NULL_PHASE) or {}).get("repeatFrac")
    check(f"{NULL_PHASE}.repeat (null)", null, null is not None and null >= LIMITS["nullRepeatMin"], f">= {LIMITS['nullRepeatMin']}")
    return checks


def native_repeat(run: dict[str, Any]) -> float | None:
    phases = (run.get("decode") or {}).get("phases") or {}
    values = [(phases.get(name) or {}).get("repeatFrac") for name in NATIVE_PHASES]
    return None if any(v is None for v in values) else round(sum(values) / len(values), 4)


def run_take(arm: str, rate: int, take: int, home: Path, out_dir: Path, keep_recording: bool) -> dict[str, Any]:
    ts = stamp()
    canvas_label, product_source = managed_obs.RATES[rate]
    source = product_source if arm == "2x" else rate
    record_dir = home / "recordings" / f"{arm}-{ts}"
    record_dir.mkdir(parents=True, exist_ok=True)
    run: dict[str, Any] = {"arm": arm, "rate": rate, "take": take, "ts": ts, "canvas": canvas_label, "source": source,
                           "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip(),
                           "home": str(home), "recordDir": str(record_dir), "checks": []}
    engine = ManagedObs(home, record_dir=record_dir, quit_timeout_s=QUIT_TIMEOUT_S)
    user_before = tree_snapshot(USER_OBS_TREE)
    sentinel_before = tree_snapshot(engine.tree / ".sentinel")
    started = datetime.now()
    print(f"[{arm} rate {rate} source {source} take {take}] launching", flush=True)
    try:
        with source_fps(rate, source):
            engine.ensure_started(rate, KEYER)
            ready, run["readyS"] = wait_engine(engine, ("ready", "blocked", "stuck", "unavailable"), READY_TIMEOUT_S)
        run["engineReady"] = ready
        if ready["state"] != "ready" or not engine.cdp_endpoint or not engine.target_id:
            raise RuntimeError(f"engine not ready: {ready}")
        port, password = websocket_credentials(engine)
        with ObsWebsocket(port, password) as ws:
            run["obsVersion"] = ws.request("GetVersion").get("obsVersion")
            run["videoSettings"] = ws.request("GetVideoSettings")
            run["sourceSettings"] = ws.request("GetInputSettings", {"inputName": "Program"}).get("inputSettings")
            ws.request("StartRecord")
            deadline = time.monotonic() + 5
            while not ws.request("GetRecordStatus").get("outputActive"):
                if time.monotonic() > deadline:
                    raise RuntimeError("recording did not start")
                time.sleep(0.1)
        time.sleep(2)
        run["session"] = rec_session(engine.cdp_endpoint, engine.target_id, rate, f"{arm}{rate}{take}{ts}")
        time.sleep(1)
        with ObsWebsocket(port, password, timeout=10.0) as ws:
            run["recording"] = ws.request("StopRecord").get("outputPath")
            run["stats"] = ws.request("GetStats")
    except Exception:
        run["fatal"] = traceback.format_exc()[-3000:]
        print(run["fatal"], flush=True)
    finally:
        engine.quit()
        engine.wait_idle(QUIT_TIMEOUT_S + 10)
        run["engineAfterQuit"] = engine.state()
        engine.close()
    ended = datetime.now()
    record = json.loads((home / "ak-engine.json").read_text()) if (home / "ak-engine.json").exists() else {}
    run["lifecycle"] = {"readyS": run.get("readyS"), "stateAfterQuit": run["engineAfterQuit"]["state"],
                        "cleanExit": record.get("cleanExit"), "obsStillRunning": obs_running(),
                        "userObsConfig": snapshot_diff(user_before, tree_snapshot(USER_OBS_TREE)),
                        "sentinel": snapshot_diff(sentinel_before, tree_snapshot(engine.tree / ".sentinel"))}
    run["sleepEvents"] = sleep_events(started, ended)
    run["valid"] = not run["sleepEvents"]
    life = run["lifecycle"]
    seeded = (run.get("sourceSettings") or {}).get("fps")
    run["checks"].append({"check": "browser source fps", "value": seeded, "limit": f"== {source}", "ok": seeded == source, "enforced": True})
    for name, ok in (("session ran", "fatal" not in run and "fatal" not in (run.get("session") or {})),
                     ("clean quit", life["stateAfterQuit"] == "stopped" and not life["obsStillRunning"]),
                     ("ak-engine.json cleanExit", life["cleanExit"] is True),
                     ("user OBS config unchanged", life["userObsConfig"]["unchanged"]),
                     (".sentinel untouched", life["sentinel"]["unchanged"])):
        run["checks"].append({"check": name, "ok": bool(ok), "enforced": True})
    recording = Path(run["recording"]) if run.get("recording") else None
    if recording and recording.exists():
        print(f"  decoding {recording}", flush=True)
        run["decode"] = obs_cadence_decode.decode_recording(recording)
        enforced = rate == 25
        run["checks"] += [{**c, "enforced": enforced} for c in cadence_checks(arm, run["decode"])]
        if not keep_recording:
            shutil.rmtree(record_dir, ignore_errors=True)
    else:
        run["checks"].append({"check": "recording decoded", "ok": False, "enforced": True})
    run["passed"] = run["valid"] and all(c["ok"] for c in run["checks"] if c["enforced"])
    dest = out_dir / "runs" / f"{arm}-{ts}.json"
    dest.write_text(json.dumps(run, indent=1, default=str))
    print_run(run, dest)
    return run


def print_run(run: dict[str, Any], dest: Path) -> None:
    verdict = "INVALID (Mac slept)" if not run["valid"] else ("PASS" if run["passed"] else "FAIL")
    print(f"[{run['arm']} rate {run['rate']} take {run['take']}] {verdict}  ready {run.get('readyS')} s  -> {dest}", flush=True)
    for name, stats in ((run.get("decode") or {}).get("phases") or {}).items():
        if stats:
            print(f"    {name:18s} repeat {stats['repeatFrac']}  raw {stats['rawRepeatFrac']}  decodable {stats['decodableFrac']}"
                  f"  distinct/s {stats['distinctPerS']}  gaps>=3 {stats['gapsGE3']}", flush=True)
    for c in run["checks"]:
        mark = "ok  " if c["ok"] else ("FAIL" if c["enforced"] else "note")
        print(f"    {mark} {c['check']}" + (f" = {c['value']} ({c['limit']})" if "value" in c else ""), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live qualification of the managed OBS (launches OBS; one OBS at a time).")
    parser.add_argument("--arm", choices=("2x", "positive", "both"), default="both")
    parser.add_argument("--rate", type=int, choices=sorted(managed_obs.RATES), default=25)
    parser.add_argument("--takes", type=int, default=2)
    parser.add_argument("--out", type=Path, required=True, help="writes <out>/runs/<arm>-<ts>.json and a summary")
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="scratch ManagedObs home (never under ~/Desktop)")
    parser.add_argument("--keep-recordings", action="store_true", help="keep the lossless recordings (~0.5 GB per take)")
    args = parser.parse_args(argv)
    home = args.home.expanduser().resolve()
    if home.is_relative_to(Path.home() / "Desktop"):
        parser.error("--home must not be under ~/Desktop (TCC blocks OBS there).")
    if home == managed_obs.DEFAULT_HOME.resolve():
        parser.error("--home must not be the product engine home.")
    if obs_running():
        parser.error("An OBS is already running; quit it first (one OBS at a time).")
    if not (FIXTURE / "html-player").is_dir():
        parser.error(f"P2 fixture missing: {FIXTURE}")
    (args.out / "runs").mkdir(parents=True, exist_ok=True)
    arms = ("2x", "positive") if args.arm == "both" else (args.arm,)
    awake = subprocess.Popen(["caffeinate", "-dimsu", "-w", str(os.getpid())])
    runs: list[dict[str, Any]] = []
    try:
        for take in range(1, args.takes + 1):
            for arm in arms:
                if obs_running():
                    print("An OBS is still running after the previous take; stopping.", flush=True)
                    break
                runs.append(run_take(arm, args.rate, take, home, args.out, args.keep_recordings))
    finally:
        awake.terminate()
    summary: dict[str, Any] = {"rate": args.rate, "arms": list(arms), "takes": args.takes, "limits": LIMITS,
                               "runs": [{"arm": r["arm"], "take": r["take"], "ts": r["ts"], "valid": r["valid"],
                                         "passed": r["passed"], "nativeRepeat": native_repeat(r)} for r in runs]}
    checks: list[dict[str, Any]] = []
    if set(arms) == {"2x", "positive"}:
        by_arm = {arm: [native_repeat(r) for r in runs if r["arm"] == arm and r["valid"]] for arm in arms}
        top_2x = max((v for v in by_arm["2x"] if v is not None), default=None)
        low_pos = min((v for v in by_arm["positive"] if v is not None), default=None)
        ok = top_2x is not None and low_pos is not None and low_pos > top_2x
        checks.append({"check": "positive native repeat above every 2x take", "value": [low_pos, top_2x], "ok": ok, "enforced": args.rate == 25})
    summary["checks"] = checks
    summary["passed"] = all(r["passed"] for r in runs) and all(c["ok"] for c in checks if c["enforced"])
    dest = args.out / "runs" / f"summary-{stamp()}.json"
    dest.write_text(json.dumps(summary, indent=1))
    print(f"SUMMARY {'PASS' if summary['passed'] else 'FAIL'} -> {dest}", flush=True)
    for c in checks:
        print(f"    {'ok  ' if c['ok'] else 'FAIL'} {c['check']} = {c['value']}", flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
