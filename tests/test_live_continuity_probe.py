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


def sample(t: float, scene: float | None, *videos: dict[str, Any]) -> dict[str, Any]:
    return {"t": t, "scene": scene, "videos": list(videos)}


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
) -> list[dict[str, Any]]:
    """A clean, carrying decoder (id=1/elId=1) that spans `boundary_scene` with a
    steadily advancing clock, optionally injected with one specific defect."""
    src_rect = src_rect or SRC_RECT
    dst_rect = dst_rect or DST_RECT
    samples: list[dict[str, Any]] = []
    t = 0.0
    current_time = start_time
    stall_frames = int(round((stall_run_s * 1000.0) / dt_ms)) if stall_run_s else 0
    stalled_so_far = 0
    for i in range(n_before):
        samples.append(sample(t, boundary_scene - 1, video(id=1, el_id=1, t=t, scene=boundary_scene - 1, current_time=current_time, rect=dict(src_rect))))
        t += dt_ms
        current_time += dt_ms / 1000.0
    if clock_drop:
        current_time -= clock_drop
    for i in range(n_after):
        scene = boundary_scene
        owner = 999 if owner_mismatch_after else "SELF"
        rect = dict(dst_rect)
        if off_rect_after:
            rect["x"] += 50
        connected = not disconnected_after
        advance = 0.0 if stalled_so_far < stall_frames else dt_ms / 1000.0
        samples.append(
            sample(
                t, scene,
                video(
                    id=1, el_id=1, t=t, scene=scene, current_time=current_time,
                    rect=rect, owner_el_id=owner, is_connected=connected,
                ),
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
                },
                "B": {
                    "continuity": {"mode": "off"},
                    "continue1to2": verdict(True), "restart2to3": verdict(True), "continue3to4": verdict(False),
                },
                "C": {
                    "continuity": {"mode": "qualified"},
                    "continue1to2": verdict(True), "restart2to3": verdict(True), "continue3to4": verdict(False),
                },
            },
            "attach": {
                "continuity": {"mode": "qualified"},
                "transparentBackground": {"computedBackground": "rgba(0, 0, 0, 0)"},
                "continue1to2": verdict(True), "restart2to3": verdict(True), "continue3to4": verdict(True),
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
