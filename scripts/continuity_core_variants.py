#!/usr/bin/env python3
"""Probe-only red controls for the live-continuity gates: string-transformed copies of
`PRESERVE_CORE_JS` and a runtime-plan entry stripper. Nothing here is product code; a
variant is injected by a gate process in place of the core, never shipped.

Each variant replaces one exact anchor that must occur exactly once in the core, so a
moved core fails loudly (`ValueError`) instead of silently injecting today's bytes.
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

_TRANSFORMS: dict[str, tuple[str, str]] = {
    "stash-any": ("    if (!movieAssetKey(src)) return;\n", ""),
    "wrong-instance": ("const cand = q.shift();", "const cand = q.pop();"),
    "fifo-reuse": ("const cand = q.shift();", "const cand = q.shift();"),
}


def variant_core(name: str, core: str = PRESERVE_CORE_JS) -> str:
    """`core` with variant `name`'s anchor replaced; `ValueError` unless the anchor occurs exactly once."""
    if name not in _TRANSFORMS:
        raise ValueError(f"unknown core variant {name!r}; expected one of {VARIANTS}")
    anchor, replacement = _TRANSFORMS[name]
    count = core.count(anchor)
    if count != 1:
        raise ValueError(f"core variant {name!r}: anchor {anchor.strip()!r} occurs {count} times, expected exactly once")
    return core.replace(anchor, replacement)


def variant_sha(name: str) -> str:
    return hashlib.sha256(variant_core(name).encode()).hexdigest()


def strip_entries(runtime_plan: dict[str, Any], action: str, at_scene: int | None = None) -> dict[str, Any]:
    """A deep copy of `runtime_plan` without its `boundaries` entries of `action` (at `at_scene` when given)."""
    def matches(entry: Any) -> bool:
        return (
            isinstance(entry, dict) and entry.get("action") == action
            and (at_scene is None or entry.get("atScene") == at_scene)
        )

    boundaries = runtime_plan.get("boundaries") or []
    if not any(matches(entry) for entry in boundaries):
        where = "" if at_scene is None else f"@{at_scene}"
        raise ValueError(f"runtime plan has no {action}{where} boundary to strip")
    stripped = copy.deepcopy(runtime_plan)
    stripped["boundaries"] = [entry for entry in stripped.get("boundaries") or [] if not matches(entry)]
    return stripped


def parse_strip(value: str) -> tuple[str, int | None]:
    """`"bridge@8"` -> `("bridge", 8)`; `"retire"` -> `("retire", None)`."""
    match = re.fullmatch(r"([A-Za-z]+)(?:@(\d+))?", value.strip())
    if not match:
        raise ValueError(f"invalid strip {value!r}: expected ACTION or ACTION@atScene")
    action, scene = match.groups()
    return action, None if scene is None else int(scene)
