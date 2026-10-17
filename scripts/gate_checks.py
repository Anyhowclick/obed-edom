#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import live_run_validity  # noqa: E402
from obed_edom.live_continuity import canonical_asset_name  # noqa: E402


# Red arms (plan §4) are keyed by the exact runtime plan, arm and GL mode. An id is a plan-generated verdict whose
# gated value differs from the plan, or `stray:slide{ordinal}:{asset}` for an unclaimed painting video. RECORD reports
# current behaviour without passing or failing. The comments below retain the probe registrations' provenance.
RECORD = "record"
# Schema-2 runtime plans (`CONTINUITY_VERSION` 6); P2 off/on, D1, D3 and D5 are pinned in
# tests/fixtures/live_continuity/runtime_v2_examples.json. D2 and D2-across derive the same plan because the export does
# not encode play-across (plan §5, R-res-1).
P2_OFF_PLAN_SHA256 = "283f5eecd18c3412172e28a40bc716c69173a7c72bcd37379dcd3d7d6a96dd4e"
ALPHA_DSK_PLAN_SHA256 = "c9e546551300e44ff1765147def49257916f14f1c139fcee704d9accad7411d6"
D7_PLAN_SHA256 = "0e2570925a56dc69204657fc5d1001e87ad4407eb3fed62e271f1d7c94b5b584"
D7S_PLAN_SHA256 = "3d1a0bd159e0e2dc91e2533d167cc5cdacd6aa5412891bd1661c6114a12a8577"
D7_COUNTER_MDAT_SHA256 = {
    "counter-a.mov": "71659a979a15ee609da711f5bfeddc61ff2fc420fae8dafed11aca820791a218",
    "counter-b.mov": "b37ffd93027cfd3e692818e0f52ce109a0febec5a6a3aae16bb84207b450db39",
}
# P2's off/on and p2-loop off/on plans are the only plans using the legacy P2 slot table.
P2_PLAN_SHA256 = frozenset({
    P2_OFF_PLAN_SHA256,
    "2fbf977277a5eef1cde701c12bb157905e40ac2b0a5ed85e30bf1056a3e65c18",
    "866de785864ad19b11ecd8cdfb4ad1729798ccf9f1764aa59718de03034ba7a5",
    "d860a09f4f6a8e24a81e2ad0c3b37bc8a3f2b4ce3947836ca315671031870131",
})
DECK_PLAN_SHA256 = {
    "D1": "4d466b2f0ee035928486dc3e61f23a5d92e3cc4e76d5d02f367e115331cc0b00",
    "D2": "029a4c427d2f7ebe2cf7410e2010fdc03834f370f5c6d25aeea9e05c2fbc20f7",
    "D3": "01b74c88f4622e5a0650d334d7721a247a2039a1767f232d792e823405a21b1b",
    "D4": "e166c385753364cdc159307b8f7d9092979533b71aee93ea4b8ebbea7a366076",
    "D5": "73d1153f086381996b5490d6f66eae2ee6996eb05b4a1dcd0af0fce70a018f5e",
    "D6": "149e813cfe68b6bac7c5c4ea0b5829f20e017ee1d0ce742ece3444fd1f60eed1",
}
_P2 = "untitled.mov#1->untitled.mov#1"
_A = "counter-a.mov#1->counter-a.mov#1"
_B = "counter-b.mov#1->counter-b.mov#1"
_A_FAR = "counter-a.mov#2->counter-a.mov#1"
_D1, _D2, _D3, _D4, _D5, _D6 = (DECK_PLAN_SHA256[f"D{n}"] for n in range(1, 7))
# Derived from the plan and v6 behaviour (WS-R, S2): a stripped carry's raw destination can resume when named by the
# next entry; an unnamed facaded pin detaches and stops; an unnamed bridge overlay remains as a stray; retire/restart of
# a raw, never-carried src is inert apart from retire preserve-refused notes. `stage1/` means main-checkout evidence at
# output/evidence/s2-dev/instr-v-277c720b/stage1, measured 2026-10-12 at 277c720b.
RED_ARM_EXPECTATIONS: dict[tuple[str, str, str], tuple[str, ...] | str] = {
    # Post-hoc from discovery g1h-089a0393 (2026-09-25), pending the final round.
    (P2_OFF_PLAN_SHA256, "core:stash-any", "off"): (
        f"b0to1:{_P2}:retire", "stray:slide2:untitled.mov", "stray:slide3:untitled.mov", "stray:slide4:untitled.mov",
        "stray:slide4:vid-20250608-wa0125.mp4",
    ),
    (P2_OFF_PLAN_SHA256, "strip:bridge@8", "off"): (f"b2to3:{_P2}:carry",),
    # Nothing names slide 1's raw decoder, so nothing is pooled; only the retire note clause is red.
    (P2_OFF_PLAN_SHA256, "strip:retire@2", "off"): (f"b0to1:{_P2}:retire",),
    (P2_OFF_PLAN_SHA256, "strip:glReplay@2", "auto"): (f"b0to1:{_P2}:armed",),
    # Slide 2's source is retired at 2 and never carried, so restart@6 is inert.
    (P2_OFF_PLAN_SHA256, "strip:restart@6", "off"): (),
    (_D1, "strip:bridge@2", "off"): (f"b0to1:{_A}:carry",),
    (_D1, "strip:bridge@4", "off"): (f"b1to2:{_A}:carry", "stray:slide3:counter-a.mov", "stray:slide4:counter-a.mov"),
    # Owner re-registration 2026-10-12; stage1/V4/D1--strippin@6.json (paint run 62).
    (_D1, "strip:pin@6", "off"): (f"b2to3:{_A}:carry", "duplicate:slide4:counter-a.mov#1"),
    (_D2, "strip:bridge@2", "off"): (f"b0to1:{_A}:carry",),
    # Post-hoc from discovery g1h-089a0393 (2026-09-25), pending the final round.
    (_D2, "strip:restart@4", "off"): (
        f"b1to2:{_A}:restart", f"b2to3:{_A}:carry", f"b3to4:{_A}:carry",
        "duplicate:slide3:counter-a.mov#1", "duplicate:slide4:counter-a.mov#1", "stray:slide5:counter-a.mov",
    ),
    # Post-hoc from discovery g1h-089a0393 (2026-09-25), pending the final round.
    (_D2, "strip:pin@6", "off"): (f"b2to3:{_A}:carry",),
    (_D2, "strip:bridge@8", "off"): (f"b3to4:{_A}:carry",),
    # Owner registration 2026-10-12; stage1/V3/D2-red-npH.json (paint run 108).
    (_D2, "core:no-pin-hold", "off"): (f"b2to3:{_A}:carry",),
    (_D3, "strip:pin@2", "off"): (f"b0to1:{_A}:carry",),
    (_D3, "strip:bridge@2", "off"): (f"b0to1:{_B}:carry",),
    (_D3, "strip:retire@4", "off"): ("b1to2:counter-a.mov#1->end:retire",),
    # Post-hoc from discovery g1h-089a0393 (2026-09-25), pending the final round.
    (_D3, "strip:pin@4", "off"): (
        f"b1to2:{_B}:carry", f"b2to3:{_B}:carry", "duplicate:slide3:counter-b.mov#1", "stray:slide4:counter-b.mov",
    ),
    (_D3, "strip:bridge@6", "off"): (f"b2to3:{_B}:carry",),
    # Owner registration 2026-10-12; stage1/V3/D3-red-npH.json (paint run 107).
    (_D3, "core:no-pin-hold", "off"): (f"b0to1:{_A}:carry",),
    # Post-hoc from discovery g1h-089a0393 (2026-09-25), pending the final round.
    (_D4, "core:wrong-instance", "off"): (
        f"b0to1:{_A_FAR}:carry", f"b1to2:{_A}:carry", "duplicate:slide2:counter-a.mov#1", "duplicate:slide3:counter-a.mov#1",
    ),
    # Post-hoc from discovery g1h-089a0393 (2026-09-25), pending the final round.
    (_D4, "core:fifo-reuse", "off"): (
        f"b0to1:{_A_FAR}:carry", f"b1to2:{_A}:carry", "duplicate:slide2:counter-a.mov#1", "duplicate:slide3:counter-a.mov#1",
    ),
    (_D4, "strip:bridge@3", "off"): (f"b0to1:{_A_FAR}:carry",),
    # Owner re-registration 2026-10-12; stage1/V4/D4--strippin@5.json (paint run 63).
    (_D4, "strip:pin@5", "off"): (f"b1to2:{_A}:carry", "duplicate:slide3:counter-a.mov#1"),
    # Post-hoc from discovery g1h-089a0393 (2026-09-25), pending the final round.
    (_D5, "core:stash-any", "off"): ("stray:slide3:counter-a.mov", "stray:slide3:counter-b.mov"),
    # Owner re-registration 2026-10-12; stage1/V4/D5--core-variantfifo-reuse.json (paint run 59).
    (_D5, "core:fifo-reuse", "off"): (f"b1to2:{_A}:carry", "duplicate:slide3:counter-a.mov#1"),
    # Post-hoc from discovery g1h-089a0393 (2026-09-25), pending the final round.
    (_D5, "strip:pin@2", "off"): (f"b0to1:{_A}:carry",),
    (_D5, "strip:pin@4", "off"): (f"b1to2:{_A}:carry",),
    # Owner registration 2026-10-12; stage1/V3/D5-red-npH.json (paint runs 108/223).
    (_D5, "core:no-pin-hold", "off"): (f"b0to1:{_A}:carry", f"b1to2:{_A}:carry"),
    (_D6, "strip:bridge@2", "off"): (f"b0to1:{_A_FAR}:carry",),
    (_D6, "strip:retire@8", "off"): (f"b3to4:{_A}:retire",),
}
# Pass-G red arms are keyed by exact plan and arm, using ids from passg_red_ids; `stage1/` is the evidence root above.
PASSG_RED_EXPECTATIONS: dict[tuple[str, str], tuple[str, ...]] = {
    # Owner registration 2026-10-12; stage1/V3/D1-passG-red-npH.json.
    (_D1, "core:no-pin-hold"): (f"G1-3-4:b2to3:{_A}:carry", "G1-3-4:destination"),
}
# Every red carry must meet the carried paintFloor (decision 3, at least 60 frames).
PAINT_FLOOR_MIN_FRAMES = 60
# Arms whose registered reds count only with the registered floor.
PAINT_RED_ARMS = ("core:no-pin-hold",)
RED_ARM_PAINT_FLOOR: dict[tuple[str, str, str], int] = {
    (deck, "core:no-pin-hold", "off"): PAINT_FLOOR_MIN_FRAMES for deck in (_D2, _D3, _D5)
}
PASSG_RED_PAINT_FLOOR: dict[tuple[str, str], int] = {(_D1, "core:no-pin-hold"): PAINT_FLOOR_MIN_FRAMES}
# IDs an arm must turn red whatever else it registers: the plan's stray and identity controls.
RED_ARM_REQUIRED: dict[tuple[str, str, str], tuple[str, ...]] = {
    (P2_OFF_PLAN_SHA256, "core:stash-any", "off"): ("stray:slide4:vid-20250608-wa0125.mp4",),
    (_D4, "core:wrong-instance", "off"): (f"b0to1:{_A_FAR}:carry",),
}

