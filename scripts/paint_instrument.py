#!/usr/bin/env python3
"""Per-frame "painted" instrument for the live-continuity probe (`.agents/plans/keynote_live_continuity_instrument.plan.md`).

The page records raw readings (`PAINT_READ_FN_JS`, `PREPAINT_FN_JS`); Python decides. Never imports the probe:
thresholds the probe owns are passed in.
"""
from __future__ import annotations

from typing import Any, Callable

SAMPLER_SCHEMA = 2
PAINT_OPACITY_FLOOR = 0.02
PAINT_OPAQUE_MIN = 0.99
PAINT_CONTROL_VARIANTS = ("ancestor-opacity", "ancestor-half", "ancestor-display", "element-visibility")
PAINT_CONTROL_PHASES = ("settled", "bridge", "pin")
PAINT_CONTROL_TIMINGS = ("early", "late")

PAINT_READ_FN_JS = ""
PREPAINT_FN_JS = ""


def paint_control_js(
    n: int, variant: str, phase: str, at_scene: int, *, timing: str = "early", depth: int = 1, delay_ticks: int = 10
) -> str:
    raise NotImplementedError


def painted_state(pv: dict[str, Any] | None) -> tuple[str, str | None]:
    raise NotImplementedError


def frame_coverage(rows: list[dict[str, Any]], *, max_gap_frames: int, min_fps: float) -> dict[str, Any]:
    raise NotImplementedError


def score_paint(
    rows: list[dict[str, Any]],
    element_id: int,
    asset_substr: str,
    *,
    start: float,
    end: float,
    slot_of: Callable[[dict[str, Any]], dict[str, float] | None],
    stage_box_of: Callable[[dict[str, Any]], dict[str, float] | None],
    rect_tolerance: float,
    iou_min: float,
    max_gap_frames: int,
    min_fps: float,
) -> dict[str, Any]:
    raise NotImplementedError


def sampler_self_check(
    rows: list[dict[str, Any]], meta: dict[str, Any], *, read_now: float, max_gap_frames: int
) -> dict[str, Any]:
    raise NotImplementedError


def paint_census(
    rows: list[dict[str, Any]], carried: Any, asset_by_id: dict[int, str], *, scene_count: int
) -> dict[str, Any]:
    raise NotImplementedError


def score_paint_control(record: dict[str, Any], target_verdict: dict[str, Any], n: int, timing: str) -> dict[str, Any]:
    raise NotImplementedError
