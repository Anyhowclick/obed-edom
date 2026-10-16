from __future__ import annotations

import copy
import math
import re
import sys
from collections.abc import Mapping, Sequence
from itertools import groupby
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from obed_edom import managed_obs  # noqa: E402

HOST_HEADLESS_CHROME = "headless Chrome"
HOST_QUALIFIED_CHROME_ATTACH = "qualified Chrome attach"
HOST_MANAGED_OBS_25 = "managed OBS 25"
HOST_MANAGED_OBS_30 = "managed OBS 30"

QUALIFIED_CHROME_BUILD = "155.0.8059.79"
COST_BUDGET_P95_MS = 8.0
REQUIRED_HOOKS = ("sampler.tick", "paint.prePaint", "feed.rvfc", "feed.raf", "feed.draw", "frame.total")

COST_POLICY_STATUS = "draft: 8 ms p95 per hook and aggregate, from the C1 timing split; gate 3 calibration pending"
CADENCE_POLICY_STATUS = "OPEN: owner Q2 at gate 5a; measurement only"
HOST_ROWS_POLICY_STATUS = "OPEN: owner Q1 at gate 5a"
REQUIRED_HOOKS_POLICY_STATUS = "proposed names; frozen with the F/P producers at C2 integration"
LOAD_POLICY_STATUS = "OPEN: recorded, no threshold"
PERCENTILE_POLICY_STATUS = "numpy linear"
POLICY_STATUS = {
    "cost": COST_POLICY_STATUS, "cadence": CADENCE_POLICY_STATUS, "hostRows": HOST_ROWS_POLICY_STATUS,
    "requiredHooks": REQUIRED_HOOKS_POLICY_STATUS, "load": LOAD_POLICY_STATUS, "percentile": PERCENTILE_POLICY_STATUS,
}


def _row(host_kind: str, engine: str, period_ms: float, **extra: Any) -> dict[str, Any]:
    return {
        "hostKind": host_kind, "engine": engine, "periodMs": period_ms,
        "cadenceBoundaryMs": 2 * period_ms, "costBudgetP95Ms": COST_BUDGET_P95_MS,
        "requiredHooks": list(REQUIRED_HOOKS), **extra,
    }


QUALIFICATIONS: dict[str, dict[str, Any]] = {
    **{
        host: _row(host, "chrome", 1000 / 60, chromeBuild=QUALIFIED_CHROME_BUILD)
        for host in (HOST_HEADLESS_CHROME, HOST_QUALIFIED_CHROME_ATTACH)
    },
    **{
        host: _row(host, "cef", 1000 / hz, outputHz=hz,
                   browserSourceHz=managed_obs.RATES[hz][1], obsVersion=managed_obs.PINNED_OBS)
        for hz, host in ((25, HOST_MANAGED_OBS_25), (30, HOST_MANAGED_OBS_30))
    },
}

_CHROME_PRODUCT = re.compile(r"(?:Chrome|HeadlessChrome)/([^/\s]+)")


def qualification(host_kind: str) -> dict[str, Any] | None:
    return copy.deepcopy(QUALIFICATIONS.get(host_kind))


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _well_formed_hook(entry: Any) -> bool:
    if not isinstance(entry, Mapping):
        return False
    count, p95, maximum = entry.get("count"), entry.get("p95"), entry.get("max")
    over = entry.get("overBudget")
    return (
        isinstance(count, int) and not isinstance(count, bool) and count >= 0
        and all(value is None or (_finite_number(value) is not None and value >= 0) for value in (p95, maximum))
        and (over is None or (isinstance(over, int) and not isinstance(over, bool) and over >= 0))
        and ((count > 0 and p95 is not None) or (count == 0 and all(
            value in (None, 0, 0.0) for value in (p95, maximum)
        )))
    )


def _cost(capture: Mapping[str, Any], row: Mapping[str, Any] | None) -> tuple[bool | None, list[str], dict[str, Any]]:
    raw = capture.get("instrumentCost")
    measured = {
        "ok": None, "budgetP95Ms": None,
        "hooks": copy.deepcopy(dict(raw)) if isinstance(raw, Mapping) else {},
        "missingHooks": [], "malformedHooks": [], "overBudgetHooks": [],
    }
    if row is None:
        return None, [], measured
    budget = row["costBudgetP95Ms"]
    required = row["requiredHooks"]
    measured["budgetP95Ms"] = copy.deepcopy(budget)
    if not isinstance(raw, Mapping):
        return None, ["cost: instrumentCost is missing or malformed"], measured
    missing = [hook for hook in required if hook not in raw]
    well_formed = {hook: _well_formed_hook(entry) for hook, entry in raw.items()}
    malformed = [str(hook) for hook, valid in well_formed.items() if not valid]
    over_budget = [
        str(hook)
        for hook, entry in raw.items()
        if well_formed[hook] and entry.get("p95") is not None and entry.get("p95") > budget
    ]
    measured.update(missingHooks=missing, malformedHooks=malformed, overBudgetHooks=over_budget)
    reasons = []
    if missing:
        reasons.append("cost: required hooks are missing: " + ", ".join(missing))
    if malformed:
        reasons.append("cost: malformed hook entries: " + ", ".join(malformed))
    if over_budget:
        reasons.append(f"cost: hook p95 exceeds {budget:g} ms: " + ", ".join(over_budget))
        measured["ok"] = False
        return False, reasons, measured
    if reasons:
        return None, reasons, measured
    measured["ok"] = True
    return True, [], measured