MM_FEED_GATE_EXPECTATIONS: dict[str, dict[str, bool | None]] = {
    "feed-on": {"feedLive": True, "holdFrame": None, "noRiderAboveCanvas": True,
                "labelsOverFeed": True, "artworkAbove": True, "handbackContinuity": True},
    "feed-off": {"feedLive": False, "holdFrame": True, "posterHold": True, "resume": True,
                 "noRiderAboveCanvas": True, "artworkAbove": True, "handbackContinuity": True},
    "attach-once": {"holdFrame": True, "posterHold": True, "resume": True,
                    "noRiderAboveCanvas": True, "artworkAbove": True, "handbackContinuity": True},
    "hold-upload-killed": {"holdFrame": False},
    "ordinal": {"feedLive": False, "holdFrame": False, "posterHold": True, "resume": True},
    "after-feed": {"feedLive": False, "holdFrame": True, "posterHold": True, "resume": True},
    "from-only-crossfade": {"feedLive": False},
    "from-only-single": {"feedLive": True},
    "overlay-ride": {"noRiderAboveCanvas": False, "labelsOverFeed": True},
    "settle-on-stage": {"artworkAbove": False},
    "no-pause": {"posterHold": False},
    "mm-opacity-off": {"labelsOverFeed": False},
    "no-linger": {"handbackContinuity": False},
    "interim-delay": {},
    "startup-moved-decoder": {"labelsOverFeed": True},
}
MM_FEED_RESUME_EXEMPTIONS = frozenset({"no-pause", "hold-upload-killed"})
MM_FEED_STRIP_EXPECTATIONS = {
    (ALPHA_DSK_PLAN_SHA256, "strip:bridge@14:movie2", "off"): (
        "b7to8:vid-20250608-wa0121.mp4#1->vid-20250608-wa0121.mp4#1:carry",
    ),
}
MM_FEED_READ_EXPECTATIONS = {
    ("D7", "crossfade"): {0.25: True, 0.5: False, 0.75: False},
    ("D7s", "crossfade"): {0.25: True, 0.5: False, 0.75: False},
    # Re-registered from round adfeb552: at 0.75 dVideo 149.6 vs dPoster 4.7, so the GL patch matches the unfed poster.
    ("Alpha_DSK", "first-crossfade"): {0.5: False, 0.75: False},
}
ALPHA_ORDINAL_TARGET = (
    "b5to6:vid-20250608-wa0125.mp4#1->vid-20250608-wa0125.mp4#1:carry",
    10,
)
MM_FEED_NOT_APPLICABLE = {
    (ALPHA_DSK_PLAN_SHA256, "mm-opacity-off"): frozenset({ALPHA_ORDINAL_TARGET}),
}
MM_FEED_REPORT_ROWS = ("entryColdStart",)
MM_FEED_DISCOVERY_REGISTRY: dict[tuple[str, str, str], dict[str, Any]] = {
    (D7_PLAN_SHA256, "departure-early-hide", live_run_validity.HOST_HEADLESS_CHROME): {
        "redArm": "core:departure-early-hide",
        "coreVariant": "departure-early-hide",
        "departureExposure": None,
    },
}

PLAN_DECK_CLASS = {
    **{sha: "P2" for sha in P2_PLAN_SHA256},
    **{sha: deck for deck, sha in DECK_PLAN_SHA256.items()},
    ALPHA_DSK_PLAN_SHA256: "Alpha_DSK",
    D7_PLAN_SHA256: "D7",
    D7S_PLAN_SHA256: "D7s",
}


class Verdict(str, Enum):
    MATCH = "MATCH"
    RECORDED = "RECORDED"
    MISMATCH = "MISMATCH"
    INVALID = "INVALID"
    REPORT = "REPORT"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class GateResult:
    verdict: Verdict
    lines: tuple[str, ...]
    exit_code: int
    status: str
    candidate: Verdict


@dataclass(frozen=True)
class RoundBuildResult:
    ok: bool
    chrome_build: str | None
    lines: tuple[str, ...]


_RESULTS = {
    Verdict.MATCH: (0, "pass"),
    Verdict.RECORDED: (3, "recorded"),
    Verdict.MISMATCH: (1, "fail"),
    Verdict.INVALID: (1, "invalid"),
    Verdict.REPORT: (0, "report"),
}


def _result(verdict: Verdict, lines: Sequence[str], *, candidate: Verdict | None = None) -> GateResult:
    exit_code, status = _RESULTS[verdict]
    return GateResult(verdict, tuple(lines), exit_code, status, candidate or verdict)


def _plan_sha(record: Mapping[str, Any]) -> str | None:
    ground = record.get("groundTruth")
    return ground.get("planSha256") if isinstance(ground, Mapping) and isinstance(ground.get("planSha256"), str) else None


def _deck_class(record: Mapping[str, Any]) -> str | None:
    sha = _plan_sha(record)
    return PLAN_DECK_CLASS.get(sha) if sha is not None else None


def _validity(record: Mapping[str, Any], host_kind: str) -> Mapping[str, Any]:
    stored = record.get("runValidity")
    if not isinstance(stored, Mapping) or stored.get("ok") not in (True, False, None):
        return {"ok": None, "reasons": ["runValidity is missing or malformed"]}
    policy = stored.get("policy")
    if not isinstance(policy, Mapping) or policy.get("hostKind") != host_kind:
        observed_host = policy.get("hostKind") if isinstance(policy, Mapping) else None
        return {
            "ok": False,
            "reasons": [f"runValidity policy hostKind {observed_host!r} != {host_kind!r}"],
        }
    return stored


