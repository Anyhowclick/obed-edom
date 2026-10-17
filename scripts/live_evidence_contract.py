"""Producer contract for the live-continuity evidence (`.agents/plans/keynote_live_continuity_contract.plan.md` §2).

Each validator yields `"<clause> at <path>"` for every way a record departs from what its producer emits (types,
nullability, enums, required keys per generation, per-sample uniqueness, producer-enforced cross-field rules); the
ingestion points turn any message into an INCONCLUSIVE or INVALID outcome. Whether enough evidence is present stays
with the scorers. A change to a `*_JS` producer or a note payload updates this module in the same commit.
"""
from __future__ import annotations

import math
import re
from itertools import islice
from typing import Any, Iterable, Iterator

import binary_counter_movie
import paint_instrument

CONTRACT_ERROR_LIMIT = 5

PLAYER_STATES = frozenset({
    "Starting", "DownloadingScipt", "ReadyToJump", "SettingUpScene", "Playing", "WaitingToJump", "Stopped",
    "IdleAtInitialState", "IdleAtFinalState",
})
OWNER_VIAS = frozenset({"footprint-video", "ambiguous", "unknown-key", "none", "no-stage-map"})
GL_STATES = frozenset({"IDLE", "ARM-PRE", "ARM-POST", "LIVE", "STANDDOWN", "RETIRED"})
DECODER_G1 = frozenset({"currentTime", "elId", "footprintOwner", "id", "isConnected", "paused", "readyState", "rect", "src",
                        "videoWidth"})
DECODER_G2 = DECODER_G1 | {"duration", "ended", "loop"}
DECODER_G3 = DECODER_G2 | {"domId", "facade", "preserved", "remounted"}
DECODER_G4 = DECODER_G3 | {"instance"}
DECODER_GENERATIONS = (DECODER_G1, DECODER_G2, DECODER_G3, DECODER_G4)
CONVERSION_KEYS = frozenset({"rectScreen", "stageMapValid"})
RUNTIME_KEYS = ("scene", "playerState", "busy")
S2_ROW_KEYS = ("seq", "ts", "hash", "sceneCount")
PV_CONNECTED_ONLY = ("checkVisibility", "visibility", "displayNone", "opacity", "hiding", "effects", "transform",
                     "visibleRect", "clippedBy")
CSS_VISIBILITY = frozenset({"visible", "hidden", "collapse"})
GL_NOTE_KINDS = re.compile(r"^(glreplay-|remount-|preserve-refused|retire)")
REFUSAL_NOTE_KINDS = re.compile(r"^(remount-|reuse-|dom-swap|facade-|preserve-refused|retire)")
PAGE_ERROR_NOTE_KINDS = re.compile(r"^player-build-error$")
CARRY_COVER_NOTE_KINDS = re.compile(r"^(bridge-motion-start|bridge-clock)$")
MM_FEED_NOTE_KINDS = re.compile(r"^(mm-feed-|feed-|poster-)")
CARRY_COVER_TICKS = 4096
REFUSE_VIAS = frozenset({"stash", "remount", "src-clear", "removeAttribute", "reuse"})
ZONE_FROM = frozenset({"pending", "armed", "released"})
ZONE_TO = frozenset({"armed", "released", "retired"})
BRIDGE_CLOCK_FALLBACK_MIN_MS = 50
INSTRUMENT_COST_HOOKS = (
    "sampler.tick", "paint.prePaint", "feed.rvfc", "feed.raf", "feed.draw", "frame.total",
)
FEED_COST_HOOKS = ("feed.rvfc", "feed.raf", "feed.draw")
INSTRUMENT_COST_ROW_FIELDS = frozenset({"applicable", "installed", "count", "p95", "max", "overBudget"})
RUN_VALIDITY_FIELDS = frozenset({"ok", "reasons", "measured", "policy"})
RUN_VALIDITY_MEASURED_FIELDS = frozenset({"cost", "environment", "cadence"})
RUN_VALIDITY_COST_FIELDS = frozenset({
    "ok", "budgetP95Ms", "hooks", "missingHooks", "malformedHooks", "uninstalledHooks",
    "inapplicableHooks", "overBudgetHooks",
})
RUN_VALIDITY_ENVIRONMENT_FIELDS = frozenset({
    "ok", "qualificationIdentity", "gitHead", "browserVersion", "observations",
})
RUN_VALIDITY_CADENCE_FIELDS = frozenset({
    "ok", "cadenceBoundaryMs", "glIntervals", "visits", "visitCount", "deltaCount",
})
RUN_VALIDITY_STATUS_FIELDS = frozenset({"cost", "cadence", "hostRows", "requiredHooks", "load", "percentile"})
ARTIFACT_RUN_VALIDITY_FIELDS = frozenset({"ok", "reasons", "policy", "measured", "holders"})
VISIBLE_PASSES = frozenset({"V", "Voff", "Vgl"})
HOLDER_SCOPE_KINDS = frozenset({
    "full-deck", "pass-g-destination", "advance-leg", "carry-cover", "visible", "replay",
})
FULL_SAMPLER_SCOPE_KINDS = frozenset({"full-deck", "pass-g-destination", "advance-leg"})


def first_errors(*streams: Iterable[str], limit: int = CONTRACT_ERROR_LIMIT) -> list[str]:
    """The first `limit` messages across `streams`, in order."""
    return list(islice((message for stream in streams for message in stream), limit))


def stage_map_valid(stage_map: dict[str, Any] | None) -> bool:
    """Fail-closed: missing `#stage`, a zero box, or a non-uniform scale (`|s -
    sy| / s` over 0.1%) is invalid, never silently treated as identity."""
    if not isinstance(stage_map, dict):
        return False
    s, sy = _finite_or_none(stage_map.get("s")), _finite_or_none(stage_map.get("sy"))
    ow, oh = _finite_or_none(stage_map.get("offsetWidth")), _finite_or_none(stage_map.get("offsetHeight"))
    if not all(v is not None and v > 0 for v in (s, sy, ow, oh)):
        return False
    if _finite_or_none(stage_map.get("ox")) is None or _finite_or_none(stage_map.get("oy")) is None:
        return False
    return abs(s - sy) / s <= 0.001


def _finite_or_none(value: Any) -> float | None:
    return float(value) if _finite(value) else None


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _id(value: Any) -> bool:
    return _int(value) and value >= 1


def _id_or_null(value: Any) -> bool:
    return value is None or _id(value)


