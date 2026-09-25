"""G6 (plan `git show ed7ff63c:.agents/plans/keynote_live_gl_replay_g5g6.plan.md` rev 2 §4): P2 under
`--gl-replay auto`.

Verdict half: `glReplayCarry1to2` clauses (a)-(h), each forced RED ALONE against the
r3 2-pooled GREEN fixture (carried decoder 1 + sibling 2, `release.retired == [2]`),
plus `progressingIndexAfterFlip` wrap/null runs and the `carriedClock1to2`
sibling-clock defence. GL-replay (c) (plan `git show ed7ff63c:.agents/plans/keynote_live_gl_replay_c.plan.md` §4, §7, §8):
clause (f) gates a third series, the G2 `probe(rect)` readback counter, and the A7′
probe-vs-`sampleFrame` pairing scores the instrument.

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
from obed_edom import live_runtime
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
            "glProbeIndex": 41 + 11 * i,
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
        "handoffScene": 2,
        "malformedTotal": 0,
        "gatedTotal": 1,
        "gated": [{"kind": "remount-into-authored-layer", "elId": CARRIED, "sceneHash": "#2", "t": 20_000.4}],
        "afterTotal": 19,
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


def _live_state(it=100, up=90, **over):
    stats = {"epoch": 1, "iter": it, "uploads": up, "glErrors": 0, "loopMode": "rvfc"}
    stats.update(over.pop("stats", {}))
    state = {"state": "LIVE", "standDowns": [], "stats": stats, "sceneHash": "#2?currentSlide=1", "t": 8000.0 + it}
    state.update(over)
    return state


def _live_states():
    return [_live_state(), _live_state(it=160, up=150)]


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
        "gl_probe_indices": [r["glProbeIndex"] for r in reads],
        "pre_flip_owner_ids": [CARRIED, None, CARRIED],
        "gl_states_s2": _live_states(),
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


@pytest.mark.parametrize(
    "states",
    [
        pytest.param([_live_state()], id="one-read"),
        pytest.param(None, id="no-reads"),
        pytest.param([_live_state(), _live_state(state="RETIRED", it=160, up=150)], id="not-live"),
        pytest.param([_live_state(), _live_state(standDowns=["contextLost"], it=160, up=150)], id="stand-down"),
        pytest.param([_live_state(), _live_state(it=160, up=150, stats={"glErrors": 1})], id="gl-error"),
        pytest.param([_live_state(), _live_state(it=160, up=150, stats={"epoch": 2})], id="epoch-changed"),
        pytest.param([_live_state(), _live_state(it=100, up=150)], id="iter-stalled"),
        pytest.param([_live_state(), _live_state(it=160, up=90)], id="uploads-stalled"),
        pytest.param([_live_state(), {"state": "LIVE", "standDowns": []}], id="stats-missing"),
        pytest.param([_live_state(), _live_state(it=160, up=150, sceneHash="#3")], id="read-on-wrong-scene"),
        pytest.param([_live_state(), _live_state(it=160, up=150, sceneHash="#2junk")], id="read-hash-malformed"),
        pytest.param([_live_state(), _live_state(it=160, up=150, t=None)], id="read-clock-missing"),
        pytest.param([_live_state(), _live_state(it=160, up=150, t=8000.0)], id="read-clock-not-increasing"),
        pytest.param(
            [_live_state(stats={"epoch": None}), _live_state(it=160, up=150, stats={"epoch": None})],
            id="epoch-missing-in-both",
        ),
        pytest.param(
            [_live_state(stats={"epoch": True}), _live_state(it=160, up=150, stats={"epoch": True})],
            id="epoch-not-an-int",
        ),
    ],
)
def test_gl_carry_b_needs_the_module_live_at_settled_slide_2(states):
    """A historical `glreplay-live` note is not enough: the module must be LIVE and
    advancing across two slide-2 reads."""
    _only_red(_gl(gl_states_s2=states), "b")


def test_gl_carry_b_accepts_a_raf_loop_mode_snapshot_while_uploads_run():
    states = [_live_state(stats={"loopMode": "raf"}), _live_state(it=160, up=150, stats={"loopMode": "raf"})]
    assert _gl(gl_states_s2=states)["ok"] is True


def test_gl_carry_b_ignores_refusals_outside_slide_2_and_for_other_movies():
    extra = [
        {"kind": "preserve-refused", "detail": {"key": "movie1", "scene": 6, "via": "stash", "sceneHash": "#6"}},
        {"kind": "preserve-refused", "detail": {"key": "wa0125.mov", "scene": 2, "via": "stash", "sceneHash": "#2"}},
    ]
    assert _gl(preserve_events=_gl_events() + extra)["ok"] is True


# ---- (c) ------------------------------------------------------------------ #
def _into(el_id=CARRIED, scene="#2"):
    return {"kind": "remount-into-authored-layer", "elId": el_id, "sceneHash": scene}


def test_gl_carry_c_later_build_re_placements_are_report_only():
    """G6-P2 r1 (live): after the hand-off `released` is pin, and builds #3-#5
    re-place the carried decoder in its authored layer 18 more times. Only the
    hand-off scene's remount is gated."""
    census = _gl_census(afterTotal=35)
    assert _gl(gl_carry_census=census)["ok"] is True


