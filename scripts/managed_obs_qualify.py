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
                on / off (g2-on, g2-mmoff, g2off-on, g2off-mmoff) plus a CvC g2-on-2 at each rate, all recorded: slide1-native 6 s (key
                shot D) -> mm-move -> advance (key shot M at settle) -> [LIVE] -> slide2-live 4 s -> slide2-handback (build 1)
                -> slide2-after. ROI_top series and an empty-canvas patch are decoded per frame; gates MO-2 (R1, R2 = the
                neutral-background test with R3's handovers folded in, R4; KB = the patch-off twins, tau and tau_key per take
                from its own slide-1 DOM frames, gated by that take's CvC) and MO-4 (G2 facts per patch mode). Binary fixture
                only. --score DIR re-scores the saved takes under DIR/runs without OBS.
  mmo-cef       MO-3: the MO-1 logger, step loop (`mm_opacity_probe.drive`) and scorer of mm_opacity_probe inside the OBS
                CEF, unrecorded; GL replay off x arms on, off, off2, sq and auto x those plus the forced stand-down pair fsd,
                fsdoff (10 sessions, one launch). Binary fixture only.
  dissolve      DX-2 (dissolve cross-fade plan §9.2): one launch, unrecorded; DX-1's P2 cross-fade, cut and opaque arms
                (`DISSOLVE_ARMS`: no screen-*, delay-*, on-sw, lifecycle, media, tone or m-snap) plus cef-skip and cef-skip-dsk
                (P2 2->3 and DSK 7->8 movie slides publish a take with no holder), each a `LiveOutputHost` session with
                `dissolve_probe`'s resolver, hook and driver, a GetSourceScreenshot burst as the capture (cut sessions score
                those shots as the screencast), continuity, G2 state, colour tuples and the served digest recorded.
                opaque-off runs first and fixes the calibration (`dissolve_calibration`) before the other captures;
                `dissolve_probe`'s integrity rules and scorer then read every control before the candidates. Checks whose
                controls DX-2 does not run (no flash, screen) are reported, not gated. CEF is attach mode, so every session
                must record `output.placement` grant null, reason `attached`, and bind no holder (a bound holder is a FAIL
                even when the round is INCONCLUSIVE). Ignores --fixture.
  feed          Stage B Q6: continuous `mm_feed="on"` and qualification-only one-shot `mm_feed="off"` sessions on an
                Alpha/D7 fixture, gated on in-frame feed plus exact poster-hold verdicts. One take, unrecorded.
  soak          g2 held on slide 2 for --soak-minutes (>= 4) with per-minute reads, 20 s recordings around a loop wrap at
                minute 1 and just before loseContext (after the first half), build 1, P3/P4; an off twin. Gate M6.
                --precheck: the loop pre-check.
