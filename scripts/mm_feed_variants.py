#!/usr/bin/env python3
"""Probe-only string variants for the Magic Move texture-feed module."""

from __future__ import annotations

VARIANTS: tuple[str, ...] = ("from-only", "no-linger")

_FROM_ONLY_ANCHOR = (
    "      var uploadTargets = record.binding.to ? [targets[0], targets[1]] : [targets[0]];\n"
)
_FROM_ONLY_REPLACEMENT = "      var uploadTargets = [targets[0]];\n"
_NO_LINGER_ANCHOR = "    linger: function(token){ return lingerRefusal(token) === null; },\n"
_NO_LINGER_REPLACEMENT = "    linger: function(token){ return false; },\n"

_TRANSFORMS = {
    "from-only": (_FROM_ONLY_ANCHOR, _FROM_ONLY_REPLACEMENT),
    "no-linger": (_NO_LINGER_ANCHOR, _NO_LINGER_REPLACEMENT),
}


def variant_script(name: str, script: str) -> str:
    """Return a probe-only feed script variant, failing if its anchor moved."""
    if name not in VARIANTS:
        raise ValueError(f"unknown feed variant {name!r}; expected one of {VARIANTS}")
    anchor, replacement = _TRANSFORMS[name]
    count = script.count(anchor)
    if count != 1:
        raise ValueError(
            f"feed variant {name!r}: anchor occurs {count} times, expected exactly once"
        )
    return script.replace(anchor, replacement)
