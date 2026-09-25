"""Live qualification of the product managed OBS (managed-OBS plan §9 "Live harness"; GL replay under
managed OBS plan §4 H and §5 gates M0-M6). Launches OBS on this Mac.

Each take: product `ManagedObs` (scratch home, lossless recording profile) -> one or more sessions through
`LiveOutputHost` attached to the engine's page (websocket StartRecord/StopRecord around each recorded session) ->
clean quit -> `obs_cadence_decode` -> gate checks -> `<out>/runs/<arm>-<ts>.json`, plus a JSON verdict per take.
Phases are 24 px corner markers (`obs_cadence_decode.PHASES`); neutral grey is unmeasured.

Arms:
  2x, positive  one `rec` session with gl_replay="off": slide1-native 8 s, slide1-paused 3 s (every playing <video>
                paused: the null control), slide1-resumed 4 s, then a report-only smoke walk (slide 2, build 1).
                Source = 2 x canvas (product) or = canvas (positive control). Cadence gated at both rates on the binary counter, at 25 only on grey.
  g2            sessions g2 (product default: no gl_replay kwarg), g2-off (gl_replay="off"), both recorded, and an
                unrecorded hidden-arm (the g2 session's gl_replay). g2/g2-off: slide 1 as above -> advance -> LIVE (<= 5 s) -> slide2-live 10 s
                (screenshot S) -> hide, slide2-hidden 3 s (screenshot H) -> show, slide2-reshown 4 s ->
                slide2-handback (advance = build 1) 4 s -> slide2-after 3 s (screenshot P3). Gates M0-M4.
  failsafe      one launch: fail-module, fail-zone, fail-bogus (forced-fail seeds), goto2, off, off-2. Gate M5.
  soak          g2 held on slide 2 for --soak-minutes (>= 4) with per-minute reads, 20 s recordings around a loop wrap at
                minute 1 and just before loseContext (after the first half), build 1, P3/P4; an off twin. Gate M6.
                --precheck: the loop pre-check.
--fixture: the soak fixture (default output/p2-loop, `loop_fixture.py`; its fixture.json `loop` key marks it looping, and it
must qualify on product code), or for the other arms the P2 fixture (default) or its binary-counter
copy (`binary_counter_movie.py --build-fixture`, output/p2-binary): its fixture.json selects the decoder's binary counter (its
movie sha256s are checked at startup and recorded per run), and M2 then enforces the hand-back max step per elapsed frame and
an undecodable-free hand-back.
--kb frozen|oldbytes swaps the G2 module text in this process (asserted sha, read back from the host's own report);
--kb latelost forces contextLost while hidden. Refuses to start while any OBS runs or OBED_LIVE_GL_REPLAY is set;
keeps the Mac awake; a Sleep/Wake, a non-lossless recording or a g2 movie past 44 s of media marks a take INVALID.

usage: uv run python scripts/managed_obs_qualify.py --arm g2 --rate 25 --takes 2 --out DIR
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import io
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import types
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator
from unittest import mock

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from obed_edom import live_gl_replay_js, managed_obs, obs_websocket  # noqa: E402
from obed_edom.html_preview import cache_dir  # noqa: E402
from obed_edom.live_continuity import Unsupported  # noqa: E402
from obed_edom.live_host import GL_REPLAY_ENV, LiveOutputHost  # noqa: E402
from obed_edom.managed_obs import ManagedObs  # noqa: E402
from obed_edom.obs_websocket import ObsWebsocket  # noqa: E402

import binary_counter_movie  # noqa: E402
import obs_cadence_decode  # noqa: E402
from live_continuity_probe import (  # noqa: E402
    GL_REPLAY_READ_JS,
    PAINTING_VIDEOS_JS,
    _carried_el_id,
    _movie_entries,
    _notes,
    armed_evidence,
    forced_fail_seed,
    ground_truth_facts,
    ground_truth_plan,
    load_slides,
    matches_asset_keys,
    score_armed,
    wait_for_destination_hash,
)
from live_host_probe import wait_for_settlement  # noqa: E402

FIXTURE = REPO / "output/p2-recovery/html-adversarial"
SOAK_FIXTURE = REPO / "output/p2-loop"
DEFAULT_HOME = Path.home() / "Library/Application Support/Obed-Edom/qualify-home"
USER_OBS_TREE = Path.home() / "Library/Application Support/obs-studio"
WS_CONFIG = "plugin_config/obs-websocket/config.json"
KEYER = "off"
READY_TIMEOUT_S = 40.0
QUIT_TIMEOUT_S = 20.0

NATIVE_PHASES = ("slide1-native",)
NULL_PHASE = "slide1-paused"
UNMEASURED_MARK = "#808080"
LIMITS = {"nativeRepeatMax2x": 0.15, "decodableMin": 0.9, "nullRepeatMin": 0.95, "nativeRepeatMinPositive": 0.18,
          "g2RepeatMax25": 0.03, "g2RepeatMax30": 0.05, "distinctMin25": 24.0, "uploadsMin": 27.0, "reshownRepeatMax": 0.03, "staticMax": 4,
          "counterTol": 2, "movieAlphaMin": 250, "slotAlpha": 75, "slotAlphaTol": 3, "domTol": 3, "liveWaitS": 5.0,
          "mediaEndS": 44.0, "binaryRepeatMax": 0.01, "binaryReshownMax": 0.02, "binaryNativeTol": 0.01, "binaryPositiveMin": 0.05, "binaryDistinctFrac": 0.96, "liveRingMax": 20, "handbackRingPx": 200, "handbackMaxStepPerFrame": 3,
          "build1AfterMarkerMinS": 0.3}
EXPECTED_STATS = {"frameLen": 88, "occludedBands": 20, "bandCount": 128, "innerRect": {"x": 4, "y": 4, "w": 952, "h": 268}}
MOVIE_FPS = 30
SOAK_LOOP_FRAMES = 1381
SOAK_WINDOW_S = 20.0
SOAK_MIN_MINUTES = 4
SOAK_WINDOW_LEAD_S = 10.0
PRECHECK_S = 105.0
RAF_JS = ("(()=>{if(!window.__obedRafN){window.__obedRafN=1;(function t(){window.__obedRafN++;requestAnimationFrame(t);})();}"
          "return [performance.now(), window.__obedRafN];})()")
HANDBACK_LEAD_S = 0.5
MARKER_RECT = {"x": 0, "y": 0, "w": 24, "h": 24}
REGION_PAD = 2
T_ERODE_PX = 6
SLOT_OPACITY = 0.2947

G2_SHA = "10a5b36a1f6008a3213bd90729915f6c15284448406f2a62dbc74ae884fe5288"
KB_SHAS = {"frozen": "413a00ba4e36dd5edf9c07425ab3c92589eb23d51c60914448621b7a456b8b67",
           "oldbytes": "4f8850e05177d12051eadd37f84e091938b46e8fd0e2b7ecf03e7637bed6351e", "latelost": G2_SHA}
KB_ARMS = {"frozen": ("g2", "soak"), "oldbytes": ("g2",), "latelost": ("g2",)}
FROZEN_OLD = "    if (fresh && !state.paused) perLiveUpload();\n"
FROZEN_NEW = "    if (false) perLiveUpload();\n"
OLD_BYTES_REV = "d56fb0dd"
PAGE_LOST_WARNINGS = ("obsPageLost", "obsUnreachable")

MARK_JS = ("(function(c){var m=document.getElementById('obs-mark'); if(!m){m=document.createElement('div'); m.id='obs-mark';"
           " m.style.cssText='position:fixed;left:0;top:0;width:24px;height:24px;z-index:2147483647;pointer-events:none';"
           " document.documentElement.appendChild(m);} m.style.background=c; return performance.now();})('%s')")
VIDEOS_JS = ("Array.prototype.map.call(document.querySelectorAll('video'), function(v){"
             "return {src:String(v.currentSrc).split('/').pop(), paused:v.paused, rs:v.readyState, t:v.currentTime, loop:v.loop};})")
HANDED_BACK_JS = ("(function(id){var v=Array.prototype.find.call(document.querySelectorAll('video'), function(v){return v.__obedElId===id;});"
                  " return v ? {elId:id, loop:v.loop, isConnected:v.isConnected, paused:v.paused, t:v.currentTime} : {elId:id, missing:true};})(%s)")
PAUSE_JS = ("(function(){var vs=Array.prototype.filter.call(document.querySelectorAll('video'), function(v){return !v.paused;});"
            " vs.forEach(function(v){v.pause();}); window.__OBS_QUALIFY_PAUSED__=vs; return vs.length;})()")
RESUME_JS = ("(function(){var vs=window.__OBS_QUALIFY_PAUSED__||[]; vs.forEach(function(v){v.play();});"
             " delete window.__OBS_QUALIFY_PAUSED__; return vs.length;})()")
FORCE_JS = ("(function(r){var A=window.__OBED_GL_REPLAY__; if(!A) return {error:'noApi'};"
            " A.debugForceFail=r; return {perf:performance.now(), state:A.state};})('%s')")
LOSE_CONTEXT_JS = ("(function(){var h=window.__OBED_GL_ORACLE__; if(!h||!h.gl) return {error:'no oracle handle (not LIVE)'};"
                   " var e=h.gl.getExtension('WEBGL_lose_context'); if(!e) return {error:'no WEBGL_lose_context'};"
                   " e.loseContext(); return {ok:true, perf:performance.now(), lost:h.gl.isContextLost()};})()")


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


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


def obs_screenshot(port: int, password: str) -> np.ndarray:
    """H x W x 4 RGBA render of scene `AK` via obs-websocket (an independent scene render, not the DeckLink wire)."""
    with mock.patch.object(obs_websocket, "_MAX_MESSAGE_BYTES", 64 * 1024 * 1024), ObsWebsocket(port, password, timeout=10.0) as ws:
        data = ws.request("GetSourceScreenshot", {"sourceName": "AK", "imageFormat": "png", "imageWidth": 1920,
                                                  "imageHeight": 1080})["imageData"]
    return np.array(Image.open(io.BytesIO(base64.b64decode(data.split(",", 1)[-1]))).convert("RGBA"))


def apply_kb(kind: str) -> dict[str, Any]:
    """Harness-only known-bad: replace `live_gl_replay_js.GL_REPLAY_JS` in this process (never product code)."""
    base = live_gl_replay_js.GL_REPLAY_JS
    if sha256_text(base) != G2_SHA:
        raise SystemExit(f"G2 module sha {sha256_text(base)} is not the qualified {G2_SHA}")
    if kind == "frozen":
        substitutions = base.count(FROZEN_OLD)
        if substitutions != 1:
            raise SystemExit(f"frozen splice: {substitutions} matches of the LIVE perLiveUpload() call, want exactly 1")
        text = base.replace(FROZEN_OLD, FROZEN_NEW)
    elif kind == "oldbytes":
        source = subprocess.run(["git", "show", f"{OLD_BYTES_REV}:src/obed_edom/live_gl_replay_js.py"], cwd=REPO,
                                capture_output=True, text=True, check=True).stdout
        module = types.ModuleType("gl_replay_old_bytes")
        exec(compile(source, f"{OLD_BYTES_REV}:live_gl_replay_js.py", "exec"), module.__dict__)
        text, substitutions = module.GL_REPLAY_JS, 1
    else:
        text, substitutions = base, 0
    if sha256_text(text) != KB_SHAS[kind]:
        raise SystemExit(f"{kind} splice sha {sha256_text(text)} != {KB_SHAS[kind]}")
    live_gl_replay_js.GL_REPLAY_JS = text
    info = {"kind": kind, "substitutions": substitutions, "baseSha": G2_SHA, "sha": live_gl_replay_js.js_sha256()}
    print("KB SPLICE", info, flush=True)
    return info


def make_export(tag: str, fixture: Path) -> tuple[Path, list[dict[str, Any]]]:
    dest = cache_dir(hashlib.sha256(f"managed-obs-qualify-{tag}-{os.getpid()}".encode()).hexdigest()) / "html"
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixture / "html-player", dest)
    shutil.copy2(fixture / "html-unmodified/index.html", dest / "index.html")
    return dest, load_slides(dest)


def fixture_counter(fixture: Path) -> str:
    return binary_counter_movie.read_manifest(fixture).get("counter", "grey")


def p2_family(fixture: Path) -> bool:
    """The P2 fixture or a counter-swapped copy of it that does not loop."""
    manifest = binary_counter_movie.read_manifest(fixture)
    return fixture.resolve() == FIXTURE.resolve() or (manifest.get("base") == binary_counter_movie.FIXTURE_BASE and "loop" not in manifest)


def fixture_loops(fixture: Path) -> bool:
    return "loop" in binary_counter_movie.read_manifest(fixture)


def check_loop_frames(fixture: Path) -> None:
    frames = {m.get("frames") for m in binary_counter_movie.read_manifest(fixture).get("movies") or []}
    if frames and frames != {SOAK_LOOP_FRAMES}:
        raise SystemExit(f"{fixture}: movie frames {sorted(frames, key=str)} are not the soak loop period {SOAK_LOOP_FRAMES}")


def movie_geometry(armed: dict[str, Any] | None) -> tuple[float, float, float]:
    if armed is None:
        return obs_cadence_decode.MOVIE_GEOMETRY
    rect = armed["instanceRect"]
    return (rect["x"], rect["y"], rect["w"] / binary_counter_movie.WIDTH)


def fixture_facts(fixture: Path) -> dict[str, Any]:
    """The flag-on armed boundary (slot table, instance rect, asset keys), derived offline from the fixture."""
    dest, slides = make_export("facts", fixture)
    try:
        for gl in (False, True):
            runtime = ground_truth_plan(dest, slides, gl_replay=gl).to_runtime()
            if isinstance(runtime, Unsupported):
                raise SystemExit(f"fixture does not qualify on product code (gl_replay={gl}): {runtime.reason}")
        return ground_truth_facts(ground_truth_plan(dest, slides, gl_replay=True), armed=True)["armed"]
    finally:
        shutil.rmtree(dest.parent, ignore_errors=True)


def hex_of(phase: str) -> str:
    return "#%02x%02x%02x" % obs_cadence_decode.PHASES[phase]


def rect_tuple(rect: dict[str, float]) -> tuple[float, float, float, float]:
    return (rect["x"], rect["y"], rect["w"], rect["h"])


def movie_media_time(videos: Any, armed: dict[str, Any]) -> float | None:
    times = [v.get("t") for v in videos or [] if isinstance(v, dict) and matches_asset_keys(v.get("src"), armed["assetKeys"])
             and not v.get("paused") and isinstance(v.get("t"), (int, float))]
    return max(times) if times else None


def carried_time(read: Any, armed: dict[str, Any]) -> float | None:
    gl = (read or {}).get("gl") or {}
    carried = _carried_el_id(gl)
    pool = gl.get("pool") if isinstance(gl.get("pool"), list) else []
    times = [e.get("currentTime") for e in _movie_entries(pool, armed) if e.get("elId") == carried]
    return times[0] if len(times) == 1 and isinstance(times[0], (int, float)) else None


class Session:
    """One `LiveOutputHost` session on the engine's page; records phases, page reads and OBS screenshots."""

    def __init__(self, name: str, host: LiveOutputHost, ctx: dict[str, Any]) -> None:
        self.name, self.host, self.creds, self.shots, self.engine_state = name, host, ctx["creds"], ctx["shots"], ctx["engineState"]
        self.out: dict[str, Any] = {"session": name, "phases": [], "reads": {}, "shots": {}}

    def ev(self, js: str) -> Any:
        return self.host._require_transport().evaluate(js)

    def phase(self, name: str, color: str | None = None) -> float:
        perf = self.ev(MARK_JS % (color or hex_of(name)))
        self.out["phases"].append({"name": name, "perf": perf, "wall": time.time(), "hash": self.ev("String(location.hash)"),
                                   "videos": self.ev(VIDEOS_JS), "raf": self.ev(RAF_JS)})
        print(f"    [{self.name}] phase {name} {self.out['phases'][-1]['hash']}", flush=True)
        return time.monotonic()

    def read(self, tag: str) -> dict[str, Any]:
        read = {"wall": time.time(), "gl": self.ev(GL_REPLAY_READ_JS), "painting": self.ev(PAINTING_VIDEOS_JS),
                "videos": self.ev(VIDEOS_JS)}
        self.out["reads"][tag] = read
        return read

    def shot(self, tag: str) -> None:
        path = self.shots / f"{self.name}-{tag}.png"
        Image.fromarray(obs_screenshot(*self.creds)).save(path)
        self.out["shots"][tag] = str(path)

    def execute(self, operation: str, slide: int | None = None) -> None:
        self.host.execute(operation, slide)
        if operation in ("advance", "goTo"):
            wait_for_settlement(self.host, timeout_s=30.0)

    def wait_live(self, timeout_s: float = LIMITS["liveWaitS"]) -> None:
        started = time.monotonic()
        while True:
            api = (self.ev(GL_REPLAY_READ_JS) or {}).get("api") or {}
            if api.get("state") == "LIVE" or time.monotonic() - started >= timeout_s:
                self.out["liveWait"] = {"live": api.get("state") == "LIVE", "s": round(time.monotonic() - started, 2),
                                        "state": api.get("state"), "standDowns": api.get("standDowns")}
                return
            time.sleep(0.1)