--fixture: the soak fixture (default output/fixtures/p2-loop, `loop_fixture.py`; its fixture.json `loop` key marks it looping, and it
must qualify on product code), or for the other arms the P2 fixture (default) or its binary-counter
copy (`binary_counter_movie.py --build-fixture`, output/fixtures/p2-binary): its fixture.json selects the decoder's binary counter (its
movie sha256s are checked at startup and recorded per run), and M2 then enforces the hand-back max step per elapsed frame and
an undecodable-free hand-back.
--kb frozen|oldbytes swaps the G2 module text in this process (asserted sha, read back from the host's own report);
--kb latelost forces contextLost while hidden. Refuses to start while any OBS runs or OBED_LIVE_GL_REPLAY or
OBED_LIVE_MM_OPACITY is set (every session passes mm_opacity explicitly); keeps the Mac awake; a Sleep/Wake, a non-lossless
recording, a g2 movie past 44 s of media, or a patch-on G2 session (g2, g2-on, g2-on-2) with the pre-fix unproven set
(rest-opacity: the hand-back fix did not engage, `UNENGAGED_STATS`) marks a take INVALID; the patch-on sessions without
G2 (g2-off, g2off-on) carry no engagement signal and are unchecked.

usage: uv run python scripts/managed_obs_qualify.py --arm g2 --rate 25 --takes 2 --out DIR
       uv run python scripts/managed_obs_qualify.py --score DIR
"""

from __future__ import annotations

import argparse
import base64
from collections import Counter
import contextlib
import hashlib
import io
import itertools
import json
import math
import os
import re
import resource
import shutil
import subprocess
import sys
import threading
import time
import traceback
import types
from concurrent.futures import Future
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator
from unittest import mock

import imageio_ffmpeg
import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from obed_edom.fixture_paths import fixture  # noqa: E402
from obed_edom import live_gl_replay_js, live_host, live_runtime, managed_obs, mm_handback_score, obs_websocket, placement_probe  # noqa: E402
from obed_edom.html_preview import cache_dir  # noqa: E402
from obed_edom.live_continuity import Unsupported, plan_signature  # noqa: E402
from obed_edom.live_host import GL_REPLAY_ENV, MM_OPACITY_ENV, ChromeCdp, LiveOutputHost, _ProgramGuard  # noqa: E402
from obed_edom.managed_obs import ManagedObs  # noqa: E402
from obed_edom.obs_websocket import ObsWebsocket  # noqa: E402

import binary_counter_movie  # noqa: E402
import dissolve_probe  # noqa: E402
import live_evidence_contract as contract  # noqa: E402
import mm_opacity_probe  # noqa: E402
import obs_cadence_decode  # noqa: E402
from live_continuity_probe import (  # noqa: E402
    GL_REPLAY_READ_JS,
    PAINTING_VIDEOS_JS,
    P2_PLAN_SHA256,
    _carried_el_id,
    _el_id,
    _events_readable,
    _handed_off,
    _movie_entries,
    _notes,
    armed_evidence,
    bind_feed_source_fps,
    combine_verdicts,
    forced_fail_seed,
    ground_truth_facts,
    ground_truth_plan,
    feed_instrument_pre_navigation_scripts,
    require_feed_fixture,
    load_slides,
    matches_asset_keys,
    rects_overlap,
    score_armed,
    score_verdicts,
    convert_samples_to_authored,
    drive_and_sample,
    wait_for_destination_hash,
)
from live_host_probe import wait_for_settlement  # noqa: E402

FIXTURE = fixture("p2-recovery") / "html-adversarial"
SOAK_FIXTURE = fixture("p2-loop")
DEFAULT_HOME = Path.home() / "Library/Application Support/Obed-Edom/qualify-home"
USER_OBS_TREE = Path.home() / "Library/Application Support/obs-studio"
WS_CONFIG = "plugin_config/obs-websocket/config.json"
KEYER = "off"
READY_TIMEOUT_S = 40.0
QUIT_TIMEOUT_S = 20.0
RECORD_STOP_TIMEOUT_S = 10.0
RECORD_TAIL_FRAMES = 3

NATIVE_PHASES = ("slide1-native",)
NULL_PHASE = "slide1-paused"
UNMEASURED_MARK = "#808080"
LIMITS = {"nativeRepeatMax2x": 0.15, "decodableMin": 0.9, "nullRepeatMin": 0.95, "nativeRepeatMinPositive": 0.18,
          "g2RepeatMax25": 0.03, "g2RepeatMax30": 0.05, "distinctMin25": 24.0, "uploadsMin": 27.0, "reshownRepeatMax": 0.03, "staticMax": 4,
          "counterTol": 2, "movieAlphaMin": 250, "slotAlpha": 75, "slotAlphaTol": 3, "domTol": 3, "liveWaitS": 5.0,
          "mediaEndS": 44.0, "binaryRepeatMax": 0.01, "binaryReshownMax": 0.02, "binaryNativeTol": 0.01, "binaryPositiveMin": 0.05, "binaryDistinctFrac": 0.96, "liveRingMax": 20, "handbackRingPx": 200, "handbackMaxStepPerFrame": 3,
          "build1AfterMarkerMinS": 0.3}
G2_STATS = {"bandCount": 128, "innerRect": {"x": 4, "y": 4, "w": 952, "h": 268}}
EXPECTED_STATS = {"on": {**G2_STATS, "frameLen": 96, "occludedBands": 0, "opacityUnproven": [{"slot": 4, "reason": "size"}]},
                  "off": {**G2_STATS, "frameLen": 88, "occludedBands": 20, "opacityUnproven": []}}
UNENGAGED_STATS = {"opacityUnproven": [{"slot": 4, "reason": "rest-opacity"}]}
_FIRST_CEF = "first CEF measurement is this value; a mismatch is a finding to root-cause, not a threshold to retune"
EXPECTED_STATS_SOURCE = {
    "on": {**{k: "CEF, OD-2" for k in G2_STATS},
           "frameLen": f"headless hand-back plan §3.3 only (+8 calls for the two blended leaves), {_FIRST_CEF}",
           "occludedBands": f"headless Q0b only, {_FIRST_CEF}",
           "opacityUnproven": f"headless hand-back plan §3.3 only (Texture holds the destination, so `size` fails first), {_FIRST_CEF}"},
    "off": {**{k: "CEF, OD-2" for k in G2_STATS}, "frameLen": "CEF, OD-2", "occludedBands": "CEF, OD-2", "opacityUnproven": "CEF, OD-2"},
}
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
#: R2's enforced limit is max(tau, this). tau is calibrated on slide-1 frames over black only; live, a correct square
#: over the white counter reads up to 4.31 (blend rounding), while the smallest wrong-square signature is ~36 (alpha^2:
#: 0.208 * spread(S_off); a DOM + GL double: alpha * (1 - alpha) * spread(S_off) = 36.3; blank 51.5, opaque 124). 8.0 is
#: ~2x the worst good frame and ~4.5x under 36 (delta-alpha ~0.046 at spread 172).
MMO_R2_FLOOR = 8.0
#: Slide-1 badness above this voids MO-2 (INCONCLUSIVE): with tau = calibration + 1 it keeps tau <= MMO_R2_FLOOR, a
#: quarter of the smallest wrong-square signature, so a calibration can never lift the limit toward a pop.
MMO_CALIB_MAX = 7.0
#: MO-2 is INCONCLUSIVE when the smallest opacity error R2 can see (R2 limit / min channel spread of S_off) exceeds this:
#: half the smallest wrong-square delta-alpha (alpha * (1 - alpha) = 0.208), so R2 still splits good from wrong.
MMO_ALPHA_FLOOR_MAX = 0.1
MMO_SLIDE1_S = 6.0
MMO_LIVE_S = 4.0
MMO_CEF_GL = ("off", "auto")
DISSOLVE_ARMS = dissolve_probe.CEF.arms
_PLACEMENT_CONTROL_ARMS = tuple(dict.fromkeys(
    name for sides in dissolve_probe.CEF_PLACEMENT.controls().values() for side in sides for name in side
    if name in dissolve_probe.CEF_PLACEMENT.arms
))
PLACEMENT_ARMS = (*_PLACEMENT_CONTROL_ARMS,
                  *(name for name in dissolve_probe.CEF_PLACEMENT.arms if name not in _PLACEMENT_CONTROL_ARMS))
PLACEMENT_ANCHORS = ("opaque-off", "off", "m-snap-cef")
PLACEMENT_DEV_PROFILES = dissolve_probe.CEF_PLACEMENT_DEV_PROFILES
PLACEMENT_CONTROL_SESSIONS = (
    "startup-preview-on", "startup-offcanvas-on", "failed-preview-off", "failed-offcanvas-on",
    "probe-replay", "probe-transparent", "probe-frozen-video",
)
PLACEMENT_CONTROL_SPECS = {
    "startup-preview-on": ("preview", True, None),
    "startup-offcanvas-on": ("offcanvas", True, None),
    "failed-preview-off": ("preview", False, "capture-error"),
    "failed-offcanvas-on": ("offcanvas", True, "capture-error"),
    "probe-replay": ("preview", False, "replay"),
    "probe-transparent": ("preview", False, "transparent"),
    "probe-frozen-video": ("preview", False, "frozen-video"),
}
PLACEMENT_RECORDING_ESTIMATE_BYTES = 500 * 1024 * 1024
PLACEMENT_INJECTION_LEASE_MS = 15_000
PLACEMENT_INJECTION_RENEW_S = 2.5
PLACEMENT_INJECTION_MAX_INTERVAL_S = 3.0
DX2_TAU_MAX = 8.0
DX2_COMPLEMENT_MAX = 6.0
DX2_NO_DIP_MIN = 248.0
HB_OBS_MAX_PX = 0.25
HB_OBS_WHITE = 235
HB_OBS_SIZE = (1920, 1080)
PLACEMENT_GATE_NAMES = (
    "probe-cef", "probe-chrome-harness", "harness-classifier-control", "iso-obs-preview", "iso-obs-offcanvas",
    "program-wire-integrity", "alpha-integrity", "life-cal-preview", "life-cal-offcanvas", "persistence-worker", "W5",
)
PLACEMENT_ALPHA_JS = (
    "addEventListener('DOMContentLoaded',function(){var n=document.createElement('div');n.id='obed-placement-alpha';"
    "n.style.cssText='position:fixed;left:64px;top:64px;width:128px;height:128px;background:rgba(255,128,0,.5);"
    "z-index:2147483646;pointer-events:none';document.documentElement.appendChild(n)},{once:true})"
)
CALIBRATION_FAULT_TESTS = (
    "tests/test_managed_obs.py::test_calibration_transaction_preview_offcanvas_faults_and_fencing",
    "tests/test_managed_obs.py::test_crash_after_launch_before_record_is_quit_before_seeding",
    "tests/test_live_host.py::test_managed_probe_state_machine_renews_suppresses_and_stops",
)


def placement_profile(tier: str, dev_profile: str | None) -> dissolve_probe.Profile:
    if tier == "full":
        return dissolve_probe.CEF_PLACEMENT
    if tier == "dev" and dev_profile in PLACEMENT_DEV_PROFILES:
        return PLACEMENT_DEV_PROFILES[dev_profile]
    raise ValueError(f"unknown placement tier/profile {tier!r}/{dev_profile!r}")


def placement_scope(tier: str, dev_profile: str | None) -> dict[str, Any]:
    return {"tier": tier, **({"devProfile": dev_profile} if tier == "dev" else {})}


def placement_acquisition(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "launchId": ctx.get("placementLaunchId"), "rate": ctx.get("rate"), "take": ctx.get("take"),
        **placement_scope(ctx.get("tier", "full"), ctx.get("devProfile")),
    }


def placement_record_scope(metadata: dict[str, Any], scopes: list[tuple[Any, Any]]) -> tuple[
        str, str | None, dissolve_probe.Profile, bool]:
    explicit_tiers = {scope[0] for scope in scopes if scope[0] is not None}
    tier = "dev" if metadata.get("tier") == "dev" or "dev" in explicit_tiers else (
        metadata.get("tier") or (next(iter(explicit_tiers)) if len(explicit_tiers) == 1 else "full"))
    explicit_profiles = {scope[1] for scope in scopes if scope[1] is not None}
    dev_profile = metadata.get("devProfile") if tier == "dev" else None
    if tier == "dev" and dev_profile is None and len(explicit_profiles) == 1:
        dev_profile = next(iter(explicit_profiles))
    if tier == "dev" and dev_profile is None and not explicit_profiles:
        dev_profile = "renderer"
    profile = placement_profile(tier, dev_profile)
    legacy = tier == "full" and not explicit_tiers
    return tier, dev_profile, profile, legacy

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
HANDED_BACK_JS = ("(function(id){return Array.prototype.filter.call(document.querySelectorAll('video'), function(v){return v.__obedElId===id;})"
                  ".map(function(v){return {elId:id, loop:v.loop, isConnected:v.isConnected, facade:!!v.__obedFacadeFor, paused:v.paused,"
                  " t:v.currentTime};});})(%s)")
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


def calibration_gate(verdict: str, problems: list[str] | tuple[str, ...] = (), **detail: Any) -> dict[str, Any]:
    if verdict not in ("PASS", "FAIL", "INCONCLUSIVE", "REPORTED"):
        raise ValueError(f"unknown calibration gate verdict {verdict!r}")
    return {"verdict": verdict, "problems": list(problems), "detail": detail}


def _jsonable(value: Any) -> Any:
    if hasattr(value, "value") and isinstance(value.value, str):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {name: _jsonable(getattr(value, name)) for name in value.__dataclass_fields__}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    return value


class PlacementInjection:
    """A launch-bound leased placement grant used only by the qualification harness."""

    def __init__(
            self, host: LiveOutputHost, engine_identity: Callable[[], managed_obs.EngineIdentity | None],
            target_id: str, value: str, *, lease_ms: int = PLACEMENT_INJECTION_LEASE_MS,
            renew_s: float = PLACEMENT_INJECTION_RENEW_S,
            monotonic: Callable[[], float] = time.monotonic,
            unix_time: Callable[[], float] = time.time,
            ) -> None:
        if value not in ("snap", "frac"):
            raise ValueError(f"unsupported placement injection {value!r}")
        if not isinstance(lease_ms, int) or isinstance(lease_ms, bool) or not 0 < lease_ms <= PLACEMENT_INJECTION_LEASE_MS:
            raise ValueError(f"invalid placement injection lease {lease_ms!r}")
        if not 0 < renew_s <= PLACEMENT_INJECTION_MAX_INTERVAL_S:
            raise ValueError(f"invalid placement injection cadence {renew_s!r}")
        self.host = host
        self.engine_identity = engine_identity
        self.target_id = target_id
        self.value = value
        self.lease_ms = lease_ms
        self.renew_s = renew_s
        self.monotonic = monotonic
        self.unix_time = unix_time
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lock = threading.RLock()
        self.transport: Any = None
        self.connection_generation: int | None = None
        self.context: str | None = None
        self.engine: managed_obs.EngineIdentity | None = None
        self.fingerprint: tuple[str, float, int, int] | None = None
        self.deadline: float | None = None
        self.last_commit: float | None = None
        self.failure: str | None = None
        self.record: dict[str, Any] = {
            "schemaVersion": 1, "value": value, "leaseMs": lease_ms, "engine": None,
            "targetId": target_id, "uniqueContextId": None, "commits": [],
            "takeRead": None, "revoke": None,
        }

    def _evaluate(self, expression: str) -> Any:
        if self.transport is None or self.context is None:
            raise RuntimeError("placement injection binding is unavailable")
        return self.transport.evaluate_in(self.context, expression, deadline_s=1.0)

    def _current_binding(self) -> tuple[Any, int, str | None, Any, Any]:
        transport = self.host._require_transport()
        context = self.host._program_context()
        engine = self.engine_identity()
        fingerprint = self.host._probe_fingerprint_read(context) if context is not None else None
        return transport, self.host._connection_generation, context, engine, fingerprint

    def _binding_matches(self) -> bool | None:
        transport, generation, context, engine, fingerprint = self._current_binding()
        if (
            transport is not self.transport or generation != self.connection_generation
            or context != self.context or engine != self.engine
        ):
            return False
        if fingerprint is None:
            return None
        return fingerprint == self.fingerprint

    def _revoke_original(self) -> str:
        try:
            return str(dissolve_probe.commit_grant(self._evaluate, self.host._placement_token, "invalid")["read"])
        except Exception:
            return "unreadable"

    def _fail(self, reason: str) -> None:
        if self.failure is None:
            self.failure = reason
        self.stop_event.set()
        self._revoke_original()

    def _check(self, phase: str) -> bool:
        now = self.monotonic()
        try:
            binding_matches = self._binding_matches()
        except Exception:
            binding_matches = False
        if binding_matches is False:
            self._fail(f"placement injection binding changed{phase}")
        elif self.deadline is None or now >= self.deadline:
            self._fail(f"placement injection lease expired{phase}")
        elif self.last_commit is None or now - self.last_commit > PLACEMENT_INJECTION_MAX_INTERVAL_S:
            self._fail(f"placement injection renewal was late{phase}")
        return binding_matches is True and self.failure is None

    def _commit(self) -> bool | None:
        with self.lock:
            now = self.monotonic()
            if self.failure is not None:
                return False
            first = self.last_commit is None
            if first:
                try:
                    binding_matches = self._binding_matches()
                except Exception:
                    binding_matches = False
                if binding_matches is not True:
                    self._fail("placement injection binding changed" if binding_matches is False
                               else "placement injection binding could not be verified")
                    return False
            elif not self._check(""):
                return None if self.failure is None else False
            at = self.unix_time()
            try:
                if first:
                    result = dissolve_probe.commit_grant(
                        self._evaluate, self.host._placement_token, self.value, self.lease_ms)
                else:
                    read = self._evaluate(live_host._placement_renew_expr(
                        self.host._placement_token, self.value, self.lease_ms))
                    result = {"committed": read == self.value, "read": read}
            except Exception:
                result = {"committed": False, "read": "unreadable"}
            self.record["commits"].append({"at": at, "committed": result["committed"], "read": result["read"]})
            if result["committed"] is not True or result["read"] != self.value:
                self._fail("placement injection commit or readback failed")
                return False
            self.last_commit = now
            self.deadline = now + self.lease_ms / 1000.0
            return True

    def start(self, *, renewal: bool = True) -> None:
        with self.lock:
            transport, generation, context, engine, fingerprint = self._current_binding()
            if context is None or engine is None or fingerprint is None:
                raise RuntimeError("placement injection binding is incomplete")
            self.transport = transport
            self.connection_generation = generation
            self.context = context
            self.engine = engine
            self.fingerprint = fingerprint
            self.record["engine"] = _jsonable(engine)
            self.record["uniqueContextId"] = context
        if self._commit() is not True:
            raise RuntimeError(self.failure or "placement injection commit failed")
        if renewal:
            self.thread = threading.Thread(
                target=self._renew_loop, name="obed-qualification-placement-renewal", daemon=True)
            self.thread.start()

    def _renew_loop(self) -> None:
        while not self.stop_event.wait(max(0.0, (
                self.last_commit if self.last_commit is not None else self.monotonic()
                ) + self.renew_s - self.monotonic())):
            renewed = self._commit()
            if renewed is False:
                return
            if renewed is None and self.stop_event.wait(0.1):
                return

    def renew_once(self) -> bool:
        return self._commit() is True

    def take_read(self, value: Any) -> None:
        with self.lock:
            if not self._check(" at take") and self.failure is None:
                self._fail("placement injection binding could not be verified at take")
            if self.failure is None and value != self.value:
                self._fail("placement injection take readback failed")
            self.record["takeRead"] = {"at": self.unix_time(), "value": value}
            if self.failure is not None:
                raise RuntimeError(self.failure)

    def ensure_valid(self) -> None:
        with self.lock:
            if not self._check(" before final capture completed") and self.failure is None:
                self._fail("placement injection binding could not be verified before final capture completed")
            if self.failure is None:
                try:
                    read = self._evaluate(dissolve_probe.PLACEMENT_JS)
                except Exception:
                    read = "unreadable"
                if read != self.value:
                    self._fail("placement injection readback failed before final capture completed")
            if self.failure is not None:
                raise RuntimeError(self.failure)

    def stop_and_revoke(self) -> dict[str, Any]:
        self.stop_event.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join()
        with self.lock:
            self.record["revoke"] = {"at": self.unix_time(), "read": self._revoke_original()}
            if self.record["revoke"]["read"] != "invalid" and self.failure is None:
                self.failure = "placement injection revocation was not verified"
            return json.loads(json.dumps(self.record))


def _read_ref_json(ref: Any, run_dir: Path, *, collection: bool = False) -> Any:
    return json.loads(dissolve_probe._placement_ref_bytes(ref, run_dir, collection=collection))


def _snapshot(ref: Any, run_dir: Path,
              pure_scores: dict[tuple[Any, ...], Any] | None = None) -> managed_obs.CollectionSnapshot:
    _read_ref_json(ref, run_dir, collection=True)
    cache_key = ("collection-state", ref["sha256"])
    if pure_scores is not None and cache_key in pure_scores:
        return managed_obs.CollectionSnapshot(pure_scores[cache_key], ref["mtimeNs"], ref["savedByObs"])
    path = run_dir / ref["path"]
    snapshot = managed_obs.read_collection(path, saved_by_obs=ref["savedByObs"])
    if pure_scores is not None:
        pure_scores[cache_key] = snapshot.state
    return managed_obs.CollectionSnapshot(snapshot.state, ref["mtimeNs"], ref["savedByObs"])


def capture_collection(path: Path, run_dir: Path, name: str, *, saved_by_obs: bool) -> tuple[managed_obs.CollectionSnapshot, dict[str, Any]]:
    snapshot = managed_obs.read_collection(path, saved_by_obs=saved_by_obs)
    dest = run_dir / "placement" / "collections" / f"{name}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(path.read_bytes())
    return snapshot, dissolve_probe.placement_file_ref(dest, run_dir, mtime_ns=snapshot.mtime_ns, saved_by_obs=snapshot.saved_by_obs)


def collection_saved_by_obs(path: Path) -> bool:
    state = json.loads(path.read_text())
    modules = state.get("modules") if isinstance(state, dict) else None
    return (isinstance(modules, dict) and any(name in modules for name in ("auto-scene-switcher", "output-timer", "scripts-tool"))) or (
        isinstance(state, dict) and state.get("scaling_level") == -49)


def _program_check(check: managed_obs.ProgramCheck | None) -> tuple[bool | None, list[str], dict[str, Any]]:
    if check is None:
        return None, ["ProgramCheck missing"], {}
    problems = []
    if check.ok is not True:
        problems.append(f"ProgramCheck.ok is {check.ok!r}: {check.reason}")
    if check.visibility_events != 0:
        problems.append(f"visibility events {check.visibility_events} != 0")
    if check.baseline_frame_ms is None or check.baseline_frame_ms <= 0 or check.max_raf_gap_ms is None:
        problems.append("rAF baseline/gap unreadable")
    elif check.max_raf_gap_ms > 2 * check.baseline_frame_ms:
        problems.append(f"rAF max gap {check.max_raf_gap_ms} > two frame periods {2 * check.baseline_frame_ms}")
    if not check.media:
        problems.append("playing-media baseline missing")
    for media in check.media:
        required = {"id", "playing", "monotonic", "maxStallMs", "frameMs"}
        if not isinstance(media, dict) or required - set(media):
            problems.append(f"media row malformed: {media!r}")
            continue
        if media["playing"] is not True or media["monotonic"] is not True:
            problems.append(f"media {media['id']} was not playing monotonically")
        if not isinstance(media["frameMs"], (int, float)) or media["frameMs"] <= 0 or not isinstance(media["maxStallMs"], (int, float)):
            problems.append(f"media {media['id']} timing unreadable")
        elif media["maxStallMs"] > media["frameMs"]:
            problems.append(f"media {media['id']} stall {media['maxStallMs']} > frame {media['frameMs']}")
    return (None if check.ok is None or any("missing" in p or "unreadable" in p or "malformed" in p for p in problems)
            else not problems), problems, _jsonable(check)


def _telemetry(calibration: dict[str, Any], run_dir: Path) -> dict[str, Any] | None:
    integrity = calibration.get("integrity") if isinstance(calibration.get("integrity"), dict) else {}
    try:
        return _read_ref_json(integrity.get("telemetry"), run_dir) if integrity.get("telemetry") is not None else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _persistence_gates(calibration: dict[str, Any], run_dir: Path, *,
                       pure_scores: dict[tuple[Any, ...], Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    evidence = calibration.get("persistence")
    if not isinstance(evidence, dict):
        return calibration_gate("INCONCLUSIVE", ["persistence evidence missing"]), []
    required = ("baseline", "nullBefore", "nullAfter", "quit")
    if any(evidence.get(name) is None for name in required) or not isinstance(evidence.get("lastRemovalMtimeNs"), int):
        return calibration_gate("INCONCLUSIVE", ["persistence baseline/null/quit/last-removal evidence incomplete"]), []
    try:
        baseline = _snapshot(evidence["baseline"], run_dir, pure_scores)
        null_before = dissolve_probe._placement_ref_bytes(evidence["nullBefore"], run_dir, collection=True)
        null_after = dissolve_probe._placement_ref_bytes(evidence["nullAfter"], run_dir, collection=True)
        null_stable = null_before == null_after
        allowlist = managed_obs.STEP0_NULL_ALLOWLIST
        checks = []
        if evidence.get("cleanup") is not None:
            checks.append(managed_obs.check_persistence(baseline, _snapshot(evidence["cleanup"], run_dir, pure_scores), null_allowlist=allowlist,
                                                        phase="cleanup", last_removal_mtime_ns=evidence["lastRemovalMtimeNs"]))
        checks.append(managed_obs.check_persistence(baseline, _snapshot(evidence["quit"], run_dir, pure_scores), null_allowlist=allowlist,
                                                    phase="quit", last_removal_mtime_ns=evidence["lastRemovalMtimeNs"]))
    except (OSError, ValueError, KeyError, json.JSONDecodeError, NotImplementedError) as exc:
        return calibration_gate("INCONCLUSIVE", [f"persistence rescore failed: {type(exc).__name__}: {exc}"]), []
    authoritative = [row for row in checks if row.authoritative]
    problems = [] if null_stable else ["running collection changed without a transaction"]
    for row in authoritative:
        if row.ok is False:
            problems.append(f"{row.phase}: {', '.join(row.differences) or 'mismatch'}")
    quit_row = next((row for row in authoritative if row.phase == "quit"), None)
    verdict = "FAIL" if problems else "PASS" if quit_row is not None and quit_row.ok is True else "INCONCLUSIVE"
    return calibration_gate(
        verdict,
        problems or (["persistence check is non-authoritative"] if verdict == "INCONCLUSIVE" else []),
        allowlist=_jsonable(allowlist), checks=_jsonable(checks), nullStable=null_stable,
        coverage="live subset", unitTests=list(CALIBRATION_FAULT_TESTS),
    ), [_jsonable(c) for c in checks]


def _cached_pure_score(cache: dict[tuple[Any, ...], Any] | None, key: tuple[Any, ...],
                       compute: Callable[[], Any]) -> Any:
    if cache is None:
        return compute()
    if key not in cache:
        cache[key] = compute()
    return cache[key]


def score_placement_calibration(calibration: Any, run_dir: Path, *,
                                live_probe_controls: dict[str, Any] | None = None,
                                pure_scores: dict[tuple[Any, ...], Any] | None = None) -> dict[str, Any]:
    """Keynote/OBS-free §5 rescore. The classifier and persistence decisions call the product APIs used live."""
    started = time.monotonic()

    def finished(value: dict[str, Any]) -> dict[str, Any]:
        value["timingS"] = {**value.get("timingS", {}), "total": round(time.monotonic() - started, 6)}
        return value

    schema = dissolve_probe.placement_schema_problems(calibration, run_dir)
    if schema:
        gates = {name: calibration_gate("INCONCLUSIVE", schema) for name in PLACEMENT_GATE_NAMES}
        return finished({"overall": "INCONCLUSIVE", "classification": None, "gates": gates, "problems": schema})
    try:
        decoded = dissolve_probe.deserialize_placement_calibration(calibration, run_dir)
    except (TypeError, ValueError, KeyError) as exc:
        problems = [f"placement decode failed: {type(exc).__name__}: {exc}"]
        gates = {name: calibration_gate("INCONCLUSIVE", problems) for name in PLACEMENT_GATE_NAMES}
        return finished({"overall": "INCONCLUSIVE", "classification": None, "gates": gates, "problems": problems})

    gates: dict[str, Any] = {}
    classified = None
    classify_problems = []
    classification_started = time.monotonic()
    if decoded.get("input") is None:
        classify_problems.append("ClassifierInput missing")
    else:
        try:
            input_key = hashlib.sha256(json.dumps(
                calibration.get("input"), sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest()
            classified = _cached_pure_score(
                pure_scores, ("classification", input_key),
                lambda: placement_probe.classify_probe(decoded["input"]))
        except (TypeError, ValueError, NotImplementedError) as exc:
            classify_problems.append(f"classifier failed: {type(exc).__name__}: {exc}")
    recorded = decoded.get("classification")
    if classified is not None and recorded is not None and _jsonable(classified) != _jsonable(recorded):
        classify_problems.append("recorded classification differs from offline classifier")
    classification_s = time.monotonic() - classification_started
    backend = calibration["backend"]
    telemetry = _telemetry(calibration, run_dir)
    classifier_controls_s = 0.0
    if backend == "cef":
        controls_started = time.monotonic()
        controls = (_cached_pure_score(
            pure_scores, ("classifier-controls", input_key, "frac", False),
            lambda: classifier_controls(decoded["input"], classified, placement_probe.ProbeVerdict.FRAC))
            if decoded.get("input") is not None and classified is not None else None)
        classifier_controls_s = time.monotonic() - controls_started
        if not isinstance(controls, dict):
            classify_problems.append("classifier controls missing")
        elif controls.get("passed") is not True:
            classify_problems.extend(list(controls.get("problems") or ["classifier controls failed"]))
        current_probe_controls = live_probe_controls or (telemetry or {}).get("liveProbeControls")
        if not isinstance(current_probe_controls, dict):
            classify_problems.append("live probe controls missing")
        else:
            for name in ("replay", "transparent", "frozen-video"):
                if (current_probe_controls.get(name) or {}).get("verdict") != "PASS":
                    classify_problems.append(f"live probe control {name} did not reject cleanly")
        ok = (classified is not None and classified.verdict == placement_probe.ProbeVerdict.FRAC
              and classified.tone_map == placement_probe.ToneMap.GPU_ANALYTIC and classified.grant_eligible)
        verdict = "INCONCLUSIVE" if classify_problems or classified is None or classified.verdict == placement_probe.ProbeVerdict.UNKNOWN else "PASS" if ok else "FAIL"
        gates["probe-cef"] = calibration_gate(verdict, classify_problems, candidate=calibration.get("request"), result=_jsonable(classified))
        gates["probe-chrome-harness"] = calibration_gate("REPORTED", [], result=None)
        gates["harness-classifier-control"] = calibration_gate("REPORTED", [], result=None)
    else:
        gpu = (telemetry or {}).get("chromeGpu")
        software = gpu is False
        ok = (classified is not None and
              ((gpu is True and classified.verdict == placement_probe.ProbeVerdict.SNAP
                and classified.tone_map == placement_probe.ToneMap.GPU_ANALYTIC and classified.grant_eligible)
               or (software and not classified.grant_eligible and
                   ((classified.verdict == placement_probe.ProbeVerdict.SNAP
                     and classified.tone_map == placement_probe.ToneMap.IDENTITY and classified.reason == "software-map")
                    or (classified.verdict == placement_probe.ProbeVerdict.UNKNOWN
                        and classified.tone_map is None and classified.reason == "ambiguous")))))
        if not isinstance(gpu, bool):
            classify_problems.append("Chrome GPU/software launch identity missing")
        verdict = "INCONCLUSIVE" if classify_problems or classified is None else "PASS" if ok else "FAIL"
        gates["probe-chrome-harness"] = calibration_gate(verdict, classify_problems, result=_jsonable(classified))
        controls_started = time.monotonic()
        controls = (_cached_pure_score(
            pure_scores, ("classifier-controls", input_key, "snap", software),
            lambda: classifier_controls(
                decoded["input"], classified, placement_probe.ProbeVerdict.SNAP, software=software))
            if decoded.get("input") is not None and classified is not None else None)
        classifier_controls_s = time.monotonic() - controls_started
        gates["harness-classifier-control"] = calibration_gate(
            "INCONCLUSIVE" if not isinstance(controls, dict) else "PASS" if controls.get("passed") is True else "FAIL",
            ["classifier controls missing"] if not isinstance(controls, dict) else list(controls.get("problems") or []), controls=controls)
        gates["probe-cef"] = calibration_gate("REPORTED", [], result=None)

    transaction = decoded.get("transaction")
    tx_problems = []
    tx_unknown = transaction is None
    if transaction is not None:
        if not transaction.isolation_ok:
            tx_problems.append("transaction isolation failed")
        if not transaction.cleanup_verified:
            tx_problems.append("transaction cleanup was not verified")
        if not transaction.restored:
            tx_problems.append("transaction state was not restored")
        tx_problems += list(transaction.errors)
    program_ok, program_problems, program_detail = _program_check(transaction.program if transaction else None)
    tx_problems += program_problems
    ownership_message = "Calibration engine ownership could not be verified."
    ownership_aborted = (transaction is not None and transaction.isolation_ok and program_ok is not False
                         and decoded.get("input") is None and bool(transaction.errors)
                         and all(error.endswith(ownership_message) for error in transaction.errors))
    placement = calibration.get("placement")
    live_controls = telemetry.get("liveControls") if isinstance(telemetry, dict) else None
    isolation_controls = live_controls.get("isolation") if isinstance(live_controls, dict) else None
    isolation_control_problems = []
    if not isinstance(isolation_controls, dict):
        isolation_control_problems.append("live isolation controls missing")
    else:
        for control, want in (("null", "PASS"), ("startup", "PASS"), ("priorStudioStates", "PASS"),
                              ("visibleOrigin", "FAIL"), ("behindTransparentProgram", "FAIL"), ("failedOnAir", "PASS")):
            if (isolation_controls.get(control) or {}).get("verdict") != want:
                isolation_control_problems.append(f"isolation control {control} did not {want}")
    for name in ("preview", "offcanvas"):
        if placement != name:
            gates[f"iso-obs-{name}"] = calibration_gate("REPORTED", [], placement=placement)
            continue
        verdict = ("INCONCLUSIVE" if tx_unknown or ownership_aborted
                   or program_ok is None or isolation_control_problems else
                   "FAIL" if tx_problems else "PASS")
        gates[f"iso-obs-{name}"] = calibration_gate(
            verdict, tx_problems + isolation_control_problems, transaction=calibration.get("transaction"),
            program=program_detail, controls=isolation_controls, coverage="live subset", unitTests=list(CALIBRATION_FAULT_TESTS),
        )

    guard = telemetry.get("programGuard") if isinstance(telemetry, dict) else None
    guard_problems = []
    if not isinstance(guard, dict) or not all(k in guard for k in ("null", "candidate", "toggle")):
        gates["program-wire-integrity"] = calibration_gate("INCONCLUSIVE", ["null/candidate/Program-toggle telemetry missing"])
    else:
        null_ok = guard["null"].get("ok") is True
        candidate_ok = guard["candidate"].get("ok") is True
        toggle_failed = guard["toggle"].get("ok") is False
        control_failed = False
        if not null_ok:
            guard_problems.append("no-transaction null did not pass")
            control_failed = True
        if not candidate_ok:
            guard_problems.append("candidate disturbed Program")
        if not toggle_failed:
            guard_problems.append("Program-toggle positive control did not fail")
            control_failed = True
        gates["program-wire-integrity"] = calibration_gate(
            "INCONCLUSIVE" if control_failed else "FAIL" if not candidate_ok else "PASS", guard_problems, **guard)

    recording = telemetry.get("programRecording") if isinstance(telemetry, dict) else None
    recording_error = telemetry.get("recordingError") if isinstance(telemetry, dict) else None
    recording_stop = telemetry.get("recordingStop") if isinstance(telemetry, dict) else None
    if not isinstance(recording, dict):
        problems = ["continuous program recording analysis missing"]
        if recording_error:
            problems.append(f"recording stop verification failed: {recording_error}")
        recording_gate = calibration_gate("INCONCLUSIVE", problems)
    else:
        required = ("lossless", "continuous", "decodedFrames", "identicalFrames", "frameCountComplete",
                    "skippedFramesZero", "statsBefore", "statsAfter", "startedAt", "stoppedAt",
                    "audioPresent", "audioSilent")
        missing = [k for k in required if k not in recording]
        transaction_values = [recording.get(name) for name in ("transactionStartedS", "transactionFinishedS", "fps")]
        if (not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                    for value in transaction_values)
                or transaction_values[1] < transaction_values[0] or transaction_values[2] <= 0):
            missing.append("transaction frame bound")
            frame_count_complete = False
        else:
            transaction_minimum = max(0, math.ceil((transaction_values[1] - transaction_values[0]) * transaction_values[2]))
            frame_count_complete = (recording.get("minimumFrames") == transaction_minimum
                                    and isinstance(recording.get("decodedFrames"), int)
                                    and recording["decodedFrames"] >= transaction_minimum
                                    and recording.get("frameCountComplete") is True)
        coverage_values = [recording.get(name) for name in (
            "startedAt", "stoppedAt", "transactionStartedS", "transactionFinishedS")]
        continuous = (all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                          for value in coverage_values)
                      and coverage_values[0] <= coverage_values[2] <= coverage_values[3] <= coverage_values[1]
                      and recording.get("continuous") is True)
        stats_before = recording.get("statsBefore")
        stats_after = recording.get("statsAfter")
        skipped = {}
        for name in ("outputSkippedFrames", "renderSkippedFrames"):
            before = stats_before.get(name) if isinstance(stats_before, dict) else None
            after = stats_after.get(name) if isinstance(stats_after, dict) else None
            if isinstance(before, int) and not isinstance(before, bool) and isinstance(after, int) and not isinstance(after, bool):
                skipped[name] = after - before
        skipped_zero = (len(skipped) == 2 and all(value == 0 for value in skipped.values())
                        and recording.get("skippedFrames") == skipped and recording.get("skippedFramesZero") is True)
        recording_ref = (calibration.get("integrity") or {}).get("recording")
        if isinstance(recording_ref, dict) and recording_ref.get("retained") is False:
            try:
                dissolve_probe._placement_ref_bytes(recording.get("framemd5"), run_dir)
            except (OSError, TypeError, ValueError) as exc:
                missing.append(f"retained framemd5 ({type(exc).__name__}: {exc})")
        if recording_error:
            missing.append(f"recording stop verification ({recording_error})")
        if isinstance(recording_stop, dict) and not all(recording_stop.get(name) is True for name in (
                "postRestorationFramesComplete", "inactive", "readable")):
            missing.append("recording stop predicates")
        incomplete = (missing or recording.get("lossless") is not True or not continuous
                      or not frame_count_complete or recording.get("audioPresent") is not True or not skipped_zero
                      or not isinstance(recording.get("decodedFrames"), int) or recording.get("decodedFrames", 0) <= 0)
        changed = (not incomplete and (recording.get("identicalFrames") != recording.get("decodedFrames")
                                      or recording.get("audioSilent") is not True))
        recording_gate = calibration_gate(
            "INCONCLUSIVE" if incomplete else "FAIL" if changed else "PASS",
            [f"recording evidence missing {k}" for k in missing]
            + ([] if continuous else ["recording does not bracket the transaction"])
            + ([] if frame_count_complete else ["recording frame count does not cover the transaction interval"])
            + ([] if skipped_zero else ["OBS skipped-frame evidence is missing, changed, or nonzero"])
            + ([] if recording.get("audioPresent") is True else ["recording audio stream is missing"]),
            recording=recording,
        )
    recording_controls = telemetry.get("recordingControls") if isinstance(telemetry, dict) else None
    flash = recording_controls.get("flash") if isinstance(recording_controls, dict) else None
    audio = recording_controls.get("audio") if isinstance(recording_controls, dict) else None
    control_problems = []
    if not isinstance(flash, dict) or flash.get("verdict") != "FAIL":
        control_problems.append("live one-frame flash control did not FAIL")
    elif isinstance(flash.get("recording"), dict) and flash["recording"].get("retained") is False:
        try:
            dissolve_probe._placement_ref_bytes(flash.get("framemd5"), run_dir)
        except (OSError, TypeError, ValueError) as exc:
            control_problems.append(f"flash framemd5 missing after recording retirement: {type(exc).__name__}: {exc}")
    if not isinstance(audio, dict) or audio.get("verdict") not in ("FAIL", "REPORTED"):
        control_problems.append("live audio control missing or invalid")
    elif audio.get("verdict") == "REPORTED" and not audio.get("reason"):
        control_problems.append("reported audio control has no reason")
    control_gate = calibration_gate("INCONCLUSIVE" if control_problems else "PASS", control_problems,
                                    flash=flash, audio=audio)
    gates["program-wire-integrity"] = calibration_gate(
        "FAIL" if "FAIL" in (gates["program-wire-integrity"]["verdict"], recording_gate["verdict"], control_gate["verdict"]) else
        "INCONCLUSIVE" if "INCONCLUSIVE" in (gates["program-wire-integrity"]["verdict"], recording_gate["verdict"],
                                               control_gate["verdict"]) else "PASS",
        gates["program-wire-integrity"]["problems"] + recording_gate["problems"] + control_gate["problems"],
        guard=gates["program-wire-integrity"]["detail"], recording=recording_gate["detail"], controls=control_gate["detail"])

    alpha = telemetry.get("alpha") if isinstance(telemetry, dict) else None
    if not isinstance(alpha, dict):
        gates["alpha-integrity"] = calibration_gate("INCONCLUSIVE", ["sampled RGBA analysis missing"])
    else:
        required = ("transparent", "halfTransparent", "sampleCount", "allChannelsEqual", "allPhasesCovered")
        missing = [k for k in required if k not in alpha]
        alpha_controls = live_controls.get("alpha") if isinstance(live_controls, dict) else None
        control_problems = []
        if not isinstance(alpha_controls, dict):
            control_problems.append("live alpha controls missing")
        else:
            for control, want in (("null", "PASS"), ("behindProgramLeak", "FAIL"), ("alphaOnly", "FAIL")):
                if (alpha_controls.get(control) or {}).get("verdict") != want:
                    control_problems.append(f"alpha control {control} did not {want}")
        product_timing = (telemetry or {}).get("samplingMode") == "product-timing"
        ok = not missing and alpha["transparent"] and alpha["halfTransparent"] and alpha["sampleCount"] > 0 and alpha["allChannelsEqual"] and alpha["allPhasesCovered"]
        verdict = ("REPORTED" if product_timing else "INCONCLUSIVE" if missing or control_problems else "PASS" if ok else "FAIL")
        gates["alpha-integrity"] = calibration_gate(
            verdict, [f"alpha evidence missing {k}" for k in missing] + control_problems,
            alpha=alpha, controls=alpha_controls, samplingMode=(telemetry or {}).get("samplingMode"),
        )

    events = calibration.get("events")
    placement_events = [event for event in events if isinstance(event, dict) and event.get("event") == "placement"] \
        if isinstance(events, list) else []
    states = [((event.get("placement") or {}).get("state")) for event in placement_events]
    for name in ("preview", "offcanvas"):
        if placement != name:
            gates[f"life-cal-{name}"] = calibration_gate("REPORTED", [], placement=placement)
            continue
        probing = next((index for index, state in enumerate(states) if state == "probing"), None)
        valid = next((index for index, state in enumerate(states) if state == "valid" and probing is not None and index > probing), None)
        final = placement_events[valid].get("placement") if valid is not None else {}
        drive = (telemetry or {}).get("drivePlacement") or final
        missing = []
        if probing is None or valid is None:
            missing.append(f"placement event sequence lacks ordered probing→valid: {states}")
        if classified is None or drive.get("grant") != classified.verdict.value or drive.get("method") != "probe":
            missing.append("drive-time placement does not match the probe classification")
        if classified is None or ((drive.get("tone") or {}).get("observed") !=
                                  (classified.tone_map.value if classified.tone_map else None)):
            missing.append("drive-time tone observation does not match the probe classification")
        gates[f"life-cal-{name}"] = calibration_gate(
            "PASS" if not missing else "INCONCLUSIVE", missing, states=states, final=final, drive=drive,
            coverage="live subset", unitTests=list(CALIBRATION_FAULT_TESTS),
        )

    persistence_started = time.monotonic()
    gates["persistence-worker"], persistence_checks = _persistence_gates(
        calibration, run_dir, pure_scores=pure_scores)
    persistence_s = time.monotonic() - persistence_started
    tone_rows = telemetry.get("toneRows") if isinstance(telemetry, dict) else None
    if not isinstance(tone_rows, dict):
        gates["W5"] = calibration_gate("INCONCLUSIVE", ["W5 tone rows missing"])
    else:
        problems = list(tone_rows.get("problems") or [])
        complete = (tone_rows.get("complete") is True and tone_rows.get("applied") == "identity"
                    and not tone_rows.get("missingRows"))
        gates["W5"] = calibration_gate("REPORTED" if complete and not problems else "INCONCLUSIVE", problems or ([] if complete else ["W5 rows incomplete"]), rows=tone_rows)

    if backend == "chrome-harness":
        for name in ("iso-obs-preview", "iso-obs-offcanvas", "program-wire-integrity", "alpha-integrity",
                     "life-cal-preview", "life-cal-offcanvas", "persistence-worker"):
            gates[name] = calibration_gate("REPORTED", [], backend=backend)

    blocking = [g["verdict"] for name, g in gates.items() if name != "W5" and g["verdict"] != "REPORTED"]
    overall = "FAIL" if "FAIL" in blocking else "INCONCLUSIVE" if "INCONCLUSIVE" in blocking or not blocking else "PASS"
    return finished({"overall": overall, "classification": _jsonable(classified), "gates": gates,
                     "persistenceChecks": persistence_checks, "problems": classify_problems,
                     "timingS": {"classification": round(classification_s, 6),
                                 "classifierControls": round(classifier_controls_s, 6),
                                 "persistence": round(persistence_s, 6)}})


def placement_evidence_mode(records: list[tuple[str, dict[str, Any]]],
                            profile: dissolve_probe.Profile) -> tuple[str, list[str]]:
    modes = []
    for name, record in records:
        if name not in profile.arms:
            continue
        calibration = isinstance(record.get("placementCalibration"), dict)
        injection = isinstance(record.get("placementInjection"), dict)
        if calibration or injection:
            modes.append((name, "both" if calibration and injection else
                          "calibration" if calibration else "injection"))
    if modes and all(mode == "calibration" for _name, mode in modes):
        return "legacy", []
    mismatches = list(dict.fromkeys(
        name for name, mode in modes
        if mode != ("calibration" if name in PLACEMENT_ANCHORS else "injection")))
    if not mismatches:
        return "anchors+injection", []
    return "mixed", [f"mixed placement evidence modes: {mismatches}"]


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def placement_anchor_problems(
        anchor_records: dict[str, dict[str, Any]], anchor_scores: dict[str, dict[str, Any]],
        ) -> tuple[list[str], list[dict[str, Any]], dict[str, str]]:
    problems = []
    engines = []
    contexts = {}
    for name in PLACEMENT_ANCHORS:
        record = anchor_records.get(name)
        calibration = record.get("placementCalibration") if isinstance(record, dict) else None
        score = anchor_scores.get(name)
        if not isinstance(calibration, dict) or not isinstance(score, dict):
            problems.append(f"anchor {name} calibration is missing")
            continue
        engine = calibration.get("engine")
        if not isinstance(engine, dict):
            problems.append(f"anchor {name} engine is missing")
        else:
            engines.append(engine)
        request = calibration.get("request")
        context = request.get("program_context_id") if isinstance(request, dict) else None
        if not isinstance(context, str) or not context:
            problems.append(f"anchor {name} unique context is missing")
        else:
            contexts[name] = context
        classification = score.get("classification")
        if score.get("overall") != "PASS":
            problems.append(f"anchor {name} product gates did not pass")
        if not isinstance(classification, dict) or classification.get("verdict") != "frac":
            problems.append(f"anchor {name} did not classify frac")
    return problems, engines, contexts


def placement_launch_evidence(
        records: list[tuple[str, Path, dict[str, Any]]], profile: dissolve_probe.Profile, *,
        live_probe_controls: dict[str, Any] | None,
        product_scores: dict[Path, dict[str, Any]] | None = None,
        pure_scores: dict[tuple[Any, ...], Any] | None = None,
        ) -> tuple[str, list[str], list[str], list[dict[str, Any]], dict[Path, dict[str, Any]]]:
    evidence_mode, mode_problems = placement_evidence_mode(
        [(name, record) for name, _path, record in records], profile)
    anchor_scores = {}
    anchor_records = {}
    scores_by_path = {}
    for name, path, record in records:
        if name not in PLACEMENT_ANCHORS:
            continue
        anchor_records[name] = record
        calibration = record.get("placementCalibration")
        if not isinstance(calibration, dict):
            continue
        rescored = (product_scores or {}).get(path)
        if rescored is None:
            rescored = score_placement_calibration(
                calibration, path.parent, live_probe_controls=live_probe_controls, pure_scores=pure_scores)
            if product_scores is not None:
                product_scores[path] = rescored
        anchor_scores[name] = rescored
        scores_by_path[path] = rescored
    launch_problems, anchor_engines, anchor_contexts = placement_anchor_problems(
        anchor_records, anchor_scores)
    contexts: dict[str, list[str]] = {}
    for name, context in anchor_contexts.items():
        contexts.setdefault(context, []).append(name)
    for name, path, record in records:
        if name in PLACEMENT_ANCHORS:
            continue
        injection = record.get("placementInjection")
        context = injection.get("uniqueContextId") if isinstance(injection, dict) else None
        if isinstance(context, str) and context:
            contexts.setdefault(context, []).append(f"{name} ({path.parent.name})")
    launch_problems.extend(
        f"placement unique context is shared by {', '.join(names)}"
        for names in contexts.values() if len(names) > 1)
    return evidence_mode, mode_problems, launch_problems, anchor_engines, scores_by_path


def score_placement_injection(
        injection: Any, record: dict[str, Any], arm: dissolve_probe.Arm,
        profile: dissolve_probe.Profile, anchor_problems: list[str], anchor_engines: list[dict[str, Any]],
        ) -> dict[str, Any]:
    problems = list(anchor_problems)
    required = {
        "schemaVersion", "value", "leaseMs", "engine", "targetId", "uniqueContextId",
        "commits", "takeRead", "revoke",
    }
    if not isinstance(injection, dict):
        problems.append("placementInjection is missing")
        return {"overall": "INCONCLUSIVE", "gates": {
            "placement-injection": calibration_gate("INCONCLUSIVE", problems)}, "problems": problems}
    missing = sorted(required - set(injection))
    unsupported = sorted(set(injection) - required)
    problems.extend(f"placementInjection missing {name}" for name in missing)
    problems.extend(f"placementInjection has unsupported {name}" for name in unsupported)
    expected = arm.placement_value or profile.placement
    value = injection.get("value")
    if injection.get("schemaVersion") != 1:
        problems.append("placementInjection schemaVersion is not 1")
    if value != expected or value not in ("snap", "frac"):
        problems.append(f"placementInjection value {value!r} != {expected!r}")
    lease_ms = injection.get("leaseMs")
    if (not isinstance(lease_ms, int) or isinstance(lease_ms, bool)
            or not 0 < lease_ms <= PLACEMENT_INJECTION_LEASE_MS):
        problems.append("placementInjection leaseMs is invalid")
        lease_s = None
    else:
        lease_s = lease_ms / 1000.0
    if not isinstance(injection.get("targetId"), str) or not injection.get("targetId"):
        problems.append("placementInjection targetId is invalid")
    if not isinstance(injection.get("uniqueContextId"), str) or not injection.get("uniqueContextId"):
        problems.append("placementInjection uniqueContextId is invalid")
    engine = injection.get("engine")
    if len(anchor_engines) != len(PLACEMENT_ANCHORS) or any(engine != anchor for anchor in anchor_engines):
        problems.append("placementInjection engine does not match every anchor")
    commits = injection.get("commits")
    commit_times = []
    if not isinstance(commits, list) or not commits:
        problems.append("placementInjection commits are missing")
    else:
        previous = None
        for index, commit in enumerate(commits, 1):
            if not isinstance(commit, dict) or set(commit) != {"at", "committed", "read"}:
                problems.append(f"placementInjection commit {index} is malformed")
                continue
            at = commit.get("at")
            if not _finite_number(at):
                problems.append(f"placementInjection commit {index} time is invalid")
                continue
            commit_times.append(float(at))
            if commit.get("committed") is not True or commit.get("read") != value:
                problems.append(f"placementInjection commit {index} failed or read back a different value")
            if previous is not None:
                gap = float(at) - previous
                if gap < 0 or gap > PLACEMENT_INJECTION_MAX_INTERVAL_S:
                    problems.append(f"placementInjection renewal {index} was late")
                if lease_s is not None and gap >= lease_s:
                    problems.append(f"placementInjection lease expired before renewal {index}")
            previous = float(at)
    take = injection.get("takeRead")
    take_at = None
    if not isinstance(take, dict) or set(take) != {"at", "value"} or not _finite_number(take.get("at")):
        problems.append("placementInjection takeRead is malformed")
    else:
        take_at = float(take["at"])
        if take.get("value") != value or record.get("placement") != take.get("value"):
            problems.append("placementInjection takeRead does not match the pre-advance placement read")
        preceding = [at for at in commit_times if at <= take_at]
        if not preceding:
            problems.append("placementInjection takeRead is outside the committed lease")
        elif take_at - preceding[-1] > PLACEMENT_INJECTION_MAX_INTERVAL_S:
            problems.append("placementInjection renewal was missing at take")
        if preceding and lease_s is not None and take_at >= preceding[-1] + lease_s:
            problems.append("placementInjection lease expired before takeRead")
    revoke = injection.get("revoke")
    if not isinstance(revoke, dict) or set(revoke) != {"at", "read"} or not _finite_number(revoke.get("at")):
        problems.append("placementInjection revoke is malformed")
    else:
        if revoke.get("read") != "invalid":
            problems.append("placementInjection revocation was not verified")
        if take_at is not None and float(revoke["at"]) < take_at:
            problems.append("placementInjection was revoked before takeRead")
        if commit_times and float(revoke["at"]) - commit_times[-1] > PLACEMENT_INJECTION_MAX_INTERVAL_S:
            problems.append("placementInjection renewal did not continue through final capture")
        if commit_times and lease_s is not None and float(revoke["at"]) >= commit_times[-1] + lease_s:
            problems.append("placementInjection lease expired before revocation")
    if record.get("integrityFailure") is not None:
        problems.append(f"placement injection integrity failure: {record['integrityFailure']}")
    verdict = "PASS" if not problems else "INCONCLUSIVE"
    return {"overall": verdict, "gates": {
        "placement-injection": calibration_gate(verdict, problems)}, "problems": problems}


def write_placement_json(run_dir: Path, name: str, value: Any) -> dict[str, Any]:
    path = run_dir / "placement" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1))
    return dissolve_probe.placement_file_ref(path, run_dir)


def placement_player_digests(stock_sha256: str) -> dict[str, str]:
    pins = live_runtime.SUPPORTED_PLAYERS.get(stock_sha256)
    if pins is None:
        raise ValueError(f"unsupported stock player {stock_sha256}")
    return {"stockSha256": stock_sha256, "liveSha256": pins[0], "renderingSha256": pins[2]}


def placement_record(*, backend: str, placement: str | None, obs_version: str | None,
                     engine: managed_obs.EngineIdentity | None, request: managed_obs.CalibrationRequest | None,
                     evidence: placement_probe.ClassifierInput | None, classification: placement_probe.ProbeResult | None,
                     transaction: managed_obs.CalibrationResult | None, events: list[dict[str, Any]],
                     persistence: dict[str, Any] | None, integrity: dict[str, Any], stock_sha256: str,
                     gates: dict[str, Any] | None = None) -> dict[str, Any]:
    assets = placement_probe.load_probe_assets()
    if backend not in dissolve_probe.PLACEMENT_BACKENDS:
        raise ValueError(f"unsupported placement backend {backend!r}")
    return {
        "schemaVersion": dissolve_probe.PLACEMENT_SCHEMA_VERSION,
        "backend": backend,
        "placement": placement,
        "obsVersion": obs_version,
        "engine": engine,
        "request": request,
        "assets": {"manifestSha256": assets.manifest_sha256, "patternSha256": assets.pattern.sha256,
                   "motionSha256": assets.motion.sha256},
        "player": placement_player_digests(stock_sha256),
        "input": evidence,
        "classification": classification,
        "transaction": transaction,
        "events": events,
        "persistence": persistence,
        "integrity": integrity,
        "gates": gates or {},
    }


def _png_array(data: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(data)).convert("RGBA")).copy()


def _png_bytes(image: np.ndarray) -> bytes:
    output = io.BytesIO()
    Image.fromarray(image, "RGBA").save(output, format="PNG")
    return output.getvalue()


def _swap_candidate_rules(evidence: placement_probe.ClassifierInput) -> placement_probe.ClassifierInput:
    captures = []
    geometries = {geometry.pose: geometry for geometry in evidence.poses}
    for capture in evidence.captures:
        geometry = geometries[capture.pose]
        image = _png_array(capture.png)
        x, y, width, height = geometry.box
        snap = image[y + geometry.snap_dy:y + geometry.snap_dy + height, x:x + width].copy()
        frac = image[y + geometry.frac_dy:y + geometry.frac_dy + height, x:x + width].copy()
        image[y + geometry.snap_dy:y + geometry.snap_dy + height, x:x + width] = frac
        image[y + geometry.frac_dy:y + geometry.frac_dy + height, x:x + width] = snap
        captures.append(replace(capture, png=_png_bytes(image)))
    return replace(evidence, captures=tuple(captures))


def _frozen_motion(evidence: placement_probe.ClassifierInput) -> placement_probe.ClassifierInput:
    freshness = list(evidence.freshness)
    geometry = evidence.poses[0]
    x, y, width, height = geometry.box
    first = _png_array(freshness[0].png)
    second = _png_array(freshness[1].png)
    second[y:y + height, x:x + width] = first[y:y + height, x:x + width]
    freshness[1] = replace(freshness[1], png=_png_bytes(second))
    return replace(evidence, freshness=tuple(freshness))


def classifier_controls(evidence: placement_probe.ClassifierInput, result: placement_probe.ProbeResult,
                        expected: placement_probe.ProbeVerdict, *, software: bool = False) -> dict[str, Any]:
    replay = list(evidence.freshness)
    replay[1] = replace(replay[1], png=replay[0].png)
    transparent = np.zeros((1080, 1920, 4), np.uint8)
    cold = list(evidence.freshness)
    cold[0] = replace(cold[0], png=_png_bytes(transparent))
    controls = {
        "wrongRule": placement_probe.classify_probe(_swap_candidate_rules(evidence)),
        "replay": placement_probe.classify_probe(replace(evidence, freshness=tuple(replay))),
        "dpr": placement_probe.classify_probe(replace(evidence, spec=replace(evidence.spec, dpr=1.5),
                                                        identity=replace(evidence.identity, dpr=1.5))),
        "undecodable": placement_probe.classify_probe(
            replace(evidence, captures=(replace(evidence.captures[0], png=b"not-a-png"), *evidence.captures[1:]))),
        "frozenMotion": placement_probe.classify_probe(_frozen_motion(evidence)),
        "coldDormant": placement_probe.classify_probe(replace(evidence, freshness=tuple(cold))),
        "notDecoded": placement_probe.classify_probe(replace(evidence, ready_state=1)),
        "wrongContext": placement_probe.classify_probe(
            replace(evidence, captures=(replace(evidence.captures[0], identity=replace(evidence.identity, context_id="prior-run")),
                                        *evidence.captures[1:]))),
    }
    wrong = placement_probe.ProbeVerdict.SNAP if expected == placement_probe.ProbeVerdict.FRAC else placement_probe.ProbeVerdict.FRAC
    expected_reason = "classified" if result.grant_eligible else "software-map"
    required = {
        "wrongRule": (wrong, "classified" if result.grant_eligible else "software-map"),
        "replay": (placement_probe.ProbeVerdict.UNKNOWN, "stale-capture"),
        "dpr": (placement_probe.ProbeVerdict.UNKNOWN, "unsupported-dpr"),
        "undecodable": (placement_probe.ProbeVerdict.UNKNOWN, "invalid-evidence"),
        "frozenMotion": (placement_probe.ProbeVerdict.UNKNOWN, "stale-capture"),
        "coldDormant": (placement_probe.ProbeVerdict.UNKNOWN, "stale-capture"),
        "notDecoded": (placement_probe.ProbeVerdict.UNKNOWN, "invalid-evidence"),
        "wrongContext": (placement_probe.ProbeVerdict.UNKNOWN, "invalid-evidence"),
    }
    problems = []
    software_candidate = software and not result.grant_eligible and (
        (result.verdict == expected and result.tone_map == placement_probe.ToneMap.IDENTITY
         and result.reason == "software-map")
        or (result.verdict == placement_probe.ProbeVerdict.UNKNOWN and result.tone_map is None
            and result.reason == "ambiguous")
    )
    if not software_candidate and (result.verdict != expected or result.reason != expected_reason):
        problems.append(f"candidate {result.verdict.value}/{result.reason} != {expected.value}/{expected_reason}")
    if software_candidate and result.verdict == placement_probe.ProbeVerdict.UNKNOWN:
        required["wrongRule"] = (placement_probe.ProbeVerdict.UNKNOWN, "ambiguous")
    for name, (verdict, reason) in required.items():
        observed = controls[name]
        if observed.verdict != verdict or observed.reason != reason:
            problems.append(f"{name} {observed.verdict.value}/{observed.reason} != {verdict.value}/{reason}")
    return {"passed": not problems, "problems": problems, "candidate": _jsonable(result),
            **{name: _jsonable(value) for name, value in controls.items()}}


def probe_tone_rows(evidence: placement_probe.ClassifierInput, result: placement_probe.ProbeResult) -> dict[str, Any]:
    if result.verdict not in (placement_probe.ProbeVerdict.SNAP, placement_probe.ProbeVerdict.FRAC):
        return {"ramp": [], "patches": [], "problems": ["classifier has no unique candidate rule"]}
    capture = evidence.captures[0]
    geometry = next((row for row in evidence.poses if row.pose == capture.pose), None)
    if geometry is None:
        return {"ramp": [], "patches": [], "problems": ["capture geometry missing"]}
    image = _png_array(capture.png)
    video, snap, frac = placement_probe._candidate_regions(image, geometry)
    candidate = snap if result.verdict == placement_probe.ProbeVerdict.SNAP else frac
    x, y, _, _ = geometry.box
    cx, cy, cw, ch = geometry.content_box
    rx, ry, _, _ = geometry.rect
    video_origin = (cx - x, cy - y)
    def js_round(value: float) -> int:
        return math.floor(value + 0.5)

    candidate_origin = ((js_round(cx) if result.verdict == placement_probe.ProbeVerdict.SNAP else rx + js_round(cx - rx)) - x,
                        (js_round(cy) if result.verdict == placement_probe.ProbeVerdict.SNAP else ry + js_round(cy - ry)) - y)
    candidate_size = (js_round(cw), js_round(ch))

    def sample(region: np.ndarray, origin: tuple[float, float], size: tuple[float, float], source: tuple[int, int, int, int]) -> list[int]:
        sx, sy, sw, sh = source
        x0 = math.ceil(origin[0] + sx * size[0] / 1920) + 1
        y0 = math.ceil(origin[1] + sy * size[1] / 540) + 1
        x1 = math.floor(origin[0] + (sx + sw) * size[0] / 1920) - 1
        y1 = math.floor(origin[1] + (sy + sh) * size[1] / 540) - 1
        pixels = region[max(0, y0):min(region.shape[0], y1), max(0, x0):min(region.shape[1], x1), :3]
        if not pixels.size:
            raise ValueError("tone cell has no eroded pixels")
        return [int(round(value)) for value in np.median(pixels.reshape(-1, 3), axis=0)]

    def row(kind: str, index: int, source: tuple[int, int, int, int]) -> dict[str, Any]:
        observed = sample(video, video_origin, (cw, ch), source)
        reference = sample(candidate, candidate_origin, candidate_size, source)
        return {"kind": kind, "index": index, "source": reference, "observed": observed,
                "maxDelta": max(abs(left - right) for left, right in zip(observed, reference))}

    try:
        ramp = [row("ramp", index, (index * 40, 270, 40, 270)) for index in range(16)]
        patches = [row("patch", index, (640 + index * 80, 270, 80, 270)) for index in range(8)]
    except ValueError as exc:
        return {"ramp": [], "patches": [], "problems": [str(exc)]}
    return {"ramp": ramp, "patches": patches, "problems": []}


def analyze_program_recording(path: Path, *, started_s: float | None, stopped_s: float | None,
                              transaction_started_s: float | None, transaction_finished_s: float | None,
                              fps: float, stats_before: dict[str, Any] | None = None,
                              stats_after: dict[str, Any] | None = None) -> dict[str, Any]:
    timing_started = time.monotonic()
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    covered = (started_s is not None and stopped_s is not None and transaction_started_s is not None
               and transaction_finished_s is not None and started_s <= transaction_started_s
               and stopped_s >= transaction_finished_s)
    duration = stopped_s - started_s if started_s is not None and stopped_s is not None else None
    transaction_duration = (transaction_finished_s - transaction_started_s
                            if transaction_started_s is not None and transaction_finished_s is not None else None)
    minimum_frames = (max(0, math.ceil(transaction_duration * fps))
                      if transaction_duration is not None and transaction_duration >= 0 else None)
    wall_clock_minimum = max(0, math.ceil(duration * fps) - 1) if duration is not None and duration >= 0 else None
    skipped: dict[str, int] = {}
    for name in ("outputSkippedFrames", "renderSkippedFrames"):
        before = stats_before.get(name) if isinstance(stats_before, dict) else None
        after = stats_after.get(name) if isinstance(stats_after, dict) else None
        if isinstance(before, int) and not isinstance(before, bool) and isinstance(after, int) and not isinstance(after, bool):
            skipped[name] = after - before
    result: dict[str, Any] = {
        "lossless": False, "continuous": covered, "decodedFrames": 0, "identicalFrames": 0, "audioSilent": None,
        "audioPresent": None, "startedAt": started_s, "stoppedAt": stopped_s, "transactionStartedS": transaction_started_s,
        "transactionFinishedS": transaction_finished_s, "fps": fps, "minimumFrames": minimum_frames,
        "wallClockMinimumFrames": wall_clock_minimum, "skippedFrames": skipped,
        "skippedFramesZero": len(skipped) == 2 and all(value == 0 for value in skipped.values()),
        "statsBefore": stats_before, "statsAfter": stats_after,
    }
    try:
        meta, frames = obs_cadence_decode.read_frames(path)
        obs_cadence_decode.check_lossless(meta)
        result.update(lossless=True, codec=meta.get("codec"), pixFmt=meta.get("pix_fmt"), size=list(meta.get("size") or ()))
        reference = None
        digests = []
        white_centres = []
        for frame in frames:
            digest = hashlib.sha256(frame.tobytes()).digest()
            reference = digest if reference is None else reference
            digests.append(digest)
            centre = frame[frame.shape[0] // 2, frame.shape[1] // 2, :3]
            white_centres.append(bool(np.all(centre >= 250)))
            result["decodedFrames"] += 1
            result["identicalFrames"] += digest == reference
        candidates = [index for index, white in enumerate(white_centres)
                      if white and reference is not None and digests[index] != reference]
        runs = []
        for index in candidates:
            if not runs or index != runs[-1][-1] + 1:
                runs.append([index])
            else:
                runs[-1].append(index)
        flash_runs = [run for run in runs if run[0] > 0 and run[-1] + 1 < len(digests)
                      and digests[run[0] - 1] == reference and digests[run[-1] + 1] == reference]
        result["flashDetected"] = bool(flash_runs)
        result["flashFrames"] = [index for run in flash_runs for index in run]
        result["frameCountComplete"] = minimum_frames is not None and result["decodedFrames"] >= minimum_frames
        result["wallClockFrameCountComplete"] = (wall_clock_minimum is not None
                                                   and result["decodedFrames"] >= wall_clock_minimum)
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        audio = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "s16le", "-"],
                               capture_output=True, timeout=30, check=True).stdout
        result["audioBytes"] = len(audio)
        result["audioPresent"] = True
        result["audioSilent"] = all(byte == 0 for byte in audio)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="replace")[-300:] if exc.stderr else str(exc)
        if "does not contain any stream" in detail or "matches no streams" in detail:
            result["audioPresent"] = False
            result["error"] = f"missing audio stream: {detail}"
        else:
            result["error"] = f"CalledProcessError: {detail}"
    except (OSError, ValueError, subprocess.SubprocessError, obs_cadence_decode.NotLossless) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    result["timingS"] = {
        "wall": round(time.monotonic() - timing_started, 6),
        "subprocessCpu": round((child_after.ru_utime + child_after.ru_stime)
                                - (child_before.ru_utime + child_before.ru_stime), 6),
        "inputBytes": path.stat().st_size if path.is_file() else None,
        "audioBytes": result.get("audioBytes"),
    }
    return result


def analyze_rgba_samples(paths: list[Path], phases: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {"transparent": False, "halfTransparent": False, "sampleCount": len(paths),
                              "allChannelsEqual": False, "allPhasesCovered": False, "phases": phases}
    try:
        images = [np.asarray(Image.open(path).convert("RGBA")) for path in paths]
        if not images or any(image.shape != images[0].shape for image in images):
            return {**result, "error": "RGBA samples missing or dimensions differ"}
        alpha = images[0][..., 3]
        result["transparent"] = bool((alpha == 0).any())
        result["halfTransparent"] = bool(((alpha > 0) & (alpha < 255)).any())
        result["allChannelsEqual"] = all(np.array_equal(images[0], image) for image in images[1:])
        required = {"before-install", "installed", "before-capture", "after-capture", "before-cleanup", "restored"}
        result["allPhasesCovered"] = required <= set(phases)
        result["sha256"] = [hashlib.sha256(image.tobytes()).hexdigest() for image in images]
    except (OSError, ValueError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def transparent_probe_png(width: int, height: int) -> bytes:
    return _png_bytes(np.zeros((height, width, 4), np.uint8))


def freeze_probe_video(channel: managed_obs.CalibrationIO) -> None:
    transport = ChromeCdp(
        Path(), Path(), None, attach_endpoint=channel.cdp_endpoint, attach_match=channel.request.url,
    )
    try:
        transport.start()
        frozen = transport.evaluate(
            "(()=>{const v=document.getElementById('obed-probe-video');if(!v)return false;"
            "v.pause();Object.defineProperty(v,'play',{value:function(){this.pause();return Promise.resolve()},"
            "configurable:true});return v.paused})()",
        )
        if frozen is not True:
            raise RuntimeError("probe video did not pause")
    finally:
        transport.detach()


class QualificationCalibrationAdapter:
    def __init__(self, adapter: managed_obs.CalibrationAdapter,
                 sample: Callable[[str], None] | None = None, *, placement: str = "preview",
                 settle: Callable[[], dict[str, Any]] | None = None,
                 start_recording: Callable[[], None] | None = None,
                 stop_recording: Callable[[], str | None] | None = None,
                 read_stats: Callable[[], dict[str, Any]] | None = None,
                 sample_capture_phases: bool = True, measure_control: str | None = None) -> None:
        self.adapter = adapter
        self.sample = sample or (lambda _phase: None)
        self.placement = placement
        self.settle = settle
        self.start_recording = start_recording
        self.stop_recording = stop_recording
        self.read_stats = read_stats
        self.sample_capture_phases = sample_capture_phases
        self.measure_control = measure_control
        self.request: managed_obs.CalibrationRequest | None = None
        self.result: managed_obs.CalibrationResult | None = None
        self.events: list[dict[str, Any]] = []
        self.phase_times_ns: dict[str, int] = {}
        self.sample_costs: list[dict[str, Any]] = []
        self.settle_detail: dict[str, Any] | None = None
        self.recording: str | None = None
        self.recording_started_s: float | None = None
        self.recording_stopped_s: float | None = None
        self.recording_error: str | None = None
        self.recording_stats_before: dict[str, Any] | None = None
        self.recording_stats_after: dict[str, Any] | None = None
        self.control_detail: dict[str, Any] = {"kind": measure_control, "captures": 0}
        self.done = threading.Event()

    def arm(self, measure_control: str | None = None) -> None:
        self.measure_control = measure_control
        self.request = None
        self.result = None
        self.control_detail = {"kind": measure_control, "captures": 0}
        self.done.clear()

    def identity(self) -> managed_obs.EngineIdentity | None:
        return self.adapter.identity()

    def start(self, request: managed_obs.CalibrationRequest, *, measure: Callable[[managed_obs.CalibrationIO], placement_probe.ClassifierInput],
              guard: managed_obs.ProgramGuard) -> Any:
        self.arm(self.measure_control)
        recorder = self

        def controlled(channel: managed_obs.CalibrationIO) -> placement_probe.ClassifierInput:
            if self.measure_control is None:
                return measure(channel)
            previous: bytes | None = None
            count = 0

            class ControlIO:
                request = channel.request
                source_uuid = channel.source_uuid
                cdp_endpoint = channel.cdp_endpoint
                cancel_event = channel.cancel_event
                deadline_s = channel.deadline_s

                def check_current(self) -> None:
                    channel.check_current()

                def capture_png(self, *, timeout_s: float = 2.0) -> bytes:
                    nonlocal count, previous
                    count += 1
                    recorder.control_detail["captures"] = count
                    if recorder.measure_control == "capture-error" and count > 1:
                        raise RuntimeError("injected capture failure after first capture")
                    current = channel.capture_png(timeout_s=timeout_s)
                    if recorder.measure_control == "transparent" and count == 1:
                        return transparent_probe_png(channel.request.spec.width, channel.request.spec.height)
                    if recorder.measure_control == "replay" and count == 2 and previous is not None:
                        return previous
                    previous = current
                    if recorder.measure_control == "frozen-video" and count == 1:
                        freeze_probe_video(channel)
                        recorder.control_detail["videoPaused"] = True
                    return current

            return measure(ControlIO())

        class Guard:
            def begin(self) -> None:
                guard.begin()

            def sample(self, phase: str) -> None:
                guard.sample(phase)
                recorder.phase_times_ns[phase] = time.time_ns()
                sampled = recorder.sample_capture_phases or phase not in ("before-capture", "after-capture")
                started = time.monotonic()
                if sampled:
                    recorder.sample(phase)
                recorder.sample_costs.append({"phase": phase, "sampled": sampled,
                                              "costMs": round((time.monotonic() - started) * 1000, 3)})

            def finish(self) -> managed_obs.ProgramCheck:
                return guard.finish()

        actual_request = replace(request, placement=self.placement)
        self.request = actual_request
        self.events.append({"at": time.time(), "event": "calibration-start", "placement": {"state": "probing"}})
        if self.settle is not None:
            self.settle_detail = self.settle()
        if self.start_recording is not None:
            self.start_recording()
            self.recording_started_s = time.monotonic()
            if self.read_stats is not None:
                try:
                    self.recording_stats_before = self.read_stats()
                except Exception as exc:
                    self.recording_error = f"GetStats before recording transaction: {type(exc).__name__}: {exc}"
        future = self.adapter.start(actual_request, measure=controlled, guard=Guard())
        host_future: Future[managed_obs.CalibrationResult] = Future()

        def finished(value: Any) -> None:
            try:
                self.result = value.result()
                event = "complete"
                host_future.set_result(replace(self.result, request=request))
            except Exception:
                event = "error"
                host_future.set_exception(RuntimeError("qualification calibration failed"))
            finally:
                if self.recording_started_s is not None and self.recording_stopped_s is None and self.stop_recording is not None:
                    try:
                        self.recording = self.stop_recording()
                    except Exception as exc:
                        self.recording_error = f"{type(exc).__name__}: {exc}"
                    self.recording_stopped_s = time.monotonic()
                    if self.read_stats is not None:
                        try:
                            self.recording_stats_after = self.read_stats()
                        except Exception as exc:
                            self.recording_error = f"GetStats after recording transaction: {type(exc).__name__}: {exc}"
            placement = self.events[-1]["placement"] if self.events else {}
            self.events.append({"at": time.time(), "event": event, "placement": placement})
            self.done.set()

        future.add_done_callback(finished)
        return host_future

    def cancel(self, run_id: str, *, timeout_s: float = 5.0) -> bool:
        return self.adapter.cancel(run_id, timeout_s=timeout_s)

    def close_recording(self) -> None:
        if self.recording_started_s is None or self.recording_stopped_s is not None or self.stop_recording is None:
            return
        try:
            self.recording = self.stop_recording()
        except Exception as exc:
            self.recording_error = f"{type(exc).__name__}: {exc}"
        self.recording_stopped_s = time.monotonic()
        if self.read_stats is not None:
            try:
                self.recording_stats_after = self.read_stats()
            except Exception as exc:
                self.recording_error = f"GetStats after recording transaction: {type(exc).__name__}: {exc}"

    def placement_event(self, placement: dict[str, Any]) -> None:
        previous = self.events[-1].get("placement") if self.events else None
        if previous != placement:
            self.events.append({"at": time.time(), "event": "placement", "placement": json.loads(json.dumps(placement))})


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


def unpremultiply(img: np.ndarray) -> np.ndarray:
    """GetSourceScreenshot's RGB is premultiplied by alpha; straight RGBA (as CDP screenshots) for the dissolve scorer,
    which premultiplies again (round trip within 0.5)."""
    a = img[..., 3:4].astype(np.float32)
    rgb = np.where(a > 0, np.minimum(np.rint(img[..., :3] * 255.0 / np.maximum(a, 1.0)), 255.0), 0.0)
    return np.concatenate([rgb.astype(np.uint8), img[..., 3:4]], axis=2)


@contextlib.contextmanager
def source_shots(port: int, password: str) -> Iterator[Callable[[], np.ndarray]]:
    """H x W x 4 premultiplied RGBA renders of scene `AK` via obs-websocket (an independent scene render, not the DeckLink
    wire), over one connection."""
    def shot() -> np.ndarray:
        data = ws.request("GetSourceScreenshot", {"sourceName": "AK", "imageFormat": "png", "imageWidth": 1920,
                                                  "imageHeight": 1080})["imageData"]
        return np.array(Image.open(io.BytesIO(base64.b64decode(data.split(",", 1)[-1]))).convert("RGBA"))

    with mock.patch.object(obs_websocket, "_MAX_MESSAGE_BYTES", 64 * 1024 * 1024), ObsWebsocket(port, password, timeout=10.0) as ws:
        yield shot


def obs_screenshot(port: int, password: str) -> np.ndarray:
    with source_shots(port, password) as shot:
        return shot()


def _color_control(ws: ObsWebsocket, name: str, color: int, *, behind: bool) -> int:
    created = ws.request(
        "CreateInput",
        {"sceneName": managed_obs.PROGRAM_SCENE, "inputName": name, "inputKind": "color_source_v3",
         "inputSettings": {"width": 1920, "height": 1080, "color": color}, "sceneItemEnabled": True},
    )
    item_id = int(created["sceneItemId"])
    if behind:
        ws.request("SetSceneItemIndex", {"sceneName": managed_obs.PROGRAM_SCENE, "sceneItemId": item_id, "sceneItemIndex": 0})
    return item_id


def live_integrity_controls(creds: tuple[int, str]) -> dict[str, Any]:
    baseline = obs_screenshot(*creds)
    repeated = obs_screenshot(*creds)
    controls: dict[str, Any] = {
        "isolation": {"null": {"verdict": "PASS" if np.array_equal(baseline, repeated) else "FAIL"}},
        "alpha": {"null": {"verdict": "PASS" if np.array_equal(baseline, repeated) else "FAIL"}},
    }

    def injected(name: str, color: int, *, behind: bool) -> dict[str, Any]:
        try:
            with ObsWebsocket(*creds) as ws:
                _color_control(ws, name, color, behind=behind)
            changed = obs_screenshot(*creds)
            return {"verdict": "FAIL" if not np.array_equal(baseline, changed) else "PASS",
                    "changedPixels": int(np.count_nonzero(np.any(baseline != changed, axis=2)))}
        except Exception as exc:
            return {"verdict": "INCONCLUSIVE", "reason": f"{type(exc).__name__}: {exc}"}
        finally:
            with contextlib.suppress(Exception), ObsWebsocket(*creds) as ws:
                ws.request("RemoveInput", {"inputName": name})

    controls["isolation"]["visibleOrigin"] = injected("AK-Control-Visible", 0xFF0000FF, behind=False)
    controls["isolation"]["behindTransparentProgram"] = injected("AK-Control-Behind", 0xFF00FF00, behind=True)
    controls["alpha"]["behindProgramLeak"] = controls["isolation"]["behindTransparentProgram"]
    controls["alpha"]["alphaOnly"] = injected("AK-Control-Alpha", 0x40000000, behind=True)
    return controls


def wait_control_inputs_absent(creds: tuple[int, str], timeout_s: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last = []
    while time.monotonic() < deadline:
        with ObsWebsocket(*creds) as ws:
            rows = ws.request("GetInputList").get("inputs") or []
        last = sorted(row.get("inputName") for row in rows
                      if isinstance(row, dict) and isinstance(row.get("inputName"), str)
                      and row["inputName"].startswith("AK-Control-"))
        if not last:
            return {"absent": True, "inputs": []}
        time.sleep(0.05)
    raise RuntimeError(f"scratch control inputs did not disappear: {last}")


def canvas_fps(video_settings: Any, rate: int) -> float:
    if isinstance(video_settings, dict):
        numerator = video_settings.get("fpsNumerator")
        denominator = video_settings.get("fpsDenominator")
        if isinstance(numerator, int) and not isinstance(numerator, bool) and isinstance(denominator, int) \
                and not isinstance(denominator, bool) and numerator > 0 and denominator > 0:
            observed = numerator / denominator
            if abs(observed - rate) <= 0.2:
                return observed
    label = managed_obs.RATES[rate][0]
    match = re.match(r"(\d+(?:\.\d+)?)", label)
    if match is None:
        raise ValueError(f"canvas rate unavailable from {video_settings!r} / {label!r}")
    return float(match.group(1))


def recording_stats(creds: tuple[int, str]) -> dict[str, Any]:
    with ObsWebsocket(*creds) as ws:
        return ws.request("GetStats")


def recording_positive_controls(creds: tuple[int, str], run_dir: Path, fps: float) -> dict[str, Any]:
    sine = run_dir / "placement" / "program" / "audio-positive.wav"
    sine.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    audio_reason = None
    try:
        subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=1000:duration=0.4",
                        "-c:a", "pcm_s16le", str(sine)], capture_output=True, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        audio_reason = f"audio fixture unavailable: {type(exc).__name__}: {exc}"
    started_s = time.monotonic()
    start_record(*creds)
    recording = None
    stop_detail: dict[str, Any] | None = None
    controls_cleaned = False
    try:
        time.sleep(0.2)
        if audio_reason is None:
            with ObsWebsocket(*creds) as ws:
                ws.request(
                    "CreateInput",
                    {"sceneName": managed_obs.PROGRAM_SCENE, "inputName": "AK-Control-Audio", "inputKind": "ffmpeg_source",
                     "inputSettings": {"is_local_file": True, "local_file": str(sine), "looping": False,
                                       "restart_on_activate": True}, "sceneItemEnabled": True},
                )
            time.sleep(0.5)
        else:
            time.sleep(0.5)
        with contextlib.suppress(Exception), ObsWebsocket(*creds) as ws:
            ws.request("RemoveInput", {"inputName": "AK-Control-Audio"})
        with ObsWebsocket(*creds) as ws:
            _color_control(ws, "AK-Control-Flash", 0xFFFFFFFF, behind=False)
        time.sleep(2 / fps)
        with ObsWebsocket(*creds) as ws:
            ws.request("RemoveInput", {"inputName": "AK-Control-Flash"})
        controls_cleaned = True
    finally:
        if not controls_cleaned:
            for input_name in ("AK-Control-Audio", "AK-Control-Flash"):
                with contextlib.suppress(Exception), ObsWebsocket(*creds) as ws:
                    ws.request("RemoveInput", {"inputName": input_name})
        recording, stop_detail = stop_record(*creds, fps=fps)
    stopped_s = time.monotonic()
    path = Path(recording)
    retained = run_dir / "placement" / "program" / f"control-{path.name}"
    shutil.move(path, retained)
    analysis = analyze_program_recording(
        retained, started_s=started_s, stopped_s=stopped_s, transaction_started_s=started_s,
        transaction_finished_s=stopped_s, fps=fps,
    )
    flash = {"verdict": "FAIL" if analysis.get("flashDetected") is True else "PASS",
             "recording": dissolve_probe.placement_file_ref(retained, run_dir)}
    if audio_reason is not None:
        audio = {"verdict": "REPORTED", "reason": audio_reason}
    elif analysis.get("audioPresent") is not True:
        audio = {"verdict": "REPORTED", "reason": "seeded Program has reroute_audio=false; page audio bypasses the OBS mix"}
    else:
        audio = {"verdict": "FAIL" if analysis.get("audioSilent") is False else "PASS"}
    return {"flash": flash, "audio": audio, "analysis": analysis, "recordingStop": stop_detail}


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
    manifest = fixture / "fixture.json"
    return binary_counter_movie.read_manifest(fixture).get("counter", "grey") if manifest.exists() else "grey"


def p2_family(fixture: Path) -> bool:
    """The P2 fixture or a counter-swapped copy of it that does not loop."""
    manifest = binary_counter_movie.read_manifest(fixture)
    return fixture.resolve() == FIXTURE.resolve() or (manifest.get("base") == binary_counter_movie.FIXTURE_BASE and "loop" not in manifest)


def fixture_loops(fixture: Path) -> bool:
    return (fixture / "fixture.json").exists() and "loop" in binary_counter_movie.read_manifest(fixture)


def check_loop_frames(fixture: Path) -> None:
    manifest = binary_counter_movie.read_manifest(fixture)
    frames = {m.get("frames") for m in manifest.get("movies") or []}
    if (frames or "loop" in manifest) and frames != {SOAK_LOOP_FRAMES}:
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
        plans = {gl: ground_truth_plan(dest, slides, gl_replay=gl) for gl in (False, True)}
        for gl, plan in plans.items():
            runtime = plan.to_runtime()
            if isinstance(runtime, Unsupported):
                raise SystemExit(f"fixture does not qualify on product code (gl_replay={gl}): {runtime.reason}")
            if plan_signature(runtime) not in P2_PLAN_SHA256:
                raise SystemExit(f"fixture is not a pinned P2-family plan (gl_replay={gl})")
        return ground_truth_facts(plans[True], armed=True)["armed"]
    finally:
        shutil.rmtree(dest.parent, ignore_errors=True)


def feed_fixture_facts(fixture: Path) -> dict[str, Any]:
    dest, slides = make_export("feed-facts", fixture)
    try:
        identity = require_feed_fixture(dest, slides)
        facts = ground_truth_facts(ground_truth_plan(dest, slides))
        if not any(spec.get("underArtwork") is True for spec in facts.get("verdicts") or []):
            raise SystemExit("feed fixture derives no under-artwork carries")
        bind_feed_source_fps(facts, dest, slides)
        facts["fixtureIdentity"] = identity
        return facts
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
        self.name, self.host, self.creds, self.shots, self.engine_state, self.ctx = (
            name, host, ctx["creds"], ctx["shots"], ctx["engineState"], ctx,
        )
        self.canvas_fps = float(ctx["canvasFps"])
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
                mm_opacity: str = "auto", seed: str | None = None, record: bool = False, logger: bool = False,
                square: bool = False, mm_feed: str | None = None, mm_feed_qualify_once: bool = False) -> dict[str, Any]:
    fixture = ctx["fixture"]
    dest, slides = make_export(f"{ctx['tag']}-{name}", fixture)
    kwargs: dict[str, Any] = {"mm_opacity": mm_opacity} if gl_replay is None else {"gl_replay": gl_replay, "mm_opacity": mm_opacity}
    if logger:
        kwargs["transport_factory"] = LoggedCdp
    if mm_feed is not None:
        kwargs["mm_feed"] = mm_feed
    if mm_feed_qualify_once:
        kwargs["mm_feed_qualify_once"] = True
    if ctx.get("feedFacts"):
        kwargs["pre_navigation_scripts"] = feed_instrument_pre_navigation_scripts(ctx["feedFacts"])
    session: Session | None = None
    out: dict[str, Any] = {"session": name, "glReplayArg": gl_replay, "mmOpacityArg": mm_opacity, "mmFeedArg": mm_feed,
                           "mmFeedQualifyOnce": mm_feed_qualify_once, "seed": seed, "square": square}
    try:
        if ctx.get("feedFacts"):
            out["fixtureIdentity"] = require_feed_fixture(dest, slides)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mm_opacity_probe.square_player(square))
            if seed is not None:
                out["seedSplice"] = stack.enter_context(forced_fail_seed(seed))
            if record:
                start_record(*ctx["creds"])
                stack.callback(lambda: out.update(recording=stop_record(
                    *ctx["creds"], fps=ctx["canvasFps"])[0]))
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


def _recording_duration_ms(status: dict[str, Any]) -> float:
    value = status.get("outputDuration")
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
        raise RuntimeError("recording duration is unavailable")
    return float(value)


def _recording_is_readable(path: Path, timeout_s: float) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    result = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(path), "-map", "0:v:0",
         "-frames:v", "1", "-f", "null", "-"],
        capture_output=True, timeout=timeout_s,
    )
    return result.returncode == 0


def _best_effort_stop_record(port: int, password: str, timeout_s: float) -> None:
    with contextlib.suppress(Exception), ObsWebsocket(port, password, timeout=timeout_s) as ws:
        ws.request("StopRecord")
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if ws.request("GetRecordStatus").get("outputActive") is False:
                return
            time.sleep(0.02)


def stop_record(port: int, password: str, *, fps: float,
                timeout_s: float = RECORD_STOP_TIMEOUT_S) -> tuple[str, dict[str, Any]]:
    started = time.monotonic()
    result_detail: dict[str, Any] = {
        "requiredPostRestorationFrames": RECORD_TAIL_FRAMES,
        "postRestorationFramesComplete": False,
        "inactive": False,
        "readable": False,
    }
    stop_sent = False
    try:
        if not isinstance(fps, (int, float)) or isinstance(fps, bool) or not math.isfinite(fps) or fps <= 0:
            raise RuntimeError(f"recording fps is invalid: {fps!r}")
        deadline = started + timeout_s
        tail_s = RECORD_TAIL_FRAMES / float(fps)
        with ObsWebsocket(port, password, timeout=timeout_s) as ws:
            initial = ws.request("GetRecordStatus")
            if initial.get("outputActive") is not True:
                raise RuntimeError("recording is not active before stop")
            initial_duration = _recording_duration_ms(initial)
            target_duration = initial_duration + 1000.0 * tail_s
            last = initial
            while time.monotonic() < deadline:
                last = ws.request("GetRecordStatus")
                if _recording_duration_ms(last) >= target_duration and time.monotonic() - started >= tail_s:
                    result_detail["postRestorationFramesComplete"] = True
                    break
                time.sleep(0.02)
            if not result_detail["postRestorationFramesComplete"]:
                raise RuntimeError(f"recording did not retain {RECORD_TAIL_FRAMES} post-restoration frames")
            result_detail["observedPostRestorationFrames"] = math.floor(
                (_recording_duration_ms(last) - initial_duration) * float(fps) / 1000.0)
            stopped = ws.request("StopRecord")
            stop_sent = True
            output_path = stopped.get("outputPath")
            if not isinstance(output_path, str) or not output_path:
                raise RuntimeError("StopRecord returned no output path")
            while time.monotonic() < deadline:
                status = ws.request("GetRecordStatus")
                if status.get("outputActive") is False:
                    result_detail["inactive"] = True
                    break
                time.sleep(0.02)
        if not result_detail["inactive"]:
            raise RuntimeError("recording remained active after StopRecord")
        remaining = max(0.1, deadline - time.monotonic())
        result_detail["readable"] = _recording_is_readable(Path(output_path), remaining)
        if not result_detail["readable"]:
            raise RuntimeError("recording output is not readable after finalization")
        return output_path, result_detail
    except Exception as exc:
        if not stop_sent:
            _best_effort_stop_record(port, password, timeout_s)
        exc.detail = result_detail
        if isinstance(exc, RuntimeError):
            raise
        error = RuntimeError(f"{type(exc).__name__}: {exc}")
        error.detail = result_detail
        raise error from exc
    finally:
        result_detail["durationS"] = round(time.monotonic() - started, 6)


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


def feed_script(continuous_expected: bool) -> Callable[[Session], None]:
    def script(s: Session) -> None:
        facts = s.ctx["feedFacts"]
        sink: dict[str, Any] = {}
        s.host.execute("show")
        raw = drive_and_sample(
            s.host, carry_into={spec["toPlayer"] for spec in facts["verdicts"] if spec["kind"] == "carry"},
            feed_facts=facts, feed_sink=sink,
        )
        samples = convert_samples_to_authored(raw)[0]
        for record in (sink.get("verdicts") or {}).values():
            if isinstance(record, dict):
                record["continuousExpected"] = continuous_expected
        s.out["feedEvidence"] = sink
        s.out["feedVerdicts"] = score_verdicts(
            samples, {}, facts, True, s.host.output.get("continuity"), schema=2, feed_evidence=sink,
        )
        s.out["sampleRows"] = samples
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


def mo3_script(gl: str, arm: str, armed: dict[str, Any]) -> Callable[[Session], None]:
    """MO-3: `mm_opacity_probe.drive` on the engine page (settle ROI and movie masks from the armed facts); the record is
    scored by `mm_opacity_probe`."""
    def script(s: Session) -> None:
        masks = mm_opacity_probe.boundary_masks(armed)
        rec: dict[str, Any] = {"gl": gl, "arm": arm, "mmOpacityKwarg": mm_opacity_probe.ALL_ARMS[arm], "steps": [],
                               "liveGreenSource": "obs", "roi": mm_opacity_probe.settle_roi(), "masks": masks}
        s.out["mo1"] = rec
        rec["output"] = {k: s.host.output.get(k) for k in ("mmOpacity", "continuity")}
        mm_opacity_probe.drive(s.host, rec, mm_opacity_probe.step_extra(masks), lambda: obs_screenshot(*s.creds))
    return script


def mo3_arms(gl: str) -> dict[str, str]:
    return mm_opacity_probe.ALL_ARMS if gl == "auto" else mm_opacity_probe.ARMS


def dissolve_calibration(n: float | None) -> dissolve_probe.Calibration | None:
    """DX-2's CEF thresholds from n = opaque-off's max mid-frame residual, unclamped; None (INCONCLUSIVE) past a cap."""
    if n is None or not math.isfinite(n) or n < 0:
        return None
    up = math.ceil(n)
    cal = dissolve_probe.Calibration(tau=float(max(dissolve_probe.TAU, up + 1)), complement=dissolve_probe.COMPLEMENT_TOL + up,
                                     no_dip=dissolve_probe.NO_DIP_MIN - up)
    return cal if cal.tau <= DX2_TAU_MAX and cal.complement <= DX2_COMPLEMENT_MAX and cal.no_dip >= DX2_NO_DIP_MIN else None


def opaque_off_calibration(record: dict[str, Any], images: dict[str, np.ndarray]) -> dict[str, Any]:
    scored = dissolve_probe.score_arm(record, images, dissolve_probe.CEF.arm("opaque-off"), profile=dissolve_probe.CEF)
    model = scored["checks"].get("model", {}).get("verdict")
    n = max(scored["midResiduals"]) if model in ("PASS", "FAIL") and scored["midResiduals"] else None
    cal = dissolve_calibration(n)
    return {"n": n, "model": model, "problems": scored["problems"], "calibration": asdict(cal) if cal else None}


def dissolve_evidence(record: dict[str, Any]) -> list[str]:
    output = record.get("output") or {}
    continuity = output.get("continuity") or {}
    missing = [name for name, value in (("continuity", continuity.get("mode")), ("G2 mode", (continuity.get("glReplay") or {}).get("mode")),
                                        ("served digest", (output.get("mmOpacity") or {}).get("sha256"))) if not value]
    if (record.get("g2") is not None) if (continuity.get("glReplay") or {}).get("mode") == "off" else (
            not isinstance(record.get("g2"), str) or not record["g2"]):
        missing.append("G2 state")
    missing += [f"colour tuple of {v.get('src')}" for v in (record.get("dump") or {}).get("vids") or [] if v.get("rv")
                and not (isinstance(v.get("tuple"), str) and dissolve_probe.COLOUR_TUPLE.fullmatch(v["tuple"]))]
    return missing


def await_input(transport: Any, timeout_s: float = 10.0) -> float:
    """CEF drops CDP key input for a moment after a new document loads; a lone Shift keyUp (the player handles keydown
    only) is resent until the page sees one. Returns the seconds it took."""
    transport.evaluate("window.__obedDxInput=0;document.addEventListener('keyup',function f(e){window.__obedDxInput=1;"
                       "document.removeEventListener('keyup',f,true)},true)")
    started = time.monotonic()
    while not transport.evaluate("window.__obedDxInput"):
        if time.monotonic() - started > timeout_s:
            raise RuntimeError(f"page saw no key input within {timeout_s} s")
        transport.call("Input.dispatchKeyEvent", type="keyUp", key="Shift", code="ShiftLeft", windowsVirtualKeyCode=16)
        time.sleep(0.1)
    return round(time.monotonic() - started, 2)


def program_guard_controls(host: LiveOutputHost, creds: tuple[int, str]) -> dict[str, Any]:
    transport = host._require_transport()
    context = host._program_context()
    if context is None:
        return {"null": {"ok": None, "reason": "program context unavailable"},
                "toggle": {"ok": None, "reason": "program context unavailable"}}

    def run(toggle: bool) -> managed_obs.ProgramCheck:
        guard = _ProgramGuard(transport, context)
        item_id = None
        finished = False
        try:
            guard.begin()
            if toggle:
                with ObsWebsocket(*creds) as ws:
                    items = ws.request("GetSceneItemList", {"sceneName": managed_obs.PROGRAM_SCENE}).get("sceneItems") or []
                    item = next((row for row in items if row.get("sourceName") == "Program"), None)
                    if not isinstance(item, dict) or not isinstance(item.get("sceneItemId"), int):
                        raise RuntimeError("Program scene item unavailable")
                    item_id = item["sceneItemId"]
                    ws.request("SetSceneItemEnabled", {"sceneName": managed_obs.PROGRAM_SCENE,
                                                       "sceneItemId": item_id, "sceneItemEnabled": False})
                    time.sleep(1.0)
                    ws.request("SetSceneItemEnabled", {"sceneName": managed_obs.PROGRAM_SCENE,
                                                       "sceneItemId": item_id, "sceneItemEnabled": True})
            time.sleep(0.35)
            guard.sample("control")
            result = guard.finish()
            finished = True
            return result
        except Exception as exc:
            return managed_obs.ProgramCheck(None, 0, None, None, (), f"{type(exc).__name__}: {exc}")
        finally:
            if not finished:
                with contextlib.suppress(Exception):
                    guard.finish()
            if toggle and item_id is not None:
                with contextlib.suppress(Exception), ObsWebsocket(*creds) as ws:
                    ws.request("SetSceneItemEnabled", {"sceneName": managed_obs.PROGRAM_SCENE,
                                                       "sceneItemId": item_id, "sceneItemEnabled": True})

    return {"null": _jsonable(run(False)), "toggle": _jsonable(run(True))}


def pre_start_gaps(record: dict[str, Any]) -> list[float] | None:
    """The rAF gaps `dissolve_probe.raf_gaps` allows (pending animations) while the transition DOM is present."""
    try:
        return [round(g, 1) for g in dissolve_probe.raf_gaps([r for r in record["dump"]["raf"] if "eff" in r])[1]]
    except (KeyError, TypeError):
        return None


def dissolve_session(name: str, ctx: dict[str, Any], decision: dict[str, Any] | None) -> dict[str, Any]:
    """One DX-2 session on the engine page; the record and images go to `<shots>/runs/<name>/` (`dissolve_probe` layout)."""
    arm = dissolve_probe.ARMS[name]
    record: dict[str, Any] = {"arm": name, "load": os.getloadavg()[0], "headlessBefore": mm_opacity_probe.headless_chromes()}
    images: dict[str, np.ndarray] = {}
    host: LiveOutputHost | None = None
    started = time.monotonic()
    try:
        resolved = dissolve_probe.resolve(arm, ctx["shots"] / "scratch", decision, tag=name)
        record.update(resolved.fields())
        host = LiveOutputHost(resolved.root, resolved.slides, resolver=resolved.resolver, transport_factory=dissolve_probe.hooked_transport(),
                              attach_endpoint=ctx["endpoint"], attach_match=ctx["target"], bridge="obs-managed", output_rate=ctx["rate"],
                              continuity=arm.continuity, gl_replay="off", mm_opacity="auto" if arm.mode == "on" else "off")
        with dissolve_probe.serving(arm.splice):
            host.start()
        record["page"] = "alpha" if host.output.get("alpha") else "screen"
        record["output"] = {k: host.output.get(k) for k in ("mmOpacity", "continuity", "placement")}
        record["inputLiveS"] = await_input(host._require_transport())
        record["g2"] = ((host._require_transport().evaluate(GL_REPLAY_READ_JS) or {}).get("api") or {}).get("state")
        raw: dict[int, np.ndarray] = {}
        with source_shots(*ctx["creds"]) as shot:
            driven, images = dissolve_probe.drive(host, arm, resolved.target, lambda: raw.setdefault(id(img := shot()), img))
        images = {k: unpremultiply(v) if raw.get(id(v)) is v else v for k, v in images.items()}
        record.update(driven)
        if arm.capture == "cut":
            record["cast"] = [{"name": s["name"], "t0": s["t0"], "t1": s["t1"]} for s in record.get("shots") or []]
        missing = dissolve_evidence(record)
        if missing:
            record["error"] = f"DX-2 evidence missing: {'; '.join(missing)}"
    except Exception:
        record["error"] = traceback.format_exc()
    finally:
        if host is not None:
            try:
                host.stop()
            except Exception as exc:
                record["stopError"] = str(exc)
    dissolve_probe.save_run(ctx["shots"], name, record, images)
    out: dict[str, Any] = {"session": name, "runDir": str(ctx["shots"] / "runs" / name), "page": record.get("page"),
                           "output": record.get("output"), "g2": record.get("g2"),
                           "colourTuples": [[v.get("src"), v.get("tuple"), v.get("err")] for v in (record.get("dump") or {}).get("vids") or []],
                           "inputLiveS": record.get("inputLiveS"), "preStartGapsMs": pre_start_gaps(record),
                           "timingS": {"script": round(time.monotonic() - started, 2)}}
    if record.get("error"):
        out["fatal"] = str(record["error"])[-3000:]
        print(f"    [{name}] {out['fatal']}", flush=True)
    if name == "opaque-off":
        out["calibration"] = opaque_off_calibration(record, images)
        print(f"    [{name}] DX-2 calibration {out['calibration']}", flush=True)
    return out


def _wait_placement_control(host: LiveOutputHost, adapter: QualificationCalibrationAdapter) -> None:
    deadline = time.monotonic() + 35.0
    while time.monotonic() < deadline:
        host.observe()
        adapter.placement_event(host.output.get("placement") or {})
        if adapter.done.is_set() and (host.output.get("placement") or {}).get("state") != "probing":
            return
        time.sleep(0.05)
    raise TimeoutError("placement control did not complete")


def _wait_output_live(host: LiveOutputHost, timeout_s: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last = None
    live_since = None
    while time.monotonic() < deadline:
        last = host.observe()
        if last.output_visible and not last.busy:
            live_since = live_since or time.monotonic()
            if time.monotonic() - live_since >= 1.0:
                return {"live": True, "outputVisible": True}
        else:
            live_since = None
        time.sleep(0.05)
    return {"live": False, "outputVisible": bool(last and last.output_visible)}


def _host_log_excerpt(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("kind") in {"placementProbe", "placementClassifier", "placementProbeRejected", "execute"}:
            rows.append(row)
    return rows


def score_placement_control(value: Any, run_dir: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        return calibration_gate("INCONCLUSIVE", ["placement control record missing"])
    name = value.get("session")
    if name not in PLACEMENT_CONTROL_SESSIONS:
        return calibration_gate("INCONCLUSIVE", [f"unknown placement control {name!r}"])
    problems = []
    unknown = []
    expected_placement, expected_studio, expected_control = PLACEMENT_CONTROL_SPECS[name]
    if (value.get("placement"), value.get("studioEnabled"), value.get("measureControl")) != \
            (expected_placement, expected_studio, expected_control):
        problems.append("control setup differs from the frozen session specification")
    transaction = value.get("transaction")
    if not isinstance(transaction, dict):
        unknown.append("transaction summary missing")
    else:
        program = transaction.get("program")
        if not (transaction.get("isolationOk") is True and transaction.get("cleanupVerified") is True
                and transaction.get("restored") is True and isinstance(program, dict) and program.get("ok") is True
                and (expected_control is not None or not transaction.get("errors"))):
            problems.append("transaction isolation, Program guard, cleanup, or restore failed")
    if value.get("studioAfter") != expected_studio:
        problems.append("Studio Mode was not preserved")
    control_detail = value.get("control")
    minimum_captures = {"capture-error": 2, "replay": 2, "transparent": 1, "frozen-video": 2}
    if expected_control is not None and not (
            isinstance(control_detail, dict) and control_detail.get("kind") == expected_control
            and isinstance(control_detail.get("captures"), int)
            and control_detail["captures"] >= minimum_captures[expected_control]):
        problems.append("named probe fault did not intercept the capture path")
    output = value.get("output")
    if not isinstance(output, dict):
        unknown.append("placement output missing")
    elif expected_control is None:
        if not (output.get("state") == "valid" and output.get("grant") == "frac" and output.get("method") == "probe"):
            problems.append("startup control did not grant frac through the probe")
    elif not (output.get("state") == "invalid" and output.get("grant") is None and output.get("reason") == "probe-failed"):
        problems.append("negative control did not reject the probe with no grant")
    try:
        log_rows = _read_ref_json(value.get("hostLog"), run_dir)
        if not isinstance(log_rows, list) or any(not isinstance(row, dict) for row in log_rows):
            raise ValueError("host-log excerpt is not a row list")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        log_rows = []
        unknown.append(f"host-log excerpt unavailable: {type(exc).__name__}: {exc}")
    if expected_control in ("replay", "transparent"):
        freshness_error = isinstance(transaction, dict) and any(
            "Probe capture freshness could not be verified." in str(error)
            for error in transaction.get("errors") or [])
        host_rejection = any(
            (row.get("kind") == "placementProbe"
             and "Probe capture freshness could not be verified." in str(row.get("error")))
            or (row.get("kind") == "placementProbeRejected" and row.get("reason") == "probe-failed")
            for row in log_rows)
        if not freshness_error or not host_rejection:
            problems.append("transaction and host log lack the probe freshness rejection")
    if expected_control == "frozen-video" and not any(
            row.get("kind") == "placementClassifier" and row.get("reason") == "stale-capture" for row in log_rows):
        problems.append("host log lacks the stale-capture classifier rejection")
    if name == "failed-preview-off":
        on_air = value.get("onAir")
        if not isinstance(on_air, dict):
            unknown.append("on-air recalibration evidence missing")
        elif not (on_air.get("shown") is True and on_air.get("live") is True
                  and on_air.get("recalibrateScheduled") is True
                  and (on_air.get("initialOutput") or {}).get("state") == "valid"
                  and (on_air.get("initialOutput") or {}).get("grant") == "frac"
                  and (on_air.get("initialOutput") or {}).get("method") == "probe"):
            problems.append("on-air recalibration did not start after a live successful show")
    verdict = "INCONCLUSIVE" if unknown else "FAIL" if problems else "PASS"
    return calibration_gate(verdict, [*unknown, *problems], session=name, output=output, transaction=transaction,
                            control=control_detail, onAir=value.get("onAir"), hostLog=log_rows)


def placement_control_session(name: str, ctx: dict[str, Any], decision: dict[str, Any] | None, *,
                              placement: str, studio_enabled: bool, measure_control: str | None = None) -> dict[str, Any]:
    started = time.monotonic()
    run_dir = ctx["shots"] / "runs" / name
    run_dir.mkdir(parents=True, exist_ok=True)
    scope = placement_scope(ctx.get("tier", "full"), ctx.get("devProfile"))
    control: dict[str, Any] = {"session": name, "placement": placement, "studioEnabled": studio_enabled,
                               **scope,
                               "measureControl": measure_control}
    host: LiveOutputHost | None = None
    initial_control = None if name == "failed-preview-off" else measure_control
    adapter = QualificationCalibrationAdapter(
        ctx["calibration"], placement=placement,
        settle=lambda: {"inputLiveS": await_input(host._require_transport())} if host is not None else {},
        measure_control=initial_control,
    )
    original_studio = None
    host_log_path = None
    try:
        with ObsWebsocket(*ctx["creds"]) as ws:
            original_studio = bool(ws.request("GetStudioModeEnabled").get("studioModeEnabled"))
            ws.request("SetStudioModeEnabled", {"studioModeEnabled": studio_enabled})
        arm = dissolve_probe.ARMS["m-snap-cef"]
        resolved = dissolve_probe.resolve(arm, ctx["shots"] / "scratch", decision, tag=name)
        host = LiveOutputHost(
            resolved.root, resolved.slides, resolver=resolved.resolver,
            transport_factory=dissolve_probe.hooked_transport(before=PLACEMENT_ALPHA_JS),
            attach_endpoint=ctx["endpoint"], attach_match=ctx["target"], bridge="obs-managed", output_rate=ctx["rate"],
            continuity=arm.continuity, gl_replay="off", mm_opacity="auto", calibration=adapter, placement_mode="probe",
        )
        with dissolve_probe.serving(arm.splice):
            host.start()
        _wait_placement_control(host, adapter)
        if name == "failed-preview-off":
            initial_output = json.loads(json.dumps(host.output.get("placement") or {}))
            shown = host.execute("show")
            live = _wait_output_live(host)
            adapter.measure_control = measure_control
            scheduled = host.execute("recalibrate")
            _wait_placement_control(host, adapter)
            control["onAir"] = {
                "initialOutput": initial_output, "shown": shown.output_visible is True,
                "live": live.get("live") is True, "recalibrateScheduled": scheduled.output.get("placement", {}).get("state") == "probing",
            }
        result = adapter.result
        output = json.loads(json.dumps(host.output.get("placement") or {}))
        with ObsWebsocket(*ctx["creds"]) as ws:
            studio_after = bool(ws.request("GetStudioModeEnabled").get("studioModeEnabled"))
        control.update(
            output=output,
            transaction=None if result is None else {
                "isolationOk": result.isolation_ok, "cleanupVerified": result.cleanup_verified,
                "restored": result.restored, "program": _jsonable(result.program), "errors": list(result.errors),
                "evidencePresent": result.evidence is not None,
            },
            control=adapter.control_detail,
            studioAfter=studio_after,
        )
        host_log_path = host._log_path
    except Exception:
        control["error"] = traceback.format_exc()
        if host is not None:
            host_log_path = host._log_path
    finally:
        if host is not None:
            with contextlib.suppress(Exception):
                host.stop()
        if original_studio is not None:
            with contextlib.suppress(Exception), ObsWebsocket(*ctx["creds"]) as ws:
                ws.request("SetStudioModeEnabled", {"studioModeEnabled": original_studio})
    control["hostLog"] = write_placement_json(run_dir, "host-log", _host_log_excerpt(host_log_path))
    scored = score_placement_control(control, run_dir)
    control["recordedVerdict"] = scored["verdict"]
    dissolve_probe.save_run(ctx["shots"], name, {**scope, "acquisition": placement_acquisition(ctx),
                                                 "placementControl": control}, {})
    return {"session": name, "runDir": str(run_dir), "verdict": scored["verdict"],
            "output": control.get("output"), "timingS": {"script": round(time.monotonic() - started, 2)}, **scope}


def placement_control_rows(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {}
    for record in records:
        name = record.get("session")
        if name not in PLACEMENT_CONTROL_SESSIONS or not record.get("runDir"):
            continue
        run_dir = Path(record["runDir"])
        try:
            saved = json.loads((run_dir / "record.json").read_text())
            scored = score_placement_control(saved.get("placementControl"), run_dir)
        except (OSError, json.JSONDecodeError) as exc:
            scored = calibration_gate("INCONCLUSIVE", [f"control rescore failed: {type(exc).__name__}: {exc}"])
        by_name[name] = {"session": name, **scored}
    startup = [by_name.get("startup-preview-on"), by_name.get("startup-offcanvas-on")]
    failed = [by_name.get("failed-preview-off"), by_name.get("failed-offcanvas-on")]
    initial_states = {PLACEMENT_CONTROL_SPECS[record["session"]][1] for record in [*startup, *failed]
                      if isinstance(record, dict)}

    def aggregate(rows: list[dict[str, Any] | None]) -> dict[str, Any]:
        verdict = ("NOT-RUN" if not all(isinstance(row, dict) for row in rows) else
                   "PASS" if all(row.get("verdict") == "PASS" for row in rows if isinstance(row, dict)) else "FAIL")
        return {"verdict": verdict,
                "sessions": [row.get("session") for row in rows if isinstance(row, dict)]}

    isolation = {
        "startup": aggregate(startup),
        "failedOnAir": aggregate(failed),
        "priorStudioStates": {"verdict": "PASS" if initial_states == {False, True} else "NOT-RUN",
                              "states": sorted(initial_states)},
    }
    probe = {name: by_name.get(f"probe-{name}") or {"verdict": "NOT-RUN"}
             for name in ("replay", "transparent", "frozen-video")}
    return {"isolation": isolation, "probe": probe}


def capture_placement_sessions(
        arm: dissolve_probe.Arm,
        capture_session: Callable[[int], tuple[dict[str, Any], dict[str, Any], dict[str, np.ndarray]]],
        cal: dissolve_probe.Calibration,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sessions = []
    attempts = []
    limit = 3 if arm.counter_strip == "distinct" else 1
    min_frames = dissolve_probe.CEF_PLACEMENT.mid_frames
    for attempt in range(1, limit + 1):
        session, record, images = capture_session(attempt)
        sessions.append(session)
        coverage = dissolve_probe.capture_coverage(record, images, arm, min_frames, cal)
        row = {"attempt": attempt, **coverage, "shots": record.get("shots", []),
               "record": f"attempt-{attempt}/record.json", "runDir": session.get("runDir")}
        attempts.append(row)
        shortage = f"{coverage['midFrames']} mid frames < {min_frames}"
        if coverage["problems"] != [shortage]:
            break
    return sessions, attempts


def placement_attempt_paths(run_dir: Path, arm: dissolve_probe.Arm) -> list[Path]:
    if arm.counter_strip != "distinct":
        return [run_dir / "record.json"]
    try:
        parent = json.loads((run_dir / "record.json").read_text())
    except (OSError, json.JSONDecodeError):
        return []
    attempts = parent.get("captureAttempts")
    if not isinstance(attempts, list):
        return []
    paths = []
    for index, attempt in enumerate(attempts, 1):
        relative = attempt.get("record") if isinstance(attempt, dict) else None
        paths.append(run_dir / relative if isinstance(relative, str) else run_dir / f"attempt-{index}" / "record.json")
    return paths


def score_placement_capture_attempts(run_dir: Path, arm: dissolve_probe.Arm,
                                     cal: dissolve_probe.Calibration, lut: np.ndarray | None) -> dict[str, Any]:
    rows = []
    if arm.counter_strip != "distinct":
        return calibration_gate("PASS", [])
    paths = placement_attempt_paths(run_dir, arm)
    if not paths:
        return calibration_gate("INCONCLUSIVE", ["capture attempt records missing"])
    profile = replace(dissolve_probe.CEF_PLACEMENT, mid_frames=0)
    for index, path in enumerate(paths, 1):
        try:
            record = json.loads(path.read_text())
            images = dissolve_probe.RunImages(path.parent)
            scored = dissolve_probe.score_arm(record, images, arm, cal, profile=profile, lut=lut)
            rows.append({"attempt": index, "outcome": scored["outcome"], "problems": scored["problems"],
                         "mismatch": scored["mismatch"]})
        except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
            rows.append({"attempt": index, "outcome": "INCONCLUSIVE",
                         "problems": [f"attempt unreadable: {type(exc).__name__}: {exc}"], "mismatch": []})
    problems = [f"attempt {row['attempt']}: {problem}" for row in rows if row["outcome"] != "MATCH"
                for problem in (row["problems"] or [f"outcome {row['outcome']}; mismatch {row['mismatch']}"])]
    verdict = ("FAIL" if any(row["outcome"] == "MISMATCH" for row in rows) else
               "INCONCLUSIVE" if problems else "PASS")
    return calibration_gate(verdict, problems, attempts=rows)


def _drive_placement(host: LiveOutputHost, arm: dissolve_probe.Arm, target: dict[str, Any],
                     capture: Callable[[], np.ndarray], *,
                     placement_read: Callable[[Any], None] | None = None,
                     ) -> tuple[dict[str, Any], dict[str, np.ndarray], dict[str, Any] | None]:
    try:
        driven, images = dissolve_probe.drive(
            host, arm, target, capture, placement=True, placement_read=placement_read)
        return driven, images, None
    except dissolve_probe.ReadinessTimeout as exc:
        return {}, {}, {"verdict": "INCONCLUSIVE", "kind": "readiness", "message": str(exc)}


def _placement_injected_session_attempt(
        name: str, ctx: dict[str, Any], decision: dict[str, Any] | None, *,
        run_name: str, attempt: int | None = None,
        ) -> tuple[dict[str, Any], dict[str, Any], dict[str, np.ndarray]]:
    arm = dissolve_probe.ARMS[name]
    scope = placement_scope(ctx.get("tier", "full"), ctx.get("devProfile"))
    record: dict[str, Any] = {
        "arm": name, "load": os.getloadavg()[0], "headlessBefore": mm_opacity_probe.headless_chromes(),
        **scope, "acquisition": placement_acquisition(ctx),
    }
    timing = record["timingS"] = {"classification": 0.0, "recordingAnalysis": 0.0, "collectionCopy": 0.0}
    if attempt is not None:
        record["captureAttempt"] = attempt
    images: dict[str, np.ndarray] = {}
    host: LiveOutputHost | None = None
    injection: PlacementInjection | None = None
    started = time.monotonic()
    run_dir = ctx["shots"] / "runs" / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        t = time.monotonic()
        resolved = dissolve_probe.resolve(arm, ctx["shots"] / "scratch", decision, tag=name)
        timing["preparation"] = round(time.monotonic() - t, 6)
        record.update(resolved.fields())
        acquisition_started = time.monotonic()
        host = LiveOutputHost(
            resolved.root, resolved.slides, resolver=resolved.resolver,
            transport_factory=dissolve_probe.hooked_transport(before=PLACEMENT_ALPHA_JS),
            attach_endpoint=ctx["endpoint"], attach_match=ctx["target"], bridge="obs-managed", output_rate=ctx["rate"],
            continuity=arm.continuity, gl_replay="off", mm_opacity="auto" if arm.mode == "on" else "off",
            calibration=None, placement_mode="probe",
        )
        with dissolve_probe.serving(arm.splice):
            host.start()
        value = arm.placement_value or dissolve_probe.CEF_PLACEMENT.placement
        injection = PlacementInjection(host, ctx["calibration"].identity, ctx["target"], value)
        injection.start()
        transport = host._require_transport()
        record["inputLiveS"] = await_input(transport)
        transport.evaluate("(function(){var n=document.getElementById('obed-placement-alpha');if(n)n.remove()})()")
        record["page"] = "alpha" if host.output.get("alpha") else "screen"
        record["output"] = {k: host.output.get(k) for k in ("mmOpacity", "continuity", "placement")}
        record["g2"] = ((transport.evaluate(GL_REPLAY_READ_JS) or {}).get("api") or {}).get("state")
        with source_shots(*ctx["creds"]) as shot:
            raw: dict[int, np.ndarray] = {}
            driven, captured, integrity_failure = _drive_placement(
                host, arm, resolved.target, lambda: raw.setdefault(id(image := shot()), image),
                placement_read=injection.take_read)
            images = {key: unpremultiply(value) if raw.get(id(value)) is value else value
                      for key, value in captured.items()}
        record.update(driven)
        if integrity_failure is not None:
            record["integrityFailure"] = integrity_failure
        else:
            injection.ensure_valid()
        timing["acquisition"] = round(time.monotonic() - acquisition_started, 6)
        missing = dissolve_evidence(record)
        if integrity_failure is not None:
            record["error"] = f"placement readiness INCONCLUSIVE: {integrity_failure['message']}"
        elif missing:
            record["error"] = f"placement evidence missing: {'; '.join(missing)}"
    except Exception:
        record["error"] = traceback.format_exc()
    finally:
        if injection is not None:
            record["placementInjection"] = injection.stop_and_revoke()
            if injection.failure is not None:
                record["integrityFailure"] = {
                    "verdict": "INCONCLUSIVE", "kind": "placement-injection", "message": injection.failure,
                }
        if host is not None:
            try:
                host.stop()
            except Exception as exc:
                record["stopError"] = str(exc)
    timing["script"] = round(time.monotonic() - started, 6)
    t = time.monotonic()
    dissolve_probe.save_run(ctx["shots"], run_name, record, images)
    timing["reportWrite"] = round(time.monotonic() - t, 6)
    saved_path = run_dir / "record.json"
    if saved_path.is_file():
        saved = json.loads(saved_path.read_text())
        saved["timingS"] = timing
        saved_path.write_text(json.dumps(saved))
    out: dict[str, Any] = {
        "session": name, "runDir": str(run_dir), "page": record.get("page"), **scope,
        "output": record.get("output"), "timingS": timing,
    }
    if record.get("integrityFailure"):
        out["integrityFailure"] = record["integrityFailure"]
    if record.get("error"):
        out["fatal"] = str(record["error"])[-3000:]
    return out, record, images


def _placement_session_attempt(name: str, ctx: dict[str, Any], decision: dict[str, Any] | None, *,
                               run_name: str, attempt: int | None = None,
                               ) -> tuple[dict[str, Any], dict[str, Any], dict[str, np.ndarray]]:
    if name not in PLACEMENT_ANCHORS:
        return _placement_injected_session_attempt(
            name, ctx, decision, run_name=run_name, attempt=attempt)
    arm = dissolve_probe.ARMS[name]
    scope = placement_scope(ctx.get("tier", "full"), ctx.get("devProfile"))
    record: dict[str, Any] = {"arm": name, "load": os.getloadavg()[0],
                              "headlessBefore": mm_opacity_probe.headless_chromes(), **scope,
                              "acquisition": placement_acquisition(ctx)}
    timing = record["timingS"] = {"collectionCopy": 0.0, "recordingAnalysis": 0.0, "classification": 0.0}
    if attempt is not None:
        record["captureAttempt"] = attempt
    images: dict[str, np.ndarray] = {}
    samples: list[tuple[str, np.ndarray]] = []
    sample_lock = threading.Lock()
    host: LiveOutputHost | None = None
    preflight: dict[str, Any] = {}
    recording_stop: dict[str, Any] = {}
    started = time.monotonic()
    run_dir = ctx["shots"] / "runs" / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    def sample(phase: str) -> None:
        image = obs_screenshot(*ctx["creds"])
        with sample_lock:
            samples.append((phase, image))

    def settle() -> dict[str, Any]:
        if host is None:
            raise RuntimeError("placement host unavailable")
        input_live_s = await_input(host._require_transport())
        preflight["liveControls"] = live_integrity_controls(ctx["creds"])
        preflight["liveControls"]["isolation"].update(ctx["placementControls"]["isolation"])
        preflight["recordingControls"] = recording_positive_controls(ctx["creds"], run_dir, ctx["canvasFps"])
        preflight["programGuard"] = program_guard_controls(host, ctx["creds"])
        absent = wait_control_inputs_absent(ctx["creds"])
        first = obs_screenshot(*ctx["creds"])
        second = obs_screenshot(*ctx["creds"])
        with sample_lock:
            samples.extend((("settled-0", first), ("settled-1", second)))
        if not np.array_equal(first, second):
            raise RuntimeError("Program did not settle to two equal OBS samples")
        return {"inputLiveS": input_live_s, "controlsAbsent": absent, "equalProgramSamples": True}

    sampled = name != "m-snap-cef"

    def stop_placement_recording() -> str:
        nonlocal recording_stop
        try:
            recording, recording_stop = stop_record(*ctx["creds"], fps=ctx["canvasFps"])
            return recording
        except Exception as exc:
            detail = getattr(exc, "detail", None)
            if isinstance(detail, dict):
                recording_stop = detail
            raise

    adapter = QualificationCalibrationAdapter(
        ctx["calibration"], sample, placement="offcanvas" if name == "opaque-off" else "preview",
        settle=settle, start_recording=lambda: start_record(*ctx["creds"]),
        stop_recording=stop_placement_recording,
        read_stats=lambda: recording_stats(ctx["creds"]),
        sample_capture_phases=sampled,
    )
    try:
        t = time.monotonic()
        resolved = dissolve_probe.resolve(arm, ctx["shots"] / "scratch", decision, tag=name)
        timing["preparation"] = round(time.monotonic() - t, 6)
        record.update(resolved.fields())
        collection_path = ctx["collectionPath"]
        baseline_saved = collection_saved_by_obs(collection_path)
        t = time.monotonic()
        _baseline, baseline_ref = capture_collection(collection_path, run_dir, "baseline", saved_by_obs=baseline_saved)
        _null_before, null_before_ref = capture_collection(collection_path, run_dir, "null-before", saved_by_obs=baseline_saved)
        _null_after, null_after_ref = capture_collection(collection_path, run_dir, "null-after", saved_by_obs=baseline_saved)
        timing["collectionCopy"] += time.monotonic() - t
        acquisition_started = time.monotonic()
        host = LiveOutputHost(
            resolved.root, resolved.slides, resolver=resolved.resolver,
            transport_factory=dissolve_probe.hooked_transport(before=PLACEMENT_ALPHA_JS),
            attach_endpoint=ctx["endpoint"], attach_match=ctx["target"], bridge="obs-managed", output_rate=ctx["rate"],
            continuity=arm.continuity, gl_replay="off", mm_opacity="auto" if arm.mode == "on" else "off",
            calibration=adapter, placement_mode="probe",
        )
        with dissolve_probe.serving(arm.splice):
            host.start()
        deadline = time.monotonic() + 35.0
        while time.monotonic() < deadline:
            host.observe()
            placement = host.output.get("placement") or {}
            adapter.placement_event(placement)
            if adapter.done.is_set() and placement.get("state") != "probing":
                break
            time.sleep(0.05)
        result = adapter.result
        placement = host.output.get("placement") or {}
        if result is None:
            raise RuntimeError("managed placement calibration did not complete")
        t = time.monotonic()
        _cleanup, cleanup_ref = capture_collection(collection_path, run_dir, "cleanup", saved_by_obs=True)
        timing["collectionCopy"] += time.monotonic() - t
        controls = preflight.get("programGuard") or {}
        controls["candidate"] = _jsonable(result.program)
        sample("null")
        record["page"] = "alpha" if host.output.get("alpha") else "screen"
        record["output"] = {k: host.output.get(k) for k in ("mmOpacity", "continuity", "placement")}
        record["inputLiveS"] = (adapter.settle_detail or {}).get("inputLiveS")
        drive_placement = json.loads(json.dumps(placement))
        t = time.monotonic()
        classification = placement_probe.classify_probe(result.evidence) if result.evidence is not None else None
        tone = probe_tone_rows(result.evidence, classification) if result.evidence is not None and classification is not None else {
            "ramp": [], "patches": [], "problems": ["classifier evidence missing"]}
        tone.update({"complete": False, "applied": "identity", "observed": classification.tone_map.value
                     if classification and classification.tone_map else None,
                     "missingRows": ["second fresh launch acceleration-on", "second fresh launch acceleration-off", "hevc10",
                                     "Keynote-HEVC", "skin tones", "reset/invalidation controls"]})
        timing["classification"] = round(time.monotonic() - t, 6)
        t = time.monotonic()
        classifier_control_rows = (
            classifier_controls(result.evidence, classification, placement_probe.ProbeVerdict.FRAC)
            if result.evidence is not None and classification is not None else None)
        timing["classifierControls"] = round(time.monotonic() - t, 6)
        expected_value = classification.verdict.value if classification else None
        if arm.placement_value is not None and arm.placement_value != expected_value:
            record["forcedPlacement"] = dissolve_probe.commit_grant(
                host._require_transport().evaluate, host._placement_token, arm.placement_value, 15_000)
        host._require_transport().evaluate("(function(){var n=document.getElementById('obed-placement-alpha');if(n)n.remove()})()")
        record["g2"] = ((host._require_transport().evaluate(GL_REPLAY_READ_JS) or {}).get("api") or {}).get("state")
        with source_shots(*ctx["creds"]) as shot:
            raw: dict[int, np.ndarray] = {}
            driven, captured, integrity_failure = _drive_placement(
                host, arm, resolved.target, lambda: raw.setdefault(id(image := shot()), image))
            images = {key: unpremultiply(value) if raw.get(id(value)) is value else value
                      for key, value in captured.items()}
        record.update(driven)
        if integrity_failure is not None:
            record["integrityFailure"] = integrity_failure
        timing["acquisition"] = round(time.monotonic() - acquisition_started, 6)

        rgba_paths = []
        phases = []
        with sample_lock:
            captured = list(samples)
        for index, (phase, image) in enumerate(captured):
            path = run_dir / "placement" / "rgba" / f"{index:02d}-{phase}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(image).save(path)
            rgba_paths.append(path)
            phases.append(phase)
        recording_ref = None
        recording_analysis = None
        if adapter.recording and Path(adapter.recording).is_file():
            path = run_dir / "placement" / "program" / Path(adapter.recording).name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(adapter.recording, path)
            recording_ref = dissolve_probe.placement_file_ref(path, run_dir)
            t = time.monotonic()
            recording_analysis = analyze_program_recording(
                path, started_s=adapter.recording_started_s, stopped_s=adapter.recording_stopped_s,
                transaction_started_s=result.started_s, transaction_finished_s=result.finished_s,
                fps=ctx["canvasFps"], stats_before=adapter.recording_stats_before,
                stats_after=adapter.recording_stats_after,
            )
            timing["recordingAnalysis"] = round(time.monotonic() - t, 6)
        telemetry = {
            "programGuard": controls,
            "programRecording": recording_analysis,
            "recordingError": adapter.recording_error,
            "recordingStop": recording_stop or None,
            "recordingControls": preflight.get("recordingControls"),
            "alpha": analyze_rgba_samples(rgba_paths, phases),
            "classifierControls": classifier_control_rows,
            "liveProbeControls": ctx["placementControls"]["probe"],
            "toneRows": tone,
            "liveControls": preflight.get("liveControls"),
            "drivePlacement": drive_placement,
            "samplingMode": "sampled-alpha" if sampled else "product-timing",
            "sampleCosts": adapter.sample_costs,
            "settle": adapter.settle_detail,
            "persistenceNull": "running-file stability only; STEP0_NULL_ALLOWLIST scores persistence",
        }
        telemetry_ref = write_placement_json(run_dir, "telemetry", telemetry)
        record["placementCalibration"] = placement_record(
            backend="cef", placement=result.request.placement, obs_version=ctx.get("obsVersion"),
            engine=result.request.engine, request=result.request, evidence=result.evidence, classification=classification,
            transaction=result, events=adapter.events,
            persistence={"baseline": baseline_ref, "nullBefore": null_before_ref, "nullAfter": null_after_ref,
                         "cleanup": cleanup_ref, "quit": None, "backup": [],
                         "lastRemovalMtimeNs": adapter.phase_times_ns.get("restored"),
                         "checks": [_jsonable(result.persistence)] if result.persistence is not None else []},
            integrity={"recording": recording_ref, "rgba": [dissolve_probe.placement_file_ref(path, run_dir) for path in rgba_paths],
                       "telemetry": telemetry_ref},
            stock_sha256=resolved.served["stockSha256"],
        )
        missing = dissolve_evidence(record)
        if integrity_failure is not None:
            record["error"] = f"placement readiness INCONCLUSIVE: {integrity_failure['message']}"
        elif missing:
            record["error"] = f"placement evidence missing: {'; '.join(missing)}"
    except Exception:
        record["error"] = traceback.format_exc()
    finally:
        adapter.close_recording()
        if host is not None:
            try:
                host.stop()
            except Exception as exc:
                record["stopError"] = str(exc)
    timing["collectionCopy"] = round(timing["collectionCopy"], 6)
    timing["script"] = round(time.monotonic() - started, 6)
    t = time.monotonic()
    dissolve_probe.save_run(ctx["shots"], run_name, record, images)
    timing["reportWrite"] = round(time.monotonic() - t, 6)
    saved_path = run_dir / "record.json"
    if saved_path.is_file():
        saved = json.loads(saved_path.read_text())
        saved["timingS"] = timing
        saved_path.write_text(json.dumps(saved))
    out: dict[str, Any] = {"session": name, "runDir": str(run_dir), "page": record.get("page"), **scope,
                           "output": record.get("output"), "timingS": timing}
    if record.get("integrityFailure"):
        out["integrityFailure"] = record["integrityFailure"]
    if record.get("error"):
        out["fatal"] = str(record["error"])[-3000:]
    if name == "opaque-off":
        out["calibration"] = opaque_off_calibration(record, images)
    return out, record, images


def placement_session(name: str, ctx: dict[str, Any], decision: dict[str, Any] | None) -> dict[str, Any]:
    arm = dissolve_probe.ARMS[name]
    if arm.counter_strip != "distinct":
        return _placement_session_attempt(name, ctx, decision, run_name=name)[0]
    run_dir = ctx["shots"] / "runs" / name
    run_dir.mkdir(parents=True, exist_ok=True)
    cal = ctx.get("placementScoringCalibration")
    if not isinstance(cal, dissolve_probe.Calibration):
        cal = dissolve_probe.Calibration()

    def capture(attempt: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, np.ndarray]]:
        return _placement_session_attempt(
            name, ctx, decision, run_name=f"{name}/attempt-{attempt}", attempt=attempt)

    sessions, attempts = capture_placement_sessions(arm, capture, cal)
    scope = placement_scope(ctx.get("tier", "full"), ctx.get("devProfile"))
    summary = {"arm": name, **scope, "acquisition": placement_acquisition(ctx), "captureAttempts": [
        {key: value for key, value in row.items() if key != "runDir"} for row in attempts
    ]}
    (run_dir / "record.json").write_text(json.dumps(summary))
    last = sessions[-1]
    fatal = [session.get("fatal") for session in sessions if session.get("fatal")]
    return {
        "session": name,
        "runDir": str(run_dir),
        "page": last.get("page"),
        "output": last.get("output"),
        "timingS": {"attempts": [session.get("timingS") for session in sessions]},
        "attempts": [{"attempt": index, "runDir": session.get("runDir")} for index, session in enumerate(sessions, 1)],
        **scope,
        **({"fatal": fatal[-1]} if fatal else {}),
    }


def chrome_placement_session(name: str, ctx: dict[str, Any], *, gpu: bool) -> dict[str, Any]:
    started = time.monotonic()
    run_dir = ctx["shots"] / "runs" / name
    run_dir.mkdir(parents=True, exist_ok=True)
    scope = placement_scope(ctx.get("tier", "full"), ctx.get("devProfile"))
    record: dict[str, Any] = {"arm": name, **scope, "acquisition": placement_acquisition(ctx)}
    try:
        measured = dissolve_probe.run_chrome_placement_probe(gpu=gpu)
        tone = probe_tone_rows(measured["input"], measured["classification"])
        tone.update({"complete": False, "applied": "identity",
                     "observed": measured["classification"].tone_map.value if measured["classification"].tone_map else None,
                     "missingRows": ["second fresh launch", "hevc10", "Keynote-HEVC", "skin tones",
                                     "reset/invalidation controls"]})
        telemetry_ref = write_placement_json(
            run_dir, "telemetry",
            {"classifierControls": classifier_controls(measured["input"], measured["classification"],
                                                       placement_probe.ProbeVerdict.SNAP, software=not gpu),
             "toneRows": tone, "chromeGpu": gpu},
        )
        stock = (dissolve_probe.DECKS["p2"].unmodified / "assets/player/main.js").read_bytes()
        record["launch"] = measured["launch"]
        record["placementCalibration"] = placement_record(
            backend="chrome-harness", placement=None, obs_version=None, engine=None, request=None,
            evidence=measured["input"], classification=measured["classification"], transaction=None, events=[],
            persistence=None, integrity={"recording": None, "rgba": [], "telemetry": telemetry_ref},
            stock_sha256=hashlib.sha256(stock).hexdigest(),
        )
    except Exception:
        record["error"] = traceback.format_exc()
    dissolve_probe.save_run(ctx["shots"], name, record, {})
    record_path = run_dir / "record.json"
    if record_path.is_file():
        saved = json.loads(record_path.read_text())
        calibration = saved.get("placementCalibration")
        if isinstance(calibration, dict):
            calibration["gates"] = score_placement_calibration(calibration, run_dir)["gates"]
            record_path.write_text(json.dumps(saved))
    out = {"session": name, "runDir": str(run_dir),
           "timingS": {"script": round(time.monotonic() - started, 2)}, **scope}
    if record.get("error"):
        out["fatal"] = str(record["error"])[-3000:]
    return out


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
        s.out.setdefault("windows", []).append({
            "minute": minute, "recording": stop_record(*s.creds, fps=s.canvas_fps)[0]})

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
        s.read("postHandback")
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
        check(checks, f"{prefix}{key}", stats.get(key), stats.get(key) == want,
              f"== {want} (patch {mode}; expected from {EXPECTED_STATS_SOURCE[mode][key]})")


def handback_unengaged(session: dict[str, Any]) -> str | None:
    """A patch-on G2 session whose hand-back fix did not engage (hand-back plan §3.4: timing-dependent) replays today's
    geometry: its take is INVALID, never a stock twin read as a pass or a failure of the fix. The signal is G2's unproven
    set still holding the pre-fix `rest-opacity` (`UNENGAGED_STATS`: Texture is still the 178x157 source, so `size` passes);
    `frameLen` is no signal, the player's uniform cache makes it timing-dependent. A patch-on session without G2
    (`g2-off`, `g2off-on`) has no signal: its engagement is unchecked under OBS."""
    stats = api_of((session.get("reads") or {}).get("liveEnd")).get("stats") or {}
    if mm_mode(session) != "on" or any(stats.get(k) != v for k, v in UNENGAGED_STATS.items()):
        return None
    return f"{session.get('session')}: hand-back fix not engaged (G2 frameLen {stats.get('frameLen')}, unproven rest-opacity)"


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
    clauses = ("mode", "live", "events", "noPainting", "pool")
    for clause in clauses:
        check(m1, f"score_armed.{clause}", scored["checks"][clause], scored["checks"][clause], enforced=scored["checks"][clause] is not None)
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
    off_checks = score_armed(off.get("armed"), armed, continuity_of(off))["checks"]
    off_verdict = combine_verdicts(*(off_checks[c] for c in clauses))
    check(m1, "KB: g2-off score_armed False", off_verdict, off_verdict is False, "False", enforced=off_verdict is not None)
    check(m1, "report: page rAF Hz from each phase start", raf_rates(g2), True, enforced=False)
    unengaged = handback_unengaged(g2)
    unreadable = [c for c in clauses if scored["checks"][c] is None]
    reasons = [unengaged, f"g2: score_armed clauses unreadable: {unreadable}" if unreadable else None,
               f"g2-off: score_armed clauses unreadable: {[c for c in clauses if off_checks[c] is None]}" if off_verdict is None else None]
    gates["M1"] = gate(m1, "; ".join(r for r in reasons if r) or None)

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
    painters = movie_painters(after, armed)
    check(m2, "one painting movie <video> at P3", painters, painters is not None and len(painters) == 1
          and matches_asset_keys(painters[0], armed["assetKeys"]), "== 1, the movie")
    check(m2, "report: handback repeat/gaps", [handback.get("repeatFrac"), handback.get("gapsGE3")], True, enforced=False)
    check(m2, "report: counter; max forward step live/handback/native", [d_g2.get("counter"), live.get("maxForwardStep"),
          forward, native.get("maxForwardStep")], True, enforced=False)
    check(m2, "report: handoff completedMs", [h.get("completedMs") for h in handoffs], True, enforced=False)
    check(m2, "report: g2 handback ringDiag", (d_g2.get("ringDiag") or {}).get("slide2-handback"), True, enforced=False)
    check(m2, "report: g2-off handback ringMaxDelta (DOM null)", (d_off.get("ringMaxDelta") or {}).get("slide2-handback"), True, enforced=False)
    check(m2, "report: handback ring px over 20, g2 vs g2-off", over20, True, enforced=False)
    check(m2, "report: g2-off handback ringDiag", (d_off.get("ringDiag") or {}).get("slide2-handback"), True, enforced=False)
    gates["M2"] = gate(m2, "g2: painting at P3 unreadable" if painters is None else None)

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
    fidelity = scaled_alpha_delta(s_g2, p3_g2, band, 1.0)
    check(m3, "edge: G2-S alpha == G2-P3 (DOM) alpha", fidelity, fidelity is not None and fidelity <= tol, f"<= {tol}")
    stock = scaled_alpha_delta(p3_g2, s_opaque, band, SLOT_OPACITY)
    check(m3, "KB: edge, G2-P3 vs round(mm-off-S alpha x 0.2947) (stock geometry) fails", stock, stock is not None and stock > tol,
          f"> {tol}")
    unscaled = scaled_alpha_delta(s_g2, s_opaque, band, 1.0)
    check(m3, "KB: edge vs unscaled mm-off-S alpha fails", unscaled, unscaled is not None and unscaled > tol, f"> {tol}")
    edge_dom = max_delta(s_g2, p3_g2, band)
    edge_count = int((band & (np.abs(s_g2.astype(np.int16) - p3_g2.astype(np.int16)).max(axis=2) > LIMITS["domTol"])).sum()) \
        if s_g2 is not None and p3_g2 is not None else None
    check(m3, "report: edge G2-S vs G2-P3 (player vs DOM softness) max, px > 3", [edge_dom, edge_count], True, enforced=False)
    opaque_alpha = alpha_range(s_opaque, reg["T"])
    check(m3, "KB: mm-off-S T alpha fails the slot check", opaque_alpha,
          opaque_alpha is not None and not (want - tol <= opaque_alpha[0] and opaque_alpha[1] <= want + tol), f"not {want} +- {tol}")
    check(m3, "prerequisite: mm-off-S T alpha is opaque (the KB reference)", opaque_alpha, opaque_alpha is not None and opaque_alpha[0] >= LIMITS["movieAlphaMin"],
          f">= {LIMITS['movieAlphaMin']}")
    off_alpha = alpha_range(s_off, reg["T"])
    check(m3, "T alpha (g2-off-S, patch on, GL replay off)", off_alpha,
          off_alpha is not None and want - tol <= off_alpha[0] and off_alpha[1] <= want + tol, f"{want} +- {tol}")
    gates["M3"] = gate(m3, gates["M0"]["invalid"] or unengaged)

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


def mmo_badness(top: np.ndarray, s_off: np.ndarray, alpha: float = MM_ALPHA) -> np.ndarray:
    """Per frame, in output levels, how far ROI_top is from the square at `alpha` over a neutral background. The residual
    R = P - alpha * S_off is (1 - alpha) * B; premise (the p2-binary fixture): every background under the square is neutral
    (black canvas and sentinel, black/white counter, grey grating), so R's channels agree and lie in [0, (1 - alpha) * 255].
    Badness = max over ROI_top of max(channel spread of R, excess of R outside that range)."""
    r = top.astype(float) - alpha * s_off[None]
    hi, lo = r.max(axis=-1), r.min(axis=-1)
    return np.maximum.reduce([hi - lo, hi - (1.0 - alpha) * 255, -lo]).max(axis=-1)


def slide1_instrument(series: dict[str, np.ndarray] | None, s_off: np.ndarray | None, alpha: float = MM_ALPHA) -> float | None:
    """Max badness over slide-1 frames: the (Keynote-correct) DOM square read by the same test."""
    if series is None or s_off is None or not phase_rows(series, MMO_SLIDE1).any():
        return None
    return round(float(mmo_badness(series["pixels.top"][phase_rows(series, MMO_SLIDE1)], s_off, alpha).max()), 2)


def mmo_tau(series: dict[str, dict[str, np.ndarray] | None], s_off: np.ndarray | None, alpha: float = MM_ALPHA) -> dict[str, Any]:
    """tau = max(patch on vs off slide-1 DOM medians per GL mode, slide-1 badness per session) + 1."""
    dom = {f"{on}/{off}": median_delta(phase_median(series.get(on), MMO_SLIDE1), phase_median(series.get(off), MMO_SLIDE1))
           for on, off in MMO_PAIRS}
    instrument = {name: slide1_instrument(ser, s_off, alpha) for name, ser in series.items()}
    values = [*dom.values(), *instrument.values()]
    tau = round(max(values) + 1, 2) if values and None not in values else None
    calibration = max(instrument.values()) if instrument and None not in instrument.values() else None
    return {"tau": tau, "domOnOff": dom, "instrument": instrument, "calibration": calibration}


def mmo_frame(series: dict[str, np.ndarray], row: int, bad: np.ndarray, s_off: np.ndarray, alpha: float = MM_ALPHA) -> dict[str, Any]:
    """alphaEffOverBlack = mean G / S_off's mean G: alpha over black, alpha * (2 - alpha) where the DOM and GL squares overlap.
    background = mean residual P - alpha * S_off, i.e. (1 - alpha) * B: ~0 over black, up to ~180 over the white counter."""
    top = series["pixels.top"][row].astype(float)
    mean = top.mean(axis=0)
    return {"row": int(row), "index": int(series["index"][row]), "phase": str(series["phase"][row]), "badness": round(float(bad[row]), 2),
            "background": round(float((top - alpha * s_off).mean()), 1), "mean": np.round(mean, 1).tolist(),
            "alphaEffOverBlack": round(float(mean[1] / s_off[:, 1].mean()), 3)}


def first_change_row(series: dict[str, np.ndarray], phases: tuple[str, ...]) -> int | None:
    top = series["pixels.top"].astype(float)
    changed = np.r_[False, np.abs(np.diff(top, axis=0)).max(axis=(1, 2)) > 0]
    rows = np.nonzero(changed & phase_rows(series, phases))[0]
    return int(rows[0]) if len(rows) else None


def mmo_handovers(series: dict[str, np.ndarray], bad: np.ndarray, s_off: np.ndarray) -> dict[str, Any]:
    """The first ROI_top change inside `MMO_WINDOW` (slide-1 DOM -> move) and inside slide2-handback (GL -> DOM at build 1),
    each with its predecessor frame."""
    out: dict[str, Any] = {}
    for name, phases in (("moveStart", MMO_WINDOW), ("build1", ("slide2-handback",))):
        row = first_change_row(series, phases)
        out[name] = [mmo_frame(series, r, bad, s_off) for r in (row - 1, row)] if row is not None else None
    return out


def recording_y(recording: Path, first: int, last: int, size: tuple[int, int] = HB_OBS_SIZE) -> Iterator[tuple[int, np.ndarray]]:
    """(frame index, Y plane) for frames first..last of a yuv420p recording, tv range as recorded (`-pix_fmt gray` would
    range-expand it)."""
    w, h = size
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(recording), "-vf", f"select=between(n\\,{first}\\,{last})",
           "-vsync", "0", "-frames:v", str(last - first + 1), "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"]
    frame_bytes = w * h * 3 // 2
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc:
        for index in range(first, last + 1):
            raw = proc.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                raise RuntimeError(f"{recording}: frame {index} missing")
            yield index, np.frombuffer(raw, np.uint8, w * h).reshape(h, w)


def handback_geometry(recording: Path, series: dict[str, np.ndarray], size: Any) -> dict[str, Any]:
    """HB-OBS: W2's scorer on the build-1 pair (last GL frame, first DOM frame) of the Y plane, plus a GL null (the two
    frames before) and a DOM null (the two after). The pair is the first ROI_top change in slide2-handback (`mmo_handovers`);
    without one (the fixed GL settle can equal the DOM), the consecutive handback pair whose hand-back edges move most."""
    if tuple(size or ()) != HB_OBS_SIZE:
        return {"error": f"frame size {size} is not the 1920x1080 stage"}
    handback = np.nonzero(phase_rows(series, ("slide2-handback",)))[0]
    if len(handback) < 2:
        return {"error": "fewer than two slide2-handback frames"}
    row, locator = first_change_row(series, ("slide2-handback",)), "ROI_top build-1 change"
    index = series["index"]
    if row is not None and 2 <= row < len(index) - 1:
        frames = dict(recording_y(recording, int(index[row - 2]), int(index[row + 1])))
    else:
        locator = "largest hand-back edge step in slide2-handback"
        frames = dict(recording_y(recording, int(index[max(handback[0] - 2, 0)]), int(index[min(handback[-1] + 1, len(index) - 1)])))
        edges = {int(index[r]): mm_handback_score.measure_edges(frames[int(index[r])], mm_handback_score.HANDBACK_EDGES,
                                                                white=HB_OBS_WHITE) for r in handback}
        row = max(handback[1:-1], key=lambda r: mm_handback_score.max_abs(
            mm_handback_score.deltas(edges[int(index[r - 1])], edges[int(index[r])])))
    n = [int(index[r]) for r in (row - 2, row - 1, row, row + 1)]

    def score(a: int, b: int) -> dict[str, Any]:
        return mm_handback_score.score_handback_pair(frames[a], frames[b], white=HB_OBS_WHITE)

    pair = score(n[1], n[2])
    return {"locator": locator, "gl": n[1], "dom": n[2], "max": round(pair["max"], 3), "static": round(pair["static"], 3),
            "delta": {k: round(v, 3) for k, v in pair["delta"].items()}, "weak": pair["weak"],
            "nullGL": round(score(n[0], n[1])["max"], 3), "nullDOM": round(score(n[2], n[3])["max"], 3)}


def mmo_series_checks(series: dict[str, np.ndarray] | None, s_off: np.ndarray | None, tau: float | None,
                      alpha: float = MM_ALPHA) -> dict[str, Any]:
    """Over the frames from mm-move to past build 1 (`MMO_WINDOW`): R1 frames whose ROI_top mean is within tau of S_off's;
    R2 max `mmo_badness`, every frame over tau listed (a report: the gate's limit is max(tau, `MMO_R2_FLOOR`)). R3 is folded
    into R2 (its handover frames are window frames) and reported as `handovers`."""
    if series is None or s_off is None or tau is None or not phase_rows(series, MMO_WINDOW).any():
        return {"frames": 0, "R1": None, "R2": None}
    rows = phase_rows(series, MMO_WINDOW)
    top = series["pixels.top"][rows].astype(float)
    near = np.abs(top.mean(axis=1) - s_off.mean(axis=0)).max(axis=1) <= tau
    bad = mmo_badness(series["pixels.top"], s_off, alpha)
    window = np.nonzero(rows)[0]
    over = window[bad[window] > tau]
    return {"frames": int(rows.sum()), "R1": int(near.sum()), "R1First": int(series["index"][rows][near][0]) if near.any() else None,
            "R2": round(float(bad[window].max()), 2), "R2Frame": int(series["index"][window[int(bad[window].argmax())]]),
            "R2Over": len(over), "R2Frames": [mmo_frame(series, r, bad, s_off, alpha) for r in over[:20]],
            "handovers": mmo_handovers(series, bad, s_off)}


def shot_alpha(img: np.ndarray | None, mask: np.ndarray) -> np.ndarray | None:
    return None if img is None else img[..., 3][mask].astype(float)


def mmo_key(shots: dict[str, dict[str, np.ndarray | None]], masks: dict[str, np.ndarray], alpha: float = MM_ALPHA) -> dict[str, Any]:
    """R4 on the key: per session max |M - D| alpha on ROI_top (M at settle, D on slide 1); tau_key = max(D patch on vs off per GL
    mode, |D - E_key| per session) + 1, E_key = alpha * the reference's M alpha + (1 - alpha) * that session's M empty-patch
    alpha. The patch is empty on slide 2 only (`mmo_masks`); on slide 1 other content covers it, so D cannot supply it. R4's KB is
    enforced on the G2-less twin only: once G2 is LIVE its own override makes the patch-off settle key translucent."""
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
        if d is None or m is None or ref is None:
            instrument[name] = None
        else:
            instrument[name] = float(np.abs(d - (alpha * ref + (1.0 - alpha) * pair["M"][..., 3][empty].mean())).max())
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
    cvc = mmo_cvc(series.get(MMO_CVC[0]), series.get(MMO_CVC[1]), shots.get(MMO_CVC[0]) or {}, shots.get(MMO_CVC[1]) or {},
                  masks["top"])
    check(checks, f"CvC {MMO_CVC[0]} vs {MMO_CVC[1]} before tau", cvc, cvc["max"] is not None and cvc["max"] <= MMO_CVC_MAX,
          f"<= {MMO_CVC_MAX}")
    dom_ref = phase_median(series.get(MMO_REFERENCE), MMO_SLIDE1)
    premise = None if dom_ref is None or s_off is None else round(float(np.abs(s_off.mean(axis=0) - dom_ref.mean(axis=0)).max()), 2)
    check(checks, "premise: S_off differs from the slide-1 DOM square by > tau", [premise, tau],
          None not in (premise, tau) and premise > tau, "> tau")
    calibration = cal["calibration"]
    premise_ok = calibration is None or calibration <= MMO_CALIB_MAX
    check(checks, "premise: slide-1 badness (neutral backgrounds under ROI_top)", calibration, premise_ok, f"<= {MMO_CALIB_MAX}")
    limit = None if tau is None else max(tau, MMO_R2_FLOOR)
    spread = None if s_off is None else max(float((s_off.max(axis=-1) - s_off.min(axis=-1)).min()), 1.0)
    alpha_floor = None if limit is None or spread is None else round(limit / spread, 3)
    chroma_ok = alpha_floor is None or alpha_floor <= MMO_ALPHA_FLOOR_MAX
    check(checks, "premise: S_off is coloured (R2's alphaFloor = limit / min channel spread)", alpha_floor, chroma_ok,
          f"<= {MMO_ALPHA_FLOOR_MAX}")
    r2_name = "R2: neutral-background badness (R3 folded in)"
    per: dict[str, Any] = {}
    for on, off in MMO_PAIRS:
        r_on, r_off = (mmo_series_checks(series.get(n), s_off, tau) for n in (on, off))
        per[on], per[off] = r_on, r_off
        check(checks, f"{on} frames in window", r_on["frames"], r_on["frames"] > 0, "> 0")
        check(checks, f"{on} R1: frames within tau of S_off", r_on["R1"], r_on["R1"] == 0, "== 0")
        check(checks, f"KB: {off} R1", r_off["R1"], r_off["R1"] is not None and r_off["R1"] > 0, "> 0")
        check(checks, f"{on} {r2_name}", {k: r_on.get(k) for k in ("R2", "R2Frame", "R2Over", "R2Frames")},
              None not in (r_on["R2"], limit) and r_on["R2"] <= limit, f"<= max(tau {tau}, {MMO_R2_FLOOR})")
        check(checks, f"KB: {off} {r2_name}", {k: r_off.get(k) for k in ("R2", "R2Frame", "R2Over")},
              None not in (r_off["R2"], limit) and r_off["R2"] > limit, f"> max(tau {tau}, {MMO_R2_FLOOR})")
        check(checks, f"report: {on} R3 handover frames", r_on.get("handovers"), True, enforced=False)
        v_on, v_off = key["R4"].get(on), key["R4"].get(off)
        check(checks, f"{on} R4: key alpha |M - D|", v_on, None not in (v_on, tau_key) and v_on <= tau_key, f"<= tau_key {tau_key}")
        check(checks, f"KB: {off} R4: key alpha |M - D|", v_off, None not in (v_off, tau_key) and v_off > tau_key, f"> tau_key {tau_key}",
              enforced=off == MMO_REFERENCE)
        cadence = {n: {ph: {k: ((((sessions.get(n) or {}).get("decode") or {}).get("phases") or {}).get(ph) or {}).get(k)
                            for k in ("repeatFrac", "distinctPerS")} for ph in ("mm-move", "slide2-live")} for n in (on, off)}
        check(checks, f"report: cadence {on} vs {off}", cadence, True, enforced=False)
    cvc_on = mmo_series_checks(series.get(MMO_CVC[1]), s_off, tau)
    per[MMO_CVC[1]] = cvc_on
    check(checks, f"{MMO_CVC[1]} {r2_name}", {k: cvc_on.get(k) for k in ("R2", "R2Frame", "R2Over", "R2Frames")},
          None not in (cvc_on["R2"], limit) and cvc_on["R2"] <= limit, f"<= max(tau {tau}, {MMO_R2_FLOOR})")
    check(checks, "report: shot M G2 state before/after", {n: sess.get("shotM") for n, sess in sessions.items()}, True, enforced=False)
    for name, sess in sessions.items():
        hb = (sess.get("decode") or {}).get("handbackGeometry") or {}
        fixed = mm_mode(sess) == "on"
        check(checks, f"report: {name} HB-OBS hand-back geometry max |DOM - GL| px (decision 7a)", hb,
              hb.get("max") is not None and (hb["max"] <= HB_OBS_MAX_PX) == fixed,
              f"<= {HB_OBS_MAX_PX} with the fix; stock (patch off) ~2.77", enforced=False)

    m4: list[dict[str, Any]] = []
    for name in ("g2-on", "g2-mmoff"):
        sess = sessions.get(name) or {}
        wait = sess.get("liveWait") or {}
        check(m4, f"{name}: G2 LIVE", wait, wait.get("live") is True, "LIVE (a stand-down voids the pair)")
        g2_stats_checks(m4, api_of((sess.get("reads") or {}).get("liveEnd")).get("stats") or {}, mm_mode(sess), f"{name}: ")
    live = median_delta(phase_median(series.get("g2-on"), ("slide2-live",)), phase_median(series.get("g2-mmoff"), ("slide2-live",)))
    check(m4, "report: g2-on vs g2-mmoff slide2-live ROI_top (LIVE equal)", live, True, "~0 (headless MO-4 enforces 0)", enforced=False)
    unengaged = [r for r in (handback_unengaged(sessions.get(n) or {}) for n in ("g2-on", MMO_CVC[1])) if r]
    reasons = [*unengaged,
               *([] if premise_ok else [f"slide-1 badness {calibration} > {MMO_CALIB_MAX} (premise: neutral backgrounds)"]),
               *([] if chroma_ok else [f"alphaFloor {alpha_floor} > {MMO_ALPHA_FLOOR_MAX} (premise: a coloured square)"])]
    invalid = f"MO-2 INCONCLUSIVE: {'; '.join(reasons)}" if reasons else None
    return {"MO-2": gate(checks, invalid), "MO-4": gate(m4, handback_unengaged(sessions.get("g2-on") or {})),
            "mmoCalibration": {"tau": tau, "r2Limit": limit, "alphaFloor": alpha_floor, "tauKey": tau_key, "cvc": cvc, "perSession": per,
                               "doubleFrameAlpha": round(MM_ALPHA * (2 - MM_ALPHA), 3)}}


def mmo_cef_gates(run: dict[str, Any]) -> dict[str, Any]:
    sessions = {s["session"]: s for s in run["sessions"]}
    records: dict[str, dict[str, dict[str, Any]]] = {}
    for gl in MMO_CEF_GL:
        for arm in mo3_arms(gl):
            sess = sessions.get(f"mo3-{gl}-{arm}")
            if sess is None:
                continue
            record = dict(sess.get("mo1") or {"gl": gl, "arm": arm})
            if sess.get("fatal"):
                record["error"] = sess["fatal"]
            if "seedSplice" in sess:
                record["seedSplice"] = sess["seedSplice"]
            records.setdefault(gl, {})[arm] = record
    verdict = mm_opacity_probe.score_all(records)
    checks: list[dict[str, Any]] = []
    for gl in MMO_CEF_GL:
        check(checks, f"{gl}: every arm ran", sorted((records.get(gl) or {})), set(records.get(gl) or {}) == set(mo3_arms(gl)),
              ",".join(mo3_arms(gl)))
    for gl, gates in verdict["modes"].items():
        for name, result in gates.items():
            check(checks, f"{gl} {name}", [result["verdict"], result.get("reasons")], result["verdict"] == "PASS", "PASS")
    return {"MO-3": gate(checks), "probeVerdict": verdict}


def dissolve_gates(run: dict[str, Any], decision: dict[str, Any] | None) -> dict[str, Any]:
    sessions = {s["session"]: s for s in run["sessions"]}
    checks: list[dict[str, Any]] = []
    check(checks, "every session ran", sorted(sessions), set(sessions) == set(DISSOLVE_ARMS), ",".join(DISSOLVE_ARMS))
    calibration = (sessions.get("opaque-off") or {}).get("calibration") or {"n": None, "calibration": None}
    derived = dissolve_calibration(calibration.get("n")) if calibration.get("model") in ("PASS", "FAIL") else None
    cal = derived if derived is not None and calibration.get("calibration") == asdict(derived) else None
    check(checks, "calibration (opaque-off n)", calibration, cal is not None,
          f"n <= 4: tau <= {DX2_TAU_MAX}, complement <= {DX2_COMPLEMENT_MAX}, no dip >= {DX2_NO_DIP_MIN}")
    runs = {name: (json.loads((Path(s["runDir"]) / "record.json").read_text()), dissolve_probe.RunImages(Path(s["runDir"])))
            for name, s in sessions.items() if s.get("runDir") and (Path(s["runDir"]) / "record.json").is_file()}
    held = False
    for name in DISSOLVE_ARMS:
        record = runs[name][0] if name in runs else {}
        placement = (record.get("output") or {}).get("placement") or {}
        check(checks, f"{name}: output.placement", placement,
              placement.get("grant") is None and placement.get("reason") == "attached", "grant null, reason attached")
        holders = ((record.get("dump") or {}).get("first") or {}).get("holders")
        held |= bool(holders)
        skip = name.startswith("cef-skip")
        check(checks, f"{name}: no bound holder", holders, holders == [] if skip else not holders,
              "[] (a published take)" if skip else "none")
    verdict = dissolve_probe.score_runs(runs, decision, cal or dissolve_probe.Calibration(), profile=dissolve_probe.CEF)
    for name, g in verdict["gates"].items():
        reported = g["verdict"] in ("REPORTED", "N/A")
        check(checks, name, [g["verdict"], g.get("reasons") or g.get("problems")], g["verdict"] == "PASS" or reported, "PASS",
              enforced=not reported)
    for name, outcome in verdict["arms"].items():
        check(checks, f"arm {name}", outcome, outcome == "MATCH", "MATCH")
    reasons = ([] if cal else [f"calibration: opaque-off n {calibration['n']}"]) + (
        ["round INCONCLUSIVE"] if verdict["overall"] == "INCONCLUSIVE" else [])
    invalid = f"DX-2 INCONCLUSIVE: {'; '.join(reasons)}" if reasons and not held else None
    return {"DX-2": gate(checks, invalid), "dissolveCalibration": calibration, "dissolveVerdict": verdict}


def placement_gates(run: dict[str, Any], decision: dict[str, Any] | None, *,
                    profile: dissolve_probe.Profile = dissolve_probe.CEF_PLACEMENT,
                    write_updates: bool = True,
                    product_scores: dict[Path, dict[str, Any]] | None = None,
                    pure_scores: dict[tuple[Any, ...], Any] | None = None) -> dict[str, Any]:
    sessions = {s["session"]: s for s in run["sessions"]}
    control_rows = placement_control_rows(run["sessions"])
    checks: list[dict[str, Any]] = []
    integrity_problems = []
    expected = {*profile.arms, "probe-chrome-gpu", "probe-chrome-software", *PLACEMENT_CONTROL_SESSIONS}
    check(checks, "every placement session ran", sorted(sessions), set(sessions) == expected, ",".join(sorted(expected)))
    for name in PLACEMENT_CONTROL_SESSIONS:
        session = sessions.get(name) or {}
        run_dir_value = session.get("runDir")
        rescored = calibration_gate("INCONCLUSIVE", ["control run directory missing"])
        if run_dir_value:
            run_dir = Path(run_dir_value)
            try:
                path = run_dir / "record.json"
                cached = (product_scores or {}).get(path)
                if cached is not None:
                    rescored = (cached.get("gates") or {}).get("placement-control") or calibration_gate(
                        "INCONCLUSIVE", ["cached control score missing"])
                else:
                    saved = json.loads(path.read_text())
                    rescored = score_placement_control(saved.get("placementControl"), run_dir)
            except (OSError, json.JSONDecodeError) as exc:
                rescored = calibration_gate("INCONCLUSIVE", [f"control rescore failed: {type(exc).__name__}: {exc}"])
        check(checks, f"{name}: control verdict", rescored, rescored["verdict"] == "PASS", "PASS")
    calibration = (sessions.get("opaque-off") or {}).get("calibration") or {"n": None, "calibration": None}
    derived = dissolve_calibration(calibration.get("n")) if calibration.get("model") in ("PASS", "FAIL") else None
    cal = derived if derived is not None and calibration.get("calibration") == asdict(derived) else None
    check(checks, "calibration (opaque-off n)", calibration, cal is not None,
          f"n <= 4: tau <= {DX2_TAU_MAX}, complement <= {DX2_COMPLEMENT_MAX}, no dip >= {DX2_NO_DIP_MIN}")
    run_paths = {}
    for name, session in sessions.items():
        run_dir_value = session.get("runDir")
        if not run_dir_value or name not in dissolve_probe.ARMS:
            continue
        run_dir = Path(run_dir_value)
        paths = placement_attempt_paths(run_dir, dissolve_probe.ARMS[name])
        if paths:
            run_paths[name] = paths
    runs = {}
    for name, paths in run_paths.items():
        try:
            if not all(path.is_file() for path in paths):
                continue
            runs[name] = (json.loads(paths[-1].read_text()), dissolve_probe.RunImages(paths[-1].parent))
        except (OSError, json.JSONDecodeError):
            pass
    evidence_records = []
    for name, paths in run_paths.items():
        if name not in profile.arms:
            continue
        for path in paths:
            try:
                evidence_records.append((name, path, json.loads(path.read_text())))
            except (OSError, json.JSONDecodeError):
                pass
    evidence_mode, mode_problems, anchor_problems, anchor_engines, anchor_scores = placement_launch_evidence(
        evidence_records, profile, live_probe_controls=control_rows["probe"],
        product_scores=product_scores, pure_scores=pure_scores)
    check(checks, "placement evidence composition", evidence_mode,
          evidence_mode in ("legacy", "anchors+injection"), "legacy or anchors+injection")
    integrity_problems.extend(mode_problems)
    if evidence_mode == "anchors+injection":
        integrity_problems.extend(anchor_problems)
    lut, lut_detail = dissolve_probe.launch_lut(runs, cal or dissolve_probe.Calibration(), profile=profile)
    check(checks, "CEF placement tone observation", lut_detail, lut is not None, "measured identity/analytic/table map")
    tone_summary = {"complete": False, "applied": "identity", "observed": lut_detail.get("kind"),
                    "samples": lut_detail.get("samples"), "problems": list(lut_detail.get("problems") or []),
                    "missingRows": ["second fresh CEF launch acceleration-on", "second fresh CEF launch acceleration-off",
                                    "hevc10", "Keynote-HEVC", "skin tones", "reset/invalidation controls"]}
    for name in profile.arms:
        run_dir_value = sessions.get(name, {}).get("runDir")
        run_dir = Path(run_dir_value) if run_dir_value else None
        paths = run_paths.get(name, [])
        if not paths:
            check(checks, f"{name}: placement evidence", None, False, "PASS")
        for attempt, path in enumerate(paths, 1):
            try:
                record = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                check(checks, f"{name} attempt {attempt}: placement evidence", None, False,
                      f"readable record ({type(exc).__name__})")
                continue
            integrity_problem = None
            if "integrityFailure" in record:
                integrity_failure = record["integrityFailure"]
                message = (integrity_failure.get("message") if isinstance(integrity_failure, dict)
                           else str(integrity_failure))
                integrity_problem = f"{name} attempt {attempt}: {message or 'integrity failure reported'}"
                integrity_problems.append(integrity_problem)
            encoded = record.get("placementCalibration") or {}
            integrity = encoded.get("integrity") if isinstance(encoded, dict) else None
            telemetry_ref = integrity.get("telemetry") if isinstance(integrity, dict) else None
            telemetry_changed = False
            if write_updates and isinstance(telemetry_ref, dict):
                telemetry = _read_ref_json(telemetry_ref, path.parent)
                updated_tone = {**(telemetry.get("toneRows") or {}), **tone_summary}
                if telemetry.get("toneRows") != updated_tone:
                    telemetry["toneRows"] = updated_tone
                    integrity["telemetry"] = write_placement_json(path.parent, "telemetry", telemetry)
                    telemetry_changed = True
            rescored = None if telemetry_changed else (anchor_scores.get(path) or (product_scores or {}).get(path))
            if evidence_mode == "mixed":
                rescored = {"overall": "INCONCLUSIVE", "gates": {
                    "placement-evidence": calibration_gate("INCONCLUSIVE", mode_problems)},
                    "problems": mode_problems}
            elif evidence_mode == "anchors+injection" and name not in PLACEMENT_ANCHORS:
                rescored = score_placement_injection(
                    record.get("placementInjection"), record, dissolve_probe.ARMS[name], profile,
                    anchor_problems, anchor_engines)
            elif rescored is None:
                rescored = score_placement_calibration(
                    encoded, path.parent, live_probe_controls=control_rows["probe"], pure_scores=pure_scores)
            if product_scores is not None:
                product_scores[path] = rescored
            if integrity_problem is not None:
                rescored = {**rescored, "overall": "INCONCLUSIVE",
                            "problems": [*rescored.get("problems", []), integrity_problem]}
            if evidence_mode == "anchors+injection" and rescored.get("overall") == "INCONCLUSIVE":
                evidence_problems = rescored.get("problems") or ["placement evidence was inconclusive"]
                integrity_problems.extend(
                    f"{name} attempt {attempt}: {problem}" for problem in evidence_problems
                    if problem not in anchor_problems)
            if write_updates and isinstance(record.get("placementCalibration"), dict):
                encoded["gates"] = rescored["gates"]
            if write_updates:
                path.write_text(json.dumps(record))
            label = f"{name} attempt {attempt}: placement evidence" if len(paths) > 1 else f"{name}: placement evidence"
            check(checks, label, rescored.get("overall"), rescored.get("overall") == "PASS", "PASS")
        attempts = (score_placement_capture_attempts(run_dir, dissolve_probe.ARMS[name],
                                                     cal or dissolve_probe.Calibration(), lut)
                    if run_dir is not None else calibration_gate("INCONCLUSIVE", ["run directory missing"]))
        parent_path = run_dir / "record.json" if run_dir is not None else None
        if write_updates and parent_path is not None and parent_path.is_file():
            parent = json.loads(parent_path.read_text())
            parent["captureAttemptScore"] = attempts
            parent_path.write_text(json.dumps(parent))
        check(checks, f"{name}: every capture attempt", attempts, attempts["verdict"] == "PASS", "PASS")
    for name in ("probe-chrome-gpu", "probe-chrome-software"):
        observed = "INCONCLUSIVE"
        run_dir_value = (sessions.get(name) or {}).get("runDir")
        if run_dir_value:
            run_dir = Path(run_dir_value)
            try:
                path = run_dir / "record.json"
                rescored = (product_scores or {}).get(path)
                if rescored is None:
                    record = json.loads(path.read_text())
                    rescored = score_placement_calibration(
                        record.get("placementCalibration") or {}, run_dir, pure_scores=pure_scores)
                observed = ((rescored.get("gates") or {}).get("probe-chrome-harness") or {}).get("verdict")
            except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError, AttributeError):
                pass
        check(checks, f"{name}: classifier", observed, observed == "PASS", "PASS")
    try:
        verdict = dissolve_probe.score_runs(runs, decision, cal or dissolve_probe.Calibration(), profile=profile, lut=lut)
    except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
        verdict = {"gates": {name: {"verdict": "INCONCLUSIVE", "reasons": [
            f"renderer rescore failed: {type(exc).__name__}: {exc}"]} for name in profile.controls()},
                   "arms": {}, "overall": "INCONCLUSIVE", "missing": list(profile.required(False)),
                   "profile": profile.name}
    for name, result in verdict["gates"].items():
        reported = result["verdict"] in ("REPORTED", "N/A", "NOT RUN")
        check(checks, name, [result["verdict"], result.get("reasons") or result.get("problems")],
              result["verdict"] == "PASS" or reported, "PASS", enforced=not reported)
    for name, outcome in verdict["arms"].items():
        check(checks, f"arm {name}", outcome, outcome == "MATCH", "MATCH")
    invalid = None if cal is not None else f"placement INCONCLUSIVE: calibration opaque-off n {calibration['n']}"
    placement_gate = gate(checks, invalid)
    if integrity_problems:
        placement_gate["verdict"] = "INCONCLUSIVE"
        integrity_invalid = f"placement INCONCLUSIVE: {'; '.join(integrity_problems)}"
        placement_gate["invalid"] = "; ".join(part for part in (invalid, integrity_invalid) if part)
    return {"CEF-placement": placement_gate, "dissolveCalibration": calibration, "placementVerdict": verdict}


def mmo_summary(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """MO-2 across the per-rate takes: both rates ran, and each rate's own CvC read <= 2 (it gates that take; tau and tau_key
    are per take)."""
    checks: list[dict[str, Any]] = []
    mmo = [r for r in runs if r["arm"] == "mmo"]
    if not mmo:
        return checks
    check(checks, "MO-2: a valid take per rate", sorted(r["rate"] for r in mmo if r["valid"]),
          sorted(r["rate"] for r in mmo if r["valid"]) == list(MMO_RATES), f"== {list(MMO_RATES)}")
    for rate in MMO_RATES:
        cvc = [((r.get("gates") or {}).get("mmoCalibration") or {}).get("cvc") for r in mmo if r["rate"] == rate]
        value = cvc[0].get("max") if cvc and cvc[0] else None
        check(checks, f"MO-2 CvC (rate {rate}) gates that rate", value, value is not None and value <= MMO_CVC_MAX, f"<= {MMO_CVC_MAX}")
    return checks


def placement_launch_record(run: dict[str, Any]) -> dict[str, Any]:
    sessions = run.get("sessions") if isinstance(run.get("sessions"), list) else []
    scopes = []
    cef_identities = set()
    chrome_targets = {True: set(), False: set()}
    unreadable = []
    for session in sessions:
        paths = placement_session_run_dirs(session)
        if not paths:
            unreadable.append(f"{session.get('session')}: run directory missing")
            continue
        for path in paths:
            try:
                record = json.loads((path / "record.json").read_text())
            except (OSError, json.JSONDecodeError) as exc:
                unreadable.append(f"{session.get('session')}: {type(exc).__name__}")
                continue
            scopes.append((record.get("tier"), record.get("devProfile")))
            calibration = record.get("placementCalibration")
            injection = record.get("placementInjection")
            if isinstance(calibration, dict) and calibration.get("backend") == "cef" and isinstance(calibration.get("engine"), dict):
                cef_identities.add(json.dumps(calibration["engine"], sort_keys=True))
            if isinstance(injection, dict) and isinstance(injection.get("engine"), dict):
                cef_identities.add(json.dumps(injection["engine"], sort_keys=True))
            if isinstance(calibration, dict) and calibration.get("backend") == "chrome-harness":
                identity = (calibration.get("input") or {}).get("identity") or {}
                target = identity.get("target_id")
                telemetry = _telemetry(calibration, path)
                gpu = telemetry.get("chromeGpu") if isinstance(telemetry, dict) else None
                if isinstance(gpu, bool) and target:
                    chrome_targets[gpu].add(str(target))
    expected = set()
    profile_problem = None
    try:
        tier, dev_profile, profile, legacy = placement_record_scope(run, scopes)
        expected = {*profile.arms, *PLACEMENT_CONTROL_SESSIONS, "probe-chrome-gpu", "probe-chrome-software"}
    except ValueError as exc:
        tier, dev_profile, legacy = run.get("tier") or "full", run.get("devProfile"), False
        profile_problem = str(exc)
    names = [session.get("session") for session in sessions if isinstance(session.get("session"), str)]
    scope_expected = (tier, dev_profile if tier == "dev" else None)
    wrong_scopes = [scope for scope in scopes if scope != scope_expected and not (legacy and scope == (None, None))]
    problems = list(unreadable)
    if profile_problem:
        problems.append(profile_problem)
    if set(names) != expected or len(names) != len(expected):
        problems.append(f"session set incomplete: missing={sorted(expected - set(names))}, unexpected={sorted(set(names) - expected)}")
    if wrong_scopes:
        problems.append(f"child acquisition scope mismatch: {wrong_scopes}")
    if not sessions:
        problems.append("launch has no sessions")
    if len(cef_identities) != 1:
        problems.append(f"launch has {len(cef_identities)} CEF engine identities; need exactly one")
    for gpu in (True, False):
        if len(chrome_targets[gpu]) != 1:
            problems.append(f"launch has {len(chrome_targets[gpu])} Chrome target identities for gpu={gpu}; need exactly one")
    launch_passed = run.get("devPassed") is True if tier == "dev" else run.get("passed") is True
    if run.get("valid") is not True or not launch_passed:
        problems.append("launch did not finish valid and passing")
    return {
        "launchId": run.get("placementLaunchId") or run.get("ts"), "rate": run.get("rate"), "take": run.get("take"),
        "tier": tier, "devProfile": dev_profile, "sessions": names, "cefIdentities": sorted(cef_identities),
        "chromeTargets": {str(gpu).lower(): sorted(chrome_targets[gpu]) for gpu in (True, False)},
        "problems": problems, "passed": not problems,
    }


def placement_launch_set_check(launches: list[dict[str, Any]]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, value: Any, ok: bool, limit: str) -> None:
        checks.append({"check": name, "value": value, "ok": ok, "limit": limit, "enforced": True})

    add("placement launches present", len(launches), bool(launches), ">= 1")
    tiers = [launch.get("tier") for launch in launches]
    bundle_tier = "dev" if "dev" in tiers else "full"
    add("one acquisition tier", tiers, bool(launches) and len(set(tiers)) == 1 and set(tiers) <= {"full", "dev"}, "all full or all dev")
    incomplete = {launch.get("launchId") or f"row-{index}": launch.get("problems") or []
                  for index, launch in enumerate(launches) if not launch.get("passed")}
    add("every placement launch complete", incomplete, not incomplete, "no empty, aborted, missing, or malformed launch")
    launch_ids = [launch.get("launchId") for launch in launches]
    add("fresh launch identities", launch_ids,
        bool(launches) and all(isinstance(value, str) and value for value in launch_ids) and len(set(launch_ids)) == len(launch_ids),
        "one distinct identity per launch")
    cef = [identity for launch in launches for identity in launch.get("cefIdentities") or []]
    add("fresh CEF launches", cef, bool(launches) and len(cef) == len(launches) and len(set(cef)) == len(launches),
        "one distinct CEF identity per launch")
    for gpu in (True, False):
        targets = [target for launch in launches for target in (launch.get("chromeTargets") or {}).get(str(gpu).lower(), [])]
        add(f"fresh Chrome launches gpu={gpu}", targets,
            bool(launches) and len(targets) == len(launches) and len(set(targets)) == len(launches),
            "one distinct target per launch")
    rates = sorted(launch.get("rate") for launch in launches if launch.get("rate") in MMO_RATES)
    if bundle_tier == "full":
        add("full placement rates", rates, set(rates) == set(MMO_RATES), f"both {list(MMO_RATES)}")
        rate_counts = Counter(rates)
        add("complete placement pairs", dict(rate_counts),
            rate_counts[25] == rate_counts[30] >= 1,
            "equal non-zero counts at 25 and 30 fps")
    else:
        add("full placement rates", rates, False, f"DEV cannot satisfy both-rate qualification ({list(MMO_RATES)})")
    ok = bool(checks) and all(row["ok"] for row in checks)
    return {"tier": bundle_tier, "checks": checks, "qualified": bundle_tier == "full" and ok,
            "devPassed": bundle_tier == "dev" and all(row["ok"] for row in checks if row["check"] != "full placement rates")}


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


def movie_painters(read: Any, armed: dict[str, Any]) -> list[str] | None:
    """The sources of the `<video>`s painting the movie asset, at an armed movie rect (screen px == authored px on the
    1920x1080 browser source) or carrying a tracked movie `elId`; None when the painting read is not a list or such a
    source is empty."""
    painting = read.get("painting") if isinstance(read, dict) else None
    if not isinstance(painting, list):
        return None
    gl = read.get("gl") if isinstance(read.get("gl"), dict) else {}
    pool = gl.get("pool") if isinstance(gl.get("pool"), list) else []
    tracked = {e.get("elId") for e in _movie_entries(pool, armed)} | {_carried_el_id(gl)}
    srcs = [v.get("src") for v in painting if isinstance(v, dict) and (
        matches_asset_keys(v.get("src"), armed["assetKeys"])
        or (v.get("elId") is not None and v.get("elId") in tracked)
        or (isinstance(v.get("rect"), dict) and any(rects_overlap(v["rect"], r) for r in armed["rects"])))]
    return None if any(not isinstance(s, str) or not s for s in srcs) else srcs


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
        gl = after.get("gl") if isinstance(after, dict) else None
        notes_ok = _events_readable(gl) and _events_readable(gl, "api")
        checks: list[dict[str, Any]] = []
        zone = want(after)
        check(checks, "zone retired with expected reason", zone_notes(after), zone is not None)
        kinds = g2_kinds(after) + [e["kind"] for e in gl["coreEvents"]] if notes_ok else None
        check(checks, "0 glreplay-live", None if kinds is None else kinds.count("glreplay-live"),
              kinds is not None and "glreplay-live" not in kinds, "== 0")
        painters = [movie_painters(after, armed), movie_painters((off.get("reads") or {}).get("after"), armed)]
        check(checks, "painting movie count == off", painters, None not in painters and len(painters[0]) == len(painters[1])
              and all(matches_asset_keys(s, armed["assetKeys"]) for s in painters[0] + painters[1]), "same count, all the movie")
        parity = outside_parity(sess, off, armed)
        check(checks, "P3 == off P3 outside movie rects", [parity, tau_off], None not in (parity, tau_off) and parity <= tau_off, "<= tau_off")
        remounts = remounts_after_standdown(after) if notes_ok else None
        check(checks, "0 remount-* after the stand-down", remounts, remounts == [], "[]")
        unreadable = [part for part, ok in (("notes", notes_ok), ("painting", None not in painters)) if not ok]
        return gate(checks, f"{name} unreadable {'/'.join(unreadable)}" if unreadable else None)

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
    bogus_after = ((sessions.get("fail-bogus") or {}).get("reads") or {}).get("after")
    bogus_notes = ((bogus_after or {}).get("gl") or {}).get("coreEvents") if isinstance(bogus_after, dict) else None
    check(checks, "KB: fail-bogus does not read as retired-with-expected-reason", bogus["failing"],
          bogus_zone is not None and bogus_zone["ok"] is False and isinstance(bogus_notes, list),
          "zone check FAIL on a readable note list")
    reasons = [g["invalid"] for g in (*per.values(), bogus) if g["invalid"]]
    invalid = f"M5 INCONCLUSIVE: {'; '.join(reasons)}" if reasons else None
    return {"M5": gate(checks, invalid), "perSession": {**per, "fail-bogus": bogus}, "tauOff": tau_off}


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
    slide1 = [v for v in session.get("slide1Videos") or [] if isinstance(v, dict) and matches_asset_keys(v.get("src"), ["untitled.mov"])]
    check(checks, "(a) video.loop on every slide-1 untitled.mov", [v.get("loop") for v in slide1],
          bool(slide1) and all(v.get("loop") is True for v in slide1), "all true")
    handed = session.get("handedBack")
    post_read = (session.get("reads") or {}).get("postHandback")
    post = (post_read or {}).get("gl")
    source = handed_back_source(handed, post_read)
    check(checks, "(a) video.loop on the handed-back carried element",
          {"elements": handed, "handback": handback_of(post), "source": source}, handed_back_loops(handed, post) and source is True,
          "one connected non-facade element painting untitled.mov, loop true, G2 RETIRED by a hand-off of that id")
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
    return {"precheck": gate(checks, "precheck INCONCLUSIVE: handed-back element's source unreadable" if source is None else None)}


def handback_of(read: Any) -> dict[str, Any]:
    api = (read or {}).get("api") if isinstance(read, dict) else None
    releases = _notes(read, "glreplay-release") if isinstance(read, dict) else []
    handoffs = _notes(read, "glreplay-handoff", "api") if isinstance(read, dict) else []
    module = [h.get("released") if isinstance(h.get("released"), dict) else {} for h in handoffs]
    return {"state": (api or {}).get("state"), "releases": [{"mode": r.get("mode"), "elId": r.get("elId")} for r in releases],
            "moduleReleased": [{"ok": m.get("ok"), "mode": m.get("mode"), "elId": m.get("elId")} for m in module]}


def handed_back_source(handed: Any, read: Any) -> bool | None:
    """Whether the handed-back element paints `untitled.mov` in the post-hand-back read (its `PAINTING_VIDEOS_JS` row by
    `elId`); False when no single element is named, None when its row or source cannot be read."""
    if not (isinstance(handed, list) and len(handed) == 1 and isinstance(handed[0], dict) and _el_id(handed[0].get("elId"))):
        return False
    painting = read.get("painting") if isinstance(read, dict) else None
    rows = [v for v in painting if isinstance(v, dict) and v.get("elId") == handed[0]["elId"]] if isinstance(painting, list) else []
    src = rows[0].get("src") if len(rows) == 1 else None
    return matches_asset_keys(src, ["untitled.mov"]) if isinstance(src, str) and src else None


def handed_back_loops(handed: Any, post: Any) -> bool:
    if not (isinstance(handed, list) and len(handed) == 1 and isinstance(handed[0], dict)):
        return False
    element = handed[0]
    if element.get("elId") is None or element.get("loop") is not True or element.get("isConnected") is not True or element.get("facade") is not False:
        return False
    handback = handback_of(post)
    return (handback["state"] == "RETIRED" and _handed_off(post)
            and handback["releases"] == [{"mode": "handoff", "elId": element["elId"]}]
            and handback["moduleReleased"] == [{"ok": True, "mode": "handoff", "elId": element["elId"]}])


def json_paths(tree: Path) -> set[str]:
    return {str(p.relative_to(tree)) for p in tree.rglob("*.json*") if p.is_file() and p.suffix in (".json", ".jsonp")}


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
    differing = [rel for rel in sorted(json_paths(ours) | json_paths(p2))
                 if not ((ours / rel).is_file() and (p2 / rel).is_file() and (ours / rel).read_bytes() == (p2 / rel).read_bytes())]
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
                run_session("hidden-arm", hidden_arm_script, ctx),
                run_session("mm-off", g2_script(None, armed), ctx, gl_replay="off", mm_opacity="off")]
    if arm == "mmo":
        names = [*MMO_SESSIONS, MMO_CVC[1]]
        return [run_session(name, mmo_script(MMO_SESSIONS[mmo_base(name)][0] is None), ctx, gl_replay=MMO_SESSIONS[mmo_base(name)][0],
                            mm_opacity=MMO_SESSIONS[mmo_base(name)][1], record=True) for name in names]
    if arm == "mmo-cef":
        return [run_session(f"mo3-{gl}-{name}", mo3_script(gl, name, armed), ctx, gl_replay=gl, mm_opacity=kwarg, logger=True,
                            square=name == "sq", seed=mm_opacity_probe.FSD_REASON if name in mm_opacity_probe.FSD_ARMS else None)
                for gl in MMO_CEF_GL for name, kwarg in mo3_arms(gl).items()]
    if arm == "feed":
        return [
            run_session("feed", feed_script(True), ctx, gl_replay="off", mm_feed="on"),
            run_session("feed-off", feed_script(True), ctx, gl_replay="off", mm_feed="off", mm_feed_qualify_once=True),
        ]
    if arm == "failsafe":
        return [run_session("fail-module", failsafe_script(False), ctx, seed="planUnreadable"),
                run_session("fail-zone", failsafe_script(False), ctx, seed="posterAmbiguous"),
                run_session("fail-bogus", failsafe_script(False), ctx, seed="bogusReason"),
                run_session("goto2", failsafe_script(True), ctx),
                run_session("off", failsafe_script(False), ctx, gl_replay="off"),
                run_session("off-2", failsafe_script(False), ctx, gl_replay="off")]
    if args.precheck:
        return [run_session("precheck", precheck_script(armed), ctx)]
    if arm == "dissolve":
        return [dissolve_session(name, ctx, args.decision) for name in DISSOLVE_ARMS]
    if arm == "placement":
        profile = placement_profile(args.tier, args.dev_profile)
        controls = [placement_control_session(
            name, ctx, args.decision, placement=PLACEMENT_CONTROL_SPECS[name][0],
            studio_enabled=PLACEMENT_CONTROL_SPECS[name][1], measure_control=PLACEMENT_CONTROL_SPECS[name][2],
        ) for name in PLACEMENT_CONTROL_SESSIONS]
        ctx["placementControls"] = placement_control_rows(controls)
        sessions = [*controls, chrome_placement_session("probe-chrome-gpu", ctx, gpu=True),
                    chrome_placement_session("probe-chrome-software", ctx, gpu=False)]
        for name in (arm_name for arm_name in PLACEMENT_ARMS if arm_name in profile.arms):
            session = placement_session(name, ctx, args.decision)
            sessions.append(session)
            if name == "opaque-off":
                encoded = (session.get("calibration") or {}).get("calibration")
                if isinstance(encoded, dict):
                    try:
                        ctx["placementScoringCalibration"] = dissolve_probe.Calibration(**encoded)
                    except TypeError:
                        pass
        return sessions
    return [run_session("soak", soak_script(args.soak_minutes, armed, fixture_loops(ctx["fixture"])), ctx),
            run_session("soak-off", soak_off_script, ctx, gl_replay="off")]


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
        if series is not None and masks:
            result["handbackGeometry"] = handback_geometry_safe(path, series, result.get("size"))
        return result
    except obs_cadence_decode.NotLossless as exc:
        return {"notLossless": str(exc)}
    finally:
        if not keep:
            path.unlink(missing_ok=True)


def handback_geometry_safe(recording: Path, series: dict[str, np.ndarray], size: Any) -> dict[str, Any]:
    try:
        return handback_geometry(recording, series, size)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def run_take(arm: str, rate: int, take: int, home: Path, out_dir: Path, args: argparse.Namespace,
             armed: dict[str, Any] | None) -> dict[str, Any]:
    take_started = time.monotonic()
    preparation_started = time.monotonic()
    ts = stamp()
    canvas_label, product_source = managed_obs.RATES[rate]
    source = rate if arm == "positive" else product_source
    record_dir = home / "recordings" / f"{arm}-{ts}"
    record_dir.mkdir(parents=True, exist_ok=True)
    shots = out_dir / "shots" / f"{arm}-{ts}"
    shots.mkdir(parents=True, exist_ok=True)
    scope = placement_scope(args.tier, args.dev_profile) if arm == "placement" else {}
    run: dict[str, Any] = {"arm": arm, "rate": rate, "take": take, "ts": ts, "canvas": canvas_label, "source": source,
                           **scope,
                           "launch": args.launch, "kb": args.kb, "kbSplice": args.kb_splice, "fixture": str(args.fixture),
                           "counter": fixture_counter(args.fixture), "fixtureIdentity": args.fixture_identity,
                           "soakMinutes": args.soak_minutes, "precheck": args.precheck,
                           "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip(),
                           "home": str(home), "recordDir": str(record_dir), "checks": [], "sessions": []}
    if arm == "placement":
        run["decision"] = args.decision
    engine = ManagedObs(home, record_dir=record_dir, quit_timeout_s=QUIT_TIMEOUT_S)
    user_before = tree_snapshot(USER_OBS_TREE)
    sentinel_before = tree_snapshot(engine.tree / ".sentinel")
    started = datetime.now()
    timing = run["timingS"] = {}
    pure_scores: dict[tuple[Any, ...], Any] = {}
    timing["preparation"] = round(time.monotonic() - preparation_started, 6)
    print(f"[{arm} rate {rate} source {source} {args.launch} take {take}] launching", flush=True)
    try:
        t = time.monotonic()
        creds = launch_engine(engine, rate, source, args.launch, run)
        timing["launch"] = round(time.monotonic() - t, 2)
        launch_id = f"{ts}:{engine.target_id}"
        if arm == "placement":
            run["placementLaunchId"] = launch_id
        ctx = {"endpoint": engine.cdp_endpoint, "target": engine.target_id, "rate": rate, "take": take, "creds": creds, "shots": shots,
               "fixture": args.fixture, "tag": f"{arm}{rate}{take}{ts}",
               "tier": args.tier, "devProfile": args.dev_profile, "placementLaunchId": launch_id,
               "calibration": engine.calibration_adapter(), "obsVersion": run.get("obsVersion"),
               "videoSettings": run.get("videoSettings"), "canvasFps": canvas_fps(run.get("videoSettings"), rate),
               "collectionPath": engine.tree / "basic/scenes/AK.json",
               "engineState": lambda: {k: engine.state().get(k) for k in ("state", "warnings")}}
        if arm == "feed":
            ctx["feedFacts"] = armed
        t = time.monotonic()
        run["sessions"] = sessions_for(arm, ctx, args, armed)
        timing["acquisition"] = round(time.monotonic() - t, 6)
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
    t = time.monotonic()
    if arm == "placement":
        timing["placementFinalization"] = finalize_placement_persistence(
            run["sessions"], engine.tree / "basic/scenes/AK.json", pure_scores=pure_scores)
    timing["finalization"] = round(time.monotonic() - t, 6)
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
    counter, geometry = run["counter"], movie_geometry(None if arm == "feed" else armed)
    masks = mmo_masks(armed, (1080, 1920)) if arm == "mmo" else None
    for session in run["sessions"]:
        t = time.monotonic()
        if session.get("recording"):
            session["decode"] = decode_session(session, session["recording"], rings=rings, loop_frames=None, keep=args.keep_recordings,
                                               crops_dir=shots / f"{session['session']}-crops", ring_exclude=ring_exclude,
                                               counter=counter, geometry=geometry, masks=masks,
                                               series_path=shots / f"{session['session']}-series.npz")
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

    t = time.monotonic()
    try:
        run["gates"] = arm_gates(
            arm, run, args, armed, invalid, pure_scores=pure_scores)
    except Exception:
        run["gates"] = {"error": gate([{"check": "gate computation", "value": traceback.format_exc()[-2000:], "limit": "",
                                        "ok": False, "enforced": True}])}
    if arm == "placement":
        timing["rendererScoring"] = (run["gates"].get("placementVerdict") or {}).get("timingS") or {}
    timing["scoring"] = round(time.monotonic() - t, 6)
    run["invalid"] = invalid
    run["valid"] = not invalid
    gate_ok = all(g.get("verdict") in ("PASS", "INVALID") for g in run["gates"].values() if isinstance(g, dict) and "verdict" in g)
    run["kbResult"] = kb_verdict(args.kb, arm, run["gates"]) if args.kb and not args.precheck else None
    lifecycle_ok = all(c["ok"] for c in run["checks"] if c["enforced"])
    run["passed"] = run["valid"] and lifecycle_ok and (run["kbResult"]["caught"] if run["kbResult"] else gate_ok)
    if arm == "placement" and args.tier == "dev":
        run["devPassed"] = run["passed"]
        run["passed"] = False
    dest = out_dir / "runs" / f"{arm}-{ts}.json"
    timing["total"] = round(time.monotonic() - take_started, 6)
    payload = json.dumps(run, indent=1, default=str)
    t = time.monotonic()
    dest.write_text(payload)
    timing["reportWrite"] = round(time.monotonic() - t, 6)
    timing["bytes"] = {"runJson": len(payload)}
    print_run(run, dest)
    return run


def contract_problem(run: dict[str, Any]) -> str | None:
    """Why the run's page reads are outside the producer contract (`live_evidence_contract.managed_run`), else None."""
    errors = contract.first_errors(contract.managed_run(run))
    return f"evidence contract: {'; '.join(errors)}" if errors else None