@pytest.mark.parametrize(
    "over",
    [
        pytest.param({"before": {"total": 1, "sample": [{"kind": "remount-done"}]}}, id="carry-before-handoff"),
        pytest.param({"gated": [], "gatedTotal": 0}, id="no-remount-into-layer"),
        pytest.param(
            {"gated": [_into(), _into()], "gatedTotal": 2},
            id="two-remount-into-layer-at-handoff",
        ),
        pytest.param({"gated": [_into(SIBLING)], "gatedTotal": 1}, id="remount-into-layer-for-sibling"),
        pytest.param({"gated": [_into(scene="#3")], "gatedTotal": 1}, id="remount-into-layer-only-later"),
        pytest.param(
            {"gated": [_into(), {"kind": "remount-done", "elId": CARRIED, "sceneHash": "#4"}], "gatedTotal": 2},
            id="remount-done-carried",
        ),
        pytest.param(
            {"gated": [_into(), {"kind": "remount-footprint-rect", "elId": 7, "sceneHash": "#3"}], "gatedTotal": 2},
            id="footprint-rect-facade",
        ),
        pytest.param({"gatedTotal": 41}, id="truncated"),
        pytest.param({"handoffScene": None}, id="no-handoff-scene"),
        pytest.param({"handoffScene": -1}, id="handoff-hash-malformed"),
        pytest.param({"malformedTotal": 1}, id="malformed-event-hash"),
        pytest.param({"malformedTotal": None}, id="malformed-count-missing"),
        pytest.param({"gated": [_into(scene="#2junk")], "gatedTotal": 1}, id="remount-hash-malformed"),
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
        pytest.param({"gl_probe_indices": [41, None, None, 74]}, id="gl-probe-sparse"),
        pytest.param({"gl_probe_indices": [41, 41, 41, 41]}, id="gl-probe-frozen"),
        pytest.param({"gl_probe_indices": [41, 52, 201, 212]}, id="gl-probe-jump"),
        pytest.param({"gl_probe_indices": [None] * 4}, id="gl-probe-no-reads"),
        pytest.param({"gl_probe_indices": []}, id="gl-probe-absent"),
    ],
)
def test_gl_carry_f_each_counter_defect_is_red_alone(over):
    _only_red(_gl(**over), "f")


def test_gl_carry_f_the_gl_series_gates_even_with_both_other_series_green():
    """N5 known-bad shape (frozen-upload): the decoder and `sampleFrame` keep running
    while the GL composite freezes. (f) must fail naming the GL series only."""
    verdict = _gl(gl_probe_indices=[41, 41, 41, 41])
    _only_red(verdict, "f")
    progress = verdict["progressingIndexAfterFlip"]
    assert progress["composite"]["ok"] is True and progress["sourceSampleFrame"]["ok"] is True
    assert progress["glProbe"]["reason"] == "counter never advanced"
    (reason,) = [r for r in verdict["reasons"] if r.startswith("(f)")]
    assert "glProbe 'counter never advanced'" in reason
    assert "composite" not in reason and "sampleFrame" not in reason


def test_gl_carry_f_reason_names_every_failing_series():
    verdict = _gl(sample_frame_indices=[None] * 4, gl_probe_indices=[None] * 4)
    (reason,) = [r for r in verdict["reasons"] if r.startswith("(f)")]
    assert "sampleFrame 'insufficient decoded reads'" in reason
    assert "glProbe 'insufficient decoded reads'" in reason
    assert "composite" not in reason


def test_progressing_index_wraps_mod_256():
    samples = [{"index": 240}] + [{"index": x} for x in (250, 254, 2, 6)]
    got = v.progressingIndexAfterFlip(samples, 1, [253, 5, 13], [254, 6, 14])
    assert got["ok"] is True
    assert got["composite"]["deltas"] == [4, 4, 4]
    assert got["sourceSampleFrame"]["deltas"] == [8, 8]
    assert got["glProbe"]["deltas"] == [8, 8]


def test_progressing_index_skips_null_runs_but_counts_only_decoded_reads():
    ok = v.progressingIndexAfterFlip([{"index": x} for x in (10, None, None, 18, None, 22, 30)], 0, [1, 2, 3], [2, 3, 4])
    assert ok["ok"] is True
    assert ok["composite"]["nDecoded"] == 4 and ok["composite"]["nNull"] == 3
    short = v.progressingIndexAfterFlip([{"index": x} for x in (10, None, None, 18, None, 22)], 0, [1, 2, 3], [2, 3, 4])
    assert short["ok"] is False
    assert short["composite"]["reason"] == "insufficient decoded reads"


def test_progressing_index_agreement_is_report_only():
    got = v.progressingIndexAfterFlip([{"index": x} for x in (0, 1, 2, 3)], 0, [0, 60, 120], [1, 2, 62])
    assert got["ok"] is True
    assert got["agreementNonGating"] == {"compositeForward": 3, "sourceForward": 120, "glForward": 61}


def test_progressing_index_step_bound_is_exclusive_at_64():
    assert v.progressingIndexAfterFlip([{"index": x} for x in (0, 63, 126, 189)], 0, [0, 1, 2], [0, 63, 126])["ok"] is True
    assert v.progressingIndexAfterFlip([{"index": x} for x in (0, 64, 128, 192)], 0, [0, 1, 2], [0, 1, 2])["ok"] is False
    assert v.progressingIndexAfterFlip([{"index": x} for x in (0, 63, 126, 189)], 0, [0, 1, 2], [0, 64, 128])["ok"] is False