def _with_precedence(
    record: Mapping[str, Any], host_kind: str, candidate: GateResult
) -> GateResult:
    if record.get("_loadError"):
        return candidate
    validity = _validity(record, host_kind)
    ok = validity.get("ok")
    reasons = validity.get("reasons") if isinstance(validity.get("reasons"), list) else []
    if ok is False:
        return _result(
            Verdict.INVALID,
            [*candidate.lines, *[f"    INVALID: {reason}" for reason in reasons]],
            candidate=candidate.candidate,
        )
    if ok is not True:
        suffix = reasons or ["run validity is unproven"]
        return _result(
            Verdict.INVALID,
            [*candidate.lines, *[f"    INVALID: {reason}" for reason in suffix]],
            candidate=candidate.candidate,
        )
    return candidate


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _frames(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _registered_specs(record: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], list[str]]:
    ground = record.get("groundTruth")
    specs = ground.get("verdicts") if isinstance(ground, Mapping) else None
    if not isinstance(specs, list):
        return [], ["groundTruth.verdicts missing or malformed"]
    problems: list[str] = []
    rows: list[Mapping[str, Any]] = []
    ids: list[str] = []
    for index, spec in enumerate(specs):
        if not isinstance(spec, Mapping) or not isinstance(spec.get("id"), str):
            problems.append(f"groundTruth.verdicts[{index}] missing an exact string id")
            continue
        rows.append(spec)
        ids.append(spec["id"])
    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicates:
        problems.append(f"duplicate spec ids {duplicates}")
    return rows, problems


def _scored_arm(record: Mapping[str, Any], label: str) -> tuple[Mapping[str, Any] | None, str]:
    if label == "attach-once":
        holder, name = record.get("attach"), "attach"
    elif "redArm" in record:
        holder, name = record.get("arm"), "arm"
    else:
        arms = record.get("arms")
        holder, name = (arms.get("A") if isinstance(arms, Mapping) else None), "arms.A"
    return (holder if isinstance(holder, Mapping) else None), name


def _inventory(record: Mapping[str, Any], label: str) -> tuple[list[Mapping[str, Any]], Mapping[str, Any], list[str]]:
    specs, problems = _registered_specs(record)
    arm, holder_name = _scored_arm(record, label)
    if arm is None:
        return specs, {}, [*problems, f"{holder_name} missing or malformed"]
    verdicts = arm.get("verdicts")
    if not isinstance(verdicts, Mapping):
        return specs, arm, [*problems, f"{holder_name} verdict inventory missing or malformed"]
    expected = [spec["id"] for spec in specs if isinstance(spec.get("id"), str)]
    actual = list(verdicts)
    if not all(isinstance(item, str) for item in actual):
        problems.append("arm A verdict inventory has a non-string id")
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing:
        problems.append(f"missing verdict ids {missing}")
    if extra:
        problems.append(f"extra verdict ids {extra}")
    if len(actual) != len(set(actual)):
        problems.append("duplicate scored verdict ids")
    for spec_id in expected:
        if spec_id in verdicts and not isinstance(arm.get(spec_id), Mapping):
            problems.append(f"verdict record {spec_id!r} missing or malformed")
    return specs, arm, problems


def _control_aggregate_problems(label: str, rows: Sequence[Mapping[str, Any]]) -> list[str]:
    import mm_feed_instrument

    if label == "startup-moved-decoder":
        riders = [row.get("noRiderAboveCanvas") for row in rows]
        problems = [
            f"row {index} startup-moved-decoder noRiderAboveCanvas is unreadable"
            for index, rider in enumerate(riders)
            if not isinstance(rider, Mapping) or rider.get("verdict") is None
        ]
        separated = any(
            rider.get("verdict") is False and any(
                isinstance(offender, Mapping)
                and isinstance(offender.get("sourceRectError"), (int, float))
                and not isinstance(offender.get("sourceRectError"), bool)
                and offender["sourceRectError"] > mm_feed_instrument.SOURCE_RECT_TOLERANCE_PX
                for offender in rider.get("offenders") or []
            )
            for rider in riders if isinstance(rider, Mapping)
        )
        if not separated:
            problems.append("startup-moved-decoder did not expose a geometry-backed rider in any row")
        return problems
    handbacks = [row.get("handbackContinuity") for row in rows]
    if label == "no-linger":
        return [
            f"row {index} no-linger sourceFrames {(handback or {}).get('sourceFrames')!r} is not > 2"
            for index, handback in enumerate(handbacks)
            if not isinstance(handback, Mapping)
            or not isinstance(handback.get("sourceFrames"), int)
            or isinstance(handback.get("sourceFrames"), bool)
            or handback["sourceFrames"] <= 2
        ]
    if label != "interim-delay":
        return []
    problems = [
        f"row {index} interim-delay handbackContinuity is unreadable"
        for index, handback in enumerate(handbacks)
        if not isinstance(handback, Mapping) or handback.get("verdict") is None
    ]
    if not any(
        isinstance(handback, Mapping)
        and handback.get("verdict") is False
        and handback.get("reason") == "a static poster was exposed during DOM hand-back"
        for handback in handbacks
    ):
        problems.append("interim-delay did not expose a static poster in any hand-back row")
    return problems


def _mm_feed_report_lines(scored: Mapping[str, Any]) -> list[str]:
    entry_cold_start = scored.get("entryColdStart")
    if "entryColdStart" not in MM_FEED_REPORT_ROWS or not isinstance(entry_cold_start, Mapping):
        return []
    return [
        f"    REPORT: asset={mount.get('asset')} scene={mount.get('scene')} "
        f"visibleUndecodedDurationMs={mount.get('visibleUndecodedDurationMs')}"
        for mount in entry_cold_start.values()
        if isinstance(mount, Mapping)
    ]


def _mm_feed_discovery(
    record: Mapping[str, Any], label: str, rc: Any, host_kind: str
) -> tuple[GateResult, bool] | None:
    registration = MM_FEED_DISCOVERY_REGISTRY.get((_plan_sha(record), label, host_kind))
    if registration is None:
        return None
    from continuity_core_variants import variant_sha

    specs, scored, problems = _inventory(record, label)
    variant = registration["coreVariant"]
    expected_sha = variant_sha(variant)
    continuity = scored.get("continuity") if isinstance(scored.get("continuity"), Mapping) else {}
    if record.get("kind") != "live-continuity-probe-red-arm":
        problems.append(f"kind {record.get('kind')!r} is not a red-arm capture")
    if record.get("coreVariant") != variant:
        problems.append(f"coreVariant {record.get('coreVariant')!r} != {variant!r}")
    if record.get("redArm") != registration["redArm"]:
        problems.append(f"redArm {record.get('redArm')!r} != {registration['redArm']!r}")
    if record.get("expectedCoreSha256") != expected_sha or continuity.get("sha256") != expected_sha:
        problems.append("the departure discovery did not run the registered core variant")
    if continuity.get("mode") != "qualified":
        problems.append(f"arm.continuity.mode {continuity.get('mode')!r} != 'qualified'")
    if "expectedRedSet" not in record or record.get("expectedRedSet") is not None:
        problems.append("expectedRedSet is not explicit None")
    if record.get("status") != "unregistered":
        problems.append(f"status {record.get('status')!r} != 'unregistered'")
    if not _strings(record.get("redSet")):
        problems.append("redSet is not a list of strings")
    if record.get("unknown") != []:
        problems.append(f"unknown {record.get('unknown')!r} != []")
    if str(rc) != "1":
        problems.append(f"exit {rc} != 1")

    feed_specs = [spec for spec in specs if spec.get("underArtwork") is True]
    rows = 0
    for spec in feed_specs:
        entry = scored.get(spec["id"])
        under = entry.get("underArtwork") if isinstance(entry, Mapping) else None
        if not isinstance(under, Mapping) or "verdict" not in under:
            problems.append(f"{spec['id']}.underArtwork missing or malformed")
            continue
        rows += 1
        departure = under.get("departureExposure")
        if not isinstance(departure, Mapping) or "verdict" not in departure:
            problems.append(f"{spec['id']}.departureExposure missing or malformed")
        elif departure.get("verdict") is not registration["departureExposure"]:
            problems.append(
                f"{spec['id']}.departureExposure {departure.get('verdict')!r} != "
                f"{registration['departureExposure']!r}"
            )
    if not rows:
        problems.append("no under-artwork verdict records")
    lines = [
        f"[MM-FEED {_deck_class(record)} {label}] exit={rc} records={rows} status={record.get('status')}",
        f"    discovery redSet={record.get('redSet')}",
        *[f"    MISMATCH: {problem}" for problem in problems],
        *_mm_feed_report_lines(scored),
    ]
    ok = not problems
    return _result(Verdict.RECORDED if ok else Verdict.MISMATCH, lines), ok


