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
                unrecorded hidden-arm (the g2 session's gl_replay) and an unrecorded mm-off twin (gl_replay="off",
                mm_opacity="off": M3's opaque reference). g2/g2-off: slide 1 as above -> advance -> LIVE (<= 5 s) ->
                slide2-live 10 s (screenshot S) -> hide, slide2-hidden 3 s (screenshot H) -> show, slide2-reshown 4 s ->
                slide2-handback (advance = build 1) 4 s -> slide2-after 3 s (screenshot P3). Gates M0-M4.
  failsafe      one launch: fail-module, fail-zone, fail-bogus (forced-fail seeds), goto2, off, off-2. Gate M5.
  mmo           MO-2 (Magic Move opacity plan §10): one launch per rate (25, 30; --rate ignored), sessions g2 / g2-off x patch
                on / off (g2-on, g2-mmoff, g2off-on, g2off-mmoff) plus a CvC g2-on-2 at 25, all recorded: slide1-native 6 s (key
                shot D) -> mm-move -> advance (key shot M at settle) -> [LIVE] -> slide2-live 4 s -> slide2-handback (build 1)
                -> slide2-after. ROI_top series and an empty-canvas patch are decoded per frame; gates MO-2 (R1-R4, KB =
                the patch-off twins, tau from slide-1 DOM frames) and MO-4 (G2 facts per patch mode). Binary fixture only.
  mmo-cef       MO-3: the MO-1 logger and scorer of mm_opacity_probe inside the OBS CEF, unrecorded; GL replay off and
                auto x arms on, off, off2, sq (8 sessions, one launch). Binary fixture only.
  soak          g2 held on slide 2 for --soak-minutes (>= 4) with per-minute reads, 20 s recordings around a loop wrap at
                minute 1 and just before loseContext (after the first half), build 1, P3/P4; an off twin. Gate M6.
                --precheck: the loop pre-check. --build-fixture KEY: export the owner's looping copy (needs
                --i-have-owner-go; drives Keynote).
