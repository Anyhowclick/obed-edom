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

    def evaluate(self, js: str) -> Any:
        if js == probe.SCENE_ID_JS:
            return self.host.next_scene_id()
        if js == probe.STAGE_MAP_JS:
            return self.host.stage_map
        if js == probe.PAINTING_VIDEOS_JS:
            return self.host.painting
        return True

    def call(self, method: str, **params: Any) -> dict[str, Any]:
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
        painting: Any = _UNSET,
    ) -> None:
        self.scene_ids = list(scene_ids)
        self.busy = busy
        self.shots = shots if shots is not None else [shot if shot is not None else png_b64(*VISIBLE_VIEWPORT)]
        self.stage_map = dict(FULL_BLEED_STAGE_MAP) if stage_map is _UNSET else stage_map
        self.painting: Any = [] if painting is _UNSET else painting
        self.transport = FakeTransport(self)
        self.observations = 0

    def shot_for(self, index: int) -> str:
        return self.shots[index % len(self.shots)]

    def next_scene_id(self) -> Any:
        return self.scene_ids.pop(0) if self.scene_ids else "exhausted"

    def observe(self) -> FakeObservation:
        busy = self.busy if isinstance(self.busy, bool) else (self.busy.pop(0) if self.busy else False)
        self.observations += 1
        return FakeObservation(busy)

    def _require_transport(self) -> FakeTransport:
        return self.transport


def passing_scorer(frames: list[Any], rects: list[dict[str, Any]], control: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": True, "status": "pass",
        "perRect": [{"label": rect.get("label"), "verdict": True} for rect in rects],
        "stray": {"components": []}, "noiseFloor": {"p99": 0},
    }


VISIBLE_INSTANCES = {0: {"Untitled.mov": [{"x": 10.0, "y": 10.0, "w": 20.0, "h": 10.0}]}}
VISIBLE_SLIDE = {"playerIndex": 0, "originalOrdinal": 1, "skipped": False}


class TestBurstScheduling:
    def test_deadlines_are_absolute_offsets_from_the_burst_start(self) -> None:
        assert probe.burst_deadlines(100.0, (0, 130, 290, 500, 770)) == [100.0, 100.13, 100.29, 100.5, 100.77]
        assert probe.burst_deadlines(100.0) == [100.0 + ms / 1000 for ms in probe.BURST_OFFSETS_MS]

    def test_offsets_are_unequal_so_a_periodic_animation_cannot_alias(self) -> None:
        gaps = [b - a for a, b in zip(probe.BURST_OFFSETS_MS, probe.BURST_OFFSETS_MS[1:])]
        assert gaps[:4] == [130, 160, 210, 270]
        assert len(set(gaps)) == len(gaps)

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
                clock.t += 0.2
            return real_call(method, **params)

        host.transport.call = slow_call  # type: ignore[method-assign]
        _, offsets = probe.capture_burst(host.transport, now=clock.now, sleep=clock.sleep)
        assert offsets[0] == 0.0
        assert offsets[1] == 200.0  # the overrun itself is reported, never hidden
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


def test_burst_is_long_enough_that_a_two_state_movie_cannot_plausibly_alias():
    # The fixture movie is a two-state grating that flips every video frame. With n
    # shots at effectively independent phases, P(every shot lands on the same state)
    # = 2 * 0.5**n. The original 5-shot burst gave 6.25 % per live rect - measured:
    # 2 dead reads in 24 healthy live-expected rects at 2560x1440 - which is a false
    # RED about once per gate chain. 12 shots put it at ~0.05 %.
    shots = len(probe.BURST_OFFSETS_MS)
    assert 2 * 0.5 ** shots < 0.001
    gaps = [b - a for a, b in zip(probe.BURST_OFFSETS_MS, probe.BURST_OFFSETS_MS[1:])]
    assert len(set(gaps)) == len(gaps)