@pytest.mark.parametrize(
    "gl_probe_indices,ok",
    [([1, 2, 3], True), ([1, None, 3], False), ([1, 2], False), ([None, None, None], False), (None, False)],
)
def test_progressing_index_needs_three_decoded_gl_probe_reads(gl_probe_indices, ok):
    got = v.progressingIndexAfterFlip([{"index": x} for x in (0, 1, 2, 3)], 0, [0, 1, 2], gl_probe_indices)
    assert got["ok"] is ok
    assert got["glProbe"]["ok"] is ok


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
        pytest.param({"hash1": "#0", "hash2": "#2"}, id="jump-0-to-2"),
        pytest.param({"hash1": "#1", "hash2": "#3"}, id="jump-1-to-3"),
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
        gl_probe_indices=[None] * 4,
        gl_state_after=None,
        gl_states_s2=[None, None],
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


def test_the_probe_read_is_the_one_oracle_carve_out_and_touches_only_probe():
    """Plan §4 carve-out from the g5g6 "no oracle in arms" rule: `GL_PROBE_READ_JS` is
    the only P2 read of `__OBED_GL_ORACLE__`, and it may call `handle.probe` once and
    nothing else (never `.gl`, `markerBands`, `pause` or `resume`)."""
    import re

    js = drv.GL_PROBE_READ_JS
    assert js.count("window.__OBED_GL_ORACLE__") == 1
    assert js.count(".probe(") == 1
    assert ".gl" not in js
    assert "markerBands" not in js and ".pause(" not in js and ".resume(" not in js
    handle = re.search(r"const (\w+) = window\.__OBED_GL_ORACLE__;", js).group(1)
    assert set(re.findall(rf"\b{handle}\.(\w+)", js)) == {"probe"}
    assert "__ROI__" in js


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


@pytest.mark.parametrize("mm_opacity", [True, False])
def test_patched_main_js_refuses_an_unsupported_player(tmp_path, mm_opacity):
    player = _fake_player(tmp_path, "unsupported")
    (player / drv.PLAYER_MAIN_JS).write_bytes(b"not the pinned player")
    with pytest.raises(SystemExit, match="not supported"):
        drv._patched_main_js(player, mm_opacity=mm_opacity)


def test_patched_main_js_uses_live_runtime_on_the_pinned_player(tmp_path, monkeypatch):
    player = _fake_player(tmp_path, "pinned")
    raw = b"...UC=new Eg,UC.displayManager.showWaitingIndicator()..."
    (player / drv.PLAYER_MAIN_JS).write_bytes(raw)
    seen = []
    monkeypatch.setattr(drv, "patch_player", lambda b, *, mm_opacity: seen.append(mm_opacity) or b + b"/*patched*/")
    patched, meta = drv._patched_main_js(player, mm_opacity=False)
    assert seen == [False]
    assert patched == raw + b"/*patched*/"
    assert meta["mainJsSha256"] == hashlib.sha256(raw).hexdigest()
    assert meta["playerSha256"] == PLAYER_SHA256
    assert meta["mmOpacity"] is False
    assert (player / drv.PLAYER_MAIN_JS).read_bytes() == raw


# --------------------------------------------------------------------------- #
# `--mm-opacity auto|off` (plan `keynote_live_mm_opacity.plan.md` rev 4 §8, W5).
# `auto` (default) serves `patch_player(raw, mm_opacity=True)` in every arm; `off`
# keeps the pre-W5 bytes per arm: stock from disk for the non-GL arms (fast, slow,
# bridge-off), `patch_player(raw, mm_opacity=False)` under `--gl-replay auto`. The
# wait profile and `--disable-bridge34` never reach `_served_main_js`, so the three
# non-GL arms share the `gl_auto=False` rows below.
# --------------------------------------------------------------------------- #
def _synthetic_pinned_player(tmp_path: Path, monkeypatch, name: str) -> tuple[Path, bytes]:
    raw = (
        b"before;" + live_runtime._ANCHOR + b";"
        + b";".join(before for before, _ in live_runtime._MM_OPACITY_REPLACEMENTS)
        + b";after"
    )
    monkeypatch.setattr(live_runtime, "PLAYER_SHA256", hashlib.sha256(raw).hexdigest())
    player = _fake_player(tmp_path, name)
    (player / drv.PLAYER_MAIN_JS).write_bytes(raw)
    return player, raw


def _hook_only(raw: bytes) -> bytes:
    """The pre-W5 GL-arm bytes, built independently of `patch_player`."""
    return raw.replace(
        live_runtime._ANCHOR,
        b"UC=new Eg," + live_runtime._INSTALL + b",UC.displayManager.showWaitingIndicator()",
    )


def test_mm_opacity_mode_defaults_auto_and_rejects_unknown(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["p2"])
    assert drv._mm_opacity_mode() == "auto"
    monkeypatch.setattr(sys, "argv", ["p2", "--mm-opacity", "off"])
    assert drv._mm_opacity_mode() == "off"
    monkeypatch.setattr(sys, "argv", ["p2", "--mm-opacity=auto"])
    assert drv._mm_opacity_mode() == "auto"
    monkeypatch.setattr(sys, "argv", ["p2", "--mm-opacity", "on"])
    with pytest.raises(SystemExit, match="--mm-opacity"):
        drv._mm_opacity_mode()