def hold(started: float, secs: float) -> None:
    time.sleep(max(0.0, started + secs - time.monotonic()))


def start_log(host: LiveOutputHost) -> dict[str, Any] | None:
    path = (host.output or {}).get("logPath")
    if not path or not Path(path).exists():
        return None
    for line in Path(path).read_text().splitlines():
        record = json.loads(line)
        if record.get("kind") == "start":
            return record
    return None


def run_session(name: str, script: Callable[[Session], None], ctx: dict[str, Any], *, gl_replay: str | None = None,
                seed: str | None = None, record: bool = False) -> dict[str, Any]:
    fixture = ctx["fixture"]
    dest, slides = make_export(f"{ctx['tag']}-{name}", fixture)
    kwargs = {} if gl_replay is None else {"gl_replay": gl_replay}
    session: Session | None = None
    out: dict[str, Any] = {"session": name, "glReplayArg": gl_replay, "seed": seed}
    try:
        with contextlib.ExitStack() as stack:
            if seed is not None:
                out["seedSplice"] = stack.enter_context(forced_fail_seed(seed))
            if record:
                start_record(*ctx["creds"])
                stack.callback(lambda: out.update(recording=stop_record(*ctx["creds"])))
                time.sleep(2)
            host = LiveOutputHost(dest, slides, attach_endpoint=ctx["endpoint"], attach_match=ctx["target"], bridge="obs-managed",
                                  output_rate=ctx["rate"], **kwargs)
            session = Session(name, host, ctx)
            started = time.monotonic()
            try:
                host.observe()
                session.out["output"] = host.output
                script(session)
            except Exception:
                session.out["fatal"] = traceback.format_exc()[-3000:]
                print(session.out["fatal"], flush=True)
            finally:
                session.out["timingS"] = {"script": round(time.monotonic() - started, 2)}
                session.out["outputAtStop"] = host.output
                host.stop()
                session.out["startLog"] = start_log(host)
    except Exception:
        out["fatal"] = traceback.format_exc()[-3000:]
        print(out["fatal"], flush=True)
    finally:
        shutil.rmtree(dest.parent, ignore_errors=True)
    return {**(session.out if session else {}), **out}


def start_record(port: int, password: str) -> None:
    with ObsWebsocket(port, password) as ws:
        ws.request("StartRecord")
        deadline = time.monotonic() + 5
        while not ws.request("GetRecordStatus").get("outputActive"):
            if time.monotonic() > deadline:
                raise RuntimeError("recording did not start")
            time.sleep(0.1)


def stop_record(port: int, password: str) -> str | None:
    time.sleep(1)
    with ObsWebsocket(port, password, timeout=10.0) as ws:
        return ws.request("StopRecord").get("outputPath")


def slide1_phases(s: Session) -> None:
    s.execute("show")
    time.sleep(1.2)
    s.out["viewport"] = s.ev("[window.innerWidth, window.innerHeight, window.devicePixelRatio]")
    hold(s.phase("slide1-native"), 8)
    s.out["pausedVideos"] = s.ev(PAUSE_JS)
    hold(s.phase("slide1-paused"), 3)
    s.out["resumedVideos"] = s.ev(RESUME_JS)
    hold(s.phase("slide1-resumed"), 4)
    s.ev(MARK_JS % UNMEASURED_MARK)


def rec_script(s: Session) -> None:
    slide1_phases(s)
    s.out["smoke"] = smoke_walk(s)


def smoke_walk(s: Session) -> list[dict[str, Any]]:
    """Advance to slide 2 and through build 1; report-only, nothing here is measured."""
    steps = []
    for name in ("advance to slide 2", "advance build 1"):
        try:
            s.host.execute("advance")
            observed, seconds = wait_for_settlement(s.host, timeout_s=30.0)
            steps.append({"step": name, "ok": True, "settleS": round(seconds, 2), "hash": s.ev("String(location.hash)"),
                          "observed": observed})
        except Exception:
            steps.append({"step": name, "ok": False, "error": traceback.format_exc()[-1500:]})
            break
        time.sleep(1.0)
    print("    smoke " + ", ".join(f"{step['step']}: {'ok' if step['ok'] else 'FAIL'}" for step in steps), flush=True)
    return steps