def arm_gates(arm: str, run: dict[str, Any], args: argparse.Namespace, armed: dict[str, Any] | None,
              invalid: list[str], *, pure_scores: dict[tuple[Any, ...], Any] | None = None) -> dict[str, Any]:
    problem = contract_problem(run)
    if problem:
        invalid.append(problem)
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
        gates = g2_gates(run, armed)
        invalid.extend(gates[name]["invalid"] for name in ("M1", "M2") if gates[name]["invalid"])
        return gates
    if arm == "failsafe":
        gates = failsafe_gates(run, armed)
        if gates["M5"]["invalid"]:
            invalid.append(gates["M5"]["invalid"])
        return gates
    if arm == "mmo":
        gates = mmo_gates(run, armed)
        if gates["MO-2"]["invalid"]:
            invalid.append(gates["MO-2"]["invalid"])
        return gates
    if arm == "mmo-cef":
        return mmo_cef_gates(run)
    if arm == "feed":
        return feed_gates(run, armed)
    if arm == "dissolve":
        gates = dissolve_gates(run, args.decision)
        if gates["DX-2"]["invalid"]:
            invalid.append(gates["DX-2"]["invalid"])
        return gates
    if arm == "placement":
        gates = placement_gates(
            run, args.decision, profile=placement_profile(args.tier, args.dev_profile), pure_scores=pure_scores)
        if gates["CEF-placement"]["invalid"]:
            invalid.append(gates["CEF-placement"]["invalid"])
        return gates
    if args.precheck:
        gates = precheck_gates(run, args.fixture)
        if gates["precheck"]["invalid"]:
            invalid.append(gates["precheck"]["invalid"])
        return gates
    return soak_gates(run, armed, fixture_loops(args.fixture))