def test_run_refuses_an_unknown_mm_opacity_mode_before_any_destructive_work(tmp_path, monkeypatch):
    import asyncio

    marker = tmp_path / "runs" / "marker.txt"
    marker.parent.mkdir()
    marker.write_text("prior")
    monkeypatch.setattr(drv, "OUT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["p2", "--mm-opacity", "bogus"])
    calls = []
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(drv, "file_identity", lambda *a, **k: calls.append(a))
    with pytest.raises(SystemExit, match="--mm-opacity"):
        asyncio.run(drv._run(tmp_path / "html-player"))
    assert calls == []
    assert marker.read_text() == "prior"


def test_off_non_gl_arms_serve_the_stock_main_js_from_disk(tmp_path, monkeypatch):
    player, raw = _synthetic_pinned_player(tmp_path, monkeypatch, "off-stock")
    main_js, meta = drv._served_main_js(player, gl_auto=False, mm_opacity=False)
    assert main_js is None
    assert meta == {"mainJsSha256": hashlib.sha256(raw).hexdigest(), "patchedMainJsSha256": None, "mmOpacity": False}
    httpd, base = _serve(drv._player_handler(player, main_js))
    try:
        assert _get(base + drv.PLAYER_MAIN_JS) == raw
    finally:
        httpd.shutdown()


def test_off_gl_arm_serves_the_hook_only_bytes(tmp_path, monkeypatch):
    player, raw = _synthetic_pinned_player(tmp_path, monkeypatch, "off-gl")
    main_js, meta = drv._served_main_js(player, gl_auto=True, mm_opacity=False)
    assert main_js == _hook_only(raw)
    assert meta["mmOpacity"] is False
    assert meta["patchedMainJsSha256"] == hashlib.sha256(main_js).hexdigest()
    for _, after in live_runtime._MM_OPACITY_REPLACEMENTS:
        assert after not in main_js


@pytest.mark.parametrize("gl_auto", [False, True], ids=["fast-slow-bridge-off", "gl-replay"])
def test_auto_serves_the_mm_opacity_patch_in_every_arm(tmp_path, monkeypatch, gl_auto):
    player, raw = _synthetic_pinned_player(tmp_path, monkeypatch, f"auto-{gl_auto}")
    main_js, meta = drv._served_main_js(player, gl_auto=gl_auto, mm_opacity=True)
    assert main_js == live_runtime.patch_player(raw, mm_opacity=True)
    assert b"window, '__obedLive'" in main_js
    for before, after in live_runtime._MM_OPACITY_REPLACEMENTS:
        assert main_js.count(after) == 1
    assert meta == {
        "mainJsSha256": hashlib.sha256(raw).hexdigest(),
        "playerSha256": PLAYER_SHA256,
        "patchedMainJsSha256": hashlib.sha256(main_js).hexdigest(),
        "mmOpacity": True,
    }
    httpd, base = _serve(drv._player_handler(player, main_js))
    try:
        assert _get(base + drv.PLAYER_MAIN_JS) == main_js
    finally:
        httpd.shutdown()
    assert (player / drv.PLAYER_MAIN_JS).read_bytes() == raw


@pytest.mark.parametrize(
    "webgl, canvas, mm_opacity, painted, exercised",
    [
        (True, {"present": True, "inStage": True}, True, True, True),
        (True, {"present": True, "inStage": True}, False, True, False),
        (False, {"present": False, "inStage": False}, True, False, False),
        (True, {"present": False, "inStage": False}, True, False, False),
        (False, {"present": True, "inStage": True}, True, False, False),
        (True, None, True, False, False),
    ],
    ids=["gl-patched", "gl-stock-mm", "no-webgl-css-path", "webgl-but-no-mm-canvas", "canvas-without-webgl", "probe-failed"],
)
def test_main_js_report_says_whether_the_arm_exercised_the_mm_patch(webgl, canvas, mm_opacity, painted, exercised):
    """Review F3: the non-GL arms launch Chrome with `--disable-gpu`, so serving the MM patch
    there proves nothing unless the arm had WebGL AND the 1->2 move painted through `#0-canvas`."""
    meta = {"mainJsSha256": "a", "patchedMainJsSha256": "b", "mmOpacity": mm_opacity}
    report = drv._main_js_report(meta, webgl=webgl, mm_canvas=canvas)
    assert report == {
        **meta,
        "webglAvailable": webgl,
        "mmCanvas1to2": canvas,
        "mmPaintedViaWebgl": painted,
        "mmPatchExercised": exercised,
    }


def test_mm_canvas_probe_reads_the_stage_canvas_without_making_a_context():
    """A `getContext` call on `#0-canvas` would create a context on a CSS-path page; the probe must only look."""
    assert "getElementById('0-canvas')" in drv.MM_CANVAS_JS
    assert "closest('#stage')" in drv.MM_CANVAS_JS
    assert "getContext" not in drv.MM_CANVAS_JS


class _ChromeLaunched(Exception):
    pass


@pytest.mark.parametrize("gl_auto", [False, True], ids=["fast-slow-bridge-off", "gl-replay"])
def test_freeze_bracket_chrome_follows_the_gl_flag_not_the_served_bytes(tmp_path, monkeypatch, gl_auto):
    """Under `--mm-opacity auto` the non-GL arms also serve patched bytes, so the bracket
    must not infer `--gl-replay auto` (Chrome without `--disable-gpu`) from `main_js`."""
    import asyncio

    seen = []

    def fake_chrome(profile, *, gl_auto):
        seen.append(gl_auto)
        raise _ChromeLaunched

    monkeypatch.setattr(drv, "_chrome", fake_chrome)
    monkeypatch.setattr(sys, "argv", ["p2"])
    player = tmp_path / "player"
    player.mkdir()
    runs = tmp_path / "runs"
    runs.mkdir()
    with pytest.raises(_ChromeLaunched):
        asyncio.run(
            drv._run_freeze_bracket(
                player, runs, drv.WAIT_PROFILES["fast"], "fast", main_js=b"x", gl_auto=gl_auto
            )
        )
    assert seen == [gl_auto]


def _boot_check(**over):
    check = {
        "order": ["plan", "core", "info", "gl", "main"],
        "webgl": True,
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
        {"glVersion": 2},
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


def _fake_export(root: Path) -> Path:
    d = root / "html-unmodified"
    d.mkdir(parents=True)
    (d / "index.html").write_text("shared", encoding="utf-8")
    return d


def test_auto_reuse_strips_a_private_copy_never_the_shared_export(tmp_path, monkeypatch):
    monkeypatch.setattr(drv, "OUT", tmp_path)
    shared = _fake_export(tmp_path)
    root = drv._out_root(True)
    stale = root / "html-unmodified"
    stale.mkdir(parents=True)
    (stale / "old.txt").write_text("stale")
    got = drv._unmodified_export(root, reuse=True, gl_auto=True)
    assert got == root / "html-unmodified"
    assert not (got / "old.txt").exists()
    (got / "index.html").write_text("stripped", encoding="utf-8")
    assert (shared / "index.html").read_text(encoding="utf-8") == "shared"


def test_off_and_fresh_exports_use_the_root_export(tmp_path, monkeypatch):
    monkeypatch.setattr(drv, "OUT", tmp_path)
    assert drv._unmodified_export(tmp_path, reuse=True, gl_auto=False) == tmp_path / "html-unmodified"
    assert drv._unmodified_export(tmp_path / "gl-replay", reuse=False, gl_auto=True) == tmp_path / "gl-replay" / "html-unmodified"
    assert not (tmp_path / "gl-replay").exists()


def test_sample_frame_roi_is_index_patch_roi_scaled_to_the_frame():
    """Derived, not tuned: at the movie footprint's own size it reproduces INDEX_PATCH_ROI's
    offset and size exactly."""
    x, y, w, h = drv._sample_frame_index_roi(drv.MOVIE_ROI[2], drv.MOVIE_ROI[3])
    assert (x + drv.MOVIE_ROI[0], y + drv.MOVIE_ROI[1], w, h) == drv.INDEX_PATCH_ROI
    x, y, w, h = drv._sample_frame_index_roi(320, 90)
    assert x + w <= 320 * 120 / 1920 and y + h <= 90 * 48 / 540


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
        _ev("remount-into-authored-layer", 70, elId=1, key="untitled.mov", sceneHash="#3"),
        _ev("remount-done", 80, elId=7, sceneHash="#3"),
        _ev("remount-done", 90, elId=1, sceneHash="#6"),
        _ev("remount-done", 5, elId=3, key="wa0125.mov", sceneHash="#1"),
    ]
    census = _run_census(events, videos=[{"elId": 7, "facadeFor": 1}, {"elId": 8}])
    assert census["handoffT"] == 50
    assert census["carriedElId"] == 1
    assert census["facadeElIds"] == [7]
    assert census["before"]["total"] == 0
    assert census["handoffScene"] == 2
    assert census["afterTotal"] == 3
    assert [(e["kind"], e["elId"]) for e in census["gated"]] == [
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
        _ev("remount-scheduled", 60, elId=1, sceneHash="#3"),
        _ev("remount-into-authored-layer", 61, elId=1, key="untitled.mov", sceneHash="#3"),
        _ev("dom-swap", 62, elId=1, sceneHash="#4"),
    ]
    census = _run_census(events)
    assert census["afterTotal"] == 4 and census["gatedTotal"] == 1
    assert v.glCarryCensusVerdict(census, 1)["ok"] is True


# --------------------------------------------------------------------------- #
# The auto Chrome (G6-P2 r1 root cause): WebGL present, page kept visible.
# --------------------------------------------------------------------------- #
def _spawn_argv(cls, monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **k: seen.append(argv) or object())
    c = cls(Path("/bin/chrome"), tmp_path / "p")
    c._spawn()
    return [a for a in seen[0] if not a.startswith("--remote-debugging-port=")]


def test_auto_chrome_argv_is_the_p2_argv_minus_disable_gpu_only(monkeypatch, tmp_path):
    """Under `--disable-gpu` headless Chrome has no WebGL: the player takes its
    non-WebGL path and G2 never sees a context (r1: ARM-PRE, canvasId null)."""
    base = _spawn_argv(drv.ChromeCdp, monkeypatch, tmp_path)
    auto = _spawn_argv(drv.GlReplayChromeCdp, monkeypatch, tmp_path)
    assert "--disable-gpu" in base
    assert auto == [a for a in base if a != "--disable-gpu"]


def test_chrome_class_follows_the_mode(tmp_path):
    assert type(drv._chrome(tmp_path / "a", gl_auto=False)) is drv.ChromeCdp
    assert type(drv._chrome(tmp_path / "b", gl_auto=True)) is drv.GlReplayChromeCdp


def test_boot_check_requires_webgl():
    assert drv._gl_boot_ok(_boot_check(webgl=False)) is False
    assert drv._gl_boot_ok(_boot_check(webgl=None)) is False


def _probe_result(level: int = 121, w: int = 41, h: int = 14, alpha: int = 255, **over) -> dict:
    pixels = [level, level, level, alpha] * (w * h)
    result = {
        "ok": True,
        "epoch": 1,
        "iter": 200,
        "t": 10_000.0,
        "vt": 5.0,
        "rect": {"x": 111, "y": 795, "w": w, "h": h},
        "width": w,
        "height": h,
        "alphaMin": alpha,
        "pixels": pixels,
    }
    result.update(over)
    return result


class _ReadChrome:
    def __init__(self, probe=None):
        self.calls = []
        self.probe = _probe_result() if probe is None else probe

    async def evaluate(self, js, await_promise=False):
        if js.startswith("(async () => {") and "__OBED_GL_ORACLE__" in js:
            self.calls.append(("probe", await_promise))
            return copy.deepcopy(self.probe)
        self.calls.append(("read", await_promise))
        return {"t": 1.0, "sceneHash": "#2", "carried": 1, "pool": [], "frame": _sample_frame(120)}

    async def screenshot(self):
        self.calls.append(("shot", None))
        return np.zeros((1080, 1920, 4), dtype=np.uint8)


def _probe_js():
    return drv._gl_probe_read_js(v.build_continuity_plan(True))


def test_slide2_reads_pair_every_sample_frame_with_a_probe_then_a_screenshot(tmp_path, monkeypatch):
    """Auto read order (plan §7): `sampleFrame` then the awaited probe, both before the
    screenshot, so the A7′ pair is taken one tick apart."""
    import asyncio

    monkeypatch.setattr(drv, "GL_POOL_READ_GAP_S", 0.0)
    chrome = _ReadChrome()
    reads = asyncio.run(drv._gl_slide2_reads(chrome, tmp_path, _probe_js()))
    assert chrome.calls == [("read", False), ("probe", True), ("shot", None)] * drv.GL_POOL_READS_N
    assert all(abs(r["frameIndex"] - 120) <= 2 for r in reads)
    assert all(r["glProbeIndex"] == 121 for r in reads)
    assert all("dataURL" not in r["frameMeta"] for r in reads)
    for r in reads:
        assert "pixels" not in r["glProbeMeta"]
        assert r["glProbeMeta"]["alphaMin"] == 255 and r["glProbeMeta"]["rect"] == {"x": 111, "y": 795, "w": 41, "h": 14}
    for i in range(drv.GL_POOL_READS_N):
        assert (tmp_path / f"gl-slide2-{i}.png").is_file()
        assert (tmp_path / f"gl-sample-frame-{i}.jpg").is_file()
        assert (tmp_path / f"gl-probe-{i}.png").is_file()


def test_slide2_reads_record_a_failed_probe_as_a_null_reading(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setattr(drv, "GL_POOL_READ_GAP_S", 0.0)
    chrome = _ReadChrome(probe={"ok": False, "reason": "timeout"})
    reads = asyncio.run(drv._gl_slide2_reads(chrome, tmp_path, _probe_js()))
    assert all(r["glProbeIndex"] is None for r in reads)
    assert all(r["glProbeMeta"] == {"ok": False, "reason": "timeout"} for r in reads)
    assert not any(tmp_path.glob("gl-probe-*.png"))


def test_probe_roi_is_the_index_patch_roi_of_the_injected_instance_rect():
    """The ROI is computed in Python from the injected plan's entry and substituted as a
    literal (plan §5): `index_patch_roi_for(instanceRect)` == (111, 795, 41, 14)."""
    from obed_edom.html_alpha_probe import index_patch_roi_for

    plan = v.build_continuity_plan(True)
    (entry,) = [b for b in plan["boundaries"] if b.get("action") == "glReplay"]
    x, y, w, h = index_patch_roi_for(entry["instanceRect"])
    assert (x, y, w, h) == (111, 795, 41, 14)
    js = drv._gl_probe_read_js(plan)
    assert "__ROI__" not in js
    assert json.dumps({"x": x, "y": y, "w": w, "h": h}) in js
    assert js == drv.GL_PROBE_READ_JS.replace("__ROI__", json.dumps({"x": x, "y": y, "w": w, "h": h}))


@pytest.mark.parametrize("level", [0, 16, 121, 235, 255])
def test_gl_probe_counter_decodes_the_flat_patch(level, tmp_path):
    assert drv._gl_probe_index(_probe_result(level), tmp_path / "p.png") == level
    saved = np.asarray(Image.open(tmp_path / "p.png"))
    assert saved.shape == (14, 41, 4)


def test_gl_probe_pixels_are_read_top_down():
    """`pixels` rows are top-down (plan §4): row 0 is the ROI's top row."""
    w, h = 3, 2
    pixels = [10, 10, 10, 255] * w + [200, 200, 200, 255] * w
    arr = drv._gl_probe_array(_probe_result(width=w, height=h, pixels=pixels))
    assert arr.shape == (2, 3, 4)
    assert arr[0, 0, 0] == 10 and arr[1, 0, 0] == 200


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(None, id="no-result"),
        pytest.param({"ok": False, "reason": "standDown"}, id="stand-down"),
        pytest.param({"ok": False, "reason": "noProbe"}, id="no-probe"),
        pytest.param(_probe_result(alpha=254), id="alpha-below-255"),
        pytest.param(_probe_result(alphaMin=None), id="alpha-missing"),
        pytest.param(_probe_result(pixels=[121, 121, 121, 255] * 10), id="short-buffer"),
        pytest.param(_probe_result(width=0, pixels=[]), id="empty"),
        pytest.param(_probe_result(pixels=None), id="no-pixels"),
        pytest.param(_probe_result(ok="true"), id="ok-not-true"),
        pytest.param(_probe_result(width=True, height=1, pixels=[121, 121, 121, 255]), id="bool-width"),
        pytest.param(_probe_result(width=1, height=True, pixels=[121, 121, 121, 255]), id="bool-height"),
        pytest.param(_probe_result(width=1, height=1, pixels=[121, 121, True, 255]), id="bool-pixel"),
        pytest.param(_probe_result(width=1, height=1, pixels=[121, 121, 256, 255]), id="pixel-above-255"),
        pytest.param(_probe_result(width=1, height=1, pixels=[121, 121, -1, 255]), id="pixel-negative"),
        pytest.param(_probe_result(width=1, height=1, pixels=[121, 121, 121.0, 255]), id="float-pixel"),
        pytest.param(_probe_result(width=1, height=1, pixels=[121, 121, "121", 255]), id="string-pixel"),
        pytest.param(_probe_result(width=1, height=1, pixels=[121, 121, None, 255]), id="null-pixel"),
        pytest.param(_probe_result(width=1, height=1, pixels=[121, 121, 121, 254]), id="computed-alpha-below-255"),
    ],
)
def test_a_failed_probe_read_is_none_never_a_raise(result):
    """Consumer rule (plan §4): `ok: false`, `alphaMin` < 255 or a missing probe is a
    failed read."""
    assert drv._gl_probe_index(result) is None