def _mm_feed(
    record: Mapping[str, Any], arm: str, rc: Any, *, host_kind: str
) -> tuple[GateResult, bool]:
    deck = _deck_class(record)
    label = arm
    if record.get("_loadError"):
        shown = record.get("_deckLabel") or deck or "unknown"
        lines = [f"[MM-FEED {shown} {label}] no artifact ({record['_loadError']}) exit={rc}"]
        return _result(Verdict.MISMATCH, lines), False
    if deck is None:
        lines = [f"[MM-FEED unknown {label}] exit={rc} records=0 status={record.get('status')}",
                 "    MISMATCH: unregistered or missing groundTruth.planSha256"]
        return _result(Verdict.MISMATCH, lines), False
    discovery = _mm_feed_discovery(record, label, rc, host_kind)
    if discovery is not None:
        return discovery
    if label == "strip-bridge14-movie2":
        scored, _ = _scored_arm(record, label)
        key = (_plan_sha(record), record.get("redArm"), "off")
        wanted = MM_FEED_STRIP_EXPECTATIONS.get(key)
        got = record.get("redSet")
        problems = []
        if record.get("status") != "pass":
            problems.append(f"status {record.get('status')!r} != 'pass'")
        if got != list(wanted or ()):
            problems.append(f"redSet {got!r} != {list(wanted or ())!r}")
        if record.get("unknown") != []:
            problems.append(f"unknown {record.get('unknown')!r} != []")
        lines = [f"[MM-FEED {deck} {label}] exit={rc} redSet={got}",
                 *[f"    MISMATCH: {problem}" for problem in problems],
                 *_mm_feed_report_lines(scored or {})]
        ok = str(rc) == "0" and not problems
        return _result(Verdict.MATCH if ok else Verdict.MISMATCH, lines), ok

    internal_labels = {"feed-on", "feed-off", "from-only-crossfade", "from-only-single"}
    registered_controls = set(MM_FEED_GATE_EXPECTATIONS) - internal_labels
    if label.startswith("feed-off-"):
        expectation = "feed-off"
    elif label.startswith("feed-on-"):
        expectation = "feed-on"
    elif label == "from-only":
        expectation = label
    elif label in registered_controls:
        expectation = label
    else:
        lines = [
            f"[MM-FEED {deck} {label}] exit={rc} records=0 status={record.get('status')}",
            "    MISMATCH: unregistered MM-FEED label",
        ]
        return _result(Verdict.MISMATCH, lines), False

    specs, scored, problems = _inventory(record, label)
    notes: list[str] = []
    feed_specs = [spec for spec in specs if spec.get("underArtwork") is True]
    rows: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for spec in feed_specs:
        entry = scored.get(spec["id"])
        under = entry.get("underArtwork") if isinstance(entry, Mapping) else None
        if not isinstance(under, Mapping) or "verdict" not in under:
            problems.append(f"{spec['id']}.underArtwork missing or malformed")
        else:
            rows.append((spec, under))
    if not rows:
        problems.append("no under-artwork verdict records")
    problems.extend(_control_aggregate_problems(label, [row for _, row in rows]))
    first_feed_scene = min(
        (spec.get("atScene") for spec in feed_specs if isinstance(spec.get("feed"), Mapping)), default=None,
    )
    target_id, target_scene = ALPHA_ORDINAL_TARGET
    if label in {"ordinal", "after-feed"} and not any(
        spec.get("id") == target_id and spec.get("atScene") == target_scene for spec, _ in rows
    ):
        problems.append(f"target carry {target_id!r} atScene {target_scene} is missing")
    applicable_na = MM_FEED_NOT_APPLICABLE.get((_plan_sha(record), label), frozenset())
    opacity_evidence = 0
    resume_problems: list[str] = []
    resume_reports: list[str] = []
    for spec, row in rows:
        row_expectation = expectation
        wanted = dict(MM_FEED_GATE_EXPECTATIONS.get(expectation, {}))
        if label in {"ordinal", "after-feed"}:
            if spec.get("id") == target_id and spec.get("atScene") == target_scene:
                wanted = dict(MM_FEED_GATE_EXPECTATIONS[label])
            else:
                row_expectation = "feed-on"
                wanted = dict(MM_FEED_GATE_EXPECTATIONS["feed-on"])
        if label == "from-only":
            crossfade = isinstance(spec.get("feed"), Mapping) and spec["feed"].get("to") is not None
            expectation = "from-only-crossfade" if crossfade else "from-only-single"
            wanted = dict(MM_FEED_GATE_EXPECTATIONS[expectation])
            read_key = (deck, "first-crossfade") if deck == "Alpha_DSK" and spec.get("atScene") == first_feed_scene else (deck, "crossfade")
            want_reads = MM_FEED_READ_EXPECTATIONS.get(read_key) if crossfade else None
            if want_reads:
                feed_live = row.get("feedLive") if isinstance(row.get("feedLive"), Mapping) else {}
                checks = {
                    check.get("progress"): check.get("ok")
                    for check in feed_live.get("checks") or [] if isinstance(check, Mapping)
                }
                for progress, want in want_reads.items():
                    if checks.get(progress) is not want:
                        problems.append(f"{spec['id']}.feedLive[{progress}] {checks.get(progress)!r} != {want!r}")
        for name, want in wanted.items():
            check = row.get(name)
            row_key = (spec.get("id"), spec.get("atScene"))
            if label == "mm-opacity-off" and name == "labelsOverFeed":
                is_na = isinstance(check, Mapping) and check.get("notApplicable") is True
                if row_key in applicable_na:
                    if is_na:
                        notes.append(f"    N/A: {spec['id']}.{name} explicitly notApplicable")
                        continue
                    problems.append(f"{spec['id']}.{name} must be explicitly notApplicable")
                    continue
                if is_na:
                    problems.append(f"{spec['id']}.{name} is not registered as notApplicable")
                    continue
            if not isinstance(check, Mapping) or "verdict" not in check:
                target = resume_problems if name == "resume" else problems
                target.append(f"{spec['id']}.{name} missing or malformed")
                continue
            actual = check.get("verdict")
            if name == "resume":
                if actual is not want:
                    resume_problems.append(f"{spec['id']}.{name} {actual!r} != {want!r}")
                report, drop = check.get("report"), check.get("dropSize")
                if not isinstance(report, bool):
                    resume_problems.append(f"{spec['id']}.{name}.report missing or malformed")
                if not isinstance(drop, int) or isinstance(drop, bool) or drop < 0:
                    resume_problems.append(f"{spec['id']}.{name}.dropSize missing or malformed")
                elif drop >= 2:
                    resume_problems.append(
                        f"{spec['id']}.{name} dropSize {drop} is not an approved one-frame report"
                    )
                elif report is True and drop != 1:
                    resume_problems.append(f"{spec['id']}.{name} report requires dropSize 1, got {drop}")
                elif report is False and drop != 0:
                    resume_problems.append(f"{spec['id']}.{name} dropSize {drop} requires report true")
                elif report is True:
                    resume_reports.append(f"    REPORT: {spec['id']} resume dropSize=1")
                continue
            if row_expectation == "feed-on" and name == "holdFrame" and want is None:
                if actual is not None or check.get("notApplicable") is not True or row.get("mode") != "continuous":
                    problems.append(
                        f"{spec['id']}.{name} must be explicit notApplicable on continuous under-artwork"
                    )
            elif actual is not want:
                problems.append(f"{spec['id']}.{name} {actual!r} != {want!r}")
            elif label == "mm-opacity-off" and name == "labelsOverFeed" and actual is False:
                opacity_evidence += 1
    if label == "mm-opacity-off" and opacity_evidence == 0:
        problems.append("mm-opacity-off has no evidenced labelsOverFeed False row")
    problems.extend(resume_problems)
    lines = [f"[MM-FEED {deck} {label}] exit={rc} records={len(rows)} status={record.get('status')}", *notes,
             *[f"    MISMATCH: {problem}" for problem in problems]]
    ok = str(rc) in ("0", "1") and not problems
    lines.extend(_mm_feed_report_lines(scored))
    lines.extend(resume_reports)
    verdict = Verdict.MATCH if ok else Verdict.MISMATCH
    return _result(verdict, lines), ok


