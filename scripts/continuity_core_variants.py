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

VARIANTS: tuple[str, ...] = (
    "stash-any",
    "wrong-instance",
    "fifo-reuse",
    "linear-bridge",
    "no-pin-hold",
    "no-gl-clock",
    "overlay-ride",
    "settle-on-stage",
    "no-pause",
    "interim-delay",
    "departure-early-hide",
    "startup-moved-decoder",
)

_POOL_PLANNED_ONLY = "    if (!armedPool && !poolable(v)) return;\n"
_PICK_SRC_ONLY = "      if (c === el || !isCarrySource(c, entry)) return;\n"
_PICK_SAME_ASSET = "      if (c === el || movieKeyFor(c, c.currentSrc || c.src || '') !== entry.movieKey) return;\n"
_PICK_VERDICT = "    const reason = found.length === 0 ? 'absent'\n"
_BRIDGE_PROGRESS = "const progress = easeInEaseOut(bridgeElapsedMs(v, motion) / (1000 * boundary.durationSeconds));"
_HIDDEN_BRIDGE = "    }, 'keepThroughBridge', !!boundary.underArtwork);\n"
_SETTLE_REHOME = "    if (bridge && !entry.underArtwork) {\n"
_POSTER_PAUSE = (
    "    v.__obedPosterHeld = true;\n"
    "    try { v.pause(); } catch (e) {}\n"
)
_INTERIM_SCAN = "    interimScan(roots, performance.now());\n"
_STARTUP_HOLD = """    if (waitForGl && (document.contains(v) || departureInterimPlace(v, boundary))) {
      v.style.opacity = '1';
      return true;
    }
"""
_STARTUP_MOVED_DECODER = """    if (waitForGl && (document.contains(v) || departureInterimPlace(v, boundary))) {
      const screenRect = toScreen(boundary.src.rect);
      if (screenRect) {
        if (v.parentNode !== stage) {
          beginMove(v);
          stage.appendChild(v);
        }
        v.style.left = (screenRect.x + 8) + 'px';
        v.style.top = screenRect.y + 'px';
        v.style.width = screenRect.w + 'px';
        v.style.height = screenRect.h + 'px';
      }
      v.style.opacity = '1';
      return true;
    }
"""
_DEPARTURE_HIDE = """  function rideTransition(v, owner, boundary, rectAt, caller, hidden) {
    // The ride owns the decoder now: end any footprint hold, or it drags the
    // landed decoder back to the source slot once the hash settles (live D2).
    if (v.__obedPinning) {
      v.__obedPinning = false;
      v.__obedPinToken = (v.__obedPinToken || 0) + 1;
    }
    const generation = preserveGeneration;
    const stage = document.getElementById('body') || document.body;
    if (v.__obedMotionPinning === owner) {
      if (!hidden && v.parentNode !== stage) {
        beginMove(v);
        stage.appendChild(v);
      }
      return false;
    }
    v.__obedMotionPinning = owner;
    v.style.position = 'absolute';
    v.style.visibility = 'visible';
    v.style.display = 'block';
    v.style.pointerEvents = 'none';
    v.dataset.obedRemounted = '1';
    const claimed = hidden && feedClaimed(v, boundary);
    const onceAccepted = hidden && !claimed ? posterHold(v, boundary, null, true) : false;
    const ride = {
      boundary: boundary, generation: generation, owner: owner, rectAt: rectAt, caller: caller
    };
    const waitForGl = hidden && (claimed || onceAccepted)
      && deferDepartureHide(v, boundary, owner, rectAt, caller);
    if (waitForGl && (document.contains(v) || departureInterimPlace(v, boundary))) {
      v.style.opacity = '1';
      return true;
    }
    if (hidden) departureHides.delete(v);
    if (v.parentNode !== stage) {
      beginMove(v);
      stage.appendChild(v);
    }
    v.style.opacity = hidden ? '0' : '1';
    if (hidden) v.__obedDepartureHidden = boundary;
    rideFrame(v, ride);
    return true;
  }
"""
_DEPARTURE_EARLY_HIDE = """  function rideTransition(v, owner, boundary, rectAt, caller, hidden) {
    // The ride owns the decoder now: end any footprint hold, or it drags the
    // landed decoder back to the source slot once the hash settles (live D2).
    if (v.__obedPinning) {
      v.__obedPinning = false;
      v.__obedPinToken = (v.__obedPinToken || 0) + 1;
    }
    const generation = preserveGeneration;
    const stage = document.getElementById('body') || document.body;
    if (v.parentNode !== stage) {
      beginMove(v);
      stage.appendChild(v);
    }
    if (v.__obedMotionPinning === owner) return false;
    v.__obedMotionPinning = owner;
    v.style.position = 'absolute';
    v.style.visibility = 'visible';
    v.style.display = 'block';
    v.style.opacity = hidden ? '0' : '1';
    v.style.pointerEvents = 'none';
    v.dataset.obedRemounted = '1';
    function frame() {
      if (v.__obedMotionPinning !== owner) return;
      const scene = currentHashNum();
      if (generation !== preserveGeneration || v.__obedGen === -1
          || v.ended || !document.contains(v) || scene !== boundary.atScene - 1) {
        v.__obedMotionPinning = false;
        return;
      }
      const screenRect = toScreen(rectAt());
      if (!screenRect) {
        noteStageMapUnavailable(caller);
      } else {
        v.style.left = screenRect.x + 'px';
        v.style.top = screenRect.y + 'px';
        v.style.width = screenRect.w + 'px';
        v.style.height = screenRect.h + 'px';
      }
      requestAnimationFrame(frame);
    }
    if (hidden && !feedClaimed(v, boundary)) posterHold(v, boundary, null, true);
    frame();
    return true;
  }
"""

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
    # Restore the pre-easing linear bridge progress on the product clock: the P2 carry-cover red.
    "linear-bridge": (
        (
            _BRIDGE_PROGRESS,
            "const progress = Math.min(1, Math.max(0, bridgeElapsedMs(v, motion) / (1000 * boundary.durationSeconds)));",
        ),
    ),
    # Never hold a pin through its transition scene: only bridges ride it on the stage (the pre-pin-hold core), so a
    # pin's decoder sits in the source layer the player hides for the move.
    "no-pin-hold": (("  function keepThroughPin(v) {\n", "  function keepThroughPin(v) {\n    return false;\n"),),
    # Keep the requestAnimFrame hook but never stamp a GL loop start: every bridge takes the fallback, today's
    # `performance.now()` clock after the GL_CLOCK_WAIT_MS hold. The D1 carry-cover red.
    "no-gl-clock": (("    departure.gl = {date: Date.now(), perf: performance.now()};\n", ""),),
    "overlay-ride": ((_HIDDEN_BRIDGE, "    }, 'keepThroughBridge', false);\n"),),
    "settle-on-stage": ((_SETTLE_REHOME, "    if (bridge) {\n"),),
    "no-pause": ((_POSTER_PAUSE, "    v.__obedPosterHeld = true;\n"),),
    "interim-delay": ((
        _INTERIM_SCAN,
        "    const observedAt = performance.now();\n"
        "    requestAnimationFrame(function() {\n"
        "      interimScan(roots.filter(function(r) { return r.isConnected; }), observedAt);\n"
        "    });\n",
    ),),
    "departure-early-hide": ((_DEPARTURE_HIDE, _DEPARTURE_EARLY_HIDE),),
    "startup-moved-decoder": ((_STARTUP_HOLD, _STARTUP_MOVED_DECODER),),
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