def test_a_non_flat_probe_patch_decodes_to_none():
    w, h = 41, 14
    pixels = [v for i in range(w * h) for v in ((i % 2) * 255,) * 3 + (255,)]
    assert drv._gl_probe_index(_probe_result(width=w, height=h, pixels=pixels)) is None


def _run_probe_read(handle_js: str, *, fast_timeout: bool = False, window_js: str | None = None) -> dict:
    harness = (
        (
            "global.setTimeout = function (f, ms) { global.__timeoutMs = ms; f(); return 0; };\n"
            if fast_timeout else ""
        )
        + (window_js or f"global.window = {{__OBED_GL_ORACLE__: {handle_js}}};") + "\n"
        + f"Promise.resolve({_probe_js()}).then((r) => {{"
        " console.log(JSON.stringify({result: r, timeoutMs: global.__timeoutMs === undefined ? null : global.__timeoutMs,"
        " calls: global.__calls || []})); process.exit(0); });\n"
    )
    out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, check=False, timeout=20)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_probe_read_js_passes_the_roi_literal_and_returns_the_probe_result():
    got = _run_probe_read(
        "{rect: {x: 0}, probe: function (r) { (global.__calls = global.__calls || []).push(r);"
        " return Promise.resolve({ok: true, width: 1}); }}"
    )
    assert got["result"] == {"ok": True, "width": 1}
    assert got["calls"] == [{"x": 111, "y": 795, "w": 41, "h": 14}]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
