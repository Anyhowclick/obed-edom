"""Unit tests for the pure scoring functions in `scripts/live_continuity_probe.py`.

These are synthetic-sample tests: no Chrome, no host, no Keynote export. They
exist because a reviewer found the host-gate probe's scoring could pass without
proving what it claims (see `.agents/plans/keynote-alpha.md`, "Instrument
design": fail-closed, a green you cannot trace to the fix is a red). Each test
is deliberately named after the specific gap it closes, so a regression that
reopens one fails a NAMED test, not a vague "score changed" diff.

The script lives under `scripts/` (not an installed package), so it is loaded
by file path, mirroring `tests/test_p2_adversarial.py`.
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent


def _load_probe_module():
    for sub in ("scripts", "src"):
        p = str(REPO / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location(
        "live_continuity_probe", REPO / "scripts" / "live_continuity_probe.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


probe = _load_probe_module()

ASSET = "untitled.mov"
SRC_RECT = {"x": 100.0, "y": 100.0, "w": 200.0, "h": 100.0}
DST_RECT = {"x": 300.0, "y": 300.0, "w": 260.0, "h": 130.0}

IDENTITY_STAGE_MAP = {"s": 1.0, "sy": 1.0, "ox": 0.0, "oy": 0.0, "offsetWidth": 1920.0, "offsetHeight": 1080.0}
SCALED_STAGE_MAP_4_3 = {"s": 4 / 3, "sy": 4 / 3, "ox": 0.0, "oy": 0.0, "offsetWidth": 1920.0, "offsetHeight": 1080.0}
LETTERBOXED_STAGE_MAP_5_6 = {"s": 5 / 6, "sy": 5 / 6, "ox": 0.0, "oy": 50.0, "offsetWidth": 1920.0, "offsetHeight": 1080.0}

_UNSET = object()


def _screen_rect(authored: dict[str, float], stage_map: dict[str, Any]) -> dict[str, float]:
    """Test-only inverse of `probe.to_authored_rect`: build the on-screen rect a
    real sampler would have observed for a given authored rect under a given
    stage map."""
    s = stage_map["s"]
    return {
        "x": authored["x"] * s + stage_map["ox"],
        "y": authored["y"] * s + stage_map["oy"],
        "w": authored["w"] * s,
        "h": authored["h"] * s,
    }


def video(
    *,
    id: int,
    el_id: int | None,
    src: str = ASSET,
    t: float,
    scene: float | None,
    current_time: float,
    paused: bool = False,
    ready_state: int = 4,
    is_connected: bool = True,
    rect: dict[str, float] | None = None,
    owner_el_id: int | None | object = "SELF",
) -> dict[str, Any]:
    """Build one sampled `<video>` row the way SAMPLER_JS emits it. `owner_el_id`
    defaults to the sentinel "SELF" (footprintOwnerDecoderId agrees the tracked
    element owns its own footprint); pass an explicit id, None (no owner
    resolved), or a dict for other cases."""
    if rect is None:
        rect = dict(SRC_RECT if (scene or 0) < 2 else DST_RECT)
    if owner_el_id == "SELF":
        owner = {"elId": el_id, "key": "movie1", "via": "footprint-video", "contextType": None}
    elif owner_el_id is None:
        owner = None
    else:
        owner = {"elId": owner_el_id, "key": "movie1", "via": "footprint-video", "contextType": None}
    return {
        "id": id,
        "elId": el_id,
        "src": src,
        "currentTime": current_time,
        "paused": paused,
        "readyState": ready_state,
        "videoWidth": 640,
        "isConnected": is_connected,
        "rect": rect,
        "footprintOwner": owner,
    }


def sample(t: float, scene: float | None, *videos: dict[str, Any], stage_map: Any = _UNSET) -> dict[str, Any]:
    resolved = IDENTITY_STAGE_MAP if stage_map is _UNSET else stage_map
    return {"t": t, "scene": scene, "videos": list(videos), "stageMap": resolved}


def rows_around_boundary(
    *,
    boundary_scene: float = 2.0,
    n_before: int = 20,
    n_after: int = 20,
    dt_ms: float = 16.0,
    start_time: float = 5.0,
    src_rect: dict[str, float] | None = None,
    dst_rect: dict[str, float] | None = None,
    stall_run_s: float = 0.0,
    clock_drop: float = 0.0,
    owner_mismatch_after: bool = False,
    off_rect_after: bool = False,
    disconnected_after: bool = False,
    stage_map: Any = _UNSET,
    rect_stage_map: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """A clean, carrying decoder (id=1/elId=1) that spans `boundary_scene` with a
    steadily advancing clock, optionally injected with one specific defect.
    `stage_map` is what the sample RECORDS (the probe's own reading, `None`
    meaning "no `#stage`"); `rect_stage_map` is the map actually used to place
    the sampled `<video>` rects on screen -- it defaults to the recorded map
    (a correctly-mapped stage) but a test can diverge them to build a
    scale/offset defect. Defaults to identity if not given."""
    src_rect = src_rect or SRC_RECT
    dst_rect = dst_rect or DST_RECT
    stage_map = IDENTITY_STAGE_MAP if stage_map is _UNSET else stage_map
    rect_stage_map = rect_stage_map or (stage_map if stage_map else IDENTITY_STAGE_MAP)
    samples: list[dict[str, Any]] = []
    t = 0.0
    current_time = start_time
    stall_frames = int(round((stall_run_s * 1000.0) / dt_ms)) if stall_run_s else 0
    stalled_so_far = 0
    for i in range(n_before):
        samples.append(sample(
            t, boundary_scene - 1,
            video(id=1, el_id=1, t=t, scene=boundary_scene - 1, current_time=current_time, rect=_screen_rect(src_rect, rect_stage_map)),
            stage_map=stage_map,
        ))
        t += dt_ms
        current_time += dt_ms / 1000.0
    if clock_drop:
        current_time -= clock_drop
    for i in range(n_after):
        scene = boundary_scene
        owner = 999 if owner_mismatch_after else "SELF"
        authored_rect = dict(dst_rect)
        if off_rect_after:
            authored_rect["x"] += 50
        rect = _screen_rect(authored_rect, rect_stage_map)
        connected = not disconnected_after
        advance = 0.0 if stalled_so_far < stall_frames else dt_ms / 1000.0
        samples.append(
            sample(
                t, scene,
                video(
                    id=1, el_id=1, t=t, scene=scene, current_time=current_time,
                    rect=rect, owner_el_id=owner, is_connected=connected,
                ),
                stage_map=stage_map,
            )
        )
        current_time += advance
        if advance == 0.0:
            stalled_so_far += 1
        t += dt_ms
    return samples


class TestScoreContinuityCleanCarry:
    def test_clean_carry_passes(self) -> None:
        samples = rows_around_boundary()
        verdict = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=True)
        assert verdict["verdict"] is True
        assert verdict["elementId"] == 1
        assert verdict["windowAdvanceS"] >= probe.MIN_ADVANCE_S
        assert verdict["longestStallS"] == 0.0
        assert verdict["ownerMismatches"] == []
        assert verdict["rectMismatches"] == []


class TestOwnerMismatchAfterCut:
    def test_id_present_before_and_after_but_different_owner_fails(self) -> None:
        """Reviewer finding #1: the same element id existing before and after is
        not enough if a DIFFERENT element is the runtime's reported footprint
        owner after the cut -- that means the tracked id is not actually driving
        the composited image any more."""
        samples = rows_around_boundary(owner_mismatch_after=True)
        verdict = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=True)
        assert verdict["verdict"] is False
        assert verdict["ownerMismatches"], "expected at least one recorded owner mismatch"
        assert all(m["footprintOwner"]["elId"] == 999 for m in verdict["ownerMismatches"])

    def test_owner_check_skipped_when_runtime_not_installed(self) -> None:
        """Arm B (continuity off) never installs the preserve runtime, so
        footprintOwnerDecoderId never resolves anything -- the owner check must
        not itself fail the verdict when there is no runtime to ask."""
        samples = rows_around_boundary(owner_mismatch_after=False)
        for s in samples:
            for v in s["videos"]:
                v["footprintOwner"] = None
        verdict = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=False)
        assert verdict["verdict"] is True
        assert verdict["ownerMismatches"] == []


class TestOffRectOrDisconnected:
    def test_hidden_decoder_fails(self) -> None:
        samples = rows_around_boundary(disconnected_after=True)
        verdict = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=True)
        assert verdict["verdict"] is False
        assert verdict["rectMismatches"]
        assert all(m["phase"] == "after" for m in verdict["rectMismatches"])

    def test_off_rect_decoder_fails(self) -> None:
        samples = rows_around_boundary(off_rect_after=True)
        verdict = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=True)
        assert verdict["verdict"] is False
        assert verdict["rectMismatches"]


class TestStallDetection:
    def test_frozen_clock_spread_over_many_samples_fails_with_stall_reported(self) -> None:
        """Reviewer finding #2: comparing only CONSECUTIVE ~16ms samples against
        the 0.3s threshold never sees a 1.2s freeze made of many non-advancing
        16ms samples -- it must be caught by accumulating the run."""
        samples = rows_around_boundary(n_after=250, stall_run_s=1.2)
        verdict = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=True)
        assert verdict["verdict"] is False
        assert verdict["longestStallS"] >= 1.2 - 1e-6

    def test_short_stall_under_threshold_does_not_fail(self) -> None:
        samples = rows_around_boundary(n_after=40, stall_run_s=0.1)
        verdict = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=True)
        assert verdict["verdict"] is True
        assert verdict["longestStallS"] < probe.MAX_STALL_S


class TestWindowedAdvance:
    def test_whole_run_advance_but_less_than_window_minimum_fails(self) -> None:
        """A decoder that has plenty of lifetime clock advance overall, but whose
        advance INSIDE the boundary window is under the floor, must fail --
        whole-run advance is not evidence about the cut itself (reviewer finding
        #1: "advance measured WITHIN the window", not whole-run advance)."""
        pad_ms = probe.WINDOW_PAD_S * 1000.0
        dt_ms = 16.0
        samples: list[dict[str, Any]] = []
        t = 0.0
        current_time = 0.0
        # Real advance far before the cut, well outside the padded window, giving
        # a large WHOLE-RUN advance that must not leak into the window's verdict.
        genuine_frames = int((pad_ms * 2) / dt_ms) + 50
        for _ in range(genuine_frames):
            samples.append(sample(t, 0.0, video(id=1, el_id=1, t=t, scene=0.0, current_time=current_time, rect=dict(SRC_RECT))))
            t += dt_ms
            current_time += dt_ms / 1000.0
        frozen_at = current_time
        # Frozen clock for long enough, on BOTH sides of the cut, that the entire
        # padded window sits inside the freeze (never touching the genuine-advance
        # history above).
        freeze_frames = int((pad_ms + 500.0) / dt_ms)
        for _ in range(freeze_frames):
            samples.append(sample(t, 1.9, video(id=1, el_id=1, t=t, scene=1.9, current_time=frozen_at, rect=dict(SRC_RECT))))
            t += dt_ms
        for _ in range(freeze_frames):
            samples.append(sample(t, 2.0, video(id=1, el_id=1, t=t, scene=2.0, current_time=frozen_at, rect=dict(DST_RECT))))
            t += dt_ms
        verdict = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=True)
        assert verdict["verdict"] is False
        assert verdict["windowAdvanceS"] < probe.MIN_ADVANCE_S
        # Sanity: the whole-run advance genuinely was large -- the failure is
        # about the WINDOW, not about the decoder never having moved at all.
        assert (genuine_frames * dt_ms / 1000.0) >= probe.MIN_ADVANCE_S


class TestClockReset:
    def test_clock_reset_fails(self) -> None:
        samples = rows_around_boundary(clock_drop=1.0)
        verdict = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=True)
        assert verdict["verdict"] is False
        # rows_around_boundary applies the drop between the last pre-cut sample and
        # the first post-cut one, one frame (16ms) apart, so the measured drop is
        # the injected amount minus that one frame's own advance.
        assert verdict["maxDropS"] >= 1.0 - 0.02


class TestNoCrossing:
    def test_asset_never_crosses_boundary_fails(self) -> None:
        samples = [
            sample(0.0, 0.0, video(id=1, el_id=1, t=0.0, scene=0.0, current_time=0.0)),
            sample(16.0, 0.0, video(id=1, el_id=1, t=16.0, scene=0.0, current_time=0.016)),
        ]
        verdict = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=True)
        assert verdict["verdict"] is False
        assert verdict["reason"] == "boundary crossing not observed in samples"

    def test_never_decoded_is_inconclusive_not_pass_or_fail(self) -> None:
        samples = [
            sample(0.0, 0.0, video(id=1, el_id=1, t=0.0, scene=0.0, current_time=0.0, ready_state=0)),
            sample(16.0, 2.0, video(id=1, el_id=1, t=16.0, scene=2.0, current_time=0.0, ready_state=0)),
        ]
        verdict = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=True)
        assert verdict["verdict"] is None
        assert "inconclusive" in verdict["reason"]


class TestScoreRestart:
    def _samples(self, *, fresh_start: float = 0.0, fresh_id: int = 2) -> list[dict[str, Any]]:
        samples = []
        t = 0.0
        for _ in range(10):
            samples.append(sample(t, 1.0, video(id=1, el_id=1, t=t, scene=1.0, current_time=1.0 + t / 1000.0, ready_state=4)))
            t += 16.0
        for i in range(10):
            samples.append(
                sample(
                    t, 3.0,
                    video(id=fresh_id, el_id=fresh_id, t=t, scene=3.0, current_time=fresh_start + i * 0.016, ready_state=4),
                )
            )
            t += 16.0
        return samples

    def test_restart_needs_genuinely_new_id_with_start_under_threshold(self) -> None:
        verdict = probe.score_restart(self._samples(fresh_start=0.0), ASSET, 3.0)
        assert verdict["verdict"] is True
        assert verdict["elementId"] == 2
        assert verdict["startTimeS"] < probe.RESTART_MAX_START_S

    def test_restart_fails_when_start_time_is_not_near_zero(self) -> None:
        verdict = probe.score_restart(self._samples(fresh_start=5.0), ASSET, 3.0)
        assert verdict["verdict"] is False

    def test_restart_fails_when_the_same_id_carries_across(self) -> None:
        samples = []
        t = 0.0
        for _ in range(10):
            samples.append(sample(t, 1.0, video(id=1, el_id=1, t=t, scene=1.0, current_time=1.0 + t / 1000.0)))
            t += 16.0
        for _ in range(10):
            samples.append(sample(t, 3.0, video(id=1, el_id=1, t=t, scene=3.0, current_time=1.5 + t / 1000.0)))
            t += 16.0
        verdict = probe.score_restart(samples, ASSET, 3.0)
        assert verdict["verdict"] is False
        assert verdict["reason"] == "no distinct decoder id after the boundary"

    def test_restart_inconclusive_when_never_decoded(self) -> None:
        samples = [sample(0.0, 1.0, video(id=1, el_id=1, t=0.0, scene=1.0, current_time=0.0, ready_state=0))]
        verdict = probe.score_restart(samples, ASSET, 3.0)
        assert verdict["verdict"] is None


class TestBackgroundAlpha:
    @pytest.mark.parametrize(
        ("css", "expected"),
        [
            ("rgba(0, 0, 0, 0)", 0.0),
            ("rgba(0, 0, 0, 1)", 1.0),
            ("rgba(12, 34, 56, 0.5)", 0.5),
            ("rgb(0, 0, 0)", 1.0),  # no alpha channel at all -> opaque, never a pass
            ("", 1.0),
            (None, 1.0),
            ("not-a-color", 1.0),
        ],
    )
    def test_parses_alpha_and_fails_closed(self, css: str | None, expected: float) -> None:
        assert probe.background_alpha(css) == expected


class TestOverallStatusTruthTable:
    def _base_result(self) -> dict[str, Any]:
        def verdict(v: bool) -> dict[str, Any]:
            return {"verdict": v}

        def visible_slide(ordinal: int, verdict: bool | None) -> dict[str, Any]:
            return {
                "playerIndex": ordinal - 1, "originalOrdinal": ordinal, "verdict": verdict,
                "status": "pass" if verdict is True else "fail",
            }

        return {
            # The 1->2 destination slide, derived by the probe from the plan (never
            # hardcoded as "slide 2"): the slide the Voff control must be RED on.
            "groundTruth": {"boundaryPlayerIndex": 1},
            "visible": {
                "V": {
                    "pass": "V", "status": "ok", "continuity": {"mode": "qualified"},
                    "stageFit": verdict(True),
                    "slides": [visible_slide(n, True) for n in (1, 2, 3, 4)],
                    "verdict": True,
                },
                "Voff": {
                    "pass": "Voff", "status": "ok", "continuity": {"mode": "off"},
                    "stageFit": verdict(True),
                    "slides": [
                        visible_slide(1, True), visible_slide(2, False),
                        visible_slide(3, True), visible_slide(4, True),
                    ],
                    "verdict": False,
                },
            },
            "arms": {
                "A": {
                    "continuity": {"mode": "qualified"},
                    "continue1to2": verdict(True), "restart2to3": verdict(True), "continue3to4": verdict(True),
                    "stageFit": verdict(True),
                },
                "B": {
                    "continuity": {"mode": "off"},
                    "continue1to2": verdict(True), "restart2to3": verdict(True), "continue3to4": verdict(False),
                    "stageFit": verdict(True),
                },
                "C": {
                    "continuity": {"mode": "qualified"},
                    "continue1to2": verdict(True), "restart2to3": verdict(True), "continue3to4": verdict(False),
                    "stageFit": verdict(True),
                },
            },
            "attach": {
                "continuity": {"mode": "qualified"},
                "transparentBackground": {"computedBackground": "rgba(0, 0, 0, 0)"},
                "continue1to2": verdict(True), "restart2to3": verdict(True), "continue3to4": verdict(True),
                "stageFit": verdict(True),
            },
        }

    def test_all_green_with_correct_modes_passes(self) -> None:
        status, reasons = probe.overall_status(self._base_result())
        assert status == "pass"
        assert reasons == []

    def test_arm_a_wrong_mode_fails_even_if_boundaries_are_green(self) -> None:
        result = self._base_result()
        result["arms"]["A"]["continuity"]["mode"] = "unsupported"
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("arm A" in r for r in reasons)

    def test_arm_b_wrong_mode_fails_even_if_boundary_is_correctly_red(self) -> None:
        result = self._base_result()
        result["arms"]["B"]["continuity"]["mode"] = "qualified"
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("arm B" in r for r in reasons)

    def test_arm_c_wrong_mode_fails(self) -> None:
        result = self._base_result()
        result["arms"]["C"]["continuity"]["mode"] = "off"
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("arm C" in r for r in reasons)

    def test_attach_opaque_background_fails(self) -> None:
        result = self._base_result()
        result["attach"]["transparentBackground"]["computedBackground"] = "rgb(0, 0, 0)"
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("alpha" in r for r in reasons)

    def test_attach_wrong_mode_fails(self) -> None:
        result = self._base_result()
        result["attach"]["continuity"]["mode"] = "unsupported"
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("attach" in r for r in reasons)

    def test_missing_verdict_is_inconclusive(self) -> None:
        result = self._base_result()
        result["arms"]["A"]["continue1to2"] = {"verdict": None}
        status, reasons = probe.overall_status(result)
        assert status == "inconclusive"

    def test_wrong_boundary_pattern_fails(self) -> None:
        result = self._base_result()
        result["arms"]["B"]["continue3to4"] = {"verdict": True}  # should have been False
        status, _ = probe.overall_status(result)
        assert status == "fail"


def moving_boundary_samples() -> list[dict[str, Any]]:
    samples = []
    phases = (
        [(6, "IdleAtFinalState", False, 0.0)] * 10
        + [(7, "Playing", True, index / 30) for index in range(31)]
        + [(7, "IdleAtFinalState", False, 1.0)] * 5
        + [(8, "IdleAtInitialState", False, 1.0)] * 20
    )
    for index, (scene, state, busy, progress) in enumerate(phases):
        t = index * 50.0
        rect = {key: SRC_RECT[key] + progress * (DST_RECT[key] - SRC_RECT[key]) for key in SRC_RECT}
        row = sample(t, scene, video(id=1, el_id=1, t=t, scene=scene, current_time=5 + t / 1000, rect=rect))
        row.update(playerState=state, busy=busy)
        samples.append(row)
    return samples


def score_moving_boundary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    return probe.score_continuity(
        samples, ASSET, 8, SRC_RECT, DST_RECT, runtime_installed=True, transition_scene=7,
    )


class TestMovingBoundary:
    def test_shared_scalar_motion_then_destination_at_idle_final_passes(self) -> None:
        result = score_moving_boundary(moving_boundary_samples())
        assert result["verdict"] is True
        assert result["motion"]["errors"] == []
        assert result["motion"]["sampleCount"] == 31

    @pytest.mark.parametrize("defect", ["old-footprint", "stationary-snap", "early-destination", "backward", "off-path"])
    def test_movement_null_controls_fail(self, defect: str) -> None:
        samples = moving_boundary_samples()
        moving = [row for row in samples if row["playerState"] == "Playing"]
        for index, row in enumerate(moving):
            rect = row["videos"][0]["rect"]
            if defect == "old-footprint":
                rect.update(SRC_RECT, x=109.0)
            elif defect == "stationary-snap":
                rect.update(SRC_RECT)
            elif defect == "early-destination":
                rect.update(DST_RECT)
            elif defect == "backward" and 10 <= index < 20:
                progress = (30 - index) / 30
                rect.update({key: SRC_RECT[key] + progress * (DST_RECT[key] - SRC_RECT[key]) for key in SRC_RECT})
            elif defect == "off-path":
                rect["y"] = SRC_RECT["y"]
        result = score_moving_boundary(samples)
        assert result["verdict"] is False
        assert result["motion"]["errors"]

    @pytest.mark.parametrize("field,value", [("scene", 6), ("playerState", "SettingUpScene"), ("busy", False)])
    def test_path_allowance_requires_actual_playing_transition(self, field: str, value: Any) -> None:
        samples = moving_boundary_samples()
        for row in samples:
            if row["playerState"] == "Playing":
                row[field] = value
        result = score_moving_boundary(samples)
        assert result["verdict"] is False
        assert result["rectMismatches"]

    def test_settled_source_must_remain_at_source(self) -> None:
        samples = moving_boundary_samples()
        for row in samples:
            if row["scene"] == 6:
                row["videos"][0]["rect"] = dict(DST_RECT)
        result = score_moving_boundary(samples)
        assert result["verdict"] is False
        assert result["rectMismatches"]

    def test_idle_final_transition_scene_must_already_be_at_destination(self) -> None:
        samples = moving_boundary_samples()
        for row in samples:
            if row["scene"] == 7 and row["playerState"] == "IdleAtFinalState":
                row["videos"][0]["rect"] = dict(SRC_RECT)
        result = score_moving_boundary(samples)
        assert result["verdict"] is False
        assert result["rectMismatches"]

    def test_owner_must_match_during_motion_too(self) -> None:
        samples = moving_boundary_samples()
        samples[20]["videos"][0]["footprintOwner"]["elId"] = 999
        result = score_moving_boundary(samples)
        assert result["verdict"] is False
        assert result["ownerMismatches"]

    def test_motion_does_not_weaken_clock_gate(self) -> None:
        samples = moving_boundary_samples()
        for row in samples[20:]:
            row["videos"][0]["currentTime"] -= 1.0
        result = score_moving_boundary(samples)
        assert result["verdict"] is False
        assert result["maxDropS"] > probe.MAX_DROP_S

    def test_path_allowance_is_opt_in(self) -> None:
        result = probe.score_continuity(moving_boundary_samples(), ASSET, 8, SRC_RECT, DST_RECT, True)
        assert result["verdict"] is False
        assert result["rectMismatches"]

    def test_sampler_preserves_phase_evidence_in_track(self) -> None:
        samples = moving_boundary_samples()
        tracked = probe.track_by_id(samples, ASSET)[1]
        assert tracked[10]["playerState"] == "Playing"
        assert tracked[10]["busy"] is True

    def test_nonfinite_rect_never_passes_path_gate(self) -> None:
        samples = moving_boundary_samples()
        samples[20]["videos"][0]["rect"]["x"] = float("nan")
        assert score_moving_boundary(samples)["verdict"] is False

    def test_wait_after_motion_does_not_clip_transition_out_of_window(self) -> None:
        samples = moving_boundary_samples()
        insert_at = next(index for index, row in enumerate(samples) if row["scene"] == 8)
        waiting = samples[insert_at - 1]
        samples[insert_at:insert_at] = [
            {**waiting, "videos": [dict(waiting["videos"][0])]} for _ in range(80)
        ]
        for index, row in enumerate(samples):
            row["t"] = index * 50.0
            row["videos"][0]["currentTime"] = 5.0 + index * 0.05
        result = score_moving_boundary(samples)
        assert result["verdict"] is True
        assert result["motion"]["sampleCount"] == 31
        assert result["window"]["start"] <= samples[10]["t"]

    def test_cumulative_backward_drift_cannot_hide_below_per_frame_jitter(self) -> None:
        values = (
            [index / 20 for index in range(11)]
            + [0.5 - index * 0.005 for index in range(1, 11)]
            + [0.45 + index * 0.05 for index in range(1, 12)]
        )
        rows = [{"rect": {key: SRC_RECT[key] + progress * (DST_RECT[key] - SRC_RECT[key]) for key in SRC_RECT}} for progress in values]
        result = probe.score_motion(rows, SRC_RECT, DST_RECT, probe.RECT_TOLERANCE_PX)
        assert "transition progress reverses" in result["errors"]

    def test_transition_without_settled_source_evidence_fails(self) -> None:
        samples = [row for row in moving_boundary_samples() if row["scene"] >= 7]
        result = score_moving_boundary(samples)
        assert result["verdict"] is False
        assert "settled source not observed" in result["motion"]["errors"]

    def test_static_same_asset_ghost_cannot_displace_actual_moving_owner(self) -> None:
        samples = moving_boundary_samples()
        for row in samples:
            ghost_rect = SRC_RECT if row["scene"] < 7 or row["playerState"] == "Playing" else DST_RECT
            row["videos"].append(video(
                id=2, el_id=2, t=row["t"], scene=row["scene"], current_time=5.0 + row["t"] / 1000,
                rect=dict(ghost_rect), owner_el_id=1,
            ))
        result = score_moving_boundary(samples)
        assert result["verdict"] is True
        assert result["elementId"] == 1

    @pytest.mark.parametrize("missing_indices", [range(20, 25), range(5, 6), range(60, 61)])
    def test_selected_decoder_must_exist_in_every_window_frame(self, missing_indices: range) -> None:
        samples = moving_boundary_samples()
        for index in missing_indices:
            samples[index]["videos"] = []
        result = score_moving_boundary(samples)
        assert result["verdict"] is False
        assert [row["t"] for row in result["missingSamples"]] == [samples[index]["t"] for index in missing_indices]

    def test_static_boundary_also_rejects_temporarily_missing_decoder(self) -> None:
        samples = rows_around_boundary()
        samples[25]["videos"] = []
        result = probe.score_continuity(samples, ASSET, 2, SRC_RECT, DST_RECT, True)
        assert result["verdict"] is False
        assert result["missingSamples"][0]["t"] == samples[25]["t"]

    def test_window_does_not_reach_back_past_restart_into_prior_scene(self) -> None:
        """Real host-gate evidence: with a deliberate decoder restart right before
        the move (from_scene = transition_scene - 1), a blind pad_s before the
        from_scene/transition_scene crossing can reach BEFORE that restart, into a
        scene where the continuing decoder cannot exist -- producing spurious
        `missingSamples` that are not evidence of any real defect. The window must
        instead ground at the first settled sample of from_scene, not a scene
        earlier where the tracked decoder id is legitimately absent."""
        samples = moving_boundary_samples()
        prior_scene = [
            {"t": samples[0]["t"] - probe.WINDOW_PAD_S * 1000.0 - 200.0 + i * 50.0, "scene": 5,
             "playerState": "SettingUpScene", "busy": True, "videos": []}
            for i in range(4)
        ]
        result = score_moving_boundary(prior_scene + samples)
        assert result["verdict"] is True
        assert result["missingSamples"] == []
        assert result["window"]["start"] >= samples[0]["t"]

    def test_waiting_to_jump_already_at_destination_is_move_complete_not_a_mismatch(self) -> None:
        """Real host-gate evidence: after the move finishes, the player passes
        through `IdleAtFinalState`, then `WaitingToJump`, then `SettingUpScene`
        before cutting to the next scene -- the movie is parked at the destination
        throughout ALL of them, not only the first. The scorer must not expect the
        source rect again during the later post-move states."""
        samples = moving_boundary_samples()
        for row in samples:
            if row["scene"] == 7 and row["playerState"] == "IdleAtFinalState":
                row["playerState"] = "WaitingToJump"
        result = score_moving_boundary(samples)
        assert result["verdict"] is True
        assert result["rectMismatches"] == []

    def test_waiting_to_jump_at_source_rect_is_still_a_mismatch(self) -> None:
        """The relaxation above is phase-specific, not a blanket allowance: a
        WaitingToJump sample that is NOT yet at the destination must still fail."""
        samples = moving_boundary_samples()
        for row in samples:
            if row["scene"] == 7 and row["playerState"] == "IdleAtFinalState":
                row["playerState"] = "WaitingToJump"
                row["videos"][0]["rect"] = dict(SRC_RECT)
        result = score_moving_boundary(samples)
        assert result["verdict"] is False
        assert result["rectMismatches"]


class TestStageMapIdentityConversion:
    def test_identity_stage_map_conversion_is_a_noop(self) -> None:
        """(a) rows at 1:1 with a recorded stage map of s=1 must score exactly
        as they did before I3 -- the conversion pipeline is a true no-op at
        identity."""
        samples = rows_around_boundary()
        converted, invalid_count = probe.convert_samples_to_authored(samples)
        assert invalid_count == 0
        verdict = probe.score_continuity(converted, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=True)
        assert verdict["verdict"] is True
        assert verdict["stageMapInvalid"] == []


class TestStageMapScaledConversion:
    @pytest.mark.parametrize(
        "stage_map",
        [SCALED_STAGE_MAP_4_3, LETTERBOXED_STAGE_MAP_5_6],
        ids=["scaled-4-3-origin-0-0", "letterboxed-5-6-origin-0-50"],
    )
    def test_correctly_recorded_scaled_stage_passes(self, stage_map: dict[str, Any]) -> None:
        """(b) the same authored trajectory expressed in SCREEN px at a scaled
        and at a letterboxed (non-zero origin) stage map, correctly recorded,
        converts back to the authored numbers and scores green."""
        samples = rows_around_boundary(stage_map=stage_map, rect_stage_map=stage_map)
        converted, invalid_count = probe.convert_samples_to_authored(samples)
        assert invalid_count == 0
        verdict = probe.score_continuity(converted, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=True)
        assert verdict["verdict"] is True
        assert verdict["rectMismatches"] == []

    def test_wrongly_assumed_identity_map_is_a_null_control(self) -> None:
        """(c) NULL CONTROL: rects genuinely sampled on a 4/3-scaled stage, but
        the sample wrongly RECORDS an identity map -- the instrument must see
        the scale error, not silently accept the raw screen numbers."""
        samples = rows_around_boundary(stage_map=IDENTITY_STAGE_MAP, rect_stage_map=SCALED_STAGE_MAP_4_3)
        converted, invalid_count = probe.convert_samples_to_authored(samples)
        assert invalid_count == 0
        verdict = probe.score_continuity(converted, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=True)
        assert verdict["verdict"] is False
        assert verdict["rectMismatches"]

    def test_unmapped_runtime_control(self) -> None:
        """(d) UNMAPPED RUNTIME control: the stage map is correctly recorded as
        4/3-scaled, but the sampled `<video>` rects sit at the raw unscaled
        authored numbers -- what an old v2 runtime that never applied the
        scale to its screen writes would produce. Must be red."""
        samples = rows_around_boundary(stage_map=SCALED_STAGE_MAP_4_3, rect_stage_map=IDENTITY_STAGE_MAP)
        converted, invalid_count = probe.convert_samples_to_authored(samples)
        assert invalid_count == 0
        verdict = probe.score_continuity(converted, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=True)
        assert verdict["verdict"] is False
        assert verdict["rectMismatches"]

    def test_missing_letterbox_origin_control(self) -> None:
        """(e) offset bug control: the stage map is correctly recorded with the
        letterboxed +50 y-origin, but the sampled rects were actually placed
        as if the origin were 0 (the bug this arm exists to catch). Must be
        red."""
        buggy_rect_map = {**LETTERBOXED_STAGE_MAP_5_6, "oy": 0.0}
        samples = rows_around_boundary(stage_map=LETTERBOXED_STAGE_MAP_5_6, rect_stage_map=buggy_rect_map)
        converted, invalid_count = probe.convert_samples_to_authored(samples)
        assert invalid_count == 0
        verdict = probe.score_continuity(converted, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=True)
        assert verdict["verdict"] is False
        assert verdict["rectMismatches"]


class TestStageMapInvalid:
    @pytest.mark.parametrize(
        "stage_map",
        [
            None,
            {"s": 0.0, "sy": 0.0, "ox": 0.0, "oy": 0.0, "offsetWidth": 0.0, "offsetHeight": 0.0},
            {"s": 1.0, "sy": 1.2, "ox": 0.0, "oy": 0.0, "offsetWidth": 1920.0, "offsetHeight": 1080.0},
        ],
        ids=["no-stage-element", "zero-box", "non-uniform-scale"],
    )
    def test_invalid_stage_map_is_never_silently_skipped(self, stage_map: dict[str, Any] | None) -> None:
        """(f) a missing/invalid stage map is a scoring FAILURE, reported under
        `stageMapInvalid`, never a silently-skipped sample."""
        samples = rows_around_boundary(stage_map=stage_map, rect_stage_map=IDENTITY_STAGE_MAP)
        converted, invalid_count = probe.convert_samples_to_authored(samples)
        assert invalid_count == len(samples)
        verdict = probe.score_continuity(converted, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=True)
        assert verdict["verdict"] is False
        assert verdict["stageMapInvalid"]


class TestStageFit:
    def test_matching_fit_passes(self) -> None:
        """(g) the observed stage map matching the expected aspect-fit of the
        authored canvas into the viewport scores green."""
        expected = probe.expected_stage_fit({"width": 1920, "height": 1080}, {"width": 2560, "height": 1440})
        samples = rows_around_boundary(stage_map=SCALED_STAGE_MAP_4_3, rect_stage_map=SCALED_STAGE_MAP_4_3)
        converted, _ = probe.convert_samples_to_authored(samples)
        result = probe.score_stage_fit(converted, expected)
        assert result["verdict"] is True
        assert result["mismatchCount"] == 0
        assert result["invalidCount"] == 0

    def test_wrong_origin_fails(self) -> None:
        """(g) a stage that reports the expected scale but the wrong origin
        must fail -- the mapping is only meaningful against a correctly fitted
        stage."""
        expected = probe.expected_stage_fit({"width": 1920, "height": 1080}, {"width": 2560, "height": 1440})
        wrong_map = {**SCALED_STAGE_MAP_4_3, "ox": 200.0}
        samples = rows_around_boundary(stage_map=wrong_map, rect_stage_map=wrong_map)
        converted, _ = probe.convert_samples_to_authored(samples)
        result = probe.score_stage_fit(converted, expected)
        assert result["verdict"] is False
        assert result["mismatchCount"] > 0

    def test_no_valid_samples_fails(self) -> None:
        expected = probe.expected_stage_fit({"width": 1920, "height": 1080}, {"width": 2560, "height": 1440})
        samples = rows_around_boundary(stage_map=None, rect_stage_map=IDENTITY_STAGE_MAP)
        converted, _ = probe.convert_samples_to_authored(samples)
        result = probe.score_stage_fit(converted, expected)
        assert result["verdict"] is False
        assert result["invalidCount"] == len(samples)

    def test_zero_samples_fails_no_evidence_is_not_a_pass(self) -> None:
        expected = probe.expected_stage_fit({"width": 1920, "height": 1080}, {"width": 2560, "height": 1440})
        result = probe.score_stage_fit([], expected)
        assert result["verdict"] is False

    def test_one_invalid_sample_outside_the_scored_window_still_fails_the_arm(self) -> None:
        """Codex review finding: boundary scoring only ever inspects the
        selected decoder's crossing windows, so a missing/non-uniform
        stage-map sample sitting OUTSIDE every such window was previously
        invisible to `stageFit` (it only looked at the samples that happened
        to be valid). Add one such sample, well past the padded window, with
        an invalid (missing) stage map: the boundary verdict must stay green
        (it genuinely never sees this sample) while `stageFit` -- scored over
        the WHOLE arm -- must still catch it and fail."""
        expected = probe.expected_stage_fit({"width": 1920, "height": 1080}, {"width": 2560, "height": 1440})
        samples = rows_around_boundary(stage_map=SCALED_STAGE_MAP_4_3, rect_stage_map=SCALED_STAGE_MAP_4_3)
        far_t = samples[-1]["t"] + probe.WINDOW_PAD_S * 1000.0 + 500.0
        samples = samples + [
            sample(
                far_t, 2.0,
                video(id=1, el_id=1, t=far_t, scene=2.0, current_time=99.0, rect={"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}),
                stage_map=None,
            )
        ]
        converted, invalid_count = probe.convert_samples_to_authored(samples)
        assert invalid_count == 1

        boundary = probe.score_continuity(converted, ASSET, 2.0, SRC_RECT, DST_RECT, runtime_installed=True)
        assert boundary["verdict"] is True
        assert boundary["stageMapInvalid"] == []

        result = probe.score_stage_fit(converted, expected)
        assert result["verdict"] is False
        assert result["invalidCount"] == 1


class TestOverallStatusStageFit:
    """Fail-closed: `stage_fit_ok` passes only on an explicit truthy verdict.
    `_base_result` (shared with `TestOverallStatusTruthTable`) now carries a
    passing `stageFit` on every arm and on attach, so these tests exercise
    deviations from that baseline rather than an absent field."""

    def _base_result(self) -> dict[str, Any]:
        return TestOverallStatusTruthTable()._base_result()

    def test_arm_a_stage_fit_failure_fails_even_if_boundaries_are_green(self) -> None:
        result = self._base_result()
        result["arms"]["A"]["stageFit"] = {"verdict": False}
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("arm A stageFit failed" in r for r in reasons)

    def test_attach_stage_fit_failure_fails(self) -> None:
        result = self._base_result()
        result["attach"]["stageFit"] = {"verdict": False}
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("attach stageFit failed" in r for r in reasons)

    @pytest.mark.parametrize(
        ("path", "label"),
        [
            (("arms", "A"), "arm A"),
            (("arms", "B"), "arm B"),
            (("arms", "C"), "arm C"),
            (("attach",), "attach"),
        ],
    )
    def test_missing_stage_fit_fails_closed(self, path: tuple[str, ...], label: str) -> None:
        """A `stageFit` key that is simply absent -- an arm that crashed before
        scoring it, or a caller that never set it -- must fail, not pass, and
        must be distinguishable (by reason text) from an explicit False
        verdict."""
        result = self._base_result()
        entry = result
        for key in path[:-1]:
            entry = entry[key]
        del entry[path[-1]]["stageFit"]
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any(f"{label} stageFit missing" in r for r in reasons)


class TestViewportParsing:
    def test_parses_valid_viewport(self) -> None:
        assert probe.parse_viewport_arg("2560x1440") == (2560, 1440)

    def test_default_viewport_is_1920x1080(self) -> None:
        args = probe.parse_args([])
        assert args.viewport == (probe.VIEWPORT_WIDTH, probe.VIEWPORT_HEIGHT)

    def test_viewport_flag_overrides_default(self) -> None:
        args = probe.parse_args(["--viewport", "1600x1000"])
        assert args.viewport == (1600, 1000)

    @pytest.mark.parametrize(
        "value", ["", "1920", "1920xabc", "0x1080", "1920x0", "-100x1080", "1920,1080"]
    )
    def test_rejects_bad_viewport(self, value: str) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            probe.parse_viewport_arg(value)


# --------------------------------------------------------------------------
# Visible-content pass (V / Voff)
# --------------------------------------------------------------------------

VISIBLE_VIEWPORT = (64, 32)
FULL_BLEED_STAGE_MAP = {"s": 1.0, "sy": 1.0, "ox": 0.0, "oy": 0.0, "offsetWidth": 64.0, "offsetHeight": 32.0}


class FakeClock:
    """Monotonic clock whose only way to move is a `sleep` -- so a burst's
    scheduling can be asserted exactly, with no wall-clock time spent."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, duration: float) -> None:
        self.sleeps.append(duration)
        self.t += max(0.0, duration)


def png_b64(width: int, height: int, fill: int = 7) -> str:
    image = np.full((height, width, 3), fill, dtype=np.uint8)
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    return base64.b64encode(buffer.tobytes()).decode("ascii")


class FakeObservation:
    def __init__(self, busy: bool) -> None:
        self.busy = busy


class FakeTransport:
    def __init__(self, host: "FakeHost") -> None:
        self.host = host
        self.captures = 0
        self.evaluations: list[str] = []

    def evaluate(self, js: str) -> Any:
        self.evaluations.append(js)
        if js == probe.SCENE_ID_JS:
            return self.host.next_scene_id()
        if js == probe.STAGE_MAP_JS:
            return self.host.stage_map
        if js == probe.PAINTING_VIDEOS_JS:
            return self.host.painting
        return True

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        if method == "Runtime.evaluate":
            assert params.get("awaitPromise") is True
            self.evaluations.append(params.get("expression", ""))
            value = self.host.next_inpage()
            if isinstance(value, BaseException):
                raise value
            return {"result": {"value": value}}
        assert method == "Page.captureScreenshot"
        assert params == {"format": "png"}
        data = self.host.shot_for(self.captures)
        self.captures += 1
        return {"data": data}


class FakeHost:
    """A host-like object for the slide loop: scripted `sceneId` reads (two per
    burst attempt: before and after), scripted `busy`, a fixed screenshot, and a
    scripted `PAINTING_VIDEOS_JS` result.

    `painting` defaults to `[]` -- the shape of a Magic-Move-settled slide, whose
    movies are painted by the stage-wide WebGL canvas while the DOM layer tree
    sits at opacity 0, so no `<video>` passes the paint test. That is not an
    error: pixel liveness judges such a slide.
    """

    def __init__(
        self, *, scene_ids: list[Any], busy: list[bool] | bool = False,
        shot: str | None = None, shots: list[str] | None = None, stage_map: Any = _UNSET,
        painting: Any = _UNSET, inpage: Any = _UNSET,
    ) -> None:
        self.scene_ids = list(scene_ids)
        self.busy = busy
        self.shots = shots if shots is not None else [shot if shot is not None else png_b64(*VISIBLE_VIEWPORT)]
        self.stage_map = dict(FULL_BLEED_STAGE_MAP) if stage_map is _UNSET else stage_map
        self.painting: Any = [] if painting is _UNSET else painting
        self.inpage: list[Any] = [] if inpage is _UNSET else list(inpage)
        self.transport = FakeTransport(self)
        self.observations = 0

    def shot_for(self, index: int) -> str:
        return self.shots[index % len(self.shots)]

    def next_scene_id(self) -> Any:
        return self.scene_ids.pop(0) if self.scene_ids else "exhausted"

    def next_inpage(self) -> Any:
        return self.inpage.pop(0) if self.inpage else {"applicable": False, "status": "n/a", "reason": "no __OBED_GL_ORACLE__ handle published"}

    def observe(self) -> FakeObservation:
        busy = self.busy if isinstance(self.busy, bool) else (self.busy.pop(0) if self.busy else False)
        self.observations += 1
        return FakeObservation(busy)

    def _require_transport(self) -> FakeTransport:
        return self.transport


def passing_scorer(frames: list[Any], rects: list[dict[str, Any]], control: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": True, "status": "pass",
        "perRect": [
            {"label": rect.get("label"), "verdict": True, "rect": {"x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0}}
            for rect in rects
        ],
        "stray": {"components": []}, "noiseFloor": {"p99": 0},
    }


VISIBLE_INSTANCES = {0: {"Untitled.mov": [{"x": 10.0, "y": 10.0, "w": 20.0, "h": 10.0}]}}
VISIBLE_SLIDE = {"playerIndex": 0, "originalOrdinal": 1, "skipped": False}


class TestBurstScheduling:
    def test_deadlines_are_absolute_offsets_from_the_burst_start(self) -> None:
        assert probe.burst_deadlines(100.0, (0, 130, 290, 500, 770)) == [100.0, 100.13, 100.29, 100.5, 100.77]
        assert probe.burst_deadlines(100.0) == [100.0 + ms / 1000 for ms in probe.BURST_OFFSETS_MS]

    def test_cadence_preserves_the_owner_approved_shape(self) -> None:
        # Owner-approved tuple (research doc "Paint-oracle E0",
        # .agents/plans/keynote_live_alternatives_research.md ~L265-287, L317-321;
        # plan keynote_live_paint_oracle.plan.md SS14). Codex r1 Spec 11: "two
        # distinct gaps" does not itself prove a periodic animation cannot
        # alias -- pin the exact tuple, not just the measured min-gap/distinct
        # -gap properties it happens to have.
        assert probe.BURST_OFFSETS_MS == (0, 360, 730, 1090, 1460, 1820, 2190, 2550, 2920, 3280, 3650, 4010)
        assert len(probe.BURST_OFFSETS_MS) == 12
        gaps = [b - a for a, b in zip(probe.BURST_OFFSETS_MS, probe.BURST_OFFSETS_MS[1:])]
        assert min(gaps) >= 350
        assert len(set(gaps)) >= 2

    def test_capture_burst_records_actual_offsets_and_captures_every_shot(self) -> None:
        host = FakeHost(scene_ids=[])
        clock = FakeClock()
        frames, offsets = probe.capture_burst(host.transport, now=clock.now, sleep=clock.sleep)
        assert len(frames) == len(probe.BURST_OFFSETS_MS)
        assert host.transport.captures == len(probe.BURST_OFFSETS_MS)
        assert offsets == [float(value) for value in probe.BURST_OFFSETS_MS]

    def test_a_slow_capture_does_not_drift_the_later_offsets(self) -> None:
        """Scheduling is against a fixed start, not accumulated per shot: a shot
        that overruns its slot is recorded late but the NEXT shot still lands at
        its own absolute offset."""
        host = FakeHost(scene_ids=[])
        clock = FakeClock()
        real_call = host.transport.call

        def slow_call(method: str, **params: Any) -> dict[str, Any]:
            if host.transport.captures == 0:
                clock.t += 0.4  # must overrun the first gap (360 ms) to be an overrun at all
            return real_call(method, **params)

        host.transport.call = slow_call  # type: ignore[method-assign]
        _, offsets = probe.capture_burst(host.transport, now=clock.now, sleep=clock.sleep)
        assert offsets[0] == 0.0
        assert offsets[1] == 400.0  # the overrun itself is reported, never hidden
        assert offsets[2:] == [float(ms) for ms in probe.BURST_OFFSETS_MS[2:]]


class TestPngDecode:
    def test_png_round_trip_returns_rgb_pixels(self) -> None:
        image = np.zeros((3, 5, 3), dtype=np.uint8)
        image[0, 0] = (255, 0, 0)  # RGB red
        ok, buffer = cv2.imencode(".png", cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
        assert ok
        decoded = probe.decode_png(base64.b64encode(buffer.tobytes()).decode("ascii"))
        assert decoded.shape == (3, 5, 3)
        assert decoded.dtype == np.uint8
        assert tuple(decoded[0, 0]) == (255, 0, 0)

    def test_undecodable_data_raises_rather_than_returning_a_blank_frame(self) -> None:
        with pytest.raises(probe.VisiblePassError):
            probe.decode_png(base64.b64encode(b"not a png").decode("ascii"))


class TestAuthoredToScreenConversion:
    @pytest.mark.parametrize(
        "stage_map",
        [IDENTITY_STAGE_MAP, SCALED_STAGE_MAP_4_3, LETTERBOXED_STAGE_MAP_5_6],
        ids=["identity", "scaled-4-3", "letterboxed-origin-0-50"],
    )
    def test_screen_conversion_is_the_inverse_of_the_authored_conversion(self, stage_map: dict[str, Any]) -> None:
        screen = probe.to_screen_rect(SRC_RECT, stage_map)
        assert screen == _screen_rect(SRC_RECT, stage_map)
        back = probe.to_authored_rect(screen, stage_map)
        assert all(abs(back[key] - SRC_RECT[key]) < 1e-9 for key in ("x", "y", "w", "h"))

    def test_letterbox_origin_is_applied_to_position_but_not_to_size(self) -> None:
        screen = probe.to_screen_rect({"x": 0.0, "y": 0.0, "w": 120.0, "h": 60.0}, LETTERBOXED_STAGE_MAP_5_6)
        assert screen == {"x": 0.0, "y": 50.0, "w": 100.0, "h": 50.0}

    def test_expected_rects_label_every_instance_of_a_multi_instance_asset(self) -> None:
        instances = {0: {"Untitled.mov": [
            {"x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0},
            {"x": 40.0, "y": 0.0, "w": 5.0, "h": 5.0},
        ]}}
        rects = probe.expected_screen_rects(instances, 0, SCALED_STAGE_MAP_4_3)
        assert [rect["label"] for rect in rects] == ["Untitled.mov#1", "Untitled.mov#2"]
        assert rects[1]["screen"] == pytest.approx({"x": 40 * 4 / 3, "y": 0.0, "w": 5 * 4 / 3, "h": 5 * 4 / 3})

    def test_a_slide_the_plan_never_described_fails_closed(self) -> None:
        with pytest.raises(probe.VisiblePassError):
            probe.expected_screen_rects({0: {}}, 3, IDENTITY_STAGE_MAP)


class TestSlideInstancesGroundTruth:
    def test_missing_slide_instances_fails_closed_with_no_fallback_to_slide_rects(self) -> None:
        """`slide_rects` drops multi-instance assets, so it cannot stand in as
        ground truth: a plan without `slide_instances` is no ground truth at
        all."""
        class PlanWithoutInstances:
            slide_rects = {0: {"Untitled.mov": {"x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0}}}

        with pytest.raises(probe.VisiblePassError, match="slide_instances"):
            probe.slide_instances_of(PlanWithoutInstances())

    def test_empty_slide_instances_fails_closed(self) -> None:
        class PlanWithEmptyInstances:
            slide_instances: dict[int, dict[str, list[dict[str, float]]]] = {}

        with pytest.raises(probe.VisiblePassError, match="slide_instances"):
            probe.slide_instances_of(PlanWithEmptyInstances())

    def test_present_slide_instances_are_returned_as_is(self) -> None:
        class Plan:
            slide_instances = VISIBLE_INSTANCES

        assert probe.slide_instances_of(Plan()) == VISIBLE_INSTANCES


class TestControlRegion:
    def test_letterboxed_stage_uses_the_bar_above_it(self) -> None:
        stage = {"x": 0.0, "y": 180.0, "width": 1920.0, "height": 720.0}
        control = probe.control_region(stage, (1920, 1080))
        assert control["source"] == "letterbox-top"
        assert (control["y"], control["w"], control["h"]) == (0, 40, 40)

    def test_pillarboxed_stage_uses_the_bar_beside_it(self) -> None:
        stage = {"x": 240.0, "y": 0.0, "width": 1440.0, "height": 1080.0}
        control = probe.control_region(stage, (1920, 1080))
        assert control["source"] == "letterbox-left"
        assert (control["x"], control["w"], control["h"]) == (0, 40, 40)

    def test_full_bleed_stage_falls_back_to_the_inset_stage_corner(self) -> None:
        stage = {"x": 0.0, "y": 0.0, "width": 1920.0, "height": 1080.0}
        control = probe.control_region(stage, (1920, 1080))
        assert control["source"] == "stage-corner"
        assert (control["x"], control["y"]) == (probe.CONTROL_INSET_PX, probe.CONTROL_INSET_PX)

    def test_a_bar_thinner_than_the_patch_is_not_used_as_the_control(self) -> None:
        """A 20px bar cannot hold a 40x40 patch -- falling back to the stage
        corner is correct; sampling off the end of the bar would put half the
        control inside the stage."""
        stage = {"x": 0.0, "y": 20.0, "width": 1920.0, "height": 1040.0}
        control = probe.control_region(stage, (1920, 1080))
        assert control["source"] == "stage-corner"
        assert control["y"] == 20 + probe.CONTROL_INSET_PX


class TestVisibleSlideRecord:
    def _record(self, host: FakeHost, **kwargs: Any) -> dict[str, Any]:
        clock = FakeClock()
        return probe.visible_slide_record(
            host, VISIBLE_SLIDE, VISIBLE_INSTANCES, VISIBLE_VIEWPORT,
            scorer=kwargs.pop("scorer", passing_scorer), now=clock.now, sleep=clock.sleep, **kwargs,
        )

    def test_stable_scene_scores_on_the_first_attempt(self) -> None:
        host = FakeHost(scene_ids=["scene-1", "scene-1"])
        record = self._record(host)
        assert record["verdict"] is True
        assert record["status"] == "pass"
        assert record["attempts"] == 1
        assert record["sceneId"] == "scene-1"
        assert record["shotOffsetsMs"] == [float(v) for v in probe.BURST_OFFSETS_MS]
        assert [rect["label"] for rect in record["expectedRects"]] == ["Untitled.mov#1"]
        assert record["control"]["source"] == "stage-corner"

    def test_scene_change_during_the_burst_is_retried_once_and_then_passes(self) -> None:
        host = FakeHost(scene_ids=["scene-1", "scene-2", "scene-2", "scene-2"])
        record = self._record(host)
        assert record["verdict"] is True
        assert record["attempts"] == 2
        assert record["sceneId"] == "scene-2"

    def test_scene_changing_under_both_attempts_is_inconclusive_never_a_pass_or_a_red(self) -> None:
        host = FakeHost(scene_ids=["scene-1", "scene-2", "scene-3", "scene-4"])
        record = self._record(host)
        assert record["status"] == "inconclusive"
        assert record["verdict"] is None
        assert record["attempts"] == 2

    def test_player_going_busy_during_the_burst_is_inconclusive(self) -> None:
        # observe(): settle check, then the post-burst check of each attempt.
        host = FakeHost(scene_ids=["s", "s", "s", "s"], busy=[False, True, True])
        record = self._record(host)
        assert record["status"] == "inconclusive"
        assert record["verdict"] is None

    def test_busy_that_never_clears_is_a_bounded_wait_then_inconclusive(self) -> None:
        host = FakeHost(scene_ids=["s", "s"], busy=True)
        record = self._record(host)
        assert record["status"] == "inconclusive"
        assert record["verdict"] is None
        assert "never settled" in record["reason"]
        assert host.transport.captures == 0

    def test_screenshot_that_is_not_the_forced_viewport_fails_closed(self) -> None:
        host = FakeHost(scene_ids=["s", "s"], shot=png_b64(VISIBLE_VIEWPORT[0] - 1, VISIBLE_VIEWPORT[1]))
        record = self._record(host)
        assert record["status"] == "error"
        assert record["verdict"] is None
        assert "expected 64x32" in record["reason"]

    def test_untrustworthy_stage_map_fails_closed(self) -> None:
        host = FakeHost(scene_ids=["s", "s"], stage_map=None)
        record = self._record(host)
        assert record["status"] == "error"
        assert record["verdict"] is None
        assert "stage map" in record["reason"]

    def test_a_slide_missing_from_the_ground_truth_fails_closed(self) -> None:
        host = FakeHost(scene_ids=["s", "s"])
        clock = FakeClock()
        record = probe.visible_slide_record(
            host, {"playerIndex": 9, "originalOrdinal": 10}, VISIBLE_INSTANCES, VISIBLE_VIEWPORT,
            scorer=passing_scorer, now=clock.now, sleep=clock.sleep,
        )
        assert record["status"] == "error"
        assert record["verdict"] is None

    def test_a_failing_slide_writes_mask_and_first_shot_evidence(self, tmp_path: Path) -> None:
        written: list[tuple[dict[str, Any], int]] = []

        def evidence(record: dict[str, Any], frames: list[Any]) -> dict[str, str]:
            written.append((record, len(frames)))
            return {"mask": str(tmp_path / "mask.png")}

        def failing_scorer(frames: Any, rects: Any, control: Any) -> dict[str, Any]:
            return {"verdict": False, "status": "fail", "perRect": [], "stray": {}, "noiseFloor": {}}

        host = FakeHost(scene_ids=["s", "s"])
        record = self._record(host, scorer=failing_scorer, evidence=evidence)
        assert record["verdict"] is False
        assert written and written[0][1] == len(probe.BURST_OFFSETS_MS)
        assert record["evidence"]["mask"].endswith("mask.png")

    def test_a_passing_slide_writes_no_evidence(self) -> None:
        def evidence(record: dict[str, Any], frames: list[Any]) -> dict[str, str]:
            raise AssertionError("evidence must only be written for a failing or inconclusive slide")

        host = FakeHost(scene_ids=["s", "s"])
        assert self._record(host, evidence=evidence)["verdict"] is True


class TestVisibleSlideLoop:
    def test_slide_one_is_scored_before_any_advance_and_the_rest_after_one_each(self) -> None:
        advanced: list[int] = []
        host = FakeHost(scene_ids=["s"] * 8)
        clock = FakeClock()
        slides = [
            {"playerIndex": index, "originalOrdinal": index + 1, "skipped": False}
            for index in range(4)
        ]
        instances = {index: {"Untitled.mov": [{"x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0}]} for index in range(4)}
        records = probe.run_visible_slides(
            host, slides, instances, VISIBLE_VIEWPORT, scorer=passing_scorer,
            advance=lambda _host, target: advanced.append(target), now=clock.now, sleep=clock.sleep,
        )
        assert advanced == [2, 3, 4]
        assert [record["originalOrdinal"] for record in records] == [1, 2, 3, 4]
        assert all(record["verdict"] is True for record in records)

    def test_skipped_slides_are_never_scored(self) -> None:
        host = FakeHost(scene_ids=["s"] * 8)
        clock = FakeClock()
        slides = [
            {"playerIndex": 0, "originalOrdinal": 1, "skipped": False},
            {"playerIndex": 1, "originalOrdinal": 2, "skipped": True},
        ]
        records = probe.run_visible_slides(
            host, slides, VISIBLE_INSTANCES, VISIBLE_VIEWPORT, scorer=passing_scorer,
            advance=lambda *_a: None, now=clock.now, sleep=clock.sleep,
        )
        assert [record["originalOrdinal"] for record in records] == [1]


class TestVisibleScorerContract:
    """End-to-end over the REAL shared scorers (still no browser): synthetic
    screenshots in, a verdict out, proving the probe hands S2's composer the
    shapes it documents."""

    VIEWPORT = (320, 200)
    STAGE_MAP = {"s": 1.0, "sy": 1.0, "ox": 0.0, "oy": 0.0, "offsetWidth": 320.0, "offsetHeight": 200.0}
    INSTANCES = {0: {"Untitled.mov": [{"x": 40.0, "y": 60.0, "w": 200.0, "h": 100.0}]}}

    def test_the_shared_pure_scorers_are_importable_under_their_agreed_names(self) -> None:
        """S1 codes against S2's published API; a rename is a contract break the
        gate must see as a failure, not work around."""
        from obed_edom.html_alpha_probe import (  # noqa: F401
            liveness_mask,
            score_live_coverage,
            score_no_stray_movie,
            score_noise_floor,
            score_visible_slide,
        )

    def _shots(self, live_width: int) -> list[str]:
        rng = np.random.default_rng(1234)
        shots = []
        for _ in probe.BURST_OFFSETS_MS:
            frame = np.zeros((self.VIEWPORT[1], self.VIEWPORT[0], 3), dtype=np.uint8)
            frame[60:160, 40:40 + live_width] = rng.integers(0, 255, (100, live_width, 3), dtype=np.uint8)
            ok, buffer = cv2.imencode(".png", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
            assert ok
            shots.append(base64.b64encode(buffer.tobytes()).decode("ascii"))
        return shots

    def _record(self, live_width: int) -> dict[str, Any]:
        from obed_edom.html_alpha_probe import score_visible_slide

        host = FakeHost(scene_ids=["s", "s"], shots=self._shots(live_width), stage_map=dict(self.STAGE_MAP))
        clock = FakeClock()
        return probe.visible_slide_record(
            host, VISIBLE_SLIDE, self.INSTANCES, self.VIEWPORT,
            scorer=score_visible_slide, now=clock.now, sleep=clock.sleep,
        )

    def test_a_fully_live_authored_rect_passes(self) -> None:
        record = self._record(live_width=200)
        assert record["verdict"] is True
        assert record["status"] == "pass"
        assert record["perRect"] and record["perRect"][0]["label"] == "Untitled.mov#1"
        assert record["noiseFloor"] is not None

    def test_a_control_region_that_is_not_static_makes_the_slide_inconclusive(self) -> None:
        """Documented limitation of the stage-corner fallback: if a movie is
        authored under the corner patch, the noise floor is not a floor. The
        slide must then be INCONCLUSIVE -- never a pass, and never the RED the
        Voff control has to earn."""
        from obed_edom.html_alpha_probe import score_visible_slide

        instances = {0: {"Untitled.mov": [{"x": 0.0, "y": 0.0, "w": 200.0, "h": 100.0}]}}
        rng = np.random.default_rng(99)
        shots = []
        for _ in probe.BURST_OFFSETS_MS:
            frame = np.zeros((self.VIEWPORT[1], self.VIEWPORT[0], 3), dtype=np.uint8)
            frame[0:100, 0:200] = rng.integers(0, 255, (100, 200, 3), dtype=np.uint8)
            ok, buffer = cv2.imencode(".png", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
            assert ok
            shots.append(base64.b64encode(buffer.tobytes()).decode("ascii"))
        host = FakeHost(scene_ids=["s", "s"], shots=shots, stage_map=dict(self.STAGE_MAP))
        clock = FakeClock()
        record = probe.visible_slide_record(
            host, VISIBLE_SLIDE, instances, self.VIEWPORT,
            scorer=score_visible_slide, now=clock.now, sleep=clock.sleep,
        )
        assert record["verdict"] is None
        assert record["status"] == "inconclusive"

    def test_a_half_dead_authored_rect_is_red(self) -> None:
        """Today's evidence shape: only part of the authored rect paints a live
        movie, the rest is a static poster."""
        record = self._record(live_width=100)
        assert record["verdict"] is False
        assert record["status"] == "fail"


class TestOverallStatusVisible:
    def _base_result(self) -> dict[str, Any]:
        return TestOverallStatusTruthTable()._base_result()

    def test_v_all_live_and_voff_red_at_the_boundary_slide_passes(self) -> None:
        status, reasons = probe.overall_status(self._base_result())
        assert status == "pass"
        assert reasons == []

    def test_v_with_one_dead_slide_fails(self) -> None:
        result = self._base_result()
        result["visible"]["V"]["slides"][2]["verdict"] = False
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("visible pass V slide 3" in reason for reason in reasons)

    def test_v_with_one_inconclusive_slide_fails_it_is_never_a_pass(self) -> None:
        result = self._base_result()
        result["visible"]["V"]["slides"][1].update(verdict=None, status="inconclusive")
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("inconclusive" in reason for reason in reasons)

    def test_v_in_the_wrong_continuity_mode_fails_even_if_every_slide_is_live(self) -> None:
        result = self._base_result()
        result["visible"]["V"]["continuity"]["mode"] = "unsupported"
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("visible pass V continuity.mode" in reason for reason in reasons)

    def test_voff_in_the_wrong_continuity_mode_fails(self) -> None:
        result = self._base_result()
        result["visible"]["Voff"]["continuity"]["mode"] = "qualified"
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("visible pass Voff continuity.mode" in reason for reason in reasons)

    def test_voff_live_everywhere_fails_because_the_instrument_is_blind(self) -> None:
        result = self._base_result()
        result["visible"]["Voff"]["slides"][1]["verdict"] = True
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("blind" in reason for reason in reasons)

    def test_voff_red_on_slide_one_fails_because_the_instrument_is_always_red(self) -> None:
        """Movies do play before any transition, so slide 1 with continuity OFF
        must still be live -- a red there means the instrument reds out on
        anything, and its boundary red proves nothing."""
        result = self._base_result()
        result["visible"]["Voff"]["slides"][0]["verdict"] = False
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("always-red" in reason for reason in reasons)

    def test_voff_inconclusive_at_the_boundary_slide_is_not_the_required_red(self) -> None:
        result = self._base_result()
        result["visible"]["Voff"]["slides"][1].update(verdict=None, status="inconclusive")
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("blind" in reason for reason in reasons)

    @pytest.mark.parametrize("name", ["V", "Voff"])
    def test_a_missing_pass_fails_with_its_own_reason(self, name: str) -> None:
        result = self._base_result()
        del result["visible"][name]
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any(f"visible pass {name} missing" in reason for reason in reasons)

    def test_a_missing_visible_block_fails_both_passes(self) -> None:
        result = self._base_result()
        del result["visible"]
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("visible pass V missing" in reason for reason in reasons)
        assert any("visible pass Voff missing" in reason for reason in reasons)

    @pytest.mark.parametrize("name", ["V", "Voff"])
    def test_an_errored_pass_fails_with_the_recorded_reason(self, name: str) -> None:
        result = self._base_result()
        result["visible"][name].update(status="error", error="plan has no slide_instances")
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("plan has no slide_instances" in reason for reason in reasons)

    @pytest.mark.parametrize("name", ["V", "Voff"])
    def test_a_pass_that_scored_no_slides_fails(self, name: str) -> None:
        result = self._base_result()
        result["visible"][name]["slides"] = []
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any(f"visible pass {name} scored no slides" in reason for reason in reasons)

    def test_the_expected_red_slide_is_taken_from_the_plan_not_hardcoded(self) -> None:
        """A deck whose first continuing boundary lands on player index 2 must be
        scored there -- with slide 2 green and slide 3 red, the same artifact
        that fails under a hardcoded "slide 2" must pass."""
        result = self._base_result()
        result["groundTruth"]["boundaryPlayerIndex"] = 2
        slides = result["visible"]["Voff"]["slides"]
        slides[1]["verdict"] = True
        slides[2]["verdict"] = False
        status, reasons = probe.overall_status(result)
        assert status == "pass"
        assert reasons == []

    def test_an_unknown_expected_red_slide_fails_closed(self) -> None:
        result = self._base_result()
        del result["groundTruth"]["boundaryPlayerIndex"]
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("expected-red slide is unknown" in reason for reason in reasons)

    def test_an_expected_red_slide_that_was_never_scored_fails_closed(self) -> None:
        result = self._base_result()
        result["groundTruth"]["boundaryPlayerIndex"] = 7
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("never scored the expected-red slide" in reason for reason in reasons)

    def test_visible_failures_do_not_mask_arm_failures(self) -> None:
        result = self._base_result()
        result["arms"]["A"]["stageFit"] = {"verdict": False}
        result["visible"]["V"]["slides"][0]["verdict"] = False
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("arm A stageFit failed" in reason for reason in reasons)
        assert any("visible pass V slide 1" in reason for reason in reasons)


# --------------------------------------------------------------------------
# Independent DOM instance evidence (Codex R1, probe MAJOR #1)
# --------------------------------------------------------------------------

PAINT_VIEWPORT = (1000, 400)
# The defect actually measured on the deck: a 663x186 duplicate movie overlay
# sitting at the top-left corner of the expected 952x268 movie rect. Wholly
# INSIDE the expected rect, so `score_no_stray_movie` erases it from the stray
# mask and no amount of pixel evidence can report it.
EXPECTED_SCREEN_RECT = {"x": 20.0, "y": 70.0, "w": 952.0, "h": 268.0}
DUPLICATE_SCREEN_RECT = {"x": 20.0, "y": 70.0, "w": 663.0, "h": 186.0}
DUPLICATE_IOU = (663.0 * 186.0) / (952.0 * 268.0)

PAINT_STAGE_MAPS = {
    "full-bleed": {"s": 1.0, "sy": 1.0, "ox": 0.0, "oy": 0.0, "offsetWidth": 1000.0, "offsetHeight": 400.0},
    "scaled-4-3": {"s": 4 / 3, "sy": 4 / 3, "ox": 0.0, "oy": 0.0, "offsetWidth": 750.0, "offsetHeight": 300.0},
    "letterboxed-origin-0-50": {"s": 1.0, "sy": 1.0, "ox": 0.0, "oy": 50.0, "offsetWidth": 1000.0, "offsetHeight": 300.0},
}


def painting_video(rect: dict[str, float], *, src: str = "Untitled.mov", el_id: Any = None) -> dict[str, Any]:
    """One row as `PAINTING_VIDEOS_JS` returns it: screen px, already filtered by
    the in-page paint test."""
    return {"src": src, "elId": el_id, "rect": dict(rect)}


class TestPaintingVideoPaintTest:
    """The paint test itself runs in the page, so these assert the contract of
    the expression the probe evaluates -- a refactor that drops one of its terms
    (and so starts counting videos the player is not painting, or stops counting
    ones it is) fails a named test."""

    def test_the_expression_tests_connectedness_decode_and_size(self) -> None:
        assert "v.isConnected" in probe.PAINTING_VIDEOS_JS
        assert "v.readyState >= 2" in probe.PAINTING_VIDEOS_JS
        assert "v.videoWidth > 0" in probe.PAINTING_VIDEOS_JS
        assert "r.width > 1 && r.height > 1" in probe.PAINTING_VIDEOS_JS

    def test_the_expression_tests_visibility_and_the_ancestor_opacity_product(self) -> None:
        """A Magic-Move-settled slide paints through a stage-wide WebGL canvas
        with the DOM layer tree at opacity 0: those videos must NOT be listed."""
        assert "checkVisibility({checkOpacity: true, checkVisibilityCSS: true})" in probe.PAINTING_VIDEOS_JS
        assert "opacityProduct(v) > 0.02" in probe.PAINTING_VIDEOS_JS
        assert "node.parentElement" in probe.PAINTING_VIDEOS_JS

    def test_the_expression_tests_viewport_intersection(self) -> None:
        assert "r.left >= window.innerWidth" in probe.PAINTING_VIDEOS_JS
        assert "r.top >= window.innerHeight" in probe.PAINTING_VIDEOS_JS

    def test_a_browser_without_check_visibility_answers_with_an_error_not_a_short_list(self) -> None:
        assert "checkVisibility is unavailable" in probe.PAINTING_VIDEOS_JS


class TestRectIou:
    def test_identical_rects_are_one_and_disjoint_rects_are_zero(self) -> None:
        rect = {"x": 10.0, "y": 10.0, "w": 100.0, "h": 50.0}
        assert probe.rect_iou(rect, rect) == 1.0
        assert probe.rect_iou(rect, {"x": 500.0, "y": 500.0, "w": 100.0, "h": 50.0}) == 0.0

    def test_the_measured_duplicate_is_well_below_the_claim_threshold(self) -> None:
        assert probe.rect_iou(DUPLICATE_SCREEN_RECT, EXPECTED_SCREEN_RECT) == pytest.approx(DUPLICATE_IOU, abs=1e-6)
        assert DUPLICATE_IOU < probe.INSTANCE_IOU_MIN

    def test_a_slightly_offset_video_still_claims_its_rect(self) -> None:
        """The threshold is the runtime's own owner-resolution IoU, not an exact
        match: sub-pixel layout drift must not read as a stray instance."""
        expected = {"x": 100.0, "y": 100.0, "w": 200.0, "h": 100.0}
        assert probe.rect_iou({"x": 101.0, "y": 101.0, "w": 200.0, "h": 100.0}, expected) >= probe.INSTANCE_IOU_MIN


class TestPaintingVideoInstanceCheck:
    """Pixels inside one expected rect cannot separate two live movies, so the
    slide also has to match the DOM's painting `<video>` elements one-for-one
    against the expected instances."""

    def _record(
        self, stage_map: dict[str, Any], painting: Any, *, instances: Any = None,
        scorer: Any = passing_scorer, shots: list[str] | None = None,
    ) -> dict[str, Any]:
        if instances is None:
            instances = {0: {"Untitled.mov": [probe.to_authored_rect(EXPECTED_SCREEN_RECT, stage_map)]}}
        host = FakeHost(
            scene_ids=["s", "s"], stage_map=dict(stage_map), painting=painting,
            shot=png_b64(*PAINT_VIEWPORT), shots=shots,
        )
        clock = FakeClock()
        return probe.visible_slide_record(
            host, VISIBLE_SLIDE, instances, PAINT_VIEWPORT,
            scorer=scorer, now=clock.now, sleep=clock.sleep,
        )

    def _live_shots(self) -> list[str]:
        """Real pixels: the whole expected rect is live in every frame, so the
        pixel scorers alone would call this slide green."""
        rng = np.random.default_rng(7)
        rect = EXPECTED_SCREEN_RECT
        shots = []
        for _ in probe.BURST_OFFSETS_MS:
            frame = np.zeros((PAINT_VIEWPORT[1], PAINT_VIEWPORT[0], 3), dtype=np.uint8)
            y, x, h, w = int(rect["y"]), int(rect["x"]), int(rect["h"]), int(rect["w"])
            frame[y:y + h, x:x + w] = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
            ok, buffer = cv2.imencode(".png", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
            assert ok
            shots.append(base64.b64encode(buffer.tobytes()).decode("ascii"))
        return shots

    def test_todays_duplicate_is_red_even_though_the_pixels_are_fully_live(self) -> None:
        """The exact shape the gate could not see before: a 663x186 second movie
        wholly inside the expected 952x268 rect, with a full-size live overlay on
        top of it, so coverage passes and the stray mask is erased. Scored here
        through the REAL pixel scorers -- the red can only come from the DOM."""
        from obed_edom.html_alpha_probe import score_visible_slide

        stage_map = PAINT_STAGE_MAPS["full-bleed"]
        pixels_only = self._record(stage_map, [], scorer=score_visible_slide, shots=self._live_shots())
        assert pixels_only["verdict"] is True

        record = self._record(
            stage_map, [painting_video(DUPLICATE_SCREEN_RECT, el_id=9)],
            scorer=score_visible_slide, shots=self._live_shots(),
        )
        assert record["verdict"] is False
        assert record["status"] == "fail"
        unexpected = record["instanceCheck"]["unexpectedVideos"]
        assert len(unexpected) == 1
        assert unexpected[0]["elId"] == 9
        assert unexpected[0]["screen"] == DUPLICATE_SCREEN_RECT
        assert unexpected[0]["bestIou"] == pytest.approx(DUPLICATE_IOU, abs=1e-6)
        assert unexpected[0]["bestLabel"] == "Untitled.mov#1"

    @pytest.mark.parametrize("stage_map", list(PAINT_STAGE_MAPS.values()), ids=list(PAINT_STAGE_MAPS))
    def test_one_correctly_placed_painting_video_is_green(self, stage_map: dict[str, Any]) -> None:
        record = self._record(stage_map, [painting_video(EXPECTED_SCREEN_RECT)])
        assert record["verdict"] is True
        assert record["instanceCheck"]["verdict"] is True
        assert record["instanceCheck"]["unexpectedVideos"] == []
        assert record["instanceCheck"]["duplicateVideos"] == []

    @pytest.mark.parametrize("stage_map", list(PAINT_STAGE_MAPS.values()), ids=list(PAINT_STAGE_MAPS))
    def test_the_duplicate_shape_is_unexpected_under_every_stage_map(self, stage_map: dict[str, Any]) -> None:
        """Screen-to-authored conversion uses the probe's own per-burst stage
        map, so a scaled or letterboxed stage neither hides the duplicate nor
        turns a correct instance into a stray."""
        record = self._record(stage_map, [painting_video(DUPLICATE_SCREEN_RECT)])
        assert record["verdict"] is False
        assert len(record["instanceCheck"]["unexpectedVideos"]) == 1
        assert record["instanceCheck"]["unexpectedVideos"][0]["bestIou"] == pytest.approx(DUPLICATE_IOU, abs=1e-6)

    @pytest.mark.parametrize("stage_map", list(PAINT_STAGE_MAPS.values()), ids=list(PAINT_STAGE_MAPS))
    def test_two_painting_videos_claiming_one_rect_are_a_duplicate_red(self, stage_map: dict[str, Any]) -> None:
        """A retired overlay that still paints at the same place as its
        replacement: both match the one expected instance, which is exactly the
        defect pixels cannot report."""
        record = self._record(stage_map, [
            painting_video(EXPECTED_SCREEN_RECT, el_id=1),
            painting_video(EXPECTED_SCREEN_RECT, el_id=2),
        ])
        assert record["verdict"] is False
        assert record["status"] == "fail"
        assert record["instanceCheck"]["unexpectedVideos"] == []
        duplicates = record["instanceCheck"]["duplicateVideos"]
        assert [entry["label"] for entry in duplicates] == ["Untitled.mov#1"]
        assert [video["elId"] for video in duplicates[0]["videos"]] == [1, 2]

    def test_a_video_the_paint_test_filtered_out_is_ignored(self) -> None:
        """On a Magic-Move-settled slide the player paints with a stage-wide
        WebGL canvas and the DOM layer tree sits at opacity 0. The in-page paint
        test drops those videos, so the probe sees an empty list -- and an empty
        list is not a duplicate, a stray, or an error."""
        record = self._record(PAINT_STAGE_MAPS["full-bleed"], [])
        assert record["verdict"] is True
        assert record["instanceCheck"] == {
            "verdict": True, "painting": [], "unexpectedVideos": [], "duplicateVideos": [], "reason": None,
        }

    def test_an_expected_rect_with_no_painting_video_but_live_pixels_is_green(self) -> None:
        """Two expected instances, only one of them painted by a DOM video: the
        other may be drawn by the player in WebGL, and pixel liveness -- not this
        check -- is its judge."""
        stage_map = PAINT_STAGE_MAPS["full-bleed"]
        second = {"x": 20.0, "y": 350.0, "w": 100.0, "h": 40.0}
        instances = {0: {"Untitled.mov": [
            probe.to_authored_rect(EXPECTED_SCREEN_RECT, stage_map),
            probe.to_authored_rect(second, stage_map),
        ]}}
        record = self._record(stage_map, [painting_video(second)], instances=instances)
        assert record["verdict"] is True
        assert record["instanceCheck"]["verdict"] is True

    @pytest.mark.parametrize(
        "raw",
        [
            True,
            None,
            {"error": "checkVisibility is unavailable in this browser"},
            [{"src": "Untitled.mov"}],
            [{"src": "Untitled.mov", "rect": {"x": 0.0, "y": 0.0, "w": float("nan"), "h": 10.0}}],
        ],
        ids=["true", "null", "error-object", "row-without-a-rect", "non-finite-rect"],
    )
    def test_a_malformed_painting_result_is_an_instrument_error_never_a_verdict(self, raw: Any) -> None:
        record = self._record(PAINT_STAGE_MAPS["full-bleed"], raw)
        assert record["status"] == "error"
        assert record["verdict"] is None
        assert "painting-video probe" in record["reason"]

    def test_an_instance_failure_does_not_promote_an_inconclusive_slide_to_red(self) -> None:
        """An unusable noise floor means the instrument is not trusted at all --
        the `Voff` control's required RED must never be earned that way."""
        def inconclusive_scorer(frames: Any, rects: Any, control: Any) -> dict[str, Any]:
            return {"verdict": None, "status": "inconclusive", "perRect": [], "stray": None, "noiseFloor": {}}

        record = self._record(
            PAINT_STAGE_MAPS["full-bleed"], [painting_video(DUPLICATE_SCREEN_RECT)], scorer=inconclusive_scorer,
        )
        assert record["verdict"] is None
        assert record["status"] == "inconclusive"
        assert record["instanceCheck"]["verdict"] is False


class TestExpectedRectClipping:
    """Codex R1 (probe MAJOR #2, second half): an expected rect that falls off
    the screenshot is a measurement the probe cannot make, not an ordinary red --
    scoring it would measure a truncated rect, and `Voff` would accept that as
    its required RED without ever seeing the raw-export defect."""

    def _record(self, authored: dict[str, float]) -> dict[str, Any]:
        host = FakeHost(scene_ids=["s", "s"])
        clock = FakeClock()
        return probe.visible_slide_record(
            host, VISIBLE_SLIDE, {0: {"Untitled.mov": [authored]}}, VISIBLE_VIEWPORT,
            scorer=passing_scorer, now=clock.now, sleep=clock.sleep,
        )

    @pytest.mark.parametrize(
        "authored",
        [
            {"x": 40.0, "y": 10.0, "w": 40.0, "h": 10.0},
            {"x": -5.0, "y": 10.0, "w": 20.0, "h": 10.0},
            {"x": 10.0, "y": 25.0, "w": 20.0, "h": 20.0},
            {"x": 10.0, "y": -1.0, "w": 20.0, "h": 10.0},
        ],
        ids=["off-right", "off-left", "off-bottom", "off-top"],
    )
    def test_a_rect_that_clips_off_the_screenshot_is_an_instrument_error(self, authored: dict[str, float]) -> None:
        record = self._record(authored)
        assert record["status"] == "error"
        assert record["verdict"] is None
        assert "clip outside" in record["reason"]
        assert record["expectedRects"], "the offending rect is still recorded as evidence"

    def test_a_rect_flush_with_the_screenshot_edges_is_scored_normally(self) -> None:
        record = self._record({"x": 0.0, "y": 0.0, "w": 64.0, "h": 32.0})
        assert record["verdict"] is True


class TestVisiblePassStageFitGate:
    """Codex R1 (probe MAJOR #2): V and Voff run in separate sessions, so a pass
    whose stage was shifted or cropped is not evidence -- and its slide verdicts
    must not be consulted at all."""

    def _base_result(self) -> dict[str, Any]:
        return TestOverallStatusTruthTable()._base_result()

    EXPECTED_FIT = {"x": 0.0, "y": 0.0, "width": 64.0, "height": 32.0}

    def _slides(self, *stage_maps: Any) -> list[dict[str, Any]]:
        return [{"stageMap": stage_map} for stage_map in stage_maps]

    def test_every_slides_burst_map_is_a_stage_fit_sample(self) -> None:
        samples = probe.visible_stage_samples(self._slides(FULL_BLEED_STAGE_MAP, FULL_BLEED_STAGE_MAP))
        result = probe.score_stage_fit(samples, self.EXPECTED_FIT)
        assert result["verdict"] is True
        assert result["sampleCount"] == 2

    def test_one_shifted_slide_fails_the_whole_pass(self) -> None:
        shifted = {**FULL_BLEED_STAGE_MAP, "ox": 12.0}
        samples = probe.visible_stage_samples(self._slides(FULL_BLEED_STAGE_MAP, shifted))
        result = probe.score_stage_fit(samples, self.EXPECTED_FIT)
        assert result["verdict"] is False
        assert result["mismatchCount"] == 1

    def test_a_slide_that_never_recorded_a_map_fails_the_pass(self) -> None:
        samples = probe.visible_stage_samples(self._slides(FULL_BLEED_STAGE_MAP, None))
        result = probe.score_stage_fit(samples, self.EXPECTED_FIT)
        assert result["verdict"] is False
        assert result["invalidCount"] == 1

    def test_a_pass_that_scored_nothing_has_no_stage_evidence_either(self) -> None:
        assert probe.score_stage_fit(probe.visible_stage_samples([]), self.EXPECTED_FIT)["verdict"] is False

    @pytest.mark.parametrize("name", ["V", "Voff"])
    def test_a_failed_stage_fit_fails_the_pass_and_hides_its_slide_verdicts(self, name: str) -> None:
        result = self._base_result()
        result["visible"][name]["stageFit"] = {"verdict": False}
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any(f"visible pass {name} stage fit failed" in reason for reason in reasons)
        assert not any(f"visible pass {name} slide" in reason for reason in reasons)

    @pytest.mark.parametrize("name", ["V", "Voff"])
    def test_a_missing_stage_fit_fails_closed(self, name: str) -> None:
        result = self._base_result()
        del result["visible"][name]["stageFit"]
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any(f"visible pass {name} stage fit missing" in reason for reason in reasons)

    def test_a_cropped_voff_cannot_supply_the_required_red(self) -> None:
        """The whole point: with a shifted stage, the expected rect can fall off
        the image and come back as an ordinary red that Voff would accept."""
        result = self._base_result()
        result["visible"]["Voff"]["stageFit"] = {"verdict": False}
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("visible pass Voff stage fit failed" in reason for reason in reasons)
        assert not any("blind" in reason for reason in reasons)


class TestVisiblePassStopError:
    """Codex R1 (probe MINOR): a `player.stop()` failure can leak Chrome into the
    next pass, so it fails the pass it happened in."""

    def _base_result(self) -> dict[str, Any]:
        return TestOverallStatusTruthTable()._base_result()

    @pytest.mark.parametrize("name", ["V", "Voff"])
    def test_a_stop_failure_fails_the_pass_and_is_reported(self, name: str) -> None:
        result = self._base_result()
        result["visible"][name]["stopError"] = "websocket closed"
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any(f"visible pass {name} player.stop() failed: websocket closed" in reason for reason in reasons)

    def test_a_clean_pass_reports_no_stop_reason(self) -> None:
        status, reasons = probe.overall_status(self._base_result())
        assert status == "pass"
        assert reasons == []


# --------------------------------------------------------------------------
# Baseline refusal (I3): plan-derived expectations, `refused*`, live/dead rects
#
# `.agents/plans/keynote_live_baseline.plan.md` §1/§4: a boundary the plan
# RETIRES hands its movie back to the raw player. Nothing below is hard-wired to
# "slide 2" -- every expectation is derived from the plan the host installs, and a
# plan WITHOUT a retire must reproduce the pre-refusal model exactly.
# --------------------------------------------------------------------------

BIG_ASSET = "Untitled.mov"
OTHER_ASSET = "WA0125.mov"
BIG_INSTANCE = {"x": 109.0, "y": 795.0, "w": 952.0, "h": 268.0}
SMALL_INSTANCE = {"x": 1076.0, "y": 876.0, "w": 663.0, "h": 186.0}
OTHER_INSTANCE = {"x": 300.0, "y": 100.0, "w": 400.0, "h": 200.0}

# The measured fixture's scene onsets: slide 1 opens at scene 0, the 1->2 magic
# move lands at 2, the 2->3 restart at 6, the 3->4 bridge at 8.
SCENE_INDEX_BY_PLAYER = {0: 0, 1: 2, 2: 6, 3: 8}
SLIDE_INSTANCES = {
    0: {BIG_ASSET: [BIG_INSTANCE], OTHER_ASSET: [OTHER_INSTANCE]},
    1: {BIG_ASSET: [BIG_INSTANCE]},
    2: {BIG_ASSET: [BIG_INSTANCE, SMALL_INSTANCE]},
    3: {BIG_ASSET: [BIG_INSTANCE]},
}

RUNTIME_MOVIES = {"movie1": {"assetKeys": ["untitled.mov"], "footprint": {"x": 109, "y": 795, "w": 952, "h": 268}}}
RESTART_BOUNDARY = {"atScene": 6, "action": "restart"}
BRIDGE_BOUNDARY = {
    "atScene": 8, "action": "bridge", "movieKey": "movie1",
    "srcRect": {"x": 198, "y": 797, "w": 952, "h": 268}, "durationSeconds": 1.5,
    "rect": {"x": 327, "y": 709, "w": 1266, "h": 356},
}
RETIRE_BOUNDARY = {"atScene": 2, "action": "retire", "movieKey": "movie1"}

CARRIED_RUNTIME = {"movies": RUNTIME_MOVIES, "boundaries": [RESTART_BOUNDARY, BRIDGE_BOUNDARY]}
RETIRED_RUNTIME = {"movies": RUNTIME_MOVIES, "boundaries": [RETIRE_BOUNDARY, RESTART_BOUNDARY, BRIDGE_BOUNDARY]}
BRIDGE_ONLY_RUNTIME = {"movies": RUNTIME_MOVIES, "boundaries": [BRIDGE_BOUNDARY]}

BOUNDARY_KEYS = {2: "continue1to2", 6: "restart2to3", 8: "continue3to4"}


def synthetic_plan(
    scene_index: dict[int, int] | None = None, instances: dict[int, Any] | None = None
) -> Any:
    """A `ContinuityPlan` carrying only what the expectation model reads: the scene
    onset of each slide and every authored movie instance on it."""
    return probe.ContinuityPlan(
        canvas={"width": 1920, "height": 1080},
        scene_index_by_player=dict(SCENE_INDEX_BY_PLAYER if scene_index is None else scene_index),
        slide_rects={},
        boundaries=(),
        slide_instances=dict(SLIDE_INSTANCES if instances is None else instances),
    )


class TestRectExpectationModel:
    """The whole live/dead table, derived from the plan alone (plan §4, "V/Voff
    expectation model")."""

    def test_a_plan_without_a_retire_is_todays_model_unchanged(self) -> None:
        """V live everywhere; Voff dead only at the geometry-static pin's
        destination, which is exactly the slide today's hardcoded control reds on."""
        plan = synthetic_plan()
        on = probe.rect_expectations(plan, CARRIED_RUNTIME, continuity_on=True)
        off = probe.rect_expectations(plan, CARRIED_RUNTIME, continuity_on=False)
        assert on == {
            0: {BIG_ASSET: "live", OTHER_ASSET: "live"},
            1: {BIG_ASSET: "live"},
            2: {BIG_ASSET: "live"},
            3: {BIG_ASSET: "live"},
        }
        assert off == {
            0: {BIG_ASSET: "live", OTHER_ASSET: "live"},
            1: {BIG_ASSET: "dead"},
            2: {BIG_ASSET: "live"},
            3: {BIG_ASSET: "live"},
        }

    def test_the_fixture_plan_with_a_retire_at_scene_two_is_dead_in_both_passes(self) -> None:
        """V: s1 live, s2 dead, s3 live, s4 live -- and Voff the same, because a
        refused boundary leaves the destination looking exactly like the raw export."""
        plan = synthetic_plan()
        expected = {
            0: {BIG_ASSET: "live", OTHER_ASSET: "live"},
            1: {BIG_ASSET: "dead"},
            2: {BIG_ASSET: "live"},
            3: {BIG_ASSET: "live"},
        }
        assert probe.rect_expectations(plan, RETIRED_RUNTIME, continuity_on=True) == expected
        assert probe.rect_expectations(plan, RETIRED_RUNTIME, continuity_on=False) == expected

    def test_a_bridge_only_plan_keeps_every_uncut_boundary_implicitly_pinned(self) -> None:
        """No restart and no retire: the bridge destination is live in both passes,
        every other destination is a carried pin."""
        plan = synthetic_plan()
        on = probe.rect_expectations(plan, BRIDGE_ONLY_RUNTIME, continuity_on=True)
        off = probe.rect_expectations(plan, BRIDGE_ONLY_RUNTIME, continuity_on=False)
        assert [on[i][BIG_ASSET] for i in (0, 1, 2, 3)] == ["live", "live", "live", "live"]
        assert [off[i][BIG_ASSET] for i in (0, 1, 2, 3)] == ["live", "dead", "dead", "live"]

    def test_only_the_retired_asset_goes_dead_on_a_refused_destination(self) -> None:
        """A second movie on the same destination slide follows its own (carried)
        expectation -- the refusal is per movie, not per slide."""
        instances = dict(SLIDE_INSTANCES)
        instances[1] = {BIG_ASSET: [BIG_INSTANCE], OTHER_ASSET: [OTHER_INSTANCE]}
        on = probe.rect_expectations(synthetic_plan(instances=instances), RETIRED_RUNTIME, continuity_on=True)
        assert on[1] == {BIG_ASSET: "dead", OTHER_ASSET: "live"}

    def test_both_passes_are_derived_in_one_call(self) -> None:
        plan = synthetic_plan()
        both = probe.visible_expectations(plan, RETIRED_RUNTIME)
        assert both["V"] == probe.rect_expectations(plan, RETIRED_RUNTIME, continuity_on=True)
        assert both["Voff"] == probe.rect_expectations(plan, RETIRED_RUNTIME, continuity_on=False)


class TestRetireFact:
    def test_no_retire_is_none_so_nothing_downstream_changes(self) -> None:
        assert probe.retire_fact(synthetic_plan(), CARRIED_RUNTIME, BOUNDARY_KEYS) is None

    def test_the_retire_resolves_to_its_boundary_slide_asset_keys_and_rects(self) -> None:
        retire = probe.retire_fact(synthetic_plan(), RETIRED_RUNTIME, BOUNDARY_KEYS)
        assert retire["boundaryKey"] == "continue1to2"
        assert retire["verdictKey"] == "refused1to2"
        assert retire["playerIndex"] == 1 and retire["originalOrdinal"] == 2
        assert retire["assetKeys"] == ["untitled.mov"]
        assert retire["rects"] == [BIG_INSTANCE]

    def test_a_retire_at_a_scene_no_boundary_under_test_owns_fails_closed(self) -> None:
        runtime = {"movies": RUNTIME_MOVIES, "boundaries": [{"atScene": 4, "action": "retire", "movieKey": "movie1"}]}
        with pytest.raises(SystemExit):
            probe.retire_fact(synthetic_plan(), runtime, BOUNDARY_KEYS)

    def test_a_retire_naming_an_undefined_movie_key_fails_closed(self) -> None:
        runtime = {"movies": RUNTIME_MOVIES, "boundaries": [dict(RETIRE_BOUNDARY, movieKey="movie9")]}
        with pytest.raises(SystemExit):
            probe.retire_fact(synthetic_plan(), runtime, BOUNDARY_KEYS)

    def test_more_than_one_retire_is_outside_the_contract_and_fails_closed(self) -> None:
        runtime = {"movies": RUNTIME_MOVIES, "boundaries": [RETIRE_BOUNDARY, dict(RETIRE_BOUNDARY, atScene=6)]}
        with pytest.raises(SystemExit):
            probe.retire_fact(synthetic_plan(), runtime, BOUNDARY_KEYS)


class TestRefusalScoring:
    """The POSITIVE half: "did not continue" alone is vacuous, so the refusal has
    to be shown on the destination slide's DOM."""

    STAGE_MAP = {"s": 1.0, "sy": 1.0, "ox": 0.0, "oy": 0.0, "offsetWidth": 1920.0, "offsetHeight": 1080.0}
    RETIRE = {"assetKeys": ["untitled.mov"], "rects": [BIG_INSTANCE]}

    def _sample(self, painting: Any = None, snapshot: Any = None, stage_map: Any = _UNSET) -> dict[str, Any]:
        return {
            "stageMap": dict(self.STAGE_MAP) if stage_map is _UNSET else stage_map,
            "painting": [] if painting is None else painting,
            "poolSnapshot": [] if snapshot is None else snapshot,
        }

    def test_a_clean_refusal_is_green(self) -> None:
        scored = probe.score_refusal(self._sample(), self.RETIRE, True)
        assert scored["verdict"] is True
        assert scored["paintingOverRect"] == [] and scored["pooled"] == []
        assert scored["reason"] is None

    def test_a_painting_video_over_the_retired_rect_is_red(self) -> None:
        scored = probe.score_refusal(
            self._sample(painting=[painting_video(BIG_INSTANCE)]), self.RETIRE, True
        )
        assert scored["verdict"] is False
        assert "overlap the retired movie" in scored["reason"]

    def test_a_painting_video_elsewhere_on_the_slide_does_not_refute_the_refusal(self) -> None:
        elsewhere = {"x": 1200.0, "y": 100.0, "w": 300.0, "h": 200.0}
        scored = probe.score_refusal(self._sample(painting=[painting_video(elsewhere)]), self.RETIRE, True)
        assert scored["verdict"] is True

    def test_an_edge_touching_video_is_not_an_overlap(self) -> None:
        touching = {"x": BIG_INSTANCE["x"] + BIG_INSTANCE["w"], "y": BIG_INSTANCE["y"], "w": 200.0, "h": 100.0}
        scored = probe.score_refusal(self._sample(painting=[painting_video(touching)]), self.RETIRE, True)
        assert scored["verdict"] is True

    def test_a_pooled_decoder_for_the_retired_asset_is_red(self) -> None:
        scored = probe.score_refusal(
            self._sample(snapshot=[{"key": "untitled.mov", "elId": 1}]), self.RETIRE, True
        )
        assert scored["verdict"] is False
        assert "pooled/preserved" in scored["reason"]

    def test_another_assets_pooled_decoder_is_irrelevant(self) -> None:
        scored = probe.score_refusal(self._sample(snapshot=[{"key": "wa0125.mov"}]), self.RETIRE, True)
        assert scored["verdict"] is True

    def test_the_pool_is_not_consulted_when_no_runtime_is_installed(self) -> None:
        scored = probe.score_refusal(self._sample(snapshot=None), self.RETIRE, False)
        assert scored["verdict"] is True

    def test_an_unreadable_pool_census_is_red_never_a_silently_clean_one(self) -> None:
        scored = probe.score_refusal(self._sample(snapshot={"error": "boom"}), self.RETIRE, True)
        assert scored["verdict"] is False
        assert "preserve snapshot is unreadable" in scored["reason"]

    def test_a_missing_sample_is_red_not_a_free_pass(self) -> None:
        scored = probe.score_refusal(None, self.RETIRE, True)
        assert scored["verdict"] is False
        assert "no refusal evidence" in scored["reason"]

    @pytest.mark.parametrize("stage_map", [None, {"s": 0, "sy": 0, "offsetWidth": 0, "offsetHeight": 0}])
    def test_an_untrustworthy_stage_map_is_red(self, stage_map: Any) -> None:
        scored = probe.score_refusal(self._sample(stage_map=stage_map), self.RETIRE, True)
        assert scored["verdict"] is False
        assert "stage map" in scored["reason"]

    def test_a_malformed_painting_result_is_red(self) -> None:
        scored = probe.score_refusal(self._sample(painting={"error": "no checkVisibility"}), self.RETIRE, True)
        assert scored["verdict"] is False

    def test_score_refusals_is_keyed_by_the_plans_own_boundary(self) -> None:
        retire = probe.retire_fact(synthetic_plan(), RETIRED_RUNTIME, BOUNDARY_KEYS)
        scored = probe.score_refusals({"refused1to2": self._sample()}, {"retire": retire}, True)
        assert list(scored) == ["refused1to2"]
        assert scored["refused1to2"]["verdict"] is True

    def test_a_plan_without_a_retire_scores_no_refusal_at_all(self) -> None:
        assert probe.score_refusals({}, {"retire": None}, True) == {}


class TestRefusedArmTable:
    """The arm expectations, derived from the plan rather than hard-wired."""

    def _result(self) -> dict[str, Any]:
        """The base artifact, re-expressed for a plan that RETIRES the 1->2
        boundary: the carry verdict goes False and the positive verdict carries the
        refusal. Arm B is continuity-off and keeps today's expectations."""
        result = TestOverallStatusTruthTable()._base_result()
        result["groundTruth"]["refusedBoundaries"] = ["continue1to2"]
        for entry in (result["arms"]["A"], result["arms"]["C"], result["attach"]):
            entry["continue1to2"] = {"verdict": False}
            entry["refused1to2"] = {"verdict": True, "reason": None}
        return result

    def test_a_retired_boundary_that_did_not_carry_and_proved_it_passes(self) -> None:
        status, reasons = probe.overall_status(self._result())
        assert status == "pass"
        assert reasons == []

    @pytest.mark.parametrize("arm", ["A", "C", "attach"])
    def test_carrying_a_retired_boundary_fails_the_arm(self, arm: str) -> None:
        """The runtime ignored the refusal: the movie crossed the boundary anyway."""
        result = self._result()
        entry = result["attach"] if arm == "attach" else result["arms"][arm]
        entry["continue1to2"] = {"verdict": True}
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("expected False (the plan retires this boundary)" in reason for reason in reasons)

    @pytest.mark.parametrize("arm", ["A", "C", "attach"])
    def test_a_false_positive_half_fails_the_arm_with_its_reason(self, arm: str) -> None:
        """A painting video still over the rect, or a pooled decoder for the key."""
        result = self._result()
        entry = result["attach"] if arm == "attach" else result["arms"][arm]
        entry["refused1to2"] = {"verdict": False, "reason": "1 painting video(s) still overlap the retired movie"}
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("still overlap the retired movie" in reason for reason in reasons)

    @pytest.mark.parametrize("arm", ["A", "C", "attach"])
    def test_a_missing_positive_half_fails_with_its_own_reason(self, arm: str) -> None:
        """"Did not continue" without the positive half is vacuous -- and it must
        not read as inconclusive either, which would hide it behind the sampler."""
        result = self._result()
        entry = result["attach"] if arm == "attach" else result["arms"][arm]
        del entry["refused1to2"]
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("has no refused1to2 verdict, so the refusal is unproven" in reason for reason in reasons)

    def test_an_inconclusive_carry_verdict_still_reads_inconclusive(self) -> None:
        result = self._result()
        result["arms"]["A"]["continue1to2"] = {"verdict": None}
        status, _ = probe.overall_status(result)
        assert status == "inconclusive"

    def test_arm_b_keeps_todays_expectations_under_a_refusal(self) -> None:
        """Continuity is off there, so the retire says nothing about it."""
        result = self._result()
        assert result["arms"]["B"]["continue1to2"] == {"verdict": True}
        assert probe.overall_status(result)[0] == "pass"

    def test_without_a_retire_a_carried_boundary_must_still_be_true(self) -> None:
        result = TestOverallStatusTruthTable()._base_result()
        result["arms"]["A"]["continue1to2"] = {"verdict": False}
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("expected True (the plan carries this boundary)" in reason for reason in reasons)

    def test_an_unknown_refused_boundary_name_is_ignored_rather_than_trusted(self) -> None:
        result = TestOverallStatusTruthTable()._base_result()
        result["groundTruth"]["refusedBoundaries"] = ["continue9to10"]
        assert probe.overall_status(result)[0] == "pass"


def expectation_slide(ordinal: int, rects: list[tuple[str, str, bool | None]], status: str | None = None) -> dict[str, Any]:
    """One visible-pass record as the scorer leaves it: each rect carries the
    expectation the plan stated and the verdict it earned against that expectation."""
    verdict = all(met is True for _, _, met in rects)
    return {
        "playerIndex": ordinal - 1, "originalOrdinal": ordinal,
        "verdict": verdict, "status": status or ("pass" if verdict else "fail"),
        "perRect": [{"label": label, "expect": expect, "verdict": met} for label, expect, met in rects],
    }


class TestVisibleExpectationModel:
    """Plan §4: both passes are scored against the plan's own per-rect
    expectations, and each proves itself two-sided from the inside."""

    LIVE_OK = (f"{BIG_ASSET}#1", "live", True)
    LIVE_RED = (f"{BIG_ASSET}#1", "live", False)
    DEAD_OK = (f"{BIG_ASSET}#1", "dead", True)
    DEAD_RED = (f"{BIG_ASSET}#1", "dead", False)

    def _result(self) -> dict[str, Any]:
        """The baseline artifact: slide 2 is dead-expected in BOTH passes because
        the plan refuses to carry the 1->2 boundary."""
        result = TestOverallStatusTruthTable()._base_result()
        result["groundTruth"]["refusedBoundaries"] = ["continue1to2"]
        result["groundTruth"]["rectExpectations"] = probe.visible_expectations(
            synthetic_plan(), RETIRED_RUNTIME
        )
        for entry in (result["arms"]["A"], result["arms"]["C"], result["attach"]):
            entry["continue1to2"] = {"verdict": False}
            entry["refused1to2"] = {"verdict": True, "reason": None}
        slides = [
            expectation_slide(1, [self.LIVE_OK]), expectation_slide(2, [self.DEAD_OK]),
            expectation_slide(3, [self.LIVE_OK]), expectation_slide(4, [self.LIVE_OK]),
        ]
        for name in ("V", "Voff"):
            result["visible"][name]["slides"] = [dict(slide) for slide in slides]
            result["visible"][name]["verdict"] = True
        return result

    def test_both_passes_meeting_every_expectation_pass(self) -> None:
        status, reasons = probe.overall_status(self._result())
        assert status == "pass"
        assert reasons == []

    def test_v_slide_two_live_where_dead_was_expected_fails(self) -> None:
        """The carried movie is still painting on the refused destination."""
        result = self._result()
        result["visible"]["V"]["slides"][1] = expectation_slide(2, [self.DEAD_RED])
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("visible pass V slide 2 does not meet its per-rect expectations" in r for r in reasons)

    def test_v_slide_four_dead_where_live_was_expected_fails(self) -> None:
        """The surviving carry must still be visibly live -- a refusal elsewhere is
        no licence for a dead bridge destination."""
        result = self._result()
        result["visible"]["V"]["slides"][3] = expectation_slide(4, [self.LIVE_RED])
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("visible pass V slide 4 does not meet its per-rect expectations" in r for r in reasons)

    def test_voff_slide_two_live_where_dead_was_expected_fails(self) -> None:
        result = self._result()
        result["visible"]["Voff"]["slides"][1] = expectation_slide(2, [self.DEAD_RED])
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("visible pass Voff slide 2" in r for r in reasons)

    def test_a_pass_with_no_live_read_rect_is_always_red_and_fails(self) -> None:
        """Every rect dead-expected and dead: the slides all "pass", but the pass
        has proved nothing about an instrument that reds out on anything."""
        result = self._result()
        result["visible"]["V"]["slides"] = [
            expectation_slide(ordinal, [self.DEAD_OK]) for ordinal in (1, 2, 3, 4)
        ]
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("no live-expected rect that read live" in r for r in reasons)

    def test_a_pass_that_never_read_its_dead_rect_dead_is_blind_and_fails(self) -> None:
        """Slide 2's dead expectation is the only proof the pass can see a frozen
        movie at all; an inconclusive slide 2 does not supply it."""
        result = self._result()
        result["visible"]["V"]["slides"][1] = {
            "playerIndex": 1, "originalOrdinal": 2, "verdict": None, "status": "inconclusive", "perRect": [],
        }
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("blind to a frozen movie" in r for r in reasons)

    def test_an_inconclusive_slide_never_counts_as_meeting_an_expectation(self) -> None:
        slide = expectation_slide(2, [self.DEAD_OK], status="inconclusive")
        counts = probe.visible_rect_expectation_counts({"slides": [slide]})
        assert counts == {"liveTotal": 0, "liveMet": 0, "deadTotal": 0, "deadMet": 0}

    def test_a_pass_without_stated_expectations_keeps_todays_rules_exactly(self) -> None:
        """A record with no per-rect expectations at all (the pre-refusal shape) is
        still scored by the V-live-everywhere / Voff-red-at-the-boundary rules."""
        result = TestOverallStatusTruthTable()._base_result()
        assert probe.overall_status(result) == ("pass", [])
        result["visible"]["Voff"]["slides"][1]["verdict"] = True
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("blind to the raw-export defect" in r for r in reasons)

    def test_counts_are_two_sided_and_per_pass(self) -> None:
        counts = probe.visible_rect_expectation_counts(self._result()["visible"]["V"])
        assert counts == {"liveTotal": 3, "liveMet": 3, "deadTotal": 1, "deadMet": 1}


class TestExpectedRectsCarryTheirExpectation:
    def test_an_asset_the_plan_calls_dead_is_labelled_dead(self) -> None:
        expectations = {1: {BIG_ASSET: "dead"}}
        rects = probe.expected_screen_rects({1: {BIG_ASSET: [BIG_INSTANCE]}}, 1, IDENTITY_STAGE_MAP, expectations)
        assert [rect["expect"] for rect in rects] == ["dead"]

    def test_an_unmentioned_asset_is_expected_live_which_is_the_stricter_reading(self) -> None:
        rects = probe.expected_screen_rects({1: {BIG_ASSET: [BIG_INSTANCE]}}, 1, IDENTITY_STAGE_MAP, {1: {}})
        assert [rect["expect"] for rect in rects] == ["live"]

    def test_without_expectations_every_rect_is_live_exactly_as_before(self) -> None:
        rects = probe.expected_screen_rects(VISIBLE_INSTANCES, 0, IDENTITY_STAGE_MAP)
        assert [rect["expect"] for rect in rects] == ["live"]

    def test_every_instance_of_a_dead_asset_is_dead(self) -> None:
        rects = probe.expected_screen_rects(
            {2: {BIG_ASSET: [BIG_INSTANCE, SMALL_INSTANCE]}}, 2, IDENTITY_STAGE_MAP, {2: {BIG_ASSET: "dead"}}
        )
        assert [rect["expect"] for rect in rects] == ["dead", "dead"]


class TestPaintingVideoOnADeadRect:
    """A dead-expected rect must have NO painting `<video>` matched to it: the plan
    says that movie is back under the raw player, so a `<video>` there is a defect
    however live its pixels look."""

    def _expected(self, expect: str) -> list[dict[str, Any]]:
        return [{"label": "movie1#1", "authored": dict(EXPECTED_SCREEN_RECT), "expect": expect}]

    def test_a_video_on_a_dead_expected_rect_is_unexpected(self) -> None:
        videos = [{"src": "Untitled.mov", "elId": 1, "authored": dict(EXPECTED_SCREEN_RECT)}]
        scored = probe.match_painting_videos(videos, self._expected("dead"))
        assert scored["verdict"] is False
        assert len(scored["unexpectedVideos"]) == 1
        assert scored["unexpectedVideos"][0]["bestExpect"] == "dead"
        assert scored["duplicateVideos"] == []

    def test_the_same_video_on_a_live_expected_rect_claims_it(self) -> None:
        videos = [{"src": "Untitled.mov", "elId": 1, "authored": dict(EXPECTED_SCREEN_RECT)}]
        assert probe.match_painting_videos(videos, self._expected("live"))["verdict"] is True

    def test_a_dead_expected_rect_with_no_painting_video_is_green(self) -> None:
        assert probe.match_painting_videos([], self._expected("dead"))["verdict"] is True


class TestDeadExpectationEndToEndInARecord:
    """The wiring from the plan's expectation to the real scorer and the DOM
    instance check, which the per-function tests above cannot see."""

    STAGE_MAP = PAINT_STAGE_MAPS["full-bleed"]

    def _record(self, expectations: Any, painting: Any = None) -> dict[str, Any]:
        from obed_edom.html_alpha_probe import score_visible_slide

        host = FakeHost(
            scene_ids=["s", "s"], stage_map=dict(self.STAGE_MAP),
            painting=[] if painting is None else painting, shot=png_b64(*PAINT_VIEWPORT),
        )
        clock = FakeClock()
        instances = {0: {"Untitled.mov": [probe.to_authored_rect(EXPECTED_SCREEN_RECT, self.STAGE_MAP)]}}
        return probe.visible_slide_record(
            host, VISIBLE_SLIDE, instances, PAINT_VIEWPORT, scorer=score_visible_slide,
            expectations=expectations, now=clock.now, sleep=clock.sleep,
        )

    def test_a_frozen_rect_the_plan_expects_dead_is_green(self) -> None:
        record = self._record({0: {"Untitled.mov": "dead"}})
        assert record["verdict"] is True and record["status"] == "pass"
        assert record["expectedRects"][0]["expect"] == "dead"
        assert record["perRect"][0]["expect"] == "dead"

    def test_the_same_frozen_rect_is_red_when_the_plan_expects_it_live(self) -> None:
        record = self._record({0: {"Untitled.mov": "live"}})
        assert record["verdict"] is False
        assert record["perRect"][0]["expect"] == "live"

    def test_a_painting_video_on_a_dead_expected_rect_reds_the_slide(self) -> None:
        """Pixels alone call this slide green -- only the DOM can see that the
        refused movie still has a `<video>` on its rect."""
        record = self._record(
            {0: {"Untitled.mov": "dead"}}, painting=[painting_video(EXPECTED_SCREEN_RECT)]
        )
        assert record["verdict"] is False and record["status"] == "fail"
        assert record["instanceCheck"]["unexpectedVideos"][0]["bestExpect"] == "dead"


def test_burst_is_long_enough_that_a_two_state_movie_cannot_plausibly_alias():
    # The fixture movie is a two-state grating that flips every video frame. With n
    # shots at effectively independent phases, P(every shot lands on the same state)
    # = 2 * 0.5**n. The original 5-shot burst gave 6.25 % per live rect - measured:
    # 2 dead reads in 24 healthy live-expected rects at 2560x1440 - which is a false
    # RED about once per gate chain. 12 shots put it at ~0.05 %, unchanged by the
    # spacing fix in plan keynote_live_paint_oracle.plan.md SS14 (still 12 shots).
    shots = len(probe.BURST_OFFSETS_MS)
    assert 2 * 0.5 ** shots < 0.001
    gaps = [b - a for a, b in zip(probe.BURST_OFFSETS_MS, probe.BURST_OFFSETS_MS[1:])]
    assert min(gaps) >= 350
    assert len(set(gaps)) >= 2


def _inpage_raw(
    *, live: bool, n_bands: int = probe.INPAGE_BAND_COUNT, n: int = probe.INPAGE_MIN_SAMPLES,
    paused_n: int = probe.INPAGE_MIN_SAMPLES, epoch: int = 1, marker_epoch: int | None = None,
) -> dict[str, Any]:
    """A synthetic `INPAGE_LIVENESS_JS` result: every band ramps (LIVE) or holds
    constant (DEAD), a usable occluder mask (markers differ by 100), and a
    paused-decoder control window -- sized at the fixed `INPAGE_MIN_SAMPLES`,
    never a magic 8/30 (Codex r1 Spec 6) -- that itself reads DEAD, the shape
    a passing in-page read must have."""
    samples = [
        {
            "t": t, "ms": float(t), "vt": t * 0.033, "mediaTime": t * 0.033,
            "bands": [100.0 + (t % 10) * 3.0 for _ in range(n_bands)] if live else [100.0] * n_bands,
            "control": 50.0, "green": 80.0, "greenRGB": [10.0, 200.0, 10.0], "glErr": 0,
        }
        for t in range(n)
    ]
    paused = [
        {
            "t": 1000 + t, "ms": 1000.0 + t, "vt": None, "mediaTime": None,
            "bands": [100.0] * n_bands, "control": 50.0, "green": 80.0,
            "greenRGB": [10.0, 200.0, 10.0], "glErr": 0,
        }
        for t in range(paused_n)
    ]
    return {
        "applicable": True, "status": "ok", "canvasId": "canvas-1", "epoch": epoch,
        "samples": samples, "pausedDecoderSamples": paused,
        "markerDark": [0.0] * n_bands, "markerLight": [100.0] * n_bands,
        "markerEpoch": epoch if marker_epoch is None else marker_epoch,
    }


class TestBurstPoke:
    def test_burst_poke_is_off_by_default(self) -> None:
        host = FakeHost(scene_ids=[])
        clock = FakeClock()
        probe.capture_burst(host.transport, now=clock.now, sleep=clock.sleep)
        assert probe.BURST_POKE_JS not in host.transport.evaluations

    def test_burst_poke_evaluates_once_per_shot_when_requested(self) -> None:
        host = FakeHost(scene_ids=[])
        clock = FakeClock()
        probe.capture_burst(host.transport, poke=True, now=clock.now, sleep=clock.sleep)
        assert host.transport.evaluations.count(probe.BURST_POKE_JS) == len(probe.BURST_OFFSETS_MS)

    def test_burst_poke_flag_defaults_false_in_parse_args(self) -> None:
        args = probe.parse_args([])
        assert args.burst_poke is False

    def test_poke_is_the_e0_qualified_painted_element_poke(self) -> None:
        """Codex r1 Spec 7: `--burst-poke` must be the E0-qualified painted
        1x1-element poke (`output/research-harnesses/live-visible-content/
        alt-oracle/oracle.py` POKE_JS), not an unused CSS custom property."""
        assert "__orpoke" in probe.BURST_POKE_JS
        assert "position:fixed" in probe.BURST_POKE_JS
        assert "width:1px;height:1px" in probe.BURST_POKE_JS
        assert "style.background=" in probe.BURST_POKE_JS
        assert "Math.random()" in probe.BURST_POKE_JS


class TestBurstProfileArtifact:
    def test_record_carries_the_burst_profile(self) -> None:
        host = FakeHost(scene_ids=["scene-1", "scene-1"])
        clock = FakeClock()
        record = probe.visible_slide_record(
            host, VISIBLE_SLIDE, VISIBLE_INSTANCES, VISIBLE_VIEWPORT,
            scorer=passing_scorer, now=clock.now, sleep=clock.sleep,
        )
        profile = record["burstProfile"]
        assert profile["offsetsMs"] == [float(v) for v in probe.BURST_OFFSETS_MS]
        assert profile["poke"] is False
        assert profile["fromSurface"] is False
        assert profile["uniqueShas"] == 1
        assert len(profile["shas"]) == len(probe.BURST_OFFSETS_MS)

    def test_unique_shas_do_not_affect_the_verdict(self) -> None:
        shots = [png_b64(*VISIBLE_VIEWPORT, fill=i % 250) for i in range(len(probe.BURST_OFFSETS_MS))]
        host = FakeHost(scene_ids=["scene-1", "scene-1"], shots=shots)
        clock = FakeClock()
        record = probe.visible_slide_record(
            host, VISIBLE_SLIDE, VISIBLE_INSTANCES, VISIBLE_VIEWPORT,
            scorer=passing_scorer, now=clock.now, sleep=clock.sleep,
        )
        assert record["burstProfile"]["uniqueShas"] == len(probe.BURST_OFFSETS_MS)
        assert record["verdict"] is True


def _base_shaped_record(
    host: "FakeHost", slide: dict[str, Any], instances: dict[int, dict[str, list[Any]]],
    viewport: tuple[int, int], scorer: Any, clock: "FakeClock",
) -> dict[str, Any]:
    """Regenerates `tests/fixtures/live_continuity_probe/base_shaped_record.json`
    (Codex r3 Spec 5): the origin/main record shape, built by driving the SAME
    pre-existing primitives `visible_slide_record` itself calls (settle wait,
    scene, stage map, burst capture, expected rects, instance check, control,
    scorer) -- literally the pre-oracle record path. NOT called by any test;
    kept only so the golden fixture can be regenerated deliberately (never
    silently) when one of those primitives intentionally changes shape. See
    that JSON's own `_provenance` field for the exact call this reproduces."""
    transport = host._require_transport()
    assert probe.wait_until_settled(host, now=clock.now, sleep=clock.sleep)
    scene_id = transport.evaluate(probe.SCENE_ID_JS)
    stage_map = transport.evaluate(probe.STAGE_MAP_JS)
    painting_raw = transport.evaluate(probe.PAINTING_VIDEOS_JS)
    frames, offsets = probe.capture_burst(transport, now=clock.now, sleep=clock.sleep)
    expected = probe.expected_screen_rects(instances, slide["playerIndex"], stage_map, None)
    painting = probe.painting_videos(painting_raw, stage_map)
    instance_check = probe.match_painting_videos(painting, expected)
    control = probe.control_region(probe.stage_screen_rect(stage_map), viewport)
    scored = scorer(
        frames,
        [{**item["screen"], "label": item["label"], "expect": item["expect"]} for item in expected],
        control,
    )
    verdict, status = scored.get("verdict"), scored.get("status")
    if verdict is True and not instance_check["verdict"]:
        verdict, status = False, "fail"
    return {
        "playerIndex": int(slide["playerIndex"]), "originalOrdinal": slide.get("originalOrdinal"),
        "sceneId": scene_id, "expectedRects": expected, "perRect": scored.get("perRect") or [],
        "stray": scored.get("stray"), "noiseFloor": scored.get("noiseFloor"), "shotOffsetsMs": offsets,
        "stageMap": stage_map, "instanceCheck": instance_check, "status": status, "verdict": verdict,
        "attempts": 1, "control": control,
    }


class TestInPageOracleApplicability:
    """The JS predicate cannot run in pytest, so these test the Python
    handling of each `reason` the JS could return, plus the JS source's own
    fail-closed shape (never a speculative `getContext`)."""

    # Codex r4: only an ABSENT handle may be n/a. Every other "not applicable"
    # claim the JS could make -- and any malformed n/a-shaped response -- is an
    # APPLICABLE inconclusive result, so a present-but-unusable handle can never
    # silently hand the rect back to the screenshot oracle alone.
    NON_ABSENCE_REASONS = [
        "canvas is not a descendant of #stage",
        "canvas disconnected or context lost",
        "canvas does not cover the movie rect",
        "canvas or an ancestor is not fully opaque",
        "checkVisibility is false",
        "handle is present but malformed",
        "",
        None,
    ]

    def test_only_an_absent_handle_is_not_applicable(self) -> None:
        raw = {"applicable": False, "status": "n/a", "reason": probe.INPAGE_HANDLE_ABSENT_REASON}
        assert probe.inpage_oracle_result(raw) is None
        assert probe.INPAGE_HANDLE_ABSENT_REASON in probe.INPAGE_LIVENESS_JS

    @pytest.mark.parametrize("reason", NON_ABSENCE_REASONS)
    def test_every_other_n_a_claim_is_an_applicable_inconclusive(self, reason: object) -> None:
        raw = {"applicable": False, "status": "n/a", "reason": reason}
        result = probe.inpage_oracle_result(raw)
        assert result is not None
        assert result["verdict"] is None and result["status"] == "inconclusive"

    # Codex r3 Spec 5: compare against a FIXED literal/checked-in golden, not a
    # dynamically re-derived one -- the primitives below could otherwise drift
    # in lockstep with the branch and never show a real difference. The golden
    # was generated ONCE by driving the pre-existing (pre-oracle) primitives
    # `visible_slide_record` itself calls (`wait_until_settled`,
    # `capture_burst`, `expected_screen_rects`, `painting_videos`,
    # `match_painting_videos`, `control_region`, `stage_screen_rect`,
    # `score_visible_slide`) over the same `FakeHost`/`instances` fixture this
    # test builds; see the JSON file's own `_provenance` field for the exact
    # recipe to regenerate it if one of those primitives intentionally changes
    # shape.
    GOLDEN_BASE_RECORD_PATH = (
        Path(__file__).parent / "fixtures" / "live_continuity_probe" / "base_shaped_record.json"
    )

    def test_no_gl_handle_records_not_applicable_and_changes_nothing(self) -> None:
        """Full base-shaped golden compare (Codex r2 Spec 7; Codex r3 Spec 5
        fixes the golden to a checked-in literal): the branch's record must be
        IDENTICAL, field for field, to the FIXED golden -- scene, expected
        rects, stage map, instance check, attempts, and control included, not
        only the scorer's own verdict -- exempting only `shotOffsetsMs`, and
        permitting only the documented additive `burstProfile` and per-rect
        `oracles` keys."""
        from obed_edom.html_alpha_probe import score_visible_slide

        stage_map = PAINT_STAGE_MAPS["full-bleed"]
        shot = png_b64(*PAINT_VIEWPORT)
        instances = {0: {"Untitled.mov": [probe.to_authored_rect(EXPECTED_SCREEN_RECT, stage_map)]}}

        clock = FakeClock()
        host = FakeHost(scene_ids=["s"] * 8, stage_map=dict(stage_map), shot=shot)
        record = probe.visible_slide_record(
            host, VISIBLE_SLIDE, instances, PAINT_VIEWPORT, scorer=score_visible_slide,
            now=clock.now, sleep=clock.sleep,
        )

        base = json.loads(self.GOLDEN_BASE_RECORD_PATH.read_text())["record"]

        assert record["perRect"], "the fixture must exercise at least one rect"
        stripped_record = dict(record)
        stripped_record.pop("burstProfile", None)
        stripped_record["perRect"] = [
            {k: v for k, v in rect.items() if k != "oracles"} for rect in stripped_record["perRect"]
        ]
        for rect in record["perRect"]:
            assert set(rect) - set(base["perRect"][0]) <= {"oracles"}
            assert rect["oracles"]["inpage"] is None

        assert set(record) - set(base) == {"burstProfile"}
        assert stripped_record.pop("shotOffsetsMs") == [float(v) for v in probe.BURST_OFFSETS_MS]
        base.pop("shotOffsetsMs")
        assert stripped_record == base

    def test_js_source_never_speculatively_calls_get_context(self) -> None:
        assert "getContext(" not in probe.INPAGE_LIVENESS_JS
        assert "__OBED_GL_ORACLE__" in probe.INPAGE_LIVENESS_JS
        assert "checkVisibility" in probe.INPAGE_LIVENESS_JS
        assert "isContextLost" in probe.INPAGE_LIVENESS_JS

    def test_a_malformed_not_applicable_response_is_an_applicable_inconclusive(self) -> None:
        """Codex r1 Spec 8: only a well-formed, explicit
        `{applicable:false,status:'n/a'}` may vanish as n/a -- anything else
        that merely claims `applicable: False` is untrustworthy and must stay
        an APPLICABLE inconclusive result, never disappear into a
        screenshot-only pass."""
        result = probe.inpage_oracle_result({"applicable": False, "reason": "no status field at all"})
        assert result is not None
        assert result["verdict"] is None
        assert result["status"] == "inconclusive"

    def test_a_non_dict_response_is_an_applicable_inconclusive(self) -> None:
        assert probe.inpage_oracle_result(None) is not None
        assert probe.inpage_oracle_result("oops")["verdict"] is None
        assert probe.inpage_oracle_result(True)["status"] == "inconclusive"


class TestTwoOracleRecord:
    def _base_result(self) -> dict[str, Any]:
        return TestOverallStatusTruthTable()._base_result()

    def test_dead_expected_rect_both_oracles_physically_dead_passes(self) -> None:
        """Codex r1 Spec 2: screenshot `verdict=True` on a dead-expected rect
        means "frozen as expected" (physically DEAD); it must agree with an
        in-page DEAD read, not be read as an opposite-polarity disagreement."""
        entry = {"verdict": True, "expect": probe.DEAD, "reason": None, "liveFrac": 0.01}
        inpage = {"verdict": False, "status": "dead", "reason": None}
        combined = probe.combine_rect_oracles(entry, inpage)
        assert combined["verdict"] is True

    def test_dead_expected_rect_screenshot_dead_inpage_live_is_inconclusive(self) -> None:
        """The physical readings genuinely disagree (frozen pixels, but the GL
        canvas underneath is still drawing) -- that is a real disagreement and
        must be inconclusive, not resolved by either oracle alone."""
        entry = {"verdict": True, "expect": probe.DEAD, "reason": None, "liveFrac": 0.01}
        inpage = {"verdict": True, "status": "live", "reason": None}
        combined = probe.combine_rect_oracles(entry, inpage)
        assert combined["verdict"] is None

    def test_dead_expected_rect_with_an_inconclusive_paused_control_is_inconclusive(self) -> None:
        """Codex r2 Spec 1 regression: screenshot expectation-met `True` on a
        DEAD-expected rect became physical `False`, and the combiner used to
        preserve physical DEAD when the in-page result was merely INCONCLUSIVE
        (a failed paused-decoder control), then translate it back to
        expectation-met `True` -- a silent PASS on a failed control. A failed
        or otherwise applicable-but-inconclusive control must make the slide
        INCONCLUSIVE, never a pass, regardless of `expect`."""
        entry = {"verdict": True, "expect": probe.DEAD, "reason": None, "liveFrac": 0.01}
        inpage = {"verdict": None, "status": "inconclusive", "reason": "paused-decoder control did not read dead"}
        combined = probe.combine_rect_oracles(entry, inpage)
        assert combined["verdict"] is None

    def test_disagreement_makes_the_slide_inconclusive_and_writes_evidence(self, tmp_path: Path) -> None:
        host = FakeHost(scene_ids=["s", "s"], inpage=[_inpage_raw(live=False)])
        clock = FakeClock()
        record = probe.visible_slide_record(
            host, VISIBLE_SLIDE, VISIBLE_INSTANCES, VISIBLE_VIEWPORT, scorer=passing_scorer,
            evidence=probe.visible_evidence_writer(tmp_path, "V"), now=clock.now, sleep=clock.sleep,
        )
        assert record["verdict"] is None
        assert record["status"] == "inconclusive"
        assert record["perRect"][0]["verdict"] is None
        assert record["perRect"][0]["reason"] == "oracle disagreement"
        assert record["perRect"][0]["oracles"]["inpage"]["verdict"] is False
        assert Path(record["evidence"]["inpage"]).exists()

    def test_an_inconclusive_slide_cannot_earn_the_voff_red(self) -> None:
        entry = {
            "slides": [
                {"originalOrdinal": 1, "playerIndex": 0, "verdict": True},
                {"originalOrdinal": 2, "playerIndex": 1, "verdict": None},
            ],
            "stageFit": {"verdict": True},
        }
        result = {"groundTruth": {"boundaryPlayerIndex": 1}}
        reasons = probe.visible_control_reasons(entry, result)
        assert any("is not RED" in reason for reason in reasons)

    def test_an_inconclusive_slide_fails_overall_status(self) -> None:
        result = self._base_result()
        result["visible"]["V"]["slides"][1].update(verdict=None, status="inconclusive")
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any("inconclusive" in reason for reason in reasons)

    def test_a_failed_paused_decoder_control_makes_the_slide_inconclusive(self) -> None:
        raw = _inpage_raw(live=True)
        raw["pausedDecoderSamples"] = raw["samples"]
        result = probe.inpage_oracle_result(raw)
        assert result["verdict"] is None
        assert result["status"] == "inconclusive"
        assert result["reason"] == "paused-decoder control did not read dead"

    def test_an_unusable_occluder_mask_is_inconclusive(self) -> None:
        raw = _inpage_raw(live=True)
        raw["markerDark"] = [0.0] * probe.INPAGE_BAND_COUNT
        raw["markerLight"] = [0.1] * probe.INPAGE_BAND_COUNT
        result = probe.inpage_oracle_result(raw)
        assert result["verdict"] is None
        assert result["status"] == "inconclusive"
        assert result["reason"] == "occluder mask unusable"


class TestHandleIdentityBinding:
    """Codex r2 Spec 3: the JS handle contract publishes `sceneId`/`rect`/
    `instanceId`/`canvasId` and Python must bind the read to the scene,
    authored rect, and movie-instance identity being scored. The JS predicate
    itself cannot run in pytest, so these test the wiring Python controls:
    the exact values sent to the page, and the Python-side handling of each
    identity-mismatch reason the JS could return.
    """

    IDENTITY_MISMATCH_REASONS = [
        "the runtime handle was replaced",
        "handle re-recorded during the sample window",
        "handle scene does not match the scene being scored",
        "handle canvas, gl, or video identity changed",
        "canvas is not a descendant of #stage",
        "canvas disconnected",
        "context lost",
        "canvas is not visible",
        "handle rect does not exactly match the scored instance rect",
        "handle instance does not match the scored instance",
        "handle is present but malformed",
    ]

    @pytest.mark.parametrize("reason", IDENTITY_MISMATCH_REASONS)
    def test_each_identity_mismatch_reason_is_an_applicable_inconclusive(self, reason: str) -> None:
        raw = {"applicable": True, "status": "inconclusive", "reason": reason}
        result = probe.inpage_oracle_result(raw)
        assert result is not None
        assert result["verdict"] is None
        assert result["status"] == "inconclusive"
        assert result["reason"] == reason

    def test_a_new_scene_with_the_same_rect_is_an_applicable_inconclusive(self) -> None:
        """Codex r3 Spec 1: a self-consistent handle re-published for a NEW
        scene, whose rect happens to coincide with the previous scene's, must
        not corroborate the previous scene's screenshots -- the JS's own
        `recheck()` binds `handle.sceneId === expectedScene === liveSceneId()`,
        not merely "the current live scene equals whatever the handle claims"."""
        raw = {"applicable": True, "status": "inconclusive", "reason": "handle scene does not match the scene being scored"}
        result = probe.inpage_oracle_result(raw)
        assert result["verdict"] is None
        assert result["status"] == "inconclusive"

    def test_a_swapped_canvas_object_is_an_applicable_inconclusive(self) -> None:
        """A handle whose `canvas`/`gl`/`video` object identity changed after
        entry (e.g. the runtime re-created the canvas mid-read) must not be
        trusted just because `handle.rect`/`sceneId` still read the same."""
        raw = {"applicable": True, "status": "inconclusive", "reason": "handle canvas, gl, or video identity changed"}
        result = probe.inpage_oracle_result(raw)
        assert result["verdict"] is None
        assert result["status"] == "inconclusive"

    def test_present_but_malformed_handle_is_inconclusive_not_n_a(self) -> None:
        """Codex r3 Spec 1: only an ABSENT global handle may answer n/a; a
        PRESENT but malformed one (missing a required member) must be an
        applicable INCONCLUSIVE, never silently n/a."""
        raw = {"applicable": True, "status": "inconclusive", "reason": "handle is present but malformed"}
        result = probe.inpage_oracle_result(raw)
        assert result is not None
        assert result["status"] == "inconclusive"

    def test_measurement_binds_the_scene_rect_and_instance_before_reading(self) -> None:
        host = FakeHost(scene_ids=["scene-7", "scene-7"], inpage=[{"applicable": False, "status": "n/a", "reason": "no handle"}])
        rect = {"x": 1.0, "y": 2.0, "w": 3.0, "h": 4.0}
        probe.measure_inpage_oracle_with_paused_control(host.transport, rect, "scene-7", "Untitled.mov#1")
        setter = next(js for js in host.transport.evaluations if "__obedInpageRect" in js)
        assert json.dumps(rect) in setter
        assert json.dumps("scene-7") in setter
        assert json.dumps("Untitled.mov#1") in setter

    def test_js_source_rechecks_identity_after_every_await(self) -> None:
        js = probe.INPAGE_LIVENESS_JS
        assert "instanceId" in js
        assert "recheck" in js
        assert js.count("recheck()") >= 4
        assert "__OBED_GL_ORACLE__ !== handle" in js

    def test_js_source_snapshots_scene_and_object_identities_at_entry(self) -> None:
        js = probe.INPAGE_LIVENESS_JS
        assert "var expectedScene = window.__obedInpageSceneId" in js
        assert "var canvas0 = handle.canvas, gl0 = handle.gl, video0 = handle.video" in js
        assert "handle.canvas !== canvas0 || handle.gl !== gl0 || handle.video !== video0" in js
        assert "handle.sceneId !== expectedScene || liveSceneId() !== expectedScene" in js

    def test_js_source_only_an_absent_handle_returns_n_a(self) -> None:
        js = probe.INPAGE_LIVENESS_JS
        absent_check = js.index("if (!handle) { return notApplicable(")
        malformed_check = js.index("return inconclusive('handle is present but malformed')")
        assert absent_check < malformed_check
        assert js.count("notApplicable(") == 2  # the definition plus its one call site


class TestAsyncOracleFailureHandling:
    """Codex r2 Spec 4: a rejected promise or a transport timeout while
    measuring the (optional, inert) in-page oracle must degrade to an
    applicable INCONCLUSIVE for that one rect -- never `status:"error"` for
    the whole pass."""

    def test_a_rejected_promise_is_an_applicable_inconclusive_not_a_raise(self) -> None:
        host = FakeHost(scene_ids=["s", "s"], inpage=[RuntimeError("promise rejected")])
        result = probe.measure_inpage_oracle_with_paused_control(
            host.transport, {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, "s", "Untitled.mov#1"
        )
        assert result["verdict"] is None
        assert result["status"] == "inconclusive"
        assert "promise rejected" in result["reason"]

    def test_a_transport_timeout_is_an_applicable_inconclusive_not_a_raise(self) -> None:
        host = FakeHost(scene_ids=["s", "s"], inpage=[TimeoutError("cdp deadline")])
        result = probe.measure_inpage_oracle_with_paused_control(
            host.transport, {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, "s", "Untitled.mov#1"
        )
        assert result["verdict"] is None
        assert result["status"] == "inconclusive"

    def test_a_failure_never_collapses_the_whole_slide_to_status_error(self) -> None:
        host = FakeHost(scene_ids=["s", "s"], inpage=[RuntimeError("boom")])
        clock = FakeClock()
        record = probe.visible_slide_record(
            host, VISIBLE_SLIDE, VISIBLE_INSTANCES, VISIBLE_VIEWPORT,
            scorer=passing_scorer, now=clock.now, sleep=clock.sleep,
        )
        assert record["status"] != "error"
        assert record["perRect"][0]["oracles"]["inpage"]["status"] == "inconclusive"

    def test_js_source_wraps_paused_sampling_in_try_finally_with_resume(self) -> None:
        """Codex r3 Spec 3: `pause()` itself moved INSIDE the `try` (a promise
        that pauses and then rejects must still hit `finally`)."""
        js = probe.INPAGE_LIVENESS_JS
        try_index = js.index("try {")
        pause_index = js.index("handle.pause()", try_index)
        finally_index = js.index("finally", pause_index)
        resume_index = js.index("handle.resume()", finally_index)
        assert try_index < pause_index < finally_index < resume_index
        # A recheck immediately follows the paused sample, still inside the try.
        paused_sample_index = js.index("handle.sample(", pause_index)
        recheck_after_paused = js.index("recheck()", paused_sample_index)
        assert paused_sample_index < recheck_after_paused < finally_index

    def _run_inpage_js_against_stub(self, *, pause_rejects: bool, sample_rejects: bool) -> dict[str, Any]:
        """Executes the actual `INPAGE_LIVENESS_JS` source under Node (no
        browser) against a stub handle whose `pause()` or paused `sample()`
        rejects, and reports how many times `resume()` was called -- proving
        the `finally` actually runs on a rejection from EITHER phase."""
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not available")
        pause_body = "return Promise.reject(new Error('pause rejected'));" if pause_rejects else "return Promise.resolve();"
        sample_body = (
            "if (sampleCalls === 1 && " + ("true" if sample_rejects else "false") + ") "
            "{ return Promise.reject(new Error('sample rejected')); } "
            "return Promise.resolve([]);"
        )
        script = f"""
        global.window = global;
        var resumeCalls = 0, sampleCalls = 0;
        var handle = {{
          gl: {{ isContextLost: function(){{ return false; }} }},
          canvas: {{ isConnected: true, nodeType: 1, parentElement: null, checkVisibility: function(){{ return true; }} }},
          video: {{}},
          sceneId: 'scene-1', rect: {{x: 0, y: 0, w: 1, h: 1}}, instanceId: 'inst-1',
          canvasId: 'canvas-1', epoch: 1,
          markerBands: function(){{ return Promise.resolve({{dark: [0], light: [1], epoch: 1}}); }},
          pause: function(){{ {pause_body} }},
          resume: function(){{ resumeCalls++; return Promise.resolve(); }},
          sample: function(n){{ sampleCalls++; {sample_body} }},
        }};
        window.__OBED_GL_ORACLE__ = handle;
        window.__obedInpageSceneId = 'scene-1';
        window.__obedInpageRect = handle.rect;
        window.__obedInpageInstanceId = 'inst-1';
        window.__obedLive = {{ snapshot: function(){{ return {{sceneId: 'scene-1'}}; }} }};
        window.getComputedStyle = function(){{ return {{opacity: '1'}}; }};
        global.document = {{
          getElementById: function(id){{
            return id === 'stage' ? {{ contains: function(c){{ return c === handle.canvas; }} }} : null;
          }},
        }};
        (async function(){{
          try {{
            var result = await ({probe.INPAGE_LIVENESS_JS});
            console.log(JSON.stringify({{ok: true, result: result, resumeCalls: resumeCalls}}));
          }} catch (e) {{
            console.log(JSON.stringify({{ok: false, error: String(e), resumeCalls: resumeCalls}}));
          }}
        }})();
        """
        result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout.strip())

    def test_resume_is_awaited_even_when_pause_rejects(self) -> None:
        outcome = self._run_inpage_js_against_stub(pause_rejects=True, sample_rejects=False)
        assert outcome["resumeCalls"] == 1
        assert outcome["ok"] is False
        assert "pause rejected" in outcome["error"]

    def test_resume_is_awaited_even_when_the_paused_sample_rejects(self) -> None:
        outcome = self._run_inpage_js_against_stub(pause_rejects=False, sample_rejects=True)
        assert outcome["resumeCalls"] == 1
        assert outcome["ok"] is False
        assert "sample rejected" in outcome["error"]


class TestPokeIsProbabilistic:
    def test_poke_test_documents_random_values_may_repeat(self) -> None:
        """Codex r2 Spec 8: `BURST_POKE_JS` is byte-for-byte the E0 harness's
        POKE_JS (test_poke_is_the_e0_qualified_painted_element_poke), which
        derives its painted value from `Math.random()` -- consecutive shots
        MAY repeat by chance. This test only asserts the poke reassigns the
        background on every evaluation, not that every value differs."""
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is not available")
        script = f"""
        var backgrounds = [];
        var style = {{}};
        var el = {{
          id: null,
          style: {{ cssText: '', set background(v) {{ style.background = v; backgrounds.push(v); }}, get background() {{ return style.background; }} }},
        }};
        var byId = null;
        var document = {{
          getElementById: function(id) {{ return byId; }},
          createElement: function() {{ return el; }},
          body: {{ appendChild: function(node) {{ byId = node; }} }},
        }};
        for (var i = 0; i < {len(probe.BURST_OFFSETS_MS)}; i++) {{
          eval({json.dumps(probe.BURST_POKE_JS)});
        }}
        console.log(JSON.stringify(backgrounds));
        """
        result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        backgrounds = json.loads(result.stdout.strip())
        assert len(backgrounds) == len(probe.BURST_OFFSETS_MS)
        assert all(bg for bg in backgrounds)


# --------------------------------------------------------------------------
# Pass G -- goTo autoplay repair gate
# --------------------------------------------------------------------------

class TestPassGArgs:
    def test_pass_flag_defaults_to_full_run(self) -> None:
        assert probe.parse_args([]).only_pass is None

    def test_pass_g_selectable(self) -> None:
        assert probe.parse_args(["--pass", "G"]).only_pass == "G"

    def test_pass_rejects_other_values(self) -> None:
        with pytest.raises(SystemExit):
            probe.parse_args(["--pass", "V"])

    def test_attach_flag_defaults_false(self) -> None:
        assert probe.parse_args([]).attach is False

    def test_attach_flag_settable(self) -> None:
        assert probe.parse_args(["--pass", "G", "--attach"]).attach is True


class TestGBurstSpacing:
    def test_g_offsets_are_eight_shots(self) -> None:
        assert len(probe.G_BURST_OFFSETS_MS) == 8

    def test_g_offsets_have_real_margin_over_the_360ms_floor(self) -> None:
        # A live gate run measured realized gaps as low as 358.5ms against the
        # paint-oracle cadence's 360/370ms nominal schedule -- ordinary
        # scheduling jitter, not a defect, but enough to trip the floor. The
        # nominal schedule needs headroom over that jitter; the floor itself
        # (checked on MEASURED timestamps, see `spacing_ok`) stays 360ms.
        gaps = [b - a for a, b in zip(probe.G_BURST_OFFSETS_MS, probe.G_BURST_OFFSETS_MS[1:])]
        assert min(gaps) >= 440

    def test_g_offsets_are_spaced_at_least_360ms_apart(self) -> None:
        assert probe.spacing_ok(probe.G_BURST_OFFSETS_MS) is True

    def test_spacing_ok_detects_a_rapid_burst_of_the_right_count(self) -> None:
        rapid = (0, 100, 200, 300, 400, 500, 600, 700)
        assert probe.spacing_ok(rapid, expected_count=len(rapid)) is False

    def test_wrong_count_is_inconclusive(self) -> None:
        assert probe.spacing_ok(()) is None
        assert probe.spacing_ok((0,)) is None
        assert probe.spacing_ok(probe.G_BURST_OFFSETS_MS[:-1]) is None

    def test_non_finite_value_is_inconclusive(self) -> None:
        values = list(probe.G_BURST_OFFSETS_MS)
        values[-1] = float("nan")
        assert probe.spacing_ok(tuple(values)) is None


class TestCombineVerdicts:
    def test_all_true_is_true(self) -> None:
        assert probe.combine_verdicts(True, True, True) is True

    def test_any_false_is_false(self) -> None:
        assert probe.combine_verdicts(True, False, True) is False

    def test_any_none_is_none_even_with_a_false_present(self) -> None:
        # A missing/unreadable check must not let another check's False stand
        # in for it, and must not let a True elsewhere paper over it either.
        assert probe.combine_verdicts(True, None) is None
        assert probe.combine_verdicts(False, None) is None

    def test_empty_is_true(self) -> None:
        assert probe.combine_verdicts() is True


class TestCaptureIsFresh:
    def test_a_single_frame_burst_where_something_is_live_expected_is_stale(self) -> None:
        assert probe.capture_is_fresh(True, 1) is False

    def test_varied_frames_are_fresh(self) -> None:
        assert probe.capture_is_fresh(True, 8) is True

    def test_exactly_the_minimum_is_fresh(self) -> None:
        assert probe.capture_is_fresh(True, 2) is True

    def test_nothing_live_expected_is_never_flagged(self) -> None:
        assert probe.capture_is_fresh(False, 1) is True
        assert probe.capture_is_fresh(False, None) is True

    def test_unreadable_count_when_live_expected_is_inconclusive(self) -> None:
        assert probe.capture_is_fresh(True, None) is None
        assert probe.capture_is_fresh(True, "n/a") is None
        assert probe.capture_is_fresh(True, True) is None


class TestGotoRectExpectations:
    V_EXPECTATIONS = {
        0: {"untitled.mov": probe.LIVE},
        1: {"untitled.mov": probe.DEAD, "vid.mp4": probe.LIVE},
    }

    def test_armed_returns_the_v_expectations_unchanged(self) -> None:
        assert probe.goto_rect_expectations(self.V_EXPECTATIONS, armed=True) == self.V_EXPECTATIONS

    def test_off_marks_every_asset_dead(self) -> None:
        off = probe.goto_rect_expectations(self.V_EXPECTATIONS, armed=False)
        assert off == {
            0: {"untitled.mov": probe.DEAD},
            1: {"untitled.mov": probe.DEAD, "vid.mp4": probe.DEAD},
        }

    def test_off_does_not_mutate_the_input(self) -> None:
        before = {k: dict(v) for k, v in self.V_EXPECTATIONS.items()}
        probe.goto_rect_expectations(self.V_EXPECTATIONS, armed=False)
        assert self.V_EXPECTATIONS == before


class TestScoreNoConsumption:
    def test_missing_execute_record_is_inconclusive(self) -> None:
        verdict = probe.score_no_consumption("2", "2", None)
        assert verdict["verdict"] is None
        assert verdict["sceneOk"] is True

    def test_missing_fields_on_the_record_are_inconclusive(self) -> None:
        # Another stream is landing autoPlayRunLength/autoPlayFired on
        # live_host.py concurrently -- a record that predates them must not
        # be read as a false pass.
        assert probe.score_no_consumption("2", "2", {"outcome": "ok"})["verdict"] is None

    def test_wrong_scene_fails(self) -> None:
        verdict = probe.score_no_consumption("6", "2", {"autoPlayRunLength": 0, "autoPlayFired": False})
        assert verdict["verdict"] is False
        assert verdict["sceneOk"] is False

    def test_nonzero_run_length_fails(self) -> None:
        verdict = probe.score_no_consumption("2", "2", {"autoPlayRunLength": 1, "autoPlayFired": True})
        assert verdict["verdict"] is False

    def test_fired_true_fails_even_with_zero_run_length(self) -> None:
        verdict = probe.score_no_consumption("2", "2", {"autoPlayRunLength": 0, "autoPlayFired": True})
        assert verdict["verdict"] is False

    def test_clean_no_consumption_passes(self) -> None:
        verdict = probe.score_no_consumption(
            "2", "2", {"autoPlayRunLength": 0, "autoPlayFired": False, "autoPlayRunKinds": []}
        )
        assert verdict["verdict"] is True


class TestExecuteLog:
    def test_read_execute_log_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert probe.read_execute_log(tmp_path / "nope.jsonl") == []

    def test_read_execute_log_returns_none_for_no_path(self) -> None:
        assert probe.read_execute_log(None) == []

    def test_read_execute_log_skips_malformed_or_non_object_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "log.jsonl"
        p.write_text(
            '{"kind": "start"}\n'
            "not json\n"
            '["a list is not a record"]\n'
            '{"kind": "execute", "operation": "goTo", "slide": 2}\n'
        )
        assert probe.read_execute_log(p) == [
            {"kind": "start"},
            {"kind": "execute", "operation": "goTo", "slide": 2},
        ]

    def test_find_execute_record_returns_the_last_match(self) -> None:
        records = [
            {"kind": "execute", "operation": "goTo", "slide": 2, "autoPlayFired": True},
            {"kind": "execute", "operation": "goTo", "slide": 2, "autoPlayFired": False},
        ]
        assert probe.find_execute_record(records, operation="goTo", slide=2)["autoPlayFired"] is False

    def test_find_execute_record_ignores_other_operations_and_slides(self) -> None:
        records = [
            {"kind": "execute", "operation": "advance", "slide": None},
            {"kind": "execute", "operation": "goTo", "slide": 3},
        ]
        assert probe.find_execute_record(records, operation="goTo", slide=2) is None

    def test_wait_for_execute_record_polls_until_the_record_lands(self, tmp_path: Path) -> None:
        log_path = tmp_path / "log.jsonl"
        clock = FakeClock()
        calls = {"n": 0}

        def sleep(duration: float) -> None:
            calls["n"] += 1
            clock.sleep(duration)
            if calls["n"] == 2:
                log_path.write_text(
                    '{"kind": "execute", "operation": "goTo", "slide": 2, "autoPlayRunLength": 0}\n'
                )

        record = probe.wait_for_execute_record(
            log_path, operation="goTo", slide=2, timeout_s=1.0, now=clock.now, sleep=sleep
        )
        assert record is not None and record["autoPlayRunLength"] == 0

    def test_wait_for_execute_record_gives_up_after_the_timeout(self, tmp_path: Path) -> None:
        clock = FakeClock()
        record = probe.wait_for_execute_record(
            tmp_path / "nope.jsonl", operation="goTo", slide=2, timeout_s=0.2, now=clock.now, sleep=clock.sleep
        )
        assert record is None


class TestCropScreenRect:
    def test_crop_clips_to_frame_bounds(self) -> None:
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        crop = probe._crop_screen_rect(frame, {"x": 5, "y": 5, "w": 20, "h": 20})
        assert crop.shape == (5, 5, 3)

    def test_crop_outside_frame_is_empty(self) -> None:
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        crop = probe._crop_screen_rect(frame, {"x": 50, "y": 50, "w": 5, "h": 5})
        assert crop.size == 0


class TestScoreRegionChanged:
    @staticmethod
    def _frame(width: int, height: int, fill: int) -> np.ndarray:
        return np.full((height, width, 3), fill, dtype=np.uint8)

    def test_a_changed_region_passes(self) -> None:
        before, after = self._frame(100, 100, 10), self._frame(100, 100, 10)
        after[20:60, 20:60] = 200
        result = probe.score_region_changed(before, after, {"x": 20, "y": 20, "w": 40, "h": 40})
        assert result["verdict"] is True
        assert result["mae"] >= probe.CHARACTER_REGION_MAE_MIN

    def test_an_unchanged_region_fails(self) -> None:
        before, after = self._frame(100, 100, 10), self._frame(100, 100, 10)
        result = probe.score_region_changed(before, after, {"x": 20, "y": 20, "w": 40, "h": 40})
        assert result["verdict"] is False
        assert result["mae"] == 0.0

    def test_an_empty_crop_is_a_hard_fail(self) -> None:
        before, after = self._frame(100, 100, 10), self._frame(100, 100, 10)
        result = probe.score_region_changed(before, after, {"x": 500, "y": 500, "w": 10, "h": 10})
        assert result["verdict"] is False
        assert result["mae"] is None

    def test_mismatched_crop_shapes_are_a_hard_fail(self) -> None:
        before, after = self._frame(100, 100, 10), self._frame(50, 50, 10)
        result = probe.score_region_changed(before, after, {"x": 30, "y": 30, "w": 40, "h": 40})
        assert result["verdict"] is False
        assert result["mae"] is None


def _character_effect(object_id: str, px: float, py: float, width: float, height: float, *, anchor: bool = True) -> dict[str, Any]:
    state: dict[str, Any] = {"position": {"pointX": px, "pointY": py}, "width": width, "height": height}
    if anchor:
        state["anchorPoint"] = {"pointX": 0.5, "pointY": 0.5}
    return {
        "beginTime": 0, "type": "buildIn", "name": "apple:dissolve character", "objectID": object_id,
        "baseLayer": {"initialState": state},
    }


class TestWalkCharacterRects:
    def test_finds_a_character_buildin_rect(self) -> None:
        rects = probe._walk_character_rects([_character_effect("A", 100, 200, 40, 60)])
        assert rects == [{"x": 80.0, "y": 170.0, "w": 40.0, "h": 60.0}]

    def test_ignores_non_character_effects(self) -> None:
        node = [{
            "type": "buildIn", "name": "apple:dissolve", "objectID": "X",
            "baseLayer": {"initialState": {"position": {"pointX": 0, "pointY": 0}, "width": 10, "height": 10}},
        }]
        assert probe._walk_character_rects(node) == []

    def test_defaults_anchor_to_center_when_unspecified(self) -> None:
        node = [_character_effect("A", 50, 50, 10, 10, anchor=False)]
        assert probe._walk_character_rects(node) == [{"x": 45.0, "y": 45.0, "w": 10.0, "h": 10.0}]

    def test_recurses_into_nested_effects(self) -> None:
        node = [{"type": "buildIn", "effects": [_character_effect("A", 100, 200, 40, 60)]}]
        assert len(probe._walk_character_rects(node)) == 1

    def test_a_node_missing_geometry_is_skipped(self) -> None:
        node = [{"name": "apple:dissolve character", "baseLayer": {"initialState": {}}}]
        assert probe._walk_character_rects(node) == []


class TestUnionRect:
    def test_empty_is_none(self) -> None:
        assert probe._union_rect([]) is None

    def test_unions_the_bounding_box(self) -> None:
        rects = [{"x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0}, {"x": 20.0, "y": -5.0, "w": 10.0, "h": 10.0}]
        assert probe._union_rect(rects) == {"x": 0.0, "y": -5.0, "w": 30.0, "h": 15.0}


class TestCharacterRegionRect:
    def test_unions_every_character_build_on_the_slide(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(probe, "safe_export_file", lambda root, rel: root / rel)
        export_root = tmp_path / "export"
        uuid = "SLIDE-UUID"
        slide_dir = export_root / "assets" / uuid
        slide_dir.mkdir(parents=True)
        events = [
            {"automaticPlay": False, "effects": [_character_effect("A", 100, 100, 40, 40)]},
            {"automaticPlay": False, "effects": [_character_effect("B", 300, 300, 40, 40)]},
            {"automaticPlay": False, "effects": []},
        ]
        (slide_dir / f"{uuid}.json").write_text(json.dumps({"events": events, "assets": {}}))
        rect = probe.character_region_rect(export_root, {"exportedUuid": uuid})
        assert rect == {"x": 80.0, "y": 80.0, "w": 240.0, "h": 240.0}

    def test_missing_slide_json_is_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(probe, "safe_export_file", lambda root, rel: root / rel)
        assert probe.character_region_rect(tmp_path, {"exportedUuid": "nope"}) is None

    def test_malformed_slide_json_is_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(probe, "safe_export_file", lambda root, rel: root / rel)
        export_root = tmp_path / "export"
        uuid = "SLIDE-UUID"
        slide_dir = export_root / "assets" / uuid
        slide_dir.mkdir(parents=True)
        (slide_dir / f"{uuid}.json").write_text("{not valid json")
        assert probe.character_region_rect(export_root, {"exportedUuid": uuid}) is None

    def test_events_not_a_list_is_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(probe, "safe_export_file", lambda root, rel: root / rel)
        export_root = tmp_path / "export"
        uuid = "SLIDE-UUID"
        slide_dir = export_root / "assets" / uuid
        slide_dir.mkdir(parents=True)
        (slide_dir / f"{uuid}.json").write_text(json.dumps({"events": None, "assets": {}}))
        assert probe.character_region_rect(export_root, {"exportedUuid": uuid}) is None

    def test_missing_uuid_is_none(self) -> None:
        assert probe.character_region_rect(Path("/nonexistent"), {}) is None


class TestResolveNoConsumption:
    """Codex round 2: missing/unreadable character geometry must make the
    no-consumption check inconclusive, never silently True -- and must never
    touch the player to get there."""

    def test_missing_character_rect_is_inconclusive_without_touching_the_player(self) -> None:
        result = probe.resolve_no_consumption(None, "2", None, {"s": 1}, execute_record=None)
        assert result["verdict"] is None
        assert "characters region rect is unavailable" in result["reason"]

    def test_invalid_stage_map_is_inconclusive_without_touching_the_player(self) -> None:
        result = probe.resolve_no_consumption(None, "2", {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, None, execute_record=None)
        assert result["verdict"] is None
        assert "stage map" in result["reason"]


class TestGotoTelemetry:
    def test_extracts_the_four_autoplay_fields(self) -> None:
        record = {
            "autoPlayRunLength": 1, "autoPlayRunKinds": ["apple:movie-start"], "autoPlayFired": True,
            "autoPlayDeferredReason": None, "operation": "goTo", "slide": 3,
        }
        assert probe.goto_telemetry(record) == {
            "autoPlayRunLength": 1, "autoPlayRunKinds": ["apple:movie-start"],
            "autoPlayFired": True, "autoPlayDeferredReason": None,
        }

    def test_missing_record_is_all_none(self) -> None:
        assert probe.goto_telemetry(None) == {field: None for field in probe.GOTO_TELEMETRY_FIELDS}


class TestTelemetryPresent:
    def test_all_fields_present_is_true_even_with_null_values(self) -> None:
        record = {field: None for field in probe.GOTO_TELEMETRY_FIELDS}
        assert probe.telemetry_present(record) is True

    def test_missing_record_is_inconclusive(self) -> None:
        assert probe.telemetry_present(None) is None

    def test_partial_record_is_inconclusive(self) -> None:
        assert probe.telemetry_present({"autoPlayRunLength": 1}) is None


class _ShotTransport:
    def __init__(self, shots: list[str]) -> None:
        self.shots = shots
        self.calls = 0

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        assert method == "Page.captureScreenshot"
        data = self.shots[min(self.calls, len(self.shots) - 1)]
        self.calls += 1
        return {"data": data}


def _png_b64_from_array(image: np.ndarray) -> str:
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    return base64.b64encode(buffer.tobytes()).decode("ascii")


class TestScoreStaticControl:
    """Codex round 2: a black or wrong-slide capture must fail even though every movie rect is
    correctly DEAD-expected there -- scored on the area OUTSIDE every expected movie rect."""

    def test_all_black_frame_fails_the_non_black_check(self) -> None:
        shot = png_b64(40, 40, fill=0)
        transport = _ShotTransport([shot, shot])
        result = probe.score_static_control(transport, [], gap_s=0.0)
        assert result["verdict"] is False
        assert "no rendered content" in result["reason"]

    def test_bright_content_outside_the_excluded_rect_passes(self) -> None:
        image = np.zeros((40, 40, 3), dtype=np.uint8)
        image[0:10, 0:10] = 200
        shot = _png_b64_from_array(image)
        transport = _ShotTransport([shot, shot])
        result = probe.score_static_control(transport, [{"x": 10, "y": 10, "w": 30, "h": 30}], gap_s=0.0)
        assert result["verdict"] is True

    def test_bright_content_only_inside_the_excluded_rect_still_fails(self) -> None:
        image = np.zeros((40, 40, 3), dtype=np.uint8)
        image[10:40, 10:40] = 200
        shot = _png_b64_from_array(image)
        transport = _ShotTransport([shot, shot])
        result = probe.score_static_control(transport, [{"x": 10, "y": 10, "w": 30, "h": 30}], gap_s=0.0)
        assert result["verdict"] is False
        assert "no rendered content" in result["reason"]

    def test_unstable_content_outside_the_rect_fails(self) -> None:
        first = np.zeros((40, 40, 3), dtype=np.uint8)
        first[0:10, 0:10] = 200
        second = np.zeros((40, 40, 3), dtype=np.uint8)
        second[0:10, 0:10] = 50
        transport = _ShotTransport([_png_b64_from_array(first), _png_b64_from_array(second)])
        result = probe.score_static_control(transport, [], gap_s=0.0)
        assert result["verdict"] is False
        assert "changed unexpectedly" in result["reason"]

    def test_excluding_the_whole_frame_is_inconclusive(self) -> None:
        shot = png_b64(40, 40, fill=200)
        transport = _ShotTransport([shot, shot])
        result = probe.score_static_control(transport, [{"x": 0, "y": 0, "w": 40, "h": 40}], gap_s=0.0)
        assert result["verdict"] is None

    def test_mismatched_shots_fail(self) -> None:
        transport = _ShotTransport([png_b64(40, 40, fill=200), png_b64(20, 20, fill=200)])
        result = probe.score_static_control(transport, [], gap_s=0.0)
        assert result["verdict"] is False
        assert "empty or mismatched" in result["reason"]


def _g_destination(from_ordinal: int, to_ordinal: int, verdict: bool | None, reasons: Sequence[str] = ()) -> dict[str, Any]:
    return {"fromOrdinal": from_ordinal, "toOrdinal": to_ordinal, "verdict": verdict, "reasons": list(reasons)}


class TestDestinationsOf:
    def test_reads_a_list_of_dicts(self) -> None:
        entry = {"destinations": [{"a": 1}, "not a dict", {"b": 2}]}
        assert probe.destinations_of(entry) == [{"a": 1}, {"b": 2}]

    def test_missing_or_wrong_shape_is_empty(self) -> None:
        assert probe.destinations_of(None) == []
        assert probe.destinations_of({}) == []
        assert probe.destinations_of({"destinations": "nope"}) == []


def _g_arm(destinations: list[dict[str, Any]], *, output_visible: bool = True, stop_error: str | None = None) -> dict[str, Any]:
    arm: dict[str, Any] = {"destinations": destinations, "outputVisible": output_visible}
    if stop_error is not None:
        arm["stopError"] = stop_error
    return arm


def _all_true_g_arm() -> dict[str, Any]:
    return _g_arm([_g_destination(f, t, True) for f, t in probe.GOTO_MATRIX])


class TestOverallStatusG:
    def test_all_true_both_arms_passes(self) -> None:
        result = {"armed": _all_true_g_arm(), "nullControl": _all_true_g_arm()}
        assert probe.overall_status_g(result) == ("pass", [])

    def test_a_false_armed_destination_fails(self) -> None:
        destinations = [_g_destination(f, t, True) for f, t in probe.GOTO_MATRIX]
        destinations[0] = _g_destination(1, 2, False, ["movie rect stayed dead"])
        result = {"armed": _g_arm(destinations), "nullControl": _all_true_g_arm()}
        status, reasons = probe.overall_status_g(result)
        assert status == "fail"
        assert any("armed goTo 1->2" in reason for reason in reasons)

    def test_a_green_null_control_fails_the_pass(self) -> None:
        """A null-control destination reading LIVE (verdict False, missing its
        DEAD expectation) is the "green null control" the plan requires to
        fail the whole pass -- never a silent pass alongside a clean armed
        arm."""
        destinations = [_g_destination(f, t, True) for f, t in probe.GOTO_MATRIX]
        destinations[0] = _g_destination(1, 2, False, ["expected dead, read live"])
        result = {"armed": _all_true_g_arm(), "nullControl": _g_arm(destinations)}
        status, reasons = probe.overall_status_g(result)
        assert status == "fail"
        assert any("null control goTo 1->2" in reason for reason in reasons)

    def test_any_inconclusive_destination_makes_the_pass_inconclusive(self) -> None:
        destinations = [_g_destination(f, t, True) for f, t in probe.GOTO_MATRIX]
        destinations[0] = _g_destination(1, 2, None)
        result = {"armed": _g_arm(destinations), "nullControl": _all_true_g_arm()}
        status, _ = probe.overall_status_g(result)
        assert status == "inconclusive"

    def test_missing_destinations_is_an_error(self) -> None:
        status, _ = probe.overall_status_g({"armed": _g_arm([]), "nullControl": _all_true_g_arm()})
        assert status == "error"

    def test_output_not_visible_fails_even_with_all_true_destinations(self) -> None:
        result = {"armed": _g_arm([_g_destination(f, t, True) for f, t in probe.GOTO_MATRIX], output_visible=False), "nullControl": _all_true_g_arm()}
        status, reasons = probe.overall_status_g(result)
        assert status == "fail"
        assert any("armed output was not visible" in reason for reason in reasons)

    def test_a_stop_error_fails(self) -> None:
        result = {
            "armed": _g_arm([_g_destination(f, t, True) for f, t in probe.GOTO_MATRIX], stop_error="boom"),
            "nullControl": _all_true_g_arm(),
        }
        status, reasons = probe.overall_status_g(result)
        assert status == "fail"
        assert any("armed player.stop() failed: boom" in reason for reason in reasons)


# --------------------------------------------------------------------------
# GL replay G5 (`git show ed7ff63c:.agents/plans/keynote_live_gl_replay_g5g6.plan.md` §3): the
# probe's `--gl-replay auto` arms, the armed 1->2 verdict, the Vgl pass, the
# hand-back capture, occluded cells and the forced-fail splice. Flag off must
# change nothing: every test below that touches an off path asserts it.
# --------------------------------------------------------------------------

GL_SLOT_RECTS = [[0.0, 0.0, 1920.0, 1080.0], [105.0, 790.0, 960.0, 276.0], [788.0, 672.0, 353.0, 313.0]]
GL_BOUNDARY = {
    "atScene": 2, "action": "glReplay", "movieKey": "movie1", "fallback": "retire",
    "slotSizes": [[1920, 1080], [960, 276], [178, 157]], "slotRects": GL_SLOT_RECTS,
    "opacityOverrides": [{"slot": 2, "opacity": 0.3, "texW": 178, "texH": 157}],
    "instanceId": f"{BIG_ASSET}#1", "instanceRect": dict(BIG_INSTANCE), "movieSlot": 1,
}
GL_RUNTIME = {"movies": RUNTIME_MOVIES, "boundaries": [GL_BOUNDARY, RESTART_BOUNDARY, BRIDGE_BOUNDARY]}
GL_REPLAY_VERSION = probe.GL_REPLAY_VERSION
GL_CONTINUITY = {"mode": "qualified", "glReplay": {"mode": "injected", "version": GL_REPLAY_VERSION, "sha256": probe.gl_replay_js_sha256()}}
ARMED = probe.armed_fact(synthetic_plan(), GL_RUNTIME, BOUNDARY_KEYS)
GL_STAGE = {"s": 1.0, "sy": 1.0, "ox": 0.0, "oy": 0.0, "offsetWidth": 1920.0, "offsetHeight": 1080.0}


def _ev(kind: str, **detail: Any) -> dict[str, Any]:
    return {"kind": kind, "detail": detail, "t": 1.0}


def _pool_entry(el_id: int, current_time: float, **extra: Any) -> dict[str, Any]:
    return {
        "key": "untitled.mov", "movieKey": "movie1", "elId": el_id, "currentTime": current_time,
        "paused": False, "readyState": 4, "inDocument": False, **extra,
    }


def _armed_read(t: float, iteration: int, carried_time: float) -> dict[str, Any]:
    """One settled-slide-2 read in the r3 GREEN shape: 2 pooled (1 carried, 2
    sibling), none in the document, LIVE, rVFC loop, no stand-down."""
    return {
        "stageMap": dict(GL_STAGE), "painting": [], "poolSnapshot": [],
        "glReplay": {
            "t": t, "hash": "#2", "ready": True,
            "api": {
                "version": 1, "state": "LIVE", "standDowns": [], "events": [],
                "stats": {"epoch": 1, "iter": iteration, "uploads": iteration, "glErrors": 0, "loopMode": "rvfc"},
            },
            "coreEvents": [
                _ev("glreplay-zone", key="movie1", **{"from": "pending"}, to="armed", reason="moduleReady", sceneHash=""),
                _ev("glreplay-arm", canvasId="1-canvas", atScene=2, sceneHash="#1"),
                _ev("glreplay-carried", elId=1, delta=0.012, candidates=[{"elId": 1}, {"elId": 2}], sceneHash="#1"),
                _ev("glreplay-live", canvasId="1-canvas", epoch=1, frameLen=88, sceneHash="#1"),
            ],
            "pool": [_pool_entry(1, carried_time), _pool_entry(2, 3.0)],
            "facades": [],
        },
    }


def _armed_reads() -> list[dict[str, Any]]:
    return [_armed_read(1000.0, 10, 5.0), _armed_read(1600.0, 46, 5.6)]


def _gl(read: dict[str, Any]) -> dict[str, Any]:
    return read["glReplay"]


def _events_without(read: dict[str, Any], kind: str) -> None:
    _gl(read)["coreEvents"] = [e for e in _gl(read)["coreEvents"] if e["kind"] != kind]


def _set_detail(read: dict[str, Any], kind: str, **detail: Any) -> None:
    for event in _gl(read)["coreEvents"]:
        if event["kind"] == kind:
            event["detail"].update(detail)


ARMED_CLAUSE_MUTATIONS = {
    # clause 1 -- mode/version/sha
    "mode not injected": ("mode", lambda reads, c: c["glReplay"].update(mode="notApplicable")),
    "version drift": ("mode", lambda reads, c: c["glReplay"].update(version=GL_REPLAY_VERSION + 1)),
    "sha drift": ("mode", lambda reads, c: c["glReplay"].update(sha256="0" * 64)),
    # clause 2 -- both reads LIVE, same epoch, strictly progressing
    "first read not LIVE": ("live", lambda reads, c: _gl(reads[0])["api"].update(state="ARM-POST")),
    "a stand-down": ("live", lambda reads, c: _gl(reads[1])["api"].update(standDowns=["glError"])),
    "gl error": ("live", lambda reads, c: _gl(reads[0])["api"]["stats"].update(glErrors=1)),
    "epoch changed": ("live", lambda reads, c: _gl(reads[1])["api"]["stats"].update(epoch=2)),
    "iter stalled": ("live", lambda reads, c: _gl(reads[1])["api"]["stats"].update(iter=10)),
    "uploads stalled": ("live", lambda reads, c: _gl(reads[1])["api"]["stats"].update(uploads=10)),
    "reads too close": ("live", lambda reads, c: (_gl(reads[1]).update(t=1400.0), _set_pool_time(reads[1], 5.4))),
    "hash before destination": ("live", lambda reads, c: _gl(reads[0]).update(hash="#1")),
    # clause 3 -- one arm, one live, zone, one carried
    "two arms": ("events", lambda reads, c: _gl(reads[1])["coreEvents"].append(_ev("glreplay-arm", sceneHash="#1"))),
    "arm at the wrong scene": ("events", lambda reads, c: _set_detail(reads[1], "glreplay-arm", sceneHash="#2")),
    "no live": ("events", lambda reads, c: _events_without(reads[1], "glreplay-live")),
    "live before the transition": ("events", lambda reads, c: _set_detail(reads[1], "glreplay-live", sceneHash="#0")),
    "a stand-down event": ("events", lambda reads, c: _gl(reads[1])["coreEvents"].append(_ev("glreplay-standdown", reason="glError"))),
    "an early hand-off": ("events", lambda reads, c: _gl(reads[1])["coreEvents"].append(_ev("glreplay-handoff", reason="canvasRemoved"))),
    "zone retired": ("events", lambda reads, c: _gl(reads[1])["coreEvents"].append(
        _ev("glreplay-zone", **{"from": "armed"}, to="retired", reason="moduleRetired"))),
    "zone reason drift": ("events", lambda reads, c: _set_detail(reads[1], "glreplay-zone", reason="entryInvalid")),
    "carry delta too large": ("events", lambda reads, c: _set_detail(reads[1], "glreplay-carried", delta=0.05)),
    # clause 4 -- no painting <video> over the armed rect
    "painting over the rect": ("noPainting", lambda reads, c: reads[0].update(painting=[painting_video(BIG_INSTANCE, el_id=1)])),
    "unreadable painting": ("noPainting", lambda reads, c: reads[1].update(painting={"error": "no checkVisibility"})),
    "bad stage map": ("noPainting", lambda reads, c: reads[1].update(stageMap=None)),
    # clause 5 -- pool = {carried} U siblings, out of the document, carried decoding in real time
    "carried not pooled": ("pool", lambda reads, c: _gl(reads[1]).update(pool=[_pool_entry(2, 3.0)])),
    "sibling in the document": ("pool", lambda reads, c: _gl(reads[0])["pool"][1].update(inDocument=True)),
    "a preserved DOM copy": ("pool", lambda reads, c: _gl(reads[1])["pool"].append(_pool_entry(5, 1.0, fromDom=True))),
    "carried paused": ("pool", lambda reads, c: _gl(reads[1])["pool"][0].update(paused=True)),
    "carried not decoding": ("pool", lambda reads, c: _gl(reads[0])["pool"][0].update(readyState=1)),
    "carried clock frozen": ("pool", lambda reads, c: _set_pool_time(reads[1], 5.0)),
    "carried clock double speed": ("pool", lambda reads, c: _set_pool_time(reads[1], 6.2)),
    "carried clock half speed": ("pool", lambda reads, c: _set_pool_time(reads[1], 5.3)),
    "unreadable pool": ("pool", lambda reads, c: _gl(reads[0]).update(pool={"error": "boom"})),
}


def _set_pool_time(read: dict[str, Any], value: float) -> None:
    _gl(read)["pool"][0]["currentTime"] = value


class TestArmedFact:
    def test_the_glreplay_boundary_resolves_to_armed1to2_with_its_geometry(self) -> None:
        armed = probe.armed_fact(synthetic_plan(), GL_RUNTIME, BOUNDARY_KEYS)
        assert armed["verdictKey"] == "armed1to2" == probe.ARMED_VERDICT_KEY["continue1to2"]
        assert armed["boundaryKey"] == "continue1to2"
        assert armed["movieKey"] == "movie1" and armed["atScene"] == 2
        assert armed["playerIndex"] == 1 and armed["originalOrdinal"] == 2
        assert armed["assetKeys"] == ["untitled.mov"] and armed["rects"] == [BIG_INSTANCE]
        assert armed["instanceId"] == f"{BIG_ASSET}#1" and armed["instanceRect"] == BIG_INSTANCE
        assert armed["movieSlot"] == 1 and armed["overrideSlots"] == [2]
        assert armed["slotRects"][1] == {"x": 105.0, "y": 790.0, "w": 960.0, "h": 276.0}

    @pytest.mark.parametrize("boundaries", [
        [RESTART_BOUNDARY, BRIDGE_BOUNDARY],
        [GL_BOUNDARY, dict(GL_BOUNDARY, atScene=6), BRIDGE_BOUNDARY],
    ])
    def test_anything_but_exactly_one_glreplay_boundary_fails_closed(self, boundaries: list[Any]) -> None:
        with pytest.raises(SystemExit):
            probe.armed_fact(synthetic_plan(), {"movies": RUNTIME_MOVIES, "boundaries": boundaries}, BOUNDARY_KEYS)

    @pytest.mark.parametrize("change", [
        {"atScene": 4}, {"atScene": 6}, {"movieKey": "movie9"}, {"instanceId": f"{BIG_ASSET}#2"},
        {"instanceRect": dict(BIG_INSTANCE, x=110.0)}, {"movieSlot": 3}, {"slotRects": None},
        {"opacityOverrides": [{"slot": 7}]},
    ])
    def test_an_unscorable_entry_fails_closed(self, change: dict[str, Any]) -> None:
        runtime = {"movies": RUNTIME_MOVIES, "boundaries": [dict(GL_BOUNDARY, **change)]}
        with pytest.raises(SystemExit):
            probe.armed_fact(synthetic_plan(), runtime, BOUNDARY_KEYS)


def _gl_plan(gl: bool = False) -> Any:
    """The refused 1->2 pin (G2-armed when `gl`) and the 3->4 bridge, each instance authored on
    its slides, so the plan agrees with RETIRED_RUNTIME (off) / GL_RUNTIME (on)."""
    rect = probe.live_continuity_module.Rect
    movie = probe.live_continuity_module.MovieContinuity
    boundary = probe.live_continuity_module.SlideBoundary
    pin = movie(
        BIG_ASSET, "pin", rect(**BIG_INSTANCE), rect(**BIG_INSTANCE), refusal="overlap", gl_replay={"x": 1} if gl else None,
    )
    src, dst = {"x": 198.0, "y": 797.0, "w": 952.0, "h": 268.0}, {"x": 327.0, "y": 709.0, "w": 1266.0, "h": 356.0}
    bridge = movie(BIG_ASSET, "bridge", rect(**src), rect(**dst))
    return probe.ContinuityPlan(
        canvas={"width": 1920, "height": 1080}, scene_index_by_player=dict(SCENE_INDEX_BY_PLAYER),
        slide_rects={}, boundaries=(boundary(0, 1, (pin,)), boundary(2, 3, (bridge,))),
        slide_instances={0: {BIG_ASSET: [BIG_INSTANCE]}, 1: {BIG_ASSET: [BIG_INSTANCE]}, 2: {BIG_ASSET: [src]}, 3: {BIG_ASSET: [dst]}},
    )


class TestFactsPerArm:
    def test_the_off_fact_set_has_no_armed_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(probe, "runtime_of", lambda plan: RETIRED_RUNTIME)
        facts = probe.ground_truth_facts(_gl_plan())
        assert "armed" not in facts and "armedBoundaries" not in facts
        assert facts["retire"]["verdictKey"] == "refused1to2"

    def test_the_on_fact_set_adds_armed_and_no_retire(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(probe, "runtime_of", lambda plan: GL_RUNTIME)
        facts = probe.ground_truth_facts(_gl_plan(gl=True), armed=True)
        assert facts["armed"] == probe.armed_fact(_gl_plan(gl=True), GL_RUNTIME, BOUNDARY_KEYS)
        assert facts["armedBoundaries"] == ["continue1to2"]
        assert facts["retire"] is None and facts["refusedBoundaries"] == []

    def test_asking_for_armed_facts_from_an_off_plan_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(probe, "runtime_of", lambda plan: RETIRED_RUNTIME)
        with pytest.raises(SystemExit):
            probe.ground_truth_facts(_gl_plan(), armed=True)

    @pytest.mark.parametrize("continuity,expected", [
        ({"mode": "qualified", "glReplay": {"mode": "injected"}}, "on"),
        ({"mode": "qualified", "glReplay": {"mode": "off"}}, "off"),
        ({"mode": "qualified", "glReplay": {"mode": "unavailable"}}, "off"),
        ({"mode": "qualified", "glReplay": {"mode": "notApplicable"}}, "off"),
        ({"mode": "qualified"}, "off"),
        (None, "off"),
    ])
    def test_the_reported_mode_selects_the_fact_set(self, continuity: Any, expected: str) -> None:
        on, off = {"set": "on"}, {"set": "off"}
        assert probe.facts_for(continuity, off, on)["set"] == expected

    def test_without_an_on_set_injected_still_scores_off(self) -> None:
        off = {"set": "off"}
        assert probe.facts_for({"glReplay": {"mode": "injected"}}, off, None) is off

    def test_the_off_observer_is_todays_refusal_observer(self) -> None:
        retire = probe.retire_fact(synthetic_plan(), RETIRED_RUNTIME, BOUNDARY_KEYS)
        out: dict[str, Any] = {}
        host = ArmedHost([])
        probe.boundary_observer(host, {"retire": retire}, out)(2)
        assert list(out) == ["refused1to2"]
        assert probe.GL_REPLAY_READ_JS not in host.transport.evaluations
        assert probe.boundary_observer(host, {"retire": None}, out) is None

    def test_the_armed_observer_reads_twice_on_the_armed_slide_only(self) -> None:
        clock = FakeClock()
        host = ArmedHost([_gl(r) for r in _armed_reads()])
        out: dict[str, Any] = {}
        observe = probe.boundary_observer(host, {"retire": None, "armed": ARMED}, out, sleep=clock.sleep, now=clock.now)
        observe(1)
        assert out == {}
        observe(2)
        assert len(out["armed1to2"]) == 2
        assert clock.sleeps[-1] == probe.ARMED_READ_GAP_S
        joined = "\n".join(host.transport.evaluations)
        assert probe.INPAGE_LIVENESS_JS not in host.transport.evaluations
        assert "markerBands" not in joined and "__OBED_GL_ORACLE__" not in joined

    def test_the_gl_read_never_touches_the_oracle_handle_or_its_context(self) -> None:
        import re

        js = probe.GL_REPLAY_READ_JS
        assert "__OBED_GL_ORACLE__" not in js
        assert "markerBands" not in js and "pause" not in js and "sample(" not in js
        assert not re.search(r"\.gl\b", js)


class ArmedTransport:
    def __init__(self, host: "ArmedHost") -> None:
        self.host = host
        self.evaluations: list[str] = []
        self.captures = 0

    def evaluate(self, js: str) -> Any:
        self.evaluations.append(js)
        if js == probe.HASH_JS:
            hashes = self.host.hashes
            return hashes.pop(0) if len(hashes) > 1 else (hashes[0] if hashes else "#2")
        if js == probe.GL_REPLAY_READ_JS:
            reads = self.host.reads
            return reads.pop(0) if len(reads) > 1 else (reads[0] if reads else None)
        if js == probe.STAGE_MAP_JS:
            return self.host.stage_map
        if js == probe.PAINTING_VIDEOS_JS:
            return self.host.painting
        if js == probe.PRESERVE_SNAPSHOT_JS:
            return []
        return True

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        if method == "Runtime.evaluate":
            self.evaluations.append(params.get("expression", ""))
            return {"result": {"value": True}}
        assert method == "Page.captureScreenshot"
        self.captures += 1
        return {"data": png_b64(64, 32)}


class ArmedHost:
    def __init__(self, reads: list[Any], *, advance_error: BaseException | None = None) -> None:
        self.reads = list(reads)
        self.hashes: list[Any] = []
        self.stage_map = dict(GL_STAGE)
        self.painting: Any = []
        self.transport = ArmedTransport(self)
        self.executed: list[str] = []
        self.advance_error = advance_error

    def observe(self) -> FakeObservation:
        return FakeObservation(False)

    def execute(self, operation: str, *args: Any) -> None:
        self.executed.append(operation)
        if self.advance_error is not None:
            raise self.advance_error

    def _require_transport(self) -> ArmedTransport:
        return self.transport


class TestArmedScoring:
    """Plan §3.3: `armed1to2` is True iff all five clauses hold; every way of not
    knowing is False, never None."""

    def test_the_r3_two_pooled_shape_is_green(self) -> None:
        scored = probe.score_armed(_armed_reads(), ARMED, json.loads(json.dumps(GL_CONTINUITY)), owner_ids=[1, 1])
        assert scored["verdict"] is True, scored
        assert all(scored["checks"].values())

    @pytest.mark.parametrize("name", sorted(ARMED_CLAUSE_MUTATIONS))
    def test_each_clause_is_red_alone(self, name: str) -> None:
        clause, mutate = ARMED_CLAUSE_MUTATIONS[name]
        reads, continuity = _armed_reads(), json.loads(json.dumps(GL_CONTINUITY))
        mutate(reads, continuity)
        scored = probe.score_armed(reads, ARMED, continuity, owner_ids=[1, 1])
        assert scored["verdict"] is False
        assert {key for key, ok in scored["checks"].items() if not ok} == {clause}

    @pytest.mark.parametrize("modes", [("raf", "raf"), ("rvfc", "raf"), (None, "rvfc")])
    def test_the_loop_driver_is_not_scored(self, modes: tuple[Any, Any]) -> None:
        """Owner 2026-09-23: `loopMode` is whichever driver ticked last and flips
        many times a second in a healthy LIVE loop, so it is never a clause."""
        reads = _armed_reads()
        for read, mode in zip(reads, modes):
            _gl(read)["api"]["stats"]["loopMode"] = mode
        assert probe.score_armed(reads, ARMED, GL_CONTINUITY, owner_ids=[1, 1])["verdict"] is True

    def test_no_carried_note_fails_the_events_and_cannot_vouch_for_the_pool(self) -> None:
        reads = _armed_reads()
        for read in reads:
            _events_without(read, "glreplay-carried")
        scored = probe.score_armed(reads, ARMED, GL_CONTINUITY, owner_ids=[1, 1])
        assert scored["verdict"] is False
        assert not scored["checks"]["events"] and not scored["checks"]["pool"]

    @pytest.mark.parametrize("reads", [None, [], "x", [_armed_read(1000.0, 10, 5.0)], [{"glReplay": None}, {"glReplay": None}]])
    def test_missing_reads_are_false_never_none(self, reads: Any) -> None:
        scored = probe.score_armed(reads, ARMED, GL_CONTINUITY, owner_ids=[1, 1])
        assert scored["verdict"] is False

    def test_the_r3_forced_shape_is_red(self) -> None:
        reads = _armed_reads()
        for read in reads:
            _gl(read)["api"].update(state="RETIRED", standDowns=["posterAmbiguous"])
            _events_without(read, "glreplay-live")
            _gl(read)["coreEvents"].append(_ev("glreplay-zone", **{"from": "armed"}, to="retired", reason="moduleRetired"))
        scored = probe.score_armed(reads, ARMED, GL_CONTINUITY, owner_ids=[1, 1])
        assert scored["verdict"] is False
        assert not scored["checks"]["live"] and not scored["checks"]["events"]

    def test_positive_halves_score_the_armed_boundary_for_an_armed_set(self) -> None:
        scored = probe.score_positive_halves({"armed1to2": _armed_reads()}, {"retire": None, "armed": ARMED}, True, GL_CONTINUITY)
        assert list(scored) == ["armed1to2"] and scored["armed1to2"]["checks"]["owner"] is False
        samples = [{"scene": 1, "videos": [
            {"src": "untitled.mov", "rect": dict(BIG_INSTANCE), "footprintOwner": {"elId": 1}},
            {"src": "untitled.mov", "rect": dict(SMALL_INSTANCE), "footprintOwner": {"elId": 2}},
        ]}, {"scene": 2, "videos": [{"src": "untitled.mov", "rect": dict(BIG_INSTANCE), "footprintOwner": {"elId": 2}}]}]
        scored = probe.score_positive_halves(
            {"armed1to2": _armed_reads()}, {"retire": None, "armed": ARMED}, True, GL_CONTINUITY, samples,
        )
        assert scored["armed1to2"]["verdict"] is True, scored

    def test_positive_halves_are_todays_refusals_for_the_off_set(self) -> None:
        retire = probe.retire_fact(synthetic_plan(), RETIRED_RUNTIME, BOUNDARY_KEYS)
        evidence = {"refused1to2": {"stageMap": dict(GL_STAGE), "painting": [], "poolSnapshot": []}}
        facts = {"retire": retire}
        assert probe.score_positive_halves(evidence, facts, True, {"mode": "qualified"}) == probe.score_refusals(evidence, facts, True)


class TestRectExpectationModelGl:
    def test_a_glreplay_boundary_is_live_on_and_dead_off_like_a_carried_pin(self) -> None:
        plan = synthetic_plan()
        on = probe.rect_expectations(plan, GL_RUNTIME, continuity_on=True)
        off = probe.rect_expectations(plan, GL_RUNTIME, continuity_on=False)
        assert on[1] == {BIG_ASSET: "live"} and off[1] == {BIG_ASSET: "dead"}
        assert on == probe.rect_expectations(plan, CARRIED_RUNTIME, continuity_on=True)
        assert off == probe.rect_expectations(plan, CARRIED_RUNTIME, continuity_on=False)

    def test_vgl_may_differ_from_v_only_at_the_armed_movie(self) -> None:
        plan = synthetic_plan()
        v = probe.rect_expectations(plan, RETIRED_RUNTIME, continuity_on=True)
        vgl = probe.rect_expectations(plan, GL_RUNTIME, continuity_on=True)
        probe.check_vgl_expectations(v, vgl, ARMED)
        with pytest.raises(SystemExit):
            probe.check_vgl_expectations(v, v, ARMED)
        extra = json.loads(json.dumps(vgl), object_hook=lambda d: {int(k) if k.isdigit() else k: val for k, val in d.items()})
        extra[2][BIG_ASSET] = "dead"
        with pytest.raises(SystemExit):
            probe.check_vgl_expectations(v, extra, ARMED)


# Hand-back geometry: a 0.1 stage scale keeps the frames small.
HB_STAGE = {"s": 0.1, "sy": 0.1, "ox": 0.0, "oy": 0.0, "offsetWidth": 1920.0, "offsetHeight": 1080.0}
HB_SHAPE = (108, 192, 3)


def _hb_frames() -> tuple[np.ndarray, np.ndarray]:
    """V and Vgl captures identical outside the movie, different inside it."""
    v = np.full(HB_SHAPE, 50, dtype=np.uint8)
    g = v.copy()
    g[80:106, 11:106] = 200
    return v, g


def _hb_v_record() -> dict[str, Any]:
    return {
        "status": "ok", "stageMap": dict(HB_STAGE), "painting": [],
        "before": {"pool": [], "facades": [], "coreEvents": []},
        "after": {"hash": "#3", "coreEvents": [], "api": None, "facades": []},
    }


def _hb_vgl_record() -> dict[str, Any]:
    screen = probe.to_screen_rect(BIG_INSTANCE, HB_STAGE)
    return {
        "status": "ok", "stageMap": dict(HB_STAGE),
        "painting": [{"src": "untitled.mov", "elId": 1, "rect": dict(screen)}],
        "before": {"pool": [_pool_entry(1, 5.0), _pool_entry(2, 3.0)], "facades": [], "coreEvents": []},
        "after": {
            "hash": "#3",
            "coreEvents": [
                _ev("glreplay-carried", elId=1, delta=0.01),
                _ev("glreplay-release", ok=True, mode="handoff", reason=None, elId=1, retired=[2]),
                _ev("remount-into-authored-layer", elId=1),
            ],
            "api": {
                "version": 1, "state": "RETIRED", "standDowns": ["canvasRemoved"],
                "events": [_ev("glreplay-handoff", reason="canvasRemoved", completedMs=1.8)],
                "stats": {"mutationScanMs": 0.3},
            },
            "facades": [{"elId": 3, "forElId": 1}],
        },
    }


class TestHandbackScoring:
    def _score(self, v_rec=None, v_frame=None, g_rec=None, g_frame=None, **kwargs: Any) -> dict[str, Any]:
        v, g = _hb_frames()
        return probe.score_handback(
            v_rec or _hb_v_record(), v if v_frame is None else v_frame,
            g_rec or _hb_vgl_record(), g if g_frame is None else g_frame, ARMED, **kwargs,
        )

    def test_the_green_hand_back_passes(self) -> None:
        scored = self._score()
        assert scored["verdict"] is True, scored
        assert scored["parity"]["maxOutside"] == 0 and scored["parity"]["maxInside"] > 0

    def test_v_versus_v_parity_is_zero(self) -> None:
        v, _ = _hb_frames()
        parity = probe.handback_parity(_hb_v_record(), v, _hb_v_record(), v.copy(), ARMED)
        assert parity["verdict"] is True and parity["maxOutside"] == 0 and parity["maxInside"] == 0

    def test_v_scored_as_vgl_is_red(self) -> None:
        v, _ = _hb_frames()
        scored = self._score(g_rec=_hb_v_record(), g_frame=v.copy())
        assert scored["verdict"] is False
        assert not scored["carry"]["checks"]["painting"] and not scored["carry"]["checks"]["release"]

    def test_one_pixel_outside_the_mask_is_red(self) -> None:
        _, g = _hb_frames()
        g[5, 150] = 51
        scored = self._score(g_frame=g)
        assert scored["verdict"] is False and scored["parity"]["nChangedOutside"] == 1

    def test_the_poke_pixel_is_red_unless_the_poke_is_masked(self) -> None:
        _, g = _hb_frames()
        g[0, 0] = 99
        assert self._score(g_frame=g)["verdict"] is False
        assert self._score(g_frame=g, poke=True)["verdict"] is True

    def test_an_undilated_mask_is_red_on_the_antialiased_edge(self) -> None:
        _, g = _hb_frames()
        g[90, 9] = 60
        assert self._score(g_frame=g)["verdict"] is True
        assert self._score(g_frame=g, dilate_px=0)["verdict"] is False

    def test_the_override_and_green_slot_are_masked(self) -> None:
        _, g = _hb_frames()
        g[70, 100] = 90
        assert self._score(g_frame=g)["verdict"] is True

    @pytest.mark.parametrize("mutate,check", [
        (lambda r: r["painting"][0].update(elId=7), "painting"),
        (lambda r: r["painting"][0]["rect"].update(x=r["painting"][0]["rect"]["x"] + 1.0), "painting"),
        (lambda r: r["painting"].append(dict(r["painting"][0])), "painting"),
        (lambda r: r.update(painting={"error": "x"}), "painting"),
        (lambda r: r["after"]["coreEvents"][1]["detail"].update(mode="retire"), "release+handoff"),
        (lambda r: r["after"]["coreEvents"][1]["detail"].update(retired=[]), "release"),
        (lambda r: r["before"].update(pool={"error": "x"}), "release"),
        (lambda r: r["after"]["coreEvents"].append(_ev("remount-done", elId=1)), "noRemount"),
        (lambda r: r["after"]["coreEvents"].append(_ev("remount-footprint-rect", elId=3)), "noRemount"),
    ])
    def test_each_vgl_carry_check_is_red_alone(self, mutate: Any, check: str) -> None:
        record = _hb_vgl_record()
        mutate(record)
        scored = self._score(g_rec=record)
        assert scored["verdict"] is False
        assert {key for key, ok in scored["carry"]["checks"].items() if not ok} == set(check.split("+"))

    def test_a_remount_of_an_unrelated_decoder_is_irrelevant(self) -> None:
        record = _hb_vgl_record()
        record["after"]["coreEvents"].append(_ev("remount-done", elId=9))
        assert self._score(g_rec=record)["verdict"] is True

    @pytest.mark.parametrize("which", ["v", "g"])
    def test_an_inconclusive_capture_is_inconclusive(self, which: str) -> None:
        record = _hb_v_record() if which == "v" else _hb_vgl_record()
        record["status"] = "inconclusive"
        scored = self._score(**({"v_rec": record} if which == "v" else {"g_rec": record}))
        assert scored["verdict"] is None

    def test_mismatched_frames_are_inconclusive(self) -> None:
        assert self._score(g_frame=np.zeros((10, 10, 3), dtype=np.uint8))["verdict"] is None

    def test_latency_is_report_only(self) -> None:
        assert probe.handback_latency(_hb_vgl_record()) == {"mutationScanMs": 0.3, "completedMs": 1.8}
        assert probe.handback_latency(None) == {"mutationScanMs": None, "completedMs": None}


def _hb_read(hash_: str, *, handoff: bool = False) -> dict[str, Any]:
    read: dict[str, Any] = {"t": 1.0, "hash": hash_, "ready": True, "api": {"events": []}, "coreEvents": [], "pool": [], "facades": []}
    if handoff:
        read["api"]["events"].append(_ev("glreplay-handoff", completedMs=1.0))
        read["coreEvents"].append(_ev("glreplay-release", mode="handoff"))
    return read


class TestHandbackCapture:
    def _capture(self, reads: list[Any], *, expect_handoff: bool = False, **host_kwargs: Any) -> tuple[Any, Any, ArmedHost]:
        clock = FakeClock()
        host = ArmedHost(reads, **host_kwargs)
        record, frame = probe.capture_handback(host, ARMED, expect_handoff=expect_handoff, now=clock.now, sleep=clock.sleep)
        return record, frame, host

    def test_one_advance_then_a_capture_at_the_build(self) -> None:
        record, frame, host = self._capture([_hb_read("#2"), _hb_read("#3"), _hb_read("#3")])
        assert record["status"] == "ok" and frame is not None
        assert host.executed == ["advance"]
        assert probe.TWO_RAF_JS in host.transport.evaluations

    def test_an_early_capture_is_inconclusive(self) -> None:
        record, frame, host = self._capture([_hb_read("#2"), _hb_read("#2")])
        assert record["status"] == "inconclusive" and frame is None
        assert host.transport.captures == 0

    def test_a_past_hash_poll_is_inconclusive(self) -> None:
        record, frame, _ = self._capture([_hb_read("#2"), _hb_read("#4")])
        assert record["status"] == "inconclusive" and frame is None

    def test_a_hash_that_moves_during_the_capture_is_inconclusive(self) -> None:
        record, frame, _ = self._capture([_hb_read("#2"), _hb_read("#3"), _hb_read("#4")])
        assert record["status"] == "inconclusive" and frame is None

    def test_an_unready_player_is_not_captured(self) -> None:
        unready = dict(_hb_read("#3"), ready=False)
        record, _, _ = self._capture([_hb_read("#2"), unready])
        assert record["status"] == "inconclusive"

    def test_vgl_waits_for_the_hand_off_and_its_release(self) -> None:
        record, _, _ = self._capture([_hb_read("#2"), _hb_read("#3")], expect_handoff=True)
        assert record["status"] == "inconclusive"
        record, _, _ = self._capture([_hb_read("#2"), _hb_read("#3", handoff=True), _hb_read("#3", handoff=True)], expect_handoff=True)
        assert record["status"] == "ok"

    def test_a_rejected_advance_is_inconclusive(self) -> None:
        record, frame, _ = self._capture([_hb_read("#2")], advance_error=probe.PlayerCommandRejected("busy"))
        assert record["status"] == "inconclusive" and frame is None


class TestOccludedScreenCells:
    def test_gl_row_zero_is_the_bottom_screen_row(self) -> None:
        mask = [0] * 128
        mask[0] = 1
        mask[127] = 1
        assert probe.occluded_screen_cells(mask) == [(0, 15), (7, 0)]

    @pytest.mark.parametrize("mask", [None, [0] * 127, [2] + [0] * 127])
    def test_an_unusable_mask_fails_loudly(self, mask: Any) -> None:
        with pytest.raises(ValueError):
            probe.occluded_screen_cells(mask)


def _rescore_fixture(static_screen_row: int) -> tuple[dict[str, Any], list[np.ndarray]]:
    """A Vgl slide-2 record whose armed rect is live except one screen row band,
    with markers that occlude GL row 0 (the BOTTOM row)."""
    screen = {"x": 0.0, "y": 0.0, "w": 320.0, "h": 160.0}
    frames = [np.full((160, 320, 3), 10 + 40 * i, dtype=np.uint8) for i in range(4)]
    y0 = static_screen_row * 20
    for frame in frames:
        frame[max(0, y0 - 5): y0 + 25, :, :] = 200
    dark = [0.0] * 128
    light = [255.0] * 128
    for col in range(16):
        light[col] = 0.0
    inpage = {"verdict": True, "status": "live", "reason": None, "markerDark": dark, "markerLight": light,
              "controls": {"pausedDecoder": {"verdict": False}}}
    live = probe.liveness_mask(frames)
    unmasked = probe.score_live_coverage(live, screen)
    entry = {**unmasked, "expect": "live", "label": f"{BIG_ASSET}#1"}
    combined = probe.combine_rect_oracles(entry, inpage)
    record = {
        "playerIndex": 1, "expectedRects": [{"label": f"{BIG_ASSET}#1", "screen": screen, "expect": "live"}],
        "perRect": [combined], "stray": {"verdict": True}, "instanceCheck": {"verdict": True, "painting": []},
        "verdict": combined["verdict"], "status": "fail",
    }
    return record, frames


class TestOcclusionRescore:
    def test_the_bottom_gl_row_masks_the_bottom_screen_row(self) -> None:
        record, frames = _rescore_fixture(7)
        assert record["verdict"] is None, "unmasked, the static band disagrees with the in-page LIVE read"
        probe.occlusion_rescorer(ARMED)(record, frames)
        entry = record["perRect"][0]
        assert entry["occlusion"]["status"] == "ok" and entry["occlusion"]["cells"] == 16
        assert entry["occlusion"]["unmasked"]["verdict"] is False
        assert entry["verdict"] is True and record["verdict"] is True and record["status"] == "pass"

    def test_an_unflipped_mask_would_miss_it(self) -> None:
        """Known-bad: the static band at the TOP is not what GL row 0 occludes, so
        the masked screenshot still reads it dead against the in-page LIVE."""
        record, frames = _rescore_fixture(0)
        probe.occlusion_rescorer(ARMED)(record, frames)
        entry = record["perRect"][0]
        assert entry["oracles"]["screenshot"]["verdict"] is False and entry["occlusion"]["masked"]["deadRowBands"] == [0]
        assert entry["verdict"] is None and record["verdict"] is None

    def test_no_markers_is_inconclusive_not_a_pass(self) -> None:
        record, frames = _rescore_fixture(7)
        record["perRect"][0]["oracles"]["inpage"] = None
        probe.occlusion_rescorer(ARMED)(record, frames)
        assert record["perRect"][0]["verdict"] is None and record["verdict"] is None

    def test_another_slide_is_untouched(self) -> None:
        record, frames = _rescore_fixture(7)
        record["playerIndex"] = 0
        before = json.loads(json.dumps(record))
        probe.occlusion_rescorer(ARMED)(record, frames)
        assert json.loads(json.dumps(record)) == before


def _vgl_slide(ordinal: int, *, armed: bool = False) -> dict[str, Any]:
    rect: dict[str, Any] = {"expect": "live", "verdict": True}
    if armed:
        rect.update(
            label=f"{BIG_ASSET}#1",
            oracles={
                "screenshot": {"verdict": True, "status": "live"},
                "inpage": {"verdict": True, "status": "live", "controls": {"pausedDecoder": {"verdict": False}}},
            },
            occlusion={"status": "ok", "cells": 20},
        )
    return {
        "playerIndex": ordinal - 1, "originalOrdinal": ordinal, "verdict": True, "status": "pass",
        "perRect": [rect], "instanceCheck": {"verdict": True, "painting": []},
    }


def _vgl_pass() -> dict[str, Any]:
    return {
        "pass": "Vgl", "status": "ok", "continuity": {"mode": "qualified", "glReplay": {"mode": "injected"}},
        "stageFit": {"verdict": True}, "slides": [_vgl_slide(n, armed=(n == 2)) for n in (1, 2, 3, 4)], "verdict": True,
    }


def _auto_result() -> dict[str, Any]:
    result = TestOverallStatusTruthTable()._base_result()
    result["glReplay"] = {"requested": "auto"}
    result["groundTruth"]["refusedBoundaries"] = ["continue1to2"]
    result["groundTruthGl"] = {"armed": ARMED, "armedBoundaries": ["continue1to2"]}
    for name, mode in (("A", "injected"), ("B", "off"), ("C", "injected")):
        result["arms"][name]["continuity"]["glReplay"] = {"mode": mode}
    for name in ("A", "C"):
        result["arms"][name]["continue1to2"] = {"verdict": False}
        result["arms"][name]["armed1to2"] = {"verdict": True, "reason": None}
    result["attach"]["continuity"]["glReplay"] = {"mode": "unavailable"}
    result["attach"]["continue1to2"] = {"verdict": False}
    result["attach"]["refused1to2"] = {"verdict": True, "reason": None}
    for name in ("V", "Voff"):
        result["visible"][name]["continuity"]["glReplay"] = {"mode": "off"}
    result["visible"]["Vgl"] = _vgl_pass()
    result["handback"] = {"verdict": True, "reason": None}
    result["liveRing"] = {"verdict": True, "reason": None}
    return result


class TestAutoOverallStatus:
    def test_the_auto_green_passes(self) -> None:
        assert probe.overall_status(_auto_result()) == ("pass", [])

    @pytest.mark.parametrize("arm", ["A", "C"])
    def test_an_armed_arm_needs_armed1to2(self, arm: str) -> None:
        result = _auto_result()
        result["arms"][arm]["armed1to2"] = {"verdict": False, "reason": "armed checks failed: ['pool']"}
        status, reasons = probe.overall_status(result)
        assert status == "fail" and any(f"arm {arm} armed1to2=False" in r for r in reasons)

    @pytest.mark.parametrize("arm", ["A", "C"])
    def test_a_missing_armed1to2_fails(self, arm: str) -> None:
        result = _auto_result()
        del result["arms"][arm]["armed1to2"]
        status, reasons = probe.overall_status(result)
        assert status == "fail" and any(f"arm {arm} has no armed1to2 verdict" in r for r in reasons)

    @pytest.mark.parametrize("value", [None, True, False])
    def test_continue1to2_is_report_only_in_an_armed_arm(self, value: Any) -> None:
        result = _auto_result()
        result["arms"]["A"]["continue1to2"] = {"verdict": value}
        result["arms"]["C"]["continue1to2"] = {"verdict": value}
        assert probe.overall_status(result)[0] == "pass"

    @pytest.mark.parametrize("where,mode", [
        (("arms", "A"), "notApplicable"), (("arms", "B"), "injected"), (("arms", "C"), "unavailable"),
        (("visible", "V"), "injected"), (("visible", "Voff"), "injected"), (("visible", "Vgl"), "off"),
        (("attach",), "injected"),
    ])
    def test_every_arm_and_pass_must_report_its_expected_mode(self, where: tuple[str, ...], mode: str) -> None:
        result = _auto_result()
        entry = result
        for key in where:
            entry = entry[key]
        entry["continuity"]["glReplay"] = {"mode": mode}
        status, reasons = probe.overall_status(result)
        assert status == "fail"
        assert any(f"{where[-1]} glReplay.mode={mode!r}" in r for r in reasons)

    def test_a_missing_vgl_pass_fails(self) -> None:
        result = _auto_result()
        del result["visible"]["Vgl"]
        status, reasons = probe.overall_status(result)
        assert status == "fail" and any("visible pass Vgl missing" in r for r in reasons)

    @pytest.mark.parametrize("mutate", [
        lambda s: s["perRect"][0]["oracles"]["inpage"].update(verdict=None),
        lambda s: s["perRect"][0]["oracles"]["inpage"]["controls"]["pausedDecoder"].update(verdict=True),
        lambda s: s["perRect"][0]["oracles"].update(inpage=None),
        lambda s: s["perRect"][0]["oracles"]["screenshot"].update(verdict=False),
        lambda s: s["perRect"][0].update(occlusion={"status": "unavailable"}),
        lambda s: s["instanceCheck"].update(painting=[{"authored": dict(BIG_INSTANCE)}]),
        lambda s: s["perRect"][0].update(label="other#1"),
    ])
    def test_the_vgl_armed_slide_must_be_live_in_both_oracles_with_no_video(self, mutate: Any) -> None:
        result = _auto_result()
        mutate(result["visible"]["Vgl"]["slides"][1])
        status, reasons = probe.overall_status(result)
        assert status == "fail" and any("Vgl armed slide" in r for r in reasons)

    def test_a_red_hand_back_fails_and_an_unknown_one_is_inconclusive(self) -> None:
        result = _auto_result()
        result["handback"] = {"verdict": False, "reason": "parity"}
        assert probe.overall_status(result)[0] == "fail"
        result["handback"] = {"verdict": None, "reason": "early capture"}
        assert probe.overall_status(result)[0] == "inconclusive"
        del result["handback"]
        assert probe.overall_status(result)[0] == "inconclusive"

    def test_a_red_live_ring_fails_and_an_unknown_one_is_inconclusive(self) -> None:
        """Plan (c) N3: `liveRing` False fails the run; None or missing is inconclusive."""
        result = _auto_result()
        result["liveRing"] = {"verdict": False, "reason": "7 px differ in the live ring"}
        status, reasons = probe.overall_status(result)
        assert status == "fail" and "live ring failed: 7 px differ in the live ring" in reasons
        result["liveRing"] = {"verdict": None, "reason": "a live capture is missing"}
        status, reasons = probe.overall_status(result)
        assert status == "inconclusive" and "live ring inconclusive: a live capture is missing" in reasons
        del result["liveRing"]
        status, reasons = probe.overall_status(result)
        assert status == "inconclusive" and "live ring inconclusive: not captured" in reasons

    def test_an_off_result_never_consults_gl_modes(self) -> None:
        result = TestOverallStatusTruthTable()._base_result()
        result["arms"]["B"]["continuity"]["glReplay"] = {"mode": "whatever"}
        assert probe.overall_status(result) == ("pass", [])


class RecordingHost:
    """A `LiveOutputHost` stand-in that records its constructor kwargs and stops
    the run at `start()`."""

    made: list[dict[str, Any]] = []

    def __init__(self, export_root: Any, slides: Any, **kwargs: Any) -> None:
        RecordingHost.made.append(kwargs)

    def start(self) -> None:
        raise RuntimeError("recording host stops here")

    def stop(self) -> None:
        pass


class TestGlReplayCli:
    def test_defaults_are_off_with_no_forced_fail(self) -> None:
        args = probe.parse_args([])
        assert args.gl_replay == "off" and args.gl_force_fail is None

    def test_auto_is_selectable(self) -> None:
        assert probe.parse_args(["--gl-replay", "auto"]).gl_replay == "auto"

    def test_other_values_are_rejected(self) -> None:
        with pytest.raises(SystemExit):
            probe.parse_args(["--gl-replay", "on"])

    def test_forced_fail_requires_auto(self) -> None:
        with pytest.raises(SystemExit):
            probe.parse_args(["--gl-force-fail", "posterAmbiguous"])
        args = probe.parse_args(["--gl-replay", "auto", "--gl-force-fail", "posterAmbiguous"])
        assert args.gl_force_fail == "posterAmbiguous"

    def test_forced_fail_is_not_a_pass_g_option(self) -> None:
        with pytest.raises(SystemExit):
            probe.parse_args(["--pass", "G", "--gl-replay", "auto", "--gl-force-fail", "posterAmbiguous"])

    @pytest.fixture
    def recording(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        RecordingHost.made = []
        monkeypatch.setattr(probe, "LiveOutputHost", RecordingHost)
        monkeypatch.setattr(probe, "force_viewport", lambda *a: None)
        monkeypatch.setenv("OBED_LIVE_GL_REPLAY", "auto")
        return RecordingHost.made

    @pytest.mark.parametrize("gl", [None, "off", "auto"])
    def test_run_arm_passes_gl_replay_explicitly(self, recording: list[dict[str, Any]], gl: Any) -> None:
        kwargs = {} if gl is None else {"gl_replay": gl}
        with pytest.raises(RuntimeError):
            probe.run_arm("A", Path("x"), [], {}, (64, 32), {}, **kwargs)
        assert recording[-1]["gl_replay"] == (gl or "off")

    @pytest.mark.parametrize("gl", [None, "off", "auto"])
    def test_run_visible_pass_passes_gl_replay_explicitly(self, recording: list[dict[str, Any]], tmp_path: Path, gl: Any) -> None:
        kwargs = {} if gl is None else {"gl_replay": gl}
        result = probe.run_visible_pass("V", Path("x"), [], synthetic_plan(), (64, 32), {}, tmp_path, **kwargs)
        assert result["status"] == "error"
        assert recording[-1]["gl_replay"] == (gl or "off")

    @pytest.mark.parametrize("gl", [None, "off", "auto"])
    def test_goto_arm_passes_gl_replay_explicitly(self, recording: list[dict[str, Any]], tmp_path: Path, gl: Any) -> None:
        kwargs = {} if gl is None else {"gl_replay": gl}
        with pytest.raises(RuntimeError):
            probe._run_goto_arm(
                Path("x"), [], env={}, tag="G", armed=True, instances={}, expectations={}, viewport=(64, 32),
                evidence_dir=tmp_path, character_rect=None, onset_scene_id="2", **kwargs,
            )
        assert recording[-1]["gl_replay"] == (gl or "off")

    @pytest.mark.parametrize("gl", [None, "off", "auto"])
    def test_attach_arm_passes_gl_replay_explicitly(
        self, recording: list[dict[str, Any]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gl: Any,
    ) -> None:
        class Proc:
            pid = 1

            def terminate(self) -> None:
                pass

            def wait(self, timeout: float) -> int:
                return 0

            def poll(self) -> int:
                return 0

        monkeypatch.setattr(probe, "free_port", lambda: 1)
        monkeypatch.setattr(probe, "launch_attach_chrome", lambda port, profile: Proc())
        monkeypatch.setattr(probe, "wait_for_cdp", lambda port: None)
        monkeypatch.setattr(probe, "force_exact_viewport", lambda *a: None)
        kwargs = {} if gl is None else {"gl_replay": gl}
        with pytest.raises(RuntimeError):
            probe.run_attach_arm(Path("x"), [], {}, tmp_path, {}, **kwargs)
        assert recording[-1]["gl_replay"] == (gl or "off")


class TestForcedFailSplice:
    def test_the_seed_lands_once_ahead_of_exactly_one_module_and_is_restored(self) -> None:
        original = probe.live_host_module.gl_replay_script
        with probe.forced_fail_seed("posterAmbiguous") as splice:
            script = probe.live_host_module.gl_replay_script(GL_RUNTIME)
        assert probe.live_host_module.gl_replay_script is original
        assert splice == {"reason": "posterAmbiguous", "splices": 1}
        assert script.startswith('<script id="probe-force-fail">window.__OBED_GL_REPLAY__={"debugForceFail": "posterAmbiguous"};</script>')
        assert script.count('id="probe-force-fail"') == 1 and script.count('id="obed-gl-replay"') == 1
        assert script.endswith(original(GL_RUNTIME))

    def test_a_script_breaking_reason_is_escaped(self) -> None:
        with probe.forced_fail_seed("</script><b>") as _:
            script = probe.live_host_module.gl_replay_script(GL_RUNTIME)
        assert script.count("</script>") == 2

    def test_no_module_means_no_splice(self) -> None:
        with probe.forced_fail_seed("posterAmbiguous") as splice:
            with pytest.raises(RuntimeError):
                probe.live_host_module.gl_replay_script(CARRIED_RUNTIME)
        assert splice["splices"] == 0

    def test_restored_even_when_the_run_raises(self) -> None:
        original = probe.live_host_module.gl_replay_script
        with pytest.raises(ValueError):
            with probe.forced_fail_seed("posterAmbiguous"):
                raise ValueError("boom")
        assert probe.live_host_module.gl_replay_script is original


def _forced_after(reason: str, *, zone_reason: str = "failure", live: bool = False) -> dict[str, Any]:
    zone = _ev("glreplay-zone", **{"from": "armed"}, to="retired", reason=zone_reason)
    if zone_reason == "failure":
        zone["detail"]["standDown"] = reason
    record = {
        "status": "ok",
        "after": {
            "hash": "#3", "api": {"version": 1, "state": "RETIRED", "standDowns": [reason], "events": []},
            "coreEvents": [_ev("glreplay-zone", **{"from": "pending"}, to="armed", reason="moduleReady"), zone],
        },
    }
    if live:
        record["after"]["coreEvents"].append(_ev("glreplay-live"))
    return record


def _forced_pass(verdicts: list[Any]) -> dict[str, Any]:
    return {
        "status": "ok", "continuity": {"mode": "qualified", "glReplay": {"mode": "injected"}}, "stageFit": {"verdict": True},
        "slides": [{"originalOrdinal": i + 1, "playerIndex": i, "verdict": v, "status": "pass" if v else "fail"} for i, v in enumerate(verdicts)],
    }


def _v_reference() -> dict[str, Any]:
    return dict(_forced_pass([True] * 4), continuity={"mode": "qualified", "glReplay": {"mode": "off"}})


class TestForcedFailScoring:
    def _score(self, **overrides: Any) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "v_pass": _v_reference(), "g_pass": _forced_pass([True] * 4),
            "refusal": {"verdict": True}, "g_handback": _forced_after("posterAmbiguous"),
            "parity": {"verdict": True}, "reason": "posterAmbiguous", "splice": {"splices": 1},
        }
        kwargs.update(overrides)
        return probe.score_forced(**kwargs)

    def test_a_clean_fallback_is_forced_ok_never_pass(self) -> None:
        scored = self._score()
        assert scored["status"] == "forced-ok", scored

    def test_module_retired_is_an_accepted_zone_reason(self) -> None:
        assert self._score(g_handback=_forced_after("planUnreadable", zone_reason="moduleRetired"), reason="planUnreadable")["status"] == "forced-ok"

    @pytest.mark.parametrize("override", [
        {"g_handback": _forced_after("posterAmbiguous", live=True)},
        {"g_handback": _forced_after("posterAmbiguous", zone_reason="leftDestination")},
        {"g_handback": _forced_after("glError")},
        {"g_handback": {"status": "inconclusive"}},
        {"refusal": {"verdict": False}},
        {"parity": {"verdict": None}},
        {"parity": {"verdict": False}},
        {"g_pass": _forced_pass([True, False, True, True])},
        {"g_pass": dict(_forced_pass([True] * 4), continuity={"mode": "qualified", "glReplay": {"mode": "off"}})},
        {"splice": {"splices": 0}},
        {"v_pass": dict(_v_reference(), stageFit={"verdict": False})},
        {"v_pass": dict(_v_reference(), stopError="websocket closed")},
        {"v_pass": dict(_v_reference(), status="error", error="boom")},
        {"v_pass": _forced_pass([True] * 4)},
        {"v_pass": dict(_v_reference(), slides=[])},
    ])
    def test_every_deviation_is_forced_fail(self, override: dict[str, Any]) -> None:
        assert self._score(**override)["status"] == "forced-fail"


class TestCodexR1ProbeFixes:
    """Codex r1 (stream P): each finding's known-bad, forced."""

    def test_a_substituted_sibling_is_red_on_the_owner_clause_alone(self) -> None:
        """The note names the sibling (2) and the sibling's clock runs plausibly,
        but the decoder that owned the footprint before the flip was 1."""
        reads = _armed_reads()
        for read in reads:
            _set_detail(read, "glreplay-carried", elId=2)
        _gl(reads[0])["pool"][1]["currentTime"] = 3.0
        _gl(reads[1])["pool"][1]["currentTime"] = 3.6
        scored = probe.score_armed(reads, ARMED, GL_CONTINUITY, owner_ids=[1, 1])
        assert scored["verdict"] is False
        assert {k for k, ok in scored["checks"].items() if not ok} == {"owner"}
        assert probe.score_armed(reads, ARMED, GL_CONTINUITY, owner_ids=[2, 2])["verdict"] is True

    @pytest.mark.parametrize("owners", [None, [], [None], [None, None], [1, 2], [2, None]])
    def test_no_resolved_owner_or_a_sibling_owner_is_red(self, owners: Any) -> None:
        scored = probe.score_armed(_armed_reads(), ARMED, GL_CONTINUITY, owner_ids=owners)
        assert {k for k, ok in scored["checks"].items() if not ok} == {"owner"}

    @pytest.mark.parametrize("owners", [[1, None], [None, 1, 1]])
    def test_an_unresolved_owner_read_is_dropped(self, owners: Any) -> None:
        """Owner 2026-09-23, mirroring P2's carriedClock1to2: gates r2 saw ['1', None]."""
        assert probe.score_armed(_armed_reads(), ARMED, GL_CONTINUITY, owner_ids=owners)["verdict"] is True

    def test_pre_flip_owners_read_only_the_instance_rect_before_the_flip(self) -> None:
        samples = [
            {"scene": 0, "videos": [{"src": "untitled.mov", "rect": dict(BIG_INSTANCE), "footprintOwner": {"elId": 1}}]},
            {"scene": 1, "videos": [{"src": "untitled.mov", "rect": dict(BIG_INSTANCE), "footprintOwner": None}]},
            {"scene": 1, "videos": [{"src": "other.mov", "rect": dict(BIG_INSTANCE), "footprintOwner": {"elId": 9}}]},
            {"scene": 2, "videos": [{"src": "untitled.mov", "rect": dict(BIG_INSTANCE), "footprintOwner": {"elId": 7}}]},
        ]
        assert probe.pre_flip_owner_ids(samples, ARMED) == [1, None]

    def test_a_setup_time_system_exit_stamps_forced_fail(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        def boom(*a: Any, **k: Any) -> Any:
            raise SystemExit("fixture does not derive a continuity plan")

        monkeypatch.setattr(probe, "prepare_export", boom)
        artifact = tmp_path / "forced.json"
        args = probe.parse_args(["--gl-replay", "auto", "--gl-force-fail", "posterAmbiguous", "--artifact", str(artifact)])
        probe.run_forced_fail_cli(args)
        saved = json.loads(artifact.read_text())
        assert saved["status"] == "forced-fail"
        assert "does not derive" in saved["error"]

    def test_readiness_never_accepts_a_stand_down_for_the_hand_off(self) -> None:
        read = _hb_read("#3")
        read["api"]["events"].append(_ev("glreplay-standdown", reason="glError"))
        read["coreEvents"].append(_ev("glreplay-release", mode="retire"))
        assert probe._handback_ready(read, 3, True) is False
        assert probe._handback_ready(_hb_read("#3", handoff=True), 3, True) is True
        twice = _hb_read("#3", handoff=True)
        twice["api"]["events"].append(_ev("glreplay-handoff"))
        assert probe._handback_ready(twice, 3, True) is False
        retire = _hb_read("#3", handoff=True)
        retire["coreEvents"][0]["detail"]["mode"] = "retire"
        assert probe._handback_ready(retire, 3, True) is False

    def test_final_scoring_requires_the_module_hand_off(self) -> None:
        record = _hb_vgl_record()
        record["after"]["api"]["events"] = [_ev("glreplay-standdown", reason="glError")]
        v, g = _hb_frames()
        scored = probe.score_handback(_hb_v_record(), v, record, g, ARMED)
        assert scored["verdict"] is False
        assert {k for k, ok in scored["carry"]["checks"].items() if not ok} == {"handoff"}

    @pytest.mark.parametrize("value", ["#3junk", "#3-1", " #3", "#", "3.0", None])
    def test_hash_numbers_full_match(self, value: Any) -> None:
        assert probe.hash_number(value) is None

    def test_a_malformed_hash_is_red_in_armed_scoring(self) -> None:
        reads = _armed_reads()
        _gl(reads[1]).update(hash="#2junk")
        failing = {k for k, ok in probe.score_armed(reads, ARMED, GL_CONTINUITY, owner_ids=[1, 1])["checks"].items() if not ok}
        assert failing == {"live"}
        reads = _armed_reads()
        for read in reads:
            _set_detail(read, "glreplay-arm", sceneHash="#1junk")
        failing = {k for k, ok in probe.score_armed(reads, ARMED, GL_CONTINUITY, owner_ids=[1, 1])["checks"].items() if not ok}
        assert failing == {"events"}

    def test_a_malformed_hash_never_captures_a_hand_back(self) -> None:
        clock = FakeClock()
        host = ArmedHost([_hb_read("#2"), _hb_read("#3junk")])
        record, frame = probe.capture_handback(host, ARMED, expect_handoff=False, now=clock.now, sleep=clock.sleep)
        assert record["status"] == "inconclusive" and frame is None and host.transport.captures == 0

    def test_an_unknown_reason_is_forced_fail_even_when_otherwise_green(self) -> None:
        scored = probe.score_forced(
            v_pass=_v_reference(), g_pass=_forced_pass([True] * 4), refusal={"verdict": True},
            g_handback=_forced_after("bogusReason"), parity={"verdict": True}, reason="bogusReason",
            splice={"splices": 1},
        )
        assert scored["status"] == "forced-fail"
        assert {k for k, ok in scored["checks"].items() if not ok} == {"knownReason"}


class TestArmedReadWaitsForDestination:
    """P5-A r1: read 1 was taken at #1 (LIVE precedes #2 by ~98 ms)."""

    def test_the_first_read_waits_for_the_destination_hash(self) -> None:
        clock = FakeClock()
        host = ArmedHost([_gl(r) for r in _armed_reads()])
        host.hashes = ["#1", "#1", "#2"]
        out: dict[str, Any] = {}
        probe.boundary_observer(host, {"retire": None, "armed": ARMED}, out, sleep=clock.sleep, now=clock.now)(2)
        evaluations = host.transport.evaluations
        assert evaluations.count(probe.HASH_JS) == 3
        assert evaluations.index(probe.GL_REPLAY_READ_JS) > max(i for i, js in enumerate(evaluations) if js == probe.HASH_JS)
        assert len(out["armed1to2"]) == 2

    @pytest.mark.parametrize("stuck", ["#1", "#2junk", "#3", None])
    def test_a_hash_that_never_settles_is_red_not_read(self, stuck: Any) -> None:
        clock = FakeClock()
        host = ArmedHost([_gl(r) for r in _armed_reads()])
        host.hashes = [stuck]
        out: dict[str, Any] = {}
        probe.boundary_observer(host, {"retire": None, "armed": ARMED}, out, sleep=clock.sleep, now=clock.now)(2)
        assert probe.GL_REPLAY_READ_JS not in host.transport.evaluations
        assert probe.score_armed(out["armed1to2"], ARMED, GL_CONTINUITY, owner_ids=[1, 1])["verdict"] is False


class TestVglScreenshotLiveIsPhysical:
    """Gate runner r2: `oracles.screenshot.verdict` means "met expectation", so a
    DEAD-expected rect that read dead must not count as a LIVE screenshot."""

    def _slide(self, record: dict[str, Any]) -> dict[str, Any]:
        entry = _vgl_pass()
        entry["slides"][1]["perRect"] = [record]
        return entry

    def test_a_dead_expected_rect_that_read_dead_is_red(self) -> None:
        met_dead = probe.combine_rect_oracles(
            {"expect": probe.DEAD, "verdict": True, "label": f"{BIG_ASSET}#1", "liveFrac": 0.0},
            {"verdict": False, "status": "dead", "reason": None, "controls": {"pausedDecoder": {"verdict": False}}},
        )
        met_dead["occlusion"] = {"status": "ok"}
        assert met_dead["oracles"]["screenshot"] == {"verdict": True, "status": "dead", "liveFrac": 0.0}
        scored = probe.score_vgl_armed_slide(self._slide(met_dead), ARMED)
        assert scored["checks"]["screenshotLive"] is False and scored["verdict"] is False

    def test_a_live_expected_rect_that_read_live_is_green(self) -> None:
        met_live = probe.combine_rect_oracles(
            {"expect": probe.LIVE, "verdict": True, "label": f"{BIG_ASSET}#1", "liveFrac": 0.9},
            {"verdict": True, "status": "live", "reason": None, "controls": {"pausedDecoder": {"verdict": False}}},
        )
        met_live["occlusion"] = {"status": "ok"}
        scored = probe.score_vgl_armed_slide(self._slide(met_live), ARMED)
        assert scored["verdict"] is True, scored

    @pytest.mark.parametrize("mutate", [
        lambda r: r["oracles"]["screenshot"].update(status="pass"),
        lambda r: r["oracles"]["screenshot"].pop("status"),
        lambda r: r.update(expect=probe.DEAD),
    ])
    def test_status_or_expectation_other_than_live_is_red(self, mutate: Any) -> None:
        entry = _vgl_pass()
        mutate(entry["slides"][1]["perRect"][0])
        assert probe.score_vgl_armed_slide(entry, ARMED)["checks"]["screenshotLive"] is False


class TestForcedFixtureValidationIsCaught:
    """Astra H r2: a missing fixture in forced mode must still overwrite the
    artifact with forced-fail, never leave a previous one untouched."""

    @pytest.mark.parametrize("missing", ["fixture", "index"])
    def test_a_missing_fixture_stamps_forced_fail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
        artifact = tmp_path / "forced.json"
        artifact.write_text(json.dumps({"status": "forced-ok", "stale": True}))
        index = tmp_path / "index.html"
        index.write_text("x")
        fixture = tmp_path / "fixture"
        fixture.mkdir()
        argv = ["x", "--gl-replay", "auto", "--gl-force-fail", "posterAmbiguous", "--artifact", str(artifact),
                "--fixture", str(tmp_path / "nope" if missing == "fixture" else fixture),
                "--original-index", str(tmp_path / "nope.html" if missing == "index" else index)]
        monkeypatch.setattr(sys, "argv", argv)
        probe.main()
        saved = json.loads(artifact.read_text())
        assert saved["status"] == "forced-fail" and "stale" not in saved
        assert "unavailable" in saved["error"]


# --------------------------------------------------------------------------
# GL replay (c) N3 (`git show ed7ff63c:.agents/plans/keynote_live_gl_replay_c.plan.md` §2 "Filter
# footprint", §5, §7, §8): V vs Vgl over the movie slot's ring while LIVE, i.e.
# toScreen(S) - dilate(toScreen(I), 2) - dilate(override and green slots, 2),
# rasterised with the hand-back parity's floor/ceil rule.
# --------------------------------------------------------------------------

# The fixture's real geometry (plan F3): slot 3 and the DOM instance rect.
C_SLOT = {"x": 105.123, "y": 790.847, "w": 960.0, "h": 276.0}
C_INSTANCE = {"x": 109.35, "y": 795.04, "w": 951.54, "h": 267.62}
C_ARMED = {
    "atScene": 2, "originalOrdinal": 2, "movieSlot": 1, "overrideSlots": [], "instanceRect": dict(C_INSTANCE),
    "slotRects": [{"x": 0.0, "y": 0.0, "w": 1920.0, "h": 1080.0}, dict(C_SLOT)],
}
STAGE_2560 = {"s": 4 / 3, "sy": 4 / 3, "ox": 0.0, "oy": 0.0, "offsetWidth": 2560.0, "offsetHeight": 1440.0}
STAGE_1920 = {"s": 1.0, "sy": 1.0, "ox": 0.0, "oy": 0.0, "offsetWidth": 1920.0, "offsetHeight": 1080.0}
FRAME_BG, FRAME_VIDEO = 50, 200


def _live_frames(stage: dict[str, Any], shape: tuple[int, int], instance: dict[str, float]) -> tuple[np.ndarray, np.ndarray]:
    """V and Vgl identical everywhere, both showing video exactly over toScreen(I)."""
    v = np.full((*shape, 3), FRAME_BG, dtype=np.uint8)
    screen = probe.to_screen_rect(instance, stage)
    v[round(screen["y"]):round(screen["y"] + screen["h"]), round(screen["x"]):round(screen["x"] + screen["w"])] = FRAME_VIDEO
    return v, v.copy()


def _sink(frame: Any, stage: Any) -> dict[str, Any]:
    return {"live": {"stageMap": None if stage is None else dict(stage), "frame": frame, "reason": None}}


def _ring(v: np.ndarray, g: np.ndarray, armed: dict[str, Any], stage: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return probe.score_live_ring(_sink(v, stage), _sink(g, stage), armed, **kwargs)


class TestLiveRingScoring:
    def test_identical_frames_are_green(self) -> None:
        v, g = _live_frames(STAGE_2560, (1440, 2560), C_INSTANCE)
        scored = _ring(v, g, C_ARMED, STAGE_2560)
        assert scored["verdict"] is True, scored
        assert scored["maxRing"] == 0 and scored["nRing"] > 0 and scored["dilatePx"] == probe.HANDBACK_DILATE_PX == 2

    def test_the_stretched_video_filling_the_ring_is_red(self) -> None:
        """The old-bytes known-bad: the whole texture (slot S) is video in Vgl."""
        v, g = _live_frames(STAGE_2560, (1440, 2560), C_INSTANCE)
        screen = probe.to_screen_rect(C_SLOT, STAGE_2560)
        g[round(screen["y"]):round(screen["y"] + screen["h"]), round(screen["x"]):round(screen["x"] + screen["w"])] = FRAME_VIDEO
        scored = _ring(v, g, C_ARMED, STAGE_2560)
        assert scored["verdict"] is False
        assert scored["maxRing"] == FRAME_VIDEO - FRAME_BG and scored["nChangedRing"] > 1000

    @pytest.mark.parametrize("dilate_px,verdict", [(1, False), (2, True)])
    def test_a_one_pixel_edge_bleed_at_2560_needs_the_two_pixel_dilation(self, dilate_px: int, verdict: bool) -> None:
        """Plan §2 "Filter footprint" / §13 B1: LINEAR texture filtering plus the
        bilinear CSS scale bleed video one canvas pixel past each inner edge,
        which at 2560 reaches screen row 1058 (top) and column 1416 (right) --
        outside a 1 px dilation of toScreen(I), inside a 2 px one. With 1 px, (c)
        itself would read RED."""
        v, g = _live_frames(STAGE_2560, (1440, 2560), C_INSTANCE)
        screen = probe.to_screen_rect(C_INSTANCE, STAGE_2560)
        top, right = math.floor(screen["y"]) - 2, math.ceil(screen["x"] + screen["w"]) + 1
        assert (top, right) == (1058, 1416)
        y0, y1 = math.floor(screen["y"]), math.ceil(screen["y"] + screen["h"])
        x0, x1 = math.floor(screen["x"]), math.ceil(screen["x"] + screen["w"])
        g[top, x0:x1] = FRAME_BG + 30
        g[y0:y1, right] = FRAME_BG + 30
        scored = _ring(v, g, C_ARMED, STAGE_2560, dilate_px=dilate_px)
        assert scored["verdict"] is verdict, scored
        if not verdict:
            assert scored["maxRing"] == 30

    def test_the_two_pixel_dilation_still_sees_the_third_pixel(self) -> None:
        v, g = _live_frames(STAGE_2560, (1440, 2560), C_INSTANCE)
        screen = probe.to_screen_rect(C_INSTANCE, STAGE_2560)
        g[math.floor(screen["y"]) - 3, 600] = FRAME_BG + 1
        scored = _ring(v, g, C_ARMED, STAGE_2560)
        assert scored["verdict"] is False and scored["nChangedRing"] == 1

    def test_pixels_outside_the_slot_are_not_the_ring(self) -> None:
        v, g = _live_frames(STAGE_2560, (1440, 2560), C_INSTANCE)
        slot = probe.to_screen_rect(C_SLOT, STAGE_2560)
        g[math.floor(slot["y"]) - 1, 600] = 0
        g[10, 10] = 0
        assert _ring(v, g, C_ARMED, STAGE_2560)["verdict"] is True

    def test_the_override_and_green_slots_are_masked(self) -> None:
        """Synthetic ARMED: slot 2 is both the override and the green slot and
        overlaps the movie slot's right ring edge (x 1063-1064) above y 987."""
        assert ARMED["overrideSlots"] == [2] and probe.green_slot(ARMED["slotRects"], ARMED["movieSlot"]) == 2
        v, g = _live_frames(STAGE_1920, (1080, 1920), BIG_INSTANCE)
        g[800, 1063] = 0
        assert _ring(v, g, ARMED, STAGE_1920)["verdict"] is True
        g[1000, 1063] = 0
        scored = _ring(v, g, ARMED, STAGE_1920)
        assert scored["verdict"] is False and scored["nChangedRing"] == 1

    def test_the_ring_follows_the_stage_map(self) -> None:
        """At s=2 with an offset, a diff on the scaled ring is RED, and a diff at the
        unscaled ring's position (now inside the dilated instance) is ignored."""
        stage = {"s": 2.0, "sy": 2.0, "ox": -100.0, "oy": -1000.0, "offsetWidth": 3840.0, "offsetHeight": 2160.0}
        v, g = _live_frames(stage, (1200, 2100), BIG_INSTANCE)
        g[791, 500] = 0
        assert _ring(v, g, ARMED, stage)["verdict"] is True
        g[583, 500] = 0
        scored = _ring(v, g, ARMED, stage)
        assert scored["verdict"] is False and scored["nChangedRing"] == 1

    def test_the_mask_matches_the_hand_back_rasterisation(self) -> None:
        """Every dilated rect is rasterised floor/ceil, as `handback_parity` does."""
        mask = probe.live_ring_mask(C_ARMED, [STAGE_2560], (1440, 2560))
        slot = probe.to_screen_rect(C_SLOT, STAGE_2560)
        inst = probe.to_screen_rect(C_INSTANCE, STAGE_2560)
        rows = np.flatnonzero(mask.any(axis=1))
        cols = np.flatnonzero(mask.any(axis=0))
        assert rows[0] == math.floor(slot["y"]) and rows[-1] == math.ceil(slot["y"] + slot["h"]) - 1
        assert cols[0] == math.floor(slot["x"]) and cols[-1] == math.ceil(slot["x"] + slot["w"]) - 1
        hole = ~mask[math.floor(slot["y"]):math.ceil(slot["y"] + slot["h"]), math.floor(slot["x"]):math.ceil(slot["x"] + slot["w"])]
        hole_rows, hole_cols = np.flatnonzero(hole.any(axis=1)), np.flatnonzero(hole.any(axis=0))
        assert hole_rows[0] + math.floor(slot["y"]) == math.floor(inst["y"] - 2)
        assert hole_cols[-1] + math.floor(slot["x"]) == math.ceil(inst["x"] + inst["w"] + 2) - 1

    @pytest.mark.parametrize("which", ["v", "g"])
    @pytest.mark.parametrize("sink", [
        None, {}, {"live": None}, {"live": {"stageMap": None, "frame": None, "reason": "live capture failed: boom"}},
    ])
    def test_a_missing_or_failed_capture_is_inconclusive(self, which: str, sink: Any) -> None:
        v, g = _live_frames(STAGE_1920, (1080, 1920), BIG_INSTANCE)
        sinks = [_sink(v, STAGE_1920), _sink(g, STAGE_1920)]
        sinks[0 if which == "v" else 1] = sink
        scored = probe.score_live_ring(*sinks, ARMED)
        assert scored["verdict"] is None
        if isinstance(sink, dict) and sink.get("live"):
            assert scored["reason"] == "live capture failed: boom"

    @pytest.mark.parametrize("stage", [None, {"s": 1.0, "sy": 1.2, "ox": 0.0, "oy": 0.0, "offsetWidth": 1.0, "offsetHeight": 1.0}])
    def test_an_untrustworthy_stage_map_is_inconclusive(self, stage: Any) -> None:
        v, g = _live_frames(STAGE_1920, (1080, 1920), BIG_INSTANCE)
        assert probe.score_live_ring(_sink(v, STAGE_1920), _sink(g, stage), ARMED)["verdict"] is None

    def test_mismatched_shapes_and_an_empty_ring_are_inconclusive(self) -> None:
        v, _ = _live_frames(STAGE_1920, (1080, 1920), BIG_INSTANCE)
        assert probe.score_live_ring(_sink(v, STAGE_1920), _sink(v[:10], STAGE_1920), ARMED)["verdict"] is None
        small = np.zeros((20, 20, 3), dtype=np.uint8)
        scored = probe.score_live_ring(_sink(small, STAGE_1920), _sink(small, STAGE_1920), ARMED)
        assert scored == {"verdict": None, "reason": "the live ring is empty"}


class OrderedHost(ArmedHost):
    """Records how many screenshots were taken when the build-1 advance ran."""

    def __init__(self, reads: list[Any]) -> None:
        super().__init__(reads)
        self.captures_at_advance: list[int] = []

    def execute(self, operation: str, *args: Any) -> None:
        self.captures_at_advance.append(self.transport.captures)
        super().execute(operation, *args)


def _hook_host() -> OrderedHost:
    return OrderedHost([_hb_read("#2"), _hb_read("#3"), _hb_read("#3")])


class TestLiveCaptureHook:
    def _run(self, host: ArmedHost, ordinal: int = 2, **kwargs: Any) -> dict[str, Any]:
        sink: dict[str, Any] = {}
        probe.handback_hook(ARMED, sink, expect_handoff=False, **kwargs)(host, {"originalOrdinal": ordinal}, {})
        return sink

    def test_live_is_captured_before_the_advance_only_when_asked(self) -> None:
        host = _hook_host()
        sink = self._run(host, capture_live=True)
        live = sink["live"]
        assert live["reason"] is None and live["frame"].shape == (32, 64, 3) and live["stageMap"] == GL_STAGE
        assert host.captures_at_advance == [1] and host.transport.captures == 2
        assert sink["record"]["status"] == "ok"
        evaluations = host.transport.evaluations
        assert evaluations.index(probe.TWO_RAF_JS) < evaluations.index(probe.GL_REPLAY_READ_JS)

    def test_by_default_nothing_new_is_captured(self) -> None:
        host = _hook_host()
        sink = self._run(host)
        assert set(sink) == {"record", "frame"}
        assert host.captures_at_advance == [0] and host.transport.captures == 1
        assert probe.HASH_JS not in host.transport.evaluations

    def test_other_slides_capture_nothing(self) -> None:
        host = _hook_host()
        assert self._run(host, ordinal=1, capture_live=True) == {}
        assert host.transport.captures == 0 and host.executed == []

    @pytest.mark.parametrize("hashes", [["#1"], ["#2", "#3"], ["#3"]])
    def test_a_capture_off_the_armed_scene_is_inconclusive(self, hashes: list[str]) -> None:
        host = _hook_host()
        host.hashes = list(hashes)
        live = self._run(host, capture_live=True)["live"]
        assert live["frame"] is None and live["reason"].startswith("live capture off #2")
        assert probe.score_live_ring({"live": live}, {"live": live}, ARMED)["verdict"] is None

    def test_a_failed_screenshot_is_inconclusive_and_the_hand_back_still_runs(self) -> None:
        host = _hook_host()
        calls = {"n": 0}
        original = host.transport.call

        def call(method: str, **params: Any) -> dict[str, Any]:
            if method == "Page.captureScreenshot":
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("boom")
            return original(method, **params)

        host.transport.call = call  # type: ignore[method-assign]
        sink = self._run(host, capture_live=True)
        assert sink["live"] == {"stageMap": None, "frame": None, "reason": "live capture failed: boom"}
        assert sink["record"]["status"] == "ok"

    def test_the_live_shot_is_written_as_evidence(self, tmp_path: Path) -> None:
        sink = self._run(_hook_host(), capture_live=True)
        probe.write_handback_shot(tmp_path, "Vgl", sink)
        assert sink["live"]["shot"] == str(tmp_path / "Vgl-live.png") and (tmp_path / "Vgl-live.png").is_file()
        assert (tmp_path / "Vgl-handback.png").is_file()


class TestLiveRingWiring:
    """Forced, not grepped: drive `main` (auto and off) and `run_forced_fail` with
    their heavy steps stubbed, record every `handback_hook` and fire each hook
    at the armed slide against a fake host."""

    @pytest.fixture
    def driven(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
        seen: dict[str, Any] = {"hooks": [], "passes": {}, "hosts": {}}
        original_hook = probe.handback_hook

        def hook(armed: Any, sink: Any, **kwargs: Any) -> Any:
            seen["hooks"].append(kwargs)
            return original_hook(armed, sink, **kwargs)

        def visible_pass(name: str, *args: Any, after_slide: Any = None, **kwargs: Any) -> dict[str, Any]:
            seen["passes"][name] = after_slide
            if after_slide is not None:
                host = _hook_host()
                after_slide(host, {"originalOrdinal": ARMED["originalOrdinal"]}, {})
                seen["hosts"][name] = host
            return {"pass": name}

        facts = {
            key: None for key in (
                "asset", "onset1to2", "boundaryPlayerIndex", "restartScene", "bridgeScene", "pinRect",
                "bridgeSrcRect", "destRect", "canvas", "refusals",
            )
        }
        facts.update(retire={"boundaryKey": ARMED["boundaryKey"]}, refusedBoundaries=[], rectExpectations={"V": {}, "Voff": {}})
        monkeypatch.setattr(probe, "handback_hook", hook)
        monkeypatch.setattr(probe, "run_visible_pass", visible_pass)
        monkeypatch.setattr(probe, "prepare_export", lambda *a: tmp_path)
        monkeypatch.setattr(probe, "load_slides", lambda *a: [])
        monkeypatch.setattr(probe, "ground_truth_plan", lambda *a, **k: None)
        monkeypatch.setattr(probe, "ground_truth_facts", lambda *a, **k: facts)
        monkeypatch.setattr(probe, "expected_stage_fit", lambda *a: {})
        monkeypatch.setattr(probe, "gl_ground_truth", lambda *a: (None, {"armed": ARMED, "armedBoundaries": []}, {}))
        monkeypatch.setattr(probe, "run_arm", lambda *a, **k: {})
        monkeypatch.setattr(probe, "run_attach_arm", lambda *a, **k: {})
        monkeypatch.setattr(probe, "check_no_leftover_chrome", lambda: [])
        seen["tmp"] = tmp_path
        return seen

    def _main(self, seen: dict[str, Any], monkeypatch: pytest.MonkeyPatch, *gl: str) -> dict[str, Any]:
        tmp = seen["tmp"]
        index = tmp / "index.html"
        index.write_text("x")
        artifact = tmp / "out" / "probe.json"
        argv = ["x", "--fixture", str(tmp), "--original-index", str(index), "--artifact", str(artifact), *gl]
        monkeypatch.setattr(sys, "argv", argv)
        probe.main()
        return json.loads(artifact.read_text())

    def test_the_auto_run_captures_live_in_v_and_vgl_and_scores_the_ring(self, driven: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
        result = self._main(driven, monkeypatch, "--gl-replay", "auto")
        assert driven["hooks"] == [
            {"expect_handoff": False, "capture_live": True}, {"expect_handoff": True, "capture_live": True},
        ]
        assert {name: host.captures_at_advance for name, host in driven["hosts"].items()} == {"V": [1], "Vgl": [1]}
        ring = result["liveRing"]
        assert ring["verdict"] is None and ring["reason"] == "the live ring is empty"
        assert result["visible"]["V"]["live"]["reason"] is None and "frame" not in result["visible"]["V"]["live"]
        assert result["visible"]["Vgl"]["live"]["shot"].endswith("Vgl-live.png")

    def test_the_off_run_records_nothing_new(self, driven: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
        result = self._main(driven, monkeypatch)
        assert driven["hooks"] == [] and driven["passes"] == {"V": None, "Voff": None}
        assert "liveRing" not in result and "live" not in result["visible"]["V"]

    def test_the_forced_fail_run_records_nothing_new(self, driven: dict[str, Any]) -> None:
        tmp = driven["tmp"]
        args = probe.parse_args(["--gl-replay", "auto", "--gl-force-fail", "posterAmbiguous", "--artifact", str(tmp / "f.json")])
        result = probe.run_forced_fail(args)
        assert driven["hooks"] == [{"expect_handoff": False}, {"expect_handoff": False, "refusal": True}]
        assert {name: host.captures_at_advance for name, host in driven["hosts"].items()} == {"V": [0], "VglForced": [0]}
        assert all(probe.HASH_JS not in host.transport.evaluations for host in driven["hosts"].values())
        assert "liveRing" not in result and "live" not in result["visible"]["V"]


# --- Looping movies (plan keynote_live_continuity_loopmode §5, WS-B) --------------------

LOOP_P = 46.0333
LEGACY_REV = "bd9ae9f4"


def _loop_fields(samples: list[dict[str, Any]], *, loop: bool = True, period: float | None = LOOP_P) -> list[dict[str, Any]]:
    for row in samples:
        for v in row["videos"]:
            v.update(loop=loop, duration=period, ended=False)
    return samples


def wrap_samples(*, lead_s: float = 0.3, period: float = LOOP_P, n_after: int = 40, **kwargs: Any) -> list[dict[str, Any]]:
    """`rows_around_boundary`, but the carried clock starts `lead_s` before the period end and
    wraps to ~0 after the boundary, exactly as the browser's `loop` restarts the file."""
    samples = rows_around_boundary(start_time=period - lead_s, n_after=n_after, **kwargs)
    for row in samples:
        for v in row["videos"]:
            v["currentTime"] = v["currentTime"] % period
    return _loop_fields(samples)


def _load_legacy_probe():
    try:
        text = subprocess.run(
            ["git", "show", f"{LEGACY_REV}:scripts/live_continuity_probe.py"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_loader("legacy_live_continuity_probe", loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(REPO / "scripts" / "live_continuity_probe.py")
    exec(compile(text, f"{LEGACY_REV}:live_continuity_probe.py", "exec"), module.__dict__)
    return module


LEGACY = _load_legacy_probe()


def _continuity_batteries() -> dict[str, tuple[list[dict[str, Any]], dict[str, Any]]]:
    moving = {"transition_scene": 7}
    return {
        "clean": (rows_around_boundary(), {}),
        "stall": (rows_around_boundary(stall_run_s=0.5), {}),
        "drop": (rows_around_boundary(clock_drop=0.2), {}),
        "owner": (rows_around_boundary(owner_mismatch_after=True), {}),
        "offRect": (rows_around_boundary(off_rect_after=True), {}),
        "disconnected": (rows_around_boundary(disconnected_after=True), {}),
        "wrap": (wrap_samples(), {}),
        "moving": (moving_boundary_samples(), moving),
    }


class TestWrapAwareScorerDefaultIsLegacy:
    """`loop_period_s=None` must be today's scorer byte-for-byte (L2 CvC, offline half)."""

    @pytest.mark.skipif(LEGACY is None, reason=f"git history for {LEGACY_REV} is unavailable")
    @pytest.mark.parametrize("name", sorted(_continuity_batteries()))
    def test_none_matches_the_pre_loop_scorer_byte_for_byte(self, name: str) -> None:
        samples, kwargs = _continuity_batteries()[name]
        scene = 8 if kwargs else 2.0
        legacy = LEGACY.score_continuity(samples, ASSET, scene, SRC_RECT, DST_RECT, True, **kwargs)
        current = probe.score_continuity(samples, ASSET, scene, SRC_RECT, DST_RECT, True, loop_period_s=None, **kwargs)
        assert json.dumps(current, sort_keys=True) == json.dumps(legacy, sort_keys=True)

    @pytest.mark.skipif(LEGACY is None, reason=f"git history for {LEGACY_REV} is unavailable")
    def test_score_boundaries_default_matches_the_pre_loop_scorer(self) -> None:
        facts = {
            "asset": ASSET, "onset1to2": 2.0, "restartScene": 6, "bridgeScene": 8,
            "pinRect": SRC_RECT, "bridgeSrcRect": SRC_RECT, "destRect": DST_RECT,
        }
        samples = wrap_samples()
        legacy = LEGACY.score_boundaries(samples, facts, True)
        assert json.dumps(probe.score_boundaries(samples, facts, True), sort_keys=True) == json.dumps(legacy, sort_keys=True)

    @pytest.mark.parametrize("name", sorted(_continuity_batteries()))
    def test_none_adds_no_keys(self, name: str) -> None:
        samples, kwargs = _continuity_batteries()[name]
        scene = 8 if kwargs else 2.0
        result = probe.score_continuity(samples, ASSET, scene, SRC_RECT, DST_RECT, True, **kwargs)
        assert "wraps" not in result and "wrapTimes" not in result
        assert "groundedStart" not in (result.get("window") or {})


class TestWrapAwareScorer:
    def test_known_bad_a_real_wrap_fails_the_strict_scorer(self) -> None:
        result = probe.score_continuity(wrap_samples(), ASSET, 2.0, SRC_RECT, DST_RECT, True)
        assert result["verdict"] is False
        assert result["maxDropS"] > 46.0

    def test_a_real_wrap_passes_with_the_period_and_is_counted_once(self) -> None:
        result = probe.score_continuity(wrap_samples(), ASSET, 2.0, SRC_RECT, DST_RECT, True, loop_period_s=LOOP_P)
        assert result["verdict"] is True, result
        assert result["wraps"] == 1 and len(result["wrapTimes"]) == 1
        assert result["maxDropS"] == 0.0
        assert result["windowAdvanceS"] >= probe.MIN_ADVANCE_S

    def test_known_bad_a_mid_period_drop_fails_even_with_the_period(self) -> None:
        samples = _loop_fields(rows_around_boundary(start_time=20.0, clock_drop=0.2))
        result = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, True, loop_period_s=LOOP_P)
        assert result["verdict"] is False
        assert result["wraps"] == 0
        assert result["maxDropS"] == pytest.approx(0.2, abs=0.02)

    def test_a_restart_to_zero_from_mid_period_is_not_a_wrap(self) -> None:
        samples = _loop_fields(rows_around_boundary(start_time=20.0, clock_drop=20.0 + 0.32))
        result = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, True, loop_period_s=LOOP_P)
        assert result["verdict"] is False and result["wraps"] == 0
        assert result["maxDropS"] > 19.0

    def test_a_jump_from_the_end_to_mid_period_is_not_a_wrap(self) -> None:
        samples = wrap_samples()
        for row in samples:
            for v in row["videos"]:
                if v["currentTime"] < 1.0:
                    v["currentTime"] += 10.0
        result = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, True, loop_period_s=LOOP_P)
        assert result["verdict"] is False and result["wraps"] == 0

    def test_a_freeze_after_the_wrap_still_fails(self) -> None:
        samples = wrap_samples(lead_s=0.05, stall_run_s=0.5)
        result = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, True, loop_period_s=LOOP_P)
        assert result["verdict"] is False
        assert result["longestStallS"] > probe.MAX_STALL_S

    def test_two_wraps_are_both_counted(self) -> None:
        samples = wrap_samples(period=0.5, lead_s=0.1)
        result = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, True, loop_period_s=0.5)
        assert result["wraps"] == 2

    def test_unwrap_tolerance_is_two_frames_plus_the_step(self) -> None:
        rows = [{"t": 0.0, "currentTime": 9.9}, {"t": 50.0, "currentTime": 0.1}]
        unwrapped, wraps = probe.unwrap_clock(rows, 10.0, fps=30.0)
        assert wraps == [50.0] and unwrapped[1]["currentTime"] == pytest.approx(10.1)
        tol = 2 / 30 + 0.05
        edge = [{"t": 0.0, "currentTime": 10.0 - tol - 0.01}, {"t": 50.0, "currentTime": 0.0}]
        assert probe.unwrap_clock(edge, 10.0, fps=30.0)[1] == []
        late = [{"t": 0.0, "currentTime": 10.0}, {"t": 50.0, "currentTime": tol + 0.01}]
        assert probe.unwrap_clock(late, 10.0, fps=30.0)[1] == []

    def test_min_window_start_clips_and_keeps_the_grounded_start(self) -> None:
        samples = rows_around_boundary()
        full = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, True, loop_period_s=LOOP_P)
        clipped = probe.score_continuity(
            samples, ASSET, 2.0, SRC_RECT, DST_RECT, True, loop_period_s=LOOP_P, min_window_start=160.0,
        )
        assert clipped["window"]["groundedStart"] == full["window"]["start"]
        assert clipped["window"]["start"] == 160.0
        assert clipped["sampleCount"] == full["sampleCount"] - 10

    def test_sampler_records_loop_duration_and_ended(self) -> None:
        for field in ("loop: v.loop", "ended: v.ended", "duration: isFinite(v.duration) ? v.duration : null"):
            assert field in probe.SAMPLER_JS


class TestUnplannedWraps:
    def test_a_looping_elements_wrap_is_found(self) -> None:
        found = probe.unplanned_wraps(wrap_samples())
        assert len(found) == 1
        assert found[0]["from"] > 46.0 and found[0]["to"] < 0.1 and found[0]["duration"] == LOOP_P

    def test_a_non_looping_element_never_invalidates(self) -> None:
        samples = wrap_samples()
        for row in samples:
            for v in row["videos"]:
                v["loop"] = False
        assert probe.unplanned_wraps(samples) == []

    def test_a_small_drop_is_left_to_the_strict_scorer(self) -> None:
        assert probe.unplanned_wraps(_loop_fields(rows_around_boundary(clock_drop=0.2))) == []

    def test_a_looping_element_without_a_duration_is_not_guessed(self) -> None:
        assert probe.unplanned_wraps(_loop_fields(wrap_samples(), period=None)) == []

    def test_legacy_samples_without_the_fields_find_nothing(self) -> None:
        assert probe.unplanned_wraps(rows_around_boundary(start_time=LOOP_P - 0.3)) == []

    def _green(self) -> dict[str, Any]:
        return TestOverallStatusTruthTable()._base_result()

    @pytest.mark.parametrize("where", ["A", "B", "C", "attach"])
    def test_any_standard_arm_with_an_unplanned_wrap_is_invalid(self, where: str) -> None:
        result = self._green()
        entry = result["attach"] if where == "attach" else result["arms"][where]
        entry["unplannedWraps"] = probe.unplanned_wraps(wrap_samples())
        status, reasons = probe.overall_status(result)
        assert status == "invalid"
        assert len(reasons) == 1 and "retake" in reasons[0]

    def test_an_empty_list_changes_nothing(self) -> None:
        result = self._green()
        for entry in [*result["arms"].values(), result["attach"]]:
            entry["unplannedWraps"] = []
        assert probe.overall_status(result) == ("pass", [])


FW_PERIOD = 46.0333
FW_SEEKED = 10_000.0


def _fw_recorder(
    *, offset_ms: float = 375.0, press: float = FW_SEEKED + 2000.0, wrap: bool = True, period: float = FW_PERIOD,
    stop_at: float | None = None, el_id: Any = 1, dt: float = 1000.0 / 30.0, end: float = FW_SEEKED + 7000.0,
) -> dict[str, Any]:
    """rVFC frames from the seek on: the clock lands `lead` before the end and wraps (or,
    `wrap=False`, ends and stops presenting) `offset_ms` after the press."""
    wrap_t = press + offset_ms
    lead_s = (wrap_t - FW_SEEKED) / 1000.0
    frames = []
    t = FW_SEEKED
    while t <= end and (stop_at is None or t <= stop_at):
        media = period - lead_s + (t - FW_SEEKED) / 1000.0
        if media >= period:
            if not wrap:
                break
            media %= period
        frames.append({"now": t, "mediaTime": media, "presentedFrames": len(frames)})
        t += dt
    return {
        "seekedT": FW_SEEKED, "target": period - lead_s, "frames": frames, "elId": el_id, "probeId": 1, "loop": wrap,
        "duration": period, "playbackRate": 1, "ended": not wrap,
    }


def _fw_take(*, press: float = FW_SEEKED + 2000.0, count: int = 1, reached: bool = True, **extra: Any) -> dict[str, Any]:
    return {"domId": "6BB39942-video", "select": {"count": count}, "pressT": press, "reached": reached, **extra}


def _fw_window() -> dict[str, float]:
    return {"start": FW_SEEKED + 1000.0, "end": FW_SEEKED + 6000.0}


def _fw_score(
    *, boundary: str = "3to4", offset_ms: float = 375.0, recorder: Any = None, take: Any = None,
    continuity: Any = None, clock: Any = None, reads: Any = None, armed: Any = None, restart: Any = None,
    page_errors: Any = (),
) -> dict[str, Any]:
    recorder = _fw_recorder(offset_ms=offset_ms) if recorder is None else recorder
    return probe.score_forced_wrap(
        boundary=boundary, offset_ms=offset_ms, take=_fw_take() if take is None else take, recorder=recorder,
        node_period_s=FW_PERIOD,
        continuity={"verdict": True, "wraps": 1, "elementId": 1} if continuity is None else continuity,
        clock=probe.score_recorder_clock(recorder, _fw_window()) if clock is None else clock,
        reads=reads, armed=armed, restart={"verdict": False} if restart is None else restart,
        rects=[dict(BIG_INSTANCE)], page_errors=list(page_errors) if page_errors is not None else None,
    )


def _fw_reads(*, stand_downs: list[str] | None = None, zones: list[tuple[str, str, str]] = (), carried: int = 1) -> list[dict[str, Any]]:
    reads = _armed_reads()
    for read in reads:
        gl = read["glReplay"]
        _set_detail(read, "glreplay-carried", elId=carried)
        if stand_downs is not None:
            gl["api"]["standDowns"] = list(stand_downs)
            gl["api"]["state"] = "STOOD_DOWN" if stand_downs else "LIVE"
        gl["coreEvents"].extend(
            _ev("glreplay-zone", key="movie1", **{"from": a}, to=b, reason=c, sceneHash="#1") for a, b, c in zones
        )
    return reads


class TestForceWrapArgs:
    def test_parses_boundary_and_signed_offset(self) -> None:
        assert probe.parse_args(["--force-wrap", "1to2:-200"]).force_wrap == {"boundary": "1to2", "offsetMs": -200}
        assert probe.parse_args(["--force-wrap", "3to4:1700"]).force_wrap == {"boundary": "3to4", "offsetMs": 1700}
        assert probe.parse_args([]).force_wrap is None and probe.parse_args([]).rescore is None

    @pytest.mark.parametrize("value", ["2to3:0", "1to2", "1to2:1.5", "3to4:+x", ""])
    def test_rejects_anything_else(self, value: str) -> None:
        with pytest.raises(SystemExit):
            probe.parse_args(["--force-wrap", value])

    @pytest.mark.parametrize("extra", [["--pass", "G"], ["--gl-replay", "auto", "--gl-force-fail", "planUnreadable"], ["--rescore", "x.json"]])
    def test_runs_on_its_own(self, extra: list[str]) -> None:
        with pytest.raises(SystemExit):
            probe.parse_args(["--force-wrap", "1to2:0", *extra])


class TestForceWrapSourceInstance:
    ROOT = REPO / "tests" / "fixtures" / "live_continuity"

    def _facts_and_nodes(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        slides = probe.load_slides(self.ROOT)
        plan = probe.derive_plan(self.ROOT, slides, resolver=lambda root, rel: root / rel)
        return probe.ground_truth_facts(plan), probe.movie_nodes(self.ROOT, slides)

    def test_selects_the_continuing_instance_by_rect_on_each_source_slide(self) -> None:
        facts, nodes = self._facts_and_nodes()
        pin = probe.source_instance(nodes, 0, facts["asset"], facts["pinRect"])
        bridge = probe.source_instance(nodes, 2, facts["asset"], facts["bridgeSrcRect"])
        assert pin["domId"] == "6BB39942-6C61-4763-839D-777C09E7E594-video"
        assert bridge["domId"] == "98D59E27-7807-477D-BEFB-27EB1CF1D185-video"
        assert pin["periodS"] == pytest.approx(46.0333, abs=1e-3)

    def test_no_or_two_matching_instances_fail_closed(self) -> None:
        facts, nodes = self._facts_and_nodes()
        with pytest.raises(SystemExit):
            probe.source_instance(nodes, 0, facts["asset"], facts["bridgeSrcRect"])
        with pytest.raises(SystemExit):
            probe.source_instance([*nodes, dict(nodes[0])], 0, facts["asset"], facts["pinRect"])

    def test_loop_period_is_the_single_trim_of_the_asset(self) -> None:
        facts, nodes = self._facts_and_nodes()
        assert probe.loop_period_of(nodes, facts["asset"]) == pytest.approx(46.0333, abs=1e-3)
        with pytest.raises(SystemExit):
            probe.loop_period_of([*nodes, dict(nodes[0], endTime=10.0)], facts["asset"])


class TestForceWrapInvalid:
    def _invalid(self, *, take: Any = None, recorder: Any = None, offset_ms: float = 375.0) -> list[str]:
        return probe.force_wrap_invalid(
            _fw_take() if take is None else take, _fw_recorder(offset_ms=offset_ms) if recorder is None else recorder,
            offset_ms=offset_ms, node_period_s=FW_PERIOD,
        )

    @pytest.mark.parametrize("offset_ms", [-200, 0, 375, 750, 1125, 1700])
    def test_an_on_target_take_is_valid_at_every_planned_offset(self, offset_ms: int) -> None:
        assert self._invalid(offset_ms=offset_ms) == []
        wrap = probe.recorded_wrap(_fw_recorder(offset_ms=offset_ms))
        assert abs(wrap["t"] - (FW_SEEKED + 2000.0) - offset_ms) <= 1000.0 / 30.0

    @pytest.mark.parametrize("count", [0, 2])
    def test_a_missing_or_duplicate_dom_id_is_invalid(self, count: int) -> None:
        assert "expected exactly one" in self._invalid(take=_fw_take(count=count))[0]

    def test_a_wrap_off_target_by_more_than_100ms_is_invalid(self) -> None:
        reasons = self._invalid(recorder=_fw_recorder(offset_ms=375.0 + 150.0))
        assert any("from the press" in r for r in reasons)
        assert self._invalid(recorder=_fw_recorder(offset_ms=375.0 + 60.0)) == []

    def test_no_recorded_wrap_is_not_invalid_it_is_left_to_fail(self) -> None:
        assert self._invalid(recorder=_fw_recorder(wrap=False)) == []

    def test_a_press_too_soon_after_the_seek_is_invalid(self) -> None:
        press = FW_SEEKED + 1400.0
        reasons = self._invalid(take=_fw_take(press=press), recorder=_fw_recorder(press=press))
        assert any("after the seek" in r for r in reasons)

    def test_too_few_frames_between_seek_and_press_is_invalid(self) -> None:
        recorder = _fw_recorder(dt=250.0)
        assert any("frame(s) between" in r for r in self._invalid(recorder=recorder))

    def test_a_duration_that_is_not_the_nodes_trim_is_invalid(self) -> None:
        recorder = _fw_recorder()
        recorder["duration"] = FW_PERIOD + 0.1
        assert any("within one frame" in r for r in self._invalid(recorder=recorder))

    def test_a_seek_that_landed_elsewhere_is_invalid(self) -> None:
        recorder = _fw_recorder()
        recorder["target"] -= 1.0
        assert any("seek landed" in r for r in self._invalid(recorder=recorder))

    @pytest.mark.parametrize("mutate", ["unseeked", "unpressed", "unreached", "rate", "error", "unread"])
    def test_every_other_harness_gap_is_invalid(self, mutate: str) -> None:
        take, recorder = _fw_take(), _fw_recorder()
        if mutate == "unseeked":
            recorder["seekedT"] = None
        elif mutate == "unpressed":
            take["pressT"] = None
        elif mutate == "unreached":
            take["reached"] = False
        elif mutate == "rate":
            recorder["playbackRate"] = 2
        elif mutate == "error":
            take["error"] = "advance rejected"
        elif mutate == "unread":
            recorder = None
        assert probe.force_wrap_invalid(take, recorder, offset_ms=375.0, node_period_s=FW_PERIOD)


class TestRecorderClock:
    def test_one_wrap_with_a_steady_clock_passes(self) -> None:
        result = probe.score_recorder_clock(_fw_recorder(), _fw_window())
        assert result["verdict"] is True and result["wraps"] == 1
        assert result["windowAdvanceS"] > 4.0

    def test_known_bad_a_movie_that_ends_fails(self) -> None:
        result = probe.score_recorder_clock(_fw_recorder(wrap=False), _fw_window())
        assert result["verdict"] is False and result["wraps"] == 0
        assert result["longestGapS"] > probe.MAX_STALL_S

    def test_a_decoder_that_stops_presenting_fails(self) -> None:
        result = probe.score_recorder_clock(_fw_recorder(stop_at=FW_SEEKED + 4000.0), _fw_window())
        assert result["verdict"] is False and result["longestGapS"] > probe.MAX_STALL_S

    def test_a_mid_period_drop_fails(self) -> None:
        recorder = _fw_recorder()
        for frame in recorder["frames"]:
            if frame["now"] > FW_SEEKED + 4000.0:
                frame["mediaTime"] -= 0.2
        result = probe.score_recorder_clock(recorder, _fw_window())
        assert result["verdict"] is False and result["maxDropS"] > probe.MAX_DROP_S

    def test_two_wraps_fail(self) -> None:
        recorder = _fw_recorder(period=1.5, offset_ms=-600.0)
        result = probe.score_recorder_clock(recorder, _fw_window())
        assert result["verdict"] is False and result["wraps"] > 1

    def test_forced_window_is_clipped_past_the_seek(self) -> None:
        samples = rows_around_boundary(n_before=200, n_after=200)
        window = probe.forced_window(samples, 2.0, None, seeked_t=1000.0)
        assert window["start"] == 2000.0
        assert window["groundedStart"] < window["start"]


class TestScoreForcedWrap:
    def test_bridge_carry_holds_across_exactly_one_wrap(self) -> None:
        result = _fw_score()
        assert (result["status"], result["outcome"]) == ("pass", "carried")
        assert result["wrapFromPressMs"] == pytest.approx(375.0, abs=1000.0 / 30.0)

    @pytest.mark.parametrize("continuity", [
        {"verdict": True, "wraps": 0, "elementId": 1}, {"verdict": True, "wraps": 2, "elementId": 1},
        {"verdict": False, "wraps": 1, "elementId": 1},
    ])
    def test_bridge_needs_a_true_verdict_and_exactly_one_wrap(self, continuity: dict[str, Any]) -> None:
        result = _fw_score(continuity=continuity)
        assert result["status"] == "fail"

    @pytest.mark.parametrize("tracked", [2, None])
    def test_known_bad_bridge_scoring_another_element_than_the_seeked_one_fails(self, tracked: Any) -> None:
        result = _fw_score(continuity={"verdict": True, "wraps": 1, "elementId": tracked})
        assert result["status"] == "fail"
        assert result["carry"]["checks"]["tracksSeeked"] is False

    def test_known_bad_bridge_with_a_frozen_recorder_fails(self) -> None:
        result = _fw_score(recorder=_fw_recorder(stop_at=FW_SEEKED + 4000.0))
        assert result["status"] == "fail"
        assert result["carry"]["checks"]["recorderClock"] is False

    def test_known_bad_a_non_loop_movie_ends_in_window_and_fails(self) -> None:
        recorder = _fw_recorder(wrap=False)
        result = _fw_score(recorder=recorder, continuity={"verdict": False, "wraps": 0}, restart={"verdict": True})
        assert result["status"] == "fail" and result["reasons"] == ["no wrap was recorded"]

    def test_invalid_wins_over_everything(self) -> None:
        result = _fw_score(take=_fw_take(reached=False))
        assert result["status"] == "invalid" and result["outcome"] is None

    def test_armed_carry_holds(self) -> None:
        result = _fw_score(boundary="1to2", reads=_fw_reads(), armed=ARMED, continuity={"verdict": False})
        assert (result["status"], result["outcome"]) == ("pass", "carried"), result
        assert result["carry"]["checks"] == {
            "armSeen": True, "live": True, "noStandDown": True, "carriesSeeked": True, "noPainting": True,
        }

    def test_armed_carry_of_another_element_fails(self) -> None:
        result = _fw_score(boundary="1to2", reads=_fw_reads(carried=2), armed=ARMED)
        assert result["status"] == "fail"
        assert result["carry"]["checks"]["carriesSeeked"] is False

    def test_armed_carry_with_a_frozen_clock_fails(self) -> None:
        recorder = _fw_recorder(stop_at=FW_SEEKED + 4000.0)
        result = _fw_score(boundary="1to2", reads=_fw_reads(), armed=ARMED, recorder=recorder)
        assert result["status"] == "fail"

    def test_armed_carry_without_the_arm_note_fails(self) -> None:
        reads = _fw_reads()
        for read in reads:
            _events_without(read, "glreplay-arm")
        result = _fw_score(boundary="1to2", reads=reads, armed=ARMED)
        assert result["status"] == "fail" and result["carry"]["checks"]["armSeen"] is False

    def test_video_not_ready_stand_down_is_a_listed_fallback(self) -> None:
        result = _fw_score(boundary="1to2", reads=_fw_reads(stand_downs=["videoNotReady"]), armed=ARMED)
        assert (result["status"], result["outcome"]) == ("pass", "videoNotReady")
        assert result["fallbackEvents"]["standDowns"] == ["videoNotReady"]

    def test_not_pooled_retire_is_a_listed_fallback(self) -> None:
        reads = _fw_reads(zones=[("armed", "retired", "notPooled")])
        for read in reads:
            _events_without(read, "glreplay-carried")
        result = _fw_score(boundary="1to2", reads=reads, armed=ARMED)
        assert (result["status"], result["outcome"]) == ("pass", "notPooled")

    @pytest.mark.parametrize("stand_downs", [["canvasLost"], ["videoNotReady", "glError"]])
    def test_any_other_stand_down_fails(self, stand_downs: list[str]) -> None:
        result = _fw_score(boundary="1to2", reads=_fw_reads(stand_downs=stand_downs), armed=ARMED)
        assert result["status"] == "fail"

    def test_g2_fallbacks_do_not_count_on_the_unarmed_boundary(self) -> None:
        result = _fw_score(
            boundary="3to4", reads=_fw_reads(stand_downs=["videoNotReady"]), armed=ARMED,
            continuity={"verdict": False, "wraps": 1},
        )
        assert result["status"] == "fail"

    def test_raw_restart_with_nothing_preserved_painting_is_a_listed_fallback(self) -> None:
        reads = _fw_reads()
        for read in reads:
            read["painting"] = [{"src": "untitled.mov", "elId": None, "rect": dict(BIG_INSTANCE)}]
        result = _fw_score(continuity={"verdict": False, "wraps": 0}, reads=reads, restart={"verdict": True})
        assert (result["status"], result["outcome"]) == ("pass", "rawRestart")

    def test_raw_restart_with_a_preserved_element_still_painting_fails(self) -> None:
        reads = _fw_reads()
        for read in reads:
            read["painting"] = [{"src": "untitled.mov", "elId": 7, "rect": dict(BIG_INSTANCE)}]
        result = _fw_score(continuity={"verdict": False, "wraps": 0}, reads=reads, restart={"verdict": True})
        assert result["status"] == "fail"
        assert result["fallback"]["preservedPainting"]

    def test_raw_restart_needs_a_readable_destination(self) -> None:
        result = _fw_score(continuity={"verdict": False, "wraps": 0}, reads=None, restart={"verdict": True})
        assert result["status"] == "fail"

    def test_a_fallback_without_a_recorded_wrap_fails(self) -> None:
        result = _fw_score(
            boundary="1to2", reads=_fw_reads(stand_downs=["videoNotReady"]), armed=ARMED,
            recorder=_fw_recorder(wrap=False),
        )
        assert result["status"] == "fail" and result["reasons"] == ["no wrap was recorded"]


class TestRawRestart:
    def _fresh(self, *, advancing: bool) -> list[dict[str, Any]]:
        samples = []
        for i in range(40):
            t = i * 50.0
            scene = 7 if i < 20 else 8
            videos = [video(id=1, el_id=1, t=t, scene=scene, current_time=5 + t / 1000)]
            if scene == 8:
                current = (t - 1000.0) / 1000.0 if advancing else 0.0
                videos.append(video(id=2, el_id=None, t=t, scene=scene, current_time=current))
            samples.append(sample(t, scene, *videos))
        return samples

    def test_a_fresh_decoder_that_plays_is_a_raw_restart(self) -> None:
        result = probe.score_raw_restart(self._fresh(advancing=True), ASSET, 8)
        assert result["verdict"] is True and result["elementId"] == 2

    def test_a_fresh_decoder_parked_at_zero_is_not(self) -> None:
        result = probe.score_raw_restart(self._fresh(advancing=False), ASSET, 8)
        assert result["verdict"] is False and result["advanceS"] == 0.0


class TestRescoreArtifact:
    FACTS = {
        "asset": ASSET, "onset1to2": 2.0, "restartScene": 6, "bridgeScene": 8,
        "pinRect": SRC_RECT, "bridgeSrcRect": SRC_RECT, "destRect": DST_RECT,
    }

    def _artifact(self, tmp_path: Path, samples: list[dict[str, Any]]) -> Path:
        arm = {"continuity": {"mode": "qualified"}, "samples": samples}
        arm.update(json.loads(json.dumps(probe.score_boundaries(samples, self.FACTS, True))))
        path = tmp_path / "host.json"
        path.write_text(json.dumps({"groundTruth": self.FACTS, "arms": {"A": arm}, "attach": dict(arm)}))
        return path

    def test_samples_without_a_wrap_rescore_identically(self, tmp_path: Path) -> None:
        report = probe.rescore_artifact(self._artifact(tmp_path, rows_around_boundary()), LOOP_P)
        assert report["ok"] is True
        assert all(arm["strictMatchesArtifact"] and arm["identical"] for arm in report["arms"].values())

    def test_samples_with_a_wrap_do_not(self, tmp_path: Path) -> None:
        report = probe.rescore_artifact(self._artifact(tmp_path, wrap_samples()), LOOP_P)
        assert report["ok"] is False and report["arms"]["arm A"]["identical"] is False
        assert len(report["arms"]["arm A"]["wrapTimes"]["continue1to2"]) == 1

    def test_known_bad_a_stored_verdict_the_strict_rescore_does_not_reproduce_fails(self, tmp_path: Path) -> None:
        path = self._artifact(tmp_path, rows_around_boundary())
        data = json.loads(path.read_text())
        data["attach"]["continue1to2"]["verdict"] = not data["attach"]["continue1to2"]["verdict"]
        path.write_text(json.dumps(data))
        report = probe.rescore_artifact(path, LOOP_P)
        assert report["arms"]["attach"]["identical"] is True
        assert report["arms"]["attach"]["strictMatchesArtifact"] is False
        assert report["ok"] is False

    def test_an_arm_without_samples_fails_closed(self, tmp_path: Path) -> None:
        path = self._artifact(tmp_path, rows_around_boundary())
        data = json.loads(path.read_text())
        del data["attach"]["samples"]
        path.write_text(json.dumps(data))
        assert probe.rescore_artifact(path, LOOP_P)["ok"] is False

    @pytest.mark.parametrize(("strict", "generated"), [(True, True), (False, True), (True, False)])
    def test_cli_exits_nonzero_unless_ok(
        self, strict: bool, generated: bool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """S1: the strict/wrap-aware CvC and the plan-generated rescore (G-S1a) must both hold."""
        ok = strict and generated
        monkeypatch.setattr(probe, "prepare_export", lambda *a: tmp_path)
        monkeypatch.setattr(probe, "load_slides", lambda *a: [])
        monkeypatch.setattr(probe, "ground_truth_plan", lambda *a, **k: None)
        monkeypatch.setattr(probe, "ground_truth_facts", lambda *a, **k: {"asset": ASSET})
        monkeypatch.setattr(probe, "movie_nodes", lambda *a: [])
        monkeypatch.setattr(probe, "loop_period_of", lambda *a: LOOP_P)
        monkeypatch.setattr(probe, "rescore_artifact", lambda *a: {"ok": strict})
        monkeypatch.setattr(probe, "rescore_generated", lambda *a: {"ok": generated})
        (tmp_path / "host.json").write_text(json.dumps({"kind": "live-continuity-probe"}))
        args = probe.parse_args(["--rescore", str(tmp_path / "host.json")])
        if ok:
            probe.run_rescore_cli(args)
        else:
            with pytest.raises(SystemExit) as exc:
                probe.run_rescore_cli(args)
            assert exc.value.code == 1


class _WrapTransport:
    """Answers the force-wrap harness's evaluations from a scripted page: the seek lands, the
    last settled frame puts the wrap 375 ms after a press at FW_SEEKED + 2000."""

    def __init__(self) -> None:
        self.evaluations: list[str] = []

    def evaluate(self, expression: str) -> Any:
        self.evaluations.append(expression)
        if expression.startswith(probe.FORCE_WRAP_SEEK_JS):
            return {"count": 1, "duration": FW_PERIOD, "loop": True, "playbackRate": 1}
        if expression == probe.FORCE_WRAP_STATUS_JS:
            return {
                "seekedT": FW_SEEKED, "framesAfterSeek": 12, "duration": FW_PERIOD, "playbackRate": 1,
                "last": {"now": FW_SEEKED + 2000.0, "mediaTime": FW_PERIOD - 0.375},
            }
        if expression == probe.PAGE_NOW_JS:
            return FW_SEEKED + 2000.0
        if expression == probe.FORCE_WRAP_READ_JS:
            return _fw_recorder()
        if expression == "window.__obedContinuityProbe__.samples":
            return []
        if expression == probe.PAGE_ERRORS_JS:
            return [{"kind": "player-build-error", "t": FW_SEEKED - 500.0, "detail": {"message": "before the seek"}}]
        return True


class _WrapHost:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.transport = _WrapTransport()
        self.commands: list[str] = []
        self.output = {"continuity": {"mode": "qualified"}}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def _require_transport(self) -> _WrapTransport:
        return self.transport

    def execute(self, command: str) -> None:
        self.commands.append(command)

    def observe(self) -> Any:
        return argparse.Namespace(original_slide=4, busy=False)


class TestRunForceWrap:
    def test_one_take_seeks_the_source_presses_once_and_scores(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        hosts: list[_WrapHost] = []

        def host(*args: Any, **kwargs: Any) -> _WrapHost:
            hosts.append(_WrapHost())
            return hosts[-1]

        facts = {
            "asset": ASSET, "onset1to2": 2, "bridgeScene": 8, "pinRect": dict(SRC_RECT),
            "bridgeSrcRect": dict(SRC_RECT), "destRect": dict(DST_RECT),
        }
        scored: dict[str, Any] = {}

        def continuity(*args: Any, **kwargs: Any) -> dict[str, Any]:
            scored.update(kwargs)
            return {"verdict": True, "wraps": 1, "elementId": 1}

        node = {"playerIndex": 2, "objectId": "98D59E27-X", "asset": ASSET, "startTime": 0, "endTime": FW_PERIOD, "rect": dict(SRC_RECT)}
        monkeypatch.setattr(probe, "LiveOutputHost", host)
        monkeypatch.setattr(probe, "prepare_export", lambda *a: tmp_path)
        monkeypatch.setattr(probe, "load_slides", lambda *a: [])
        monkeypatch.setattr(probe, "ground_truth_plan", lambda *a, **k: synthetic_plan())
        monkeypatch.setattr(probe, "ground_truth_facts", lambda *a, **k: facts)
        monkeypatch.setattr(probe, "movie_nodes", lambda *a: [node])
        monkeypatch.setattr(probe, "force_viewport", lambda *a: None)
        monkeypatch.setattr(probe, "wait_for_decode", lambda *a: True)
        monkeypatch.setattr(probe, "advance_until_original_slide", lambda player, ordinal: player.commands.append(f"to{ordinal}"))
        monkeypatch.setattr(probe, "wait_until_settled", lambda *a, **k: True)
        monkeypatch.setattr(probe, "wait_for_destination_hash", lambda *a, **k: True)
        monkeypatch.setattr(probe, "armed_evidence", lambda *a, **k: [])
        monkeypatch.setattr(probe, "score_continuity", continuity)
        monkeypatch.setattr(probe, "check_no_leftover_chrome", lambda: "")
        monkeypatch.setattr(probe, "CLICK_DELAY_S", 0.0)
        monkeypatch.setattr(probe, "POST_ADVANCE_SETTLE_S", 0.0)
        monkeypatch.setattr(probe, "forced_window", lambda *a: _fw_window())

        args = probe.parse_args(["--force-wrap", "3to4:375", "--fixture", str(tmp_path)])
        result = probe.run_force_wrap(args)

        assert hosts[0].commands == ["to2", "to3", "advance"]
        seek = next(e for e in hosts[0].transport.evaluations if e.startswith(probe.FORCE_WRAP_SEEK_JS))
        assert seek.endswith('("98D59E27-X-video", 2.375)')
        assert result["take"]["pressT"] == FW_SEEKED + 2000.0 and result["take"]["reached"] is True
        assert result["take"]["plannedWrapT"] == pytest.approx(FW_SEEKED + 2375.0)
        assert scored["loop_period_s"] == FW_PERIOD
        assert scored["min_window_start"] == FW_SEEKED + probe.FORCE_WRAP_WINDOW_AFTER_SEEK_MS
        assert scored["transition_scene"] == 7
        assert (result["status"], result["forced"]["outcome"]) == ("pass", "carried")
        assert len(result["pageErrorNotes"]) == 1 and result["forced"]["pageErrors"] == []


PAGE_ERROR = {"kind": "player-build-error", "t": FW_SEEKED + 2500.0, "detail": {"errorType": "error", "message": "boom"}}


class TestForcedWrapPageErrors:
    def test_known_bad_a_page_error_fails_a_carried_take(self) -> None:
        result = _fw_score(page_errors=[PAGE_ERROR])
        assert (result["status"], result["outcome"]) == ("fail", None)
        assert result["pageErrors"] == [PAGE_ERROR]

    def test_known_bad_a_page_error_fails_a_fallback_take(self) -> None:
        result = _fw_score(boundary="1to2", reads=_fw_reads(stand_downs=["videoNotReady"]), armed=ARMED, page_errors=[PAGE_ERROR])
        assert result["status"] == "fail"

    def test_control_no_page_error_leaves_the_outcome_unchanged(self) -> None:
        assert (_fw_score()["status"], _fw_score()["outcome"]) == ("pass", "carried")
        assert _fw_score()["pageErrors"] == []

    def test_unreadable_notes_are_invalid(self) -> None:
        assert _fw_score(page_errors=None)["status"] == "invalid"

    def test_only_notes_from_the_seek_to_the_window_end_count(self) -> None:
        window = _fw_window()
        notes = [dict(PAGE_ERROR, t=FW_SEEKED - 1.0), PAGE_ERROR, dict(PAGE_ERROR, t=window["end"] + 1.0), "junk"]
        assert probe.page_errors_in(notes, FW_SEEKED, window) == [PAGE_ERROR]
        assert probe.page_errors_in(None, FW_SEEKED, window) is None
        assert probe.page_errors_in(notes, None, window) is None


class TestWrapScorerSparseGap:
    def test_known_bad_a_sparse_mid_period_restart_is_not_a_wrap(self) -> None:
        rows = [{"t": 0.0, "currentTime": 30.0}, {"t": 20000.0, "currentTime": 10.0}]
        assert probe.unwrap_clock(rows, LOOP_P)[1] == []

    def test_known_bad_a_sparse_30_to_10_restart_fails_the_scorer(self) -> None:
        samples = _loop_fields(rows_around_boundary(start_time=29.7, n_after=20))
        after = [row for row in samples if row["scene"] == 2.0]
        for row in after:
            row["t"] += 20000.0
            for v in row["videos"]:
                v["t"] = row["t"]
                v["currentTime"] -= 20.0
        result = probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, True, loop_period_s=LOOP_P, pad_s=30.0)
        assert result["wraps"] == 0
        assert result["verdict"] is False and result["maxDropS"] > 19.0

    def test_a_step_at_the_stall_limit_still_wraps(self) -> None:
        step = probe.MAX_STALL_S * 1000.0
        rows = [{"t": 0.0, "currentTime": LOOP_P - 0.1}, {"t": step, "currentTime": 0.1}]
        assert probe.unwrap_clock(rows, LOOP_P)[1] == [step]


class TestForceWrapCliExit:
    @pytest.mark.parametrize("status,code", [("pass", None), ("fail", 1), ("invalid", 1), ("error", 1)])
    def test_exits_nonzero_unless_pass(self, status: str, code: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        def run(args: Any) -> dict[str, Any]:
            if status == "error":
                raise RuntimeError("boom")
            return {"status": status, "forced": {"status": status}}

        monkeypatch.setattr(probe, "run_force_wrap", run)
        args = probe.parse_args(["--force-wrap", "1to2:0", "--artifact", str(tmp_path / "fw.json")])
        if code is None:
            probe.run_force_wrap_cli(args)
        else:
            with pytest.raises(SystemExit) as exc:
                probe.run_force_wrap_cli(args)
            assert exc.value.code == code
        assert json.loads((tmp_path / "fw.json").read_text())["status"] == status


FORCED_WRAP_FIXTURES = REPO / "tests" / "fixtures" / "live_continuity" / "forced_wrap"


def _armed_reads_at(end: float) -> list[dict[str, Any]]:
    reads = _fw_reads()
    reads[0]["glReplay"]["t"] = end - 500.0
    reads[1]["glReplay"]["t"] = end
    return reads


class TestArmedRecorderWindow:
    """L2 BUG 1: with G2 armed the sampler never sees the detached carried element, so the
    recorder's window comes from the take: seekedT + 1 s to the last destination read."""

    def test_window_is_grounded_in_the_take(self) -> None:
        window = probe.armed_recorder_window(_fw_recorder(), _armed_reads_at(FW_SEEKED + 6000.0))
        assert window["start"] == FW_SEEKED + probe.FORCE_WRAP_WINDOW_AFTER_SEEK_MS
        assert window["end"] == FW_SEEKED + 6000.0
        assert window["rule"].startswith("armed")

    @pytest.mark.parametrize("case", ["no-reads", "no-seek", "read-before-start"])
    def test_missing_evidence_gives_no_window(self, case: str) -> None:
        recorder, reads = _fw_recorder(), _armed_reads_at(FW_SEEKED + 6000.0)
        if case == "no-reads":
            reads = None
        elif case == "no-seek":
            recorder["seekedT"] = None
        else:
            reads = _armed_reads_at(FW_SEEKED + 900.0)
        assert probe.armed_recorder_window(recorder, reads) is None
        assert probe.score_recorder_clock(recorder, None)["verdict"] is False

    def test_steady_recorder_holds(self) -> None:
        window = probe.armed_recorder_window(_fw_recorder(), _armed_reads_at(FW_SEEKED + 6000.0))
        assert probe.score_recorder_clock(_fw_recorder(), window)["verdict"] is True

    def test_known_bad_frozen_recorder_fails(self) -> None:
        recorder = _fw_recorder(stop_at=FW_SEEKED + 4000.0)
        window = probe.armed_recorder_window(recorder, _armed_reads_at(FW_SEEKED + 6000.0))
        assert probe.score_recorder_clock(recorder, window)["verdict"] is False

    def test_known_bad_mid_period_jump_fails(self) -> None:
        recorder = _fw_recorder()
        for frame in recorder["frames"]:
            if frame["now"] > FW_SEEKED + 4000.0:
                frame["mediaTime"] += 10.0
        window = probe.armed_recorder_window(recorder, _armed_reads_at(FW_SEEKED + 6000.0))
        result = probe.score_recorder_clock(recorder, window)
        assert result["verdict"] is False and result["wraps"] == 1 and result["maxJumpS"] > 9.0

    def test_a_one_frame_forward_step_is_tolerated(self) -> None:
        recorder = _fw_recorder()
        for frame in recorder["frames"]:
            if frame["now"] > FW_SEEKED + 4000.0:
                frame["mediaTime"] += 1.0 / 30.0
        window = probe.armed_recorder_window(recorder, _armed_reads_at(FW_SEEKED + 6000.0))
        assert probe.score_recorder_clock(recorder, window)["verdict"] is True

    def test_known_bad_no_frames_in_window_fails(self) -> None:
        recorder = _fw_recorder(stop_at=FW_SEEKED + 900.0)
        window = probe.armed_recorder_window(recorder, _armed_reads_at(FW_SEEKED + 6000.0))
        result = probe.score_recorder_clock(recorder, window)
        assert result["verdict"] is False and "no recorded frame" in result["reason"]

    def _gt(self) -> dict[str, Any]:
        return {
            "facts": {"asset": ASSET}, "factsOn": {"armed": ARMED}, "source": {"periodS": FW_PERIOD},
            "scene": 2, "srcRect": dict(BIG_INSTANCE), "dstRect": dict(BIG_INSTANCE), "transition": None,
        }

    def test_the_armed_take_is_scored_from_its_own_window(self) -> None:
        result = {
            "continuity": GL_CONTINUITY, "samples": [], "recorder": _fw_recorder(), "take": _fw_take(),
            "reads": _armed_reads_at(FW_SEEKED + 6000.0), "pageErrorNotes": [],
        }
        probe.score_force_wrap_run(result, self._gt(), "1to2", 375.0)
        assert result["continuityVerdict"]["verdict"] is not True
        assert result["recorderClock"]["window"]["rule"].startswith("armed")
        assert (result["status"], result["forced"]["outcome"]) == ("pass", "carried")

    def test_the_armed_take_with_a_frozen_recorder_fails(self) -> None:
        result = {
            "continuity": GL_CONTINUITY, "samples": [], "recorder": _fw_recorder(stop_at=FW_SEEKED + 4000.0),
            "take": _fw_take(), "reads": _armed_reads_at(FW_SEEKED + 6000.0), "pageErrorNotes": [],
        }
        probe.score_force_wrap_run(result, self._gt(), "1to2", 375.0)
        assert result["status"] == "fail"

    def test_real_1to2_0_recorder_holds_under_the_take_window(self) -> None:
        artifact = json.loads((FORCED_WRAP_FIXTURES / "1to2_0.min.json").read_text())
        window = probe.armed_recorder_window(artifact["recorder"], artifact["reads"])
        clock = probe.score_recorder_clock(artifact["recorder"], window)
        assert clock["verdict"] is True and clock["wraps"] == 1, clock
        held, carry = probe.armed_carry(artifact["reads"], _real_armed(), artifact["recorder"])
        assert held, carry


def _real_armed() -> dict[str, Any]:
    root = REPO / "tests" / "fixtures" / "live_continuity"
    plan = probe.derive_plan(root, probe.load_slides(root), resolver=lambda r, rel: r / rel, gl_replay=True)
    return probe.armed_fact(plan, plan.to_runtime(), {2: "continue1to2", 6: "restart2to3", 8: "continue3to4"})


def _excuse_samples() -> list[dict[str, Any]]:
    return wrap_samples(lead_s=0.5)


def _track(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row["videos"][0] | {"t": row["t"]} for row in samples]


def _wrap_index(samples: list[dict[str, Any]]) -> int:
    track = _track(samples)
    index = next(i for i in range(1, len(track)) if track[i]["currentTime"] < track[i - 1]["currentTime"])
    assert samples[index]["scene"] == 2.0, "the wrap must land on an owner-checked (after-cut) row"
    return index


def _unown(row: dict[str, Any], *, ready: int = 1, owner: Any = None) -> None:
    v = row["videos"][0]
    v["readyState"] = ready
    v["footprintOwner"] = owner if owner is not None else {"elId": None, "key": None, "via": "none", "contextType": None}


class TestWrapOwnerExcuse:
    """L2 BUG 2: `footprintOwnerDecoderId` fails closed on the not-ready decoder at the
    browser's loop seek; exactly that sample may go unowned, nothing else."""

    def _score(self, samples: list[dict[str, Any]], period: float | None = LOOP_P) -> dict[str, Any]:
        return probe.score_continuity(samples, ASSET, 2.0, SRC_RECT, DST_RECT, True, loop_period_s=period)

    def test_the_loop_seek_sample_is_excused_and_reported(self) -> None:
        samples = _excuse_samples()
        index = _wrap_index(samples)
        _unown(samples[index])
        result = self._score(samples)
        assert result["verdict"] is True, result
        assert result["ownerMismatches"] == []
        assert [e["t"] for e in result["wrapOwnerExcused"]] == [samples[index]["t"]]

    def test_a_clean_wrap_reports_an_empty_excuse_list(self) -> None:
        assert self._score(_excuse_samples())["wrapOwnerExcused"] == []

    def test_the_strict_scorer_never_excuses(self) -> None:
        samples = _excuse_samples()
        _unown(samples[_wrap_index(samples)])
        result = self._score(samples, period=None)
        assert result["verdict"] is False and "wrapOwnerExcused" not in result

    def test_known_bad_via_none_away_from_a_wrap_fails(self) -> None:
        samples = _excuse_samples()
        _unown(samples[_wrap_index(samples) + 3])
        result = self._score(samples)
        assert result["verdict"] is False and len(result["ownerMismatches"]) == 1

    def test_known_bad_wrap_row_owned_by_another_element_fails(self) -> None:
        samples = _excuse_samples()
        _unown(samples[_wrap_index(samples)], owner={"elId": 999, "key": "movie1", "via": "footprint-video"})
        result = self._score(samples)
        assert result["verdict"] is False and result["wrapOwnerExcused"] == []

    def test_known_bad_ready_wrap_row_unowned_fails(self) -> None:
        samples = _excuse_samples()
        _unown(samples[_wrap_index(samples)], ready=4)
        assert self._score(samples)["verdict"] is False

    def test_known_bad_two_consecutive_unowned_rows_at_a_wrap_fail(self) -> None:
        samples = _excuse_samples()
        index = _wrap_index(samples)
        _unown(samples[index])
        _unown(samples[index + 1])
        result = self._score(samples)
        assert result["verdict"] is False
        assert len(result["ownerMismatches"]) == 2

    def test_known_bad_unowned_row_before_the_wrap_row_fails(self) -> None:
        samples = _excuse_samples()
        index = _wrap_index(samples)
        _unown(samples[index])
        _unown(samples[index - 1], ready=4)
        assert self._score(samples)["verdict"] is False

    def test_real_3to4_750_passes_with_its_one_loop_seek_excused(self) -> None:
        artifact = json.loads((FORCED_WRAP_FIXTURES / "3to4_750.min.json").read_text())
        root = REPO / "tests" / "fixtures" / "live_continuity"
        plan = probe.derive_plan(root, probe.load_slides(root), resolver=lambda r, rel: r / rel)
        facts = probe.ground_truth_facts(plan)
        kwargs = dict(transition_scene=facts["bridgeScene"] - 1, loop_period_s=artifact["recorder"]["duration"],
                      min_window_start=artifact["recorder"]["seekedT"] + probe.FORCE_WRAP_WINDOW_AFTER_SEEK_MS)
        args = (artifact["samples"], facts["asset"], facts["bridgeScene"], facts["bridgeSrcRect"], facts["destRect"], True)
        result = probe.score_continuity(*args, **kwargs)
        assert result["verdict"] is True, result
        assert [round(e["t"], 1) for e in result["wrapOwnerExcused"]] == [15745.8]
        assert probe.score_continuity(*args, **{**kwargs, "loop_period_s": None})["verdict"] is False


class TestRescoreForceWrapCli:
    @pytest.mark.parametrize("status,code", [("pass", None), ("fail", 1), ("invalid", 1)])
    def test_a_force_wrap_artifact_is_rescored_and_exits_nonzero_unless_pass(
        self, status: str, code: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        path = tmp_path / "fw.json"
        path.write_text(json.dumps({"kind": "live-continuity-probe-force-wrap"}))
        monkeypatch.setattr(probe, "rescore_force_wrap", lambda p: {"status": status})
        monkeypatch.setattr(probe, "rescore_artifact", lambda *a: pytest.fail("host re-score must not run"))
        args = probe.parse_args(["--rescore", str(path)])
        if code is None:
            probe.run_rescore_cli(args)
        else:
            with pytest.raises(SystemExit) as exc:
                probe.run_rescore_cli(args)
            assert exc.value.code == code

    def test_rescore_force_wrap_rescores_the_saved_take_in_place(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        saved = {
            "kind": "live-continuity-probe-force-wrap", "status": "fail", "fixture": "f", "originalIndex": "i",
            "forceWrap": {"boundary": "1to2", "offsetMs": 375}, "glReplay": {"requested": "auto"},
            "continuity": GL_CONTINUITY, "samples": [], "recorder": _fw_recorder(), "take": _fw_take(),
            "reads": _armed_reads_at(FW_SEEKED + 6000.0), "pageErrorNotes": [],
        }
        path = tmp_path / "fw.json"
        path.write_text(json.dumps(saved))
        seen: list[Any] = []

        def gt(*args: Any) -> dict[str, Any]:
            seen.append(args)
            return TestArmedRecorderWindow()._gt()

        monkeypatch.setattr(probe, "force_wrap_ground_truth", gt)
        report = probe.rescore_force_wrap(path)
        assert seen == [(Path("f"), Path("i"), "1to2", "auto")]
        assert (report["statusBefore"], report["status"], report["outcome"]) == ("fail", "pass", "carried")
        assert report["recorderWindow"]["rule"].startswith("armed")


class TestArmedCarryPainting:
    """Codex r2 F1: a fresh raw-player `<video>` painting the armed slot is not a carry, even
    while the recorder and G2 stay LIVE; and a raw restart on the armed boundary counts only
    once G2 is no longer active."""

    def _fresh_painting(self, reads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for read in reads:
            read["painting"] = [{"src": "untitled.mov", "elId": None, "rect": dict(BIG_INSTANCE)}]
        return reads

    def test_known_bad_fresh_video_over_the_armed_rect_is_not_carried(self) -> None:
        result = _fw_score(boundary="1to2", reads=self._fresh_painting(_fw_reads()), armed=ARMED)
        assert result["status"] == "fail"
        checks = result["carry"]["checks"]
        assert checks["noPainting"] is False
        assert all(value for key, value in checks.items() if key != "noPainting")

    def test_known_bad_armed_raw_restart_while_g2_is_live_is_not_a_fallback(self) -> None:
        result = _fw_score(
            boundary="1to2", reads=self._fresh_painting(_fw_reads()), armed=ARMED,
            recorder=_fw_recorder(), restart={"verdict": True},
        )
        assert result["status"] == "fail"
        assert result["fallback"]["g2Inactive"] is False

    def test_armed_raw_restart_after_g2_retired_is_a_fallback(self) -> None:
        reads = self._fresh_painting(_fw_reads(zones=[("armed", "retired", "failure")]))
        for read in reads:
            read["glReplay"]["api"]["state"] = "RETIRED"
        result = _fw_score(boundary="1to2", reads=reads, armed=ARMED, restart={"verdict": True})
        assert (result["status"], result["outcome"]) == ("pass", "rawRestart")

    def test_armed_raw_restart_with_the_zone_still_armed_is_not_a_fallback(self) -> None:
        reads = self._fresh_painting(_fw_reads())
        for read in reads:
            read["glReplay"]["api"]["state"] = "RETIRED"
        result = _fw_score(boundary="1to2", reads=reads, armed=ARMED, restart={"verdict": True})
        assert result["status"] == "fail"


class TestWrapOwnerExcuseFailsClosed:
    """Codex r2 F2: the excuse needs a finite readyState < 2, a non-null elId, and both
    neighbours carrying that same elId."""

    _score = TestWrapOwnerExcuse._score

    @pytest.mark.parametrize("ready", ["missing", None, float("nan"), "1"])
    def test_known_bad_unreadable_ready_state_is_not_excused(self, ready: Any) -> None:
        samples = _excuse_samples()
        row = samples[_wrap_index(samples)]
        _unown(row)
        if ready == "missing":
            del row["videos"][0]["readyState"]
        else:
            row["videos"][0]["readyState"] = ready
        result = self._score(samples)
        assert result["verdict"] is False and result["wrapOwnerExcused"] == []

    def test_known_bad_null_el_id_is_not_excused(self) -> None:
        samples = _excuse_samples()
        row = samples[_wrap_index(samples)]
        _unown(row)
        row["videos"][0]["elId"] = None
        assert self._score(samples)["wrapOwnerExcused"] == []

    @pytest.mark.parametrize("side", [-1, 1])
    def test_known_bad_a_retagged_neighbour_is_not_excused(self, side: int) -> None:
        samples = _excuse_samples()
        index = _wrap_index(samples)
        _unown(samples[index])
        neighbour = samples[index + side]["videos"][0]
        neighbour["elId"] = 5
        neighbour["footprintOwner"] = {"elId": 5, "key": "movie1", "via": "footprint-video", "contextType": None}
        result = self._score(samples)
        assert result["verdict"] is False and result["wrapOwnerExcused"] == []


# --------------------------------------------------------------------------
# S1 (plan `keynote_live_continuity_generalisation.plan.md` §3 S1 WS-G, §4; Codex r1 #3-#8,
# #10, #11): verdicts GENERATED from `ContinuityPlan.boundaries[].movies[]`, one per
# (boundary, movie instance, kind), P2's legacy names kept as aliases; False only for a fully
# observed contrary behaviour, INCONCLUSIVE for every integrity gap; the red arms (`--strip`,
# `--core-variant`) with pre-registered red multisets; and the G-S1a rescore control.
# --------------------------------------------------------------------------

S1_BASE_REV = "90911466"
P2_ROOT = REPO / "tests" / "fixtures" / "live_continuity"
P2_ID = "untitled.mov#1->untitled.mov#1"
P2_CARRY12, P2_RETIRE12, P2_ARMED12 = (f"b0to1:{P2_ID}:{kind}" for kind in ("carry", "retire", "armed"))
P2_RESTART23, P2_CARRY34 = f"b1to2:{P2_ID}:restart", f"b2to3:{P2_ID}:carry"


def _load_probe_at(rev: str) -> Any:
    try:
        text = subprocess.run(
            ["git", "show", f"{rev}:scripts/live_continuity_probe.py"], cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    spec = importlib.util.spec_from_loader(f"probe_at_{rev}", loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(REPO / "scripts" / "live_continuity_probe.py")
    exec(compile(text, f"{rev}:live_continuity_probe.py", "exec"), module.__dict__)
    return module


S1_BASE = _load_probe_at(S1_BASE_REV)
needs_base = pytest.mark.skipif(S1_BASE is None, reason=f"git history for {S1_BASE_REV} is unavailable")
_RECT = probe.live_continuity_module.Rect
_MOVIE = probe.live_continuity_module.MovieContinuity
_BOUNDARY = probe.live_continuity_module.SlideBoundary


def _p2_plan(gl: bool = False) -> Any:
    return probe.derive_plan(P2_ROOT, probe.load_slides(P2_ROOT), resolver=lambda r, rel: r / rel, gl_replay=gl)


def _p2_facts(gl: bool = False) -> dict[str, Any]:
    return probe.ground_truth_facts(_p2_plan(gl), armed=gl)


def _spec(facts: dict[str, Any], spec_id: str) -> dict[str, Any]:
    return next(spec for spec in facts["verdicts"] if spec["id"] == spec_id)


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _real_samples() -> list[dict[str, Any]]:
    return json.loads((FORCED_WRAP_FIXTURES / "3to4_750.min.json").read_text())["samples"]


def _plan(boundaries: tuple[Any, ...], scenes: dict[int, int], instances: dict[int, Any]) -> Any:
    return probe.ContinuityPlan(
        canvas={"width": 1920, "height": 1080}, scene_index_by_player=scenes, slide_rects={},
        boundaries=boundaries, slide_instances=instances,
    )


def _p2_run_samples() -> list[dict[str, Any]]:
    """A whole P2 run on the real rects, 50 ms apart: decoder 1 on the pin (scenes 1, 2, 5; long
    enough that the 1->2 window never reaches slide 3),
    a fresh decoder 2 from 0 s on slide 3 (scene 6), moving on scene 7 and landed on 8."""
    facts = _p2_facts()
    pin, src, dst = facts["pinRect"], facts["bridgeSrcRect"], facts["destRect"]
    rows: list[dict[str, Any]] = []
    phases = (
        [(1, 1, pin, "IdleAtFinalState", False)] * 20 + [(2, 1, pin, "IdleAtFinalState", False)] * 20
        + [(5, 1, pin, "IdleAtFinalState", False)] * 60 + [(6, 2, src, "IdleAtFinalState", False)] * 40
        + [(7, 2, None, "Playing", True)] * 31 + [(7, 2, dst, "IdleAtFinalState", False)] * 5
        + [(8, 2, dst, "IdleAtInitialState", False)] * 20
    )
    moving = 0
    fresh_start = None
    for index, (scene, vid, rect, state, busy) in enumerate(phases):
        t = index * 50.0
        if rect is None:
            rect = {key: src[key] + (moving / 30) * (dst[key] - src[key]) for key in src}
            moving += 1
        if vid == 2 and fresh_start is None:
            fresh_start = t
        current = 5 + t / 1000 if vid == 1 else (t - fresh_start) / 1000
        row = sample(t, scene, video(id=vid, el_id=vid, t=t, scene=scene, current_time=current, rect=dict(rect)))
        row.update(playerState=state, busy=busy)
        rows.append(row)
    return rows


class TestVerdictSpecsFromThePlan:
    def test_p2_off_generates_one_verdict_per_boundary_instance_and_kind(self) -> None:
        facts = _p2_facts()
        assert [(s["id"], s["alias"], s["expect"], s["atScene"]) for s in facts["verdicts"]] == [
            (P2_CARRY12, "continue1to2", False, 2), (P2_RETIRE12, "refused1to2", True, 2),
            (P2_RESTART23, "restart2to3", True, 6), (P2_CARRY34, "continue3to4", True, 8),
        ]
        assert _spec(facts, P2_CARRY34)["transitionScene"] == 7 and _spec(facts, P2_CARRY34)["action"] == "bridge"
        assert _spec(facts, P2_CARRY12)["transitionScene"] is None
        assert _spec(facts, P2_RESTART23)["settleUntilScene"] == 7
        assert _spec(facts, P2_RETIRE12)["movieKey"] == "movie1" and _spec(facts, P2_RETIRE12)["originalOrdinal"] == 2

    def test_p2_on_arms_the_refused_pin_and_leaves_its_carry_ungated(self) -> None:
        facts = _p2_facts(gl=True)
        assert [(s["id"], s["alias"], s["expect"]) for s in facts["verdicts"]] == [
            (P2_CARRY12, "continue1to2", None), (P2_ARMED12, "armed1to2", True),
            (P2_RESTART23, "restart2to3", True), (P2_CARRY34, "continue3to4", True),
        ]
        assert facts["armed"]["verdictKey"] == "armed1to2" and facts["retire"] is None

    def test_two_instances_of_one_asset_across_one_boundary_are_two_verdicts(self) -> None:
        """Codex r1 #5: (boundary, asset, kind) collided; the instance pair does not."""
        near, far = dict(BIG_INSTANCE), dict(OTHER_INSTANCE)
        plan = _plan(
            (_BOUNDARY(0, 1, (_MOVIE("a.mov", "pin", _RECT(**near), _RECT(**near)), _MOVIE("a.mov", "pin", _RECT(**far), _RECT(**far)))),),
            {0: 0, 1: 2}, {0: {"a.mov": [near, far]}, 1: {"a.mov": [near, far]}},
        )
        assert [(s["id"], s["alias"]) for s in probe.verdict_specs(plan)] == [
            ("b0to1:a.mov#1->a.mov#1:carry", None), ("b0to1:a.mov#2->a.mov#2:carry", None),
        ]

    def test_the_same_movie_twice_fails_closed(self) -> None:
        pin = _MOVIE("a.mov", "pin", _RECT(**BIG_INSTANCE), _RECT(**BIG_INSTANCE))
        plan = _plan((_BOUNDARY(0, 1, (pin, pin)),), {0: 0, 1: 2}, {0: {"a.mov": [BIG_INSTANCE]}, 1: {"a.mov": [BIG_INSTANCE]}})
        with pytest.raises(SystemExit, match="not unique"):
            probe.verdict_specs(plan)

    @pytest.mark.parametrize("instances", [{}, {0: {"a.mov": [OTHER_INSTANCE]}, 1: {"a.mov": [BIG_INSTANCE]}}])
    def test_a_movie_bound_to_no_authored_instance_fails_closed(self, instances: dict[int, Any]) -> None:
        pin = _MOVIE("a.mov", "pin", _RECT(**BIG_INSTANCE), _RECT(**BIG_INSTANCE))
        with pytest.raises(SystemExit, match="authored instances"):
            probe.verdict_specs(_plan((_BOUNDARY(0, 1, (pin,)),), {0: 0, 1: 2}, instances))

    def test_an_unhandled_action_is_kept_and_always_inconclusive(self) -> None:
        odd = _MOVIE("a.mov", "morph", _RECT(**BIG_INSTANCE), _RECT(**BIG_INSTANCE))
        plan = _plan((_BOUNDARY(0, 1, (odd,)),), {0: 0, 1: 2}, {0: {"a.mov": [BIG_INSTANCE]}, 1: {"a.mov": [BIG_INSTANCE]}})
        specs = probe.verdict_specs(plan)
        assert [(s["kind"], s["expect"], s["alias"]) for s in specs] == [("unhandled", True, None)]
        scored = probe.score_verdicts([], {}, {"verdicts": specs}, True, None)
        assert scored[specs[0]["id"]]["verdict"] is None
        assert probe.unmet_verdicts(scored, specs) == ([], [specs[0]["id"]])

    def test_the_trailing_boundary_has_no_verdict(self) -> None:
        assert all(spec["toPlayer"] is not None for spec in probe.verdict_specs(_p2_plan()))

    @pytest.mark.parametrize(("key", "prefix", "expected"), [
        ("continue1to2", "refused", "refused1to2"), ("restart2to3", "refused", "refused2to3"),
        ("continue1to2", "armed", "armed1to2"), ("continue5to6", "refused", "refused5to6"),
        (f"b0to1:{P2_ID}:carry", "refused", f"b0to1:{P2_ID}:retire"), (f"b0to1:{P2_ID}:carry", "armed", f"b0to1:{P2_ID}:armed"),
    ])
    def test_positive_keys_follow_the_carry_key(self, key: str, prefix: str, expected: str) -> None:
        assert probe.positive_key(key, prefix) == expected


class TestGroundTruthFactsIsGeneral:
    @needs_base
    @pytest.mark.parametrize("gl", [False, True])
    def test_p2_facts_equal_the_s1_base_facts_plus_the_verdicts_and_sha(self, gl: bool) -> None:
        plan = _p2_plan(gl)
        base = _plain(S1_BASE.ground_truth_facts(plan, armed=gl))
        current = _plain(probe.ground_truth_facts(plan, armed=gl))
        assert current.pop("verdicts")[0]["id"] == P2_CARRY12
        assert current.pop("planSha256") in probe.P2_PLAN_SHA256
        assert current == base

    def test_legacy_slot_facts_only_for_a_pinned_p2_plan(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Codex r1 #4: a pin + bridge + >= 4 slides is not P2 unless its runtime plan IS P2's."""
        movies = {"movie1": dict(RUNTIME_MOVIES["movie1"], footprint={"x": 110, "y": 795, "w": 952, "h": 268})}
        monkeypatch.setattr(probe, "runtime_of", lambda plan: dict(RETIRED_RUNTIME, movies=movies))
        facts = probe.ground_truth_facts(_gl_plan())
        assert "bridgeScene" not in facts and facts["planSha256"] not in probe.P2_PLAN_SHA256
        monkeypatch.undo()
        assert "bridgeScene" in _p2_facts()

    def test_the_pinned_shas_are_the_committed_fixtures_off_and_on(self) -> None:
        assert {_p2_facts()["planSha256"], _p2_facts(gl=True)["planSha256"]} <= probe.P2_PLAN_SHA256
        assert probe.plan_signature(_p2_plan().to_runtime()) == probe.P2_OFF_PLAN_SHA256

    def test_a_deck_without_p2_shape_derives_facts_and_keeps_the_armed_contract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pin = _MOVIE(BIG_ASSET, "pin", _RECT(**BIG_INSTANCE), _RECT(**BIG_INSTANCE), refusal="overlap", gl_replay={"x": 1})
        plan = _plan((_BOUNDARY(0, 1, (pin,)),), {0: 0, 1: 2}, {0: {BIG_ASSET: [BIG_INSTANCE]}, 1: {BIG_ASSET: [BIG_INSTANCE]}})
        monkeypatch.setattr(probe, "runtime_of", lambda plan: {"movies": RUNTIME_MOVIES, "boundaries": [GL_BOUNDARY]})
        facts = probe.ground_truth_facts(plan, armed=True)
        assert "bridgeScene" not in facts and "asset" not in facts
        assert facts["armed"]["instanceRect"] == BIG_INSTANCE and facts["armed"]["verdictKey"] == "armed1to2"
        assert [s["kind"] for s in facts["verdicts"]] == ["carry", "armed"]

    def test_a_runtime_retire_the_plan_does_not_refuse_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pin = _MOVIE(BIG_ASSET, "pin", _RECT(**BIG_INSTANCE), _RECT(**BIG_INSTANCE))
        plan = _plan((_BOUNDARY(0, 1, (pin,)),), {0: 0, 1: 2}, {0: {BIG_ASSET: [BIG_INSTANCE]}, 1: {BIG_ASSET: [BIG_INSTANCE]}})
        monkeypatch.setattr(probe, "runtime_of", lambda plan: {"movies": RUNTIME_MOVIES, "boundaries": [RETIRE_BOUNDARY]})
        with pytest.raises(SystemExit, match="matches 0 plan verdicts"):
            probe.ground_truth_facts(plan)

    def test_retire_and_armed_facts_key_off_generated_ids_without_an_alias(self) -> None:
        keys = {2: f"b0to1:{P2_ID}:carry"}
        assert probe.retire_fact(synthetic_plan(), RETIRED_RUNTIME, keys)["verdictKey"] == P2_RETIRE12
        assert probe.armed_fact(synthetic_plan(), GL_RUNTIME, keys)["verdictKey"] == P2_ARMED12
        with pytest.raises(SystemExit):
            probe.armed_fact(synthetic_plan(), GL_RUNTIME, {2: f"b0to1:{P2_ID}:restart"})


class TestCarryVerdict:
    """Codex r1 #3: the alias is the legacy carry verdict whenever it was fully observed; an
    integrity gap is INCONCLUSIVE, never the red a red arm expects."""

    @needs_base
    @pytest.mark.parametrize("installed", [True, False])
    def test_a_fully_observed_run_equals_the_s1_base_scorer(self, installed: bool) -> None:
        facts, samples = _p2_facts(), _p2_run_samples()
        legacy = S1_BASE.score_boundaries(samples, facts, installed)
        scored = probe.with_aliases(probe.score_verdicts(samples, {}, facts, installed, {"mode": "qualified"}), facts["verdicts"])
        assert {key: value["verdict"] for key, value in legacy.items()} == {
            "continue1to2": True, "restart2to3": True, "continue3to4": True,
        }
        for key in ("continue1to2", "continue3to4"):
            assert _plain(scored[key]) == _plain(legacy[key])
        assert scored["restart2to3"]["verdict"] is True

    @needs_base
    def test_the_committed_real_samples_carry_the_bridge_exactly_as_before(self) -> None:
        facts = _p2_facts()
        legacy = S1_BASE.score_continuity(
            _real_samples(), "untitled.mov", 8, facts["bridgeSrcRect"], facts["destRect"], True, transition_scene=7,
            loop_period_s=FW_PERIOD,
        )
        scored = probe.score_verdicts(_real_samples(), {}, facts, True, {"mode": "qualified"}, loop_period_s=FW_PERIOD)
        assert scored[P2_CARRY34]["verdict"] is True and _plain(scored[P2_CARRY34]) == _plain(legacy)

    def test_a_missing_crossing_is_inconclusive_not_red(self) -> None:
        """The Codex scenario: sampling stops before slide 4."""
        facts = _p2_facts()
        samples = [row for row in _p2_run_samples() if row["scene"] < 8]
        scored = probe.score_verdicts(samples, {}, facts, True, {"mode": "qualified"})
        assert scored[P2_CARRY34]["verdict"] is None
        assert probe.score_continuity(samples, "untitled.mov", 8, facts["bridgeSrcRect"], facts["destRect"], True, transition_scene=7)["verdict"] is False

    def test_a_fully_observed_restart_across_a_carry_is_red(self) -> None:
        facts = _p2_facts()
        samples = _p2_run_samples()
        for row in samples:
            if row["scene"] == 8:
                row["videos"][0]["id"] = 9
        assert probe.score_verdicts(samples, {}, facts, True, {"mode": "qualified"})[P2_CARRY34]["verdict"] is False

    def test_a_sampler_gap_over_the_move_is_inconclusive(self) -> None:
        facts = _p2_facts()
        samples = [row for row in _p2_run_samples() if row.get("playerState") != "Playing"]
        scored = probe.score_verdicts(samples, {}, facts, True, {"mode": "qualified"})[P2_CARRY34]
        assert scored["verdict"] is None and "moving-transition" in scored["integrity"]

    def test_an_untrustworthy_stage_map_is_inconclusive(self) -> None:
        facts = _p2_facts()
        samples = _p2_run_samples()
        for row in samples:
            if row["scene"] == 8:
                row["videos"][0]["stageMapValid"] = False
        assert probe.score_verdicts(samples, {}, facts, True, {"mode": "qualified"})[P2_CARRY34]["verdict"] is None

    @pytest.mark.parametrize("breakage", ["notList", "t", "scene", "videos", "id", "src", "currentTime", "rect", "isConnected"])
    def test_a_malformed_sample_is_inconclusive_before_any_tracking(self, breakage: str) -> None:
        facts = _p2_facts()
        samples: Any = _p2_run_samples()
        row, vid = samples[70], samples[70]["videos"][0]
        if breakage == "notList":
            samples = {"samples": samples}
        elif breakage in ("t", "scene"):
            row[breakage] = "x"
        elif breakage == "videos":
            row["videos"] = None
        elif breakage == "currentTime":
            vid["currentTime"] = float("nan")
        elif breakage == "rect":
            vid["rect"] = {"x": 1}
        elif breakage == "id":
            vid["id"] = True
        else:
            del vid[breakage]
        scored = probe.score_verdicts(samples, {}, facts, True, {"mode": "qualified"})
        for spec_id in (P2_CARRY12, P2_RESTART23, P2_CARRY34):
            assert scored[spec_id]["verdict"] is None and scored[spec_id]["schemaErrors"], spec_id

    def test_the_real_samples_have_a_valid_schema(self) -> None:
        assert probe.sample_schema_errors(_real_samples()) == []


class TestRestartVerdict:
    """Codex r1 #7: a fresh decoder near 0 s AT the destination instance, and every source
    decoder gone after the boundary."""

    def _score(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        facts = _p2_facts()
        return probe.score_restart_strict(samples, _spec(facts, P2_RESTART23))

    def test_a_clean_restart_is_green(self) -> None:
        scored = self._score(_p2_run_samples())
        assert scored["verdict"] is True and scored["elementId"] == 2 and scored["sourceIds"] == [1]

    def test_known_bad_the_source_decoder_leaks_across_the_cut(self) -> None:
        samples = _p2_run_samples()
        pin = _p2_facts()["pinRect"]
        for row in samples:
            if row["scene"] == 6:
                row["videos"].append(video(id=1, el_id=1, t=row["t"], scene=6, current_time=9.0, rect=dict(pin)))
        scored = self._score(samples)
        assert scored["verdict"] is False and scored["leaked"] and "still connected" in scored["reason"]

    def test_a_disconnected_source_row_is_not_a_leak(self) -> None:
        samples = _p2_run_samples()
        pin = _p2_facts()["pinRect"]
        for row in samples:
            if row["scene"] == 6:
                row["videos"].append(video(id=1, el_id=1, t=row["t"], scene=6, current_time=9.0, rect=dict(pin), is_connected=False))
        assert self._score(samples)["verdict"] is True

    def test_known_bad_the_fresh_decoder_is_not_at_the_destination_instance(self) -> None:
        samples = _p2_run_samples()
        for row in samples:
            if row["scene"] == 6:
                row["videos"][0]["rect"]["x"] += 40
        scored = self._score(samples)
        assert scored["verdict"] is False and scored["reason"] == "no fresh decoder at the destination instance"

    def test_known_bad_the_fresh_decoder_starts_late(self) -> None:
        samples = _p2_run_samples()
        for row in samples:
            if row["videos"][0]["id"] == 2:
                row["videos"][0]["currentTime"] += 3.0
        scored = self._score(samples)
        assert scored["verdict"] is False and "starts at" in scored["reason"]

    def test_a_missing_crossing_or_destination_is_inconclusive(self) -> None:
        assert self._score([r for r in _p2_run_samples() if r["scene"] < 6])["verdict"] is None
        assert self._score([r for r in _p2_run_samples() if r["scene"] != 6])["verdict"] is None

    def test_no_source_before_the_boundary_is_inconclusive(self) -> None:
        samples = _p2_run_samples()
        for row in samples:
            if row["scene"] < 6:
                row["videos"][0]["rect"]["y"] -= 300
        assert self._score(samples)["verdict"] is None


def _retire_read(events: Any = (), *, painting: Any = (), pool: Any = ()) -> dict[str, Any]:
    return {
        "stageMap": dict(IDENTITY_STAGE_MAP), "painting": list(painting), "poolSnapshot": list(pool) if isinstance(pool, tuple) else pool,
        "coreEvents": list(events) if isinstance(events, tuple) else events,
    }


RETIRE_NOTE = _ev("retire-boundary", key="movie1", elIds=[3], atScene=2, sceneHash="#2")


class TestRetireVerdict:
    """Codex r1 #8: the F5 `retire-boundary` note, no carry note in the zone, and the settled checks."""

    def _score(self, read: Any, installed: bool = True) -> dict[str, Any]:
        return probe.score_retire(read, _spec(_p2_facts(), P2_RETIRE12), installed)

    def test_one_note_and_nothing_carried_is_green(self) -> None:
        scored = self._score(_retire_read((RETIRE_NOTE, _ev("preserve-refused", key="movie1", scene=1, via="stash"))))
        assert scored["verdict"] is True and scored["retireNotes"] == [RETIRE_NOTE["detail"]]

    @pytest.mark.parametrize("notes", [(), (RETIRE_NOTE, RETIRE_NOTE), (_ev("retire-boundary", key="movie1", elIds=[3], atScene=6),),
                                       (_ev("retire-boundary", key="movie2", elIds=[3], atScene=2),), (_ev("retire-boundary", key="movie1", atScene=2),)])
    def test_known_bad_anything_but_exactly_one_matching_note_is_red(self, notes: tuple[Any, ...]) -> None:
        scored = self._score(_retire_read(notes))
        assert scored["verdict"] is False and "retire-boundary note(s)" in scored["reason"]

    @pytest.mark.parametrize("carry", [
        _ev("remount-done", elId=5, key="untitled.mov", sceneHash="#1"),
        _ev("remount-scheduled", elId=3, why="detach", epoch=1, sceneHash="#2"),
        _ev("reuse-decoder", key="untitled.mov", newElId=7, oldElId=3, sceneHash="#2"),
    ])
    def test_known_bad_a_carry_note_in_the_zone_is_red_even_if_cleared_later(self, carry: dict[str, Any]) -> None:
        scored = self._score(_retire_read((carry, RETIRE_NOTE)))
        assert scored["verdict"] is False and scored["carryNotes"] == [carry]

    def test_a_carry_note_before_the_zone_or_for_another_movie_is_not(self) -> None:
        events = (_ev("remount-done", elId=5, key="untitled.mov", sceneHash="#0"), _ev("remount-done", elId=8, key="other.mov", sceneHash="#2"), RETIRE_NOTE)
        assert self._score(_retire_read(events))["verdict"] is True

    def test_known_bad_the_settled_checks_still_hold(self) -> None:
        pin = _p2_facts()["pinRect"]
        assert self._score(_retire_read((RETIRE_NOTE,), painting=[painting_video(pin)]))["verdict"] is False
        assert self._score(_retire_read((RETIRE_NOTE,), pool=[{"key": "untitled.mov"}]))["verdict"] is False

    @pytest.mark.parametrize("read", [
        None, {"reason": "x"}, dict(_retire_read((RETIRE_NOTE,)), stageMap=None), dict(_retire_read((RETIRE_NOTE,)), painting={"error": "x"}),
        dict(_retire_read((RETIRE_NOTE,)), poolSnapshot={"error": "x"}), _retire_read(None), _retire_read({"error": "x"}),
    ])
    def test_unreadable_evidence_is_inconclusive(self, read: Any) -> None:
        assert self._score(read)["verdict"] is None

    def test_without_the_runtime_the_notes_are_not_required(self) -> None:
        assert self._score(_retire_read(None), installed=False)["verdict"] is True

    def test_the_observer_retains_the_core_events(self) -> None:
        retire = probe.retire_fact(synthetic_plan(), RETIRED_RUNTIME, BOUNDARY_KEYS)
        out: dict[str, Any] = {}
        host = ArmedHost([])
        probe.boundary_observer(host, {"retire": retire}, out)(2)
        assert "coreEvents" in out["refused1to2"] and probe.CORE_EVENTS_JS in host.transport.evaluations


class TestArmedVerdict:
    @pytest.mark.parametrize("reads", [None, {"reason": "hash never settled"}, [_armed_read(1000.0, 10, 5.0)], [None, None]])
    def test_missing_reads_are_inconclusive(self, reads: Any) -> None:
        assert probe.score_armed_strict(reads, ARMED, GL_CONTINUITY, [])["verdict"] is None

    def test_readable_reads_are_score_armed(self) -> None:
        reads = _armed_reads()
        assert probe.score_armed_strict(reads, ARMED, GL_CONTINUITY, []) == probe.score_armed(reads, ARMED, GL_CONTINUITY, owner_ids=[])

    def test_an_armed_spec_without_its_armed_fact_is_inconclusive(self) -> None:
        facts = probe.ground_truth_facts(_p2_plan(gl=True))
        assert probe.score_verdicts([], {}, facts, True, GL_CONTINUITY)[P2_ARMED12]["verdict"] is None

    def test_unmet_verdicts_skips_ungated_and_separates_unknowns(self) -> None:
        specs = _p2_facts(gl=True)["verdicts"]
        entry = {P2_CARRY12: {"verdict": False}, P2_ARMED12: {"verdict": True}, P2_RESTART23: {"verdict": None}, P2_CARRY34: {"verdict": False}}
        assert probe.unmet_verdicts(entry, specs) == ([P2_CARRY34], [P2_RESTART23])


def _stored_artifact(*, evidence: bool = False, arms: tuple[str, ...] = ("A", "B", "C")) -> dict[str, Any]:
    """A host artifact as the S1 base probe stored it (legacy scorers, no raw evidence unless asked)."""
    facts = _p2_facts()
    samples = _p2_run_samples()
    stored: dict[str, Any] = {}
    for name in arms:
        mode = "off" if name == "B" else "qualified"
        installed = mode == "qualified"
        read = _retire_read((RETIRE_NOTE,))
        arm: dict[str, Any] = {"continuity": {"mode": mode}, "samples": samples}
        arm.update(_plain(probe.score_boundaries(samples, facts, installed)))
        arm["refused1to2"] = _plain(probe.score_retire(read, _spec(facts, P2_RETIRE12), installed))
        if evidence:
            arm["evidence"] = {"refused1to2": read}
        stored[name] = arm
    ground = {key: facts[key] for key in probe.GROUND_TRUTH_KEYS if key in facts and key not in ("verdicts", "planSha256")}
    return {"kind": "live-continuity-probe", "groundTruth": _plain(ground), "arms": stored, "attach": dict(stored.get("A") or {})}


class TestRescoreGenerated:
    """Codex r1 #11: re-derivable verdicts reproduced; the rest INCONCLUSIVE and counted, never "reproduced"."""

    def test_a_legacy_artifact_reproduces_its_rederivable_verdicts_and_counts_the_rest(self) -> None:
        report = probe.rescore_generated(_stored_artifact(), _p2_facts(), None)
        assert report["ok"] is True and report["inventoryComplete"] is True
        assert report["counts"] == {"reproduced": 12, "differ": 0, "notRederivable": 4}
        assert report["claim"] == "re-derivable verdicts reproduced: 12/12; 4 not re-derivable (INCONCLUSIVE)"
        arm = report["arms"]["arm A"]
        assert arm["equalsLegacyScorer"] is True and arm["legacyWithoutGenerated"] == []
        assert arm["verdicts"]["refused1to2"]["match"] is None and arm["verdicts"]["refused1to2"]["reason"].startswith("inconclusive")

    def test_retained_evidence_with_core_events_is_re_scored_too(self) -> None:
        report = probe.rescore_generated(_stored_artifact(evidence=True), _p2_facts(), None)
        assert report["ok"] is True and report["counts"]["notRederivable"] == 0
        assert report["arms"]["arm B"]["verdicts"]["refused1to2"]["match"] is True

    @pytest.mark.parametrize("key", ["continue3to4", "restart2to3"])
    def test_known_bad_a_stored_verdict_the_generated_scorer_does_not_reproduce_fails(self, key: str) -> None:
        artifact = _stored_artifact()
        artifact["arms"]["A"][key]["verdict"] = not artifact["arms"]["A"][key]["verdict"]
        report = probe.rescore_generated(artifact, _p2_facts(), None)
        assert report["ok"] is False and report["arms"]["arm A"]["verdicts"][key]["match"] is False

    @pytest.mark.parametrize("arms", [("A", "B"), ("A", "C"), ()])
    def test_known_bad_an_incomplete_arm_inventory_is_not_ok(self, arms: tuple[str, ...]) -> None:
        report = probe.rescore_generated(_stored_artifact(arms=arms), _p2_facts(), None)
        assert report["ok"] is False and report["inventoryComplete"] is False

    def test_known_bad_a_stored_legacy_verdict_with_no_generated_counterpart_fails(self) -> None:
        artifact = _stored_artifact()
        artifact["arms"]["A"]["armed1to2"] = {"verdict": True}
        report = probe.rescore_generated(artifact, _p2_facts(), None)
        assert report["ok"] is False and report["arms"]["arm A"]["legacyWithoutGenerated"] == ["armed1to2"]

    def test_an_arm_that_scored_on_facts_is_rescored_with_them(self) -> None:
        artifact = _stored_artifact()
        artifact["arms"]["A"]["factsSet"] = "on"
        del artifact["arms"]["A"]["refused1to2"]
        report = probe.rescore_generated(artifact, _p2_facts(), _p2_facts(gl=True))
        assert report["arms"]["arm A"]["verdicts"]["armed1to2"]["match"] is None
        assert "refused1to2" not in report["arms"]["arm A"]["verdicts"]


class TestGotoMatrixFromThePlan:
    def test_p2_is_todays_matrix(self) -> None:
        assert probe.goto_matrix(probe.verdict_specs(_p2_plan()), 4) == probe.GOTO_MATRIX

    def test_a_chain_adds_goto_mid_chain_then_advance_across_the_next_carry(self) -> None:
        pin = _MOVIE(BIG_ASSET, "pin", _RECT(**BIG_INSTANCE), _RECT(**BIG_INSTANCE))
        bridge = _MOVIE(BIG_ASSET, "bridge", _RECT(**BIG_INSTANCE), _RECT(**OTHER_INSTANCE))
        plan = _plan(
            (_BOUNDARY(0, 1, (pin,)), _BOUNDARY(1, 2, (bridge,), 1.5)), {0: 0, 1: 2, 2: 4},
            {0: {BIG_ASSET: [BIG_INSTANCE]}, 1: {BIG_ASSET: [BIG_INSTANCE]}, 2: {BIG_ASSET: [OTHER_INSTANCE]}},
        )
        assert probe.goto_matrix(probe.verdict_specs(plan), 3) == ((1, 2), (1, 3), (3, 1), (1, 2, 3))

    def test_overall_status_g_counts_against_the_recorded_matrix(self) -> None:
        matrix = [[1, 2], [1, 2, 3]]
        arm = _g_arm([_g_destination(1, 2, True), _g_destination(1, 2, True)])
        assert probe.overall_status_g({"matrix": matrix, "armed": arm, "nullControl": dict(arm)})[0] == "pass"
        assert probe.overall_status_g({"armed": arm, "nullControl": dict(arm)})[0] == "error"


class _SlidesPlayer:
    def __init__(self, count: int) -> None:
        self.slides = [{"originalOrdinal": i + 1, "playerIndex": i} for i in range(count)]
        self.transport = FakeTransport(self)

    def _require_transport(self) -> Any:
        return self.transport


class TestDriveEverySlide:
    def test_every_slide_is_visited_and_observed_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        advanced: list[int] = []
        monkeypatch.setattr(probe, "wait_for_decode", lambda player: True)
        monkeypatch.setattr(probe, "advance_until_original_slide", lambda player, ordinal: advanced.append(ordinal))
        monkeypatch.setattr(probe.time, "sleep", lambda s: None)
        player = _SlidesPlayer(6)
        player.transport.evaluate = lambda expression: []
        observed: list[int] = []
        probe.drive_and_sample(player, observer=observed.append)
        assert advanced == [2, 3, 4, 5, 6] and observed == [1, 2, 3, 4, 5, 6]


class TestRedArmInjection:
    PLAN = {"movies": RUNTIME_MOVIES, "boundaries": [RETIRE_BOUNDARY, RESTART_BOUNDARY, BRIDGE_BOUNDARY]}

    def _injected(self) -> dict[str, Any]:
        script = probe.live_host_module._continuity_scripts(self.PLAN, {"width": 1920, "height": 1080})
        return json.loads(script.split("var plan=", 1)[1].split(";var w=", 1)[0])

    @pytest.mark.parametrize(("action", "scene", "left"), [
        ("bridge", None, [2, 6]), ("bridge", 8, [2, 6]), ("retire", 2, [6, 8]), ("restart", 6, [2, 8]),
    ])
    def test_strip_removes_only_the_matching_entry_from_the_injected_plan(self, action: str, scene: int | None, left: list[int]) -> None:
        with probe.stripped_runtime(action, scene):
            assert [b["atScene"] for b in self._injected()["boundaries"]] == left
        assert [b["atScene"] for b in self._injected()["boundaries"]] == [2, 6, 8]
        assert self.PLAN["boundaries"][2] is BRIDGE_BOUNDARY

    def test_bridge_disabled_is_strip_bridge(self) -> None:
        with probe.bridge_disabled():
            assert [b["action"] for b in self._injected()["boundaries"]] == ["retire", "restart"]

    def test_a_strip_that_matches_nothing_fails_loudly_at_injection(self) -> None:
        with probe.stripped_runtime("pin"):
            with pytest.raises(ValueError):
                self._injected()

    def test_strip_never_touches_the_derivation(self) -> None:
        with probe.stripped_runtime("retire", 2):
            assert _p2_plan().to_runtime()["boundaries"][0]["action"] == "retire"

    @pytest.mark.parametrize("name", ["stash-any", "wrong-instance", "fifo-reuse"])
    def test_a_core_variant_is_what_the_host_injects_and_reports(self, name: str) -> None:
        core_before = probe.live_host_module._continuity_core_script()
        with probe.injected_core_variant(name) as sha:
            core = probe.live_host_module._continuity_core_script()
            assert sha == probe.variant_sha(name) == probe.live_host_module.js_sha256()
            assert (core == core_before) is (name == "fifo-reuse")
        assert probe.live_host_module._continuity_core_script() == core_before
        assert probe.live_host_module.js_sha256() == probe.js_sha256()


class TestRedArmArgs:
    @pytest.mark.parametrize(("value", "expected"), [("bridge@8", ("bridge", 8)), ("retire", ("retire", None))])
    def test_strip_parses(self, value: str, expected: tuple[str, int | None]) -> None:
        assert probe.parse_args(["--strip", value]).strip == expected

    def test_core_variant_parses_and_rejects_unknown_names(self) -> None:
        assert probe.parse_args(["--core-variant", "stash-any"]).core_variant == "stash-any"
        with pytest.raises(SystemExit):
            probe.parse_args(["--core-variant", "lifo"])
        with pytest.raises(SystemExit):
            probe.parse_args(["--strip", "bridge@x"])

    @pytest.mark.parametrize("extra", [
        ["--core-variant", "stash-any"], ["--pass", "G"], ["--force-wrap", "1to2:0"], ["--rescore", "x.json"],
        ["--gl-replay", "auto", "--gl-force-fail", "planUnreadable"],
    ])
    def test_a_red_arm_runs_on_its_own(self, extra: list[str]) -> None:
        with pytest.raises(SystemExit):
            probe.parse_args(["--strip", "bridge@8", *extra])


class TestRedArmRegistration:
    def test_every_registered_id_is_a_p2_verdict_or_a_stray_on_a_p2_slide(self) -> None:
        ids = {spec["id"] for gl in (False, True) for spec in probe.verdict_specs(_p2_plan(gl))}
        assets = {asset.lower() for per in _p2_plan().slide_instances.values() for asset in per}
        for (sha, label, gl), expected in probe.RED_ARM_EXPECTATIONS.items():
            assert sha == probe.P2_OFF_PLAN_SHA256 and gl in ("off", "auto")
            for red_id in () if expected == probe.RECORD else expected:
                if red_id.startswith("stray:"):
                    _, slide, asset = red_id.split(":")
                    assert asset in assets and 1 <= int(slide.removeprefix("slide")) <= 4
                else:
                    assert red_id in ids, red_id

    def test_the_pre_registered_sets_are_the_plans(self) -> None:
        """Plan §3 G-S1c/G-S1d: stash-any reds only the slide-4 WA0125 stray; each strip only its boundary."""
        expected = {label: value for (_, label, _), value in probe.RED_ARM_EXPECTATIONS.items()}
        assert expected["core:stash-any"] == ("stray:slide4:vid-20250608-wa0125.mp4",)
        assert expected["strip:bridge@8"] == (P2_CARRY34,)
        assert expected["strip:retire@2"] == (P2_CARRY12, P2_RETIRE12, "stray:slide2:untitled.mov")
        assert expected["strip:glReplay@2"] == (P2_ARMED12,)
        assert expected["strip:restart@6"] == probe.RECORD

    @pytest.mark.parametrize(("core", "strip", "label"), [
        ("stash-any", None, "core:stash-any"), (None, ("bridge", 8), "strip:bridge@8"),
        (None, ("bridge", None), "strip:bridge@8"), (None, ("restart", None), "strip:restart"),
    ])
    def test_labels(self, core: Any, strip: Any, label: str) -> None:
        runtime = {"boundaries": [RETIRE_BOUNDARY, RESTART_BOUNDARY, BRIDGE_BOUNDARY, dict(RESTART_BOUNDARY, atScene=10)]}
        assert probe.red_arm_label(core, strip, runtime) == label


def _red_result(red: list[str], expected: Any = (P2_CARRY34,), **arm: Any) -> dict[str, Any]:
    sha = probe.js_sha256()
    entry = {"continuity": {"mode": "qualified", "sha256": sha}, "stageFit": {"verdict": True}, "unplannedWraps": [], **arm}
    return {
        "redArm": "strip:bridge@8", "expectedCoreSha256": sha, "arm": entry, "redSet": sorted(red),
        "unknown": [], "expectedRedSet": list(expected) if isinstance(expected, tuple) else expected,
    }


class TestRedArmStatus:
    def test_exactly_the_pre_registered_set_passes(self) -> None:
        assert probe.red_arm_status(_red_result([P2_CARRY34])) == ("pass", [])

    def test_known_bad_an_extra_red_fails(self) -> None:
        status, reasons = probe.red_arm_status(_red_result([P2_CARRY34, "stray:slide4:x.mov"]))
        assert status == "fail" and reasons == ["unexpectedly red: stray:slide4:x.mov"]

    def test_known_bad_a_red_that_stayed_green_fails(self) -> None:
        status, reasons = probe.red_arm_status(_red_result([]))
        assert status == "fail" and reasons == [f"expected red but green: {P2_CARRY34}"]

    def test_known_bad_a_second_occurrence_of_an_expected_stray_fails(self) -> None:
        """Codex r1 #10: exact multisets, never `set()`."""
        stray = "stray:slide4:vid-20250608-wa0125.mp4"
        status, reasons = probe.red_arm_status(_red_result([stray, stray], expected=(stray,)))
        assert status == "fail" and reasons == [f"unexpectedly red: {stray}"]

    def test_record_and_unregistered_never_pass(self) -> None:
        assert probe.red_arm_status(_red_result([], expected=probe.RECORD))[0] == "recorded"
        assert probe.red_arm_status(_red_result([], expected=None))[0] == "unregistered"

    def test_a_variant_arm_must_report_the_variants_sha(self) -> None:
        stray = "stray:slide4:vid-20250608-wa0125.mp4"
        result = _red_result([stray], expected=(stray,))
        result["expectedCoreSha256"] = probe.variant_sha("stash-any")
        status, reasons = probe.red_arm_status(result)
        assert status == "error" and "expected" in reasons[0]
        result["arm"]["continuity"]["sha256"] = probe.variant_sha("stash-any")
        assert probe.red_arm_status(result)[0] == "pass"

    @pytest.mark.parametrize(("change", "status"), [
        ({"continuity": {"mode": "off"}}, "error"), ({"stageFit": {"verdict": False}}, "error"),
        ({"unplannedWraps": [{"t": 1}]}, "invalid"),
    ])
    def test_the_wrong_mechanism_is_never_a_verdict(self, change: dict[str, Any], status: str) -> None:
        result = _red_result([P2_CARRY34])
        result["arm"].update(change)
        assert probe.red_arm_status(result)[0] == status

    def test_an_expected_red_that_came_back_inconclusive_is_never_a_match(self) -> None:
        """Codex r1 #3: the bridge verdict None (sampling stopped) with the census clean."""
        result = _red_result([])
        result["unknown"] = [P2_CARRY34]
        assert probe.red_arm_status(result)[0] == "inconclusive"


class TestStrayCensus:
    PLAN_INSTANCES = {0: {BIG_ASSET: [BIG_INSTANCE]}, 1: {BIG_ASSET: [BIG_INSTANCE], OTHER_ASSET: [OTHER_INSTANCE]}}
    PLAYERS = {1: 0, 2: 1}

    def _read(self, *rects: tuple[dict[str, float], str]) -> dict[str, Any]:
        return {"stageMap": dict(IDENTITY_STAGE_MAP), "painting": [painting_video(r, src=src) for r, src in rects]}

    def _clean(self) -> dict[str, Any]:
        return {"1": self._read((BIG_INSTANCE, "untitled.mov")), "2": self._read((BIG_INSTANCE, "untitled.mov"))}

    def test_an_unplanned_video_is_a_stray_named_by_slide_and_asset(self) -> None:
        raw = dict(self._clean(), **{"1": self._read((BIG_INSTANCE, "Untitled.mov"), (OTHER_INSTANCE, "wa0125.mov"))})
        records, red, unknown = probe.score_census(raw, self.PLAN_INSTANCES, {}, self.PLAYERS)
        assert red == ["stray:slide1:wa0125.mov"] and unknown == []
        assert len(records["1"]["unexpectedVideos"]) == 1 and records["2"]["verdict"] is True

    def test_every_occurrence_is_counted(self) -> None:
        raw = dict(self._clean(), **{"1": self._read((BIG_INSTANCE, "untitled.mov"), (OTHER_INSTANCE, "wa0125.mov"), (OTHER_INSTANCE, "wa0125.mov"))})
        assert probe.score_census(raw, self.PLAN_INSTANCES, {}, self.PLAYERS)[1] == ["stray:slide1:wa0125.mov"] * 2

    def test_a_dead_expected_rect_painted_is_a_stray(self) -> None:
        _, red, _ = probe.score_census(self._clean(), self.PLAN_INSTANCES, {1: {BIG_ASSET: "dead"}}, self.PLAYERS)
        assert red == ["stray:slide2:untitled.mov"]

    def test_two_videos_on_one_instance_are_a_duplicate(self) -> None:
        raw = dict(self._clean(), **{"1": self._read((BIG_INSTANCE, "untitled.mov"), (BIG_INSTANCE, "untitled.mov"))})
        assert probe.score_census(raw, self.PLAN_INSTANCES, {}, self.PLAYERS)[1] == [f"duplicate:slide1:{BIG_ASSET}#1"]

    def test_an_unknown_source_is_named_unknown(self) -> None:
        raw = dict(self._clean(), **{"1": self._read((BIG_INSTANCE, "untitled.mov"), (OTHER_INSTANCE, "zzz.mp4"))})
        assert probe.score_census(raw, self.PLAN_INSTANCES, {}, self.PLAYERS)[1] == ["stray:slide1:unknown"]

    @pytest.mark.parametrize("read", [None, {"stageMap": None, "painting": []}, {"stageMap": dict(IDENTITY_STAGE_MAP), "painting": {"error": "x"}}])
    def test_an_unreadable_or_missing_slide_is_unknown_never_clean(self, read: Any) -> None:
        raw = self._clean()
        if read is None:
            del raw["2"]
        else:
            raw["2"] = read
        records, red, unknown = probe.score_census(raw, self.PLAN_INSTANCES, {}, self.PLAYERS)
        assert red == [] and unknown == ["census:slide2"] and records["2"]["verdict"] is None

    @pytest.mark.parametrize("raw", [None, [], {}])
    def test_no_census_at_all_is_unknown_for_every_slide(self, raw: Any) -> None:
        assert probe.score_census(raw, self.PLAN_INSTANCES, {}, self.PLAYERS)[2] == ["census:slide1", "census:slide2"]

    def test_an_extra_read_is_unknown(self) -> None:
        raw = dict(self._clean(), **{"3": self._read()})
        assert probe.score_census(raw, self.PLAN_INSTANCES, {}, self.PLAYERS)[2] == ["census:slide3"]

    def test_the_census_observer_reads_every_slide_after_the_inner_observer(self) -> None:
        host = ArmedHost([])
        order: list[Any] = []
        out: dict[str, Any] = {}
        observe = probe.census_observer(host, order.append, out)
        observe(1)
        observe(2)
        assert order == [1, 2] and sorted(out) == ["1", "2"]
        assert set(out["1"]) == {"stageMap", "painting"}


def _generated_result() -> dict[str, Any]:
    """A non-P2 deck (a carried pin, then a bridge) whose arms all meet the plan."""
    specs = [
        {"id": "b0to1:a.mov#1->a.mov#1:carry", "alias": "continue1to2", "kind": "carry", "expect": True, "action": "pin"},
        {"id": "b1to2:a.mov#1->a.mov#1:carry", "alias": "continue2to3", "kind": "carry", "expect": True, "action": "bridge"},
    ]
    pin, bridge = specs[0]["id"], specs[1]["id"]
    green = {"verdict": True}
    arm = {"continuity": {"mode": "qualified"}, "stageFit": {"verdict": True}, pin: green, bridge: green}
    off = dict(arm, continuity={"mode": "off"}, **{bridge: {"verdict": False}})
    stripped = dict(arm, **{bridge: {"verdict": False}})
    visible = {name: {"verdict": True} for name in ("V", "Voff")}
    return {
        "groundTruth": {"verdicts": specs, "planSha256": "0" * 64}, "arms": {"A": arm, "B": off, "C": stripped},
        "attach": dict(arm, transparentBackground={"computedBackground": "rgba(0, 0, 0, 0)"}), "visible": visible,
    }


class TestGeneratedStatus:
    PIN, BRIDGE = "b0to1:a.mov#1->a.mov#1:carry", "b1to2:a.mov#1->a.mov#1:carry"

    @pytest.fixture(autouse=True)
    def _visible_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(probe, "visible_reasons", lambda result: [])

    def test_a_deck_meeting_its_plan_passes(self) -> None:
        assert probe.overall_status(_generated_result()) == ("pass", [])

    @pytest.mark.parametrize(("arm", "which", "value"), [("A", 0, False), ("B", 1, True), ("C", 1, True), ("C", 0, False)])
    def test_known_bad_a_verdict_off_its_expectation_fails_by_id(self, arm: str, which: int, value: bool) -> None:
        spec_id = (self.PIN, self.BRIDGE)[which]
        result = _generated_result()
        result["arms"][arm][spec_id] = {"verdict": value}
        status, reasons = probe.overall_status(result)
        assert status == "fail" and reasons == [f"arm {arm} {spec_id}={value!r}, expected {not value!r}"]

    def test_an_unreadable_or_missing_gated_verdict_is_inconclusive(self) -> None:
        result = _generated_result()
        result["attach"][self.PIN] = {"verdict": None}
        assert probe.overall_status(result)[0] == "inconclusive"
        result = _generated_result()
        del result["arms"]["A"][self.BRIDGE]
        assert probe.overall_status(result)[0] == "inconclusive"

    def test_the_wrong_mechanism_fails(self) -> None:
        result = _generated_result()
        result["arms"]["B"]["continuity"] = {"mode": "qualified"}
        status, reasons = probe.overall_status(result)
        assert status == "fail" and "arm B continuity.mode='qualified', expected 'off'" in reasons

    @pytest.mark.parametrize("change", ["noC", "extraArm", "noAttach", "noB"])
    def test_known_bad_a_missing_or_extra_arm_is_an_error(self, change: str) -> None:
        """Codex r1 #6: A, B, attach -- and C exactly when the plan has a bridge."""
        result = _generated_result()
        if change == "noC":
            del result["arms"]["C"]
        elif change == "extraArm":
            result["arms"]["D"] = dict(result["arms"]["A"])
        elif change == "noAttach":
            del result["attach"]
        else:
            del result["arms"]["B"]
        assert probe.overall_status(result)[0] == "error"

    def test_c_is_not_required_without_a_bridge(self) -> None:
        result = _generated_result()
        result["groundTruth"]["verdicts"] = result["groundTruth"]["verdicts"][:1]
        del result["arms"]["C"]
        assert probe.overall_status(result) == ("pass", [])

    @pytest.mark.parametrize("specs", [[], [{"id": 3}], [{"id": "x", "kind": "carry", "expect": "yes", "action": "pin"}], "x"])
    def test_known_bad_an_empty_or_malformed_verdict_set_is_an_error(self, specs: Any) -> None:
        result = _generated_result()
        result["groundTruth"]["verdicts"] = specs
        assert probe.overall_status(result)[0] == "error"

    def test_duplicate_ids_are_an_error(self) -> None:
        result = _generated_result()
        result["groundTruth"]["verdicts"] = [result["groundTruth"]["verdicts"][0]] * 2
        assert probe.overall_status(result)[0] == "error"

    @pytest.mark.parametrize("sha", sorted(probe.P2_PLAN_SHA256))
    def test_only_a_pinned_p2_plan_keeps_the_legacy_status(self, sha: str) -> None:
        result = TestOverallStatusTruthTable()._base_result()
        result["groundTruth"]["verdicts"] = []
        result["groundTruth"]["planSha256"] = sha
        assert probe.overall_status(result) == probe.overall_status(TestOverallStatusTruthTable()._base_result())
        result["groundTruth"]["planSha256"] = "0" * 64
        assert probe.overall_status(result)[0] == "error"