def _matches(label: str, observed: Any, expected: Any, tolerance: float = 0.0) -> tuple[bool | None, str | None]:
    if observed is None or observed == "":
        return None, f"environment: {label} is missing"
    if isinstance(expected, str):
        if not isinstance(observed, str):
            return None, f"environment: {label} is malformed"
        matches = observed == expected
    else:
        value = _finite_number(observed)
        if value is None:
            return None, f"environment: {label} is malformed"
        matches = abs(value - expected) <= tolerance
    return (True, None) if matches else (
        False, f"environment: {label} {observed!r} does not match {expected!r}"
    )


def _environment(capture: Mapping[str, Any], row: Mapping[str, Any] | None) -> tuple[bool | None, list[str], dict[str, Any]]:
    raw = capture.get("environment")
    measured: dict[str, Any] = {
        "ok": None,
        "qualificationIdentity": None,
        "gitHead": None,
        "browserVersion": None,
        "observations": None,
    }
    if not isinstance(raw, Mapping):
        return None, ["environment: environment is missing or malformed"], measured
    measured.update({key: copy.deepcopy(raw.get(key)) for key in (
        "qualificationIdentity", "gitHead", "browserVersion", "observations",
    )})
    checks: list[bool | None] = []
    reasons: list[str] = []
    git_head = raw.get("gitHead")
    status = True if isinstance(git_head, str) and git_head.strip() else None
    checks.append(status)
    if status is None:
        reasons.append("environment: gitHead is missing")
    if row is None:
        return None, reasons, measured
    check_specs = [("qualificationIdentity", raw.get("qualificationIdentity"), row["hostKind"])]
    if row["engine"] == "cef":
        measured.update({key: copy.deepcopy(raw.get(key)) for key in (
            "obsVersion", "outputRate", "browserSourceRate",
        )})
        output = raw.get("outputRate") if isinstance(raw.get("outputRate"), Mapping) else {}
        source = raw.get("browserSourceRate") if isinstance(raw.get("browserSourceRate"), Mapping) else {}
        check_specs.extend([
            ("obsVersion", raw.get("obsVersion"), row["obsVersion"]),
            ("outputRate.configuredHz", output.get("configuredHz"), row["outputHz"]),
            ("outputRate.observedHz", output.get("observedHz"), row["outputHz"], 1e-9),
            ("browserSourceRate.configuredHz", source.get("configuredHz"), row["browserSourceHz"]),
            ("browserSourceRate.settingHz", source.get("settingHz"), row["browserSourceHz"]),
        ])
    for spec in check_specs:
        status, reason = _matches(*spec)
        checks.append(status)
        if reason is not None:
            reasons.append(reason)
    if row["engine"] == "chrome":
        browser = raw.get("browserVersion")
        product = browser.get("product") if isinstance(browser, Mapping) else None
        match = _CHROME_PRODUCT.fullmatch(product) if isinstance(product, str) else None
        if match is None:
            checks.append(None)
            reasons.append("environment: Chrome browserVersion.product is missing or unparseable")
        elif match.group(1) != row["chromeBuild"]:
            checks.append(False)
            reasons.append(f"environment: Chrome {match.group(1)} is not the qualified {row['chromeBuild']}")
        else:
            checks.append(True)
        if row["hostKind"] == HOST_QUALIFIED_CHROME_ATTACH:
            checks.append(None)
            reasons.append("environment: attach display/timing profile is not recorded")

    measured["ok"] = False if False in checks else None if None in checks else True
    return measured["ok"], reasons, measured


def _capture_rows(capture: Mapping[str, Any]) -> list[Mapping[str, Any]] | None:
    key = "sampleRows" if not isinstance(capture.get("samples"), list) and "sampleRows" in capture else "samples"
    rows = capture.get(key)
    return rows if isinstance(rows, list) and all(isinstance(row, Mapping) for row in rows) else None