def _host_red(record: Mapping[str, Any], arm: str, rc: Any) -> tuple[GateResult, bool]:
    from continuity_core_variants import variant_sha
    from obed_edom.live_continuity_js import js_sha256

    label = record.get("_displayLabel") if isinstance(record.get("_displayLabel"), str) else arm
    if record.get("_loadError"):
        return _result(Verdict.MISMATCH, (f"[HOST {label}] no artifact ({record['_loadError']}) -> MISMATCH",)), False
    variant = arm.removeprefix("core:") if arm.startswith("core:") else None
    want_sha = variant_sha(variant) if variant else js_sha256()
    status, arm_label, exp, got, unknown, sha = (record.get(key) for key in (
        "status", "redArm", "expectedRedSet", "redSet", "unknown", "expectedCoreSha256",
    ))
    scored = record.get("arm") if isinstance(record.get("arm"), Mapping) else {}
    census = scored.get("census") if isinstance(scored.get("census"), Mapping) else None
    problems: list[str] = []
    for key in ("status", "redArm", "expectedRedSet", "redSet", "unknown", "expectedCoreSha256"):
        if key not in record:
            problems.append(f"missing {key}")
    if not isinstance(status, str):
        problems.append("status not a string")
    if arm_label != arm:
        problems.append(f"redArm {arm_label!r} != {arm!r}")
    if sha != want_sha:
        problems.append(f"expectedCoreSha256 {sha!r} != {want_sha}")
    if not _strings(unknown):
        problems.append("unknown not a list of strings")
    elif unknown:
        problems.append(f"unknown {unknown}")
    if not _strings(got):
        problems.append("redSet not a list of strings")
    plan_sha = _plan_sha(record)
    gl_replay = record.get("glReplay")
    gl_mode = gl_replay.get("requested") if isinstance(gl_replay, Mapping) else None
    if gl_mode not in {"off", "auto"}:
        problems.append("glReplay.requested missing or malformed")
    argv_gl_mode = record.get("_argvGlReplay")
    if argv_gl_mode is not None and gl_mode != argv_gl_mode:
        problems.append(f"glReplay.requested {gl_mode!r} != argv {argv_gl_mode!r}")
    registered = RED_ARM_EXPECTATIONS.get((plan_sha, arm, gl_mode))
    if exp != (list(registered) if isinstance(registered, tuple) else registered):
        problems.append("expectedRedSet does not match the registered plan/arm/GL row")
    if not (exp == RECORD or _strings(exp)):
        problems.append("expectedRedSet neither 'record' nor a list of strings")
    sampler = scored.get("sampler") if isinstance(scored.get("sampler"), Mapping) else None
    if not (isinstance(sampler, Mapping) and sampler.get("schema") == 2
            and isinstance(sampler.get("selfCheck"), Mapping) and sampler["selfCheck"].get("ok") is True):
        problems.append("arm.sampler is not schema 2 with selfCheck.ok")
    if not (isinstance(census, Mapping) and census and all(isinstance(value, Mapping) for value in census.values())):
        problems.append("arm.census missing or malformed")
    elif _strings(got):
        strays = [red for red in got if red.partition(":")[0] == "stray"]
        duplicates = [red for red in got if red.partition(":")[0] == "duplicate"]
        wanted_duplicates: list[str] = []
        pool = list(strays)
        for ordinal, item in sorted(census.items()):
            videos, duplicate_videos = item.get("unexpectedVideos"), item.get("duplicateVideos")
            if not isinstance(videos, list) or not isinstance(duplicate_videos, list):
                problems.append(f"census slide {ordinal} lacks unexpectedVideos/duplicateVideos")
                continue
            wanted_duplicates += [
                f"duplicate:slide{ordinal}:{value.get('label') if isinstance(value, Mapping) else None}"
                for value in duplicate_videos
            ]
            for video in videos:
                source = str((video or {}).get("src") or "").lower()
                source_name = canonical_asset_name((video or {}).get("src"))
                hit = next((
                    red for red in pool
                    if red.split(":", 2)[:2] == ["stray", f"slide{ordinal}"]
                    and (red.split(":", 2)[2] == "unknown" or red.split(":", 2)[2] == source_name)
                ), None)
                if hit is None:
                    problems.append(f"census stray on slide {ordinal} ({source}) not in redSet")
                else:
                    pool.remove(hit)
        if pool:
            problems.append(f"redSet strays with no census video: {pool}")
        if Counter(duplicates) != Counter(wanted_duplicates):
            problems.append(f"redSet duplicates {sorted(duplicates)} != census {sorted(wanted_duplicates)}")
    floor = record.get("paintFloor")
    required_floor = RED_ARM_PAINT_FLOOR.get((plan_sha, arm, gl_mode))
    if required_floor is not None and floor is None:
        problems.append(f"paintFloor missing (a {variant} red arm needs at least {PAINT_FLOOR_MIN_FRAMES} frames)")
    elif floor is not None and not (_frames(floor) and floor >= PAINT_FLOOR_MIN_FRAMES):
        problems.append(f"paintFloor {floor!r} is not a frame count of at least {PAINT_FLOOR_MIN_FRAMES}")
    elif floor is not None:
        specs, spec_problems = _registered_specs(record)
        problems.extend(spec_problems)
        spec_ids = {spec["id"] for spec in specs}
        carry_ids = {spec["id"] for spec in specs if spec.get("kind") == "carry"}
        for red in got if _strings(got) else []:
            if red not in spec_ids and red.partition(":")[0] not in {"stray", "duplicate"}:
                problems.append(f"red id {red!r} is not a registered spec id, stray or duplicate")
                continue
            value = scored.get(red) if isinstance(scored.get(red), Mapping) else None
            paint = value.get("paint") if isinstance(value, Mapping) and isinstance(value.get("paint"), Mapping) else None
            run = paint.get("longestRun") if isinstance(paint, Mapping) else None
            if red in carry_ids and not (_frames(run) and run >= floor):
                problems.append(f"{red} longest unpainted run {run!r} below the {floor}-frame floor")
    recorded = exp == RECORD
    ok = not problems and status == ("recorded" if recorded else "pass") and int(rc) == 0
    if not recorded and _strings(got) and _strings(exp):
        ok = ok and Counter(got) == Counter(exp)
    verdict = Verdict.RECORDED if ok and recorded else Verdict.MATCH if ok else Verdict.MISMATCH
    lines = [
        f"[HOST {label}] {arm_label} status={status} exit={rc} expectedCoreSha256={sha} (want {want_sha}) unknown={unknown}",
        f"    expected red: {exp}",
        f"    observed red: {got} -> {verdict}",
        *[f"    contract: {problem}" for problem in problems],
    ]
    for ordinal, item in sorted((census or {}).items()):
        if isinstance(item, Mapping) and (item.get("unexpectedVideos") or item.get("duplicateVideos")):
            lines.append(f"    slide {ordinal}: unexpected={[(value or {}).get('src') for value in item.get('unexpectedVideos') or []]} duplicates={len(item.get('duplicateVideos') or [])}")
    return _result(verdict, lines), ok


def _passg(record: Mapping[str, Any], arm: str, rc: Any) -> tuple[GateResult, bool]:
    if record.get("_loadError"):
        return _result(Verdict.MISMATCH, (f"[PASSG {arm}] no artifact ({record['_loadError']}) exit={rc}",)), False
    lines = [f"[PASSG {arm}] status={record.get('status')} exit={rc}"]
    if record.get("pass") != "G":
        lines.append(f"    not a Pass G artifact (pass={record.get('pass')!r})")
    lines.extend(f"    {reason}" for reason in record.get("reasons") or [])
    if record.get("error"):
        lines.append(f"    error: {record['error']}")
    ok = str(rc) == "0" and record.get("pass") == "G" and record.get("status") == "pass"
    return _result(Verdict.MATCH if ok else Verdict.MISMATCH, lines), ok


