#!/usr/bin/env python3
"""Probe-only red controls for the live-continuity gates: string-transformed copies of
`PRESERVE_CORE_JS` and a runtime-plan entry stripper. Nothing here is product code; a
variant is injected by a gate process in place of the core, never shipped.

Each variant replaces exact anchors that must each occur exactly once in the core, so a
moved core fails loudly (`ValueError`) instead of silently injecting the core's bytes.
"""
from __future__ import annotations

import copy
import hashlib
import re
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from obed_edom.live_continuity_js import PRESERVE_CORE_JS  # noqa: E402

VARIANTS: tuple[str, ...] = ("stash-any", "wrong-instance", "fifo-reuse")

_POOL_PLANNED_ONLY = "    if (!armedPool && !poolable(v)) return;\n"
_PICK_SRC_ONLY = "      if (c === el || !isCarrySource(c, entry)) return;\n"
_PICK_SAME_ASSET = "      if (c === el || movieKeyFor(c, c.currentSrc || c.src || '') !== entry.movieKey) return;\n"
_PICK_VERDICT = "    const reason = found.length === 0 ? 'absent'\n"

_TRANSFORMS: dict[str, tuple[tuple[str, str], ...]] = {
    # Pool every decoder: neither the plan-asset filter nor the planned-instance filter.
    "stash-any": (("    if (!movieAssetKey(src)) return;\n", ""), (_POOL_PLANNED_ONLY, "")),
    # Pool every plan-asset instance and carry a same-asset candidate that is NOT `src` when one
    # exists (the real pick otherwise): the identity red.
    "wrong-instance": (
        (_POOL_PLANNED_ONLY, ""),
        (_PICK_SRC_ONLY, _PICK_SAME_ASSET),
        (_PICK_VERDICT, "    const wrong = found.filter(function(c) { return !isCarrySource(c, entry); });\n"
                        "    if (wrong.length) return wrong[0];\n" + _PICK_VERDICT),
    ),
    # Pool every plan-asset instance and carry the first same-asset candidate (pool order, then
    # held): the pre-v6 FIFO pick.
    "fifo-reuse": (
        (_POOL_PLANNED_ONLY, ""),
        (_PICK_SRC_ONLY, _PICK_SAME_ASSET),
        (_PICK_VERDICT, "    if (found.length) return found[0];\n" + _PICK_VERDICT),
    ),
}


def variant_core(name: str, core: str = PRESERVE_CORE_JS) -> str:
    """`core` with each of variant `name`'s anchors replaced; `ValueError` unless every anchor
    occurs exactly once."""
    if name not in _TRANSFORMS:
        raise ValueError(f"unknown core variant {name!r}; expected one of {VARIANTS}")
    for anchor, replacement in _TRANSFORMS[name]:
        count = core.count(anchor)
        if count != 1:
            raise ValueError(
                f"core variant {name!r}: anchor {anchor.strip()!r} occurs {count} times, expected exactly once"
            )
        core = core.replace(anchor, replacement)
    return core


def variant_sha(name: str) -> str:
    return hashlib.sha256(variant_core(name).encode()).hexdigest()


def entry_keys(entry: dict[str, Any]) -> set[str]:
    """What a strip KEY may name: the entry's `movieKey` and its `src`/`dst` objectIds (lowercased)."""
    ends = [entry.get("src"), entry.get("dst")]
    keys = [entry.get("movieKey"), *(end.get("objectId") for end in ends if isinstance(end, dict))]
    return {key.lower() for key in keys if isinstance(key, str) and key}


def strip_entries(
    runtime_plan: dict[str, Any], action: str, at_scene: int | None = None, key: str | None = None
) -> dict[str, Any]:
    """A deep copy of `runtime_plan` without its `boundaries` entries of `action` (at `at_scene`, and
    naming `key` as movieKey or src/dst objectId, when given)."""
    def matches(entry: Any) -> bool:
        return (
            isinstance(entry, dict) and entry.get("action") == action
            and (at_scene is None or entry.get("atScene") == at_scene)
            and (key is None or key.lower() in entry_keys(entry))
        )

    boundaries = runtime_plan.get("boundaries") or []
    if not any(matches(entry) for entry in boundaries):
        where = ("" if at_scene is None else f"@{at_scene}") + ("" if key is None else f":{key}")
        raise ValueError(f"runtime plan has no {action}{where} boundary to strip")
    stripped = copy.deepcopy(runtime_plan)
    stripped["boundaries"] = [entry for entry in stripped.get("boundaries") or [] if not matches(entry)]
    return stripped


def parse_strip(value: str) -> tuple[str, int | None, str | None]:
    """`"bridge@8"` -> `("bridge", 8, None)`; `"pin@4:movie2"` -> `("pin", 4, "movie2")`; `"retire"` -> `("retire", None, None)`."""
    match = re.fullmatch(r"([A-Za-z]+)(?:@(\d+)(?::([A-Za-z0-9_-]+))?)?", value.strip())
    if not match:
        raise ValueError(f"invalid strip {value!r}: expected ACTION, ACTION@atScene or ACTION@atScene:KEY")
    action, scene, key = match.groups()
    return action, None if scene is None else int(scene), key


def strip_label(action: str, at_scene: int | None, key: str | None = None) -> str:
    """The red-arm label `strip:ACTION[@SCENE[:KEY]]`."""
    return f"strip:{action}" + ("" if at_scene is None else f"@{at_scene}") + ("" if key is None else f":{key}")