def g2_script(kb: str | None, armed: dict[str, Any]) -> Callable[[Session], None]:
    def script(s: Session) -> None:
        slide1_phases(s)
        s.execute("advance")
        s.wait_live()
        s.out["destinationHash"] = wait_for_destination_hash(s.host, armed["atScene"])
        started = s.phase("slide2-live")
        s.out["armed"] = armed_evidence(s.host._require_transport())
        s.read("liveStart")
        hold(started, 9.5)
        s.read("liveEnd")
        s.shot("S")
        started = s.phase("slide2-hidden")
        s.execute("hide")
        s.read("hiddenStart")
        if kb == "latelost":
            s.out["lateForce"] = s.ev(FORCE_JS % "contextLost")
        hold(started, 1.5)
        s.shot("H")
        hold(started, 3)
        s.read("hiddenEnd")
        s.execute("show")
        s.read("afterShow")
        started = s.phase("slide2-reshown")
        hold(started, 3.8)
        s.read("reshownEnd")
        started = s.phase("slide2-handback")
        hold(started, HANDBACK_LEAD_S)
        s.read("preHandback")
        s.out["build1AfterMarkerS"] = round(time.monotonic() - started, 3)
        s.execute("advance")
        s.out["postHandbackVideos"] = s.ev(VIDEOS_JS)
        hold(started, 4)
        started = s.phase("slide2-after")
        s.read("after")
        hold(started, 3)
        s.shot("P3")
        s.ev(MARK_JS % UNMEASURED_MARK)
    return script


def hidden_arm_script(s: Session) -> None:
    s.execute("show")
    time.sleep(2)
    s.execute("hide")
    s.execute("advance")
    time.sleep(1)
    s.read("hiddenOnSlide2")
    s.execute("show")
    s.wait_live()
    s.read("afterShow")


def failsafe_script(goto: bool) -> Callable[[Session], None]:
    def script(s: Session) -> None:
        s.execute("show")
        time.sleep(1.5)
        if goto:
            s.execute("goTo", 2)
        else:
            s.execute("advance")
        time.sleep(2)
        s.read("slide2")
        s.execute("advance")
        time.sleep(1.5)
        s.read("after")
        s.shot("P3")
    return script