def _passg_red(record: Mapping[str, Any], arm: str, rc: Any) -> tuple[GateResult, bool]:
    from continuity_core_variants import variant_sha

    variant = arm.removeprefix("core:")
    want_sha = variant_sha(variant)
    if record.get("_loadError"):
        label = record.get("_displayLabel") or f"unknown --core-variant {variant}"
        return _result(Verdict.MISMATCH, (f"[PASSG-RED {label}] no artifact ({record['_loadError']}) exit={rc}",)), False
    exp, got, unknown, floor = (record.get(key) for key in ("expectedRedSet", "redSet", "unknown", "paintFloor"))
    label = f"{_deck_class(record) or 'unknown'} --core-variant {variant}"
    lines = [
        f"[PASSG-RED {label}] {record.get('redArm')} status={record.get('status')} exit={rc} expectedCoreSha256={record.get('expectedCoreSha256')} (want {want_sha}) unknown={unknown}",
        f"    expected red: {exp}", f"    observed red: {got}",
    ]
    lines.extend(f"    {reason}" for reason in record.get("statusReasons") or record.get("reasons") or [])
    if record.get("error"):
        lines.append(f"    error: {record['error']}")
    problems: list[str] = []
    if record.get("kind") != "live-continuity-probe-pass-g" or record.get("pass") != "G":
        problems.append(f"not a Pass G artifact (kind={record.get('kind')!r}, pass={record.get('pass')!r})")
    if record.get("redArm") != arm:
        problems.append(f"redArm {record.get('redArm')!r} != {arm!r}")
    if record.get("expectedCoreSha256") != want_sha:
        problems.append("expectedCoreSha256 is not the variant's")
    def sha_of(name: str) -> Any:
        entry = record.get(name)
        continuity = entry.get("continuity") if isinstance(entry, Mapping) else None
        return continuity.get("sha256") if isinstance(continuity, Mapping) else None
    for name in ("armed", "nullControl"):
        if sha_of(name) != want_sha:
            problems.append(f"{name} installed core sha {sha_of(name)!r} is not the variant's")
    registered = PASSG_RED_EXPECTATIONS.get((_plan_sha(record), arm))
    if exp != (list(registered) if registered is not None else None):
        problems.append("expectedRedSet does not match the registered plan/arm row")
    if not _strings(exp):
        problems.append("expectedRedSet is not a registered list of ids")
    if not _strings(got):
        problems.append("redSet not a list of strings")
    elif _strings(exp) and Counter(got) != Counter(exp):
        problems.append(f"red set {sorted(got)} != registered {sorted(exp)}")
    if not _strings(unknown):
        problems.append("unknown not a list of strings")
    elif unknown:
        problems.append(f"unknown {unknown}")
    if record.get("status") != "pass":
        problems.append(f"status {record.get('status')!r} != 'pass'")
    if str(rc) != "0":
        problems.append(f"exit {rc} != 0")
    required_floor = PASSG_RED_PAINT_FLOOR.get((_plan_sha(record), arm))
    if required_floor is not None and floor is None:
        problems.append(f"paintFloor missing (a {variant} red arm needs at least {PAINT_FLOOR_MIN_FRAMES} frames)")
    elif floor is not None and not (_frames(floor) and floor >= PAINT_FLOOR_MIN_FRAMES):
        problems.append(f"paintFloor {floor!r} is not a frame count of at least {PAINT_FLOOR_MIN_FRAMES}")
    elif floor is not None:
        runs: dict[str, Any] = {}
        destinations: set[str] = set()
        armed = record.get("armed") if isinstance(record.get("armed"), Mapping) else {}
        for destination in armed.get("destinations") or []:
            if not isinstance(destination, Mapping) or not isinstance(destination.get("advanceCarry"), Mapping):
                continue
            case = f"G{destination.get('fromOrdinal')}-{destination.get('toOrdinal')}-{destination.get('advanceTo')}"
            destinations.add(f"{case}:destination")
            for spec_id, value in (destination["advanceCarry"].get("verdicts") or {}).items():
                paint = value.get("paint") if isinstance(value, Mapping) and isinstance(value.get("paint"), Mapping) else None
                runs[f"{case}:{spec_id}"] = paint.get("longestRun") if isinstance(paint, Mapping) else None
        for red in got if _strings(got) else []:
            run = runs.get(red)
            if red not in runs and red not in destinations:
                if red.endswith(":carry"):
                    problems.append(f"{red} longest unpainted run {run!r} below the {floor}-frame floor")
                else:
                    problems.append(f"{red} has no measured leg or armed destination")
            elif red in runs and not (_frames(run) and run >= floor):
                problems.append(f"{red} longest unpainted run {run!r} below the {floor}-frame floor")
    lines.extend(f"    MISMATCH: {problem}" for problem in problems)
    ok = not problems
    return _result(Verdict.MATCH if ok else Verdict.MISMATCH, lines), ok


def _paint_control(record: Mapping[str, Any], arm: str, rc: Any) -> tuple[GateResult, bool]:
    from obed_edom.live_continuity_js import js_sha256
    import paint_instrument

    parts = arm.split(":")
    count, variant = int(parts[0]), parts[1]
    if record.get("_loadError"):
        label = f"{record.get('_deckLabel') or 'unknown'} {arm}"
        return _result(Verdict.MISMATCH, (f"[PAINT-CONTROL {label}] no artifact ({record['_loadError']}) exit={rc}",)), False
    control_record = record.get("controlRecord") if isinstance(record.get("controlRecord"), Mapping) else {}
    scored = record.get("arm") if isinstance(record.get("arm"), Mapping) else {}
    target = record.get("targetVerdictId")
    target_value = scored.get(target) if isinstance(target, str) and isinstance(scored.get(target), Mapping) else {}
    paint = target_value.get("paint") if isinstance(target_value.get("paint"), Mapping) else {}
    sampler = scored.get("sampler") if isinstance(scored.get("sampler"), Mapping) else {}
    hidden = control_record.get("hiddenSeqs")
    half = variant == "ancestor-half"
    seen, other = (paint.get("partialSeqs"), "unpaintedFrames") if half else (paint.get("unpaintedSeqs"), "partialFrames")
    label = f"{_deck_class(record) or 'unknown'} {arm}"
    lines = [
        f"[PAINT-CONTROL {label}] control={record.get('control')} status={record.get('status')} exit={rc} target={target} fired={control_record.get('fired')} hiddenTicks={control_record.get('hiddenTicks')} (want {count})",
        f"    injected seqs: {hidden}",
        f"    {'partial' if half else 'unpainted'} seqs on target: {seen}",
        f"    paint {paint.get('status')} unpainted={paint.get('unpaintedFrames')} partial={paint.get('partialFrames')} double={paint.get('doubleFrames')} substitute={paint.get('substituteFrames')}; redSet={record.get('redSet')} unknown={record.get('unknown')}",
    ]
    lines.extend(f"    {reason}" for reason in record.get("statusReasons") or [])
    if record.get("error"):
        lines.append(f"    error: {record['error']}")
    problems: list[str] = []
    if record.get("kind") != "live-continuity-probe-paint-control":
        problems.append(f"not a paint-control artifact (kind={record.get('kind')!r})")
    if record.get("control") != arm:
        problems.append(f"control {record.get('control')!r} != {arm!r}")
    if record.get("expectedCoreSha256") != js_sha256():
        problems.append("expectedCoreSha256 is not today's core")
    self_check = sampler.get("selfCheck")
    if sampler.get("schema") != 2 or not isinstance(self_check, Mapping) or self_check.get("ok") is not True:
        problems.append("arm.sampler is not schema 2 with selfCheck.ok")
    control_problem = paint_instrument.control_record_problem(record.get("controlRecord"))
    if control_problem:
        problems.append(f"controlRecord unreadable: {control_problem}")
    paint_problem = paint_instrument.schema_problem(target_value.get("paint"), paint_instrument.PAINT_SCORE_FIELDS)
    if paint_problem:
        problems.append(f"target paint score unreadable: {paint_problem}")
    if control_record.get("fired") is not True:
        problems.append("injector never fired")
    if control_record.get("hiddenTicks") != count:
        problems.append(f"hiddenTicks {control_record.get('hiddenTicks')!r} != {count}")
    ints = lambda value: isinstance(value, list) and all(isinstance(item, int) and not isinstance(item, bool) for item in value)
    consecutive = hidden == [] if not count else ints(hidden) and len(hidden) == count and hidden == list(range(hidden[0], hidden[0] + count))
    if not consecutive:
        problems.append(f"injected seqs {hidden!r} are not {count} consecutive ticks")
    if not ints(seen) or seen != hidden:
        problems.append(f"target seq set {seen!r} != injected {hidden!r}")
    for key in (other, "doubleFrames", "substituteFrames"):
        if paint.get(key) != 0:
            problems.append(f"target {key} {paint.get(key)!r} != 0")
    if record.get("redSet") != ([target] if count else []):
        problems.append(f"redSet {record.get('redSet')!r} != {[target] if count else []!r}")
    if record.get("unknown") != []:
        problems.append(f"unknown {record.get('unknown')!r} not an empty list")
    if record.get("status") != "pass":
        problems.append(f"status {record.get('status')!r} != 'pass'")
    if str(rc) != "0":
        problems.append(f"exit {rc} != 0")
    lines.extend(f"    MISMATCH: {problem}" for problem in problems)
    ok = not problems
    return _result(Verdict.MATCH if ok else Verdict.MISMATCH, lines), ok


