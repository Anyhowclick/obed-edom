"""G6 (plan `.agents/plans/keynote_live_gl_replay_g5g6.plan.md` rev 2 §4): P2 under
`--gl-replay auto`.

Verdict half: `glReplayCarry1to2` clauses (a)-(h), each forced RED ALONE against the
r3 2-pooled GREEN fixture (carried decoder 1 + sibling 2, `release.retired == [2]`),
plus `progressingIndexAfterFlip` wrap/null runs and the `carriedClock1to2`
sibling-clock defence.

Driver half: the flag-off contract (fetch JS / census JS / injected HTML byte-identical,
no `gl-replay/` root), the auto injection order, INFO only in auto, `main.js` served
through `patch_player` with the disk file untouched, the boot check, and the in-page
carry census split at the hand-off, run in node against a fake page.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import shutil
import subprocess
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from obed_edom import p2_verdict as v
from obed_edom.live_gl_replay_js import GL_REPLAY_JS
from obed_edom.live_runtime import PLAYER_SHA256

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [p for p in (str(REPO / "tests"), str(REPO / "scripts")) if p not in sys.path]

from test_p2_adversarial_driver import dissolve_live  # noqa: E402
from test_p2_adversarial_driver import p2 as drv  # noqa: E402

CARRIED, SIBLING = 1, 2

# Pinned BEFORE the G6 edits (worktree at 0ecb3e7c): the flag-off page JS must not move.
OFF_FETCH_JS_SHA256 = "238e48e6bce74408edaf131b34ac576e0478b90d3e9ec88d92898147a1e5d1f9"
OFF_CARRY_CENSUS_JS_SHA256 = "9de5ef2845830499e63a6db515f8eb7134b4f7c1e2e8c778de3545bb4190ed6e"
OFF_POOL_CENSUS_JS_SHA256 = "ac6e41307d836be111f6af8267b0c0e35653e7118dc841502633c4c6398d7812"
OFF_PLAN_SHA256 = "3f5b1e8e4b77e5af276bf9ce58d3ca8530a419082d54935c1bdafd71bc28435f"


# --------------------------------------------------------------------------- #
# GREEN fixture: r3 gate 2's shape — 2 pooled (1 carried, 2 sibling), 0 in the
# document; gate 4's hand-off (`release retired [2]`, one remount-into-authored-layer).
# --------------------------------------------------------------------------- #
def _zone(frm, to, reason, scene="#1"):
    return {"kind": "glreplay-zone", "detail": {"key": "movie1", "from": frm, "to": to, "reason": reason, "sceneHash": scene}}


def _gl_events() -> list[dict]:
    return [
        _zone("pending", "armed", "moduleReady", "#0"),
        {"kind": "glreplay-arm", "detail": {"canvasId": "12-canvas", "atScene": 2, "sceneHash": "#1"}},
        {
            "kind": "glreplay-carried",
            "detail": {
                "elId": CARRIED,
                "delta": 0.004,
                "candidates": [{"elId": CARRIED}, {"elId": SIBLING}],
                "sceneHash": "#1",
            },
        },
        {"kind": "glreplay-live", "detail": {"canvasId": "12-canvas", "epoch": 1, "frameLen": 40, "sceneHash": "#1"}},
        _zone("armed", "released", "handoff", "#2"),
        {
            "kind": "glreplay-release",
            "detail": {"ok": True, "mode": "handoff", "reason": None, "elId": CARRIED, "retired": [SIBLING], "sceneHash": "#2"},
        },
        {"kind": "glreplay-handoff", "detail": {"reason": "canvasRemoved", "completedMs": 1.7, "sceneHash": "#2"}},
        {"kind": "retire-on-start-movie", "detail": {"key": "movie1", "sceneHash": "#6"}},
    ]


def _pool_entry(el_id, ct, **over):
    entry = {
        "key": "untitled.mov",
        "movieKey": "movie1",
        "elId": el_id,
        "currentTime": ct,
        "paused": el_id != CARRIED,
        "readyState": 4,
        "ended": False,
        "inDocument": False,
        "videoWidth": 1920,
        "videoHeight": 540,
    }
    entry.update(over)
    return entry


def _pool_reads(n=4, gap_ms=350.0, rate=1.0) -> list[dict]:
    return [
        {
            "t": 10_000.0 + i * gap_ms,
            "sceneHash": "#2",
            "carried": CARRIED,
            "pool": [_pool_entry(CARRIED, 5.0 + rate * i * gap_ms / 1000.0), _pool_entry(SIBLING, 2.1)],
            "frameIndex": 40 + 11 * i,
        }
        for i in range(n)
    ]


def _gl_census(**over) -> dict:
    census = {
        "key": "movie1",
        "handoffT": 20_000.0,
        "carriedElId": CARRIED,
        "facadeElIds": [7],
        "before": {"total": 0, "sample": []},
        "afterTotal": 1,
        "after": [{"kind": "remount-into-authored-layer", "elId": CARRIED, "sceneHash": "#2", "t": 20_000.4}],
        "loScene": 1,
        "hiScene": 6,
        "eventsSeen": 300,
    }
    census.update(over)
    return census


def _index_samples() -> list[dict]:
    pre = [{"index": 10 + 4 * i, "sceneHash": "#1"} for i in range(3)]
    post = [{"index": 22 + 4 * i, "sceneHash": "#2"} for i in range(6)]
    return pre + post


def _gl_args(**over) -> dict:
    reads = _pool_reads()
    args = {
        "injected_plan": v.build_continuity_plan(True),
        "preserve_events": _gl_events(),
        "gl_carry_census": _gl_census(),
        "pool_reads": reads,
        "lingering": {"count": 0, "elIds": [], "preservedCount": 0, "paintingCount": 0, "paintingElIds": []},
        "index_samples": _index_samples(),
        "flip_index": 3,
        "sample_frame_indices": [r["frameIndex"] for r in reads],
        "pre_flip_owner_ids": [CARRIED, None, CARRIED],
        "gl_state_after": {"state": "RETIRED", "standDowns": ["canvasRemoved"]},
        "hash1": "#1",
        "hash2": "#2",
        "player_build_errors": [],
    }
    args.update(over)
    return args


def _gl(**over) -> dict:
    return v.glReplayCarry1to2(**_gl_args(**over))


def _only_red(verdict: dict, clause: str) -> None:
    assert verdict["ok"] is False
    red = sorted(k for k, ok in verdict["clauses"].items() if not ok)
    assert red == [clause], (red, verdict["reasons"])
    assert any(r.startswith(f"({clause})") for r in verdict["reasons"])


def test_gl_carry_passes_on_the_r3_two_pooled_shape():
    verdict = _gl()
    assert verdict["ok"] is True, verdict["reasons"]
    assert verdict["reasons"] == []
    assert set(verdict["clauses"]) == set("abcdefgh")
    assert verdict["carriedElId"] == CARRIED
    assert verdict["poolReads"]["pooledElIds"] == [str(CARRIED), str(SIBLING)]
    assert verdict["zone"]["expectedRetired"] == [str(SIBLING)]


def test_gl_carry_passes_with_a_lone_carried_decoder_and_nothing_retired():
    """{carried} ∪ siblings with no sibling: the release retires nothing."""
    reads = _pool_reads()
    for r in reads:
        r["pool"] = r["pool"][:1]
    events = _gl_events()
    events[5]["detail"]["retired"] = []
    assert _gl(pool_reads=reads, preserve_events=events)["ok"] is True


# ---- (a) ------------------------------------------------------------------ #
@pytest.mark.parametrize(
    "field,value",
    [("fallback", "pin"), ("atScene", v.SLIDE2_MIN_HASH + 1), ("movieKey", "movie2"), ("action", "retire")],
)
def test_gl_carry_a_needs_the_retire_fallback_gl_replay_entry(field, value):
    plan = v.build_continuity_plan(True)
    plan["boundaries"][0][field] = value
    _only_red(_gl(injected_plan=plan), "a")


# ---- (b) ------------------------------------------------------------------ #
def _events_with(mutate):
    events = copy.deepcopy(_gl_events())
    mutate(events)
    return events


def _set_detail(i, **kw):
    return lambda events: events[i]["detail"].update(kw)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda e: e.append(_zone("released", "retired", "leftDestination", "#2")), id="extra-zone-note"),
        pytest.param(lambda e: e.__setitem__(0, _zone("pending", "armed", "somethingElse", "#0")), id="arm-reason"),
        pytest.param(lambda e: e.pop(4), id="no-released-note"),
        pytest.param(_set_detail(1, sceneHash="#2"), id="arm-at-destination"),
        pytest.param(lambda e: e.insert(2, copy.deepcopy(e[1])), id="two-arms"),
        pytest.param(lambda e: e.pop(3), id="no-live"),
        pytest.param(lambda e: e.insert(4, copy.deepcopy(e[3])), id="two-lives"),
        pytest.param(_set_detail(2, delta=0.05), id="carried-delta"),
        pytest.param(_set_detail(2, delta=None), id="carried-delta-missing"),
        pytest.param(_set_detail(5, mode="retire"), id="release-retire"),
        pytest.param(_set_detail(5, ok=False), id="release-not-ok"),
        pytest.param(_set_detail(5, elId=SIBLING), id="release-other-decoder"),
        pytest.param(_set_detail(5, retired=[]), id="sibling-not-retired"),
        pytest.param(_set_detail(5, retired=[CARRIED, SIBLING]), id="carried-retired"),
        pytest.param(_set_detail(5, retired=[SIBLING, SIBLING]), id="retired-duplicate"),
        pytest.param(lambda e: e.pop(5), id="no-release"),
        pytest.param(
            lambda e: e.append({"kind": "preserve-refused", "detail": {"key": "movie1", "scene": 2, "via": "stash", "sceneHash": "#2"}}),
            id="refused-at-2",
        ),
        pytest.param(
            lambda e: e.append({"kind": "retire-boundary", "detail": {"key": "untitled.mov", "elIds": [2], "atScene": 2, "sceneHash": "#2"}}),
            id="retire-boundary-at-2",
        ),
    ],
)
def test_gl_carry_b_each_zone_or_seam_defect_is_red_alone(mutate):
    _only_red(_gl(preserve_events=_events_with(mutate)), "b")


def test_gl_carry_b_ignores_refusals_outside_slide_2_and_for_other_movies():
    extra = [
        {"kind": "preserve-refused", "detail": {"key": "movie1", "scene": 6, "via": "stash", "sceneHash": "#6"}},
        {"kind": "preserve-refused", "detail": {"key": "wa0125.mov", "scene": 2, "via": "stash", "sceneHash": "#2"}},
    ]
    assert _gl(preserve_events=_gl_events() + extra)["ok"] is True


# ---- (c) ------------------------------------------------------------------ #
@pytest.mark.parametrize(
    "over",
    [
        pytest.param({"before": {"total": 1, "sample": [{"kind": "remount-done"}]}}, id="carry-before-handoff"),
        pytest.param({"after": [], "afterTotal": 0}, id="no-remount-into-layer"),
        pytest.param(
            {
                "after": [
                    {"kind": "remount-into-authored-layer", "elId": CARRIED},
                    {"kind": "remount-into-authored-layer", "elId": CARRIED},
                ],
                "afterTotal": 2,
            },
            id="two-remount-into-layer",
        ),
        pytest.param(
            {"after": [{"kind": "remount-into-authored-layer", "elId": SIBLING}], "afterTotal": 1},
            id="remount-into-layer-for-sibling",
        ),
        pytest.param(
            {
                "after": [{"kind": "remount-into-authored-layer", "elId": CARRIED}, {"kind": "remount-done", "elId": CARRIED}],
                "afterTotal": 2,
            },
            id="remount-done-carried",
        ),
        pytest.param(
            {
                "after": [{"kind": "remount-into-authored-layer", "elId": CARRIED}, {"kind": "remount-footprint-rect", "elId": 7}],
                "afterTotal": 2,
            },
            id="footprint-rect-facade",
        ),
        pytest.param({"afterTotal": 41}, id="truncated"),
        pytest.param({"handoffT": None}, id="no-handoff"),
        pytest.param({"carriedElId": SIBLING}, id="census-other-carried"),
        pytest.param({"facadeElIds": None}, id="facades-malformed"),
        pytest.param({"before": None}, id="before-malformed"),
    ],
)
def test_gl_carry_c_each_census_defect_is_red_alone(over):
    _only_red(_gl(gl_carry_census=_gl_census(**over)), "c")


@pytest.mark.parametrize("census", [None, "x", {"error": "carry census unavailable"}])
def test_gl_carry_c_missing_census_fails_closed(census):
    _only_red(_gl(gl_carry_census=census), "c")


# ---- (d) ------------------------------------------------------------------ #
def _reads_with(i, **entry_over):
    reads = _pool_reads()
    reads[i]["pool"][0].update(entry_over)
    return reads


@pytest.mark.parametrize(
    "reads",
    [
        pytest.param(_reads_with(1, paused=True), id="carried-paused"),
        pytest.param(_reads_with(2, readyState=1), id="carried-not-ready"),
        pytest.param(_reads_with(0, inDocument=True), id="carried-in-document"),
        pytest.param(_reads_with(3, fromDom=True), id="carried-fromDom"),
        pytest.param(
            [dict(r, pool=[r["pool"][0], _pool_entry(SIBLING, 2.1, inDocument=True)]) for r in _pool_reads()],
            id="sibling-in-document",
        ),
        pytest.param(
            [dict(r, pool=[r["pool"][0], _pool_entry(SIBLING, 2.1, fromDom=True)]) for r in _pool_reads()],
            id="fromDom-sibling",
        ),
        pytest.param(
            [dict(r, pool=r["pool"] + [_pool_entry(9, 1.0, key="", movieKey=None)]) for r in _pool_reads()],
            id="unattributable-entry",
        ),
        pytest.param(
            [dict(r, pool=r["pool"] + [_pool_entry(CARRIED, 5.0)]) if i == 1 else r for i, r in enumerate(_pool_reads())],
            id="carried-twice",
        ),
        pytest.param(
            [dict(r, sceneHash="#3") if i == 3 else r for i, r in enumerate(_pool_reads())],
            id="read-past-build-1",
        ),
        pytest.param(
            [dict(r, t=r["t"] - 200.0) if i == 1 else r for i, r in enumerate(_pool_reads())],
            id="reads-too-close",
        ),
    ],
)
def test_gl_carry_d_each_pool_defect_is_red_alone(reads):
    _only_red(_gl(pool_reads=reads, sample_frame_indices=[r["frameIndex"] for r in _pool_reads()]), "d")


def test_gl_carry_d_other_movies_in_the_pool_are_tolerated():
    reads = [dict(r, pool=r["pool"] + [_pool_entry(11, 3.0, key="wa0125.mov", movieKey=None, inDocument=True)]) for r in _pool_reads()]
    assert _gl(pool_reads=reads)["ok"] is True


# ---- (e) ------------------------------------------------------------------ #
@pytest.mark.parametrize("lingering", [{"paintingCount": 1}, {"count": 0}, None, {"paintingCount": False}])
def test_gl_carry_e_a_painting_or_unread_video_on_slide_2_is_red_alone(lingering):
    _only_red(_gl(lingering=lingering), "e")


# ---- (f) ------------------------------------------------------------------ #
@pytest.mark.parametrize(
    "over",
    [
        pytest.param({"index_samples": _index_samples()[:3] + [{"index": 22}, {"index": 26}, {"index": None}, {"index": 30}]}, id="three-decoded"),
        pytest.param({"index_samples": _index_samples()[:3] + [{"index": 22}] * 5}, id="frozen-composite"),
        pytest.param({"index_samples": _index_samples()[:3] + [{"index": x} for x in (22, 26, 100, 104)]}, id="jump-64"),
        pytest.param({"index_samples": _index_samples()[:3] + [{"index": x} for x in (22, 26, 20, 24)]}, id="rewind"),
        pytest.param({"flip_index": None}, id="no-flip"),
        pytest.param({"sample_frame_indices": [40, None, None, 73]}, id="sample-frame-sparse"),
        pytest.param({"sample_frame_indices": [40, 40, 40, 40]}, id="sample-frame-frozen"),
        pytest.param({"sample_frame_indices": [40, 51, 200, 211]}, id="sample-frame-jump"),
    ],
)
def test_gl_carry_f_each_counter_defect_is_red_alone(over):
    _only_red(_gl(**over), "f")


def test_progressing_index_wraps_mod_256():
    samples = [{"index": 240}] + [{"index": x} for x in (250, 254, 2, 6)]
    got = v.progressingIndexAfterFlip(samples, 1, [253, 5, 13])
    assert got["ok"] is True
    assert got["composite"]["deltas"] == [4, 4, 4]
    assert got["sourceSampleFrame"]["deltas"] == [8, 8]


def test_progressing_index_skips_null_runs_but_counts_only_decoded_reads():
    ok = v.progressingIndexAfterFlip([{"index": x} for x in (10, None, None, 18, None, 22, 30)], 0, [1, 2, 3])
    assert ok["ok"] is True
    assert ok["composite"]["nDecoded"] == 4 and ok["composite"]["nNull"] == 3
    short = v.progressingIndexAfterFlip([{"index": x} for x in (10, None, None, 18, None, 22)], 0, [1, 2, 3])
    assert short["ok"] is False
    assert short["composite"]["reason"] == "insufficient decoded reads"


def test_progressing_index_agreement_is_report_only():
    got = v.progressingIndexAfterFlip([{"index": x} for x in (0, 1, 2, 3)], 0, [0, 60, 120])
    assert got["ok"] is True
    assert got["agreementNonGating"] == {"compositeForward": 3, "sourceForward": 120}


def test_progressing_index_step_bound_is_exclusive_at_64():
    assert v.progressingIndexAfterFlip([{"index": x} for x in (0, 63, 126, 189)], 0, [0, 1, 2])["ok"] is True
    assert v.progressingIndexAfterFlip([{"index": x} for x in (0, 64, 128, 192)], 0, [0, 1, 2])["ok"] is False


# ---- (g) ------------------------------------------------------------------ #
def _clock_reads(carried_cts, sibling_cts=None):
    reads = _pool_reads()
    for r, ct, sct in zip(reads, carried_cts, sibling_cts or [2.1] * len(reads)):
        r["pool"][0]["currentTime"] = ct
        r["pool"][1]["currentTime"] = sct
    return reads


@pytest.mark.parametrize(
    "over",
    [
        pytest.param({"pre_flip_owner_ids": [SIBLING, CARRIED]}, id="pre-flip-owner-sibling"),
        pytest.param({"pre_flip_owner_ids": [None, None]}, id="pre-flip-owner-unresolved"),
        pytest.param({"pre_flip_owner_ids": []}, id="pre-flip-owner-absent"),
        pytest.param({"pool_reads": _clock_reads([5.0, 5.35, 5.35, 6.05])}, id="clock-stall"),
        pytest.param({"pool_reads": _clock_reads([5.0, 5.7, 6.4, 7.1])}, id="clock-double-rate"),
        pytest.param({"pool_reads": _clock_reads([5.0, 5.1, 5.2, 5.3])}, id="clock-slow"),
        pytest.param({"pool_reads": _clock_reads([5.0, 5.35, None, 6.05])}, id="clock-missing"),
    ],
)
def test_gl_carry_g_each_clock_defect_is_red_alone(over):
    _only_red(_gl(**over), "g")


def test_carried_clock_reads_the_carried_decoder_never_a_sibling():
    """Sibling-clock defence: the sibling runs at wall rate while the carried one is
    frozen — the clock must be RED, not borrowed from the sibling or a max."""
    reads = _clock_reads([5.0, 5.0, 5.0, 5.0], sibling_cts=[5.0, 5.35, 5.7, 6.05])
    got = v.carriedClock1to2([CARRIED], reads, CARRIED)
    assert got["ok"] is False
    assert got["reason"] == "carried clock not strictly increasing"
    swapped = v.carriedClock1to2([SIBLING], reads, SIBLING)
    assert swapped["ok"] is True
    assert v.carriedClock1to2([CARRIED], reads, None)["reason"] == "no carried decoder"


@pytest.mark.parametrize("rate,ok", [(0.74, False), (0.76, True), (1.0, True), (1.24, True), (1.26, False)])
def test_carried_clock_rate_band(rate, ok):
    got = v.carriedClock1to2([CARRIED], _pool_reads(rate=rate), CARRIED)
    assert got["ok"] is ok
    assert got["rate"] == pytest.approx(rate)


# ---- (h) ------------------------------------------------------------------ #
@pytest.mark.parametrize(
    "over",
    [
        pytest.param({"gl_state_after": {"state": "RETIRED", "standDowns": ["canvasRemoved", "writebackFailed"]}}, id="extra-stand-down"),
        pytest.param({"gl_state_after": {"state": "RETIRED", "standDowns": ["posterAmbiguous"]}}, id="wrong-stand-down"),
        pytest.param({"gl_state_after": {"state": "LIVE", "standDowns": []}}, id="never-stood-down"),
        pytest.param({"gl_state_after": None}, id="module-absent"),
        pytest.param({"hash2": "#1"}, id="no-forward-hash"),
        pytest.param({"hash2": "#2junk"}, id="malformed-hash"),
        pytest.param({"player_build_errors": [{"kind": "player-build-error"}]}, id="build-error"),
    ],
)
def test_gl_carry_h_each_retire_or_boundary_defect_is_red_alone(over):
    _only_red(_gl(**over), "h")


def test_gl_carry_an_off_run_scored_by_it_is_red():
    """The flag-off page (zone retired `moduleAbsent`, nothing pooled, frozen counter)
    must never satisfy the auto finding."""
    off_events = [
        _zone("pending", "retired", "moduleAbsent", "#0"),
        {"kind": "retire-boundary", "detail": {"key": "movie1", "elIds": [1], "atScene": 2, "sceneHash": "#1"}},
    ]
    verdict = _gl(
        preserve_events=off_events,
        gl_carry_census=None,
        pool_reads=[dict(r, pool=[]) for r in _pool_reads()],
        index_samples=_index_samples()[:3] + [{"index": 22}] * 6,
        sample_frame_indices=[None] * 4,
        gl_state_after=None,
    )
    assert verdict["ok"] is False
    assert {k for k, ok in verdict["clauses"].items() if not ok} >= {"b", "c", "d", "f", "g", "h"}


# --------------------------------------------------------------------------- #
# Keep kinds + flag-off page JS.
# --------------------------------------------------------------------------- #
def test_gl_keep_kinds_are_sorted_and_disjoint_from_nothing_the_off_list_needs():
    assert list(v.GL_REPLAY_KEEP_KINDS) == sorted(set(v.GL_REPLAY_KEEP_KINDS))
    assert {"glreplay-arm", "glreplay-carried", "glreplay-release", "glreplay-live", "glreplay-zone"} <= set(
        v.GL_REPLAY_KEEP_KINDS
    )


def test_off_fetch_and_census_js_are_byte_identical_to_the_pre_g6_bytes():
    assert hashlib.sha256(drv._preserve_events_js(False).encode()).hexdigest() == OFF_FETCH_JS_SHA256
    assert hashlib.sha256(drv.CARRY_CENSUS_JS.encode()).hexdigest() == OFF_CARRY_CENSUS_JS_SHA256
    assert hashlib.sha256(drv.POOL_CENSUS_JS.encode()).hexdigest() == OFF_POOL_CENSUS_JS_SHA256
    assert hashlib.sha256(json.dumps(v.build_continuity_plan(True)).encode()).hexdigest() == OFF_PLAN_SHA256


def test_off_keep_list_is_unchanged_and_auto_is_the_union():
    def kept(js):
        return json.loads(js.split("const keep = ", 1)[1].split(";", 1)[0])

    off, auto = kept(drv._preserve_events_js(False)), kept(drv._preserve_events_js(True))
    assert off == list(v.PRESERVE_EVENT_KEEP_KINDS)
    assert "glreplay-arm" not in off
    assert auto == sorted(set(v.PRESERVE_EVENT_KEEP_KINDS) | set(v.GL_REPLAY_KEEP_KINDS))


def test_gl_reads_never_touch_the_oracle_handle():
    for js in (drv.GL_STATE_JS, drv.GL_SLIDE2_READ_JS, drv.GL_CARRY_CENSUS_JS, drv.GL_BOOT_CHECK_JS):
        assert "__OBED_GL_ORACLE__" not in js
        assert ".gl" not in js.replace(".glReplay", "")
        assert "markerBands" not in js and ".pause(" not in js


# --------------------------------------------------------------------------- #
# Injection + serving.
# --------------------------------------------------------------------------- #
PROBE_HTML = (
    '<html><head><script data-obed-p2-probe="4">window.__OBED_P2_PROBE__={};</script>'
    '<script src="assets/player/main.js"></script></head><body></body></html>'
)
CANVAS = {"width": 1920.0, "height": 1080.0}


def _fake_player(tmp_path: Path, name: str) -> Path:
    d = tmp_path / name
    (d / "assets" / "player").mkdir(parents=True)
    (d / "index.html").write_text(PROBE_HTML, encoding="utf-8")
    return d


def test_off_injection_is_byte_identical_to_the_pre_g6_two_calls(tmp_path):
    plan = v.build_continuity_plan(True)
    old = _fake_player(tmp_path, "old")
    dissolve_live.inject_preserve(old)
    dissolve_live.inject_continuity_plan(old, plan)
    new = _fake_player(tmp_path, "new")
    preserve, plan_inject, gl = drv._inject_player(new, plan, gl_auto=False, canvas=CANVAS)
    assert gl is None
    assert (new / "index.html").read_bytes() == (old / "index.html").read_bytes()
    html = (new / "index.html").read_text(encoding="utf-8")
    assert "data-obed-p2-gl-info" not in html and "data-obed-p2-gl-replay" not in html
    assert "__OBED_CONTINUITY_INFO__" not in html
    assert preserve["injected"] is True and plan_inject["injected"] is True


def test_auto_injection_serves_plan_core_info_gl_then_main(tmp_path):
    player = _fake_player(tmp_path, "auto")
    _, _, gl = drv._inject_player(player, v.build_continuity_plan(True), gl_auto=True, canvas=CANVAS)
    html = (player / "index.html").read_text(encoding="utf-8")
    assert gl["servedOrder"] == ["plan", "core", "info", "gl", "main"]
    assert drv._served_script_order(html) == drv.GL_SERVED_ORDER
    assert html.count("__OBED_CONTINUITY_INFO__=") == 1
    assert (
        "window.__OBED_CONTINUITY_INFO__={authoredWidth:1920,authoredHeight:1080,"
        "viewportWidth:window.innerWidth,viewportHeight:window.innerHeight,installed:true};"
    ) in html
    gl_tag = html.split('<script data-obed-p2-gl-replay="1">', 1)[1].split("</script>", 1)[0]
    assert "</script" not in gl_tag.lower()
    assert gl_tag.replace("<\\/", "</") == GL_REPLAY_JS


def test_auto_injection_refuses_a_plan_without_a_usable_gl_replay_entry(tmp_path):
    plan = v.build_continuity_plan(True)
    plan["boundaries"][0]["fallback"] = "pin"
    player = _fake_player(tmp_path, "bad")
    with pytest.raises(SystemExit, match="no usable glReplay entry"):
        drv._inject_player(player, plan, gl_auto=True, canvas=CANVAS)


def test_auto_injection_refuses_a_wrong_served_order(tmp_path, monkeypatch):
    player = _fake_player(tmp_path, "order")
    monkeypatch.setattr(drv, "GL_SERVED_ORDER", ["plan", "core", "gl", "info", "main"])
    with pytest.raises(SystemExit, match="served script order"):
        drv._inject_player(player, v.build_continuity_plan(True), gl_auto=True, canvas=CANVAS)


def _serve(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.read()


def test_the_handler_serves_patched_main_js_from_memory_and_leaves_disk_untouched(tmp_path):
    player = _fake_player(tmp_path, "srv")
    disk = b"var original = 1;"
    (player / drv.PLAYER_MAIN_JS).write_bytes(disk)
    patched = b"var patched = 1;"
    httpd, base = _serve(drv._player_handler(player, patched))
    try:
        assert _get(base + drv.PLAYER_MAIN_JS) == patched
        assert _get(base + drv.PLAYER_MAIN_JS + "?v=1") == patched
        assert _get(base + "index.html") == PROBE_HTML.encode()
    finally:
        httpd.shutdown()
    assert (player / drv.PLAYER_MAIN_JS).read_bytes() == disk
    httpd, base = _serve(drv._player_handler(player, None))
    try:
        assert _get(base + drv.PLAYER_MAIN_JS) == disk
    finally:
        httpd.shutdown()


def test_patched_main_js_refuses_an_unsupported_player(tmp_path):
    player = _fake_player(tmp_path, "unsupported")
    (player / drv.PLAYER_MAIN_JS).write_bytes(b"not the pinned player")
    with pytest.raises(SystemExit, match="not supported"):
        drv._patched_main_js(player)


def test_patched_main_js_uses_live_runtime_on_the_pinned_player(tmp_path, monkeypatch):
    player = _fake_player(tmp_path, "pinned")
    raw = b"...UC=new Eg,UC.displayManager.showWaitingIndicator()..."
    (player / drv.PLAYER_MAIN_JS).write_bytes(raw)
    monkeypatch.setattr(drv, "patch_player", lambda b: b + b"/*patched*/")
    patched, meta = drv._patched_main_js(player)
    assert patched == raw + b"/*patched*/"
    assert meta["mainJsSha256"] == hashlib.sha256(raw).hexdigest()
    assert meta["playerSha256"] == PLAYER_SHA256
    assert (player / drv.PLAYER_MAIN_JS).read_bytes() == raw


def _boot_check(**over):
    check = {
        "order": ["plan", "core", "info", "gl", "main"],
        "obedLive": True,
        "runtimeVersion": 2,
        "glVersion": 1,
        "glState": "IDLE",
        "info": {"authoredWidth": 1920, "authoredHeight": 1080, "installed": True},
    }
    check.update(over)
    return check


def test_boot_check_green():
    assert drv._gl_boot_ok(_boot_check()) is True


@pytest.mark.parametrize(
    "over",
    [
        {"order": ["plan", "core", "gl", "main"]},
        {"order": ["plan", "core", "gl", "info", "main"]},
        {"obedLive": False},
        {"runtimeVersion": None},
        {"glVersion": None},
        {"glState": "RETIRED"},
        {"info": None},
    ],
)
def test_boot_check_fails_closed(over):
    assert drv._gl_boot_ok(_boot_check(**over)) is False
    assert drv._gl_boot_ok(None) is False


def test_gl_replay_mode_defaults_off_and_rejects_unknown(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["p2"])
    assert drv._gl_replay_mode() == "off"
    monkeypatch.setattr(sys, "argv", ["p2", "--gl-replay", "auto"])
    assert drv._gl_replay_mode() == "auto"
    monkeypatch.setattr(sys, "argv", ["p2", "--gl-replay=on"])
    with pytest.raises(SystemExit, match="--gl-replay"):
        drv._gl_replay_mode()


def test_off_writes_to_out_and_auto_only_under_gl_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(drv, "OUT", tmp_path)
    assert drv._out_root(False) == tmp_path
    assert drv._out_root(True) == tmp_path / "gl-replay"


def test_run_refuses_an_unknown_gl_replay_mode_before_any_destructive_work(tmp_path, monkeypatch):
    import asyncio

    marker = tmp_path / "runs" / "marker.txt"
    marker.parent.mkdir()
    marker.write_text("prior")
    monkeypatch.setattr(drv, "OUT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["p2", "--gl-replay", "bogus"])
    calls = []
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(drv, "file_identity", lambda *a, **k: calls.append(a))
    with pytest.raises(SystemExit, match="--gl-replay"):
        asyncio.run(drv._run(tmp_path / "html-player"))
    assert calls == []
    assert marker.read_text() == "prior"


# --------------------------------------------------------------------------- #
# sampleFrame counter decode.
# --------------------------------------------------------------------------- #
def _sample_frame(level: int, w: int = 320, h: int = 90) -> dict:
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[:, :, :] = ((np.arange(w) // 3) % 2 * 255)[None, :, None]
    arr[: round(h * 48 / 540), : round(w * 120 / 1920)] = level
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG", quality=70)
    import base64

    return {"ok": True, "dataURL": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}


@pytest.mark.parametrize("level", [16, 90, 200, 235])
def test_sample_frame_counter_decodes_within_two(level):
    got = drv._sample_frame_index(_sample_frame(level))
    assert got is not None and abs(got - level) <= 2


@pytest.mark.parametrize("frame", [None, {"ok": False, "reason": "no-video-pixels"}, {"ok": True}])
def test_sample_frame_counter_is_none_without_pixels(frame):
    assert drv._sample_frame_index(frame) is None


# --------------------------------------------------------------------------- #
# The in-page census, run in node against a fake page.
# --------------------------------------------------------------------------- #
def _run_census(events, videos=()):
    harness = (
        f"const events = {json.dumps(events)};\n"
        f"const videos = {json.dumps(list(videos))}.map((v) => v.facadeFor === undefined"
        " ? {__obedElId: v.elId} : {__obedElId: v.elId, __obedFacadeFor: {__obedElId: v.facadeFor}});\n"
        "global.window = {__OBED_P2_PRESERVE__: {events}};\n"
        "global.document = {querySelectorAll: () => videos};\n"
        f"console.log(JSON.stringify({drv.GL_CARRY_CENSUS_JS}));\n"
    )
    out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _ev(kind, t, **detail):
    return {"kind": kind, "t": t, "detail": detail}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_gl_carry_census_splits_at_the_released_zone_note():
    events = [
        _ev("glreplay-carried", 10, elId=1, delta=0.0, sceneHash="#1"),
        _ev("glreplay-zone", 50, key="movie1", to="released", sceneHash="#2"),
        _ev("remount-into-authored-layer", 51, elId=1, key="untitled.mov", sceneHash="#2"),
        _ev("remount-done", 80, elId=7, sceneHash="#3"),
        _ev("remount-done", 90, elId=1, sceneHash="#6"),
        _ev("remount-done", 5, elId=3, key="wa0125.mov", sceneHash="#1"),
    ]
    census = _run_census(events, videos=[{"elId": 7, "facadeFor": 1}, {"elId": 8}])
    assert census["handoffT"] == 50
    assert census["carriedElId"] == 1
    assert census["facadeElIds"] == [7]
    assert census["before"]["total"] == 0
    assert census["afterTotal"] == 2
    assert [(e["kind"], e["elId"]) for e in census["after"]] == [
        ("remount-into-authored-layer", 1),
        ("remount-done", 7),
    ]
    verdict = v.glCarryCensusVerdict(census, 1)
    assert verdict["ok"] is False
    assert "facade" in verdict["reason"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_gl_carry_census_counts_a_pre_handoff_carry_and_a_missing_handoff():
    events = [
        _ev("glreplay-carried", 10, elId=1, delta=0.0, sceneHash="#1"),
        _ev("remount-done", 20, elId=1, sceneHash="#1"),
    ]
    census = _run_census(events)
    assert census["handoffT"] is None
    assert census["before"]["total"] == 1
    assert census["afterTotal"] == 0
    assert v.glCarryCensusVerdict(census, 1)["reason"] == "no hand-off in the census"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_gl_carry_census_green_shape_passes_the_verdict():
    events = [
        _ev("glreplay-carried", 10, elId=1, delta=0.0, sceneHash="#1"),
        _ev("glreplay-zone", 50, key="movie1", to="released", sceneHash="#2"),
        _ev("remount-into-authored-layer", 51, elId=1, key="untitled.mov", sceneHash="#2"),
    ]
    census = _run_census(events)
    assert v.glCarryCensusVerdict(census, 1)["ok"] is True