@pytest.mark.parametrize(
    "handle,reason",
    [
        pytest.param("undefined", "noProbe", id="no-handle"),
        pytest.param("{rect: {}}", "noProbe", id="no-probe-method"),
        pytest.param("{probe: function () { throw new Error('boom'); }}", "threw", id="probe-throws"),
        pytest.param("{probe: function () { return Promise.reject(new Error('boom')); }}", "threw", id="probe-rejects"),
        pytest.param("{get probe() { throw new Error('boom'); }}", "threw", id="probe-getter-throws"),
    ],
)
def test_probe_read_js_fails_a_read_it_cannot_make(handle, reason):
    got = _run_probe_read(handle)
    assert got["result"]["ok"] is False
    assert got["result"]["reason"] == reason


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_probe_read_js_races_a_never_resolving_probe_at_two_seconds():
    got = _run_probe_read("{probe: function () { return new Promise(function () {}); }}", fast_timeout=True)
    assert got["result"] == {"ok": False, "reason": "timeout"}
    assert got["timeoutMs"] == 2000


# --------------------------------------------------------------------------- #
# A7′ instrument (plan §8): probe vs `sampleFrame`, same read, pooled over runs.
# --------------------------------------------------------------------------- #
def _a7_reads(offset=1, alpha=255, n=4) -> list[dict]:
    return [
        {
            "frameIndex": 40 + 15 * i,
            "glProbeIndex": 40 + 15 * i + offset,
            "glProbeMeta": {"ok": True, "alphaMin": alpha, "epoch": 1},
        }
        for i in range(n)
    ]