def _gl_ranges(gl_intervals: Any) -> list[tuple[float, float]] | None:
    if not isinstance(gl_intervals, Sequence) or isinstance(gl_intervals, (str, bytes)):
        return None
    ranges = []
    for interval in gl_intervals:
        if not isinstance(interval, Mapping):
            return None
        start = _finite_number(interval.get("start"))
        end = _finite_number(interval.get("end"))
        if start is None or end is None or end < start:
            return None
        ranges.append((start, end))
    return ranges


def _settled_scene(row: Mapping[str, Any]) -> float | None:
    scene = _finite_number(row.get("scene"))
    state = row.get("playerState")
    return scene if scene is not None and (
        row.get("busy") is False or (isinstance(state, str) and state != "Playing")
    ) else None


def _cadence(capture: Mapping[str, Any], row: Mapping[str, Any] | None,
             gl_intervals: Sequence[Mapping[str, Any]] | None) -> tuple[None, list[str], dict[str, Any]]:
    boundary = row["cadenceBoundaryMs"] if row is not None else None
    measured = {
        "ok": None, "cadenceBoundaryMs": copy.deepcopy(boundary),
        "glIntervals": copy.deepcopy(gl_intervals), "visits": None,
        "visitCount": None, "deltaCount": None,
    }
    open_reason = "cadence: settled-cadence statistic is open (owner Q2, gate 5a); measured only"
    reasons = []
    ranges = None if gl_intervals is None else _gl_ranges(gl_intervals)
    if gl_intervals is None:
        reasons.append("cadence: GL intervals were not supplied")
    elif ranges is None:
        return None, ["cadence: GL intervals are malformed", open_reason], measured
    rows = _capture_rows(capture)
    if rows is None:
        return None, reasons + ["cadence: samples are missing or malformed", open_reason], measured
    if row is None:
        return None, reasons + [open_reason], measured
    timed = []
    for sample in rows:
        frame_time = _finite_number(sample.get("ts"))
        frame_time = frame_time if frame_time is not None else _finite_number(sample.get("t"))
        if frame_time is None:
            return None, reasons + ["cadence: sample rows are missing a finite frame time", open_reason], measured
        timed.append((sample, frame_time))
    visits = []
    total_deltas = 0
    for scene, items in groupby(timed, key=lambda item: _settled_scene(item[0])):
        visit = list(items)
        if scene is None:
            continue
        times = [frame_time for _, frame_time in visit]
        deltas = []
        excluded = 0
        for start, end in zip(times, times[1:]):
            if ranges is not None and any(start < gl_end and gl_start < end for gl_start, gl_end in ranges):
                excluded += 1
            else:
                deltas.append(end - start)
        total_deltas += len(deltas)
        visits.append({
            "scene": copy.deepcopy(visit[0][0].get("scene")), "start": times[0], "end": times[-1],
            "sampleCount": len(visit), "deltaCount": len(deltas),
            "medianMs": float(np.percentile(deltas, 50)) if deltas else None,
            "p95Ms": float(np.percentile(deltas, 95)) if deltas else None,
            "maxMs": max(deltas) if deltas else None,
            "overBoundaryCount": sum(delta > boundary for delta in deltas), "glExcludedDeltas": excluded,
        })
    measured.update(visits=visits, visitCount=len(visits), deltaCount=total_deltas)
    return None, reasons + [open_reason], measured


def _policy(row: Mapping[str, Any] | None) -> dict[str, Any]:
    return {**copy.deepcopy(dict(row or {})), "status": copy.deepcopy(POLICY_STATUS)}


def run_validity(capture: Mapping[str, Any], qualification: Mapping[str, Any] | None, *,
                 gl_intervals: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    host_kind = capture.get("hostKind")
    row = QUALIFICATIONS.get(host_kind) if isinstance(host_kind, str) else None
    qualification_ok: bool | None = None
    if host_kind is None:
        qualification_reasons = ["qualification: capture hostKind is missing"]
    elif not isinstance(host_kind, str):
        qualification_reasons = ["qualification: capture hostKind is malformed"]
    elif row is None:
        qualification_reasons = [f"qualification: unknown hostKind {host_kind!r}"]
    elif qualification != row:
        qualification_reasons = [f"qualification: supplied qualification does not match the qualification for {host_kind}"]
    else:
        qualification_ok, qualification_reasons = True, []
    cost_ok, cost_reasons, measured_cost = _cost(capture, row)
    environment_ok, environment_reasons, measured_environment = _environment(capture, row)
    cadence_ok, cadence_reasons, measured_cadence = _cadence(capture, row, gl_intervals)
    statuses = (qualification_ok, cost_ok, environment_ok, cadence_ok)
    return {
        "ok": False if False in statuses else None if None in statuses else True,
        "reasons": qualification_reasons + cost_reasons + environment_reasons + cadence_reasons,
        "measured": {"cost": measured_cost, "environment": measured_environment, "cadence": measured_cadence},
        "policy": _policy(row),
    }