def feed_gates(run: dict[str, Any], facts: dict[str, Any] | None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    sessions = {session.get("session"): session for session in run.get("sessions") or []}
    expected = [spec["id"] for spec in (facts or {}).get("verdicts") or [] if spec.get("underArtwork") is True]
    for name in ("feed", "feed-off"):
        session = sessions.get(name) or {}
        verdicts = session.get("feedVerdicts") if isinstance(session.get("feedVerdicts"), dict) else {}
        for spec_id in expected:
            carry = verdicts.get(spec_id) if isinstance(verdicts.get(spec_id), dict) else {}
            under = carry.get("underArtwork") if isinstance(carry.get("underArtwork"), dict) else {}
            if name == "feed":
                wanted = {"feedLive": True, "noRiderAboveCanvas": True, "labelsOverFeed": True,
                          "artworkAbove": True, "handbackContinuity": True}
            else:
                wanted = {"feedLive": False, "holdFrame": True, "posterHold": True,
                          "noRiderAboveCanvas": True, "artworkAbove": True, "handbackContinuity": True}
            for verdict, value in wanted.items():
                actual = (under.get(verdict) or {}).get("verdict") if isinstance(under.get(verdict), dict) else None
                check(checks, f"{name} {spec_id} {verdict}", actual, actual is value, f"is {value}")
    if not expected:
        check(checks, "under-artwork carries", 0, False, ">= 1")
    return {"feed": gate(checks)}


def timing_summary(run: dict[str, Any]) -> dict[str, Any]:
    timing = run.get("timingS") or {}
    sessions = {s.get("session"): s.get("timingS") or {} for s in run.get("sessions") or []}

    def total_of(value: Any, key: str) -> float:
        if isinstance(value, dict):
            return float(value.get(key) or 0) + sum(total_of(child, key) for name, child in value.items() if name != key)
        if isinstance(value, list):
            return sum(total_of(child, key) for child in value)
        return 0.0

    detail_keys = ("script", "decode", "recordingAnalysis", "framemd5", "collectionCopy",
                   "retirement", "pngDecode", "classification", "classifierControls", "pixelScoring", "subprocessCpu")
    detail = {key: round(sum(total_of(value, key) for value in sessions.values()) + total_of(timing, key), 6)
              for key in detail_keys}
    detail["preparationNested"] = round(
        sum(total_of(value, "preparation") for value in sessions.values()) + total_of(timing, "preparation"), 6)
    phases = {key: timing.get(key) for key in
              ("preparation", "launch", "acquisition", "quit", "finalization", "scoring", "reportWrite", "total")}
    measured = sum(float(phases.get(key) or 0) for key in
                   ("preparation", "launch", "acquisition", "quit", "finalization", "scoring", "reportWrite"))
    exclusive = None if phases["total"] is None else round(max(0.0, float(phases["total"]) - measured), 6)
    return {"arm": run.get("arm"), "take": run.get("take"), **phases, **detail,
            "obsRelease": phases["quit"], "exclusiveUnattributed": exclusive,
            "bytes": timing.get("bytes") or {}, "sessions": sessions}


def print_run(run: dict[str, Any], dest: Path) -> None:
    verdict = (f"INVALID ({'; '.join(run['invalid'])})" if not run["valid"] else
               "DEV — NOT A QUALIFICATION PASS" if run.get("devPassed") else
               "PASS" if run["passed"] else "FAIL")
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


def fixture_identity_now(fixture: Path) -> dict[str, Any] | str | None:
    try:
        return binary_counter_movie.verify_fixture(fixture)
    except SystemExit as exc:
        return str(exc)


def score_mmo(root: Path) -> int:
    """Re-score the MO-2 takes (arm mmo) under `root`/runs from their JSON, series npz and key shots; writes
    `root`/rescore-<ts>.json. Each take keeps its live validity and lifecycle checks, and is INVALID when the fixture on
    disk no longer matches its recorded identity; `verdict` combines them with the re-scored MO-2."""
    facts: dict[str, dict[str, Any]] = {}
    identity: dict[str, Any] = {}
    results = []
    for path in sorted((root / "runs").glob("mmo-*.json")):
        run = json.loads(path.read_text())
        if run.get("arm") != "mmo":
            continue
        fixture = run["fixture"]
        if fixture not in identity:
            identity[fixture] = fixture_identity_now(Path(fixture))
        invalid = [r for r in run.get("invalid") or [] if not r.startswith("MO-2 INCONCLUSIVE")]
        if identity[fixture] != run.get("fixtureIdentity"):
            invalid.append(f"fixture identity changed since the take: {identity[fixture]}")
        if problem := contract_problem(run):
            invalid.append(problem)
        if fixture not in facts:
            facts[fixture] = fixture_facts(Path(fixture))
        for sess in run["sessions"]:
            rec, ser = sess.get("recording"), load_series(sess)
            if rec and Path(rec).exists() and ser is not None and sess.get("decode"):
                sess["decode"]["handbackGeometry"] = handback_geometry_safe(Path(rec), ser, sess["decode"].get("size"))
        gates = mmo_gates(run, facts[fixture])
        mo2, cal = gates["MO-2"], gates["mmoCalibration"]
        if mo2["invalid"]:
            invalid.append(mo2["invalid"])
        lifecycle = [c["check"] for c in run.get("checks") or [] if c.get("enforced") and not c.get("ok")]
        verdict = "INVALID" if invalid else ("PASS" if mo2["verdict"] == "PASS" and not lifecycle else "FAIL")
        results.append({"run": path.name, "rate": run["rate"], "verdict": verdict, "invalid": invalid, "lifecycle": lifecycle,
                        "MO-2": mo2["verdict"], "failing": mo2["failing"], "MO-4": gates["MO-4"]["verdict"],
                        "calibration": cal, "checks": mo2["checks"]})
        print(f"[mmo rate {run['rate']} {path.stem}] {verdict}  MO-2 {mo2['verdict']} {mo2['invalid'] or mo2['failing']}"
              f"  lifecycle {lifecycle or 'ok'}  invalid {invalid or '-'}  MO-4 {results[-1]['MO-4']}"
              f"  tau {cal['tau']}  limit {cal['r2Limit']}  alphaFloor {cal['alphaFloor']}  tau_key {cal['tauKey']}",
              flush=True)
        for name, per in cal["perSession"].items():
            frames = [{k: f[k] for k in ("index", "phase", "badness", "background")} for f in per.get("R2Frames", [])[:3]]
            print(f"    {name:12s} R1 {per.get('R1')}  R2 {per.get('R2')} over tau {per.get('R2Over')}  {frames}", flush=True)
        for sess in run["sessions"]:
            hb = (sess.get("decode") or {}).get("handbackGeometry") or {}
            print(f"    {sess['session']:12s} HB-OBS max {hb.get('max')} px (report-only, {HB_OBS_MAX_PX} with the fix)  "
                  f"frames {hb.get('gl')}->{hb.get('dom')}  nulls {hb.get('nullGL')}/{hb.get('nullDOM')}  {hb.get('error') or ''}",
                  flush=True)
    dest = root / f"rescore-{stamp()}.json"
    dest.write_text(json.dumps(results, indent=1, default=str))
    print(f"-> {dest}", flush=True)
    return 0 if results and all(r["verdict"] == "PASS" for r in results) else 1


def score_placement_runs(root: Path) -> int | None:
    parent_paths = sorted(set(root.glob("**/runs/*/record.json")))
    summary_paths = sorted((root / "runs").glob("placement-*.json"))
    if not parent_paths and not summary_paths:
        return None

    summaries = []
    for path in summary_paths:
        try:
            value = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            value = {"arm": "placement", "ts": path.stem.removeprefix("placement-"), "fatal": "summary unreadable"}
        value["_path"] = path
        summaries.append(value)

    groups: dict[str, dict[str, Any]] = {}

    def fallback_group(path: Path) -> str:
        runs_parent = next((parent.parent for parent in path.parents if parent.name == "runs"), path.parent.parent)
        return runs_parent.name or str(runs_parent)

    for parent_path in parent_paths:
        try:
            parent = json.loads(parent_path.read_text())
        except (OSError, json.JSONDecodeError):
            parent = None
        acquisition = parent.get("acquisition") if isinstance(parent, dict) else None
        key = acquisition.get("launchId") if isinstance(acquisition, dict) else None
        key = str(key or fallback_group(parent_path))
        session_name = parent_path.parent.name
        paths = [parent_path]
        attempts = parent.get("captureAttempts") if isinstance(parent, dict) else None
        if isinstance(attempts, list):
            paths = []
            for index, attempt in enumerate(attempts, 1):
                relative = attempt.get("record") if isinstance(attempt, dict) else None
                paths.append(parent_path.parent / relative if isinstance(relative, str)
                             else parent_path.parent / f"attempt-{index}" / "record.json")
        group = groups.setdefault(key, {"sessions": {}, "records": [], "metadata": None})
        group["sessions"][session_name] = {"session": session_name, "runDir": str(parent_path.parent),
                                            **({"attempts": [{"attempt": index, "runDir": str(path.parent)}
                                                              for index, path in enumerate(paths, 1)]}
                                               if isinstance(attempts, list) else {})}
        for path in paths:
            group["records"].append((session_name, path))

    for summary in summaries:
        key = str(summary.get("placementLaunchId") or f"placement-{summary.get('ts')}")
        group = groups.get(key)
        if group is None:
            dirname = f"placement-{summary.get('ts')}"
            group = groups.get(dirname)
        if group is None:
            group = groups.setdefault(key, {"sessions": {}, "records": [], "metadata": None})
        group["metadata"] = summary

    results = []
    launch_records = []
    dev_renderer = []
    any_placement_record = False
    product_scores: dict[Path, dict[str, Any]] = {}
    pure_scores: dict[tuple[Any, ...], Any] = {}
    for key, group in sorted(groups.items()):
        records = []
        scopes = []
        acquisitions = []
        for session_name, path in group["records"]:
            any_placement_record = True
            try:
                record = json.loads(path.read_text())
                error = None
            except (OSError, json.JSONDecodeError) as exc:
                record = {}
                error = f"record unreadable: {type(exc).__name__}: {exc}"
            records.append((session_name, path, record, error))
            scopes.append((record.get("tier"), record.get("devProfile")))
            if isinstance(record.get("acquisition"), dict):
                acquisitions.append(record["acquisition"])
        metadata_record = group.get("metadata") if isinstance(group.get("metadata"), dict) else None
        metadata = metadata_record or {}
        try:
            tier, dev_profile, profile, _legacy = placement_record_scope(metadata, scopes)
        except ValueError:
            tier = "dev" if any(scope[0] == "dev" for scope in scopes) else (metadata.get("tier") or "full")
            dev_profile = metadata.get("devProfile")
            profile = dissolve_probe.CEF_PLACEMENT
        controls = [{"session": name, "runDir": session["runDir"]} for name, session in group["sessions"].items()
                    if name in PLACEMENT_CONTROL_SESSIONS]
        probe_controls = (placement_control_rows(controls)["probe"]
                          if {row["session"] for row in controls} == set(PLACEMENT_CONTROL_SESSIONS) else None)
        evidence_records = [(name, path, record) for name, path, record, error in records
                            if name in profile.arms and error is None]
        evidence_mode, mode_problems, anchor_problems, anchor_engines, _anchor_scores = placement_launch_evidence(
            evidence_records, profile, live_probe_controls=probe_controls,
            product_scores=product_scores, pure_scores=pure_scores)
        product_ok = True
        for session_name, path, record, error in records:
            if error:
                rescored = {"overall": "INCONCLUSIVE", "gates": {
                    "placement-evidence": calibration_gate("INCONCLUSIVE", [error])}, "problems": [error]}
                backend = None
            elif isinstance(record.get("placementControl"), dict):
                control = score_placement_control(record["placementControl"], path.parent)
                rescored = {"overall": control["verdict"], "gates": {"placement-control": control},
                            "problems": control["problems"]}
                backend = "control"
            elif session_name in profile.arms and evidence_mode == "mixed":
                rescored = {"overall": "INCONCLUSIVE", "gates": {
                    "placement-evidence": calibration_gate("INCONCLUSIVE", mode_problems)},
                    "problems": mode_problems}
                backend = None
            elif session_name in profile.arms and evidence_mode == "anchors+injection" and session_name not in PLACEMENT_ANCHORS:
                rescored = score_placement_injection(
                    record.get("placementInjection"), record, dissolve_probe.ARMS[session_name], profile,
                    anchor_problems, anchor_engines)
                backend = "harness-injection"
            elif isinstance(record.get("placementCalibration"), dict):
                calibration = record["placementCalibration"]
                rescored = product_scores.get(path)
                if rescored is None:
                    rescored = score_placement_calibration(
                        calibration, path.parent,
                        live_probe_controls=probe_controls if calibration.get("backend") == "cef" else None,
                        pure_scores=pure_scores)
                backend = calibration.get("backend")
            else:
                problem = "placement evidence missing"
                rescored = {"overall": "INCONCLUSIVE", "gates": {
                    "placement-evidence": calibration_gate("INCONCLUSIVE", [problem])}, "problems": [problem]}
                backend = None
            product_ok &= rescored["overall"] == "PASS"
            product_scores[path] = rescored
            results.append({"run": str(path.relative_to(root)), "launchId": key, "session": session_name,
                            "tier": tier, **({"devProfile": dev_profile} if tier == "dev" else {}),
                            "backend": backend, **rescored})
            print(f"[placement {key}/{session_name}] {rescored['overall']}", flush=True)

        sessions = list(group["sessions"].values())
        opaque = next((row for row in records if row[0] == "opaque-off" and not row[3]), None)
        if opaque is not None:
            try:
                summary = opaque_off_calibration(opaque[2], dissolve_probe.RunImages(opaque[1].parent))
                sessions_by_name = {session["session"]: session for session in sessions}
                sessions_by_name["opaque-off"]["calibration"] = summary
            except (OSError, KeyError, TypeError, ValueError):
                pass
        metadata_valid = (metadata_record is not None and metadata.get("valid") is True
                          and not metadata.get("fatal")
                          and all(row.get("ok") for row in metadata.get("checks") or [] if row.get("enforced")))
        recorded_passed = metadata.get("passed") is True
        live = {
            "arm": "placement", "ts": metadata.get("ts") or key, "placementLaunchId": key,
            "rate": metadata.get("rate") or next((row.get("rate") for row in acquisitions if row.get("rate") in MMO_RATES), None),
            "take": metadata.get("take") or next((row.get("take") for row in acquisitions if isinstance(row.get("take"), int)), None),
            "tier": tier, **({"devProfile": dev_profile} if tier == "dev" else {}), "sessions": sessions,
            "valid": product_ok and metadata_valid,
            "passed": product_ok and metadata_valid and (recorded_passed if tier == "full" else True),
        }
        if tier == "dev":
            gates = placement_gates(live, metadata.get("decision"), profile=profile, write_updates=False,
                                    product_scores=product_scores, pure_scores=pure_scores)
            renderer_gate = gates["CEF-placement"]
            renderer_verdict = ("INCONCLUSIVE" if renderer_gate["verdict"] == "INVALID"
                                else renderer_gate["verdict"])
            renderer_ok = renderer_verdict == "PASS"
            live["valid"] &= renderer_ok
            live["devPassed"] = product_ok and metadata_valid and renderer_ok
            live["passed"] = False
            dev_renderer.append({"launchId": key, "profile": profile.name,
                                 "recordedDevPassed": metadata.get("devPassed"),
                                 "verdict": renderer_verdict,
                                 "gate": renderer_gate, "placementVerdict": gates.get("placementVerdict")})
        launch_records.append(placement_launch_record(live))

    if not any_placement_record and not summaries:
        return None
    launch_set = placement_launch_set_check(launch_records)
    bundle_dev = launch_set["tier"] == "dev"
    product_passed = bool(results) and all(row["overall"] == "PASS" for row in results)
    dev_pixel_passed = all(row["verdict"] == "PASS" for row in dev_renderer)
    passed = product_passed and (launch_set["devPassed"] and dev_pixel_passed if bundle_dev else launch_set["qualified"])
    report = {"scope": "DEV renderer pixel rescore" if bundle_dev else "qualification product/control rescore",
              "tier": launch_set["tier"], "devPassed": passed if bundle_dev else False,
              "qualified": passed if not bundle_dev else False, "productControlPassed": product_passed,
              "launchSet": launch_set,
              "results": results, "renderer": dev_renderer}
    dest = root / f"placement-rescore-{stamp()}.json"
    dest.write_text(json.dumps(report, indent=1))
    print(f"-> {dest}", flush=True)
    if bundle_dev and passed:
        print("DEV — NOT A QUALIFICATION PASS", flush=True)
        return 10
    return 0 if passed else 1


def _recording_framemd5(path: Path, run_dir: Path) -> dict[str, Any]:
    result = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "framemd5", "-"],
        capture_output=True, timeout=120, check=True,
    )
    destination = path.with_name(f"{path.name}.framemd5")
    destination.write_bytes(result.stdout)
    return dissolve_probe.placement_file_ref(destination, run_dir)