def test_a7_prime_sixteen_same_read_pairs_agree():
    got = v.glProbeSampleFramePairing([_a7_reads() for _ in range(4)])
    assert got["ok"] is True
    assert got["nPairs"] == 16 and got["nAgree"] == 16
    assert got["instrumentEscalation"] is False
    assert {p["delta"] for p in got["pairs"]} == {1}


def test_a7_prime_known_bad_previous_read_pairing_is_red():
    """Pairing each probe with the previous read's `sampleFrame` (≈ 350 ms apart)."""
    got = v.glProbeSampleFramePairing([_a7_reads() for _ in range(4)], lag=1)
    assert got["ok"] is False
    assert got["nAgree"] == 0
    assert {p["delta"] for p in got["pairs"] if p["delta"] is not None} == {16}


@pytest.mark.parametrize("broken,ok", [(4, True), (5, False)])
def test_a7_prime_needs_twelve_of_sixteen(broken, ok):
    runs = [_a7_reads() for _ in range(4)]
    for k in range(broken):
        runs[k // 4][k % 4]["glProbeIndex"] = None if k % 2 else runs[k // 4][k % 4]["frameIndex"] + 3
    got = v.glProbeSampleFramePairing(runs)
    assert got["nAgree"] == 16 - broken
    assert got["ok"] is ok


def test_a7_prime_delta_is_signed_mod_256():
    runs = [[{"frameIndex": 255, "glProbeIndex": 1, "glProbeMeta": {"ok": True, "alphaMin": 255}}]]
    got = v.glProbeSampleFramePairing(runs, min_agree=1)
    assert got["pairs"][0]["delta"] == 2 and got["ok"] is True


def test_a7_prime_alpha_below_255_is_an_instrument_escalation_not_a_pass():
    """A control read with `alphaMin` < 255 is an instrument fact to escalate (plan §4,
    §13), never scored as agreement."""
    runs = [_a7_reads() for _ in range(4)]
    runs[2][1]["glProbeMeta"]["alphaMin"] = 254
    got = v.glProbeSampleFramePairing(runs)
    assert got["ok"] is False
    assert got["instrumentEscalation"] is True
    assert got["alphaBelow255"] == [{"run": 2, "read": 1, "alphaMin": 254}]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_probe_read_js_fails_a_throwing_oracle_getter():
    """Accessor failures on `window.__OBED_GL_ORACLE__` itself are a failed read, never a
    rejected evaluate."""
    got = _run_probe_read(
        "",
        window_js="global.window = {}; Object.defineProperty(global.window, '__OBED_GL_ORACLE__',"
        " {get: function () { throw new Error('boom'); }});",
    )
    assert got["result"]["ok"] is False
    assert got["result"]["reason"] == "threw"


@pytest.mark.parametrize(
    "meta",
    [
        pytest.param({"ok": False, "reason": "standDown", "alphaMin": 255}, id="probe-failed"),
        pytest.param(None, id="meta-missing"),
        pytest.param({"ok": True}, id="alpha-missing"),
        pytest.param({"ok": True, "alphaMin": True}, id="alpha-bool"),
        pytest.param({"ok": "true", "alphaMin": 255}, id="ok-not-true"),
    ],
)
def test_a7_prime_a_pair_without_a_clean_probe_read_has_no_delta(meta):
    """Known-bads: a decoded-looking counter on a failed or unattested probe read is
    never scored as agreement."""
    runs = [_a7_reads() for _ in range(4)]
    for reads in runs:
        for read in reads:
            if meta is None:
                read.pop("glProbeMeta")
            else:
                read["glProbeMeta"] = dict(meta)
    got = v.glProbeSampleFramePairing(runs)
    assert got["ok"] is False
    assert got["nAgree"] == 0
    assert all(p["delta"] is None for p in got["pairs"])


@pytest.mark.parametrize(
    "probe,frame",
    [
        pytest.param(True, 1, id="bool-probe"),
        pytest.param(1, False, id="bool-frame"),
        pytest.param(256, 255, id="probe-above-255"),
        pytest.param(-1, 0, id="probe-negative"),
        pytest.param(40, 296, id="frame-above-255"),
        pytest.param(41.0, 40, id="float-probe"),
    ],
)
def test_a7_prime_counters_must_be_integers_in_0_255(probe, frame):
    runs = [[{"frameIndex": frame, "glProbeIndex": probe, "glProbeMeta": {"ok": True, "alphaMin": 255}}]]
    got = v.glProbeSampleFramePairing(runs, min_agree=1)
    assert got["pairs"][0]["delta"] is None
    assert got["ok"] is False


@pytest.mark.parametrize("runs", [None, [], [None], "x"])
def test_a7_prime_fails_closed_without_reads(runs):
    assert v.glProbeSampleFramePairing(runs)["ok"] is False


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_gl_carry_census_counts_malformed_movie1_hashes_instead_of_dropping_them():
    events = [
        _ev("glreplay-carried", 10, elId=1, delta=0.0, sceneHash="#1?currentSlide=1"),
        _ev("glreplay-zone", 50, key="movie1", to="released", sceneHash="#2?currentSlide=1"),
        _ev("remount-into-authored-layer", 51, elId=1, key="untitled.mov", sceneHash="#2?currentSlide=1"),
        _ev("remount-done", 60, elId=1, sceneHash="#3junk"),
        _ev("remount-done", 61, elId=9, key="wa0125.mov", sceneHash="bogus"),
    ]
    census = _run_census(events)
    assert census["handoffScene"] == 2
    assert census["malformedTotal"] == 1
    verdict = v.glCarryCensusVerdict(census, 1)
    assert verdict["ok"] is False
    assert verdict["reason"] == "movie1 carry notes with an unparseable scene hash"
    clean = _run_census(events[:3])
    assert clean["malformedTotal"] == 0 and v.glCarryCensusVerdict(clean, 1)["ok"] is True
