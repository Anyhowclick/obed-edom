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
import importlib.util
import sys
from pathlib import Path
from typing import Any

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

        return {
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