def soak_schedule(minutes: int) -> tuple[int, tuple[int, ...]]:
    """Context loss after the first half, two wrap windows before it and at least one minute after it."""
    if minutes < SOAK_MIN_MINUTES:
        raise ValueError(f"soak of {minutes} min < {SOAK_MIN_MINUTES}: no minute after the context loss")
    lose_at = max(3, minutes // 2 + 1)
    return lose_at, tuple(sorted({1, lose_at - 1}))


def soak_script(minutes: int, armed: dict[str, Any], looping: bool) -> Callable[[Session], None]:
    lose_at, windows = soak_schedule(minutes)

    def minute_read(s: Session, minute: int) -> None:
        read = s.read(f"minute{minute}")
        read["heap"] = s.host._require_transport().call("Runtime.getHeapUsage")
        port, password = s.creds
        with ObsWebsocket(port, password) as ws:
            read["obsStats"] = ws.request("GetStats")
        read["engine"] = s.engine_state()
        api = (read["gl"] or {}).get("api") or {}
        print(f"    [{s.name}] minute {minute} {api.get('state')} standDowns {api.get('standDowns')}"
              f" uploads {(api.get('stats') or {}).get('uploads')}", flush=True)

    def window(s: Session, minute: int) -> None:
        deadline = time.monotonic() + 60
        while looping and time.monotonic() < deadline:
            t = carried_time(s.read(f"window{minute}Wait"), armed)
            if t is not None and 0 <= SOAK_LOOP_FRAMES / MOVIE_FPS - SOAK_WINDOW_LEAD_S - t <= 2:
                break
            time.sleep(0.5)
        start_record(*s.creds)
        time.sleep(1)
        started = s.phase("slide2-live")
        hold(started, SOAK_WINDOW_S)
        s.ev(MARK_JS % UNMEASURED_MARK)
        s.out.setdefault("windows", []).append({"minute": minute, "recording": stop_record(*s.creds)})

    def script(s: Session) -> None:
        s.execute("show")
        time.sleep(1.5)
        s.execute("advance")
        s.wait_live()
        s.ev(MARK_JS % UNMEASURED_MARK)
        t0 = time.monotonic()
        minute_read(s, 0)
        for minute in range(1, minutes + 1):
            hold(t0, 60 * minute)
            minute_read(s, minute)
            if minute in windows:
                window(s, minute)
            if minute == lose_at:
                s.out["loseContext"] = s.ev(LOSE_CONTEXT_JS)
                time.sleep(1)
                s.read("afterLose")
        after_build(s)
    return script


def after_build(s: Session) -> None:
    s.execute("advance")
    time.sleep(1.5)
    s.read("after")
    s.shot("P3")
    time.sleep(1)
    s.shot("P4")


def soak_off_script(s: Session) -> None:
    s.execute("show")
    time.sleep(1.5)
    s.execute("advance")
    time.sleep(5)
    after_build(s)


def precheck_script(armed: dict[str, Any]) -> Callable[[Session], None]:
    def script(s: Session) -> None:
        s.execute("show")
        time.sleep(1.5)
        s.out["slide1Videos"] = s.ev(VIDEOS_JS)
        s.execute("advance")
        s.wait_live()
        started = time.monotonic()
        samples = []
        while time.monotonic() - started < PRECHECK_S:
            read = s.read(f"t{len(samples)}")
            api = (read["gl"] or {}).get("api") or {}
            stats = api.get("stats") or {}
            samples.append({"t": round(time.monotonic() - started, 2), "state": api.get("state"), "standDowns": api.get("standDowns"),
                            "videoEnded": stats.get("videoEnded"), "loopMode": stats.get("loopMode"), "uploads": stats.get("uploads"),
                            "carriedT": carried_time(read, armed)})
            time.sleep(2)
        s.out["samples"] = samples
        carried = _carried_el_id(s.read("preHandback")["gl"])
        s.execute("advance")
        time.sleep(1.5)
        s.out["handedBack"] = s.ev(HANDED_BACK_JS % json.dumps(carried))
    return script


def check(checks: list[dict[str, Any]], name: str, value: Any, ok: bool, limit: str = "", enforced: bool = True) -> None:
    checks.append({"check": name, "value": value, "limit": limit, "ok": bool(ok), "enforced": enforced})


def gate(checks: list[dict[str, Any]], invalid: str | None = None) -> dict[str, Any]:
    failing = [c["check"] for c in checks if c["enforced"] and not c["ok"]]
    verdict = "INVALID" if invalid else ("FAIL" if failing else "PASS")
    return {"verdict": verdict, "invalid": invalid, "failing": failing, "checks": checks}


def cadence_checks(arm: str, decode: dict[str, Any]) -> list[dict[str, Any]]:
    phases = decode.get("phases") or {}
    binary = decode.get("counter") == "binary"
    max_2x = LIMITS["binaryRepeatMax"] if binary else LIMITS["nativeRepeatMax2x"]
    min_positive = LIMITS["binaryPositiveMin"] if binary else LIMITS["nativeRepeatMinPositive"]
    checks: list[dict[str, Any]] = []
    for name in NATIVE_PHASES:
        stats = phases.get(name) or {}
        repeat, decodable = stats.get("repeatFrac"), stats.get("decodableFrac")
        check(checks, f"{name}.decodable", decodable, decodable is not None and decodable >= LIMITS["decodableMin"], f">= {LIMITS['decodableMin']}")
        if arm == "2x":
            check(checks, f"{name}.repeat", repeat, repeat is not None and repeat <= max_2x, f"<= {max_2x}")
        else:
            check(checks, f"{name}.repeat", repeat, repeat is not None and repeat >= min_positive, f">= {min_positive}")
    null = (phases.get(NULL_PHASE) or {}).get("repeatFrac")
    check(checks, f"{NULL_PHASE}.repeat (null)", null, null is not None and null >= LIMITS["nullRepeatMin"], f">= {LIMITS['nullRepeatMin']}")
    return checks


def native_repeat(run: dict[str, Any]) -> float | None:
    phases = (run.get("decode") or {}).get("phases") or {}
    values = [(phases.get(name) or {}).get("repeatFrac") for name in NATIVE_PHASES]
    return None if any(v is None for v in values) else round(sum(values) / len(values), 4)


def api_of(read: Any) -> dict[str, Any]:
    api = ((read or {}).get("gl") or {}).get("api")
    return api if isinstance(api, dict) else {}


def upload_rate(a: Any, b: Any) -> float | None:
    sa, sb = api_of(a).get("stats") or {}, api_of(b).get("stats") or {}
    ta, tb = ((a or {}).get("gl") or {}).get("t"), ((b or {}).get("gl") or {}).get("t")
    if None in (sa.get("uploads"), sb.get("uploads"), ta, tb) or tb <= ta:
        return None
    return round((sb["uploads"] - sa["uploads"]) / ((tb - ta) / 1000.0), 2)


def rect_mask(shape: tuple[int, ...], rect: dict[str, float], pad: int = 0) -> np.ndarray:
    mask = np.zeros(shape[:2], bool)
    x0, y0 = max(0, int(np.floor(rect["x"])) - pad), max(0, int(np.floor(rect["y"])) - pad)
    x1, y1 = min(shape[1], int(np.ceil(rect["x"] + rect["w"])) + pad), min(shape[0], int(np.ceil(rect["y"] + rect["h"])) + pad)
    if x1 > x0 and y1 > y0:
        mask[y0:y1, x0:x1] = True
    return mask


def erode(mask: np.ndarray, px: int) -> np.ndarray:
    out = mask.copy()
    padded = np.pad(mask, px, constant_values=False)
    for dy in range(2 * px + 1):
        for dx in range(2 * px + 1):
            out &= padded[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
    return out


def regions(armed: dict[str, Any], shape: tuple[int, ...]) -> dict[str, np.ndarray]:
    """Output-px gate regions at scale 1: O (outside movie, slot T, marker), movie, T (the override slot minus every
    other slot but the full-stage background, eroded to its plateau), edge (T's erosion band), marker."""
    if len(armed["overrideSlots"]) != 1:
        raise RuntimeError(f"expected one opacity-override slot, got {armed['overrideSlots']}")
    slot_t = armed["overrideSlots"][0]
    slots = armed["slotRects"]
    marker = rect_mask(shape, MARKER_RECT, REGION_PAD)
    movie = armed["instanceRect"]
    t = rect_mask(shape, slots[slot_t]) & ~marker
    for index, rect in enumerate(slots):
        if index != slot_t and not (rect["w"] >= shape[1] and rect["h"] >= shape[0]):
            t &= ~rect_mask(shape, rect)
    plateau = erode(t, T_ERODE_PX)
    outside = ~(marker | rect_mask(shape, movie, REGION_PAD) | rect_mask(shape, slots[slot_t], REGION_PAD))
    return {"O": outside, "movie": rect_mask(shape, movie, -REGION_PAD), "T": plateau, "edge": t & ~plateau, "marker": marker,
            "markerCore": rect_mask(shape, {"x": 4, "y": 4, "w": 16, "h": 16})}


def load_shot(session: dict[str, Any], tag: str) -> np.ndarray | None:
    path = (session.get("shots") or {}).get(tag)
    return np.array(Image.open(path).convert("RGBA")) if path and Path(path).exists() else None


def max_delta(a: np.ndarray | None, b: np.ndarray | None, mask: np.ndarray) -> int | None:
    if a is None or b is None or not mask.any():
        return None
    return int(np.abs(a[mask].astype(np.int16) - b[mask].astype(np.int16)).max())


def alpha_range(img: np.ndarray | None, mask: np.ndarray) -> list[int] | None:
    if img is None or not mask.any():
        return None
    alpha = img[..., 3][mask]
    return [int(alpha.min()), int(alpha.max())]


def scaled_alpha_delta(img: np.ndarray | None, ref: np.ndarray | None, mask: np.ndarray, scale: float) -> int | None:
    if img is None or ref is None or not mask.any():
        return None
    return int(np.abs(img[..., 3][mask].astype(np.int16) - np.round(ref[..., 3][mask] * scale).astype(np.int16)).max())


def continuity_of(session: dict[str, Any]) -> dict[str, Any]:
    return (session.get("outputAtStop") or session.get("output") or {}).get("continuity") or {}


def raf_rates(session: dict[str, Any]) -> dict[str, float | None]:
    marks = [(p["name"], p.get("raf")) for p in session.get("phases") or []]
    rates: dict[str, float | None] = {}
    for (name, a), (_, b) in zip(marks, marks[1:]):
        ok = isinstance(a, list) and isinstance(b, list) and b[0] > a[0]
        rates[name] = round((b[1] - a[1]) * 1000.0 / (b[0] - a[0]), 1) if ok else None
    return rates


def g2_gates(run: dict[str, Any], armed: dict[str, Any]) -> dict[str, Any]:
    sessions = {s["session"]: s for s in run["sessions"]}
    g2, off, hidden_arm = sessions.get("g2") or {}, sessions.get("g2-off") or {}, sessions.get("hidden-arm") or {}
    rate, kb = run["rate"], run.get("kb")
    d_g2, d_off = g2.get("decode") or {}, off.get("decode") or {}
    p_g2, p_off = d_g2.get("phases") or {}, d_off.get("phases") or {}
    live, native = p_g2.get("slide2-live") or {}, p_g2.get("slide1-native") or {}
    reads = g2.get("reads") or {}
    gates: dict[str, Any] = {}

    shots = {(name, tag): load_shot(sess, tag) for name, sess in (("g2", g2), ("off", off)) for tag in ("S", "H", "P3")}
    shape = next((img.shape for img in shots.values() if img is not None), (1080, 1920, 4))
    reg = regions(armed, shape)
    s_g2, h_g2, p3_g2 = shots[("g2", "S")], shots[("g2", "H")], shots[("g2", "P3")]
    s_off, h_off, p3_off = shots[("off", "S")], shots[("off", "H")], shots[("off", "P3")]

    m0: list[dict[str, Any]] = []
    outside_marker = ~reg["marker"]
    h_alpha = alpha_range(h_g2, outside_marker)
    check(m0, "H alpha outside marker", h_alpha, h_alpha is not None and h_alpha[1] == 0, "== 0")
    for tag, img in (("H", h_g2), ("S", s_g2)):
        marker = alpha_range(img, reg["markerCore"])
        check(m0, f"{tag} marker alpha", marker, marker is not None and marker[0] == 255, "== 255")
    hs = max_delta(h_g2[..., 3:] if h_g2 is not None else None, s_g2[..., 3:] if s_g2 is not None else None, np.ones(shape[:2], bool))
    check(m0, "KB: H vs S alpha planes differ", hs, hs is not None and hs > 0, "> 0")
    constant = [tag for tag, img in (("S", s_g2), ("H", h_g2)) if img is not None and int(img[..., 3].min()) == 255]
    poked, unpoked = None, max_delta(s_g2, s_off, reg["O"])
    if unpoked is not None:
        ys, xs = np.nonzero(reg["O"])
        copy = s_g2.copy()
        copy[ys[len(ys) // 2], xs[len(xs) // 2]] ^= np.array([255, 255, 255, 255], np.uint8)
        poked = max_delta(copy, s_off, reg["O"])
    check(m0, "KB: 1-px poked G2-S fails M3 O vs g2-off-S", [poked, unpoked], None not in (poked, unpoked) and poked > unpoked,
          "poked > unpoked O delta")
    gates["M0"] = gate(m0, "constant alpha 255 in " + ",".join(constant) + " -> M3 to hardware day" if constant else None)

    m1: list[dict[str, Any]] = []
    info, expected_sha = continuity_of(g2).get("glReplay") or {}, KB_SHAS.get(kb or "", G2_SHA)
    pref = (g2.get("startLog") or {}).get("glReplayPreference")
    check(m1, "glReplayPreference (product default)", pref, pref == "auto", "== auto")
    check(m1, "glReplay mode/version/sha", info, info.get("mode") == "injected" and info.get("version") == 1 and info.get("sha256") == expected_sha,
          f"injected v1 {expected_sha[:8]}")
    scale = continuity_of(g2).get("scale")
    check(m1, "continuity.scale", scale, scale == 1, "== 1")
    lr, nr = live.get("repeatFrac"), native.get("repeatFrac")
    distinct = live.get("distinctPerS")
    if d_g2.get("counter") == "binary":
        tol, bound, min_distinct = LIMITS["binaryNativeTol"], LIMITS["binaryRepeatMax"], LIMITS["binaryDistinctFrac"] * rate
        check(m1, "slide2-live repeat <= slide1-native repeat + tol", [lr, nr], None not in (lr, nr) and lr <= nr + tol, f"same take, tol {tol}")
        check(m1, "slide2-live repeat", lr, lr is not None and lr <= bound, f"<= {bound}", enforced=rate == 25)
        check(m1, "slide2-live distinct/s", distinct, distinct is not None and distinct >= min_distinct, f">= {min_distinct:.1f}")
    else:
        check(m1, "slide2-live repeat < slide1-native repeat", [lr, nr], lr is not None and nr is not None and lr < nr, "same take")
        bound = LIMITS["g2RepeatMax25"] if rate == 25 else LIMITS["g2RepeatMax30"]
        check(m1, "slide2-live repeat", lr, lr is not None and lr <= bound, f"<= {bound}", enforced=rate == 25)
        check(m1, "slide2-live distinct/s", distinct, distinct is not None and distinct >= LIMITS["distinctMin25"], f">= {LIMITS['distinctMin25']}",
              enforced=rate == 25)
    decodable = live.get("decodableFrac")
    check(m1, "slide2-live decodable", decodable, decodable is not None and decodable >= LIMITS["decodableMin"], f">= {LIMITS['decodableMin']}")
    scored = score_armed(g2.get("armed"), armed, continuity_of(g2))
    for clause in ("mode", "live", "events", "noPainting", "pool"):
        check(m1, f"score_armed.{clause}", scored["checks"][clause], scored["checks"][clause])
    check(m1, "score_armed.owner (report-only)", scored["checks"]["owner"], scored["checks"]["owner"], enforced=False)
    rate_live = upload_rate(reads.get("liveStart"), reads.get("liveEnd"))
    check(m1, "uploads/s over slide2-live", rate_live, rate_live is not None and rate_live >= LIMITS["uploadsMin"], f">= {LIMITS['uploadsMin']}")
    stats = api_of(reads.get("liveEnd")).get("stats") or {}
    check(m1, "glErrors", stats.get("glErrors"), stats.get("glErrors") == 0, "== 0")
    for key, want in EXPECTED_STATS.items():
        check(m1, key, stats.get(key), stats.get(key) == want, f"== {want} (headless r2)")
    null = (p_g2.get(NULL_PHASE) or {}).get("repeatFrac")
    check(m1, "null: slide1-paused repeat", null, null is not None and null >= LIMITS["nullRepeatMin"], f">= {LIMITS['nullRepeatMin']}")
    static_off = (d_off.get("staticMaxDelta") or {}).get("slide2-live")
    static_g2 = (d_g2.get("staticMaxDelta") or {}).get("slide2-live")
    check(m1, "null: g2-off slide2-live movie rect static", static_off, static_off is not None and static_off <= LIMITS["staticMax"],
          f"<= {LIMITS['staticMax']}")
    check(m1, "KB: g2 slide2-live movie rect fails the static check", static_g2, static_g2 is not None and static_g2 > LIMITS["staticMax"],
          f"> {LIMITS['staticMax']}")
    off_scored = score_armed(off.get("armed"), armed, continuity_of(off))
    check(m1, "KB: g2-off score_armed False", off_scored["verdict"], off_scored["verdict"] is False, "False")
    check(m1, "report: page rAF Hz from each phase start", raf_rates(g2), True, enforced=False)
    gates["M1"] = gate(m1)

    m2: list[dict[str, Any]] = []
    offsets = {name: ((d_g2.get("roiOffsets") or {}).get(name) or {}).get("offset") for name in ("slide2-live", "slide2-handback", "slide2-after")}
    check(m2, "report: ROI offset live/handback/after", offsets, True, enforced=False)
    live_ring = (d_g2.get("ringMaxDelta") or {}).get("slide2-live")
    check(m2, "slide2-live ringMaxDelta", live_ring, live_ring is not None and live_ring <= LIMITS["liveRingMax"], f"<= {LIMITS['liveRingMax']}")
    over20 = [(((d.get("ringDiag") or {}).get("slide2-handback") or {}).get("over20") or {}).get("count") for d in (d_g2, d_off)]
    check(m2, "handback ring px over 20", over20[0], over20[0] is not None and over20[0] <= LIMITS["handbackRingPx"], f"<= {LIMITS['handbackRingPx']}")
    handback = p_g2.get("slide2-handback") or {}
    backward, forward, per_frame = handback.get("backwardSteps"), handback.get("maxForwardStep"), handback.get("maxStepPerFrame")
    check(m2, "slide2-handback backwardSteps", backward, backward == 0, "== 0")
    binary = d_g2.get("counter") == "binary"
    check(m2, "slide2-handback maxStepPerFrame", per_frame, per_frame is not None and per_frame <= LIMITS["handbackMaxStepPerFrame"],
          f"<= {LIMITS['handbackMaxStepPerFrame']} per elapsed frame (binary counter; report-only on grey)", enforced=binary)
    frames, decoded = handback.get("frames"), handback.get("decodable")
    check(m2, "slide2-handback every frame decodable", [decoded, frames], bool(frames) and decoded == frames,
          "== frames (binary counter; report-only on grey)", enforced=binary)
    check(m2, "report: handback max-step window, undecodable within 3 frames", [handback.get("maxStepWindow"),
          handback.get("undecodableNearMaxStep")], True, enforced=False)
    lead = g2.get("build1AfterMarkerS")
    check(m2, "build-1 advance after handback marker (s)", lead, lead is not None and lead >= LIMITS["build1AfterMarkerMinS"],
          f">= {LIMITS['build1AfterMarkerMinS']}")
    after = reads.get("after") or {}
    handoffs = _notes(after.get("gl") or {}, "glreplay-handoff", "api")
    check(m2, "glreplay-handoff note", len(handoffs), len(handoffs) >= 1, ">= 1")
    painting = [v for v in after.get("painting") or [] if isinstance(v, dict) and matches_asset_keys(v.get("src"), armed["assetKeys"])]
    check(m2, "one painting movie <video> at P3", len(painting), len(painting) == 1, "== 1")
    check(m2, "report: handback repeat/gaps", [handback.get("repeatFrac"), handback.get("gapsGE3")], True, enforced=False)
    check(m2, "report: counter; max forward step live/handback/native", [d_g2.get("counter"), live.get("maxForwardStep"),
          forward, native.get("maxForwardStep")], True, enforced=False)
    check(m2, "report: handoff completedMs", [h.get("completedMs") for h in handoffs], True, enforced=False)
    check(m2, "report: g2 handback ringDiag", (d_g2.get("ringDiag") or {}).get("slide2-handback"), True, enforced=False)
    check(m2, "report: g2-off handback ringMaxDelta (DOM null)", (d_off.get("ringMaxDelta") or {}).get("slide2-handback"), True, enforced=False)
    check(m2, "report: handback ring px over 20, g2 vs g2-off", over20, True, enforced=False)
    check(m2, "report: g2-off handback ringDiag", (d_off.get("ringDiag") or {}).get("slide2-handback"), True, enforced=False)
    gates["M2"] = gate(m2)

    m3: list[dict[str, Any]] = []
    o = max_delta(s_g2, s_off, reg["O"])
    check(m3, "O: G2-S vs g2-off-S", o, o is not None and o <= 0, "<= tau_O (0; CvC in summary)")
    movie_alpha = alpha_range(s_g2, reg["movie"])
    check(m3, "movie rect min alpha (G2-S)", movie_alpha, movie_alpha is not None and movie_alpha[0] >= LIMITS["movieAlphaMin"], f">= {LIMITS['movieAlphaMin']}")
    want, tol = LIMITS["slotAlpha"], LIMITS["slotAlphaTol"]
    check(m3, "T non-empty", int(reg["T"].sum()), bool(reg["T"].any()), "> 0")
    t_alpha = alpha_range(s_g2, reg["T"])
    check(m3, "T alpha (G2-S)", t_alpha, t_alpha is not None and want - tol <= t_alpha[0] and t_alpha[1] <= want + tol, f"{want} +- {tol}")
    t_dom = max_delta(s_g2, p3_g2, reg["T"])
    check(m3, "T: G2-S vs G2-P3 (DOM)", t_dom, t_dom is not None and t_dom <= LIMITS["domTol"], f"<= {LIMITS['domTol']}")
    t_pre = max_delta(p3_g2, p3_off, reg["T"])
    check(m3, "prerequisite: G2-P3 T == g2-off-P3 T", t_pre, t_pre == 0, "== 0")
    band = reg["edge"]
    check(m3, "edge band non-empty", int(band.sum()), bool(band.any()), "> 0")
    fidelity = scaled_alpha_delta(s_g2, s_off, band, SLOT_OPACITY)
    check(m3, "edge: G2-S alpha == round(g2-off-S alpha x 0.2947)", fidelity, fidelity is not None and fidelity <= tol, f"<= {tol}")
    unscaled = scaled_alpha_delta(s_g2, s_off, band, 1.0)
    check(m3, "KB: edge vs unscaled g2-off-S alpha fails", unscaled, unscaled is not None and unscaled > tol, f"> {tol}")
    edge_dom = max_delta(s_g2, p3_g2, band)
    edge_count = int((band & (np.abs(s_g2.astype(np.int16) - p3_g2.astype(np.int16)).max(axis=2) > LIMITS["domTol"])).sum()) \
        if s_g2 is not None and p3_g2 is not None else None
    check(m3, "report: edge G2-S vs G2-P3 (player vs DOM softness) max, px > 3", [edge_dom, edge_count], True, enforced=False)
    off_alpha = alpha_range(s_off, reg["T"])
    check(m3, "KB: g2-off-S T alpha fails the slot check", off_alpha,
          off_alpha is not None and not (want - tol <= off_alpha[0] and off_alpha[1] <= want + tol), f"not {want} +- {tol}")
    gates["M3"] = gate(m3, gates["M0"]["invalid"])

    m4: list[dict[str, Any]] = []
    check(m4, "H alpha outside marker", h_alpha, h_alpha is not None and h_alpha[1] == 0, "== 0")
    after_show = api_of(reads.get("reshownEnd"))
    check(m4, "LIVE after show", [after_show.get("state"), after_show.get("standDowns")],
          after_show.get("state") == "LIVE" and after_show.get("standDowns") == [], "LIVE, standDowns []")
    hidden_rate = upload_rate(reads.get("hiddenStart"), reads.get("hiddenEnd"))
    check(m4, "uploads/s over hidden window", hidden_rate, hidden_rate is not None and hidden_rate >= LIMITS["uploadsMin"], f">= {LIMITS['uploadsMin']}")
    reshown = (p_g2.get("slide2-reshown") or {}).get("repeatFrac")
    native_repeat_frac = native.get("repeatFrac")
    if d_g2.get("counter") == "binary":
        bound = LIMITS["binaryReshownMax"]
        check(m4, "slide2-reshown repeat <= native + tol", [reshown, native_repeat_frac], None not in (reshown, native_repeat_frac)
              and reshown <= native_repeat_frac + bound, f"<= native + {bound}")
        check(m4, "slide2-reshown repeat", reshown, reshown is not None and reshown <= bound, f"<= {bound}", enforced=rate == 25)
    else:
        check(m4, "slide2-reshown repeat < slide1-native repeat", [reshown, native_repeat_frac],
              None not in (reshown, native_repeat_frac) and reshown < native_repeat_frac, "relative to native (owner 2026-09-24)")
    check(m4, "report: slide2-reshown repeat", reshown, True, f"<= {LIMITS['reshownRepeatMax']}", enforced=False)
    ends = d_g2.get("endpoints") or {}
    last, first = (ends.get("slide2-live") or {}).get("last"), (ends.get("slide2-reshown") or {}).get("first")
    drift = None
    if last and first and d_g2.get("fps"):
        mod = obs_cadence_decode.modulus(d_g2.get("counter", "grey"))
        predicted = last[1] + round((first[0] - last[0]) / d_g2["fps"] * MOVIE_FPS)
        drift = obs_cadence_decode._circular(first[1], predicted if mod is None else predicted % mod, mod)
    check(m4, "first reshown counter vs last live + elapsed*30", drift, drift is not None and drift <= LIMITS["counterTol"], f"<= {LIMITS['counterTol']}")
    arm_wait = hidden_arm.get("liveWait") or {}
    check(m4, "hidden-arm: LIVE within 5 s of show", arm_wait, arm_wait.get("live") is True, "a stand-down is a finding for the owner")
    off_h = alpha_range(h_off, outside_marker)
    off_api = [api_of(r) for r in (off.get("reads") or {}).values()]
    check(m4, "null: g2-off H alpha 0, no G2 state", [off_h, sum(bool(a) for a in off_api)],
          off_h is not None and off_h[1] == 0 and not any(off_api), "0, 0")
    gates["M4"] = gate(m4)
    return gates


KB_EXPECT = {
    "frozen": [("M1", "KB: g2 slide2-live movie rect fails the static check"), ("M1", "uploads/s over slide2-live"),
               ("M4", "uploads/s over hidden window")],
    "oldbytes": [("M2", "slide2-live ringMaxDelta"), ("M2", "handback ring px over 20")],
    "latelost": [("M4", "LIVE after show")],
}


def kb_verdict(kb: str, arm: str, gates: dict[str, Any]) -> dict[str, Any]:
    """A known-bad g2 take passes only when every check it targets FAILs; the frozen soak when any per-minute read does."""
    if arm == "soak":
        results = {c["check"]: {"ok": c["ok"], "value": c["value"]} for c in (gates.get("M6") or {}).get("checks", [])
                   if c["check"].startswith("minute ")}
        looping = gates.get("fixtureLooping") is True
        return {"kb": kb, "targets": results, "fixtureLooping": looping,
                "caught": looping and any(v["ok"] is False and v["value"][2] is not None for v in results.values())}
    results = {}
    for gate_name, name in KB_EXPECT[kb]:
        found = [c for c in (gates.get(gate_name) or {}).get("checks", []) if c["check"] == name]
        results[f"{gate_name}:{name}"] = {"ok": found[0]["ok"], "value": found[0]["value"]} if found else None
    return {"kb": kb, "targets": results,
            "caught": all(v is not None and v["ok"] is False and v["value"] is not None for v in results.values())}


def zone_notes(read: Any) -> list[dict[str, Any]]:
    return _notes(((read or {}).get("gl")) or {}, "glreplay-zone")


def retired_with(read: Any, reason: str, stand_down: str | None = None) -> dict[str, Any] | None:
    for z in zone_notes(read):
        if z.get("to") != "retired":
            continue
        if z.get("reason") == reason and (stand_down is None or z.get("standDown") == stand_down):
            return z
        if stand_down is not None and z.get("reason") == f"{reason}/{stand_down}":
            return z
    return None


def g2_kinds(read: Any) -> list[str]:
    return [e.get("kind") for e in api_of(read).get("events") or [] if isinstance(e, dict)]


def remounts_after_standdown(read: Any) -> list[str]:
    gl = (read or {}).get("gl") or {}
    downs = [e.get("t") for e in api_of(read).get("events") or [] if e.get("kind") in ("glreplay-standdown", "glreplay-handoff")]
    since = min(downs) if downs else None
    return [e.get("kind") for e in gl.get("coreEvents") or [] if str(e.get("kind")).startswith("remount-")
            and (since is None or (e.get("t") or 0) > since)]


def movie_painting(read: Any, armed: dict[str, Any]) -> int:
    return sum(1 for v in (read or {}).get("painting") or [] if isinstance(v, dict) and matches_asset_keys(v.get("src"), armed["assetKeys"]))


def outside_parity(a: dict[str, Any], b: dict[str, Any], armed: dict[str, Any], tags: tuple[str, ...] = ("P3",)) -> int | None:
    values = []
    for tag in tags:
        ia, ib = load_shot(a, tag), load_shot(b, tag)
        if ia is None or ib is None:
            return None
        mask = ~(rect_mask(ia.shape, MARKER_RECT, REGION_PAD) | np.logical_or.reduce(
            [rect_mask(ia.shape, r, REGION_PAD) for r in armed["rects"]]))
        values.append(max_delta(ia, ib, mask))
    return None if None in values else max(values)


def failsafe_gates(run: dict[str, Any], armed: dict[str, Any]) -> dict[str, Any]:
    sessions = {s["session"]: s for s in run["sessions"]}
    off, off2 = sessions.get("off") or {}, sessions.get("off-2") or {}
    tau_off = outside_parity(off, off2, armed)
    per: dict[str, Any] = {}

    def score(name: str, want: Callable[[Any], dict[str, Any] | None]) -> dict[str, Any]:
        sess = sessions.get(name) or {}
        after = (sess.get("reads") or {}).get("after")
        checks: list[dict[str, Any]] = []
        zone = want(after)
        check(checks, "zone retired with expected reason", zone_notes(after), zone is not None)
        kinds = g2_kinds(after) + [e.get("kind") for e in ((after or {}).get("gl") or {}).get("coreEvents") or []]
        check(checks, "0 glreplay-live", kinds.count("glreplay-live"), "glreplay-live" not in kinds, "== 0")
        counts = [movie_painting(after, armed), movie_painting((off.get("reads") or {}).get("after"), armed)]
        check(checks, "painting movie count == off", counts, counts[0] == counts[1])
        parity = outside_parity(sess, off, armed)
        check(checks, "P3 == off P3 outside movie rects", [parity, tau_off], None not in (parity, tau_off) and parity <= tau_off, "<= tau_off")
        remounts = remounts_after_standdown(after)
        check(checks, "0 remount-* after the stand-down", remounts, not remounts, "[]")
        return gate(checks)

    def zone_expect(reason: str) -> Callable[[Any], dict[str, Any] | None]:
        return lambda read: retired_with(read, "failure", reason)

    def goto_expect(read: Any) -> dict[str, Any] | None:
        retired = [z for z in zone_notes(read) if z.get("to") == "retired"]
        return retired[0] if retired and retired[0].get("reason") in ("cleared", "unengaged") else None

    per["fail-module"] = score("fail-module", lambda read: retired_with(read, "moduleRetired"))
    per["fail-zone"] = score("fail-zone", zone_expect("posterAmbiguous"))
    per["goto2"] = score("goto2", goto_expect)
    bogus = score("fail-bogus", zone_expect("posterAmbiguous"))
    checks = [c for name in ("fail-module", "fail-zone", "goto2") for c in
              [{**c, "check": f"{name}: {c['check']}"} for c in per[name]["checks"]]]
    check(checks, "tau_off: off vs off-2 P3", tau_off, tau_off == 0, "== 0 (expected)", enforced=False)
    bogus_zone = next((c for c in bogus["checks"] if c["check"] == "zone retired with expected reason"), None)
    check(checks, "KB: fail-bogus does not read as retired-with-expected-reason", bogus["failing"],
          bogus_zone is not None and bogus_zone["ok"] is False, "zone check FAIL")
    return {"M5": gate(checks), "perSession": {**per, "fail-bogus": bogus}, "tauOff": tau_off}


def soak_gates(run: dict[str, Any], armed: dict[str, Any], looping: bool) -> dict[str, Any]:
    sessions = {s["session"]: s for s in run["sessions"]}
    soak, off = sessions.get("soak") or {}, sessions.get("soak-off") or {}
    reads = soak.get("reads") or {}
    minutes = sorted(int(k[6:]) for k in reads if re.fullmatch(r"minute\d+", k))
    lose_at, expected_windows = soak_schedule(run["soakMinutes"])
    checks: list[dict[str, Any]] = []
    engines = [(reads[f"minute{m}"].get("engine") or {}) for m in minutes]
    bad = [e for e in engines if e.get("state") != "ready" or any(w.get("id") in PAGE_LOST_WARNINGS for w in e.get("warnings") or [])]
    check(checks, "engine ready, no pageLost/obsUnreachable", len(bad), not bad and bool(engines), "== 0")
    report = []
    for a, b in zip(minutes, minutes[1:]):
        ra, rb = reads[f"minute{a}"], reads[f"minute{b}"]
        api, rate = api_of(rb), upload_rate(ra, rb)
        report.append({"minute": b, "state": api.get("state"), "standDowns": api.get("standDowns"), "uploadsPerS": rate,
                       "glErrors": (api.get("stats") or {}).get("glErrors"), "heap": rb.get("heap"),
                       "renderSkipped": (rb.get("obsStats") or {}).get("renderSkippedFrames"),
                       "outputSkipped": (rb.get("obsStats") or {}).get("outputSkippedFrames"),
                       "obsMemoryMB": (rb.get("obsStats") or {}).get("memoryUsage")})
        if b <= lose_at:
            check(checks, f"minute {b}: LIVE, standDowns [], uploads/s", [api.get("state"), api.get("standDowns"), rate],
                  api.get("state") == "LIVE" and api.get("standDowns") == [] and rate is not None and rate >= LIMITS["uploadsMin"],
                  f"LIVE, [], >= {LIMITS['uploadsMin']}", enforced=looping)
    recorded = [w["minute"] for w in soak.get("windows") or []]
    check(checks, "wrap windows recorded", recorded, recorded == list(expected_windows), f"== {list(expected_windows)}", enforced=looping)
    for window in soak.get("windows") or []:
        stats = (((window.get("decode") or {}).get("phases") or {}).get("slide2-live")) or {}
        check(checks, f"window minute {window['minute']}: only wrap-signature backward steps",
              [stats.get("backwardSteps"), stats.get("wrapSteps")], stats.get("backwardSteps") == 0 and (stats.get("wrapSteps") or 0) >= 1,
              "backward 0, wraps >= 1", enforced=looping)
    lost = soak.get("loseContext") or {}
    after_lose = reads.get("afterLose")
    downs = api_of(after_lose).get("standDowns")
    events = [e for e in api_of(after_lose).get("events") or [] if e.get("kind") == "glreplay-standdown"]
    check(checks, "loseContext applied", lost, lost.get("ok") is True)
    check(checks, "contextLost stand-down, write-back skipped", [downs, [(e.get("detail") or {}).get("posterRestored") for e in events]],
          downs == ["contextLost"] and bool(events) and all((e.get("detail") or {}).get("posterRestored") is None for e in events))
    check(checks, "zone retired failure/contextLost", zone_notes(after_lose), retired_with(after_lose, "failure", "contextLost") is not None)
    parity = outside_parity(soak, off, armed, ("P3", "P4"))
    check(checks, "P3/P4 == off twin outside movie rects", parity, parity == 0, "<= tau_off (0)")
    return {"M6": gate(checks), "perMinute": report, "fixtureLooping": looping}


def precheck_gates(run: dict[str, Any], fixture: Path) -> dict[str, Any]:
    session = next(iter(run["sessions"]), {})
    samples = session.get("samples") or []
    checks: list[dict[str, Any]] = []
    static = loop_representation(fixture)
    check(checks, "(a) loop representation", static, static["ok"], "differing JSON == loop-splice.json; added loop keys all loopMode=\"looping\"")
    slide1 = [v for v in session.get("slide1Videos") or [] if isinstance(v, dict) and "untitled.mov" in str(v.get("src")).lower()]
    check(checks, "(a) video.loop on every slide-1 untitled.mov", [v.get("loop") for v in slide1],
          bool(slide1) and all(v.get("loop") is True for v in slide1), "all true")
    handed = session.get("handedBack")
    check(checks, "(a) video.loop on the handed-back carried element", handed,
          isinstance(handed, dict) and handed.get("elId") is not None and handed.get("loop") is True, "true")
    continuity = continuity_of(session)
    check(checks, "(b) continuity qualified, glReplay injected", [continuity.get("mode"), (continuity.get("glReplay") or {}).get("mode")],
          continuity.get("mode") == "qualified" and (continuity.get("glReplay") or {}).get("mode") == "injected")
    times = [s["carriedT"] for s in samples if s.get("carriedT") is not None]
    wraps = sum(1 for a, b in zip(times, times[1:]) if b < a - 20)
    uploads = [s.get("uploads") for s in samples]
    check(checks, "(c) >= 2 wraps", wraps, wraps >= 2, ">= 2")
    check(checks, "(c) LIVE, no stand-down, videoEnded false throughout",
          sorted({(s.get("state"), json.dumps(s.get("standDowns")), s.get("videoEnded")) for s in samples}),
          bool(samples) and all(s.get("state") == "LIVE" and s.get("standDowns") == [] and s.get("videoEnded") is False for s in samples))
    check(checks, "(c) uploads keep rising", uploads, all(isinstance(a, (int, float)) and isinstance(b, (int, float)) and b > a
                                                          for a, b in zip(uploads, uploads[1:])) and len(uploads) > 1)
    return {"precheck": gate(checks)}


def loop_keys(tree: Path) -> set[str]:
    keys = set()
    for path in sorted(tree.rglob("*.json*")):
        if path.suffix not in (".json", ".jsonp"):
            continue
        for key, value in re.findall(r'"(\w*[Ll]oop\w*)"\s*:\s*([^,}\]]+)', path.read_text(errors="ignore")):
            keys.add(f"{path.relative_to(tree)}:{key}={value.strip()}")
    return keys


def loop_representation(fixture: Path) -> dict[str, Any]:
    """The fixture's `html-unmodified` against the P2 base: only the spliced files differ, and every loop key they add is `loopMode="looping"`."""
    ours, p2 = fixture / "html-unmodified", FIXTURE / "html-unmodified"
    differing = []
    for path in sorted(ours.rglob("*.json*")):
        if path.suffix not in (".json", ".jsonp"):
            continue
        other = p2 / path.relative_to(ours)
        if not other.exists() or other.read_bytes() != path.read_bytes():
            differing.append(str(path.relative_to(ours)))
    record = fixture / "loop-splice.json"
    spliced = sorted(str(Path(f["path"]).relative_to("html-unmodified")) for f in json.loads(record.read_text())["files"]
                     if Path(f["path"]).parts[0] == "html-unmodified") if record.is_file() else None
    added = sorted(loop_keys(ours) - loop_keys(p2))
    ok = spliced is not None and differing == spliced and bool(added) and all(k.split(":", 1)[1] == 'loopMode="looping"' for k in added)
    main_js = next(iter(ours.rglob("main.js")), None)
    return {"ok": ok, "differing": differing, "spliced": spliced, "addedLoopKeys": added,
            "mainJsLoopMentions": main_js.read_text(errors="ignore").count("loop") if main_js else None}


def launch_engine(engine: ManagedObs, rate: int, source: int, launch: str, run: dict[str, Any]) -> tuple[int, str]:
    with source_fps(rate, source):
        engine.ensure_started(rate, KEYER)
        ready, run["readyS"] = wait_engine(engine, ("ready", "blocked", "stuck", "unavailable"), READY_TIMEOUT_S)
    run["engineReady"] = ready
    if ready["state"] != "ready" or not engine.cdp_endpoint or not engine.target_id:
        raise RuntimeError(f"engine not ready: {ready}")
    if launch == "shown":
        engine.show()
        time.sleep(2)
        run["shownState"] = engine.state()["state"]
    port, password = websocket_credentials(engine)
    if launch == "projector":
        with ObsWebsocket(port, password) as ws:
            ws.request("OpenVideoMixProjector", {"videoMixType": "OBS_WEBSOCKET_VIDEO_MIX_TYPE_PROGRAM"})
        time.sleep(1)
    with ObsWebsocket(port, password) as ws:
        run["obsVersion"] = ws.request("GetVersion").get("obsVersion")
        run["videoSettings"] = ws.request("GetVideoSettings")
        run["sourceSettings"] = ws.request("GetInputSettings", {"inputName": "Program"}).get("inputSettings")
    return port, password


def sessions_for(arm: str, ctx: dict[str, Any], args: argparse.Namespace, armed: dict[str, Any] | None) -> list[dict[str, Any]]:
    if arm in ("2x", "positive"):
        return [run_session("rec", rec_script, ctx, gl_replay="off", record=True)]
    if arm == "g2":
        return [run_session("g2", g2_script(args.kb, armed), ctx, record=True),
                run_session("g2-off", g2_script(None, armed), ctx, gl_replay="off", record=True),
                run_session("hidden-arm", hidden_arm_script, ctx)]
    if arm == "failsafe":
        return [run_session("fail-module", failsafe_script(False), ctx, seed="planUnreadable"),
                run_session("fail-zone", failsafe_script(False), ctx, seed="posterAmbiguous"),
                run_session("fail-bogus", failsafe_script(False), ctx, seed="bogusReason"),
                run_session("goto2", failsafe_script(True), ctx),
                run_session("off", failsafe_script(False), ctx, gl_replay="off"),
                run_session("off-2", failsafe_script(False), ctx, gl_replay="off")]
    if args.precheck:
        return [run_session("precheck", precheck_script(armed), ctx)]
    return [run_session("soak", soak_script(args.soak_minutes, armed, fixture_loops(ctx["fixture"])), ctx),
            run_session("soak-off", soak_off_script, ctx, gl_replay="off")]


def ring_exclusions(armed: dict[str, Any]) -> list[tuple[float, float, float, float]]:
    """Every slot but the movie's own and the full-stage background: their edges sharpen GL -> DOM at build 1."""
    return [rect_tuple(r) for i, r in enumerate(armed["slotRects"])
            if i != armed["movieSlot"] and not (r["w"] >= 1920 and r["h"] >= 1080)]


def decode_session(session: dict[str, Any], recording: str | None, *, rings: list[Any] | None, loop_frames: int | None,
                   keep: bool, crops_dir: Path | None = None, ring_exclude: list[Any] = (), counter: str = "grey",
                   geometry: tuple[float, float, float] = obs_cadence_decode.MOVIE_GEOMETRY) -> dict[str, Any] | None:
    path = Path(recording) if recording else None
    if path is None or not path.exists():
        return None
    print(f"  decoding {session['session']} {path}", flush=True)
    try:
        return obs_cadence_decode.decode_recording(path, rings=rings, statics=rings, ring_exclude=ring_exclude, loop_frames=loop_frames,
                                                   crops_dir=crops_dir if keep and rings else None, counter=counter, geometry=geometry)
    except obs_cadence_decode.NotLossless as exc:
        return {"notLossless": str(exc)}
    finally:
        if not keep:
            path.unlink(missing_ok=True)


def run_take(arm: str, rate: int, take: int, home: Path, out_dir: Path, args: argparse.Namespace,
             armed: dict[str, Any] | None) -> dict[str, Any]:
    ts = stamp()
    canvas_label, product_source = managed_obs.RATES[rate]
    source = rate if arm == "positive" else product_source
    record_dir = home / "recordings" / f"{arm}-{ts}"
    record_dir.mkdir(parents=True, exist_ok=True)
    shots = out_dir / "shots" / f"{arm}-{ts}"
    shots.mkdir(parents=True, exist_ok=True)
    run: dict[str, Any] = {"arm": arm, "rate": rate, "take": take, "ts": ts, "canvas": canvas_label, "source": source,
                           "launch": args.launch, "kb": args.kb, "kbSplice": args.kb_splice, "fixture": str(args.fixture),
                           "counter": fixture_counter(args.fixture), "fixtureIdentity": args.fixture_identity,
                           "soakMinutes": args.soak_minutes, "precheck": args.precheck,
                           "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip(),
                           "home": str(home), "recordDir": str(record_dir), "checks": [], "sessions": []}
    engine = ManagedObs(home, record_dir=record_dir, quit_timeout_s=QUIT_TIMEOUT_S)
    user_before = tree_snapshot(USER_OBS_TREE)
    sentinel_before = tree_snapshot(engine.tree / ".sentinel")
    started = datetime.now()
    take_started = time.monotonic()
    timing = run["timingS"] = {}
    print(f"[{arm} rate {rate} source {source} {args.launch} take {take}] launching", flush=True)
    try:
        t = time.monotonic()
        creds = launch_engine(engine, rate, source, args.launch, run)
        timing["launch"] = round(time.monotonic() - t, 2)
        ctx = {"endpoint": engine.cdp_endpoint, "target": engine.target_id, "rate": rate, "creds": creds, "shots": shots,
               "fixture": args.fixture, "tag": f"{arm}{rate}{take}{ts}",
               "engineState": lambda: {k: engine.state().get(k) for k in ("state", "warnings")}}
        run["sessions"] = sessions_for(arm, ctx, args, armed)
    except Exception:
        run["fatal"] = traceback.format_exc()[-3000:]
        print(run["fatal"], flush=True)
    finally:
        t = time.monotonic()
        engine.quit()
        engine.wait_idle(QUIT_TIMEOUT_S + 10)
        timing["quit"] = round(time.monotonic() - t, 2)
        run["engineAfterQuit"] = engine.state()
        engine.close()
    ended = datetime.now()
    record = json.loads((home / "ak-engine.json").read_text()) if (home / "ak-engine.json").exists() else {}
    run["lifecycle"] = {"readyS": run.get("readyS"), "stateAfterQuit": run["engineAfterQuit"]["state"],
                        "cleanExit": record.get("cleanExit"), "obsStillRunning": obs_running(),
                        "userObsConfig": snapshot_diff(user_before, tree_snapshot(USER_OBS_TREE)),
                        "sentinel": snapshot_diff(sentinel_before, tree_snapshot(engine.tree / ".sentinel"))}
    run["sleepEvents"] = sleep_events(started, ended)
    invalid = ["Mac slept"] if run["sleepEvents"] else []
    life = run["lifecycle"]
    seeded = (run.get("sourceSettings") or {}).get("fps")
    run["checks"].append({"check": "browser source fps", "value": seeded, "limit": f"== {source}", "ok": seeded == source, "enforced": True})
    for name, ok in (("sessions ran", "fatal" not in run and all("fatal" not in s for s in run["sessions"])),
                     ("clean quit", life["stateAfterQuit"] == "stopped" and not life["obsStillRunning"]),
                     ("ak-engine.json cleanExit", life["cleanExit"] is True),
                     ("user OBS config unchanged", life["userObsConfig"]["unchanged"]),
                     (".sentinel untouched", life["sentinel"]["unchanged"])):
        run["checks"].append({"check": name, "ok": bool(ok), "enforced": True})

    loop_frames = SOAK_LOOP_FRAMES if fixture_loops(args.fixture) else None
    rings = [rect_tuple(armed["instanceRect"])] if arm == "g2" else None
    ring_exclude = ring_exclusions(armed) if arm == "g2" else []
    counter, geometry = run["counter"], movie_geometry(armed)
    for session in run["sessions"]:
        t = time.monotonic()
        if session.get("recording"):
            session["decode"] = decode_session(session, session["recording"], rings=rings, loop_frames=None, keep=args.keep_recordings,
                                               crops_dir=shots / f"{session['session']}-crops", ring_exclude=ring_exclude,
                                               counter=counter, geometry=geometry)
        for window in session.get("windows") or []:
            w = time.monotonic()
            window["decode"] = decode_session(session, window["recording"], rings=None, loop_frames=loop_frames,
                                              keep=args.keep_recordings, counter=counter, geometry=geometry)
            window["decodeS"] = round(time.monotonic() - w, 2)
        session.setdefault("timingS", {})["decode"] = round(time.monotonic() - t, 2)
    decodes = [s.get("decode") for s in run["sessions"] if s.get("recording")] + [
        w.get("decode") for s in run["sessions"] for w in s.get("windows") or []]
    if any(d is None for d in decodes):
        run["checks"].append({"check": "recordings decoded", "ok": False, "enforced": True})
    lossy = [d["notLossless"] for d in decodes if d and "notLossless" in d]
    if lossy:
        invalid.append(f"not lossless: {lossy[0]}")
    run["codecs"] = sorted({f"{d.get('codec')}/{d.get('pixFmt')}" for d in decodes if d and "codec" in d})
    if not args.keep_recordings:
        shutil.rmtree(record_dir, ignore_errors=True)

    try:
        run["gates"] = arm_gates(arm, run, args, armed, invalid)
    except Exception:
        run["gates"] = {"error": gate([{"check": "gate computation", "value": traceback.format_exc()[-2000:], "limit": "",
                                        "ok": False, "enforced": True}])}
    run["invalid"] = invalid
    run["valid"] = not invalid
    gate_ok = all(g.get("verdict") in ("PASS", "INVALID") for g in run["gates"].values() if isinstance(g, dict) and "verdict" in g)
    run["kbResult"] = kb_verdict(args.kb, arm, run["gates"]) if args.kb and not args.precheck else None
    lifecycle_ok = all(c["ok"] for c in run["checks"] if c["enforced"])
    run["passed"] = run["valid"] and lifecycle_ok and (run["kbResult"]["caught"] if run["kbResult"] else gate_ok)
    timing["total"] = round(time.monotonic() - take_started, 2)
    dest = out_dir / "runs" / f"{arm}-{ts}.json"
    dest.write_text(json.dumps(run, indent=1, default=str))
    print_run(run, dest)
    return run


def arm_gates(arm: str, run: dict[str, Any], args: argparse.Namespace, armed: dict[str, Any] | None,
              invalid: list[str]) -> dict[str, Any]:
    if arm in ("2x", "positive"):
        run["session"] = run["sessions"][0] if run["sessions"] else {}
        run["decode"] = run["session"].get("decode")
        smoke = run["session"].get("smoke") or []
        run["checks"].append({"check": "slide 2 smoke walk", "value": [s["step"] for s in smoke if s["ok"]],
                              "limit": "2 steps ok", "ok": len(smoke) == 2 and all(s["ok"] for s in smoke), "enforced": False})
        if run["decode"] and "phases" in run["decode"]:
            binary = run["decode"].get("counter") == "binary"
            run["checks"] += [{**c, "enforced": c["enforced"] and (binary or run["rate"] == 25)} for c in cadence_checks(arm, run["decode"])]
        return {}
    if arm == "g2":
        g2 = next((s for s in run["sessions"] if s["session"] == "g2"), {})
        after = next((p for p in g2.get("phases") or [] if p["name"] == "slide2-after"), None)
        media = movie_media_time(after.get("videos"), armed) if after else None
        run["mediaTimeAtAfter"] = media
        if media is None or media + 3 > LIMITS["mediaEndS"]:
            invalid.append(f"media time at slide2-after {media} (+3 s) past {LIMITS['mediaEndS']} s or unreadable")
        return g2_gates(run, armed)
    if arm == "failsafe":
        return failsafe_gates(run, armed)
    if args.precheck:
        return precheck_gates(run, args.fixture)
    return soak_gates(run, armed, fixture_loops(args.fixture))


def timing_summary(run: dict[str, Any]) -> dict[str, Any]:
    timing = run.get("timingS") or {}
    sessions = {s.get("session"): s.get("timingS") or {} for s in run.get("sessions") or []}
    return {"arm": run.get("arm"), "take": run.get("take"), "launch": timing.get("launch"),
            "script": round(sum(t.get("script") or 0 for t in sessions.values()), 2),
            "quit": timing.get("quit"), "decode": round(sum(t.get("decode") or 0 for t in sessions.values()), 2),
            "total": timing.get("total"), "sessions": sessions}


def print_run(run: dict[str, Any], dest: Path) -> None:
    verdict = f"INVALID ({'; '.join(run['invalid'])})" if not run["valid"] else ("PASS" if run["passed"] else "FAIL")
    print(f"[{run['arm']} rate {run['rate']} take {run['take']}] {verdict}  ready {run.get('readyS')} s  -> {dest}", flush=True)
    for session in run["sessions"]:
        for name, stats in ((session.get("decode") or {}).get("phases") or {}).items():
            if stats:
                print(f"    {session['session']:10s} {name:16s} repeat {stats['repeatFrac']}  raw {stats['rawRepeatFrac']}"
                      f"  decodable {stats['decodableFrac']}  distinct/s {stats['distinctPerS']}  gaps>=3 {stats['gapsGE3']}"
                      f"  back {stats['backwardSteps']}", flush=True)
    for c in run["checks"]:
        mark = "ok  " if c["ok"] else ("FAIL" if c["enforced"] else "note")
        print(f"    {mark} {c['check']}" + (f" = {c['value']} ({c['limit']})" if "value" in c else ""), flush=True)
    summary = {"arm": run["arm"], "rate": run["rate"], "launch": run["launch"], "take": run["take"], "kb": run["kb"],
               "verdict": verdict, "codecs": run.get("codecs"), "kbResult": run.get("kbResult"),
               "gates": {name: {"verdict": g["verdict"], "failing": g["failing"], "invalid": g.get("invalid"),
                                "values": {c["check"]: c.get("value") for c in g["checks"]}}
                         for name, g in run["gates"].items() if isinstance(g, dict) and "verdict" in g}}
    print("TAKE " + json.dumps(summary, default=str), flush=True)


def cross_take(runs: list[dict[str, Any]], armed: dict[str, Any] | None) -> list[dict[str, Any]]:
    """CvC across valid g2 takes: M0 H vs H (expected 0) and M3 tau_O = g2-off S vs g2-off S."""
    checks: list[dict[str, Any]] = []
    g2_runs = [r for r in runs if r["arm"] == "g2" and r["valid"] and not r.get("kb")]
    if len(g2_runs) < 2 or armed is None:
        return checks
    by = [{s["session"]: s for s in r["sessions"]} for r in g2_runs]
    hs = [load_shot(b.get("g2") or {}, "H") for b in by]
    offs = [load_shot(b.get("g2-off") or {}, "S") for b in by]
    shape = next((h.shape for h in hs + offs if h is not None), (1080, 1920, 4))
    everywhere, reg = np.ones(shape[:2], bool), regions(armed, shape)
    h_pairs = [max_delta(a, b, everywhere) for a, b in itertools.combinations(hs, 2)]
    check(checks, "M0 CvC: H vs H across takes", h_pairs, bool(h_pairs) and all(v == 0 for v in h_pairs), "== 0")
    tau_pairs = [max_delta(a, b, reg["O"]) for a, b in itertools.combinations(offs, 2)]
    tau = max(tau_pairs) if tau_pairs and None not in tau_pairs else None
    o_values = [c["value"] for r in g2_runs for c in r["gates"]["M3"]["checks"] if c["check"] == "O: G2-S vs g2-off-S"]
    check(checks, "M3 CvC: tau_O (g2-off S across takes)", tau_pairs, tau == 0, "== 0 (expected)")
    check(checks, "M3: every take's O <= tau_O", [o_values, tau], tau is not None and all(v is not None and v <= tau for v in o_values), "<= tau_O")
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live qualification of the managed OBS (launches OBS; one OBS at a time).")
    parser.add_argument("--arm", choices=("2x", "positive", "both", "g2", "failsafe", "soak"), default="both")
    parser.add_argument("--rate", type=int, choices=sorted(managed_obs.RATES), default=25)
    parser.add_argument("--takes", type=int, default=2, help="ignored (1) for failsafe and soak")
    parser.add_argument("--launch", choices=("hidden", "shown", "projector"), default="hidden", help="shown = hidden launch, then Show OBS once ready; projector = hidden launch + a windowed program projector (eyeball)")
    parser.add_argument("--kb", choices=sorted(KB_SHAS), help="known-bad control: frozen|oldbytes (module splice), latelost (g2)")
    parser.add_argument("--fixture", type=Path, help=f"soak fixture root (default {SOAK_FIXTURE}); other arms: {FIXTURE} (default) or "
                        f"its binary-counter copy ({binary_counter_movie.BINARY_FIXTURE})")
    parser.add_argument("--precheck", action="store_true", help="soak: the loop pre-check instead of the soak")
    parser.add_argument("--soak-minutes", type=int, default=5, help=f">= {SOAK_MIN_MINUTES}; 20 before a show")
    parser.add_argument("--out", type=Path, help="writes <out>/runs/<arm>-<ts>.json, <out>/shots/ and a summary")
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="scratch ManagedObs home (never under ~/Desktop)")
    parser.add_argument("--keep-recordings", action="store_true", help="keep the lossless recordings (~0.5 GB per session)")
    args = parser.parse_args(argv)
    args.kb_splice = None
    if args.arm == "soak":
        args.fixture = (args.fixture or SOAK_FIXTURE).expanduser().resolve()
        check_loop_frames(args.fixture)
    elif args.fixture is not None:
        args.fixture = args.fixture.expanduser().resolve()
        if not p2_family(args.fixture):
            parser.error(f"--fixture for --arm {args.arm} must be {FIXTURE} or a non-looping binary_counter_movie.py copy of it.")
    else:
        args.fixture = FIXTURE
    if args.arm == "soak" and args.soak_minutes < SOAK_MIN_MINUTES:
        parser.error(f"--soak-minutes must be >= {SOAK_MIN_MINUTES} (two wrap windows, then context loss, then at least a minute after it).")
    if args.precheck and args.arm != "soak":
        parser.error("--precheck applies to --arm soak only.")
    if args.out is None:
        parser.error("--out is required.")
    if GL_REPLAY_ENV in os.environ:
        parser.error(f"{GL_REPLAY_ENV} is set; unset it so the g2 session exercises the product default.")
    if args.kb and args.arm not in KB_ARMS[args.kb]:
        parser.error(f"--kb {args.kb} applies to --arm {' / '.join(KB_ARMS[args.kb])} only.")
    home = args.home.expanduser().resolve()
    if home.is_relative_to(Path.home() / "Desktop"):
        parser.error("--home must not be under ~/Desktop (TCC blocks OBS there).")
    if home == managed_obs.DEFAULT_HOME.resolve():
        parser.error("--home must not be the product engine home.")
    if obs_running():
        parser.error("An OBS is already running; quit it first (one OBS at a time).")
    if not (args.fixture / "html-player").is_dir() or not (args.fixture / "html-unmodified/index.html").is_file():
        parser.error(f"fixture missing: {args.fixture}")
    args.fixture_identity = binary_counter_movie.verify_fixture(args.fixture)
    if args.kb:
        args.kb_splice = apply_kb(args.kb)
    armed = None
    if args.arm not in ("2x", "positive", "both"):
        armed = fixture_facts(args.fixture)
        print("ARMED", json.dumps({k: armed[k] for k in ("instanceRect", "movieSlot", "overrideSlots", "assetKeys")}), flush=True)
    (args.out / "runs").mkdir(parents=True, exist_ok=True)
    arms = ("2x", "positive") if args.arm == "both" else (args.arm,)
    takes = 1 if args.arm in ("failsafe", "soak") else args.takes
    awake = subprocess.Popen(["caffeinate", "-dimsu", "-w", str(os.getpid())])
    runs: list[dict[str, Any]] = []
    try:
        for take in range(1, takes + 1):
            for arm in arms:
                if obs_running():
                    print("An OBS is still running after the previous take; stopping.", flush=True)
                    break
                runs.append(run_take(arm, args.rate, take, home, args.out, args, armed))
    finally:
        awake.terminate()
    summary: dict[str, Any] = {"rate": args.rate, "arms": list(arms), "takes": takes, "launch": args.launch, "kb": args.kb,
                               "kbSplice": args.kb_splice, "limits": LIMITS,
                               "runs": [{"arm": r["arm"], "take": r["take"], "ts": r["ts"], "valid": r["valid"], "invalid": r["invalid"],
                                         "passed": r["passed"], "nativeRepeat": native_repeat(r),
                                         "gates": {n: g["verdict"] for n, g in r["gates"].items() if isinstance(g, dict) and "verdict" in g}}
                                        for r in runs]}
    checks: list[dict[str, Any]] = []
    if set(arms) == {"2x", "positive"}:
        by_arm = {arm: [native_repeat(r) for r in runs if r["arm"] == arm and r["valid"]] for arm in arms}
        top_2x = max((v for v in by_arm["2x"] if v is not None), default=None)
        low_pos = min((v for v in by_arm["positive"] if v is not None), default=None)
        ok = top_2x is not None and low_pos is not None and low_pos > top_2x
        binary = fixture_counter(args.fixture) == "binary"
        checks.append({"check": "every positive slide1-native repeat above every 2x one", "value": [low_pos, top_2x], "ok": ok,
                       "enforced": binary or args.rate == 25})
    checks += cross_take(runs, armed)
    summary["checks"] = checks
    summary["timingS"] = [timing_summary(r) for r in runs]
    summary["passed"] = all(r["passed"] for r in runs) and all(c["ok"] for c in checks if c["enforced"])
    dest = args.out / "runs" / f"summary-{stamp()}.json"
    dest.write_text(json.dumps(summary, indent=1, default=str))
    print(f"SUMMARY {'PASS' if summary['passed'] else 'FAIL'} -> {dest}", flush=True)
    for c in checks:
        print(f"    {'ok  ' if c['ok'] else 'FAIL'} {c['check']} = {c['value']}", flush=True)
    print("TIMING " + json.dumps([{k: v for k, v in t.items() if k != "sessions"} for t in summary["timingS"]]), flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