def _str_or_null(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _ready_state(value: Any) -> bool:
    return _int(value) and 0 <= value <= 4


def _count(value: Any) -> bool:
    return _int(value) and value >= 0


def _box(value: Any, floor: float | None = None) -> bool:
    """x, y finite; w, h finite and >= 0, or > `floor` when given."""
    if not (isinstance(value, dict) and all(_finite(value.get(k)) for k in ("x", "y", "w", "h"))):
        return False
    return value["w"] > floor and value["h"] > floor if floor is not None else value["w"] >= 0 and value["h"] >= 0


def _error_read(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"error"} and isinstance(value["error"], str)


def _fields(value: dict[str, Any], kind: str, path: str, table: dict[str, Any]) -> Iterator[str]:
    for key, valid in table.items():
        if key not in value:
            yield f"{kind}.{key}:missing at {path}"
        elif not valid(value[key]):
            yield f"{kind}.{key} at {path}"


def _unique(values: list[Any], clause: str, path: str) -> Iterator[str]:
    if len(values) != len(set(values)):
        yield f"{clause} at {path}"


def feed_hook_health(value: Any, path: str = "mmFeedEvidence.hookHealth") -> Iterator[str]:
    if not isinstance(value, dict):
        yield f"feedHookHealth:object at {path}"
        return
    yield from _fields(value, "feedHookHealth", path, {
        "version": lambda v: v == 1,
        "bootstrapCalls": _count,
        "configureCalls": _count,
        "installAttempts": _count,
        "accountingComplete": lambda v: isinstance(v, bool),
        "errors": lambda v: isinstance(v, list),
        "hooks": lambda v: isinstance(v, dict),
    })
    errors = value.get("errors") if isinstance(value.get("errors"), list) else []
    for index, error in enumerate(errors):
        if not isinstance(error, dict) or not _non_empty_str(error.get("where")) \
                or not _non_empty_str(error.get("error")):
            yield f"feedHookHealth.error at {path}.errors[{index}]"
    hooks = value.get("hooks") if isinstance(value.get("hooks"), dict) else {}
    if set(hooks) != set(FEED_COST_HOOKS):
        yield f"feedHookHealth.hooks at {path}.hooks"
    valid_rows = True
    for hook in FEED_COST_HOOKS:
        row = hooks.get(hook)
        where = f"{path}.hooks[{hook!r}]"
        if not isinstance(row, dict):
            yield f"feedHookHealth.hook:object at {where}"
            valid_rows = False
            continue
        yield from _fields(row, "feedHookHealth.hook", where, {
            "installed": lambda v: isinstance(v, bool),
            "callbackCount": _count,
            "enterCount": _count,
            "leaveCount": _count,
            "active": _count,
        })
        counts = [row.get(key) for key in ("callbackCount", "enterCount", "leaveCount", "active")]
        if not all(_count(count) for count in counts):
            valid_rows = False
        elif row.get("installed") is False and any(counts[1:]):
            yield f"feedHookHealth.hook:uninstalled accounting at {where}"
            valid_rows = False
    if valid_rows and isinstance(value.get("accountingComplete"), bool):
        complete = not errors and all(
            hooks[hook]["installed"] is True
            and hooks[hook]["callbackCount"] == hooks[hook]["enterCount"] == hooks[hook]["leaveCount"]
            and hooks[hook]["active"] == 0
            for hook in FEED_COST_HOOKS
        )
        if value["accountingComplete"] is not complete:
            yield f"feedHookHealth.accountingComplete at {path}"


def instrument_cost(value: Any, path: str = "instrumentCost") -> Iterator[str]:
    if not isinstance(value, dict):
        yield f"instrumentCost:object at {path}"
        return
    if set(value) != set(INSTRUMENT_COST_HOOKS):
        yield f"instrumentCost.hooks at {path}"
    for hook in INSTRUMENT_COST_HOOKS:
        row = value.get(hook)
        where = f"{path}[{hook!r}]"
        if not isinstance(row, dict):
            yield f"instrumentCost.hook:object at {where}"
            continue
        if set(row) != INSTRUMENT_COST_ROW_FIELDS:
            yield f"instrumentCost.hook:fields at {where}"
        yield from _fields(row, "instrumentCost.hook", where, {
            "applicable": lambda v: isinstance(v, bool),
            "installed": lambda v: isinstance(v, bool),
            "count": _count,
            "p95": lambda v: v is None or _finite(v) and v >= 0,
            "max": lambda v: v is None or _finite(v) and v >= 0,
            "overBudget": _count,
        })
        applicable, installed = row.get("applicable"), row.get("installed")
        count, p95, maximum, over = (row.get(key) for key in ("count", "p95", "max", "overBudget"))
        if applicable is False and (installed is not False or count != 0):
            yield f"instrumentCost.hook:inapplicable at {where}"
        if applicable is True and installed is False and count != 0:
            yield f"instrumentCost.hook:uninstalled at {where}"
        if _count(count) and _count(over) and count == 0:
            if p95 is not None or maximum is not None or over != 0:
                yield f"instrumentCost.hook:zero statistics at {where}"
        elif _count(count) and _count(over) and not (
                _finite(p95) and p95 >= 0 and _finite(maximum) and maximum >= p95 and over <= count):
            yield f"instrumentCost.hook:measured statistics at {where}"
    frame_total = value.get("frame.total")
    if isinstance(frame_total, dict) and frame_total.get("applicable") is not True:
        yield f"instrumentCost.frame.total:applicable at {path}['frame.total']"


def _bool_or_null(value: Any) -> bool:
    return value is None or isinstance(value, bool)


def _finite_nonnegative_or_null(value: Any) -> bool:
    return value is None or _finite(value) and value >= 0


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(_non_empty_str(item) for item in value)


def _run_validity_policy(value: Any, path: str) -> Iterator[str]:
    if not isinstance(value, dict):
        yield f"runValidity.policy:object at {path}"
        return
    status = value.get("status")
    if "status" not in value:
        yield f"runValidity.policy.status:missing at {path}"
    elif not isinstance(status, dict) or set(status) != RUN_VALIDITY_STATUS_FIELDS \
            or not all(_non_empty_str(item) for item in status.values()):
        yield f"runValidity.policy.status at {path}.status"
    host_kind = value.get("hostKind")
    if host_kind is None:
        if set(value) != {"status"}:
            yield f"runValidity.policy:fields at {path}"
        return
    yield from _fields(value, "runValidity.policy", path, {
        "hostKind": _non_empty_str,
        "engine": lambda item: item in ("chrome", "cef"),
        "periodMs": lambda item: _finite(item) and item > 0,
        "cadenceBoundaryMs": lambda item: _finite(item) and item > 0,
        "costBudgetP95Ms": lambda item: _finite(item) and item > 0,
        "requiredHooks": lambda item: isinstance(item, list) and tuple(item) == INSTRUMENT_COST_HOOKS,
    })
    engine = value.get("engine")
    if engine == "chrome":
        expected = {
            "hostKind", "engine", "periodMs", "cadenceBoundaryMs", "costBudgetP95Ms",
            "requiredHooks", "chromeMajors", "status",
        }
        if set(value) != expected:
            yield f"runValidity.policy:fields at {path}"
        yield from _fields(value, "runValidity.policy", path, {
            "chromeMajors": lambda item: isinstance(item, list) and bool(item)
            and all(_int(major) and major > 0 for major in item),
        })
    elif engine == "cef":
        expected = {
            "hostKind", "engine", "periodMs", "cadenceBoundaryMs", "costBudgetP95Ms",
            "requiredHooks", "outputHz", "browserSourceHz", "obsVersion", "status",
        }
        if set(value) != expected:
            yield f"runValidity.policy:fields at {path}"
        yield from _fields(value, "runValidity.policy", path, {
            "outputHz": lambda item: _finite(item) and item > 0,
            "browserSourceHz": lambda item: _finite(item) and item > 0,
            "obsVersion": _non_empty_str,
        })


def _run_validity_cost(
    value: Any, path: str, *, missing_instrument: bool = False, validate_hooks: bool = True,
) -> Iterator[str]:
    if not isinstance(value, dict):
        yield f"runValidity.measured.cost:object at {path}"
        return
    if set(value) != RUN_VALIDITY_COST_FIELDS:
        yield f"runValidity.measured.cost:fields at {path}"
    yield from _fields(value, "runValidity.measured.cost", path, {
        "ok": _bool_or_null,
        "budgetP95Ms": _finite_nonnegative_or_null,
        "hooks": lambda item: isinstance(item, dict),
        "missingHooks": _string_list,
        "malformedHooks": _string_list,
        "uninstalledHooks": _string_list,
        "inapplicableHooks": _string_list,
        "overBudgetHooks": _string_list,
    })
    hooks = value.get("hooks")
    missing = value.get("missingHooks")
    malformed = value.get("malformedHooks")
    if isinstance(missing, list) and all(isinstance(hook, str) for hook in missing) \
            and not set(missing) <= set(INSTRUMENT_COST_HOOKS):
        yield f"runValidity.measured.cost.missingHooks at {path}.missingHooks"
    if isinstance(malformed, list) and all(isinstance(hook, str) for hook in malformed) \
            and isinstance(hooks, dict) and not set(malformed) <= set(hooks):
        yield f"runValidity.measured.cost.malformedHooks at {path}.malformedHooks"
    if validate_hooks and isinstance(hooks, dict) and missing == [] and malformed == [] \
            and not (not hooks and missing_instrument):
        yield from instrument_cost(hooks, f"{path}.hooks")


def _run_validity_environment(value: Any, path: str, engine: Any) -> Iterator[str]:
    if not isinstance(value, dict):
        yield f"runValidity.measured.environment:object at {path}"
        return
    expected = set(RUN_VALIDITY_ENVIRONMENT_FIELDS)
    if engine == "chrome":
        expected.add("chromeBuild")
    elif engine == "cef":
        expected.update(("obsVersion", "outputRate", "browserSourceRate"))
    if set(value) != expected:
        yield f"runValidity.measured.environment:fields at {path}"
    yield from _fields(value, "runValidity.measured.environment", path, {
        "ok": _bool_or_null,
        "qualificationIdentity": _str_or_null,
        "gitHead": _str_or_null,
        "browserVersion": lambda item: item is None or isinstance(item, dict),
        "observations": lambda item: item is None or isinstance(item, dict),
    })
    chrome_build = value.get("chromeBuild")
    if engine == "chrome" and not (chrome_build is None or _non_empty_str(chrome_build)):
        yield f"runValidity.measured.environment.chromeBuild at {path}.chromeBuild"
    if engine == "cef":
        yield from _fields(value, "runValidity.measured.environment", path, {
            "obsVersion": _str_or_null,
            "outputRate": lambda item: item is None or isinstance(item, dict),
            "browserSourceRate": lambda item: item is None or isinstance(item, dict),
        })


def _run_validity_visit(value: Any, path: str) -> Iterator[str]:
    if not isinstance(value, dict):
        yield f"runValidity.cadence.visit:object at {path}"
        return
    yield from _fields(value, "runValidity.cadence.visit", path, {
        "scene": lambda item: item is None or _finite(item),
        "start": _finite,
        "end": _finite,
        "sampleCount": _count,
        "deltaCount": _count,
        "medianMs": _finite_nonnegative_or_null,
        "p95Ms": _finite_nonnegative_or_null,
        "maxMs": _finite_nonnegative_or_null,
        "overBoundaryCount": _count,
        "glExcludedDeltas": _count,
    })


def _run_validity_cadence(value: Any, path: str) -> Iterator[str]:
    if not isinstance(value, dict):
        yield f"runValidity.measured.cadence:object at {path}"
        return
    if set(value) != RUN_VALIDITY_CADENCE_FIELDS:
        yield f"runValidity.measured.cadence:fields at {path}"
    yield from _fields(value, "runValidity.measured.cadence", path, {
        "ok": lambda item: item is None,
        "cadenceBoundaryMs": _finite_nonnegative_or_null,
        "glIntervals": lambda item: item is None or isinstance(item, list),
        "visits": lambda item: item is None or isinstance(item, list),
        "visitCount": lambda item: item is None or _count(item),
        "deltaCount": lambda item: item is None or _count(item),
    })
    intervals = value.get("glIntervals")
    if isinstance(intervals, list):
        for index, interval in enumerate(intervals):
            if not isinstance(interval, dict) or not _finite(interval.get("start")) \
                    or not _finite(interval.get("end")) or interval["end"] < interval["start"]:
                yield f"runValidity.cadence.glInterval at {path}.glIntervals[{index}]"
    visits = value.get("visits")
    if isinstance(visits, list):
        for index, visit in enumerate(visits):
            yield from _run_validity_visit(visit, f"{path}.visits[{index}]")


def run_validity(value: Any, path: str = "runValidity") -> Iterator[str]:
    """The exact per-holder result shape emitted by ``live_run_validity.run_validity``."""
    if not isinstance(value, dict):
        yield f"runValidity:object at {path}"
        return
    if set(value) != RUN_VALIDITY_FIELDS:
        yield f"runValidity:fields at {path}"
    yield from _fields(value, "runValidity", path, {
        "ok": _bool_or_null,
        "reasons": _string_list,
        "measured": lambda item: isinstance(item, dict),
        "policy": lambda item: isinstance(item, dict),
    })
    policy = value.get("policy")
    yield from _run_validity_policy(policy, f"{path}.policy")
    measured = value.get("measured")
    if not isinstance(measured, dict):
        return
    if set(measured) != RUN_VALIDITY_MEASURED_FIELDS:
        for key in RUN_VALIDITY_MEASURED_FIELDS - set(measured):
            yield f"runValidity.measured.{key}:missing at {path}.measured"
        if set(measured) - RUN_VALIDITY_MEASURED_FIELDS:
            yield f"runValidity.measured:fields at {path}.measured"
    engine = policy.get("engine") if isinstance(policy, dict) else None
    if "cost" in measured:
        reasons = value.get("reasons")
        missing_instrument = isinstance(reasons, list) \
            and "cost: instrumentCost is missing or malformed" in reasons
        yield from _run_validity_cost(
            measured["cost"], f"{path}.measured.cost", missing_instrument=missing_instrument,
            validate_hooks=isinstance(policy, dict) and _non_empty_str(policy.get("hostKind")),
        )
    if "environment" in measured:
        yield from _run_validity_environment(measured["environment"], f"{path}.measured.environment", engine)
    if "cadence" in measured:
        yield from _run_validity_cadence(measured["cadence"], f"{path}.measured.cadence")


def artifact_run_validity(value: Any, path: str = "runValidity") -> Iterator[str]:
    """The homogeneous top-level aggregate, retaining every holder's full validity result."""
    if not isinstance(value, dict):
        yield f"artifactRunValidity:object at {path}"
        return
    if set(value) != ARTIFACT_RUN_VALIDITY_FIELDS:
        yield f"artifactRunValidity:fields at {path}"
    yield from _fields(value, "artifactRunValidity", path, {
        "ok": _bool_or_null,
        "reasons": _string_list,
        "policy": lambda item: isinstance(item, dict),
        "measured": lambda item: isinstance(item, dict),
        "holders": lambda item: isinstance(item, dict) and bool(item),
    })
    policy = value.get("policy")
    if isinstance(policy, dict):
        if set(policy) != {"hostKind"}:
            yield f"artifactRunValidity.policy:fields at {path}.policy"
        yield from _fields(policy, "artifactRunValidity.policy", f"{path}.policy", {
            "hostKind": _non_empty_str,
        })
    measured = value.get("measured")
    environment = measured.get("environment") if isinstance(measured, dict) else None
    if isinstance(measured, dict) and set(measured) != {"environment"}:
        yield f"artifactRunValidity.measured:fields at {path}.measured"
    if isinstance(environment, dict):
        if set(environment) != {"chromeBuild"}:
            yield f"artifactRunValidity.measured.environment:fields at {path}.measured.environment"
        yield from _fields(
            environment, "artifactRunValidity.measured.environment", f"{path}.measured.environment",
            {"chromeBuild": lambda item: item is None or _non_empty_str(item)},
        )
    elif isinstance(measured, dict):
        yield f"artifactRunValidity.measured.environment:object at {path}.measured.environment"
    holders = value.get("holders")
    if not isinstance(holders, dict):
        return
    statuses: list[bool | None] = []
    expected_reasons: list[str] = []
    holder_builds: list[Any] = []
    aggregate_host = policy.get("hostKind") if isinstance(policy, dict) else None
    for name, validity in holders.items():
        where = f"{path}.holders[{name!r}]"
        if not _non_empty_str(name):
            yield f"artifactRunValidity.holderName at {where}"
        if not isinstance(validity, dict):
            statuses.append(None)
            expected_reasons.append(f"{name}: runValidity is missing or malformed")
            holder_builds.append(None)
            continue
        yield from run_validity(validity, where)
        status = validity.get("ok")
        statuses.append(status if status is True or status is False else None)
        reasons = validity.get("reasons")
        if isinstance(reasons, list):
            expected_reasons.extend(f"{name}: {reason}" for reason in reasons if _non_empty_str(reason))
        holder_policy = validity.get("policy")
        policy_host = holder_policy.get("hostKind") if isinstance(holder_policy, dict) else None
        if policy_host != aggregate_host:
            yield f"artifactRunValidity.policy.hostKind at {where}.policy.hostKind"
        holder_measured = validity.get("measured")
        holder_environment = holder_measured.get("environment") if isinstance(holder_measured, dict) else None
        holder_builds.append(
            holder_environment.get("chromeBuild") if isinstance(holder_environment, dict) else None
        )
    expected_ok = (
        False if False in statuses
        else True if statuses and all(status is True for status in statuses)
        else None
    )
    if value.get("ok") is not expected_ok:
        yield f"artifactRunValidity.ok at {path}.ok"
    if value.get("reasons") != expected_reasons:
        yield f"artifactRunValidity.reasons at {path}.reasons"
    expected_build = (
        holder_builds[0]
        if holder_builds and all(build == holder_builds[0] for build in holder_builds)
        else None
    )
    aggregate_build = environment.get("chromeBuild") if isinstance(environment, dict) else None
    if aggregate_build != expected_build:
        yield f"artifactRunValidity.measured.environment.chromeBuild at {path}.measured.environment.chromeBuild"


def _sampler_observer(value: Any, path: str) -> Iterator[str]:
    if not isinstance(value, dict):
        yield f"samplerObserver:object at {path}"
        return
    yield from _fields(value, "samplerObserver", path, {
        "installed": lambda item: isinstance(item, bool),
        "active": lambda item: isinstance(item, bool),
        "disconnected": lambda item: isinstance(item, bool),
        "callbacks": _count,
        "ignored": _count,
        "failures": _count,
    })


def _read_cost(value: Any, kind: str, path: str) -> Iterator[str]:
    if not isinstance(value, dict):
        yield f"{kind}:object at {path}"
        return
    yield from _fields(value, kind, path, {
        "sum": lambda item: _finite(item) and item >= 0,
        "max": lambda item: _finite(item) and item >= 0,
    })
    if _finite(value.get("sum")) is True and _finite(value.get("max")) is True and value["max"] > value["sum"]:
        yield f"{kind}:maximum at {path}"


def _sampler_cost_health(value: Any, path: str) -> Iterator[str]:
    if not isinstance(value, dict):
        yield f"samplerCost:object at {path}"
        return
    yield from _fields(value, "samplerCost", path, {
        "installAttempts": _count,
        "installed": lambda item: isinstance(item, bool),
        "callbacks": _count,
        "enterCount": _count,
        "leaveCount": _count,
        "active": _count,
        "accountingComplete": lambda item: isinstance(item, bool),
    })
    counts = [value.get(key) for key in ("callbacks", "enterCount", "leaveCount", "active")]
    if all(_count(count) for count in counts) and isinstance(value.get("installed"), bool) \
            and isinstance(value.get("accountingComplete"), bool):
        complete = value["installed"] and value["active"] == 0 \
            and value["callbacks"] == value["enterCount"] == value["leaveCount"]
        if value["accountingComplete"] is not complete:
            yield f"samplerCost.accountingComplete at {path}"


def sampler_health(value: Any, path: str = "sampler") -> Iterator[str]:
    """The stopped sampler's lifecycle, retained-row and observer-accounting record."""
    if not isinstance(value, dict):
        yield f"sampler:object at {path}"
        return
    yield from _fields(value, "sampler", path, {
        "schema": lambda item: item is None or item == 2,
        "meta": lambda item: isinstance(item, dict),
        "selfCheck": lambda item: isinstance(item, dict),
    })
    meta = value.get("meta")
    missing_meta = value.get("schema") is None
    if isinstance(meta, dict):
        meta_fields = {
            "schema": lambda item: item is None or item == 2,
            "rafTicks": lambda item: item is None or _count(item),
            "overflow": lambda item: item is None or _count(item),
            "errors": lambda item: item is None or _string_list(item),
            "lastTs": lambda item: item is None or _finite(item),
            "running": lambda item: item is None or item is False,
            "startedAt": lambda item: item is None or _finite(item),
            "stoppedAt": lambda item: item is None or _finite(item),
            "prepaint": lambda item: item is None or _count(item),
            "ppMismatch": lambda item: item is None or _count(item),
            "ppDuplicate": lambda item: item is None or _count(item),
            "readCostMs": lambda item: item is None or isinstance(item, dict),
            "prepaintObserver": lambda item: item is None or isinstance(item, dict),
            "samplerCost": lambda item: item is None or isinstance(item, dict),
        }
        for key, valid in meta_fields.items():
            if key not in meta or meta[key] is None:
                missing_meta = True
            elif not valid(meta[key]):
                yield f"samplerMeta.{key} at {path}.meta"
        if isinstance(meta.get("readCostMs"), dict):
            yield from _read_cost(meta["readCostMs"], "samplerReadCost", f"{path}.meta.readCostMs")
        if isinstance(meta.get("prepaintObserver"), dict):
            yield from _sampler_observer(meta["prepaintObserver"], f"{path}.meta.prepaintObserver")
        if isinstance(meta.get("samplerCost"), dict):
            yield from _sampler_cost_health(meta["samplerCost"], f"{path}.meta.samplerCost")
    check = value.get("selfCheck")
    if isinstance(check, dict):
        yield from _fields(check, "samplerSelfCheck", f"{path}.selfCheck", {
            "ok": lambda item: isinstance(item, bool),
            "reasons": _string_list,
            "rows": _count,
            "rowsWithPp": _count,
            "rowsWithoutPp": _count,
            "seqGaps": _count,
            "staleMs": _finite_nonnegative_or_null,
            "periodMs": _finite_nonnegative_or_null,
            "rafTicks": lambda item: item is None or _count(item),
            "prepaint": lambda item: item is None or _count(item),
            "startedAt": lambda item: item is None or _finite(item),
            "stoppedAt": lambda item: item is None or _finite(item),
            "prepaintObserver": lambda item: item is None or isinstance(item, dict),
            "observerAccountingComplete": lambda item: item is None or isinstance(item, bool),
            "readCostMs": lambda item: item is None or isinstance(item, dict),
        })
        if isinstance(check.get("prepaintObserver"), dict):
            yield from _sampler_observer(check["prepaintObserver"], f"{path}.selfCheck.prepaintObserver")
        if isinstance(check.get("readCostMs"), dict):
            yield from _read_cost(check["readCostMs"], "samplerReadCost", f"{path}.selfCheck.readCostMs")
        reasons = check.get("reasons")
        ok = check.get("ok")
        if isinstance(ok, bool) and isinstance(reasons, list) and ok is not (reasons == []):
            yield f"samplerSelfCheck.ok at {path}.selfCheck.ok"
        if missing_meta and not (ok is False and isinstance(reasons, list) and bool(reasons)):
            yield f"samplerHealth.failureState at {path}.selfCheck"


def attach_provenance(value: Any, path: str = "environment.attach") -> Iterator[str]:
    """The disposable headless-Chrome attach launch and exact renderer read-back."""
    if not isinstance(value, dict):
        yield f"attachProvenance:object at {path}"
        return
    yield from _fields(value, "attachProvenance", path, {
        "launchArguments": lambda item: isinstance(item, list) and all(isinstance(arg, str) for arg in item),
        "deviceMetricsResponse": lambda item: isinstance(item, dict),
        "viewportReadback": lambda item: isinstance(item, dict),
    })
    args = value.get("launchArguments")
    if isinstance(args, list) and "--headless=new" not in args:
        yield f"attachProvenance.launchArguments:headless at {path}.launchArguments"
    viewport = value.get("viewportReadback")
    if isinstance(viewport, dict):
        yield from _fields(viewport, "attachViewport", f"{path}.viewportReadback", {
            "innerWidth": lambda item: item == 1920 and _int(item),
            "innerHeight": lambda item: item == 1080 and _int(item),
            "devicePixelRatio": lambda item: _finite(item) and item == 1,
        })


def visible_scope(value: Any, path: str = "scope") -> Iterator[str]:
    if not isinstance(value, dict):
        yield f"visibleScope:object at {path}"
        return
    if set(value) != {"kind", "pass"}:
        yield f"visibleScope.fields at {path}"
    yield from _fields(value, "visibleScope", path, {
        "kind": lambda item: item == "visible",
        "pass": lambda item: item in VISIBLE_PASSES,
    })


def validity_holder(value: Any, path: str = "holder", *, attach: bool = False) -> Iterator[str]:
    """Common Phase-2 holder contract; capture-kind policy remains with the producer."""
    if not isinstance(value, dict):
        yield f"validityHolder:object at {path}"
        return
    yield from _fields(value, "validityHolder", path, {
        "hostKind": _non_empty_str,
        "scope": lambda item: isinstance(item, dict),
        "runValidity": lambda item: isinstance(item, dict),
    })
    costs = value.get("instrumentCost")
    validity = value.get("runValidity")
    reasons = validity.get("reasons") if isinstance(validity, dict) else None
    measured = validity.get("measured") if isinstance(validity, dict) else None
    missing_cost_reason = isinstance(reasons, list) \
        and "cost: instrumentCost is missing or malformed" in reasons
    missing_environment_reason = isinstance(reasons, list) \
        and "environment: environment is missing or malformed" in reasons
    environment = value.get("environment")
    if environment is None:
        if not missing_environment_reason:
            yield f"validityHolder.environment:missing at {path}"
    elif not isinstance(environment, dict):
        yield f"validityHolder.environment at {path}.environment"
    if costs is None:
        if not missing_cost_reason:
            yield f"validityHolder.instrumentCost:missing at {path}"
    elif not isinstance(costs, dict):
        yield f"validityHolder.instrumentCost at {path}.instrumentCost"
    if isinstance(validity, dict):
        yield from run_validity(validity, f"{path}.runValidity")
        policy = validity.get("policy")
        if isinstance(policy, dict) and policy.get("hostKind") != value.get("hostKind"):
            yield f"validityHolder.hostKind at {path}.runValidity.policy.hostKind"
        measured_cost = measured.get("cost") if isinstance(measured, dict) else None
        if isinstance(measured_cost, dict):
            missing = measured_cost.get("missingHooks")
            malformed = measured_cost.get("malformedHooks")
            if isinstance(costs, dict) and missing == [] and malformed == []:
                yield from instrument_cost(costs, f"{path}.instrumentCost")
            expected_hooks = costs if isinstance(costs, dict) else {}
            if measured_cost.get("hooks") != expected_hooks:
                yield f"validityHolder.instrumentCost at {path}.runValidity.measured.cost.hooks"
    scope = value.get("scope")
    kind = scope.get("kind") if isinstance(scope, dict) else None
    if isinstance(scope, dict):
        if kind not in HOLDER_SCOPE_KINDS:
            yield f"validityHolder.scope.kind at {path}.scope.kind"
        elif kind == "visible":
            yield from visible_scope(scope, f"{path}.scope")
    measured_cost = measured.get("cost") if isinstance(measured, dict) else None
    missing_values = measured_cost.get("missingHooks") if isinstance(measured_cost, dict) else None
    malformed_values = measured_cost.get("malformedHooks") if isinstance(measured_cost, dict) else None
    missing_hooks = {hook for hook in missing_values or [] if isinstance(hook, str)} \
        if isinstance(missing_values, list) else set()
    malformed_hooks = {hook for hook in malformed_values or [] if isinstance(hook, str)} \
        if isinstance(malformed_values, list) else set()
    pinned = {
        "full-deck": {"sampler.tick": True, "paint.prePaint": True},
        "pass-g-destination": {"sampler.tick": True, "paint.prePaint": True},
        "advance-leg": {"sampler.tick": True, "paint.prePaint": True},
        "carry-cover": {"sampler.tick": True, "paint.prePaint": False},
        "visible": {"sampler.tick": False, "paint.prePaint": False},
    }
    if isinstance(costs, dict):
        expected_applicability = {"frame.total": True, **pinned.get(kind, {})}
        for hook, applicable in expected_applicability.items():
            if hook in missing_hooks or hook in malformed_hooks:
                continue
            row = costs.get(hook)
            if not isinstance(row, dict) or row.get("applicable") is not applicable:
                yield f"validityHolder.scope.applicability at {path}.instrumentCost[{hook!r}]"
    if kind == "replay" and isinstance(validity, dict) and validity.get("ok") is True:
        yield f"validityHolder.replay.ok at {path}.runValidity.ok"
    if kind == "visible" and "sampler" in value:
        yield f"visibleHolder.sampler at {path}.sampler"
    elif kind in FULL_SAMPLER_SCOPE_KINDS and "sampler" not in value:
        yield f"validityHolder.sampler:missing at {path}"
    elif "sampler" in value:
        sampler = value["sampler"]
        if sampler is None:
            has_reason = isinstance(reasons, list) and bool(reasons)
            tick = costs.get("sampler.tick") if isinstance(costs, dict) else None
            full_sampler_failure = (
                isinstance(tick, dict) and tick.get("installed") is False
                or costs is None and missing_cost_reason
            )
            if not has_reason or kind in FULL_SAMPLER_SCOPE_KINDS and not (
                    full_sampler_failure and isinstance(validity, dict) and validity.get("ok") is not True):
                yield f"validityHolder.sampler at {path}.sampler"
        else:
            yield from sampler_health(sampler, f"{path}.sampler")
    if attach:
        environment = value.get("environment")
        provenance = environment.get("attach") if isinstance(environment, dict) else None
        yield from attach_provenance(provenance, f"{path}.environment.attach")
        if value.get("hostKind") != "headless Chrome":
            yield f"attachProvenance.hostKind at {path}.hostKind"


STAGE_MAP_FIELDS = {
    "s": lambda v: _finite(v) and v > 0, "sy": lambda v: _finite(v) and v > 0, "ox": _finite, "oy": _finite,
    "offsetWidth": _id, "offsetHeight": _id,
}


def stage_map(value: Any, path: str) -> Iterator[str]:
    """`STAGE_MAP_FN_JS`: null, or `{s, sy}` finite > 0, `{ox, oy}` finite, `{offsetWidth, offsetHeight}` int >= 1."""
    if value is None:
        return
    if not isinstance(value, dict):
        yield f"stageMap:object at {path}"
        return
    yield from _fields(value, "stageMap", path, STAGE_MAP_FIELDS)


def owner(value: Any, path: str) -> Iterator[str]:
    """`footprintOwnerDecoderId`: `{elId, key, via, contextType: null}`; a `footprint-video` owner names a non-empty
    `key` and an `elId` int >= 1, absent when the owner is untagged; every other `via` names neither."""
    if value is None:
        return
    if not isinstance(value, dict):
        yield f"owner:object at {path}"
        return
    if value.get("via") not in OWNER_VIAS:
        yield f"owner.via at {path}"
        return
    if "contextType" not in value or value["contextType"] is not None:
        yield f"owner.contextType at {path}"
    if value["via"] == "footprint-video":
        if not _non_empty_str(value.get("key")):
            yield f"owner.key at {path}"
        if "elId" in value and not _id(value["elId"]):
            yield f"owner.elId at {path}"
    elif "elId" not in value or "key" not in value or value["elId"] is not None or value["key"] is not None:
        yield f"owner:unresolved names a decoder at {path}"


DECODER_FIELDS = {
    "id": _id, "elId": _id_or_null, "src": lambda v: isinstance(v, str),
    "currentTime": lambda v: _finite(v) and v >= 0, "readyState": _ready_state, "videoWidth": _count,
    "isConnected": lambda v: v is True, "paused": lambda v: isinstance(v, bool),
}
DECODER_G2_FIELDS = {"ended": lambda v: isinstance(v, bool), "loop": lambda v: isinstance(v, bool),
                     "duration": lambda v: v is None or _finite(v) and v > 0}
DECODER_G3_FIELDS = {"domId": lambda v: v is None or _non_empty_str(v), "facade": lambda v: isinstance(v, bool),
                     "preserved": lambda v: isinstance(v, bool), "remounted": lambda v: isinstance(v, bool)}


def decoder(value: Any, path: str, converted: bool | None) -> Iterator[str]:
    """One `videos[]` row: exactly one generation's keys (plus the conversion keys on a converted row); `converted` is
    the row's `stageMapValid`, None on a raw row."""
    if not isinstance(value, dict):
        yield f"decoder:object at {path}"
        return
    keys = frozenset(value) - CONVERSION_KEYS
    if keys not in DECODER_GENERATIONS:
        yield f"decoder:generation at {path}"
        return
    yield from _fields(value, "decoder", path, DECODER_FIELDS)
    if "ended" in keys:
        yield from _fields(value, "decoder", path, DECODER_G2_FIELDS)
    if "domId" in keys:
        yield from _fields(value, "decoder", path, DECODER_G3_FIELDS)
    if "instance" in keys and not _str_or_null(value["instance"]):
        yield f"decoder.instance at {path}"
    if converted is None:
        if CONVERSION_KEYS & set(value):
            yield f"decoder:conversion keys on a raw row at {path}"
        if not _box(value["rect"]):
            yield f"decoder.rect at {path}"
    else:
        if value.get("stageMapValid") is not converted:
            yield f"decoder.stageMapValid at {path}"
        if not _box(value.get("rectScreen")):
            yield f"decoder.rectScreen at {path}"
        if not (value["rect"] is None if converted is False else _box(value["rect"])):
            yield f"decoder.rect at {path}"
    yield from owner(value["footprintOwner"], f"{path}.footprintOwner")


def _hiding(value: Any) -> bool:
    if value is None:
        return True
    if not (isinstance(value, dict) and isinstance(value.get("node"), str)):
        return False
    if value.get("prop") == "display":
        return value.get("value") == "none"
    return value.get("prop") == "opacity" and _finite(value.get("value"))


PV_FIELDS = {
    "id": _id_or_null, "elId": _id_or_null, "instance": _str_or_null, "src": lambda v: isinstance(v, str),
    "connected": lambda v: isinstance(v, bool), "facade": lambda v: isinstance(v, bool),
    "suppressed": lambda v: isinstance(v, bool), "seeking": lambda v: isinstance(v, bool),
    "paused": lambda v: isinstance(v, bool), "ended": lambda v: isinstance(v, bool),
    "readyState": _ready_state, "videoWidth": _count, "videoHeight": _count,
    "currentTime": lambda v: _finite(v) and v >= 0, "rect": _box, "parent": _str_or_null, "layer": _str_or_null,
}
PV_CONNECTED_FIELDS = {
    "checkVisibility": lambda v: isinstance(v, bool), "visibility": lambda v: v in CSS_VISIBILITY,
    "opacity": lambda v: v is None or _finite(v) and 0 <= v <= 1, "hiding": _hiding,
    "visibleRect": lambda v: v is None or _box(v, 0), "displayNone": _str_or_null, "effects": _str_or_null,
    "transform": _str_or_null, "clippedBy": _str_or_null,
}


def pv(value: Any, path: str) -> Iterator[str]:
    """`paintReadOf`: one pre-paint decoder read (`*Screen` twins after conversion read as their originals)."""
    if not isinstance(value, dict):
        yield f"pv:object at {path}"
        return
    yield from _fields(value, "pv", path, PV_FIELDS)
    if "rectScreen" in value and not _box(value["rectScreen"]):
        yield f"pv.rectScreen at {path}"
    if "visibleRectScreen" in value and not (value["visibleRectScreen"] is None or _box(value["visibleRectScreen"], 0)):
        yield f"pv.visibleRectScreen at {path}"
    if value.get("connected") is False:
        if any(value.get(key, True) is not None for key in PV_CONNECTED_ONLY):
            yield f"pv:disconnected read carries style at {path}"
    elif value.get("connected") is True:
        yield from _fields(value, "pv", path, PV_CONNECTED_FIELDS)


PP_FIELDS = {"seq": _id, "ts": _finite, "t": _finite, "videos": lambda v: isinstance(v, list),
             "cover": lambda v: isinstance(v, bool), "stageBox": lambda v: v is None or _box(v)}


def pp(value: Any, path: str, row: dict[str, Any]) -> Iterator[str]:
    """The ResizeObserver's pre-paint read of `row`'s frame: same `seq` and `ts`, read no earlier than the row."""
    if not isinstance(value, dict):
        yield f"pp:object at {path}"
        return
    yield from _fields(value, "pp", path, PP_FIELDS)
    if "stageMap" not in value:
        yield f"pp.stageMap:missing at {path}"
    else:
        yield from stage_map(value["stageMap"], f"{path}.stageMap")
    if "stageBoxScreen" in value and not (value["stageBoxScreen"] is None or _box(value["stageBoxScreen"])):
        yield f"pp.stageBoxScreen at {path}"
    if value.get("seq") != row.get("seq") or value.get("ts") != row.get("ts"):
        yield f"pp:frame is not the row's at {path}"
    if _finite(value.get("t")) and _finite(row.get("t")) and value["t"] < row["t"]:
        yield f"pp:read before the row at {path}"
    if not isinstance(value.get("videos"), list):
        return
    for index, entry in enumerate(value["videos"]):
        yield from pv(entry, f"{path}.videos[{index}]")
    entries = [e for e in value["videos"] if isinstance(e, dict)]
    yield from _unique([e["id"] for e in entries if _id(e.get("id"))], "pp:duplicate id", path)
    yield from _unique([e["elId"] for e in entries if _id(e.get("elId"))], "pp:duplicate elId", path)


ROW_FIELDS = {"t": _finite, "videos": lambda v: isinstance(v, list)}
ROW_RUNTIME_FIELDS = {"scene": lambda v: v is None or _count(v), "playerState": lambda v: v in PLAYER_STATES,
                      "busy": lambda v: isinstance(v, bool)}
ROW_S2_FIELDS = {"seq": _id, "ts": _finite, "hash": lambda v: isinstance(v, str),
                 "sceneCount": lambda v: v is None or _count(v)}


def sample_rows(rows: Any, *, schema: Any = None, path: str = "samples") -> Iterator[str]:
    """`SAMPLER_JS` rows, raw or after `convert_samples_to_authored`. One sampler schema and one decoder generation
    per stream, schema 2 iff the sampler reported it; `t` non-decreasing and (schema 2) `ts` strictly increasing; a
    probe id's `elId` is null until tagged, then one int that no other probe id carries."""
    if not isinstance(rows, list):
        yield f"rows:list at {path}"
        return
    schemas: set[bool] = set()
    generations: set[frozenset[str]] = set()
    el_ids: dict[Any, Any] = {}
    probe_ids: dict[Any, Any] = {}
    prev_t = prev_ts = None
    for index, row in enumerate(rows):
        where = f"{path}[{index}]"
        if not isinstance(row, dict):
            yield f"row:object at {where}"
            continue
        yield from _fields(row, "row", where, ROW_FIELDS)
        present = [key in row for key in RUNTIME_KEYS]
        if all(present):
            yield from _fields(row, "row", where, ROW_RUNTIME_FIELDS)
        elif any(present):
            yield f"row:runtime state partly absent at {where}"
        if "nextSceneId" in row and not (row["nextSceneId"] is None or _count(row["nextSceneId"])):
            yield f"row.nextSceneId at {where}"
        if "stageMap" not in row:
            yield f"row.stageMap:missing at {where}"
        else:
            yield from stage_map(row["stageMap"], f"{where}.stageMap")
        v2 = "seq" in row
        schemas.add(v2)
        if v2:
            yield from _fields(row, "row", where, ROW_S2_FIELDS)
            if _finite(row.get("ts")):
                if prev_ts is not None and row["ts"] <= prev_ts:
                    yield f"row:ts not increasing at {where}"
                prev_ts = row["ts"]
            if "pp" in row:
                yield from pp(row["pp"], f"{where}.pp", row)
            if "ppUnreadable" in row:
                yield from pp(row["ppUnreadable"], f"{where}.ppUnreadable", row)
        elif any(key in row for key in (*S2_ROW_KEYS, "pp", "ppUnreadable")):
            yield f"row:schema-2 keys without seq at {where}"
        if "rafTs" in row and row["rafTs"] != row.get("ts"):
            yield f"row.rafTs at {where}"
        if _finite(row.get("t")):
            if prev_t is not None and row["t"] < prev_t:
                yield f"row:t decreasing at {where}"
            prev_t = row["t"]
        converted = None
        if "stageMapValid" in row:
            converted = stage_map_valid(row.get("stageMap"))
            if row["stageMapValid"] is not converted:
                yield f"row.stageMapValid at {where}"
        if not isinstance(row.get("videos"), list):
            continue
        ids, els = [], []
        for vindex, video in enumerate(row["videos"]):
            vwhere = f"{where}.videos[{vindex}]"
            yield from decoder(video, vwhere, converted)
            if not isinstance(video, dict):
                continue
            keys = frozenset(video) - CONVERSION_KEYS
            if keys in DECODER_GENERATIONS:
                generations.add(keys)
            if row.get("stageMap") is None and video.get("footprintOwner") is not None:
                yield f"row:owner without a stage map at {vwhere}"
            vid, el = video.get("id"), video.get("elId")
            if _id(vid):
                ids.append(vid)
                if el is None and _id(el_ids.get(vid)):
                    yield f"row:elId untagged after tagging at {vwhere}"
                elif _id(el):
                    if el_ids.setdefault(vid, el) != el:
                        yield f"row:elId changed at {vwhere}"
                    if probe_ids.setdefault(el, vid) != vid:
                        yield f"row:elId under another id at {vwhere}"
            if _id(el):
                els.append(el)
        yield from _unique(ids, "row:duplicate id", where)
        yield from _unique(els, "row:duplicate elId", where)
    if len(schemas) > 1:
        yield f"rows:mixed sampler schemas at {path}"
    if schemas and (schemas == {True}) != (schema == paint_instrument.SAMPLER_SCHEMA):
        yield f"rows:schema at {path} (sampler schema {schema!r})"
    if len(generations) > 1:
        yield f"rows:mixed decoder generations at {path}"


PAINTING_FIELDS = {"src": lambda v: isinstance(v, str), "elId": _id_or_null, "rect": lambda v: _box(v, 1)}


def painting(value: Any, path: str) -> Iterator[str]:
    """`PAINTING_VIDEOS_JS`: `{error}`, or painting decoders with a rect over 1 px and unique non-null `elId`s."""
    if _error_read(value):
        return
    if not isinstance(value, list):
        yield f"painting:list at {path}"
        return
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            yield f"painting:object at {path}[{index}]"
            continue
        yield from _fields(entry, "painting", f"{path}[{index}]", PAINTING_FIELDS)
    yield from _unique([e["elId"] for e in value if isinstance(e, dict) and _id(e.get("elId"))],
                       "painting:duplicate elId", path)


POOL_FIELDS = {
    "key": lambda v: isinstance(v, str), "movieKey": _str_or_null, "elId": _id, "currentTime": _finite,
    "paused": lambda v: isinstance(v, bool), "ended": lambda v: isinstance(v, bool),
    "inDocument": lambda v: isinstance(v, bool), "readyState": _ready_state, "videoWidth": _count,
    "videoHeight": _count,
}


def pool(value: Any, path: str) -> Iterator[str]:
    """The core's `snapshot()`: null, `{error}`, or pool entries then `fromDom` entries. `instance` is on every entry
    or none; an empty `key` only on a `fromDom` entry (a cleared src), which keeps its movie stamp; `elId` unique
    within each half."""
    if value is None or _error_read(value):
        return
    if not isinstance(value, list):
        yield f"pool:list at {path}"
        return
    instances = set()
    for index, entry in enumerate(value):
        where = f"{path}[{index}]"
        if not isinstance(entry, dict):
            yield f"pool:object at {where}"
            continue
        yield from _fields(entry, "pool", where, POOL_FIELDS)
        instances.add("instance" in entry)
        if "instance" in entry and not (entry["instance"] is None or _non_empty_str(entry["instance"])):
            yield f"pool.instance at {where}"
        if "fromDom" in entry and entry["fromDom"] is not True:
            yield f"pool.fromDom at {where}"
        if entry.get("key") == "" and "fromDom" not in entry:
            yield f"pool:empty key off the DOM at {where}"
        elif entry.get("key") == "" and entry.get("movieKey") is None:
            yield f"pool:empty key without its movie stamp at {where}"
    if len(instances) > 1:
        yield f"pool:instance on some entries at {path}"
    entries = [e for e in value if isinstance(e, dict) and _id(e.get("elId"))]
    for from_dom in (False, True):
        yield from _unique([e["elId"] for e in entries if ("fromDom" in e) is from_dom],
                           f"pool:duplicate elId{' fromDom' if from_dom else ''}", path)


NOTE_IDENTITY = {
    "elId": _id, "newElId": _id, "oldElId": _id,
    "elIds": lambda v: isinstance(v, list) and bool(v) and all(_id(x) for x in v),
    "key": _str_or_null, "movieKey": _str_or_null, "instance": _str_or_null, "src": _str_or_null, "dst": _str_or_null,
}
NOTE_PAYLOADS: dict[str, dict[str, Any]] = {
    "glreplay-carried": {"elId": _id, "delta": lambda v: _finite(v) and 0 <= v <= 1},
    "glreplay-release": {"ok": lambda v: isinstance(v, bool), "mode": lambda v: v in ("retire", "handoff", None),
                         "retired": lambda v: isinstance(v, list) and all(_id(x) for x in v)},
    "glreplay-zone": {"key": lambda v: isinstance(v, str), "from": lambda v: v in ZONE_FROM,
                      "to": lambda v: v in ZONE_TO, "reason": lambda v: isinstance(v, str)},
    "remount-done": {"elId": _id},
    "remount-footprint-rect": {"elId": _id},
    "preserve-refused": {"scene": lambda v: v is None or _int(v), "via": lambda v: v in REFUSE_VIAS},
    "retire-boundary": {"key": lambda v: isinstance(v, str), "elIds": NOTE_IDENTITY["elIds"], "atScene": _int},
    "reuse-decoder": {"key": lambda v: isinstance(v, str), "src": lambda v: isinstance(v, str),
                      "dst": lambda v: isinstance(v, str), "newElId": _id, "oldElId": _id},
    "bridge-motion-start": {"durationSeconds": lambda v: _finite(v) and v > 0, "srcRect": _box, "rect": _box},
    "bridge-clock": {"via": lambda v: v in ("gl", "fallback"), "lagMs": _finite},
    "player-build-error": {"errorType": lambda v: v in ("error", "unhandledrejection"),
                           "message": lambda v: isinstance(v, str)},
    "poster-hold": {"elId": _id, "objectId": _non_empty_str,
                    "t": lambda v: _finite(v) and v >= 0, "reason": _str_or_null},
    "poster-resume": {"elId": _id, "t": lambda v: _finite(v) and v >= 0},
    "mm-feed-claim": {"objectId": _non_empty_str, "mode": lambda v: v == "continuous"},
    "mm-feed-stand-down": {"objectId": _non_empty_str, "reason": _non_empty_str,
                            "usableContext": lambda v: isinstance(v, bool),
                            "boundTextures": lambda v: isinstance(v, bool)},
}
NOTE_PAYLOADS["bridge-3to4"] = NOTE_PAYLOADS["reuse-decoder"]


def _note_detail(kind: str, detail: dict[str, Any], path: str) -> Iterator[str]:
    for key, valid in NOTE_IDENTITY.items():
        if key not in detail:
            continue
        if key == "elId" and kind == "glreplay-release" and detail[key] is None:
            continue
        if not valid(detail[key]):
            yield f"note.{key} at {path}"
    yield from _fields(detail, kind, path, NOTE_PAYLOADS.get(kind, {}))
    if kind == "glreplay-release" and detail.get("mode") == "handoff" \
            and not (detail.get("ok") is True and _id(detail.get("elId"))):
        yield f"glreplay-release:handoff without ok and its elId at {path}"
    if kind == "retire-boundary" and "instance" in detail and not isinstance(detail["instance"], str):
        yield f"retire-boundary.instance at {path}"
    if kind == "bridge-clock" and detail.get("via") == "fallback" and _finite(detail.get("lagMs")) \
            and detail["lagMs"] < BRIDGE_CLOCK_FALLBACK_MIN_MS:
        yield f"bridge-clock:fallback before its wait at {path}"


def notes(value: Any, path: str, kinds: re.Pattern[str] | None = None, *, module: bool = False,
          readable: bool = True) -> Iterator[str]:
    """A note list: `{kind, detail, t}` in non-decreasing `t`, each kind within the read's filter; a core note's
    detail carries its `sceneHash` (a module event's does not). `readable` admits the producers' null and `{error}`."""
    if readable and (value is None or _error_read(value)):
        return
    if not isinstance(value, list):
        yield f"notes:list at {path}"
        return
    prev = None
    for index, note in enumerate(value):
        where = f"{path}[{index}]"
        if not (isinstance(note, dict) and _non_empty_str(note.get("kind")) and isinstance(note.get("detail"), dict)
                and _finite(note.get("t"))):
            yield f"note:envelope at {where}"
            continue
        if kinds is not None and not kinds.search(note["kind"]):
            yield f"note:kind outside the read's filter at {where}"
        if not module and not isinstance(note["detail"].get("sceneHash"), str):
            yield f"note.sceneHash at {where}"
        if prev is not None and note["t"] < prev:
            yield f"note:t decreasing at {where}"
        prev = note["t"]
        yield from _note_detail(note["kind"], note["detail"], f"{where}.detail")


API_STATS_FIELDS = {"epoch": _int, "iter": _int, "uploads": _int, "glErrors": _int}


def api(value: Any, path: str) -> Iterator[str]:
    """`window.__OBED_GL_REPLAY__` as read: null, `{error}`, or version 1 with a known state, its stand-downs (none
    before a stand-down, at least one once RETIRED), its events and its stats."""
    if value is None or _error_read(value):
        return
    if not isinstance(value, dict):
        yield f"api:object at {path}"
        return
    if value.get("version") != 1:
        yield f"api.version at {path}"
    if value.get("state") not in GL_STATES:
        yield f"api.state at {path}"
    downs = value.get("standDowns")
    if not (isinstance(downs, list) and all(isinstance(d, str) for d in downs)):
        yield f"api.standDowns at {path}"
    elif value.get("state") == "RETIRED" and not downs:
        yield f"api:retired without a stand-down at {path}"
    elif value.get("state") in ("IDLE", "ARM-PRE", "ARM-POST", "LIVE") and downs:
        yield f"api:stand-down before STANDDOWN at {path}"
    if "events" not in value:
        yield f"api.events:missing at {path}"
    else:
        yield from notes(value["events"], f"{path}.events", module=True, readable=False)
    if "stats" not in value:
        yield f"api.stats:missing at {path}"
    elif value["stats"] is not None:
        if not isinstance(value["stats"], dict):
            yield f"api.stats at {path}"
        else:
            yield from _fields(value["stats"], "api.stats", f"{path}.stats", API_STATS_FIELDS)


GL_READ_FIELDS = {"t": _finite, "hash": lambda v: isinstance(v, str), "ready": lambda v: v is None or isinstance(v, bool)}


def gl_read(value: Any, path: str) -> Iterator[str]:
    """`GL_REPLAY_READ_JS`."""
    if not isinstance(value, dict):
        yield f"gl:object at {path}"
        return
    yield from _fields(value, "gl", path, GL_READ_FIELDS)
    for key, check in (("api", api), ("pool", pool)):
        if key not in value:
            yield f"gl.{key}:missing at {path}"
        else:
            yield from check(value[key], f"{path}.{key}")
    if "coreEvents" not in value:
        yield f"gl.coreEvents:missing at {path}"
    else:
        yield from notes(value["coreEvents"], f"{path}.coreEvents", GL_NOTE_KINDS)
    facades = value.get("facades")
    if not (isinstance(facades, list) and all(
        isinstance(f, dict) and "elId" in f and "forElId" in f and _id_or_null(f["elId"]) and _id_or_null(f["forElId"])
        for f in facades
    )):
        yield f"gl.facades at {path}"


def _read_parts(value: dict[str, Any], path: str) -> Iterator[str]:
    for key in ("stageMap", "painting"):
        if key not in value:
            yield f"read.{key}:missing at {path}"
    yield from stage_map(value.get("stageMap"), f"{path}.stageMap")
    if "painting" in value:
        yield from painting(value["painting"], f"{path}.painting")
    if "poolSnapshot" in value:
        yield from pool(value["poolSnapshot"], f"{path}.poolSnapshot")


def refusal_read(value: Any, path: str) -> Iterator[str]:
    """`refusal_evidence` plus `CORE_EVENTS_JS` (a census read carries only the stage map and painting)."""
    if not isinstance(value, dict):
        yield f"read:object at {path}"
        return
    yield from _read_parts(value, path)
    if "coreEvents" in value:
        yield from notes(value["coreEvents"], f"{path}.coreEvents", REFUSAL_NOTE_KINDS)


def armed_reads(value: Any, path: str) -> Iterator[str]:
    """`armed_evidence`: exactly two reads with a GL read each, or `{reason}` when the hash never settled."""
    if isinstance(value, dict) and set(value) == {"reason"} and isinstance(value["reason"], str):
        return
    if not (isinstance(value, list) and len(value) == 2):
        yield f"armed:two reads at {path}"
        return
    for index, read in enumerate(value):
        where = f"{path}[{index}]"
        if not isinstance(read, dict):
            yield f"read:object at {where}"
            continue
        yield from _read_parts(read, where)
        if "poolSnapshot" not in read:
            yield f"read.poolSnapshot:missing at {where}"
        if "glReplay" not in read:
            yield f"read.glReplay:missing at {where}"
        else:
            yield from gl_read(read["glReplay"], f"{where}.glReplay")


def evidence(value: Any, path: str = "evidence") -> Iterator[str]:
    """Every boundary-observer value: armed reads (a list, or `{reason}`) or a refusal read."""
    if not isinstance(value, dict):
        yield f"evidence:object at {path}"
        return
    for key, item in value.items():
        where = f"{path}.{key}"
        if isinstance(item, list) or isinstance(item, dict) and set(item) == {"reason"}:
            yield from armed_reads(item, where)
        else:
            yield from refusal_read(item, where)


MM_FEED_CONTEXT_FIELDS = {
    "serial": _id, "id": _non_empty_str, "createdAt": _finite,
    "closedAt": lambda v: v is None or _finite(v), "atScene": lambda v: v is None or _count(v),
    "lost": lambda v: isinstance(v, bool),
    "entryIds": lambda v: isinstance(v, list) and all(_non_empty_str(item) for item in v),
}
MM_FEED_DOM_FIELDS = {
    "connected": lambda v: isinstance(v, bool), "inStage": lambda v: isinstance(v, bool),
    "onBody": lambda v: isinstance(v, bool), "shown": lambda v: isinstance(v, bool),
    "opacityProduct": lambda v: _finite(v) and v >= 0, "canvasCount": _count,
    "afterCanvas": lambda v: v is None or isinstance(v, bool),
    "sameStackingContext": lambda v: v is None or isinstance(v, bool), "rectError": lambda v: _finite(v) and v >= 0,
}
MM_FEED_TEXTURE_FIELDS = {
    "unit": lambda v: _int(v) and v in (0, 1), "ordinal": _count,
    "size": lambda v: isinstance(v, list) and len(v) == 2 and all(_count(n) for n in v),
    "video": lambda v: isinstance(v, bool), "flip": lambda v: isinstance(v, bool),
}
MM_FEED_DECODER_FIELDS = {
    "objectId": _non_empty_str, "elId": _id_or_null, "currentTime": lambda v: _finite(v) and v >= 0,
    "paused": lambda v: isinstance(v, bool), "readyState": _ready_state,
    "opacityProduct": lambda v: _finite(v) and v >= 0, "visible": lambda v: isinstance(v, bool),
    "instance": _str_or_null,
}


def _mm_feed_texture(value: Any, path: str) -> Iterator[str]:
    if value is None:
        return
    if not isinstance(value, dict):
        yield f"mmFeed.texture:object at {path}"
        return
    yield from _fields(value, "mmFeed.texture", path, MM_FEED_TEXTURE_FIELDS)
    if value.get("uploadedSize") is not None and not (
        isinstance(value["uploadedSize"], list) and len(value["uploadedSize"]) == 2
        and all(_count(n) for n in value["uploadedSize"])
    ):
        yield f"mmFeed.texture.uploadedSize at {path}"
    for key in ("presentedFrames", "mediaTime"):
        if key in value and value[key] is not None and not _finite(value[key]):
            yield f"mmFeed.texture.{key} at {path}"


def _mm_feed_decoder(value: Any, path: str) -> Iterator[str]:
    if value is None:
        return
    if not isinstance(value, dict):
        yield f"mmFeed.decoder:object at {path}"
        return
    yield from _fields(value, "mmFeed.decoder", path, MM_FEED_DECODER_FIELDS)
    for key in ("presentedFrames", "mediaTime"):
        if key in value and value[key] is not None and not _finite(value[key]):
            yield f"mmFeed.decoder.{key} at {path}"


def _counter_read(levels: Any, counter: Any, reason: Any, counter_layout: Any, path: str) -> Iterator[str]:
    blocks = counter_layout.get("blockRects") if isinstance(counter_layout, dict) else None
    if not isinstance(levels, list) or not isinstance(blocks, list):
        return
    if len(levels) == len(blocks):
        decoded = binary_counter_movie.decode_counter(levels, counter_layout)
        if decoded["counter"] != counter or decoded["reason"] != reason:
            yield f"mmFeed.counterBinding at {path}"
    elif reason is not None and counter is not None:
        yield f"mmFeed.counterBinding at {path}"


def mm_feed_report(value: Any, path: str = "mmFeedEvidence") -> Iterator[str]:
    """`mm_feed_instrument.INSTRUMENT_JS` report and its decoder/GL frame producers."""
    if not isinstance(value, dict):
        yield f"mmFeed:object at {path}"
        return
    version = value.get("version")
    config = value.get("config")
    counter_layout = config.get("counterLayout") if isinstance(config, dict) else None
    counter_blocks = counter_layout.get("blockRects") if isinstance(counter_layout, dict) else None
    strict_counter = "sampling" in value or isinstance(config, dict) and "counterLayout" in config
    if value.get("kind") != "mm-feed" or version not in (1, 2, 3):
        yield f"mmFeed:version at {path}"
    lists = ("contexts", "frames", "media", "mediaDropped", "artwork", "errors", "killedOnce", "uploads", "claims", "standDowns", "departures")
    if version in (2, 3):
        lists = (*lists, "browserFrames", "handbacks")
    for key in lists:
        if not isinstance(value.get(key), list):
            yield f"mmFeed.{key}:list at {path}"
    if not _count(value.get("mediaOverflow")):
        yield f"mmFeed.mediaOverflow at {path}"
    if version == 3 and not _count(value.get("unplannedContextCount")):
        yield f"mmFeed.unplannedContextCount at {path}"
    if version == 3:
        yield from feed_hook_health(value.get("hookHealth"), f"{path}.hookHealth")
        if "instrumentVariant" in value and value["instrumentVariant"] != "calibration-red":
            yield f"mmFeed.instrumentVariant at {path}"
    if value.get("callbackCostP95Ms") is not None and not (_finite(value.get("callbackCostP95Ms")) and value["callbackCostP95Ms"] >= 0):
        yield f"mmFeed.callbackCostP95Ms at {path}"
    if strict_counter:
        if not isinstance(counter_layout, dict):
            yield f"mmFeed.counterLayout:object at {path}.config.counterLayout"
        else:
            yield from _fields(counter_layout, "mmFeed.counterLayout", f"{path}.config.counterLayout", {
                "format": lambda v: v == "binary-counter-v1",
                "sourceSize": lambda v: isinstance(v, list) and len(v) == 2 and all(_count(n) for n in v),
                "blockRects": lambda v: isinstance(v, list) and bool(v) and all(
                    isinstance(rect, list) and len(rect) == 4 and all(_finite(n) for n in rect) for rect in v
                ),
                "dataBits": lambda v: _finite(v) and v > 0 and int(v) == v,
                "start": lambda v: isinstance(v, list) and bool(v) and all(n in (0, 1) for n in v),
                "end": lambda v: isinstance(v, list) and bool(v) and all(n in (0, 1) for n in v),
                "parity": lambda v: v == "even",
                "minContrast": lambda v: _finite(v) and v > 0,
                "ambiguousRatio": lambda v: _finite(v) and 0 <= v < .5,
            })
            if isinstance(counter_blocks, list) and isinstance(counter_layout.get("start"), list) \
                    and isinstance(counter_layout.get("end"), list) \
                    and _finite(counter_layout.get("dataBits")) and counter_layout["dataBits"] > 0 \
                    and int(counter_layout["dataBits"]) == counter_layout["dataBits"] \
                    and len(counter_blocks) != len(counter_layout["start"]) + int(counter_layout["dataBits"]) + 1 \
                    + len(counter_layout["end"]):
                yield f"mmFeed.counterLayout.blockRects at {path}.config.counterLayout"
        sampling = value.get("sampling")
        if not isinstance(sampling, dict):
            yield f"mmFeed.sampling:object at {path}"
        else:
            yield from _fields(sampling, "mmFeed.sampling", f"{path}.sampling", {
                "width": lambda v: v == 192,
                "referenceCapacity": lambda v: v == 18,
                "entries": lambda v: isinstance(v, dict),
            })
            sampling_entries = sampling.get("entries") if isinstance(sampling.get("entries"), dict) else {}
            reasons = (None, "bounds", "marker", "ambiguous", "parity", "layout", "read", "source")
            for entry_id, entry in sampling_entries.items():
                where = f"{path}.sampling.entries[{entry_id!r}]"
                if not isinstance(entry, dict):
                    yield f"mmFeed.sampling.entry:object at {where}"
                else:
                    yield from _fields(entry, "mmFeed.sampling.entry", where, {
                        "references": lambda v: _count(v) and v <= 18,
                        "latestFrame": lambda v: v is None or _count(v),
                        "latestCounter": lambda v: v is None or _count(v),
                        "latestLevels": lambda v: isinstance(v, list) and all(_finite(level) for level in v),
                        "latestReason": lambda v: v in reasons,
                    })
                    levels, reason = entry.get("latestLevels"), entry.get("latestReason")
                    if isinstance(levels, list) and isinstance(counter_blocks, list) \
                            and len(levels) != len(counter_blocks) \
                            and not (not levels and (
                                reason in ("bounds", "layout", "read", "source")
                                or entry.get("references") == 0 and entry.get("latestFrame") is None and reason is None
                            )):
                        yield f"mmFeed.sampling.entry.latestLevels at {where}"
                    yield from _counter_read(
                        levels, entry.get("latestCounter"), reason, counter_layout,
                        f"{where}.latestLevels",
                    )
    contexts_by_serial = {}
    for index, context in enumerate(value.get("contexts") or []):
        where = f"{path}.contexts[{index}]"
        if not isinstance(context, dict):
            yield f"mmFeed.context:object at {where}"
        else:
            contexts_by_serial[context.get("serial")] = context
            yield from _fields(context, "mmFeed.context", where, MM_FEED_CONTEXT_FIELDS)
            yield from _fields(context, "mmFeed.context", where, {
                "firstDrawAt": lambda v: v is None or _finite(v),
            })
            if version == 3:
                yield from _fields(context, "mmFeed.context", where, {
                    "evidenceComplete": lambda v: isinstance(v, bool),
                })
            if _finite(context.get("firstDrawAt")) and _finite(context.get("createdAt")) \
                    and context["firstDrawAt"] < context["createdAt"]:
                yield f"mmFeed.context.firstDrawAt at {where}"
            if context.get("atScene") is None and (version != 2 or context.get("entryIds") != []):
                yield f"mmFeed.context.atScene at {where}"
            if version in (2, 3) and not (context.get("closedFrameIndex") is None or _count(context.get("closedFrameIndex"))):
                yield f"mmFeed.context.closedFrameIndex at {where}"
    previous = None
    for index, frame in enumerate(value.get("frames") or []):
        where = f"{path}.frames[{index}]"
        if not isinstance(frame, dict):
            yield f"mmFeed.frame:object at {where}"
            continue
        yield from _fields(frame, "mmFeed.frame", where, {
            "serial": _id, "atScene": lambda v: v is None or _count(v), "n": _id, "t": _finite, "frameTime": _finite,
            "draws": _count, "uploads": _count,
            "rows": lambda v: isinstance(v, list), "labels": lambda v: isinstance(v, list),
            "riders": lambda v: isinstance(v, list), "labelExpected": lambda v: isinstance(v, list),
            "glErrors": lambda v: isinstance(v, list) and all(_int(e) for e in v),
        })
        if frame.get("atScene") is None:
            context = contexts_by_serial.get(frame.get("serial"))
            empty = all(frame.get(key) == [] for key in ("rows", "labels", "riders", "labelExpected"))
            if version != 2 or not isinstance(context, dict) or context.get("atScene") is not None \
                    or context.get("entryIds") != [] or not empty:
                yield f"mmFeed.frame.atScene at {where}"
        if version in (2, 3):
            yield from _fields(frame, "mmFeed.frame", where, {"frameIndex": _count, "frameTimestamp": _finite})
        if previous is not None and _finite(frame.get("t")) and frame["t"] < previous:
            yield f"mmFeed.frame:t decreasing at {where}"
        if _finite(frame.get("t")):
            previous = frame["t"]
        for rindex, row in enumerate(frame.get("rows") or []):
            rwhere = f"{where}.rows[{rindex}]"
            if not isinstance(row, dict):
                yield f"mmFeed.row:object at {rwhere}"
                continue
            yield from _fields(row, "mmFeed.row", rwhere, {
                "entryId": _non_empty_str, "objectId": _non_empty_str, "dstObjectId": _non_empty_str,
                "serial": _id, "atScene": _count, "draw": _id, "t": _finite,
                "textures": lambda v: isinstance(v, list) and len(v) == 2,
                "feedRead": lambda v: isinstance(v, dict),
            })
            yield from _mm_feed_decoder(row.get("decoder"), f"{rwhere}.decoder")
            for tindex, texture in enumerate(row.get("textures") or []):
                yield from _mm_feed_texture(texture, f"{rwhere}.textures[{tindex}]")
            read = row.get("feedRead")
            if isinstance(read, dict):
                yield from _fields(read, "mmFeed.feedRead", f"{rwhere}.feedRead", {
                    "patchInside": lambda v: isinstance(v, bool),
                    "coveredByLaterDraw": lambda v: isinstance(v, bool),
                    "kind": lambda v: v is None or v in ("counter", "alpha"),
                })
                fields = ("counter", "referenceCounter") if read.get("kind") == "counter" else (
                    "dVideo", "dPoster", "dSep"
                ) if read.get("kind") == "alpha" else ()
                yield from _fields(read, "mmFeed.feedRead", f"{rwhere}.feedRead", {
                    key: lambda v: v is None or _finite(v) for key in fields
                })
                if strict_counter and read.get("kind") in ("counter", "alpha"):
                    reasons = (None, "bounds", "marker", "ambiguous", "parity", "layout", "read", "source")
                    yield from _fields(read, "mmFeed.feedRead", f"{rwhere}.feedRead", {
                        "referenceCounter": lambda v: v is None or _count(v),
                        "referenceLevels": lambda v: isinstance(v, list) and all(_finite(level) for level in v),
                        "referenceReason": lambda v: v in reasons,
                    })
                    if read.get("kind") == "counter":
                        yield from _fields(read, "mmFeed.feedRead", f"{rwhere}.feedRead", {
                            "counterLevels": lambda v: isinstance(v, list) and all(_finite(level) for level in v),
                            "counterReason": lambda v: v in reasons,
                        })
                    for prefix in ("counter", "reference"):
                        levels = read.get(f"{prefix}Levels")
                        reason = read.get(f"{prefix}Reason")
                        if isinstance(levels, list) and isinstance(counter_blocks, list) \
                                and len(levels) != len(counter_blocks) and not (not levels and reason in ("bounds", "layout", "read", "source")):
                            yield f"mmFeed.feedRead.{prefix}Levels at {rwhere}.feedRead"
                        yield from _counter_read(
                            levels, read.get(prefix if prefix == "counter" else "referenceCounter"), reason,
                            counter_layout, f"{rwhere}.feedRead.{prefix}Levels",
                        )
                if read.get("kind") is None and read.get("late") is not True:
                    yield f"mmFeed.feedRead.late at {rwhere}.feedRead"
            match = row.get("holdMatch")
            if match is not None:
                if not isinstance(match, dict):
                    yield f"mmFeed.holdMatch:object at {rwhere}.holdMatch"
                else:
                    yield from _fields(match, "mmFeed.holdMatch", f"{rwhere}.holdMatch", {
                        "kind": lambda v: v in ("counter", "alpha"), "bestFrame": _count,
                        "matchDistance": lambda v: _finite(v) and v >= 0, "matchMargin": _finite,
                    })
                    if "matches" in match:
                        yield from _fields(match, "mmFeed.holdMatch", f"{rwhere}.holdMatch", {
                            "targetFrame": lambda v: v is None or _count(v),
                            "matches": lambda v: isinstance(v, list) and len(v) >= 2,
                        })
                        for mindex, measured in enumerate(match.get("matches") or []):
                            mwhere = f"{rwhere}.holdMatch.matches[{mindex}]"
                            if not isinstance(measured, dict):
                                yield f"mmFeed.holdMatch.match:object at {mwhere}"
                            else:
                                yield from _fields(measured, "mmFeed.holdMatch.match", mwhere, {
                                    "frame": _count, "poster": lambda v: isinstance(v, bool),
                                    "distance": lambda v: _finite(v) and v >= 0,
                                    "targetDistance": lambda v: v is None or _finite(v) and v >= 0,
                                })
        for lindex, label in enumerate(frame.get("labels") or []):
            lwhere = f"{where}.labels[{lindex}]"
            if not isinstance(label, dict):
                yield f"mmFeed.label:object at {lwhere}"
            else:
                yield from _fields(label, "mmFeed.label", lwhere, {
                    "entryId": _non_empty_str, "serial": _id, "atScene": _count,
                    "opacity": _finite, "spread": lambda v: _finite(v) and v >= 0,
                    "slope": lambda v: v is None or _finite(v),
                })
        for rindex, rider in enumerate(frame.get("riders") or []):
            rwhere = f"{where}.riders[{rindex}]"
            if not isinstance(rider, dict):
                yield f"mmFeed.rider:object at {rwhere}"
            else:
                rider_fields = {
                    "entryId": _non_empty_str, "serial": _id, "atScene": _count, "instance": _non_empty_str,
                    "visible": lambda v: isinstance(v, bool), "opacityProduct": lambda v: _finite(v) and v >= 0,
                    "intersectsCanvas": lambda v: isinstance(v, bool),
                    "sourceRectError": lambda v: v is None or _finite(v) and v >= 0,
                }
                yield from _fields(rider, "mmFeed.rider", rwhere, rider_fields)
    for index, entry in enumerate(value.get("killedOnce") or []):
        where = f"{path}.killedOnce[{index}]"
        if not isinstance(entry, dict):
            yield f"mmFeed.killedOnce:object at {where}"
        else:
            yield from _fields(entry, "mmFeed.killedOnce", where, {"objectId": _non_empty_str, "t": _finite})
    for index, entry in enumerate(value.get("media") or []):
        where = f"{path}.media[{index}]"
        if not isinstance(entry, dict):
            yield f"mmFeed.media:object at {where}"
            continue
        yield from _fields(entry, "mmFeed.media", where, {
            "kind": lambda v: v in ("pause", "play", "seeking", "videoFrame"), "t": _finite,
            "serial": _id, "atScene": _count, "entryId": _non_empty_str, "instance": _non_empty_str, "elId": _id_or_null,
            "currentTime": lambda v: _finite(v) and v >= 0, "paused": lambda v: isinstance(v, bool),
        })
        if version in (2, 3):
            yield from _fields(entry, "mmFeed.media", where, {"generation": _id, "visit": _id})
        for key in ("presentedFrames", "mediaTime"):
            if key in entry and entry[key] is not None and not _finite(entry[key]):
                yield f"mmFeed.media.{key} at {where}"
        if entry.get("kind") == "videoFrame":
            yield from _fields(entry, "mmFeed.media", where, {
                "presentedFrames": _count, "mediaTime": lambda v: _finite(v) and v >= 0,
            })
    for index, entry in enumerate(value.get("mediaDropped") or []):
        where = f"{path}.mediaDropped[{index}]"
        if not isinstance(entry, dict):
            yield f"mmFeed.mediaDropped:object at {where}"
        else:
            yield from _fields(entry, "mmFeed.mediaDropped", where, {"atScene": _count, "count": _id})
    for index, entry in enumerate(value.get("artwork") or []):
        where = f"{path}.artwork[{index}]"
        if not isinstance(entry, dict):
            yield f"mmFeed.artwork:object at {where}"
        else:
            yield from _fields(entry, "mmFeed.artwork", where, {
                "entryId": _non_empty_str, "serial": _id_or_null, "atScene": _count,
                "artworkAbove": lambda v: v is None or isinstance(v, bool),
            })

    event_fields = {
        "uploads": {"serial": _id, "atScene": _count, "t": _finite, "frameN": _id_or_null,
                    "textureOrdinal": _id_or_null},
        "claims": {"objectId": _non_empty_str, "entryId": _non_empty_str, "serial": _id_or_null,
                   "atScene": _count, "t": _finite, "claimed": lambda v: isinstance(v, bool)},
        "standDowns": {"objectId": _non_empty_str, "entryId": _non_empty_str, "serial": _id_or_null,
                       "atScene": _count, "t": _finite, "accepted": lambda v: isinstance(v, bool)},
        "departures": {"t": _finite, "serial": _id_or_null, "atScene": _count, "entryId": _non_empty_str},
    }
    for key, fields in event_fields.items():
        for index, entry in enumerate(value.get(key) or []):
            if not isinstance(entry, dict):
                yield f"mmFeed.{key}.entry:object at {path}.{key}[{index}]"
            else:
                yield from _fields(entry, f"mmFeed.{key}.entry", f"{path}.{key}[{index}]", fields)
                if version in (2, 3) and key == "uploads":
                    yield from _fields(entry, "mmFeed.uploads.entry", f"{path}.{key}[{index}]", {
                        "frameIndex": _count, "frameTimestamp": _finite,
                    })
                if version in (2, 3) and key == "departures":
                    yield from _fields(entry, "mmFeed.departures.entry", f"{path}.{key}[{index}]", {
                        "generation": _id, "visit": _id,
                    })
                if version == 3 and key in ("claims", "departures"):
                    yield from _fields(entry, f"mmFeed.{key}.entry", f"{path}.{key}[{index}]", {
                        "generation": _id_or_null if key == "claims" else _id,
                        "visit": _id_or_null if key == "claims" else _id,
                        "source": lambda v: v in (("claim",) if key == "claims" else ("pause", "context")),
                        "decoder": lambda v: isinstance(v, dict) or (key == "claims" and v is None),
                    })
                    decoder = entry.get("decoder")
                    if isinstance(decoder, dict):
                        yield from _fields(decoder, "mmFeed.departure.decoder", f"{path}.{key}[{index}].decoder", {
                            "instance": _str_or_null, "elId": _id_or_null,
                            "visible": lambda v: isinstance(v, bool),
                            "opacityProduct": lambda v: _finite(v) and v >= 0,
                            "rect": lambda v: v is None or isinstance(v, dict),
                        })
    if version in (2, 3):
        for index, frame in enumerate(value.get("browserFrames") or []):
            where = f"{path}.browserFrames[{index}]"
            if not isinstance(frame, dict):
                yield f"mmFeed.browserFrame:object at {where}"
            else:
                yield from _fields(frame, "mmFeed.browserFrame", where, {"index": _count, "timestamp": _finite})
                if frame.get("index") != index:
                    yield f"mmFeed.browserFrame:index at {where}"
        for index, handback in enumerate(value.get("handbacks") or []):
            where = f"{path}.handbacks[{index}]"
            if not isinstance(handback, dict):
                yield f"mmFeed.handback:object at {where}"
                continue
            yield from _fields(handback, "mmFeed.handback", where, {
                "entryId": _non_empty_str, "serial": _id, "atScene": _count, "closedAt": _finite,
                "closedFrameIndex": _count, "complete": lambda v: isinstance(v, bool),
                "timedOut": lambda v: isinstance(v, bool), "frames": lambda v: isinstance(v, list),
                "lastUpload": lambda v: v is None or isinstance(v, dict),
                "closedDom": lambda v: v is None or isinstance(v, dict),
            })
            if version == 3:
                yield from _fields(handback, "mmFeed.handback", where, {"generation": _id_or_null, "visit": _id})
            if isinstance(handback.get("closedDom"), dict):
                yield from _fields(handback["closedDom"], "mmFeed.dom", f"{where}.closedDom", MM_FEED_DOM_FIELDS)
            for findex, presented in enumerate(handback.get("frames") or []):
                fwhere = f"{where}.frames[{findex}]"
                if not isinstance(presented, dict):
                    yield f"mmFeed.handback.frame:object at {fwhere}"
                    continue
                yield from _fields(presented, "mmFeed.handback.frame", fwhere, {
                    "now": _finite, "t": _finite, "mediaTime": lambda v: _finite(v) and v >= 0,
                    "presentedFrames": _count, "frameIndex": _count, "frameTimestamp": _finite,
                    "dom": lambda v: isinstance(v, dict),
                })
                if isinstance(presented.get("dom"), dict):
                    yield from _fields(presented["dom"], "mmFeed.dom", f"{fwhere}.dom", MM_FEED_DOM_FIELDS)
            if isinstance(handback.get("lastUpload"), dict):
                yield from _fields(handback["lastUpload"], "mmFeed.handback.lastUpload", f"{where}.lastUpload", {
                    "frameIndex": _count, "frameTimestamp": _finite,
                    "presentedFrames": lambda v: v is None or _count(v),
                    "mediaTime": lambda v: v is None or _finite(v) and v >= 0,
                })
        expected = {
            (context.get("serial"), entry_id)
            for context in value.get("contexts") or [] if isinstance(context, dict) and _finite(context.get("closedAt"))
            for entry_id in context.get("entryIds") or [] if isinstance(entry_id, str)
        }
        observed = {
            (handback.get("serial"), handback.get("entryId"))
            for handback in value.get("handbacks") or [] if isinstance(handback, dict)
        }
        if expected != observed:
            yield f"mmFeed.handbacks:closed-context coverage at {path}"


def feed_verdict_record(value: Any, path: str = "feedVerdict") -> Iterator[str]:
    """The scorer-facing feed/hold record assembled from the in-frame producer."""
    if not isinstance(value, dict):
        yield f"feedVerdict:object at {path}"
        return
    if value.get("mode") not in ("continuous", "once", "departure", "standDown", "unavailable"):
        yield f"feedVerdict.mode at {path}"
    if value.get("mode") == "unavailable" and not _non_empty_str(value.get("reason")):
        yield f"feedVerdict.reason at {path}"
    visits = value.get("visits")
    if visits is not None:
        if not isinstance(visits, list) or not visits:
            yield f"feedVerdict.visits:list at {path}"
        else:
            for index, visit in enumerate(visits):
                yield from feed_verdict_record(visit, f"{path}.visits[{index}]")
        return
    for key in ("usableContext", "boundTextures"):
        if not isinstance(value.get(key), bool):
            yield f"feedVerdict.{key} at {path}"
    linger = value.get("canvasLingerMs")
    if (value.get("mode") != "unavailable" and "canvasLingerMs" not in value) or (
        linger is not None and not (_finite(linger) and linger >= 0)
    ):
        yield f"feedVerdict.canvasLingerMs at {path}"
    interval = value.get("interval")
    if interval is not None and not (
        isinstance(interval, dict) and _finite(interval.get("start")) and _finite(interval.get("end"))
        and interval["end"] >= interval["start"]
    ):
        yield f"feedVerdict.interval at {path}"
    if "notes" in value:
        yield from notes(value["notes"], f"{path}.notes", MM_FEED_NOTE_KINDS, module=True, readable=False)
    strict_handback = value.get("evidenceVersion") in (2, 3)
    required = () if value.get("mode") == "unavailable" else ("feed", "rider", "labels", "artwork") if value.get("mode") == "continuous" else (
        "hold", "poster", "rider", "artwork"
    )
    if strict_handback and value.get("mode") != "unavailable":
        required = (*required, "handback")
    if value.get("evidenceVersion") == 3 and value.get("mode") != "unavailable":
        required = (*required, "departureExposure")
        if value.get("mode") != "continuous":
            required = (*required, "resume")
    if value.get("continuousExpected") is True and "feed" not in required:
        required = (*required, "feed")
    for key in required:
        if not isinstance(value.get(key), dict):
            yield f"feedVerdict.{key}:object at {path}"
    for key in ("feed", "hold"):
        record = value.get(key)
        if not isinstance(record, dict):
            continue
        for field in ("usableContext", "boundTextures"):
            if not isinstance(record.get(field), bool):
                yield f"feedVerdict.{key}.{field} at {path}"
        linger = record.get("canvasLingerMs")
        if "canvasLingerMs" not in record or linger is not None and not (_finite(linger) and linger >= 0):
            yield f"feedVerdict.{key}.canvasLingerMs at {path}"
        if not isinstance(record.get("reads"), list):
            yield f"feedVerdict.{key}.reads:list at {path}"
    feed = value.get("feed")
    if isinstance(feed, dict) and "crossfade" in feed and not isinstance(feed["crossfade"], bool):
        yield f"feedVerdict.feed.crossfade at {path}"
    if isinstance(feed, dict) and feed.get("counterLayout") is not None and not isinstance(feed["counterLayout"], dict):
        yield f"feedVerdict.feed.counterLayout at {path}"
    for index, read in enumerate(feed.get("reads") or [] if isinstance(feed, dict) else []):
        where = f"{path}.feed.reads[{index}]"
        if not isinstance(read, dict):
            yield f"feedVerdict.feed.read:object at {where}"
            continue
        yield from _fields(read, "feedVerdict.feed.read", where, {
            "progress": _finite, "patchInside": lambda v: isinstance(v, bool),
            "coveredByLaterDraw": lambda v: isinstance(v, bool), "kind": lambda v: v is None or v in ("counter", "alpha"),
        })
        fields = ("counter", "referenceCounter") if read.get("kind") == "counter" else ("dVideo", "dPoster", "dSep") \
            if read.get("kind") == "alpha" else ()
        yield from _fields(read, "feedVerdict.feed.read", where, {
            key: lambda v: v is None or _finite(v) for key in fields
        })
    hold = value.get("hold")
    for index, read in enumerate(hold.get("reads") or [] if isinstance(hold, dict) else []):
        where = f"{path}.hold.reads[{index}]"
        if not isinstance(read, dict):
            yield f"feedVerdict.hold.read:object at {where}"
            continue
        yield from _fields(read, "feedVerdict.hold.read", where, {
            "phase": lambda v: v in ("first", "middle", "last"), "bestFrame": _count,
            "kind": lambda v: v in ("counter", "alpha", "texture"),
        })
        if read.get("kind") == "texture":
            if not isinstance(read.get("textureOrdinals"), list) or not read["textureOrdinals"] \
                    or not all(_count(value) for value in read["textureOrdinals"]):
                yield f"feedVerdict.hold.read.textureOrdinals at {where}"
        elif not _finite(read.get("matchMargin")):
            yield f"feedVerdict.hold.read.matchMargin at {where}"
        if read.get("kind") == "alpha" and "matches" in read:
            if not isinstance(read.get("matches"), list) or not read["matches"] \
                    or read.get("targetFrame") is not None and not _count(read.get("targetFrame")):
                yield f"feedVerdict.hold.read.matches at {where}"
            for mindex, measured in enumerate(read.get("matches") or []):
                mwhere = f"{where}.matches[{mindex}]"
                if not isinstance(measured, dict):
                    yield f"feedVerdict.hold.read.match:object at {mwhere}"
                else:
                    yield from _fields(measured, "feedVerdict.hold.read.match", mwhere, {
                        "frame": _count, "poster": lambda v: isinstance(v, bool),
                        "distance": lambda v: _finite(v) and v >= 0,
                        "targetDistance": lambda v: v is None or _finite(v) and v >= 0,
                    })
    for key, list_key in (("rider", "riders"), ("labels", "labels"), ("artwork", "reads")):
        record = value.get(key)
        if isinstance(record, dict) and not isinstance(record.get(list_key), list):
            yield f"feedVerdict.{key}.{list_key}:list at {path}"
        if key in ("rider", "labels") and isinstance(record, dict) and not isinstance(record.get("coverage"), bool):
            yield f"feedVerdict.{key}.coverage at {path}"
    handback = value.get("handback")
    if isinstance(handback, dict):
        yield from _fields(handback, "feedVerdict.handback", f"{path}.handback", {
            "complete": lambda v: isinstance(v, bool), "timedOut": lambda v: v is None or isinstance(v, bool),
            "frameMappingComplete": lambda v: isinstance(v, bool), "lastUpload": lambda v: isinstance(v, dict),
            "closed": lambda v: isinstance(v, dict), "presented": lambda v: isinstance(v, list),
            "sourceFrameDurationS": lambda v: v is None or _finite(v) and v > 0,
            "durationSource": lambda v: v in ("fps", "rvfc"),
            "adjacentFrames": lambda v: v is None or isinstance(v, bool),
            "canvasLingerMs": lambda v: v is None or _finite(v) and v >= 0,
        })
    departure = value.get("departureExposure")
    if isinstance(departure, dict):
        identity = _id if departure.get("complete") is True else _id_or_null
        yield from _fields(departure, "feedVerdict.departureExposure", f"{path}.departureExposure", {
            "complete": lambda v: isinstance(v, bool), "entryId": _non_empty_str,
            "serial": identity, "atScene": identity, "visit": identity, "generation": identity,
            "decoder": lambda v: isinstance(v, dict), "context": lambda v: isinstance(v, dict),
            "start": lambda v: isinstance(v, dict), "firstDraw": lambda v: isinstance(v, dict),
            "ordering": lambda v: isinstance(v, bool), "intervalCoverage": lambda v: isinstance(v, bool),
            "posterExposure": lambda v: v is None or isinstance(v, bool),
            "preDrawVisibility": lambda v: isinstance(v, list)
            and all(isinstance(item, bool) for item in v),
            "hiddenWholePreDraw": lambda v: isinstance(v, bool),
            "riders": lambda v: isinstance(v, list),
        })
        decoder = departure.get("decoder")
        if isinstance(decoder, dict):
            yield from _fields(decoder, "feedVerdict.departureExposure.decoder",
                               f"{path}.departureExposure.decoder", {
                                   "instance": _str_or_null, "elId": _id_or_null,
                               })
        context = departure.get("context")
        if isinstance(context, dict):
            yield from _fields(context, "feedVerdict.departureExposure.context",
                               f"{path}.departureExposure.context", {
                                   "serial": identity, "id": _str_or_null,
                               })
        start = departure.get("start")
        if isinstance(start, dict):
            yield from _fields(start, "feedVerdict.departureExposure.start",
                               f"{path}.departureExposure.start", {
                                   "t": lambda v: v is None or _finite(v),
                                   "source": lambda v: v is None or v in ("pause", "context"),
                                   "decoderVisible": lambda v: v is None or isinstance(v, bool),
                                   "observedAt": lambda v: v is None or _finite(v),
                                   "unobservedBeforeContextMs": lambda v: _finite(v) and v >= 0,
                               })
        first_draw = departure.get("firstDraw")
        if isinstance(first_draw, dict):
            yield from _fields(first_draw, "feedVerdict.departureExposure.firstDraw",
                               f"{path}.departureExposure.firstDraw", {
                                   "t": lambda v: v is None or _finite(v),
                                   "frameN": _id_or_null,
                               })
        for index, rider in enumerate(departure.get("riders") or []):
            where = f"{path}.departureExposure.riders[{index}]"
            if not isinstance(rider, dict):
                yield f"feedVerdict.departureExposure.rider:object at {where}"
            else:
                yield from _fields(rider, "feedVerdict.departureExposure.rider", where, {
                    "visible": lambda v: isinstance(v, bool),
                    "opacityProduct": lambda v: _finite(v) and v >= 0,
                    "intersectsCanvas": lambda v: isinstance(v, bool),
                })
    resume = value.get("resume")
    if isinstance(resume, dict):
        yield from _fields(resume, "feedVerdict.resume", f"{path}.resume", {
            "complete": lambda v: isinstance(v, bool), "mode": lambda v: v in ("departure", "standDown"),
            "mediaOverflow": _count, "holdPauseMissing": lambda v: isinstance(v, bool),
            "clockReadable": lambda v: isinstance(v, bool),
            "clockStill": lambda v: v is None or isinstance(v, bool),
        })
        for key in ("pauseTime", "settleTime", "pauseCurrentTime", "settleCurrentTime",
                    "pauseMediaTime", "firstAfterMediaTime", "frameDurationS", "clockToleranceS",
                    "lastUploadedMediaTime"):
            if key in resume and resume[key] is not None and not _finite(resume[key]):
                yield f"feedVerdict.resume.{key} at {path}.resume"
        for key in ("pauseFrame", "firstAfterFrame", "lastUploadedFrame"):
            if key in resume and resume[key] is not None and not _count(resume[key]):
                yield f"feedVerdict.resume.{key} at {path}.resume"
        for key in ("seeked", "resumedFromZero", "successfulFeed", "departurePauseBeforeMove"):
            if key in resume and not isinstance(resume[key], bool):
                yield f"feedVerdict.resume.{key} at {path}.resume"


def _published_verdict(value: Any, kind: str, path: str) -> Iterator[str]:
    if not isinstance(value, dict):
        yield f"{kind}:object at {path}"
        return
    if value.get("verdict") is not None and not isinstance(value.get("verdict"), bool):
        yield f"{kind}.verdict at {path}"
    if "verdict" not in value:
        yield f"{kind}.verdict:missing at {path}"
    if "reason" in value and value["reason"] is not None and not _non_empty_str(value["reason"]):
        yield f"{kind}.reason at {path}"
    if "notApplicable" in value and not isinstance(value["notApplicable"], bool):
        yield f"{kind}.notApplicable at {path}"


def under_artwork_result(value: Any, path: str = "underArtwork") -> Iterator[str]:
    if not isinstance(value, dict):
        yield f"underArtwork:object at {path}"
        return
    yield from _published_verdict(value, "underArtwork", path)
    visits = value.get("visits")
    if visits is not None:
        if not isinstance(visits, list) or not visits:
            yield f"underArtwork.visits:list at {path}"
        else:
            for index, visit in enumerate(visits):
                yield from under_artwork_result(visit, f"{path}.visits[{index}]")
        return
    mode = value.get("mode")
    if mode is None and value.get("verdict") is None and _non_empty_str(value.get("reason")):
        return
    if mode not in ("continuous", "once", "departure", "standDown"):
        yield f"underArtwork.mode at {path}"
        return
    for key in ("noRiderAboveCanvas", "artworkAbove", "departureExposure"):
        yield from _published_verdict(value.get(key), f"underArtwork.{key}", f"{path}.{key}")
    if mode == "continuous":
        for key in ("feedLive", "labelsOverFeed"):
            yield from _published_verdict(value.get(key), f"underArtwork.{key}", f"{path}.{key}")
        hold = value.get("holdFrame")
        if hold != {"verdict": None, "notApplicable": True}:
            yield f"underArtwork.holdFrame:notApplicable at {path}.holdFrame"
    else:
        for key in ("holdFrame", "posterHold"):
            yield from _published_verdict(value.get(key), f"underArtwork.{key}", f"{path}.{key}")
        resume = value.get("resume")
        yield from _published_verdict(resume, "underArtwork.resume", f"{path}.resume")
        if isinstance(resume, dict):
            if "report" in resume and not isinstance(resume["report"], bool):
                yield f"underArtwork.resume.report at {path}.resume"
            if "dropSize" in resume and not _int(resume["dropSize"]):
                yield f"underArtwork.resume.dropSize at {path}.resume"
            if resume.get("report") is True and not (
                    resume.get("verdict") is True and resume.get("dropSize") == 1):
                yield f"underArtwork.resume.reportSemantics at {path}.resume"


HANDBACK_FIELDS = {"status": lambda v: v in ("ok", "inconclusive"), "reason": _str_or_null, "targetHash": _int,
                   "expectHandoff": lambda v: isinstance(v, bool)}


def handback_record(value: Any, path: str = "handback") -> Iterator[str]:
    """`capture_handback`: the GL reads it took (`before`, `polled`, `after`); an `ok` record also has the settled
    stage map, painting and preserve snapshot."""
    if not isinstance(value, dict):
        yield f"handback:object at {path}"
        return
    yield from _fields(value, "handback", path, HANDBACK_FIELDS)
    required = ("before", "stageMap", "painting", "preserve", "after") if value.get("status") == "ok" else ()
    for key in required:
        if key not in value:
            yield f"handback.{key}:missing at {path}"
    for key in ("before", "polled", "after"):
        if key in value:
            yield from gl_read(value[key], f"{path}.{key}")
    if "stageMap" in value:
        yield from stage_map(value["stageMap"], f"{path}.stageMap")
    if "painting" in value:
        yield from painting(value["painting"], f"{path}.painting")
    if "preserve" in value:
        yield from pool(value["preserve"], f"{path}.preserve")


def _seeked(v: Any) -> bool:
    return v is None or _finite(v)


SELECT_FIELDS = {"domId": lambda v: isinstance(v, str), "count": _count, "t": _finite}
SELECT_SEEK_FIELDS = {"duration": lambda v: v is None or _finite(v) and v > 0, "loop": lambda v: isinstance(v, bool),
                      "playbackRate": _finite, "seekFrom": _finite, "target": _seeked}
FRAME_FIELDS = {"now": _finite, "mediaTime": lambda v: _finite(v) and v >= 0, "presentedFrames": _int}
STATUS_FIELDS = {"t": _finite, "seekedT": _seeked, "framesAfterSeek": _count,
                 "duration": lambda v: v is None or _finite(v) and v > 0, "playbackRate": _finite}
RECORDER_FIELDS = {
    "t": _finite, "seekedT": _seeked, "seekFrom": _finite, "target": _seeked, "frames": lambda v: isinstance(v, list),
    "id": lambda v: isinstance(v, str), "elId": _id_or_null, "probeId": _id_or_null,
    "loop": lambda v: isinstance(v, bool), "ended": lambda v: isinstance(v, bool), "paused": lambda v: isinstance(v, bool),
    "isConnected": lambda v: isinstance(v, bool), "duration": lambda v: v is None or _finite(v) and v > 0,
    "playbackRate": _finite,
}


def _frame(value: Any, path: str) -> Iterator[str]:
    if not isinstance(value, dict):
        yield f"frame:object at {path}"
    else:
        yield from _fields(value, "frame", path, FRAME_FIELDS)


def force_wrap(result: Any) -> Iterator[str]:
    """One force-wrap take: its rows, the seek (`take.select`, `take.status`), the recorder, the armed reads and the
    page-error notes."""
    if not isinstance(result, dict):
        yield "forceWrap:object at result"
        return
    sampler = result.get("sampler") if isinstance(result.get("sampler"), dict) else {}
    yield from sample_rows(result.get("samples") or [], schema=sampler.get("schema"))
    take = result.get("take") if isinstance(result.get("take"), dict) else {}
    select = take.get("select")
    if "select" in take:
        if not isinstance(select, dict):
            yield "select:object at take.select"
        else:
            yield from _fields(select, "select", "take.select", SELECT_FIELDS)
            if select.get("count") == 1 and "error" not in select:
                yield from _fields(select, "select", "take.select", SELECT_SEEK_FIELDS)
            elif "error" in select and not isinstance(select["error"], str):
                yield "select.error at take.select"
    status = take.get("status")
    if status is not None:
        if not isinstance(status, dict):
            yield "status:object at take.status"
        else:
            yield from _fields(status, "status", "take.status", STATUS_FIELDS)
            if status.get("last") is not None:
                yield from _frame(status["last"], "take.status.last")
    recorder = result.get("recorder")
    if recorder is not None:
        if not isinstance(recorder, dict):
            yield "recorder:object at recorder"
        else:
            yield from _fields(recorder, "recorder", "recorder", RECORDER_FIELDS)
            frames = recorder.get("frames") if isinstance(recorder.get("frames"), list) else []
            for index, frame in enumerate(frames):
                yield from _frame(frame, f"recorder.frames[{index}]")
            good = [f for f in frames if isinstance(f, dict) and _finite(f.get("now")) and _int(f.get("presentedFrames"))]
            if any(b["now"] <= a["now"] for a, b in zip(good, good[1:])):
                yield "recorder:frame times not increasing at recorder.frames"
            if any(b["presentedFrames"] < a["presentedFrames"] for a, b in zip(good, good[1:])):
                yield "recorder:presentedFrames decreasing at recorder.frames"
    if "reads" in result:
        yield from armed_reads(result["reads"], "reads")
    if result.get("pageErrorNotes") is not None:
        yield from notes(result["pageErrorNotes"], "pageErrorNotes", PAGE_ERROR_NOTE_KINDS, readable=False)


VID_FIELDS = {"elId": _id, "x": _finite, "y": _finite, "w": lambda v: _finite(v) and v >= 0,
              "h": lambda v: _finite(v) and v >= 0, "readyState": _ready_state, "opaque": lambda v: isinstance(v, bool)}


def _vids(value: Any, path: str) -> Iterator[str]:
    if not isinstance(value, list):
        yield f"carryCover:vids list at {path}"
        return
    for index, vid in enumerate(value):
        if not isinstance(vid, dict):
            yield f"vid:object at {path}[{index}]"
        else:
            yield from _fields(vid, "vid", f"{path}[{index}]", VID_FIELDS)
            if "src" in vid and not isinstance(vid["src"], str):
                yield f"vid.src at {path}[{index}]"
    yield from _unique([v["elId"] for v in value if isinstance(v, dict) and _id(v.get("elId"))],
                       "carryCover:duplicate elId", path)


def carry_cover(rows: Any, notes_read: Any, stage: Any) -> Iterator[str]:
    """`CARRY_COVER_SAMPLER_JS` rows (`ts` increasing, `tick` contiguous mod 4096, `vids` with its `readAt` on every
    row but a trailing run; every read with a string `src`, or none in a legacy record), `CARRY_COVER_READ_JS` notes
    and the capture's stage map."""
    yield from stage_map(stage, "stageMap")
    yield from notes(notes_read, "notes", CARRY_COVER_NOTE_KINDS, readable=False)
    if rows is None:
        return
    if not isinstance(rows, list):
        yield "carryCover:rows list at rows"
        return
    prev = None
    unread = False
    sourced: set[bool] = set()
    for index, row in enumerate(rows):
        where = f"rows[{index}]"
        if not isinstance(row, dict):
            yield f"carryCover:row object at {where}"
            prev = None
            continue
        if not _finite(row.get("ts")):
            yield f"carryCover.ts at {where}"
        if not (_int(row.get("tick")) and 0 <= row["tick"] < CARRY_COVER_TICKS):
            yield f"carryCover.tick at {where}"
        if prev is not None and _finite(row.get("ts")) and _finite(prev.get("ts")) and row["ts"] <= prev["ts"]:
            yield f"carryCover:ts not increasing at {where}"
        if prev is not None and _int(row.get("tick")) and _int(prev.get("tick")) \
                and row["tick"] != (prev["tick"] + 1) % CARRY_COVER_TICKS:
            yield f"carryCover:tick not contiguous at {where}"
        yield from _vids(row.get("pre"), f"{where}.pre")
        sourced.update(
            "src" in v for key in ("pre", "vids") if isinstance(row.get(key), list) for v in row[key] if isinstance(v, dict)
        )
        if "vids" in row:
            if unread:
                yield f"carryCover:read after an unread row at {where}"
            yield from _vids(row["vids"], f"{where}.vids")
            if not _finite(row.get("readAt")):
                yield f"carryCover.readAt at {where}"
        else:
            unread = True
            if "readAt" in row:
                yield f"carryCover:readAt without vids at {where}"
        prev = row
    if len(sourced) > 1:
        yield "carryCover:mixed read generations (with and without src) at rows"


def census(raw: Any, path: str = "censusRaw") -> Iterator[str]:
    """`census_observer`: per slide, a list of `{stageMap, painting}` reads."""
    if not isinstance(raw, dict):
        return
    for key, reads in raw.items():
        if not isinstance(reads, list):
            continue
        for index, read in enumerate(reads):
            yield from refusal_read(read, f"{path}.{key}[{index}]")


MANAGED_VIDEO_FIELDS = {"src": lambda v: isinstance(v, str), "paused": lambda v: isinstance(v, bool),
                        "rs": _ready_state, "t": _finite, "loop": lambda v: isinstance(v, bool)}
MANAGED_HANDED_FIELDS = {"elId": _id, "loop": lambda v: isinstance(v, bool), "isConnected": lambda v: isinstance(v, bool),
                         "facade": lambda v: isinstance(v, bool), "paused": lambda v: isinstance(v, bool), "t": _finite}
MANAGED_SAMPLE_FIELDS = {"t": _finite, "state": lambda v: v is None or v in GL_STATES,
                         "standDowns": lambda v: v is None or isinstance(v, list) and all(isinstance(d, str) for d in v),
                         "videoEnded": lambda v: v is None or isinstance(v, bool),
                         "uploads": lambda v: v is None or _int(v), "carriedT": lambda v: v is None or _finite(v)}


def _managed_list(value: Any, path: str, kind: str, table: dict[str, Any]) -> Iterator[str]:
    if not isinstance(value, list):
        yield f"{kind}:list at {path}"
        return
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            yield f"{kind}:object at {path}[{index}]"
        else:
            yield from _fields(entry, kind, f"{path}[{index}]", table)


def _handed_back(value: Any, path: str) -> Iterator[str]:
    """`HANDED_BACK_JS`: every element with the carried `elId`; the dd9ecc9f generation read the first one alone,
    without `facade`, or `{elId, missing: true}`."""
    if not isinstance(value, dict):
        yield from _managed_list(value, path, "managed.handedBack", MANAGED_HANDED_FIELDS)
    elif value.get("missing") is not True:
        yield from _fields(value, "managed.handedBack", path,
                           {k: v for k, v in MANAGED_HANDED_FIELDS.items() if k != "facade"})


def managed_session(session: Any, path: str) -> Iterator[str]:
    """One `managed_obs_qualify` session: its page reads (`Session.read`), phase records, armed reads, hand-back and
    video reads, context-loss result, precheck samples and feed-arm sampler rows."""
    if not isinstance(session, dict):
        yield f"managed:session object at {path}"
        return
    for tag, read in (session.get("reads") or {}).items():
        where = f"{path}.reads.{tag}"
        if not isinstance(read, dict):
            yield f"managed:read object at {where}"
            continue
        if not _finite(read.get("wall")):
            yield f"managed.wall at {where}"
        yield from gl_read(read.get("gl"), f"{where}.gl")
        if "painting" not in read:
            yield f"managed.painting:missing at {where}"
        else:
            yield from painting(read["painting"], f"{where}.painting")
        yield from _managed_list(read.get("videos"), f"{where}.videos", "managed.video", MANAGED_VIDEO_FIELDS)
    for index, phase in enumerate(session.get("phases") or []):
        where = f"{path}.phases[{index}]"
        if not isinstance(phase, dict):
            yield f"managed:phase object at {where}"
            continue
        if not isinstance(phase.get("hash"), str):
            yield f"managed.hash at {where}"
        yield from _managed_list(phase.get("videos"), f"{where}.videos", "managed.video", MANAGED_VIDEO_FIELDS)
        raf = phase.get("raf")
        if not (isinstance(raf, list) and len(raf) == 2 and _finite(raf[0]) and _int(raf[1])):
            yield f"managed.raf at {where}"
    if "armed" in session:
        yield from armed_reads(session["armed"], f"{path}.armed")
    for key in ("slide1Videos", "postHandbackVideos"):
        if key in session:
            yield from _managed_list(session[key], f"{path}.{key}", "managed.video", MANAGED_VIDEO_FIELDS)
    if "handedBack" in session:
        yield from _handed_back(session["handedBack"], f"{path}.handedBack")
    if "loseContext" in session and not isinstance(session["loseContext"], dict):
        yield f"managed.loseContext at {path}"
    if "samples" in session:
        yield from _managed_list(session["samples"], f"{path}.samples", "managed.sample", MANAGED_SAMPLE_FIELDS)
    if "sampleRows" in session:
        yield from sample_rows(session["sampleRows"], schema=2, path=f"{path}.sampleRows")


def managed_run(run: Any) -> Iterator[str]:
    sessions = run.get("sessions") if isinstance(run, dict) else None
    if not isinstance(sessions, list):
        return
    for index, session in enumerate(sessions):
        name = session.get("session") if isinstance(session, dict) else None
        yield from managed_session(session, f"sessions[{name if isinstance(name, str) else index}]")