--fixture: the soak fixture (default output/p2-soak-loop), or for the other arms the P2 fixture (default) or its binary-counter
copy (`binary_counter_movie.py --build-fixture`, output/p2-binary): its fixture.json selects the decoder's binary counter (its
movie sha256s are checked at startup and recorded per run), and M2 then enforces the hand-back max step per elapsed frame and
an undecodable-free hand-back.
--kb frozen|oldbytes swaps the G2 module text in this process (asserted sha, read back from the host's own report);
--kb latelost forces contextLost while hidden. Refuses to start while any OBS runs or OBED_LIVE_GL_REPLAY or
OBED_LIVE_MM_OPACITY is set (every session passes mm_opacity explicitly); keeps the Mac awake; a Sleep/Wake, a non-lossless
recording or a g2 movie past 44 s of media marks a take INVALID.

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

from obed_edom import live_continuity, live_gl_replay_js, managed_obs, obs_websocket  # noqa: E402
from obed_edom.html_preview import cache_dir  # noqa: E402
from obed_edom.live_continuity import Unsupported, derive_plan  # noqa: E402
from obed_edom.live_host import GL_REPLAY_ENV, MM_OPACITY_ENV, ChromeCdp, LiveOutputHost  # noqa: E402
from obed_edom.managed_obs import ManagedObs  # noqa: E402
from obed_edom.obs_websocket import ObsWebsocket  # noqa: E402

import binary_counter_movie  # noqa: E402
import mm_opacity_probe  # noqa: E402
import obs_cadence_decode  # noqa: E402
from live_continuity_probe import (  # noqa: E402
    GL_REPLAY_READ_JS,
    HASH_JS,
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
    wait_for_decode,
    wait_for_destination_hash,
)
from live_host_probe import wait_for_settlement  # noqa: E402

FIXTURE = REPO / "output/p2-recovery/html-adversarial"
SOAK_FIXTURE = REPO / "output/p2-soak-loop"
P2_SOURCE = Path("/Users/anyhowclick/Desktop/Convert wall to 16x9 CGs/Minimal Alpha_DSK.key")
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
G2_STATS = {"frameLen": 88, "bandCount": 128, "innerRect": {"x": 4, "y": 4, "w": 952, "h": 268}}
EXPECTED_STATS = {"on": {**G2_STATS, "occludedBands": 0, "opacityUnproven": [{"slot": 4, "reason": "rest-opacity"}]},
                  "off": {**G2_STATS, "occludedBands": 20, "opacityUnproven": []}}
MM_MODES = {"auto": "on", "off": "off"}
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
MM_ALPHA = 0.29468628764152527
MMO_RATES = (25, 30)
MMO_SESSIONS = {"g2-on": (None, "auto"), "g2-mmoff": (None, "off"), "g2off-on": ("off", "auto"), "g2off-mmoff": ("off", "off")}
MMO_CVC = ("g2-on", "g2-on-2")
MMO_PAIRS = (("g2-on", "g2-mmoff"), ("g2off-on", "g2off-mmoff"))
MMO_REFERENCE = "g2off-mmoff"
MMO_WINDOW = ("mm-move", "slide2-live", "slide2-handback")
MMO_SLIDE1 = ("slide1-native",)
MMO_FROM_RECT = {"x": 635.86, "y": 722.97, "w": 178.0, "h": 157.0}
MMO_EMPTY_RECT = {"x": 1150, "y": 690, "w": 50, "h": 90}
MMO_ERODE_PX = 6
MMO_CVC_MAX = 2
MMO_SLIDE1_S = 6.0
MMO_LIVE_S = 4.0
MMO_CEF_GL = ("off", "auto")

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


@contextlib.contextmanager
def allow_soak_plan(export_root: Path, slides: list[dict[str, Any]], record: dict[str, Any]) -> Iterator[None]:
    """Harness-only (OQ-3a): add the soak fixture's runtime-plan shas to the continuity allowlist in this process."""
    seen: list[str] = []
    real = live_continuity.plan_signature

    def capture(runtime: dict[str, Any]) -> str:
        seen.append(real(runtime))
        return seen[-1]

    with mock.patch.object(live_continuity, "plan_signature", capture):
        for gl in (False, True):
            plan = derive_plan(export_root, slides, gl_replay=gl)
            if isinstance(plan, Unsupported):
                raise SystemExit(f"soak fixture does not derive a continuity plan (gl_replay={gl}): {plan.reason}")
            plan.to_runtime()
    original = live_continuity.QUALIFIED_PLAN_SHA256
    added = sorted(set(seen) - original)
    if not 1 <= len(set(seen)) <= 2:
        raise SystemExit(f"soak allowlist splice: {len(set(seen))} distinct plan shas, want 1 or 2")
    record.update({"planShas": sorted(set(seen)), "added": added, "alreadyQualified": sorted(set(seen) & original)})
    with mock.patch.object(live_continuity, "QUALIFIED_PLAN_SHA256", original | frozenset(added)):
        for gl in (False, True):
            runtime = derive_plan(export_root, slides, gl_replay=gl).to_runtime()
            if isinstance(runtime, Unsupported):
                raise SystemExit(f"soak allowlist splice did not qualify the plan (gl_replay={gl}): {runtime.reason}")
        yield


def fixture_counter(fixture: Path) -> str:
    return binary_counter_movie.read_manifest(fixture).get("counter", "grey")


def p2_family(fixture: Path) -> bool:
    """The P2 fixture or a counter-swapped copy of it: its plan is qualified as is and its movie does not loop."""
    return fixture.resolve() == FIXTURE.resolve() or binary_counter_movie.read_manifest(fixture).get("base") == binary_counter_movie.FIXTURE_BASE


def movie_geometry(armed: dict[str, Any] | None) -> tuple[float, float, float]:
    if armed is None:
        return obs_cadence_decode.MOVIE_GEOMETRY
    rect = armed["instanceRect"]
    return (rect["x"], rect["y"], rect["w"] / binary_counter_movie.WIDTH)


def fixture_facts(fixture: Path, allow: dict[str, Any] | None) -> dict[str, Any]:
    """The flag-on armed boundary (slot table, instance rect, asset keys), derived offline from the fixture."""
    dest, slides = make_export("facts", fixture)
    try:
        with allow_soak_plan(dest, slides, allow) if allow is not None else contextlib.nullcontext():
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


class LoggedCdp(ChromeCdp):
    """Installs the MO-1 logger innermost (before any page script) on the attached engine page."""

    def start(self) -> None:
        super().start()
        self.call("Page.addScriptToEvaluateOnNewDocument", source=mm_opacity_probe.LOGGER_JS)


def run_session(name: str, script: Callable[[Session], None], ctx: dict[str, Any], *, gl_replay: str | None = None,
                mm_opacity: str = "auto", seed: str | None = None, record: bool = False, allow: dict[str, Any] | None = None,
                logger: bool = False, square: bool = False) -> dict[str, Any]:
    fixture = ctx["fixture"]
    dest, slides = make_export(f"{ctx['tag']}-{name}", fixture)
    kwargs: dict[str, Any] = {"mm_opacity": mm_opacity} if gl_replay is None else {"gl_replay": gl_replay, "mm_opacity": mm_opacity}
    if logger:
        kwargs["transport_factory"] = LoggedCdp
    session: Session | None = None
    out: dict[str, Any] = {"session": name, "glReplayArg": gl_replay, "mmOpacityArg": mm_opacity, "seed": seed, "square": square}
    try:
        with contextlib.ExitStack() as stack:
            stack.enter_context(mm_opacity_probe.square_player(square))
            if allow is not None:
                stack.enter_context(allow_soak_plan(dest, slides, allow))
                out["allowlistSplice"] = allow
            if seed is not None:
                out["seedSplice"] = stack.enter_context(forced_fail_seed(seed))
            if record:
                start_record(*ctx["creds"])
                stack.callback(lambda: out.update(recording=stop_record(*ctx["creds"])))
                time.sleep(2)
            host = LiveOutputHost(dest, slides, attach_endpoint=ctx["endpoint"], attach_match=ctx["target"], bridge="obs-managed",
                                  output_rate=ctx["rate"], **kwargs)
            session = Session(name, host, ctx)
            try:
                host.observe()
                session.out["output"] = host.output
                script(session)
            except Exception:
                session.out["fatal"] = traceback.format_exc()[-3000:]
                print(session.out["fatal"], flush=True)
            finally:
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


def g2_state(s: Session) -> Any:
    return ((s.ev(GL_REPLAY_READ_JS) or {}).get("api") or {}).get("state")


def mmo_script(gl_live: bool) -> Callable[[Session], None]:
    """MO-2: slide-1 DOM (key shot D) -> mm-move marker -> advance (key shot M at settle) -> slide 2 -> build 1."""
    def script(s: Session) -> None:
        s.execute("show")
        time.sleep(1.2)
        started = s.phase("slide1-native")
        hold(started, 1.0)
        s.shot("D")
        hold(started, MMO_SLIDE1_S)
        s.phase("mm-move")
        s.execute("advance")
        before = g2_state(s)
        s.shot("M")
        s.out["shotM"] = {"g2Before": before, "g2After": g2_state(s)}
        if gl_live:
            s.wait_live()
        else:
            time.sleep(1.0)
        started = s.phase("slide2-live")
        s.read("liveStart")
        hold(started, MMO_LIVE_S)
        s.read("liveEnd")
        started = s.phase("slide2-handback")
        hold(started, HANDBACK_LEAD_S)
        s.execute("advance")
        hold(started, 3)
        started = s.phase("slide2-after")
        s.read("after")
        hold(started, 2)
        s.ev(MARK_JS % UNMEASURED_MARK)
    return script


def mo3_script(gl: str, arm: str) -> Callable[[Session], None]:
    """MO-3: `mm_opacity_probe.run_arm`'s drive loop on the engine page; the record is scored by `mm_opacity_probe`."""
    def script(s: Session) -> None:
        rec: dict[str, Any] = {"gl": gl, "arm": arm, "mmOpacityKwarg": mm_opacity_probe.ARMS[arm], "steps": [], "liveGreenSource": "obs"}
        s.out["mo1"] = rec
        rec["output"] = {k: s.host.output.get(k) for k in ("mmOpacity", "continuity")}
        rec["loggerInstalled"] = s.ev("!!window.__OBED_MMO__")
        s.execute("show")
        rec["decoded"] = wait_for_decode(s.host)
        rec["stage"] = s.ev("(function(){var r=document.getElementById('stage').getBoundingClientRect();"
                            "return {x:r.x,y:r.y,width:r.width,height:r.height};})()")
        time.sleep(2.0)
        for label, expect, cfg in mm_opacity_probe.PLAN:
            s.ev(f"window.__OBED_MMO__.setLabel({json.dumps(label)}, {json.dumps(cfg)})")
            step: dict[str, Any] = {"label": label, "expectHash": expect, "hashBefore": s.ev(HASH_JS)}
            s.host.execute("advance")
            _, step["settleS"] = wait_for_settlement(s.host, timeout_s=30)
            if label == "mm12" and gl == "auto":
                started = time.monotonic()
                while time.monotonic() - started < mm_opacity_probe.LIVE_WAIT_S and g2_state(s) not in ("LIVE", "STANDDOWN", "RETIRED"):
                    time.sleep(0.1)
                time.sleep(mm_opacity_probe.LIVE_HOLD_S)
                rec["g2"] = s.ev(GL_REPLAY_READ_JS)
                x, y, w, h = mm_opacity_probe.ROI_TOP
                rec["liveGreen"] = obs_screenshot(*s.creds)[y:y + h, x:x + w].reshape(-1).tolist()
            else:
                time.sleep(mm_opacity_probe.LIVE_HOLD_S if label.startswith("mm") else 1.5)
            step["hashAfter"] = s.ev(HASH_JS)
            rec["steps"].append(step)
        rec["log"] = s.host._require_transport().evaluate(mm_opacity_probe.LOG_READ_JS, deadline_s=60)
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


def mm_mode(session: dict[str, Any]) -> str | None:
    return ((session.get("outputAtStop") or session.get("output") or {}).get("mmOpacity") or {}).get("mode")


def g2_stats_checks(checks: list[dict[str, Any]], stats: dict[str, Any], mode: str | None, prefix: str = "") -> None:
    expected = EXPECTED_STATS.get(mode or "")
    check(checks, f"{prefix}G2 stats expectation for the patch mode", mode, expected is not None, "on | off")
    for key, want in (expected or {}).items():
        check(checks, f"{prefix}{key}", stats.get(key), stats.get(key) == want, f"== {want} (headless r2 / Q0b, patch {mode})")


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
    mm_off = sessions.get("mm-off") or {}
    rate, kb = run["rate"], run.get("kb")
    d_g2, d_off = g2.get("decode") or {}, off.get("decode") or {}
    p_g2, p_off = d_g2.get("phases") or {}, d_off.get("phases") or {}
    live, native = p_g2.get("slide2-live") or {}, p_g2.get("slide1-native") or {}
    reads = g2.get("reads") or {}
    gates: dict[str, Any] = {}

    shots = {(name, tag): load_shot(sess, tag) for name, sess in (("g2", g2), ("off", off), ("mm-off", mm_off)) for tag in ("S", "H", "P3")}
    shape = next((img.shape for img in shots.values() if img is not None), (1080, 1920, 4))
    reg = regions(armed, shape)
    s_g2, h_g2, p3_g2 = shots[("g2", "S")], shots[("g2", "H")], shots[("g2", "P3")]
    s_off, h_off, p3_off = shots[("off", "S")], shots[("off", "H")], shots[("off", "P3")]
    s_opaque = shots[("mm-off", "S")]

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
    check(m1, "mmOpacity mode (g2 / g2-off)", [mm_mode(g2), mm_mode(off)], mm_mode(g2) == mm_mode(off) == "on", "on, on")
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
    g2_stats_checks(m1, stats, mm_mode(g2))
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
    check(m3, "prerequisite: mm-off twin is patch off (opaque reference)", mm_mode(mm_off), mm_mode(mm_off) == "off", "== off")
    fidelity = scaled_alpha_delta(s_g2, s_opaque, band, SLOT_OPACITY)
    check(m3, "edge: G2-S alpha == round(mm-off-S alpha x 0.2947)", fidelity, fidelity is not None and fidelity <= tol, f"<= {tol}")
    unscaled = scaled_alpha_delta(s_g2, s_opaque, band, 1.0)
    check(m3, "KB: edge vs unscaled mm-off-S alpha fails", unscaled, unscaled is not None and unscaled > tol, f"> {tol}")
    edge_dom = max_delta(s_g2, p3_g2, band)
    edge_count = int((band & (np.abs(s_g2.astype(np.int16) - p3_g2.astype(np.int16)).max(axis=2) > LIMITS["domTol"])).sum()) \
        if s_g2 is not None and p3_g2 is not None else None
    check(m3, "report: edge G2-S vs G2-P3 (player vs DOM softness) max, px > 3", [edge_dom, edge_count], True, enforced=False)
    opaque_alpha = alpha_range(s_opaque, reg["T"])
    check(m3, "KB: mm-off-S T alpha fails the slot check", opaque_alpha,
          opaque_alpha is not None and not (want - tol <= opaque_alpha[0] and opaque_alpha[1] <= want + tol), f"not {want} +- {tol}")
    check(m3, "report: g2-off-S T alpha (patch on, GL replay off)", alpha_range(s_off, reg["T"]), True, f"{want} +- {tol} expected",
          enforced=False)
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


def mmo_base(name: str) -> str:
    return MMO_CVC[0] if name == MMO_CVC[1] else name


def mmo_masks(armed: dict[str, Any], shape: tuple[int, ...]) -> dict[str, np.ndarray]:
    """top = ROI_top: the slide-1 square (`MMO_FROM_RECT`: effect_1_to_2 slot 4 wrapper position +- leaf size / 2) intersected
    with its slide-2 rect (the override slot), minus the movie rect padded 2, eroded `MMO_ERODE_PX` (past the square's
    ~2x AA edge). empty = a same-frame canvas patch outside every slot but the full-stage background."""
    if len(armed["overrideSlots"]) != 1:
        raise RuntimeError(f"expected one opacity-override slot, got {armed['overrideSlots']}")
    to = armed["slotRects"][armed["overrideSlots"][0]]
    top = rect_mask(shape, MMO_FROM_RECT) & rect_mask(shape, to) & ~rect_mask(shape, armed["instanceRect"], REGION_PAD)
    top = erode(top, MMO_ERODE_PX)
    empty = rect_mask(shape, MMO_EMPTY_RECT)
    slots = [r for r in armed["slotRects"] if not (r["w"] >= shape[1] and r["h"] >= shape[0])]
    if not top.any() or any((empty & rect_mask(shape, r, REGION_PAD)).any() for r in slots):
        raise RuntimeError(f"MO-2 masks: ROI_top {int(top.sum())} px, or the empty patch overlaps a slot")
    return {"top": top, "empty": empty}


def load_series(session: dict[str, Any]) -> dict[str, np.ndarray] | None:
    path = (session.get("decode") or {}).get("seriesPath")
    if not path or not Path(path).exists():
        return None
    with np.load(path) as data:
        return {key: data[key] for key in data.files}


def phase_rows(series: dict[str, np.ndarray], phases: tuple[str, ...]) -> np.ndarray:
    return np.isin(series["phase"], phases)


def phase_median(series: dict[str, np.ndarray] | None, phases: tuple[str, ...]) -> np.ndarray | None:
    if series is None or not phase_rows(series, phases).any():
        return None
    return np.median(series["pixels.top"][phase_rows(series, phases)].astype(float), axis=0)


def median_delta(a: np.ndarray | None, b: np.ndarray | None) -> float | None:
    return None if a is None or b is None else round(float(np.abs(a - b).max()), 2)


def expected_top(series: dict[str, np.ndarray], s_off: np.ndarray, alpha: float = MM_ALPHA) -> np.ndarray:
    """Per frame E = alpha * S_off + (1 - alpha) * B_frame (B_frame = that frame's empty-patch mean)."""
    return alpha * s_off[None] + (1.0 - alpha) * series["means.empty"][:, None, :]


def slide1_instrument(series: dict[str, np.ndarray] | None, s_off: np.ndarray | None, alpha: float = MM_ALPHA) -> float | None:
    """max |DOM - E| over slide-1 frames: how well E predicts the (Keynote-correct) DOM square."""
    if series is None or s_off is None or not phase_rows(series, MMO_SLIDE1).any():
        return None
    rows = phase_rows(series, MMO_SLIDE1)
    return round(float(np.abs(series["pixels.top"][rows].astype(float) - expected_top(series, s_off, alpha)[rows]).max()), 2)


def mmo_tau(series: dict[str, dict[str, np.ndarray] | None], s_off: np.ndarray | None, alpha: float = MM_ALPHA) -> dict[str, Any]:
    """tau = max(patch on vs off slide-1 DOM medians per GL mode, instrument |DOM - E| per session) + 1."""
    dom = {f"{on}/{off}": median_delta(phase_median(series.get(on), MMO_SLIDE1), phase_median(series.get(off), MMO_SLIDE1))
           for on, off in MMO_PAIRS}
    instrument = {name: slide1_instrument(ser, s_off, alpha) for name, ser in series.items()}
    values = [*dom.values(), *instrument.values()]
    tau = round(max(values) + 1, 2) if values and None not in values else None
    return {"tau": tau, "domOnOff": dom, "instrument": instrument}


def mmo_series_checks(series: dict[str, np.ndarray] | None, s_off: np.ndarray | None, tau: float | None,
                      alpha: float = MM_ALPHA) -> dict[str, Any]:
    """Over the frames from mm-move to past build 1 (`MMO_WINDOW`): R1 frames whose ROI_top mean is within tau of S_off's,
    R2 max |ROI_top - E|, R3 max |ROI_top| step between consecutive frames (covers DOM -> GL and GL -> DOM)."""
    if series is None or s_off is None or tau is None or not phase_rows(series, MMO_WINDOW).any():
        return {"frames": 0, "R1": None, "R2": None, "R3": None}
    rows = phase_rows(series, MMO_WINDOW)
    top = series["pixels.top"][rows].astype(float)
    near = np.abs(top.mean(axis=1) - s_off.mean(axis=0)).max(axis=1) <= tau
    r2 = np.abs(top - expected_top(series, s_off, alpha)[rows]).max(axis=(1, 2))
    steps = np.abs(np.diff(top, axis=0)).max(axis=(1, 2)) if len(top) > 1 else np.zeros(1)
    worst = int(steps.argmax())
    index, phase = series["index"][rows], series["phase"][rows]
    return {"frames": int(rows.sum()), "R1": int(near.sum()), "R1First": int(index[near][0]) if near.any() else None,
            "R2": round(float(r2.max()), 2), "R2Frame": int(index[int(r2.argmax())]), "R3": round(float(steps.max()), 2),
            "R3At": [int(index[worst]), str(phase[worst]), str(phase[min(worst + 1, len(phase) - 1)])]}


def shot_alpha(img: np.ndarray | None, mask: np.ndarray) -> np.ndarray | None:
    return None if img is None else img[..., 3][mask].astype(float)


def mmo_key(shots: dict[str, dict[str, np.ndarray | None]], masks: dict[str, np.ndarray], alpha: float = MM_ALPHA) -> dict[str, Any]:
    """R4 on the key: per session max |M - D| alpha on ROI_top (M at settle, D on slide 1); tau_key = max(D patch on vs off per GL
    mode, |D - E_key| per session) + 1, E_key = alpha * the reference's M alpha + (1 - alpha) * that D's empty-patch alpha."""
    top, empty = masks["top"], masks["empty"]
    ref = shot_alpha((shots.get(MMO_REFERENCE) or {}).get("M"), top)
    dom: dict[str, float | None] = {}
    for on, off in MMO_PAIRS:
        a, b = (shot_alpha((shots.get(n) or {}).get("D"), top) for n in (on, off))
        dom[f"{on}/{off}"] = None if a is None or b is None else float(np.abs(a - b).max())
    instrument: dict[str, float | None] = {}
    r4: dict[str, float | None] = {}
    for name, pair in shots.items():
        d, m = shot_alpha(pair.get("D"), top), shot_alpha(pair.get("M"), top)
        if d is None or ref is None:
            instrument[name] = None
        else:
            instrument[name] = float(np.abs(d - (alpha * ref + (1.0 - alpha) * pair["D"][..., 3][empty].mean())).max())
        r4[name] = None if d is None or m is None else float(np.abs(m - d).max())
    values = [*dom.values(), *instrument.values()]
    tau_key = round(max(values) + 1, 2) if values and None not in values else None
    return {"tauKey": tau_key, "domOnOff": dom, "instrument": instrument, "R4": r4}


def mmo_cvc(a: dict[str, np.ndarray] | None, b: dict[str, np.ndarray] | None, shots_a: dict[str, Any], shots_b: dict[str, Any],
            top: np.ndarray) -> dict[str, Any]:
    values = {phase: median_delta(phase_median(a, (phase,)), phase_median(b, (phase,)))
              for phase in (*MMO_SLIDE1, "slide2-live", "slide2-after")}
    for tag in ("D", "M"):
        x, y = shot_alpha(shots_a.get(tag), top), shot_alpha(shots_b.get(tag), top)
        values[f"key {tag}"] = None if x is None or y is None else float(np.abs(x - y).max())
    return {"values": values, "max": None if None in values.values() else max(values.values())}


def mmo_gates(run: dict[str, Any], armed: dict[str, Any]) -> dict[str, Any]:
    sessions = {s["session"]: s for s in run["sessions"]}
    masks = mmo_masks(armed, (1080, 1920, 4))
    series = {name: load_series(sess) for name, sess in sessions.items()}
    shots = {name: {tag: load_shot(sess, tag) for tag in ("D", "M")} for name, sess in sessions.items()}
    checks: list[dict[str, Any]] = []
    for name, sess in sessions.items():
        want = MM_MODES[MMO_SESSIONS[mmo_base(name)][1]]
        check(checks, f"{name}: mmOpacity mode", mm_mode(sess), mm_mode(sess) == want, f"== {want}")
    s_off = phase_median(series.get(MMO_REFERENCE), ("slide2-live",))
    check(checks, f"S_off: {MMO_REFERENCE} slide2-live ROI_top", None if s_off is None else np.round(s_off.mean(axis=0), 1).tolist(),
          s_off is not None, "present")
    cal, key = mmo_tau(series, s_off), mmo_key(shots, masks)
    tau, tau_key = cal["tau"], key["tauKey"]
    check(checks, "report: tau (RGB), tau_key (alpha)", {"tau": cal, "tauKey": {k: v for k, v in key.items() if k != "R4"}}, True,
          enforced=False)
    cvc = None
    if run["rate"] == 25:
        cvc = mmo_cvc(series.get(MMO_CVC[0]), series.get(MMO_CVC[1]), shots.get(MMO_CVC[0]) or {}, shots.get(MMO_CVC[1]) or {},
                      masks["top"])
        check(checks, f"CvC {MMO_CVC[0]} vs {MMO_CVC[1]} before tau", cvc, cvc["max"] is not None and cvc["max"] <= MMO_CVC_MAX,
              f"<= {MMO_CVC_MAX}")
    dom_ref = phase_median(series.get(MMO_REFERENCE), MMO_SLIDE1)
    premise = None if dom_ref is None or s_off is None else round(float(np.abs(s_off.mean(axis=0) - dom_ref.mean(axis=0)).max()), 2)
    check(checks, "premise: S_off differs from the slide-1 DOM square by > tau", [premise, tau],
          None not in (premise, tau) and premise > tau, "> tau")
    per: dict[str, Any] = {}
    for on, off in MMO_PAIRS:
        r_on, r_off = (mmo_series_checks(series.get(n), s_off, tau) for n in (on, off))
        per[on], per[off] = r_on, r_off
        check(checks, f"{on} frames in window", r_on["frames"], r_on["frames"] > 0, "> 0")
        check(checks, f"{on} R1: frames within tau of S_off", r_on["R1"], r_on["R1"] == 0, "== 0")
        check(checks, f"KB: {off} R1", r_off["R1"], r_off["R1"] is not None and r_off["R1"] > 0, "> 0")
        for name, value, limit in (("R2: max |ROI_top - E|", "R2", tau), ("R3: max frame-to-frame step", "R3", tau),
                                   ("R4: key alpha |M - D|", None, tau_key)):
            v_on = r_on[value] if value else key["R4"].get(on)
            v_off = r_off[value] if value else key["R4"].get(off)
            label = "tau_key" if value is None else "tau"
            check(checks, f"{on} {name}", v_on, None not in (v_on, limit) and v_on <= limit, f"<= {label} {limit}")
            check(checks, f"KB: {off} {name}", v_off, None not in (v_off, limit) and v_off > limit, f"> {label} {limit}")
        cadence = {n: {ph: {k: ((((sessions.get(n) or {}).get("decode") or {}).get("phases") or {}).get(ph) or {}).get(k)
                            for k in ("repeatFrac", "distinctPerS")} for ph in ("mm-move", "slide2-live")} for n in (on, off)}
        check(checks, f"report: cadence {on} vs {off}", cadence, True, enforced=False)
    check(checks, "report: shot M G2 state before/after", {n: sess.get("shotM") for n, sess in sessions.items()}, True, enforced=False)

    m4: list[dict[str, Any]] = []
    for name in ("g2-on", "g2-mmoff"):
        sess = sessions.get(name) or {}
        wait = sess.get("liveWait") or {}
        check(m4, f"{name}: G2 LIVE", wait, wait.get("live") is True, "LIVE (a stand-down voids the pair)")
        g2_stats_checks(m4, api_of((sess.get("reads") or {}).get("liveEnd")).get("stats") or {}, mm_mode(sess), f"{name}: ")
    live = median_delta(phase_median(series.get("g2-on"), ("slide2-live",)), phase_median(series.get("g2-mmoff"), ("slide2-live",)))
    check(m4, "report: g2-on vs g2-mmoff slide2-live ROI_top (LIVE equal)", live, True, "~0 (headless MO-4 enforces 0)", enforced=False)
    return {"MO-2": gate(checks), "MO-4": gate(m4), "mmoCalibration": {"tau": tau, "tauKey": tau_key, "cvc": cvc, "perSession": per}}


def mmo_cef_gates(run: dict[str, Any]) -> dict[str, Any]:
    sessions = {s["session"]: s for s in run["sessions"]}
    records: dict[str, dict[str, dict[str, Any]]] = {}
    for gl in MMO_CEF_GL:
        for arm in mm_opacity_probe.ARMS:
            sess = sessions.get(f"mo3-{gl}-{arm}")
            if sess is None:
                continue
            record = dict(sess.get("mo1") or {"gl": gl, "arm": arm})
            if sess.get("fatal"):
                record["error"] = sess["fatal"]
            records.setdefault(gl, {})[arm] = record
    verdict = mm_opacity_probe.score_all(records)
    checks: list[dict[str, Any]] = []
    for gl in MMO_CEF_GL:
        check(checks, f"{gl}: every arm ran", sorted((records.get(gl) or {})), set(records.get(gl) or {}) == set(mm_opacity_probe.ARMS),
              ",".join(mm_opacity_probe.ARMS))
    for gl, gates in verdict["modes"].items():
        for name, result in gates.items():
            check(checks, f"{gl} {name}", [result["verdict"], result.get("reasons")], result["verdict"] == "PASS", "PASS")
    return {"MO-3": gate(checks), "probeVerdict": verdict}


def mmo_summary(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """MO-2 across the per-rate takes: both rates ran and the rate-25 CvC (which sets tau for both) read <= 2."""
    checks: list[dict[str, Any]] = []
    mmo = [r for r in runs if r["arm"] == "mmo"]
    if not mmo:
        return checks
    check(checks, "MO-2: a valid take per rate", sorted(r["rate"] for r in mmo if r["valid"]),
          sorted(r["rate"] for r in mmo if r["valid"]) == list(MMO_RATES), f"== {list(MMO_RATES)}")
    cvc = [((r.get("gates") or {}).get("mmoCalibration") or {}).get("cvc") for r in mmo if r["rate"] == 25]
    value = cvc[0].get("max") if cvc and cvc[0] else None
    check(checks, "MO-2 CvC (rate 25) gates every rate", value, value is not None and value <= MMO_CVC_MAX, f"<= {MMO_CVC_MAX}")
    return checks


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
    check(checks, "(a) loop representation (report)", static, True, enforced=False)
    check(checks, "(a) video.loop on slide 1", [v.get("loop") for v in session.get("slide1Videos") or []], True, enforced=False)
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


def loop_representation(fixture: Path) -> dict[str, Any]:
    ours, p2 = fixture / "html-unmodified", FIXTURE / "html-unmodified"
    differing = []
    for path in sorted(ours.rglob("*.json")):
        other = p2 / path.relative_to(ours)
        if not other.exists() or other.read_bytes() != path.read_bytes():
            differing.append(str(path.relative_to(ours)))
    loop_keys = set()
    for path in sorted(ours.rglob("*.json")):
        for key, value in re.findall(r'"(\w*[Ll]oop\w*)"\s*:\s*([^,}\]]+)', path.read_text(errors="ignore")):
            loop_keys.add(f"{path.relative_to(ours)}:{key}={value.strip()}")
    main_js = next(iter(ours.rglob("main.js")), None)
    return {"differingJson": differing[:40], "loopKeys": sorted(loop_keys)[:40],
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
                run_session("hidden-arm", hidden_arm_script, ctx),
                run_session("mm-off", g2_script(None, armed), ctx, gl_replay="off", mm_opacity="off")]
    if arm == "mmo":
        names = [*MMO_SESSIONS, MMO_CVC[1]] if ctx["rate"] == 25 else list(MMO_SESSIONS)
        return [run_session(name, mmo_script(MMO_SESSIONS[mmo_base(name)][0] is None), ctx, gl_replay=MMO_SESSIONS[mmo_base(name)][0],
                            mm_opacity=MMO_SESSIONS[mmo_base(name)][1], record=True) for name in names]
    if arm == "mmo-cef":
        return [run_session(f"mo3-{gl}-{name}", mo3_script(gl, name), ctx, gl_replay=gl, mm_opacity=kwarg, logger=True, square=name == "sq")
                for gl in MMO_CEF_GL for name, kwarg in mm_opacity_probe.ARMS.items()]
    if arm == "failsafe":
        return [run_session("fail-module", failsafe_script(False), ctx, seed="planUnreadable"),
                run_session("fail-zone", failsafe_script(False), ctx, seed="posterAmbiguous"),
                run_session("fail-bogus", failsafe_script(False), ctx, seed="bogusReason"),
                run_session("goto2", failsafe_script(True), ctx),
                run_session("off", failsafe_script(False), ctx, gl_replay="off"),
                run_session("off-2", failsafe_script(False), ctx, gl_replay="off")]
    looping = not p2_family(ctx["fixture"])
    allow = {} if looping else None
    if args.precheck:
        return [run_session("precheck", precheck_script(armed), ctx, allow=allow)]
    return [run_session("soak", soak_script(args.soak_minutes, armed, looping), ctx, allow=allow),
            run_session("soak-off", soak_off_script, ctx, gl_replay="off", allow=None if allow is None else {})]


def ring_exclusions(armed: dict[str, Any]) -> list[tuple[float, float, float, float]]:
    """Every slot but the movie's own and the full-stage background: their edges sharpen GL -> DOM at build 1."""
    return [rect_tuple(r) for i, r in enumerate(armed["slotRects"])
            if i != armed["movieSlot"] and not (r["w"] >= 1920 and r["h"] >= 1080)]


def decode_session(session: dict[str, Any], recording: str | None, *, rings: list[Any] | None, loop_frames: int | None,
                   keep: bool, crops_dir: Path | None = None, ring_exclude: list[Any] = (), counter: str = "grey",
                   geometry: tuple[float, float, float] = obs_cadence_decode.MOVIE_GEOMETRY, masks: dict[str, np.ndarray] | None = None,
                   series_path: Path | None = None) -> dict[str, Any] | None:
    """With `masks` (MO-2) the per-frame ROI_top pixels and empty-patch means go to `series_path` (npz), not the run JSON."""
    path = Path(recording) if recording else None
    if path is None or not path.exists():
        return None
    print(f"  decoding {session['session']} {path}", flush=True)
    try:
        result = obs_cadence_decode.decode_recording(
            path, rings=rings, statics=rings, ring_exclude=ring_exclude, loop_frames=loop_frames,
            crops_dir=crops_dir if keep and rings else None, counter=counter, geometry=geometry,
            pixel_series={"top": masks["top"]} if masks else None, mean_series={"empty": masks["empty"]} if masks else None)
        series = result.pop("series", None)
        if series is not None and series_path is not None:
            np.savez_compressed(series_path, **series)
            result["seriesPath"] = str(series_path)
        return result
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
    print(f"[{arm} rate {rate} source {source} {args.launch} take {take}] launching", flush=True)
    try:
        creds = launch_engine(engine, rate, source, args.launch, run)
        ctx = {"endpoint": engine.cdp_endpoint, "target": engine.target_id, "rate": rate, "creds": creds, "shots": shots,
               "fixture": args.fixture, "tag": f"{arm}{rate}{take}{ts}",
               "engineState": lambda: {k: engine.state().get(k) for k in ("state", "warnings")}}
        run["sessions"] = sessions_for(arm, ctx, args, armed)
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

    looping = not p2_family(args.fixture)
    rings = [rect_tuple(armed["instanceRect"])] if arm == "g2" else None
    ring_exclude = ring_exclusions(armed) if arm == "g2" else []
    counter, geometry = run["counter"], movie_geometry(armed)
    masks = mmo_masks(armed, (1080, 1920)) if arm == "mmo" else None
    for session in run["sessions"]:
        if session.get("recording"):
            session["decode"] = decode_session(session, session["recording"], rings=rings, loop_frames=None, keep=args.keep_recordings,
                                               crops_dir=shots / f"{session['session']}-crops", ring_exclude=ring_exclude,
                                               counter=counter, geometry=geometry, masks=masks,
                                               series_path=shots / f"{session['session']}-series.npz")
        for window in session.get("windows") or []:
            window["decode"] = decode_session(session, window["recording"], rings=None, loop_frames=SOAK_LOOP_FRAMES if looping else None,
                                              keep=args.keep_recordings, counter=counter, geometry=geometry)
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
    if arm == "mmo":
        return mmo_gates(run, armed)
    if arm == "mmo-cef":
        return mmo_cef_gates(run)
    if args.precheck:
        return precheck_gates(run, args.fixture)
    return soak_gates(run, armed, not p2_family(args.fixture))


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


def build_fixture(key: Path, dest: Path) -> int:
    """Owner-go only (drives Keynote): export the owner's looping copy with the P2 pipeline's own steps into `dest`."""
    from obed_edom.html_alpha_probe import file_identity, strip_export_pdf_bg_fills, write_json, write_patched_export
    from obed_edom.html_preview import export_html
    from p2_recovery_html_dissolve_live import _replace_hevc_movies

    before = file_identity(key)
    dest.mkdir(parents=True, exist_ok=True)
    unmodified, disposable = dest / "html-unmodified", dest / "html-disposable"
    for path in (unmodified, disposable):
        if path.exists():
            shutil.rmtree(path)
    export_html(key, unmodified, log=print)
    shutil.copytree(unmodified, disposable)
    write_json(dest / "asset-replace.json", _replace_hevc_movies(disposable))
    write_json(dest / "pdf-strip.json", strip_export_pdf_bg_fills(disposable))
    write_patched_export(disposable, dest / "html-player")
    after = file_identity(key)
    record = {"source": before.as_dict(), "sourceAfter": after.as_dict(), "sourceUnchanged": before.sha256 == after.sha256,
              "unmodified": file_identity(unmodified).as_dict(), "player": file_identity(dest / "html-player").as_dict()}
    write_json(dest / "fingerprints.json", record)
    print("BUILT", dest, json.dumps(record, default=str), flush=True)
    return 0 if record["sourceUnchanged"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live qualification of the managed OBS (launches OBS; one OBS at a time).")
    parser.add_argument("--arm", choices=("2x", "positive", "both", "g2", "failsafe", "soak", "mmo", "mmo-cef"), default="both")
    parser.add_argument("--rate", type=int, choices=sorted(managed_obs.RATES), default=25, help=f"ignored for mmo ({MMO_RATES})")
    parser.add_argument("--takes", type=int, default=2, help="ignored (1) for failsafe, soak, mmo and mmo-cef")
    parser.add_argument("--launch", choices=("hidden", "shown", "projector"), default="hidden", help="shown = hidden launch, then Show OBS once ready; projector = hidden launch + a windowed program projector (eyeball)")
    parser.add_argument("--kb", choices=sorted(KB_SHAS), help="known-bad control: frozen|oldbytes (module splice), latelost (g2)")
    parser.add_argument("--fixture", type=Path, help=f"soak fixture root (default {SOAK_FIXTURE}); other arms: {FIXTURE} (default) or "
                        f"its binary-counter copy ({binary_counter_movie.BINARY_FIXTURE})")
    parser.add_argument("--precheck", action="store_true", help="soak: the loop pre-check instead of the soak")
    parser.add_argument("--soak-minutes", type=int, default=5, help=f">= {SOAK_MIN_MINUTES}; 20 before a show")
    parser.add_argument("--build-fixture", type=Path, metavar="KEY", help="soak: export the owner's looping .key copy into --fixture")
    parser.add_argument("--i-have-owner-go", action="store_true", help="required by --build-fixture (it drives Keynote)")
    parser.add_argument("--out", type=Path, help="writes <out>/runs/<arm>-<ts>.json, <out>/shots/ and a summary")
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="scratch ManagedObs home (never under ~/Desktop)")
    parser.add_argument("--keep-recordings", action="store_true", help="keep the lossless recordings (~0.5 GB per session)")
    args = parser.parse_args(argv)
    args.kb_splice = None
    if args.arm == "soak":
        args.fixture = (args.fixture or SOAK_FIXTURE).expanduser().resolve()
    elif args.fixture is not None:
        args.fixture = args.fixture.expanduser().resolve()
        if not p2_family(args.fixture):
            parser.error(f"--fixture for --arm {args.arm} must be {FIXTURE} or a binary_counter_movie.py copy of it.")
    else:
        args.fixture = FIXTURE
    if args.arm in ("mmo", "mmo-cef") and fixture_counter(args.fixture) != "binary":
        parser.error(f"--arm {args.arm} needs the binary-counter fixture ({binary_counter_movie.BINARY_FIXTURE}).")
    if args.arm == "soak" and args.soak_minutes < SOAK_MIN_MINUTES:
        parser.error(f"--soak-minutes must be >= {SOAK_MIN_MINUTES} (two wrap windows, then context loss, then at least a minute after it).")
    if (args.precheck or args.build_fixture) and args.arm != "soak":
        parser.error("--precheck and --build-fixture apply to --arm soak only.")
    if args.build_fixture:
        key = args.build_fixture.expanduser().resolve()
        if not args.i_have_owner_go:
            parser.error("--build-fixture drives Keynote: pass --i-have-owner-go only with the owner's explicit go.")
        if key == P2_SOURCE.resolve() or not key.suffix == ".key" or not key.exists():
            parser.error("--build-fixture needs the owner's looping .key copy, never the P2 source deck.")
        if "p2-recovery" in args.fixture.parts:
            parser.error("--build-fixture never writes output/p2-recovery/.")
        return build_fixture(key, args.fixture)
    if args.out is None:
        parser.error("--out is required.")
    if GL_REPLAY_ENV in os.environ:
        parser.error(f"{GL_REPLAY_ENV} is set; unset it so the g2 session exercises the product default.")
    if MM_OPACITY_ENV in os.environ:
        parser.error(f"{MM_OPACITY_ENV} is set; unset it (every session passes mm_opacity explicitly).")
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
        allow: dict[str, Any] | None = None if p2_family(args.fixture) else {}
        armed = fixture_facts(args.fixture, allow)
        print("ARMED", json.dumps({k: armed[k] for k in ("instanceRect", "movieSlot", "overrideSlots", "assetKeys")}), flush=True)
        if args.arm == "mmo":
            top = mmo_masks(armed, (1080, 1920))["top"]
            ys, xs = np.nonzero(top)
            print("MO-2 ROI_top", [int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())], int(top.sum()), "px", flush=True)
        if allow is not None:
            print("ALLOWLIST SPLICE (harness-only)", json.dumps(allow), flush=True)
    (args.out / "runs").mkdir(parents=True, exist_ok=True)
    arms = ("2x", "positive") if args.arm == "both" else (args.arm,)
    takes = 1 if args.arm in ("failsafe", "soak", "mmo", "mmo-cef") else args.takes
    rates = MMO_RATES if args.arm == "mmo" else (args.rate,)
    awake = subprocess.Popen(["caffeinate", "-dimsu", "-w", str(os.getpid())])
    runs: list[dict[str, Any]] = []
    try:
        for take in range(1, takes + 1):
            for arm, rate in itertools.product(arms, rates):
                if obs_running():
                    print("An OBS is still running after the previous take; stopping.", flush=True)
                    break
                runs.append(run_take(arm, rate, take, home, args.out, args, armed))
    finally:
        awake.terminate()
    summary: dict[str, Any] = {"rate": list(rates) if len(rates) > 1 else args.rate, "arms": list(arms), "takes": takes, "launch": args.launch, "kb": args.kb,
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
    checks += cross_take(runs, armed) + mmo_summary(runs)
    summary["checks"] = checks
    summary["passed"] = all(r["passed"] for r in runs) and all(c["ok"] for c in checks if c["enforced"])
    dest = args.out / "runs" / f"summary-{stamp()}.json"
    dest.write_text(json.dumps(summary, indent=1, default=str))
    print(f"SUMMARY {'PASS' if summary['passed'] else 'FAIL'} -> {dest}", flush=True)
    for c in checks:
        print(f"    {'ok  ' if c['ok'] else 'FAIL'} {c['check']} = {c['value']}", flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