def _carry_cover(record: Mapping[str, Any], arm: str, rc: Any) -> tuple[GateResult, bool]:
    from continuity_core_variants import variant_sha
    from obed_edom.live_continuity_js import js_sha256

    params = json.loads(arm)
    label, wanted, fixture, variant, control = (
        params["label"], params["wanted"], params["fixture"], params.get("variant"), params["control"],
    )
    if record.get("_loadError"):
        return _result(Verdict.MISMATCH, (f"[CARRY-COVER {label}] no artifact ({record['_loadError']}) exit={rc}",)), False
    want_sha = variant_sha(variant) if variant else js_sha256()
    continuity = record.get("continuity") if isinstance(record.get("continuity"), Mapping) else {}
    sha = continuity.get("sha256")
    lines = [f"[CARRY-COVER {label}] control={record.get('control')} status={record.get('status')} (want {wanted}) exit={rc} core sha {sha} (want {want_sha})"]
    lines.extend(f"    {reason}" for reason in record.get("reasons") or [])
    if record.get("error"):
        lines.append(f"    error: {record['error']}")
    bridges = [value if isinstance(value, Mapping) else {} for value in record.get("bridges")] if isinstance(record.get("bridges"), list) else []
    clocks = [value.get("clock") if isinstance(value.get("clock"), Mapping) else {} for value in bridges]
    for bridge, clock in zip(bridges, clocks):
        scored = bridge.get("result") if isinstance(bridge.get("result"), Mapping) else {}
        lines.append(f"    {bridge.get('boundary')}: verdict={scored.get('verdict')} maxStripPx={scored.get('maxStripPx')} cleanShare={scored.get('cleanShare')} undecidedFrames={scored.get('undecidedFrames')} clock={clock.get('via')} lagMs={clock.get('lagMs')}")
    problems: list[str] = []
    if record.get("kind") != "live-continuity-probe-carry-cover":
        problems.append(f"not a carry-cover artifact (kind={record.get('kind')!r})")
    if record.get("fixture") != fixture:
        problems.append(f"fixture {record.get('fixture')!r} != {fixture!r}")
    if record.get("control") != control:
        problems.append(f"control {record.get('control')!r} != {control!r}")
    if record.get("coreVariant") != variant:
        problems.append(f"coreVariant {record.get('coreVariant')!r} != {variant!r}")
    if sha != want_sha or record.get("coreSha256") != want_sha:
        problems.append("installed core sha is not the arm's")
    want_via = "fallback" if variant == "no-gl-clock" else "gl"
    if control != "null" and (not bridges or any(clock.get("via") != want_via for clock in clocks)):
        problems.append(f"bridge clocks {[clock.get('via') for clock in clocks]!r} are not all {want_via!r}")
    if record.get("status") != wanted:
        problems.append(f"status {record.get('status')!r} != {wanted!r}")
    if str(rc) != ("0" if wanted == "pass" else "1"):
        problems.append(f"exit {rc} does not agree with {wanted}")
    lines.extend(f"    MISMATCH: {problem}" for problem in problems)
    ok = not problems
    return _result(Verdict.MATCH if ok else Verdict.MISMATCH, lines), ok


def _expect(record: Mapping[str, Any], arm: str, rc: Any) -> tuple[GateResult, bool]:
    from continuity_core_variants import variant_sha
    from obed_edom.live_continuity_js import js_sha256
    from obed_edom.p2_verdict import build_continuity_plan

    if record.get("_loadError"):
        return _result(Verdict.MISMATCH, (f"    no log ({record['_loadError']}) -> MISMATCH",)), False
    text = record.get("text") if isinstance(record.get("text"), str) else ""
    args = record.get("args") if isinstance(record.get("args"), list) else []
    spec, inc_spec = record.get("expectedRed"), record.get("expectedInconclusive")
    found = re.findall(r"^- ([A-Za-z0-9]+): \*\*(True|False)\*\*(?: \(([^)]*)\))?", text, re.M)
    inconclusive = sorted(name for name, _, result in found if result == "inconclusive")
    red = {name for name, value, result in found if value == "False" and result != "inconclusive"}
    ids = {name for name, _, _ in found}
    auto = "--gl-replay" in args and args[args.index("--gl-replay") + 1:][:1] == ["auto"] or "--gl-replay=auto" in args
    slot_ok = ("glReplayCarry1to2" in ids and "refusedCarry1to2" not in ids) if auto else ("refusedCarry1to2" in ids and "glReplayCarry1to2" not in ids)
    core = re.search(r"injected core sha256: ([0-9a-f]{64})", text)
    success = re.search(r"^success: \*\*(True|False)\*\*", text, re.M)
    unchanged = re.search(r"^Source unchanged: \*\*True\*\*", text, re.M)
    def arg(name: str) -> str | None:
        return next((value.split("=", 1)[1] for value in args if value.startswith(name + "=")), None) or next(
            (args[index + 1] for index, value in enumerate(args[:-1]) if value == name), None,
        )
    variant, strip = arg("--core-variant"), arg("--strip")
    head_core = re.search(r"^Core variant: (\S+) · injected core sha256: ", text, re.M)
    head_strip = re.search(r"^Strip: (\S+) · injected plan sha256: ([0-9a-f]{64})$", text, re.M)
    unstripped = hashlib.sha256(json.dumps(build_continuity_plan("--disable-bridge34" not in args)).encode()).hexdigest()
    head_freeze = re.search(r"^Freeze bracket: (.+)$", text, re.M)
    want_freeze = "skipped (--skip-freeze-bracket)" if "--skip-freeze-bracket" in args else "skipped (bridge disabled)" if "--disable-bridge34" in args else "run"
    header_ok = bool(head_core) and head_core.group(1) == (variant or "none") and bool(head_strip) and head_strip.group(1) == (strip or "none") and (strip is None or head_strip.group(2) != unstripped) and bool(head_freeze) and head_freeze.group(1) == want_freeze
    want_sha = variant_sha(variant) if variant else js_sha256()
    sha_ok = bool(core) and core.group(1) == want_sha
    count_ok = len(found) == 15 and len(ids) == 15
    exit_ok = (int(rc) == 0) == (success is not None and success.group(1) == "True") and int(rc) in (0, 1)
    lines = [
        "    validity: not applicable (P2 adversarial harness has no instrument capture)",
        f"    core sha {core.group(1) if core else None} expected {want_sha} {'MATCH' if sha_ok else 'MISMATCH'}",
        f"    header core {head_core.group(1) if head_core else None} strip {head_strip.group(1) if head_strip else None} plan sha {head_strip.group(2) if head_strip else None} (unstripped {unstripped}) freeze bracket {head_freeze.group(1) if head_freeze else None!r} (want {want_freeze!r}) {'OK' if header_ok else 'WRONG'}",
        f"    exit {rc}; findings {len(found)}/15; source unchanged {bool(unchanged)}; success {success.group(1) if success else None}; 1->2 slot {'glReplayCarry1to2' if auto else 'refusedCarry1to2'} {'OK' if slot_ok else 'WRONG'}; inconclusive: {inconclusive or '{}'}; observed red: {sorted(red) or '{}'}",
    ]
    integrity = sha_ok and count_ok and bool(unchanged) and bool(success) and exit_ok and slot_ok and header_ok
    if spec == "RECORD":
        recorded = integrity and not inconclusive
        lines.append(f"    expected red: (none registered) -> {'RECORDED' if recorded else 'MISMATCH'}")
        return _result(Verdict.RECORDED if recorded else Verdict.MISMATCH, lines), recorded
    wanted, wanted_inconclusive = set(str(spec or "").split()), set(str(inc_spec or "").split())
    ok = integrity and red == wanted and set(inconclusive) == wanted_inconclusive and int(rc) == (1 if wanted or wanted_inconclusive else 0)
    lines.append(f"    expected red: {sorted(wanted) or '{}'}; expected inconclusive: {sorted(wanted_inconclusive) or '{}'} -> {'MATCH' if ok else 'MISMATCH'}")
    return _result(Verdict.MATCH if ok else Verdict.MISMATCH, lines), ok