def _retire_passing_recordings(calibration: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    framemd5_s = 0.0
    integrity = calibration.get("integrity") or {}
    telemetry_ref = integrity.get("telemetry")
    telemetry = _read_ref_json(telemetry_ref, run_dir)
    refs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    candidate = integrity.get("recording")
    analysis = telemetry.get("programRecording") if isinstance(telemetry, dict) else None
    if isinstance(candidate, dict) and isinstance(analysis, dict):
        refs.append((candidate, analysis))
    controls = telemetry.get("recordingControls") if isinstance(telemetry, dict) else None
    flash = controls.get("flash") if isinstance(controls, dict) else None
    if isinstance(flash, dict) and isinstance(flash.get("recording"), dict):
        refs.append((flash["recording"], flash))
    retired = []
    by_path: dict[str, dict[str, Any]] = {}
    for ref, owner in refs:
        dissolve_probe._placement_ref_bytes(ref, run_dir, load=False)
        path = run_dir / ref["path"]
        if ref["path"] not in by_path:
            size = path.stat().st_size
            framemd5_started = time.monotonic()
            framemd5 = _recording_framemd5(path, run_dir)
            framemd5_s += time.monotonic() - framemd5_started
            subprocess.run(["/usr/bin/trash", str(path)], capture_output=True, text=True, check=True, timeout=30)
            by_path[ref["path"]] = framemd5
            retired.append({"recording": ref["path"], "sha256": ref["sha256"], "framemd5": framemd5, "bytes": size})
        owner["framemd5"] = by_path[ref["path"]]
        ref["retained"] = False
    child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    telemetry["retention"] = {"verdict": "PASS", "recordings": retired}
    retirement_s = round(time.monotonic() - started, 6)
    detail = {
        "retirement": retirement_s,
        "framemd5": round(framemd5_s, 6),
        "subprocessCpu": round((child_after.ru_utime + child_after.ru_stime)
                                - (child_before.ru_utime + child_before.ru_stime), 6),
    }
    telemetry.setdefault("timingS", {}).update(
        retirement=retirement_s,
        framemd5=detail["framemd5"], subprocessCpu=detail["subprocessCpu"],
    )
    detail["bytes"] = sum(row["bytes"] for row in retired)
    telemetry.setdefault("bytes", {})["retiredRecordings"] = detail["bytes"]
    integrity["telemetry"] = write_placement_json(run_dir, "telemetry", telemetry)
    return detail


def placement_session_run_dirs(session: dict[str, Any]) -> list[Path]:
    attempts = session.get("attempts")
    if isinstance(attempts, list):
        return [Path(row["runDir"]) for row in attempts
                if isinstance(row, dict) and isinstance(row.get("runDir"), str)]
    return [Path(session["runDir"])] if isinstance(session.get("runDir"), str) else []


def _quit_evidence(collection_path: Path) -> dict[str, Any]:
    stat = collection_path.stat()
    collection = collection_path.read_bytes()
    value = json.loads(collection)
    if not isinstance(value, dict):
        raise ValueError("OBS scene collection is not a JSON object")
    backups = []
    for source in sorted(collection_path.parent.glob("AK.json.bak*")):
        if source.is_file():
            data = source.read_bytes()
            backups.append({"name": source.name, "digest": hashlib.sha256(data).hexdigest(), "data": data})
    return {
        "quit": {"data": collection, "digest": hashlib.sha256(collection).hexdigest(),
                 "mtimeNs": stat.st_mtime_ns, "savedByObs": True},
        "backups": backups,
    }


def finalize_placement_persistence(
        sessions: list[dict[str, Any]], collection_path: Path, *,
        pure_scores: dict[tuple[Any, ...], Any] | None = None,
        ) -> dict[str, Any]:
    rows = []
    run_dirs = [run_dir for session in sessions for run_dir in placement_session_run_dirs(session)]
    if not run_dirs:
        return {"records": rows, "bytes": 0}
    try:
        evidence = _quit_evidence(collection_path)
    except (OSError, ValueError, managed_obs.ManagedObsError) as exc:
        return {"records": rows, "bytes": 0,
                "error": f"authoritative quit evidence unavailable: {type(exc).__name__}: {exc}"}
    for run_dir in run_dirs:
        detail = _finalize_placement_persistence(run_dir, evidence, pure_scores=pure_scores)
        if detail:
            rows.append(detail)
    return {"records": rows, "bytes": sum(row.get("bytes", 0) for row in rows),
            "quitDigests": {"collection": evidence["quit"]["digest"],
                            "backups": [row["digest"] for row in evidence["backups"]]}}


def _finalize_placement_persistence(
        run_dir: Path, evidence: dict[str, Any], *,
        pure_scores: dict[tuple[Any, ...], Any] | None = None,
        ) -> dict[str, Any] | None:
    started = time.monotonic()
    record_path = run_dir / "record.json"
    if not record_path.is_file():
        return None
    record = json.loads(record_path.read_text())
    calibration = record.get("placementCalibration")
    persistence = calibration.get("persistence") if isinstance(calibration, dict) else None
    if not isinstance(persistence, dict):
        return None
    copying_started = time.monotonic()
    quit_row = evidence["quit"]
    quit_path = run_dir / "placement" / "collections" / "quit.json"
    quit_path.parent.mkdir(parents=True, exist_ok=True)
    quit_path.write_bytes(quit_row["data"])
    persistence["quit"] = dissolve_probe.placement_file_ref(
        quit_path, run_dir, mtime_ns=quit_row["mtimeNs"], saved_by_obs=quit_row["savedByObs"])
    backups = []
    for row in evidence["backups"]:
        dest = run_dir / "placement" / "collections" / row["name"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(row["data"])
        backups.append(dissolve_probe.placement_file_ref(dest, run_dir))
    persistence["backup"] = backups
    collection_copy_s = time.monotonic() - copying_started
    rescored = score_placement_calibration(calibration, run_dir, pure_scores=pure_scores)
    retirement = {}
    if rescored["overall"] == "PASS":
        retirement = _retire_passing_recordings(calibration, run_dir)
        rescored = score_placement_calibration(calibration, run_dir, pure_scores=pure_scores)
    persistence["checks"] = rescored.get("persistenceChecks", [])
    calibration["gates"] = rescored["gates"]
    detail = {"finalization": round(time.monotonic() - started, 6), "collectionCopy": round(collection_copy_s, 6),
              "framemd5": retirement.get("framemd5", 0.0), "retirement": retirement.get("retirement", 0.0),
              "subprocessCpu": retirement.get("subprocessCpu", 0.0), "bytes": retirement.get("bytes", 0)}
    record.setdefault("timingS", {})["finalization"] = detail
    record_path.write_text(json.dumps(record))
    return detail


def placement_disk_preflight(out_dir: Path, home: Path, takes: int, *,
                             profile: dissolve_probe.Profile = dissolve_probe.CEF_PLACEMENT,
                             rates: tuple[int, ...] = MMO_RATES) -> dict[str, Any]:
    attempts = sum(3 if dissolve_probe.ARMS[name].counter_strip == "distinct" else 1
                   for name in PLACEMENT_ANCHORS if name in profile.arms)
    recordings = attempts * len(rates) * takes * 2
    non_pass = recordings * PLACEMENT_RECORDING_ESTIMATE_BYTES
    working = 2 * PLACEMENT_RECORDING_ESTIMATE_BYTES
    out_free = shutil.disk_usage(out_dir).free
    home.parent.mkdir(parents=True, exist_ok=True)
    home_free = shutil.disk_usage(home.parent).free
    same_device = out_dir.stat().st_dev == home.parent.stat().st_dev
    required_out = working
    if out_free < required_out or (not same_device and home_free < working):
        raise RuntimeError(
            f"placement needs about {working / 1024 ** 3:.1f} GiB working; "
            f"a fully retained non-PASS run totals about {non_pass / 1024 ** 3:.1f} GiB; "
            f"free is {out_free / 1024 ** 3:.1f} GiB at {out_dir} and {home_free / 1024 ** 3:.1f} GiB at {home.parent}"
        )
    detail = {"profile": profile.name, "rates": list(rates), "takes": takes,
              "acquisitionPath": "anchors+injection", "recordings": recordings,
              "nonPassRetentionBytes": non_pass, "workingBytes": working, "requiredOutBytes": required_out,
              "nonPassRetentionBytesPerSession": 2 * PLACEMENT_RECORDING_ESTIMATE_BYTES,
              "outFreeBytes": out_free, "homeFreeBytes": home_free}
    print("placement disk preflight", json.dumps(detail), flush=True)
    return detail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live qualification of the managed OBS (launches OBS; one OBS at a time).")
    parser.add_argument("--arm", choices=("2x", "positive", "both", "g2", "failsafe", "soak", "mmo", "mmo-cef", "dissolve", "feed", "placement"),
                        default="both")
    parser.add_argument("--rate", type=int, choices=sorted(managed_obs.RATES),
                        help=f"placement DEV rate (default 25); full placement always runs {MMO_RATES}; default 25 otherwise; ignored for mmo")
    parser.add_argument("--takes", type=int,
                        help="placement pairs (default 1); default 2 otherwise; ignored (1) for failsafe, soak, mmo, mmo-cef, dissolve and feed")
    parser.add_argument("--tier", choices=("dev", "full"), default="full",
                        help="placement acquisition tier (default full; DEV never qualifies and exits 10 on success)")
    parser.add_argument("--dev-profile", choices=sorted(PLACEMENT_DEV_PROFILES),
                        help="placement DEV subset (default renderer; renderer or harness)")
    parser.add_argument("--launch", choices=("hidden", "shown", "projector"), default="hidden", help="shown = hidden launch, then Show OBS once ready; projector = hidden launch + a windowed program projector (eyeball)")
    parser.add_argument("--kb", choices=sorted(KB_SHAS), help="known-bad control: frozen|oldbytes (module splice), latelost (g2)")
    parser.add_argument("--fixture", type=Path, help=f"feed: Alpha/D7 root with html-player and html-unmodified; soak: "
                        f"loop root (default {SOAK_FIXTURE}); other arms: {FIXTURE} or {binary_counter_movie.BINARY_FIXTURE}")
    parser.add_argument("--precheck", action="store_true", help="soak: the loop pre-check instead of the soak")
    parser.add_argument("--soak-minutes", type=int, default=5, help=f">= {SOAK_MIN_MINUTES}; 20 before a show")
    parser.add_argument("--out", type=Path, help="writes <out>/runs/<arm>-<ts>.json, <out>/shots/ and a summary")
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME, help="scratch ManagedObs home (never under ~/Desktop)")
    parser.add_argument("--keep-recordings", action="store_true", help="keep the lossless recordings (~0.5 GB per session)")
    parser.add_argument("--score", type=Path, metavar="DIR", help="re-score saved placement or MO-2 takes under DIR/runs (no OBS)")
    parser.add_argument("--decision", type=Path, help="dissolve: the Q0b decision record JSON (L, counterEncoding, toneEncoding)")
    args = parser.parse_args(argv)
    if args.score is not None:
        root = args.score.expanduser().resolve()
        placement_status = score_placement_runs(root)
        return placement_status if placement_status is not None else score_mmo(root)
    if args.tier == "dev" and args.arm != "placement":
        parser.error("--tier dev applies to --arm placement only.")
    if args.dev_profile is not None and not (args.arm == "placement" and args.tier == "dev"):
        parser.error("--dev-profile requires --arm placement --tier dev.")
    args.dev_profile = (args.dev_profile or "renderer") if args.arm == "placement" and args.tier == "dev" else None
    if args.arm == "placement" and args.tier == "full" and args.rate is not None:
        parser.error("--rate cannot be supplied for full placement; full always runs both 25 and 30 fps.")
    if args.takes is not None and args.takes < 1:
        parser.error("--takes must be >= 1.")
    if args.decision is not None and args.arm not in ("dissolve", "placement"):
        parser.error("--decision applies to --arm dissolve or placement only.")
    if args.arm in ("dissolve", "placement") and args.fixture is not None:
        parser.error(f"--arm {args.arm} serves dissolve_probe's own decks; --fixture does not apply.")
    args.decision = json.loads(args.decision.read_text()) if args.decision else None
    args.kb_splice = None
    if args.arm == "soak":
        args.fixture = (args.fixture or SOAK_FIXTURE).expanduser().resolve()
        check_loop_frames(args.fixture)
    elif args.arm == "feed" and args.fixture is None:
        parser.error("--arm feed requires an Alpha/D7 --fixture")
    elif args.fixture is not None:
        args.fixture = args.fixture.expanduser().resolve()
        if args.arm != "feed" and not p2_family(args.fixture):
            parser.error(f"--fixture for --arm {args.arm} must be {FIXTURE} or a non-looping binary_counter_movie.py copy of it.")
    else:
        args.fixture = FIXTURE
    if args.arm in ("mmo", "mmo-cef") and fixture_counter(args.fixture) != "binary":
        parser.error(f"--arm {args.arm} needs the binary-counter fixture ({binary_counter_movie.BINARY_FIXTURE}).")
    if args.arm == "soak" and args.soak_minutes < SOAK_MIN_MINUTES:
        parser.error(f"--soak-minutes must be >= {SOAK_MIN_MINUTES} (two wrap windows, then context loss, then at least a minute after it).")
    if args.precheck and args.arm != "soak":
        parser.error("--precheck applies to --arm soak only.")
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
    args.fixture_identity = None if args.arm == "feed" else binary_counter_movie.verify_fixture(args.fixture)
    if args.kb:
        args.kb_splice = apply_kb(args.kb)
    armed = None
    if args.arm not in ("2x", "positive", "both", "dissolve", "placement"):
        armed = feed_fixture_facts(args.fixture) if args.arm == "feed" else fixture_facts(args.fixture)
        if args.arm == "feed":
            args.fixture_identity = armed["fixtureIdentity"]
            print("FEED", json.dumps([spec["id"] for spec in armed["verdicts"] if spec.get("underArtwork")]), flush=True)
        else:
            print("ARMED", json.dumps({k: armed[k] for k in ("instanceRect", "movieSlot", "overrideSlots", "assetKeys")}), flush=True)
        if args.arm == "mmo":
            top = mmo_masks(armed, (1080, 1920))["top"]
            ys, xs = np.nonzero(top)
            print("MO-2 ROI_top", [int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())], int(top.sum()), "px", flush=True)
    (args.out / "runs").mkdir(parents=True, exist_ok=True)
    arms = ("2x", "positive") if args.arm == "both" else (args.arm,)
    default_takes = 1 if args.arm == "placement" else 2
    requested_takes = args.takes if args.takes is not None else default_takes
    takes = 1 if args.arm in ("failsafe", "soak", "mmo", "mmo-cef", "dissolve", "feed") else requested_takes
    selected_rate = args.rate or 25
    args.rate = selected_rate
    rates = (MMO_RATES if args.arm == "mmo" or (args.arm == "placement" and args.tier == "full") else
             (selected_rate,))
    if args.arm == "placement":
        try:
            placement_disk_preflight(args.out, home, takes, profile=placement_profile(args.tier, args.dev_profile),
                                     rates=rates)
        except RuntimeError as exc:
            parser.error(str(exc))
    runs: list[dict[str, Any]] = []
    preparation_cache = args.out / "prep-cache" if args.arm == "placement" else None
    prep_cache_cleanup = None
    try:
        if preparation_cache is not None:
            if preparation_cache.exists():
                subprocess.run(["/usr/bin/trash", str(preparation_cache)], check=True)
            dissolve_probe.set_preparation_cache(preparation_cache)
        awake = subprocess.Popen(["caffeinate", "-dimsu", "-w", str(os.getpid())])
        try:
            for take in range(1, takes + 1):
                for arm, rate in itertools.product(arms, rates):
                    if obs_running():
                        print("An OBS is still running after the previous take; stopping.", flush=True)
                        break
                    runs.append(run_take(arm, rate, take, home, args.out, args, armed))
        finally:
            awake.terminate()
    finally:
        if preparation_cache is not None:
            dissolve_probe.set_preparation_cache(None)
            if preparation_cache.exists():
                cleanup = subprocess.run(["/usr/bin/trash", str(preparation_cache)], capture_output=True, text=True)
                if cleanup.returncode != 0:
                    prep_cache_cleanup = {
                        "returncode": cleanup.returncode,
                        "stderr": cleanup.stderr.strip(),
                    }
                    print(f"WARNING prep-cache cleanup failed: {json.dumps(prep_cache_cleanup)}", flush=True)
    summary: dict[str, Any] = {"rate": list(rates) if len(rates) > 1 else rates[0], "arms": list(arms), "takes": takes, "launch": args.launch, "kb": args.kb,
                               **(placement_scope(args.tier, args.dev_profile) if args.arm == "placement" else {}),
                               "kbSplice": args.kb_splice, "limits": LIMITS,
                               **({"prepCacheCleanup": prep_cache_cleanup} if prep_cache_cleanup is not None else {}),
                               "runs": [{"arm": r["arm"], "take": r["take"], "ts": r["ts"], "valid": r["valid"], "invalid": r["invalid"],
                                         **({k: r[k] for k in ("tier", "devProfile") if k in r}),
                                         "passed": r["passed"], **({"devPassed": r["devPassed"]} if "devPassed" in r else {}),
                                         "nativeRepeat": native_repeat(r),
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
    summary["timingS"] = [timing_summary(r) for r in runs]
    base_passed = all((r.get("devPassed") if args.arm == "placement" and args.tier == "dev" else r["passed"])
                      for r in runs) and all(c["ok"] for c in checks if c["enforced"])
    launch_set = None
    if args.arm == "placement":
        launch_set = placement_launch_set_check([placement_launch_record(run) for run in runs])
        checks.extend(launch_set["checks"])
        summary["launchSet"] = launch_set
        summary["devPassed"] = base_passed and launch_set["devPassed"]
        summary["passed"] = base_passed and launch_set["qualified"]
    else:
        summary["passed"] = base_passed
    dest = args.out / "runs" / f"summary-{stamp()}.json"
    dest.write_text(json.dumps(summary, indent=1, default=str))
    label = "PASS" if summary["passed"] else "DEV — NOT A QUALIFICATION PASS" if summary.get("devPassed") else "FAIL"
    print(f"SUMMARY {label} -> {dest}", flush=True)
    for c in checks:
        print(f"    {'ok  ' if c['ok'] else 'FAIL'} {c['check']} = {c['value']}", flush=True)
    print("TIMING " + json.dumps([{k: v for k, v in t.items() if k != "sessions"} for t in summary["timingS"]]), flush=True)
    return 0 if summary["passed"] else 10 if summary.get("devPassed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