def judge(record: Mapping[str, Any], gate_kind: str, arm: str, host_kind: str, *, rc: Any) -> GateResult:
    handlers = {
        "check_mm_feed": _mm_feed,
        "expect": _expect,
        "check_host_red": _host_red,
        "check_passg": _passg,
        "check_passg_red": _passg_red,
        "check_paint_control": _paint_control,
        "check_cc": _carry_cover,
    }
    handler = handlers.get(gate_kind)
    if handler is None:
        return _result(Verdict.MISMATCH, (f"unknown gate kind {gate_kind!r}",))
    if live_run_validity.qualification(host_kind) is None:
        return _result(Verdict.MISMATCH, (f"{gate_kind}: unregistered host kind {host_kind!r}",))
    try:
        candidate, _ = (
            handler(record, arm, rc, host_kind=host_kind)
            if gate_kind == "check_mm_feed"
            else handler(record, arm, rc)
        )
    except Exception as exc:
        return _result(Verdict.MISMATCH, (f"{gate_kind}: judgement error ({exc})",))
    if (
        gate_kind in {"check_mm_feed", "check_host_red", "check_passg_red", "check_paint_control"}
        and not record.get("_loadError")
        and _deck_class(record) is None
        and not any("groundTruth.planSha256" in line for line in candidate.lines)
    ):
        candidate = _result(
            Verdict.MISMATCH,
            (*candidate.lines, "    MISMATCH: unregistered or missing groundTruth.planSha256"),
        )
    if gate_kind == "expect":
        return candidate
    return _with_precedence(record, host_kind, candidate)


def _load(path: str) -> dict[str, Any]:
    try:
        with open(path) as stream:
            value = json.load(stream)
    except Exception as exc:
        return {"_loadError": str(exc)}
    record = value if isinstance(value, dict) else {}
    if "groundTruth" not in record and isinstance(record.get("planSha256"), str):
        record["groundTruth"] = {"planSha256": record["planSha256"]}
    return record


def _holder_chrome_builds(validity: Mapping[str, Any]) -> list[str | None]:
    holders = validity.get("holders")
    if not isinstance(holders, Mapping):
        return []
    builds: set[str | None] = set()
    for holder in holders.values():
        measured = holder.get("measured") if isinstance(holder, Mapping) else None
        environment = measured.get("environment") if isinstance(measured, Mapping) else None
        build = environment.get("chromeBuild") if isinstance(environment, Mapping) else None
        if build is None or isinstance(build, str):
            builds.add(build)
    return sorted(builds, key=lambda value: (value is not None, value or ""))


def round_chrome_build(
    records: Sequence[tuple[str, Mapping[str, Any]]], *, validity_na: frozenset[str] = frozenset()
) -> RoundBuildResult:
    lines: list[str] = []
    builds: list[tuple[str, str]] = []
    invalid: list[str] = []
    for label, record in records:
        if "_loadError" in record:
            if label in validity_na:
                lines.append(f"[ROUND BUILD {label}] P2 report unreadable (validity N/A)")
            else:
                invalid.append(label)
                lines.append(f"[ROUND BUILD {label}] artifact unreadable: {record['_loadError']}")
            continue
        validity = record.get("runValidity")
        if not isinstance(validity, Mapping):
            if label in validity_na:
                lines.append(f"[ROUND BUILD {label}] build not recorded (validity N/A)")
            else:
                invalid.append(label)
                lines.append(f"[ROUND BUILD {label}] runValidity absent")
            continue
        measured = validity.get("measured")
        environment = measured.get("environment") if isinstance(measured, Mapping) else None
        build = environment.get("chromeBuild") if isinstance(environment, Mapping) else None
        if not isinstance(build, str) or not build:
            invalid.append(label)
            holder_suffix = ""
            if build is None:
                holder_builds = _holder_chrome_builds(validity)
                holder_suffix = f"; holders.*.measured.environment.chromeBuild={holder_builds!r}"
            lines.append(
                f"[ROUND BUILD {label}] MISSING: runValidity.measured.environment.chromeBuild{holder_suffix}"
            )
            continue
        builds.append((label, build))
        lines.append(f"[ROUND BUILD {label}] chromeBuild={build}")
    distinct = sorted({build for _, build in builds})
    if invalid:
        lines.append(f"ROUND BUILD INVALID: unusable build evidence in {len(invalid)} artifact(s)")
    if len(distinct) > 1:
        detail = ", ".join(f"{build} ({sum(value == build for _, value in builds)})" for build in distinct)
        lines.append(f"ROUND BUILD INVALID: mixed exact chromeBuild values: {detail}")
    if not distinct:
        lines.append("ROUND BUILD INVALID: no artifact recorded a Chrome build")
    build = distinct[0] if len(distinct) == 1 else None
    ok = not invalid and len(distinct) == 1
    if ok:
        lines.append(f"ROUND BUILD MATCH: chromeBuild={build if build is not None else 'N/A'}")
    return RoundBuildResult(ok=ok, chrome_build=build, lines=tuple(lines))


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "check_round_build":
        parser = argparse.ArgumentParser()
        parser.add_argument("gate_kind", choices=("check_round_build",))
        parser.add_argument("--validity-na", action="append", default=[])
        parser.add_argument("paths", nargs="*")
        args = parser.parse_args()
        paths = [*args.paths, *args.validity_na]
        result = round_chrome_build(
            [(path, _load(path)) for path in paths], validity_na=frozenset(args.validity_na)
        )
        print("\n".join(result.lines))
        raise SystemExit(0 if result.ok else 1)
    parser = argparse.ArgumentParser()
    parser.add_argument("gate_kind", choices=(
        "check_mm_feed", "expect", "check_host_red", "check_passg", "check_passg_red", "check_paint_control", "check_cc",
    ))
    parser.add_argument("path")
    parser.add_argument("rc")
    parser.add_argument("arm")
    parser.add_argument("host_kind")
    parser.add_argument("gate_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.gate_kind == "expect":
        if len(args.gate_args) < 2:
            parser.error("expect needs expected-red, expected-inconclusive and optional arm arguments")
        record = {"expectedRed": args.gate_args[0], "expectedInconclusive": args.gate_args[1], "args": args.gate_args[2:]}
        try:
            record["text"] = Path(args.path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            record["_loadError"] = str(exc)
    else:
        record = _load(args.path)
    arm = args.arm
    if args.gate_kind == "check_mm_feed" and args.gate_args:
        record["_deckLabel"] = args.gate_args[0]
    if args.gate_kind == "check_host_red" and arm == "AUTO":
        from continuity_core_variants import parse_strip, strip_label
        raw = args.gate_args
        if "--core-variant" in raw:
            arm = f"core:{raw[raw.index('--core-variant') + 1]}"
        elif "--strip" in raw:
            arm = strip_label(*parse_strip(raw[raw.index("--strip") + 1]))
        else:
            parser.error("check_host_red needs --core-variant or --strip")
        record["_displayLabel"] = " ".join(raw)
        record["_argvGlReplay"] = raw[raw.index("--gl-replay") + 1] if "--gl-replay" in raw else "off"
    elif args.gate_kind == "check_passg_red" and arm == "AUTO":
        raw = args.gate_args[1:] if args.gate_args and not args.gate_args[0].startswith("--") else args.gate_args
        deck_label = args.gate_args[0] if raw is not args.gate_args else "unknown"
        if "--core-variant" not in raw:
            parser.error("check_passg_red needs --core-variant")
        arm = f"core:{raw[raw.index('--core-variant') + 1]}"
        record["_displayLabel"] = " ".join([deck_label, *raw])
    elif args.gate_kind == "check_paint_control" and args.gate_args:
        record["_deckLabel"] = args.gate_args[0]
    elif args.gate_kind == "check_cc":
        if len(args.gate_args) < 4:
            parser.error("check_cc needs label, wanted status, fixture and control")
        label, wanted, fixture, control, *raw = args.gate_args
        variant = raw[raw.index("--core-variant") + 1] if "--core-variant" in raw else None
        if control == "AUTO":
            control = "null" if "--carry-cover-null" in raw else "red" if variant else "green"
        arm = json.dumps({
            "label": label, "wanted": wanted, "fixture": fixture, "control": control, "variant": variant,
        })
    result = judge(record, args.gate_kind, arm, args.host_kind, rc=args.rc)
    print("\n".join(result.lines))
    if result.candidate is not result.verdict:
        print(f"    candidate: {result.candidate}")
    raise SystemExit(result.exit_code)


if __name__ == "__main__":
    main()
